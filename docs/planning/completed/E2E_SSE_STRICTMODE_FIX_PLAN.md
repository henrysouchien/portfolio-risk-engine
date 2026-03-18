# Fix: NormalizerBuilderPanel StrictMode Stream Invalidation

## Context

3 of 18 onboarding E2E tests fail because `NormalizerBuilderPanel`'s SSE stream is killed by React 18 StrictMode's mount→unmount→remount cycle. The SSE mock body is delivered correctly (confirmed via `page.evaluate`), but the component's `for await` loop never processes events.

## Root Cause

React 18 `StrictMode` (`frontend/packages/ui/src/index.tsx:21`) replays effects: mount → cleanup → remount. In `NormalizerBuilderPanel`:

1. **First mount**: Effect at line 236 fires. `initialPromptSentRef.current` is `false` → set to `true`, calls `sendMessage()`. Stream starts with `streamId=1`, `streamSequenceRef=1`. `fetch()` is awaited (async).
2. **StrictMode cleanup**: Effect at line 117 fires. `streamSequenceRef.current` incremented to `2`.
3. **StrictMode remount**: Effect at line 236 fires again. `initialPromptSentRef.current` is still `true` (refs persist across StrictMode cycles) → **early return, no new stream started**.
4. Original stream's `fetch` resolves, first SSE event arrives. Guard at line 151: `streamSequenceRef.current (2) !== streamId (1)` → **loop breaks**.
5. `finally` block at line 230: `2 !== 1` → `isStreaming` NOT cleared.
6. **Dead state**: `isStreaming=true` forever, no active stream, no recovery path.

## Fix (3 changes)

### Change 1: Reset `initialPromptSentRef` in cleanup

**File**: `NormalizerBuilderPanel.tsx` line 117-122

```typescript
// Before
useEffect(() => () => {
  streamSequenceRef.current += 1;
  if (activationTimeoutRef.current !== null) {
    window.clearTimeout(activationTimeoutRef.current);
  }
}, []);

// After
useEffect(() => () => {
  streamSequenceRef.current += 1;
  initialPromptSentRef.current = false;
  if (activationTimeoutRef.current !== null) {
    window.clearTimeout(activationTimeoutRef.current);
  }
}, []);
```

**Why**: Allows the StrictMode remount's effect to re-send the initial prompt. Without this, the ref stays `true` and the remount skips `sendMessage()` entirely.

### Change 2: Add AbortController to cancel stale fetches

**File**: `NormalizerBuilderPanel.tsx` — new ref + pass to sendMessageStream + abort in cleanup

```typescript
// New ref (after line 79)
const abortControllerRef = useRef<AbortController | null>(null);

// In sendMessage (before the fetch, around line 149)
// Abort any previous stream's fetch
abortControllerRef.current?.abort();
abortControllerRef.current = new AbortController();

// In cleanup effect (line 117-122)
useEffect(() => () => {
  streamSequenceRef.current += 1;
  initialPromptSentRef.current = false;
  abortControllerRef.current?.abort();
  if (activationTimeoutRef.current !== null) {
    window.clearTimeout(activationTimeoutRef.current);
  }
}, []);
```

**File**: `GatewayClaudeService.ts` — accept optional `AbortSignal` in `sendMessageStream`

```typescript
// sendMessageStream signature (line 102)
async* sendMessageStream(
  message: string,
  history: ChatMessage[],
  portfolioName?: string,
  signal?: AbortSignal,
): AsyncGenerator<ClaudeStreamChunk, void, unknown> {

// Pass signal to fetch (line 117)
const response = await fetch(`${this.proxyUrl}/chat`, {
  method: 'POST',
  credentials: 'include',
  headers: { 'Accept': 'text/event-stream', 'Content-Type': 'application/json' },
  body: JSON.stringify({ messages, context: { channel: 'web', ...(portfolioName ? { portfolio_name: portfolioName } : {}) } }),
  signal,
});
```

**File**: `NormalizerBuilderPanel.tsx` — pass signal when calling sendMessageStream (line 150)

```typescript
for await (const chunk of service.sendMessageStream(
  content, priorHistory, undefined, abortControllerRef.current?.signal
)) {
```

**Why**: Cancels the stale stream's `fetch()` at the network level during cleanup, instead of just ignoring its events client-side. Prevents a wasted request to the real gateway in development.

### Change 3: Guard the catch block against stale streams

**File**: `NormalizerBuilderPanel.tsx` — line 220-228

```typescript
// Before
} catch (error) {
  const errorMessage = error instanceof Error ? error.message : 'Builder request failed.';
  setMessages(current => {
    const withoutEmptyAssistant = current.filter(entry => {
      return entry.id !== assistantMessageId || entry.content.trim().length > 0;
    });
    return [...withoutEmptyAssistant, buildMessage('error', errorMessage)];
  });
  setStatusText(null);
}

// After
} catch (error) {
  if (streamSequenceRef.current !== streamId) {
    return; // Stale stream — don't touch the UI
  }
  // Ignore AbortError from cancelled fetches (cleanup or superseded stream)
  if (error instanceof DOMException && error.name === 'AbortError') {
    return;
  }
  const errorMessage = error instanceof Error ? error.message : 'Builder request failed.';
  setMessages(current => {
    const withoutEmptyAssistant = current.filter(entry => {
      return entry.id !== assistantMessageId || entry.content.trim().length > 0;
    });
    return [...withoutEmptyAssistant, buildMessage('error', errorMessage)];
  });
  setStatusText(null);
}
```

**Why**: If stream 1's fetch fails (e.g., network error or abort) after stream 2 has started, the catch block would otherwise append an error message and clear `statusText` on stream 2's UI. The sequence guard and AbortError check prevent this.

### Change 4: Add sequence check after `respondToApproval` await

**File**: `NormalizerBuilderPanel.tsx` — line 178-193

The auto-approval branch awaits `respondToApproval()` (line 181) then calls `setStatusText()` (line 182) with no post-await sequence check. If cleanup/remount happens while the approval POST is in-flight, the stale stream's `setStatusText` would mutate the live stream's UI.

```typescript
// Before (line 178-193)
if (chunk.type === 'tool_approval_request') {
  if (chunk.tool_name.startsWith('normalizer_')) {
    setStatusText(`Approving ${chunk.tool_name}...`);
    await service.respondToApproval(chunk.tool_call_id, chunk.nonce, true);
    setStatusText(`Running ${chunk.tool_name}...`);
  } else {
    // ... manual approval
  }
  continue;
}

// After
if (chunk.type === 'tool_approval_request') {
  if (chunk.tool_name.startsWith('normalizer_')) {
    setStatusText(`Approving ${chunk.tool_name}...`);
    await service.respondToApproval(chunk.tool_call_id, chunk.nonce, true);
    if (streamSequenceRef.current !== streamId) {
      break;
    }
    setStatusText(`Running ${chunk.tool_name}...`);
  } else {
    // ... manual approval (unchanged — blocked by pending UI, not async)
  }
  continue;
}
```

**Why**: The `await respondToApproval()` yields control. If cleanup fires during the await (StrictMode or genuine unmount), the sequence will have changed. The guard prevents the stale stream from writing to the live UI.

## Post-fix StrictMode Sequence

1. First mount: `initialPromptSentRef=false` → set `true`, call `sendMessage`, `streamId=1`, `streamSequenceRef=1`, `abortControllerRef` created
2. Cleanup: `streamSequenceRef=2`, `initialPromptSentRef=false`, `abortControllerRef.abort()` → stream 1's fetch aborted
3. Remount: `initialPromptSentRef=false` → set `true`, call `sendMessage`, `streamId=3`, `streamSequenceRef=3`, new `abortControllerRef`
4. Stream 1: fetch aborted → `AbortError` caught → sequence guard `3 !== 1` → return (no UI effect)
5. Stream 2: processes all events normally. Guard `3 === 3` → continues. Finally `3 === 3` → clears `isStreaming`

## Edge Cases

- **`activationTriggeredRef`**: Stream 1 is aborted before processing events. Stream 2 correctly triggers activation.
- **`messagesRef`**: Stream 2 called with `history=[]`, starts fresh.
- **Production (no StrictMode)**: Cleanup only fires on genuine unmount. `AbortController` cancels any in-flight fetch (correct). `initialPromptSentRef` reset allows re-send on genuine remount (correct).
- **User sends follow-up message**: The panel blocks `sendMessage` while `isStreaming` is true (line 126) and disables input/send controls (lines 377, 388). The `AbortController` abort-before-replace is a safety net for the cleanup path, not for user-initiated supersession.

## Files to Modify

| File | Changes |
|------|---------|
| `frontend/packages/ui/src/components/onboarding/NormalizerBuilderPanel.tsx` | Add `abortControllerRef`, reset `initialPromptSentRef` in cleanup, abort in cleanup + sendMessage, guard catch block, pass signal |
| `frontend/packages/chassis/src/services/GatewayClaudeService.ts` | Add optional `signal` param to `sendMessageStream`, pass to `fetch` |

## Verification

1. `cd frontend && npx vitest run` — no regressions
2. `npx playwright test --config e2e/playwright.config.ts --reporter=list` — expect 18/18 pass
3. Specifically verify the 3 previously failing tests:
   - `normalizer-builder.spec.ts:72` "Full normalizer builder flow"
   - `csv-import-errors.spec.ts:106` "Gateway SSE error in builder"
   - `csv-import-errors.spec.ts:166` "Tool approval POST failure"

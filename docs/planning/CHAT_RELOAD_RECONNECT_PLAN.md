# Chat Reload / Clear Thread — Abort & Cleanup Fix

Bug F2: Reload and clear buttons do not abort in-flight streams, leaving zombie requests that race with new messages.

## Problem

Clicking "Reload thread" or "Clear thread" in the chat only clears local React state (messages, status, errors, artifacts). It does not:

1. Abort any in-flight streaming request, leaving a zombie stream that writes into the now-cleared message array (ghost text).
2. The `sendMessageStream()` call at `usePortfolioChat.ts:663` never passes the `AbortController.signal` to the service, so even `stop()` only checks the signal inside the JS for-await loop rather than actually cancelling the underlying `fetch`.
3. After abort, the old request's `catch`/`finally` blocks (lines 862-889) run unconditionally and can clobber state set by a new request started after reload.

Users expect "Reload thread" to produce a genuinely clean slate with no lingering stream side-effects.

## Root Cause Analysis

### 1. AbortSignal not wired to fetch (Finding 1)

`sendMessage()` creates an `AbortController` at line 601 and stores it in `abortControllerRef`, but the `sendMessageStream()` call at line 663 only passes 4 arguments:

```ts
gatewayService.sendMessageStream(trimmed, messages, portfolioDisplayName, 'chat');
```

`GatewayClaudeService.sendMessageStream()` accepts `signal?: AbortSignal` as the 5th parameter (`:135`) and forwards it to `fetch()` at `:162`. Without it, the abort controller only works via the JS-level `abortController.signal.aborted` check inside the for-await loop (`:684`). The actual HTTP connection stays open, and on the backend the per-user stream lock (`:174-176`) remains held until the disconnect watcher (`:264-272`, polling every 2s) detects the closed connection. This creates a ~2s window where a new `sendMessage()` will hit the 409 "stream already active" lock.

### 2. Stale callback race conditions (Finding 2)

The `sendMessage` closure captures `assistantMessageId` via lexical scope. After `reload()` aborts the old request:

- The old `catch` block (`:862-883`) runs and calls `setMessages(prev => prev.filter(...))` and `setMessages(prev => [...prev, errorMessage])` -- these operate on the *current* state, which reload just cleared to `[]`. The filter is a no-op, but the error-message append re-introduces a stale error message into the fresh empty conversation.
- The old `finally` block (`:884-889`) sets `abortControllerRef.current = null`, which can null out a *new* controller if `sendMessage` was called immediately after reload.

**Backend 409 risk**: The backend proxy acquires a per-user `asyncio.Lock` at `:178` before streaming. `release_resources()` at `:183-190` only releases when the stream generator finishes. The disconnect watcher polls every 2s (`:265`). If the user reloads and immediately sends a new message, the new `/chat` POST can arrive before the backend detects the old disconnect, hitting the `user_lock.locked()` check at `:175` and returning 409.

### 3. Query invalidation is wrong mechanism (Finding 3)

The original plan proposed invalidating the `chatContextKey(currentPortfolio?.id)` React Query cache on reload. This is incorrect:

- `PortfolioManager.getPortfolioContext()` (`:935-956`) is a **local derivation** that extracts fields from the `Portfolio` object already in memory (`portfolioValue`, `holdingsCount`, `topHoldings`, `accountType`, `statementDate`). It makes no network request.
- `sendMessage()` at line 663 sends `messages` + `portfolioDisplayName` to the gateway. The `chatContext` query result is not passed to the stream call at all.
- Invalidating this query triggers an unnecessary re-derivation of local data. The real value of reload is: abort stream + clear UI state + allow a fresh send.

**Conclusion**: Remove query invalidation from the plan entirely. No `useQueryClient` import needed.

### 4. clearMessages vs reload distinction (Finding 4)

The UI distinguishes two actions in `ChatCore.tsx`:
- "Reload thread" (`:1552`) calls `reload()` -- fresh start
- "Clear thread" (`:1559`) calls `clearMessages()` -- erase messages

Both need abort behavior (prevent ghost text from in-flight stream), but they should remain separate callbacks. The current code already has them as separate functions (`:1015-1022` and `:1030-1036`). Both need the abort logic added.

## Fix Strategy

Four changes, all in `usePortfolioChat.ts`. No service class changes. No backend changes. No new components.

1. **Wire AbortSignal to sendMessageStream** so abort actually cancels the fetch.
2. **Add a generation counter** to guard against stale catch/finally callbacks from aborted requests.
3. **Add abort to reload() and clearMessages()** to kill in-flight streams on reset.
4. **Guard respondToApproval() catch block** with the same generation counter to prevent stale approval failures from clobbering clean thread state after reload/clear.

## Implementation Steps

### Step 1: Add generation counter ref

After `abortControllerRef` declaration (line 260), add a request generation counter:

```ts
const requestGenerationRef = useRef(0);
```

This counter increments on every `sendMessage()` call and on every `reload()`/`clearMessages()` invocation. Async callbacks in `sendMessage()` and `respondToApproval()` capture the generation at call start and bail out if it no longer matches, preventing stale state writes.

### Step 2: Wire signal to sendMessageStream and guard with generation

In `sendMessage()`, update the request lifecycle setup and stream call:

**At line 601** (after creating AbortController), increment the generation and capture it:

```ts
const abortController = new AbortController();
abortControllerRef.current = abortController;
requestGenerationRef.current += 1;
const thisGeneration = requestGenerationRef.current;
```

**At line 663** (the `sendMessageStream` call), pass the signal as the 5th argument:

```ts
const streamGenerator = gatewayService.sendMessageStream(
  trimmed,
  messages,
  portfolioDisplayName,
  'chat',
  abortController.signal,                                                        // Wire abort signal to fetch
);
```

**At lines 832-860** (success/completion path after the streaming loop), guard against stale generation AND aborted signal. Two abort scenarios exit the loop without throwing:

1. `reload()`/`clearMessages()` abort the controller AND bump generation -- caught by the generation check.
2. `stop()` aborts the controller but does NOT bump generation (it keeps the same generation so the user can continue the conversation). The loop breaks at line 684 via the `abortController.signal.aborted` check, then falls through to the completion block. Without an abort-signal check here, a stopped stream would be finalized as "Response complete" and could open artifacts from partial output.

Both guards are needed. Add them at the top of the completion block:

```ts
      // ═══════════════════════════════════════════════════════════════════════════════
      // 🎯 STREAMING COMPLETION - Finalize successful response
      // ═══════════════════════════════════════════════════════════════════════════════
      
      // Stale request -- a newer sendMessage or reload has taken over
      if (requestGenerationRef.current !== thisGeneration) return;

      // Aborted by stop() -- the loop exited via break, not an error.
      // stop() already set status to 'ready' and cleaned up streaming state.
      // Do NOT finalize as "Response complete" or open artifacts from partial output.
      if (abortController.signal.aborted) return;

      // Parse UI blocks from completed response
      const { cleanContent, segments } = parseMessageContent(accumulatedContent);
      // ... rest of completion block unchanged
```

**At line 862** (catch block), guard against stale generation AND handle `AbortError` from intentional aborts. When the `AbortSignal` is wired to `fetch`, aborting throws `AbortError` from the network layer. Both `stop()` and `reload()` are intentional aborts -- they must not surface as error state:

```ts
} catch (error) {
  // Stale request -- a newer sendMessage or reload has taken over
  if (requestGenerationRef.current !== thisGeneration) return;

  // Intentional abort (stop() or reload()) -- not an error
  if (error instanceof DOMException && error.name === 'AbortError') return;

  const chatError = categorizeError(error);
  // ... rest of catch block unchanged
```

**At line 884** (finally block), same generation guard:

```ts
} finally {
  // Only clean up shared refs if this is still the active request
  if (requestGenerationRef.current === thisGeneration) {
    setIsStreaming(false);
    setCurrentStreamingMessageId(null);
    abortControllerRef.current = null;
    setPendingApproval(null);
  }
}
```

### Step 3: Add abort to reload()

Replace `reload()` at lines 1015-1022:

```ts
const reload = useCallback(() => {
  // Abort any in-flight stream and bump generation to discard its callbacks
  if (abortControllerRef.current) {
    abortControllerRef.current.abort();
    abortControllerRef.current = null;
  }
  requestGenerationRef.current += 1;
  setMessages([]);
  setChatStatus({ state: 'ready' });
  setStreamError(null);
  setIsStreaming(false);
  setCurrentStreamingMessageId(null);
  setPendingApproval(null);
  resetArtifact();
  frontendLogger.user.action('reloadConversation', 'usePortfolioChat');
}, [resetArtifact, setPendingApproval]);
```

Key differences from original:
- Aborts in-flight controller and nulls the ref.
- Bumps `requestGenerationRef` so old catch/finally become no-ops.
- Explicitly resets `isStreaming` and `currentStreamingMessageId` (the old `reload()` did not, relying on `finally` -- which races).

### Step 4: Add abort to clearMessages()

Replace `clearMessages()` at lines 1030-1036 with the same abort pattern but no logging:

```ts
const clearMessages = useCallback(() => {
  // Abort any in-flight stream and bump generation to discard its callbacks
  if (abortControllerRef.current) {
    abortControllerRef.current.abort();
    abortControllerRef.current = null;
  }
  requestGenerationRef.current += 1;
  setMessages([]);
  setChatStatus({ state: 'ready' });
  setStreamError(null);
  setIsStreaming(false);
  setCurrentStreamingMessageId(null);
  setPendingApproval(null);
  resetArtifact();
}, [resetArtifact, setPendingApproval]);
```

### Step 5: Guard respondToApproval() catch block with generation counter

`respondToApproval()` (lines 401-432) has an unguarded async `catch` that writes `setStreamError` and `setChatStatus` after the `await gatewayService.respondToApproval()` POST. If the user approves/denies a tool call and then clicks "Reload thread" (`:1552`) or "Clear thread" (`:1559`) before the approval POST settles, a late failure can repopulate stale error state in the now-clean conversation.

The fix captures `requestGenerationRef.current` at call start and checks it in the catch block before writing state:

```ts
const respondToApproval = useCallback(
  async (approved: boolean, allowToolType?: boolean) => {
    const activeApproval = pendingApprovalRef.current;
    if (!activeApproval) {
      return;
    }

    if (chatBackend !== 'gateway') {
      throw new Error('Legacy chat backend was removed. Set VITE_CHAT_BACKEND=gateway.');
    }

    // Capture generation so reload/clear can invalidate this callback
    const thisGeneration = requestGenerationRef.current;

    try {
      await gatewayService.respondToApproval(
        activeApproval.toolCallId,
        activeApproval.nonce,
        approved,
        allowToolType,
      );
      // Guard: reload/clear may have fired while the POST was in flight
      if (requestGenerationRef.current !== thisGeneration) return;
      setPendingApproval(null);
    } catch (error) {
      // Stale request -- reload/clear has taken over, discard the error
      if (requestGenerationRef.current !== thisGeneration) return;

      const err = error instanceof Error ? error : new Error(String(error));
      setStreamError(err);
      setChatStatus({
        state: 'error',
        message: 'Tool approval failed',
        error: categorizeError(err),
      });
      throw err;
    }
  },
  [chatBackend, categorizeError, gatewayService, setPendingApproval]
);
```

Key changes from the current code:
- Captures `thisGeneration` before the await.
- Guards both the success path (`setPendingApproval(null)`) and the catch path (`setStreamError`/`setChatStatus`) with a generation check. A stale success write is harmless (clearing an already-null approval), but guarding it is defensive-correct and consistent with the `sendMessage` pattern.
- The `throw err` at the end of catch only executes if the generation still matches, which is correct — the caller (`ChatCore.tsx:667`) wraps this in a try/catch, and if generation is stale the caller's error handling is irrelevant.

### Step 6: Update existing test assertions

The existing test at line 166 asserts `sendMessageStream` is called with 4 args:

```ts
expect(mockGatewayService.sendMessageStream).toHaveBeenCalledWith(
  'Explain the risk.', [], 'Growth Portfolio', 'chat',
);
```

Update to expect the AbortSignal as the 5th argument:

```ts
expect(mockGatewayService.sendMessageStream).toHaveBeenCalledWith(
  'Explain the risk.', [], 'Growth Portfolio', 'chat',
  expect.any(AbortSignal),
);
```

## Testing

### Automated tests (new, in `usePortfolioChat.test.tsx`)

1. **AbortSignal propagation**: Verify `sendMessageStream` receives an `AbortSignal` as the 5th argument on every call.

2. **Mid-stream reload aborts stream and produces clean state**: Start a stream with a gate (deferred promise), verify streaming state, call `reload()`, resolve the gate, verify: messages empty, status ready, no error message reintroduced.

3. **Mid-stream clearMessages aborts stream**: Same as above but with `clearMessages()`.

4. **Stale catch does not reintroduce error message after reload**: Start a stream that will throw, call `reload()` before the throw resolves, verify the error message from the old request does not appear in the fresh conversation.

5. **Stale finally does not null new controller**: Start stream A (gated), call `reload()`, immediately start stream B, resolve gate A, verify `abortControllerRef` still points to stream B's controller (observable via `stop()` still working on stream B).

6. **Stale success path does not clobber fresh state after reload**: Start a stream with a gate, call `reload()` (clears messages), resolve the gate so the old stream completes normally (no error). Verify: `setChatStatus` was not called with 'Response complete' after reload, `openArtifact` was not called, messages remain empty. This covers the success-path generation guard (lines 832-860).

7. **AbortError from stop() does not surface as error**: Start a stream that is blocked on a gated chunk. Call `stop()` (which aborts the controller). Verify: no error message appended, no `streamError` set, status is 'ready' (from `stop()`), not 'error'. This covers the `AbortError` guard in the catch block (when wired signal causes fetch to throw `AbortError`).

8. **Stale approval failure does not clobber clean thread after reload**: Set up a pending approval (mock `pendingApprovalRef.current`), call `respondToApproval(true)` with a gated `gatewayService.respondToApproval` that defers settlement. While the POST is in flight, call `reload()`. Then reject the gated promise (simulating a network error). Verify: `setStreamError` was NOT called after reload, `setChatStatus` was NOT set to 'error', messages remain empty, status is 'ready'. This covers the generation guard added in Step 5.

9. **Rapid reload+send with 409 resilience**: This is a manual/integration test -- the automated mock does not have the backend lock. Document as manual test.

10. **stop() does not finalize as "Response complete" or open artifacts**: Start a stream that yields a text_delta containing an artifact block (e.g. `:::artifact ... :::`), then gate further chunks. Call `stop()` (which aborts the controller). Resolve the gate so the loop exits via the `break` at the abort check. Verify: `setChatStatus` was NOT called with 'Response complete' after `stop()`, `openArtifact` was NOT called (partial artifact must not auto-open), status remains 'ready' (set by `stop()` itself). This covers the `abortController.signal.aborted` guard in the completion block -- distinct from test 7 which covers the catch-block `AbortError` path.

### Manual tests

- Open chat, send a message, click "Reload thread". Verify messages clear immediately and no ghost text appears.
- Start a streaming response, click "Reload thread" mid-stream. Verify stream stops, messages clear, no error toast.
- Start a streaming response, click "Clear thread" mid-stream. Same verification.
- Reload mid-stream, immediately send a new message. Verify the new message succeeds without 409 error (the abort + signal cancellation should release the backend lock before the new request arrives; if not, the 2s disconnect poll is the worst-case delay).

## Files Changed

| File | Change |
|------|--------|
| `frontend/packages/connectors/src/features/external/hooks/usePortfolioChat.ts` | Add `requestGenerationRef`, wire signal to `sendMessageStream`, generation guards + abort-signal guard in completion/catch/finally, abort in `reload()` and `clearMessages()` |
| `frontend/packages/connectors/src/features/external/__tests__/usePortfolioChat.test.tsx` | Update existing signal assertion, add 8 new test cases for mid-stream abort, stale-callback races (including success path and approval race), AbortError suppression, and stop()-completion guard |

## Risks & Rollback

- **Low risk**: All changes are additive guards within one hook. The generation counter pattern is a standard React concurrent-safe technique. Wiring the signal to fetch is the intended API usage that was simply missing.
- **409 edge case**: If the user reloads and sends a new message within ~2s, the backend disconnect watcher may not have released the lock yet. The fetch abort + signal wiring mitigates this (the browser closes the TCP connection immediately on abort, which the upstream httpx response detects faster than the 2s poll). If this proves insufficient, a frontend retry-after-409 with a short delay could be added as a follow-up, but this is unlikely to be needed.
- **Rollback**: Revert changes to the two files. No schema, API, or state shape changes.

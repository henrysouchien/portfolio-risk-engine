# E2E SSE Builder Test Failures — Debug Notes

## Status
3 of 18 onboarding E2E tests fail. All 3 involve the NormalizerBuilderPanel consuming a mocked SSE stream.

## Failing Tests

| Test | File | Line | Timeout |
|------|------|------|---------|
| Full normalizer builder flow → re-preview → import → completion | `normalizer-builder.spec.ts` | 72 | 15s |
| Gateway SSE error in builder shows error message | `csv-import-errors.spec.ts` | 106 | 5s |
| Tool approval POST failure during builder shows chat error | `csv-import-errors.spec.ts` | 166 | 10s |

## Symptom

The builder panel opens. The initial user prompt is visible. The status text shows "Claude is analyzing the CSV..." (set at `NormalizerBuilderPanel.tsx:145`). The SSE events from the mock **never appear** in the messages. The builder stays in `isStreaming=true` indefinitely until timeout.

## What Works

- `page.route('**/api/gateway/chat')` **does** intercept the POST request (confirmed via `[E2E-gateway] Intercepted chat: POST http://localhost:3000/api/gateway/chat`)
- `route.fulfill()` with `contentType: 'text/event-stream'` **does** deliver a readable `response.body` (confirmed via `page.evaluate` manual fetch — 13 SSE events parsed correctly)
- Tests that use `mockGateway` with a simple stream (text_delta + DONE, no tool calls) **pass** (e.g., "Build with AI stages CSV and opens builder panel")
- Tests that don't involve the gateway at all **pass** (15/18)

## Root Cause Hypothesis

The `GatewayClaudeService.sendMessageStream()` generator yields events from `parseSSE(response.body)` inside a `for await` loop in `NormalizerBuilderPanel.sendMessage()` (line 150). The loop processes events and updates React state via `setMessages()`, `setStatusText()`, etc.

**The SSE body is delivered correctly but the `for await` loop in the React component doesn't consume the events.**

Possible causes (ordered by likelihood):

### 1. Component remount kills the stream (MOST LIKELY)

`NormalizerBuilderPanel` uses `streamSequenceRef` to guard against stale streams:
```typescript
// Line 151
if (streamSequenceRef.current !== streamId) {
  break;
}
```

If the component unmounts and remounts between `sendMessage()` being called and the first event arriving, the cleanup effect (line 117-122) increments `streamSequenceRef.current`, causing the guard to break the loop before any events are processed.

This would explain why:
- Simple streams (text + DONE) work — they complete before any remount
- Complex streams with multiple events fail — React state updates from `setMessages()` trigger parent re-renders that may unmount/remount the builder

The key React state flow: when `handleBuildWithAI()` (CsvImportStep.tsx:161) sets `showBuilder=true` and `needsNormalizerData` state, the `NormalizerBuilderPanel` mounts and immediately calls `sendMessage()` via the `useEffect` at line 236. If `CsvImportStep` re-renders after `stage-csv` completes (e.g., `setStagedFilePath`/`setStagedFilename` state updates), the `showBuilder && stagedFilePath && needsNormalizerData` condition (line 344) may briefly become false and then true again, causing an unmount/remount cycle.

### 2. `route.fulfill()` body consumed synchronously

Playwright's `route.fulfill()` may deliver the entire body as a single synchronous chunk. `parseSSE()` reads with `reader.read()` in a while loop. If all bytes arrive in one `read()` call, the parsing is synchronous and all 13 events are yielded in a tight loop.

The `for await` consumer in `sendMessage()` calls `setMessages()` / `setStatusText()` for each event. These are React state updates that are **batched** in React 18. The tight synchronous event loop might conflict with React's batching — all state updates may be deferred until after the loop, meaning intermediate renders never happen.

This alone shouldn't prevent the final state from being visible, but combined with cause #1, it could prevent the "normalizer is now active" text from ever being set if the loop breaks early.

### 3. `response.body` null in production bundle

The `GatewayClaudeService.sendMessageStream()` checks `if (!response.body)` at line 136 and yields an error if null. If `route.fulfill()` somehow produces a `null` body in the production Vite bundle (e.g., different response constructor behavior), the stream would short-circuit.

This is **unlikely** given our `page.evaluate` test proved the body exists, but worth checking with a browser console assertion.

## Diagnostic Approach

### Step 1: Add temporary console logging to NormalizerBuilderPanel

Add `console.log` statements at key points:
- Before `for await` loop (line 150): log `streamId`, `streamSequenceRef.current`
- Inside the loop (line 155): log each `chunk.type`
- At the `streamSequenceRef` guard (line 151): log if breaking
- In the cleanup effect (line 117): log when incrementing
- In the catch block (line 220): log the error

Run the failing test with `page.on('console')` listener to capture these logs.

### Step 2: Check for remount

Add `console.log('NormalizerBuilderPanel MOUNT')` in the component body (before the first `useState`). If it fires twice, that confirms cause #1.

### Step 3: Test with delayed stream delivery

Instead of `route.fulfill()`, use `page.addInitScript` to monkey-patch `window.fetch` and return a `ReadableStream` that drip-feeds events with 100ms delays. This would test whether synchronous delivery (cause #2) is the issue.

We tried this approach earlier with 50ms delays but it also failed — the addInitScript approach had its own issues (the monkey-patched fetch may not persist correctly across React's fast update cycles).

### Step 4: Verify with headed mode

Run `npx playwright test --headed -g "Full normalizer" --retries=0` and visually inspect:
- Does the builder panel flash/disappear/reappear?
- Does the status text change at all after "Claude is analyzing..."?
- Is there a JavaScript error in the browser console?

## Files Involved

| File | Role |
|------|------|
| `e2e/helpers/gateway-mock.ts` | SSE mock builder + route handlers |
| `e2e/tests/normalizer-builder.spec.ts:72` | Full flow test |
| `e2e/tests/csv-import-errors.spec.ts:106,166` | Error flow tests |
| `frontend/packages/chassis/src/services/GatewayClaudeService.ts:102-147` | SSE fetch + parseSSE |
| `frontend/packages/ui/src/components/onboarding/NormalizerBuilderPanel.tsx:124-234` | Stream consumer loop |
| `frontend/packages/ui/src/components/onboarding/CsvImportStep.tsx:161-180` | Builder mount trigger |

## Fix Strategies

### A. Fix the remount (if cause #1 confirmed)
Stabilize the `CsvImportStep` rendering so `showBuilder && stagedFilePath && needsNormalizerData` never flickers. Options:
- Move the builder mount condition to a `useMemo`
- Add a `key` prop to prevent remount
- Defer `sendMessage()` with a small timeout after mount

### B. Use addInitScript with chunked delivery (if cause #2)
Monkey-patch `window.fetch` at the page level to return a `ReadableStream` that yields events one at a time with delays. Must be registered before `page.goto()`.

### C. Skip SSE-dependent assertions (pragmatic)
Mark the 3 tests as `test.skip()` or `test.fixme()` with a comment, and verify the builder works via integration tests or manual testing. The 15 passing tests already cover the core onboarding flow.

# Tool-Call Approval Expiration UX Fix

## Context

When the upstream agent-gateway's tool-call approval TTL expires, clicking "Approve" returns a raw error string: `Approval failed (404): {"error":"Unknown tool_call_id"}`. This is confusing — the user doesn't know the approval expired, and the stale card lingers with useless Approve/Deny buttons.

**Upstream fix** (TTL removal) is tracked separately in `AI-excel-addin/docs/TODO.md`. This plan covers **client-side graceful handling** in risk_module: proxy error enrichment + frontend UX.

**Sidebar gap**: The `ChatMargin` component is a summary strip, not a chat surface — it has no message rendering or approval flow. Both actual chat surfaces (modal `AIChat` + fullscreen `ChatInterface`) share `ChatCore`, which has the approval card. The sidebar gap noted in the TODO is a separate feature request (showing a notification badge on `ChatMargin` when an approval is pending), not in scope here.

---

## Changes

### 1. Proxy: structured error responses on tool-approval failures

**File:** `app_platform/gateway/proxy.py` (lines 344-350)

Currently returns `text/plain` with raw upstream body. Change to return structured JSON with an `error_code` field so the frontend can branch without string-matching.

```python
# Replace lines 344-350
body_text = response.text
if response.status_code >= 400:
    error_code = "approval_expired" if response.status_code == 404 else "approval_failed"
    try:
        upstream_body = response.json()
        if not isinstance(upstream_body, dict):
            upstream_body = {"detail": str(upstream_body)}
    except (ValueError, TypeError):
        upstream_body = {"detail": body_text or "Gateway approval failed"}

    # Proxy-owned fields go last to prevent upstream overwrite
    result = {**upstream_body, "error_code": error_code, "upstream_status": response.status_code}
    return JSONResponse(content=result, status_code=response.status_code)
```

Key guards (from Codex R1 finding #3):
- `isinstance(upstream_body, dict)` check — non-object JSON (e.g. a bare string/array) won't crash the `**` spread.
- Proxy-owned fields (`error_code`, `upstream_status`) placed **after** the spread so upstream data cannot overwrite them.

### 2. Frontend service: `ApprovalError` class + JSON parsing

**File:** `frontend/packages/chassis/src/services/GatewayClaudeService.ts` (lines 222-226)

Add a lightweight `ApprovalError` class (same file, exported):

```typescript
export class ApprovalError extends Error {
  readonly errorCode: string;
  readonly upstreamStatus: number;
  constructor(message: string, errorCode: string, upstreamStatus: number) {
    super(message);
    this.name = 'ApprovalError';
    this.errorCode = errorCode;
    this.upstreamStatus = upstreamStatus;
  }
}
```

Update error branch in `respondToApproval` — read body once as text, then try JSON.parse (from Codex R1 finding #1: `response.json()` then `response.text()` double-reads the body):

```typescript
if (!response.ok) {
  const raw = await response.text();
  let errorCode = 'approval_failed';
  let detail = raw || `Approval failed (${response.status})`;
  try {
    const body = JSON.parse(raw);
    errorCode = body.error_code ?? errorCode;
    detail = body.detail ?? body.error ?? detail;
  } catch {
    // raw is already captured as detail
  }
  throw new ApprovalError(detail, errorCode, response.status);
}
```

**Barrel export:** Add `ApprovalError` to `frontend/packages/chassis/src/services/index.ts` (line 62 area, alongside `GatewayClaudeService`).

### 3. Frontend hook: clear stale approval card on expiration

**File:** `frontend/packages/connectors/src/features/external/hooks/usePortfolioChat.ts` (lines 420-428)

Import `ApprovalError` from `@risk/chassis`. Two changes in the `respondToApproval` callback:

**3a.** At the **start** of `respondToApproval` (before the try block, after the `pendingApprovalRef` guard), clear any pre-existing global error state from a previous attempt (from Codex R15: generic→expired retry leaves stale global banner):

```typescript
// Clear previous error state on retry
setStreamError(null);
setChatStatus({ state: 'ready', message: '' });
```

**3b.** In the catch block, clear `pendingApproval` for expired and skip the global error:

```typescript
catch (error) {
  const err = error instanceof Error ? error : new Error(String(error));
  if (err instanceof ApprovalError && err.errorCode === 'approval_expired') {
    // Clear stale card; don't set global chat error — ChatCore shows a local friendly message
    setPendingApproval(null);
  } else {
    setStreamError(err);
    setChatStatus({ state: 'error', message: 'Tool approval failed', error: categorizeError(err) });
  }
  throw err;
}
```

Key difference: `setStreamError` and `setChatStatus` are **only called for non-expired errors**. The expired case is handled entirely by the local `approvalError` state in ChatCore (section 4b post-card display). The pre-try clear (3a) ensures any stale global error from a previous generic failure is wiped before a retry attempt.

### 4. Frontend UI: friendly error message + copy fix

**File:** `frontend/packages/ui/src/components/chat/shared/ChatCore.tsx`

**4a.** Import `ApprovalError` from `@risk/chassis`. Update `handleApprovalDecision` (lines 663-674) to detect expired approvals:

```typescript
catch (error) {
  if (error instanceof ApprovalError && error.errorCode === 'approval_expired') {
    setApprovalError('This approval has expired \u2014 the tool call is no longer active.');
  } else {
    const message = error instanceof Error ? error.message : 'Failed to respond to approval request';
    setApprovalError(message);
  }
}
```

**4b.** Error display in two locations (from Codex R1 finding #2: keep in-card error for non-expired failures):

- **Keep existing in-card error** (line 1507-1509) for generic failures (401/500/network) where `pendingApproval` stays mounted:
  ```tsx
  {approvalError && (
    <p className="mt-2 text-xs text-down">{approvalError}</p>
  )}
  ```

- **Add post-card error** (after line 1511) for the expired case where the hook clears `pendingApproval`:
  ```tsx
  {approvalError && !pendingApproval && (
    <p className="mb-4 text-xs text-down">{approvalError}</p>
  )}
  ```

This way: non-expired errors show inside the card (card stays mounted), expired errors show below where the card was (card unmounted by hook).

**4c.** Clear stale `approvalError` when a new approval arrives (from Codex R7: if a new `pendingApproval` shows up before the 5s timer, the old expired message would bleed into the new card). Add a `useEffect`:

```typescript
useEffect(() => {
  if (pendingApproval) {
    setApprovalError(null);
  }
}, [pendingApproval]);
```

**4d.** Auto-clear the post-card error after 5 seconds. Add a `useEffect`:

```typescript
useEffect(() => {
  if (approvalError && !pendingApproval) {
    const timer = setTimeout(() => setApprovalError(null), 5000);
    return () => clearTimeout(timer);
  }
}, [approvalError, pendingApproval]);
```

**4e.** Update approval card copy (line 1483):
- Before: `"Approve or deny this tool call before the request times out."`
- After: `"Approve or deny this tool call to continue."`

### 4½. NormalizerBuilderPanel: friendly error for expired approvals

**File:** `frontend/packages/ui/src/components/onboarding/NormalizerBuilderPanel.tsx`

This component has two `respondToApproval` callsites:

**4½a. Auto-approve branch (lines 190-195):** `normalizer_*` tools are auto-approved inline during streaming. Wrap in try/catch so an expired approval doesn't crash the stream. Important: the existing code after `respondToApproval` (line 195) overwrites `statusText` with `Running ${chunk.tool_name}...`, so the expired branch must `continue` past it (from Codex R15):

```typescript
setStatusText(`Approving ${chunk.tool_name}...`);
try {
  await service.respondToApproval(chunk.tool_call_id, chunk.nonce, true);
} catch (error) {
  if (error instanceof ApprovalError && error.errorCode === 'approval_expired') {
    setStatusText('Approval expired — tool call is no longer active.');
    continue; // skip the "Running ..." status text below
  }
  throw error; // re-throw non-expired errors to break the stream
}
if (streamSequenceRef.current !== streamId) {
  break;
}
setStatusText(`Running ${chunk.tool_name}...`);
```

**4½b. Manual approve handler (lines 279-282):** Catches raw `error.message`. Same problem as ChatCore — `approvalError` renders inside the `{pendingApproval ? ... : null}` block (line 373), so clearing `pendingApproval` makes the error invisible. Fix: for expired errors, keep `pendingApproval` mounted but disable the buttons (the card serves as the error container):

```typescript
catch (error) {
  if (error instanceof ApprovalError && error.errorCode === 'approval_expired') {
    setApprovalError('This approval has expired — the tool call is no longer active.');
    // Do NOT clear pendingApproval — keep card mounted so error is visible
  } else {
    setApprovalError(
      error instanceof Error ? error.message : 'Failed to respond to approval request.'
    );
  }
}
```

Unlike ChatCore (which has a separate post-card error slot), NormalizerBuilderPanel keeps the card mounted and shows the error inside it. To prevent stale clickable buttons after expiration while still allowing retry on transient errors (from Codex R5 + R9), track whether the approval is expired via a separate boolean:

Add state: `const [approvalExpired, setApprovalExpired] = useState(false);`

In the catch block (4½b above), set `setApprovalExpired(true)` for expired errors.

At line 359 and 368, change the `disabled` prop:
```tsx
disabled={approvalBusy || approvalExpired}
```

This disables buttons only for expired approvals (permanent — no point retrying). Generic errors (transient 500/network) keep buttons enabled so users can retry. Reset `approvalExpired` when a new `pendingApproval` arrives via a `useEffect`:

```typescript
useEffect(() => {
  if (pendingApproval) {
    setApprovalExpired(false);
  }
}, [pendingApproval]);
```

Import `ApprovalError` from `@risk/chassis` at the top of the file.

### 5. Tests

#### Backend: `tests/app_platform/test_gateway_proxy.py`

**5a.** Update `test_proxy_approval_401_returns_error_without_refresh` (line 158): the upstream returns `content="nonce/session mismatch"` (plain text), so the proxy will now wrap it in JSON. Update assertion:

```python
assert approval.status_code == 401
body = approval.json()
assert body["error_code"] == "approval_failed"
assert body["detail"] == "nonce/session mismatch"
```

**5b.** Add `test_proxy_approval_404_returns_expired_error_code`: upstream returns 404 with `{"error": "Unknown tool_call_id"}`. Assert:

```python
assert approval.status_code == 404
body = approval.json()
assert body["error_code"] == "approval_expired"
assert body["error"] == "Unknown tool_call_id"
```

**5c.** Add `test_proxy_approval_500_returns_generic_error_code`: upstream returns 500 with plain text. Assert `error_code == "approval_failed"` and `detail` contains the text.

**5c½.** Add `test_proxy_approval_non_dict_json_body`: upstream returns 422 with JSON array body `["validation error"]`. Assert response is valid JSON with `error_code == "approval_failed"` and `detail` contains stringified array (no crash from `**` spread).

**5c¾.** Add `test_proxy_approval_upstream_cannot_overwrite_error_code`: upstream returns 404 with JSON `{"error_code":"spoofed","upstream_status":999}`. Assert response has `error_code == "approval_expired"` and `upstream_status == 404` (proxy fields win).

#### Backend (duplicate file): `tests/test_gateway_proxy.py`

**5d.** Update the duplicate `test_proxy_approval_401_returns_error_without_refresh` (line 148) with the same JSON assertion changes as 5a. Mirror all new approval tests (5b, 5c, 5c½, 5c¾) in this file — it has parallel copies of the approval test suite.

#### Frontend: `frontend/packages/connectors/src/features/external/__tests__/usePortfolioChat.test.tsx`

**5e.** Add test: `respondToApproval clears pendingApproval and skips global error on approval_expired`. Mock `gatewayService.respondToApproval` to throw `ApprovalError('expired', 'approval_expired', 404)`. Assert `result.current.pendingApproval` is `null`, AND assert `result.current.chatStatus.error` is not set and `result.current.error` is not set (validates R2 fix — global banner suppressed).

**5f.** Add test: `respondToApproval keeps pendingApproval and sets global error on generic failure`. Mock to throw `ApprovalError('failed', 'approval_failed', 500)`. Assert `result.current.pendingApproval` is NOT null, AND assert `result.current.chatStatus.error` IS set and `result.current.error` IS set (global banner shown for non-expired).

**5f½.** Add test: `generic failure then expired retry clears global banner`. First call throws `ApprovalError('failed', 'approval_failed', 500)` (sets global error). Second call throws `ApprovalError('expired', 'approval_expired', 404)`. Assert after second call: `result.current.chatStatus.error` is NOT set (3a pre-try clear wiped it), `result.current.pendingApproval` is null, and no stale global banner.

#### Frontend: ChatCore (required)

**5g.** **File:** `frontend/packages/ui/src/components/chat/shared/__tests__/ChatCore.approval.test.tsx` (new file). Add tests for `handleApprovalDecision`:
- `shows friendly expired message after card disappears`: mock `respondToApproval` to throw `ApprovalError('expired', 'approval_expired', 404)`. Assert post-card error text contains "expired" and the approval card is unmounted.
- `shows raw message in-card for generic failures`: mock with `ApprovalError('nonce mismatch', 'approval_failed', 401)`. Assert error appears inside the approval card.
- `clears stale expired message when new approval arrives`: trigger expired error, then set a new `pendingApproval` before the 5s timer fires. Assert the new card has no error message.

Note: the global error banner suppression (no `setChatStatus.error` for expired) is tested at the hook level in 5e/5f, not in ChatCore — ChatCore receives `respondToApproval` as a prop and doesn't control `chatStatus`. ChatCore tests (5g) focus on local `approvalError` rendering and card lifecycle.

#### Frontend: GatewayClaudeService (service-level parsing)

**5h.** **File:** `frontend/packages/chassis/src/services/GatewayClaudeService.test.ts` (new file, colocated with existing service tests). Add tests for `respondToApproval()` JSON parsing (from Codex R4 finding #2):
- `throws ApprovalError with error_code from JSON 404`: mock `fetch` returning 404 with JSON body `{"error_code":"approval_expired","error":"Unknown tool_call_id"}`. Assert thrown error is `ApprovalError` with `errorCode === 'approval_expired'`.
- `throws ApprovalError with fallback on plain text 500`: mock `fetch` returning 500 with plain text body. Assert `errorCode === 'approval_failed'` and message contains the text.
- `throws ApprovalError with fallback on empty body`: mock `fetch` returning 502 with empty body. Assert default detail message.

#### Frontend: NormalizerBuilderPanel

**5i.** **File:** `frontend/packages/ui/src/components/onboarding/__tests__/NormalizerBuilderPanel.approval.test.tsx` (new file or add to existing). Add tests for approval error handling (from Codex R6 finding #2):
- `expired manual approval shows friendly message with buttons disabled`: mock `service.respondToApproval` to throw `ApprovalError('expired', 'approval_expired', 404)`. Assert card stays mounted, error text contains "expired", both buttons are disabled.
- `generic manual approval error shows raw message with buttons retryable`: mock with non-expired error. Assert error text shown, buttons remain enabled (user can retry).
- `expired auto-approve sets status text and continues stream`: mock `respondToApproval` throwing expired error in the auto-approve branch. Assert `statusText` is set to expired message, stream continues.

---

## Files touched

| File | Change |
|------|--------|
| `app_platform/gateway/proxy.py` | Structured JSON error responses with dict guard |
| `frontend/packages/chassis/src/services/GatewayClaudeService.ts` | `ApprovalError` class + text-then-parse |
| `frontend/packages/chassis/src/services/index.ts` | Export `ApprovalError` |
| `frontend/packages/connectors/src/features/external/hooks/usePortfolioChat.ts` | Clear stale approval on expiration |
| `frontend/packages/ui/src/components/chat/shared/ChatCore.tsx` | Dual error display, copy fix, auto-clear |
| `frontend/packages/ui/src/components/onboarding/NormalizerBuilderPanel.tsx` | Friendly error for expired approvals |
| `tests/app_platform/test_gateway_proxy.py` | Update 401 test, add 404/500/non-dict-JSON/overwrite tests |
| `tests/test_gateway_proxy.py` | Mirror all approval test changes from above |
| `frontend/packages/connectors/src/features/external/__tests__/usePortfolioChat.test.tsx` | Add expired/generic approval error tests |
| `frontend/packages/ui/src/components/chat/shared/__tests__/ChatCore.approval.test.tsx` | New: expired message, generic in-card error, stale-message-on-new-approval |
| `frontend/packages/chassis/src/services/GatewayClaudeService.test.ts` | New: service-level JSON parsing tests |
| `frontend/packages/ui/src/components/onboarding/__tests__/NormalizerBuilderPanel.approval.test.tsx` | New: expired/generic approval + auto-approve tests |

## Verification

1. **Backend tests:** `pytest tests/app_platform/test_gateway_proxy.py tests/test_gateway_proxy.py -v -k approval` — all approval tests pass
2. **Frontend tests:** `cd frontend && npx vitest run --reporter=verbose` — check no regressions, new approval tests pass
3. **Manual:** Start dev server, trigger a tool call in chat. To simulate the expired 404: either wait for upstream TTL to expire naturally, or temporarily patch the proxy to return `JSONResponse({"error_code":"approval_expired","error":"Unknown tool_call_id"}, status_code=404)` unconditionally. Click Approve → should see friendly "expired" message that auto-clears after 5s, no global error banner, no raw error strings.

## Codex Review History

**R1 — FAIL (4 findings)**:
1. `response.json()` then `response.text()` double-reads fetch body → **Fixed**: read once with `response.text()` + `JSON.parse()`
2. Error display incomplete: non-expired errors invisible when only rendered outside card → **Fixed**: dual display (in-card for generic, post-card for expired)
3. Proxy `**upstream_body` spread unsafe for non-dict JSON + upstream can overwrite `error_code` → **Fixed**: `isinstance` guard + proxy fields placed after spread
4. Missing frontend tests + duplicate backend test file → **Fixed**: added 5d-5g test items

**R2 — FAIL (1 finding)**:
1. `setChatStatus({ error })` still fires for expired approvals → global error banner shows raw upstream message, defeating friendly UX → **Fixed**: skip `setStreamError`/`setChatStatus` for `approval_expired`, let ChatCore local `approvalError` handle it. ChatCore test made required (not optional).

**R3 — FAIL (1 real finding, 4 false positives)**:
- Codex reviewed source files instead of plan → reported "code hasn't changed" as findings (false positives for #1-3, #5).
- Real finding #4: `NormalizerBuilderPanel.tsx` is a second consumer of `respondToApproval` that catches raw `error.message` → **Fixed**: added section 4½ with `ApprovalError` handling in NormalizerBuilderPanel.

**R4 — FAIL (2 findings)**:
1. NormalizerBuilderPanel: clearing `pendingApproval` makes error invisible (same bug as ChatCore), plus auto-approve branch at line 191 has no error handling → **Fixed**: keep card mounted for expired errors (don't clear `pendingApproval`), wrap auto-approve in try/catch.
2. No service-level test for `GatewayClaudeService.respondToApproval()` JSON parsing → **Fixed**: added test items 5h (3 cases: JSON 404, plain text 500, empty body 502).

**R5 — FAIL (1 finding)**:
1. NormalizerBuilderPanel stale clickable buttons after expired error → **Fixed**: `disabled={approvalBusy || !!approvalError}` on both buttons.

**R6 — FAIL (3 findings, 1 deferred)**:
1. Raw error strings for non-expired failures → **Deferred**: existing behavior, diagnostic text is useful, out of scope for this fix.
2. Missing NormalizerBuilderPanel tests → **Fixed**: added test items 5i (3 cases).
3. Test file naming + Files touched table incomplete → **Fixed**: all test files named, added to table.

**R7 — FAIL (1 finding)**:
1. Stale expired message bleeds into new approval card if new `pendingApproval` arrives before 5s auto-clear → **Fixed**: added `useEffect` to clear `approvalError` when `pendingApproval` changes (section 4c).

**R8 — FAIL (1 finding)**:
1. Missing regression test for the R7 fix → **Fixed**: added ChatCore test case for stale expired message cleared on new approval.

**R9 — FAIL (3 findings)**:
1. Duplicate test suite missing 404/500 mirrors → **Fixed**: added note to mirror in 5d.
2. NormalizerBuilderPanel `!!approvalError` disabling strands users on transient errors → **Fixed**: track `approvalExpired` boolean separately, only disable for expired.
3. Manual verification simulates wrong error (502 not 404) → **Fixed**: updated to proxy patch approach.

**R10 — FAIL (3 findings)**:
1. "if tests exist" header inconsistency → **Fixed**: ChatCore tests marked required, header updated.
2. Global banner test at wrong layer → **Fixed**: moved to hook tests (5e/5f), ChatCore tests focus on local rendering.
3. Files touched table incomplete for duplicate test file → **Fixed**: table row updated.

**R11 — FAIL (2 findings)**:
1. 5e/5f missing explicit assertions on `chatStatus.error`/`streamError` → **Fixed**: added assertions using public hook surface (`result.current.chatStatus.error`, `result.current.error`).
2. Missing tests for non-dict JSON body and upstream field overwrite → **Fixed**: added 5c½ and 5c¾.

**R12 — FAIL (3 findings)**:
1. Duplicate test file 5d not mirroring 5c½/5c¾ → **Fixed**: 5d now mirrors all new tests.
2. ChatCore Files-touched row said "no global banner" but that's hook-level → **Fixed**: row updated.
3. `approvalExpired` reset underspecified → **Fixed**: concrete `useEffect` added.

**R13 — FAIL (3 findings)**:
1. 5e/5f used `streamError` instead of public `result.current.error` → **Fixed**.
2. GatewayClaudeService test file path wrong → **Fixed**: colocated at `services/GatewayClaudeService.test.ts`.
3. Files-touched table stale → **Fixed**: full test descriptions.

**R14 — FAIL (2 findings)**:
1. 5f missing `result.current.error` assertion → **Fixed**: added.
2. Review history incomplete → **Fixed**: added R12-R14 entries.

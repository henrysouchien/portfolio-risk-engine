# Friendly Approval Error Copy

## Context

When a tool-call approval fails with a non-expired error (401 nonce mismatch, 500 server error, 502 proxy error, etc.), the UI currently shows raw upstream error text like `"Gateway approval proxy error: ..."` or `"Approval failed (401)"`. The expired case (404) was already handled with a friendly message in `APPROVAL_EXPIRATION_UX_FIX_PLAN.md`. This task maps common `error_code` + `upstreamStatus` combinations to user-friendly copy.

## Approach

Add a shared `friendlyApprovalMessage()` utility in `GatewayClaudeService.ts` (co-located with `ApprovalError`) and use it in all 4 catch sites that currently show raw error text.

## Error → Message Mapping

| `upstreamStatus` | Friendly copy |
|---|---|
| 401 | "Session mismatch — try sending a new message." |
| 404 (already handled separately) | "This approval has expired — the tool call is no longer active." |
| 429 | "Rate limited — try again in a moment." |
| 500 | "Server error — try again in a moment." |
| 502 | "Gateway unreachable — try again in a moment." |
| other 4xx/5xx | "Approval failed — try again or send a new message." |

Function signature:

```typescript
export function friendlyApprovalMessage(error: ApprovalError): string {
  switch (error.upstreamStatus) {
    case 401: return 'Session mismatch — try sending a new message.';
    case 429: return 'Rate limited — try again in a moment.';
    case 500: return 'Server error — try again in a moment.';
    case 502: return 'Gateway unreachable — try again in a moment.';
    default:  return 'Approval failed — try again or send a new message.';
  }
}
```

## Files to Change

### 1. `frontend/packages/chassis/src/services/GatewayClaudeService.ts` (~line 118)

Add `friendlyApprovalMessage()` function after the `ApprovalError` class definition.

### 2. `frontend/packages/chassis/src/services/index.ts` (line 31, 62)

Add `friendlyApprovalMessage` to the import from `./GatewayClaudeService` and re-export it.

### 3. `frontend/packages/ui/src/components/chat/shared/ChatCore.tsx` (lines 682–686)

Current:
```typescript
} else {
  const message = error instanceof Error ? error.message : 'Failed to respond to approval request'
  setApprovalError(message)
}
```

Change to:
```typescript
} else if (error instanceof ApprovalError) {
  setApprovalError(friendlyApprovalMessage(error))
} else {
  setApprovalError('Failed to respond to approval request.')
}
```

Import `friendlyApprovalMessage` alongside `ApprovalError` from `@risk/chassis`.

### 4. `frontend/packages/connectors/src/features/external/hooks/usePortfolioChat.ts` (lines 427–433)

This is the hook-level catch that sets `streamError` and `chatStatus` for non-expired failures. The `categorizeError()` call does string-matching on `error.message` which surfaces raw upstream text. For `ApprovalError`, bypass `categorizeError()` entirely and construct the `ChatError` directly — this avoids the problem where friendly copy (e.g. "Session mismatch — try sending a new message.") doesn't contain `'401'` or `'unauthorized'`, so `categorizeError` would misclassify it as `unknown` instead of `auth`.

Current:
```typescript
} else {
  setStreamError(err);
  setChatStatus({
    state: 'error',
    message: 'Tool approval failed',
    error: categorizeError(err),
  });
}
```

Change to:
```typescript
} else if (err instanceof ApprovalError) {
  const friendlyMsg = friendlyApprovalMessage(err);
  const errorType = err.upstreamStatus === 401 ? 'auth'
    : err.upstreamStatus === 429 ? 'rate_limit'
    : 'server';
  setStreamError(new Error(friendlyMsg));
  setChatStatus({
    state: 'error',
    message: 'Tool approval failed',
    error: {
      type: errorType,
      message: friendlyMsg,
      retryable: errorType !== 'auth',
      ...(errorType === 'rate_limit' ? { retryDelay: 30000 } : {}),
    },
  });
} else {
  setStreamError(err);
  setChatStatus({
    state: 'error',
    message: 'Tool approval failed',
    error: categorizeError(err),
  });
}
```

Import `friendlyApprovalMessage` alongside `ApprovalError` from `@risk/chassis`.

Note: the `throw err` at line 435 re-throws the original error so ChatCore's own catch still receives the real `ApprovalError` instance for its `errorCode` checks. We only swap the message for the hook-level global error/banner path. The 401 case is correctly typed as `auth`/non-retryable (nonce is bound to old session — user must send a new message). All other statuses are `server`/retryable.

### 5. `frontend/packages/ui/src/components/onboarding/NormalizerBuilderPanel.tsx`

**Auto-approve catch (lines 201–205):** Do NOT change. The current behavior correctly rethrows non-expired failures — a 401/500 means the approval was not delivered, so the upstream tool call is still pending and will stall until timeout. Only `approval_expired` should `continue` (the tool call is already gone). Leave this branch as-is.

**Manual approval catch (lines 298–301):** Replace `error.message` with `friendlyApprovalMessage`:

```typescript
} else if (error instanceof ApprovalError) {
  setApprovalError(friendlyApprovalMessage(error));
} else {
  setApprovalError('Failed to respond to approval request.');
}
```

Import `friendlyApprovalMessage` alongside `ApprovalError` from `@risk/chassis`.

### 6. Update existing tests

**`frontend/packages/ui/src/components/chat/shared/__tests__/ChatCore.approval.test.tsx` (line 81–95):**

Test `'shows raw message in-card for generic failures'` currently asserts `screen.getByText('nonce mismatch')` (raw upstream text). Change to assert the friendly message instead:
```typescript
expect(screen.getByText('Session mismatch — try sending a new message.')).toBeInTheDocument();
```

**`frontend/packages/ui/src/components/onboarding/__tests__/NormalizerBuilderPanel.approval.test.tsx` (line 98–127):**

Test `'generic manual approval error shows raw message with buttons retryable'` currently asserts `screen.getByText('nonce mismatch')`. Change to assert:
```typescript
expect(screen.getByText('Server error — try again in a moment.')).toBeInTheDocument();
```
(This test mocks `upstreamStatus: 500`, so the friendly message for 500 applies.)

**`frontend/packages/connectors/src/features/external/__tests__/usePortfolioChat.test.tsx` (lines 622–642):**

Test `'respondToApproval keeps pendingApproval and sets global error on generic failure'` — this test checks that `chatStatus.error` is defined and `error` is not null, which will still pass. The `error.message` going through `categorizeError` will now be the friendly string. No assertion changes needed here since the test doesn't assert on the specific error message text.

### 7. `docs/TODO.md` (~line 1147)

Mark the "Friendlier copy for non-expired approval errors" bullet as done with a strikethrough prefix.

## Verification

- `cd frontend && npx tsc --noEmit` — type check passes
- `cd frontend && npx vitest run --reporter=verbose packages/ui/src/components/chat/shared/__tests__/ChatCore.approval.test.tsx packages/ui/src/components/onboarding/__tests__/NormalizerBuilderPanel.approval.test.tsx packages/connectors/src/features/external/__tests__/usePortfolioChat.test.tsx` — all approval tests pass with updated assertions
- Manual: trigger a 401/500 in the approval flow and confirm the card shows friendly copy instead of raw error text

## Codex Review History

- R1 FAIL: 3 findings — (1) auto-approve `continue` for non-expired is wrong (rethrow is correct), (2) missed `usePortfolioChat.ts` catch site, (3) existing tests need updating. All addressed in v2.
- R2 FAIL: 2 findings — (1) friendly 401 text doesn't match `categorizeError()` string patterns, changing error type from `auth` to `unknown` — fixed by bypassing `categorizeError()` and constructing `ChatError` directly for `ApprovalError`, (2) 401 copy should be "Session mismatch" not "Session expired" (404 is expiration) — fixed. All addressed in v3.
- R3 FAIL: 1 finding — 429 collapsed to `type: 'server'` instead of `type: 'rate_limit'` with `retryDelay: 30000` matching existing `categorizeError` pattern. Fixed in v4.

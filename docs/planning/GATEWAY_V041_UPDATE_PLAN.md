# Gateway v0.4.1 Frontend + Docs Update Plan

## Context

`ai-agent-gateway` v0.4.1 was published and installed. This version adds background sub-agents (`run_agent` with `background=true`, `get_background_result`) and refactors `tool_dispatcher.py` into its own module. The risk_module proxy (`app_platform/gateway/proxy.py`) is already compatible — it does raw SSE byte passthrough via `aiter_raw()` (line 251), so new event types flow through unchanged. No proxy or model changes needed.

This plan covers frontend resilience (thinking_delta mapping, debug logging) and documentation updates.

## Complete SSE Event Surface (v0.4.1)

For reference — the full set of events the gateway can emit:

**From runner.py** (already handled by frontend mapper):
- `text_delta` — streamed text content
- `tool_call_start` — tool invocation begins (mapped as-is)
- `tool_call_complete` — tool finished (mapped to `tool_result` chunk by frontend)
- `error` — runner error
- `stream_complete` — run finished (mapped to `done` chunk by frontend)

**From runner.py** (NEW — not yet handled):
- `thinking_delta` — extended thinking content
- `stream_retry` — retry attempt with `attempt` and `error` fields
- `compaction` — context window compaction
- `max_turns_reached` — turn limit hit, with `turn_count` and `max_turns` fields (followed by `text_delta` with user-visible message)
- `budget_exceeded` — cost budget exceeded (followed by `text_delta` with user-visible message)

**From server.py** (via event_log.append):
- `tool_approval_request` (already handled)
- `heartbeat` (correctly ignored)
- `error` — server-level error

**From server.py** (yielded directly during SSE serialization, not via event_log):
- `stream_error` — SSE serialization failure

## Changes

### 1. ClaudeStreamTypes.ts — Add thinking_delta chunk type

**File**: `frontend/packages/chassis/src/services/ClaudeStreamTypes.ts`

Add one new union member:
```typescript
| { type: 'thinking_delta'; content: string }
```

This handles extended thinking content from the gateway. No generic `status` type — the other new events (`stream_retry`, `compaction`, `max_turns_reached`, `budget_exceeded`) carry distinct payloads that would be lost in a generic wrapper. They remain debug-logged until a concrete UI needs them.

### 2. GatewayClaudeService.ts — Map thinking_delta + debug logging

**File**: `frontend/packages/chassis/src/services/GatewayClaudeService.ts`

**2a.** Add `thinking_delta` case in `mapEvent()` (before `stream_complete`):
```typescript
case 'thinking_delta':
  return { type: 'thinking_delta', content: String(event.text ?? '') };
```

**2b.** Pass `tool_input` through on `tool_call_start`. The existing type in `ClaudeStreamTypes.ts` already has `tool_input?: unknown`, so the mapper just needs to forward it:
```typescript
case 'tool_call_start':
  return {
    type: 'tool_call_start',
    tool_name: String(event.tool_name ?? 'unknown'),
    tool_input: event.tool_input as Record<string, unknown> | undefined,
  };
```

Note: `tool_input` is typed as `unknown` — consumers must use runtime guards (e.g. `typeof chunk.tool_input === 'object' && chunk.tool_input?.task`) to access `.task` for sub-agent display. No type narrowing needed at the mapper level.

**2c.** Add debug logging in `default` case using Vite's env check:
```typescript
default:
  if (import.meta.env.DEV && event.type !== 'heartbeat') {
    console.debug('[GatewayClaudeService] Unhandled event type:', event.type);
  }
  return null;
```

### 3. Documentation

**3a. DEPLOY_CHECKLIST.md**: Add version compatibility note under the claude-gateway section stating that the `app-platform` gateway proxy is version-agnostic (byte passthrough) and does not need updates when the upstream gateway version changes.

**3b. TODO.md**: Add entry noting v0.4.1 is live and deferred future work (rendering thinking_delta in chat UI, sub-agent progress indicators, status event UI).

## Files Modified

| File | Change |
|------|--------|
| `frontend/packages/chassis/src/services/ClaudeStreamTypes.ts` | Add `thinking_delta` chunk type |
| `frontend/packages/chassis/src/services/GatewayClaudeService.ts` | Map `thinking_delta`, pass `tool_input` on `tool_call_start`, add dev debug log |
| `docs/DEPLOY_CHECKLIST.md` | Version compatibility note |
| `docs/TODO.md` | v0.4.1 status entry |

## Consumers (no changes needed this pass)

These files consume `ClaudeStreamChunk` but already safely ignore unknown types via `if` chains:
- `frontend/packages/connectors/src/features/external/hooks/usePortfolioChat.ts` — `chunk.type === 'text_delta'` etc, ignores unmatched
- `frontend/packages/ui/src/components/onboarding/NormalizerBuilderPanel.tsx` — same pattern
- `frontend/packages/connectors/src/features/external/__tests__/usePortfolioChat.test.tsx` — tests use `text_delta`/`done`/`error`/`upgrade_required` only

These consumers will not break from the new union member. Future work can add `thinking_delta` rendering in `usePortfolioChat.ts` when the UI design is ready.

## What Does NOT Change

- `app_platform/gateway/proxy.py` — byte passthrough, already compatible (line 251: `aiter_raw()`)
- `app_platform/gateway/session.py` — no new auth requirements
- `app_platform/gateway/models.py` — no new fields needed
- `routes/gateway_proxy.py` — no new endpoints
- `app_platform/pyproject.toml` — no new dependency on `ai-agent-gateway` (by design)

## Risk

Changes are additive. The `thinking_delta` union member is new — consumers that don't handle it will pass through their existing `if` chains unchanged (no `else` clauses would match). The `tool_call_start` change forwards a field that's already in the TypeScript type definition as `unknown`. The debug log only fires in dev mode (`import.meta.env.DEV`).

Note: because `ClaudeStreamChunk` is exported from `@risk/chassis`, external consumers (if any) will see the new union member on type upgrade. All in-repo consumers have been verified safe.

## Verification

1. `cd frontend && npx tsc -b` — confirm no TypeScript errors
2. `cd frontend && npx vitest run` — confirm no test regressions
3. Manual: start a chat session in dev mode, observe console for debug logs of unhandled events
4. Manual: trigger a `run_agent` tool call (if sub-agents enabled on gateway) and verify `tool_input` is forwarded

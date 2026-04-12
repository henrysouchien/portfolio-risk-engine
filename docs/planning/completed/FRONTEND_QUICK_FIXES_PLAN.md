# Frontend Quick Fixes Plan (F2, F3, F4)

**Date**: 2026-04-07
**Status**: READY (revised after Codex review rounds 1-2)

---

## F2: Chat reload button doesn't reconnect

### Summary
The visible reload button in the AIChat modal header is a hardcoded no-op. Even if it worked, the underlying `reload()` in `usePortfolioChat.ts` has three additional bugs: it doesn't abort in-flight streams, it duplicates `clearMessages()` without differentiation, and invalidating the React Query chat context cache would be ineffective because `sendMessage()` never reads `chatContext` when calling the gateway.

### Root Cause Analysis

**Problem 1 — AIChat.tsx reload button is a no-op (PRIMARY)**
`AIChat.tsx:69` defines `const handleReloadConversation = () => undefined` — a hardcoded no-op. The header button at line 97-105 calls this function. Meanwhile, `ChatCore.tsx` (the child component) has its own working reload via `useSharedChat()` → `reload()` (line 321), exposed in a dropdown menu (line 1552). The modal header button and the ChatCore dropdown menu are completely disconnected.

**Problem 2 — `reload()` doesn't abort in-flight streams**
`usePortfolioChat.ts:1015-1022` — `reload()` resets UI state (messages, status, errors, artifact) but never calls `abortControllerRef.current?.abort()`. If a stream is active when the user clicks reload, the response continues accumulating in the background. By contrast, `stop()` (line 903-912) does call `abortControllerRef.current.abort()` but only updates streaming-specific state — it doesn't clear messages.

**Problem 3 — `clearMessages()` is an exact duplicate of `reload()`**
`usePortfolioChat.ts:1030-1036` — `clearMessages()` contains the same 5 lines as `reload()` minus the log statement. Both are returned from the hook and both are wired in ChatCore's dropdown (lines 1552, 1559). Fixing only one leaves the other inconsistent.

**Problem 4 — `sendMessage()` never passes abort signal to stream**
`usePortfolioChat.ts:663-668` — `sendMessage()` creates an `AbortController` (line 601) and stores it in `abortControllerRef`, but only passes 4 arguments to `gatewayService.sendMessageStream()`. The 5th parameter (`signal?: AbortSignal`) defined in `GatewayClaudeService.ts:135` is never provided. Even when `stop()` calls `abort()`, the underlying fetch request is not actually cancelled.

**Non-issue — chatContext cache invalidation**
The original plan proposed invalidating the `chatContextKey` React Query cache. This would be ineffective: `sendMessage()` (line 663-668) calls `gatewayService.sendMessageStream(trimmed, messages, portfolioDisplayName, 'chat')` — it sends the prompt text, the local message array, the portfolio display name, and a purpose string. It never reads `chatContext` from the React Query cache. The `chatContext` query exists (line 272-274) but its data is not consumed by `sendMessage()`.

**Non-issue — GatewayClaudeService session state**
The original plan proposed re-creating the `GatewayClaudeService` instance. This is unnecessary: `GatewayClaudeService` (in `GatewayClaudeService.ts:111-121`) is stateless — it holds only `proxyUrl: string`. It has no conversation history, no session token, no internal state. The actual session state lives server-side in `GatewaySessionManager` (in `app_platform/gateway/session.py`), which manages per-user gateway tokens. Recreating the frontend service object would have zero effect on the backend session.

### Fix

**File 1**: `frontend/packages/ui/src/components/chat/AIChat.tsx`

Wire the modal header reload button to the actual `reload` function from the shared chat hook instead of the no-op:

1. Import `useSharedChat` is already present (line 59). It already provides `reload` via `usePortfolioChat`.
2. Replace the no-op `handleReloadConversation` (line 69) with the real `reload` from `useSharedChat()`:
   ```tsx
   const { artifactPanelOpen, reload } = useSharedChat()
   ```
3. Change the button's `onClick` (line 100) from `handleReloadConversation` to `reload`.
4. Remove the dead `handleReloadConversation` constant.

**File 2**: `frontend/packages/connectors/src/features/external/hooks/usePortfolioChat.ts`

Fix `reload()` to be a proper conversation reset (abort + clear), make `clearMessages()` delegate to it, and thread the abort signal through to the stream:

1. **Pass abort signal to stream** (line 663-668): Add `abortController.signal` as the 5th argument to `gatewayService.sendMessageStream()`:
   ```ts
   const streamGenerator = gatewayService.sendMessageStream(
     trimmed,
     messages,
     portfolioDisplayName,
     'chat',
     abortController.signal,
   );
   ```

2. **Add abort to `reload()`** (line 1015-1022): Insert `abortControllerRef.current?.abort()` and `setIsStreaming(false)` / `setCurrentStreamingMessageId(null)` at the top of the function body, before the existing state resets. This ensures an in-flight stream is cancelled before clearing messages.

3. **Make `clearMessages()` delegate to `reload()`** (line 1030-1036): Replace the duplicated body with a single call to `reload()` to eliminate the copy-paste divergence risk.

4. **Handle AbortError as benign cancellation** (line ~862 catch block): The current catch block in `sendMessage()` treats every thrown error as a failure — sets `chatStatus` to `error` and appends a generic assistant error message. `categorizeError()` (line ~338) also has no abort-specific branch. Once the abort signal is actually threaded through, `reload()` and `stop()` will trigger an `AbortError` from the fetch. Without handling this, the chat would enter error state after every cancellation. Fix: add an early return in the catch block when `error.name === 'AbortError'` or `abortControllerRef.current?.signal.aborted` — skip error message insertion and status update, since cancellation is intentional.
   ```ts
   } catch (error) {
     if (error instanceof DOMException && error.name === 'AbortError') {
       // Intentional cancellation (reload/stop) — not an error
       return;
     }
     // ... existing error handling ...
   }
   ```

### Risk Assessment
**Low**. All changes are additive or consolidation of existing code. No API contract changes. The abort signal threading uses the existing `AbortSignal` parameter that `GatewayClaudeService.sendMessageStream` already accepts but was never being passed. The AIChat button wiring uses the existing `reload` function from the same hook that ChatCore already consumes.

---

## F3: Settings AI Providers grey badge despite being connected

### Summary
Providers with a valid API key but not currently selected as `LLM_PROVIDER` show a grey "inactive" dot, identical to providers with no key configured. Users cannot distinguish "available but not selected" from "not configured." The issue appears in two frontend components and the backend API.

### Root Cause
**Backend** (`routes/ai_providers.py:37-42`): The status logic uses a binary `active`/`inactive`. A provider with `has_key=True` but `is_active=False` gets `status="inactive"` -- the same status as a provider with no key at all (line 42). The detail string says "(available)" but the status field is still "inactive".

**Frontend — AIProviders.tsx** (`AIProviders.tsx:16-20`): `STATUS_DOT` maps `inactive` to the dim grey color (`bg-[hsl(var(--text-dim))]`). No visual distinction for "has key, not selected."

**Frontend — AIProviderPickerModal.tsx** (`AIProviderPickerModal.tsx:18-22, 48-49`): Has its own duplicate `STATUS_DOT` map (lines 18-22) with the same `active`/`inactive`/`error` keys. The badge label at line 49 uses a binary check: `provider.status === 'active' ? 'Configured' : 'Setup required'` — so any provider that has a key but is not active shows "Setup required", which is misleading.

**Type** (`chassis/src/types/index.ts`): `AIProviderInfo.status` is `'active' | 'inactive' | 'error'` -- no "available" variant.

**Test** (`tests/routes/test_ai_providers.py:47`): `test_openai_available` asserts `openai["status"] == "inactive"` for a provider that has a key but is not the active provider. This assertion must change to `"available"`.

### Fix

**File 1**: `routes/ai_providers.py` (lines 15, 37-42)

Update the `Literal` on the model and the status logic:
- Change `status: Literal["active", "inactive", "error"]` to `Literal["active", "available", "inactive", "error"]` (line 15).
- Change the `elif has_key:` branch (line 39-40) to emit `status="available"` instead of `status="inactive"`.

```python
# lines 37-42, after fix:
if is_active and has_key:
    status, detail = "active", f"{model} (active)"
elif has_key:
    status, detail = "available", f"{model} (available)"
else:
    status, detail = "inactive", "API key not configured"
```

**File 2**: `frontend/packages/chassis/src/types/index.ts`

Add `'available'` to the status union:
```ts
status: 'active' | 'available' | 'inactive' | 'error';
```

**File 3**: `frontend/packages/ui/src/components/settings/AIProviders.tsx` (lines 16-20)

Add `available` to `STATUS_DOT` with a dimmed green (configured but not primary):
```ts
const STATUS_DOT: Record<AIProviderInfo['status'], string> = {
  active: 'bg-up',
  available: 'bg-up/50',
  inactive: 'bg-[hsl(var(--text-dim))]',
  error: 'bg-down',
};
```

**File 4**: `frontend/packages/ui/src/components/settings/AIProviderPickerModal.tsx` (lines 18-22, 48-49)

1. Add `available` to the local `STATUS_DOT` map (line 18-22):
   ```ts
   const STATUS_DOT: Record<string, string> = {
     active: 'bg-foreground/80',
     available: 'bg-foreground/40',
     inactive: 'bg-[hsl(var(--text-dim))]',
     error: 'bg-[hsl(var(--down))]',
   };
   ```

2. Fix the badge label (line 49) to distinguish three states instead of the binary active/not-active:
   ```tsx
   {provider.status === 'active' ? 'Active' : provider.status === 'available' ? 'Configured' : 'Setup required'}
   ```

**File 5**: `tests/routes/test_ai_providers.py` (line 47)

Update `test_openai_available` assertion to match the new status value:
```python
assert openai["status"] == "available"
```

### Risk Assessment
**Low**. Additive status value. The backend Pydantic model, TypeScript type, frontend maps, and test all get updated in lockstep. Existing `active`/`inactive`/`error` consumers are unaffected. The `AIProviderPickerModal` duplicate `STATUS_DOT` is typed as `Record<string, string>` so adding a key is safe.

---

## F4: Settings Portfolio oversized cards

### Summary
The main settings card in RiskSettingsViewModern uses `p-8` padding on `CardContent`, making it noticeably larger than other cards (which use the standard `p-6`).

### Root Cause
`RiskSettingsViewModern.tsx:286` -- `<CardContent className="p-8">` applies 32px padding instead of the standard 24px (`p-6`). The adjacent `CsvImportCard` and other settings cards use `p-6`. No `max-width` constraint on the outer `<Card>`.

### Fix

**File**: `frontend/packages/ui/src/components/dashboard/views/modern/RiskSettingsViewModern.tsx`

1. Line 286: Change `p-8` to `p-6` on `<CardContent>`.
2. Line 288: Change `mb-8` to `mb-6` on the `<TabsList>` to match the reduced padding rhythm.
3. Line 285: Optionally add `max-w-4xl` to the outer `<Card>` if the card still appears too wide on large viewports. Evaluate visually -- skip if `p-6` alone is sufficient.

### Risk Assessment
**Trivial**. CSS-only change, no logic impact. Aligns with existing card padding convention across the settings views.

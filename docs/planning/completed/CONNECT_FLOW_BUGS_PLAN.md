# Fix Brokerage Connect Flow Bugs (Plaid + SnapTrade)

## Context

Two bugs prevent the parent window from detecting successful brokerage connections made in popup windows. These are blocking the Account Connections wiring plan because the connect/disconnect flows need reliable completion signals.

**Bug 1 (SnapTrade):** `useConnectSnapTrade.ts:164` sets `isConnecting=false` immediately after `window.open()`. SnapTradeSuccess.tsx auto-closes after 3s but sends no signal back. Parent never knows connection succeeded.

**Bug 2 (Plaid):** `useConnectAccount.ts:85` calls `await refreshConnections()` but `usePlaid.ts:349` returns void (not a Promise). The await is a no-op. Then line 87 reads `connections?.length` from a stale closure. `hasNewConnection` is always false.

## Codex Review Findings Addressed
- **#1 SnapTrade return contract**: `connectAccount()` now returns `Promise<ConnectSnapTradeResult | undefined>` — discriminated union (`confirmed | pending_sync | cancelled | ready`)
- **#2 Modal vs popup paths**: `openPopup` param splits paths. Modal path returns `connectionUrl` directly (no stale closure). SnapTradeLaunchButton reads return value.
- **R2#1 SnapTrade modal stale closure**: `connectAccount({ openPopup: false })` returns `{ connectionUrl }` directly. SnapTradeLaunchButton reads from return, not state.
- **R2#2 postMessage != backend ready**: After invalidateQueries, reads cache with exact scoped key, confirms count increased. Retry once after 2s. If still unchanged → resolve as unconfirmed.
- **R2#3 refresh-holdings can throw**: Best-effort with `.catch(() => {})`, separated from connection confirmation.
- **R3#1 useConnectionFlow blocking contract**: Updated to branch on `result.status` — no redundant polling.
- **R3#2 Cache key scoping**: Uses `plaidConnectionsKey(userId)` for exact cache reads, not hand-built keys.
- **R3#3 Retry terminal rule**: If count unchanged after retry → resolve as `{ status: 'pending_sync' }`, not confirmed.
- **R3#4 HoldingsViewModernContainer**: Updated to branch on result (skip refresh on cancel).
- **R6#1 postMessage/closed race**: `confirmationInFlight` flag prevents closed-poll from resolving during async confirmation.
- **R6#2 pendingSync recovery scope**: Delayed refetch invalidates holdings + portfolioSummary + portfolios, not just connections.
- **R6#3 HoldingsView contract**: Added to files modified — branches on result.
- **R6#4 SnapTrade success ownership**: monitorSnapTradePopup owns all popup-path side effects. handleConnectionSuccess reserved for modal path only.
- **R7#1 invalidateQueries not guaranteed fresh**: Use `refetchQueries({ exact: true })` + `getQueryData` for confirmed-fresh reads.
- **R7#2 Modal path same race**: Upgrade `handleConnectionSuccess()` to async — refetch + confirm count before declaring success. If unconfirmed, set `pendingSync` state on the hook (callers read from `state.pendingSync`).
- **R7#3 pendingSync fragile across callers**: Use discriminated union return type that forces exhaustive handling. Hook also owns a self-healing `useEffect` that schedules recovery refetch when `state.pendingSync` is true.
- **R8#1 Fixed popup names → reuse**: Nonce not viable (can't inject params into provider redirect). Instead: `isConnecting` flag already prevents concurrent attempts (only one popup at a time), so origin check is sufficient. No cross-attempt confusion possible.
- **R8#2 Single retry not self-healing**: Exponential backoff — 4 retries over ~45s (3s, 6s, 12s, 24s). Covers realistic backend lag.
- **R8#3 Return contract inconsistent**: Both Plaid and SnapTrade now use unified `ConnectResult` discriminated union (`confirmed | pending_sync | cancelled`).
- **R8#4 Modal baseline missing**: `initialSnapTradeCount` captured at `connectAccount()` call time and stored in hook state, not just closure.
- **R8#5 Baseline on unloaded data**: Hook ensures connections query is loaded before capturing baseline — refetches if `connections === undefined`.
- **R9#1 Nonce not viable via provider redirect**: Dropped nonce approach. isConnecting single-attempt guard + origin check is sufficient.
- **R9#2 Modal path two-phase**: Added `{ status: 'ready', connectionUrl }` variant to union. Modal callers check for `'ready'` and open modal.
- **R9#3 SnapTrade count uses authorization_id**: Uses `countDistinctAuthorizations()`, not raw array length. Move helper from `ui/useConnectionFlow.ts` to `connectors/src/features/external/utils.ts` to avoid cross-package import.
- **R10#1 Origin-only insufficient with multiple hook instances**: Restored `event.source === popup` check alongside origin check. Source ref is unique per window.open() call.
- **R10#2 Plaid count-only confirmation lossy**: Added timestamp signal — check `last_updated` newer than `attemptStartTime` as secondary confirmation.
- **R11#1-5**: Retry uses dual-signal, state.pendingSync set before resolve, timestamp acknowledged as heuristic, modal uses countDistinctAuthorizations, popup blocker handled.
- **R12#1 pendingSync bleeds across attempts**: Hard reset at start of every connectAccount() call.
- **R12#2 undefined vs null guard**: Use `== null` (hooks normalize to null).
- **R12#3 Unmount cleanup incomplete**: settle() now closes popup + all async paths check settled flag before setState.
- **R13#1 Re-entrancy**: Synchronous `inFlightRef` guard at start of connectAccount() — prevents two same-tick calls.
- **R13#2 HoldingsView pending_sync**: Skip immediate refresh on both cancel AND pending_sync (hook owns retry).
- **R13#3 Closed fallback too eager**: One last refetch/baseline check before resolving cancelled — catches missed postMessage.
- **#3 postMessage ≠ backend ready**: postMessage triggers a confirmation flow (invalidate queries + await refetch), NOT instant resolve. The `invalidateQueries` call forces a re-fetch from the backend, which won't return until data is available. If the backend hasn't persisted yet, the re-fetch returns stale data and the UI will update on the next window-focus refetch (30s staleTime fallback).
- **#4 Scoped query keys**: Use React Query prefix matching — `invalidateQueries({ queryKey: ['plaidConnections'] })` matches all entries starting with that prefix, including user-scoped `['plaidConnections', userId]`. This is React Query's default behavior.
- **#5 Message security**: Verify BOTH `event.origin === window.location.origin` AND `event.source === popup` (the stored Window ref from `window.open()`). The origin check ensures only our pages can send. The source check ensures the message comes from THIS attempt's popup, not a different hook instance's popup (multiple instances of useConnectAccount/useConnectSnapTrade can coexist in Settings, Holdings, ConnectionFlow, etc.). No nonce needed — the source ref is unique per `window.open()` call.
- **#6 Automatic cleanup**: Store message listener + interval refs. Add `useEffect` cleanup return that calls `settle()` on unmount. The existing manual `cleanup()` method also calls `settle()`.

## Steps

### Step 1: Create shared event constants
**New file:** `frontend/packages/connectors/src/features/auth/connectEvents.ts`
```ts
export const PLAID_CONNECT_SUCCESS = 'plaid-connect-success' as const;
export const SNAPTRADE_CONNECT_SUCCESS = 'snaptrade-connect-success' as const;
```
Export from `features/auth/index.ts` and `connectors/src/index.ts`.

### Step 2: Fix PlaidSuccess.tsx — add postMessage
**File:** `frontend/packages/ui/src/pages/PlaidSuccess.tsx`
Add at top of the existing useEffect (before setTimeout):
```ts
if (window.opener) {
  window.opener.postMessage({ type: PLAID_CONNECT_SUCCESS }, window.location.origin);
}
```
Import `PLAID_CONNECT_SUCCESS` from `@risk/connectors`. Message fires on mount, parent gets it before popup closes.

### Step 3: Fix SnapTradeSuccess.tsx — add postMessage
**File:** `frontend/packages/ui/src/pages/SnapTradeSuccess.tsx`
Same pattern with `SNAPTRADE_CONNECT_SUCCESS`.

### Step 4: Fix usePlaid.ts — return promises from refresh methods
**File:** `frontend/packages/connectors/src/features/external/hooks/usePlaid.ts`
Lines 338-351: Add `return` before `refetchConnections()` and `refetchHoldings()`.
Backward-compatible — void callers unaffected, await callers now actually wait.

### Step 5: Fix useSnapTrade.ts — return promises from refresh methods
**File:** `frontend/packages/connectors/src/features/external/hooks/useSnapTrade.ts`
Lines 332-349: Add `return` before `refetchConnections()` / `refetchHoldings()`. Return `Promise.resolve()` for the disabled-guard branch.

### Step 6: Rewrite useConnectAccount.ts monitorPopupClosure
**File:** `frontend/packages/connectors/src/features/auth/hooks/useConnectAccount.ts`

Replace the current `monitorPopupClosure` (lines 60-160) with dual-signal approach:

**Signal 1 (postMessage):** Listen for `PLAID_CONNECT_SUCCESS`. Verify BOTH:
- `event.origin === window.location.origin`
- `event.origin === window.location.origin` AND `event.source === popup` (origin + source ref check)

On valid message:
1. Set `isCheckingStatus: true`
2. Use `refetchQueries` with exact key for guaranteed-fresh read:
   ```ts
   await queryClient.refetchQueries({ queryKey: plaidConnectionsKey(userId), exact: true });
   const freshConnections = queryClient.getQueryData(plaidConnectionsKey(userId));
   ```
   Unlike `invalidateQueries` + `getQueryData`, `refetchQueries` guarantees the cache entry is updated from the network before we read it. The `exact: true` ensures we target the specific user-scoped query, not a prefix match.
3. **Confirm success** using TWO signals (not just count):
   - **Signal A (count):** Check if `freshConnections.length > initialConnectionCount`
   - **Signal B (timestamp):** Check if any connection has `last_updated` newer than `attemptStartTime` (captured before popup opened)
   - If EITHER signal confirms → resolve `{ status: 'confirmed', hasNewConnection: true }`
   - If neither → wait 2s and retry once. After retry, if still no confirmation → `setState(prev => ({ ...prev, pendingSync: true }))` THEN resolve `{ status: 'pending_sync', hasNewConnection: false }`. The state write triggers the Step 11 recovery useEffect.

   The timestamp signal handles the case where adding accounts to an already-connected institution doesn't increase connection count (Plaid is "one connection per institution, aggregates multiple accounts"). Note: this is a heuristic — an unrelated background Plaid refresh could also update `last_updated`. However, this is acceptable because: (a) the user just completed a Plaid flow, so a fresh timestamp is strongly correlated with their action, and (b) false-positive "confirmed" is better than false-negative "pending_sync" — the data will be correct either way, it's only the UI feedback that differs.

**Baseline safety:** `initialConnectionCount` and `attemptStartTime` must only be captured AFTER the connections query has loaded. Check `connections == null` (both hooks normalize unloaded data to `null`, not `undefined`). If null, `await queryClient.refetchQueries(...)` to force load before capturing baseline. `attemptStartTime = new Date()` captured at popup-open time. Same pattern for SnapTrade `initialSnapTradeCount`.

**Attempt reset:** At the START of every `connectAccount()` call, hard-reset: `setState(prev => ({ ...prev, pendingSync: false, initialConnectionCount: 0, attemptStartTime: null }))`. This prevents a prior attempt's recovery useEffect from bleeding into the new attempt with stale baselines. The baselines are then re-captured fresh after the query-loaded check above.

**Re-entrancy guard:** Add a synchronous `inFlightRef = useRef(false)` to both hooks. At the start of `connectAccount()`, check `if (inFlightRef.current) return undefined;` then set `inFlightRef.current = true`. Clear it in `finally` block. React state (`isConnecting`) is async and can't prevent two same-tick calls — the ref is synchronous and catches this edge case.

**Unique popup names:** Use a unique popup name per attempt to prevent browser WindowProxy reuse across multiple mounted hook instances. Generate via `const popupName = 'plaid-link-' + crypto.randomUUID()` (or `'snaptrade-' + crypto.randomUUID()`). This doesn't require changing the provider redirect URL — the popup name is purely a browser-side window identifier. Combined with `event.source === popup` check, this guarantees the postMessage comes from THIS attempt's exact popup window.

**Caller wiring for pendingSync:**

**AccountConnectionsContainer** (line 799): Branch on discriminated union status:
```ts
switch (result.status) {
  case 'confirmed':
    // Full success — data is fresh
    setSelectedProvider("");
    break;
  case 'pending_sync':
    // Connected but backend slow — hook self-heals via useEffect
    toast({ title: "Account Connected", description: "Syncing data — this may take a moment." });
    setSelectedProvider("");
    break;
  case 'cancelled':
    // User closed popup without completing
    break;
}
```
Note: No manual 5s setTimeout needed here — the hook's own `useEffect` (Step 11) handles recovery automatically.
5. On confirmed success:
   - `await queryClient.invalidateQueries({ queryKey: ['plaidHoldings'] })`
   - `await queryClient.invalidateQueries({ queryKey: ['portfolios'] })`
   - `await queryClient.invalidateQueries({ queryKey: ['portfolioSummary'] })`
   - **Best-effort holdings refresh:** `IntentRegistry.triggerIntent('refresh-holdings', ...).catch(() => {})` — catch and log, don't treat holdings failure as connection failure
   - Resolve with `{ status: 'confirmed', hasNewConnection: true }`
6. Set `isCheckingStatus: false`

**Why initialConnectionCount is safe here:** It's captured once at popup-open time (not from a stale closure in a memoized callback). The postMessage handler reads it from a local variable in the Promise scope, not from React state.

**Why staleTime: Infinity doesn't block this:** `invalidateQueries` with `await` forces a network refetch regardless of staleTime. The Infinity staleTime only prevents *automatic* refetches — explicit invalidation always fetches fresh data.

**Signal 2 (popup.closed fallback):** Poll `popup.closed` every 1s. When detected:
- Wait 1s grace period for postMessage to arrive (the message fires on mount, before close)
- If still not settled AND `confirmationInFlight` is false:
  - Do one last refetch/baseline check (same dual-signal) — catches cases where success page closed before postMessage script ran
  - If confirmed → resolve `{ status: 'confirmed', hasNewConnection: true }`
  - If not → resolve `{ status: 'cancelled', hasNewConnection: false }`

**Popup blocker handling:** If `window.open()` returns `null`, immediately clear `isConnecting`, set error state, and return `{ status: 'cancelled', hasNewConnection: false }`. No monitor setup needed. This is already handled in the existing code (Plaid line 198, SnapTrade line 155) — preserve it in the rewrite.

**Race prevention:** When a valid postMessage is received, immediately set a `confirmationInFlight = true` flag BEFORE starting async work. The popup.closed fallback checks this flag — if `confirmationInFlight` is true, it does NOT resolve as cancelled but instead waits for confirmation to finish. This prevents the closed-poll from racing against the async invalidate/confirm/resolve chain.

**Cleanup:** `settle()` helper does ALL cleanup: removes message listener, clears popup.closed interval, closes the popup window (`popup.close()`), and resolves the promise (idempotent via `settled` flag). After `settle()`, all async paths check `settled` before calling `setState` — this prevents late confirmation from hitting state after unmount. `useEffect` return calls `settle({ status: 'cancelled', hasNewConnection: false })` on unmount. The existing exported `cleanup()` callback also calls `settle()`.

**Key change:** Remove `connections` from dependency array entirely. No stale closure, no count comparison.

### Step 7: Fix useConnectSnapTrade.ts — popup monitor (popup path only)
**File:** `frontend/packages/connectors/src/features/auth/hooks/useConnectSnapTrade.ts`

**Two paths, only popup gets the monitor:**

The `connectAccount()` function currently does two things:
1. Registers user + creates connection URL (lines 97-140)
2. Opens popup + sets isConnecting=false (lines 148-165)

**Change:** Split the popup path. After `window.open()` (line 149), instead of immediately setting `isConnecting=false` (line 164), await a `monitorSnapTradePopup(popup)`:

```ts
const result = await monitorSnapTradePopup(popup);
// Returns ConnectResult: { status: 'confirmed'|'pending_sync'|'cancelled' }
// monitorSnapTradePopup owns ALL popup-path side effects.
setState(prev => ({ ...prev, isConnecting: false }));
return result;
```

**`monitorSnapTradePopup` function:** Same dual-signal pattern as Plaid, INCLUDING backend confirmation:
- postMessage listener (verify `event.origin === window.location.origin`)
- On message: `await refetchQueries({ queryKey: snaptradeConnectionsKey(userId), exact: true })`, read cache, confirm count increased using `countDistinctAuthorizations(fresh)` (reuse from `useConnectionFlow.ts` line 11 — counts unique `authorization_id` values, not raw array length, to handle multi-account authorizations). If not → retry once after 2s. If still unchanged → `setState({ pendingSync: true })` then resolve `{ status: 'pending_sync', hasNewConnection: false }`. State write triggers recovery useEffect.
- On confirmed: invalidate `snaptradeConnections` + `snaptradeHoldings` + `portfolios` + `portfolioSummary` (full freshness, matching Plaid flow). Update state to `connected`. Resolve `{ status: 'confirmed', hasNewConnection: true }`. Note: `handleConnectionSuccess()` is NOT called here — the monitor owns side effects for the popup path. `handleConnectionSuccess` remains for the modal path only (SnapTradeLaunchButton).
- popup.closed fallback with 1s grace → resolve `{ status: 'cancelled', hasNewConnection: false }`
- `settle()` for cleanup

**Return contract:** `connectAccount()` now returns `Promise<ConnectSnapTradeResult | undefined>` using the discriminated union:
- Returns result object when popup path is used (AccountConnectionsContainer)
- Returns `undefined` when early-exiting (disabled/unauthenticated guards at lines 79-95)
- The modal path (SnapTradeLaunchButton) calls `connectAccount()` to get `state.connectionUrl`, then opens SnapTradeReact modal. It only uses the staging side-effect, not the return value. The popup is NOT opened when SnapTradeLaunchButton is the consumer because it opens a modal instead — `state.connectionUrl` is set at line 139, and `SnapTradeLaunchButton` reads it at line 119 to decide whether to open the modal.

**Wait — the popup opens unconditionally at line 149.** This means SnapTradeLaunchButton currently opens BOTH a popup AND a modal. That's a bug. But it's pre-existing and out of scope. The monitor only wraps the popup it opened — the modal has its own callback system.

Actually, re-reading SnapTradeLaunchButton more carefully: it calls `await connectAccount()` at line 116, which currently opens the popup. Then at line 119 it checks `state.connectionUrl` and opens the modal. So the user gets both a popup and a modal. This is indeed a pre-existing bug, but our change makes it worse because now `connectAccount()` blocks until the popup is done.

**Fix:** Guard the `window.open()` behind an `openPopup` option. Return the connection URL directly so callers don't need to read stale `state.connectionUrl`:

```ts
interface ConnectSnapTradeOptions { openPopup?: boolean }
// Discriminated union forces exhaustive handling
type ConnectResult =
  | { status: 'confirmed'; hasNewConnection: true }
  | { status: 'pending_sync'; hasNewConnection: false }
  | { status: 'cancelled'; hasNewConnection: false }
  | { status: 'ready'; hasNewConnection: false; connectionUrl: string } // modal path: URL staged, caller opens modal

// Plaid uses ConnectResult (no 'ready' — always popup)
// SnapTrade uses ConnectSnapTradeResult (includes 'ready' for modal path)
type ConnectSnapTradeResult = ConnectResult | { status: 'ready'; hasNewConnection: false; connectionUrl: string }

const connectAccount = useCallback(async (options?: ConnectSnapTradeOptions): Promise<ConnectSnapTradeResult | undefined> => {
  const shouldOpenPopup = options?.openPopup !== false; // default true
  ...
  // After URL creation (line 139):
  if (shouldOpenPopup) {
    const popup = window.open(...);
    const result = await monitorSnapTradePopup(popup);
    // monitorSnapTradePopup owns ALL side effects (invalidation, state) for popup path.
    // No handleConnectionSuccess() call — that's modal-only.
    // isConnecting is cleared inside settle() — no setState here (avoids late update after unmount).
    return result;
  }
  // Modal path: synchronous return, no async monitor — safe to setState directly
  inFlightRef.current = false;
  setState(prev => ({ ...prev, isConnecting: false, connectionUrl: urlResponse.connection_url }));
  return { status: 'ready', hasNewConnection: false, connectionUrl: urlResponse.connection_url };
}, [snapTrade, queryClient]);
```

**SnapTradeLaunchButton update:** Replace stale-closure pattern:
```ts
// OLD (stale closure):
await connectAccount();
if (state.connectionUrl) { setIsModalOpen(true); }

// NEW (direct return, exhaustive check):
const result = await connectAccount({ openPopup: false });
if (result?.status === 'ready') { setIsModalOpen(true); }
```
No more reading `state.connectionUrl` from a previous render.

AccountConnectionsContainer calls `connectSnapTradeAccount()` (default popup=true), gets `ConnectSnapTradeResult` back (discriminated union with `status`).

### Step 8: Update useConnectionFlow.ts for new blocking contract
**File:** `frontend/packages/ui/src/components/connections/hooks/useConnectionFlow.ts`

`startSnapTradeFlow` (line 174) currently does:
```ts
await snapTradeConnection.connectAccount(); // was non-blocking, now blocks until popup settles
setState({ step: 'polling', ... }); // starts 2.5s polling
```

Update to use the result from the now-blocking `connectAccount()`:
```ts
const result = await snapTradeConnection.connectAccount();
switch (result?.status) {
  case 'confirmed':
  case 'pending_sync': // hook self-heals via useEffect
    stopSnapTradePolling();
    setState({ step: 'connected', ... });
    break;
  case 'cancelled':
  default:
    setState({ step: 'idle', ... });
}
```

This removes the redundant polling loop for the popup path since `connectAccount()` now handles confirmation internally.

### Step 9: Automatic cleanup via useEffect
**File:** `frontend/packages/connectors/src/features/auth/hooks/useConnectAccount.ts`

Add a `useEffect` cleanup for the message listener + interval:
```ts
const cleanupRef = useRef<(() => void) | null>(null);

useEffect(() => {
  return () => { cleanupRef.current?.(); };
}, []);
```

Inside `monitorPopupClosure`, set `cleanupRef.current = () => settle(...)` so unmount triggers cleanup automatically.

Same pattern in `useConnectSnapTrade.ts`.

### Step 10: Upgrade handleConnectionSuccess for modal path
**File:** `frontend/packages/connectors/src/features/auth/hooks/useConnectSnapTrade.ts`

The modal path (SnapTradeLaunchButton → SnapTradeReact `onSuccess` → `handleConnectionSuccess()`) has the same "success signal != backend ready" race. Upgrade to async with confirmation:

```ts
// initialSnapTradeCount captured at connectAccount() call time and stored in state/ref
const handleConnectionSuccess = useCallback(async () => {
  // Same confirm-or-pendingSync pattern as popup path
  await queryClient.refetchQueries({ queryKey: snaptradeConnectionsKey(userId), exact: true });
  const fresh = queryClient.getQueryData(snaptradeConnectionsKey(userId));
  const confirmed = countDistinctAuthorizations(fresh) > state.initialSnapTradeCount; // same helper as popup path // captured at connect start, not at callback creation

  if (confirmed) {
    await queryClient.refetchQueries({ queryKey: snaptradeHoldingsKey(userId), exact: true });
    void queryClient.invalidateQueries({ queryKey: ['portfolios'] });
    void queryClient.invalidateQueries({ queryKey: ['portfolioSummary'] });
  }

  setState(prev => ({
    ...prev,
    currentStep: 'connected',
    connectionUrl: null,
    pendingSync: !confirmed,
  }));
}, [queryClient, userId, initialSnapTradeCount]);
```

SnapTradeLaunchButton's `onConnectionSuccess` calls this and it's now async. The `await` at the call site is optional — fire-and-forget is fine since the hook manages its own state.

### Step 11: Hook-owned pendingSync recovery
**File:** `frontend/packages/connectors/src/features/auth/hooks/useConnectAccount.ts` and `useConnectSnapTrade.ts`

Add a `useEffect` in each hook that retries with backoff when `state.pendingSync` is true:

```ts
useEffect(() => {
  if (!state.pendingSync) return;
  let attempt = 0;
  const maxAttempts = 4; // 3s, 6s, 12s, 24s — covers ~45s total
  let timer: NodeJS.Timeout;

  const tryConfirm = async () => {
    attempt++;
    await queryClient.refetchQueries({ queryKey: connectionKey, exact: true });
    const fresh = queryClient.getQueryData(connectionKey);
    // Use SAME dual-signal as initial confirmation:
    // Signal A: count increased
    // Signal B: any connection has last_updated > attemptStartTime (Plaid)
    //           or distinct authorization count increased (SnapTrade)
    const countConfirmed = (fresh?.length || 0) > initialCount;
    const timestampConfirmed = fresh?.some((c: any) => new Date(c.last_updated) > attemptStartTime);
    if (countConfirmed || timestampConfirmed) {
      setState(prev => ({ ...prev, pendingSync: false }));
      // Refresh ALL dependent queries — holdings, portfolios, summary
      void queryClient.invalidateQueries({ queryKey: ['plaidHoldings'] });
      void queryClient.invalidateQueries({ queryKey: ['snaptradeHoldings'] });
      void queryClient.invalidateQueries({ queryKey: ['portfolios'] });
      void queryClient.invalidateQueries({ queryKey: ['portfolioSummary'] });
      return; // confirmed — done
    }
    if (attempt < maxAttempts) {
      timer = setTimeout(tryConfirm, 3000 * Math.pow(2, attempt - 1)); // 3s, 6s, 12s, 24s
    }
    // After maxAttempts: leave pendingSync true — user sees "syncing" and can manual refresh
  };

  timer = setTimeout(tryConfirm, 3000); // first retry after 3s
  return () => clearTimeout(timer);
}, [state.pendingSync, queryClient]);
```

This covers ~45s of backend persistence lag with 4 retries. Both `staleTime: Infinity` and `refetchOnWindowFocus: false` mean no automatic recovery, so the hook MUST retry. After max attempts, `pendingSync` stays true — the sync button in the UI provides manual fallback.

### Step 12: Update tests

**`features/auth/__tests__/useConnectAccount.test.tsx`:**
- Update tests that rely on 3s setTimeout + count comparison → postMessage flow
- Add: "resolves success when postMessage received from popup"
- Add: "awaits query invalidation before resolving"
- Add: "resolves cancel when popup.closed without postMessage"
- Add: "ignores postMessage from wrong origin"
- Add: "ignores postMessage from wrong source (not the popup)"
- Add: "cleans up listener on unmount"
- Add: "cleans up listener on settle"

**`features/auth/__tests__/useConnectSnapTrade.test.tsx`:**
- Add: "keeps isConnecting=true until popup signal"
- Add: "returns { status: 'confirmed' } on postMessage"
- Add: "returns { status: 'cancelled' } when popup closed without message"
- Add: "does not open popup when openPopup=false"

**`features/external/__tests__/usePlaid.test.tsx`:**
- Verify refreshConnections/refreshHoldings return promises

## Files Modified
| File | Change |
|------|--------|
| `connectors/src/features/auth/connectEvents.ts` | **New**: event constants |
| `connectors/src/features/auth/index.ts` | Export constants |
| `connectors/src/index.ts` | Re-export constants |
| `ui/src/pages/PlaidSuccess.tsx` | Add postMessage |
| `ui/src/pages/SnapTradeSuccess.tsx` | Add postMessage |
| `connectors/src/features/external/hooks/usePlaid.ts` | Return promises from refresh |
| `connectors/src/features/external/hooks/useSnapTrade.ts` | Return promises from refresh |
| `connectors/src/features/auth/hooks/useConnectAccount.ts` | Rewrite monitorPopupClosure + useEffect cleanup |
| `connectors/src/features/auth/hooks/useConnectSnapTrade.ts` | Add popup monitor + openPopup param + useEffect cleanup |
| `ui/src/components/snaptrade/SnapTradeLaunchButton.tsx` | Pass `{ openPopup: false }`, read URL from return |
| `ui/src/components/connections/hooks/useConnectionFlow.ts` | Branch on result.status, remove redundant polling |
| `ui/src/components/dashboard/views/modern/HoldingsViewModernContainer.tsx` | Branch on result — skip refresh on cancel AND pending_sync (hook owns retry) |
| Test files (3-4) | Update + new test cases |

## Verification
1. `npx tsc --noEmit` — type check
2. `npx vitest run useConnectAccount useConnectSnapTrade usePlaid useSnapTrade` — run tests
3. Browser: Connect Plaid → popup → complete → parent detects success, data refreshes
4. Browser: Connect SnapTrade via Settings → popup → complete → parent stays loading until done, data refreshes
5. Browser: SnapTradeLaunchButton (modal path) → still works, no popup opened
6. Browser: Close popup manually (cancel) → parent resolves as cancelled
7. Verify AccountConnectionsContainer still works (now gets proper return value from connectSnapTradeAccount)

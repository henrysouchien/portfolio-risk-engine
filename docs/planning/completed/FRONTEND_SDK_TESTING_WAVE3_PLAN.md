# Frontend SDK Testing — Wave 3 Plan

**Status:** Planning
**Prerequisite:** Wave 2 complete (246 tests, 26 hook test files, commit `54b82f63`)
**Target:** ~185 tests across 16 hooks
**Convention:** Same patterns as Wave 2 — `renderHookWithQuery`, `vi.mock`, `waitFor`/`act`, `__tests__/` sibling dirs

---

## Scope Decision: UI Re-Export Wrappers

The `ui` package contains 6+ feature index files that are 1-line `export * from '@risk/connectors'` re-exports. These are **out of scope** — testing them adds no value (no logic, no transformation). Wave 3 focuses exclusively on the **connectors-package implementations** where the actual hook logic lives.

---

## Hook Inventory

| # | Hook | Package | Lines | Category | Phase |
|---|------|---------|-------|----------|-------|
| 1 | useCancelableRequest | connectors | 35 | Utility | A |
| 2 | useCancellablePolling | connectors | 59 | Utility | A |
| 3 | useChat | connectors | 9 | Re-export alias | A |
| 4 | usePendingUpdates | connectors | 78 | Query | A |
| 5 | usePlaid | connectors | 410 | SDK/Query+Mutation | B |
| 6 | useSnapTrade | connectors | 397 | SDK/Query+Mutation | B |
| 7 | usePlaidPolling | connectors | 172 | Polling | B |
| 8 | useAuthFlow | connectors | 248 | Auth/State | C |
| 9 | useConnectAccount | connectors | 239 | Auth/Popup | C |
| 10 | useConnectSnapTrade | connectors | 298 | Auth/State Machine | C |
| 11 | usePortfolioOptimization | connectors | 295 | Query+Adapter | D |
| 12 | useInstantAnalysis | connectors | 213 | Workflow | D |
| 13 | useWhatIfAnalysis | connectors | 500 | Query+State+Input | D |
| 14 | usePortfolioSummary | connectors | 399 | Multi-Query | D |
| 15 | useRiskSettings | connectors | 490 | Query+Adapter+Mutation | D |
| 16 | usePortfolioChat | connectors | 970 | Streaming+State | E |

---

## Phase A — Quick Wins (4 hooks, ~20 tests)

Simple utilities, one alias, and one straightforward query hook. No external SDK deps.

### A1. useCancelableRequest (~6 tests)
**File:** `frontend/packages/connectors/src/features/utils/hooks/useCancelableRequest.ts` (35 lines)
**Test:** `frontend/packages/connectors/src/features/utils/__tests__/useCancelableRequest.test.tsx`

**Pattern:** AbortController wrapper. `executeOperation(asyncFn)` → passes AbortSignal, catches AbortError → null.

**Tests:**
1. Returns `executeOperation` function
2. `executeOperation` passes AbortSignal to async function
3. Returns result from successful operation
4. Returns null when operation is aborted (AbortError caught)
5. Aborts pending operation on unmount (useEffect cleanup)
6. Re-throws non-abort errors

**Mocks:** Async operation functions. AbortController is native in jsdom.

---

### A2. useCancellablePolling (~5 tests)
**File:** `frontend/packages/connectors/src/features/utils/hooks/useCancellablePolling.ts` (59 lines)
**Test:** `frontend/packages/connectors/src/features/utils/__tests__/useCancellablePolling.test.tsx`

**Pattern:** `useCancellablePolling(pollFn, interval)` — calls `pollFn()` immediately, schedules `setTimeout(poll, interval)` while `pollFn()` returns false. Internal AbortController in useEffect cleanup aborts on unmount. No external callbacks — the hook is fire-and-forget; `pollFn` itself handles side effects.

**Actual API:** `(pollFn: () => boolean, interval: number) => void` — no return value, no `onComplete`, no `onError`, no external AbortSignal parameter.

**Tests:**
1. Calls `pollFn` immediately on mount
2. Repeats `pollFn` on interval when it returns false
3. Stops polling when `pollFn` returns true (no more setTimeout scheduled)
4. Clears timeout on unmount (internal AbortController aborts + clearTimeout)
5. Re-runs polling when `pollFn` or `interval` dependency changes (useEffect deps)

**Mocks:** `vi.useFakeTimers()` for setTimeout control.

---

### A3. useChat (~2 tests)
**File:** `frontend/packages/connectors/src/features/external/hooks/useChat.ts` (9 lines)
**Test:** `frontend/packages/connectors/src/features/external/__tests__/useChat.test.tsx`

**Pattern:** Re-exports `usePortfolioChat` as `useChat` at module level (line 972 of usePortfolioChat.ts: `export const useChat = usePortfolioChat`). Backward-compat alias.

**Tests:**
1. `useChat` is identical reference to `usePortfolioChat`
2. Module exports include `useChat`

**Mocks:** None — static import verification only.

---

### A4. usePendingUpdates (~8 tests)
**File:** `frontend/packages/connectors/src/features/portfolio/hooks/usePendingUpdates.ts` (78 lines)
**Test:** `frontend/packages/connectors/src/features/portfolio/__tests__/usePendingUpdates.test.tsx`

**Pattern:** `useQueries` — parallel polling of Plaid + SnapTrade pending status. 60s staleTime, 5min refetchInterval.

**Tests:**
1. Initial state: `hasPendingUpdates=false`, `plaidPending=false`, `snaptradePending=false`
2. Returns `hasPendingUpdates=true` when Plaid has pending
3. Returns `hasPendingUpdates=true` when SnapTrade has pending
4. Returns `hasPendingUpdates=true` when both have pending
5. Disabled when no user (`useAuthStore` returns null user)
6. Calls correct API methods (plaid pending check, snaptrade pending check)
7. `refetch` triggers both queries
8. Error in one query doesn't block the other

**Mocks:** `useSessionServices`, `useAuthStore`, TanStack Query (via `renderHookWithQuery`).

---

## Phase B — External SDK Integration (3 hooks, ~55 tests)

Plaid and SnapTrade — session-long caching (`staleTime: Infinity`), multi-query/mutation, feature flags.

### B1. usePlaid (~24 tests)
**File:** `frontend/packages/connectors/src/features/external/hooks/usePlaid.ts` (410 lines)
**Test:** `frontend/packages/connectors/src/features/external/__tests__/usePlaid.test.tsx`

**Pattern:** 2 queries (connections, holdings) with `staleTime: Infinity` + 5 mutations (createLinkToken, exchangePublicToken, disconnectConnection, reauthConnection, deleteUser). Holdings query gated on connections existing. Refetch on mutation success.

**Actual return shape:** `connections: data | null` (not `[]`), `holdings: data | null` (not `[]`).

**Tests — Queries:**
1. Initial state: `connections=null`, `holdings=null`, isLoading flags
2. Loads connections on mount (calls API)
3. Holdings query gated on connections — only fires when connections exist
4. Disabled when no userId (`useAuthStore`)
5. Session-long cache: no refetch on remount (`staleTime: Infinity`)
6. `hasConnections` computed correctly (true when connections array non-empty)
7. `hasHoldings` computed correctly (true when holdings array non-empty)
8. `hasError` reflects query error state

**Tests — Mutations:**
9. `createLinkToken` calls `api.createLinkToken(user.id)`, returns `{ link_token, hosted_link_url }`
10. `createLinkToken` error surfaces to hook
11. `exchangePublicToken` calls `api.exchangePublicToken()` with public_token
12. `exchangePublicToken` success triggers `refetchConnections()`
13. `disconnectConnection` calls `api.disconnectPlaidConnection(itemId)`
14. `disconnectConnection` onSuccess refetches connections only (not holdings)
15. `reauthConnection` calls `api.createUpdateLinkToken(itemId)` — opens popup + interval monitoring + 3s delay + refetchConnections
16. `deleteUser` calls `api.deletePlaidUser()`
17. `deleteUser` onSuccess refetches connections only (not holdings)

**Tests — Computed State & Methods:**
18. `isLoading` true while any query pending
19. `refreshConnections` delegates to connections query refetch
20. `refreshHoldings` delegates to holdings query refetch
21. Error from API surfaces to hook error state
22. `isAuthenticated` reflects userId presence

**Tests — Reauth Popup Flow:**
23. `reauthConnection` opens popup via `window.open`, monitors `popup.closed` via `setInterval`
24. After popup closes, 3s delay then `refetchConnections()`

**Mocks:** `useSessionServices` (`api` — direct methods like `api.getConnections()`, `api.disconnectPlaidConnection()`, etc.), `useAuthStore`, `renderHookWithQuery`, `window.open`.

---

### B2. useSnapTrade (~20 tests)
**File:** `frontend/packages/connectors/src/features/external/hooks/useSnapTrade.ts` (397 lines)
**Test:** `frontend/packages/connectors/src/features/external/__tests__/useSnapTrade.test.tsx`

**Pattern:** Mirrors usePlaid. Feature-flagged (`config.enableSnapTrade`). Graceful degradation when disabled. `connections: data | null`, `holdings: data | null`.

**Tests — Feature Flag:**
1. Disabled flag: queries disabled, returns `connections: null`, `holdings: null`, `isEnabled=false`
2. Enabled flag: queries fire normally, `isEnabled=true`

**Tests — Queries:**
3. Initial state: `connections=null` (from `connections ?? null`), `holdings=null`
4. Loads connections on mount via `api.getSnapTradeConnections()`
5. Holdings query gated on connections existing
6. Disabled when no userId
7. Session-long cache (`staleTime: Infinity`)
8. `hasConnections` / `hasHoldings` computed correctly

**Tests — Mutations:**
9. `registerUser` calls `api.registerSnapTradeUser()` via mutation
10. `createConnectionUrl` calls API, returns `{ success, connection_url }`
11. `disconnectConnection` calls API + triggers refetchConnections AND refetchHoldings on success
12. `disconnectUser` calls API + triggers refetchConnections AND refetchHoldings on success

**Tests — Graceful Degradation:**
13. Service unavailable (`message === 'SnapTrade service unavailable'`) returns `[]` connections gracefully (no error thrown)
14. `clearError` resets all mutation error states via `.reset()`

**Tests — Computed State:**
15. `isLoading` true while any query pending
16. `refreshConnections` delegates to query refetch (gated on `isEnabled`)
17. `refreshHoldings` delegates to query refetch (gated on `isEnabled`)
18. `isAuthenticated` reflects userId presence
19. Error string aggregated from all query + mutation errors
20. `isEnabled` reflects `config.enableSnapTrade`

**Mocks:** `useSessionServices`, `useAuthStore`, `config` module, `renderHookWithQuery`.

---

### B3. usePlaidPolling (~10 tests)
**File:** `frontend/packages/connectors/src/features/utils/hooks/usePlaidPolling.ts` (172 lines)
**Test:** `frontend/packages/connectors/src/features/utils/__tests__/usePlaidPolling.test.tsx`

**Pattern:** Wraps user-scoped `PlaidPollingService` from SessionServices. Token tracking via `activeTokensRef` for multi-user safety. Returns `{ startPolling, stopPolling, stopAllPolling, isPolling, getActiveCount }`.

**Tests:**
1. Returns `startPolling`, `stopPolling`, `stopAllPolling`, `isPolling`, `getActiveCount`
2. `startPolling` delegates to `plaidPolling.startPolling` with wrapped callbacks
3. `startPolling` tracks token in `activeTokensRef` (`getActiveCount` increments)
4. `stopPolling` delegates to `plaidPolling.stopPolling` and removes token from tracking
5. `stopAllPolling` stops all tracked tokens and clears ref
6. Success callback unwraps result — validates `public_token` string field present
7. Success callback with malformed payload (missing `public_token`) calls onError instead
8. Error callback receives error and removes token from tracking
9. Cleanup on unmount stops all active polling (`plaidPolling.stopPolling` for each)
10. `isPolling` delegates to `plaidPolling.isPolling`

**Mocks:** `useSessionServices` (`plaidPolling` service mock with `startPolling`, `stopPolling`, `isPolling` methods).

---

## Phase C — Auth & Connection (3 hooks, ~38 tests)

OAuth flows, popup lifecycle management, state machines.

### C1. useAuthFlow (~14 tests)
**File:** `frontend/packages/connectors/src/features/auth/hooks/useAuthFlow.ts` (248 lines)
**Test:** `frontend/packages/connectors/src/features/auth/__tests__/useAuthFlow.test.tsx`

**Pattern:** Google OAuth with AuthManager. `isLoading` hardcoded `false` (TODO in source), `error` hardcoded `null` (TODO in source). signIn calls `authManager.handleGoogleSignIn(idToken)`. signOut calls `authManager.signOut()` then `onLogout()`. Uses `useAuthStore` for `user`/`isAuthenticated` + `useUIActions` for `setViewLoading`/`setViewError`.

**Actual API:**
- State: `{ isAuthenticated, user, isLoading: false, error: null, hasError: false, isIdle: true }`
- Methods: `signIn(idToken) → AuthFlowResult`, `signOut()`, `login(provider?)`, `logout()`, `checkAuthStatus()`, `clearError()`

**Tests — State:**
1. `isAuthenticated` and `user` come from `useAuthStore`
2. `isLoading` is always `false` (hardcoded TODO)
3. `error` is always `null` (hardcoded TODO)
4. `hasError` is `false`, `isIdle` is `true`

**Tests — signIn:**
5. `signIn(idToken)` calls `authManager.handleGoogleSignIn(idToken)` (not `authenticate`)
6. `signIn` success calls `storeSignIn(user, '')` and returns `{ success: true, user }`
7. `signIn` failure returns `{ success: false, error }` and calls `setViewError('auth', msg)`
8. `signIn` sets `setViewLoading('auth', true)` before call, `false` in finally

**Tests — signOut:**
9. `signOut` calls `authManager.signOut()` then `onLogout()`
10. `signOut` calls `onLogout()` even if `authManager.signOut()` throws (error recovery)
11. `signOut` sets `setViewLoading('auth', true/false)` around call

**Tests — Compatibility:**
12. `login('google')` delegates to `signIn` with mock token
13. `logout()` delegates to `signOut`
14. `checkAuthStatus` returns `{ isAuthenticated: true, user }` when authenticated, calls `storeSignOut` when not

**Mocks:** `AuthManager` class (constructor mock), `APIService` class, `useAuthStore`/`useAuthActions` from `@risk/chassis`, `useUIActions`, `onLogout` from sessionCleanup, `frontendLogger`.

**Special setup:** Mock `useMemo` to capture AuthManager/APIService construction, or mock the module constructors directly.

---

### C2. useConnectAccount (~13 tests)
**File:** `frontend/packages/connectors/src/features/auth/hooks/useConnectAccount.ts` (239 lines)
**Test:** `frontend/packages/connectors/src/features/auth/__tests__/useConnectAccount.test.tsx`

**Pattern:** Popup lifecycle. Returns `{ state, connectAccount, clearError, cleanup }` where `state` is a **nested object** `ConnectAccountState { isConnecting, isCheckingStatus, error, lastConnectionAttempt }`. `connectAccount()` calls `createLinkToken()` → `window.open(hosted_link_url)` → `setInterval` polls `popup.closed` → 3s setTimeout → `refreshConnections()` → compares connection count → `queryClient.invalidateQueries`.

**Race condition note:** After popup closes, `refreshConnections()` is called, then `connections.length` is read from the closed-over value (may not reflect the refetch). This is a known limitation worth a regression test.

**Tests — State:**
1. Initial `state`: `{ isConnecting: false, isCheckingStatus: false, error: null, lastConnectionAttempt: null }`
2. `clearError` sets `state.error` to null

**Tests — Connect Flow:**
3. `connectAccount` calls `createLinkToken()` from usePlaid
4. `connectAccount` opens popup via `window.open(hosted_link_url)`
5. Sets `state.isConnecting=true` when popup opens
6. Monitors `popup.closed` via `setInterval(checkClosed, 1000)`
7. Sets `state.isCheckingStatus=true` after popup detected closed
8. 3-second `setTimeout` delay before checking connection count
9. On new connection detected: invalidates `portfolioSummaryKey` queries, triggers `IntentRegistry.triggerIntent('refresh-holdings')`
10. On no new connection: sets `state.isCheckingStatus=false` (user cancelled)

**Tests — Error Handling:**
11. Sets `state.error` when popup blocked (`window.open` returns null → "Failed to open Plaid Link")
12. Sets `state.error` when `createLinkToken` throws
13. Sets `state.error` when post-close status check throws

**Tests — Cleanup:**
~~13. Unmount clears interval (no leak)~~
Note: No useEffect unmount cleanup — `cleanup()` is a manual callback exposed to the consumer. Test that `cleanup()` clears the interval and closes the popup.

**Mocks:** `window.open`, `vi.useFakeTimers()` (setInterval + setTimeout), `usePlaid` (createLinkToken, refreshConnections, connections), `useQueryClient`, `IntentRegistry`, `frontendLogger`.

---

### C3. useConnectSnapTrade (~11 tests)
**File:** `frontend/packages/connectors/src/features/auth/hooks/useConnectSnapTrade.ts` (298 lines)
**Test:** `frontend/packages/connectors/src/features/auth/__tests__/useConnectSnapTrade.test.tsx`

**Pattern:** State machine: idle → registering → creating_url → opening_connection → connected. Returns `{ state, isEnabled, connectAccount, handleConnectionSuccess, handleConnectionError, handleConnectionExit, resetFlow, clearError, snapTrade }`.

**Key behavior:** Registration failure is **intentionally swallowed** (user may already be registered) — flow continues to URL creation. Gates on `snapTrade.isEnabled` and `snapTrade.isAuthenticated`. Opens popup via `window.open`.

**Tests — State Machine:**
1. Initial `state`: `{ currentStep: 'idle', isConnecting: false, isRegistering: false, isCreatingUrl: false, error: null, connectionUrl: null }`
2. `connectAccount` transitions idle → registering → creating_url → opening_connection (happy path)
3. `connectAccount` continues past registration failure (swallowed error)
4. `connectAccount` with successful URL sets `state.connectionUrl` and opens `window.open`
5. `handleConnectionSuccess` transitions to `connected`, calls `snapTrade.refreshConnections()`
6. `handleConnectionError(error)` sets `state.error`, resets `currentStep` to idle

**Tests — Guards:**
7. `connectAccount` sets error when `snapTrade.isEnabled=false` ("SnapTrade integration is not enabled")
8. `connectAccount` sets error when `snapTrade.isAuthenticated=false` ("User authentication required")

**Tests — Event Handlers & Reset:**
9. `handleConnectionExit` resets `currentStep` to idle, clears `connectionUrl`
10. `resetFlow` resets entire state to initial values
11. `clearError` clears `state.error` AND delegates to `snapTrade.clearError()`

**Mocks:** `useSnapTrade` (isEnabled, isAuthenticated, registerUser, createConnectionUrl, refreshConnections, clearError), `window.open`, `frontendLogger`.

---

## Phase D — Complex Query, Adapter & Workflow Hooks (5 hooks, ~55 tests)

Adapter composition, multi-query aggregation, trigger-based execution, bidirectional transformation.

### D1. usePortfolioOptimization (~12 tests)
**File:** `frontend/packages/connectors/src/features/optimize/hooks/usePortfolioOptimization.ts` (295 lines)
**Test:** `frontend/packages/connectors/src/features/optimize/__tests__/usePortfolioOptimization.test.tsx`

**Pattern:** useQuery with strategy state (`min_variance` | `max_return`). Query key includes strategy → auto-refetch on switch. AdapterRegistry transform.

**Tests:**
1. Initial state: `strategy='min_variance'`, `data=null`, `hasPortfolio` from `useCurrentPortfolio`
2. No query when portfolio missing (`hasPortfolio=false`)
3. Calls `manager.optimizeMinVariance()` for `min_variance` strategy
4. Calls `manager.optimizeMaxReturn()` for `max_return` strategy
5. `optimizeMinVariance()` is no-op from default state (already `min_variance`); switching back from `max_return` triggers refetch
6. `optimizeMaxReturn()` sets strategy to `max_return` → query key changes → triggers refetch
7. Data passes through `adapter.transform()`
8. Error from manager surfaces to hook (`error?.message`)
9. `isLoading` true during optimization
10. Query key includes portfolioId and strategy
11. `refetch` delegates to TanStack Query refetch
12. `hasData` computed correctly

**Mocks:** `useSessionServices` (manager), `useCurrentPortfolio`, `AdapterRegistry`, `renderHookWithQuery`.

---

### D2. useInstantAnalysis (~8 tests)
**File:** `frontend/packages/connectors/src/features/portfolio/hooks/useInstantAnalysis.ts` (213 lines)
**Test:** `frontend/packages/connectors/src/features/portfolio/__tests__/useInstantAnalysis.test.tsx`

**Pattern:** Returns only `{ analyzePortfolio, extractFromFile }` — **no local state API exposed**. Both are `useCallback` async methods returning `PortfolioFlowResult { success, error?, data? }`. Uses `setViewLoading`/`setViewError` from `useUIActions` for UI state. `analyzePortfolio` stores portfolio via `PortfolioRepository.add()` + `setCurrent()` before calling `manager.analyzePortfolioRisk()`.

**Tests — analyzePortfolio:**
1. Calls `PortfolioRepository.add(portfolioData)` and `PortfolioRepository.setCurrent(portfolioId)`
2. Calls `manager.analyzePortfolioRisk(portfolioId)` with the generated ID
3. Returns `{ success: true, data: result.analysis }` on success
4. Returns `{ success: false, error }` when manager returns error
5. Sets `setViewLoading('analysis', true/false)` around the call

**Tests — extractFromFile:**
6. Calls `manager.extractPortfolioData(file)`
7. Returns `{ success: true, data: portfolioData }` on success
8. Returns `{ success: false, error }` on failure, calls `setViewError('extraction', msg)`

**Mocks:** `useSessionServices` (manager.analyzePortfolioRisk, manager.extractPortfolioData), `PortfolioRepository` (static methods: add, setCurrent), `useUIActions` (setViewLoading, setViewError), `frontendLogger`.

---

### D3. useWhatIfAnalysis (~14 tests)
**File:** `frontend/packages/connectors/src/features/whatIf/hooks/useWhatIfAnalysis.ts` (500 lines)
**Test:** `frontend/packages/connectors/src/features/whatIf/__tests__/useWhatIfAnalysis.test.tsx`

**Pattern:** Disabled query (`enabled: false`) triggered by `runScenario(ScenarioParams)` which sets state + calls `refetch()` via `setTimeout(0)`. Input management uses **keyed Record<string, string> maps** (not arrays). `addAssetInput` generates key `ASSET_N`. `setInputMode` toggles `'weights'` | `'deltas'`. `runScenarioFromInputs` validates non-empty, creates `InputScenario`, calls `runScenario`. **No weight normalization** — values pass through as-is.

**Actual return shape:** `{ data, loading, isLoading, isRefetching, error, refetch, refreshWhatIfAnalysis, hasData, hasError, hasPortfolio, currentPortfolio, clearError, scenarioId, runScenario, inputMode, setInputMode, weightInputs, deltaInputs, addAssetInput, removeAssetInput, updateAssetName, updateAssetValue, runScenarioFromInputs }`

**Tests — Input Management:**
1. Initial `inputMode='weights'`, `weightInputs={}`, `deltaInputs={}`
2. `addAssetInput()` adds `ASSET_1: ''` to current mode's map (keyed, not indexed)
3. `removeAssetInput('ASSET_1')` removes key from current mode's map
4. `updateAssetName('ASSET_1', 'AAPL')` renames key preserving value
5. `updateAssetValue('AAPL', '0.25')` sets value for key
6. `setInputMode('deltas')` switches mode; inputs are independent per mode

**Tests — Scenario Execution:**
7. `runScenario(params)` sets scenarioParams + scenarioId + calls refetch via setTimeout
8. Query calls `manager.analyzeWhatIfScenario(portfolioId, { scenario: apiScenario })`
9. Data passes through `whatIfAnalysisAdapter.transform()`
10. Error from manager surfaces to hook (`error?.message`)
11. Query disabled when no portfolio (returns null)
12. `runScenarioFromInputs` validates non-empty inputs before calling `runScenario`
13. `runScenarioFromInputs` with empty inputs does not call `runScenario` (calls `alert()`)

**Tests — Computed State:**
14. `hasData`, `hasError`, `hasPortfolio` computed correctly

**Mocks:** `useSessionServices` (manager), `useCurrentPortfolio`, `WhatIfAnalysisAdapter`, `AdapterRegistry`, `renderHookWithQuery`, `window.alert` (stub for validation).

**Special setup:** `vi.useFakeTimers()` needed for `setTimeout(refetch, 0)` in `runScenario`.

---

### D4. usePortfolioSummary (~10 tests)
**File:** `frontend/packages/connectors/src/features/portfolio/hooks/usePortfolioSummary.ts` (399 lines)
**Test:** `frontend/packages/connectors/src/features/portfolio/__tests__/usePortfolioSummary.test.tsx`

**Pattern:** `useQueries` — 3 parallel queries (riskScore, riskAnalysis, performance). Shared cache keys with individual hooks. `portfolioSummaryAdapter.transform()` merges all 3 results into a unified summary. **Risk score + risk analysis are hard-required; performance can fail and still produce summary data.**

**Tests:**
1. Initial state when no portfolio: `hasPortfolio=false`, `data=null`
2. Fires 3 parallel queries when portfolio present
3. Uses shared cache keys (`riskScoreKey`, `riskAnalysisKey`, `performanceKey`)
4. Individual adapters transform each query result before combining
5. `portfolioSummaryAdapter.transform()` merges all 3 transformed results into summary
6. `isLoading` true while any query pending
7. Performance query failure still produces partial summary (graceful degradation)
8. `hasData` true when required queries (riskScore + riskAnalysis) resolved
9. Legacy aliases: `loading` → `isLoading`, `refreshSummary` → `refetch`
10. `refetch` triggers all 3 queries

**Mocks:** `useSessionServices` (`manager` + `unifiedAdapterCache` — hook does NOT use `api`), `useCurrentPortfolio`, `PortfolioSummaryAdapter` (mock `transform(riskAnalysis, riskScore, portfolioHoldings, performance?)` — 4 args, riskAnalysis first), `RiskScoreAdapter`, `RiskAnalysisAdapter`, `PerformanceAdapter`, `AdapterRegistry`, `renderHookWithQuery`.

---

### D5. useRiskSettings (~12 tests)
**File:** `frontend/packages/connectors/src/features/riskSettings/hooks/useRiskSettings.ts` (490 lines)
**Test:** `frontend/packages/connectors/src/features/riskSettings/__tests__/useRiskSettings.test.tsx`

**Pattern:** useQuery + `updateSettings` mutation with bidirectional adapter transformation and coordinated cache invalidation. Uses `riskSettingsManager.getRiskSettings()` for reads, `riskSettingsManager.updateRiskSettings()` for writes. `RiskSettingsAdapter` handles forward (backend decimals → UI integers) and reverse (UI integers → backend decimals) transforms. Depends on `useRiskScore` for compliance data.

**Actual return shape:** `{ data, loading, isLoading, isRefetching, error, refetch, refreshRiskSettings, hasData, hasError, hasPortfolio, currentPortfolio, clearError, updateSettings }`

**Tests — Query:**
1. Initial state when no portfolio: `data=null`, `hasPortfolio=false`, query disabled
2. Calls `riskSettingsManager.getRiskSettings(portfolioId)` when portfolio present
3. Passes result through `riskSettingsAdapter.transform(rawData, riskScoreData)`
4. Error from manager throws → TanStack Query error state (`error?.message`)
5. `hasData`, `hasError`, `hasPortfolio` computed correctly

**Tests — updateSettings:**
6. `updateSettings` with backend format (`{ risk_limits: {...} }`) passes through unchanged
7. `updateSettings` with UI format (flat: `{ max_volatility: 40 }`) auto-transforms via `adapter.transformForBackend()`
8. `updateSettings` calls `riskSettingsManager.updateRiskSettings(portfolioId, data)`
9. On success, calls `cacheCoordinator.invalidateRiskData(portfolioId)` for coordinated invalidation
10. `updateSettings` throws when no portfolio loaded

**Tests — Configuration:**
11. Query `enabled` gated on `!!currentPortfolio && !!riskSettingsManager`
12. Legacy alias: `refreshRiskSettings` → `refetch`

**Mocks:** `useSessionServices` (riskSettingsManager, cache, cacheCoordinator), `useCurrentPortfolio`, `useRiskScore`, `RiskSettingsAdapter`, `AdapterRegistry`, `useQueryClient`, `renderHookWithQuery`.

---

## Phase E — Streaming Chat (1 hook, ~20 tests)

Dedicated phase for the most complex hook. Requires async-generator mock, AbortController, event processing, approval flow.

### E1. usePortfolioChat (~20 tests)
**File:** `frontend/packages/connectors/src/features/external/hooks/usePortfolioChat.ts` (970 lines)
**Test:** `frontend/packages/connectors/src/features/external/__tests__/usePortfolioChat.test.tsx`

**Pattern:** Streaming chat with Claude AI via `GatewayClaudeService.sendMessageStream()` (async generator). useQuery for portfolio context. Multi-state: messages array, chatStatus state machine (`ready` → `submitted` → `streaming` → `tool-executing` → `ready`/`error`), pending tool approval flow. Message management: edit, delete, retry, regenerate, reload. File processing (internal, underscore-prefixed).

**Actual return shape (UsePortfolioChatReturn):** `{ messages, sendMessage, status, chatStatus, stop, regenerate, reload, error, editMessage, deleteMessage, retryMessage, loading, isLoading, isSending, hasMessages, hasError, hasPortfolio, canSend, currentPortfolio, chatContext, clearMessages, clearError, pendingApproval, respondToApproval }`

**Tests — Initial State:**
1. Initial state: `messages=[]`, `status='ready'`, `error=null`, `hasMessages=false`
2. `canSend` true when portfolio present and not streaming
3. `canSend` false when no portfolio (`hasPortfolio=false`)
4. `chatContext` loaded via useQuery when portfolio present

**Tests — sendMessage:**
5. `sendMessage(text)` adds user message + empty assistant message to `messages`
6. `sendMessage` calls `gatewayService.sendMessageStream()` with text and message history
7. Text delta chunks accumulate into assistant message content
8. Status transitions: ready → submitted → streaming → ready on completion
9. `sendMessage` with no text and no files is a no-op
10. `sendMessage` requires `chatBackend === 'gateway'` (sets error otherwise)

**Tests — Streaming Control:**
11. `stop()` aborts current stream via AbortController, sets `status='ready'`
12. `stop()` is no-op when not streaming

**Tests — Error Handling:**
13. Streaming error sets `status='error'`, removes failed assistant message, adds error message
14. `categorizeError` classifies errors: network, auth, rate_limit, token_limit, server, unknown
15. `clearError` clears `streamError` and `chatStatus.error`

**Tests — Message Management:**
16. `editMessage(id, newContent)` updates message content in array
17. `deleteMessage(id)` removes message from array
18. `retryMessage(id)` truncates messages before the target user message, resends
19. `regenerate` finds last user message, truncates after it, resends
20. `reload` / `clearMessages` resets messages to `[]`, status to `ready`

**Tests — Tool Approval (stretch):**
- `tool_approval_request` chunk sets `pendingApproval` state
- `respondToApproval(approved)` calls `gatewayService.respondToApproval()` and clears pending

**Mocks:** `GatewayClaudeService` class (mock `sendMessageStream()` as async generator yielding chunks, mock `respondToApproval()`), `loadRuntimeConfig` (return `{ chatBackend: 'gateway' }`), `useSessionServices` (manager.getPortfolioContext), `useCurrentPortfolio`, `parseMessageContent`/`stripUIBlocks` from `@risk/chassis`, `frontendLogger`, `renderHookWithQuery`.

**Special harnessing:**
- Async generator mock: `async function* mockStream() { yield { type: 'text_delta', content: 'Hello' }; yield { type: 'done' }; }`
- `vi.useFakeTimers()` for setTimeout in retryMessage/regenerate (100ms delay)

---

## Implementation Notes

### File Location Convention
```
frontend/packages/connectors/src/features/<domain>/__tests__/<hookName>.test.tsx
```
Test files are `.tsx` (jsdom environment via vitest glob match).

### Standard Test Boilerplate
```typescript
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHookWithQuery } from '../../../../../../test/helpers/renderWithProviders';

vi.mock('../../../providers/SessionServicesProvider', () => ({
  useSessionServices: vi.fn(),
}));

const mockUseSessionServices = vi.mocked(useSessionServices);
const mockManager = { /* methods */ };

beforeEach(() => {
  vi.clearAllMocks();
  mockUseSessionServices.mockReturnValue({ manager: mockManager } as never);
});
```

### Key Patterns
- **`as never`** for partial mock objects (TS type suppression)
- **`renderHookWithQuery`** for any hook using useQuery/useMutation/useQueries
- **`renderHook`** (plain) for pure useState/useEffect hooks (useCancelableRequest, useCancellablePolling)
- **`vi.useFakeTimers()`** for setTimeout/setInterval hooks (useCancellablePolling, useConnectAccount, useWhatIfAnalysis, usePortfolioChat)
- **Deferred promises** for testing loading states
- **`waitFor(() => expect(...))`** for async query resolution
- **`act(() => { ... })`** for synchronous state mutations
- **Async generator mocks** for usePortfolioChat streaming
- **`window.open` stub** for popup hooks (useConnectAccount, useConnectSnapTrade, usePlaid reauth)
- **`window.alert` stub** for useWhatIfAnalysis input validation
- **Constructor mocks** for useAuthFlow (AuthManager, APIService via `vi.mock`)

### Dependency Order
Phase A has no inter-hook dependencies. Within later phases:
- B2 (useSnapTrade) mirrors B1 (usePlaid) — do B1 first, copy pattern
- C2 (useConnectAccount) depends on usePlaid mock from B1
- C3 (useConnectSnapTrade) depends on useSnapTrade mock from B2
- D5 (useRiskSettings) depends on useRiskScore (already tested in Wave 2)
- E1 (usePortfolioChat) is standalone but most complex — dedicated final phase

### Test Count Summary

| Phase | Hooks | Tests |
|-------|-------|-------|
| A | 4 | ~21 |
| B | 3 | ~55 |
| C | 3 | ~38 |
| D | 5 | ~56 |
| E | 1 | ~20 |
| **Total** | **16** | **~190** |

---

## Acceptance Criteria
- [ ] All 16 hooks have test files
- [ ] All tests pass (`cd frontend && pnpm test`)
- [ ] No new TS errors introduced
- [ ] Test count ≥ 170 (cumulative Wave 3)
- [ ] Wave 2 tests still pass (regression)

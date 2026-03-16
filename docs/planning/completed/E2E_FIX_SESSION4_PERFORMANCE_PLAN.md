# E2E Fix Session 4: Performance & Infrastructure

**Status**: NOT STARTED
**Session**: 4 of 4 (parallel fix sessions)
**Findings**: R3, R17, R18 from `docs/planning/REVIEW_FINDINGS.md`
**Date**: 2026-03-16

## Scope

This session handles backend performance, request deduplication, and authentication
stability. These are lower-visibility but high-impact infrastructure issues. All work
is isolated from Sessions 1-3 with no file conflicts.

**Session boundaries (DO NOT TOUCH):**
- Session 1: `index.css`, frontend UI components (visual fixes)
- Session 2: Backend portfolio analysis / risk computation logic
- Session 3: Recommendation logic, sector enrichment
- Session 4 (this): HTTP layer, auth layer, logging layer, query infrastructure

---

## Findings

### R3 (High) — All Accounts portfolio switch takes ~30s, frontend times out

**Symptom**: Switching to "All Accounts" (CURRENT_PORTFOLIO / COMBINED) triggers
`POST /api/risk-score` and `POST /api/analyze`, each taking ~30s for 51 positions
across IBKR + SnapTrade + Plaid. The frontend timeout fires before the backend
completes, showing "Data Loading Error — Request timed out while loading data."

**Root cause chain**:
1. `app.py:1244` (`/api/analyze`) and `app.py:1543` (`/api/risk-score`) both call
   `_run_analyze_workflow` / `_run_risk_score_workflow` via `run_in_threadpool`
2. These call `_load_portfolio_for_analysis()` in `mcp_tools/risk.py:400`, which
   calls `PositionService.get_all_positions()` in `services/position_service.py:297`
3. Position fetching loops over providers **sequentially** (line 324: `for provider_name
   in self._position_providers`) — each provider fetch (IBKR, SnapTrade, Plaid) may
   take 5-10s on cache miss
4. After position fetch, `ensure_factor_proxies()` generates missing proxies via GPT
   (potentially slow on first run for 51 tickers)
5. Frontend SDK descriptors use `timeout: 30000` (30s) as the default
   (`frontend/packages/chassis/src/catalog/descriptors.ts:13`) — too short for the
   combined-portfolio compute path

### R17 (Medium) — Dashboard fires 71 API requests on load

**Symptom**: Page load generates ~71 requests: ~30 `/api/log-frontend` POST calls,
~7 OPTIONS preflights, ~34 data API calls (~10 of which are duplicates.

**Root cause analysis**:
1. **Log batching regression**: The FrontendLogger (`frontend/packages/app-platform/
   src/logging/Logger.ts`) batches in groups of 10 with 200ms debounce (line 929:
   `splice(0, 10)`, line 881: `QUEUE_FLUSH_DEBOUNCE_MS = 200`). But the batch size
   of 10 is too small — startup generates 50+ log entries, producing 5+ POST calls.
   The 200ms debounce fires multiple times as new logs arrive after each flush.
2. **Duplicate data requests**: Multiple components independently fetch the same data
   with slightly different query keys. Observed duplicates:
   - `/api/positions/alerts`: 3x with `CURRENT_PORTFOLIO` + 1x with account-specific name
   - `/api/v2/portfolios`: 3x
   - `/api/positions/holdings`: 2x
   - `/api/income/projection`: 2x
   - `/api/allocations/target`: 2x
   - `/api/positions/metric-insights`: 2x
   - `/api/strategies/templates`: 2x
   All SDK queries use `['sdk', sourceId, ...params]` key structure, but if the
   portfolioId param varies (e.g., `CURRENT_PORTFOLIO` vs account slug), React Query
   treats them as distinct queries.
3. **5-second auto-refresh**: `SettingsPanel.tsx:34-35` defaults `autoRefresh: true`
   with `refreshInterval: 5000` (5 seconds). This is local component state and not
   persisted, but the component initializes with these defaults on every mount,
   potentially compounding request volume during the session.

### R18 (Medium) — Session drops when clicking Strategy/Settings sidebar

**Symptom**: Clicking Strategy or Settings sidebar buttons occasionally redirects to
the login page. Happens ~2 out of 3 times during testing.

**Root cause investigation**:
1. All views are rendered via the `activeView` switch in `ModernDashboardApp.tsx`
   (lines 420-508). Strategy (`'strategies'`) and Settings (`'settings'`) both render
   lazy-loaded components:
   - Settings: `AccountConnectionsContainer` (React.lazy, line 107) and
     `CsvImportCard` (React.lazy, line 111)
   - Strategies: `ScenariosRouter` (non-lazy)
2. The Settings view renders `AccountConnectionsContainer` which calls SnapTrade/Plaid
   APIs that require auth. If any of those APIs returns 401, the `HttpClient`
   (`frontend/packages/app-platform/src/http/HttpClient.ts:83-85`) calls
   `this.onUnauthorized()` which triggers `handleUnauthorizedSession()` in
   `authStore.ts:46-68`, which calls `authState.signOut()` — logging the user out.
3. The 401 may be a **legitimate session expiry** that coincides with navigation, or
   a **race condition** where the session cookie is not sent on a preflight or the
   session lookup fails transiently.
4. Backend session validation (`app.py:1038-1044`): `get_current_user()` reads
   `session_id` from cookies → `auth_service.get_user_by_session()`. If the session
   store lookup fails (DB timeout, connection pool exhaustion during the slow All
   Accounts fetch from R3), it returns `None` → 401 → frontend logout.
5. The `AuthServiceBase.get_user_by_session()` (`app_platform/auth/service.py:110-141`)
   catches exceptions and falls back to `fallback_session_store`, but returns `None`
   if both fail. A transient DB issue during the ~30s All Accounts compute could
   cause this.

---

## Steps

### Step 1: Increase frontend timeout for analysis endpoints

**Goal**: Stop the timeout error for All Accounts by giving the backend enough time.

**Files**:
- `frontend/packages/chassis/src/catalog/descriptors.ts`

**Changes**:
1. Increase `DEFAULT_ERRORS.timeout` from `30000` to `60000` (30s → 60s) — this
   gives the backend adequate headroom for combined portfolios
2. Verify that the `risk-score` descriptor inherits from `DEFAULT_ERRORS` (it uses
   `...DEFAULT_ERRORS` so the change propagates automatically)
3. Keep specialized descriptors (backtest, stress-test, monte-carlo) at their
   existing `120000` timeout — those are already generous

**Rationale**: The quick fix. Even with backend improvements, the combined portfolio
will always be slower than single-account. 60s is reasonable for a one-time portfolio
switch that happens rarely.

**Test**: Switch from IBKR to All Accounts. Should see loading state instead of
timeout error. Data should appear within 30s.

---

### Step 2: Fix frontend log batching regression (R17a)

**Goal**: Reduce `/api/log-frontend` calls from ~30 to <5 on page load.

**Files**:
- `frontend/packages/app-platform/src/logging/Logger.ts`

**Changes**:
1. Increase batch size from 10 to 50 (line 929: `splice(0, 10)` → `splice(0, 50)`).
   Startup generates ~50 log entries — a batch size of 50 sends them all in one POST.
2. Increase `QUEUE_FLUSH_DEBOUNCE_MS` from `200` to `1000` (line 41). The 200ms
   debounce fires repeatedly during component mount cascade. A 1s debounce collects
   more logs per batch without noticeable delay to the developer viewing logs.
3. Add an initial startup hold: do not flush the queue for the first 2 seconds after
   `init()`. This collects all mount-time logs into a single batch. Implementation:
   add a `private _initTimestamp: number = 0` field, set it in `init()`, and in
   `scheduleQueueFlush()` compute a delay of
   `Math.max(this.QUEUE_FLUSH_DEBOUNCE_MS, 2000 - (Date.now() - this._initTimestamp))`
   for the first flush.

**Expected result**: ~50 startup logs → 1 batch POST instead of 5+. Ongoing logs
still flush within 1s.

**Test**: Open browser DevTools Network tab, navigate to dashboard. Filter by
`log-frontend`. Count should be <5 on initial load (was ~30).

---

### Step 3: Deduplicate data requests on dashboard load (R17b)

**Goal**: Reduce duplicate data API calls from ~10 to 0.

**Files**:
- `frontend/packages/connectors/src/resolver/useDataSource.ts` (query key construction)
- Frontend hooks that fetch alerts, portfolios, holdings (identify callers)

**Investigation and changes**:
1. **Identify duplicate callers**: The alerts endpoint fires with both
   `CURRENT_PORTFOLIO` and the account-specific name. This happens because different
   components pass different portfolio identifiers. Find all callers of the alerts
   data source and ensure they use the **resolved** portfolio name from the store,
   not a local override.

2. **Normalize portfolio ID in query keys**: In the `useDataSource` hook, the query
   key includes the raw `portfolioId` param. If one component passes
   `CURRENT_PORTFOLIO` and another passes `_auto_interactive_brokers_u2471778`, React
   Query creates two separate cache entries. Add normalization:
   - If `portfolioId` is the active portfolio's internal ID, normalize it to the
     canonical `CURRENT_PORTFOLIO` key (or vice versa — pick one canonical form)
   - This ensures all components share the same query key and cache entry

3. **Deduplicate `portfolios` calls**: The `/api/v2/portfolios` is called 3x. This
   likely comes from multiple components reading from the portfolio store before it
   is initialized. Ensure the portfolios query is fetched once (eager, priority 0)
   and other components read from the cache.

4. **Deduplicate `strategies/templates`**: Called 2x. Find both callers and ensure
   they use the same query key / data source descriptor.

**Test**: Open DevTools Network tab, navigate to dashboard. Count duplicate data
requests. Target: 0 duplicates, total data requests <25.

---

### Step 4: Update auto-refresh default interval (R17c)

**Goal**: Prevent the 5-second auto-refresh from compounding request volume.

**Files**:
- `frontend/packages/ui/src/components/portfolio/overview/SettingsPanel.tsx`

**Changes**:
1. Change `refreshInterval` default from `5000` to `60000` (5s → 60s) on line 35
2. Change the reset-to-defaults handler to also use `60000` (line 593)
3. This is local component state — it does not persist across sessions, but the
   default should be reasonable. 5-second polling is excessive for a portfolio
   dashboard where positions change at most once per day.

**Note**: The auto-refresh toggle and interval controls in the Settings panel appear
to be **UI-only** — they set local state but may not actually drive any polling.
Investigate whether any hook or effect reads `refreshSettings` and passes it to
React Query's `refetchInterval`. If it is purely cosmetic, note that in the commit
but still fix the default to avoid confusion.

**Test**: Open Settings panel. Verify default shows "60 seconds" instead of
"5 seconds". If the auto-refresh actually polls, verify network requests are spaced
60s apart.

---

### Step 5: Investigate and fix session drops on navigation (R18)

**Goal**: Prevent spurious logouts when navigating to Strategy/Settings views.

**Files**:
- `frontend/packages/app-platform/src/http/HttpClient.ts` — 401 handling
- `frontend/packages/chassis/src/stores/authStore.ts` — `handleUnauthorizedSession()`
- `app.py` — `get_current_user()` dependency
- `app_platform/auth/service.py` — `get_user_by_session()`

**Investigation**:
1. **Add diagnostic logging**: In `handleUnauthorizedSession()` (authStore.ts:46),
   add a `frontendLogger.warning()` call that logs which endpoint returned 401 and
   the current auth state. This helps determine if the 401 is from a data endpoint
   or a navigation-triggered endpoint.

2. **Check for 401 retry before logout**: Currently `HttpClient.ts:83-85` immediately
   calls `onUnauthorized()` on any 401. This is too aggressive — a single transient
   401 should not log the user out. Add a **single retry with auth re-check** before
   calling `onUnauthorized()`:
   - On 401, first call `checkAuthStatus()` to see if the session is truly expired
   - If `checkAuthStatus()` returns authenticated, retry the original request
   - If `checkAuthStatus()` returns unauthenticated, then call `onUnauthorized()`
   - This handles transient 401s (DB timeout, connection pool exhaustion) without
     losing the session

3. **Guard against concurrent logouts**: `handleUnauthorizedSession()` uses
   `isHandlingUnauthorizedSession` flag, but multiple 401 responses arriving
   simultaneously could still race. Verify the flag is checked before calling
   `signOut()`.

4. **Backend resilience**: In `app.py:1038-1044`, `get_current_user()` raises 401
   if `get_user_by_session()` returns None. But `get_user_by_session()` in
   `app_platform/auth/service.py:110-141` returns None on **any exception** (line
   140-141). This means a transient DB error during the heavy All Accounts compute
   (R3) could return None → 401 → frontend logout. Consider:
   - Differentiating "session not found" (genuine 401) from "session lookup failed"
     (503 with retry)
   - Returning 503 on session store exceptions instead of 401
   - Adding a retry on the backend before returning 401

**Changes (concrete)**:
1. In `HttpClient.ts`, add a 401 retry with auth re-check (described above)
2. In `authStore.ts:handleUnauthorizedSession()`, add diagnostic logging
3. In `app.py:get_current_user()`, wrap the `auth_service.get_user_by_session()`
   call in a try/except that returns 503 on exceptions (not 401)

**Test**: Navigate repeatedly between Dashboard, Strategy, and Settings (10+ times).
Should never redirect to login page. Monitor backend logs for any session lookup
failures.

---

### Step 6: Verify provider fetching is concurrent (R3 backend)

**Goal**: Ensure position fetches from multiple providers run in parallel.

**Files**:
- `services/position_service.py:324-337` — provider fetch loop

**Investigation**:
1. The current code iterates providers sequentially:
   ```python
   for provider_name in self._position_providers:
       provider_results[provider_name] = self._get_positions_df(...)
   ```
   Each `_get_positions_df()` call is synchronous and blocks until the provider
   responds.

2. **Option A — ThreadPoolExecutor**: Wrap the loop in
   `concurrent.futures.ThreadPoolExecutor` to fetch all providers in parallel:
   ```python
   with ThreadPoolExecutor(max_workers=len(providers)) as executor:
       futures = {
           executor.submit(self._get_positions_df, provider, use_cache, force_refresh, False): provider
           for provider in providers
       }
       for future in as_completed(futures):
           provider = futures[future]
           provider_results[provider] = future.result()
   ```
   This should reduce the total position fetch time from `sum(provider_times)` to
   `max(provider_times)`.

3. **Risk**: Thread safety. `_get_positions_df()` uses per-provider caching that may
   not be thread-safe. Verify that the cache (likely an in-memory dict) is not
   mutated concurrently. If the cache uses a simple dict, add a lock or switch to
   `threading.Lock`-guarded access.

4. **Cache hit path**: If all providers return cached positions (24h TTL), the
   sequential loop is already fast (<1s total). The parallel optimization only helps
   on cache miss. Verify that the common case (cached) is not regressed.

**Changes**: Implement Option A with thread safety guards. Keep the sequential path
as a fallback if only one provider is configured.

**Test**: Clear position cache, then switch to All Accounts. Measure total position
fetch time. Should be ~max(provider_times) instead of ~sum(provider_times). With
3 providers at ~5s each, this reduces from ~15s to ~5s.

---

## File Ownership Matrix

| File | Session | Notes |
|------|---------|-------|
| `frontend/packages/chassis/src/catalog/descriptors.ts` | 4 | Timeout config |
| `frontend/packages/app-platform/src/logging/Logger.ts` | 4 | Log batching |
| `frontend/packages/app-platform/src/http/HttpClient.ts` | 4 | 401 retry logic |
| `frontend/packages/chassis/src/stores/authStore.ts` | 4 | Auth diagnostics |
| `frontend/packages/ui/src/components/portfolio/overview/SettingsPanel.tsx` | 4 | Refresh interval |
| `frontend/packages/connectors/src/resolver/useDataSource.ts` | 4 | Query key dedup |
| `services/position_service.py` | 4 | Parallel provider fetch |
| `app.py` (get_current_user only) | 4 | 503 on session failure |
| `app_platform/auth/service.py` | 4 | Session lookup resilience |
| `frontend/packages/ui/src/index.css` | 1 | DO NOT TOUCH |
| `core/portfolio_analysis.py` | 2 | DO NOT TOUCH |
| `mcp_tools/risk.py` | 2 | DO NOT TOUCH |

---

## Testing Plan

### R3 — Portfolio switch timeout
1. Navigate to IBKR single-account portfolio
2. Switch to "All Accounts" via dropdown
3. **Before fix**: Expect timeout error after ~15s
4. **After fix**: Expect loading state, data appears within 30s
5. Repeat 3x to verify consistency

### R17 — Request count
1. Open browser DevTools → Network tab
2. Clear network log, hard refresh dashboard
3. Count total requests after page settles (wait 10s)
4. **Before fix**: ~71 requests
5. **After fix**: Target <35 requests
6. Specifically verify:
   - `/api/log-frontend`: <5 calls (was ~30)
   - No duplicate data requests (alerts, portfolios, holdings)

### R18 — Session stability
1. Sign in via Google
2. Navigate: Dashboard → Strategy → Dashboard → Settings → Dashboard → Strategy → Settings
3. Repeat 10 times
4. **Before fix**: ~2/3 navigations trigger logout
5. **After fix**: 0 logouts across all 10 navigations
6. Check browser console for any 401 responses

### Regression checks
- All existing frontend tests pass (`npm test` in each package)
- Backend tests pass (`pytest` — should not be affected since changes are minimal)
- No new console errors on page load
- Position data loads correctly for IBKR single-account (fast path not regressed)

---

## Commit Plan

One commit per step if changes are small, or group Steps 2+4 (both frontend logging/
settings) into one commit. Suggested messages:

1. `fix: increase frontend timeout for analysis endpoints (R3)`
2. `fix: reduce log-frontend requests via larger batches and startup hold (R17)`
3. `fix: deduplicate dashboard data requests via query key normalization (R17)`
4. `fix: increase auto-refresh default interval from 5s to 60s (R17)`
5. `fix: add 401 retry with auth re-check to prevent spurious logouts (R18)`
6. `perf: parallelize multi-provider position fetching (R3)`

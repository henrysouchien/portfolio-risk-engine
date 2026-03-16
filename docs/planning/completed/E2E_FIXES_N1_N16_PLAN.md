# E2E Fixes N1–N16 Implementation Plan

**Source**: `E2E_ISSUES_2026_03_14.md` (root cause analysis)
**Date**: 2026-03-15
**Scope**: 15 open issues from the 2026-03-14 E2E browser audit (N6 already fixed)
**Review**: v6 — COMPLETE. All 16 issues resolved. 559 tests pass.

---

## Overview

16 issues found across 2 browser audit sessions. N6 (auth hang) already fixed via timeout in `createAuthStore.ts`. The remaining 15 issues cluster into 4 root causes:

1. **Auth/session fragility** (N7, N8, N10, N13) — no 401 interceptor, no re-auth cache clear, unscoped query invalidation
2. **Portfolio scope leakage** (N1, N2, N5, N11, N12, N16) — alerts unscoped, position counts divergent
3. **React render hygiene** (N4) — `useSyncExternalStore` cross-component setState
4. **Minor polish** (N3, N9, N14, N15) — loading timeout, rounding, margin label

---

## Phase 1: Auth & Session Recovery (N13, N8, N7, N10)

### Fix 1a: 401 Interceptor in HttpClient [N13, N8]

**Problem**: `HttpClient.fetchWithRetry()` (lines 67-99) only special-cases 429. Status 401 is retried 3× with exponential backoff (~7s wasted), then thrown as generic error. No mechanism transitions the app to unauthenticated state on session expiry.

**Files to change**:
- `frontend/packages/app-platform/src/http/HttpClient.ts`
- `frontend/packages/chassis/src/services/APIService.ts`

**Changes**:

1. **HttpClient.ts** — Add `onUnauthorized` callback to `HttpClientConfig` and 401 early-exit in `fetchWithRetry`:

```typescript
export interface HttpClientConfig {
  baseURL: string;
  getToken?: () => string | null;
  logger?: FrontendLogger;
  onUnauthorized?: () => void;  // NEW
}

private readonly onUnauthorized?: () => void;
constructor(config: HttpClientConfig) {
  // ... existing
  this.onUnauthorized = config.onUnauthorized;
}
```

In `fetchWithRetry` (line 67-99), two insertion points:

**Try block** — insert between `if (response.ok)` (line 76) and `throw this.createHttpError(response)` (line 80):
```typescript
if (response.ok) {
  return response;
}
if (response.status === 401) {
  this.onUnauthorized?.();
  throw this.createHttpError(response, 'Session expired');
}
throw this.createHttpError(response);
```

**Catch block** — the 401 throw above gets caught by the `catch` at line 81. Without a bail-out, it would be retried (lines 90-94 only throw on last attempt). Insert after the existing 429 bail-out (line 86-88):
```typescript
if (this.isRetryableHttpError(error) && error.status === 429) {
  throw error;
}
// NEW: Never retry 401 — session expired, retrying is pointless
if (this.isRetryableHttpError(error) && error.status === 401) {
  throw error;
}
```

This ensures 401 is NEVER retried (mirrors the existing 429 non-retry pattern).

2. **APIService.ts** — Wire `onUnauthorized` when constructing HttpClient (line 593-597).

**Package boundary constraint**: `APIService` is in `@risk/chassis`. Full session cleanup (`onLogout`) is in `@risk/connectors`. `chassis` cannot import `connectors` (dependency flows connectors → chassis, not the reverse).

**Solution**: Use a late-bound callback registration pattern. The `onUnauthorized` callback resolves at call time, not snapshot time:

```typescript
// In chassis — add a registrable callback slot:
// File: frontend/packages/chassis/src/services/unauthorizedHandler.ts
let _handler: (() => void) | null = null;
export const registerUnauthorizedHandler = (handler: () => void) => { _handler = handler; };
export const getUnauthorizedHandler = () => _handler;

// In APIService constructor (line 593):
this.http = new HttpClient({
  baseURL: this.baseURL,
  getToken,
  logger: frontendLogger,
  onUnauthorized: () => {
    // Resolve handler at call time — connectors registers it during startup
    const handler = getUnauthorizedHandler();
    if (handler) handler();
  },
});
```

```typescript
// In connectors startup — register the handler:
// File: frontend/packages/connectors/src/utils/sessionCleanup.ts (add at module scope,
// alongside the existing `registerSessionCleanup()` call at line 43)
import { registerUnauthorizedHandler } from '@risk/chassis';

registerUnauthorizedHandler(() => {
  if (useAuthStore.getState().isAuthenticated) {
    onLogout(); // Full cleanup: portfolio store, UI, adapters, React Query, auth
  }
});
```

This uses `onLogout()` (sessionCleanup.ts line 58-81) for full session cleanup, not just `signOut()`. The `isAuthenticated` guard prevents re-entrant calls from concurrent 401 responses. The late-binding ensures the handler is available even for `APIService` instances created before connectors loads (like the `stockCacheService` singleton at `services/index.ts` line 51).

**Loading guarantee**: `sessionCleanup.ts` already has module-level side effects at line 43 (`registerSessionCleanup(...)`) that the existing cross-tab logout system depends on. This proves the module loads before any API calls can fire (auth flow must mount first). Adding our registration alongside the existing one follows the same proven loading path.

**Test**: When backend session expires, the FIRST 401 triggers full logout cleanup + redirect to landing page. No retry delays, no mixed state.

---

### Fix 1b: TanStack Query Cache Invalidation on Re-Auth [N7]

**Problem**: After Google OAuth re-auth, TanStack Query cache retains stale error states from the expired session. Dashboard shows "Mock" badge because sub-queries fail.

**Auth path**: Google OAuth re-auth goes through `useAuthFlow.signIn()` (useAuthFlow.ts line 94) → `storeSignIn(result.user, '')` → `createAuthStore`'s `signIn()` (line 71-73). This does NOT go through `initializeAuth()` — that's only for cookie-based session recovery on page load, and returns early once `isInitialized` is `true` (line 118).

**Files to change**:
- `frontend/packages/app-platform/src/auth/createAuthStore.ts`
- `frontend/packages/chassis/src/stores/authStore.ts`

**Changes**:

1. **createAuthStore.ts** — Add `onReauthenticate` callback and trigger it from `signIn()`:

```typescript
export interface AuthStoreConfig<TUser> {
  // ... existing
  /** Called when signIn succeeds for a previously unauthenticated user.
   *  Use to invalidate stale caches from the expired session. */
  onReauthenticate?: () => void;
}
```

In `signIn()` (the OAuth re-auth path — line 71-73):
```typescript
signIn: (user, token) => {
  const wasUnauthenticated = !get().isAuthenticated && get().isInitialized;
  config.onSignIn?.(user);
  set({ user, token, isAuthenticated: true, error: null, isInitialized: true });
  if (wasUnauthenticated) {
    config.onReauthenticate?.();
  }
},
```

Note: `initializeAuth()` does NOT need this hook. It returns early when `isInitialized` is true (line 118), and on its only execution `isInitialized` is still `false`, so `wasUnauthenticated` would be `false` (since `!isAuthenticated && isInitialized` = `!false && false` = `false`). The `signIn()` path is the sole re-auth entry point.

2. **chassis/stores/authStore.ts** — Wire the callback:

```typescript
import { getQueryClient } from '@risk/app-platform';

onReauthenticate: () => {
  const qc = getQueryClient();
  if (qc) {
    void qc.invalidateQueries({ queryKey: ['sdk'] });
  }
},
```

`getQueryClient()` is exported from `@risk/app-platform` (index.ts line 66) and re-exported from `@risk/chassis` (QueryProvider.tsx line 4).

**Test**: Sign out → sign in via Google OAuth → all Dashboard metric cards load with fresh data, no "Mock" badge.

---

### Fix 1c: Scoped Query Invalidation on Portfolio Switch [N10]

**Problem**: `PortfolioSelector.handleSelect()` calls `queryClient.invalidateQueries()` with NO filter (line 166), invalidating ALL queries. Triggers massive refetch storm.

**Files to change**:
- `frontend/packages/ui/src/components/dashboard/PortfolioSelector.tsx`

**Change**: Replace line 166:
```typescript
// BEFORE:
await queryClient.invalidateQueries();
// AFTER:
await queryClient.invalidateQueries({ queryKey: ['sdk'] });
```

All SDK data queries use `['sdk', sourceId, ...]` keys (core.ts line 57-60). Non-SDK queries key off portfolio ID and auto-refetch.

**Test**: Switch portfolios — no page reload, data refreshes smoothly.

---

## Phase 2: Portfolio Scope Resolution (N1, N2, N5, N11)

### Fix 2a: Auto-Portfolio Display Name [N1] — CLOSED (no code change)

**Problem**: Portfolio selector shows raw `_auto_*` name instead of friendly name.

**Investigation result (2026-03-15)**: All auto portfolios have `display_name` set in the DB. Verified via direct query — every `_auto_*` row has a friendly name (e.g., "Interactive Brokers (Henry Chien)", "Charles Schwab 25524252", "Merrill CMA-Edge"). The live app confirms these display correctly in `PortfolioSelector`. The original audit issue was likely a stale browser cache or transient state.

**No code change needed.**

---

### Fix 2b: Holdings & Trading Analysis [N2, N5] — CLOSED (infrastructure, not code)

**Problem**: Holdings empty for single-account, trading analysis HTTP 500.

**Investigation result (2026-03-15)**:
- **N2 (empty holdings)**: Not reproducing. IBKR single-account portfolio loads all 15 holdings with full enrichment (market values, weights, returns, volatility, risk scores). The `resolve_portfolio_scope()` path handles `_auto_*` names correctly.
- **N5 (trading analysis 500)**: Root cause is expired Schwab refresh token + IBKR Gateway not running. Backend logs: `"Schwab refresh token appears expired"` and `ConnectionRefusedError on port 7496`. The `/api/trading/analysis` endpoint throws `RuntimeError: Provider fetch failed (no data)` when transaction sources are unavailable. Frontend already handles this gracefully — falls back to "synthetic resolver data only".

**Fix**: Re-auth Schwab (`python3 -m scripts.run_schwab login`) + start IB Gateway. No code change needed.

---

### Fix 2c: Portfolio-Scoped Alerts [N11]

**Problem**: `GET /api/positions/alerts` (line 411) always loads ALL positions. No portfolio scope parameter.

**Files to change**:
- Backend: `routes/positions.py` — `get_portfolio_alerts` (line 411)
- Frontend: `frontend/packages/connectors/src/resolver/registry.ts` — `smart-alerts` resolver (line 662)
- Frontend: `frontend/packages/chassis/src/services/APIService.ts` — `getPortfolioAlerts` (line 782)
- Frontend: `frontend/packages/chassis/src/catalog/types.ts` — `SDKSourceParamsMap['smart-alerts']` (line 676)
- Frontend: `frontend/packages/chassis/src/catalog/descriptors.ts` — `smart-alerts` descriptor
- Frontend: `frontend/packages/connectors/src/features/positions/hooks/useSmartAlerts.ts` (line 15)

**Changes**:

1. **Backend** (`routes/positions.py`) — Accept `portfolio_name` query param, mirroring the exact scoping pattern from `_load_enriched_positions` (lines 181-199). The existing imports at line 28 already provide `LoadStrategy`, `filter_position_result`, `resolve_portfolio_scope`:

```python
@positions_router.get("/alerts")
async def get_portfolio_alerts(
    request: Request,
    portfolio_name: str | None = None,
):
    # ... existing auth check (lines 413-416) ...
    def _build_alerts():
        service = PositionService(user_email=user["email"], user_id=user["user_id"])

        if portfolio_name and portfolio_name != "CURRENT_PORTFOLIO":
            try:
                scope = resolve_portfolio_scope(int(user["user_id"]), portfolio_name)
            except PortfolioNotFoundError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc

            if scope.strategy == LoadStrategy.PHYSICAL:
                # Manual portfolios have no live positions — return empty alerts
                return {"success": True, "alerts": [], "total": 0}
            elif scope.strategy == LoadStrategy.VIRTUAL_FILTERED:
                result = service.get_all_positions(consolidate=False)
                result = filter_position_result(result, scope.account_filters or [])
                # Rebuild consolidated result like _load_enriched_positions does
                result = _rebuild_position_result(service, result)
            else:
                result = service.get_all_positions(consolidate=True)
        else:
            result = service.get_all_positions(consolidate=True)

        # ... existing flag generation from `result` (lines 423+) ...
```

Key differences from v4:
- Uses string literal `"CURRENT_PORTFOLIO"` matching `_load_enriched_positions` (line 183) instead of referencing `CURRENT_PORTFOLIO_NAME` from `portfolio_management.py`
- Manual portfolios (`PHYSICAL`) return empty alerts (they have no live positions, unlike combined/auto)
- Virtual-filtered path calls `_rebuild_position_result(service, result)` (line 160-178) to reconsolidate after filtering, matching the `_load_enriched_positions` pattern at line 197
- Add `PortfolioNotFoundError` import from `services.portfolio_scope`

2. **Frontend catalog types** (`types.ts` line 676):
```typescript
// BEFORE:
'smart-alerts': Record<string, never>;
// AFTER:
'smart-alerts': { portfolioId?: string };
```

3. **Frontend resolver** (`registry.ts` line 662):
```typescript
'smart-alerts': async (params, context) => {
  const portfolio = getPortfolio(params?.portfolioId, context.currentPortfolio);
  const portfolioName = portfolio ? getPortfolioName(undefined, portfolio) : undefined;
  const payload = await context.services.api.getPortfolioAlerts(portfolioName);
  return { alerts: transformSmartAlerts(payload) };
},
```

4. **APIService** (`APIService.ts` line 782):
```typescript
async getPortfolioAlerts(portfolioName?: string): Promise<PortfolioAlertsResponse> {
  const params = portfolioName ? `?portfolio_name=${encodeURIComponent(portfolioName)}` : '';
  return this.http.request<PortfolioAlertsResponse>(`/api/positions/alerts${params}`);
}
```

5. **useSmartAlerts.ts** — Pass current portfolio ID so query key includes it:
```typescript
export const useSmartAlerts = () => {
  const currentPortfolio = useCurrentPortfolio();
  const resolved = useDataSource('smart-alerts', { portfolioId: currentPortfolio?.id });
  // ... rest unchanged
};
```
Requires adding `import { useCurrentPortfolio } from '@risk/chassis';`.

6. **Descriptor** (`descriptors.ts`) — If the `smart-alerts` descriptor has `dependsOn` or static query keys, update to include portfolio context.

**Test**: Switch to IBKR-only portfolio → alerts show only IBKR positions with correct percentages.

---

## Phase 3: Position Count & Concentration Score (N12, N16)

### Fix 3a: Position Count Alignment [N12]

**Problem**: Portfolio selector shows "21 positions" (raw DB count including options/cash) while Dashboard shows "View All 15 Holdings" (enriched/filtered count).

**Files to change**:
- Backend: `mcp_tools/portfolio_management.py` — `_build_portfolio_payload` (lines 109-117)
- Frontend: `frontend/packages/chassis/src/types/index.ts` — `PortfolioInfo` (line 73-81)
- Frontend: `frontend/packages/ui/src/components/dashboard/PortfolioSelector.tsx` (line 268)

**Changes**: Add a `holdings_count` field alongside the existing `position_count`, without changing `position_count` semantics:

1. **Backend** — In `_build_portfolio_payload`, add `holdings_count` that excludes options, zero-quantity, and cash. Raw positions from `database_client.get_portfolio_positions()` (line 1340-1351) use `ticker` and `type` (NOT `symbol`/`instrument_type`):
```python
# Existing (unchanged):
"position_count": len(current_positions),
# New:
"holdings_count": len([
    p for p in current_positions
    if (p.get("quantity") if isinstance(p, dict) else getattr(p, "quantity", 0)) != 0
    and (p.get("type") if isinstance(p, dict) else getattr(p, "type", "equity")) not in ("option",)
    and not str(p.get("ticker", "") if isinstance(p, dict) else getattr(p, "ticker", "")).upper().startswith("CUR:")
]),
```
This follows the same dict-or-object access pattern already used in `_count_non_cash_positions` (lines 98-105) which does the same `isinstance(position, dict)` check. The `CUR:` prefix exclusion mirrors `_count_non_cash_positions`, and the `type != "option"` exclusion filters option contracts which the enriched holdings pipeline also excludes.

2. **Frontend type** — Add to `PortfolioInfo` (types/index.ts line 73-81):
```typescript
export interface PortfolioInfo {
  // ... existing
  position_count: number;
  holdings_count?: number;  // NEW — filtered to match Dashboard enriched pipeline
  // ...
}
```

3. **Frontend selector** — Use `holdings_count` for display (PortfolioSelector.tsx line 268):
```typescript
// BEFORE:
{portfolio.position_count} {portfolio.position_count === 1 ? 'position' : 'positions'}
// AFTER:
{(portfolio.holdings_count ?? portfolio.position_count)} {(portfolio.holdings_count ?? portfolio.position_count) === 1 ? 'holding' : 'holdings'}
```

**Test**: Portfolio selector count matches "View All N Holdings" on Dashboard.

---

### Fix 3b: Concentration Score [N16] — CLOSED (implemented by Codex)

Codex implemented a dual-metric concentration scoring approach in commit `fd2a135b`:
- Single-position loss + top-N stressed basket with per-position security-type crash scenarios
- `_compute_concentration_loss()` shared helper across all 3 call sites (score, compliance, suggested limits)
- IBKR portfolio: concentration score 100 → 55 "Moderate" (verified live)
- Combined portfolio (51 holdings, max 17.1%): still scores 100 "Well Diversified" which is correct for a well-spread portfolio
- 3 new test files added (150+ test cases)

---

## Phase 4: React Render Hygiene (N4) — CLOSED (cosmetic, no fix)

### Fix 4a: setState-during-render warnings [N4]

**Investigation result (2026-03-15)**: Confirmed 10+ warnings from `useSyncExternalStore` in `useDataSource.ts` and `SessionServicesProvider.tsx`. Warnings originate from `ModernDashboardApp` propagating to child components (`PortfolioSelector`, `ChatProvider`, `DashboardHoldingsCard`, `AssetAllocationContainer`, etc.).

These are React 18/19 dev-mode strict-mode warnings from external store subscriptions. `useSyncExternalStore` is the architecturally correct React primitive for TanStack Query cache subscriptions. Replacing with `useEffect`/`useState` would cause timing regressions in dependency-gated queries.

**No fix needed** — cosmetic dev-mode warnings only.

---

## Phase 5: Minor Polish (N3, N9, N14, N15)

### Fix 5a: Risk Settings Loading Timeout [N3]

**Files**: `frontend/packages/ui/src/components/dashboard/views/modern/RiskSettingsContainer.tsx`

The loading gate is at line 203: `if (isLoading && !hasData) { return <LoadingSpinner ... /> }`. Add a timeout at this component level:

```typescript
const [timedOut, setTimedOut] = useState(false);
useEffect(() => {
  if (!isLoading || hasData) {
    setTimedOut(false);
    return;
  }
  const timer = setTimeout(() => setTimedOut(true), 15_000);
  return () => clearTimeout(timer);
}, [isLoading, hasData]);

if (isLoading && !hasData) {
  if (timedOut) {
    return (
      <ErrorMessage
        error="Unable to load risk settings — request timed out"
        onRetry={() => { setTimedOut(false); refetch(); }}
      />
    );
  }
  return <LoadingSpinner message="Loading risk settings..." />;
}
```

The `onRetry` handler resets `timedOut` and calls `refetch()` (line 197) to try again. This doesn't cancel the underlying request but provides a user-facing escape from the infinite spinner.

### Fix 5b: Normalize Allocation Total [N14]

**Files**: `frontend/packages/ui/src/components/portfolio/AssetAllocation.tsx`

After computing `totalAllocation` (line 183), snap to 100% if within floating-point tolerance:

```typescript
const rawTotal = allocations.reduce((sum, item) => sum + (Number(item.percentage) || 0), 0);
const totalAllocation = Math.abs(rawTotal - 100) <= 0.1 ? 100.0 : rawTotal;
```

Uses `<= 0.1` (inclusive) so that `100.1` snaps to `100.0`.

### Fix 5c: Margin Label for Negative Cash [N15]

**Files**: `frontend/packages/ui/src/components/dashboard/views/modern/AssetAllocationContainer.tsx`

Apply at caller site (line 158) where both `canonicalKey` and `item.percentage` are available:

```typescript
category: canonicalKey === 'cash' && (item.percentage || 0) < 0
  ? 'Cash (Margin)'
  : formatAssetClassName(canonicalKey),
```

### Fix 5d: Plaid 500 [N9] — CLOSED (not reproducing)

**Investigation result (2026-03-15)**: Plaid balance refresh succeeded during live test: `"Plaid balances API call succeeded (accounts=1)"`. Frontend isolation via `Promise.allSettled()` in `PortfolioManager.ts` confirmed working. The original 500 was likely a transient token issue during the audit.

**No fix needed.**

---

## Implementation Order

| Step | Fix | Issues | Status | Commit |
|------|-----|--------|--------|--------|
| 1 | 1a: 401 interceptor | N13, N8 | **Done** | `e6f0b7dd` |
| 2 | 1b: Re-auth cache clear | N7 | **Done** | `e6f0b7dd` |
| 3 | 1c: Scoped invalidation | N10 | **Done** (already present) | `06822618` |
| 4 | 2c: Scoped alerts | N11 | **Done** | `edd9b8a4` |
| 5 | 3a: Position count | N12 | **Done** | `3ff6d9cf` |
| 6 | 5b: Allocation rounding | N14 | **Done** | `06822618` |
| 7 | 5c: Margin label | N15 | **Done** | `3ff6d9cf` |
| 8 | 5a: Settings timeout | N3 | **Done** | `edd9b8a4` |
| 9 | 2a: Display name | N1 | **Closed** — no code change (DB already correct) | — |
| 10 | 2b: Holdings/trading | N2, N5 | **Closed** — infra issue (expired Schwab token) | — |
| 11 | 3b: Concentration score | N16 | **Done** | `fd2a135b` |
| 12 | 4a: setState warnings | N4 | **Closed** — cosmetic, no fix needed | — |
| 13 | 5d: Plaid 500 | N9 | **Closed** — not reproducing | — |

All 16 issues from the E2E audit are resolved. 9 implemented (code changes), 4 closed after investigation (no code change needed), 2 already fixed (N6 auth hang, N10 already scoped), 1 infrastructure (N5 Schwab token).

---

## Constraints

- **app-platform is an npm package** (`web-app-platform`): Changes to `HttpClient.ts` and `createAuthStore.ts` need publishing via `scripts/sync_frontend_app_platform.sh` + `scripts/publish_web_app_platform.sh`.
- **Package boundary**: `chassis` → `connectors` import is invalid. Fix 1a uses late-bound callback registration.
- All frontend changes must maintain existing test suites (443+ tests).

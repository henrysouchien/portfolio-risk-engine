# E2E Re-Audit Fix Plan (N1-N16)

**Status**: 9/9 DONE + N1, N16 fixed by other sessions. N7 investigating. N2-N3, N5 plan ready.
**Created**: 2026-03-15
**Source**: `FRONTEND_E2E_FINDINGS_2026_03_14.md` — Sessions 1+2 (16 issues)
**Reviewed**: 3 rounds Codex review → all 9 steps PASS.

### Execution Status
| Step | Issue | Status | Commit |
|------|-------|--------|--------|
| 1 | N16 — Concentration score | **DONE** (other session) | `fd2a135b` |
| 2 | N12 — Position count | **DONE** | `3ff6d9cf` |
| 3 | N14 — Allocation rounding | **DONE** | `06822618` |
| 4 | N15 — Cash margin label | **DONE** | `3ff6d9cf` |
| 5 | N10 — Selector invalidation | **DONE** | `06822618` |
| 6 | N11 — Alerts scoping | **DONE** | `edd9b8a4` |
| 7 | N7 — Auto-load after auth | **INVESTIGATING** (another session) | — |
| 8 | N13 — 401 interceptor | **DONE** | `e6f0b7dd` |
| 9 | N6 — Auth timeout | **DONE** | `edd9b8a4` |

---

## Issue Summary

| # | Severity | Root Cause | Category |
|---|----------|-----------|----------|
| N16 | Major | Concentration label — see Step 1 for correct semantics | Quick fix |
| N12 | Major | Position count includes cash in selector, excludes in Dashboard | Quick fix |
| N14 | Minor | Asset allocation rounding to 100.1% — backend per-bucket rounding | Backend fix |
| N15 | Minor | Cash -12.1% not labeled as margin | Quick fix |
| N10 | Major | `PortfolioSelector.handleSelect()` calls `invalidateQueries()` with no filter | Scoping fix |
| N11 | Major | `useSmartAlerts` passes no portfolio param — backend consolidates all accounts | Scoping fix |
| N7 | Blocker | Data doesn't auto-load after auth — root cause unclear, not a simple invalidation fix | Auth/session |
| N13 | Major | HttpClient has no 401 interceptor — no session expiry recovery UX | Auth/session |
| N6 | Blocker | 10s auth timeout too aggressive for dev-login two-call flow | Auth/session |
| N1 | Major | `findActivePortfolio()` lookup fails → raw name fallback | Selector fix |
| N2 | Major | Account filter mismatch in `portfolio_scope.py` — no account ID aliasing | Backend fix |
| N3 | Minor | Risk settings no `CURRENT_PORTFOLIO` fallback for `_auto_` portfolios | Backend fix |
| N5 | Minor | Trading analysis 500 — same account filter issue + no empty-result handling | Backend fix |
| N8 | Major | Rebalance 401 — missing session cookie (resolves with N13) | Resolves with N13 |
| N9 | Major | Plaid holdings 500 — expected when credentials expired | Not a bug |
| N4 | Minor | 7× setState-during-render warnings | Deferred |

---

## Batch 1: Quick Fixes (~45 min)

### Step 1: N16 — Fix Concentration label

**File**: `frontend/packages/ui/src/components/portfolio/overview/useOverviewMetrics.ts` ~line 96

**Codex correction**: Backend `score_excess_ratio()` makes `100 = safe/diversified` and `0 = critical/concentrated` (see `portfolio_risk_score.py:236`). The current thresholds (`>=70` = "Well Diversified") are **actually correct** for the score semantics.

**Real problem**: The issue seen in the E2E audit (score=100 with "Well Diversified" on a concentrated portfolio) means the **score itself is wrong**, not the label. A portfolio with AAPL 25.7% + MSFT 30.0% should NOT score 100 (safe).

**Investigation needed**: Check why `concentration_risk` returns 100 for a clearly concentrated portfolio. Likely a backend computation bug in `portfolio_risk_score.py:1521` or the input data (wrong weights being passed).

**Action**: Investigate backend score computation before changing frontend thresholds. Do NOT flip the labels — they match the backend's intended semantics.

**Effort**: Medium (investigation first)

### Step 2: N12 — Align position counts

**File**: `mcp_tools/portfolio_management.py` ~line 113

**Codex correction**: `current_positions` is a **list**, not a dict. Fix the filter syntax.

**Fix**:
```python
# BEFORE:
position_count = len(current_positions)

# AFTER — filter cash positions from count:
position_count = len([p for p in current_positions if not str(p.get('ticker', '') if isinstance(p, dict) else getattr(p, 'ticker', '')).startswith('CUR:')])
```

Apply after account filtering for non-manual portfolios.

**Effort**: Quick (15 min)

### Step 3: N14 — Fix allocation rounding

**Codex correction**: The 100.1% comes from **backend** per-bucket rounding in `core/result_objects/risk.py:903`, not frontend. Frontend just sums the pre-rounded values.

**File**: `core/result_objects/risk.py` → `_build_asset_allocation_breakdown()` ~line 903

**Fix**: Use a remainder allocation scheme (largest-remainder method) instead of independent rounding:
1. Compute exact percentages for all buckets
2. Floor each to 1 decimal
3. Distribute remaining 0.1% to the bucket with the largest remainder
4. Note: unclassified assets are skipped at line 869 — don't force-normalize when assets are missing

**Effort**: Quick (20 min)

### Step 4: N15 — Label negative cash as margin

**Codex correction**: The "Cash -12.1%" is rendered in `frontend/packages/ui/src/components/portfolio/AssetAllocation.tsx` at lines 300-302 (the shared render path), NOT in `AssetAllocationContainer.tsx`.

**File**: `frontend/packages/ui/src/components/portfolio/AssetAllocation.tsx` ~line 300

**Fix**: When the cash category has a negative percentage, append "(Margin)" to the label:
```typescript
const displayName = category.name === 'Cash' && category.percentage < 0
  ? 'Cash (Margin)'
  : category.name;
```

**Effort**: Quick (10 min)

---

## Batch 2: Scoping Fixes (~1-2 hrs)

### Step 5: N10 — Narrow portfolio selector query invalidation `PASS`

**File**: `frontend/packages/ui/src/components/dashboard/PortfolioSelector.tsx` ~line 166

**Fix**: Scope to SDK data source queries:
```typescript
// BEFORE:
await queryClient.invalidateQueries();

// AFTER:
await queryClient.invalidateQueries({ queryKey: ['sdk'] });
```

SDK queries are keyed under `['sdk']` per `resolver/core.ts:57`. This invalidates all portfolio-aware data without touching market data, stock analysis, or other independent caches.

**Effort**: Quick (10 min)

### Step 6: N11 — Scope smart alerts to current portfolio `PASS with correction`

**Files** (full chain — 6 files):
- `frontend/packages/connectors/src/features/positions/hooks/useSmartAlerts.ts:16` — add `portfolioId` param to `useDataSource` call
- `frontend/packages/chassis/src/catalog/types.ts:676` — change `smart-alerts` params type from `Record<string, never>` to include `portfolioId`
- `frontend/packages/chassis/src/catalog/descriptors.ts:1006` — add `portfolioId` to `params` array
- `frontend/packages/chassis/src/services/APIService.ts:782` — add `portfolio_name` query param to `getPortfolioAlerts()`
- `frontend/packages/connectors/src/resolver/registry.ts:662` — convert `portfolioId` to `portfolio_name` and pass to API
- `routes/positions.py:410` — accept `portfolio_name` query param, filter positions by scope

**Fix**: Thread `currentPortfolio.id` through hook → type system → descriptor → resolver (convert to `portfolio_name`) → API service → backend endpoint. Backend filters `get_all_positions()` to the scoped portfolio.

**Effort**: Medium (1 hr — 6 files across frontend + backend)

---

## Batch 3: Auth/Session Architecture (~3-4 hrs)

### Step 7: N7 — Auto-load data after portfolio bootstrap

**Investigation complete** (2026-03-15). Root cause identified:

The lifecycle stalls because data source queries have `enabled: !!currentPortfolio`, and `currentPortfolio` doesn't become truthy until bootstrap completes. The scheduler also gates on `currentPortfolio`. If the bootstrap → setCurrent → re-render → scheduler enablement chain doesn't complete synchronously, data never loads.

The **Refresh button works** because it calls `.refetch()` directly, bypassing the `enabled` flag.

**Codex correction**: Calling `invalidateQueries` inside a `queryFn` is wrong — it only runs after bootstrap succeeds, can't fix the case where bootstrap never fires. Also only covers one of two `setCurrent()` sites (line 225, not line 180).

**Fix**: Add a `useEffect` in `PortfolioInitializer.tsx` that watches `currentPortfolio` and invalidates SDK queries when it becomes truthy. This covers both `setCurrent()` sites and runs in the React lifecycle (not inside a queryFn).

**File**: `frontend/packages/connectors/src/providers/PortfolioInitializer.tsx`

**Changes**:
1. Add `useQueryClient` to the `@tanstack/react-query` import (line 3)
2. Get `queryClient` via `useQueryClient()` at the top of the component body
3. Add a `useEffect` after the existing hooks (before the scheduler call at line ~245):
```typescript
// Ensure data sources fire after portfolio is set.
// The scheduler should handle this via currentPortfolio reactivity,
// but if the render cycle races, this effect guarantees data loads.
// Note: currentPortfolio here comes from useCurrentId() which returns string | null
useEffect(() => {
  if (currentPortfolio) {
    queryClient.invalidateQueries({ queryKey: ['sdk'] });
  }
}, [currentPortfolio, queryClient]);
```

**Why this is safe**: `invalidateQueries` is idempotent. `currentPortfolio` is a `string | null` from `useCurrentId()` (line ~136), not an object — so the dependency is just `currentPortfolio`, not `currentPortfolio?.id`. Covers both `setCurrent()` sites (lines 180 and 225). Also fires on portfolio switch (correct — switching portfolios should refresh data).

**Effort**: Quick (10 min)

### Step 8: N13 — Add 401 interceptor for session expiry

**Codex correction**: `window.dispatchEvent` violates package boundaries. Use `onUnauthorized` callback in `HttpClientConfig`. Note: HttpClient currently **retries 401s** — this must be addressed too.

**Files** (full chain):

Layer 1 — HttpClient (app-platform):
- `frontend/packages/app-platform/src/http/HttpClient.ts:8` — add `onUnauthorized?: () => void` to config interface
- `frontend/packages/app-platform/src/http/HttpClient.ts:70` — in `fetchWithRetry()`, check for 401: if `onUnauthorized` is set, call it and throw (don't retry). Existing retry logic at lines 89-107 only fires when callback is NOT set.

Layer 2 — APIService (chassis) — already wired:
- `frontend/packages/chassis/src/services/APIService.ts:570` — `APIServiceConfig` already has `onUnauthorized` field
- `frontend/packages/chassis/src/services/APIService.ts:604` — already forwards to HttpClient

Layer 3 — APIService instantiation sites (4 total):
- `frontend/packages/chassis/src/stores/authStore.ts:43` — Wire `onUnauthorized` to `handleUnauthorizedSession()` at authStore.ts:46 (uses existing `isHandlingUnauthorizedSession` guard for dedup). Cleanup registration hook at authStore.ts:148 (`registerSessionCleanup`)
- `frontend/packages/chassis/src/services/index.ts:51` — `new StockCacheService(new APIService())`. Wire callback or explicitly exempt (stock cache doesn't need auth recovery)
- `frontend/packages/connectors/src/providers/SessionServicesProvider.tsx:217` — Wire to `sessionCleanup()` from `connectors/utils/sessionCleanup.ts:58`. **Add a once-per-expiry guard** to prevent concurrent 401s triggering repeated cleanup
- `frontend/packages/connectors/src/features/auth/hooks/useAuthFlow.ts:73` — Wire to same cleanup with same dedup guard

**Fix pattern**:
```typescript
// HttpClient config:
interface HttpClientConfig {
  baseUrl: string;
  onUnauthorized?: () => void;  // NEW
}

// In response handling (HttpClient.ts):
if (response.status === 401) {
  if (this.config.onUnauthorized) {
    this.config.onUnauthorized();
    throw this.createHttpError(response);  // Don't retry
  }
  // Existing retry logic for non-configured clients
}
```

Each APIService instantiation site passes `onUnauthorized: () => sessionCleanup()` or equivalent.

**Effort**: Medium (1-2 hrs — 6 files)

### Step 9: N6 — Dev-login auth timeout

**Codex correction**: The generic timeout is in `createAuthStore.ts:116` (app-platform), but the two-call dev flow is in `authStore.ts:48` (chassis). Raising the global timeout is a workaround. Better: split the timeout around the two calls in the chassis auth store.

**Files**:
- `frontend/packages/chassis/src/stores/authStore.ts:48` — the `checkAuthStatus` callback that does status + dev-login
- `frontend/packages/app-platform/src/auth/createAuthStore.ts:123` — the generic timeout wrapper

**Fix**: Move the timeout handling into the chassis `checkAuthStatus` callback so each call gets its own timeout:
```typescript
checkAuthStatus: async () => {
  // Individual timeout per call, not one timeout for the whole chain
  const response = await Promise.race([
    authAPIService.checkAuthStatus(),
    rejectAfter(10_000, 'Auth status check timed out'),
  ]);

  if (!response.authenticated && response.dev_mode) {
    // Dev-login gets its own generous timeout (cold backend)
    const devResult = await Promise.race([
      authAPIService.devLogin(),
      rejectAfter(20_000, 'Dev login timed out'),
    ]);
    if (devResult.user) {
      return { authenticated: true, user: devResult.user };
    }
  }

  return { authenticated: response.authenticated, user: response.user ?? null };
},
```

Remove or increase the generic timeout in `createAuthStore.ts` since the chassis now handles its own timeouts.

**Effort**: Quick (20 min)

---

## Execution Order

| Batch | Steps | Issues | Effort | Dependencies |
|-------|-------|--------|--------|--------------|
| 1 | 2, 4 | N12, N15 | ~25 min | None |
| 1b | 1, 3 | N16, N14 | ~40 min | Investigation (N16), backend (N14) |
| 2 | 5, 6 | N10, N11 | ~1-1.5 hrs | None |
| 3 | 7, 8, 9 | N7, N13, N6 | ~3-4 hrs | Investigation (N7) |

**Not addressed** (resolve naturally or deferred):
- N8: Resolves when N13 (401 interceptor) is fixed
- N9: Not a bug — expected Plaid failure
- N4: setState warnings — deferred until stack traces available
- N1-N3, N5: From original selector scope plan — separate execution

**Total effort**: ~5-7 hrs across 3-4 batches

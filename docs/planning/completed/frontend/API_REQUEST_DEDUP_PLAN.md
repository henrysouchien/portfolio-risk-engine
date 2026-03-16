# R17: API Request Deduplication Plan

**Status**: READY TO EXECUTE (v3 — revised after Codex review)
**Date**: 2026-03-16
**Goal**: Dashboard page load from 31 requests → ≤20 data requests
**Current duplication**: ~14 excess requests across 6+ endpoints

---

## Root Cause Analysis

Five independent root causes produce all the duplicate requests:

### Cause 1: Portfolio-Summary Cascade (3 duplicated endpoints)

The `portfolio-summary` resolver (`registry.ts:355-358`) calls sub-resolvers directly:
```typescript
const [riskScoreData, riskAnalysisData, performanceData] = await Promise.all([
  resolverMap['risk-score']({ portfolioId: portfolio.id }, context),
  resolverMap['risk-analysis']({ portfolioId: portfolio.id }, context),
  resolverMap.performance({ portfolioId: portfolio.id }, context),
]);
```

These calls **bypass React Query** — they call resolver functions directly, not through `useDataSource`. Meanwhile, sibling components mount individual hooks that make the **same API calls** through React Query:

| Cascade sub-resolver | Also called by | Backend endpoint |
|---------------------|----------------|-----------------|
| `risk-score` | `DashboardAlertsPanel` → `useRiskScore()` | `/api/risk-score` |
| `risk-analysis` | `AssetAllocationContainer` → `useRiskAnalysis()` | `/api/analyze` |
| `performance` | `DashboardPerformanceStrip` → `usePerformance()` + `PortfolioOverviewContainer` → `usePerformance()` | `/api/performance` |

**Result**: 2× React Query fetch cycles for each of risk-score, risk-analysis, performance. Backend `PortfolioCacheService.getOrFetch()` coalesces in-flight requests, so actual network duplication depends on timing.

### Cause 2: Scheduler Query-Key Mismatch (doubles the cascade)

`useDataSourceScheduler` (`scheduler.ts`) prefetches all eager-strategy sources, including `portfolio-summary`. But `PREFETCH_PORTFOLIO_SCOPED_SOURCES` (line 14) does NOT include `portfolio-summary`, so the scheduler calls `buildPrefetchParams()` which returns `undefined` params. Meanwhile, `usePortfolioSummary()` always passes `{ portfolioId: currentPortfolio.id }`.

This produces **different React Query keys**:
- Scheduler: `['sdk', 'portfolio-summary', '{}']`
- Hook: `['sdk', 'portfolio-summary', '{"portfolioId":"xxx"}']`

Result: **two separate portfolio-summary React Query executions**, each triggering the full cascade (risk-score + risk-analysis + performance). Backend `PortfolioCacheService` may coalesce in-flight requests, but the extra query-layer overhead (state transitions, re-renders) and potential network calls remain.

### Cause 3: PortfolioInitializer Broad SDK Invalidation

`PortfolioInitializer.tsx:261-264`:
```typescript
useEffect(() => {
  if (currentPortfolio) {
    void queryClient.invalidateQueries({ queryKey: ['sdk'] });
  }
}, [currentPortfolio, queryClient]);
```

When `currentPortfolio` becomes truthy (after bootstrap), this invalidates **every active SDK query**, causing a refetch burst. This is the primary cause of the 2× pattern for single-owner sources: `market-intelligence`, `metric-insights`, `allocation`, `positions-enriched`.

The scheduler fires after PortfolioInitializer (line 267: `useDataSourceScheduler(isAuthenticated && !!api && !!currentPortfolio && ...)`), which means SDK queries may get fetched, then immediately invalidated, then fetched again.

### Cause 4: Triple Smart-Alerts Ownership

`useSmartAlerts()` is mounted by **three** components simultaneously:
1. `PortfolioOverviewContainer` (line 79)
2. `DashboardAlertsPanel` (line 71)
3. `useNotifications()` (line 39) — mounted by `ModernDashboardApp` (line 239)

React Query deduplicates the initial fetch (same query key), but three hook instances register separate event-driven invalidation listeners. Combined with Cause 3's broad invalidation, this contributes to extra refetch cycles.

### Cause 5: Aggressive usePortfolioList Settings

`usePortfolioList` (`usePortfolioList.ts:42-43`) has:
```typescript
staleTime: 0,
refetchOnMount: 'always',
```

Three components mount this hook on dashboard load:
- `PortfolioInitializer` (provider tree, mounts first)
- `PortfolioSelector` (header)
- `DashboardIncomeCard` (unnecessarily — `portfolio_type` is already on `currentPortfolio`)

With `refetchOnMount: 'always'`, every mount triggers a new fetch even when cached data exists.

### Invalidation Layer Clarification

CacheCoordinator invalidates **legacy keys** (`riskScoreKey()`, `portfolioSummaryKey()` etc.), NOT SDK `['sdk', ...]` keys. The `useDataSource` event bridge (lines 159-179) that listens to EventBus events is the ONLY invalidation path for SDK queries. Container-level manual event handlers (`PortfolioOverviewContainer` lines 125-176, `AssetAllocationContainer` lines 223-241) that call `refetch()` are a **third** invalidation path that overlaps with the useDataSource bridge. The manual handlers are redundant with the useDataSource bridge (both react to the same events), but NOT redundant with CacheCoordinator's direct invalidation (which targets different keys).

---

## Fix Plan

### Phase 1: usePortfolioList staleTime + Remove Unnecessary Mount (Quick Wins)

**Impact**: Eliminates 2× `/api/v2/portfolios`
**Risk**: Low
**Files**: 2 (+ 3 for required freshness follow-up: `useConnectAccount.ts`, `useConnectSnapTrade.ts`, `CsvImportCard.tsx`)

**Step 1a**: Change `usePortfolioList.ts`:
```typescript
// Before:
staleTime: 0,
refetchOnMount: 'always',

// After:
staleTime: 30_000,  // 30 seconds — portfolio list doesn't change within a page load
// remove refetchOnMount: 'always' (default 'true' only refetches if stale)
```

**Required follow-up**: No code currently invalidates `['portfolios', 'v2', 'list']` after account connection/import success. Add `queryClient.invalidateQueries({ queryKey: ['portfolios'] })` to success handlers in `useConnectAccount.ts`, `useConnectSnapTrade.ts`, and `CsvImportCard.tsx` to ensure newly added portfolios appear promptly.

**Step 1b**: Remove `usePortfolioList()` from `DashboardIncomeCard.tsx` (line 162). It only reads `supported_modes` and `portfolio_type`, which are already available on `currentPortfolio`. Preserve current behavior: today the component treats a missing portfolio-list match as "income supported" (`!activePortfolio || ...`), so the fallback when `supported_modes` is undefined on `currentPortfolio` should also treat income as supported (do NOT default to `['hypothetical']` — that would hide the income card for portfolios added via onboarding, instant analysis, or refresh paths).

### Phase 2: Fix Scheduler Query-Key Mismatch + Cache Seeding (Core Fix)

**Impact**: Step 2a (scheduler fix) eliminates a second React Query execution of the portfolio-summary composite resolver plus up to 3 backend calls it fans out to (PortfolioCacheService coalesces in-flight duplicates, so backend savings depend on timing — worst case 3 extra, best case 0). Steps 2b-2e (cache seeding) prevent React Query from triggering redundant fetch cycles for risk-score, risk-analysis, and performance — the backend already deduplicates via `PortfolioCacheService.getOrFetch()`, so the savings are at the React Query layer (avoided query state transitions, re-renders, and stale→fetching→fresh cycles).
**Risk**: Medium — touches resolver plumbing
**Files**: 4 (`scheduler.ts`, `registry.ts`, `core.ts`, `useDataSource.ts`)

**Step 2a**: Add `portfolio-summary` to `PREFETCH_PORTFOLIO_SCOPED_SOURCES` in `scheduler.ts`:
```typescript
const PREFETCH_PORTFOLIO_SCOPED_SOURCES = new Set<DataSourceId>([
  'positions',
  'risk-score',
  'risk-analysis',
  'risk-profile',
  'performance',
  'portfolio-summary',  // NEW — ensures scheduler uses same query key as usePortfolioSummary
]);
```

This ensures the scheduler prefetch uses `{ portfolioId: portfolio.id }` params, producing the SAME query key as `usePortfolioSummary()`. React Query will deduplicate them, eliminating the second cascade entirely.

**Step 2b**: Extend `ResolverContext` to include `queryClient` (use `QueryClient` type, not `ReturnType<typeof useQueryClient>`):
```typescript
// registry.ts
import type { QueryClient } from '@tanstack/react-query';

interface ResolverContext {
  services: Services;
  currentPortfolio: Portfolio | null;
  signal: AbortSignal;
  queryClient?: QueryClient;  // NEW
}
```

**Step 2c**: In the `portfolio-summary` resolver, after calling sub-resolvers, seed caches:
```typescript
// registry.ts, portfolio-summary resolver
const [riskScoreData, riskAnalysisData, performanceData] = await Promise.all([...]);

// Seed sub-query caches to prevent duplicate fetches by individual hooks
if (context.queryClient) {
  const seedParams = { portfolioId: portfolio.id };
  context.queryClient.setQueryData(
    buildDataSourceQueryKey('risk-score', seedParams), riskScoreData
  );
  context.queryClient.setQueryData(
    buildDataSourceQueryKey('risk-analysis', seedParams), riskAnalysisData
  );
  context.queryClient.setQueryData(
    buildDataSourceQueryKey('performance', seedParams), performanceData
  );
}
```

**Step 2d**: Thread `queryClient` from `useDataSource` → `resolveWithCatalog` → `resolveDataSource`:
```typescript
// useDataSource.ts — add queryClient to queryFn call
queryFn: ({ signal }) => resolveWithCatalog(
  sourceId, normalizedParams, services, currentPortfolio, signal, queryClient
),

// core.ts — add queryClient parameter and pass through
export const resolveWithCatalog = async <Id extends DataSourceId>(
  sourceId: Id,
  params: ...,
  services: Services,
  currentPortfolio: Portfolio | null,
  signal: AbortSignal,
  queryClient?: QueryClient,
): Promise<...> => {
  const dataPromise = resolveDataSource(sourceId, params, {
    services, currentPortfolio, signal, queryClient,
  });
  // ...
};
```

**Step 2e**: Thread `queryClient` through the scheduler's `resolveWithCatalog` call in `scheduler.ts`:
```typescript
// scheduler.ts line 118 — add queryClient parameter
queryFn: ({ signal }) => resolveWithCatalog(sourceId, params, services, currentPortfolio, signal, queryClient),
```

**Why cache seeding instead of removing individual hooks**: Individual hooks (useRiskScore, usePerformance, useRiskAnalysis) are also used on other views (Research, Performance, etc.) where portfolio-summary is NOT loaded. Removing them would break those views. Cache seeding is transparent — if the cache has fresh data, the hook uses it; if not, it fetches.

### Phase 3: Scope PortfolioInitializer Invalidation

**Impact**: Eliminates the 2× burst for all single-owner SDK sources (market-intelligence, metric-insights, allocation, positions-enriched)
**Risk**: Medium — must ensure portfolio-dependent queries still refresh on portfolio change
**Files**: 1

**Current behavior** (`PortfolioInitializer.tsx:261-264`): Invalidates ALL `['sdk']` queries when `currentPortfolio` becomes truthy. This causes every mounted SDK hook to refetch, producing the 2× pattern for every single-owner source.

**Fix approach**: Replace the broad invalidation with scoped invalidation of only portfolio-dependent sources. The scheduler (line 267) already handles prefetching eager sources after portfolio load — the broad invalidation is redundant with it.

```typescript
// Before:
useEffect(() => {
  if (currentPortfolio) {
    void queryClient.invalidateQueries({ queryKey: ['sdk'] });
  }
}, [currentPortfolio, queryClient]);

// After:
// Remove this effect entirely. The scheduler (useDataSourceScheduler) already
// prefetches eager sources with correct portfolio-scoped params when
// currentPortfolio becomes available. Lazy sources will fetch on mount
// with the correct portfolio from useCurrentPortfolio().
```

**Alternative** (if removing entirely is too aggressive): Scope to only the sources that genuinely need re-fetching on portfolio change:
```typescript
useEffect(() => {
  if (currentPortfolio) {
    // Only invalidate sources that cache portfolio-specific data from a previous portfolio
    const portfolioScopedKeys: DataSourceId[] = [
      'positions', 'positions-enriched', 'risk-score', 'risk-analysis',
      'performance', 'portfolio-summary',
    ];
    for (const sourceId of portfolioScopedKeys) {
      void queryClient.invalidateQueries({ queryKey: ['sdk', sourceId] });
    }
  }
}, [currentPortfolio, queryClient]);
```

This preserves cache for non-portfolio-scoped sources (market-intelligence, metric-insights, etc.) while still refreshing portfolio-dependent data.

### Phase 4: Remove Redundant Manual Event Handlers

**Impact**: Cleanup — removes overlapping invalidation paths that cause extra refetches on cache invalidation events (not page-load, but during use)
**Risk**: Low — useDataSource event bridge already handles these same events for SDK queries
**Files**: 6 (PortfolioOverviewContainer, AssetAllocationContainer + 4 additional containers in Step 4c)

**Step 4a**: `PortfolioOverviewContainer.tsx` — Remove the `useEffect` block (lines 125-176) that subscribes to `portfolio-data-invalidated`, `risk-data-invalidated`, and `cache-updated` events. The `useDataSource` hook inside `usePortfolioSummary` already reacts to `portfolio-data-invalidated` and `risk-data-invalidated` via the `portfolio-summary` descriptor's `invalidatedBy`. The `cache-updated` handler (lines 156-165) is dead logging code — it only logs and never calls `refetch()`, and `portfolio-summary` does not subscribe to `cache-updated` via its descriptor.

**Step 4b**: `AssetAllocationContainer.tsx` — Remove the `useEffect` block (lines 223-241) that subscribes to `risk-data-invalidated`. The `useDataSource` hook inside `useRiskAnalysis` already handles this.

**Step 4c**: Audit and remove the same redundant manual event handler pattern in other resolver-backed containers:
- `RiskAnalysisModernContainer.tsx` (line ~325)
- `RiskMetricsContainer.tsx` (line ~81)
- `PerformanceViewContainer.tsx` (line ~266)
- `FactorRiskModelContainer.tsx` (line ~133)

All of these subscribe to EventBus events that the `useDataSource` hook already handles via descriptor `invalidatedBy`. The manual handlers are redundant.

**Note**: Manual refresh (refresh button) is unaffected — it goes through `handleRefresh()` → `IntentRegistry.triggerIntent('refresh-holdings')` → `refetch()`, not through event handlers.

### Phase 5: Consolidate Smart-Alerts Ownership

**Impact**: Reduces hook instances from 3→1, prevents edge-case refetch storms
**Risk**: Low-medium — requires prop threading
**Files**: 4

`useSmartAlerts()` is currently mounted by three components:
1. `PortfolioOverviewContainer` (line 79) — passes to `PortfolioOverview` as prop
2. `DashboardAlertsPanel` (line 71) — primary alerts display
3. `useNotifications()` → `ModernDashboardApp` (line 239) — notification badge/center

**Approach**: Keep ONE mount in `ModernDashboardApp` (where `useNotifications()` already calls it), pass data down to both `PortfolioOverviewContainer` and `DashboardAlertsPanel`.

**Step 5a**: In `ModernDashboardApp.tsx`, the `useNotifications()` hook already calls `useSmartAlerts()` internally. Extract the alert data from notifications and pass it down:
```tsx
const { notifications, alertData } = useNotifications(); // alertData = raw smart-alerts
<PortfolioOverviewContainer smartAlerts={alertData} />
<DashboardAlertsPanel smartAlerts={alertData} />
```

**Step 5b**: Update `useNotifications()` to also expose raw alert data (not just transformed notifications).

**Step 5c**: Remove `useSmartAlerts()` from `PortfolioOverviewContainer` and `DashboardAlertsPanel`. Accept `smartAlerts` as a prop instead.

### Phase 6: Additional Quick Wins

**Step 6a**: `AssetAllocationContainer` eagerly mounts `useTradingAccounts()` on every dashboard page load (line 139), but accounts are only needed when the rebalance UI opens. Defer with `{ enabled: isRebalanceOpen }` or lazy-mount. Verify `useTradingAccounts` supports an `enabled` option before implementing.

**Step 6b**: `usePerformance()` in `PortfolioOverviewContainer` (line 83) — after Phase 2's cache seeding, this hook MAY find data in cache, but this is not guaranteed on initial load because `usePortfolioSummary()` and `usePerformance()` mount in the same render cycle and the scheduler runs in an effect (after render). Backend `PortfolioCacheService` coalesces in-flight duplicates regardless. No code change needed — this is a minor query-layer inefficiency, not a network issue.

---

## Expected Results

| Endpoint | Before | After | Fix |
|----------|--------|-------|-----|
| `/api/v2/portfolios` | 2-3× | 1× | Phase 1 |
| `/api/risk-score` | 3-4× | 1× | Phase 2 (scheduler fix + cache seeding) |
| `/api/analyze` (risk-analysis) | 3-4× | 1× | Phase 2 (scheduler fix + cache seeding) |
| `/api/performance` | 3-4× | 1× | Phase 2 (scheduler fix + cache seeding) |
| `/api/positions/alerts` | 3-4× | 1× | Phase 3 + Phase 5 |
| `/api/positions/holdings` | 2× | 1× | Phase 3 (scoped invalidation) |
| `/api/positions/market-intelligence` | 2× | 1× | Phase 3 (scoped invalidation) |
| `/api/positions/metric-insights` | 2× | 1× | Phase 3 (scoped invalidation) |
| `/api/allocations/target` | 2× | 1× | Phase 3 (scoped invalidation) |

**Projected total**: 31 → ~15-17 data requests (target ≤20 ✓)

---

## Execution Order

```
Phase 1 (quick wins)         — INDEPENDENT, 2 files
Phase 2 (scheduler + seeding) — INDEPENDENT, 4 files, biggest impact
Phase 3 (scoped invalidation) — INDEPENDENT, 1 file, second-biggest impact
Phase 4 (remove event handlers) — After Phase 3 (cleanup, not load-critical)
Phase 5 (smart-alerts consolidation) — INDEPENDENT, 4 files
Phase 6 (additional quick wins) — INDEPENDENT
```

Recommended order: **1 → 2 → 3 → 5 → 4 → 6**

Phases 1, 2, 3 can run in parallel with no file conflicts.

---

## Testing

1. **Network tab verification**: Fresh dashboard load with browser devtools Network tab open. Count unique data requests (excluding log-frontend). Target: ≤20.
2. **Functional verification**: All dashboard cards render correctly — overview, alerts, holdings, performance strip, allocation, income.
3. **Cache invalidation verification**: After a manual refresh (refresh button), data updates correctly across all cards.
4. **Portfolio switch verification**: Switch between portfolios in the selector — verify all data updates correctly (Phase 3's scoped invalidation must handle this).
5. **Other views**: Switch to Holdings, Performance, Research views — verify they still load data correctly (individual hooks should still work when portfolio-summary isn't loaded).
6. **Notification badge**: Verify notification center still shows alerts after Phase 5 consolidation.
7. **Frontend test suite**: Run `vitest` — no regressions.

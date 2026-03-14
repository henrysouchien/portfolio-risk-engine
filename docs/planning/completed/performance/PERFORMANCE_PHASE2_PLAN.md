# Performance Optimization — Phase 2 (Frontend Request Reduction)
**Status:** DONE

## Context

Phase 1 complete (`4d8ca07e`): batched frontendLogger (55→11 requests), fixed market-intelligence 500. Page load dropped from ~103 to ~45 API requests. Phase 2 targets the remaining inefficiencies in the frontend data-fetching architecture.

## Architecture Summary

The frontend has **two parallel data-fetching systems**:

1. **Legacy hooks** — `usePortfolioSummary()` fires 3 `useQuery` calls with legacy keys:
   - `riskScoreKey(portfolioId)` → `manager.calculateRiskScore()`
   - `riskAnalysisKey(portfolioId)` → `manager.analyzePortfolioRisk()`
   - `performanceKey(portfolioId)` → `manager.getPerformanceAnalysis()`

2. **Resolver hooks** — `useRiskAnalysis()`, `useRiskScore()`, `usePerformance()` all delegate to `useDataSource(sourceId, params)` which builds keys like `['sdk', 'risk-analysis', '{"portfolioId":"abc"}']`

These use **different TanStack query key namespaces**, so TanStack does NOT deduplicate them. However, both paths converge on `PortfolioManager` → `PortfolioCacheService.getOrFetch()`, which deduplicates via `pendingOperations` Map keyed by `${portfolioId}.${operation}.v${contentVersion}[.p${period}]`. So **duplicate HTTP requests are prevented** by the service layer for same-period calls — the cost is query-layer overhead (double query function execution, double state management), not actual duplicate network calls. **Exception**: `getRiskAnalysis()` passes `opts?.performancePeriod` to `getOrFetch` as the period suffix (`PortfolioCacheService.ts:356`), so explicit `performancePeriod: '1M'` vs omitted produces different service-layer cache keys (`portfolio1.riskAnalysis.v0.p1M` vs `portfolio1.riskAnalysis.v0`) — this IS a real duplicate HTTP request.

### Current call tree on page load (portfolio/risk/performance paths only):

Other hooks (smart-alerts, market-intelligence, AI-recommendations, metric-insights, hedging-recommendations, target-allocation) are omitted — they are not involved in the redundancy being fixed here.

```
ModernDashboardApp (app level)
├── usePortfolioSummary()     → 3 legacy-key queries (risk-score, risk-analysis, performance)
└── useRiskAnalysis()         → 1 resolver-key query (risk-analysis)

PortfolioOverviewContainer
├── usePortfolioSummary()     → 3 legacy-key queries (same keys as app-level → TanStack dedupes)
└── usePerformance()          → resolver-key performance

RiskMetricsContainer
└── useRiskAnalysis()         → resolver-key risk-analysis

RiskAnalysisModernContainer
├── useRiskAnalysis()         → resolver-key risk-analysis (same key → TanStack dedupes with RiskMetricsContainer)
└── useRiskScore()            → resolver-key risk-score

PerformanceViewContainer
└── usePerformance()          → resolver-key performance (same key as PortfolioOverviewContainer if benchmark=SPY;
                                different key if user has saved a non-SPY benchmark in localStorage)

AssetAllocationContainer
└── useRiskAnalysis({performancePeriod: '1M'})  → resolver-key with params (different TanStack key!
                                                   AND different service-layer key due to .p1M suffix)
```

### Three-layer deduplication:
1. **TanStack Query** — deduplicates same query keys (e.g. two `useRiskAnalysis()` calls produce one network request)
2. **PortfolioCacheService** `getOrFetch()` — deduplicates via `pendingOperations` Map keyed by `${portfolioId}.${operation}.v${contentVersion}` (catches cross-system duplicates between legacy and resolver)
3. **Event-based invalidation** — portfolio-data-invalidated / risk-data-invalidated events trigger refetches

### Prefetch key mismatch:
```
Scheduler prefetches:  ['sdk', 'risk-analysis', '{}']           ← no params
Consumer queries:      ['sdk', 'risk-analysis', '{"portfolioId":"abc"}']  ← with portfolioId
Result: prefetch cache miss every time — wasted work
```

### Eager sources (from descriptors.ts):
```
Level 0: positions          (no deps, priority 1)
Level 1: risk-score         (depends on positions, priority 2)
         risk-analysis      (depends on positions, priority 3)
         risk-profile       (depends on positions, priority 4)
         performance        (depends on positions, priority 5)
```

All 5 eager sources accept a `portfolioId` param. The scheduler only prefetches eager sources.

## Items

### 2B. Fix eager prefetch cache key alignment
**Impact**: Prefetch actually warms the cache for resolver hooks — eliminates redundant fetches on container mount | **Effort**: Medium
**Files**: `frontend/packages/connectors/src/resolver/scheduler.ts`

The scheduler (`scheduler.ts:89`) prefetches with `buildDataSourceQueryKey(sourceId)` passing no params, generating key `['sdk', sourceId, '{}']`. But consumers (via `useDataSource`) pass `{ portfolioId }`, generating different keys. Prefetch never warms the consumer cache — each eager source with an active UI consumer is fetched twice (once by scheduler with wrong key, once by consumer with correct key). Currently `risk-profile` has no direct UI consumer, and `positions` is primarily consumed as a dependency, so the practical impact is 3 wasted prefetches (risk-score, risk-analysis, performance).

**Change**: Build portfolio-scoped params for each eager source from `currentPortfolio` (already in scope at `scheduler.ts:64`):

```ts
// In scheduler.ts, new helper — ONLY for eager sources:
const buildPrefetchParams = (
  sourceId: DataSourceId,
  portfolio: Portfolio
): Record<string, unknown> => {
  // All eager sources accept portfolioId as their primary param.
  // Lazy sources are NOT prefetched by the scheduler so they don't appear here.
  switch (sourceId) {
    case 'positions':
    case 'risk-score':
    case 'risk-analysis':
    case 'risk-profile':
    case 'performance':
      return { portfolioId: portfolio.id };
    default:
      return {};
  }
};

// In the prefetch loop (~line 89):
const params = buildPrefetchParams(sourceId, currentPortfolio);
await queryClient.prefetchQuery({
  queryKey: buildDataSourceQueryKey(sourceId, params),
  queryFn: ({ signal }) => resolveWithCatalog(sourceId, params, services, currentPortfolio, signal),
  staleTime: dataCatalog.describe(sourceId).refresh.defaultTTL * 1000,
});
```

**Verification**:
- After prefetch completes, TanStack devtools should show `['sdk', 'risk-analysis', '{"portfolioId":"abc"}']` as `fresh` (not just `['sdk', 'risk-analysis', '{}']`)
- Container hooks should get instant cache hits instead of triggering new fetches
- No orphan `['sdk', sourceId, '{}']` keys in cache

### 2B-ii. Parallelize independent eager sources
**Impact**: Faster prefetch phase — Level 1 sources run concurrently instead of sequentially | **Effort**: Small (depends on 2B)
**Files**: `frontend/packages/connectors/src/resolver/scheduler.ts`

After key alignment, parallelize sources at the same dependency level. Currently the scheduler awaits each source sequentially even when they have no dependencies on each other.

**Change**: Group by dependency level and run each level with `Promise.allSettled` (not `Promise.all`, so one source failure doesn't abort siblings):

```ts
// Replace the sequential loop (~lines 86-102) with:
const levels = groupByDependencyLevel(orderedSourceIds);
for (const level of levels) {
  const results = await Promise.allSettled(
    level.map((sourceId) => {
      const params = buildPrefetchParams(sourceId, currentPortfolio);
      return queryClient.prefetchQuery({
        queryKey: buildDataSourceQueryKey(sourceId, params),
        queryFn: ({ signal }) =>
          resolveWithCatalog(sourceId, params, services, currentPortfolio, signal),
        staleTime: dataCatalog.describe(sourceId).refresh.defaultTTL * 1000,
      });
    })
  );
  // Log any rejected prefetches for debugging
  results.forEach((result, i) => {
    if (result.status === 'rejected') {
      console.warn(`[scheduler] prefetch failed for ${level[i]}:`, result.reason);
    }
  });
}
```

Helper function:
```ts
const groupByDependencyLevel = (orderedIds: DataSourceId[]): DataSourceId[][] => {
  const completed = new Set<DataSourceId>();
  const levels: DataSourceId[][] = [];

  let remaining = [...orderedIds];
  while (remaining.length > 0) {
    const level: DataSourceId[] = [];
    const nextRemaining: DataSourceId[] = [];

    for (const id of remaining) {
      const deps = dataCatalog.describe(id).loading.dependsOn ?? [];
      const allDepsMet = deps.every((dep) => completed.has(dep as DataSourceId));
      if (allDepsMet) {
        level.push(id);
      } else {
        nextRemaining.push(id);
      }
    }

    if (level.length === 0) {
      // Circular dependency safety — push remaining as final level
      levels.push(nextRemaining);
      break;
    }

    levels.push(level);
    level.forEach((id) => completed.add(id));
    remaining = nextRemaining;
  }

  return levels;
};
```

Expected levels after grouping:
```
Level 0: [positions]
Level 1: [risk-score, risk-analysis, risk-profile, performance]  ← all run concurrently
```

### 2C. Normalize `performancePeriod` default in risk-analysis cache key
**Impact**: Prevents 1 duplicate risk-analysis HTTP request | **Effort**: Small
**Files**: `frontend/packages/connectors/src/resolver/core.ts`

`AssetAllocationContainer` passes `{ portfolioId, performancePeriod: '1M' }` while other consumers pass `{ portfolioId }` (no `performancePeriod`). The backend defaults to `'1M'` (`portfolio_service.py:117`), and the descriptor declares `defaults: { performancePeriod: '1M' }` (`descriptors.ts:123-125`). These are semantically identical but generate different cache keys at **two layers**:

1. **TanStack**: `['sdk', 'risk-analysis', '{"portfolioId":"abc"}']` vs `['sdk', 'risk-analysis', '{"performancePeriod":"1M","portfolioId":"abc"}']`
2. **PortfolioCacheService**: `getRiskAnalysis()` passes `opts?.performancePeriod` to `getOrFetch` as the period arg (`PortfolioCacheService.ts:356`), and `generateCacheKey()` appends `.p${period}` when present (`PortfolioCacheService.ts:100`). So service-layer keys are `portfolio1.riskAnalysis.v0` vs `portfolio1.riskAnalysis.v0.p1M` — **this is a real duplicate HTTP request**, not just TanStack overhead.

**Change**: Strip default values before serializing params. In `core.ts`, add a defaults map:

```ts
const SOURCE_PARAM_DEFAULTS: Partial<Record<DataSourceId, Record<string, unknown>>> = {
  'risk-analysis': { performancePeriod: '1M' },
};

export const buildDataSourceQueryKey = <Id extends DataSourceId>(
  sourceId: Id,
  params?: Partial<SDKSourceParamsMap[Id]>
) => {
  const cleaned = stripDefaults(sourceId, params ?? {});
  return ['sdk', sourceId, serializeParams(cleaned)] as const;
};

const stripDefaults = (sourceId: DataSourceId, params: Record<string, unknown>) => {
  const defaults = SOURCE_PARAM_DEFAULTS[sourceId];
  if (!defaults) return params;
  const result = { ...params };
  for (const [key, defaultValue] of Object.entries(defaults)) {
    if (result[key] === defaultValue) {
      delete result[key];
    }
  }
  return result;
};
```

This ensures `{ performancePeriod: '1M' }` and `{}` produce the same cache key for `risk-analysis`.

**Verification**:
- TanStack devtools should show only ONE `risk-analysis` query key (not two with different params)
- AssetAllocationContainer changing to a non-default period (e.g. `3M`) still triggers a fresh fetch (non-default values are NOT stripped)

### 2A. Remove redundant app-level hooks from ModernDashboardApp
**Impact**: Eliminates 4 unnecessary TanStack query observer subscriptions per load | **Effort**: Small but requires careful testing
**Files**: `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx`

`ModernDashboardApp.tsx:165-166` calls both `usePortfolioSummary()` and `useRiskAnalysis()` at the app level. These create **always-mounted TanStack query observers** that persist for the entire app lifecycle. Removing them is safe because:
- `PortfolioOverviewContainer:71` already calls `usePortfolioSummary()` (same legacy keys → TanStack dedupes)
- `PortfolioOverviewContainer:76` calls `usePerformance()` (resolver key)
- `RiskMetricsContainer:77` calls `useRiskAnalysis()` (resolver key)
- `RiskAnalysisModernContainer` calls `useRiskAnalysis()` + `useRiskScore()` (resolver keys)
- `PerformanceViewContainer` calls `usePerformance()` (resolver key)
- `PortfolioCacheService.getOrFetch()` prevents duplicate HTTP requests across legacy/resolver

**Risk**: The app-level hooks are always-mounted observers. Specifically, the `usePortfolioSummary` → `getRiskAnalysis()` path writes risk analysis data to PortfolioRepository on success (`PortfolioCacheService.ts:346` → `repository.setRiskAnalysis()`). However, no current UI consumers were found reading risk data from the repository instead of their own hooks. The performance path does NOT write to the repository. So the practical risk of removing these is low — the main concern is ensuring container-level hooks alone sustain cache freshness during tab switching.

**Change**: Remove both hook calls from `ModernDashboardApp.tsx`:
```ts
// DELETE these lines (165-166):
const _portfolioSummaryHook = usePortfolioSummary();
const _riskAnalysisHook = useRiskAnalysis();
```

Also remove the unused imports for `usePortfolioSummary` and `useRiskAnalysis` (~line 45-46).

**Verification**:
- Page should still load all data (containers have their own hooks)
- Network requests should be identical (service-layer dedup was already preventing duplicates)
- TanStack devtools should show fewer query observer subscriptions
- **Important**: legacy query keys (`riskScoreKey`, `riskAnalysisKey`, `performanceKey`) will still exist because `PortfolioOverviewContainer` calls `usePortfolioSummary()`. Only the app-level *duplicate* observer subscriptions are removed, not the legacy keys themselves.
- Test tab switching — ensure data persists when navigating between views (the container-level observer remounts, but TanStack cache should satisfy it instantly)

### 2D. Throttle network-category logs in production
**Impact**: Further reduces log-frontend volume | **Effort**: Small
**Files**: `frontend/packages/chassis/src/services/frontendLogger.ts`

Auto-logged API request/response entries still dominate log volume. Add a production-mode filter:

```ts
// In the log() method, before queueLog():
if (this.isProduction && logData.category === 'network' && logData.level !== 'error') {
  // In production, only log network errors and slow requests
  const duration = (logData.data as any)?.duration_ms;
  if (!duration || duration < 2000) return; // Skip fast successful requests
}
```

## Implementation Order

1. **2C** first (small, safe — normalizes a cache key default, no behavioral change)
2. **2B** + **2B-ii** next (medium — fixes prefetch to actually work, parallelizes)
3. **2A** after verification of 2B/2C (removes always-mounted observers — riskier, do after the safe fixes confirm behavior)
4. **2D** last (optional polish)

**Rationale**: 2C and 2B are additive fixes that make existing code work better without removing anything. 2A is a removal that changes observer lifecycle — do it last when we can clearly attribute any regressions to this specific change.

## Verification

After all items:
1. `cd frontend && npx tsc --noEmit` — TypeScript passes
2. Page load: count API requests in network tab (target: <35, from current ~45)
3. TanStack devtools: only one `risk-analysis` entry per unique params (not two for default `1M` vs omitted)
4. Prefetch entries show `fresh` status when containers mount (not `fetching`)
5. `AssetAllocationContainer` changing period selector still works (non-default periods should trigger fresh fetches)
6. Tab switching doesn't cause data flickers or re-fetches (after 2A, container-level observers must sustain cache)

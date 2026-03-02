# Benchmark Selection UI

**Date**: 2026-02-28
**Status**: COMPLETE (implemented, tested, committed `33e5b78b`)

## Context

The performance view hardcodes SPY as the benchmark. The backend already fully supports `benchmark_ticker` as a parameter through the entire stack (`POST /api/performance` → `PortfolioService` → `compute_performance_metrics()`). The frontend just doesn't thread it through. This is P3 from the frontend data wiring audit.

**Goal**: Wire the existing benchmark selector in `PerformanceView` through the frontend data pipeline to the API.

## Codex R1 Findings (addressed below)

| # | Severity | Finding | Fix |
|---|----------|---------|-----|
| 1 | HIGH | Missing `APIService` layer — pass-through between cache and `RiskAnalysisService` | Added as step 6 in threading chain |
| 2 | HIGH | `PerformanceView` already has a benchmark selector (`selectedBenchmark` state, line 253). Adding another in container creates duplication | Lift state to container, pass via props (`selectedBenchmark` + `onBenchmarkChange`) |
| 3 | HIGH | `PerformanceAdapter.generateCacheKey()` doesn't include benchmark → stale cache on switch | Include benchmark identity in adapter cache key |
| 4 | LOW | `descriptors.ts` performance params don't include benchmarkTicker | Update for catalog consistency |

## Codex R2 Findings (addressed below)

| # | Severity | Finding | Fix |
|---|----------|---------|-----|
| 1 | MEDIUM | Cache key underspecified — plan didn't show exact key composition | Explicit `performanceAnalysis:${benchmarkTicker}` operation string |
| 2 | MEDIUM | localStorage persistence not handled after state lift | Container hydrates from localStorage; PerformanceView continues save-on-change |
| 3 | LOW | Threading diagram missing return path through adapter | Added adapter layer to diagram |

## Codex R3 Findings (addressed below)

| # | Severity | Finding | Fix |
|---|----------|---------|-----|
| 1 | HIGH | Container passes 1-item `benchmarks` array from API → overrides fallback list in selector | Don't pass `benchmarks` in mapped data — let PerformanceView use its static fallback list |
| 2 | MEDIUM | localStorage parse in state initializer can crash on malformed data | Wrap in try/catch with 'SPY' fallback |
| 3 | LOW | Save effect line reference wrong (315-322 is hydration, save is 343-357) | Corrected line references |
| 4 | LOW | Cache key duplication: container 'SPY' → `performanceAnalysis:SPY` vs other callers `performanceAnalysis` | Container passes `undefined` when benchmark is 'SPY' (default) — canonical key stays `performanceAnalysis` |

## What Already Works (no backend changes needed)

- `POST /api/performance` accepts `benchmark_ticker` in body (`app.py:1454`)
- `PortfolioService.analyze_performance(benchmark_ticker=)` (`services/portfolio_service.py:538`)
- `PerformanceResult` includes `benchmark_analysis` + `benchmark_comparison` (`core/result_objects/performance.py:90`)
- `PerformanceAdapter.transformBenchmark()` reads `benchmark_ticker` from response (`connectors/src/adapters/PerformanceAdapter.ts:989`)
- `PerformanceView.tsx:253,889` already has a benchmark selector UI (SPY/QQQ/VTI/CUSTOM) — just not wired to data fetching

## Files to Modify (frontend only — 9 files)

### 1. `chassis/src/catalog/types.ts` — Type definition
**Line 228**: Add `benchmarkTicker` to params map:
```typescript
performance: { portfolioId?: string; benchmarkTicker?: string };
```

### 2. `chassis/src/catalog/descriptors.ts` — Catalog metadata
**Line 198**: Add `benchmarkTicker` to performance descriptor params for catalog consistency.

### 3. `connectors/src/features/analysis/hooks/usePerformance.ts` — Hook
Accept `benchmarkTicker` and pass to `useDataSource`. Follow `useRiskAnalysis` pattern (line 5):
```typescript
export const usePerformance = (options?: { benchmarkTicker?: string }) => {
  const resolved = useDataSource('performance', {
    portfolioId: currentPortfolio?.id,
    benchmarkTicker: options?.benchmarkTicker,
  });
```

### 4. `connectors/src/resolver/registry.ts` — Resolver
**Line 202**: Pass `params?.benchmarkTicker` to manager:
```typescript
const result = await manager.getPerformanceAnalysis(portfolio.id!, params?.benchmarkTicker);
```

### 5. `connectors/src/managers/PortfolioManager.ts` — Manager
**Line 396**: Add `benchmarkTicker?: string` param, pass to cache service.

### 6. `chassis/src/services/PortfolioCacheService.ts` — Cache
**Line 265**: Add `benchmarkTicker?: string` param. Pass to API service. Include benchmark in cache key via the `operation` string passed to `generateCacheKey()` (format: `${portfolioId}.${operation}.v${contentVersion}`):
```typescript
async getPerformanceAnalysis(portfolioId: string, portfolio: Portfolio, benchmarkTicker?: string): Promise<PerformanceApiResponse> {
  const operation = benchmarkTicker ? `performanceAnalysis:${benchmarkTicker}` : 'performanceAnalysis';
  const result = await this.getOrFetch(portfolioId, operation, () => {
    return this.apiService.getPerformanceAnalysis(portfolioId, benchmarkTicker);
  });
```
This ensures different benchmarks get different cache entries. Default (no benchmarkTicker) uses `'performanceAnalysis'` — matching current behavior exactly.

### 7. `chassis/src/services/APIService.ts` — API facade (R1 fix)
**Line 486**: Add `benchmarkTicker?: string` param, forward to `RiskAnalysisService`:
```typescript
async getPerformanceAnalysis(portfolioId: string, benchmarkTicker?: string): Promise<PerformanceApiResponse> {
  return this.riskAnalysisService.getPerformanceAnalysis(portfolioId, benchmarkTicker);
}
```

### 8. `chassis/src/services/RiskAnalysisService.ts` — API call
**Line 176-192**: Add `benchmarkTicker?: string` param. Include in POST body:
```typescript
async getPerformanceAnalysis(portfolioId: string, benchmarkTicker?: string): Promise<PerformanceApiResponse> {
  // ...
  body: JSON.stringify({
    portfolio_name: portfolioName,
    ...(benchmarkTicker && { benchmark_ticker: benchmarkTicker }),
  })
}
```

### 9. `ui/src/components/dashboard/views/modern/PerformanceViewContainer.tsx` — Container (R1 fix)
Instead of adding a new selector, lift state to container and wire to existing `PerformanceView` selector.

Initialize from localStorage to preserve user preference across remounts/reloads (PerformanceView currently owns this persistence at line 343-357 — we're lifting hydration to the container):
```typescript
const [benchmarkTicker, setBenchmarkTicker] = useState(() => {
  try {
    const saved = localStorage.getItem('performance-preferences');
    if (saved) {
      const prefs = JSON.parse(saved);
      return prefs.benchmark || 'SPY';
    }
  } catch { /* malformed localStorage — ignore */ }
  return 'SPY';
});

// Pass undefined for SPY (default) to avoid cache key duplication with other callers
const benchmarkParam = benchmarkTicker === 'SPY' ? undefined : benchmarkTicker;
const { data, ... } = usePerformance({ benchmarkTicker: benchmarkParam });
```

**Benchmark list**: Do NOT pass `benchmarks` in mapped data (currently line 309-314 passes a 1-item array from API response, overriding the fallback list). Remove the `benchmarks` property from the mapped data object so PerformanceView uses its static fallback list (SPY/QQQ/VTI/CUSTOM at line 894-898).

Pass to PerformanceView as props:
```typescript
<PerformanceView
  data={mappedData}  // without benchmarks property
  selectedBenchmark={benchmarkTicker}
  onBenchmarkChange={setBenchmarkTicker}
  ...
/>
```

### 10. `ui/src/components/portfolio/PerformanceView.tsx` — View component (R1 fix)
Add props to `PerformanceViewProps`:
```typescript
interface PerformanceViewProps {
  // ... existing props ...
  selectedBenchmark?: string;
  onBenchmarkChange?: (ticker: string) => void;
}
```

Replace internal `selectedBenchmark` state (line 253) with props. If `onBenchmarkChange` prop is provided, use it; otherwise fall back to local state for backwards compatibility.

The existing selector UI at line 889 already renders SPY/QQQ/VTI/CUSTOM options — just wire `onValueChange` to call `onBenchmarkChange` prop.

**Persistence**: When `onBenchmarkChange` is provided (controlled mode), the localStorage save effect (line 343-357) should still persist benchmark to `performance-preferences` so the container can hydrate it on next mount. The container owns initial hydration; PerformanceView continues to own the save-on-change effect.

### 11. `connectors/src/adapters/PerformanceAdapter.ts` — Cache key (R1 fix)
**Line 898**: Include benchmark ticker in `generateCacheKey()` content hash so switching benchmarks doesn't return stale cached transforms:
```typescript
const content = {
  analysisPeriod,
  returns: performance.returns,
  benchmarkTicker: (performance.benchmark_analysis as Record<string, unknown>)?.benchmark_ticker,
  // ... existing fields ...
};
```

## Threading Diagram

```
PerformanceViewContainer (state: benchmarkTicker, hydrated from localStorage)
  → usePerformance({ benchmarkTicker })
    → useDataSource('performance', { portfolioId, benchmarkTicker })
      → registry resolver (params.benchmarkTicker)
        → PortfolioManager.getPerformanceAnalysis(id, benchmarkTicker)
          → PortfolioCacheService (cache key: performanceAnalysis:${ticker})
            → APIService.getPerformanceAnalysis(id, benchmarkTicker)
              → RiskAnalysisService.getPerformanceAnalysis(id, benchmarkTicker)
                → POST /api/performance { portfolio_name, benchmark_ticker }
                  → Backend (already works)
  ← response flows back through:
        RiskAnalysisService → APIService → PortfolioCacheService (cached)
          → registry resolver → AdapterRegistry → PerformanceAdapter.transform()
            → PerformanceAdapter.generateCacheKey() (includes benchmark_ticker in hash)
              → useDataSource resolved data → PerformanceViewContainer → PerformanceView
```

## Key Notes

- **Cache key must include benchmark** at two levels: (1) `PortfolioCacheService` raw data cache, (2) `PerformanceAdapter` transform cache
- **Default is SPY**: Container passes `undefined` when benchmark is SPY so the cache key stays `performanceAnalysis` — same as other callers. Non-SPY benchmarks use `performanceAnalysis:${ticker}`. All param additions are optional (`?:`).
- **Existing UI**: `PerformanceView` already has a benchmark selector (line 889) with fallback list (SPY/QQQ/VTI/CUSTOM). We're wiring it, not adding a new one. Container must NOT pass `benchmarks` in mapped data (line 309-314) to avoid overriding the fallback list with a single-item array.
- **No backend changes**: Entire backend stack already supports this.
- **Other callers**: `usePortfolioSummary.ts:311` and `SessionServicesProvider.tsx:411` also call `getPerformanceAnalysis()` — they'll pass `undefined` for benchmarkTicker (default SPY). No breaking change since all params are optional.

## Verification

1. `cd frontend && pnpm build` — builds cleanly with no TS errors
2. Open performance view in browser — existing benchmark selector (SPY/QQQ/VTI) visible
3. Select QQQ — data refetches, benchmark name/alpha/beta/returns all update
4. Select SPY — matches original behavior
5. Switch back to previous benchmark — should use cached data (fast)

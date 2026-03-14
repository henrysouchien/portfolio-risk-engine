# Hook Migration Plan: Bespoke → useDataSource
**Status:** DONE

## Context

Phase 1 of the Composable App Framework introduced `useDataSource` (resolver) and the Data Catalog (18 descriptors). Currently 5 of 34 hooks use `useDataSource`; 29 are bespoke. Of those 29, **18 are data-fetch hooks** that should migrate to thin `useDataSource` wrappers. The remaining 11 (mutations, auth flows, chat) are legitimately different patterns.

**Goal**: Migrate 18 data-fetch hooks to use `useDataSource`, reducing ~2,400 lines of duplicated query/cache/error logic to ~600 lines of thin wrappers.

**Current inventory**: 18 `DataSourceId` values in `chassis/catalog/types.ts`, 18 catalog descriptors in `descriptors.ts`, 18 resolvers in `registry.ts` (1:1:1 correspondence). New source IDs for Tier 3 hooks require additions to all three.

**Template**: Migrated hooks follow a consistent ~35-line pattern:
```typescript
export function useXxx(params?) {
  const resolved = useDataSource('source-id', { ...params });
  return useMemo(() => ({
    data: resolved.data,
    loading: resolved.loading,
    isLoading: resolved.loading,
    isRefetching: resolved.isFetching && !resolved.loading,
    error: resolved.error?.userMessage ?? null,
    refetch: resolved.refetch,
    refreshXxx: resolved.refetch,
    hasData: !!resolved.data,
    hasError: !!resolved.error,
    hasPortfolio: !!resolved.data,
    currentPortfolio,
    clearError: () => {},
  }), [resolved, currentPortfolio]);
}
```

## Migration Tiers

### Tier 1 — Simple Hooks (4 hooks, ~200 lines → ~140 lines)

Small hooks with straightforward data-fetching. Some need resolver updates before migration.

| Hook | Lines | Resolver Status | Notes |
|------|-------|----------------|-------|
| usePositions | 57 | `positions` resolver exists but **data shape mismatch** — resolver reads raw holdings from portfolio store; hook calls `api.getPositionsHoldings()` + `PositionsAdapter.transform()` (enriched with day change, sparklines, sector, etc.). **Must update resolver** to call API + adapter instead of reading store. |
| useTargetAllocation | 33 | No `allocation` resolver or descriptor — needs both | Tiny hook, `api.getTargetAllocations()`. |
| useMonteCarlo | 62 | No resolver — needs descriptor + resolver | `enabled: false` pattern, manual trigger via `runMonteCarlo()`. |
| useStrategyTemplates | 14 | No resolver — needs descriptor + resolver | Just `api.getStrategyTemplates()`. |

### Tier 2 — Have Resolver, Custom Actions (3 hooks, ~1,073 lines → ~200 lines)

Resolver exists but hook has local state or action methods beyond basic data-fetching. Strategy: split data-fetching (→ useDataSource) from UI state (stays in hook).

| Hook | Lines | Resolver | Custom Logic |
|------|-------|----------|-------------|
| useStockAnalysis | 280 | `stock-analysis` | Local `[ticker, setTicker]` state + `analyzeStock()` action. Split: data via resolver, ticker state stays local. |
| usePortfolioOptimization | 294 | `optimization` | Strategy param (`min_variance`/`max_return`), constraint inputs. Split: results via resolver, input state stays local. |
| useWhatIfAnalysis | 499 | `what-if` | Massive input management (inputMode, weightInputs, deltaInputs, add/remove/update asset). Split: scenario results via resolver, input management stays local. ~200 lines of input state will remain. |

### Tier 3 — Need New Resolver + Descriptor (8 hooks, ~640 lines → ~280 lines)

No resolver exists. Need to: (a) add catalog descriptor, (b) add resolver to registry, (c) rewrite hook.

| Hook | Lines | New Source ID | Adapter/Transform |
|------|-------|--------------|-------------------|
| useBacktest | 128 | `backtest` | `BacktestAdapter.transform()` |
| useStressTest | 100 | `stress-test` | `StressTestAdapter.transform()` |
| useHedgingRecommendations | 105 | `hedging-recommendations` | `HedgingAdapter.transform()` |
| usePeerComparison | 37 | `peer-comparison` | Raw API response |
| useMarketIntelligence | 58 | `market-intelligence` | `transformEvents()` inline |
| useSmartAlerts | 56 | `smart-alerts` | `transformAlerts()` inline |
| useMetricInsights | 58 | `metric-insights` | `transformInsights()` inline |
| useStockSearch | 37 | `stock-search` | Raw API response |

For each: (a) add to `DataSourceId` union in `chassis/catalog/types.ts`, (b) add output type to `SDKSourceOutputMap` + params type to `SDKSourceParamsMap`, (c) add descriptor to `descriptors.ts`, (d) add resolver to `registry.ts`, (e) rewrite hook as thin wrapper.

**Pattern for new descriptors:**
```typescript
{
  id: 'backtest',
  label: 'Backtest Results',
  category: 'trading',
  params: [{ name: 'strategy', type: 'string', required: true, description: 'Strategy name' }, ...],
  fields: [{ name: 'returns', type: 'object', description: 'Backtest return series' }, ...],
  flagTypes: [{ name: 'backtest_warning', description: '...', severity: 'warning' }],
  refresh: { defaultTTL: 900, staleWhileRevalidate: false, invalidatedBy: ['all-data-invalidated'] },
  loading: { strategy: 'lazy', dependsOn: ['positions'], priority: 10 },
  error: { retryable: true, maxRetries: 2, timeout: 30000, fallbackToStale: false },
}
```

**Pattern for new resolvers:**
```typescript
'backtest': async (params, { services, currentPortfolio, signal }) => {
  const manager = services.get('portfolioManager');
  const result = await manager.analyzeBacktest(params);
  const adapter = AdapterRegistry.getAdapter('backtest', [...], () => new BacktestAdapter(), cache);
  return adapter.transform(result);
}
```

### Tier 4 — Special Patterns (3 hooks, ~560 lines)

These hooks have structural differences from the `useDataSource` read pattern. Evaluate case-by-case.

| Hook | Lines | Issue | Recommendation |
|------|-------|-------|---------------|
| usePortfolioSummary | 398 | Aggregates 3 resolvers (risk-score + risk-analysis + performance) | Migrate to 3 `useDataSource` calls + `useMemo` aggregation. No new resolver needed — it's a composition of existing ones. ~80 lines. |
| useRealizedPerformance | 24 | Uses `useMutation` (POST with params) | Add descriptor + resolver with param-based fetching. Small hook, easy migration if resolver handles POST. |
| useScenarioHistory | 137 | Query + 2 mutations (save, delete) | Split: read path → `useDataSource('scenario-history')`, mutations stay as `useMutation`. ~60 lines. |

## Excluded (11 hooks, not data-fetch pattern)

These hooks are mutations, auth flows, or streaming — legitimately different from `useDataSource`:

- **Mutations**: useHedgePreview (27), useHedgeTrade (51), useSetTargetAllocation (44), useRebalanceTrades (20)
- **Auth/Connection**: usePlaid (409), useSnapTrade (396), useConnectAccount (238)
- **Settings**: useRiskSettings (492) — complex form state + mutations
- **Chat**: usePortfolioChat (972) — streaming SSE, completely different pattern
- **Sync**: usePendingUpdates (77) — polling pattern
- **AI**: useAIRecommendations (70) — AI endpoint, could migrate later

## Execution Order

**Batch A — Small hooks** ✅ DONE
- useStrategyTemplates (14→35), useStockSearch (37→35), usePeerComparison (37→35)
- useMarketIntelligence (58→35), useSmartAlerts (56→35), useMetricInsights (58→35)
- useTargetAllocation (33→35)
- New: 7 `DataSourceId` values + 7 descriptors + 7 resolvers
- **Scope**: 7 hooks, ~293 lines → ~245 lines. Mechanical, low risk.
- **Note**: usePositions deferred — requires resolver rewrite (store → API+adapter).

**Batch B — Scenario hooks** ✅ DONE (`f974ab70`)
- useBacktest (128→55), useStressTest (100→50), useMonteCarlo (62→50), useHedgingRecommendations (105→72)
- New: 4 descriptors + 4 resolvers (backtest, stress-test, monte-carlo, hedging-recommendations)
- Added `enabled` option to `useDataSource` (3rd param), `_runId` cache-busting, `runPortfolioId` render-time guard
- 12 intentional behavioral changes documented (BC-1 through BC-12) in `HOOK_MIGRATION_BATCH_B_PLAN.md`
- **Scope**: 4 hooks, ~395 lines → ~227 lines. 52 tests, TypeScript clean, Chrome live-tested.
- **Note**: usePositions deferred to separate batch — requires resolver rewrite (store → API+adapter).

**Batch C — Custom-action + summary hooks** ✅ DONE (`d37b7c53`)
- useStockAnalysis (280→36), usePortfolioOptimization (294→38), useRealizedPerformance (24→97), usePortfolioSummary (398→29)
- Updated stock-analysis + optimization resolvers to route through adapters
- New: 2 descriptors + 2 resolvers (realized-performance, portfolio-summary)
- DataSourceError thrown directly in resolvers (bypasses classifyError rewriting)
- useRealizedPerformance: mutation→query with monotonic `_runId`, promise-based `mutateAsync` settlement
- 15 intentional behavioral changes documented (BC-1 through BC-15) in `HOOK_MIGRATION_BATCH_C_PLAN.md`
- **Scope**: 4 hooks, ~996 lines → ~200 lines. 441 tests, TypeScript clean.

**Batch D — Complex state hooks** ✅ DONE (`f6c1e94b`)
- useWhatIfAnalysis (499→261) — input management stays local, data-fetching via `useDataSource('what-if')`
- Updated what-if resolver to route through `WhatIfAnalysisAdapter` + `DataSourceError`
- Descriptor: fields updated to match adapter output, `dependsOn` removed, `retryable: false`
- `_runId` monotonic trigger, `runPortfolioId` guard, `guardedRefetch`, portfolio-change reset
- 9 intentional behavioral changes documented (BC-1 through BC-9) in `HOOK_MIGRATION_BATCH_D_PLAN.md`
- **Scope**: 1 hook, 499 lines → 261 lines. 443 tests, TypeScript clean, Chrome live-tested.
- **Note**: useScenarioHistory deferred — 90% mutations (save/clear history), doesn't fit `useDataSource`.

## Verification

Each batch:
1. `pnpm typecheck` — zero TS errors
2. `pnpm test` in connectors package — existing tests pass
3. Chrome verify — views using migrated hooks render correctly
4. Check that TanStack Query devtools show resolver-managed queries (not duplicated manual ones)

## Backward Compatibility

- All hooks keep their existing return type signatures
- Consumers (TSX components) require zero changes
- Old query keys may still exist in TanStack cache — verify no duplicate fetching
- Legacy aliases (e.g., `refreshSummary` → `refetch`) preserved in wrapper

## Metrics

| | Before | After |
|--|--------|-------|
| Bespoke data-fetch hooks | 18 | 0 |
| Lines of hook code | ~2,400 | ~880 |
| Resolver coverage | 28% (5/18) | 100% (18/18) |
| `DataSourceId` union members | 18 | 26 (+8 new) |
| Catalog descriptors | 18 | 26 (+8 new) |
| Resolvers in registry | 18 | 26 (+8 new) |

**New DataSourceId values needed** (add to `chassis/catalog/types.ts`):
`backtest`, `stress-test`, `hedging-recommendations`, `peer-comparison`, `market-intelligence`, `smart-alerts`, `metric-insights`, `stock-search`

Plus 2 for Tier 4: `realized-performance`, `scenario-history`

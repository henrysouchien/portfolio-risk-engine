# Hook Migration Batch B — Scenario + Hedging Hooks
**Status:** DONE

## Scope

Migrate 4 hooks to `useDataSource`: 4 new DataSourceIds + descriptors + resolvers. `usePositions` deferred to Batch B2 (resolver shape mismatch needs separate treatment).

| Hook | Lines | Pattern | New Infrastructure |
|------|-------|---------|-------------------|
| useHedgingRecommendations | 105 | Param-gated auto-fetch | New descriptor + resolver |
| useBacktest | 128 | Manual trigger (`enabled: false`) | New descriptor + resolver |
| useStressTest | 100 | Manual trigger (`enabled: false`) | New descriptor + resolver |
| useMonteCarlo | 62 | Manual trigger (`enabled: false`) | New descriptor + resolver |

Total: ~395 lines → ~170 lines.

### usePositions — Deferred

The existing `positions` resolver returns `PositionsSourceData` with `Holding[]` (fields: `market_value`, `security_name`). `usePositions` calls `api.getPositionsHoldings()` + `PositionsAdapter.transform()` which returns `PositionsData` with `PositionsHolding[]` (fields: `value`, `name`, `dayChange`, `trend`, `riskScore`, etc.) — a completely different shape.

6 downstream resolvers (trading-analysis, exit-signals, income-projection, tax-harvest, portfolio-news, events-calendar) depend on `holding.market_value` from the current `positions` contract. Changing the resolver output breaks them.

**Options** (for later):
- (a) Create `positions-enriched` DataSourceId with API+adapter shape — dual resolvers
- (b) Update `PositionsSourceData` to match adapter output + update 6 downstream resolvers
- (c) Keep usePositions as bespoke hook (it's only 57 lines)

## Infrastructure Change: `enabled` Option for useDataSource

**Problem**: `useDataSource` always fetches when dependencies are ready. Three hooks use `enabled: false` + manual trigger. Without an `enabled` option, we can't suppress initial fetch.

**Solution**: Add optional third parameter to `useDataSource`:

```typescript
export const useDataSource = <Id extends DataSourceId>(
  sourceId: Id,
  params?: Partial<SDKSourceParamsMap[Id]>,
  options?: { enabled?: boolean }
): ResolvedData<SDKSourceOutputMap[Id]> => {
  // ...
  const query = useQuery({
    // ...
    enabled: dependenciesReady && (options?.enabled ?? true),
  });
```

Backwards-compatible — existing callers pass no third arg, default `enabled: true`.

## Step 1 — Add `enabled` option to useDataSource

File: `frontend/packages/connectors/src/resolver/useDataSource.ts`

- Add `options?: { enabled?: boolean }` as third param
- Apply `&& (options?.enabled ?? true)` to the `enabled` field in `useQuery`
- No other changes needed — fully backwards-compatible

## Step 2 — Add 4 New DataSourceIds + Output/Param Types

File: `frontend/packages/chassis/src/catalog/types.ts`

Add to `DataSourceId` union:
```
| 'backtest'
| 'stress-test'
| 'hedging-recommendations'
| 'monte-carlo'
```

**Output types — structural types defined in chassis (no cross-package imports):**

Chassis MUST NOT import from connectors (`chassis/package.json` has no connectors dependency). Define structural interfaces in `types.ts` that the real adapter outputs satisfy via TypeScript structural typing. The connectors adapters are the source of truth — these types mirror their shapes.

```typescript
// Matches BacktestData from BacktestAdapter exactly
export interface BacktestSourceData {
  success: boolean;
  backtestResults: Array<{ period: string; return: number; benchmark: number; alpha: number; sharpe: number }>;
  performanceMetrics: Record<string, unknown>;
  monthlyReturns: Record<string, number>;
  benchmarkMonthlyReturns: Record<string, number>;
  cumulativeReturns: Record<string, number>;
  benchmarkCumulative: Record<string, number>;
  annualBreakdown: Array<Record<string, unknown>>;
  weights: Record<string, number>;
  benchmarkTicker: string;
  excludedTickers: string[];
  warnings: string[];
  analysisDate: string | null;
  portfolioName: string | null;
  summary: Record<string, unknown>;
  portfolioMetadata: Record<string, unknown>;
  securityAttribution: Array<{ name: string; allocation?: number; return: number; contribution: number; beta?: number }>;
  sectorAttribution: Array<{ name: string; allocation?: number; return: number; contribution: number; beta?: number }>;
  factorAttribution: Array<{ name: string; allocation?: number; return: number; contribution: number; beta?: number }>;
  rawResponse: unknown;
}

// Matches StressTestData from StressTestAdapter exactly
export interface StressTestSourceData {
  success: boolean;
  scenarioName: string;
  scenarioId?: string;
  severity?: string;
  estimatedImpactPct: number;
  estimatedImpactDollar: number | null;
  positionImpacts: Array<{ ticker: string; weight: number; estimatedImpactPct: number; portfolioContributionPct: number }>;
  factorContributions: Array<{ factor: string; shock: number; portfolioBeta: number; contributionPct: number }>;
  riskContext: {
    currentVolatility: number;
    leverageRatio: number;
    systematicRiskPct: number;
    worstPosition: { ticker: string; impactPct: number } | null;
    bestPosition: { ticker: string; impactPct: number } | null;
  };
  rawResponse: unknown;
}

// Wraps HedgeStrategy[] from HedgingAdapter
export interface HedgingRecommendationsSourceData {
  strategies: Array<{
    strategy: string;
    cost: string;
    protection: string;
    duration: string;
    efficiency: 'High' | 'Medium' | 'Low';
    hedgeTicker: string;
    suggestedWeight: number;
    details: {
      description: string;
      riskReduction: number;
      expectedCost: number;
      implementationSteps: string[];
      marketImpact: {
        beforeVaR: string;
        afterVaR: string;
        riskReduction: string;
        portfolioBeta: string;
      };
    };
  }>;
}

// Matches MonteCarloApiResponse from chassis types
export type MonteCarloSourceData = MonteCarloApiResponse;
```

Add to `SDKSourceOutputMap`:
```typescript
backtest: BacktestSourceData;
'stress-test': StressTestSourceData;
'hedging-recommendations': HedgingRecommendationsSourceData;
'monte-carlo': MonteCarloSourceData;
```

Add to `SDKSourceParamsMap`:
```typescript
backtest: {
  portfolioId?: string;  // Portfolio-scoped query key (matches current backtestKey behavior)
  weights: Record<string, number>;
  benchmark?: string;
  period?: BacktestPeriod;  // Re-use existing type from chassis types/api.ts
  startDate?: string;
  endDate?: string;
  _runId?: number;  // Force unique query key for re-runs with same params
};
'stress-test': {
  portfolioId?: string;  // Portfolio-scoped query key
  scenario: string;
  _runId?: number;  // Force unique query key for re-runs with same scenario
};
'hedging-recommendations': {
  portfolioId?: string;  // Portfolio-scoped query key
  weights: Record<string, number>;
  portfolioValue?: number;
};
'monte-carlo': {
  portfolioId?: string;  // Portfolio-scoped query key
  numSimulations?: number;
  timeHorizonMonths?: number;
  _runId?: number;  // Force unique query key for re-runs
};
```

### Portfolio-scoped query keys

Current hooks use portfolio-scoped React Query keys (e.g., `backtestKey(portfolioId, backtestId)`). `buildDataSourceQueryKey()` keys by `['sdk', sourceId, serializedParams]`, so `portfolioId` MUST be in params to prevent cache bleed between portfolios. Each hook wrapper passes `currentPortfolio?.id` as `portfolioId`.

**`portfolioId` is for cache scoping only** — it isolates query keys per portfolio but does NOT route the resolver to a specific portfolio. The manager methods (`analyzeBacktest`, `analyzeStressTest`, `analyzeMonteCarlo`) internally read from `usePortfolioStore.getState().currentPortfolioId` (`PortfolioManager.ts:504/541/575`).

**Note**: This is specific to Batch B managers. Other existing managers (risk-analysis, optimization, what-if at `PortfolioManager.ts:259/396/425/478`) accept an explicit `portfolioId` param and resolve via `byId[portfolioId]`. The Batch B managers do not — they always use the store's current portfolio. This could be improved in a future PR by adding `portfolioId` params to `analyzeBacktest`/`analyzeStressTest`/`analyzeMonteCarlo`, but it's out of scope for this migration. The wrappers always pass `currentPortfolio?.id`, keeping key and store in sync. The `runPortfolioId` render-time guard (BC-12) adds additional safety by disabling the query if the active portfolio changes after a run.

### `_runId` for re-run dedup

`_runId: Date.now()` changes the query key, forcing React Query to create a new cache entry and call the resolver fresh. This matches the current `backtestId`/`stressTestRunId` behavior. The resolver strips `_runId` before calling the manager — the downstream `PortfolioCacheService` caches by business-param hash, which is the same behavior as the current hooks (they also call the manager with identical params and hit the same cache).

## Step 3 — Add 4 New Catalog Descriptors

File: `frontend/packages/chassis/src/catalog/descriptors.ts`

Pattern follows existing descriptors. All 4 are `category: 'trading'`, lazy loading, low priority.

**Wiring checklist** (each new descriptor must be added to all 3 structures):
1. `descriptorList` array (line ~810) — append 4 new descriptor consts
2. `sdkDescriptorMap` object (line ~838) — add 4 new `'source-id': descriptorConst` entries
3. `ensureFieldConformance()` conformance object (line ~899) — add 4 new `'source-id': true` entries
4. Update descriptor count assertion in `descriptors.test.ts:6` (test currently asserts 18, but `descriptorList` has 25 entries after Batch A — update assertion to actual count + 4 new = 29)

**Explicit descriptor fields** (must be set, not left to defaults or copied from adjacent descriptors):
- `dependsOn: []` — see rationale below
- `invalidatedBy: []` — explicitly empty. Adjacent descriptors (e.g., `optimization`, `what-if`) use `['portfolio-data-invalidated']` which subscribes to eventBus events and auto-invalidates active queries (`useDataSource.ts:95-115`). For manual-trigger hooks, this would cause unintended auto-refetch when portfolio data changes while the component is mounted. Current hooks are permanently `enabled: false` and immune to event-driven invalidation. Empty array preserves this behavior.
- `fallbackToStale: false` — no stale data fallback on error (matches current behavior)

**No `dependsOn`**: All 4 descriptors use `dependsOn: []` (empty). While `useAnalysisReport.ts:18` does call `useDataSource('positions')`, `sourceDependencySatisfied()` in `useDataSource.ts:58-62` checks globally across all `['sdk', sourceId]` entries — so a positions query from portfolio A could falsely satisfy the dependency for a backtest on portfolio B (cross-portfolio false satisfaction). More importantly, the current hooks have NO positions dependency — they fire independently when the user triggers them. Adding `dependsOn: ['positions']` would introduce a new coupling that doesn't exist today.

- Backtest + stress-test + Monte Carlo: `defaultTTL: 3600` (production 'reference' staleTime). **Note**: current hooks use `getStaleTime('reference')` which is env-dependent: 0 in test, ~120s in dev, 3600s in prod (`queryConfig.ts:118-149`). The descriptor `defaultTTL` is a static value — `useDataSource` converts it to `staleTime: defaultTTL * 1000`. This means dev/test environments lose the shorter stale times. Acceptable: these are manual-trigger hooks where staleTime mainly affects reconnect refetch (BC-2), not primary UX. **`timeout: 120000`** (2 min) — override default 30s. See BC-10.
- Hedging: `defaultTTL: 600` (market-dependent, params-gated). `retryable: true, maxRetries: 2`. **BC-4**: per-error retry suppression lost — see "Intentional Behavioral Changes".

**Why `defaultTTL: 3600` (not 0) for manual-trigger sources:** `_runId` already forces unique query keys. `defaultTTL: 0` makes results immediately stale; `refetchOnReconnect: true` (global default) would re-run them. `defaultTTL: 3600` matches current 'reference' staleTime. **BC-2**: after 60+ min, reconnect can trigger backend refetch — see "Intentional Behavioral Changes".

**On component remount**: `useState(null)` resets params → `enabled: false` → no auto-run (same as current).

## Step 4 — Add 4 New Resolvers

File: `frontend/packages/connectors/src/resolver/registry.ts`

**No-portfolio guard**: All 3 manual-trigger wrappers gate `runXxx()` on `!!currentPortfolio` — bails without setting state (**BC-1**: intentional improvement, see "Intentional Behavioral Changes"). The `requirePortfolio()` in the resolver is a safety net — should never be reached. Render-time `runPortfolioId` guard prevents auto-execution if portfolio changes mid-render.

### 4a. New `backtest` resolver

```typescript
'backtest': async (params, context) => {
  const { manager, unifiedAdapterCache } = context.services;
  const portfolio = requirePortfolio('backtest', getPortfolio(params?.portfolioId, context.currentPortfolio));

  const result = await manager.analyzeBacktest({
    weights: params?.weights ?? {},
    benchmark: params?.benchmark,
    period: params?.period,
    startDate: params?.startDate,
    endDate: params?.endDate,
  });

  if (result.error) throw new Error(result.error);
  if (!result.backtest) throw new Error('Backtest returned no data');

  const adapter = AdapterRegistry.getAdapter(
    'backtest',
    [portfolio.id ?? 'default'],
    (cache) => new BacktestAdapter(cache, portfolio.id ?? undefined),
    unifiedAdapterCache
  );

  return adapter.transform(result.backtest) as SDKSourceOutputMap['backtest'];
},
```

### 4b. New `stress-test` resolver

```typescript
'stress-test': async (params, context) => {
  const { manager, unifiedAdapterCache } = context.services;
  const portfolio = requirePortfolio('stress-test', getPortfolio(params?.portfolioId, context.currentPortfolio));

  const result = await manager.analyzeStressTest({
    scenario: params?.scenario ?? '',
  });

  if (result.error) throw new Error(result.error);
  if (!result.stressTest) throw new Error('Stress test returned no data');

  const adapter = AdapterRegistry.getAdapter(
    'stressTest',
    [portfolio.id ?? 'default'],
    (cache) => new StressTestAdapter(cache, portfolio.id ?? undefined),
    unifiedAdapterCache
  );

  return adapter.transform(result.stressTest) as SDKSourceOutputMap['stress-test'];
},
```

### 4c. New `monte-carlo` resolver

```typescript
'monte-carlo': async (params, context) => {
  const { manager } = context.services;
  requirePortfolio('monte-carlo', getPortfolio(params?.portfolioId, context.currentPortfolio));

  const result = await manager.analyzeMonteCarlo({
    numSimulations: params?.numSimulations,
    timeHorizonMonths: params?.timeHorizonMonths,
  });

  if (result.error) throw new Error(result.error);
  if (!result.monteCarlo) throw new Error('Monte Carlo simulation returned no data');

  return result.monteCarlo as SDKSourceOutputMap['monte-carlo'];
},
```

### 4d. New `hedging-recommendations` resolver

```typescript
'hedging-recommendations': async (params, context) => {
  const { api } = context.services;

  const weights = params?.weights;
  if (!weights || Object.keys(weights).length === 0) {
    return { strategies: [] };
  }

  const response = params?.portfolioValue !== undefined
    ? await api.getHedgingRecommendations(weights, params.portfolioValue)
    : await api.getHedgingRecommendations(weights);

  const strategies = HedgingAdapter.transform(response);

  return { strategies } as SDKSourceOutputMap['hedging-recommendations'];
},
```

Import additions at top of registry.ts:
```typescript
import { BacktestAdapter } from '../adapters/BacktestAdapter';
import { StressTestAdapter } from '../adapters/StressTestAdapter';
import { HedgingAdapter } from '../adapters/HedgingAdapter';
```

## Step 5 — Rewrite 4 Hooks as Thin Wrappers

### useHedgingRecommendations (105 → ~45 lines)

Keeps `sanitizeWeights()` and `portfolioValue` normalization in the wrapper. Includes `portfolioId` for portfolio-scoped query key.

```typescript
const currentPortfolio = useCurrentPortfolio();
const sanitizedWeights = useMemo(() => sanitizeWeights(weights), [weights]);
const normalizedPortfolioValue = useMemo(
  () => (typeof portfolioValue === 'number' && Number.isFinite(portfolioValue) && portfolioValue > 0
    ? portfolioValue : undefined),
  [portfolioValue]
);

const resolved = useDataSource(
  'hedging-recommendations',
  sanitizedWeights
    ? { portfolioId: currentPortfolio?.id, weights: sanitizedWeights, portfolioValue: normalizedPortfolioValue }
    : undefined,
  { enabled: !!sanitizedWeights }
);
```

Full return shape (matches current `useHedgingRecommendations.ts:87-103` and test assertions):
- `data: resolved.data?.strategies ?? undefined` (coerce null→undefined)
- `loading: resolved.loading`
- `isLoading: resolved.loading`
- `isRefetching: resolved.isRefetching`
- `error: resolved.error?.message ?? null`
- `refetch: resolved.refetch` (hedging is auto-fetch, not manual — refetch is always safe)
- `hasData: Array.isArray(resolved.data?.strategies) && resolved.data.strategies.length > 0` (matches current `hasStrategies` check at line 85 — NOT `!!resolved.data`)
- `hasError: !!resolved.error`
- `hasPortfolio: !!currentPortfolio`
- `currentPortfolio`
- `clearError: () => {}` (errors clear on successful refetch, same as current)

### useBacktest (128 → ~60 lines)

Keeps `normalizeWeights()` in wrapper. Uses `_runId` for cache-busting. Preserves validation error when all weights normalize away (current hook throws, existing test expects it).

**Contract preservation notes:**
- `backtestId` initial value is `null` (matching current `useBacktest.ts:28` and test at `useBacktest.test.tsx:54`). After first run: `${period}_${runId}` (e.g., `1Y_1709913600000`).
- Initial `data` is `undefined` (NOT `null`): `resolved.data ?? undefined` coercion in return, since current hook returns `undefined` before first run and existing tests assert `data === undefined`.
- On validation error (empty weights), `params` is reset to `null` which disables the query and clears stale data. **BC-7**: current hook sets state before validation; new validates first. See "Intentional Behavioral Changes".
- `enabled` gates on `!!resolverParams` (params only set after `runBacktest()` passes validation).
- `runBacktest()` bails when no portfolio — does NOT set params, preventing deferred execution. **Behavioral change BC-1**: current hooks set state and call `refetch()` even without a portfolio. See "Intentional Behavioral Changes" section.
- **Render-time portfolio guard**: `resolverParams` checks `runPortfolioId === currentPortfolio?.id`. When the user switches portfolios, the mismatch immediately returns `undefined` → `enabled: false`, preventing TanStack from fetching against the new portfolio before any `useEffect` runs. The `useEffect` then cleans up stale state.
- **Guarded refetch**: Wrapper exposes a guarded `refetch` that only calls `resolved.refetch()` when `resolverParams` is set. Before first run or after `setParams(null)`, calling `refetch()` is a no-op — prevents hitting the resolver with missing params.

```typescript
const currentPortfolio = useCurrentPortfolio();
const [params, setParams] = useState<BacktestParams | null>(null);
const [runId, setRunId] = useState<number | null>(null);
const [runPortfolioId, setRunPortfolioId] = useState<string | undefined>(undefined);
const [validationError, setValidationError] = useState<string | null>(null);

const portfolioId = currentPortfolio?.id;

// Render-time guard: if portfolio changed since run, disable query immediately
// useEffect cleanup follows for state reset
const resolverParams = useMemo(() => {
  if (!params || !runPortfolioId || runPortfolioId !== portfolioId) return undefined;
  return {
    ...params,
    portfolioId,
    _runId: runId ?? undefined,
  };
}, [params, runId, portfolioId, runPortfolioId]);

// Post-render cleanup: reset stale state after portfolio switch
useEffect(() => {
  setParams(null);
  setRunId(null);
  setRunPortfolioId(undefined);
  setValidationError(null);
}, [portfolioId]);

const backtestId = useMemo(() => {
  if (!runId || !params) return null;  // null before first run (matches current hook)
  const period = params.period ?? 'CUSTOM';
  return `${period}_${runId}`;
}, [runId, params]);

const resolved = useDataSource('backtest', resolverParams, {
  enabled: !!resolverParams,
});

// Guarded refetch — no-op before first run or after params cleared
const guardedRefetch = useCallback(() => {
  if (resolverParams) resolved.refetch();
}, [resolverParams, resolved.refetch]);

const runBacktest = useCallback((nextParams: BacktestParams) => {
  if (!currentPortfolio) return;  // Bail — no deferred execution (intentional improvement)
  const normalizedWeights = normalizeWeights(nextParams.weights);
  if (Object.keys(normalizedWeights).length === 0) {
    setValidationError('Backtest requires at least one ticker weight');
    setParams(null);  // Clear params → disables query → clears stale data
    return;
  }
  setValidationError(null);
  setRunPortfolioId(currentPortfolio.id);  // Lock to current portfolio
  setParams({ ...nextParams, weights: normalizedWeights });
  setRunId(Date.now());
}, [currentPortfolio]);
```

Returns: `data: resolved.data ?? undefined` (coerce null→undefined for contract compat), `loading`, `isLoading`, `isRefetching`, `error` (from `validationError ?? resolved.error?.message ?? null`), `refetch: guardedRefetch` (no-op before first run), `refreshBacktest: guardedRefetch`, `hasData`, `hasError` (includes validationError), `hasPortfolio: !!currentPortfolio`, `currentPortfolio`, `runBacktest` (bails if no portfolio), `backtestId` (null before first run, then `${period}_${runId}`), `clearError` (clears validationError).

### useStressTest (100 → ~45 lines)

Same pattern as useBacktest: render-time portfolio guard + `useEffect` cleanup + guarded refetch.

```typescript
const currentPortfolio = useCurrentPortfolio();
const [scenarioId, setScenarioId] = useState<string | null>(null);
const [runId, setRunId] = useState<number | null>(null);
const [runPortfolioId, setRunPortfolioId] = useState<string | undefined>(undefined);

const portfolioId = currentPortfolio?.id;

const resolverParams = useMemo(() => {
  if (!scenarioId || !runPortfolioId || runPortfolioId !== portfolioId) return undefined;
  return { portfolioId, scenario: scenarioId, _runId: runId ?? undefined };
}, [scenarioId, runId, portfolioId, runPortfolioId]);

useEffect(() => {
  setScenarioId(null);
  setRunId(null);
  setRunPortfolioId(undefined);
}, [portfolioId]);

const stressTestRunId = useMemo(() => {
  if (!runId || !scenarioId) return null;
  return `${scenarioId}_${runId}`;
}, [scenarioId, runId]);

const resolved = useDataSource('stress-test', resolverParams, {
  enabled: !!resolverParams,
});

const guardedRefetch = useCallback(() => {
  if (resolverParams) resolved.refetch();
}, [resolverParams, resolved.refetch]);

const runStressTest = useCallback((nextScenarioId: string) => {
  if (!currentPortfolio) return;
  setRunPortfolioId(currentPortfolio.id);
  setScenarioId(nextScenarioId);
  setRunId(Date.now());
}, [currentPortfolio]);
```

Returns: `data: resolved.data ?? undefined`, `loading`, `isLoading`, `isRefetching`, `error`, `refetch: guardedRefetch`, `hasData`, `hasError`, `hasPortfolio: !!currentPortfolio`, `currentPortfolio`, `runStressTest`, `stressTestRunId` (null before first run, then `${scenarioId}_${runId}`).

NOTE: `useStressScenarios` companion hook stays as-is (simple `useQuery` for scenario list).

### useMonteCarlo (62 → ~40 lines)

Same pattern as useBacktest: render-time portfolio guard + `useEffect` cleanup.

```typescript
const currentPortfolio = useCurrentPortfolio();
const [params, setParams] = useState<MonteCarloParams | null>(null);
const [runId, setRunId] = useState<number | null>(null);
const [runPortfolioId, setRunPortfolioId] = useState<string | undefined>(undefined);

const portfolioId = currentPortfolio?.id;

const resolverParams = useMemo(() => {
  if (!params || !runPortfolioId || runPortfolioId !== portfolioId) return undefined;
  return { ...params, portfolioId, _runId: runId ?? undefined };
}, [params, runId, portfolioId, runPortfolioId]);

useEffect(() => {
  setParams(null);
  setRunId(null);
  setRunPortfolioId(undefined);
}, [portfolioId]);

const resolved = useDataSource('monte-carlo', resolverParams, {
  enabled: !!resolverParams,
});

const runMonteCarlo = useCallback((nextParams: MonteCarloParams = {}) => {
  if (!currentPortfolio) return;
  setRunPortfolioId(currentPortfolio.id);
  setParams(nextParams);
  setRunId(Date.now());
}, [currentPortfolio]);
```

Returns: `result: resolved.data ?? undefined`, `isRunning: resolved.loading || resolved.isRefetching` (matches current `useMonteCarlo.ts:55` — reports running during both initial load and refetch), `runMonteCarlo` (bails if no portfolio), `error: resolved.error?.message ?? null`.

## Step 6 — Export New Types from Catalog Index

File: `frontend/packages/chassis/src/catalog/index.ts`

Export: `BacktestSourceData`, `StressTestSourceData`, `HedgingRecommendationsSourceData`, `MonteCarloSourceData`.

## Verification

1. `pnpm typecheck` — zero TS errors
2. **Run catalog tests** — `pnpm test -- descriptors.test` — update descriptor count assertion (currently 18 in test, live list is 25 after Batch A → update to 29 with Batch B)
3. **Add `enabled` option test** — `pnpm test -- useDataSource.test` — add test that `enabled: false` prevents query execution
4. **Run existing hook tests** — update and verify all 4 test suites pass:
   - `pnpm test -- useBacktest.test` — verify: initial data=undefined, backtestId=null, error on empty weights, data after run, weight normalization (uppercase + finite filter), `refreshBacktest` re-run, portfolio-switch reset. Update tests for BC-1 (no-portfolio no-op) and BC-3 (guarded refetch).
   - `pnpm test -- useStressTest.test` — verify: initial data=undefined, stressTestRunId=null, data after run, error propagation, portfolio-switch reset.
   - `pnpm test -- useMonteCarlo.test` — verify: initial result=undefined, data after run, API error path, no-data error path (exact message: "Monte Carlo simulation returned no data"), portfolio-switch reset.
   - `pnpm test -- useHedgingRecommendations.test` — verify: data rendering, undefined/empty weight sanitization, error handling, `hasData` (non-empty strategies array), refetch (`await` still works with void return per BC-6). Add: weight-change-driven refetch test (BC-5).
5. **Add test coverage** for new behaviors:
   - Portfolio switch: render-time guard disables query immediately (no stale auto-run against new portfolio)
   - `runXxx()` no-ops when no portfolio (params stay null)
   - `refetch()` is no-op before first run (guarded)
   - `refetch()` is no-op after `setParams(null)` (validation error path)
   - **`_runId` re-run test**: call `runBacktest()` twice with identical params, verify second call triggers a fresh resolver/manager call (different `_runId` → different query key → new fetch). This is the core regression `_runId` prevents.
6. Chrome verify:
   - Scenario Analysis → run stress test (trigger, verify data renders) (`ScenarioAnalysisContainer.tsx`)
   - **Strategy Builder** → run backtest (trigger, verify results table) (`StrategyBuilderContainer.tsx:165`)
   - Scenario Analysis → run Monte Carlo (trigger, verify simulation output) (`ScenarioAnalysisContainer.tsx`)
   - Hedging tab → verify recommendations render with weights passed
   - **Switch portfolio while Scenario Analysis is open** → verify results clear, then **switch back** → verify clean state (no stale results from previous portfolio, `runXxx()` required to re-trigger). This tests BC-12 render-time guard, not just portfolio-scoped key isolation (which already clears results).
7. Verify existing `positions` resolver consumers still work (trading-analysis, etc.) — NOT changed in this batch

## Intentional Behavioral Changes

These are explicit deviations from current hook behavior. Each is an intentional improvement or acceptable trade-off. Tests must be updated to match.

### BC-1: `runXxx()` no-ops when no portfolio (improvement)

**Current**: `runBacktest()`/`runStressTest()`/`runMonteCarlo()` set local state (params, runId) and call `refetch()` even without a portfolio. The queryFn then short-circuits to `null` (e.g., `useBacktest.ts:48-52`).

**New**: `runXxx()` returns immediately without setting state when `!currentPortfolio`. No queryFn execution, no state change.

**Rationale**: Avoids unnecessary state changes and a wasted queryFn call that always returns null. Observable difference: `backtestId`/`stressTestRunId` won't update on a no-portfolio trigger. No known caller depends on this.

**Test update**: No existing tests assert state changes on no-portfolio `runXxx()` calls — they only check `hasPortfolio=false`. No test changes needed for this BC.

### BC-2: Reconnect-driven refetch after 60+ minutes (trade-off)

**Current**: Permanently `enabled: false` — queries NEVER auto-refetch. Not on reconnect, not on mount, never.

**New**: After a run, query stays enabled with `staleTime: 3600s`. After 60+ minutes, if the component is still mounted and network reconnects, `refetchOnReconnect: true` (global default at `QueryProvider.tsx:216`) triggers a refetch. This hits the backend (PortfolioCacheService TTL is 5 min per `cacheConfig.ts:89`).

**Rationale**: Extremely rare scenario (component mounted 60+ min on Scenario Analysis). If it happens, the user gets refreshed data. If exact parity is needed in the future, add per-source `refetchOnReconnect` override to `useDataSource`.

**Test update**: No existing test covers this — add a note in test comments.

### BC-3: Guarded refetch replaces raw TanStack refetch (improvement)

**Current**: `refetch`/`refreshBacktest` expose raw TanStack `refetch()` which returns `Promise<QueryObserverResult>` and bypasses `enabled: false` to execute the queryFn.

**New**: Manual-trigger hooks expose `guardedRefetch: () => void` — no-op when `resolverParams` is undefined (before first run, after params cleared). Returns void, not a Promise.

**Rationale**: Prevents spurious refetch calls from hitting resolvers with missing params. `await void` resolves immediately, so `await refetch()` in tests still works. The raw TanStack `refetch()` behavior of bypassing `enabled: false` is unnecessary in the new architecture since `enabled` is data-driven.

**Test update**: Tests that `await refetch()` still work. No tests depend on the return value.

### BC-4: Hedging retry — per-error suppression lost (trade-off)

**Current**: Custom retry function does `error.message.toLowerCase().includes('validation')` and `.includes('contract')` substring checks — suppresses retries for those, retries others up to 2 times (`useHedgingRecommendations.ts:75-81`).

**New**: Descriptor-level `retryable: true, maxRetries: 2`. All errors retry up to 2 times uniformly.

**Rationale**: Resolver validates inputs before API call (returns `{ strategies: [] }` for empty weights). Validation errors surface as results, not thrown errors. If a deterministic error is thrown, retries fail quickly with the same error. Negligible user impact.

**Test update**: No existing test asserts retry suppression by error type.

### BC-5: Hedging query key includes weights (trade-off)

**Current**: Query key is `[...hedgingRecommendationsKey(portfolioId), portfolioValue]` — does NOT include `weights`. When weights change (e.g., from `useRiskAnalysis` in `RiskAnalysisModernContainer`), the query does NOT refetch; the old result stays visible.

**New**: `buildDataSourceQueryKey` serializes ALL params including `weights`. When weights change, the query key changes → React Query creates a new cache entry → refetch with new weights.

**Rationale**: This is arguably correct behavior — if weights change, hedging recommendations should update. However, it means more frequent API calls when weights are derived from upstream data. Low risk: hedging descriptor has `defaultTTL: 600`, so the same weights won't re-fetch within 10 min.

**Test update**: Add test for weight-change-driven refetch. Note: BC-9 documents that a data flash WILL occur during weight transitions (no `keepPreviousData`).

### BC-6: Hedging refetch Promise→void (hook API contract change)

**Current**: `useHedgingRecommendations` exposes raw TanStack `refetch` (`useHedgingRecommendations.ts:94`) which returns `Promise<QueryObserverResult<HedgeStrategy[], Error>>`.

**New**: `resolved.refetch` from `useDataSource` is typed as `() => void` (`resolver/types.ts:17`). This is a real TypeScript API contract change — callers that type-check against the Promise return will get compilation errors.

**Impact**: The hedging test at `useHedgingRecommendations.test.tsx:146` does `await refetch()` — `await void` resolves to `undefined`, so runtime behavior is preserved. No callers use the return value of `refetch()`.

**Test update**: If tests type-check the return of `refetch()`, they need adjustment.

### BC-7: Backtest/stress local-state ordering differences (improvement)

**Current backtest**: `runBacktest()` sets `backtestId` and `params` BEFORE validation — then calls `refetch()`. The queryFn normalizes weights and THROWS `'Backtest requires at least one ticker weight'` if empty (`useBacktest.ts:59-62`).

**New backtest**: `runBacktest()` validates FIRST (normalizeWeights), only sets state if valid. `backtestId` is derived from `runId` + `params.period` AFTER successful `setParams()`. On validation failure, `setParams(null)` clears state.

**Current stress-test**: No portfolio-switch reset — `stressTestRunId` persists across portfolio changes.

**New stress-test**: `useEffect` resets `stressTestRunId` to null on portfolio change (via `runPortfolioId` mismatch at render time).

**Current backtest clearError**: No-op function (`useBacktest.ts:112`).

**New backtest clearError**: Actively clears `validationError` state.

**Rationale**: All improvements — validate before state mutation, clean up on portfolio switch, functional clearError. No known callers depend on the old ordering.

**Test update**: Update tests that assert `backtestId` is set before validation completes. Update `clearError` tests if any.

### BC-8: Error message rewriting via classifyError (all 4 hooks)

**Current**: All 4 hooks return raw `error.message` strings — `useBacktest.ts:103`, `useStressTest.ts:68`, `useMonteCarlo.ts:57`, `useHedgingRecommendations.ts:84`. Tests assert exact error messages (e.g., `useBacktest.test.tsx:110`, `useMonteCarlo.test.tsx:95`).

**New**: `useDataSource` routes errors through `classifyError()` (`chassis/errors/classifyError.ts`), which may rewrite validation/invalid messages to generic user-facing messages. All 4 wrappers return `resolved.error?.message ?? null`.

**Rationale**: Consistent error handling across all `useDataSource` consumers. Trade-off: specific error messages may be genericized by the classifier.

**Error message detail**: `DataSourceError.message` is set from `userMessage` (via `super(init.userMessage)` at `DataSourceError.ts:32`). For the "unknown" category (`classifyError.ts:141-147`), `userMessage` = the original error message — so `.message` IS preserved. Resolver-thrown errors (e.g., "Backtest requires at least one ticker weight", "Monte Carlo simulation returned no data") have no status code and no validation/invalid substring match → fall through to "unknown" → raw message preserved.

In practice, most errors reaching classifyError from these hooks are plain `Error` strings without a `status` field. The managers (`PortfolioManager.ts:529/563/597`) collapse API errors to raw strings before throwing. `APIService.ts:339` throws plain `Error("HTTP ...")` for non-429 failures (no `status` property). So classifyError falls through to "unknown" for virtually all cases. The only exceptions: (a) errors containing "validation" or "invalid" substrings get rewritten to "Received an unexpected data format from the server" (`classifyError.ts:126-138`), (b) 429 errors from APIService that preserve `status` get rewritten to "Rate limit exceeded." (`classifyError.ts:62-71`).

**Decision**: Use `resolved.error?.message ?? null` in all 4 wrappers. Most errors preserve raw strings. The validation-substring and 429 rewrites are acceptable edge cases.

**Test update**: Tests asserting resolver-thrown error messages (backtest empty-weights, Monte Carlo no-data) pass as-is — no "validation"/"invalid" substring match. API error tests: most pass since managers collapse to plain strings.

### BC-9: Hedging weight-change data flash (trade-off)

**Current**: Query key does NOT include weights. When weights change, the old cached result stays visible (same key, `enabled` toggles).

**New**: Query key includes weights (via `buildDataSourceQueryKey`). When weights change, the key changes → new cache entry starts with `data: null` → `loading: true` while fetching → data appears. The old result disappears immediately (no `keepPreviousData`/`placeholderData` in `useDataSource`).

**User impact**: Brief flash of empty hedging recommendations when weights update. Acceptable for now; if problematic, a future enhancement can add `keepPreviousData` to `useDataSource`.

**Test update**: Add test verifying loading state during weight-change transition.

### BC-10: Resolver timeout (new constraint)

**Current**: Hooks call manager/API directly with no timeout wrapper. Backtest/stress/Monte Carlo can take 30-60+ seconds.

**New**: `resolveWithCatalog()` in `core.ts:49-57` races the resolver promise with a timer (`descriptor.errors.timeout`). Default is 30s (`descriptors.ts:13`). NOTE: this only rejects the React Query promise — the underlying API request continues in `APIService`/`PortfolioCacheService` (they create their own `AbortController`). The timeout prevents UI from waiting indefinitely but doesn't cancel the backend call.

**Fix**: Override to `timeout: 120000` (2 min) in backtest/stress-test/monte-carlo descriptors. Hedging keeps default 30s (fast API call).

### BC-11: Monte Carlo _runId changes rerun UX (trade-off)

**Current**: Query key is `monteCarloKey(portfolioId)` only — no run ID. All `runMonteCarlo()` calls share one cache entry. On rerun, TanStack refetches in-place: old result stays visible (`data` remains non-null) while `isRefetching` is true. `MonteCarloTab.tsx:123/146` renders results off `monteCarloResult` truthiness — so the prior chart stays visible during rerun.

**New**: `_runId: Date.now()` → unique query key per run → new cache entry starts with `data: null`. Prior result disappears during rerun. `MonteCarloTab` shows loading/empty state until new results arrive.

**Rationale**: Consistent with backtest/stress-test pattern. Trade-off: brief blank during rerun. `isRunning` indicator communicates progress. If the blank is unacceptable, a future enhancement can add `keepPreviousData` support to `useDataSource`.

**Test update**: Add test verifying `result` is undefined/null during second run (differs from current where prior result persists).

### BC-12: Portfolio-switch render-time guard (improvement)

**Current**: After a portfolio switch, backtest/stress/MC hooks retain their stored inputs (`params`, `backtestId`, `stressTestRunId`). A manual `refetch()` would run the old analysis against the new portfolio.

**New**: `runPortfolioId` state tracks which portfolio was active when `runXxx()` was called. On render, if `runPortfolioId !== currentPortfolio?.id`, `resolverParams` returns `undefined` → query disabled. `useEffect` then clears stale state.

**Rationale**: Prevents cross-portfolio data contamination. Running a backtest configured for portfolio A against portfolio B would produce misleading results.

**Test update**: Add test for portfolio-switch clearing results.

## Risk Assessment

- **Manual-trigger re-run**: LOW — `_runId` ensures unique query keys. `defaultTTL: 3600` matches current staleTime.
- **Portfolio scoping**: LOW — `portfolioId` in params + render-time `runPortfolioId` guard.
- **Validation errors**: LOW — preserved via `validationError` state in useBacktest.
- **Type compatibility**: LOW — structural types match adapter outputs.
- **Normalization**: LOW — `normalizeWeights()`, `sanitizeWeights()`, portfolioValue validation kept in wrappers.
- **`useStressScenarios` companion**: NONE — stays as-is.
- **Positions resolver**: NOT TOUCHED — deferred.

## Files Changed (Expected: ~10)

1. `connectors/src/resolver/useDataSource.ts` — add `enabled` option
2. `chassis/src/catalog/types.ts` — 4 new DataSourceIds + types
3. `chassis/src/catalog/descriptors.ts` — 4 new descriptors
4. `chassis/src/catalog/index.ts` — new exports
5. `connectors/src/resolver/registry.ts` — 4 new resolvers (no positions change)
6-9. 4 hook files rewritten

# Hook Migration Batch C — Stock, Optimization, Realized Performance, Portfolio Summary
**Status:** DONE

## Scope

Migrate 4 hooks to `useDataSource`: 2 reuse existing resolvers + DataSourceIds (`stock-analysis`, `optimization`), 2 require new infrastructure (`realized-performance`, `portfolio-summary`).

| Hook | Lines | Pattern | New Infrastructure |
|------|-------|---------|-------------------|
| useStockAnalysis | 280 | Ticker-gated auto-fetch | Reuses existing `stock-analysis` resolver + descriptor |
| usePortfolioOptimization | 294 | Strategy-gated auto-fetch | Reuses existing `optimization` resolver + descriptor |
| useRealizedPerformance | 24 | Manual trigger (`useMutation`) | New DataSourceId + descriptor + resolver |
| usePortfolioSummary | 398 | Multi-query aggregation | New DataSourceId + descriptor + resolver |

Total: ~996 lines -> ~250 lines.

### Key Insight: Existing Resolvers

`stock-analysis` and `optimization` already have resolvers in `registry.ts`, descriptors in `descriptors.ts`, DataSourceIds in `types.ts`, and output/param types in the catalog. The hooks currently bypass these — they call `stockManager`/`manager` directly with their own `useQuery`. Migration means routing through `useDataSource` with the existing resolver, which changes the transformation pipeline (adapter vs. resolver output shape — see BC-1, BC-2).

## Step 1 — Add 2 New DataSourceIds + Output/Param Types

File: `frontend/packages/chassis/src/catalog/types.ts`

### 1a. Add to `DataSourceId` union (line ~48):

```typescript
| 'realized-performance'
| 'portfolio-summary'
```

### 1b. Add output types (after `AllocationSourceData`, line ~341):

**Design constraint**: `@risk/chassis` cannot import from `@risk/connectors` (connectors depends on chassis, not the reverse). The `RealizedPerformanceTransformed` type lives in connectors' `RealizedPerformanceAdapter.ts`. We must define the catalog output type inline in `types.ts`.

**Strategy**: Define `RealizedPerformanceSourceData` in `types.ts` as a structural match for `RealizedPerformanceTransformed`. The hook wrapper casts `resolved.data as RealizedPerformanceTransformed` (from the adapter module). The resolver returns `RealizedPerformanceTransformed` which satisfies the `RealizedPerformanceSourceData` structure via TypeScript structural typing.

```typescript
// Structural match for RealizedPerformanceTransformed from connectors/adapters/RealizedPerformanceAdapter.
// Cannot import directly — chassis must not depend on connectors.
// The hook wrapper casts resolved.data to the adapter's concrete type.
export interface RealizedPerformanceSourceData {
  performanceData: {
    success?: boolean;
    formatted_report?: string;
    summary?: Record<string, unknown>;
    portfolio_metadata?: Record<string, unknown>;
    benchmark_name?: string;
    data_availability?: {
      has_formatted_report: boolean;
      has_summary: boolean;
      has_portfolio_metadata: boolean;
      data_quality: 'complete' | 'partial' | 'minimal';
    };
    period: { start: string; end: string; totalMonths: number; years: number };
    returns: { totalReturn: number; annualizedReturn: number; bestMonth: number; worstMonth: number; winRate: number };
    risk: { volatility: number; maxDrawdown: number; downsideDeviation: number; trackingError: number };
    performanceTimeSeries: Array<Record<string, unknown>>;
    timeline?: Array<Record<string, unknown>>;
    performanceSummary?: {
      periods?: Record<string, { portfolioReturn: number; benchmarkReturn: number | null; activeReturn: number; volatility: number }>;
      riskMetrics?: Record<string, unknown>;
      attribution?: Record<string, unknown>;
    };
    benchmark?: Record<string, string>;
    monthly?: Record<string, unknown>;
  };
  realizedDetails: {
    pnl: {
      navPnlUsd: number | null;
      navPnlObservedOnlyUsd: number | null;
      navPnlSyntheticImpactUsd: number | null;
      lotPnlUsd: number;
      realizedPnl: number;
      unrealizedPnl: number;
      reconciliationGapUsd: number | null;
      externalNetFlowsUsd: number;
    };
    income: {
      total: number; dividends: number; interest: number;
      currentMonthlyRate: number; projectedAnnual: number;
      yieldOnCost: number; yieldOnValue: number;
      byInstitution: Record<string, unknown>;
      byMonth: Record<string, unknown>;
    };
    dataQuality: {
      coverage: number; reliable: boolean; highConfidence: boolean;
      navMetricsEstimated: boolean; warnings: string[];
      reliabilityReasons: string[]; reliabilityReasonCodes: string[];
      syntheticCurrentPositionCount: number; syntheticCurrentMarketValue: number;
      unpriceableSymbolCount: number; fetchErrors: Record<string, string>;
    };
  };
  rawResponse: unknown;
}

// Matches PortfolioSummaryData from PortfolioSummaryAdapter
export interface PortfolioSummarySourceData {
  success?: boolean;
  portfolio_name?: string;
  portfolio_data?: Record<string, unknown> | Array<Record<string, unknown>>;
  portfolio_metadata?: Record<string, unknown>;
  summary: {
    totalValue: number;
    riskScore: number | null;
    volatilityAnnual: number | null;
    dayChange: number;
    dayChangePercent: number;
    ytdReturn: number;
    sharpeRatio: number;
    maxDrawdown: number;
    alphaAnnual: number;
    concentrationScore: number;
    lastUpdated: string;
  };
  holdings: Array<{
    ticker: string;
    name: string;
    value: number;
    shares: number;
    isProxy: boolean;
    weight: number;
    factorBetas: Record<string, number>;
    riskContributionPct: number;
    beta: number | null;
    volatility: number | null;
    aiScore: number | null;
    alerts: number;
    trend: number[];
  }>;
}
```

### 1c. Add to `SDKSourceOutputMap` (line ~372):

```typescript
'realized-performance': RealizedPerformanceSourceData;
'portfolio-summary': PortfolioSummarySourceData;
```

No cross-package import needed — `RealizedPerformanceSourceData` is defined inline in `types.ts` (Step 1b). The resolver in connectors returns `RealizedPerformanceTransformed` which satisfies `RealizedPerformanceSourceData` via structural typing. The hook wrapper casts `resolved.data as RealizedPerformanceTransformed` for consumer type safety.

### 1d. Add to `SDKSourceParamsMap` (line ~425):

```typescript
'realized-performance': {
  benchmarkTicker?: string;
  source?: 'all' | 'snaptrade' | 'plaid' | 'ibkr_flex' | 'schwab';
  institution?: string;
  account?: string;
  startDate?: string;
  endDate?: string;
  includeSeries?: boolean;
  _runId?: number;  // Force unique query key for re-runs with same params
};
'portfolio-summary': {
  portfolioId?: string;
};
```

### 1e. Existing types — UPDATED in Step 3

`stock-analysis` and `optimization` already have DataSourceIds, output types, param types, and descriptors. However, their output types (`StockAnalysisSourceData`, `OptimizationSourceData`) must be updated in Step 3 to match adapter output shapes. See Steps 3a and 3b for the updated type definitions.

**Critical shape mismatch (stock-analysis)**: The existing `stock-analysis` resolver returns `StockAnalysisSourceData` (`{ ticker, summary?, fundamentals?, technicals?, ...payload }`). The current `useStockAnalysis` hook returns `StockRiskDisplayData` from `StockAnalysisAdapter.transform()` (`{ ticker, volatility_metrics, regression_metrics, factor_summary, analysis_date, ... }`). These are completely different shapes. See BC-1.

**Critical shape mismatch (optimization)**: The existing `optimization` resolver returns `OptimizationSourceData` (`{ strategy, allocations, expected_return?, volatility?, sharpe_ratio?, ...data }`). The current `usePortfolioOptimization` hook returns `OptimizationData` from `PortfolioOptimizationAdapter.transform()` (`{ strategy, weights, summary, portfolio_metadata, ... }`). These are completely different shapes. See BC-2.

**Resolution**: Both hooks must use their adapters to maintain the consumer contract. The resolvers must be updated to route through adapters (Step 3).

## Step 2 — Add 2 New Catalog Descriptors

File: `frontend/packages/chassis/src/catalog/descriptors.ts`

### 2a. `realized-performance` descriptor (after `allocationDescriptor`, line ~1009):

```typescript
const realizedPerformanceDescriptor = defineDescriptor({
  id: 'realized-performance',
  label: 'Realized Performance',
  category: 'portfolio',
  params: [
    {
      name: 'benchmarkTicker',
      type: 'string',
      required: false,
      description: 'Benchmark ticker for performance comparison.',
    },
    {
      name: 'source',
      type: 'string',
      required: false,
      description: 'Data source filter (all, snaptrade, plaid, ibkr_flex, schwab).',
      defaultValue: 'all',
    },
    {
      name: 'institution',
      type: 'string',
      required: false,
      description: 'Filter by institution name.',
    },
    {
      name: 'account',
      type: 'string',
      required: false,
      description: 'Filter by account identifier.',
    },
    {
      name: 'startDate',
      type: 'string',
      required: false,
      description: 'Analysis start date.',
    },
    {
      name: 'endDate',
      type: 'string',
      required: false,
      description: 'Analysis end date.',
    },
    {
      name: 'includeSeries',
      type: 'boolean',
      required: false,
      description: 'Whether to include monthly series in the response.',
    },
  ],
  fields: [
    { name: 'performanceData', type: 'object', description: 'Transformed performance metrics and time series.' },
    { name: 'realizedDetails', type: 'object', description: 'PnL, income, and data quality details.' },
    { name: 'rawResponse', type: 'object', description: 'Unmodified API response payload.' },
  ],
  flagTypes: [{ name: 'realized_data_quality', description: 'Realized performance data may have limited coverage.', severity: 'warning' }],
  refresh: {
    defaultTTL: 300,
    staleWhileRevalidate: false,
    invalidatedBy: [],
  },
  loading: {
    strategy: 'lazy',
    dependsOn: [],
  },
  errors: {
    retryable: true,
    maxRetries: 2,
    timeout: 120000,
    fallbackToStale: false,
  },
});
```

**Rationale for `defaultTTL: 300`**: Realized performance is transaction-based and rarely changes within a session. 5 minutes matches the performance descriptor. `timeout: 120000` because the backend analysis can take 30-60+ seconds. `dependsOn: []` because this is a manual-trigger hook. `invalidatedBy: []` because `_runId` handles re-runs.

### 2b. `portfolio-summary` descriptor:

```typescript
const portfolioSummaryDescriptor = defineDescriptor({
  id: 'portfolio-summary',
  label: 'Portfolio Summary',
  category: 'portfolio',
  params: [
    {
      name: 'portfolioId',
      type: 'string',
      required: false,
      description: 'Portfolio identifier override. Defaults to the active portfolio.',
    },
  ],
  fields: [
    { name: 'summary', type: 'object', description: 'Aggregated portfolio summary metrics.' },
    { name: 'holdings', type: 'array', description: 'Simplified holdings for overview display.' },
  ],
  flagTypes: [{ name: 'portfolio_summary_warning', description: 'Portfolio summary computed from partial data.', severity: 'warning' }],
  refresh: {
    defaultTTL: 300,
    staleWhileRevalidate: true,
    invalidatedBy: ['risk-data-invalidated', 'performance-data-invalidated', 'portfolio-data-invalidated', 'all-data-invalidated'],
  },
  loading: {
    strategy: 'eager',
    dependsOn: [],
    priority: 6,
  },
  errors: DEFAULT_ERRORS,
});
```

**Rationale for `dependsOn: []`**: The resolver internally calls `risk-score`, `risk-analysis`, and `performance` resolvers via `Promise.all`. Adding these as `dependsOn` would create a serial dependency chain (wait for each to appear in cache, then run). The parallel internal calls are faster. `invalidatedBy` includes all relevant events because the summary aggregates data from risk, performance, and portfolio sources. `strategy: 'eager'` and `priority: 6` because the SummaryBar renders immediately on portfolio overview.

### 2c. Wiring checklist (all 4 structures):

1. `descriptorList` array (line ~1041): append `realizedPerformanceDescriptor`, `portfolioSummaryDescriptor`
2. `sdkDescriptorMap` object (line ~1073): add `'realized-performance': realizedPerformanceDescriptor`, `'portfolio-summary': portfolioSummaryDescriptor`
3. `ensureFieldConformance()` object (line ~1138): add `'realized-performance': true`, `'portfolio-summary': true`
4. Update descriptor count in `descriptors.test.ts:6-8`: 29 -> 31

## Step 3 — Update/Add Resolvers

File: `frontend/packages/connectors/src/resolver/registry.ts`

### 3a. Update `stock-analysis` resolver to use adapter

The existing `stock-analysis` resolver (line 563-588) returns raw `StockAnalysisSourceData` — it does NOT go through `StockAnalysisAdapter.transform()`. The current `useStockAnalysis` hook DOES use the adapter. To preserve the consumer contract, the resolver must be updated.

**Problem**: Changing the `stock-analysis` resolver output shape would break the existing `option-strategy` resolver (line 590-623) which depends on `stock.summary` from `StockAnalysisSourceData`. It would also change the `SDKSourceOutputMap['stock-analysis']` type contract.

**Solution**: Do NOT change the `stock-analysis` resolver. Instead, the `useStockAnalysis` wrapper will call `useDataSource('stock-analysis', ...)` but apply `StockAnalysisAdapter.transform()` on top of the resolver output in the wrapper. This is documented in BC-1.

**Actually, better approach**: The `useStockAnalysis` wrapper should NOT use `useDataSource('stock-analysis')` at all, because the existing resolver returns a fundamentally different shape and changing it has downstream effects. Instead, we create a **new** `stock-analysis-detailed` DataSourceId whose resolver goes through the adapter. But this adds unnecessary complexity.

**Final approach (simplest, matching Batch B pattern)**: The `useStockAnalysis` wrapper calls `useDataSource('stock-analysis', ...)` and transforms the result inside `useMemo`. The `stock-analysis` resolver's output flows to the wrapper, which applies `StockAnalysisAdapter.transform()` on the raw `stockAnalysis` response (not on the resolver's output, but from re-calling the manager). This is circular.

**Actual final approach**: Update the `stock-analysis` resolver to call `StockAnalysisAdapter.transform()` and return `StockRiskDisplayData`. This means changing `StockAnalysisSourceData` in `types.ts` OR having the resolver return a superset. The `option-strategy` resolver only uses `stock.summary` — and `StockRiskDisplayData` includes `summary` (from the Pydantic model passthrough). So changing the resolver IS safe.

Let me trace it precisely:
- Current `stock-analysis` resolver returns: `{ ticker, summary?, fundamentals?, technicals?, ...payload }` where `payload = response.stockAnalysis as Record<string, unknown>`
- `StockAnalysisAdapter.transform()` returns: `StockRiskDisplayData` which includes `{ ticker, volatility_metrics, regression_metrics, factor_summary, risk_metrics, analysis_date, success, summary, endpoint, ...data }`
- `option-strategy` resolver uses `stock.summary` — this field exists in both shapes

**Decision**: Update the `stock-analysis` resolver to route through `StockAnalysisAdapter`. Update `StockAnalysisSourceData` to be `StockRiskDisplayData` (which is a superset). This maintains the `option-strategy` dependency on `stock.summary`.

Replace the `stock-analysis` resolver (lines 563-588):

```typescript
'stock-analysis': async (params, context) => {
  const ticker = params?.ticker?.trim();
  if (!ticker) {
    throw new DataSourceError({
      category: 'validation',
      sourceId: 'stock-analysis',
      retryable: false,
      userMessage: 'Ticker is required for stock-analysis.',
    });
  }

  const { stockManager, unifiedAdapterCache } = context.services;
  const response = await stockManager.analyzeStock(ticker.toUpperCase(), params?.analysisType ?? 'comprehensive');
  if (response.error || !response.stockAnalysis) {
    // Throw DataSourceError directly to bypass classifyError rewriting.
    // Without this, errors containing "invalid" (e.g., "Invalid ticker") would be
    // rewritten to "Received an unexpected data format from the server." (BC-14 fix).
    throw new DataSourceError({
      category: 'unknown',
      sourceId: 'stock-analysis',
      retryable: false,
      userMessage: response.error ?? 'Stock analysis returned no data',
    });
  }

  const adapter = AdapterRegistry.getAdapter(
    'stockAnalysis',
    [ticker.toUpperCase()],
    (cache) => new StockAnalysisAdapter(cache, ticker.toUpperCase()),
    unifiedAdapterCache
  );

  return adapter.transform(
    response.stockAnalysis as Parameters<typeof adapter.transform>[0]
  ) as SDKSourceOutputMap['stock-analysis'];
},
```

Import addition at top of registry.ts:
```typescript
import { StockAnalysisAdapter } from '../adapters/StockAnalysisAdapter';
```

Update `StockAnalysisSourceData` in `types.ts` to match `StockRiskDisplayData`:

```typescript
export interface StockAnalysisSourceData {
  [key: string]: unknown;
  ticker: string;
  success?: boolean;
  summary?: Record<string, unknown>;
  endpoint?: string;
  volatility_metrics: {
    monthly_vol: number;
    annual_vol: number;
    sharpe_ratio?: number;
    sortino_ratio?: number;
    max_drawdown?: number;
  };
  regression_metrics: {
    beta: number;
    alpha: number;
    r_squared: number;
    idio_vol_m: number;
  };
  factor_summary?: {
    beta?: Record<string, number>;
    r_squared?: Record<string, number>;
    idio_vol_m?: Record<string, number>;
  };
  risk_metrics?: Record<string, unknown>;
  analysis_date: string;
}
```

Update the `stock-analysis` descriptor fields (in `stockAnalysisDescriptor`):
```typescript
fields: [
  { name: 'ticker', type: 'string', description: 'Ticker symbol analyzed.' },
  { name: 'volatility_metrics', type: 'object', description: 'Monthly and annual volatility metrics.' },
  { name: 'regression_metrics', type: 'object', description: 'Beta, alpha, R-squared metrics.' },
  { name: 'analysis_date', type: 'date', description: 'Date of the analysis.' },
],
```

### 3b. Update `optimization` resolver to use adapter

Same issue: the existing `optimization` resolver returns `OptimizationSourceData` (`{ strategy, allocations, ... }`), but the hook returns `OptimizationData` from `PortfolioOptimizationAdapter.transform()` (`{ strategy, weights, summary, portfolio_metadata, ... }`).

**Decision**: Update the resolver to route through `PortfolioOptimizationAdapter`. Update `OptimizationSourceData` to match `OptimizationData`.

Replace the `optimization` resolver (lines 353-379):

```typescript
optimization: async (params, context) => {
  const portfolio = requirePortfolio('optimization', getPortfolio(params?.portfolioId, context.currentPortfolio));
  const { manager, unifiedAdapterCache } = context.services;
  const strategy = params?.strategy ?? 'min_variance';

  const response = strategy === 'max_return'
    ? await manager.optimizeMaxReturn(portfolio.id!)
    : await manager.optimizeMinVariance(portfolio.id!);

  if (response.error || !response.optimization) {
    // Throw DataSourceError directly to bypass classifyError rewriting (BC-14 fix).
    throw new DataSourceError({
      category: 'unknown',
      sourceId: 'optimization',
      retryable: false,
      userMessage: response.error ?? 'Optimization returned no data',
    });
  }

  const adapter = AdapterRegistry.getAdapter(
    'portfolioOptimization',
    [portfolio.id ?? 'default', strategy],
    (cache) => new PortfolioOptimizationAdapter(cache, portfolio.id ?? undefined),
    unifiedAdapterCache
  );

  return adapter.transform(response.optimization, strategy) as SDKSourceOutputMap['optimization'];
},
```

Import addition at top of registry.ts:
```typescript
import { PortfolioOptimizationAdapter } from '../adapters/PortfolioOptimizationAdapter';
```

Update `OptimizationSourceData` in `types.ts` to match `OptimizationData`:

```typescript
export interface OptimizationSourceData {
  strategy: 'min_variance' | 'max_return';
  weights: Record<string, number>;
  summary: Record<string, unknown> & {
    total_assets: number;
    optimization_date: string;
    objective_value: number;
  };
  portfolio_metadata: Record<string, unknown> & {
    portfolio_name: string;
    analyzed_at: string;
    total_value: number;
  };
  success?: boolean;
  optimization_results?: Record<string, unknown>;
  optimization_results_raw?: Record<string, unknown>;
  risk_limits_metadata?: Record<string, unknown>;
  data_availability?: {
    has_success: boolean;
    has_risk_limits: boolean;
    data_quality: 'complete' | 'partial' | 'minimal';
  };
  [key: string]: unknown;
}
```

Update the `optimization` descriptor fields:
```typescript
fields: [
  { name: 'strategy', type: 'string', description: 'Optimization strategy used.' },
  { name: 'weights', type: 'object', description: 'Optimized asset allocation weights.' },
  { name: 'summary', type: 'object', description: 'Optimization summary metrics.' },
  { name: 'portfolio_metadata', type: 'object', description: 'Portfolio metadata.' },
],
```

### 3c. New `realized-performance` resolver

```typescript
'realized-performance': async (params, context) => {
  const { api } = context.services;

  const response = await api.getRealizedPerformance({
    benchmarkTicker: params?.benchmarkTicker,
    source: params?.source,
    institution: params?.institution,
    account: params?.account,
    startDate: params?.startDate,
    endDate: params?.endDate,
    includeSeries: params?.includeSeries,
  });

  return RealizedPerformanceAdapter.transform(response) as SDKSourceOutputMap['realized-performance'];
},
```

Import addition at top of registry.ts:
```typescript
import { RealizedPerformanceAdapter } from '../adapters/RealizedPerformanceAdapter';
```

### 3d. New `portfolio-summary` resolver

The resolver composes three existing resolvers in parallel, then combines via `PortfolioSummaryAdapter`.

```typescript
'portfolio-summary': async (params, context) => {
  const portfolio = requirePortfolio('portfolio-summary', getPortfolio(params?.portfolioId, context.currentPortfolio));
  const { unifiedAdapterCache } = context.services;

  // All three sub-resolvers are required. Performance failure should propagate
  // to the consumer (PortfolioOverviewContainer gates on `error` at line 164).
  // Current hook requires risk-score + risk-analysis (returns null without them)
  // and surfaces performance errors via the error field. Swallowing performance
  // errors would cause the container to render zero-filled metrics (BC-8 fix).
  const [riskScoreData, riskAnalysisData, performanceData] = await Promise.all([
    resolverMap['risk-score']({ portfolioId: portfolio.id }, context),
    resolverMap['risk-analysis']({ portfolioId: portfolio.id }, context),
    resolverMap.performance({ portfolioId: portfolio.id }, context),
  ]);

  const adapter = AdapterRegistry.getAdapter(
    'portfolioSummary',
    [portfolio.id ?? 'default'],
    (cache) => new PortfolioSummaryAdapter(cache, portfolio.id ?? undefined),
    unifiedAdapterCache
  );

  const portfolioForAdapter = {
    holdings: portfolio.holdings ?? null,
  };

  return adapter.transform(
    riskAnalysisData,
    riskScoreData,
    portfolioForAdapter,
    performanceData
  ) as SDKSourceOutputMap['portfolio-summary'];
},
```

Import additions at top of registry.ts:
```typescript
import { PortfolioSummaryAdapter } from '../adapters/PortfolioSummaryAdapter';
```

**Note**: All three sub-resolver calls are required (no `.catch()` swallowing). If any fails, the entire `portfolio-summary` resolver throws, which surfaces the error via `useDataSource.error` — matching the current consumer behavior where `PortfolioOverviewContainer` gates on `error` and shows an error state. The existing test at `usePortfolioSummary.test.tsx:185` that verifies partial data on performance failure should be updated to verify the error propagation instead.

## Step 4 — Rewrite 4 Hooks as Thin Wrappers

### 4a. useStockAnalysis (280 -> ~40 lines)

File: `frontend/packages/connectors/src/features/stockAnalysis/hooks/useStockAnalysis.ts`

```typescript
import { useMemo, useState, useCallback } from 'react';
import { useDataSource } from '../../../resolver/useDataSource';
import type { StockRiskDisplayData } from '../../../adapters/StockAnalysisAdapter';

export const useStockAnalysis = () => {
  const [ticker, setTicker] = useState<string | null>(null);

  const resolved = useDataSource(
    'stock-analysis',
    ticker ? { ticker } : undefined,
    { enabled: !!ticker }
  );

  const analyzeStock = useCallback((newTicker: string) => {
    setTicker(newTicker.trim().toUpperCase());
  }, []);

  return useMemo(() => ({
    data: (resolved.data ?? undefined) as StockRiskDisplayData | undefined,
    loading: resolved.loading,
    isLoading: resolved.loading,
    isRefetching: resolved.isRefetching,
    error: resolved.error?.message ?? null,
    refetch: resolved.refetch,
    refreshStockAnalysis: resolved.refetch,
    hasData: !!resolved.data,
    hasError: !!resolved.error,
    hasTicker: !!ticker,
    ticker,
    clearError: () => {},
    analyzeStock,
  }), [resolved.data, resolved.loading, resolved.isRefetching, resolved.error, resolved.refetch, ticker, analyzeStock]);
};

export default useStockAnalysis;
```

**Key decisions**:
- `enabled: !!ticker` — only fetch when ticker is set (same as current `enabled: !!ticker && !!stockManager`)
- `data` typed as `StockRiskDisplayData | undefined` — the resolver now returns adapter-transformed data, which matches `StockRiskDisplayData`. Cast needed because `SDKSourceOutputMap['stock-analysis']` is `StockAnalysisSourceData` (updated to match).
- `resolved.data ?? undefined` — coerce `null` to `undefined` for consumer compat (current hook returns `undefined` before first analysis)
- `analyzeStock` calls `setTicker` which changes params -> new query key -> auto-fetch
- No `frontendLogger` calls — resolver handles logging

### 4b. usePortfolioOptimization (294 -> ~50 lines)

File: `frontend/packages/connectors/src/features/optimize/hooks/usePortfolioOptimization.ts`

```typescript
import { useMemo, useState, useCallback } from 'react';
import { useCurrentPortfolio } from '@risk/chassis';
import { useDataSource } from '../../../resolver/useDataSource';
import type { OptimizationData, OptimizationStrategy } from '../../../adapters/PortfolioOptimizationAdapter';

export const usePortfolioOptimization = () => {
  const currentPortfolio = useCurrentPortfolio();
  const [strategy, setStrategy] = useState<OptimizationStrategy>('min_variance');

  const resolved = useDataSource(
    'optimization',
    currentPortfolio
      ? { portfolioId: currentPortfolio.id, strategy }
      : undefined,
    { enabled: !!currentPortfolio }
  );

  const optimizeMinVariance = useCallback(() => {
    setStrategy('min_variance');
  }, []);

  const optimizeMaxReturn = useCallback(() => {
    setStrategy('max_return');
  }, []);

  return useMemo(() => ({
    data: (resolved.data ?? null) as OptimizationData | null,
    loading: resolved.loading,
    isLoading: resolved.loading,
    isRefetching: resolved.isRefetching,
    error: resolved.error?.message ?? null,
    refetch: resolved.refetch,
    refreshOptimization: resolved.refetch,
    hasData: !!resolved.data,
    hasError: !!resolved.error,
    hasPortfolio: !!currentPortfolio,
    currentPortfolio,
    clearError: () => {},
    strategy,
    optimizeMinVariance,
    optimizeMaxReturn,
  }), [resolved.data, resolved.loading, resolved.isRefetching, resolved.error, resolved.refetch, currentPortfolio, strategy, optimizeMinVariance, optimizeMaxReturn]);
};

export default usePortfolioOptimization;
```

**Key decisions**:
- `params` includes `portfolioId` for cache scoping (same rationale as Batch B)
- When `currentPortfolio` is null, params is `undefined` + `enabled: false` — no fetch. Matches current `enabled: !!currentPortfolio && !!manager`
- Strategy change -> params change -> new query key -> auto-fetch (same behavior as current hook)
- `data` typed as `OptimizationData | null` — resolver now returns adapter-transformed data
- `optimizeMinVariance`/`optimizeMaxReturn` are simpler — no `frontendLogger` calls (resolver handles)

### 4c. useRealizedPerformance (24 -> ~45 lines)

File: `frontend/packages/connectors/src/features/analysis/hooks/useRealizedPerformance.ts`

The current hook uses `useMutation` — a fundamentally different TanStack pattern from `useQuery`. Migration to `useDataSource` requires the manual-trigger `_runId` pattern from Batch B.

```typescript
import { useMemo, useState, useCallback, useRef, useEffect } from 'react';
import type { GetRealizedPerformanceParams } from '@risk/chassis';
import type { RealizedPerformanceTransformed } from '../../../adapters/RealizedPerformanceAdapter';
import { useDataSource } from '../../../resolver/useDataSource';

// Monotonic counter for unique run IDs — avoids Date.now() collisions in rapid reruns
let nextRunId = 1;

export const useRealizedPerformance = () => {
  const [params, setParams] = useState<GetRealizedPerformanceParams | null>(null);
  const [runId, setRunId] = useState<number | null>(null);

  // Promise-based settlement for mutateAsync — resolves when query settles (data or error).
  // Stores { resolve, reject, runId } so we only settle the promise for the matching run.
  const pendingRef = useRef<{
    resolve: () => void;
    reject: (err: Error) => void;
    runId: number;
  } | null>(null);

  // Resolve any pending promise on unmount to prevent hanging awaits
  useEffect(() => {
    return () => {
      if (pendingRef.current) {
        pendingRef.current.resolve();
        pendingRef.current = null;
      }
    };
  }, []);

  const resolverParams = useMemo(() => {
    if (!params) return undefined;
    return {
      ...params,
      _runId: runId ?? undefined,
    };
  }, [params, runId]);

  const resolved = useDataSource('realized-performance', resolverParams, {
    enabled: !!resolverParams,
  });

  // Settle the pending promise when query finishes loading — only for matching runId
  useEffect(() => {
    if (!pendingRef.current) return;
    if (resolved.loading) return;  // Still in flight
    // Only settle if the current runId matches the pending promise's runId
    if (runId !== pendingRef.current.runId) return;

    if (resolved.error) {
      pendingRef.current.reject(resolved.error);
    } else {
      pendingRef.current.resolve();
    }
    pendingRef.current = null;
  }, [resolved.loading, resolved.error, runId]);

  const mutate = useCallback((nextParams: GetRealizedPerformanceParams = {}) => {
    // Resolve any prior pending promise (superseded by this new run)
    if (pendingRef.current) {
      pendingRef.current.resolve();
      pendingRef.current = null;
    }
    setParams(nextParams);
    setRunId(nextRunId++);
  }, []);

  const mutateAsync = useCallback((nextParams: GetRealizedPerformanceParams = {}): Promise<void> => {
    // Resolve any prior pending promise (superseded by this new run)
    if (pendingRef.current) {
      pendingRef.current.resolve();
      pendingRef.current = null;
    }
    const thisRunId = nextRunId++;
    setParams(nextParams);
    setRunId(thisRunId);
    // Return a promise that resolves when the query settles — preserves await semantics
    // for spinner control in PerformanceView.tsx:72 (await onRefresh())
    return new Promise<void>((resolve, reject) => {
      pendingRef.current = { resolve, reject, runId: thisRunId };
    });
  }, []);

  const reset = useCallback(() => {
    setParams(null);
    setRunId(null);
    // Cancel any pending promise
    if (pendingRef.current) {
      pendingRef.current.resolve();
      pendingRef.current = null;
    }
  }, []);

  return useMemo(() => ({
    mutate,
    mutateAsync,
    data: (resolved.data ?? undefined) as RealizedPerformanceTransformed | undefined,
    isPending: resolved.loading,
    error: resolved.error,
    reset,
  }), [mutate, mutateAsync, resolved.data, resolved.loading, resolved.error, reset]);
};
```

**Key decisions**:
- `mutate`/`mutateAsync` set params + `_runId` to trigger the query
- `enabled: !!resolverParams` — disabled until first `mutate()` call
- `reset` clears params -> disables query -> clears data
- `isPending` maps to `resolved.loading`
- `error` is `DataSourceError | null` instead of `Error | null` (BC-6)
- `mutateAsync` can no longer return the resolved data synchronously — it triggers a state change that causes `useDataSource` to fetch, but the data arrives asynchronously via `resolved.data`. Consumer (`PerformanceViewContainer`) already uses `await realizedMutation.mutateAsync(...)` but only uses `.data` from the hook return, not the `mutateAsync` return value.

### 4d. usePortfolioSummary (398 -> ~50 lines)

File: `frontend/packages/connectors/src/features/portfolio/hooks/usePortfolioSummary.ts`

```typescript
import { useMemo } from 'react';
import { useCurrentPortfolio } from '@risk/chassis';
import { useDataSource } from '../../../resolver/useDataSource';

export const usePortfolioSummary = () => {
  const currentPortfolio = useCurrentPortfolio();

  const resolved = useDataSource(
    'portfolio-summary',
    currentPortfolio ? { portfolioId: currentPortfolio.id } : undefined,
    { enabled: !!currentPortfolio }
  );

  return useMemo(() => ({
    data: resolved.data ?? null,
    summary: resolved.data ?? null,
    loading: resolved.loading,
    isLoading: resolved.loading,
    isRefetching: resolved.isRefetching,
    error: resolved.error?.message ?? null,
    refetch: resolved.refetch,
    refreshSummary: resolved.refetch,
    hasData: !!resolved.data,
    hasError: !!resolved.error,
    hasPortfolio: !!currentPortfolio,
    currentPortfolio,
    clearError: () => {},
  }), [resolved.data, resolved.loading, resolved.isRefetching, resolved.error, resolved.refetch, currentPortfolio]);
};
```

**Key decisions**:
- Single `useDataSource` call replaces `useQueries` with 3 parallel queries
- `portfolio-summary` resolver internally does `Promise.all` of risk-score + risk-analysis + performance, then combines via `PortfolioSummaryAdapter`
- `summary: resolved.data ?? null` — legacy alias, same object reference as `data`
- No `AdapterRegistry` calls in the hook — adapter is in the resolver

## Step 5 — Export New Types from Catalog Index

File: `frontend/packages/chassis/src/catalog/index.ts`

Add to exports:
```typescript
RealizedPerformanceSourceData,
PortfolioSummarySourceData,
```

## Step 6 — Update Tests

### 6a. Descriptor count test

File: `frontend/packages/chassis/src/catalog/__tests__/descriptors.test.ts`

Update line 7-8: `29` -> `31`

### 6b. useStockAnalysis tests

File: `frontend/packages/connectors/src/features/stockAnalysis/__tests__/useStockAnalysis.test.tsx`

**Complete rewrite needed**: Current tests mock `useSessionServices`, `AdapterRegistry.getAdapter`, and call `stockManager.analyzeStock()` directly. New tests must mock `useDataSource` (or the resolver) and verify the thin wrapper behavior.

Key test changes:
- Remove `stockManager`/`AdapterRegistry` mocks — replaced by resolver mocking
- `analyzeStock('aapl')` -> verify `setTicker('AAPL')` -> verify `useDataSource` called with `{ ticker: 'AAPL' }`
- Error test: resolver throws -> `resolved.error.message` -> `error` field
- `data` is now `StockRiskDisplayData | undefined` (same shape, different pipeline)
- `refreshStockAnalysis` delegates to `resolved.refetch` (no longer returns Promise)

### 6c. usePortfolioOptimization tests

File: `frontend/packages/connectors/src/features/optimize/__tests__/usePortfolioOptimization.test.tsx`

Key test changes:
- Remove `manager.optimizeMinVariance`/`optimizeMaxReturn` mocks — replaced by resolver mocking
- Strategy switching: `optimizeMaxReturn()` -> `strategy` changes to `max_return` -> `useDataSource` called with new `strategy` param
- Query key test: current test asserts `portfolioOptimizationKey('pf-1', 'min_variance')` — new key is `['sdk', 'optimization', serializedParams]`. Update assertion.
- `data` shape is `OptimizationData` (same as current — resolver now goes through adapter)
- No-portfolio test: `enabled: false` prevents fetch

### 6d. useRealizedPerformance tests

File: `frontend/packages/connectors/src/features/analysis/__tests__/useRealizedPerformance.test.tsx`

Key test changes:
- Remove `api.getRealizedPerformance` + `RealizedPerformanceAdapter.transform` mocks — replaced by resolver mocking
- `mutate({ benchmarkTicker: 'SPY' })` -> verify params set -> verify `useDataSource` called with params
- `isPending` maps to `resolved.loading` (was `mutation.isPending`)
- `error` is `DataSourceError | null` instead of `Error | null` (BC-6)
- `reset` clears params -> disables query
- `mutateAsync` no longer returns the transformed data — test should not assert return value (BC-5)

### 6e. usePortfolioSummary tests

File: `frontend/packages/connectors/src/features/portfolio/__tests__/usePortfolioSummary.test.tsx`

Key test changes:
- Remove `manager.calculateRiskScore`/`analyzePortfolioRisk`/`getPerformanceAnalysis` mocks and all individual adapter mocks — replaced by single resolver mock
- Shared cache key tests: current tests assert `riskScoreKey`, `riskAnalysisKey`, `performanceKey` entries in queryClient. New hook uses `['sdk', 'portfolio-summary', ...]` key. Update assertions.
- Performance failure resilience test: resolver now propagates performance errors (no `.catch()`). Test must verify error surfaces via `resolved.error` when performance sub-resolver fails. Remove old test that asserts partial data on performance failure — that behavior is gone.
- `refreshSummary` delegates to `resolved.refetch` — single call refetches the summary resolver (which re-runs all 3 internal calls)

## Intentional Behavioral Changes

### BC-1: stock-analysis resolver output shape change (improvement)

**Current resolver**: Returns `{ ticker, summary?, fundamentals?, technicals?, ...payload }` — raw API passthrough with lightweight extraction.

**New resolver**: Returns `StockRiskDisplayData` from `StockAnalysisAdapter.transform()` — `{ ticker, volatility_metrics, regression_metrics, factor_summary, risk_metrics, analysis_date, success, summary, endpoint, ... }`.

**Impact**: Any consumer of `useDataSource('stock-analysis', ...)` (currently none — only `option-strategy` resolver calls the `stock-analysis` resolver) receives the adapter-transformed shape. The `option-strategy` resolver uses `stock.summary` which exists in both shapes. No breakage.

**useStockAnalysis consumer impact**: `StockLookupContainer` destructures `data`, `loading`, `error`, `ticker`, `analyzeStock`, `refetch`, `clearError`. All preserved exactly.

### BC-2: optimization resolver output shape change (improvement)

**Current resolver**: Returns `{ strategy, allocations, expected_return?, volatility?, sharpe_ratio?, ...data }` — raw data with lightweight extraction.

**New resolver**: Returns `OptimizationData` from `PortfolioOptimizationAdapter.transform()` — `{ strategy, weights, summary, portfolio_metadata, success?, ... }`.

**Impact**: `allocations` field renamed to `weights`. The `OptimizationSourceData` type is updated to use `weights`. No external consumers of `useDataSource('optimization', ...)` exist — the `optimization` DataSourceId was created in Batch A but only the hook uses it now.

**usePortfolioOptimization consumer impact**: `StrategyBuilderContainer` destructures `data`, `loading`, `error`, `hasData`, `hasPortfolio`, `strategy`, `optimizeMinVariance`, `optimizeMaxReturn`, `refetch`, `clearError`. All preserved exactly. The `data` shape is now `OptimizationData` (same as current hook output).

### BC-3: Stock analysis cache key change (trade-off)

**Current**: Query key is `stockAnalysisKey(ticker)` — a custom key function.

**New**: Query key is `['sdk', 'stock-analysis', serializedParams]` where params = `{ ticker }`.

**Impact**: On upgrade, cached stock analysis data under the old key is orphaned. Fresh fetch on next `analyzeStock()`. Negligible impact — stock analysis is a manual action.

**Shared cache loss**: Current hook and potential `useDataSource('stock-analysis')` consumers would share cache. After migration they DO share via the resolver.

### BC-4: Optimization cache key change (trade-off)

**Current**: Query key is `portfolioOptimizationKey(portfolioId, strategy)`.

**New**: Query key is `['sdk', 'optimization', serializedParams]` where params = `{ portfolioId, strategy }`.

**Impact**: Same as BC-3 — old cache orphaned. Fresh fetch on next optimization run.

**Additional**: Current hook includes `enabled: !!currentPortfolio && !!manager`. New hook uses `enabled: !!currentPortfolio` only (manager availability is guaranteed by `useSessionServices`).

### BC-5: useRealizedPerformance `mutateAsync` return value change (trade-off, mitigated)

**Current**: `mutateAsync(params)` returns `Promise<RealizedPerformanceTransformed>` — resolves to the transformed data.

**New**: `mutateAsync(params)` returns `Promise<void>` — resolves when the underlying query settles (data or error), NOT immediately. Uses a `useRef`-based pending promise that is settled by a `useEffect` watching `resolved.loading`.

**Await semantics preserved**: `PerformanceView.tsx:72` does `await onRefresh()` to control spinner state (`setIsRefreshing`). The new implementation's promise resolves when `resolved.loading` transitions to `false`, so the spinner stays active during the fetch — matching current behavior.

**Error propagation**: If the query errors, `pendingRef.reject(resolved.error)` fires, so `try/catch` in `PerformanceViewContainer.tsx:387` still catches.

**Race condition handling**: The pending promise stores a `runId` (monotonic counter, not `Date.now()`) and only settles for the matching run. A second `mutateAsync()` call resolves the prior promise before creating a new one. This prevents stale settlements from previous runs.

**Unmount cleanup**: Cleanup effect resolves any pending promise on unmount, preventing hanging awaits.

**Return value change**: The promise now resolves to `void` instead of `RealizedPerformanceTransformed`. Consumer at `PerformanceViewContainer.tsx:381` does NOT use the return value — it reads `realizedMutation.data` separately. Safe.

**Test update**: Test at line 50 does `await result.current.mutateAsync({...})` — this will resolve to `void` instead of the transformed data. Tests that assert on the return value must be updated to wait for `result.current.data` instead.

### BC-6: useRealizedPerformance `error` type change (type-level)

**Current**: `error` is `Error | null`.

**New**: `error` is `DataSourceError | null` (from `classifyError`).

**Consumer check**: `PerformanceViewContainer.tsx:368` reads `realizedMutation.error?.message`. `DataSourceError` extends `Error` and has `.message`. Safe.

**Test update**: Tests that assert `result.current.error?.message` still work. Tests that type-check `Error` specifically need `DataSourceError` import.

### BC-7: usePortfolioSummary shared cache keys lost (trade-off)

**Current**: Uses `riskScoreKey(portfolioId)`, `riskAnalysisKey(portfolioId)`, `performanceKey(portfolioId)` — SHARED with `useRiskScore`, `useRiskAnalysis`, `usePerformance`. When individual views load first, `usePortfolioSummary` gets instant cache hits.

**New**: Uses `['sdk', 'portfolio-summary', { portfolioId }]` — single key, NOT shared with individual hooks. The resolver calls individual resolvers which may or may not benefit from their own `['sdk', 'risk-score', ...]` cache entries depending on whether those hooks are also rendered.

**Impact**: If user visits Portfolio Overview first, individual risk views will still need their own fetches (no pre-warming from summary). If individual views render first, the summary resolver still calls them fresh (resolver-to-resolver calls don't go through React Query cache — they call the function directly).

**Mitigation**: The `portfolio-summary` resolver calls `resolverMap['risk-score']`, `resolverMap['risk-analysis']`, `resolverMap.performance` which go through the manager's internal `CacheService`. Manager cache has 30-min TTL. So the underlying API calls are still cached — just not at the React Query level.

**Acceptable**: Backend calls are cached by `CacheService`. UI-level cache sharing was a performance optimization, not a correctness requirement. Could be restored in a future PR with a custom `useDataSource` override that reads individual query caches.

### BC-8: usePortfolioSummary error reporting change (parity)

**Current**: Error is the first truthy error message from `riskScoreQuery.error || riskAnalysisQuery.error || performanceQuery.error`. All three are required — if risk-score or risk-analysis fails, `data` is `null` (line 336: `if (!riskScoreQuery.data || !riskAnalysisQuery.data) return null`). Performance error is surfaced via the error field. `PortfolioOverviewContainer.tsx:164` gates on `error` to show error state.

**New**: All three sub-resolver calls are required (no `.catch()` swallowing). If any fails, the `portfolio-summary` resolver throws, surfacing via `useDataSource.error` → `PortfolioOverviewContainer.tsx:164` shows error state. This matches the current behavior: any sub-query failure → error shown, no zero-filled metrics.

**Impact**: Behavioral parity. The error message format changes from raw `Error.message` to `DataSourceError.userMessage` (via `classifyError`), but the error/no-error gating is identical.

### BC-9: Optimization auto-fetch on mount (behavioral parity)

**Current**: Auto-fetches `min_variance` when portfolio is available and manager exists (`enabled: !!currentPortfolio && !!manager`).

**New**: Auto-fetches `min_variance` when portfolio is available (`enabled: !!currentPortfolio`). Strategy is in params, so portfolio-change or strategy-change triggers refetch.

**Impact**: Identical behavior — `manager` is always available when session services are initialized.

### BC-10: Stock analysis retry logic simplification (trade-off)

**Current**: Custom retry function suppresses retries for `'Invalid ticker'` and `'analysis failed'` substring matches.

**New**: Descriptor-level `retryable: true, maxRetries: 2`. All errors retry up to 2 times uniformly.

**Impact**: If the API returns "Invalid ticker" error, it will retry 2 times (then fail). Negligible — these retries fail quickly with the same error. The existing `stock-analysis` descriptor already has `retryable: true, maxRetries: 2`.

### BC-11: Optimization retry logic simplification (trade-off)

**Current**: Custom retry function suppresses retries for `'Portfolio validation'` and `'optimization failed'` substring matches.

**New**: Descriptor-level `retryable: true, maxRetries: 2` (from existing `optimizationDescriptor`).

**Impact**: Same as BC-10 — deterministic errors retry quickly and fail.

### BC-12: usePortfolioOptimization refetch return type change (hook API contract)

**Current**: `refetch` returns `Promise<QueryObserverResult>`.

**New**: `refetch` returns `void` (from `useDataSource`'s `resolved.refetch`).

**Impact**: `StrategyBuilderContainer.tsx:179` stores `refetch: refetchOptimization` but only calls it as `refetchOptimization()` without `await`. Safe.

**Test update**: Test at line 241-247 does `await result.current.refetch()` — `await void` resolves immediately. Test still passes.

### BC-13: useStockAnalysis refetch return type change (hook API contract)

**Current**: `refetch`/`refreshStockAnalysis` returns `Promise<QueryObserverResult>`.

**New**: Returns `void`.

**Impact**: `StockLookupContainer.tsx` calls `refetchStock` — no consumer uses the return value. Safe.

**Test update**: Test at line 151 does `await result.current.refreshStockAnalysis()` — still works.

### BC-14: Error message rewriting via classifyError — MITIGATED at resolver level

**Current**: All 4 hooks return raw `error.message` strings.

**New**: `useDataSource` routes errors through `classifyError()`. `classifyError` rewrites errors containing "validation" or "invalid" substrings to the generic `"Received an unexpected data format from the server."` (line 136). 429 errors get rewritten to `"Rate limit exceeded."`.

**Mitigation**: Resolvers for `stock-analysis` and `optimization` now throw `DataSourceError` directly (not plain `Error`) for known API error messages. `classifyError` passes `DataSourceError` instances through unchanged (line 30-32). This preserves the original error message (e.g., "Invalid ticker symbol: XYZ") in `userMessage`/`message`.

**Impact on stock analysis**: "Invalid ticker" preserved — resolver throws `DataSourceError` with original message.

**Impact on optimization**: "Portfolio validation failed" preserved — resolver throws `DataSourceError` with original message.

**Impact on realized performance**: Most errors are plain API errors → pass through `classifyError` "unknown" category which preserves the original message.

**Impact on portfolio summary**: Errors are from internal resolvers, already classified as `DataSourceError`.

**Remaining edge case**: If `stockManager.analyzeStock` throws an unexpected `Error` (not caught by the resolver's `response.error` check), it would still hit `classifyError`. This is a narrow edge case — the manager's contract is to return `{ error: string }`, not throw.

### BC-15: useRealizedPerformance query vs mutation lifecycle difference (trade-off)

**Current**: `useMutation` — no caching, no staleTime, no refetchOnReconnect, no auto-refetch. Each `mutate()` fires a fresh API call. Data persists in mutation state until `reset()`.

**New**: `useQuery` with `_runId` — cached per `_runId` key, `staleTime: 300s`, subject to `refetchOnReconnect`. Each `mutate()` creates a new `_runId` -> new cache entry. Previous run's data is orphaned in cache (not displayed, GC'd by React Query).

**Impact**: After 5 min stale + reconnect, the current run's data could be refetched. Extremely rare scenario for a manual-trigger analysis. Acceptable.

**Additional difference**: Current `useMutation` state persists across re-renders and component unmount/remount within same React tree. New `useQuery` cache persists globally in `QueryClient` — so if the component unmounts and remounts, the last `_runId`'s data would be re-fetched if stale, or served from cache if fresh. Different from mutation state which is component-scoped.

## Verification Checklist

1. `pnpm typecheck` — zero TS errors
2. Run catalog tests — `pnpm test -- descriptors.test` — update count assertion (29 -> 31)
3. Run hook tests — update all 4 test suites:
   - `pnpm test -- useStockAnalysis.test`
   - `pnpm test -- usePortfolioOptimization.test`
   - `pnpm test -- useRealizedPerformance.test`
   - `pnpm test -- usePortfolioSummary.test`
4. Add new test coverage:
   - stock-analysis: verify `analyzeStock('aapl')` normalizes to `'AAPL'` and triggers fetch
   - stock-analysis: verify no fetch before `analyzeStock()` called (`data === undefined`)
   - optimization: verify strategy switch triggers refetch with new strategy param
   - optimization: verify no-portfolio disables query
   - realized-performance: verify `mutate()` sets params + `_runId`
   - realized-performance: verify `mutateAsync()` returns a promise that resolves when query settles
   - realized-performance: verify `mutateAsync()` rejects when query errors (try/catch still works)
   - realized-performance: verify `reset()` clears data and disables query
   - realized-performance: verify `_runId` changes on repeated `mutate()` calls with same params
   - portfolio-summary: verify single `useDataSource` call with `portfolioId`
   - portfolio-summary: verify data=null when no portfolio
5. Chrome verify:
   - Stock Lookup -> search for AAPL -> verify data renders with volatility/regression metrics (`StockLookupContainer.tsx`)
   - Strategy Builder -> verify min_variance optimization loads -> switch to max_return -> verify data updates (`StrategyBuilderContainer.tsx`)
   - Performance View -> switch to realized mode -> click Analyze -> verify realized data renders (`PerformanceViewContainer.tsx`)
   - Portfolio Overview -> verify summary bar renders (risk score, volatility, total value) (`PortfolioOverviewContainer.tsx`)
   - **Switch portfolio** -> verify all views update with new portfolio data
   - **Note**: `HoldingsViewModernContainer` uses `usePositions()`, NOT `usePortfolioSummary`. No Chrome verify needed for Holdings.

## Files Changed (Expected: ~12)

1. `chassis/src/catalog/types.ts` — 2 new DataSourceIds + 2 output types + 2 param types + updated `StockAnalysisSourceData` + `OptimizationSourceData`
2. `chassis/src/catalog/descriptors.ts` — 2 new descriptors + updated field lists for `stock-analysis` + `optimization`
3. `chassis/src/catalog/index.ts` — 2 new type exports
4. `chassis/src/catalog/__tests__/descriptors.test.ts` — update count 29 -> 31
5. `connectors/src/resolver/registry.ts` — updated `stock-analysis` + `optimization` resolvers + 2 new resolvers + 3 import additions
6. `connectors/src/features/stockAnalysis/hooks/useStockAnalysis.ts` — rewritten
7. `connectors/src/features/optimize/hooks/usePortfolioOptimization.ts` — rewritten
8. `connectors/src/features/analysis/hooks/useRealizedPerformance.ts` — rewritten
9. `connectors/src/features/portfolio/hooks/usePortfolioSummary.ts` — rewritten
10-12. 4 test files updated (may split into separate PRs)

## Risk Assessment

- **stock-analysis resolver shape change**: MEDIUM — changes `StockAnalysisSourceData` type and resolver output. `option-strategy` resolver dependency verified safe (`stock.summary` exists in both shapes). No external `useDataSource('stock-analysis')` consumers.
- **optimization resolver shape change**: MEDIUM — changes `OptimizationSourceData` type (`allocations` -> `weights`). No external `useDataSource('optimization')` consumers.
- **realized-performance mutation->query**: MEDIUM — `mutateAsync` return type changes from `Promise<RealizedPerformanceTransformed>` to `Promise<void>`. Await semantics preserved via `useRef`-based pending promise. Consumer verified safe (doesn't use return value, spinner timing preserved).
- **portfolio-summary error propagation**: LOW — all three sub-resolver calls required (no `.catch()` swallowing). Matches current behavior where any sub-query failure → error state shown.
- **Type compatibility**: LOW — `RealizedPerformanceSourceData` defined inline in chassis types.ts as structural match for adapter's `RealizedPerformanceTransformed`. Hook wrapper casts for consumer type safety.
- **Error classification**: LOW — `stock-analysis` and `optimization` resolvers throw `DataSourceError` directly, bypassing `classifyError` rewriting. Original error messages preserved.

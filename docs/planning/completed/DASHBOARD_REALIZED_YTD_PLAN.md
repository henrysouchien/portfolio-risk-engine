# Switch Frontend Performance to Realized Mode (v10)

## Context

All frontend performance numbers currently use hypothetical mode — a backtest of current holdings since 2019. This is misleading. We switch the `performance` resolver to use realized (transaction-based) performance everywhere. Manual portfolios fall back to hypothetical.

## Part 1: Backend — Add Factor Attribution to Realized Performance

### File: `routes/realized_performance.py` (after line 201)

The realized route computes `sector_attribution` and `security_attribution` but not `factor_attribution`. Add it using the same `_compute_factor_attribution()` function the hypothetical path uses.

`_compute_factor_attribution()` needs `port_ret` (portfolio returns series). Compute from `df_ret` and `filtered_weights` which are already in scope:

```python
# After line 201 (security_attribution):
try:
    from portfolio_risk_engine.portfolio_risk import _compute_factor_attribution
    # Compute portfolio returns from per-ticker returns × weights.
    # Align weights to surviving tickers in df_ret, then compute weighted sum.
    weight_series = pd.Series(filtered_weights)
    common = weight_series.index.intersection(df_ret.columns)
    if len(common) > 0:
        aligned_ret = df_ret[common]
        aligned_w = weight_series[common]
        aligned_w = aligned_w / aligned_w.abs().sum()  # re-normalize
        port_ret = (aligned_ret * aligned_w).sum(axis=1)
        response["factor_attribution"] = _compute_factor_attribution(
            port_ret=port_ret,
            start_date=attr_start,
            end_date=attr_end,
            fmp_ticker_map=fmp_ticker_map,
        )
    else:
        response["factor_attribution"] = []
except Exception:
    response["factor_attribution"] = []
```

This produces `[{ name, beta, return, contribution }]` — matching the shape the frontend adapter expects.

### File: `frontend/packages/connectors/src/adapters/RealizedPerformanceAdapter.ts`

First add `factor_attribution` to `RealizedPerformanceApiResponse` in `chassis/src/types/index.ts:434`:
```ts
factor_attribution?: Array<{ name: string; beta: number | null; return: number; contribution: number }>;
```

Then update the adapter to read it from the response instead of hardcoding `[]`:

```ts
// Current (line 207):
factors: [],

// New:
factors: Array.isArray(apiResponse.factor_attribution)
  ? apiResponse.factor_attribution.map((f: Record<string, unknown>) => ({
      name: String(f.name ?? ''),
      beta: typeof f.beta === 'number' ? f.beta : null,
      return: Number(f.return ?? 0),
      contribution: Number(f.contribution ?? 0),
    }))
  : [],
```

## Part 2: Frontend Adapter — Fix Period Breakdown

### File: `frontend/packages/connectors/src/adapters/RealizedPerformanceAdapter.ts` (lines 169-186)

Replace hardcoded periods with computed values from `monthlyReturns` (decimal format, e.g., 0.0333 = 3.33%):

```ts
function computePeriodReturn(returns: Record<string, number>, months: string[], n: number): number {
  const window = months.slice(-n);
  if (!window.length) return 0;
  return (window.reduce((acc, m) => acc * (1 + (returns[m] ?? 0)), 1) - 1) * 100;
}

function computeYtdReturn(returns: Record<string, number>, months: string[]): number {
  const lastMonth = months[months.length - 1] ?? '';
  const year = lastMonth.slice(0, 4);
  const ytdMonths = months.filter(m => m.startsWith(year));
  if (!ytdMonths.length) return 0;
  return (ytdMonths.reduce((acc, m) => acc * (1 + (returns[m] ?? 0)), 1) - 1) * 100;
}

const sortedMonths = Object.keys(monthlyReturns).sort();
// Align benchmark to portfolio month keys to avoid window drift
const alignedBenchMonths = sortedMonths.filter(m => m in benchmarkMonthlyReturns);

// Build period entries — UI uses 1M, 1Y (PerformanceHeaderCard.tsx:107-108). YTD for summary cards.
// 1Y uses annualized return (matching hypothetical mode behavior at PerformanceAdapter.ts:820).
const makePeriod = (n: number) => {
  const pRet = computePeriodReturn(monthlyReturns, sortedMonths, n);
  const bRet = computePeriodReturn(benchmarkMonthlyReturns, alignedBenchMonths, n);
  return { portfolioReturn: pRet, benchmarkReturn: bRet, activeReturn: pRet - bRet, volatility: toNumber(risk.volatility, 0) };
};
const ytdPeriod = (() => {
  const pRet = computeYtdReturn(monthlyReturns, sortedMonths);
  const bRet = computeYtdReturn(benchmarkMonthlyReturns, alignedBenchMonths);
  return { portfolioReturn: pRet, benchmarkReturn: bRet, activeReturn: pRet - bRet, volatility: toNumber(risk.volatility, 0) };
})();

// Use in performanceSummary.periods:
'1M': makePeriod(1),
'1Y': {
  // Match hypothetical behavior: use annualized return for both sides (PerformanceAdapter.ts:820)
  // Backend annualized benchmark is comparison.benchmark_return (not benchmark_total_return)
  portfolioReturn: toNumber(returns.annualized_return, 0),
  benchmarkReturn: toNumber(comparison.benchmark_return, 0),
  activeReturn: toNumber(returns.annualized_return, 0) - toNumber(comparison.benchmark_return, 0),
  volatility: toNumber(risk.volatility, 0),
},
'YTD': ytdPeriod,
```

## Part 3: Frontend Adapter — Fix Drawdown Dates

### File: `frontend/packages/connectors/src/adapters/RealizedPerformanceAdapter.ts`

The backend already computes drawdown metadata in `risk_metrics` via `performance_metrics_engine.py:193-196` and passes it through in the realized response. Map these fields from the API response instead of recomputing in the frontend.

In the adapter's risk object construction (line 159), add all 5 drawdown fields matching `PerformanceAdapter.ts:312-320`:

```ts
// The API risk_metrics already contains drawdown metadata from the backend engine.
// Map to the adapter's camelCase output (matching PerformanceAdapter.ts:743-746):
const riskMetrics = apiResponse.risk_metrics;
risk: {
  volatility: toNumber(risk.volatility, 0),
  maxDrawdown: toNumber(risk.maximum_drawdown, 0),
  downsideDeviation: toNumber(risk.downside_deviation, 0),
  trackingError: toNumber(risk.tracking_error, 0),
  // Drawdown dates from backend engine (performance_metrics_engine.py:193-196)
  drawdownPeakDate: riskMetrics?.drawdown_peak_date ?? undefined,
  drawdownTroughDate: riskMetrics?.drawdown_trough_date ?? undefined,
  drawdownRecoveryDate: riskMetrics?.drawdown_recovery_date ?? undefined,
  drawdownDurationDays: riskMetrics?.drawdown_duration_days ?? undefined,
  drawdownRecoveryDays: riskMetrics?.drawdown_recovery_days ?? undefined,
},
```

Also extend the existing `risk_metrics` type in `RealizedPerformanceApiResponse` (`chassis/src/types/index.ts:394`) with optional drawdown fields. Keep `risk_metrics` required (the adapter reads it as required at line 123):
```ts
// Add to existing risk_metrics type (keep existing fields required):
risk_metrics: {
  volatility: number;
  maximum_drawdown: number;
  downside_deviation: number;
  tracking_error: number;
  // Drawdown metadata from backend engine (null when no drawdown exists)
  drawdown_peak_date?: string | null;
  drawdown_trough_date?: string | null;
  drawdown_recovery_date?: string | null;
  drawdown_duration_days?: number | null;
  drawdown_recovery_days?: number | null;
};
```

UI reads `drawdownPeakDate`, `drawdownTroughDate`, `drawdownDurationDays`, `drawdownRecoveryDays`, `drawdownRecoveryDate` at `PerformanceViewContainer.tsx:334+` and `PerformanceAdapter.ts:312-320`.

## Part 4: Frontend Adapter — Add Insights

### File: `frontend/packages/connectors/src/adapters/RealizedPerformanceAdapter.ts`

Generate insights matching `{ text: string, action: string, impact: 'high' | 'medium' | 'low' }` (per `PerformanceAdapter.ts:401`, `types.ts:101`):

```ts
const maxDD = Math.abs(toNumber(risk.maximum_drawdown, 0));
const insights = {
  performance: {
    text: totalReturn > 0 ? `Portfolio returned +${totalReturn.toFixed(1)}%` : `Portfolio declined ${Math.abs(totalReturn).toFixed(1)}%`,
    action: totalReturn > 0 ? 'Consider rebalancing to lock in gains' : 'Review underperforming positions',
    impact: Math.abs(totalReturn) > 10 ? 'high' as const : Math.abs(totalReturn) > 5 ? 'medium' as const : 'low' as const,
  },
  risk: {
    text: `Maximum drawdown of ${maxDD.toFixed(1)}%`,
    action: maxDD > 15 ? 'Consider hedging or reducing position sizes' : 'Drawdown within normal range',
    impact: maxDD > 15 ? 'high' as const : maxDD > 10 ? 'medium' as const : 'low' as const,
  },
  opportunity: {
    text: activeReturn > 0 ? `Outperforming benchmark by +${activeReturn.toFixed(1)}%` : `Underperforming benchmark by ${Math.abs(activeReturn).toFixed(1)}%`,
    action: activeReturn > 0 ? 'Current strategy generating alpha' : 'Review holdings vs benchmark',
    impact: Math.abs(activeReturn) > 5 ? 'high' as const : 'medium' as const,
  },
};

// Wire into the return object (RealizedPerformanceAdapter.ts:135):
// Add `insights` to the returned performanceData object alongside existing fields
return {
  ...existingReturnObject,
  insights,
};
```

The insights object must be added to the `performanceData` returned by `transformPerformanceData()` at line 135. The exact insertion depends on the return statement structure — add `insights` as a sibling of `performanceSummary`, `returns`, `risk`, etc.
```

## Part 5: Switch the Resolver

### File: `frontend/packages/connectors/src/resolver/registry.ts` (lines 316-337)

```ts
performance: async (params, context) => {
  const portfolio = requirePortfolio('performance', getPortfolio(params?.portfolioId, context.currentPortfolio));
  const supportedModes: string[] = (portfolio as { supported_modes?: string[] }).supported_modes ?? [];
  const useRealized = supportedModes.includes('performance_realized');

  if (useRealized) {
    // No try/catch — realized errors should surface, not silently fall back to hypothetical
    const realizedResult = await resolverMap['realized-performance']({
      portfolioId: portfolio.id,
      benchmarkTicker: params?.benchmarkTicker,
      // No startDate — full inception for proper period breakdown
    }, context);
    return realizedResult.performanceData as unknown as SDKSourceOutputMap['performance'];
  }

  // Hypothetical: manual portfolios only
  const { manager, unifiedAdapterCache } = context.services;
  const result = await manager.getPerformanceAnalysis(portfolio.id!, params?.benchmarkTicker, params?.includeAttribution);
  if (result.error || !result.performance) throw new Error(result.error ?? 'Performance analysis returned no data');
  const adapter = AdapterRegistry.getAdapter('performance', [portfolio.id ?? 'default'],
    (cache) => new PerformanceAdapter(cache, portfolio.id ?? undefined), unifiedAdapterCache);
  return adapter.transform(result.performance) as SDKSourceOutputMap['performance'];
},
```

## Part 6: Summary Card YTD Wiring

### File: `frontend/packages/connectors/src/adapters/PortfolioSummaryAdapter.ts` (line 345-347)

Since full inception data flows through, `totalReturn` is the full-period return. Use the computed YTD period:

```ts
// Current:
derivedYtdReturn = this.toNumber(returns.totalReturn, 0);

// New — use asRecord chain for type safety (performanceSummary is Record<string, unknown>):
const perfSummaryPeriods = this.asRecord(this.asRecord(performanceSummary).periods);
const ytdPeriod = this.asRecord(perfSummaryPeriods.YTD);
derivedYtdReturn = this.toNullableNumber(ytdPeriod.portfolioReturn) ?? this.toNumber(returns.totalReturn, 0);
```

Also update comment: `// YTD return — realized when available, hypothetical fallback`

## Part 7: Label Update

### File: `frontend/packages/ui/src/components/portfolio/overview/useOverviewMetrics.ts` (line 44)

```ts
description: "portfolio return"
```

## Implementation Notes

- **Benchmark alignment**: Benchmark period windows use `sortedMonths.filter(m => m in benchmarkMonthlyReturns)` to align with portfolio months.

## Scope

**Changed**: All performance numbers — summary cards, Performance view (period selectors, charts), factor attribution (now computed in realized backend), drawdown dates, insights.
**Known gaps**: 1D/1W periods not available in realized mode (UI skips gracefully). Day change uses $100K growth curve (pre-existing, separate fix).
**Fallback**: Manual portfolios use hypothetical. Realized errors surface (no silent fallback).

## Verification

- Browser: YTD Return card shows realistic number
- Browser: Performance view 1M/1Y show different period-specific values
- Browser: Factor attribution table populated with realized data
- Browser: Drawdown peak date and duration shown
- Browser: Manual portfolio falls back to hypothetical
- `python3 -m pytest tests/ -x -q` — backend tests
- `npx tsc --noEmit` — frontend type check

## Files Modified

| File | Change |
|------|--------|
| `routes/realized_performance.py` | Add `factor_attribution` computation from portfolio returns |
| `frontend/.../RealizedPerformanceAdapter.ts` | Period breakdown, factor reading, drawdown dates, insights |
| `frontend/.../resolver/registry.ts` | `performance` resolver: realized when supported, hypothetical fallback for manual |
| `frontend/.../PortfolioSummaryAdapter.ts` | YTD wiring from period data + comment |
| `frontend/.../useOverviewMetrics.ts` | Description update |
| `frontend/packages/chassis/src/types/index.ts` | Add `factor_attribution` to `RealizedPerformanceApiResponse` type (~line 374) |

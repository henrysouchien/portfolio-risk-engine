# Codex Spec: Percentage Formatting Standardization (T1 #23)

**Rule:** All percentages displayed to users should use 1 decimal place. Sharpe ratios use 2 decimal places — existing `formatNumber(..., { decimals: 2 })` and `.toFixed(2)` for Sharpe are already correct and kept as-is. A new `formatSharpeRatio()` utility is created for new call sites (Strategy PerformanceTab line 257) and the raw interpolation in helpers.ts. Non-percentage `toFixed(2)` (prices, betas, correlations, ratios, market cap) are NOT changed.

**Scope:** ~65 changes across 17 files (+ 1 re-export). All mechanical find-and-replace. No logic changes.

**Note:** Several files (PerformanceHeaderCard.tsx, RiskAnalysisTab.tsx, BenchmarksTab.tsx, PeriodAnalysisTab.tsx) already use `decimals: 1` and are NOT included in this spec.

---

## Step 1: Fix PercentageBadge default

**File:** `frontend/packages/ui/src/components/blocks/percentage-badge.tsx`
- **Line 111:** Change default prop `decimals = 2` to `decimals = 1`

---

## Step 2: Create formatSharpeRatio utility + re-export

**File:** `frontend/packages/app-platform/src/utils/formatting.ts`
- Add after `formatBasisPoints()` (after line 222):
```typescript
export function formatSharpeRatio(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '\u2014';
  const finite = value as number;
  const normalized = Object.is(finite, -0) ? 0 : finite;
  return normalized.toFixed(2);
}
```

**File:** `frontend/packages/chassis/src/utils/formatting.ts`
- **Line 7:** Add `formatSharpeRatio` to the named re-export list:
```typescript
export {
  formatBasisPoints,
  formatCompact,
  formatCurrency,
  formatNumber,
  formatPercent,
  formatSharpeRatio,
  roundTo,
} from '@risk/app-platform';
```

Both barrels (`app-platform/src/index.ts` line 55, `chassis/src/index.ts` line 11) already use `export *` so no changes needed there. Consumers import from `@risk/chassis`.

---

## Step 3: Fix performance helpers — formatOptionalPercent default + alpha tooltip

**File:** `frontend/packages/ui/src/components/portfolio/performance/helpers.ts`

| Line | Current | New |
|------|---------|-----|
| 21 | `formatOptionalPercent = (value: ..., decimals = 2)` | `decimals = 1` |
| 55 | `formatPercent(data.alpha, { decimals: 2, sign: true })` | `{ decimals: 1, sign: true }` |
| 74 | Raw `data.sharpeRatio` interpolated in tooltip text | Wrap with `formatSharpeRatio(data.sharpeRatio)` |

**Note:** Line 55 is the alpha tooltip inside `generateTooltipContent("alpha", ...)`. Line 74 is inside `generateTooltipContent("sharpe", ...)` where `data.sharpeRatio` is interpolated as a raw number — needs `formatSharpeRatio()` for consistent 2dp display. Add `import { formatSharpeRatio } from "@risk/chassis"` to the helpers.ts imports.

3 changes.

---

## Step 4: Fix strategy helpers — formatOptionalPercent default

**File:** `frontend/packages/ui/src/components/portfolio/strategy/helpers.tsx`

| Line | Current | New |
|------|---------|-----|
| 22 | `formatOptionalPercent = (value: ..., decimals = 2)` | `decimals = 1` |

1 change. (All callers passing explicit `2` are fixed in their respective steps.)

---

## Step 5: Fix stock-lookup helpers — percentage toFixed

**File:** `frontend/packages/ui/src/components/portfolio/stock-lookup/helpers.ts`

| Line | Current | New | Context |
|------|---------|-----|---------|
| 34 | `normalized.toFixed(2)` | `normalized.toFixed(1)` | `formatPeerMetricValue` — percent metric |
| 46 | `(value * 100).toFixed(2)` | `(value * 100).toFixed(1)` | `formatPortfolioMetric` — `format === 'percent'` |
| 49 | `value.toFixed(2)` | `value.toFixed(1)` | `formatPortfolioMetric` — `format === 'percentPoints'` |
| 62 | `(delta * 100).toFixed(2)` | `(delta * 100).toFixed(1)` | `formatPortfolioDelta` — `format === 'percent'` |
| 65 | `delta.toFixed(2)` | `delta.toFixed(1)` | `formatPortfolioDelta` — `format === 'percentPoints'` |

**NOT changed** (non-percentage):
- Line 37: `numeric.toFixed(2)` — generic numeric metric (PE ratio, D/E, etc.)
- Line 51: `value.toFixed(4)` — ratio format
- Lines 87, 90, 92: `formatMarketCap` — dollar values

5 changes.

---

## ~~Step 6: SKIP — PerformanceHeaderCard already uses decimals: 1~~

All `formatPercent` calls in `PerformanceHeaderCard.tsx` already use `{ decimals: 1, sign: true }`. No changes needed. Sharpe on line 224 uses `.toFixed(2)` which is correct (Sharpe is a ratio, not a percentage).

---

## ~~Step 7: SKIP — RiskAnalysisTab already uses decimals: 1~~

All `formatOptionalPercent` calls in `RiskAnalysisTab.tsx` already use `1` as the decimals argument. No changes needed.

---

## ~~Step 8: SKIP — BenchmarksTab already uses decimals: 1~~

All `formatPercent` and `formatOptionalPercent` calls in `BenchmarksTab.tsx` already use `decimals: 1`. No changes needed.

---

## Step 9: Fix AttributionTab

**File:** `frontend/packages/ui/src/components/portfolio/performance/AttributionTab.tsx`

| Line | Current | New |
|------|---------|-----|
| 27 | `formatOptionalPercent(row.allocation, 2)` | `formatOptionalPercent(row.allocation, 1)` |
| 35 | `formatPercent(row.return, { decimals: 2, sign: true })` | `{ decimals: 1, sign: true }` |
| 45 | `formatPercent(row.contribution, { decimals: 2, sign: true })` | `{ decimals: 1, sign: true }` |
| 74 | `formatPercent(row.return, { decimals: 2, sign: true })` | `{ decimals: 1, sign: true }` |
| 84 | `formatPercent(row.contribution, { decimals: 2, sign: true })` | `{ decimals: 1, sign: true }` |
| 104 | `formatOptionalPercent(row.weight, 2)` | `formatOptionalPercent(row.weight, 1)` |
| 112 | `formatPercent(row.return, { decimals: 2, sign: true })` | `{ decimals: 1, sign: true }` |
| 122 | `formatPercent(row.contribution, { decimals: 2, sign: true })` | `{ decimals: 1, sign: true }` |

8 changes.

---

## ~~Step 10: SKIP — PeriodAnalysisTab already uses decimals: 1~~

All `formatPercent` calls in `PeriodAnalysisTab.tsx` already use `{ decimals: 1, sign: true }`. No changes needed.

---

## Step 11: Fix Strategy PerformanceTab

**File:** `frontend/packages/ui/src/components/portfolio/strategy/PerformanceTab.tsx`

| Line | Current | New |
|------|---------|-----|
| 31 | `formatOptionalPercent(row.allocation, 2)` | `formatOptionalPercent(row.allocation, 1)` |
| 38 | `formatPercent(row.return, { decimals: 2, sign: true })` | `{ decimals: 1, sign: true }` |
| 47 | `formatPercent(row.contribution, { decimals: 2, sign: true })` | `{ decimals: 1, sign: true }` |
| 66 | `formatOptionalPercent(row.allocation, 2)` | `formatOptionalPercent(row.allocation, 1)` |
| 73 | `formatPercent(row.return, { decimals: 2, sign: true })` | `{ decimals: 1, sign: true }` |
| 82 | `formatPercent(row.contribution, { decimals: 2, sign: true })` | `{ decimals: 1, sign: true }` |
| 108 | `formatPercent(row.return, { decimals: 2, sign: true })` | `{ decimals: 1, sign: true }` |
| 117 | `formatPercent(row.contribution, { decimals: 2, sign: true })` | `{ decimals: 1, sign: true }` |
| 199 | `formatPercent(row.portfolioReturn, { decimals: 2, sign: true })` | `{ decimals: 1, sign: true }` |
| 206 | `formatPercent(row.benchmarkReturn, { decimals: 2, sign: true })` | `{ decimals: 1, sign: true }` |
| 215 | `formatPercent(row.alpha, { decimals: 2, sign: true })` | `{ decimals: 1, sign: true }` |
| 245 | `formatPercent(toNumber(returnsMetrics?.total_return, 0), { decimals: 2, sign: true })` | `{ decimals: 1, sign: true }` |
| 251 | `formatPercent(toNumber(returnsMetrics?.annualized_return, 0), { decimals: 2, sign: true })` | `{ decimals: 1, sign: true }` |
| 257 | `formatNumber(toNumber(riskAdjustedMetrics?.sharpe_ratio, 0), { decimals: 3 })` | `formatSharpeRatio(toNumber(riskAdjustedMetrics?.sharpe_ratio, 0))` |
| 263 | `formatPercent(toNumber(riskMetrics?.maximum_drawdown, 0), { decimals: 2 })` | `{ decimals: 1 }` |
| 269 | `formatOptionalPercent(... benchmarkMetrics?.alpha_annual ..., 2)` | `..., 1)` |
| 293 | `formatPercent(toNumber(benchmarkComparison?.portfolio_total_return, 0), { decimals: 2, sign: true })` | `{ decimals: 1, sign: true }` |
| 296 | `formatPercent(toNumber(benchmarkComparison?.benchmark_total_return, 0), { decimals: 2, sign: true })` | `{ decimals: 1, sign: true }` |

Also add `formatSharpeRatio` to the import from `@risk/chassis` (or from the local `helpers` if it re-exports). Line 257 currently uses `formatNumber` with 3 decimal places for Sharpe — this should use `formatSharpeRatio()` (created in Step 2) which standardizes Sharpe to 2dp with null/NaN guarding.

18 changes.

---

## Step 12: Fix useOverviewMetrics

**File:** `frontend/packages/ui/src/components/portfolio/overview/useOverviewMetrics.ts`

| Line | Current | New |
|------|---------|-----|
| 20 | `formatPercent(summary.dayChangePercent,{ decimals: 2,sign: true })` | `{ decimals: 1,sign: true }` |

1 change.

---

## Step 13: Fix HedgeWorkflowDialog — percentage helpers

**File:** `frontend/packages/ui/src/components/portfolio/HedgeWorkflowDialog.tsx`

| Line | Current | New |
|------|---------|-----|
| 155 | `(value * 100).toFixed(2)` in `toPercent` | `(value * 100).toFixed(1)` |
| 156 | `(value * 100).toFixed(2)` in `toSignedPercent` | `(value * 100).toFixed(1)` |

**NOT changed** (non-percentage):
- Line 524: `impliedCorrelation.toFixed(2)` — correlation value, not percentage
- Line 659: `trade.price.toFixed(2)` — dollar price

2 changes.

---

## Step 14: Fix OptimizationsTab — weight percentages

**File:** `frontend/packages/ui/src/components/portfolio/scenario/OptimizationsTab.tsx`

| Line | Current | New |
|------|---------|-----|
| 156 | `row.currentWeight.toFixed(2)` + `%` | `row.currentWeight.toFixed(1)` |
| 157 | `row.optimizedWeight.toFixed(2)` + `%` | `row.optimizedWeight.toFixed(1)` |
| 161 | `row.delta.toFixed(2)` + `%` | `row.delta.toFixed(1)` |

3 changes.

---

## Step 15: Fix RiskMetricsContainer — VaR percentage

**File:** `frontend/packages/ui/src/components/dashboard/views/modern/RiskMetricsContainer.tsx`

| Line | Current | New |
|------|---------|-----|
| 149 | `formatPercent(varPercentOfPortfolio,{ decimals: 2 })` | `{ decimals: 1 }` |

1 change.

---

## Step 16: Fix PerformanceAdapter — benchmark display strings

**File:** `frontend/packages/connectors/src/adapters/PerformanceAdapter.ts`

| Line | Current | New | Notes |
|------|---------|-----|-------|
| 1061 | `formatPercent(benchmark.alpha_annual \|\| 0,{ decimals: 2 })` | `{ decimals: 1 }` | alpha % |
| 1064 | `formatPercent(benchmark.excess_return \|\| 0,{ decimals: 2 })` | `{ decimals: 1 }` | excess return % |
| 1067 | `formatPercent(comparison.portfolio_return \|\| 0,{ decimals: 2 })` | `{ decimals: 1 }` | portfolio return % |
| 1068 | `formatPercent(comparison.benchmark_return \|\| 0,{ decimals: 2 })` | `{ decimals: 1 }` | benchmark return % |
| 1069 | `formatPercent(comparison.portfolio_volatility \|\| 0,{ decimals: 2 })` | `{ decimals: 1 }` | portfolio vol % |
| 1070 | `formatPercent(comparison.benchmark_volatility \|\| 0,{ decimals: 2 })` | `{ decimals: 1 }` | benchmark vol % |

**NOT changed** (non-percentage ratios):
- Line 1062: `formatNumber(benchmark.beta \|\| 0,{ decimals: 2 })` — beta coefficient
- Line 1063: `formatNumber(benchmark.r_squared \|\| 0,{ decimals: 3 })` — R-squared
- Line 1071: `formatNumber(comparison.portfolio_sharpe \|\| 0,{ decimals: 2 })` — Sharpe ratio
- Line 1072: `formatNumber(comparison.benchmark_sharpe \|\| 0,{ decimals: 2 })` — Sharpe ratio

6 changes.

---

## Step 17: Fix RealizedPerformanceAdapter — benchmark display strings

**File:** `frontend/packages/connectors/src/adapters/RealizedPerformanceAdapter.ts`

| Line | Current | New | Notes |
|------|---------|-----|-------|
| 221 | `formatPercent(toNumber(benchmark.alpha_annual, 0), { decimals: 2 })` | `{ decimals: 1 }` | alpha % |
| 224 | `formatPercent(toNumber(benchmark.excess_return, 0), { decimals: 2 })` | `{ decimals: 1 }` | excess return % |
| 225 | `formatPercent(toNumber(comparison.portfolio_return, 0), { decimals: 2 })` | `{ decimals: 1 }` | portfolio return % |
| 226 | `formatPercent(toNumber(comparison.benchmark_return, 0), { decimals: 2 })` | `{ decimals: 1 }` | benchmark return % |
| 227 | `formatPercent(toNumber(comparison.portfolio_volatility, 0), { decimals: 2 })` | `{ decimals: 1 }` | portfolio vol % |
| 228 | `formatPercent(toNumber(comparison.benchmark_volatility, 0), { decimals: 2 })` | `{ decimals: 1 }` | benchmark vol % |

**NOT changed** (non-percentage ratios):
- Line 222: `formatNumber(... benchmark.beta ..., { decimals: 2 })` — beta
- Line 223: `formatNumber(... benchmark.r_squared ..., { decimals: 3 })` — R-squared
- Line 229: `formatNumber(... comparison.portfolio_sharpe ..., { decimals: 2 })` — Sharpe
- Line 230: `formatNumber(... comparison.benchmark_sharpe ..., { decimals: 2 })` — Sharpe

6 changes.

---

## Step 18: Fix RiskAnalysisAdapter — risk contribution display

**File:** `frontend/packages/connectors/src/adapters/RiskAnalysisAdapter.ts`

| Line | Current | New | Notes |
|------|---------|-----|-------|
| 583 | `formatPercent(normalizedContribution * 100,{ decimals: 2 })` | `{ decimals: 1 }` | risk contribution % |
| 777 | `formatPercent(pct * 100,{ decimals: 2 })` | `{ decimals: 1 }` | position risk % |

2 changes.

---

## Step 19: Fix useAnalysisReport — report text percentages

**File:** `frontend/packages/connectors/src/features/analysis/hooks/useAnalysisReport.ts`

| Line | Current | New |
|------|---------|-----|
| 35 | `formatPercent(annualVolatility * 100,{ decimals: 2 })` | `{ decimals: 1 }` |
| 43 | `formatPercent(factorVariance,{ decimals: 2 })` | `{ decimals: 1 }` |
| 44 | `formatPercent(idiosyncraticVariance,{ decimals: 2 })` | `{ decimals: 1 }` |

3 changes.

---

## Step 20: Fix registry — trading analysis signal text

**File:** `frontend/packages/connectors/src/resolver/registry.ts`

| Line | Current | New |
|------|---------|-----|
| 355 | `formatPercent(performance.risk.maxDrawdown,{ decimals: 2 })` | `{ decimals: 1 }` |

1 change.

---

## Step 21: Fix StockLookup — changePercent display

**File:** `frontend/packages/ui/src/components/portfolio/StockLookup.tsx`

| Line | Current | New | Context |
|------|---------|-----|---------|
| 167 | `result.changePercent.toFixed(2)` | `result.changePercent.toFixed(1)` | Search result row — percentage change display |
| 266 | `selectedStock.changePercent.toFixed(2)` | `selectedStock.changePercent.toFixed(1)` | Selected stock header — percentage change display |

**NOT changed on these lines** (non-percentage values on the same lines):
- `result.change.toFixed(2)` (line 167) — dollar change, not percentage
- `selectedStock.change.toFixed(2)` (line 266) — dollar change, not percentage

2 changes.

---

## Explicitly NOT changed

These `toFixed(2)` / `decimals: 2` instances are intentionally kept because they format non-percentage values:

| File | Line(s) | Reason |
|------|---------|--------|
| stock-lookup/helpers.ts | 37, 51, 67, 87-92 | Generic numeric ratios, dollar market cap |
| stock-lookup/OverviewTab.tsx | 32, 50, 77 | Beta, Sharpe ratio, correlation — all ratios |
| StockLookup.tsx | 65, 165, 263 | Beta display, dollar prices, dollar change |
| stock-lookup/FundamentalsTab.tsx | 110 | D/E ratio |
| stock-lookup/TechnicalsTab.tsx | 37, 56, 93 | MACD, dollar support/resistance |
| stock-lookup/PortfolioFitTab.tsx | 174 | Dollar reference price |
| HedgeWorkflowDialog.tsx | 524, 659 | Correlation, dollar price |
| HedgingAdapter.ts | 74, 80 | Beta display |
| RiskMetricsContainer.tsx | 154 | Beta coefficient (formatNumber) |
| useOverviewMetrics.ts | 63 | Sharpe ratio — already `formatNumber(..., { decimals: 2 })`, correct |
| EfficientFrontierTab.tsx | 90 | Chart domain bounds |
| AssetAllocation.tsx | 389 | Dollar price |
| AssetAllocationContainer.tsx | 245 | Numeric rounding |
| StressTestsTab.tsx | 206, 223 | Beta display, leverage ratio |
| RiskAnalysisModernContainer.tsx | 250 | Beta display |
| PerformanceAdapter.ts | 1062-1063, 1071-1072 | Beta, R-squared, Sharpe — already `formatNumber(..., { decimals: 2 })`, correct |
| RealizedPerformanceAdapter.ts | 222-223, 229-230 | Beta, R-squared, Sharpe — already `formatNumber(..., { decimals: 2 })`, correct |
| formatting.test.ts | 23 | Test for `decimals: 2` option — keep test as-is |

---

## Verification

```bash
cd frontend && pnpm typecheck && pnpm test --run
```

No test logic changes needed. The single test that asserts `decimals: 2` output (`formatting.test.ts` line 23) tests the formatting function option itself, not the UI default, so it stays.

---

## Summary

| # | File | Changes |
|---|------|---------|
| 1 | `ui/.../percentage-badge.tsx` | 1 |
| 2 | `app-platform/.../formatting.ts` | 1 (new function) |
| 2b | `chassis/.../formatting.ts` | 1 (re-export) |
| 3 | `ui/.../performance/helpers.ts` | 3 |
| 4 | `ui/.../strategy/helpers.tsx` | 1 |
| 5 | `ui/.../stock-lookup/helpers.ts` | 5 |
| ~~6~~ | ~~PerformanceHeaderCard.tsx~~ | ~~SKIP — already decimals: 1~~ |
| ~~7~~ | ~~RiskAnalysisTab.tsx~~ | ~~SKIP — already decimals: 1~~ |
| ~~8~~ | ~~BenchmarksTab.tsx~~ | ~~SKIP — already decimals: 1~~ |
| 9 | `ui/.../performance/AttributionTab.tsx` | 8 |
| ~~10~~ | ~~PeriodAnalysisTab.tsx~~ | ~~SKIP — already decimals: 1~~ |
| 11 | `ui/.../strategy/PerformanceTab.tsx` | 18 |
| 12 | `ui/.../overview/useOverviewMetrics.ts` | 1 |
| 13 | `ui/.../HedgeWorkflowDialog.tsx` | 2 |
| 14 | `ui/.../scenario/OptimizationsTab.tsx` | 3 |
| 15 | `ui/.../modern/RiskMetricsContainer.tsx` | 1 |
| 16 | `connectors/.../PerformanceAdapter.ts` | 6 |
| 17 | `connectors/.../RealizedPerformanceAdapter.ts` | 6 |
| 18 | `connectors/.../RiskAnalysisAdapter.ts` | 2 |
| 19 | `connectors/.../useAnalysisReport.ts` | 3 |
| 20 | `connectors/.../registry.ts` | 1 |
| 21 | `ui/.../portfolio/StockLookup.tsx` | 2 |
| | **Total** | **~65 changes across 17 files (+ 1 re-export)** |

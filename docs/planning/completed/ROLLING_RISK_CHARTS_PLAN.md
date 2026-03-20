# Repurpose Risk Analysis Tab: Rolling Sharpe & Volatility Charts

## Context
The Risk Analysis tab in the Performance view overlaps heavily with the Benchmarks tab — Max Drawdown, Sortino, Sharpe, and Tracking Error all appear in both. The backend already computes `rolling_sharpe` and `rolling_volatility` (12-month trailing window, monthly) and the PerformanceAdapter already embeds them as `rollingSharpe` and `rollingVol` in each `performanceTimeSeries` point — but the frontend never surfaces them. Repurposing the Risk Analysis tab to show these rolling time series charts makes it genuinely useful and non-redundant.

## Data Path (already exists)
1. **Backend**: `performance_metrics_engine.py` → `rolling_sharpe` + `rolling_volatility` dicts (date→value)
2. **Adapter**: `PerformanceAdapter.ts:787-788` → merged into `performanceTimeSeries[].rollingSharpe` / `.rollingVol`
3. **Container GAP**: `PerformanceViewContainer.tsx:314-320` strips these fields during time series mapping — only passes `date`, `portfolioValue`, `benchmarkValue`, `portfolioReturn`, `benchmarkReturn`
4. **UI**: `RiskAnalysisTab.tsx` currently shows static metric tiles

## Changes

### 1. Thread rolling data through PerformanceViewContainer
**Path:** `frontend/packages/ui/src/components/dashboard/views/modern/PerformanceViewContainer.tsx`

In the `timeSeries` mapping (~line 314-320), add rolling fields:
```typescript
rollingSharpe: p.rollingSharpe ?? null,
rollingVol: p.rollingVol ?? null,
```

Add to `PerformanceTimeSeriesItem` interface (~line 80):
```typescript
rollingSharpe?: number | null;
rollingVol?: number | null;
```

Add to `MappedPerformanceViewData.timeSeries` item type.

### 2. Update PerformanceTimeSeriesPoint type
**Path:** `frontend/packages/ui/src/components/portfolio/performance/types.ts`

Add to `PerformanceTimeSeriesPoint` (~line 19, the type for `PerformanceViewData.timeSeries[]`):
```typescript
rollingSharpe?: number | null;
rollingVol?: number | null;
```

This is the type that flows through `data.timeSeries` into `PerformanceView`.

### 3. Pass timeSeries directly to RiskAnalysisTab
**Path:** `frontend/packages/ui/src/components/portfolio/PerformanceView.tsx`

Pass `data?.timeSeries` as a new prop to `<RiskAnalysisTab />` alongside existing `performanceData`. Update `RiskAnalysisTabProps`:
```typescript
interface RiskAnalysisTabProps {
  performanceData: PerformanceData;          // kept — for drawdown details
  timeSeries?: PerformanceTimeSeriesPoint[];  // added — for rolling charts
}
```

Use the shared `PerformanceTimeSeriesPoint` type (after extending it in Step 2) rather than an inline ad-hoc type.

### 4. Rewrite RiskAnalysisTab with two Recharts line charts
**Path:** `frontend/packages/ui/src/components/portfolio/performance/RiskAnalysisTab.tsx`

Replace the top metric tile grid with two rolling charts, and retain the existing drawdown details card below.

**Layout:**
- Keep outer `Card variant="glassTinted"` + `SectionHeader icon={AlertTriangle} title="Rolling Risk Analysis" colorScheme="red" size="sm"`
- Two charts stacked vertically, each in a sub-card
- Existing drawdown details card retained below the charts

**Chart 1 — Rolling Sharpe Ratio:**
- Recharts `LineChart` inside `ChartContainer` (which already wraps in `ResponsiveContainer` — do NOT double-wrap), height ~200px
- Single line: `rollingSharpe` values over time
- XAxis: dates (formatted monthly via `formatChartDate`)
- YAxis: ratio values
- Reference line at 0 (dashed)
- Use `ChartContainer` + `ChartTooltip` blocks (matching IncomeBarChart pattern)
- Use `chartSemanticColors` / `getAxisPreset` from `chart-theme`

**Chart 2 — Rolling Volatility:**
- Same layout as above
- Single line: `rollingVol` values over time (already in %)
- YAxis: percentage values

**Data filtering:** Each chart uses its own filtered dataset:
- `rollingSharpeSeries = timeSeries.filter(p => p.rollingSharpe != null)`
- `rollingVolSeries = timeSeries.filter(p => p.rollingVol != null)`

Backend is asymmetric: Sharpe drops zero-vol windows (NaN), while volatility can legitimately be 0.0. So each chart renders independently from its own filtered array.

**Empty states:**
- Each chart gets its own empty state if its filtered array is empty
- Tab-level empty state only if BOTH arrays are empty: "Rolling metrics require at least 12 months of data"

**Drawdown details retained:**
- Keep the existing drawdown details card (Duration, Recovery Time, Peak Date) below the charts
- `performanceData` prop stays for drawdown data; `timeSeries` prop added for chart data

## Reference Files
- `frontend/packages/ui/src/components/dashboard/cards/IncomeBarChart.tsx` — pattern for Recharts + ChartContainer + chart-theme
- `frontend/packages/ui/src/lib/chart-theme.ts` — `chartSemanticColors`, `formatChartDate`, `getAxisPreset`
- `frontend/packages/ui/src/components/blocks/chart-container.tsx` — `ChartContainer`, `ChartTooltip`
- `frontend/packages/connectors/src/adapters/PerformanceAdapter.ts:787-788` — source of rolling data

## Files to Modify
- `frontend/packages/ui/src/components/dashboard/views/modern/PerformanceViewContainer.tsx` — thread rolling fields
- `frontend/packages/ui/src/components/portfolio/performance/types.ts` — add timeSeries type
- `frontend/packages/ui/src/components/portfolio/PerformanceView.tsx` — pass timeSeries prop
- `frontend/packages/ui/src/components/portfolio/performance/RiskAnalysisTab.tsx` — rewrite with charts

## Date Format Note
The rolling charts use the same `timeSeries[].date` field that the existing Performance Trend chart already renders successfully. No additional date manipulation is needed — just pass the `date` field as the XAxis dataKey. Any pre-existing date format issues in the adapter (`month + '-01'` at PerformanceAdapter.ts:781) affect all performance charts equally and are out of scope for this change.

## Verification
1. TypeScript: `cd frontend && npx tsc --noEmit --project packages/ui/tsconfig.json`
2. Visual: Performance → Risk Analysis tab shows two line charts (Rolling Sharpe + Rolling Volatility) with drawdown details below
3. Empty state: for portfolios with < 12 months data, shows appropriate message
4. Charts use consistent theming (chart-theme colors, axis presets, ChartTooltip)
5. Edge case: portfolio with zero-vol rolling windows still shows Rolling Volatility chart even if Rolling Sharpe has no points

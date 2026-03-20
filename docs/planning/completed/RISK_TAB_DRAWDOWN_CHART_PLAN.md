# Enhance Risk Analysis Tab: Drawdown Chart

## Context
The Risk Analysis tab has rolling Sharpe and rolling volatility charts, plus static drawdown metric tiles. Replace the static tiles with a **drawdown time series area chart** — much more visual and informative than 4 numbers.

## Data Availability

### Drawdown time series
- PerformanceAdapter (hypothetical path) correctly computes drawdown from peak via `calculateDrawdown()` at line 789/939
- **RealizedPerformanceAdapter line 63 is WRONG** — it computes cumulative return `((portfolioValue - 100000) / 100000) * 100`, not drawdown from peak. Must be fixed to track peak value and compute `((portfolioValue - peakValue) / peakValue) * 100`
- NOT currently in `PerformanceTimeSeriesPoint` type or container mapping — needs threading (same pattern as rolling data)


## Changes

### 1. Fix RealizedPerformanceAdapter drawdown calculation
**`frontend/packages/connectors/src/adapters/RealizedPerformanceAdapter.ts`**

In `buildTimeSeries()`, track peak portfolio value and compute proper drawdown:
```typescript
let peakValue = 100000;
// inside the map:
peakValue = Math.max(peakValue, portfolioValue);
drawdown: peakValue > 0 ? ((portfolioValue - peakValue) / peakValue) * 100 : 0,
```
This matches the `calculateDrawdown()` pattern in PerformanceAdapter.

### 2. Thread `drawdown` through the time series
**`frontend/packages/ui/src/components/portfolio/performance/types.ts`**
- Add `drawdown?: number | null` to `PerformanceTimeSeriesPoint` (line ~28)

**`frontend/packages/ui/src/components/dashboard/views/modern/PerformanceViewContainer.tsx`**
- Add `drawdown` to `PerformanceTimeSeriesItem` interface
- Add `drawdown` to `MappedPerformanceViewData` timeSeries item type
- Add to timeSeries mapping: `drawdown: p.drawdown ?? null`

### 2. Replace drawdown tiles with drawdown area chart
**`frontend/packages/ui/src/components/portfolio/performance/RiskAnalysisTab.tsx`**

Replace the 4 metric tiles with a drawdown area chart:
- Recharts `AreaChart` inside `ChartContainer` (height ~160, more compact than the rolling charts)
- `Area` with dataKey="drawdown", red fill with gradient (deeper red = deeper drawdown)
- XAxis with dates, YAxis with percent (all negative values)
- Title: "Drawdown from Peak" with subtitle "Peak-to-trough decline over time"
- Filter data: `drawdownSeries = timeSeries.filter(p => p.drawdown != null)`
- Always negative or zero — no reference line needed, but can add one at 0

Keep key stats as a compact inline row below the chart:
- Max Drawdown, Duration, Recovery, Peak Date — as small `text-xs` key-value pairs in a flex row

**Important**: The drawdown chart must render even when rolling metrics are unavailable (< 12 months data). The `hasNoRollingMetrics` empty state only gates the rolling charts, not the drawdown section.

## Reference Files
- `frontend/packages/ui/src/components/portfolio/overview/PerformanceTrendChart.tsx` — Area chart pattern with gradient fill
- `frontend/packages/connectors/src/adapters/PerformanceAdapter.ts:789,939` — correct drawdown calculation via `calculateDrawdown()`

## Files to Modify
- `frontend/packages/connectors/src/adapters/RealizedPerformanceAdapter.ts` — fix drawdown calculation
- `frontend/packages/ui/src/components/portfolio/performance/types.ts` — add drawdown to time series type
- `frontend/packages/ui/src/components/dashboard/views/modern/PerformanceViewContainer.tsx` — thread drawdown
- `frontend/packages/ui/src/components/portfolio/performance/RiskAnalysisTab.tsx` — drawdown chart + compact stats

## Data Path
- **PerformanceAdapter** (hypothetical path): correctly computes drawdown via `calculateDrawdown()` at line 939. Field already in chassis type at `types.ts:175`.
- **RealizedPerformanceAdapter** (realized path, BUG): line 63 computes cumulative return, not drawdown from peak. Must be fixed.
- **Resolver**: switches between adapters at `registry.ts:417`. Both must emit correct `drawdown`.
- **PerformanceViewContainer**: drops `drawdown` in time series mapping at lines 80, 146, 314. Must thread through.
- **PerformanceTimeSeriesPoint**: missing `drawdown` field at `types.ts:21`. Must add.

## Verification
1. TypeScript: `cd frontend && pnpm typecheck` (covers all packages including connectors)
2. Visual: Risk Analysis tab shows drawdown area chart (red gradient, negative values) below rolling charts
3. All 4 key stats (Max Drawdown, Duration, Recovery, Peak Date) shown as compact text below drawdown chart
4. Short-history regression: portfolio with < 12 months data → rolling charts show empty state, but drawdown chart + compact stats still render
5. Drawdown empty state: if `drawdownSeries` is empty (no time series data at all), show appropriate message

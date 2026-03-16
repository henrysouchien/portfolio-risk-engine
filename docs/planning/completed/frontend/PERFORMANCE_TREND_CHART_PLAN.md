# Performance Trend Chart Replacement Plan

**Status**: READY TO EXECUTE (v2 — Codex review fixes applied)
**Date**: 2026-03-16
**Finding**: R2 follow-up — replace custom SVG SparklineChart with Recharts AreaChart
**Scope**: 4 files changed, 1 new component

---

## Problem

The Performance Trend chart on the dashboard uses `SparklineChart` — a hand-rolled SVG component with no axes, no date labels, no grid, no real tooltip. Even at 180px height it looks amateurish next to the Recharts charts used everywhere else in the app (PriceChartTab, PerformanceTab, etc.).

## Design Direction

**Aesthetic**: Refined financial terminal — clean, high-density, professional. NOT flashy or decorative. Think Bloomberg meets Carta.

**Key design choices**:
- Recharts `AreaChart` with emerald/red gradient fill (matches positive/negative returns)
- Subtle horizontal grid lines (existing `getGridPreset()` — dashed, 50% opacity)
- X-axis: month abbreviations ("Jan", "Feb", "Mar") — NOT full dates
- Y-axis: percentage with sign (+10.8%, -1.6%) — right-aligned, muted
- Tooltip: existing `ChartTooltip` component (frosted glass card with date + return %)
- Optional benchmark dashed line (SPY) when data available
- Zero reference line (subtle dashed) to anchor positive/negative
- Header: "Performance Trend" left, cumulative return badge right, "Portfolio" + optional "Benchmark" legend below
- Height: 200px via `ChartContainer` (responsive)
- Card: existing `glassTinted` variant

---

## Implementation

### Step 1: Create `PerformanceTrendChart` component

**New file**: `frontend/packages/ui/src/components/portfolio/overview/PerformanceTrendChart.tsx`

```tsx
import { cn } from "@risk/chassis"
import { Area, AreaChart, CartesianGrid, ReferenceLine, Line, Tooltip, XAxis, YAxis } from "recharts"
import { ChartContainer, ChartTooltip } from "../../blocks"
import { Card } from "../../ui/card"
import {
  chartSemanticColors,
  getCSSColor,
  getAxisPreset,
  getGridPreset,
  getReferenceLinePreset,
  formatPercent,
  formatChartDate,
} from "../../../lib/chart-theme"
import type { TrendDataPoint } from "./types"

interface PerformanceTrendChartProps {
  data: TrendDataPoint[]
  showBenchmark?: boolean
  benchmarkLabel?: string   // e.g., "S&P 500"
}
```

**Component internals**:
- Compute `isPositive` from last data point's `portfolioReturn`
- Use `chartSemanticColors.positive()` for emerald, `chartSemanticColors.negative()` for red
- Benchmark line color: `getCSSColor("--muted-foreground")`, dashed (`strokeDasharray="5 3"`), 1.5px
- Gradient: `linearGradient` from 30% opacity at top → 0% at bottom
- Zero reference line: `getReferenceLinePreset()` at `y={0}`
- X-axis: `tickFormatter` using `formatChartDate(value, "monthly")` — shows "Jan 2026" (matches existing `chart-theme.ts:167` output)
- Y-axis: `tickFormatter` using `formatPercent(value, { decimals: 1 })` — shows "+6.7%"
- Y-axis `domain`: Use computed domain that always includes 0:
  ```tsx
  const minReturn = Math.min(0, ...data.map(d => d.portfolioReturn))
  const maxReturn = Math.max(0, ...data.map(d => d.portfolioReturn))
  // domain={[minReturn - 1, maxReturn + 1]} ensures zero line is always visible
  ```
- Tooltip: `<ChartTooltip defaultFormat="percent" dateGranularity="monthly" />` — explicitly set monthly granularity

**Card wrapper** (in the same component):
```tsx
<Card variant="glassTinted" className="p-5 rounded-2xl">
  {/* Header row */}
  <div className="flex items-center justify-between mb-1">
    <p className="text-sm font-medium text-foreground/70 tracking-tight">
      Performance Trend
    </p>
    <span className={cn(
      "text-sm font-semibold tabular-nums",
      isPositive ? "text-emerald-600" : "text-red-600"
    )}>
      {formatPercent(latestReturn)}
    </span>
  </div>

  {/* Legend row */}
  <div className="flex items-center gap-4 mb-3">
    <span className="text-xs text-muted-foreground">Cumulative return</span>
    <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
      <span className={cn("inline-block w-3 h-[2px] rounded-full",
        isPositive ? "bg-emerald-500" : "bg-red-500"
      )} />
      Portfolio
    </span>
    {showBenchmark && (
      <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <span className="inline-block w-3 h-[2px] rounded-full bg-muted-foreground/50 border-b border-dashed" />
        {benchmarkLabel ?? "Benchmark"}
      </span>
    )}
  </div>

  {/* Chart */}
  <ChartContainer height={200} minHeight={160} isEmpty={!data?.length}>
    <AreaChart data={data} margin={{ top: 5, right: 5, bottom: 0, left: -10 }}>
      ...
    </AreaChart>
  </ChartContainer>
</Card>
```

### Step 2: Update container to pass full time series

**File**: `frontend/packages/ui/src/components/dashboard/views/modern/PortfolioOverviewContainer.tsx`

**Current** (line 84-88):
```tsx
const performanceSparkline = useMemo(() => {
  const ts = perfData?.performanceTimeSeries;
  if (!ts || ts.length < 2) return undefined;
  return ts.map((p: { portfolioCumReturn: number }) => p.portfolioCumReturn);
}, [perfData]);
```

**Change to** — pass structured data with dates:
```tsx
const performanceTrendData = useMemo(() => {
  const ts = perfData?.performanceTimeSeries;
  if (!ts || ts.length < 2) return undefined;
  return ts.map((p: { date: string; portfolioCumReturn: number; benchmarkCumReturn?: number }) => ({
    date: p.date,
    portfolioReturn: p.portfolioCumReturn,
    benchmarkReturn: p.benchmarkCumReturn,
  }));
}, [perfData]);
```

Also update the prop passed to `PortfolioOverview`:
```tsx
<PortfolioOverview
  ...
  performanceTrendData={performanceTrendData}  // NEW: replaces performanceSparkline
  ...
/>
```

### Step 3: Update PortfolioOverview to use new component

**File**: `frontend/packages/ui/src/components/portfolio/PortfolioOverview.tsx`

Replace the SparklineChart section (lines 80-113) with:
```tsx
{performanceTrendData && (
  <PerformanceTrendChart
    data={performanceTrendData}
    showBenchmark
    benchmarkLabel={data?.summary?.benchmarkTicker ?? "SPY"}
  />
)}
```

Notes:
- Remove the `length > 1` guard — let `ChartContainer isEmpty={!data?.length}` handle empty/single-point states internally
- `showBenchmark` is always true since the adapter always emits `benchmarkCumReturn` — the component handles missing values gracefully
- Import `PerformanceTrendChart` directly: `import { PerformanceTrendChart } from "./overview/PerformanceTrendChart"`
- Remove the `SparklineChart` import (line 2) if no longer used in this file
- Update props interface to accept `performanceTrendData` instead of `performanceSparkline`

### Step 4: Update types

**File**: `frontend/packages/ui/src/components/portfolio/overview/types.ts`

Add `TrendDataPoint` type, update `PortfolioOverviewProps`, and export from barrel:
```tsx
export interface TrendDataPoint {
  date: string              // "YYYY-MM-01" format from PerformanceAdapter
  portfolioReturn: number   // cumulative return in % (e.g., 6.7)
  benchmarkReturn?: number  // benchmark cumulative return (always present from adapter)
}

// In PortfolioOverviewProps — replace performanceSparkline:
performanceTrendData?: TrendDataPoint[]
```

Also add to `overview/index.ts` barrel export:
```tsx
export { PerformanceTrendChart } from "./PerformanceTrendChart"
```

---

## Files Changed

| File | Change |
|------|--------|
| `frontend/packages/ui/src/components/portfolio/overview/PerformanceTrendChart.tsx` | **NEW** — Recharts AreaChart component |
| `frontend/packages/ui/src/components/portfolio/overview/types.ts` | Add `TrendDataPoint`, update `PortfolioOverviewProps` |
| `frontend/packages/ui/src/components/portfolio/overview/index.ts` | Add barrel export for `PerformanceTrendChart` |
| `frontend/packages/ui/src/components/portfolio/PortfolioOverview.tsx` | Replace SparklineChart with PerformanceTrendChart, update import |
| `frontend/packages/ui/src/components/dashboard/views/modern/PortfolioOverviewContainer.tsx` | Pass full time series with dates, rename prop |

## DO NOT Touch

- `sparkline-chart.tsx` — still used elsewhere, don't delete
- Any backend files
- Any adapter files

## Testing

1. Visual: Dashboard chart should show proper axes, dates, grid, tooltip on hover
2. Positive returns: emerald gradient fill, green return badge
3. Negative returns: red gradient fill, red return badge
4. Benchmark line: dashed line when benchmark data available
5. Responsive: chart resizes correctly on window resize
6. Empty state: "No data available" via ChartContainer when no perf data
7. TypeScript: zero errors

## Data Shape Reference

The `perfData.performanceTimeSeries` array from `PerformanceAdapter.ts:323` contains:
```json
{
  "date": "2025-06-01",
  "portfolioCumReturn": 6.7,
  "benchmarkCumReturn": 4.2,
  "portfolioDailyReturn": 0.3
}
```

Dates are formatted as `YYYY-MM-01` (monthly granularity, adapter line 781).
`benchmarkCumReturn` is always present in adapter output (not optional at runtime).
We map: `date` → `date`, `portfolioCumReturn` → `portfolioReturn`, `benchmarkCumReturn` → `benchmarkReturn`.

## Codex Review Fixes (v2)

Issues fixed from Codex round 1:
1. **Empty state**: Removed `length > 1` guard from parent — let `ChartContainer isEmpty` handle it
2. **Y-axis domain**: Computed domain that always includes 0 so zero reference line is always visible
3. **Missing import**: Added `cn` import from `@risk/chassis`, added barrel export in `overview/index.ts`
4. **Date format**: Clarified `formatChartDate(value, "monthly")` returns "Jan 2026" (month+year), set `dateGranularity="monthly"` on tooltip
5. **Benchmark always present**: `showBenchmark` defaults to true since adapter always emits `benchmarkCumReturn`

# Performance View Bottom Tabs Restructure

## Context

The Performance view has 4 bottom tabs (Attribution, Benchmarks, Risk Analysis, Period Analysis) that feel disconnected from the top section's narrative. The top tells a story (metrics → money), but the bottom tabs feel like a data dump appendix. Additionally:
- **Benchmarks tab** has a cumulative chart redundant with Overview, plus Sharpe already shown in header
- **Risk Analysis tab** duplicates content better suited to the Factors page
- **Attribution** and **Period Analysis** are useful and non-redundant

Goal: Tighten the bottom section to 3 tabs with no redundancy, and visually connect it to the top narrative.

## Changes

### Step 1: Update type — `types.ts`
**File:** `frontend/packages/ui/src/components/portfolio/performance/types.ts`
- **Line 5:** Remove `"drawdown"` from `PerformanceTab` union → `"attribution" | "benchmarks" | "monthly"`

### Step 2: Remove Risk Analysis tab + add section header — `PerformanceView.tsx`
**File:** `frontend/packages/ui/src/components/portfolio/PerformanceView.tsx`
- **Line 8:** Remove `AlertTriangle` from lucide import (only used by Risk Analysis trigger)
- **Line 19:** Remove `RiskAnalysisTab` from performance barrel import
- **Line 146:** Change `grid-cols-4` → `grid-cols-3`
- **Lines 161-167:** Delete Risk Analysis `TabsTrigger` block
- **Lines 200-205:** Delete Risk Analysis `TabsContent` block
- **Lines 191-198:** Simplify BenchmarksTab call — remove `selectedPeriod`, `selectedBenchmark`, `timeSeries` props (only used by the chart being removed)
- **Before line 145:** Add a section header to bridge the narrative:
  ```tsx
  <div className="mb-2 text-xs font-semibold uppercase tracking-widest text-muted-foreground">Return Decomposition</div>
  ```
  (Simple text label matching existing style, not a full SectionHeader block — keeps it lightweight)

### Step 3: Slim down BenchmarksTab — `BenchmarksTab.tsx`
**File:** `frontend/packages/ui/src/components/portfolio/performance/BenchmarksTab.tsx`
- **Strip dead imports:** Remove `useId`, all recharts imports, `ChartContainer`/`ChartTooltip`, entire chart-theme import block, `getSharpeStrength`, `PerformancePeriod`/`PerformanceTimeSeriesPoint` types
- **Simplify interface:** `BenchmarksTabProps` → just `{ performanceData: PerformanceData }`
- **Simplify function:** Remove all chart setup variables (gradient IDs, tick calculations, color logic, ~50 lines)
- **Remove Sharpe from `riskAdjustedMetrics`:** Array goes from 4 → 3 items (Sortino, Info Ratio, Calmar)
- **Delete chart JSX:** Remove lines 199-297 (entire cumulative chart section)
- **Update first grid:** `md:grid-cols-4` → `md:grid-cols-3` (now 3 items)
- **Update SectionHeader title:** "Performance vs Benchmarks" → "Benchmark Metrics"

### Step 4: Remove barrel export — `index.ts`
**File:** `frontend/packages/ui/src/components/portfolio/performance/index.ts`
- **Line 6:** Remove `export { RiskAnalysisTab } from "./RiskAnalysisTab"`
- Do NOT delete `RiskAnalysisTab.tsx` file

## Files Modified
| File | Change |
|------|--------|
| `performance/types.ts` | Remove "drawdown" from type |
| `PerformanceView.tsx` | Remove tab, simplify BenchmarksTab call, add section label |
| `performance/BenchmarksTab.tsx` | Remove chart + Sharpe, clean imports (~130 lines removed) |
| `performance/index.ts` | Remove barrel export |

## Verification
1. `npx tsc --noEmit` from frontend workspace — catches any stale "drawdown" references or missing props
2. Visual check in browser: Performance page should show 3 tabs, Benchmarks should show 7 metrics (no chart), section label above tabs
3. Confirm no console errors in dev tools

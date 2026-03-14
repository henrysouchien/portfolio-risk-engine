# Frontend Phase 5 Polish: Chart Polish Batch

## Context
Continuing Phase 5 Visual Polish. Previous batches applied glassTinted, hover-lift-subtle, and stagger animations across all views. This batch migrates hard-coded chart colors to the chart-theme system.

Of 4 Recharts files, 2 are already fully integrated (PerformanceTab.tsx, PriceChartTab.tsx) and 1 is a utility wrapper (ChartContainer). Only MonteCarloTab.tsx has hard-coded hex colors.

All files under `frontend/packages/ui/src/components/portfolio/scenario/`.

## Changes

### 1. Migrate MonteCarloTab.tsx SVG gradient colors to chartSemanticColors

**Current** (lines 173-189): 4 `<linearGradient>` definitions use hard-coded hex colors:
- `#ef4444` (red-500) for P5 gradient
- `#f59e0b` (amber-500) for P25 gradient
- `#10b981` (emerald-500) for P75 gradient
- `#10b981` (emerald-500) for P95 gradient

**Change**: Replace hex values with `chartSemanticColors` calls:
- P5 (worst): `chartSemanticColors.negative()` (replaces `#ef4444`)
- P25: `chartSemanticColors.warning()` (replaces `#f59e0b`)
- P75: `chartSemanticColors.positive()` (replaces `#10b981`)
- P95: `chartSemanticColors.positive()` (replaces `#10b981`)

Import `chartSemanticColors` from `../../../lib/chart-theme` (add to existing import on line 5).

### 2. Migrate MonteCarloTab.tsx Area stroke colors

**Current** (lines 209-248): 5 `<Area>` components use hard-coded stroke colors:
- P95 stroke: `#10b981` → `chartSemanticColors.positive()`
- P75 stroke: `#10b981` → `chartSemanticColors.positive()`
- P50 stroke: `#3b82f6` → `chartSemanticColors.neutral()` (median line, blue)
- P25 stroke: `#f59e0b` → `chartSemanticColors.warning()`
- P5 stroke: `#ef4444` → `chartSemanticColors.negative()`

### 3. Extract colors to local constants

To avoid calling `chartSemanticColors.*()` multiple times (once in gradient defs, once in Area strokes), extract to local constants at the top of the render body (after `grid`):

```typescript
const mcColors = {
  best: chartSemanticColors.positive(),
  median: chartSemanticColors.neutral(),
  caution: chartSemanticColors.warning(),
  worst: chartSemanticColors.negative(),
}
```

Then reference `mcColors.best`, `mcColors.worst`, etc. in both gradients and Area strokes.

## Dropped
- No changes to PerformanceTab.tsx (already fully integrated with chart-theme)
- No changes to PriceChartTab.tsx (already fully integrated with chart-theme)
- No changes to ChartContainer.tsx (utility wrapper, no chart colors)
- No custom Legend component — the default Recharts Legend already inherits the axis font from the theme preset. Custom legend styling is cosmetic-only with diminishing returns.
- No gradient area fill additions to PerformanceTab LineChart — line charts with two series (portfolio vs benchmark) are clearer without area fills that would overlap and obscure each other.

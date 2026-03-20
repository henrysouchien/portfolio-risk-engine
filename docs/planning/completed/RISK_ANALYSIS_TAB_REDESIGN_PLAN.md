# Redesign Risk Analysis Tab to Match Other Performance Tabs

## Context
The Risk Analysis tab in the Performance view uses a different design language than its sibling tabs (Attribution, Benchmarks, Period Analysis). It has custom gradient backgrounds (`gradient-risk`, `gradient-sophisticated`), raw `h3` headings, and large `text-3xl` colored values — while the other tabs consistently use `Card variant="glassTinted"`, `SectionHeader` blocks, `DataTable` components, and structured metric grids with `hover-lift-subtle`. The goal is to bring the Risk Analysis tab into visual alignment with the established pattern.

## Current State (RiskAnalysisTab.tsx)
- Single `Card` wrapper containing a 2-column grid
- Left: "Maximum Drawdown" — red gradient background, `text-3xl` red value, key-value detail rows (Duration, Recovery Time, Peak Date)
- Right: "Volatility Metrics" — `gradient-sophisticated` background, `text-3xl` neutral value, single Tracking Error row
- Custom `h3` typography instead of `SectionHeader`

## Target Design Pattern (from BenchmarksTab.tsx / AttributionTab.tsx)
- `Card variant="glassTinted"` with `SectionHeader icon={...} colorScheme="..." size="sm"`
- Metric cards: `rounded-xl border border-neutral-200/60 bg-neutral-50 p-3` with `hover-lift-subtle`
- Values: `text-base font-bold` or `text-2xl font-bold`, not `text-3xl`
- Small uppercase labels: `text-xs font-medium uppercase tracking-wide text-neutral-500`
- Tooltips on hover for explanatory content
- Consistent use of `StatPair` where applicable

## Redesign Plan

### Single file: `frontend/packages/ui/src/components/portfolio/performance/RiskAnalysisTab.tsx`

Replace the current implementation with:

1. **Outer wrapper**: Keep `Card variant="glassTinted" hover="lift"` + `SectionHeader icon={AlertTriangle} title="Risk & Drawdown Analysis" colorScheme="red" size="sm"` (already correct)

2. **Top row — 4 key metrics in a grid** (matching BenchmarksTab's `grid-cols-2 md:grid-cols-4` metric tiles):
   - Max Drawdown (red accent, `formatOptionalPercent`)
   - Volatility (neutral, `formatOptionalPercent`)
   - Sortino Ratio (neutral, `formatOptionalNumber` — already in PerformanceData)
   - Tracking Error (neutral, `formatOptionalPercent` — may show `--` if unmapped)

   Each tile: `rounded-xl border border-neutral-200/60 bg-neutral-50 p-3 hover-lift-subtle`
   - Value: `text-base font-bold` with semantic color
   - Label: `text-xs font-medium uppercase tracking-wide text-neutral-500`
   - Tooltip on hover with explanation

3. **Bottom section — Drawdown Details card**:
   - Small card with `rounded-xl border border-red-100/60 bg-red-50/30 p-4`
   - Title: "Drawdown Details" in `text-sm font-semibold`
   - Key-value rows for Duration, Recovery Time, Peak Date using simple flex rows with `text-sm`
   - Consistent with the detailed metric pattern

### Data from `PerformanceData` type (already available, no plumbing needed):
- `maxDrawdown`, `volatility`, `trackingError`, `sortino` — metric tiles
- `drawdownDurationDays`, `drawdownRecoveryDays`, `drawdownPeakDate` — detail rows
- Note: `downsideDeviation` is NOT in PerformanceData UI types (exists in adapter but not plumbed through). Use `sortino` instead.
- Note: `sortino` and `trackingError` may be null/undefined if not plumbed through PerformanceViewContainer. This is not a regression — the current tab already renders `trackingError` as `--` via `formatOptionalPercent`. The `formatOptional*` helpers handle null gracefully.

## Reference Files
- `frontend/packages/ui/src/components/portfolio/performance/BenchmarksTab.tsx` — target design pattern (metric grid + card structure)
- `frontend/packages/ui/src/components/portfolio/performance/AttributionTab.tsx` — target design pattern (SectionHeader + DataTable)
- `frontend/packages/ui/src/components/portfolio/performance/helpers.ts` — shared formatters
- `frontend/packages/ui/src/components/portfolio/performance/types.ts` — PerformanceData type

## Verification
1. TypeScript: `cd frontend && npx tsc --noEmit --project packages/ui/tsconfig.json`
2. Visual: Performance → Risk Analysis tab should now match the card/grid style of Attribution and Benchmarks tabs
3. All existing data (drawdown, volatility, tracking error, duration, recovery, peak date) still displayed

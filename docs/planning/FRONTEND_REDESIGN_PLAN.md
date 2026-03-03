# Frontend Full Redesign Plan

## Context

The frontend has 7 monolith view components (2,300 / 1,800 / 1,600 / 1,100 / 1,000 / 1,000 / 900 lines) with zero sub-component extraction. The visual identity is "shadcn default" — premium CSS effects are defined but unused, Recharts are completely unstyled, and 49 shadcn components are unmodified. The goal is a full redesign: rethink layouts, information hierarchy, and visual language to feel like a premium financial analytics tool, not a template.

**Approach**: Horizontal-first (design system → decompose → polish) to avoid decompose-then-restyle double-work.

---

## Phase 1: Design System Foundation

Build the shared layer everything else depends on.

### 1a. Consolidated color/formatting utilities
- Merge duplicated color helpers from 6+ files into `packages/ui/src/lib/colors.ts`
- Expand `theme/colors.ts` beyond risk colors to include: change, performance, trend, sector colors
- Export typed helpers; deprecation re-exports from old locations

### 1b. Recharts theme layer
- Custom `<ChartTooltip>` with glass styling, typography, dark mode
- Custom axis presets (styled XAxis/YAxis with proper font, color, tick formatting)
- `<ChartContainer>` wrapper with consistent padding, responsive sizing, gradient fills
- Chart color palette from CSS variables (automatic dark mode)

### 1c. Expand block component library (4-6 new blocks)
- `<StatRow>` — horizontal key/value pair for detail panels
- `<DataTable>` — styled table wrapper with sorting/filtering (wrapping shadcn Table)
- `<TabPanel>` — consistent tab content wrapper with spacing + transitions
- `<AlertBanner>` — for AI insights and warnings
- `<ScoreRing>` — circular risk score visualization
- All blocks: dark mode via CSS variables, CVA variants, 7 color schemes

### 1d. Upgrade base shadcn components
- Extend shadcn Card with `variant="glass"` (applies `glass-premium`)
- `hover-lift-premium` on interactive cards
- `btn-premium` shimmer on primary buttons

**Key files**: `lib/colors.ts`, `lib/chart-theme.ts`, new blocks in `components/blocks/`, `components/ui/card.tsx`

---

## Phase 2: PortfolioOverview Decomposition

Flagship view (2,303 lines → ~200 line orchestrator). Sets the pattern for all others.

Extract to `components/portfolio/overview/`:
- `OverviewHeader.tsx` — title, last updated, refresh, settings trigger
- `MetricsGrid.tsx` — key metrics using `MetricCard` blocks
- `RiskScorePanel.tsx` — risk score visualization using `ScoreRing`
- `InsightsPanel.tsx` — AI insights using `AlertBanner`
- `ViewModeSelector.tsx` — compact/detailed/professional/institutional toggle
- Clean up `MetricData` interface (remove unused AI/institutional fields)

Apply Phase 1 blocks: MetricCard with color schemes, glass cards, hover-lift, stagger animations.

Container (`PortfolioOverviewContainer.tsx`) untouched.

---

## Phase 3: Performance + Holdings Decomposition

### PerformanceView (1,782 lines → `components/portfolio/performance/`)
- `PerformanceSummaryCards.tsx` — period return cards
- `PerformanceChart.tsx` — time series using chart theme
- `AttributionTable.tsx` — sector/factor attribution using `DataTable`
- `BenchmarkSelector.tsx` — extract cleanly
- Root orchestrates tabs, ~200 lines

### HoldingsView (1,031 lines → `components/portfolio/holdings/`)
- `HoldingsTable.tsx` — main table using `DataTable`
- `HoldingsSummaryBar.tsx` — aggregate metrics
- `HoldingDetailRow.tsx` — expandable position details
- `HoldingsFilters.tsx` — search, filter, sort
- Root ~150 lines

Remove inline mock data from both views.

---

## Phase 4: Risk + Scenario + Strategy + Stock Decomposition

### RiskAnalysis (942 lines → `components/portfolio/risk/`)
- `RiskOverviewCards.tsx`, `FactorExposurePanel.tsx`, `StressTestPanel.tsx`, `HedgingPanel.tsx`
- Root orchestrates 3 tabs, ~200 lines

### ScenarioAnalysis (1,648 lines → `components/portfolio/scenario/`)
- `PortfolioBuilder.tsx`, `HistoricalScenarios.tsx`, `StressTestRunner.tsx`, `MonteCarloPanel.tsx`
- Root orchestrates 5 tabs, ~250 lines

### StrategyBuilder (1,145 lines → `components/portfolio/strategy/`)
- `OptimizationForm.tsx`, `OptimizationResults.tsx`, `EfficientFrontierChart.tsx`
- Root ~200 lines

### StockLookup (1,036 lines → `components/portfolio/stock/`)
- `StockSearchBar.tsx`, `StockSummaryPanel.tsx`, `StockMetricsGrid.tsx`, `StockFactorPanel.tsx`
- Root ~200 lines

---

## Phase 5: Visual Polish Pass

Final sweep across all views for "Bloomberg meets modern SaaS" aesthetic.

- Glass effects: main panels `glass-premium`, secondary `glass-tinted`
- Hover interactions: `hover-lift-premium` / `hover-lift-subtle` by importance
- Animated borders: `morph-border` on key interactive sections
- Premium buttons: `btn-premium` shimmer on primary actions
- Entrance animations: `animate-stagger-fade-in` on grids/lists
- Dark mode audit: verify every view, fix hardcoded colors
- Typography: `text-balance-optimal` on headings, verify `clamp()` usage
- Chart polish: custom legends, branded tooltips, gradient area fills
- Prune any unused premium CSS

---

## Execution Notes

- Use `/frontend-design` skill for generating component code in each phase
- Each phase is a separate commit for clean rollback
- Container components never modified — only view components change
- New UI components go in `@risk/ui`; color utilities in `@risk/ui/lib`
- No component should exceed ~300 lines after decomposition
- ~40-50 focused components extracted from ~10,000 lines of monolith code

## Verification

- `pnpm typecheck` passes after each phase
- `pnpm lint` passes after each phase
- `pnpm build` succeeds after each phase
- Visual inspection in browser (light + dark mode) after each phase
- Existing Vitest tests continue to pass

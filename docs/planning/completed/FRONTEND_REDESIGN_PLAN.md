# Frontend Full Redesign Plan

## Context

The frontend has 7 monolith view components (2,300 / 1,800 / 1,600 / 1,100 / 1,000 / 1,000 / 900 lines) with zero sub-component extraction. The visual identity is "shadcn default" — premium CSS effects are defined but unused, Recharts are completely unstyled, and 49 shadcn components are unmodified. The goal is a full redesign: rethink layouts, information hierarchy, and visual language to feel like a premium financial analytics tool, not a template.

**Approach**: Horizontal-first (design system → decompose → polish) to avoid decompose-then-restyle double-work.

---

## Phase 1: Design System Foundation

Build the shared layer everything else depends on.

### ~~1a. Consolidated color/formatting utilities~~ DONE (`d8d985a6`)
- 4 helpers in `lib/colors.ts`: `getChangeColor`, `getLevelBadgeClasses`, `getTrendColor`, `getChangeStrokeColor`
- 9 components migrated, 20 duplicated functions → 4 shared. Plan: `completed/FRONTEND_REDESIGN_PHASE1A_PLAN.md`

### ~~1b. Recharts theme layer~~ DONE (`69a5b7b2`)
- `lib/chart-theme.ts`: color palette from CSS vars, axis/grid presets, financial formatters
- `ChartTooltip` + `ChartContainer` blocks with glass styling, loading/empty/error states
- PriceChartTab migrated as proof-of-concept (`af2d51d4`). Plan: `FRONTEND_REDESIGN_PHASE1B_PLAN.md`

### ~~1c. Expand block component library (5 new blocks)~~ DONE (`48fc07ca`)
- StatPair, InsightBanner, StatusCell, TabContentWrapper, DataTable
- Block library now at 12 components. Infrastructure only, no consumers migrated yet.
- Plan: `FRONTEND_REDESIGN_PHASE1C_PLAN.md`

### ~~1d. Upgrade base shadcn components~~ DONE (`28a99734`)
- Card: CVA variants (default/glass/glassTinted) + hover prop (lift/subtle)
- Button: `premium` variant (emerald gradient + shimmer + text-white dark mode fix)
- 28 consumer sites migrated across 13 files. Chrome-verified.
- Plan: `FRONTEND_REDESIGN_PHASE1D_PLAN.md`

**Key files**: `lib/colors.ts`, `lib/chart-theme.ts`, 12 blocks in `components/blocks/`, `components/ui/card.tsx`, `components/ui/button.tsx`

---

## ~~Phase 2: PortfolioOverview Decomposition~~ DONE (`810c6140`)

2,303 lines → 127-line orchestrator + 9 files in `overview/`: types, helpers, useOverviewMetrics hook, ViewControlsHeader, OverviewMetricCard, SmartAlertsPanel, MarketIntelligenceBanner, AIRecommendationsPanel, SettingsPanel, InstitutionalSparkline, index. Chrome-verified. Container untouched.

---

## ~~Phase 3: Performance + Holdings Decomposition~~ DONE

### ~~Phase 3a: HoldingsView~~ DONE (`8c082330`)
924 lines → 95-line orchestrator + 8 files in `holdings/`: types, helpers, useHoldingsData hook, HoldingsSummaryCards, HoldingsTableHeader, HoldingsTable, HoldingsTableFooter, index. Chrome-verified with live data (26 positions). Plan: `FRONTEND_REDESIGN_PHASE3_PLAN.md`.

### ~~Phase 3b: PerformanceView~~ DONE (`10a326d9`)
1,407 lines → 201-line orchestrator + 10 files in `performance/`: types, helpers, usePerformanceState, usePerformanceData, PerformanceHeaderCard, AttributionTab, BenchmarksTab, RiskAnalysisTab, PeriodAnalysisTab, index. Chrome-verified with live data (4 metric cards, 3 insights, 4 tabs with full attribution/benchmark/risk data). Plan: `FRONTEND_REDESIGN_PHASE3_PLAN.md`.

---

## ~~Phase 4: Risk + Scenario + Strategy + Stock Decomposition~~ DONE

### RiskAnalysis (345 lines) — already reasonable, skip

### ~~Phase 4a: ScenarioAnalysis~~ DONE (`9a4a460f`)
2,302 lines → 408-line orchestrator + 12 files in `scenario/`: types, helpers, useScenarioHistory hook, useScenarioOrchestration hook, RecentRunsPanel, ScenarioHeader, PortfolioBuilderTab, OptimizationsTab, HistoricalTab, StressTestsTab, MonteCarloTab, index. Chrome-verified (all 5 tabs). Plan: `FRONTEND_REDESIGN_PHASE4A_PLAN.md`.

### ~~Phase 4b: StockLookup~~ DONE (`6d9ada9d`)
1,348 lines → 384-line orchestrator + 9 files in `stock-lookup/`: types, helpers, OverviewTab, TechnicalsTab, FundamentalsTab, PeerComparisonTab, PortfolioFitTab, PriceChartTab, index. Risk Factors tab stays inline (~42 lines). Chrome-verified (all 7 tabs). Plan: `FRONTEND_REDESIGN_PHASE4B_PLAN.md`.

### ~~Phase 4c: StrategyBuilder~~ DONE (`a2c88462`)
1,128 lines → 167-line orchestrator + 8 files in `strategy/`: types, helpers, useStrategyData hook, BuilderTab, MarketplaceTab, ActiveStrategiesTab, PerformanceTab, index. Chrome-verified with live data (all 4 tabs). Plan: `completed/FRONTEND_REDESIGN_PHASE4A_PLAN.md`.


---

## Phase 4.5: Block Component Migration Batches

Migrate decomposed views to use Phase 1c block components (replacing inline patterns with shared blocks).

### ~~Batch 1: GradientProgress + SectionHeader~~ DONE (`af2d51d4`)
- GradientProgress: 6 sites across 3 files (OverviewTab, TechnicalsTab, FundamentalsTab)
- SectionHeader: 14 sites across 5 files
- Plan: `FRONTEND_REDESIGN_MIGRATION_BATCH1_PLAN.md`

### ~~Batch 2: Recharts chart-theme + StatPair~~ DONE (`61d24aca`)
- Chart-theme: 2 charts (equity curve in PerformanceTab, price chart in PriceChartTab)
- StatPair: 6 sites across 3 files (OverviewTab, TechnicalsTab, FundamentalsTab)
- Plan: `FRONTEND_REDESIGN_MIGRATION_BATCH2_PLAN.md`

### ~~Batch 3: StatusCell + DataTable~~ DONE (`2805bfd3`)
- StatusCell: 6 sites across 2 files (OverviewTab 4 risk metric cards, FactorRiskModel 2 risk attribution cards)
- DataTable: 8 tables across 2 files (AttributionTab 4 tables, PerformanceTab 4 tables)
- InsightBanner: evaluated, zero clean migration targets (typography/size mismatches)
- Plan: `FRONTEND_REDESIGN_MIGRATION_BATCH3_PLAN.md`

---

## Phase 4.75: Theme System Infrastructure DONE (`d00019ec`)

Added `visualStyle: "classic" | "premium"` toggle to `useUIStore` with localStorage persistence, `data-visual-style` attribute sync on `<html>`, and staged Classic/Premium toggle in SettingsPanel. Phase 5 will wire premium CSS classes gated on this toggle. Plan: `FRONTEND_THEME_SYSTEM_PLAN.md`.

---

## ~~Phase 5: Visual Polish Pass~~ DONE

Final sweep across all views for "Bloomberg meets modern SaaS" aesthetic. Delivered in 4 batches:

### ~~Batch 1: StockLookup + Risk Analysis~~ DONE (`05bb1241`)
- `glassTinted` on 11 plain white Cards (StockLookup tabs + RiskAnalysis main)
- `hover-lift-subtle` on 12 metric/interactive cards
- `animate-stagger-fade-in` on 4 card lists (risk factors, stress tests, hedging strategies)
- Plan: `FRONTEND_STOCKLOOKUP_RISK_POLISH_PLAN.md`

### ~~Batch 2: Chart Polish~~ DONE (`e3570800`)
- MonteCarloTab: migrated 9 hard-coded hex colors → `chartSemanticColors` system
- Extracted `mcColors` constant object for gradient defs + Area strokes
- Plan: `FRONTEND_CHART_POLISH_PLAN.md`

### ~~Batch 3: Typography + CSS Pruning~~ DONE (`26831157`)
- `text-balance-optimal` on SectionHeader `<h2>` (propagates to 8+ consumers) + 5 standalone `CardTitle` headings
- Removed unused `dashboard-layout` CSS class (31 lines)
- Plan: `FRONTEND_TYPOGRAPHY_CSS_PRUNE_PLAN.md`

### ~~Batch 4: Dark Mode Audit + Morph Border~~ DONE (`02ee0a3a`)
- Dark mode `morph-border` gradient (0.1→0.25 opacity for dark bg visibility)
- Dark mode premium hover shadows (stronger opacity for dark backgrounds)
- `morph-border rounded-3xl` on MarketplaceTab Featured Strategy hero card
- Full premium class dark mode audit (26 classes evaluated)
- Plan: `FRONTEND_DARKMODE_MORPHBORDER_PLAN.md`

**Known remaining gaps** (documented, out of scope for polish pass): gradient backgrounds (`bg-gradient-sophisticated`, etc.), loading states (`shimmer-loading`, `skeleton-premium`), hardcoded Tailwind light-mode colors. These require a dedicated dark mode color palette effort.

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

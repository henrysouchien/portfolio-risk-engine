# Frontend Redesign — Phase 4a: StrategyBuilder Decomposition

**Date:** 2026-03-06
**Status:** DONE (`a2c88462`, `9a4a460f`)
**Source:** `FRONTEND_REDESIGN_PLAN.md` Phase 4
**Prerequisite:** Phase 3 (Holdings + Performance decomposition) complete

---

## Context

Phase 3 (Holdings + Performance decomposition) is complete. StrategyBuilder.tsx at 1,128 lines is the last true monolith — ScenarioAnalysis is already decomposed (408-line orchestrator + 12 files in `scenario/`), RiskAnalysis (345 lines) and StockLookup (384 lines) are already reasonable.

**Source:** `frontend/packages/ui/src/components/portfolio/StrategyBuilder.tsx` (1,128 lines → ~150 line orchestrator)
**Container:** `dashboard/views/modern/StrategyBuilderContainer.tsx` (unchanged)
**New directory:** `components/portfolio/strategy/`

---

## Files

| File | ~Lines | Extracts from |
|------|--------|---------------|
| `types.ts` | ~90 | `Strategy` interface (lines 26-59), `BacktestPeriod` type (line 61), `UnknownRecord` (line 63), `StrategyBuilderBacktestData` (lines 65-74), `StrategyBuilderProps` (lines 99-147) |
| `helpers.ts` | ~100 | `toRecord()` (line 76), `toNumber()` (line 79), `formatOptionalPercent()` (line 92), `formatOptionalNumber()` (line 95), `getStrategyTypeColor()` (line 309), `getStatusColor()` (line 321), `getStatusIcon()` (line 337), `normalizeTemplatesToStrategies()` (extracted from IIFE at lines 223-274), `normalizeAnnualBreakdown()` (extracted from lines 285-307), `PREBUILT_STRATEGIES` constant (extracted from lines 193-212) |
| `useStrategyData.ts` | ~60 | Derived values: `currentMetrics`, `strategyPreview`, `strategies`, `activeStrategies`, `primaryStrategy`, all `performanceMetrics`/`returnsMetrics`/`riskMetrics`/etc decomposition (lines 214-307). Calls `normalizeTemplatesToStrategies` and `normalizeAnnualBreakdown` from helpers. |
| `BuilderTab.tsx` | ~200 | Strategy Configuration card (lines 484-535), Asset Allocation card (lines 538-589), Strategy Preview card (lines 599-634), action buttons (lines 636-657). Owns `strategyName`, `strategyType`, `riskTolerance`, `allocation` state internally. |
| `MarketplaceTab.tsx` | ~110 | Featured Strategy Spotlight (lines 671-698), Strategy Grid (lines 700-764). Receives `strategies`, `primaryStrategy`, `onOptimize`. |
| `ActiveStrategiesTab.tsx` | ~70 | Active strategy cards with empty state (lines 773-829). Receives `activeStrategies`. |
| `PerformanceTab.tsx` | ~300 | Backtest Summary 8-metric grid (lines 839-908), Equity Curve recharts LineChart (lines 910-963), Annual Breakdown table (lines 965-997), Security/Sector/Factor Attribution tables (lines 999-1099), empty state (lines 1102-1122). Receives `backtestData`, `annualBreakdownRows`. |
| `index.ts` | ~15 | Barrel re-exports |

**Dependencies:**
- `SectionHeader` from `components/blocks/`
- `getChangeColor` from `lib/colors.ts`
- `formatCurrency`, `formatNumber`, `formatPercent` from `@risk/chassis`
- `AttributionRow` type from `@risk/connectors`
- `Badge`, `Button`, `Card`, `CardContent`, `CardHeader`, `Input`, `Label`, `ScrollArea`, `Select/*`, `Slider`, `Tabs/*` from `components/ui/`
- `recharts`: `LineChart`, `Line`, `XAxis`, `YAxis`, `Tooltip`, `ResponsiveContainer`, `Legend` (only in PerformanceTab)
- Lucide icons: `Activity`, `BarChart3`, `Brain`, `CheckCircle`, `Clock`, `Layers`, `Lightbulb`, `Pause`, `Play`, `Sparkles`, `Target`, `TrendingUp`

---

## Orchestrator (~150 lines)

- Imports from `./strategy/`
- Owns: `activeTab`, `backtestPeriod` state (needed at Tabs level and header)
- Calls `useStrategyData(optimizationData, backtestData)` hook
- Handler functions: `runBacktest()`, `handleBacktestPeriodChange()` stay in orchestrator (they need `backtestPeriod` + container callbacks)
- `handleCreateStrategy()` stays in orchestrator — calls 3 container callbacks (`onSaveStrategy`, `onOptimize`, `onExportToScenario`), receives form values from BuilderTab via callback
- CardHeader with SectionHeader + backtestPeriod Select
- Composes: `<Tabs>` → BuilderTab, MarketplaceTab, ActiveStrategiesTab, PerformanceTab

---

## Key Decisions

- **BuilderTab owns form state**: `strategyName`, `strategyType`, `riskTolerance`, `allocation` are only used inside the Builder tab. Moving them down avoids prop drilling and keeps the orchestrator thin.
- **PerformanceTab gets recharts**: Only tab that uses recharts. Keeps the import isolated.
- **Attribution tables**: 3 near-identical tables (Security, Sector, Factor) in PerformanceTab. Could extract a shared `AttributionTable` component, but they have slightly different columns (Factor has Beta instead of Weight). Keep inline in PerformanceTab for simplicity — can extract later if needed.
- **`PREBUILT_STRATEGIES` constant**: Static placeholder data (lines 193-212) moves to helpers.ts as a named export.

---

## Verification

1. `cd frontend && pnpm typecheck` — must pass
2. `cd frontend && pnpm build` — must succeed
3. `cd frontend && pnpm test` — existing tests pass
4. Chrome: Strategy Builder renders identically (all 4 tabs, marketplace cards, backtest data, equity curve chart)
5. Container import path unchanged — no breakage in routing

## Files Modified

| New files | Modified | NOT modified |
|-----------|----------|-------------|
| 8 in `strategy/` | `StrategyBuilder.tsx` (rewrite) | `StrategyBuilderContainer.tsx` |

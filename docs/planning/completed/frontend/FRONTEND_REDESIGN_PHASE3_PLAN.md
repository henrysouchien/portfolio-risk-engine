# Frontend Redesign — Phase 3: Performance + Holdings Decomposition

**Date:** 2026-03-06
**Status:** DONE (implemented + Chrome-verified 2026-03-06)
**Source:** `FRONTEND_REDESIGN_PLAN.md` Phase 3
**Prerequisite:** Phase 2 (PortfolioOverview decomposition) complete via Codex

---

## Context

Phase 2 (PortfolioOverview decomposition, 2,076 → ~126 lines + 11 files in `overview/`) is complete. Phase 3 decomposes the next two largest monoliths: **PerformanceView.tsx** (1,407 lines) and **HoldingsView.tsx** (924 lines) into focused sub-components following the same pattern.

Containers are NOT modified. Import paths preserved. Each sub-phase is a separate commit.

---

## Phase 3a: HoldingsView Decomposition

**Source:** `frontend/packages/ui/src/components/portfolio/HoldingsView.tsx` (924 lines → ~160 line orchestrator)
**Container:** `dashboard/views/modern/HoldingsViewModernContainer.tsx` (unchanged)
**New directory:** `components/portfolio/holdings/`

### Files

| File | Lines | Extracts from |
|------|-------|---------------|
| `types.ts` | ~80 | `Holding` interface (27 fields, lines 186-258), `HoldingsViewProps` (lines 259-268), sort field/direction types |
| `helpers.ts` | ~60 | `renderMiniSparkline()` (SVG, lines 464-495), `getSectorIcon()` (lines 497-517), `renderRiskScoreBadge()` (lines 519-537) |
| `useHoldingsData.ts` | ~120 | State: `holdings`, `searchTerm`, `sortField`, `sortDirection`, `selectedSector`, `hoveredRow` (lines 273-319). Filtering/sorting memos (lines 366-426). `summaryMetrics` computation. `handleSort()` (line 434), `handleExportCsv()` (line 445, needs `loadRuntimeConfig` from `@risk/chassis`). `sectors` memo. |
| `HoldingsSummaryCards.tsx` | ~60 | 4 MetricCard row (lines 548-590): Total Holdings, Total Return, Avg Volatility, Active Alerts. Plus pending updates banner (lines 592-604). |
| `HoldingsTableHeader.tsx` | ~80 | Card header with title, search input, sector filter dropdown, Export CSV button (lines 606-653) |
| `HoldingsTable.tsx` | ~200 | Table with 7 sortable columns: Symbol, Market Value, Weight, Total Return, Day Change, Volatility, Risk Score (lines 661-896). Uses `renderMiniSparkline`, `getSectorIcon`, `renderRiskScoreBadge` from helpers. |
| `HoldingsTableFooter.tsx` | ~30 | Footer with filtered/total count + total value + last updated badge (lines 902-918). No export button (export is in header). |
| `index.ts` | ~15 | Barrel re-exports |

**Dependencies:**
- `MetricCard` from `components/blocks/`
- `getChangeColor` from `lib/colors.ts`
- `formatCurrency`, `formatPercent`, `loadRuntimeConfig` from `@risk/chassis`
- `Badge`, `Button`, `Card`, `CardHeader`, `CardTitle`, `CardContent`, `Input`, `Tooltip`/`TooltipProvider` from `components/ui/`
- Lucide icons: `Wallet`, `TrendingUp`, `Shield`, `AlertTriangle`, `PieChart`, `Search`, `ChevronDown`, `Download`, `ArrowUpDown`, `ExternalLink`

### Orchestrator (~160 lines)
- Imports from `./holdings/`
- Calls `useHoldingsData(portfolioData)` hook
- Composes: SummaryCards → Card(TableHeader + Table + TableFooter)
- Keeps: `mounted` animation state, container callback delegation (`onRefresh`, `onAnalyzeRisk`, `onConnectAccount`)

---

## Phase 3b: PerformanceView Decomposition

**Source:** `frontend/packages/ui/src/components/portfolio/PerformanceView.tsx` (1,407 lines → ~170 line orchestrator)
**Container:** `dashboard/views/modern/PerformanceViewContainer.tsx` (unchanged)
**New directory:** `components/portfolio/performance/`

### Files

| File | Lines | Extracts from |
|------|-------|---------------|
| `types.ts` | ~100 | `PerformanceAttributionStock` (lines 45-63), `PerformanceViewProps` (lines 65-110), `ViewMode` type, period/benchmark types |
| `helpers.ts` | ~90 | `getAlphaColor()` (line 479), `getPerformanceIcon()` (line 487), `formatOptionalPercent()` (line 493), `formatOptionalNumber()` (line 496), `getAlphaStrength()` (line 499), `getSharpeStrength()` (line 506), `generateTooltipContent()` (line 514, takes `Pick<PerformanceData, 'alpha' | 'sharpeRatio' | 'beta'>`) |
| `usePerformanceState.ts` | ~100 | 9 state vars (lines 128-139): `viewMode`, `showInsights`, `selectedPeriod`, `selectedBenchmark`, `showAllContributors`, `showAllDetractors`, `isBusy`, `lastUpdated`, `savePending`. localStorage preference load/save effects (lines 204-255), debounced save. |
| `usePerformanceData.ts` | ~130 | `performanceData` memo (lines 256-315), `mappedSectors`/`mappedFactors`/`sortedSectorRows`/`sortedFactorRows` (lines 316-360), `buildInsights()` (lines 361-410), monthly returns (lines 411-462), `sortedContributorRows`/`sortedDetractorRows` |
| `PerformanceHeaderCard.tsx` | ~280 | Title bar + controls (view mode, insights toggle, period/benchmark selectors, export dropdown, refresh) + 4 metric summary cards (lines 570-958). No sparkline — uses computed `alphaStrength`/`sharpeStrength` badges. |
| `AttributionTab.tsx` | ~180 | Sector attribution table, factor attribution table, top contributors (with `showAllContributors` toggle, default 5), top detractors (with `showAllDetractors` toggle, default 5) (lines 990-1155). Uses `SectionHeader` from `components/blocks/`. |
| `BenchmarksTab.tsx` | ~100 | Benchmark comparison table + risk metrics grid (lines 1155-1238) |
| `RiskAnalysisTab.tsx` | ~90 | Drawdown analysis, risk metrics, volatility breakdown (lines 1238-1340) |
| `PeriodAnalysisTab.tsx` | ~90 | Monthly returns grid/heatmap (lines 1340-1403) |
| `index.ts` | ~15 | Barrel re-exports |

**Dependencies:**
- `SectionHeader` from `components/blocks/`
- `getChangeColor`, `getLevelBadgeClasses` from `lib/colors.ts`
- `formatNumber`, `formatPercent` from `@risk/chassis`
- `Badge`, `Button`, `Card`, `CardContent`, `CardHeader`, `DropdownMenu/*`, `Select/*`, `Tabs/*`, `Tooltip/*` from `components/ui/`
- Lucide icons: `ArrowDown`, `ArrowUp`, `BarChart3`, `Calendar`, `Minus`, `PieChart`, `RefreshCw`, `Share2`, `Target`, `Timer`, `TrendingUp`, `Zap`
- NO recharts imports (PerformanceView doesn't use recharts currently)

### Orchestrator (~170 lines)
- Imports from `./performance/`
- Calls `usePerformanceState()` and `usePerformanceData(data, ...)`
- Composes: HeaderCard → Tabs (Attribution, Benchmarks, Risk, Period)
- Keeps: `activeTab` state, handler delegation to container callbacks (`onRefresh`, `onExport`, `onBenchmarkChange`)
- `showAllContributors`/`showAllDetractors` state lives in `usePerformanceState` hook, passed down to `AttributionTab`

---

## Implementation Sequence

1. **Phase 3a** first (simpler, 924 lines, fewer internal dependencies) — ✅ `8c082330`
2. **Phase 3b** second (larger, 1,407 lines, more complex state management) — ✅ `10a326d9`
3. Each phase is a separate commit for clean rollback

## Key Constraints

- Container components (`*Container.tsx`) are NEVER modified
- `HoldingsView.tsx` and `PerformanceView.tsx` stay at their current paths as orchestrators — same pattern as Phase 2
- No component should exceed ~300 lines after decomposition
- Existing `MetricCard` block and `lib/colors.ts` utilities must be reused (no duplication)
- `generateTooltipContent()` must receive typed data param to avoid type friction when extracted
- `handleBenchmarkChange` logic must be preserved exactly (controlled component pattern from container)
- All shadcn UI components imported from `components/ui/`

## Verification

Per phase:
1. `cd frontend && pnpm typecheck` — must pass
2. `cd frontend && pnpm build` — must succeed
3. `cd frontend && pnpm test` — existing tests pass
4. Chrome: visual verification that view renders identically (data, interactions, animations)
5. Container import path unchanged — no breakage in routing

## Files Modified

| Phase | New files | Modified | NOT modified |
|-------|-----------|----------|-------------|
| 3a | 8 in `holdings/` | `HoldingsView.tsx` (rewrite) | `HoldingsViewModernContainer.tsx` |
| 3b | 10 in `performance/` | `PerformanceView.tsx` (rewrite) | `PerformanceViewContainer.tsx` |

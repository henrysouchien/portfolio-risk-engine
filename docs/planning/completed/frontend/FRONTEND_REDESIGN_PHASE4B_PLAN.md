# Frontend Redesign — Phase 4b: StockLookup Decomposition

**Date:** 2026-03-06
**Status:** DONE (`6d9ada9d`)
**Source:** `FRONTEND_REDESIGN_PLAN.md` Phase 4

---

## Context

`StockLookup.tsx` is 1,348 lines — a 7-tab stock research component containing types, helpers, 3 useMemo derivations, and all tab JSX inline. Decomposing it follows the same pattern as Phase 2 (PortfolioOverview) and Phase 4a (ScenarioAnalysis).

The container (`StockLookupContainer.tsx`, line 72: `import StockLookup from '../../../portfolio/StockLookup'`) is NOT modified.

**Goal:** 1,348-line monolith → ~220-line orchestrator + 8 focused files in `components/portfolio/stock-lookup/`.

---

## New directory: `components/portfolio/stock-lookup/`

### 1. `types.ts` (~100 lines)
**Replaces:** lines 22-216
- All type definitions: `RiskFactor`, `PortfolioFitMetricFormat`, `PortfolioFitMetricRow`, `PortfolioFitAnalysisData`, `TradePreviewData`, `PeerComparisonData`, `StockLookupProps`
- New shared alias: `SelectedStockData = NonNullable<StockLookupProps['selectedStock']>`
- Imports only from `@risk/chassis` and `@risk/connectors`

### 2. `helpers.ts` (~75 lines)
**Replaces:** lines 65-115 (module-level helpers) + lines 299-318 + 419-440 (component-internal helpers moved to module level)
- `LOWER_IS_BETTER_METRICS` (lines 65-72) — used by PeerComparisonTab
- `toNumericValue()` (lines 74-86) — used by PeerComparisonTab
- `formatPeerMetricValue()` (lines 87-101) — used by PeerComparisonTab
- `formatPortfolioMetric()` (lines 102-115) — used by PortfolioFitTab
- `getRiskColor()` (lines 299-308) — used by orchestrator (stock header badge)
- `formatMarketCap()` (lines 309-318) — used by orchestrator (stock header)
- `formatPortfolioDelta()` (lines 419-434) — used by PortfolioFitTab
- `riskCardStyles` (lines 435-440) — used by OverviewTab
- Depends on: `types.ts`

### 3. `OverviewTab.tsx` (~110 lines)
**Replaces:** lines 634-729 (overview TabsContent)
- Props: `{ selectedStock: SelectedStockData }`
- 4 risk metric cards (VaR 95%, Beta, Volatility, Sharpe), additional risk metrics card
- Imports `riskCardStyles` from `./helpers`
- Depends on: `types.ts`, `helpers.ts`

### 4. `TechnicalsTab.tsx` (~125 lines)
**Replaces:** lines 782-893 (technicals TabsContent)
- Props: `{ selectedStock: SelectedStockData }`
- RSI card, MACD card, support/resistance visualization, Bollinger bands card
- Depends on: `types.ts`

### 5. `FundamentalsTab.tsx` (~155 lines)
**Replaces:** lines 899-1028 (fundamentals TabsContent)
- Props: `{ selectedStock: SelectedStockData }`
- Computes `financialHealthScores` useMemo internally (moved from lines 363-418)
- 4 fundamental metric cards, valuation metrics, financial health score section
- Depends on: `types.ts`

### 6. `PeerComparisonTab.tsx` (~115 lines)
**Replaces:** lines 1030-1121 (peer-comparison TabsContent)
- Props: `{ selectedStock: SelectedStockData; peerComparison; peerComparisonLoading; peerComparisonError }`
- Computes `peerTableTickers` and `peerComparisonRows` useMemo internally (moved from lines 319-362)
- Peer table with ranking badges, loading/error/empty states
- Depends on: `types.ts`, `helpers.ts`

### 7. `PortfolioFitTab.tsx` (~170 lines)
**Replaces:** lines 1123-1272 (portfolio-fit TabsContent)
- Props: `{ selectedStock, portfolioFitSize, portfolioFitSizeOptions, onPortfolioFitSizeChange, onRunPortfolioFit, portfolioFitLoading, portfolioFitError, portfolioFitAnalysis, onPreviewTrade, tradePreview, portfolioValue }`
- Position sizing controls, what-if results table, risk/beta check badges, trade preview card
- Imports `formatPortfolioMetric`, `formatPortfolioDelta` from `./helpers`
- Depends on: `types.ts`, `helpers.ts`

### 8. `PriceChartTab.tsx` (~85 lines)
**Replaces:** lines 1274-1341 (price-chart TabsContent)
- Props: `{ selectedStock: SelectedStockData }`
- All recharts imports move here exclusively (Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis)
- 90-day price history chart + volume chart
- Depends on: `types.ts`

### 9. `index.ts` (~15 lines)
- Barrel re-exports all sub-components, helpers used by orchestrator, and key types
- Does NOT re-export StockLookup (orchestrator lives outside)

---

## Orchestrator: `StockLookup.tsx` (~220 lines)

**State** (~4 lines): `activeTab`, `searchQuery`

**Effects** (~4 lines): Sync `searchQuery` from `searchTerm` prop

**Derived** (~15 lines): `riskFactors` (from selectedStock.factorSummary), `showSearchDropdown`

**Handlers** (~30 lines): `handleSearchChange`, `handleSearch`, `handleQuickSelect`, `handleSelectSearchResult`

**JSX** (~170 lines): Card > CardHeader (search panel + dropdown) + CardContent with empty/loading states, stock header, Tabs with TabsList + Risk Factors tab inline (~42 lines, too small to extract) + 6 delegated tab components

**NOT extracted (stays inline):** Risk Factors tab (lines 735-776, ~42 lines) — too small to justify its own file

---

## Import path strategy

Container import: `import StockLookup from '../../../portfolio/StockLookup'` (line 72). Orchestrator stays at `components/portfolio/StockLookup.tsx`, imports from `./stock-lookup/`. Zero container modifications.

---

## Implementation sequence

1. `stock-lookup/types.ts` — no deps
2. `stock-lookup/helpers.ts` — depends on types
3-8. (parallel) `OverviewTab.tsx`, `TechnicalsTab.tsx`, `FundamentalsTab.tsx`, `PeerComparisonTab.tsx`, `PortfolioFitTab.tsx`, `PriceChartTab.tsx`
9. `stock-lookup/index.ts` — barrel
10. Rewrite `StockLookup.tsx` as orchestrator

---

## Files modified

| File | Changes |
|------|---------|
| `stock-lookup/types.ts` | **NEW** ~100 lines |
| `stock-lookup/helpers.ts` | **NEW** ~75 lines |
| `stock-lookup/OverviewTab.tsx` | **NEW** ~110 lines |
| `stock-lookup/TechnicalsTab.tsx` | **NEW** ~125 lines |
| `stock-lookup/FundamentalsTab.tsx` | **NEW** ~155 lines |
| `stock-lookup/PeerComparisonTab.tsx` | **NEW** ~115 lines |
| `stock-lookup/PortfolioFitTab.tsx` | **NEW** ~170 lines |
| `stock-lookup/PriceChartTab.tsx` | **NEW** ~85 lines |
| `stock-lookup/index.ts` | **NEW** ~15 lines |
| `StockLookup.tsx` | **REWRITE** 1,348 → ~220 lines |

**NOT modified:** StockLookupContainer.tsx, any other view/container, scenario/, overview/

**Total:** ~1,170 lines across 10 files (was 1,348 in 1 file).

---

## Verification

1. `cd frontend && pnpm typecheck` — UI package must pass
2. `cd frontend && pnpm build` — must pass
3. Visual: all 7 tabs render (Overview, Risk Factors, Technicals, Fundamentals, Peer Comparison, Portfolio Fit, Price Chart)
4. Functional: search, stock selection, peer comparison loading, portfolio fit run all work
5. Container import path unchanged (line 72 of StockLookupContainer.tsx)

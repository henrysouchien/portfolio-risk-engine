# Frontend Delete Pass Plan
**Status:** DONE — commit `631fe4cb`


**Goal:** Aggressively remove fake, broken, duplicate, and placeholder UI elements to create a clean canvas for redesign. Conservative scope: REMOVE and FIX only. No new features.

**Source:** Issues from `docs/planning/FRONTEND_ISSUES_2026_03_10.md`

**Principle:** If it's broken, fake, placeholder, or redundant — remove it. If it works and shows real data — keep it. Component files stay in the repo; we only remove their usage from pages or strip broken elements within them.

**Estimated effort:** ~2-3 hours total

---

## Order of Operations

| # | Step | Target | Effort | Risk |
|---|------|--------|--------|------|
| 1 | 1.2 | Fix stray "0" bug | 5 min | Near-zero |
| 2 | 1.4 | Remove Asset Allocation period selector | 10 min | Low (fixes crash) |
| 3 | 2.2 | Remove "CUSTOM" benchmark option | 2 min | Near-zero |
| 4 | 1.3 | Remove "Critical" badge on hover | 5 min | Near-zero |
| 5 | 1.5 | Remove Hypothetical/Realized toggle | 20 min | Low |
| 6 | 2.1 | Remove Standard/Detailed toggle | 15 min | Low |
| 7 | 1.1 | Remove View Mode toggle + hover metadata | 30 min | Medium |
| 8 | 3.1 | Remove Active Strategies tab | 5 min | Near-zero |
| 9 | 4.1 | Remove Historical Scenarios tab | 5 min | Near-zero |
| 10 | 5.1 | Remove duplicate PerformanceView from Overview | 5 min | Low |
| 11 | 1.6 | Remove RiskMetricsContainer from Overview + Factors | 10 min | Medium |
| 12 | 1.7 | Remove Risk Efficiency metric | 10 min | Low |
| 13 | 5.2 | Clean up unused imports | 10 min | Near-zero |

---

## Phase 1: Portfolio Overview (`activeView === 'score'`)

### Step 1.1: Remove View Mode Toggle (Compact/Detailed/Pro/Institutional)

**Issues:** 4, 5 (partial)

**Remove:**
- `ViewControlsHeader.tsx` lines 29-65: All four view mode buttons
- `OverviewMetricCard.tsx` — all `viewMode`-conditional logic:
  - Lines 101-106: Institutional CORR/ScanLine icons
  - Lines 117-121: Variable padding → replace with fixed `p-6`
  - Lines 126-128: Variable title font → replace with fixed `text-sm`
  - Lines 136-140: Institutional CORR badge
  - Lines 143-166: Hover metadata row (volatility label, timestamp, AI confidence %)
  - Lines 159-164: Institutional marketSentiment hover data
  - Lines 185-189: Variable value font → replace with fixed `text-3xl`
  - Lines 215-219: AI confidence "High Confidence" badge
  - Lines 221-229: Institutional marketSentiment badge
  - Lines 266-276: Institutional futureProjection section
  - Lines 278-316: Institutional correlations + technicalSignals section
  - Lines 329-333: Institutional "LIVE" text
  - Lines 383-411: Remove the tooltip entirely (rehashes visible data)
  - Lines 394-396: Institutional marketSentiment in tooltip
  - Lines 405-409: Institutional correlations in tooltip
- `ViewControlsHeader.tsx` interface: Remove `viewMode` and `onViewModeChange` props
- `PortfolioOverview.tsx`: Remove `viewMode` state, stop passing to children
- `types.ts`: Remove `ViewMode` type + `MetricCorrelation`, `MetricRiskFactor`, `MetricMarketSentiment`, `MetricTechnicalSignal`, `MetricFutureProjection` interfaces

**Keep:**
- Refresh button, AI Insights toggle, Settings gear in `ViewControlsHeader.tsx`
- Basic card structure and real data display
- AI Analysis panel (lines 250-319)

**Test:** Overview renders, cards at consistent size, no mode toggle, no TS errors

---

### Step 1.2: Fix Stray "0" Bug + Remove Hardcoded Metadata

**Issues:** 7, 8

**Fix/Remove:**
- `OverviewMetricCard.tsx` line 215: `{metric.aiConfidence && metric.aiConfidence > 90 && (` → `{metric.aiConfidence > 90 && (`
- `useOverviewMetrics.ts` lines 95-96, 118-119, 141-142: Remove hardcoded `volatility: "Stable"/"Very Low"`, `lastUpdate: ""`

**Test:** No stray "0" on bottom 3 cards, no "Updated0" text

---

### Step 1.3: Remove "Critical" Badge on Hover

**Issues:** 5 (partial)

**Remove:**
- `OverviewMetricCard.tsx` lines 209-213: "Critical" badge on hover
- `useOverviewMetrics.ts` line 28: Change `priority: "critical"` to `priority: "high"`

**Test:** No "Critical" badge appears on hover

---

### Step 1.4: Remove Asset Allocation Period Selector

**Issues:** 13 (fixes crash + layout imbalance)

**Remove:**
- `AssetAllocationContainer.tsx` line 104: Remove `performancePeriod` state
- `AssetAllocationContainer.tsx` line 118: Change `useRiskAnalysis({ performancePeriod })` → `useRiskAnalysis()`
- `AssetAllocationContainer.tsx` lines 366-381: Remove entire period selector button row

**Keep:** Full AssetAllocation component, targets, drift, rebalance

**Test:** Card loads, no period buttons, no crash, visually balanced with Risk Assessment

---

### Step 1.5: Remove Hypothetical/Realized Mode Toggle Card

**Issues:** 20b

**Remove:**
- `PerformanceViewContainer.tsx` line 308: Remove `mode` state
- Lines 309-310: Remove `institution`, `account` state
- Lines 434-493: Remove entire `modeControls` card (Performance Mode header + buttons + form)
- Line 569: Remove `{modeControls}` from JSX
- Lines 360-368: Simplify to always use hypothetical data
- Lines 600-608: Remove realized-specific no-data message
- Lines 632-634: Remove `RealizedPerformanceDetails` render
- Line 323: Remove `useRealizedPerformance()` hook call
- Lines 379-390: Remove `runRealizedAnalysis` function
- Lines 194-280: Remove `RealizedPerformanceDetails` inner component

**Keep:** `usePerformance()` hook, all tabs, benchmark selection, export

**Note:** Realized perf still accessible via AI assistant and REST API

**Test:** Performance loads immediately, no mode card, all tabs work

---

### Step 1.6: Remove RiskMetricsContainer from Overview + Factor Analysis

**Issues:** 27, Design Note E

**Remove from `ModernDashboardApp.tsx`:**
- 'score' view (lines 361-365): Remove `RiskMetricsContainer` from the 2-column grid. Let AssetAllocation + RiskAnalysisModernContainer share the grid (or make AssetAllocation full-width).
- 'factors' view (lines 386-395): Remove `RiskMetricsContainer` from right column. Make `FactorRiskModelContainer` full-width.

**Keep:** `RiskMetricsContainer.tsx` and `RiskMetrics.tsx` files in repo

**Test:** Overview + Factor Analysis render without the duplicate risk card, no import errors

---

### Step 1.7: Remove Risk Efficiency Metric

**Issues:** 18

**Remove:**
- `RiskMetricsContainer.tsx` lines 136-138: Remove `riskEfficiency` computation
- `RiskMetricsContainer.tsx` lines 183-187: Remove `efficiency` and `rating` from `riskSummary`
- `RiskMetrics.tsx` lines 384-393: Remove "Risk Efficiency" + "Overall Rating" grid cells

**Keep:** The amber summary box with systematic/idiosyncratic variance text (real data)

**Test:** Summary box shows variance text, no fake metrics

---

## Phase 2: Performance Analytics

### Step 2.1: Remove Standard/Detailed View Mode Toggle

**Issues:** 21

**Remove:**
- `PerformanceHeaderCard.tsx` lines 103-106: Standard/Detailed buttons
- `PerformanceHeaderCard.tsx` interface: Remove `viewMode`, `onViewModeChange` props
- `usePerformanceState.ts`: Remove `viewMode` state + handler
- `PeriodAnalysisTab.tsx` lines 73-78: Remove `viewMode === "detailed"` conditional (Market Event text is placeholder)
- `performance/types.ts`: Remove `ViewMode` type

**Keep:** Period selector, benchmark selector, insights toggle, export, refresh

**Test:** No Standard/Detailed buttons, Period Analysis works, no TS errors

---

### Step 2.2: Remove "CUSTOM" Benchmark Option

**Issues:** 22 (partial)

**Remove:**
- `PerformanceHeaderCard.tsx` line 54: Remove `{ symbol: "CUSTOM", name: "Custom" }` from `fallbackBenchmarks`

**Test:** Dropdown shows SPY, QQQ, VTI only

---

## Phase 3: Strategy Builder

### Step 3.1: Remove Active Strategies Tab

**Issues:** 33c

**Remove:**
- `StrategyBuilder.tsx`: Remove `<TabsTrigger value="active">Active Strategies</TabsTrigger>`
- `StrategyBuilder.tsx`: Remove `<ActiveStrategiesTab .../>` render
- `StrategyBuilder.tsx`: Change `grid-cols-4` → `grid-cols-3` in TabsList

**Keep:** `ActiveStrategiesTab.tsx` file in repo. Builder, Marketplace, Performance tabs stay.

**Test:** 3 tabs, balanced layout, no errors

---

## Phase 4: Scenario Analysis

### Step 4.1: Remove Historical Scenarios Tab

**Issues:** 32 (partial)

**Remove:**
- `ScenarioAnalysis.tsx`: Remove `<TabsTrigger value="historical">Historical</TabsTrigger>`
- `ScenarioAnalysis.tsx`: Remove `<HistoricalTab .../>` render
- `ScenarioAnalysis.tsx`: Remove `selectedScenario` state
- Remove `HistoricalTab` and `HISTORICAL_SCENARIOS` imports

**Keep:** `HistoricalTab.tsx` and `helpers.ts` files in repo. Other 5 tabs stay.

**Test:** 5 tabs, all working tabs function, no errors

---

## Phase 5: Cross-Cutting

### Step 5.1: Remove Duplicate PerformanceView from Overview

**Issues:** 31

**Remove:**
- `ModernDashboardApp.tsx` 'score' case (lines 368-371): Remove `<PerformanceViewContainer />` from the Overview page

**Keep:** The 'performance' case renders it as a standalone page (Analytics → Performance)

**Test:** Overview ends after Asset Allocation / Risk Analysis. Cmd+4 Performance view still works.

---

### Step 5.2: Clean Up Unused Imports

After all removals, clean up:
- Unused component imports in `ModernDashboardApp.tsx`
- Unused type imports across modified files
- Run `pnpm tsc --noEmit` and `pnpm lint` to verify

---

## Summary of All Removals

| What | Where | Issue |
|------|-------|-------|
| View mode toggle (4 modes) | ViewControlsHeader, OverviewMetricCard, types | 4 |
| Hover metadata row | OverviewMetricCard | 5 |
| Card tooltip | OverviewMetricCard | 5 |
| "Critical" badge | OverviewMetricCard | 5 |
| Stray "0" (fix) | OverviewMetricCard | 7 |
| Hardcoded volatility/lastUpdate | useOverviewMetrics | 8 |
| Asset Allocation period selector | AssetAllocationContainer | 13 |
| Hypothetical/Realized toggle | PerformanceViewContainer | 20b |
| Standard/Detailed toggle | PerformanceHeaderCard, usePerformanceState | 21 |
| "CUSTOM" benchmark option | PerformanceHeaderCard | 22 |
| Active Strategies tab | StrategyBuilder | 33c |
| Historical Scenarios tab | ScenarioAnalysis | 32 |
| Duplicate PerformanceView | ModernDashboardApp (score view) | 31 |
| RiskMetricsContainer (2 places) | ModernDashboardApp (score + factors) | 27 |
| Risk Efficiency + Overall Rating | RiskMetricsContainer, RiskMetrics | 18 |
| Institutional-only types | types.ts | 4 |

## What This Plan Does NOT Touch

Enhancements, redesigns, and new features are explicitly out of scope:
- Adding tooltips/explanations (Issue 16)
- Refresh success toast (Issue 3)
- Replacing Daily P&L card (Issue 6)
- Chart improvements (Issue 9)
- AI Recommendations cleanup (Issues 10, 11)
- Attribution column labels (Issue 26)
- Scenario Analysis / Strategy Builder redesign (Issues 32, 33)
- Navigation restructuring (Issue 28)
- Provider disconnect handling (Issue 25)
- VaR/Max Drawdown methodology (Issues 15, 17)
- Error state color theming (Issue 37)

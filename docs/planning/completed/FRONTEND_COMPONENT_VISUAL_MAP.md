# Frontend Component Visual Map

**Date**: 2026-03-04 (updated)
**Purpose**: Maps what you see on screen to the actual code components, so we can discuss changes using the same language. Includes every tab, click-through, expandable section, and dialog.

> Major update 2026-03-04: Most views previously marked MOCK are now REAL after Waves 1-3 (data wiring, enrichment, workflows). See `completed/FRONTEND_DATA_WIRING_AUDIT.md` for detailed per-view status.

### Related Docs
| Doc | Purpose |
|-----|---------|
| `completed/FRONTEND_PHASE2_WORKING_DOC.md` | Phase 2 master doc — full mock data inventory (16 items) |
| `completed/FRONTEND_WAVE1_IMPLEMENTATION_PLAN.md` | Wave 1 implementation details for the components marked here |
| `COMPOSABLE_APP_FRAMEWORK_PLAN.md` | Phase 3 — the bigger picture this feeds into |

---

## Current Snapshot (2026-03-04)

| View | Actual container wiring | Current status |
|------|-------------------------|----------------|
| Overview (`score`) | `PortfolioOverviewContainer` + `AssetAllocationContainer` + `RiskAnalysisModernContainer` + `PerformanceViewContainer` + `RiskMetricsContainer` | ✅ All 4 AI/insights endpoints live. Metric cards real. |
| Holdings (`holdings`) | `HoldingsViewModernContainer` -> `usePositions()` -> `/api/positions/holdings` | ✅ All per-position fields wired (sector, dayChange, vol, riskScore, alerts, sparklines) |
| Factor Analysis (`factors`) | `FactorRiskModelContainer` + `RiskMetricsContainer` | ✅ All 3 tabs wired (exposure, attribution, performance) |
| Performance (`performance`) | `PerformanceViewContainer` | ✅ Period/risk real, sector+security attribution wired, realized mode, benchmark selection |
| Strategy Builder (`strategies`) | `StrategyBuilderContainer` | ✅ 6 YAML templates, real optimization, backtest + 3 attribution tables |
| Stock Research (`research`) | `StockLookupContainer` | ✅ All tabs wired. Peer Comparison + Portfolio Fit tabs added. Search dropdown gap only |
| Scenario Analysis (`scenarios`) | `ScenarioAnalysisContainer` | ✅ All 5 phases complete (templates, Monte Carlo, history, optimization) |
| AI Assistant (`chat`) | `ChatInterface` | ✅ Real |
| Settings (`settings`) | `RiskSettingsContainer` + `AccountConnectionsContainer` | ✅ Real |

Known shell-level placeholders:

- Header notification center is now **REAL** — `useNotifications()` composing `useSmartAlerts()` + `usePendingUpdates()`. localStorage persistence.
- Market status indicator is time-based client logic (no market calendar integration).
- Command palette still has a small static command list.

---

## How to Navigate

| Keyboard | Nav Bar | View Name (in code) |
|----------|---------|---------------------|
| `⌘1` | Overview | `score` |
| `⌘2` | Holdings | `holdings` |
| `⌘3` | Analytics > Factor Analysis | `factors` |
| `⌘4` | Analytics > Performance | `performance` |
| `⌘5` | Analytics > Strategy Builder | `strategies` |
| `⌘6` | Analytics > Stock Research | `research` |
| `⌘8` | Analytics > Scenario Analysis | `scenarios` |
| `⌘7` | AI Assistant | `chat` |
| `⌘,` | Settings (overflow menu) | `settings` |
| `⌘K` | Command Palette (overflow menu) | (modal overlay) |

---

## App Shell — `ModernDashboardApp`

**File**: `packages/ui/src/components/apps/ModernDashboardApp.tsx`

Before any view renders, you see these persistent elements:

### Header Bar (sticky top)
```
┌─────────────────────────────────────────────────────────────────────────────┐
│  [TrendingUp+Brain] PortfolioRisk Pro [AI] [Pro]                           │
│                                                                             │
│  ● Market Open | WiFi Live | 10:32 AM                                      │
│                                                                             │
│  [Overview] [Holdings] [Analytics ▼] [AI Assistant]  [🔔] [⋯]             │
└─────────────────────────────────────────────────────────────────────────────┘
```
- **Market status**: CLIENT-SIDE only — computed from `new Date().getHours()` (9-16=Open, 16-20=After Hours, else Closed)
- **Notification bell**: Opens notification drawer — **REAL** (`useNotifications()` composing `useSmartAlerts()` + `usePendingUpdates()`. `alertMappings.ts` maps ~20 flag types → titles + navigation actions. localStorage persistence. Commit `1505c1f1`)
- **Overflow (⋯)**: Settings (`⌘,`), Command Palette (`⌘K`)

### Floating "Ask AI" Button (fixed bottom-right)
- Blue gradient FAB with sparkles icon
- Opens `ChatInterface` as a slide-in modal from the right (`⌘J`)

### Command Palette (`⌘K`)
- **Component**: `CommandPalette` (inside `ModernDashboardApp`)
- **MOCK** — 4 hardcoded navigation commands (Go to Overview, Holdings, Analytics, Settings)

---

## Overview Page (`⌘1` / "Overview" tab)

**View key**: `score`
**Layout**: `PortfolioOverviewContainer` + `AssetAllocationContainer` + `PerformanceViewContainer` + `RiskAnalysisModernContainer` + `RiskMetricsContainer` arranged in a 2-column grid.

This is the main dashboard. Scrolling top to bottom:

### Row 1: Market Intelligence Banner
```
┌─────────────────────────────────────────────────────────────────────┐
│  Market Intelligence                                  1 Action Items │
│  Real-time market analysis and impact assessment                    │
│  ┌──────────────────────────┐  ┌──────────────────────────┐        │
│  │ EARNINGS    87% relevant │  │ FED         94% relevant │        │
│  │ NVIDIA Q3 earnings beat  │  │ Rate decision scheduled  │        │
│  │ [ACTIONABLE]             │  │                          │        │
│  └──────────────────────────┘  └──────────────────────────┘        │
│  ┌──────────────────────────┐  ┌──────────────────────────┐        │
│  │ TECHNICAL       72%     │  │ SENTIMENT        65%     │        │
│  │ Testing 200-day MA      │  │ Large cap tech buying    │        │
│  │                          │  │ [ACTIONABLE]             │        │
│  └──────────────────────────┘  └──────────────────────────┘        │
└─────────────────────────────────────────────────────────────────────┘
```
**Component**: `PortfolioOverviewContainer` → `PortfolioOverview`
**Data**: **REAL** — `useMarketIntelligence()` → `POST /api/positions/market-intelligence`. Earnings + sentiment events with relevance scores.

### Row 2: Smart Alerts
```
┌─────────────────────────────────────────────────────────────────────┐
│  Smart Alerts   5 Active                                            │
│  ┌─ red ─── DSU is 27.1% of exposure           [View Holdings] [✕] ─┐│
│  ┌─ amber ─ Tech concentration above X%       [View Holdings] [✕] ─┐│
│  ┌─ blue ── ...                                   [Explore]  [✕] ─┐│
└─────────────────────────────────────────────────────────────────────┘
```
**Component**: Inside `PortfolioOverview`
**Data**: **REAL** — `useSmartAlerts()` → `POST /api/positions/alerts`. Real position flags from backend. Commit `1dea17ba`.

### Row 3: Six Metric Cards (3x2 grid)
```
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│ TOTAL PORTFOLIO   │  │ DAILY P&L        │  │ RISK SCORE       │
│ VALUE             │  │                  │  │                  │
│ $2,847,291        │  │ $18,442          │  │ 92.10            │
│ +0.00%            │  │ +0.00%           │  │ High Risk        │
│ $0 vs prev day    │  │ Strong perf      │  │ +0.3 this week   │
│ [sparkline bg]    │  │ [sparkline bg]   │  │ [sparkline bg]   │
└──────────────────┘  └──────────────────┘  └──────────────────┘
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│ SHARPE RATIO     │  │ ALPHA GENERATION │  │ ESG SCORE        │
│                  │  │                  │  │                  │
│ 1.34             │  │ 5.80             │  │ 8.40             │
│ Poor             │  │ Outstanding      │  │ Superior         │
│ +0.12 improve    │  │ +1.2% this qtr   │  │ +0.6 improve     │
│ [sparkline bg]   │  │ [sparkline bg]   │  │ [sparkline bg]   │
└──────────────────┘  └──────────────────┘  └──────────────────┘
```
**Component**: Inside `PortfolioOverviewContainer` → `PortfolioOverview`
**Data**: **MIXED**

| Card | Big Number | Status |
|------|-----------|--------|
| Total Portfolio Value | `summary.totalValue` | **REAL** |
| Daily P&L | `summary.dayChange` | **REAL** |
| Risk Score | `summary.riskScore` | **REAL** |
| Sharpe Ratio | `summary.sharpeRatio` | **REAL** |
| Alpha Generation | "+5.8%" hardcoded | **MOCK** |
| ESG Score | "8.4" hardcoded | **MOCK** |

The labels ("Poor", "Outstanding", "Superior"), change text (+0.12, +1.2%, +0.6), trend badges (URGENT/CAUTION/WATCH), and sparkline backgrounds are all **MOCK**.

Each card has a tooltip (hover) showing AI insight text — **REAL** via `useMetricInsights()` → `POST /api/positions/metric-insights`.

### Hidden: View Mode Toggle + Settings Sheet

The `PortfolioOverview` header has buttons you might not notice:

- **View Mode toggle**: Compact / Detailed (default) / Pro / Institutional — changes card grid column count
- **AI Insights toggle** (Lightbulb icon): Shows/hides AI Recommendations section (see below)
- **Settings gear**: Opens a slide-in Sheet panel

**Settings Sheet** (all stored in local state only, NOT persisted to backend):
- Display Settings: 6 toggles (Show Performance Charts, Risk Metrics, Holdings, Market Events, Smart Alerts, AI Recommendations)
- Refresh Settings: Auto Refresh switch, Refresh Interval input, Real-Time Data switch
- Alert Settings: Loss Threshold %, Concentration Warning %, Volatility Alert %, Email/Push Notification switches
- Chart Settings: Default Timeframe select, Chart Type select, Benchmark input, Show Volume switch
- Export Settings: Report Format select, Include Charts switch, Scheduled Reports switch, Report Frequency select

All **MOCK** — no backend persistence, no effect on data.

### Hidden: AI Recommendations (toggle to show)

When AI Insights toggle is on, recommendation cards appear below the metric grid.

**Data**: **REAL** — `useAIRecommendations()` → `POST /api/positions/ai-recommendations`. Concentration analysis with priority ranking.

### Row 4: Two-Column Layout — Asset Allocation + Portfolio Performance
```
┌────────────────────────────┐  ┌─────────────────────────────────┐
│  Asset Allocation          │  │  Portfolio Performance          │
│  [Allocation] [Performance]│  │  Portfolio +12.8%  Benchmark    │
│                            │  │  +8.4%                          │
│  ● US Equity    45%        │  │  [Line] [Bar]  1D 1W [1M] 3M   │
│    $1,281,281  ↗ +2.3%    │  │  6M 1Y ALL                      │
│  ● Intl Equity  20%       │  │                                  │
│    $569,458    ↘ -0.8%    │  │  ┌──────────────────────────┐   │
│  ● Fixed Income 15%       │  │  │  Bar chart: Portfolio vs  │   │
│    $427,094    ↗ +0.5%    │  │  │  S&P 500 (green bars)    │   │
│  ● Real Estate  10%       │  │  └──────────────────────────┘   │
│    $284,729    ↗ +1.2%    │  │                                  │
│  ● Commodities   6%       │  │  Total Return  Benchmark  Alpha │
│    $170,837    ↘ -1.5%    │  │  +12.8%       +8.4%     +4.4%  │
│  ● Cash          4%       │  │  Volatility: 18.4%              │
│    $113,891    ↗ +0.1%    │  │                                  │
│                            │  │                                  │
│  Total Allocation: 100%   │  │                                  │
│  Last updated: 2/26/2026  │  │                                  │
└────────────────────────────┘  └─────────────────────────────────┘
```

**Left — Asset Allocation**:
- **Component**: `AssetAllocationContainer` → `AssetAllocation`
- **Data**: **REAL** — Portfolio weights from risk analysis, target allocation read/write via `useTargetAllocation()`/`useSetTargetAllocation()`, drift calculation, rebalance trade generator via `useRebalanceTrades()`. Commit `f2dc9b55`.

**Right — Portfolio Performance**:
- **Component**: `PerformanceViewContainer` -> `PerformanceView`
- **Data**: **REAL** — Period returns, risk metrics, sector+security attribution, benchmark selection, realized mode all wired.

### Row 5: Two-Column Layout — Advanced Risk Analysis + Risk Assessment
```
┌────────────────────────────┐  ┌─────────────────────────────────┐
│  Advanced Risk Analysis    │  │  Risk Assessment                │
│  [Risk Score] [Stress      │  │  Portfolio risk breakdown       │
│   Tests] [Hedging]         │  │  [Live Analysis]                │
│                            │  │                                  │
│  (see click-through        │  │  Value at Risk (VaR)  HIGH      │
│   details below)           │  │  -$42,891                       │
│                            │  │  95% confidence, 1-day          │
│                            │  │  ████████████████░░░ 85%        │
│                            │  │                                  │
│                            │  │  Beta Coefficient  MEDIUM       │
│                            │  │  1.23                           │
│                            │  │  ██████████████░░░░░ 62%       │
│                            │  │                                  │
│                            │  │  Volatility  MEDIUM             │
│                            │  │  18.4%                          │
│                            │  │  █████████████░░░░░░ 73%       │
│                            │  │                                  │
│                            │  │  Max Drawdown  LOW              │
│                            │  │  -8.7%                          │
│                            │  │  █████████░░░░░░░░░ 43%        │
└────────────────────────────┘  └─────────────────────────────────┘
```

**Left — Advanced Risk Analysis** (3 tabs):
- **Component**: `RiskAnalysisModernContainer` → `RiskAnalysis`

#### Tab: Risk Score (default)
4 expandable cards. Each shows: Name, Risk Level badge, Score (x/100), Description, Progress bar, Impact ($).

| Card | Score | Risk Level | Impact | Data |
|------|-------|------------|--------|------|
| Concentration Risk | 8.5/10 | High | -$56.9K | MOCK fallback |
| Correlation Risk | 6.8/10 | Medium | -$38.4K | MOCK fallback |
| Volatility Risk | 7.2/10 | High | -$42.7K | MOCK fallback |
| Liquidity Risk | 3.1/10 | Low | -$12.8K | MOCK fallback |

**Click to expand** each card: reveals Mitigation Strategy text + Implementation Timeline. All **MOCK**.

**REAL** — Risk factor descriptions (concentration, volatility, factor, sector) computed from real backend data. Commit `5831c982`.

#### Tab: Stress Tests

**REAL** — Full stress test engine (Wave 3h). 8 predefined scenarios from backend via `useStressScenarios()` + `useStressTest()`. 3 API endpoints. Commits `d1df3fee`→`a1d598fb`.

#### Tab: Hedging

**REAL** — 4-step workflow dialog (Review→Impact→Trades→Execute). `useHedgePreview()`, `useHedgeTradePreview()`, `useHedgeTradeExecute()` hooks wrapping `POST /api/hedging/preview` + `/api/hedging/execute`. Commit `18aa43ae`.

**Right — Risk Assessment**:
- **Component**: `RiskMetricsContainer` -> `RiskMetrics`
- **Data**: **REAL** — VaR/Beta/Volatility/Max Drawdown from `useRiskAnalysis()`.

---

## Holdings Page (`⌘2` / "Holdings" tab)

**View key**: `holdings`
**Component**: `HoldingsViewModernContainer` → `HoldingsView`
**File**: `packages/ui/src/components/portfolio/HoldingsView.tsx`

### Header Section
```
┌─────────────────────────────────────────────────────────────────────┐
│  Portfolio Holdings                           Total: $2,847,291     │
│  Last updated: 2/26/2026 10:32 AM                                  │
│                                                                     │
│  Connected: Schwab (Active) | SnapTrade (Active)                   │
│                                                                     │
│  [Search: _______________]  [Filter]  [Sort ▼]                     │
└─────────────────────────────────────────────────────────────────────┘
```
- Portfolio total value: **REAL** (from `summary.totalValue`)
- Last updated: **REAL** (from `summary.lastUpdated`)
- Connected accounts: **REAL** (from Plaid/SnapTrade connection status)

### Holdings Table (sortable, searchable)

```
┌────────┬───────────┬────────┬──────────┬─────────┬────────┬─────────┬───────┐
│ Ticker │ Name      │ Sector │ Shares   │ Value   │ Weight │ Beta    │ ...   │
├────────┼───────────┼────────┼──────────┼─────────┼────────┼─────────┼───────┤
│ AAPL   │ Apple Inc │ Tech   │ 150      │ $28.5K  │ 8.5%   │ 1.12    │       │
│ MSFT   │ Microsoft │ Tech   │ 85       │ $34.2K  │ 7.2%   │ 0.95    │       │
│ ...    │           │        │          │         │        │         │       │
└────────┴───────────┴────────┴──────────┴─────────┴────────┴─────────┴───────┘
```

| Column | Status | Notes |
|--------|--------|-------|
| Ticker | **REAL** | From adapter |
| Company Name | **REAL** | From adapter |
| Sector | **REAL** | From backend enrichment |
| Asset Class | **REAL** | From SecurityTypeService |
| Shares | **REAL** | From adapter |
| Avg Cost | **REAL** | From IBKR Flex / Schwab txns |
| Current Price | **REAL** | From `latest_price()` |
| Market Value | **REAL** | From adapter |
| Total Return $ / % | **REAL** | From adapter |
| Day Change $ / % | **REAL** | Per-position dayChange wired (Wave 2.5, `06e8759b`) |
| Portfolio Weight % | **REAL** | Calculated value/totalValue |
| Risk Score | **REAL** | 0-100 composite (vol/drawdown/beta/concentration). Commit `8a8445ad` |
| Beta | **REAL** | From factorBetas.market |
| Volatility | **REAL** | Per-position volatility wired (Wave 2.5) |
| Alerts | **REAL** | Badge + tooltip with alert messages. Commit `d644687f` |
| Sparkline trend | **REAL** | Per-position trend sparkline wired (Wave 2.5) |

### Click-through: Expandable Row Detail

Click any holding row to expand and see:
- **Factor Betas breakdown**: market, size, value, momentum, etc. — **REAL** (from `factorBetas` dict)
- **Risk Contribution %** — **REAL** (from `riskContributionPct` via euler_variance_pct in adapter)

### Bottom: Account Management
- Connected accounts cards with sync status
- "Connect Account" button
- "Refresh" button with spinner
- "Analyze Risk" button (triggers `IntentRegistry.triggerIntent('analyze-risk')`)

### Fallback State
When no portfolio data: renders a static mock array of 10 holdings (AAPL, MSFT, GOOGL, TSLA, AMZN, NVDA, META, JPM, BRK.B, JNJ).

---

## Factor Analysis Page (`⌘3` / Analytics > Factor Analysis)

**View key**: `factors`
**Layout**: Two-column — `FactorRiskModel` (2/3 width) + `RiskMetrics` (1/3 width)

### Left — Factor Risk Model (3 tabs)

**Component**: `FactorRiskModel` (NO container — used directly)
**File**: `packages/ui/src/components/portfolio/FactorRiskModel.tsx`

```
┌──────────────────────────────────────┐
│  Factor Risk Model                   │
│  Multi-factor risk attribution       │
│  R² = 0.847  [Active]                │
│                                      │
│  [Factor Exposure] [Risk Attribution]│
│  [Performance]                       │
└──────────────────────────────────────┘
```

#### Tab: Factor Exposure (default)

8 factor cards, each showing: factor name, significance badge (High/Medium/Low), beta exposure, description, t-statistic, risk contribution %, progress bar.

| Factor | Exposure | t-stat | Contribution | Significance |
|--------|----------|--------|-------------|-------------|
| Market (Beta) | +0.89 | 4.23 | 65.2% | High |
| Size (SMB) | -0.23 | -2.45 | -8.7% | Medium |
| Value (HML) | +0.15 | 1.87 | 12.3% | Medium |
| Momentum (WML) | +0.31 | 3.12 | 18.5% | High |
| Quality (QMJ) | +0.22 | 2.56 | 8.9% | Medium |
| Low Volatility | -0.18 | -1.92 | -6.4% | Low |
| Profitability | +0.28 | 2.89 | 11.2% | Medium |
| Investment | -0.12 | -1.45 | -4.3% | Low |

**REAL** — wired via `FactorRiskModelContainer` → `useRiskAnalysis()`. Real factor exposures, t-stats, significance, risk contributions.

#### Tab: Risk Attribution

5-source attribution breakdown with donut chart. **REAL** — from `useRiskAnalysis()` variance decomposition.

#### Tab: Performance

Monthly performance attribution table + risk-adjusted metrics. **REAL** — wired in Wave 2e (`dbcee8c9`).

### Right — Risk Assessment

Same `RiskMetricsContainer` → `RiskMetrics` as Overview page — **REAL**.

---

## Performance Page (`⌘4` / Analytics > Performance)

**View key**: `performance`
**Component**: `PerformanceViewContainer` → `PerformanceView`
**File**: `packages/ui/src/components/portfolio/PerformanceView.tsx`

### Header + Controls
```
┌─────────────────────────────────────────────────────────────────────┐
│  Performance Analytics                              ● Real-time     │
│  Last updated: 10:32 AM                                            │
│                                                                     │
│  [Standard] [Detailed]  [AI Insights]                              │
│  Period: [1M ▼]  Benchmark: [SPY ▼]  [Export ▼]  [Refresh]        │
└─────────────────────────────────────────────────────────────────────┘
```
- Period selector: 1M/3M/6M/1Y/3Y/5Y/MAX
- Benchmark selector: SPY/QQQ/VTI/Custom
- Export dropdown: PDF Report, Excel Workbook, CSV Data, Share Link
- User preferences persisted to `localStorage` key `'performance-preferences'`

### 4 Top Metric Cards
```
┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ Portfolio     │  │ Period       │  │ Alpha        │  │ Sharpe       │
│ Value         │  │ Return       │  │              │  │ Ratio        │
│ $1,247,850   │  │ +12.8%       │  │ +4.4%        │  │ 1.34         │
└──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘
```

| Card | Status |
|------|--------|
| Portfolio Value | **MOCK** — hardcoded $1,247,850 |
| Period Return | **REAL** — `periods[selectedPeriod].return` from adapter |
| Alpha | **REAL** (derived) — periodReturn - benchmarkReturn |
| Sharpe Ratio | **REAL** — `riskMetrics.sharpeRatio` from adapter |

Each card has a tooltip showing formula explanation.

### Tab: Attribution (default) — REAL

**REAL** — Sector + security attribution wired (`2315fa16`). Real sector performance rows and top contributors/detractors from backend data.

### Tab: Returns — REAL

Monthly returns from adapter. Risk-adjusted metrics (Information Ratio, Tracking Error, etc.) from `compute_performance_metrics()`.

### Tab: Benchmarks — REAL

Benchmark comparison with dynamic benchmark selection (SPY/QQQ/VTI/Custom). localStorage persistence. Commit `33e5b78b`.

### Realized Mode

**REAL** — Toggle between hypothetical and realized performance. `useRealizedPerformance()` mutation → `POST /api/performance/realized`. Institution/account filtering. P&L/income/data quality panels. Commit `ae290b35`.

---

## Strategy Builder Page (`⌘5` / Analytics > Strategy Builder)

**View key**: `strategies`
**Component**: `StrategyBuilderContainer` → `StrategyBuilder`
**File**: `packages/ui/src/components/portfolio/StrategyBuilder.tsx`

### 4 Tabs: Builder (default) | Marketplace | Performance | Active Strategies

#### Tab: Builder

**REAL** — Real optimization engine fully wired via `usePortfolioOptimization()`. Constraint configuration, objective selection, optimization execution. Results show optimal weights, expected return, risk metrics.

#### Tab: Marketplace

**REAL** — 6 curated YAML templates served via `GET /api/strategies/templates`. `useStrategyTemplates()` hook. Deploy → backtest with real ticker weights. Commits `d680cf50`, `1884c9c1`.

#### Tab: Performance

**REAL** — Rebuilt with real backtest data + 3 attribution tables. Sections:
- Summary metrics: Total Return, Ann Return, Sharpe, Max DD, Alpha, Beta, R², Info Ratio
- Annual Breakdown table (year-by-year portfolio vs benchmark)
- Security Attribution (per-ticker contribution, sorted by |contribution|)
- Sector Attribution (sector-level via FMP profiles)
- Factor Attribution (Market/Momentum/Value betas + Selection & Other)
- Empty state CTA when no backtest has been run

Backtest engine: `useBacktest()` → `POST /api/backtest`. `BacktestAdapter` with `AttributionRow` type. Commit `2f5320ca`.

#### Tab: Active Strategies

Future feature — strategy versioning/tracking. Not a wiring gap.

---

## Stock Research Page (`⌘6` / Analytics > Stock Research)

**View key**: `research`
**Component**: `StockLookupContainer` → `StockLookup`
**File**: `packages/ui/src/components/portfolio/StockLookup.tsx`

### Search + Empty State
```
┌─────────────────────────────────────────────────────────────────────┐
│  Stock Risk Lookup                                                  │
│  [Search: Enter symbol e.g. AAPL, TSLA __________]  [Search]       │
│                                                                     │
│  (empty state: search icon + "Search for a Stock" heading)          │
│                                                                     │
│  Quick Access: [AAPL] [TSLA] [NVDA] [JPM]                         │
└─────────────────────────────────────────────────────────────────────┘
```

**Search results dropdown** while typing: **MOCK** — constructs a single fake result from typed text (hardcoded price $150.00, change +$2.50).

### Stock Analysis Dashboard (after selecting a stock)

#### Header
```
┌─────────────────────────────────────────────────────────────────────┐
│  AAPL  Apple Inc.                          [Low Risk] badge         │
│  $178.52  +$2.50 (+1.42%)                 Market Cap: $2.8T        │
└─────────────────────────────────────────────────────────────────────┘
```
All header fields (price, change, market cap, risk rating) — **REAL** from `StockAnalysisAdapter`.

### 6 Tabs: Overview | Risk Factors | Technicals | Fundamentals | Peer Comparison | Portfolio Fit

#### Tab: Overview — REAL

4 metric cards (2x2):

| Card | Status |
|------|--------|
| VaR 95% | **REAL** — from adapter |
| Beta | **REAL** — regression_metrics.beta |
| Volatility % | **REAL** — volatility_metrics.annual_vol |
| Sharpe Ratio | **REAL** — from adapter |

Additional Risk Metrics card: VaR 99%, Max Drawdown %, S&P 500 Correlation, Sector — all **REAL**.

Risk Assessment descriptive paragraph based on risk rating level.

#### Tab: Risk Factors — REAL

**REAL** — Real `factor_summary` data wired (Wave 2.6, `03f010ea`). Max drawdown, vol metrics, sharpe, correlation, VaR all from backend. Factor cards show real per-stock risk data.

#### Tab: Technicals — REAL

| Element | Status |
|---------|--------|
| RSI card (value, Overbought/Neutral/Oversold label) | **REAL** |
| MACD card (value, Bullish/Bearish label) | **REAL** |
| Support & Resistance (prices + visual bar) | **REAL** |
| Bollinger Bands (position, interpretation) | **REAL** |

All from `technicals` object via `StockAnalysisAdapter`.

#### Tab: Fundamentals — PARTIAL REAL

4 metric cards (2x2):

| Card | Status |
|------|--------|
| P/E Ratio | **REAL** if available |
| ROE % | **REAL** if available |
| Debt/Equity | **REAL** if available |
| Profit Margin % | **REAL** if available |

Valuation Metrics card (P/B, ROE, Profit Margin progress bars) — **REAL** where available.

**Financial Health Score card** — **MOCK** (hardcoded: Profitability 85/100, Leverage 72/100, Valuation 45/100).

---

## Scenario Analysis Page (`⌘8` / Analytics > Scenario Analysis)

**View key**: `scenarios`
**Component**: `ScenarioAnalysisContainer` → `ScenarioAnalysis`
**File**: `packages/ui/src/components/portfolio/ScenarioAnalysis.tsx`

### Header
```
┌─────────────────────────────────────────────────────────────────────┐
│  Advanced Scenario Analysis           [What-If Analysis] badge      │
│                                       [Run Analysis] button         │
└─────────────────────────────────────────────────────────────────────┘
```
- "Run Analysis" triggers `runComprehensiveAnalysis()` → shows progress overlay → results summary
- **Results summary** (after completion): Timestamp, Confidence %, 4 mini cards (Expected Return, Volatility, Sharpe, VaR 95), Export + Details buttons
- Results data is **REAL** when `runScenarioFromInputs()` completes via `WhatIfAnalysisAdapter`

### 5 Tabs: Portfolio Builder | Session History | Stress Tests | Monte Carlo | Optimizations

All 5 phases of the Scenario Analysis overhaul are complete. Plan: `completed/SCENARIO_ANALYSIS_OVERHAUL_PLAN.md`.

#### Tab: Portfolio Builder (default)

**REAL** — 5 computed portfolio presets from real portfolio data (Phase 2, `627c167f`). Real what-if execution via `useWhatIfAnalysis()`. Editable weights with live recalculation.

#### Tab: Session History

**REAL** — Backend persistence via `/api/scenarios/history`. Auto-save, re-run, compare. `useScenarioHistory()` hook. Phase 4, commit `c3e4eb56`.

#### Tab: Stress Tests

**REAL** — 8 predefined scenarios from backend via `useStressScenarios()` + `useStressTest()`. Real execution with portfolio-specific results. Wave 3h, commits `d1df3fee`→`a1d598fb`.

#### Tab: Monte Carlo

**REAL** — Real Monte Carlo engine via `useMonteCarlo()`. Configurable params (simulations, horizon). Percentile paths + terminal distribution. Phase 3, commit `078aed92`.

#### Tab: Optimizations

**REAL** — Reads Strategy Builder optimization cache. Apply-as-what-if cross-link. Phase 5, commit `b6f3e45e`.

---

## AI Assistant (`⌘7` / "AI Assistant" button)

**View key**: `chat`
**Component**: `ChatInterface`
**Data**: Connected to real backend via `GatewayClaudeService` (gateway mode) or legacy chat endpoint. Full-screen view with `onChatTransition` callback.

---

## Settings Page (`⌘,` / overflow menu)

**View key**: `settings`
**Layout**: Stacked — `RiskSettingsContainer` + `AccountConnectionsContainer`

### Risk Settings
**Component**: `RiskSettingsContainer` → `RiskSettings`
**Data**: **REAL** — Reads from and saves to `/api/risk-settings`. Includes risk tolerance sliders, benchmark selection, alert thresholds.

### Account Connections
**Component**: `AccountConnectionsContainer`
**Data**: **REAL** — Shows connected brokerage accounts (Plaid, SnapTrade, IBKR) with sync status, reconnect, and disconnect actions.

---

## Data Status Summary (All Views) — Updated 2026-03-04

| View | Component | Status | Remaining Gaps |
|------|-----------|--------|----------------|
| Overview | PortfolioOverview | ✅ 100% | Alpha Generation + ESG Score cards show "—" (no backend data) |
| Overview | AssetAllocation | ✅ 100% | Target allocation read/write + rebalance wired |
| Overview | PerformanceViewContainer | ✅ 95% | Factor-level Brinson attribution (backlog) |
| Overview | RiskAnalysis | ✅ 100% | Risk factors, stress tests, hedging all real |
| Overview | RiskMetrics | ✅ 100% | VaR, beta, volatility, max drawdown real |
| Holdings | HoldingsView | ✅ 98% | Only `isProxy` hardcoded false |
| Factor Analysis | FactorRiskModel | ✅ 100% | All 3 tabs wired |
| Performance | PerformanceView | ✅ 95% | Realized mode + sector/security attribution. Factor Brinson backlog |
| Strategy Builder | StrategyBuilder | ✅ 95% | 6 templates, optimization, backtest + 3 attribution tables |
| Stock Research | StockLookup | ✅ 95% | Search dropdown not rendering results (hook works) |
| Scenarios | ScenarioAnalysis | ✅ 100% | All 5 phases complete |
| AI Assistant | ChatInterface | ✅ 100% | Real gateway backend |
| Settings | RiskSettings + AccountConnections | ✅ 100% | Real read/write |
| Notifications | NotificationCenter | ✅ 100% | Smart Alerts + pending updates + localStorage |

---

## Wave 1-3 Summary: COMPLETE

All Wave 1-3 wiring work is done. See `completed/FRONTEND_DATA_WIRING_AUDIT.md` for the detailed per-view status and `TODO.md` for remaining gaps (search dropdown, Brinson attribution, stale TODOs).

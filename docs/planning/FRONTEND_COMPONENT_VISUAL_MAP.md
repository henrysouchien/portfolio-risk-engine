# Frontend Component Visual Map

**Date**: 2026-03-03 (updated)
**Purpose**: Maps what you see on screen to the actual code components, so we can discuss changes using the same language. Includes every tab, click-through, expandable section, and dialog.

> Drift note: this doc started as a 2026-02-26 snapshot. Some deeper sections below are historical. Use the "Current Snapshot (2026-03-03)" section first when reconciling code vs docs.

### Related Docs
| Doc | Purpose |
|-----|---------|
| `FRONTEND_PHASE2_WORKING_DOC.md` | Phase 2 master doc — full mock data inventory (16 items) |
| `completed/FRONTEND_WAVE1_IMPLEMENTATION_PLAN.md` | Wave 1 implementation details for the components marked here |
| `COMPOSABLE_APP_FRAMEWORK_PLAN.md` | Phase 3 — the bigger picture this feeds into |

---

## Current Snapshot (2026-03-03)

| View | Actual container wiring | Current status |
|------|-------------------------|----------------|
| Overview (`score`) | `PortfolioOverviewContainer` + `AssetAllocationContainer` + `RiskAnalysisModernContainer` + `PerformanceViewContainer` + `RiskMetricsContainer` | Mixed real + fallback |
| Holdings (`holdings`) | `HoldingsViewModernContainer` -> `usePositions()` -> `/api/positions/holdings` | Mixed real + fallback |
| Factor Analysis (`factors`) | `FactorRiskModelContainer` + `RiskMetricsContainer` | Exposure/attribution real, performance tab still fallback |
| Performance (`performance`) | `PerformanceViewContainer` | Period/risk metrics real, several AI/contributor sections fallback |
| Strategy Builder (`strategies`) | `StrategyBuilderContainer` | Optimization hooks wired, template/backtest UI still mixed |
| Stock Research (`research`) | `StockLookupContainer` | Analysis real, search + risk-factors tab still mixed |
| Scenario Analysis (`scenarios`) | `ScenarioAnalysisContainer` | What-if execution wired; historical/stress/monte-carlo mostly placeholder |
| AI Assistant (`chat`) | `ChatInterface` | Real |
| Settings (`settings`) | `RiskSettingsContainer` + `AccountConnectionsContainer` | Real |

Known shell-level placeholders:

- Header notification center is initialized from hardcoded sample notifications.
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
- **Notification bell**: Opens notification drawer — **MOCK** (2 hardcoded notifications: "High Tech Concentration Detected" warning, "Portfolio Data Updated" success)
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
**Data**: **MOCK** — 4 hardcoded event cards. Each has: type badge, relevance %, description, timeline, confidence %, optional ACTIONABLE badge.

### Row 2: Smart Alerts
```
┌─────────────────────────────────────────────────────────────────────┐
│  Smart Alerts   3 Active                                            │
│  ┌─ red ─── Portfolio outperforming by X%       [Rebalance]  [✕] ─┐│
│  ┌─ amber ─ Tech concentration above X%       [View Holdings] [✕] ─┐│
│  ┌─ blue ── Healthcare opportunity identified     [Explore]  [✕] ─┐│
└─────────────────────────────────────────────────────────────────────┘
```
**Component**: Inside `PortfolioOverview`
**Data**: **MOCK** — 3 alerts generated on mount. Each has: severity color, message, action button, dismiss button.

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

Each card has a tooltip (hover) showing AI insight text — **MOCK**.

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

When AI Insights toggle is on, 3 recommendation cards appear below the metric grid:

| Card | Type | Priority | Expected Impact |
|------|------|----------|-----------------|
| Rebalancing Required | rebalance | HIGH | "+X% return improvement" |
| Add Tail Risk Hedge | hedge | MEDIUM | "Reduce drawdown by Y%" |
| International Opportunity | opportunity | LOW | "+Z% diversification benefit" |

Each card has: Type badge, Priority badge, Description, Confidence % bar, Timeframe, Action Items list, Risk Level, Estimated Return %.
**Data**: **MOCK** — generated on mount.

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
- **Data**: **MOCK** — The 6 asset class rows (US Equity 45%, Intl Equity 20%, Fixed Income 15%, Real Estate 10%, Commodities 6%, Cash 4%) with dollar values and daily changes are hardcoded in the presentation component. The container can pass real data from `useRiskAnalysis()` but the component falls back to mock when props don't match expected shape.
- **Click-through**: `[Performance]` tab shows the same 6 categories with individual holdings badges beneath each (AAPL, MSFT, GOOGL under US Equity, etc.) — also **MOCK**.

**Right — Portfolio Performance**:
- **Component**: `PerformanceViewContainer` -> `PerformanceView`
- **Data**: **MIXED** — real period/risk data is wired; several AI insight/contributor sections in `PerformanceView.tsx` still use fallback/static data.

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

Real data flows through if `data.riskFactors` array is populated by `RiskAnalysisAdapter`. The `overallRiskScore` and `riskCategory` in the header badge are **REAL** from `useRiskScore()`.

#### Tab: Stress Tests
4 scenario cards (not expandable):

| Scenario | Probability | Potential Loss | Data |
|----------|-------------|----------------|------|
| Market Crash (2008-style) | 5% | -$569K | **MOCK** |
| Tech Sector Decline | 10% | -$384K | **MOCK** |
| Interest Rate Spike | 25% | -$142K | **MOCK** |
| Geopolitical Crisis | 15% | -$298K | **MOCK** |

Plus: "Stress Test Summary" info card at bottom with methodology text.

#### Tab: Hedging
3 hedging strategy cards:

| Strategy | Duration | Cost | Protection | Data |
|----------|----------|------|------------|------|
| Put Options on QQQ | 3 months | $12.5K | -40% drawdown | **MOCK** |
| VIX Call Options | 1 month | $8.2K | Volatility spike | **MOCK** |
| Gold Position (5%) | 6 months | $142K | Inflation/crisis | **MOCK** |

Each has an **"Implement Strategy" button** that opens a **Dialog** with:
1. Strategy Overview card: Risk Reduction %, Implementation Cost $, Protected Value $
2. Portfolio Impact Analysis: Before/After VaR and Beta in 2x2 grid
3. Implementation Process: Animated step-by-step progress tracker (pending → processing → complete)
4. Success Message: Green checkmark on completion

All dialog content is **MOCK**.

**Right — Risk Assessment**:
- **Component**: `RiskMetricsContainer` -> `RiskMetrics`
- **Data**: **REAL (with fallback)** — VaR/Beta/Volatility/Max Drawdown are sourced from `useRiskAnalysis()` when available.

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
| Sector | **MOCK** — fallback "Unknown" | Backend has it but not threaded to summary endpoint |
| Asset Class | **REAL** | From SecurityTypeService |
| Shares | **REAL** | From adapter |
| Avg Cost | **MOCK** — fallback 0 | Available from IBKR Flex / Schwab txns, not threaded |
| Current Price | **MOCK** — fallback 0 | Available from `latest_price()`, not threaded |
| Market Value | **REAL** | From adapter |
| Total Return $ / % | **MOCK** — fallback 0 | Computable from cost basis + price |
| Day Change $ / % | **MOCK** — fallback 0 | Not threaded |
| Portfolio Weight % | **REAL** | Calculated value/totalValue |
| Risk Score | **MOCK** — fallback 0 | Per-position risk not implemented |
| Beta | **REAL** | From factorBetas.market |
| Volatility | **MOCK** — fallback 0 | Available in risk analysis, not threaded |
| AI Score | **MOCK** — fallback 0 | Not implemented |
| Sparkline trend | **MOCK** — fallback [] | No price history threaded |

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

All **MOCK** — hardcoded arrays.

#### Tab: Risk Attribution

5-source attribution breakdown with donut chart:

| Source | Contribution | Volatility |
|--------|-------------|-----------|
| Systematic Risk | 72.3% | 14.8% |
| Idiosyncratic Risk | 15.2% | 5.2% |
| Factor Interaction | 5.8% | 2.1% |
| Currency Risk | 3.4% | 1.8% |
| Liquidity Premium | 3.3% | 1.2% |

Total Risk: 20.4%. All **MOCK**.

#### Tab: Performance

Monthly performance attribution table + risk-adjusted metrics. All **MOCK**.

**Wave 1 Task 1b**: Create `FactorRiskModelContainer` to wire real factor data from `useRiskAnalysis()`.

### Right — Risk Assessment

Same `RiskMetrics` component as Overview page — **MOCK** (VaR, Beta, Volatility, Max Drawdown).

**Wave 1 Task 1c**: Same fix — replaced by `RiskMetricsContainer`.

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

### Tab: Attribution (default) — ALL MOCK

**Sector Performance** (6 rows):

| Sector | Allocation | Return | Risk | Momentum | Recommendation |
|--------|-----------|--------|------|----------|---------------|
| Technology | 42.3% | +28.7% | Medium | +5.2% | Maintain |
| Healthcare | 18.2% | +15.4% | Low | +2.1% | Add |
| Financials | 15.8% | +22.1% | Medium | +3.8% | Maintain |
| Consumer | 12.1% | +19.6% | Low | +1.5% | Hold |
| Industrials | 8.4% | +12.3% | Low | -0.3% | Review |
| Energy | 3.2% | +31.8% | High | +8.4% | Reduce |

Each row has a collapsible AI insight text.

**Top Contributors table** (5 rows): AAPL, MSFT, NVDA, GOOGL, AMZN — each with Contribution %, Return %, Weight %, Target Price, Analyst Rating.

**Top Detractors table** (3 rows): META, NFLX, PYPL — same columns.

All hardcoded. Not from adapter.

### Tab: Returns — ALL MOCK

Monthly returns table (Jan-Dec): Portfolio %, Benchmark %, Volatility %, Market Event note.

Advanced metrics row: Information Ratio 0.34, Tracking Error 4.2%, Up Capture 108.5%, Down Capture 92.3%.

### Tab: Benchmarks — PARTIAL REAL

Benchmark comparison cards. SPY benchmark data is **REAL** from adapter; no additional benchmarks connected yet.

### Hidden: AI Insights Section (toggle to show)

3 insight cards below tabs. **MOCK** — Performance insight (~75% confidence), Risk insight (~68%), Opportunity insight (~82%). Each has recommended action text.

---

## Strategy Builder Page (`⌘5` / Analytics > Strategy Builder)

**View key**: `strategies`
**Component**: `StrategyBuilderContainer` → `StrategyBuilder`
**File**: `packages/ui/src/components/portfolio/StrategyBuilder.tsx`

### 3 Tabs: Builder (default) | Optimizer | Backtest

#### Tab: Builder

**Strategy Templates** (3 cards):

| Template | Expected Return | Volatility | Risk Level | Sharpe |
|----------|----------------|-----------|-----------|--------|
| AI Momentum Alpha | 18.4% | 22.1% | 8/10 | 1.64 |
| Defensive Quality Growth | 12.8% | 16.3% | 6/10 | 1.21 |
| Income Plus Shield | 8.9% | 11.2% | 4/10 | 0.97 |

All **MOCK** — hardcoded `prebuiltStrategies` array.

**Custom Strategy Builder** below templates:
```
Strategy Name: [____________]  Type: [Balanced ▼]
Risk Tolerance: [═══════●═══] 5
Allocation: Stocks 60% | Bonds 30% | Commodities 5% | Cash 5%
[Run Optimization]
```
Allocation sliders for each asset class.

#### Tab: Optimizer

Before/after comparison when optimization runs. Currently uses mock `setTimeout` timer instead of real `onOptimize` callback.

#### Tab: Backtest

Mock backtesting with fake 4-second delay timer. Shows simulated equity curve and metrics.

**Data status**: **PARTIALLY MOCK** — The container fetches real optimization data from `usePortfolioOptimization()` and passes it as props, but the `StrategyBuilder` component **ignores all props** (destructured with `_` prefix). Uses internal mock state for everything.

**Wave 1 Task 1d**: Remove `_` prefixes from props, wire real `optimizationData` and `onOptimize` callback.

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

### 4 Tabs: Overview | Risk Factors | Technicals | Fundamentals

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

#### Tab: Risk Factors — ALL MOCK

6 risk factor cards (same values for every stock searched):

| Factor | Exposure | Risk Contribution |
|--------|---------|------------------|
| Market Risk | 78% | 65% |
| Sector Risk | 92% | 48% |
| Volatility Risk | 85% | 72% |
| Liquidity Risk | 15% | 12% |
| Currency Risk | 35% | 28% |
| Credit Risk | 5% | 3% |

Each has description text, exposure progress bar, contribution progress bar. All **MOCK** — hardcoded, never changes.

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

### 5 Tabs: Portfolio Builder | AI Optimization | Historical | Stress Tests | Monte Carlo

#### Tab: Portfolio Builder (default)

Left panel (2/3): Scrollable position list with editable weights.

| Ticker | Name | Weight | Data |
|--------|------|--------|------|
| AAPL | Apple Inc. | 8.5% | **MOCK** (local state) |
| MSFT | Microsoft Corp. | 7.2% | **MOCK** |
| NVDA | NVIDIA Corp. | 6.8% | **MOCK** |
| GOOGL | Alphabet Inc. | 5.9% | **MOCK** |
| TSLA | Tesla Inc. | 4.2% | **MOCK** |
| SPY | SPDR S&P 500 ETF | 25.4% | **MOCK** |
| QQQ | Invesco QQQ Trust | 15.8% | **MOCK** |
| VTI | Vanguard Total Market | 12.7% | **MOCK** |
| BND | Vanguard Bond Market | 8.9% | **MOCK** |
| GLD | SPDR Gold Trust | 4.6% | **MOCK** |

Per position: weight slider + input, price, shares, remove button. Bottom: add ticker input, rebalancing strategy buttons (Equal Weight, Market Cap, Risk Parity).

Right panel (1/3): Portfolio metrics summary + optimization preview.

#### Tab: AI Optimization — MOCK

3 optimization suggestion cards:

| Suggestion | Type | Impact |
|-----------|------|--------|
| Reduce Tech Concentration | concentration | +2.3% |
| Add International Diversification | diversify | +1.8% |
| Tail Risk Protection | hedge | -drawdown |

Each has: actions list (ticker, current weight → new weight), "Apply Optimization" button. All **MOCK**.

#### Tab: Historical — MOCK

4 historical scenario cards:

| Scenario | Portfolio Return | Max Drawdown |
|----------|-----------------|-------------|
| 2008 Financial Crisis | -38.5% | -52.3% |
| COVID-19 Pandemic | -33.9% | -33.9% |
| Dot-Com Crash | -49.1% | -78.4% |
| 1987 Black Monday | -22.6% | -22.6% |

Each has: VaR 95/99, description, factor impacts grid (equity/bonds/commodities/currencies %), "Run Scenario" button. All **MOCK**.

#### Tab: Stress Tests — MOCK

6 stress factor cards:

| Factor | Severity | Shock | Portfolio Impact |
|--------|----------|-------|-----------------|
| Interest Rate Shock | Extreme | +300bp | -18.4% |
| Credit Spread Widening | High | +200bp | -12.7% |
| Volatility Spike | High | VIX +100% | -22.1% |
| Currency Depreciation | Medium | USD -25% | -8.9% |
| Oil Price Surge | Medium | Oil +150% | -6.3% |
| Correlation Breakdown | Extreme | Corr +50% | -31.2% |

Each has description + "Run Stress Test" button. All **MOCK**.

#### Tab: Monte Carlo — MOCK

"Run Monte Carlo Simulation" button (mock 3-second simulation). After completion:
- Probability distribution visualization
- Percentile outcome cards (5th, 25th, 50th, 75th, 95th)
- Risk metrics: Expected Value, Std Dev, Probability of Loss, Worst Case

All **MOCK** simulation.

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

## Data Status Summary (All Views)

| View | Component | REAL | MOCK | Key Mock Items |
|------|-----------|------|------|---------------|
| Overview | PortfolioOverview | totalValue, dayChange, riskScore, sharpe | Alpha, ESG, market events, alerts, AI recs, insights labels |
| Overview | AssetAllocation | (adapter data available) | 6 asset class rows, holdings badges, all values |
| Overview | PerformanceViewContainer / PerformanceView | period returns, volatility, sharpe, beta (when adapter data exists) | AI insight cards, top contributors/detractors, monthly returns table |
| Overview | RiskAnalysis | overallRiskScore, riskCategory | Risk factor cards, stress tests, hedging strategies |
| Overview | RiskMetricsContainer / RiskMetrics | VaR, beta, volatility, max drawdown | Some derived text/labels |
| Holdings | HoldingsView | ticker, name, value, shares, weight, sector, avgCost, currentPrice, totalReturn | riskScore/aiScore/alerts/trend fields still fallback |
| Factor Analysis | FactorRiskModelContainer / FactorRiskModel | factor exposures + risk attribution | Performance tab metrics and header badges still fallback |
| Factor Analysis | RiskMetricsContainer / RiskMetrics | Same as overview risk metrics | Some derived text/labels |
| Performance | PerformanceView | periodReturn, alpha, sharpe, timeSeries, benchmark, some attribution | Portfolio value card, AI insights, contributor/detractor narratives, monthly returns, advanced metrics |
| Strategy Builder | StrategyBuilder | optimizationData props consumed from container | template defaults and backtest UX still mixed |
| Stock Research | StockLookup | price, beta, vol, sharpe, VaR, technicals, fundamentals | Risk Factors tab, search results, Financial Health Score |
| Scenarios | ScenarioAnalysis | portfolio-builder execution + run results integration | historical/stress/monte-carlo tabs and some helpers still placeholder |
| AI Assistant | ChatInterface | Connected to real backend | (none) |
| Settings | RiskSettings + AccountConnections | Real read/write | (none) |

---

## Wave 1 Summary: What Changes Where

| What You See | Where | Component | Currently | After Wave 1 |
|---|---|---|---|---|
| "Portfolio Performance" chart (bar chart, +12.8%) | Overview page, right column row 4 | `PerformanceChart` | MOCK | Replaced with real `PerformanceViewContainer` |
| "Risk Assessment" card (VaR, Beta, Vol, Drawdown) | Overview page, right column row 5 | `RiskMetrics` | MOCK | Wired to real data via `RiskMetricsContainer` |
| "Risk Assessment" card (same) | Factor Analysis page, right column | `RiskMetrics` | MOCK | Same — replaced by `RiskMetricsContainer` |
| "Factor Risk Model" card (Market Beta, Size, Value...) | Factor Analysis page, left column | `FactorRiskModel` | MOCK | Wired to real data via `FactorRiskModelContainer` |
| Strategy templates + optimization results | Strategy Builder page | `StrategyBuilder` | Uses real container props with fallbacks | Remaining work is mostly UX/backtest-depth, not base wiring |

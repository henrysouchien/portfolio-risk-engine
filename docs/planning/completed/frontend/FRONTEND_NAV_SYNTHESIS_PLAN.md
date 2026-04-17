# Frontend Navigation Synthesis Plan

**Status**: DRAFT
**Date**: 2026-03-12
**Synthesizes**: `CODEX_SIDEBAR_NAV_SPEC.md` (sidebar layout), `FRONTEND_LAYOUT_SPEC.md` (content architecture), `NAVIGATION_RESTRUCTURE_PLAN.md` (information architecture)
**Resolves**: T3 #28 (nav hides functionality), #32 (Scenario Analysis cramped), #33 (Strategy Builder confusing), #35-37a (Stock Lookup buried)
**Informed by**: `ADVISOR_WORKFLOW_RESULTS.md` (10 live agent runs)
**Supersedes**: `CODEX_FLATTEN_NAV_SPEC.md` (flat top-nav option — kept as reference but not used)

---

## Problem

The current nav shows 7 items (Overview, Holdings, Performance | Factors, Scenarios | Research, Strategy) grouped into 3 clusters with thin separators. Before the NavBar was extracted, 5 of these were hidden behind an Analytics dropdown — the app looked like it had 3 pages when it has 8. Related features are split across unrelated views (Factor Analysis and Stock Research are both "research"; Scenario Analysis and Strategy Builder are both "modeling").

## Design Principles

1. **Organize by user intent, not technical category** — 5 workflows: "what do I have?", "how am I doing?", "help me understand", "what if?", "do it"
2. **State → Understanding → Action** — top-to-bottom progression in the sidebar from observation to execution
3. **Exit ramps everywhere** — every page has contextual buttons that flow into the next workflow step, mirroring the agent's tool chains as user click paths
4. **Shallow overview, deep drill-down** — surface metrics on Dashboard, full analysis in Research

---

## Target Navigation

Persistent left sidebar (icon-only, `w-16`), modeled after the existing AnalystApp sidebar pattern (`CODEX_SIDEBAR_NAV_SPEC.md`). Header becomes a slim brand bar (logo + clock + notifications).

```
┌──────┬──────────────────────────────────────────┐
│ 📊   │  [Brand / Logo]   [LiveClock]   [Notif]  │
│ Dash  │─────────────────────────────────────────│
│      │                                          │
│ 📈   │                                          │
│ Perf  │            Content Area                  │
│      │                                          │
│ 🔍   │                                          │
│ Res   │                                          │
│      │                                          │
│ ⚡   │                                          │
│ Scen  │                                          │
│      │                                          │
│ 💱   │                                          │
│ Trade │                                          │
│      │                                          │
│      │                                          │
│ ──── │                                          │
│ 🤖 AI│                                          │
│ ⚙ Set│                                          │
└──────┴──────────────────────────────────────────┘
```

5 primary items in the sidebar, always visible. AI Assistant and Settings pinned to the bottom. No dropdowns, no horizontal nav. Net change: 7 → 5 nav items, every feature more visible.

### Why a sidebar (not flat top-nav)

- The AnalystApp already proves the pattern — same codebase, same styling conventions.
- Icon-only sidebar (`w-16`) costs minimal horizontal space (64px) while giving persistent, always-visible navigation.
- Vertical layout naturally supports the top-to-bottom workflow progression (Dashboard → Performance → Research → Scenarios → Trading).
- The header is freed up to be a clean brand bar — no nav logic competing with brand/clock/notifications.

### Why 5 sections (not 4)

The layout spec (`FRONTEND_LAYOUT_SPEC.md`) proposes 4 sections by folding Performance into Overview as a sparkline strip. We go with 5 because:

- Performance is already a rich multi-tab view (Attribution, Benchmarks, Period Analysis, Risk). Reducing it to a strip loses depth.
- "How am I doing?" is a distinct workflow from "what's happening right now?" — advisors navigate to Performance explicitly.
- 5 items still fits comfortably in a sidebar (down from the current 7).

### Keyboard Shortcuts

| Key | Section | Current mapping |
|-----|---------|----------------|
| ⌘1 | Dashboard | ⌘1 (score) — unchanged |
| ⌘2 | Performance | ⌘4 (performance) |
| ⌘3 | Research | ⌘3 (factors) + ⌘6 (research) |
| ⌘4 | Scenarios | ⌘8 (scenarios) + ⌘5 (strategies) |
| ⌘5 | Trading | new |
| ⌘6 | AI Assistant | ⌘7 (chat) |
| ⌘, | Settings | unchanged |

---

## Section Definitions

### 1. Dashboard — "What's happening?"

*Layout spec's Overview content in the nav restructure's Dashboard slot.*

The morning briefing surface. Scans wide, surfaces what's actionable.

```
┌──────────────────────────────────────────────────────────┐
│  Portfolio Value    Day Change    Risk Score    Compliance │  ← Hero metrics bar
├────────────────────────────┬─────────────────────────────┤
│                            │                             │
│   Holdings Table           │   Alerts & Briefing         │
│                            │                             │
│   - Sortable by value,     │   ● Risk violations (red)   │
│     P&L, weight, sector    │   ● Exit signals triggered  │
│   - Inline sparklines      │   ● Expiring options/hedges │
│   - Flag badges on rows    │   ● Concentration warnings  │
│     (concentration,        │   ● News (portfolio-relevant)│
│      large loss, etc.)     │   ● Upcoming earnings/divs  │
│                            │                             │
│   Click row → Research     │   Click alert → Detail      │
│                            │                             │
├────────────────────────────┴─────────────────────────────┤
│   Performance Strip                                      │
│   [YTD Return] [vs Benchmark] [Sharpe] [Volatility]     │
│   Mini cumulative return chart (sparkline, 6-month)      │
├──────────────────────┬───────────────────────────────────┤
│  Sector Allocation   │   Income & Cash Flow              │
│  (donut or bar)      │   Next 3 dividends, projected     │
│                      │   12-month income, margin cost    │
└──────────────────────┴───────────────────────────────────┘
```

**Key decision**: Holdings is absorbed here — the holdings table *is* the dashboard centerpiece (per layout spec). The separate HoldingsView becomes a "full-screen / expanded" mode within Dashboard, not a top-level nav slot.

**Data sources** (from layout spec §1):

| Card / Section | Primary Tool | Secondary |
|----------------|-------------|-----------|
| Hero metrics | `get_positions` | `get_risk_score` |
| Holdings table | `get_positions` (agent format — flags drive badge icons) | — |
| Risk violations | `get_risk_score` → `flags[]` | `get_risk_analysis` → `compliance` |
| Exit signals | `check_exit_signals` (batch across holdings) | — |
| Hedge alerts | `monitor_hedge_positions` | — |
| Concentration warnings | `get_positions` → `flags[]` | — |
| News | `get_portfolio_news` | `fmp:get_news` |
| Upcoming events | `get_portfolio_events_calendar` | — |
| Performance strip | `get_performance` (agent format) | — |
| Sector allocation | `get_positions` → `exposure.by_sector` | — |
| Income | `get_income_projection` | `list_income_events` |

**On load**: Parallel fetch of positions + risk_score + performance + news + calendar (mirrors the Q1 agent's wave 1 from `ADVISOR_WORKFLOW_RESULTS.md`).

**Exit ramps**:
- Click holding row → Research > Stock Lookup (ticker pre-loaded)
- Click risk violation → Research > Portfolio Risk (violation highlighted)
- Click "Simulate change" on selected holdings → Scenarios > What-If (tickers pre-filled)
- Click exit signal → Trading (sell preview pre-filled)

---

### 2. Performance — "How am I doing?"

*Existing Performance view, enriched per nav restructure Phase 5.*

Mostly unchanged. Tabs stay: **Attribution | Benchmarks | Risk Analysis | Period Analysis**

**Additions** (new summary cards above tabs):
- **Trading P&L** summary card — realized gains/losses at a glance (from `get_trading_analysis`)
- **Income projection** card — dividend/income forecast (from `get_income_projection`)
- **Realized vs hypothetical** toggle — already built (`POST /api/performance/realized`)

This is the backward-looking, read-only analysis surface. No modeling, no actions — just understanding returns and attribution.

**Data sources**: `get_performance`, `get_trading_analysis`, `get_income_projection`, `list_income_events`

---

### 3. Research — "Help me understand"

*Layout spec's "Analysis" concept (Risk + Research) under the nav restructure's "Research" label.*

Two sub-views accessible via a segmented control:

```
Research:  [Portfolio Risk]  [Stock Lookup]
```

#### 3a. Portfolio Risk

Deep risk analysis — the content currently crammed into Dashboard's RiskAnalysisModernContainer, given room to breathe.

```
┌──────────────────────────────────────────────────────────┐
│  Risk Score: 78.5    Compliance: ✗ 2 violations          │  ← Hero
│  Volatility: 20.1%   Beta: 1.02   Leverage: 1.56x       │
├──────────────────────────┬───────────────────────────────┤
│                          │                               │
│  Risk Attribution Table  │   Factor Exposures            │
│                          │                               │
│  Ticker | Weight | Risk  │   Market β: 1.02              │
│  Contribution | Beta     │   Momentum: -0.11             │
│                          │   Value: -0.26                │
│  (sorted by risk cont.)  │   Industry: 0.99              │
│                          │                               │
│                          │   Variance Decomposition      │
│                          │   [Factor 38%] [Idio 62%]     │
│                          │   (stacked bar)               │
│                          │                               │
├──────────────────────────┼───────────────────────────────┤
│                          │                               │
│  Industry Concentration  │   Compliance Detail           │
│  (bar chart)             │                               │
│                          │   ✗ Volatility: 20.1% > 20%  │
│                          │   ✗ Market β: 1.02 > limit   │
│                          │   ✓ Max weight: OK            │
│                          │   ✓ Factor variance: OK       │
│                          │                               │
├──────────────────────────┴───────────────────────────────┤
│  [Simulate hedge →]   [Run stress test →]   [View factors →] │
└──────────────────────────────────────────────────────────┘
```

**Data sources**: `get_risk_score`, `get_risk_analysis` (risk_attribution, factor_exposures, variance_decomposition, industry_concentration, compliance), `get_factor_analysis`, `get_factor_recommendations`

**Exit ramps**:
- "Simulate hedge" → Scenarios > What-If (defensive ETFs suggested)
- "Run stress test" → Scenarios > Stress Test
- "View factors" → factor correlation detail (expand in-place or modal)

**Implementation**: Composes existing `FactorRiskModelContainer` + `RiskAnalysisModernContainer` content into a unified layout. Not a rewrite — a recomposition.

#### 3b. Stock Lookup

Stock evaluation with automatic portfolio fit analysis. The layout spec's key insight: *every research workflow ends with `run_whatif`* — the Portfolio Fit card is not optional, it's the centerpiece.

```
┌──────────────────────────────────────────────────────────┐
│  Search: [____________]  or click a holding from Dashboard │
├──────────────────────────────────────────────────────────┤
│  ┌─── Stock Profile ──────────────────────────────────┐  │
│  │ NVDA  $186.03  +0.7%     Semiconductors            │  │
│  │ Mkt Cap: $4.5T   Vol: 51%   Beta: 2.35            │  │
│  │ Sharpe: 1.28   Max DD: -63%   Alpha: +3.2%/mo     │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  ┌─── Portfolio Fit (auto-runs on ticker entry) ──────┐  │
│  │ Current weight: 21.5%   Risk contribution: 21.6%  │  │
│  │ Sector overlap: Technology already at 17.7%        │  │
│  │                                                    │  │
│  │ What-if +5%:                                       │  │
│  │   Vol: 23.7% → 22.3% ✓   Compliance: PASS        │  │
│  │   Concentration: improves (HHI -0.03)             │  │
│  │                                                    │  │
│  │ [Adjust size ▾]  [Preview trade →]                │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  ┌── Tabs ────────────────────────────────────────────┐  │
│  │ [Technicals] [Estimates] [News] [Factor Exposure]  │  │
│  │ (content loads on tab click — lazy)                │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  ┌─── Compare Mode ──────────────────────────────────┐  │
│  │ + Add ticker   [AAPL] [MSFT] [GOOGL]              │  │
│  │ Side-by-side: Vol | Beta | Sharpe | Alpha          │  │
│  │   What-if compliance for each                      │  │
│  │   "Best fit: GOOGL (passes all risk checks)"       │  │
│  └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

**Data sources**: `analyze_stock`, `run_whatif` (auto), `get_positions` (pre-loaded), `fmp:get_technical_analysis`, `fmp:get_estimate_revisions`, `fmp:get_news`, `get_factor_analysis`

**Compare mode** (from layout spec §2b): Add 2-4 tickers → auto-run `analyze_stock` + `run_whatif` for each → side-by-side table with compliance pass/fail highlighted → surface "best fit" recommendation.

**Exit ramps**:
- "Preview trade" → Trading (ticker + quantity pre-filled)
- "Adjust size" → Scenarios > What-If (ticker pre-filled)

---

### 4. Scenarios — "What if?"

*Layout spec's "Tools" content, nav restructure's card-based entry and "Scenarios" label.*

#### Landing Page

Card grid — each card describes a tool with a one-line purpose. Guided entry instead of a wall of tabs.

```
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  What-If Builder  │  │  Optimize        │  │  Backtest        │
│  Edit weights,    │  │  Find optimal    │  │  Test allocation │
│  test allocation  │  │  allocation for  │  │  against history │
│  changes          │  │  your risk       │  │                  │
│                   │  │  tolerance       │  │                  │
└──────────────────┘  └──────────────────┘  └──────────────────┘
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  Stress Tests    │  │  Monte Carlo     │  │  Rebalance       │
│  See how crashes │  │  Simulate 1000s  │  │  Generate trades │
│  would affect    │  │  of possible     │  │  to hit target   │
│  your portfolio  │  │  futures         │  │  weights         │
└──────────────────┘  └──────────────────┘  └──────────────────┘
┌──────────────────┐
│  Tax Harvest     │
│  Find harvest    │
│  candidates,     │
│  estimate savings│
└──────────────────┘
```

#### Full-Width Tool Views

Clicking a card replaces the landing grid with a **full-width tool view** — the entire content area below the nav. Each tool gets full viewport width and height for inputs, results, charts, and action buttons. A back arrow / breadcrumb returns to the card grid.

This directly resolves #32 (Scenario Analysis cramped) and #33 (Strategy Builder confusing) by giving each tool its own page instead of cramming them into tabs within a card.

#### What-If Simulator (full-width)

```
┌──────────────────────────────────────────────────────────┐
│  ← Scenarios  /  What-If Simulator                       │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  Adjust weights:                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │ NVDA    21.5% → [___]%   [slider]              │    │
│  │ DSU     29.1% → [___]%   [slider]              │    │
│  │ + Add ticker: [AGG___]  weight: [10]%          │    │
│  └─────────────────────────────────────────────────┘    │
│                                                          │
│  [Run Simulation]                                        │
│                                                          │
│  ┌─── Results ────────────────────────────────────────┐  │
│  │           Before    After     Delta                │  │
│  │ Vol       20.1%     15.3%     -4.8%  ✓            │  │
│  │ Beta      1.02      0.80      -0.22  ✓            │  │
│  │ HHI       0.152     0.117     -0.035 ✓            │  │
│  │ Max wt    29.1%     20.3%     -8.8%  ✓            │  │
│  │ Compliant NO        YES       ──── IMPROVED       │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  [Generate trades →]  [Save scenario]  [Compare →]       │
└──────────────────────────────────────────────────────────┘
```

**Tool**: `run_whatif` (target_weights or delta_changes)

#### Scenario Comparison (full-width)

Compare 2-4 what-if or optimization scenarios side by side.

**Tool**: `compare_scenarios`
**Entry**: "Compare" button from What-If, or directly from landing card with saved scenarios.
**Exit**: "Implement Scenario B →" generates rebalance trades for the winning scenario.

#### Backtest (full-width)

Historical what-if: "how would this allocation have performed?"

**Tool**: `run_backtest` (weights + benchmark + period)
**Output**: Monthly return series, annual breakdown, max drawdown, Sharpe, vs benchmark chart.

#### Stress Tests / Monte Carlo (full-width)

Currently tabs within ScenarioAnalysisContainer — each gets its own full-width view.

**Tools**: Stress tests via `run_stress_test()` / `get_stress_scenarios()`. Monte Carlo via `run_monte_carlo()`.

#### Rebalance (full-width)

Target allocation → drift calculation → trade generation.

**Tools**: `get_target_allocation` + `get_positions` → drift calc → `preview_rebalance_trades`
**Exit ramp**: "Preview all trades →" → Trading section.

#### Tax Harvest (full-width)

**Tool**: `suggest_tax_loss_harvest`
**Output**: Tiered harvest candidates (clean / wash-sale risk / small), estimated tax savings, replacement suggestions.
**Exit ramp**: "Sell for harvest →" → Trading section.

#### Cross-references between tools

The key UX pattern (from layout spec): tools link to each other contextually.

```
What-If  ──"Compare"──→  Scenario Comparison
What-If  ──"Generate trades"──→  Rebalance
Stress Test  ──"Optimize to reduce this risk"──→  Optimize
Optimize  ──"Backtest this"──→  Backtest
Backtest  ──"Set as target allocation"──→  Rebalance
Rebalance  ──"Preview all trades"──→  Trading
Tax Harvest  ──"Sell for harvest"──→  Trading
```

#### What gets killed

| Current element | Fate | Reason |
|----------------|------|--------|
| Historical Scenarios tab | Removed | Was placeholder / disabled |
| Active Strategies tab | Removed | Was always empty, no persistence |
| Strategy Marketplace tab | "Templates" dropdown within Optimize | Not a standalone view |

---

### 5. Trading — "Do it"

*New section — from both layout spec §4 and nav restructure §5.*

No dedicated trading view exists today — all trading goes through AI chat. This section surfaces execution capabilities directly.

```
┌──────────────────────────────────────────────────────────┐
│  Trade                                                   │
├──────────────────────────────────────────────────────────┤
│  ┌─── Quick Trade ───────────────────────────────────┐  │
│  │ [BUY/SELL ▾]  [GOOGL___]  [10 shares]  [Market ▾] │  │
│  │                                                    │  │
│  │ [Preview Trade]                                    │  │
│  │                                                    │  │
│  │ Est. cost: $3,087   Commission: $1.00              │  │
│  │ New weight: 7.2%    Compliance: PASS ✓             │  │
│  │                                                    │  │
│  │ [Execute Trade]                                    │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  ┌─── Open Orders ────────────────────────────────────┐  │
│  │ (from get_orders — active/pending with cancel)     │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  ┌─── Baskets ────────────────────────────────────────┐  │
│  │ (list_baskets → basket management + batch execute) │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  ┌─── Hedge Monitor ─────────────────────────────────┐  │
│  │ (expiry alerts, delta drift, roll recommendations) │  │
│  └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

**Tools**: `preview_trade`, `execute_trade`, `preview_option_trade`, `execute_option_trade`, `preview_futures_roll`, `execute_futures_roll`, `get_orders`, `cancel_order`, basket tools (`create_basket`, `list_baskets`, `get_basket`, `update_basket`, `delete_basket`, `create_basket_from_etf`, `preview_basket_trade`, `execute_basket_trade`), `monitor_hedge_positions`

---

## Cross-Cutting: AI Chat Panel

Available as a slide-out panel from any page (per layout spec §5). The chat is the **unstructured** way to access the same workflows the structured UI provides.

- **From Dashboard**: "Give me a morning briefing" → agent runs Q1 workflow
- **From Research**: "Should I add NVDA?" → agent runs research + what-if, renders Portfolio Fit inline
- **From Scenarios**: "What if I shift 10% to bonds?" → runs what-if, shows results in chat AND can update the tool view
- **From Trading**: "Sell NVDA and buy AGG" → generates preview, asks for confirmation

Power users use the nav. New users or complex questions use chat. Both access the same tools.

---

## Navigation Flow — Exit Ramps

Every page connects to the next natural step. The agent's tool chains become the user's click paths.

```
Dashboard
  ├── Click holding row ──────────→ Research > Stock Lookup (ticker pre-loaded)
  ├── Click risk violation ────────→ Research > Portfolio Risk (violation highlighted)
  ├── Click "Simulate change" ─────→ Scenarios > What-If (tickers pre-filled)
  └── Click exit signal ──────────→ Trading (sell preview pre-filled)

Research > Portfolio Risk
  ├── "Simulate hedge" ───────────→ Scenarios > What-If (defensive ETFs)
  └── "Run stress test" ──────────→ Scenarios > Stress Test

Research > Stock Lookup
  ├── "Preview trade" ────────────→ Trading (ticker + quantity)
  └── "Adjust size" ──────────────→ Scenarios > What-If (ticker pre-filled)

Scenarios > What-If
  ├── "Generate trades" ──────────→ Scenarios > Rebalance (scenario weights)
  └── "Compare" ──────────────────→ Scenarios > Scenario Comparison

Scenarios > Rebalance
  └── "Preview all trades" ────────→ Trading (batch preview)

Scenarios > Tax Harvest
  └── "Sell for harvest" ─────────→ Trading (sell preview)
```

---

## What Gets Cut / Merged

| Current nav item (7) | Target | Rationale |
|----------------------|--------|-----------|
| Overview (⌘1) | → **Dashboard** (⌘1) | Renamed. Enriched with alerts panel + integrated holdings. |
| Holdings (⌘2) | → **Dashboard** (absorbed) | Holdings table is the dashboard centerpiece, not a separate page. |
| Performance (⌘4) | → **Performance** (⌘2) | Stays standalone. Enriched with Trading P&L + Income cards. |
| Factors (⌘3) | → **Research > Portfolio Risk** (⌘3) | Merged with risk analysis into one "understand" surface. |
| Scenarios (⌘8) | → **Scenarios** (⌘4, expanded) | Absorbs Strategy Builder. Card-based entry → full-width tools. |
| Research (⌘6) | → **Research > Stock Lookup** (⌘3) | Elevated from buried position. Auto Portfolio Fit added. |
| Strategy (⌘5) | → **Scenarios** (merged) | Optimize/Efficient Frontier live alongside What-If + Backtest. |
| — | **Trading** (⌘5, new) | New execution surface. |

---

## Implementation Phases

### Phase 0: Sidebar Layout — Codex Spec Surgery
**Scope**: Create sidebar, restructure root layout, slim the header.
**Spec**: `CODEX_SIDEBAR_NAV_SPEC.md` (follow exactly)

1. **Create `AppSidebar.tsx`** — new component at `frontend/packages/ui/src/components/dashboard/AppSidebar.tsx`, modeled after AnalystApp's sidebar (lines 35–71). Icon-only (`w-16`), `ViewId`-typed props (no string→ViewId cast needed). 8 view icons in 3 groups (Portfolio / Analysis / Tools) with horizontal separators. AI + Settings pinned to bottom via `mt-auto`.
2. **Restructure root layout** in `ModernDashboardApp.tsx` — change from vertical (`flex flex-col min-h-screen`) to horizontal (`flex h-screen`). Sidebar as first child, content area wrapped in `flex flex-1 flex-col min-w-0`.
3. **Slim the header** — delete dropdown nav JSX (~276 lines, lines 560–835). Keep brand section, LiveClock, NotificationCenter. Remove `overflow-visible` (was needed for dropdown menus).
4. **Clean up imports** — remove 8 unused icons + DropdownMenu import, add AppSidebar import.

**Files**: `AppSidebar.tsx` (new, ~80 lines), `ModernDashboardApp.tsx` (~270 lines removed)
**Risk**: Minimal — follows proven AnalystApp sidebar pattern. Floating elements (AI chat, artifact panel, command palette) all use `fixed` positioning, unaffected by layout change.

### Phase 1: Sidebar Items 7 → 5
**Scope**: Update AppSidebar groups, ViewId type, keyboard shortcuts, view routing.

1. **`AppSidebar.tsx`** — Replace sidebar groups with 5-section IA:
   - **Main group**: Dashboard (`score`, Eye, ⌘1), Performance (`performance`, TrendingUp, ⌘2)
   - **Analysis group**: Research (`research`, Search, ⌘3), Scenarios (`scenarios`, Shield, ⌘4)
   - **Execution group**: Trading (`trading`, new icon, ⌘5)
   - **Bottom**: AI Assistant (`chat`, ⌘6), Settings (`settings`, ⌘,)

2. **`uiStore.ts`** — Add `'trading'` to ViewId union. Keep old values for backward compat during transition.

3. **`ModernDashboardApp.tsx`** → `renderMainContent()`:
   - `holdings` → redirect to `score` (absorbed into Dashboard)
   - `factors` → redirect to `research`
   - `strategies` → redirect to `scenarios`
   - `trading` → new minimal placeholder (orders card + "coming soon")

4. **Command palette** — update section mappings

**Files**: ~3-4 files (AppSidebar.tsx, uiStore.ts, ModernDashboardApp.tsx, command-palette)

### Phase 2: Research Merge
**Scope**: Combine Factor Analysis + Stock Lookup into one Research section with Portfolio Risk / Stock Lookup sub-views.

1. Create `ResearchContainer.tsx` — orchestrator with segmented control
2. Compose existing `FactorRiskModelContainer` + `StockLookupContainer` as sub-views
3. Add risk analysis content (from RiskAnalysisModernContainer) to Portfolio Risk sub-view
4. Add exit ramp buttons ("Simulate hedge →", "Run stress test →")

**Reuses**: Existing containers as sub-components. Not a rewrite — a recomposition.
**Files**: ~3-4 new/modified

### Phase 3: Scenarios Overhaul
**Scope**: Replace cramped tab-in-card layout with card-based landing → full-width tool views. Biggest UX win.

1. Create `ScenariosContainer.tsx` — landing page with entry card grid
2. Create `ScenariosRouter.tsx` (or state-driven) — routes card clicks to full-width tool views
3. Each tool (What-If, Optimize, Backtest, Stress, Monte Carlo, Rebalance, Tax) gets full content area
4. Add breadcrumb navigation (← Scenarios / What-If Builder)
5. Wire cross-reference exit ramps between tools
6. Remove dead weight: Historical Scenarios placeholder, Active Strategies empty tab
7. Strategy Marketplace → "Templates" dropdown within Optimize

**Existing containers reused**: ScenarioAnalysisContainer internals are decomposed — the individual tool panels become standalone full-width views.
**Files**: ~6-8 new/modified

### Phase 4: Dashboard Enrichment
**Scope**: Upgrade Overview into the layout spec's morning briefing surface.

1. Integrate holdings table into Dashboard layout (from layout spec §1 wireframe)
2. Add Alerts & Briefing panel (risk violations, exit signals, hedge expiry, news, events)
3. Add Performance strip with sparkline
4. Add Sector Allocation + Income cards
5. Wire exit ramps (click holding → Research, click alert → detail, etc.)

**Dependencies**: Phase 2 (Research must exist for cross-nav links)
**Files**: ~4-6 new/modified

### Phase 5: Trading Section
**Scope**: Build the Trading view with orders, quick trade, baskets, hedge monitor.

1. Create `TradingContainer.tsx` — card-based layout
2. Create sub-components: `QuickTradeCard`, `OrdersCard`, `BasketsCard`, `HedgeMonitorCard`
3. Wire to existing MCP tools via hooks or direct API calls
4. Receive context from exit ramps (pre-filled ticker, quantity, sell direction)

**Files**: ~5-8 new files

### Phase 6: Performance Enrichment
**Scope**: Add Trading P&L summary and Income projection to Performance section.

1. Add summary cards above existing PerformanceViewContainer tabs
2. Wire `get_trading_analysis` and `get_income_projection` data
3. Add realized vs hypothetical toggle prominence

**Files**: ~2-3 files

### Phase 7: Polish & Cleanup
**Scope**: Remove transitional aliases, dead ViewIds, unused containers.

1. Remove `holdings`, `factors`, `strategies` redirect handlers
2. Remove dead ViewId values from type union
3. Clean up old container imports
4. Update all deep links / bookmarks
5. Final keyboard shortcut audit

---

## Suggested Execution Order

Phases 0-1 first — they're the nav surgery. Immediate, low risk, visible improvement. Can be done in a single session.

Then the priority order for content phases:

1. **Phase 3** (Scenarios overhaul) — highest UX impact, resolves #32 + #33, most user-visible improvement
2. **Phase 2** (Research merge) — resolves #35-37a, unlocks the Portfolio Fit workflow
3. **Phase 4** (Dashboard enrichment) — depends on Phase 2 for cross-nav links
4. **Phase 5** (Trading) — new capability, no urgency (AI chat covers this today)
5. **Phase 6** (Performance enrichment) — polish
6. **Phase 7** (Cleanup) — after everything stabilizes

---

## Migration Notes

- **No backend changes** — all restructuring is frontend-only
- **Sidebar pattern proven** — AnalystApp already uses the same sidebar approach (`CODEX_SIDEBAR_NAV_SPEC.md` §Reference). Same styling, same `ViewId` typing, same keyboard shortcut pattern.
- **NavBar.tsx preserved** — not deleted, kept as flat-nav fallback option (unused but importable)
- **Layout shift** — root layout changes from vertical (`flex-col`) to horizontal (`flex`). All `fixed`-position floating elements (AI chat modal, artifact panel, command palette, background orbs) are unaffected.
- **Content area is 64px narrower** — sidebar is `w-16`. No layout changes needed for content containers; they already use flex/responsive sizing.
- **Lazy loading preserved** — new containers use `React.lazy()` (per `FRONTEND_PERFORMANCE_PLAN.md` Phase 2)
- **Existing containers reused** — FactorRiskModelContainer, StockLookupContainer, ScenarioAnalysisContainer internals are composed into new orchestrators, not rewritten
- **Old ViewId values kept as aliases** during transition (Phases 1-6). Removed in Phase 7.
- **Theme system preserved** — all new components respect `data-visual-style` attribute (per `FRONTEND_THEME_SYSTEM_PLAN.md`)
- **Agent format compatibility** — Dashboard alerts panel consumes the same flags the AI agent reads from `get_positions`, `get_risk_score`, etc.

---

## What This Plan Does NOT Cover

- Component-level visual design (colors, spacing, animations) — follows existing design system
- Mobile responsiveness
- AI chat integration with structured views (chat updating tool views)
- New backend endpoints — all tools already exist via MCP
- AnalystApp (only covers ModernDashboardApp)

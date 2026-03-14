# Frontend Layout Spec — Advisor Toolbox

> **Date**: 2026-03-12
> **Informed by**: Advisor Workflow Experiment (10 live agent runs, `ADVISOR_WORKFLOW_RESULTS.md`)
> **Design principle**: State → Understanding → Action

---

## Navigation Structure

```
┌─────────────────────────────────────────────────────┐
│  [Logo]   Overview   Analysis   Tools   Trade   [AI Chat]  │
└─────────────────────────────────────────────────────┘
```

4 sections + persistent AI chat toggle. Linear progression left→right from passive observation to active execution.

---

## 1. Overview — "What do I need to know?"

The morning briefing surface. Scans wide, surfaces what's actionable. This is the page you open every morning.

### Layout

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
│                                                          │
│   Performance Strip                                      │
│   [YTD Return] [vs Benchmark] [Sharpe] [Volatility]     │
│   Mini cumulative return chart (sparkline, 6-month)      │
│                                                          │
├──────────────────────┬───────────────────────────────────┤
│                      │                                   │
│  Sector Allocation   │   Income & Cash Flow              │
│  (donut or bar)      │   Next 3 dividends, projected     │
│                      │   12-month income, margin cost    │
│                      │                                   │
└──────────────────────┴───────────────────────────────────┘
```

### Data Sources (MCP tools)

| Card / Section | Primary Tool | Secondary |
|----------------|-------------|-----------|
| Hero metrics | `get_positions` | `get_risk_score` |
| Holdings table | `get_positions` (agent format — includes flags) | — |
| Risk violations | `get_risk_score` → `flags[]` | `get_risk_analysis` → `compliance` |
| Exit signals | `check_exit_signals` (batch across holdings) | — |
| Hedge alerts | `monitor_hedge_positions` | — |
| Concentration warnings | `get_positions` → `flags[]` (auto-generated) | — |
| News | `get_portfolio_news` (stock mode) | `fmp:get_news` |
| Upcoming events | `get_portfolio_events_calendar` (earnings + dividends) | — |
| Performance strip | `get_performance` (agent format) | — |
| Sector allocation | `get_positions` → `exposure.by_sector` | — |
| Income | `get_income_projection` | `list_income_events` |

### Behavior
- **On load**: Parallel fetch of positions + risk_score + performance + news + calendar (mirrors Q1 agent's wave 1)
- **Alerts panel**: Sorted by severity (error → warning → info). Each alert is clickable — navigates to the relevant detail view.
- **Holdings row click**: Navigate to Analysis → Stock Research with that ticker pre-loaded
- **"What if" quick action**: Select 1+ holdings → "Simulate change" button → opens Tools → What-If with those tickers pre-filled
- **Flag badges on holdings rows**: Driven by `get_positions` flags (concentration, large_loss, leveraged, etc.) — same flags the agent reads

---

## 2. Analysis — "Help me understand"

The deep-dive surface. Two modes: **Portfolio Risk** and **Stock Research**. This is where the agent goes 10-17 tools deep.

### Sub-navigation

```
┌─────────────────────────────────────────┐
│  Analysis:  [Risk]  [Research]          │
└─────────────────────────────────────────┘
```

### 2a. Risk View

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
│  "Why does KINS at 13%   │   Variance Decomposition      │
│   contribute 28% of      │   [Factor 38%] [Idio 62%]    │
│   risk?"                 │   (stacked bar)               │
│                          │                               │
├──────────────────────────┼───────────────────────────────┤
│                          │                               │
│  Industry Concentration  │   Compliance Detail           │
│  (bar chart — SOXX 25%,  │                               │
│   XOP 9%, SLV 5%, etc.)  │   ✗ Volatility: 20.1% > 20% │
│                          │   ✗ Market β: 1.02 > limit   │
│                          │   ✓ Max weight: OK            │
│                          │   ✓ Factor variance: OK       │
│                          │                               │
├──────────────────────────┴───────────────────────────────┤
│                                                          │
│  [Simulate hedge →]   [Run stress test →]   [View factors →] │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

**Action ramps** (bottom row): Each button navigates to Tools with context pre-filled:
- "Simulate hedge" → Tools → What-If with defensive ETFs suggested
- "Run stress test" → Tools → Backtest with stress scenarios
- "View factors" → Factor correlation detail (expand in-place or modal)

### Data Sources

| Section | Tool |
|---------|------|
| Risk score + compliance | `get_risk_score` |
| Risk attribution table | `get_risk_analysis` → `risk_attribution` |
| Factor exposures | `get_risk_analysis` → `factor_exposures` |
| Variance decomposition | `get_risk_analysis` → `variance_decomposition` |
| Industry concentration | `get_risk_analysis` → `industry_concentration` |
| Compliance detail | `get_risk_analysis` → `compliance` |
| Factor deep-dive (expanded) | `get_factor_analysis` |
| Hedge suggestions | `get_factor_recommendations` |

### 2b. Research View

```
┌──────────────────────────────────────────────────────────┐
│  Search: [____________]  or click a holding from Overview │  ← Entry
├──────────────────────────────────────────────────────────┤
│                                                          │
│  ┌─── Stock Profile ──────────────────────────────────┐  │
│  │ NVDA  $186.03  +0.7%     Semiconductors            │  │
│  │ Mkt Cap: $4.5T   Vol: 51%   Beta: 2.35            │  │
│  │ Sharpe: 1.28   Max DD: -63%   Alpha: +3.2%/mo     │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  ┌─── Portfolio Fit ──────────────────────────────────┐  │
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
│  │                                                    │  │
│  │  (content loads on tab click — lazy)               │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  ┌─── Compare Mode ──────────────────────────────────┐  │
│  │ + Add ticker   [AAPL] [MSFT] [GOOGL]              │  │
│  │                                                    │  │
│  │ Side-by-side: Vol | Beta | Sharpe | Alpha |        │  │
│  │   What-if compliance for each                      │  │
│  │   "Best fit: GOOGL (only one that passes all       │  │
│  │    risk checks)"                                   │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

**Key design insight from experiment**: Every research workflow ends with `run_whatif`. The "Portfolio Fit" card is not optional — it's the centerpiece. The agent never recommends a stock without simulating its portfolio impact. The UI should make this automatic: enter a ticker → immediately see portfolio fit.

### Data Sources

| Section | Tool | Cross-MCP |
|---------|------|-----------|
| Stock profile | `analyze_stock` | — |
| Portfolio fit (current) | `get_positions` (pre-loaded from Overview) | — |
| Portfolio fit (what-if) | `run_whatif` | — |
| Technicals tab | — | `fmp:get_technical_analysis` |
| Estimates tab | — | `fmp:get_estimate_revisions` |
| News tab | — | `fmp:get_news` |
| Factor exposure tab | `get_factor_analysis` | — |
| Compare mode | `analyze_stock`(×N) + `run_whatif`(×N) | `fmp:fmp_profile`(×N) |

### Compare Mode
The Q16 agent naturally ran analyze_stock + run_whatif + fmp_profile for each of 3 candidates. The compare UI should:
- Let user add 2-4 tickers
- Auto-run analyze_stock + run_whatif for each
- Show side-by-side table with compliance pass/fail highlighted
- Surface "best fit" recommendation based on which passes risk checks

---

## 3. Tools — "Model a change"

Interactive instruments. These are not views you read — they're things you operate. Each tool has inputs, a "Run" button, and structured output.

### Sub-navigation

```
┌────────────────────────────────────────────────────────────────┐
│  Tools:  [What-If]  [Scenarios]  [Backtest]  [Rebalance]  [Tax] │
└────────────────────────────────────────────────────────────────┘
```

### 3a. What-If Simulator

The universal connector — accessed from Overview, Risk, or Research.

```
┌──────────────────────────────────────────────────────────┐
│  What-If Simulator                                       │
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
│  [Generate trades →]  [Save scenario]  [Compare ▾]      │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

**Tool**: `run_whatif` (target_weights or delta_changes)
**Exit ramps**: "Generate trades" → Rebalance tool. "Compare" → Scenarios tool.

### 3b. Scenario Comparison

Compare 2-4 what-if or optimization scenarios side by side. The Q18 agent naturally ran 3 graduated scenarios (5%/10%/15% bonds).

```
┌──────────────────────────────────────────────────────────┐
│  Scenario Comparison                                     │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  Scenario A: "10% bonds"    [edit]                       │
│  Scenario B: "15% bonds"    [edit]                       │
│  Scenario C: "Current"      [baseline]                   │
│  + Add scenario                                          │
│                                                          │
│  ┌─── Comparison Table ──────────────────────────────┐  │
│  │              A         B         C (baseline)     │  │
│  │ Vol          15.3%     14.1%     20.1%            │  │
│  │ Sharpe       1.8       1.9       1.2              │  │
│  │ Max DD       -12%      -10%      -22%             │  │
│  │ Compliant    YES       YES       NO               │  │
│  │ ──────────────────────────────────────────────    │  │
│  │ Rank         #2        #1 ★      #3               │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  [Implement Scenario B →]                                │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

**Tool**: `compare_scenarios`
**Exit ramp**: "Implement" → generates rebalance trades for the winning scenario.

### 3c. Backtest

Historical what-if: "how would this allocation have performed?"

**Tool**: `run_backtest` (weights + benchmark + period)
**Output**: Monthly return series, annual breakdown, max drawdown, Sharpe, vs benchmark chart.

### 3d. Rebalance

Target allocation → drift calculation → trade generation.

```
┌──────────────────────────────────────────────────────────┐
│  Rebalance                                               │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  ┌─── Drift Table ────────────────────────────────────┐  │
│  │ Asset Class   Target   Current   Drift    $ Gap    │  │
│  │ Equity        60%      76.5%     +16.5    +$8,503  │  │
│  │ Bond          25%      29.1%     +4.1     +$2,093  │  │
│  │ Real Estate   10%      17.8%     +7.8     +$4,019  │  │
│  │ Cash          5%       -28.2%    -33.2    -$17,087 │  │
│  │ Commodity     0%       4.8%      +4.8     +$2,472  │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  [Generate Trades]                                       │
│                                                          │
│  ┌─── Trade Legs ─────────────────────────────────────┐  │
│  │ SELL  STWD   400 shares   ~$3,400   (reduce RE)   │  │
│  │ SELL  SLV    25 shares    ~$1,900   (remove comm.) │  │
│  │ BUY   AGG    50 shares    ~$5,300   (add bonds)   │  │
│  │ ...                                                │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  [Preview all trades →]                                  │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

**Tools**: `get_target_allocation` + `get_positions` → drift calc → `generate_rebalance_trades`
**Exit ramp**: "Preview all trades" → Trade section.

### 3e. Tax Harvest Scanner

**Tool**: `suggest_tax_loss_harvest`
**Output**: Tiered harvest candidates (clean / wash-sale risk / small), estimated tax savings, replacement suggestions.
**Exit ramp**: "Sell for harvest" → Trade section.

---

## 4. Trade — "Do it"

Execution surface. Preview → confirm → execute.

```
┌──────────────────────────────────────────────────────────┐
│  Trade                                                   │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  ┌─── New Trade ──────────────────────────────────────┐  │
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
│  │ (from get_orders)                                  │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  ┌─── Baskets ────────────────────────────────────────┐  │
│  │ (list_baskets → basket management)                 │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

**Tools**: `preview_trade` → `execute_trade`, `get_orders`, basket tools, option/futures execution tools.

---

## Cross-Cutting: AI Chat Panel

The AI chat (Claude) is available as a slide-out panel from any page. It has access to all the same tools. The key design pattern:

- **From Overview**: "Give me a morning briefing" → agent runs the Q1 workflow
- **From Research**: "Should I add NVDA?" → agent runs the Q14 workflow, renders Portfolio Fit card inline
- **From Tools**: "What if I shift 10% to bonds?" → agent runs what-if, shows results in chat AND updates the What-If tool

The chat is the **unstructured** way to access the same workflows the structured UI provides. Power users use the nav. New users or complex questions use chat.

---

## Navigation Flow (How Pages Connect)

```
Overview
  │
  ├── Click holding row ──────────→ Analysis > Research (ticker pre-loaded)
  ├── Click risk violation ────────→ Analysis > Risk (violation highlighted)
  ├── Click "Simulate change" ─────→ Tools > What-If (tickers pre-filled)
  ├── Click exit signal ──────────→ Trade (sell preview pre-filled)
  │
Analysis > Risk
  │
  ├── "Simulate hedge" ───────────→ Tools > What-If (defensive ETFs suggested)
  ├── "Run stress test" ──────────→ Tools > Backtest (stress scenarios)
  │
Analysis > Research
  │
  ├── "Preview trade" ────────────→ Trade (ticker + quantity pre-filled)
  ├── "Adjust size" ──────────────→ Tools > What-If (ticker pre-filled)
  │
Tools > What-If
  │
  ├── "Generate trades" ──────────→ Tools > Rebalance (scenario weights)
  ├── "Compare" ──────────────────→ Tools > Scenarios (add to comparison)
  │
Tools > Rebalance
  │
  ├── "Preview all trades" ────────→ Trade (batch preview)
  │
Tools > Tax
  │
  ├── "Sell for harvest" ─────────→ Trade (sell preview)
```

Every page has **exit ramps** that flow naturally into the next step. The agent's tool chains become the user's click paths.

---

## Summary

| Section | Purpose | Complexity | Agent Equivalent |
|---------|---------|------------|-----------------|
| **Overview** | State + Alerts | Medium (wide but shallow) | Q1 morning briefing |
| **Analysis > Risk** | Deep risk understanding | Medium | Q5, Q7 risk review |
| **Analysis > Research** | Stock evaluation + portfolio fit | High (cross-MCP) | Q14, Q16, Q30 |
| **Tools** | Interactive modeling | Medium (per tool) | Q18, Q20, Q23 |
| **Trade** | Execution | Low (preview → confirm) | Q26-29 (not yet tested) |

**Total pages**: 4 top-level + 2 Analysis sub-views + 5 Tool sub-views = manageable complexity with clear information hierarchy.

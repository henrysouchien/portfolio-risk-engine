# Frontend Views → Defined Workflows

## Vision

The frontend has 7 views that started as UI scaffolding. Most are now wired to real backend data, but they're **data displays, not workflows**. The goal is to turn each into a defined, multi-step workflow process that:

1. **Lives on the backend** as a standalone, composable process (not just an API endpoint)
2. **Can be driven by the UI** — user steps through it interactively
3. **Can be driven by an agent** — Claude calls the workflow as a tool/process
4. **Can be iterated independently** — change the workflow logic without touching UI or agent code

The workflow definition becomes the shared contract between all three layers.

---

## Current State Audit (2026-03-01)

### Summary

| View | Backend Wired | Real Data | Workflow Today | Pattern |
|------|:---:|:---:|:---:|---|
| **Hedging** | Yes | Yes | Data display | Recommend only, no execute |
| **Scenarios** | Yes | Yes | Functional | Single-shot what-if, no save/chain |
| **Asset Allocation** | Yes | Yes | Data display | Classification + drift, no rebalance |
| **Risk Analysis** | Yes (3 sources) | Yes | Partial | Deep analytics, no mitigation actions |
| **Performance** | Yes | Yes | Mostly functional | Attribution wired, some UI gaps |
| **Stock Lookup** | Partial | Search mocked | Partial | Analysis real, search missing |
| **Strategy Builder** | Partial | Templates mocked | Partial | Optimization real, persistence/backtest missing |

### Architecture Today

**Backend**: Mature single-shot analytics. 16 MCP tools with agent format, 15 result object classes, service layer with caching. Each tool is standalone — loads its own dependencies, returns a complete result. No orchestration between tools.

**Frontend**: Container → Adapter → Hook → API pattern. Proper loading/error/empty states. Adapters transform backend responses into view-specific shapes. Cache coordination via events.

**Gap**: No workflow orchestration layer. Multi-step analyses (risk → what-if → optimize → execute) must be chained manually by the user or by Claude calling tools in sequence. No state machine, no step tracking, no process persistence.

---

## Per-View Detail

### 1. Hedging

**Current**: `RiskAnalysisModernContainer` embeds hedging via `useHedgingRecommendations()`. Backend `/api/portfolio-recommendations` returns driver-based hedge candidates with correlation metrics and Sharpe ratios. `HedgingAdapter` ranks top 3 strategies by correlation + Sharpe.

**What works**: Real recommendations from live portfolio factor exposures. Efficiency ratings (High/Medium/Low). Cost labels (% of portfolio).

**What's missing**:
- No "apply hedge" action — display only
- No impact simulation (what happens to risk if I add this hedge?)
- VaR before/after hardcoded as N/A
- No hedge sizing (how much to buy?)
- Embedded in Risk Analysis, not standalone

**Backend tools available**: `get_factor_recommendations(mode="portfolio")`, `run_whatif()` (could simulate hedge impact)

### 2. Scenarios / What-If

**Current**: `ScenarioAnalysisContainer` uses `useWhatIfAnalysis()`. Backend `run_whatif()` accepts `target_weights` or `delta_changes`, returns before/after risk comparison with compliance checks. User can input weights/deltas, add/remove assets, run scenario.

**What works**: Real scenario execution. Weight and delta input modes. Before/after risk metrics (volatility, concentration, factor variance). Compliance flags (`risk_passes`, `beta_passes`).

**What's missing**:
- Templates hardcoded (Conservative, Aggressive) — should come from backend
- No scenario save/history — each run is fire-and-forget
- No batch comparison (run 5 scenarios, compare side-by-side)
- No predefined stress tests ("market -20%", "rates +200bp")
- Period selector buttons exist but don't feed into scenario params

**Backend tools available**: `run_whatif()` (single scenario), `get_risk_analysis()` (baseline)

### 3. Asset Allocation

**Current**: `AssetAllocationContainer` uses `useRiskAnalysis()` to get `asset_allocation` data. Backend classifies positions into Equity/Fixed Income/Commodities/Cash. Drift analysis available (`target_pct`, `drift_pct`, `drift_status`).

**What works**: Real allocation percentages from live positions. Asset class color-coded cards with holdings lists. Drift severity indicators. Period selector (1M/3M/6M/1Y/YTD) fully wired with three-layer cache (backend + frontend + adapter). Real per-class performance change per period. Drift infrastructure built (`allocation_drift.py`, `compute_allocation_drift()`).

**What's missing**:
- Target allocations DB table not yet migrated (schema defined, graceful fallback in place)
- No target allocation configuration UI
- No rebalancing suggestions — drift shown but no action
- Historical allocation snapshots not tracked (trend over time)
- No drill-down to individual holdings per class

**Backend tools available**: `get_risk_analysis()` (allocation), `run_optimization()` (could drive rebalancing), `run_whatif()` (preview rebalance impact)

### 4. Risk Analysis

**Current**: `RiskAnalysisModernContainer` wires 3 hooks: `useRiskAnalysis()`, `useRiskScore()`, `useHedgingRecommendations()`. Backend returns comprehensive risk metrics: correlation matrix, factor exposures, variance decomposition, risk contributions, industry analysis, limit checks, component scores (0-100).

**What works**: Real multi-source risk analysis. Component scoring (Concentration, Volatility, Factor, Sector). Event-driven cache invalidation. Segment filtering (equities/futures/all).

**What's missing**:
- No interactive drill-down on risk factors
- Stress test scenarios partially implemented (worst_by_factor)
- No risk-to-action pipeline (flag breach → suggest mitigation → execute)
- Hedging embedded rather than cross-linked
- No historical risk trending

**Backend tools available**: `get_risk_analysis()`, `get_risk_score()`, `get_leverage_capacity()`, `check_exit_signals()`, `get_factor_analysis()`

### 5. Performance

**Current**: `PerformanceViewContainer` uses `usePerformance({ benchmarkTicker })`. Backend returns time series, period returns (1D/1W/1M/3M/1Y/YTD), risk-adjusted metrics, factor attribution. Benchmark selector with localStorage persistence.

**What works**: Real performance metrics with benchmark comparison. Alpha/beta/Sharpe from live data. Benchmark switching with cache invalidation. Factor attribution (Market, Value, Momentum, Selection & Other). Sector + security attribution.

**What's missing**:
- Attribution breakdown UI doesn't fully surface backend data
- No multi-benchmark comparison
- No rolling windows (1Y rolling Sharpe, etc.)
- Export intents may not be registered
- No performance alerts (drawdown threshold, underperformance)

**Backend tools available**: `get_performance(mode="hypothetical"|"realized")`, `get_trading_analysis()` (with date ranges)

### 6. Stock Lookup

**Current**: `StockLookupContainer` uses `useStockAnalysis()`. Backend `analyze_stock()` returns single-stock risk: volatility, beta, factor betas (growth, value, size, momentum), VaR. Tabs for metrics, fundamentals, technicals.

**What works**: Real stock analysis once a ticker is selected. Comprehensive risk/factor profile. 300ms debounce on search.

**What's missing**:
- **Search results are entirely mocked** (hardcoded list)
- No stock search API wired (`fmp_search` exists on fmp-mcp but not connected to frontend)
- No peer comparison (backend has it but not exposed)
- No position sizing recommendation
- No "add to portfolio" or "what-if with this stock" action
- Chart visualization component missing

**Backend tools available**: `analyze_stock()`, `fmp_search()` (fmp-mcp), `fmp_profile()` (fmp-mcp), `compare_peers()` (fmp-mcp), `run_whatif()` (could simulate adding stock)

### 7. Strategy Builder

**Current**: `StrategyBuilderContainer` uses `usePortfolioOptimization()` and `useWhatIfAnalysis()`. Backend `run_optimization()` supports min_variance and max_return objectives with constraint enforcement (volatility cap, concentration, factor limits).

**What works**: Real optimization results (optimized weights, improvement metrics, constraint summary). Cross-container export to Scenarios via `whatIf.runScenario()`.

**What's missing**:
- Strategy templates hardcoded (should be backend-driven)
- No strategy saving/persistence
- Backtesting framework exists but depends on Scenarios completion
- No constraint tuning UI (must call `set_risk_profile()` separately)
- No trade sequencing (which trades to execute first?)
- No sensitivity analysis (how much does allocation change if I relax a constraint?)

**Backend tools available**: `run_optimization()`, `run_whatif()`, `set_risk_profile()`, `get_risk_profile()`

---

## Workflow Design Framework

Each view maps to a **workflow process** — a defined sequence of steps with inputs, analysis, decisions, and actions.

### Workflow Structure

```
Workflow:
  name: string
  trigger: "user" | "agent" | "scheduled"
  steps:
    - step_1: Gather context (current state snapshot)
    - step_2: Analyze (run computations, flag issues)
    - step_3: Recommend (generate actionable suggestions)
    - step_4: Preview (show impact of proposed changes)
    - step_5: Execute (apply changes, with confirmation gate)
  inputs: what the workflow needs to start
  outputs: what it produces at each step
  tools_used: which existing MCP tools power each step
```

### Workflow Definitions

| Workflow | Steps | Status |
|----------|-------|--------|
| Hedging | Identify exposures → Find hedges → Size → Preview impact → Execute | **Defined** |
| Scenario Analysis | Define scenario → Run what-if → Compare outcomes → Refine → Execute | **Defined** |
| Allocation Review | Snapshot allocation → Analyze drift → Generate rebalance plan → Preview impact → Execute | **Defined** |
| Risk Review | Assess risk state → Diagnose drivers → Recommend mitigations → Preview impact → Execute | **Defined** |
| Performance Review | Measure returns → Attribute → Diagnose issues → Recommend improvements → Preview & execute | **Defined** |
| Stock Research | Find & profile → Analyze (6 dimensions) → Evaluate portfolio fit → Size position → Execute | **Defined** |
| Strategy Design | Set objectives & constraints → Optimize → Compare variants → Validate & save → Execute | **Defined** |

---

## Workflow 1: Hedging

### Overview

The hedging workflow takes a portfolio from "I have risk exposures" to "I've put on hedges that reduce those exposures." It spans five steps — each independently useful (you can stop after step 2 and just know your exposures), but the full pipeline connects identification through execution.

The workflow is instrument-agnostic: hedge candidates can be ETFs, individual stocks, options strategies, futures, or custom baskets. The same step sequence applies regardless of hedge instrument type.

### Step 1: Identify Exposures

**Purpose:** Understand what the portfolio is exposed to and what's driving risk.

**Tools:**
- `get_risk_analysis(format="agent")` — factor betas, variance decomposition, risk contributions, industry concentration, compliance violations
- `get_risk_score()` — overall risk score (0-100), component scores (Concentration, Volatility, Factor, Sector), top risk factors, recommendations
- `get_factor_analysis(analysis_type="correlations")` — cross-asset correlation matrices, rate/market sensitivity overlays

**Inputs:** Portfolio (loaded from current positions or specified by name)

**Outputs:**
```
exposures:
  factor_betas: {market: 1.05, growth: 0.8, value: -0.2, momentum: 0.6, ...}
  top_risk_contributors: [{ticker, weight, risk_contribution_pct}, ...]
  variance_decomposition: {factor_pct: 72%, idiosyncratic_pct: 28%}
  industry_concentration: [{industry, weight, variance_contribution}, ...]
  compliance_violations: [{limit_name, current, threshold, severity}, ...]
  risk_score: {overall: 68, components: {concentration: 72, volatility: 55, ...}}
```

**Flags that trigger hedging consideration:**
- `factor_overexposure` — beta > 1.5 to any factor
- `concentration_warning` — single stock > 15% or sector > 40%
- `compliance_violation` — any risk limit breach
- `high_risk_score` — overall score > 70

**UI:** Dashboard view showing factor heatmap, top contributors bar chart, risk score gauge. Flags highlighted as actionable items. "Find hedges" button on each flagged exposure.

**Agent:** Reads flags from agent format response. If any hedging-relevant flags present, proceeds to Step 2 automatically.

---

### Step 2: Find Hedge Candidates

**Purpose:** Given the identified exposures, find instruments that offset them.

**Tools:**
- `get_factor_recommendations(mode="portfolio")` — auto-detects risk drivers from live positions, returns negatively-correlated hedge candidates (ETFs, style factors, commodities, user baskets)
- `get_factor_recommendations(mode="single", overexposed_factor="Technology")` — targeted search for a specific exposure
- `analyze_option_chain(symbol, expiry)` — for any equity exposure, find put protection levels (OI concentration, max pain, put/call ratio)
- `get_futures_curve(symbol)` — for commodity/index exposures, evaluate futures hedge cost (contango/backwardation, roll costs)
- `list_baskets()` / `analyze_basket(name)` — check if existing custom baskets could serve as hedges

**Inputs:** Exposures from Step 1 (factor betas, risk drivers, flagged items)

**Outputs:**
```
hedge_candidates:
  - type: "etf"
    candidates:
      - {ticker: "XLU", correlation: -0.35, sharpe: 0.8, category: "Utilities", rationale: "Offset Technology overexposure"}
      - {ticker: "GLD", correlation: -0.28, sharpe: 0.5, category: "Commodity", rationale: "Offset equity beta"}
  - type: "options"
    candidates:
      - {underlying: "SPY", strategy: "protective_put", expiry: "20260620", strike: 520, put_call_ratio: 1.2, max_pain: 530}
      - {underlying: "QQQ", strategy: "collar", expiry: "20260620", put_strike: 440, call_strike: 480}
  - type: "futures"
    candidates:
      - {symbol: "ES", front_month: "202606", curve_shape: "contango", roll_cost_ann: "2.1%", rationale: "Short ES to reduce market beta"}
  - type: "basket"
    candidates:
      - {name: "defensive_staples", correlation: -0.22, components: 15, rationale: "Custom low-beta basket"}
```

**Decision point:** User/agent selects which candidates to evaluate further. Can select multiple across instrument types.

**UI:** Candidate cards grouped by type (ETFs, Options, Futures, Baskets). Each card shows correlation, cost indication, rationale. Checkboxes to select candidates for impact analysis. Filter/sort by correlation strength, cost, instrument type.

**Agent:** Ranks candidates by `abs(correlation) * sharpe_ratio` or similar heuristic. Selects top N for impact simulation. Can explain rationale for each.

---

### Step 3: Size & Model Hedge

**Purpose:** For each selected candidate, determine the right size and model the strategy details.

**Tools:**
- `analyze_option_strategy(legs=[...])` — model protective put, collar, spread payoffs: Greeks, break-evens, max loss, max profit
- `get_futures_curve(symbol)` — evaluate roll schedule and carry cost for futures hedge
- `analyze_basket(name, benchmark_ticker="SPY")` — basket risk/return profile, component contributions
- No dedicated sizing tool yet — sizing derived from what-if in Step 4

**Inputs:** Selected candidates from Step 2

**Outputs per candidate:**
```
hedge_model:
  - candidate: "SPY protective put, 520 strike, June 2026"
    strategy_type: "protective_put"
    legs: [{position: "long", option_type: "put", strike: 520, premium: 8.50}]
    greeks: {delta: -0.35, gamma: 0.02, theta: -0.15, vega: 0.18}
    max_loss: $850 per contract (premium paid)
    break_even: $511.50
    protection_level: "5.8% downside from current"

  - candidate: "XLU allocation +10%"
    sizing: "10% of portfolio = ~$25,000"
    shares: 370 shares at $67.50
    estimated_cost: $24,975

  - candidate: "Short 2x ES futures"
    contract_value: $265,000 per contract
    margin_required: ~$13,250 per contract
    roll_cost: "2.1% annualized (contango)"
```

**UI:** Strategy modeler per candidate. Options: payoff diagram, Greeks table, break-even visualization. ETFs/baskets: allocation slider, cost estimate. Futures: contract sizing, margin requirement, roll schedule.

**Agent:** Models each candidate, summarizes cost vs. protection tradeoff in natural language.

---

### Step 4: Preview Impact

**Purpose:** Simulate adding each hedge to the portfolio and compare risk reduction vs. cost.

**Tools:**
- `run_whatif(delta_changes={...})` — for each candidate, simulate adding it. Returns before/after: volatility, concentration, factor betas, compliance status
- **Gap: No batch comparison** — must call `run_whatif()` per candidate and compare manually. Future: `compare_scenarios()` that runs N candidates in parallel and returns a ranked comparison table.

**Inputs:** Sized hedge candidates from Step 3

**Outputs:**
```
impact_comparison:
  baseline:
    volatility: 22.5%
    market_beta: 1.05
    herfindahl: 0.082
    risk_score: 68

  candidates:
    - name: "SPY protective put"
      volatility: 22.5% → 19.8% (-12%)
      market_beta: 1.05 → 0.70 (-33%)
      cost: $1,700 (2 contracts)
      risk_reduction_per_dollar: 1.59%/$1K
      compliance_impact: "Resolves beta_overexposure violation"

    - name: "XLU +10%"
      volatility: 22.5% → 20.1% (-11%)
      market_beta: 1.05 → 0.92 (-12%)
      cost: $24,975 (capital reallocation)
      risk_reduction_per_dollar: 0.10%/$1K
      compliance_impact: "Reduces concentration from 0.082 to 0.071"

    - name: "Short 2x ES"
      volatility: 22.5% → 17.2% (-24%)
      market_beta: 1.05 → 0.45 (-57%)
      cost: $26,500 margin
      risk_reduction_per_dollar: 0.20%/$1K margin
      compliance_impact: "Resolves beta_overexposure, adds leverage"

  ranking: [ES_short, SPY_put, XLU_allocation]  # by risk_reduction_per_dollar
```

**Decision point:** User/agent selects which hedge(s) to execute. May select a combination (e.g., protective put + sector reallocation).

**UI:** Comparison table — rows are candidates, columns are metrics (vol change, beta change, cost, efficiency). Highlight best-in-class per metric. Allow multi-select for combined execution. Before/after risk dashboard preview.

**Agent:** Ranks by risk-reduction efficiency. Recommends top candidate with explanation. If multiple hedges complement each other (e.g., options for tail risk + ETF for factor reduction), suggests the combination.

---

### Step 5: Execute

**Purpose:** Place the trades to implement the chosen hedge(s).

**Tools:**
- `preview_trade(ticker, quantity, side)` → `execute_trade(preview_id)` — single ETF/equity hedge
- `preview_basket_trade(name, action="buy", total_value=X)` → `execute_basket_trade(preview_ids)` — basket hedge
- `preview_futures_roll(symbol, ...)` → `execute_futures_roll(preview_id)` — futures hedge
- **Gap: No multi-leg options execution** — must execute legs individually. Future: `preview_option_trade(legs=[...])` for atomic spread/collar orders.
- **Gap: No rebalance trade generator** — must manually translate what-if weight deltas into trade list. Future: `generate_rebalance_trades(target_weights)` → trade list with share quantities and sequencing.

**Inputs:** Selected hedge(s) from Step 4 with sizing from Step 3

**Outputs:**
```
execution_plan:
  trades:
    - {action: "BUY", ticker: "SPY 250620P00520000", quantity: 2, order_type: "Limit", limit_price: 8.50, estimated_cost: $1,700}
    - {action: "BUY", ticker: "XLU", quantity: 370, order_type: "Market", estimated_cost: $24,975}
  total_cost: $26,675
  margin_impact: +$0 (options are paid, ETF is capital)

execution_result:
  - {ticker: "SPY put", status: "filled", fill_price: 8.45, fill_qty: 2}
  - {ticker: "XLU", status: "filled", fill_price: 67.48, fill_qty: 370}
  total_executed: $26,641
  slippage: -$34 (0.13%)
```

**Confirmation gate:** Both UI and agent require explicit user approval before execution. Preview shows all trades, costs, and portfolio impact. No autonomous execution.

**UI:** Trade ticket showing all orders. "Preview" button shows fills/costs. "Execute All" button with confirmation dialog. Post-execution: updated portfolio view showing new positions and revised risk metrics.

**Agent:** Presents trade plan in natural language. Asks for confirmation. After execution, runs `get_risk_analysis()` again to verify risk reduction achieved.

---

### Workflow Summary

```
Step 1: Identify Exposures
  Tools: get_risk_analysis, get_risk_score, get_factor_analysis
  Output: Flagged exposures + risk drivers

Step 2: Find Hedge Candidates
  Tools: get_factor_recommendations, analyze_option_chain, get_futures_curve, list_baskets
  Output: Ranked candidates by instrument type

Step 3: Size & Model
  Tools: analyze_option_strategy, get_futures_curve, analyze_basket
  Output: Sized positions with cost/payoff profiles

Step 4: Preview Impact
  Tools: run_whatif (per candidate)
  Output: Before/after comparison, ranked by efficiency
  Gap: No batch comparison tool

Step 5: Execute
  Tools: preview_trade/execute_trade, preview_basket_trade/execute_basket_trade, preview_futures_roll/execute_futures_roll
  Output: Fill confirmations + updated risk view
  Gaps: No multi-leg options execution, no rebalance trade generator
```

### Gaps Summary (backlog items in TODO.md)

| Gap | Impact | Workaround |
|-----|--------|------------|
| Multi-leg options execution | Spread/collar legs executed separately, slippage risk | Execute legs individually via `preview_trade()` |
| Batch scenario comparison | Must call `run_whatif()` N times and compare manually | Agent/UI loops over candidates |
| Rebalance trade generator | Must manually calculate shares from weight deltas | Compute from what-if `position_changes` output |
| Live options pricing | Greeks are model-based, not real-time | Use `analyze_option_strategy()` with manual price input |
| Continuous monitoring | No alerts when hedges drift or expire | Manual re-run of Step 1 periodically |

---

## Workflow 2: Scenario Analysis

### Overview

The scenario analysis workflow takes a portfolio from "what if I change my allocation?" to "I understand the risk/return tradeoff of each option and I've executed my preferred one." It bridges the gap between static portfolio analysis and active portfolio construction — every scenario run answers the question "is this portfolio better than what I have now?"

The workflow supports three modes: **custom** (user-defined weight changes), **templated** (predefined strategies like "defensive rotation" or "growth tilt"), and **stress tests** (market shock simulations like "-20% equities" or "+200bp rates"). All three modes flow through the same 5-step pipeline.

### Step 1: Define Scenario

**Purpose:** Specify what portfolio change to evaluate — either as target weights, relative deltas, or a predefined template.

**Tools:**
- `get_risk_analysis(format="agent")` — current portfolio baseline (weights, risk metrics, factor exposures) to inform scenario construction
- `get_risk_profile()` — current constraints (volatility cap, concentration limits, factor bounds) that scenarios will be checked against

**Inputs:**

Three input modes:

```
mode_1_custom:
  target_weights: {AAPL: 0.15, MSFT: 0.12, ...}  # absolute weights (must sum to ~1.0)
  # OR
  delta_changes: {AAPL: "+5%", MSFT: "-3%", GLD: "+8%"}  # relative changes (bp/% syntax)

mode_2_template:
  template_name: "defensive_rotation" | "growth_tilt" | "yield_focus" | "derisking" | ...
  intensity: 0.0-1.0  # how aggressively to apply (0.5 = half the template's deltas)

mode_3_stress_test:
  scenario_name: "market_crash" | "rate_shock" | "sector_rotation" | "stagflation" | ...
  parameters: {equity_shock: -0.20, rate_change_bp: 200, ...}
```

**Outputs:**
```
scenario_definition:
  name: "Defensive rotation - 50% intensity"
  mode: "template"
  delta_changes: {XLU: "+5%", XLP: "+5%", QQQ: "-8%", ARKK: "-2%"}
  baseline_snapshot:
    total_value: $500,000
    volatility: 22.5%
    market_beta: 1.05
    top_holdings: [{ticker, weight, risk_contribution}, ...]
```

**Gap: No predefined templates or stress tests.** `run_whatif()` only accepts raw weights/deltas. Templates and stress test presets need to be defined (either as config or a new tool). Workaround: agent constructs the delta_changes dict from natural language ("make it more defensive" → reduce high-beta, add low-vol).

**Gap: No scenario persistence.** Each run is fire-and-forget. No save/load/history. Workaround: agent maintains scenario parameters in conversation context.

**UI:** Three-tab input: Custom (weight sliders), Templates (preset cards with intensity slider), Stress Tests (scenario cards with parameter knobs). Current portfolio shown alongside for reference. "Run Scenario" button.

**Agent:** Interprets natural language intent ("what if I went more defensive?") → constructs delta_changes dict. Uses `get_risk_analysis()` baseline to identify what to change. Can suggest templates based on portfolio state.

---

### Step 2: Run Analysis

**Purpose:** Execute the scenario and get the full before/after risk comparison.

**Tools:**
- `run_whatif(target_weights=... OR delta_changes=..., format="agent")` — single scenario execution returning:
  - Before/after: volatility, concentration (Herfindahl), factor betas, VaR
  - Compliance checks: `risk_passes`, `beta_passes`, `concentration_passes` against current risk profile
  - Position-level changes: which positions increase/decrease and by how much
  - Marginal risk impact per position change
  - What-if flags: `risk_violation`, `volatility_increase`, `volatility_decrease`, `concentration_increase`, `marginal_impact`, `overall_improvement`

**Inputs:** Scenario definition from Step 1 (delta_changes or target_weights)

**Outputs:**
```
scenario_result:
  name: "Defensive rotation"
  before:
    volatility: 22.5%
    market_beta: 1.05
    herfindahl: 0.082
    var_95: -3.2%
    factor_betas: {market: 1.05, growth: 0.8, value: -0.2, momentum: 0.6}
  after:
    volatility: 19.1%
    market_beta: 0.88
    herfindahl: 0.074
    var_95: -2.7%
    factor_betas: {market: 0.88, growth: 0.5, value: 0.1, momentum: 0.4}
  changes:
    volatility_delta: -3.4% (-15.1%)
    beta_delta: -0.17 (-16.2%)
    compliance: {risk_passes: true, beta_passes: true, concentration_passes: true}
  position_changes:
    - {ticker: "XLU", before: 0.02, after: 0.07, delta: +0.05}
    - {ticker: "QQQ", before: 0.12, after: 0.04, delta: -0.08}
  flags:
    - {severity: "success", type: "overall_improvement", message: "Portfolio risk improved across all dimensions"}
    - {severity: "info", type: "volatility_decrease", message: "Volatility reduced by 3.4pp"}
```

**UI:** Before/after comparison panel. Risk metrics in paired columns. Position changes table sorted by absolute delta. Compliance pass/fail badges. Flag banner at top (green for improvement, amber for tradeoffs, red for violations).

**Agent:** Reads flags from agent format. Summarizes: "This scenario reduces volatility by 15% and brings beta under 1.0. All constraints pass. The main tradeoff is reduced growth exposure (-0.3 beta)."

---

### Step 3: Compare Outcomes

**Purpose:** Run multiple scenarios side-by-side to find the best option.

**Tools:**
- `run_whatif()` — called once per scenario (no batch mode today)
- `get_risk_analysis()` — baseline for consistent comparison anchor

**Inputs:** 2-5 scenario definitions (from Step 1, possibly with variations)

**Outputs:**
```
comparison_table:
  baseline:
    volatility: 22.5%, beta: 1.05, sharpe: 0.85, var_95: -3.2%

  scenarios:
    - name: "Defensive rotation"
      volatility: 19.1% (-15%), beta: 0.88, sharpe: 0.91, compliance: PASS
    - name: "Growth tilt"
      volatility: 25.8% (+15%), beta: 1.22, sharpe: 0.78, compliance: FAIL (beta)
    - name: "Yield focus"
      volatility: 18.5% (-18%), beta: 0.75, sharpe: 0.88, compliance: PASS
    - name: "Market neutral"
      volatility: 12.1% (-46%), beta: 0.15, sharpe: 0.65, compliance: PASS

  ranking:
    by_sharpe: [Defensive, Yield, Growth, Neutral]
    by_risk_reduction: [Neutral, Yield, Defensive, Growth]
    by_compliance: [Defensive, Yield, Neutral]  # Growth excluded (FAIL)
```

**Gap: No batch comparison tool.** Must call `run_whatif()` N times serially and assemble the comparison manually. Future: `compare_scenarios(scenarios=[...])` that runs all in parallel, returns a ranked comparison table, and identifies Pareto-optimal options.

**Gap: No Sharpe/return estimation.** `run_whatif()` returns risk metrics (vol, beta, VaR) but not expected return or Sharpe. Return estimation would require expected returns model. Workaround: Use factor beta changes as proxy for return impact.

**Decision point:** User/agent selects preferred scenario (or combination) to implement.

**UI:** Comparison table — rows are scenarios, columns are key metrics. Color coding: green = improvement, red = degradation vs. baseline. "Best" badges per metric. Radar chart overlay showing all scenarios on same axes. Select checkbox + "Implement" button.

**Agent:** Presents ranked options. Recommends Pareto-optimal choice (best risk-adjusted, compliant). If no single scenario dominates, suggests a blend.

---

### Step 4: Decide & Refine

**Purpose:** Finalize the chosen scenario and prepare for execution. Optionally refine by adjusting parameters and re-running.

**Tools:**
- `run_whatif()` — re-run with tweaked parameters if user wants to adjust
- `run_optimization(objective="min_variance" | "max_return")` — if user wants the optimal allocation within constraints instead of a manual scenario
- `set_risk_profile(template=...)` — adjust constraints if a good scenario fails compliance

**Inputs:** Selected scenario from Step 3 (or optimization result)

**Outputs:**
```
final_scenario:
  name: "Defensive rotation (adjusted)"
  target_weights: {AAPL: 0.12, MSFT: 0.10, XLU: 0.07, XLP: 0.05, ...}
  position_changes:
    buys: [{ticker: "XLU", shares: 148, est_cost: $9,990}, {ticker: "XLP", shares: 65, est_cost: $5,135}]
    sells: [{ticker: "QQQ", shares: -42, est_proceeds: $18,690}, {ticker: "ARKK", shares: -25, est_proceeds: $1,250}]
  net_cash_impact: +$4,815
  trades_required: 4
  compliance: PASS
```

**UI:** Final scenario summary card. Editable weight sliders for last-mile adjustments (re-runs what-if on change). "Optimize within these constraints" button as alternative to manual tweaking. Trade preview list showing buys/sells with estimated costs.

**Agent:** Presents final scenario with trade summary. If user wants adjustments, re-runs with modified deltas. Can suggest: "This is close to the min-variance optimal — want me to run optimization instead?"

---

### Step 5: Execute

**Purpose:** Translate the scenario into actual trades and execute.

**Tools:**
- `preview_trade(ticker, quantity, side)` → `execute_trade(preview_id)` — per position change
- `preview_basket_trade()` → `execute_basket_trade()` — if rebalance maps to a basket
- **Gap: No rebalance trade generator** — must manually translate weight deltas to share quantities. Same gap as Hedging Step 5. Future: `generate_rebalance_trades(current_weights, target_weights, portfolio_value)` → ordered trade list with share quantities and sequencing (sells before buys to free capital).

**Inputs:** Final scenario position changes from Step 4

**Outputs:**
```
execution_plan:
  sequence:
    1. SELL QQQ × 42 → free ~$18,690
    2. SELL ARKK × 25 → free ~$1,250
    3. BUY XLU × 148 → cost ~$9,990
    4. BUY XLP × 65 → cost ~$5,135
  total_sells: $19,940
  total_buys: $15,125
  net_cash: +$4,815

execution_result:
  fills: [{ticker, side, quantity, fill_price, status}, ...]
  total_slippage: -$67 (0.3%)
  post_execution_verification:
    new_volatility: 19.3% (target was 19.1%)
    new_beta: 0.89 (target was 0.88)
    drift_from_target: <0.5% — within tolerance
```

**Confirmation gate:** Same as Hedging — explicit user approval required. Preview all trades before execution.

**UI:** Trade sequencing view (sells first, then buys). Preview fills and costs. "Execute All" with confirmation. Post-execution: re-run risk analysis to verify the scenario played out as expected.

**Agent:** Presents trade plan. Sequences sells before buys. After execution, runs `get_risk_analysis()` to confirm actual risk matches predicted risk. Reports any drift.

---

### Workflow Summary

```
Step 1: Define Scenario
  Tools: get_risk_analysis, get_risk_profile
  Input modes: Custom weights/deltas, template, stress test
  Output: Scenario definition + baseline snapshot
  Gaps: No predefined templates, no stress test presets, no persistence

Step 2: Run Analysis
  Tools: run_whatif
  Output: Before/after risk comparison, compliance checks, flags
  Gap: None (single scenario works well)

Step 3: Compare Outcomes
  Tools: run_whatif (×N)
  Output: Ranked comparison table
  Gap: No batch comparison tool, no return/Sharpe estimation

Step 4: Decide & Refine
  Tools: run_whatif, run_optimization, set_risk_profile
  Output: Final scenario with trade list
  Gap: None (tools exist, orchestration needed)

Step 5: Execute
  Tools: preview_trade/execute_trade
  Output: Fill confirmations + post-execution verification
  Gap: No rebalance trade generator (shared with Hedging)
```

### Gaps Summary

| Gap | Impact | Workaround | Shared? |
|-----|--------|------------|---------|
| Predefined scenario templates | User must construct deltas manually | Agent interprets intent → builds deltas | Scenario-specific |
| Stress test presets | No "market crash -20%" one-click | Agent constructs shock parameters | Scenario-specific |
| Scenario persistence | No save/load/history | Conversation context only | Scenario-specific |
| Batch scenario comparison | Must run what-if N times serially | Agent loops + assembles table | Shared with Hedging (Step 4) |
| Return/Sharpe estimation | Risk-only comparison, no return forecast | Factor beta proxy | Scenario-specific |
| Rebalance trade generator | Manual weight→shares conversion | Compute from position_changes | Shared with Hedging (Step 5) |

---

## Workflow 3: Allocation Review

### Overview

The allocation review workflow answers "is my portfolio still where I want it to be?" and guides the user from drift detection through rebalancing execution. It's the most operationally routine workflow — something a disciplined investor does monthly or quarterly — which makes it a strong candidate for automation.

The workflow has a natural split: Steps 1-2 are **monitoring** (always valuable, low-risk), Steps 3-5 are **action** (optional, require user decision). An agent can run Steps 1-2 proactively and only escalate when drift exceeds thresholds.

### Step 1: Snapshot Current Allocation

**Purpose:** Capture the portfolio's current allocation by asset class, sector, and individual position, alongside any stored target allocation.

**Tools:**
- `get_risk_analysis(format="agent")` — returns `asset_allocation` breakdown with drift analysis when targets exist. Also provides: factor betas, variance decomposition, industry concentration, compliance status
- `get_positions(format="agent")` — position-level detail: weights, values, asset classes, sectors, account attribution
- `get_risk_profile()` — current constraint set (volatility cap, concentration limits, factor bounds)

**Inputs:** Portfolio (loaded from current positions or specified by name)

**Outputs:**
```
allocation_snapshot:
  by_asset_class:
    - {category: "equity", percentage: 72.3, value: "$361,500", holdings: ["AAPL", "MSFT", ...], count: 15}
    - {category: "bond", percentage: 18.1, value: "$90,500", holdings: ["SGOV", "BND"], count: 2}
    - {category: "cash", percentage: 5.2, value: "$26,000", holdings: ["USD"], count: 1}
    - {category: "commodity", percentage: 4.4, value: "$22,000", holdings: ["GLD"], count: 1}

  target_allocation:   # From DB — may be null if no targets set
    equity: 60.0
    bond: 25.0
    cash: 10.0
    commodity: 5.0

  top_positions:
    - {ticker: "AAPL", weight: 18.2%, value: "$91,000", asset_class: "equity", sector: "Technology"}
    - {ticker: "MSFT", weight: 14.5%, value: "$72,500", asset_class: "equity", sector: "Technology"}
    ...

  risk_profile:
    template: "balanced"
    max_single_stock: 25%
    volatility_target: 18%
    max_industry_contribution: 35%
```

**UI:** Allocation pie/bar chart by asset class. Position table sorted by weight. Target overlay (if targets exist). Risk profile badge showing active template.

**Agent:** Loads snapshot, checks if targets exist. If no targets → suggests setting them before proceeding. If targets exist → proceeds to Step 2.

---

### Step 2: Analyze Drift

**Purpose:** Compare current allocation to targets and identify what's drifted and why.

**Tools:**
- `get_risk_analysis(format="agent")` — `asset_allocation` entries include `target_pct`, `drift_pct`, `drift_status`, `drift_severity` when targets are set. Uses `compute_allocation_drift()` with hardcoded thresholds: ±2pp = on_target, ±5pp = warning
- `get_risk_score()` — component scores flag concentration and sector drift via `concentration_warning` and `sector_skew` flags

**Inputs:** Allocation snapshot from Step 1

**Outputs:**
```
drift_analysis:
  overall_status: "drift_detected"  # or "on_target", "minor_drift"
  rebalance_urgency: "medium"       # low (<2pp max drift), medium (2-5pp), high (>5pp)

  by_asset_class:
    - category: "equity"
      current_pct: 72.3
      target_pct: 60.0
      drift_pct: +12.3
      drift_status: "overweight"
      drift_severity: "warning"
      driver: "AAPL +8.2% appreciation, MSFT +6.1%"

    - category: "bond"
      current_pct: 18.1
      target_pct: 25.0
      drift_pct: -6.9
      drift_status: "underweight"
      drift_severity: "warning"
      driver: "No rebalance since rates rose"

    - category: "cash"
      current_pct: 5.2
      target_pct: 10.0
      drift_pct: -4.8
      drift_status: "underweight"
      drift_severity: "info"

    - category: "commodity"
      current_pct: 4.4
      target_pct: 5.0
      drift_pct: -0.6
      drift_status: "on_target"
      drift_severity: "info"

  concentration_flags:
    - {type: "single_stock_concentration", ticker: "AAPL", weight: 18.2%, threshold: 25%, severity: "info"}
    - {type: "sector_concentration", sector: "Technology", weight: 38.5%, threshold: 35%, severity: "warning"}

  compliance_status:
    risk_passes: true
    concentration_passes: false  # Tech sector > 35%
    factor_passes: true
```

**Decision point:** If all drift is within tolerance and compliance passes → no action needed. If drift exceeds thresholds → proceed to Step 3.

**Flags that trigger rebalancing:**
- Any asset class `drift_severity: "warning"` (≥5pp from target)
- Concentration limit breach (single stock or sector)
- Risk profile compliance failure
- `rebalance_urgency: "high"`

**UI:** Drift dashboard — horizontal bars showing current vs. target per asset class. Color-coded: green (on target), amber (minor drift), red (warning). Concentration alerts as callout cards. "Rebalance" button enabled when any drift exceeds threshold.

**Agent:** Reads drift flags. If all on-target → reports "portfolio aligned, no action needed." If warnings → summarizes drift and asks whether to generate a rebalance plan. Can run proactively on a schedule and only notify when drift exceeds thresholds.

---

### Step 3: Generate Rebalance Plan

**Purpose:** Determine what trades are needed to bring the portfolio back to target allocation.

**Tools:**
- `run_optimization(optimization_type="min_variance", format="agent")` — finds optimal weights within risk profile constraints. Returns `weight_changes` (top changes with before/after/bps), `trades_required` count, compliance status. The optimizer respects all risk limits (volatility, concentration, factor bounds).
- `run_whatif(target_weights={...})` — preview a specific target allocation. Returns before/after risk comparison, position changes, compliance checks.
- **Gap: No dedicated rebalance trade generator.** Must translate weight changes to share quantities manually. `run_optimization()` returns weights, not trade orders. Future: `generate_rebalance_trades(target_weights, portfolio_value)` → ordered trade list.

**Inputs:** Drift analysis from Step 2 + risk profile constraints

**Two approaches:**

1. **Optimization-driven** (recommended): Let optimizer find best weights within constraints
   ```
   run_optimization(optimization_type="min_variance")
   → optimized_weights: {AAPL: 0.12, MSFT: 0.10, BND: 0.15, SGOV: 0.10, ...}
   → weight_changes: [{ticker: "AAPL", original: 0.182, new: 0.12, change_bps: -620}, ...]
   → verdict: "moderate rebalance" (trades_required: 8)
   ```

2. **Target-driven**: Apply stored target allocation at asset class level, proportional within each class
   ```
   run_whatif(target_weights={derived from target_allocation + proportional split})
   → position_changes: [{position: "AAPL", before: "18.2%", after: "15.1%", change: "-3.1%"}, ...]
   ```

**Outputs:**
```
rebalance_plan:
  approach: "optimization" | "target_driven"
  verdict: "moderate rebalance"
  trades_required: 8

  weight_changes:
    sells:
      - {ticker: "AAPL", current_weight: 18.2%, target_weight: 12.0%, delta: -6.2%, est_shares: -31, est_proceeds: $28,210}
      - {ticker: "MSFT", current_weight: 14.5%, target_weight: 10.0%, delta: -4.5%, est_shares: -12, est_proceeds: $4,860}
    buys:
      - {ticker: "BND", current_weight: 10.1%, target_weight: 15.0%, delta: +4.9%, est_shares: 35, est_cost: $2,485}
      - {ticker: "SGOV", current_weight: 8.0%, target_weight: 10.0%, delta: +2.0%, est_shares: 20, est_cost: $2,010}
      - {ticker: "GLD", current_weight: 4.4%, target_weight: 5.0%, delta: +0.6%, est_shares: 1, est_cost: $295}

  impact:
    equity_allocation: 72.3% → 60.0% (on target)
    bond_allocation: 18.1% → 25.0% (on target)
    max_drift_after: 0.6pp (commodity, within tolerance)
    concentration: Tech sector 38.5% → 28.2% (within 35% limit)

  compliance_after:
    risk_passes: true
    concentration_passes: true
    factor_passes: true
```

**UI:** Rebalance plan summary card. Weight change bar chart (before → after per position). Two tabs: "Optimization" (let the math decide) vs. "Target" (stick to asset class targets). Trade list preview with estimated shares and costs. "Refine" sliders to adjust individual positions.

**Agent:** Recommends optimization-driven approach by default. Presents plan with trade count and compliance impact. If verdict is "no changes needed" or "minor rebalance" (< 3 trades), suggests skipping or partial execution.

---

### Step 4: Preview Impact

**Purpose:** Verify the rebalance plan improves the portfolio without unintended consequences.

**Tools:**
- `run_whatif(target_weights={optimized_weights}, format="agent")` — before/after comparison on all risk dimensions: volatility, concentration, factor betas, VaR, compliance
- `get_risk_score()` — compare risk score before and after (run on current, then estimate post-rebalance)

**Inputs:** Rebalance plan from Step 3

**Outputs:**
```
rebalance_impact:
  before:
    volatility: 22.5%
    market_beta: 1.05
    herfindahl: 0.082
    risk_score: 68
    tech_sector_weight: 38.5%
    max_asset_class_drift: 12.3pp

  after:
    volatility: 18.2%
    market_beta: 0.88
    herfindahl: 0.061
    risk_score: 52
    tech_sector_weight: 28.2%
    max_asset_class_drift: 0.6pp

  improvement:
    volatility: -4.3pp (-19%)
    concentration: -0.021 HHI (-26%)
    risk_score: -16 (-24%)
    drift_resolved: 3 of 4 asset classes now on target
    compliance: 1 violation resolved (sector concentration)

  tradeoffs:
    - "Reduced equity exposure may lower expected returns in bull markets"
    - "8 trades required — estimated transaction costs ~$35"

  flags:
    - {severity: "success", type: "overall_improvement", message: "Risk improved across all dimensions"}
    - {severity: "success", type: "drift_resolved", message: "All asset classes within 2pp of target"}
    - {severity: "info", type: "trade_count", message: "8 trades needed for full rebalance"}
```

**Decision point:** User/agent approves the rebalance plan, requests modifications, or decides to defer.

**UI:** Side-by-side before/after dashboard. Risk metrics comparison table with improvement percentages. Tradeoff callouts. "Approve & Execute" or "Modify Plan" buttons.

**Agent:** Summarizes: "Rebalancing would reduce risk score from 68 to 52, resolve all drift, and fix the tech concentration violation. 8 trades needed. Proceed?" If tradeoffs are significant, highlights them explicitly.

---

### Step 5: Execute Rebalance

**Purpose:** Place the trades to implement the rebalance.

**Tools:**
- `preview_trade(ticker, quantity, side)` → `execute_trade(preview_id)` — per position change
- `preview_basket_trade()` → `execute_basket_trade()` — if rebalance maps to a basket
- **Gap: No rebalance trade generator.** Must manually convert weight deltas → share quantities → trade orders. Shared gap with Hedging and Scenario Analysis workflows. Future: `generate_rebalance_trades(current_weights, target_weights, portfolio_value)` → sequenced trade list (sells first to free capital).
- **Gap: No tax-aware rebalancing.** `suggest_tax_loss_harvest()` exists but isn't integrated into the rebalance workflow. Future: check lots before selling, prefer tax-loss positions, flag wash sale risks.

**Inputs:** Approved rebalance plan from Step 4

**Outputs:**
```
execution_plan:
  sequence:   # Sells first to free capital
    1. SELL AAPL × 31 → free ~$28,210
    2. SELL MSFT × 12 → free ~$4,860
    3. SELL QQQ × 8 → free ~$3,560
    4. BUY BND × 35 → cost ~$2,485
    5. BUY SGOV × 20 → cost ~$2,010
    6. BUY GLD × 1 → cost ~$295
    7. BUY VTV × 15 → cost ~$2,115
    8. BUY SCHD × 10 → cost ~$825
  total_sells: $36,630
  total_buys: $7,730
  net_cash: +$28,900

execution_result:
  fills: [{ticker, side, quantity, fill_price, status}, ...]
  total_slippage: -$42 (0.1%)

post_execution_verification:
  new_allocation: {equity: 60.2%, bond: 24.8%, cash: 10.1%, commodity: 4.9%}
  max_drift: 0.2pp (all on target)
  risk_score: 53 (target was 52 — within tolerance)
  next_review_date: "2026-04-01" (30 days)
```

**Confirmation gate:** Explicit user approval required before any trade execution. Preview shows all orders, costs, and expected portfolio state.

**UI:** Trade queue showing all orders in execution sequence. Preview fills and estimated costs. "Execute All" with confirmation dialog. Post-execution: updated allocation chart and drift dashboard showing resolved state. Suggested next review date.

**Agent:** Presents trade plan in sequence. Asks for confirmation. After execution, runs `get_risk_analysis()` to verify allocation matches targets. Reports any remaining drift. Suggests next review date.

---

### Workflow Summary

```
Step 1: Snapshot Allocation
  Tools: get_risk_analysis, get_positions, get_risk_profile
  Output: Current allocation + targets + risk constraints
  Gap: None

Step 2: Analyze Drift
  Tools: get_risk_analysis (drift fields), get_risk_score
  Output: Per-class drift analysis, concentration flags, urgency level
  Gap: No configurable drift thresholds (hardcoded 2pp/5pp)

Step 3: Generate Rebalance Plan
  Tools: run_optimization, run_whatif
  Output: Weight changes + trade estimates + compliance forecast
  Gap: No rebalance trade generator (shared)

Step 4: Preview Impact
  Tools: run_whatif, get_risk_score
  Output: Before/after comparison, improvement summary, tradeoffs
  Gap: None

Step 5: Execute Rebalance
  Tools: preview_trade/execute_trade
  Output: Fill confirmations + post-execution verification
  Gaps: No rebalance trade generator (shared), no tax-aware rebalancing
```

### Gaps Summary

| Gap | Impact | Workaround | Shared? |
|-----|--------|------------|---------|
| Rebalance trade generator | Must manually convert weights → shares → orders | Compute from position_changes + current prices | Shared (Hedging, Scenarios, Allocation) |
| Tax-aware rebalancing | Selling may trigger unnecessary capital gains | Run `suggest_tax_loss_harvest()` separately before rebalancing | Allocation-specific integration |
| Set target allocation API | No MCP tool to set/update targets — DB only | Direct DB management or manual setup | Allocation-specific |
| Configurable drift thresholds | Hardcoded 2pp/5pp in `allocation_drift.py` | Change code to make configurable via risk profile | Allocation-specific |
| Partial rebalance | All-or-nothing — no "fix top 3 drifts only" | Manually construct partial target_weights | Allocation-specific |
| Rebalance history | No tracking of past rebalances or outcomes | Trading analysis shows historical trades | Allocation-specific |

---

## Workflow 4: Risk Review

### Overview

The risk review workflow is the portfolio's health check. It answers "where am I at risk, how bad is it, and what should I do about it?" Unlike Allocation Review (which monitors drift from targets), Risk Review monitors absolute risk levels — volatility, concentration, factor exposure, compliance — and drives toward mitigation actions when breaches are detected.

This is the most flag-driven workflow. The backend already detects 15+ flag types across 4 tools (`get_risk_analysis`, `get_risk_score`, `get_leverage_capacity`, `check_exit_signals`). The gap is connecting those flags to a prioritized action plan.

The workflow is designed for two cadences: **on-demand** (user opens risk dashboard) and **proactive** (agent runs Steps 1-2 periodically, escalates when flags appear).

### Step 1: Assess Risk State

**Purpose:** Capture the portfolio's complete risk profile — scores, compliance, exposures, concentrations, and leverage.

**Tools:**
- `get_risk_analysis(format="agent")` — volatility, Herfindahl, factor betas, variance decomposition, risk contributions, industry concentration, compliance violations, beta breaches
- `get_risk_score(format="agent")` — overall score (0-100), component scores (Concentration, Volatility, Factor, Sector), risk category, top 5 risk factors, top 5 recommendations
- `get_leverage_capacity(format="agent")` — effective leverage, max leverage, headroom, binding constraint, breach count
- `get_positions(format="agent")` — position-level context: weights, values, P&L, sectors

**Inputs:** Portfolio (loaded from current positions or specified by name)

**Outputs:**
```
risk_state:
  overall:
    risk_score: 58
    risk_category: "Elevated Risk"
    is_compliant: false
    violation_count: 3
    leverage: 1.05x
    leverage_headroom: 43%

  component_scores:
    concentration: 45     # Poor — high position concentration
    volatility: 72        # Moderate
    factor_risk: 55       # Poor — overexposed to growth
    sector_risk: 60       # Moderate — tech heavy

  key_metrics:
    volatility_annual: 24.8%
    herfindahl: 0.092
    market_beta: 1.18
    factor_variance_pct: 78%
    top5_risk_pct: 74%

  compliance:
    violations:
      - {metric: "Portfolio Volatility", actual: 24.8%, limit: 18.0%, severity: "error"}
      - {metric: "Max Single Stock", actual: 22.1%, limit: 25.0%, severity: "ok"}
    beta_breaches:
      - {factor: "growth", portfolio_beta: 0.95, max_allowed: 0.80, severity: "error"}
      - {factor: "market", portfolio_beta: 1.18, max_allowed: 1.20, severity: "warning"}

  risk_factors:
    - "High portfolio volatility (24.8% vs 18% target)"
    - "Growth factor overexposure (beta 0.95 vs 0.80 limit)"
    - "Top 5 positions drive 74% of risk"
    - "Technology sector at 38% of variance"
    - "Market beta elevated at 1.18"
```

**UI:** Risk dashboard with score gauge (0-100), component score cards, compliance status badges (pass/fail), key metrics panel. Flag banner at top sorted by severity (errors first, then warnings).

**Agent:** Loads all four tools in parallel. Synthesizes into a single risk state summary. If `is_compliant: true` and `risk_score >= 80` → "Portfolio risk looks healthy, no action needed." Otherwise → proceeds to Step 2.

---

### Step 2: Diagnose Risk Drivers

**Purpose:** For each flagged issue, drill into the root cause — which positions, factors, or concentrations are driving the problem.

**Tools:**
- `get_risk_analysis(format="agent")` — `risk_attribution` links each position to its risk contribution. `factor_exposures` shows per-factor betas. `industry_concentration` shows sector variance breakdown.
- `get_factor_analysis(analysis_type="correlations")` — cross-asset correlations reveal clustering (e.g., all tech names moving together amplifies concentration risk)
- `get_factor_analysis(analysis_type="performance")` — factor Sharpe/volatility context (is growth exposure actually rewarded?)

**Inputs:** Risk state flags from Step 1

**Diagnostic logic per flag type:**

```
Flag: compliance_violation (volatility > limit)
  → Drill: Which positions contribute most to portfolio variance?
  → Source: risk_attribution sorted by risk_pct descending
  → Output: "AAPL (22% of risk), TSLA (18% of risk), NVDA (15% of risk)"

Flag: beta_breach (growth beta > limit)
  → Drill: Which positions have highest growth beta?
  → Source: factor_exposures per position (from full analysis)
  → Output: "NVDA (growth beta 1.8), TSLA (1.5), AMZN (1.2)"

Flag: hhi_concentrated
  → Drill: Position weight distribution
  → Source: position weights from get_positions()
  → Output: "Top 3 positions hold 48% of portfolio"

Flag: risk_weight_mismatch
  → Drill: Position risk vs. weight
  → Source: risk_attribution (risk_pct vs weight_pct)
  → Output: "TSLA: 8% weight but 18% of risk (2.3x risk ratio)"

Flag: top5_dominance
  → Drill: Diversification analysis
  → Source: risk_attribution top 5
  → Output: "Top 5 drive 74% of risk — adding uncorrelated positions would help"
```

**Outputs:**
```
risk_diagnosis:
  issues:
    - id: 1
      flag: "compliance_violation"
      severity: "error"
      metric: "Portfolio Volatility"
      actual: 24.8%
      limit: 18.0%
      root_cause: "AAPL (22% risk), TSLA (18% risk), NVDA (15% risk) — 3 positions drive 55% of vol"
      driver_positions: ["AAPL", "TSLA", "NVDA"]

    - id: 2
      flag: "beta_breach"
      severity: "error"
      metric: "Growth Beta"
      actual: 0.95
      limit: 0.80
      root_cause: "NVDA (growth beta 1.8), TSLA (1.5) — two positions drive the breach"
      driver_positions: ["NVDA", "TSLA"]

    - id: 3
      flag: "top5_dominance"
      severity: "info"
      metric: "Top 5 Risk Concentration"
      actual: 74%
      threshold: 70%
      root_cause: "Insufficient diversification — 15 positions but risk dominated by 5"
      driver_positions: ["AAPL", "TSLA", "NVDA", "MSFT", "GOOGL"]

  overlap_analysis:
    - "TSLA and NVDA appear in both volatility and growth beta issues — addressing these positions would resolve 2 violations simultaneously"
```

**UI:** Expandable issue cards — each flag becomes a card with root cause detail, driver positions highlighted. Position cross-reference: positions that appear in multiple issues are flagged as "high-impact action targets." Correlation heatmap showing why positions cluster.

**Agent:** Identifies overlap — positions driving multiple issues are highest-priority targets. Summarizes: "TSLA and NVDA drive both the volatility breach and the growth beta breach. Reducing these two positions would address both issues. AAPL drives concentration but is within compliance — lower priority."

---

### Step 3: Recommend Mitigations

**Purpose:** For each diagnosed issue, generate specific, actionable recommendations ranked by impact.

**Tools:**
- `get_risk_score(format="agent")` — `recommendations` field provides top 5 risk management recommendations
- `get_factor_recommendations(mode="portfolio")` — auto-detects risk drivers, suggests hedge instruments (negatively correlated ETFs, sectors, commodities)
- `get_factor_recommendations(mode="single", overexposed_factor=...)` — targeted hedge search for a specific factor breach
- `suggest_tax_loss_harvest()` — if reducing positions, check for tax-efficient lots to sell first
- `check_exit_signals()` — for positions flagged as risk drivers, check if exit signals are active

**Inputs:** Risk diagnosis from Step 2

**Recommendation generation:**

```
For each issue:
  1. Reduction actions: Reduce weight of driver positions (trim, not necessarily exit)
  2. Hedge actions: Add offsetting positions (from factor recommendations)
  3. Profile actions: Adjust risk limits if current profile is too aggressive/conservative
  4. Combined actions: Stack reduction + hedge for maximum impact

Ranking criteria:
  - Impact: How much does this reduce the flagged metric?
  - Cost: Transaction cost + tax impact + opportunity cost
  - Complexity: Number of trades required
  - Multi-issue resolution: Actions that fix 2+ issues ranked higher
```

**Outputs:**
```
mitigation_plan:
  actions:
    - id: "A1"
      type: "reduce"
      priority: 1
      description: "Trim TSLA from 12% to 6% weight"
      resolves: ["volatility_breach", "growth_beta_breach"]
      estimated_impact:
        volatility: 24.8% → 21.5% (-3.3pp)
        growth_beta: 0.95 → 0.78 (within limit)
      trades: [{action: "SELL", ticker: "TSLA", quantity: 50, est_proceeds: $12,500}]
      tax_impact: "$800 short-term gain" | "tax-loss opportunity: -$200"

    - id: "A2"
      type: "reduce"
      priority: 2
      description: "Trim NVDA from 10% to 7% weight"
      resolves: ["volatility_breach", "growth_beta_breach"]
      estimated_impact:
        volatility: 21.5% → 19.8% (-1.7pp) [after A1]
        growth_beta: 0.78 → 0.72 (further below limit)
      trades: [{action: "SELL", ticker: "NVDA", quantity: 25, est_proceeds: $8,750}]

    - id: "A3"
      type: "hedge"
      priority: 3
      description: "Add XLU (5% weight) to offset equity beta"
      resolves: ["volatility_breach"]
      estimated_impact:
        volatility: 19.8% → 18.5% (-1.3pp) [after A1+A2]
        market_beta: 1.18 → 1.02
      trades: [{action: "BUY", ticker: "XLU", quantity: 110, est_cost: $7,425}]
      hedge_source: "get_factor_recommendations(mode='portfolio')"

    - id: "A4"
      type: "profile"
      priority: 4
      description: "Switch from 'growth' to 'balanced' risk profile"
      resolves: ["growth_beta_breach"]
      estimated_impact: "Widens growth beta limit from 0.80 to 0.85"
      trades: []
      note: "Only changes limits, not portfolio — use if portfolio changes aren't desired"

  summary:
    actions_A1_A2: "Trimming TSLA and NVDA resolves both compliance violations"
    actions_A1_A2_A3: "Adding XLU hedge brings volatility within 18% target"
    total_trades: 3 (2 sells + 1 buy)
    total_cost: net proceeds $13,825
    issues_resolved: 3 of 3
```

**UI:** Action cards sorted by priority. Each card shows: what to do, which issues it resolves, estimated impact, trade detail. Dependency indicators (A2 impact assumes A1 is done). Multi-select checkboxes to build a combined action plan. "Preview Combined Impact" button.

**Agent:** Presents prioritized action plan. Recommends: "Trimming TSLA and NVDA (actions A1 + A2) would resolve both compliance violations. Adding an XLU hedge (A3) would bring volatility within your 18% target. Total: 3 trades, net proceeds of $13.8K. Want to preview the combined impact?"

---

### Step 4: Preview Combined Impact

**Purpose:** Simulate the combined effect of all selected mitigation actions before executing.

**Tools:**
- `run_whatif(delta_changes={...}, format="agent")` — simulate all selected actions as a single scenario. Returns before/after for all risk metrics, compliance status, factor betas, position changes.
- `get_risk_score()` — estimate post-mitigation risk score (approximate — run on current portfolio as proxy)

**Inputs:** Selected actions from Step 3 (combined into a single delta_changes dict)

**Outputs:**
```
mitigation_impact:
  before:
    risk_score: 58
    volatility: 24.8%
    market_beta: 1.18
    growth_beta: 0.95
    herfindahl: 0.092
    compliance_violations: 3

  after:
    risk_score: ~76 (estimated)
    volatility: 18.5%
    market_beta: 1.02
    growth_beta: 0.72
    herfindahl: 0.068
    compliance_violations: 0

  improvement:
    risk_score: +18 points (+31%)
    volatility: -6.3pp (-25%)
    all_violations_resolved: true
    risk_category: "Elevated Risk" → "Moderate Risk"

  flags:
    - {severity: "success", type: "overall_improvement", message: "All 3 compliance violations resolved"}
    - {severity: "success", type: "volatility_decrease", message: "Volatility reduced from 24.8% to 18.5%"}
    - {severity: "info", type: "trade_count", message: "3 trades required"}
```

**Decision point:** User/agent approves the mitigation plan, adjusts (re-select actions), or defers.

**UI:** Before/after risk dashboard side-by-side. Compliance status: red badges → green badges. Risk score gauge animation (58 → 76). "Approve & Execute" or "Modify" buttons.

**Agent:** Summarizes: "This plan resolves all 3 violations, improves risk score from 58 to ~76, and reduces volatility by 25%. 3 trades needed. Proceed to execution?"

---

### Step 5: Execute Mitigations

**Purpose:** Place the trades to implement the chosen mitigation actions.

**Tools:**
- `preview_trade(ticker, quantity, side)` → `execute_trade(preview_id)` — per trade
- `preview_basket_trade()` → `execute_basket_trade()` — if a hedge maps to a basket
- **Gap: No rebalance trade generator** (shared). Must manually construct trade list from action plan.
- **Gap: No action tracking / audit trail.** No persistence of which recommendations were accepted/rejected/executed. Future: `record_risk_action(action_id, status, execution_result)` for compliance audit.

**Inputs:** Approved action plan from Step 4

**Outputs:**
```
execution_plan:
  sequence:
    1. SELL TSLA × 50 → free ~$12,500
    2. SELL NVDA × 25 → free ~$8,750
    3. BUY XLU × 110 → cost ~$7,425
  net_proceeds: $13,825

execution_result:
  fills: [{ticker, side, quantity, fill_price, status}, ...]
  total_slippage: -$28 (0.1%)

post_execution_verification:
  new_risk_score: 74
  new_volatility: 18.7%
  compliance_violations: 0
  growth_beta: 0.73 (within 0.80 limit)
  market_beta: 1.03 (within 1.20 limit)
  all_issues_resolved: true
```

**Confirmation gate:** Explicit user approval before any execution.

**UI:** Trade queue with execution sequence. Post-execution: re-run risk dashboard showing all flags resolved, updated risk score.

**Agent:** Presents trade plan. After execution, runs `get_risk_analysis()` + `get_risk_score()` to verify all violations resolved. Reports final state.

---

### Workflow Summary

```
Step 1: Assess Risk State
  Tools: get_risk_analysis, get_risk_score, get_leverage_capacity, get_positions
  Output: Risk score, compliance status, component scores, key metrics
  Gap: None (strong detection layer)

Step 2: Diagnose Risk Drivers
  Tools: get_risk_analysis (attribution), get_factor_analysis (correlations, performance)
  Output: Per-flag root cause, driver positions, overlap analysis
  Gap: No automated driver synthesis (agent must cross-reference manually)

Step 3: Recommend Mitigations
  Tools: get_risk_score (recommendations), get_factor_recommendations, suggest_tax_loss_harvest, check_exit_signals
  Output: Prioritized action plan with estimated impact per action
  Gap: No unified action synthesis tool, no impact estimation without running whatif

Step 4: Preview Combined Impact
  Tools: run_whatif, get_risk_score
  Output: Before/after comparison for combined actions
  Gap: None (whatif handles combined scenarios)

Step 5: Execute Mitigations
  Tools: preview_trade/execute_trade
  Output: Fill confirmations + post-execution risk verification
  Gaps: No rebalance trade generator (shared), no action audit trail
```

### Gaps Summary

| Gap | Impact | Workaround | Shared? |
|-----|--------|------------|---------|
| Unified action synthesis | Must manually cross-reference flags → recommendations → trades | Agent chains tools in sequence | Risk-specific |
| Impact estimation per action | Can't estimate impact without running full whatif | Run whatif per candidate action | Risk-specific |
| Action audit trail | No record of which recommendations were taken | Conversation/session context only | Risk-specific |
| Historical risk trending | Can't show "risk is getting worse over time" | Compare to last manual run | Risk-specific |
| Automated driver synthesis | Agent must cross-reference attribution across tools | Agent-driven pattern matching | Risk-specific |
| Rebalance trade generator | Must manually build trade list from actions | Compute from delta_changes | Shared (all workflows) |
| Composable action stacking | Can't preview sequential actions (A1 then A2 effect) | Run whatif with combined deltas | Risk-specific |

---

## Workflow 5: Performance Review

### Overview

The performance review workflow answers "how is my portfolio actually doing, why, and what should I change?" It connects return measurement through attribution diagnosis to actionable improvements. This workflow is unique in having two distinct lenses — **hypothetical** (current-weights backtested) and **realized** (actual transaction-based) — which can tell very different stories.

The workflow naturally splits into a **measurement phase** (Steps 1-2, always valuable) and a **diagnostic/action phase** (Steps 3-5, triggered by underperformance or anomalies). Like Risk Review, an agent can run Steps 1-2 proactively and only escalate when flags fire.

### Step 1: Measure Returns

**Purpose:** Compute portfolio performance over the analysis period, compare to benchmark, and surface risk-adjusted metrics.

**Tools:**
- `get_performance(mode="hypothetical", benchmark_ticker="SPY", format="agent")` — backtests current weights over historical period. Returns: total return, CAGR, volatility, Sharpe, Sortino, max drawdown, alpha, beta, R², win rate.
- `get_performance(mode="realized", format="agent")` — actual transaction-based returns. Adds: realized/unrealized P&L, income (dividends + interest), data quality metrics (coverage, reliability, synthetic count).
- `get_income_projection(format="agent")` — forward dividend/income estimate: annual yield, monthly schedule, position-level income breakdown.

**Inputs:**
```
portfolio: current positions or named portfolio
benchmark_ticker: "SPY" (default, any ticker supported)
mode: "hypothetical" | "realized" | both
date_range: optional (start_date, end_date) — supports custom windows
source: optional — filter realized to specific provider (schwab, plaid, etc.)
institution: optional — filter to specific brokerage
account: optional — filter to specific account
```

**Outputs:**
```
performance_snapshot:
  hypothetical:
    total_return: +18.5%
    annualized_return: 12.3%
    volatility: 19.2%
    sharpe_ratio: 0.64
    sortino_ratio: 0.91
    max_drawdown: -14.2%
    win_rate: 58%
    best_month: +6.8%
    worst_month: -8.1%
    verdict: "fair"

  benchmark:
    ticker: "SPY"
    benchmark_return: 15.2%
    alpha_annual: +3.3%
    beta: 1.08
    r_squared: 0.85
    excess_return: +3.3%

  realized:
    nav_pnl: +$42,500
    realized_pnl: +$18,200
    unrealized_pnl: +$24,300
    income_total: $8,750
    dividends: $7,200
    interest: $1,550
    yield_on_cost: 3.2%
    yield_on_value: 2.8%
    data_quality:
      coverage: 87%
      reliable: true
      synthetic_count: 3

  income_projection:
    annual_estimated: $9,200
    next_12mo_confirmed: $4,800
    portfolio_yield: 2.8%
```

**Flags surfaced:**
- `outperforming` (success) — beating benchmark
- `benchmark_underperformance` (warning) — alpha < -5% annualized
- `negative_total_return` (warning) — portfolio is down
- `deep_drawdown` (warning) — max drawdown > 20%
- `low_sharpe` (warning) — Sharpe < 0.3 over 1+ year
- `high_volatility` (info) — vol > 25%
- `realized_reliability_warning` (warning) — low data coverage
- `high_confidence` (success) — reliable realized data

**UI:** Performance dashboard with period returns (1D/1W/1M/3M/1Y/YTD), time series chart (portfolio vs benchmark), risk-adjusted metrics panel, income summary card. Toggle for hypothetical vs. realized mode. Benchmark selector. Flag banner at top.

**Agent:** Runs both modes in parallel. If hypothetical and realized diverge significantly (e.g., hypothetical +18% but realized +8%), flags: "Timing drag: trade execution cost 10% in returns vs. buy-and-hold." Proceeds to Step 2 if any warning flags fire.

---

### Step 2: Attribute Returns

**Purpose:** Decompose returns into their sources — which sectors, factors, and individual positions drove or dragged performance.

**Tools:**
- `get_risk_analysis(format="agent")` — factor betas, variance decomposition, industry concentration. Used as proxy for factor attribution when direct attribution is unavailable.
- `get_factor_analysis(analysis_type="performance")` — factor Sharpe ratios, factor volatility, factor returns. Shows whether the factors the portfolio is exposed to actually delivered returns.
- `get_factor_analysis(analysis_type="returns", windows=["1m","3m","6m","1y"])` — trailing factor returns by window. Identifies which factors drove recent performance.
- `get_trading_analysis(format="agent")` — trade-level quality: win rate, profit factor, payoff ratio, avg hold duration, entry/exit timing grades. Reveals whether trade execution helped or hurt.

**Gap: No direct return attribution.** The `sector_attribution`, `factor_attribution`, and `security_attribution` fields exist in `PerformanceResult` but are **never populated**. No Brinson decomposition or Fama-French return attribution is implemented. Workaround: combine factor exposure (from risk analysis) with factor returns (from factor analysis) to estimate contribution.

**Inputs:** Performance snapshot from Step 1

**Attribution approach (workaround):**
```
For each factor the portfolio is exposed to:
  factor_contribution ≈ portfolio_factor_beta × factor_return

Example:
  market_beta: 1.08 × market_return: +12% = ~12.96% from market
  growth_beta: 0.85 × growth_return: +8% = ~6.80% from growth
  value_beta: -0.20 × value_return: +4% = ~-0.80% from value
  residual (selection): total_return - sum(factor_contributions) = ~0.34%
```

**Outputs:**
```
attribution_analysis:
  factor_attribution:  # Estimated from beta × return
    - {factor: "market", beta: 1.08, factor_return: 12.0%, contribution: 12.96%}
    - {factor: "growth", beta: 0.85, factor_return: 8.0%, contribution: 6.80%}
    - {factor: "value", beta: -0.20, factor_return: 4.0%, contribution: -0.80%}
    - {factor: "momentum", beta: 0.45, factor_return: 2.0%, contribution: 0.90%}
    - {factor: "selection", contribution: 0.34%}  # Residual

  factor_context:
    - "Growth factor delivered +8% — your 0.85 beta captured most of it"
    - "Value factor delivered +4% but your -0.20 beta cost 0.8%"
    - "Momentum contributed +0.9% — moderate tailwind"

  trade_quality:  # From trading analysis
    overall_grade: "B-"
    win_rate: 62%
    profit_factor: 1.8
    avg_hold_days: 45
    entry_timing: "Fair" (bought near 60th percentile)
    exit_timing: "Good" (sold near 75th percentile)
    disposition_effect: "Mild" (slight tendency to hold losers)

  income_attribution:
    dividend_contribution: +1.4% of total return
    interest_contribution: +0.3% of total return
    income_total_contribution: +1.7%

  performance_vs_hypothesis:
    hypothetical_return: +18.5%
    realized_return: +14.2%
    timing_drag: -4.3%  # Cost of actual trade timing vs. buy-and-hold
    explanation: "Entry timing on NVDA and TSLA cost ~2.1%, late exit on META cost ~1.5%"
```

**UI:** Attribution breakdown chart — stacked bar showing factor contributions. Trade quality scorecard. Income contribution card. Hypothetical vs. realized comparison with timing drag explanation. Drill-down on individual factors showing which positions drove the exposure.

**Agent:** Synthesizes: "Your 18.5% hypothetical return was driven primarily by market beta (13%) and growth exposure (6.8%). Value detracted slightly (-0.8%). Actual realized return was 14.2% — the 4.3% gap came from trade timing, mainly late entries on tech names. Trade quality is B- with a mild disposition effect."

---

### Step 3: Diagnose Issues

**Purpose:** For each performance flag or attribution anomaly, identify the root cause and potential fixes.

**Tools:**
- `get_risk_analysis(format="agent")` — risk attribution links positions to risk contribution (positions dragging returns often have outsized risk contribution)
- `get_trading_analysis(format="agent")` — trade-level diagnostics: which specific trades were worst? Behavioral patterns (disposition effect, overtrading)?
- `check_exit_signals()` — for positions with unrealized losses, are exit signals active?
- `get_factor_analysis(analysis_type="correlations")` — are the portfolio's factor exposures aligned with the regime that played out?

**Diagnostic logic per flag:**

```
Flag: benchmark_underperformance (alpha < -5%)
  → Drill: Factor attribution — which factor bets lost?
  → Check: Was the portfolio overexposed to underperforming factors?
  → Output: "Growth factor returned -3% but portfolio had 1.2 beta — cost 3.6%"

Flag: deep_drawdown (max_drawdown > 20%)
  → Drill: When did it happen? Which positions drove it?
  → Check: Were exit signals active during the drawdown?
  → Output: "Max drawdown hit -22% in Oct 2025, driven by TSLA (-35%) and NVDA (-28%)"

Flag: low_sharpe (Sharpe < 0.3)
  → Drill: Is it return problem (low return) or risk problem (high vol)?
  → Check: Compare to benchmark Sharpe
  → Output: "Portfolio Sharpe 0.25 vs SPY 0.72 — excess volatility (+6pp) with no return premium"

Flag: negative_total_return
  → Drill: Factor vs. selection — was market down too, or just portfolio?
  → Check: Benchmark return for context
  → Output: "Portfolio -8% vs SPY +12% — significant underperformance driven by stock selection"

Flag: timing_drag (hypothetical >> realized)
  → Drill: Trading analysis — which trades had worst timing?
  → Check: Entry/exit percentiles per trade
  → Output: "Average entry at 65th percentile (buying high). Top 3 timing losses: NVDA, META, TSLA"
```

**Outputs:**
```
diagnosis:
  issues:
    - id: 1
      flag: "benchmark_underperformance"
      severity: "warning"
      root_cause: "Growth factor bet lost — growth returned -3%, portfolio beta 1.2"
      impact: "-3.6% drag from growth exposure"
      driver_positions: ["NVDA", "TSLA", "AMZN"]
      actionable: true

    - id: 2
      flag: "timing_drag"
      severity: "info"
      root_cause: "Trade entry timing — buying near highs on tech names"
      impact: "-4.3% vs. buy-and-hold"
      driver_trades: ["NVDA entry +8% above avg", "META exit -12% below peak"]
      actionable: true

  behavioral_patterns:
    - "Mild disposition effect — holding losers 40% longer than winners"
    - "Overconcentrated entries — 3 of last 5 buys were tech sector"
```

**UI:** Issue cards with root cause, impact, and driver positions/trades. Behavioral pattern callouts. Links to individual trade details. "Fix this" button on actionable issues.

**Agent:** Prioritizes issues by impact. "The biggest performance drag is growth factor exposure (-3.6%), followed by trade timing (-4.3%). Reducing growth beta and using limit orders for tech entries would address both."

---

### Step 4: Recommend Improvements

**Purpose:** Generate specific, actionable recommendations to improve future performance based on the diagnosis.

**Tools:**
- `get_factor_recommendations(mode="portfolio")` — if factor exposure is the problem, find better factor alignment
- `run_optimization(optimization_type="max_return")` — if allocation is suboptimal, find higher-return weights within constraints
- `run_whatif(delta_changes={...})` — preview impact of recommended changes on risk/return profile
- `suggest_tax_loss_harvest()` — if selling underperformers, check for tax-efficient exits

**Recommendation categories:**

1. **Factor alignment** — adjust factor exposures to match rewarded factors
2. **Position changes** — trim/exit underperformers, add/increase outperformers
3. **Execution improvement** — trade timing, order types, behavioral nudges
4. **Income optimization** — dividend rebalancing for income investors

**Outputs:**
```
recommendations:
  - id: "R1"
    category: "factor_alignment"
    priority: 1
    description: "Reduce growth beta from 1.2 to 0.7 — growth factor underperforming"
    actions: [{sell: "NVDA -3%", sell: "TSLA -4%", buy: "VTV +5%"}]
    estimated_impact: "+2-3% annual alpha improvement"
    tradeoff: "Miss upside if growth recovers"

  - id: "R2"
    category: "position_change"
    priority: 2
    description: "Exit META — negative exit signals active, -12% unrealized loss"
    actions: [{sell: "META 100%"}]
    estimated_impact: "Tax loss harvest -$2,400 + reduce vol by 1.2pp"
    tax_status: "Short-term loss, no wash sale risk"

  - id: "R3"
    category: "execution"
    priority: 3
    description: "Use limit orders for tech entries — timing drag costing 4%+ annually"
    actions: []  # Behavioral, not a trade
    estimated_impact: "Could recover 1-2% of timing drag"

  - id: "R4"
    category: "income"
    priority: 4
    description: "Shift 5% from non-dividend to dividend payers — increase yield from 2.8% to 3.4%"
    actions: [{sell: "TSLA -3%", buy: "SCHD +3%"}]
    estimated_impact: "+$3,000 annual income"
```

**UI:** Recommendation cards sorted by priority. Each card: description, actions, estimated impact, tradeoff. "Preview Impact" button runs whatif for trade-based recommendations. Behavioral recommendations shown as insight cards (no trade action).

**Agent:** Presents top recommendations. For trade-based ones, offers to preview impact via whatif. For behavioral ones, notes them as process improvements.

---

### Step 5: Preview & Execute

**Purpose:** For trade-based recommendations, simulate combined impact and execute.

**Tools:**
- `run_whatif(delta_changes={...})` — preview combined effect of all selected recommendations
- `preview_trade()` → `execute_trade()` — standard execution path
- `suggest_tax_loss_harvest()` — check tax implications before selling

**Inputs:** Selected recommendations from Step 4

**Outputs:**
```
combined_impact:
  before:
    annualized_return: 12.3% (hypothetical)
    volatility: 19.2%
    sharpe: 0.64
    growth_beta: 1.2
    income_yield: 2.8%

  after (projected):
    volatility: 17.1% (-2.1pp)
    growth_beta: 0.7 (within target)
    income_yield: 3.4% (+0.6pp)
    sharpe: ~0.72 (estimated improvement)

  trades:
    1. SELL NVDA × 15 (trim -3%)
    2. SELL TSLA × 20 (trim -4%)
    3. SELL META × all (exit, tax loss)
    4. BUY VTV × 45 (+5%)
    5. BUY SCHD × 30 (+3%)
  net_cash: -$1,200

  tax_impact:
    META: -$2,400 short-term loss harvested
    NVDA: +$800 short-term gain
    net_tax_benefit: -$1,600
```

**Confirmation gate:** Explicit user approval before execution. Post-execution: re-run performance analysis in 30 days to measure improvement.

**UI:** Before/after metrics panel. Trade list with tax impact. "Execute" with confirmation. Post-execution: "Review again in 30 days" reminder.

**Agent:** Presents trade plan with tax impact. After execution, schedules mental reminder to re-check performance next month.

---

### Workflow Summary

```
Step 1: Measure Returns
  Tools: get_performance (hypothetical + realized), get_income_projection
  Output: Return metrics, benchmark comparison, income summary, flags
  Gap: None (strong measurement layer)

Step 2: Attribute Returns
  Tools: get_risk_analysis, get_factor_analysis (performance + returns), get_trading_analysis
  Output: Factor/sector/trade attribution, timing analysis
  Gap: No direct return attribution (Brinson/Fama-French not implemented)

Step 3: Diagnose Issues
  Tools: get_risk_analysis, get_trading_analysis, check_exit_signals, get_factor_analysis
  Output: Root cause per flag, driver positions/trades, behavioral patterns
  Gap: No automated diagnosis synthesis

Step 4: Recommend Improvements
  Tools: get_factor_recommendations, run_optimization, run_whatif, suggest_tax_loss_harvest
  Output: Prioritized recommendations (factor, position, execution, income)
  Gap: No performance-to-action recommendation engine

Step 5: Preview & Execute
  Tools: run_whatif, preview_trade/execute_trade, suggest_tax_loss_harvest
  Output: Combined impact preview, trade execution, tax impact
  Gap: Rebalance trade generator (shared)
```

### Gaps Summary

| Gap | Impact | Workaround | Shared? |
|-----|--------|------------|---------|
| Return attribution (Brinson/FF) | Can't decompose returns by factor/sector/selection | Estimate via beta × factor_return proxy | Performance-specific |
| Multi-benchmark comparison | Single benchmark only per run | Run `get_performance` multiple times with different benchmarks | Performance-specific |
| Performance → action engine | No automated "underperforming → here's what to change" | Agent chains diagnosis → recommendation tools | Performance-specific |
| Drawdown recovery tracking | Can't show "peak was X, we've recovered Y%" | Compute from monthly_returns time series | Performance-specific |
| Hypothetical vs. realized reconciliation | No automated timing drag analysis | Agent compares both modes and computes difference | Performance-specific |
| Rolling window metrics | No 1Y rolling Sharpe, rolling vol | Must compute from monthly_returns client-side | Performance-specific |
| Rebalance trade generator | Must manually build trade list | Compute from delta_changes | Shared (all workflows) |

---

## Workflow 6: Stock Research

### Overview

The stock research workflow takes a user from "I'm interested in this stock" to "I've added it to my portfolio at the right size." It aggregates multiple data sources — risk analysis, fundamentals, technicals, earnings, news, peer comparison — into a comprehensive research view, then connects to position sizing and execution.

Unlike the portfolio-level workflows (Risk Review, Performance, Allocation), this workflow is **single-stock focused**. The portfolio context enters at Step 3 (how does this stock fit?) and Step 4 (what's the right size?).

The backend is notably complete for this workflow — almost all data sources exist as MCP tools. The primary gap is orchestration (auto-fetching everything for one ticker) and frontend wiring (search is mocked, no buy button).

### Step 1: Find & Profile

**Purpose:** Search for a stock by name/ticker and load its company profile.

**Tools:**
- `fmp_search(query, limit=10)` — search companies by name or ticker. Returns: symbol, name, currency, exchange.
- `fmp_profile(symbol)` — comprehensive company data: sector, industry, market cap, CEO, employees, price, beta, volume, DCF valuation, website, description.

**Inputs:**
```
query: "apple" | "AAPL" | "semiconductor companies"
```

**Outputs:**
```
search_results:
  - {symbol: "AAPL", name: "Apple Inc.", exchange: "NASDAQ", currency: "USD"}
  - {symbol: "APLE", name: "Apple Hospitality REIT", exchange: "NYSE", currency: "USD"}

selected_profile:
  symbol: "AAPL"
  name: "Apple Inc."
  sector: "Technology"
  industry: "Consumer Electronics"
  market_cap: $3.05T
  price: $195.50
  beta: 1.18
  volume_avg: 52.3M
  dcf_valuation: $220.00
  dcf_diff: +$24.50 (12.5% upside to DCF)
  employees: 161,000
  ceo: "Tim Cook"
  description: "Apple Inc. designs, manufactures..."
```

**Gap: Frontend search is mocked.** `fmp_search()` exists and works but isn't wired to the frontend StockLookup component. The UI shows hardcoded search results.

**UI:** Search bar with typeahead results (from `fmp_search`). Clicking a result loads the full profile card: company name, sector, price, market cap, DCF valuation, description.

**Agent:** Takes natural language ("tell me about Apple" or "find semiconductor stocks") → calls `fmp_search` → selects best match → loads profile. Can filter by exchange if specified.

---

### Step 2: Analyze

**Purpose:** Run comprehensive analysis across all available dimensions — risk, fundamentals, technicals, earnings, news.

**Tools (all available, run in parallel):**
- `analyze_stock(ticker, format="agent")` — single-stock risk: volatility (annual/monthly), beta, alpha, R², Sharpe, max drawdown, factor exposures (market, momentum, value, industry, subindustry). Bond analytics for fixed-income.
- `get_technical_analysis(symbol, timeframe="1day")` — trend direction (bullish/bearish/neutral), momentum signals (RSI, MACD), volatility (Bollinger, ADX), support/resistance levels, overall buy/sell/hold signal.
- `compare_peers(symbol, format="summary")` — P/E, P/B, P/S, ROE, ROA, margins, debt/equity, dividend yield vs. auto-detected peers (same sector + similar market cap). Up to 60+ TTM ratios in full format.
- `get_estimate_revisions(ticker, period="quarter")` — earnings estimate revision history: EPS/revenue deltas, direction (up/down/flat), revision count, trend.
- `get_news(symbols=ticker, mode="stock", quality="trusted")` — recent stock-specific news from trusted sources.
- `analyze_option_chain(symbol, expiry)` — OI/volume concentration, put/call ratio, max pain, implied volatility by strike. (Requires IBKR connection.)

**Inputs:** Ticker from Step 1

**Outputs:**
```
research_analysis:
  risk_profile:
    verdict: "moderate risk"
    volatility_annual: 28.5%
    beta: 1.15
    sharpe: 1.23
    max_drawdown: -45.2%
    factor_exposures: {market: 1.22, momentum: 0.85, value: -0.12}
    flags: ["high_beta (1.15)", "style_tilt (value: -0.12)"]

  technicals:
    trend: "bullish"
    momentum: "RSI 62 — neutral, approaching overbought"
    macd: "bullish crossover 3 days ago"
    bollinger: "price near upper band — extended"
    support: $185.00
    resistance: $202.50
    signal: "hold" (bullish trend but extended near resistance)

  fundamentals:  # From profile + peer comparison
    pe_ratio: 32.5 (peers avg: 28.1)
    pb_ratio: 48.2 (peers avg: 12.5)
    roe: 160% (peers avg: 25%)
    debt_equity: 1.95 (peers avg: 1.10)
    net_margin: 26.3% (peers avg: 18.5%)
    dividend_yield: 0.52% (peers avg: 1.1%)
    valuation_vs_peers: "Premium — trades at 16% P/E premium to peers"

  earnings:
    latest_revision: "up" (+$0.05 EPS, +2.1%)
    revision_trend: "3 upward revisions in last 90 days"
    consensus_eps: $6.85
    consensus_revenue: $395B

  news:
    recent_headlines:
      - "Apple announces new AI features at WWDC" (2 days ago)
      - "iPhone sales beat estimates in China" (5 days ago)
    sentiment: "positive" (3 positive, 1 neutral, 0 negative in last 7 days)

  options:  # If IBKR connected
    put_call_ratio: 0.85 (slightly bullish)
    max_pain: $190
    high_oi_strikes: [$190 call, $185 put, $200 call]
    implied_vol: 26.5%
```

**Stock flags surfaced:**
- `very_high_volatility` (warning) — vol > 50%
- `high_beta` / `extreme_beta` (info/warning) — |beta| > 1.5 / 2.0
- `negative_sharpe` (warning) — Sharpe < 0
- `strong_sharpe` (success) — Sharpe > 1.5
- `deep_drawdown` (warning) — max DD < -50%
- `momentum_tilt` / `style_tilt` (info) — strong factor tilts
- `well_behaved` (success) — moderate vol, reasonable beta, good R²

**UI:** Multi-tab research view:
- **Overview**: Risk metrics + verdict + flags
- **Technicals**: Chart with indicators, buy/sell/hold signal
- **Fundamentals**: Peer comparison table, valuation metrics
- **Earnings**: Revision timeline, consensus estimates
- **News**: Recent headlines with sentiment
Each tab loads from its respective backend tool.

**Agent:** Runs all tools in parallel for comprehensive research. Synthesizes: "AAPL is moderate risk (beta 1.15, Sharpe 1.23). Technically bullish but extended near resistance. Fundamentally premium-valued (32.5x P/E vs peers 28x) but best-in-class margins. Earnings revisions trending up. Recent news positive."

---

### Step 3: Evaluate Portfolio Fit

**Purpose:** Assess how this stock fits the existing portfolio — does it add diversification, does it duplicate existing exposures, does it change the risk profile?

**Tools:**
- `get_risk_analysis(format="agent")` — current portfolio factor exposures, concentration, sector weights. Compare to the stock's factor profile from Step 2.
- `get_factor_analysis(analysis_type="correlations")` — correlation of this stock's factors with existing portfolio factors. High correlation = less diversification benefit.
- `run_whatif(delta_changes={ticker: "+5%"}, format="agent")` — simulate adding the stock at a trial allocation. Returns: volatility impact, concentration change, factor beta shifts, compliance check.

**Inputs:** Stock analysis from Step 2 + current portfolio

**Outputs:**
```
portfolio_fit:
  current_portfolio:
    tech_weight: 38.5%
    market_beta: 1.05
    growth_beta: 0.85
    volatility: 22.5%

  stock_overlap:
    sector_overlap: "Technology — already 38.5% of portfolio"
    factor_overlap: "High market beta (1.22) and growth tilt — amplifies existing exposures"
    correlation_to_portfolio: 0.78 (high — limited diversification)
    similar_holdings: ["MSFT", "GOOGL", "NVDA"]  # Same sector/factor profile

  trial_allocation:  # run_whatif with +5%
    at_5pct:
      volatility: 22.5% → 23.1% (+0.6pp)
      market_beta: 1.05 → 1.07
      tech_weight: 38.5% → 43.5%
      herfindahl: 0.082 → 0.085
      compliance: {risk_passes: true, concentration_passes: false}  # Tech > 35% limit
      verdict: "Adds to existing tech concentration — consider sizing carefully"

  diversification_score: "Low" (high correlation, same sector)
  fit_assessment: "AAPL would amplify existing tech/growth exposure. Consider smaller allocation or pair with a diversifying position."
```

**Decision point:** Is this stock worth adding given portfolio context? If yes → proceed to sizing.

**UI:** Portfolio fit panel showing: sector overlap visualization, correlation gauge (0-1), trial allocation before/after mini-dashboard, compliance flag if limit breached. "Add to Portfolio" button (enabled) or "Concentration Warning" card (if limit breached).

**Agent:** "Adding AAPL at 5% would increase tech from 38.5% to 43.5%, which breaches your 35% sector limit. You could add at 2% to stay within limits, or pair with a non-tech position. Shall I size it at 2% instead?"

---

### Step 4: Size Position

**Purpose:** Determine the right allocation and share quantity for the new position.

**Tools:**
- `run_whatif(delta_changes={ticker: "+X%"})` — test multiple allocation levels (1%, 2%, 5%, 10%) to find the sweet spot between impact and concentration.
- `get_leverage_capacity()` — ensure the position doesn't push leverage beyond capacity.
- `analyze_option_strategy(legs=[...])` — if using options for entry (e.g., cash-secured put for discounted entry), model the strategy.

**Inputs:** Stock analysis from Step 2 + portfolio fit from Step 3

**Sizing approaches:**

1. **Risk-budget sizing** — allocate based on target risk contribution (e.g., "this stock should contribute no more than 5% of portfolio risk")
2. **Equal-weight sizing** — match average position weight (portfolio_value / position_count)
3. **Conviction sizing** — user specifies target weight directly
4. **Options entry** — sell cash-secured put at discount, or buy call for leveraged exposure

**Outputs:**
```
position_sizing:
  recommended_weight: 2.5%
  rationale: "Keeps tech sector under 35% limit while adding meaningful exposure"

  sizing_scenarios:
    - weight: 1%
      shares: 26
      cost: $5,083
      vol_impact: +0.1pp
      compliance: PASS
    - weight: 2.5%
      shares: 64
      cost: $12,512
      vol_impact: +0.3pp
      compliance: PASS
    - weight: 5%
      shares: 128
      cost: $25,024
      vol_impact: +0.6pp
      compliance: FAIL (tech sector > 35%)

  options_alternative:
    strategy: "Cash-secured put"
    strike: $185 (5.4% discount to current)
    expiry: "2026-04-17"
    premium_received: $3.20/share ($320 per contract)
    effective_entry: $181.80
    max_risk: $18,180 per contract (if assigned)
```

**UI:** Allocation slider (1%-10%) with real-time impact preview. Sizing scenario cards. Options alternative section (if IBKR connected). "Set Allocation" button to confirm.

**Agent:** Recommends allocation based on constraints: "2.5% ($12.5K, 64 shares) keeps you within all limits. Alternatively, you could sell a $185 put for $3.20 premium — if assigned, you'd get a 7% discount to current price."

---

### Step 5: Execute

**Purpose:** Place the trade to add the stock to the portfolio.

**Tools:**
- `preview_trade(ticker, quantity, side="BUY", order_type="Market"|"Limit")` → `execute_trade(preview_id)` — standard equity execution
- `analyze_option_strategy(legs=[...])` → `preview_trade()` — for options entry strategies

**Inputs:** Position size from Step 4

**Outputs:**
```
trade_execution:
  order:
    ticker: "AAPL"
    side: "BUY"
    quantity: 64
    order_type: "Limit"
    limit_price: $196.00
    estimated_cost: $12,544

  execution_result:
    status: "filled"
    fill_price: $195.85
    fill_quantity: 64
    total_cost: $12,534.40
    slippage: -$9.60 (0.08%)

  post_execution:
    new_weight: 2.5%
    new_tech_weight: 41.0%
    portfolio_volatility: 22.8% (+0.3pp)
    compliance: PASS
```

**Confirmation gate:** Standard — preview shows all order details, user approves before execution.

**UI:** Trade ticket: order type selector (Market/Limit), quantity, estimated cost. Preview shows fill estimate. "Execute" with confirmation. Post-execution: updated portfolio view with new position highlighted.

**Agent:** "Buying 64 shares of AAPL at limit $196.00 ($12,544 estimated). This brings your AAPL weight to 2.5%. Proceed?"

---

### Workflow Summary

```
Step 1: Find & Profile
  Tools: fmp_search, fmp_profile
  Output: Company profile, sector, valuation, description
  Gap: Frontend search is mocked (backend works)

Step 2: Analyze
  Tools: analyze_stock, get_technical_analysis, compare_peers, get_estimate_revisions, get_news, analyze_option_chain
  Output: Comprehensive research across 6 dimensions
  Gap: No auto-fetch orchestration (must call each tool separately)

Step 3: Evaluate Portfolio Fit
  Tools: get_risk_analysis, get_factor_analysis, run_whatif
  Output: Overlap analysis, diversification score, trial allocation impact
  Gap: None (tools exist and compose well)

Step 4: Size Position
  Tools: run_whatif (multiple sizes), get_leverage_capacity, analyze_option_strategy
  Output: Recommended allocation, sizing scenarios, options alternative
  Gap: No automated risk-budget sizing tool

Step 5: Execute
  Tools: preview_trade/execute_trade
  Output: Fill confirmation + updated portfolio
  Gap: No "buy" button in frontend stock lookup view
```

### Gaps Summary

| Gap | Impact | Workaround | Shared? |
|-----|--------|------------|---------|
| Frontend search mocked | Can't search stocks from UI | Agent uses `fmp_search` directly | Stock-specific |
| No auto-fetch orchestration | Must call 6 tools separately for full research | Agent runs in parallel | Stock-specific |
| No risk-budget sizing | Can't auto-compute "target X% of risk" allocation | Run whatif at multiple weights, pick best | Stock-specific |
| No "buy" button in UI | Can't execute from stock lookup view | Agent calls `preview_trade` | Stock-specific |
| No watchlist / save for later | Can't bookmark stocks for future research | Conversation context only | Stock-specific |
| Fundamental data fragmented | Profile + peers + estimates are separate calls | Agent aggregates | Stock-specific |

---

## Workflow 7: Strategy Design

### Overview

The strategy design workflow takes a user from "I want to build/improve my portfolio allocation" to "I've deployed an optimized strategy with validated constraints." It's the most construction-oriented workflow — where the other workflows analyze what exists, this one builds what should exist.

The workflow has two entry points: **build from scratch** (define objectives → optimize → validate → deploy) and **improve existing** (current portfolio → identify inefficiencies → optimize → compare → deploy). Both converge at the optimization step.

This workflow has the largest gap inventory of any workflow. The optimization engine (min_variance/max_return QP solver) is production-ready, but the surrounding infrastructure — backtesting, strategy persistence, sensitivity analysis, efficient frontier — doesn't exist yet. The workflow is still valuable today via the tools that do exist, with the gaps clearly marked for future implementation.

### Step 1: Set Objectives & Constraints

**Purpose:** Define what the strategy should achieve (objective) and what limits it must respect (constraints). This configures the optimization engine before running it.

**Tools:**
- `get_risk_profile(format="agent")` — retrieve current constraint set to use as starting point
- `set_risk_profile(template="growth"|"income"|"trading"|"balanced", ...)` — apply a template or custom constraints
- `get_risk_analysis(format="agent")` — current portfolio baseline for "improve existing" entry point
- `get_factor_analysis(analysis_type="performance")` — factor Sharpe ratios to inform which factor exposures to target

**Templates available:**

| Template | Vol Target | Max Loss | Single Stock | Factor Contrib | Industry Contrib |
|----------|-----------|----------|--------------|----------------|------------------|
| Income | 20% | 25% | 45% | 85% | 50% |
| Growth | 18% | 20% | 25% | 80% | 35% |
| Trading | 15% | 15% | 15% | 85% | 40% |
| Balanced | 18% | 20% | 25% | 70% | 35% |

**Inputs:**
```
strategy_config:
  entry_point: "build_new" | "improve_existing"
  objective: "min_variance" | "max_return"

  # Option 1: Use template
  template: "growth"
  overrides: {max_single_stock_weight: 0.20, max_volatility: 0.16}

  # Option 2: Full custom
  constraints:
    max_volatility: 0.16
    max_loss: 0.20
    max_single_stock_weight: 0.20
    max_factor_contribution: 0.75
    max_market_contribution: 0.50
    max_industry_contribution: 0.30
    max_single_factor_loss: -0.10

  # For max_return objective — expected returns per ticker
  expected_returns: {AAPL: 0.12, MSFT: 0.15, ...}  # From DB or manual
```

**Outputs:**
```
strategy_setup:
  profile_name: "STRATEGY_DRAFT_1"
  objective: "min_variance"
  template: "growth" (with overrides)
  active_constraints:
    max_volatility: 16% (overridden from 18%)
    max_loss: 20%
    max_single_stock: 20% (overridden from 25%)
    max_factor_contribution: 75%
    max_market_contribution: 50%
    max_industry_contribution: 30%
  baseline:  # Current portfolio if "improve_existing"
    volatility: 22.5%
    sharpe: 0.64
    herfindahl: 0.082
```

**Gap: No constraint sensitivity analysis.** Can't answer "what if I relax vol target to 20%?" without running a full re-optimization. Future: `sensitivity_analysis(constraint, range)` → shows how the optimal allocation shifts as a constraint changes. Also no efficient frontier visualization.

**UI:** Constraint configuration panel. Template selector with override sliders. Side panel showing current portfolio metrics for comparison. "Optimize" button to proceed.

**Agent:** For "improve existing": reads current risk profile and portfolio state, identifies which constraints are binding ("your volatility is 22.5% against an 18% cap — the optimizer will need to make significant changes"). For "build new": suggests template based on stated goals ("income-focused investing → start with Income template").

---

### Step 2: Optimize

**Purpose:** Run the optimization engine to find the best allocation within the configured constraints.

**Tools:**
- `run_optimization(optimization_type="min_variance"|"max_return", portfolio_name=..., format="agent")` — QP solver finds optimal weights. Returns: optimized_weights, weight_changes (top changes with bps), compliance tables (risk/beta/proxy pass/fail), verdict ("no changes"/"minor rebalance"/"moderate rebalance"/"major rebalance"/"has violations").

**Inputs:** Strategy configuration from Step 1

**Outputs:**
```
optimization_result:
  verdict: "moderate rebalance"
  trades_required: 8

  optimized_weights:
    AAPL: 12.0% (was 18.2%, -620bps)
    MSFT: 10.0% (was 14.5%, -450bps)
    BND: 15.0% (was 10.1%, +490bps)
    SGOV: 10.0% (was 8.0%, +200bps)
    VTV: 8.0% (was 0%, +800bps — new position)
    ... (15 positions total)

  top_weight_changes:
    - {ticker: "AAPL", original: 18.2%, new: 12.0%, change_bps: -620}
    - {ticker: "VTV", original: 0%, new: 8.0%, change_bps: +800}
    - {ticker: "BND", original: 10.1%, new: 15.0%, change_bps: +490}

  compliance:
    risk_passes: 4/4
    beta_passes: 5/5
    proxy_passes: 3/3
    all_pass: true

  metrics:
    portfolio_volatility: 15.8% (within 16% cap)
    herfindahl: 0.058 (well diversified)
    largest_weight: 12.0% (AAPL, within 20% cap)

  flags:
    - {severity: "success", type: "clean_rebalance", message: "All constraints pass, 8 trades needed"}
    - {severity: "info", type: "large_single_change", message: "VTV added at 8.0% (new position)"}
```

**If optimization fails (infeasible constraints):**
```
optimization_result:
  verdict: "has violations"
  compliance:
    risk_passes: 3/4 (volatility still above cap with any feasible allocation)
    beta_passes: 4/5 (growth beta can't be reduced enough)
  flags:
    - {severity: "warning", type: "risk_violations", message: "Cannot satisfy volatility cap with current universe"}
  suggestion: "Relax max_volatility to 18% or add low-vol positions to the universe"
```

**UI:** Optimization result dashboard. Weight change waterfall chart (before → after per position). Compliance status table (all green checks or red failures). If infeasible: warning banner with suggestion to relax constraints. "Compare Variant" button to run alternative optimization.

**Agent:** Presents result: "Min-variance optimization found a solution with 15.8% vol (within 16% cap). Major changes: trim AAPL/MSFT, add BND/VTV. 8 trades needed. All constraints pass." If infeasible: "Can't meet the 16% vol cap with current positions. Two options: relax to 18%, or add low-vol ETFs like SGOV/BND to the universe."

---

### Step 3: Compare Variants

**Purpose:** Run multiple optimization variants (different objectives, constraints, or templates) and compare side-by-side to find the best strategy.

**Tools:**
- `run_optimization()` — run per variant (different objective, constraints)
- `run_whatif(target_weights={optimized_weights})` — validate each variant's risk impact
- `set_risk_profile()` — configure different constraint sets for each variant

**Inputs:** Multiple strategy configurations (typically 2-4 variants)

**Variant examples:**
```
variant_A: min_variance + growth template (default)
variant_B: min_variance + balanced template (tighter constraints)
variant_C: max_return + growth template (risk-seeking)
variant_D: min_variance + custom (relaxed vol target)
```

**Outputs:**
```
variant_comparison:
  baseline:
    volatility: 22.5%, sharpe: 0.64, herfindahl: 0.082, trades: 0

  variants:
    - name: "MinVar Growth"
      volatility: 15.8%, sharpe: 0.72, herfindahl: 0.058, trades: 8
      compliance: PASS, verdict: "moderate rebalance"

    - name: "MinVar Balanced"
      volatility: 14.2%, sharpe: 0.68, herfindahl: 0.052, trades: 12
      compliance: PASS, verdict: "major rebalance"

    - name: "MaxReturn Growth"
      volatility: 17.5%, sharpe: 0.85, herfindahl: 0.071, trades: 10
      compliance: PASS, verdict: "moderate rebalance"

    - name: "MinVar Relaxed"
      volatility: 17.8%, sharpe: 0.74, herfindahl: 0.065, trades: 5
      compliance: PASS, verdict: "minor rebalance"

  ranking:
    by_sharpe: [MaxReturn Growth, MinVar Relaxed, MinVar Growth, MinVar Balanced]
    by_risk: [MinVar Balanced, MinVar Growth, MaxReturn Growth, MinVar Relaxed]
    by_trade_count: [MinVar Relaxed, MinVar Growth, MaxReturn Growth, MinVar Balanced]
```

**Gap: No batch optimization.** Must run `set_risk_profile` + `run_optimization` per variant and compare manually. Future: `compare_strategies(variants=[...])` that runs all in parallel and returns ranked comparison.

**Gap: No backtesting.** Can't validate "would this strategy have worked historically?" No walk-forward simulation, no out-of-sample testing. Workaround: use `get_performance(mode="hypothetical")` on the optimized weights as a rough proxy, but this has survivorship bias (current universe only).

**Gap: No efficient frontier.** Can't visualize all optimal portfolios across the risk/return spectrum. Would require running optimization at many vol targets and plotting the curve.

**Decision point:** User/agent selects preferred variant. May iterate by adjusting constraints and re-running.

**UI:** Comparison table — rows are variants, columns are key metrics. Radar chart overlay. Trade count column (fewer trades = easier to implement). "Select" button on preferred variant. "New Variant" button to add more.

**Agent:** Ranks by stated objective. "If you want maximum Sharpe, MaxReturn Growth wins at 0.85 but requires 10 trades. If you want minimum disruption, MinVar Relaxed needs only 5 trades with a solid 0.74 Sharpe. Recommendation: MinVar Relaxed offers the best tradeoff of improvement vs. implementation cost."

---

### Step 4: Validate & Save

**Purpose:** Final validation of the chosen strategy — confirm compliance, review all weight changes, optionally save for future reference.

**Tools:**
- `run_whatif(target_weights={optimized_weights}, format="agent")` — full before/after risk comparison with compliance checks, position changes, factor beta shifts
- `create_basket(name="strategy_name", tickers=..., weights=...)` — save optimized weights as a named basket for future reference and execution
- `analyze_basket(name="strategy_name", benchmark_ticker="SPY")` — validate basket risk/return profile

**Inputs:** Selected variant from Step 3

**Outputs:**
```
strategy_validation:
  name: "MinVar Relaxed — March 2026"
  before_after:
    volatility: 22.5% → 17.8% (-4.7pp, -21%)
    sharpe: 0.64 → 0.74 (+0.10, +16%)
    market_beta: 1.05 → 0.92 (-0.13)
    herfindahl: 0.082 → 0.065 (-21%)
    factor_variance: 78% → 68% (-10pp)
    compliance_violations: 3 → 0

  position_changes:
    new_positions: [{ticker: "VTV", weight: 5.0%}, {ticker: "SCHD", weight: 3.0%}]
    removed_positions: []
    increased: [{ticker: "BND", from: 10.1%, to: 15.0%}]
    decreased: [{ticker: "AAPL", from: 18.2%, to: 14.0%}, {ticker: "MSFT", from: 14.5%, to: 11.0%}]

  saved_as:
    basket_name: "strategy_minvar_relaxed_202603"
    positions: 15
    reusable: true  # Can be loaded via analyze_basket or preview_basket_trade

  compliance: ALL PASS
```

**Gap: No strategy versioning.** Saving to a basket works but there's no version history, no diff between strategy iterations, no audit trail of constraint changes. Future: strategy version table with timestamps, constraint snapshots, and optimization results per version.

**UI:** Final review panel. Before/after side-by-side. Position change table. "Save Strategy" button (creates basket). "Deploy" button proceeds to execution.

**Agent:** "Strategy validated — all constraints pass. Key improvements: volatility down 21%, Sharpe up 16%, all violations resolved. Saved as basket 'strategy_minvar_relaxed_202603'. Ready to execute?"

---

### Step 5: Execute

**Purpose:** Deploy the strategy by executing the required trades.

**Tools:**
- `preview_basket_trade(name="strategy_name", action="rebalance", total_value=...)` → `execute_basket_trade(preview_ids)` — multi-leg execution from saved basket
- `preview_trade()` → `execute_trade()` — individual legs if basket trade isn't suitable
- **Gap: No rebalance trade generator** (shared). Basket trade handles multi-leg, but the weight-to-shares math is approximate. Future: precise share calculation with rounding, odd-lot handling, and cash residual management.
- **Gap: No transaction cost modeling.** Optimization assumes zero-cost execution. Future: include estimated commissions/spreads in the optimization objective or as a post-optimization adjustment.

**Inputs:** Saved strategy basket from Step 4

**Outputs:**
```
execution_plan:
  basket: "strategy_minvar_relaxed_202603"
  sequence:
    sells_first:
      1. SELL AAPL × 21 (trim -4.2%) → ~$19,100
      2. SELL MSFT × 9 (trim -3.5%) → ~$3,645
    then_buys:
      3. BUY BND × 35 (+4.9%) → ~$2,485
      4. BUY VTV × 37 (+5.0%) → ~$5,217
      5. BUY SCHD × 28 (+3.0%) → ~$2,212
  total_trades: 5
  total_sells: $22,745
  total_buys: $9,914
  net_cash: +$12,831

execution_result:
  fills: [{ticker, side, qty, fill_price, status}, ...]
  total_slippage: -$38 (0.2%)

post_deployment:
  new_volatility: 17.9% (target was 17.8% — within tolerance)
  new_sharpe: ~0.73 (estimated)
  compliance: ALL PASS
  next_rebalance: "Review in 30 days or when drift > 5pp"
```

**Confirmation gate:** Explicit approval before execution. Preview all trades with costs.

**UI:** Trade queue (sells first, then buys). Cost summary. "Execute" with confirmation. Post-deployment: updated portfolio dashboard + strategy performance tracking card. Suggested rebalance date.

**Agent:** Presents trade plan. After execution, runs `get_risk_analysis()` to verify deployed portfolio matches optimization target. Suggests review cadence.

---

### Workflow Summary

```
Step 1: Set Objectives & Constraints
  Tools: get_risk_profile, set_risk_profile, get_risk_analysis, get_factor_analysis
  Output: Strategy configuration with constraints
  Gap: No constraint sensitivity analysis, no efficient frontier

Step 2: Optimize
  Tools: run_optimization
  Output: Optimized weights, compliance validation, verdict
  Gap: None (QP solver works well)

Step 3: Compare Variants
  Tools: run_optimization (×N), run_whatif, set_risk_profile
  Output: Ranked variant comparison
  Gaps: No batch optimization, no backtesting, no efficient frontier

Step 4: Validate & Save
  Tools: run_whatif, create_basket, analyze_basket
  Output: Final validation + saved strategy
  Gap: No strategy versioning

Step 5: Execute
  Tools: preview_basket_trade/execute_basket_trade, preview_trade/execute_trade
  Output: Fill confirmations + post-deployment verification
  Gaps: Rebalance trade generator (shared), no transaction cost modeling
```

### Gaps Summary

| Gap | Impact | Workaround | Shared? |
|-----|--------|------------|---------|
| Backtesting engine | Can't validate strategy on historical data | Use hypothetical performance as rough proxy (survivorship bias) | Strategy-specific |
| Efficient frontier | Can't visualize risk/return tradeoff curve | Run optimization at multiple vol targets manually | Strategy-specific |
| Constraint sensitivity | Can't see how relaxing one constraint changes output | Re-run optimization with adjusted constraint | Strategy-specific |
| Strategy versioning | No history of strategy iterations | Save as differently-named baskets | Strategy-specific |
| Batch optimization | Must run variants one at a time | Agent loops over configurations | Shared with Scenarios |
| Transaction cost modeling | Optimization assumes zero-cost execution | Post-hoc cost estimation from trade preview | Strategy-specific |
| Multi-objective optimization | Only min_variance or max_return, not both | Run both and compare | Strategy-specific |
| Rebalance scheduling | No automated periodic rebalance trigger | Manual re-run or agent reminder | Shared (Allocation) |
| Rebalance trade generator | Approximate weight-to-shares conversion | Basket trade handles multi-leg | Shared (all workflows) |

---

## Implementation Approach

### Phase 1: Define Workflows (this doc)
For each of the 7 workflows, define: steps, inputs/outputs, existing tools used, new capabilities needed. This is the contract that UI and agents will share.

### Phase 2: Backend Workflow Layer
Decide how workflows live on the backend:
- **Option A: Orchestrator functions** — Python functions that chain existing tools (lightweight, composable)
- **Option B: Workflow engine** — State machine with step tracking, persistence, resumability (heavier, more powerful)
- **Option C: Agent-driven** — Claude chains tools via MCP; no new backend code needed, but less reusable for UI

Likely: Start with Option A (orchestrator functions) for the most common workflows, evolve to B for complex ones.

### Phase 3: UI Second Pass
For each view, update the frontend to step through the workflow (not just display data). This means:
- Multi-step UI patterns (wizard, progressive disclosure)
- Action buttons at each step (not just "view results")
- Cross-view navigation (risk → hedging → execution)

### Phase 4: Agent Integration
Expose workflows as composable MCP tools that Claude can drive. The same workflow definition that powers the UI becomes a tool the agent can call with structured inputs and get structured outputs.

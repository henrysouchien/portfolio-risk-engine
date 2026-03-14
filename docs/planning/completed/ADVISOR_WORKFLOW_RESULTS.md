# Advisor Workflow Experiment — Results

> **Date**: 2026-03-12
> **Method**: 10 live agent runs against real portfolio data using full MCP tool suite
> **Questions**: Sampled across all 8 categories from the 33-question bank

---

## Tool Chain Data (10 Runs)

### Raw Tool Chains

| Q# | Category | Tools Called (in order) | Total Calls | Entry Point |
|----|----------|----------------------|-------------|-------------|
| Q1 | morning_checkin | `get_positions` → `get_risk_score` → `get_performance` → `get_portfolio_news`(stock) → `get_portfolio_events_calendar`(earn) → `get_portfolio_events_calendar`(div) → `monitor_hedge_positions` → `get_portfolio_news`(general) → `analyze_stock`(IT) → `analyze_stock`(FIG) → `check_exit_signals`(IT,FIG,SLV) → `get_risk_analysis` | **15** | `get_positions` |
| Q5 | risk_review | `get_positions` → `get_risk_analysis` → `get_factor_analysis`(corr) → `get_risk_score` → `get_factor_analysis`(perf) → `get_factor_recommendations` | **7** | `get_positions` |
| Q7 | risk_review (stress) | `get_positions` → `get_risk_analysis` → `get_risk_score` → `get_factor_analysis` → `get_leverage_capacity` → `get_performance` → `run_backtest` → `compare_scenarios` → `run_whatif`(×2) | **10** | `get_positions` |
| Q10 | performance | `get_performance`(×3 attempts) → `get_positions`(×2) → `get_risk_analysis` → `get_quote`(SPY) | **8** | `get_performance` |
| Q14 | research | `get_positions` → `analyze_stock`(NVDA) → `get_risk_analysis` → `run_whatif` → `get_quote` → `fmp:get_technical_analysis` → `fmp:get_news` → `get_factor_analysis` → `get_risk_score` → `fmp:get_estimate_revisions` | **10** | `get_positions` |
| Q16 | research (compare) | `get_positions` → `analyze_stock`(×3) → `get_risk_analysis` → `fmp:get_market_context` → `run_whatif`(×3) → `get_performance` → `get_factor_analysis` → `fmp:fmp_profile`(×3) → `fmp:get_estimate_revisions`(×3) | **17** | `get_positions` |
| Q18 | planning (what-if) | `get_positions` → `get_risk_analysis` → `get_risk_score` → `run_whatif` → `compare_scenarios`(3 scenarios) | **5** | `get_positions` |
| Q20 | planning (rebalance) | `get_positions`(×2) → `get_target_allocation` → `get_risk_analysis` → `get_risk_score` → `generate_rebalance_trades`(failed) | **8** | `get_positions` + `get_target_allocation` |
| Q23 | tax | `get_positions` → `suggest_tax_loss_harvest`(×2) → `get_performance`(failed) → `list_transactions`(×2) | **12** | `get_positions` + `suggest_tax_loss_harvest` |
| Q30 | research (thematic) | `get_positions` → `get_risk_analysis` → `get_factor_analysis` → `analyze_stock`(×2) → `get_risk_score` → `fmp:fmp_profile`(×5) → `run_whatif` | **13** | `get_positions` |

---

## Analysis 1: Tool Frequency Distribution

How often each tool appears across 10 questions (unique tools per question, not call count):

| Tool | Questions Used | Frequency | Nav Section |
|------|---------------|-----------|-------------|
| **`get_positions`** | 10/10 | **100%** | Dashboard |
| **`get_risk_analysis`** | 8/10 | **80%** | Dashboard |
| **`get_risk_score`** | 7/10 | **70%** | Dashboard |
| **`get_performance`** | 4/10 | 40% | Performance |
| **`get_factor_analysis`** | 5/10 | 50% | Research |
| **`run_whatif`** | 5/10 | 50% | Plan |
| **`analyze_stock`** | 4/10 | 40% | Research |
| **`get_portfolio_news`** | 1/10 | 10% | Dashboard |
| **`get_portfolio_events_calendar`** | 1/10 | 10% | Dashboard |
| **`monitor_hedge_positions`** | 1/10 | 10% | Dashboard |
| **`check_exit_signals`** | 1/10 | 10% | Dashboard |
| **`get_risk_profile`** | 2/10 | 20% | Dashboard |
| **`get_target_allocation`** | 2/10 | 20% | Dashboard |
| **`compare_scenarios`** | 2/10 | 20% | Plan |
| **`run_backtest`** | 1/10 | 10% | Plan |
| **`get_leverage_capacity`** | 1/10 | 10% | Dashboard |
| **`suggest_tax_loss_harvest`** | 1/10 | 10% | Plan |
| **`generate_rebalance_trades`** | 1/10 | 10% | Plan |
| **`list_transactions`** | 1/10 | 10% | Dashboard |
| **`get_quote`** | 2/10 | 20% | Dashboard |
| **`get_factor_recommendations`** | 1/10 | 10% | Research |
| `fmp:get_technical_analysis` | 1/10 | 10% | Research (cross-MCP) |
| `fmp:get_news` | 1/10 | 10% | Dashboard (cross-MCP) |
| `fmp:fmp_profile` | 2/10 | 20% | Research (cross-MCP) |
| `fmp:get_market_context` | 1/10 | 10% | Dashboard (cross-MCP) |
| `fmp:get_estimate_revisions` | 2/10 | 20% | Research (cross-MCP) |

### Tier 1 — Universal (>60% frequency)
These tools are the "always on" layer — the agent reaches for them regardless of question type:
1. **`get_positions`** (100%) — the universal entry point
2. **`get_risk_analysis`** (80%) — the universal context enricher
3. **`get_risk_score`** (70%) — the compliance checkpoint

### Tier 2 — Workflow-Specific (30-60%)
These appear when the question enters a specific domain:
4. **`get_factor_analysis`** (50%) — risk review, research, thematic
5. **`run_whatif`** (50%) — any forward-looking question
6. **`get_performance`** (40%) — benchmarking, evaluation
7. **`analyze_stock`** (40%) — any single-stock question

### Tier 3 — Specialized (<30%)
Deep tools for specific workflows:
- Tax: `suggest_tax_loss_harvest`, `list_transactions`
- Rebalance: `get_target_allocation`, `generate_rebalance_trades`
- Stress: `run_backtest`, `get_leverage_capacity`, `compare_scenarios`
- Monitoring: `get_portfolio_news`, `get_portfolio_events_calendar`, `monitor_hedge_positions`, `check_exit_signals`

---

## Analysis 2: Entry Points by Category

| Category | First Tool(s) Called | Pattern |
|----------|---------------------|---------|
| Morning check-in | `get_positions` (parallel with risk_score, performance, news, calendar) | Wide fan-out |
| Risk review | `get_positions` + `get_risk_analysis` (parallel) | Risk-focused pair |
| Performance | `get_performance` (standalone first) | Domain-specific entry |
| Research | `get_positions` + `analyze_stock` (parallel) | Position context + stock deep-dive |
| Planning | `get_positions` + `get_target_allocation` or `get_risk_analysis` | Context + target |
| Tax | `get_positions` + `suggest_tax_loss_harvest` (parallel) | Domain-specific pair |

**Key insight**: `get_positions` is the universal entry point for 9/10 question types. The only exception is pure performance questions, which start with `get_performance`.

---

## Analysis 3: Co-occurrence Matrix (Unique Tool Pairs)

Tools that appear together in the same question (count out of 10):

| | positions | risk_analysis | risk_score | performance | factor_analysis | whatif | analyze_stock |
|---|---|---|---|---|---|---|---|
| **positions** | — | **8** | **7** | 4 | 5 | 5 | 4 |
| **risk_analysis** | 8 | — | **7** | 3 | 5 | 4 | 3 |
| **risk_score** | 7 | 7 | — | 2 | 4 | 4 | 2 |
| **performance** | 4 | 3 | 2 | — | 1 | 1 | 0 |
| **factor_analysis** | 5 | 5 | 4 | 1 | — | 3 | 3 |
| **whatif** | 5 | 4 | 4 | 1 | 3 | — | 2 |
| **analyze_stock** | 4 | 3 | 2 | 0 | 3 | 2 | — |

**Strongest clusters:**
1. `positions` + `risk_analysis` (8/10) — the foundation pair
2. `positions` + `risk_score` (7/10) — positions + compliance check
3. `risk_analysis` + `risk_score` (7/10) — the risk triangle
4. `positions` + `factor_analysis` (5/10) — position context + factor context
5. `positions` + `whatif` (5/10) — understand current → simulate change

---

## Analysis 4: Workflow Patterns (Tool Chain Shapes)

### Pattern A: "Assess & Report" (Q1, Q5, Q10)
```
get_positions ──┬── get_risk_analysis ──┬── get_risk_score
                ├── get_performance     │
                ├── get_portfolio_news  │
                └── get_events_calendar │
                                        └── [report]
```
Shape: Wide parallel fan → converge → synthesize. 5-15 tools.

### Pattern B: "Research & Evaluate" (Q14, Q16, Q30)
```
get_positions ── analyze_stock(s) ──┬── run_whatif
                                    ├── get_factor_analysis
                                    ├── fmp:technicals/profile
                                    └── get_risk_score
                                         └── [recommendation]
```
Shape: Start narrow → expand research → simulate → recommend. 10-13 tools.

### Pattern C: "Plan & Model" (Q7, Q18, Q20)
```
get_positions ── get_risk_analysis ── run_whatif / compare_scenarios / run_backtest
                                                └── [action plan]
```
Shape: Context → model → prescribe. 5-10 tools.

### Pattern D: "Specialized Domain" (Q23)
```
get_positions ── suggest_tax_loss_harvest ── list_transactions
                                              └── [harvest plan]
```
Shape: Context → domain tool → detail drill → prescribe. 5-12 tools.

---

## Analysis 5: Cross-MCP Usage

| MCP Server | Questions | Tools Used | Total Calls |
|------------|-----------|------------|-------------|
| **portfolio-mcp** | 10/10 (100%) | 21 distinct tools | ~90 |
| **fmp-mcp** | 3/10 (30%) | `get_technical_analysis`, `get_news`, `get_estimate_revisions`(×4), `fmp_profile`(×8), `get_market_context` | ~15 |
| ibkr-mcp | 0/10 | (portfolio-mcp abstracts over it) | 0 |
| edgar-financials | 0/10 | (not triggered by any question) | 0 |
| finance-cli | 0/10 | (personal finance, not investment analysis) | 0 |

**Insight**: `portfolio-mcp` is the dominant server (~85% of all tool calls). `fmp-mcp` is reached for only when the agent needs market-level data (technicals, earnings estimates, company profiles, market context) that portfolio-mcp doesn't provide. Q16 (stock comparison) was the heaviest cross-MCP user — 7 fmp-mcp calls for profiles + estimate revisions across 3 candidates. The other MCPs are not triggered by advisor-style questions.

---

## Analysis 6: Hypothesis Validation

| Question Type | Hypothesized Chain | Actual Chain | Match? |
|---|---|---|---|
| Morning check-in | positions → risk_score → news → calendar → hedge_monitor | positions → risk_score → performance → news(×2) → calendar(×2) → hedge_monitor → analyze_stock(×2) → exit_signals(×3) → risk_analysis | **Partial** — hypothesis missed the adaptive drill-down (flagged positions → deeper analysis) |
| Risk review | risk_analysis → factor_analysis → factor_recs | positions → risk_analysis → factor_analysis(×2) → risk_score → factor_recs | **Close** — hypothesis missed positions as entry point and risk_score as compliance check |
| Performance | performance → trading_analysis | performance(×3) → positions(×2) → risk_analysis → quote | **Partial** — trading_analysis not used; risk_analysis + quote used instead |
| Stock research (single) | analyze_stock → quote → positions | positions → analyze_stock → risk_analysis → whatif → quote → fmp:technicals → fmp:news → factor_analysis → risk_score → fmp:estimates | **Partial** — hypothesis was too simple; actual chain includes whatif simulation and cross-MCP research |
| Stock research (compare) | (not hypothesized) | positions → analyze_stock(×3) → risk_analysis → whatif(×3) → performance → factor_analysis → fmp:profile(×3) → fmp:estimates(×3) → fmp:market_context | **17 calls** — heaviest workflow; comparison multiplies per-stock tools 3× plus adds valuation layer |
| What-if planning | positions → whatif → compare → rebalance | positions → risk_analysis → risk_score → whatif → compare_scenarios | **Close** — correct core chain; rebalance not reached in what-if (only in rebalance question) |
| Tax optimization | tax_harvest → trading_analysis | positions → tax_harvest(×2) → list_transactions(×2) | **Partial** — trading_analysis not used; list_transactions used for realized gain context |

**Key finding**: Hypotheses underestimated (a) the role of `get_positions` as universal entry point, (b) the adaptive drill-down pattern where flags trigger deeper investigation, and (c) the heavy use of `run_whatif` across question types.

---

## Analysis 7: Implications for Frontend Toolbox Design

### 1. Dashboard Must Show the "Foundation Three"
`get_positions`, `get_risk_analysis`, and `get_risk_score` are called in 70-100% of workflows. The Dashboard view should surface these as persistent, always-visible data — not behind clicks.

### 2. "What-If" Is a Universal Action, Not a Separate View
`run_whatif` appears in 50% of questions across research, planning, and risk categories. It should be accessible from any context (e.g., "what if I change this?" from any position or allocation view), not siloed in a Scenarios tab.

### 3. Research Workflows Are the Deepest
Stock research questions generate the most tool calls (10-13) and the most cross-MCP usage. The Research view needs to accommodate multi-step flows: stock profile → portfolio fit → factor context → scenario → recommendation.

### 4. Morning Briefing Is the Widest Workflow
Q1 touched 8 distinct tool types across all nav sections. This suggests the Overview/Dashboard should be a briefing surface that aggregates alerts from positions, risk, news, calendar, and hedge monitor.

### 5. Specialized Tools Need Entry Points, Not Tabs
Tax harvesting, rebalancing, and hedge monitoring each appeared in only 1 question but were critical when needed. These should be discoverable via alerts or AI suggestions rather than permanent nav items.

### 6. Adaptive Drill-Down Is the Agent's Natural Pattern
The agent doesn't follow a linear workflow. It fans out → reads flags → drills into flagged items. The frontend should mirror this: show summary cards with flags → click flag → detail view with relevant tools pre-loaded.

### 7. `get_performance` vs `get_trading_analysis` Surprise
`get_trading_analysis` was never called despite hypothesis. `get_performance` was used instead. Either (a) the agent doesn't know about trading_analysis, or (b) performance covers the common case and trading_analysis is a power-user tool. Frontend implication: Performance view is primary; Trading Analysis is a deeper tab.

---

## Nav Section Tool Mapping (Updated from Experiment)

| Nav Section | Primary Tools (>30%) | Secondary Tools (<30%) | Cross-MCP |
|-------------|---------------------|----------------------|-----------|
| **Dashboard** | `get_positions`, `get_risk_analysis`, `get_risk_score` | `get_portfolio_news`, `get_portfolio_events_calendar`, `monitor_hedge_positions`, `check_exit_signals`, `get_leverage_capacity`, `get_quote`, `list_transactions` | `fmp:get_news`, `fmp:get_market_context` |
| **Performance** | `get_performance` | `get_trading_analysis` | — |
| **Research** | `analyze_stock`, `get_factor_analysis` | `get_factor_recommendations` | `fmp:get_technical_analysis`, `fmp:get_estimate_revisions`, `fmp:fmp_profile` |
| **Plan** | `run_whatif`, `compare_scenarios` | `run_backtest`, `get_target_allocation`, `generate_rebalance_trades`, `suggest_tax_loss_harvest`, `run_optimization`, `get_efficient_frontier` | — |
| **Trade** | (not tested — execution questions not in this batch) | `preview_trade`, `execute_trade`, basket tools | — |

---

## Remaining Questions to Run

Still need to cover: Q2-4 (more morning), Q6/8/9 (more risk), Q11-13 (more performance), Q15/17 (more research), Q19/21-22 (more planning), Q24-25 (more tax), Q26-29 (execution), Q31-33 (hot topics).

Priority for next batch: **Execution questions (Q26-29)** to test the Trade nav section, and **Q13 (trading quality)** to see if `get_trading_analysis` appears.

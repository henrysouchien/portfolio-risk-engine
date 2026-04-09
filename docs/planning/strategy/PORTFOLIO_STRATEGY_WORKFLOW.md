# Portfolio Strategy Workflow — Dogfooding the System

> **Purpose**: Bridge between investment ideas and the tools we built. Maps each phase of the investment process to concrete system capabilities across risk_module, investment_tools, AI Excel addin, and agent skills.
>
> **Strategy source**: `~/Desktop/investment-workspace/portfolio-strategy-plan.md`
>
> **Status**: TODO — start after design system work stabilizes.

---

## The Full Loop

Idea sourcing → Research → Modeling → Risk sizing → Execution → Monitoring

Every layer of the system gets exercised. This is the first real user engagement test.

---

## Active Ideas

### 1. Brazil Equities — Value + BRL Inflection

**Thesis**: Brazilian equities look cheap, possible economic/currency inflection point (BRL), likely underowned by institutions.

**Expression**: Single stocks + futures (Bovespa / EWZ)

| Phase | What to do | Tools |
|-------|-----------|-------|
| **Screen** | Quality Brazilian equities with value characteristics | `it-screener` (quality framework), `screen_stocks` via fmp-mcp (country=BR, valuation filters), `screen_estimate_revisions` (earnings momentum turning up?) |
| **Macro thesis** | BRL inflection, rates cycle, capital flows | `fred-mcp` (Brazil interest rates, USD/BRL), `macro-mcp` (EM positioning/flows), `get_economic_data` (GDP, inflation) |
| **Ownership/flows** | Confirm underowned thesis | `get_institutional_ownership` (per-ticker), `it-ownership` screener, `get_insider_trades` |
| **Deep research** | Per-ticker analysis on top 3-5 picks | Research workbench (create study, track findings), `analyze_stock` (risk profile, factor exposures, beta), `compare_peers`, `get_earnings_transcript` |
| **Model** | DCF / comps on best ideas | AI Excel addin → `model_summarize`, `model_values`, `model_scenario`, `model_sensitivity` |
| **Size & risk** | Portfolio impact, concentration check | `run_whatif` (add Brazil weights to current portfolio), `run_stress_test` (EM crisis scenario, custom BRL shock), `run_monte_carlo` (forward simulation with new weights), `get_risk_analysis` (factor/geo concentration) |
| **Futures overlay** | Leveraged macro expression | `manage_instrument_config` (Bovespa mini specs), `get_leverage_capacity` (headroom check), `preview_futures_roll` (contract roll planning) |
| **Execute** | Place trades | `preview_trade` / `execute_trade` (IBKR), `preview_basket_trade` (multi-leg entry) |
| **Monitor** | Ongoing position management | `check_exit_signals`, `get_portfolio_events_calendar`, `get_portfolio_news`, jobs-mcp (recurring quality screens on holdings) |

### 2. Japan Equities — Similar Opportunity Profile

**Thesis**: TBD — needs catalyst / inflection research.

**Expression**: Single stocks + Nikkei 225 futures

Same pipeline as Brazil, swap:
- Country filter → Japan
- Macro data → BOJ rates, USD/JPY, Nikkei
- Futures → Nikkei 225 mini

**Open questions**:
- [ ] What's the catalyst / inflection?
- [ ] Corporate governance reforms still playing out?
- [ ] Currency hedge or unhedged?

### 3. Macro Portfolio Construction Framework

**The overarching question**: How do futures leverage + concentrated stock positions combine into a coherent portfolio?

This is the methodology layer, not a specific trade. The system tools that enforce it:

| Concept | Tool |
|---------|------|
| Total portfolio volatility target | `run_optimization` (target_volatility mode) |
| Leverage headroom | `get_leverage_capacity` |
| Risk budget across positions | `get_risk_analysis` (contribution to risk), `get_factor_analysis` |
| Scenario stress limits | `run_stress_test` (max drawdown tolerance) |
| Position sizing rules | `run_whatif` (test size before committing) |
| Composite risk score | `get_risk_score` (0-100, compliance gate) |

**To define**:
- [ ] Max portfolio leverage ratio
- [ ] Per-position size limits (% of equity)
- [ ] Futures notional as % of total
- [ ] Drawdown tolerance / stop-loss framework
- [ ] Rebalance triggers

**Reference**: Video script on Google Drive re "$20K → $1M" plan (not located yet)

---

## How to Use the System

Expected usage patterns for the strategy work:

| Mode | When | Example |
|------|------|---------|
| **Claude Code + MCP tools** | Ad-hoc research, quick checks | "Screen Brazilian stocks with P/E < 10 and rising estimates" → `screen_stocks` + `screen_estimate_revisions` |
| **Frontend scenario tools** | Portfolio-level analysis, chained workflows | Stress test → Monte Carlo → Optimize chain via UI |
| **Research workbench** | Building thesis over time, tracking findings | Create study "Brazil Equities", log per-ticker findings, link to screen hits |
| **AI Excel addin** | Financial modeling | Build DCF for top picks, sensitivity analysis |
| **Claude Code + skills** | Heavy research sessions | `/browse` for filings, agent skills for multi-step analysis |
| **Jobs (investment_tools)** | Recurring monitoring | Schedule weekly quality screen on Brazil universe, earnings transcript parsing |

---

## What This Tests

Every layer of the platform:

- **investment_tools** — idea sourcing, screening, research tracking, jobs
- **risk_module scenario tools** — stress test, Monte Carlo, optimization, what-if, backtest
- **MCP tools** — stock analysis, factor analysis, hedge analysis, trading preview
- **Trading execution** — IBKR (futures + stocks), SnapTrade (Schwab)
- **AI Excel addin** — model building + scenario analysis
- **Agent skills** — browse, research, analysis workflows
- **Frontend** — scenario tool UI, chaining, design system in action

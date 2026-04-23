# Agent Surface Audit — Risk Module

**Date**: 2026-04-17
**Purpose**: Classify the 96 functions exposed to the agent via `agent/registry.py` + `risk_client` against the finance_cli spec for agent-composable primitives (self-documenting signatures, labeled return types, pure functions, composability).
**Goal**: Decide which functions can move into a sandbox-local math package vs. which must stay behind the HTTP boundary.

## Phase progress

| Phase | Scope | Status |
|---|---|---|
| **Phase 1** | Type-polish `risk_client` (typed sigs + curated TypedDicts) | ✅ **SHIPPED 2026-04-17** — see `RISK_CLIENT_TYPE_POLISH_PLAN.md` ship log |
| **Phase 2** | Extract pure-compute math kernels into sandbox-local `portfolio_math/` package | ✅ **SHIPPED 2026-04-17** — see `PORTFOLIO_MATH_EXTRACTION_PLAN.md` ship log. 11 MVP kernels. |
| **PM1A** | AI-excel-addin subprocess mount for `portfolio_math` | ✅ **SHIPPED 2026-04-19** — see `PORTFOLIO_MATH_SANDBOX_MOUNT_PLAN.md` ship log. Agent sandbox can now `import portfolio_math`. |
| **Phase 3B** | `building_blocks` delegate to `portfolio_math` directly (non-breaking) | ✅ **SHIPPED 2026-04-21** — see `BUILDING_BLOCKS_INTERNAL_DELEGATE_PLAN.md` ship log (`afe4fe93`). |
| **Phase 3C** | Monte Carlo kernel extraction | 🟡 **ACTIONABLE — capability-unlock candidate**. Codex R1 on Phase 2 flagged as "API redesign, not a move" (~5-7 days). Agent can call `rc.run_monte_carlo(...)` over HTTP today — one-shot HTTP works fine for the current one-call shape, so composition win is narrower than 3D. Worth extracting if/when agent needs to compose MC with custom drift models / scenario-conditioning locally. Schedule against priority, not workflow-demand gate. |
| **Phase 3D** | Option payoff + `OptionLeg`/`OptionStrategy` domain type extraction | ✅ **SHIPPED 2026-04-22 (end-to-end)** — (a) risk_module extraction per `PORTFOLIO_MATH_OPTIONS_PAYOFF_EXTRACTION_PLAN.md`: `portfolio_math` exports `OptionLeg`, `OptionStrategy`, and all 10 pure payoff functions at root (un-curated per `PORTFOLIO_MATH_OPTIONS_ROOT_EXPORT_FIX_PLAN.md`), matching Phase 2's pricing-primitive pattern, with legacy `options.*` paths preserved via shims. (b) AI-excel-addin cross-repo per `PORTFOLIO_MATH_OPTIONS_AI_EXCEL_ADDIN_PLAN.md`: subprocess smoke test + system prompt enumerates the full root surface for agent discovery. Agent sandbox can now `import portfolio_math as pm`, compose `pm.OptionStrategy`, and run full payoff analysis locally with zero HTTP round-trips. |
| **PM1B** | Docker-backend parity for `portfolio_math` (statsmodels + volume mount + image rebuild) | ⚪ **DEFERRED — PM1A subprocess is the live pattern**. Revisit if docker backend becomes the primary agent path. Tracked in `docs/TODO.md`. |

### Decision on remaining Phase 2 deferred scope (2026-04-21, revised same day)

**Superseded framing** (original 2026-04-21 decision): "deferred pending a concrete use case … revisit when a user-facing workflow actually needs it."

**Revised framing (2026-04-21)**: Do NOT gate agent-surface / code-execution capability work on "is there a concrete workflow that needs this?" — that's backwards. The agent can't develop new compositional workflows until the capability exists in the sandbox. Asking "what workflow needs this?" locks the agent into the shape its current surface already permits.

Instead, evaluate capability work on:
1. **Asymmetry**: is some of the capability already local while the rest is HTTP-only? (Options: YES — Black-Scholes local, strategy/payoff HTTP. MC: NO — the whole kernel is one HTTP call.)
2. **Composition value**: does the agent need to call this *repeatedly* with varying inputs, or compose its output with other local math? (Options payoff: YES, sweeps over price/vol/time. MC: one-shot, weaker case.)
3. **Scope cost**: how many days to extract cleanly, including Codex-flagged API redesign risk.

Under the revised framing: **Phase 3D is actionable** (clear asymmetry + composition win), **Phase 3C is actionable but lower-priority** (one-shot shape makes HTTP still reasonable; extraction unlocks only when composing MC with other local math becomes a pattern), **optimizer / PM1B** remain deferred (optimizer = cvxpy dep + API redesign; PM1B = docker infra work unrelated to capability).

---

## 1. Current state

**Surface exposed to agent sandbox**:
- `risk_client.RiskClient` (package at `risk_module/risk_client/`) — ~70 thin HTTP-wrapper methods
- All methods: `**kw: Any` → `dict[str, Any]`
- Dispatches to `POST /api/agent/call` on risk_module backend
- Backend routes via `agent/registry.py::AGENT_FUNCTIONS` to 96 registered callables

**Registry structure**:
- **10 "building_block" tier** (`agent/building_blocks.py`) — intended as composable primitives
- **86 "tool" tier** — one-per-MCP-tool wrappers registered so the agent can also call full tools from code

**How AI-excel-addin uses it**: Sandbox preamble `from risk_client import RiskClient as _RiskClient`; `RISK_CLIENT_PATH` env var on PYTHONPATH. No direct import of `agent.building_blocks` or `agent.registry`.

---

## 2. Spec gaps (finance_cli `SPEC_FINANCIAL_MATH_LIBRARY.md`)

| Spec principle | risk_client status | building_blocks status |
|---|---|---|
| Self-documenting signatures (no `Any`) | ❌ all `**kw: Any` | ⚠️ mixed — many use `tickers: Any`, `returns_dict: dict[str, Any]` |
| Labeled return types (dataclass/TypedDict) | ❌ `dict[str, Any]` | ❌ bare `dict[str, Any]` |
| Pure functions / no hidden state | ❌ network-bound, requires `RISK_API_URL` + `RISK_API_KEY` | ⚠️ most do portfolio load / factor enrichment / DB read |
| Composability over completeness | ⚠️ 70 tool methods, not primitives | ✅ 10 primitives + factor/stress/MC compute |
| Per-method docstrings with units | ❌ none on wrapper methods | ⚠️ terse, no units |

**Ironically, the tool-tier mcp_tools/ functions are better typed than the "primitive" building_blocks** — the MCP surface evolved signature discipline; the building_blocks did not.

---

## 3. Classification summary

### By purity

| Purity | Count | Examples |
|---|---|---|
| `pure_compute` (no I/O, deterministic) | 3 | `list_supported_brokerages`, `get_action_history`, core of `analyze_option_strategy` |
| `fmp_fetch` | 6 | `get_quote`, `get_price_series`, `fetch_fmp_data`, `analyze_stock`, `check_exit_signals`, `run_backtest` |
| `db_read` | ~20 | `list_transactions`, `list_baskets`, `list_portfolios`, `get_portfolio_weights`, `get_target_allocation`, research-read funcs |
| `db_write` | ~15 | `set_target_allocation`, `create_portfolio`, research-write funcs, `update_editorial_memory` |
| `brokerage_call` | ~10 | `preview_trade`, `execute_trade`, option/futures/basket execution, `list_connections` |
| `mixed` (multi-source compute) | ~40 | `run_optimization`, `run_whatif`, `run_monte_carlo`, `run_stress_test`, `get_risk_analysis`, `get_factor_analysis`, `compute_metrics`, `get_performance` |
| `llm_call` (LLM in path) | 2 | `prepopulate_diligence`, nested in `get_risk_score` (factor proxy gen) |

### By recommendation

| Recommendation | Count | Rationale |
|---|---|---|
| `extract_local_pure` | 3 | Genuinely pure — no cross-service deps |
| `needs_typing_only` | ~5 | HTTP-bound but core compute is pure given inputs; candidate for split |
| `stay_http_data` | ~55 | Needs backend data (DB/FMP/brokerage); typed wrapper is the ceiling |
| `stay_http_heavy` | ~33 | Heavy orchestration + state (portfolio load + risk enrichment + factor proxy + MC engine); untouchable as a unit |

**Bottom line**: 3 functions-as-they-stand can move into the sandbox local package. ~5 more have pure compute kernels that could be extracted if split. The other 88 are inherently HTTP-bound.

---

## 4. Key findings

### 4.1 The real extraction story is at the *sub*-function level

The registered functions are mostly orchestrators: load portfolio → enrich factor proxies → call compute engine → format output. The **compute engines** (`portfolio_risk_engine/`, `core/`, `portfolio_risk_engine.performance_metrics_engine.compute_performance_metrics`) are already pure — they just aren't what's registered in the agent surface.

The finance_cli-style math library should be carved out of these engines, not out of the registered tools. Current pure-ish kernels already in the codebase:

| Kernel | Location | Notes |
|---|---|---|
| `compute_performance_metrics` | `portfolio_risk_engine/performance_metrics_engine.py` | Returns dict; needs dataclass |
| Stress shock application | `portfolio_risk_engine/` stress modules | Pure given weights + shocks |
| MC simulation kernels | `portfolio_risk_engine/` MC modules | Pure given returns + params |
| Optimizer kernels | `portfolio_risk_engine/` optimization | CVXPY solves; deterministic |
| Black-Scholes / Black-76 | `core/options.py::OptionAnalyzer` | Pure math |
| Correlation / vol / Sharpe / drawdown | scattered in `portfolio_risk_engine/` | Pure NumPy/pandas |

### 4.2 `building_blocks` is the wrong typing boundary

The 10 building_blocks were added as "primitives for agent composition", but inspection shows they're thin wrappers that still do portfolio loading, factor proxy lookup, MC engine invocation, etc. They're not primitives — they're mini-orchestrators. Typing them is valuable; pretending they're pure is not.

Examples:
- `run_monte_carlo` — 500+ lines of branch logic on drift_model/distribution; loads portfolio state; calls MC engine. **Orchestrator, not primitive.**
- `run_stress_test` — three codepaths (custom / preset / all scenarios); portfolio load + factor proxy enrichment + GPT allowed. **Orchestrator, not primitive.**
- `compute_metrics` — fetches benchmark returns via provider then calls engine. **Pure compute kernel hidden behind one I/O call.**
- `get_correlation_matrix` — fetches returns then `df.corr()`. **Pure compute kernel behind one I/O call.**

### 4.3 Return-shape inconsistency

Three envelope conventions coexist:
1. **Agent envelope** `{status, format, snapshot, flags, file_path}` — 16 tools (per memory — verified: `get_positions`, `get_risk_analysis`, `run_optimization`, `run_whatif`, `run_backtest`, `analyze_stock`, etc.)
2. **Status + top-level fields** `{status, portfolio_name, metrics, ...}` — most of building_blocks
3. **Bare status + data** `{status, data}` or `{status, actions, summary}` — ad-hoc on some tools

This asymmetry is a drag on agent ergonomics: the agent can't rely on a single extraction pattern.

### 4.4 Param typing is generally good at the tool tier

Tool-tier MCP functions consistently use `Literal[...]` for enums, `Optional[...]` for nullable, explicit `int`/`float`/`str`. The building_blocks have weaker typing (`tickers: Any`, `returns_dict: dict[str, Any]`).

The `risk_client` shim **discards** this type info — every method is `**kw: Any`. This is the biggest single ergonomics loss between server and sandbox.

### 4.5 Orchestration patterns are repeated

Most tools follow: `resolve user → load portfolio (cached) → enrich factor proxies (may LLM) → call compute engine → format (summary/full/agent) → optional file I/O`. This is shared-boilerplate territory that would benefit from an explicit `PortfolioContext` dataclass that sandbox code could inspect — but inside the sandbox it doesn't help because the agent can't load portfolio state without HTTP.

---

## 5. Recommended target architecture

### Layer 1: `portfolio_math/` (NEW — sandbox-installable pure Python package)

**In-scope primitives** (pure functions, typed, dataclass returns, docstrings with units):

```
portfolio_math/
  stats.py       — compute_metrics, sharpe, sortino, max_drawdown, annualize
  returns.py     — from_prices, monthly_from_daily, align_series
  correlation.py — correlation_matrix, beta, tracking_error
  stress.py      — apply_factor_shocks (pure given betas + shocks + weights)
  monte_carlo.py — simulate_normal, simulate_student_t, simulate_bootstrap
                    (each takes covariance + drift + horizon, returns paths)
  optimize.py    — min_variance, max_sharpe, efficient_frontier
                    (pure CVXPY solves given returns + constraints)
  options.py     — bs_price, bs_greeks, black76_price
  types.py       — @dataclass returns: PerformanceMetrics, StressResult,
                    SimulationResult, OptimizationResult, OptionValuation
```

Each function: typed params, labeled dataclass return, no I/O, no DB, no FMP. `pip install portfolio_math`. Sandbox preamble imports both `RiskClient` (for data) and `portfolio_math` (for compute).

### Layer 2: `risk_client` — type-polished HTTP shim

Rewrite the 70 wrapper methods with real signatures and `TypedDict` return types that mirror each registered tool's response shape. Generated from a single source (either `agent/registry.py` inspection or per-tool type stubs). Agent gets IDE-level signature help inside the sandbox for data fetches.

### Layer 3: `agent/registry.py` + `mcp_tools/` + `actions/` — unchanged

Keep all 96 registered functions as-is. They are the orchestrators and are working.

---

## 6. What the agent does in the sandbox (target pattern)

```python
from risk_client import RiskClient
from portfolio_math import (
    compute_metrics, correlation_matrix, simulate_student_t,
    PerformanceMetrics, SimulationResult,
)

rc = RiskClient()

# Data: HTTP
positions = rc.get_positions()
returns   = rc.get_returns_series(tickers=[p.ticker for p in positions.positions])

# Compute: local, pure, typed
metrics: PerformanceMetrics = compute_metrics(
    returns.series, benchmark=returns.series["SPY"], risk_free=0.05,
)
corr = correlation_matrix(returns.series)
sim: SimulationResult = simulate_student_t(
    returns.covariance, drift=metrics.annual_return, horizon_days=252, n=1000, df=5,
)

# Result: labeled fields, no guessing
print(f"Sharpe={metrics.sharpe:.2f}, VaR(95%)=${sim.var_95:,.0f}")
```

Contrast today's pattern:

```python
rc = RiskClient()
resp = rc.run_monte_carlo(portfolio_name="CURRENT_PORTFOLIO", num_simulations=1000)  # dict[str, Any]
# Agent has to inspect resp["simulation"]["paths"]["p95"] etc. by trial
```

---

## 7. Scope proposal

### Phase 1 — Type-polish risk_client (1-2 weeks)
- Generate TypedDict/dataclass types from existing tool return shapes
- Replace `**kw: Any → dict[str, Any]` on all 70 methods with real signatures
- Agent gets sandbox affordance without a single architectural change
- **80% of the agent ergonomics win at minimal risk**

### Phase 2 — Extract pure math kernels to `portfolio_math/` (4-6 weeks)
- Carve out pure-compute kernels from `portfolio_risk_engine/` + `core/options.py`
- Package as `portfolio_math` with typed signatures + labeled dataclass returns
- Leave the compute engines in-repo too (risk_module still uses them internally)
- `portfolio_math` is a thin, documented extraction, not a fork
- Backend registered tools keep calling the originals; sandbox uses the extraction

### Phase 3 — Retire the `building_blocks` tier (1 week)
- Once `portfolio_math` ships, the 10 building_block functions are redundant (the agent can fetch data via `risk_client` and compute locally)
- Deprecate the tier; remove from registry
- Decision can be deferred until Phase 2 lands

### Explicit non-goals
- Don't try to extract the 33 `stay_http_heavy` orchestrators (MC runner, optimization runner, risk analysis). They depend on portfolio state + factor proxy DB + risk limits.
- Don't change the 96-function registry. That surface is stable and well-tested.

---

## 8. Appendix — Full function classification

Per-function detail (signature, return shape, deps, composition notes) was collected during audit across all 96 functions. The compact table below is the index. Pull detail for any row on demand.

### Quick reference table

| # | Function | File | Purity | Recommendation |
|---|---|---|---|---|
| **Building blocks (10)** | | | | |
| 1 | `get_price_series` | agent/building_blocks.py:242 | fmp_fetch | stay_http_data |
| 2 | `get_returns_series` | agent/building_blocks.py:298 | mixed | stay_http_data |
| 3 | `get_portfolio_weights` | agent/building_blocks.py:335 | db_read | stay_http_data |
| 4 | `get_correlation_matrix` | agent/building_blocks.py:350 | mixed | needs_typing_only (extract kernel) |
| 5 | `compute_metrics` | agent/building_blocks.py:382 | mixed | needs_typing_only (extract kernel) |
| 6 | `run_stress_test` | agent/building_blocks.py:420 | mixed | stay_http_heavy |
| 7 | `run_monte_carlo` | agent/building_blocks.py:484 | mixed | stay_http_heavy (extract MC kernel) |
| 8 | `get_factor_exposures` | agent/building_blocks.py:622 | mixed | stay_http_data |
| 9 | `fetch_fmp_data` | agent/building_blocks.py:665 | fmp_fetch | stay_http_data |
| 10 | `get_dividend_history` | agent/building_blocks.py:686 | db_read | stay_http_data |
| **Risk & Performance (9)** | | | | |
| 11 | `get_positions` | mcp_tools/positions.py:496 | mixed | stay_http_data |
| 12 | `export_holdings` | mcp_tools/positions.py:852 | mixed | stay_http_data |
| 13 | `get_risk_profile` | mcp_tools/risk.py:842 | db_read | stay_http_data |
| 14 | `set_risk_profile` | mcp_tools/risk.py:676 | db_write | stay_http_data |
| 15 | `get_risk_score` | agent/registry.py:667 | mixed (llm) | stay_http_heavy |
| 16 | `get_risk_analysis` | agent/registry.py:727 | mixed | stay_http_heavy |
| 17 | `get_leverage_capacity` | agent/registry.py:789 | mixed | stay_http_heavy |
| 18 | `get_performance` | mcp_tools/performance.py:451 | mixed | stay_http_data |
| 19 | `monitor_hedge_positions` | mcp_tools/hedge_monitor.py:548 | mixed (brokerage) | stay_http_data |
| **Scenarios & Optimization (6)** | | | | |
| 20 | `run_optimization` | mcp_tools/optimization.py:163 | mixed | stay_http_heavy (extract solver kernel) |
| 21 | `get_efficient_frontier` | mcp_tools/optimization.py:357 | mixed | stay_http_heavy (extract solver kernel) |
| 22 | `run_whatif` | mcp_tools/whatif.py:71 | mixed | stay_http_heavy |
| 23 | `run_backtest` | mcp_tools/backtest.py:115 | fmp_fetch | stay_http_data |
| 24 | `compare_scenarios` | mcp_tools/compare.py:176 | mixed | stay_http_heavy |
| 25 | `preview_rebalance_trades` | mcp_tools/rebalance.py:217 | mixed | stay_http_heavy |
| **Analysis (5)** | | | | |
| 26 | `get_trading_analysis` | mcp_tools/trading_analysis.py:133 | mixed | stay_http_heavy |
| 27 | `analyze_stock` | mcp_tools/stock.py:65 | fmp_fetch | stay_http_data |
| 28 | `check_exit_signals` | mcp_tools/signals.py:363 | fmp_fetch | stay_http_data |
| 29 | `analyze_option_chain` | mcp_tools/chain_analysis.py:314 | mixed (brokerage) | stay_http_data |
| 30 | `analyze_option_strategy` | mcp_tools/options.py:128 | mixed | stay_http_data (extract BS/Black-76) |
| **Factor & Tax (3)** | | | | |
| 31 | `get_factor_analysis` | mcp_tools/factor_intelligence.py:608 | mixed | stay_http_heavy |
| 32 | `get_factor_recommendations` | mcp_tools/factor_intelligence.py:984 | mixed | stay_http_heavy |
| 33 | `suggest_tax_loss_harvest` | mcp_tools/tax_harvest.py:1014 | mixed | stay_http_heavy |
| **Income (1)** | | | | |
| 34 | `get_income_projection` | mcp_tools/income.py:78 | mixed | stay_http_data |
| **Market data (5)** | | | | |
| 35 | `get_quote` | mcp_tools/quote.py:22 | fmp_fetch | stay_http_data |
| 36 | `get_futures_curve` | mcp_tools/futures_curve.py:113 | mixed (brokerage) | stay_http_data |
| 37 | `get_portfolio_news` | mcp_tools/news_events.py:297 | mixed | stay_http_data |
| 38 | `get_portfolio_events_calendar` | mcp_tools/news_events.py:362 | mixed | stay_http_data |
| 39 | `update_editorial_memory` | mcp_tools/overview_editorial.py:16 | db_write | stay_http_data |
| **Research (15)** | | | | |
| 40 | `list_research_files` | actions/research.py:22 | db_read | stay_http_data |
| 41 | `start_research` | actions/research.py:35 | db_write | stay_http_heavy |
| 42 | `read_research_thread` | actions/research.py:100 | db_read | stay_http_data |
| 43 | `load_document` | actions/research.py:141 | db_read | stay_http_data |
| 44 | `ingest_document` | actions/research.py:193 | db_write | stay_http_heavy |
| 45 | `create_annotation` | actions/research.py:220 | db_write | stay_http_heavy |
| 46 | `get_diligence_state` | actions/research.py:293 | db_read | stay_http_data |
| 47 | `update_diligence_section` | actions/research.py:314 | db_write | stay_http_heavy |
| 48 | `manage_qualitative_factor` | actions/research.py:365 | db_write | stay_http_heavy |
| 49 | `prepopulate_diligence` | actions/research.py:435 | db_write (llm) | stay_http_heavy |
| 50 | `get_handoff` | actions/research.py:500 | db_read | stay_http_data |
| 51 | `finalize_handoff` | actions/research.py:534 | db_write | stay_http_heavy |
| 52 | `new_handoff_version` | actions/research.py:553 | db_write | stay_http_heavy |
| 53 | `build_model` | actions/research.py:570 | mixed (file + llm) | stay_http_heavy |
| 54 | `activate_diligence` | actions/research.py:472 | db_write | stay_http_heavy |
| **Portfolio mgmt (7)** | | | | |
| 55 | `list_accounts` | mcp_tools/portfolio_management.py:20 | db_read | stay_http_data |
| 56 | `list_portfolios` | mcp_tools/portfolio_management.py:35 | db_read | stay_http_data |
| 57 | `create_portfolio` | mcp_tools/portfolio_management.py:54 | db_write | stay_http_data |
| 58 | `delete_portfolio` | mcp_tools/portfolio_management.py:79 | db_write | stay_http_data |
| 59 | `update_portfolio_accounts` | mcp_tools/portfolio_management.py:93 | db_write | stay_http_data |
| 60 | `account_activate` | mcp_tools/portfolio_management.py:109 | db_write | stay_http_data |
| 61 | `account_deactivate` | mcp_tools/portfolio_management.py:123 | db_write | stay_http_data |
| **Allocation (3)** | | | | |
| 62 | `get_target_allocation` | mcp_tools/allocation.py:129 | db_read | stay_http_data |
| 63 | `get_allocation_presets` | mcp_tools/allocation.py:172 | db_read | stay_http_data |
| 64 | `set_target_allocation` | mcp_tools/allocation.py:93 | db_write | stay_http_data |
| **Connections (3)** | | | | |
| 65 | `list_supported_brokerages` | mcp_tools/connections.py:684 | pure_compute | **extract_local_pure** |
| 66 | `list_connections` | mcp_tools/connection_status.py:35 | mixed | stay_http_data |
| 67 | `wait_for_sync` | mcp_tools/sync.py:10 | db_read | stay_http_data |
| **Baskets (7)** | | | | |
| 68 | `list_baskets` | mcp_tools/baskets.py:97 | db_read | stay_http_data |
| 69 | `get_basket` | mcp_tools/baskets.py:118 | db_read | stay_http_data |
| 70 | `analyze_basket` | mcp_tools/baskets.py:141 | mixed | stay_http_data |
| 71 | `create_basket` | mcp_tools/baskets.py | db_write | stay_http_data |
| 72 | `update_basket` | mcp_tools/baskets.py | db_write | stay_http_data |
| 73 | `delete_basket` | mcp_tools/baskets.py | db_write | stay_http_data |
| 74 | `create_basket_from_etf` | mcp_tools/baskets.py | mixed (fmp) | stay_http_data |
| **Trading (10)** | | | | |
| 75 | `get_orders` | mcp_tools/trading.py:77 | brokerage_call | stay_http_data |
| 76 | `preview_trade` | mcp_tools/trading.py:37 | brokerage_call | stay_http_data |
| 77 | `execute_trade` | mcp_tools/trading.py:66 | brokerage_call | stay_http_data |
| 78 | `cancel_order` | mcp_tools/trading.py:121 | brokerage_call | stay_http_data |
| 79 | `preview_basket_trade` | mcp_tools/basket_trading.py | brokerage_call | stay_http_data |
| 80 | `execute_basket_trade` | mcp_tools/basket_trading.py | brokerage_call | stay_http_data |
| 81 | `preview_futures_roll` | mcp_tools/futures_roll.py | brokerage_call | stay_http_data |
| 82 | `execute_futures_roll` | mcp_tools/futures_roll.py | brokerage_call | stay_http_data |
| 83 | `preview_option_trade` | mcp_tools/multi_leg_options.py | brokerage_call | stay_http_data |
| 84 | `execute_option_trade` | mcp_tools/multi_leg_options.py | brokerage_call | stay_http_data |
| **Transactions (8)** | | | | |
| 85 | `list_transactions` | mcp_tools/transactions.py | db_read | stay_http_data |
| 86 | `list_ingestion_batches` | mcp_tools/transactions.py | db_read | stay_http_data |
| 87 | `inspect_transactions` | mcp_tools/transactions.py | db_read | stay_http_data |
| 88 | `list_flow_events` | mcp_tools/transactions.py | db_read | stay_http_data |
| 89 | `list_income_events` | mcp_tools/transactions.py | db_read | stay_http_data |
| 90 | `transaction_coverage` | mcp_tools/transactions.py | db_read | stay_http_data |
| 91 | `fetch_provider_transactions` | mcp_tools/transactions.py | mixed | stay_http_heavy |
| 92 | `refresh_transactions` | mcp_tools/transactions.py | mixed | stay_http_heavy |
| **Audit + Config (4)** | | | | |
| 93 | `record_workflow_action` | mcp_tools/audit.py:28 | db_write | stay_http_data |
| 94 | `update_action_status` | mcp_tools/audit.py | db_write | stay_http_heavy |
| 95 | `get_action_history` | mcp_tools/audit.py:446 | db_read | **extract_local_pure**-adjacent (but keep HTTP for auth) |
| 96 | `manage_ticker_config` | mcp_tools/user_overrides.py:175 | mixed | stay_http_data |

---

## 9. Decision log

- **Don't touch the registry.** 96 functions work; this audit doesn't propose changing them.
- **The typing win is in `risk_client`, not `building_blocks`.** Polish the HTTP shim first — cheap, high-value.
- **The spec-correct move is a separate `portfolio_math` package**, not reshuffling the existing surface. It's new code in a new place.
- **Deprecate `building_blocks` only after `portfolio_math` ships** and the sandbox pattern `fetch via HTTP → compute locally` is proven.

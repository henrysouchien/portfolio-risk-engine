# Portfolio Tool Parity Matrix

Date: 2026-02-25

Scope: parity between legacy `ai_function_registry.py` tools and `portfolio-mcp` tools in `mcp_server.py`.

Pass criteria: zero `to be added` entries.

| Legacy AI-registry tool | portfolio-mcp equivalent | Status | Notes |
|---|---|---|---|
| `create_portfolio_scenario` | `run_whatif` | intentionally dropped | Legacy flow wrote YAML scenario files. MCP flow runs scenario analysis directly via structured inputs (`target_weights` / `delta_changes`) and avoids file-state side effects. |
| `run_portfolio_analysis` | `get_risk_analysis` | mapped | Same core risk-analysis capability; MCP adds section filtering and agent/file formats. |
| `analyze_stock` | `analyze_stock` | mapped | Direct equivalent. |
| `run_what_if_scenario` | `run_whatif` | mapped | Direct equivalent with explicit scenario arguments. |
| `optimize_minimum_variance` | `run_optimization(optimization_type="min_variance")` | mapped | Same optimization objective via typed parameter. |
| `optimize_maximum_return` | `run_optimization(optimization_type="max_return")` | mapped | Same optimization objective via typed parameter. |
| `get_risk_score` | `get_risk_score` | mapped | Direct equivalent. |
| `setup_new_portfolio` | `get_risk_profile` + `set_risk_profile` + per-tool `portfolio_name` | intentionally dropped | Legacy setup generated proxy scaffolding/state. MCP tools are stateless per call and work off current holdings/context without a dedicated setup command. |
| `estimate_expected_returns` | `get_factor_analysis(analysis_type="returns")` + optimization internals | intentionally dropped | Standalone expected-return estimator no longer exposed as a top-level tool; factor-return analysis plus optimization pipeline covers the workflow without persisting separate return assumptions. |
| `set_expected_returns` | none | intentionally dropped | Manual expected-return override was a mutable side-channel in legacy orchestration. MCP optimization is parameterized/stateless per call; no separate persistent override API. |
| `view_current_risk_limits` | `get_risk_profile` | mapped | `get_risk_profile` returns current risk profile metadata and limits. |
| `update_risk_limits` | `set_risk_profile` | mapped | Profile and explicit limit overrides are supported. |
| `reset_risk_limits` | `set_risk_profile(profile="balanced")` | mapped | Reset behavior achieved by reapplying baseline profile defaults. |
| `calculate_portfolio_performance` | `get_performance` | mapped | Direct performance-equivalent capability with summary/full/report/agent formats. |
| `list_portfolios` | none | intentionally dropped | MCP tools take `portfolio_name` per request; listing/switching active portfolio state is intentionally removed from the tool surface. |
| `switch_portfolio` | none | intentionally dropped | Replaced by explicit `portfolio_name` parameter on each call (stateless request model). |

## Result

- `mapped`: 10
- `intentionally dropped`: 6
- `to be added`: 0

The current `portfolio-mcp` surface is migration-ready under the stateless-per-call tool model.

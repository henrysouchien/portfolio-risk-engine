# Optimization Sub-Objectives: max_sharpe + target_volatility

## Context

The optimizer currently has only two modes: `min_variance` and `max_return`. An agent can't express *what kind* of optimization it wants — "find the best risk-adjusted portfolio" or "target 12% annual volatility" aren't possible. This is the biggest gap in the scenario tool chain identified by the decomposition audit.

Both new objectives can be built on the existing efficient frontier CVXPY infrastructure without new solver formulations:
- **max_sharpe**: Compute frontier → pick highest `(return - rf) / vol` point
- **target_volatility**: Single-point solve → maximize return subject to vol ≤ target

---

## Step 1a: Add `solve_single_volatility_target()` to frontier engine

**File:** `portfolio_risk_engine/efficient_frontier.py`

New public function after `compute_efficient_frontier()` (after line 372):

```python
def solve_single_volatility_target(
    weights: Dict[str, float],
    config: Dict[str, Any],
    risk_config: Dict[str, Any],
    proxies: Dict[str, Dict[str, Any]],
    expected_returns: Dict[str, float],
    target_volatility: float,
    fmp_ticker_map: Optional[Dict[str, str]] = None,
    instrument_types: Optional[Dict[str, str]] = None,
) -> FrontierPoint:
```

Logic:
1. Call `_extract_problem_data()` (existing, line 31)
2. **Validate target against risk limits**: `if target_volatility > data["max_vol"]: raise ValueError("Target volatility exceeds max_vol risk limit")`
3. **Guard against zero effective returns**: `if np.all(np.abs(data["mu"]) < 1e-10): raise ValueError("Effective expected returns are all zero after ticker filtering")`. This guards on the post-filtering `mu` vector from `_extract_problem_data()`, matching the pattern at `portfolio_optimizer.py:1200` which also guards after building the effective universe.
4. Create `cp.Variable(n)`, `cp.Parameter(nonneg=True)` for vol budget
5. Build constraints via `_build_shared_constraints()` (existing, line 129)
6. Set `vol_budget_param.value = (target_volatility / np.sqrt(12.0)) ** 2`
7. Create `cp.Problem(cp.Maximize(mu @ w), constraints)`
8. Solve via `_solve_with_cascade()` (existing, line 171)
9. If infeasible, raise `ValueError("Target volatility ... is not achievable within constraints")`
10. Return `FrontierPoint(volatility, expected_return, weights, is_feasible=True, label="target_vol")`

**Codex R3 fix**: Moved zero-returns guard INTO `solve_single_volatility_target()` after `_extract_problem_data()`, guarding on `data["mu"]` (the effective post-filtering vector) rather than raw `expected_returns`. A nonzero return on a ticker excluded from the covariance universe would otherwise still let an all-zero objective through.

This is the same single-point solve the frontier sweep does at lines 329-357, factored out as a reusable function.

**Codex R1 fix**: Added explicit `target_volatility <= data["max_vol"]` validation to prevent bypassing risk limits. `_build_shared_constraints()` only enforces the caller-supplied `vol_budget_param`, so the caller must guard against targets exceeding the configured max.

---

## Step 1b: Extract `evaluate_optimized_weights()` post-processing helper

**File:** `portfolio_risk_engine/portfolio_optimizer.py`

Extract the shared post-processing pattern from `run_max_return_portfolio()` (lines 1342-1387) into a reusable helper:

```python
def evaluate_optimized_weights(
    weights: Dict[str, float],
    config: Dict[str, Any],
    risk_config: Dict[str, Any],
    proxies: Dict[str, Dict[str, Any]],
    fmp_ticker_map: Optional[Dict[str, str]] = None,
    instrument_types: Optional[Dict[str, str]] = None,
    currency_map: Optional[Dict[str, str]] = None,
    contract_identities: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Evaluate optimized weights: build portfolio view, run risk/beta/proxy checks.

    Returns (portfolio_summary, risk_table, factor_table, proxy_table).
    Threads currency_map and contract_identities to build_portfolio_view() for
    FX-sensitive and derivative portfolios.
    """
```

**Codex R2 fix**: Added `currency_map` and `contract_identities` params. `build_portfolio_view()` supports these (`portfolio_risk.py:1754-1757`) and the frontier's `_extract_problem_data()` also uses them (`efficient_frontier.py:44-45`). Without threading them, the evaluation view could differ from the solve view for FX/derivative portfolios.

Logic (extracted from `run_max_return_portfolio()` lines 1342-1387):
1. `build_portfolio_view(weights, start_date, end_date, proxies, fmp_ticker_map, instrument_types)`
2. `_safe_eval_risk_limits(summary, risk_config)`
3. `compute_max_betas(proxies, start_date, end_date, loss_limit_pct)`
4. `calc_max_factor_betas(...)` for proxy caps
5. `_safe_eval_beta_limits(summary, max_betas, proxy_betas, max_proxy_betas)`
6. Split factor vs proxy tables
7. Return `(summary, risk_tbl, df_factors, df_proxies)`

Then update `run_max_return_portfolio()` to call this helper internally (reducing duplication).

**Codex R1 fix**: `evaluate_weights()` at line 519 only returns `(risk_table, beta_table)` — missing `portfolio_summary` and `proxy_table` needed by `OptimizationResult.from_core_optimization()`. This new helper produces the full 4-tuple matching the existing `max_return` pattern.

---

## Step 2: Add `optimize_max_sharpe()` and `optimize_target_volatility()` to optimization API

**File:** `portfolio_risk_engine/optimization.py`

Two new public functions, parallel to existing `optimize_min_variance()` (line 48) and `optimize_max_return()` (line 137):

### `optimize_max_sharpe(portfolio, risk_limits, risk_free_rate=None)`

```python
def optimize_max_sharpe(
    portfolio: Union[str, PortfolioData],
    risk_limits: Union[str, RiskLimitsData, Dict[str, Any], None] = "risk_limits.yaml",
    risk_free_rate: Optional[float] = None,
) -> OptimizationResult:
```

Logic:
1. `resolve_portfolio_config()` + `resolve_risk_config()` (same as existing functions)
2. `standardize_portfolio_input()` → `weights`
3. Call `compute_efficient_frontier(weights, config, risk_config, proxies, expected_returns, fmp_ticker_map, instrument_types, n_points=25)` — denser than default (15) for Sharpe precision. Pass `fmp_ticker_map` and `instrument_types` from config.
4. If no `risk_free_rate`, use `_safe_treasury_rate(datetime.fromisoformat(config["start_date"]), datetime.fromisoformat(config["end_date"]))` — note: `_safe_treasury_rate` expects `datetime` objects, not strings.
5. Filter to feasible points: `[p for p in frontier["frontier_points"] if p.is_feasible and p.volatility > 1e-8]`
6. For each feasible point: compute `sharpe = (point.expected_return - rf) / point.volatility`
7. Pick point with highest Sharpe. If no feasible points, raise `ValueError("No feasible frontier points")`
8. Evaluate via `evaluate_optimized_weights()` (new helper from Step 1b) → `(summary, risk_tbl, factor_tbl, proxy_tbl)`
9. Return `OptimizationResult.from_core_optimization(optimized_weights=best.weights, risk_table=risk_tbl, factor_table=factor_tbl, portfolio_summary=summary, proxy_table=proxy_tbl, optimization_metadata={...})`
10. Store `risk_free_rate`, `sharpe_ratio`, `analysis_date` (ISO string, required by `from_core_optimization`), `original_weights`, and `optimization_type: "max_sharpe"` in metadata

**Codex R1 fixes**: (a) Pass `fmp_ticker_map`/`instrument_types` through to frontier. (b) Convert string dates to `datetime` for `_safe_treasury_rate()`. (c) Use `evaluate_optimized_weights()` instead of `evaluate_weights()` to get full 4-tuple. (d) Include required `analysis_date` in metadata.

### `optimize_target_volatility(portfolio, risk_limits, target_volatility)`

```python
def optimize_target_volatility(
    portfolio: Union[str, PortfolioData],
    risk_limits: Union[str, RiskLimitsData, Dict[str, Any], None] = "risk_limits.yaml",
    target_volatility: float = 0.12,
) -> OptimizationResult:
```

Logic:
1. `resolve_portfolio_config()` + `resolve_risk_config()` (same as existing)
2. `standardize_portfolio_input()` → `weights`
3. Call `solve_single_volatility_target(weights, config, risk_config, proxies, expected_returns, target_volatility, fmp_ticker_map, instrument_types)` from Step 1a — zero-returns guard is inside `solve_single_volatility_target()` after `_extract_problem_data()` (guards on effective `mu` vector, not raw expected_returns)
5. Evaluate via `evaluate_optimized_weights()` (Step 1b) → `(summary, risk_tbl, factor_tbl, proxy_tbl)`
6. Return `OptimizationResult.from_core_optimization(optimized_weights=point.weights, risk_table=risk_tbl, factor_table=factor_tbl, portfolio_summary=summary, proxy_table=proxy_tbl, optimization_metadata={...})`
7. Store `target_volatility`, `analysis_date`, `original_weights`, `optimization_type: "target_volatility"` in metadata

**Codex R2 fix**: Added all-zero expected returns guard (matching `portfolio_optimizer.py:1200`). Without this, CVXPY maximizes a flat objective and returns arbitrary feasible weights.

---

## Step 3: Extend `run_optimization()` MCP tool

**File:** `mcp_tools/optimization.py`

1. **Extend `optimization_type` Literal** (line 73):
   ```python
   optimization_type: Literal["min_variance", "max_return", "max_sharpe", "target_volatility"] = "min_variance",
   ```

2. **Add `target_volatility` parameter** (after `optimization_type`):
   ```python
   target_volatility: Optional[float] = None,
   ```

3. **Extend expected returns loading** (line 119): Both `max_sharpe` and `target_volatility` require expected returns, same as `max_return`. Change the guard:
   ```python
   if optimization_type in ("max_return", "max_sharpe", "target_volatility"):
       # ... existing expected returns loading ...
   ```

4. **Extend routing** (line 142-145):
   ```python
   if optimization_type == "min_variance":
       result = optimize_min_variance(portfolio_data, risk_limits_data)
   elif optimization_type == "max_return":
       result = optimize_max_return(portfolio_data, risk_limits_data)
   elif optimization_type == "max_sharpe":
       result = optimize_max_sharpe(portfolio_data, risk_limits_data)
   elif optimization_type == "target_volatility":
       if target_volatility is None or not isinstance(target_volatility, (int, float)) or target_volatility <= 0:
           return {"status": "error", "error": "target_volatility parameter required as a positive decimal when optimization_type='target_volatility' (e.g., 0.12 for 12%)."}
       result = optimize_target_volatility(portfolio_data, risk_limits_data, target_volatility=float(target_volatility))
   ```

5. **Add imports** at top for the new functions.

---

## Step 4: Update MCP server wrapper

**File:** `mcp_server.py`

In the `run_optimization` wrapper (line 1507-1554):

1. Extend `optimization_type` Literal:
   ```python
   optimization_type: Literal["min_variance", "max_return", "max_sharpe", "target_volatility"] = "min_variance",
   ```
2. Add `target_volatility: Optional[float] = None` parameter
3. Pass through: `target_volatility=target_volatility` in the `_run_optimization()` call
4. Update docstring with new types

---

## Step 5: Update compare tool routing

**File:** `mcp_tools/compare.py`

1. **Extend validation** (line 224):
   ```python
   if optimization_type not in {"min_variance", "max_return", "max_sharpe", "target_volatility"}:
   ```

2. **Extend normalization** (line 229) — preserve `target_volatility` value in normalized scenario:
   ```python
   normalized = {"name": name, "optimization_type": optimization_type}
   if optimization_type == "target_volatility":
       tv = scenario.get("target_volatility")
       if tv is None or not isinstance(tv, (int, float)) or tv <= 0:
           return _error_response(f"Scenario '{name}' requires positive numeric 'target_volatility' (e.g., 0.12 for 12%).")
       normalized["target_volatility"] = float(tv)
   normalized_scenarios.append(normalized)
   ```

3. **Extend routing** (lines 326-333):
   ```python
   if optimization_type == "max_return":
       result = optimize_max_return(portfolio_copy, risk_limits_data)
   elif optimization_type == "max_sharpe":
       result = optimize_max_sharpe(portfolio_copy, risk_limits_data)
   elif optimization_type == "target_volatility":
       result = optimize_target_volatility(portfolio_copy, risk_limits_data, target_volatility=scenario["target_volatility"])
   else:
       result = optimize_min_variance(portfolio_copy, risk_limits_data)
   ```

4. **Extend expected returns guard** (line 327) — `max_sharpe` and `target_volatility` also need expected returns:
   ```python
   if optimization_type in ("max_return", "max_sharpe", "target_volatility") and not expected_returns:
       raise ValueError(expected_returns_error)
   ```

5. **Add imports** for new functions.

**Codex R1 fix**: Normalization at line 229 only preserved `name` and `optimization_type`. Now explicitly stores and validates `target_volatility` during normalization so it's available in the routing block.

---

## Step 6: Add `sharpe_ratio` to OptimizationResult agent snapshot

**File:** `core/result_objects/optimization.py`

In `get_agent_snapshot()`, add conditional fields (only when present in metadata):

```python
sharpe_from_metadata = self.optimization_metadata.get("sharpe_ratio")
if sharpe_from_metadata is not None:
    snapshot["sharpe_ratio"] = round(sharpe_from_metadata, 4)

target_vol = self.optimization_metadata.get("target_volatility")
if target_vol is not None:
    snapshot["target_volatility_pct"] = round(target_vol * 100, 2)
```

These are conditional — existing optimization types don't get these fields. Only `max_sharpe` results include `sharpe_ratio`, only `target_volatility` results include `target_volatility_pct`.

---

## Step 7: Tests

### 7a. Engine tests
**File:** `tests/portfolio_risk_engine/test_efficient_frontier_targets.py` (NEW)

- `test_solve_single_volatility_target_returns_frontier_point()` — basic solve
- `test_solve_single_volatility_target_respects_vol_cap()` — realized vol ≤ target
- `test_solve_single_volatility_target_infeasible_raises()` — too-tight target raises ValueError

### 7b. Optimization API tests
**File:** `tests/portfolio_risk_engine/test_optimization_new_types.py` (NEW)

- `test_optimize_max_sharpe_returns_result()` — returns OptimizationResult with type="max_sharpe"
- `test_optimize_max_sharpe_picks_best_sharpe()` — verify selected point has highest Sharpe
- `test_optimize_target_volatility_returns_result()` — returns OptimizationResult
- `test_optimize_target_volatility_metadata()` — target_volatility stored in metadata

### 7c. MCP tool tests
**File:** `tests/mcp_tools/test_optimization_new_types.py` (NEW)

- `test_max_sharpe_agent_format()` — response structure correct
- `test_max_sharpe_snapshot_has_sharpe_ratio()` — sharpe_ratio in snapshot
- `test_target_volatility_requires_param()` — missing target_volatility returns error
- `test_target_volatility_agent_format()` — response structure correct
- `test_target_volatility_snapshot_has_target()` — target_volatility_pct in snapshot
- `test_target_volatility_above_max_vol()` — above-max-vol target returns error
- `test_target_volatility_negative()` — negative target returns error
- `test_mcp_server_optimization_type_includes_new()` — AST check for Literal types includes max_sharpe and target_volatility
- `test_mcp_server_target_volatility_param()` — AST check for parameter existence

### 7d. Compare tool tests
**File:** `tests/mcp_tools/test_compare_new_opt_types.py` (NEW)

- `test_compare_max_sharpe_routing()` — max_sharpe scenario dispatches correctly
- `test_compare_target_volatility_normalization()` — target_volatility value preserved through normalization
- `test_compare_target_volatility_missing_value()` — error when target_volatility missing from scenario
- `test_compare_mixed_optimization_types()` — mix of min_variance + max_sharpe in one comparison

### 7e. Update existing tests
**File:** `tests/core/test_optimization_agent_snapshot.py`

- Existing key assertion does NOT need updating (new fields are conditional, not always present)
- Add: `test_agent_snapshot_sharpe_ratio_present_when_in_metadata()`
- Add: `test_agent_snapshot_target_volatility_present_when_in_metadata()`
- Add: `test_agent_snapshot_sharpe_ratio_absent_without_metadata()` — verify field not present for min_variance

**Codex R1 fix**: Added compare-tool routing tests, above-max-vol target test, negative target test, absent-metadata test.

---

## Edge Cases

- **Infeasible target volatility** — target below min-variance vol: CVXPY solver returns infeasible. Target above `max_vol` risk limit: caught by explicit guard in `solve_single_volatility_target()`. Both raise `ValueError`, caught by `@handle_mcp_errors` → structured error response.
- **Frontier endpoint failure** — `compute_efficient_frontier()` raises (not returns empty) if min-var or max-return endpoint solve fails (`efficient_frontier.py:268`, `:310`). `@handle_mcp_errors` catches this.
- **All-zero expected returns** — frontier returns only min-variance point when returns are near-constant (`efficient_frontier.py:286`). `optimize_max_sharpe()` should handle this: if only 1 feasible point, use it (Sharpe is undefined but weights are valid).
- **All Sharpe values negative** — still pick highest (least negative). No flag changes needed — existing flags already cover `has violations` and compliance verdicts.
- **Zero volatility point** — skip in Sharpe calculation: filter `p.volatility > 1e-8`.
- **`target_volatility` without the param** — explicit validation in MCP tool returns clear error.
- **Expected returns missing** — same guard as `max_return` (lines 119-139 of `mcp_tools/optimization.py`). Both new types require DB.
- **Negative/non-numeric target_volatility in compare** — validated during normalization with explicit error.

**Codex R1 fix**: Corrected frontier failure model (raises, not returns empty). Added all-zero expected returns handling. Removed unsupported "agent flags can warn" claim.

---

## Files Changed

| File | Type | Change |
|------|------|--------|
| `portfolio_risk_engine/efficient_frontier.py` | Modify | +45 lines: `solve_single_volatility_target()` |
| `portfolio_risk_engine/portfolio_optimizer.py` | Modify | +35 lines: `evaluate_optimized_weights()` helper, refactor `run_max_return_portfolio()` |
| `portfolio_risk_engine/optimization.py` | Modify | +90 lines: `optimize_max_sharpe()`, `optimize_target_volatility()` |
| `mcp_tools/optimization.py` | Modify | +25 lines: routing, params, imports |
| `mcp_server.py` | Modify | +8 lines: params, passthrough, docstring |
| `mcp_tools/compare.py` | Modify | +20 lines: routing, validation, normalization |
| `core/result_objects/optimization.py` | Modify | +8 lines: conditional snapshot fields |
| `tests/portfolio_risk_engine/test_efficient_frontier_targets.py` | Create | ~80 lines |
| `tests/portfolio_risk_engine/test_optimization_new_types.py` | Create | ~100 lines |
| `tests/mcp_tools/test_optimization_new_types.py` | Create | ~180 lines |
| `tests/mcp_tools/test_compare_new_opt_types.py` | Create | ~100 lines |
| `tests/core/test_optimization_agent_snapshot.py` | Modify | +30 lines: 3 new tests |

~230 lines production code, ~490 lines tests. 12 files total.

---

## Reused Infrastructure

- `_extract_problem_data()` — `efficient_frontier.py:31` (tickers, sigma, mu, constraints)
- `_build_shared_constraints()` — `efficient_frontier.py:129` (CVXPY constraint list)
- `_solve_with_cascade()` — `efficient_frontier.py:171` (multi-solver cascade)
- `compute_efficient_frontier()` — `efficient_frontier.py:232` (full frontier for max_sharpe)
- `_safe_treasury_rate()` — `core/realized_performance/nav.py:906` (risk-free rate)
- `evaluate_optimized_weights()` — NEW helper extracted from `run_max_return_portfolio()` post-processing (lines 1342-1387). Returns full `(summary, risk_tbl, factor_tbl, proxy_tbl)` 4-tuple.
- `build_portfolio_view()` — `portfolio_risk.py` (portfolio analysis)
- `_safe_eval_risk_limits()` — `portfolio_optimizer.py:44` (risk limit checks)
- `_safe_eval_beta_limits()` — `portfolio_optimizer.py` (factor+proxy beta checks)
- `compute_max_betas()` — `risk_helpers.py` (factor beta caps)
- `calc_max_factor_betas()` — `risk_helpers.py` (proxy beta caps)
- `resolve_portfolio_config()` + `resolve_risk_config()` — `config_adapters.py`
- `OptimizationResult.from_core_optimization()` — `result_objects/optimization.py`

---

## Verification

1. `pytest tests/portfolio_risk_engine/test_efficient_frontier_targets.py tests/portfolio_risk_engine/test_optimization_new_types.py tests/mcp_tools/test_optimization_new_types.py tests/core/test_optimization_agent_snapshot.py -v`
2. Full suite: `pytest tests/ -x`
3. Live MCP test: `run_optimization(optimization_type="max_sharpe", format="agent")`
4. Live MCP test: `run_optimization(optimization_type="target_volatility", target_volatility=0.12, format="agent")`
5. Compare test: `compare_scenarios(mode="optimization", scenarios=[{"name": "min_var", "optimization_type": "min_variance"}, {"name": "max_sharpe", "optimization_type": "max_sharpe"}])`

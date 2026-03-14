# Efficient Frontier Visualization — Plan
**Status:** DONE

## Context

The optimization infrastructure supports single-point optimization (min_variance or max_return) via CVXPY. There's no way to compute or visualize the full efficient frontier — the set of optimal portfolios across the risk-return spectrum.

**Existing building blocks:**
- `solve_min_variance_with_risk_limits()` — CVXPY QP solver, minimizes `w^T Σ w` subject to concentration, factor beta, proxy, and volatility constraints
- `solve_max_return_with_risk_limits()` — maximizes `Σ w_i μ_i` subject to same constraints + vol cap
- `build_portfolio_view()` — returns `volatility_annual`, `volatility_monthly`, covariance matrix, factor betas
- `evaluate_weights()` — runs risk+beta limit checks on arbitrary weights
- `standardize_portfolio_input()` — converts shares/dollars to weights via live prices (required before any solver call)
- Recharts in frontend with `ChartContainer` wrapper, `ScatterChart`/`LineChart` available
- `OptimizationsTab` in ScenarioAnalysis already displays cached optimization results
- Existing API pattern: `_run_*_workflow()` helpers, `OptimizationService`, response model envelopes, threadpool execution
- Frontend pattern: `usePortfolioOptimization` hook via `SessionManager`/`AdapterRegistry` flow

## Design

### Approach: Parametric Volatility Sweep

Sweep a volatility target from σ_min (minimum-variance portfolio) to σ_max (maximum-return portfolio or risk limit cap), solving `maximize Σ w_i μ_i` at each step with a tightened volatility constraint. This produces frontier points (σ, μ, weights).

**Why volatility sweep (not return sweep):** The vol constraint is already a second-order cone constraint in both solvers. Parametrizing it is natural — just change the `max_vol` bound in each solve. A return sweep would require adding a new return floor constraint.

**Number of points:** 15 points (min-var + 13 intermediate + max-return). Each solve takes ~2-5s depending on portfolio size, so 15 points ≈ 30-75s total. Covariance matrix and betas are computed once and reused.

### Architecture

```
compute_efficient_frontier()          # New orchestration function
  ├── build_portfolio_view()          # Once — get Σ, betas, tickers (reuse)
  ├── _build_shared_problem_data()    # Once — extract Σ, beta_mat, proxy_caps, mu
  ├── solve_min_variance()            # Point 1: σ_min endpoint
  ├── _solve_frontier_point(σ_target) # Points 2-14: parametric sweep (cp.Parameter for vol cap)
  │     └── CVXPY: max Σ w_i μ_i s.t. σ_p ≤ σ_target + all other constraints
  └── solve_max_return()              # Point 15: σ_max endpoint
```

## Files to Modify / Create

**Phase 1 — Backend (this plan):**
1. **`portfolio_risk_engine/efficient_frontier.py`** — NEW: core frontier computation
2. **`core/result_objects/efficient_frontier.py`** — NEW: `EfficientFrontierResult` dataclass (with `to_api_response()` + `get_summary()`)
3. **`core/result_objects/__init__.py`** — re-export
4. **`mcp_tools/optimization.py`** — add `get_efficient_frontier()` MCP tool
5. **`mcp_server.py`** — register new tool
6. **`services/optimization_service.py`** — add `compute_efficient_frontier()` method with content-keyed caching
7. **`models/response_models.py`** — add `EfficientFrontierResponse` response model
8. **`models/__init__.py`** — re-export
9. **`app.py`** — add `EfficientFrontierRequest` (inline, same as `OptimizationRequest` at line 580), `_run_efficient_frontier_workflow()`, `POST /api/efficient-frontier` endpoint

**Phase 2 — Frontend (separate plan, requires architecture exploration):**
Frontend integration requires exploring the actual container/orchestration/hook plumbing. Key architecture notes for Phase 2 plan:
- `OptimizationsTab` is rendered in `ScenarioAnalysis.tsx:355`, not `ScenarioAnalysisContainer`
- Tab props flow through `useScenarioOrchestration.ts:166`
- `usePortfolioOptimization` auto-runs on mount; frontier should be button-triggered (expensive)
- Types in `api.ts` depend on OpenAPI generated components; need `openapi-schema.json` update
- Hook/adapter/manager must be re-exported through barrel files (`hooks/index.ts`, `connectors/index.ts`)

## Changes

### 1. Core Engine: `portfolio_risk_engine/efficient_frontier.py`

**Design principle: reuse existing solver infrastructure, don't duplicate.** The constraint-building logic (ticker filtering, beta/proxy caps, concentration, solver cascade) already lives in `portfolio_optimizer.py`. The frontier engine extracts the shared data once and delegates per-point solves to a thin inner function that reuses the same pre-computed arrays.

Use `cp.Parameter` for the volatility cap to avoid rebuilding the full CVXPY problem at each point — only the parameter value changes between solves (warm-start friendly).

```python
"""Efficient frontier computation via parametric volatility sweep."""

import math
import numpy as np
import cvxpy as cp
import pandas as pd
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from portfolio_risk_engine.portfolio_risk import build_portfolio_view, normalize_weights
from portfolio_risk_engine.risk_helpers import compute_max_betas, get_worst_monthly_factor_losses
from portfolio_risk_engine._logging import portfolio_logger, log_timing, log_errors


@dataclass
class FrontierPoint:
    """Single point on the efficient frontier."""
    volatility: float          # Annualized volatility (decimal, e.g. 0.08 = 8%)
    expected_return: float     # Expected annual return (decimal)
    weights: Dict[str, float]  # Optimal weights at this risk level
    is_feasible: bool          # Whether solver found a solution
    label: str                 # "min_variance", "max_return", or "frontier_{i}"


def _extract_problem_data(
    weights: Dict[str, float],
    config: Dict[str, Any],
    proxies: Dict[str, Dict[str, Any]],
    expected_returns: Dict[str, float],
    fmp_ticker_map: Optional[Dict[str, str]],
    instrument_types: Optional[Dict[str, str]],
    risk_config: Dict[str, Any],
) -> dict:
    """
    Build portfolio view ONCE and extract all data needed for the frontier sweep.

    Returns dict with: tickers, n, Σ, beta_mat, mu, max_betas, proxy_caps,
    max_weight, max_vol, summary (for current portfolio metrics).

    This mirrors the data extraction in solve_min_variance_with_risk_limits()
    and solve_max_return_with_risk_limits() but is done once for all points.
    """
    normalized = normalize_weights(weights, normalize=True)
    summary = build_portfolio_view(
        normalized, config["start_date"], config["end_date"],
        expected_returns=None, stock_factor_proxies=proxies,
        fmp_ticker_map=fmp_ticker_map, instrument_types=instrument_types,
    )

    # Filter to tickers with covariance data (same logic as existing solvers)
    cov_tickers = set(summary["covariance_matrix"].columns)
    original_tickers = list(normalized.keys())
    tickers = [t for t in original_tickers if t in cov_tickers]
    if not tickers:
        raise ValueError("No valid tickers with covariance data.")

    # Renormalize weights after dropping missing-data tickers
    # (same as solve_min_variance_with_risk_limits lines 248-254)
    if len(tickers) < len(original_tickers):
        missing = set(original_tickers) - set(tickers)
        portfolio_logger.warning(
            "Frontier: dropping %d tickers with no data: %s", len(missing), missing
        )
        remaining = {t: normalized[t] for t in tickers}
        total = sum(remaining.values())
        normalized = {t: w / total for t, w in remaining.items()}

    n = len(tickers)
    Σ = summary["covariance_matrix"].loc[tickers, tickers].values
    beta_mat = summary["df_stock_betas"].fillna(0.0).loc[tickers]

    # Expected returns vector.
    # Coverage enforcement is done UPSTREAM in the MCP tool / REST workflow
    # via ReturnsService.ensure_returns_coverage() (same as max-return path,
    # app.py:3116). By the time we get here, expected_returns should have
    # full coverage. Tickers still missing get 0 (conservative).
    tickers_with_returns = [t for t in tickers if t in expected_returns]
    coverage_pct = len(tickers_with_returns) / len(tickers) * 100 if tickers else 0
    if coverage_pct < 80:
        portfolio_logger.warning(
            "Frontier: only %.0f%% of tickers have expected returns — "
            "missing tickers default to 0%% return (penalized by optimizer).",
            coverage_pct,
        )
    mu = np.array([expected_returns.get(t, 0.0) for t in tickers])

    # Pre-compute beta limits (same as existing solvers)
    max_betas = compute_max_betas(
        proxies, config["start_date"], config["end_date"],
        loss_limit_pct=risk_config["max_single_factor_loss"],
        fmp_ticker_map=fmp_ticker_map,
    )

    # Pre-compute proxy caps (same as existing solvers)
    worst_proxy_loss = get_worst_monthly_factor_losses(
        proxies, config["start_date"], config["end_date"],
        fmp_ticker_map=fmp_ticker_map,
    )
    loss_lim = risk_config["max_single_factor_loss"]
    proxy_caps = {
        proxy: (np.inf if loss >= 0 else loss_lim / loss)
        for proxy, loss in worst_proxy_loss.items()
    }

    max_weight = risk_config["concentration_limits"]["max_single_stock_weight"]
    max_vol = risk_config["portfolio_limits"]["max_volatility"]

    # Current portfolio metrics
    current_vol = summary.get("volatility_annual", 0.0)
    current_ret = float(mu @ np.array([normalized.get(t, 0.0) for t in tickers]))

    return {
        "tickers": tickers, "n": n, "Σ": Σ, "beta_mat": beta_mat,
        "mu": mu, "max_betas": max_betas, "proxy_caps": proxy_caps,
        "proxies": proxies, "max_weight": max_weight, "max_vol": max_vol,
        "summary": summary, "current_vol": current_vol, "current_ret": current_ret,
    }


def _build_shared_constraints(w_var, data, vol_budget_param):
    """
    Build constraint list matching existing solver constraints.

    Uses cp.Parameter for vol cap so the problem can be re-solved with
    different targets without full reconstruction.

    Mirrors constraints in solve_min_variance_with_risk_limits() and
    solve_max_return_with_risk_limits():
    1. Fully invested (sum = 1)
    2. Long-only (w >= 0)
    3. Concentration cap
    4. Factor beta limits (excl. industry)
    5. Per-proxy industry beta limits
    6. Volatility cap (parametric via cp.Parameter)
    """
    tickers = data["tickers"]
    beta_mat = data["beta_mat"]
    max_betas = data["max_betas"]
    proxy_caps = data["proxy_caps"]
    proxies = data["proxies"]
    Σ = data["Σ"]
    max_weight = data["max_weight"]

    cons = [
        cp.sum(w_var) == 1,
        w_var >= 0,
        cp.abs(w_var) <= max_weight,
    ]

    # Factor beta constraints — only market/momentum/value aggregate caps
    # (same as solve_max_return_with_risk_limits, portfolio_optimizer.py:1194)
    for fac in ("market", "momentum", "value"):
        if fac not in max_betas or fac not in beta_mat.columns:
            continue
        cons.append(cp.abs(beta_mat[fac].values @ w_var) <= max_betas[fac])

    # Per-proxy beta constraints (same logic as existing solvers)
    for proxy, cap in proxy_caps.items():
        coeff = []
        for t in tickers:
            this_proxy = proxies.get(t, {}).get("industry")
            if this_proxy == proxy:
                coeff.append(beta_mat.loc[t, "industry"] if "industry" in beta_mat.columns else 0.0)
            else:
                coeff.append(0.0)
        coeff_array = np.array(coeff)
        if not np.allclose(coeff_array, 0):
            cons.append(cp.abs(coeff_array @ w_var) <= cap)

    # Parametric volatility cap: √(12 w^T Σ w) ≤ vol_cap
    # Expressed as: w^T Σ w ≤ vol_budget_param
    # where vol_budget_param = (vol_cap / √12)^2
    # NOTE: vol_budget_param IS the squared budget (not the raw vol cap),
    # so the RHS is just the parameter itself. This is DPP-compliant
    # (affine in parameter), enabling true problem reuse across solves.
    cons.append(cp.quad_form(w_var, Σ) <= vol_budget_param)

    return cons


def _solve_with_cascade(prob, objective_type="max_return"):
    """
    Try solvers in priority order matching existing solver cascades.
    - min_variance: ECOS→CLARABEL→MOSEK→SCS + OSQP fallback
      (matches solve_min_variance_with_risk_limits, portfolio_optimizer.py:333)
    - max_return: CLARABEL→OSQP→ECOS→SCS
      (matches solve_max_return_with_risk_limits, portfolio_optimizer.py:1247)
    Returns True if solved.
    """
    # Solver order matches existing implementations exactly:
    # - min_variance: portfolio_optimizer.py:333 (ECOS→CLARABEL→MOSEK→SCS + OSQP fallback)
    # - max_return: portfolio_optimizer.py:1247 (CLARABEL→OSQP→ECOS→SCS)
    #   Note: only ECOS uses qcp=True in max-return (line 1257-1258)
    if objective_type == "min_variance":
        solvers = [
            (cp.ECOS, {"verbose": False}, True),
            (cp.CLARABEL, {"verbose": False}, True),
            (cp.MOSEK, {"verbose": False}, True),
            (cp.SCS, {"verbose": False, "eps": 1e-6}, True),
            (cp.OSQP, {"verbose": False, "eps_abs": 1e-6, "eps_rel": 1e-6}, False),
        ]
    else:
        # Max-return: only ECOS uses qcp=True (matching portfolio_optimizer.py:1257)
        solvers = [
            (cp.CLARABEL, {"verbose": False}, False),
            (cp.OSQP, {"verbose": False, "eps_abs": 1e-5, "eps_rel": 1e-5}, False),
            (cp.ECOS, {"verbose": False}, True),   # qcp=True for ECOS only
            (cp.SCS, {"verbose": False, "eps": 1e-4}, False),
        ]
    for solver, kwargs, use_qcp in solvers:
        try:
            solve_kwargs = {**kwargs, "warm_start": True}
            if use_qcp:
                solve_kwargs["qcp"] = True
            prob.solve(solver=solver, **solve_kwargs)
            if prob.status in ("optimal", "optimal_inaccurate"):
                return True
        except Exception:
            continue
    return False


def _validate_endpoint_weights(w_arr, data, label):
    """
    Post-solve validation for endpoint weights (min-var and max-return).
    Checks proxy caps that evaluate_weights() doesn't cover.
    Logs warnings for 'optimal_inaccurate' violations rather than hard-failing,
    since CVXPY constraints were already enforced during solving.
    """
    tickers = data["tickers"]
    proxy_caps = data["proxy_caps"]
    proxies = data["proxies"]
    beta_mat = data["beta_mat"]

    for proxy, cap in proxy_caps.items():
        if cap == np.inf:
            continue
        port_beta = sum(
            w_arr[i] * (beta_mat.loc[t, "industry"] if proxies.get(t, {}).get("industry") == proxy
                        and "industry" in beta_mat.columns else 0.0)
            for i, t in enumerate(tickers)
        )
        if abs(port_beta) > cap * 1.01:  # 1% tolerance for numerical noise
            portfolio_logger.warning(
                "Frontier %s: proxy '%s' beta %.4f exceeds cap %.4f "
                "(likely 'optimal_inaccurate' solution).",
                label, proxy, port_beta, cap,
            )


@log_errors("high")
@log_timing(60.0)
def compute_efficient_frontier(
    weights: Dict[str, float],
    config: Dict[str, Any],
    risk_config: Dict[str, Any],
    proxies: Dict[str, Dict[str, Any]],
    expected_returns: Dict[str, float],
    fmp_ticker_map: Optional[Dict[str, str]] = None,
    instrument_types: Optional[Dict[str, str]] = None,
    n_points: int = 15,
) -> dict:
    """
    Compute the efficient frontier by sweeping volatility targets.

    Steps:
    1. Build portfolio view once (Σ, betas, tickers) via _extract_problem_data
    2. Solve min-variance → get σ_min
    3. Guard: if all expected returns are zero/missing, return min-var only
    4. Solve max-return (at risk limit σ_max) → get σ_max
    5. Sweep σ_min to σ_max in n_points-2 intermediate steps
    6. At each step: maximize Σ w_i μ_i s.t. σ_p ≤ σ_target

    Returns dict with frontier_points, current_portfolio, endpoints, meta.
    """
    # Clamp n_points at engine level (defense-in-depth — also validated upstream)
    n_points = max(5, min(30, n_points))

    data = _extract_problem_data(
        weights, config, proxies, expected_returns,
        fmp_ticker_map, instrument_types, risk_config,
    )

    n = data["n"]
    Σ = data["Σ"]
    mu = data["mu"]
    max_vol = data["max_vol"]
    tickers = data["tickers"]

    # --- Min-variance endpoint ---
    w_min = cp.Variable(n)
    vol_cap_min = cp.Parameter(nonneg=True)
    vol_cap_min.value = (max_vol / np.sqrt(12)) ** 2  # squared budget (DPP)
    cons_min = _build_shared_constraints(w_min, data, vol_cap_min)
    prob_min = cp.Problem(cp.Minimize(cp.quad_form(w_min, Σ)), cons_min)

    if not _solve_with_cascade(prob_min, objective_type="min_variance"):
        raise ValueError("Min-variance solve failed — check risk constraints.")

    w_min_vals = {t: float(w_min.value[i]) for i, t in enumerate(tickers)}
    min_var = float(w_min.value @ Σ @ w_min.value)
    σ_min = math.sqrt(12 * min_var)
    ret_min = float(mu @ w_min.value)

    # Post-solve validation for min-var endpoint (proxy caps — logs warnings)
    _validate_endpoint_weights(w_min.value, data, "min_variance")

    min_var_point = FrontierPoint(
        volatility=σ_min, expected_return=ret_min,
        weights=w_min_vals, is_feasible=True, label="min_variance",
    )

    # --- Guard: degenerate expected returns → return min-var only ---
    # Catches both all-zero and near-constant mu. With sum(w)=1 constraint,
    # constant mu makes mu@w a constant, so sweep produces dominated points.
    mu_range = mu.max() - mu.min()
    if np.allclose(mu, 0) or mu_range < 1e-6:
        portfolio_logger.warning(
            "Expected returns are zero or near-constant (range=%.2e) — "
            "frontier degenerates to min-variance point only.", mu_range,
        )
        return {
            "frontier_points": [min_var_point],
            "current_portfolio": {"volatility": data["current_vol"], "expected_return": data["current_ret"]},
            "min_variance_point": min_var_point,
            "max_return_point": min_var_point,  # same as min-var when μ=0
            "n_feasible": 1,
            "n_requested": n_points,
        }

    # --- Max-return endpoint (at full risk budget) ---
    w_max = cp.Variable(n)
    vol_cap_max = cp.Parameter(nonneg=True)
    vol_cap_max.value = (max_vol / np.sqrt(12)) ** 2  # squared budget (DPP)
    cons_max = _build_shared_constraints(w_max, data, vol_cap_max)
    prob_max = cp.Problem(cp.Maximize(mu @ w_max), cons_max)

    if not _solve_with_cascade(prob_max):
        raise ValueError("Max-return solve failed — check risk constraints and expected returns.")

    w_max_vals = {t: float(w_max.value[i]) for i, t in enumerate(tickers)}
    max_var = float(w_max.value @ Σ @ w_max.value)
    σ_max = math.sqrt(12 * max_var)
    ret_max = float(mu @ w_max.value)

    # Post-solve validation for max-return endpoint (proxy caps — logs warnings)
    _validate_endpoint_weights(w_max.value, data, "max_return")

    max_ret_point = FrontierPoint(
        volatility=σ_max, expected_return=ret_max,
        weights=w_max_vals, is_feasible=True, label="max_return",
    )

    # --- Sweep intermediate points ---
    frontier = [min_var_point]

    if σ_max > σ_min + 1e-6 and n_points > 2:
        # Build parametric max-return problem with cp.Parameter for vol target
        w_sweep = cp.Variable(n)
        vol_cap_sweep = cp.Parameter(nonneg=True)
        cons_sweep = _build_shared_constraints(w_sweep, data, vol_cap_sweep)
        prob_sweep = cp.Problem(cp.Maximize(mu @ w_sweep), cons_sweep)

        vol_targets = np.linspace(σ_min, σ_max, n_points)[1:-1]
        for i, σ_target in enumerate(vol_targets):
            vol_cap_sweep.value = (σ_target / np.sqrt(12)) ** 2  # squared budget (DPP)
            solved = _solve_with_cascade(prob_sweep)

            if solved:
                w_vals = {t: float(w_sweep.value[i_t]) for i_t, t in enumerate(tickers)}
                pv = float(w_sweep.value @ Σ @ w_sweep.value)
                pv_vol = math.sqrt(12 * pv)
                pv_ret = float(mu @ w_sweep.value)
                frontier.append(FrontierPoint(
                    volatility=pv_vol, expected_return=pv_ret,
                    weights=w_vals, is_feasible=True,
                    label=f"frontier_{i+1}",
                ))
            else:
                # σ_target >= σ_min should always be feasible (min-var portfolio satisfies it).
                # If we fail here, it's a numerical issue, not true infeasibility.
                portfolio_logger.warning(
                    "Frontier point %d (σ_target=%.4f) failed numerically — skipping.",
                    i + 1, σ_target,
                )

    frontier.append(max_ret_point)
    frontier.sort(key=lambda p: p.volatility)

    return {
        "frontier_points": frontier,
        "current_portfolio": {"volatility": data["current_vol"], "expected_return": data["current_ret"]},
        "min_variance_point": min_var_point,
        "max_return_point": max_ret_point,
        "n_feasible": len(frontier),
        "n_requested": n_points,
    }
```

**Key design decisions:**
- **Reuse, not duplicate**: `_extract_problem_data()` and `_build_shared_constraints()` mirror the data extraction and constraint logic in `solve_min_variance_with_risk_limits()` / `solve_max_return_with_risk_limits()`. Same ticker filtering, same beta/proxy cap computation, same constraint structure. Future refactor can extract these into shared functions to eliminate drift.
- **`cp.Parameter` for vol budget (DPP-compliant)**: The sweep problem is built once with a `cp.Parameter` for the squared volatility budget (`(σ / √12)²`). The constraint `quad_form(w, Σ) ≤ vol_budget_param` is affine in the parameter, making it DPP-compliant. This means CVXPY can reuse the compiled problem structure across solves — only the parameter value changes, avoiding full problem reconstruction.
- **Zero returns guard**: If all μ=0, `Maximize(μ^T w)` is a constant objective. Existing max-return solver rejects this. We guard explicitly and return only the min-var point.
- **Numerical failure ≠ infeasibility**: Any σ_target ≥ σ_min is geometrically feasible (the min-var portfolio satisfies it). Failures at intermediate points are numerical — log a warning, don't silently filter.
- **Post-solve validation**: `_validate_endpoint_weights()` checks proxy-cap compliance on min-var and max-return endpoints (which `evaluate_weights()` doesn't cover). Logs warnings for `optimal_inaccurate` violations (1% tolerance). Intermediate sweep points skip validation for performance — CVXPY constraints enforce limits during solving.
- **Solver cascade**: Matches existing solvers exactly — min-variance uses ECOS→CLARABEL→MOSEK→SCS+OSQP (portfolio_optimizer.py:333), max-return sweep uses CLARABEL→OSQP→ECOS→SCS (portfolio_optimizer.py:1247). `objective_type` parameter selects the cascade.

### 2. Result Object: `core/result_objects/efficient_frontier.py`

```python
"""Efficient frontier result object."""
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from datetime import datetime, UTC

@dataclass
class EfficientFrontierResult:
    """Result of efficient frontier computation."""
    frontier_points: List[Dict[str, Any]]   # [{volatility, expected_return, weights, label}]
    current_portfolio: Dict[str, Any]       # {volatility, expected_return} of current weights
    min_variance_point: Dict[str, Any]      # The min-var endpoint
    max_return_point: Dict[str, Any]        # The max-return endpoint
    n_feasible: int                         # Number of feasible points found
    n_requested: int                        # Number of points requested
    computation_time_s: float               # Wall clock time
    analysis_date: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_api_response(self) -> Dict[str, Any]:
        """Serialize for REST API / frontend consumption."""
        def _point_to_pct(p):
            """Convert FrontierPoint or dict to pct-formatted dict."""
            vol = p.volatility if hasattr(p, 'volatility') else p["volatility"]
            ret = p.expected_return if hasattr(p, 'expected_return') else p["expected_return"]
            label = p.label if hasattr(p, 'label') else p.get("label", "")
            feasible = p.is_feasible if hasattr(p, 'is_feasible') else p.get("is_feasible", True)
            return {
                "volatility_pct": round(vol * 100, 2),
                "expected_return_pct": round(ret * 100, 2),
                "label": label,
                "is_feasible": feasible,
            }

        return {
            "frontier_points": [_point_to_pct(p) for p in self.frontier_points],
            "current_portfolio": {
                "volatility_pct": round(self.current_portfolio["volatility"] * 100, 2),
                "expected_return_pct": round(self.current_portfolio["expected_return"] * 100, 2),
            },
            "min_variance": _point_to_pct(self.min_variance_point),
            "max_return": _point_to_pct(self.max_return_point),
            "meta": {
                "n_feasible": self.n_feasible,
                "n_requested": self.n_requested,
                "computation_time_s": round(self.computation_time_s, 1),
                "analysis_date": self.analysis_date.isoformat(),
            },
        }

    def get_summary(self) -> Dict[str, Any]:
        """Summary dict for REST API envelope (matches OptimizationResult.get_summary())."""
        min_vol = self.min_variance_point.volatility if hasattr(self.min_variance_point, 'volatility') else self.min_variance_point.get("volatility", 0)
        max_ret = self.max_return_point.expected_return if hasattr(self.max_return_point, 'expected_return') else self.max_return_point.get("expected_return", 0)
        return {
            "type": "efficient_frontier",
            "n_frontier_points": self.n_feasible,
            "n_requested": self.n_requested,
            "min_variance_volatility_pct": round(min_vol * 100, 2),
            "max_return_pct": round(max_ret * 100, 2),
            "current_portfolio_volatility_pct": round(self.current_portfolio.get("volatility", 0) * 100, 2),
            "current_portfolio_return_pct": round(self.current_portfolio.get("expected_return", 0) * 100, 2),
            "computation_time_s": round(self.computation_time_s, 1),
        }
```

### 3. MCP Tool: `mcp_tools/optimization.py` addition

Add `compute_efficient_frontier()` tool alongside existing `run_optimization()`. Must use `standardize_portfolio_input()` to convert shares/dollars to weights (same as existing `optimize_min_variance()` / `optimize_max_return()` entry points).

```python
@handle_mcp_errors
def get_efficient_frontier(
    user_email: Optional[str] = None,
    portfolio_name: str = "CURRENT_PORTFOLIO",
    n_points: int = 15,
    use_cache: bool = True,
) -> dict:
    """
    Compute the efficient frontier for your portfolio.

    Sweeps across risk levels from minimum-variance to maximum-return,
    finding the optimal portfolio at each risk target. Returns frontier
    points (risk, return) plus your current portfolio position.

    Auto-generates missing expected returns via ReturnsService if needed.
    """
    user, user_id, portfolio_data = _load_portfolio_for_analysis(
        user_email, portfolio_name, use_cache=use_cache
    )

    # Load risk limits
    risk_limits_data = RiskLimitsManager(
        use_database=True, user_id=user_id
    ).load_risk_limits(portfolio_name)
    if risk_limits_data is None or risk_limits_data.is_empty():
        return {"status": "error", "error": "No risk limits configured."}

    # Ensure expected returns coverage via ReturnsService (same as REST max-return
    # path, app.py:3116). Handles auto-generation, cash proxy tickers (SGOV etc),
    # and temporary returns transparently.
    from services.returns_service import ReturnsService
    from inputs.portfolio_manager import PortfolioManager
    pm = PortfolioManager(use_database=True, user_id=user_id)
    returns_service = ReturnsService(portfolio_manager=pm)
    coverage_result = returns_service.ensure_returns_coverage(
        portfolio_name=portfolio_name, auto_generate=True,
    )
    if not coverage_result["success"]:
        return {
            "status": "error",
            "error": "Expected returns auto-generation failed. "
                     "Check portfolio tickers and try estimate_expected_returns manually."
        }
    expected_returns = returns_service.get_complete_returns(portfolio_name)
    if not expected_returns:
        return {
            "status": "error",
            "error": "No expected returns available after auto-generation."
        }
    portfolio_data.expected_returns = expected_returns

    # Resolve config (same pattern as optimize_min_variance / optimize_max_return)
    from portfolio_risk_engine.config_adapters import resolve_portfolio_config, resolve_risk_config
    config, _ = resolve_portfolio_config(portfolio_data)
    risk_cfg = resolve_risk_config(risk_limits_data)

    # Standardize weights (shares/dollars → weights via live prices)
    from portfolio_risk_engine.portfolio_config import standardize_portfolio_input, latest_price
    fmp_ticker_map = config.get("fmp_ticker_map")
    currency_map = config.get("currency_map")
    instrument_types_cfg = config.get("instrument_types")
    price_fetcher = lambda t: latest_price(
        t, fmp_ticker_map=fmp_ticker_map,
        currency=currency_map.get(t) if currency_map else None,
        instrument_types=instrument_types_cfg,
    )
    standardized = standardize_portfolio_input(
        config["portfolio_input"], price_fetcher,
        currency_map=currency_map, fmp_ticker_map=fmp_ticker_map,
    )
    weights = standardized["weights"]

    # Clamp n_points
    n_points = max(5, min(30, n_points))

    # Compute frontier
    import time
    t0 = time.monotonic()

    from portfolio_risk_engine.efficient_frontier import compute_efficient_frontier as _compute
    result_data = _compute(
        weights=weights,
        config=config,
        risk_config=risk_cfg,
        proxies=config["stock_factor_proxies"],
        expected_returns=expected_returns,
        fmp_ticker_map=fmp_ticker_map,
        instrument_types=instrument_types_cfg,
        n_points=n_points,
    )
    elapsed = time.monotonic() - t0

    # Build result object
    from core.result_objects.efficient_frontier import EfficientFrontierResult
    result = EfficientFrontierResult(
        frontier_points=result_data["frontier_points"],
        current_portfolio=result_data["current_portfolio"],
        min_variance_point=result_data["min_variance_point"],
        max_return_point=result_data["max_return_point"],
        n_feasible=result_data["n_feasible"],
        n_requested=result_data["n_requested"],
        computation_time_s=elapsed,
    )

    return {"status": "success", **result.to_api_response()}
```

### 4. Service Layer: `services/optimization_service.py`

Add `compute_efficient_frontier()` method to the existing `OptimizationService`, following the same caching pattern as `optimize_minimum_variance()`:

```python
# In OptimizationService class:

def compute_efficient_frontier(
    self, portfolio_data: PortfolioData,
    risk_limits_data: RiskLimitsData | None = None,
    risk_file: str = "risk_limits.yaml",
    n_points: int = 15,
) -> EfficientFrontierResult:
    """
    Compute efficient frontier with cache keyed on portfolio + risk content.
    Follows same pattern as optimize_minimum_variance() — cache key from
    portfolio_data.get_cache_key() + risk_limits_data.get_cache_key().
    Uses existing self._cache (TTLCache from SERVICE_CACHE_TTL).
    """
    # Regenerate cache key after caller has mutated expected_returns/proxies.
    # PortfolioData._cache_key is generated at __init__ time and doesn't auto-refresh
    # on attribute assignment. Existing optimize_minimum_variance() has the same
    # limitation — cache key reflects initial load, not post-mutation state.
    # We explicitly regenerate here so expected_returns/proxies are reflected.
    portfolio_data._cache_key = portfolio_data._generate_cache_key()
    risk_cache_key = risk_limits_data.get_cache_key() if risk_limits_data else risk_file
    cache_key = f"frontier_{portfolio_data.get_cache_key()}_{risk_cache_key}_{n_points}"

    with self._lock:
        if self.cache_results and cache_key in self._cache:
            return self._cache[cache_key]

    # Guard: expected returns required (caller must set before calling)
    if not portfolio_data.expected_returns:
        raise ValueError(
            "Expected returns required for efficient frontier. "
            "Set portfolio_data.expected_returns before calling service."
        )

    effective_risk_limits = (
        risk_limits_data
        if risk_limits_data and not risk_limits_data.is_empty()
        else risk_file
    )

    # Resolve config + standardize + compute (same as run_min_variance / run_max_return)
    from portfolio_risk_engine.config_adapters import resolve_portfolio_config, resolve_risk_config
    config, _ = resolve_portfolio_config(portfolio_data)
    risk_cfg = resolve_risk_config(effective_risk_limits)

    # Standardize weights
    from portfolio_risk_engine.portfolio_config import standardize_portfolio_input, latest_price
    fmp_ticker_map = config.get("fmp_ticker_map")
    currency_map = config.get("currency_map")
    instrument_types_cfg = config.get("instrument_types")
    price_fetcher = lambda t: latest_price(
        t, fmp_ticker_map=fmp_ticker_map,
        currency=currency_map.get(t) if currency_map else None,
        instrument_types=instrument_types_cfg,
    )
    standardized = standardize_portfolio_input(
        config["portfolio_input"], price_fetcher,
        currency_map=currency_map, fmp_ticker_map=fmp_ticker_map,
    )

    import time
    t0 = time.monotonic()
    from portfolio_risk_engine.efficient_frontier import compute_efficient_frontier as _compute
    result_data = _compute(
        weights=standardized["weights"],
        config=config, risk_config=risk_cfg,
        proxies=config["stock_factor_proxies"],
        expected_returns=portfolio_data.expected_returns or {},
        fmp_ticker_map=fmp_ticker_map,
        instrument_types=instrument_types_cfg,
        n_points=n_points,
    )
    elapsed = time.monotonic() - t0

    from core.result_objects.efficient_frontier import EfficientFrontierResult
    result = EfficientFrontierResult(
        frontier_points=result_data["frontier_points"],
        current_portfolio=result_data["current_portfolio"],
        min_variance_point=result_data["min_variance_point"],
        max_return_point=result_data["max_return_point"],
        n_feasible=result_data["n_feasible"],
        n_requested=result_data["n_requested"],
        computation_time_s=elapsed,
    )

    if self.cache_results:
        with self._lock:
            self._cache[cache_key] = result

    return result
```

### 5. REST Endpoint: `app.py`

Follow the existing `_run_min_variance_workflow()` + per-user service pattern. Uses `get_user_optimization_service(user)` for user-isolated caching, `ReturnsService.ensure_returns_coverage()` for expected returns, and the standard response envelope.

**Request model** (inline in `app.py`, same pattern as `OptimizationRequest` at line 580):
```python
class EfficientFrontierRequest(BaseModel):
    portfolio_name: str = "CURRENT_PORTFOLIO"
    n_points: int = Field(default=15, ge=5, le=30)
```

**Response model** (in `models/response_models.py`, matching MinVarianceResponse/MaxReturnResponse envelope):
```python
class EfficientFrontierResponse(BaseModel):
    success: bool
    optimization_results: Dict[str, Any]  # from EfficientFrontierResult.to_api_response()
    summary: Dict[str, Any]               # from EfficientFrontierResult.get_summary()
    portfolio_metadata: Dict[str, Any]
    risk_limits_metadata: Dict[str, Any]
```

Also add to `models/__init__.py` re-exports.

**Workflow helper + endpoint**:
```python
def _run_efficient_frontier_workflow(
    frontier_request: EfficientFrontierRequest,
    user: dict,
    optimization_service: OptimizationService,
) -> Dict[str, Any]:
    """Workflow helper for efficient frontier (runs in threadpool)."""
    portfolio_name = frontier_request.portfolio_name
    pm = PortfolioManager(use_database=True, user_id=user['user_id'])
    pd = pm.load_portfolio_data(portfolio_name)

    # Ensure factor proxies (same as _run_min_variance_workflow)
    from services.factor_proxy_service import ensure_factor_proxies
    pd.stock_factor_proxies = ensure_factor_proxies(
        user['user_id'], portfolio_name, set(pd.portfolio_input.keys()),
        allow_gpt=True,
        **({"instrument_types": getattr(pd, "instrument_types", None)}
           if getattr(pd, "instrument_types", None) else {}),
    )

    # Ensure expected returns coverage (same as max-return path, app.py:3116)
    from services.returns_service import ReturnsService
    returns_service = ReturnsService(portfolio_manager=pm)
    coverage_result = returns_service.ensure_returns_coverage(
        portfolio_name=portfolio_name, auto_generate=True,
    )
    if not coverage_result["success"]:
        # Match max-return coverage failure pattern (app.py:3142-3155)
        raise HTTPException(
            status_code=422,
            detail={
                "message": f"Cannot compute efficient frontier: {coverage_result.get('warnings', ['Incomplete expected returns coverage'])}",
                "error_code": ErrorCodes.INVALID_PARAMETER,
                "details": {
                    'coverage_analysis': coverage_result.get("final_coverage", {}),
                    'missing_returns': True,
                    'optimization_type': 'efficient_frontier',
                },
            },
        )
    pd.expected_returns = returns_service.get_complete_returns(portfolio_name)

    # Load risk limits (with fallback, matching app.py:3053-3061)
    risk_config_manager = RiskLimitsManager(use_database=True, user_id=user['user_id'])
    risk_limits_name = None
    try:
        risk_limits_data = risk_config_manager.load_risk_limits(portfolio_name)
        risk_limits_name = risk_limits_data.name
    except Exception as e:
        from utils.logging import portfolio_logger
        portfolio_logger.warning(f"Database connection failed for user {user['user_id']}: {e}")
        risk_limits_name = "Default (Fallback)"
        risk_limits_data = None

    result = optimization_service.compute_efficient_frontier(
        pd, risk_limits_data=risk_limits_data,
        n_points=frontier_request.n_points,
    )

    # Return envelope matching existing optimization endpoints (app.py:3072)
    return {
        'success': True,
        'optimization_results': result.to_api_response(),
        'summary': result.get_summary(),
        'portfolio_metadata': {
            'name': portfolio_name,
            'user_id': user['user_id'],
            'source': 'database',
            'analyzed_at': datetime.now(UTC).isoformat(),
        },
        'risk_limits_metadata': {
            'name': risk_limits_name,
            'source': 'database' if risk_limits_name not in ['Default', 'Default (Fallback)'] else 'file',
        },
    }


@app.post("/api/efficient-frontier", response_model=get_response_model(EfficientFrontierResponse))
@limiter.limit("50 per day;100 per day;250 per day")
async def api_efficient_frontier(
    request: Request,
    frontier_request: EfficientFrontierRequest,
    user: dict = Depends(get_current_user),
    api_key: str = Depends(get_api_key),
    optimization_service: OptimizationService = Depends(
        lambda user=Depends(get_current_user): get_user_optimization_service(user)
    ),
):
    """API endpoint for efficient frontier computation."""
    user_tier = TIER_MAP.get(api_key, "public")
    portfolio_name = frontier_request.portfolio_name

    try:
        response_payload = await run_in_threadpool(
            _run_efficient_frontier_workflow,
            frontier_request, user, optimization_service,
        )
        log_request("EFFICIENT_FRONTIER", "API", "EXECUTE", api_key, "react", "success", user_tier)
        return response_payload

    except HTTPException:
        raise  # Let 422 (coverage failure) pass through
    except Exception as e:
        from inputs.exceptions import PortfolioNotFoundError
        if isinstance(e, (ValidationError, ValueError)) and "returns" in str(e).lower():
            raise HTTPException(
                status_code=422,
                detail={
                    "message": str(e),
                    "error_code": ErrorCodes.INVALID_PARAMETER,
                    "endpoint": "efficient-frontier",
                },
            )
        if isinstance(e, PortfolioNotFoundError):
            raise HTTPException(
                status_code=404,
                detail={
                    "message": f"Portfolio '{portfolio_name}' not found",
                    "error_code": ErrorCodes.PORTFOLIO_NOT_FOUND,
                    "endpoint": "efficient-frontier",
                },
            )
        log_error("EFFICIENT_FRONTIER", "API error", context=str(e), tier=user_tier)
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Failed to compute efficient frontier",
                "error_code": ErrorCodes.ANALYSIS_ERROR,
                "endpoint": "efficient-frontier",
            },
        )
```

### Phase 2 Sketches (Frontend — separate plan)

The sections below are preliminary sketches for Phase 2 planning. The actual implementation requires exploring the ScenarioAnalysis/Orchestration architecture first.

#### Frontend: `EfficientFrontierChart.tsx`

Recharts `ComposedChart` with:
- **Line** (blue curve) — frontier points connected
- **Scatter** (single red dot) — current portfolio position
- **Scatter** (labeled) — min-variance and max-return endpoints
- **Tooltip** — hover shows vol%, return%, label
- **X-axis**: Volatility (%)
- **Y-axis**: Expected Return (%)

```tsx
import { ComposedChart, Line, Scatter, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts"

interface FrontierPoint {
  volatility_pct: number
  expected_return_pct: number
  label: string
}

interface EfficientFrontierChartProps {
  frontierPoints: FrontierPoint[]
  currentPortfolio: { volatility_pct: number; expected_return_pct: number }
  minVariance: { volatility_pct: number; expected_return_pct: number }
  maxReturn: { volatility_pct: number; expected_return_pct: number }
}

export function EfficientFrontierChart({ ... }: EfficientFrontierChartProps) {
  // Frontier curve as line data
  // Current portfolio as scatter overlay
  // Min-var and max-return as labeled scatter points
}
```

#### Frontend Hook

Follow the `usePortfolioOptimization` pattern (SessionManager / AdapterRegistry flow):

```ts
// frontend/packages/connectors/src/features/optimize/hooks/useEfficientFrontier.ts
export function useEfficientFrontier(portfolioName: string) {
  // POST /api/efficient-frontier via SessionManager
  // Long timeout (120s) since computation is slow
  // Returns { data, loading, error, refetch }
  // Triggered by explicit "Compute Frontier" button (not auto)
}
```

#### Integration: OptimizationsTab

Add frontier chart section below the existing optimization results table. Show a "Compute Frontier" button (since it's expensive, ~45-60s) rather than auto-computing. Loading state shows progress indicator.

## Sequencing

**Phase 1 — Backend (this plan):**
1. `efficient_frontier.py` — core engine
2. `EfficientFrontierResult` — result object
3. `OptimizationService.compute_efficient_frontier()` — service layer with content-keyed caching
4. `EfficientFrontierRequest` / `EfficientFrontierResponse` — response models
5. MCP tool + REST endpoint (per-user service, returns coverage, response envelope)
6. Unit tests

**Phase 2 — Frontend (separate plan, requires architecture exploration):**
Architecture notes for Phase 2 planning:
- `OptimizationsTab` rendered in `ScenarioAnalysis.tsx:355`, NOT `ScenarioAnalysisContainer`
- Tab props flow through `useScenarioOrchestration.ts:166`
- `usePortfolioOptimization` auto-runs on mount; frontier hook should be button-triggered (expensive)
- Types in `api.ts` depend on OpenAPI generated components; need `openapi-schema.json` update
- Hook/adapter/manager must be re-exported through barrel files (`hooks/index.ts`, `connectors/index.ts`)
- Chart component, hook+adapter, manager method, OptimizationsTab integration

## Dependencies

- **Expected returns.** Both MCP and REST paths use `ReturnsService.ensure_returns_coverage(auto_generate=True)` to auto-generate missing returns using industry ETF methodology. Coverage failure (structured `success=False`) → MCP returns error, REST returns 422. Runtime exceptions from ReturnsService (e.g., `ValidationError`) → MCP returns error, REST returns 422 (caught in error handler).
- **Risk limits must be configured.** The frontier respects existing risk constraints.
- **`standardize_portfolio_input()` required.** Raw `portfolio_input` from DB contains shares/dollars, not weights. Must convert via live price fetcher before passing to the solver — same requirement as existing `optimize_min_variance()` / `optimize_max_return()`.

## Performance

- **15 points × ~3s each = ~45s** total (dominated by CVXPY solver calls)
- Covariance, betas, proxy caps computed once via `_extract_problem_data()` (not 15×)
- `build_portfolio_view()` called once (not per-point) — this is the expensive FMP data fetch
- **`cp.Parameter` for vol budget** — DPP-compliant (`quad_form ≤ param`), so problem structure reused across solves. Combined with `warm_start=True` for efficient sequential solves.
- **Service-level caching** (30-min TTL) should be added since positions/returns don't change frequently. Use same cache pattern as `PortfolioService.analyze_risk_score()`.

## Testing

1. Unit: `compute_efficient_frontier()` with synthetic Σ + returns → monotonically increasing return along the frontier
2. Unit: `EfficientFrontierResult.to_api_response()` produces valid JSON with `_pct` fields
3. Unit: All expected returns = 0 → returns only min-var point (no max-return solve attempted)
4. Unit: Near-constant mu (range < 1e-6) → returns only min-var point (degenerate guard)
5. Unit: σ_min ≈ σ_max (flat frontier) → returns ~2 points, no sweep
6. Unit: Numerical failure at intermediate point → logged as warning, other points still returned
7. Unit: `_validate_endpoint_weights()` logs warning when proxy cap violated beyond 1% tolerance
9. Unit: Single ticker with max_weight < 1 → raises infeasible (not a single-point frontier)
10. Unit: Service method raises ValueError when `portfolio_data.expected_returns` is empty
11. Integration: MCP tool with live portfolio → auto-generates returns, returns success with frontier points
12. Integration: REST endpoint returns 200 with valid JSON
13. Integration: MCP tool with failed auto-generation → returns error with clear message
14. Integration: REST endpoint with failed coverage (structured failure) → returns 422
15. Integration: REST endpoint with ReturnsService ValidationError → returns 422

## Out of Scope

- **Unconstrained frontier**: We only compute the constrained frontier (respecting risk limits). The unconstrained Markowitz frontier is a separate exercise.
- **Individual asset points**: Plotting each individual asset on the risk-return plane alongside the frontier. Nice-to-have for Phase 2.
- **Tangent portfolio / Capital Market Line**: Requires risk-free rate; could add later.
- **Weight detail endpoint**: Clicking a frontier point to see its full weight allocation. Could add in Phase 2.
- **Refactor shared constraint builder**: The constraint logic is currently mirrored between `efficient_frontier.py` and `portfolio_optimizer.py`. A future refactor can extract `_build_shared_constraints()` into a shared module. Not worth the churn for v1 since the logic is small and stable.

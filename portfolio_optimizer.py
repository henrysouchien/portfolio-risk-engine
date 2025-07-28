#!/usr/bin/env python
# coding: utf-8

# In[1]:


from typing import Optional, Dict, Any, Tuple
import cvxpy as cp
import pandas as pd
from copy import deepcopy

import pandas as pd

from portfolio_risk      import build_portfolio_view, normalize_weights
from run_portfolio_risk  import (
    evaluate_portfolio_risk_limits,
    evaluate_portfolio_beta_limits,
)

from risk_helpers import (
    compute_max_betas,
    get_worst_monthly_factor_losses,
    aggregate_worst_losses_by_factor_type,
)

from helpers_display import _drop_factors

# Add logging decorator imports
from utils.logging import (
    log_workflow_state_decorator,
    log_resource_usage_decorator,
    log_performance,
    log_error_handling
)


# In[17]:


# ─── File: portfolio_optimizer.py ──────────────────────────────────────────
"""
Light-weight optimisation helpers that bolt onto the existing risk-runner.

Requires:
    pip install cvxpy

Functions
---------
simulate_portfolio_change(weights, edits, risk_cfg, start, end, proxies)
    → returns (summary, df_risk, df_beta)

solve_min_variance_with_risk_limits(weights, risk_cfg, start, end, proxies)
    → returns new_weights OR raises ValueError if infeasible
"""

# ────────────────────────────────────────────────────────────────────────────
@log_error_handling("medium")
@log_performance(5.0)
def simulate_portfolio_change(
    weights: Dict[str, float],
    edits: Dict[str, float],
    risk_cfg: Dict[str, Any],
    start: str,
    end: str,
    proxies: Dict[str, Dict[str, Any]],
):
    """
    Build a *new* summary after applying `edits` (delta-weights).
    `edits` can add new tickers or override existing weights.

    Example:
        new_summary, df_risk, df_beta = simulate_portfolio_change(
            weights,
            edits={"MSFT": +0.05, "AAPL": -0.02},
            ...
        )
    """
    new_w = deepcopy(weights)
    for tkr, w in edits.items():
        new_w[tkr] = new_w.get(tkr, 0.0) + w

    # normalize
    new_w = normalize_weights(new_w)

    summary = build_portfolio_view(
        new_w, start, end, expected_returns=None, stock_factor_proxies=proxies
    )

    df_risk = evaluate_portfolio_risk_limits(
        summary,
        risk_cfg["portfolio_limits"],
        risk_cfg["concentration_limits"],
        risk_cfg["variance_limits"],
    )

    max_betas = compute_max_betas(
        proxies, 
        start, 
        end, 
        loss_limit_pct=risk_cfg["max_single_factor_loss"]
    )
    
    df_beta = evaluate_portfolio_beta_limits(summary["portfolio_factor_betas"], max_betas)

    return summary, df_risk, df_beta


# ────────────────────────────────────────────────────────────────────────────
@log_error_handling("high")
@log_workflow_state_decorator("portfolio_optimization")
@log_resource_usage_decorator(monitor_memory=True, monitor_cpu=True)
@log_performance(10.0)
def solve_min_variance_with_risk_limits(
    weights: Dict[str, float],
    risk_cfg: Dict[str, Any],
    start: str,
    end: str,
    proxies: Dict[str, Dict[str, Any]],
    allow_short: bool = False,
):
    """
    Solves minimum variance portfolio optimization subject to comprehensive risk constraints.
    
    Finds the portfolio allocation that minimizes variance (w^T Σ w) while satisfying:
    • Concentration limits (max single position size)
    • Factor beta limits (market, momentum, value) 
    • Industry-specific proxy beta limits (per ETF/peer basket)
    • Portfolio volatility limits (annualized)
    • Optional long-only constraint
    
    The optimizer correctly prioritizes lowest-risk assets (e.g., SGOV government bonds)
    and will allocate maximum allowable amounts to assets with minimal volatility 
    and factor exposures, subject to concentration limits.

    Mathematical Formulation
    ------------------------
    minimize:    w^T Σ w                           (portfolio variance)
    subject to:  Σ w_i = 1                        (fully invested)
                 |w_i| ≤ c_max                     (concentration limit)
                 |Σ w_i β_i,f| ≤ β_max,f           (factor beta limits)
                 |Σ w_i β_i,p| ≤ β_max,p           (per-proxy beta limits) 
                 √(12 w^T Σ w) ≤ σ_max             (annualized volatility)
                 w_i ≥ 0 (if long_only=True)       (no short positions)

    Parameters
    ----------
    weights : Dict[str, float]
        Current portfolio weights (used to define asset universe and covariance estimation)
    risk_cfg : Dict[str, Any]
        Parsed risk_limits.yaml containing:
        - portfolio_limits: {max_volatility}
        - concentration_limits: {max_single_stock_weight}  
        - max_single_factor_loss: loss limit for beta calculations
    start, end : str
        Historical window (YYYY-MM-DD) for covariance and beta estimation
    proxies : Dict[str, Dict[str, Any]]
        Asset-to-proxy mapping from portfolio.yaml stock_factor_proxies
    allow_short : bool, default False
        If True, allows negative weights (long/short optimization)

    Returns
    -------
    Dict[str, float]
        Optimized portfolio weights summing to 1.0

    Raises
    ------
    ValueError
        If optimization problem is infeasible under given constraints

    Notes
    -----
    - Uses monthly covariance matrix with proper √12 annualization for volatility
    - Industry beta constraints are applied per-proxy (not globally) to avoid
      over-constraining the system with worst-performing proxy limits
    - Solver: ECOS with QCP=True for second-order cone constraints
    - Expected result: High allocation to lowest-risk assets (bonds, low-beta stocks)
    """
    from portfolio_risk import normalize_weights
    from risk_helpers import get_worst_monthly_factor_losses
    import numpy as np
    
    # Pre-normalize weights for internal consistency
    normalized_weights = normalize_weights(weights, normalize=True)
    tickers = list(normalized_weights)
    n       = len(tickers)

    # Pre-compute covariance
    base_summary = build_portfolio_view(normalized_weights, start, end, None, proxies)
    Σ = base_summary["covariance_matrix"].loc[tickers, tickers].values

    # Limits for betas
    max_betas = compute_max_betas(
        proxies, 
        start, 
        end, 
        loss_limit_pct=risk_cfg["max_single_factor_loss"]
    )

    # Variables
    w = cp.Variable(n)

    # Objective: minimise portfolio variance wᵀ Σ w
    obj = cp.Minimize(cp.quad_form(w, Σ))

    cons = []

    # 1. Weights sum to 1 (fully invested)
    cons += [cp.sum(w) == 1]

    # 2. Concentration limit
    max_weight = risk_cfg["concentration_limits"]["max_single_stock_weight"]
    cons += [cp.abs(w) <= max_weight]

    if not allow_short:
        cons += [w >= 0]

    # 3. Factor beta limits (exclude industry - handled per-proxy)
    beta_mat = base_summary["df_stock_betas"].fillna(0.0).loc[tickers]  # shape n × factors
    for fac, max_b in max_betas.items():
        if fac not in beta_mat or fac == "industry":  # Skip industry - handled per-proxy
            continue
        cons += [
            cp.abs(beta_mat[fac].values @ w) <= max_b
        ]

    # 3b. Per-proxy beta constraints (industry-specific limits) - RE-ENABLED
    loss_lim = risk_cfg["max_single_factor_loss"]
    worst_proxy_loss = get_worst_monthly_factor_losses(proxies, start, end)
    
    proxy_caps = {
        proxy: (np.inf if loss >= 0 else loss_lim / loss)
        for proxy, loss in worst_proxy_loss.items()
    }
    
    # Build coefficient vectors for each proxy
    for proxy, cap in proxy_caps.items():
        coeff = []
        for t in tickers:
            this_proxy = proxies[t].get("industry")
            if this_proxy == proxy:
                coeff.append(beta_mat.loc[t, "industry"])
            else:
                coeff.append(0.0)
        
        coeff_array = np.array(coeff)
        if not np.allclose(coeff_array, 0):  # Only add constraint if non-zero
            cons += [cp.abs(coeff_array @ w) <= cap]

    # 4. Gross volatility limit (annualize monthly covariance properly)
    max_vol = risk_cfg["portfolio_limits"]["max_volatility"]
    cons += [cp.sqrt(cp.quad_form(w, Σ)) * np.sqrt(12) <= max_vol]

    prob = cp.Problem(obj, cons)
    prob.solve(solver=cp.ECOS, qcp=True, verbose=False)

    if prob.status not in ("optimal", "optimal_inaccurate"):
        raise ValueError(f"Infeasible under current limits (status={prob.status})")

    new_w = {t: float(w.value[i]) for i, t in enumerate(tickers)}
    return new_w


# In[18]:


# ─── File: portfolio_optimizer.py ──────────────────────────────────────────

# ---------------------------------------------------------------
#  WHAT-IF helper
# ---------------------------------------------------------------

from typing import Dict, Tuple
import pandas as pd

def run_what_if(
    base_weights: pd.Series,
    delta: Dict[str, float],
    risk_cfg: Dict,
    start_date: str,
    end_date: str,
    factor_proxies: Dict[str, Dict],
    *,           
    verbose: bool = True,
) -> Tuple[dict, pd.DataFrame, pd.DataFrame]:
    """
    Apply absolute weight shifts (`delta`) to `base_weights`, evaluate the
    resulting portfolio, and pretty-print a compact risk report.

    Parameters
    ----------
    base_weights : pd.Series
        Current portfolio weights (summing to 1.0).
    delta : dict
        {ticker: +shift or –shift}.  Shifts are *absolute* (e.g. +0.05 = +5 ppts).
    risk_cfg : dict
        Parsed risk-limits YAML (needs `portfolio_limits`, `concentration_limits`,
        `variance_limits`, `max_single_factor_loss`).
    start_date, end_date : str
        Analysis window (YYYY-MM-DD).
    factor_proxies : dict
        Mapping used by `simulate_portfolio_change`.
    verbose : bool, default **True**
    • **True**  → pretty-prints risk / beta tables (old behaviour).  
    • **False** → no console output; function only returns data frames.

    Returns
    -------
    summary : dict              # build_portfolio_view output
    risk_df : pd.DataFrame      # risk-limit check table
    beta_df : pd.DataFrame      # factor-beta check table
    """
    
    # 1) build new portfolio + tables
    summary, risk_df, beta_df = simulate_portfolio_change(
        base_weights, delta, risk_cfg,
        start_date, end_date, factor_proxies
    )

    # 2) optionally pretty-print
    if verbose:
        
        # --- fancy title --------------------------------------------------------
        delta_str = " / ".join(f"{v:+.0%} {k}" for k, v in delta.items())
        print(f"\n📐  What-if Risk Checks ({delta_str})\n")
    
        # --- risk table ---------------------------------------------------------
        pct = lambda x: f"{x:.1%}"
        print(risk_df.to_string(index=False,
                                formatters={"Actual": pct, "Limit": pct}))
    
        # --- beta table ---------------------------------------------------------
        print("\n📊  What-if Factor Betas\n")
        beta_df_disp = _drop_factors(beta_df)
    
        print(beta_df_disp.to_string(formatters={
            "portfolio_beta":    "{:.2f}".format,     # or "{:.2f}" if you prefer two decimals
            "max_allowed_beta":  "{:.2f}".format,
            "buffer":            "{:.2f}".format,
            "pass":              lambda x: "PASS" if x else "FAIL"
        }))

    return summary, risk_df, beta_df


# In[19]:


# ─── portfolio_optimizer.py ───────────────────────

# ---------------------------------------------------------------
#  Risk evaluation portfolio helper
# ---------------------------------------------------------------


import pandas as pd
from typing import Dict, Any, Tuple

def evaluate_weights(
    weights: Dict[str, float],
    risk_cfg: Dict[str, Any],
    start_date: str,
    end_date: str,
    proxies: Dict[str, Dict[str, Any]],
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Runs the standard risk + beta limit checks on a given weight dict.
    Returns (df_risk, df_beta) – no printing.
    """
    from portfolio_risk import build_portfolio_view
    from run_portfolio_risk import (
        evaluate_portfolio_risk_limits,
        evaluate_portfolio_beta_limits,
    )
    from risk_helpers import compute_max_betas

    summary = build_portfolio_view(
        weights, start_date, end_date,
        expected_returns=None, stock_factor_proxies=proxies
    )

    df_risk = evaluate_portfolio_risk_limits(
        summary,
        risk_cfg["portfolio_limits"],
        risk_cfg["concentration_limits"],
        risk_cfg["variance_limits"],
    )

    max_betas = compute_max_betas(
        proxies=proxies,
        start_date=start_date,
        end_date=end_date,
        loss_limit_pct=risk_cfg["max_single_factor_loss"],
    )

    df_beta = evaluate_portfolio_beta_limits(
        summary["portfolio_factor_betas"],
        max_betas,
    )
    return df_risk, df_beta


# In[21]:


# ─── File: portfolio_optimizer.py ───────────────────────

def print_what_if_report(
    *,
    summary_new: Dict[str, Any],
    summary_old: Dict[str, Any],  # Original portfolio for before/after comparison
    risk_new: pd.DataFrame,
    beta_f_new: pd.DataFrame,
    beta_p_new: pd.DataFrame,
    cmp_risk: pd.DataFrame,
    cmp_beta: pd.DataFrame,
):
    """
    Prints a CLI-friendly report for a what-if portfolio scenario.

    Includes:
        • Before/after portfolio weights comparison (if summary_old provided)
        • New portfolio risk checks
        • New factor and industry betas
        • Before/after diffs for risk and factor exposures

    All output is printed to stdout using fixed-width formatting.
    """
    
    print("\n📊 Portfolio Weights — Before vs After\n")
    
    # Get reference data for position labeling
    try:
        from run_portfolio_risk import get_cash_positions
        from utils.etf_mappings import get_etf_to_industry_map, format_ticker_with_label
        cash_positions = get_cash_positions()
        industry_map = get_etf_to_industry_map()
    except ImportError:
        cash_positions = set()
        industry_map = {}
    
    # Get weights from both portfolios
    old_weights = summary_old["allocations"]["Portfolio Weight"]
    new_weights = summary_new["allocations"]["Portfolio Weight"]
    
    # Combine all tickers and calculate changes
    all_tickers = set(old_weights.index) | set(new_weights.index)
    
    # Calculate adaptive column width
    max_width = 12  # minimum width
    changes_data = []
    
    for ticker in all_tickers:
        old_weight = old_weights.get(ticker, 0.0)
        new_weight = new_weights.get(ticker, 0.0)
        change = new_weight - old_weight
        
        # Only show positions that exist in at least one portfolio
        if abs(old_weight) > 0.001 or abs(new_weight) > 0.001:
            labeled_ticker = format_ticker_with_label(ticker, cash_positions, industry_map)
            max_width = max(max_width, len(labeled_ticker))
            changes_data.append((ticker, labeled_ticker, old_weight, new_weight, change))
    
    # Add padding
    max_width += 2
    
    # Print header
    print(f"{'Position':<{max_width}} {'Before':<8} {'After':<8} {'Change':<8}")
    print("─" * (max_width + 26))
    
    # Sort by absolute change (largest changes first)
    changes_data.sort(key=lambda x: abs(x[4]), reverse=True)
    
    # Print changes
    for ticker, labeled_ticker, old_weight, new_weight, change in changes_data:
        if abs(change) > 0.001:  # Only show meaningful changes
            change_str = f"{change:+.1%}" if abs(change) >= 0.001 else ""
            print(f"{labeled_ticker:<{max_width}} {old_weight:.1%}    {new_weight:.1%}    {change_str}")
    
    print()  # Add spacing

    print("\n📐  NEW Portfolio – Risk Checks\n")
    print(risk_new.to_string(index=False, formatters={
        "Actual": lambda x: f"{x:.1%}",
        "Limit":  lambda x: f"{x:.1%}",
    }))

    print("\n📊  NEW Aggregate Factor Exposures\n")
    print(beta_f_new.to_string(index_names=False, formatters={
        "portfolio_beta":   "{:.2f}".format,
        "max_allowed_beta": "{:.2f}".format,
        "buffer":           "{:.2f}".format,
        "pass":             lambda x: "PASS" if x else "FAIL",
    }))

    print("\n📊  NEW Industry Exposure Checks\n")
    print(beta_p_new.to_string(index_names=False, formatters={
        "portfolio_beta":   "{:.2f}".format,
        "max_allowed_beta": "{:.2f}".format,
        "buffer":           "{:.2f}".format,
        "pass":             lambda x: "PASS" if x else "FAIL",
    }))

    print("\n📐  Risk Limits — Before vs After\n")
    print(cmp_risk.to_string(index=False, formatters={
        "Old":   lambda x: f"{x:.1%}",
        "New":   lambda x: f"{x:.1%}",
        "Δ":     lambda x: f"{x:.1%}",
        "Limit": lambda x: f"{x:.1%}",
    }))

    print("\n📊  Factor Betas — Before vs After\n")
    print(cmp_beta.to_string(index_names=False, formatters={
        "Old":       "{:.2f}".format,
        "New":       "{:.2f}".format,
        "Δ":         "{:.2f}".format,
        "Max Beta":  "{:.2f}".format,
        "Old Pass":  lambda x: "PASS" if x else "FAIL",
        "New Pass":  lambda x: "PASS" if x else "FAIL",
    }))


# In[22]:


# ─── File: portfolio_optimizer.py ───────────────────────

# WHAT-IF DRIVER
#
# Input precedence
# ----------------
# 1. If `what_if_portfolio.yaml` contains a top-level `new_weights:` section
#    → treat as a full-replacement portfolio.
#      • `shift_dict` is ignored in this case.
#
# 2. Otherwise, build an incremental *delta* dict:
#      • YAML `delta:` values are parsed first.
#      • Any overlapping keys in `shift_dict` overwrite the YAML values.
#
# 3. Branch logic
#      • full-replacement  → evaluate_weights(new_weights_yaml)
#      • incremental tweak → run_what_if(base_weights, delta)
#
# 4. After computing the new portfolio’s risk/beta tables once,
#    we also compute the baseline (unchanged) tables once, then
#    show before-vs-after diffs.
#
# Note: No function ever writes back to the YAML file; all merges happen
#       in memory.
# ──────────────────────────────────────────────────────────────────────────────

def run_what_if_scenario(
    *,
    base_weights: Dict[str, float],
    config: Dict[str, Any],
    risk_config: Dict[str, Any],
    proxies: Dict[str, Any],
    shift_dict: Optional[Dict[str, str]] = None,
    scenario_yaml: Optional[str] = None,
):
    """
    Runs a portfolio what-if scenario and returns the full risk report.

    Accepts either a YAML file or an inline delta dictionary to simulate portfolio changes,
    then compares the updated risk profile to the current baseline. Outputs include
    updated risk metrics, factor exposures, and before/after comparisons.

    Input precedence:
        1. If `scenario_yaml` contains a top-level `new_weights:` section,
           it is treated as a full-replacement portfolio.
        2. Otherwise, the function looks for a `delta:` section in the YAML.
        3. If neither is found or YAML is missing keys, `shift_dict` is used as a fallback or override.

    This function does not return any data. It prints:
        • NEW portfolio risk checks (volatility, concentration, variance share)
        • NEW factor and industry beta exposures (vs. max allowed betas)
        • BEFORE vs AFTER comparison of key risk metrics
        • BEFORE vs AFTER comparison of factor beta pass/fail status

    Parameters
    ----------
    base_weights : dict
        Current portfolio weights (must sum to 1.0).
    config : dict
        Parsed contents of `portfolio.yaml`. Must include:
        - start_date : str (YYYY-MM-DD)
        - end_date   : str (YYYY-MM-DD)
    risk_config : dict
        Parsed contents of `risk_limits.yaml`, including:
        - portfolio_limits
        - concentration_limits
        - variance_limits
        - max_single_factor_loss
    proxies : dict
        Mapping from tickers to their factor proxies (from `portfolio.yaml`).
    shift_dict : dict, optional
        Inline dictionary of weight changes to apply. Format: {"TICKER": "+500bp"}.
        Used as fallback if YAML is missing or incomplete.
    scenario_yaml : str, optional
        Path to a YAML file that contains either `new_weights:` or `delta:`. Overrides shift_dict if populated.

    Raises
    ------
    ValueError
        If neither `scenario_yaml` nor `shift_dict` provide any usable changes.

    Returns
    -------
    summary_new, risk_new, beta_new, cmp_risk, cmp_beta
    """
    from helpers_input import parse_delta
    from risk_helpers import calc_max_factor_betas
    from helpers_display import (
        compare_risk_tables,
        compare_beta_tables,
        _drop_factors,
    )
    from run_portfolio_risk import (
        evaluate_portfolio_risk_limits,
        evaluate_portfolio_beta_limits,
    )
    from portfolio_risk import build_portfolio_view, normalize_weights
    from portfolio_optimizer import run_what_if

    _fmt_pct = lambda x: f"{x:.1%}"
    _fmt_beta = {
        "portfolio_beta":   "{:.2f}".format,
        "max_allowed_beta": "{:.2f}".format,
        "buffer":           "{:.2f}".format,
        "pass":             lambda x: "PASS" if x else "FAIL",
    }

    # fallback-safe delta parse
    delta, new_weights = parse_delta(yaml_path=scenario_yaml, literal_shift=shift_dict)

    # get proxy-level beta caps
    from settings import PORTFOLIO_DEFAULTS
    lookback_years = PORTFOLIO_DEFAULTS.get('worst_case_lookback_years', 10)
    _, max_betas_by_proxy = calc_max_factor_betas(
        portfolio_yaml="portfolio.yaml",
        risk_yaml="risk_limits.yaml",
        lookback_years=lookback_years,
        echo=False
    )

    # construct summary_new
    if new_weights:
        new_weights = normalize_weights(new_weights)
        summary_new = build_portfolio_view(
            new_weights, config["start_date"], config["end_date"],
            expected_returns=None, stock_factor_proxies=proxies
        )
    else:
        summary_new, *_ = run_what_if(
            base_weights, delta, risk_config,
            config["start_date"], config["end_date"], proxies,
            verbose=False
        )

    # construct summary_base
    summary_base = build_portfolio_view(
        base_weights, config["start_date"], config["end_date"],
        expected_returns=None, stock_factor_proxies=proxies
    )

    # run risk tables
    def get_risk(summary):
        return evaluate_portfolio_risk_limits(
            summary,
            risk_config["portfolio_limits"],
            risk_config["concentration_limits"],
            risk_config["variance_limits"]
        )

    def get_betas(summary):
        from risk_helpers import compute_max_betas
        max_betas = compute_max_betas(
            proxies, config["start_date"], config["end_date"],
            loss_limit_pct=risk_config["max_single_factor_loss"]
        )
        return evaluate_portfolio_beta_limits(
            summary["portfolio_factor_betas"],
            max_betas,
            proxy_betas=summary["industry_variance"]["per_industry_group_beta"],
            max_proxy_betas=max_betas_by_proxy
        )

    risk_new  = get_risk(summary_new)
    risk_base = get_risk(summary_base)
    beta_new  = get_betas(summary_new)
    beta_base = get_betas(summary_base)

    # compare diffs
    cmp_risk = (
        compare_risk_tables(risk_base, risk_new)
        .set_index("Metric")
        .loc[risk_new["Metric"]]
        .reset_index()
    )
    cmp_beta = compare_beta_tables(beta_base, beta_new)
    cmp_beta = _drop_factors(cmp_beta)
    cmp_beta = cmp_beta[~cmp_beta.index.str.startswith("industry_proxy::")]

    return summary_new, risk_new, beta_new, cmp_risk, cmp_beta


# In[20]:


# ─── File: portfolio_optimizer.py ──────────────────────────────────

# ---------------------------------------------------------------
#  Minimum variance portfolio helper
# ---------------------------------------------------------------

from typing import Dict, Any
import pandas as pd

@log_error_handling("high")
@log_workflow_state_decorator("minimum_variance_optimization")
@log_resource_usage_decorator(monitor_memory=True, monitor_cpu=True)
@log_performance(10.0)
def run_min_var_optimiser(
    weights: Dict[str, float],
    risk_cfg: Dict[str, Any],
    start_date: str,
    end_date:   str,
    proxies: Dict[str, Dict[str, Any]],
    echo: bool = True,
) -> Dict[str, float]:
    """
    Minimum-variance portfolio under firm-wide limits
    ------------------------------------------------

    Objective
    ---------
    **min wᵀ Σ w**  
    Σ = monthly covariance estimated over *start_date*→*end_date*.

    Constraints
    -----------
    1. ∑ wᵢ = 1  (fully invested)  
    2. wᵢ ≥ 0  (long-only; see lower-level solver for shorts)  
    3. |wᵢ| ≤ single-name cap from *risk_cfg*  
    4. √12 · √(wᵀ Σ w) ≤ σ_cap  
    5. |β_port,f| ≤ dynamic β_max,f (via `compute_max_betas`)

    Convex QP solved with CVXPY + ECOS.  
    Returns only the optimised weights; use `evaluate_weights(...)`
    if you need PASS/FAIL tables.

    Parameters
    ----------
    weights : {ticker: weight} (sums ≈ 1)  
    risk_cfg : parsed *risk_limits.yaml*  
    start_date, end_date : YYYY-MM-DD window for Σ & betas  
    proxies : `stock_factor_proxies` from portfolio YAML  
    echo : print weights ≥ 0.01 % when True

    Returns
    -------
    Dict[str, float] – optimised weights (summing to 1)
    """
    
    # 1. ---------- solve ----------------------------------------------------
    new_w = solve_min_variance_with_risk_limits(
        weights,
        risk_cfg,
        start_date,
        end_date,
        proxies,
    )

    # 2. ---------- optional console output ---------------------------------
    if echo:
        # 3a. pretty-print weights ≥ 0.01 %
        print("\n🎯  Target minimum-variance weights:\n")
        (pd.Series(new_w, name="Weight")
           .loc[lambda s: s.abs() > 0.0001]
           .sort_values(ascending=False)
           .apply(lambda x: f"{x:.2%}")
           .pipe(lambda s: print(s.to_string()))
        )

    return new_w


# In[24]:


# ─── File: portfolio_optimizer.py ──────────────────────────────────

def run_min_var(
    *,
    base_weights: Dict[str, float],
    config: Dict[str, Any],
    risk_config: Dict[str, Any],
    proxies: Dict[str, Any],
) -> Tuple[Dict[str, float], pd.DataFrame, pd.DataFrame]:
    """
    Runs minimum-variance optimisation under risk constraints.

    Returns
    -------
    Tuple of:
        - optimised weights (dict)
        - risk check DataFrame
        - factor beta check DataFrame
    """
    # LOGGING: Add minimum variance optimization start logging
    # LOGGING: Add workflow state logging for optimization workflow here
    # LOGGING: Add resource usage monitoring for optimization process here
    # LOGGING: Add optimization algorithm timing
    # LOGGING: Add constraint validation logging
    # LOGGING: Add convergence tracking
    # LOGGING: Add solution quality logging
    from portfolio_optimizer import run_min_var_optimiser, evaluate_weights

    w_opt = run_min_var_optimiser(
        weights    = base_weights,
        risk_cfg   = risk_config,
        start_date = config["start_date"],
        end_date   = config["end_date"],
        proxies    = proxies,
        echo       = False,
    )

    risk_tbl, beta_tbl = evaluate_weights(
        w_opt, risk_config,
        config["start_date"], config["end_date"],
        proxies
    )
    # LOGGING: Add minimum variance optimization completion logging
    # LOGGING: Add workflow state logging for optimization workflow completion here
    # LOGGING: Add resource usage monitoring for optimization completion here
    return w_opt, risk_tbl, beta_tbl


# In[25]:


# ─── File: portfolio_optimizer.py ──────────────────────────────────

def print_min_var_report(
    *,
    weights: Dict[str, float],
    risk_tbl: pd.DataFrame,
    beta_tbl: pd.DataFrame,
    echo_weights: bool = True,
):
    """
    Prints risk and factor exposure tables for a min-var portfolio.

    Parameters
    ----------
    weights : dict
        Optimised portfolio weights (sum to 1).
    risk_tbl : pd.DataFrame
        Output from evaluate_portfolio_risk_limits.
    beta_tbl : pd.DataFrame
        Output from evaluate_portfolio_beta_limits.
    echo_weights : bool
        If True, prints weights ≥ 0.01%.
    """
    from helpers_display import _drop_factors

    if echo_weights:
        print("\n🎯  Target minimum-variance weights\n")
        for t, w in sorted(weights.items(), key=lambda kv: -abs(kv[1])):
            if abs(w) >= 0.0001:
                print(f"{t:<10} : {w:.2%}")

    print("\n📐  Optimised Portfolio – Risk Checks\n")
    pct = lambda x: f"{x:.2%}"
    print(risk_tbl.to_string(index=False, formatters={"Actual": pct, "Limit": pct}))

    print("\n📊  Optimised Portfolio – Factor Betas\n")
    beta_tbl = _drop_factors(beta_tbl)
    print(beta_tbl.to_string(formatters={
        "Beta":      "{:.2f}".format,
        "Max Beta":  "{:.2f}".format,
        "Buffer":    "{:.2f}".format,
        "Pass":      lambda x: "PASS" if x else "FAIL",
    }))


# In[26]:


# File: portfolio_optimizer.py

# ---------------------------------------------------------------------
# Max-return portfolio subject to risk limits
#   • Aggregate β caps: market, momentum, value
#   • Per-proxy β caps: one for each industry ETF / peer basket
# ---------------------------------------------------------------------
import cvxpy as cp
import numpy as np
import pandas as pd
from typing import Dict, Union, List

def solve_max_return_with_risk_limits(
    init_weights: Dict[str, float],
    risk_cfg: Dict[str, Dict[str, float]],
    start_date: str,
    end_date: str,
    stock_factor_proxies: Dict[str, Dict[str, Union[str, List[str]]]],
    expected_returns: Dict[str, float],
    allow_short: bool = False,
) -> Dict[str, float]:
    r"""Return the weight vector *w* that maximises expected portfolio return
    subject to **all** firm-wide risk limits.

    The problem is formulated as a convex quadratic programme (QP)::

        maximise   \sum_i w_i * µ_i
        subject to  w  \in  ℝⁿ
                    \sum_i w_i                = 1                 (fully-invested)
                    0 ≤ w_i ≤ w_cap           ∀ i  (long-only + concentration cap)
                    σ_p(w)                    ≤ σ_cap             (annual vol cap)
                    |β_port,f(w)|             ≤ β_cap,f           f ∈ {market,momentum,value}
                    |β_port,proxy(w)|         ≤ β_cap,proxy       ∀ industry proxies

    where ::

        µ_i       expected annual return of ticker *i* (``expected_returns``)
        σ_p(w)    √(12 * wᵀ Σ_m w)   – annualised portfolio volatility
        β_port,f  ∑_i w_i β_{i,f}    – portfolio beta to factor *f*
        β_port,proxy  constructed similarly using each industry ETF / peer basket

    Parameters
    ----------
    init_weights
        Current portfolio weights (need not sum to 1 – they’ll be re-normalised).
    risk_cfg
        Parsed ``risk_limits.yaml`` containing the three sub-dicts:
        ``portfolio_limits``, ``concentration_limits``, ``variance_limits`` and
        the scalar ``max_single_factor_loss``.
    start_date, end_date
        Historical window (YYYY-MM-DD) used for covariance and beta estimation.
    stock_factor_proxies
        Mapping ``{ticker: {market: 'SPY', momentum: 'MTUM', value: 'IWD',
        industry: 'SOXX', …}}``.  Only *industry* proxies are used for the
        per-proxy caps, but the full dict is passed for completeness.
    expected_returns
        Dict of expected **annual** returns (in decimals, eg 0.12 = 12 %).
        Missing tickers default to 0.
    allow_short
        If ``True`` the lower-bound on *w* is removed (long/short optimisation).

    Returns
    -------
    Dict[str, float]
        Optimised weight vector summing exactly to 1.  Keys match the order of
        ``init_weights``.

    Raises
    ------
    ValueError
        * If *expected_returns* is empty / all zeros.
        * If the optimisation is infeasible under the supplied risk limits.

    Notes
    -----
    *Factor & proxy beta caps*
        The aggregate caps for **market**, **momentum** and **value** factors are
        taken from :pyfunc:`risk_helpers.compute_max_betas`.  Per-industry caps
        are derived by dividing the firm-wide *max_single_factor_loss* by each
        proxy’s historical worst 1-month return (see
        :pyfunc:`risk_helpers.get_worst_monthly_factor_losses`).
    """
    from portfolio_risk import build_portfolio_view, normalize_weights          # reuse: get Σ & betas
    from risk_helpers   import compute_max_betas, get_worst_monthly_factor_losses

    # ---------- 0. Pre-normalize weights for internal consistency -----------
    # Always work with normalized weights (sum = 1) to ensure risk calculations
    # and constraints are consistent, regardless of external normalization settings
    normalized_weights = normalize_weights(init_weights, normalize=True)
    tickers = list(normalized_weights)
    
    view = build_portfolio_view(
        normalized_weights, start_date, end_date,
        expected_returns=None,
        stock_factor_proxies=stock_factor_proxies,
    )

    Σ_m = view["covariance_matrix"].loc[tickers, tickers].values          # Σ (monthly)
    β_tbl = view["df_stock_betas"].fillna(0.0).loc[tickers]               # n × factors

    μ = np.array([expected_returns.get(t, 0.0) for t in tickers])
    if np.allclose(μ, 0):
        raise ValueError("expected_returns is empty or zeros – nothing to maximise")

    # ---------- 1. Build β caps -------------------------------------------
    # 1a) Aggregate factors
    all_caps = compute_max_betas(
        stock_factor_proxies,
        start_date, end_date,
        loss_limit_pct=risk_cfg["max_single_factor_loss"],
    )
    agg_caps = {k: all_caps[k] for k in ("market", "momentum", "value")}

    # 1b) Per-industry proxy caps
    loss_lim = risk_cfg["max_single_factor_loss"]            # e.g. -0.10
    worst_proxy_loss = get_worst_monthly_factor_losses(
        stock_factor_proxies, start_date, end_date
    )
    proxy_caps = {
        proxy: (np.inf if loss >= 0 else loss_lim / loss)
        for proxy, loss in worst_proxy_loss.items()
    }

    # Build coefficient vectors c_proxy (length n) such that
    #   β_port,proxy = Σ_i c_proxy[i] · w_i
    coeff_proxy: Dict[str, np.ndarray] = {}
    for proxy in proxy_caps:
        coeff = []
        for t in tickers:
            this_proxy = stock_factor_proxies[t].get("industry")
            coeff.append(β_tbl.loc[t, "industry"] if this_proxy == proxy else 0.0)
        coeff_proxy[proxy] = np.array(coeff)

    # ---------- 2. CVXPY variables & objective ----------------------------
    w = cp.Variable(len(tickers))
    objective = cp.Maximize(μ @ w)

    # ---------- 3. Constraints -------------------------------------------
    cons = [cp.sum(w) == 1]                               # fully invested
    if not allow_short:
        cons += [w >= 0]

    # single-name cap
    cons += [w <= risk_cfg["concentration_limits"]["max_single_stock_weight"]]

    # portfolio vol cap (monthly Σ → annual σ)
    σ_cap = risk_cfg["portfolio_limits"]["max_volatility"]
    cons += [cp.sqrt(cp.quad_form(w, Σ_m)) * np.sqrt(12) <= σ_cap]

    # 3a) Aggregate β caps
    for fac, cap in agg_caps.items():
        if fac in β_tbl.columns:
            cons += [cp.abs(β_tbl[fac].values @ w) <= cap]

    # 3b) Per-proxy β caps
    for proxy, cap in proxy_caps.items():
        cons += [cp.abs(coeff_proxy[proxy] @ w) <= cap]

    # ---------- 4. Solve --------------------------------------------------
    prob = cp.Problem(objective, cons)
    prob.solve(solver=cp.ECOS, qcp=True, verbose=False)

    if prob.status not in ("optimal", "optimal_inaccurate"):
        raise ValueError(f"Solver status = {prob.status} (infeasible)")

    return {t: float(w.value[i]) for i, t in enumerate(tickers)}


# In[27]:


# File: portfolio_optimizer.py

def run_max_return_portfolio(
    *,
    weights: Dict[str, float],
    config: Dict[str, Any],
    risk_config: Dict[str, Any],
    proxies: Dict[str, Any],
) -> Tuple[Dict[str, float], Dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Runs max-return optimisation under risk constraints and returns full output.

    Returns:
        - Optimised weights (dict)
        - Portfolio summary (from build_portfolio_view)
        - Risk check table
        - Factor-level beta check table
        - Proxy-level beta check table
    """
    from portfolio_optimizer import solve_max_return_with_risk_limits
    from portfolio_risk import build_portfolio_view
    from run_portfolio_risk import (
        evaluate_portfolio_beta_limits,
        evaluate_portfolio_risk_limits,
    )
    from risk_helpers import compute_max_betas, calc_max_factor_betas

    # 1. Optimise weights
    w_opt = solve_max_return_with_risk_limits(
        init_weights         = weights,
        risk_cfg             = risk_config,
        start_date           = config["start_date"],
        end_date             = config["end_date"],
        stock_factor_proxies = proxies,
        expected_returns     = config["expected_returns"],
    )

    # 2. Build full summary
    summary = build_portfolio_view(
        w_opt,
        start_date           = config["start_date"],
        end_date             = config["end_date"],
        expected_returns     = None,
        stock_factor_proxies = proxies,
    )

    # 3. Run risk checks
    risk_tbl = evaluate_portfolio_risk_limits(
        summary,
        risk_config["portfolio_limits"],
        risk_config["concentration_limits"],
        risk_config["variance_limits"],
    )

    # 4. Compute β caps
    max_betas = compute_max_betas(
        proxies,
        config["start_date"],
        config["end_date"],
        loss_limit_pct = risk_config["max_single_factor_loss"],
    )
    from settings import PORTFOLIO_DEFAULTS
    lookback_years = PORTFOLIO_DEFAULTS.get('worst_case_lookback_years', 10)
    _, max_betas_by_proxy = calc_max_factor_betas(
        portfolio_yaml = "portfolio.yaml",
        risk_yaml      = "risk_limits.yaml",
        lookback_years = lookback_years,
        echo = False,
    )

    # 5. Run beta check with proxy caps
    df_beta_chk = evaluate_portfolio_beta_limits(
        summary["portfolio_factor_betas"],
        max_betas,
        proxy_betas     = summary["industry_variance"]["per_industry_group_beta"],
        max_proxy_betas = max_betas_by_proxy,
    )

    # 6. Split factor vs proxy
    df_factors = df_beta_chk[~df_beta_chk.index.str.startswith("industry_proxy::")]
    df_proxies = df_beta_chk[df_beta_chk.index.str.startswith("industry_proxy::")].copy()
    df_proxies.index = df_proxies.index.str.replace("industry_proxy::", "")

    return w_opt, summary, risk_tbl, df_factors, df_proxies


# In[28]:


# File: portfolio_optimizer.py

def print_max_return_report(
    *,
    weights: Dict[str, float],
    risk_tbl: pd.DataFrame,
    df_factors: pd.DataFrame,
    df_proxies: pd.DataFrame,
    echo_weights: bool = True,
):
    """
    Prints weights and all risk / beta check tables for max-return portfolio.
    """
    if echo_weights:
        print("\n🎯  Target max-return, risk-constrained weights\n")
        for k, v in sorted(weights.items(), key=lambda kv: -abs(kv[1])):
            if abs(v) > 1e-4:
                print(f"{k:<10} : {v:.2%}")

    print("\n📐  Max-return Portfolio – Risk Checks\n")
    pct = lambda x: f"{x:.2%}"
    print(risk_tbl.to_string(index=False, formatters={"Actual": pct, "Limit": pct}))

    print("\n📊  Aggregate Factor Exposures\n")
    fmt = {
        "portfolio_beta":   "{:.2f}".format,
        "max_allowed_beta": "{:.2f}".format,
        "buffer":           "{:.2f}".format,
        "pass":             lambda x: "PASS" if x else "FAIL",
    }
    print(df_factors.to_string(index_names=False, formatters=fmt))

    if not df_proxies.empty:
        print("\n📊  Industry Exposure Checks\n")
        print(df_proxies.to_string(index_names=False, formatters=fmt))


# In[ ]:





# In[ ]:





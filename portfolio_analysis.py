#!/usr/bin/env python3
# coding: utf-8

"""
Core portfolio analysis business logic.
Extracted from run_risk.py as part of the refactoring to create a clean service layer.
"""

import yaml
from typing import Dict, Any, Optional
from datetime import datetime

from run_portfolio_risk import (
    load_portfolio_config,
    standardize_portfolio_input,
    latest_price,
    evaluate_portfolio_risk_limits,
    evaluate_portfolio_beta_limits,
)
from portfolio_risk import build_portfolio_view
from risk_helpers import calc_max_factor_betas
from settings import PORTFOLIO_DEFAULTS

# Add logging decorator imports
from utils.logging import (
    log_portfolio_operation_decorator,
    log_performance,
    log_error_handling
)


@log_error_handling("high")
@log_portfolio_operation_decorator("portfolio_analysis")
@log_performance(3.0)
def analyze_portfolio(filepath: str) -> Dict[str, Any]:
    """
    Core portfolio analysis business logic.
    
    This function contains the pure business logic extracted from run_portfolio(),
    without any CLI or dual-mode concerns.
    
    Parameters
    ----------
    filepath : str
        Path to the portfolio YAML file.
        
    Returns
    -------
    Dict[str, Any]
        Structured portfolio analysis results containing:
        - portfolio_summary: Complete portfolio view from build_portfolio_view
        - risk_analysis: Risk limit checks and violations
        - beta_analysis: Factor beta checks and violations
        - analysis_metadata: Analysis configuration and timestamps
    """
    
    # ─── 1. Load YAML Inputs ─────────────────────────────
    config = load_portfolio_config(filepath)
    
    with open("risk_limits.yaml", "r") as f:
        risk_config = yaml.safe_load(f)

    weights = standardize_portfolio_input(config["portfolio_input"], latest_price)["weights"]
    
    # ─── 2. Build Portfolio View ─────────────────────────────
    summary = build_portfolio_view(
        weights,
        config["start_date"],
        config["end_date"],
        config.get("expected_returns"),
        config.get("stock_factor_proxies")
    )
    
    # ─── 3. Calculate Beta Limits ────────────────────────────
    lookback_years = PORTFOLIO_DEFAULTS.get('worst_case_lookback_years', 10)
    max_betas, max_betas_by_proxy = calc_max_factor_betas(
        portfolio_yaml=filepath,
        risk_yaml="risk_limits.yaml",
        lookback_years=lookback_years,
        echo=False  # Don't print helper tables when capturing output
    )
    
    # ─── 4. Run Risk Checks ──────────────────────────────────
    df_risk = evaluate_portfolio_risk_limits(
        summary,
        risk_config["portfolio_limits"],
        risk_config["concentration_limits"],
        risk_config["variance_limits"]
    )
    
    df_beta = evaluate_portfolio_beta_limits(
        portfolio_factor_betas=summary["portfolio_factor_betas"],
        max_betas=max_betas,
        proxy_betas=summary["industry_variance"].get("per_industry_group_beta"),
        max_proxy_betas=max_betas_by_proxy
    )
    
    # ─── 5. Return Structured Results ────────────────────────
    return {
        "portfolio_summary": summary,
        "risk_analysis": {
            "risk_checks": df_risk.to_dict('records'),
            "risk_passes": bool(df_risk['Pass'].all()),
            "risk_violations": df_risk[~df_risk['Pass']].to_dict('records'),
            "risk_limits": {
                "portfolio_limits": risk_config["portfolio_limits"],
                "concentration_limits": risk_config["concentration_limits"],
                "variance_limits": risk_config["variance_limits"]
            }
        },
        "beta_analysis": {
            "beta_checks": df_beta.reset_index().to_dict('records'),
            "beta_passes": bool(df_beta['pass'].all()),
            "beta_violations": df_beta[~df_beta['pass']].reset_index().to_dict('records'),
            "max_betas": max_betas,
            "max_betas_by_proxy": max_betas_by_proxy
        },
        "analysis_metadata": {
            "analysis_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "portfolio_file": filepath,
            "lookback_years": lookback_years,
            "weights": weights,
            "total_positions": len(weights),
            "active_positions": len([v for v in weights.values() if abs(v) > 0.001])
        }
    } 
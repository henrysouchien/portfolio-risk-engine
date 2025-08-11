#!/usr/bin/env python3
# coding: utf-8

"""
Core portfolio analysis business logic.
Extracted from run_risk.py as part of the refactoring to create a clean service layer.
"""

import yaml
from typing import Dict, Any, Optional
from datetime import datetime, UTC

from core.result_objects import RiskAnalysisResult

from run_portfolio_risk import (
    load_portfolio_config,
    standardize_portfolio_input,
    latest_price,
    evaluate_portfolio_risk_limits,
    evaluate_portfolio_beta_limits,
    get_cash_positions,
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
def analyze_portfolio(filepath: str, risk_yaml: str = "risk_limits.yaml") -> RiskAnalysisResult:
    """
    Core portfolio analysis business logic.
    
    This function contains the pure business logic extracted from run_portfolio(),
    without any CLI or dual-mode concerns.
    
    Parameters
    ----------
    filepath : str
        Path to the portfolio YAML file.
    risk_yaml : str, default "risk_limits.yaml"
        Path to the risk limits YAML file to use for analysis.
        
    Returns
    -------
    RiskAnalysisResult
        Complete risk analysis result object containing all portfolio metrics,
        factor exposures, risk checks, and formatted reporting capabilities.
    """
    
    # ─── 1. Load YAML Inputs ─────────────────────────────
    config = load_portfolio_config(filepath)
    
    with open(risk_yaml, "r") as f:
        risk_config = yaml.safe_load(f)

    # Get full standardized portfolio data (including exposure metrics)
    standardized_data = standardize_portfolio_input(config["portfolio_input"], latest_price)
    weights = standardized_data["weights"]
    
    # ─── 2. Build Portfolio View ─────────────────────────────
    summary = build_portfolio_view(
        weights,
        config["start_date"],
        config["end_date"],
        config.get("expected_returns"),
        config.get("stock_factor_proxies")
    )
    
    # ─── 2.1. Add Exposure Metrics to Summary ─────────────────
    summary.update({
        "net_exposure": standardized_data["net_exposure"],
        "gross_exposure": standardized_data["gross_exposure"],
        "leverage": standardized_data["leverage"],
        "total_value": standardized_data["total_value"],
        "dollar_exposure": standardized_data["dollar_exposure"]
    })
    
    # ─── 3. Calculate Beta Limits ────────────────────────────
    lookback_years = PORTFOLIO_DEFAULTS.get('worst_case_lookback_years', 10)
    max_betas, max_betas_by_proxy, historical_analysis = calc_max_factor_betas(
        portfolio_yaml=filepath,
        risk_yaml=risk_yaml,
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
    
    # ─── 5. Return Result Object ────────────────────────
    return RiskAnalysisResult.from_core_analysis(
        portfolio_summary=summary,
        risk_checks=df_risk.to_dict('records'), 
        beta_checks=df_beta.reset_index().to_dict('records'),
        max_betas=max_betas,
        max_betas_by_proxy=max_betas_by_proxy,
        historical_analysis=historical_analysis,
        analysis_metadata={
            "analysis_date": datetime.now(UTC).isoformat(),
            "portfolio_file": filepath,
            "lookback_years": lookback_years,
            "weights": weights,
            "total_positions": len(weights),
            "active_positions": len([v for v in weights.values() if abs(v) > 0.001]),
            "portfolio_name": config.get("name", "Portfolio"),
            "expected_returns": config.get("expected_returns"),
            "factor_proxies": config.get("stock_factor_proxies"),
            "cash_positions": list(get_cash_positions()),
        }
    ) 
#!/usr/bin/env python3
# coding: utf-8

"""
Core portfolio analysis business logic.

Agent orientation:
    This is the canonical pure-function risk analysis entrypoint for portfolio
    analysis. Start here when debugging risk metrics drift between CLI/API.

Called by:
    - ``run_risk.run_portfolio`` (dual-mode wrapper)
    - ``services.portfolio_service.PortfolioService.analyze_portfolio``

Primary flow:
    1) Resolve portfolio/risk config.
    2) Standardize weights/exposures.
    3) Build portfolio risk view.
    4) Evaluate risk/beta checks.
    5) Return ``RiskAnalysisResult``.
"""

from typing import Dict, Any, Optional, Union
from datetime import datetime, UTC

from core.result_objects import RiskAnalysisResult
from core.data_objects import PortfolioData, RiskLimitsData
from core.config_adapters import resolve_portfolio_config, resolve_risk_config

from core.portfolio_config import (
    standardize_portfolio_input,
    latest_price,
    get_cash_positions,
)
from run_portfolio_risk import (
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
def analyze_portfolio(
    portfolio: Union[str, PortfolioData],
    risk_limits: Union[str, RiskLimitsData, Dict[str, Any], None] = "risk_limits.yaml",
    *,
    asset_classes: Optional[Dict[str, str]] = None
) -> RiskAnalysisResult:
    """
    Run pure portfolio risk analysis and return ``RiskAnalysisResult``.

    Contract notes:
    - ``portfolio`` accepts YAML path or ``PortfolioData``.
    - ``risk_limits`` accepts YAML path, typed object, raw dict, or ``None``.
    - Returned object is the canonical contract for downstream API/service layers.
    
    Parameters
    ----------
    portfolio : Union[str, PortfolioData]
        Portfolio YAML filepath or a PortfolioData object.
    risk_limits : Union[str, RiskLimitsData, Dict[str, Any], None], default "risk_limits.yaml"
        Risk limits input as file path, typed object, raw dict, or None
        (None falls back to default risk limits YAML).
        
    Returns
    -------
    RiskAnalysisResult
        Complete risk analysis result object containing all portfolio metrics,
        factor exposures, risk checks, and formatted reporting capabilities.
    """
    
    # ─── 1. Load Inputs ─────────────────────────────
    config, filepath = resolve_portfolio_config(portfolio)
    risk_config = resolve_risk_config(risk_limits)

    # Get full standardized portfolio data (including exposure metrics)
    fmp_ticker_map = config.get("fmp_ticker_map")
    currency_map = config.get("currency_map")
    if fmp_ticker_map:
        price_fetcher = lambda t: latest_price(
            t,
            fmp_ticker_map=fmp_ticker_map,
            currency=currency_map.get(t) if currency_map else None,
        )
    else:
        price_fetcher = lambda t: latest_price(
            t,
            currency=currency_map.get(t) if currency_map else None,
        )
    standardized_keys = (
        "weights",
        "dollar_exposure",
        "total_value",
        "net_exposure",
        "gross_exposure",
        "leverage",
    )
    if all(k in config for k in standardized_keys) and config.get("weights") is not None:
        standardized_data = {k: config.get(k) for k in standardized_keys}
    else:
        standardized_data = standardize_portfolio_input(
            config["portfolio_input"],
            price_fetcher,
            currency_map=currency_map,
            fmp_ticker_map=fmp_ticker_map,
        )
    weights = standardized_data["weights"]
    
    # ─── 2. Build Portfolio View ─────────────────────────────
    summary = build_portfolio_view(
        weights,
        config["start_date"],
        config["end_date"],
        config.get("expected_returns"),
        config.get("stock_factor_proxies"),
        asset_classes=asset_classes,
        fmp_ticker_map=fmp_ticker_map,
        currency_map=currency_map,
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
        lookback_years=lookback_years,
        echo=False,  # Don't print helper tables when capturing output
        stock_factor_proxies=config.get("stock_factor_proxies"),
        fmp_ticker_map=config.get("fmp_ticker_map"),
        max_single_factor_loss=risk_config.get("max_single_factor_loss"),
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
            "asset_classes": asset_classes,
            "fmp_ticker_map": fmp_ticker_map,
        }
    ) 

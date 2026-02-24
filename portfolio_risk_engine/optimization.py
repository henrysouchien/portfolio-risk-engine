#!/usr/bin/env python3
# coding: utf-8

"""
Core portfolio optimization business logic.

Agent orientation:
    Canonical pure-function optimization entrypoints. Start here for min-var or
    max-return behavior before checking service/CLI wrappers.

Called by:
    - ``run_risk.run_min_variance``
    - ``run_risk.run_max_return``

Primary flow:
    1) Resolve portfolio/risk config.
    2) Standardize weights.
    3) Run optimization engine.
    4) Return ``OptimizationResult``.
"""

from typing import Dict, Any, Union
from datetime import datetime, UTC

from portfolio_risk_engine.results import OptimizationResult
from portfolio_risk_engine.data_objects import PortfolioData, RiskLimitsData
from portfolio_risk_engine.config_adapters import resolve_portfolio_config, resolve_risk_config

from portfolio_risk_engine.portfolio_config import (
    standardize_portfolio_input,
    latest_price,
)
from portfolio_risk_engine.portfolio_optimizer import (
    run_min_var,
    run_max_return_portfolio,
)

# Import logging decorators for optimization
from portfolio_risk_engine._logging import (
    log_operation,
    log_timing,
    log_errors,
)

@log_errors("high")
@log_operation("min_variance_optimization")
@log_timing(10.0)
def optimize_min_variance(
    portfolio: Union[str, PortfolioData],
    risk_limits: Union[str, RiskLimitsData, Dict[str, Any], None] = "risk_limits.yaml",
) -> OptimizationResult:
    """
    Run minimum-variance optimization and return ``OptimizationResult``.

    Contract notes:
    - ``portfolio`` accepts YAML path or ``PortfolioData``.
    - ``risk_limits`` accepts YAML path, typed object, raw dict, or ``None``.
    - Output is consumed unchanged by CLI/API wrappers.
    
    Parameters
    ----------
    portfolio : Union[str, PortfolioData]
        Portfolio input as YAML filepath or PortfolioData object.
        
    Returns
    -------
    OptimizationResult
        Complete optimization result object with:
        - optimized_weights: Optimized portfolio weights
        - risk_table: Risk checks for optimized portfolio  
        - beta_table: Beta checks for optimized portfolio
        - optimization_metadata: Optimization configuration and results
        - CLI and API formatting methods
    """
    # LOGGING: Add min variance optimization start logging and timing here
    
    # --- load configs ------------------------------------------------------
    config, source_file = resolve_portfolio_config(portfolio)
    risk_config = resolve_risk_config(risk_limits)

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

    weights = standardize_portfolio_input(
        config["portfolio_input"],
        price_fetcher,
        currency_map=currency_map,
        fmp_ticker_map=fmp_ticker_map,
    )["weights"]

    # --- run the engine ----------------------------------------------------
    w, r, b = run_min_var(
        base_weights = weights,
        config       = config,
        risk_config  = risk_config,
        proxies      = config["stock_factor_proxies"],
        fmp_ticker_map = fmp_ticker_map,
    )
    # LOGGING: Add min variance calculation performance timing here
    # TODO: Could add proxy table and summary like max return
    
    # --- Return OptimizationResult object ----------------------------------
    from portfolio_risk_engine.results import OptimizationResult

    return OptimizationResult.from_core_optimization(
        optimized_weights=w,
        risk_table=r,
        factor_table=b,  # Use as factor_table (same as beta_table)
        optimization_metadata={
            "optimization_type": "min_variance",
            "analysis_date": datetime.now(UTC).isoformat(),
            "portfolio_file": source_file,
            "original_weights": weights,
            "total_positions": len(w),
            "active_positions": len([v for v in w.values() if abs(v) > 0.001])
        }
        # portfolio_summary and proxy_table omitted - will use defaults (empty dict/DataFrame)
    )


@log_errors("high")
@log_operation("max_return_optimization")
@log_timing(10.0)
def optimize_max_return(
    portfolio: Union[str, PortfolioData],
    risk_limits: Union[str, RiskLimitsData, Dict[str, Any], None] = "risk_limits.yaml",
) -> OptimizationResult:
    """
    Run maximum-return optimization and return ``OptimizationResult``.

    Contract notes:
    - Same input flexibility as ``optimize_min_variance``.
    - Includes factor/proxy check tables for downstream diagnostics.
    
    Parameters
    ----------
    portfolio : Union[str, PortfolioData]
        Portfolio input as YAML filepath or PortfolioData object.
        
    Returns
    -------
    OptimizationResult
        Complete optimization result object containing:
        - optimized_weights: Optimized portfolio weights
        - portfolio_summary: Portfolio view of optimized weights
        - risk_table: Risk checks for optimized portfolio
        - factor_table: Factor beta checks for optimized portfolio
        - proxy_table: Proxy beta checks for optimized portfolio
        - optimization metadata and analysis date
    """
    
    # --- load configs ------------------------------------------------------
    config, source_file = resolve_portfolio_config(portfolio)
    risk_config = resolve_risk_config(risk_limits)

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

    weights = standardize_portfolio_input(
        config["portfolio_input"],
        price_fetcher,
        currency_map=currency_map,
        fmp_ticker_map=fmp_ticker_map,
    )["weights"]
    
    # --- run the engine ----------------------------------------------------
    w, summary, r, f_b, p_b = run_max_return_portfolio(
        weights     = weights,
        config      = config,
        risk_config = risk_config,
        proxies     = config["stock_factor_proxies"],
        fmp_ticker_map = fmp_ticker_map,
    )
    
    # --- Return OptimizationResult object --------------------------------
    return OptimizationResult.from_core_optimization(
        optimized_weights=w,
        portfolio_summary=summary,
        risk_table=r,
        factor_table=f_b,
        proxy_table=p_b,
        optimization_metadata={
            "optimization_type": "max_return",
            "analysis_date": datetime.now(UTC).isoformat(),
            "portfolio_file": source_file,
            "risk_limits_file": risk_limits if isinstance(risk_limits, str) else None,
            "original_weights": weights,
            "risk_limits": risk_config  # Pass the actual risk limits configuration
        }
    ) 

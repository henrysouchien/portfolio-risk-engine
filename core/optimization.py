#!/usr/bin/env python3
# coding: utf-8

"""
Core portfolio optimization business logic.
Extracted from run_risk.py as part of the refactoring to create a clean service layer.
"""

import yaml
from typing import Dict, Any, Optional, Tuple, Union
from datetime import datetime, UTC

from core.result_objects import OptimizationResult

from run_portfolio_risk import (
    load_portfolio_config,
    standardize_portfolio_input,
    latest_price,
)
from portfolio_optimizer import (
    run_min_var,
    run_max_return_portfolio,
)
from utils.serialization import make_json_safe

# Import logging decorators for optimization
from utils.logging import (
    log_portfolio_operation_decorator,
    log_performance,
    log_error_handling,
    log_resource_usage_decorator
)

@log_error_handling("high")
@log_portfolio_operation_decorator("min_variance_optimization")
@log_resource_usage_decorator(monitor_memory=True, monitor_cpu=True)
@log_performance(10.0)
def optimize_min_variance(filepath: str, risk_yaml: str = "risk_limits.yaml") -> 'OptimizationResult':
    """
    Core minimum variance optimization business logic.
    
    This function contains the pure business logic extracted from run_min_variance(),
    without any CLI or dual-mode concerns.
    
    Parameters
    ----------
    filepath : str
        Path to the portfolio YAML file.
        
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
    config = load_portfolio_config(filepath)
    with open(risk_yaml, "r") as f:
        risk_config = yaml.safe_load(f)

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
    from core.result_objects import OptimizationResult

    return OptimizationResult.from_core_optimization(
        optimized_weights=w,
        risk_table=r,
        factor_table=b,  # Use as factor_table (same as beta_table)
        optimization_metadata={
            "optimization_type": "min_variance",
            "analysis_date": datetime.now(UTC).isoformat(),
            "portfolio_file": filepath,
            "original_weights": weights,
            "total_positions": len(w),
            "active_positions": len([v for v in w.values() if abs(v) > 0.001])
        }
        # portfolio_summary and proxy_table omitted - will use defaults (empty dict/DataFrame)
    )


@log_error_handling("high")
@log_portfolio_operation_decorator("max_return_optimization")
@log_resource_usage_decorator(monitor_memory=True, monitor_cpu=True)
@log_performance(10.0)
def optimize_max_return(filepath: str, risk_yaml: str = "risk_limits.yaml") -> OptimizationResult:
    """
    Core maximum return optimization business logic.
    
    This function contains the pure business logic extracted from run_max_return(),
    without any CLI or dual-mode concerns.
    
    Parameters
    ----------
    filepath : str
        Path to the portfolio YAML file.
        
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
    config = load_portfolio_config(filepath)
    
    # Handle case where risk_yaml is None (use default)
    if risk_yaml is None:
        risk_yaml = "risk_limits.yaml"
    
    with open(risk_yaml, "r") as f:
        risk_config = yaml.safe_load(f)

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
            "portfolio_file": filepath,
            "risk_limits_file": risk_yaml,
            "original_weights": weights,
            "risk_limits": risk_config  # Pass the actual risk limits configuration
        }
    ) 

#!/usr/bin/env python3
# coding: utf-8

"""
Core portfolio optimization business logic.
Extracted from run_risk.py as part of the refactoring to create a clean service layer.
"""

import yaml
from typing import Dict, Any, Optional, Tuple, Union
from datetime import datetime

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
def optimize_min_variance(filepath: str) -> Dict[str, Any]:
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
    Dict[str, Any]
        Structured optimization results containing:
        - optimized_weights: Optimized portfolio weights
        - risk_analysis: Risk checks for optimized portfolio
        - beta_analysis: Beta checks for optimized portfolio
        - optimization_metadata: Optimization configuration and results
    """
    # LOGGING: Add min variance optimization start logging and timing here
    
    # --- load configs ------------------------------------------------------
    config = load_portfolio_config(filepath)
    with open("risk_limits.yaml", "r") as f:
        risk_config = yaml.safe_load(f)

    weights = standardize_portfolio_input(config["portfolio_input"], latest_price)["weights"]

    # --- run the engine ----------------------------------------------------
    w, r, b = run_min_var(
        base_weights = weights,
        config       = config,
        risk_config  = risk_config,
        proxies      = config["stock_factor_proxies"],
    )
    # LOGGING: Add min variance calculation performance timing here
    
    # --- Return structured results ----------------------------------------
    result = make_json_safe({
        "optimized_weights": w,
        "risk_analysis": {
            "risk_checks": r.to_dict('records'),
            "risk_passes": bool(r['Pass'].all()),
            "risk_violations": r[~r['Pass']].to_dict('records'),
            "risk_limits": {
                "portfolio_limits": risk_config["portfolio_limits"],
                "concentration_limits": risk_config["concentration_limits"],
                "variance_limits": risk_config["variance_limits"]
            }
        },
        "beta_analysis": {
            "beta_checks": b.to_dict('records'),
            "beta_passes": bool(b['pass'].all()),
            "beta_violations": b[~b['pass']].to_dict('records'),
        },
        "optimization_metadata": {
            "optimization_type": "minimum_variance",
            "analysis_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "portfolio_file": filepath,
            "original_weights": weights,
            "total_positions": len(w),
            "active_positions": len([v for v in w.values() if abs(v) > 0.001])
        }
    })
    
    # Add raw objects for dual-mode compatibility
    result["raw_tables"] = {
        "weights": w,
        "risk_table": r,
        "beta_table": b
    }
    
    return result


@log_error_handling("high")
@log_portfolio_operation_decorator("max_return_optimization")
@log_resource_usage_decorator(monitor_memory=True, monitor_cpu=True)
@log_performance(10.0)
def optimize_max_return(filepath: str) -> Dict[str, Any]:
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
    Dict[str, Any]
        Structured optimization results containing:
        - optimized_weights: Optimized portfolio weights
        - portfolio_summary: Portfolio view of optimized weights
        - risk_analysis: Risk checks for optimized portfolio
        - beta_analysis: Factor and proxy beta checks for optimized portfolio
        - optimization_metadata: Optimization configuration and results
    """
    
    # --- load configs ------------------------------------------------------
    config = load_portfolio_config(filepath)
    with open("risk_limits.yaml", "r") as f:
        risk_config = yaml.safe_load(f)

    weights = standardize_portfolio_input(config["portfolio_input"], latest_price)["weights"]
    
    # --- run the engine ----------------------------------------------------
    w, summary, r, f_b, p_b = run_max_return_portfolio(
        weights     = weights,
        config      = config,
        risk_config = risk_config,
        proxies     = config["stock_factor_proxies"],
    )
    
    # --- Return structured results ----------------------------------------
    result = make_json_safe({
        "optimized_weights": w,
        "portfolio_summary": summary,
        "risk_analysis": {
            "risk_checks": r.to_dict('records'),
            "risk_passes": bool(r['Pass'].all()),
            "risk_violations": r[~r['Pass']].to_dict('records'),
            "risk_limits": {
                "portfolio_limits": risk_config["portfolio_limits"],
                "concentration_limits": risk_config["concentration_limits"],
                "variance_limits": risk_config["variance_limits"]
            }
        },
        "beta_analysis": {
            "factor_beta_checks": f_b.to_dict('records'),
            "proxy_beta_checks": p_b.to_dict('records'),
            "factor_beta_passes": bool(f_b['pass'].all()),
            "proxy_beta_passes": bool(p_b['pass'].all()),
            "factor_beta_violations": f_b[~f_b['pass']].to_dict('records'),
            "proxy_beta_violations": p_b[~p_b['pass']].to_dict('records'),
        },
        "optimization_metadata": {
            "optimization_type": "maximum_return",
            "analysis_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "portfolio_file": filepath,
            "original_weights": weights,
            "total_positions": len(w),
            "active_positions": len([v for v in w.values() if abs(v) > 0.001]),
            "expected_returns_used": config.get("expected_returns", {})
        }
    })
    
    # Add raw objects for dual-mode compatibility
    result["raw_tables"] = {
        "weights": w,
        "summary": summary,
        "risk_table": r,
        "factor_table": f_b,
        "proxy_table": p_b
    }
    
    # LOGGING: Add optimization completion logging with timing here
    return result 
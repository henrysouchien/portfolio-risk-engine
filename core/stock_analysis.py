#!/usr/bin/env python3
# coding: utf-8

"""
Core stock analysis business logic.
Extracted from run_risk.py as part of the refactoring to create a clean service layer.
"""

import pandas as pd
from typing import Dict, Any, Optional, Union, List

from run_portfolio_risk import load_portfolio_config
from risk_summary import (
    get_detailed_stock_factor_profile,
    get_stock_risk_profile
)
from utils.serialization import make_json_safe

# Import logging decorators for stock analysis
from utils.logging import (
    log_portfolio_operation_decorator,
    log_performance,
    log_error_handling
)

@log_error_handling("high")
@log_portfolio_operation_decorator("stock_analysis")
@log_performance(3.0)
def analyze_stock(
    ticker: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    factor_proxies: Optional[Dict[str, Union[str, List[str]]]] = None,
    yaml_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Core stock analysis business logic.
    
    This function contains the pure business logic extracted from run_stock(),
    without any CLI or dual-mode concerns.
    
    Parameters
    ----------
    ticker : str
        Stock symbol.
    start : Optional[str]
        Start date in YYYY-MM-DD format. Defaults to 5 years ago.
    end : Optional[str]
        End date in YYYY-MM-DD format. Defaults to today.
    factor_proxies : Optional[Dict[str, Union[str, List[str]]]]
        Optional factor mapping.
    yaml_path : Optional[str]
        Path to YAML file for factor proxy lookup.
        
    Returns
    -------
    Dict[str, Any]
        Structured stock analysis results containing:
        - ticker: Stock symbol
        - analysis_period: Start and end dates
        - analysis_type: Type of analysis performed
        - volatility_metrics: Volatility analysis results
        - regression_metrics or risk_metrics: Market regression analysis
        - factor_summary: Factor analysis summary (if applicable)
        - analysis_metadata: Analysis configuration and timestamps
    """
    # LOGGING: Add stock analysis start logging and timing here
    # LOGGING: Add workflow state logging for stock analysis workflow here
    # LOGGING: Add resource usage monitoring for stock analysis here
    
    ticker = ticker.upper()

    # ─── 1. Resolve date window ─────────────────────────────────────────
    today = pd.Timestamp.today().normalize()
    start = pd.to_datetime(start) if start else today - pd.DateOffset(years=5)
    end   = pd.to_datetime(end)   if end   else today

    # ─── 2. Auto-lookup proxy block from YAML (if requested) ────────────
    if factor_proxies is None and yaml_path:
        try:
            cfg = load_portfolio_config(yaml_path)       # already handles safe_load + validation
            proxies = cfg.get("stock_factor_proxies", {})
            factor_proxies = proxies.get(ticker.upper())
        except Exception as e:
            # Note: In the original, this only printed if not return_data
            # For the core function, we'll just continue without factor_proxies
            pass

    # ─── 3. Diagnostics path A: multi-factor profile ────────────────────
    if factor_proxies:
        profile = get_detailed_stock_factor_profile(
            ticker, start, end, factor_proxies
        )
        
        # Return structured data for multi-factor analysis
        return make_json_safe({
            "ticker": ticker,
            "analysis_period": {
                "start_date": start.strftime("%Y-%m-%d"),
                "end_date": end.strftime("%Y-%m-%d")
            },
            "analysis_type": "multi_factor",
            "volatility_metrics": profile["vol_metrics"],
            "regression_metrics": profile["regression_metrics"],
            "factor_summary": profile["factor_summary"],
            "factor_proxies": factor_proxies,
            "analysis_metadata": {
                "has_factor_analysis": True,
                "num_factors": len(factor_proxies) if factor_proxies else 0,
                "analysis_date": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
            },
            "raw_data": {
                "profile": profile
            }
        })
        
    # ─── 4. Diagnostics path B: simple market regression ────────────────
    else:
        result = get_stock_risk_profile(
            ticker,
            start_date=start,
            end_date=end,
            benchmark="SPY"
        )
        
        # Return structured data for simple regression analysis
        return make_json_safe({
            "ticker": ticker,
            "analysis_period": {
                "start_date": start.strftime("%Y-%m-%d"),
                "end_date": end.strftime("%Y-%m-%d")
            },
            "analysis_type": "simple_market_regression",
            "volatility_metrics": result["vol_metrics"],
            "risk_metrics": result["risk_metrics"],
            "benchmark": "SPY",
            "analysis_metadata": {
                "has_factor_analysis": False,
                "num_factors": 0,
                "analysis_date": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
            },
            "raw_data": {
                "result": result
            }
        })
    # LOGGING: Add stock analysis completion logging with timing here
    # LOGGING: Add workflow state logging for stock analysis workflow completion here 
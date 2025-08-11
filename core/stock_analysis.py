#!/usr/bin/env python3
# coding: utf-8

"""
Core stock analysis business logic.
Extracted from run_risk.py as part of the refactoring to create a clean service layer.
"""

import pandas as pd
from typing import Dict, Any, Optional, Union, List
from datetime import datetime, UTC

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

def _create_factor_exposures_mapping(factor_summary, factor_proxies):
    """
    Create structured factor exposures mapping from raw factor_summary array and factor_proxies dict.
    
    Args:
        factor_summary: List of dicts with beta, r_squared, idio_vol_m (from compute_factor_metrics)
        factor_proxies: Dict mapping factor names to proxy tickers/lists
        
    Returns:
        Dict mapping factor names to their stats and proxy metadata:
        {
            "industry": {"beta": 1.224, "r_squared": 0.658, "idio_vol_m": 0.037, "proxy": "XLK"},
            "market": {"beta": -1.113, "r_squared": 0.136, "idio_vol_m": 0.059, "proxy": "SPY"},
            ...
        }
    """
    if factor_proxies is None or (hasattr(factor_summary, 'empty') and factor_summary.empty) or (isinstance(factor_summary, list) and not factor_summary):
        return {}
    
    factor_exposures = {}
    factor_names = list(factor_proxies.keys())
    
    # Handle both DataFrame and list formats
    if hasattr(factor_summary, 'iterrows'):
        # DataFrame format from compute_factor_metrics (factor names as index)
        for factor_name, row in factor_summary.iterrows():
            if factor_name in factor_proxies:
                factor_exposures[factor_name] = {
                    "beta": float(row.get("beta", 0)),
                    "r_squared": float(row.get("r_squared", 0)),
                    "idio_vol_m": float(row.get("idio_vol_m", 0)),
                    "proxy": factor_proxies[factor_name]
                }
    elif isinstance(factor_summary, list):
        # List format (array indices map to factor_names order)
        for i, factor_stats in enumerate(factor_summary):
            if i < len(factor_names) and isinstance(factor_stats, dict):
                factor_name = factor_names[i]
                factor_exposures[factor_name] = {
                    "beta": factor_stats.get("beta", 0),
                    "r_squared": factor_stats.get("r_squared", 0),
                    "idio_vol_m": factor_stats.get("idio_vol_m", 0),
                    "proxy": factor_proxies[factor_name]
                }
    
    return factor_exposures

@log_error_handling("high")
@log_portfolio_operation_decorator("stock_analysis")
@log_performance(3.0)
def analyze_stock(
    ticker: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    factor_proxies: Optional[Dict[str, Union[str, List[str]]]] = None
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
        Optional factor mapping. If None, auto-generates intelligent factor proxies.
        
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

    # ─── 2. Auto-generate factor proxies if needed ─────────────────────
    if factor_proxies is None:
        # Use intelligent auto-generation of factor proxies
        from services.factor_proxy_service import get_stock_factor_proxies
        factor_proxies = get_stock_factor_proxies(ticker)
    elif factor_proxies:
        # If user provided partial factor_proxies, fill in missing ones
        from services.factor_proxy_service import get_stock_factor_proxies
        full_proxies = get_stock_factor_proxies(ticker)
        # Update with user-provided proxies, keeping auto-generated ones as fallback
        full_proxies.update(factor_proxies)
        factor_proxies = full_proxies

    # ─── 3. Diagnostics path A: multi-factor profile ────────────────────
    if factor_proxies:
        profile = get_detailed_stock_factor_profile(
            ticker, start, end, factor_proxies
        )
        
        # Create structured factor exposures with metadata
        factor_exposures = _create_factor_exposures_mapping(profile["factor_summary"], factor_proxies)
        
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
            "factor_summary": profile["factor_summary"],  # Keep for backward compatibility
            "factor_proxies": factor_proxies,              # Keep for backward compatibility
            "factor_exposures": factor_exposures,          # NEW: Structured factor metadata
            "analysis_metadata": {
                "has_factor_analysis": True,
                "num_factors": len(factor_proxies) if factor_proxies else 0,
                "analysis_date": datetime.now(UTC).isoformat()
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
                "analysis_date": datetime.now(UTC).isoformat()
            },
            "raw_data": {
                "result": result
            }
        })
    # LOGGING: Add stock analysis completion logging with timing here
    # LOGGING: Add workflow state logging for stock analysis workflow completion here 
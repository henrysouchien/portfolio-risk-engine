#!/usr/bin/env python3
# coding: utf-8

"""
Core stock analysis business logic.

Called by:
- ``run_risk.run_stock`` wrapper path.
- Service/API stock-analysis flows.

Calls into:
- Factor/risk helper modules for regression and proxy construction.
- ``core.result_objects.StockAnalysisResult`` for response contract.

Contract notes:
- Returns canonical ``StockAnalysisResult`` for CLI/API formatting layers.
- Supports both equity and bond-style analysis paths.

Updates:
- Asset class detection: Optional asset_class parameter (auto-detected when None)
  enables bond-specific rate factor analysis.
- Bond analytics: For asset_class='bond', performs key‑rate regression using
  monthly Treasury Δy (2y/5y/10y/30y) and returns a single interest_rate beta
  (effective duration), plus diagnostics (adj‑R²) and per‑maturity breakdown.
- Total-return preference: Stock return series prefer dividend-adjusted prices
  for improved accuracy, with fallback to close-only.
"""

import pandas as pd
from typing import Dict, Any, Optional, Union, List
from datetime import datetime, UTC

from portfolio_risk_engine.portfolio_config import load_portfolio_config
from risk_summary import (
    get_detailed_stock_factor_profile,
    get_stock_risk_profile
)
from portfolio_risk_engine._vendor import make_json_safe
from portfolio_risk_engine.results import StockAnalysisResult
from portfolio_risk_engine.data_loader import fetch_monthly_close, fetch_monthly_total_return_price
from portfolio_risk_engine.factor_utils import (
    calc_monthly_returns,
    fetch_monthly_treasury_yield_levels,
    prepare_rate_factors,
    compute_multifactor_betas,
)

# Import logging decorators for stock analysis
from portfolio_risk_engine._logging import (
    log_operation,
    log_timing,
    log_errors,
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


def _has_complete_factor_proxies(
    factor_proxies: Optional[Dict[str, Union[str, List[str]]]]
) -> bool:
    """
    Return True when we have enough proxies for stable multi-factor analysis.

    Multi-factor path requires all core keys. Missing/empty keys should fall back
    to simple market regression instead of raising downstream KeyError.
    """
    if not isinstance(factor_proxies, dict):
        return False

    required_keys = ("market", "momentum", "value", "industry", "subindustry")
    for key in required_keys:
        val = factor_proxies.get(key)
        if val is None:
            return False
        if isinstance(val, str) and not val.strip():
            return False
        if isinstance(val, (list, tuple, set)) and len(val) == 0:
            return False
    return True

@log_errors("high")
@log_operation("stock_analysis")
@log_timing(3.0)
def analyze_stock(
    ticker: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    factor_proxies: Optional[Dict[str, Union[str, List[str]]]] = None,
    *,
    asset_class: Optional[str] = None,
    fmp_ticker_map: Optional[Dict[str, str]] = None,
) -> 'StockAnalysisResult':
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
    StockAnalysisResult
        Structured stock analysis result object containing:
        - ticker: Stock symbol
        - analysis_period: Start and end dates
        - analysis_type: Type of analysis performed
        - volatility_metrics: Volatility analysis results
        - regression_metrics or risk_metrics: Market regression analysis
        - factor_summary: Factor analysis summary (if applicable)
        - factor_exposures: Structured factor metadata (if applicable)
        - analysis_metadata: Analysis configuration and timestamps
        - (Bonds) interest_rate_beta, effective_duration (abs years),
          rate_regression_r2, and key_rate_breakdown
        
        Use .to_cli_report() for CLI output or .to_api_response() for API serialization.
    """
    # LOGGING: Add stock analysis start logging and timing here
    # LOGGING: Add workflow state logging for stock analysis workflow here
    # LOGGING: Add resource usage monitoring for stock analysis here
    
    ticker = ticker.upper()

    # ─── 1. Resolve date window ─────────────────────────────────────────
    today = pd.Timestamp.today().normalize()
    start = pd.to_datetime(start) if start else today - pd.DateOffset(years=5)
    end   = pd.to_datetime(end)   if end   else today

    # ─── 2. Asset class detection & factor proxies ─────────────────────
    if asset_class is None:
        try:
            from services.security_type_service import SecurityTypeService
            asset_class = SecurityTypeService.get_asset_classes([ticker]).get(ticker, 'equity')
        except Exception:
            asset_class = 'equity'

    # Auto-generate factor proxies if needed
    if factor_proxies is None:
        # Use intelligent auto-generation of factor proxies
        try:
            from services.factor_proxy_service import get_stock_factor_proxies

            factor_proxies = get_stock_factor_proxies(ticker)
        except Exception:
            factor_proxies = {}
    elif factor_proxies:
        # If user provided partial factor_proxies, fill in missing ones
        try:
            from services.factor_proxy_service import get_stock_factor_proxies

            full_proxies = get_stock_factor_proxies(ticker)
            # Update with user-provided proxies, keeping auto-generated ones as fallback
            full_proxies.update(factor_proxies)
            factor_proxies = full_proxies
        except Exception:
            # Standalone mode: proceed with provided proxies only.
            factor_proxies = factor_proxies or {}

    # ─── 3. Diagnostics path A: multi-factor profile ────────────────────
    if _has_complete_factor_proxies(factor_proxies):
        profile = get_detailed_stock_factor_profile(
            ticker, start, end, factor_proxies, fmp_ticker_map=fmp_ticker_map
        )
        
        # Create structured factor exposures with metadata
        factor_exposures = _create_factor_exposures_mapping(profile["factor_summary"], factor_proxies)
        
        # Optional: rate factor analysis for bonds (single interest_rate beta)
        rate_kwargs = {}
        if asset_class == 'bond':
            try:
                # Prefer total-return prices for stock
                try:
                    prices = fetch_monthly_total_return_price(
                        ticker,
                        start,
                        end,
                        fmp_ticker_map=fmp_ticker_map,
                    )
                except Exception:
                    prices = fetch_monthly_close(
                        ticker,
                        start,
                        end,
                        fmp_ticker_map=fmp_ticker_map,
                    )
                stock_ret = calc_monthly_returns(prices)
                # Treasury Δy
                levels = fetch_monthly_treasury_yield_levels(start, end)
                dy_df = prepare_rate_factors(levels)
                idx = stock_ret.index
                rate_df = dy_df.reindex(idx).dropna()
                aligned = stock_ret.reindex(rate_df.index)
                # Require sufficient observations for meaningful rate fit using centralized threshold
                from portfolio_risk_engine.config import DATA_QUALITY_THRESHOLDS
                min_obs = DATA_QUALITY_THRESHOLDS["min_observations_for_interest_rate_beta"]
                
                if not rate_df.empty and not aligned.empty and len(rate_df) >= min_obs:
                    res = compute_multifactor_betas(aligned, rate_df, hac_lags=3)
                    betas = res.get('betas', {}) or {}
                    ir_beta = float(sum(betas.values())) if betas else 0.0
                    rate_kwargs = {
                        'interest_rate_beta': ir_beta,
                        'effective_duration': abs(ir_beta),
                        'rate_regression_r2': float(res.get('r2_adj', 0.0)),
                        'key_rate_breakdown': {k: float(v) for k, v in betas.items()}
                    }
                    # VIF diagnostics
                    try:
                        vifs = res.get('vif', {}) or {}
                        if any((v is not None and v > 10) for v in vifs.values()):
                            from portfolio_risk_engine._logging import log_portfolio_operation
                            log_portfolio_operation("stock_rate_factor_high_vif", {"ticker": ticker, "vif": vifs}, execution_time=0)
                    except Exception:
                        pass
            except Exception:
                # Skip rate factor if any failure occurs
                rate_kwargs = {}

        # Return StockAnalysisResult object for multi-factor analysis
        return StockAnalysisResult.from_core_analysis(
            ticker=ticker,
            analysis_period={
                "start_date": start.strftime("%Y-%m-%d"),
                "end_date": end.strftime("%Y-%m-%d")
            },
            analysis_type="multi_factor",
            volatility_metrics=profile["vol_metrics"],
            regression_metrics=profile["regression_metrics"],
            factor_summary=profile["factor_summary"],
            factor_exposures=factor_exposures,
            factor_proxies=factor_proxies,
            analysis_metadata={
                "has_factor_analysis": True,
                "num_factors": len(factor_proxies) if factor_proxies else 0,
                "analysis_date": datetime.now(UTC).isoformat()
            },
            **rate_kwargs
        )
        
    # ─── 4. Diagnostics path B: simple market regression ────────────────
    else:
        result = get_stock_risk_profile(
            ticker,
            start_date=start,
            end_date=end,
            benchmark="SPY",
            fmp_ticker_map=fmp_ticker_map,
        )
        
        # Return StockAnalysisResult object for simple regression analysis
        return StockAnalysisResult.from_core_analysis(
            ticker=ticker,
            analysis_period={
                "start_date": start.strftime("%Y-%m-%d"),
                "end_date": end.strftime("%Y-%m-%d")
            },
            analysis_type="simple_market_regression",
            volatility_metrics=result["vol_metrics"],
            risk_metrics=result["risk_metrics"],
            analysis_metadata={
                "has_factor_analysis": False,
                "num_factors": 0,
                "analysis_date": datetime.now(UTC).isoformat(),
                "benchmark": "SPY"
            }
        )
    # LOGGING: Add stock analysis completion logging with timing here
    # LOGGING: Add workflow state logging for stock analysis workflow completion here 

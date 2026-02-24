#!/usr/bin/env python3
# coding: utf-8

"""
Core what-if scenario analysis business logic.

Called by:
- ``run_risk.run_what_if`` wrapper paths.
- Service/API layers that execute scenario comparisons.

Calls into:
- ``portfolio_optimizer.run_what_if_scenario`` for scenario engine execution.

Contract notes:
- Accepts portfolio/risk config as paths or typed objects via config adapters.
- Returns canonical ``WhatIfResult`` object for CLI/API formatting layers.
"""

import pandas as pd
from typing import Dict, Any, Optional, Union
from datetime import datetime, UTC

from portfolio_risk_engine.data_objects import PortfolioData, RiskLimitsData
from portfolio_risk_engine.config_adapters import resolve_portfolio_config, resolve_risk_config
from portfolio_risk_engine.portfolio_config import (
    standardize_portfolio_input,
    latest_price,
)
from portfolio_risk_engine.portfolio_risk import build_portfolio_view
from portfolio_risk_engine.portfolio_optimizer import run_what_if_scenario
from portfolio_risk_engine.results import WhatIfResult

# Import logging decorators for scenario analysis
from portfolio_risk_engine._logging import (
    log_operation,
    log_timing,
    log_errors,
)

@log_errors("high")
@log_operation("scenario_analysis")
@log_timing(5.0)
def analyze_scenario(
    portfolio: Union[str, PortfolioData],
    risk_limits: Union[str, RiskLimitsData, Dict[str, Any], None] = None,
    scenario_yaml: Optional[str] = None,
    delta: Optional[Union[str, Dict[str, str]]] = None
) -> WhatIfResult:
    """
    Core scenario analysis business logic.
    
    This function contains the pure business logic extracted from run_what_if(),
    without any CLI or dual-mode concerns. Analyzes portfolio changes defined either
    in a YAML file or via inline delta strings.
    
    Parameters
    ----------
    portfolio : Union[str, PortfolioData]
        Portfolio input as YAML filepath or in-memory PortfolioData object.
    scenario_yaml : str, optional
        Path to a YAML file containing scenario definitions. Two supported formats:
        
        1. Full portfolio replacement (new_weights):
           ```yaml
           new_weights:
             AAPL: 0.25    # 25% allocation as decimal
             SGOV: 0.15    # 15% allocation as decimal  
             MSCI: 0.60    # 60% allocation as decimal
           ```
           
        2. Incremental changes (delta):
           ```yaml
           delta:
             AAPL: "+200bp"   # Increase by 2% (basis points)
             SGOV: "-0.05"    # Decrease by 5% (decimal)
             NVDA: "1.5%"     # Increase by 1.5% (percentage string)
           ```
           
    delta : str, optional
        Comma-separated inline weight shifts, e.g. "TW:+500bp,PCTY:-200bp".
        Used as fallback if scenario_yaml is not provided or doesn't contain valid changes.
        Format: "TICKER1:+/-change,TICKER2:+/-change" where change can be:
        - Basis points: "+500bp", "-200bps" 
        - Percentages: "+2%", "-1.5%"
        - Decimals: "+0.02", "-0.015"
    risk_limits : Union[str, RiskLimitsData, Dict[str, Any], None], optional
        Risk limits input as path, typed object, dict, or None (defaults to
        "risk_limits.yaml" via resolver fallback).
        
    Returns
    -------
    WhatIfResult
        Complete what-if scenario analysis result object containing:
        - Current and scenario portfolio metrics
        - Risk and beta comparison tables
        - CLI formatting capabilities via to_cli_report()
        - API response data via to_api_response()
        
    Notes
    -----
    Input precedence:
    1. If scenario_yaml contains 'new_weights', treats as full portfolio replacement
    2. Otherwise, looks for 'delta' section in YAML file
    3. Falls back to inline 'delta' parameter if YAML is missing or incomplete
    
    Weight formats:
    - new_weights: Must be decimal allocations (0.25 for 25%)
    - delta changes: Support multiple formats (bp, %, decimals) with automatic parsing
    """
    # LOGGING: Add scenario analysis start logging and timing here
    
    # --- load configs ------------------------------------------------------
    config, filepath = resolve_portfolio_config(portfolio)
    # LOGGING: Add config loading performance timing here
    # LOGGING: Add workflow state logging for scenario analysis workflow here
    # LOGGING: Add resource usage monitoring for scenario analysis here
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

    # parse CLI delta string OR accept dict directly
    shift_dict = None
    if delta:
        if isinstance(delta, dict):
            # Already a dict from service layer - use directly
            shift_dict = delta
        else:
            # String from CLI - parse it
            shift_dict = {k.strip(): v.strip() for k, v in (pair.split(":") for pair in delta.split(","))}

    # --- run the engine ----------------------------------------------------
    # First, create base portfolio summary for comparison
    summary_base = build_portfolio_view(
        weights,
        config["start_date"],
        config["end_date"],
        config.get("expected_returns"),
        config.get("stock_factor_proxies"),
        fmp_ticker_map=fmp_ticker_map,
        currency_map=currency_map,
    )
    
    # Then run the scenario
    summary, risk_new, beta_new, cmp_risk, cmp_beta = run_what_if_scenario(
        base_weights = weights,
        config       = config,
        risk_config  = risk_config,
        proxies      = config["stock_factor_proxies"],
        scenario_yaml = scenario_yaml,
        shift_dict   = shift_dict,
    )
    
    # split beta table between factors and industry
    beta_f_new = beta_new.copy()
    beta_p_new = pd.DataFrame()
    
    # Only try to split if we have a proper index
    if hasattr(beta_new.index, 'str') and len(beta_new) > 0:
        try:
            industry_mask = beta_new.index.str.startswith("industry_proxy::")
            beta_f_new = beta_new[~industry_mask]
            beta_p_new = beta_new[industry_mask].copy()
            if not beta_p_new.empty:
                beta_p_new.index = beta_p_new.index.str.replace("industry_proxy::", "")
        except Exception as e:
            # Fallback: use the original beta table as factor table
            print(f"Warning: Could not split beta table: {e}")
            beta_f_new = beta_new.copy()
            beta_p_new = pd.DataFrame()
    
    # --- Build minimal result data structure consumed by WhatIfResult -----
    raw_tables = {
        "summary": summary,
        "summary_base": summary_base,  # Original portfolio for before/after comparison
        "risk_new": risk_new,
        "beta_f_new": beta_f_new,
        "beta_p_new": beta_p_new,
        "cmp_risk": cmp_risk,
        "cmp_beta": cmp_beta,
    }

    scenario_metadata = {
        "scenario_yaml": scenario_yaml,
        "delta_string": delta,
        "shift_dict": shift_dict,
        "analysis_date": datetime.now(UTC).isoformat(),
        "portfolio_file": filepath,
        "base_weights": weights,
        "risk_limits": risk_config,
    }

    scenario_result_data = {
        "raw_tables": raw_tables,
        "scenario_metadata": scenario_metadata,
    }
    
    # LOGGING: Add scenario analysis completion logging with timing here
    # LOGGING: Add workflow state logging for scenario analysis workflow completion here
    
    # Use new builder method to create WhatIfResult
    return WhatIfResult.from_core_scenario(
        scenario_result=scenario_result_data,
        scenario_name="What-If Scenario"
    ) 

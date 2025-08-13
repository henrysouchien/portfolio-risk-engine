#!/usr/bin/env python3
# coding: utf-8

"""
Core scenario analysis business logic.
Extracted from run_risk.py as part of the refactoring to create a clean service layer.
"""

import yaml
import pandas as pd
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, UTC

from run_portfolio_risk import (
    load_portfolio_config,
    standardize_portfolio_input,
    latest_price,
)
from portfolio_risk import build_portfolio_view
from portfolio_optimizer import run_what_if_scenario
from core.result_objects import WhatIfResult

# Import logging decorators for scenario analysis
from utils.logging import (
    log_portfolio_operation_decorator,
    log_performance,
    log_error_handling
)

@log_error_handling("high")
@log_portfolio_operation_decorator("scenario_analysis")
@log_performance(5.0)
def analyze_scenario(
    filepath: str,
    risk_limits_yaml: str,
    scenario_yaml: Optional[str] = None,
    delta: Optional[str] = None
) -> WhatIfResult:
    """
    Core scenario analysis business logic.
    
    This function contains the pure business logic extracted from run_what_if(),
    without any CLI or dual-mode concerns. Analyzes portfolio changes defined either
    in a YAML file or via inline delta strings.
    
    Parameters
    ----------
    filepath : str
        Path to the primary portfolio YAML file.
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
    risk_limits_yaml : str, optional
        Path to the risk limits YAML file. Defaults to "risk_limits.yaml".
        
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
    config = load_portfolio_config(filepath)
    # LOGGING: Add config loading performance timing here
    # LOGGING: Add workflow state logging for scenario analysis workflow here
    # LOGGING: Add resource usage monitoring for scenario analysis here
    with open(risk_limits_yaml, "r") as f:
        risk_config = yaml.safe_load(f)

    weights = standardize_portfolio_input(config["portfolio_input"], latest_price)["weights"]

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
        config.get("stock_factor_proxies")
    )
    
    # Then run the scenario
    summary, risk_new, beta_new, cmp_risk, cmp_beta = run_what_if_scenario(
        base_weights = weights,
        config       = config,
        risk_config  = risk_config,
        proxies      = config["stock_factor_proxies"],
        scenario_yaml = scenario_yaml,
        shift_dict   = shift_dict,
        portfolio_yaml_path = filepath,
        risk_yaml_path = risk_limits_yaml,
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
    
    # --- Build result object using new builder method ---------------------
    # Create structured data for the builder method
    #TODO: Need to consolidate all this data stuff with the result_objects.py builder method or API response
    scenario_result_data = {
        # Raw scenario_summary with pandas objects (for service layer)
        "scenario_summary": summary,
        
        # Analysis data with selective conversion (matching portfolio analysis pattern)
        "risk_analysis": {
            "risk_checks": risk_new.to_dict('records') if not risk_new.empty else [],
            "risk_passes": bool(risk_new['Pass'].all()) if not risk_new.empty and 'Pass' in risk_new.columns else True,
            "risk_violations": risk_new[~risk_new['Pass']].to_dict('records') if not risk_new.empty and 'Pass' in risk_new.columns else [],
            "risk_limits": {
                "portfolio_limits": risk_config["portfolio_limits"],
                "concentration_limits": risk_config["concentration_limits"],
                "variance_limits": risk_config["variance_limits"]
            }
        },
        
        "beta_analysis": {
            "factor_beta_checks": beta_f_new.to_dict('records') if not beta_f_new.empty else [],
            "proxy_beta_checks": beta_p_new.to_dict('records') if not beta_p_new.empty else [],
            "beta_passes": bool(beta_new['pass'].all()) if not beta_new.empty and 'pass' in beta_new.columns else True,
            "beta_violations": beta_new[~beta_new['pass']].to_dict('records') if not beta_new.empty and 'pass' in beta_new.columns else [],
        },
        
        "comparison_analysis": {
            "risk_comparison": cmp_risk.to_dict('records'),
            "beta_comparison": cmp_beta.to_dict('records'),
        },
        
        "scenario_metadata": {
            "scenario_yaml": scenario_yaml,
            "delta_string": delta,
            "shift_dict": shift_dict,
            "analysis_date": datetime.now(UTC).isoformat(),
            "portfolio_file": filepath,
            "base_weights": weights
        },
        
        # Store raw objects for dual-mode compatibility
        "raw_tables": {
            "summary": summary,
            "summary_base": summary_base,  # Add original portfolio for before/after comparison
            "risk_new": risk_new,
            "beta_f_new": beta_f_new,
            "beta_p_new": beta_p_new,
            "cmp_risk": cmp_risk,
            "cmp_beta": cmp_beta
        }
    }
    
    # LOGGING: Add scenario analysis completion logging with timing here
    # LOGGING: Add workflow state logging for scenario analysis workflow completion here
    
    # Use new builder method to create WhatIfResult
    return WhatIfResult.from_core_scenario(
        scenario_result=scenario_result_data,
        scenario_name="What-If Scenario"
    ) 
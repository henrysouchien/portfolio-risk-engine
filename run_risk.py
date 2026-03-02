#!/usr/bin/env python3
# coding: utf-8

# In[ ]:


# File: run_risk.py

import argparse
import yaml
from contextlib import redirect_stdout 
from typing import Optional, Dict, Union, List, Any, overload
import pandas as pd
from io import StringIO
import numpy as np
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

from risk_summary import (
    get_detailed_stock_factor_profile,
    get_stock_risk_profile
)
from core.portfolio_config import (
    latest_price,
    load_portfolio_config,
    standardize_portfolio_input,
)
from run_portfolio_risk import (
    display_portfolio_config,
    display_portfolio_summary,
    evaluate_portfolio_beta_limits,
    evaluate_portfolio_risk_limits,
)
from portfolio_risk import build_portfolio_view
from portfolio_optimizer import (
    run_what_if_scenario,
    print_what_if_report,
    run_min_var,
    run_max_return_portfolio,
    print_max_return_report,
)  
from risk_helpers import (
    calc_max_factor_betas
)
from proxy_builder import inject_all_proxies
from gpt_helpers import (
    interpret_portfolio_risk,
    generate_subindustry_peers,
)
from helpers_display import display_enhanced_stock_analysis
from utils.serialization import make_json_safe
from core.data_objects import PortfolioData, RiskLimitsData
from core.config_adapters import config_from_portfolio_data
from core.portfolio_analysis import analyze_portfolio

# Import logging decorators
from utils.logging import (
    log_errors,
    log_operation,
    log_timing,
)
from core.scenario_analysis import analyze_scenario
from core.optimization import optimize_min_variance, optimize_max_return
from core.result_objects import (
    OptimizationResult, 
    StockAnalysisResult, 
    InterpretationResult, 
    WhatIfResult, 
    PerformanceResult, 
    RiskScoreResult, 
    RiskAnalysisResult
)
from core.stock_analysis import analyze_stock
from core.performance_analysis import analyze_performance
from core.interpretation import analyze_and_interpret, interpret_portfolio_data

"""
Risk Analysis CLI & API Interface Module

This module provides DUAL-MODE functions that serve as the primary interface layer for 
portfolio risk analysis, optimization, and what-if scenarios. Each function supports both 
Command Line Interface (CLI) and Application Programming Interface (API) usage patterns.

🔄 DUAL-MODE PATTERN
==================

Every major analysis function follows this pattern:

    function_name(parameters, *, return_data: bool = False)

CLI Mode (default, return_data=False):
    - Prints formatted analysis directly to stdout
    - Perfect for terminal usage and scripting
    - Example: python run_risk.py --portfolio portfolio.yaml

API Mode (return_data=True):
    - Returns structured dictionary with analysis data + formatted report
    - Used by service layer, web APIs, and Claude AI integration
    - Guarantees identical output to CLI mode
    - Example: result = run_portfolio("portfolio.yaml", return_data=True)

🎯 WHY DUAL-MODE?
================

This pattern solves the "multiple consumer" challenge:
- CLI users need formatted text output
- APIs need structured JSON data  
- Claude AI needs human-readable reports
- All must have IDENTICAL analysis logic and formatting

Without dual-mode, we'd need separate functions that could drift apart over time.
With dual-mode, there's a single source of truth for business logic and formatting.

📋 DUAL-MODE FUNCTIONS
======================

- run_portfolio(): Portfolio risk analysis with 30+ metrics
- run_what_if(): What-if scenario analysis and comparison  
- run_min_variance() / run_max_return(): Portfolio optimization
- run_stock(): Individual stock risk analysis
- run_portfolio_performance(): Performance metrics calculation

🏗️ ARCHITECTURE INTEGRATION
============================

CLI Users:           run_risk.py functions → stdout
Service Layer:       run_risk.py functions → structured data + formatted reports  
Web APIs:           Service Layer → JSON responses
Claude AI:          Service Layer → human-readable formatted reports

For detailed architecture documentation, see: architecture.md
"""

# ============================================================================
# This handles AI interpretation of portfolio analysis
# ============================================================================
def run_and_interpret(portfolio_yaml: str, *, return_data: bool = False) -> Union[str, InterpretationResult]:
    """
    Convenience wrapper:

        1. runs `run_portfolio(portfolio_yaml)`
        2. captures everything it prints
        3. feeds that text to GPT for a summary
        4. prints **both** the GPT summary *and* the raw diagnostics (CLI mode)
        5. returns GPT summary string (CLI mode) or InterpretationResult object (data mode)

    Parameters
    ----------
    portfolio_yaml : str
        Path to the portfolio configuration YAML.
    return_data : bool, default False
        If True, returns InterpretationResult object for programmatic use.
        If False, prints formatted output to stdout and returns AI interpretation string.

    Returns
    -------
    Union[str, InterpretationResult]
        If return_data=False: Returns str (AI interpretation text only - existing CLI behavior)
        If return_data=True: Returns InterpretationResult object with:
            - ai_interpretation: GPT interpretation of the analysis
            - full_diagnostics: Complete analysis output text
            - analysis_metadata: Analysis configuration and timestamps
    """
    # --- BUSINESS LOGIC: Call extracted core function ---------------------
    interpretation_result = analyze_and_interpret(portfolio_yaml)
    
    # --- Dual-Mode Logic ---------------------------------------------------
    if return_data:
        # Return InterpretationResult object
        return interpretation_result
    else:
        # CLI MODE: Print formatted output using Result Object method
        print(interpretation_result.to_cli_report())
        
        return interpretation_result.ai_interpretation  # Return GPT summary text (existing behavior)

# ============================================================================
# This handles AI interpretation of structured portfolio output
# ============================================================================
@log_errors("high")
@log_operation("ai_interpretation")
@log_timing(3.0)
def interpret_portfolio_output(portfolio_output: Dict[str, Any], *, 
                              portfolio_name: Optional[str] = None,
                              return_data: bool = False) -> Union[str, InterpretationResult]:
    """
    Add AI interpretation to existing portfolio analysis output.
    
    This function enables two-level caching optimization:
    1. run_portfolio() output can be cached by PortfolioService
    2. AI interpretation can be cached separately
    
    Parameters
    ----------
    portfolio_output : Dict[str, Any]
        Structured output from run_portfolio(return_data=True)
    portfolio_name : Optional[str]
        Name/identifier for the portfolio (for metadata)
    return_data : bool, default False
        If True, returns structured data instead of printing.
        If False, prints formatted output to stdout (existing behavior).
    
    Returns
    -------
    str or Dict[str, Any]
        If return_data=False: Returns GPT interpretation string (existing behavior)
        If return_data=True: Returns structured data dictionary with:
            - ai_interpretation: GPT interpretation of the analysis
            - full_diagnostics: Complete analysis output text
            - analysis_metadata: Analysis configuration and timestamps

            TODO: Deprecate this function (current usage is in api.py)
    """
    # --- BUSINESS LOGIC: Call extracted core function ---------------------
    interpretation_result = interpret_portfolio_data(portfolio_output, portfolio_name)
    
    # --- Dual-Mode Logic ---------------------------------------------------
    if return_data:
        # Return structured data from extracted function
        return interpretation_result
    else:
        # CLI MODE: Print formatted output (existing behavior)
        print("\n=== GPT Portfolio Interpretation ===\n")
        print(interpretation_result["ai_interpretation"])
        print("\n=== Full Diagnostics ===\n")
        print(interpretation_result["full_diagnostics"])
        
        return interpretation_result["ai_interpretation"]  # Return GPT summary text (existing behavior)



# ============================================================================
# CORE BUSINESS LOGIC
# ============================================================================

# Import logging decorators for portfolio analysis (imported at top of file)

@log_errors("high")
@log_operation("portfolio_analysis")
@log_timing(5.0)
def run_portfolio(
    filepath: Union[str, PortfolioData],
    risk_yaml: Union[str, RiskLimitsData, Dict[str, Any], None] = "risk_limits.yaml",
    *,
    return_data: bool = False,
    asset_classes: Optional[Dict[str, str]] = None,
    security_types: Optional[Dict[str, str]] = None,
) -> Union[None, RiskAnalysisResult]:
    """
    High-level "one-click" entry-point for a full portfolio risk run.

    Called by:
    - CLI usage (`run_risk.py`) and service wrappers that need full risk analysis.

    Calls into:
    - `core.portfolio_analysis.analyze_portfolio` for core computation.
    - `SecurityTypeService` asset-class resolution when classes are not supplied.

    Contract:
    - CLI mode prints `RiskAnalysisResult.to_cli_report()`.
    - Data mode returns `RiskAnalysisResult` for downstream serialization.

    It ties together **all** of the moving pieces you've built so far:

        1.  Loads the portfolio YAML file (positions, dates, factor proxies).
        2.  Loads the firm-wide risk-limits YAML.
        3.  Standardises the raw position inputs into weights, then calls
            `build_portfolio_view` to produce the master `summary` dictionary
            (returns, vol, correlation, factor betas, variance decomposition, …).
        4.  Pretty-prints the standard risk summary via `display_portfolio_summary`.
        5.  Derives *dynamic* max-beta limits:
                • looks back over the analysis window,
                • finds worst 1-month drawdowns for every unique factor proxy,
                • converts those losses into a per-factor β ceiling
                  using the global `max_single_factor_loss`.
        6.  Runs two rule-checkers
                • `evaluate_portfolio_risk_limits`   →   Vol, concentration, factor %
                • `evaluate_portfolio_beta_limits`   →   Actual β vs. max β
        7.  Prints both tables in a compact "PASS/FAIL" console report.

    Parameters
    ----------
    filepath : Union[str, PortfolioData]
        Path to the *portfolio* YAML ( **not** the risk-limits file ) or a
        PortfolioData object with equivalent fields.
    return_data : bool, default False
        If True, returns structured data instead of printing.
        If False, prints formatted output to stdout (existing behavior).

    Returns
    -------
    None or Dict[str, Any]
        If return_data=False: Returns None, prints formatted output (existing behavior)
        If return_data=True: Returns structured data dictionary with:
            - portfolio_summary: Complete portfolio view from build_portfolio_view
            - risk_analysis: Risk limit checks and violations
            - beta_analysis: Factor beta checks and violations
            - analysis_metadata: Analysis configuration and timestamps
            - formatted_report: Captured CLI output text

    Side-effects
    ------------
    • When return_data=False: Prints a formatted risk report to stdout.
    • When return_data=True: No console output, returns structured data.

    Example
    -------
    # CLI usage (existing behavior)
    >>> run_portfolio("portfolio.yaml")
    === Target Allocations ===
    …                                 # summary table
    === Portfolio Risk Limit Checks ===
    Volatility:             21.65%  ≤ 40.00%     → PASS
    …
    === Beta Exposure Checks ===
    market       β = 0.74  ≤ 0.80  → PASS
    …
    
    # API usage (new behavior)
    >>> result = run_portfolio("portfolio.yaml", return_data=True)
    >>> print(result["portfolio_summary"]["annual_volatility"])
    0.2165
    >>> print(result["risk_analysis"]["risk_passes"])
    True
    """
    # LOGGING: Add portfolio analysis entry logging with timing
    # LOGGING: Add workflow state logging for risk analysis workflow start here
    # LOGGING: Add user context tracking
    # LOGGING: Add performance monitoring for operations >1s
    # LOGGING: Add resource usage monitoring for analysis process here
    
    # ─── BUSINESS LOGIC: Call extracted core function ─────────
    # If classification data not provided, derive both via SecurityTypeService
    if asset_classes is None or security_types is None:
        try:
            if isinstance(filepath, str):
                from core.portfolio_config import load_portfolio_config, standardize_portfolio_input, latest_price
                config = load_portfolio_config(filepath)
                weights = config.get("weights") or standardize_portfolio_input(config["portfolio_input"], latest_price)["weights"]
                tickers = list(weights.keys())
            else:
                tickers = filepath.get_tickers()
            from services.security_type_service import SecurityTypeService
            full_classification = SecurityTypeService.get_full_classification(tickers)
            if asset_classes is None:
                asset_classes = {
                    ticker: labels.get("asset_class")
                    for ticker, labels in full_classification.items()
                }
            if security_types is None:
                security_types = {
                    ticker: labels.get("security_type")
                    for ticker, labels in full_classification.items()
                }
        except Exception:
            if asset_classes is None:
                asset_classes = None
            if security_types is None:
                security_types = None

    result = analyze_portfolio(
        filepath,
        risk_limits=risk_yaml,
        asset_classes=asset_classes,
        security_types=security_types,
    )
    
    # ─── 5. Dual-Mode Logic ─────────────────────────────────
    if return_data:
        # API MODE: Return result object (service layer will call to_api_response())
        return result
        # LOGGING: Add portfolio analysis completion logging with execution time
        # LOGGING: Add workflow state logging for risk analysis workflow completion here
        # LOGGING: Add resource usage monitoring for analysis completion here
    else:
        # CLI MODE: Print portfolio config first, then formatted output from result object
        from core.portfolio_config import load_portfolio_config
        from run_portfolio_risk import display_portfolio_config
        if isinstance(filepath, str):
            config = load_portfolio_config(filepath)
        else:
            config = config_from_portfolio_data(filepath)
        display_portfolio_config(config)
        print(result.to_cli_report())
        # LOGGING: Add portfolio analysis completion logging with execution time

# ============================================================================
# WHAT-IF SCENARIO LOGIC
# This handles what-if scenario analysis
# ============================================================================

def _handle_new_tickers_for_cli(
    filepath: str,
    scenario_yaml: Optional[str] = None,
    delta: Optional[str] = None
) -> str:
    """
    CLI-specific helper to detect new tickers and create temporary portfolio file with proxies.
    
    This function creates a temporary portfolio file if new tickers are detected that need
    factor proxy generation. The original file is never modified. It handles both scenario
    YAML files and inline delta strings.
    
    Parameters
    ----------
    filepath : str
        Path to the original portfolio YAML file (read-only).
    scenario_yaml : str, optional
        Path to a YAML file containing scenario definitions.
    delta : str, optional
        Comma-separated inline weight shifts.
        
    Returns
    -------
    str
        Path to the portfolio file to use for analysis. Either the original filepath
        (if no new tickers) or a temporary file path (if new tickers were added).
        
    Side Effects
    ------------
    • May create a temporary portfolio file with factor proxies for new tickers
    • Logs new ticker detection and proxy injection activities
    • Temporary files are automatically cleaned up by the system
    """
    import yaml
    import tempfile
    import os
    from pathlib import Path
    from helpers_input import parse_delta
    from proxy_builder import inject_all_proxies
    from utils.logging import portfolio_logger
    
    try:
        # Load current portfolio to get existing tickers
        with open(filepath, 'r') as f:
            portfolio_config = yaml.safe_load(f)
        
        current_tickers = set(portfolio_config.get('portfolio_input', {}).keys())
        
        # Parse scenario/delta to get requested tickers
        scenario_tickers = set()
        
        if scenario_yaml and Path(scenario_yaml).exists():
            # Parse scenario YAML file
            delta_dict, new_weights = parse_delta(yaml_path=scenario_yaml)
            if new_weights:
                # Full replacement scenario - all tickers are potentially new
                scenario_tickers = set(new_weights.keys())
            elif delta_dict:
                # Delta scenario - only delta tickers matter
                scenario_tickers = set(delta_dict.keys())
        elif delta:
            # Parse inline delta string
            try:
                delta_dict_str = {k.strip(): v.strip() for k, v in (pair.split(":") for pair in delta.split(",")) if k.strip()}
                delta_dict, _ = parse_delta(yaml_path=None, literal_shift=delta_dict_str)
                scenario_tickers = set(delta_dict.keys())
            except Exception:
                # Invalid delta format - let analyze_scenario handle the error
                return filepath
        else:
            # No scenario changes - return original file
            return filepath
        
        # Detect new tickers (filter out empty strings for safety)
        scenario_tickers = {ticker for ticker in scenario_tickers if ticker.strip()}
        new_tickers = scenario_tickers - current_tickers
        
        if new_tickers:
            portfolio_logger.info(f"CLI: Detected new tickers in scenario: {new_tickers}")
            
            # Create a temporary portfolio file with new tickers added
            import copy
            portfolio_config_copy = copy.deepcopy(portfolio_config)
            
            # Add new tickers to the copy with minimal shares
            for ticker in new_tickers:
                portfolio_config_copy['portfolio_input'][ticker] = {'shares': 0.001}
            
            # Create temporary file
            temp_fd, temp_filepath = tempfile.mkstemp(suffix='.yaml', prefix='cli_portfolio_')
            try:
                with os.fdopen(temp_fd, 'w') as temp_file:
                    yaml.dump(portfolio_config_copy, temp_file, sort_keys=False)
                
                # Inject proxies for all tickers (including new ones) in the temp file
                portfolio_logger.info(f"CLI: Injecting factor proxies for new tickers: {new_tickers}")
                inject_all_proxies(temp_filepath, use_gpt_subindustry=True)
                
                portfolio_logger.info(f"CLI: Successfully created temporary portfolio with {len(new_tickers)} new tickers and proxies")
                return temp_filepath
                
            except Exception as proxy_error:
                # Clean up temp file if proxy injection fails
                try:
                    os.unlink(temp_filepath)
                except:
                    pass
                raise proxy_error
        else:
            # No new tickers - return original file
            return filepath
        
    except Exception as e:
        # Log warning but don't fail - return original file
        portfolio_logger.warning(f"CLI: Failed to inject proxies for new tickers: {e}")
        return filepath


def _handle_new_tickers_for_cli_with_validation(
    filepath: str,
    scenario_yaml: Optional[str] = None,
    delta: Optional[str] = None
) -> tuple[str, Optional[str]]:
    """
    CLI-specific helper that validates inputs and handles new tickers.
    
    This function validates delta strings and filters out malformed entries
    before delegating to the main CLI ticker handling function.
    
    Returns:
        tuple[str, Optional[str]]: (portfolio_filepath, cleaned_delta)
            - portfolio_filepath: Either original or temporary file with new tickers
            - cleaned_delta: Validated and cleaned delta string, or None if invalid
    """
    # Validate and clean delta string if provided
    cleaned_delta = delta
    if delta:
        try:
            # Test if delta can be parsed without errors
            delta_dict_str = {k.strip(): v.strip() for k, v in (pair.split(":") for pair in delta.split(",")) if k.strip()}
            if not delta_dict_str:
                # No valid ticker:value pairs found
                cleaned_delta = None
            else:
                # Reconstruct cleaned delta string
                cleaned_delta = ",".join(f"{k}:{v}" for k, v in delta_dict_str.items())
        except Exception:
            # Malformed delta - set to None to avoid processing
            cleaned_delta = None
    
    # Process with the existing function
    portfolio_file_to_use = _handle_new_tickers_for_cli(filepath, scenario_yaml, cleaned_delta)
    
    return portfolio_file_to_use, cleaned_delta


def run_what_if(
    filepath: Union[str, PortfolioData],
    scenario_yaml: Optional[str] = None, 
    delta: Optional[str] = None,
    *,
    return_data: bool = False,
    risk_limits_yaml: Union[str, RiskLimitsData, Dict[str, Any], None] = "risk_limits.yaml"
) -> Union[None, WhatIfResult]:
    """
    Execute a single *what-if* scenario on an existing portfolio.

    The function loads the base portfolio & firm-wide risk limits,
    applies either a YAML-defined scenario **or** an inline `delta`
    string, and prints a full before/after risk report.

    Parameters
    ----------
    filepath : str
        Path to the primary portfolio YAML file (same schema as
        ``run_portfolio``).
    scenario_yaml : str, optional
        Path to a YAML file that contains a ``new_weights`` or ``delta``
        section (see ``helpers_input.parse_delta`` for precedence rules).
        If supplied, this file overrides any `delta` string.
    delta : str, optional
        Comma-separated inline weight shifts, e.g.
        ``"TW:+500bp,PCTY:-200bp"``.  Ignored when `scenario_yaml`
        contains a ``new_weights`` block.
    return_data : bool, default False
        If True, returns structured data instead of printing.
        If False, prints formatted output to stdout (existing behavior).
    risk_limits_yaml : str, default "risk_limits.yaml"
        Path to the risk limits YAML file.

    Returns
    -------
    None or WhatIfResult
        If return_data=False: Returns None, prints formatted output (existing behavior)
        If return_data=True: Returns WhatIfResult object with:
            - current_metrics: RiskAnalysisResult for current portfolio
            - scenario_metrics: RiskAnalysisResult for scenario portfolio  
            - scenario_name: Name of the scenario
            - risk_comparison: Before/after risk comparison data
            - beta_comparison: Before/after beta comparison data
            - to_api_response(): Convert to API dictionary format
            - to_cli_report(): Generate CLI formatted report

    Notes
    -----
    ▸ Does *not* return anything; all output is printed via
      ``print_what_if_report``.  
    ▸ Raises ``ValueError`` if neither YAML nor `delta`
      provide a valid change set.
    """
    
    # ─── Dual-Mode Logic ─────────────────────────────────────
    if return_data:
        # API MODE: Use original analyze_scenario directly (no file modifications)
        result = analyze_scenario(filepath, risk_limits_yaml, scenario_yaml, delta)
        return result
    else:
        if isinstance(filepath, str):
            # CLI MODE: Handle new ticker proxy injection before analysis
            portfolio_file_to_use, cleaned_delta = _handle_new_tickers_for_cli_with_validation(filepath, scenario_yaml, delta)
            result = analyze_scenario(portfolio_file_to_use, risk_limits_yaml, scenario_yaml, cleaned_delta)
        else:
            # In-memory mode skips file mutation logic used for CLI-only proxy injection.
            result = analyze_scenario(filepath, risk_limits_yaml, scenario_yaml, delta)
        print(result.to_cli_report())

# ============================================================================
# MIN VARIANCE OPTIMIZATION
# This handles minimum variance portfolio optimization
# ============================================================================
def run_min_variance(
    filepath: Union[str, PortfolioData],
    risk_yaml: Union[str, RiskLimitsData, Dict[str, Any], None] = "risk_limits.yaml",
    *,
    return_data: bool = False,
) -> Union[None, OptimizationResult]:
    """
    Run the minimum-variance optimiser under current risk limits.

    Steps
    -----
    1. Load portfolio & risk-limit YAML files.
    2. Convert raw position input into normalised weights.
    3. Call :pyfunc:`portfolio_optimizer.run_min_var` to solve for the
       lowest-variance weight vector that satisfies **all** firm-wide
       constraints.
    4. Display the resulting weights plus risk & beta check tables
       via OptimizationResult CLI formatting.

    Parameters
    ----------
    filepath : str
        Path to the portfolio YAML file (``start_date``, ``end_date``,
        ``portfolio_input``, etc.).
    return_data : bool, default False
        If True, returns structured data instead of printing.
        If False, prints formatted output to stdout (existing behavior).

    Returns
    -------
    None or OptimizationResult
        If return_data=False: Returns None, prints formatted output (existing behavior)
        If return_data=True: Returns OptimizationResult object with:
            - optimized_weights: Optimized portfolio weights
            - risk_table: Risk checks for optimized portfolio
            - beta_table: Beta checks for optimized portfolio
            - to_api_response(): Convert to API dictionary format
            - to_cli_report(): Generate CLI formatted report

    Raises
    ------
    ValueError
        Propagated from the optimiser if the constraints are infeasible.

    Side Effects
    ------------
    Prints the optimised weight allocation and PASS/FAIL tables to
    stdout; nothing is returned.
    """
    
    # --- BUSINESS LOGIC: Call core function that returns OptimizationResult ---
    result = optimize_min_variance(filepath, risk_yaml)  # Returns OptimizationResult
    
    # ─── Dual-Mode Logic ─────────────────────────────────────
    if return_data:
        # API MODE: Return OptimizationResult object
        return result
    else:
        # CLI MODE: Print formatted output  
        print(result.to_cli_report())

# ============================================================================
# MAX RETURN OPTIMIZATION
# This handles maximum return portfolio optimization
# ============================================================================
def run_max_return(
    filepath: Union[str, PortfolioData],
    risk_yaml: Union[str, RiskLimitsData, Dict[str, Any], None] = "risk_limits.yaml",
    *,
    return_data: bool = False,
) -> Union[None, OptimizationResult]:
    """
    Solve for the highest-return portfolio that still passes all
    volatility, concentration, and beta limits.

    Workflow
    --------
    * Parse the portfolio and risk-limit YAMLs.
    * Standardise the raw positions → weights.
    * Call :pyfunc:`portfolio_optimizer.run_max_return_portfolio` to
      perform a convex QP that maximises expected return subject to:
        – portfolio σ cap  
        – single-name weight cap  
        – factor & industry beta caps
    * Print the final weight vector and the associated risk / beta
      check tables via :pyfunc:`portfolio_optimizer.print_max_return_report`.

    Parameters
    ----------
    filepath : str
        Path to the portfolio YAML file.
    return_data : bool, default False
        If True, returns structured data instead of printing.
        If False, prints formatted output to stdout (existing behavior).

    Returns
    -------
    None or Dict[str, Any]
        If return_data=False: Returns None, prints formatted output (existing behavior)
        If return_data=True: Returns structured data dictionary with:
            - optimized_weights: Optimized portfolio weights
            - portfolio_summary: Portfolio view of optimized weights
            - risk_analysis: Risk checks for optimized portfolio
            - beta_analysis: Factor and proxy beta checks for optimized portfolio
            - optimization_metadata: Optimization configuration and results

    Notes
    -----
    * Uses the **expected_returns** section inside the portfolio YAML for
      the objective function.  Missing tickers default to 0 % expected
      return.
    * All output is written to stdout; the function does not return
      anything.
    """
    
    # --- BUSINESS LOGIC: Call core function (now returns OptimizationResult) -----
    result = optimize_max_return(filepath, risk_yaml)  # Returns OptimizationResult directly
    
    # ─── Simplified Dual-Mode Logic ─────────────────────────────────────
    if return_data:
        # API MODE: Return OptimizationResult object
        return result
    else:
        # CLI MODE: Print formatted output  
        print(result.to_cli_report())

# ============================================================================
# STOCK ANALYSIS
# This handles individual stock risk analysis
# ============================================================================
def run_stock(
    ticker: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    factor_proxies: Optional[Dict[str, Union[str, List[str]]]] = None,
    *,
    return_data: bool = False
) -> Union[None, StockAnalysisResult]:
    """
    Runs stock risk diagnostics. If factor_proxies are provided, runs detailed multi-factor profile.
    If factor_proxies is None, auto-generates intelligent factor proxies for comprehensive analysis.

    Args:
        ticker (str): Stock symbol.
        start (Optional[str]): Start date in YYYY-MM-DD format. Defaults to 5 years ago.
        end (Optional[str]): End date in YYYY-MM-DD format. Defaults to today.
        factor_proxies (Optional[Dict[str, Union[str, List[str]]]]): Optional factor mapping.
        return_data (bool): If True, returns structured data instead of printing.

    Returns:
        None or StockAnalysisResult: If return_data=False, returns None and prints formatted output.
                                    If return_data=True, returns StockAnalysisResult object with:
                                        - ticker: Stock symbol analyzed
                                        - volatility_metrics: Historical volatility statistics  
                                        - regression_metrics: Market beta analysis
                                        - factor_summary: Multi-factor exposure analysis
                                        - to_api_response(): Convert to API dictionary format
                                        - to_cli_report(): Generate CLI formatted report
    """
    # --- BUSINESS LOGIC: Call core function (now returns StockAnalysisResult) -----
    result = analyze_stock(ticker, start, end, factor_proxies)  # Returns StockAnalysisResult directly
    
    # ─── Dual-Mode Logic ─────────────────────────────────────
    if return_data:
        # API MODE: Return StockAnalysisResult object directly
        return result
    else:
        # CLI MODE: Print formatted output  
        print(result.to_cli_report())

# ============================================================================
# PERFORMANCE ANALYSIS
# This handles portfolio performance calculation and analysis
# ============================================================================
@log_errors("high")
@log_operation("portfolio_performance")
@log_timing(5.0)
def run_portfolio_performance(filepath: str, *, return_data: bool = False, benchmark_ticker: str = "SPY") -> Union[None, PerformanceResult, Dict[str, Any]]:
    """
    Calculate and display comprehensive portfolio performance metrics.

    Called by:
    - CLI workflows and MCP/service wrappers needing performance metrics.

    Calls into:
    - `core.performance_analysis.analyze_performance`.

    Contract:
    - Returns `PerformanceResult` in data mode.
    - Prints formatted report in CLI mode.
    
    Simplified dual-mode wrapper around core analyze_performance() function.
    Uses PerformanceResult object's built-in formatting for consistent output.

    Parameters
    ----------
    filepath : str
        Path to the portfolio YAML file.
    return_data : bool, optional
        If True, return PerformanceResult object for programmatic usage. If False, print formatted output.
    benchmark_ticker : str, optional
        Benchmark ticker symbol for comparison (default: "SPY").

    Returns
    -------
    PerformanceResult or None
        If return_data=True, returns PerformanceResult object.
        If return_data=False, prints CLI-formatted output and returns None.

    Notes
    -----
    * Delegates to core.performance_analysis.analyze_performance()
    * Uses PerformanceResult.to_api_response() for API mode
    * Uses PerformanceResult.to_cli_report() for CLI mode
    * Error cases return/print error information directly
    """
    # Get performance analysis result
    performance_result = analyze_performance(filepath, benchmark_ticker)
    
    # Handle error case (returns dict on error, PerformanceResult on success)
    if isinstance(performance_result, dict) and "error" in performance_result:
        if return_data:
            return performance_result  # Return error dict for API
        else:
            print(f"❌ Performance calculation failed: {performance_result['error']}")
            return
    
    # Handle success case - use PerformanceResult's built-in formatting
    if return_data:
        return performance_result  # Return PerformanceResult object for programmatic use
    else:
        print(performance_result.to_cli_report())


def run_risk_score(
    portfolio_yaml: Union[str, PortfolioData] = "portfolio.yaml",
    risk_yaml: Union[str, RiskLimitsData, Dict[str, Any], None] = "risk_limits.yaml",
    *,
    return_data: bool = False,
) -> Union[None, RiskScoreResult]:
    """
    CLI wrapper for portfolio risk score analysis with dual-mode support.
    
    This function provides a consistent interface for risk score analysis that matches
    the pattern of other CLI functions in this module, with support for both CLI
    display and programmatic data return.
    
    Args:
        portfolio_yaml: Path to portfolio configuration file
        risk_yaml: Path to risk limits configuration file  
        return_data: If True, return RiskScoreResult object instead of printing
        
    Returns:
        RiskScoreResult when return_data=True, None when printing to CLI
        
    Example:
        # CLI mode (default)
        run_risk_score("my_portfolio.yaml", "conservative_limits.yaml")
        
        # API/programmatic mode
        result = run_risk_score("portfolio.yaml", return_data=True)
        api_response = result.to_api_response()
    """
    from portfolio_risk_score import run_risk_score_analysis
    
    # Call the core analysis function
    result = run_risk_score_analysis(portfolio_yaml, risk_yaml, return_data=True)
    
    if return_data:
        # API/Data mode - return the result object for programmatic use
        return result
    else:
        # CLI mode - print formatted output and return None
        print(result.to_cli_report())
        return None


def run_realized_performance(
    user_email: Optional[str] = None,
    *,
    benchmark_ticker: str = "SPY",
    source: str = "all",
    institution: Optional[str] = None,
    return_data: bool = False,
) -> Optional[Union["RealizedPerformanceResult", Dict[str, Any]]]:
    """
    Run realized performance analysis from brokerage transaction history.

    Unlike hypothetical performance (--performance), this reconstructs actual
    portfolio returns from trade history using cash-inclusive NAV and Modified Dietz TWR.

    Parameters
    ----------
    user_email : str, optional
        User email for fetching positions/transactions. Falls back to
        TEST_USER_EMAIL env var, then RISK_MODULE_USER_EMAIL.
    benchmark_ticker : str
        Benchmark ticker for comparison (default: "SPY").
    source : str
        Transaction source filter: "all", "snaptrade", or "plaid".
    institution : str, optional
        Filter by institution/brokerage (realized performance only).
    return_data : bool
        If True, return raw result dict instead of printing.

    Returns
    -------
    RealizedPerformanceResult or dict or None
        If return_data=True, returns typed result on success or error dict on failure.
        Otherwise prints report.
    """
    import os
    from services.position_service import PositionService
    from services.portfolio_service import PortfolioService
    from mcp_tools.performance import _format_realized_report
    from settings import get_default_user

    # Resolve user email: explicit > TEST_USER_EMAIL > RISK_MODULE_USER_EMAIL
    user = user_email or os.getenv("TEST_USER_EMAIL") or get_default_user()
    if not user:
        print("Error: No user email provided. Use --user-email or set TEST_USER_EMAIL / RISK_MODULE_USER_EMAIL.")
        return None

    print(
        "Running realized performance for "
        f"{user} (source={source}, benchmark={benchmark_ticker}, institution={institution or 'all'})..."
    )

    # Fetch live brokerage positions
    position_service = PositionService(user)
    position_result = position_service.get_all_positions(consolidate=(institution is None))

    if not position_result.data.positions:
        print("Error: No brokerage positions found.")
        return None

    # Run realized performance analysis via service layer
    result = PortfolioService(cache_results=True).analyze_realized_performance(
        position_result=position_result,
        user_email=user,
        benchmark_ticker=benchmark_ticker,
        source=source,
        institution=institution,
    )

    if isinstance(result, dict) and result.get("status") == "error":
        print(f"Error: {result.get('message', 'Realized performance analysis failed')}")
        return result if return_data else None

    if return_data:
        return result

    # Print formatted report
    print()
    print(_format_realized_report(result.to_dict(), benchmark_ticker))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--portfolio", type=str, help="Path to YAML portfolio file")
    parser.add_argument("--stock", type=str, help="Ticker symbol")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")

    parser.add_argument("--factor-proxies", type=str, help='JSON string of factor proxies for multi-factor analysis. Common factors: market, momentum, value, industry, subindustry. Example: \'{"market": "SPY", "momentum": "MTUM", "value": "IWD", "industry": "XLK", "subindustry": ["MSFT", "GOOGL"]}\'')
    parser.add_argument("--whatif", action="store_true", help="Run what-if scenario")
    parser.add_argument("--minvar", action="store_true", help="Run min-variance optimization")
    parser.add_argument("--maxreturn", action="store_true", help="Run max-return optimization")
    parser.add_argument("--performance", action="store_true", help="Run portfolio performance analysis")
    parser.add_argument("--risk-score", action="store_true", help="Run portfolio risk score analysis")
    parser.add_argument("--scenario", type=str, help="Path to what-if scenario YAML file")
    parser.add_argument("--delta", type=str, help='Inline weight shifts, e.g. "TW:+500bp,PCTY:-200bp"')
    parser.add_argument("--inject_proxies", action="store_true", help="Inject market, industry, and optional subindustry proxies")
    parser.add_argument("--use_gpt", action="store_true", help="Enable GPT-generated subindustry peers (used with --inject_proxies)")
    parser.add_argument("--gpt", action="store_true", help="Run the portfolio report and send the output to GPT for a plain-English summary")
    parser.add_argument("--realized-performance", action="store_true",
                        help="Run realized performance from transaction history")
    parser.add_argument("--user-email", type=str,
                        help="User email (required for realized performance, or set TEST_USER_EMAIL)")
    parser.add_argument("--source", choices=["all", "snaptrade", "plaid"], default="all",
                        help="Transaction source filter (realized performance only)")
    parser.add_argument("--institution", default=None,
                        help="Filter by institution name (realized performance only)")
    parser.add_argument("--benchmark", type=str, default="SPY",
                        help="Benchmark ticker for performance comparison")
    args = parser.parse_args()

    if args.portfolio and args.inject_proxies:
        from proxy_builder import inject_all_proxies
        inject_all_proxies(args.portfolio, use_gpt_subindustry=args.use_gpt)
    
    elif args.portfolio and args.whatif:
        run_what_if(args.portfolio, scenario_yaml=args.scenario, delta=args.delta)
    
    elif args.portfolio and args.minvar:
        run_min_variance(args.portfolio)
    
    elif args.portfolio and args.maxreturn:
        run_max_return(args.portfolio)

    elif args.portfolio and args.performance:
        run_portfolio_performance(args.portfolio)

    elif args.realized_performance:
        run_realized_performance(
            user_email=args.user_email,
            benchmark_ticker=args.benchmark,
            source=args.source,
            institution=args.institution,
        )

    elif args.portfolio and getattr(args, 'risk_score', False):
        run_risk_score(args.portfolio)
        
    elif args.portfolio and args.gpt:
        run_and_interpret(args.portfolio)
    
    elif args.portfolio:
        run_portfolio(args.portfolio)
    
    elif args.stock and args.start and args.end:
        # Parse factor proxies from JSON string if provided
        factor_proxies = None
        if args.factor_proxies:
            try:
                import json
                factor_proxies = json.loads(args.factor_proxies)
            except json.JSONDecodeError as e:
                print(f"❌ Error parsing factor proxies JSON: {e}")
                print("   Example format: '{\"market\": \"SPY\", \"momentum\": \"MTUM\", \"value\": \"IWD\", \"industry\": \"XLK\", \"subindustry\": [\"MSFT\", \"GOOGL\"]}'")
                parser.print_help()
                exit(1)
        
        # Run stock analysis with all parameters
        run_stock(
            ticker=args.stock,
            start=args.start,
            end=args.end,
            factor_proxies=factor_proxies
        )
    
    else:
        parser.print_help()


# In[ ]:

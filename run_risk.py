#!/usr/bin/env python3
# coding: utf-8

# In[ ]:


# File: run_risk.py

import argparse
import yaml
from contextlib import redirect_stdout 
from typing import Optional, Dict, Union, List, Any
import pandas as pd
from io import StringIO
import numpy as np
from datetime import datetime

from risk_summary import (
    get_detailed_stock_factor_profile,
    get_stock_risk_profile
)
from run_portfolio_risk import (
    latest_price,
    load_portfolio_config,
    display_portfolio_config,
    standardize_portfolio_input,
    display_portfolio_summary,
    evaluate_portfolio_beta_limits,
    evaluate_portfolio_risk_limits,
)
from portfolio_risk import build_portfolio_view
from portfolio_optimizer import (
    run_what_if_scenario,
    print_what_if_report,
    run_min_var,
    print_min_var_report,
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
from helpers_display import format_stock_metrics
from utils.serialization import make_json_safe, _format_portfolio_output_as_text
from core.portfolio_analysis import analyze_portfolio

# Import logging decorators
from utils.logging import (
    log_error_handling,
    log_portfolio_operation_decorator,
    log_performance
)
from core.scenario_analysis import analyze_scenario
from core.optimization import optimize_min_variance, optimize_max_return
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
def run_and_interpret(portfolio_yaml: str, *, return_data: bool = False):
    """
    Convenience wrapper:

        1. runs `run_portfolio(portfolio_yaml)`
        2. captures everything it prints
        3. feeds that text to GPT for a summary
        4. prints **both** the GPT summary *and* the raw diagnostics
        5. returns the GPT summary string

    Parameters
    ----------
    portfolio_yaml : str
        Path to the portfolio configuration YAML.
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
    """
    # --- BUSINESS LOGIC: Call extracted core function ---------------------
    interpretation_result = analyze_and_interpret(portfolio_yaml)
    
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
# This handles AI interpretation of structured portfolio output
# ============================================================================
@log_error_handling("high")
@log_portfolio_operation_decorator("ai_interpretation")
@log_performance(3.0)
def interpret_portfolio_output(portfolio_output: Dict[str, Any], *, 
                              portfolio_name: Optional[str] = None,
                              return_data: bool = False):
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

@log_error_handling("high")
@log_portfolio_operation_decorator("portfolio_analysis")
@log_performance(5.0)
def run_portfolio(filepath: str, *, return_data: bool = False):
    """
    High-level "one-click" entry-point for a full portfolio risk run.

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
    filepath : str
        Path to the *portfolio* YAML ( **not** the risk-limits file ).
        The function expects the YAML schema
        (`start_date`, `end_date`, `portfolio_input`, `stock_factor_proxies`, …).
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
    analysis_result = analyze_portfolio(filepath)
    
    # Extract components for compatibility with dual-mode logic
    summary = analysis_result["portfolio_summary"]
    df_risk = pd.DataFrame(analysis_result["risk_analysis"]["risk_checks"])
    df_beta = pd.DataFrame(analysis_result["beta_analysis"]["beta_checks"])
    max_betas = analysis_result["beta_analysis"]["max_betas"]
    max_betas_by_proxy = analysis_result["beta_analysis"]["max_betas_by_proxy"]
    weights = analysis_result["analysis_metadata"]["weights"]
    lookback_years = analysis_result["analysis_metadata"]["lookback_years"]
    
    # Load config for CLI display (needed for return_data mode)
    # LOGGING: Add portfolio config load timing
    config = load_portfolio_config(filepath)
    with open("risk_limits.yaml", "r") as f:
        risk_config = yaml.safe_load(f)

    # ─── 5. Dual-Mode Logic ─────────────────────────────────
    if return_data:
        # API MODE: Capture CLI output and return structured data
        from io import StringIO
        import contextlib
        
        # Capture the CLI output
        buf = StringIO()
        with contextlib.redirect_stdout(buf):
            display_portfolio_config(config)
            display_portfolio_summary(summary)
            
            # Display Risk Rules
            print("\n=== Portfolio Risk Limit Checks ===")
            for _, row in df_risk.iterrows():
                status = "→ PASS" if row["Pass"] else "→ FAIL"
                print(f"{row['Metric']:<22} {row['Actual']:.2%}  ≤ {row['Limit']:.2%}  {status}")

            # Display Beta Limits
            print("\n=== Beta Exposure Checks ===")
            for _, row in df_beta.iterrows():
                factor = row['factor']  # Factor names are now in 'factor' column
                status = "→ PASS" if row["pass"] else "→ FAIL"
                print(f"{factor:<20} β = {row['portfolio_beta']:+.2f}  ≤ {row['max_allowed_beta']:.2f}  {status}")
        
        # Return structured data with captured CLI output
        return {
            "portfolio_summary": summary,
            "risk_analysis": {
                "risk_checks": df_risk.to_dict('records'),
                "risk_passes": bool(df_risk['Pass'].all()),
                "risk_violations": df_risk[~df_risk['Pass']].to_dict('records'),
                "risk_limits": {
                    "portfolio_limits": risk_config["portfolio_limits"],
                    "concentration_limits": risk_config["concentration_limits"],
                    "variance_limits": risk_config["variance_limits"]
                }
            },
            "beta_analysis": {
                "beta_checks": df_beta.reset_index().to_dict('records'),
                "beta_passes": bool(df_beta['pass'].all()),
                "beta_violations": df_beta[~df_beta['pass']].reset_index().to_dict('records'),
                "max_betas": max_betas,
                "max_betas_by_proxy": max_betas_by_proxy
            },
            "analysis_metadata": {
                "analysis_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "portfolio_file": filepath,
                "lookback_years": lookback_years,
                "weights": weights,
                "total_positions": len(weights),
                "active_positions": len([v for v in weights.values() if abs(v) > 0.001])
            },
            "formatted_report": buf.getvalue()
        }
        # LOGGING: Add portfolio analysis completion logging with execution time
        # LOGGING: Add workflow state logging for risk analysis workflow completion here
        # LOGGING: Add resource usage monitoring for analysis completion here
    else:
        # CLI MODE: Print formatted output
        display_portfolio_config(config)
        display_portfolio_summary(summary)
        
        # Display Risk Rules
        print("\n=== Portfolio Risk Limit Checks ===")
        for _, row in df_risk.iterrows():
            status = "→ PASS" if row["Pass"] else "→ FAIL"
            print(f"{row['Metric']:<22} {row['Actual']:.2%}  ≤ {row['Limit']:.2%}  {status}")

        # Display Beta Limits
        print("\n=== Beta Exposure Checks ===")
        for _, row in df_beta.iterrows():
            factor = row['factor']  # Factor names are now in 'factor' column
            status = "→ PASS" if row["pass"] else "→ FAIL"
            print(f"{factor:<20} β = {row['portfolio_beta']:+.2f}  ≤ {row['max_allowed_beta']:.2f}  {status}")

        # LOGGING: Add portfolio analysis completion logging with execution time

# ============================================================================
# WHAT-IF SCENARIO LOGIC
# This handles what-if scenario analysis
# ============================================================================
def run_what_if(
    filepath: str, 
    scenario_yaml: Optional[str] = None, 
    delta: Optional[str] = None,
    *,
    return_data: bool = False
):
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

    Returns
    -------
    None or Dict[str, Any]
        If return_data=False: Returns None, prints formatted output (existing behavior)
        If return_data=True: Returns structured data dictionary with:
            - scenario_summary: Portfolio view after scenario changes
            - risk_analysis: Risk checks for scenario portfolio
            - beta_analysis: Beta checks for scenario portfolio
            - comparison_analysis: Before/after comparison data
            - scenario_metadata: Scenario configuration and metadata

    Notes
    -----
    ▸ Does *not* return anything; all output is printed via
      ``print_what_if_report``.  
    ▸ Raises ``ValueError`` if neither YAML nor `delta`
      provide a valid change set.
    """
    
    # --- BUSINESS LOGIC: Call extracted core function ----------------------
    scenario_result = analyze_scenario(filepath, scenario_yaml, delta)
    
    # Extract components for compatibility with dual-mode logic
    summary = scenario_result["raw_tables"]["summary"]
    summary_base = scenario_result["raw_tables"]["summary_base"]  # Extract original portfolio
    risk_new = scenario_result["raw_tables"]["risk_new"]
    beta_f_new = scenario_result["raw_tables"]["beta_f_new"]
    beta_p_new = scenario_result["raw_tables"]["beta_p_new"]
    cmp_risk = scenario_result["raw_tables"]["cmp_risk"]
    cmp_beta = scenario_result["raw_tables"]["cmp_beta"]
    
    # ─── Dual-Mode Logic ─────────────────────────────────────
    if return_data:
        # API MODE: Return structured data from extracted function
        from io import StringIO
        from contextlib import redirect_stdout
        
        # Create formatted report by capturing print output
        report_buffer = StringIO()
        with redirect_stdout(report_buffer):
            print_what_if_report(
                summary_new=summary,
                summary_old=summary_base,  # Add original portfolio for before/after comparison
                risk_new=risk_new,
                beta_f_new=beta_f_new,
                beta_p_new=beta_p_new,
                cmp_risk=cmp_risk,
                cmp_beta=cmp_beta,
            )
        formatted_report = report_buffer.getvalue()
        
        # Add formatted report to scenario result and return
        scenario_result["formatted_report"] = formatted_report
        return scenario_result
    else:
        # CLI MODE: Print formatted output
        print_what_if_report(
            summary_new=summary,
            summary_old=summary_base,  # Add original portfolio for before/after comparison
            risk_new=risk_new,
            beta_f_new=beta_f_new,
            beta_p_new=beta_p_new,
            cmp_risk=cmp_risk,
            cmp_beta=cmp_beta,
        )

# ============================================================================
# MIN VARIANCE OPTIMIZATION
# This handles minimum variance portfolio optimization
# ============================================================================
def run_min_variance(filepath: str, *, return_data: bool = False):
    """
    Run the minimum-variance optimiser under current risk limits.

    Steps
    -----
    1. Load portfolio & risk-limit YAML files.
    2. Convert raw position input into normalised weights.
    3. Call :pyfunc:`portfolio_optimizer.run_min_var` to solve for the
       lowest-variance weight vector that satisfies **all** firm-wide
       constraints.
    4. Pretty-print the resulting weights plus risk & beta check tables
       via :pyfunc:`portfolio_optimizer.print_min_var_report`.

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
    None or Dict[str, Any]
        If return_data=False: Returns None, prints formatted output (existing behavior)
        If return_data=True: Returns structured data dictionary with:
            - optimized_weights: Optimized portfolio weights
            - risk_analysis: Risk checks for optimized portfolio
            - beta_analysis: Beta checks for optimized portfolio
            - optimization_metadata: Optimization configuration and results

    Raises
    ------
    ValueError
        Propagated from the optimiser if the constraints are infeasible.

    Side Effects
    ------------
    Prints the optimised weight allocation and PASS/FAIL tables to
    stdout; nothing is returned.
    """
    
    # --- BUSINESS LOGIC: Call extracted core function ---------------------
    optimization_result = optimize_min_variance(filepath)
    
    # Extract components for compatibility with dual-mode logic
    w = optimization_result["raw_tables"]["weights"]
    r = optimization_result["raw_tables"]["risk_table"]
    b = optimization_result["raw_tables"]["beta_table"]
    
    # ─── Dual-Mode Logic ─────────────────────────────────────
    if return_data:
        # API MODE: Return structured data from extracted function
        from core.result_objects import OptimizationResult
        
        # Create OptimizationResult object for formatted report
        optimization_obj = OptimizationResult.from_min_variance_output(
            optimized_weights=w,
            risk_table=r,
            beta_table=b
        )
        
        # Add formatted report to optimization result and return
        optimization_result["formatted_report"] = optimization_obj.to_formatted_report()
        return optimization_result
    else:
        # CLI MODE: Print formatted output
        print_min_var_report(weights=w, risk_tbl=r, beta_tbl=b)

# ============================================================================
# MAX RETURN OPTIMIZATION
# This handles maximum return portfolio optimization
# ============================================================================
def run_max_return(filepath: str, *, return_data: bool = False):
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
    
    # --- BUSINESS LOGIC: Call extracted core function ---------------------
    optimization_result = optimize_max_return(filepath)
    
    # Extract components for compatibility with dual-mode logic
    w = optimization_result["raw_tables"]["weights"]
    summary = optimization_result["raw_tables"]["summary"]
    r = optimization_result["raw_tables"]["risk_table"]
    f_b = optimization_result["raw_tables"]["factor_table"]
    p_b = optimization_result["raw_tables"]["proxy_table"]
    
    # ─── Dual-Mode Logic ─────────────────────────────────────
    if return_data:
        # API MODE: Return structured data from extracted function
        from core.result_objects import OptimizationResult
        from io import StringIO
        import contextlib
        
        # Create result object for structured data
        optimization_obj = OptimizationResult.from_max_return_output(
            optimized_weights=w,
            portfolio_summary=summary,
            risk_table=r,
            factor_table=f_b,
            proxy_table=p_b
        )
        
        # Capture the formatted report by running the CLI logic
        report_buffer = StringIO()
        with contextlib.redirect_stdout(report_buffer):
            print_max_return_report(weights=w, risk_tbl=r, df_factors=f_b, df_proxies=p_b)
        
        formatted_report = report_buffer.getvalue()
        
        # Add formatted report to optimization result and return
        optimization_result["formatted_report"] = formatted_report
        return optimization_result
    else:
        # CLI MODE: Print formatted output
        print_max_return_report(weights=w, risk_tbl=r, df_factors=f_b, df_proxies=p_b)

# ============================================================================
# STOCK ANALYSIS
# This handles individual stock risk analysis
# ============================================================================
def run_stock(
    ticker: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    factor_proxies: Optional[Dict[str, Union[str, List[str]]]] = None,
    yaml_path: Optional[str] = None, 
    *,
    return_data: bool = False
):
    """
    Runs stock risk diagnostics. If factor_proxies are provided, runs detailed multi-factor profile.
    Otherwise, if ``yaml_path`` is supplied, the function looks for the
    ticker under ``stock_factor_proxies`` in that YAML.
    If neither is found, falls back to simple regression vs. market benchmark.

    Args:
        ticker (str): Stock symbol.
        start (Optional[str]): Start date in YYYY-MM-DD format. Defaults to 5 years ago.
        end (Optional[str]): End date in YYYY-MM-DD format. Defaults to today.
        factor_proxies (Optional[Dict[str, Union[str, List[str]]]]): Optional factor mapping.
        yaml_path (Optional[str]): Path to YAML file for factor proxy lookup.
        return_data (bool): If True, returns structured data instead of printing.

    Returns:
        None or Dict[str, Any]: If return_data=False, returns None and prints formatted output.
                                If return_data=True, returns structured data dictionary.
    """
    # --- BUSINESS LOGIC: Call extracted core function ---------------------
    analysis_result = analyze_stock(ticker, start, end, factor_proxies, yaml_path)
    
    # Handle any YAML loading errors for CLI mode
    if factor_proxies is None and yaml_path and not return_data:
        try:
            cfg = load_portfolio_config(yaml_path)
            proxies = cfg.get("stock_factor_proxies", {})
            if not proxies.get(ticker.upper()):
                print(f"⚠️  Could not load proxies from YAML for {ticker}")
        except Exception as e:
            print(f"⚠️  Could not load proxies from YAML: {e}")
    
    # --- Dual-Mode Logic ---------------------------------------------------
    if return_data:
        # API MODE: Return structured data from extracted function
        from core.result_objects import StockAnalysisResult
        
        # Create StockAnalysisResult object for formatted report
        if analysis_result["analysis_type"] == "multi_factor":
            stock_result = StockAnalysisResult.from_stock_analysis(
                ticker=ticker,
                vol_metrics=analysis_result["volatility_metrics"],
                regression_metrics=analysis_result["regression_metrics"],
                factor_summary=analysis_result["factor_summary"]
            )
        else:
            stock_result = StockAnalysisResult.from_stock_analysis(
                ticker=ticker,
                vol_metrics=analysis_result["volatility_metrics"],
                regression_metrics=analysis_result["risk_metrics"],
                factor_summary=None
            )
        
        # Add formatted report to analysis result and return
        analysis_result["formatted_report"] = stock_result.to_formatted_report()
        return analysis_result
    else:
        # CLI MODE: Print formatted output based on analysis type
        if analysis_result["analysis_type"] == "multi_factor":
            format_stock_metrics(analysis_result["volatility_metrics"], "Volatility Metrics")
            format_stock_metrics(analysis_result["regression_metrics"], "Market Regression")
            
            print("=== Factor Summary ===")
            print(analysis_result["factor_summary"])
        else:
            format_stock_metrics(analysis_result["volatility_metrics"], "Volatility Metrics")
            format_stock_metrics(analysis_result["risk_metrics"], "Market Regression (SPY)")

# ============================================================================
# PERFORMANCE ANALYSIS
# This handles portfolio performance calculation and analysis
# ============================================================================
@log_error_handling("high")
@log_portfolio_operation_decorator("portfolio_performance")
@log_performance(5.0)
def run_portfolio_performance(filepath: str, *, return_data: bool = False):
    """
    Calculate and display comprehensive portfolio performance metrics.

    Workflow
    --------
    * Parse the portfolio YAML file.
    * Standardise the raw positions → weights.
    * Call :func:`portfolio_risk.calculate_portfolio_performance_metrics` to
      compute returns, volatility, Sharpe ratio, alpha, beta, max drawdown,
      and other risk-adjusted performance metrics vs benchmark.
    * Display results using :func:`run_portfolio_risk.display_portfolio_performance_metrics`.

    Parameters
    ----------
    filepath : str
        Path to the portfolio YAML file.
    return_data : bool, optional
        If True, return structured data for API usage. If False, print formatted output.

    Returns
    -------
    dict or None
        If return_data=True, returns structured performance metrics and metadata.
        If return_data=False, prints results and returns None.

    Notes
    -----
    * Uses the **start_date** and **end_date** from the portfolio YAML for
      the performance analysis window.
    * Defaults to SPY as benchmark but can be customized.
    * Uses 3-month Treasury rates from FMP API as risk-free rate.
    """
    # --- BUSINESS LOGIC: Call extracted core function ---------------------
    performance_result = analyze_performance(filepath)
    
    # Check for errors in the analysis result
    if "error" in performance_result:
        if return_data:
            # API MODE: Return error from extracted function
            return performance_result
        else:
            # CLI MODE: Print error and return
            print(f"❌ Performance calculation failed: {performance_result['error']}")
            return
    
    # --- Dual-Mode Logic ---------------------------------------------------
    if return_data:
        # API MODE: Return structured data from extracted function
        from run_portfolio_risk import display_portfolio_performance_metrics
        import io
        import sys
        
        # Capture CLI-style formatted output as string
        original_stdout = sys.stdout
        sys.stdout = captured_output = io.StringIO()
        
        try:
            # Generate the formatted CLI output
            display_portfolio_performance_metrics(performance_result["raw_data"]["performance_metrics"])
            formatted_report_string = captured_output.getvalue()
        finally:
            sys.stdout = original_stdout
        
        # Add formatted report to performance result and return
        performance_result["formatted_report"] = formatted_report_string
        return performance_result
    else:
        # CLI MODE: Print formatted output (original behavior)
        from run_portfolio_risk import display_portfolio_performance_metrics
        
        config = performance_result["raw_data"]["config"]
        weights = performance_result["raw_data"]["weights"]
        performance_metrics = performance_result["raw_data"]["performance_metrics"]
        
        print("📊 Portfolio Performance Analysis")
        print("=" * 50)
        
        print(f"📁 Portfolio file: {filepath}")
        print(f"📅 Analysis period: {config['start_date']} to {config['end_date']}")
        print(f"📊 Positions: {len(weights)}")
        print()
        
        print("🔄 Calculating performance metrics...")
        print("✅ Performance calculation successful!")
        
        # Display the results
        display_portfolio_performance_metrics(performance_metrics)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--portfolio", type=str, help="Path to YAML portfolio file")
    parser.add_argument("--stock", type=str, help="Ticker symbol")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--yaml-path", type=str, help="Path to YAML file for factor proxy lookup (for detailed stock analysis)")
    parser.add_argument("--factor-proxies", type=str, help='JSON string of factor proxies, e.g. \'{"market": "SPY", "momentum": "MTUM"}\'')
    parser.add_argument("--whatif", action="store_true", help="Run what-if scenario")
    parser.add_argument("--minvar", action="store_true", help="Run min-variance optimization")
    parser.add_argument("--maxreturn", action="store_true", help="Run max-return optimization")
    parser.add_argument("--performance", action="store_true", help="Run portfolio performance analysis")
    parser.add_argument("--scenario", type=str, help="Path to what-if scenario YAML file")
    parser.add_argument("--delta", type=str, help='Inline weight shifts, e.g. "TW:+500bp,PCTY:-200bp"')
    parser.add_argument("--inject_proxies", action="store_true", help="Inject market, industry, and optional subindustry proxies")
    parser.add_argument("--use_gpt", action="store_true", help="Enable GPT-generated subindustry peers (used with --inject_proxies)")
    parser.add_argument("--gpt", action="store_true", help="Run the portfolio report and send the output to GPT for a plain-English summary")
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
                print("   Example format: '{\"market\": \"SPY\", \"momentum\": \"MTUM\", \"value\": \"IWD\"}'")
                parser.print_help()
                exit(1)
        
        # Run stock analysis with all parameters
        run_stock(
            ticker=args.stock,
            start=args.start,
            end=args.end,
            factor_proxies=factor_proxies,
            yaml_path=args.yaml_path
        )
    
    else:
        parser.print_help()


# In[ ]:





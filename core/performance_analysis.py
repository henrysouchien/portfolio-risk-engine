#!/usr/bin/env python3
# coding: utf-8

"""
Core portfolio performance analysis business logic.

This module orchestrates the performance analysis pipeline, loading portfolio
configuration, standardizing inputs (including total portfolio value), and
producing a PerformanceResult suitable for API and CLI consumption. Dividend
metrics are included when available, using a current‑yield method integrated
into the performance engine.
"""

import pandas as pd
from typing import Dict, Any, Optional, Union
from datetime import datetime, UTC

from run_portfolio_risk import (
    load_portfolio_config,
    standardize_portfolio_input,
    latest_price,
)
from portfolio_risk import calculate_portfolio_performance_metrics
from utils.serialization import make_json_safe
from core.result_objects import PerformanceResult

# Import logging decorators for performance analysis
from utils.logging import (
    log_portfolio_operation_decorator,
    log_performance,
    log_error_handling
)


@log_error_handling("high")
@log_portfolio_operation_decorator("performance_analysis")
@log_performance(5.0)
def analyze_performance(filepath: str, benchmark_ticker: str = "SPY") -> Union[PerformanceResult, Dict[str, Any]]:
    """
    Core portfolio performance analysis business logic.
    
    This function contains the pure business logic extracted from run_portfolio_performance(),
    without any CLI or dual‑mode concerns. It also forwards total portfolio value to
    the performance engine so that dividend metrics can include estimated annual
    dividends and top contributors when available.
    
    Parameters
    ----------
    filepath : str
        Path to the portfolio YAML file.
    benchmark_ticker : str, optional
        Benchmark ticker symbol for comparison (default: "SPY").
        
    Returns
    -------
    Union[PerformanceResult, Dict[str, Any]]
        On success: PerformanceResult object with complete performance analysis
        On error: Dict with error information for backward compatibility
        
        Success case contains:
        - performance_metrics: Complete performance metrics (including dividend_metrics)
        - analysis_period: Analysis date range and duration  
        - portfolio_summary: Portfolio configuration summary
        - analysis_metadata: Analysis configuration and timestamps
        
    Raises
    ------
    FileNotFoundError
        If the portfolio file doesn't exist
    Exception
        If performance calculation fails
    """
    
    try:
        # Load portfolio configuration
        config = load_portfolio_config(filepath)
        
        # Standardize portfolio weights and capture total value for dividend estimates
        standardized_data = standardize_portfolio_input(config["portfolio_input"], latest_price)
        weights = standardized_data["weights"]
        total_value = standardized_data.get("total_value")
        
        # Calculate performance metrics
        performance_metrics = calculate_portfolio_performance_metrics(
            weights=weights,
            start_date=config["start_date"],
            end_date=config["end_date"],
            benchmark_ticker=benchmark_ticker,
            total_value=total_value
        )
        
        # Check for calculation errors
        if "error" in performance_metrics:
            # Return error in structured format with debugging context
            return make_json_safe({
                "error": performance_metrics["error"],
                "analysis_period": {
                    "start_date": config["start_date"],
                    "end_date": config["end_date"]
                },
                "portfolio_file": filepath,
                "benchmark_ticker": benchmark_ticker,
                "analysis_date": datetime.now(UTC).isoformat(),
                "debug_context": {
                    "weights": weights,
                    "portfolio_positions": len(weights),
                    "config_keys": list(config.keys())
                }
            })
        
        # Return PerformanceResult object using from_core_analysis() builder
        return PerformanceResult.from_core_analysis(
            performance_metrics=performance_metrics,
            analysis_period={
                "start_date": config["start_date"],
                "end_date": config["end_date"],
                "years": performance_metrics["analysis_period"]["years"]
            },
            portfolio_summary={
                "file": filepath,
                "positions": len(weights),
                "benchmark": benchmark_ticker
            },
            analysis_metadata={
                "analysis_date": datetime.now(UTC).isoformat(),
                "portfolio_file": filepath,
                "benchmark_ticker": benchmark_ticker
            },
            allocations=weights  # Pass weights as allocations for position counting
        )
        
    except FileNotFoundError:
        # Return error in structured format
        return make_json_safe({
            "error": f"Portfolio file '{filepath}' not found",
            "portfolio_file": filepath,
            "analysis_date": datetime.now(UTC).isoformat()
        })
    except Exception as e:
        # Return error in structured format
        return make_json_safe({
            "error": f"Error during performance analysis: {str(e)}",
            "portfolio_file": filepath,
            "analysis_date": datetime.now(UTC).isoformat()
        }) 

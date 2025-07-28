#!/usr/bin/env python3
# coding: utf-8

"""
Core portfolio performance analysis business logic.
Extracted from run_risk.py as part of the refactoring to create a clean service layer.
"""

import pandas as pd
from typing import Dict, Any, Optional

from run_portfolio_risk import (
    load_portfolio_config,
    standardize_portfolio_input,
    latest_price,
)
from portfolio_risk import calculate_portfolio_performance_metrics
from utils.serialization import make_json_safe

# Import logging decorators for performance analysis
from utils.logging import (
    log_portfolio_operation_decorator,
    log_performance,
    log_error_handling
)


@log_error_handling("high")
@log_portfolio_operation_decorator("performance_analysis")
@log_performance(5.0)
def analyze_performance(filepath: str) -> Dict[str, Any]:
    """
    Core portfolio performance analysis business logic.
    
    This function contains the pure business logic extracted from run_portfolio_performance(),
    without any CLI or dual-mode concerns.
    
    Parameters
    ----------
    filepath : str
        Path to the portfolio YAML file.
        
    Returns
    -------
    Dict[str, Any]
        Structured performance analysis results containing:
        - performance_metrics: Complete performance metrics
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
        
        # Standardize portfolio weights  
        weights = standardize_portfolio_input(config["portfolio_input"], latest_price)["weights"]
        
        # Calculate performance metrics
        performance_metrics = calculate_portfolio_performance_metrics(
            weights=weights,
            start_date=config["start_date"],
            end_date=config["end_date"],
            benchmark_ticker="SPY"  # Could make this configurable later
        )
        
        # Check for calculation errors
        if "error" in performance_metrics:
            # Return error in structured format
            return make_json_safe({
                "error": performance_metrics["error"],
                "analysis_period": {
                    "start_date": config["start_date"],
                    "end_date": config["end_date"]
                },
                "portfolio_file": filepath,
                "analysis_date": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
            })
        
        # Return structured performance analysis results
        return make_json_safe({
            "performance_metrics": performance_metrics,
            "analysis_period": {
                "start_date": config["start_date"],
                "end_date": config["end_date"],
                "years": performance_metrics["analysis_period"]["years"]
            },
            "portfolio_summary": {
                "file": filepath,
                "positions": len(weights),
                "benchmark": "SPY"
            },
            "analysis_metadata": {
                "analysis_date": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
                "calculation_successful": True
            },
            "raw_data": {
                "config": config,
                "weights": weights,
                "performance_metrics": performance_metrics
            }
        })
        
    except FileNotFoundError:
        # Return error in structured format
        return make_json_safe({
            "error": f"Portfolio file '{filepath}' not found",
            "portfolio_file": filepath,
            "analysis_date": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
        })
    except Exception as e:
        # Return error in structured format
        return make_json_safe({
            "error": f"Error during performance analysis: {str(e)}",
            "portfolio_file": filepath,
            "analysis_date": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
        }) 
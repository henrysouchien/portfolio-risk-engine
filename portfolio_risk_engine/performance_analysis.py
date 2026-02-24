#!/usr/bin/env python3
# coding: utf-8

"""
Core portfolio performance analysis business logic.

Agent orientation:
    Canonical pure-function performance entrypoint used beneath service and CLI
    wrappers. Start here when performance API/CLI outputs diverge.

Called by:
    - ``run_risk.run_portfolio_performance`` (dual-mode wrapper)
    - ``services.portfolio_service.PortfolioService.analyze_performance``

Primary flow:
    1) Load portfolio config.
    2) Standardize weights and total value.
    3) Run performance engine.
    4) Return ``PerformanceResult`` or error payload.
"""

import pandas as pd
from typing import Dict, Any, Optional, Union
from datetime import datetime, UTC

from portfolio_risk_engine.portfolio_config import (
    load_portfolio_config,
    standardize_portfolio_input,
    latest_price,
)
from portfolio_risk_engine.portfolio_risk import calculate_portfolio_performance_metrics
from portfolio_risk_engine._vendor import make_json_safe
from portfolio_risk_engine.results import PerformanceResult

# Import logging decorators for performance analysis
from portfolio_risk_engine._logging import (
    log_operation,
    log_timing,
    log_errors,
)


@log_errors("high")
@log_operation("performance_analysis")
@log_timing(5.0)
def analyze_performance(filepath: str, benchmark_ticker: str = "SPY") -> Union[PerformanceResult, Dict[str, Any]]:
    """
    Run pure portfolio performance analysis for one portfolio config.

    Contract notes:
    - Success path returns ``PerformanceResult``.
    - Error path returns legacy dict payload for backward compatibility.
    - Dividend metrics depend on total portfolio value threading.
    
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
        standardized_data = standardize_portfolio_input(
            config["portfolio_input"],
            price_fetcher,
            currency_map=currency_map,
            fmp_ticker_map=fmp_ticker_map,
        )
        weights = standardized_data["weights"]
        total_value = standardized_data.get("total_value")
        
        # Calculate performance metrics
        performance_metrics = calculate_portfolio_performance_metrics(
            weights=weights,
            start_date=config["start_date"],
            end_date=config["end_date"],
            benchmark_ticker=benchmark_ticker,
            total_value=total_value,
            fmp_ticker_map=fmp_ticker_map,
            currency_map=currency_map,
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
                "benchmark_ticker": benchmark_ticker,
                "fmp_ticker_map": fmp_ticker_map,
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

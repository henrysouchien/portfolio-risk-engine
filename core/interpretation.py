#!/usr/bin/env python3
# coding: utf-8

"""
Core AI interpretation business logic.
Extracted from run_risk.py as part of the refactoring to create a clean service layer.
"""

from io import StringIO
from contextlib import redirect_stdout 
from typing import Optional, Dict, Any
from datetime import datetime

from core.portfolio_analysis import analyze_portfolio
from utils.serialization import _format_portfolio_output_as_text
from gpt_helpers import interpret_portfolio_risk

# Import logging decorators for AI interpretation
from utils.logging import (
    log_portfolio_operation_decorator,
    log_performance,
    log_error_handling
)


@log_error_handling("high")
@log_portfolio_operation_decorator("ai_interpretation")
@log_performance(8.0)
def analyze_and_interpret(portfolio_yaml: str) -> Dict[str, Any]:
    """
    Core AI interpretation business logic for portfolio analysis.
    
    This function contains the pure business logic extracted from run_and_interpret(),
    without any CLI or dual-mode concerns.
    
    Parameters
    ----------
    portfolio_yaml : str
        Path to the portfolio configuration YAML.
        
    Returns
    -------
    Dict[str, Any]
        Structured interpretation results containing:
        - ai_interpretation: GPT interpretation of the analysis
        - full_diagnostics: Complete analysis output text
        - analysis_metadata: Analysis configuration and timestamps
    """
    
    # Run portfolio analysis and capture CLI output
    buf = StringIO()
    with redirect_stdout(buf):
        analyze_portfolio(portfolio_yaml)

    diagnostics = buf.getvalue()
    summary_txt = interpret_portfolio_risk(diagnostics)

    # Return structured data with raw objects (for service layer)
    return {
        "ai_interpretation": summary_txt,
        "full_diagnostics": diagnostics,
        "analysis_metadata": {
            "analysis_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "portfolio_file": portfolio_yaml,
            "interpretation_service": "gpt",
            "diagnostics_length": len(diagnostics),
            "interpretation_length": len(summary_txt)
        }
    }


def interpret_portfolio_data(
    portfolio_output: Dict[str, Any], 
    portfolio_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Core AI interpretation business logic for existing portfolio data.
    
    This function contains the pure business logic extracted from interpret_portfolio_output(),
    without any CLI or dual-mode concerns.
    
    This function enables two-level caching optimization:
    1. run_portfolio() output can be cached by PortfolioService
    2. AI interpretation can be cached separately
    
    Parameters
    ----------
    portfolio_output : Dict[str, Any]
        Structured output from run_portfolio(return_data=True)
    portfolio_name : Optional[str]
        Name/identifier for the portfolio (for metadata)
        
    Returns
    -------
    Dict[str, Any]
        Structured interpretation results containing:
        - ai_interpretation: GPT interpretation of the analysis
        - full_diagnostics: Complete analysis output text
        - analysis_metadata: Analysis configuration and timestamps
    """
    
    # Generate formatted diagnostics text from structured output
    diagnostics = _format_portfolio_output_as_text(portfolio_output)
    
    # Get AI interpretation
    summary_txt = interpret_portfolio_risk(diagnostics)
    
    # Return structured data with raw objects (for service layer)
    return {
        "ai_interpretation": summary_txt,
        "full_diagnostics": diagnostics,
        "analysis_metadata": {
            "analysis_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "portfolio_file": portfolio_name or "portfolio_output",
            "interpretation_service": "gpt",
            "diagnostics_length": len(diagnostics),
            "interpretation_length": len(summary_txt)
        }
    } 
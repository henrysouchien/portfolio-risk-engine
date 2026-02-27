#!/usr/bin/env python3
# coding: utf-8

"""
Core AI interpretation business logic.

Called by:
- ``run_risk.run_and_interpret`` wrapper path.
- Service/API interpretation endpoints that already have portfolio output data.

Calls into:
- ``gpt_helpers.interpret_portfolio_risk`` for language-model interpretation.

Contract notes:
- Returns canonical ``InterpretationResult`` for wrapper serialization.
- Supports two entry modes: run-analysis-and-interpret, or interpret existing
  structured portfolio output.
"""

from typing import Optional, Dict, Any
from datetime import datetime, UTC

from gpt_helpers import interpret_portfolio_risk
from core.result_objects import InterpretationResult

# Import logging decorators for AI interpretation
from utils.logging import (
    log_operation,
    log_timing,
    log_errors,
)


@log_errors("high")
@log_operation("ai_interpretation")
@log_timing(8.0)
def analyze_and_interpret(portfolio_yaml: str) -> InterpretationResult:
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
    InterpretationResult
        Structured interpretation results containing:
        - ai_interpretation: GPT interpretation of the analysis
        - full_diagnostics: Complete analysis output text
        - analysis_metadata: Analysis configuration and timestamps
    """
    
    # Import run_portfolio here to avoid circular imports
    from run_risk import run_portfolio
    
    # Get full analysis with formatted report (matching API path behavior)
    portfolio_result = run_portfolio(portfolio_yaml, return_data=True)
    
    # Extract the formatted report for GPT interpretation
    diagnostics = portfolio_result.to_cli_report()
    summary_txt = interpret_portfolio_risk(diagnostics)

    # Return InterpretationResult object
    return InterpretationResult(
        ai_interpretation=summary_txt,
        full_diagnostics=diagnostics,
        analysis_metadata={
            "analysis_date": datetime.now(UTC).isoformat(),
            "portfolio_file": portfolio_yaml,
            "interpretation_service": "gpt",
            "diagnostics_length": len(diagnostics),
            "interpretation_length": len(summary_txt)
        },
        analysis_date=datetime.now(UTC)
    )


def interpret_portfolio_data(
    portfolio_output: Dict[str, Any], 
    portfolio_name: Optional[str] = None
) -> InterpretationResult:
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
    InterpretationResult
        Structured interpretation results containing:
        - ai_interpretation: GPT interpretation of the analysis
        - full_diagnostics: Complete analysis output text
        - analysis_metadata: Analysis configuration and timestamps
    """
    
    # Generate formatted diagnostics text from structured output
    diagnostics = portfolio_output.get("formatted_report", "")
    
    # Get AI interpretation
    summary_txt = interpret_portfolio_risk(diagnostics)
    
    # Return InterpretationResult object
    return InterpretationResult(
        ai_interpretation=summary_txt,
        full_diagnostics=diagnostics,
        analysis_metadata={
            "analysis_date": datetime.now(UTC).isoformat(),
            "portfolio_file": portfolio_name or "portfolio_output",
            "interpretation_service": "gpt",
            "diagnostics_length": len(diagnostics),
            "interpretation_length": len(summary_txt)
        },
        analysis_date=datetime.now(UTC)
    ) 

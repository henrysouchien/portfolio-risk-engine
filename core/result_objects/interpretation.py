"""Interpretation result objects."""

from typing import Dict, Any, Optional, List, Union, Tuple
import numbers
import math
import pandas as pd
from datetime import datetime, UTC
import json
import numpy as np
from dataclasses import dataclass, field
from utils.serialization import make_json_safe
from ._helpers import _convert_to_json_serializable

@dataclass
class InterpretationResult:
    """
    Portfolio interpretation results from AI-assisted analysis.
    
    Contains the GPT interpretation of portfolio analysis along with
    the full diagnostic output and analysis metadata.
    
    Use to_api_response() for API serialization (schema-compliant).
    """
    
    # AI interpretation content
    ai_interpretation: str
    
    # Full diagnostic output from portfolio analysis
    full_diagnostics: str
    
    # Analysis metadata and configuration
    analysis_metadata: Dict[str, Any]
    
    # Metadata
    analysis_date: datetime
    portfolio_name: Optional[str] = None
    
    def get_summary(self) -> Dict[str, Any]:
        """Get interpretation summary with calculated metrics."""
        return {
            "interpretation_length": len(self.ai_interpretation),
            "diagnostics_length": len(self.full_diagnostics)
        }
    
    def to_cli_report(self) -> str:
        """Generate complete CLI formatted report - IDENTICAL to current output"""
        sections = []
        sections.append("=== GPT Portfolio Interpretation ===")
        sections.append("")
        sections.append(self.ai_interpretation)
        sections.append("")
        sections.append("=== Full Diagnostics ===")
        sections.append("")
        sections.append(self.full_diagnostics)
        return "\n".join(sections)
    
    def to_api_response(self) -> Dict[str, Any]:
        """
        Convert InterpretationResult to comprehensive API response format.
        
        CONSUMER ANALYSIS:
        - Direct API: Uses full structured response for AI interpretation and portfolio diagnostics
        - Claude/AI: Only uses ai_interpretation (ignores diagnostics and metadata)
        - Frontend: Uses adapters to display AI insights alongside diagnostic data
        
        Returns structured data suitable for JSON serialization and API responses.
        This method provides complete interpretation results including both the AI
        analysis and the underlying portfolio diagnostics that were analyzed.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary containing all interpretation data with the following fields:
            
            - ai_interpretation: GPT-generated interpretation and insights
            - full_diagnostics: Complete formatted portfolio analysis report
            - analysis_metadata: Configuration and metadata about the analysis process
            - analysis_date: ISO timestamp when the interpretation was generated
            - portfolio_name: Name/identifier of the analyzed portfolio
            - summary: Calculated metrics (content lengths)
        
        Example
        -------
        ```python
        result = service.interpret_with_portfolio_service(portfolio_data)
        api_data = result.to_api_response()
        
        # Access AI insights
        insights = api_data["ai_interpretation"]
        
        # Access full analysis details
        diagnostics = api_data["full_diagnostics"]
        
        # Access metadata
        analysis_info = api_data["analysis_metadata"]
        portfolio_file = analysis_info["portfolio_file"]
        service_used = analysis_info["interpretation_service"]
        ```
        """
        return {
            "ai_interpretation": self.ai_interpretation,      # STR: GPT-generated interpretation and insights
            "full_diagnostics": self.full_diagnostics,        # STR: Complete formatted portfolio analysis report
            "analysis_metadata": _convert_to_json_serializable(self.analysis_metadata),  # DICT: Analysis configuration and process metadata
            "analysis_date": self.analysis_date.isoformat(),  # STR: ISO timestamp of interpretation generation
            "portfolio_name": self.portfolio_name,            # STR|NULL: Portfolio identifier/name
            "summary": self.get_summary()                     # DICT: Calculated metrics (interpretation_length, diagnostics_length)
        }


    
    @classmethod
    def from_interpretation_output(cls, interpretation_output: Dict[str, Any],
                                  portfolio_name: Optional[str] = None) -> 'InterpretationResult':
        """
        Create InterpretationResult from AI interpretation analysis function data.
        
        ARCHITECTURE CONTEXT:
        This is the primary factory method for creating InterpretationResult objects from
        AI-assisted portfolio interpretation functions (run_and_interpret). It transforms
        AI interpretation output into a structured result object ready for API responses.
        
        DATA FLOW:
        run_and_interpret() → interpretation_output → from_interpretation_output() → InterpretationResult
        
        INPUT DATA STRUCTURE:
        - interpretation_output: Complete AI interpretation results containing:
          • ai_interpretation: GPT-generated portfolio analysis and insights (str)
          • full_diagnostics: Complete formatted portfolio analysis report (str)
          • analysis_metadata: Analysis configuration and process metadata (Dict)
            - portfolio_file: Source portfolio file path (str)
            - analysis_date: When analysis was performed (str, ISO format)
            - interpretation_service: AI service used (str, e.g., "claude", "gpt-4")
            - analysis_type: Type of analysis performed (str)
            - model_version: AI model version used (str)
            - token_usage: Token consumption statistics (Dict, optional)
        - portfolio_name: Portfolio identifier (Optional[str])
        
        TRANSFORMATION PROCESS:
        1. Extract AI interpretation text from output
        2. Extract full diagnostic report from output
        3. Preserve analysis metadata for traceability
        4. Set current timestamp for result creation
        5. Associate with portfolio name if provided
        
        OUTPUT OBJECT CAPABILITIES:
        - to_api_response(): Complete structured API response with AI insights and diagnostics
        - to_cli_report(): Human-readable CLI report combining AI interpretation and diagnostics
        - get_summary(): Content length metrics for interpretation and diagnostics
        
        🔒 BACKWARD COMPATIBILITY CONSTRAINT:
        Must preserve exact field mappings to ensure to_api_response() produces
        identical output structure. This builder ensures consistent API compatibility.
        
        Args:
            interpretation_output (Dict[str, Any]): AI interpretation analysis results
            portfolio_name (Optional[str]): Portfolio identifier for context
            
        Returns:
            InterpretationResult: Fully populated interpretation result with AI insights
        """
        return cls(
            ai_interpretation=interpretation_output["ai_interpretation"],
            full_diagnostics=interpretation_output["full_diagnostics"],
            analysis_metadata=interpretation_output["analysis_metadata"],
            analysis_date=datetime.now(UTC),
            portfolio_name=portfolio_name
        )
    
   
    
    def __hash__(self) -> int:
        """Make InterpretationResult hashable for caching."""
        # Hash based on content length and portfolio file
        key_data = (
            len(self.ai_interpretation),
            len(self.full_diagnostics),
            self.analysis_metadata.get("portfolio_file", ""),
            self.analysis_metadata.get("analysis_date", "")
        )
        return hash(key_data)


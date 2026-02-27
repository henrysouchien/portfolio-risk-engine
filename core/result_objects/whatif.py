"""Whatif result objects."""

from typing import Dict, Any, Optional, List, Union, Tuple
import numbers
import math
import pandas as pd
from datetime import datetime, UTC
import json
import numpy as np
from dataclasses import dataclass, field
from utils.serialization import make_json_safe
from .risk import RiskAnalysisResult
from ._helpers import _convert_to_json_serializable, _clean_nan_values

class WhatIfResult:
    """
    Scenario analysis output with before/after comparison.
    
    This matches the actual output from run_what_if() and run_what_if_scenario() functions,
    which return build_portfolio_view summaries and comparison tables.
    """
    
    def __init__(self, 
                 current_metrics: RiskAnalysisResult,
                 scenario_metrics: RiskAnalysisResult,
                 scenario_name: str = "Unknown",
                 risk_comparison: Optional[pd.DataFrame] = None,
                 beta_comparison: Optional[pd.DataFrame] = None):
        
        # Before/after analysis
        self.current_metrics = current_metrics
        self.scenario_metrics = scenario_metrics
        self.scenario_name = scenario_name
        
        # Comparison tables from actual what-if functions
        self.risk_comparison = risk_comparison if risk_comparison is not None else pd.DataFrame()
        self.beta_comparison = beta_comparison if beta_comparison is not None else pd.DataFrame()
        
        # Calculated deltas using correct metrics
        self.volatility_delta = scenario_metrics.volatility_annual - current_metrics.volatility_annual
        self.concentration_delta = scenario_metrics.herfindahl - current_metrics.herfindahl
        self.factor_variance_delta = (
            scenario_metrics.variance_decomposition.get('factor_pct', 0) - 
            current_metrics.variance_decomposition.get('factor_pct', 0)
        )
        
        # Risk improvement analysis (explicitly convert to Python bool to avoid JSON serialization issues)
        self.risk_improvement = bool(self.volatility_delta < 0)  # Lower volatility is better
        self.concentration_improvement = bool(self.concentration_delta < 0)  # Lower concentration is better
    
    @classmethod
    def from_core_scenario(cls,
                          scenario_result: Dict[str, Any],
                          scenario_name: str = "What-If Scenario") -> 'WhatIfResult':
        """
        Create WhatIfResult from core analyze_scenario() output data.
        
        ARCHITECTURE CONTEXT:
        This is the primary factory method for creating WhatIfResult objects from the
        streamlined analyze_scenario() core function. It transforms raw DataFrames and
        portfolio summaries into a structured result object ready for API responses.
        
        DATA FLOW:
        analyze_scenario() → scenario_result_data → from_core_scenario() → WhatIfResult
        
        INPUT DATA STRUCTURE (scenario_result):
        {
            "raw_tables": {
                "summary": Dict,           # Scenario portfolio analysis from build_portfolio_view()
                "summary_base": Dict,      # Current portfolio analysis from build_portfolio_view()
                "risk_new": DataFrame,     # Risk checks for scenario portfolio
                "beta_f_new": DataFrame,   # Factor beta checks for scenario portfolio  
                "beta_p_new": DataFrame,   # Industry proxy checks for scenario portfolio
                "cmp_risk": DataFrame,     # Before/after risk comparison table
                "cmp_beta": DataFrame      # Before/after beta comparison table
            },
            "scenario_metadata": {
                "analysis_date": str,      # ISO timestamp when analysis was performed
                "base_weights": Dict,      # Original portfolio weights for comparison
                "risk_limits": Dict,       # Risk limits configuration used
                ...                        # Additional metadata from analyze_scenario()
            }
        }
        
        TRANSFORMATION PROCESS:
        1. Extract raw DataFrames and portfolio summaries from scenario_result
        2. Create two RiskAnalysisResult objects (current vs scenario portfolios)
        3. Store comparison DataFrames directly for API table generation
        4. Store private attributes for CLI table formatting methods
        5. Calculate delta metrics (volatility, concentration, factor variance changes)
        
        OUTPUT OBJECT CAPABILITIES:
        - to_api_response(): Full structured API response with raw + formatted data
        - to_formatted_report(): Human-readable CLI report for Claude/AI consumption
        - get_*_table(): Individual formatted table methods for UI components
        - get_summary(): Core delta metrics for quick analysis
        
        🔒 BACKWARD COMPATIBILITY CONSTRAINT:
        Must preserve exact field mappings to ensure to_api_response() produces
        identical output structure. Any changes here must be validated against
        existing API consumers and schema samples.
        
        Args:
            scenario_result (Dict[str, Any]): Raw output from analyze_scenario() containing
                raw_tables (DataFrames) and scenario_metadata (analysis context)
            scenario_name (str): Human-readable scenario identifier for display
            
        Returns:
            WhatIfResult: Fully populated result object ready for API serialization
        """
        # === STEP 1: Extract core data from analyze_scenario() output ===
        raw_tables = scenario_result["raw_tables"]                   # Dict[str, DataFrame]: Core analysis DataFrames
        scenario_metadata = scenario_result.get("scenario_metadata", {})  # Dict: Analysis context and configuration
        
        # === STEP 2: Create RiskAnalysisResult for CURRENT portfolio (baseline) ===
        # Transform build_portfolio_view() output into RiskAnalysisResult parameters
        current_risk_checks = []                                     # List[Dict]: Empty - baseline doesn't run risk checks
        current_beta_checks = []                                     # List[Dict]: Empty - baseline doesn't run beta checks  
        current_historical_analysis = raw_tables["summary_base"].get("historical_analysis", {})  # Dict: Historical performance data
        current_metadata = {                                         # Dict: Metadata for RiskAnalysisResult creation
            "portfolio_name": "Current Portfolio",                  # str: Display name for baseline
            "analysis_date": scenario_metadata.get("analysis_date") # str: ISO timestamp from analyze_scenario()
        }
        
        current_metrics = RiskAnalysisResult.from_core_analysis(     # RiskAnalysisResult: Baseline portfolio analysis
            portfolio_summary=raw_tables["summary_base"],           # Dict: build_portfolio_view() output for current portfolio
            risk_checks=current_risk_checks,                        # List[Dict]: No risk checks for baseline
            beta_checks=current_beta_checks,                        # List[Dict]: No beta checks for baseline
            max_betas=raw_tables["summary_base"].get("max_betas", {}),          # Dict: Max beta thresholds
            max_betas_by_proxy=raw_tables["summary_base"].get("max_betas_by_proxy", {}),  # Dict: Max proxy beta thresholds
            historical_analysis=current_historical_analysis,        # Dict: Historical analysis data
            analysis_metadata=current_metadata                      # Dict: Portfolio metadata
        )
        
        # === STEP 3: Create RiskAnalysisResult for SCENARIO portfolio (modified) ===
        # Convert DataFrames to List[Dict] format expected by RiskAnalysisResult
        scenario_risk_checks = raw_tables["risk_new"].to_dict('records') if not raw_tables["risk_new"].empty else []      # List[Dict]: Risk limit checks
        scenario_beta_checks = raw_tables["beta_f_new"].to_dict('records') if not raw_tables["beta_f_new"].empty else []  # List[Dict]: Beta exposure checks
        scenario_historical_analysis = raw_tables["summary"].get("historical_analysis", {})  # Dict: Historical performance data
        scenario_metadata_dict = {                                  # Dict: Metadata for RiskAnalysisResult creation
            "portfolio_name": scenario_name,                        # str: Display name for scenario (e.g., "What-If Scenario")
            "analysis_date": scenario_metadata.get("analysis_date") # str: ISO timestamp from analyze_scenario()
        }
        
        scenario_metrics = RiskAnalysisResult.from_core_analysis(   # RiskAnalysisResult: Scenario portfolio analysis
            portfolio_summary=raw_tables["summary"],               # Dict: build_portfolio_view() output for scenario portfolio
            risk_checks=scenario_risk_checks,                      # List[Dict]: Risk limit validation results
            beta_checks=scenario_beta_checks,                      # List[Dict]: Beta exposure validation results
            max_betas=raw_tables["summary"].get("max_betas", {}),                # Dict: Max beta thresholds
            max_betas_by_proxy=raw_tables["summary"].get("max_betas_by_proxy", {}),  # Dict: Max proxy beta thresholds
            historical_analysis=scenario_historical_analysis,      # Dict: Historical analysis data
            analysis_metadata=scenario_metadata_dict               # Dict: Portfolio metadata
        )
        
        # === STEP 4: Create WhatIfResult instance with core comparison data ===
        result = cls(                                               # WhatIfResult: Main result object
            current_metrics=current_metrics,                       # RiskAnalysisResult: Baseline portfolio analysis
            scenario_metrics=scenario_metrics,                     # RiskAnalysisResult: Scenario portfolio analysis
            scenario_name=scenario_name,                           # str: Human-readable scenario name
            risk_comparison=raw_tables["cmp_risk"],                # DataFrame: Before/after risk comparison from run_what_if_scenario()
            beta_comparison=raw_tables["cmp_beta"]                 # DataFrame: Before/after beta comparison from run_what_if_scenario()
        )
        
        # === STEP 5: Store private attributes for CLI table formatting methods ===
        # These DataFrames are used by get_*_table() methods to generate formatted display tables
        result._new_portfolio_risk_checks = raw_tables["risk_new"]           # DataFrame: Risk checks for get_new_portfolio_risk_checks_table()
        result._new_portfolio_factor_checks = raw_tables["beta_f_new"]       # DataFrame: Factor checks for get_new_portfolio_factor_checks_table()
        result._new_portfolio_industry_checks = raw_tables["beta_p_new"]     # DataFrame: Industry checks for get_new_portfolio_industry_checks_table()
        result._scenario_metadata = scenario_metadata                        # Dict: Analysis metadata for position_changes_table() and _build_risk_analysis()
        result._formatted_report = scenario_result.get("formatted_report", "")  # str: Pre-generated CLI report (if available)
        
        return result



    def get_summary(self) -> Dict[str, Any]:
        """Get summary of scenario impact using real metrics."""
        return {
            "scenario_name": self.scenario_name,
            "volatility_change": {
                "current": round(self.current_metrics.volatility_annual, 4),
                "scenario": round(self.scenario_metrics.volatility_annual, 4),
                "delta": round(self.volatility_delta, 4)
            },
            "concentration_change": {
                "current": round(self.current_metrics.herfindahl, 3),
                "scenario": round(self.scenario_metrics.herfindahl, 3),
                "delta": round(self.concentration_delta, 3)
            },
            "factor_variance_change": {
                "current": round(self.current_metrics.variance_decomposition.get('factor_pct', 0), 3),
                "scenario": round(self.scenario_metrics.variance_decomposition.get('factor_pct', 0), 3),
                "delta": round(self.factor_variance_delta, 3)
            },
            "risk_improvement": self.risk_improvement,
            "concentration_improvement": self.concentration_improvement
        }

    def get_agent_snapshot(self) -> Dict[str, Any]:
        """Compact metrics for agent consumption."""
        vol_current_pct = round(self.current_metrics.volatility_annual * 100, 2)
        vol_scenario_pct = round(self.scenario_metrics.volatility_annual * 100, 2)
        vol_delta_pct = round(self.volatility_delta * 100, 2)

        conc_current = round(self.current_metrics.herfindahl, 4)
        conc_scenario = round(self.scenario_metrics.herfindahl, 4)
        conc_delta = round(self.concentration_delta, 4)

        factor_var_current = round(
            self.current_metrics.variance_decomposition.get("factor_pct", 0) * 100, 2
        )
        factor_var_scenario = round(
            self.scenario_metrics.variance_decomposition.get("factor_pct", 0) * 100, 2
        )
        factor_var_delta = round(self.factor_variance_delta * 100, 2)

        scenario_risk = self.scenario_metrics
        has_risk_checks = bool(getattr(scenario_risk, "risk_checks", None))
        has_factor_checks = bool(getattr(scenario_risk, "beta_checks", None))

        if has_risk_checks:
            risk_fails = [check for check in scenario_risk.risk_checks if not check.get("Pass", True)]
            risk_passes = len(risk_fails) == 0
            risk_violation_count = len(risk_fails)
        else:
            risk_passes = None
            risk_violation_count = 0

        if has_factor_checks:
            factor_fails = [check for check in scenario_risk.beta_checks if not check.get("pass", True)]
            factor_passes = len(factor_fails) == 0
            factor_violation_count = len(factor_fails)
        else:
            factor_passes = None
            factor_violation_count = 0

        proxy_passes = None
        proxy_violation_count = 0
        if hasattr(self, "_new_portfolio_industry_checks"):
            industry_df = self._new_portfolio_industry_checks
            if not industry_df.empty and "pass" in industry_df.columns:
                proxy_passes = bool(industry_df["pass"].all())
                proxy_violation_count = int((~industry_df["pass"]).sum())

        position_changes: List[Dict[str, Any]] = []
        try:
            if not hasattr(self, "_scenario_metadata") or not self._scenario_metadata.get("base_weights"):
                raise ValueError("No baseline weights available")
            base_weights = self._scenario_metadata.get("base_weights", {})
            scenario_weights = getattr(self.scenario_metrics, "portfolio_weights", None) or {}
            all_tickers = set(base_weights.keys()) | set(scenario_weights.keys())
            parsed = []
            for ticker in all_tickers:
                before = base_weights.get(ticker, 0.0)
                after = scenario_weights.get(ticker, 0.0)
                change = after - before
                abs_change = abs(change)
                if abs_change >= 0.005 or math.isclose(abs_change, 0.005, abs_tol=1e-12):
                    parsed.append(
                        {
                            "position": ticker,
                            "before": f"{before:.1%}",
                            "after": f"{after:.1%}",
                            "change": f"{change:+.1%}",
                            "_abs_change": abs_change,
                        }
                    )
            parsed.sort(key=lambda change: (-change["_abs_change"], change["position"]))
            for position in parsed:
                del position["_abs_change"]
            position_changes = parsed[:5]
        except Exception:
            pass

        factor_deltas: Dict[str, Dict[str, float]] = {}
        try:
            factor_comparison = self.get_factor_exposures_comparison()
            sorted_factors = sorted(
                factor_comparison.items(),
                key=lambda item: (-abs(item[1].get("delta", 0)), item[0]),
            )
            for factor, values in sorted_factors[:3]:
                factor_deltas[factor] = {
                    "current": values.get("current", 0),
                    "scenario": values.get("scenario", 0),
                    "delta": values.get("delta", 0),
                }
        except Exception:
            pass

        raw_vol_delta_pct = self.volatility_delta * 100
        raw_conc_delta = self.concentration_delta
        total_violations = risk_violation_count + factor_violation_count + proxy_violation_count
        is_marginal = abs(raw_vol_delta_pct) < 0.1 and abs(raw_conc_delta) < 0.001
        if total_violations > 0:
            verdict = "introduces violations"
        elif is_marginal:
            verdict = "marginal impact"
        elif self.risk_improvement and self.concentration_improvement:
            verdict = "improves risk and concentration"
        elif self.risk_improvement:
            verdict = "improves risk"
        elif self.concentration_improvement:
            verdict = "improves concentration"
        else:
            verdict = "increases risk"

        snapshot = {
            "verdict": verdict,
            "is_marginal": is_marginal,
            "_raw_vol_delta_pct": raw_vol_delta_pct,
            "_raw_conc_delta": raw_conc_delta,
            "scenario_name": self.scenario_name,
            "risk_deltas": {
                "volatility_annual_pct": {
                    "current": vol_current_pct,
                    "scenario": vol_scenario_pct,
                    "delta": vol_delta_pct,
                },
                "herfindahl": {
                    "current": conc_current,
                    "scenario": conc_scenario,
                    "delta": conc_delta,
                },
                "factor_variance_pct": {
                    "current": factor_var_current,
                    "scenario": factor_var_scenario,
                    "delta": factor_var_delta,
                },
            },
            "improvements": {
                "risk": self.risk_improvement,
                "concentration": self.concentration_improvement,
            },
            "compliance": {
                "risk_passes": risk_passes,
                "risk_violation_count": risk_violation_count,
                "factor_passes": factor_passes,
                "factor_violation_count": factor_violation_count,
                "proxy_passes": proxy_passes,
                "proxy_violation_count": proxy_violation_count,
            },
            "top_position_changes": position_changes,
            "top_factor_deltas": factor_deltas,
        }

        return snapshot
    
    def get_factor_exposures_comparison(self) -> Dict[str, Dict[str, float]]:
        """Compare factor exposures between current and scenario portfolios."""
        current_betas = self.current_metrics.portfolio_factor_betas.to_dict()
        scenario_betas = self.scenario_metrics.portfolio_factor_betas.to_dict()
        
        comparison = {}
        all_factors = set(current_betas.keys()) | set(scenario_betas.keys())
        
        for factor in all_factors:
            current_beta = current_betas.get(factor, 0)
            scenario_beta = scenario_betas.get(factor, 0)
            comparison[factor] = {
                "current": round(current_beta, 3),
                "scenario": round(scenario_beta, 3),
                "delta": round(scenario_beta - current_beta, 3)
            }
        
        return comparison
    
    def to_cli_report(self) -> str:
        """
        Generate complete CLI formatted report - IDENTICAL to current print_what_if_report() output.
        
        🔒 CONSTRAINT: CLI output must be IDENTICAL to current run_what_if() output.
        This method replicates the exact formatting from print_what_if_report().
        """
        # If we have stored formatted report from print_what_if_report, use it
        if hasattr(self, '_formatted_report') and self._formatted_report:
            return self._formatted_report
            
        # Otherwise generate equivalent report sections
        sections = []
        sections.append(self._format_scenario_header())
        sections.append(self._format_position_changes())
        sections.append(self._format_new_portfolio_risk_checks())
        sections.append(self._format_new_portfolio_factor_checks())
        sections.append(self._format_new_portfolio_industry_checks())
        sections.append(self._format_risk_comparison())
        sections.append(self._format_factor_comparison())
        return "\n".join(sections)
    
    def to_formatted_report(self) -> str:
        """Format what-if scenario results for display (identical to to_cli_report())."""
        return self.to_cli_report()
    
    def _format_scenario_header(self) -> str:
        """Format scenario header - EXACT copy of print_what_if_report logic"""
        return f"=== What-If Scenario Analysis: {self.scenario_name} ==="
    
    def _format_position_changes(self) -> str:
        """Format position changes table - EXACT copy of CLI output"""
        lines = ["\n📊 Portfolio Weights — Before vs After\n"]
        
        # Get reference data for position labeling
        try:
            from core.portfolio_config import get_cash_positions
            from utils.etf_mappings import get_etf_to_industry_map, format_ticker_with_label
            cash_positions = get_cash_positions()
            industry_map = get_etf_to_industry_map()
        except ImportError:
            cash_positions = set()
            industry_map = {}
        
        # Get weights from both portfolios - use stored metadata
        if not hasattr(self, '_scenario_metadata'):
            return "\n📊 Portfolio Weights — Before vs After\n\n(No position changes data available)\n"
            
        base_weights = self._scenario_metadata.get("base_weights", {})
        scenario_weights = getattr(self.scenario_metrics, 'portfolio_weights', {})
        
        # If scenario_weights is empty, try to get from allocations
        if not scenario_weights and hasattr(self.scenario_metrics, 'allocations'):
            if hasattr(self.scenario_metrics.allocations, 'to_dict'):
                scenario_weights = self.scenario_metrics.allocations.to_dict().get('Portfolio Weight', {})
        
        # Combine all tickers and calculate changes
        all_tickers = set(base_weights.keys()) | set(scenario_weights.keys())
        
        # Calculate adaptive column width
        max_width = 12  # minimum width
        changes_data = []
        
        for ticker in all_tickers:
            old_weight = base_weights.get(ticker, 0.0)
            new_weight = scenario_weights.get(ticker, 0.0)
            change = new_weight - old_weight
            
            # Only show positions that exist in at least one portfolio
            if abs(old_weight) > 0.001 or abs(new_weight) > 0.001:
                try:
                    labeled_ticker = format_ticker_with_label(ticker, cash_positions, industry_map)
                except:
                    labeled_ticker = ticker
                max_width = max(max_width, len(labeled_ticker))
                changes_data.append((ticker, labeled_ticker, old_weight, new_weight, change))
        
        # Add padding
        max_width += 2
        
        # Print header
        lines.append(f"{'Position':<{max_width}} {'Before':<8} {'After':<8} {'Change':<8}")
        lines.append("─" * (max_width + 26))
        
        # Sort by absolute change (largest changes first)
        changes_data.sort(key=lambda x: abs(x[4]), reverse=True)
        
        # Print changes
        for ticker, labeled_ticker, old_weight, new_weight, change in changes_data:
            if abs(change) > 0.001:  # Only show meaningful changes
                change_str = f"{change:+.1%}" if abs(change) >= 0.001 else ""
                lines.append(f"{labeled_ticker:<{max_width}} {old_weight:.1%}    {new_weight:.1%}    {change_str}")
        
        lines.append("")  # Add spacing
        return "\n".join(lines)
    
    def _format_new_portfolio_risk_checks(self) -> str:
        """Format new portfolio risk checks - EXACT copy of CLI output"""
        lines = ["\n📐  NEW Portfolio – Risk Checks\n"]
        
        if not hasattr(self, '_new_portfolio_risk_checks') or self._new_portfolio_risk_checks.empty:
            lines.append("(No risk checks data available)")
            return "\n".join(lines)
        
        # Format using pandas to_string with exact formatters from print_what_if_report
        formatted_table = self._new_portfolio_risk_checks.to_string(
            index=False, 
            formatters={
                "Actual": lambda x: f"{x:.1%}",
                "Limit":  lambda x: f"{x:.1%}",
            }
        )
        lines.append(formatted_table)
        return "\n".join(lines)
    
    def _format_new_portfolio_factor_checks(self) -> str:
        """Format new portfolio factor checks - EXACT copy of CLI output"""
        lines = ["\n📊  NEW Aggregate Factor Exposures\n"]
        
        if not hasattr(self, '_new_portfolio_factor_checks') or self._new_portfolio_factor_checks.empty:
            lines.append("(No factor checks data available)")
            return "\n".join(lines)
        
        # Format using pandas to_string with exact formatters from print_what_if_report
        formatted_table = self._new_portfolio_factor_checks.to_string(
            index_names=False, 
            formatters={
                "portfolio_beta":   "{:.2f}".format,
                "max_allowed_beta": "{:.2f}".format,
                "buffer":           "{:.2f}".format,
                "pass":             lambda x: "PASS" if x else "FAIL",
            }
        )
        lines.append(formatted_table)
        return "\n".join(lines)
    
    def _format_new_portfolio_industry_checks(self) -> str:
        """Format new portfolio industry checks - EXACT copy of CLI output"""
        lines = ["\n📊  NEW Industry Exposure Checks\n"]
        
        if not hasattr(self, '_new_portfolio_industry_checks') or self._new_portfolio_industry_checks.empty:
            lines.append("(No industry checks data available)")
            return "\n".join(lines)
        
        # Format using pandas to_string with exact formatters from print_what_if_report
        formatted_table = self._new_portfolio_industry_checks.to_string(
            index_names=False, 
            formatters={
                "portfolio_beta":   "{:.2f}".format,
                "max_allowed_beta": "{:.2f}".format,
                "buffer":           "{:.2f}".format,
                "pass":             lambda x: "PASS" if x else "FAIL",
            }
        )
        lines.append(formatted_table)
        return "\n".join(lines)
    
    def _format_risk_comparison(self) -> str:
        """Format risk comparison table - EXACT copy of CLI output"""
        lines = ["\n📐  Risk Limits — Before vs After\n"]
        
        if self.risk_comparison.empty:
            lines.append("(No risk comparison data available)")
            return "\n".join(lines)
        
        # Format using pandas to_string with exact formatters from print_what_if_report
        formatted_table = self.risk_comparison.to_string(
            index=False, 
            formatters={
                "Old":   lambda x: f"{x:.1%}",
                "New":   lambda x: f"{x:.1%}",
                "Δ":     lambda x: f"{x:.1%}",
                "Limit": lambda x: f"{x:.1%}",
            }
        )
        lines.append(formatted_table)
        return "\n".join(lines)
    
    def _format_factor_comparison(self) -> str:
        """Format factor comparison table - EXACT copy of CLI output"""
        lines = ["\n📊  Factor Betas — Before vs After\n"]
        
        if self.beta_comparison.empty:
            lines.append("(No factor comparison data available)")
            return "\n".join(lines)
        
        # Format using pandas to_string with exact formatters from print_what_if_report
        formatted_table = self.beta_comparison.to_string(
            index_names=False, 
            formatters={
                "Old":       "{:.2f}".format,
                "New":       "{:.2f}".format,
                "Δ":         "{:.2f}".format,
                "Max Beta":  "{:.2f}".format,
                "Old Pass":  lambda x: "PASS" if x else "FAIL",
                "New Pass":  lambda x: "PASS" if x else "FAIL",
            }
        )
        lines.append(formatted_table)
        return "\n".join(lines)


    
    def to_api_response(self) -> Dict[str, Any]:
        """
        Convert WhatIfResult to comprehensive API response format.
        
        CONSUMER ANALYSIS:
        - Direct API: Uses full structured response for programmatic processing
        - Claude/AI: Only uses formatted_report (ignores all structured data)
        - Frontend: Not yet implemented (currently uses mock data)
        
        RESPONSE STRUCTURE:
        
        **Basic Information:**
        - scenario_name: Scenario identifier string
        - deltas: Core impact metrics (volatility, concentration, factor variance changes)
        
        **Structured Analysis Data (Raw - for programming):**
        - risk_analysis: {
            risk_checks: List[Dict],           # All risk limit checks in row format
            risk_passes: bool,                 # True if all risk checks pass
            risk_violations: List[Dict],       # Only failed risk checks
            risk_limits: Dict                  # Risk limits configuration used
          }
        - beta_analysis: {
            factor_beta_checks: List[Dict],    # Factor beta checks in row format
            proxy_beta_checks: List[Dict],     # Industry proxy checks in row format
            factor_beta_passes: bool,          # True if all factor checks pass
            proxy_beta_passes: bool,           # True if all proxy checks pass
            factor_beta_violations: List[Dict], # Only failed factor checks
            proxy_beta_violations: List[Dict]   # Only failed proxy checks
          }
        - comparison_analysis: {
            risk_comparison: List[Dict],       # Before/after risk comparison in row format
            beta_comparison: List[Dict]        # Before/after beta comparison in row format
          }
        
        **Formatted Display Tables (Human-readable - for UI):**
        - position_changes: Portfolio weight changes with percentage formatting
        - new_portfolio_risk_checks: Risk checks formatted as display table
        - new_portfolio_factor_checks: Factor checks formatted as display table
        - new_portfolio_industry_checks: Industry checks formatted as display table
        - risk_comparison: Before/after risk comparison with percentage formatting
        - factor_comparison: Before/after factor comparison with decimal formatting
        
        **Human-Readable Report:**
        - formatted_report: Complete CLI-style text report (primary Claude/AI input)
        
        EXAMPLE STRUCTURED DATA:
        {
          "risk_analysis": {
            "risk_checks": [{"Metric": "Annual Volatility", "Actual": 0.185, "Limit": 0.20, "Pass": true}],
            "risk_passes": true,
            "risk_violations": [],
            "risk_limits": {"portfolio_limits": {...}, "concentration_limits": {...}}
          },
          "beta_analysis": {
            "factor_beta_checks": [{"market": {"portfolio_beta": 1.22, "max_allowed_beta": 0.77, "pass": false}}],
            "factor_beta_passes": false,
            "factor_beta_violations": [{"market": {"portfolio_beta": 1.22, "pass": false}}],
            "proxy_beta_checks": [{"DSU": {"portfolio_beta": 0.85, "max_allowed_beta": 1.10, "pass": true}}],
            "proxy_beta_passes": true,
            "proxy_beta_violations": []
          },
          "comparison_analysis": {
            "risk_comparison": [{"Metric": "Annual Volatility", "Old": 0.18, "New": 0.185, "Δ": 0.005}],
            "beta_comparison": [{"market": {"Old": 1.18, "New": 1.22, "Δ": 0.04}}]
          }
        }
        
        NOTE: Currently includes data duplication (raw + formatted) for backward compatibility.
        Raw structured data and formatted tables contain same information in different formats.
        
        Returns:
            Dict[str, Any]: Complete what-if scenario analysis with structured + formatted data
        """
        result_data = {
            # === BASIC INFORMATION ===
            "scenario_name": self.scenario_name,                        # str: Scenario identifier ("What-If Scenario")
            #TODO: Add current and scenario metrics back in (if needed)
            # "current_metrics": self.current_metrics.to_api_response(),  # Dict: Full baseline portfolio analysis
            # "scenario_metrics": self.scenario_metrics.to_api_response(), # Dict: Full scenario portfolio analysis
            
            "deltas": {                                                  # Dict: Core impact metrics
                "volatility_delta": self.volatility_delta,              # float: Change in annual volatility (e.g., 0.02 = +2%)
                "concentration_delta": self.concentration_delta,        # float: Change in Herfindahl concentration index
                "factor_variance_delta": self.factor_variance_delta     # float: Change in factor variance percentage
            },
            
            # === STRUCTURED ANALYSIS DATA (Raw - for programming) ===
            "risk_analysis": self._build_risk_analysis(),               # Dict: Raw risk data with checks/passes/violations/limits
            "beta_analysis": self._build_beta_analysis(),               # Dict: Raw beta data with factor/proxy checks/passes/violations
            "comparison_analysis": self._build_comparison_analysis(),   # Dict: Raw before/after comparison data
            
            # === FORMATTED DISPLAY TABLES (Human-readable - for UI) ===
            "position_changes": self.get_position_changes_table(show_all_positions=True),      # List[Dict]: Weight changes with % formatting ("15.2%" → "18.5%") - shows all positions
            "new_portfolio_risk_checks": self.get_new_portfolio_risk_checks_table(),        # List[Dict]: Risk checks with % formatting
            "new_portfolio_factor_checks": self.get_new_portfolio_factor_checks_table(),    # List[Dict]: Factor checks with decimal formatting
            "new_portfolio_industry_checks": self.get_new_portfolio_industry_checks_table(), # List[Dict]: Industry checks with decimal formatting
            "risk_comparison": self.get_risk_comparison_table(),        # List[Dict]: Before/after risk with % formatting
            "factor_comparison": self.get_factor_comparison_table(),    # List[Dict]: Before/after factors with decimal formatting
            
            # === HUMAN-READABLE REPORT (Primary Claude/AI input) ===
            "formatted_report": self.to_formatted_report()             # str: Complete CLI-style text report for natural language processing
        }
        
        # Ensure all data is JSON serializable (handles nested numpy types)
        return _convert_to_json_serializable(result_data)

    def _build_risk_analysis(self) -> Dict[str, Any]:
        """Build structured risk analysis data for API response (matching OptimizationResult pattern)."""
        if not hasattr(self, '_new_portfolio_risk_checks') or self._new_portfolio_risk_checks.empty:
            return {
                "risk_checks": [],
                "risk_passes": True,
                "risk_violations": [],
                "risk_limits": {}
            }
        
        risk_df = self._new_portfolio_risk_checks
        
        # Use standard serialization (consistent with OptimizationResult)
        risk_checks = _convert_to_json_serializable(risk_df)
        risk_passes = bool(risk_df['Pass'].all()) if 'Pass' in risk_df.columns else True
        risk_violations = _convert_to_json_serializable(risk_df[~risk_df['Pass']]) if 'Pass' in risk_df.columns else []
        
        return {
            "risk_checks": risk_checks,              # List[Dict]: All risk checks in row format
            "risk_passes": risk_passes,              # bool: True if all risk checks pass
            "risk_violations": risk_violations,      # List[Dict]: Only failed risk checks
            "risk_limits": getattr(self, '_scenario_metadata', {}).get('risk_limits', {})  # Dict: Risk limits configuration
        }

    def _build_beta_analysis(self) -> Dict[str, Any]:
        """Build structured beta analysis data for API response (matching OptimizationResult pattern)."""
        # Initialize defaults
        factor_checks = []
        proxy_checks = []
        factor_passes = True
        proxy_passes = True
        factor_violations = []
        proxy_violations = []
        
        # Process factor beta checks
        if hasattr(self, '_new_portfolio_factor_checks') and not self._new_portfolio_factor_checks.empty:
            factor_df = self._new_portfolio_factor_checks
            factor_checks = _convert_to_json_serializable(factor_df)
            if 'pass' in factor_df.columns:
                factor_passes = bool(factor_df['pass'].all())
                factor_violations = _convert_to_json_serializable(factor_df[~factor_df['pass']])
        
        # Process proxy beta checks
        if hasattr(self, '_new_portfolio_industry_checks') and not self._new_portfolio_industry_checks.empty:
            proxy_df = self._new_portfolio_industry_checks
            proxy_checks = _convert_to_json_serializable(proxy_df)
            if 'pass' in proxy_df.columns:
                proxy_passes = bool(proxy_df['pass'].all())
                proxy_violations = _convert_to_json_serializable(proxy_df[~proxy_df['pass']])
        
        return {
            "factor_beta_checks": factor_checks,     # List[Dict]: Factor beta checks in row format
            "proxy_beta_checks": proxy_checks,       # List[Dict]: Industry proxy beta checks in row format
            "factor_beta_passes": factor_passes,     # bool: True if all factor checks pass
            "proxy_beta_passes": proxy_passes,       # bool: True if all proxy checks pass
            "factor_beta_violations": factor_violations,  # List[Dict]: Only failed factor checks
            "proxy_beta_violations": proxy_violations,    # List[Dict]: Only failed proxy checks
        }

    def _build_comparison_analysis(self) -> Dict[str, Any]:
        """Build structured comparison analysis data for API response (matching OptimizationResult pattern)."""
        # Use standard serialization (consistent with OptimizationResult)
        risk_comparison = _convert_to_json_serializable(self.risk_comparison) if not self.risk_comparison.empty else []
        beta_comparison = _convert_to_json_serializable(self.beta_comparison) if not self.beta_comparison.empty else []
        
        return {
            "risk_comparison": risk_comparison,       # List[Dict]: Before/after risk comparison in row format
            "beta_comparison": beta_comparison,       # List[Dict]: Before/after beta comparison in row format
        }

    def _get_scenario_metadata(self) -> Dict[str, Any]:
        """Generate scenario metadata and description."""
        return {
            "description": f"Scenario analysis: {self.scenario_name}",
            "change_type": "position_adjustment",
            "analysis_type": "what_if_comparison",
            "baseline": "current_portfolio",
            "scenario": self.scenario_name or "modified_portfolio"
        }
    
    def _generate_change_summaries(self) -> List[str]:
        """Generate formatted position change summaries like 'AAPL 0.0% → 5.0% +5.0%'."""
        summaries = []
        
        # Try to extract position changes from comparison data
        # This would need to be populated from the actual scenario data
        # For now, create a placeholder based on scenario name
        if self.scenario_name and "AAPL" in self.scenario_name:
            summaries.append("AAPL 0.0% → 5.0% +5.0%")
            summaries.append("SPY (DEFAULT) 0.0% → -2.0% -2.0%")
        else:
            # Generic change summary
            summaries.append(f"Portfolio modified for scenario: {self.scenario_name}")
            
            # Add delta information if available
            if hasattr(self, 'volatility_delta') and self.volatility_delta != 0:
                direction = "increased" if self.volatility_delta > 0 else "decreased"
                summaries.append(f"Volatility {direction} by {abs(self.volatility_delta):.2f}%")
            
            if hasattr(self, 'concentration_delta') and self.concentration_delta != 0:
                direction = "increased" if self.concentration_delta > 0 else "decreased"  
                summaries.append(f"Concentration {direction} by {abs(self.concentration_delta):.2f}%")
        
        return summaries

    def get_position_changes_table(self, show_all_positions: bool = False) -> List[Dict[str, Any]]:
        """
        Generate position changes table (Portfolio Weights — Before vs After).
        
        Args:
            show_all_positions (bool): If True, shows all positions including unchanged ones.
                                     If False, only shows positions with meaningful changes (> 0.0001).
        
        Returns list of position changes with before/after weights and deltas.
        """
        if not hasattr(self, '_scenario_metadata'):
            return []
            
        base_weights = self._scenario_metadata.get("base_weights", {})
        scenario_weights = getattr(self.scenario_metrics, 'portfolio_weights', {})
        
        position_changes = []
        all_tickers = set(base_weights.keys()) | set(scenario_weights.keys())
        
        for ticker in sorted(all_tickers):
            before = base_weights.get(ticker, 0.0)
            after = scenario_weights.get(ticker, 0.0)
            change = after - before
            
            # Include position if:
            # 1. show_all_positions is True (show everything), OR
            # 2. There's a meaningful change (> 0.0001)
            if show_all_positions or abs(change) > 0.0001:
                position_changes.append({
                    "position": ticker,
                    "before": f"{before:.1%}",
                    "after": f"{after:.1%}", 
                    "change": f"{change:+.1%}"
                })
        
        return position_changes

    def get_new_portfolio_risk_checks_table(self) -> List[Dict[str, Any]]:
        """
        Generate new portfolio risk checks table (NEW Portfolio – Risk Checks).
        
        Returns formatted risk checks for the scenario portfolio.
        """
        if not hasattr(self, '_new_portfolio_risk_checks') or self._new_portfolio_risk_checks.empty:
            return []
            
        risk_checks = []
        df = self._new_portfolio_risk_checks
        
        for _, row in df.iterrows():
            risk_checks.append({
                "metric": row.get("Metric", ""),
                "actual": f"{row.get('Actual', 0):.1%}" if 'Actual' in row else "",
                "limit": f"{row.get('Limit', 0):.1%}" if 'Limit' in row else "",
                "pass": bool(row.get("Pass", True))
            })
            
        return risk_checks

    def get_new_portfolio_factor_checks_table(self) -> List[Dict[str, Any]]:
        """
        Generate new portfolio factor checks table (NEW Aggregate Factor Exposures).
        
        Returns formatted factor exposure checks for the scenario portfolio.
        """
        if not hasattr(self, '_new_portfolio_factor_checks') or self._new_portfolio_factor_checks.empty:
            return []
            
        factor_checks = []
        df = self._new_portfolio_factor_checks
        
        for _, row in df.iterrows():
            factor_checks.append({
                "factor": row.name if hasattr(row, 'name') else "",
                "portfolio_beta": round(row.get("portfolio_beta", 0), 2),
                "max_allowed_beta": round(row.get("max_allowed_beta", 0), 2),
                "pass": row.get("pass", True),
                "buffer": round(row.get("buffer", 0), 2)
            })
            
        return factor_checks

    def get_new_portfolio_industry_checks_table(self) -> List[Dict[str, Any]]:
        """
        Generate new portfolio industry checks table (NEW Industry Exposure Checks).
        
        Returns formatted industry exposure checks for the scenario portfolio.
        """
        if not hasattr(self, '_new_portfolio_industry_checks') or self._new_portfolio_industry_checks.empty:
            return []
            
        industry_checks = []
        df = self._new_portfolio_industry_checks
        
        for _, row in df.iterrows():
            industry_checks.append({
                "industry": row.name if hasattr(row, 'name') else "",
                "portfolio_beta": round(row.get("portfolio_beta", 0), 2),
                "max_allowed_beta": round(row.get("max_allowed_beta", 0), 2),
                "pass": row.get("pass", True),
                "buffer": round(row.get("buffer", 0), 2)
            })
            
        return industry_checks

    def get_risk_comparison_table(self) -> List[Dict[str, Any]]:
        """
        Generate risk comparison table (Risk Limits — Before vs After).
        
        Returns formatted before/after risk comparison.
        """
        if self.risk_comparison.empty:
            return []
            
        risk_comparison = []
        
        for _, row in self.risk_comparison.iterrows():
            risk_comparison.append({
                "metric": row.get("Metric", ""),
                "old": f"{row.get('Old', 0):.1%}" if 'Old' in row else "",
                "new": f"{row.get('New', 0):.1%}" if 'New' in row else "",
                "delta": f"{row.get('Δ', 0):+.1%}" if 'Δ' in row else "",
                "limit": f"{row.get('Limit', 0):.1%}" if 'Limit' in row else "",
                "old_pass": bool(row.get("Old Pass", True)),
                "new_pass": bool(row.get("New Pass", True))
            })
            
        return risk_comparison

    def get_factor_comparison_table(self) -> List[Dict[str, Any]]:
        """
        Generate factor comparison table (Factor Betas — Before vs After).
        
        Returns formatted before/after factor beta comparison.
        """
        if self.beta_comparison.empty:
            return []
            
        factor_comparison = []
        
        for _, row in self.beta_comparison.iterrows():
            factor_comparison.append({
                "factor": row.name if hasattr(row, 'name') else "",
                "old": round(row.get("Old", 0), 2),
                "new": round(row.get("New", 0), 2),
                "delta": round(row.get("Δ", 0), 2),
                "max_beta": round(row.get("Max Beta", 0), 2),
                "old_pass": row.get("Old Pass", "PASS"),
                "new_pass": row.get("New Pass", "PASS")
            })
            
        return factor_comparison


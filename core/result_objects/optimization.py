"""Optimization result objects."""

from typing import Dict, Any, Optional, List, Union, Tuple
import numbers
import math
import pandas as pd
from datetime import datetime, UTC
import json
import numpy as np
from dataclasses import dataclass, field
from utils.serialization import make_json_safe
from ._helpers import _convert_to_json_serializable, _clean_nan_values

class OptimizationResult:
    """
    Mathematical portfolio optimization results with QP solvers and risk compliance analysis.
    
    Contains comprehensive optimization results from minimum variance and maximum return
    optimization algorithms, including optimal weights, risk analysis, compliance checks,
    and performance metrics. Supports both constrained and unconstrained optimization.
    
    Key Features:
    - **Optimization Algorithms**: Minimum variance and maximum return with QP solvers
    - **Risk Compliance**: Automated risk limit and beta exposure validation
    - **Weight Analysis**: Position changes, concentration analysis, and allocation breakdown
    - **Performance Metrics**: Risk-adjusted returns, Sharpe ratios, and tracking error
    - **Factor Analysis**: Beta exposure optimization and factor risk budgeting
    - **Proxy Integration**: Automatic proxy injection for enhanced diversification
    
    Optimization Types:
    - **Minimum Variance**: Minimize portfolio volatility subject to constraints
    - **Maximum Return**: Maximize risk-adjusted returns with factor exposure limits
    
    Architecture Role:
        Core Optimization → Service Layer → OptimizationResult → Portfolio Implementation
    
    Example:
        ```python
        # Get optimization result from service
        result = portfolio_service.optimize_portfolio(portfolio_data, "min_variance")
        
        # Access optimal weights
        optimal_weights = result.optimized_weights
        # {"AAPL": 0.25, "MSFT": 0.20, "GOOGL": 0.15, "SGOV": 0.40}
        
        # Analyze weight changes from original
        original_weights = {"AAPL": 0.30, "MSFT": 0.25, "GOOGL": 0.20, "SGOV": 0.25}
        changes = result.get_weight_changes(original_weights)
        # [{"ticker": "SGOV", "change": 0.15, "direction": "increase"}]
        
        # Check risk compliance
        risk_compliant = all(result.risk_table["Pass"])
        beta_compliant = all(result.beta_table["pass"])
        
        # Get performance summary
        summary = result.get_summary()
        volatility = summary["portfolio_volatility"]    # 0.12 (12% annual vol)
        sharpe_ratio = summary["sharpe_ratio"]          # 1.45 (risk-adjusted return)
        
        # Implementation ready weights
        weights_for_trading = result.get_top_positions(20)  # Top 20 positions
        
        # API serialization (Phase 1.5+)
        api_data = result.to_api_response()  # Schema-compliant JSON for APIs
        ```
    
    Use Cases:
    - Portfolio rebalancing and risk reduction optimization
    - Factor exposure management and systematic risk control
    - Performance enhancement through mathematical optimization
    - Compliance-driven portfolio construction and risk budgeting
    """
    
    def __init__(self, 
                 optimized_weights: Dict[str, float],
                 optimization_type: str,
                 risk_table: pd.DataFrame,
                 beta_table: pd.DataFrame,
                 portfolio_summary: Optional[Dict[str, Any]] = None,
                 factor_table: Optional[pd.DataFrame] = None,
                 proxy_table: Optional[pd.DataFrame] = None):
        
        # Core optimization results
        self.optimized_weights = optimized_weights
        self.optimization_type = optimization_type  # "min_variance" or "max_return"
        
        # Risk and beta check tables from actual functions
        self.risk_table = risk_table
        self.beta_table = beta_table
        
        # Additional data for max return optimization
        self.portfolio_summary = portfolio_summary
        self.factor_table = factor_table if factor_table is not None else pd.DataFrame()
        self.proxy_table = proxy_table if proxy_table is not None else pd.DataFrame()
        
        # Analysis timestamp (will be set by builder methods)
        self.analysis_date = None  # Must be set by builder methods
        
        # Optimization metadata (for storing additional context like risk limits)
        self.optimization_metadata = {}
    

    
    @classmethod  
    def from_core_optimization(cls,
                              optimized_weights: Dict[str, float],
                              risk_table: pd.DataFrame,
                              factor_table: pd.DataFrame,
                              optimization_metadata: Dict[str, Any],
                              portfolio_summary: Optional[Dict[str, Any]] = None,
                              proxy_table: Optional[pd.DataFrame] = None) -> 'OptimizationResult':
        """
        Create OptimizationResult from core optimization function output data.
        
        ARCHITECTURE CONTEXT:
        This is the primary factory method for creating OptimizationResult objects from
        core optimization functions (optimize_minimum_variance, optimize_maximum_return).
        It transforms QP solver results and validation data into a structured result object.
        
        DATA FLOW:
        optimize_*() → optimized_weights + validation tables → from_core_optimization() → OptimizationResult
        
        INPUT DATA STRUCTURE:
        - optimized_weights: Optimal portfolio allocation from QP solver
          Format: Dict[ticker, weight] (e.g., {"AAPL": 0.25, "MSFT": 0.30})
        
        - risk_table: Risk limit validation results from optimization
          Format: pd.DataFrame with columns: Metric, Actual, Limit, Pass
          
        - factor_table: Factor beta validation results from optimization  
          Format: pd.DataFrame with columns: factor, portfolio_beta, max_allowed_beta, pass
          
        - optimization_metadata: Optimization context and configuration
          • optimization_type: "min_variance" or "max_return" (str)
          • analysis_date: ISO timestamp when optimization was performed (str)
          • risk_limits: Risk limits configuration used (Dict)
          • solver_info: QP solver details and convergence status (Dict)
          
        - portfolio_summary: Complete portfolio analysis for max return optimization (Optional)
          Contains build_portfolio_view() output with performance metrics
          
        - proxy_table: Industry proxy validation results (Optional)
          Format: pd.DataFrame with proxy beta checks
        
        OPTIMIZATION TYPE HANDLING:
        - **Minimum Variance**: Uses optimized_weights, risk_table, factor_table only
        - **Maximum Return**: Uses all parameters including portfolio_summary for performance metrics
        
        TRANSFORMATION PROCESS:
        1. Create OptimizationResult instance with core optimization data
        2. Set optimization type from metadata
        3. Map factor_table to beta_table for consistency
        4. Store optional data (portfolio_summary, proxy_table) for max return optimization
        5. Set analysis timestamp and optimization metadata
        
        OUTPUT OBJECT CAPABILITIES:
        - to_api_response(): Structured API response with optimization results and compliance
        - get_weight_changes(): Analysis of position changes from original weights
        - get_summary(): Core optimization metrics and performance data
        - to_formatted_report(): Human-readable optimization report for Claude/AI
        
        🔒 BACKWARD COMPATIBILITY CONSTRAINT:
        Must preserve exact field mappings to ensure to_api_response() produces
        identical output structure. Supports both optimization types with unified interface.
        
        Args:
            optimized_weights (Dict[str, float]): Optimal portfolio weights from QP solver
            risk_table (pd.DataFrame): Risk limit validation results
            factor_table (pd.DataFrame): Factor beta validation results
            optimization_metadata (Dict[str, Any]): Optimization context and solver info
            portfolio_summary (Optional[Dict[str, Any]]): Portfolio analysis for max return optimization
            proxy_table (Optional[pd.DataFrame]): Industry proxy validation results
            
        Returns:
            OptimizationResult: Fully populated optimization result with compliance validation
        """
        from datetime import datetime, timezone
        
        instance = cls(
            optimized_weights=optimized_weights, # Optimal portfolio allocation from QP solver
            optimization_type=optimization_metadata.get("optimization_type", "max_return"),
            risk_table=risk_table, # Risk limit validation results from optimization
            beta_table=factor_table,  # Use factor_table as beta_table for consistency
            portfolio_summary=portfolio_summary or {},  # Default to empty dict for min variance
            factor_table=factor_table, # Factor beta validation results from optimization
            proxy_table=proxy_table if proxy_table is not None else pd.DataFrame()  # Default to empty DataFrame for min variance
        )
        
        # Set analysis_date from metadata (when optimization was actually performed)
        instance.analysis_date = datetime.fromisoformat(optimization_metadata["analysis_date"])
        
        # Store optimization metadata for risk limits and other context
        instance.optimization_metadata = optimization_metadata
        
        return instance
    

    
    def get_weight_changes(self, original_weights: Dict[str, float], limit: int = 5) -> List[Dict[str, Any]]:
        """Get the largest weight changes from optimization."""
        changes = []
        all_tickers = set(list(original_weights.keys()) + list(self.optimized_weights.keys()))
        
        for ticker in all_tickers:
            original = original_weights.get(ticker, 0)
            new = self.optimized_weights.get(ticker, 0)
            change = new - original
            
            if abs(change) > 0.001:  # Only significant changes
                changes.append({
                    "ticker": ticker,
                    "original_weight": round(original, 4),
                    "new_weight": round(new, 4),
                    "change": round(change, 4),
                    "change_bps": round(change * 10000)
                })
        
        # Sort by absolute change and return top N
        changes.sort(key=lambda x: abs(x["change"]), reverse=True)
        return changes[:limit]
    
    def get_agent_snapshot(self, original_weights: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        """Compact optimization metrics for agent consumption."""
        # Position counts
        active_positions = {k: v for k, v in self.optimized_weights.items() if abs(v) > 0.001}
        total_positions = len(active_positions)

        # Concentration (abs for short positions)
        weights_list = list(active_positions.values())
        largest_weight = max(abs(w) for w in weights_list) if weights_list else 0
        hhi = sum(w ** 2 for w in weights_list) if weights_list else 0

        # Trade count (positions that change significantly)
        trades_required = 0
        if original_weights:
            all_tickers = set(list(original_weights.keys()) + list(self.optimized_weights.keys()))
            for ticker in all_tickers:
                orig = original_weights.get(ticker, 0)
                new = self.optimized_weights.get(ticker, 0)
                if abs(new - orig) >= 0.005:
                    trades_required += 1

        # Compliance (None = checks not available, True/False = checked)
        has_risk_checks = not self.risk_table.empty and "Pass" in self.risk_table.columns
        has_factor_checks = not self.beta_table.empty and "pass" in self.beta_table.columns
        has_proxy_checks = not self.proxy_table.empty and "pass" in self.proxy_table.columns

        risk_passes = bool(self.risk_table["Pass"].all()) if has_risk_checks else None
        risk_violation_count = int((~self.risk_table["Pass"]).sum()) if has_risk_checks else 0

        factor_passes = bool(self.beta_table["pass"].all()) if has_factor_checks else None
        factor_violation_count = int((~self.beta_table["pass"]).sum()) if has_factor_checks else 0

        proxy_passes = bool(self.proxy_table["pass"].all()) if has_proxy_checks else None
        proxy_violation_count = int((~self.proxy_table["pass"]).sum()) if has_proxy_checks else 0

        # Weight changes (top 5, filtered to >= 50bps using same raw threshold as trade count)
        weight_changes: List[Dict[str, Any]] = []
        if original_weights:
            raw_changes = self.get_weight_changes(original_weights, limit=20)
            filtered_changes: List[Dict[str, Any]] = []
            for change_row in raw_changes:
                orig = original_weights.get(change_row["ticker"], 0)
                new = self.optimized_weights.get(change_row["ticker"], 0)
                if abs(new - orig) >= 0.005:
                    filtered_changes.append(change_row)
            weight_changes = filtered_changes[:5]

        # Top positions (top 5)
        top_positions = self.get_top_positions(5)

        # Portfolio metrics (max_return only)
        portfolio_metrics = None
        if self.portfolio_summary:
            portfolio_metrics = {
                "volatility_annual_pct": round(self.portfolio_summary.get("volatility_annual", 0) * 100, 2),
                "volatility_monthly_pct": round(self.portfolio_summary.get("volatility_monthly", 0) * 100, 2),
                "herfindahl": round(self.portfolio_summary.get("herfindahl", 0), 4),
            }

        # Verdict (violations override trade-based verdict)
        compliance_known = (
            risk_passes is not None
            or factor_passes is not None
            or proxy_passes is not None
        )
        if risk_violation_count > 0 or factor_violation_count > 0 or proxy_violation_count > 0:
            verdict = "has violations"
        elif not original_weights:
            verdict = "baseline unavailable"
        elif trades_required == 0 and compliance_known:
            verdict = "already optimal"
        elif trades_required == 0:
            verdict = "no changes needed"
        elif trades_required <= 3:
            verdict = "minor rebalance"
        elif trades_required <= 10:
            verdict = "moderate rebalance"
        else:
            verdict = "major rebalance"

        snapshot: Dict[str, Any] = {
            "verdict": verdict,
            "optimization_type": self.optimization_type,
            "positions": {
                "total": total_positions,
                "largest_weight_pct": round(largest_weight * 100, 2),
                "hhi": round(hhi, 4),
            },
            "trades_required": trades_required,
            "compliance": {
                "risk_passes": risk_passes,
                "risk_violation_count": risk_violation_count,
                "factor_passes": factor_passes,
                "factor_violation_count": factor_violation_count,
                "proxy_passes": proxy_passes,
                "proxy_violation_count": proxy_violation_count,
            },
            "top_positions": {k: round(v * 100, 2) for k, v in top_positions.items()},
            "weight_changes": weight_changes,
        }

        if portfolio_metrics is not None:
            snapshot["portfolio_metrics"] = portfolio_metrics

        return snapshot


    

    
    def get_summary(self) -> Dict[str, Any]:
        """Get optimization summary."""
        summary = {
            "optimization_type": self.optimization_type,
            "total_positions": len([w for w in self.optimized_weights.values() if abs(w) > 0.001]),
            "largest_position": max(self.optimized_weights.values()) if self.optimized_weights else 0,
            "smallest_position": min([w for w in self.optimized_weights.values() if w > 0.001]) if self.optimized_weights else 0,
        }
        
        # Add portfolio metrics if available (max return optimization)
        if self.portfolio_summary:
            summary["portfolio_metrics"] = {
                "volatility_annual": self.portfolio_summary.get("volatility_annual", 0),
                "volatility_monthly": self.portfolio_summary.get("volatility_monthly", 0),
                "herfindahl": self.portfolio_summary.get("herfindahl", 0)
            }
        
        return summary
    
    def get_top_positions(self, n: int = 10) -> Dict[str, float]:
        """Get top N positions by weight."""
        sorted_weights = sorted(self.optimized_weights.items(), key=lambda x: abs(x[1]), reverse=True)
        return dict(sorted_weights[:n])
    
    def to_formatted_report(self) -> str:
        """Format optimization results for display (identical to to_cli_report())."""
        return self.to_cli_report()
    
    def to_api_response(self) -> Dict[str, Any]:
        """
        Convert OptimizationResult to comprehensive API response format.
        
        CONSUMER ANALYSIS:
        - Direct API: Uses full structured response for programmatic optimization analysis
        - Claude/AI: Only uses formatted_report (ignores all structured data)
        - Frontend: Uses adapters to transform structured data for optimization UI components
        
        RESPONSE STRUCTURE:
        
        **Core Optimization Results:**
        - optimized_weights: Dict[ticker, weight] - Optimal portfolio allocation from QP solver
        - optimization_type: str - "min_variance" or "max_return"
        - analysis_date: str (ISO-8601 UTC) - When optimization was performed
        - summary: Dict - Optimization metrics (total_positions, largest_position, etc.)
        
        **Structured Compliance Analysis (Raw - for programming):**
        - risk_analysis: {
            risk_checks: List[Dict],           # All risk limit checks in row format
            risk_passes: bool,                 # True if all risk checks pass
            risk_violations: List[Dict],       # Only failed risk checks
            risk_limits: Dict                  # Risk limits configuration applied
          }
        - beta_analysis: {
            factor_beta_checks: List[Dict],    # Factor beta checks in row format
            proxy_beta_checks: List[Dict],     # Industry proxy checks in row format
            factor_beta_passes: bool,          # True if all factor checks pass
            proxy_beta_passes: bool,           # True if all proxy checks pass
            factor_beta_violations: List[Dict], # Only failed factor checks
            proxy_beta_violations: List[Dict]   # Only failed proxy checks
          }
        
        **Legacy Table Format (Column-oriented - for backward compatibility):**
        - risk_table: Dict[column, Dict[index, value]] - Risk compliance checks (DataFrame format)
        - beta_table: Dict[column, Dict[index, value]] - Factor exposure analysis (DataFrame format)
        - factor_table: Dict[column, Dict[index, value]] - Factor beta checks (DataFrame format)
        - proxy_table: Dict[column, Dict[index, value]] - Proxy/industry beta checks (DataFrame format)
        
        **Performance Metrics (Max Return Optimization Only):**
        - portfolio_summary: Dict - Complete portfolio analysis with performance metrics
          Contains volatility, returns, factor exposures from build_portfolio_view()
        
        **Human-Readable Output:**
        - formatted_report: str - Complete CLI-style optimization report (primary Claude/AI input)
        
        OPTIMIZATION TYPE DIFFERENCES:
        - **Minimum Variance**: Basic structure with risk/beta compliance only
        - **Maximum Return**: Includes portfolio_summary with performance metrics and factor analysis
        
        DATA QUALITY NOTES:
        - All timestamps are UTC and serialized via ISO-8601
        - Structured analysis provides row-oriented data (easier for frontends)
        - Legacy tables maintain column-oriented format for backward compatibility
        - Violation lists contain only failed checks for efficient error handling
        
        EXAMPLE STRUCTURED DATA:
        {
          "risk_analysis": {
            "risk_checks": [{"Metric": "Annual Volatility", "Actual": 0.12, "Limit": 0.15, "Pass": true}],
            "risk_passes": true,
            "risk_violations": []
          },
          "beta_analysis": {
            "factor_beta_checks": [{"factor": "market", "portfolio_beta": 0.95, "max_allowed_beta": 1.0, "pass": true}],
            "factor_beta_passes": true,
            "factor_beta_violations": []
          }
        }
        
        Returns:
            Dict[str, Any]: Complete optimization results with compliance validation and performance metrics
        """
        # Use standard serialization (consistent with rest of codebase)
        risk_checks = _convert_to_json_serializable(self.risk_table) # Risk limit validation results from optimization
        factor_checks = _convert_to_json_serializable(self.beta_table) # Factor beta validation results from optimization
        proxy_checks = _convert_to_json_serializable(self.proxy_table) # Industry proxy validation results from optimization
        
        # Compute summary statuses for quick API consumption
        risk_passes = bool(self.risk_table['Pass'].all()) # True if all risk checks pass
        factor_passes = bool(self.beta_table['pass'].all()) # True if all factor checks pass
        proxy_passes = bool(self.proxy_table['pass'].all()) if not self.proxy_table.empty else True # True if all proxy checks pass
        
        # Extract violations only (failed checks for error handling)
        risk_violations = _convert_to_json_serializable(self.risk_table[~self.risk_table['Pass']]) # Only failed risk checks
        factor_violations = _convert_to_json_serializable(self.beta_table[~self.beta_table['pass']]) # Only failed factor checks
        proxy_violations = _convert_to_json_serializable(self.proxy_table[~self.proxy_table['pass']]) if not self.proxy_table.empty else [] # Only failed proxy checks
        
        # Build comprehensive response with both structured and original formats
        result = {
            "optimized_weights": self.optimized_weights,  # Dict[str, float]: Optimal portfolio allocation weights per ticker
            "optimization_type": self.optimization_type,  # str: Type of optimization performed ("min_variance" or "max_return")
            "analysis_date": self.analysis_date.isoformat(),  # str: ISO timestamp when optimization was performed
            "summary": self.get_summary(),  # str: Optimization summary of positions
            "formatted_report": self.to_formatted_report(),  # str: Complete CLI-style formatted report
            
            # NEW: Structured risk analysis with computed summaries (easy API consumption)
            "risk_analysis": {
                "risk_checks": risk_checks,              # List[Dict]: All risk checks in row format
                "risk_passes": risk_passes,              # bool: True if all risk checks pass
                "risk_violations": risk_violations,      # List[Dict]: Only failed risk checks
                "risk_limits": self._get_risk_limits_config()  # Dict: Risk limits configuration applied
            },
            
            # NEW: Structured beta analysis with computed summaries (easy API consumption)
            "beta_analysis": {
                "factor_beta_checks": factor_checks,     # List[Dict]: Factor beta checks in row format
                "proxy_beta_checks": proxy_checks,       # List[Dict]: Industry proxy beta checks in row format
                "factor_beta_passes": factor_passes,     # bool: True if all factor checks pass
                "proxy_beta_passes": proxy_passes,       # bool: True if all proxy checks pass
                "factor_beta_violations": factor_violations,  # List[Dict]: Only failed factor checks
                "proxy_beta_violations": proxy_violations      # List[Dict]: Only failed proxy checks
            },
            
            # LEGACY: Original flat table format (backward compatibility & detailed analysis)
            "risk_table": _convert_to_json_serializable(self.risk_table),      # Dict: Risk limit compliance checks (column-oriented)
            "beta_table": _convert_to_json_serializable(self.beta_table),      # Dict: Factor exposure analysis (column-oriented)
            "factor_table": _convert_to_json_serializable(self.factor_table),  # Dict: Factor beta checks for optimization (column-oriented)
            "proxy_table": _convert_to_json_serializable(self.proxy_table),    # Dict: Proxy/industry beta checks for optimization (column-oriented)
        }
        
        # Include portfolio_summary for max-return optimization
        if self.portfolio_summary is not None:
            result["portfolio_summary"] = self.portfolio_summary  # Dict: Portfolio performance metrics
            
        # Apply JSON serialization for any remaining complex objects
        return _convert_to_json_serializable(result)
    

    def _get_risk_limits_config(self) -> Dict[str, Any]:
        """
        Extract risk limits configuration that was applied during optimization.
        
        Returns the risk limits configuration from optimization metadata,
        providing context about what limits were enforced during the optimization.
        
        Returns:
            Dict[str, Any]: Risk limits configuration containing:
                - portfolio_limits: Overall portfolio constraints
                - concentration_limits: Position size limits  
                - variance_limits: Factor variance constraints
                
        Example:
            {
                "portfolio_limits": {"max_volatility": 0.4, "max_loss": -0.25},
                "concentration_limits": {"max_single_stock_weight": 0.4},
                "variance_limits": {"max_factor_contribution": 0.3, "max_market_contribution": 0.5}
            }
        """
        # Extract from optimization metadata if available
        if hasattr(self, 'optimization_metadata') and self.optimization_metadata:
            return self.optimization_metadata.get('risk_limits', {})
        
        # Fallback: return empty dict if no metadata available
        # In a future enhancement, this could be passed during construction
        return {}



    def to_cli_report(self) -> str:
        """Generate complete CLI formatted report - IDENTICAL to current CLI output"""
        if self.optimization_type in ["min_variance", "minimum_variance"]:
            return self._format_min_variance_report()
        else:
            return self._format_max_return_report()

    def _format_min_variance_report(self) -> str:
        """Generate minimum variance CLI report - IDENTICAL to print_min_var_report() output"""
        sections = []
        
        # Add weights section
        sections.append(self._format_min_variance_weights())
        
        # Add risk checks section
        sections.append(self._format_min_variance_risk_checks())
        
        # Add factor exposures section
        sections.append(self._format_min_variance_factor_checks())
        
        return "\n".join(sections)

    def _format_max_return_report(self) -> str:
        """Generate max return CLI report - IDENTICAL to print_max_return_report() output"""
        sections = []
        
        # Add weights section
        sections.append(self._format_optimized_weights())
        
        # Add risk checks section
        sections.append(self._format_risk_compliance())
        
        # Add factor exposures section
        sections.append(self._format_factor_exposures())
        
        # Add proxy analysis section if available
        proxy_section = self._format_proxy_analysis()
        if proxy_section:
            sections.append(proxy_section)
        
        return "\n".join(sections)

    def _format_optimized_weights(self) -> str:
        """Format optimized weights table - EXACT copy from print_max_return_report"""
        lines = ["\n🎯  Target max-return, risk-constrained weights\n"]
        for k, v in sorted(self.optimized_weights.items(), key=lambda kv: -abs(kv[1])):
            if abs(v) > 1e-4:
                lines.append(f"{k:<10} : {v:.2%}")
        return "\n".join(lines)

    def _format_risk_compliance(self) -> str:
        """Format risk compliance checks - EXACT copy from print_max_return_report"""
        lines = ["\n📐  Max-return Portfolio – Risk Checks\n"]
        pct = lambda x: f"{x:.2%}"
        lines.append(self.risk_table.to_string(index=False, formatters={"Actual": pct, "Limit": pct}))
        return "\n".join(lines)

    def _format_factor_exposures(self) -> str:
        """Format factor exposures - EXACT copy from print_max_return_report"""
        lines = ["\n📊  Aggregate Factor Exposures\n"]
        fmt = {
            "portfolio_beta":   "{:.2f}".format,
            "max_allowed_beta": "{:.2f}".format,
            "buffer":           "{:.2f}".format,
            "pass":             lambda x: "PASS" if x else "FAIL",
        }
        lines.append(self.factor_table.to_string(index_names=False, formatters=fmt))
        return "\n".join(lines)

    def _format_proxy_analysis(self) -> str:
        """Format proxy analysis - EXACT copy from print_max_return_report"""
        if self.proxy_table is not None and not self.proxy_table.empty:
            lines = ["\n📊  Industry Exposure Checks\n"]
            fmt = {
                "portfolio_beta":   "{:.2f}".format,
                "max_allowed_beta": "{:.2f}".format,
                "buffer":           "{:.2f}".format,
                "pass":             lambda x: "PASS" if x else "FAIL",
            }
            lines.append(self.proxy_table.to_string(index_names=False, formatters=fmt))
            return "\n".join(lines)
        return ""

    def _format_min_variance_weights(self) -> str:
        """Format minimum variance weights - EXACT copy from print_min_var_report"""
        lines = ["\n🎯  Target minimum-variance weights\n"]
        for t, w in sorted(self.optimized_weights.items(), key=lambda kv: -abs(kv[1])):
            if abs(w) >= 0.0001:
                lines.append(f"{t:<10} : {w:.2%}")
        return "\n".join(lines)

    def _format_min_variance_risk_checks(self) -> str:
        """Format minimum variance risk checks - EXACT copy from print_min_var_report"""
        lines = ["\n📐  Optimised Portfolio – Risk Checks\n"]
        pct = lambda x: f"{x:.2%}"
        lines.append(self.risk_table.to_string(index=False, formatters={"Actual": pct, "Limit": pct}))
        return "\n".join(lines)

    def _format_min_variance_factor_checks(self) -> str:
        """Format minimum variance factor checks - EXACT copy from print_min_var_report"""
        from helpers_display import _drop_factors
        
        lines = ["\n📊  Optimised Portfolio – Factor Betas\n"]
        beta_tbl = _drop_factors(self.beta_table)
        lines.append(beta_tbl.to_string(formatters={
            "Beta":      "{:.2f}".format,
            "Max Beta":  "{:.2f}".format,
            "Buffer":    "{:.2f}".format,
            "pass":      lambda x: "PASS" if x else "FAIL",  # Use lowercase 'pass' to match actual column name
        }))
        return "\n".join(lines)


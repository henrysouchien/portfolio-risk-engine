"""Performance result objects."""

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

@dataclass
class PerformanceResult:
    """
    Portfolio performance analysis results matching calculate_portfolio_performance_metrics output.
    
    Contains comprehensive performance metrics including returns, risk metrics,
    risk-adjusted returns, benchmark analysis, and monthly statistics. This result object
    provides both structured data access and JSON-serializable output for API responses.
    
    Key Data Categories:
    - **Returns Analysis**: Total, annualized, and periodic return calculations
    - **Risk Metrics**: Volatility, maximum drawdown, downside deviation measures
    - **Risk-Adjusted Returns**: Sharpe, Sortino, Information, and Calmar ratios
    - **Benchmark Analysis**: Alpha, beta, correlation, and tracking error vs benchmark
    - **Monthly Statistics**: Period-by-period performance breakdown and statistics
    - **Time Series Data**: Monthly returns and cumulative performance over time
    - **Dividend Metrics**: Portfolio dividend yield, per‑ticker yields, income contributions,
      data coverage, and dollar estimates when total_value is available (present on successful analyses)
    
    Usage Patterns:
    1. **Structured Data Access**: Use getter methods for programmatic analysis
    2. **Performance Summary**: Use get_summary() for key metrics overview
    3. **Risk Analysis**: Use get_risk_metrics() for risk-specific measures
    4. **API Serialization**: Use to_api_response() for JSON export and API responses
    5. **Formatted Reporting**: Use to_cli_report() for human-readable display
    
    Architecture Role:
        Core Functions → Service Layer → PerformanceResult → Consumer (API/Claude/UI)
    
    Example:
        ```python
        # Get result from service layer
        result = portfolio_service.analyze_performance(portfolio_data, benchmark='SPY')
        
        # Access key performance metrics
        total_return = result.returns["total_return"]           # 0.155 (15.5% total return)
        annual_return = result.returns["annualized_return"]     # 0.124 (12.4% annualized)
        volatility = result.risk_metrics["volatility"]         # 0.185 (18.5% volatility)
        sharpe_ratio = result.risk_adjusted_returns["sharpe_ratio"]  # 1.25 (risk-adjusted)
        
        # Get performance summary
        summary = result.get_summary()
        win_rate = summary["win_rate"]                          # 0.58 (58% positive months)
        max_drawdown = summary["max_drawdown"]                  # -0.125 (12.5% max loss)
        
        # Benchmark comparison
        alpha = result.benchmark_analysis["alpha"]              # 0.025 (2.5% outperformance)
        beta = result.benchmark_analysis["beta"]                # 1.02 (market correlation)
        tracking_error = result.risk_metrics["tracking_error"] # 0.045 (4.5% tracking error)
        
        # Export for API response (OpenAPI schema compliant)
        api_data = result.to_api_response()
        # {"analysis_period": {...}, "returns": {...}, "risk_metrics": {...}, ...}
        
        # Get formatted report for display
        report = result.to_cli_report()
        # "📊 Portfolio Performance Analysis\n==================================================\n..."
        ```
        
    Data Quality: All time series data is properly handled and JSON-serializable for API usage.
    Performance: Result creation ~5-20ms, summary calculations ~1-3ms.
    """
    
    # Analysis period information
    analysis_period: Dict[str, Any]
    
    # Returns metrics
    returns: Dict[str, float]
    
    # Risk metrics
    risk_metrics: Dict[str, float]
    
    # Risk-adjusted returns
    risk_adjusted_returns: Dict[str, float]
    
    # Benchmark analysis
    benchmark_analysis: Dict[str, float]
    
    # Benchmark comparison
    benchmark_comparison: Dict[str, float]
    
    # Monthly statistics
    monthly_stats: Dict[str, float]
    
    # Risk-free rate
    risk_free_rate: float
    
    # Monthly returns time series
    monthly_returns: Dict[str, float]
    
    # Metadata
    analysis_date: datetime
    portfolio_name: Optional[str] = None
    portfolio_file: Optional[str] = None
    
    # Additional fields for CLI-API parity
    _allocations: Optional[Dict[str, Any]] = None
    
    # Data quality information
    excluded_tickers: Optional[List[str]] = None
    warnings: Optional[List[str]] = None
    analysis_notes: Optional[str] = None
    
    # Dividend metrics (optional)
    dividend_metrics: Optional[Dict[str, Any]] = None
    
    @classmethod  
    def from_core_analysis(cls,
                          performance_metrics: Dict[str, Any],
                          analysis_period: Dict[str, Any], 
                          portfolio_summary: Dict[str, Any],
                          analysis_metadata: Dict[str, Any],
                          allocations: Optional[Dict[str, Any]] = None) -> 'PerformanceResult':
        """
        Create PerformanceResult from core performance analysis function data.
        
        ARCHITECTURE CONTEXT:
        This is the primary factory method for creating PerformanceResult objects from
        core performance analysis functions (calculate_portfolio_performance_metrics).
        It transforms performance calculations into a structured result object ready for API responses.
        
        DATA FLOW:
        calculate_portfolio_performance_metrics() → performance_metrics + metadata → from_core_analysis() → PerformanceResult
        
        INPUT DATA STRUCTURE:
        - performance_metrics: Complete performance calculation results containing:
          • analysis_period: Dict with start_date, end_date, total_months, years
          • returns: Dict with total_return, annualized_return, best_month, worst_month, positive_months, negative_months, win_rate
          • risk_metrics: Dict with volatility, maximum_drawdown, downside_deviation, tracking_error
          • risk_adjusted_returns: Dict with sharpe_ratio, sortino_ratio, information_ratio, calmar_ratio
          • benchmark_analysis: Dict with benchmark_ticker, alpha_annual, beta, r_squared, excess_return
          • benchmark_comparison: Dict with portfolio_return, benchmark_return, portfolio_volatility, benchmark_volatility, portfolio_sharpe, benchmark_sharpe
          • monthly_stats: Dict with average_monthly_return, average_win, average_loss, win_loss_ratio
          • monthly_returns: Dict[date_str, return] time series data
          • risk_free_rate: Risk-free rate used in calculations (float, as percentage)
        
        - analysis_period: Time period analysis configuration
          • start_date: Analysis start date (str, YYYY-MM-DD)
          • end_date: Analysis end date (str, YYYY-MM-DD)  
          • years: Analysis period in years (float)
          • total_months: Analysis period in months (int)
          • positions: Number of positions in portfolio (int)
        
        - portfolio_summary: Portfolio context and metadata
          • file: Portfolio file path (str)
          • positions: Position count (int)
          • benchmark: Benchmark ticker used (str)
          • portfolio_name: Display name (str)
        
        - analysis_metadata: Analysis execution context
          • analysis_date: ISO timestamp when analysis was performed (str)
          • calculation_successful: Whether calculations completed successfully (bool)
          • portfolio_file: Source file path (str)
        
        - allocations: Portfolio allocation data (Optional)
          Dict[ticker, weight] for position analysis
        
        TRANSFORMATION PROCESS:
        1. Parse analysis timestamp from metadata
        2. Build complete analysis_period with position count
        3. Map performance_metrics to structured fields
        4. Set portfolio context and metadata
        5. Ensure CLI compatibility with required fields
        
        OUTPUT OBJECT CAPABILITIES:
        - to_api_response(): Complete structured API response with performance metrics
        - to_formatted_report(): Human-readable CLI report for Claude/AI
        - get_summary(): Core performance metrics for quick analysis
        - Time series analysis with monthly returns and benchmark comparison
        
        🔒 BACKWARD COMPATIBILITY CONSTRAINT:
        Must preserve exact field mappings to ensure to_api_response() produces
        identical output structure. All existing API fields must be maintained.
        
        Args:
            performance_metrics (Dict[str, Any]): Complete performance calculation results
            analysis_period (Dict[str, Any]): Time period configuration and metrics
            portfolio_summary (Dict[str, Any]): Portfolio context and benchmark info
            analysis_metadata (Dict[str, Any]): Analysis execution context and timestamps
            allocations (Optional[Dict[str, Any]]): Portfolio allocation data for position analysis
            
        Returns:
            PerformanceResult: Fully populated performance analysis with time series data
        """
        from datetime import datetime
        
        # Parse analysis_date from metadata
        analysis_date_str = analysis_metadata.get("analysis_date")
        if isinstance(analysis_date_str, str):
            analysis_date = datetime.fromisoformat(analysis_date_str.replace('Z', '+00:00'))
        else:
            analysis_date = datetime.now()
        
        # Build complete analysis_period with all required fields
        complete_analysis_period = analysis_period.copy()
        if 'positions' not in complete_analysis_period:
            complete_analysis_period['positions'] = portfolio_summary.get('positions', 0)
        
        # Ensure total_months is present for CLI formatting compatibility
        if 'total_months' not in complete_analysis_period and 'years' in complete_analysis_period:
            complete_analysis_period['total_months'] = int(complete_analysis_period['years'] * 12)
        
        return cls(
            # Map from core analysis structure to PerformanceResult fields
            analysis_period=complete_analysis_period, # Time period configuration and metrics
            returns=performance_metrics.get("returns", {}), # Performance metrics
            risk_metrics=performance_metrics.get("risk_metrics", {}), # Risk metrics
            risk_adjusted_returns=performance_metrics.get("risk_adjusted_returns", {}), # Risk-adjusted returns
            benchmark_analysis=performance_metrics.get("benchmark_analysis", {}), # Benchmark analysis
            benchmark_comparison=performance_metrics.get("benchmark_comparison", {}), # Benchmark comparison
            monthly_stats=performance_metrics.get("monthly_stats", {}), # Monthly statistics
            risk_free_rate=performance_metrics.get("risk_free_rate", 0.0), # Risk-free rate
            monthly_returns=performance_metrics.get("monthly_returns", {}), # Monthly returns
            analysis_date=analysis_date, # Analysis date
            portfolio_name=portfolio_summary.get("name"), # Portfolio name
            portfolio_file=portfolio_summary.get("file"), # Portfolio file
            # Additional fields for position counting and API compatibility
            _allocations=allocations, # Portfolio allocation data for position analysis
            # Data quality information
            excluded_tickers=performance_metrics.get("excluded_tickers"), # Tickers excluded due to insufficient data
            warnings=performance_metrics.get("warnings"), # Data quality warnings
            analysis_notes=performance_metrics.get("analysis_notes"), # Analysis notes about data quality
            # Dividend metrics
            dividend_metrics=performance_metrics.get("dividend_metrics"),
        )
    
    def get_summary(self) -> Dict[str, Any]:
        """Get key performance metrics summary."""
        return {
            "total_return": self.returns.get("total_return", 0),
            "annualized_return": self.returns.get("annualized_return", 0),
            "volatility": self.risk_metrics.get("volatility", 0),
            "sharpe_ratio": self.risk_adjusted_returns.get("sharpe_ratio", 0),
            "max_drawdown": self.risk_metrics.get("maximum_drawdown", 0),
            "win_rate": self.returns.get("win_rate", 0),
            "analysis_years": self.analysis_period.get("years", 0)
        }

    def get_agent_snapshot(self) -> Dict[str, Any]:
        """Compact metrics payload for agent-oriented performance responses."""
        returns = self.returns or {}
        risk = self.risk_metrics or {}
        risk_adjusted = self.risk_adjusted_returns or {}
        benchmark = self.benchmark_analysis or {}
        period = self.analysis_period or {}
        benchmark_comp = self.benchmark_comparison or {}

        years = period.get("years")
        rounded_years = (
            round(float(years), 1)
            if isinstance(years, numbers.Real) and not isinstance(years, bool)
            else 0.0
        )

        return make_json_safe({
            "mode": "hypothetical",
            "period": {
                "start_date": period.get("start_date"),
                "end_date": period.get("end_date"),
                "months": period.get("total_months"),
                "years": rounded_years,
            },
            "returns": {
                "total_return_pct": returns.get("total_return"),
                "annualized_return_pct": returns.get("annualized_return"),
                "best_month_pct": returns.get("best_month"),
                "worst_month_pct": returns.get("worst_month"),
                "win_rate_pct": returns.get("win_rate"),
            },
            "risk": {
                "volatility_pct": risk.get("volatility"),
                "max_drawdown_pct": risk.get("maximum_drawdown"),
                "sharpe_ratio": risk_adjusted.get("sharpe_ratio"),
                "sortino_ratio": risk_adjusted.get("sortino_ratio"),
            },
            "benchmark": {
                "ticker": benchmark.get("benchmark_ticker"),
                "alpha_annual_pct": benchmark.get("alpha_annual"),
                "beta": benchmark.get("beta"),
                "portfolio_return_pct": benchmark_comp.get("portfolio_total_return"),
                "benchmark_return_pct": benchmark_comp.get("benchmark_total_return"),
                "excess_return_pct": benchmark.get("excess_return"),
            },
            "verdict": self._categorize_performance(),
            "insights": self._generate_key_insights(),
        })
    
    def get_risk_metrics(self) -> Dict[str, float]:
        """Get risk-specific metrics."""
        return {
            "volatility": self.risk_metrics.get("volatility", 0),
            "maximum_drawdown": self.risk_metrics.get("maximum_drawdown", 0),
            "downside_deviation": self.risk_metrics.get("downside_deviation", 0),
            "tracking_error": self.risk_metrics.get("tracking_error", 0)
        }
    
    def get_risk_adjusted_returns(self) -> Dict[str, float]:
        """Get risk-adjusted return metrics."""
        return {
            "sharpe_ratio": self.risk_adjusted_returns.get("sharpe_ratio", 0),
            "sortino_ratio": self.risk_adjusted_returns.get("sortino_ratio", 0),
            "information_ratio": self.risk_adjusted_returns.get("information_ratio", 0),
            "calmar_ratio": self.risk_adjusted_returns.get("calmar_ratio", 0)
        }
    
    def _categorize_performance(self) -> str:
        """
        Categorize performance based on risk-adjusted metrics.
        
        Returns clean enum value for API logic/filtering.
        """
        sharpe = self.risk_adjusted_returns.get("sharpe_ratio")
        annual_return = self.returns.get("annualized_return")
        if sharpe is None or annual_return is None:
            return "unknown"
        
        if sharpe >= 1.5 and annual_return >= 15:
            return "excellent"
        elif sharpe >= 1.0 and annual_return >= 10:
            return "good"
        elif sharpe >= 0.5 and annual_return >= 5:
            return "fair"
        else:
            return "poor"
    
    def _generate_key_insights(self) -> list:
        """
        Generate key insights bullets based on performance metrics.
        
        Returns actionable insights highlighting strengths and areas for improvement.
        """
        insights = []
        
        # Alpha generation insight
        alpha = self.benchmark_analysis.get("alpha_annual", 0)
        if alpha is not None and alpha > 5:
            insights.append(f"• Strong alpha generation (+{alpha:.1f}% vs benchmark)")
        elif alpha is not None and alpha < -2:
            insights.append(f"• Underperforming benchmark ({alpha:.1f}% alpha)")
        
        # Risk-adjusted returns insight
        sharpe = self.risk_adjusted_returns.get("sharpe_ratio", 0)
        if sharpe is not None and sharpe > 1.2:
            insights.append(f"• Excellent risk-adjusted returns (Sharpe: {sharpe:.2f})")
        elif sharpe is not None and sharpe < 0.5:
            insights.append(f"• Poor risk-adjusted returns (Sharpe: {sharpe:.2f})")
        
        # Volatility insight
        volatility = self.risk_metrics.get("volatility", 0)
        benchmark_vol = self.benchmark_comparison.get("benchmark_volatility", 0)
        if (
            volatility is not None
            and benchmark_vol is not None
            and benchmark_vol > 0
            and volatility > benchmark_vol * 1.2
        ):
            insights.append(f"• High volatility ({volatility:.1f}% vs {benchmark_vol:.1f}% benchmark)")
        
        # Win rate insight
        win_rate = self.returns.get("win_rate", 0)
        if win_rate is not None and win_rate > 65:
            insights.append(f"• High consistency ({win_rate:.0f}% positive months)")
        elif win_rate is not None and win_rate < 50:
            insights.append(f"• Low consistency ({win_rate:.0f}% positive months)")
        
        # Drawdown insight
        max_dd = self.risk_metrics.get("maximum_drawdown", 0)
        if max_dd is not None and abs(max_dd) > 25:
            insights.append(f"• Significant drawdown risk (max: {max_dd:.1f}%)")
        
        return insights
    
    def _format_analysis_period(self) -> str:
        """Return human-readable analysis period text (e.g. "2019-01-31 to 2025-06-27")."""
        if not self.analysis_period:
            return ""
        start = self.analysis_period.get("start_date") or self.analysis_period.get("start")
        end = self.analysis_period.get("end_date") or self.analysis_period.get("end")
        if start and end:
            return f"{start} to {end}"
        return ""

    def get_position_count(self) -> int:
        """
        Get the number of positions in the portfolio.
        
        Attempts to derive from allocations data if available.
        """
        if self._allocations:
            return len(self._allocations)
        
        # Fallback: estimate from portfolio name or return unknown
        return 0  # Will be updated when allocations data is available
    
    def to_api_response(self) -> Dict[str, Any]:
        """
        Convert PerformanceResult to comprehensive API response format.
        
        CONSUMER ANALYSIS:
        - Direct API: Uses full structured response for programmatic performance analysis
        - Claude/AI: Only uses formatted_report (ignores all structured data)
        - Frontend: Uses adapters to transform structured data for performance charts and tables
        
        RESPONSE STRUCTURE:
        
        **Analysis Period & Context:**
        - analysis_period: Dict with time period configuration
          • start_date: str (YYYY-MM-DD) - Analysis start date
          • end_date: str (YYYY-MM-DD) - Analysis end date
          • years: float - Analysis period in years
          • total_months: int - Analysis period in months
          • positions: int - Number of positions in portfolio
        - portfolio_name: str (Optional) - Portfolio identifier
        - analysis_date: str (ISO-8601 UTC) - When analysis was performed
        
        **Returns Analysis:**
        - returns: Dict with return metrics
          • total_return: float - Cumulative return over period (as percentage)
          • annualized_return: float - Annualized return rate (as percentage)
          • best_month: float - Highest monthly return (as percentage)
          • worst_month: float - Lowest monthly return (as percentage)
          • positive_months: int - Number of months with positive returns
          • negative_months: int - Number of months with negative returns
          • win_rate: float - Percentage of positive return periods
        
        **Risk Metrics:**
        - risk_metrics: Dict with risk measures
          • volatility: float - Annualized volatility (as percentage)
          • maximum_drawdown: float - Maximum peak-to-trough decline (as percentage)
          • downside_deviation: float - Downside risk measure (as percentage)
          • tracking_error: float - Standard deviation of excess returns vs benchmark (as percentage)
        
        **Risk-Adjusted Returns:**
        - risk_adjusted_returns: Dict with risk-adjusted performance ratios
          • sharpe_ratio: float - Excess return per unit of risk
          • sortino_ratio: float - Excess return per unit of downside risk
          • information_ratio: float - Active return per unit of tracking error
          • calmar_ratio: float - Annualized return divided by maximum drawdown
        
        **Benchmark Analysis:**
        - benchmark_analysis: Dict with benchmark performance metrics
          • benchmark_ticker: str - Benchmark ticker symbol used
          • alpha_annual: float - Annual alpha vs benchmark (as percentage)
          • beta: float - Portfolio sensitivity to benchmark movements
          • r_squared: float - R-squared from benchmark regression
          • excess_return: float - Annual excess return vs benchmark (as percentage)
        - benchmark_comparison: Dict with side-by-side performance metrics
          • portfolio_return: float - Portfolio annualized return (as percentage)
          • benchmark_return: float - Benchmark annualized return (as percentage)
          • portfolio_volatility: float - Portfolio volatility (as percentage)
          • benchmark_volatility: float - Benchmark volatility (as percentage)
          • portfolio_sharpe: float - Portfolio Sharpe ratio
          • benchmark_sharpe: float - Benchmark Sharpe ratio
        
        **Time Series & Statistics:**
        - monthly_returns: Dict[date_str, return] - Monthly return time series (ISO date keys)
                - monthly_stats: Dict with monthly return statistics
          • average_monthly_return: float - Average monthly return (as percentage)
          • average_win: float - Average positive month return (as percentage)
          • average_loss: float - Average negative month return (as percentage)
          • win_loss_ratio: float - Ratio of average win to average loss
        - risk_free_rate: float - Risk-free rate used in calculations (as percentage)
        
        **Human-Readable Output:**
        - formatted_report: str - Complete CLI-style performance report (primary Claude/AI input)
        
        **Optional Data:**
        - allocations: Dict[ticker, weight] (Optional) - Portfolio allocations if available
        
        DATA QUALITY NOTES:
        - All timestamps are UTC and serialized via ISO-8601
        - Time series data maintains chronological order
        - Risk metrics use annualized conventions for consistency
        - Benchmark comparison requires valid benchmark data
        
        SCHEMA COMPLIANCE:
        Output structure matches PerformanceResultSchema for OpenAPI documentation.
        All fields map directly to schema definitions with proper type validation.
        
        EXAMPLE STRUCTURED DATA:
        {
          "returns": {
            "total_return": 14.5,
            "annualized_return": 8.2,
            "best_month": 12.3,
            "worst_month": -8.7,
            "positive_months": 8,
            "negative_months": 4,
            "win_rate": 66.7
          },
          "risk_metrics": {
            "volatility": 18.5,
            "maximum_drawdown": -8.9,
            "downside_deviation": 12.4,
            "tracking_error": 4.2
          },
          "risk_adjusted_returns": {
            "sharpe_ratio": 1.23,
            "sortino_ratio": 1.67,
            "information_ratio": 0.85,
            "calmar_ratio": 0.92
          },
          "benchmark_analysis": {
            "benchmark_ticker": "SPY",
            "alpha_annual": 2.1,
            "beta": 1.02,
            "r_squared": 0.89,
            "excess_return": 1.8
          }
        }
        
        Returns:
            Dict[str, Any]: Complete performance analysis with time series and benchmark comparison
        """
        return {
            "analysis_period": self.analysis_period, # Time period configuration and metrics
            "returns": self.returns, # Performance metrics (total_return, annualized_return, best_month, worst_month, positive_months, negative_months, win_rate)
            "risk_metrics": self.risk_metrics, # Risk metrics (volatility, maximum_drawdown, downside_deviation, tracking_error)
            "risk_adjusted_returns": self.risk_adjusted_returns, # Risk-adjusted returns (sharpe_ratio, sortino_ratio, information_ratio, calmar_ratio)
            "benchmark_analysis": self.benchmark_analysis, # Benchmark analysis (benchmark_ticker, alpha_annual, beta, r_squared, excess_return)
            "benchmark_comparison": self.benchmark_comparison, # Benchmark comparison (portfolio_return, benchmark_return, portfolio_volatility, benchmark_volatility, portfolio_sharpe, benchmark_sharpe)
            "monthly_stats": self.monthly_stats, # Monthly statistics (average_monthly_return, average_win, average_loss, win_loss_ratio)   
            "risk_free_rate": self.risk_free_rate, # Risk-free rate (as percentage)
            "monthly_returns": self.monthly_returns, # Monthly returns (date, return)
            "analysis_date": self.analysis_date.isoformat(), # Analysis date (ISO-8601 UTC)
            "portfolio_name": self.portfolio_name, # Portfolio name
            "formatted_report": self.to_cli_report(), # Human-readable CLI report (identical to current output)
            "analysis_period_text": self._format_analysis_period(), # Human-readable analysis period (e.g. "2019-01-31 to 2025-06-27")
            "position_count": self.get_position_count(), # Number of positions in portfolio
            "performance_category": self._categorize_performance(), # Performance category (excellent, good, fair, poor)
            "key_insights": self._generate_key_insights(), # Key insights (benchmark comparison, market sensitivity, risk-adjusted returns, win rate)
            "display_formatting": self._get_display_formatting_metadata(), # Display formatting metadata    
            "enhanced_key_insights": self._generate_enhanced_key_insights(), # Enhanced key insights
            "allocations": _convert_to_json_serializable(self._allocations) if self._allocations else None, # Portfolio allocation data for position analysis
            # Data quality information
            "excluded_tickers": self.excluded_tickers, # Tickers excluded due to insufficient data
            "warnings": self.warnings, # Data quality warnings
            "analysis_notes": self.analysis_notes, # Analysis notes about data quality
            # Dividend metrics (optional)
            "dividend_metrics": self.dividend_metrics,
        }


    def _get_display_formatting_metadata(self) -> Dict[str, Any]:
        """Generate display formatting metadata for UI rendering hints."""
        # Get clean category and map to display components
        category = self._categorize_performance()
        
        # Map category to emoji and description
        display_map = {
            "excellent": {"emoji": "🟢", "description": "Outstanding risk-adjusted performance"},
            "good": {"emoji": "🟡", "description": "Solid performance with reasonable risk"},
            "fair": {"emoji": "🟠", "description": "Moderate performance with some risk concerns"},
            "poor": {"emoji": "🔴", "description": "Underperforming with high risk"}
        }
        
        display_info = display_map.get(category, {"emoji": "⚪", "description": "Unknown performance level"})
        
        return {
            "performance_category_emoji": display_info["emoji"],
            "performance_category_description": display_info["description"],
            "performance_category_formatted": f"{display_info['emoji']} {category.upper()}: {display_info['description']}",
            "section_headers": [
                "📈 RETURN METRICS",
                "⚡ RISK METRICS", 
                "🎯 RISK-ADJUSTED RETURNS",
                "🔍 BENCHMARK ANALYSIS",
                "📅 MONTHLY STATISTICS"
            ],
            "table_structure": {
                "comparison_table": {
                    "columns": ["Metric", "Portfolio", "Benchmark"],
                    "rows": ["Return", "Volatility", "Sharpe Ratio"]
                }
            }
        }
    
    def to_cli_report(self) -> str:
        """Generate complete CLI formatted report - IDENTICAL to current output"""
        sections = []
        sections.append(self._format_performance_header())
        sections.append(self._format_performance_metrics())
        return "\n".join(sections)
    
    def _format_performance_header(self) -> str:
        """Format portfolio info header - EXACT copy of run_risk.py:727-733"""
        # CRITICAL: Must produce identical output to current implementation
        lines = ["📊 Portfolio Performance Analysis"]
        lines.append("=" * 50)
        lines.append(f"📁 Portfolio file: {self.portfolio_file or '(in-memory)'}")
        lines.append(f"📅 Analysis period: {self.analysis_period['start_date']} to {self.analysis_period['end_date']}")
        # Get positions count from position_count method or analysis_period
        positions = self.get_position_count() or self.analysis_period.get('positions', 'N/A')
        lines.append(f"📊 Positions: {positions}")
        lines.append("")
        lines.append("🔄 Calculating performance metrics...")
        lines.append("✅ Performance calculation successful!")
        return "\n".join(lines)
    
    def _format_performance_metrics(self) -> str:
        """Format performance metrics - delegates to display_portfolio_performance_metrics"""
        # CRITICAL: Must use existing display function to preserve exact formatting
        from run_portfolio_risk import display_portfolio_performance_metrics
        import io
        import sys
        
        original_stdout = sys.stdout
        sys.stdout = captured = io.StringIO()
        try:
            # Build performance_metrics dict compatible with existing function
            # Use analysis_period directly since total_months is already calculated in from_core_analysis()
            
            performance_metrics = {
                "returns": self.returns,
                "risk_metrics": self.risk_metrics,
                "risk_adjusted_returns": self.risk_adjusted_returns,
                "benchmark_analysis": self.benchmark_analysis,
                "benchmark_comparison": self.benchmark_comparison,
                "monthly_stats": self.monthly_stats,
                "monthly_returns": self.monthly_returns,
                "risk_free_rate": self.risk_free_rate,
                "analysis_period": self.analysis_period,
                "dividend_metrics": self.dividend_metrics
            }
            display_portfolio_performance_metrics(performance_metrics)
            return captured.getvalue()
        finally:
            sys.stdout = original_stdout

    def _generate_enhanced_key_insights(self) -> List[str]:
        """Generate enhanced key insights with detailed bullet points."""
        insights = []
        
        # Benchmark comparison insight
        if hasattr(self, 'benchmark_analysis') and self.benchmark_analysis:
            excess_return = self.benchmark_analysis.get('excess_return', 0)
            if excess_return is not None and excess_return > 0:
                insights.append(f"• Outperforming benchmark (+{excess_return:.1f}% vs benchmark)")
            elif excess_return is not None:
                insights.append(f"• Underperforming benchmark ({excess_return:+.1f}% vs benchmark)")
        
        # Market sensitivity insight
        if hasattr(self, 'benchmark_analysis') and 'beta' in self.benchmark_analysis:
            beta = self.benchmark_analysis['beta']
            if beta is not None and beta > 1.1:
                insights.append(f"• High market sensitivity (β = {beta:.2f})")
            elif beta is not None and beta < 0.9:
                insights.append(f"• Low market sensitivity (β = {beta:.2f})")
            elif beta is not None:
                insights.append(f"• Moderate market sensitivity (β = {beta:.2f})")
        
        # Risk-adjusted returns insight
        if hasattr(self, 'risk_adjusted_returns') and 'sharpe_ratio' in self.risk_adjusted_returns:
            sharpe = self.risk_adjusted_returns['sharpe_ratio']
            if sharpe is not None and sharpe > 1.5:
                insights.append(f"• Excellent risk-adjusted returns (Sharpe = {sharpe:.2f})")
            elif sharpe is not None and sharpe > 1.0:
                insights.append(f"• Good risk-adjusted returns (Sharpe = {sharpe:.2f})")
            elif sharpe is not None:
                insights.append(f"• Below-average risk-adjusted returns (Sharpe = {sharpe:.2f})")
        
        # Win rate insight
        if hasattr(self, 'returns') and 'win_rate' in self.returns:
            win_rate = self.returns['win_rate']
            if win_rate is not None and win_rate > 60:
                insights.append(f"• High consistency ({win_rate:.0f}% win rate)")
            elif win_rate is not None and win_rate > 50:
                insights.append(f"• Moderate consistency ({win_rate:.0f}% win rate)")
            elif win_rate is not None:
                insights.append(f"• Low consistency ({win_rate:.0f}% win rate)")
        
        return insights
    
    def to_formatted_report(self) -> str:
        """Format performance results for display (identical to to_cli_report())."""
        return self.to_cli_report()
    
    
    def __hash__(self) -> int:
        """Make PerformanceResult hashable for caching."""
        key_data = (
            self.returns.get("total_return", 0),
            self.returns.get("annualized_return", 0),
            self.risk_metrics.get("volatility", 0),
            self.risk_adjusted_returns.get("sharpe_ratio", 0),
            self.analysis_period.get("years", 0)
        )
        return hash(key_data)


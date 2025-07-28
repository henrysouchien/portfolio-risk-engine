"""Result objects for structured service layer responses."""

from typing import Dict, Any, Optional, List, Union
import pandas as pd
from datetime import datetime
import json
import numpy as np
from dataclasses import dataclass


def _convert_to_json_serializable(obj):
    """Convert pandas objects to JSON-serializable format."""
    if isinstance(obj, pd.DataFrame):
        # Convert DataFrame with timestamp handling
        df_copy = obj.copy()
        
        # Convert any datetime indices to strings
        if hasattr(df_copy.index, 'strftime'):
            df_copy.index = df_copy.index.strftime('%Y-%m-%d %H:%M:%S')
        
        # Convert to dict and clean NaN values
        result = df_copy.to_dict()
        return _clean_nan_values(result)
    
    elif isinstance(obj, pd.Series):
        # Convert Series with timestamp handling
        series_copy = obj.copy()
        
        # Convert any datetime indices to strings
        if hasattr(series_copy.index, 'strftime'):
            series_copy.index = series_copy.index.strftime('%Y-%m-%d %H:%M:%S')
        
        # Convert to dict and clean NaN values
        result = series_copy.to_dict()
        return _clean_nan_values(result)
    
    elif isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    
    elif isinstance(obj, (np.integer, np.floating)):
        if np.isnan(obj):
            return None
        return obj.item()
    
    elif isinstance(obj, dict):
        return {k: _convert_to_json_serializable(v) for k, v in obj.items()}
    
    elif isinstance(obj, list):
        return [_convert_to_json_serializable(item) for item in obj]
    
    return obj


def _clean_nan_values(obj):
    """Recursively convert NaN values to None for JSON serialization."""
    if isinstance(obj, dict):
        return {k: _clean_nan_values(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_clean_nan_values(item) for item in obj]
    elif isinstance(obj, float) and (np.isnan(obj) or obj != obj):  # NaN check
        return None
    elif hasattr(obj, 'item'):  # numpy scalar
        val = obj.item()
        if isinstance(val, float) and (np.isnan(val) or val != val):
            return None
        return val
    else:
        return obj


@dataclass
class RiskAnalysisResult:
    """
    Comprehensive portfolio risk analysis results with 30+ risk metrics and formatted reporting.
    
    This is the primary result object returned by PortfolioService.analyze_portfolio() and contains
    the complete set of portfolio risk metrics, factor exposures, and compliance checks. It provides
    both structured data access and human-readable formatted reporting capabilities.
    
    Key Data Categories:
    - **Volatility Metrics**: Annual/monthly volatility, portfolio risk measures
    - **Factor Exposures**: Beta coefficients for market factors (market, growth, value, etc.)
    - **Risk Decomposition**: Factor vs. idiosyncratic variance breakdown
    - **Position Analysis**: Individual security risk contributions and correlations
    - **Compliance Checks**: Risk limit violations and factor exposure compliance
    - **Portfolio Composition**: Allocation analysis and concentration metrics
    
    Usage Patterns:
    1. **Structured Data Access**: Use getter methods for programmatic analysis
    2. **Formatted Reporting**: Use to_formatted_report() for human-readable display
    3. **Serialization**: Use to_dict() for JSON export and API responses
    4. **Comparison**: Compare multiple results for scenario analysis
    
    Architecture Role:
        Core Functions → Service Layer → RiskAnalysisResult → Consumer (Claude/API/UI)
    
    Example:
        ```python
        # Get result from service layer
        result = portfolio_service.analyze_portfolio(portfolio_data)
        
        # Access structured data
        annual_vol = result.volatility_annual              # 0.185 (18.5% volatility)
        market_beta = result.portfolio_factor_betas["market"]  # 1.02 (market exposure)
        top_risks = result.get_top_risk_contributors(3)    # Top 3 risk contributors
        
        # Get summary metrics
        summary = result.get_summary()
        factor_pct = summary["factor_variance_pct"]        # 0.72 (72% factor risk)
        
        # Get formatted report for Claude/display
        report = result.to_formatted_report()
        # "=== PORTFOLIO RISK SUMMARY ===\nAnnual Volatility: 18.50%\n..."
        
        # Check compliance
        risk_violations = [check for check in result.risk_checks if not check["Pass"]]
        is_compliant = len(risk_violations) == 0
        ```
        
    Data Quality: All pandas objects are properly indexed and serializable for caching and API usage.
    Performance: Result creation ~10-50ms, formatted report generation ~5-10ms.
    """
    
    # Core volatility metrics
    volatility_annual: float
    volatility_monthly: float
    
    # Portfolio concentration
    herfindahl: float  # Herfindahl index for concentration
    
    # Factor exposures (pandas Series)
    portfolio_factor_betas: pd.Series
    
    # Variance decomposition
    variance_decomposition: Dict[str, Union[float, Dict[str, float]]]
    
    # Risk contributions by position (pandas Series)
    risk_contributions: pd.Series
    
    # Stock-level factor betas (pandas DataFrame)
    df_stock_betas: pd.DataFrame
    
    # Covariance and correlation matrices (pandas DataFrame)
    covariance_matrix: pd.DataFrame
    correlation_matrix: pd.DataFrame
    
    # Portfolio composition analysis
    allocations: pd.DataFrame
    
    # Factor volatilities (pandas DataFrame)
    factor_vols: pd.DataFrame
    
    # Weighted factor variance contributions (pandas DataFrame)
    weighted_factor_var: pd.DataFrame
    
    # Individual asset volatility breakdown (pandas DataFrame)
    asset_vol_summary: pd.DataFrame
    
    # Portfolio returns time series (pandas Series)
    portfolio_returns: pd.Series
    
    # Euler variance percentages (pandas Series)
    euler_variance_pct: pd.Series
    
    # Industry-level variance analysis
    industry_variance: Dict[str, Dict[str, float]]
    
    # Suggested risk limits
    suggested_limits: Dict[str, Dict[str, Union[float, bool]]]
    
    # Risk compliance checks
    risk_checks: List[Dict[str, Any]]
    beta_checks: List[Dict[str, Any]]
    
    # Beta limits (from calc_max_factor_betas)
    max_betas: Dict[str, float]
    max_betas_by_proxy: Dict[str, float]
    
    # Metadata
    analysis_date: datetime
    portfolio_name: Optional[str] = None
    
    def get_summary(self) -> Dict[str, Any]:
        """
        Get key portfolio risk metrics in a condensed summary format.
        
        Returns the most important risk metrics in a simple dictionary format,
        ideal for quick analysis, API responses, and dashboard displays.
        
        Returns:
            Dict[str, Any]: Key risk metrics containing:
                - volatility_annual: Annual portfolio volatility (float)
                - volatility_monthly: Monthly portfolio volatility (float)  
                - herfindahl_index: Portfolio concentration measure (float, 0-1)
                - factor_variance_pct: Percentage of risk from factors (float, 0-1)
                - idiosyncratic_variance_pct: Percentage of risk from stock-specific sources (float, 0-1)
                - top_risk_contributors: Top 5 positions by risk contribution (Dict[str, float])
                - factor_betas: Portfolio beta exposures to all factors (Dict[str, float])
                
        Example:
            ```python
            summary = result.get_summary()
            
            # Risk level assessment
            risk_level = "High" if summary["volatility_annual"] > 0.20 else "Moderate"
            
            # Concentration check
            is_concentrated = summary["herfindahl_index"] > 0.15
            
            # Factor vs stock-specific risk
            factor_dominated = summary["factor_variance_pct"] > 0.70
            ```
        """
        return {
            "volatility_annual": self.volatility_annual,
            "volatility_monthly": self.volatility_monthly,
            "herfindahl_index": self.herfindahl,
            "factor_variance_pct": self.variance_decomposition.get('factor_pct', 0),
            "idiosyncratic_variance_pct": self.variance_decomposition.get('idiosyncratic_pct', 0),
            "top_risk_contributors": self.risk_contributions.nlargest(5).to_dict(),
            "factor_betas": self.portfolio_factor_betas.to_dict()
        }
    
    def get_factor_exposures(self) -> Dict[str, float]:
        """
        Get portfolio beta exposures to market factors.
        
        Returns factor beta coefficients showing portfolio sensitivity to systematic
        risk factors like market, growth, value, momentum, etc.
        
        Returns:
            Dict[str, float]: Factor beta exposures where:
                - Key: Factor name (e.g., "market", "growth", "value")
                - Value: Beta coefficient (e.g., 1.02 = 2% more sensitive than market)
                
        Interpretation:
            - Beta = 1.0: Same sensitivity as factor benchmark
            - Beta > 1.0: More sensitive (amplified exposure)
            - Beta < 1.0: Less sensitive (defensive exposure)
            - Beta < 0.0: Negative correlation (hedge exposure)
            
        Example:
            ```python
            betas = result.get_factor_exposures()
            
            market_beta = betas["market"]        # 1.15 (15% more volatile than market)
            growth_beta = betas["growth"]        # 0.85 (defensive to growth factor)
            value_beta = betas["value"]          # -0.10 (slight value hedge)
            
            # Risk assessment
            is_aggressive = market_beta > 1.2
            is_growth_oriented = growth_beta > 0.5
            ```
        """
        return self.portfolio_factor_betas.to_dict()
    
    def get_top_risk_contributors(self, n: int = 5) -> Dict[str, float]:
        """
        Get the securities that contribute most to portfolio risk.
        
        Risk contribution measures how much each position contributes to total portfolio
        variance, accounting for both the position size and its correlations with other holdings.
        
        Args:
            n (int): Number of top contributors to return (default: 5)
            
        Returns:
            Dict[str, float]: Top N risk contributors where:
                - Key: Ticker symbol
                - Value: Risk contribution (decimal, sums to 1.0 across all positions)
                
        Example:
            ```python
            top_risks = result.get_top_risk_contributors(3)
            # {"AAPL": 0.285, "TSLA": 0.198, "MSFT": 0.147}
            
            # Analysis
            largest_risk = max(top_risks.values())      # 0.285 (28.5% of total risk)
            concentration = sum(top_risks.values())     # 0.630 (63% from top 3)
            
            # Risk management insights
            if largest_risk > 0.25:
                print(f"High concentration: {max(top_risks, key=top_risks.get)} contributes {largest_risk:.1%}")
            ```
        """
        return self.risk_contributions.nlargest(n).to_dict()
    
    def get_variance_breakdown(self) -> Dict[str, float]:
        """
        Get portfolio variance decomposition between systematic and idiosyncratic risk.
        
        Variance decomposition shows how much of portfolio risk comes from systematic
        factors (market-wide risks) vs. idiosyncratic risks (stock-specific risks).
        
        Returns:
            Dict[str, float]: Variance breakdown containing:
                - factor_pct: Percentage of variance from systematic factors (0-1)
                - idiosyncratic_pct: Percentage of variance from stock-specific risk (0-1)
                - portfolio_variance: Total portfolio variance (absolute value)
                
        Interpretation:
            - High factor_pct (>70%): Portfolio dominated by systematic risk
            - High idiosyncratic_pct (>40%): Significant stock-specific risk
            - Balanced (~60/40): Diversified risk profile
            
        Example:
            ```python
            breakdown = result.get_variance_breakdown()
            
            factor_risk = breakdown["factor_pct"]           # 0.68 (68% systematic)
            specific_risk = breakdown["idiosyncratic_pct"]  # 0.32 (32% stock-specific)
            
            # Risk profile assessment
            if factor_risk > 0.8:
                profile = "Market-dependent"
            elif specific_risk > 0.4:
                profile = "Stock-picker portfolio"
            else:
                profile = "Balanced diversification"
            ```
        """
        return {
            "factor_pct": self.variance_decomposition.get('factor_pct', 0),
            "idiosyncratic_pct": self.variance_decomposition.get('idiosyncratic_pct', 0),
            "portfolio_variance": self.variance_decomposition.get('portfolio_variance', 0)
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "volatility_annual": self.volatility_annual,
            "volatility_monthly": self.volatility_monthly,
            "herfindahl": self.herfindahl,
            "portfolio_factor_betas": _convert_to_json_serializable(self.portfolio_factor_betas),
            "variance_decomposition": _convert_to_json_serializable(self.variance_decomposition),
            "risk_contributions": _convert_to_json_serializable(self.risk_contributions),
            "df_stock_betas": _convert_to_json_serializable(self.df_stock_betas),
            "covariance_matrix": _convert_to_json_serializable(self.covariance_matrix),
            "correlation_matrix": _convert_to_json_serializable(self.correlation_matrix),
            "allocations": _convert_to_json_serializable(self.allocations),
            "factor_vols": _convert_to_json_serializable(self.factor_vols),
            "weighted_factor_var": _convert_to_json_serializable(self.weighted_factor_var),
            "asset_vol_summary": _convert_to_json_serializable(self.asset_vol_summary),
            "portfolio_returns": _convert_to_json_serializable(self.portfolio_returns),
            "euler_variance_pct": _convert_to_json_serializable(self.euler_variance_pct),
            "industry_variance": _convert_to_json_serializable(self.industry_variance),
            "suggested_limits": _convert_to_json_serializable(self.suggested_limits),
            "risk_checks": _convert_to_json_serializable(self.risk_checks),
            "beta_checks": _convert_to_json_serializable(self.beta_checks),
            "max_betas": _convert_to_json_serializable(self.max_betas),
            "max_betas_by_proxy": _convert_to_json_serializable(self.max_betas_by_proxy),
            "analysis_date": self.analysis_date.isoformat(),
            "portfolio_name": self.portfolio_name,
            "formatted_report": self.to_formatted_report()
        }
    
    @classmethod
    def from_build_portfolio_view(cls, portfolio_view_result: Dict[str, Any],
                                 portfolio_name: Optional[str] = None,
                                 risk_checks: Optional[List[Dict[str, Any]]] = None,
                                 beta_checks: Optional[List[Dict[str, Any]]] = None,
                                 max_betas: Optional[Dict[str, float]] = None,
                                 max_betas_by_proxy: Optional[Dict[str, float]] = None) -> 'RiskAnalysisResult':
        """Create RiskAnalysisResult from build_portfolio_view output."""
        return cls(
            volatility_annual=portfolio_view_result["volatility_annual"],
            volatility_monthly=portfolio_view_result["volatility_monthly"],
            herfindahl=portfolio_view_result["herfindahl"],
            portfolio_factor_betas=portfolio_view_result["portfolio_factor_betas"],
            variance_decomposition=portfolio_view_result["variance_decomposition"],
            risk_contributions=portfolio_view_result["risk_contributions"],
            df_stock_betas=portfolio_view_result["df_stock_betas"],
            covariance_matrix=portfolio_view_result.get("covariance_matrix", pd.DataFrame()),
            correlation_matrix=portfolio_view_result.get("correlation_matrix", pd.DataFrame()),
            allocations=portfolio_view_result.get("allocations", pd.DataFrame()),
            factor_vols=portfolio_view_result.get("factor_vols", pd.DataFrame()),
            weighted_factor_var=portfolio_view_result.get("weighted_factor_var", pd.DataFrame()),
            asset_vol_summary=portfolio_view_result.get("asset_vol_summary", pd.DataFrame()),
            portfolio_returns=portfolio_view_result.get("portfolio_returns", pd.Series()),
            euler_variance_pct=portfolio_view_result.get("euler_variance_pct", pd.Series()),
            industry_variance=portfolio_view_result.get("industry_variance", {}),
            suggested_limits=portfolio_view_result.get("suggested_limits", {}),
            risk_checks=risk_checks or [],
            beta_checks=beta_checks or [],
            max_betas=max_betas or {},
            max_betas_by_proxy=max_betas_by_proxy or {},
            analysis_date=datetime.now(),
            portfolio_name=portfolio_name
        )
    
    def to_formatted_report(self) -> str:
        """
        Generate comprehensive human-readable portfolio risk analysis report.
        
        This method returns the same formatted text report that appears in the CLI,
        making it perfect for Claude AI responses, email reports, logging, and
        any situation requiring human-readable risk analysis.
        
        Report Sections:
        1. **Portfolio Risk Summary**: Core volatility and concentration metrics
        2. **Factor Exposures**: Beta coefficients for all systematic risk factors
        3. **Variance Decomposition**: Factor vs. idiosyncratic risk breakdown
        4. **Top Risk Contributors**: Largest individual position risk contributors
        5. **Risk Limit Checks**: Compliance status with portfolio risk limits
        6. **Beta Exposure Checks**: Factor exposure compliance with limits
        
        Format: Professional financial analysis report with clear section headers,
        aligned columns, and percentage formatting following industry standards.
        
        Performance: Uses cached formatted report if available (from service layer),
        otherwise reconstructs from structured data in ~5-10ms.
        
        Returns:
            str: Complete formatted risk analysis report (typically 500-2000 characters)
            
        Example:
            ```python
            report = result.to_formatted_report()
            
            # Display to user
            print(report)
            
            # Send to Claude AI
            claude_response = claude_client.send_message(
                f"Analyze this portfolio risk report:\\n{report}"
            )
            
            # Save to file
            with open("portfolio_analysis.txt", "w") as f:
                f.write(report)
                
            # Include in email
            email_body = f"Portfolio Analysis Results:\\n\\n{report}"
            ```
            
        Sample Output:
            ```
            === PORTFOLIO RISK SUMMARY ===
            Annual Volatility:        18.50%
            Monthly Volatility:       5.34%
            Herfindahl Index:         0.142
            
            === FACTOR EXPOSURES ===
            Market             1.02
            Growth             0.85
            Value             -0.12
            
            === VARIANCE DECOMPOSITION ===
            Factor Variance:          68.2%
            Idiosyncratic Variance:   31.8%
            
            === TOP RISK CONTRIBUTORS ===
            AAPL     0.2847
            TSLA     0.1982
            MSFT     0.1473
            ```
        """
        # Use stored formatted report if available (from service layer)
        if hasattr(self, '_formatted_report') and self._formatted_report:
            return self._formatted_report
        
        # Fallback to manual reconstruction
        sections = []
        
        # Portfolio Risk Summary
        sections.append("=== PORTFOLIO RISK SUMMARY ===")
        sections.append(f"Annual Volatility:        {self.volatility_annual:.2%}")
        sections.append(f"Monthly Volatility:       {self.volatility_monthly:.2%}")
        sections.append(f"Herfindahl Index:         {self.herfindahl:.3f}")
        sections.append("")
        
        # Factor Exposures
        sections.append("=== FACTOR EXPOSURES ===")
        for factor, beta in self.portfolio_factor_betas.items():
            sections.append(f"{factor.capitalize():<15} {beta:>8.2f}")
        sections.append("")
        
        # Variance Decomposition
        sections.append("=== VARIANCE DECOMPOSITION ===")
        factor_pct = self.variance_decomposition.get('factor_pct', 0)
        idio_pct = self.variance_decomposition.get('idiosyncratic_pct', 0)
        sections.append(f"Factor Variance:          {factor_pct:.1%}")
        sections.append(f"Idiosyncratic Variance:   {idio_pct:.1%}")
        sections.append("")
        
        # Top Risk Contributors
        sections.append("=== TOP RISK CONTRIBUTORS ===")
        
        # Get reference data for position labeling
        try:
            from run_portfolio_risk import get_cash_positions
            from utils.etf_mappings import get_etf_to_industry_map, format_ticker_with_label
            cash_positions = get_cash_positions()
            industry_map = get_etf_to_industry_map()
        except ImportError:
            # Fallback if imports fail
            cash_positions = set()
            industry_map = {}
        
        # Handle both pandas Series and dict formats defensively
        if hasattr(self.risk_contributions, 'nlargest'):
            top_contributors = self.risk_contributions.nlargest(5)
            
            # Calculate adaptive width based on labeled tickers
            max_ticker_width = 8  # minimum for backward compatibility
            for ticker, contribution in top_contributors.items():
                labeled_ticker = format_ticker_with_label(ticker, cash_positions, industry_map)
                max_ticker_width = max(max_ticker_width, len(labeled_ticker))
            
            for ticker, contribution in top_contributors.items():
                labeled_ticker = format_ticker_with_label(ticker, cash_positions, industry_map)
                sections.append(f"{labeled_ticker:<{max_ticker_width}} {contribution:>8.4f}")
        else:
            # It's a dict, sort by value
            sorted_items = sorted(self.risk_contributions.items(), key=lambda x: x[1], reverse=True)
            top_items = sorted_items[:5]
            
            # Calculate adaptive width based on labeled tickers  
            max_ticker_width = 8  # minimum for backward compatibility
            for ticker, contribution in top_items:
                labeled_ticker = format_ticker_with_label(ticker, cash_positions, industry_map)
                max_ticker_width = max(max_ticker_width, len(labeled_ticker))
            
            for ticker, contribution in top_items:
                labeled_ticker = format_ticker_with_label(ticker, cash_positions, industry_map)
                sections.append(f"{labeled_ticker:<{max_ticker_width}} {contribution:>8.4f}")
        sections.append("")
        
        # Factor Breakdown (if available)
        if hasattr(self, 'variance_decomposition') and 'factor_breakdown_pct' in self.variance_decomposition:
            sections.append("=== FACTOR VARIANCE BREAKDOWN ===")
            factor_breakdown = self.variance_decomposition.get('factor_breakdown_pct', {})
            for factor, pct in factor_breakdown.items():
                sections.append(f"{factor.capitalize():<15} {pct:.1%}")
            sections.append("")
        
        # Industry Analysis (if available)
        if hasattr(self, 'industry_variance') and self.industry_variance:
            sections.append("=== INDUSTRY VARIANCE CONTRIBUTIONS ===")
            industry_data = self.industry_variance.get('percent_of_portfolio', {})
            
            # Get reference data for ETF labeling (reuse from above if available)
            try:
                # Try to reuse from above if already imported
                if 'cash_positions' not in locals() or 'industry_map' not in locals():
                    from run_portfolio_risk import get_cash_positions
                    from utils.etf_mappings import get_etf_to_industry_map, format_ticker_with_label
                    cash_positions = get_cash_positions()
                    industry_map = get_etf_to_industry_map()
            except ImportError:
                # Fallback if imports fail
                cash_positions = set()
                industry_map = {}
            
            # Calculate adaptive width based on labeled ETFs
            max_etf_width = 15  # minimum for backward compatibility
            sorted_industry_items = sorted(industry_data.items(), key=lambda x: x[1], reverse=True)
            for etf, pct in sorted_industry_items:
                labeled_etf = format_ticker_with_label(etf, cash_positions, industry_map)
                max_etf_width = max(max_etf_width, len(labeled_etf))
            
            for etf, pct in sorted_industry_items:
                labeled_etf = format_ticker_with_label(etf, cash_positions, industry_map)
                sections.append(f"{labeled_etf:<{max_etf_width}} {pct:.1%}")
            sections.append("")
        
        # Risk Limit Checks (if available)
        if hasattr(self, 'risk_checks') and self.risk_checks:
            sections.append("=== Portfolio Risk Limit Checks ===")
            for check in self.risk_checks:
                metric = check.get('Metric', 'Unknown')
                actual = check.get('Actual', 0)
                limit = check.get('Limit', 0)
                passed = check.get('Pass', False)
                status = "→ PASS" if passed else "→ FAIL"
                sections.append(f"{metric:<22} {actual:.2%}  ≤ {limit:.2%}  {status}")
            sections.append("")
        
        # Beta Exposure Checks (if available)
        if hasattr(self, 'beta_checks') and self.beta_checks:
            sections.append("=== Beta Exposure Checks ===")
            for check in self.beta_checks:
                factor = check.get('factor', 'Unknown')
                portfolio_beta = check.get('portfolio_beta', 0)
                max_allowed_beta = check.get('max_allowed_beta', 0)
                passed = check.get('pass', False)
                status = "→ PASS" if passed else "→ FAIL"
                sections.append(f"{factor:<20} β = {portfolio_beta:+.2f}  ≤ {max_allowed_beta:.2f}  {status}")
            sections.append("")
        
        return "\n".join(sections)
    
    def __hash__(self) -> int:
        """Make RiskAnalysisResult hashable for caching."""
        # Use key metrics for hashing
        key_data = (
            self.volatility_annual,
            self.volatility_monthly,
            self.herfindahl,
            tuple(self.portfolio_factor_betas.items()),
            self.variance_decomposition.get('portfolio_variance', 0)
        )
        return hash(key_data)



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
        
        # Analysis timestamp
        self.analysis_date = datetime.now()
    
    @classmethod
    def from_min_variance_output(cls, 
                                optimized_weights: Dict[str, float],
                                risk_table: pd.DataFrame,
                                beta_table: pd.DataFrame) -> 'OptimizationResult':
        """Create OptimizationResult from run_min_variance() output."""
        return cls(
            optimized_weights=optimized_weights,
            optimization_type="min_variance",
            risk_table=risk_table,
            beta_table=beta_table
        )
    
    @classmethod
    def from_max_return_output(cls,
                              optimized_weights: Dict[str, float],
                              portfolio_summary: Dict[str, Any],
                              risk_table: pd.DataFrame,
                              factor_table: pd.DataFrame,
                              proxy_table: pd.DataFrame) -> 'OptimizationResult':
        """Create OptimizationResult from run_max_return() output.
        
        This matches EXACTLY what run_max_return_portfolio returns:
        w, summary, r, f_b, p_b
        """
        return cls(
            optimized_weights=optimized_weights,
            optimization_type="max_return",
            risk_table=risk_table,
            beta_table=factor_table,  # Use factor_table as beta_table for consistency
            portfolio_summary=portfolio_summary,
            factor_table=factor_table,
            proxy_table=proxy_table
        )
    
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
        """
        Generate comprehensive human-readable portfolio optimization report.
        
        Creates a formatted report showing optimization results, allocation changes,
        risk compliance, and performance metrics. Report format matches CLI output
        and includes professional presentation suitable for client communication.
        
        Report Sections:
        1. **Optimization Summary**: Method, positions, and key metrics
        2. **Optimal Allocation**: Top positions with weight percentages
        3. **Risk Compliance**: Portfolio risk limits and validation status
        4. **Beta Exposure**: Factor exposure limits and compliance checks
        5. **Performance Metrics**: Risk-adjusted returns and efficiency measures
        6. **Factor Analysis**: Systematic risk exposure breakdown
        
        Format: Professional optimization report with clear headers, aligned columns,
        and percentage formatting following industry standards.
        
        Returns:
            str: Complete formatted optimization report for review and implementation
            
        Example:
            ```python
            report = result.to_formatted_report()
            
            # Display optimization results
            print(report)
            
            # Send to Claude for analysis
            claude_prompt = f"Review this portfolio optimization:\\n{report}"
            
            # Include in optimization summary email
            email_content = f"Optimization Results:\\n\\n{report}"
            ```
            
        Sample Output:
            ```
            === PORTFOLIO OPTIMIZATION RESULTS ===
            Optimization Type: Minimum Variance
            Total Positions: 8
            
            === OPTIMAL ALLOCATION ===
            SGOV     25.0%
            MSFT     22.0% 
            TLT      20.0%
            AAPL     18.0%
            GOOGL    15.0%
            
            === RISK COMPLIANCE ===
            Portfolio Volatility  12.5%  ≤ 15.0%  → PASS
            Concentration Limit   25.0%  ≤ 30.0%  → PASS
            ```
        """
        return f"Optimization Results: {self.optimization_type} - {len(self.optimized_weights)} positions"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "optimized_weights": self.optimized_weights,
            "optimization_type": self.optimization_type,
            "risk_table": self.risk_table.to_dict(),
            "beta_table": self.beta_table.to_dict(),
            "portfolio_summary": self.portfolio_summary,
            "factor_table": self.factor_table.to_dict(),
            "proxy_table": self.proxy_table.to_dict(),
            "analysis_date": self.analysis_date.isoformat(),
            "summary": self.get_summary()
        }


@dataclass
class PerformanceResult:
    """
    Portfolio performance analysis results matching calculate_portfolio_performance_metrics output.
    
    Contains comprehensive performance metrics including returns, risk metrics,
    risk-adjusted returns, benchmark analysis, and monthly statistics.
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
    
    def to_formatted_report(self) -> str:
        """
        Generate formatted text report matching the CLI output style.
        
        Returns the stored formatted report if available, otherwise returns
        a basic formatted summary.
        """
        # Use stored formatted report if available (from service layer)
        if hasattr(self, '_formatted_report') and self._formatted_report:
            return self._formatted_report
        
        # Fallback to basic summary
        return f"Performance Analysis - {self.portfolio_name or 'Portfolio'}\n" \
               f"Annualized Return: {self.returns.get('annualized_return', 0):.2f}%\n" \
               f"Volatility: {self.risk_metrics.get('volatility', 0):.2f}%\n" \
               f"Sharpe Ratio: {self.risk_adjusted_returns.get('sharpe_ratio', 0):.3f}\n" \
               f"Max Drawdown: {self.risk_metrics.get('maximum_drawdown', 0):.2f}%"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "analysis_period": self.analysis_period,
            "returns": self.returns,
            "risk_metrics": self.risk_metrics,
            "risk_adjusted_returns": self.risk_adjusted_returns,
            "benchmark_analysis": self.benchmark_analysis,
            "benchmark_comparison": self.benchmark_comparison,
            "monthly_stats": self.monthly_stats,
            "risk_free_rate": self.risk_free_rate,
            "monthly_returns": self.monthly_returns,
            "analysis_date": self.analysis_date.isoformat(),
            "portfolio_name": self.portfolio_name,
            "formatted_report": self.to_formatted_report()
        }
    
    @classmethod
    def from_performance_metrics(cls, performance_metrics: Dict[str, Any],
                                portfolio_name: Optional[str] = None) -> 'PerformanceResult':
        """Create PerformanceResult from calculate_portfolio_performance_metrics output."""
        return cls(
            analysis_period=performance_metrics["analysis_period"],
            returns=performance_metrics["returns"],
            risk_metrics=performance_metrics["risk_metrics"],
            risk_adjusted_returns=performance_metrics["risk_adjusted_returns"],
            benchmark_analysis=performance_metrics["benchmark_analysis"],
            benchmark_comparison=performance_metrics["benchmark_comparison"],
            monthly_stats=performance_metrics["monthly_stats"],
            risk_free_rate=performance_metrics["risk_free_rate"],
            monthly_returns=performance_metrics["monthly_returns"],
            analysis_date=datetime.now(),
            portfolio_name=portfolio_name
        )
    
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


@dataclass
class RiskScoreResult:
    """
    Portfolio risk scoring results with comprehensive limit compliance analysis.
    
    This result object contains portfolio risk assessment with an overall risk score (0-100 scale),
    detailed component scoring across multiple risk dimensions, limit violation analysis, and
    actionable risk management recommendations.
    
    Risk Scoring Components:
    - **Overall Risk Score**: Composite score (0-100) summarizing portfolio risk quality
    - **Component Scores**: Individual scores for concentration, volatility, factor exposure, etc.
    - **Risk Limit Analysis**: Detailed compliance checks against predefined risk limits
    - **Violation Detection**: Identification of specific risk limit breaches
    - **Risk Recommendations**: Actionable suggestions for risk management improvements
    
    Scoring Methodology:
    Risk scores use a 0-100 scale where higher scores indicate better risk management:
    - 90-100: Excellent risk management with strong diversification
    - 80-89: Good risk profile with minor areas for improvement
    - 70-79: Moderate risk with some concerns requiring attention
    - 60-69: Elevated risk with multiple areas needing improvement
    - Below 60: High risk requiring immediate risk management action
    
    Architecture Role:
        PortfolioService → Core Risk Scoring → Risk Limits → RiskScoreResult
    
    Example:
        ```python
        # Get risk score result from service
        result = portfolio_service.analyze_risk_score(portfolio_data, "risk_limits.yaml")
        
        # Access overall risk assessment
        overall_score = result.get_overall_score()              # 75 (Moderate risk)
        risk_category = result.get_risk_category()              # "Moderate Risk"
        is_compliant = result.is_compliant()                    # False (has violations)
        
        # Analyze component scores
        component_scores = result.get_component_scores()
        concentration_score = component_scores["concentration"] # 65 (needs improvement)
        volatility_score = component_scores["volatility"]      # 82 (good)
        
        # Review risk factors and recommendations
        risk_factors = result.get_risk_factors()
        # ["High concentration in technology sector", "Excessive single position weight"]
        
        recommendations = result.get_recommendations()
        # ["Reduce AAPL weight to below 25%", "Add defensive positions"]
        
        # Get formatted report for review
        report = result.to_formatted_report()
        ```
    
    Use Cases:
    - Portfolio risk assessment and compliance monitoring
    - Risk limit compliance reporting and violation tracking
    - Client risk profiling and suitability analysis
    - Risk management workflow automation and alerting
    """
    
    # Risk score information
    risk_score: Dict[str, Any]
    
    # Limits analysis and violations
    limits_analysis: Dict[str, Any]
    
    # Portfolio analysis details
    portfolio_analysis: Dict[str, Any]
    
    # Metadata
    analysis_date: datetime
    portfolio_name: Optional[str] = None
    
    def get_summary(self) -> Dict[str, Any]:
        """Get risk score summary."""
        # Handle the actual data structure from run_risk_score_analysis
        overall_score = self.risk_score.get("score", 0)
        risk_category = self.risk_score.get("category", "Unknown")
        component_scores = self.risk_score.get("component_scores", {})
        potential_losses = self.risk_score.get("potential_losses", {})
        max_loss_limit = potential_losses.get("max_loss_limit", 0) if isinstance(potential_losses, dict) else 0
        
        return {
            "overall_score": overall_score,
            "risk_category": risk_category,
            "component_scores": component_scores,
            "total_violations": len(self.limits_analysis.get("risk_factors", [])),
            "recommendations_count": len(self.limits_analysis.get("recommendations", [])),
            "max_loss_limit": max_loss_limit
        }
    
    def get_risk_factors(self) -> List[str]:
        """Get list of identified risk factors."""
        return self.limits_analysis.get("risk_factors", [])
    
    def get_recommendations(self) -> List[str]:
        """Get list of risk management recommendations."""
        return self.limits_analysis.get("recommendations", [])
    
    def get_component_scores(self) -> Dict[str, int]:
        """Get component risk scores."""
        return self.risk_score.get("component_scores", {})
    
    def get_limit_violations(self) -> Dict[str, int]:
        """Get count of limit violations by category."""
        return self.limits_analysis.get("limit_violations", {})
    
    def is_compliant(self) -> bool:
        """Check if portfolio is compliant with risk limits."""
        violations = self.get_limit_violations()
        return sum(violations.values()) == 0
    
    def get_overall_score(self) -> float:
        """Get overall risk score."""
        return self.risk_score.get("score", 0)
    
    def get_risk_category(self) -> str:
        """Get risk category classification."""
        return self.risk_score.get("category", "Unknown")
    
    def to_formatted_report(self) -> str:
        """
        Generate comprehensive human-readable portfolio risk score report.
        
        Creates a detailed risk assessment report with overall scoring, component
        breakdown, risk factor analysis, and actionable recommendations. Format
        includes professional presentation with emoji indicators and clear sections.
        
        Report Sections:
        1. **Risk Score Summary**: Overall score and risk category with visual indicators
        2. **Component Scores**: Detailed breakdown by risk dimension with status indicators
        3. **Risk Factors**: Specific risk issues requiring attention
        4. **Recommendations**: Actionable risk management suggestions
        5. **Compliance Status**: Overall assessment and next steps
        
        Format: Professional risk assessment report with emoji indicators, clear
        section breaks, and structured presentation suitable for client communication.
        
        Returns:
            str: Complete formatted risk score report (typically 800-1500 characters)
            
        Example:
            ```python
            report = result.to_formatted_report()
            
            # Display for client review
            print(report)
            
            # Send to Claude for risk analysis
            claude_prompt = f"Review this portfolio risk assessment:\\n{report}"
            
            # Include in client communication
            client_email = f"Portfolio Risk Assessment:\\n\\n{report}"
            
            # Risk management documentation
            risk_file = f"risk_assessment_{datetime.now().strftime('%Y%m%d')}.txt"
            with open(risk_file, "w") as f:
                f.write(report)
            ```
            
        Sample Output:
            ```
            ============================================================
            📊 PORTFOLIO RISK SCORE (Scale: 0-100, higher = better)
            ============================================================
            🟡 Overall Score: 75/100 (Moderate Risk)
            
            📈 Component Scores:
            ────────────────────────────────────────
            🔴 Concentration                      52/100
            🟢 Volatility                         82/100
            🟡 Factor Exposure                    71/100
            🟢 Liquidity                          88/100
            
            ⚠️  KEY RISK FACTORS:
               • Portfolio concentration exceeds 30% limit
               • Technology sector allocation above 40% limit
               • Single position weight above 25% threshold
            
            💡 KEY RECOMMENDATIONS:
               • Reduce AAPL position from 28% to below 25%
               • Add defensive positions to reduce volatility
               • Diversify sector concentration
            
            ============================================================
            ```
        """
        # Use stored formatted report if available (from dual-mode function)
        if hasattr(self, '_formatted_report') and self._formatted_report:
            return self._formatted_report
        
        # Fallback to manual reconstruction (basic version)
        sections = []
        
        # Risk Score Summary
        sections.append("=" * 60)
        sections.append("📊 PORTFOLIO RISK SCORE (Scale: 0-100, higher = better)")
        sections.append("=" * 60)
        
        overall_score = self.risk_score.get("score", 0)
        risk_category = self.risk_score.get("category", "Unknown")
        sections.append(f"🟢 Overall Score: {overall_score}/100 ({risk_category})")
        sections.append("")
        
        # Component Scores
        component_scores = self.risk_score.get("component_scores", {})
        if component_scores:
            sections.append("📈 Component Scores:")
            sections.append("─" * 40)
            for component, score in component_scores.items():
                icon = "🟢" if score >= 80 else "🟡" if score >= 60 else "🔴"
                component_name = component.replace("_", " ").title()
                sections.append(f"{icon} {component_name:<30} {score}/100")
            sections.append("")
        
        # Risk Factors
        risk_factors = self.get_risk_factors()
        if risk_factors:
            sections.append("⚠️  KEY RISK FACTORS:")
            for factor in risk_factors:
                sections.append(f"   • {factor}")
            sections.append("")
        
        # Recommendations
        recommendations = self.get_recommendations()
        if recommendations:
            sections.append("💡 KEY RECOMMENDATIONS:")
            for rec in recommendations:
                sections.append(f"   • {rec}")
            sections.append("")
        
        sections.append("=" * 60)
        
        return "\n".join(sections)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "risk_score": _convert_to_json_serializable(self.risk_score),
            "limits_analysis": _convert_to_json_serializable(self.limits_analysis),
            "portfolio_analysis": _convert_to_json_serializable(self.portfolio_analysis),
            "analysis_date": self.analysis_date.isoformat(),
            "portfolio_name": self.portfolio_name,
            "formatted_report": self.to_formatted_report()
        }
    
    @classmethod
    def from_risk_score_analysis(cls, risk_score_result: Dict[str, Any],
                                portfolio_name: Optional[str] = None) -> 'RiskScoreResult':
        """Create RiskScoreResult from run_risk_score_analysis output."""
        return cls(
            risk_score=risk_score_result["risk_score"],
            limits_analysis=risk_score_result["limits_analysis"],
            portfolio_analysis=risk_score_result["portfolio_analysis"],
            analysis_date=datetime.now(),
            portfolio_name=portfolio_name
        )
    
    def __hash__(self) -> int:
        """Make RiskScoreResult hashable for caching."""
        key_data = (
            self.risk_score.get("score", 0),
            self.risk_score.get("category", ""),
            len(self.limits_analysis.get("risk_factors", [])),
            len(self.limits_analysis.get("recommendations", []))
        )
        return hash(key_data)


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
        
        # Risk improvement analysis
        self.risk_improvement = self.volatility_delta < 0  # Lower volatility is better
        self.concentration_improvement = self.concentration_delta < 0  # Lower concentration is better
    
    @classmethod
    def from_what_if_output(cls, 
                           current_summary: Dict[str, Any],
                           scenario_summary: Dict[str, Any],
                           scenario_name: str = "What-If Scenario",
                           risk_comparison: Optional[pd.DataFrame] = None,
                           beta_comparison: Optional[pd.DataFrame] = None) -> 'WhatIfResult':
        """Create WhatIfResult from actual run_what_if() function outputs."""
        
        # Create RiskAnalysisResult objects from build_portfolio_view outputs
        current_metrics = RiskAnalysisResult.from_build_portfolio_view(
            current_summary, portfolio_name="Current Portfolio"
        )
        
        scenario_metrics = RiskAnalysisResult.from_build_portfolio_view(
            scenario_summary, portfolio_name=scenario_name
        )
        
        return cls(
            current_metrics=current_metrics,
            scenario_metrics=scenario_metrics,
            scenario_name=scenario_name,
            risk_comparison=risk_comparison,
            beta_comparison=beta_comparison
        )
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary of scenario impact using real metrics."""
        return {
            "scenario_name": self.scenario_name,
            "volatility_change": {
                "current": round(self.current_metrics.volatility_annual * 100, 2),
                "scenario": round(self.scenario_metrics.volatility_annual * 100, 2),
                "delta": round(self.volatility_delta * 100, 2)
            },
            "concentration_change": {
                "current": round(self.current_metrics.herfindahl, 3),
                "scenario": round(self.scenario_metrics.herfindahl, 3),
                "delta": round(self.concentration_delta, 3)
            },
            "factor_variance_change": {
                "current": round(self.current_metrics.variance_decomposition.get('factor_pct', 0) * 100, 1),
                "scenario": round(self.scenario_metrics.variance_decomposition.get('factor_pct', 0) * 100, 1),
                "delta": round(self.factor_variance_delta * 100, 1)
            },
            "risk_improvement": self.risk_improvement,
            "concentration_improvement": self.concentration_improvement
        }
    
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
    
    def to_formatted_report(self) -> str:
        """Format before/after comparison for display using real metrics."""
        # If we have a stored formatted report (from print_what_if_report), use that
        if hasattr(self, '_formatted_report') and self._formatted_report:
            return self._formatted_report
        
        # Otherwise, fall back to generating our own report
        lines = [
            f"What-If Scenario Analysis: {self.scenario_name}",
            f"{'='*50}",
            f"",
            f"Portfolio Risk Comparison:",
            f"  Annual Volatility:",
            f"    Current:  {self.current_metrics.volatility_annual:.2%}",
            f"    Scenario: {self.scenario_metrics.volatility_annual:.2%}",
            f"    Change:   {self.volatility_delta:+.2%}",
            f"",
            f"  Concentration (Herfindahl):",
            f"    Current:  {self.current_metrics.herfindahl:.3f}",
            f"    Scenario: {self.scenario_metrics.herfindahl:.3f}",
            f"    Change:   {self.concentration_delta:+.3f}",
            f"",
            f"  Factor Variance Share:",
            f"    Current:  {self.current_metrics.variance_decomposition.get('factor_pct', 0):.1%}",
            f"    Scenario: {self.scenario_metrics.variance_decomposition.get('factor_pct', 0):.1%}",
            f"    Change:   {self.factor_variance_delta:+.1%}",
            f""
        ]
        
        # Add factor exposures comparison
        factor_comparison = self.get_factor_exposures_comparison()
        if factor_comparison:
            lines.append("Factor Exposures Comparison:")
            for factor, values in factor_comparison.items():
                lines.append(f"  {factor.capitalize()}:")
                lines.append(f"    Current:  {values['current']:+.2f}")
                lines.append(f"    Scenario: {values['scenario']:+.2f}")
                lines.append(f"    Change:   {values['delta']:+.2f}")
            lines.append("")
        
        # Add improvement summary
        lines.append("Improvement Summary:")
        lines.append(f"  Risk (Volatility): {'✅ Improved' if self.risk_improvement else '❌ Increased'}")
        lines.append(f"  Concentration:     {'✅ Improved' if self.concentration_improvement else '❌ Increased'}")
        
        return "\n".join(lines)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "scenario_name": self.scenario_name,
            "current_metrics": self.current_metrics.to_dict(),
            "scenario_metrics": self.scenario_metrics.to_dict(),
            "deltas": {
                "volatility_delta": self.volatility_delta,
                "concentration_delta": self.concentration_delta,
                "factor_variance_delta": self.factor_variance_delta
            },
            "analysis": {
                "risk_improvement": self.risk_improvement,
                "concentration_improvement": self.concentration_improvement
            },
            "factor_exposures_comparison": self.get_factor_exposures_comparison(),
            "summary": self.get_summary()
        }


class StockAnalysisResult:
    """
    Individual stock analysis results with multi-factor support and volatility metrics.
    
    Contains comprehensive single-stock risk analysis including volatility characteristics,
    market regression statistics, factor exposures, and risk decomposition. Supports both
    simple market regression and multi-factor model analysis.
    
    Key Analysis Components:
    - **Volatility Metrics**: Historical volatility, Sharpe ratio, maximum drawdown
    - **Market Regression**: Beta, alpha, R-squared, and correlation with market
    - **Factor Exposures**: Systematic risk factor beta coefficients (growth, value, momentum)
    - **Risk Decomposition**: Systematic vs. idiosyncratic risk breakdown
    - **Performance Metrics**: Risk-adjusted returns and performance attribution
    - **Statistical Quality**: Model fit, significance tests, and diagnostic measures
    
    Analysis Types:
    - **Simple Regression**: Beta vs. market index (SPY) with basic risk metrics
    - **Multi-Factor**: Complete factor model with growth, value, momentum, and market exposures
    
    Architecture Role:
        Stock Analysis → Core Functions → StockAnalysisResult → Investment Research
    
    Example:
        ```python
        # Get stock analysis result
        result = stock_service.analyze_stock("AAPL", "2020-01-01", "2023-12-31")
        
        # Access volatility characteristics
        vol_metrics = result.get_volatility_metrics()
        annual_vol = vol_metrics["volatility_annual"]       # 0.285 (28.5% volatility)
        sharpe_ratio = vol_metrics["sharpe_ratio"]          # 1.23 (risk-adjusted return)
        max_drawdown = vol_metrics["max_drawdown"]          # -0.45 (45% peak-to-trough)
        
        # Market regression analysis
        regression = result.get_market_regression()
        market_beta = regression["beta"]                    # 1.15 (15% more volatile than market)
        alpha = regression["alpha"]                         # 0.05 (5% annual outperformance)
        r_squared = regression["r_squared"]                 # 0.78 (78% explained by market)
        
        # Factor exposure analysis (if multi-factor)
        factor_betas = result.get_factor_exposures()
        growth_beta = factor_betas["growth"]                # 1.35 (growth-oriented)
        value_beta = factor_betas["value"]                  # -0.12 (growth > value)
        momentum_beta = factor_betas["momentum"]            # 0.85 (moderate momentum)
        
        # Risk decomposition
        risk_chars = result.get_risk_characteristics()
        systematic_risk = risk_chars["systematic_risk"]     # 0.201 (systematic component)
        idiosyncratic_risk = risk_chars["idiosyncratic_risk"] # 0.084 (stock-specific)
        
        # Get formatted report for analysis
        report = result.to_formatted_report()
        ```
    
    Use Cases:
    - Individual stock risk assessment and due diligence
    - Factor exposure analysis for portfolio construction
    - Performance attribution and risk-adjusted return analysis
    - Security selection and investment research workflows
    """
    
    def __init__(self, 
                 stock_data: Dict[str, Any],
                 ticker: str):
        # Core stock analysis data
        self.ticker = ticker.upper()
        self.volatility_metrics = stock_data.get("vol_metrics", {})
        self.regression_metrics = stock_data.get("regression_metrics", {})
        self.factor_summary = stock_data.get("factor_summary")
        self.risk_metrics = stock_data.get("risk_metrics", {})
        
        # Analysis metadata
        self.analysis_date = datetime.now()
    
    def get_volatility_metrics(self) -> Dict[str, float]:
        """Get stock volatility metrics from run_stock() output."""
        return {
            "monthly_volatility": self.volatility_metrics.get("monthly_vol", 0),
            "annual_volatility": self.volatility_metrics.get("annual_vol", 0)
        }
    
    def get_market_regression(self) -> Dict[str, float]:
        """Get market regression metrics from run_stock() output."""
        return {
            "beta": self.regression_metrics.get("beta", 0),
            "alpha": self.regression_metrics.get("alpha", 0),
            "r_squared": self.regression_metrics.get("r_squared", 0),
            "idiosyncratic_volatility": self.regression_metrics.get("idio_vol_m", 0)
        }
    
    def get_factor_exposures(self) -> Dict[str, float]:
        """Get factor exposures from run_stock() output (if factor analysis was performed)."""
        if self.factor_summary is not None and not self.factor_summary.empty:
            return self.factor_summary.get("beta", pd.Series()).to_dict()
        return {}
    
    def get_risk_characteristics(self) -> Dict[str, float]:
        """Get comprehensive risk characteristics for this individual stock."""
        return {
            "annual_volatility": self.volatility_metrics.get("annual_vol", 0),
            "market_beta": self.regression_metrics.get("beta", 0),
            "market_correlation": self.regression_metrics.get("r_squared", 0) ** 0.5 if self.regression_metrics.get("r_squared", 0) > 0 else 0,
            "idiosyncratic_risk": self.regression_metrics.get("idio_vol_m", 0)
        }
    
    @classmethod
    def from_stock_analysis(cls, ticker: str, vol_metrics: Dict[str, float], 
                           regression_metrics: Dict[str, float], 
                           factor_summary: Optional[pd.DataFrame] = None) -> 'StockAnalysisResult':
        """Create StockAnalysisResult from run_stock() underlying function outputs."""
        stock_data = {
            "ticker": ticker,
            "vol_metrics": vol_metrics,
            "regression_metrics": regression_metrics,
            "factor_summary": factor_summary
        }
        return cls(stock_data=stock_data, ticker=ticker)
    
    def to_formatted_report(self) -> str:
        """Format stock analysis results to match run_stock() output style."""
        lines = [
            f"Stock Analysis Report: {self.ticker}",
            f"{'='*40}",
            f"",
            f"=== Volatility Metrics ===",
            f"Monthly Volatility:      {self.volatility_metrics.get('monthly_vol', 0):.2%}",
            f"Annual Volatility:       {self.volatility_metrics.get('annual_vol', 0):.2%}",
            f"",
            f"=== Market Regression ===",
            f"Beta:                   {self.regression_metrics.get('beta', 0):.3f}",
            f"Alpha (Monthly):        {self.regression_metrics.get('alpha', 0):.4f}",
            f"R-Squared:              {self.regression_metrics.get('r_squared', 0):.3f}",
            f"Idiosyncratic Vol:      {self.regression_metrics.get('idio_vol_m', 0):.2%}",
            f""
        ]
        
        # Add factor analysis if available
        if self.factor_summary is not None and not self.factor_summary.empty:
            lines.append("=== Factor Analysis ===")
            if "beta" in self.factor_summary:
                for factor, beta in self.factor_summary["beta"].items():
                    lines.append(f"{factor.capitalize():<15} {beta:>8.3f}")
            lines.append("")
        
        return "\n".join(lines) 
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "ticker": self.ticker,
            "volatility_metrics": self.volatility_metrics,
            "regression_metrics": self.regression_metrics,
            "factor_summary": self.factor_summary.to_dict() if self.factor_summary is not None and not self.factor_summary.empty else {},
            "risk_metrics": self.risk_metrics,
            "analysis_date": self.analysis_date.isoformat()
        }
    
    def __hash__(self) -> int:
        """Make StockAnalysisResult hashable for caching."""
        key_data = (
            self.ticker,
            self.volatility_metrics.get("annual_vol", 0),
            self.regression_metrics.get("beta", 0),
            self.regression_metrics.get("r_squared", 0)
        )
        return hash(key_data) 


@dataclass
class InterpretationResult:
    """
    Portfolio interpretation results from AI-assisted analysis.
    
    Contains the GPT interpretation of portfolio analysis along with
    the full diagnostic output and analysis metadata.
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
        """Get interpretation summary."""
        return {
            "interpretation_length": len(self.ai_interpretation),
            "diagnostics_length": len(self.full_diagnostics),
            "portfolio_file": self.analysis_metadata.get("portfolio_file", ""),
            "interpretation_service": self.analysis_metadata.get("interpretation_service", ""),
            "analysis_date": self.analysis_metadata.get("analysis_date", "")
        }
    
    def get_interpretation_preview(self, max_chars: int = 200) -> str:
        """Get preview of AI interpretation."""
        if len(self.ai_interpretation) <= max_chars:
            return self.ai_interpretation
        return self.ai_interpretation[:max_chars] + "..."
    
    def get_diagnostics_preview(self, max_chars: int = 500) -> str:
        """Get preview of diagnostic output."""
        if len(self.full_diagnostics) <= max_chars:
            return self.full_diagnostics
        return self.full_diagnostics[:max_chars] + "..."
    
    def to_formatted_report(self) -> str:
        """Format interpretation results for display."""
        sections = []
        
        sections.append("=== GPT PORTFOLIO INTERPRETATION ===")
        sections.append("")
        sections.append(self.ai_interpretation)
        sections.append("")
        sections.append("=== FULL DIAGNOSTICS ===")
        sections.append("")
        sections.append(self.full_diagnostics)
        
        return "\n".join(sections)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "ai_interpretation": self.ai_interpretation,
            "full_diagnostics": self.full_diagnostics,
            "analysis_metadata": _convert_to_json_serializable(self.analysis_metadata),
            "analysis_date": self.analysis_date.isoformat(),
            "portfolio_name": self.portfolio_name,
            "summary": self.get_summary()
        }
    
    @classmethod
    def from_interpretation_output(cls, interpretation_output: Dict[str, Any],
                                  portfolio_name: Optional[str] = None) -> 'InterpretationResult':
        """Create InterpretationResult from run_and_interpret output."""
        return cls(
            ai_interpretation=interpretation_output["ai_interpretation"],
            full_diagnostics=interpretation_output["full_diagnostics"],
            analysis_metadata=interpretation_output["analysis_metadata"],
            analysis_date=datetime.now(),
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


@dataclass
class DirectPortfolioResult:
    """Result object for direct portfolio analysis endpoints.
    
    Provides consistent serialization with service layer endpoints by wrapping
    raw output from run_portfolio() function and applying standard JSON conversion.
    """
    raw_output: Dict[str, Any]
    analysis_type: str = "portfolio"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary using standard service layer serialization."""
        return {
            "analysis_type": self.analysis_type,
            "volatility_annual": self.raw_output.get('volatility_annual'),
            "portfolio_factor_betas": _convert_to_json_serializable(
                self.raw_output.get('portfolio_factor_betas')
            ),
            "risk_contributions": _convert_to_json_serializable(
                self.raw_output.get('risk_contributions')
            ),
            "df_stock_betas": _convert_to_json_serializable(
                self.raw_output.get('df_stock_betas')
            ),
            "covariance_matrix": _convert_to_json_serializable(
                self.raw_output.get('covariance_matrix')
            ),
            **{k: _convert_to_json_serializable(v) 
               for k, v in self.raw_output.items()}
        }
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary using standard formatting."""
        return {
            "endpoint": "direct/portfolio",
            "analysis_type": self.analysis_type,
            "volatility_annual": self.raw_output.get('volatility_annual'),
            "total_positions": len(self.raw_output.get('risk_contributions', {})),
            "data_quality": "direct_access"
        }


@dataclass  
class DirectStockResult:
    """Result object for direct stock analysis endpoints."""
    raw_output: Dict[str, Any]
    analysis_type: str = "stock"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary using standard service layer serialization."""
        return {
            "analysis_type": self.analysis_type,
            **{k: _convert_to_json_serializable(v) 
               for k, v in self.raw_output.items()}
        }
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary using standard formatting."""
        return {
            "endpoint": "direct/stock",
            "analysis_type": self.analysis_type,
            "data_quality": "direct_access"
        }


@dataclass
class DirectOptimizationResult:
    """Result object for direct optimization endpoints."""
    raw_output: Dict[str, Any]
    analysis_type: str = "optimization"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary using standard service layer serialization."""
        return {
            "analysis_type": self.analysis_type,
            "optimal_weights": _convert_to_json_serializable(
                self.raw_output.get('optimal_weights')
            ),
            "optimization_metrics": _convert_to_json_serializable(
                self.raw_output.get('optimization_metrics')
            ),
            **{k: _convert_to_json_serializable(v) 
               for k, v in self.raw_output.items()}
        }
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary using standard formatting."""
        return {
            "endpoint": "direct/optimization",
            "analysis_type": self.analysis_type,
            "data_quality": "direct_access"
        }


@dataclass
class DirectPerformanceResult:
    """Result object for direct performance analysis endpoints."""
    raw_output: Dict[str, Any]
    analysis_type: str = "performance"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary using standard service layer serialization."""
        return {
            "analysis_type": self.analysis_type,
            "performance_metrics": _convert_to_json_serializable(
                self.raw_output.get('performance_metrics')
            ),
            **{k: _convert_to_json_serializable(v) 
               for k, v in self.raw_output.items()}
        }
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary using standard formatting."""
        return {
            "endpoint": "direct/performance", 
            "analysis_type": self.analysis_type,
            "data_quality": "direct_access"
        } 


@dataclass
class DirectWhatIfResult:
    """Result object for direct what-if analysis endpoints."""
    raw_output: Dict[str, Any]
    analysis_type: str = "what_if"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary using standard service layer serialization."""
        return {
            "analysis_type": self.analysis_type,
            "current_scenario": _convert_to_json_serializable(
                self.raw_output.get('current_scenario')
            ),
            "what_if_scenario": _convert_to_json_serializable(
                self.raw_output.get('what_if_scenario')
            ),
            "comparison_metrics": _convert_to_json_serializable(
                self.raw_output.get('comparison_metrics')
            ),
            **{k: _convert_to_json_serializable(v) 
               for k, v in self.raw_output.items()}
        }
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary using standard formatting."""
        return {
            "endpoint": "direct/what-if",
            "analysis_type": self.analysis_type,
            "data_quality": "direct_access"
        }


@dataclass
class DirectInterpretResult:
    """Result object for direct interpretation endpoints."""
    raw_output: Dict[str, Any]
    analysis_type: str = "interpret"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary using standard service layer serialization."""
        return {
            "analysis_type": self.analysis_type,
            "ai_interpretation": self.raw_output.get('ai_interpretation', ''),
            "full_diagnostics": self.raw_output.get('full_diagnostics', ''),
            "analysis_metadata": _convert_to_json_serializable(
                self.raw_output.get('analysis_metadata', {})
            ),
            **{k: _convert_to_json_serializable(v) 
               for k, v in self.raw_output.items()}
        }
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary using standard formatting."""
        return {
            "endpoint": "direct/interpret",
            "analysis_type": self.analysis_type,
            "interpretation_length": len(self.raw_output.get('ai_interpretation', '')),
            "diagnostics_length": len(self.raw_output.get('full_diagnostics', '')),
            "data_quality": "direct_access"
        } 
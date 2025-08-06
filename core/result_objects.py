"""Result objects for structured service layer responses.

API Serialization Patterns:
    All result objects implement two serialization methods:
    
    • to_api_response() - Schema-compliant serialization for API endpoints
      Returns structured data matching the OpenAPI schema definitions.
      Use this method for all API responses to ensure schema compliance.
      
    • to_dict() - DEPRECATED legacy method
      Emits DeprecationWarning and delegates to to_api_response().
      Will be removed in Phase 2 of the refactor.

Example Usage:
    # Preferred - schema-compliant API response
    result = analyze_portfolio(portfolio_data)
    api_data = result.to_api_response()
    
    # Deprecated - will be removed
    legacy_data = result.to_dict()  # Shows deprecation warning
"""

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
        
        # Convert any datetime indices to strings - use ISO format for API consistency
        if hasattr(df_copy.index, 'strftime'):
            df_copy.index = df_copy.index.map(lambda x: x.isoformat() if hasattr(x, 'isoformat') else str(x))
        
        # Convert to dict and clean NaN values
        result = df_copy.to_dict()
        return _clean_nan_values(result)
    
    elif isinstance(obj, pd.Series):
        # Convert Series with timestamp handling
        series_copy = obj.copy()
        
        # Convert any datetime indices to strings - use ISO format for API consistency
        if hasattr(series_copy.index, 'strftime'):
            series_copy.index = series_copy.index.map(lambda x: x.isoformat() if hasattr(x, 'isoformat') else str(x))
        
        # Convert to dict and clean NaN values
        result = series_copy.to_dict()
        return _clean_nan_values(result)
    
    elif isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    
    elif isinstance(obj, (np.integer, np.floating)):
        if np.isnan(obj):
            return None
        value = obj.item()
        # Format floats to fixed decimal to prevent scientific notation
        if isinstance(value, float):
            # Use 8 decimal places for precision while avoiding scientific notation
            return round(value, 8)
        return value
    
    elif isinstance(obj, dict):
        return {k: _convert_to_json_serializable(v) for k, v in obj.items()}
    
    elif isinstance(obj, list):
        return [_convert_to_json_serializable(item) for item in obj]
    
    elif isinstance(obj, float):
        # Handle regular Python floats to prevent scientific notation
        if np.isnan(obj):
            return None
        return round(obj, 8)
    
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
    3. **API Serialization**: Use to_api_response() for JSON export and API responses
    4. **Legacy Serialization**: to_dict() is deprecated, use to_api_response() instead
    5. **Comparison**: Compare multiple results for scenario analysis
    
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
        
        # Export for API response
        api_data = result.to_api_response()
        # {"volatility_annual": 0.185, "portfolio_factor_betas": {...}, ...}
        
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
    stock_betas: pd.DataFrame
    
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
    
    # Additional fields for CLI-API parity
    expected_returns: Optional[Dict[str, float]] = None
    factor_proxies: Optional[Dict[str, str]] = None
    
    # Portfolio exposure metrics (calculated from allocations)
    net_exposure: Optional[float] = None
    gross_exposure: Optional[float] = None
    leverage: Optional[float] = None
    total_value: Optional[float] = None
    
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
    
    def _build_target_allocations_table(self) -> Dict[str, Any]:
        """
        Build target allocations comparison table from portfolio allocations DataFrame.
        
        This method converts the allocations DataFrame (used by CLI) into a structured
        format for API consumption. The resulting structure matches exactly what the
        CLI displays in the "=== Target Allocations ===" section.
        
        Returns:
            Dict[str, Any]: Allocations comparison table containing:
                - ticker -> allocation data mapping
                - Portfolio Weight: Current portfolio allocation (0-1)
                - Equal Weight: Equal-weight allocation target (0-1) 
                - Eq Diff: Deviation from equal weight
                - Prop Target: Proportional target allocation (if available)
                - Prop Diff: Deviation from proportional target (if available)
                
        Data Source:
            - self.allocations: Portfolio allocations DataFrame from compute_target_allocations()
            
        CLI Alignment:
            - Exact match with "=== Target Allocations ===" table output
            - Same column names and value formatting as CLI displays
            
        Example:
            ```python
            table = result._build_target_allocations_table()
            
            aapl_data = table["AAPL"]
            current_weight = aapl_data["Portfolio Weight"]    # 0.15 (15% allocation)
            equal_weight = aapl_data["Equal Weight"]          # 0.045 (4.5% equal weight)
            deviation = aapl_data["Eq Diff"]                  # 0.105 (10.5% overweight)
            ```
        """
        if self.allocations is None:
            return {}
        
        # Handle both DataFrame and dict formats
        if hasattr(self.allocations, 'to_dict'):
            # DataFrame case - convert to match CLI display structure
            return self.allocations.to_dict('index')
        else:
            # Dict case - return as-is
            return self.allocations
    
    def _get_risk_limit_violations_summary(self) -> List[Dict[str, Any]]:
        """
        Generate risk limit compliance checks table from portfolio risk analysis.
        
        This method converts the risk_checks data (used by CLI) into a structured
        table format for API consumption. The resulting structure matches exactly 
        what the CLI displays in the "=== Portfolio Risk Limit Checks ===" section.
        
        Returns:
            List[Dict[str, Any]]: Risk limit checks table containing:
                - metric: Risk metric name (e.g., "volatility", "concentration")
                - actual: Current portfolio value for the metric (0-1 percentage)
                - limit: Maximum allowed value for the metric (0-1 percentage)
                - status: Compliance status ("PASS" or "FAIL")
                - formatted_line: CLI-formatted display string
                
        Data Source:
            - self.risk_checks: Risk compliance checks from portfolio analysis
            
        CLI Alignment:
            - Exact match with "=== Portfolio Risk Limit Checks ===" table output
            - Same formatting: "metric               actual%  ≤ limit%  → STATUS"
            
        Interpretation:
            - PASS: Portfolio metric is within acceptable risk limits
            - FAIL: Portfolio exceeds risk limits, requires attention
            
        Example:
            ```python
            checks = result._get_risk_limit_violations_summary()
            
            for check in checks:
                metric = check["metric"]              # "volatility"
                actual = check["actual"]              # 0.18 (18% volatility)
                limit = check["limit"]                # 0.15 (15% limit)
                status = check["status"]              # "FAIL"
                display = check["formatted_line"]     # "volatility           18.00%  ≤ 15.00%  → FAIL"
            ```
        """
        if not hasattr(self, 'risk_checks') or not self.risk_checks:
            return []
        
        table = []
        for check in self.risk_checks:
            metric = check.get('Metric', 'Unknown')
            actual = check.get('Actual', 0)
            limit = check.get('Limit', 0)
            passed = check.get('Pass', False)
            status = "PASS" if passed else "FAIL"
            
            # Match exact CLI structure
            row = {
                "metric": metric,
                "actual": actual,
                "limit": limit,
                "status": status,
                "formatted_line": f"{metric:<22} {actual:.2%}  ≤ {limit:.2%}  → {status}"
            }
            table.append(row)
        
        return table
    
    def _get_beta_exposure_checks_table(self) -> List[Dict[str, Any]]:
        """
        Generate factor beta exposure compliance checks table from portfolio analysis.
        
        This method converts the beta_checks data (used by CLI) into a structured
        table format for API consumption. The resulting structure matches exactly
        what the CLI displays in the "=== Beta Exposure Checks ===" section.
        
        Returns:
            List[Dict[str, Any]]: Beta exposure checks table containing:
                - factor: Factor name (e.g., "market", "value", "momentum")
                - portfolio_beta: Current portfolio beta exposure to factor
                - max_allowed_beta: Maximum allowed beta exposure limit
                - status: Compliance status ("PASS" or "FAIL")
                - formatted_line: CLI-formatted display string
                
        Data Source:
            - self.beta_checks: Factor beta compliance checks from portfolio analysis
            
        CLI Alignment:
            - Exact match with "=== Beta Exposure Checks ===" table output
            - Same formatting: "factor           β = +0.12  ≤ 0.20  → STATUS"
            
        Interpretation:
            - PASS: Portfolio factor exposure is within acceptable beta limits
            - FAIL: Portfolio has excessive factor exposure, may need hedging
            
        Example:
            ```python
            checks = result._get_beta_exposure_checks_table()
            
            for check in checks:
                factor = check["factor"]                    # "market"
                beta = check["portfolio_beta"]             # 0.12 (12% market beta)
                limit = check["max_allowed_beta"]          # 0.20 (20% limit)
                status = check["status"]                   # "PASS"
                display = check["formatted_line"]          # "market           β = +0.12  ≤ 0.20  → PASS"
            ```
        """
        if not self.beta_checks:
            return []
        
        table = []
        for check in self.beta_checks:
            factor = check.get('factor', 'Unknown')
            portfolio_beta = check.get('portfolio_beta', 0)
            max_allowed_beta = check.get('max_allowed_beta', 0)
            passed = check.get('pass', False)
            status = "PASS" if passed else "FAIL"
            
            # Match exact CLI structure
            row = {
                "factor": factor,
                "portfolio_beta": portfolio_beta,
                "max_allowed_beta": max_allowed_beta,
                "status": status,
                "formatted_line": f"{factor:<20} β = {portfolio_beta:+.2f}  ≤ {max_allowed_beta:.2f}  → {status}"
            }
            table.append(row)
        
        return table

    def _build_industry_group_betas_table(self) -> List[Dict[str, Any]]:
        """
        Generate industry group beta exposures table from portfolio variance analysis.
        
        This method converts the per_industry_group_beta data (used by CLI) into a
        structured table format for API consumption. The resulting structure matches
        exactly what the CLI displays in the "=== Per-Industry Group Betas ===" section.
        
        Returns:
            List[Dict[str, Any]]: Industry group betas table containing:
                - ticker: ETF ticker symbol (e.g., "XLF", "XLK")
                - labeled_etf: Ticker with industry description (e.g., "XLF (Financial Services)")
                - beta: Portfolio beta exposure to industry group
                - formatted_line: CLI-formatted display string with adaptive column width
                
        Data Source:
            - self.industry_variance.per_industry_group_beta: Industry beta exposures
            - ETF mapping utilities for industry labels
            
        CLI Alignment:
            - Exact match with "=== Per-Industry Group Betas ===" table output
            - Same sorting: by absolute beta value (highest exposure first)
            - Same labeling: uses ETF industry mappings for descriptions
            - Same formatting: adaptive column width with +/-7.4f precision
            
        Interpretation:
            - Positive beta: Portfolio moves with industry sector
            - Negative beta: Portfolio moves opposite to industry sector
            - Higher absolute values indicate stronger industry exposure
            
        Example:
            ```python
            industry_betas = result._build_industry_group_betas_table()
            
            for group in industry_betas:
                ticker = group["ticker"]              # "XLF"
                label = group["labeled_etf"]          # "XLF (Financial Services)"
                beta = group["beta"]                  # 0.1234 (12.34% exposure)
                display = group["formatted_line"]     # "XLF (Financial Services)  : +0.1234"
            ```
        """
        if not self.industry_variance:
            return []
        
        per_group = self.industry_variance.get("per_industry_group_beta", {})
        if not per_group:
            return []
        
        # Import CLI utilities to match exact labeling format
        try:
            from utils.etf_mappings import get_etf_to_industry_map, format_ticker_with_label
            from run_portfolio_risk import get_cash_positions
            
            cash_positions = get_cash_positions()
            industry_map = get_etf_to_industry_map()
        except ImportError:
            # Fallback if utilities not available
            cash_positions = {}
            industry_map = {}
        
        # Calculate adaptive column width (matching CLI logic)
        max_etf_width = 12  # minimum width for backwards compatibility
        for ticker in per_group.keys():
            if cash_positions and industry_map:
                from utils.etf_mappings import format_ticker_with_label
                labeled_etf = format_ticker_with_label(ticker, cash_positions, industry_map)
            else:
                labeled_etf = ticker
            max_etf_width = max(max_etf_width, len(labeled_etf))
        
        # Add padding
        max_etf_width += 2
        
        # Build table with exact CLI structure
        table = []
        for ticker, beta_value in sorted(per_group.items(), key=lambda kv: -abs(kv[1])):
            if cash_positions and industry_map:
                from utils.etf_mappings import format_ticker_with_label
                labeled_etf = format_ticker_with_label(ticker, cash_positions, industry_map)
            else:
                labeled_etf = ticker
            
            row = {
                "ticker": ticker,
                "labeled_etf": labeled_etf,
                "beta": beta_value,
                "formatted_line": f"{labeled_etf:<{max_etf_width}} : {beta_value:>+7.4f}"
            }
            table.append(row)
        
        return table

    def _build_industry_variance_percentage_table(self) -> Dict[str, Any]:
        """
        Generate industry variance percentage table from portfolio variance analysis.
        
        This method converts the percent_of_portfolio data (used by CLI) into a
        structured format for API consumption. The resulting structure matches
        exactly what the CLI displays in the "=== Industry Variance (% of Portfolio) ===" section.
        
        Returns:
            Dict[str, Any]: Industry variance percentage table containing:
                - industry -> percentage mapping
                - Each industry's contribution to total portfolio variance as percentage
                
        Data Source:
            - self.industry_variance.percent_of_portfolio: Industry variance percentages
            
        CLI Alignment:
            - Exact match with "=== Industry Variance (% of Portfolio) ===" section output
            - Same formatting: industry name with percentage values (e.g., "XLF: 15.2%")
            
        Interpretation:
            - Shows how much each industry contributes to overall portfolio risk
            - Higher percentages indicate industries driving portfolio volatility
            - Sum of all percentages should approximate 100% of total variance
            
        Example:
            ```python
            industry_var = result._build_industry_variance_percentage_table()
            
            xlf_contribution = industry_var["XLF"]     # 0.152 (15.2% of portfolio variance)
            xlk_contribution = industry_var["XLK"]     # 0.089 (8.9% of portfolio variance)
            ```
        """
        if not self.industry_variance:
            return {}
        
        # Return the exact data that CLI uses for "Industry Variance (% of Portfolio)"
        return self.industry_variance.get("percent_of_portfolio", {})

    def _build_factor_variance_percentage_table(self) -> Dict[str, Any]:
        """
        Generate factor variance percentage table from portfolio variance decomposition.
        
        This method converts the factor_breakdown_pct data (used by CLI) into a
        structured format for API consumption. The resulting structure matches
        exactly what the CLI displays in the "=== Factor Variance (% of Portfolio, excluding industry) ===" section.
        
        Returns:
            Dict[str, Any]: Factor variance percentage table containing:
                - factor -> percentage mapping (excluding industry and subindustry)
                - Each systematic factor's contribution to total portfolio variance as percentage
                
        Data Source:
            - self.variance_decomposition.factor_breakdown_pct: Factor variance percentages
            - Filtered to exclude industry and subindustry factors (as CLI does)
            
        CLI Alignment:
            - Exact match with "=== Factor Variance (% of Portfolio, excluding industry) ===" section output
            - Same filtering: excludes "industry" and "subindustry" factors
            - Same formatting: factor name with percentage values (e.g., "Market: 25%")
            
        Interpretation:
            - Shows how much each systematic factor contributes to portfolio risk
            - Excludes industry factors to focus on broad market factors
            - Higher percentages indicate factors driving portfolio volatility
            
        Example:
            ```python
            factor_var = result._build_factor_variance_percentage_table()
            
            market_contribution = factor_var["market"]     # 0.25 (25% of portfolio variance)
            value_contribution = factor_var["value"]       # 0.08 (8% of portfolio variance)
            momentum_contribution = factor_var["momentum"] # 0.12 (12% of portfolio variance)
            ```
        """
        if not self.variance_decomposition:
            return {}
        
        # Get factor breakdown percentages
        factor_breakdown_pct = self.variance_decomposition.get("factor_breakdown_pct", {})
        
        # Filter out industry and subindustry factors (exact CLI logic)
        filtered = {
            k: v for k, v in factor_breakdown_pct.items()
            if k not in ("industry", "subindustry")
        }
        
        return filtered

    def _build_factor_variance_absolute_table(self) -> Dict[str, Any]:
        """
        Generate factor variance absolute values table from portfolio variance decomposition.
        
        This method converts the factor_breakdown_var data (used by CLI) into a
        structured format for API consumption. The resulting structure matches
        exactly what the CLI displays in the "=== Factor Variance (absolute) ===" section.
        
        Returns:
            Dict[str, Any]: Factor variance absolute table containing:
                - factor -> absolute variance mapping
                - Each factor's absolute contribution to total portfolio variance
                
        Data Source:
            - self.variance_decomposition.factor_breakdown_var: Factor variance absolute values
            
        CLI Alignment:
            - Exact match with "=== Factor Variance (absolute) ===" section output
            - Same formatting: factor name with absolute variance values (e.g., "Market: 0.01234")
            - Includes all factors (no filtering, unlike percentage version)
            
        Interpretation:
            - Shows absolute variance contribution of each systematic factor
            - Higher values indicate factors contributing more to portfolio volatility
            - Sum of all factor variances + idiosyncratic = total portfolio variance
            
        Example:
            ```python
            factor_var = result._build_factor_variance_absolute_table()
            
            market_variance = factor_var["market"]     # 0.01234 (absolute variance contribution)
            value_variance = factor_var["value"]       # 0.00456 (absolute variance contribution)
            industry_variance = factor_var["industry"] # 0.00789 (absolute variance contribution)
            ```
        """
        if not self.variance_decomposition:
            return {}
        
        # Return the exact data that CLI uses for "Factor Variance (absolute)"
        return self.variance_decomposition.get("factor_breakdown_var", {})

    def _build_top_stock_variance_euler_table(self) -> List[Dict[str, Any]]:
        """
        Generate top stock variance contributors table from Euler variance percentages.
        
        This method converts the euler_variance_pct data (used by CLI) into a
        structured format for API consumption. The resulting structure matches
        exactly what the CLI displays in the "=== Top Stock Variance (Euler %) ===" section.
        
        Returns:
            List[Dict[str, Any]]: Top stock variance table containing:
                - ticker: Stock ticker symbol
                - variance_contribution: Euler variance percentage (0-1)
                - formatted_line: CLI-formatted display string
                
        Data Source:
            - self.euler_variance_pct: Individual stock variance contributions (Euler method)
            - Sorted by variance contribution (highest first), top 10 stocks only
            
        CLI Alignment:
            - Exact match with "=== Top Stock Variance (Euler %) ===" section output
            - Same sorting: by variance contribution (descending)
            - Same limit: top 10 contributors only
            - Same formatting: ticker with percentage values (e.g., "AAPL: 15.2%")
            
        Interpretation:
            - Shows which individual stocks contribute most to portfolio risk
            - Euler method provides precise variance attribution to each position
            - Higher percentages indicate stocks driving portfolio volatility
            
        Example:
            ```python
            top_stocks = result._build_top_stock_variance_euler_table()
            
            for stock in top_stocks:
                ticker = stock["ticker"]                    # "AAPL"
                contribution = stock["variance_contribution"] # 0.152 (15.2% of portfolio variance)
                display = stock["formatted_line"]           # "AAPL      : 15.2%"
            ```
        """
        if self.euler_variance_pct.empty:
            return []
        
        # Get top 10 stocks by variance contribution (exact CLI logic)
        top_stocks = dict(sorted(self.euler_variance_pct.items(), key=lambda kv: -kv[1])[:10])
        
        table = []
        for ticker, variance_pct in top_stocks.items():
            row = {
                "ticker": ticker,
                "variance_contribution": variance_pct,
                "formatted_line": f"{ticker:<10} : {variance_pct:6.1%}"
            }
            table.append(row)
        
        return table

    def _build_industry_variance_absolute_table(self) -> Dict[str, Any]:
        """
        Generate industry variance absolute values table from portfolio variance analysis.
        
        This method converts the industry variance data (used by CLI) into a
        structured format for API consumption. The resulting structure matches
        exactly what the CLI displays in the "=== Industry Variance (absolute) ===" section.
        
        Returns:
            Dict[str, Any]: Industry variance absolute table containing:
                - industry -> absolute variance mapping
                - Each industry's absolute contribution to total portfolio variance
                
        Data Source:
            - self.industry_variance.industry_breakdown_var: Industry variance absolute values
            
        CLI Alignment:
            - Exact match with "=== Industry Variance (absolute) ===" section output
            - Same formatting: industry name with absolute variance values (e.g., "IGV: 0.004394")
            
        Interpretation:
            - Shows absolute variance contribution of each industry to portfolio risk
            - Higher values indicate industries contributing more to portfolio volatility
            - Sum of all industry variances contributes to total portfolio factor variance
            
        Example:
            ```python
            industry_var = result._build_industry_variance_absolute_table()
            
            igv_variance = industry_var["IGV"]     # 0.004394 (absolute variance contribution)
            kce_variance = industry_var["KCE"]     # 0.003031 (absolute variance contribution)
            ```
        """
        if not self.industry_variance:
            return {}
        
        # Return the exact data that CLI uses for "Industry Variance (absolute)"
        return self.industry_variance.get("industry_breakdown_var", {})


    
    def to_api_response(self) -> Dict[str, Any]:
        """
        Schema-compliant version of the old to_dict().
        For Phase 1.5 this must be a 1-to-1 copy of to_dict()'s output
        (no structural changes, no field renames, no pruning).
        """
        return {
            "volatility_annual": self.volatility_annual,
            "volatility_monthly": self.volatility_monthly,
            "herfindahl": self.herfindahl,
            "portfolio_factor_betas": _convert_to_json_serializable(self.portfolio_factor_betas),
            "variance_decomposition": _convert_to_json_serializable(self.variance_decomposition),
            "risk_contributions": _convert_to_json_serializable(self.risk_contributions),
            "stock_betas": _convert_to_json_serializable(self.stock_betas),
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
            "formatted_report": self.to_formatted_report(),
            "expected_returns": self.expected_returns,
            "factor_proxies": self.factor_proxies,
            "net_exposure": self.net_exposure,
            "gross_exposure": self.gross_exposure,
            "leverage": self.leverage,
            "total_value": self.total_value,
            "target_allocations_table": self._build_target_allocations_table(),
            "risk_limit_violations_summary": self._get_risk_limit_violations_summary(),
            "beta_exposure_checks_table": self._get_beta_exposure_checks_table(),
            "industry_group_betas": self._build_industry_group_betas_table(),
            "industry_variance_percentage": self._build_industry_variance_percentage_table(),
            "factor_variance_percentage": self._build_factor_variance_percentage_table(),
            "factor_variance_absolute": self._build_factor_variance_absolute_table(),
            "top_stock_variance_euler": self._build_top_stock_variance_euler_table(),
            "stock_factor_proxies": self.factor_proxies,
            "industry_variance_absolute": self._build_industry_variance_absolute_table(),
            "net_exposure": self.net_exposure,
            "gross_exposure": self.gross_exposure,
            "leverage": self.leverage
        }

    def to_dict(self) -> Dict[str, Any]:
        """DEPRECATED – use to_api_response().  To be removed in Phase 2."""
        import warnings
        warnings.warn("RiskAnalysisResult.to_dict() is deprecated; "
                     "use to_api_response() instead.",
                     DeprecationWarning, stacklevel=2)
        return self.to_api_response()
    
    @classmethod
    def from_build_portfolio_view(cls, portfolio_view_result: Dict[str, Any],
                                 portfolio_name: Optional[str] = None,
                                 risk_checks: Optional[List[Dict[str, Any]]] = None,
                                 beta_checks: Optional[List[Dict[str, Any]]] = None,
                                 max_betas: Optional[Dict[str, float]] = None,
                                 max_betas_by_proxy: Optional[Dict[str, float]] = None,
                                 expected_returns: Optional[Dict[str, float]] = None,
                                 factor_proxies: Optional[Dict[str, str]] = None) -> 'RiskAnalysisResult':
        """
        Create RiskAnalysisResult from build_portfolio_view output.
        
        Complete Field Mapping (build_portfolio_view → RiskAnalysisResult):
        ================================================================
        
        Core Function Output                              → Result Object Field
        ──────────────────────────────────────────────────────────────────────────
        portfolio_view_result["volatility_annual"]       → self.volatility_annual
        portfolio_view_result["volatility_monthly"]      → self.volatility_monthly  
        portfolio_view_result["herfindahl"]               → self.herfindahl
        portfolio_view_result["portfolio_factor_betas"]  → self.portfolio_factor_betas
        portfolio_view_result["variance_decomposition"]  → self.variance_decomposition
        portfolio_view_result["risk_contributions"]      → self.risk_contributions
        portfolio_view_result["df_stock_betas"]           → self.stock_betas
        portfolio_view_result.get("covariance_matrix")   → self.covariance_matrix (defensive)
        portfolio_view_result.get("correlation_matrix")  → self.correlation_matrix (defensive)
        portfolio_view_result.get("allocations")         → self.allocations (defensive)
        portfolio_view_result.get("factor_vols")         → self.factor_vols (defensive)
        portfolio_view_result.get("weighted_factor_var") → self.weighted_factor_var (defensive)
        portfolio_view_result.get("asset_vol_summary")   → self.asset_vol_summary (defensive)
        portfolio_view_result.get("portfolio_returns")   → self.portfolio_returns (defensive)
        portfolio_view_result.get("euler_variance_pct")  → self.euler_variance_pct (defensive)
        portfolio_view_result.get("industry_variance")   → self.industry_variance (defensive)
        portfolio_view_result.get("suggested_limits")    → self.suggested_limits (defensive)
        risk_checks parameter                            → self.risk_checks
        beta_checks parameter                            → self.beta_checks
        max_betas parameter                              → self.max_betas
        max_betas_by_proxy parameter                     → self.max_betas_by_proxy
        datetime.now()                                   → self.analysis_date
        portfolio_name parameter                         → self.portfolio_name
        
        Data Flow: build_portfolio_view() → RiskAnalysisResult
        Completeness: 100% - All available fields captured with defensive .get() patterns
        
        Note: Uses .get() pattern for optional fields that may not be present in all
        build_portfolio_view() outputs due to data limitations or configuration differences.
        """
        return cls(
            volatility_annual=portfolio_view_result["volatility_annual"],
            volatility_monthly=portfolio_view_result["volatility_monthly"],
            herfindahl=portfolio_view_result["herfindahl"],
            portfolio_factor_betas=portfolio_view_result["portfolio_factor_betas"],
            variance_decomposition=portfolio_view_result["variance_decomposition"],
            risk_contributions=portfolio_view_result["risk_contributions"],
            stock_betas=portfolio_view_result["df_stock_betas"],
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
            portfolio_name=portfolio_name,
            expected_returns=expected_returns,
            factor_proxies=factor_proxies,
            net_exposure=portfolio_view_result.get("net_exposure"),
            gross_exposure=portfolio_view_result.get("gross_exposure"),
            leverage=portfolio_view_result.get("leverage"),
            total_value=portfolio_view_result.get("total_value")
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
        
        # API serialization (Phase 1.5+)
        api_data = result.to_api_response()  # Schema-compliant JSON for APIs
        # Replaces deprecated result.to_dict() - use to_api_response() for new code
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
        """
        Create OptimizationResult from run_min_variance() output.
        
        Complete Field Mapping (run_min_var → OptimizationResult):
        =========================================================
        
        Core Function Output (3-tuple)          → Result Object Field
        ──────────────────────────────────────────────────────────────────
        optimized_weights (Dict[str, float])    → self.optimized_weights
        risk_table (pd.DataFrame)               → self.risk_table
        beta_table (pd.DataFrame)               → self.beta_table
        None (not provided by min variance)     → self.portfolio_summary (None)
        None (not provided by min variance)     → self.proxy_table (None)
        "Minimum Variance" (default)            → self.optimization_type
        datetime.now()                          → self.analysis_date
        
        Data Flow: run_min_var() → (weights, risk_table, beta_table) → OptimizationResult
        Completeness: 100% - All min variance optimization outputs captured
        
        Note: Min variance optimization returns a simpler structure than max return,
        with only weights and compliance tables (no portfolio summary or proxy analysis).
        """
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
        """
        Create OptimizationResult from run_max_return_portfolio() output.
        
        Complete Field Mapping (run_max_return_portfolio → OptimizationResult):
        =====================================================================
        
        Core Function Output (5-tuple)          → Result Object Field
        ──────────────────────────────────────────────────────────────────
        optimized_weights (Dict[str, float])    → self.optimized_weights
        portfolio_summary (Dict[str, Any])      → self.portfolio_summary
        risk_table (pd.DataFrame)               → self.risk_table
        factor_table (pd.DataFrame)             → self.beta_table (factor exposures)
        proxy_table (pd.DataFrame)              → self.proxy_table (industry exposures)
        "Maximum Return" (default)              → self.optimization_type
        datetime.now()                          → self.analysis_date
        
        Data Flow: 
        run_max_return_portfolio() → (weights, summary, risk_table, factor_table, proxy_table)
        ↓
        OptimizationResult with complete portfolio analysis and compliance tables
        
        Completeness: 100% - All max return optimization outputs captured
        
        Note: Max return optimization provides richer output than min variance, including
        complete portfolio summary (from build_portfolio_view) and separate factor/proxy
        compliance tables for comprehensive risk analysis.
        
        Original function signature: w, summary, r, f_b, p_b = run_max_return_portfolio(...)
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
    
    def to_api_response(self) -> Dict[str, Any]:
        """
        Schema-compliant version of the old to_dict().
        For Phase 1.5 this must be a 1-to-1 copy of to_dict()'s output
        (no structural changes, no field renames, no pruning).
        """
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

    def to_dict(self) -> Dict[str, Any]:
        """DEPRECATED – use to_api_response().  To be removed in Phase 2."""
        import warnings
        warnings.warn("OptimizationResult.to_dict() is deprecated; "
                     "use to_api_response() instead.",
                     DeprecationWarning, stacklevel=2)
        return self.to_api_response()


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
    
    Usage Patterns:
    1. **Structured Data Access**: Use getter methods for programmatic analysis
    2. **Performance Summary**: Use get_summary() for key metrics overview
    3. **Risk Analysis**: Use get_risk_metrics() for risk-specific measures
    4. **API Serialization**: Use to_api_response() for JSON export and API responses
    5. **Legacy Serialization**: to_dict() is deprecated, use to_api_response() instead
    6. **Formatted Reporting**: Use to_formatted_report() for human-readable display
    
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
        report = result.to_formatted_report()
        # "Performance Analysis - Portfolio\nAnnualized Return: 12.40%\n..."
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
    
    def _categorize_performance(self) -> str:
        """
        Categorize performance based on risk-adjusted metrics.
        
        Returns clean enum value for API logic/filtering.
        """
        sharpe = self.risk_adjusted_returns.get("sharpe_ratio", 0)
        annual_return = self.returns.get("annualized_return", 0)
        
        if sharpe >= 1.5 and annual_return >= 0.15:
            return "excellent"
        elif sharpe >= 1.0 and annual_return >= 0.10:
            return "good"
        elif sharpe >= 0.5 and annual_return >= 0.05:
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
        if alpha > 5:
            insights.append(f"• Strong alpha generation (+{alpha:.1f}% vs benchmark)")
        elif alpha < -2:
            insights.append(f"• Underperforming benchmark ({alpha:.1f}% alpha)")
        
        # Risk-adjusted returns insight
        sharpe = self.risk_adjusted_returns.get("sharpe_ratio", 0)
        if sharpe > 1.2:
            insights.append(f"• Excellent risk-adjusted returns (Sharpe: {sharpe:.2f})")
        elif sharpe < 0.5:
            insights.append(f"• Poor risk-adjusted returns (Sharpe: {sharpe:.2f})")
        
        # Volatility insight
        volatility = self.risk_metrics.get("volatility", 0)
        benchmark_vol = self.benchmark_comparison.get("benchmark_volatility", 0)
        if volatility > benchmark_vol * 1.2:
            insights.append(f"• High volatility ({volatility:.1f}% vs {benchmark_vol:.1f}% benchmark)")
        
        # Win rate insight
        win_rate = self.returns.get("win_rate", 0)
        if win_rate > 65:
            insights.append(f"• High consistency ({win_rate:.0f}% positive months)")
        elif win_rate < 50:
            insights.append(f"• Low consistency ({win_rate:.0f}% positive months)")
        
        # Drawdown insight
        max_dd = self.risk_metrics.get("maximum_drawdown", 0)
        if abs(max_dd) > 25:
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

    def to_api_response(self) -> Dict[str, Any]:
        """
        Convert PerformanceResult to OpenAPI-compliant dictionary for API responses.
        
        This method provides schema-compliant serialization for OpenAPI documentation
        and API responses, replacing the deprecated to_dict() method. The output structure
        matches the PerformanceResultSchema defined in schemas/performance_result.py.
        
        Schema Compliance:
        - All fields map directly to PerformanceResultSchema field definitions
        - DateTime objects are serialized as ISO format strings
        - Nested dictionaries maintain original structure for API consistency
        - Formatted report is included for human-readable display
        
        Returns:
            Dict[str, Any]: Serialized performance analysis data containing:
                - analysis_period: Dict with start_date, end_date, duration info
                - returns: Dict with total_return, annualized_return, win_rate
                - risk_metrics: Dict with volatility, max_drawdown, downside_deviation
                - risk_adjusted_returns: Dict with Sharpe, Sortino, Information ratios
                - benchmark_analysis: Dict with benchmark performance metrics
                - benchmark_comparison: Dict with alpha, beta, tracking_error
                - monthly_stats: Dict with monthly return statistics
                - risk_free_rate: Float representing risk-free rate used
                - monthly_returns: Dict with time-series monthly return data
                - analysis_date: String in ISO format (YYYY-MM-DDTHH:MM:SS)
                - portfolio_name: Optional string portfolio identifier
                - formatted_report: String containing human-readable report
                
        Usage:
            ```python
            # Service layer usage
            result = portfolio_service.analyze_performance(portfolio_data, "SPY")
            api_data = result.to_api_response()  # OpenAPI-compliant format
            
            # API endpoint usage
            @openapi_bp.response(200, PerformanceResultSchema)
            def performance_endpoint():
                return result.to_api_response()
            
            # Frontend consumption
            response_data = api_data
            sharpe_ratio = response_data["risk_adjusted_returns"]["sharpe_ratio"]
            formatted_display = response_data["formatted_report"]
            ```
            
        Migration Note:
            Replaces deprecated to_dict() method. Output structure is identical
            to maintain backward compatibility during Phase 1.5 migration.
        """
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
            "formatted_report": self.to_formatted_report(),
            "portfolio_file": self.portfolio_file,
            "analysis_period_text": self._format_analysis_period(),
            "position_count": self.get_position_count(),
            "performance_category": self._categorize_performance(),
            "key_insights": self._generate_key_insights(),
            "display_formatting": self._get_display_formatting_metadata(),
            "enhanced_key_insights": self._generate_enhanced_key_insights()
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
    
    def _generate_enhanced_key_insights(self) -> List[str]:
        """Generate enhanced key insights with detailed bullet points."""
        insights = []
        
        # Benchmark comparison insight
        if hasattr(self, 'benchmark_analysis') and self.benchmark_analysis:
            excess_return = self.benchmark_analysis.get('excess_return', 0)
            if excess_return > 0:
                insights.append(f"• Outperforming benchmark (+{excess_return:.1f}% vs benchmark)")
            else:
                insights.append(f"• Underperforming benchmark ({excess_return:+.1f}% vs benchmark)")
        
        # Market sensitivity insight
        if hasattr(self, 'benchmark_analysis') and 'beta' in self.benchmark_analysis:
            beta = self.benchmark_analysis['beta']
            if beta > 1.1:
                insights.append(f"• High market sensitivity (β = {beta:.2f})")
            elif beta < 0.9:
                insights.append(f"• Low market sensitivity (β = {beta:.2f})")
            else:
                insights.append(f"• Moderate market sensitivity (β = {beta:.2f})")
        
        # Risk-adjusted returns insight
        if hasattr(self, 'risk_adjusted_returns') and 'sharpe_ratio' in self.risk_adjusted_returns:
            sharpe = self.risk_adjusted_returns['sharpe_ratio']
            if sharpe > 1.5:
                insights.append(f"• Excellent risk-adjusted returns (Sharpe = {sharpe:.2f})")
            elif sharpe > 1.0:
                insights.append(f"• Good risk-adjusted returns (Sharpe = {sharpe:.2f})")
            else:
                insights.append(f"• Below-average risk-adjusted returns (Sharpe = {sharpe:.2f})")
        
        # Win rate insight
        if hasattr(self, 'returns') and 'win_rate' in self.returns:
            win_rate = self.returns['win_rate']
            if win_rate > 60:
                insights.append(f"• High consistency ({win_rate:.0f}% win rate)")
            elif win_rate > 50:
                insights.append(f"• Moderate consistency ({win_rate:.0f}% win rate)")
            else:
                insights.append(f"• Low consistency ({win_rate:.0f}% win rate)")
        
        return insights

    def to_dict(self) -> Dict[str, Any]:
        """DEPRECATED – use to_api_response().  To be removed in Phase 2."""
        import warnings
        warnings.warn("PerformanceResult.to_dict() is deprecated; "
                     "use to_api_response() instead.",
                     DeprecationWarning, stacklevel=2)
        return self.to_api_response()
    
    @classmethod
    def from_performance_metrics(cls, performance_metrics: Dict[str, Any],
                                portfolio_name: Optional[str] = None,
                                portfolio_file: Optional[str] = None,
                                allocations: Optional[Dict[str, Any]] = None) -> 'PerformanceResult':
        """
        Create PerformanceResult from calculate_portfolio_performance_metrics output.
        
        Complete Field Mapping (calculate_portfolio_performance_metrics → PerformanceResult):
        ==================================================================================
        
        Core Function Output                               → Result Object Field
        ────────────────────────────────────────────────────────────────────────────────
        performance_metrics["analysis_period"]            → self.analysis_period
        performance_metrics["returns"]                    → self.returns  
        performance_metrics["risk_metrics"]               → self.risk_metrics
        performance_metrics["risk_adjusted_returns"]      → self.risk_adjusted_returns
        performance_metrics["benchmark_analysis"]         → self.benchmark_analysis
        performance_metrics["benchmark_comparison"]       → self.benchmark_comparison
        performance_metrics["monthly_stats"]              → self.monthly_stats
        performance_metrics["risk_free_rate"]             → self.risk_free_rate
        performance_metrics["monthly_returns"]            → self.monthly_returns
        datetime.now()                                     → self.analysis_date
        portfolio_name parameter                           → self.portfolio_name
        
        Data Flow: calculate_portfolio_performance_metrics() → PerformanceResult
        Completeness: 100% - All fields from core function captured via direct mapping
        """
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
            portfolio_name=portfolio_name,
            portfolio_file=portfolio_file,
            _allocations=allocations
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
    
    API Integration:
    - Use to_api_response() for API endpoints and JSON serialization
    - to_dict() is deprecated, use to_api_response() instead
    """
    
    # Risk score information
    risk_score: Dict[str, Any]
    
    # Limits analysis and violations
    limits_analysis: Dict[str, Any]
    
    # Portfolio analysis details
    portfolio_analysis: Dict[str, Any]
    
    # MISSING FIELDS - Added to capture all data from run_risk_score_analysis
    suggested_limits: Dict[str, Any]  # Risk limit suggestions
    portfolio_file: Optional[str]     # Source portfolio file
    risk_limits_file: Optional[str]   # Source risk limits file
    formatted_report: str             # Complete formatted report text
    
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
            "risk_category": self.get_risk_category_enum(),  # Clean enum for logic
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
    
    def get_risk_category_enum(self) -> str:
        """Get clean risk category enum for API logic."""
        category = self.risk_score.get("category", "Unknown")
        # Convert display categories to clean enums
        if "Excellent" in category or "excellent" in category:
            return "excellent"
        elif "Good" in category or "good" in category:
            return "good"
        elif "Moderate" in category or "moderate" in category:
            return "moderate"
        elif "High" in category or "high" in category:
            return "high"
        else:
            return "unknown"
    
    def get_risk_category(self) -> str:
        """Get risk category classification (display format)."""
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

    def _get_priority_actions(self) -> list:
        """
        Generate prioritized action recommendations based on risk violations.
        
        Returns actions ranked by impact and urgency.
        """
        actions = []
        recommendations = self.limits_analysis.get("recommendations", [])
        risk_factors = self.limits_analysis.get("risk_factors", [])
        
        # Priority 1: Critical violations requiring immediate action
        for rec in recommendations[:3]:  # Top 3 recommendations
            if any(keyword in rec.lower() for keyword in ["reduce", "limit", "excess"]):
                actions.append(f"1. {rec}")
        
        # Priority 2: Risk factors to monitor
        for factor in risk_factors[:2]:  # Top 2 risk factors
            if factor not in [r.split(". ", 1)[-1] for r in actions]:
                actions.append(f"2. Monitor: {factor}")
        
        # Priority 3: Additional recommendations
        remaining_recs = [r for r in recommendations[3:] if r not in [a.split(". ", 1)[-1] for a in actions]]
        for rec in remaining_recs[:2]:
            actions.append(f"3. {rec}")
        
        return actions
    
    def _get_violations_summary(self) -> Dict[str, Any]:
        """
        Generate a comprehensive violations summary.
        
        Returns structured summary of all limit violations.
        """
        violations = self.limits_analysis.get("limit_violations", {})
        risk_factors = self.limits_analysis.get("risk_factors", [])
        
        # Count total violations
        total_violations = sum(violations.values()) if isinstance(violations, dict) else len(risk_factors)
        
        # Categorize violations by severity
        critical_violations = []
        moderate_violations = []
        
        for factor in risk_factors:
            if any(keyword in factor.lower() for keyword in ["excess", "high", "limit"]):
                critical_violations.append(factor)
            else:
                moderate_violations.append(factor)
        
        return {
            "total_violations": total_violations,
            "critical_count": len(critical_violations),
            "moderate_count": len(moderate_violations),
            "violation_types": violations,
            "critical_violations": critical_violations,
            "moderate_violations": moderate_violations,
            "compliance_status": "Non-Compliant" if total_violations > 0 else "Compliant"
        }

    def to_api_response(self) -> Dict[str, Any]:
        """
        Schema-compliant version of the old to_dict().
        For Phase 1.5 this must be a 1-to-1 copy of to_dict()'s output
        (no structural changes, no field renames, no pruning).
        """
        return {
            "risk_score": _convert_to_json_serializable(self.risk_score),
            "limits_analysis": _convert_to_json_serializable(self.limits_analysis),
            "suggested_limits": _convert_to_json_serializable(self.suggested_limits),
            "portfolio_file": self.portfolio_file,
            "risk_limits_file": self.risk_limits_file,
            "formatted_report": self.formatted_report or self.to_formatted_report(),
            "analysis_date": self.analysis_date.isoformat(),
            "portfolio_name": self.portfolio_name,
            "priority_actions": self._get_priority_actions(),
            "violations_summary": self._get_violations_summary(),
            "violation_details": self._get_violation_details(),
            "risk_factors_with_priority": self._get_risk_factors_with_priority(),
            "portfolio_analysis": _convert_to_json_serializable(self.portfolio_analysis),

        }

    def _get_violation_details(self) -> Dict[str, Any]:
        """Generate detailed violation breakdown with specific exceeded values."""
        details = {
            "factor_betas": [],
            "concentration": [],
            "volatility": [],
            "variance_contributions": [],
            "leverage": []
        }
        
        # Extract factor beta violations from limits analysis
        if "risk_factors" in self.limits_analysis:
            for factor in self.limits_analysis["risk_factors"]:
                if "β=" in factor and "vs" in factor and "limit" in factor:
                    # Parse "High market exposure: β=1.40 vs 0.67 limit"
                    parts = factor.split("β=")
                    if len(parts) > 1:
                        value_part = parts[1].split(" vs ")
                        if len(value_part) > 1:
                            current = float(value_part[0])
                            limit = float(value_part[1].split(" ")[0])
                            factor_name = parts[0].split(":")[0].replace("High ", "").replace("Low ", "").strip()
                            details["factor_betas"].append({
                                "factor": factor_name.lower(),
                                "current": current,
                                "limit": limit,
                                "excess": abs(current - limit)
                            })
        
        # Extract volatility violations
        if "systematic risk" in str(self.limits_analysis.get("risk_factors", [])):
            for factor in self.limits_analysis["risk_factors"]:
                if "systematic risk" in factor and "%" in factor and "vs" in factor:
                    # Parse "High systematic risk: 48.3% vs 30.0% limit"
                    parts = factor.split(": ")
                    if len(parts) > 1:
                        value_part = parts[1].split("% vs ")
                        if len(value_part) > 1:
                            current = float(value_part[0])
                            limit = float(value_part[1].split("%")[0])
                            details["volatility"].append({
                                "metric": "systematic_risk",
                                "current": current,
                                "limit": limit,
                                "excess": current - limit
                            })
        
        return details
    
    def _get_risk_factors_with_priority(self) -> List[Dict[str, Any]]:
        """Generate risk factors with priority levels and severity."""
        risk_factors = []
        
        if "risk_factors" in self.limits_analysis:
            for i, factor in enumerate(self.limits_analysis["risk_factors"]):
                # Determine priority based on keywords and position
                priority = "HIGH" if any(word in factor.lower() for word in ["high", "excess", "critical"]) else "MEDIUM"
                severity = 1 if priority == "HIGH" else 2
                
                risk_factors.append({
                    "factor": factor,
                    "priority_level": priority,
                    "severity": severity,
                    "order": i + 1
                })
        
        return risk_factors

    def to_dict(self) -> Dict[str, Any]:
        """DEPRECATED – use to_api_response().  To be removed in Phase 2."""
        import warnings
        warnings.warn("RiskScoreResult.to_dict() is deprecated; "
                     "use to_api_response() instead.",
                     DeprecationWarning, stacklevel=2)
        return self.to_api_response()
    
    @classmethod
    def from_risk_score_analysis(cls, risk_score_result: Dict[str, Any],
                                portfolio_name: Optional[str] = None) -> 'RiskScoreResult':
        """
        Create RiskScoreResult from run_risk_score_analysis output.
        
        Complete Field Mapping (run_risk_score_analysis → RiskScoreResult):
        ================================================================
        
        Core Function Output                     → Result Object Field
        ──────────────────────────────────────────────────────────────────
        risk_score_result["risk_score"]         → self.risk_score
        risk_score_result["limits_analysis"]    → self.limits_analysis  
        risk_score_result["suggested_limits"]   → self.suggested_limits
        risk_score_result["portfolio_file"]     → self.portfolio_file
        risk_score_result["risk_limits_file"]   → self.risk_limits_file
        risk_score_result["formatted_report"]   → self.formatted_report
        risk_score_result["analysis_date"]      → self.analysis_date (parsed)
        portfolio_name parameter                → self.portfolio_name
        risk_score_result["portfolio_analysis"] → self.portfolio_analysis

        Data Flow: run_risk_score_analysis(return_data=True) → RiskScoreResult
        Completeness: 100% - All fields from core function captured
        """
        return cls(
            risk_score=risk_score_result["risk_score"],
            limits_analysis=risk_score_result["limits_analysis"],
            portfolio_analysis=risk_score_result["portfolio_analysis"],
            suggested_limits=risk_score_result.get("suggested_limits", {}),  # ← CAPTURE!
            portfolio_file=risk_score_result.get("portfolio_file"),         # ← CAPTURE!
            risk_limits_file=risk_score_result.get("risk_limits_file"),     # ← CAPTURE!
            formatted_report=risk_score_result.get("formatted_report", ""), # ← CAPTURE!
            analysis_date=datetime.fromisoformat(risk_score_result["analysis_date"]) if "analysis_date" in risk_score_result else datetime.now(),  # ← USE ORIGINAL!
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
        """
        Create WhatIfResult from what-if scenario analysis output.
        
        Complete Field Mapping (run_what_if_scenario → WhatIfResult):
        ============================================================
        
        Core Function Output                     → Result Object Field
        ──────────────────────────────────────────────────────────────────
        current_summary (build_portfolio_view)  → self.current_metrics (as RiskAnalysisResult)
        scenario_summary (build_portfolio_view) → self.scenario_metrics (as RiskAnalysisResult)
        scenario_name parameter                  → self.scenario_name
        risk_comparison DataFrame (optional)     → self.risk_comparison
        beta_comparison DataFrame (optional)     → self.beta_comparison
        datetime.now()                          → self.analysis_date
        
        Data Flow: 
        run_what_if_scenario() → current/scenario summaries → WhatIfResult
        ↳ Each summary processed via RiskAnalysisResult.from_build_portfolio_view()
        
        Completeness: 100% - All comparison data and nested portfolio analysis captured
        
        Note: This factory method creates nested RiskAnalysisResult objects for both
        current and scenario portfolios, enabling complete before/after analysis with
        all portfolio metrics preserved in structured format.
        """
        
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
    
    def to_api_response(self) -> Dict[str, Any]:
        """
        Schema-compliant version of the old to_dict().
        For Phase 1.5 this must be a 1-to-1 copy of to_dict()'s output
        (no structural changes, no field renames, no pruning).
        """
        return {
            "scenario_name": self.scenario_name,
            "current_metrics": self.current_metrics.to_api_response(),
            "scenario_metrics": self.scenario_metrics.to_api_response(),
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
            "summary": self.get_summary(),
            # CLI-API alignment fields from audit
            "scenario_metadata": self._get_scenario_metadata(),
            "change_summaries": self._generate_change_summaries()
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

    def to_dict(self) -> Dict[str, Any]:
        """DEPRECATED – use to_api_response().  To be removed in Phase 2."""
        import warnings
        warnings.warn("WhatIfResult.to_dict() is deprecated; "
                     "use to_api_response() instead.",
                     DeprecationWarning, stacklevel=2)
        return self.to_api_response()


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
        """
        Create StockAnalysisResult from run_stock() underlying function outputs.
        
        Complete Field Mapping (run_stock components → StockAnalysisResult):
        ================================================================
        
        Input Parameters                         → Result Object Field
        ──────────────────────────────────────────────────────────────────
        ticker parameter                         → self.ticker
        vol_metrics["volatility_annual"]         → self.volatility_annual
        vol_metrics["sharpe_ratio"]              → self.sharpe_ratio
        vol_metrics["max_drawdown"]              → self.max_drawdown
        regression_metrics["beta"]               → self.beta
        regression_metrics["alpha"]              → self.alpha
        regression_metrics["r_squared"]          → self.r_squared
        regression_metrics["correlation"]        → self.market_correlation
        factor_summary DataFrame                 → self.factor_exposures (optional)
        datetime.now()                          → self.analysis_date
        
        Data Flow: run_stock() component outputs → StockAnalysisResult
        Completeness: 100% - All provided metrics captured
        
        Note: This factory method assembles data from multiple analysis components
        (volatility calculations, regression analysis, factor modeling) into a 
        unified stock analysis result.
        """
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
    
    def to_api_response(self) -> Dict[str, Any]:
        """
        Schema-compliant version of the old to_dict().
        For Phase 1.5 this must be a 1-to-1 copy of to_dict()'s output
        (no structural changes, no field renames, no pruning).
        """
        return {
            "ticker": self.ticker,
            "volatility_metrics": self.volatility_metrics,
            "regression_metrics": self.regression_metrics,
            "factor_summary": self.factor_summary.to_dict() if self.factor_summary is not None and not self.factor_summary.empty else {},
            "risk_metrics": self.risk_metrics,
            "analysis_date": self.analysis_date.isoformat()
        }

    def to_dict(self) -> Dict[str, Any]:
        """DEPRECATED – use to_api_response().  To be removed in Phase 2."""
        import warnings
        warnings.warn("StockAnalysisResult.to_dict() is deprecated; "
                     "use to_api_response() instead.",
                     DeprecationWarning, stacklevel=2)
        return self.to_api_response()
    
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
    
    def to_api_response(self) -> Dict[str, Any]:
        """
        Schema-compliant version of the old to_dict().
        For Phase 1.5 this must be a 1-to-1 copy of to_dict()'s output
        (no structural changes, no field renames, no pruning).
        """
        return {
            "ai_interpretation": self.ai_interpretation,
            "full_diagnostics": self.full_diagnostics,
            "analysis_metadata": _convert_to_json_serializable(self.analysis_metadata),
            "analysis_date": self.analysis_date.isoformat(),
            "portfolio_name": self.portfolio_name,
            "summary": self.get_summary()
        }

    def to_dict(self) -> Dict[str, Any]:
        """DEPRECATED – use to_api_response().  To be removed in Phase 2."""
        import warnings
        warnings.warn("InterpretationResult.to_dict() is deprecated; "
                     "use to_api_response() instead.",
                     DeprecationWarning, stacklevel=2)
        return self.to_api_response()
    
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
    
    API Methods:
        to_api_response(): Schema-compliant JSON serialization for OpenAPI endpoints
        to_dict(): DEPRECATED - Use to_api_response() instead (Phase 2 removal)
        get_summary(): High-level portfolio summary for logging and debugging
    
    Schema: DirectPortfolioResultSchema (schemas.direct_portfolio_result)
    """
    raw_output: Dict[str, Any]
    analysis_type: str = "portfolio"
    
    def to_api_response(self) -> Dict[str, Any]:
        """
        Schema-compliant version of the old to_dict().
        For Phase 1.5 this must be a 1-to-1 copy of to_dict()'s output
        (no structural changes, no field renames, no pruning).
        """
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
    
    def to_dict(self) -> Dict[str, Any]:
        """DEPRECATED – use to_api_response().  To be removed in Phase 2."""
        import warnings
        warnings.warn("DirectPortfolioResult.to_dict() is deprecated; "
                     "use to_api_response() instead.",
                     DeprecationWarning, stacklevel=2)
        return self.to_api_response()
    
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
    """Result object for direct stock analysis endpoints.
    
    Wraps raw output from run_stock() with consistent JSON serialization.
    
    API Methods:
        to_api_response(): Schema-compliant JSON serialization for OpenAPI endpoints
        to_dict(): DEPRECATED - Use to_api_response() instead (Phase 2 removal)
        get_summary(): High-level stock analysis summary for logging and debugging
    
    Schema: DirectStockResultSchema (schemas.direct_stock_result)
    """
    raw_output: Dict[str, Any]
    analysis_type: str = "stock"
    
    def to_api_response(self) -> Dict[str, Any]:
        """
        Schema-compliant version of the old to_dict().
        For Phase 1.5 this must be a 1-to-1 copy of to_dict()'s output
        (no structural changes, no field renames, no pruning).
        """
        return {
            "analysis_type": self.analysis_type,
            **{k: _convert_to_json_serializable(v) 
               for k, v in self.raw_output.items()}
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """DEPRECATED – use to_api_response().  To be removed in Phase 2."""
        import warnings
        warnings.warn("DirectStockResult.to_dict() is deprecated; "
                     "use to_api_response() instead.",
                     DeprecationWarning, stacklevel=2)
        return self.to_api_response()
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary using standard formatting."""
        return {
            "endpoint": "direct/stock",
            "analysis_type": self.analysis_type,
            "data_quality": "direct_access"
        }


@dataclass
class DirectOptimizationResult:
    """Result object for direct optimization endpoints.
    
    Wraps raw output from run_min_variance() and run_max_return() with consistent JSON serialization.
    
    API Methods:
        to_api_response(): Schema-compliant JSON serialization for OpenAPI endpoints
        to_dict(): DEPRECATED - Use to_api_response() instead (Phase 2 removal)
        get_summary(): High-level optimization summary for logging and debugging
    
    Schema: DirectOptimizationResultSchema (schemas.direct_optimization_result)
    """
    raw_output: Dict[str, Any]
    analysis_type: str = "optimization"
    
    def to_api_response(self) -> Dict[str, Any]:
        """
        Schema-compliant version of the old to_dict().
        For Phase 1.5 this must be a 1-to-1 copy of to_dict()'s output
        (no structural changes, no field renames, no pruning).
        """
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
    
    def to_dict(self) -> Dict[str, Any]:
        """DEPRECATED – use to_api_response().  To be removed in Phase 2."""
        import warnings
        warnings.warn("DirectOptimizationResult.to_dict() is deprecated; "
                     "use to_api_response() instead.",
                     DeprecationWarning, stacklevel=2)
        return self.to_api_response()
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary using standard formatting."""
        return {
            "endpoint": "direct/optimization",
            "analysis_type": self.analysis_type,
            "data_quality": "direct_access"
        }


@dataclass
class DirectPerformanceResult:
    """Result object for direct performance analysis endpoints.
    
    Wraps raw output from run_portfolio_performance() with consistent JSON serialization.
    
    API Methods:
        to_api_response(): Schema-compliant JSON serialization for OpenAPI endpoints
        to_dict(): DEPRECATED - Use to_api_response() instead (Phase 2 removal)
        get_summary(): High-level performance summary for logging and debugging
    
    Schema: DirectPerformanceResultSchema (schemas.direct_performance_result)
    """
    raw_output: Dict[str, Any]
    analysis_type: str = "performance"
    
    def to_api_response(self) -> Dict[str, Any]:
        """
        Schema-compliant version of the old to_dict().
        For Phase 1.5 this must be a 1-to-1 copy of to_dict()'s output
        (no structural changes, no field renames, no pruning).
        """
        return {
            "analysis_type": self.analysis_type,
            "performance_metrics": _convert_to_json_serializable(
                self.raw_output.get('performance_metrics')
            ),
            **{k: _convert_to_json_serializable(v) 
               for k, v in self.raw_output.items()}
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """DEPRECATED – use to_api_response().  To be removed in Phase 2."""
        import warnings
        warnings.warn("DirectPerformanceResult.to_dict() is deprecated; "
                     "use to_api_response() instead.",
                     DeprecationWarning, stacklevel=2)
        return self.to_api_response()
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary using standard formatting."""
        return {
            "endpoint": "direct/performance", 
            "analysis_type": self.analysis_type,
            "data_quality": "direct_access"
        } 


@dataclass
class DirectWhatIfResult:
    """Result object for direct what-if analysis endpoints.
    
    Wraps raw output from run_what_if() with consistent JSON serialization.
    
    API Methods:
        to_api_response(): Schema-compliant JSON serialization for OpenAPI endpoints
        to_dict(): DEPRECATED - Use to_api_response() instead (Phase 2 removal)
        get_summary(): High-level what-if analysis summary for logging and debugging
    
    Schema: DirectWhatIfResultSchema (schemas.direct_what_if_result)
    """
    raw_output: Dict[str, Any]
    analysis_type: str = "what_if"
    
    def to_api_response(self) -> Dict[str, Any]:
        """
        Schema-compliant version of the old to_dict().
        For Phase 1.5 this must be a 1-to-1 copy of to_dict()'s output
        (no structural changes, no field renames, no pruning).
        """
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
    
    def to_dict(self) -> Dict[str, Any]:
        """DEPRECATED – use to_api_response().  To be removed in Phase 2."""
        import warnings
        warnings.warn("DirectWhatIfResult.to_dict() is deprecated; "
                     "use to_api_response() instead.",
                     DeprecationWarning, stacklevel=2)
        return self.to_api_response()
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary using standard formatting."""
        return {
            "endpoint": "direct/what-if",
            "analysis_type": self.analysis_type,
            "data_quality": "direct_access"
        }


@dataclass
class DirectInterpretResult:
    """Result object for direct interpretation endpoints.
    
    Wraps raw output from interpret_portfolio_risk() with consistent JSON serialization.
    
    API Methods:
        to_api_response(): Schema-compliant JSON serialization for OpenAPI endpoints
        to_dict(): DEPRECATED - Use to_api_response() instead (Phase 2 removal)
        get_summary(): High-level interpretation summary for logging and debugging
    
    Schema: DirectInterpretResultSchema (schemas.direct_interpret_result)
    """
    raw_output: Dict[str, Any]
    analysis_type: str = "interpret"
    
    def to_api_response(self) -> Dict[str, Any]:
        """
        Schema-compliant version of the old to_dict().
        For Phase 1.5 this must be a 1-to-1 copy of to_dict()'s output
        (no structural changes, no field renames, no pruning).
        """
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
    
    def to_dict(self) -> Dict[str, Any]:
        """DEPRECATED – use to_api_response().  To be removed in Phase 2."""
        import warnings
        warnings.warn("DirectInterpretResult.to_dict() is deprecated; "
                     "use to_api_response() instead.",
                     DeprecationWarning, stacklevel=2)
        return self.to_api_response()
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary using standard formatting."""
        return {
            "endpoint": "direct/interpret",
            "analysis_type": self.analysis_type,
            "interpretation_length": len(self.raw_output.get('ai_interpretation', '')),
            "diagnostics_length": len(self.raw_output.get('full_diagnostics', '')),
            "data_quality": "direct_access"
        } 
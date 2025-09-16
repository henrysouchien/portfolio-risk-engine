"""Result objects for structured service layer responses.

API Serialization Patterns:
    All result objects implement two serialization methods:
    
    • to_api_response() - Schema-compliant serialization for API endpoints
      Returns structured data matching the OpenAPI schema definitions.
      Use this method for all API responses to ensure schema compliance.
    
    • to_cli_report() - Human-readable formatted reports for CLI and Claude AI
      Returns formatted text reports with consistent styling and structure.

ASSET CLASS & RATE FACTOR EXTENSIONS:
    Enhanced RiskAnalysisResult with asset allocation breakdown and interest rate
    duration exposure:
    
    • asset_allocation field in API responses for frontend charts
    • Asset allocation section in CLI reports with formatted tables
    • Automatic categorization using SecurityTypeService asset class data
    • Color mapping for consistent UI presentation
    • New API field: effective_duration (abs years), derived from aggregated
      portfolio 'interest_rate' beta (key‑rate regression over monthly Treasury Δy)

Example Usage:
    # API response with asset allocation and effective duration
    result = analyze_portfolio(portfolio_data)
    api_data = result.to_api_response()
    # api_data['asset_allocation'] contains frontend-ready allocation breakdown
    # api_data['effective_duration'] contains portfolio duration in years (abs)
    
    # CLI report with asset allocation table
    cli_report = result.to_cli_report()
    # Contains "=== Asset Allocation ===" section with formatted table
"""

from typing import Dict, Any, Optional, List, Union, Tuple
import pandas as pd
from datetime import datetime, UTC
import json
import numpy as np
from dataclasses import dataclass
from utils.serialization import make_json_safe
from core.constants import get_asset_class_color, get_asset_class_display_name



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
    
    elif isinstance(obj, (np.bool_, pd.BooleanDtype, bool)):
        # Handle numpy/pandas booleans by converting to Python bool
        return bool(obj)
    
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
    """Recursively convert NaN values to None and handle boolean serialization for JSON."""
    if isinstance(obj, dict):
        return {k: _clean_nan_values(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_clean_nan_values(item) for item in obj]
    elif isinstance(obj, float) and (np.isnan(obj) or obj != obj):  # NaN check
        return None
    elif isinstance(obj, (np.bool_, pd.BooleanDtype)):  # Handle pandas/numpy booleans
        return bool(obj)
    elif hasattr(obj, 'item'):  # numpy scalar
        val = obj.item()
        if isinstance(val, float) and (np.isnan(val) or val != val):
            return None
        elif isinstance(val, (bool, np.bool_)):  # Handle boolean numpy scalars
            return bool(val)
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
        
        # Export for API response
        api_data = result.to_api_response()
        # {"volatility_annual": 0.185, "portfolio_factor_betas": {...}, ...}
        
        # Check compliance
        risk_violations = [check for check in result.risk_checks if not check["Pass"]]
        is_compliant = len(risk_violations) == 0
        ```
        
    Data Quality: All pandas objects are properly indexed and serializable for caching and API usage.
    Performance: Result creation ~10-50ms, formatted report generation ~5-10ms.

    Raw vs Normalized Checks:
        - The fields `risk_checks` and `beta_checks` mirror the CLI's internal tables for
          exact parity. They preserve original key casing and shapes used by the CLI.
          These are provided for backward compatibility and auditing.

        - For API consumers, prefer the normalized tables:
            • `risk_limit_violations_summary` – normalized version of risk limit checks
            • `beta_exposure_checks_table` – normalized version of beta exposure checks

          These normalized tables use consistent field names and are intended to be stable
          for programmatic consumption. The raw fields will remain during Phase 1.x and may
          be deprecated in Phase 2.
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
    
    # Industry-level variance analysis (RAW / nested)
    # Note: This preserves the raw nested structure returned by core computation:
    #   {
    #     "absolute": {industry -> variance},
    #     "percent_of_portfolio": {industry -> pct},
    #     "per_industry_group_beta": {industry -> beta}
    #   }
    # For API consumers, prefer the flattened fields produced by to_api_response():
    #   - industry_variance_absolute
    #   - industry_variance_percentage
    #   - industry_group_betas
    # The raw nested field is kept for parity/backward-compatibility and may be
    # deprecated in Phase 2 to remove duplication.
    industry_variance: Dict[str, Dict[str, float]]
    
    # Risk compliance checks (RAW / CLI-aligned)
    # Note: This preserves the CLI's original structure and key casing (e.g., 'Metric',
    # 'Actual', 'Limit', 'Pass'). Prefer using `risk_limit_violations_summary` for a
    # normalized schema in API responses.
    risk_checks: List[Dict[str, Any]]
    # Beta exposure checks (RAW / CLI-aligned)
    # Note: This preserves the CLI's original structure and key casing (e.g., 'factor',
    # 'portfolio_beta', 'max_allowed_beta', 'pass'). Prefer using
    # `beta_exposure_checks_table` for a normalized schema in API responses.
    beta_checks: List[Dict[str, Any]]
    
    # Beta limits (from calc_max_factor_betas)
    max_betas: Dict[str, float]
    max_betas_by_proxy: Dict[str, float]
    
    # Historical worst-case analysis data
    historical_analysis: Dict[str, Any]
    
    # Metadata
    analysis_date: datetime
    portfolio_name: Optional[str] = None
    
    # Additional fields for CLI-API parity
    # Analysis metadata and auxiliary context (optional; used by formatters)
    analysis_metadata: Optional[Dict[str, Any]] = None
    expected_returns: Optional[Dict[str, float]] = None
    factor_proxies: Optional[Dict[str, str]] = None
    
    # Portfolio exposure metrics (calculated from allocations)
    net_exposure: Optional[float] = None
    gross_exposure: Optional[float] = None
    leverage: Optional[float] = None
    total_value: Optional[float] = None
    dollar_exposure: Optional[Dict[str, float]] = None
    
    @property
    def portfolio_weights(self) -> Optional[Dict[str, float]]:
        """Extract just the portfolio weights from the allocations DataFrame"""
        if self.allocations is None:
            return None
        return self.allocations["Portfolio Weight"].to_dict()
    
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

    @property
    def effective_duration(self) -> float:
        """
        Portfolio effective duration in years (absolute value).

        Derived from the aggregated 'interest_rate' beta in portfolio_factor_betas.
        Returns 0.0 if unavailable.
        """
        try:
            ir_beta = float(self.portfolio_factor_betas.get("interest_rate", 0.0))
        except Exception:
            ir_beta = 0.0
        return abs(ir_beta)
    
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
        return self.industry_variance.get("absolute", {})

    def _build_asset_allocation_breakdown(self) -> List[Dict[str, Any]]:
        """
        Build asset allocation breakdown for frontend AssetAllocation component.
        
        Uses pre-calculated asset classes from analysis_metadata. This is pure formatting
        logic - no business logic or service calls in result objects.
        
        Returns:
            List[Dict]: Asset allocation breakdown for frontend charts
        """
        if not self.portfolio_weights:
            return []
        
        # Require pre-calculated asset classes - fail fast if missing
        asset_classes = getattr(self, 'analysis_metadata', {}).get('asset_classes', {})
        if not asset_classes:
            # Fail fast - don't hide missing data with fallback business logic
            return []  # Return empty, this is a real error that should be fixed in core analysis
        
        # Optional performance data for change/changeType
        perf_meta = (self.analysis_metadata or {}).get('asset_class_performance', {})
        perf_data = perf_meta.get('performance_data', {}) if isinstance(perf_meta, dict) else {}

        def _classify_change(val: float) -> str:
            if val is None:
                return "neutral"
            if val > 0.005:
                return "positive"
            if val < -0.005:
                return "negative"
            return "neutral"

        # Group by asset class and calculate aggregates
        asset_groups = {}
        total_value = self.total_value or 0
        
        for ticker, weight in self.portfolio_weights.items():
            asset_class = asset_classes.get(ticker)
            if not asset_class:
                continue  # Skip tickers without asset class classification
                
            dollar_value = weight * total_value
            
            if asset_class not in asset_groups:
                asset_groups[asset_class] = {
                    'total_weight': 0,
                    'total_value': 0,
                    'holdings': []
                }
            
            asset_groups[asset_class]['total_weight'] += weight
            asset_groups[asset_class]['total_value'] += dollar_value
            asset_groups[asset_class]['holdings'].append(ticker)
        
        # Build frontend-compatible array
        allocation_breakdown = []
        for asset_class, data in asset_groups.items():
            period_return = perf_data.get(asset_class)
            allocation_breakdown.append({
                # Keep category as canonical key (snake_case) for frontend adapters
                'category': asset_class,
                'percentage': round(data['total_weight'] * 100, 1),
                'value': f"${data['total_value']:,.0f}",
                'change': (f"{period_return:+.1%}" if isinstance(period_return, (int, float)) else "+0.0%"),
                'changeType': _classify_change(period_return if isinstance(period_return, (int, float)) else 0.0),
                'color': get_asset_class_color(asset_class),
                'holdings': data['holdings']
            })
        
        return sorted(allocation_breakdown, key=lambda x: x['percentage'], reverse=True)

    def _get_asset_class_color(self, asset_class: str) -> str:
        """Map asset classes to consistent UI colors using centralized constants"""
        from core.constants import get_asset_class_color
        return get_asset_class_color(asset_class)
    
    def _format_asset_allocation_table(self, allocation_data: List[Dict[str, Any]]) -> str:
        """Format asset allocation as CLI table for Claude AI and CLI users."""
        if not allocation_data:
            return "No asset allocation data available"
        
        lines = []
        lines.append("Asset Class      Allocation    Value        Change   Holdings")
        lines.append("-" * 75)
        
        for item in allocation_data:
            # Display friendly name in CLI even though API uses snake_case
            display_name = get_asset_class_display_name(item.get('category', 'unknown'))
            asset_class = display_name.ljust(15)
            percentage = f"{item['percentage']:>6.1f}%".ljust(12)
            value = str(item['value']).ljust(12)
            change_str = str(item.get('change', "+0.0%"))
            change = f"{change_str:>7}".ljust(9)
            holdings_count = f"({len(item['holdings'])} positions)"
            lines.append(f"{asset_class} {percentage} {value} {change} {holdings_count}")
            
            # Show top holdings for each asset class
            if len(item['holdings']) <= 3:
                holdings_str = ", ".join(item['holdings'])
            else:
                holdings_str = ", ".join(item['holdings'][:3]) + f", +{len(item['holdings'])-3} more"
            
            lines.append(f"                 └─ {holdings_str}")
            lines.append("")  # Blank line between asset classes
        
        return "\n".join(lines)

    def to_api_response(self) -> Dict[str, Any]:
        """
        Convert RiskAnalysisResult to comprehensive API response format.
        
        CONSUMER ANALYSIS:
        - Direct API: Uses full structured response for programmatic risk analysis
        - Claude/AI: Only uses formatted_report (ignores all structured data)
        - Frontend: Uses adapters to transform structured data for UI components
        
        RESPONSE STRUCTURE (30+ Risk Metrics):
        
        **Portfolio Composition:**
        - portfolio_weights: Dict[ticker, weight] - Raw portfolio allocations
        - dollar_exposure: Dict[ticker, dollar_amount] - Position dollar values  
        - target_allocations: Dict - Allocation table with Portfolio Weight, Equal Weight, Eq Diff
        - total_value, net_exposure, gross_exposure, leverage: Portfolio-level metrics
        
        **Risk Metrics:**
        - volatility_annual, volatility_monthly: Core volatility measures (float)
        - herfindahl: Concentration index (float, 0-1 scale)
        - risk_contributions: Dict[ticker, contribution] - Euler risk contributions per position
        
        **Factor Analysis:**
        - portfolio_factor_betas: Dict[factor, beta] - Portfolio factor exposures
        - stock_betas: Dict[ticker, Dict[factor, beta]] - Individual stock factor betas
        - variance_decomposition: {
            portfolio_variance: float,           # Total portfolio variance
            factor_variance: float,              # Systematic risk component
            idiosyncratic_variance: float,       # Stock-specific risk component
            factor_pct: float                    # Percentage of risk from factors
          }
        
        **Industry Analysis:**
        - industry_group_betas: Dict[industry, beta] - Industry exposure mapping
        - industry_variance_absolute: Dict[industry, variance] - Absolute industry risk
        - industry_variance_percentage: Dict[industry, pct] - Industry risk as % of portfolio
        - industry_variance: Dict (RAW) - Legacy nested object (prefer flattened fields above)
        
        **Risk Matrices (Large Objects):**
        - covariance_matrix: Dict[Dict] - Asset covariance matrix (N×N)
        - correlation_matrix: Dict[Dict] - Asset correlation matrix (N×N)
        
        **Compliance & Validation:**
        - risk_checks: List[Dict] (RAW) - Risk limit checks with original CLI formatting
        - beta_checks: List[Dict] (RAW) - Beta exposure checks with original CLI formatting
        - risk_limit_violations_summary: List[Dict] (NORMALIZED) - Structured violation data
        - beta_exposure_checks_table: List[Dict] (NORMALIZED) - Structured beta checks
        - max_betas: Dict[factor, threshold] - Maximum beta thresholds per factor
        - max_betas_by_proxy: Dict[proxy, threshold] - Maximum proxy beta thresholds
        
        **Technical Analysis:**
        - asset_vol_summary: Dict - Individual asset volatility summary
        - factor_vols: Dict - Factor volatility data
        - weighted_factor_var: Dict - Weighted factor variance contributions
        - portfolio_returns: Dict[date, return] - Historical portfolio returns time series
        - euler_variance_pct: Dict[ticker, pct] - Euler variance percentages per position
        
        **Metadata & Context:**
        - analysis_date: str (ISO-8601 UTC) - When analysis was performed
        - portfolio_name: str - Portfolio identifier
        - expected_returns: Dict[ticker, return] (Optional) - Expected return assumptions
        - stock_factor_proxies: Dict[str, str] (Optional) - Factor proxy mappings
        - historical_analysis: Dict - Historical performance analysis data
        
        **Human-Readable Output:**
        - formatted_report: str - Complete CLI-style text report (primary Claude/AI input)
        
        DATA QUALITY NOTES:
        - All timestamps are UTC and serialized via ISO-8601
        - Dictionaries derived from DataFrame/Series provide stable key ordering
        - NaN values converted to null for JSON compatibility
        - Large matrices (covariance/correlation) may impact response size
        
        BACKWARD COMPATIBILITY:
        - RAW fields (risk_checks, beta_checks, industry_variance) preserve original CLI formatting
        - NORMALIZED fields provide structured data for programmatic consumption
        - RAW fields maintained during Phase 1.x, may be deprecated in Phase 2
        
        Returns:
            Dict[str, Any]: Complete portfolio risk analysis with 30+ metrics and compliance data
        """
        # Compute effective duration if interest_rate factor present
        return {
            # Fields ordered to match CLI section sequence  
            "portfolio_weights": self.portfolio_weights,  # PORTFOLIO ALLOCATIONS (Raw weights)
            "dollar_exposure": self.dollar_exposure,  # DOLLAR EXPOSURE BY POSITION
            "target_allocations": _convert_to_json_serializable(self.allocations),  # TARGET ALLOCATIONS TABLE (Portfolio Weight, Equal Weight, Eq Diff)
            "total_value": self.total_value,  # TOTAL PORTFOLIO VALUE
            "net_exposure": self.net_exposure,  # NET EXPOSURE (sum of weights)
            "gross_exposure": self.gross_exposure,  # GROSS EXPOSURE (sum of abs(weights))
            "leverage": self.leverage,  # LEVERAGE (gross / net)
            "risk_contributions": _convert_to_json_serializable(self.risk_contributions),  # Risk Contributions
            "covariance_matrix": _convert_to_json_serializable(self.covariance_matrix),  # Covariance Matrix
            "correlation_matrix": _convert_to_json_serializable(self.correlation_matrix),  # Correlation Matrix
            "stock_betas": _convert_to_json_serializable(self.stock_betas),  # Per-Stock Factor Betas
            "portfolio_factor_betas": _convert_to_json_serializable(self.portfolio_factor_betas),  # Portfolio-Level Factor Betas
            "effective_duration": self.effective_duration,  # years (abs for intuitive display)
            "industry_group_betas": self._build_industry_group_betas_table(),  # Per-Industry Group Betas
            "asset_vol_summary": _convert_to_json_serializable(self.asset_vol_summary),  # Per-Asset Vol & Var
            "factor_vols": _convert_to_json_serializable(self.factor_vols),  # Factor Annual Volatilities (σ_i,f)
            "weighted_factor_var": _convert_to_json_serializable(self.weighted_factor_var),  # Weighted Factor Variance
            "variance_decomposition": _convert_to_json_serializable(self.variance_decomposition),  # Portfolio Variance Decomposition
            "factor_variance_absolute": self._build_factor_variance_absolute_table(),  # Factor Variance (absolute)
            "top_stock_variance_euler": self._build_top_stock_variance_euler_table(),  # Top Stock Variance (Euler %)
            "factor_variance_percentage": self._build_factor_variance_percentage_table(),  # Factor Variance (% of Portfolio, excluding industry)
            "industry_variance_absolute": self._build_industry_variance_absolute_table(),  # Industry Variance (absolute)
            "industry_variance_percentage": self._build_industry_variance_percentage_table(),  # Industry Variance (% of Portfolio)
            "risk_checks": _convert_to_json_serializable(self.risk_checks),  # Portfolio Risk Limit Checks
            "beta_checks": _convert_to_json_serializable(self.beta_checks),  # Beta Exposure Checks
            "volatility_annual": self.volatility_annual,  # Volatility Annual   
            "volatility_monthly": self.volatility_monthly,  # Volatility Monthly
            "herfindahl": self.herfindahl,  # Herfindahl Index
            "portfolio_returns": _convert_to_json_serializable(self.portfolio_returns),  # Portfolio Returns
            "euler_variance_pct": _convert_to_json_serializable(self.euler_variance_pct),  # Euler Variance Contribution by Stock
            "industry_variance": _convert_to_json_serializable(self.industry_variance),  # Industry Variance (absolute, percentage, and group betas) TODO: Figure out how to handle this (duplication)
            "max_betas": _convert_to_json_serializable(self.max_betas),  # Max Factor Beta
            "max_betas_by_proxy": _convert_to_json_serializable(self.max_betas_by_proxy),  # Max Sector Betas
            "historical_analysis": _convert_to_json_serializable(self.historical_analysis),  # Historical Worst-Case Analysis Data
            "analysis_metadata": {
                "analysis_date": self.analysis_date.isoformat(),  # Analysis Date
                "portfolio_name": self.portfolio_name,  # Portfolio Name
                "stock_factor_proxies": self.factor_proxies,  # Stock Factor Proxies
                "cash_positions": (self.analysis_metadata or {}).get("cash_positions"), # Cash Positions    
                "lookback_years": (self.analysis_metadata or {}).get("lookback_years"), # Lookback Years
                "total_positions": (self.analysis_metadata or {}).get("total_positions"), # Total Positions
                "active_positions": (self.analysis_metadata or {}).get("active_positions"), # Active Positions
                "expected_returns": self.expected_returns,  # EXPECTED RETURNS
                "asset_classes": (self.analysis_metadata or {}).get("asset_classes"),  # NEW: Asset class classifications
            },
            "asset_allocation": self._build_asset_allocation_breakdown(),  # NEW: Asset allocation breakdown for frontend charts
            "formatted_report": self.to_cli_report(),  # Formatted Report
            "risk_limit_violations_summary": self._get_risk_limit_violations_summary(),  # Risk Limit Violations Summary
            "beta_exposure_checks_table": self._get_beta_exposure_checks_table()  # Beta Exposure Checks Formatted Table
        }
    
    
    def to_cli_report(self) -> str:
        """
        Generate the human-readable portfolio risk report used by the CLI.

        Purpose:
            Produce a formatted, plain-text report with the exact section order and
            formatting used in the CLI workflow in `run_risk.py`. This ensures
            perfect parity between CLI output and programmatic generation.

        Sections (conditionally included when data is available):
            1) Target Allocations: Table with Portfolio Weight, Equal Weight, Eq Diff
            2) Portfolio Risk Summary: Annual/Monthly volatility, Herfindahl index
            3) Factor Exposures: Portfolio-level betas to market factors
            4) Variance Decomposition: Factor vs idiosyncratic breakdown
            5) Top Risk Contributors: Largest position risk contributions
            6) Portfolio Risk Limit Checks: PASS/FAIL summary of risk limits
            7) Beta Exposure Checks: PASS/FAIL summary vs max allowed betas
            8) Industry Analysis: Absolute and percent-of-portfolio variance, and
               per-industry-group betas

        Returns:
            str: Complete formatted report suitable for stdout, logs, or AI display.

        Notes:
            - Performance: Typically 5–10 ms using already-computed fields.
            - Parity: The same text is exposed via `to_api_response()` under
              `formatted_report` for API consumers that need CLI-identical text.
            - Omission: Sections will be omitted when corresponding data is missing.
        """
        sections = []
        
        # Section 1: Target Allocations (from display_portfolio_summary)
        if hasattr(self, 'allocations') and self.allocations is not None and not self.allocations.empty:
            sections.append("=== Target Allocations ===")
            sections.append(str(self.allocations))
        
        # NEW: Asset Allocation Section (after Target Allocations)
        asset_allocation = self._build_asset_allocation_breakdown()
        if asset_allocation:
            sections.append("=== Asset Allocation ===")
            # Show performance period and data quality when available
            perf_meta = (self.analysis_metadata or {}).get('asset_class_performance', {}) if hasattr(self, 'analysis_metadata') else {}
            if perf_meta:
                period = perf_meta.get('period')
                quality = perf_meta.get('data_quality')
                meta_line = ""
                if period:
                    meta_line += f"Period: {period}"
                if quality:
                    meta_line += ("  " if meta_line else "") + f"Quality: {quality}"
                if meta_line:
                    sections.append(meta_line)
            sections.append(self._format_asset_allocation_table(asset_allocation))
        
        # Section 2: Covariance Matrix 
        if hasattr(self, 'covariance_matrix') and self.covariance_matrix is not None and not self.covariance_matrix.empty:
            sections.append("=== Covariance Matrix ===")
            sections.append(str(self.covariance_matrix))
        
        # Section 3: Correlation Matrix
        if hasattr(self, 'correlation_matrix') and self.correlation_matrix is not None and not self.correlation_matrix.empty:
            sections.append("=== Correlation Matrix ===")
            sections.append(str(self.correlation_matrix))
        
        # Section 4: Volatility Metrics
        volatility_lines = []
        if hasattr(self, 'volatility_monthly'):
            volatility_lines.append(f"Monthly Volatility:  {self.volatility_monthly:.4%}")
        if hasattr(self, 'volatility_annual'):
            volatility_lines.append(f"Annual Volatility:   {self.volatility_annual:.4%}")
        if volatility_lines:
            sections.append("\n".join(volatility_lines))
        
        # Section 4.5: Portfolio Returns (Monthly Time Series)
        if hasattr(self, 'portfolio_returns') and self.portfolio_returns is not None and not self.portfolio_returns.empty:
            sections.append("=== Portfolio Returns (Monthly) ===")
            returns_lines = []
            # Show last 12 months or all if less than 12
            recent_returns = self.portfolio_returns.tail(12)
            for date, return_val in recent_returns.items():
                # Format date and return percentage
                date_str = date.strftime("%Y-%m") if hasattr(date, 'strftime') else str(date)[:7]
                returns_lines.append(f"{date_str}    {return_val:>8.2%}")
            
            if len(returns_lines) > 0:
                sections.append("\n".join(returns_lines))
            else:
                sections.append("(No portfolio returns data available)")
        
        # Section 5: Risk Contributions
        if hasattr(self, 'risk_contributions') and self.risk_contributions is not None and not self.risk_contributions.empty:
            sections.append("=== Risk Contributions ===")
            sections.append(str(self.risk_contributions))
        
        # Section 6: Herfindahl Index
        if hasattr(self, 'herfindahl'):
            sections.append(f"Herfindahl Index: {self.herfindahl}")
        
        # Section 7: Per-Stock Factor Betas
        if hasattr(self, 'stock_betas') and self.stock_betas is not None and not self.stock_betas.empty:
            sections.append("=== Per-Stock Factor Betas ===")
            sections.append(str(self.stock_betas))
        
        # Section 8: Portfolio-Level Factor Betas
        if hasattr(self, 'portfolio_factor_betas') and self.portfolio_factor_betas is not None and not self.portfolio_factor_betas.empty:
            sections.append("=== Portfolio-Level Factor Betas ===")
            sections.append(str(self.portfolio_factor_betas))
            # Display Interest Rate Exposure when present
            try:
                ir_beta = float(self.portfolio_factor_betas.get('interest_rate', 0.0))
            except Exception:
                ir_beta = 0.0
            if ir_beta != 0.0:
                sections.append("— Interest Rate Exposure —")
                sections.append(f"Interest Rate Beta:   {ir_beta:+.2f}")
                sections.append(f"Effective Duration:   {self.effective_duration:.2f} years")
                # Optional CLI notice for activation count
                try:
                    ac = (self.analysis_metadata or {}).get('asset_classes', {})
                    if ac:
                        n_bonds = sum(1 for t, c in ac.items() if c == 'bond')
                        if n_bonds > 0:
                            sections.append(f"✓ Rate factor analysis enabled for {n_bonds} bond holding(s)")
                except Exception:
                    pass
        
        # Section 9: Per-Asset Vol & Var
        if hasattr(self, 'asset_vol_summary') and self.asset_vol_summary is not None and not self.asset_vol_summary.empty:
            sections.append("=== Per-Asset Vol & Var ===")
            sections.append(str(self.asset_vol_summary))
        
        # Section 10: Factor Annual Volatilities
        if hasattr(self, 'factor_vols') and self.factor_vols is not None and not self.factor_vols.empty:
            sections.append("=== Factor Annual Volatilities (σ_i,f) ===")
            sections.append(str(self.factor_vols.round(4)))
        
        # Section 11: Weighted Factor Variance
        if hasattr(self, 'weighted_factor_var') and self.weighted_factor_var is not None and not self.weighted_factor_var.empty:
            sections.append("=== Weighted Factor Variance   w_i² · β_i,f² · σ_i,f² ===")
            sections.append(str(self.weighted_factor_var.round(6)))
        
        # Section 12: Portfolio Variance Decomposition
        if hasattr(self, 'variance_decomposition') and self.variance_decomposition is not None:
            sections.append("=== Portfolio Variance Decomposition ===")
            var_dec = self.variance_decomposition
            decomp_lines = []
            if 'portfolio_variance' in var_dec:
                decomp_lines.append(f"Portfolio Variance:          {var_dec['portfolio_variance']:.4f}")
            if 'idiosyncratic_variance' in var_dec and 'idiosyncratic_pct' in var_dec:
                decomp_lines.append(f"Idiosyncratic Variance:      {var_dec['idiosyncratic_variance']:.4f}  ({var_dec['idiosyncratic_pct']:.0%})")
            if 'factor_variance' in var_dec and 'factor_pct' in var_dec:
                decomp_lines.append(f"Factor Variance:             {var_dec['factor_variance']:.4f}  ({var_dec['factor_pct']:.0%})")
            sections.append("\n".join(decomp_lines))
        
        # Section 13: Factor Variance (absolute)
        if hasattr(self, 'variance_decomposition') and self.variance_decomposition and 'factor_breakdown_var' in self.variance_decomposition:
            sections.append("=== Factor Variance (absolute) ===")
            factor_lines = []
            for k, v in self.variance_decomposition["factor_breakdown_var"].items():
                factor_lines.append(f"{k.title():<10} : {v:.5f}")
            sections.append("\n".join(factor_lines))
        
        # Section 14: Top Stock Variance (Euler %)
        if hasattr(self, 'euler_variance_pct') and self.euler_variance_pct is not None:
            sections.append("=== Top Stock Variance (Euler %) ===")
            euler = self.euler_variance_pct
            if isinstance(euler, dict) and euler:
                top = dict(sorted(euler.items(), key=lambda kv: -kv[1])[:10])  # top-10
                euler_lines = []
                for ticker, pct in top.items():
                    euler_lines.append(f"{ticker:<10} : {pct:6.1%}")
                sections.append("\n".join(euler_lines))
            elif hasattr(euler, 'items'):  # pandas Series
                top = euler.nlargest(10)
                euler_lines = []
                for ticker, pct in top.items():
                    euler_lines.append(f"{ticker:<10} : {pct:6.1%}")
                sections.append("\n".join(euler_lines))
        
        # Section 15: Factor Variance (% of Portfolio, excluding industry)
        if hasattr(self, 'variance_decomposition') and self.variance_decomposition is not None:
            var_dec = self.variance_decomposition
            if 'factor_breakdown_pct' in var_dec:
                filtered = {
                    k: v for k, v in var_dec["factor_breakdown_pct"].items()
                    if k not in ("industry", "subindustry")
                }
                if filtered:
                    sections.append("=== Factor Variance (% of Portfolio, excluding industry) ===")
                    factor_lines = []
                    for k, v in filtered.items():
                        factor_lines.append(f"{k.title():<10} : {v:.0%}")
                    sections.append("\n".join(factor_lines))
        
        # Section 16: Industry Analysis (if available)
        if hasattr(self, 'industry_variance') and self.industry_variance is not None:
            # Industry variance (absolute)
            if 'absolute' in self.industry_variance:
                sections.append("=== Industry Variance (absolute) ===")
                industry_lines = []
                for k, v in self.industry_variance["absolute"].items():
                    industry_lines.append(f"{k:<10} : {v:.6f}")
                sections.append("\n".join(industry_lines))
            
            # Industry variance (% of Portfolio)
            if 'percent_of_portfolio' in self.industry_variance:
                sections.append("=== Industry Variance (% of Portfolio) ===")
                industry_pct_lines = []
                for k, v in self.industry_variance["percent_of_portfolio"].items():
                    industry_pct_lines.append(f"{k:<10} : {v:.1%}")
                sections.append("\n".join(industry_pct_lines))
            
            # Per-Industry Group Betas
            per_group = self.industry_variance.get("per_industry_group_beta", {})
            if per_group:
                sections.append("=== Per-Industry Group Betas ===")
                try:
                    from utils.etf_mappings import get_etf_to_industry_map, format_ticker_with_label
                    
                    # Use cash positions passed via analysis_metadata to avoid core calls
                    cash_positions = set((self.analysis_metadata or {}).get("cash_positions", []))
                    industry_map = get_etf_to_industry_map()
                    
                    # Calculate adaptive column width based on labeled ETF tickers
                    max_etf_width = 12  # minimum width for backwards compatibility
                    for k, v in per_group.items():
                        labeled_etf = format_ticker_with_label(k, cash_positions, industry_map)
                        max_etf_width = max(max_etf_width, len(labeled_etf))
                    
                    # Add some padding
                    max_etf_width += 2
                    
                    # Display with labels and adaptive width
                    group_lines = []
                    for k, v in sorted(per_group.items(), key=lambda kv: -abs(kv[1])):
                        labeled_etf = format_ticker_with_label(k, cash_positions, industry_map)
                        group_lines.append(f"{labeled_etf:<{max_etf_width}} : {v:>+7.4f}")
                    sections.append("\n".join(group_lines))
                except ImportError:
                    # Fallback without labels
                    group_lines = []
                    for k, v in sorted(per_group.items(), key=lambda kv: -abs(kv[1])):
                        group_lines.append(f"{k:<12} : {v:>+7.4f}")
                    sections.append("\n".join(group_lines))
        
        # Section 16: Portfolio Risk Limit Checks (existing)
        sections.append(self._format_risk_checks())
        
        # Section 17: Beta Exposure Checks (existing)
        sections.append(self._format_beta_checks())
        
        # Section 18: Historical Worst-Case Analysis sections
        if hasattr(self, 'historical_analysis') and self.historical_analysis:
            sections.append(self._format_historical_analysis())
        
        return "\n\n".join(sections)
    
    def _format_risk_checks(self) -> str:
        """Format risk checks as CLI table - EXACT copy of run_risk.py:335-338"""
        lines = ["=== Portfolio Risk Limit Checks ==="]
        for check in self.risk_checks:
            status = "→ PASS" if check["Pass"] else "→ FAIL"
            lines.append(f"{check['Metric']:<22} {check['Actual']:.2%}  ≤ {check['Limit']:.2%}  {status}")
        return "\n".join(lines)
    
    def _format_beta_checks(self) -> str:
        """Format beta checks as CLI table - EXACT copy of run_risk.py:342-345"""
        lines = ["=== Beta Exposure Checks ==="]
        for check in self.beta_checks:
            status = "→ PASS" if check["pass"] else "→ FAIL"
            factor = check['factor']
            lines.append(f"{factor:<20} β = {check['portfolio_beta']:+.2f}  ≤ {check['max_allowed_beta']:.2f}  {status}")
        return "\n".join(lines)
    
    def _format_historical_analysis(self) -> str:
        """Format historical worst-case analysis sections - EXACT copy of calc_max_factor_betas output"""
        if not self.historical_analysis:
            return ""
        
        sections = []
        
        # Extract data from historical_analysis
        worst_per_proxy = self.historical_analysis.get('worst_per_proxy', {})
        worst_by_factor = self.historical_analysis.get('worst_by_factor', {})
        analysis_period = self.historical_analysis.get('analysis_period', {})
        loss_limit = self.historical_analysis.get('loss_limit', -0.10)
        
        lookback_years = analysis_period.get('years', 10)
        start_str = analysis_period.get('start', '')
        end_str = analysis_period.get('end', '')
        
        # Section 1: Historical Worst-Case Analysis header
        sections.append(f"=== Historical Worst-Case Analysis ({lookback_years}-year lookback) ===")
        if start_str and end_str:
            sections.append(f"Analysis Period: {start_str} to {end_str}")
        
        # Section 2: Worst Monthly Losses per Proxy
        if worst_per_proxy:
            sections.append("\n=== Worst Monthly Losses per Proxy ===")
            proxy_lines = []
            for p, v in sorted(worst_per_proxy.items(), key=lambda kv: kv[1]):
                proxy_lines.append(f"{p:<12} : {v:.2%}")
            sections.append("\n".join(proxy_lines))
        
        # Section 3: Worst Monthly Losses per Factor Type
        if worst_by_factor:
            sections.append("\n=== Worst Monthly Losses per Factor Type ===")
            factor_lines = []
            for ftype, (p, v) in worst_by_factor.items():
                factor_lines.append(f"{ftype:<10} → {p:<12} : {v:.2%}")
            sections.append("\n".join(factor_lines))
        
        # Section 4: Max Allowable Beta per Factor
        if hasattr(self, 'max_betas') and self.max_betas:
            sections.append(f"\n=== Max Allowable Beta per Factor (Loss Limit = {loss_limit:.0%}) ===")
            beta_lines = []
            for ftype, beta in self.max_betas.items():
                beta_lines.append(f"{ftype:<10} → β ≤ {beta:.2f}")
            sections.append("\n".join(beta_lines))
        
        # Section 5: Max Beta per Industry Proxy
        if hasattr(self, 'max_betas_by_proxy') and self.max_betas_by_proxy:
            sections.append("\n=== Max Beta per Industry Proxy ===")
            proxy_beta_lines = []
            for p, b in sorted(self.max_betas_by_proxy.items()):
                proxy_beta_lines.append(f"{p:<12} → β ≤ {b:.2f}")
            sections.append("\n".join(proxy_beta_lines))
        
        return "\n".join(sections)

    @classmethod
    def _build_allocations_dataframe(cls, portfolio_summary: Dict[str, Any], analysis_metadata: Dict[str, Any]) -> pd.DataFrame:
        """
        Build allocations DataFrame ensuring Portfolio Weight column exists.
        
        This fixes the root cause where empty allocations DataFrame causes
        portfolio_weights property to return None, leading to len(None) errors
        in to_api_response() method.
        """
        # Try to get allocations from portfolio_summary first
        allocations_df = portfolio_summary.get("allocations", pd.DataFrame())
        
        # If allocations are empty or missing Portfolio Weight column, build from weights
        if allocations_df.empty or "Portfolio Weight" not in allocations_df.columns:
            weights = analysis_metadata.get("weights", {})
            if weights:
                allocations_df = pd.DataFrame({'Portfolio Weight': pd.Series(weights)})
            else:
                # Create empty DataFrame with proper structure
                allocations_df = pd.DataFrame(columns=['Portfolio Weight'])
        
        return allocations_df
    
    @classmethod
    def from_core_analysis(cls, 
                          portfolio_summary: Dict[str, Any],
                          risk_checks: List[Dict[str, Any]], 
                          beta_checks: List[Dict[str, Any]],
                          max_betas: Dict[str, float],
                          max_betas_by_proxy: Dict[str, float],
                          historical_analysis: Dict[str, Any],
                          analysis_metadata: Dict[str, Any]) -> 'RiskAnalysisResult':
        """
        Create RiskAnalysisResult from core portfolio analysis function data.
        
        ARCHITECTURE CONTEXT:
        This is the primary factory method for creating RiskAnalysisResult objects from
        core portfolio analysis functions (analyze_portfolio, build_portfolio_view).
        It transforms raw analysis data into a structured result object ready for API responses.
        
        DATA FLOW:
        analyze_portfolio() → portfolio_summary + checks → from_core_analysis() → RiskAnalysisResult
        
        INPUT DATA STRUCTURE:
        - portfolio_summary: Complete output from build_portfolio_view() containing:
          • volatility_annual/monthly: Risk metrics (float)
          • herfindahl: Concentration index (float)
          • portfolio_factor_betas: Factor exposures (Dict[str, float])
          • variance_decomposition: Risk breakdown (Dict[str, Any])
          • risk_contributions: Position risk contributions (pd.Series)
          • df_stock_betas: Individual stock betas (pd.DataFrame)
          • covariance_matrix, correlation_matrix: Risk matrices (pd.DataFrame)
          • industry_variance: Industry risk breakdown (Dict[str, Any])
          • net_exposure, gross_exposure, leverage, total_value: Portfolio metrics
          • dollar_exposure: Position dollar amounts (Dict[str, float])
        
        - risk_checks: Risk limit validation results from evaluate_portfolio_risk_limits()
          Format: List[Dict] with keys: Metric, Actual, Limit, Pass
        
        - beta_checks: Beta exposure validation results from evaluate_portfolio_beta_limits()
          Format: List[Dict] with keys: factor, portfolio_beta, max_allowed_beta, pass
        
        - max_betas: Maximum allowed beta thresholds (Dict[str, float])
        - max_betas_by_proxy: Maximum proxy beta thresholds (Dict[str, float])
        - historical_analysis: Historical performance data (Dict[str, Any])
        - analysis_metadata: Analysis context and configuration
          • portfolio_name: Display name (str)
          • analysis_date: ISO timestamp (str)
          • expected_returns: Expected return assumptions (Dict[str, float])
          • factor_proxies: Factor proxy mappings (Dict[str, str])
        
        TRANSFORMATION PROCESS:
        1. Extract core risk metrics from portfolio_summary
        2. Map DataFrames and Series to structured fields
        3. Build allocations DataFrame for API compatibility
        4. Store validation results (risk_checks, beta_checks)
        5. Set analysis metadata and timestamps
        
        OUTPUT OBJECT CAPABILITIES:
        - to_api_response(): Complete structured API response with 30+ risk metrics
        - to_formatted_report(): Human-readable CLI report for Claude/AI
        - get_summary(): Core risk metrics for quick analysis
        - Comprehensive risk analysis with factor exposures and compliance checks
        
        🔒 BACKWARD COMPATIBILITY CONSTRAINT:
        Must preserve exact field mappings to ensure to_api_response() produces
        identical output structure. This replaces from_build_portfolio_view() while
        maintaining 100% API compatibility.
        
        Args:
            portfolio_summary (Dict[str, Any]): Complete build_portfolio_view() output
            risk_checks (List[Dict[str, Any]]): Risk limit validation results
            beta_checks (List[Dict[str, Any]]): Beta exposure validation results  
            max_betas (Dict[str, float]): Maximum beta thresholds per factor
            max_betas_by_proxy (Dict[str, float]): Maximum proxy beta thresholds
            historical_analysis (Dict[str, Any]): Historical performance analysis
            analysis_metadata (Dict[str, Any]): Analysis context and configuration
            
        Returns:
            RiskAnalysisResult: Fully populated result object with 30+ risk metrics
        """
        return cls(
            # Core field mappings from existing from_build_portfolio_view()
            volatility_annual=portfolio_summary["volatility_annual"],
            volatility_monthly=portfolio_summary["volatility_monthly"],
            herfindahl=portfolio_summary["herfindahl"],
            portfolio_factor_betas=portfolio_summary["portfolio_factor_betas"],
            variance_decomposition=portfolio_summary["variance_decomposition"],
            risk_contributions=portfolio_summary["risk_contributions"],
            stock_betas=portfolio_summary["df_stock_betas"],
            covariance_matrix=portfolio_summary.get("covariance_matrix", pd.DataFrame()),
            correlation_matrix=portfolio_summary.get("correlation_matrix", pd.DataFrame()),
            allocations=cls._build_allocations_dataframe(portfolio_summary, analysis_metadata),  # Used by to_api_response()
            factor_vols=portfolio_summary.get("factor_vols", pd.DataFrame()),
            weighted_factor_var=portfolio_summary.get("weighted_factor_var", pd.DataFrame()),
            asset_vol_summary=portfolio_summary.get("asset_vol_summary", pd.DataFrame()),
            portfolio_returns=portfolio_summary.get("portfolio_returns", pd.Series()),
            euler_variance_pct=portfolio_summary.get("euler_variance_pct", pd.Series()),
            industry_variance=portfolio_summary.get("industry_variance", {}),
            net_exposure=portfolio_summary.get("net_exposure"),
            gross_exposure=portfolio_summary.get("gross_exposure"),
            leverage=portfolio_summary.get("leverage"),
            total_value=portfolio_summary.get("total_value"),  # Used by to_api_response()
            dollar_exposure=portfolio_summary.get("dollar_exposure"),  # Used by to_api_response()
            # New structured fields from parameters
            risk_checks=risk_checks,
            beta_checks=beta_checks, 
            max_betas=max_betas,
            max_betas_by_proxy=max_betas_by_proxy,
            historical_analysis=historical_analysis,
            analysis_date=datetime.now(UTC),
            analysis_metadata=analysis_metadata,
            portfolio_name=analysis_metadata.get("portfolio_name"),
            expected_returns=analysis_metadata.get("expected_returns"),
            factor_proxies=analysis_metadata.get("factor_proxies")
        )
    
    def to_formatted_report(self) -> str:
        """Format interpretation results for display (identical to to_cli_report())."""
        return self.to_cli_report()
    


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
        lines.append(f"📁 Portfolio file: {self.portfolio_file}")
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
    
    Enhanced API Features:
    =====================
    The RiskScoreResult provides enhanced API functionality through:
    
    - **Structured Interpretation**: risk_score.interpretation contains both
      actionable guidance (details) and risk assessment context, generated
      via shared interpretation logic ensuring 100% CLI/API alignment
    - **Priority Actions**: Auto-generated prioritized action list from 
      violation analysis, ranked by urgency and impact for optimal execution
    - **Organized Summaries**: Structured violation summaries and risk factor
      analysis with priority levels and severity rankings
    - **Comprehensive Field Coverage**: 100% field mapping between CLI output
      and API response ensures complete data consistency across interfaces
    
    API Integration:
    - Use to_api_response() for API endpoints and JSON serialization
    """
    
    # Risk score information
    risk_score: Dict[str, Any]
    
    # Limits analysis and violations
    limits_analysis: Dict[str, Any]
    
    # Portfolio analysis details
    portfolio_analysis: Dict[str, Any]
    
    # Data from run_risk_score_analysis
    suggested_limits: Dict[str, Any]  # Risk limit suggestions
    formatted_report: str             # Complete formatted report text
    
    # Metadata
    analysis_date: datetime
    portfolio_name: Optional[str] = None
    
    # Risk limits metadata (from RiskLimitsData object)
    risk_limits_name: Optional[str] = None        # Risk limits profile name
    
    # Analysis metadata (for CLI report generation)
    analysis_metadata: Optional[Dict[str, Any]] = None
    
    @classmethod  
    def from_risk_score_analysis(cls, 
                               risk_score: Dict[str, Any],
                               limits_analysis: Dict[str, Any], 
                               portfolio_analysis: Dict[str, Any],
                               suggested_limits: Dict[str, Any],
                               analysis_metadata: Dict[str, Any]) -> 'RiskScoreResult':
        """
        Create RiskScoreResult from core risk scoring analysis function data.
        
        ARCHITECTURE CONTEXT:
        This is the primary factory method for creating RiskScoreResult objects from
        core risk scoring functions (run_risk_score_analysis). It transforms risk scoring
        calculations and limit compliance analysis into a structured result object.
        
        DATA FLOW:
        run_risk_score_analysis() → risk_score + limits_analysis → from_risk_score_analysis() → RiskScoreResult
        
        INPUT DATA STRUCTURE:
        - risk_score: Core risk scoring results containing:
          • score: Overall risk score (0-100 scale, float)
          • category: Risk category ("Excellent", "Good", "Fair", "Poor", "Very Poor")
          • component_scores: Dict with individual risk component scores
            - factor_risk: Market/Value/Momentum exposure risk score (0-100)
            - concentration_risk: Position sizes & diversification risk score (0-100)
            - volatility_risk: Portfolio volatility level risk score (0-100)
            - sector_risk: Sector concentration risk score (0-100)
          • risk_factors: List[str] of identified risk factors with descriptions
          • recommendations: List[str] of actionable risk management recommendations
          • potential_losses: Dict with loss analysis
            - factor_risk: Potential loss from factor exposure (float)
            - concentration_risk: Potential loss from concentration (float)
            - volatility_risk: Potential loss from volatility (float)
            - sector_risk: Potential loss from sector concentration (float)
            - max_loss_limit: Maximum acceptable loss threshold (float)
          • details: Dict with additional scoring details
          • interpretation: Risk assessment interpretation and guidance (from generate_score_interpretation)
        
        - limits_analysis: Risk limit compliance analysis containing:
          • risk_factors: List[str] of identified risk factors (same as risk_score.risk_factors)
          • recommendations: List[str] of actionable risk management recommendations (same as risk_score.recommendations)
          • limit_violations: Dict with violation details (derived from risk scoring analysis)
          • compliance_status: Overall compliance status (bool)
        
        - portfolio_analysis: Portfolio context and analysis containing:
          Complete portfolio analysis data from build_portfolio_view (Dict[str, Any])
        
        - suggested_limits: Risk limit recommendations containing:
          Risk limit suggestions calculated from max loss tolerance (Dict[str, Any])
        
        - analysis_metadata: Analysis context and configuration
          • portfolio_name: Portfolio identifier (str)
          • risk_limits_name: Risk limits profile name (str)
          • analysis_date: ISO timestamp when analysis was performed (str)
          • risk_limits_file: Path to risk limits configuration (str)
          • portfolio_file: Path to portfolio configuration (str)
        
        TRANSFORMATION PROCESS:
        1. Create RiskScoreResult instance with core risk scoring data
        2. Set analysis timestamp and portfolio context
        3. Store risk limits metadata and file paths
        4. Generate formatted CLI report via to_cli_report()
        5. Attach formatted report to result object
        
        OUTPUT OBJECT CAPABILITIES:
        - to_api_response(): Complete structured API response with risk scoring and compliance
        - to_formatted_report(): Human-readable CLI report for Claude/AI
        - get_summary(): Core risk metrics and compliance status
        - Risk factor analysis with priority rankings and actionable recommendations
        
        🔒 BACKWARD COMPATIBILITY CONSTRAINT:
        Must preserve exact field mappings to ensure to_api_response() produces
        identical output structure. This builder ensures consistent API compatibility.
        
        Args:
            risk_score (Dict[str, Any]): Core risk scoring results with 0-100 scale scores
            limits_analysis (Dict[str, Any]): Risk limit compliance analysis and violations
            portfolio_analysis (Dict[str, Any]): Portfolio context and risk metrics
            suggested_limits (Dict[str, Any]): Risk limit recommendations
            analysis_metadata (Dict[str, Any]): Analysis context and file paths
            
        Returns:
            RiskScoreResult: Fully populated risk scoring result with compliance analysis
        """
        from datetime import datetime, timezone
        
        # Create the result object first
        result = cls(
            risk_score=risk_score,
            limits_analysis=limits_analysis,
            portfolio_analysis=portfolio_analysis,
            suggested_limits=suggested_limits,
            formatted_report="",  # Will be populated below
            analysis_date=datetime.now(timezone.utc),
            portfolio_name=analysis_metadata.get("portfolio_name", "portfolio"),
            risk_limits_name=analysis_metadata.get("risk_limits_name"),
            analysis_metadata=analysis_metadata
        )
        
        # Generate and attach the formatted report
        result.formatted_report = result.to_cli_report()
        
        return result
    
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
    
    

    def _get_priority_actions(self) -> list:
        """
        Generate prioritized action recommendations based on risk violations and analysis.
        
        This method transforms raw violation-based recommendations and risk factors into a 
        structured, prioritized action list for portfolio managers. It processes data from
        the limits analysis and organizes it into three priority tiers for optimal execution.
        
        Data Sources:
        - limits_analysis.recommendations: Violation-specific actions from risk limits analysis
        - limits_analysis.risk_factors: Identified risk issues requiring attention
        
        Priority Algorithm:
        - **Priority 1 (Critical)**: Top 3 recommendations containing urgent keywords 
          ("reduce", "limit", "excess") requiring immediate action
        - **Priority 2 (Monitor)**: Top 2 risk factors to actively monitor, excluding 
          duplicates already in Priority 1
        - **Priority 3 (Additional)**: Remaining recommendations (up to 2) for 
          comprehensive risk management
        
        Returns:
        --------
        list
            Prioritized action items with numbered prefixes (1., 2., 3.) indicating
            execution priority. Typical length: 3-7 actions.
            
        Examples:
        ---------
        [
            "1. Reduce market exposure (sell high-beta stocks or add market hedges)",
            "1. Reduce exposure to REM industry", 
            "2. Monitor: High market variance contribution",
            "3. Add more positions to improve diversification"
        ]
        
        Usage Context:
        --------------
        Used in to_api_response() to provide structured, actionable guidance for API
        consumers who need clear prioritization for portfolio risk management decisions.
        Complements the interpretation fields by providing specific execution priorities.
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
        Convert RiskScoreResult to comprehensive API response format.
        
        CONSUMER ANALYSIS:
        - Direct API: Uses full structured response for programmatic risk scoring and compliance monitoring
        - Claude/AI: Only uses formatted_report (ignores all structured data)
        - Frontend: Uses adapters to transform structured data for risk dashboards and compliance views
        
        This method transforms raw risk analysis data into a structured, enhanced API response
        that provides both core risk metrics and actionable insights for portfolio management.
        The response ensures 100% field coverage alignment with CLI output while adding
        API-specific enhancements for programmatic consumption.
        
        RESPONSE STRUCTURE:
        ==================
        
        **Core Risk Metrics:**
        - risk_score: Overall and component scores with structured interpretation
          └── interpretation: Actionable guidance + risk assessment context
        - suggested_limits: Backwards-calculated limits from loss tolerance
        
        **Violation Analysis:**
        - limits_analysis: Raw violation data and recommendations from core analysis
        - violations_summary: Structured violation counts by category and severity
        - violation_details: Detailed breakdown of specific limit breaches with values
        
        **Enhanced Guidance:**
        - priority_actions: Ranked action list (Priority 1/2/3) for optimal execution
        - risk_factors_with_priority: Risk factors with severity and priority levels
        
        **Metadata & Context:**
        - portfolio_file/risk_limits_file: Source data file paths
        - formatted_report: Complete CLI output for display/debugging
        - analysis_date/portfolio_name: Analysis context and identification
        
        Key Features:
        =============
        - **CLI Alignment**: 100% field coverage ensures identical content between CLI and API
        - **Structured Interpretation**: Both actionable details and risk assessment context
        - **Priority-Based Actions**: Ranked recommendations for optimal portfolio management
        - **Comprehensive Violations**: Multiple violation analysis views (summary, details, priorities)
        - **Schema Compliance**: OpenAPI-compatible structure for consistent API integration
        
        Returns:
        --------
        Dict[str, Any]
            Complete risk analysis response ready for API serialization, containing
            all core metrics, violation analysis, actionable recommendations, and
            enhanced guidance with priority rankings.
            
        Usage:
        ------
        Used by portfolio service endpoints to provide comprehensive risk analysis
        data to API consumers, ensuring they receive both quantitative metrics and
        actionable guidance for portfolio risk management decisions.
        """
        return {
            # Core risk scoring data with score-based interpretation
            "risk_score": _convert_to_json_serializable(self.risk_score),  # Contains: score, category, component_scores, interpretation{summary, details, risk_assessment}
            
            # Violation-based analysis with specific recommendations  
            "limits_analysis": _convert_to_json_serializable(self.limits_analysis),  # Contains: risk_factors, recommendations (violation-specific), limit_violations
            
            # Suggested risk limits (backwards-calculated from max loss tolerance)
            "suggested_limits": _convert_to_json_serializable(self.suggested_limits),  # Contains: factor_limits, concentration_limit, volatility_limit, sector_limit
            
            # Complete formatted CLI output (for display/debugging)
            "formatted_report": self.formatted_report or self.to_cli_report(),  # Full CLI text output
            
            # Enhanced analysis fields (generated by helper methods)
            "priority_actions": self._get_priority_actions(),  # Prioritized action list from recommendations
            "violations_summary": self._get_violations_summary(),  # Summary counts of violations by type
            "violation_details": self._get_violation_details(),  # Detailed violation breakdown with values
            "risk_factors_with_priority": self._get_risk_factors_with_priority(),  # Risk factors with priority levels
            
            # Complete portfolio analysis data (correlations, allocations, etc.)
            "portfolio_analysis": _convert_to_json_serializable(self.portfolio_analysis),  # Full portfolio view data
            
            # Analysis metadata (grouped for cleaner API structure)
            "analysis_metadata": {
                "analysis_date": self.analysis_date.isoformat(),  # When analysis was performed
                "portfolio_name": self.portfolio_name,  # Portfolio identifier
                "risk_limits_name": self.risk_limits_name,  # Risk limits profile name (e.g., "Conservative", "Aggressive")
                "max_loss": self.analysis_metadata.get('max_loss') if self.analysis_metadata else None,  # Maximum loss tolerance used
                "analysis_type": self.analysis_metadata.get('analysis_type', 'risk_score') if self.analysis_metadata else 'risk_score'  # Type of analysis performed
            }

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
    
    def to_cli_report(self) -> str:
        """
        Generate complete CLI formatted report - IDENTICAL to current output.
        
        This method produces the exact same CLI output as the current portfolio_risk_score.py
        implementation, ensuring byte-for-byte compatibility during the refactoring process.
        """
        sections = []
        sections.append(self._format_risk_score_display())
        sections.append("")  # Add blank line
        sections.append(self._format_detailed_risk_analysis())  
        sections.append("")  # Add blank line
        sections.append(self._format_suggested_risk_limits())
        return "\n".join(sections)
    
    def _format_risk_score_display(self) -> str:
        """Format risk score display - EXACT copy of display_portfolio_risk_score()"""
        # Import generate_score_interpretation from portfolio_risk_score module
        from portfolio_risk_score import generate_score_interpretation
        
        score = self.risk_score["score"]
        category = self.risk_score["category"]
        component_scores = self.risk_score["component_scores"]
        risk_factors = self.risk_score["risk_factors"]
        recommendations = self.risk_score["recommendations"]
        
        lines = []
        lines.append("")  # Add initial blank line
        
        # Color coding based on score
        if score >= 90:
            color = "🟢"  # Green
        elif score >= 80:
            color = "🟡"  # Yellow
        elif score >= 70:
            color = "🟠"  # Orange
        elif score >= 60:
            color = "🔴"  # Red
        else:
            color = "⚫"  # Black
        
        lines.append("=" * 60)
        lines.append("📊 PORTFOLIO RISK SCORE (Scale: 0-100, higher = better)")
        lines.append("=" * 60)
        lines.append(f"{color} Overall Score: {score}/100 ({category})")
        
        # Show max loss context if available
        max_loss_limit = self.risk_score.get("details", {}).get("max_loss_limit", None)
        if max_loss_limit:
            lines.append(f"Based on your {abs(max_loss_limit):.0%} maximum loss tolerance")
        
        lines.append("=" * 60)
        lines.append("")  # Add blank line
        
        # Component breakdown with explanations
        lines.append("📈 Component Scores: (Risk of exceeding loss tolerance)")
        lines.append(f"{'─'*40}")
        component_explanations = {
            "factor_risk": "Market/Value/Momentum exposure",
            "concentration_risk": "Position sizes & diversification", 
            "volatility_risk": "Portfolio volatility level",
            "sector_risk": "Sector concentration"
        }
        
        for component, comp_score in component_scores.items():
            comp_color = "🟢" if comp_score >= 80 else "🟡" if comp_score >= 60 else "🔴"
            explanation = component_explanations.get(component, "")
            component_name = component.replace('_', ' ').title()
            lines.append(f"{comp_color} {component_name:<15} ({explanation}) {comp_score:>5.1f}/100")
        
        lines.append("")  # Add blank line after component scores
        
        # Risk factors with simplified language
        if risk_factors:
            lines.append(f"⚠️  Risk Factors Identified:")
            lines.append(f"{'─'*40}")
            for factor in risk_factors:
                # Simplify technical language
                simplified_factor = factor.replace("Factor exposure", "Market exposure")
                simplified_factor = simplified_factor.replace("systematic factor exposure", "market exposure")
                lines.append(f"   • {simplified_factor}")
        
        # Recommendations with implementation guidance
        if recommendations:
            lines.append(f"💡 Recommendations:")
            lines.append(f"{'─'*40}")
            for rec in recommendations:
                simplified_rec = rec.replace("systematic factor exposure", "market exposure")
                simplified_rec = simplified_rec.replace("through hedging or position sizing", "(sell high-beta stocks or add hedges)")
                lines.append(f"   • {simplified_rec}")
            
            # Add detailed implementation guidance
            lines.append(f"🔧 How to Implement:")
            lines.append(f"{'─'*40}")
            
            # Market/Factor exposure guidance
            if any("market exposure" in rec.lower() or "market factor" in rec.lower() for rec in recommendations):
                lines.append("   • Reduce market exposure: Sell high-beta stocks, add market hedges (SPY puts), or increase cash")
            
            # Specific factor guidance
            if any("momentum" in rec.lower() for rec in recommendations):
                lines.append("   • Reduce momentum exposure: Trim momentum-oriented positions or add momentum shorts")
            if any("value" in rec.lower() for rec in recommendations):
                lines.append("   • Reduce value exposure: Trim value-oriented positions or add growth positions")
            
            # Sector-specific guidance
            sector_recs = [rec for rec in recommendations if any(sector in rec for sector in ["REM", "DSU", "XOP", "KIE", "XLK", "KCE", "SOXX", "ITA", "XLP", "SLV", "XLC"])]
            if sector_recs:
                lines.append("   • Reduce sector concentration: Trim specific sector ETF positions or add offsetting sectors")
            
            # Concentration/diversification guidance
            if any("concentration" in rec.lower() or "position size" in rec.lower() for rec in recommendations):
                lines.append("   • Reduce concentration: Trim largest positions, spread allocation across more stocks")
            if any("diversification" in rec.lower() for rec in recommendations):
                lines.append("   • Improve diversification: Add more positions across different sectors and factors")
            
            # Volatility guidance
            if any("volatility" in rec.lower() for rec in recommendations):
                lines.append("   • Reduce volatility: Add defensive stocks, increase cash, or add volatility hedges")
            
            # Systematic risk guidance
            if any("systematic" in rec.lower() for rec in recommendations):
                lines.append("   • Reduce systematic risk: Lower factor exposures, add uncorrelated assets")
            
            # Leverage guidance
            if any("leverage" in rec.lower() for rec in recommendations):
                lines.append("   • Reduce leverage: Increase cash position, pay down margin, or reduce position sizes")
        
        # Score interpretation - action-focused
        lines.append(f"📋 Score Interpretation:")
        lines.append(f"{'─'*40}")
        interpretation = generate_score_interpretation(score)
        lines.append(f"   {interpretation['summary']}")
        for detail in interpretation['details']:
            lines.append(f"      • {detail}")
        
        lines.append("")  # Add blank line after score interpretation
        
        # Risk assessment - contextual understanding
        lines.append(f"📊 Risk Assessment:")
        lines.append(f"{'─'*40}")
        for assessment in interpretation['risk_assessment']:
            lines.append(f"   • {assessment}")
        
        lines.append("")  # Add blank line after risk assessment
        
        lines.append("=" * 60)
        
        return "\n".join(lines)
    
    def _format_detailed_risk_analysis(self) -> str:
        """Format detailed risk limits analysis - EXACT copy of lines 1511-1553"""
        lines = []
        
        # Display detailed risk limits analysis
        lines.append("═" * 80)
        lines.append("📋 DETAILED RISK LIMITS ANALYSIS")
        lines.append("═" * 80)
        lines.append("")  # Add blank line after header
        
        # Display limit violations summary
        violations = self.limits_analysis["limit_violations"]
        total_violations = sum(violations.values())
        
        lines.append("📊 LIMIT VIOLATIONS SUMMARY:")
        lines.append(f"   Total violations: {total_violations}")
        lines.append(f"   Factor betas: {violations['factor_betas']}")
        lines.append(f"   Concentration: {violations['concentration']}")
        lines.append(f"   Volatility: {violations['volatility']}")
        lines.append(f"   Variance contributions: {violations['variance_contributions']}")
        lines.append(f"   Leverage: {violations['leverage']}")
        lines.append("")  # Add blank line after violations summary
        
        # Display detailed risk factors
        if self.limits_analysis["risk_factors"]:
            lines.append("⚠️  KEY RISK FACTORS:")
            for factor in self.limits_analysis["risk_factors"]:
                lines.append(f"   • {factor}")
            lines.append("")  # Add blank line after risk factors
        
        # Display detailed recommendations
        if self.limits_analysis["recommendations"]:
            lines.append("💡 KEY RECOMMENDATIONS:")
            
            # Filter recommendations to show only beta-based ones (more intuitive for users)
            # Keep variance calculations but don't show variance-based recommendations in output
            beta_recommendations = []
            for rec in self.limits_analysis["recommendations"]:
                # Skip variance-based recommendations (they're duplicative of beta-based ones)
                if "factor exposure (contributing" in rec.lower():
                    continue  # Skip "Reduce X factor exposure (contributing Y% to variance)"
                if "industry (contributing" in rec.lower():
                    continue  # Skip "Reduce X industry (contributing Y% to variance)"
                if "reduce market factor exposure" in rec.lower():
                    continue  # Skip generic market factor exposure
                
                # Keep all other recommendations (beta-based, concentration, volatility, leverage, etc.)
                beta_recommendations.append(rec)
            
            for rec in beta_recommendations:
                lines.append(f"   • {rec}")
        
        return "\n".join(lines)
    
    def _format_suggested_risk_limits(self) -> str:
        """Format suggested limits - EXACT copy of display_suggested_risk_limits()"""
        # Get max loss from analysis metadata or default
        analysis_metadata = getattr(self, 'analysis_metadata', {})
        max_loss = analysis_metadata.get('max_loss', 0.25)  # Default 25%
        
        lines = []
        
        # Get current leverage for display
        current_leverage = self.suggested_limits.get("leverage_limit", {}).get("current_leverage", 1.0)
        
        lines.append("=" * 60)
        lines.append(f"📋 SUGGESTED RISK LIMITS (to stay within {max_loss:.0%} max loss)")
        lines.append(f"Working backwards from your risk tolerance to show exactly what needs to change")
        if current_leverage > 1.01:
            lines.append(f"Adjusted for your current {current_leverage:.2f}x leverage - limits are tighter")
        lines.append("=" * 60)
        lines.append("")  # Add blank line after header
        
        # Factor limits
        factor_limits = self.suggested_limits["factor_limits"]
        if factor_limits:
            lines.append(f"🎯 Factor Beta Limits: (Beta = sensitivity to market moves)")
            lines.append(f"{'─'*40}")
            for factor, data in factor_limits.items():
                status = "🔴 REDUCE" if data["needs_reduction"] else "🟢 OK"
                factor_name = factor.replace('_', ' ').title().replace('Beta', 'Exposure')
                current_val = data['current']
                suggested_val = data['suggested_max']
                
                # Add note for negative values (hedges)
                note = ""
                if current_val < 0:
                    note = " (hedge position)"
                
                lines.append(f"{status} {factor_name:<15} Current: {current_val:>6.2f}{note}  →  Max: {suggested_val:>6.2f}")
        
        lines.append("")  # Add blank line after factor limits
        
        # Concentration limit
        conc = self.suggested_limits["concentration_limit"]
        conc_status = "🔴 REDUCE" if conc["needs_reduction"] else "🟢 OK"
        lines.append(f"🎯 Position Size Limit:")
        lines.append(f"{'─'*40}")
        lines.append(f"{conc_status} Max Position Size     Current: {conc['current_max_position']:>6.1%}  →  Max: {conc['suggested_max_position']:>6.1%}")
        
        lines.append("")  # Add blank line after concentration limit
        
        # Volatility limit
        vol = self.suggested_limits["volatility_limit"]
        vol_status = "🔴 REDUCE" if vol["needs_reduction"] else "🟢 OK"
        lines.append(f"🎯 Volatility Limit:")
        lines.append(f"{'─'*40}")
        lines.append(f"{vol_status} Portfolio Volatility  Current: {vol['current_volatility']:>6.1%}  →  Max: {vol['suggested_max_volatility']:>6.1%}")
        
        lines.append("")  # Add blank line after volatility limit
        
        # Sector limit
        sector = self.suggested_limits["sector_limit"]
        sector_status = "🔴 REDUCE" if sector["needs_reduction"] else "🟢 OK"
        lines.append(f"🎯 Sector Concentration Limit:")
        lines.append(f"{'─'*40}")
        lines.append(f"{sector_status} Max Sector Exposure   Current: {sector['current_max_sector']:>6.1%}  →  Max: {sector['suggested_max_sector']:>6.1%}")
        
        lines.append("")  # Add blank line after sector limit
        
        lines.append("💡 Priority Actions:")
        lines.append(f"{'─'*40}")
        
        # Identify biggest issues
        issues = []
        if any(data["needs_reduction"] for data in factor_limits.values()):
            issues.append("Reduce systematic factor exposures")
        if conc["needs_reduction"]:
            issues.append("Reduce largest position sizes")
        if vol["needs_reduction"]:
            issues.append("Reduce portfolio volatility")
        if sector["needs_reduction"]:
            issues.append("Reduce sector concentration")
        
        if not issues:
            lines.append("   🟢 Portfolio structure is within suggested limits!")
        else:
            for i, issue in enumerate(issues, 1):
                lines.append(f"   {i}. {issue}")
        
        lines.append("")  # Add blank line after priority actions
        
        lines.append("=" * 60)
        
        return "\n".join(lines)

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

    def to_formatted_report(self) -> str:
        """Format risk score results for display (identical to to_cli_report())."""
        return self.to_cli_report()
 
    
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
            from run_portfolio_risk import get_cash_positions
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



class StockAnalysisResult:
    """
    Individual stock analysis results with multi-factor support, volatility metrics,
    and (for bonds) interest-rate sensitivity derived from key‑rate regression.
    
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
                 ticker: str,
                 *,
                 # Optional rate factor fields for bonds (Phase 2-ready)
                 interest_rate_beta: Optional[float] = None,
                 effective_duration: Optional[float] = None,
                 rate_regression_r2: Optional[float] = None,
                 key_rate_breakdown: Optional[Dict[str, float]] = None):
        # Core stock analysis data
        self.ticker = ticker.upper()
        self.volatility_metrics = stock_data.get("vol_metrics", {})
        self.regression_metrics = stock_data.get("regression_metrics", {})
        self.factor_summary = stock_data.get("factor_summary")
        self.risk_metrics = stock_data.get("risk_metrics", {})
        
        # Enhanced factor analysis data (from analyze_stock improvements)
        self.factor_exposures = stock_data.get("factor_exposures", {})
        self.factor_proxies = stock_data.get("factor_proxies", {})
        self.analysis_metadata = stock_data.get("analysis_metadata", {})
        
        # Analysis metadata
        self.analysis_date = datetime.now(UTC)

        # Rate factor fields (populated for bonds when available)
        self.interest_rate_beta = interest_rate_beta
        self.effective_duration = effective_duration
        self.rate_regression_r2 = rate_regression_r2
        self.key_rate_breakdown = key_rate_breakdown or {}
    
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
    def from_core_analysis(cls, 
                          ticker: str,
                          analysis_period: Dict[str, str],
                          analysis_type: str,
                          volatility_metrics: Dict[str, Any],
                          regression_metrics: Optional[Dict[str, Any]] = None,
                          risk_metrics: Optional[Dict[str, Any]] = None,
                          factor_summary: Optional[Any] = None,
                          factor_exposures: Optional[Dict[str, Any]] = None,
                          factor_proxies: Optional[Dict[str, Any]] = None,
                          analysis_metadata: Dict[str, Any] = None,
                          *,
                          interest_rate_beta: Optional[float] = None,
                          effective_duration: Optional[float] = None,
                          rate_regression_r2: Optional[float] = None,
                          key_rate_breakdown: Optional[Dict[str, float]] = None) -> 'StockAnalysisResult':
        """
        Create StockAnalysisResult from core stock analysis function data.
        
        ARCHITECTURE CONTEXT:
        This is the primary factory method for creating StockAnalysisResult objects from
        core stock analysis functions (analyze_stock). It transforms individual stock
        risk analysis calculations into a structured result object ready for API responses.
        
        DATA FLOW:
        analyze_stock() → volatility_metrics + regression_metrics + factor_summary → from_core_analysis() → StockAnalysisResult
        
        INPUT DATA STRUCTURE:
        - ticker: Stock symbol identifier (str, e.g., "AAPL")
        - analysis_period: Time period analysis configuration
          • start_date: Analysis start date (str, YYYY-MM-DD)
          • end_date: Analysis end date (str, YYYY-MM-DD)
        - analysis_type: Type of analysis performed (str, "simple_market_regression" or "multi_factor")
        - volatility_metrics: Stock volatility analysis containing:
          • monthly_vol: Monthly volatility (standard deviation of returns) (float)
          • annual_vol: Annualized volatility (monthly_vol * sqrt(12)) (float)
        - regression_metrics: Market regression analysis (Optional) containing:
          • beta: Market sensitivity coefficient (slope from OLS regression) (float)
          • alpha: Intercept from OLS regression (float)
          • r_squared: Model R-squared (proportion of variance explained) (float)
          • idio_vol_m: Idiosyncratic volatility (standard deviation of residuals) (float)
        - factor_summary: Multi-factor analysis results (Optional, pandas DataFrame)
          One row per factor (market, momentum, value, industry, subindustry) with columns:
          • beta: Factor exposure coefficient (float)
          • r_squared: Variance explained by this factor (float, 0-1 scale)  
          • idio_vol_m: Unexplained monthly volatility after this factor (float)
        - risk_metrics: Market regression analysis for simple_market_regression (Optional) containing:
          Same fields as regression_metrics: beta, alpha, r_squared, idio_vol_m
        - factor_exposures: Structured factor metadata (Optional, Dict)
          Maps factor names to their stats and proxy metadata from _create_factor_exposures_mapping
        - factor_proxies: ETF/ticker mappings for factors (Optional, Dict)
          Maps factor names to proxy tickers (e.g., {"market": "SPY", "momentum": "MTUM"})
        - analysis_metadata: Analysis configuration and timestamps (Optional, Dict)
          • has_factor_analysis: Whether multi-factor analysis was performed (bool)
          • num_factors: Number of factors analyzed (int)
          • analysis_date: When analysis was performed (str, ISO format)
          • benchmark: Benchmark used for simple regression (str, "SPY")
        
        TRANSFORMATION PROCESS:
        1. Create stock_data dictionary from input parameters
        2. Instantiate StockAnalysisResult with stock_data and ticker
        3. Set additional fields required for CLI formatting (analysis_period, analysis_type)
        4. Preserve raw data for API response compatibility
        5. Ensure backward compatibility with existing service layer
        
        OUTPUT OBJECT CAPABILITIES:
        - to_api_response(): Complete structured API response with stock analysis and factor exposures
        - to_formatted_report(): Human-readable CLI report for Claude/AI
        - get_volatility_metrics(), get_market_regression(), get_factor_exposures(): Accessor methods
        
        🔒 BACKWARD COMPATIBILITY CONSTRAINT:
        Must preserve exact field mappings to ensure to_api_response() produces
        identical output structure. This builder ensures consistent API compatibility.
        
        Args:
            ticker (str): Stock symbol identifier
            analysis_period (Dict[str, str]): Time period configuration
            analysis_type (str): Analysis type performed
            volatility_metrics (Dict[str, Any]): Stock volatility analysis results
            regression_metrics (Optional[Dict[str, Any]]): Market regression analysis
            risk_metrics (Optional[Dict[str, Any]]): Additional risk characteristics
            factor_summary (Optional[Any]): Multi-factor analysis DataFrame
            factor_exposures (Optional[Dict[str, Any]]): Factor metadata
            factor_proxies (Optional[Dict[str, Any]]): Factor proxy mappings
            analysis_metadata (Dict[str, Any]): Analysis configuration
            
        Returns:
            StockAnalysisResult: Fully populated stock analysis with multi-factor support
        """
        # Create the stock_data dict that the constructor expects
        stock_data = {
            "vol_metrics": volatility_metrics,
            "regression_metrics": regression_metrics or {},
            "risk_metrics": risk_metrics or {},
            "factor_summary": factor_summary,
            "factor_exposures": factor_exposures or {},
            "factor_proxies": factor_proxies or {},
            "analysis_metadata": analysis_metadata or {}
        }
        
        # Create the result object
        result = cls(stock_data=stock_data, ticker=ticker,
                     interest_rate_beta=interest_rate_beta,
                     effective_duration=effective_duration,
                     rate_regression_r2=rate_regression_r2,
                     key_rate_breakdown=key_rate_breakdown)
        
        # Set additional fields that CLI formatting expects
        result.analysis_period = analysis_period
        result.analysis_type = analysis_type
        
        # Preserve any additional fields that to_api_response() expects
        result.raw_data = {
            "analysis_period": analysis_period,
            "volatility_metrics": volatility_metrics,
            "regression_metrics": regression_metrics,
            "risk_metrics": risk_metrics,
            "factor_summary": factor_summary
        }
        
        return result

    def to_cli_report(self) -> str:
        """Generate complete CLI formatted report - IDENTICAL to current output"""
        sections = []
        sections.append(self._format_stock_summary())        # Stock ticker and period
        sections.append(self._format_volatility_metrics())   # Volatility analysis  
        sections.append(self._format_factor_analysis())      # Factor exposures (if applicable)
        sections.append(self._format_regression_metrics())   # Market regression
        sections.append(self._format_risk_decomposition())   # Risk breakdown
        return "\n\n".join(sections)
    
    def _format_stock_summary(self) -> str:
        """Format stock header - EXACT copy of run_stock lines ~580-585"""
        lines = [f"=== Stock Analysis: {self.ticker} ==="]
        analysis_period = getattr(self, 'analysis_period', {})
        if analysis_period:
            lines.append(f"Analysis Period: {analysis_period.get('start_date', 'N/A')} to {analysis_period.get('end_date', 'N/A')}")
        analysis_type = getattr(self, 'analysis_type', 'multi_factor')
        lines.append(f"Analysis Type: {analysis_type}")
        return "\n".join(lines)
    
    def _format_volatility_metrics(self) -> str:
        """Format volatility section - EXACT copy of run_stock lines ~590-600"""
        vol = self.volatility_metrics
        lines = ["=== Volatility Metrics ==="]
        lines.append(f"Annual Volatility:    {vol.get('volatility_annual', vol.get('annual_vol', 0)):.1%}")
        lines.append(f"Monthly Volatility:   {vol.get('volatility_monthly', vol.get('monthly_vol', 0)):.1%}") 
        lines.append(f"Sharpe Ratio:         {vol.get('sharpe_ratio', 0):.2f}")
        lines.append(f"Maximum Drawdown:     {vol.get('max_drawdown', 0):.1%}")
        return "\n".join(lines)
        
    def _format_factor_analysis(self) -> str:
        """Format factor exposures - EXACT copy of run_stock lines ~605-625"""
        if not self.factor_exposures and not self.interest_rate_beta:
            return ""
        lines = ["=== Factor Exposures ==="]
        for factor_name, exposure in self.factor_exposures.items():
            beta = exposure.get('beta', 0)
            r_sq = exposure.get('r_squared', 0)
            proxy = exposure.get('proxy', 'N/A')
            lines.append(f"{factor_name:<12} β = {beta:+.2f}  R² = {r_sq:.3f}  Proxy: {proxy}")
        # Add Interest Rate section when available
        if self.interest_rate_beta is not None:
            lines.append("")
            lines.append("— Interest Rate Sensitivity —")
            lines.append(f"Interest Rate Beta:   {self.interest_rate_beta:+.2f}")
            if self.effective_duration is not None:
                lines.append(f"Effective Duration:   {self.effective_duration:.2f} years")
            if self.rate_regression_r2 is not None:
                lines.append(f"Rate R²:              {self.rate_regression_r2:.3f}")
            if self.key_rate_breakdown:
                for k, v in self.key_rate_breakdown.items():
                    lines.append(f"{k:<16}: {v:+.2f}")
        return "\n".join(lines)
        
    def _format_regression_metrics(self) -> str:
        """Format market regression - EXACT copy of run_stock lines ~630-640"""
        if hasattr(self, 'regression_metrics') and self.regression_metrics:
            reg = self.regression_metrics
            lines = ["=== Market Regression ==="]
            lines.append(f"Market Beta:          {reg.get('beta', 0):.2f}")
            lines.append(f"Alpha (Annual):       {reg.get('alpha', 0):.1%}")
            lines.append(f"R-Squared:            {reg.get('r_squared', 0):.3f}")
            lines.append(f"Correlation:          {reg.get('correlation', 0):.3f}")
            return "\n".join(lines)
        elif hasattr(self, 'risk_metrics') and self.risk_metrics:
            risk = self.risk_metrics
            lines = ["=== Market Risk Profile ==="]
            lines.append(f"Market Beta:          {risk.get('beta', 0):.2f}")
            lines.append(f"Alpha (Annual):       {risk.get('alpha', 0):.1%}")
            lines.append(f"R-Squared:            {risk.get('r_squared', 0):.3f}")
            return "\n".join(lines)
        return ""
    
    def _format_risk_decomposition(self) -> str:
        """Format risk decomposition section"""
        if hasattr(self, 'regression_metrics') and self.regression_metrics:
            reg = self.regression_metrics
            idio_vol = reg.get('idio_vol_m', 0)
            if idio_vol > 0:
                lines = ["=== Risk Decomposition ==="]
                lines.append(f"Idiosyncratic Vol:    {idio_vol:.1%}")
                return "\n".join(lines)
        return ""

    def to_formatted_report(self) -> str:
        """Format stock analysis results for display (identical to to_cli_report())."""
        return self.to_cli_report() 
    
    def to_api_response(self) -> Dict[str, Any]:
        """
        Convert StockAnalysisResult to comprehensive API response format.
        
        CONSUMER ANALYSIS:
        - Direct API: Uses full structured response for programmatic stock analysis and factor exposure research
        - Claude/AI: Only uses formatted_report (ignores all structured data)
        - Frontend: Uses adapters to transform structured data for stock analysis dashboards and factor charts
        
        Converts internal data structures (including pandas DataFrames) to 
        JSON-serializable dictionaries for API responses. Provides comprehensive
        multi-factor risk analysis data for programmatic consumption.
        
        Returns:
            Dict[str, Any]: JSON-serializable dictionary containing:
            
                📊 CORE IDENTIFIERS:
                - ticker: Stock symbol (e.g., "AAPL")
                - analysis_date: ISO-formatted analysis timestamp
                
                📈 VOLATILITY ANALYSIS:
                - volatility_metrics: Historical volatility statistics
                  • monthly_vol: Monthly volatility (standard deviation of returns)
                  • annual_vol: Annualized volatility (monthly_vol * sqrt(12))
                
                📉 MARKET REGRESSION:
                - regression_metrics: Market regression analysis (vs benchmark)
                  • beta: Market sensitivity coefficient (slope from OLS regression)
                  • alpha: Intercept from OLS regression
                  • r_squared: Model R-squared (proportion of variance explained)
                  • idio_vol_m: Idiosyncratic volatility (standard deviation of residuals)
                
                🎯 MULTI-FACTOR ANALYSIS:
                - factor_summary: Comprehensive factor exposure analysis (pandas DataFrame → dict)
                  Structure: {"beta": {...}, "r_squared": {...}, "idio_vol_m": {...}}
                  Each contains factor exposures for:
                  • market: Market factor (typically SPY proxy)
                  • momentum: Momentum factor (ETF proxy based on factor_proxies)
                  • value: Value factor (ETF proxy based on factor_proxies)
                  • industry: Industry sector factor (ETF proxy based on factor_proxies)
                  • subindustry: Sub-industry peer group factor (list of peer tickers)
                  
                  Metrics per factor:
                  • beta: Factor exposure coefficient (how much stock moves with factor)
                  • r_squared: Variance explained by this factor (0-1 scale)
                  • idio_vol_m: Unexplained monthly volatility after factor
                
                🔍 ENHANCED METADATA:
                - factor_exposures: Structured factor metadata with proxy info
                - factor_proxies: ETF/ticker mappings used for each factor
                - analysis_metadata: Analysis configuration and timestamps
                - risk_metrics: Additional risk characteristics (if available)
                
                🧭 INTEREST RATE (BONDS ONLY):
                - interest_rate_beta: Aggregated key‑rate beta (sum over Δy factors)
                - effective_duration: abs(interest_rate_beta) in years
                - rate_regression_r2: Adjusted R² from multivariate rate regression
                - key_rate_breakdown: Per-maturity betas (e.g., UST2Y/UST5Y/UST10Y/UST30Y)
        """
        # 🔄 Convert factor_summary from pandas DataFrame to JSON-serializable dict
        # factor_summary is generated by compute_factor_metrics() and contains:
        # - Rows: factors (market, momentum, value, industry, subindustry)  
        # - Columns: beta, r_squared, idio_vol_m
        # Result: {"beta": {"market": 1.22, ...}, "r_squared": {"market": 0.658, ...}, "idio_vol_m": {"market": 0.037, ...}}
        if self.factor_summary is not None and hasattr(self.factor_summary, 'to_dict'):
            factor_summary_dict = self.factor_summary.to_dict() if not getattr(self.factor_summary, 'empty', False) else {}
        else:
            factor_summary_dict = {}

        return {
            # 📊 Core identifiers
            "ticker": self.ticker,                                    # Stock symbol (str)
            "analysis_date": self.analysis_date.isoformat(),          # Timestamp (ISO format)
            
            # 📈 Volatility analysis  
            "volatility_metrics": self.volatility_metrics,            # Dict: monthly_vol, annual_vol
            
            # 📉 Market regression analysis
            "regression_metrics": self.regression_metrics,            # Dict: beta, alpha, r_squared, idio_vol_m
            
            # 🎯 Multi-factor analysis (CORE FEATURE)
            "factor_summary": factor_summary_dict,                    # Dict: {"beta": {factors...}, "r_squared": {factors...}, "idio_vol_m": {factors...}}
                                                                      # Contains exposures for: market, momentum, value, industry, subindustry
            
            # 🔍 Enhanced metadata and context
            "factor_exposures": self.factor_exposures,                # Dict: Structured factor metadata with proxy info
            "factor_proxies": self.factor_proxies,                    # Dict: ETF/ticker mappings used for each factor (e.g., {"market": "SPY", "momentum": "MTUM"})
            "analysis_metadata": self.analysis_metadata,              # Dict: Analysis configuration, timestamps, and settings
            "risk_metrics": self.risk_metrics,                        # Dict: Additional risk characteristics (if available)
            # 🔹 Interest rate analytics (when available for bonds)
            "interest_rate_beta": self.interest_rate_beta,
            "effective_duration": self.effective_duration,
            "rate_regression_r2": self.rate_regression_r2,
            "key_rate_breakdown": self.key_rate_breakdown,
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



 
# -----------------------------
# Factor Intelligence results
# -----------------------------

class FactorCorrelationResult:
    """
    Structured result for factor correlation analysis.

    Attributes
    ----------
    matrices : Dict[str, Any]
        Per-category correlation matrices (pandas DataFrames).
    overlays : Dict[str, Any]
        Optional overlay matrices and metadata (rate/market/macro views).
    data_quality : Dict[str, Any]
        Coverage and exclusion info by category.
    performance : Dict[str, Any]
        Timing metrics (ms) for correlation construction.
    analysis_metadata : Dict[str, Any]
        Echo of analysis window and universe hash.
    """

    def __init__(self, matrices: Dict[str, Any], overlays: Dict[str, Any], data_quality: Dict[str, Any], performance: Dict[str, Any], analysis_metadata: Dict[str, Any]):
        self.matrices = matrices or {}
        self.overlays = overlays or {}
        self.data_quality = data_quality or {}
        self.performance = performance or {}
        self.analysis_metadata = analysis_metadata or {}

    @classmethod
    def from_core_analysis(cls,
                          core_matrices: Dict[str, Any],
                          overlays: Dict[str, Any],
                          data_quality: Dict[str, Any],
                          performance: Dict[str, Any],
                          analysis_metadata: Dict[str, Any]) -> 'FactorCorrelationResult':
        """
        Create FactorCorrelationResult from core factor intelligence analysis data.

        ARCHITECTURE CONTEXT:
        This is the primary factory method for creating FactorCorrelationResult objects from
        core factor intelligence functions (compute_per_category_correlation_matrices, etc.).
        It transforms raw correlation analysis data into a structured result object ready for API responses.

        DATA FLOW:
        factor_intelligence_service.analyze_correlations() → core analysis data → from_core_analysis() → FactorCorrelationResult

        INPUT DATA STRUCTURE:
        - core_matrices: Output from compute_per_category_correlation_matrices() containing:
          • Per-category correlation matrices (Dict[str, pd.DataFrame])
        - overlays: Rate/market sensitivity and macro matrices (Dict[str, Any])
        - data_quality: Coverage and exclusion info by category (Dict[str, Any])
        - performance: Timing metrics (ms) for correlation construction (Dict[str, Any])
        - analysis_metadata: Analysis window, universe hash, and configuration (Dict[str, Any])

        Returns
        -------
        FactorCorrelationResult
            Structured result object ready for API serialization
        """
        return cls(
            matrices=core_matrices,
            overlays=overlays,
            data_quality=data_quality,
            performance=performance,
            analysis_metadata=analysis_metadata
        )

    @staticmethod
    def _df_to_nested(df) -> Dict[str, Dict[str, float]]:
        try:
            return {r: {c: float(v) for c, v in row.items()} for r, row in df.round(4).to_dict(orient='index').items()}
        except Exception:
            return {}

    def to_dict(self) -> Dict[str, Any]:
        mats = {}
        for name, df in self.matrices.items():
            mats[name] = self._df_to_nested(df) if hasattr(df, 'to_dict') else {}
        return {
            'matrices': mats,
            'overlays': self.overlays,
            'data_quality': self.data_quality,
            'performance': self.performance,
            'analysis_metadata': self.analysis_metadata,
        }

    def to_api_response(self) -> Dict[str, Any]:
        """
        Convert FactorCorrelationResult to comprehensive API response format.

        CONSUMER ANALYSIS:
        - Direct API: Uses full structured response for factor analysis and visualization
        - Claude/AI: Uses formatted_report (to_cli_report) for human-readable analysis
        - Frontend: Uses matrices and overlays for correlation heatmaps and charts

        Returns structured data suitable for JSON serialization and API responses.
        This method provides complete factor correlation analysis including matrices,
        overlays, performance metrics, and data quality information.

        Returns
        -------
        Dict[str, Any]
            Dictionary containing all factor correlation data with the following fields:

            - matrices: Dict[str, Dict[str, Dict[str, float]]] - Per-category correlation matrices
            - overlays: Dict[str, Any] - Rate/market sensitivity and macro matrices
            - data_quality: Dict[str, Any] - Coverage and exclusion info by category
            - performance: Dict[str, Any] - Timing metrics (ms) for correlation construction
            - analysis_metadata: Dict[str, Any] - Analysis window, universe hash, and configuration
            - formatted_report: str - Human-readable CLI report (identical to to_cli_report)

        Example
        -------
        ```python
        result = service.analyze_correlations(start_date="2020-01-01", end_date="2024-12-31")
        api_data = result.to_api_response()

        # Access correlation matrices
        industry_matrix = api_data["matrices"]["industry"]

        # Access sensitivity overlays
        rate_sensitivity = api_data["overlays"]["rate_sensitivity"]

        # Access performance metrics
        timing = api_data["performance"]
        ```
        """
        # Convert matrices to nested format for JSON serialization
        matrices_serialized = {}
        for name, df in self.matrices.items():
            matrices_serialized[name] = self._df_to_nested(df) if hasattr(df, 'to_dict') else {}

        return {
            "matrices": matrices_serialized,                                    # DICT: Per-category correlation matrices (nested format)
            "overlays": _convert_to_json_serializable(self.overlays),          # DICT: Rate/market sensitivity and macro matrices
            "data_quality": _convert_to_json_serializable(self.data_quality),  # DICT: Coverage and exclusion info
            "performance": _convert_to_json_serializable(self.performance),    # DICT: Timing metrics
            "analysis_metadata": _convert_to_json_serializable(self.analysis_metadata),  # DICT: Analysis configuration
            "formatted_report": self.to_cli_report(),                          # STR: Human-readable report
        }

    def to_cli_report(self, max_rows: int = 10) -> str:
        """Human-readable summary for CLI/AI contexts.

        Includes:
        - Per-category correlation matrices (top-left submatrix)
        - Macro overlays when present:
          • Macro composite matrix (equity/fixed_income/cash/commodity/crypto)
          • Macro ETF matrix (curated), if computed
        """
        lines: List[str] = []
        lines.append("FACTOR CORRELATIONS (summary)")
        for name, df in self.matrices.items():
            lines.append(f"\n[{name}]\n" + ("(empty)" if getattr(df, "empty", True) else ""))
            if getattr(df, "empty", True):
                continue
            # Show top-left submatrix up to max_rows
            sub = df.copy()
            rows = list(sub.index)[:max_rows]
            cols = list(sub.columns)[:min(max_rows, len(sub.columns))]
            header = "        " + " ".join([c[:8].ljust(9) for c in cols])
            lines.append(header)
            for r in rows:
                rowvals = [f"{float(sub.loc[r, c]):>+0.2f}" if c in sub.columns else "" for c in cols]
                lines.append(f"{r[:8].ljust(8)}  " + " ".join(v.rjust(6) for v in rowvals))

        # Overlays: Macro composite and curated macro ETF matrices (if present)
        def _format_matrix_block(title: str, df: Any) -> List[str]:
            out: List[str] = []
            out.append(f"\n{title}")
            if df is None or getattr(df, 'empty', True):
                out.append("(empty)")
                return out
            # Limit for readability
            rows = list(df.index)[:max_rows]
            cols = list(df.columns)[:min(max_rows, len(df.columns))]
            sub = df.reindex(index=rows, columns=cols).copy()
            header = "        " + " ".join([str(c)[:10].ljust(11) for c in sub.columns])
            out.append(header)
            for r in sub.index:
                rowvals = []
                for c in sub.columns:
                    try:
                        v = float(sub.loc[r, c])
                        rowvals.append(f"{v:+0.2f}")
                    except Exception:
                        rowvals.append("   nan")
                out.append(f"{str(r)[:10].ljust(10)}  " + " ".join(v.rjust(6) for v in rowvals))
            return out

        try:
            ov = self.overlays or {}
            if isinstance(ov, dict):
                mc = ov.get('macro_composite_matrix')
                if isinstance(mc, dict) and hasattr(mc.get('matrix'), 'corr'):
                    lines.extend(_format_matrix_block("MACRO COMPOSITE MATRIX (equity/fixed_income/cash/commodity/crypto)", mc.get('matrix')))

                me = ov.get('macro_etf_matrix')
                if isinstance(me, dict) and hasattr(me.get('matrix'), 'corr'):
                    # group sizes (optional)
                    groups = me.get('groups') or {}
                    if isinstance(groups, dict) and groups:
                        lines.append("\nMacro ETF groups:")
                        for g, etfs in groups.items():
                            lines.append(f"  - {g}: {len(etfs)} ETFs")
                    lines.extend(_format_matrix_block("MACRO ETF MATRIX (curated)", me.get('matrix')))
        except Exception:
            # Overlays are optional; keep CLI resilient
            pass
        return "\n".join(lines)


class FactorPerformanceResult:
    """
    Structured result for factor performance analysis.

    Attributes
    ----------
    per_factor : Dict[str, Any]
        Performance metrics per ETF.
    composites : Dict[str, Any]
        Composite performance across macro and factor categories.
    data_quality : Dict[str, Any]
        Coverage of tickers/groups used in composites.
    performance : Dict[str, Any]
        Timing metrics (ms).
    analysis_metadata : Dict[str, Any]
        Echo of analysis window and universe hash.
    """

    def __init__(self, per_factor: Dict[str, Any], composites: Dict[str, Any], data_quality: Dict[str, Any], performance: Dict[str, Any], analysis_metadata: Dict[str, Any]):
        self.per_factor = per_factor or {}
        self.composites = composites or {}
        self.data_quality = data_quality or {}
        self.performance = performance or {}
        self.analysis_metadata = analysis_metadata or {}

    @classmethod
    def from_core_analysis(cls,
                          per_factor_metrics: Dict[str, Any],
                          composite_performance: Dict[str, Any],
                          data_quality: Dict[str, Any],
                          performance: Dict[str, Any],
                          analysis_metadata: Dict[str, Any]) -> 'FactorPerformanceResult':
        """
        Create FactorPerformanceResult from core factor intelligence performance analysis data.

        ARCHITECTURE CONTEXT:
        This is the primary factory method for creating FactorPerformanceResult objects from
        core factor intelligence functions (compute_factor_performance_profiles, compute_composite_performance).
        It transforms raw performance analysis data into a structured result object ready for API responses.

        DATA FLOW:
        factor_intelligence_service.analyze_performance() → core analysis data → from_core_analysis() → FactorPerformanceResult

        INPUT DATA STRUCTURE:
        - per_factor_metrics: Output from compute_factor_performance_profiles() containing:
          • Performance metrics per ETF (Sharpe, volatility, returns) (Dict[str, Any])
        - composite_performance: Output from compute_composite_performance() containing:
          • Composite performance across macro and factor categories (Dict[str, Any])
        - data_quality: Coverage of tickers/groups used in composites (Dict[str, Any])
        - performance: Timing metrics (ms) for performance calculations (Dict[str, Any])
        - analysis_metadata: Analysis window, universe hash, and configuration (Dict[str, Any])

        Returns
        -------
        FactorPerformanceResult
            Structured result object ready for API serialization
        """
        return cls(
            per_factor=per_factor_metrics,
            composites=composite_performance,
            data_quality=data_quality,
            performance=performance,
            analysis_metadata=analysis_metadata
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            'per_factor': self.per_factor,
            'composites': self.composites,
            'data_quality': self.data_quality,
            'performance': self.performance,
            'analysis_metadata': self.analysis_metadata,
        }

    def to_api_response(self) -> Dict[str, Any]:
        """
        Convert FactorPerformanceResult to comprehensive API response format.

        CONSUMER ANALYSIS:
        - Direct API: Uses full structured response for performance analysis and charts
        - Claude/AI: Uses formatted_report (to_cli_report) for human-readable summaries
        - Frontend: Uses per_factor and composites for performance visualization

        Returns structured data suitable for JSON serialization and API responses.
        This method provides complete factor performance analysis including per-ETF
        metrics, composite performance, and data quality information.

        Returns
        -------
        Dict[str, Any]
            Dictionary containing all factor performance data with the following fields:

            - per_factor: Dict[str, Any] - Performance metrics per ETF (Sharpe, volatility, returns)
            - composites: Dict[str, Any] - Composite performance across macro and factor categories
            - data_quality: Dict[str, Any] - Coverage of tickers/groups used in composites
            - performance: Dict[str, Any] - Timing metrics (ms) for performance calculations
            - analysis_metadata: Dict[str, Any] - Analysis window, universe hash, and configuration
            - formatted_report: str - Human-readable report (identical to to_cli_report)
        """
        return {
            "per_factor": _convert_to_json_serializable(self.per_factor),        # DICT: Performance metrics per ETF
            "composites": _convert_to_json_serializable(self.composites),        # DICT: Composite performance data
            "data_quality": _convert_to_json_serializable(self.data_quality),    # DICT: Coverage and quality info
            "performance": _convert_to_json_serializable(self.performance),      # DICT: Timing metrics
            "analysis_metadata": _convert_to_json_serializable(self.analysis_metadata),  # DICT: Analysis configuration
            "formatted_report": self.to_cli_report(),                           # STR: Human-readable report
        }

    def to_cli_report(self, top_n: int = 10) -> str:
        """Human-readable summary highlighting top Sharpe factors and macro composites."""
        lines: List[str] = []
        lines.append("FACTOR PERFORMANCE (summary)")
        pf = self.per_factor or {}
        # Sort by Sharpe where available
        try:
            ranked = sorted(pf.items(), key=lambda kv: (-(kv[1].get('sharpe_ratio') or float('-inf'))))[:top_n]
        except Exception:
            ranked = list(pf.items())[:top_n]
        if ranked:
            lines.append("\nTop factors by Sharpe:")
            for k, v in ranked:
                sr = v.get('sharpe_ratio')
                vol = v.get('volatility')
                ar = v.get('annual_return')
                lines.append(f"  {k:<10}  Sharpe={sr!s:<6}  Vol={vol!s:<6}  AnnRet={ar!s:<6}")
        comps = self.composites or {}
        macro = comps.get('macro') or {}
        if macro:
            lines.append("\nMacro composites:")
            for name, metrics in macro.items():
                sr = metrics.get('sharpe_ratio'); vol = metrics.get('volatility'); ar = metrics.get('annual_return')
                lines.append(f"  {name:<12}  Sharpe={sr!s:<6}  Vol={vol!s:<6}  AnnRet={ar!s:<6}")
        return "\n".join(lines)


class OffsetRecommendationResult:
    """
    Structured result for correlation‑based offset recommendations.
    """

    def __init__(self, overexposed_label: str, recommendations: List[Dict[str, Any]], analysis_metadata: Dict[str, Any]):
        self.overexposed_label = overexposed_label
        self.recommendations = recommendations or []
        self.analysis_metadata = analysis_metadata or {}

    @classmethod
    def from_core_analysis(cls,
                          overexposed_label: str,
                          offset_recommendations: List[Dict[str, Any]],
                          analysis_metadata: Dict[str, Any]) -> 'OffsetRecommendationResult':
        """
        Create OffsetRecommendationResult from core factor intelligence offset analysis data.

        ARCHITECTURE CONTEXT:
        This is the primary factory method for creating OffsetRecommendationResult objects from
        core factor intelligence offset recommendation functions.
        It transforms raw offset analysis data into a structured result object ready for API responses.

        DATA FLOW:
        factor_intelligence_service.recommend_offsets() → core analysis data → from_core_analysis() → OffsetRecommendationResult

        INPUT DATA STRUCTURE:
        - overexposed_label: The factor/category that is overexposed (str)
        - offset_recommendations: List of offset recommendations with correlation data (List[Dict[str, Any]])
        - analysis_metadata: Analysis window, universe hash, and configuration (Dict[str, Any])

        Returns
        -------
        OffsetRecommendationResult
            Structured result object ready for API serialization
        """
        return cls(
            overexposed_label=overexposed_label,
            recommendations=offset_recommendations,
            analysis_metadata=analysis_metadata
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            'overexposed_label': self.overexposed_label,
            'recommendations': self.recommendations,
            'analysis_metadata': self.analysis_metadata,
        }

    def to_api_response(self) -> Dict[str, Any]:
        """
        Convert OffsetRecommendationResult to comprehensive API response format.

        CONSUMER ANALYSIS:
        - Direct API: Uses full structured response for offset recommendations and portfolio rebalancing
        - Claude/AI: Uses formatted_report (to_cli_report) for human-readable recommendations
        - Frontend: Uses recommendations list for displaying offset suggestions with correlations

        Returns structured data suitable for JSON serialization and API responses.
        This method provides complete offset recommendation analysis including correlation-based
        suggestions for portfolio rebalancing.

        Returns
        -------
        Dict[str, Any]
            Dictionary containing all offset recommendation data with the following fields:

            - overexposed_label: str - The overexposed factor/ETF being analyzed
            - recommendations: List[Dict] - Ranked offset recommendations with correlations and metrics
            - analysis_metadata: Dict[str, Any] - Analysis configuration and metadata
            - formatted_report: str - Human-readable report (identical to to_cli_report)
        """
        return {
            "overexposed_label": self.overexposed_label,                        # STR: Overexposed factor identifier
            "recommendations": _convert_to_json_serializable(self.recommendations),  # LIST: Offset recommendations
            "analysis_metadata": _convert_to_json_serializable(self.analysis_metadata),  # DICT: Analysis metadata
            "formatted_report": self.to_cli_report(),                          # STR: Human-readable report
        }

    def to_cli_report(self, top_n: int = 10) -> str:
        """Human-readable recommendations list with basic ranking fields."""
        lines: List[str] = []
        lines.append(f"OFFSET RECOMMENDATIONS for {self.overexposed_label}")
        recs = (self.recommendations or [])[:top_n]
        if not recs:
            lines.append("(none)")
            return "\n".join(lines)
        for i, r in enumerate(recs, 1):
            lab = r.get('label') or r.get('factor') or r.get('ticker') or 'unknown'
            corr = r.get('correlation')
            sh = r.get('sharpe_ratio')
            cat = r.get('category')
            lines.append(f"  {i:>2}. {lab:<12}  Corr={corr!s:<6}  Sharpe={sh!s:<6}  Cat={cat!s:<10}")
        return "\n".join(lines)


class PortfolioOffsetRecommendationResult:
    """
    Portfolio-aware offset recommendations with detected drivers and suggested sizing.

    Attributes
    ----------
    drivers : List[Dict[str, Any]]
        Detected risk drivers (e.g., industries/factors) with metrics.
    recommendations : List[Dict[str, Any]]
        Recommended hedges with correlation, Sharpe, category, suggested_weight, and rationale.
    analysis_metadata : Dict[str, Any]
        Portfolio snapshot and configuration used for analysis.
    """

    def __init__(self, drivers: List[Dict[str, Any]], recommendations: List[Dict[str, Any]], analysis_metadata: Dict[str, Any]):
        self.drivers = drivers or []
        self.recommendations = recommendations or []
        self.analysis_metadata = analysis_metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            'drivers': self.drivers,
            'recommendations': self.recommendations,
            'analysis_metadata': self.analysis_metadata,
        }

    def to_api_response(self) -> Dict[str, Any]:
        return {
            'drivers': _convert_to_json_serializable(self.drivers),
            'recommendations': _convert_to_json_serializable(self.recommendations),
            'analysis_metadata': _convert_to_json_serializable(self.analysis_metadata),
            'formatted_report': self.to_cli_report(),
        }

    def to_cli_report(self, top_n: int = 10) -> str:
        lines: List[str] = []
        lines.append("PORTFOLIO-AWARE OFFSET RECOMMENDATIONS")
        if self.drivers:
            lines.append("\nTop risk drivers:")
            for d in self.drivers:
                lab = d.get('label') or d.get('id')
                pct = d.get('percent_of_portfolio') or d.get('factor_pct')
                lines.append(f"  • {lab}: {pct!s}")
        recs = (self.recommendations or [])[:top_n]
        lines.append("\nRecommended hedges:")
        if not recs:
            lines.append("  (none)")
            return "\n".join(lines)
        for i, r in enumerate(recs, 1):
            lab = r.get('label') or r.get('ticker')
            cat = r.get('category')
            corr = r.get('correlation')
            sh = r.get('sharpe_ratio')
            w = r.get('suggested_weight')
            lines.append(f"  {i:>2}. {lab:<10}  Cat={cat!s:<10} Corr={corr!s:<6} Sharpe={sh!s:<6} Wgt={w!s:<6}")
        return "\n".join(lines)

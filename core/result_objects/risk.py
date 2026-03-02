"""Risk result objects."""

from typing import Dict, Any, Optional, List, Union, Tuple
import numbers
import math
import pandas as pd
from datetime import datetime, UTC
import json
import numpy as np
from dataclasses import dataclass, field
from portfolio_risk_engine.allocation_drift import compute_allocation_drift
from utils.serialization import make_json_safe
from core.constants import get_asset_class_color, get_asset_class_display_name
from ._helpers import (_convert_to_json_serializable, _clean_nan_values, _format_df_as_text, _abbreviate_labels, _DEFAULT_INDUSTRY_ABBR_MAP)

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
    notional_leverage: Optional[float] = None
    fx_attribution: Optional[Dict[str, Dict[str, Any]]] = None
    
    @property
    def portfolio_weights(self) -> Optional[Dict[str, float]]:
        """Extract just the portfolio weights from the allocations DataFrame"""
        if self.allocations is None:
            return None
        return self.allocations["Portfolio Weight"].to_dict()
    
    def get_summary(self) -> Dict[str, Any]:
        """
        Get a portfolio-level snapshot for sizing, exposure, and concentration.

        This summary intentionally excludes per-position details (risk attribution,
        factor betas by position). Those are exposed via dedicated getters.
        """
        position_count = (self.analysis_metadata or {}).get("active_positions")
        if position_count is None:
            position_count = len(self.risk_contributions) if self.risk_contributions is not None else 0

        return {
            "total_value": self.total_value,
            "net_exposure": self.net_exposure,
            "gross_exposure": self.gross_exposure,
            "leverage": self.leverage,
            "notional_leverage": self.notional_leverage,
            "position_count": position_count,
            "volatility_annual": self.volatility_annual,
            "volatility_monthly": self.volatility_monthly,
            "herfindahl": self.herfindahl,
            "factor_variance_pct": self.variance_decomposition.get('factor_pct', 0),
            "idiosyncratic_variance_pct": self.variance_decomposition.get('idiosyncratic_pct', 0),
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
    
    def get_top_risk_contributors(self, n: int = 5) -> List[Dict[str, Any]]:
        """
        Get top N risk contributors with weight, beta, and volatility context.
        """
        if self.euler_variance_pct is None or len(self.euler_variance_pct) == 0:
            return []

        top_tickers = self.euler_variance_pct.nlargest(n).index.tolist()
        rows: List[Dict[str, Any]] = []
        for ticker in top_tickers:
            risk_raw = self._safe_num(self.euler_variance_pct.get(ticker), default=0.0)
            rows.append(
                {
                    "ticker": ticker,
                    "weight_pct": round(self._get_weight(ticker) * 100, 2),
                    "risk_pct": round(risk_raw * 100, 2),
                    "beta": self._safe_float(self.stock_betas, ticker, "market"),
                    "volatility": self._safe_float(self.asset_vol_summary, ticker, "Vol A"),
                }
            )
        return rows

    def get_compliance_summary(self) -> Dict[str, Any]:
        """Get a unified compliance summary from risk and beta checks."""
        violations: List[Dict[str, Any]] = []
        for check in (self.risk_checks or []):
            if not check.get("Pass", True):
                violations.append(
                    {
                        "metric": check.get("Metric"),
                        "actual": check.get("Actual"),
                        "limit": check.get("Limit"),
                    }
                )

        beta_breaches: List[Dict[str, Any]] = []
        for check in (self.beta_checks or []):
            if not check.get("pass", True):
                beta_breaches.append(
                    {
                        "factor": check.get("factor"),
                        "portfolio_beta": check.get("portfolio_beta"),
                        "max_allowed_beta": check.get("max_allowed_beta"),
                    }
                )

        return {
            "is_compliant": len(violations) == 0 and len(beta_breaches) == 0,
            "violation_count": len(violations) + len(beta_breaches),
            "violations": violations,
            "beta_breaches": beta_breaches,
        }

    def get_industry_concentration(self, n: int = 5) -> List[Dict[str, Any]]:
        """
        Get top industries by positive variance contribution (hedges excluded).
        """
        pct = (self.industry_variance or {}).get("percent_of_portfolio", {}) or {}
        positive = [(industry, val) for industry, val in pct.items() if self._safe_num(val, 0.0) > 0.0]
        sorted_industries = sorted(positive, key=lambda x: self._safe_num(x[1], 0.0), reverse=True)[:n]
        return [
            {"industry": industry, "variance_pct": round(self._safe_num(val, 0.0) * 100, 2)}
            for industry, val in sorted_industries
        ]

    def _get_weight(self, ticker: str) -> float:
        """Extract portfolio weight for a ticker from the allocations DataFrame."""
        if self.allocations is not None and ticker in self.allocations.index and "Portfolio Weight" in self.allocations.columns:
            return self._safe_num(self.allocations.loc[ticker, "Portfolio Weight"], default=0.0)
        return 0.0

    def _safe_float(self, df: Optional[pd.DataFrame], ticker: str, col: str) -> Optional[float]:
        """Safely extract a rounded float from a DataFrame."""
        try:
            if df is not None and ticker in df.index and col in df.columns:
                val = df.loc[ticker, col]
                if val is not None and pd.notna(val):
                    return round(float(val), 4)
        except (TypeError, ValueError, KeyError):
            pass
        return None

    @staticmethod
    def _safe_num(val: Any, default: float = 0.0) -> float:
        """Coerce value to float, returning default for None/NaN/non-numeric."""
        if val is None:
            return default
        try:
            numeric = float(val)
            return default if numeric != numeric else numeric
        except (TypeError, ValueError):
            return default

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
            from core.portfolio_config import get_cash_positions
            
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
        
        current_allocation_pct = {
            asset_class: float(data["total_weight"]) * 100.0
            for asset_class, data in asset_groups.items()
        }
        raw_target_allocation = (self.analysis_metadata or {}).get("target_allocation")
        target_allocation = raw_target_allocation if isinstance(raw_target_allocation, dict) else {}
        drift_rows = compute_allocation_drift(current_allocation_pct, target_allocation) if target_allocation else []
        drift_by_class = {str(row["asset_class"]): row for row in drift_rows}

        # Build frontend-compatible array
        allocation_breakdown = []
        for asset_class, data in asset_groups.items():
            period_return = perf_data.get(asset_class)
            drift = drift_by_class.get(asset_class)
            allocation_breakdown.append({
                # Keep category as canonical key (snake_case) for frontend adapters
                'category': asset_class,
                'percentage': round(data['total_weight'] * 100, 1),
                'target_pct': drift.get('target_pct') if drift else None,
                'drift_pct': drift.get('drift_pct') if drift else None,
                'drift_status': drift.get('drift_status') if drift else None,
                'drift_severity': drift.get('drift_severity') if drift else None,
                'value': f"${data['total_value']:,.0f}",
                'change': (f"{period_return:+.1%}" if isinstance(period_return, (int, float)) else "+0.0%"),
                'changeType': _classify_change(period_return if isinstance(period_return, (int, float)) else 0.0),
                'color': get_asset_class_color(asset_class),
                'holdings': data['holdings']
            })

        current_classes = set(asset_groups.keys())
        for asset_class, drift in drift_by_class.items():
            if asset_class in current_classes:
                continue
            allocation_breakdown.append(
                {
                    "category": asset_class,
                    "percentage": 0.0,
                    "target_pct": drift.get("target_pct"),
                    "drift_pct": drift.get("drift_pct"),
                    "drift_status": drift.get("drift_status"),
                    "drift_severity": drift.get("drift_severity"),
                    "value": "$0",
                    "change": "+0.0%",
                    "changeType": "neutral",
                    "color": get_asset_class_color(asset_class),
                    "holdings": [],
                }
            )
        
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
            # Phase 2 cleanup: removed risk_checks, beta_checks (redundant with risk_limit_violations_summary, beta_exposure_checks_table)
            "volatility_annual": self.volatility_annual,  # Volatility Annual   
            "volatility_monthly": self.volatility_monthly,  # Volatility Monthly
            "herfindahl": self.herfindahl,  # Herfindahl Index
            "portfolio_returns": _convert_to_json_serializable(self.portfolio_returns),  # Portfolio Returns
            "euler_variance_pct": _convert_to_json_serializable(self.euler_variance_pct),  # Euler Variance Contribution by Stock
            # Phase 2 cleanup: removed nested industry_variance (redundant with industry_variance_absolute, industry_variance_percentage, industry_group_betas)
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
                "target_allocation": (self.analysis_metadata or {}).get("target_allocation"),
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
            notional_leverage=portfolio_summary.get("notional_leverage"),
            fx_attribution=portfolio_summary.get("fx_attribution"),
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
    
    def get_agent_snapshot(self) -> Dict[str, Any]:
        """Compact decision-oriented snapshot for agent consumption."""
        def _safe_float(val, default: float = 0.0) -> float:
            if val is None:
                return default
            try:
                numeric = float(val)
                if numeric != numeric:  # NaN check
                    return default
                return numeric
            except (TypeError, ValueError):
                return default

        score = self.risk_score.get("score", 0)
        category = self.get_risk_category_enum()
        component_scores = self.get_component_scores()
        is_compliant = self.is_compliant()
        violations_summary = self._get_violations_summary()

        violation_count = violations_summary.get("total_violations", 0)
        if is_compliant:
            verdict = f"Portfolio risk is {category} (score {score}/100), fully compliant"
        else:
            suffix = "s" if violation_count != 1 else ""
            verdict = f"Portfolio risk is {category} (score {score}/100), {violation_count} violation{suffix}"

        recommendations = self.get_recommendations()
        if not isinstance(recommendations, list):
            recommendations = []

        risk_factors = self.get_risk_factors()
        if not isinstance(risk_factors, list):
            risk_factors = []

        priority_actions = self._get_priority_actions()
        if not isinstance(priority_actions, list):
            priority_actions = []

        clean_component_scores = component_scores if isinstance(component_scores, dict) else {}
        critical_violations = violations_summary.get("critical_violations", [])
        if not isinstance(critical_violations, list):
            critical_violations = []

        return {
            "overall_score": _safe_float(score),
            "risk_category": category,
            "is_compliant": is_compliant,
            "verdict": verdict,
            "component_scores": {k: _safe_float(v) for k, v in clean_component_scores.items()},
            "violation_count": violation_count,
            "critical_violations": critical_violations[:3],
            "recommendations": recommendations[:5],
            "risk_factors": risk_factors[:5],
            "priority_actions": priority_actions[:5],
        }


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

"""Stock Analysis result objects."""

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

    def get_agent_snapshot(self) -> Dict[str, Any]:
        """Compact stock metrics for agent consumption."""
        vol = self.volatility_metrics or {}
        reg = self.regression_metrics or self.risk_metrics or {}

        def _to_float_or_none(value: Any) -> Optional[float]:
            if value is None:
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        annual_vol = _to_float_or_none(vol.get("annual_vol"))
        monthly_vol = _to_float_or_none(vol.get("monthly_vol"))
        sharpe = _to_float_or_none(vol.get("sharpe_ratio"))
        max_drawdown = _to_float_or_none(vol.get("max_drawdown"))

        beta = _to_float_or_none(reg.get("beta"))
        alpha = _to_float_or_none(reg.get("alpha"))
        r_squared = _to_float_or_none(reg.get("r_squared"))
        idio_vol = _to_float_or_none(reg.get("idio_vol_m"))

        factor_betas = self.get_factor_exposures() or {}
        cleaned_factor_betas: Dict[str, float] = {}
        for name, value in factor_betas.items():
            numeric = _to_float_or_none(value)
            if numeric is not None:
                cleaned_factor_betas[name] = numeric

        if not cleaned_factor_betas and self.factor_exposures:
            for name, exposure in self.factor_exposures.items():
                if isinstance(exposure, dict):
                    numeric = _to_float_or_none(exposure.get("beta"))
                    if numeric is not None:
                        cleaned_factor_betas[name] = numeric

        risk_labels = {
            "very_high": "very high risk",
            "high": "high risk",
            "moderate": "moderate risk",
            "low": "low risk",
        }

        rate_beta = _to_float_or_none(getattr(self, "interest_rate_beta", None))
        rate_risk = abs(rate_beta) if rate_beta is not None else 0
        vol_for_threshold = annual_vol or 0
        beta_for_threshold = abs(beta) if beta is not None else 0

        if vol_for_threshold > 0.50 or beta_for_threshold > 2.0 or rate_risk > 8.0:
            risk_level = "very_high"
        elif vol_for_threshold > 0.30 or beta_for_threshold > 1.5 or rate_risk > 5.0:
            risk_level = "high"
        elif vol_for_threshold > 0.15 or beta_for_threshold > 1.0 or rate_risk > 2.0:
            risk_level = "moderate"
        else:
            risk_level = "low"

        snapshot: Dict[str, Any] = {
            "ticker": self.ticker,
            "verdict": risk_labels[risk_level],
            "risk_level": risk_level,
            "analysis_type": getattr(self, "analysis_type", "unknown"),
            "analysis_period": getattr(self, "analysis_period", {}),
            "volatility": {
                "annual_pct": round(annual_vol * 100, 1) if annual_vol is not None else None,
                "monthly_pct": round(monthly_vol * 100, 1) if monthly_vol is not None else None,
                "sharpe_ratio": round(sharpe, 2) if sharpe is not None else None,
                "max_drawdown_pct": round(max_drawdown * 100, 1) if max_drawdown is not None else None,
            },
            "regression": {
                "beta": round(beta, 3) if beta is not None else None,
                "alpha_monthly_pct": round(alpha * 100, 3) if alpha is not None else None,
                "r_squared": round(r_squared, 3) if r_squared is not None else None,
                "idiosyncratic_vol_monthly_pct": round(idio_vol * 100, 2) if idio_vol is not None else None,
            },
            "factor_exposures": {
                factor: round(value, 3) for factor, value in cleaned_factor_betas.items()
            },
        }

        if rate_beta is not None:
            effective_duration = _to_float_or_none(self.effective_duration)
            rate_r_squared = _to_float_or_none(self.rate_regression_r2)
            key_rate_breakdown = {}
            for key, value in (self.key_rate_breakdown or {}).items():
                numeric = _to_float_or_none(value)
                if numeric is not None:
                    key_rate_breakdown[key] = round(numeric, 3)

            snapshot["bond_analytics"] = {
                "interest_rate_beta": round(rate_beta, 3),
                "effective_duration": round(effective_duration, 2) if effective_duration is not None else None,
                "rate_r_squared": round(rate_r_squared, 3) if rate_r_squared is not None else None,
                "key_rate_breakdown": key_rate_breakdown,
            }

        return snapshot
    
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


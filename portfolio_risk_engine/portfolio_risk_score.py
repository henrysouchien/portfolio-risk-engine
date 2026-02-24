#!/usr/bin/env python3
"""
Portfolio Risk Score Module

A standalone module that calculates a "credit score" for portfolios (0-100)
based on multiple risk metrics including volatility, concentration, factor exposures,
and variance decomposition.

This module is independent and doesn't modify the existing codebase.
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, List, Tuple, Union
from datetime import datetime, UTC
import os
from portfolio_risk_engine.constants import DIVERSIFIED_SECURITY_TYPES
from portfolio_risk_engine.data_objects import PortfolioData, RiskLimitsData
from portfolio_risk_engine.config_adapters import resolve_portfolio_config, resolve_risk_config

# Import settings for risk analysis thresholds and scenarios
from portfolio_risk_engine.config import RISK_ANALYSIS_THRESHOLDS, WORST_CASE_SCENARIOS, MAX_SINGLE_FACTOR_LOSS, SECURITY_TYPE_CRASH_MAPPING

# Import existing modules without modifying them
try:
    from portfolio_risk_engine.portfolio_risk import build_portfolio_view
    from portfolio_risk_engine.risk_helpers import calc_max_factor_betas
    from portfolio_risk_engine.portfolio_config import standardize_portfolio_input, latest_price
    from portfolio_risk_engine.results import RiskScoreResult
    from services.security_type_service import SecurityTypeService
except ImportError:
    print("Warning: Could not import required modules. Make sure portfolio-risk-engine is installed.")
    build_portfolio_view = None
    calc_max_factor_betas = None
    standardize_portfolio_input = None
    latest_price = None
    RiskScoreResult = None
    SecurityTypeService = None


# =====================================================================
# WORST-CASE SCENARIO DEFINITIONS
# =====================================================================
# These scenarios define the stress tests used for risk calculations
# 
# DATA SOURCE HIERARCHY:
# 1. Historical Data: Preferred when available (via max_betas parameters)
# 2. Configured Scenarios: Fallback values from settings.WORST_CASE_SCENARIOS
# 
# USAGE BY FUNCTION:
# - calculate_factor_risk_loss: Historical → Fallback to configured
# - calculate_sector_risk_loss: Historical → Fallback to configured  
# - calculate_concentration_risk_loss: Uses security-type-aware scenarios (NEW!)
# - calculate_volatility_risk_loss: Always uses configured scenarios
# - calculate_suggested_risk_limits: Historical → Fallback to configured
#   + security-type-aware concentration/leverage suggestions when security_types are provided
#
# SECURITY-TYPE-AWARE RISK SCORING (NEW):
# calculate_concentration_risk_loss now uses different crash scenarios based on security type:
# - equity: 80% (individual stock failure - ENRON, LEHMAN)
# - etf: 35% (diversified ETF crash - market-like risk)  
# - fund: 40% (fund crash - moderate diversification) ← FIXES DSU ISSUE!
# - cash: 5% (cash equivalent risk - money market funds)
#
# CONFIGURATION:
# All scenario values are centralized in settings.py:
# - settings.WORST_CASE_SCENARIOS: Market crash, factor crashes, security-type-specific scenarios
# - settings.SECURITY_TYPE_CRASH_MAPPING: Maps security types to crash scenarios
# - settings.MAX_SINGLE_FACTOR_LOSS: Default loss limits for factor exposures
#
# Update these values in settings.py as new historical data becomes available

# =====================================================================
# RISK ANALYSIS THRESHOLDS
# =====================================================================
# These constants define the hardcoded limits and thresholds used throughout 
# the risk analysis system. All values are centralized in settings.RISK_ANALYSIS_THRESHOLDS
#
# THRESHOLD CATEGORIES:
#
# 1. LEVERAGE ANALYSIS:
#    - leverage_warning_threshold (1.1): Leverage ratio above which warnings are triggered
#
# 2. RISK SCORE CALCULATION:
#    - risk_score_safe_threshold (0.8): Below this excess ratio = 100 points (safe)
#    - risk_score_caution_threshold (1.0): At limit = 75 points (caution)
#    - risk_score_danger_threshold (1.5): 50% over limit = 50 points (danger)
#    - risk_score_critical_threshold (2.0): 100% over limit = 0 points (critical)
#
# 3. BETA EXPOSURE ANALYSIS:
#    - beta_warning_ratio (0.75): Flag beta exposures above 75% of limit
#    - beta_violation_ratio (1.0): Beta exposures above 100% of limit
#
# 4. DIVERSIFICATION ANALYSIS:
#    - herfindahl_warning_threshold (0.15): HHI above this indicates low diversification
#    - concentration_warning_ratio (0.8): Position size above 80% of limit triggers warning
#
# 5. VOLATILITY ANALYSIS:
#    - volatility_warning_ratio (0.8): Portfolio volatility above 80% of limit
#
# 6. VARIANCE CONTRIBUTION ANALYSIS:
#    - factor_variance_warning_ratio (0.8): Factor variance above 80% of limit
#    - market_variance_warning_ratio (0.8): Market variance above 80% of limit
#    - variance_contribution_threshold (0.05): 5% - minimum contribution to recommend reduction
#    - industry_concentration_warning_ratio (0.5): Industry concentration above 50% of limit
#
# 7. DISPLAY THRESHOLDS:
#    - leverage_display_threshold (1.01): Show leverage adjustments above this ratio
#
# USAGE PATTERN:
# These thresholds are imported and used throughout portfolio_risk_score.py functions:
# - analyze_portfolio_risk_limits(): Uses leverage, beta, diversification, volatility thresholds
# - score_excess_ratio(): Uses risk score calculation thresholds
# - Various display functions: Use display thresholds
#
# Update these values in settings.py to adjust risk sensitivity across the system

# =====================================================================
# RISK LIMITS USAGE DOCUMENTATION
# =====================================================================
# This section documents how user-provided risk limits from risk_limits.yaml
# are used throughout the risk analysis system.
#
# RISK LIMITS FILE STRUCTURE (risk_limits.yaml):
# portfolio_limits:
#   max_volatility: 0.4          # Maximum portfolio volatility (40%)
#   max_loss: -0.25              # Maximum acceptable portfolio loss (25%)
# concentration_limits:
#   max_single_stock_weight: 0.4  # Maximum position size (40%)
# variance_limits:
#   max_factor_contribution: 0.3   # Maximum factor variance contribution (30%)
#   max_market_contribution: 0.5   # Maximum market variance contribution (50%)
#   max_industry_contribution: 0.3 # Maximum industry variance contribution (30%)
# max_single_factor_loss: -0.1    # Maximum single factor loss limit (10%)
#
# FUNCTIONS THAT USE RISK LIMITS:
#
# 1. ANALYZE_PORTFOLIO_RISK_LIMITS (Lines 358-556):
#    ✅ Uses ALL user risk limits from YAML file
#    - portfolio_limits["max_volatility"] → Volatility limit checking
#    - concentration_limits["max_single_stock_weight"] → Position size checking
#    - variance_limits["max_factor_contribution"] → Factor variance checking
#    - variance_limits["max_market_contribution"] → Market variance checking  
#    - variance_limits["max_industry_contribution"] → Industry concentration checking
#    - max_betas (from historical analysis) → Beta exposure checking
#    - max_proxy_betas (from historical analysis) → Sector beta checking
#    - Leverage checking uses RISK_ANALYSIS_THRESHOLDS (not user-configurable)
#
# 2. CALCULATE_PORTFOLIO_RISK_SCORE (Lines 1000-1100):
#    ✅ Uses ALL user risk limits from YAML file  
#    - Same risk limits as analyze_portfolio_risk_limits
#    - Calculates 0-100 risk score based on limit violations
#    - Uses portfolio_limits["max_loss"] for risk score calculation
#
# 3. CALCULATE_SUGGESTED_RISK_LIMITS (Lines 563-798):
#    ✅ Uses user max_loss to suggest optimal limits
#    - portfolio_limits["max_loss"] → Works backward to suggest limits
#    - max_single_factor_loss → Factor loss tolerance for suggestions
#    - Does NOT directly use other limits (generates new suggestions)
#
# 4. CALCULATE_FACTOR_RISK_LOSS (Lines 137-217):
#    ✅ Uses user-configured factor loss limit
#    - max_single_factor_loss → Maximum acceptable factor loss
#    - Does NOT use other risk limits (only calculates potential loss)
#
# 5. CALCULATE_SECTOR_RISK_LOSS (Lines 285-356):
#    ✅ Uses user-configured factor loss limit  
#    - max_single_factor_loss → Maximum acceptable sector loss
#    - Does NOT use other risk limits (only calculates potential loss)
#
# 6. CALCULATE_CONCENTRATION_RISK_LOSS (Lines 218-242):
#    ❌ Does NOT use user risk limits
#    - Uses hardcoded WORST_CASE_SCENARIOS["single_stock_crash"] (80%)
#    - Should potentially use concentration_limits for consistency
#
# 7. CALCULATE_VOLATILITY_RISK_LOSS (Lines 243-283):
#    ❌ Does NOT use user risk limits
#    - Uses hardcoded WORST_CASE_SCENARIOS["max_reasonable_volatility"] (40%)  
#    - Should potentially use portfolio_limits["max_volatility"] for consistency
#
# SUMMARY:
# ✅ MAIN ANALYSIS FUNCTIONS: Use ALL user risk limits correctly
# ✅ RISK SCORE CALCULATION: Uses ALL user risk limits correctly  
# ✅ SUGGESTED LIMITS: Uses user max_loss correctly
# ✅ FACTOR/SECTOR LOSS: Uses user factor loss limits correctly
# ❌ CONCENTRATION/VOLATILITY LOSS: Use hardcoded scenarios (design choice)
#
# The core risk analysis (functions 1-2) correctly uses ALL user-provided risk limits.
# Loss calculation functions (6-7) use hardcoded scenarios by design for worst-case analysis.
# This ensures user limits control the risk assessment while maintaining consistent stress testing.


def score_excess_ratio(excess_ratio: float) -> float:
    """
    Score based on how much potential loss exceeds the max loss limit.
    
    Parameters
    ----------
    excess_ratio : float
        potential_loss / max_loss_limit
        
    Returns
    -------
    float
        Score from 0-100 using a piecewise linear curve:
        - ≤ safe threshold: 100
        - safe → caution: linearly interpolates 100 → 75
        - caution → danger: linearly interpolates 75 → 50
        - danger → critical: linearly interpolates 50 → 0
        - ≥ critical threshold: 0
    """
    safe_threshold = RISK_ANALYSIS_THRESHOLDS["risk_score_safe_threshold"]
    caution_threshold = RISK_ANALYSIS_THRESHOLDS["risk_score_caution_threshold"] 
    danger_threshold = RISK_ANALYSIS_THRESHOLDS["risk_score_danger_threshold"]
    critical_threshold = RISK_ANALYSIS_THRESHOLDS["risk_score_critical_threshold"]

    def _interpolate(value: float, start_x: float, end_x: float, start_y: float, end_y: float) -> float:
        if end_x <= start_x:
            return end_y
        progress = (value - start_x) / (end_x - start_x)
        return start_y + progress * (end_y - start_y)

    if excess_ratio <= safe_threshold:
        return 100.0
    if excess_ratio <= caution_threshold:
        return _interpolate(excess_ratio, safe_threshold, caution_threshold, 100.0, 75.0)
    if excess_ratio <= danger_threshold:
        return _interpolate(excess_ratio, caution_threshold, danger_threshold, 75.0, 50.0)
    if excess_ratio <= critical_threshold:
        return _interpolate(excess_ratio, danger_threshold, critical_threshold, 50.0, 0.0)
    return 0.0


def _get_single_issuer_weights(
    weights: pd.Series,
    security_types: Optional[Dict[str, str]],
) -> pd.Series:
    """
    Filter weights to single-issuer positions based on security type.

    Conservative fallback behavior:
    - If security types are unavailable, return raw weights.
    - If all positions are exempt diversified vehicles, return raw weights.
    """
    if not isinstance(weights, pd.Series) or weights.empty:
        return weights
    if not security_types:
        return weights

    single_issuer_tickers = [
        ticker for ticker in weights.index
        if security_types.get(ticker) not in DIVERSIFIED_SECURITY_TYPES
    ]
    if not single_issuer_tickers:
        return weights
    return weights.loc[single_issuer_tickers]


def calculate_factor_risk_loss(summary: Dict[str, Any], leverage_ratio: float, max_betas: Dict[str, float] = None, max_single_factor_loss: float = None) -> float:
    """
    Calculate potential loss from factor exposure.
    
    DATA SOURCES (in priority order):
    1. Historical worst losses: Derived from max_betas when provided
       Formula: worst_loss = max_single_factor_loss / max_beta
    2. Configured scenarios: WORST_CASE_SCENARIOS as fallback
    
    Parameters
    ----------
    summary : Dict[str, Any]
        Portfolio analysis with factor betas
    leverage_ratio : float
        Portfolio leverage multiplier (use 1.0 when weights already include leverage)
    max_betas : Dict[str, float], optional
        Historical max betas by factor. When provided, derives historical worst losses.
        When None, uses configured WORST_CASE_SCENARIOS.
    max_single_factor_loss : float, default -0.10
        Maximum acceptable loss from any single factor (used with historical data)
        
    Returns
    -------
    float
        Maximum potential loss from factor exposures
        
    Notes
    -----
    - Only counts negative factor impacts as risk (positive impacts are protective)
    - Uses actual portfolio factor betas from summary["portfolio_factor_betas"]
    - For each factor: loss = |portfolio_beta × worst_case_move × leverage_ratio|
    """
    # Use default from settings if not provided
    if max_single_factor_loss is None:
        max_single_factor_loss = MAX_SINGLE_FACTOR_LOSS["default"]
        
    portfolio_betas = summary["portfolio_factor_betas"]
    
    # For PORTFOLIO RISK SCORE: Use historical data for ALL factors when available
    worst_case_scenarios = {}
    
    if max_betas:
        # Use historical data for ALL factors (including market)
        loss_limit = max_single_factor_loss
        
        for factor in ["market", "momentum", "value"]:
            if factor not in max_betas:
                continue  # Skip factors without historical data
            max_beta = max_betas[factor]
            if max_beta != 0 and max_beta != float('inf'):
                # Use historical data: max_beta = loss_limit / worst_loss, so worst_loss = loss_limit / max_beta
                worst_case_scenarios[factor] = loss_limit / max_beta
            else:
                # Fallback to configured scenarios if no historical data
                worst_case_scenarios[factor] = -{
                    "market": WORST_CASE_SCENARIOS["market_crash"],
                    "momentum": WORST_CASE_SCENARIOS["momentum_crash"],
                    "value": WORST_CASE_SCENARIOS["value_crash"]
                }[factor]  # Remove fallback - factor should be in WORST_CASE_SCENARIOS
    else:
        # Use configured scenarios when no historical data available
        worst_case_scenarios = {
            "market": -WORST_CASE_SCENARIOS["market_crash"],
            "momentum": -WORST_CASE_SCENARIOS["momentum_crash"],
            "value": -WORST_CASE_SCENARIOS["value_crash"]
        }
    
    max_factor_loss = 0.0
    
    for factor, worst_case_move in worst_case_scenarios.items():
        factor_beta = portfolio_betas.get(factor, 0.0)
        # Calculate actual impact: beta * factor_move
        factor_impact = factor_beta * worst_case_move * leverage_ratio
        
        # Only count negative impacts (losses) as risk
        # Positive impacts (gains) are protective, not risky
        if factor_impact < 0:  # Loss
            factor_loss = abs(factor_impact)
            max_factor_loss = max(max_factor_loss, factor_loss)
    
    return max_factor_loss


def calculate_concentration_risk_loss(
    summary: Dict[str, Any],
    leverage_ratio: float,
    portfolio_data=None,
    security_types: Optional[Dict[str, str]] = None,
) -> float:
    """
    Calculate potential loss from single stock concentration with security-type-aware crash scenarios.
    
    ENHANCEMENT: This function now uses SecurityTypeService to apply different crash scenarios
    based on the actual security type rather than treating all securities as individual stocks.
    This fixes the DSU issue where mutual funds were getting 80% crash scenarios instead of 40%.
    
    DATA SOURCE: Uses security-type-specific WORST_CASE_SCENARIOS via SECURITY_TYPE_CRASH_MAPPING
    
    Parameters
    ----------
    summary : Dict[str, Any]
        Portfolio analysis with position weights from build_portfolio_view()
    leverage_ratio : float
        Portfolio leverage multiplier (use 1.0 when weights already include leverage)
    portfolio_data : PortfolioData, optional
        Portfolio data containing provider classifications for cash preservation.
        Required for SecurityTypeService to preserve provider cash classifications.
        
    Returns
    -------
    float
        Potential loss from largest single position using appropriate crash scenario.
        Values range from 5% (cash) to 80% (individual equity) of position size.
        
    Notes
    -----
    SECURITY-TYPE-AWARE CRASH SCENARIOS:
    - equity: 80% crash (individual stock failure - Enron, Lehman Brothers)
    - etf: 35% crash (diversified ETF - tracks market-wide crashes)
    - fund: 40% crash (diversified fund - moderate crash protection)
    - cash: 5% crash (money market risk - very low)
    
    CASH-FIRST STRATEGY:
    - Cash positions: Trust provider classification (Plaid/SnapTrade expertise)
    - Securities: Use FMP via SecurityTypeService for authoritative classification
    
    FALLBACK BEHAVIOR:
    - If SecurityTypeService unavailable: Falls back to generic 80% (equity) scenario
    - If security type unknown: Defaults to equity classification (conservative)
    
    PERFORMANCE:
    - Leverages dual-layer caching (LFU memory + database) for fast lookups
    - Typical response time: <1ms for cached securities, <200ms for new lookups
    
    Formula: max_position_weight × security_type_crash_scenario × leverage_ratio
    
    Examples
    --------
    >>> # DSU mutual fund with 30% portfolio allocation
    >>> # Before: 0.30 × 0.80 × 1.0 = 0.24 (24% loss)
    >>> # After:  0.30 × 0.40 × 1.0 = 0.12 (12% loss) ← 50% reduction!
    """
    weights = summary["allocations"]["Portfolio Weight"]
    check_weights = _get_single_issuer_weights(weights, security_types)
    if check_weights.empty:
        return 0.0

    max_position = check_weights.abs().max()
    largest_ticker = check_weights.abs().idxmax()
    
    # Get security types with provider cash preservation
    if security_types and largest_ticker in security_types:
        security_type = security_types.get(largest_ticker, "equity")
    elif SecurityTypeService and largest_ticker:
        try:
            tickers = [largest_ticker]
            type_lookup = SecurityTypeService.get_security_types(tickers, portfolio_data)
            security_type = type_lookup.get(largest_ticker, "equity")
        except Exception as e:
            print(f"Warning: SecurityTypeService failed, using default: {e}")
            security_type = "equity"
    else:
        security_type = "equity"  # Conservative fallback
    
    # Apply security-type-specific crash scenario
    # Use centralized mapping system with built-in 3-tier fallback
    if security_type not in SECURITY_TYPE_CRASH_MAPPING:
        portfolio_logger.warning(f"Unmapped security type '{security_type}' for {largest_ticker}, defaulting to equity crash scenario")
        security_type = "equity"
    crash_scenario_key = SECURITY_TYPE_CRASH_MAPPING[security_type]
    crash_scenario = WORST_CASE_SCENARIOS[crash_scenario_key]
    
    concentration_loss = max_position * crash_scenario * leverage_ratio
    return concentration_loss


def get_crash_scenario_for_security_type(security_type: str) -> float:
    """
    Map security type to appropriate crash scenario percentage using centralized mapping system.
    
    This function now uses the centralized security type mapping system with 3-tier fallback:
    Database → YAML → Hardcoded defaults. This ensures consistency across the entire
    risk module and allows for dynamic updates via the admin interface.
    
    Parameters
    ----------
    security_type : str
        Security type classification ('equity', 'etf', 'fund', 'cash')
        
    Returns
    -------
    float
        Crash scenario percentage (0.0 to 1.0)
        
    Notes
    -----
    CENTRALIZED CRASH SCENARIO MAPPINGS:
    Uses the centralized security type mapping system with 3-tier fallback:
    Database → YAML → Hardcoded defaults. Supported security types:
    - equity: 0.80 (80%) - Individual stock failure risk (Enron, WorldCom)
    - etf: 0.35 (35%) - Diversified ETF crash (market correlation risk)
    - fund: 0.40 (40%) - Fund crash (moderate diversification)
    - cash: 0.05 (5%) - Money market/cash equivalent risk (very low)
    
    The centralized system supports both "fund" and "mutual_fund" for backward compatibility.
    If an unsupported security type is passed, the centralized system will handle fallback logic.
    
    Examples
    --------
    >>> get_crash_scenario_for_security_type('fund')
    0.4
    >>> get_crash_scenario_for_security_type('etf')
    0.35
    >>> get_crash_scenario_for_security_type('unknown_type')  # doctest: +SKIP
    # Will raise KeyError - centralized system handles unsupported types
    """
    from portfolio_risk_engine.config import SECURITY_TYPE_CRASH_MAPPING, WORST_CASE_SCENARIOS
    
    # Use centralized mapping system with built-in 3-tier fallback
    # The centralized system already handles all fallback logic
    if security_type not in SECURITY_TYPE_CRASH_MAPPING:
        portfolio_logger.warning(f"Unmapped security type '{security_type}', defaulting to equity crash scenario")
        security_type = "equity"
    crash_scenario_key = SECURITY_TYPE_CRASH_MAPPING[security_type]
    return WORST_CASE_SCENARIOS[crash_scenario_key]


def calculate_volatility_risk_loss(summary: Dict[str, Any], leverage_ratio: float) -> float:
    """
    Calculate potential loss from portfolio volatility.
    
    DATA SOURCE: Always uses configured WORST_CASE_SCENARIOS
    
    Parameters
    ----------
    summary : Dict[str, Any]
        Portfolio analysis with volatility metrics
    leverage_ratio : float
        Portfolio leverage multiplier (use 1.0 when weights already include leverage)
        
    Returns
    -------
    float
        Potential loss from portfolio volatility
        
    Notes
    -----
    - Uses actual annual portfolio volatility from summary["volatility_annual"]
    - Caps at configured max_reasonable_volatility (40%)
    - Formula: min(actual_vol, max_reasonable_vol) × leverage_ratio
    """
    actual_vol = summary["volatility_annual"]
    max_reasonable_vol = WORST_CASE_SCENARIOS["max_reasonable_volatility"]
    
    # Use actual volatility, capped at configured maximum
    volatility_loss = min(actual_vol, max_reasonable_vol) * leverage_ratio
    return volatility_loss


def calculate_sector_risk_loss(summary: Dict[str, Any], leverage_ratio: float, max_betas_by_proxy: Dict[str, float] = None, max_single_factor_loss: float = None) -> float:
    """
    Calculate potential loss from sector exposure.
    
    DATA SOURCES (in priority order):
    1. Historical worst losses: Derived from max_betas_by_proxy when provided
       Formula: worst_loss = max_single_factor_loss / max_beta
    2. Configured scenarios: WORST_CASE_SCENARIOS["sector_crash"] as fallback
    
    Parameters
    ----------
    summary : Dict[str, Any]
        Portfolio analysis with industry betas
    leverage_ratio : float
        Portfolio leverage multiplier (use 1.0 when weights already include leverage)
    max_betas_by_proxy : Dict[str, float], optional
        Historical max betas by industry proxy. When provided, derives historical worst losses.
        When None, uses configured sector_crash scenario.
    max_single_factor_loss : float, default -0.08
        Maximum acceptable loss from any single factor (used with historical data)
        
    Returns
    -------
    float
        Maximum potential loss from sector exposures
        
    Notes
    -----
    - Uses portfolio betas to each industry proxy from summary["industry_variance"]["per_industry_group_beta"]
    - Only counts negative sector impacts as risk
    - For each sector: loss = |portfolio_beta × worst_sector_loss × leverage_ratio|
    """
    # Use default from settings if not provided
    if max_single_factor_loss is None:
        max_single_factor_loss = MAX_SINGLE_FACTOR_LOSS["sector"]
        
    # Get portfolio's beta exposure to each industry proxy
    industry_betas = summary["industry_variance"].get("per_industry_group_beta", {})
    
    if not industry_betas:
        return 0.0
    
    max_sector_loss = 0.0
    
    # Calculate loss for each sector using actual beta exposure and historical worst losses
    for sector_proxy, portfolio_beta in industry_betas.items():
        if portfolio_beta == 0:
            continue
            
        # Get historical worst loss for this sector
        if max_betas_by_proxy and sector_proxy in max_betas_by_proxy:
            # Use historical data: max_beta = loss_limit / worst_loss, so worst_loss = loss_limit / max_beta
            max_beta = max_betas_by_proxy[sector_proxy]
            if max_beta != 0 and max_beta != float('inf'):
                worst_historical_loss = abs(max_single_factor_loss / max_beta)
            else:
                # Fallback to generic sector crash if no historical data
                worst_historical_loss = WORST_CASE_SCENARIOS["sector_crash"]
        else:
            # Fallback to generic sector crash if no historical data
            worst_historical_loss = WORST_CASE_SCENARIOS["sector_crash"]
        
        # Calculate sector impact: beta × worst_loss × leverage
        sector_impact = portfolio_beta * -worst_historical_loss * leverage_ratio
        
        # Only count negative impacts (losses) as risk
        if sector_impact < 0:  # Loss
            sector_loss = abs(sector_impact)
            max_sector_loss = max(max_sector_loss, sector_loss)
    
    return max_sector_loss


def analyze_portfolio_risk_limits(
    summary: Dict[str, Any],
    portfolio_limits: Dict[str, float],
    concentration_limits: Dict[str, float],
    variance_limits: Dict[str, float],
    max_betas: Dict[str, float],
    max_proxy_betas: Optional[Dict[str, float]] = None,
    leverage_ratio: float = 1.0,
    security_types: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Detailed risk limits analysis with specific violations and recommendations.
    
    This function performs comprehensive limit checking similar to the old system,
    providing specific beta violations, concentration issues, and actionable recommendations.
    
    Parameters
    ----------
    summary : Dict[str, Any]
        Portfolio analysis summary
    portfolio_limits : Dict[str, float]
        Portfolio-level limits (volatility, max_loss)
    concentration_limits : Dict[str, float]
        Concentration limits (max_single_stock_weight)
    variance_limits : Dict[str, float]
        Variance decomposition limits
    max_betas : Dict[str, float]
        Maximum allowed factor betas
    max_proxy_betas : Optional[Dict[str, float]]
        Maximum allowed proxy betas
    leverage_ratio : float
        Portfolio leverage ratio
        
    Returns
    -------
    Dict[str, Any]
        Detailed risk factors and recommendations
    """
    risk_factors = []
    recommendations = []
    
    # ═══════════════════════════════════════════════════════════════════════════
    # DETAILED RISK LIMITS ANALYSIS
    # ═══════════════════════════════════════════════════════════════════════════
    
    # ─── 1. Factor Beta Limit Analysis ────────────────────────────────────────
    portfolio_betas = summary["portfolio_factor_betas"]
    
    # Check each factor against its limit
    for factor in ["market", "momentum", "value"]:
        if factor in max_betas and factor in portfolio_betas:
            actual_beta = portfolio_betas[factor]
            max_beta = max_betas[factor]
            beta_ratio = abs(actual_beta) / max_beta if max_beta > 0 else 0
            
            beta_violation_ratio = RISK_ANALYSIS_THRESHOLDS["beta_violation_ratio"]
            beta_warning_ratio = RISK_ANALYSIS_THRESHOLDS["beta_warning_ratio"]
            
            if beta_ratio > beta_violation_ratio:  # Exceeds limit
                risk_factors.append(f"High {factor} exposure: β={actual_beta:.2f} vs {max_beta:.2f} limit")
                if factor == "market":
                    recommendations.append("Reduce market exposure (sell high-beta stocks or add market hedges)")
                else:
                    recommendations.append(f"Reduce {factor} factor exposure")
            elif beta_ratio > beta_warning_ratio:  # Approaching limit  
                risk_factors.append(f"High {factor} exposure: β={actual_beta:.2f} vs {max_beta:.2f} limit")
                if factor == "market":
                    recommendations.append("Reduce market exposure (sell high-beta stocks or add market hedges)")
                else:
                    recommendations.append(f"Reduce {factor} factor exposure")
    
    # Check industry proxy exposures
    if max_proxy_betas:
        industry_betas = summary["industry_variance"].get("per_industry_group_beta", {})
        for proxy, actual_beta in industry_betas.items():
            if proxy in max_proxy_betas and actual_beta != 0:
                max_beta = max_proxy_betas[proxy]
                beta_ratio = abs(actual_beta) / max_beta if max_beta > 0 else 0
                
                beta_warning_ratio = RISK_ANALYSIS_THRESHOLDS["beta_warning_ratio"]
                if beta_ratio > beta_warning_ratio:  # Flag if >warning ratio of limit
                    risk_factors.append(f"High {proxy} exposure: β={actual_beta:.2f} vs {max_beta:.2f} limit")
                    recommendations.append(f"Reduce exposure to {proxy} sector")
    
    # ─── 2. Concentration Limit Analysis ──────────────────────────────────────
    weights = summary["allocations"]["Portfolio Weight"]
    check_weights = _get_single_issuer_weights(weights, security_types)
    max_weight = check_weights.abs().max() if not check_weights.empty else 0.0
    herfindahl = summary["herfindahl"]
    weight_limit = concentration_limits["max_single_stock_weight"]
    
    # Check position concentration
    concentration_warning_ratio = RISK_ANALYSIS_THRESHOLDS["concentration_warning_ratio"]
    if max_weight > weight_limit:
        risk_factors.append(f"High concentration: {max_weight:.1%} vs {weight_limit:.1%} limit")
        recommendations.append("Reduce position size in largest holdings")
    elif max_weight > weight_limit * concentration_warning_ratio:  # Approaching limit
        risk_factors.append(f"High concentration: {max_weight:.1%} in single position")
        recommendations.append("Reduce position size in largest holdings")
    
    # Check diversification
    hhi_threshold = RISK_ANALYSIS_THRESHOLDS["herfindahl_warning_threshold"]
    if herfindahl > hhi_threshold:
        risk_factors.append(f"Low diversification (HHI: {herfindahl:.3f})")
        recommendations.append("Add more positions to improve diversification")
    
    # ─── 3. Volatility Limit Analysis ─────────────────────────────────────────
    actual_vol = summary["volatility_annual"]
    vol_limit = portfolio_limits["max_volatility"]
    
    volatility_warning_ratio = RISK_ANALYSIS_THRESHOLDS["volatility_warning_ratio"]
    if actual_vol > vol_limit:
        risk_factors.append(f"High volatility: {actual_vol:.1%} vs {vol_limit:.1%} limit")
        recommendations.append("Reduce portfolio volatility through diversification or defensive positions")
    elif actual_vol > vol_limit * volatility_warning_ratio:  # Approaching limit
        risk_factors.append(f"High portfolio volatility ({actual_vol:.1%})")
        recommendations.append("Reduce volatility through diversification or defensive positions")
    
    # ─── 4. Variance Contribution Analysis ────────────────────────────────────
    var_decomp = summary["variance_decomposition"]
    factor_pct = var_decomp["factor_pct"]
    market_pct = var_decomp["factor_breakdown_pct"].get("market", 0.0)
    
    # Check factor variance contribution
    factor_limit = variance_limits["max_factor_contribution"]
    factor_variance_warning_ratio = RISK_ANALYSIS_THRESHOLDS["factor_variance_warning_ratio"]
    
    if factor_pct > factor_limit:
        risk_factors.append(f"High systematic risk: {factor_pct:.1%} vs {factor_limit:.1%} limit")
        
        # Identify which specific factors are contributing most to variance
        factor_breakdown = var_decomp["factor_breakdown_pct"]
        # Sort factors by contribution (descending)
        sorted_factors = sorted(factor_breakdown.items(), key=lambda x: x[1], reverse=True)
        
        # Generate specific recommendations for the top contributors
        for factor, contribution in sorted_factors:
            variance_contribution_threshold = RISK_ANALYSIS_THRESHOLDS["variance_contribution_threshold"] * 100  # Convert to percentage
            if contribution > variance_contribution_threshold:  # Only recommend for factors contributing >threshold%
                recommendations.append(f"Reduce {factor} factor exposure (contributing {contribution:.1%} to variance)")
                
    elif factor_pct > factor_limit * factor_variance_warning_ratio:  # Approaching limit
        risk_factors.append(f"High systematic risk: {factor_pct:.1%} variance from factors")
        
        # Identify which specific factors are contributing most to variance
        factor_breakdown = var_decomp["factor_breakdown_pct"]
        # Sort factors by contribution (descending)
        sorted_factors = sorted(factor_breakdown.items(), key=lambda x: x[1], reverse=True)
        
        # Generate specific recommendations for the top contributors
        for factor, contribution in sorted_factors:
            variance_contribution_threshold = RISK_ANALYSIS_THRESHOLDS["variance_contribution_threshold"] * 100  # Convert to percentage
            if contribution > variance_contribution_threshold:  # Only recommend for factors contributing >threshold%
                recommendations.append(f"Reduce {factor} factor exposure (contributing {contribution:.1%} to variance)")
    
    # Check market variance contribution
    market_limit = variance_limits["max_market_contribution"]
    market_variance_warning_ratio = RISK_ANALYSIS_THRESHOLDS["market_variance_warning_ratio"]
    if market_pct > market_limit:
        risk_factors.append(f"High market variance contribution: {market_pct:.1%} vs {market_limit:.1%} limit")
        recommendations.append("Reduce market factor exposure")
    elif market_pct > market_limit * market_variance_warning_ratio:  # Approaching limit
        risk_factors.append(f"High market variance contribution: {market_pct:.1%}")
        recommendations.append("Reduce market factor exposure")
    
    # ─── 5. Industry Variance Contribution Analysis ───────────────────────────
    industry_pct_dict = summary["industry_variance"].get("percent_of_portfolio", {})
    max_industry_pct = max(industry_pct_dict.values()) if industry_pct_dict else 0.0
    industry_limit = variance_limits["max_industry_contribution"]
    
    if max_industry_pct > industry_limit:
        risk_factors.append(f"High industry concentration: {max_industry_pct:.1%} vs {industry_limit:.1%} limit")
        
        # Identify which specific industry is causing the concentration
        # Sort industries by contribution (descending)
        sorted_industries = sorted(industry_pct_dict.items(), key=lambda x: x[1], reverse=True)
        
        # Generate specific recommendation for the top industry contributor
        if sorted_industries:
            top_industry, top_contribution = sorted_industries[0]
            recommendations.append(f"Reduce exposure to {top_industry} industry (contributing {top_contribution:.1%} to variance)")
            
            # Also suggest general diversification if there are multiple concentrated industries
            industry_concentration_warning_ratio = RISK_ANALYSIS_THRESHOLDS["industry_concentration_warning_ratio"]
            if len([ind for ind, pct in sorted_industries if pct > industry_limit * industry_concentration_warning_ratio]) > 1:
                recommendations.append("Add diversification across multiple industries")
        else:
            recommendations.append("Reduce industry concentration through diversification")
    
    # ─── 6. Leverage Analysis ─────────────────────────────────────────────────
    leverage_threshold = RISK_ANALYSIS_THRESHOLDS["leverage_warning_threshold"]
    if leverage_ratio > leverage_threshold:
        risk_factors.append(f"Leverage ({leverage_ratio:.2f}x) amplifies all potential losses")
        recommendations.append("Consider reducing leverage to limit downside risk")
    
    return {
        "risk_factors": risk_factors,
        "recommendations": recommendations,
        "limit_violations": {
            "factor_betas": len([f for f in risk_factors if "exposure:" in f and "β=" in f]),
            "concentration": len([f for f in risk_factors if "concentration" in f.lower()]),
            "volatility": len([f for f in risk_factors if "volatility" in f.lower()]),
            "variance_contributions": len([f for f in risk_factors if "variance" in f.lower()]),
            "leverage": len([f for f in risk_factors if "leverage" in f.lower()])
        }
    }


def calculate_suggested_risk_limits(
    summary: Dict[str, Any],
    max_loss: float,
    current_leverage: float,
    max_single_factor_loss: float = None,
    stock_factor_proxies: Dict = None,
    start_date: str = None,
    end_date: str = None,
    *,
    security_types: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Work backwards from max loss tolerance to suggest risk limits that would
    keep the current portfolio structure within acceptable risk levels.
    
    DATA SOURCES (in priority order):
    1. Historical worst losses: Calculated from actual factor proxy data when available
       Requires stock_factor_proxies, start_date, and end_date parameters
    2. Configured scenarios: WORST_CASE_SCENARIOS as fallback when historical data unavailable
    
    Parameters
    ----------
    summary : Dict[str, Any]
        Portfolio analysis summary with betas, weights, volatility, etc.
    max_loss : float
        Maximum acceptable portfolio loss (e.g., 0.25 for 25%)
    current_leverage : float
        Current portfolio leverage ratio (adjusted for raw vs normalized weights)
    max_single_factor_loss : float, default -0.10
        Maximum acceptable loss from any single factor (used with historical data)
    stock_factor_proxies : Dict, optional
        Stock factor proxy mappings for historical analysis
        When None, uses configured scenarios for all calculations
    start_date : str, optional
        Start date for historical analysis (e.g., "2020-01-01")
        Required for historical data calculation
    end_date : str, optional
        End date for historical analysis (e.g., "2024-12-31")
        Required for historical data calculation
        
    Returns
    -------
    Dict[str, Any]
        Suggested risk limits organized by category:
        - factor_limits: Market, momentum, value beta limits
        - concentration_limit: Maximum single position size
        - volatility_limit: Maximum portfolio volatility
        - sector_limit: Maximum sector exposure
        - leverage_limit: Maximum portfolio leverage
        
    Notes
    -----
    Factor Limits:
    - Market: Uses portfolio max_loss with historical/configured market crash
    - Momentum/Value: Uses max_single_factor_loss with historical/configured crashes
    
    Other Limits:
    - Concentration: Uses largest single-issuer position when security types are provided;
      otherwise falls back to raw weights + single_stock_crash (80%)
    - Volatility: Simple volatility ≤ max_loss / leverage proxy
    - Sector: Always uses configured sector_crash (50%)
    - Leverage: Calculated from worst-case scenario across all risk types
      (including the same concentration scenario logic above)
    
    Historical Data Fallback:
    If historical calculation fails, automatically falls back to configured scenarios
    with warning message to user.
    """
    # Use default from settings if not provided
    if max_single_factor_loss is None:
        max_single_factor_loss = MAX_SINGLE_FACTOR_LOSS["default"]

    if max_loss <= 0:
        portfolio_logger.warning(f"Received non-positive max_loss ({max_loss}); clamping to 0.01 for suggestion math")
        max_loss = 0.01
    if current_leverage <= 0:
        portfolio_logger.warning(
            f"Received non-positive current_leverage ({current_leverage}); clamping to 1.0 for suggestion math"
        )
        current_leverage = 1.0
        
    # =====================================================================
    # SCENARIO CONFIGURATION - Using module-level constants
    # =====================================================================
    # All scenarios are now defined at the module level in WORST_CASE_SCENARIOS
    
    # =====================================================================
    # PORTFOLIO DATA EXTRACTION
    # =====================================================================
    portfolio_betas = summary["portfolio_factor_betas"]
    weights = summary["allocations"]["Portfolio Weight"]
    actual_vol = summary["volatility_annual"]
    industry_pct = summary["industry_variance"].get("percent_of_portfolio", {})
    
    suggestions = {}
    
    # =====================================================================
    # 1. FACTOR LIMITS - Work backwards from HISTORICAL factor scenarios
    # =====================================================================
    factor_suggestions = {}
    
    # Get historical worst losses for ALL factors (market, momentum, value)
    historical_worst_losses = {}
    if stock_factor_proxies and start_date and end_date:
        try:
            # Get raw historical worst losses
            from portfolio_risk_engine.risk_helpers import get_worst_monthly_factor_losses, aggregate_worst_losses_by_factor_type
            worst_losses = get_worst_monthly_factor_losses(stock_factor_proxies, start_date, end_date)
            worst_by_factor = aggregate_worst_losses_by_factor_type(stock_factor_proxies, worst_losses)
            
            # Extract historical worst losses for each factor
            for factor, (proxy, worst_loss) in worst_by_factor.items():
                historical_worst_losses[factor] = abs(worst_loss)
        except Exception as e:
            print(f"Warning: Could not get historical factor data, using configured scenarios: {e}")
            historical_worst_losses = {}
    
    # Fallback to configured scenarios if no historical data available
    if not historical_worst_losses:
        historical_worst_losses = {
            "market": WORST_CASE_SCENARIOS["market_crash"],
            "momentum": WORST_CASE_SCENARIOS["momentum_crash"],
            "value": WORST_CASE_SCENARIOS["value_crash"]
        }
    
    # Market factor limit - Use PORTFOLIO max loss with HISTORICAL worst loss
    market_beta = portfolio_betas.get("market", 0.0)
    if market_beta != 0:
        market_crash_scenario = historical_worst_losses.get("market", WORST_CASE_SCENARIOS["market_crash"])
        # max_loss = market_beta × market_crash × leverage
        # So: market_beta ≤ max_loss / (market_crash × leverage)
        suggested_market_beta = max_loss / (market_crash_scenario * current_leverage)
        factor_suggestions["market_beta"] = {
            "current": market_beta,
            "suggested_max": suggested_market_beta,
            "needs_reduction": abs(market_beta) > suggested_market_beta
        }
    
    # Momentum factor limit - Use FACTOR max loss with HISTORICAL worst loss
    momentum_beta = portfolio_betas.get("momentum", 0.0)
    if momentum_beta != 0:
        momentum_worst_loss = historical_worst_losses.get("momentum", WORST_CASE_SCENARIOS["momentum_crash"])
        suggested_momentum_beta = abs(max_single_factor_loss) / (momentum_worst_loss * current_leverage)
        factor_suggestions["momentum_beta"] = {
            "current": momentum_beta,
            "suggested_max": suggested_momentum_beta,
            "needs_reduction": abs(momentum_beta) > suggested_momentum_beta
        }
    
    # Value factor limit - Use FACTOR max loss with HISTORICAL worst loss
    value_beta = portfolio_betas.get("value", 0.0)
    if value_beta != 0:
        value_worst_loss = historical_worst_losses.get("value", WORST_CASE_SCENARIOS["value_crash"])
        suggested_value_beta = abs(max_single_factor_loss) / (value_worst_loss * current_leverage)
        factor_suggestions["value_beta"] = {
            "current": value_beta,
            "suggested_max": suggested_value_beta,
            "needs_reduction": abs(value_beta) > suggested_value_beta
        }
    
    suggestions["factor_limits"] = factor_suggestions
    
    # =====================================================================
    # 2. CONCENTRATION LIMIT - Work backwards from single stock scenario
    # =====================================================================
    concentration_weights = _get_single_issuer_weights(weights, security_types)
    max_position = concentration_weights.abs().max() if not concentration_weights.empty else 0.0
    largest_ticker = concentration_weights.abs().idxmax() if not concentration_weights.empty else None
    if security_types is None:
        concentration_crash = WORST_CASE_SCENARIOS["single_stock_crash"]
    else:
        largest_security_type = security_types.get(largest_ticker, "equity") if largest_ticker else "equity"
        concentration_crash = get_crash_scenario_for_security_type(largest_security_type)

    # max_loss = max_position × concentration_crash × leverage
    # So: max_position ≤ max_loss / (concentration_crash × leverage)
    suggested_max_position = max_loss / (concentration_crash * current_leverage)
    
    suggestions["concentration_limit"] = {
        "current_max_position": max_position,
        "suggested_max_position": suggested_max_position,
        "needs_reduction": max_position > suggested_max_position
    }
    
    # =====================================================================
    # 3. VOLATILITY LIMIT - Work backwards from volatility scenario
    # =====================================================================
    # max_loss = volatility × leverage (simple proxy)
    # So: volatility ≤ max_loss / leverage
    suggested_max_volatility = max_loss / current_leverage
    
    suggestions["volatility_limit"] = {
        "current_volatility": actual_vol,
        "suggested_max_volatility": suggested_max_volatility,
        "needs_reduction": actual_vol > suggested_max_volatility
    }
    
    # =====================================================================
    # 4. SECTOR LIMIT - Work backwards from historical worst losses per sector
    # =====================================================================
    max_sector_exposure = max(industry_pct.values()) if industry_pct else 0.0
    
    # Use generic sector crash scenario - sector-specific historical data would require
    # individual sector proxy historical analysis which is complex and not always available
    sector_crash = WORST_CASE_SCENARIOS["sector_crash"]
    suggested_max_sector = max_loss / (sector_crash * current_leverage)
    
    suggestions["sector_limit"] = {
        "current_max_sector": max_sector_exposure,
        "suggested_max_sector": suggested_max_sector,
        "needs_reduction": max_sector_exposure > suggested_max_sector
    }
    
    # =====================================================================
    # 5. LEVERAGE LIMIT - Work backwards from worst-case scenario
    # =====================================================================
    # Find the worst-case unleveraged loss across all scenarios
    # Using CONSISTENT approach: historical data for ALL factors (market, momentum, value)
    worst_unleveraged_loss = 0.0
    
    # Check market scenario without leverage (use historical worst loss for consistency)
    market_beta = portfolio_betas.get("market", 0.0)
    market_crash = historical_worst_losses.get("market", WORST_CASE_SCENARIOS["market_crash"])
    market_loss = abs(market_beta * market_crash)
    worst_unleveraged_loss = max(worst_unleveraged_loss, market_loss)
    
    # Check factor scenarios without leverage using CONSISTENT approach
    # (same logic as risk scoring function)
    for factor in ["momentum", "value"]:
        factor_beta = portfolio_betas.get(factor, 0.0)
        worst_loss = historical_worst_losses.get(factor, WORST_CASE_SCENARIOS[f"{factor}_crash"])
        factor_impact = factor_beta * -worst_loss
        # Only count negative impacts (losses) as risk
        if factor_impact < 0:  # Loss
            factor_loss = abs(factor_impact)
            worst_unleveraged_loss = max(worst_unleveraged_loss, factor_loss)
    
    # Check concentration scenario without leverage
    concentration_loss = max_position * concentration_crash
    worst_unleveraged_loss = max(worst_unleveraged_loss, concentration_loss)
    
    # Check volatility scenario without leverage  
    vol_loss = actual_vol  # Simple proxy
    worst_unleveraged_loss = max(worst_unleveraged_loss, vol_loss)
    
    # Check sector scenario without leverage using generic sector crash
    max_sector_exposure = max(industry_pct.values()) if industry_pct else 0.0
    sector_loss_unleveraged = max_sector_exposure * WORST_CASE_SCENARIOS["sector_crash"]
    worst_unleveraged_loss = max(worst_unleveraged_loss, sector_loss_unleveraged)
    
    # max_loss = worst_unleveraged_loss × leverage
    # So: leverage ≤ max_loss / worst_unleveraged_loss
    suggested_max_leverage = max_loss / worst_unleveraged_loss if worst_unleveraged_loss > 0 else float('inf')
    
    suggestions["leverage_limit"] = {
        "current_leverage": current_leverage,
        "suggested_max_leverage": suggested_max_leverage,
        "worst_unleveraged_loss": worst_unleveraged_loss,
        "needs_reduction": current_leverage > suggested_max_leverage
    }
    
    return suggestions


def display_suggested_risk_limits(suggestions: Dict[str, Any], max_loss: float):
    """
    Pretty-print the risk-limit recommendations produced by
    ``calculate_suggested_risk_limits``.

    This helper is intended for interactive CLI or notebook sessions
    where a human-readable summary is more useful than the raw
    dictionary.  The function prints:

    • A headline describing the user’s maximum-loss tolerance and, if
      applicable, the leverage-adjusted context.  
    • A coloured block for each limit category (factor, concentration,
      volatility, sector) showing the current value versus the
      suggested maximum.  
    • A "💡 Priority Actions" section that lists the most urgent
      remediation steps, ranked by severity.

    Parameters
    ----------
    suggestions : Dict[str, Any]
        The structure returned by ``calculate_suggested_risk_limits``.
    max_loss : float
        Absolute maximum portfolio loss tolerance (e.g. ``0.25`` for
        25 %).  Used only for display; the function does **not** mutate
        the input data.

    Returns
    -------
    None
        The report is written directly to ``stdout``.  Callers can
        choose to capture or redirect the output if required.

    Notes
    -----
    The function intentionally performs no internal logging so that it
    can be composed inside higher-level helpers like
    ``_format_risk_score_output`` which handle logging/capture.
    """
    # Get current leverage for display
    current_leverage = suggestions.get("leverage_limit", {}).get("current_leverage", 1.0)
    
    print(f"\n{'='*60}")
    print(f"📋 SUGGESTED RISK LIMITS (to stay within {max_loss:.0%} max loss)")
    print(f"Working backwards from your risk tolerance to show exactly what needs to change")
    leverage_display_threshold = RISK_ANALYSIS_THRESHOLDS["leverage_display_threshold"]
    if current_leverage > leverage_display_threshold:
        print(f"Adjusted for your current {current_leverage:.2f}x leverage - limits are tighter")
    print(f"{'='*60}")
    
    # Factor limits
    factor_limits = suggestions["factor_limits"]
    if factor_limits:
        print(f"\n🎯 Factor Beta Limits: (Beta = sensitivity to market moves)")
        print(f"{'─'*40}")
        for factor, data in factor_limits.items():
            status = "🔴 REDUCE" if data["needs_reduction"] else "🟢 OK"
            factor_name = factor.replace('_', ' ').title().replace('Beta', 'Exposure')
            current_val = data['current']
            suggested_val = data['suggested_max']
            
            # Add note for negative values (hedges)
            note = ""
            if current_val < 0:
                note = " (hedge position)"
            
            print(f"{status} {factor_name:<15} Current: {current_val:>6.2f}{note}  →  Max: {suggested_val:>6.2f}")
    
    # Concentration limit
    conc = suggestions["concentration_limit"]
    conc_status = "🔴 REDUCE" if conc["needs_reduction"] else "🟢 OK"
    print(f"\n🎯 Position Size Limit:")
    print(f"{'─'*40}")
    print(f"{conc_status} Max Position Size     Current: {conc['current_max_position']:>6.1%}  →  Max: {conc['suggested_max_position']:>6.1%}")
    
    # Volatility limit
    vol = suggestions["volatility_limit"]
    vol_status = "🔴 REDUCE" if vol["needs_reduction"] else "🟢 OK"
    print(f"\n🎯 Volatility Limit:")
    print(f"{'─'*40}")
    print(f"{vol_status} Portfolio Volatility  Current: {vol['current_volatility']:>6.1%}  →  Max: {vol['suggested_max_volatility']:>6.1%}")
    
    # Sector limit
    sector = suggestions["sector_limit"]
    sector_status = "🔴 REDUCE" if sector["needs_reduction"] else "🟢 OK"
    print(f"\n🎯 Sector Concentration Limit:")
    print(f"{'─'*40}")
    print(f"{sector_status} Max Sector Exposure   Current: {sector['current_max_sector']:>6.1%}  →  Max: {sector['suggested_max_sector']:>6.1%}")
    
    print(f"\n💡 Priority Actions:")
    print(f"{'─'*40}")
    
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
        print("   🟢 Portfolio structure is within suggested limits!")
    else:
        for i, issue in enumerate(issues, 1):
            print(f"   {i}. {issue}")
    
    print(f"\n{'='*60}")


def generate_score_interpretation(score: float) -> Dict[str, Any]:
    """
    Generate comprehensive score interpretation with both risk assessment and actionable guidance.
    
    This function creates interpretation content used by both the CLI display and API response 
    to ensure consistency across interfaces. Returns both risk-focused context and actionable steps.
    
    Parameters
    ----------
    score : float
        Overall risk score (0-100 scale)
        
    Returns
    -------
    Dict[str, Any]
        Interpretation with:
        - 'summary': Action-focused title (for display)
        - 'details': Actionable steps (for user guidance)  
        - 'risk_assessment': Risk-focused context (for risk understanding)
    """
    if score >= 90:
        interpretation_summary = "🟢 EXCELLENT: Portfolio structure is well-balanced"
        interpretation_details = [
            "Continue current allocation strategy",
            "Monitor for any concentration drift",
            "Consider tactical adjustments for market conditions"
        ]
        risk_assessment = [
            "All potential losses are well within acceptable limits",
            "Strong risk management across all components", 
            "Suitable for risk-averse investors"
        ]
    elif score >= 80:
        interpretation_summary = "🟡 GOOD: Portfolio needs minor tweaks"
        interpretation_details = [
            "Trim positions exceeding target allocations",
            "Consider adding defensive positions if volatility spikes",
            "Review factor exposures quarterly"
        ]
        risk_assessment = [
            "Most potential losses are within acceptable limits",
            "Minor risk management improvements recommended",
            "Suitable for most investors"
        ]
    elif score >= 70:
        interpretation_summary = "🟠 FAIR: Portfolio requires rebalancing"
        interpretation_details = [
            "Reduce largest positions to improve diversification",
            "Add hedges for concentrated exposures",
            "Consider lowering systematic risk through position sizing"
        ]
        risk_assessment = [
            "Some potential losses exceed acceptable limits",
            "Risk management improvements needed",
            "Monitor positions closely"
        ]
    elif score >= 60:
        interpretation_summary = "🔴 POOR: Portfolio needs significant restructuring"
        interpretation_details = [
            "Address high-risk components through hedging or deleveraging",
            "Reduce concentrated positions exceeding risk limits",
            "Consider systematic risk reduction strategies"
        ]
        risk_assessment = [
            "Multiple potential losses exceed acceptable limits",
            "Significant risk management action required",
            "Consider reducing exposures"
        ]
    else:
        interpretation_summary = "⚫ VERY POOR: Portfolio needs immediate restructuring"
        interpretation_details = [
            "Address highest-risk components immediately",
            "Reduce positions exceeding acceptable loss limits",
            "Consider temporary risk reduction until rebalanced"
        ]
        risk_assessment = [
            "Very high disruption risk - immediate action required",
            "Portfolio exceeds acceptable risk limits significantly", 
            "Requires comprehensive restructuring"
        ]
    
    return {
        "summary": interpretation_summary,
        "details": interpretation_details,
        "risk_assessment": risk_assessment
    }


def calculate_portfolio_risk_score(
    summary: Dict[str, Any],
    portfolio_limits: Dict[str, float],
    concentration_limits: Dict[str, float],
    variance_limits: Dict[str, float],
    max_betas: Dict[str, float],
    max_proxy_betas: Optional[Dict[str, float]] = None,
    leverage_ratio: float = 1.0,
    max_single_factor_loss: float = None,
    security_types: Optional[Dict[str, str]] = None,
    portfolio_data=None,
) -> Dict[str, Any]:
    """
    Calculate a comprehensive risk score (0-100) for a portfolio based on 
    potential losses under worst-case scenarios vs. user-defined loss limits.
    
    The score measures "disruption risk" - how likely the portfolio is to
    exceed the user's maximum acceptable loss in various failure scenarios.
    
    Parameters
    ----------
    summary : Dict[str, Any]
        Output from build_portfolio_view()
    portfolio_limits : Dict[str, float]
        Portfolio-level risk limits (contains max_loss)
    concentration_limits : Dict[str, float]
        Concentration risk limits (kept for compatibility)
    variance_limits : Dict[str, float]
        Variance decomposition limits (kept for compatibility)
    max_betas : Dict[str, float]
        Maximum allowed factor betas for historical data lookup
    max_proxy_betas : Optional[Dict[str, float]]
        Maximum allowed proxy betas for historical data lookup
    leverage_ratio : float, default 1.0
        Portfolio leverage multiplier
    max_single_factor_loss : float, default -0.08
        Maximum single factor loss limit
        
    Returns
    -------
    Dict[str, Any]
        Risk score details including:
        - 'score': Overall risk score (0-100)
        - 'category': Risk category (Excellent, Good, Fair, Poor, Very Poor)
        - 'component_scores': Individual component scores
        - 'risk_factors': Specific risk issues identified
        - 'recommendations': Suggested improvements
        - 'potential_losses': Calculated loss potentials for each component
    """
    # Use default from settings if not provided
    if max_single_factor_loss is None:
        max_single_factor_loss = MAX_SINGLE_FACTOR_LOSS["portfolio"]
    
    # Get max loss limit from user preferences
    max_loss = abs(portfolio_limits["max_loss"])
    
    # Calculate potential losses under worst-case scenarios
    factor_loss = calculate_factor_risk_loss(summary, leverage_ratio, max_betas, max_single_factor_loss)
    concentration_loss = calculate_concentration_risk_loss(
        summary,
        leverage_ratio,
        portfolio_data=portfolio_data,
        security_types=security_types,
    )
    volatility_loss = calculate_volatility_risk_loss(summary, leverage_ratio)
    sector_loss = calculate_sector_risk_loss(summary, leverage_ratio, max_proxy_betas, max_single_factor_loss)
    
    # Score each component based on excess ratio
    component_scores = {
        "factor_risk": score_excess_ratio(factor_loss / max_loss),
        "concentration_risk": score_excess_ratio(concentration_loss / max_loss),
        "volatility_risk": score_excess_ratio(volatility_loss / max_loss),
        "sector_risk": score_excess_ratio(sector_loss / max_loss)
    }
    
    # Calculate overall score (weighted average)
    # Weight by importance for portfolio disruption
    weights = {
        "factor_risk": 0.35,        # Market crashes are common and severe
        "concentration_risk": 0.30,  # Single stock failures can be devastating
        "volatility_risk": 0.20,     # Less likely to be primary cause of disruption
        "sector_risk": 0.15         # Sector crashes less frequent but important
    }
    
    overall_score = sum(
        component_scores[component] * weight 
        for component, weight in weights.items()
    )
    
    # Determine risk category based on score
    if overall_score >= 90:
        category = "Excellent"
    elif overall_score >= 80:
        category = "Good"
    elif overall_score >= 70:
        category = "Fair"
    elif overall_score >= 60:
        category = "Poor"
    else:
        category = "Very Poor"
    
    # Simple risk factors for disruption scoring
    risk_factors = []
    recommendations = []
    
    # Only flag high-level disruption risks
    if factor_loss > max_loss:
        excess_pct = ((factor_loss / max_loss) - 1) * 100
        risk_factors.append(f"Market exposure could cause {factor_loss:.1%} loss (exceeds limit by {excess_pct:.0f}%)")
        recommendations.append("Reduce market exposure (sell high-beta stocks or add hedges)")
    
    leverage_threshold = RISK_ANALYSIS_THRESHOLDS["leverage_warning_threshold"]
    if leverage_ratio > leverage_threshold:
        risk_factors.append(f"Leverage ({leverage_ratio:.2f}x) amplifies all potential losses")
        recommendations.append("Consider reducing leverage to limit downside risk")
    
    # Generate interpretation using shared function
    interpretation = generate_score_interpretation(overall_score)

    return {
        "score": round(overall_score, 1),
        "category": category,
        "component_scores": {k: round(v, 1) for k, v in component_scores.items()},
        "risk_factors": risk_factors,
        "recommendations": recommendations,
        "interpretation": interpretation,
        "potential_losses": {
            "factor_risk": factor_loss,
            "concentration_risk": concentration_loss,
            "volatility_risk": volatility_loss,
            "sector_risk": sector_loss,
            "max_loss_limit": max_loss
        },
        "details": {
            "leverage_ratio": leverage_ratio,
            "max_loss_limit": max_loss,
            "excess_ratios": {
                "factor_risk": factor_loss / max_loss,
                "concentration_risk": concentration_loss / max_loss,
                "volatility_risk": volatility_loss / max_loss,
                "sector_risk": sector_loss / max_loss
            }
        }
    }


def display_portfolio_risk_score(risk_score: Dict[str, Any]) -> None:
    """
    Pretty-print a single portfolio disruption-risk score in a style
    inspired by consumer credit-score reports.

    The output includes:
    • Overall headline score with emoji-based colour coding for quick
      visual interpretation.  
    • Breakdown of component scores (factor, concentration, volatility,
      sector) together with short plain-English explanations.  
    • Key risk factors and actionable recommendations distilled from
      the numerical analysis.  
    • A concise interpretation block that maps the numeric score to an
      action level (Excellent → Very Poor).

    This function is designed for interactive CLI / notebook use where
    immediate human readability is valuable.  For programmatic
    consumption (for example in an API) rely on the structured dict
    returned by ``calculate_portfolio_risk_score``.

    Parameters
    ----------
    risk_score : Dict[str, Any]
        The dictionary returned by ``calculate_portfolio_risk_score``.

    Returns
    -------
    None
        Output is printed directly to ``stdout``.

    Raises
    ------
    KeyError
        If mandatory keys are missing from ``risk_score``.
    """
    score = risk_score["score"]
    category = risk_score["category"]
    component_scores = risk_score["component_scores"]
    risk_factors = risk_score["risk_factors"]
    recommendations = risk_score["recommendations"]
    
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
    
    print(f"\n{'='*60}")
    print(f"📊 PORTFOLIO RISK SCORE (Scale: 0-100, higher = better)")
    print(f"{'='*60}")
    print(f"{color} Overall Score: {score}/100 ({category})")
    
    # Show max loss context if available
    max_loss_limit = risk_score.get("details", {}).get("max_loss_limit", None)
    if max_loss_limit:
        print(f"Based on your {abs(max_loss_limit):.0%} maximum loss tolerance")
    
    print(f"{'='*60}")
    
    # Component breakdown with explanations
    print(f"\n📈 Component Scores: (Risk of exceeding loss tolerance)")
    print(f"{'─'*40}")
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
        print(f"{comp_color} {component_name:<15} ({explanation}) {comp_score:>5.1f}/100")
    
    # Risk factors with simplified language
    if risk_factors:
        print(f"\n⚠️  Risk Factors Identified:")
        print(f"{'─'*40}")
        for factor in risk_factors:
            # Simplify technical language
            simplified_factor = factor.replace("Factor exposure", "Market exposure")
            simplified_factor = simplified_factor.replace("systematic factor exposure", "market exposure")
            print(f"   • {simplified_factor}")
    
    # Recommendations with implementation guidance
    if recommendations:
        print(f"\n💡 Recommendations:")
        print(f"{'─'*40}")
        for rec in recommendations:
            simplified_rec = rec.replace("systematic factor exposure", "market exposure")
            simplified_rec = simplified_rec.replace("through hedging or position sizing", "(sell high-beta stocks or add hedges)")
            print(f"   • {simplified_rec}")
        
        # Add detailed implementation guidance
        print(f"\n🔧 How to Implement:")
        print(f"{'─'*40}")
        
        # Market/Factor exposure guidance
        if any("market exposure" in rec.lower() or "market factor" in rec.lower() for rec in recommendations):
            print("   • Reduce market exposure: Sell high-beta stocks, add market hedges (SPY puts), or increase cash")
        
        # Specific factor guidance
        if any("momentum" in rec.lower() for rec in recommendations):
            print("   • Reduce momentum exposure: Trim momentum-oriented positions or add momentum shorts")
        if any("value" in rec.lower() for rec in recommendations):
            print("   • Reduce value exposure: Trim value-oriented positions or add growth positions")
        
        # Sector-specific guidance
        sector_recs = [rec for rec in recommendations if any(sector in rec for sector in ["REM", "DSU", "XOP", "KIE", "XLK", "KCE", "SOXX", "ITA", "XLP", "SLV", "XLC"])]
        if sector_recs:
            print("   • Reduce sector concentration: Trim specific sector ETF positions or add offsetting sectors")
        
        # Concentration/diversification guidance
        if any("concentration" in rec.lower() or "position size" in rec.lower() for rec in recommendations):
            print("   • Reduce concentration: Trim largest positions, spread allocation across more stocks")
        if any("diversification" in rec.lower() for rec in recommendations):
            print("   • Improve diversification: Add more positions across different sectors and factors")
        
        # Volatility guidance
        if any("volatility" in rec.lower() for rec in recommendations):
            print("   • Reduce volatility: Add defensive stocks, increase cash, or add volatility hedges")
        
        # Systematic risk guidance
        if any("systematic" in rec.lower() for rec in recommendations):
            print("   • Reduce systematic risk: Lower factor exposures, add uncorrelated assets")
        
        # Leverage guidance
        if any("leverage" in rec.lower() for rec in recommendations):
            print("   • Reduce leverage: Increase cash position, pay down margin, or reduce position sizes")
    
    # Score interpretation - action-focused
    print(f"\n📋 Score Interpretation:")
    print(f"{'─'*40}")
    interpretation = generate_score_interpretation(score)
    print(f"   {interpretation['summary']}")
    for detail in interpretation['details']:
        print(f"      • {detail}")
    
    # Risk assessment - contextual understanding
    print(f"\n📊 Risk Assessment:")
    print(f"{'─'*40}")
    for assessment in interpretation['risk_assessment']:
        print(f"   • {assessment}")
    
    print(f"\n{'='*60}")


def _format_risk_score_output(risk_score: Dict[str, Any], limits_analysis: Dict[str, Any], suggestions: Dict[str, Any], max_loss: float) -> str:
    """
    Compose a consolidated, human-readable report string that combines
    all pieces of the disruption-risk analysis.

    This helper simply redirects ``stdout`` to an in-memory buffer,
    invokes the existing *display* utilities and then returns the
    captured text.  No additional calculations are performed; the
    function is pure presentation logic and has no side-effects other
    than the temporary redirection of the standard output streams.

    Parameters
    ----------
    risk_score : Dict[str, Any]
        Dictionary produced by :pyfunc:`calculate_portfolio_risk_score`.
    limits_analysis : Dict[str, Any]
        Dictionary produced by :pyfunc:`analyze_portfolio_risk_limits`.
    suggestions : Dict[str, Any]
        Dictionary produced by :pyfunc:`calculate_suggested_risk_limits`.
    max_loss : float
        Absolute maximum-loss tolerance (e.g. ``0.25`` for 25 %). Used
        exclusively for labelling inside the printed report.

    Returns
    -------
    str
        A multi-line string that mirrors the CLI output of the
        high-level analysis workflow.

    Notes
    -----
    • The helper is intended for API endpoints or e-mail integrations
      where returning a single string blob is more convenient than a
      series of ``print`` statements.
    • All input dictionaries remain unchanged; the function does **not**
      mutate state.

    Examples
    --------
    >>> fmt = _format_risk_score_output(risk, limits, sugg, 0.25)
    >>> send_email("Risk Report", fmt)
    """
    import io
    import sys
    from contextlib import redirect_stdout
    
    # Capture the formatted output
    f = io.StringIO()
    with redirect_stdout(f):
        # Display comprehensive disruption risk score with explanations
        display_portfolio_risk_score(risk_score)
        
        # Display detailed risk limits analysis
        print("\n" + "═" * 80)
        print("📋 DETAILED RISK LIMITS ANALYSIS")
        print("═" * 80)
        
        # Display limit violations summary
        violations = limits_analysis["limit_violations"]
        total_violations = sum(violations.values())
        
        print(f"\n📊 LIMIT VIOLATIONS SUMMARY:")
        print(f"   Total violations: {total_violations}")
        print(f"   Factor betas: {violations['factor_betas']}")
        print(f"   Concentration: {violations['concentration']}")
        print(f"   Volatility: {violations['volatility']}")
        print(f"   Variance contributions: {violations['variance_contributions']}")
        print(f"   Leverage: {violations['leverage']}")
        
        # Display detailed risk factors
        if limits_analysis["risk_factors"]:
            print(f"\n⚠️  KEY RISK FACTORS:")
            for factor in limits_analysis["risk_factors"]:
                print(f"   • {factor}")
        
        # Display detailed recommendations
        if limits_analysis["recommendations"]:
            print(f"\n💡 KEY RECOMMENDATIONS:")
            
            # Filter recommendations to show only beta-based ones (more intuitive for users)
            beta_recommendations = []
            for rec in limits_analysis["recommendations"]:
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
                print(f"   • {rec}")
        
        # Display suggested risk limits
        display_suggested_risk_limits(suggestions, max_loss)
    
    return f.getvalue()


# Import logging decorators for risk scoring
from portfolio_risk_engine._logging import log_operation, log_timing, log_errors, portfolio_logger

@log_errors("high")
@log_operation("risk_score_analysis")
@log_timing(5.0)
def run_risk_score_analysis(
    portfolio: Union[str, PortfolioData] = "portfolio.yaml",
    risk_limits: Union[str, RiskLimitsData, Dict[str, Any], None] = "risk_limits.yaml",
    *,
    return_data: bool = False,
):
    """
    High-level orchestration entry point for generating a full disruption-risk
    assessment of a single portfolio.

    Called by:
    - CLI usage and service wrappers that need risk-score + limit suggestions.

    Calls into:
    - Portfolio/risk config loaders and `build_portfolio_view`.
    - Risk scoring helpers (component score, violation analysis, suggestions).

    Contract:
    - In data mode returns JSON-safe dict for API/service consumers.
    - In CLI mode prints formatted report and still returns data dict.

    The function performs the following steps:

    1. **Load configuration** – reads the *portfolio* definition and the
       *risk-limit* preferences from YAML files.
    2. **Standardise weights** – converts raw position weights into
       consistent economic exposure using latest prices.
    3. **Build portfolio view** – enriches the position list with factor
       exposures, return/variance statistics, and industry breakdowns.
    4. **Compute analytics** –
       • overall 0-100 disruption-risk score;
       • detailed limit-violation analysis;
       • backward-calculated risk-limit suggestions that would keep the
         portfolio within the user-specified maximum loss tolerance.
    5. **Render output** – either prints a richly formatted report to
       *stdout* (CLI/notebook usage) **or** returns all artefacts as a
       JSON-serialisable dictionary for API callers when
       ``return_data=True``.

    Several logging decorators wrap this function to capture execution
    time, CPU/memory usage, and workflow state, and to provide robust
    error handling.

    Parameters
    ----------
    portfolio : Union[str, PortfolioData], optional
        Portfolio input as file path or in-memory PortfolioData object.
    risk_limits : Union[str, RiskLimitsData, Dict[str, Any], None], optional
        Risk limits input as file path, typed object, dict, or None.
    return_data : bool, default ``False``
        If ``True`` the function suppresses the console report and
        instead returns a dictionary with all intermediate and final
        results. In the default *False* mode the report is printed but
        the same dictionary is still returned so that callers can
        inspect it programmatically.

    Returns
    -------
    dict | None
        A JSON-safe dictionary with the keys ``risk_score``,
        ``limits_analysis``, ``portfolio_analysis``, and
        ``suggested_limits``. ``None`` is returned only when the routine
        aborts early because mandatory dependencies are missing or a
        fatal exception occurs.

    Raises
    ------
    Exception
        Propagated from lower-level helpers if the analysis fails.

    Examples
    --------
    >>> # CLI usage (prints report)
    >>> python -m portfolio_risk_score

    >>> # Programmatic usage
    >>> from portfolio_risk_score import run_risk_score_analysis
    >>> out = run_risk_score_analysis("my_portfolio.yaml", "my_risk.yaml", return_data=True)
    >>> print(out["risk_score"]["score"])
    """
    
    # LOGGING: Add risk score analysis start logging
    # LOGGING: Add workflow state logging for risk score analysis workflow here
    # LOGGING: Add resource usage monitoring for risk score calculation here
    # LOGGING: Add component score logging
    # LOGGING: Add recommendation generation logging
    # LOGGING: Add score validation logging
    if build_portfolio_view is None or calc_max_factor_betas is None or standardize_portfolio_input is None:
        print("Error: Required modules not available. Make sure portfolio-risk-engine is installed.")
        return
    
    try:
        # Load configuration
        # LOGGING: Add configuration load timing
        config, portfolio_file = resolve_portfolio_config(portfolio)
        risk_config = resolve_risk_config(risk_limits)

        portfolio_source = portfolio_file or "(in-memory)"
        print(f"Analyzing portfolio from {portfolio_source}...")
        
        # Standardize portfolio weights first
        raw_weights = config["portfolio_input"]
        fmp_ticker_map = config.get("fmp_ticker_map")
        currency_map = config.get("currency_map")
        if fmp_ticker_map:
            price_fetcher = lambda t: latest_price(
                t,
                fmp_ticker_map=fmp_ticker_map,
                currency=currency_map.get(t) if currency_map else None,
            )
        else:
            price_fetcher = lambda t: latest_price(
                t,
                currency=currency_map.get(t) if currency_map else None,
            )
        standardized = standardize_portfolio_input(
            raw_weights,
            price_fetcher,
            currency_map=currency_map,
            fmp_ticker_map=fmp_ticker_map,
        )
        weights = standardized["weights"]
        portfolio_data = portfolio if isinstance(portfolio, PortfolioData) else None

        # Resolve security types once and thread through downstream concentration checks.
        security_types = None
        if SecurityTypeService:
            try:
                tickers = list(weights.keys())
                security_types = SecurityTypeService.get_security_types(tickers, portfolio_data)
            except Exception as e:
                portfolio_logger.warning(f"Security type lookup failed in risk score path, falling back: {e}")
                security_types = None
        
        # Build portfolio view with standardized weights
        summary = build_portfolio_view(
            weights=weights,
            start_date=config["start_date"],
            end_date=config["end_date"],
            expected_returns=config.get("expected_returns"),
            stock_factor_proxies=config.get("stock_factor_proxies"),
            fmp_ticker_map=fmp_ticker_map,
            currency_map=currency_map,
        )
        
        # Calculate max betas
        from portfolio_risk_engine.config import PORTFOLIO_DEFAULTS
        lookback_years = PORTFOLIO_DEFAULTS.get('worst_case_lookback_years', 10)
        configured_factor_loss = risk_config.get("factor_limits", {}).get(
            "max_single_factor_loss",
            risk_config.get("max_single_factor_loss", -0.08),
        )
        max_betas, max_betas_by_proxy, historical_analysis = calc_max_factor_betas(
            lookback_years=lookback_years,
            echo=False,
            stock_factor_proxies=config.get("stock_factor_proxies"),
            fmp_ticker_map=fmp_ticker_map,
            max_single_factor_loss=configured_factor_loss,
        )
        
        # Calculate leverage ratio
        # standardize_portfolio_input always returns leverage, no fallback needed
        leverage_ratio = standardized["leverage"]
        
        # IMPORTANT: Always use actual leverage for risk calculations
        # Leverage amplifies risk regardless of how portfolio weights are calculated
        # The normalize_weights setting affects weight calculation, not risk amplification
        risk_leverage_ratio = leverage_ratio
        
        # ═══════════════════════════════════════════════════════════════════════════
        # DISRUPTION RISK SCORING (High-level 0-100 score)
        # ═══════════════════════════════════════════════════════════════════════════
        
        # Use the user's configured factor loss limit (check both possible locations)
        max_single_factor_loss = configured_factor_loss
        
        # Calculate disruption risk score
        risk_score = calculate_portfolio_risk_score(
            summary=summary,
            portfolio_limits=risk_config["portfolio_limits"],
            concentration_limits=risk_config["concentration_limits"],
            variance_limits=risk_config["variance_limits"],
            max_betas=max_betas,
            max_proxy_betas=max_betas_by_proxy,
            leverage_ratio=risk_leverage_ratio,
            max_single_factor_loss=max_single_factor_loss,
            security_types=security_types,
            portfolio_data=portfolio_data,
        )
        
        # Calculate and display suggested risk limits
        max_loss = abs(risk_config["portfolio_limits"]["max_loss"])
        suggestions = calculate_suggested_risk_limits(
            summary,
            max_loss,
            risk_leverage_ratio,
            max_single_factor_loss,
            config.get("stock_factor_proxies"),
            config.get("start_date"),
            config.get("end_date"),
            security_types=security_types,
        )
        
        # Perform detailed risk limits analysis
        limits_analysis = analyze_portfolio_risk_limits(
            summary=summary,
            portfolio_limits=risk_config["portfolio_limits"],
            concentration_limits=risk_config["concentration_limits"],
            variance_limits=risk_config["variance_limits"],
            max_betas=max_betas,
            max_proxy_betas=max_betas_by_proxy,
            leverage_ratio=risk_leverage_ratio,
            security_types=security_types,
        )
        
        # Build result object using new builder method
        result = RiskScoreResult.from_risk_score_analysis(
            risk_score=risk_score,
            limits_analysis=limits_analysis,
            portfolio_analysis=summary,
            suggested_limits=suggestions,
            analysis_metadata={
                "analysis_date": datetime.now(UTC).isoformat(),
                "portfolio_file": portfolio_file,
                "risk_limits_file": risk_limits if isinstance(risk_limits, str) else None,
                "portfolio_name": (
                    os.path.basename(portfolio_file).replace(".yaml", "")
                    if portfolio_file
                    else config.get("name", "portfolio")
                ),
                "max_loss": max_loss,
                "analysis_type": "risk_score",
                "security_types": security_types,
            }
        )

        if return_data:
            # API/Data mode - return result object for API conversion
            return result
        else:
            # CLI mode - print formatted output
            print(result.to_cli_report())
            return result  # For programmatic access
        
    except Exception as e:
        print(f"Error running risk score analysis: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    # Run the risk score analysis
    risk_score = run_risk_score_analysis()
    
    if risk_score:
        print(f"\n✅ Risk score analysis completed successfully!")
        print(f"   Score: {risk_score.risk_score['score']}/100")
        print(f"   Category: {risk_score.risk_score['category']}")
    else:
        print("\n❌ Risk score analysis failed. Check your configuration files.") 

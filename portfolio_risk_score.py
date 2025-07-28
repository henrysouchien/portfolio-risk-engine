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
import yaml
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime

# Import existing modules without modifying them
try:
    from portfolio_risk import build_portfolio_view
    from risk_helpers import calc_max_factor_betas
    from run_portfolio_risk import standardize_portfolio_input, latest_price
except ImportError:
    print("Warning: Could not import existing modules. Make sure you're in the risk_module directory.")
    build_portfolio_view = None
    calc_max_factor_betas = None
    standardize_portfolio_input = None
    latest_price = None


# =====================================================================
# WORST-CASE SCENARIO DEFINITIONS (Module-level constants)
# =====================================================================
# These scenarios define the stress tests used for risk calculations
# 
# DATA SOURCE HIERARCHY:
# 1. Historical Data: Preferred when available (via max_betas parameters)
# 2. Configured Scenarios: Fallback values defined below
# 
# USAGE BY FUNCTION:
# - calculate_factor_risk_loss: Historical → Fallback to configured
# - calculate_sector_risk_loss: Historical → Fallback to configured  
# - calculate_concentration_risk_loss: Always uses configured scenarios
# - calculate_volatility_risk_loss: Always uses configured scenarios
# - calculate_suggested_risk_limits: Historical → Fallback to configured
#
# Update these values as new historical data becomes available

WORST_CASE_SCENARIOS = {
    # Market crash scenario - based on major historical crashes
    # 2008: -37%, 2000-2002: -49%, 2020: -34%, 1987: -22%
    "market_crash": 0.35,
    
    # Factor-specific scenarios - for momentum/value tilts
    # These use individual factor loss limits since they're specific bets
    "momentum_crash": 0.50,  # Momentum factor reversal
    "value_crash": 0.40,     # Value factor underperformance
    
    # Concentration scenarios
    "single_stock_crash": 0.80,  # Individual stock failure
    "sector_crash": 0.50,        # Sector-wide crisis
    
    # Volatility scenarios
    "max_reasonable_volatility": 0.40,  # Maximum reasonable portfolio volatility
}


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
        Score from 0-100 based on excess ratio
        - 100: Very safe (≤80% of limit)
        - 75: At limit threshold  
        - 50: Moderately over limit
        - 0: Significantly over limit (≥150%)
    """
    if excess_ratio <= 0.8:        # 20% buffer below limit
        return 100  # Safe - Very low disruption risk
    elif excess_ratio <= 1.0:      # At limit
        return 75   # Caution - Some disruption risk
    elif excess_ratio <= 1.5:      # 50% over limit
        return 50   # Danger - High disruption risk
    else:                          # Way over limit
        return 0    # Critical - Certain disruption


def calculate_factor_risk_loss(summary: Dict[str, Any], leverage_ratio: float, max_betas: Dict[str, float] = None, max_single_factor_loss: float = -0.10) -> float:
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
    portfolio_betas = summary["portfolio_factor_betas"]
    
    # For PORTFOLIO RISK SCORE: Use historical data for ALL factors when available
    worst_case_scenarios = {}
    
    if max_betas:
        # Use historical data for ALL factors (including market)
        loss_limit = max_single_factor_loss
        
        for factor in ["market", "momentum", "value"]:
            max_beta = max_betas.get(factor, 0.77)  # Default fallback
            if max_beta != 0 and max_beta != float('inf'):
                # Use historical data: max_beta = loss_limit / worst_loss, so worst_loss = loss_limit / max_beta
                worst_case_scenarios[factor] = loss_limit / max_beta
            else:
                # Fallback to configured scenarios if no historical data
                worst_case_scenarios[factor] = -{
                    "market": WORST_CASE_SCENARIOS["market_crash"],
                    "momentum": WORST_CASE_SCENARIOS["momentum_crash"],
                    "value": WORST_CASE_SCENARIOS["value_crash"]
                }.get(factor, 0.30)
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


def calculate_concentration_risk_loss(summary: Dict[str, Any], leverage_ratio: float) -> float:
    """
    Calculate potential loss from single stock concentration.
    
    DATA SOURCE: Always uses configured WORST_CASE_SCENARIOS
    
    Parameters
    ----------
    summary : Dict[str, Any]
        Portfolio analysis with position weights
    leverage_ratio : float
        Portfolio leverage multiplier (use 1.0 when weights already include leverage)
        
    Returns
    -------
    float
        Potential loss from largest single position
        
    Notes
    -----
    - Uses largest absolute position weight from portfolio
    - Applies configured single_stock_crash scenario (80% loss)
    - Formula: max_position × single_stock_crash × leverage_ratio
    """
    weights = summary["allocations"]["Portfolio Weight"]
    max_position = weights.abs().max()
    
    # Use configured single stock crash scenario
    single_stock_crash = WORST_CASE_SCENARIOS["single_stock_crash"]
    concentration_loss = max_position * single_stock_crash * leverage_ratio
    return concentration_loss


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


def calculate_sector_risk_loss(summary: Dict[str, Any], leverage_ratio: float, max_betas_by_proxy: Dict[str, float] = None, max_single_factor_loss: float = -0.08) -> float:
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
    leverage_ratio: float = 1.0
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
            
            if beta_ratio > 1.0:  # Exceeds limit
                risk_factors.append(f"High {factor} exposure: β={actual_beta:.2f} vs {max_beta:.2f} limit")
                if factor == "market":
                    recommendations.append("Reduce market exposure (sell high-beta stocks or add market hedges)")
                else:
                    recommendations.append(f"Reduce {factor} factor exposure")
            elif beta_ratio > 0.75:  # Approaching limit  
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
                
                if beta_ratio > 0.75:  # Flag if >75% of limit
                    risk_factors.append(f"High {proxy} exposure: β={actual_beta:.2f} vs {max_beta:.2f} limit")
                    recommendations.append(f"Reduce exposure to {proxy} sector")
    
    # ─── 2. Concentration Limit Analysis ──────────────────────────────────────
    weights = summary["allocations"]["Portfolio Weight"]
    max_weight = weights.abs().max()
    herfindahl = summary["herfindahl"]
    weight_limit = concentration_limits["max_single_stock_weight"]
    
    # Check position concentration
    if max_weight > weight_limit:
        risk_factors.append(f"High concentration: {max_weight:.1%} vs {weight_limit:.1%} limit")
        recommendations.append("Reduce position size in largest holdings")
    elif max_weight > weight_limit * 0.8:  # Approaching limit
        risk_factors.append(f"High concentration: {max_weight:.1%} in single position")
        recommendations.append("Reduce position size in largest holdings")
    
    # Check diversification
    if herfindahl > 0.15:
        risk_factors.append(f"Low diversification (HHI: {herfindahl:.3f})")
        recommendations.append("Add more positions to improve diversification")
    
    # ─── 3. Volatility Limit Analysis ─────────────────────────────────────────
    actual_vol = summary["volatility_annual"]
    vol_limit = portfolio_limits["max_volatility"]
    
    if actual_vol > vol_limit:
        risk_factors.append(f"High volatility: {actual_vol:.1%} vs {vol_limit:.1%} limit")
        recommendations.append("Reduce portfolio volatility through diversification or defensive positions")
    elif actual_vol > vol_limit * 0.8:  # Approaching limit
        risk_factors.append(f"High portfolio volatility ({actual_vol:.1%})")
        recommendations.append("Reduce volatility through diversification or defensive positions")
    
    # ─── 4. Variance Contribution Analysis ────────────────────────────────────
    var_decomp = summary["variance_decomposition"]
    factor_pct = var_decomp["factor_pct"]
    market_pct = var_decomp["factor_breakdown_pct"].get("market", 0.0)
    
    # Check factor variance contribution
    factor_limit = variance_limits["max_factor_contribution"]
    if factor_pct > factor_limit:
        risk_factors.append(f"High systematic risk: {factor_pct:.1%} vs {factor_limit:.1%} limit")
        
        # Identify which specific factors are contributing most to variance
        factor_breakdown = var_decomp["factor_breakdown_pct"]
        # Sort factors by contribution (descending)
        sorted_factors = sorted(factor_breakdown.items(), key=lambda x: x[1], reverse=True)
        
        # Generate specific recommendations for the top contributors
        for factor, contribution in sorted_factors:
            if contribution > 5.0:  # Only recommend for factors contributing >5%
                recommendations.append(f"Reduce {factor} factor exposure (contributing {contribution:.1%} to variance)")
                
    elif factor_pct > factor_limit * 0.8:  # Approaching limit
        risk_factors.append(f"High systematic risk: {factor_pct:.1%} variance from factors")
        
        # Identify which specific factors are contributing most to variance
        factor_breakdown = var_decomp["factor_breakdown_pct"]
        # Sort factors by contribution (descending)
        sorted_factors = sorted(factor_breakdown.items(), key=lambda x: x[1], reverse=True)
        
        # Generate specific recommendations for the top contributors
        for factor, contribution in sorted_factors:
            if contribution > 5.0:  # Only recommend for factors contributing >5%
                recommendations.append(f"Reduce {factor} factor exposure (contributing {contribution:.1%} to variance)")
    
    # Check market variance contribution
    market_limit = variance_limits["max_market_contribution"]
    if market_pct > market_limit:
        risk_factors.append(f"High market variance contribution: {market_pct:.1%} vs {market_limit:.1%} limit")
        recommendations.append("Reduce market factor exposure")
    elif market_pct > market_limit * 0.8:  # Approaching limit
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
            if len([ind for ind, pct in sorted_industries if pct > industry_limit * 0.5]) > 1:
                recommendations.append("Add diversification across multiple industries")
        else:
            recommendations.append("Reduce industry concentration through diversification")
    
    # ─── 6. Leverage Analysis ─────────────────────────────────────────────────
    if leverage_ratio > 1.1:
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


def calculate_suggested_risk_limits(summary: Dict[str, Any], max_loss: float, current_leverage: float, max_single_factor_loss: float = -0.10, stock_factor_proxies: Dict = None, start_date: str = None, end_date: str = None) -> Dict[str, Any]:
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
    - Concentration: Always uses configured single_stock_crash (80%)
    - Volatility: Simple volatility ≤ max_loss / leverage proxy
    - Sector: Always uses configured sector_crash (50%)
    - Leverage: Calculated from worst-case scenario across all risk types
    
    Historical Data Fallback:
    If historical calculation fails, automatically falls back to configured scenarios
    with warning message to user.
    """
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
            from risk_helpers import get_worst_monthly_factor_losses, aggregate_worst_losses_by_factor_type
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
    max_position = weights.abs().max()
    single_stock_crash = WORST_CASE_SCENARIOS["single_stock_crash"]
    # max_loss = max_position × single_stock_crash × leverage
    # So: max_position ≤ max_loss / (single_stock_crash × leverage)
    suggested_max_position = max_loss / (single_stock_crash * current_leverage)
    
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
        worst_loss = historical_worst_losses.get(factor, WORST_CASE_SCENARIOS.get(f"{factor}_crash", 0.30))
        factor_impact = factor_beta * -worst_loss
        # Only count negative impacts (losses) as risk
        if factor_impact < 0:  # Loss
            factor_loss = abs(factor_impact)
            worst_unleveraged_loss = max(worst_unleveraged_loss, factor_loss)
    
    # Check concentration scenario without leverage
    concentration_loss = max_position * WORST_CASE_SCENARIOS["single_stock_crash"]
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
    Display suggested risk limits in a user-friendly format.
    """
    # Get current leverage for display
    current_leverage = suggestions.get("leverage_limit", {}).get("current_leverage", 1.0)
    
    print(f"\n{'='*60}")
    print(f"📋 SUGGESTED RISK LIMITS (to stay within {max_loss:.0%} max loss)")
    print(f"Working backwards from your risk tolerance to show exactly what needs to change")
    if current_leverage > 1.01:
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


def calculate_portfolio_risk_score(
    summary: Dict[str, Any],
    portfolio_limits: Dict[str, float],
    concentration_limits: Dict[str, float],
    variance_limits: Dict[str, float],
    max_betas: Dict[str, float],
    max_proxy_betas: Optional[Dict[str, float]] = None,
    leverage_ratio: float = 1.0,
    max_single_factor_loss: float = -0.08
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
    
    # Get max loss limit from user preferences
    max_loss = abs(portfolio_limits["max_loss"])
    
    # Calculate potential losses under worst-case scenarios
    factor_loss = calculate_factor_risk_loss(summary, leverage_ratio, max_betas, max_single_factor_loss)
    concentration_loss = calculate_concentration_risk_loss(summary, leverage_ratio)
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
    
    if leverage_ratio > 1.1:
        risk_factors.append(f"Leverage ({leverage_ratio:.2f}x) amplifies all potential losses")
        recommendations.append("Consider reducing leverage to limit downside risk")
    
    # Generate interpretation
    if overall_score >= 90:
        interpretation_summary = "Portfolio has very low disruption risk"
        interpretation_details = [
            "All potential losses are well within acceptable limits",
            "Strong risk management across all components",
            "Suitable for risk-averse investors"
        ]
    elif overall_score >= 80:
        interpretation_summary = "Portfolio has acceptable disruption risk"
        interpretation_details = [
            "Most potential losses are within acceptable limits",
            "Minor risk management improvements recommended",
            "Suitable for most investors"
        ]
    elif overall_score >= 70:
        interpretation_summary = "Portfolio has moderate disruption risk"
        interpretation_details = [
            "Some potential losses exceed acceptable limits",
            "Risk management improvements needed",
            "Monitor positions closely"
        ]
    elif overall_score >= 60:
        interpretation_summary = "Portfolio has high disruption risk"
        interpretation_details = [
            "Multiple potential losses exceed acceptable limits",
            "Significant risk management action required",
            "Consider reducing exposures"
        ]
    else:
        interpretation_summary = "Portfolio needs immediate restructuring"
        interpretation_details = [
            "Address highest-risk components immediately",
            "Reduce positions exceeding acceptable loss limits",
            "Consider temporary risk reduction until rebalanced"
        ]

    return {
        "score": round(overall_score, 1),
        "category": category,
        "component_scores": {k: round(v, 1) for k, v in component_scores.items()},
        "risk_factors": risk_factors,
        "recommendations": recommendations,
        "interpretation": {
            "summary": interpretation_summary,
            "details": interpretation_details
        },
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
    Display portfolio risk score in a user-friendly format similar to a credit score report.
    
    Parameters
    ----------
    risk_score : Dict[str, Any]
        Output from calculate_portfolio_risk_score()
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
    if score >= 90:
        print("   🟢 EXCELLENT: Portfolio structure is well-balanced")
        print("      • Continue current allocation strategy")
        print("      • Monitor for any concentration drift")
        print("      • Consider tactical adjustments for market conditions")
    elif score >= 80:
        print("   🟡 GOOD: Portfolio needs minor tweaks")
        print("      • Trim positions exceeding target allocations")
        print("      • Consider adding defensive positions if volatility spikes")
        print("      • Review factor exposures quarterly")
    elif score >= 70:
        print("   🟠 FAIR: Portfolio requires rebalancing")
        print("      • Reduce largest positions to improve diversification")
        print("      • Add hedges for concentrated exposures")
        print("      • Consider lowering systematic risk through position sizing")
    elif score >= 60:
        print("   🔴 POOR: Portfolio needs significant restructuring")
        print("      • Address high-risk components through hedging or deleveraging")
        print("      • Reduce concentrated positions exceeding risk limits")
        print("      • Consider systematic risk reduction strategies")
    else:
        print("   ⚫ VERY POOR: Portfolio needs immediate restructuring")
        print("      • Address highest-risk components immediately")
        print("      • Reduce positions exceeding acceptable loss limits")
        print("      • Consider temporary risk reduction until rebalanced")
    
    print(f"\n{'='*60}")


def _format_risk_score_output(risk_score: Dict[str, Any], limits_analysis: Dict[str, Any], suggestions: Dict[str, Any], max_loss: float) -> str:
    """
    Format the risk score analysis output as a string for API responses.
    
    This captures the same output that would be printed to the console
    and returns it as a formatted string.
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
from utils.logging import log_portfolio_operation_decorator, log_performance, log_error_handling, log_resource_usage_decorator, log_workflow_state_decorator

@log_error_handling("high")
@log_portfolio_operation_decorator("risk_score_analysis")
@log_workflow_state_decorator("risk_score_analysis")
@log_resource_usage_decorator(monitor_memory=True, monitor_cpu=True)
@log_performance(5.0)
def run_risk_score_analysis(portfolio_yaml: str = "portfolio.yaml", risk_yaml: str = "risk_limits.yaml", *, return_data: bool = False):
    """
    Run a complete risk score analysis on a portfolio.
    
    Parameters
    ----------
    portfolio_yaml : str
        Path to portfolio configuration file
    risk_yaml : str
        Path to risk limits configuration file
    """
    # LOGGING: Add risk score analysis start logging
    # LOGGING: Add workflow state logging for risk score analysis workflow here
    # LOGGING: Add resource usage monitoring for risk score calculation here
    # LOGGING: Add component score logging
    # LOGGING: Add recommendation generation logging
    # LOGGING: Add score validation logging
    if build_portfolio_view is None or calc_max_factor_betas is None or standardize_portfolio_input is None:
        print("Error: Required modules not available. Make sure you're in the risk_module directory.")
        return
    
    try:
        # Load configuration
        # LOGGING: Add configuration load timing
        with open(portfolio_yaml, "r") as f:
            config = yaml.safe_load(f)
        
        with open(risk_yaml, "r") as f:
            risk_config = yaml.safe_load(f)
        
        print(f"Analyzing portfolio from {portfolio_yaml}...")
        
        # Standardize portfolio weights first
        raw_weights = config["portfolio_input"]
        standardized = standardize_portfolio_input(raw_weights, latest_price)
        weights = standardized["weights"]
        
        # Build portfolio view with standardized weights
        summary = build_portfolio_view(
            weights=weights,
            start_date=config["start_date"],
            end_date=config["end_date"],
            expected_returns=config.get("expected_returns"),
            stock_factor_proxies=config.get("stock_factor_proxies")
        )
        
        # Calculate max betas
        from settings import PORTFOLIO_DEFAULTS
        lookback_years = PORTFOLIO_DEFAULTS.get('worst_case_lookback_years', 10)
        max_betas, max_betas_by_proxy = calc_max_factor_betas(
            portfolio_yaml=portfolio_yaml,
            risk_yaml=risk_yaml,
            lookback_years=lookback_years,
            echo=False
        )
        
        # Calculate leverage ratio
        leverage_ratio = standardized.get("leverage", 1.0)
        
        # When using raw weights (normalize_weights = False), the weights already represent 
        # the true economic exposure, so we shouldn't apply leverage adjustment to risk calculations
        from settings import PORTFOLIO_DEFAULTS
        normalize_weights = PORTFOLIO_DEFAULTS.get("normalize_weights", True)
        risk_leverage_ratio = leverage_ratio if normalize_weights else 1.0
        
        # ═══════════════════════════════════════════════════════════════════════════
        # DISRUPTION RISK SCORING (High-level 0-100 score)
        # ═══════════════════════════════════════════════════════════════════════════
        
        # Use the user's configured factor loss limit (check both possible locations)
        max_single_factor_loss = risk_config.get("factor_limits", {}).get("max_single_factor_loss", 
                                                  risk_config.get("max_single_factor_loss", -0.08))
        
        # Calculate disruption risk score
        risk_score = calculate_portfolio_risk_score(
            summary=summary,
            portfolio_limits=risk_config["portfolio_limits"],
            concentration_limits=risk_config["concentration_limits"],
            variance_limits=risk_config["variance_limits"],
            max_betas=max_betas,
            max_proxy_betas=max_betas_by_proxy,
            leverage_ratio=risk_leverage_ratio,
            max_single_factor_loss=max_single_factor_loss
        )
        
        # Calculate and display suggested risk limits
        max_loss = abs(risk_config["portfolio_limits"]["max_loss"])
        suggestions = calculate_suggested_risk_limits(summary, max_loss, risk_leverage_ratio, max_single_factor_loss, config.get("stock_factor_proxies"), config.get("start_date"), config.get("end_date"))
        
        # Perform detailed risk limits analysis
        limits_analysis = analyze_portfolio_risk_limits(
            summary=summary,
            portfolio_limits=risk_config["portfolio_limits"],
            concentration_limits=risk_config["concentration_limits"],
            variance_limits=risk_config["variance_limits"],
            max_betas=max_betas,
            max_proxy_betas=max_betas_by_proxy,
            leverage_ratio=risk_leverage_ratio
        )
        
        if return_data:
            # API/Data mode - return structured data
            from run_risk import make_json_safe
            return make_json_safe({
                "risk_score": risk_score,
                "limits_analysis": limits_analysis,
                "portfolio_analysis": summary,
                "suggested_limits": suggestions,
                "analysis_date": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
                "portfolio_file": portfolio_yaml,
                "risk_limits_file": risk_yaml,
                "formatted_report": _format_risk_score_output(risk_score, limits_analysis, suggestions, max_loss)
            })
        else:
            # CLI mode - print formatted output
            # Display comprehensive disruption risk score with explanations
            display_portfolio_risk_score(risk_score)
            
            # ═══════════════════════════════════════════════════════════════════════════
            # DETAILED RISK LIMITS ANALYSIS
            # ═══════════════════════════════════════════════════════════════════════════
            
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
                # Keep variance calculations but don't show variance-based recommendations in output
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
        
        # Return comprehensive results
        return {
            "risk_score": risk_score,
            "limits_analysis": limits_analysis,
            "portfolio_analysis": summary,
            "suggested_limits": suggestions
        }
        
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
        print(f"   Score: {risk_score['risk_score']['score']}/100")
        print(f"   Category: {risk_score['risk_score']['category']}")
    else:
        print("\n❌ Risk score analysis failed. Check your configuration files.") 
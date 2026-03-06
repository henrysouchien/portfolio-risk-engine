"""Stress testing engine for predefined and custom multi-factor scenarios."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from core.result_objects import RiskAnalysisResult


STRESS_SCENARIOS: Dict[str, Dict[str, Any]] = {
    "interest_rate_shock": {
        "name": "Interest Rate Shock",
        "description": "300bp parallel shift in yield curve",
        "severity": "High",
        "shocks": {"interest_rate": 0.03},
    },
    "credit_spread_widening": {
        "name": "Credit Spread Widening",
        "description": "200bp widening in credit spreads",
        "severity": "Medium",
        "shocks": {"interest_rate": 0.02, "market": -0.05},
    },
    "equity_vol_spike": {
        "name": "Equity Volatility Spike",
        "description": "VIX doubles - broad equity selloff",
        "severity": "High",
        "shocks": {"market": -0.15, "momentum": -0.10},
    },
    "currency_devaluation": {
        "name": "Currency Devaluation",
        "description": "25% USD weakening vs major currencies",
        "severity": "Medium",
        "shocks": {"market": -0.03},
    },
    "oil_price_shock": {
        "name": "Oil Price Shock",
        "description": "150% increase in crude oil prices",
        "severity": "Low",
        "shocks": {"market": -0.05, "value": 0.05},
    },
    "correlation_breakdown": {
        "name": "Correlation Breakdown",
        "description": "Diversification failure - all correlations spike to 1",
        "severity": "Extreme",
        "shocks": {"market": -0.25},
    },
    "market_crash": {
        "name": "Market Crash (-20%)",
        "description": "Broad equity decline of 20%",
        "severity": "Extreme",
        "shocks": {"market": -0.20},
    },
    "stagflation": {
        "name": "Stagflation",
        "description": "Rising rates + falling equities + value rotation",
        "severity": "High",
        "shocks": {
            "market": -0.10,
            "interest_rate": 0.02,
            "growth": -0.10,
            "value": 0.05,
        },
    },
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        value_float = float(value)
        if pd.isna(value_float):
            return default
        return value_float
    except (TypeError, ValueError):
        return default


def _safe_leverage(leverage: Optional[float]) -> float:
    leverage_ratio = _safe_float(leverage, default=1.0)
    return leverage_ratio if leverage_ratio > 0 else 1.0


def _get_portfolio_weights(risk_result: RiskAnalysisResult) -> Dict[str, float]:
    weights: Dict[str, float] = {}

    portfolio_weights = getattr(risk_result, "portfolio_weights", None)
    if isinstance(portfolio_weights, dict):
        for ticker, weight in portfolio_weights.items():
            weights[str(ticker)] = _safe_float(weight, default=0.0)
        return weights

    allocations = getattr(risk_result, "allocations", None)
    if isinstance(allocations, pd.DataFrame) and "Portfolio Weight" in allocations.columns:
        for ticker, weight in allocations["Portfolio Weight"].to_dict().items():
            weights[str(ticker)] = _safe_float(weight, default=0.0)

    return weights


def run_stress_test(
    risk_result: RiskAnalysisResult,
    shocks: Dict[str, float],
    scenario_name: str = "Custom",
    portfolio_value: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Run a multi-factor stress test using precomputed risk analysis outputs.

    Math:
    - Portfolio impact: sum(beta_factor * shock_factor) * leverage_ratio
    - Position impact: sum(stock_beta_factor * shock_factor)
    - Position contribution: weight * position_impact
    """
    shocks = shocks or {}
    factor_exposures = risk_result.get_factor_exposures() if hasattr(risk_result, "get_factor_exposures") else {}
    leverage_ratio = _safe_leverage(getattr(risk_result, "leverage", None))

    portfolio_impact = 0.0
    factor_contributions: List[Dict[str, Any]] = []
    for factor, shock in shocks.items():
        shock_value = _safe_float(shock, default=0.0)
        factor_beta = _safe_float(factor_exposures.get(factor), default=0.0)
        contribution = factor_beta * shock_value * leverage_ratio
        portfolio_impact += contribution
        factor_contributions.append(
            {
                "factor": factor,
                "shock": shock_value,
                "portfolio_beta": factor_beta,
                "contribution_pct": contribution * 100.0,
            }
        )

    factor_contributions.sort(key=lambda item: item["contribution_pct"])

    weights = _get_portfolio_weights(risk_result)
    position_impacts: List[Dict[str, Any]] = []
    stock_betas = getattr(risk_result, "stock_betas", None)

    if isinstance(stock_betas, pd.DataFrame) and not stock_betas.empty:
        for ticker, row in stock_betas.iterrows():
            ticker_key = str(ticker)
            position_impact = 0.0
            for factor, shock in shocks.items():
                stock_beta = _safe_float(row.get(factor), default=0.0)
                position_impact += stock_beta * _safe_float(shock, default=0.0)

            weight = _safe_float(weights.get(ticker_key), default=0.0)
            portfolio_contribution = weight * position_impact
            position_impacts.append(
                {
                    "ticker": ticker_key,
                    "weight": weight,
                    "estimated_impact_pct": position_impact * 100.0,
                    "portfolio_contribution_pct": portfolio_contribution * 100.0,
                }
            )

    position_impacts.sort(key=lambda item: item["estimated_impact_pct"])

    worst_position = None
    best_position = None
    if position_impacts:
        worst_position = {
            "ticker": position_impacts[0]["ticker"],
            "impact_pct": position_impacts[0]["estimated_impact_pct"],
        }
        best_position = {
            "ticker": position_impacts[-1]["ticker"],
            "impact_pct": position_impacts[-1]["estimated_impact_pct"],
        }

    resolved_portfolio_value = portfolio_value
    if resolved_portfolio_value is None:
        resolved_portfolio_value = getattr(risk_result, "total_value", None)
    resolved_portfolio_value = (
        _safe_float(resolved_portfolio_value, default=0.0)
        if resolved_portfolio_value is not None
        else None
    )

    dollar_impact = None
    if resolved_portfolio_value is not None:
        dollar_impact = resolved_portfolio_value * portfolio_impact

    variance_decomposition = getattr(risk_result, "variance_decomposition", {}) or {}
    return {
        "scenario_name": scenario_name,
        "estimated_portfolio_impact_pct": portfolio_impact * 100.0,
        "estimated_portfolio_impact_dollar": dollar_impact,
        "position_impacts": position_impacts,
        "factor_contributions": factor_contributions,
        "risk_context": {
            "current_volatility": _safe_float(getattr(risk_result, "volatility_annual", 0.0), default=0.0) * 100.0,
            "leverage_ratio": leverage_ratio,
            "systematic_risk_pct": _safe_float(variance_decomposition.get("factor_pct"), default=0.0) * 100.0,
            "worst_position": worst_position,
            "best_position": best_position,
        },
    }


def get_stress_scenarios() -> Dict[str, Dict[str, Any]]:
    """Return a copy of the predefined stress scenario catalog."""
    return {
        scenario_id: {
            **scenario_data,
            "shocks": dict(scenario_data.get("shocks", {})),
        }
        for scenario_id, scenario_data in STRESS_SCENARIOS.items()
    }


def run_all_stress_tests(
    risk_result: RiskAnalysisResult,
    portfolio_value: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Run all predefined stress tests and sort by worst estimated impact first."""
    results: List[Dict[str, Any]] = []
    for scenario_id, scenario_data in STRESS_SCENARIOS.items():
        result = run_stress_test(
            risk_result=risk_result,
            shocks=scenario_data.get("shocks", {}),
            scenario_name=scenario_data.get("name", scenario_id),
            portfolio_value=portfolio_value,
        )
        result["scenario"] = scenario_id
        result["severity"] = scenario_data.get("severity")
        results.append(result)

    results.sort(key=lambda item: item["estimated_portfolio_impact_pct"])
    return results

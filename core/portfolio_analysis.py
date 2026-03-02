#!/usr/bin/env python3
# coding: utf-8

"""
Core portfolio analysis business logic.

Agent orientation:
    This is the canonical pure-function risk analysis entrypoint for portfolio
    analysis. Start here when debugging risk metrics drift between CLI/API.

Called by:
    - ``run_risk.run_portfolio`` (dual-mode wrapper)
    - ``services.portfolio_service.PortfolioService.analyze_portfolio``

Primary flow:
    1) Resolve portfolio/risk config.
    2) Standardize weights/exposures.
    3) Build portfolio risk view.
    4) Evaluate risk/beta checks.
    5) Return ``RiskAnalysisResult``.
"""

import math
from typing import Dict, Any, Optional, Union
from datetime import datetime, UTC

import pandas as pd

from core.result_objects import RiskAnalysisResult
from core.data_objects import PortfolioData, RiskLimitsData
from core.config_adapters import resolve_portfolio_config, resolve_risk_config

from core.portfolio_config import (
    standardize_portfolio_input,
    latest_price,
    get_cash_positions,
)
from core.constants import DIVERSIFIED_SECURITY_TYPES
from run_portfolio_risk import (
    evaluate_portfolio_risk_limits,
    evaluate_portfolio_beta_limits,
)
from portfolio_risk import build_portfolio_view
from risk_helpers import calc_max_factor_betas
from settings import PORTFOLIO_DEFAULTS

# Add logging decorator imports
from utils.logging import (
    log_operation,
    log_timing,
    log_errors,
)


@log_errors("high")
@log_operation("portfolio_analysis")
@log_timing(3.0)
def analyze_portfolio(
    portfolio: Union[str, PortfolioData],
    risk_limits: Union[str, RiskLimitsData, Dict[str, Any], None] = "risk_limits.yaml",
    *,
    asset_classes: Optional[Dict[str, str]] = None,
    security_types: Optional[Dict[str, str]] = None,
) -> RiskAnalysisResult:
    """
    Run pure portfolio risk analysis and return ``RiskAnalysisResult``.

    Contract notes:
    - ``portfolio`` accepts YAML path or ``PortfolioData``.
    - ``risk_limits`` accepts YAML path, typed object, raw dict, or ``None``.
    - Returned object is the canonical contract for downstream API/service layers.
    
    Parameters
    ----------
    portfolio : Union[str, PortfolioData]
        Portfolio YAML filepath or a PortfolioData object.
    risk_limits : Union[str, RiskLimitsData, Dict[str, Any], None], default "risk_limits.yaml"
        Risk limits input as file path, typed object, raw dict, or None
        (None falls back to default risk limits YAML).
        
    Returns
    -------
    RiskAnalysisResult
        Complete risk analysis result object containing all portfolio metrics,
        factor exposures, risk checks, and formatted reporting capabilities.
    """
    
    # ─── 1. Load Inputs ─────────────────────────────
    config, filepath = resolve_portfolio_config(portfolio)
    risk_config = resolve_risk_config(risk_limits)

    # Get full standardized portfolio data (including exposure metrics)
    fmp_ticker_map = config.get("fmp_ticker_map")
    currency_map = config.get("currency_map")
    instrument_types = config.get("instrument_types")
    if fmp_ticker_map:
        price_fetcher = lambda t: latest_price(
            t,
            fmp_ticker_map=fmp_ticker_map,
            currency=currency_map.get(t) if currency_map else None,
            instrument_types=instrument_types,
        )
    else:
        price_fetcher = lambda t: latest_price(
            t,
            currency=currency_map.get(t) if currency_map else None,
            instrument_types=instrument_types,
        )
    standardized_keys = (
        "weights",
        "dollar_exposure",
        "total_value",
        "net_exposure",
        "gross_exposure",
        "leverage",
        "notional_leverage",
    )
    if all(k in config for k in standardized_keys) and config.get("weights") is not None:
        standardized_data = {k: config.get(k) for k in standardized_keys}
    else:
        standardized_data = standardize_portfolio_input(
            config["portfolio_input"],
            price_fetcher,
            currency_map=currency_map,
            fmp_ticker_map=fmp_ticker_map,
            instrument_types=instrument_types,
        )
    weights = standardized_data["weights"]
    
    # ─── 2. Build Portfolio View ─────────────────────────────
    summary = build_portfolio_view(
        weights,
        config["start_date"],
        config["end_date"],
        config.get("expected_returns"),
        config.get("stock_factor_proxies"),
        asset_classes=asset_classes,
        fmp_ticker_map=fmp_ticker_map,
        currency_map=currency_map,
        instrument_types=instrument_types,
        security_types=security_types,
    )
    
    # ─── 2.1. Add Exposure Metrics to Summary ─────────────────
    summary.update({
        "net_exposure": standardized_data["net_exposure"],
        "gross_exposure": standardized_data["gross_exposure"],
        "leverage": standardized_data["leverage"],
        "total_value": standardized_data["total_value"],
        "dollar_exposure": standardized_data["dollar_exposure"],
        "notional_leverage": standardized_data.get("notional_leverage", 1.0),
    })
    
    # ─── 3. Calculate Beta Limits ────────────────────────────
    lookback_years = PORTFOLIO_DEFAULTS.get('worst_case_lookback_years', 10)
    max_betas, max_betas_by_proxy, historical_analysis = calc_max_factor_betas(
        lookback_years=lookback_years,
        echo=False,  # Don't print helper tables when capturing output
        stock_factor_proxies=config.get("stock_factor_proxies"),
        fmp_ticker_map=config.get("fmp_ticker_map"),
        max_single_factor_loss=risk_config.get("max_single_factor_loss"),
    )
    
    # ─── 4. Run Risk Checks ──────────────────────────────────
    df_risk = evaluate_portfolio_risk_limits(
        summary,
        risk_config["portfolio_limits"],
        risk_config["concentration_limits"],
        risk_config["variance_limits"],
        security_types=security_types,
    )
    
    df_beta = evaluate_portfolio_beta_limits(
        portfolio_factor_betas=summary["portfolio_factor_betas"],
        max_betas=max_betas,
        proxy_betas=summary["industry_variance"].get("per_industry_group_beta"),
        max_proxy_betas=max_betas_by_proxy
    )
    
    # ─── 5. Return Result Object ────────────────────────
    return RiskAnalysisResult.from_core_analysis(
        portfolio_summary=summary,
        risk_checks=df_risk.to_dict('records'), 
        beta_checks=df_beta.reset_index().to_dict('records'),
        max_betas=max_betas,
        max_betas_by_proxy=max_betas_by_proxy,
        historical_analysis=historical_analysis,
        analysis_metadata={
            "analysis_date": datetime.now(UTC).isoformat(),
            "portfolio_file": filepath,
            "lookback_years": lookback_years,
            "weights": weights,
            "total_positions": len(weights),
            "active_positions": len([v for v in weights.values() if abs(v) > 0.001]),
            "portfolio_name": config.get("name", "Portfolio"),
            "expected_returns": config.get("expected_returns"),
            "factor_proxies": config.get("stock_factor_proxies"),
            "cash_positions": list(get_cash_positions()),
            "asset_classes": asset_classes,
            "security_types": security_types,
            "target_allocation": config.get("target_allocation"),
            "fmp_ticker_map": fmp_ticker_map,
        }
    )


def _as_finite_float(value: Any) -> Optional[float]:
    """Convert value to finite float, or return None when invalid."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def _compute_capped_capacity(limit: float, metric_at_1x: float, *, cap: float, eps: float) -> float:
    """Compute leverage capacity from a scaling limit with near-zero denominator handling."""
    if abs(metric_at_1x) <= eps:
        return cap
    raw = abs(limit) / abs(metric_at_1x)
    if not math.isfinite(raw):
        return cap
    return max(0.0, min(raw, cap))


def compute_leverage_capacity(
    analysis_result: RiskAnalysisResult,
    risk_limits: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Compute leverage headroom analytically from an existing portfolio analysis result.

    Uses scaling constraints (volatility, implied max-loss, max stock weight,
    factor/proxy betas) to estimate the maximum leverage multiplier before limit breach.
    """
    max_cap = 10.0
    eps = 1e-12
    warnings = []

    allocations = getattr(analysis_result, "allocations", None)
    if not isinstance(allocations, pd.DataFrame) or "Portfolio Weight" not in allocations.columns:
        raise ValueError("Cannot compute leverage capacity: allocations['Portfolio Weight'] is missing.")

    weights = pd.to_numeric(allocations["Portfolio Weight"], errors="coerce").dropna()
    if not weights.empty:
        weights = weights[weights.map(math.isfinite)]
    if weights.empty:
        raise ValueError("Cannot compute leverage capacity: analyzed portfolio weights are empty.")

    effective_leverage = float(weights.abs().sum())
    if not math.isfinite(effective_leverage) or effective_leverage <= eps:
        raise ValueError("Cannot compute leverage capacity: effective leverage must be finite and > 0.")

    volatility_annual = _as_finite_float(getattr(analysis_result, "volatility_annual", None))
    if volatility_annual is None:
        raise ValueError("Cannot compute leverage capacity: missing volatility_annual.")
    volatility_annual = abs(volatility_annual)
    vol_at_1x = volatility_annual / effective_leverage

    metadata = getattr(analysis_result, "analysis_metadata", None) or {}
    security_types = metadata.get("security_types") if isinstance(metadata, dict) else None
    if security_types:
        single_issuer_tickers = [
            ticker for ticker in weights.index
            if security_types.get(ticker) not in DIVERSIFIED_SECURITY_TYPES
        ]
        weight_check = weights.loc[single_issuer_tickers] if single_issuer_tickers else weights
    else:
        weight_check = weights

    max_weight = float(weight_check.abs().max()) if not weight_check.empty else 0.0
    max_weight_at_1x = max_weight / effective_leverage

    limits = risk_limits or {}
    portfolio_limits = limits.get("portfolio_limits") if isinstance(limits.get("portfolio_limits"), dict) else {}
    concentration_limits = (
        limits.get("concentration_limits") if isinstance(limits.get("concentration_limits"), dict) else {}
    )
    variance_limits = limits.get("variance_limits") if isinstance(limits.get("variance_limits"), dict) else {}

    constraints: Dict[str, Dict[str, Any]] = {}
    scaling_constraints = []

    vol_limit = _as_finite_float(portfolio_limits.get("max_volatility"))
    if vol_limit is not None and abs(vol_limit) > eps:
        max_l_from_vol = _compute_capped_capacity(vol_limit, vol_at_1x, cap=max_cap, eps=eps)
        constraints["volatility"] = {
            "current": volatility_annual,
            "at_unit_leverage": vol_at_1x,
            "limit": abs(vol_limit),
            "max_leverage": max_l_from_vol,
            "headroom": max_l_from_vol - effective_leverage,
        }
        scaling_constraints.append(("volatility", max_l_from_vol))

    max_loss_limit_raw = _as_finite_float(portfolio_limits.get("max_loss"))
    if max_loss_limit_raw is not None and abs(max_loss_limit_raw) > eps:
        loss_at_1x = vol_at_1x * 1.65
        max_l_from_loss = _compute_capped_capacity(abs(max_loss_limit_raw), loss_at_1x, cap=max_cap, eps=eps)
        current_implied_loss = -(volatility_annual * 1.65)
        constraints["max_loss"] = {
            "current_implied": current_implied_loss,
            "at_unit_leverage": -loss_at_1x,
            "limit": -abs(max_loss_limit_raw),
            "max_leverage": max_l_from_loss,
            "headroom": max_l_from_loss - effective_leverage,
            "method": "parametric_var_95",
        }
        scaling_constraints.append(("max_loss", max_l_from_loss))

    max_single_weight_limit = _as_finite_float(concentration_limits.get("max_single_stock_weight"))
    if max_single_weight_limit is not None and abs(max_single_weight_limit) > eps:
        max_l_from_weight = _compute_capped_capacity(
            max_single_weight_limit,
            max_weight_at_1x,
            cap=max_cap,
            eps=eps,
        )
        constraints["max_single_stock_weight"] = {
            "current": max_weight,
            "at_unit_leverage": max_weight_at_1x,
            "limit": abs(max_single_weight_limit),
            "max_leverage": max_l_from_weight,
            "headroom": max_l_from_weight - effective_leverage,
        }
        scaling_constraints.append(("max_single_stock_weight", max_l_from_weight))

    beta_rows = getattr(analysis_result, "beta_checks", None) or []
    beta_capacities = []
    for row in beta_rows:
        if not isinstance(row, dict):
            continue
        factor = str(row.get("factor", "unknown"))
        portfolio_beta = _as_finite_float(row.get("portfolio_beta"))
        max_allowed_beta = _as_finite_float(row.get("max_allowed_beta"))
        if portfolio_beta is None or max_allowed_beta is None:
            continue
        if max_allowed_beta < 0:
            continue
        beta_at_1x = abs(portfolio_beta) / effective_leverage
        max_l = _compute_capped_capacity(max_allowed_beta, beta_at_1x, cap=max_cap, eps=eps)
        beta_capacities.append(
            {
                "factor": factor,
                "portfolio_beta": portfolio_beta,
                "max_allowed_beta": max_allowed_beta,
                "beta_at_1x": beta_at_1x,
                "max_leverage": max_l,
            }
        )

    if beta_capacities:
        binding_beta = min(beta_capacities, key=lambda row: row["max_leverage"])
        constraints["factor_betas"] = {
            "binding_factor": binding_beta["factor"],
            "current_beta": binding_beta["portfolio_beta"],
            "at_unit_leverage": binding_beta["beta_at_1x"],
            "max_allowed_beta": binding_beta["max_allowed_beta"],
            "max_leverage": binding_beta["max_leverage"],
            "headroom": binding_beta["max_leverage"] - effective_leverage,
        }
        scaling_constraints.append(("factor_betas", binding_beta["max_leverage"]))
    else:
        warnings.append("No beta checks available; factor beta capacity constraint skipped.")

    if not scaling_constraints:
        raise ValueError("Cannot compute leverage capacity: no scaling constraints available from risk limits.")

    binding_constraint, max_leverage = min(scaling_constraints, key=lambda item: item[1])
    headroom = max_leverage - effective_leverage
    headroom_pct = headroom / effective_leverage if effective_leverage > eps else 0.0

    variance_decomposition = getattr(analysis_result, "variance_decomposition", {}) or {}
    factor_breakdown = variance_decomposition.get("factor_breakdown_pct", {})
    factor_actual = _as_finite_float(variance_decomposition.get("factor_pct"))
    market_actual = _as_finite_float(factor_breakdown.get("market")) if isinstance(factor_breakdown, dict) else None
    industry_variance = getattr(analysis_result, "industry_variance", {}) or {}
    industry_pct_map = (
        industry_variance.get("percent_of_portfolio", {})
        if isinstance(industry_variance, dict)
        else {}
    )
    industry_actual = None
    if isinstance(industry_pct_map, dict) and industry_pct_map:
        finite_industry_values = [
            abs(v) for v in (_as_finite_float(v) for v in industry_pct_map.values()) if v is not None
        ]
        if finite_industry_values:
            industry_actual = max(finite_industry_values)

    invariant_limits: Dict[str, Dict[str, Any]] = {}
    invariant_specs = (
        ("max_factor_contribution", factor_actual),
        ("max_market_contribution", market_actual),
        ("max_industry_contribution", industry_actual),
    )
    for key, actual in invariant_specs:
        limit = _as_finite_float(variance_limits.get(key))
        if limit is None or actual is None:
            continue
        passed = actual <= abs(limit)
        invariant_limits[key] = {"actual": actual, "limit": abs(limit), "pass": passed}
        if not passed:
            warnings.append(
                f"Invariant variance limit '{key}' is already failing; leverage changes may not resolve it."
            )

    return {
        "effective_leverage": effective_leverage,
        "max_leverage": max_leverage,
        "headroom": headroom,
        "headroom_pct": headroom_pct,
        "binding_constraint": binding_constraint,
        "constraints": constraints,
        "invariant_limits": invariant_limits,
        "warnings": warnings,
        "note": (
            "Variance contribution limits are approximately leverage-invariant and shown for reference. "
            "Max-loss is derived via parametric VaR (95%, 1Y). Factor beta capacity uses the tightest "
            "factor/proxy from beta_checks."
        ),
    }

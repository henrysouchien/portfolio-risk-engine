#!/usr/bin/env python3
# coding: utf-8

"""
Shared adapters for resolving portfolio and risk-limit configuration inputs.

Called by:
- Core analysis entrypoints that accept file paths or typed data objects.

Contract notes:
- Normalizes mixed caller inputs to canonical config dicts.
- Preserves ``core.portfolio_config`` output shape for downstream engines.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple, Union

import yaml

from portfolio_risk_engine.data_objects import PortfolioData, RiskLimitsData
from portfolio_risk_engine.portfolio_config import load_portfolio_config, latest_price, standardize_portfolio_input


def config_from_portfolio_data(portfolio_data: PortfolioData) -> Dict[str, Any]:
    """
    Build canonical config dict from typed ``PortfolioData`` input.

    Output shape intentionally mirrors ``load_portfolio_config`` so core
    analyzers can treat file and in-memory sources identically.
    """
    config: Dict[str, Any] = {
        "portfolio_input": portfolio_data.standardized_input or portfolio_data.portfolio_input,
        "start_date": portfolio_data.start_date,
        "end_date": portfolio_data.end_date,
        "stock_factor_proxies": portfolio_data.stock_factor_proxies,
        "fmp_ticker_map": portfolio_data.fmp_ticker_map,
        "currency_map": portfolio_data.currency_map,
        "instrument_types": portfolio_data.instrument_types,
        "expected_returns": portfolio_data.expected_returns,
        "name": portfolio_data.portfolio_name or "Portfolio",
    }

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

    parsed = standardize_portfolio_input(
        config["portfolio_input"],
        price_fetcher,
        currency_map=currency_map,
        fmp_ticker_map=fmp_ticker_map,
    )

    config.update(
        weights=parsed["weights"],
        dollar_exposure=parsed["dollar_exposure"],
        total_value=parsed["total_value"],
        net_exposure=parsed["net_exposure"],
        gross_exposure=parsed["gross_exposure"],
        leverage=parsed["leverage"],
    )
    return config


def resolve_portfolio_config(
    portfolio: Union[str, PortfolioData],
) -> Tuple[Dict[str, Any], Optional[str]]:
    """
    Resolve portfolio input to ``(config_dict, filepath_or_none)``.
    """
    if isinstance(portfolio, str):
        return load_portfolio_config(portfolio), portfolio
    return config_from_portfolio_data(portfolio), None


def normalize_risk_config(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Ensure all expected top-level keys exist with safe defaults.

    RiskLimitsData.to_dict() omits None fields and several core call sites read
    keys directly; this normalizes missing keys to avoid KeyError.
    """
    raw_config = dict(raw or {})
    reserved = {
        "portfolio_limits",
        "concentration_limits",
        "variance_limits",
        "max_single_factor_loss",
    }
    normalized = {
        "portfolio_limits": raw_config.get("portfolio_limits") or {},
        "concentration_limits": raw_config.get("concentration_limits") or {},
        "variance_limits": raw_config.get("variance_limits") or {},
        "max_single_factor_loss": raw_config.get("max_single_factor_loss"),
    }
    normalized.update({k: v for k, v in raw_config.items() if k not in reserved})
    return normalized


def resolve_risk_config(
    risk_limits: Union[str, RiskLimitsData, Dict[str, Any], None],
    *,
    default_path: str = "risk_limits.yaml",
) -> Dict[str, Any]:
    """
    Resolve risk-limits input variants to normalized config dict.
    """
    if isinstance(risk_limits, dict):
        return normalize_risk_config(risk_limits)
    if isinstance(risk_limits, RiskLimitsData):
        return normalize_risk_config(risk_limits.to_dict())
    if isinstance(risk_limits, str):
        with open(risk_limits, "r", encoding="utf-8") as f:
            return normalize_risk_config(yaml.safe_load(f))
    if risk_limits is None:
        with open(default_path, "r", encoding="utf-8") as f:
            return normalize_risk_config(yaml.safe_load(f))
    raise TypeError(f"Unsupported risk_limits type: {type(risk_limits)!r}")

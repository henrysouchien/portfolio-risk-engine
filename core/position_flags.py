"""Position-level interpretive flags for agent-oriented responses."""

from __future__ import annotations

import math
from typing import Any


def _to_float(value: Any, default: float = 0.0) -> float:
    """Convert value to finite float, otherwise return default."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(numeric):
        return default
    return numeric


def generate_position_flags(
    positions: list[dict],
    total_value: float,
    cache_info: dict,
) -> list[dict]:
    """Generate actionable flags from position data."""
    flags: list[dict] = []
    all_positions = positions or []
    portfolio_total = _to_float(total_value)

    non_cash = [
        position
        for position in all_positions
        if position.get("type") != "cash"
        and not str(position.get("ticker", "")).startswith("CUR:")
    ]

    for provider, info in (cache_info or {}).items():
        if not isinstance(info, dict):
            continue
        if info.get("error"):
            flags.append(
                {
                    "type": "provider_error",
                    "severity": "error",
                    "message": f"{provider}: {info['error']}",
                    "provider": provider,
                }
            )

    # Concentration uses absolute non-cash exposure.
    gross_non_cash = sum(abs(_to_float(position.get("value", 0))) for position in non_cash)

    if gross_non_cash > 0:
        for position in non_cash:
            ticker = str(position.get("ticker", "UNKNOWN"))
            abs_weight = abs(_to_float(position.get("value", 0))) / gross_non_cash * 100.0
            if abs_weight > 15.0:
                flags.append(
                    {
                        "type": "single_position_concentration",
                        "severity": "warning",
                        "message": f"{ticker} is {abs_weight:.1f}% of exposure",
                        "ticker": ticker,
                        "weight_pct": round(abs_weight, 1),
                    }
                )

        sorted_by_abs = sorted(
            non_cash,
            key=lambda position: abs(_to_float(position.get("value", 0))),
            reverse=True,
        )
        top5_value = sum(abs(_to_float(position.get("value", 0))) for position in sorted_by_abs[:5])
        top5_weight = top5_value / gross_non_cash * 100.0
        if top5_weight > 60.0:
            flags.append(
                {
                    "type": "top5_concentration",
                    "severity": "info",
                    "message": f"Top 5 holdings are {top5_weight:.0f}% of exposure",
                    "top5_weight_pct": round(top5_weight, 1),
                }
            )

    # Leverage: exclude positive cash, include negative cash (margin debt).
    net_exposure = 0.0
    gross_exposure = 0.0
    for position in all_positions:
        ticker = str(position.get("ticker", ""))
        position_type = str(position.get("type", ""))
        value = _to_float(position.get("value", 0))
        is_cash = position_type == "cash" or ticker.startswith("CUR:")
        if is_cash and value > 0:
            continue
        net_exposure += value
        gross_exposure += abs(value)

    leverage = gross_exposure / abs(net_exposure) if abs(net_exposure) > 1e-12 else 1.0
    if leverage > 2.0:
        flags.append(
            {
                "type": "high_leverage",
                "severity": "warning",
                "message": f"Portfolio is {leverage:.1f}x levered",
                "leverage": round(leverage, 2),
            }
        )
    elif leverage > 1.1:
        flags.append(
            {
                "type": "leveraged",
                "severity": "info",
                "message": f"Portfolio is {leverage:.2f}x levered",
                "leverage": round(leverage, 2),
            }
        )

    # Cash: split into positive cash (drag) and negative cash (margin debt)
    cash_balance = 0.0
    margin_debt = 0.0
    for position in all_positions:
        ptype = str(position.get("type", ""))
        ticker = str(position.get("ticker", ""))
        if ptype == "cash" or ticker.startswith("CUR:"):
            val = _to_float(position.get("value", 0))
            if val >= 0:
                cash_balance += val
            else:
                margin_debt += val  # negative

    # Cash drag: positive cash > 15% of portfolio
    if portfolio_total > 0:
        cash_pct = cash_balance / portfolio_total * 100.0
        if cash_pct > 15.0:
            flags.append(
                {
                    "type": "cash_drag",
                    "severity": "info",
                    "message": f"Cash is {cash_pct:.0f}% of portfolio (${cash_balance:,.0f})",
                    "cash_pct": round(cash_pct, 1),
                    "cash_value": round(cash_balance, 2),
                }
            )

    # Margin usage: negative cash (borrowed funds) > 20% of portfolio
    if portfolio_total > 0 and margin_debt < 0:
        margin_pct = abs(margin_debt) / portfolio_total * 100.0
        if margin_pct > 20.0:
            flags.append(
                {
                    "type": "margin_usage",
                    "severity": "warning",
                    "message": f"${abs(margin_debt):,.0f} margin debt ({margin_pct:.0f}% of portfolio)",
                    "margin_debt": round(margin_debt, 2),
                    "margin_pct": round(margin_pct, 1),
                }
            )

    # Stale data: age > 2x TTL for each provider.
    for provider, info in (cache_info or {}).items():
        if not isinstance(info, dict):
            continue
        age = info.get("age_hours")
        ttl = info.get("ttl_hours", 24)
        age_val = _to_float(age, default=float("nan"))
        ttl_val = _to_float(ttl, default=24.0)
        if math.isfinite(age_val) and ttl_val > 0 and age_val > ttl_val * 2:
            flags.append(
                {
                    "type": "stale_data",
                    "severity": "warning",
                    "message": f"{provider} data is {age_val:.0f}h old (TTL {ttl_val:g}h)",
                    "provider": provider,
                    "age_hours": round(age_val, 1),
                    "ttl_hours": ttl_val,
                }
            )

    non_cash_count = len(non_cash)
    if 0 < non_cash_count < 5:
        flags.append(
            {
                "type": "low_position_count",
                "severity": "info",
                "message": f"Only {non_cash_count} non-cash positions - limited diversification",
                "position_count": non_cash_count,
            }
        )

    severity_order = {"error": 0, "warning": 1, "info": 2}
    flags.sort(key=lambda flag: severity_order.get(flag.get("severity"), 9))
    return flags

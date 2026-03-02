"""Portfolio-level option Greeks interpretive flags."""

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


def generate_option_portfolio_flags(snapshot: dict) -> list[dict]:
    """
    Generate option portfolio flags from exposure snapshot.

    Expects:
    - ``snapshot["total_value"]``: portfolio value
    - ``snapshot["portfolio_greeks"]``: dict from PortfolioGreeksSummary.to_dict()
    """
    flags: list[dict] = []
    if not isinstance(snapshot, dict):
        return flags

    greeks = snapshot.get("portfolio_greeks")
    if not isinstance(greeks, dict):
        return flags

    total_value = abs(_to_float(snapshot.get("total_value", 0.0)))
    total_delta = _to_float(greeks.get("total_delta", 0.0))
    total_theta = _to_float(greeks.get("total_theta", 0.0))
    total_vega = _to_float(greeks.get("total_vega", 0.0))
    failed_count = int(_to_float(greeks.get("failed_count", 0.0), default=0.0))

    if total_theta < -50.0:
        flags.append(
            {
                "type": "theta_drain",
                "severity": "warning",
                "message": f"Portfolio theta is {total_theta:,.2f}/day (time decay drag)",
                "total_theta": round(total_theta, 2),
            }
        )

    if total_value > 0 and abs(total_delta) > total_value * 0.20:
        flags.append(
            {
                "type": "significant_net_delta",
                "severity": "info",
                "message": (
                    f"Net dollar delta {total_delta:,.0f} exceeds 20% of portfolio value "
                    f"(${total_value:,.0f})"
                ),
                "total_delta": round(total_delta, 2),
                "delta_to_portfolio_ratio": round(abs(total_delta) / total_value, 3),
            }
        )

    if total_value > 0 and abs(total_vega) > total_value * 0.05:
        flags.append(
            {
                "type": "high_vega_exposure",
                "severity": "warning",
                "message": (
                    f"Dollar vega {total_vega:,.0f} exceeds 5% of portfolio value "
                    f"(${total_value:,.0f})"
                ),
                "total_vega": round(total_vega, 2),
                "vega_to_portfolio_ratio": round(abs(total_vega) / total_value, 3),
            }
        )

    if failed_count > 0:
        flags.append(
            {
                "type": "greeks_computation_failures",
                "severity": "info",
                "message": f"Greeks could not be computed for {failed_count} option position(s)",
                "failed_count": failed_count,
            }
        )

    severity_order = {"error": 0, "warning": 1, "info": 2}
    flags.sort(key=lambda flag: severity_order.get(flag.get("severity"), 9))
    return flags

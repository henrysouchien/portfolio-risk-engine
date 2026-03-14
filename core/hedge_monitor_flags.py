"""Hedge-monitor interpretive flags for agent-oriented responses."""

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


def _extract_days_to_expiry(position: dict[str, Any]) -> int | None:
    raw = position.get("days_to_expiry")
    try:
        days = int(raw)
    except (TypeError, ValueError):
        return None
    return days


def generate_hedge_monitor_flags(snapshot: dict) -> list[dict]:
    """Generate severity-tagged flags from hedge monitoring snapshot."""
    flags: list[dict] = []

    status = snapshot.get("status", "error")
    if status != "success":
        flags.append(
            {
                "flag": "monitor_error",
                "severity": "error",
                "message": snapshot.get("verdict", "Hedge monitor evaluation failed"),
            }
        )
        return _sort_flags(flags)

    option_count = int(_to_float(snapshot.get("option_count", 0), default=0.0))
    if option_count <= 0:
        flags.append(
            {
                "flag": "no_options",
                "severity": "info",
                "message": "No option positions found in portfolio",
            }
        )
        return _sort_flags(flags)

    expiring_positions = snapshot.get("expiring_positions", [])
    if not isinstance(expiring_positions, list):
        expiring_positions = []

    critical_expiring = []
    approaching_expiring = []
    for position in expiring_positions:
        if not isinstance(position, dict):
            continue
        days = _extract_days_to_expiry(position)
        tier_severity = str(position.get("tier_severity") or "").strip().lower()
        if tier_severity == "error" or (days is not None and days <= 7):
            critical_expiring.append(position)
        elif tier_severity == "info" or (days is not None and 14 < days <= 30):
            approaching_expiring.append(position)

    if critical_expiring:
        flags.append(
            {
                "flag": "critical_expiry",
                "severity": "error",
                "message": (
                    f"{len(critical_expiring)} option position"
                    f"{'s' if len(critical_expiring) != 1 else ''} "
                    "within critical expiry window (<= 7 days)"
                ),
            }
        )

    delta_drift = snapshot.get("delta_drift", {})
    if not isinstance(delta_drift, dict):
        delta_drift = {}
    within_tolerance = delta_drift.get("within_tolerance")
    if within_tolerance is False:
        deviation = _to_float(delta_drift.get("deviation"), default=0.0)
        tolerance = _to_float(delta_drift.get("tolerance"), default=0.0)
        flags.append(
            {
                "flag": "delta_drift",
                "severity": "error",
                "message": (
                    f"Net delta drift {deviation:.3f} exceeds tolerance {tolerance:.3f}"
                ),
            }
        )

    roll_recommendations = snapshot.get("roll_recommendations", [])
    if not isinstance(roll_recommendations, list):
        roll_recommendations = []
    if roll_recommendations:
        flags.append(
            {
                "flag": "roll_needed",
                "severity": "warning",
                "message": (
                    f"{len(roll_recommendations)} option position"
                    f"{'s' if len(roll_recommendations) != 1 else ''} "
                    "within configured roll window"
                ),
            }
        )

    greeks = snapshot.get("greeks", {})
    if not isinstance(greeks, dict):
        greeks = {}

    theta_threshold = _to_float(snapshot.get("theta_drain_threshold", -50.0), default=-50.0)
    total_theta = _to_float(greeks.get("total_theta"), default=0.0)
    if total_theta < theta_threshold:
        flags.append(
            {
                "flag": "theta_drain",
                "severity": "warning",
                "message": f"Portfolio theta {total_theta:,.2f}/day is below threshold {theta_threshold:,.2f}",
            }
        )

    total_vega = _to_float(greeks.get("total_vega"), default=0.0)
    portfolio_value = _to_float(snapshot.get("portfolio_value"), default=0.0)
    vega_pct_threshold = _to_float(snapshot.get("vega_pct_threshold", 0.05), default=0.05)
    if portfolio_value > 0:
        vega_ratio = abs(total_vega) / portfolio_value
        if vega_ratio > vega_pct_threshold:
            flags.append(
                {
                    "flag": "high_vega",
                    "severity": "warning",
                    "message": (
                        f"Vega exposure {vega_ratio:.1%} exceeds threshold {vega_pct_threshold:.1%}"
                    ),
                }
            )

    if approaching_expiring:
        flags.append(
            {
                "flag": "expiry_approaching",
                "severity": "info",
                "message": (
                    f"{len(approaching_expiring)} option position"
                    f"{'s' if len(approaching_expiring) != 1 else ''} "
                    "approaching expiry (15-30 days)"
                ),
            }
        )

    failed_count = int(_to_float(greeks.get("failed_count"), default=0.0))
    if failed_count > 0:
        flags.append(
            {
                "flag": "greeks_failures",
                "severity": "info",
                "message": f"Greeks computation failed for {failed_count} option position(s)",
            }
        )

    if not flags:
        flags.append(
            {
                "flag": "hedges_ok",
                "severity": "success",
                "message": "All hedge monitoring checks are within configured thresholds",
            }
        )

    return _sort_flags(flags)


def _sort_flags(flags: list[dict]) -> list[dict]:
    order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    return sorted(flags, key=lambda flag: order.get(flag.get("severity", "info"), 2))

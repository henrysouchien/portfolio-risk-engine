"""Basket trade interpretive flags for agent-oriented responses."""

from __future__ import annotations

import math
from typing import Any


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def generate_basket_trade_preview_flags(snapshot: dict) -> list[dict]:
    """Generate flags from basket trade preview snapshot payload."""
    if not isinstance(snapshot, dict):
        return []

    flags: list[dict] = []
    total_legs = _to_int(snapshot.get("total_legs")) or 0
    failed_legs = _to_int(snapshot.get("failed_legs")) or 0
    skipped_legs = _to_int(snapshot.get("skipped_legs")) or 0
    buy_legs = _to_int(snapshot.get("buy_legs")) or 0
    sell_legs = _to_int(snapshot.get("sell_legs")) or 0
    total_cost = _to_float(snapshot.get("total_estimated_cost")) or 0.0
    action = str(snapshot.get("action") or "").lower()

    if failed_legs > 0 and total_legs > 0:
        flags.append(
            {
                "type": "preview_legs_failed",
                "severity": "error",
                "message": f"{failed_legs} of {total_legs} legs failed preview",
                "failed_legs": failed_legs,
                "total_legs": total_legs,
            }
        )

    if skipped_legs > 0:
        flags.append(
            {
                "type": "legs_skipped",
                "severity": "warning",
                "message": f"{skipped_legs} legs skipped (quantity rounded to 0)",
                "skipped_legs": skipped_legs,
            }
        )

    if total_cost > 50_000:
        flags.append(
            {
                "type": "large_basket_order",
                "severity": "warning",
                "message": f"Basket order notional is ${total_cost:,.2f} (> $50,000)",
                "total_estimated_cost": round(total_cost, 2),
            }
        )

    if total_legs > 0 and failed_legs == 0:
        flags.append(
            {
                "type": "all_legs_valid",
                "severity": "success",
                "message": f"All {total_legs} legs passed preview",
                "total_legs": total_legs,
            }
        )

    if action == "rebalance":
        flags.append(
            {
                "type": "rebalance_summary",
                "severity": "info",
                "message": f"Rebalance order staged as {sell_legs} sells then {buy_legs} buys",
                "sell_legs": sell_legs,
                "buy_legs": buy_legs,
            }
        )

    severity_order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    flags.sort(key=lambda flag: severity_order.get(flag.get("severity"), 9))
    return flags


def generate_basket_trade_execution_flags(snapshot: dict) -> list[dict]:
    """Generate flags from basket trade execution snapshot payload."""
    if not isinstance(snapshot, dict):
        return []

    flags: list[dict] = []
    status = str(snapshot.get("status") or "").lower()
    requested_legs = _to_int(snapshot.get("requested_legs")) or 0
    succeeded_legs = _to_int(snapshot.get("succeeded_legs")) or 0
    failed_legs = _to_int(snapshot.get("failed_legs")) or 0
    reprieved_legs = _to_int(snapshot.get("reprieved_legs")) or 0

    if status == "failed" or (requested_legs > 0 and failed_legs >= requested_legs):
        flags.append(
            {
                "type": "basket_execution_failed",
                "severity": "error",
                "message": "All basket execution legs failed",
                "requested_legs": requested_legs,
                "failed_legs": failed_legs,
            }
        )
    elif status in {"partial", "needs_confirmation"} or failed_legs > 0 or reprieved_legs > 0:
        flags.append(
            {
                "type": "basket_execution_partial",
                "severity": "warning",
                "message": (
                    "Basket execution partially completed "
                    f"({succeeded_legs} succeeded, {failed_legs} failed, {reprieved_legs} reprieved)"
                ),
                "requested_legs": requested_legs,
                "succeeded_legs": succeeded_legs,
                "failed_legs": failed_legs,
                "reprieved_legs": reprieved_legs,
            }
        )
    elif status == "completed":
        flags.append(
            {
                "type": "basket_execution_complete",
                "severity": "success",
                "message": f"All {requested_legs} basket legs executed",
                "requested_legs": requested_legs,
            }
        )

    severity_order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    flags.sort(key=lambda flag: severity_order.get(flag.get("severity"), 9))
    return flags


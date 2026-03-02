"""Futures-curve interpretive flags for agent-oriented responses."""

from __future__ import annotations


def _sort_flags(flags: list[dict]) -> list[dict]:
    order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    return sorted(flags, key=lambda f: order.get(f.get("severity", "info"), 2))


def generate_futures_curve_flags(snapshot: dict) -> list[dict]:
    """Generate severity-tagged flags from futures curve snapshot."""
    flags: list[dict] = []

    if snapshot.get("status") != "success":
        flags.append(
            {
                "type": "fetch_error",
                "severity": "error",
                "message": snapshot.get("error", "Failed to fetch curve data"),
            }
        )
        return _sort_flags(flags)

    curve_shape = snapshot.get("curve_shape")
    total_spread_pct = snapshot.get("total_spread_pct", 0)
    days_to_front_expiry = snapshot.get("days_to_front_expiry")
    months = snapshot.get("months", [])

    if curve_shape == "contango":
        flags.append(
            {
                "type": "contango",
                "severity": "info",
                "message": f"Curve in contango (+{total_spread_pct:.2f}% front to back)",
            }
        )
    elif curve_shape == "backwardation":
        flags.append(
            {
                "type": "backwardation",
                "severity": "info",
                "message": f"Curve in backwardation ({total_spread_pct:.2f}% front to back)",
            }
        )

    nearest_ann = snapshot.get("nearest_annualized_basis_pct")
    if nearest_ann is not None and nearest_ann > 5.0:
        flags.append(
            {
                "type": "steep_contango",
                "severity": "warning",
                "message": f"Steep contango: {nearest_ann:.1f}% annualized nearest spread",
            }
        )

    if days_to_front_expiry is not None and days_to_front_expiry <= 5:
        flags.append(
            {
                "type": "near_expiry_front",
                "severity": "info",
                "message": f"Front month expires in {days_to_front_expiry} trading days",
            }
        )

    if len(months) >= 2:
        back_months = months[1:]
        low_vol = [month for month in back_months if (month.get("volume") or 0) < 10]
        if low_vol:
            flags.append(
                {
                    "type": "low_liquidity_warning",
                    "severity": "warning",
                    "message": f"{len(low_vol)} back month(s) with very low volume",
                }
            )

    flags.append(
        {
            "type": "curve_fetched",
            "severity": "success",
            "message": f"Fetched {len(months)} active contract months",
        }
    )

    return _sort_flags(flags)

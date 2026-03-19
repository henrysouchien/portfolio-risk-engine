"""Income-focused interpretive flags for overview card insights."""

from __future__ import annotations

import math
from typing import Any


def _to_float(value: Any) -> float | None:
    """Convert to finite float; return None for missing/invalid values."""
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def generate_income_flags(snapshot: dict) -> list[dict]:
    """Generate income and yield context flags from a realized performance snapshot."""
    if not isinstance(snapshot, dict):
        return []

    income = snapshot.get("income", {})
    if not isinstance(income, dict):
        return []

    yield_on_value = _to_float(income.get("yield_on_value_pct"))
    projected_annual = _to_float(income.get("projected_annual"))
    if yield_on_value is None:
        return []

    if yield_on_value > 4 and projected_annual is not None:
        return [
            {
                "type": "high_income_yield",
                "severity": "success",
                "message": f"Strong income: {yield_on_value:.1f}% yield (${projected_annual:,.0f}/yr)",
                "yield_on_value_pct": round(yield_on_value, 2),
                "projected_annual": round(projected_annual, 2),
            }
        ]

    if 0 < yield_on_value <= 4:
        flag = {
            "type": "portfolio_income_yield",
            "severity": "success",
            "message": f"Portfolio yields {yield_on_value:.1f}% annually",
            "yield_on_value_pct": round(yield_on_value, 2),
        }
        if projected_annual is not None:
            flag["projected_annual"] = round(projected_annual, 2)
        return [flag]

    return []

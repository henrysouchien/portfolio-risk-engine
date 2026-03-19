"""Alpha-focused interpretive flags for agent-oriented responses."""

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


def generate_alpha_flags(snapshot: dict) -> list[dict]:
    """Generate severity-tagged alpha flags from a performance snapshot."""
    if not isinstance(snapshot, dict):
        return []

    benchmark = snapshot.get("benchmark", {})
    if not isinstance(benchmark, dict):
        return []
    risk = snapshot.get("risk", {})
    if not isinstance(risk, dict):
        risk = {}

    alpha_annual = _to_float(benchmark.get("alpha_annual_pct"))
    if alpha_annual is None:
        return []

    flags: list[dict] = []
    benchmark_ticker = benchmark.get("ticker", "benchmark")

    if alpha_annual < -5:
        flags.append(
            {
                "type": "deep_underperformance",
                "severity": "warning",
                "message": f"Underperforming {benchmark_ticker} by {abs(alpha_annual):.1f}% annually",
                "alpha_annual_pct": round(alpha_annual, 2),
            }
        )
    elif alpha_annual > 2:
        flags.append(
            {
                "type": "strong_alpha",
                "severity": "success",
                "message": f"Generating {alpha_annual:.1f}% annualized alpha vs {benchmark_ticker}",
                "alpha_annual_pct": round(alpha_annual, 2),
            }
        )
    elif alpha_annual > 0:
        flags.append(
            {
                "type": "moderate_alpha",
                "severity": "info",
                "message": f"Generating {alpha_annual:.1f}% annualized alpha vs {benchmark_ticker}",
                "alpha_annual_pct": round(alpha_annual, 2),
            }
        )
    else:
        flags.append(
            {
                "type": "negative_alpha",
                "severity": "info",
                "message": f"Alpha is {alpha_annual:.1f}% annually vs {benchmark_ticker}",
                "alpha_annual_pct": round(alpha_annual, 2),
            }
        )

    up_capture = _to_float(risk.get("up_capture_ratio"))
    down_capture = _to_float(risk.get("down_capture_ratio"))
    if up_capture is not None and down_capture is not None:
        if up_capture > 1.0 and down_capture < 1.0:
            flags.append(
                {
                    "type": "asymmetric_capture",
                    "severity": "success",
                    "message": f"Captures {up_capture:.2f}x of gains, only {down_capture:.2f}x of losses",
                    "up_capture_ratio": round(up_capture, 3),
                    "down_capture_ratio": round(down_capture, 3),
                }
            )
        elif up_capture < 1.0 and down_capture > 1.0:
            flags.append(
                {
                    "type": "unfavorable_capture",
                    "severity": "success",
                    "message": f"Captures only {up_capture:.2f}x of gains but {down_capture:.2f}x of losses",
                    "up_capture_ratio": round(up_capture, 3),
                    "down_capture_ratio": round(down_capture, 3),
                }
            )

    tracking_error = _to_float(risk.get("tracking_error_pct"))
    if tracking_error is not None and tracking_error > 10:
        flags.append(
            {
                "type": "high_tracking_error",
                "severity": "success",
                "message": (
                    f"High tracking error ({tracking_error:.1f}%) - portfolio diverges "
                    f"significantly from {benchmark_ticker}"
                ),
                "tracking_error_pct": round(tracking_error, 2),
            }
        )

    beta = _to_float(benchmark.get("beta"))
    if flags and beta is not None and beta > 1.3:
        flags.append(
            {
                "type": "high_beta_context",
                "severity": "success",
                "message": f"Beta is {beta:.2f}, so results come with above-market sensitivity",
                "beta": round(beta, 3),
            }
        )

    return _sort_flags(flags)


def _sort_flags(flags: list[dict]) -> list[dict]:
    """Sort by severity: error > warning > info > success."""
    order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    return sorted(flags, key=lambda flag: order.get(flag.get("severity", "info"), 2))

"""Monte Carlo interpretive flags for agent-oriented responses."""

from __future__ import annotations

import math
from typing import Any


def _to_float(value: Any) -> float | None:
    """Convert to finite float; return None when invalid."""
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def generate_monte_carlo_flags(snapshot: dict) -> list[dict]:
    """Generate actionable flags from MonteCarloResult agent snapshot."""
    if not isinstance(snapshot, dict):
        return []

    flags: list[dict] = []
    simulation = snapshot.get("simulation", {}) or {}
    terminal = snapshot.get("terminal", {}) or {}
    conditioning = snapshot.get("conditioning", {}) or {}
    warnings = list(snapshot.get("warnings") or [])

    distribution = simulation.get("distribution")
    requested_distribution = simulation.get("requested_distribution")
    fallback_reason = simulation.get("distribution_fallback_reason")
    num_simulations = _to_float(simulation.get("num_simulations"))
    months = _to_float(simulation.get("time_horizon_months"))
    bootstrap_sample_size = _to_float(simulation.get("bootstrap_sample_size"))
    distribution_params = simulation.get("distribution_params", {}) or {}
    df = _to_float(distribution_params.get("df"))

    initial_value = _to_float(snapshot.get("initial_value"))
    var_95 = _to_float(terminal.get("var_95"))
    probability_of_loss = _to_float(terminal.get("probability_of_loss"))
    vol_scale = _to_float(conditioning.get("vol_scale"))

    if distribution and requested_distribution and distribution != requested_distribution:
        flags.append(
            {
                "type": "distribution_fallback",
                "severity": "warning",
                "message": (
                    f"Requested {requested_distribution} but fell back to {distribution}: "
                    f"{fallback_reason or 'no reason provided'}"
                ),
            }
        )

    if probability_of_loss is not None and months is not None and probability_of_loss > 0.50:
        flags.append(
            {
                "type": "high_loss_probability",
                "severity": "warning",
                "message": f"Over 50% probability of loss over {int(months)} months",
                "probability_of_loss": round(probability_of_loss, 4),
            }
        )

    if initial_value and initial_value > 0 and var_95 is not None and months is not None:
        var_ratio = var_95 / initial_value
        threshold = 0.20 * math.sqrt(months / 12.0)
        if var_ratio > threshold:
            flags.append(
                {
                    "type": "extreme_var",
                    "severity": "warning",
                    "message": f"95% VaR exceeds {var_ratio * 100:.1f}% of portfolio value",
                    "var_95": round(var_95, 2),
                    "var_ratio": round(var_ratio, 4),
                    "threshold": round(threshold, 4),
                }
            )

    if distribution == "bootstrap" and bootstrap_sample_size is not None and bootstrap_sample_size < 24:
        flags.append(
            {
                "type": "small_bootstrap_sample",
                "severity": "warning",
                "message": (
                    f"Bootstrap uses only {int(bootstrap_sample_size)} months - results may be unstable"
                ),
                "bootstrap_sample_size": int(bootstrap_sample_size),
            }
        )

    if num_simulations is not None and num_simulations < 500:
        flags.append(
            {
                "type": "low_simulation_count",
                "severity": "info",
                "message": "Low simulation count; consider 1000+ for stable estimates",
                "num_simulations": int(num_simulations),
            }
        )

    if distribution == "t" and df is not None and df < 4:
        flags.append(
            {
                "type": "extreme_fat_tails",
                "severity": "info",
                "message": f"Student-t df={_format_number(df)} produces very heavy tails",
                "df": _format_number(df),
            }
        )

    if vol_scale is not None and not math.isclose(vol_scale, 1.0, rel_tol=0.0, abs_tol=1e-12):
        flags.append(
            {
                "type": "vol_regime_adjustment",
                "severity": "info",
                "message": f"Volatility scaled by {vol_scale:.2f}x (regime-conditional)",
                "vol_scale": round(vol_scale, 4),
            }
        )

    for warning_text in warnings:
        flags.append(
            {
                "type": "engine_warnings",
                "severity": "info",
                "message": str(warning_text),
            }
        )

    if probability_of_loss is not None and probability_of_loss < 0.05:
        flags.append(
            {
                "type": "low_loss_probability",
                "severity": "success",
                "message": "Less than 5% probability of loss",
                "probability_of_loss": round(probability_of_loss, 4),
            }
        )

    severity_order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    flags.sort(key=lambda flag: severity_order.get(flag.get("severity"), 9))
    return flags


def _format_number(value: float) -> int | float:
    if float(value).is_integer():
        return int(value)
    return round(float(value), 3)

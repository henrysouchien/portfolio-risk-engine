"""Option strategy interpretive flags for agent-oriented responses."""

from __future__ import annotations


def generate_option_strategy_flags(snapshot: dict) -> list[dict]:
    """Generate severity-tagged flags from option strategy snapshot."""
    flags = []

    status = snapshot.get("status", "success")
    if status != "success":
        flags.append(
            {
                "flag": "analysis_error",
                "severity": "error",
                "message": f"Analysis failed: {snapshot.get('verdict', 'unknown error')}",
            }
        )
        return _sort_flags(flags)

    max_profit = snapshot.get("max_profit", 0)
    max_loss = snapshot.get("max_loss", 0)
    rr_ratio = snapshot.get("risk_reward_ratio", 0)
    warning_count = snapshot.get("warning_count", 0)

    # Unlimited loss exposure
    if max_loss == "unlimited":
        flags.append(
            {
                "flag": "unlimited_loss",
                "severity": "warning",
                "message": "Strategy has unlimited loss exposure — consider adding a protective leg",
            }
        )

    # Risk/reward assessment
    if isinstance(max_loss, (int, float)) and isinstance(max_profit, (int, float)):
        if rr_ratio >= 3.0:
            flags.append(
                {
                    "flag": "favorable_risk_reward",
                    "severity": "success",
                    "message": f"Favorable risk/reward ratio of {rr_ratio:.2f}",
                }
            )
        elif 0 < rr_ratio < 1.0:
            flags.append(
                {
                    "flag": "unfavorable_risk_reward",
                    "severity": "warning",
                    "message": f"Risk/reward ratio {rr_ratio:.2f} — risking more than potential profit",
                }
            )
        elif rr_ratio == 0:
            # R:R is 0 when max_loss is 0 (undefined) — no risk capital
            flags.append(
                {
                    "flag": "zero_risk_capital",
                    "severity": "info",
                    "message": "No risk capital required (max loss is zero)",
                }
            )
    elif max_profit == "unlimited":
        flags.append(
            {
                "flag": "unlimited_profit_potential",
                "severity": "success",
                "message": "Strategy has unlimited profit potential",
            }
        )

    # Greeks-based flags
    greeks = snapshot.get("aggregate_greeks", {})
    delta = greeks.get("delta", 0)
    theta = greeks.get("theta", 0)
    if isinstance(delta, (int, float)):
        if abs(delta) > 0.8:
            flags.append(
                {
                    "flag": "high_directional_exposure",
                    "severity": "info",
                    "message": f"Net delta {delta:.2f} — significant directional exposure",
                }
            )
    if isinstance(theta, (int, float)):
        if theta < -5.0:
            flags.append(
                {
                    "flag": "high_theta_decay",
                    "severity": "warning",
                    "message": f"Daily theta decay ${theta:.2f} — time is working against this position",
                }
            )

    # Warnings from analysis
    if warning_count > 0:
        flags.append(
            {
                "flag": "has_warnings",
                "severity": "info",
                "message": f"{warning_count} analysis warning{'s' if warning_count != 1 else ''}",
            }
        )

    # No issues at all
    if not flags:
        flags.append(
            {
                "flag": "clean_analysis",
                "severity": "success",
                "message": "Strategy analysis complete with no concerns",
            }
        )

    return _sort_flags(flags)


def _sort_flags(flags):
    order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    return sorted(flags, key=lambda f: order.get(f.get("severity", "info"), 2))

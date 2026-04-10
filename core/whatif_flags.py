"""What-if interpretive flags for agent-oriented responses."""

from __future__ import annotations


def generate_whatif_flags(snapshot: dict) -> list[dict]:
    """
    Generate actionable flags from what-if snapshot.

    Input: dict from WhatIfResult.get_agent_snapshot()
    """
    if not snapshot:
        return []

    flags: list[dict] = []
    compliance = snapshot.get("compliance", {})
    improvements = snapshot.get("improvements", {})
    risk_deltas = snapshot.get("risk_deltas", {})
    vol = risk_deltas.get("volatility_annual_pct", {})
    conc = risk_deltas.get("herfindahl", {})

    risk_violations = compliance.get("risk_violation_count", 0)
    if risk_violations > 0:
        flags.append(
            {
                "type": "risk_violations",
                "severity": "warning",
                "message": f"Scenario portfolio has {risk_violations} risk limit violation(s)",
                "risk_violation_count": risk_violations,
            }
        )

    factor_violations = compliance.get("factor_violation_count", 0)
    if factor_violations > 0:
        flags.append(
            {
                "type": "factor_violations",
                "severity": "warning",
                "message": f"Scenario portfolio has {factor_violations} factor beta violation(s)",
                "factor_violation_count": factor_violations,
            }
        )

    proxy_violations = compliance.get("proxy_violation_count", 0)
    if proxy_violations > 0:
        flags.append(
            {
                "type": "proxy_violations",
                "severity": "warning",
                "message": f"Scenario portfolio has {proxy_violations} proxy constraint violation(s)",
                "proxy_violation_count": proxy_violations,
            }
        )

    total_violations = risk_violations + factor_violations + proxy_violations
    new_violation_count = compliance.get("new_violation_count")
    if new_violation_count is not None and new_violation_count == 0 and total_violations > 0:
        base_count = compliance.get("base_violation_count", 0)
        flags.append(
            {
                "type": "inherited_violations",
                "severity": "info",
                "message": (
                    f"All {total_violations} violation(s) are inherited from the base portfolio "
                    f"({base_count} base violations)"
                ),
            }
        )
    elif new_violation_count is not None and new_violation_count > 0:
        flags.append(
            {
                "type": "new_violations",
                "severity": "warning",
                "message": (
                    f"Scenario introduces {new_violation_count} new violation(s) "
                    "not present in the base portfolio"
                ),
                "new_violation_count": new_violation_count,
            }
        )

    resolved_count = compliance.get("resolved_violation_count", 0)
    if resolved_count > 0:
        flags.append(
            {
                "type": "resolved_violations",
                "severity": "success",
                "message": f"Scenario resolves {resolved_count} violation(s) present in the base portfolio",
                "resolved_violation_count": resolved_count,
            }
        )

    new_tickers = snapshot.get("new_tickers", [])
    if new_tickers:
        flags.append(
            {
                "type": "new_tickers_added",
                "severity": "info",
                "message": (
                    f"Scenario introduces {len(new_tickers)} ticker(s) not in current portfolio: "
                    f"{', '.join(new_tickers)}"
                ),
                "new_tickers": new_tickers,
            }
        )

    vol_delta = snapshot.get("_raw_vol_delta_pct", vol.get("delta", 0))
    if vol_delta > 2.0:
        flags.append(
            {
                "type": "volatility_increase",
                "severity": "warning",
                "message": f"Scenario increases annual volatility by {vol_delta:+.2f}pp",
                "vol_delta_pct": vol_delta,
            }
        )
    elif vol_delta < -2.0:
        flags.append(
            {
                "type": "volatility_decrease",
                "severity": "success",
                "message": f"Scenario reduces annual volatility by {abs(vol_delta):.2f}pp",
                "vol_delta_pct": vol_delta,
            }
        )

    conc_delta = snapshot.get("_raw_conc_delta", conc.get("delta", 0))
    if conc_delta > 0.02:
        flags.append(
            {
                "type": "concentration_increase",
                "severity": "info",
                "message": f"Scenario increases portfolio concentration (HHI delta: {conc_delta:+.4f})",
                "hhi_delta": conc_delta,
            }
        )

    is_marginal = snapshot.get("is_marginal", False)
    if is_marginal and total_violations == 0:
        flags.append(
            {
                "type": "marginal_impact",
                "severity": "info",
                "message": "Scenario has negligible impact on volatility and concentration",
            }
        )

    if (
        improvements.get("risk")
        and improvements.get("concentration")
        and not is_marginal
        and total_violations == 0
    ):
        flags.append(
            {
                "type": "overall_improvement",
                "severity": "success",
                "message": "Scenario improves both risk and concentration with no violations",
            }
        )

    severity_order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    flags.sort(key=lambda flag: severity_order.get(flag.get("severity"), 9))
    return flags

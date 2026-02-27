"""Optimization interpretive flags for agent-oriented responses."""

from __future__ import annotations


def generate_optimization_flags(snapshot: dict) -> list[dict]:
    """
    Generate actionable flags from optimization snapshot.

    Input: dict from OptimizationResult.get_agent_snapshot()
    """
    if not snapshot:
        return []

    flags: list[dict] = []
    positions = snapshot.get("positions", {})
    compliance = snapshot.get("compliance", {})
    changes = snapshot.get("weight_changes", [])
    trades = snapshot.get("trades_required", 0)
    metrics = snapshot.get("portfolio_metrics")
    del metrics

    # --- Compliance flags ---
    risk_violations = compliance.get("risk_violation_count", 0)
    if risk_violations > 0:
        flags.append(
            {
                "type": "risk_violations",
                "severity": "warning",
                "message": f"{risk_violations} risk limit violation(s) in optimized portfolio",
                "risk_violation_count": risk_violations,
            }
        )

    factor_violations = compliance.get("factor_violation_count", 0)
    if factor_violations > 0:
        flags.append(
            {
                "type": "factor_violations",
                "severity": "warning",
                "message": f"{factor_violations} factor beta violation(s) in optimized portfolio",
                "factor_violation_count": factor_violations,
            }
        )

    proxy_violations = compliance.get("proxy_violation_count", 0)
    if proxy_violations > 0:
        flags.append(
            {
                "type": "proxy_violations",
                "severity": "warning",
                "message": f"{proxy_violations} proxy constraint violation(s) in optimized portfolio",
                "proxy_violation_count": proxy_violations,
            }
        )

    # --- Trade complexity flags ---
    if trades > 15:
        flags.append(
            {
                "type": "many_trades",
                "severity": "info",
                "message": f"Optimization requires {trades} trades - significant rebalancing effort",
                "trades_required": trades,
            }
        )

    total_violations = (
        compliance.get("risk_violation_count", 0)
        + compliance.get("factor_violation_count", 0)
        + compliance.get("proxy_violation_count", 0)
    )
    compliance_known = (
        compliance.get("risk_passes") is not None
        or compliance.get("factor_passes") is not None
        or compliance.get("proxy_passes") is not None
    )
    if trades == 0 and total_violations == 0 and compliance_known:
        flags.append(
            {
                "type": "already_optimal",
                "severity": "success",
                "message": "Portfolio is already at or near optimal allocation",
            }
        )

    # --- Concentration flags ---
    largest = positions.get("largest_weight_pct", 0)
    if largest > 30:
        flags.append(
            {
                "type": "concentrated_position",
                "severity": "warning",
                "message": f"Largest position is {largest:.1f}% of optimized portfolio",
                "largest_weight_pct": largest,
            }
        )

    hhi = positions.get("hhi", 0)
    if hhi > 0.15:
        flags.append(
            {
                "type": "high_concentration",
                "severity": "info",
                "message": f"Portfolio concentration is high (HHI: {hhi:.3f})",
                "hhi": hhi,
            }
        )

    # --- Weight change flags ---
    if changes:
        biggest = changes[0]
        change_bps = biggest.get("change_bps", 0)
        if abs(change_bps) > 1000:
            flags.append(
                {
                    "type": "large_single_change",
                    "severity": "info",
                    "message": (
                        f"Largest change: {biggest['ticker']} moves {int(change_bps):+d} bps "
                        f"({biggest.get('original_weight', 0) * 100:.1f}% -> {biggest.get('new_weight', 0) * 100:.1f}%)"
                    ),
                    "ticker": biggest["ticker"],
                    "change_bps": change_bps,
                }
            )

    # --- Position count flags ---
    total = positions.get("total", 0)
    if 0 < total <= 3:
        flags.append(
            {
                "type": "few_positions",
                "severity": "info",
                "message": f"Optimized portfolio has only {total} positions - low diversification",
                "total_positions": total,
            }
        )

    # --- Positive signals ---
    if (
        compliance.get("risk_passes") is True
        and compliance.get("factor_passes") is True
        and compliance.get("proxy_passes") is not False
        and 0 < trades <= 5
    ):
        flags.append(
            {
                "type": "clean_rebalance",
                "severity": "success",
                "message": f"All checked constraints satisfied with only {trades} trades needed",
                "trades_required": trades,
            }
        )

    severity_order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    flags.sort(key=lambda flag: severity_order.get(flag.get("severity"), 9))
    return flags

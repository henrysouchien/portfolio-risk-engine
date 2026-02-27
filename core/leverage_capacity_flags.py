"""Leverage-capacity interpretive flags for agent-oriented responses."""

from __future__ import annotations


def generate_leverage_capacity_flags(snapshot: dict) -> list[dict]:
    """Generate severity-tagged flags from leverage capacity snapshot."""
    flags = []

    status = snapshot.get("status", "error")
    if status != "success":
        flags.append({
            "flag": "capacity_error",
            "severity": "error",
            "message": snapshot.get("verdict", "Leverage capacity analysis failed"),
        })
        return _sort_flags(flags)

    headroom = snapshot.get("headroom", 0)
    headroom_pct = snapshot.get("headroom_pct", 0)
    binding = snapshot.get("binding_constraint")
    breached = snapshot.get("breached_constraints", [])
    invariant_failures = snapshot.get("invariant_failures", [])

    if headroom < 0:
        breach_count = len(breached)
        if breach_count > 1:
            names = [b["constraint"] for b in breached]
            flags.append({
                "flag": "multiple_breaches",
                "severity": "warning",
                "message": f"Leverage exceeds capacity on {breach_count} constraints: {', '.join(names)}",
            })
        else:
            flags.append({
                "flag": "over_leveraged",
                "severity": "warning",
                "message": f"Leverage exceeds capacity by {abs(headroom_pct) * 100:.0f}% — binding constraint: {binding}",
            })
    elif headroom_pct < 0.10:
        flags.append({
            "flag": "tight_headroom",
            "severity": "info",
            "message": f"Only {headroom_pct * 100:.0f}% headroom to max leverage — near capacity",
        })

    if invariant_failures:
        names = [f["limit"] for f in invariant_failures]
        flags.append({
            "flag": "invariant_breach",
            "severity": "warning",
            "message": f"Variance contribution limit{'s' if len(names) != 1 else ''} breached: {', '.join(names)}",
        })

    warning_count = snapshot.get("warning_count", 0)
    if warning_count > 0:
        flags.append({
            "flag": "capacity_warnings",
            "severity": "info",
            "message": f"{warning_count} warning{'s' if warning_count != 1 else ''} during capacity analysis",
        })

    if headroom >= 0 and headroom_pct >= 0.10 and not invariant_failures:
        flags.append({
            "flag": "within_capacity",
            "severity": "success",
            "message": f"Leverage {snapshot.get('effective_leverage', 0):.2f}x is within capacity with {headroom_pct * 100:.0f}% headroom",
        })

    if not flags:
        flags.append({
            "flag": "capacity_assessed",
            "severity": "info",
            "message": f"Max leverage {snapshot.get('max_leverage', 0):.2f}x, current {snapshot.get('effective_leverage', 0):.2f}x",
        })

    return _sort_flags(flags)


def _sort_flags(flags):
    order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    return sorted(flags, key=lambda f: order.get(f.get("severity", "info"), 2))

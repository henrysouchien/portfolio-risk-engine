"""Exit-signal interpretive flags for agent-oriented responses."""

from __future__ import annotations


def generate_exit_signal_flags(snapshot: dict) -> list[dict]:
    """Generate severity-tagged flags from exit signal snapshot."""
    flags = []

    status = snapshot.get("status", "error")
    if status != "success":
        flags.append(
            {
                "flag": "signal_error",
                "severity": "error",
                "message": snapshot.get("verdict", "Exit signal evaluation failed"),
            }
        )
        return _sort_flags(flags)

    overall = snapshot.get("overall_assessment", "")
    trade_eligible = snapshot.get("trade_eligible", False)
    signals = snapshot.get("signals", [])

    errored_rules = [s for s in signals if s.get("status") == "error"]
    if errored_rules:
        names = [s["rule_name"] for s in errored_rules]
        flags.append(
            {
                "flag": "rule_evaluation_error",
                "severity": "warning",
                "message": f"Rule{'s' if len(names) != 1 else ''} failed to evaluate: {', '.join(names)}",
            }
        )

    if overall.startswith("STRONG EXIT"):
        flags.append(
            {
                "flag": "strong_exit",
                "severity": "warning",
                "message": "Both momentum and regime signals triggered — strong exit signal",
            }
        )
    elif overall.startswith("EXIT"):
        flags.append(
            {
                "flag": "exit_signal",
                "severity": "warning",
                "message": "Primary momentum signal triggered — exit recommended",
            }
        )
    elif overall.startswith("MONITOR"):
        flags.append(
            {
                "flag": "monitor",
                "severity": "info",
                "message": "Secondary signal triggered — monitoring, no action yet",
            }
        )
    elif overall.startswith("HOLD"):
        flags.append(
            {
                "flag": "hold",
                "severity": "success",
                "message": "No exit signals triggered — position holds",
            }
        )
    elif overall.startswith("ERROR"):
        flags.append(
            {
                "flag": "primary_rule_error",
                "severity": "error",
                "message": "Primary rule failed — cannot determine exit status",
            }
        )

    if trade_eligible and snapshot.get("sell_quantity", 0) > 0:
        qty = snapshot["sell_quantity"]
        total = snapshot.get("shares", 0)
        pct = (qty / total * 100) if total > 0 else 0
        flags.append(
            {
                "flag": "trade_recommended",
                "severity": "info",
                "message": f"Recommended: sell {qty} shares ({pct:.0f}% of position)",
            }
        )

    return _sort_flags(flags)


def _sort_flags(flags):
    order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    return sorted(flags, key=lambda f: order.get(f.get("severity", "info"), 2))

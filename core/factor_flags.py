"""Factor analysis interpretive flags for agent-oriented responses."""

from __future__ import annotations


def generate_factor_flags(snapshot: dict) -> list[dict]:
    """
    Generate actionable flags from factor analysis snapshot.

    Input: dict from any of the 3 result get_agent_snapshot() methods.
    Dispatches by analysis_type.
    """
    if not snapshot:
        return []

    analysis_type = snapshot.get("analysis_type")
    if analysis_type == "correlations":
        return _correlation_flags(snapshot)
    if analysis_type == "performance":
        return _performance_flags(snapshot)
    if analysis_type == "returns":
        return _returns_flags(snapshot)
    return []


def _correlation_flags(snapshot: dict) -> list[dict]:
    flags: list[dict] = []
    verdict = snapshot.get("verdict", "")

    if verdict.startswith("no "):
        return [{"type": "insufficient_data", "severity": "info", "message": verdict}]

    pair_count = snapshot.get("total_high_corr_count", len(snapshot.get("high_correlation_pairs", [])))

    if pair_count >= 3:
        flags.append(
            {
                "type": "many_high_correlations",
                "severity": "warning",
                "message": f"{pair_count} factor pairs with |correlation| > 0.7",
                "pair_count": pair_count,
            }
        )
    elif pair_count > 0:
        flags.append(
            {
                "type": "high_correlation_detected",
                "severity": "info",
                "message": f"{pair_count} factor pair(s) with |correlation| > 0.7",
                "pair_count": pair_count,
            }
        )

    if pair_count == 0:
        flags.append(
            {
                "type": "correlations_normal",
                "severity": "success",
                "message": "No factor pairs with |correlation| > 0.7",
            }
        )

    return _sort_flags(flags)


def _performance_flags(snapshot: dict) -> list[dict]:
    flags: list[dict] = []
    verdict = snapshot.get("verdict", "")

    if verdict.startswith("no "):
        return [{"type": "insufficient_data", "severity": "info", "message": verdict}]

    top = snapshot.get("top_factors", [])
    bottom = snapshot.get("bottom_factors", [])

    if top and top[0].get("sharpe_ratio", 0) > 1.5:
        flags.append(
            {
                "type": "exceptional_factor",
                "severity": "info",
                "message": f"Top factor {top[0]['ticker']} has Sharpe ratio {top[0]['sharpe_ratio']:.2f}",
                "ticker": top[0]["ticker"],
                "sharpe_ratio": top[0]["sharpe_ratio"],
            }
        )

    if bottom:
        worst = bottom[0]
        if worst.get("sharpe_ratio", 0) < -0.5:
            flags.append(
                {
                    "type": "poor_factor_performance",
                    "severity": "warning",
                    "message": f"Worst factor {worst['ticker']} has Sharpe ratio {worst['sharpe_ratio']:.2f}",
                    "ticker": worst["ticker"],
                    "sharpe_ratio": worst["sharpe_ratio"],
                }
            )

    if not flags:
        flags.append(
            {
                "type": "performance_normal",
                "severity": "success",
                "message": "Factor performance within normal ranges",
            }
        )

    return _sort_flags(flags)


def _returns_flags(snapshot: dict) -> list[dict]:
    flags: list[dict] = []
    verdict = snapshot.get("verdict", "")

    if verdict.startswith("no "):
        return [{"type": "insufficient_data", "severity": "info", "message": verdict}]

    top_per_window = snapshot.get("top_per_window", {})
    bottom_per_window = snapshot.get("bottom_per_window", {})
    shortest = snapshot.get("shortest_window")

    if shortest and top_per_window.get(shortest):
        top = top_per_window[shortest]
        if top and isinstance(top[0], dict):
            top_return = top[0].get("total_return", 0)
            if isinstance(top_return, (int, float)) and top_return > 0.15:
                flags.append(
                    {
                        "type": "extreme_positive_return",
                        "severity": "info",
                        "message": f"Top factor returned {top_return:.1%} in {shortest} window",
                        "window": shortest,
                        "total_return": top_return,
                    }
                )

    if shortest and bottom_per_window.get(shortest):
        bottom = bottom_per_window[shortest]
        if bottom and isinstance(bottom[-1], dict):
            bot_return = bottom[-1].get("total_return", 0)
            if isinstance(bot_return, (int, float)) and bot_return < -0.10:
                flags.append(
                    {
                        "type": "extreme_negative_return",
                        "severity": "warning",
                        "message": f"Worst factor returned {bot_return:.1%} in {shortest} window",
                        "window": shortest,
                        "total_return": bot_return,
                    }
                )

    if not flags:
        flags.append(
            {
                "type": "returns_normal",
                "severity": "success",
                "message": "Factor returns within normal ranges",
            }
        )

    return _sort_flags(flags)


def _sort_flags(flags: list[dict]) -> list[dict]:
    severity_order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    flags.sort(key=lambda f: severity_order.get(f.get("severity"), 9))
    return flags

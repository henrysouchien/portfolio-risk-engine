"""Risk score interpretive flags for agent-oriented responses."""

from __future__ import annotations


def generate_risk_score_flags(snapshot: dict) -> list[dict]:
    """Generate severity-tagged flags from a risk score snapshot."""
    if not snapshot:
        return _sort_flags(
            [
                {
                    "flag": "compliant",
                    "severity": "success",
                    "message": "Portfolio is compliant with all risk limits",
                }
            ]
        )

    flags: list[dict] = []
    score_raw = snapshot.get("overall_score", 0) if isinstance(snapshot, dict) else 0
    try:
        score = float(score_raw)
    except (TypeError, ValueError):
        score = 0.0
    is_compliant = snapshot.get("is_compliant", True) if isinstance(snapshot, dict) else True
    violation_count = snapshot.get("violation_count", 0) if isinstance(snapshot, dict) else 0
    component_scores = snapshot.get("component_scores", {}) if isinstance(snapshot, dict) else {}

    if not is_compliant:
        flags.append(
            {
                "flag": "non_compliant",
                "severity": "error" if violation_count >= 3 else "warning",
                "message": f"{violation_count} risk limit violation{'s' if violation_count != 1 else ''} detected",
            }
        )

    if score < 60:
        flags.append(
            {
                "flag": "high_risk",
                "severity": "warning",
                "message": f"Risk score {score}/100 indicates high portfolio risk requiring attention",
            }
        )
    elif score >= 90:
        flags.append(
            {
                "flag": "excellent_risk",
                "severity": "success",
                "message": f"Risk score {score}/100 - excellent risk management",
            }
        )

    for component, comp_score in component_scores.items() if isinstance(component_scores, dict) else []:
        if isinstance(comp_score, (int, float)) and comp_score < 60:
            label = component.replace("_", " ")
            flags.append(
                {
                    "flag": f"weak_{component}",
                    "severity": "warning",
                    "message": f"{label.title()} score {comp_score}/100 needs improvement",
                }
            )

    if is_compliant and not any(flag.get("flag") == "excellent_risk" for flag in flags):
        flags.append(
            {
                "flag": "compliant",
                "severity": "success",
                "message": "Portfolio is compliant with all risk limits",
            }
        )

    return _sort_flags(flags)


def _sort_flags(flags: list[dict]) -> list[dict]:
    """Sort by severity: error > warning > info > success."""
    order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    return sorted(flags, key=lambda flag: order.get(flag.get("severity", "info"), 2))

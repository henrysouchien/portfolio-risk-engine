"""
Risk flag generation — interpretive analysis layer.

Consumes RiskAnalysisResult getter methods and applies rules/thresholds
to generate actionable, severity-tagged flags. This is the "what does it mean"
layer, separate from:
  - core/result_objects.py — "what the data says" (getters)
  - inputs/risk_limits_manager.py — config persistence
  - run_portfolio_risk.py — hard limit comparisons (risk_checks, beta_checks)

Flags are structured dicts with type, severity, human-readable message,
and the underlying data values so consumers can reason about them.
"""

from typing import Any, Dict, List


def _safe_num(val: Any, default: float = 0.0) -> float:
    """Coerce value to float, returning default for None/NaN/non-numeric."""
    if val is None:
        return default
    try:
        numeric = float(val)
        return default if numeric != numeric else numeric
    except (TypeError, ValueError):
        return default


def generate_flags(result) -> List[Dict[str, Any]]:
    """
    Generate ordered risk flags from a RiskAnalysisResult.

    Severity levels (returned in this order):
    - "error": Compliance violations, hard breaches — requires attention
    - "warning": Concentration risk, outsized positions — worth discussing
    - "info": Informational observations — context for the agent

    Args:
        result: A RiskAnalysisResult (or any object implementing
                get_compliance_summary, get_top_risk_contributors, get_summary)

    Returns:
        List of structured flag dicts, ordered by severity.
    """
    flags: List[Dict[str, Any]] = []
    _sn = _safe_num

    compliance = result.get_compliance_summary()

    # --- error: hard breaches ---
    for v in compliance.get("violations", []):
        actual = _sn(v.get("actual"))
        limit = _sn(v.get("limit"))
        metric = v.get("metric", "unknown_metric")
        flags.append(
            {
                "type": "compliance_violation",
                "severity": "error",
                "message": f"VIOLATION: {metric} at {actual:.2%} exceeds limit {limit:.2%}",
                "metric": metric,
                "actual": actual,
                "limit": limit,
            }
        )
    for b in compliance.get("beta_breaches", []):
        beta = _sn(b.get("portfolio_beta"))
        max_beta = _sn(b.get("max_allowed_beta"))
        factor = b.get("factor", "unknown_factor")
        flags.append(
            {
                "type": "beta_breach",
                "severity": "error",
                "message": f"Beta breach: {factor} at {beta:.2f} vs limit {max_beta:.2f}",
                "factor": factor,
                "portfolio_beta": beta,
                "max_allowed_beta": max_beta,
            }
        )

    # --- warning: concentration risk ---
    for pos in result.get_top_risk_contributors(10):
        weight_pct = _sn(pos.get("weight_pct"))
        risk_pct = _sn(pos.get("risk_pct"))
        if weight_pct > 2.0 and risk_pct > 3 * weight_pct:
            ticker = pos.get("ticker", "UNKNOWN")
            flags.append(
                {
                    "type": "risk_weight_mismatch",
                    "severity": "warning",
                    "message": f"{ticker} contributes {risk_pct:.1f}% of risk at only {weight_pct:.1f}% weight",
                    "ticker": ticker,
                    "risk_pct": risk_pct,
                    "weight_pct": weight_pct,
                }
            )

    summary = result.get_summary()
    hhi = _sn(summary.get("herfindahl"))
    if hhi > 0.25:
        flags.append(
            {
                "type": "hhi_concentrated",
                "severity": "warning",
                "message": f"Portfolio is concentrated (HHI: {hhi:.3f})",
                "herfindahl": hhi,
            }
        )

    # --- info: contextual observations ---
    top5 = result.get_top_risk_contributors(5)
    top5_total = sum(_sn(p.get("risk_pct")) for p in top5)
    if top5_total > 70:
        flags.append(
            {
                "type": "top5_dominance",
                "severity": "info",
                "message": f"Top 5 positions account for {top5_total:.0f}% of portfolio risk",
                "top5_risk_pct": round(top5_total, 1),
            }
        )

    return flags

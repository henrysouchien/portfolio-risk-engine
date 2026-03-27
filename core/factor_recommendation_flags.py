"""Interpretive flags for factor recommendation agent snapshots."""

from __future__ import annotations


def generate_factor_recommendation_flags(snapshot: dict) -> list[dict]:
    """Generate severity-tagged flags from factor recommendation snapshot."""
    flags = []
    mode = snapshot.get("mode", "single")
    rec_count = snapshot.get("recommendation_count", 0)
    top_recs = snapshot.get("top_recommendations", [])
    best_corr = None
    for rec in top_recs:
        corr = rec.get("correlation")
        try:
            best_corr = float(corr)
        except (TypeError, ValueError):
            continue
        break

    if mode == "portfolio":
        driver_count = snapshot.get("driver_count", 0)
        counts = snapshot.get("recommendation_counts_by_type", {}) or {}
        direct_offsets = counts.get("direct_offset", 0)
        beta_alternatives = counts.get("beta_alternative", counts.get("beta_alternatives", 0))
        diagnosis_summary = snapshot.get("diagnosis_summary", {}) or {}
        top_variance_drivers = diagnosis_summary.get("top_variance_drivers", []) or []
        top_variance_share = 0.0
        if top_variance_drivers:
            try:
                top_variance_share = float(top_variance_drivers[0].get("variance_share") or 0.0)
            except (TypeError, ValueError):
                top_variance_share = 0.0

        if driver_count == 0:
            flags.append({
                "flag": "no_risk_drivers",
                "severity": "info",
                "message": "No significant risk drivers detected in portfolio",
            })
            return _sort_flags(flags)

        if rec_count == 0:
            flags.append({
                "flag": "drivers_without_hedges",
                "severity": "warning",
                "message": f"{driver_count} risk driver{'s' if driver_count != 1 else ''} detected but no suitable hedges found",
            })

        if direct_offsets > 0:
            flags.append({
                "flag": "direct_offset_available",
                "severity": "info",
                "message": f"{direct_offsets} direct offset hedge{'s' if direct_offsets != 1 else ''} available",
            })

        if beta_alternatives == 0:
            flags.append({
                "flag": "no_low_beta_alternatives",
                "severity": "warning",
                "message": "No low-beta alternatives found for the detected risk drivers",
            })

        if top_variance_share > 0.4:
            flags.append({
                "flag": "high_factor_concentration",
                "severity": "warning",
                "message": f"Top risk driver contributes {top_variance_share:.0%} of portfolio risk",
            })

        if driver_count >= 3:
            flags.append({
                "flag": "multiple_risk_drivers",
                "severity": "warning",
                "message": f"{driver_count} risk drivers detected — portfolio may need broader rebalancing",
            })
    else:
        if rec_count == 0:
            flags.append({
                "flag": "no_hedges_available",
                "severity": "info",
                "message": "No suitable hedge candidates found for the given criteria",
            })
            return _sort_flags(flags)

    # Check if top recommendation has strong negative correlation
    if best_corr is not None:
        if best_corr < -0.5:
            flags.append({
                "flag": "strong_hedge_available",
                "severity": "success",
                "message": f"Strong hedge candidate with {best_corr:.2f} correlation",
            })
        elif best_corr > -0.1:
            flags.append({
                "flag": "weak_hedges_only",
                "severity": "warning",
                "message": f"Best hedge has weak correlation ({best_corr:.2f}); limited hedging benefit",
            })
        else:
            # Moderate hedge: between -0.5 and -0.1
            flags.append({
                "flag": "hedges_available",
                "severity": "info",
                "message": f"Hedge candidates available (best correlation: {best_corr:.2f})",
            })

    # Good set of options
    if rec_count >= 5:
        flags.append({
            "flag": "diverse_hedges",
            "severity": "info",
            "message": f"{rec_count} hedge candidates available across categories",
        })

    return _sort_flags(flags)


def _sort_flags(flags):
    order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    return sorted(flags, key=lambda f: order.get(f.get("severity", "info"), 2))

"""Interpretive flags for factor recommendation agent snapshots."""

from __future__ import annotations


def generate_factor_recommendation_flags(snapshot: dict) -> list[dict]:
    """Generate severity-tagged flags from factor recommendation snapshot."""
    flags = []
    mode = snapshot.get("mode", "single")
    rec_count = snapshot.get("recommendation_count", 0)
    top_recs = snapshot.get("top_recommendations", [])

    # No recommendations available — branch by mode for distinct messaging
    if rec_count == 0:
        if mode == "portfolio":
            driver_count = snapshot.get("driver_count", 0)
            if driver_count == 0:
                flags.append({
                    "flag": "no_risk_drivers",
                    "severity": "info",
                    "message": "No significant risk drivers detected in portfolio",
                })
            else:
                flags.append({
                    "flag": "drivers_without_hedges",
                    "severity": "warning",
                    "message": f"{driver_count} risk driver{'s' if driver_count != 1 else ''} detected but no suitable hedges found",
                })
        else:
            flags.append({
                "flag": "no_hedges_available",
                "severity": "info",
                "message": "No suitable hedge candidates found for the given criteria",
            })
        return _sort_flags(flags)

    # Check if top recommendation has strong negative correlation
    if top_recs:
        best_corr = top_recs[0].get("correlation", 0)
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

    # Portfolio mode: multiple drivers
    if mode == "portfolio":
        driver_count = snapshot.get("driver_count", 0)
        if driver_count >= 3:
            flags.append({
                "flag": "multiple_risk_drivers",
                "severity": "warning",
                "message": f"{driver_count} risk drivers detected — portfolio may need broader rebalancing",
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

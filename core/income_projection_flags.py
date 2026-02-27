"""Income projection interpretive flags for agent-oriented responses."""

from __future__ import annotations


def generate_income_projection_flags(snapshot: dict) -> list[dict]:
    """Generate severity-tagged flags from income projection snapshot."""
    flags = []

    status = snapshot.get("status", "error")
    if status != "success":
        flags.append({
            "flag": "projection_error",
            "severity": "error",
            "message": snapshot.get("verdict", "Income projection failed"),
        })
        return _sort_flags(flags)

    annual_income = snapshot.get("annual_income", 0)
    # yield is in percentage points (e.g. 3.31 = 3.31%)
    yield_on_value = snapshot.get("portfolio_yield_on_value", 0)
    holding_count = snapshot.get("holding_count", 0)
    income_count = snapshot.get("income_holding_count", 0)
    warning_count = snapshot.get("warning_count", 0)

    # Negative income (short positions or adjustments)
    if annual_income < 0:
        flags.append({
            "flag": "negative_income",
            "severity": "warning",
            "message": f"Negative projected income ${annual_income:,.0f}/yr — review short positions",
        })
        return _sort_flags(flags)

    # No income
    if annual_income == 0:
        flags.append({
            "flag": "no_income",
            "severity": "info",
            "message": "Portfolio has no projected dividend income",
        })
        return _sort_flags(flags)

    # Yield assessment (thresholds in percentage points)
    if yield_on_value >= 4.0:
        flags.append({
            "flag": "high_yield",
            "severity": "info",
            "message": f"Portfolio yield {yield_on_value:.1f}% is above average — verify dividend sustainability",
        })
    elif yield_on_value < 1.0 and annual_income > 0:
        flags.append({
            "flag": "low_yield",
            "severity": "info",
            "message": f"Portfolio yield {yield_on_value:.1f}% — income is a minor component",
        })

    # Coverage: how many positions pay dividends
    if holding_count > 0:
        income_ratio = income_count / holding_count
        if income_ratio < 0.25:
            flags.append({
                "flag": "low_income_coverage",
                "severity": "info",
                "message": f"Only {income_count} of {holding_count} positions ({income_ratio:.0%}) pay dividends",
            })
        elif income_ratio >= 0.75:
            flags.append({
                "flag": "broad_income_coverage",
                "severity": "success",
                "message": f"{income_count} of {holding_count} positions ({income_ratio:.0%}) generate income",
            })

    # Variable/uncertain dividends
    if warning_count > 0:
        flags.append({
            "flag": "dividend_warnings",
            "severity": "warning",
            "message": f"{warning_count} position{'s' if warning_count != 1 else ''} with variable or recently initiated dividends",
        })

    # Clean if no flags yet
    if not flags:
        flags.append({
            "flag": "healthy_income",
            "severity": "success",
            "message": f"${annual_income:,.0f}/yr projected income across {income_count} positions",
        })

    return _sort_flags(flags)


def _sort_flags(flags):
    order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    return sorted(flags, key=lambda f: order.get(f.get("severity", "info"), 2))

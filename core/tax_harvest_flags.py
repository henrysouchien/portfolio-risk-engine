"""Tax-harvest interpretive flags for agent-oriented responses."""

from __future__ import annotations


def generate_tax_harvest_flags(snapshot: dict) -> list[dict]:
    """Generate severity-tagged flags from tax harvest snapshot."""
    flags = []

    status = snapshot.get("status", "error")
    if status != "success":
        flags.append({
            "flag": "harvest_error",
            "severity": "error",
            "message": snapshot.get("verdict", "Tax harvest analysis failed"),
        })
        return _sort_flags(flags)

    candidate_count = snapshot.get("candidate_count", 0)
    total_loss = snapshot.get("total_harvestable_loss", 0)
    st_loss = snapshot.get("short_term_loss", 0)
    coverage = snapshot.get("data_coverage_pct", 0)
    wash_count = snapshot.get("wash_sale_ticker_count", 0)
    positions_analyzed = snapshot.get("positions_analyzed", 0)
    positions_with_lots = snapshot.get("positions_with_lots", 0)

    # No candidates
    if candidate_count == 0:
        flags.append({
            "flag": "no_candidates",
            "severity": "success",
            "message": "No unrealized losses to harvest — all lots are at a gain or break-even",
        })
        return _sort_flags(flags)

    # Significant harvesting opportunity (> $3,000 = annual deduction limit)
    abs_loss = abs(total_loss)
    if abs_loss >= 3000:
        flags.append({
            "flag": "significant_harvest",
            "severity": "info",
            "message": f"${abs_loss:,.0f} harvestable losses exceed $3,000 annual deduction limit",
        })

    # Short-term losses are more valuable (taxed at ordinary income rates)
    abs_st = abs(st_loss)
    if abs_st > 0 and abs_loss > 0:
        st_pct = abs_st / abs_loss * 100
        if st_pct >= 50:
            flags.append({
                "flag": "mostly_short_term",
                "severity": "info",
                "message": f"{st_pct:.0f}% of losses are short-term (higher tax offset value)",
            })

    # Wash sale risk
    if wash_count > 0:
        tickers = snapshot.get("wash_sale_tickers", [])
        ticker_str = ", ".join(tickers[:3])
        suffix = f" + {wash_count - 3} more" if wash_count > 3 else ""
        flags.append({
            "flag": "wash_sale_risk",
            "severity": "warning",
            "message": f"Wash sale risk on {wash_count} ticker{'s' if wash_count != 1 else ''}: {ticker_str}{suffix}",
        })

    # Low data coverage
    if coverage < 50:
        flags.append({
            "flag": "low_coverage",
            "severity": "warning",
            "message": f"Only {coverage:.0f}% of positions have FIFO lot data — losses may be understated",
        })
    elif coverage < 75:
        flags.append({
            "flag": "moderate_coverage",
            "severity": "info",
            "message": f"{coverage:.0f}% lot coverage — {positions_analyzed - positions_with_lots} positions missing transaction history",
        })

    # Clean if no flags yet
    if not flags:
        flags.append({
            "flag": "harvest_available",
            "severity": "info",
            "message": f"${abs_loss:,.0f} in harvestable losses across {candidate_count} lots",
        })

    return _sort_flags(flags)


def _sort_flags(flags):
    order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    return sorted(flags, key=lambda f: order.get(f.get("severity", "info"), 2))

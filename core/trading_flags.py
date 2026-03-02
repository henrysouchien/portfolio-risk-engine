"""Trading-level interpretive flags for agent-oriented responses."""

from __future__ import annotations


def generate_trading_flags(snapshot: dict) -> list[dict]:
    """
    Generate actionable flags from trading analysis snapshot.

    Input: dict from FullAnalysisResult.get_agent_snapshot()
    Each flag: {type, severity, message, ...contextual_data}
    """
    flags: list[dict] = []
    trades = snapshot.get("trades", {}) if isinstance(snapshot, dict) else {}
    grades = snapshot.get("grades", {}) if isinstance(snapshot, dict) else {}
    performance = snapshot.get("performance", {}) if isinstance(snapshot, dict) else {}
    timing = snapshot.get("timing", {}) if isinstance(snapshot, dict) else {}
    conviction = snapshot.get("conviction", {}) if isinstance(snapshot, dict) else {}
    behavioral = snapshot.get("behavioral", {}) if isinstance(snapshot, dict) else {}

    # --- Performance flags ---
    win_rate = trades.get("win_rate_pct")
    total = trades.get("total", 0)
    if win_rate is not None and total >= 5 and win_rate < 40:
        flags.append(
            {
                "type": "low_win_rate",
                "severity": "warning",
                "message": f"Win rate is {win_rate:.0f}% across {total} trades",
                "win_rate_pct": win_rate,
            }
        )

    expectancy = performance.get("expectancy")
    if expectancy is not None and total >= 5 and expectancy < 0:
        flags.append(
            {
                "type": "negative_expectancy",
                "severity": "warning",
                "message": f"Negative expectancy: losing {abs(expectancy):.0f} per trade on average",
                "expectancy": expectancy,
            }
        )

    profit_factor = performance.get("profit_factor")
    if profit_factor is not None and total >= 5 and profit_factor < 1.0:
        flags.append(
            {
                "type": "low_profit_factor",
                "severity": "warning",
                "message": f"Profit factor is {profit_factor:.2f} (losses exceed wins in dollar terms)",
                "profit_factor": profit_factor,
            }
        )

    # --- Timing flags ---
    avg_timing = timing.get("avg_timing_score_pct")
    if avg_timing is not None and total >= 5 and avg_timing < 40:
        flags.append(
            {
                "type": "poor_timing",
                "severity": "warning",
                "message": f"Exit timing score is {avg_timing:.0f}% (capturing less than half of available gains)",
                "avg_timing_score_pct": avg_timing,
            }
        )

    total_regret = timing.get("total_regret")
    if total_regret is not None and total_regret > 1000:
        flags.append(
            {
                "type": "high_regret",
                "severity": "info",
                "message": f"{total_regret:,.0f} left on table vs optimal exit timing",
                "total_regret": total_regret,
            }
        )

    # --- Behavioral flags ---
    revenge_count = behavioral.get("revenge_trade_count", 0)
    if revenge_count > 0:
        flags.append(
            {
                "type": "revenge_trading",
                "severity": "warning",
                "message": f"{revenge_count} potential revenge trade(s) detected (rapid re-entry after loss)",
                "revenge_trade_count": revenge_count,
            }
        )

    avg_down_completed = behavioral.get("averaging_down_completed_count", 0)
    avg_down_rate = behavioral.get("averaging_down_success_rate_pct")
    if avg_down_completed >= 3 and avg_down_rate is not None and avg_down_rate < 50:
        flags.append(
            {
                "type": "poor_averaging_down",
                "severity": "warning",
                "message": (
                    f"Averaging down succeeded only {avg_down_rate:.0f}% of the time "
                    f"({avg_down_completed} resolved instances)"
                ),
                "averaging_down_success_rate_pct": avg_down_rate,
            }
        )

    cv = behavioral.get("position_size_cv")
    if cv is not None and cv > 80:
        flags.append(
            {
                "type": "erratic_position_sizing",
                "severity": "info",
                "message": (
                    f"Position sizing is inconsistent (CV: {cv:.0f}%) "
                    "— may indicate lack of a sizing framework"
                ),
                "position_size_cv": cv,
            }
        )

    # --- Conviction flags ---
    conviction_aligned = conviction.get("conviction_aligned", True)
    high_cr = conviction.get("high_conviction_win_rate_pct")
    low_cr = conviction.get("low_conviction_win_rate_pct")
    if not conviction_aligned and high_cr is not None and low_cr is not None and total >= 10:
        flags.append(
            {
                "type": "conviction_misaligned",
                "severity": "info",
                "message": (
                    f"Larger positions win {high_cr:.0f}% vs {low_cr:.0f}% for smaller ones "
                    "— bigger bets aren't performing better"
                ),
                "high_conviction_win_rate_pct": high_cr,
                "low_conviction_win_rate_pct": low_cr,
            }
        )

    # --- Grade flags ---
    overall = grades.get("overall", "")
    if overall and overall in ("D", "F"):
        flags.append(
            {
                "type": "poor_overall_grade",
                "severity": "warning",
                "message": f"Overall trading grade is {overall} — significant room for improvement",
                "overall_grade": overall,
            }
        )

    # --- Futures flags ---
    futures_breakdown = snapshot.get("futures_breakdown") if isinstance(snapshot, dict) else None
    if isinstance(futures_breakdown, dict):
        futures_pnl = futures_breakdown.get("futures_pnl_usd", 0)
        futures_count = futures_breakdown.get("futures_trade_count", 0)

        if futures_pnl < -5000 and futures_count >= 3:
            flags.append(
                {
                    "type": "futures_trading_losses",
                    "severity": "warning",
                    "message": f"Futures trading lost ${abs(futures_pnl):,.0f} across {futures_count} trades",
                    "futures_pnl_usd": futures_pnl,
                    "futures_trade_count": futures_count,
                }
            )

        equity_pnl = futures_breakdown.get("equity_pnl_usd", 0)
        total_abs_pnl = abs(futures_pnl) + abs(equity_pnl)
        if total_abs_pnl > 0 and abs(futures_pnl) / total_abs_pnl > 0.6:
            futures_pnl_pct = abs(futures_pnl) / total_abs_pnl * 100
            flags.append(
                {
                    "type": "futures_pnl_dominant",
                    "severity": "info",
                    "message": f"Futures account for {futures_pnl_pct:.0f}% of total trading P&L",
                    "futures_pnl_pct": round(futures_pnl_pct, 1),
                }
            )

    # --- Positive signals ---
    if overall and overall == "A":
        flags.append(
            {
                "type": "strong_trading",
                "severity": "success",
                "message": f"Overall trading grade is {overall} — disciplined and effective",
                "overall_grade": overall,
            }
        )

    if profit_factor is not None and profit_factor >= 2.0:
        flags.append(
            {
                "type": "strong_profit_factor",
                "severity": "success",
                "message": f"Profit factor is {profit_factor:.2f} — wins significantly outweigh losses",
                "profit_factor": profit_factor,
            }
        )

    severity_order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    flags.sort(key=lambda flag: severity_order.get(flag.get("severity"), 9))
    return flags

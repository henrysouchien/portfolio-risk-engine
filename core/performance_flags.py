"""Performance-level interpretive flags for agent-oriented responses."""

from __future__ import annotations

import math
from typing import Any


def _to_float(value: Any) -> float | None:
    """Convert to finite float; return None for missing/invalid values."""
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def generate_performance_flags(snapshot: dict) -> list[dict]:
    """Generate actionable flags from a performance snapshot payload."""
    flags: list[dict] = []
    returns = snapshot.get("returns", {}) if isinstance(snapshot, dict) else {}
    risk = snapshot.get("risk", {}) if isinstance(snapshot, dict) else {}
    benchmark = snapshot.get("benchmark", {}) if isinstance(snapshot, dict) else {}
    data_quality = snapshot.get("data_quality", {}) if isinstance(snapshot, dict) else {}
    mode = snapshot.get("mode", "hypothetical") if isinstance(snapshot, dict) else "hypothetical"

    total_return = _to_float(returns.get("total_return_pct"))
    win_rate = _to_float(returns.get("win_rate_pct"))
    best_month = _to_float(returns.get("best_month_pct"))
    worst_month = _to_float(returns.get("worst_month_pct"))
    best_month_date = returns.get("best_month_date")
    worst_month_date = returns.get("worst_month_date")
    alpha_annual = _to_float(benchmark.get("alpha_annual_pct"))
    sharpe_ratio = _to_float(risk.get("sharpe_ratio"))
    sortino_ratio = _to_float(risk.get("sortino_ratio"))
    max_drawdown = _to_float(risk.get("max_drawdown_pct"))
    volatility = _to_float(risk.get("volatility_pct"))
    excess_return = _to_float(benchmark.get("excess_return_pct"))
    benchmark_sharpe = _to_float(benchmark.get("sharpe_ratio"))
    period_years = _to_float((snapshot.get("period", {}) or {}).get("years")) if isinstance(snapshot, dict) else None
    if period_years is None:
        period_years = 0.0

    if total_return is not None and total_return < 0:
        flags.append(
            {
                "type": "negative_total_return",
                "severity": "warning",
                "message": f"Portfolio is down {abs(total_return):.1f}% total",
                "total_return_pct": round(total_return, 2),
            }
        )
    elif total_return is not None and total_return > 0:
        flags.append(
            {
                "type": "positive_total_return",
                "severity": "success",
                "message": f"Portfolio is up {total_return:.1f}% total",
                "total_return_pct": round(total_return, 2),
            }
        )

    if alpha_annual is not None and alpha_annual < -5:
        flags.append(
            {
                "type": "benchmark_underperformance",
                "severity": "warning",
                "message": f"Underperforming {benchmark.get('ticker', 'benchmark')} by {abs(alpha_annual):.1f}% annually",
                "alpha_annual_pct": round(alpha_annual, 2),
            }
        )

    if sharpe_ratio is not None and period_years >= 1 and sharpe_ratio < 0.3:
        flags.append(
            {
                "type": "low_sharpe",
                "severity": "warning" if sharpe_ratio < 0 else "info",
                "message": f"Sharpe ratio is {sharpe_ratio:.2f} (poor risk-adjusted returns)",
                "sharpe_ratio": round(sharpe_ratio, 3),
            }
        )

    if max_drawdown is not None and max_drawdown < -20:
        flags.append(
            {
                "type": "deep_drawdown",
                "severity": "warning",
                "message": f"Max drawdown of {abs(max_drawdown):.1f}% experienced",
                "max_drawdown_pct": round(max_drawdown, 2),
            }
        )

    if volatility is not None and volatility > 25:
        flags.append(
            {
                "type": "high_volatility",
                "severity": "info",
                "message": f"Portfolio volatility is {volatility:.1f}% (above average)",
                "volatility_pct": round(volatility, 2),
            }
        )

    if period_years >= 1 and win_rate is not None:
        if win_rate > 65:
            flags.append(
                {
                    "type": "high_win_rate",
                    "severity": "success",
                    "message": f"Positive {win_rate:.0f}% of months over the past year",
                    "win_rate_pct": round(win_rate, 1),
                }
            )
        elif win_rate < 40:
            flags.append(
                {
                    "type": "low_win_rate",
                    "severity": "success",
                    "message": f"Only {win_rate:.0f}% of months were positive",
                    "win_rate_pct": round(win_rate, 1),
                }
            )

    if best_month is not None and best_month > 5:
        message = f"Best month: +{best_month:.1f}%"
        if best_month_date:
            message = f"{message} ({best_month_date})"
        flags.append(
            {
                "type": "strong_best_month",
                "severity": "success",
                "message": message,
                "best_month_pct": round(best_month, 2),
                "best_month_date": best_month_date,
            }
        )

    if worst_month is not None and worst_month < -8:
        message = f"Worst month: {worst_month:.1f}%"
        if worst_month_date:
            message = f"{message} ({worst_month_date})"
        flags.append(
            {
                "type": "harsh_worst_month",
                "severity": "warning",
                "message": message,
                "worst_month_pct": round(worst_month, 2),
                "worst_month_date": worst_month_date,
            }
        )

    if period_years >= 1 and sharpe_ratio is not None:
        if sharpe_ratio >= 1.5:
            flags.append(
                {
                    "type": "excellent_sharpe",
                    "severity": "success",
                    "message": f"Excellent risk-adjusted returns (Sharpe {sharpe_ratio:.2f})",
                    "sharpe_ratio": round(sharpe_ratio, 3),
                }
            )
        elif sharpe_ratio >= 1.0:
            flags.append(
                {
                    "type": "good_sharpe",
                    "severity": "success",
                    "message": f"Strong risk-adjusted returns (Sharpe {sharpe_ratio:.2f})",
                    "sharpe_ratio": round(sharpe_ratio, 3),
                }
            )

    if sharpe_ratio is not None and benchmark_sharpe is not None:
        if sharpe_ratio - benchmark_sharpe > 0.2:
            flags.append(
                {
                    "type": "sharpe_above_benchmark",
                    "severity": "success",
                    "message": (
                        f"Sharpe {sharpe_ratio:.2f} vs benchmark {benchmark_sharpe:.2f} "
                        f"- earning a premium for risk taken"
                    ),
                    "sharpe_ratio": round(sharpe_ratio, 3),
                    "benchmark_sharpe_ratio": round(benchmark_sharpe, 3),
                }
            )
        elif benchmark_sharpe - sharpe_ratio > 0.2:
            flags.append(
                {
                    "type": "sharpe_below_benchmark",
                    "severity": "success",
                    "message": f"Sharpe {sharpe_ratio:.2f} vs benchmark {benchmark_sharpe:.2f}",
                    "sharpe_ratio": round(sharpe_ratio, 3),
                    "benchmark_sharpe_ratio": round(benchmark_sharpe, 3),
                }
            )

    if period_years >= 1 and sortino_ratio is not None and sortino_ratio > 1.5:
        flags.append(
            {
                "type": "good_sortino",
                "severity": "success",
                "message": f"Sortino {sortino_ratio:.2f} - downside risk well managed",
                "sortino_ratio": round(sortino_ratio, 3),
            }
        )

    if mode == "realized":
        reliable = data_quality.get("reliable")
        if reliable is False:
            flags.append(
                {
                    "type": "realized_reliability_warning",
                    "severity": "warning",
                    "message": "Realized metrics are marked low reliability; use caution for decisioning.",
                    "reason_codes": list(data_quality.get("reliability_reason_codes") or []),
                    "reasons": list(data_quality.get("reliability_reasons") or []),
                }
            )

        coverage = _to_float(data_quality.get("coverage_pct"))
        if coverage is not None and coverage < 80:
            flags.append(
                {
                    "type": "low_data_coverage",
                    "severity": "warning",
                    "message": f"Transaction data covers only {coverage:.0f}% of portfolio",
                    "coverage_pct": round(coverage, 1),
                }
            )

        warning_count_raw = data_quality.get("warning_count", 0)
        warning_count = int(warning_count_raw) if isinstance(warning_count_raw, (int, float)) else 0
        if warning_count > 3:
            flags.append(
                {
                    "type": "data_quality_issues",
                    "severity": "info",
                    "message": f"{warning_count} data quality warnings detected",
                    "warning_count": warning_count,
                }
            )

        synthetic_count_raw = data_quality.get("synthetic_count", 0)
        synthetic_count = int(synthetic_count_raw) if isinstance(synthetic_count_raw, (int, float)) else 0
        if synthetic_count > 0:
            flags.append(
                {
                    "type": "synthetic_positions",
                    "severity": "info",
                    "message": f"{synthetic_count} position(s) inferred from current holdings (no opening trade found)",
                    "synthetic_count": synthetic_count,
                }
            )

        if bool(data_quality.get("nav_metrics_estimated", False)):
            flags.append(
                {
                    "type": "nav_metrics_estimated",
                    "severity": "info",
                    "message": "NAV-based metrics (return, drawdown) are estimated - not all cash flows observed",
                }
            )

        fetch_errors = data_quality.get("fetch_errors") or {}
        if fetch_errors:
            skipped = sorted(p for p, e in fetch_errors.items() if "skipped" in str(e).lower())
            errored = sorted(p for p in fetch_errors if p not in skipped)
            if skipped:
                flags.append(
                    {
                        "type": "provider_data_missing",
                        "severity": "warning",
                        "message": (
                            f"Transaction provider(s) not configured: "
                            f"{', '.join(skipped)}. Realized performance may be incomplete."
                        ),
                    }
                )
            if errored:
                flags.append(
                    {
                        "type": "provider_fetch_error",
                        "severity": "warning",
                        "message": (
                            f"Transaction provider(s) failed during fetch: "
                            f"{', '.join(errored)}. Their transactions are excluded."
                        ),
                    }
                )

        if bool(data_quality.get("high_confidence", False)) and reliable is not False:
            flags.append(
                {
                    "type": "high_confidence",
                    "severity": "success",
                    "message": "Transaction coverage is high - realized metrics are reliable",
                }
            )

    if total_return is not None and total_return > 0 and excess_return is not None and excess_return > 0:
        flags.append(
            {
                "type": "outperforming",
                "severity": "success",
                "message": f"Beating {benchmark.get('ticker', 'benchmark')} by {excess_return:.1f}% annualized excess return",
                "excess_return_pct": round(excess_return, 2),
            }
        )

    severity_order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    flags.sort(key=lambda flag: severity_order.get(flag.get("severity"), 9))
    return flags

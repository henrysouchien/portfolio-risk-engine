"""Rebalance interpretive flags for agent-oriented responses."""

from __future__ import annotations

import math
from typing import Any, Dict, List

from portfolio_risk_engine.constants import get_asset_class_display_name


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _sort_flags(flags: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    severity_order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    flags.sort(key=lambda flag: severity_order.get(flag.get("severity"), 9))
    return flags


def _format_pct(value: float, *, decimals: int = 0) -> str:
    if decimals <= 0:
        return f"{value:.0f}%"
    return f"{value:.{decimals}f}%"


def generate_rebalance_flags(snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Generate interpretive flags from a rebalance agent snapshot."""
    if not isinstance(snapshot, dict):
        return []

    flags: List[Dict[str, Any]] = []
    trades = snapshot.get("trades") if isinstance(snapshot.get("trades"), list) else []
    skipped_trades = (
        snapshot.get("skipped_trades") if isinstance(snapshot.get("skipped_trades"), list) else []
    )

    portfolio_value = _to_float(snapshot.get("portfolio_value")) or 0.0
    total_sell_value = _to_float(snapshot.get("total_sell_value")) or 0.0
    total_buy_value = _to_float(snapshot.get("total_buy_value")) or 0.0
    total_trade_value = total_sell_value + total_buy_value
    trade_count = _to_int(snapshot.get("trade_count")) or len(trades)
    skipped_count = _to_int(snapshot.get("skipped_count")) or len(skipped_trades)

    if portfolio_value > 0 and total_trade_value > (0.5 * portfolio_value):
        flags.append(
            {
                "type": "large_rebalance",
                "severity": "warning",
                "message": (
                    f"Trade notional is ${total_trade_value:,.2f} "
                    f"({(total_trade_value / portfolio_value) * 100:.1f}% of portfolio)"
                ),
                "total_trade_value": round(total_trade_value, 2),
                "portfolio_value": round(portfolio_value, 2),
            }
        )

    turnover = 0.0
    for trade in trades:
        turnover += abs(_to_float(trade.get("weight_delta")) or 0.0)
    if turnover > 0.30:
        flags.append(
            {
                "type": "high_turnover",
                "severity": "warning",
                "message": f"Total turnover is {turnover * 100:.1f}% (> 30%)",
                "turnover": round(turnover, 4),
            }
        )

    sell_all = []
    preview_failures = []
    for trade in trades:
        ticker = str(trade.get("ticker") or "").upper()
        side = str(trade.get("side") or "").upper()
        current_weight = _to_float(trade.get("current_weight")) or 0.0
        target_weight = _to_float(trade.get("target_weight")) or 0.0
        status = str(trade.get("status") or "").lower()

        if side == "SELL" and current_weight > 0 and target_weight <= 0:
            sell_all.append(ticker)
        if status == "preview_failed":
            preview_failures.append(ticker)

    if sell_all:
        flags.append(
            {
                "type": "sell_all_position",
                "severity": "info",
                "message": f"Selling out of {len(sell_all)} position(s)",
                "tickers": sorted(set(sell_all)),
            }
        )

    if skipped_count > 0:
        flags.append(
            {
                "type": "trades_skipped",
                "severity": "info",
                "message": f"{skipped_count} trade leg(s) skipped",
                "skipped_count": skipped_count,
            }
        )

    missing_price_tickers = sorted(
        {
            str(row.get("ticker") or "").upper()
            for row in skipped_trades
            if str(row.get("reason") or "").lower() == "missing_price"
            and str(row.get("ticker") or "").strip()
        }
    )
    if missing_price_tickers:
        flags.append(
            {
                "type": "price_fetch_failed",
                "severity": "warning",
                "message": f"Missing prices for {len(missing_price_tickers)} ticker(s)",
                "tickers": missing_price_tickers,
            }
        )

    unmanaged_mode = str(snapshot.get("unmanaged_mode") or "hold").lower()
    unmanaged_positions = (
        snapshot.get("unmanaged_positions")
        if isinstance(snapshot.get("unmanaged_positions"), list)
        else []
    )
    unmanaged_positions = [
        str(ticker).upper()
        for ticker in unmanaged_positions
        if str(ticker or "").strip()
    ]
    if unmanaged_mode == "hold" and unmanaged_positions:
        flags.append(
            {
                "type": "unmanaged_positions",
                "severity": "info",
                "message": f"{len(unmanaged_positions)} held position(s) left unchanged",
                "tickers": sorted(set(unmanaged_positions)),
            }
        )

    if preview_failures:
        flags.append(
            {
                "type": "preview_failures",
                "severity": "error",
                "message": f"{len(preview_failures)} leg(s) failed preview",
                "tickers": sorted(set(preview_failures)),
            }
        )

    target_weight_sum = _to_float(snapshot.get("target_weight_sum"))
    if target_weight_sum is not None:
        if target_weight_sum < 0.90 or target_weight_sum > 1.10:
            flags.append(
                {
                    "type": "weight_sum_drift",
                    "severity": "warning",
                    "message": (
                        "Target weights sum to "
                        f"{target_weight_sum:.3f} (outside warning range 0.90-1.10)"
                    ),
                    "target_weight_sum": round(target_weight_sum, 6),
                }
            )
        elif target_weight_sum < 0.95 or target_weight_sum > 1.05:
            flags.append(
                {
                    "type": "weight_sum_drift",
                    "severity": "info",
                    "message": (
                        "Target weights sum to "
                        f"{target_weight_sum:.3f} (outside ideal range 0.95-1.05)"
                    ),
                    "target_weight_sum": round(target_weight_sum, 6),
                }
            )

    has_error = any(str(flag.get("severity")) == "error" for flag in flags)
    if trade_count > 0 and not has_error:
        flags.append(
            {
                "type": "rebalance_ready",
                "severity": "success",
                "message": f"{trade_count} rebalance trade(s) generated and ready",
                "trade_count": trade_count,
            }
        )

    return _sort_flags(flags)


def generate_rebalance_diagnostic_flags(
    risk_contributions: List[Dict[str, Any]],
    factor_betas: Dict[str, Dict[str, float]],
    compliance_summary: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Generate pre-rebalance diagnostic flags from cached risk analysis outputs."""
    flags: List[Dict[str, Any]] = []

    for row in risk_contributions if isinstance(risk_contributions, list) else []:
        ratio = _to_float(row.get("risk_weight_ratio"))
        if ratio is None or ratio <= 1.2:
            continue

        asset_class = str(row.get("asset_class") or "unknown").strip().lower() or "unknown"
        risk_pct = _to_float(row.get("risk_pct")) or 0.0
        weight_pct = _to_float(row.get("weight_pct")) or 0.0
        severity = "warning" if ratio > 1.5 else "info"
        flags.append(
            {
                "type": "risk_weight_imbalance",
                "severity": severity,
                "message": (
                    f"{get_asset_class_display_name(asset_class)} contributes "
                    f"{_format_pct(risk_pct)} of risk at {_format_pct(weight_pct)} weight "
                    f"({ratio:.1f}x ratio)"
                ),
                "asset_class": asset_class,
                "risk_pct": round(risk_pct, 2),
                "weight_pct": round(weight_pct, 2),
                "risk_weight_ratio": round(ratio, 2),
            }
        )

    systemic_factors = {"market", "interest_rate", "rate_2y", "rate_5y", "rate_10y", "rate_30y"}
    weight_lookup = {
        str(row.get("asset_class") or "").strip().lower(): (_to_float(row.get("weight_pct")) or 0.0) / 100.0
        for row in risk_contributions
        if isinstance(row, dict)
    }
    factor_scores: Dict[str, List[Dict[str, float | str]]] = {}
    for asset_class, exposures in factor_betas.items() if isinstance(factor_betas, dict) else []:
        asset_class_key = str(asset_class or "").strip().lower()
        class_weight = weight_lookup.get(asset_class_key, 0.0)
        if class_weight <= 0 or not isinstance(exposures, dict):
            continue
        for factor, raw_beta in exposures.items():
            beta = _to_float(raw_beta)
            if beta is None or abs(beta) < 0.5:
                continue
            factor_scores.setdefault(str(factor), []).append(
                {
                    "asset_class": asset_class_key,
                    "beta": beta,
                    "score": abs(beta) * class_weight,
                }
            )

    for factor, rows in factor_scores.items():
        total_score = sum(float(row.get("score") or 0.0) for row in rows)
        if total_score <= 0:
            continue
        dominant = max(rows, key=lambda row: float(row.get("score") or 0.0))
        dominant_share = float(dominant.get("score") or 0.0) / total_score
        dominant_beta = _to_float(dominant.get("beta"))
        asset_class = str(dominant.get("asset_class") or "unknown")
        if dominant_share < 0.6 or dominant_beta is None:
            continue

        flags.append(
            {
                "type": "factor_exposure_driver",
                "severity": "warning" if factor in systemic_factors else "info",
                "message": (
                    f"{get_asset_class_display_name(asset_class)} drives "
                    f"{_format_pct(dominant_share * 100)} of {factor} exposure "
                    f"(beta {dominant_beta:.1f})"
                ),
                "asset_class": asset_class,
                "factor": factor,
                "dominance_pct": round(dominant_share * 100, 2),
                "beta": round(dominant_beta, 4),
            }
        )

    violation_count = _to_int((compliance_summary or {}).get("violation_count")) or 0
    if violation_count > 0:
        flags.append(
            {
                "type": "compliance_driven_rebalance",
                "severity": "error",
                "message": f"Rebalancing needed to resolve {violation_count} compliance violation(s)",
                "violation_count": violation_count,
            }
        )

    return _sort_flags(flags)

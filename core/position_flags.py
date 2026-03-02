"""Position-level interpretive flags for agent-oriented responses."""

from __future__ import annotations

from datetime import date, datetime
import math
from typing import Any

from portfolio_risk_engine.constants import DIVERSIFIED_SECURITY_TYPES


def _to_float(value: Any, default: float = 0.0) -> float:
    """Convert value to finite float, otherwise return default."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(numeric):
        return default
    return numeric


def _is_diversified(position: dict[str, Any], security_types: dict[str, str] | None) -> bool:
    """Return True when position is an ETF/fund/mutual fund."""
    ticker_raw = str(position.get("ticker") or "").strip()
    ticker = ticker_raw.upper()
    if security_types and ticker:
        security_type = security_types.get(ticker)
        if security_type is None:
            security_type = security_types.get(ticker_raw)
        if security_type is not None:
            return str(security_type).lower() in DIVERSIFIED_SECURITY_TYPES

    raw_type = str(position.get("type", "")).strip().lower()
    return raw_type in DIVERSIFIED_SECURITY_TYPES or raw_type == "mutual fund"


def _parse_option_expiry(value: Any) -> date | None:
    """Parse option expiry values into a date object."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    token = str(value or "").strip()
    if not token:
        return None

    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(token, fmt).date()
        except ValueError:
            continue
    return None


def generate_position_flags(
    positions: list[dict],
    total_value: float,
    cache_info: dict,
    *,
    by_sector: dict[str, dict[str, Any]] | None = None,
    monitor_positions: list[dict] | None = None,
    security_types: dict[str, str] | None = None,
) -> list[dict]:
    """Generate actionable flags from position data."""
    flags: list[dict] = []
    all_positions = positions or []
    portfolio_total = abs(_to_float(total_value))

    non_cash = [
        position
        for position in all_positions
        if position.get("type") != "cash"
        and not str(position.get("ticker", "")).startswith("CUR:")
    ]
    single_issuer = [position for position in non_cash if not _is_diversified(position, security_types)]
    diversified = [position for position in non_cash if _is_diversified(position, security_types)]

    for provider, info in (cache_info or {}).items():
        if not isinstance(info, dict):
            continue
        if info.get("error"):
            flags.append(
                {
                    "type": "provider_error",
                    "severity": "error",
                    "message": f"{provider}: {info['error']}",
                    "provider": provider,
                }
            )

    # Concentration uses absolute non-cash exposure.
    gross_non_cash = sum(abs(_to_float(position.get("value", 0))) for position in non_cash)

    if gross_non_cash > 0:
        for position in single_issuer:
            ticker = str(position.get("ticker", "UNKNOWN"))
            abs_weight = abs(_to_float(position.get("value", 0))) / gross_non_cash * 100.0
            if abs_weight > 15.0:
                flags.append(
                    {
                        "type": "single_position_concentration",
                        "severity": "warning",
                        "message": f"{ticker} is {abs_weight:.1f}% of exposure",
                        "ticker": ticker,
                        "weight_pct": round(abs_weight, 1),
                    }
                )

        sorted_by_abs = sorted(
            single_issuer,
            key=lambda position: abs(_to_float(position.get("value", 0))),
            reverse=True,
        )
        top5_value = sum(abs(_to_float(position.get("value", 0))) for position in sorted_by_abs[:5])
        top5_weight = top5_value / gross_non_cash * 100.0
        if top5_weight > 60.0:
            flags.append(
                {
                    "type": "top5_concentration",
                    "severity": "info",
                    "message": f"Top 5 holdings are {top5_weight:.0f}% of exposure",
                    "top5_weight_pct": round(top5_weight, 1),
                }
            )

        for position in diversified:
            ticker = str(position.get("ticker", "UNKNOWN"))
            abs_weight = abs(_to_float(position.get("value", 0))) / gross_non_cash * 100.0
            if abs_weight > 30.0:
                flags.append(
                    {
                        "type": "large_fund_position",
                        "severity": "info",
                        "message": f"{ticker} is {abs_weight:.1f}% of exposure (diversified fund/ETF)",
                        "ticker": ticker,
                        "weight_pct": round(abs_weight, 1),
                    }
                )

    # Leverage: exclude positive cash, include negative cash (margin debt).
    net_exposure = 0.0
    gross_exposure = 0.0
    for position in all_positions:
        ticker = str(position.get("ticker", ""))
        position_type = str(position.get("type", ""))
        value = _to_float(position.get("value", 0))
        is_cash = position_type == "cash" or ticker.startswith("CUR:")
        if is_cash and value > 0:
            continue
        net_exposure += value
        gross_exposure += abs(value)

    leverage = gross_exposure / abs(net_exposure) if abs(net_exposure) > 1e-12 else 1.0
    if leverage > 2.0:
        flags.append(
            {
                "type": "high_leverage",
                "severity": "warning",
                "message": f"Portfolio is {leverage:.1f}x levered",
                "leverage": round(leverage, 2),
            }
        )
    elif leverage > 1.1:
        flags.append(
            {
                "type": "leveraged",
                "severity": "info",
                "message": f"Portfolio is {leverage:.2f}x levered",
                "leverage": round(leverage, 2),
            }
        )

    futures_notional = sum(
        _to_float(p.get("notional", 0))
        for p in all_positions
        if p.get("notional") is not None
    )
    if futures_notional > 0 and portfolio_total > 0:
        notional_ratio = futures_notional / portfolio_total
        if notional_ratio > 2.0:
            flags.append(
                {
                    "type": "futures_high_notional",
                    "severity": "warning",
                    "message": f"Futures notional ${futures_notional:,.0f} is {notional_ratio:.1f}x portfolio value",
                    "notional": round(futures_notional, 2),
                    "ratio": round(notional_ratio, 1),
                }
            )
        elif notional_ratio > 0.5:
            flags.append(
                {
                    "type": "futures_notional",
                    "severity": "info",
                    "message": f"Futures notional exposure: ${futures_notional:,.0f} ({notional_ratio:.1f}x portfolio)",
                    "notional": round(futures_notional, 2),
                    "ratio": round(notional_ratio, 1),
                }
            )

    option_positions = [
        position
        for position in all_positions
        if bool(position.get("is_option"))
        or str(position.get("type") or "").strip().lower() == "option"
    ]
    if option_positions:
        expired_count = 0
        near_expiry_count = 0
        nearest_dte = None
        today = date.today()

        for position in option_positions:
            dte_raw = _to_float(position.get("days_to_expiry"), default=float("nan"))
            dte = int(dte_raw) if math.isfinite(dte_raw) else None
            if dte is None:
                expiry_dt = _parse_option_expiry(position.get("expiry"))
                if expiry_dt is not None:
                    dte = (expiry_dt - today).days

            if dte is None:
                continue

            if nearest_dte is None or dte < nearest_dte:
                nearest_dte = dte

            if dte <= 0:
                expired_count += 1
            elif dte <= 7:
                near_expiry_count += 1

        if expired_count > 0:
            flags.append(
                {
                    "type": "expired_options",
                    "severity": "error",
                    "message": f"{expired_count} option position(s) are expired (DTE <= 0)",
                    "expired_count": expired_count,
                }
            )

        if near_expiry_count > 0:
            flags.append(
                {
                    "type": "near_expiry_options",
                    "severity": "warning",
                    "message": f"{near_expiry_count} option position(s) expire within 7 days",
                    "near_expiry_count": near_expiry_count,
                    "nearest_dte": nearest_dte,
                }
            )

        option_value = sum(abs(_to_float(position.get("value", 0))) for position in option_positions)
        if portfolio_total > 0:
            option_ratio = option_value / portfolio_total
            if option_ratio > 0.20:
                flags.append(
                    {
                        "type": "options_concentration",
                        "severity": "info",
                        "message": (
                            f"Options are {option_ratio * 100.0:.1f}% of portfolio value "
                            f"(${option_value:,.0f})"
                        ),
                        "option_count": len(option_positions),
                        "options_value": round(option_value, 2),
                        "options_weight_pct": round(option_ratio * 100.0, 1),
                    }
                )

    # Cash: split into positive cash (drag) and negative cash (margin debt)
    cash_balance = 0.0
    margin_debt = 0.0
    for position in all_positions:
        ptype = str(position.get("type", ""))
        ticker = str(position.get("ticker", ""))
        if ptype == "cash" or ticker.startswith("CUR:"):
            val = _to_float(position.get("value", 0))
            if val >= 0:
                cash_balance += val
            else:
                margin_debt += val  # negative

    # Cash drag: positive cash > 15% of portfolio
    if portfolio_total > 0:
        cash_pct = cash_balance / portfolio_total * 100.0
        if cash_pct > 15.0:
            flags.append(
                {
                    "type": "cash_drag",
                    "severity": "info",
                    "message": f"Cash is {cash_pct:.0f}% of portfolio (${cash_balance:,.0f})",
                    "cash_pct": round(cash_pct, 1),
                    "cash_value": round(cash_balance, 2),
                }
            )

    # Margin usage: negative cash (borrowed funds) > 20% of portfolio
    if portfolio_total > 0 and margin_debt < 0:
        margin_pct = abs(margin_debt) / portfolio_total * 100.0
        if margin_pct > 20.0:
            flags.append(
                {
                    "type": "margin_usage",
                    "severity": "warning",
                    "message": f"${abs(margin_debt):,.0f} margin debt ({margin_pct:.0f}% of portfolio)",
                    "margin_debt": round(margin_debt, 2),
                    "margin_pct": round(margin_pct, 1),
                }
            )

    # Stale data: age > 2x TTL for each provider.
    for provider, info in (cache_info or {}).items():
        if not isinstance(info, dict):
            continue
        age = info.get("age_hours")
        ttl = info.get("ttl_hours", 24)
        age_val = _to_float(age, default=float("nan"))
        ttl_val = _to_float(ttl, default=24.0)
        if math.isfinite(age_val) and ttl_val > 0 and age_val > ttl_val * 2:
            flags.append(
                {
                    "type": "stale_data",
                    "severity": "warning",
                    "message": f"{provider} data is {age_val:.0f}h old (TTL {ttl_val:g}h)",
                    "provider": provider,
                    "age_hours": round(age_val, 1),
                    "ttl_hours": ttl_val,
                }
            )

    non_cash_count = len(non_cash)
    if 0 < non_cash_count < 5:
        flags.append(
            {
                "type": "low_position_count",
                "severity": "info",
                "message": f"Only {non_cash_count} non-cash positions - limited diversification",
                "position_count": non_cash_count,
            }
        )

    # Sector concentration/diversification based on enriched monitor payload.
    if by_sector:
        real_sector_rows = [
            (str(sector), stats)
            for sector, stats in by_sector.items()
            if str(sector).strip() and str(sector).strip().lower() != "unknown"
            and isinstance(stats, dict)
        ]

        for sector, stats in real_sector_rows:
            weight_pct = _to_float(stats.get("weight_pct"))
            if weight_pct > 40.0:
                flags.append(
                    {
                        "type": "sector_concentration",
                        "severity": "warning",
                        "message": f"{sector} is {weight_pct:.0f}% of exposure",
                        "sector": sector,
                        "weight_pct": round(weight_pct, 1),
                    }
                )

        if 0 < len(real_sector_rows) <= 2:
            sectors = [sector for sector, _ in real_sector_rows]
            count = len(sectors)
            noun = "sector" if count == 1 else "sectors"
            flags.append(
                {
                    "type": "low_sector_diversification",
                    "severity": "info",
                    "message": f"Portfolio concentrated in {count} {noun}: {', '.join(sectors)}",
                    "sector_count": count,
                    "sectors": sectors,
                }
            )

    # P&L quality/risk flags from monitor payload.
    if monitor_positions:
        total_positions = 0
        missing_cost_basis = 0

        for position in monitor_positions:
            if not isinstance(position, dict):
                continue
            total_positions += 1

            cost_basis = position.get("cost_basis")
            if cost_basis is None:
                missing_cost_basis += 1

            pnl_percent = _to_float(position.get("pnl_percent"), default=float("nan"))
            pnl_usd = _to_float(position.get("pnl_usd"), default=float("nan"))
            if math.isfinite(pnl_percent) and math.isfinite(pnl_usd):
                if pnl_percent < -20.0 and pnl_usd < -5000.0:
                    ticker = str(position.get("ticker", "UNKNOWN"))
                    flags.append(
                        {
                            "type": "large_unrealized_loss",
                            "severity": "warning",
                            "message": f"{ticker} is down {abs(pnl_percent):.0f}% (${abs(pnl_usd):,.0f})",
                            "ticker": ticker,
                            "pnl_percent": round(pnl_percent, 1),
                            "pnl_usd": round(pnl_usd, 2),
                        }
                    )

        if total_positions > 0:
            coverage_pct = ((total_positions - missing_cost_basis) / total_positions) * 100.0
            missing_pct = 100.0 - coverage_pct
            if missing_pct > 30.0:
                flags.append(
                    {
                        "type": "low_cost_basis_coverage",
                        "severity": "info",
                        "message": (
                            f"{missing_cost_basis}/{total_positions} positions missing cost basis "
                            "-- P&L may be incomplete"
                        ),
                        "coverage_pct": round(coverage_pct, 1),
                        "missing_count": missing_cost_basis,
                        "position_count": total_positions,
                    }
                )

    severity_order = {"error": 0, "warning": 1, "info": 2}
    flags.sort(key=lambda flag: severity_order.get(flag.get("severity"), 9))
    return flags

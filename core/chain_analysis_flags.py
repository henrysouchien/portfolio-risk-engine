"""Option-chain interpretive flags for agent-oriented responses."""

from __future__ import annotations

from datetime import date, timedelta


def _as_float(value) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:
        return None
    return out


def _parse_expiry(expiry: str | None) -> date | None:
    raw = str(expiry or "").strip()
    if len(raw) != 8 or not raw.isdigit():
        return None
    try:
        return date(int(raw[0:4]), int(raw[4:6]), int(raw[6:8]))
    except ValueError:
        return None


def _trading_days_until(expiry_dt: date, *, today: date | None = None) -> int:
    start = today or date.today()
    if expiry_dt < start:
        return -1

    days = 0
    cursor = start
    while cursor < expiry_dt:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            days += 1
    return days


def generate_chain_analysis_flags(snapshot: dict) -> list[dict]:
    """Generate severity-tagged flags from option-chain analysis snapshot."""
    flags: list[dict] = []

    status = snapshot.get("status", "error")
    strike_count = int(snapshot.get("strike_count", 0) or 0)

    if status != "success" or strike_count <= 0:
        flags.append(
            {
                "flag": "fetch_error",
                "severity": "error",
                "message": snapshot.get("verdict", "No option chain data available"),
            }
        )
        return _sort_flags(flags)

    put_call_ratio = _as_float(snapshot.get("put_call_ratio"))
    if put_call_ratio is not None and put_call_ratio > 1.5:
        flags.append(
            {
                "flag": "high_put_call_ratio",
                "severity": "warning",
                "message": f"Put/call ratio {put_call_ratio:.2f} indicates bearish OI skew",
            }
        )
    elif put_call_ratio is not None and put_call_ratio < 0.5:
        flags.append(
            {
                "flag": "low_put_call_ratio",
                "severity": "info",
                "message": f"Put/call ratio {put_call_ratio:.2f} indicates bullish OI skew",
            }
        )

    max_pain = _as_float(snapshot.get("max_pain"))
    underlying = _as_float(snapshot.get("underlying_price"))
    if max_pain is not None and underlying is not None:
        if max_pain < underlying:
            flags.append(
                {
                    "flag": "max_pain_below_current",
                    "severity": "info",
                    "message": "Max pain is below current price",
                }
            )
        elif max_pain > underlying:
            flags.append(
                {
                    "flag": "max_pain_above_current",
                    "severity": "info",
                    "message": "Max pain is above current price",
                }
            )

    concentration = _as_float(snapshot.get("highest_oi_concentration_pct"))
    if concentration is not None and concentration > 25.0:
        flags.append(
            {
                "flag": "concentrated_oi",
                "severity": "info",
                "message": f"Single strike concentration is high ({concentration:.1f}% of total OI)",
            }
        )

    total_oi = int(snapshot.get("total_call_oi", 0) or 0) + int(snapshot.get("total_put_oi", 0) or 0)
    total_volume = int(snapshot.get("total_volume", 0) or 0)
    if total_oi < 1000 or total_volume < 100:
        flags.append(
            {
                "flag": "low_liquidity",
                "severity": "warning",
                "message": (
                    f"Low chain liquidity (total OI {total_oi:,}, total volume {total_volume:,})"
                ),
            }
        )

    expiry_dt = _parse_expiry(snapshot.get("expiry"))
    if expiry_dt is not None:
        days_to_expiry = _trading_days_until(expiry_dt)
        if 0 <= days_to_expiry <= 5:
            flags.append(
                {
                    "flag": "near_expiry",
                    "severity": "info",
                    "message": f"Expiry is near ({days_to_expiry} trading days)",
                }
            )

    flags.append(
        {
            "flag": "analysis_complete",
            "severity": "success",
            "message": "Option-chain analysis complete",
        }
    )

    return _sort_flags(flags)


def _sort_flags(flags):
    order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    return sorted(flags, key=lambda f: order.get(f.get("severity", "info"), 2))

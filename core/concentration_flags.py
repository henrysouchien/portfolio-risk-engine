"""Concentration-focused interpretive flags for overview card insights."""

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


def generate_concentration_flags(
    risk_snapshot: dict,
    position_count: int,
    analysis_summary: dict | None = None,
) -> list[dict]:
    """Generate overview-card concentration flags from the risk snapshot."""
    if position_count <= 0 or not isinstance(risk_snapshot, dict):
        return []

    component_scores = risk_snapshot.get("component_scores", {})
    if not isinstance(component_scores, dict):
        return []

    conc_score = _to_float(component_scores.get("concentration_risk"))
    if conc_score is None:
        return []

    conc_meta = risk_snapshot.get("concentration_metadata", {})
    usable_metadata = _has_usable_metadata(conc_meta)

    flags: list[dict] = []
    if conc_score < 40:
        flags.append(_build_primary_flag("concentrated_portfolio", "warning", conc_score, conc_meta, usable_metadata))
    elif conc_score < 70:
        flags.append(_build_primary_flag("moderate_concentration", "info", conc_score, conc_meta, usable_metadata))
    else:
        flags.append(_build_primary_flag("well_diversified", "success", conc_score, conc_meta, usable_metadata))

    if conc_score >= 40 and position_count < 10:
        flags.append(
            {
                "type": "low_position_count_context",
                "severity": "success",
                "message": f"Only {position_count} positions, so diversification can shift quickly as holdings move",
                "position_count": int(position_count),
            }
        )

    factor_variance_pct = _to_float((analysis_summary or {}).get("factor_variance_pct"))
    if factor_variance_pct is not None and factor_variance_pct > 0.70:
        flags.append(
            {
                "type": "factor_dominated",
                "severity": "success",
                "message": (
                    f"{factor_variance_pct * 100:.0f}% of risk from market/sector factors "
                    f"- diversification reducing stock-specific risk"
                ),
                "factor_variance_pct": round(factor_variance_pct, 4),
            }
        )

    idiosyncratic_variance_pct = _to_float((analysis_summary or {}).get("idiosyncratic_variance_pct"))
    if idiosyncratic_variance_pct is not None and idiosyncratic_variance_pct > 0.50:
        flags.append(
            {
                "type": "stock_specific_heavy",
                "severity": "success",
                "message": (
                    f"{idiosyncratic_variance_pct * 100:.0f}% stock-specific risk "
                    f"- individual holdings drive outcomes"
                ),
                "idiosyncratic_variance_pct": round(idiosyncratic_variance_pct, 4),
            }
        )

    return _sort_flags(flags)


def _build_primary_flag(
    flag_type: str,
    severity: str,
    conc_score: float,
    conc_meta: dict,
    usable_metadata: bool,
) -> dict:
    message = _build_specific_message(flag_type, conc_meta) if usable_metadata else _build_generic_message(flag_type, conc_score)
    flag = {
        "type": flag_type,
        "severity": severity,
        "message": message,
        "concentration_score": round(conc_score, 1),
    }

    if usable_metadata:
        driver = str(conc_meta.get("concentration_driver") or "").strip()
        if driver:
            flag["concentration_driver"] = driver
        largest_ticker = _normalize_text(conc_meta.get("largest_ticker"))
        if largest_ticker:
            flag["largest_ticker"] = largest_ticker
        largest_weight = _to_float(conc_meta.get("largest_weight"))
        if largest_weight is not None:
            flag["largest_weight"] = round(largest_weight, 1)
        top_n_tickers = _extract_tickers(conc_meta.get("top_n_tickers"))
        if top_n_tickers:
            flag["top_n_tickers"] = top_n_tickers
        top_n_weight = _to_float(conc_meta.get("top_n_weight"))
        if top_n_weight is not None:
            flag["top_n_weight"] = round(top_n_weight, 1)
    return flag


def _has_usable_metadata(conc_meta: Any) -> bool:
    if not isinstance(conc_meta, dict):
        return False
    driver = _normalize_text(conc_meta.get("concentration_driver"))
    if not driver:
        return False
    return bool(_extract_tickers(conc_meta.get("top_n_tickers")) or _normalize_text(conc_meta.get("largest_ticker")))


def _build_specific_message(flag_type: str, conc_meta: dict) -> str:
    driver = _normalize_text(conc_meta.get("concentration_driver"))
    top_n_tickers = _extract_tickers(conc_meta.get("top_n_tickers"))
    top_n_weight = _to_float(conc_meta.get("top_n_weight"))
    largest_ticker = _normalize_text(conc_meta.get("largest_ticker")) or "largest holding"
    largest_weight = _to_float(conc_meta.get("largest_weight"))

    if driver == "top_n" and top_n_tickers:
        tickers = ", ".join(top_n_tickers)
        weight_text = f"{top_n_weight:.1f}%" if top_n_weight is not None else "an elevated share"
        if flag_type == "concentrated_portfolio":
            return f"Top positions ({tickers}) represent {weight_text} of the portfolio"
        if flag_type == "moderate_concentration":
            return f"Top positions ({tickers}) still account for {weight_text} of the portfolio"
        return f"Top positions ({tickers}) are contained at {weight_text} of the portfolio"

    weight_text = f"{largest_weight:.1f}%" if largest_weight is not None else "a large share"
    if flag_type == "concentrated_portfolio":
        return f"Largest position ({largest_ticker}) is {weight_text} of the portfolio"
    if flag_type == "moderate_concentration":
        return f"Largest position ({largest_ticker}) is {weight_text} of the portfolio"
    return f"Largest position ({largest_ticker}) is limited to {weight_text} of the portfolio"


def _build_generic_message(flag_type: str, conc_score: float) -> str:
    if flag_type == "concentrated_portfolio":
        return f"Portfolio is concentrated (diversification score {conc_score:.0f}/100)"
    if flag_type == "moderate_concentration":
        return f"Portfolio concentration is moderate (diversification score {conc_score:.0f}/100)"
    return f"Portfolio is well diversified (diversification score {conc_score:.0f}/100)"


def _extract_tickers(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    tickers: list[str] = []
    for item in value:
        ticker = _normalize_text(item)
        if ticker:
            tickers.append(ticker)
    return tickers


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _sort_flags(flags: list[dict]) -> list[dict]:
    """Sort by severity: error > warning > info > success."""
    order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    return sorted(flags, key=lambda flag: order.get(flag.get("severity", "info"), 2))

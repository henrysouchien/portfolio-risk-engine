"""Auto-seed editorial memory from live portfolio composition."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from app_platform.logging.core import log_event
from database import get_db_session
from models.overview_editorial import EditorialMemory
from providers.completion import complete_structured, get_completion_provider
from services.position_service import PositionService

from .editorial_state_store import editorial_state_row_exists, load_editorial_state, seed_editorial_memory_if_missing
from .vocabulary import CATEGORIES, TAGS

_logger = logging.getLogger(__name__)
_DEFAULT_PORTFOLIO_NAME = "CURRENT_PORTFOLIO"
_EDITORIAL_MODEL = os.getenv("EDITORIAL_LLM_MODEL") or None


def _resolve_user_email_for_user_id(user_id: int) -> str | None:
    try:
        with get_db_session() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT email FROM users WHERE id = %s", (user_id,))
                row = cur.fetchone()
        if row is None:
            return None
        if isinstance(row, dict):
            return str(row.get("email") or "").strip() or None
        try:
            value = row["email"]
        except Exception:
            value = row[0]
        return str(value or "").strip() or None
    except Exception:
        return None


def _skip(user_id: int, trigger: str, reason: str) -> bool:
    details = {"user_id": user_id, "auto_seed_trigger": trigger, "reason": reason}
    _logger.info("editorial_memory_auto_seed_skipped", extra=details)
    log_event(
        "editorial_memory_auto_seed_skipped",
        "Editorial memory auto-seed skipped",
        **details,
    )
    return False


def build_portfolio_composition_summary(position_result: Any) -> dict[str, Any] | None:
    holdings = list(getattr(position_result, "get_top_holdings", lambda _n=10: [])(8) or [])
    if len(holdings) < 3:
        return None

    total_value = float(getattr(position_result, "total_value", 0.0) or 0.0)
    if total_value < 1000:
        return None

    return {
        "total_value": round(total_value, 2),
        "position_count": int(getattr(position_result, "position_count", len(holdings)) or len(holdings)),
        "top_holdings": [
            {
                "ticker": str(holding.get("ticker") or ""),
                "weight_pct": float(holding.get("weight_pct") or 0.0),
                "type": holding.get("type"),
            }
            for holding in holdings[:5]
        ],
    }


def _deterministic_seed_from_summary(user_id: int, summary: dict[str, Any]) -> dict[str, Any]:
    base_memory, _ = load_editorial_state(user_id, None)
    top_holdings = list(summary.get("top_holdings") or [])
    lead_with = [CATEGORIES.PERFORMANCE, CATEGORIES.CONCENTRATION]
    if top_holdings and float(top_holdings[0].get("weight_pct") or 0.0) >= 15:
        lead_with = [CATEGORIES.CONCENTRATION, CATEGORIES.RISK]

    seed = dict(base_memory)
    preferences = dict(seed.get("editorial_preferences") or {})
    preferences["lead_with"] = lead_with
    preferences["care_about"] = list(
        dict.fromkeys(
            [
                *(preferences.get("care_about") or []),
                TAGS.PERFORMANCE_VS_BENCHMARK,
                CATEGORIES.CONCENTRATION,
            ]
        )
    )
    seed["editorial_preferences"] = preferences

    current_focus = dict(seed.get("current_focus") or {})
    current_focus["watching"] = [
        {
            "ticker": str(holding.get("ticker") or ""),
            "weight_pct": float(holding.get("weight_pct") or 0.0),
        }
        for holding in top_holdings[:3]
    ]
    seed["current_focus"] = current_focus

    extracts = list(seed.get("conversation_extracts") or [])
    if top_holdings:
        extracts.append(
            {
                "date": time.strftime("%Y-%m-%d"),
                "extract": (
                    f"Auto-seed from live portfolio: {top_holdings[0].get('ticker')} leads at "
                    f"{float(top_holdings[0].get('weight_pct') or 0.0):.1f}% of exposure."
                ),
            }
        )
    seed["conversation_extracts"] = extracts[-8:]
    return EditorialMemory.model_validate(seed).model_dump(mode="python")


def _llm_seed_from_summary(user_id: int, summary: dict[str, Any]) -> dict[str, Any] | None:
    provider = get_completion_provider()
    if provider is None:
        return None

    seed_memory, _ = load_editorial_state(user_id, None)
    prompt = json.dumps(
        {
            "seed_template": seed_memory,
            "portfolio_summary": summary,
            "task": (
                "Return one editorial memory JSON object for this portfolio. "
                "Keep the same top-level shape, personalize lead_with/care_about/current_focus, "
                "and keep it compact."
            ),
        },
        indent=2,
        sort_keys=True,
    )
    try:
        payload = complete_structured(
            provider,
            prompt,
            response_model=EditorialMemory,
            system="Return only JSON matching the existing editorial memory structure.",
            model=_EDITORIAL_MODEL,
            temperature=0.2,
            max_tokens=1200,
            timeout=20,
        )
    except Exception:
        _logger.warning("overview auto-seed structured parse failed", exc_info=True)
        return None
    return payload.model_dump(mode="python")


def auto_seed_from_portfolio(
    *,
    user_id: int,
    user_email: str | None = None,
    portfolio_name: str = _DEFAULT_PORTFOLIO_NAME,
    trigger: str = "sync_completion",
) -> bool:
    if editorial_state_row_exists(user_id):
        return _skip(user_id, trigger, "row_already_exists")

    resolved_email = str(user_email or _resolve_user_email_for_user_id(user_id) or "").strip()
    if not resolved_email:
        return _skip(user_id, trigger, "missing_user_email")

    try:
        position_result = PositionService(user_email=resolved_email, user_id=user_id).get_all_positions(consolidate=True)
    except Exception:
        _logger.warning("overview auto-seed failed to load positions", exc_info=True)
        return _skip(user_id, trigger, "positions_unavailable")

    summary = build_portfolio_composition_summary(position_result)
    if summary is None:
        total_value = float(getattr(position_result, "total_value", 0.0) or 0.0)
        position_count = int(getattr(position_result, "position_count", 0) or 0)
        if total_value < 1000:
            return _skip(user_id, trigger, "portfolio_too_small")
        if position_count < 3:
            return _skip(user_id, trigger, "too_few_positions")
        return _skip(user_id, trigger, "composition_summary_unavailable")

    started = time.perf_counter()
    try:
        memory = _llm_seed_from_summary(user_id, summary) or _deterministic_seed_from_summary(user_id, summary)
    except Exception:
        _logger.warning("overview auto-seed LLM synthesis failed", exc_info=True)
        memory = _deterministic_seed_from_summary(user_id, summary)
    duration_ms = int((time.perf_counter() - started) * 1000)

    inserted = seed_editorial_memory_if_missing(
        user_id,
        memory,
        log_extra={
            "auto_seed_trigger": trigger,
            "auto_seed_llm_duration_ms": duration_ms,
            "portfolio_name": portfolio_name,
        },
    )
    if not inserted:
        return _skip(user_id, trigger, "row_already_exists")
    return True


__all__ = ["auto_seed_from_portfolio", "build_portfolio_composition_summary"]

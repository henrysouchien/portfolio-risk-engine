"""Persistence helpers for editorial memory and prior brief anchors."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app_platform.logging.core import log_event
from core.overview_editorial.vocabulary import normalize_current_focus, normalize_depth
from database import get_db_session

_logger = logging.getLogger(__name__)
_SEED_PATH = Path(__file__).resolve().parents[2] / "config" / "editorial_memory_seed.json"


def _row_value(row: Any, *, key: str, index: int) -> Any:
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(key)
    try:
        return row[key]
    except Exception:
        try:
            return row[index]
        except Exception:
            return None


def _load_seed_fallback() -> dict[str, Any]:
    try:
        if _SEED_PATH.exists():
            return _normalize_editorial_memory(json.loads(_SEED_PATH.read_text()))
    except Exception:
        _logger.warning("editorial_memory_seed_missing", exc_info=True)
    return {}


def _normalize_editorial_memory(memory: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(memory, dict):
        return {}
    normalized = dict(memory)
    philosophy = normalized.get("briefing_philosophy")
    if isinstance(philosophy, dict):
        normalized_philosophy = dict(philosophy)
        if "depth" in normalized_philosophy:
            normalized_philosophy["depth"] = normalize_depth(normalized_philosophy.get("depth"))
        normalized["briefing_philosophy"] = normalized_philosophy
    return normalized


def load_editorial_state(user_id: int, portfolio_id: str | None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Return editorial memory and prior brief anchor for a portfolio."""

    key = portfolio_id or "default"
    try:
        with get_db_session() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT editorial_memory, previous_briefs FROM user_editorial_state WHERE user_id = %s",
                    (user_id,),
                )
                row = cur.fetchone()
        if row is None:
            return _load_seed_fallback(), None

        editorial_memory = _row_value(row, key="editorial_memory", index=0) or {}
        previous_briefs = _row_value(row, key="previous_briefs", index=1) or {}
        if not isinstance(editorial_memory, dict):
            editorial_memory = {}
        if not isinstance(previous_briefs, dict):
            previous_briefs = {}
        editorial_memory = _normalize_editorial_memory(editorial_memory)

        anchor = previous_briefs.get(key)
        if anchor is not None and not isinstance(anchor, dict):
            anchor = None
        return editorial_memory, anchor
    except Exception:
        _logger.warning("editorial_state_db_miss for user %s", user_id, exc_info=True)
        return _load_seed_fallback(), None


def editorial_state_row_exists(user_id: int) -> bool:
    """Return True when the user has an editorial state row."""

    try:
        with get_db_session() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM user_editorial_state WHERE user_id = %s",
                    (user_id,),
                )
                return cur.fetchone() is not None
    except Exception:
        return False


def set_editorial_memory(
    user_id: int,
    memory: dict[str, Any],
    *,
    source: str = "chat_tool",
) -> dict[str, Any]:
    """Upsert the editorial memory blob for a user."""

    normalized_memory = dict(memory)
    if "current_focus" in normalized_memory:
        normalized_memory["current_focus"] = normalize_current_focus(normalized_memory.get("current_focus"))

    payload = json.dumps(normalized_memory)
    with get_db_session() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_editorial_state (user_id, editorial_memory, updated_at)
                VALUES (%s, %s::jsonb, NOW())
                ON CONFLICT (user_id) DO UPDATE
                  SET editorial_memory = EXCLUDED.editorial_memory,
                      updated_at = NOW()
                """,
                (user_id, payload),
            )
        conn.commit()

    size_bytes = len(payload)
    if size_bytes > 10_240:
        _logger.warning("editorial_memory > 10KB for user %s: %d bytes", user_id, size_bytes)

    _fire_invalidation_callbacks(user_id)
    _logger.info(
        "editorial_memory_updated",
        extra={"user_id": user_id, "source": source, "memory_size_bytes": size_bytes},
    )
    log_event(
        "editorial_memory_updated",
        "Editorial memory updated",
        user_id=user_id,
        source=source,
        memory_size_bytes=size_bytes,
    )
    return normalized_memory


def seed_editorial_memory_if_missing(
    user_id: int,
    seed_memory: dict[str, Any],
    *,
    log_extra: dict[str, Any] | None = None,
) -> bool:
    """Insert seed memory only when the user row does not already exist."""

    normalized_seed_memory = dict(seed_memory)
    if "current_focus" in normalized_seed_memory:
        normalized_seed_memory["current_focus"] = normalize_current_focus(normalized_seed_memory.get("current_focus"))

    payload = json.dumps(normalized_seed_memory)
    with get_db_session() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_editorial_state (user_id, editorial_memory, previous_briefs, updated_at)
                VALUES (%s, %s::jsonb, '{}'::jsonb, NOW())
                ON CONFLICT (user_id) DO NOTHING
                RETURNING user_id
                """,
                (user_id, payload),
            )
            inserted = cur.fetchone() is not None
        conn.commit()

    if inserted:
        _fire_invalidation_callbacks(user_id)
        event: dict[str, Any] = {
            "user_id": user_id,
            "source": "auto_seed",
            "memory_size_bytes": len(payload),
        }
        if log_extra:
            event.update(log_extra)
        _logger.info("editorial_memory_updated", extra=event)
        log_event("editorial_memory_updated", "Editorial memory updated", **event)

    return inserted


def set_previous_brief(user_id: int, portfolio_id: str | None, brief: dict[str, Any]) -> None:
    """Store the latest generated brief as the next diff anchor."""

    key = portfolio_id or "default"
    payload = json.dumps(brief)
    with get_db_session() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_editorial_state (user_id, previous_briefs, updated_at)
                VALUES (%s, jsonb_build_object(%s, %s::jsonb), NOW())
                ON CONFLICT (user_id) DO UPDATE
                  SET previous_briefs = jsonb_set(
                        COALESCE(user_editorial_state.previous_briefs, '{}'::jsonb),
                        ARRAY[%s]::text[],
                        %s::jsonb,
                        true
                      ),
                      updated_at = NOW()
                """,
                (user_id, key, payload, key, payload),
            )
        conn.commit()


def _fire_invalidation_callbacks(user_id: int) -> None:
    """Best-effort invalidation hooks for brief and gateway-memory caches."""

    try:
        from core.overview_editorial.brief_cache import invalidate_brief_cache

        invalidate_brief_cache(user_id)
    except ImportError:
        _logger.debug("brief_cache not available yet")

    try:
        from routes.gateway_proxy import _invalidate_user_memory_cache

        _invalidate_user_memory_cache(user_id)
    except ImportError:
        _logger.debug("gateway memory cache not available yet")


__all__ = [
    "editorial_state_row_exists",
    "load_editorial_state",
    "seed_editorial_memory_if_missing",
    "set_editorial_memory",
    "set_previous_brief",
]

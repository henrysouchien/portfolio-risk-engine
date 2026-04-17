"""Short-lived cache for generated Overview briefs."""

from __future__ import annotations

import copy
import os
import threading
from typing import Any

from cachetools import TTLCache

from models.overview_editorial import OverviewBrief
from services.portfolio.result_cache import clear_result_snapshot_caches

_CACHE_TTL_SECONDS = int(os.getenv("OVERVIEW_BRIEF_TTL_SECONDS", "3600"))
_brief_cache: TTLCache[tuple[int, str], OverviewBrief] = TTLCache(maxsize=256, ttl=_CACHE_TTL_SECONDS)
_cache_lock = threading.Lock()


def _cache_key(user_id: int, portfolio_id: str | None) -> tuple[int, str]:
    return int(user_id), str(portfolio_id or "default")


def get_cached_brief(user_id: int, portfolio_id: str | None) -> OverviewBrief | None:
    key = _cache_key(user_id, portfolio_id)
    with _cache_lock:
        cached = _brief_cache.get(key)
        return copy.deepcopy(cached) if cached is not None else None


def set_cached_brief(user_id: int, portfolio_id: str | None, brief: OverviewBrief) -> None:
    key = _cache_key(user_id, portfolio_id)
    with _cache_lock:
        _brief_cache[key] = copy.deepcopy(brief)


def invalidate_brief_cache(user_id: int) -> int:
    """Evict all cached overview briefs for a user and clear L2 snapshots."""

    evicted = 0
    with _cache_lock:
        for key in list(_brief_cache.keys()):
            if key[0] == int(user_id):
                _brief_cache.pop(key, None)
                evicted += 1
    clear_result_snapshot_caches()
    return evicted


def reset_brief_cache_for_tests() -> None:
    with _cache_lock:
        _brief_cache.clear()


__all__ = [
    "get_cached_brief",
    "invalidate_brief_cache",
    "reset_brief_cache_for_tests",
    "set_cached_brief",
]

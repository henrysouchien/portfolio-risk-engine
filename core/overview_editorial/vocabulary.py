"""Canonical editorial vocabulary used across generators and ranking."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

from models.overview_editorial import RecentAction, UpcomingEvent, WatchEntry

_logger = logging.getLogger(__name__)

CATEGORIES = SimpleNamespace(
    CONCENTRATION="concentration",
    RISK="risk",
    PERFORMANCE="performance",
    LOSS_SCREENING="loss_screening",
    INCOME="income",
    TRADING="trading",
    FACTOR="factor",
    TAX="tax",
    EVENTS="events",
    PORTFOLIO_MIX="portfolio_mix",
)

TAGS = SimpleNamespace(
    RISK_FRAMEWORK_GAPS="risk_framework_gaps",
    CONCENTRATION="concentration",
    PERFORMANCE_VS_BENCHMARK="performance_vs_benchmark",
    INCOME_GENERATION="income_generation",
    UPCOMING_EVENTS="upcoming_events",
    EARNINGS_DATES="earnings_dates",
    DIVIDEND_DATES="dividend_dates",
    NEW_INFORMATION="new_information",
    DAILY_PNL_SWINGS="daily_pnl_swings",
    MOMENTUM_SIGNALS="momentum_signals",
    DETAILED_FACTOR_DECOMPOSITION="detailed_factor_decomposition",
    VARIANCE_ATTRIBUTION="variance_attribution",
)

DEPTH_ENUM = frozenset({"summary", "high_level", "detailed"})
DEPTH_LEVELS: dict[str, int] = {"summary": 2, "high_level": 3, "detailed": 5}
ANNOTATION_TYPE_PRIORITY: dict[str, int] = {"ask_about": 0, "editorial_note": 1, "context": 2}


def normalize_depth(raw: Any) -> str:
    """Collapse legacy or malformed depth values to the supported enum."""

    if not isinstance(raw, str):
        return "high_level"
    text = raw.strip().lower().replace("-", "_")
    return text if text in DEPTH_ENUM else "high_level"


def normalize_current_focus(raw: Any) -> dict[str, Any]:
    """Validate current_focus entries and drop malformed items with WARN logs."""

    if not isinstance(raw, dict):
        return {}

    normalized: dict[str, Any] = {}
    entry_specs = {
        "watching": WatchEntry,
        "recent_actions": RecentAction,
        "upcoming": UpcomingEvent,
    }

    for key, model in entry_specs.items():
        entries = raw.get(key)
        if entries is None:
            continue
        if not isinstance(entries, list):
            _logger.warning("Dropped invalid %s entries: expected list, got %s", key, type(entries).__name__)
            normalized[key] = []
            continue

        validated_entries: list[dict[str, Any]] = []
        for entry in entries:
            try:
                validated_entries.append(model.model_validate(entry).model_dump(mode="json"))
            except Exception:
                _logger.warning("Dropped invalid %s entry: %s", key, entry, exc_info=True)
        normalized[key] = validated_entries

    for key, value in raw.items():
        if key not in entry_specs:
            normalized[key] = value
    return normalized


CONCERN_METRIC_ANCHORS: dict[str, list[str]] = {
    "concentration_risk": ["diversification"],
    "unintended_factor_exposure": ["beta"],
}
MAX_ANCHORED_METRICS = 2


__all__ = [
    "ANNOTATION_TYPE_PRIORITY",
    "CATEGORIES",
    "CONCERN_METRIC_ANCHORS",
    "DEPTH_ENUM",
    "DEPTH_LEVELS",
    "MAX_ANCHORED_METRICS",
    "TAGS",
    "normalize_current_focus",
    "normalize_depth",
]

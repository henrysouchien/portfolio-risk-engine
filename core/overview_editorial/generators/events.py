"""Upcoming portfolio events as persistent attention items."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from core.overview_editorial.context import PortfolioContext
from core.overview_editorial.generators.base import GeneratorOutput
from core.overview_editorial.vocabulary import TAGS
from models.overview_editorial import InsightCandidate, MarginAnnotation

_logger = logging.getLogger(__name__)
_EVENT_PRIORITY = {"earnings": 0, "dividends": 1}


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _parse_date(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if "T" in text:
        text = text.split("T", 1)[0]
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _event_label(event_type: str) -> str:
    return "earnings" if event_type == "earnings" else "ex-dividend"


def _event_countdown(days_until: int) -> str:
    if days_until <= 0:
        return "today"
    if days_until == 1:
        return "tomorrow"
    return f"in {days_until} days"


def _urgency(days_until: int, weight_pct: float) -> tuple[str, float]:
    if days_until <= 2 and weight_pct >= 5.0:
        return "alert", 1.0
    if days_until <= 7 and weight_pct >= 3.0:
        return "act", max(0.6, 1.0 - (days_until * 0.08))
    return "watch", max(0.5, 0.85 - (days_until * 0.05))


def _event_tags(event_type: str) -> list[str]:
    tags = [TAGS.UPCOMING_EVENTS, TAGS.NEW_INFORMATION]
    if event_type == "earnings":
        tags.append(TAGS.EARNINGS_DATES)
    elif event_type == "dividends":
        tags.append(TAGS.DIVIDEND_DATES)
    return tags


class EventsInsightGenerator:
    name = "events"
    source_tool = "events"

    def generate(self, context: PortfolioContext) -> GeneratorOutput:
        try:
            snapshot = context.tool_snapshot("events") or {}
            raw_events = list(snapshot.get("events") or [])
            if not raw_events:
                return GeneratorOutput()

            deduped: dict[str, dict[str, Any]] = {}
            for raw_event in raw_events:
                if not isinstance(raw_event, dict):
                    continue

                ticker = str(raw_event.get("ticker") or "").strip().upper()
                event_type = str(raw_event.get("event_type") or "").strip().lower()
                event_date = _parse_date(raw_event.get("date"))
                days_until = int(raw_event.get("days_until") or 0)
                if (
                    not ticker
                    or event_type not in _EVENT_PRIORITY
                    or event_date is None
                    or days_until < 0
                    or days_until > 7
                ):
                    continue

                current = deduped.get(ticker)
                if current is None:
                    deduped[ticker] = raw_event
                    continue

                current_days = int(current.get("days_until") or 0)
                current_type = str(current.get("event_type") or "").strip().lower()
                if (
                    _EVENT_PRIORITY.get(event_type, 99),
                    days_until,
                    -float(raw_event.get("weight_pct") or 0.0),
                ) < (
                    _EVENT_PRIORITY.get(current_type, 99),
                    current_days,
                    -float(current.get("weight_pct") or 0.0),
                ):
                    deduped[ticker] = raw_event

            ranked_events = sorted(
                deduped.values(),
                key=lambda event: (
                    int(event.get("days_until") or 0),
                    _EVENT_PRIORITY.get(str(event.get("event_type") or ""), 99),
                    -float(event.get("weight_pct") or 0.0),
                    str(event.get("ticker") or ""),
                ),
            )

            candidates: list[InsightCandidate] = []
            annotations: list[MarginAnnotation] = []
            for event in ranked_events[:3]:
                ticker = str(event.get("ticker") or "").strip().upper()
                event_type = str(event.get("event_type") or "").strip().lower()
                weight_pct = float(event.get("weight_pct") or 0.0)
                days_until = int(event.get("days_until") or 0)
                urgency, urgency_score = _urgency(days_until, weight_pct)
                label = _event_label(event_type)
                headline = f"{ticker} {label} {_event_countdown(days_until)}"
                if weight_pct > 0:
                    headline += f" ({weight_pct:.1f}% position)"

                candidates.append(
                    InsightCandidate(
                        slot_type="attention_item",
                        category="events",
                        tags=_event_tags(event_type),
                        content={
                            "category": "events",
                            "headline": headline,
                            "urgency": urgency,
                            "action": {
                                "label": "Review position",
                                "action_type": "navigate",
                                "payload": "holdings",
                            },
                        },
                        relevance_score=min(0.95, max(weight_pct / 10.0, 0.4)),
                        urgency_score=urgency_score,
                        novelty_score=0.8 if days_until <= 3 else 0.5,
                        evidence=[f"{ticker} {label} on {str(event.get('date') or '')}."],
                        why="Near-term portfolio events should persist on the overview until the date passes.",
                        source_tool=self.source_tool,
                    )
                )

                if event_type == "earnings" and weight_pct >= 5.0:
                    annotations.append(
                        MarginAnnotation(
                            anchor_id="lead_insight",
                            type="context",
                            content=f"{ticker} reports earnings {_event_countdown(days_until)} at {weight_pct:.1f}% of the book.",
                        )
                    )

            if ranked_events:
                next_event = ranked_events[0]
                event_type = str(next_event.get("event_type") or "").strip().lower()
                event_date = _parse_date(next_event.get("date"))
                ticker = str(next_event.get("ticker") or "").strip().upper()
                within_week = sum(1 for event in ranked_events if int(event.get("days_until") or 0) <= 7)
                if event_date is not None:
                    if within_week <= 1:
                        metric_value = f"{ticker} {_event_label(event_type)} {event_date.strftime('%a')}"
                    else:
                        metric_value = f"{within_week} events this week"
                    candidates.append(
                        InsightCandidate(
                            slot_type="metric",
                            category="events",
                            tags=[TAGS.UPCOMING_EVENTS],
                            content={
                                "id": "nextEvent",
                                "title": "Next Event",
                                "value": metric_value,
                                "context_label": "7-day calendar",
                                "tone": "neutral",
                                "why_showing": "Calendar pressure is worth a compact slot when portfolio names report soon.",
                            },
                            relevance_score=0.3,
                            urgency_score=0.4,
                            novelty_score=0.5,
                            evidence=[f"Upcoming {event_type} for {ticker} on {str(next_event.get('date') or '')}."],
                            why="The strip can carry one low-priority countdown summary when events cluster.",
                            source_tool=self.source_tool,
                        )
                    )

            return GeneratorOutput(candidates=candidates, annotations=annotations)
        except Exception:
            _logger.warning("events generator failed", exc_info=True)
            return GeneratorOutput()


__all__ = ["EventsInsightGenerator"]

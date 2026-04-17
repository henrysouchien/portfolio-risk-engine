"""Loss-screening attention items for underwater positions."""

from __future__ import annotations

import logging
from typing import Any

from core.overview_editorial.context import PortfolioContext
from core.overview_editorial.generators.base import GeneratorOutput
from models.overview_editorial import InsightCandidate, MarginAnnotation

_logger = logging.getLogger(__name__)


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _format_pct(value: float | None) -> str:
    return f"{value:.0f}%" if value is not None else "an unresolved loss"


def _format_dollar(value: float | None) -> str:
    if value is None:
        return "N/A"
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.0f}"


def _urgency_for_loss(*, pnl_pct: float | None, pnl_dollar: float | None) -> tuple[str, float]:
    if (pnl_pct is not None and pnl_pct <= -30.0) or (pnl_dollar is not None and pnl_dollar <= -5000.0):
        return "alert", 0.95
    if (pnl_pct is not None and pnl_pct <= -15.0) or (pnl_dollar is not None and pnl_dollar <= -2000.0):
        return "act", 0.75
    return "watch", 0.5


class LossScreeningInsightGenerator:
    name = "loss_screening"
    source_tool = "positions"

    def generate(self, context: PortfolioContext) -> GeneratorOutput:
        try:
            snapshot = context.tool_snapshot("positions") or {}
            losses = list(snapshot.get("loss_positions") or [])
            if not losses:
                return GeneratorOutput()

            ranked_losses = sorted(
                [entry for entry in losses if isinstance(entry, dict)],
                key=lambda entry: (
                    _num(entry.get("pnl_usd")) if _num(entry.get("pnl_usd")) is not None else _num(entry.get("pnl_dollar")) or 0.0,
                    str(entry.get("ticker") or ""),
                ),
            )

            candidates: list[InsightCandidate] = []
            annotations: list[MarginAnnotation] = []
            surfaced = 0
            for entry in ranked_losses:
                ticker = str(entry.get("ticker") or "").strip().upper()
                if not ticker:
                    continue

                pnl_pct = _num(entry.get("pnl_pct"))
                pnl_dollar = _num(entry.get("pnl_dollar"))
                pnl_usd = _num(entry.get("pnl_usd"))
                display_dollar = pnl_dollar if pnl_dollar is not None else pnl_usd
                if not (
                    (pnl_pct is not None and pnl_pct <= -10.0)
                    or (display_dollar is not None and display_dollar <= -1000.0)
                ):
                    continue

                urgency, urgency_score = _urgency_for_loss(pnl_pct=pnl_pct, pnl_dollar=display_dollar)
                magnitude = abs(pnl_usd if pnl_usd is not None else display_dollar or 0.0)
                relevance = min(1.0, max(magnitude / 5000.0, 0.5))
                headline = (
                    f"{ticker} is down {_format_pct(pnl_pct)} ({_format_dollar(display_dollar)} unrealized) "
                    "and needs a hold-or-harvest decision."
                )

                candidates.append(
                    InsightCandidate(
                        slot_type="attention_item",
                        category="loss_screening",
                        content={
                            "category": "loss_screening",
                            "headline": headline,
                            "urgency": urgency,
                            "action": {
                                "label": "Check exit signals",
                                "action_type": "chat_prompt",
                                "payload": f"Check exit signals for {ticker}.",
                            },
                        },
                        relevance_score=relevance,
                        urgency_score=urgency_score,
                        novelty_score=0.7,
                        evidence=[
                            f"{ticker} unrealized P&L: {_format_dollar(display_dollar)}.",
                            f"{ticker} return from cost basis: {_format_pct(pnl_pct)}." if pnl_pct is not None else "Loss remains unresolved.",
                        ],
                        why="Large unrealized losses should persist as attention items until the user makes an explicit decision.",
                        source_tool=self.source_tool,
                    )
                )

                if surfaced < 2:
                    harvest_tail = (
                        " Should I harvest the tax loss or hold?"
                        if display_dollar is not None and display_dollar <= -1000.0
                        else ""
                    )
                    annotations.append(
                        MarginAnnotation(
                            anchor_id="artifact.overview.concentration",
                            type="ask_about",
                            content=f"Ask whether the {ticker} thesis still holds at {_format_pct(pnl_pct)}.",
                            prompt=(
                                f"Walk me through whether {ticker} still makes sense at "
                                f"{_format_pct(pnl_pct)}.{harvest_tail}"
                            ),
                        )
                    )
                surfaced += 1
                if surfaced >= 3:
                    break

            return GeneratorOutput(candidates=candidates, annotations=annotations)
        except Exception:
            _logger.warning("loss screening generator failed", exc_info=True)
            return GeneratorOutput()


__all__ = ["LossScreeningInsightGenerator"]

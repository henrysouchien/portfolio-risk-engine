"""Concentration-oriented insight candidates."""

from __future__ import annotations

import logging
from typing import Any

from core.overview_editorial.context import PortfolioContext
from core.overview_editorial.generators.base import GeneratorOutput
from core.overview_editorial.vocabulary import TAGS
from models.overview_editorial import ArtifactDirective, InsightCandidate, MarginAnnotation

_logger = logging.getLogger(__name__)


def _pct(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


class ConcentrationInsightGenerator:
    name = "concentration"
    source_tool = "positions"

    def generate(self, context: PortfolioContext) -> GeneratorOutput:
        try:
            snapshot = context.tool_snapshot("positions") or {}
            holdings = list(snapshot.get("holdings") or [])
            if not holdings:
                return GeneratorOutput()

            top = holdings[0]
            top_ticker = str(top.get("ticker") or "Top holding")
            top_weight = _pct(top.get("weight_pct"))
            hhi = _pct(snapshot.get("hhi"))
            position_count = int(snapshot.get("position_count") or 0)

            candidates: list[InsightCandidate] = []
            directives: list[ArtifactDirective] = []
            annotations: list[MarginAnnotation] = []

            if top_weight is not None:
                candidates.append(
                    InsightCandidate(
                        slot_type="lead_insight",
                        category="concentration",
                        tags=[TAGS.CONCENTRATION],
                        content={
                            "headline": (
                                f"{top_ticker} is still doing outsized work in the book at {top_weight:.1f}% "
                                "of exposure."
                                if top_weight >= 15
                                else f"{top_ticker} remains the biggest single line item at {top_weight:.1f}% of exposure."
                            ),
                            "exit_ramps": [
                                {
                                    "label": "Review holdings",
                                    "action_type": "navigate",
                                    "payload": "holdings",
                                },
                                {
                                    "label": "Open rebalance tool",
                                    "action_type": "navigate",
                                    "payload": "scenario:rebalance",
                                },
                            ],
                        },
                        relevance_score=min(1.0, max(top_weight / 25.0, 0.4)),
                        urgency_score=0.9 if top_weight >= 20 else 0.5,
                        novelty_score=0.55,
                        evidence=[f"Lead holding: {top_ticker} at {top_weight:.1f}%."],
                        why="The largest position usually determines whether the book feels diversified or fragile.",
                        source_tool=self.source_tool,
                    )
                )

                if top_weight >= 15:
                    candidates.append(
                        InsightCandidate(
                            slot_type="attention_item",
                            category="concentration",
                            tags=[TAGS.CONCENTRATION],
                            content={
                                "category": "concentration",
                                "headline": f"{top_ticker} is large enough to dominate the next drawdown.",
                                "urgency": "alert" if top_weight >= 20 else "act",
                                "action": {
                                    "label": "Check concentration table",
                                    "action_type": "navigate",
                                    "payload": "holdings",
                                },
                            },
                            relevance_score=0.9,
                            urgency_score=1.0 if top_weight >= 20 else 0.7,
                            novelty_score=0.6,
                            evidence=[f"{top_ticker} weight is {top_weight:.1f}%."],
                            why="Oversized single-name exposure deserves a specific callout.",
                            source_tool=self.source_tool,
                        )
                    )

                    directives.append(
                        ArtifactDirective(
                            artifact_id="overview.concentration",
                            position=10,
                            visible=True,
                            annotation=f"Start with {top_ticker}; it is still the obvious concentration question.",
                            highlight_ids=[top_ticker],
                        )
                    )

                    annotations.append(
                        MarginAnnotation(
                            anchor_id="artifact.overview.concentration",
                            type="ask_about",
                            content=f"Ask whether {top_ticker} is still earning its size.",
                            prompt=f"Walk me through whether {top_ticker} still deserves to be {top_weight:.1f}% of the book.",
                        )
                    )

            if hhi is not None:
                candidates.append(
                    InsightCandidate(
                        slot_type="metric",
                        category="concentration",
                        tags=[TAGS.CONCENTRATION],
                        content={
                            "id": "diversification",
                            "title": "Diversification",
                            "value": f"{position_count} holdings",
                            "context_label": f"HHI {hhi:.3f}",
                            "tone": "neutral" if position_count >= 10 else "down",
                            "why_showing": "Position breadth gives context for whether the lead line sits inside a deep book or a short stack.",
                        },
                        relevance_score=0.45,
                        urgency_score=0.3 if position_count >= 10 else 0.55,
                        novelty_score=0.4,
                        evidence=[f"Position count: {position_count}.", f"HHI: {hhi:.3f}."],
                        why="Breadth is the quickest check on whether concentration is isolated or structural.",
                        source_tool=self.source_tool,
                    )
                )

            return GeneratorOutput(
                candidates=candidates,
                directives=directives,
                annotations=annotations,
            )
        except Exception:
            _logger.warning("concentration generator failed", exc_info=True)
            return GeneratorOutput()

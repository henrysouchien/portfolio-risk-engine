"""Trading-oriented insight candidates."""

from __future__ import annotations

import logging
from typing import Any

from core.overview_editorial.context import PortfolioContext
from core.overview_editorial.generators.base import GeneratorOutput
from models.overview_editorial import InsightCandidate, MarginAnnotation

_logger = logging.getLogger(__name__)
_GOOD_GRADES = {"A+", "A", "A-", "B+", "B", "B-"}
_POOR_GRADES = {"D+", "D", "D-", "F"}


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


class TradingInsightGenerator:
    name = "trading"
    source_tool = "trading"

    def generate(self, context: PortfolioContext) -> GeneratorOutput:
        try:
            snapshot = context.tool_snapshot("trading") or {}
            if not snapshot:
                return GeneratorOutput()

            trades = snapshot.get("trades") if isinstance(snapshot.get("trades"), dict) else {}
            grades = snapshot.get("grades") if isinstance(snapshot.get("grades"), dict) else {}
            behavioral = snapshot.get("behavioral") if isinstance(snapshot.get("behavioral"), dict) else {}

            total_trades = int(trades.get("total") or 0)
            win_rate = _num(trades.get("win_rate_pct"))
            overall_grade = str(grades.get("overall") or "").strip().upper()
            edge_grade = str(grades.get("edge") or "").strip().upper()
            revenge_trade_count = int(behavioral.get("revenge_trade_count") or 0)

            candidates: list[InsightCandidate] = []
            annotations: list[MarginAnnotation] = []

            if total_trades >= 5 and win_rate is not None:
                candidates.append(
                    InsightCandidate(
                        slot_type="metric",
                        category="trading",
                        content={
                            "id": "winRate",
                            "title": "Win Rate",
                            "value": f"{win_rate:.0f}%",
                            "tone": "up" if win_rate >= 55 else "down" if win_rate < 45 else "neutral",
                            "why_showing": "Win rate is the quickest top-line read on whether recent trade selection is still working.",
                        },
                        relevance_score=min(1.0, max(total_trades / 20.0, 0.35)),
                        urgency_score=0.75 if win_rate < 45 else 0.35,
                        novelty_score=0.5,
                        evidence=[f"Win rate across {total_trades} trades: {win_rate:.1f}%."],
                        why="Recent trade quality should show up in the strip once there is a real sample.",
                        source_tool=self.source_tool,
                    )
                )

            if edge_grade and edge_grade != "N/A":
                candidates.append(
                    InsightCandidate(
                        slot_type="metric",
                        category="trading",
                        content={
                            "id": "edgeScore",
                            "title": "Edge Score",
                            "value": edge_grade,
                            "tone": "up" if edge_grade in _GOOD_GRADES else "down" if edge_grade in _POOR_GRADES else "neutral",
                            "why_showing": "Edge grade collapses a larger trade-quality read into a single front-page signal.",
                        },
                        relevance_score=min(1.0, max(total_trades / 18.0, 0.3)),
                        urgency_score=0.7 if edge_grade in _POOR_GRADES else 0.3,
                        novelty_score=0.45,
                        evidence=[f"Edge grade: {edge_grade}."],
                        why="Edge grade is a compact read on whether the process is improving or slipping.",
                        source_tool=self.source_tool,
                    )
                )

            if total_trades >= 10 and overall_grade:
                if overall_grade in _GOOD_GRADES:
                    candidates.append(
                        InsightCandidate(
                            slot_type="lead_insight",
                            category="trading",
                            content={
                                "headline": "Trading edge has improved enough to matter.",
                                "exit_ramps": [
                                    {"label": "Open trading analysis", "action_type": "navigate", "payload": "trading"},
                                    {
                                        "label": "Review best trades",
                                        "action_type": "chat_prompt",
                                        "payload": "Walk me through what the best recent trades have in common.",
                                    },
                                ],
                            },
                            relevance_score=0.76,
                            urgency_score=0.55,
                            novelty_score=0.55,
                            evidence=[
                                f"Overall grade: {overall_grade}.",
                                f"Trade sample: {total_trades}.",
                            ],
                            why="A sustained improvement in trading quality deserves explicit front-page reinforcement.",
                            source_tool=self.source_tool,
                        )
                    )
                elif overall_grade in _POOR_GRADES:
                    candidates.append(
                        InsightCandidate(
                            slot_type="lead_insight",
                            category="trading",
                            content={
                                "headline": "Trading quality is deteriorating and needs review.",
                                "exit_ramps": [
                                    {"label": "Open trading analysis", "action_type": "navigate", "payload": "trading"},
                                    {
                                        "label": "Review worst trades",
                                        "action_type": "chat_prompt",
                                        "payload": "Walk me through the recent trading mistakes and whether they are repeating.",
                                    },
                                ],
                            },
                            relevance_score=0.84,
                            urgency_score=0.82,
                            novelty_score=0.55,
                            evidence=[
                                f"Overall grade: {overall_grade}.",
                                f"Trade sample: {total_trades}.",
                            ],
                            why="Poor trading quality across a real sample should compete for the lead slot.",
                            source_tool=self.source_tool,
                        )
                    )

            if revenge_trade_count > 0:
                candidates.append(
                    InsightCandidate(
                        slot_type="attention_item",
                        category="trading",
                        content={
                            "category": "trading",
                            "headline": f"Revenge trading showed up in {revenge_trade_count} recent trade{'s' if revenge_trade_count != 1 else ''}.",
                            "urgency": "alert",
                            "action": {
                                "label": "Inspect behavior",
                                "action_type": "navigate",
                                "payload": "trading",
                            },
                        },
                        relevance_score=0.92,
                        urgency_score=0.96,
                        novelty_score=0.5,
                        evidence=[f"Revenge-trade count: {revenge_trade_count}."],
                        why="Behavioral breakdowns should surface as explicit attention items.",
                        source_tool=self.source_tool,
                    )
                )

            if total_trades >= 10 and overall_grade in _POOR_GRADES:
                candidates.append(
                    InsightCandidate(
                        slot_type="attention_item",
                        category="trading",
                        content={
                            "category": "trading",
                            "headline": f"Trading edge is grading {overall_grade} across the recent sample.",
                            "urgency": "act",
                            "action": {
                                "label": "Review scorecard",
                                "action_type": "navigate",
                                "payload": "trading",
                            },
                        },
                        relevance_score=0.88,
                        urgency_score=0.86,
                        novelty_score=0.45,
                        evidence=[f"Overall trading grade: {overall_grade}."],
                        why="Poor overall trade quality should remain actionable until the pattern changes.",
                        source_tool=self.source_tool,
                    )
                )

            if total_trades > 0:
                annotations.append(
                    MarginAnnotation(
                        anchor_id="lead_insight",
                        type="editorial_note",
                        content="Review recent trade quality before assuming portfolio-level results are all allocation-driven.",
                    )
                )

            return GeneratorOutput(candidates=candidates, annotations=annotations)
        except Exception:
            _logger.warning("trading generator failed", exc_info=True)
            return GeneratorOutput()


__all__ = ["TradingInsightGenerator"]

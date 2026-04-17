"""Tax-harvest oriented insight candidates."""

from __future__ import annotations

import logging

from core.overview_editorial.context import PortfolioContext
from core.overview_editorial.generators.base import GeneratorOutput
from models.overview_editorial import InsightCandidate, MarginAnnotation

_logger = logging.getLogger(__name__)


def _format_money(value: float) -> str:
    return f"${abs(value):,.0f}"


class TaxHarvestInsightGenerator:
    name = "tax_harvest"
    source_tool = "tax"

    def generate(self, context: PortfolioContext) -> GeneratorOutput:
        try:
            snapshot = context.tool_snapshot("tax") or {}
            if not snapshot:
                return GeneratorOutput()

            total_loss = float(snapshot.get("total_harvestable_loss") or 0.0)
            candidate_count = int(snapshot.get("candidate_count") or 0)
            top_candidates = [candidate for candidate in list(snapshot.get("top_candidates") or []) if isinstance(candidate, dict)]
            position_count = len(top_candidates) or candidate_count
            wash_sale_ticker_count = int(snapshot.get("wash_sale_ticker_count") or 0)
            wash_sale_tickers = [
                str(ticker or "").strip().upper()
                for ticker in list(snapshot.get("wash_sale_tickers") or [])
                if str(ticker or "").strip()
            ]
            absolute_loss = abs(total_loss)
            q4 = context.generated_at.month >= 10

            candidates: list[InsightCandidate] = []
            annotations: list[MarginAnnotation] = []

            if absolute_loss > 0:
                candidates.append(
                    InsightCandidate(
                        slot_type="metric",
                        category="tax",
                        content={
                            "id": "harvestableLosses",
                            "title": "Harvestable Losses",
                            "value": _format_money(total_loss),
                            "tone": "down" if absolute_loss >= 1000 else "neutral",
                            "why_showing": "Harvestable losses turn unrealized drawdowns into a concrete tax-planning choice.",
                        },
                        relevance_score=min(1.0, max(absolute_loss / 6000.0, 0.35)),
                        urgency_score=0.8 if absolute_loss >= 5000 else 0.45,
                        novelty_score=0.55,
                        evidence=[f"Estimated harvestable losses: {_format_money(total_loss)}."],
                        why="Tax-loss capacity is a real portfolio lever once losses become material.",
                        source_tool=self.source_tool,
                    )
                )

            if position_count > 0:
                candidates.append(
                    InsightCandidate(
                        slot_type="metric",
                        category="tax",
                        content={
                            "id": "harvestCandidates",
                            "title": "Harvest Candidates",
                            "value": f"{position_count} positions",
                            "tone": "neutral",
                            "why_showing": "Candidate count distinguishes a single tactical clean-up from a broader tax-management pass.",
                        },
                        relevance_score=min(1.0, max(position_count / 6.0, 0.3)),
                        urgency_score=0.75 if position_count >= 4 else 0.35,
                        novelty_score=0.45,
                        evidence=[f"Harvest candidates: {candidate_count} lots across {position_count} positions."],
                        why="Tax opportunity size should be visible as both dollars and breadth.",
                        source_tool=self.source_tool,
                    )
                )

            lead_headline = None
            lead_urgency = 0.0
            if absolute_loss >= 1000 and position_count > 0 and q4:
                lead_headline = f"Tax deadline is approaching with {_format_money(total_loss)} in harvestable losses still open."
                lead_urgency = 0.86
            elif absolute_loss >= 1000 and position_count >= 3:
                lead_headline = f"{position_count} positions have {_format_money(total_loss)} in harvestable losses."
                lead_urgency = 0.72

            if lead_headline is not None:
                candidates.append(
                    InsightCandidate(
                        slot_type="lead_insight",
                        category="tax",
                        content={
                            "headline": lead_headline,
                            "exit_ramps": [
                                {"label": "Run tax harvest scan", "action_type": "navigate", "payload": "scenario:tax-harvest"},
                                {
                                    "label": "Review wash sale risk",
                                    "action_type": "chat_prompt",
                                    "payload": "Walk me through which tax-loss harvest candidates are actionable without triggering wash sale issues.",
                                },
                            ],
                        },
                        relevance_score=0.8,
                        urgency_score=lead_urgency,
                        novelty_score=0.55,
                        evidence=[
                            f"Harvestable losses: {_format_money(total_loss)}.",
                            f"Candidate breadth: {position_count} positions.",
                        ],
                        why="Once losses are material across multiple positions, tax management deserves front-page space.",
                        source_tool=self.source_tool,
                    )
                )

            if wash_sale_ticker_count > 0:
                headline = f"Wash sale risk is open on {wash_sale_ticker_count} ticker{'s' if wash_sale_ticker_count != 1 else ''}."
                if wash_sale_tickers:
                    headline = (
                        f"Wash sale risk is open on {', '.join(wash_sale_tickers[:3])}"
                        f"{' and others' if len(wash_sale_tickers) > 3 else ''}."
                    )
                candidates.append(
                    InsightCandidate(
                        slot_type="attention_item",
                        category="tax",
                        content={
                            "category": "tax",
                            "headline": headline,
                            "urgency": "act",
                            "action": {
                                "label": "Open tax harvest",
                                "action_type": "navigate",
                                "payload": "scenario:tax-harvest",
                            },
                        },
                        relevance_score=0.88,
                        urgency_score=0.92,
                        novelty_score=0.5,
                        evidence=[f"Wash sale warnings on {wash_sale_ticker_count} ticker(s)."],
                        why="Wash sale constraints can turn a good-looking harvest into a bad execution decision.",
                        source_tool=self.source_tool,
                    )
                )

            if absolute_loss >= 5000:
                candidates.append(
                    InsightCandidate(
                        slot_type="attention_item",
                        category="tax",
                        content={
                            "category": "tax",
                            "headline": f"{_format_money(total_loss)} of harvestable losses are available right now.",
                            "urgency": "act",
                            "action": {
                                "label": "Review candidates",
                                "action_type": "navigate",
                                "payload": "scenario:tax-harvest",
                            },
                        },
                        relevance_score=0.9,
                        urgency_score=0.85 if not q4 else 0.95,
                        novelty_score=0.48,
                        evidence=[f"Large harvest opportunity: {_format_money(total_loss)}."],
                        why="Large harvest windows should persist as explicit action items until resolved.",
                        source_tool=self.source_tool,
                    )
                )

            if absolute_loss > 0:
                annotations.append(
                    MarginAnnotation(
                        anchor_id="lead_insight",
                        type="editorial_note",
                        content="Review tax-harvest opportunities before making replacement-position decisions.",
                    )
                )

            return GeneratorOutput(candidates=candidates, annotations=annotations)
        except Exception:
            _logger.warning("tax harvest generator failed", exc_info=True)
            return GeneratorOutput()


__all__ = ["TaxHarvestInsightGenerator"]

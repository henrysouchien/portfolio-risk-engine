"""Income-oriented insight candidates."""

from __future__ import annotations

from datetime import date, datetime
import logging
from typing import Any

from core.overview_editorial.context import PortfolioContext
from core.overview_editorial.generators.base import GeneratorOutput
from core.overview_editorial.vocabulary import TAGS
from models.overview_editorial import ArtifactDirective, InsightCandidate, MarginAnnotation

_logger = logging.getLogger(__name__)


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    if "T" in text:
        text = text.split("T", 1)[0]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _days_until(context: PortfolioContext, ex_date: date | None) -> int | None:
    if ex_date is None:
        return None
    return (ex_date - context.generated_at.date()).days


class IncomeInsightGenerator:
    name = "income"
    source_tool = "income"

    def generate(self, context: PortfolioContext) -> GeneratorOutput:
        try:
            snapshot = context.tool_snapshot("income") or {}
            if not snapshot or snapshot.get("status") != "success":
                return GeneratorOutput()

            annual_income = _num(snapshot.get("annual_income")) or 0.0
            yield_on_value = _num(snapshot.get("portfolio_yield_on_value")) or 0.0
            income_holding_count = int(snapshot.get("income_holding_count") or 0)
            warning_count = int(snapshot.get("warning_count") or 0)
            warnings = [str(item).strip() for item in list(snapshot.get("warnings") or []) if str(item).strip()]
            upcoming_dividends = [item for item in list(snapshot.get("upcoming_dividends") or []) if isinstance(item, dict)]

            candidates: list[InsightCandidate] = []
            directives: list[ArtifactDirective] = []
            annotations: list[MarginAnnotation] = []

            if annual_income > 0:
                candidates.append(
                    InsightCandidate(
                        slot_type="metric",
                        category="income",
                        tags=[TAGS.INCOME_GENERATION],
                        content={
                            "id": "portfolioYield",
                            "title": "Portfolio Yield",
                            "value": f"{yield_on_value:.1f}%",
                            "context_label": f"${annual_income:,.0f}/yr",
                            "tone": "up" if yield_on_value >= 2.0 else "neutral",
                            "why_showing": "Income progress is one of the clearest checks that the portfolio is paying you while you wait.",
                        },
                        relevance_score=min(1.0, max(yield_on_value / 5.0, 0.4)),
                        urgency_score=0.3,
                        novelty_score=0.45,
                        evidence=[f"Projected annual income: ${annual_income:,.0f}.", f"Yield on value: {yield_on_value:.1f}%."],
                        why="Portfolio income belongs on the strip when it is material enough to matter.",
                        source_tool=self.source_tool,
                    )
                )

            next_dividend = upcoming_dividends[0] if upcoming_dividends else None
            if next_dividend is not None:
                ticker = str(next_dividend.get("ticker") or "").strip().upper() or "Next dividend"
                ex_date = _parse_date(next_dividend.get("ex_date"))
                ex_date_label = ex_date.strftime("%b %-d") if ex_date is not None else str(next_dividend.get("ex_date") or "")
                amount = _num(next_dividend.get("amount"))
                context_label = f"${amount:.2f}/share" if amount is not None else "ex-date"
                candidates.append(
                    InsightCandidate(
                        slot_type="metric",
                        category="income",
                        tags=[TAGS.INCOME_GENERATION],
                        content={
                            "id": "nextDividend",
                            "title": "Next Dividend",
                            "value": f"{ticker} {ex_date_label}".strip(),
                            "context_label": context_label,
                            "tone": "neutral",
                            "why_showing": "The next dividend date gives the income stream a concrete near-term checkpoint.",
                        },
                        relevance_score=0.4,
                        urgency_score=0.45,
                        novelty_score=0.55,
                        evidence=[f"Next dividend: {ticker} ex-date {str(next_dividend.get('ex_date') or 'unknown')}."],
                        why="A near-term dividend checkpoint is a compact way to keep income tangible.",
                        source_tool=self.source_tool,
                    )
                )

            if warning_count > 0:
                candidates.append(
                    InsightCandidate(
                        slot_type="lead_insight",
                        category="income",
                        tags=[TAGS.INCOME_GENERATION],
                        content={
                            "headline": (
                                f"Income needs a quality check: {warning_count} dividend warning"
                                f"{'' if warning_count == 1 else 's'} are active."
                            ),
                            "exit_ramps": [
                                {"label": "Open income view", "action_type": "navigate", "payload": "income"},
                                {"label": "Review payers", "action_type": "navigate", "payload": "holdings"},
                            ],
                        },
                        relevance_score=0.8,
                        urgency_score=0.75,
                        novelty_score=0.55,
                        evidence=warnings[:2] or ["Dividend warnings are active."],
                        why="Income warnings should override routine yield celebration.",
                        source_tool=self.source_tool,
                    )
                )
            elif annual_income > 0 and income_holding_count >= 3:
                candidates.append(
                    InsightCandidate(
                        slot_type="lead_insight",
                        category="income",
                        tags=[TAGS.INCOME_GENERATION],
                        content={
                            "headline": f"The book is on pace for about ${annual_income:,.0f} of annual dividend income.",
                            "exit_ramps": [
                                {"label": "Open income view", "action_type": "navigate", "payload": "income"},
                                {"label": "Review contributors", "action_type": "navigate", "payload": "holdings"},
                            ],
                        },
                        relevance_score=min(1.0, max(annual_income / 10000.0, 0.55)),
                        urgency_score=0.35,
                        novelty_score=0.45,
                        evidence=[f"{income_holding_count} positions contribute dividend income.", f"Projected annual income: ${annual_income:,.0f}."],
                        why="Material dividend income deserves a plain-English front-page read.",
                        source_tool=self.source_tool,
                    )
                )

            if next_dividend is not None:
                ticker = str(next_dividend.get("ticker") or "").strip().upper() or "A position"
                ex_date = _parse_date(next_dividend.get("ex_date"))
                days = _days_until(context, ex_date)
                if days is not None and 0 <= days <= 7:
                    headline = f"{ticker} goes ex-dividend {'today' if days == 0 else f'in {days} day' if days == 1 else f'in {days} days'}."
                    candidates.append(
                        InsightCandidate(
                            slot_type="attention_item",
                            category="income",
                            tags=[TAGS.INCOME_GENERATION],
                            content={
                                "category": "income",
                                "headline": headline,
                                "urgency": "act" if days <= 7 else "watch",
                                "action": {
                                    "label": "Review dividend calendar",
                                    "action_type": "navigate",
                                    "payload": "income",
                                },
                            },
                            relevance_score=0.7,
                            urgency_score=0.7 if days <= 3 else 0.55,
                            novelty_score=0.7,
                            evidence=[f"Next dividend ex-date: {ticker} on {ex_date.isoformat()}."],
                            why="A nearby dividend date is worth explicit attention while it is still actionable.",
                            source_tool=self.source_tool,
                        )
                    )

            if warnings:
                candidates.append(
                    InsightCandidate(
                        slot_type="attention_item",
                        category="income",
                        tags=[TAGS.INCOME_GENERATION],
                        content={
                            "category": "income",
                            "headline": warnings[0],
                            "urgency": "watch",
                            "action": {
                                "label": "Inspect income warnings",
                                "action_type": "navigate",
                                "payload": "income",
                            },
                        },
                        relevance_score=0.65,
                        urgency_score=0.55,
                        novelty_score=0.55,
                        evidence=warnings[:2],
                        why="Dividend warnings should persist until the user inspects the payer quality.",
                        source_tool=self.source_tool,
                    )
                )

            if annual_income > 0 and yield_on_value >= 2.0:
                directives.append(
                    ArtifactDirective(
                        artifact_id="overview.income_projection",
                        position=40,
                        visible=True,
                        annotation="Income is material enough to keep alongside risk and performance.",
                    )
                )
                annotations.append(
                    MarginAnnotation(
                        anchor_id="artifact.overview.income_projection",
                        type="ask_about",
                        content="Ask whether the current income stream is durable enough to count on.",
                        prompt="Walk me through whether the current dividend income stream looks durable.",
                    )
                )

            return GeneratorOutput(candidates=candidates, directives=directives, annotations=annotations)
        except Exception:
            _logger.warning("income generator failed", exc_info=True)
            return GeneratorOutput()


__all__ = ["IncomeInsightGenerator"]

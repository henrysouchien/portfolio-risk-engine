"""Factor-oriented insight candidates."""

from __future__ import annotations

import logging
from typing import Any

from core.overview_editorial.context import PortfolioContext
from core.overview_editorial.generators.base import GeneratorOutput
from core.overview_editorial.vocabulary import TAGS
from models.overview_editorial import InsightCandidate, MarginAnnotation

_logger = logging.getLogger(__name__)


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _factor_label(name: str | None) -> str:
    text = str(name or "").strip().replace("_", " ")
    return text.title() if text else "Factor"


class FactorInsightGenerator:
    name = "factor"
    source_tool = "factor"

    def generate(self, context: PortfolioContext) -> GeneratorOutput:
        try:
            snapshot = context.tool_snapshot("factor") or {}
            if not snapshot:
                return GeneratorOutput()

            dominant_factor = str(snapshot.get("dominant_factor") or "").strip().lower()
            dominant_factor_pct = _num(snapshot.get("dominant_factor_pct"))
            concentration_score = _num(snapshot.get("factor_concentration_score"))
            factor_variance_pct = _num(snapshot.get("factor_variance_pct"))
            factor_betas = snapshot.get("portfolio_factor_betas") if isinstance(snapshot.get("portfolio_factor_betas"), dict) else {}
            violations = list(snapshot.get("beta_exposure_violations") or [])

            candidates: list[InsightCandidate] = []
            annotations: list[MarginAnnotation] = []

            if dominant_factor and dominant_factor_pct is not None:
                candidates.append(
                    InsightCandidate(
                        slot_type="metric",
                        category="factor",
                        tags=[TAGS.DETAILED_FACTOR_DECOMPOSITION, TAGS.VARIANCE_ATTRIBUTION],
                        content={
                            "id": "dominantFactor",
                            "title": "Dominant Factor",
                            "value": f"{_factor_label(dominant_factor)} {dominant_factor_pct:.0f}%",
                            "tone": "down" if dominant_factor_pct >= 40 else "neutral",
                            "why_showing": "Factor dominance is the fastest way to see whether one macro bet is doing too much of the work.",
                        },
                        relevance_score=min(1.0, max(dominant_factor_pct / 55.0, 0.35)),
                        urgency_score=0.8 if dominant_factor_pct >= 50 else 0.45,
                        novelty_score=0.5,
                        evidence=[f"{_factor_label(dominant_factor)} is {dominant_factor_pct:.1f}% of portfolio risk."],
                        why="Factor detail should surface once one exposure starts dominating the risk stack.",
                        source_tool=self.source_tool,
                    )
                )

            if concentration_score is not None and concentration_score > 0:
                candidates.append(
                    InsightCandidate(
                        slot_type="metric",
                        category="factor",
                        tags=[TAGS.DETAILED_FACTOR_DECOMPOSITION, TAGS.VARIANCE_ATTRIBUTION],
                        content={
                            "id": "factorConcentration",
                            "title": "Factor Concentration",
                            "value": f"{concentration_score:.2f}",
                            "tone": "down" if concentration_score >= 0.20 else "neutral",
                            "why_showing": "Factor concentration shows whether the risk stack is broad or quietly collapsing into one theme.",
                        },
                        relevance_score=min(1.0, max(concentration_score / 0.3, 0.3)),
                        urgency_score=0.7 if concentration_score >= 0.20 else 0.35,
                        novelty_score=0.45,
                        evidence=[f"Factor concentration score: {concentration_score:.2f}."],
                        why="Factor concentration complements raw risk by showing whether the bet set is narrow.",
                        source_tool=self.source_tool,
                    )
                )

            strongest_non_market = None
            strongest_non_market_beta = None
            if isinstance(factor_betas, dict):
                for factor_name, raw_beta in factor_betas.items():
                    factor_key = str(factor_name or "").strip().lower()
                    if not factor_key or factor_key == "market":
                        continue
                    beta = _num(raw_beta)
                    if beta is None or abs(beta) < 0.30:
                        continue
                    if strongest_non_market_beta is None or abs(beta) > abs(strongest_non_market_beta):
                        strongest_non_market = factor_key
                        strongest_non_market_beta = beta

            lead_headline = None
            lead_evidence: list[str] = []
            lead_urgency = 0.0
            if strongest_non_market and strongest_non_market_beta is not None:
                lead_headline = (
                    f"Unintended {_factor_label(strongest_non_market)} tilt detected at "
                    f"{strongest_non_market_beta:+.2f} beta."
                )
                lead_evidence.append(
                    f"{_factor_label(strongest_non_market)} beta: {strongest_non_market_beta:+.2f}."
                )
                lead_urgency = 0.8
            elif dominant_factor and dominant_factor_pct is not None and dominant_factor_pct >= 40:
                lead_headline = f"{_factor_label(dominant_factor)} is {dominant_factor_pct:.0f}% of portfolio risk. Is that intentional?"
                lead_evidence.append(f"{_factor_label(dominant_factor)} share of risk: {dominant_factor_pct:.1f}%.")
                lead_urgency = 0.72

            if lead_headline is not None:
                if factor_variance_pct is not None:
                    lead_evidence.append(f"Factor variance share: {factor_variance_pct:.1f}%.")
                candidates.append(
                    InsightCandidate(
                        slot_type="lead_insight",
                        category="factor",
                        tags=[TAGS.DETAILED_FACTOR_DECOMPOSITION, TAGS.VARIANCE_ATTRIBUTION],
                        content={
                            "headline": lead_headline,
                            "exit_ramps": [
                                {"label": "Open risk view", "action_type": "navigate", "payload": "risk"},
                                {
                                    "label": "Explain the tilt",
                                    "action_type": "chat_prompt",
                                    "payload": "Walk me through whether these factor exposures are intentional.",
                                },
                            ],
                        },
                        relevance_score=0.78,
                        urgency_score=lead_urgency,
                        novelty_score=0.55,
                        evidence=lead_evidence,
                        why="Material factor tilts deserve a front-page explanation instead of hiding inside the risk report.",
                        source_tool=self.source_tool,
                    )
                )

            if violations:
                first = violations[0] if isinstance(violations[0], dict) else {}
                factor_name = _factor_label(first.get("factor"))
                beta = _num(first.get("portfolio_beta"))
                limit = _num(first.get("max_allowed_beta"))
                headline = f"{factor_name} beta is outside the configured limit."
                if beta is not None and limit is not None:
                    headline = f"{factor_name} beta is {beta:+.2f} versus a {limit:.2f} limit."
                candidates.append(
                    InsightCandidate(
                        slot_type="attention_item",
                        category="factor",
                        tags=[TAGS.DETAILED_FACTOR_DECOMPOSITION, TAGS.RISK_FRAMEWORK_GAPS],
                        content={
                            "category": "factor",
                            "headline": headline,
                            "urgency": "alert",
                            "action": {
                                "label": "Inspect factor checks",
                                "action_type": "navigate",
                                "payload": "risk",
                            },
                        },
                        relevance_score=0.92,
                        urgency_score=1.0,
                        novelty_score=0.55,
                        evidence=[f"Detected {len(violations)} factor beta limit issue(s)."],
                        why="Explicit beta-limit breaks should surface as hard attention items.",
                        source_tool=self.source_tool,
                    )
                )

            if dominant_factor and dominant_factor_pct is not None and dominant_factor_pct >= 50:
                candidates.append(
                    InsightCandidate(
                        slot_type="attention_item",
                        category="factor",
                        tags=[TAGS.DETAILED_FACTOR_DECOMPOSITION, TAGS.VARIANCE_ATTRIBUTION],
                        content={
                            "category": "factor",
                            "headline": f"{_factor_label(dominant_factor)} is dominating the risk stack at {dominant_factor_pct:.0f}%.",
                            "urgency": "act",
                            "action": {
                                "label": "Review exposures",
                                "action_type": "navigate",
                                "payload": "risk",
                            },
                        },
                        relevance_score=0.86,
                        urgency_score=0.88,
                        novelty_score=0.5,
                        evidence=[f"{_factor_label(dominant_factor)} accounts for {dominant_factor_pct:.1f}% of risk."],
                        why="A single dominant factor should create an explicit follow-up, not just a metric.",
                        source_tool=self.source_tool,
                    )
                )

            if lead_headline is not None or violations or (dominant_factor_pct is not None and dominant_factor_pct >= 40):
                factor_note = _factor_label(strongest_non_market or dominant_factor)
                annotations.append(
                    MarginAnnotation(
                        anchor_id="artifact.overview.composition.asset_allocation",
                        type="ask_about",
                        content=f"Ask whether the current {factor_note} exposure is intentional.",
                        prompt="Walk me through whether the current factor exposure is intentional or an artifact of the holdings mix.",
                    )
                )

            return GeneratorOutput(candidates=candidates, annotations=annotations)
        except Exception:
            _logger.warning("factor generator failed", exc_info=True)
            return GeneratorOutput()

"""Risk-oriented insight candidates."""

from __future__ import annotations

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


class RiskInsightGenerator:
    name = "risk"
    source_tool = "risk"

    def generate(self, context: PortfolioContext) -> GeneratorOutput:
        try:
            snapshot = context.tool_snapshot("risk") or {}
            if not snapshot:
                return GeneratorOutput()

            volatility = _num(snapshot.get("volatility_annual"))
            leverage = _num(snapshot.get("leverage"))
            factor_variance = _num(snapshot.get("factor_variance_pct"))
            violations = list(snapshot.get("risk_limit_violations") or [])
            risk_drivers = list(snapshot.get("risk_drivers") or [])
            candidates: list[InsightCandidate] = []
            directives: list[ArtifactDirective] = []
            annotations: list[MarginAnnotation] = []

            if volatility is not None:
                risk_metric_tags = [TAGS.RISK_FRAMEWORK_GAPS] if volatility >= 0.2 else []
                candidates.append(
                    InsightCandidate(
                        slot_type="metric",
                        category="risk",
                        tags=risk_metric_tags,
                        content={
                            "id": "volatility",
                            "title": "Volatility",
                            "value": f"{volatility * 100:.1f}%",
                            "tone": "down" if volatility >= 0.2 else "neutral",
                            "why_showing": "Annualized volatility is the simplest high-level read on how jumpy the book currently is.",
                        },
                        relevance_score=min(1.0, max(volatility / 0.35, 0.35)),
                        urgency_score=0.8 if volatility >= 0.2 else 0.35,
                        novelty_score=0.55,
                        evidence=[f"Annualized volatility is {volatility * 100:.1f}%."],
                        why="Front-page risk needs one compact volatility read.",
                        source_tool=self.source_tool,
                    )
                )

            lead_needed = bool(violations) or (volatility is not None and volatility >= 0.22) or (leverage is not None and leverage > 1.1)
            if lead_needed:
                driver_text = ""
                if risk_drivers:
                    top_driver = risk_drivers[0]
                    if isinstance(top_driver, dict):
                        label = str(top_driver.get("label") or top_driver.get("ticker") or top_driver.get("factor") or "").strip()
                        contribution = _num(top_driver.get("pct") or top_driver.get("value"))
                        if label:
                            driver_text = (
                                f" The first driver is {label}{f' at {contribution:.1f}%' if contribution is not None else ''}."
                            )

                headline = "Risk is running hot enough to lead the morning read."
                if violations:
                    first_violation = violations[0]
                    if isinstance(first_violation, dict):
                        metric = str(first_violation.get("metric") or first_violation.get("label") or "a limit").strip()
                        headline = f"{metric} is outside the configured guardrails.{driver_text}"
                elif leverage is not None and leverage > 1.1:
                    headline = f"Leverage is elevated at {leverage:.2f}x and deserves a first-pass check.{driver_text}"
                elif volatility is not None:
                    headline = f"Annualized volatility is up at {volatility * 100:.1f}% and is starting to matter.{driver_text}"

                candidates.append(
                    InsightCandidate(
                        slot_type="lead_insight",
                        category="risk",
                        tags=[TAGS.RISK_FRAMEWORK_GAPS],
                        content={
                            "headline": headline,
                            "exit_ramps": [
                                {"label": "Open risk view", "action_type": "navigate", "payload": "risk"},
                                {"label": "Stress test it", "action_type": "navigate", "payload": "scenario:stress-test"},
                            ],
                        },
                        relevance_score=0.85,
                        urgency_score=0.95 if violations else 0.75,
                        novelty_score=0.55,
                        evidence=[f"Risk limit violations: {len(violations)}." if violations else "Risk metrics are elevated."],
                        why="Guardrail breaches and hot risk metrics should outrank routine performance copy.",
                        source_tool=self.source_tool,
                    )
                )

            if violations:
                first = violations[0]
                if isinstance(first, dict):
                    metric = str(first.get("metric") or first.get("label") or "Risk limit").strip()
                    candidates.append(
                        InsightCandidate(
                            slot_type="attention_item",
                            category="risk",
                            tags=[TAGS.RISK_FRAMEWORK_GAPS],
                            content={
                                "category": "risk",
                                "headline": f"{metric} is outside the configured limit.",
                                "urgency": "alert",
                                "action": {
                                    "label": "Inspect risk limits",
                                    "action_type": "navigate",
                                    "payload": "risk",
                                },
                            },
                            relevance_score=0.95,
                            urgency_score=1.0,
                            novelty_score=0.65,
                            evidence=[f"Detected {len(violations)} risk-limit issue(s)."],
                            why="Explicit guardrail breaks should surface as hard attention items.",
                            source_tool=self.source_tool,
                        )
                    )

            if lead_needed or factor_variance is not None:
                note = None
                if violations:
                    note = "Start with asset allocation before chasing security-level fixes."
                elif volatility is not None and volatility >= 0.2:
                    note = "Asset allocation is doing enough work that it belongs near the front of the read."
                elif leverage is not None and leverage > 1.1:
                    note = "Asset mix deserves a first-pass check before leverage drifts further."

                directives.append(
                    ArtifactDirective(
                        artifact_id="overview.composition.asset_allocation",
                        position=30,
                        visible=True,
                        annotation=note,
                    )
                )

            if factor_variance is not None and factor_variance >= 70:
                annotations.append(
                    MarginAnnotation(
                        anchor_id="artifact.overview.composition.asset_allocation",
                        type="context",
                        content=f"Factor variance is doing {factor_variance:.0f}% of the work in the current risk stack.",
                    )
                )

            if violations:
                annotations.append(
                    MarginAnnotation(
                        anchor_id="artifact.overview.composition.asset_allocation",
                        type="ask_about",
                        content="Ask whether the current asset mix is what is pushing the book outside limits.",
                        prompt="Walk me through whether the current asset allocation is what is driving these risk-limit breaks.",
                    )
                )

            return GeneratorOutput(candidates=candidates, directives=directives, annotations=annotations)
        except Exception:
            _logger.warning("risk generator failed", exc_info=True)
            return GeneratorOutput()

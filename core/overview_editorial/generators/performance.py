"""Performance-oriented insight candidates."""

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


class PerformanceInsightGenerator:
    name = "performance"
    source_tool = "performance"

    def generate(self, context: PortfolioContext) -> GeneratorOutput:
        try:
            snapshot = context.tool_snapshot("performance") or {}
            if not snapshot:
                return GeneratorOutput()

            total_return = _num(snapshot.get("display_return_pct"))
            if total_return is None:
                total_return = _num(snapshot.get("ytd_return_pct"))
            if total_return is None:
                total_return = _num(snapshot.get("total_return_pct"))
            sharpe = _num(snapshot.get("sharpe_ratio"))
            drawdown = _num(snapshot.get("max_drawdown_pct"))
            alpha = _num(snapshot.get("alpha_annual_pct"))
            beta = _num(snapshot.get("beta"))
            benchmark_return = _num(snapshot.get("benchmark_return_pct"))
            benchmark_sharpe = _num(snapshot.get("benchmark_sharpe"))
            benchmark_ticker = str(snapshot.get("benchmark_ticker") or "SPY")
            return_context_label = str(snapshot.get("return_context_label") or f"vs {benchmark_ticker}")
            candidates: list[InsightCandidate] = []
            directives: list[ArtifactDirective] = []
            annotations: list[MarginAnnotation] = []

            if total_return is not None:
                candidates.append(
                    InsightCandidate(
                        slot_type="metric",
                        category="performance",
                        tags=[TAGS.PERFORMANCE_VS_BENCHMARK],
                        content={
                            "id": "return",
                            "title": "Return",
                            "value": f"{total_return:+.1f}%",
                            "context_label": return_context_label,
                            "benchmark_value": f"{benchmark_return:+.1f}%" if benchmark_return is not None else None,
                            "tone": "up" if total_return >= 0 else "down",
                            "why_showing": "Performance stays on the front page because it is the core confirmation that the system is or is not working.",
                        },
                        relevance_score=min(1.0, max(abs(total_return) / 20.0, 0.45)),
                        urgency_score=0.8 if total_return < 0 else 0.35,
                        novelty_score=0.55,
                        evidence=[f"Portfolio return: {total_return:+.1f}%."],
                        why="Performance is one of the user's explicit front-page priorities.",
                        source_tool=self.source_tool,
                    )
                )

            if sharpe is not None:
                sharpe_tags = [TAGS.PERFORMANCE_VS_BENCHMARK] if benchmark_sharpe is not None else []
                candidates.append(
                    InsightCandidate(
                        slot_type="metric",
                        category="performance",
                        tags=sharpe_tags,
                        content={
                            "id": "sharpe",
                            "title": "Sharpe",
                            "value": f"{sharpe:.2f}",
                            "benchmark_value": f"{benchmark_sharpe:.2f}" if benchmark_sharpe is not None else None,
                            "tone": "up" if sharpe >= 1 else "neutral",
                            "why_showing": "Sharpe gives a compact read on whether returns still look efficient after accounting for the path taken.",
                        },
                        relevance_score=0.4,
                        urgency_score=0.25 if sharpe >= 1 else 0.55,
                        novelty_score=0.4,
                        evidence=[f"Sharpe ratio: {sharpe:.2f}."],
                        why="Risk-adjusted quality helps distinguish good gains from noisy gains.",
                        source_tool=self.source_tool,
                    )
                )

            if drawdown is not None:
                candidates.append(
                    InsightCandidate(
                        slot_type="metric",
                        category="performance",
                        tags=[],
                        content={
                            "id": "maxDrawdown",
                            "title": "Max Drawdown",
                            "value": f"{drawdown:.1f}%",
                            "tone": "down" if drawdown < -10.0 else "neutral",
                            "why_showing": "Drawdown keeps the performance conversation honest when returns alone look fine.",
                        },
                        relevance_score=min(1.0, max(abs(drawdown) / 20.0, 0.35)),
                        urgency_score=0.8 if drawdown < -10.0 else 0.3,
                        novelty_score=0.45,
                        evidence=[f"Max drawdown: {drawdown:.1f}%."],
                        why="Drawdown is the fastest way to frame how painful the path has been.",
                        source_tool=self.source_tool,
                    )
                )

            if beta is not None:
                beta_distance = abs(beta - 1.0)
                candidates.append(
                    InsightCandidate(
                        slot_type="metric",
                        category="performance",
                        tags=[TAGS.PERFORMANCE_VS_BENCHMARK],
                        content={
                            "id": "beta",
                            "title": "Beta",
                            "value": f"{beta:.2f}",
                            "context_label": benchmark_ticker,
                            "benchmark_value": "1.00",
                            "tone": "down" if beta > 1.15 or beta < 0.85 else "neutral",
                            "why_showing": "Beta shows whether the book is leaning harder or softer than the benchmark tape.",
                        },
                        relevance_score=min(1.0, max(beta_distance / 0.6, 0.35)),
                        urgency_score=0.7 if beta_distance >= 0.2 else 0.3,
                        novelty_score=0.45,
                        evidence=[f"Portfolio beta versus {benchmark_ticker}: {beta:.2f}."],
                        why="Benchmark sensitivity belongs in the strip when the book stops behaving like plain market exposure.",
                        source_tool=self.source_tool,
                    )
                )

            if alpha is not None:
                candidates.append(
                    InsightCandidate(
                        slot_type="metric",
                        category="performance",
                        tags=[TAGS.PERFORMANCE_VS_BENCHMARK],
                        content={
                            "id": "alpha",
                            "title": "Alpha",
                            "value": f"{alpha:+.1f}%",
                            "context_label": f"vs {benchmark_ticker}",
                            "tone": "up" if alpha >= 0 else "down",
                            "why_showing": "Alpha is the cleanest read on whether performance is coming from selection instead of market drift.",
                        },
                        relevance_score=min(1.0, max(abs(alpha) / 25.0, 0.4)),
                        urgency_score=0.75 if alpha < 0 else 0.35,
                        novelty_score=0.45,
                        evidence=[f"Alpha versus {benchmark_ticker}: {alpha:+.1f}%."],
                        why="Alpha is one of the planned first-fold checks for whether the process is adding value versus benchmark.",
                        source_tool=self.source_tool,
                    )
                )

            if total_return is not None and (total_return <= -3.0 or (alpha is not None and alpha < 0)):
                headline = (
                    "Performance is lagging and the book is not being paid for the current risk."
                    if total_return <= -3.0
                    else f"Alpha versus {benchmark_ticker} is still negative, so the spread needs explanation."
                )
                candidates.append(
                    InsightCandidate(
                        slot_type="lead_insight",
                        category="performance",
                        tags=[TAGS.PERFORMANCE_VS_BENCHMARK],
                        content={
                            "headline": headline,
                            "exit_ramps": [
                                {"label": "Review performance", "action_type": "navigate", "payload": "performance"},
                                {"label": "Check attribution", "action_type": "chat_prompt", "payload": "What is driving the gap versus benchmark?"},
                            ],
                        },
                        relevance_score=0.8,
                        urgency_score=0.75,
                        novelty_score=0.55,
                        evidence=[
                            f"Return: {total_return:+.1f}%." if total_return is not None else "Performance is soft.",
                            f"Alpha annual: {alpha:+.1f}%." if alpha is not None else f"Benchmark: {benchmark_ticker}.",
                        ],
                        why="A weak spread versus benchmark should sometimes outrank risk copy.",
                        source_tool=self.source_tool,
                    )
                )

                directives.append(
                    ArtifactDirective(
                        artifact_id="overview.performance_attribution",
                        position=20,
                        visible=True,
                        annotation=f"Use the attribution view to explain the spread versus {benchmark_ticker}.",
                    )
                )

                annotations.append(
                    MarginAnnotation(
                        anchor_id="artifact.overview.performance_attribution",
                        type="ask_about",
                        content=f"Ask what is driving the gap versus {benchmark_ticker}.",
                        prompt=f"Walk me through what is driving the performance gap versus {benchmark_ticker}.",
                    )
                )

            return GeneratorOutput(candidates=candidates, directives=directives, annotations=annotations)
        except Exception:
            _logger.warning("performance generator failed", exc_info=True)
            return GeneratorOutput()

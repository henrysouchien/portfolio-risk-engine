"""Policy layer for ranking generator outputs into a fixed Overview brief."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import logging

from core.overview_editorial.context import PortfolioContext
from core.overview_editorial.generators import (
    ConcentrationInsightGenerator,
    EventsInsightGenerator,
    FactorInsightGenerator,
    GeneratorOutput,
    IncomeInsightGenerator,
    LossScreeningInsightGenerator,
    PerformanceInsightGenerator,
    RiskInsightGenerator,
    TaxHarvestInsightGenerator,
    TradingInsightGenerator,
)
from core.overview_editorial.vocabulary import (
    ANNOTATION_TYPE_PRIORITY,
    CONCERN_METRIC_ANCHORS,
    DEPTH_LEVELS,
    MAX_ANCHORED_METRICS,
    normalize_depth,
)
from models.overview_editorial import (
    ArtifactDirective,
    AttentionItem,
    EditorialMetadata,
    ExitRamp,
    InsightCandidate,
    LeadInsight,
    MarginAnnotation,
    MetricStripItem,
    OverviewBrief,
)

_logger = logging.getLogger(__name__)
_CORE_SOURCES = {"positions", "risk", "performance"}


class BriefNoCandidatesError(RuntimeError):
    """Raised when no generator can produce any usable candidate."""


@dataclass(frozen=True)
class RankedCandidate:
    candidate: InsightCandidate
    composite_score: float
    memory_fit: float


class EditorialPolicyLayer:
    """Rank generator output and compose the fixed OverviewBrief payload."""

    def __init__(self, generators: list | None = None) -> None:
        self._generators = generators or [
            ConcentrationInsightGenerator(),
            RiskInsightGenerator(),
            FactorInsightGenerator(),
            PerformanceInsightGenerator(),
            IncomeInsightGenerator(),
            LossScreeningInsightGenerator(),
            TaxHarvestInsightGenerator(),
            TradingInsightGenerator(),
            EventsInsightGenerator(),
        ]

    def generate_outputs(self, context: PortfolioContext) -> GeneratorOutput:
        candidates: list[InsightCandidate] = []
        directives: list[ArtifactDirective] = []
        annotations: list[MarginAnnotation] = []
        for generator in self._generators:
            try:
                output = generator.generate(context)
            except Exception:
                _logger.warning("overview generator failed: %s", generator.__class__.__name__, exc_info=True)
                continue
            candidates.extend(output.candidates)
            directives.extend(output.directives)
            annotations.extend(output.annotations)
        return GeneratorOutput(
            candidates=candidates,
            directives=self._dedupe_directives(directives),
            annotations=self._dedupe_annotations(annotations),
        )

    def generate_candidates(self, context: PortfolioContext) -> list[InsightCandidate]:
        return self.generate_outputs(context).candidates

    def compose_brief(self, context: PortfolioContext) -> OverviewBrief:
        outputs = self.generate_outputs(context)
        candidates = outputs.candidates
        if not candidates:
            raise BriefNoCandidatesError("No overview editorial candidates were generated.")

        ranked_candidates = self.rank(
            candidates,
            context.editorial_memory,
            context.previous_brief_anchor,
        )
        slots = self.select_slots(ranked_candidates, context.editorial_memory)

        if not slots["lead_insight"] and slots["metric"]:
            top_metric = slots["metric"][0]
            slots["lead_insight"] = [
                RankedCandidate(
                    candidate=InsightCandidate(
                        slot_type="lead_insight",
                        category=top_metric.candidate.category,
                        tags=list(top_metric.candidate.tags),
                        content={
                            "headline": top_metric.candidate.content.get("why_showing")
                            or f"{top_metric.candidate.content.get('title')} is the cleanest first read right now.",
                            "exit_ramps": [],
                        },
                        relevance_score=top_metric.candidate.relevance_score,
                        urgency_score=top_metric.candidate.urgency_score,
                        novelty_score=top_metric.candidate.novelty_score,
                        confidence=top_metric.candidate.confidence,
                        evidence=list(top_metric.candidate.evidence),
                        why=top_metric.candidate.why,
                        source_tool=top_metric.candidate.source_tool,
                    ),
                    composite_score=top_metric.composite_score,
                    memory_fit=top_metric.memory_fit,
                )
            ]

        if not slots["lead_insight"]:
            raise BriefNoCandidatesError("No lead insight could be composed for the overview brief.")

        return self._compose_brief(
            slots=slots,
            directives=outputs.directives,
            annotations=outputs.annotations,
            context=context,
            candidate_count=len(candidates),
        )

    def select_slots(
        self,
        ranked: list[RankedCandidate],
        editorial_memory: dict | None = None,
    ) -> dict[str, list[RankedCandidate]]:
        """Top-N per slot type for the fixed Overview layout."""

        anchored_metric_ids = self._resolve_anchored_metric_ids(editorial_memory or {})
        anchored_metric_entries: list[RankedCandidate] = []
        used_metric_keys: set[str] = set()
        if anchored_metric_ids:
            metric_lookup: dict[str, RankedCandidate] = {}
            for entry in ranked:
                if entry.candidate.slot_type != "metric":
                    continue
                metric_id = entry.candidate.content.get("id")
                if not metric_id:
                    continue
                metric_lookup.setdefault(str(metric_id), entry)
            for metric_id in anchored_metric_ids:
                entry = metric_lookup.get(metric_id)
                if entry is None:
                    continue
                key = self._candidate_key(entry.candidate)
                if key in used_metric_keys:
                    continue
                used_metric_keys.add(key)
                anchored_metric_entries.append(entry)

        competitive_metrics = self._select_ranked(
            ranked,
            slot_type="metric",
            limit=max(0, 6 - len(anchored_metric_entries)),
            exclude_keys=used_metric_keys,
        )
        metrics = sorted(
            anchored_metric_entries + competitive_metrics,
            key=lambda entry: entry.composite_score,
            reverse=True,
        )[:6]

        return {
            "metric": metrics,
            "lead_insight": self._select_ranked(ranked, slot_type="lead_insight", limit=1),
            "attention_item": self._select_ranked(ranked, slot_type="attention_item", limit=3),
        }

    def _compose_brief(
        self,
        *,
        slots: dict[str, list[RankedCandidate]],
        directives: list[ArtifactDirective],
        annotations: list[MarginAnnotation],
        context: PortfolioContext,
        candidate_count: int,
    ) -> OverviewBrief:
        leads = slots["lead_insight"]
        metrics = slots["metric"]
        attentions = slots["attention_item"]
        generated_at = context.generated_at if context.generated_at.tzinfo else datetime.now(UTC)
        metadata = EditorialMetadata(
            generated_at=generated_at,
            editorial_memory_version=int(context.editorial_memory.get("version") or 1),
            candidates_considered=candidate_count,
            selection_reasons=[entry.candidate.why for entry in (leads + metrics)[:4]],
            lead_insight_category=leads[0].candidate.category if leads else None,
            confidence=self._confidence(context),
            source=self._source(context),
            llm_enhanced=False,
            changed_slots=[],
        )

        return OverviewBrief(
            metric_strip=[self._metric_from_candidate(entry.candidate) for entry in metrics],
            lead_insight=self._lead_from_candidate(leads[0].candidate),
            artifact_directives=[
                self._normalize_directive(directive, index)
                for index, directive in enumerate(directives)
            ],
            margin_annotations=self._truncate_annotations(
                annotations,
                context.editorial_memory,
            ),
            attention_items=[self._attention_from_candidate(entry.candidate) for entry in attentions],
            editorial_metadata=metadata,
        )

    def _select_ranked(
        self,
        ranked: list[RankedCandidate],
        *,
        slot_type: str,
        limit: int,
        exclude_keys: set[str] | None = None,
    ) -> list[RankedCandidate]:
        selected: list[RankedCandidate] = []
        seen_key: set[str] = set(exclude_keys or set())
        for entry in ranked:
            candidate = entry.candidate
            if candidate.slot_type != slot_type:
                continue
            key = self._candidate_key(candidate)
            if key in seen_key:
                continue
            seen_key.add(key)
            selected.append(entry)
            if len(selected) >= limit:
                break
        return selected

    def _candidate_key(self, candidate: InsightCandidate) -> str:
        return str(candidate.content.get("id") or candidate.content.get("headline") or candidate.why)

    def _dedupe_directives(self, directives: list[ArtifactDirective]) -> list[ArtifactDirective]:
        deduped: list[ArtifactDirective] = []
        seen_artifact_ids: set[str] = set()
        for directive in directives:
            if directive.artifact_id in seen_artifact_ids:
                continue
            seen_artifact_ids.add(directive.artifact_id)
            deduped.append(directive)
        return deduped

    def _dedupe_annotations(self, annotations: list[MarginAnnotation]) -> list[MarginAnnotation]:
        deduped: list[MarginAnnotation] = []
        seen_keys: set[tuple[str, str, str]] = set()
        for annotation in annotations:
            key = (annotation.anchor_id, annotation.type, annotation.content)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            deduped.append(annotation)
        return deduped

    def _normalize_directive(self, directive: ArtifactDirective, position: int) -> ArtifactDirective:
        if directive.position != 0:
            return directive
        return directive.model_copy(update={"position": position})

    def rank(
        self,
        candidates: list[InsightCandidate],
        editorial_memory: dict,
        previous_brief: dict | None = None,
    ) -> list[RankedCandidate]:
        del previous_brief
        ranked: list[RankedCandidate] = []
        for candidate in candidates:
            memory_fit = self._compute_memory_fit(candidate, editorial_memory)
            composite = (
                0.35 * candidate.relevance_score
                + 0.25 * candidate.urgency_score
                + 0.25 * memory_fit
                + 0.15 * candidate.novelty_score
            )
            ranked.append(
                RankedCandidate(
                    candidate=candidate,
                    composite_score=composite,
                    memory_fit=memory_fit,
                )
            )
        ranked.sort(key=lambda entry: entry.composite_score, reverse=True)
        return ranked

    def _compute_memory_fit(self, candidate: InsightCandidate, memory: dict) -> float:
        preferences = memory.get("editorial_preferences", {})
        lead_with = {str(item).strip().lower() for item in preferences.get("lead_with", [])}
        care_about = {str(item).strip().lower() for item in preferences.get("care_about", [])}
        less_interested = {str(item).strip().lower() for item in preferences.get("less_interested_in", [])}
        category = candidate.category.strip().lower()
        tags = {str(tag).strip().lower() for tag in candidate.tags}
        labels = {category, *tags}

        if labels & lead_with:
            return 1.0
        if labels & less_interested:
            return 0.1
        if labels & care_about:
            return 0.7
        return 0.3

    def _resolve_anchored_metric_ids(self, editorial_memory: dict) -> list[str]:
        concerns = (editorial_memory.get("investor_profile") or {}).get("concerns", [])
        anchored: list[str] = []
        seen: set[str] = set()
        for concern in concerns:
            metric_ids = CONCERN_METRIC_ANCHORS.get(str(concern).strip().lower(), [])
            for metric_id in metric_ids:
                if metric_id in seen:
                    continue
                seen.add(metric_id)
                anchored.append(metric_id)
                if len(anchored) >= MAX_ANCHORED_METRICS:
                    return anchored
        return anchored

    def _truncate_annotations(
        self,
        annotations: list[MarginAnnotation],
        editorial_memory: dict | None = None,
    ) -> list[MarginAnnotation]:
        cap = self._annotation_limit(editorial_memory or {})
        if len(annotations) <= cap:
            return list(annotations)
        return sorted(
            annotations,
            key=lambda annotation: (
                ANNOTATION_TYPE_PRIORITY.get(annotation.type, 99),
                annotation.anchor_id,
                annotation.content,
            ),
        )[:cap]

    def _annotation_limit(self, editorial_memory: dict) -> int:
        philosophy = editorial_memory.get("briefing_philosophy") or {}
        depth = normalize_depth(philosophy.get("depth"))
        return DEPTH_LEVELS.get(depth, DEPTH_LEVELS["high_level"])

    def _score(self, candidate: InsightCandidate, context: PortfolioContext) -> float:
        return self.rank([candidate], context.editorial_memory, context.previous_brief_anchor)[0].composite_score

    def _metric_from_candidate(self, candidate: InsightCandidate) -> MetricStripItem:
        return MetricStripItem(**candidate.content)

    def _lead_from_candidate(self, candidate: InsightCandidate) -> LeadInsight:
        content = dict(candidate.content)
        exit_ramps = [ExitRamp(**ramp) for ramp in content.pop("exit_ramps", [])]
        evidence = content.pop("evidence", None) or candidate.evidence
        return LeadInsight(
            headline=str(content.get("headline") or ""),
            evidence=list(evidence or []),
            exit_ramps=exit_ramps,
        )

    def _attention_from_candidate(self, candidate: InsightCandidate) -> AttentionItem:
        content = dict(candidate.content)
        action = content.get("action")
        return AttentionItem(
            category=str(content.get("category") or candidate.category),
            headline=str(content.get("headline") or ""),
            urgency=str(content.get("urgency") or "watch"),
            action=ExitRamp(**action) if isinstance(action, dict) else None,
        )

    def _confidence(self, context: PortfolioContext) -> str:
        loaded_count = sum(1 for source in _CORE_SOURCES if context.data_status.get(source) == "loaded")
        if loaded_count == len(_CORE_SOURCES):
            return "high"
        if loaded_count >= 1:
            return "partial"
        return "summary only"

    def _source(self, context: PortfolioContext) -> str:
        loaded_count = sum(1 for source in _CORE_SOURCES if context.data_status.get(source) == "loaded")
        if loaded_count == len(_CORE_SOURCES):
            return "live"
        if loaded_count >= 1:
            return "mixed"
        return "summary"


__all__ = ["BriefNoCandidatesError", "EditorialPolicyLayer", "RankedCandidate"]

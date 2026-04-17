"""Best-effort LLM enhancement for deterministic overview briefs."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from app_platform.logging.core import log_event, log_timing_event
from core.overview_editorial.brief_cache import set_cached_brief
from pydantic import BaseModel, ConfigDict
from models.overview_editorial import LeadInsight, MetricStripItem, OverviewBrief
from providers.completion import build_completion_provider, complete_structured, get_completion_provider

_logger = logging.getLogger(__name__)
_UNSET = object()


class ArbiterExitRamp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    action_type: str
    payload: str


class ArbiterLeadInsightEnhancement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str | None
    evidence: list[str] | None
    exit_ramps: list[ArbiterExitRamp] | None


class ArbiterMetricEnhancement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None
    value: str | None
    change: str | None
    context_label: str | None
    tone: str | None
    why_showing: str | None


class ArbiterEnhancement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_insight: ArbiterLeadInsightEnhancement | None
    metric_strip: list[ArbiterMetricEnhancement] | None
    selection_reasons: list[str] | None


class OverviewBriefArbiter:
    """Best-effort asynchronous enhancer for the deterministic brief."""

    def __init__(
        self,
        completion_provider=_UNSET,
        *,
        provider_name: str | None = None,
        model: str | None = None,
        timeout_s: float = 10.0,
    ) -> None:
        editorial_provider_name = provider_name or os.getenv("EDITORIAL_LLM_PROVIDER", "").strip().lower() or None
        editorial_model = model or os.getenv("EDITORIAL_LLM_MODEL", "").strip() or None
        self.model = editorial_model
        self.timeout_s = timeout_s
        self._provider_name = editorial_provider_name
        if completion_provider is not _UNSET:
            self._completion_provider = completion_provider
        elif editorial_provider_name:
            self._completion_provider = build_completion_provider(
                provider_name=editorial_provider_name,
                default_model=editorial_model,
            )
        else:
            self._completion_provider = get_completion_provider()

    @property
    def enabled(self) -> bool:
        return self._completion_provider is not None

    def enhance_and_replace(
        self,
        *,
        user_id: int,
        portfolio_id: str | None,
        deterministic_brief: OverviewBrief,
        editorial_memory: dict[str, Any],
    ) -> None:
        if not self._completion_provider:
            return

        parse_success = False
        started = time.perf_counter()
        try:
            enhanced = self.enhance(deterministic_brief, editorial_memory)
            if enhanced is None:
                return
            set_cached_brief(user_id, portfolio_id, enhanced)
            parse_success = True
        except Exception:
            _logger.warning("overview LLM arbiter failed", exc_info=True)
        finally:
            duration_ms = int((time.perf_counter() - started) * 1000)
            details = {
                "user_id": user_id,
                "portfolio_id": portfolio_id or "default",
                "llm_model": self._resolved_model_name(),
                "parse_success": parse_success,
                "duration_ms": duration_ms,
            }
            _logger.info(
                "overview_brief_enhanced",
                extra=details,
            )
            log_event(
                "overview_brief_enhanced",
                "Overview brief arbiter attempted enhancement",
                **details,
            )
            log_timing_event(
                "editorial",
                "overview_brief_arbiter",
                duration_ms,
                user_id=user_id,
                portfolio_id=portfolio_id or "default",
                llm_model=self._resolved_model_name(),
                parse_success=parse_success,
            )

    def enhance(
        self,
        brief: OverviewBrief,
        editorial_memory: dict[str, Any],
    ) -> OverviewBrief | None:
        if not self._completion_provider:
            return None

        prompt = self._build_prompt(brief, editorial_memory)
        try:
            payload = complete_structured(
                self._completion_provider,
                prompt,
                response_model=ArbiterEnhancement,
                system=(
                    "You are editing a fixed JSON investment overview. "
                    "Return only JSON with keys lead_insight, metric_strip, selection_reasons. "
                    "Use null for any section or field you are leaving unchanged. "
                    "Do not change artifact_directives, margin_annotations, attention_items, or schema."
                ),
                model=self.model,
                temperature=0.2,
                max_tokens=1600,
                timeout=self.timeout_s,
            )
        except Exception:
            _logger.warning("overview LLM arbiter structured parse failed", exc_info=True)
            return None

        enhanced = brief.model_copy(deep=True)

        lead_payload = payload.lead_insight
        if lead_payload is not None:
            headline = str(lead_payload.headline or brief.lead_insight.headline).strip() or brief.lead_insight.headline
            evidence_payload = lead_payload.evidence
            evidence = (
                [str(item).strip() for item in evidence_payload if str(item).strip()]
                if evidence_payload is not None
                else list(brief.lead_insight.evidence)
            )
            exit_ramps_payload = lead_payload.exit_ramps
            exit_ramps = (
                [item.model_dump(mode="python") for item in exit_ramps_payload]
                if exit_ramps_payload is not None
                else [item.model_dump(mode="python") for item in brief.lead_insight.exit_ramps]
            )
            enhanced.lead_insight = LeadInsight(
                headline=headline,
                evidence=evidence,
                exit_ramps=exit_ramps,
            )

        metrics_payload = payload.metric_strip
        if metrics_payload is not None:
            validated_metrics: list[MetricStripItem] = []
            for original, item in zip(brief.metric_strip, metrics_payload, strict=False):
                merged = original.model_dump(mode="python")
                for key in ("title", "value", "change", "context_label", "tone", "why_showing"):
                    value = getattr(item, key)
                    if value is not None:
                        merged[key] = value
                validated_metrics.append(MetricStripItem.model_validate(merged))
            if len(validated_metrics) == len(brief.metric_strip):
                enhanced.metric_strip = validated_metrics

        reasons_payload = payload.selection_reasons
        if reasons_payload is not None:
            enhanced.editorial_metadata.selection_reasons = [
                str(item).strip() for item in reasons_payload if str(item).strip()
            ]

        enhanced.artifact_directives = [directive.model_copy(deep=True) for directive in brief.artifact_directives]
        enhanced.margin_annotations = [annotation.model_copy(deep=True) for annotation in brief.margin_annotations]
        enhanced.attention_items = [item.model_copy(deep=True) for item in brief.attention_items]
        enhanced.editorial_metadata.changed_slots = list(brief.editorial_metadata.changed_slots)
        enhanced.editorial_metadata.lead_insight_category = brief.editorial_metadata.lead_insight_category
        enhanced.editorial_metadata.candidates_considered = brief.editorial_metadata.candidates_considered
        enhanced.editorial_metadata.confidence = brief.editorial_metadata.confidence
        enhanced.editorial_metadata.source = brief.editorial_metadata.source
        enhanced.editorial_metadata.generated_at = brief.editorial_metadata.generated_at
        enhanced.editorial_metadata.llm_enhanced = True
        return enhanced

    def _build_prompt(self, brief: OverviewBrief, editorial_memory: dict[str, Any]) -> str:
        priorities = editorial_memory.get("editorial_preferences", {})
        return json.dumps(
            {
                "lead_with": priorities.get("lead_with", []),
                "care_about": priorities.get("care_about", []),
                "less_interested_in": priorities.get("less_interested_in", []),
                "editorial_memory": editorial_memory,
                "brief": brief.model_dump(mode="json"),
            },
            indent=2,
            sort_keys=True,
        )

    def _resolved_model_name(self) -> str | None:
        if self.model:
            return self.model
        return getattr(self._completion_provider, "_default_model", None)


__all__ = ["OverviewBriefArbiter"]

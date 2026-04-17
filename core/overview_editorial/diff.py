"""Slot-level diffing for overview briefs."""

from __future__ import annotations

import hashlib

from models.overview_editorial import MarginAnnotation, OverviewBrief


def _directive_changed(directive, previous: dict) -> bool:
    return (
        directive.annotation != previous.get("annotation")
        or directive.visible != previous.get("visible", True)
        or directive.position != previous.get("position", 0)
        or sorted(directive.highlight_ids) != sorted(previous.get("highlight_ids", []))
        or directive.editorial_note != previous.get("editorial_note")
    )


def annotation_identity(annotation: MarginAnnotation | dict) -> str | None:
    if isinstance(annotation, dict):
        anchor_id = annotation.get("anchor_id")
        annotation_type = annotation.get("type")
        content = annotation.get("content")
        prompt = annotation.get("prompt")
    else:
        anchor_id = getattr(annotation, "anchor_id", None)
        annotation_type = getattr(annotation, "type", None)
        content = getattr(annotation, "content", None)
        prompt = getattr(annotation, "prompt", None)

    if not anchor_id or not annotation_type or not content:
        return None

    digest_input = f"{anchor_id}|{annotation_type}|{prompt or content}"
    digest = hashlib.sha1(digest_input.encode("utf-8")).hexdigest()[:12]
    return f"{anchor_id}.{annotation_type}.{digest}"


def annotation_changed_slot(annotation: MarginAnnotation | dict) -> str | None:
    identity = annotation_identity(annotation)
    if identity is None:
        return None
    return f"annotation.{identity}"


def compute_changed_slots(new_brief: OverviewBrief, previous_anchor: dict | None) -> list[str]:
    """Return changed logical slots between the current and prior brief."""

    if previous_anchor is None:
        return []

    changed: list[str] = []

    previous_metrics = {
        metric["id"]: metric
        for metric in previous_anchor.get("metric_strip", [])
        if isinstance(metric, dict) and metric.get("id")
    }
    for metric in new_brief.metric_strip:
        previous = previous_metrics.get(metric.id)
        if previous is None:
            changed.append(f"metric.{metric.id}")
            continue
        if (
            previous.get("value") != metric.value
            or previous.get("tone") != metric.tone
            or previous.get("benchmark_value") != metric.benchmark_value
        ):
            changed.append(f"metric.{metric.id}")

    previous_headline = (
        previous_anchor.get("lead_insight", {}).get("headline")
        if isinstance(previous_anchor.get("lead_insight"), dict)
        else None
    )
    if new_brief.lead_insight.headline != (previous_headline or ""):
        changed.append("lead_insight")

    previous_directives = {
        directive["artifact_id"]: directive
        for directive in previous_anchor.get("artifact_directives", [])
        if isinstance(directive, dict) and directive.get("artifact_id")
    }
    for directive in new_brief.artifact_directives:
        previous = previous_directives.get(directive.artifact_id)
        if previous is None or _directive_changed(directive, previous):
            changed.append(f"artifact.{directive.artifact_id}")

    previous_annotations = {
        identity: annotation
        for annotation in previous_anchor.get("margin_annotations", [])
        if isinstance(annotation, dict) and (identity := annotation_identity(annotation))
    }
    for annotation in new_brief.margin_annotations:
        identity = annotation_identity(annotation)
        if identity is None:
            continue
        previous = previous_annotations.get(identity)
        if (
            previous is None
            or previous.get("content") != annotation.content
            or previous.get("prompt") != annotation.prompt
        ):
            changed.append(f"annotation.{identity}")

    return changed

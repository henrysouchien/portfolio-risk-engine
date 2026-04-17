"""Interpretive flags for research workspace agent responses."""

from __future__ import annotations

from typing import Any


def generate_research_flags(snapshot: dict[str, Any], context: str = "file") -> list[dict[str, str]]:
    """Generate severity-tagged flags for research snapshots."""

    if context == "file":
        return _sort_flags(_file_flags(snapshot))
    if context == "diligence":
        return _sort_flags(_diligence_flags(snapshot))
    if context == "handoff":
        return _sort_flags(_handoff_flags(snapshot))
    if context == "build":
        return _sort_flags(_build_flags(snapshot))
    return []


def _file_flags(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    files = snapshot.get("files")
    if not isinstance(files, list):
        files = []
    has_single_file_snapshot = snapshot.get("id") is not None

    flags: list[dict[str, str]] = []
    active_files = [
        item for item in files if isinstance(item, dict) and str(item.get("stage") or "") != "closed"
    ]

    if not files and not has_single_file_snapshot:
        flags.append({
            "flag": "no_research_files",
            "severity": "info",
            "message": "No research files found for this user",
        })
    if len(active_files) > 3:
        flags.append({
            "flag": "multiple_active",
            "severity": "info",
            "message": f"{len(active_files)} research files are active",
        })
    if snapshot.get("research_started"):
        flags.append({
            "flag": "research_started",
            "severity": "success",
            "message": "Research workspace started for this thesis",
        })
    if snapshot.get("existing_file_reused"):
        flags.append({
            "flag": "existing_file_reused",
            "severity": "info",
            "message": "Existing research file was reused",
        })
    return flags


def _diligence_flags(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    flags: list[dict[str, str]] = []

    if not snapshot.get("diligence_active", True):
        flags.append({
            "flag": "diligence_not_activated",
            "severity": "info",
            "message": "Diligence has not been activated for this research file",
        })
        return flags

    sections = snapshot.get("sections")
    if not isinstance(sections, list):
        sections = []

    total_sections = int(snapshot.get("total_sections") or len(sections))
    completed_sections = int(
        snapshot.get("completed_sections")
        or sum(
            1
            for section in sections
            if isinstance(section, dict) and str(section.get("status") or "") == "confirmed"
        )
    )

    if total_sections == 0 or completed_sections == 0:
        flags.append({
            "flag": "diligence_not_started",
            "severity": "info",
            "message": "Diligence has not started yet",
        })
    elif completed_sections < total_sections:
        flags.append({
            "flag": "diligence_incomplete",
            "severity": "warning",
            "message": f"{completed_sections} of {total_sections} diligence sections are confirmed",
        })
    else:
        flags.append({
            "flag": "diligence_confirmed",
            "severity": "success",
            "message": "All diligence sections are confirmed",
        })
        flags.append({
            "flag": "ready_for_handoff",
            "severity": "success",
            "message": "Diligence is ready for handoff finalization",
        })

    factors = snapshot.get("qualitative_factors")
    if not isinstance(factors, list) or not factors:
        flags.append({
            "flag": "missing_qualitative_factors",
            "severity": "info",
            "message": "No qualitative factors have been added",
        })

    return flags


def _handoff_flags(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    status = str(snapshot.get("status") or "")
    if status == "finalized":
        return [{
            "flag": "handoff_finalized",
            "severity": "success",
            "message": "Research handoff is finalized",
        }]
    return []


def _build_flags(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    flags: list[dict[str, str]] = []
    if snapshot.get("no_finalized_handoff"):
        flags.append({
            "flag": "no_finalized_handoff",
            "severity": "error",
            "message": "No finalized handoff is available for model build",
        })
        return flags

    build_status = str(snapshot.get("build_status") or "")
    annotation_status = str(snapshot.get("annotation_status") or "")

    if build_status == "success" and annotation_status == "success":
        flags.append({
            "flag": "model_built",
            "severity": "success",
            "message": "Model build and annotation both succeeded",
        })
        return flags

    if build_status == "success" and annotation_status == "error":
        flags.append({
            "flag": "annotation_failed",
            "severity": "warning",
            "message": "Model build succeeded but research annotation failed",
        })
        return flags

    if build_status == "error":
        flags.append({
            "flag": "build_failed",
            "severity": "error",
            "message": "Model build failed",
        })
    return flags


def _sort_flags(flags: list[dict[str, str]]) -> list[dict[str, str]]:
    order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    return sorted(flags, key=lambda flag: order.get(flag.get("severity", "info"), 2))


__all__ = ["generate_research_flags", "_sort_flags"]

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
    if str(snapshot.get("status") or "") == "error":
        return _error_file_flags(snapshot)

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
    idea_seeded = _is_truthy(snapshot.get("idea_seeded"))
    thesis_bootstrapped = _is_truthy(snapshot.get("thesis_bootstrapped"))
    idea_backfilled = _is_truthy(snapshot.get("idea_backfilled"))

    if idea_seeded and thesis_bootstrapped:
        flags.append({
            "flag": "research_started_from_idea",
            "severity": "info",
            "message": "Research workspace was seeded from an investment idea",
        })
    if idea_seeded and idea_backfilled:
        flags.append({
            "flag": "idea_backfilled_to_existing_file",
            "severity": "info",
            "message": "Investment idea provenance was backfilled onto an existing research file",
        })
    if (
        idea_seeded
        and _is_truthy(snapshot.get("existing_file_reused"))
        and snapshot.get("thesis_bootstrapped") is not None
        and not thesis_bootstrapped
    ):
        flags.append({
            "flag": "thesis_preserved_existing",
            "severity": "info",
            "message": "Existing thesis content was preserved during idea seeding",
        })
    return flags


def _error_file_flags(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    if _is_truthy(snapshot.get("idea_conflict")):
        return [{
            "flag": "idea_conflict",
            "severity": "warning",
            "message": "Requested investment idea conflicts with the existing research file",
        }]
    return []


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
    if status != "finalized":
        return []

    flags = [{
        "flag": "handoff_finalized",
        "severity": "success",
        "message": "Research handoff is finalized",
    }]
    if not _handoff_uses_v1_1_contract(snapshot):
        return flags

    if _handoff_count(snapshot, "differentiated_view_count", artifact_field="differentiated_view") == 0:
        flags.append({
            "flag": "missing_differentiated_view",
            "severity": "warning",
            "message": "No differentiated view captured",
        })
    if _handoff_count(snapshot, "invalidation_trigger_count", artifact_field="invalidation_triggers") == 0:
        flags.append({
            "flag": "missing_invalidation_triggers",
            "severity": "warning",
            "message": "No invalidation triggers captured",
        })

    strategy = str(_handoff_strategy(snapshot) or "")
    if strategy in {"special_situation", "macro"} and not _handoff_has_industry_analysis(snapshot):
        flags.append({
            "flag": "missing_industry_analysis",
            "severity": "info",
            "message": f"Industry analysis is recommended for {strategy.replace('_', ' ')} theses",
        })

    flags.extend(_handoff_scorecard_flags(snapshot))
    return flags


def _handoff_uses_v1_1_contract(snapshot: dict[str, Any]) -> bool:
    original_schema_version = _handoff_original_schema_version(snapshot)
    if original_schema_version is not None:
        return str(original_schema_version) == "1.1"
    return str(_handoff_schema_version(snapshot) or "") == "1.1"


def _handoff_schema_version(snapshot: dict[str, Any]) -> Any:
    if snapshot.get("schema_version") is not None:
        return snapshot.get("schema_version")
    artifact = snapshot.get("artifact")
    if isinstance(artifact, dict):
        return artifact.get("schema_version")
    return None


def _handoff_original_schema_version(snapshot: dict[str, Any]) -> Any:
    if snapshot.get("_original_schema_version") is not None:
        return snapshot.get("_original_schema_version")
    artifact = snapshot.get("artifact")
    if isinstance(artifact, dict):
        return artifact.get("_original_schema_version")
    return None


def _handoff_count(snapshot: dict[str, Any], key: str, *, artifact_field: str) -> int:
    value = snapshot.get(key)
    if value is None:
        summary = snapshot.get("artifact_summary")
        if isinstance(summary, dict):
            value = summary.get(key)
    if value is not None:
        try:
            return int(value)
        except (TypeError, ValueError):
            pass
    artifact = snapshot.get("artifact")
    if isinstance(artifact, dict):
        items = artifact.get(artifact_field)
        if isinstance(items, list):
            return len(items)
    return 0


def _handoff_has_industry_analysis(snapshot: dict[str, Any]) -> bool:
    value = snapshot.get("industry_analysis_present")
    if value is None:
        summary = snapshot.get("artifact_summary")
        if isinstance(summary, dict) and "industry_analysis_present" in summary:
            value = summary.get("industry_analysis_present")
    if value is not None:
        return bool(value)
    artifact = snapshot.get("artifact")
    return isinstance(artifact, dict) and artifact.get("industry_analysis") is not None


def _handoff_strategy(snapshot: dict[str, Any]) -> Any:
    if snapshot.get("thesis_strategy") is not None:
        return snapshot.get("thesis_strategy")
    artifact = snapshot.get("artifact")
    if not isinstance(artifact, dict):
        return None
    thesis = artifact.get("thesis")
    if isinstance(thesis, dict):
        return thesis.get("strategy")
    return None


def _handoff_scorecard_summary_status(snapshot: dict[str, Any]) -> str:
    value = snapshot.get("scorecard_summary_status")
    if value is None:
        summary = snapshot.get("artifact_summary")
        if isinstance(summary, dict):
            value = summary.get("scorecard_summary_status")
    if value is not None:
        return str(value)
    artifact = snapshot.get("artifact")
    if not isinstance(artifact, dict):
        return ""
    scorecard_ref = artifact.get("scorecard_ref")
    if isinstance(scorecard_ref, dict) and scorecard_ref.get("summary_status") is not None:
        return str(scorecard_ref.get("summary_status"))
    return ""


def _handoff_scorecard_flags(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    summary_status = _handoff_scorecard_summary_status(snapshot)
    if summary_status == "invalidated":
        return [{
            "flag": "invalidated",
            "severity": "error",
            "message": "Handoff scorecard is invalidated",
        }]
    if summary_status == "at_risk":
        return [{
            "flag": "at_risk",
            "severity": "warning",
            "message": "Handoff scorecard is at risk",
        }]
    if summary_status == "on_track":
        return [{
            "flag": "on_track",
            "severity": "success",
            "message": "Handoff scorecard is on track",
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


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes"}


__all__ = ["generate_research_flags", "_sort_flags"]

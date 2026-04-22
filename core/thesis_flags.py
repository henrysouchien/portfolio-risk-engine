"""Interpretive flags for thesis MCP agent responses."""

from __future__ import annotations

from typing import Any

from core.research_flags import _sort_flags


def generate_thesis_flags(snapshot: dict[str, Any], context: str = "thesis") -> list[dict[str, str]]:
    """Generate severity-tagged flags for thesis snapshots."""

    if context == "list":
        return _sort_flags(_list_flags(snapshot))
    if context == "thesis":
        return _sort_flags(_thesis_flags(snapshot))
    if context == "decisions":
        return _sort_flags(_decisions_flags(snapshot))
    if context == "links":
        return _sort_flags(_links_flags(snapshot))
    if context == "scorecard":
        return _sort_flags(_scorecard_flags(snapshot))
    return []


def _list_flags(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    count = int(snapshot.get("count") or 0)
    if count == 0:
        return [{
            "flag": "no_theses",
            "severity": "info",
            "message": "No thesis artifacts found for this user",
        }]
    return [{
        "flag": "theses_available",
        "severity": "success",
        "message": f"{count} thesis artifact(s) available",
    }]


def _thesis_flags(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    thesis = snapshot.get("thesis") if _looks_like_result_wrapper(snapshot) else snapshot
    if not isinstance(thesis, dict):
        return []

    flags: list[dict[str, str]] = []
    model_links = thesis.get("model_links")
    decisions_log = thesis.get("decisions_log")
    scorecard = thesis.get("scorecard")

    if not isinstance(model_links, list) or not model_links:
        flags.append({
            "flag": "no_model_links",
            "severity": "info",
            "message": "Thesis has no model links yet",
        })
    if not isinstance(decisions_log, list) or not decisions_log:
        flags.append({
            "flag": "no_decisions_log",
            "severity": "info",
            "message": "Thesis decisions log is empty",
        })
    flags.extend(_scorecard_summary_flags(scorecard))
    return flags


def _decisions_flags(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    if "entry" in snapshot:
        return [{
            "flag": "decision_logged",
            "severity": "success",
            "message": "Decision log entry appended",
        }]
    count = int(snapshot.get("count") or 0)
    if count == 0:
        return [{
            "flag": "no_decisions_log",
            "severity": "info",
            "message": "No thesis decisions have been logged",
        }]
    return [{
        "flag": "decision_history_available",
        "severity": "success",
        "message": f"{count} decision log entr{'y' if count == 1 else 'ies'} available",
    }]


def _links_flags(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    if snapshot.get("status") == "success" and snapshot.get("thesis_link_id"):
        return [{
            "flag": "link_removed",
            "severity": "success",
            "message": "Thesis link removed",
        }]
    if "link" in snapshot:
        return [{
            "flag": "link_saved",
            "severity": "success",
            "message": "Thesis link saved",
        }]
    count = int(snapshot.get("count") or 0)
    if count == 0:
        return [{
            "flag": "no_model_links",
            "severity": "info",
            "message": "No thesis links found for this thesis",
        }]
    return [{
        "flag": "links_available",
        "severity": "success",
        "message": f"{count} thesis link(s) available",
    }]


def _scorecard_flags(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    if snapshot.get("scorecard") is None and "thesis_id" in snapshot:
        return [{
            "flag": "no_scorecard",
            "severity": "info",
            "message": "No thesis scorecard has been stored yet",
        }]
    scorecard = snapshot.get("scorecard") if "scorecard" in snapshot else snapshot
    return _scorecard_summary_flags(scorecard)


def _scorecard_summary_flags(scorecard: Any) -> list[dict[str, str]]:
    if not isinstance(scorecard, dict):
        return []
    summary_status = str(scorecard.get("summary_status") or "").strip()
    if summary_status == "invalidated":
        return [{
            "flag": "invalidated",
            "severity": "error",
            "message": "Thesis scorecard is invalidated",
        }]
    if summary_status == "at_risk":
        return [{
            "flag": "at_risk",
            "severity": "warning",
            "message": "Thesis scorecard is at risk",
        }]
    if summary_status == "on_track":
        return [{
            "flag": "on_track",
            "severity": "success",
            "message": "Thesis scorecard is on track",
        }]
    if summary_status == "mixed":
        return [{
            "flag": "mixed",
            "severity": "info",
            "message": "Thesis scorecard is mixed",
        }]
    return []


def _looks_like_result_wrapper(snapshot: dict[str, Any]) -> bool:
    return (
        "thesis" in snapshot
        and isinstance(snapshot.get("thesis"), dict)
        and "ticker" not in snapshot
    )


__all__ = ["generate_thesis_flags"]

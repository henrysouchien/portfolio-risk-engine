"""Interpretive flags for model-build-context agent responses."""

from __future__ import annotations

from typing import Any

from core.research_flags import _sort_flags


def generate_mbc_flags(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    """Generate compact, agent-friendly flags for MBC responses."""

    flags: list[dict[str, str]] = []
    if snapshot.get("status") == "error":
        if snapshot.get("not_found"):
            flags.append({
                "flag": "mbc_not_found",
                "severity": "error",
                "message": str(snapshot.get("error") or "Model build context was not found"),
            })
        elif snapshot.get("validation_error"):
            flags.append({
                "flag": "mbc_validation_failed",
                "severity": "error",
                "message": str(snapshot.get("error_reason") or snapshot.get("error") or "Model build context validation failed"),
            })
        else:
            flags.append({
                "flag": "mbc_request_failed",
                "severity": "error",
                "message": str(snapshot.get("error") or "Model build context request failed"),
            })
        return _sort_flags(flags)

    report = snapshot.get("validation_report")
    summary = report.get("summary") if isinstance(report, dict) else {}
    error_count = int(summary.get("errors") or 0) if isinstance(summary, dict) else 0
    phase1_passed = bool(report.get("phase1_passed")) if isinstance(report, dict) else False
    phase2_passed = bool(report.get("phase2_passed")) if isinstance(report, dict) else False

    if phase1_passed and phase2_passed and error_count == 0:
        flags.append({
            "flag": "mbc_validated",
            "severity": "success",
            "message": "Model build context constructed and validated",
        })
    if isinstance(snapshot.get("mbc"), dict) and snapshot["mbc"].get("segment_config") is not None:
        flags.append({
            "flag": "segment_mode",
            "severity": "info",
            "message": "Model build context includes authoritative segment snapshot config",
        })
    return _sort_flags(flags)


__all__ = ["generate_mbc_flags"]

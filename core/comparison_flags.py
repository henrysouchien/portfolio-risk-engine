"""Comparison-level interpretive flags for batch scenario/optimization runs."""

from __future__ import annotations

import math
from typing import Any


def generate_comparison_flags(response: dict) -> list[dict]:
    """Generate aggregate comparison flags from compare_scenarios() response."""
    if not isinstance(response, dict):
        return []

    ranking = response.get("ranking", [])
    scenarios = response.get("scenarios", {})
    rank_order = response.get("rank_order", "asc")
    if rank_order not in {"asc", "desc"}:
        rank_order = "asc"

    flags: list[dict] = []

    successful_entries = _successful_ranked_entries(ranking, scenarios)
    numeric_entries = [entry for entry in successful_entries if entry["rank_value"] is not None]

    has_clear_winner = False
    if len(numeric_entries) >= 2:
        first = numeric_entries[0]
        second = numeric_entries[1]
        gap_12 = _directional_gap(first["rank_value"], second["rank_value"], rank_order)

        if len(numeric_entries) >= 3:
            third = numeric_entries[2]
            gap_23 = _directional_gap(second["rank_value"], third["rank_value"], rank_order)
            if gap_12 > (2 * gap_23) and abs(gap_12) > 0.5:
                flags.append(
                    {
                        "type": "clear_winner",
                        "severity": "success",
                        "message": (
                            f"{first['name']} is a clear winner on {first.get('rank_by', 'primary metric')}"
                        ),
                        "winner": first["name"],
                    }
                )
                has_clear_winner = True
        elif abs(gap_12) > 1.0:
            flags.append(
                {
                    "type": "clear_winner",
                    "severity": "success",
                    "message": (
                        f"{first['name']} clearly outperforms {second['name']} on "
                        f"{first.get('rank_by', 'primary metric')}"
                    ),
                    "winner": first["name"],
                }
            )
            has_clear_winner = True

        if not has_clear_winner:
            v1 = first["rank_value"]
            v2 = second["rank_value"]
            relative_diff = abs(v1 - v2) / max(abs(v1), abs(v2), 1e-9)
            if relative_diff < 0.10:
                flags.append(
                    {
                        "type": "marginal_differences",
                        "severity": "info",
                        "message": (
                            f"Top scenarios ({first['name']} vs {second['name']}) "
                            "are within 10% on the ranking metric"
                        ),
                        "top_two": [first["name"], second["name"]],
                    }
                )

    succeeded, failed = _status_counts(response.get("summary"), scenarios)
    if succeeded > 0 and failed > 0:
        flags.append(
            {
                "type": "partial_failures",
                "severity": "warning",
                "message": f"{failed} scenario(s) failed while {succeeded} succeeded",
                "failed": failed,
                "succeeded": succeeded,
            }
        )

    best_entry = successful_entries[0] if successful_entries else None
    if best_entry:
        best_total_violations = _scenario_total_violations(
            scenarios.get(best_entry["name"], {}) if isinstance(scenarios, dict) else {}
        )
        if best_total_violations > 0:
            flags.append(
                {
                    "type": "best_has_violations",
                    "severity": "warning",
                    "message": (
                        f"Top-ranked scenario '{best_entry['name']}' still has "
                        f"{best_total_violations} violation(s)"
                    ),
                    "name": best_entry["name"],
                    "total_violations": best_total_violations,
                }
            )

    successful_names = [entry["name"] for entry in successful_entries]
    if successful_names:
        totals = [
            _scenario_total_violations(scenarios.get(name, {})) if isinstance(scenarios, dict) else 0
            for name in successful_names
        ]
        if totals and all(total > 0 for total in totals):
            flags.append(
                {
                    "type": "all_have_violations",
                    "severity": "warning",
                    "message": "All successful scenarios have compliance violations",
                    "scenario_count": len(successful_names),
                }
            )

    return _sort_flags(flags)


def _successful_ranked_entries(ranking: Any, scenarios: Any) -> list[dict]:
    if not isinstance(ranking, list):
        return []

    entries: list[dict] = []
    for row in ranking:
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        if not name:
            continue

        status = row.get("status")
        if status is None and isinstance(scenarios, dict):
            status = (scenarios.get(name) or {}).get("status", "success")
        if status != "success":
            continue

        rank_value = _safe_float(row.get("rank_value"))
        entries.append(
            {
                "name": str(name),
                "rank_value": rank_value,
                "rank_by": row.get("rank_by"),
            }
        )
    return entries


def _directional_gap(v1: float, v2: float, rank_order: str) -> float:
    return (v2 - v1) if rank_order == "asc" else (v1 - v2)


def _status_counts(summary: Any, scenarios: Any) -> tuple[int, int]:
    if isinstance(summary, dict):
        succeeded = summary.get("succeeded")
        failed = summary.get("failed")
        if isinstance(succeeded, int) and isinstance(failed, int):
            return succeeded, failed

    succeeded = 0
    failed = 0
    if isinstance(scenarios, dict):
        for payload in scenarios.values():
            status = payload.get("status") if isinstance(payload, dict) else None
            if status == "success":
                succeeded += 1
            elif status == "error":
                failed += 1
    return succeeded, failed


def _scenario_total_violations(scenario_payload: Any) -> int:
    if not isinstance(scenario_payload, dict):
        return 0

    snapshot = scenario_payload.get("snapshot")
    if not isinstance(snapshot, dict):
        snapshot = scenario_payload
    compliance = snapshot.get("compliance", {}) if isinstance(snapshot, dict) else {}
    if not isinstance(compliance, dict):
        return 0

    total = 0
    for key in ("risk_violation_count", "factor_violation_count", "proxy_violation_count"):
        value = _safe_float(compliance.get(key))
        if value is not None:
            total += int(value)
    return total


def _safe_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def _sort_flags(flags: list[dict]) -> list[dict]:
    order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    return sorted(flags, key=lambda flag: order.get(flag.get("severity", "info"), 2))

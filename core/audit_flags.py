"""Workflow action audit flags for agent-oriented responses."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _sort_flags(flags: list[dict]) -> list[dict]:
    order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    return sorted(flags, key=lambda flag: order.get(flag.get("severity", "info"), 2))


def generate_audit_flags(snapshot: dict) -> list[dict]:
    """Generate severity-tagged audit flags from action history snapshot."""
    if not isinstance(snapshot, dict):
        return []

    actions = snapshot.get("actions") if isinstance(snapshot.get("actions"), list) else []
    if not actions:
        return _sort_flags(
            [
                {
                    "flag": "no_history",
                    "severity": "info",
                    "message": "No workflow action history recorded for this portfolio",
                }
            ]
        )

    flags: list[dict] = []

    now_value = snapshot.get("now")
    now = _parse_datetime(now_value) if now_value is not None else None
    if now is None:
        now = datetime.now()

    stale_threshold = now - timedelta(days=7)
    stale_pending = 0
    unresolved_violations = 0
    rejected_count = 0
    accepted_like_count = 0
    executed_count = 0

    for action in actions:
        if not isinstance(action, dict):
            continue

        status = str(action.get("action_status") or "").strip().lower()
        if status == "rejected":
            rejected_count += 1
        if status in {"accepted", "executed"}:
            accepted_like_count += 1
        if status == "executed":
            executed_count += 1

        if status != "pending":
            continue

        created_at = _parse_datetime(action.get("created_at"))
        if created_at is not None and created_at <= stale_threshold:
            stale_pending += 1

        if (
            str(action.get("flag_severity") or "").strip().lower() == "error"
            and str(action.get("source_flag") or "").strip()
        ):
            unresolved_violations += 1

    if stale_pending > 0:
        flags.append(
            {
                "flag": "stale_pending_actions",
                "severity": "warning",
                "message": f"{stale_pending} pending action(s) are older than 7 days",
                "stale_count": stale_pending,
            }
        )

    total_actions = sum(1 for action in actions if isinstance(action, dict))
    if total_actions >= 5:
        rejection_rate = rejected_count / total_actions
        if rejection_rate > 0.50:
            flags.append(
                {
                    "flag": "high_rejection_rate",
                    "severity": "info",
                    "message": f"Rejection rate is {rejection_rate:.0%} over {total_actions} recent actions",
                    "rejection_rate": round(rejection_rate, 4),
                }
            )

    if accepted_like_count >= 5:
        execution_rate = executed_count / accepted_like_count
        if execution_rate < 0.25:
            flags.append(
                {
                    "flag": "low_execution_rate",
                    "severity": "info",
                    "message": (
                        f"Execution rate is {execution_rate:.0%} for {accepted_like_count} accepted action(s)"
                    ),
                    "execution_rate": round(execution_rate, 4),
                }
            )

    if unresolved_violations > 0:
        flags.append(
            {
                "flag": "unresolved_violations",
                "severity": "warning",
                "message": (
                    f"{unresolved_violations} pending action(s) remain for error-severity violations"
                ),
                "count": unresolved_violations,
            }
        )

    return _sort_flags(flags)

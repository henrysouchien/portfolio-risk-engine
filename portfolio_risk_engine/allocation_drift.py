"""Helpers for computing asset-allocation drift against configured targets."""

from __future__ import annotations

from typing import Any, Dict, List


DRIFT_ON_TARGET_THRESHOLD = 2.0
DRIFT_WARNING_THRESHOLD = 5.0


def compute_allocation_drift(
    current_allocation: Dict[str, float],
    target_allocation: Dict[str, float],
) -> List[Dict[str, Any]]:
    """Compute per-class drift in percentage points.

    All values use percentage points (40.0 means 40%).
    """
    drift_rows: List[Dict[str, Any]] = []

    for asset_class, raw_target in (target_allocation or {}).items():
        if raw_target is None:
            continue
        try:
            target_pct = float(raw_target)
        except (TypeError, ValueError):
            continue

        raw_current = (current_allocation or {}).get(asset_class, 0.0)
        try:
            current_pct = float(raw_current)
        except (TypeError, ValueError):
            current_pct = 0.0

        drift_pct = current_pct - target_pct
        abs_drift = abs(drift_pct)

        if abs_drift < DRIFT_ON_TARGET_THRESHOLD:
            drift_status = "on_target"
            drift_severity = "info"
        elif drift_pct > 0:
            drift_status = "overweight"
            drift_severity = "warning" if abs_drift >= DRIFT_WARNING_THRESHOLD else "info"
        else:
            drift_status = "underweight"
            drift_severity = "warning" if abs_drift >= DRIFT_WARNING_THRESHOLD else "info"

        drift_rows.append(
            {
                "asset_class": asset_class,
                "current_pct": round(current_pct, 1),
                "target_pct": round(target_pct, 1),
                "drift_pct": round(drift_pct, 1),
                "drift_status": drift_status,
                "drift_severity": drift_severity,
            }
        )

    return drift_rows

"""Seed profile templates and risk-limit derivation helpers.

All risk limits are unlevered — they represent target thresholds for an
unlevered portfolio.  The risk analysis engine automatically accounts for
actual portfolio leverage when computing realised metrics, so a leveraged
portfolio is compared against these unlevered limits.
"""

from __future__ import annotations

import copy
import math
from typing import Any, Dict, Optional

_STRUCTURAL_PARAM_KEYS = (
    "max_single_stock_weight",
    "max_factor_contribution",
    "max_market_contribution",
    "max_industry_contribution",
    "max_single_factor_loss",
)

STRUCTURAL_PARAM_RANGES: Dict[str, tuple[float, float]] = {
    "max_single_stock_weight": (0.01, 1.0),
    "max_factor_contribution": (0.01, 1.0),
    "max_market_contribution": (0.01, 1.0),
    "max_industry_contribution": (0.01, 1.0),
    "max_single_factor_loss": (-0.50, -0.01),
}

PROFILE_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "income": {
        "label": "Income / Concentrated",
        "description": "High-yield, concentrated positions. Tolerates sector concentration. All limits are unlevered; analysis adjusts for actual leverage.",
        "default_max_loss": 0.25,
        "default_vol_target": 0.20,
        "params": {
            "max_single_stock_weight": 0.45,
            "max_factor_contribution": 0.85,
            "max_market_contribution": 0.60,
            "max_industry_contribution": 0.50,
            "max_single_factor_loss": -0.15,
        },
    },
    "growth": {
        "label": "Growth Equity",
        "description": "Moderate concentration, higher beta tolerance. All limits are unlevered; analysis adjusts for actual leverage.",
        "default_max_loss": 0.20,
        "default_vol_target": 0.18,
        "params": {
            "max_single_stock_weight": 0.25,
            "max_factor_contribution": 0.80,
            "max_market_contribution": 0.55,
            "max_industry_contribution": 0.35,
            "max_single_factor_loss": -0.12,
        },
    },
    "trading": {
        "label": "Active Trading",
        "description": "Tight concentration, wider factor variance, tighter vol. All limits are unlevered; analysis adjusts for actual leverage.",
        "default_max_loss": 0.15,
        "default_vol_target": 0.15,
        "params": {
            "max_single_stock_weight": 0.15,
            "max_factor_contribution": 0.85,
            "max_market_contribution": 0.55,
            "max_industry_contribution": 0.40,
            "max_single_factor_loss": -0.12,
        },
    },
    "balanced": {
        "label": "Balanced / Diversified",
        "description": "Middle-ground allocation across sectors and factors. All limits are unlevered; analysis adjusts for actual leverage.",
        "default_max_loss": 0.20,
        "default_vol_target": 0.18,
        "params": {
            "max_single_stock_weight": 0.25,
            "max_factor_contribution": 0.70,
            "max_market_contribution": 0.50,
            "max_industry_contribution": 0.35,
            "max_single_factor_loss": -0.10,
        },
    },
}


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def validate_profile_params(params: Dict[str, Any]) -> Dict[str, float]:
    """Validate and normalize all required structural profile parameters."""
    if not isinstance(params, dict):
        raise ValueError("profile_params must be a dictionary")

    missing = [key for key in _STRUCTURAL_PARAM_KEYS if key not in params]
    if missing:
        raise ValueError(f"profile_params missing required keys: {', '.join(missing)}")

    normalized: Dict[str, float] = {}
    for key in _STRUCTURAL_PARAM_KEYS:
        raw_value = params.get(key)
        if isinstance(raw_value, bool):
            raise ValueError(f"profile_params.{key} must be numeric")
        try:
            value = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"profile_params.{key} must be numeric") from exc
        if not math.isfinite(value):
            raise ValueError(f"profile_params.{key} must be finite")

        if key == "max_single_factor_loss" and value > 0:
            value = -value

        lower, upper = STRUCTURAL_PARAM_RANGES[key]
        normalized[key] = _clamp(value, lower, upper)

    return normalized


def get_template(name: str) -> Optional[Dict[str, Any]]:
    """Get a profile template by name."""
    normalized_name = str(name or "").strip().lower()
    template = PROFILE_TEMPLATES.get(normalized_name)
    return copy.deepcopy(template) if template else None


def derive_risk_limits(
    profile_params: Dict[str, Any],
    max_loss: float,
    vol_target: float,
) -> Dict[str, Any]:
    """Build a risk-limits payload compatible with RiskLimitsData.from_dict()."""
    if max_loss is None:
        raise ValueError("max_loss is required")
    if vol_target is None:
        raise ValueError("vol_target is required")

    params = validate_profile_params(profile_params)
    max_loss_value = abs(float(max_loss))
    vol_target_value = abs(float(vol_target))

    return {
        "portfolio_limits": {
            "max_volatility": vol_target_value,
            "max_loss": -max_loss_value,
        },
        "concentration_limits": {
            "max_single_stock_weight": params["max_single_stock_weight"],
        },
        "variance_limits": {
            "max_factor_contribution": params["max_factor_contribution"],
            "max_market_contribution": params["max_market_contribution"],
            "max_industry_contribution": params["max_industry_contribution"],
        },
        "max_single_factor_loss": params["max_single_factor_loss"],
    }


def list_templates() -> Dict[str, Dict[str, Any]]:
    """Return template definitions for UI/MCP display."""
    return copy.deepcopy(PROFILE_TEMPLATES)


def list_profiles() -> Dict[str, Dict[str, Any]]:
    """Backward-compatible alias for list_templates()."""
    return list_templates()

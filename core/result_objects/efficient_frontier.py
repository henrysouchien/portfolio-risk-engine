"""Efficient frontier result object."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Dict, Iterable


@dataclass
class EfficientFrontierResult:
    """Structured efficient frontier output for MCP and REST consumers."""

    frontier_points: list[Any]
    current_portfolio: Dict[str, Any]
    min_variance_point: Any
    max_return_point: Any
    n_feasible: int
    n_requested: int
    computation_time_s: float
    analysis_date: datetime = field(default_factory=lambda: datetime.now(UTC))

    @staticmethod
    def _serialize_point(point: Any) -> Dict[str, Any]:
        """Convert a frontier point object or dict into API-safe percentages."""
        if hasattr(point, "volatility"):
            volatility = float(point.volatility)
            expected_return = float(point.expected_return)
            label = str(point.label)
            is_feasible = bool(point.is_feasible)
        else:
            point_dict = dict(point or {})
            volatility = float(point_dict.get("volatility", 0.0) or 0.0)
            expected_return = float(point_dict.get("expected_return", 0.0) or 0.0)
            label = str(point_dict.get("label", ""))
            is_feasible = bool(point_dict.get("is_feasible", True))

        return {
            "volatility_pct": round(volatility * 100.0, 2),
            "expected_return_pct": round(expected_return * 100.0, 2),
            "label": label,
            "is_feasible": is_feasible,
        }

    def to_api_response(self) -> Dict[str, Any]:
        """Serialize the result to the compact API payload used by Phase 2."""
        return {
            "frontier_points": [self._serialize_point(point) for point in self.frontier_points],
            "current_portfolio": {
                "volatility_pct": round(float(self.current_portfolio.get("volatility", 0.0) or 0.0) * 100.0, 2),
                "expected_return_pct": round(
                    float(self.current_portfolio.get("expected_return", 0.0) or 0.0) * 100.0,
                    2,
                ),
            },
            "min_variance": self._serialize_point(self.min_variance_point),
            "max_return": self._serialize_point(self.max_return_point),
            "meta": {
                "n_feasible": int(self.n_feasible),
                "n_requested": int(self.n_requested),
                "computation_time_s": round(float(self.computation_time_s), 1),
                "analysis_date": self.analysis_date.isoformat(),
            },
        }

    def get_summary(self) -> Dict[str, Any]:
        """Return the lightweight summary used in API response envelopes."""
        min_point = self._serialize_point(self.min_variance_point)
        max_point = self._serialize_point(self.max_return_point)
        return {
            "type": "efficient_frontier",
            "n_frontier_points": int(self.n_feasible),
            "n_requested": int(self.n_requested),
            "min_variance_volatility_pct": min_point["volatility_pct"],
            "max_return_pct": max_point["expected_return_pct"],
            "current_portfolio_volatility_pct": round(
                float(self.current_portfolio.get("volatility", 0.0) or 0.0) * 100.0,
                2,
            ),
            "current_portfolio_return_pct": round(
                float(self.current_portfolio.get("expected_return", 0.0) or 0.0) * 100.0,
                2,
            ),
            "computation_time_s": round(float(self.computation_time_s), 1),
        }

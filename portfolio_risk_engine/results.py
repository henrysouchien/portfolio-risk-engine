"""Lightweight result objects with optional monorepo compatibility passthrough."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

from portfolio_risk_engine._vendor import make_json_safe


try:  # pragma: no cover - prefer rich legacy classes inside monorepo
    from core.result_objects import (  # type: ignore
        PerformanceResult,
        OptimizationResult,
        WhatIfResult,
        StockAnalysisResult,
        RiskScoreResult,
    )
except Exception:  # pragma: no cover - standalone fallback

    @dataclass
    class _BaseResult:
        payload: Dict[str, Any] = field(default_factory=dict)

        def to_api_response(self) -> Dict[str, Any]:
            return make_json_safe(self.payload)

        def to_cli_report(self) -> str:
            return str(self.to_api_response())

    @dataclass
    class PerformanceResult(_BaseResult):
        @classmethod
        def from_core_analysis(cls, **kwargs: Any) -> "PerformanceResult":
            return cls(payload=kwargs)

    @dataclass
    class OptimizationResult(_BaseResult):
        @classmethod
        def from_core_optimization(cls, **kwargs: Any) -> "OptimizationResult":
            return cls(payload=kwargs)

    @dataclass
    class WhatIfResult(_BaseResult):
        @classmethod
        def from_core_scenario(cls, **kwargs: Any) -> "WhatIfResult":
            return cls(payload=kwargs)

    @dataclass
    class StockAnalysisResult(_BaseResult):
        @classmethod
        def from_core_analysis(cls, **kwargs: Any) -> "StockAnalysisResult":
            return cls(payload=kwargs)

    @dataclass
    class RiskScoreResult(_BaseResult):
        @classmethod
        def from_risk_score_analysis(cls, **kwargs: Any) -> "RiskScoreResult":
            return cls(payload=kwargs)

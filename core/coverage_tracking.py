"""Coverage tracking primitives for factor modeling pipelines."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ModelingStatus(str, Enum):
    FULLY_MODELED = "FULLY_MODELED"
    PARTIALLY_MODELED = "PARTIALLY_MODELED"
    UNRESOLVED_IDENTITY = "UNRESOLVED_IDENTITY"
    EXCLUDED_NO_PROXY = "EXCLUDED_NO_PROXY"
    EXCLUDED_NO_HISTORY = "EXCLUDED_NO_HISTORY"
    EXCLUDED_CLASSIFICATION_FAILED = "EXCLUDED_CLASSIFICATION_FAILED"
    EXCLUDED_CASH = "EXCLUDED_CASH"


@dataclass(frozen=True, slots=True)
class FactorCoverage:
    modeled: bool
    detail: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {"modeled": self.modeled, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class SecurityCoverage:
    security_key: str
    factors: dict[str, FactorCoverage]
    overall_status: ModelingStatus
    excluded_at: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "security_key": self.security_key,
            "factors": {name: coverage.to_dict() for name, coverage in self.factors.items()},
            "overall_status": self.overall_status.value,
            "excluded_at": self.excluded_at,
        }


@dataclass(slots=True)
class PortfolioCoverage:
    securities: dict[str, SecurityCoverage] = field(default_factory=dict)

    def add(self, coverage: SecurityCoverage) -> None:
        self.securities[coverage.security_key] = coverage

    @property
    def modeled_count(self) -> int:
        return sum(
            1 for coverage in self.securities.values()
            if coverage.overall_status == ModelingStatus.FULLY_MODELED
        )

    @property
    def excluded_count(self) -> int:
        excluded_statuses = {
            ModelingStatus.EXCLUDED_NO_PROXY,
            ModelingStatus.EXCLUDED_NO_HISTORY,
            ModelingStatus.EXCLUDED_CLASSIFICATION_FAILED,
            ModelingStatus.EXCLUDED_CASH,
        }
        return sum(
            1 for coverage in self.securities.values()
            if coverage.overall_status in excluded_statuses
        )

    @property
    def partial_count(self) -> int:
        return sum(
            1 for coverage in self.securities.values()
            if coverage.overall_status == ModelingStatus.PARTIALLY_MODELED
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "modeled_count": self.modeled_count,
            "excluded_count": self.excluded_count,
            "partial_count": self.partial_count,
            "securities": {
                security_key: coverage.to_dict()
                for security_key, coverage in self.securities.items()
            },
        }

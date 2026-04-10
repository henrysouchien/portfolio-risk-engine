"""Provider freshness metadata for brokerage-backed reads."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


def _serialize_dt(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


@dataclass(frozen=True)
class ProviderFreshness:
    """Per-provider status surfaced alongside store-backed position data."""

    provider: str
    as_of: datetime | None = None
    status: str = "unknown"
    last_error: str | None = None
    last_success_at: datetime | None = None
    last_attempt_at: datetime | None = None
    consecutive_failures: int = 0
    circuit_state: str = "closed"
    circuit_opened_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-ready freshness metadata."""

        return {
            "provider": self.provider,
            "as_of": _serialize_dt(self.as_of),
            "status": self.status,
            "last_error": self.last_error,
            "last_success_at": _serialize_dt(self.last_success_at),
            "last_attempt_at": _serialize_dt(self.last_attempt_at),
            "consecutive_failures": int(self.consecutive_failures or 0),
            "circuit_state": self.circuit_state,
            "circuit_opened_at": _serialize_dt(self.circuit_opened_at),
            "metadata": dict(self.metadata or {}),
        }

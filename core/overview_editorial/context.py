"""Shared context object for Overview editorial generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

ToolStatus = Literal["loaded", "partial", "failed"]


@dataclass(frozen=True)
class PortfolioContext:
    user_id: int
    portfolio_id: str | None
    portfolio_name: str
    tool_results: dict[str, dict[str, Any]]
    data_status: dict[str, ToolStatus]
    editorial_memory: dict[str, Any]
    previous_brief_anchor: dict[str, Any] | None
    generated_at: datetime

    def tool_snapshot(self, name: str) -> dict[str, Any] | None:
        if self.data_status.get(name) == "failed":
            return None
        tool_result = self.tool_results.get(name) or {}
        snapshot = tool_result.get("snapshot")
        return snapshot if isinstance(snapshot, dict) else None

    def tool_flags(self, name: str) -> list[dict[str, Any]]:
        if self.data_status.get(name) == "failed":
            return []
        tool_result = self.tool_results.get(name) or {}
        flags = tool_result.get("flags")
        return list(flags) if isinstance(flags, list) else []

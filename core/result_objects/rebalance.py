"""Rebalance trade result objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.serialization import make_json_safe


@dataclass
class RebalanceLeg:
    """Single rebalance trade leg."""

    ticker: str
    side: str
    quantity: float
    estimated_value: float
    current_weight: float
    target_weight: float
    weight_delta: float
    price: float
    status: str = "computed"
    preview_id: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return make_json_safe(
            {
                "ticker": self.ticker,
                "side": self.side,
                "quantity": self.quantity,
                "estimated_value": self.estimated_value,
                "current_weight": self.current_weight,
                "target_weight": self.target_weight,
                "weight_delta": self.weight_delta,
                "price": self.price,
                "status": self.status,
                "preview_id": self.preview_id,
                "error": self.error,
            }
        )


@dataclass
class RebalanceTradeResult:
    """Aggregate rebalance trade result."""

    status: str
    trades: List[RebalanceLeg] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)
    portfolio_value: float = 0.0
    residual_cash: float = 0.0
    skipped_trades: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def get_agent_snapshot(self) -> Dict[str, Any]:
        snapshot = {
            "portfolio_value": float(self.portfolio_value or 0.0),
            "target_weight_sum": float(self.summary.get("target_weight_sum", 0.0) or 0.0),
            "trade_count": int(self.summary.get("trade_count", len(self.trades)) or 0),
            "sell_count": int(self.summary.get("sell_count", 0) or 0),
            "buy_count": int(self.summary.get("buy_count", 0) or 0),
            "total_sell_value": float(self.summary.get("total_sell_value", 0.0) or 0.0),
            "total_buy_value": float(self.summary.get("total_buy_value", 0.0) or 0.0),
            "net_cash_impact": float(self.summary.get("net_cash_impact", 0.0) or 0.0),
            "residual_cash": float(self.residual_cash or 0.0),
            "skipped_count": len(self.skipped_trades),
            "unmanaged_mode": str(self.summary.get("unmanaged_mode") or "hold"),
            "unmanaged_positions": list(self.summary.get("unmanaged_positions") or []),
            "trades": [leg.to_dict() for leg in self.trades],
            "skipped_trades": list(self.skipped_trades or []),
            "warnings": list(self.warnings or []),
        }
        return make_json_safe(snapshot)

    def to_api_response(self) -> Dict[str, Any]:
        payload = {
            "status": self.status,
            "analysis_type": "rebalance_trades",
            "portfolio_value": float(self.portfolio_value or 0.0),
            "summary": dict(self.summary or {}),
            "trades": [leg.to_dict() for leg in self.trades],
            "skipped_trades": list(self.skipped_trades or []),
            "residual_cash": float(self.residual_cash or 0.0),
            "warnings": list(self.warnings or []),
        }
        return make_json_safe(payload)

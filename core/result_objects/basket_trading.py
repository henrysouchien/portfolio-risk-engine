"""Basket trading result objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.serialization import make_json_safe


@dataclass
class BasketTradeLeg:
    """Single basket trade preview leg."""

    ticker: str
    side: str
    quantity: float
    estimated_price: Optional[float]
    estimated_total: Optional[float]
    preview_id: Optional[str]
    pre_trade_weight: Optional[float]
    post_trade_weight: Optional[float]
    target_weight: Optional[float]
    status: str
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return make_json_safe(
            {
                "ticker": self.ticker,
                "side": self.side,
                "quantity": self.quantity,
                "estimated_price": self.estimated_price,
                "estimated_total": self.estimated_total,
                "preview_id": self.preview_id,
                "pre_trade_weight": self.pre_trade_weight,
                "post_trade_weight": self.post_trade_weight,
                "target_weight": self.target_weight,
                "status": self.status,
                "error": self.error,
            }
        )


@dataclass
class BasketTradePreviewResult:
    """Aggregate basket trade preview result."""

    status: str
    basket_name: str
    action: str
    preview_legs: List[BasketTradeLeg] = field(default_factory=list)
    total_estimated_cost: float = 0.0
    total_legs: int = 0
    buy_legs: int = 0
    sell_legs: int = 0
    skipped_legs: int = 0
    warnings: List[str] = field(default_factory=list)
    error: Optional[str] = None

    def get_agent_snapshot(self) -> Dict[str, Any]:
        preview_ids = [
            leg.preview_id
            for leg in self.preview_legs
            if leg.status == "success" and leg.preview_id is not None
        ]
        failed_legs = sum(1 for leg in self.preview_legs if leg.status != "success")
        snapshot = {
            "status": self.status,
            "basket_name": self.basket_name,
            "action": self.action,
            "total_estimated_cost": float(self.total_estimated_cost or 0.0),
            "total_legs": self.total_legs,
            "buy_legs": self.buy_legs,
            "sell_legs": self.sell_legs,
            "skipped_legs": self.skipped_legs,
            "successful_legs": len(preview_ids),
            "failed_legs": failed_legs,
            "preview_ids": preview_ids,
            "legs": [
                {
                    "ticker": leg.ticker,
                    "side": leg.side,
                    "quantity": leg.quantity,
                    "status": leg.status,
                    "preview_id": leg.preview_id,
                    "error": leg.error,
                }
                for leg in self.preview_legs
            ],
            "warnings": list(self.warnings or []),
        }
        return make_json_safe(snapshot)

    def to_api_response(self) -> Dict[str, Any]:
        payload = {
            "analysis_type": "basket_trade_preview",
            "status": self.status,
            "basket_name": self.basket_name,
            "action": self.action,
            "preview_legs": [leg.to_dict() for leg in self.preview_legs],
            "total_estimated_cost": float(self.total_estimated_cost or 0.0),
            "total_legs": self.total_legs,
            "buy_legs": self.buy_legs,
            "sell_legs": self.sell_legs,
            "skipped_legs": self.skipped_legs,
            "warnings": list(self.warnings or []),
            "error": self.error,
            "agent_snapshot": self.get_agent_snapshot(),
        }
        return make_json_safe(payload)


@dataclass
class BasketExecutionLeg:
    """Single basket execution leg."""

    ticker: str
    side: str
    quantity: Optional[float]
    filled_quantity: Optional[float]
    average_fill_price: Optional[float]
    total_cost: Optional[float]
    order_status: Optional[str]
    brokerage_order_id: Optional[str]
    preview_id: Optional[str]
    error: Optional[str] = None
    new_preview_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return make_json_safe(
            {
                "ticker": self.ticker,
                "side": self.side,
                "quantity": self.quantity,
                "filled_quantity": self.filled_quantity,
                "average_fill_price": self.average_fill_price,
                "total_cost": self.total_cost,
                "order_status": self.order_status,
                "brokerage_order_id": self.brokerage_order_id,
                "preview_id": self.preview_id,
                "error": self.error,
                "new_preview_id": self.new_preview_id,
            }
        )


@dataclass
class BasketTradeExecutionResult:
    """Aggregate basket execution result."""

    status: str
    execution_legs: List[BasketExecutionLeg] = field(default_factory=list)
    reprieved_legs: List[BasketExecutionLeg] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def get_agent_snapshot(self) -> Dict[str, Any]:
        reprieved_preview_ids = [
            leg.new_preview_id for leg in self.reprieved_legs if leg.new_preview_id
        ]
        total_cost = self.summary.get("total_cost")
        if total_cost is None:
            total_cost = sum(float(leg.total_cost or 0.0) for leg in self.execution_legs)
        snapshot = {
            "status": self.status,
            "requested_legs": self.summary.get("requested_legs", len(self.execution_legs)),
            "succeeded_legs": self.summary.get("succeeded_legs"),
            "failed_legs": self.summary.get("failed_legs"),
            "reprieved_legs": self.summary.get("reprieved_legs", len(self.reprieved_legs)),
            "total_cost": float(total_cost or 0.0),
            "reprieved_preview_ids": reprieved_preview_ids,
            "legs": [
                {
                    "ticker": leg.ticker,
                    "side": leg.side,
                    "quantity": leg.quantity,
                    "order_status": leg.order_status,
                    "preview_id": leg.preview_id,
                    "new_preview_id": leg.new_preview_id,
                    "error": leg.error,
                }
                for leg in self.execution_legs
            ],
            "warnings": list(self.warnings or []),
        }
        return make_json_safe(snapshot)

    def to_api_response(self) -> Dict[str, Any]:
        payload = {
            "analysis_type": "basket_trade_execution",
            "status": self.status,
            "execution_legs": [leg.to_dict() for leg in self.execution_legs],
            "reprieved_legs": [leg.to_dict() for leg in self.reprieved_legs],
            "summary": dict(self.summary or {}),
            "warnings": list(self.warnings or []),
            "agent_snapshot": self.get_agent_snapshot(),
        }
        return make_json_safe(payload)


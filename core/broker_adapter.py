"""Abstract broker adapter interface for trade operations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BrokerAdapter(ABC):
    """Abstract interface for broker-specific trade operations."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider identifier (e.g., 'snaptrade', 'ibkr')."""

    @abstractmethod
    def owns_account(self, account_id: str) -> bool:
        """Return True if this adapter manages the given account_id."""

    @abstractmethod
    def list_accounts(self) -> List[Dict[str, Any]]:
        """List tradeable accounts managed by this broker."""

    @abstractmethod
    def search_symbol(self, account_id: str, ticker: str) -> Dict[str, Any]:
        """Resolve a ticker symbol for the given account."""

    @abstractmethod
    def preview_order(
        self,
        account_id: str,
        ticker: str,
        side: str,
        quantity: float,
        order_type: str,
        time_in_force: str,
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
        symbol_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Preview an order and return estimated cost/commission."""

    @abstractmethod
    def place_order(
        self,
        account_id: str,
        order_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Place an order and return execution details."""

    @abstractmethod
    def get_orders(
        self,
        account_id: str,
        state: str = "all",
        days: int = 30,
    ) -> List[Dict[str, Any]]:
        """Fetch order history from the broker."""

    @abstractmethod
    def cancel_order(
        self,
        account_id: str,
        order_id: str,
    ) -> Dict[str, Any]:
        """Cancel an order and return status."""

    @abstractmethod
    def get_account_balance(self, account_id: str) -> Optional[float]:
        """Return available cash balance for the account."""

    @abstractmethod
    def refresh_after_trade(self, account_id: str) -> None:
        """Trigger post-trade position refresh/cache invalidation."""

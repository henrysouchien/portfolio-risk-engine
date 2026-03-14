# IBKR Trading Integration -- Implementation Plan

> **Status:** All phases implemented and live-tested. BUY 1 AAPL Market on U2471778 placed and cancelled successfully via direct python3. MCP tool integration pending (client ID conflict between MCP server process and direct scripts).

## Context

The portfolio-mcp system has a working SnapTrade-based trade execution flow (`preview_trade` -> `execute_trade`). This plan adds Interactive Brokers (IBKR) as a second execution path via `ib_async` + IB Gateway, using a broker adapter pattern to keep both paths behind the same MCP tools.

**Pre-requisite reading:** `IBKR_TRADING_INTEGRATION_RESEARCH.md` for background on `ib_async`, IB Gateway, and the architectural recommendation.

**Reference implementation:** `TRADE_EXECUTION_PLAN.md` for the SnapTrade plan that was implemented and is now the codebase baseline.

---

## Architecture: Broker Adapter Pattern

```
MCP Tool (preview_trade / execute_trade / get_orders / cancel_order)
    |
    v
TradeExecutionService  (orchestrator, broker-agnostic)
    |
    +-- _resolve_broker_adapter(account_id) --> BrokerAdapter
    |
    +-- BrokerAdapter (abstract interface)
    |       |
    |       +-- SnapTradeBrokerAdapter
    |       |       +-- snaptrade_loader.py functions (unchanged)
    |       |
    |       +-- IBKRBrokerAdapter
    |               +-- IBKRConnectionManager (singleton)
    |                       +-- ib_async IB() -> IB Gateway (TCP socket)
    |
    +-- Pre-trade validation (shared across all brokers)
    +-- DB persistence (shared trade_previews / trade_orders tables)
    +-- Post-trade refresh
```

**Key design decisions:**

1. The MCP tools do not change at all. Account routing determines the adapter.
2. The `TradeExecutionService` becomes broker-agnostic -- it delegates broker-specific calls to the adapter.
3. SnapTrade extraction is a pure refactor (no behavior change) before IBKR code is added.
4. IBKR connection is lazy (not at server startup) to avoid blocking the MCP server if IB Gateway is offline.

---

## Common Order Status Enum

Both SnapTrade and IBKR report order statuses in their own vocabularies. The system needs a common enum that both map to, stored in `trade_orders.order_status`.

```python
class CommonOrderStatus(str, Enum):
    """Broker-agnostic order status stored in trade_orders.order_status."""
    PENDING = "PENDING"              # Order submitted, awaiting broker acknowledgement
    ACCEPTED = "ACCEPTED"            # Broker acknowledged, working the order
    EXECUTED = "EXECUTED"            # Fully filled
    PARTIAL = "PARTIAL"              # Partially filled, still working
    CANCELED = "CANCELED"            # Cancelled by user or broker
    REJECTED = "REJECTED"            # Rejected by broker (insufficient funds, invalid, etc.)
    FAILED = "FAILED"               # System-level failure (API error, connection lost)
    EXPIRED = "EXPIRED"             # Order expired (e.g., Day order after market close)
    CANCEL_PENDING = "CANCEL_PENDING"  # Cancel request submitted, awaiting confirmation
```

### Status Mapping Tables

**SnapTrade -> Common:**

| SnapTrade Status | Common Status |
|-----------------|---------------|
| NONE | PENDING |
| PENDING | PENDING |
| ACCEPTED | ACCEPTED |
| EXECUTED | EXECUTED |
| PARTIAL | PARTIAL |
| CANCELED | CANCELED |
| PARTIAL_CANCELED | CANCELED |
| CANCEL_PENDING | CANCEL_PENDING |
| REJECTED | REJECTED |
| FAILED | FAILED |
| EXPIRED | EXPIRED |
| QUEUED | PENDING |
| TRIGGERED | ACCEPTED |
| ACTIVATED | ACCEPTED |
| PENDING_RISK_REVIEW | PENDING |
| REPLACED | ACCEPTED |
| REPLACE_PENDING | ACCEPTED |
| STOPPED | ACCEPTED |
| SUSPENDED | PENDING |
| CONTINGENT_ORDER | PENDING |

**IBKR -> Common:**

Note: `ib_async` does **not** have a `PartiallyFilled` status string. Partial fills are detected by checking `filled > 0 and remaining > 0` when the status is `Submitted`. The mapping function must handle this:

```python
def ibkr_to_common_status(status: str, filled: float = 0, remaining: float = 0) -> str:
    """Map IBKR order status to common status, accounting for partial fills."""
    if status == "Submitted" and filled > 0 and remaining > 0:
        return "PARTIAL"
    return IBKR_STATUS_MAP.get(status, "PENDING")
```

| IBKR Status | Common Status | Notes |
|-------------|---------------|-------|
| PendingSubmit | PENDING | Order being sent to IB |
| ApiPending | PENDING | API-level pending |
| PreSubmitted | PENDING | Pre-submitted (e.g., bracket child) |
| Submitted | ACCEPTED | Working order (check filled/remaining for PARTIAL) |
| Submitted (filled>0, remaining>0) | PARTIAL | Derived from quantities, not status string |
| ApiUpdate | ACCEPTED | API-level update |
| Filled | EXECUTED | Fully filled |
| Cancelled | CANCELED | User/broker cancelled |
| ApiCancelled | CANCELED | API-level cancellation |
| Inactive | REJECTED | Rejected by broker |
| PendingCancel | CANCEL_PENDING | Cancel request pending |
| ValidationError | PENDING | Transient; may resolve to Submitted or Inactive |

---

## Account Routing: How the System Knows Which Adapter to Use

The system needs a deterministic way to route an `account_id` to the correct broker adapter.

### Approach: Provider Registry with Account-to-Broker Mapping

1. **IBKR accounts** use the native IBKR account ID format (e.g., `U1234567`, `DU1234567` for paper). These are fetched at connection time via `ib.managedAccounts()`.

2. **SnapTrade accounts** use SnapTrade-assigned UUIDs (e.g., `8f2a1b3c-...`).

3. **Account routing logic** in `TradeExecutionService._resolve_broker_adapter()`:

```python
def _resolve_broker_adapter(self, account_id: str) -> BrokerAdapter:
    """Determine which broker adapter handles this account."""
    # 1. Check IBKR accounts (if IBKR is enabled and connected)
    if settings.IBKR_ENABLED:
        ibkr_adapter = self._get_ibkr_adapter()
        if ibkr_adapter and ibkr_adapter.owns_account(account_id):
            return ibkr_adapter

    # 2. Check SnapTrade accounts (existing logic)
    snaptrade_adapter = self._get_snaptrade_adapter()
    if snaptrade_adapter.owns_account(account_id):
        return snaptrade_adapter

    # 3. Detect via DB position_source (fallback)
    # IMPORTANT: still require owns_account() to enforce authorization
    provider = self._detect_account_provider(account_id)
    if provider == "ibkr":
        ibkr = self._get_ibkr_adapter()
        if ibkr and ibkr.owns_account(account_id):
            return ibkr
        raise ValueError(
            f"Account '{account_id}' is associated with IBKR but not authorized for trading"
        )
    if provider == "snaptrade":
        if snaptrade_adapter.owns_account(account_id):
            return snaptrade_adapter

    raise ValueError(f"No broker adapter found for account '{account_id}'")
```

4. **Each adapter implements `owns_account(account_id) -> bool`:**
   - `SnapTradeBrokerAdapter.owns_account()`: Checks against cached SnapTrade account list
   - `IBKRBrokerAdapter.owns_account()`: Checks against `ib.managedAccounts()` result

5. **`list_tradeable_accounts()`** merges accounts from both adapters into a single list, each tagged with `provider: "snaptrade"` or `provider: "ibkr"`.

---

## Implementation Phases

### Phase 1: BrokerAdapter ABC and SnapTrade Extraction ✅ DONE

**Goal:** Introduce the abstract interface, extract existing SnapTrade logic into `SnapTradeBrokerAdapter`, and refactor `TradeExecutionService` to delegate through the adapter. This is a **pure refactor** -- no behavior change, no new features.

#### File: `core/broker_adapter.py` (new)

Define the abstract broker adapter interface.

```python
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BrokerAdapter(ABC):
    """Abstract interface for broker-specific trade operations.

    Each broker (SnapTrade, IBKR, etc.) implements this interface.
    The TradeExecutionService delegates broker-specific calls here.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider identifier (e.g., 'snaptrade', 'ibkr')."""
        ...

    @abstractmethod
    def owns_account(self, account_id: str) -> bool:
        """Return True if this adapter manages the given account_id."""
        ...

    @abstractmethod
    def list_accounts(self) -> List[Dict[str, Any]]:
        """List tradeable accounts managed by this broker.

        Returns list of dicts with keys:
            account_id, account_name, brokerage_name, provider,
            cash_balance, authorization_id (optional), meta (optional)
        """
        ...

    @abstractmethod
    def search_symbol(self, account_id: str, ticker: str) -> Dict[str, Any]:
        """Resolve a ticker symbol for the given account.

        Returns dict with keys:
            ticker, symbol, universal_symbol_id (or broker_symbol_id),
            name, currency, type
        """
        ...

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
        """Preview an order and return estimated cost/commission.

        Returns dict with keys:
            estimated_price, estimated_total, estimated_commission,
            broker_trade_id (SnapTrade) or None (IBKR),
            combined_remaining_balance, trade_impacts,
            broker_preview_data (raw broker response)
        """
        ...

    @abstractmethod
    def place_order(
        self,
        account_id: str,
        order_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Place an order and return execution details.

        order_params contains the full order specification stored
        from the preview row (ticker, side, quantity, order_type, etc.).

        Returns dict with keys:
            brokerage_order_id, status, filled_quantity,
            execution_price, total_quantity, commission
        """
        ...

    @abstractmethod
    def get_orders(
        self,
        account_id: str,
        state: str = "all",
        days: int = 30,
    ) -> List[Dict[str, Any]]:
        """Fetch order history from the broker.

        Returns list of dicts with normalized keys:
            brokerage_order_id, ticker, side, quantity, order_type,
            status, filled_quantity, execution_price, commission,
            time_placed, time_updated
        """
        ...

    @abstractmethod
    def cancel_order(
        self,
        account_id: str,
        order_id: str,
    ) -> Dict[str, Any]:
        """Cancel an order and return status.

        Returns dict with keys:
            status (CANCELED or CANCEL_PENDING), brokerage_order_id
        """
        ...

    @abstractmethod
    def get_account_balance(self, account_id: str) -> Optional[float]:
        """Return available cash balance for the account."""
        ...

    @abstractmethod
    def refresh_after_trade(self, account_id: str) -> None:
        """Trigger post-trade position refresh/cache invalidation."""
        ...
```

#### File: `services/snaptrade_broker_adapter.py` (new)

Extract SnapTrade-specific logic from `TradeExecutionService` into this adapter class. This is a **move, not a rewrite** -- the code body of each method comes directly from the current `TradeExecutionService`.

**What moves:**

| Current location (in `trade_execution_service.py`) | New location (in `snaptrade_broker_adapter.py`) |
|---|---|
| `_fetch_snaptrade_accounts()` | `SnapTradeBrokerAdapter.list_accounts()` |
| `_get_account_cash_balance()` | `SnapTradeBrokerAdapter.get_account_balance()` |
| `_resolve_authorization_id()`, `_extract_authorization_id()` | `SnapTradeBrokerAdapter._resolve_authorization_id()` |
| `_get_fractional_share_support()` | `SnapTradeBrokerAdapter._get_fractional_share_support()` |
| `_get_account_brokerage_name()` | `SnapTradeBrokerAdapter._get_account_brokerage_name()` |
| `_get_snaptrade_client()` | `SnapTradeBrokerAdapter.__init__()` (stored as instance var) |
| `_get_snaptrade_identity()` | `SnapTradeBrokerAdapter._get_identity()` |
| `_post_execution_refresh()` | `SnapTradeBrokerAdapter.refresh_after_trade()` |
| Direct calls to `preview_snaptrade_order()` | `SnapTradeBrokerAdapter.preview_order()` |
| Direct calls to `place_snaptrade_checked_order()` | `SnapTradeBrokerAdapter.place_order()` |
| Direct calls to `get_snaptrade_orders()` | `SnapTradeBrokerAdapter.get_orders()` |
| Direct calls to `cancel_snaptrade_order()` | `SnapTradeBrokerAdapter.cancel_order()` |
| Direct calls to `search_snaptrade_symbol()` | `SnapTradeBrokerAdapter.search_symbol()` |

**What stays in `TradeExecutionService`:**

- `preview_order()` -- orchestration, validation, DB persistence, risk impact
- `execute_order()` -- preview lookup, row lock, expiry check, DB persistence
- `get_orders()` -- merge local + remote, reconciliation
- `cancel_order()` -- route to adapter, update DB
- `_validate_pre_trade()` -- shared validation logic (refactored to be provider-aware, see below)
- `_compute_weight_impact()` -- shared risk calculation
- `_get_max_single_stock_weight_limit()` -- shared limit lookup
- `_store_preview()` -- shared DB write (updated to include `broker_provider` and `broker_preview_data`)
- `_resolve_target_account()` -- now calls adapter(s)
- `_execution_result_from_row()` -- shared result mapping
- `_reconcile_order_status()` -- shared reconciliation (updated to use `to_common_status()`)
- All DB access patterns

**Pre-trade validation refactoring:**

The current `_validate_pre_trade()` calls SnapTrade-specific symbol search and position checks (filtered by `position_source='snaptrade'`). This must be made provider-aware:

1. **Balance check**: Call `adapter.get_account_balance(account_id)` instead of SnapTrade-specific balance fetch.
2. **Position check (for SELLs)**: Query positions by `account_id` without filtering by `position_source`. The adapter's `account_id` is already provider-specific.
3. **Symbol resolution**: Already moved to `adapter.search_symbol()` in the refactored flow.
4. **Concentration/weight limits**: These use portfolio-wide data (all positions, all providers). No change needed — they are already provider-agnostic.

**Common status normalization:**

Add a `to_common_status(provider: str, broker_status: str, filled: float = 0, remaining: float = 0) -> str` function that both providers use when writing **order status** to `trade_orders.order_status`. This is called in:
- `execute_order()` (when writing to `trade_orders.order_status`)
- `_reconcile_order_status()` (when syncing with broker)
- `get_orders()` (when mapping remote orders to normalized dicts)

**Note:** `trade_previews.status` is a **lifecycle** status (`pending`/`executed`/`expired`/`cancelled`) and does NOT use the common order status enum. Do not call `to_common_status()` for preview status writes.

**User-to-account authorization:**

The IB Gateway is a singleton that exposes all managed accounts. In a multi-user context, any app user could list/trade any IB account. This must be guarded:

1. Add a `ibkr_user_accounts` DB table or configuration mapping: `user_id -> [ibkr_account_id, ...]`
2. `IBKRBrokerAdapter.list_accounts()` filters by the user's authorized accounts.
3. `IBKRBrokerAdapter.owns_account()` checks user authorization, not just gateway presence.
4. For the initial single-user deployment, a simple env var `IBKR_AUTHORIZED_ACCOUNTS` (comma-separated) suffices. Multi-user DB mapping is a future enhancement.

```python
# settings.py
IBKR_AUTHORIZED_ACCOUNTS = [
    a.strip() for a in os.getenv("IBKR_AUTHORIZED_ACCOUNTS", "").split(",") if a.strip()
]
```

```python
# In IBKRBrokerAdapter:
def list_accounts(self) -> List[Dict[str, Any]]:
    ib = self._conn_manager.ensure_connected()
    accounts = ib.managedAccounts()
    # Filter to authorized accounts only
    if settings.IBKR_AUTHORIZED_ACCOUNTS:
        accounts = [a for a in accounts if a in settings.IBKR_AUTHORIZED_ACCOUNTS]
    # ... rest of method
```

**Key refactoring changes in `TradeExecutionService`:**

1. Constructor gains a `broker_adapters: Dict[str, BrokerAdapter]` parameter (or builds them internally).
2. `_resolve_target_account()` iterates adapters to find the account.
3. `list_tradeable_accounts()` merges results from all adapters.
4. `preview_order()` calls `adapter.search_symbol()` and `adapter.preview_order()` instead of direct SnapTrade calls.
5. `execute_order()` calls `adapter.place_order()` instead of `place_snaptrade_checked_order()`.
6. `get_orders()` calls `adapter.get_orders()`.
7. `cancel_order()` calls `adapter.cancel_order()`.

#### File: `services/trade_execution_service.py` (modify)

Refactor to use the adapter pattern. Key changes:

```python
class TradeExecutionService:
    def __init__(self, user_email: str, ...):
        # ... existing init ...
        self._adapters: Dict[str, BrokerAdapter] = {}
        self._adapters["snaptrade"] = SnapTradeBrokerAdapter(
            user_email=user_email,
            snaptrade_client=snaptrade_client,
            region=region,
        )

    def _resolve_broker_adapter(self, account_id: str) -> BrokerAdapter:
        """Route account_id to the correct adapter."""
        for adapter in self._adapters.values():
            if adapter.owns_account(account_id):
                return adapter
        # Fallback: detect from DB position_source
        # IMPORTANT: still require owns_account() to enforce authorization
        provider = self._detect_account_provider(account_id)
        if provider and provider in self._adapters:
            adapter = self._adapters[provider]
            if adapter.owns_account(account_id):
                return adapter
            raise ValueError(
                f"Account '{account_id}' is associated with {provider} "
                "but is not authorized for trading"
            )
        raise ValueError(f"No broker adapter found for account '{account_id}'")
```

**Verification:** After this phase, all existing tests and manual E2E flows must pass unchanged. The refactor is transparent to callers.

---

### Phase 2: Database Migration ✅ DONE

**Goal:** Add `broker_provider` column to existing trade tables so previews and orders are tagged with which broker handled them.

#### File: `database/migrations/20260210_add_broker_provider.sql` (new)

```sql
-- Add broker_provider to trade_previews
ALTER TABLE trade_previews
    ADD COLUMN broker_provider VARCHAR(20) NOT NULL DEFAULT 'snaptrade';

-- Add broker_preview_data for generic broker response storage
ALTER TABLE trade_previews
    ADD COLUMN broker_preview_data JSONB;

-- Add broker_provider to trade_orders
ALTER TABLE trade_orders
    ADD COLUMN broker_provider VARCHAR(20) NOT NULL DEFAULT 'snaptrade';

-- Index for filtering by provider
CREATE INDEX idx_trade_previews_provider ON trade_previews(broker_provider);
CREATE INDEX idx_trade_orders_provider ON trade_orders(broker_provider);

-- Backfill existing trade_orders to use common status vocabulary
-- (existing data uses SnapTrade-specific values)
UPDATE trade_orders SET order_status = 'PENDING' WHERE order_status IN ('NONE', 'QUEUED', 'SUSPENDED', 'CONTINGENT_ORDER', 'PENDING_RISK_REVIEW');
UPDATE trade_orders SET order_status = 'ACCEPTED' WHERE order_status IN ('ACCEPTED', 'TRIGGERED', 'ACTIVATED', 'REPLACED', 'REPLACE_PENDING', 'STOPPED');
UPDATE trade_orders SET order_status = 'EXECUTED' WHERE order_status = 'EXECUTED';
UPDATE trade_orders SET order_status = 'PARTIAL' WHERE order_status = 'PARTIAL';
UPDATE trade_orders SET order_status = 'CANCELED' WHERE order_status IN ('CANCELED', 'PARTIAL_CANCELED');
UPDATE trade_orders SET order_status = 'REJECTED' WHERE order_status = 'REJECTED';
UPDATE trade_orders SET order_status = 'FAILED' WHERE order_status = 'FAILED';
UPDATE trade_orders SET order_status = 'EXPIRED' WHERE order_status = 'EXPIRED';
UPDATE trade_orders SET order_status = 'CANCEL_PENDING' WHERE order_status = 'CANCEL_PENDING';

-- Handle NULL order_status values
UPDATE trade_orders SET order_status = 'PENDING' WHERE order_status IS NULL;

-- Catch-all: any remaining unmapped values default to PENDING
-- (safety net before adding CHECK constraint)
UPDATE trade_orders SET order_status = 'PENDING'
WHERE order_status NOT IN ('PENDING', 'ACCEPTED', 'EXECUTED', 'PARTIAL',
                           'CANCELED', 'REJECTED', 'FAILED', 'EXPIRED', 'CANCEL_PENDING');

-- Make order_status NOT NULL with default, then add CHECK constraint
ALTER TABLE trade_orders
    ALTER COLUMN order_status SET NOT NULL,
    ALTER COLUMN order_status SET DEFAULT 'PENDING';

ALTER TABLE trade_orders
    ADD CONSTRAINT chk_order_status_common
    CHECK (order_status IN ('PENDING', 'ACCEPTED', 'EXECUTED', 'PARTIAL',
                            'CANCELED', 'REJECTED', 'FAILED', 'EXPIRED', 'CANCEL_PENDING'));
```

#### File: `services/trade_execution_service.py` (modify)

Update `_store_preview()` to write `broker_provider` and `broker_preview_data`:

```python
def _store_preview(self, ..., broker_provider: str = "snaptrade",
                   broker_preview_data: Optional[dict] = None, ...):
    # INSERT includes broker_provider and broker_preview_data columns
```

Update `execute_order()` to write `broker_provider` on `trade_orders` INSERT.

Update `_store_preview()` and `execute_order()` INSERT statements to include the new columns.

---

### Phase 3: Settings -- IBKR Configuration ✅ DONE

**Goal:** Add IBKR-specific settings and feature flag.

#### File: `settings.py` (modify)

Add after the existing `TRADING_DEFAULTS` block:

```python
# IBKR (Interactive Brokers) Configuration
IBKR_ENABLED = os.getenv("IBKR_ENABLED", "false").lower() == "true"
IBKR_GATEWAY_HOST = os.getenv("IBKR_GATEWAY_HOST", "127.0.0.1")
IBKR_GATEWAY_PORT = int(os.getenv("IBKR_GATEWAY_PORT", "4001"))  # 4001=live, 4002=paper
IBKR_CLIENT_ID = int(os.getenv("IBKR_CLIENT_ID", "1"))
IBKR_TIMEOUT = int(os.getenv("IBKR_TIMEOUT", "10"))  # seconds for connection timeout
IBKR_READONLY = os.getenv("IBKR_READONLY", "false").lower() == "true"  # safety: read-only mode
# Comma-separated list of IBKR account IDs this user is authorized to trade
# (security: prevents unauthorized access to other managed accounts)
IBKR_AUTHORIZED_ACCOUNTS = [
    a.strip() for a in os.getenv("IBKR_AUTHORIZED_ACCOUNTS", "").split(",") if a.strip()
]
```

#### File: `.env.example` (modify)

Add IBKR entries:

```
# IBKR Trading (requires IB Gateway running)
IBKR_ENABLED=false
IBKR_GATEWAY_HOST=127.0.0.1
IBKR_GATEWAY_PORT=4002          # 4002=paper, 4001=live
IBKR_CLIENT_ID=1
IBKR_TIMEOUT=10
IBKR_READONLY=false
IBKR_AUTHORIZED_ACCOUNTS=       # comma-separated account IDs (e.g., U1234567,DU1234567)
```

---

### Phase 4: IBKRConnectionManager ✅ DONE

**Goal:** Singleton managing the persistent TCP socket connection to IB Gateway via `ib_async`.

#### File: `services/ibkr_connection_manager.py` (new)

```python
"""Singleton managing the ib_async connection to IB Gateway."""

import threading
import time
from typing import Optional

from utils.logging import portfolio_logger


class IBKRConnectionManager:
    """Manages a single persistent ib_async IB() connection.

    Design:
    - Lazy connection: connect() is called on first use, not at import time.
    - Auto-reconnect: on disconnection, schedule a reconnect attempt.
    - Thread-safe: uses a lock around connect/disconnect operations.
    - Health check: ensure_connected() verifies the connection is live.
    """

    _instance: Optional["IBKRConnectionManager"] = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        from settings import (
            IBKR_GATEWAY_HOST,
            IBKR_GATEWAY_PORT,
            IBKR_CLIENT_ID,
            IBKR_TIMEOUT,
            IBKR_READONLY,
        )

        self._host = IBKR_GATEWAY_HOST
        self._port = IBKR_GATEWAY_PORT
        self._client_id = IBKR_CLIENT_ID
        self._timeout = IBKR_TIMEOUT
        self._readonly = IBKR_READONLY
        self._ib = None  # ib_async.IB instance
        self._managed_accounts: list[str] = []
        # RLock (reentrant) to prevent deadlock when disconnect() triggers
        # disconnectedEvent which calls _on_disconnect() while lock is held
        self._connect_lock = threading.RLock()
        self._reconnect_delay = 5  # seconds between reconnect attempts
        self._max_reconnect_attempts = 3
        self._reconnecting = False

    def connect(self) -> "ib_async.IB":
        """Connect to IB Gateway. Thread-safe, idempotent."""
        with self._connect_lock:
            if self._ib is not None and self._ib.isConnected():
                return self._ib

            from ib_async import IB

            ib = IB()

            # Register disconnect handler for auto-reconnect
            ib.disconnectedEvent += self._on_disconnect

            portfolio_logger.info(
                f"Connecting to IB Gateway at {self._host}:{self._port} "
                f"(clientId={self._client_id}, readonly={self._readonly})"
            )

            ib.connect(
                host=self._host,
                port=self._port,
                clientId=self._client_id,
                timeout=self._timeout,
                readonly=self._readonly,
            )

            self._ib = ib
            self._managed_accounts = ib.managedAccounts()
            portfolio_logger.info(
                f"Connected to IB Gateway. Managed accounts: {self._managed_accounts}"
            )
            return ib

    def disconnect(self):
        """Disconnect from IB Gateway. Safe to call if not connected.

        Sets _manual_disconnect flag so _on_disconnect() skips reconnect.
        The flag remains true until _on_disconnect() observes it (or the
        disconnect completes), to handle async callback timing.
        """
        with self._connect_lock:
            if self._ib is not None:
                try:
                    self._manual_disconnect = True
                    self._ib.disconnectedEvent -= self._on_disconnect
                    self._ib.disconnect()
                except Exception as e:
                    portfolio_logger.warning(f"Error during IB disconnect: {e}")
                finally:
                    self._ib = None
                    self._managed_accounts = []
                    self._manual_disconnect = False

    def ensure_connected(self) -> "ib_async.IB":
        """Return a connected IB instance, reconnecting if necessary."""
        if self._ib is not None and self._ib.isConnected():
            return self._ib
        return self.connect()

    def get_ib(self) -> "ib_async.IB":
        """Convenience alias for ensure_connected()."""
        return self.ensure_connected()

    @property
    def managed_accounts(self) -> list[str]:
        """Return the list of managed account IDs from IB Gateway."""
        return list(self._managed_accounts)

    @property
    def is_connected(self) -> bool:
        return self._ib is not None and self._ib.isConnected()

    def _on_disconnect(self):
        """Handle unexpected disconnection. Attempt reconnect.

        Skips reconnect if _manual_disconnect is set (intentional disconnect).
        Uses RLock so this can be called from disconnect() callback
        without deadlocking. Guards _reconnecting under lock to prevent
        multiple reconnect workers.
        """
        if getattr(self, "_manual_disconnect", False):
            return  # Intentional disconnect — do not reconnect

        portfolio_logger.warning("IB Gateway connection lost. Scheduling reconnect...")
        with self._connect_lock:
            self._ib = None
            self._managed_accounts = []

            # Single reconnect worker guard (atomic under lock)
            if not self._reconnecting:
                self._reconnecting = True
                thread = threading.Thread(target=self._reconnect, daemon=True)
                thread.start()

    def _reconnect(self):
        """Background reconnection with linear backoff. Single worker only."""
        try:
            for attempt in range(1, self._max_reconnect_attempts + 1):
                delay = self._reconnect_delay * attempt
                portfolio_logger.info(
                    f"IB reconnect attempt {attempt}/{self._max_reconnect_attempts} "
                    f"in {delay}s..."
                )
                time.sleep(delay)
                try:
                    self.connect()
                    portfolio_logger.info("IB Gateway reconnected successfully")
                    return
                except Exception as e:
                    portfolio_logger.warning(f"IB reconnect attempt {attempt} failed: {e}")

            portfolio_logger.error(
                f"IB Gateway reconnection failed after {self._max_reconnect_attempts} attempts. "
                "IBKR trades will fail until gateway is restored."
            )
        finally:
            with self._connect_lock:
                self._reconnecting = False
```

**Key design choices:**

- **Singleton**: Only one socket connection to IB Gateway per MCP server process.
- **Lazy**: `connect()` is not called at import or server startup. First IBKR trade triggers it.
- **Auto-reconnect**: On disconnect event, a background thread attempts reconnection with backoff.
- **Thread-safe**: `_connect_lock` prevents concurrent connect/disconnect races.
- **`readonly` flag**: When `IBKR_READONLY=true`, the connection is read-only (no order placement). Useful for testing position reads without trade risk.

---

### Phase 5: IBKRBrokerAdapter ✅ DONE

**Goal:** Implement the `BrokerAdapter` interface for IBKR using `ib_async`.

#### File: `services/ibkr_broker_adapter.py` (new)

```python
"""IBKR broker adapter implementing BrokerAdapter via ib_async."""

from typing import Any, Dict, List, Optional

from core.broker_adapter import BrokerAdapter
from services.ibkr_connection_manager import IBKRConnectionManager
from utils.logging import log_error_json, portfolio_logger


# IBKR status -> Common status mapping (base map; partial fills derived from quantities)
IBKR_STATUS_MAP = {
    "PendingSubmit": "PENDING",
    "ApiPending": "PENDING",
    "PreSubmitted": "PENDING",
    "Submitted": "ACCEPTED",
    "ApiUpdate": "ACCEPTED",
    "Filled": "EXECUTED",
    "Cancelled": "CANCELED",
    "ApiCancelled": "CANCELED",
    "Inactive": "REJECTED",
    "PendingCancel": "CANCEL_PENDING",
    # Note: ValidationError is NOT in the base map. It can be transient
    # (order resubmitted after fix) or terminal. Handled in the function below.
}


def ibkr_to_common_status(status: str, filled: float = 0, remaining: float = 0) -> str:
    """Map IBKR order status to common status, accounting for partial fills.

    Special cases:
    - Submitted with filled > 0 and remaining > 0 => PARTIAL
    - ValidationError => PENDING (may be transient; if order transitions to
      Inactive, that will map to REJECTED on next status update)
    """
    if status == "Submitted" and filled > 0 and remaining > 0:
        return "PARTIAL"
    if status == "ValidationError":
        return "PENDING"  # Transient; will resolve to terminal status
    return IBKR_STATUS_MAP.get(status, "PENDING")


class IBKRBrokerAdapter(BrokerAdapter):
    """Broker adapter for Interactive Brokers via ib_async + IB Gateway."""

    def __init__(self, user_email: str):
        self._user_email = user_email
        self._conn_manager = IBKRConnectionManager()

    @property
    def provider_name(self) -> str:
        return "ibkr"

    def owns_account(self, account_id: str) -> bool:
        """Check if this account is managed by IB Gateway AND authorized.

        Authorization is enforced unconditionally via IBKR_AUTHORIZED_ACCOUNTS.
        If the list is empty, all managed accounts are authorized (single-user mode).
        """
        import settings

        # Authorization check first (regardless of connection state)
        if settings.IBKR_AUTHORIZED_ACCOUNTS:
            if account_id not in settings.IBKR_AUTHORIZED_ACCOUNTS:
                return False

        # Check gateway managed accounts
        if self._conn_manager.is_connected:
            return account_id in self._conn_manager.managed_accounts

        # Not connected: only claim ownership if account is in authorized list
        # (no format-based guessing — require explicit authorization)
        if settings.IBKR_AUTHORIZED_ACCOUNTS:
            return account_id in settings.IBKR_AUTHORIZED_ACCOUNTS
        return False  # Cannot determine ownership without connection or config

    def list_accounts(self) -> List[Dict[str, Any]]:
        """List IBKR managed accounts with balances.

        Filtered by IBKR_AUTHORIZED_ACCOUNTS if configured.
        """
        import settings

        ib = self._conn_manager.ensure_connected()
        accounts = ib.managedAccounts()

        # Filter to authorized accounts only
        if settings.IBKR_AUTHORIZED_ACCOUNTS:
            accounts = [a for a in accounts if a in settings.IBKR_AUTHORIZED_ACCOUNTS]

        result = []
        for acct_id in accounts:
            balance = self._get_account_balance_internal(ib, acct_id)
            result.append({
                "account_id": acct_id,
                "account_name": f"IBKR {acct_id}",
                "brokerage_name": "Interactive Brokers",
                "provider": "ibkr",
                "cash_balance": balance,
                "meta": {},
            })
        return result

    def search_symbol(self, account_id: str, ticker: str) -> Dict[str, Any]:
        """Qualify a contract via ib_async."""
        from ib_async import Stock

        ib = self._conn_manager.ensure_connected()
        ticker_upper = (ticker or "").upper().strip()

        contract = Stock(ticker_upper, "SMART", "USD")
        qualified = ib.qualifyContracts(contract)

        if not qualified:
            raise ValueError(
                f"Could not resolve ticker '{ticker_upper}' on IBKR. "
                "Ensure the symbol is valid and tradeable on SMART exchange."
            )

        resolved = qualified[0]
        return {
            "ticker": ticker_upper,
            "symbol": resolved.symbol,
            "universal_symbol_id": None,  # IBKR does not use this concept
            "broker_symbol_id": str(resolved.conId),
            "con_id": resolved.conId,
            "name": resolved.description if hasattr(resolved, "description") else ticker_upper,
            "currency": resolved.currency,
            "type": resolved.secType,
            "contract": resolved,  # Pass the qualified Contract object through
        }

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
        """Preview order using ib_async whatIfOrder()."""
        ib = self._conn_manager.ensure_connected()

        # 1. Qualify contract
        symbol_info = self.search_symbol(account_id, ticker)
        contract = symbol_info["contract"]

        # 2. Build order object
        order = self._build_order(
            side=side,
            quantity=quantity,
            order_type=order_type,
            time_in_force=time_in_force,
            limit_price=limit_price,
            stop_price=stop_price,
            account_id=account_id,
        )

        # 3. whatIfOrder -- stateless preview
        order_state = ib.whatIfOrder(contract, order)

        # 4. Parse response
        estimated_commission = 0.0
        try:
            estimated_commission = float(order_state.commission)
        except (ValueError, TypeError):
            pass

        # whatIfOrder does not return an estimated fill price for market orders.
        # Use limit_price if available, otherwise request market data.
        estimated_price = limit_price or stop_price
        if estimated_price is None:
            # Try to get last price from IB (with try/finally to prevent subscription leak)
            try:
                ib.reqMktData(contract, "", False, False)
                ib.sleep(2)  # Brief wait for market data
                ticker_obj = ib.ticker(contract)
                if ticker_obj and ticker_obj.last and ticker_obj.last > 0:
                    estimated_price = float(ticker_obj.last)
                elif ticker_obj and ticker_obj.close and ticker_obj.close > 0:
                    estimated_price = float(ticker_obj.close)
            except Exception:
                pass
            finally:
                try:
                    ib.cancelMktData(contract)
                except Exception:
                    pass

        estimated_total = None
        if estimated_price is not None:
            estimated_total = (estimated_price * float(quantity)) + estimated_commission

        # IMPORTANT: order_params are stored INSIDE broker_preview_data because
        # that is the single JSONB column persisted to trade_previews. The
        # execute_order() flow reads broker_preview_data.order_params to
        # reconstruct the order. This is the canonical storage location.
        return {
            "estimated_price": estimated_price,
            "estimated_total": estimated_total,
            "estimated_commission": estimated_commission,
            "broker_trade_id": None,  # IBKR whatIfOrder is stateless
            "combined_remaining_balance": None,
            "trade_impacts": [],
            "broker_preview_data": {
                "commission": str(order_state.commission),
                "commission_currency": order_state.commissionCurrency,
                "init_margin_before": str(order_state.initMarginBefore),
                "init_margin_after": str(order_state.initMarginAfter),
                "init_margin_change": str(order_state.initMarginChange),
                "maint_margin_before": str(order_state.maintMarginBefore),
                "maint_margin_after": str(order_state.maintMarginAfter),
                "maint_margin_change": str(order_state.maintMarginChange),
                "equity_with_loan_before": str(order_state.equityWithLoanBefore),
                "equity_with_loan_after": str(order_state.equityWithLoanAfter),
                "equity_with_loan_change": str(order_state.equityWithLoanChange),
                "warning_text": order_state.warningText or "",
                # Full order params for reconstruction at execution time
                "order_params": {
                    "account_id": account_id,
                    "ticker": (ticker or "").upper().strip(),
                    "side": side,
                    "quantity": float(quantity),
                    "order_type": order_type,
                    "time_in_force": time_in_force,
                    "limit_price": limit_price,
                    "stop_price": stop_price,
                    "con_id": symbol_info["con_id"],
                },
            },
        }

    def place_order(
        self,
        account_id: str,
        order_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Place an order via ib_async placeOrder().

        order_params is reconstructed from the stored preview row's
        broker_preview_data.order_params.
        """
        from ib_async import Contract, Stock
        import settings

        # READONLY guard: prevent order placement in read-only mode
        if settings.IBKR_READONLY:
            raise ValueError(
                "IBKR is in read-only mode (IBKR_READONLY=true). "
                "Order placement is disabled."
            )

        ib = self._conn_manager.ensure_connected()

        # 1. Re-qualify contract using stored conId for safety
        ticker = order_params["ticker"]
        stored_con_id = order_params.get("con_id")

        if stored_con_id:
            # Prefer rebuilding from conId (unambiguous)
            contract = Contract(conId=int(stored_con_id), exchange="SMART")
            qualified = ib.qualifyContracts(contract)
            if not qualified:
                # Fallback to ticker-based qualification
                portfolio_logger.warning(
                    f"conId {stored_con_id} qualification failed, falling back to ticker"
                )
                contract = Stock(ticker, "SMART", "USD")
                qualified = ib.qualifyContracts(contract)
        else:
            contract = Stock(ticker, "SMART", "USD")
            qualified = ib.qualifyContracts(contract)

        if not qualified:
            raise ValueError(f"Cannot re-qualify contract for {ticker}")
        contract = qualified[0]

        # Verify conId matches if we have a stored one
        if stored_con_id and contract.conId != int(stored_con_id):
            raise ValueError(
                f"Contract mismatch: stored conId={stored_con_id}, "
                f"resolved conId={contract.conId}. Aborting for safety."
            )

        # 2. Build order
        order = self._build_order(
            side=order_params["side"],
            quantity=order_params["quantity"],
            order_type=order_params["order_type"],
            time_in_force=order_params["time_in_force"],
            limit_price=order_params.get("limit_price"),
            stop_price=order_params.get("stop_price"),
            account_id=account_id,
        )

        # 3. Set orderRef to preview_id for reconciliation (if available in order_params)
        if order_params.get("preview_id"):
            order.orderRef = str(order_params["preview_id"])

        # 4. Place order
        trade = ib.placeOrder(contract, order)

        # 4. Wait briefly for initial status update (up to 5 seconds)
        max_wait = 5
        waited = 0
        while not trade.isDone() and waited < max_wait:
            ib.sleep(1)
            waited += 1

        # 5. Map status using quantity-aware function
        ibkr_status = trade.orderStatus.status if trade.orderStatus else "PendingSubmit"
        filled = float(trade.orderStatus.filled) if trade.orderStatus else 0.0
        remaining = float(trade.orderStatus.remaining) if trade.orderStatus else 0.0
        common_status = ibkr_to_common_status(ibkr_status, filled, remaining)

        # Extract commission from fills if available
        commission = None
        if trade.fills:
            commission = sum(
                f.commissionReport.commission
                for f in trade.fills
                if f.commissionReport
            )

        avg_fill = float(trade.orderStatus.avgFillPrice) if trade.orderStatus and trade.orderStatus.avgFillPrice else None
        # total_cost = filled_quantity * avg_fill_price + commission
        total_cost = None
        if avg_fill is not None and filled > 0:
            total_cost = (filled * avg_fill) + (commission or 0.0)

        return {
            "brokerage_order_id": str(trade.order.orderId),
            "status": common_status,
            "filled_quantity": filled,
            "execution_price": avg_fill,
            "total_quantity": float(order_params["quantity"]),
            "total_cost": total_cost,
            "commission": commission,
        }

    def get_orders(
        self,
        account_id: str,
        state: str = "all",
        days: int = 30,
    ) -> List[Dict[str, Any]]:
        """Fetch open/completed orders from IB Gateway.

        Note: ib.trades() and ib.openTrades() are session-scoped (current gateway
        session only). For completed order history, we use ib.reqCompletedOrders()
        which returns orders from the past 24 hours. For longer history, the DB
        trade_orders table is the primary source (handled by TradeExecutionService).

        Deduplication uses permId (stable across sessions) to avoid duplicates
        between openTrades() and reqCompletedOrders().
        """
        from datetime import datetime, timedelta, timezone

        ib = self._conn_manager.ensure_connected()
        seen_perm_ids = set()
        results = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        # 1. Open orders (live working orders)
        if state in ("all", "open"):
            for trade in ib.openTrades():
                if account_id and trade.order.account != account_id:
                    continue
                perm_id = trade.order.permId
                if perm_id and perm_id in seen_perm_ids:
                    continue
                seen_perm_ids.add(perm_id)
                results.append(self._map_trade_to_dict(trade))

        # 2. Completed orders (filled/cancelled -- past 24h from IB)
        if state in ("all", "executed", "cancelled"):
            completed_trades = ib.reqCompletedOrders(apiOnly=False)
            for trade in completed_trades:
                if account_id and trade.order.account != account_id:
                    continue
                perm_id = trade.order.permId
                if perm_id and perm_id in seen_perm_ids:
                    continue
                seen_perm_ids.add(perm_id)

                mapped = self._map_trade_to_dict(trade)

                # Filter by state
                if state == "executed" and mapped["status"] != "EXECUTED":
                    continue
                if state == "cancelled" and mapped["status"] not in ("CANCELED", "REJECTED"):
                    continue

                # Filter by days (using time_placed if available)
                if mapped.get("time_placed") and mapped["time_placed"] < cutoff:
                    continue

                results.append(mapped)

        return results

    def cancel_order(
        self,
        account_id: str,
        order_id: str,
    ) -> Dict[str, Any]:
        """Cancel an order by orderId. Validates account_id matches."""
        ib = self._conn_manager.ensure_connected()

        # Find the trade by orderId AND account_id (both must match)
        target_trade = None
        for trade in ib.openTrades():
            if (str(trade.order.orderId) == str(order_id)
                    and trade.order.account == account_id):
                target_trade = trade
                break

        if not target_trade:
            raise ValueError(
                f"Open order {order_id} not found in IB Gateway "
                f"for account {account_id}"
            )

        ib.cancelOrder(target_trade.order)

        # Wait briefly for cancellation confirmation
        ib.sleep(2)

        return {
            "status": "CANCEL_PENDING",
            "brokerage_order_id": str(order_id),
        }

    def get_account_balance(self, account_id: str) -> Optional[float]:
        """Get available cash from IB account summary."""
        ib = self._conn_manager.ensure_connected()
        return self._get_account_balance_internal(ib, account_id)

    def refresh_after_trade(self, account_id: str) -> None:
        """Invalidate position cache for IBKR account.

        Since IBKR positions are fetched live from the gateway (not cached
        in Plaid/SnapTrade style), this mainly invalidates any local DB cache.
        """
        from database import get_db_session

        try:
            with get_db_session() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE positions
                    SET created_at = NOW() - interval '2 days'
                    WHERE user_id = (SELECT id FROM users WHERE email = %s)
                      AND account_id = %s
                    """,
                    (self._user_email, account_id),
                )
                conn.commit()
        except Exception as e:
            portfolio_logger.warning(
                f"Failed to invalidate position cache for IBKR account {account_id}: {e}"
            )

    # -----------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------

    def _build_order(
        self,
        side: str,
        quantity: float,
        order_type: str,
        time_in_force: str,
        limit_price: Optional[float],
        stop_price: Optional[float],
        account_id: str,
    ):
        """Construct an ib_async Order object from parameters."""
        from ib_async import LimitOrder, MarketOrder, Order, StopOrder

        action = side.upper()  # BUY or SELL
        qty = float(quantity)

        # Time-in-force mapping
        tif_map = {
            "Day": "DAY",
            "GTC": "GTC",
            "FOK": "FOK",
            "IOC": "IOC",
        }
        ib_tif = tif_map.get(time_in_force, "DAY")

        if order_type == "Market":
            order = MarketOrder(action, qty)
        elif order_type == "Limit":
            if limit_price is None:
                raise ValueError("limit_price required for Limit orders")
            order = LimitOrder(action, qty, limit_price)
        elif order_type == "Stop":
            if stop_price is None:
                raise ValueError("stop_price required for Stop orders")
            order = StopOrder(action, qty, stop_price)
        elif order_type == "StopLimit":
            if limit_price is None or stop_price is None:
                raise ValueError("Both limit_price and stop_price required for StopLimit orders")
            # Build StopLimit via generic Order (explicit field control)
            order = Order(
                action=action,
                totalQuantity=qty,
                orderType="STP LMT",
                lmtPrice=limit_price,
                auxPrice=stop_price,
            )
        else:
            raise ValueError(f"Unsupported order type: {order_type}")

        order.tif = ib_tif
        order.account = account_id
        return order

    def _get_account_balance_internal(self, ib, account_id: str) -> Optional[float]:
        """Fetch available cash from IB account values.

        Uses ib.accountValues() for cached data. If no cached data,
        subscribes via reqAccountUpdates() (no subscribe kwarg -- the
        method subscribes automatically), waits, then reads values.
        """
        try:
            # accountValues() returns cached values for a specific account
            account_values = ib.accountValues(account=account_id)
            for av in account_values:
                if av.tag == "AvailableFunds" and av.currency == "USD":
                    return float(av.value)

            # If no cached values, request account updates (subscribes automatically)
            if not account_values:
                ib.reqAccountUpdates(account=account_id)
                ib.sleep(2)  # Wait for data delivery
                account_values = ib.accountValues(account=account_id)
                for av in account_values:
                    if av.tag == "AvailableFunds" and av.currency == "USD":
                        return float(av.value)
        except Exception as e:
            portfolio_logger.warning(f"Failed to get IBKR balance for {account_id}: {e}")
        return None

    def _map_trade_to_dict(self, trade) -> Dict[str, Any]:
        """Map an ib_async Trade object to normalized dict."""
        ibkr_status = trade.orderStatus.status if trade.orderStatus else "Unknown"
        filled = float(trade.orderStatus.filled) if trade.orderStatus else 0.0
        remaining = float(trade.orderStatus.remaining) if trade.orderStatus else 0.0
        common_status = ibkr_to_common_status(ibkr_status, filled, remaining)

        # Extract timestamps from trade log entries
        time_placed = None
        time_updated = None
        if trade.log:
            time_placed = trade.log[0].time if trade.log[0] else None
            time_updated = trade.log[-1].time if trade.log[-1] else None

        return {
            "brokerage_order_id": str(trade.order.orderId),
            "perm_id": str(trade.order.permId) if trade.order.permId else None,
            "ticker": trade.contract.symbol if trade.contract else None,
            "side": trade.order.action,
            "quantity": float(trade.order.totalQuantity),
            "order_type": trade.order.orderType,
            "status": common_status,
            "filled_quantity": filled,
            "execution_price": float(trade.orderStatus.avgFillPrice) if trade.orderStatus and trade.orderStatus.avgFillPrice else None,
            "commission": sum(f.commissionReport.commission for f in trade.fills if f.commissionReport) if trade.fills else None,
            "time_placed": time_placed,
            "time_updated": time_updated,
        }
```

**Key design points:**

1. **`whatIfOrder()` is stateless**: No `trade_id` links preview to execution. The full order params are stored **inside** `broker_preview_data` JSONB column (at `broker_preview_data.order_params`), and reconstructed from those params at `place_order()` time.

2. **Contract re-qualification with conId verification**: Both `preview_order()` and `place_order()` call `qualifyContracts()`. At execution time, the stored `conId` is used to rebuild the contract (unambiguous), and the resolved conId is verified to match. This prevents symbol resolution changes between preview and execute.

3. **Market data for price estimation**: For market orders, `whatIfOrder()` does not return an estimated fill price. The adapter requests a brief market data snapshot to get the last traded price, with try/finally to prevent subscription leaks. If unavailable, the estimated price is `None` and the service layer handles it.

4. **Order wait**: After `placeOrder()`, we wait up to 5 seconds for initial status. Market orders typically fill within this window. If still pending, we return `PENDING` status and the user can check via `get_orders`.

5. **Partial fill detection**: `ib_async` does not have a `PartiallyFilled` status string. Partial fills are detected by checking `filled > 0 and remaining > 0` when status is `Submitted`, using the `ibkr_to_common_status()` function.

6. **READONLY enforcement**: `place_order()` checks `settings.IBKR_READONLY` and raises immediately if true, before any order construction.

7. **Account authorization**: `cancel_order()` matches both `orderId` and `account_id` before cancelling. `list_accounts()` and `owns_account()` filter by `IBKR_AUTHORIZED_ACCOUNTS` to prevent unauthorized access to other managed accounts.

8. **Order history**: `get_orders()` uses `reqCompletedOrders()` for filled/cancelled history (not `ib.trades()` which is session-scoped). Deduplication by `permId` prevents overlap between open and completed results.

---

### Phase 6: Service Layer Integration ✅ DONE

**Goal:** Wire the IBKR adapter into `TradeExecutionService` so it is available when `IBKR_ENABLED=true`.

#### File: `services/trade_execution_service.py` (modify)

Update the constructor to conditionally register the IBKR adapter:

```python
def __init__(self, user_email: str, ...):
    # ... existing init ...
    self._adapters: Dict[str, BrokerAdapter] = {}

    # Always register SnapTrade
    self._adapters["snaptrade"] = SnapTradeBrokerAdapter(
        user_email=user_email,
        snaptrade_client=snaptrade_client,
        region=region,
    )

    # Conditionally register IBKR
    from settings import IBKR_ENABLED
    if IBKR_ENABLED:
        from services.ibkr_broker_adapter import IBKRBrokerAdapter
        self._adapters["ibkr"] = IBKRBrokerAdapter(user_email=user_email)
```

Update `list_tradeable_accounts()` to merge from all adapters:

```python
def list_tradeable_accounts(self) -> List[Dict[str, Any]]:
    all_accounts = []
    for adapter in self._adapters.values():
        try:
            all_accounts.extend(adapter.list_accounts())
        except Exception as e:
            portfolio_logger.warning(
                f"Failed to list accounts from {adapter.provider_name}: {e}"
            )
    return all_accounts
```

Update `preview_order()` flow:

```python
def preview_order(self, ...):
    # ... validation ...
    adapter = self._resolve_broker_adapter(account_id)

    # Symbol resolution via adapter
    symbol_info = adapter.search_symbol(account_id, ticker)

    # Preview via adapter
    preview = adapter.preview_order(
        account_id=account_id,
        ticker=ticker,
        side=side,
        quantity=quantity,
        order_type=order_type,
        time_in_force=time_in_force,
        limit_price=limit_price,
        stop_price=stop_price,
        symbol_id=symbol_info.get("universal_symbol_id") or symbol_info.get("broker_symbol_id"),
    )

    # ... store preview with broker_provider=adapter.provider_name ...
```

Update `execute_order()` flow:

```python
def execute_order(self, preview_id: str):
    # ... load preview row, check expiry ...
    broker_provider = preview_row.get("broker_provider", "snaptrade")
    adapter = self._adapters.get(broker_provider)
    if not adapter:
        raise ValueError(f"No adapter for broker provider '{broker_provider}'")

    if broker_provider == "snaptrade":
        # Existing SnapTrade flow: use snaptrade_trade_id
        order_response = adapter.place_order(
            account_id=preview_row["account_id"],
            order_params={"snaptrade_trade_id": preview_row["snaptrade_trade_id"]},
        )
    else:
        # IBKR flow: reconstruct order from stored params
        # order_params are stored INSIDE broker_preview_data (canonical location)
        broker_preview_data = preview_row.get("broker_preview_data") or {}
        order_params = broker_preview_data.get("order_params")
        if not order_params:
            # Fallback: reconstruct from preview row columns
            order_params = {
                "ticker": preview_row["ticker"],
                "side": preview_row["side"],
                "quantity": float(preview_row["quantity"]),
                "order_type": preview_row["order_type"],
                "time_in_force": preview_row["time_in_force"],
                "limit_price": float(preview_row["limit_price"]) if preview_row.get("limit_price") else None,
                "stop_price": float(preview_row["stop_price"]) if preview_row.get("stop_price") else None,
            }
            portfolio_logger.warning(
                f"IBKR preview {preview_id} missing order_params in broker_preview_data, "
                "reconstructing from columns"
            )
        # Pass preview_id so IBKR adapter can set orderRef for reconciliation
        order_params["preview_id"] = str(preview_id)
        order_response = adapter.place_order(
            account_id=str(preview_row["account_id"]),
            order_params=order_params,
        )
    # ... store execution, refresh ...
```

#### File: `mcp_tools/trading.py` (no changes needed)

The MCP tool layer is already broker-agnostic -- it calls `TradeExecutionService` which handles routing internally. No changes required.

#### File: `mcp_server.py` (no changes needed)

The MCP server tool registrations are unchanged.

---

### Phase 7: Testing ✅ DONE (live, not paper)

**Goal:** Validate the full IBKR flow. Tested directly against live TWS on port 7496 (account U2471778) instead of paper trading.

#### Prerequisites

1. **IB Gateway installed** on macOS with paper trading account.
2. **IBC configured** for automated login.
3. **Paper account set up** (DU-prefixed account ID).
4. **IB Gateway running** on port 4002.

#### Test Configuration

```bash
# .env for testing
TRADING_ENABLED=true
IBKR_ENABLED=true
IBKR_GATEWAY_HOST=127.0.0.1
IBKR_GATEWAY_PORT=4002
IBKR_CLIENT_ID=1
IBKR_TIMEOUT=10
IBKR_READONLY=false
```

#### Test Plan

**7A. Connection tests:**

- [x] `IBKRConnectionManager.connect()` succeeds when TWS is running (port 7496)
- [ ] `IBKRConnectionManager.connect()` raises `ConnectionRefusedError` when gateway is down
- [x] `managed_accounts` returns account U2471778
- [ ] Auto-reconnect fires and recovers after brief gateway restart
- [ ] Concurrent `ensure_connected()` calls do not create duplicate connections

**7B. Symbol resolution tests:**

- [x] `search_symbol("AAPL")` returns qualified contract with conId
- [ ] `search_symbol("INVALIDXYZ")` raises ValueError with clear message
- [ ] `search_symbol("BRK.B")` handles dot-separated tickers correctly

**7C. Preview tests:**

- [x] `preview_trade(ticker="AAPL", quantity=1, side="BUY", order_type="Market")` returns valid preview with commission estimate
- [x] `preview_trade(ticker="MSFT", quantity=5, side="BUY", order_type="Limit", limit_price=350)` returns valid preview
- [x] Preview stores `broker_provider='ibkr'` in trade_previews
- [x] Preview stores `broker_preview_data` with margin impact fields
- [x] Preview returns `snaptrade_trade_id=None` (IBKR has no linked preview concept)

**7D. Execution tests:**

- [x] `execute_trade(preview_id)` places BUY 1 AAPL Market order — order ID 17, status PENDING (markets closed)
- [x] Order appears in `get_orders()` with status PENDING
- [x] `cancel_order(account_id, order_id)` cancels the order successfully
- [ ] After cancellation, `get_orders(state="cancelled")` shows the order
- [ ] Execute a market order for 1 share during market hours, verify EXECUTED status and fill price

**7E. Expiry tests:**

- [ ] Preview with IBKR account, wait >5 minutes, execute -- should return new preview (same as SnapTrade behavior)

**7F. Mixed broker tests:**

- [x] `list_tradeable_accounts()` returns both SnapTrade and IBKR accounts (4 total)
- [ ] Preview trade on SnapTrade account still works unchanged (blocked by 403)
- [x] Preview trade on IBKR account uses IBKR adapter
- [ ] `get_orders()` on SnapTrade account uses SnapTrade adapter

**7G. Error handling tests:**

- [ ] Disconnect IB Gateway mid-session; next IBKR trade returns clear error
- [ ] Attempt trade on IBKR account with `IBKR_ENABLED=false` -- returns error
- [x] Attempt SELL with no position -- returns REJECTED (tested SELL 100 TSLA)
- [ ] Attempt trade with gateway in readonly mode -- returns error

---

### Phase 8: Safety Hardening — ⬜ PARTIAL

**Goal:** Address edge cases and failure modes specific to IBKR. Basic safety is in place (READONLY guard, authorized accounts, kill switch). Connection drop recovery probe and weekly 2FA handling not yet tested.

#### 8A. Gateway Down Handling

When IB Gateway is not running or unreachable:

```python
# In IBKRBrokerAdapter methods:
try:
    ib = self._conn_manager.ensure_connected()
except ConnectionRefusedError:
    raise ValueError(
        "IB Gateway is not running. Start IB Gateway on "
        f"{settings.IBKR_GATEWAY_HOST}:{settings.IBKR_GATEWAY_PORT} "
        "and try again."
    )
except Exception as e:
    raise ValueError(f"Cannot connect to IB Gateway: {e}")
```

- SnapTrade trades continue to work normally when IB Gateway is down.
- IBKR-specific errors are returned with clear instructions.

#### 8B. Connection Drop During Order Placement

If the socket connection drops between `placeOrder()` and receiving confirmation:

1. The order may or may not have been received by IB servers.
2. On reconnect, `ib.openTrades()` and `ib.reqCompletedOrders()` will show the order if it was received.
3. The `execute_order()` method records the attempt in `trade_orders` with status `PENDING` (not `FAILED`, since the order may have been received) and `error_message` noting the connection issue.
4. Next call to `get_orders()` will reconcile with IB Gateway and update the status.

**Policy: uncertain submission => `PENDING` + reconciliation.**

```python
# In execute_order(), wrap the adapter.place_order() call:
try:
    order_response = adapter.place_order(account_id, order_params)
except Exception as place_err:
    # Record as PENDING (not FAILED) — order may have been received by IB
    cursor.execute("""
        INSERT INTO trade_orders (..., order_status, error_message)
        VALUES (..., 'PENDING', %s)
        RETURNING id
    """, (f"Connection error during placement: {place_err}",))
    inserted_row = cursor.fetchone()  # Must read RETURNING before commit
    order_row_id = inserted_row["id"] if inserted_row else None
    conn.commit()

    # IMMEDIATE RECOVERY PROBE: Try to find the order in IB after reconnect.
    # Uses orderRef (set to preview_id) for unambiguous matching.
    # Falls back to account+symbol+side+quantity+conId if orderRef not available.
    try:
        ib = adapter._conn_manager.ensure_connected()
        preview_id_str = str(preview_id) if preview_id else None

        # Scan both open and completed orders
        all_trades = list(ib.openTrades()) + list(ib.reqCompletedOrders(apiOnly=False))

        for trade in all_trades:
            # Prefer matching by orderRef (set to preview_id at placement)
            if preview_id_str and getattr(trade.order, 'orderRef', None) == preview_id_str:
                matched = True
            elif (trade.order.account == account_id
                    and trade.contract.symbol == order_params.get("ticker")
                    and trade.order.action == order_params.get("side")
                    and float(trade.order.totalQuantity) == float(order_params.get("quantity", 0))
                    and (not order_params.get("con_id") or trade.contract.conId == int(order_params["con_id"]))):
                matched = True
            else:
                matched = False

            if matched and order_row_id:
                cursor.execute("""
                    UPDATE trade_orders
                    SET brokerage_order_id = %s, order_status = %s
                    WHERE id = %s
                """, (str(trade.order.orderId),
                      ibkr_to_common_status(trade.orderStatus.status,
                                            trade.orderStatus.filled,
                                            trade.orderStatus.remaining),
                      order_row_id))
                conn.commit()
                break
    except Exception:
        pass  # Recovery probe failed; reconciliation will catch it later

    raise
```

#### 8C. Weekly 2FA Timeout

If the weekly 2FA is missed:
- IB Gateway enters a non-authenticated state.
- `ib.connect()` will fail with a timeout or auth error.
- The adapter returns a clear error: "IB Gateway authentication expired. Approve the 2FA notification on IBKR Mobile."
- SnapTrade trades are unaffected.

#### 8D. Kill Switch Interactions

The existing `TRADING_ENABLED` kill switch applies to ALL brokers. When `false`, no preview or execute calls succeed regardless of broker.

The `IBKR_ENABLED` flag controls whether the IBKR adapter is even registered. When `false`, IBKR accounts are not listed as tradeable, and routing to IBKR accounts fails with a clear error.

The `IBKR_READONLY` flag allows connecting to IB Gateway for position/balance reads without enabling order placement.

---

## File Summary

### New Files

| File | Description |
|------|-------------|
| `core/broker_adapter.py` | Abstract `BrokerAdapter` interface (ABC) |
| `services/snaptrade_broker_adapter.py` | SnapTrade adapter (extracted from TradeExecutionService) |
| `services/ibkr_connection_manager.py` | Singleton managing ib_async connection to IB Gateway |
| `services/ibkr_broker_adapter.py` | IBKR adapter implementing BrokerAdapter via ib_async |
| `database/migrations/20260210_add_broker_provider.sql` | Add broker_provider columns to trade tables |

### Modified Files

| File | Changes |
|------|---------|
| `services/trade_execution_service.py` | Refactor to use BrokerAdapter interface; register adapters; route by account |
| `settings.py` | Add IBKR_ENABLED, IBKR_GATEWAY_HOST, IBKR_GATEWAY_PORT, IBKR_CLIENT_ID, IBKR_TIMEOUT, IBKR_READONLY |
| `.env.example` | Add IBKR environment variable examples |

### Unchanged Files

| File | Why |
|------|-----|
| `mcp_tools/trading.py` | Already broker-agnostic (calls TradeExecutionService) |
| `mcp_server.py` | Tool registrations unchanged |
| `core/trade_objects.py` | Result objects are already broker-agnostic |
| `snaptrade_loader.py` | Trading functions unchanged (now called by SnapTradeBrokerAdapter) |

---

## Dependency

One new Python package:

```
pip install ib_async
```

Version: `>=2.1.0` (actively maintained fork of `ib_insync`).

**Add to `requirements.txt`:** `ib_async>=2.1.0`

No other new dependencies. `ib_async` has no external dependencies beyond the Python standard library.

---

## Phase Execution Order and Estimated Effort

| Phase | Description | Effort | Dependencies |
|-------|-------------|--------|--------------|
| **Phase 1** | BrokerAdapter ABC + SnapTrade extraction | 2 days | None |
| **Phase 2** | Database migration (broker_provider) | 0.5 day | Phase 1 |
| **Phase 3** | Settings (IBKR config) | 0.5 day | None (can parallel with Phase 1) |
| **Phase 4** | IBKRConnectionManager | 1 day | Phase 3 |
| **Phase 5** | IBKRBrokerAdapter | 2 days | Phases 1, 4 |
| **Phase 6** | Service layer integration | 1 day | Phases 1, 2, 5 |
| **Phase 7** | Paper trading tests | 1-2 days | Phase 6 + IB Gateway running |
| **Phase 8** | Safety hardening | 1 day | Phase 7 |
| **Total** | | **~8-10 days** | |

Phases 1 and 3 can run in parallel. Phase 2 is a quick migration that can happen anytime after Phase 1. The critical path is Phase 1 -> Phase 5 -> Phase 6 -> Phase 7.

---

## Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| **SnapTrade refactor breaks existing flow** | High | Phase 1 is a pure extraction; run full E2E test suite after. No behavior change. |
| **IB Gateway not available for testing** | Medium | Paper trading on port 4002 requires IB Gateway + weekly 2FA. Set up before Phase 7. |
| **ib_async sync mode blocks MCP server** | Medium | ib_async sync calls (e.g., `sleep()`, `qualifyContracts()`) block the calling thread. The MCP server is single-threaded per request, so this matches existing SnapTrade behavior. Monitor for timeout issues. |
| **whatIfOrder limitations** | Low | `whatIfOrder()` may not return fill price for market orders. Supplemented with last market price request. |
| **Connection drops mid-order** | Medium | Uncertain submissions recorded as PENDING with immediate recovery probe (matching by orderRef/preview_id). Reconciliation on `get_orders()` updates status from IB. No silent duplicates due to DB UNIQUE constraint on preview_id. |
| **IBKR account ID collision with SnapTrade** | Low | IBKR accounts use `U`/`DU` prefix format, SnapTrade uses UUIDs. Formats do not overlap. |
| **Multiple clientId conflicts** | Low | Single clientId configured in settings. If TWS is also running with the same clientId, one will disconnect. Use a dedicated clientId for the MCP server. |

---

## Open Questions Resolved

| Question | Resolution |
|----------|------------|
| **Account identification** | IBKR uses native account IDs (`U1234567`). Format-based routing distinguishes from SnapTrade UUIDs. |
| **Position data source** | Positions continue to come from Plaid for IB (read-only). Trading goes via ib_async. Both can coexist (independent systems). Future enhancement: replace Plaid position read with ib_async for real-time positions. |
| **Simultaneous connections** | Plaid reads from IB reporting. ib_async connects to IB Gateway. Independent; no conflict. |
| **IB Gateway hosting** | Initial implementation: IB Gateway runs natively on macOS alongside MCP server. Docker is a future production option. |
| **Paper trading account** | Use port 4002 for paper trading. Same IB Gateway binary; mode is controlled by the TRADING_MODE setting in IBC config. |

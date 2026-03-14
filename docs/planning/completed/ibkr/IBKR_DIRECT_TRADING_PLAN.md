# Enable IBKR Direct Trading via IB Gateway

**Date**: 2026-03-02
**Status**: COMPLETE (commits `ab8bff60`, `8a20f4b8`)

## Context

IBKR positions come through SnapTrade (IBKR Flex — read-only). When `preview_trade` is called, the order routes to SnapTrade which rejects: `"Brokerage INTERACTIVE-BROKERS-FLEX does not support trading"`. The direct IBKR trading adapter exists (`brokerage/ibkr/adapter.py`) and is registered in `TradeExecutionService`, but two bugs prevent it from working.

**Bug 1 — Connection leak**: Each MCP call creates a fresh `TradeExecutionService` → fresh `IBKRBrokerAdapter` → fresh `IBKRConnectionManager(client_id=22)`. The old connection never disconnects, so the next call gets "client ID 22 already in use" timeout from IB Gateway.

**Bug 2 — Account routing gap**: IBKR positions are stored under SnapTrade UUID `cb7a1987-bce1-42bb-afd5-6fc2b54bbf12`. The IBKR adapter only knows `U2471778` (from `IBKR_AUTHORIZED_ACCOUNTS`). When the user passes the UUID, SnapTrade wins the routing and rejects the trade.

---

## Implementation Plan

### Step 1: Module-level singleton for trading connection manager

**File**: `brokerage/ibkr/adapter.py`

The `IBKRConnectionManager(client_id=N)` non-singleton path creates a new instance every time. Add a module-level singleton so the same connection manager (and IB Gateway connection) is reused across all `IBKRBrokerAdapter` instances within the MCP server process.

```python
import threading

_trading_conn_manager: Optional[IBKRConnectionManager] = None
_trading_conn_lock = threading.Lock()

def _get_trading_conn_manager() -> IBKRConnectionManager:
    global _trading_conn_manager
    with _trading_conn_lock:
        if _trading_conn_manager is None:
            _trading_conn_manager = IBKRConnectionManager(client_id=IBKR_TRADE_CLIENT_ID)
        return _trading_conn_manager
```

In `IBKRBrokerAdapter.__init__()`, change:
```python
# Before:
self._conn_manager = IBKRConnectionManager(client_id=IBKR_TRADE_CLIENT_ID)
# After:
self._conn_manager = _get_trading_conn_manager()
```

This works because `IBKRConnectionManager.connect()` is already idempotent (checks `self._ib.isConnected()` first).

### Step 2: Trade routing + account mapping in routing_config.py

**File**: `providers/routing_config.py`

Add `TRADE_ROUTING` table alongside existing `TRANSACTION_ROUTING` and `POSITION_ROUTING` — same pattern, same file:

```python
# Controls which adapter handles TRADE EXECUTION for each institution.
# When an institution is listed here, trades route to the specified adapter
# instead of the default SnapTrade path. This enables direct broker connections
# (e.g., IBKR via IB Gateway) for institutions where SnapTrade is read-only.
TRADE_ROUTING = {
    "interactive_brokers": "ibkr",  # Direct IB Gateway, SnapTrade Flex is read-only
}

# Maps aggregator account IDs (e.g., SnapTrade UUIDs) to native broker account IDs.
# Required when positions come from an aggregator but trades route to a direct adapter.
# Format: env var is comma-separated pairs of "aggregator_id:native_id"
# Example: TRADE_ACCOUNT_MAP=cb7a1987-...:U2471778,other-uuid:OTHER_ACCT
_raw_account_map = os.getenv("TRADE_ACCOUNT_MAP", "")
TRADE_ACCOUNT_MAP: Dict[str, str] = {}
for pair in _raw_account_map.split(","):
    pair = pair.strip()
    if ":" in pair:
        agg_id, native_id = pair.split(":", 1)
        TRADE_ACCOUNT_MAP[agg_id.strip()] = native_id.strip()
```

Note: env var named `TRADE_ACCOUNT_MAP` (broker-agnostic), consistent with routing_config naming convention.

### Step 3: Teach IBKR adapter to handle mapped accounts

**File**: `brokerage/ibkr/adapter.py`

Add a helper to translate aggregator IDs to native IBKR IDs:

```python
from providers.routing_config import TRADE_ACCOUNT_MAP

def _resolve_native_account(self, account_id: str) -> str:
    """Translate aggregator account ID to native IBKR account ID if mapped."""
    return TRADE_ACCOUNT_MAP.get(account_id, account_id)
```

Update `owns_account()` to resolve mapped IDs before checking:

```python
def owns_account(self, account_id: str) -> bool:
    native_id = self._resolve_native_account(account_id)
    if IBKR_AUTHORIZED_ACCOUNTS and native_id not in IBKR_AUTHORIZED_ACCOUNTS:
        return False
    if self._conn_manager.is_connected:
        return native_id in self._conn_manager.managed_accounts
    if IBKR_AUTHORIZED_ACCOUNTS:
        return native_id in IBKR_AUTHORIZED_ACCOUNTS
    return False
```

Add `account_id = self._resolve_native_account(account_id)` at the top of: `preview_order()`, `place_order()`, `preview_roll()`, `place_roll()`, `get_orders()`, `cancel_order()`, `get_account_balance()`.

### Step 4: Trade routing in _resolve_broker_adapter()

**File**: `services/trade_execution_service.py`

In `_resolve_broker_adapter()`, add a fast-path before the normal adapter iteration. Use `TRADE_ROUTING` + `TRADE_ACCOUNT_MAP` to check if the account should be routed to a specific adapter:

```python
from providers.routing_config import TRADE_ROUTING, TRADE_ACCOUNT_MAP

def _resolve_broker_adapter(self, account_id: str) -> BrokerAdapter:
    # Fast-path: if account is mapped to a native broker, route directly
    if account_id in TRADE_ACCOUNT_MAP:
        native_id = TRADE_ACCOUNT_MAP[account_id]
        # Find which institution this maps to via TRADE_ROUTING
        for institution, adapter_name in TRADE_ROUTING.items():
            if adapter_name in self._adapters:
                adapter = self._adapters[adapter_name]
                if adapter.owns_account(account_id):  # adapter resolves internally
                    return adapter

    # Existing iteration logic unchanged...
```

This ensures mapped accounts route to the direct adapter, while all other accounts follow the existing iteration path.

### Step 5: Add env var to `.env`

```
TRADE_ACCOUNT_MAP=cb7a1987-bce1-42bb-afd5-6fc2b54bbf12:U2471778
```

---

## Files Modified

| File | Change |
|------|--------|
| `brokerage/ibkr/adapter.py` | Connection singleton + `_resolve_native_account()` + `owns_account()` update |
| `providers/routing_config.py` | `TRADE_ROUTING` table + `TRADE_ACCOUNT_MAP` parsing |
| `services/trade_execution_service.py` | Trade routing fast-path in `_resolve_broker_adapter()` |
| `.env` | Add `TRADE_ACCOUNT_MAP` |

~60 lines changed across 3 code files + 1 env var.

---

## What This Does NOT Change

- SnapTrade remains the data source for IBKR positions (Flex reads work fine)
- Schwab and non-IBKR SnapTrade trading paths are unaffected
- ibkr-mcp (client ID 20) and market data (client ID 21) connections are unaffected
- No changes to `BrokerAdapter` interface or `IBKRConnectionManager` core
- Existing `TRANSACTION_ROUTING` and `POSITION_ROUTING` patterns unchanged

---

## Design Rationale

**Why `TRADE_ROUTING` in `routing_config.py`?**
- Follows established pattern: `TRANSACTION_ROUTING`, `POSITION_ROUTING`, now `TRADE_ROUTING`
- All routing decisions in one file — easy to audit and extend
- Broker-agnostic naming (`TRADE_ACCOUNT_MAP` not `IBKR_SNAPTRADE_ACCOUNT_MAP`)
- If Schwab ever needs direct trading (bypassing SnapTrade), same pattern applies

**Why env var for account map?**
- Account IDs are deployment-specific (different per user/environment)
- No DB dependency for trading routing — simpler, more reliable
- Consistent with how `IBKR_AUTHORIZED_ACCOUNTS` already works

---

## Verification

1. **Connection reuse**: Call `preview_trade` with IBKR account twice. Second call should reuse connection (no "client ID in use" error).
2. **Mapped routing**: `preview_trade(account_id="cb7a1987-...", ticker="NVDA", quantity=1, side="SELL")` routes to IBKR adapter, translates to `U2471778`.
3. **Native ID routing**: `preview_trade(account_id="U2471778", ...)` also works directly.
4. **Schwab unaffected**: `preview_trade(account_id="25524252", ...)` still routes to Schwab.
5. **Account listing**: `preview_trade()` with no account_id lists both SnapTrade and IBKR accounts.
6. **Gateway down**: If IB Gateway is not running, IBKR adapter fails gracefully and SnapTrade/Schwab still work.

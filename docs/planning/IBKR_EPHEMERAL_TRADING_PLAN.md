# IBKR Trading Adapter: Ephemeral Connection Migration

## Context

`IBKRBrokerAdapter` holds IB Gateway connections indefinitely via `_ensure_connected()`. When multiple portfolio-mcp processes run (Claude Code + analyst backend), the second process can't connect — client ID 22 is already held. IBKR accounts silently disappear from `list_tradeable_accounts`. Trade preview fails with "not a tradeable account" or 120s timeout. First encountered 2026-03-02 during Phase 3 trade journal live test.

The rest of the codebase (`ibkr/market_data.py`) already uses ephemeral connections — connect per request, disconnect after. `IBKRConnectionManager.connection()` context manager handles both modes via `IBKR_CONNECTION_MODE` env var (defaults to `"ephemeral"`). The adapter just needs to use it.

## Plan

### Step 1: Add `_connected()` context manager

Replace `_ensure_connected()` (line 702, returns persistent `ib`) with `_connected()` (context manager wrapping `self._conn_manager.connection()`). Preserves user-friendly error messages.

**Critical**: Error translation must only wrap the **connection phase**, not the `yield` (business logic). Wrapping `yield` would misclassify business logic exceptions (e.g., order validation errors) as connection failures. Split the try/except so it covers `connection().__enter__()` but not the yielded body.

```python
from contextlib import contextmanager

@contextmanager
def _connected(self):
    """Yield a connected IB instance with user-facing error translation.

    Error translation covers only the connection phase. Exceptions raised
    by callers inside the ``with`` block propagate without remapping.
    """
    cm = self._conn_manager.connection()
    try:
        ib = cm.__enter__()
    except ConnectionRefusedError as e:
        raise ValueError(
            "IB Gateway is not running. Start IB Gateway on "
            f"{IBKR_GATEWAY_HOST}:{IBKR_GATEWAY_PORT} and try again."
        ) from e
    except Exception as e:
        message = str(e).lower()
        if "2fa" in message or "authentication" in message or "auth" in message:
            raise ValueError(
                "IB Gateway authentication expired. Approve the 2FA notification on IBKR Mobile."
            ) from e
        raise ValueError(f"Cannot connect to IB Gateway: {e}") from e
    try:
        yield ib
    finally:
        cm.__exit__(None, None, None)
```

This ensures:
- Connection errors → user-friendly `ValueError` messages (gateway down, 2FA)
- Business logic errors (order validation, contract qualification) → propagate unchanged
- Cleanup (`ib.disconnect()`) always runs via `cm.__exit__`

### Step 2: Migrate 9 call sites

Each method changes from:
```python
with ibkr_shared_lock:
    ib = self._ensure_connected()
    # body...
```
To:
```python
with ibkr_shared_lock, self._connected() as ib:
    # body...
```

Methods: `list_accounts()`, `search_symbol()`, `preview_order()`, `preview_roll()`, `place_roll()`, `place_order()`, `get_orders()`, `cancel_order()`, `get_account_balance()`

### Step 3: Delete `_ensure_connected()`

Remove old method after all call sites migrated.

### Step 4: Fix `owns_account()` for ephemeral mode

In ephemeral mode `is_connected` is always False and `managed_accounts` is empty. The current fallback to `IBKR_AUTHORIZED_ACCOUNTS` works when that env var is set, but returns False for all accounts when it's unset.

**Fix**: Require `IBKR_AUTHORIZED_ACCOUNTS` for ephemeral trading. No gateway probe — probing introduces races (needs `ibkr_shared_lock`), retries with backoff (slow when gateway is down), and gets called repeatedly from routing paths. The env var is already in `.env.example` and always set in production.

```python
def owns_account(self, account_id: str) -> bool:
    native_id = self._resolve_native_account(account_id)
    if IBKR_AUTHORIZED_ACCOUNTS and native_id not in IBKR_AUTHORIZED_ACCOUNTS:
        return False

    if self._conn_manager.is_connected:
        return native_id in self._conn_manager.managed_accounts

    # Ephemeral mode or not connected — rely on whitelist
    return bool(IBKR_AUTHORIZED_ACCOUNTS) and native_id in IBKR_AUTHORIZED_ACCOUNTS
```

The only change vs current code: the final `return False` becomes `return bool(IBKR_AUTHORIZED_ACCOUNTS) and native_id in IBKR_AUTHORIZED_ACCOUNTS` — same logic, just explicit. If `IBKR_AUTHORIZED_ACCOUNTS` is unset, returns False (IBKR adapter not available for trading). Add a `log.warning` when the env var is empty so it's obvious why IBKR trading isn't working.

### Step 5: Keep `_get_trading_conn_manager()` singleton

Caches the `IBKRConnectionManager` instance (config/factory), not the connection. Each `connection()` call creates a fresh IB instance in ephemeral mode. Still needed.

### Step 6: Update test fake + add new tests

**Update fake**: `tests/brokerage/ibkr/test_adapter_roll.py` — add `connection()` CM to `_FakeConnManager`:
```python
@contextmanager
def connection(self):
    yield self._ib
```

**New tests** (in `tests/brokerage/ibkr/test_adapter_ephemeral.py`):
1. `test_connected_translates_connection_refused` — `ConnectionRefusedError` from `connection()` → `ValueError("IB Gateway is not running...")`
2. `test_connected_translates_auth_error` — exception with "authentication" → `ValueError("IB Gateway authentication expired...")`
3. `test_connected_does_not_catch_business_logic_errors` — `ValueError` raised inside `with _connected()` body propagates unchanged (not remapped to connection error)
4. `test_owns_account_with_authorized_accounts_set` — returns True for listed account, False for unlisted
5. `test_owns_account_no_whitelist_returns_false` — when `IBKR_AUTHORIZED_ACCOUNTS` is empty and not connected, returns False

## Files Modified

| File | Change |
|------|--------|
| `brokerage/ibkr/adapter.py` | Add `contextmanager` import, replace `_ensure_connected()` with `_connected()` CM, update 9 call sites, delete old method, fix `owns_account()` |
| `tests/brokerage/ibkr/test_adapter_roll.py` | Add `connection()` CM to `_FakeConnManager` |
| `tests/brokerage/ibkr/test_adapter_ephemeral.py` | New: 5 tests for `_connected()` error handling and `owns_account()` ephemeral behavior |

## What Does NOT Change

- `ibkr_shared_lock` — still needed (prevents concurrent connects on same client ID within a process)
- `_get_trading_conn_manager()` singleton — caches manager, not connection
- `_build_roll_contract()` — receives `ib` as parameter
- Behavior when `IBKR_CONNECTION_MODE=persistent` — `connection()` CM delegates to `ensure_connected()`

## Limitations

**Cross-process client ID races**: `ibkr_shared_lock` is process-local. Two portfolio-mcp processes using the same `IBKR_TRADE_CLIENT_ID` can still race if their ephemeral windows overlap. This is significantly less likely than persistent-hold conflicts (seconds vs indefinite), but not eliminated. Full fix would require distinct client IDs per process (env var) or a cross-process lock (file lock / IPC). For now, ephemeral dramatically reduces the window and the env var workaround (`IBKR_TRADE_CLIENT_ID=10` for analyst backend) fully eliminates it.

## Verification

1. `pytest tests/brokerage/ibkr/test_adapter_roll.py -v` — roll tests pass
2. `pytest tests/services/test_ibkr_broker_adapter.py -v` — adapter tests pass
3. `pytest tests/ -v` — full suite, no regressions

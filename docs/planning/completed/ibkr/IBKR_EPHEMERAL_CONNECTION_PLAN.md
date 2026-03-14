# IBKR Connection — Ephemeral Mode (Default) with Persistent Toggle

## Context

Multiple Claude sessions each spawn their own ibkr-mcp process, all trying to hold a persistent connection on client ID 20. TWS allows only one connection per client ID, so only the first process succeeds — the rest fail with `TimeoutError`. Worse, killed processes leave "zombie" client ID registrations on TWS that block new connections until TWS is restarted.

Market data (client ID 21) avoids this entirely because `IBKRMarketDataClient` uses **ephemeral** connections — fresh `IB()` per request, disconnect after. We apply the same pattern to the account/metadata path, with an env var to switch back to persistent mode if needed.

## Step 1: Add `IBKR_CONNECTION_MODE` to `ibkr/config.py`

```python
# --- Connection mode ---
_raw_mode = os.getenv("IBKR_CONNECTION_MODE", "ephemeral").lower()
IBKR_CONNECTION_MODE: str = _raw_mode if _raw_mode in ("ephemeral", "persistent") else "ephemeral"
```

Valid: `"ephemeral"` (default), `"persistent"`. Unrecognized values are normalized to `"ephemeral"` so status reporting never exposes invalid strings.

## Step 2: Extract `_do_connect()` and add `connection()` context manager on `IBKRConnectionManager`

**`ibkr/connection.py`:**

Extract the connect-one-attempt logic into a reusable `_do_connect()` that creates and returns a connected `IB()` without storing it as `self._ib`:

```python
def _do_connect(self, attach_events: bool = True) -> "IB":
    """Create fresh IB instance, connect, return it. Does NOT store as self._ib.

    On connect failure, disconnects the IB object to release the client ID
    on TWS before re-raising. This prevents half-open zombie connections.
    """
    from ib_async import IB
    ib = IB()
    if attach_events:
        ib.disconnectedEvent += self._on_disconnect
    try:
        ib.connect(
            host=self._host, port=self._port,
            clientId=self._client_id, timeout=self._timeout,
            readonly=self._readonly,
        )
        return ib
    except Exception:
        if attach_events:
            try:
                ib.disconnectedEvent -= self._on_disconnect
            except Exception:
                pass
        try:
            ib.disconnect()
        except Exception:
            pass
        raise
```

Refactor existing `connect()` to use `_do_connect(attach_events=True)` internally, keeping its retry loop and `self._ib` storage.

Add a `connection()` context manager — the new primary API:

```python
@contextmanager
def connection(self):
    """Yield a connected IB instance. Behavior depends on IBKR_CONNECTION_MODE.

    ephemeral: fresh connection, auto-disconnect on exit.
    persistent: delegates to ensure_connected(), no disconnect on exit.
    """
    if IBKR_CONNECTION_MODE == "persistent":
        yield self.ensure_connected()
        return

    # Ephemeral: connect with retry, yield, disconnect in finally
    last_exc = None
    ib = None
    for attempt in range(1, self._default_max_attempts + 1):
        if attempt > 1:
            delay = self._reconnect_delay * (attempt - 1)
            log_event(portfolio_logger, logging.INFO, "connect.retry",
                      f"in {delay}s", attempt=attempt, max=self._default_max_attempts,
                      error=str(last_exc) or type(last_exc).__name__ if last_exc else None)
            time.sleep(delay)
        try:
            with TimingContext() as tc:
                ib = self._do_connect(attach_events=False)
            log_event(portfolio_logger, logging.INFO, "connect.ephemeral",
                      client_id=self._client_id, elapsed_ms=tc.elapsed_ms)
            break
        except Exception as exc:
            last_exc = exc
            if ib is not None:
                try: ib.disconnect()
                except Exception: pass
                ib = None
    if ib is None:
        log_event(portfolio_logger, logging.ERROR, "connect.failed",
                  client_id=self._client_id, mode="ephemeral",
                  error=str(last_exc) or type(last_exc).__name__ if last_exc else None)
        raise last_exc
    try:
        yield ib
    finally:
        try:
            ib.disconnect()
        except Exception:
            pass
```

Key points:
- Ephemeral mode: no `_on_disconnect` handler, no reconnect thread, no `self._ib` storage
- Persistent mode: thin wrapper around `ensure_connected()`, no disconnect on exit
- Retry with linear backoff (same as `connect()`)
- `ibkr_shared_lock` in `client.py` prevents concurrent ephemeral connections on the same client ID

## Step 3: Update `get_connection_status()` to report mode

Add `"mode": IBKR_CONNECTION_MODE` to the status dict. In ephemeral mode, `connected` will always be `false` and `managed_accounts` will be empty (no persistent connection held). This is expected — the status tool reports the singleton state, and ephemeral connections are transient by design. Account discovery happens per-request via `ib.managedAccounts()` inside each `connection()` context.

## Step 4: Update `IBKRClient` — replace `_get_account_ib()` with `connection()` context manager

**`ibkr/client.py`:**

Replace all 7 methods that call `self._get_account_ib()`:

```python
# BEFORE:
def get_positions(self, account_id=None):
    with ibkr_shared_lock:
        ib = self._get_account_ib()
        resolved = self._resolve_account_id(ib, account_id)
        return fetch_positions(ib, account_id=resolved)

# AFTER:
def get_positions(self, account_id=None):
    with ibkr_shared_lock:
        with self._conn_manager.connection() as ib:
            resolved = self._resolve_account_id(ib, account_id)
            return fetch_positions(ib, account_id=resolved)
```

All 7 methods:
1. `get_positions` — one-shot
2. `get_account_summary` — one-shot
3. `get_pnl` — subscribe/poll/cancel (works fine — connection stays alive during `with` block)
4. `get_pnl_single` — subscribe/poll/cancel (same)
5. `get_contract_details` — one-shot
6. `get_option_chain` — one-shot
7. `get_futures_months` — one-shot (currently has manual `ib.disconnect()` in `finally` — remove that, context manager handles it)

Remove `_get_account_ib()` method (no other callers).

## Step 5: Clean up `get_futures_months()` explicit disconnect

`get_futures_months()` in `client.py` currently wraps in try/finally with `ib.disconnect()`. With the context manager, this is redundant — **remove the manual disconnect** to avoid double-disconnect. Simplify to match the other methods.

## Step 6: Remove `_debug_ibkr_connect` from `ibkr/server.py`

Remove the temporary debug tool added during investigation. The `_error_str()` helper stays (good improvement).

## Step 7: Update `ibkr/locks.py` docstring

```python
ibkr_shared_lock = threading.Lock()
"""Serializes IBKR account/metadata calls.

In persistent mode: serializes access to the shared IB instance.
In ephemeral mode: prevents concurrent connections on the same client ID.
"""
```

## Step 8: Update `ibkr/README.md`

Add connection mode section to the existing docs:
- Document `IBKR_CONNECTION_MODE` env var
- Explain when to use each mode
- Note that ephemeral is default and eliminates stale client ID problems

## Step 9: Tests

Update existing tests + add new ones in `tests/ibkr/test_connection_modes.py`:
1. Ephemeral mode: `connection()` creates fresh IB, disconnects on exit
2. Persistent mode: `connection()` delegates to `ensure_connected()`, no disconnect
3. Ephemeral retry on connect failure
4. `get_connection_status()` reports mode
5. No `_on_disconnect` handler in ephemeral mode
6. `_do_connect()` failure cleanup: verify `disconnect()` is called and event handler is removed on connect failure
7. Update existing `IBKRClient` tests that mock `_get_account_ib` → mock `connection()` context manager

## Files Summary

| File | Change |
|------|--------|
| `ibkr/config.py` | Add `IBKR_CONNECTION_MODE` |
| `ibkr/connection.py` | Extract `_do_connect()`, add `connection()` context manager, update `get_connection_status()` |
| `ibkr/client.py` | 7 methods → `with self._conn_manager.connection() as ib:`, remove `_get_account_ib()` |
| `ibkr/server.py` | Remove `_debug_ibkr_connect` tool |
| `ibkr/locks.py` | Docstring update |
| `ibkr/README.md` | Document ephemeral/persistent modes |
| `tests/ibkr/test_connection_modes.py` | New test file |

## What Doesn't Change

- `IBKRMarketDataClient` — already ephemeral, no changes
- `brokerage/ibkr/adapter.py` (trading) — uses own client ID 22, own non-singleton `IBKRConnectionManager`, always persistent. Its `_ensure_connected()` calls `conn_manager.ensure_connected()` which is unaffected.
- `services/trade_execution_service.py` — `_run_ibkr_recovery_probe()` accesses the **trading adapter's** `_conn_manager` (client ID 22), not the ibkr-mcp singleton (client ID 20). Unaffected.
- `ibkr_shared_lock` — still used, purpose adapts to mode. Note: this is a process-local `threading.Lock` — it serializes within one ibkr-mcp process but cannot prevent cross-process collisions when multiple ibkr-mcp instances run simultaneously. Ephemeral mode mitigates this by holding client ID 20 only for the duration of each request (milliseconds) vs permanently, making collisions rare and transient. The retry loop in `connection()` handles the occasional cross-process race.
- All existing `connect()`, `ensure_connected()`, `disconnect()`, `_on_disconnect()`, `_reconnect()` methods remain (used in persistent mode and by trading adapter)
- `account.py` PnL functions (`fetch_pnl`, `fetch_pnl_single`) — their internal try/finally cleanup for `cancelPnL()` is unchanged. The connection stays alive for the duration of the `with connection() as ib:` block, so subscribe/poll/cancel all work within the same connection.

## Verification

1. `pytest tests/ibkr/` — all tests pass
2. `/mcp` reconnect ibkr-mcp
3. `get_ibkr_status` — shows `mode: "ephemeral"`, `connected: false`
4. `get_ibkr_contract(symbol="AAPL")` — works (ephemeral connect/disconnect)
5. `get_ibkr_status` — still `connected: false` (connection was released)
6. `get_ibkr_snapshot(symbol="AAPL")` — works (market data path unchanged)
7. `get_ibkr_contract(symbol="SLV", info_type="option_chain")` — works
8. Open second Claude session with ibkr-mcp — both work (no client ID collision)
9. Set `IBKR_CONNECTION_MODE=persistent`, reconnect — persistent behavior restored

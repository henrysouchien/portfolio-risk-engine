# Fix `get_ibkr_status` for Ephemeral Connection Mode

**Date**: 2026-03-02
**Status**: COMPLETE (implemented in commit `259debd5`)

## Context

`get_ibkr_status` (ibkr-mcp tool) calls `IBKRConnectionManager.get_connection_status()` which checks `self._ib is not None and self._ib.isConnected()`. In ephemeral mode (the default), `self._ib` is always `None` between requests — so the tool always reports `connected: false` even when the gateway is running and fully functional. We just confirmed this: FIG trade preview succeeded through IBKR, but `get_ibkr_status` returned `connected: false`.

The fix: in ephemeral mode, do an actual probe connection to test reachability rather than checking stale state.

## Implementation

### 1. Add `probe_connection()` to `IBKRConnectionManager`

**`ibkr/connection.py`** — new method on `IBKRConnectionManager`

```python
def probe_connection(self) -> dict[str, Any]:
    """Probe whether IB Gateway is reachable (connect + disconnect).

    For ephemeral mode where is_connected is always False between requests.
    Returns status dict with reachable=True/False and managed_accounts.
    """
    if self._ib is not None and self._ib.isConnected():
        return {"reachable": True, "managed_accounts": list(self._managed_accounts)}

    ib = None
    try:
        ib = self._do_connect(attach_events=False)
        accounts = list(ib.managedAccounts() or [])
        return {"reachable": True, "managed_accounts": accounts}
    except Exception as e:
        return {"reachable": False, "error": str(e)}
    finally:
        if ib is not None:
            try:
                ib.disconnect()
            except Exception:
                pass
```

This reuses `_do_connect()` (line 81) which already handles the IB connect with proper host/port/clientId/timeout. `attach_events=False` matches the ephemeral pattern (line 189).

### 2. Update `get_connection_status()` to use probe in ephemeral mode

**`ibkr/connection.py`** — `get_connection_status()` (line 261)

In ephemeral mode, call `probe_connection()` to get real reachability. In persistent mode, use existing `is_connected` check.

```python
def get_connection_status(self) -> dict[str, Any]:
    """Return diagnostic dict describing current connection state."""
    if IBKR_CONNECTION_MODE == "ephemeral" and not self.is_connected:
        probe = self.probe_connection()
        return {
            "connected": probe["reachable"],
            "host": self._host,
            "port": self._port,
            "client_id": self._client_id,
            "mode": IBKR_CONNECTION_MODE,
            "readonly": self._readonly,
            "managed_accounts": probe.get("managed_accounts", []),
            "reconnecting": self._reconnecting,
            "error": probe.get("error"),
            "config": {
                "timeout": self._timeout,
                "connect_max_attempts": self._default_max_attempts,
                "reconnect_delay": self._reconnect_delay,
                "max_reconnect_attempts": self._max_reconnect_attempts,
            },
        }
    return {
        "connected": self.is_connected,
        "host": self._host,
        "port": self._port,
        "client_id": self._client_id,
        "mode": IBKR_CONNECTION_MODE,
        "readonly": self._readonly,
        "managed_accounts": list(self._managed_accounts),
        "reconnecting": self._reconnecting,
        "config": {
            "timeout": self._timeout,
            "connect_max_attempts": self._default_max_attempts,
            "reconnect_delay": self._reconnect_delay,
            "max_reconnect_attempts": self._max_reconnect_attempts,
        },
    }
```

### 3. No changes to `ibkr/server.py` or `ibkr/client.py`

`get_ibkr_status` in `server.py` (line 317) already calls `client.get_connection_status()` which delegates to the connection manager. The fix flows through automatically.

### 4. Tests

**`tests/ibkr/test_connection_modes.py`** (extend existing)

1. **Ephemeral probe — gateway reachable**: Mock `_do_connect` to return a mock IB with `managedAccounts()` → `["U123"]`. Assert `get_connection_status()` returns `connected: True` and `managed_accounts: ["U123"]`.
2. **Ephemeral probe — gateway unreachable**: Mock `_do_connect` to raise `ConnectionRefusedError`. Assert `get_connection_status()` returns `connected: False` and `error` contains the exception message.
3. **Persistent mode unchanged**: Set `IBKR_CONNECTION_MODE = "persistent"`, verify `get_connection_status()` uses `is_connected` (no probe).

## Files Modified

| File | Change |
|------|--------|
| `ibkr/connection.py` | Add `probe_connection()` method. Update `get_connection_status()` to probe in ephemeral mode (~20 lines) |
| `ibkr/client.py` | Wrap `get_connection_status()` with `ibkr_shared_lock` (1 line) |
| `tests/ibkr/test_connection_modes.py` | 3 new tests |

### 5. Thread safety — wrap probe with `ibkr_shared_lock`

**`ibkr/client.py`** — `get_connection_status()` (line 49)

Currently `get_connection_status()` is NOT wrapped with `ibkr_shared_lock`, but all other account/metadata calls in `client.py` are (lines 112-166). The probe does a real `_do_connect()` using the same client ID, so it can collide with in-flight ephemeral requests.

Fix: wrap the client's `get_connection_status()` with the shared lock:

```python
def get_connection_status(self) -> dict[str, Any]:
    """Return diagnostic dict describing current connection state."""
    with ibkr_shared_lock:
        return self._conn_manager.get_connection_status()
```

`ibkr_shared_lock` is already imported in `client.py` (line 23). This serializes the probe against real requests — same pattern as every other method in the client.

## Notes

- Probe uses a single `_do_connect` call (no retry loop). This keeps the status check fast — we just want to know if the gateway is up, not retry exhaustively.
- Client ID collision prevented by `ibkr_shared_lock` at the client layer — probe can't overlap with real ephemeral connections.
- `_do_connect(attach_events=False)` matches the ephemeral pattern already used in `connection()` context manager (line 189).

## Verification

1. `pytest tests/ibkr/test_connection_modes.py -v` — all tests pass
2. Live test: `/mcp` reconnect ibkr-mcp, then call `get_ibkr_status` — should return `connected: true` when gateway is running

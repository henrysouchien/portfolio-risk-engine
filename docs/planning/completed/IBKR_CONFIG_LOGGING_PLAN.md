# IBKR Package — Config Centralization + Structured Logging

## Context

The `ibkr/` package has grown organically and now has ~10 hardcoded numeric values (timeouts, retry delays, poll intervals) scattered across files, and ~35 unstructured log calls (f-strings). This makes it hard to tune connection behavior without code changes, and hard to diagnose connection issues from logs.

This work centralizes all connection/timeout/retry settings into `ibkr/config.py` with env var overrides, adds structured logging for key connection events, and adds a `get_connection_status()` diagnostic function. Everything stays self-contained in the `ibkr/` package.

## Step 1: Extend `ibkr/config.py` with missing constants

Add `_float_env()` helper (same pattern as `_int_env()`, with `nan`/`inf` guard). Add 8 new constants:

```python
# --- Connection retry ---
IBKR_RECONNECT_DELAY: int = _int_env("IBKR_RECONNECT_DELAY", 5)
IBKR_MAX_RECONNECT_ATTEMPTS: int = _int_env("IBKR_MAX_RECONNECT_ATTEMPTS", 3)

# --- Market data ---
IBKR_MARKET_DATA_RETRY_DELAY: float = _float_env("IBKR_MARKET_DATA_RETRY_DELAY", 2.0)
IBKR_SNAPSHOT_TIMEOUT: float = _float_env("IBKR_SNAPSHOT_TIMEOUT", 5.0)
IBKR_SNAPSHOT_POLL_INTERVAL: float = _float_env("IBKR_SNAPSHOT_POLL_INTERVAL", 0.5)
IBKR_FUTURES_CURVE_TIMEOUT: float = _float_env("IBKR_FUTURES_CURVE_TIMEOUT", 8.0)

# --- Account PnL ---
IBKR_PNL_TIMEOUT: float = _float_env("IBKR_PNL_TIMEOUT", 5.0)
IBKR_PNL_POLL_INTERVAL: float = _float_env("IBKR_PNL_POLL_INTERVAL", 0.1)
```

All defaults match current hardcoded values — zero behavioral change.

## Step 2: Replace hardcoded values with config imports

Mechanical substitutions only. No logic changes.

**`ibkr/connection.py`:**
- `self._reconnect_delay = 5` → `self._reconnect_delay = IBKR_RECONNECT_DELAY`
- `self._max_reconnect_attempts = 3` → `self._max_reconnect_attempts = IBKR_MAX_RECONNECT_ATTEMPTS`

**`ibkr/market_data.py`:**
- `time.sleep(2)` → `time.sleep(IBKR_MARKET_DATA_RETRY_DELAY)`
- `timeout: float = 5.0` → `timeout: float = IBKR_SNAPSHOT_TIMEOUT`
- `poll_interval = 0.5` → `poll_interval = IBKR_SNAPSHOT_POLL_INTERVAL`
- `timeout: float = 8.0` (fetch_futures_curve_snapshot) → `timeout: float = IBKR_FUTURES_CURVE_TIMEOUT`

**`ibkr/account.py`:**
- `timeout_seconds: float = 5.0` (×2) → `timeout_seconds: float = IBKR_PNL_TIMEOUT`
- `poll_interval: float = 0.1` (×2) → `poll_interval: float = IBKR_PNL_POLL_INTERVAL`

**`ibkr/client.py`:**
- `timeout: float = 8.0` (get_futures_curve_snapshot) → `timeout: float = IBKR_FUTURES_CURVE_TIMEOUT`

**`ibkr/compat.py`:**
- `timeout: float = 8.0` (get_futures_curve_snapshot) → `timeout: float = IBKR_FUTURES_CURVE_TIMEOUT`

## Step 3: Add structured logging helpers to `ibkr/_logging.py`

Two additions:

Add `import time` at the top of `_logging.py` for `TimingContext`.

```python
def log_event(logger, level, event, msg="", **fields):
    """Log with structured key=value fields.

    Output: [ibkr.connect] Connected to gateway client_id=20 elapsed_ms=142
    """
    parts = [f"[ibkr.{event}]"]
    if msg:
        parts.append(msg)
    for key, value in fields.items():
        if value is not None:
            parts.append(f"{key}={value}")
    logger.log(level, " ".join(parts))

class TimingContext:
    """Context manager for elapsed time measurement."""
    def __enter__(self):
        self.start = time.monotonic()
        return self
    def __exit__(self, *args):
        self.elapsed_ms = round((time.monotonic() - self.start) * 1000, 1)
```

Works with both monorepo logger and fallback stderr logger — no formatter changes needed.

## Step 4: Instrument key events with structured logging

Replace ~15 high-value log calls (connection lifecycle + snapshot timing). Keep remaining ~20 as-is for incremental migration later.

**`ibkr/connection.py`** — connection lifecycle events:
- `connect()` start: `[ibkr.connect] host=... port=... client_id=...`
- `connect()` success: `[ibkr.connect.ok] client_id=... accounts=... elapsed_ms=...`
- `connect()` retry: `[ibkr.connect.retry] attempt=... max=... error=...`
- `connect()` failure: `[ibkr.connect.failed] client_id=... error=...`
- Disconnect lost: `[ibkr.disconnect] client_id=...`
- Reconnect success/failure: `[ibkr.reconnect.ok]` / `[ibkr.reconnect.failed]`

Wrap `connect()` with `TimingContext` to capture elapsed time.

**`ibkr/market_data.py`** — snapshot + market data events:
- `_request_bars()` retry: `[ibkr.bars.retry] attempt=... max=...`
- `fetch_snapshot()` ready: `[ibkr.snapshot.ok] count=... elapsed_ms=...`
- `fetch_snapshot()` timeout: `[ibkr.snapshot.timeout] count=... elapsed_s=...`

## Step 5: Add `get_connection_status()` to `IBKRConnectionManager`

```python
def get_connection_status(self) -> dict[str, Any]:
    return {
        "connected": self.is_connected,
        "host": self._host,
        "port": self._port,
        "client_id": self._client_id,
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

## Step 6: Expose through `IBKRClient`

```python
def get_connection_status(self) -> dict[str, Any]:
    return self._conn_manager.get_connection_status()
```

## Files Summary

| File | Change |
|------|--------|
| `ibkr/config.py` | Add `_float_env()`, 8 new constants |
| `ibkr/_logging.py` | Add `log_event()`, `TimingContext` |
| `ibkr/connection.py` | Import config constants, structured logging, `get_connection_status()` |
| `ibkr/market_data.py` | Import config constants, structured logging |
| `ibkr/account.py` | Import config constants for PnL timeouts |
| `ibkr/client.py` | Import config constant, `get_connection_status()` passthrough |
| `ibkr/compat.py` | Import config constant for futures curve timeout |

## Verification

1. `pytest tests/ibkr/` — all 129 tests pass
2. Start IBKR Gateway, reconnect ibkr-mcp
3. `get_ibkr_snapshot(symbol="AAPL")` — works, logs show `[ibkr.connect] ... elapsed_ms=...`
4. `get_ibkr_option_prices(...)` — works, logs show `[ibkr.snapshot.ok] count=... elapsed_ms=...`
5. Check logs: `grep '[ibkr.' logs/debug.log` — structured events visible
6. Test config override: `IBKR_SNAPSHOT_POLL_INTERVAL=1.0` → poll interval changes without code change

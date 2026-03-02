# IBKR Connection & Timeout Fixes

## Context

Option snapshot requests (`get_ibkr_option_prices`, `analyze_option_chain`) consistently timeout even for liquid names (SPY, NVDA, SLV). Root cause: `fetch_snapshot()` in `ibkr/market_data.py` defaults to 5.0s — too short for options, which require contract qualification + IBKR model Greek computation before data arrives. Stock snapshots work fine at 5s.

A broader audit of IBKR connection infrastructure also identified reliability gaps: no initial connection retry, lock contention between operations, and per-request connection churn for market data.

**Scope**: Fix the option timeout (P0), add initial connection retry (P1), and clean up minor reliability issues. Lock architecture changes are out of scope for now — they work and the contention is theoretical.

## Step 1: Increase option snapshot timeout (P0)

**File**: `ibkr/market_data.py`

The `fetch_snapshot()` method at line 541 has `timeout: float = 5.0`. Options need more time because IBKR computes model Greeks server-side before returning data.

**Change**: Add a second parameter `option_timeout` and use it for OPT contracts:

```python
from .config import IBKR_OPTION_SNAPSHOT_TIMEOUT

def fetch_snapshot(
    self,
    contracts: list["Contract"],
    timeout: float = 5.0,
    option_timeout: float = IBKR_OPTION_SNAPSHOT_TIMEOUT,
) -> list[dict[str, Any]]:
```

After qualification (line 566-578), determine if ANY contract is an option. If so, use `option_timeout` instead of `timeout` for the `ib.sleep()` call:

```python
has_options = any(
    str(getattr(c, "secType", "") or "").upper() == "OPT"
    for c in qualified_by_index.values()
)
effective_timeout = option_timeout if has_options else timeout
# ... later ...
if effective_timeout > 0:
    ib.sleep(effective_timeout)
```

This is backward-compatible — all existing callers that pass stocks get the same 5s behavior. Option callers automatically get 15s. The `option_timeout` param allows callers to override if needed.

**Note on mixed batches** (R1 fix): If a batch contains both stock and option contracts, all contracts wait for `option_timeout`. In practice this doesn't occur — callers snapshot either stocks or options, never mixed. `_resolve_underlying_price()` in `chain_analysis.py` snapshots a single stock in a separate call.

**Also update `ibkr/config.py`**: Add `IBKR_OPTION_SNAPSHOT_TIMEOUT` env var (default 15) so it's tunable without code changes:

```python
IBKR_OPTION_SNAPSHOT_TIMEOUT: int = _int_env("IBKR_OPTION_SNAPSHOT_TIMEOUT", 15)
```

The signature default reads from config at import time (`IBKR_OPTION_SNAPSHOT_TIMEOUT`), not hardcoded.

## Step 2: Add initial connection retry (P1)

**File**: `ibkr/connection.py`

Currently `connect()` (line 74) fails immediately if the gateway isn't reachable. The `_reconnect()` method (line 168) has retry logic but only fires on unexpected disconnect — not initial connection failure.

**Change**: Add retry logic to `connect()` with a configurable attempt count. The `__init__` stores a default from config, and `connect()` uses it when no explicit value is passed:

**Imports**: Add `IBKR_CONNECT_MAX_ATTEMPTS` to the existing import from `.config` (line 17).

```python
def __new__(cls, client_id=None, **kwargs):
    # **kwargs accepts default_max_attempts without TypeError
    ...  # existing singleton logic unchanged

def __init__(self, client_id=None, default_max_attempts=None):
    ...
    self._default_max_attempts = default_max_attempts or IBKR_CONNECT_MAX_ATTEMPTS

def connect(self, max_attempts: int | None = None):
    """Connect to IB Gateway. Thread-safe and idempotent."""
    effective_attempts = max_attempts if max_attempts is not None else self._default_max_attempts
    with self._connect_lock:
        if self._ib is not None and self._ib.isConnected():
            return self._ib

        from ib_async import IB

        last_exc = None
        for attempt in range(1, effective_attempts + 1):
            if attempt > 1:
                delay = self._reconnect_delay * (attempt - 1)
                portfolio_logger.info(
                    f"IB connect attempt {attempt}/{effective_attempts} in {delay}s..."
                )
                time.sleep(delay)

            ib = IB()
            ib.disconnectedEvent += self._on_disconnect
            try:
                ib.connect(
                    host=self._host,
                    port=self._port,
                    clientId=self._client_id,
                    timeout=self._timeout,
                    readonly=self._readonly,
                )
                self._ib = ib
                self._managed_accounts = list(ib.managedAccounts() or [])
                portfolio_logger.info(f"Connected to IB Gateway. Managed accounts: {self._managed_accounts}")
                return ib
            except Exception as exc:
                last_exc = exc
                try:
                    ib.disconnectedEvent -= self._on_disconnect
                except Exception:
                    pass
                try:
                    ib.disconnect()
                except Exception:
                    pass
                if attempt < effective_attempts:
                    portfolio_logger.warning(f"IB connect attempt {attempt} failed: {exc}")

        raise last_exc

def ensure_connected(self):
    if self._ib is not None and self._ib.isConnected():
        return self._ib
    return self.connect()  # uses _default_max_attempts
```

This way ibkr-mcp's lazy connection via `ensure_connected()` automatically retries (default 3 from env var). Trading adapter's `_ensure_connected()` also benefits. Singleton `__init__` guard means the first construction sets the value — fine since `IBKR_CONNECT_MAX_ATTEMPTS` is read at import.

**`_reconnect()` nesting** (R1+R2 fix): `_reconnect()` has its own outer 3-attempt loop with linear backoff (5s, 10s, 15s = 30s + 3×10s timeout = 60s worst case). To avoid 3×3=9 total attempts, `_reconnect()` must call `self.connect(max_attempts=1)` explicitly. The outer loop already provides retry semantics.

**File**: `ibkr/market_data.py` — `_connect_ib()` (line 98)

Add a single retry for per-request market data connections, but **only in the `_request_bars()` path** (R1 fix — critical):

`_connect_ib()` is called from two lock contexts:
1. `_request_bars()` — under `_ibkr_request_lock` (module-level, only blocks other bar requests)
2. `fetch_snapshot()` — under `ibkr_shared_lock` (global, blocks ALL IBKR ops)

Adding retry to `_connect_ib()` inside `ibkr_shared_lock` would hold the lock for up to 22s (10s timeout × 2 attempts + 2s backoff), blocking account queries and trading.

**Imports**: Add `IBKR_CONNECT_MAX_ATTEMPTS` and `IBKR_OPTION_SNAPSHOT_TIMEOUT` to the existing import from `.config` (line 22).

**Solution**: Keep `_connect_ib()` as single-attempt (no retry). Instead, add retry at the `_request_bars()` call site only:

```python
def _request_bars(self, ...):
    with _ibkr_request_lock:
        last_exc = None
        for attempt in range(1, IBKR_CONNECT_MAX_ATTEMPTS + 1):
            if attempt > 1:
                time.sleep(2)
                portfolio_logger.info(f"Market data connect retry {attempt}...")
            try:
                ib = self._connect_ib()
                break
            except IBKRConnectionError as exc:
                last_exc = exc
                if attempt == IBKR_CONNECT_MAX_ATTEMPTS:
                    raise last_exc
        # ... rest of bar request logic
```

`fetch_snapshot()` stays single-attempt under `ibkr_shared_lock` — fail fast, don't block other operations.

## Step 3: Add `IBKR_CONNECT_MAX_ATTEMPTS` to config (P1)

**File**: `ibkr/config.py`

```python
IBKR_CONNECT_MAX_ATTEMPTS: int = _int_env("IBKR_CONNECT_MAX_ATTEMPTS", 3)
```

Used by `IBKRConnectionManager.__init__` (default for `connect()`) and `_request_bars()` retry loop.

## Files Summary

### Modify

| File | Change |
|------|--------|
| `ibkr/config.py` | Add `IBKR_OPTION_SNAPSHOT_TIMEOUT` (15s) and `IBKR_CONNECT_MAX_ATTEMPTS` (3) |
| `ibkr/market_data.py` | Add `option_timeout` param to `fetch_snapshot()`, use config default. Add retry loop to `_request_bars()` call site (not `_connect_ib()`). |
| `ibkr/connection.py` | Add `max_attempts` param to `connect()` with retry loop. |

### Auto-benefits (no changes needed)

| File | Reason |
|------|--------|
| `ibkr/server.py` | `get_ibkr_option_prices` calls `fetch_snapshot()` with default args — auto-benefits from new `option_timeout` default |
| `mcp_tools/chain_analysis.py` | `fetch_snapshot()` call at line 342 auto-benefits |
| `options/analyzer.py` | `fetch_snapshot()` call at line 170 for IBKR Greeks enrichment — auto-benefits |
| `ibkr/locks.py` | Lock architecture works, contention is theoretical — defer to future if real issues arise |

### Existing callers with explicit timeout (unaffected)

| File | Detail |
|------|--------|
| `ibkr/market_data.py` `fetch_futures_curve_snapshot()` | Passes `timeout=8.0` — futures are `secType="FUT"`, so `option_timeout` is not used |

## Out of Scope (documented for future)

- **Lock refactoring**: `ibkr_shared_lock` is non-reentrant and shared across all ops. Theoretical deadlock risk from callbacks, but no observed issues. Would require splitting into per-concern locks (account, market data, trading) — significant refactor.
- **Persistent market data connection**: `fetch_snapshot()` creates/destroys an IB connection per call. A persistent pool would reduce overhead but adds lifecycle complexity. Current approach works.
- **Smart timeout**: Polling for data arrival instead of fixed `ib.sleep()`. Would make snapshots faster on average but adds complexity. The 15s ceiling is acceptable.

## Verification

1. `pytest tests/ibkr/` — existing IBKR tests still pass
2. Start IBKR Gateway / TWS
3. Test stock snapshot: `get_ibkr_snapshot(symbol="AAPL")` — should return in ~5s as before
4. Test option snapshot: `get_ibkr_option_prices(symbol="SPY", expiry="20260320", strikes=[580, 585, 590], right="P")` — should return bid/ask/greeks within 15s instead of timing out
5. Test chain analysis: `analyze_option_chain(symbol="SLV", expiry="20260619")` — should return OI/volume data
6. Test connection retry: Stop gateway, call snapshot → should retry and fail with clear error after attempts exhausted
7. `pnpm build` in frontend — unrelated, but sanity check nothing broke

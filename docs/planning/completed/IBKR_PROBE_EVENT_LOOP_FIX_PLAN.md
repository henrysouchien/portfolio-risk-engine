# Fix IBKR Status Probe Event Loop Error

## Context

`get_ibkr_status` returns `connected: false` with error `"There is no current event loop in thread 'AnyIO worker thread'"`. The IBKR Gateway is actually reachable — positions load fine via portfolio-mcp. The error is in the diagnostic probe itself: `probe_connection()` calls `ib_async.IB().connect()` which requires an asyncio event loop, but AnyIO worker threads (FastMCP dispatch) don't have one.

**Two affected call paths:**
1. **ibkr-mcp status tool** — `ibkr/server.py` does NOT apply `nest_asyncio` before FastMCP init (unlike `mcp_server.py:115-120` which does)
2. **Provider routing** — `providers/routing.py:331` calls `probe_connection()` from worker threads via `is_provider_available("ibkr")`

## Codex Review Feedback (R1)

- **TCP fallback produces false positives** — socket connect doesn't mean IB API works. Do NOT let TCP probe flip `reachable=True`.
- **Fix is too narrow** — `ensure_event_loop()` should go in `_do_connect()`, not just `probe_connection()`. The reconnect thread (`_reconnect()`) and ephemeral `connection()` context manager have the same exposure.
- **Handle closed loops** — `ensure_event_loop()` must also check `loop.is_closed()`.
- **nest_asyncio in server.py** is good hardening but not the primary fix.
- **Tests need real thread-based regression**, not just mock assertions.

## Changes (Revised)

### 1. `ibkr/asyncio_compat.py` — Add `ensure_event_loop()` utility

Handles both missing and closed event loops:

```python
def ensure_event_loop() -> None:
    """Ensure the current thread has a usable event loop.

    In non-main threads (AnyIO workers, reconnect threads), Python 3.10+
    raises RuntimeError from get_event_loop(). This creates and sets a new
    loop if the current one is missing or closed.
    """
    try:
        loop = asyncio.get_event_loop_policy().get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
```

### 2. `ibkr/connection.py` — Add `ensure_event_loop()` in `_do_connect()`

Call `ensure_event_loop()` at the top of `_do_connect()` (line 78) — this protects ALL callers: `connect()`, ephemeral `connection()`, `probe_connection()`, and `_reconnect()`.

```python
def _do_connect(self, attach_events: bool = True):
    """Create and connect a fresh IB instance without storing to self._ib."""
    from .asyncio_compat import ensure_event_loop
    ensure_event_loop()

    from ib_async import IB
    # ... rest unchanged
```

No TCP fallback. No changes to `probe_connection()` itself — it already handles exceptions cleanly and returns `{"reachable": False, "error": str(e)}`.

### 3. `ibkr/market_data.py` — Add `ensure_event_loop()` in `_connect_ib()`

Same pattern for consistency:

```python
def _connect_ib(self):
    from .asyncio_compat import ensure_event_loop
    ensure_event_loop()

    from ib_async import IB
    # ... rest unchanged
```

### 4. `ibkr/server.py` — Add `nest_asyncio.apply()` (hardening)

Insert after line 23 (after `load_dotenv`), before `sys.stdout = _real_stdout`:

```python
# Apply nest_asyncio early so ib_async sync wrappers work inside FastMCP's event loop.
try:
    import nest_asyncio
    nest_asyncio.apply()
except Exception:
    pass
```

Matches `mcp_server.py:115-120`. Supplementary hardening for re-entrant loop cases.

### 5. Tests

**Key principle**: Thread tests must run the REAL `_do_connect()` / `_connect_ib()` code paths — only mock `ib_async.IB` itself. This proves `ensure_event_loop()` placement is correct. If only `_do_connect` is mocked, a broken placement would still pass.

Add to `tests/ibkr/test_connection_modes.py`:

- **`test_do_connect_bare_thread_has_event_loop`** — spawn a `threading.Thread`, run real `_do_connect()` with a fake `ib_async.IB` class (monkeypatch `ib_async.IB`). Inside fake `IB.connect()`, assert `asyncio.get_event_loop()` succeeds and `not loop.is_closed()`. This proves `ensure_event_loop()` runs before `IB` import/connect.
- **`test_probe_from_bare_thread`** — spawn a `threading.Thread`, call real `probe_connection()` (which calls real `_do_connect()`) with fake `ib_async.IB`. Verify returns `{"reachable": True}`, no RuntimeError.
- **`test_reconnect_from_bare_thread`** — run `_reconnect()` in a fresh thread with fake `ib_async.IB`, verify `ensure_event_loop` is invoked via the real `_do_connect()` path.

Add to `tests/ibkr/test_asyncio_compat.py` (or create if needed):

- **`test_ensure_event_loop_creates_loop_in_bare_thread`** — run `ensure_event_loop()` in `threading.Thread`, verify `asyncio.get_event_loop()` succeeds and loop is open.
- **`test_ensure_event_loop_replaces_closed_loop`** — set a closed loop, call `ensure_event_loop()`, verify new open loop.

Add to `tests/providers/test_routing_ibkr.py`:

- **`test_is_provider_available_ibkr_from_bare_thread`** — spawn a `threading.Thread`, call `is_provider_available("ibkr")` with `IBKRConnectionManager.probe_connection` mocked to return `{"reachable": True}`. Verify no event loop error, result is `True`, and cache stores `True` (not a false negative).

## Files

| File | Change |
|------|--------|
| `ibkr/asyncio_compat.py` | Add `ensure_event_loop()` (missing + closed loop handling) |
| `ibkr/connection.py` | Add `ensure_event_loop()` call at top of `_do_connect()` |
| `ibkr/market_data.py` | Add `ensure_event_loop()` call at top of `_connect_ib()` |
| `ibkr/server.py` | Add `nest_asyncio.apply()` before FastMCP init |
| `tests/ibkr/test_connection_modes.py` | 3 new tests (real _do_connect path in bare threads) |
| `tests/ibkr/test_asyncio_compat.py` | 2 new tests (bare thread, closed loop) |
| `tests/providers/test_routing_ibkr.py` | 1 new test (routing from bare thread) |

## Implementation Order

1. `ibkr/asyncio_compat.py` — add `ensure_event_loop()` (no dependencies)
2. `ibkr/connection.py` — add call in `_do_connect()`
3. `ibkr/market_data.py` — add call in `_connect_ib()`
4. `ibkr/server.py` — add `nest_asyncio.apply()`
5. Tests

## Verification

1. Run existing IBKR tests: `pytest tests/ibkr/ -v`
2. Run new tests specifically
3. Call `get_ibkr_status` via ibkr-mcp — should return `connected: true` (or clean `connected: false` with real error if Gateway is down, not event loop error)
4. Call `get_positions` via portfolio-mcp — should still work (no regression)

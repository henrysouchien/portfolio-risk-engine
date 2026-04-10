# Positions Fetch Timeout Fix

> **Status: DEFERRED (2026-04-08).** After 12 rounds of Codex review, the plan kept uncovering deeper Python concurrency edge cases (uncancellable threads, gate races, future-vs-thread liveness, CLI shutdown hangs). The findings were real, but they revealed that we're optimizing a workaround for a constraint that shouldn't exist on the request path. The right fix is the **brokerage aggregator architecture** — decouple data collection from data serving via background sync workers and a positions store. See `BROKERAGE_AGGREGATOR_DESIGN_BRIEF.md`. This plan is preserved for reference; do NOT implement.

## Problem

`get_positions` hangs for 17+ minutes when Schwab or IBKR brokers are offline. The entire position pipeline blocks, making the tool unusable until the TCP socket eventually times out. Users see no feedback — the request simply stalls.

## Root Cause

**There is no orchestrator-level deadline that caps total wall time regardless of individual provider behavior.** `services/position_service.py:649` — the parallel provider fetch loop calls `as_completed(futures)` with no `timeout` parameter (default `None` = wait forever):

```python
# Line 636-649
with ThreadPoolExecutor(max_workers=len(providers_to_fetch)) as executor:
    futures = {
        executor.submit(self._invoke_get_positions_df, ...): provider_name
        for provider_name in providers_to_fetch
    }
    for future in as_completed(futures):   # <-- no timeout, blocks indefinitely
```

When a broker is offline, `_fetch_fresh_positions()` (line 2048) calls `provider_impl.fetch_positions()`, which makes HTTP/socket calls that can block on TCP connect/read. Individual providers have varying levels of request-level timeout coverage:
- **IBKR** has explicit timeouts (`IBKR_TIMEOUT=10s` connect, `IBKR_REQUEST_TIMEOUT=30s` per-request at `ibkr/config.py:47,50`, applied at `ibkr/connection.py:90-97`), but these only cover the `ib_async` connection layer and may not protect all code paths (e.g. reconnect loops).
- **Schwab** inherits a default 30s HTTP timeout from the `schwab-py` base client (`brokerage/schwab/client.py:208-226`), but this only covers individual HTTP requests — not the full fetch orchestration.
- **SnapTrade** and **Plaid's** holdings loaders have no explicit request-level timeout and rely on OS TCP defaults (typically 75-120s or longer).

These per-provider timeouts are insufficient because: (a) not all providers have them, (b) they may not cover all code paths within a provider, and (c) there is no aggregate cap — even if each individual request eventually times out, a provider that makes multiple sequential requests or enters a retry loop can still block for an unbounded total duration. The stale-cache fallback at line 1114 only triggers on **exception**, but the hang prevents any exception from being raised in the worst case.

The single-provider path (line 605-628) has the same problem: `_invoke_get_positions_df` blocks indefinitely with no timeout wrapper.

Additionally, `refresh_provider_positions()` (line 2101-2127) calls `_fetch_fresh_positions()` directly, bypassing `_get_positions_df` entirely. This path is reachable from `mcp_tools/positions.py:61-67` (`_refresh_and_load_positions`), `routes/plaid.py:1600-1606` (Plaid disconnect resync), and `routes/snaptrade.py:1088-1094` (SnapTrade disconnect resync). It has no timeout and no fallback — a hung provider blocks the caller indefinitely.

## Fix Strategy

**Per-provider fetch timeout via `_fetch_fresh_with_timeout()`** — wrap the `_fetch_fresh_positions()` call inside `_get_positions_df` (line 1092) with a dedicated single-thread executor and `future.result(timeout=...)`. Timed-out providers raise a specific `ProviderTimeoutError` that feeds into the EXISTING fallback path in `_get_positions_df` (lines 1113-1135). The outer parallel executor (`as_completed` loop at line 649) needs no change — each `_get_positions_df` call now returns promptly (either with fresh data or via the cache fallback after timeout). No new fallback helper, no per-provider socket hacks.

Key design decisions:
1. **Raise into existing fallback, don't extract a new helper.** The catch block at line 1113 already handles `hours_ago`, `cache_is_fresh`, `force_refresh`, `reprice_cached_positions`, `consolidate`, `defer_cached_repricing`, and sets all the metadata flags (`cache_fallback`, `stale_fallback`, `force_refresh_fallback`, `cached_repricing_skipped`). A new `_try_stale_cache_fallback()` would drop this context. Instead, the timeout raises `ProviderTimeoutError` inside `_get_positions_df`, letting the existing `except Exception as fetch_error:` handler at line 1113 deal with it.
2. **Manual executor lifecycle in the timeout wrapper.** The `_fetch_fresh_with_timeout` method creates its own single-thread executor and calls `shutdown(wait=False, cancel_futures=True)` (Python 3.9+, we're on 3.13) in a `finally` block to abandon the stuck thread. The outer `with ThreadPoolExecutor(...)` at line 636 is unchanged — its `shutdown(wait=True)` is safe because each future now completes promptly.
3. **No per-provider socket timeouts added.** Some providers already have request-level timeouts (IBKR: 10s connect + 30s request; Schwab: 30s HTTP via `schwab-py` base client), but these are insufficient — they don't cover all code paths and provide no aggregate cap. SnapTrade and Plaid have no explicit request-level timeout. Rather than patching each provider individually (`signal.alarm` and `socket.setdefaulttimeout` are unsafe in threads), the orchestrator-level timeout is the correct fix — the calling function returns promptly regardless of provider behavior.
4. **No new flag type.** Provider errors already surface through `cache_info[provider]["error"]` at `core/position_flags.py:107-118`, which emits a `type: "provider_error"` flag. The timeout error string flows through `_provider_metadata[provider]["fetch_error"]` → `result._cache_metadata[provider]["error"]` → `cache_info` → existing flag generation.

## Implementation Steps

### Step 1: ProviderTimeoutError exception class + per-provider fetch gate

**File:** `services/position_service.py` (top of file, after imports)

Add:
```python
_POSITION_FETCH_TIMEOUT = float(os.environ.get("POSITION_FETCH_TIMEOUT_SECONDS", "45"))


class ProviderTimeoutError(ValueError):
    """Raised when a provider fetch exceeds the orchestrator timeout.

    Subclasses ValueError so the disconnect route handlers' inner
    `except ValueError` catch fires correctly (see Step 3.5).
    """
    pass


class ProviderFetchError(Exception):
    """Raised by the worker wrapper when a provider's underlying call
    raises `TimeoutError` / `socket.timeout` from inside the worker
    thread.

    This exception type exists ONLY so that `future.result(timeout=...)`
    raising `TimeoutError` is unambiguous: it can only mean an
    orchestrator-level timeout, never a worker-raised timeout. The
    worker wrapper (`_wrapped_fetch_fresh_positions`) converts any
    worker-raised `TimeoutError` / `socket.timeout` into
    `ProviderFetchError` BEFORE the future ever sees it. This sidesteps
    the Python 3.11+ change where `concurrent.futures.TimeoutError IS
    TimeoutError`, and removes the need for `future.done()` race-prone
    discrimination after the catch.

    `ProviderFetchError` is re-raised unchanged from
    `_fetch_fresh_with_timeout` so the caller's existing fallback path
    (`except Exception as fetch_error:` at line 1113) handles it
    identically to any other provider error.
    """
    pass
```

The 45s default accounts for IBKR's 30s `IBKR_REQUEST_TIMEOUT` plus network overhead. Configurable via env var for slow-network deployments.

**Per-provider fetch gate** — prevents abandoned timeout threads from accumulating on repeated outages. Each timed-out provider fetch leaves a live thread until the underlying network call returns (OS TCP timeout, typically 75-120s). In a long-lived API server, repeated `get_positions` calls during an extended outage would spawn a new abandoned thread each time, eventually exhausting server resources.

**Module-level gate keyed by `(user_email, provider_name)`** — `PositionService` is created fresh per request (`position_service.py:344`, `routes/positions.py:385`, `services/position_snapshot_cache.py:90`), so a per-instance gate would be useless — each new request gets a fresh dict. Instead, the gate is a **module-level** dict keyed by `(user_email, provider_name)` tuple. The key includes user_email because `_fetch_fresh_positions()` calls `provider_impl.fetch_positions(self.config.user_email, ...)` at line 2063 — a per-provider-only gate would cause user A's hung Schwab fetch to block user B's independent Schwab fetch. With the tuple key, each user gets at most 1 abandoned thread per provider:

```python
# Module-level, after _POSITION_FETCH_TIMEOUT:
_PROVIDER_FETCH_GATES: Dict[Tuple[str, str], threading.Thread] = {}  # (user_email, provider)
_PROVIDER_FETCH_GATES_LOCK = threading.Lock()
```

This tracks the inner worker thread per (user, provider) pair across all `PositionService` instances within the process. Before spawning a new fetch thread in `_fetch_fresh_with_timeout`, check if a previous abandoned thread for this (user, provider) pair is still alive. If so, skip the fetch and raise `ProviderTimeoutError` immediately (which feeds into the existing stale-cache fallback). This caps abandoned threads at 1 per user per provider (max 5 × N_users total, bounded by active concurrent users).

### Step 2: Timeout wrapper on `_invoke_get_positions_df`

**File:** `services/position_service.py` — new private method

Add a thin wrapper that runs `_invoke_get_positions_df` in a single-thread executor with `future.result(timeout=...)`. This wrapper is called from both the single-provider and multi-provider paths, so the timeout applies uniformly:

```python
def _invoke_with_timeout(
    self,
    *,
    provider: str,
    use_cache: bool,
    force_refresh: bool,
    consolidate: bool,
    allow_stale_cache: bool = False,
    reprice_cached_positions: bool = True,
    timeout: float = _POSITION_FETCH_TIMEOUT,
) -> Tuple[pd.DataFrame, bool, Optional[float]]:
    """Call _invoke_get_positions_df with a timeout.

    Raises ProviderTimeoutError if the provider doesn't respond within
    ``timeout`` seconds. The timeout is applied at the orchestrator level
    so the exception flows into _get_positions_df's existing fallback path.
    """
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(
            self._invoke_get_positions_df,
            provider=provider,
            use_cache=use_cache,
            force_refresh=force_refresh,
            consolidate=consolidate,
            allow_stale_cache=allow_stale_cache,
            reprice_cached_positions=reprice_cached_positions,
        )
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        raise ProviderTimeoutError(
            f"Provider {provider} timed out after {timeout:.0f}s"
        )
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
```

**Wait — this won't work.** The timeout needs to wrap `_fetch_fresh_positions`, not `_invoke_get_positions_df`. The `_invoke_get_positions_df` → `_get_positions_df` call includes cache checks; the timeout should only apply to the live fetch. The existing fallback at line 1113 catches exceptions from `_fetch_fresh_positions` (line 1092). So the timeout must be injected there.

**Revised approach:** Wrap `_fetch_fresh_positions` at line 1092 in `_get_positions_df` with a per-call timeout:

```python
# In _get_positions_df, replace line 1092:
#     df = self._fetch_fresh_positions(provider)
# With:
df = self._fetch_fresh_with_timeout(provider)
```

### Step 2 (revised): Timeout on `_fetch_fresh_positions`

**File:** `services/position_service.py` — new private method, plus a worker wrapper

**Worker wrapper — converts worker-raised `TimeoutError` / `socket.timeout` to `ProviderFetchError`.** This is the key to making `future.result(timeout=...)` raising `TimeoutError` *unambiguously* mean orchestrator timeout. By the time the future ever reflects an exception, the worker function can no longer raise `TimeoutError` — the wrapper has already converted it. This eliminates the `future.done()` race entirely (where the worker could finish between `future.result()` raising and the caller checking `future.done()`):

```python
def _wrapped_fetch_fresh_positions(self, provider: str) -> pd.DataFrame:
    """Worker wrapper that runs inside the inner executor thread.

    Converts any TimeoutError / socket.timeout raised from inside
    `_fetch_fresh_positions` (or any provider code it calls) into
    `ProviderFetchError` BEFORE returning to the future. This makes
    `future.result(timeout=...)` raising `TimeoutError` mean
    *orchestrator timeout* unambiguously — the worker can no longer
    raise `TimeoutError` into the future at all.

    All other exceptions propagate unchanged.
    """
    import socket  # local import; module-level import added in Step 6 if not present
    try:
        return self._fetch_fresh_positions(provider)
    except socket.timeout as exc:
        raise ProviderFetchError(
            f"Provider {provider} worker socket timeout"
        ) from exc
    except TimeoutError as exc:
        raise ProviderFetchError(
            f"Provider {provider} worker timeout"
        ) from exc
```

Note: `socket.timeout` is a subclass of `OSError` on Python 3.10+ (and on earlier 3.x via the `IOError` alias chain). The wrapper catches `socket.timeout` *first* so it is converted, while other `OSError` subclasses (e.g. `ConnectionRefusedError`) continue to propagate unchanged through the existing `except Exception` handler at line 1113. We deliberately do NOT catch broad `OSError` here — only the timeout flavors that would otherwise alias to `TimeoutError`.

**Now the orchestrator wrapper:**

```python
def _fetch_fresh_with_timeout(self, provider: str) -> pd.DataFrame:
    """Wrap _fetch_fresh_positions with an orchestrator-level timeout.

    Uses a dedicated single-thread executor so we can abandon the thread
    via shutdown(wait=False, cancel_futures=True) if it blocks.

    Per-(user, provider) gate (module-level): if a previous abandoned
    thread for this user+provider is still alive (from a prior timed-out
    fetch), skip the fetch and raise ProviderTimeoutError immediately.
    This caps abandoned threads at 1 per user per provider, preventing
    thread accumulation during extended outages in long-lived server
    processes. The key includes user_email so that one user's hung
    fetch does not block a different user's independent fetch.
    """
    gate_key = (self.config.user_email, provider)

    executor = ThreadPoolExecutor(max_workers=1)
    own_thread = None
    try:
        # -- Lock-protected critical section: check + submit + register --
        # Holding the lock through check → submit → register eliminates
        # a race where two concurrent requests both pass the gate check
        # before either registers its thread. The submit() call itself
        # is fast (just enqueues work on the executor's thread), so
        # the lock is held only briefly.
        #
        # IMPORTANT: `add_done_callback()` is NOT called inside this
        # lock. `Future.add_done_callback()` invokes the callback
        # IMMEDIATELY (synchronously, on the calling thread) if the
        # future is already finished — and the callback itself acquires
        # `_PROVIDER_FETCH_GATES_LOCK`. Calling it under the lock would
        # deadlock the fast-success path. We register the callback
        # AFTER releasing the lock (see below).
        with _PROVIDER_FETCH_GATES_LOCK:
            prev_thread = _PROVIDER_FETCH_GATES.get(gate_key)
            if prev_thread is not None and prev_thread.is_alive():
                executor.shutdown(wait=False, cancel_futures=True)
                raise ProviderTimeoutError(
                    f"Provider {provider} fetch skipped — previous fetch "
                    f"still running from a prior timeout"
                )

            future = executor.submit(self._wrapped_fetch_fresh_positions, provider)
            # Track the inner worker thread so the gate can detect it later.
            # ThreadPoolExecutor._threads is a set; grab the (only) thread.
            workers = list(executor._threads)
            if workers:
                own_thread = workers[0]
                _PROVIDER_FETCH_GATES[gate_key] = own_thread

        # -- Self-cleaning done-callback, registered OUTSIDE the lock --
        #
        # Why outside the lock: `Future.add_done_callback()` invokes the
        # callback IMMEDIATELY (synchronously, on the current thread)
        # if the future is already finished. On a fast-success or
        # fast-error path, the worker may finish between `submit()`
        # and this line — in which case the callback fires here, on
        # the caller thread. The callback acquires
        # `_PROVIDER_FETCH_GATES_LOCK` to remove its entry. If we held
        # the lock here, that would self-deadlock.
        #
        # Releasing the lock first opens a small window where another
        # thread could check the gate and observe the just-registered
        # entry. That is the desired behavior — a concurrent fetch for
        # the same (user, provider) should see the in-flight worker.
        # The race is benign: either the callback has already fired
        # (the gate is empty, the new fetch starts a fresh worker), or
        # it has not (the gate is set, the new fetch skip-fasts).
        #
        # The callback only deletes its own key (identity-checked
        # against the worker thread it registered for), so it never
        # clobbers a newer submission that has reused the same
        # `(user, provider)` slot.
        def _clear_gate_on_done(_f, _key=gate_key, _own_thread=own_thread):
            with _PROVIDER_FETCH_GATES_LOCK:
                current = _PROVIDER_FETCH_GATES.get(_key)
                if current is _own_thread:
                    _PROVIDER_FETCH_GATES.pop(_key, None)

        future.add_done_callback(_clear_gate_on_done)

        # -- Wait for the result with the orchestrator timeout --
        #
        # Because `_wrapped_fetch_fresh_positions` converts any
        # worker-raised `TimeoutError` / `socket.timeout` into
        # `ProviderFetchError` BEFORE returning to the future, a
        # `TimeoutError` raised here can ONLY come from
        # `future.result(timeout=...)` itself — i.e. the orchestrator
        # timeout. There is no need to inspect `future.done()`; the
        # exception type alone is now sufficient and there is no race.
        try:
            result = future.result(timeout=_POSITION_FETCH_TIMEOUT)
        except TimeoutError:
            # Orchestrator timeout — worker is still blocked inside the
            # underlying provider network call. Do NOT clear the gate;
            # the done-callback will clear it later when the worker
            # eventually finishes (after OS TCP timeout, ~75-120s).
            raise ProviderTimeoutError(
                f"Provider {provider} timed out after {_POSITION_FETCH_TIMEOUT:.0f}s"
            )
        # Any other exception (ProviderFetchError from the wrapper, or
        # any provider error like auth failure / network error /
        # ValueError) propagates naturally. The worker thread has
        # terminated; the done-callback has already fired and removed
        # the gate entry.
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    # Fetch succeeded. The done-callback already cleared the gate when
    # the future completed; no explicit pop needed here.
    return result
```

**Why the worker wrapper, not `future.done()`**: Codex round 11 caught a race where, after `future.result(timeout=...)` raises `TimeoutError`, the worker can finish between the catch and the `future.done()` inspection. That race would misclassify an orchestrator timeout as a worker-raised timeout, breaking the `ProviderTimeoutError` (`ValueError` subclass) path that the disconnect routes depend on (Step 3.5). The worker-wrapper approach eliminates the race at the source: the wrapper converts any worker-raised `TimeoutError` / `socket.timeout` to `ProviderFetchError` *before* the future ever reflects it, so by the time `future.result()` could possibly raise `TimeoutError`, that exception can ONLY have come from `future.result(timeout=...)` itself — the orchestrator. No `future.done()` check needed, no race.

**Why `add_done_callback` is registered outside the lock**: Codex round 11 also caught a deadlock: `Future.add_done_callback()` invokes the callback IMMEDIATELY (synchronously, on the calling thread) if the future is already finished. On a fast-success or fast-error path, the worker can finish between `submit()` and the `add_done_callback()` call. If we registered the callback while holding `_PROVIDER_FETCH_GATES_LOCK`, the callback would try to reacquire the same lock and self-deadlock. The fix: release the lock after submit+register, THEN call `add_done_callback`. The brief window between releasing the lock and registering the callback is harmless — a concurrent fetch for the same `(user, provider)` either sees the entry (and skip-fasts) or sees an already-cleared entry (and starts a fresh fetch); both outcomes are correct.

This is called from two sites: line 1092 in `_get_positions_df` (Step 3) and line 2123 in `refresh_provider_positions` (Step 3.5). In `_get_positions_df`, `ProviderTimeoutError` (a `ValueError` subclass) is caught by the existing `except Exception as fetch_error:` at line 1113, which triggers the full fallback path with all metadata flags intact. In `refresh_provider_positions`, it propagates to the caller — and because it subclasses `ValueError`, the disconnect route handlers' inner `except ValueError` catch fires correctly (see Step 3.5 for details).

### Step 3: Wire the timeout into `_get_positions_df`

**File:** `services/position_service.py:1092`

Change:
```python
df = self._fetch_fresh_positions(provider)
```
To:
```python
df = self._fetch_fresh_with_timeout(provider)
```

That's it. One line change. The existing `except Exception as fetch_error:` block at 1113 handles everything:
- Uses `hours_ago` (already in scope from cache freshness check at line 1017-1019)
- Sets `cache_fallback` or `stale_fallback` depending on `cache_is_fresh`
- Sets `force_refresh_fallback` when `force_refresh=True`
- Sets `cached_repricing_skipped` when `reprice_cached_positions=False`
- Records `fetch_error` string in `_provider_metadata`
- Applies `_ensure_cached_columns`, `partition_positions`, `_consolidate_provider_positions`
- Applies `_calculate_market_values` repricing when not deferred

The error string (e.g. "Provider schwab timed out after 45s") flows through:
1. `_provider_metadata[provider]["fetch_error"]` (line 1129)
2. `result._cache_metadata[provider]["error"]` (line 811-812)
3. `_build_cache_info()` → `cache_info[provider]["error"]` (line 86)
4. `generate_position_flags()` → `type: "provider_error"` flag (line 107-118)

No new flag type needed.

### Step 3.5: Wire the timeout into `refresh_provider_positions`

**File:** `services/position_service.py:2123`

`refresh_provider_positions()` (line 2101-2127) calls `_fetch_fresh_positions(provider)` directly, bypassing `_get_positions_df` and its fallback path. This is a second call site that needs the same timeout wrapper. Reachable from `mcp_tools/positions.py:61-67`, `routes/plaid.py:1600-1606`, `routes/snaptrade.py:1088-1094`.

Change:
```python
df = self._fetch_fresh_positions(provider)
```
To:
```python
df = self._fetch_fresh_with_timeout(provider)
```

**Disconnect route exception handling**: The Plaid (`routes/plaid.py:1598-1619`) and SnapTrade (`routes/snaptrade.py:1086-1106`) disconnect flows have a nested try/except structure around `refresh_provider_positions()`:

```python
try:
    position_service.refresh_provider_positions('plaid')  # or 'snaptrade'
except ValueError:
    # Inner catch: stale-position cleanup runs HERE
    remaining = list_user_tokens(...)  # or list_snaptrade_connections(...)
    if not remaining:
        position_service.delete_provider_positions(...)
except Exception as sync_error:
    # Outer catch: swallows error as non-fatal, NO cleanup
    log_error(...)
```

The stale-position cleanup (deleting positions when no connections remain) only runs inside the inner `except ValueError` block (`routes/plaid.py:1608`, `routes/snaptrade.py:1095`). The outer `except Exception` at `routes/plaid.py:1617` and `routes/snaptrade.py:1104` swallows errors without cleanup.

If `ProviderTimeoutError` subclassed `Exception` (not `ValueError`), a timeout would skip the inner `ValueError` catch, get swallowed by the outer `except Exception`, and leave stale provider positions behind after a disconnect. This is why `ProviderTimeoutError` subclasses `ValueError` (see Step 1) — it ensures the disconnect route handlers' inner catch block fires on timeout, triggering the stale-position cleanup when no connections remain.

For the MCP helper path (`mcp_tools/positions.py:61-67`), `ProviderTimeoutError` propagates to the tool error response regardless of its base class, which is the correct behavior.

### Step 4: Remove context manager from parallel executor (prevent shutdown(wait=True) blocking)

**File:** `services/position_service.py:636`

The parallel `get_all_positions` path (line 636) uses `with ThreadPoolExecutor(...) as executor:`. If a provider hangs past the per-`_get_positions_df` timeout, the thread running `_fetch_fresh_with_timeout` has its own sub-executor that abandons the stuck thread. However, the outer `_get_positions_df` call itself should now return promptly (either with fresh data or via the fallback path after timeout). The outer executor's `with` block should be fine because `_get_positions_df` no longer blocks indefinitely.

**No change needed to the outer executor.** The timeout is injected one layer down, inside `_get_positions_df` → `_fetch_fresh_with_timeout`. The outer `as_completed` loop iterates normally because each future completes (either successfully or via the fallback). The `with ThreadPoolExecutor(...)` context manager's `shutdown(wait=True)` runs after all futures have already completed.

### Step 5: Handle shared mutable state safety

**Concern:** If `_fetch_fresh_with_timeout` abandons a thread, that thread may continue running in the background and could mutate shared state.

**Analysis — PositionService layer (no race):** The abandoned thread is inside `_fetch_fresh_positions` (line 2048-2067), which only calls `provider_impl.fetch_positions()` and `self._normalize_columns()`. Neither of these writes to `self._provider_metadata` or `self._defer_cached_repricing`. The metadata writes happen in `_get_positions_df` (lines 1051, 1067, 1096, 1126-1133), which is the caller — it runs on the non-abandoned thread. The `self._save_lock` at line 1106-1111 protects DB writes. The abandoned thread never reaches the save path because `_fetch_fresh_positions` only returns the raw DataFrame — the caller (`_get_positions_df`) does the save. So there is no `PositionService` metadata or DB race.

**Analysis — provider-level side effects (acceptable):** Abandoned threads may continue executing provider code that has its own side effects:
- **SnapTrade** can rotate secrets during a 401 recovery (`providers/snaptrade_loader.py:897-913`) — the rotation uses a per-user lock and is idempotent, so a concurrent rotation from a later retry is safe.
- **IBKR** updates the probe cache state (`providers/ibkr_positions.py:104-109,123-150`) via `_mark_probe_unreachable()`, which writes to `routing._ibkr_probe_cache`. This is a monotonic timestamp cache — a stale write from an abandoned thread is harmless (it marks IBKR as unreachable, which is correct if the fetch timed out).

These provider-level side effects may run to completion in abandoned threads. This is acceptable — they are idempotent or monotonic, and do not corrupt `PositionService` state.

**Analysis — `_PROVIDER_FETCH_GATES` dict (safe):** The module-level `_PROVIDER_FETCH_GATES` dict and `_PROVIDER_FETCH_GATES_LOCK` are accessed from `_fetch_fresh_with_timeout`, which may be called from multiple threads in the parallel `get_all_positions` path and from different `PositionService` instances across concurrent requests. All reads and writes to `_PROVIDER_FETCH_GATES` are protected by `_PROVIDER_FETCH_GATES_LOCK`. The gate check, `executor.submit()`, and thread registration all happen under a single lock hold, eliminating the race where two concurrent requests could both pass the gate check before either registers. The `submit()` call is fast (just enqueues work) so the lock is held only briefly. The `executor._threads` access is read-only on a freshly-created single-thread executor owned by the current call — no contention. Because the dict is module-level and keyed by `(user_email, provider_name)` tuple, it correctly tracks abandoned threads per user per provider across all service instances within the process. This means user A's hung Schwab fetch does not block user B's Schwab fetch — only user A's subsequent Schwab requests are gated until the abandoned thread finishes.

**Gate-clearing semantics (self-cleaning via done-callback):** Rather than relying on the calling thread to clear the gate on each exit path (which leaks for abandoned-thread pairs that are never fetched again), Step 2 registers `future.add_done_callback(_clear_gate_on_done)` immediately *after* releasing the gate lock (see Step 2 for the deadlock-avoidance rationale). The callback fires whenever the future completes — promptly for normal/error returns, or much later (after OS-level TCP timeout drains the abandoned worker) for orchestrator-timeout cases. The callback runs on the worker thread for normal completions, or synchronously on the caller thread if the future is already done at registration time. It takes the lock and only deletes its own key (identity-checked against the worker thread it registered for) so it never clobbers a newer submission that has reused the same `(user, provider)` slot.

Three exit paths, all converging on the same self-cleaning mechanism:

1. **Success** — `future.result()` returns normally. The done-callback has already fired (either on the worker thread, or synchronously on the caller thread when `add_done_callback()` ran on an already-finished future); the gate entry is removed.
2. **Orchestrator timeout** — `future.result(timeout=…)` raises `TimeoutError`. Because `_wrapped_fetch_fresh_positions` converts any worker-raised `TimeoutError` / `socket.timeout` into `ProviderFetchError` *before* the future reflects it, the only way `TimeoutError` can reach this point is from `future.result(timeout=…)` itself — i.e. the orchestrator timeout. The worker thread is **still alive**, blocked inside the underlying provider network call (it cannot be interrupted from Python). Gate stays set so the next call for this `(user, provider)` pair skip-fasts to the stale-cache fallback instead of spawning a second abandoned thread. The done-callback **eventually** fires on the worker thread when the OS-level TCP timeout drains the connection (typically 75-120s), at which point the gate entry is removed automatically. **Even if no fetch for this `(user, provider)` pair ever happens again**, the entry is cleared as soon as the abandoned worker exits — so no dead entries accumulate over time.
3. **Worker exception** (any non-timeout error, OR a worker-raised `TimeoutError` / `socket.timeout` that the wrapper has converted to `ProviderFetchError`) — `future.result()` raises the original exception (or `ProviderFetchError`). Worker thread has finished; the done-callback has already fired and removed the gate entry. Step 2 simply lets the exception propagate.

The done-callback handles the previously-leaky case where Finding 2 noted gate entries could persist for `(user, provider)` pairs that were never fetched again after a timeout — the callback fires on the abandoned worker thread itself when the OS-level timeout finally returns, regardless of whether a subsequent fetch ever happens.

Net effect: the gate dict size at any moment is bounded by the number of `(user, provider)` pairs whose worker thread is currently still alive — never more, never less. No accumulation under repeated provider auth errors, network errors, or extended outages where a user disconnects and never re-fetches. No leak under any code path.

**No other changes needed.** Document the gate mechanism in code comments for future maintainers.

### Step 6: Add `import threading` and `import socket`

**File:** `services/position_service.py:49`

The existing import is:
```python
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
```

Add `threading` for the module-level gate lock and `socket` for the worker wrapper's `socket.timeout` catch:
```python
import socket
import threading
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
```

`concurrent.futures.TimeoutError` is **not** imported because Step 2 uses the builtin `TimeoutError` directly (they are the same class on Python 3.11+). Discrimination between orchestrator and worker timeouts is no longer needed at all: `_wrapped_fetch_fresh_positions` converts worker-raised `TimeoutError` / `socket.timeout` to `ProviderFetchError` BEFORE the future reflects them, so a `TimeoutError` from `future.result(timeout=…)` can ONLY mean the orchestrator timeout.

(`threading` and `socket` may already be imported — check existing imports first. `Dict` and `Tuple` from `typing` are needed for the `_PROVIDER_FETCH_GATES` type annotation — check if already imported.)

## Testing

All new tests go in `tests/services/test_position_service_provider_registry.py`, extending the existing provider-fallback test suite (tests at lines 859, 919, 953).

### Test 1: Timeout triggers fallback to stale cache
Mock `_fetch_fresh_positions` to block on a shared `threading.Event` (`block_event`). Set `_POSITION_FETCH_TIMEOUT` to 1s via monkeypatch. Mock `_get_cache_freshness` to return `hours_ago=6.0, is_fresh=False`. Mock `_load_cached_positions` to return a DataFrame. Call `_get_positions_df(provider="schwab", use_cache=True, ...)` inside a `try/finally` block that sets `block_event` in `finally`. Assert: returns cached df, `from_cache=True`, `_provider_metadata["schwab"]["stale_fallback"]=True`, `_provider_metadata["schwab"]["fetch_error"]` contains "timed out". Assert: returns promptly (< 3s wall clock).

### Test 2: Timeout triggers fallback to fresh cache
Same as Test 1 but `is_fresh=True`. Assert `_provider_metadata["schwab"]["cache_fallback"]=True` (not `stale_fallback`).

### Test 3: Timeout with force_refresh=True
Same as Test 1 but `force_refresh=True`. Assert `_provider_metadata["schwab"]["force_refresh_fallback"]=True`.

### Test 4: Timeout with use_cache=False (no fallback available)
Mock `_fetch_fresh_positions` to block on a shared `block_event`. Set `use_cache=False`. Use `try/finally` with `block_event.set()` in `finally`. Assert `ProviderTimeoutError` propagates (the existing catch at line 1113 only fires when `use_cache and hours_ago is not None`; with `use_cache=False` it re-raises).

### Test 5: Timeout with no cache data available (hours_ago=None)
Mock `_get_cache_freshness` to raise. Mock `_fetch_fresh_positions` to block on a shared `block_event`. Use `try/finally` with `block_event.set()` in `finally`. Assert `ProviderTimeoutError` propagates (since `hours_ago` is `None`, the fallback at line 1114 re-raises).

### Test 6: All providers timeout in get_all_positions
Register two providers, both blocking on a shared `block_event`. Use `try/finally` with `block_event.set()` in `finally`. Assert `get_all_positions` returns within ~2s (not 17min). Assert both providers have errors in `result._cache_metadata`.

### Test 7: One provider times out, other succeeds in get_all_positions
Register two providers. One blocks on a shared `block_event` (timeout->fallback), other returns immediately. Use `try/finally` with `block_event.set()` in `finally`. Assert both providers' data is included in the combined result. Assert the timed-out provider has `fetch_error` in metadata. Assert the successful provider has no error.

### Test 8: Env var override
Monkeypatch `services.position_service._POSITION_FETCH_TIMEOUT = 2.0`. Mock `_fetch_fresh_positions` to block on a shared `block_event` (with `block_event.wait(timeout=60)`). Use `try/finally` with `block_event.set()` in `finally`. Assert timeout fires after ~2s.

### Test 9: ProviderTimeoutError flows through existing flag pipeline
Build a `result._cache_metadata` with `{"schwab": {"error": "Provider schwab timed out after 45s", ...}}`. Call `generate_position_flags(...)` with this `cache_info`. Assert it emits a flag with `type: "provider_error"`, `provider: "schwab"`, `severity: "error"`, and message containing "timed out".

### Test 10: refresh_provider_positions raises ProviderTimeoutError on timeout
Mock `_fetch_fresh_positions` to block on a shared `block_event`. Set `_POSITION_FETCH_TIMEOUT` to 1s via monkeypatch. Call `refresh_provider_positions("snaptrade")` inside a `try/finally` that sets `block_event` in `finally`. Assert `ProviderTimeoutError` is raised. Assert it is an instance of `ValueError` (confirming the subclass relationship that the disconnect route handlers depend on). Assert wall clock < 3s. Mock `_save_positions_to_db` and assert it was NOT called (the timeout fires before the save).

### Test 11a: Gate cleared on non-timeout exception (no leak)
Set `_POSITION_FETCH_TIMEOUT` to 5s (well above the test runtime). Mock `_fetch_fresh_positions` to raise `ValueError("provider auth failed")` immediately (no blocking). Call `_get_positions_df(provider="schwab", use_cache=False, ...)` and expect the `ValueError` to propagate (or, with `use_cache=True` and a cache available, expect the existing fallback to swallow it and emit `provider_error` metadata — choose whichever path the test fixture exercises). After the call returns/raises, assert `services.position_service._PROVIDER_FETCH_GATES` does NOT contain the `(user_email, "schwab")` key (the done-callback should have cleared it). Repeat the call a second time and assert it spawns a new worker thread and reaches the mock again (proving the gate did not block it). Repeat with `OSError("network unreachable")` to confirm the same behavior for network errors. Repeat with `KeyboardInterrupt` raised inside the worker callable and assert the gate is cleared and the `KeyboardInterrupt` propagates. This test guards against the gate-leak bug where the dict would slowly accumulate dead `(user, provider)` entries during extended provider outages.

### Test 11b: Worker-raised `TimeoutError` / `socket.timeout` is converted to `ProviderFetchError`
Set `_POSITION_FETCH_TIMEOUT` to 5s. Mock `_fetch_fresh_positions` to raise `TimeoutError("read timed out")` immediately (no blocking). Call `_get_positions_df(provider="schwab", use_cache=False, ...)`. Assert: the raised exception is `ProviderFetchError` — **NOT** `ProviderTimeoutError` (since the worker raised it, not the orchestrator) and **NOT** the original `TimeoutError` (the worker wrapper converted it). Assert: `ProviderFetchError.__cause__` is the original `TimeoutError` (the wrapper used `raise ... from exc`). Assert `_PROVIDER_FETCH_GATES` does NOT contain `(user_email, "schwab")` after the call (the done-callback cleared it because the worker thread terminated normally with the exception). Repeat with `socket.timeout("connect timed out")` raised from inside the worker — assert the same behavior (`ProviderFetchError` raised, `__cause__` is the `socket.timeout`, gate cleared). This test guards against the Python 3.11+ bug where `concurrent.futures.TimeoutError IS TimeoutError`, so an exception-type-only check on `future.result()` would have wrongly classified a worker-raised timeout as the orchestrator timeout. The Step 2 worker wrapper (`_wrapped_fetch_fresh_positions`) prevents this at the source — the worker can no longer raise `TimeoutError` into the future at all.

Also assert Test 11b's other path: with `use_cache=True` and a stale cache available, the `ProviderFetchError` flows through the existing `except Exception as fetch_error:` handler at line 1113, triggers the stale-cache fallback, and surfaces in `_provider_metadata["schwab"]["fetch_error"]` as the `ProviderFetchError` message string.

### Test 11c: Done-callback clears gate when abandoned worker eventually finishes
Set `_POSITION_FETCH_TIMEOUT` to 1s. Create a `block_event = threading.Event()` and a `release_event = threading.Event()`. Mock `_fetch_fresh_positions` to call `block_event.wait(timeout=10)` then return an empty DataFrame. First call: invoke `_get_positions_df(provider="schwab", use_cache=True, ...)` — it times out after 1s, falls back to cache. Assert `_PROVIDER_FETCH_GATES` DOES contain `(user_email, "schwab")` immediately after the timeout (gate is preserved while the abandoned worker is still alive). Now call `block_event.set()` to release the abandoned worker. Wait briefly (e.g. `time.sleep(0.5)` or poll `_PROVIDER_FETCH_GATES` for up to 2s) for the worker thread to finish and the done-callback to fire. Assert `_PROVIDER_FETCH_GATES` does NOT contain `(user_email, "schwab")` after the worker has finished. **Critically: do NOT issue a second fetch in between** — the gate must be cleared by the done-callback alone, not by a subsequent fetch's gate-check overwriting it. This test guards against Finding 2 (gate leaks for `(user, provider)` pairs that are never fetched again after a timeout).

### Test 11: Per-(user, provider) gate blocks second fetch while abandoned thread is alive (cross-instance)
Set `_POSITION_FETCH_TIMEOUT` to 1s. Create a shared `block_event = threading.Event()`. Mock `_fetch_fresh_positions` to call `block_event.wait(timeout=60)`. **Use two separate `PositionService` instances with the same `user_email`** (simulating two requests creating fresh service objects for the same user, as happens in production at `routes/positions.py:385` and `services/position_snapshot_cache.py:90`). First call (instance A): invoke `_get_positions_df(provider="schwab", use_cache=True, ...)` — it times out after 1s, falls back to cache. The abandoned inner thread is still alive (blocked on `block_event.wait`). Second call (instance B, same user_email, immediately): invoke `_get_positions_df(provider="schwab", use_cache=True, ...)` on the **second** `PositionService` instance. Assert: the second call raises `ProviderTimeoutError` (or falls back to cache) with message containing "previous fetch still running" — NOT "timed out after". This confirms the module-level gate works across instances for the same user. Assert: the second call completes near-instantly (< 0.5s), confirming it skipped the fetch entirely. Assert: only ONE inner thread was spawned (not two). **Cross-user independence**: create a third `PositionService` instance with a **different** `user_email`. Invoke `_get_positions_df(provider="schwab", ...)` on this instance. Assert: it does NOT hit the gate (spawns its own thread and times out normally after 1s with "timed out after" message), confirming the gate is per-(user, provider), not per-provider. Cleanup: `block_event.set()` in `finally`. Also clear `_PROVIDER_FETCH_GATES` in `finally` to avoid test pollution. After cleanup, a subsequent call (any instance, same user) should succeed normally (gate cleared because the abandoned thread has now finished).

### Test shape notes
- **Blocking mock pattern**: Create a shared `block_event = threading.Event()` in each test. The mock `_fetch_fresh_positions` calls `block_event.wait(timeout=60)`. The test body runs inside a `try/finally` that calls `block_event.set()` in `finally`, so the abandoned worker thread unblocks promptly after the assertion completes. Without this cleanup, `shutdown(wait=False, cancel_futures=True)` does NOT actually cancel a thread that is mid-`wait()` — the thread continues for the full 60s, stalling pytest teardown. The `finally` pattern ensures zero zombie threads.
- **Module-level gate cleanup**: Tests that exercise the gate (especially Test 11) must clear `services.position_service._PROVIDER_FETCH_GATES` in `finally` to avoid polluting other tests. A pytest fixture or explicit `_PROVIDER_FETCH_GATES.clear()` in `finally` is recommended. Test 11 uses `(user_email, provider)` tuple keys — ensure both same-user and cross-user assertions clean up their respective gate entries.
- Monkeypatch `_POSITION_FETCH_TIMEOUT` at module level (`services.position_service._POSITION_FETCH_TIMEOUT = 1.0`) to keep tests fast.
- For "returns promptly" assertions, measure wall clock with `time.monotonic()` and assert `< 5s`.

## What This Plan Does NOT Do

1. **No per-provider socket timeouts added.** Some providers already have request-level timeouts (IBKR: `IBKR_TIMEOUT=10s` connect + `IBKR_REQUEST_TIMEOUT=30s` at `ibkr/config.py:47,50`; Schwab: 30s HTTP via `schwab-py` base client). SnapTrade and Plaid delegate to SDK/loader code with no explicit timeout. Adding per-provider timeouts (`signal.alarm` or `socket.setdefaulttimeout`) in threads is unsafe. The orchestrator-level timeout is the correct fix because the calling function returns promptly regardless of whether individual providers have their own timeouts, how many requests they make, or whether they enter retry loops.

2. **No new `_try_stale_cache_fallback()` helper.** The existing fallback at `position_service.py:1113-1135` handles `hours_ago`, `cache_is_fresh`, `force_refresh`, `reprice_cached_positions`, `consolidate`, `defer_cached_repricing`, and sets `cache_fallback`, `stale_fallback`, `force_refresh_fallback`, `cached_repricing_skipped`, `fetch_error`. Extracting a helper would either duplicate all this context or lose it.

3. **No new flag type.** Provider errors already flow through `cache_info[provider]["error"]` → `generate_position_flags()` → `type: "provider_error"` flag at `core/position_flags.py:107-118`. The existing flag uses `type` (not `code`). The timeout error string naturally surfaces through this path.

## Files Changed

| File | Change |
|------|--------|
| `services/position_service.py` | Add `_POSITION_FETCH_TIMEOUT` constant, `ProviderTimeoutError` (`ValueError` subclass) and `ProviderFetchError` (`Exception` subclass) classes, module-level `_PROVIDER_FETCH_GATES: Dict[Tuple[str, str], Thread]` dict (keyed by `(user_email, provider)`) + `_PROVIDER_FETCH_GATES_LOCK`, worker wrapper `_wrapped_fetch_fresh_positions()` that converts worker-raised `TimeoutError` / `socket.timeout` to `ProviderFetchError` BEFORE the future reflects them (eliminates Finding 1 race), and `_fetch_fresh_with_timeout()` method with per-(user, provider) gate. The gate's check-submit-register happens under a single `_PROVIDER_FETCH_GATES_LOCK` hold; the self-cleaning `future.add_done_callback(_clear_gate_on_done)` is registered AFTER releasing the lock to avoid the deadlock where a fast-path future fires the callback synchronously on the caller thread (Finding 2). The done-callback is identity-checked so it never clobbers a newer submission. With the worker wrapper in place, a `TimeoutError` raised from `future.result(timeout=...)` unambiguously means orchestrator timeout — no `future.done()` check needed. Replace `self._fetch_fresh_positions(provider)` with `self._fetch_fresh_with_timeout(provider)` at two call sites: line 1092 in `_get_positions_df` and line 2123 in `refresh_provider_positions`. Add `import threading` and `import socket` (for the worker wrapper's `socket.timeout` catch). |
| `tests/services/test_position_service_provider_registry.py` | 14 new tests (timeout fallback variants, env var, flag pipeline, refresh_provider_positions timeout, per-provider gate cross-instance, gate-cleared-on-non-timeout-error, worker-raised `TimeoutError` is not orchestrator timeout, done-callback clears gate after abandoned worker finishes). |

## Risks & Rollback

- **Risk**: 45s default too aggressive for IBKR on slow networks. **Mitigation**: Configurable via `POSITION_FETCH_TIMEOUT_SECONDS` env var; can raise to 120s+ without code change. Default 45s > IBKR's 30s `IBKR_REQUEST_TIMEOUT`, so IBKR should fail naturally before the orchestrator timeout fires.
- **Risk**: Abandoned threads from timed-out providers continue running in the background. **Mitigation**: `shutdown(wait=False, cancel_futures=True)` on the inner executor signals cancellation. The thread eventually terminates when the underlying TCP socket times out (OS-level, typically 75-120s). No `PositionService` metadata or DB state is at risk — all metadata writes happen in the caller. Provider-level side effects (SnapTrade secret rotation, IBKR probe cache updates) may run to completion in abandoned threads but are idempotent/monotonic (see Step 5). **Thread accumulation prevention**: The module-level per-(user, provider) fetch gate (Step 1) caps abandoned threads at 1 per user per provider. Because `PositionService` is created fresh per request, the gate must be module-level to work across instances. If a previous timed-out thread for a (user, provider) pair is still alive, subsequent fetches for that same user+provider — even from a different `PositionService` instance — skip straight to stale-cache fallback without spawning a new thread. A different user's fetch for the same provider is independent and not blocked. With 5 providers max, at most 5 × N_concurrent_users abandoned threads can exist — bounded by the number of active users, which is small for this single-tenant-primary deployment. The gate check, `executor.submit()`, and thread registration are all performed under a single `_PROVIDER_FETCH_GATES_LOCK` hold, eliminating the race where two concurrent requests could both pass the check before either registers. **Self-cleaning gate (Finding 2 fix)**: The done-callback fires on the abandoned worker thread itself when the OS-level TCP timeout finally drains the connection, removing the gate entry without requiring any subsequent fetch to overwrite it. This guarantees no dead `(user, provider)` entries accumulate even for pairs that are never fetched again after a timeout. **Worker-raised timeout disambiguation (round-11 Finding 1 fix)**: Because `concurrent.futures.TimeoutError IS TimeoutError` on Python 3.11+, a worker-raised `TimeoutError` / `socket.timeout` would be indistinguishable from the orchestrator timeout by exception type alone. An earlier draft used `future.done()` after the catch to discriminate, but that was racy: the worker could finish between the catch and the inspection, misclassifying an orchestrator timeout as a worker-raised timeout and breaking the `ProviderTimeoutError` (`ValueError` subclass) path that disconnect routes depend on. The current implementation eliminates the race at the source: `_wrapped_fetch_fresh_positions` (Step 2) catches `TimeoutError` / `socket.timeout` *inside the worker thread* and converts them to `ProviderFetchError` BEFORE returning to the future. By the time `future.result(timeout=…)` could ever raise `TimeoutError`, that exception can ONLY have come from the orchestrator — no race window. **Done-callback deadlock fix (round-11 Finding 2 fix)**: `Future.add_done_callback()` invokes the callback IMMEDIATELY (synchronously, on the calling thread) if the future is already finished. An earlier draft registered the callback under `_PROVIDER_FETCH_GATES_LOCK`; on a fast-success or fast-error path the callback would self-deadlock trying to reacquire the same lock. The fix is to register `add_done_callback` AFTER releasing the gate lock (see Step 2). The brief window between releasing the lock and registering the callback is harmless — a concurrent fetch for the same `(user, provider)` either sees the in-flight entry (and skip-fasts) or sees a freshly-cleared entry (and starts a new fetch). **CLI limitation**: In CLI/short-lived processes (e.g. `scripts/run_positions.py`), the interpreter may hang at shutdown waiting for abandoned threads to finish, because Python 3.13 `concurrent.futures.thread` executor threads are non-daemon and are joined during interpreter finalization. This is acceptable: the primary consumer is the API/MCP server where the fix works as designed. CLI consumers that hit this edge case can set `POSITION_FETCH_TIMEOUT_SECONDS` lower or add `os._exit()` in their entry point as a pragmatic workaround.
- **Risk**: Stale cache positions may have outdated prices. **Mitigation**: The existing `_calculate_market_values()` repricing pass (triggered when `_should_reprice_cached_provider` returns `True` for stale fallback providers at line 832-836) handles this. The `stale_fallback` metadata flag is consumed by the repricing decision.
- **Rollback**: Set `POSITION_FETCH_TIMEOUT_SECONDS=999999` to effectively disable the timeout. No schema changes, no data migration.

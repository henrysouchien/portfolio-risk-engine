# API Rate Limiting for FMP Client

## Context

FMP plan limit is 750 calls/min. The estimate collection script currently uses `--delay-ms` (default 100ms, ~600 calls/min) between some API calls, but has gaps:
- No delay between the two bulk year calls in `_fetch_covered_universe()`
- No centralized rate tracking — just scattered `time.sleep()` calls
- If prior API activity in the session consumed budget, the script can immediately hit 429s

The bulk calls getting rate-limited causes fallback to screener-only universe (6,662 tickers), defeating the universe optimization.

## Approach: Client-level rate limiter

Add a simple sliding-window rate limiter to `FMPClient` that enforces a max calls/min across all requests. This is the right layer because:
- All FMP calls go through `_make_request()` — one enforcement point
- Works for both the snapshot script and any other FMP usage (MCP tools, ad-hoc queries)
- Eliminates the need for manual `time.sleep()` scattered through calling code

### `_RateLimiter` class in `fmp/client.py`

```python
class _RateLimiter:
    """Simple sliding-window rate limiter."""

    def __init__(self, max_calls_per_minute: int = 700):
        if max_calls_per_minute <= 0:
            raise ValueError("max_calls_per_minute must be positive")
        self._max = max_calls_per_minute
        self._timestamps: deque[float] = deque()

    def acquire(self) -> None:
        """Block until a request slot is available."""
        now = time.monotonic()
        # Evict timestamps older than 60s
        while self._timestamps and self._timestamps[0] <= now - 60:
            self._timestamps.popleft()
        # If at capacity, sleep until the oldest timestamp expires
        if len(self._timestamps) >= self._max:
            sleep_until = self._timestamps[0] + 60
            sleep_for = sleep_until - now
            if sleep_for > 0:
                time.sleep(sleep_for)
            # Evict again after sleeping
            now = time.monotonic()
            while self._timestamps and self._timestamps[0] <= now - 60:
                self._timestamps.popleft()
        self._timestamps.append(time.monotonic())
```

- Default: **700 calls/min** (50-call buffer under the 750 limit — accounts for timing imprecision, not other consumers; this is the only process making FMP calls)
- Sliding window — tracks actual call timestamps, not fixed intervals
- Blocks (sleeps) when at capacity rather than raising an error
- Shared across all calls on the same `FMPClient` instance
- **Single-threaded**: `FMPClient` is always used single-threaded (script, MCP tools). No lock needed.
- **Failed requests still consume a slot**: The FMP API counts requests regardless of response status. Acquiring before the request is correct.
- **Interrupted sleep**: `time.sleep` raises `KeyboardInterrupt` on Ctrl-C, which naturally aborts the script. No special handling needed.

### Wire into `_make_request()`

```python
def _make_request(self, endpoint, **params):
    self._rate_limiter.acquire()  # Block if at rate limit
    # ... existing request logic ...
```

### `FMPClient.__init__` change

```python
def __init__(self, api_key=None, cache=None, timeout=30, max_calls_per_minute=700):
    ...
    self._rate_limiter = _RateLimiter(max_calls_per_minute)
```

Note: Keep all existing params (`api_key`, `cache`, `timeout`). Only add `max_calls_per_minute`.

### What this replaces

- The `--delay-ms` flag in `snapshot_estimates.py` becomes redundant for rate limiting purposes (the client handles it). Keep the flag as an optional additional courtesy delay between tickers, but the rate limiter is the safety net.
- No need to manually add delays between bulk calls or any other call sequence.

## Files to modify

| File | Change |
|---|---|
| `fmp/client.py` | Add `_RateLimiter` class, wire `acquire()` into `_make_request()`, add `max_calls_per_minute` param to `__init__` |
| `tests/fmp/test_fmp_client.py` | Test rate limiter (see test details below) |

No changes needed to `snapshot_estimates.py` — the rate limiter is transparent at the client level.

### Test details

Mock `time.monotonic` and `time.sleep` to avoid real delays. Tests should follow existing patterns in `test_fmp_client.py` (monkeypatch, no real HTTP calls).

1. **`test_rate_limiter_allows_calls_under_capacity`**: Create `_RateLimiter(max_calls_per_minute=3)`. Call `acquire()` 3 times. Assert `time.sleep` was NOT called.

2. **`test_rate_limiter_blocks_at_capacity`**: Create `_RateLimiter(max_calls_per_minute=2)`. Use a monotonic counter mock: starts at `100.0`, advances by `0.001` per call, then jumps forward by `60.0` after `time.sleep` is called (simulating the sleep completing). Call `acquire()` twice (fills window). Call `acquire()` a third time. Assert `time.sleep` was called with a value close to `60.0`. After the simulated sleep, the third acquire should succeed (oldest timestamp evicted).

3. **`test_rate_limiter_evicts_old_timestamps`**: Create `_RateLimiter(max_calls_per_minute=2)`. Call `acquire()` twice at time `T=100.0`. Advance `time.monotonic` to `T+61` (past the 60s window). Call `acquire()` again. Assert `time.sleep` was NOT called (old timestamps evicted, capacity available).

4. **`test_rate_limiter_rejects_invalid_config`**: Assert `_RateLimiter(max_calls_per_minute=0)` raises `ValueError`. Same for negative values.

5. **`test_make_request_calls_rate_limiter_acquire`**: Integration test — create a real `FMPClient`, mock `client._rate_limiter.acquire` and the HTTP layer. Call `fetch_raw(...)` for a registered endpoint. Assert `acquire` was called once. This verifies the wiring between `_make_request()` and the rate limiter.

## Verification

1. Run tests: `python3 -m pytest tests/fmp/test_fmp_client.py -v`
2. Test with collection: wipe DB, run `python3 fmp/scripts/snapshot_estimates.py --universe-limit 100 --force --no-resume` — both bulk years should succeed without 429s
3. Verify no rate limit errors in output

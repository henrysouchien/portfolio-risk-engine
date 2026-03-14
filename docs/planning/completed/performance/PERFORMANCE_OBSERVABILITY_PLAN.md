# Performance Observability Plan
**Status:** DONE — All 7 phases complete (1A-1D, 2A-2B, 3A)

**Goal**: Always-on timing data across the full request lifecycle so we can identify bottlenecks from real usage, not just ad-hoc profiling.

**Created**: 2026-03-09

## Current State

### What Exists

**Backend:**
- `@log_timing(threshold_s)` decorator — only logs when duration exceeds threshold (misses baseline data)
- `@log_operation(name)` decorator — logs start/end with duration to `app.log`
- `TimingContext` context manager in `ibkr/_logging.py` (monotonic clock, ms precision)
- `log_slow_operation()` with two tiers (1s slow, 5s very slow) → `app.log`
- Decorated functions: `analyze_portfolio` (3s), `portfolio_service.analyze_portfolio` (5s), risk orchestration (3-5s), proxy builder (1-2s), AI interpretation (8s)
- Structured logging to `logs/app.log`, `logs/errors.jsonl`, `logs/usage.jsonl`

**Frontend:**
- `FrontendLogger` with `performance.measureStart()`/`measureEnd()` + session summaries every 5min
- `APIService` wraps every fetch with `performance.now()` → logs endpoint, status, duration_ms
- `UnifiedAdapterCache` tracks hit/miss rates with per-operation timing
- `CacheWarmer` measures per-operation warming duration
- Slow render detection (>1000ms threshold)

### Gaps

1. **No FastAPI request-level middleware** — timing is function-scoped only; we can't see total request latency including routing, auth, serialization overhead
2. **Threshold-only logging hides baselines** — `@log_timing(3.0)` means we only see calls when they're slow; no distribution data for normal calls
3. **No step-level breakdown in hot path** — `analyze_portfolio()` has ~5 steps but we can't see which step dominates without manual profiling
4. **External dependency timing is invisible** — FMP API calls, DB queries, IBKR snapshots not broken out in structured logs
5. **Frontend waterfall is opaque** — individual API call durations logged but not the orchestration (parallel vs sequential, critical path)
6. **No response header for DevTools** — browser DevTools can't show server-side timing without `Server-Timing` or `X-Request-Duration-Ms` header

## Design

### Timing Log Format

All timing events write to a dedicated `logs/timing.jsonl` file. This separates performance data from operational logs, making it easy to query and aggregate.

**Schema** (one JSON object per line):
```json
{
  "ts": "2026-03-09T14:30:00Z",
  "kind": "request|step|dependency|frontend",
  "name": "POST /api/portfolio/analyze",
  "duration_ms": 1142.3,
  "status": 200,
  "details": {}
}
```

**`kind` values:**
- `request` — full HTTP request lifecycle (from middleware)
- `step` — sub-step within a function (e.g., `analyze_portfolio.build_view`)
- `dependency` — external call (FMP API, DB query, IBKR)
- `frontend` — frontend timing events forwarded to backend

### Timing Logger Setup

Add a `timing` JSON logger to `LoggingManager` alongside the existing `errors`, `usage`, and `frontend` loggers:

**File**: `app_platform/logging/core.py`

```python
# In LoggingManager.__init__():
self.timing_log_path = os.path.join(self.log_dir, "timing.jsonl")
self.timing_logger_name = f"{self.app_name}.timing_json"
self.timing_event_logger = self._create_json_logger(
    self.timing_logger_name,
    self.timing_log_path,
    rotating=True,
    max_bytes=50 * 1024 * 1024,  # 50MB — high volume (always-on request + step + dependency)
    backup_count=5,              # 300MB total max retention
)
```

Add a module-level convenience function:

```python
def log_timing_event(
    kind: str,
    name: str,
    duration_ms: float,
    *,
    status: int | None = None,
    **details: Any,
) -> None:
    """Write a structured timing event to timing.jsonl."""
    manager = LoggingManager._get_default_manager()
    assert manager is not None
    record = {
        "ts": _now_iso(),
        "kind": kind,
        "name": name,
        "duration_ms": round(duration_ms, 2),
    }
    if status is not None:
        record["status"] = status
    if details:
        record["details"] = _normalize_details(details)
    _emit_json(manager.timing_event_logger, record)
```

## Changes

### Phase 1A — FastAPI Request Timing Middleware

**File**: `app_platform/middleware/timing.py` (new)

Pure ASGI middleware (not `BaseHTTPMiddleware`) to correctly handle both normal requests and long-lived SSE/streaming responses. `BaseHTTPMiddleware` measures time-to-first-byte for streaming responses, which gives misleading metrics. Pure ASGI middleware wraps the full lifecycle.

For streaming responses (SSE `text/event-stream`, chunked transfers, binary `application/octet-stream`), the middleware skips the `X-Request-Duration-Ms` header (can't set it after streaming starts) and logs duration as the full stream lifetime with `streaming: true`. This is expected — SSE connections last minutes/hours, CSV exports stream chunked.

```python
import time
from starlette.types import ASGIApp, Receive, Scope, Send

from app_platform.logging.core import log_timing_event


class RequestTimingMiddleware:
    """Pure ASGI middleware: log every HTTP request with method, path, status, duration_ms.

    Uses raw ASGI protocol instead of BaseHTTPMiddleware to correctly handle
    both normal requests and long-lived SSE/streaming responses.

    Streaming detection: buffers http.response.start until the next
    send event. If it's http.response.body with more_body=True, the
    response is streaming — skip X-Request-Duration-Ms. If more_body=False
    (single body frame), inject the header. For ASGI extensions
    (pathsend, zerocopysend, etc.), flush buffered start without header.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status_code = 500
        is_streaming = False
        buffered_start = None  # hold http.response.start until first body frame

        async def send_wrapper(message) -> None:
            nonlocal status_code, is_streaming, buffered_start

            if message["type"] == "http.response.start":
                status_code = message.get("status", 500)
                # Buffer — don't send yet; wait for first body frame
                buffered_start = message
                return

            if buffered_start is not None:
                if message["type"] == "http.response.body":
                    more_body = message.get("more_body", False)
                    is_streaming = more_body  # multiple body frames = streaming

                    if not is_streaming:
                        # Single-frame response: inject timing header
                        duration_ms = (time.perf_counter() - start) * 1000
                        raw_headers = list(buffered_start.get("headers", []))
                        raw_headers.append(
                            (b"x-request-duration-ms", f"{duration_ms:.1f}".encode())
                        )
                        buffered_start = {**buffered_start, "headers": raw_headers}

                # Flush buffered start before ANY subsequent message
                # (body frame, pathsend, zerocopysend, early_hint, etc.)
                await send(buffered_start)
                buffered_start = None

            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            method = scope.get("method", "?")
            path = scope.get("path", "?")
            query = scope.get("query_string", b"").decode()

            log_timing_event(
                kind="request",
                name=f"{method} {path}",
                duration_ms=duration_ms,
                status=status_code,
                streaming=is_streaming,
                query=query if query else None,
            )
```

**File**: `app_platform/middleware/__init__.py`

Add `RequestTimingMiddleware` to exports and `configure_middleware()`:

```python
from .timing import RequestTimingMiddleware

def configure_middleware(app, config: MiddlewareConfig | None = None):
    # ... existing middleware ...
    # Timing middleware should be outermost (added last = wraps first)
    app.add_middleware(RequestTimingMiddleware)
    return app
```

**File**: `app.py`

Register the middleware. If using `configure_middleware()`, it's automatic. Otherwise add:

```python
from app_platform.middleware.timing import RequestTimingMiddleware
app.add_middleware(RequestTimingMiddleware)
```

**Verification**: Start server, hit any endpoint, check `logs/timing.jsonl` for a `kind: "request"` entry. Check response headers for `X-Request-Duration-Ms`.

### Phase 1B — Always-Record Mode for `@log_timing`

**File**: `app_platform/logging/decorators.py`

Add `always_record: bool = False` parameter. When True, every call writes to `timing.jsonl` regardless of threshold. The threshold still controls whether a warning goes to `app.log`.

```python
def log_timing(threshold_s: float | None = None, *, always_record: bool = False):
    """Decorator: measure function duration.

    When always_record=True, every call writes to timing.jsonl.
    Threshold controls app.log warning only.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                duration_s = time.perf_counter() - start
                duration_ms = duration_s * 1000

                # Always record to timing.jsonl if enabled
                if always_record:
                    from .core import log_timing_event
                    log_timing_event(
                        kind="step",
                        name=f"{func.__module__}.{func.__name__}",
                        duration_ms=duration_ms,
                    )

                # Warn to app.log only above threshold
                manager = get_logging_manager()
                assert manager is not None
                threshold = (
                    manager.slow_operation_threshold_s
                    if threshold_s is None
                    else threshold_s
                )
                if duration_s >= threshold:
                    log_slow_operation(
                        f"{func.__module__}.{func.__name__}",
                        duration_s,
                    )

        # ... async variant with same pattern ...
        return wrapper
    return decorator
```

**Migration**: Update key decorated functions to opt in:

```python
# core/portfolio_analysis.py
@log_timing(3.0, always_record=True)
def analyze_portfolio(...):

# services/portfolio_service.py
@log_timing(5.0, always_record=True)
async def analyze_portfolio(self, ...):
```

Only add `always_record=True` to the highest-value functions initially. Don't add it everywhere — that would create noise. Target the hot paths:
- `analyze_portfolio` (core)
- `PortfolioService.analyze_portfolio` (service)
- `build_portfolio_view` (engine)
- `compute_performance_metrics` (engine)
- `_analyze_realized_performance_single_scope` (realized perf)

### Phase 1C — Step-Level Timer in `analyze_portfolio()`

**File**: `core/portfolio_analysis.py`

Add `time.perf_counter()` around each major step and collect into a `step_timings` dict:

```python
import time

def analyze_portfolio(...) -> RiskAnalysisResult:
    step_timings = {}
    t0 = time.perf_counter()

    # ─── 1. Load Inputs ─────────────────────────────
    config, filepath = resolve_portfolio_config(portfolio)
    risk_config = resolve_risk_config(risk_limits)
    step_timings["resolve_config"] = (time.perf_counter() - t0) * 1000

    # ... standardize ...
    t1 = time.perf_counter()
    standardized_data = standardize_portfolio_input(...)
    step_timings["standardize"] = (time.perf_counter() - t1) * 1000

    # ─── 2+3. Concurrent build_view + betas ─────────
    t2 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=2) as executor:
        ...
    step_timings["build_view_and_betas"] = (time.perf_counter() - t2) * 1000

    # ─── 4. Risk Checks ────────────────────────────
    t3 = time.perf_counter()
    df_risk = evaluate_portfolio_risk_limits(...)
    df_beta = evaluate_portfolio_beta_limits(...)
    step_timings["risk_checks"] = (time.perf_counter() - t3) * 1000

    # ─── 5. Result Construction ─────────────────────
    t4 = time.perf_counter()
    result = RiskAnalysisResult.from_core_analysis(...)
    step_timings["result_construction"] = (time.perf_counter() - t4) * 1000

    step_timings["total"] = (time.perf_counter() - t0) * 1000

    # Log all steps as single structured event
    log_timing_event(
        kind="step",
        name="analyze_portfolio",
        duration_ms=step_timings["total"],
        steps=step_timings,
    )

    # Attach to metadata for API response visibility
    result.analysis_metadata["step_timings_ms"] = step_timings

    return result
```

**Output example** in `timing.jsonl`:
```json
{
  "ts": "2026-03-09T14:30:01Z",
  "kind": "step",
  "name": "analyze_portfolio",
  "duration_ms": 1142.3,
  "details": {
    "steps": {
      "resolve_config": 12.1,
      "standardize": 245.6,
      "build_view_and_betas": 823.4,
      "risk_checks": 45.2,
      "result_construction": 16.0,
      "total": 1142.3
    }
  }
}
```

### Phase 1D — External Dependency Timing

**File**: `fmp/client.py`

The FMP client is **synchronous** (uses `requests.get()`). The single HTTP dispatch point is `_make_request()` which already computes `response_time` internally. We pipe this existing timing into `timing.jsonl` rather than adding a redundant timer:

```python
def _make_request(self, endpoint: EndpointSpec, params: dict, ...):
    # ... existing code that computes response_time ...
    self._log_success(endpoint.name, response_time)

    # NEW: Also emit to timing.jsonl
    try:
        from app_platform.logging.core import log_timing_event
        log_timing_event(
            kind="dependency",
            name=f"fmp:{endpoint.name}",
            duration_ms=response_time * 1000,
            status=resp.status_code,
        )
    except Exception:
        pass  # Don't break FMP operations for logging
```

This reuses the existing `response_time` (computed from `time.perf_counter()` around the `requests.get()` call at line ~234) rather than adding another timing wrapper.

**File**: `ibkr/_logging.py`

Extend `TimingContext` to optionally emit to `timing.jsonl` on exit:

```python
class TimingContext:
    def __init__(self, name: str | None = None):
        self.name = name

    def __exit__(self, *args):
        self.elapsed_ms = (time.monotonic() - self.start) * 1000
        if self.name:
            try:
                from app_platform.logging.core import log_timing_event
                log_timing_event("dependency", self.name, self.elapsed_ms)
            except Exception:
                pass  # Don't break IBKR operations for logging
```

**DB timing**: Not in initial scope. Most DB queries are fast (<10ms). Add later if DB becomes a bottleneck.

### Phase 2A — Frontend Route-to-Render Timing

**File**: `frontend/packages/chassis/src/services/frontendLogger.ts`

Add a `routeTiming` namespace:

```typescript
routeTiming: {
    start(viewName: string): void {
        this._routeTimings.set(viewName, performance.now());
    },
    end(viewName: string): void {
        const startTime = this._routeTimings.get(viewName);
        if (!startTime) return;
        const duration = performance.now() - startTime;
        this._routeTimings.delete(viewName);
        this.performance.measureEnd(`route:${viewName}`, startTime);
        // Also log structured event
        this._logEvent('route_timing', {
            view: viewName,
            duration_ms: Math.round(duration),
        });
    },
}
```

**Integration points**: Call `frontendLogger.routeTiming.start()` on route change (router guard or layout effect). Call `.end()` when the view's primary data queries settle (React Query `isSuccess` on the critical queries).

### Phase 2B — API Waterfall Logging

**File**: `frontend/packages/chassis/src/services/APIService.ts`

Track requests relative to a page-load epoch:

```typescript
// On route change, reset epoch
private _pageLoadEpoch: number = performance.now();

resetEpoch(): void {
    this._pageLoadEpoch = performance.now();
}

// In request(), log relative timing
const relativeStart = performance.now() - this._pageLoadEpoch;
frontendLogger.network.waterfall(endpoint, relativeStart, duration);
```

This produces a timeline like:
```
[  0ms] GET /api/portfolio/positions  (320ms)
[  5ms] GET /api/portfolio/risk-score (180ms)  ← parallel
[325ms] GET /api/portfolio/analyze    (1100ms) ← sequential, waited for positions
```

### Phase 3A — Timing Summary Endpoint

**File**: `routes/debug.py` (new)

Dev-only endpoint that reads recent `timing.jsonl` and returns aggregates:

```python
@router.get("/api/debug/timing")
async def get_timing_summary(minutes: int = 5):
    """Return timing aggregates from recent timing.jsonl entries."""
    # Read last N minutes of timing.jsonl
    # Group by (kind, name)
    # Return p50, p95, p99, count per group
    # Include step breakdowns for analyze_portfolio
```

Gated by `ENVIRONMENT != "production"` or require admin auth.

## Files to Modify

| File | Change | Phase |
|------|--------|-------|
| `app_platform/logging/core.py` | Add timing logger + `log_timing_event()` | 1A |
| `app_platform/middleware/timing.py` | New: `RequestTimingMiddleware` | 1A |
| `app_platform/middleware/__init__.py` | Export + register timing middleware | 1A |
| `app.py` | Register timing middleware (if not using `configure_middleware()`) | 1A |
| `app_platform/logging/decorators.py` | Add `always_record` param to `@log_timing` | 1B |
| `core/portfolio_analysis.py` | Step-level timers + `step_timings` in metadata | 1C |
| `fmp/client.py` | Wrap `_request()` with timing | 1D |
| `ibkr/_logging.py` | Extend `TimingContext` to emit to timing.jsonl | 1D |
| `frontend/.../frontendLogger.ts` | Add `routeTiming` namespace | 2A |
| `frontend/.../APIService.ts` | Add waterfall-relative timing | 2B |
| `routes/debug.py` | New: timing summary endpoint | 3A |

## Implementation Order

1. **1A** — Request timing middleware ✅ (`d08ea1c9`)
2. **1C** — Step-level timers in `analyze_portfolio()` ✅ (`d08ea1c9`)
3. **1B** — Always-record mode for `@log_timing` ✅ (`d08ea1c9`)
4. **1D** — External dependency timing (FMP, IBKR) ✅ (`d08ea1c9`)
5. **2A** — Frontend route-to-render timing ✅
6. **2B** — Frontend API waterfall ✅
7. **3A** — Timing summary endpoint ✅ (`fec082ed`)

All phases complete.

## Verification

1. **1A**: Start server, hit any endpoint, verify `logs/timing.jsonl` has `kind: "request"` entry with correct duration. Verify `X-Request-Duration-Ms` response header in browser DevTools.
2. **1B**: Call `analyze_portfolio()`, verify `timing.jsonl` has entry even when duration < threshold. Verify `app.log` only warns when above threshold.
3. **1C**: Call `analyze_portfolio()`, verify `step_timings_ms` in API response metadata. Verify `timing.jsonl` step event with all sub-timings.
4. **1D**: Trigger FMP API call, verify `kind: "dependency"` entry in `timing.jsonl`.
5. **2A**: Navigate between views in frontend, verify route timing events in console/logger.
6. **2B**: Load a page, verify waterfall log shows relative start times.
7. **3A**: Hit `GET /api/debug/timing`, verify aggregated stats.

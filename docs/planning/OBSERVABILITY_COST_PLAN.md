# Observability & Per-User Cost Guardrails Plan

**Status**: Draft
**Created**: 2026-03-19
**Author**: AI-assisted
**Priority**: High (pre-production requirement)

---

## 1. Current State Assessment

### What exists today

**Logging infrastructure** (file-based, no DB persistence):
- `app_platform/logging/core.py` — `LoggingManager` with 4 JSONL sinks:
  - `errors.jsonl` (rotating 5MB, structured errors with severity/traceback/dedup)
  - `usage.jsonl` (append-only, operational events)
  - `frontend.jsonl` (rotating 5MB, frontend log batches)
  - `timing.jsonl` (rotating 50MB, request/dependency timing)
- `app_platform/logging/decorators.py` — `@log_errors`, `@log_timing`, `@log_operation` decorators
- `app_platform/middleware/timing.py` — `RequestTimingMiddleware` records `{method, path, duration_ms, status}` to timing.jsonl for every HTTP request
- `utils/logging.py` — Domain-specific helpers: `log_frontend_event()`, `log_rate_limit_hit()`, `log_service_health()`, `log_critical_alert()`

**Frontend logging** (`frontend/packages/app-platform/src/logging/Logger.ts`):
- `FrontendLogger` singleton with 7 category namespaces (component, adapter, state, performance, error, network, user)
- Batched POST to `/api/log-frontend` with dedup, suppression, sanitization
- Session-scoped stats (API calls, errors, cache hit rate, views visited)
- `sendBeacon` on unload for session summaries
- userId attached to every payload via `setUserId()`

**Request middleware**:
- `RequestTimingMiddleware` — writes timing events but does NOT record user_id, does NOT persist to DB
- `SlowAPI` rate limiter with `ApiKeyRegistry` + tier-based key function
- CORS, session middleware configured via `configure_middleware()`

**MCP tool error handling** (`mcp_tools/common.py`):
- `@handle_mcp_errors` — catches exceptions, classifies auth errors, returns `{status, error}`. Applied to 71 tool functions across 33 files. Does NOT record duration, user_id, or cost.
- `@require_db` — short-circuits when DB unavailable
- `@handle_http_errors` — HTTP variant with `error_type` classification

**FMP API tracking** (`fmp/client.py`):
- `_RateLimiter` — sliding-window 700 calls/minute (global, not per-user)
- Disk cache (Parquet + Zstandard) prevents redundant API calls
- `log_timing_event("fmp:{endpoint}", ...)` on each request — but no per-user attribution, no cost accounting

**Gateway proxy** (`app_platform/gateway/proxy.py` + `routes/gateway_proxy.py`):
- SSE streaming to Anthropic gateway — NO token counting, NO per-user cost tracking
- Tier gate (paid only for non-normalizer chat) but no usage metering
- Per-user stream locks prevent concurrent sessions

**Database** (`database/schema.sql`):
- 25+ tables, none for analytics, events, or cost tracking
- `workflow_actions` + `workflow_action_events` (audit trail) — closest pattern to what we need
- `users.tier` column exists (`public`, `registered`, `paid`)
- `user_sessions` table with expiry tracking

### What is missing

| Gap | Impact |
|-----|--------|
| No analytics event table | Cannot query user behavior, feature adoption, error trends |
| No per-user request logging | Cannot attribute API load, cannot detect abuse |
| No MCP tool instrumentation | No visibility into tool duration, failure rates, per-user usage |
| No error triage tools | Errors rot in JSONL files; no search, no status workflow |
| No cost ledger | FMP/Anthropic/Plaid costs are invisible; cannot enforce limits |
| No per-user rate limiting for external APIs | One user can exhaust FMP quota for everyone |
| No CloudWatch integration | No alarms, no dashboards, no alerting pipeline |
| No health dashboard | System status requires SSH + log parsing |
| Timing middleware lacks user_id | Cannot build per-user latency profiles |

### Scale context

- **93 HTTP endpoints** across 19 route files
- **71 MCP tool functions** across 33 files (all wrapped by `@handle_mcp_errors`)
- **~3,050 tests** in the test suite
- **External cost centers**: FMP (700 calls/min global cap), Anthropic (per-token), Plaid (per-connection/month)

---

## 2. Architecture Overview

```
                         ┌─────────────────────────────┐
                         │    CloudWatch / Dashboard    │
                         │  (alarms, metrics, widgets)  │
                         └──────────┬──────────────────┘
                                    │ push metrics
                                    │
┌────────────┐  POST /log  ┌───────┴────────┐  write  ┌──────────────────┐
│  Frontend   │────────────▶│ FastAPI App    │────────▶│   PostgreSQL DB  │
│  Logger     │             │                │         │                  │
└────────────┘             │ middleware:     │         │ analytics_events │
                           │ - timing+user  │         │ error_events     │
┌────────────┐  stdio      │ - cost metering│         │ cost_ledger      │
│ MCP Tools  │────────────▶│                │         │ mcp_tool_calls   │
│ (71 fns)   │             │ decorators:    │         └──────────────────┘
└────────────┘             │ - @track_cost  │
                           │ - @instrument  │
┌────────────┐  HTTP       │                │
│ FMP Client │────────────▶│ cost tracker:  │
│            │             │ - per-user FMP │
└────────────┘             │ - per-user AI  │
                           └────────────────┘
```

Key design decisions:
1. **DB-backed event tables** for queryable analytics (JSONL files remain for low-latency local logging)
2. **Async write path** — events buffered in-process, flushed in batches to avoid blocking request path
3. **Cost tracking at the provider boundary** — instrument `FMPClient._make_request()`, gateway proxy, Plaid sync
4. **Tier-based guardrails** — read user tier from `users.tier`, enforce limits in middleware/decorators
5. **MCP tool instrumentation via decorator composition** — new `@instrument_tool` wraps existing `@handle_mcp_errors`

---

## 3. Database Schema

### 3.1 `analytics_events` — General-purpose event log

```sql
CREATE TABLE IF NOT EXISTS analytics_events (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    event_type VARCHAR(100) NOT NULL,       -- 'page_view', 'feature_use', 'api_call', 'tool_call', 'user_action'
    event_name VARCHAR(255) NOT NULL,       -- 'view_portfolio', 'run_optimization', 'GET /api/positions'
    metadata JSONB,                         -- Flexible payload: {component, params, duration_ms, ...}
    session_id VARCHAR(255),                -- Frontend session or MCP session
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_analytics_events_user ON analytics_events(user_id);
CREATE INDEX idx_analytics_events_type ON analytics_events(event_type);
CREATE INDEX idx_analytics_events_name ON analytics_events(event_name);
CREATE INDEX idx_analytics_events_created ON analytics_events(created_at);
CREATE INDEX idx_analytics_events_user_type_created ON analytics_events(user_id, event_type, created_at);

-- Partition by month for retention management (optional, defer to Phase 4)
-- CREATE TABLE analytics_events_2026_03 PARTITION OF analytics_events FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');
```

### 3.2 `error_events` — Structured error capture with triage workflow

```sql
CREATE TABLE IF NOT EXISTS error_events (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    source VARCHAR(255) NOT NULL,           -- 'mcp_tools/risk.py:get_risk_analysis', 'routes/positions.py'
    error_type VARCHAR(100) NOT NULL,       -- 'infrastructure', 'business', 'auth', 'validation'
    severity VARCHAR(20) NOT NULL DEFAULT 'medium',  -- 'low', 'medium', 'high', 'critical'
    message TEXT NOT NULL,
    exception_class VARCHAR(255),           -- 'FMPRateLimitError', 'ConnectionError'
    stack_trace TEXT,
    context JSONB,                          -- {endpoint, params, user_tier, ...}

    -- Triage workflow
    status VARCHAR(20) NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'acknowledged', 'investigating', 'resolved', 'wontfix')),
    assigned_to VARCHAR(255),
    resolution_note TEXT,
    resolved_at TIMESTAMP,

    -- Dedup support
    fingerprint VARCHAR(64),                -- SHA-256 of (source, exception_class, first line of stack)
    occurrence_count INTEGER NOT NULL DEFAULT 1,
    first_seen_at TIMESTAMP NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMP NOT NULL DEFAULT NOW(),

    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_error_events_status ON error_events(status);
CREATE INDEX idx_error_events_severity ON error_events(severity);
CREATE INDEX idx_error_events_source ON error_events(source);
CREATE INDEX idx_error_events_fingerprint ON error_events(fingerprint);
CREATE INDEX idx_error_events_user ON error_events(user_id);
CREATE INDEX idx_error_events_created ON error_events(created_at);
CREATE INDEX idx_error_events_open_severity ON error_events(status, severity) WHERE status = 'open';
```

### 3.3 `mcp_tool_calls` — Tool invocation ledger

```sql
CREATE TABLE IF NOT EXISTS mcp_tool_calls (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    tool_name VARCHAR(100) NOT NULL,        -- 'get_positions', 'run_optimization'
    status VARCHAR(20) NOT NULL,            -- 'success', 'error', 'auth_required'
    duration_ms INTEGER,
    error_message TEXT,
    error_type VARCHAR(50),                 -- 'infrastructure', 'business', 'auth'
    params_summary JSONB,                   -- Redacted params: {portfolio_name, ticker_count, ...}
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_mcp_tool_calls_user ON mcp_tool_calls(user_id);
CREATE INDEX idx_mcp_tool_calls_tool ON mcp_tool_calls(tool_name);
CREATE INDEX idx_mcp_tool_calls_status ON mcp_tool_calls(status);
CREATE INDEX idx_mcp_tool_calls_created ON mcp_tool_calls(created_at);
CREATE INDEX idx_mcp_tool_calls_user_tool ON mcp_tool_calls(user_id, tool_name, created_at);
```

### 3.4 `cost_ledger` — Per-user cost attribution

```sql
CREATE TABLE IF NOT EXISTS cost_ledger (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider VARCHAR(50) NOT NULL,          -- 'fmp', 'anthropic', 'plaid', 'ibkr'
    operation VARCHAR(100) NOT NULL,        -- 'fmp:historical_price_adjusted', 'anthropic:chat', 'plaid:sync'

    -- Cost tracking
    units INTEGER NOT NULL DEFAULT 1,       -- API calls for FMP, tokens for Anthropic, connections for Plaid
    unit_type VARCHAR(30) NOT NULL,         -- 'api_call', 'input_token', 'output_token', 'connection'
    cost_microcents BIGINT NOT NULL DEFAULT 0,  -- Cost in 1/10000 of a cent (avoids float issues)

    -- Context
    metadata JSONB,                         -- {endpoint, cache_hit, model, tokens_in, tokens_out, ...}

    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_cost_ledger_user ON cost_ledger(user_id);
CREATE INDEX idx_cost_ledger_provider ON cost_ledger(provider);
CREATE INDEX idx_cost_ledger_created ON cost_ledger(created_at);
CREATE INDEX idx_cost_ledger_user_provider ON cost_ledger(user_id, provider, created_at);
-- Materialized daily rollup query will use this heavily:
CREATE INDEX idx_cost_ledger_user_day ON cost_ledger(user_id, provider, date_trunc('day', created_at));
```

### 3.5 `cost_limits` — Per-tier cost ceilings

```sql
CREATE TABLE IF NOT EXISTS cost_limits (
    id SERIAL PRIMARY KEY,
    tier VARCHAR(50) NOT NULL,              -- 'public', 'registered', 'paid', 'enterprise'
    provider VARCHAR(50) NOT NULL,          -- 'fmp', 'anthropic', 'plaid', 'global'
    period VARCHAR(20) NOT NULL,            -- 'daily', 'monthly'

    -- Limits
    max_units INTEGER,                      -- NULL = unlimited
    max_cost_microcents BIGINT,             -- NULL = unlimited

    -- Alerting
    soft_limit_pct INTEGER DEFAULT 80,      -- Warn at this percentage

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(tier, provider, period)
);

-- Default limits (seeded in migration)
-- INSERT INTO cost_limits (tier, provider, period, max_units) VALUES
--   ('public',     'fmp',       'daily',    50),
--   ('public',     'anthropic', 'daily',    0),      -- No AI for public
--   ('registered', 'fmp',       'daily',    200),
--   ('registered', 'anthropic', 'daily',    10),     -- 10 chat sessions/day
--   ('paid',       'fmp',       'daily',    2000),
--   ('paid',       'anthropic', 'daily',    100),
--   ('enterprise', 'fmp',       'daily',    NULL),   -- Unlimited
--   ('enterprise', 'anthropic', 'daily',    NULL);
```

---

## 4. Observability Implementation

### 4.1 Request Logging Middleware (enhance existing `RequestTimingMiddleware`)

The existing `RequestTimingMiddleware` in `app_platform/middleware/timing.py` already records `{method, path, duration_ms, status}` to timing.jsonl. We need to:

1. **Extract user_id** from session cookie in the middleware and include it in timing events
2. **Write to `analytics_events`** for queryable request logs (async batch insert)
3. **Preserve the existing JSONL path** for local debugging (zero regression)

```python
# app_platform/middleware/timing.py — additions
# In the finally block, after the existing log_timing_event() call:

# Extract user_id from request scope (set by auth middleware)
user_id = scope.get("state", {}).get("user_id")

# Async batch-insert to analytics_events (fire-and-forget)
_enqueue_analytics_event(
    user_id=user_id,
    event_type="api_call",
    event_name=f"{method} {path}",
    metadata={"status": status_code, "duration_ms": round(duration_ms, 1), "streaming": is_streaming},
)
```

**Event buffer**: In-process `asyncio.Queue` drained by a background task that does batch INSERTs every 5 seconds or 100 events (whichever comes first). This avoids per-request DB round trips.

File: `services/analytics_writer.py` — new module (~120 lines)
- `AnalyticsWriter` class with `enqueue()`, `_flush_loop()`, `start()`, `stop()`
- Singleton via module-level instance, started in `app.py` lifespan
- Graceful shutdown flushes remaining buffer
- Falls back to JSONL-only if DB unavailable (uses `is_db_available()`)

### 4.2 MCP Tool Instrumentation

New decorator `@instrument_tool` that wraps `@handle_mcp_errors`:

```python
# mcp_tools/common.py — new decorator

def instrument_tool(fn: Callable) -> Callable:
    """Instrument MCP tool: timing, success/failure, user attribution.

    Must be applied OUTSIDE @handle_mcp_errors:
        @instrument_tool
        @handle_mcp_errors
        def get_positions(...): ...
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs) -> dict:
        start = time.perf_counter()
        result = fn(*args, **kwargs)
        duration_ms = (time.perf_counter() - start) * 1000

        status = result.get("status", "unknown") if isinstance(result, dict) else "success"
        user_email = kwargs.get("user_email")

        _record_tool_call(
            tool_name=fn.__name__,
            status=status,
            duration_ms=duration_ms,
            user_email=user_email,
            error_message=result.get("error") if status == "error" else None,
            params_summary=_redact_params(kwargs),
        )
        return result
    return wrapper
```

**Rollout strategy**: Add `@instrument_tool` to all 71 `@handle_mcp_errors` call sites. This is a mechanical change (same pattern as the agent-format rollout). Can be done in a single batch with Codex review.

### 4.3 Error Capture Pipeline

Upgrade the existing `log_error()` in `app_platform/logging/core.py` to also write to `error_events` table:

1. **Fingerprinting**: SHA-256 of `(source, exception_class, first_line_of_stack)`. Identical fingerprints increment `occurrence_count` + update `last_seen_at` instead of creating new rows.
2. **Severity mapping**: Infrastructure errors (DB, network) = high. Auth errors = medium. Business logic = low. FMP rate limit = critical.
3. **Context enrichment**: Attach `user_id`, `user_tier`, `endpoint` from `ContextVar` (already supported via `set_log_context()`).

New module: `services/error_capture.py` (~150 lines)
- `capture_error(source, message, exc, **context)` — writes to both JSONL (existing) and DB
- Dedup logic: `SELECT id, occurrence_count FROM error_events WHERE fingerprint = %s AND status = 'open' LIMIT 1` then UPDATE or INSERT
- Async wrapper for non-blocking DB writes

### 4.4 Error Triage MCP Tools

Three new MCP tools in `mcp_tools/errors.py`:

```python
@handle_mcp_errors
@require_db
def list_errors(status="open", severity=None, limit=20, user_email=None):
    """List error events with filtering."""
    # Returns: {status, errors: [{id, source, severity, message, occurrence_count, last_seen_at}]}

@handle_mcp_errors
@require_db
def show_error(error_id, user_email=None):
    """Show full error details including stack trace and context."""
    # Returns: {status, error: {id, source, message, stack_trace, context, ...}}

@handle_mcp_errors
@require_db
def update_error_status(error_id, new_status, resolution_note=None, user_email=None):
    """Transition error status (open -> acknowledged -> resolved)."""
    # Returns: {status, error_id, old_status, new_status}
```

Register in `mcp_server.py` following the existing tool registration pattern.

### 4.5 Frontend Event Tracking

The existing `FrontendLogger` already sends batched events to `/api/log-frontend`. Enhancements:

1. **DB persistence**: `routes/frontend_logging.py` `process_individual_log()` additionally writes to `analytics_events` with `event_type='frontend'` for `category in ('user', 'performance', 'error')`. Debug/component logs stay JSONL-only (too noisy for DB).
2. **Page view tracking**: Frontend already emits `user.navigation(from, to)` events. These become `event_type='page_view'` in analytics_events.
3. **Feature usage**: Frontend `user.action()` events become `event_type='feature_use'`.
4. **Error capture**: Frontend `error` category logs create `error_events` rows with `source='frontend'`.

No frontend code changes needed — the routing logic is entirely in the backend `process_individual_log()` function.

### 4.6 CloudWatch Integration

New module: `services/cloudwatch.py` (~200 lines)

**Metrics emitted** (via `boto3` `put_metric_data`):
- `Requests/Count` — per endpoint, per status code
- `Requests/Latency` — p50, p95, p99 per endpoint
- `ToolCalls/Count` — per tool name, per status
- `ToolCalls/Latency` — p50, p95 per tool
- `Errors/Count` — per severity, per source
- `FMP/APICalls` — per user, per endpoint
- `Anthropic/Tokens` — per user, input/output
- `ActiveUsers/Count` — distinct user_ids in last 5 minutes
- `CostGuardrails/LimitHits` — per user, per provider

**Emission strategy**: Batch metrics every 60 seconds from in-process aggregator. Uses the same `AnalyticsWriter` background task pattern.

**Alarms**:
- Error rate > 5% of requests in 5 minutes → SNS alert
- p99 latency > 10s for any endpoint → SNS alert
- FMP rate limit hits > 10/hour → SNS alert
- Any user exceeds 90% of cost limit → SNS alert
- DB connection pool exhaustion → SNS critical alert

**Dashboard**: CloudWatch dashboard JSON template checked into `config/cloudwatch_dashboard.json` for reproducible deploys.

### 4.7 Health Dashboard

New REST endpoint: `GET /api/admin/health` (admin-only, behind tier check)

Response shape:
```json
{
  "status": "healthy",
  "uptime_s": 86400,
  "active_users_5m": 3,
  "db": {"status": "connected", "pool_size": 10, "pool_used": 2},
  "fmp": {"status": "ok", "calls_last_hour": 142, "rate_limit_hits": 0},
  "anthropic": {"status": "ok", "tokens_last_hour": 15420},
  "error_rate_1h": 0.02,
  "latency_p50_ms": 120,
  "latency_p95_ms": 890,
  "latency_p99_ms": 2100,
  "top_errors": [
    {"source": "fmp/client.py", "count": 3, "message": "Rate limit exceeded"}
  ]
}
```

Implementation: `routes/admin.py` — new endpoint (~80 lines). Queries `analytics_events` and `error_events` with time-bounded aggregations.

---

## 5. Cost Guardrails Implementation

### 5.1 Cost Allocation Model

| Provider | Unit | Cost per unit | Tracking point |
|----------|------|---------------|----------------|
| FMP | API call | ~$0 (plan-based, 750/min limit) | `FMPClient._make_request()` |
| FMP | API call (cache miss) | $0.001 estimated | Same, flag `cache_hit=false` |
| Anthropic | Input token | $0.003/1K (Claude Sonnet) | Gateway proxy SSE stream |
| Anthropic | Output token | $0.015/1K (Claude Sonnet) | Gateway proxy SSE stream |
| Plaid | Connection/month | $0.30-$1.50 | Plaid link/sync |
| IBKR | API call | $0 (included) | Not metered |

### 5.2 FMP Cost Tracking

Instrument `FMPClient._make_request()` in `fmp/client.py`:

```python
# After successful response, before return:
_record_fmp_cost(
    user_id=_get_current_user_id(),  # From thread-local or ContextVar
    endpoint=endpoint.name,
    cache_hit=False,  # This is inside _make_request, so always a miss
)
```

Also instrument `FMPClient.fetch()` cache-hit path:

```python
# When cache returns data without calling _make_request:
_record_fmp_cost(
    user_id=_get_current_user_id(),
    endpoint=endpoint.name,
    cache_hit=True,
    cost_microcents=0,  # Cache hits are free
)
```

**User attribution**: FMP calls originate from MCP tools and HTTP routes. Both paths must set `user_id` in a `ContextVar` before calling FMP. The `@instrument_tool` decorator and request middleware both set this context.

New: `services/cost_tracker.py` (~250 lines)
- `record_cost(user_id, provider, operation, units, unit_type, cost_microcents, metadata)`
- `check_limit(user_id, provider, period) -> (allowed: bool, current: int, limit: int, pct: float)`
- `get_user_costs(user_id, provider=None, period='daily') -> dict`
- Internal: batch writes via same `AnalyticsWriter` queue pattern

### 5.3 Anthropic Token Tracking

The gateway proxy (`app_platform/gateway/proxy.py`) streams SSE from Anthropic. Token counting requires parsing the SSE stream.

Anthropic's SSE stream includes `message_delta` events with `usage` fields:
```json
{"type": "message_delta", "usage": {"output_tokens": 42}}
```

And the final `message_stop` includes total usage:
```json
{"type": "message_stop", "message": {"usage": {"input_tokens": 1200, "output_tokens": 850}}}
```

**Implementation**: Wrap the `event_stream()` generator in `create_gateway_router()` to:
1. Tee the raw SSE bytes through a lightweight parser
2. Extract `usage` from `message_stop` events
3. After stream completes, call `record_cost(user_id, 'anthropic', 'chat', tokens, ...)`

This adds ~20 lines to the gateway proxy. The parser does NOT buffer the full response — it scans for `"message_stop"` lines only.

### 5.4 Plaid Connection Tracking

Plaid charges per active connection per month. Track at two points:
1. `routes/plaid.py` — Plaid link creation (`POST /api/plaid/create-link-token`)
2. `routes/plaid.py` — Plaid sync calls

Record: `cost_ledger(user_id, 'plaid', 'connection', 1, 'connection', cost_microcents=30_000)` (assuming ~$0.30/connection/month, one-time per link).

### 5.5 Per-Tier Cost Limits

Default limits (seeded in `cost_limits` table):

| Tier | FMP calls/day | AI chats/day | Plaid connections | Global $/month |
|------|--------------|-------------|-------------------|---------------|
| public | 50 | 0 | 0 | $0 |
| registered | 200 | 10 | 2 | $5 |
| paid | 2,000 | 100 | 10 | $50 |
| enterprise | unlimited | unlimited | unlimited | unlimited |

### 5.6 Enforcement Middleware

New middleware: `app_platform/middleware/cost_guard.py`

```python
class CostGuardMiddleware:
    """Check per-user cost limits before processing requests."""

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        user_id = scope.get("state", {}).get("user_id")

        if user_id and self._is_metered_path(path):
            provider = self._classify_provider(path)
            allowed, current, limit, pct = check_limit(user_id, provider, "daily")

            if not allowed:
                # Hard limit: 429 Too Many Requests
                response = JSONResponse(
                    {"error": "rate_limit_exceeded", "provider": provider,
                     "current": current, "limit": limit,
                     "message": f"Daily {provider} limit exceeded. Upgrade your plan for higher limits."},
                    status_code=429,
                    headers={"Retry-After": str(self._seconds_until_reset())}
                )
                await response(scope, receive, send)
                return

            if pct >= 0.80:
                # Soft limit: add warning header
                scope.setdefault("state", {})["cost_warning"] = {
                    "provider": provider, "pct": pct, "current": current, "limit": limit
                }

        await self.app(scope, receive, send)
```

**Metered paths**:
- `/api/gateway/*` → provider=anthropic
- `/api/plaid/*` → provider=plaid
- Factor intelligence endpoints → provider=fmp (heavy FMP usage)
- Stock analysis endpoints → provider=fmp

**Non-metered paths**: Static assets, auth, frontend logging, admin, health checks.

### 5.7 Soft Limit Warnings

When a user hits 80% of their limit:
1. HTTP response includes `X-Cost-Warning: {"provider": "fmp", "pct": 85, "remaining": 30}`
2. Frontend reads this header and shows a non-blocking toast notification
3. `analytics_events` records `event_type='cost_warning'`

### 5.8 Admin Cost Dashboard

New MCP tools in `mcp_tools/cost.py`:

```python
@handle_mcp_errors
@require_db
def cost_summary(user_email=None, period="daily"):
    """Per-user cost breakdown for current period."""

@handle_mcp_errors
@require_db
def cost_top_consumers(provider=None, period="daily", limit=10):
    """Top N users by cost for the given period."""

@handle_mcp_errors
@require_db
def cost_projection(user_email=None):
    """Projected monthly cost based on current daily run rate."""

@handle_mcp_errors
@require_db
def cost_limits_show(tier=None):
    """Show current cost limits for a tier."""

@handle_mcp_errors
@require_db
def cost_limits_set(tier, provider, period, max_units=None, max_cost_microcents=None):
    """Update cost limits for a tier."""
```

---

## 6. Implementation Phases

### Phase 1: Analytics Events + Request Logging (Foundation)

**Goal**: Every HTTP request and frontend event is recorded in a queryable table with user attribution.

**Scope**:
1. Create migration: `analytics_events` table
2. New module: `services/analytics_writer.py` (async batch writer)
3. Enhance `app_platform/middleware/timing.py` to extract user_id and enqueue analytics events
4. Enhance `routes/frontend_logging.py` to write user/performance/error events to `analytics_events`
5. Wire `AnalyticsWriter.start()` / `stop()` into `app.py` lifespan
6. Set `user_id` ContextVar in auth dependency for downstream use
7. Add user_id context propagation to `set_log_context()` calls

**Files changed**: ~8
- `database/migrations/YYYYMMDD_add_observability_tables.sql` (new)
- `services/analytics_writer.py` (new)
- `app_platform/middleware/timing.py` (modify)
- `routes/frontend_logging.py` (modify)
- `app.py` (modify — lifespan hooks)
- `app_platform/auth/dependencies.py` (modify — set ContextVar)
- `services/__init__.py` (modify — export)

**Tests**: ~25
- AnalyticsWriter: enqueue, flush, batch insert, DB-unavailable fallback, graceful shutdown
- Timing middleware: user_id extraction, event creation
- Frontend logging: DB write for user/error events, skip for debug

**Estimated effort**: 2 days

### Phase 2: MCP Tool Instrumentation + Error Capture

**Goal**: Every MCP tool call is recorded with duration and status. Errors are captured in a triage-ready table with dedup.

**Scope**:
1. Create migration: `error_events`, `mcp_tool_calls` tables
2. New decorator: `@instrument_tool` in `mcp_tools/common.py`
3. Apply `@instrument_tool` to all 71 `@handle_mcp_errors` call sites (mechanical rollout)
4. New module: `services/error_capture.py` (fingerprint, dedup, DB write)
5. Hook `error_capture.capture_error()` into `log_error()` in `app_platform/logging/core.py`
6. New MCP tools: `mcp_tools/errors.py` (list_errors, show_error, update_error_status)
7. Register error tools in `mcp_server.py`

**Files changed**: ~40
- `database/migrations/YYYYMMDD_add_error_and_tool_tables.sql` (new)
- `services/error_capture.py` (new)
- `mcp_tools/errors.py` (new)
- `mcp_tools/common.py` (modify — add `@instrument_tool`)
- `app_platform/logging/core.py` (modify — hook error_capture)
- `mcp_server.py` (modify — register tools)
- 33 `mcp_tools/*.py` files (add `@instrument_tool` decorator)

**Tests**: ~50
- `@instrument_tool`: timing, success recording, error recording, user attribution
- Error capture: fingerprinting, dedup (increment vs new), severity mapping
- Error triage tools: list with filters, show detail, status transitions
- Integration: tool call → error → error_events row

**Rollout approach**: Same pattern as agent-format rollout — mechanical decorator addition with Codex review. Binary PASS/FAIL per file.

**Estimated effort**: 3 days

### Phase 3: Cost Ledger + Per-User Tracking

**Goal**: Every external API call is attributed to a user with cost estimation. Usage is queryable per user/provider/period.

**Scope**:
1. Create migration: `cost_ledger`, `cost_limits` tables + seed default limits
2. New module: `services/cost_tracker.py` (record, check_limit, get_user_costs)
3. Instrument `fmp/client.py` — user_id ContextVar, record on each `_make_request()` and cache hit
4. Instrument gateway proxy — parse SSE `message_stop` for token usage, record cost
5. Instrument `routes/plaid.py` — record connection cost on link creation
6. New MCP tools: `mcp_tools/cost.py` (cost_summary, cost_top_consumers, cost_projection, cost_limits_show, cost_limits_set)
7. Register cost tools in `mcp_server.py`
8. Add user_id ContextVar propagation from MCP tool → FMP client call chain

**Files changed**: ~15
- `database/migrations/YYYYMMDD_add_cost_tables.sql` (new)
- `services/cost_tracker.py` (new)
- `mcp_tools/cost.py` (new)
- `fmp/client.py` (modify — cost recording hooks)
- `app_platform/gateway/proxy.py` (modify — SSE token parser)
- `routes/plaid.py` (modify — connection cost recording)
- `mcp_server.py` (modify — register tools)
- `mcp_tools/common.py` (modify — ContextVar for user_id propagation)

**Tests**: ~40
- Cost tracker: record, check_limit (under/at/over), daily/monthly periods
- FMP instrumentation: cost recorded on miss, zero on hit, user attribution
- Gateway token parser: extract usage from SSE bytes, handle malformed
- Plaid cost: recorded on link, idempotent
- Cost MCP tools: summary, top consumers, projection math

**Estimated effort**: 3 days

### Phase 4: Guardrails + Alerting + Dashboards

**Goal**: Cost limits enforced in real time. CloudWatch alarms fire on anomalies. Admin has visibility.

**Scope**:
1. New middleware: `app_platform/middleware/cost_guard.py` (429 enforcement + soft warning headers)
2. Frontend: Read `X-Cost-Warning` header, show toast (small UI change)
3. New module: `services/cloudwatch.py` (metric emission, alarm definitions)
4. New endpoint: `GET /api/admin/health` (system health dashboard)
5. CloudWatch dashboard template: `config/cloudwatch_dashboard.json`
6. Data retention: Add monthly partition support or cron job to archive `analytics_events` older than 90 days

**Files changed**: ~10
- `app_platform/middleware/cost_guard.py` (new)
- `app_platform/middleware/__init__.py` (modify — add to middleware chain)
- `services/cloudwatch.py` (new)
- `routes/admin.py` (modify — health endpoint)
- `config/cloudwatch_dashboard.json` (new)
- `frontend/packages/chassis/src/services/HttpClient.ts` or similar (modify — cost warning toast)
- `app.py` (modify — add CostGuardMiddleware)

**Tests**: ~30
- Cost guard: allow under limit, soft warning at 80%, hard block at 100%, non-metered paths bypass
- CloudWatch: metric batching, alarm definition validation
- Health endpoint: correct aggregation, handles empty tables
- Retention: archive job preserves recent data

**Estimated effort**: 3 days

---

## 7. Migration Plan

All migrations are additive (new tables only, no existing table modifications). Safe for zero-downtime deploys.

```
database/migrations/
  20260320_add_analytics_events.sql      # Phase 1
  20260322_add_error_tool_tables.sql     # Phase 2
  20260325_add_cost_tables.sql           # Phase 3
```

Each migration is idempotent (`CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`).

Rollback: `DROP TABLE IF EXISTS <table> CASCADE` for each new table. No existing tables are modified.

---

## 8. Testing Strategy

### Unit tests (~120 total across all phases)
- `tests/services/test_analytics_writer.py` — buffer, flush, batch insert, fallback
- `tests/services/test_error_capture.py` — fingerprint, dedup, severity
- `tests/services/test_cost_tracker.py` — record, limits, projection
- `tests/mcp_tools/test_errors.py` — list, show, status transitions
- `tests/mcp_tools/test_cost.py` — summary, top consumers, limits CRUD
- `tests/middleware/test_cost_guard.py` — allow/warn/block, path classification

### Integration tests (~25 total)
- Full request → analytics_events row (with user_id)
- MCP tool call → mcp_tool_calls row + cost_ledger row (for FMP tools)
- Gateway chat → cost_ledger row with token counts
- Error in tool → error_events row with fingerprint
- Cost limit exceeded → 429 response

### Load/stress tests (manual, Phase 4)
- Verify AnalyticsWriter handles 1000 events/sec without back-pressure on request path
- Verify cost_guard middleware adds < 1ms latency (single DB round-trip with connection pool)
- Verify JSONL logging continues when DB is down

---

## 9. Feature Flags

```python
# settings.py — new flags
OBSERVABILITY_DB_ENABLED = os.getenv("OBSERVABILITY_DB_ENABLED", "false").lower() == "true"
COST_TRACKING_ENABLED = os.getenv("COST_TRACKING_ENABLED", "false").lower() == "true"
COST_ENFORCEMENT_ENABLED = os.getenv("COST_ENFORCEMENT_ENABLED", "false").lower() == "true"
CLOUDWATCH_ENABLED = os.getenv("CLOUDWATCH_ENABLED", "false").lower() == "true"
```

Rollout order:
1. `OBSERVABILITY_DB_ENABLED=true` — start writing to analytics_events, error_events, mcp_tool_calls
2. `COST_TRACKING_ENABLED=true` — start writing to cost_ledger (read-only, no enforcement)
3. Observe for 1 week, validate data correctness and DB load
4. `COST_ENFORCEMENT_ENABLED=true` — enable 429 responses
5. `CLOUDWATCH_ENABLED=true` — start emitting metrics (requires AWS credentials)

---

## 10. Security Considerations

- **PII in analytics_events**: `metadata` may contain user-agent strings and IP addresses. Apply same retention policy as access logs (90 days).
- **Cost ledger**: Contains per-user usage patterns. Admin-only access via MCP tools (no public API).
- **Error stack traces**: May contain file paths and variable values. Error triage tools require admin tier.
- **Cost limits table**: Write access restricted to `cost_limits_set` tool (admin only).
- **ContextVar user_id**: Must be set at the outermost middleware layer and cleared after request to prevent leakage between requests in async workers.

---

## 11. Dependencies

No new PyPI packages required for Phases 1-3. All DB access uses existing `psycopg2` via `database/` module.

Phase 4 additions:
- `boto3` — already in requirements for AWS (if not, add)
- No frontend package additions (toast notification uses existing UI primitives)

---

## 12. Open Questions

1. **Retention policy**: How long to keep analytics_events? Suggest 90 days with monthly archival to S3/Parquet.
2. **Cost pricing accuracy**: FMP plan-based pricing makes per-call cost estimation approximate. Should we track calls only (not cost) until pricing is clarified?
3. **Anthropic model routing**: Gateway currently does not expose which model is used. Token costs vary by model. Do we assume a fixed model for cost estimation?
4. **Multi-tenant isolation**: Current DB has `user_id` scoping. Should cost limits be per-org instead of per-user for enterprise tier?
5. **Alerting channel**: SNS → email? Slack webhook? PagerDuty? Need to decide before Phase 4.

---

## 13. Success Criteria

| Metric | Target | How to verify |
|--------|--------|---------------|
| Request logging coverage | 100% of HTTP requests have analytics_events rows | `SELECT COUNT(*) FROM analytics_events WHERE event_type='api_call'` vs timing.jsonl line count |
| Tool instrumentation coverage | 71/71 MCP tools instrumented | Grep for `@instrument_tool` count |
| Error dedup ratio | > 80% of repeat errors deduplicated | `SELECT AVG(occurrence_count) FROM error_events WHERE occurrence_count > 1` |
| Cost attribution coverage | 100% of FMP/Anthropic calls have cost_ledger rows | Compare FMP rate limiter count vs cost_ledger count |
| Enforcement latency overhead | < 2ms p99 added by CostGuardMiddleware | Timing middleware before/after comparison |
| DB write throughput | > 500 events/sec sustained without back-pressure | Load test with AnalyticsWriter |
| Graceful degradation | System fully functional when DB is down | Kill DB, verify all endpoints still respond (JSONL-only logging) |

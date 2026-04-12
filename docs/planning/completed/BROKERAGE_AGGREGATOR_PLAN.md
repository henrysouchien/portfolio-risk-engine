# Brokerage Aggregator Architecture — Implementation Plan v4

**Status:** Implementation-ready
**Date:** 2026-04-09
**Supersedes:** v1 (APScheduler); v2 (routing/coalescing/scope); v3 (lock/schema/retry)

---

## Context

`get_positions` hangs 17+ minutes when Schwab/IBKR are offline. `get_orders` has the same hang class (651s, TODO line 1187). Root cause: user requests make live calls to external brokerages on the request path. 12 Codex review rounds on a timeout patch proved Python threads cannot be cancelled. The design brief names Celery as "the realistic implementation path" and its 6 layers map 1:1 to Celery features.

**Primary references**
- Design brief: `docs/planning/BROKERAGE_AGGREGATOR_DESIGN_BRIEF.md`
- Tabled patch: `docs/planning/POSITIONS_FETCH_TIMEOUT_PLAN.md`
- TODO: `docs/TODO.md` lines 92, 1184-1191

---

## 0. Architecture Foundation

### Brief's 6 Layers → Celery Mechanisms

| Layer | Brief requirement | Celery mechanism |
|---|---|---|
| L1 Decouple | API never calls providers; reads from store | Workers write to DB; API reads from DB. **No live-call fallback, even if Redis is down.** |
| L2 Bulkheads | Each provider isolated | Separate queues (`sync.schwab`, `sync.ibkr`, `sync.plaid`, `sync.snaptrade`, `sync.orders`). Separate worker processes for slow providers (Schwab/IBKR) vs fast (Plaid/SnapTrade). Phase 5 can split to per-provider workers. |
| L3 Circuit breakers | Stop calling dead providers | `sync_status.circuit_state` gates task enqueue; task body skips on open circuit |
| L4 Deadline propagation | `expires_at` on every job | `apply_async(expires=...)` — broker drops expired jobs before execution |
| L5 Process isolation | Real cancellation via SIGKILL | `task_time_limit=120` + `worker_max_tasks_per_child=1` → forked child per task |
| L6 Idempotency/Coalescing | No duplicate concurrent syncs | Redis distributed lock via `SETNX` keyed on `sync:{user_id}:{provider}` with TTL. Released in task `finally:` block. **Celery task_id does NOT deduplicate** (confirmed: Celery GitHub #4070). |

### Deployment Topology

```
services.yaml:
  redis               — Redis 7 (broker db 1, L2 cache db 0)
  celery_worker_slow   — -Q sync.schwab,sync.ibkr --concurrency=2 --max-tasks-per-child=1
  celery_worker_fast   — -Q sync.plaid,sync.snaptrade --concurrency=2 --max-tasks-per-child=1
  celery_worker_orders — -Q sync.orders --concurrency=2 --max-tasks-per-child=1
  celery_worker_maint  — -Q sync.maintenance --concurrency=1 --max-tasks-per-child=1
  celery_beat          — single instance scheduler
  risk_module          — existing API (unchanged)
  risk_module_frontend — existing frontend (unchanged)
```

Why slow/fast split: Schwab/IBKR have long timeouts and flaky connectivity. A hung Schwab task killed at 120s occupies a prefork child for the full duration. Isolating slow providers prevents them from starving fast providers. Phase 5 can split further to per-provider workers by changing `-Q` arguments — the queues are already separate.

### Task Routing

**`task_routes` dict-based routing does NOT support template variables.** v2's `sync.{provider}` was broken.

v3 routes via `apply_async(queue=...)` at the callsite:
```python
# In sync_runner.enqueue_sync():
sync_provider_positions.apply_async(
    kwargs={...},
    queue=f"sync.{provider}",
    task_id=unique_task_id,
    expires=deadline,
)
```
This is the standard Celery pattern — `apply_async` queue parameter takes precedence over any `task_routes` config.

### Coalescing (Redis SETNX — NOT redis-py Lock class)

One sync at a time per `(user_id, provider)`. Uses raw `SETNX` + `EXPIRE`, NOT the redis-py `Lock` class (which is token/owner-based and cannot be released from a different process without passing the token).

```python
# In sync_runner.enqueue_sync():
lock_key = f"sync_lock:{user_id}:{provider}"
lock_token = str(uuid4())  # unique per enqueue attempt
acquired = redis_client.set(lock_key, lock_token, nx=True, ex=150)  # TTL > task_time_limit
if not acquired:
    # Already running — return existing task_id for polling (if available)
    existing_task_id = redis_client.get(lock_key + ":task_id")
    return {"already_running": True, "task_id": existing_task_id}  # task_id may be None briefly
try:
    task = sync_provider_positions.apply_async(
        kwargs={..., "lock_key": lock_key, "lock_token": lock_token},
        ...
    )
    redis_client.set(lock_key + ":task_id", task.id, ex=150)
except Exception:
    # apply_async failed (broker down, serialization error, etc.)
    # Release the lock immediately so the next caller can try.
    _release_lock_if_owner(lock_key, lock_token)
    raise
```

In the **task body** `finally:` block, release uses compare-and-delete (Lua script for atomicity):
```python
# In task finally: block
if lock_key and lock_token:
    _release_lock_if_owner(lock_key, lock_token)  # Lua: if GET == token then DEL

def _release_lock_if_owner(key, token):
    script = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
    redis_client.eval(script, 1, key, token)
```
This is safe cross-process: the API process sets the lock with a token, passes the token to the worker via kwargs, and only the token-owner can release. If the worker is killed by `SIGKILL`, the lock auto-expires after 150s (TTL > `task_time_limit` of 120s).

**Edge cases:**
- **`apply_async` fails after lock**: try/except releases lock immediately (see above).
- **Broker redelivery** (`acks_late + reject_on_worker_lost`): If a worker is killed mid-task, the broker may redeliver the message. The redelivered task runs with the same `lock_token`. By then the lock has either been released by `finally:` or auto-expired via TTL. Either way, the redelivered task acquires a new lock (via the Beat fan-out or a new user request) and runs normally. This means at most one duplicate execution per `SIGKILL`, which is acceptable because `refresh_provider_positions()` is idempotent (delete-and-rewrite).
- **"Lock exists but no pollable task_id"**: Brief window between lock acquire and `task_id` publish. `wait_for_sync` handles this: if `task_id` is None, sleep 1s and retry once; if still None, return `{state: 'enqueuing'}`. Callers that can't wait get store data + `{state: 'enqueuing'}`.

### Worker Boot Signal

Use `worker_ready` (fires once per main worker process), NOT `worker_process_init` (fires per forked child, which with `max_tasks_per_child=1` means every task):
```python
from celery.signals import worker_ready

@worker_ready.connect
def on_worker_ready(**kwargs):
    reconcile_on_startup()  # expire orphaned sync_jobs rows
```

### Redis Unavailability

**When Redis is down, the API returns store data annotated with freshness. It does NOT fall back to live provider calls.** This preserves L1 (decouple) unconditionally. `sync_runner.enqueue_sync()` catches both `redis.exceptions.ConnectionError` (from SETNX lock operations) and `kombu.exceptions.OperationalError` (from Celery `apply_async`), and returns a structured error to the caller. The `wait=True` shim returns `{state: 'redis_unavailable', store_positions, provider_freshness}`. For `force_refresh=True` callers: the response includes an error flag indicating sync couldn't be enqueued, plus current store data.

### Result Backend

Redis db 1, `result_expires=86400`. Used by `wait_for_sync` polling via `AsyncResult.get(timeout=...)`.

---

## 1. Schema Migrations

### Phase 1 — `sync_status`
File: `database/migrations/20260410_add_sync_status.sql`
```sql
CREATE TABLE sync_status (
    id                    SERIAL PRIMARY KEY,
    user_id               INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider              VARCHAR(50) NOT NULL,
    status                VARCHAR(20) NOT NULL DEFAULT 'unknown',
    last_success_at       TIMESTAMP,
    last_attempt_at       TIMESTAMP,
    last_error            TEXT,
    consecutive_failures  INTEGER NOT NULL DEFAULT 0,
    circuit_state         VARCHAR(20) NOT NULL DEFAULT 'closed',
    circuit_opened_at     TIMESTAMP,
    metadata              JSONB,
    created_at            TIMESTAMP DEFAULT NOW(),
    updated_at            TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, provider)
);
CREATE INDEX idx_sync_status_circuit
    ON sync_status(circuit_state) WHERE circuit_state != 'closed';
```
Rollback: `DROP TABLE sync_status;`
Note: `pgcrypto` extension already exists (`database/migrations/20260209_add_trade_tables.sql:4`).

### Phase 4 — `sync_jobs`
File: `database/migrations/20260425_add_sync_jobs.sql`
```sql
CREATE TABLE sync_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    celery_task_id  VARCHAR(64),
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider        VARCHAR(50) NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    enqueued_at     TIMESTAMP NOT NULL DEFAULT NOW(),
    started_at      TIMESTAMP,
    completed_at    TIMESTAMP,
    expires_at      TIMESTAMP NOT NULL,
    error           TEXT,
    positions_count INTEGER,
    trigger         VARCHAR(20),
    created_at      TIMESTAMP DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_sync_jobs_active
    ON sync_jobs(user_id, provider) WHERE status IN ('pending', 'running');
CREATE INDEX idx_sync_jobs_expires
    ON sync_jobs(expires_at) WHERE status IN ('pending', 'running');
CREATE INDEX idx_sync_jobs_task_id
    ON sync_jobs(celery_task_id) WHERE celery_task_id IS NOT NULL;
```
Rollback: `DROP TABLE sync_jobs;`

---

## 2. Phase 1 — Freshness Contract (no behavior change)

**Goal:** Every position response carries per-provider `as_of`, `status`, `last_error` — wired into ALL read paths. Zero behavior change.

### New files
- `database/migrations/20260410_add_sync_status.sql` (§1)
- `services/sync_status_service.py` — CRUD over `sync_status`:
  - `get_sync_status(user_id, provider)`, `get_all_sync_status(user_id)`, `record_success(user_id, provider, positions_count)`, `record_failure(user_id, provider, error)`, `get_provider_freshness(user_id, provider) -> ProviderFreshness`, `is_circuit_open(user_id, provider)` (Phase 1 stub returns `False`)
- `services/freshness_policy.py` — SLA policy layer from the brief's Freshness Contract table:
  - `FRESHNESS_SLAS`: risk_engine=4h, trading=30s, dashboard=24h, reports=None, alerts=5m
  - `FreshnessPolicy.is_acceptable(consumer, provider_freshness) -> bool`
  - Default for unspecified consumers: always return store data, never block.
- `core/result_objects/provider_freshness.py` — `ProviderFreshness` frozen dataclass with `to_dict()`

### Modified files

**`services/position_service.py`** — wire into ALL paths (v1/v2 only wired `get_all_positions`):
- Line 466 `get_positions(provider)`: attach `result._provider_freshness` after constructing `PositionResult`
- Line 636-670 `get_all_positions()` fanout: build `provider_freshness_map` post-loop, attach to result
- Line 1114 stale-cache fallback: attach freshness

**`core/result_objects/positions.py`** (dataclass at line 16, `to_api_response()` at line 124):
- Add `_provider_freshness` field. In `to_api_response()` at line 179, add `provider_freshness` to metadata alongside `cache_by_provider`.

**`mcp_tools/positions.py`** (line 73 `_build_cache_info()`, line 349 `_build_agent_response()`):
- Surface `provider_freshness` in agent format.

**`core/position_flags.py`** (line 76 `generate_position_flags()`):
- Extend `stale_data` flag (line 411) to emit on `sync_status.status in ('degraded', 'offline')`.

### Feature flag
`FRESHNESS_CONTRACT_ENABLED=true` (default). When `false`, skip attaching `provider_freshness`.

### Tests
`tests/services/test_position_service_provider_registry.py` (extend):
- `test_get_all_positions_attaches_provider_freshness`
- `test_get_positions_single_provider_attaches_freshness` (v1/v2 missed this)
- `test_stale_cache_fallback_attaches_freshness`

`tests/mcp_tools/test_positions_agent_format.py` (extend):
- `test_agent_format_surfaces_provider_freshness`

New: `tests/services/test_freshness_policy.py`, `tests/services/test_sync_status_service.py`

### Rollback
1. `FRESHNESS_CONTRACT_ENABLED=false`
2. `git revert` — no workers to stop
3. `DROP TABLE sync_status;`

### Dependencies
None.

---

## 3. Phase 2 — Celery + Redis + Schwab Background Sync

**Goal:** Celery running. Schwab positions sync on schedule. Store is the read path behind feature flag. `wait=True` shim works for short-sell and UI refresh callers.

### Infrastructure

**`requirements.txt`**: Add `celery>=5.3.0,<6.0`. `redis>=7.3.0` already present.

**`services.yaml`**: Add `redis`, `celery_worker_slow`, `celery_worker_fast`, `celery_worker_orders`, `celery_worker_maint`, `celery_beat` (see §0 topology).

**`.env.example`**: Document `CELERY_BROKER_URL=redis://localhost:6379/1`, `CELERY_RESULT_BACKEND=redis://localhost:6379/1`, `CELERY_ENABLED=false`, `CELERY_TASK_ALWAYS_EAGER=false`, `SYNC_SCHWAB_INTERVAL_SECONDS=3600`, `SYNC_WAIT_TRADING_DEADLINE_SECONDS=30`, `SYNC_WAIT_UI_DEADLINE_SECONDS=10`.

**`Makefile`**: `make celery-worker-slow`, `make celery-worker-fast`, `make celery-worker-orders`, `make celery-worker-maint`, `make celery-beat`.

### New files

**`workers/__init__.py`**, **`workers/tasks/__init__.py`** — empty.

**`workers/celery_app.py`**:
```python
from celery import Celery
from celery.signals import worker_ready

app = Celery("risk_module", broker=CELERY_BROKER_URL, backend=CELERY_RESULT_BACKEND,
             include=["workers.tasks.positions", "workers.tasks.orders", "workers.tasks.maintenance"])

app.conf.update(
    task_time_limit=120,
    task_soft_time_limit=100,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_max_tasks_per_child=1,
    worker_prefetch_multiplier=1,
    worker_max_memory_per_child=400_000,  # ~400MB RSS
    result_expires=86400,
    # NO task_routes dict — routing done via apply_async(queue=...) at callsites
)

@worker_ready.connect
def on_worker_ready(**kwargs):
    from services.sync_jobs_service import reconcile_on_startup
    reconcile_on_startup()   # runs once per worker boot, NOT per task fork
```

**`workers/beat_schedule.py`** — registers periodic entries via `app.conf.beat_schedule`. **Every Beat entry must include `"options": {"queue": "sync.maintenance"}`** so they route to `celery_worker_maint` (since there's no `task_routes` dict — routing is explicit everywhere). Phase 2 activates Schwab only. Example entry:
```python
app.conf.beat_schedule["sync-schwab"] = {
    "task": "workers.tasks.maintenance.sync_all_users_for_provider",
    "schedule": SYNC_SCHWAB_INTERVAL_SECONDS,
    "args": ["schwab"],
    "options": {"queue": "sync.maintenance"},
}
```

**`workers/tasks/positions.py`**:

**No `autoretry_for`.** Retries are handled at the enqueue level (Beat re-fires on the next interval; `enqueue_and_wait` callers can retry explicitly). This avoids a race where `finally:` releases the lock, a new sync starts, and then the old retry fires later and overwrites newer data. With no auto-retry, the lock lifecycle is clean: one enqueue → one task execution → one lock release.

```python
@app.task(bind=True, time_limit=120, soft_time_limit=100,
          acks_late=True, reject_on_worker_lost=True)
def sync_provider_positions(self, *, user_id: int, user_email: str,
                            provider: str, job_id: str | None = None,
                            lock_key: str | None = None,
                            lock_token: str | None = None):
    if is_circuit_open(user_id, provider):
        return {"skipped": True, "reason": "circuit_open"}
    if job_id:
        mark_running(job_id, celery_task_id=self.request.id)
    try:
        service = PositionService(user_email=user_email, user_id=user_id)
        df = service.refresh_provider_positions(provider)  # reuse existing at line 2101
        count = len(df)
        record_success(user_id, provider, positions_count=count)
        if job_id:
            mark_completed(job_id, positions_count=count)
        return {"ok": True, "provider": provider, "count": count}
    except SoftTimeLimitExceeded:
        record_failure(user_id, provider, error="soft_time_limit")
        if job_id: mark_failed(job_id, error="soft_time_limit")
        raise
    except Exception as exc:
        record_failure(user_id, provider, error=str(exc)[:500])
        if job_id: mark_failed(job_id, error=str(exc)[:500])
        raise
    finally:
        if lock_key and lock_token:
            _release_lock_if_owner(lock_key, lock_token)  # Lua compare-and-delete (§0)
```
Note: `user_id` for DB ops, `user_email` for `PositionService()` constructor. `lock_key` passed from `sync_runner` to release the distributed lock in `finally:`.

**`workers/tasks/maintenance.py`**:
- `sync_all_users_for_provider(provider)` — Beat fan-out. User discovery via two sources (union):
  1. `data_sources WHERE provider=X AND status='active' AND user_deactivated=false` — primary
  2. `SELECT DISTINCT user_id FROM positions WHERE position_source=X` — fallback for Schwab/IBKR direct providers whose `data_sources` rows may not exist (they're seeded from manual refresh endpoints at `routes/onboarding.py:385/626/675`, not guaranteed)
  Joins `users` for `user_email`. Calls `sync_runner.enqueue_sync()` per user (which handles locking + queue routing). This matches the existing `_get_scoped_position_providers()` pattern at `position_service.py:936-951`.
- `sweep_stale_sync_jobs()` — Phase 4 stub.
- `retention_truncate_sync_jobs()` — Phase 5 stub.

**`workers/tasks/orders.py`** — Phase 3.5 stub.

**`services/sync_runner.py`** — caller-facing shim:
```python
def enqueue_sync(user_id, user_email, provider, *, trigger, deadline_seconds=120) -> dict:
    """Enqueue a sync job. Returns {task_id, job_id, already_running: bool}.
    Uses Redis SETNX lock for coalescing: only one sync per (user, provider) at a time.
    Routes to queue via apply_async(queue=f"sync.{provider}")."""

def wait_for_sync(task_id, *, timeout_seconds) -> dict:
    """Polls Celery AsyncResult. Returns {state, result|error}. Never raises on timeout."""

def enqueue_and_wait(user_id, user_email, provider, *, trigger, timeout_seconds) -> dict:
    """Enqueue + poll. Returns store positions + sync outcome."""
```

When Redis is unavailable: `enqueue_sync` catches BOTH `redis.exceptions.ConnectionError` (from direct SETNX lock operations) AND `kombu.exceptions.OperationalError` (from Celery `apply_async`), returns `{state: 'redis_unavailable'}`. Callers receive store data + error flag. **No live-provider fallback.** All Redis operations in `sync_runner` (lock acquire, task_id publish, lock release) are wrapped in the same try/except.

**`services/sync_jobs_service.py`** — Phase 2 stub for `mark_running`/`mark_completed`/`mark_failed` (no-ops until Phase 4 migration). Full implementation in Phase 4.

### Modified files

**`services/position_service.py`** — Schwab store-read path:
- In `_get_positions_df()` (~line 968), before live-fetch:
  ```python
  if _is_sync_enabled(provider):
      return self._load_store_positions(provider)
  ```
- `_load_store_positions(provider)`: wraps `_load_cached_positions()` (line 1595). Always returns store data. Empty DataFrame on no data (not exception). Populates `_provider_metadata` from `sync_status`.

**`services/trade_execution_service.py:3437`** `_get_force_refreshed_account_positions()`:
- When `CELERY_ENABLED`: `sync_runner.enqueue_and_wait(trigger="short_sell_verify", timeout_seconds=30)`. On non-success: raise `PreOrderVerificationError`.
- Fallback when `CELERY_ENABLED=false`: original sync fetch.

**`mcp_tools/positions.py`** — migrate `refresh_provider` direct path:
- Lines 60-70 `_refresh_and_load_positions()`: when `CELERY_ENABLED`, replace `service.refresh_provider_positions(provider)` with `sync_runner.enqueue_and_wait(trigger="mcp_refresh", timeout_seconds=SYNC_WAIT_UI_DEADLINE_SECONDS)`. Then read from store.
- Lines 553-573 `refresh_provider` parameter handling: same change. The MCP tool no longer calls providers directly.
- **Phase 2**: migrate for `schwab` only.
- **Phase 3**: expand `refresh_provider` allowed values at lines 493/555/972 to include `ibkr` (currently only `plaid|snaptrade|schwab`). IBKR is already a position provider (`position_service.py:177`) and has a dedicated refresh endpoint (`routes/onboarding.py:650`). MCP should have parity.
- Lines 458/578/584 `force_refresh=True`: `enqueue_and_wait` with `wait_for_sync=True` default.
- **This fixes Codex v2 finding: MCP `refresh_provider` path at `:60` and `:553` still called `refresh_provider_positions()` directly.**

**`app.py`** (lifespan at line 1048-1060):
- Startup: if `CELERY_ENABLED`, ping broker (2s timeout), log status. Do NOT fail startup.
- Shutdown: `celery_app.close()` before `close_pool()`.

**`routes/onboarding.py`** — refresh endpoints (NOT connect handlers — lines 616/665 are `/refresh-schwab-holdings` and `/refresh-ibkr-holdings`):
- Lines 616, 665: `sync_runner.enqueue_and_wait(trigger="on_demand", timeout_seconds=SYNC_WAIT_UI_DEADLINE_SECONDS)`.
- **First-sync-on-connect**: wired in the CONNECT handlers (separate from the refresh endpoints). Plaid/SnapTrade connect flows emit `enqueue_sync(trigger="first_sync")` on connection completion.
- Plaid/SnapTrade connect handlers: `enqueue_sync(trigger="first_sync")` after connection completes.

**`routes/plaid.py:1635`** / **`routes/snaptrade.py:1131`** — disconnect cleanup:
- NOT fire-and-forget. Use `enqueue_and_wait(trigger="disconnect_cleanup", timeout_seconds=10)`.
- **SnapTrade disconnect path**: Handler at `routes/snaptrade.py:1116` removes authorization (not secret). After last authorization, `refresh_provider_positions('snaptrade')` fetches empty holdings → `ValueError` at `providers/snaptrade_positions.py:43` / `position_service.py:2063`. Task catches `ValueError`, returns `{ok: False, reason: "empty_holdings_error"}`. `enqueue_and_wait` wraps this as `{state: "failed", reason: "empty_holdings_error", store_positions, provider_freshness}`.
- **Plaid disconnect path**: No-token path returns empty holdings gracefully (at `providers/plaid_loader.py:556`). Task returns `{ok: True, count: 0}`. `enqueue_and_wait` wraps as `{state: "success", ...}` with empty positions.
- **Purge rule (canonical — route receives `enqueue_and_wait` return shape):**
  Purge (`delete_provider_positions(provider)`) ONLY when ALL of:
  1. `enqueue_and_wait` returned `state == "failed"` with `reason == "empty_holdings_error"`, OR `state == "success"` with `count == 0`
  2. AND no remaining connections for the provider (query `data_sources`)
  Other failure states (timeout, network error, redis_unavailable) do NOT trigger purge — positions stay.
- On timeout: log warning, skip purge (positions preserved, cleaned up on next successful sync).

### Snapshot Cache (30s TTL)

The `position_snapshot_cache` (at `services/position_snapshot_cache.py`) is process-local in-memory with 30s TTL. Celery workers are separate processes — they cannot invalidate API workers' caches. **v3 does not attempt cross-process invalidation.**

Instead: accept 30s staleness. The brief's SLA table shows all consumers except "trading" tolerate >>30s. The trading path (`_get_force_refreshed_account_positions`) uses `enqueue_and_wait` which reads directly from the store after sync, bypassing the snapshot cache.

The snapshot cache is a request-dedup micro-optimization, not a data freshness mechanism. When the store-read path (`_load_store_positions`) is active, it hits the DB directly — the snapshot cache wraps the outer `get_position_result_snapshot()` route-level function, so a 30s stale snapshot simply means two route calls within 30s get the same DB snapshot. This is acceptable.

### Feature flag
`CELERY_ENABLED=false` (default master switch). `SYNC_PROVIDER_SCHWAB_VIA_CELERY=true` (Phase 2 only Schwab).

### Tests

`tests/workers/test_celery_app_config.py` (new):
- `test_time_limits`, `test_acks_late`, `test_max_tasks_per_child`, `test_worker_ready_signal_registered`

`tests/workers/test_positions_task.py` (new, `CELERY_TASK_ALWAYS_EAGER=true`):
- `test_sync_happy_path_updates_store_and_status`
- `test_sync_provider_offline_records_failure`
- `test_sync_circuit_open_skips_task`
- `test_sync_releases_lock_on_success`
- `test_sync_releases_lock_on_failure`
- `test_soft_time_limit_records_failure`
- `test_user_email_forwarded_to_service` (v1 regression)

`tests/services/test_sync_runner.py` (new):
- `test_enqueue_acquires_redis_lock`
- `test_enqueue_returns_existing_when_locked`
- `test_enqueue_and_wait_success_within_deadline`
- `test_enqueue_and_wait_timeout_returns_pending`
- `test_redis_unavailable_returns_structured_error`

`tests/mcp_tools/test_positions_agent_format.py` (extend):
- `test_refresh_provider_uses_sync_runner_when_celery_enabled`
- `test_refresh_provider_falls_back_when_celery_disabled`

`tests/routes/test_trade_execution_short_sell_wait.py` (new):
- `test_short_sell_uses_wait_shim`, `test_short_sell_falls_back`, `test_short_sell_raises_on_timeout`

`tests/routes/test_disconnect_cleanup.py` (new — 5 tests covering the canonical purge rule):
- `test_snaptrade_disconnect_last_auth_purges` — `enqueue_and_wait` returns `{state: "failed", reason: "empty_holdings_error"}` + no remaining connections → `delete_provider_positions('snaptrade')`
- `test_plaid_disconnect_last_token_purges` — `enqueue_and_wait` returns `{state: "success", count: 0}` + no remaining connections → purge
- `test_disconnect_preserves_when_connections_remain` — sync succeeds but other connections exist → no purge
- `test_disconnect_does_not_purge_on_network_error` — `{state: "failed", reason: "connection_error"}` + no remaining connections → positions preserved (pins the reason gate)
- `test_disconnect_does_not_purge_on_timeout` — `{state: "pending"}` → positions preserved

Integration (`REDIS_TESTS=1`): `tests/integration/test_celery_end_to_end.py`

### Rollback
1. `CELERY_ENABLED=false` → all callers fall back to original sync paths immediately.
2. Stop Beat, stop all Celery workers via `services-mcp`.
3. Restart API workers to clear snapshot caches (or wait 30s for TTL expiry).
4. `git revert` if reverting code. Schema stays (additive).

### Dependencies
Phase 1 (`sync_status_service` must exist).

---

## 4. Phase 3 — Migrate Remaining Position Providers

**Goal:** IBKR, Plaid, SnapTrade on Celery. Webhooks enqueue syncs. All `force_refresh=True` callers transitioned.

### Modified files

**`workers/beat_schedule.py`** — activate `sync_all_users_for_provider("ibkr"|"plaid"|"snaptrade")`.

**`routes/plaid.py`**:
- Line 1070 `/plaid/holdings/refresh` → `enqueue_and_wait(trigger="on_demand", timeout_seconds=SYNC_WAIT_UI_DEADLINE_SECONDS)`.
- Line 1347 `plaid_webhook()` + helper at line 382: after existing `_set_plaid_pending_updates_for_item()`, add `enqueue_sync(trigger="webhook")`. Fire-and-forget. Keep `pending_updates` flag write.

**`routes/snaptrade.py`**:
- Line 996 `/api/snaptrade/holdings/refresh` → `enqueue_and_wait`.
- Line 1273 `webhook_handler()` + helper at line 369: after existing pending-updates flag, add `enqueue_sync(trigger="webhook")`.

**`mcp_tools/positions.py`** — new MCP tool: `wait_for_sync(job_id, timeout_seconds=30)` in `mcp_tools/sync.py`.

**`services/position_service.py`** — `_is_sync_enabled()` extends to IBKR/Plaid/SnapTrade. ThreadPoolExecutor fanout at line 636-670 stays as fallback for `CELERY_ENABLED=false`.

### Feature flags
Per-provider: `SYNC_PROVIDER_IBKR_VIA_CELERY`, `SYNC_PROVIDER_PLAID_VIA_CELERY`, `SYNC_PROVIDER_SNAPTRADE_VIA_CELERY`.

### Tests
Parameterize Phase 2 tests over `[schwab, ibkr, plaid, snaptrade]`.

`tests/routes/test_plaid_refresh_async.py` (new):
- `test_refresh_enqueues_and_waits`, `test_webhook_enqueues_sync`

`tests/routes/test_snaptrade_refresh_async.py` (new): symmetric.

`tests/services/test_position_service_provider_registry.py` (extend):
- `test_all_providers_migrated_reads_from_store`
- `test_falls_back_to_thread_pool_when_celery_disabled`

### Rollback
Per-provider: `SYNC_PROVIDER_{X}_VIA_CELERY=false` + restart Beat. Full: Phase 2 rollback.

### Dependencies
Phase 2.

---

## 5. Phase 3.5 — `get_orders` via Celery

**Goal:** `get_orders` hang fixed. Full order history synced to `trade_orders` table. Store-backed reads with freshness. Trading SLA (30s) enforced via `wait=True` shim.

### Why this is harder than positions (v2 got it wrong)

v2 proposed wrapping `reconcile_open_orders()`, but Codex caught: `reconcile_open_orders()` only handles ACTIVE orders. Today's `get_orders()` calls `adapter.get_orders(state="all")` which returns **all statuses** (open + filled + cancelled). The flow at `trade_execution_service.py:2169-2275`:
1. Line 2185: calls `adapter.get_orders()` → gets remote orders
2. Line 2190: `_upsert_remote_order_statuses()` — **UPDATEs only**, does NOT INSERT new rows
3. Lines 2244-2258: remote orders not in `trade_orders` are appended to the **in-memory response** but never persisted

So `trade_orders` only contains orders that were originally placed via `execute_trade()`. Remote-only orders (placed outside the UI) exist in the live response but not in the store.

### The sync task must INSERT new remote orders

**`workers/tasks/orders.py`**:

No `autoretry_for` (same rationale as positions — avoids lock/overwrite race):
```python
@app.task(bind=True, time_limit=60, soft_time_limit=45,
          acks_late=True, reject_on_worker_lost=True)
def sync_user_orders(self, *, user_id: int, user_email: str,
                     account_id: str | None = None,
                     lock_key: str | None = None, lock_token: str | None = None):
    """Full order sync: fetch ALL remote orders, UPDATE existing, INSERT new."""
    try:
        service = TradeExecutionService(user_email=user_email, user_id=user_id)
        for account in resolved_accounts:
            remote_orders = adapter.get_orders(account_id, state="all", days=365)
            # Step 1: Update existing local orders (existing behavior)
            service._upsert_remote_order_statuses(account_id, remote_orders, provider)
            # Step 2: INSERT new remote orders not in trade_orders (NEW)
            service._insert_new_remote_orders(account_id, remote_orders, provider, user_id)
        record_success(user_id, f"orders:{provider}")
        return {"ok": True, "count": total_synced}
    except SoftTimeLimitExceeded:
        record_failure(user_id, f"orders:{provider}", error="soft_time_limit")
        raise
    except Exception as exc:
        record_failure(user_id, f"orders:{provider}", error=str(exc)[:500])
        raise
    finally:
        if lock_key and lock_token:
            _release_lock_if_owner(lock_key, lock_token)
```

### Schema migration for Phase 3.5

**`trade_orders` has NO unique constraint on `brokerage_order_id`** (only `preview_id` is unique). Add one:

File: `database/migrations/20260415_add_trade_orders_brokerage_id_unique.sql`
```sql
-- Add partial unique index for ON CONFLICT upsert during remote order sync.
-- NOT CONCURRENTLY — this repo's migration runner wraps each file in a transaction
-- (scripts/run_migrations.py:29, app_platform/db/migration.py:25), and PostgreSQL
-- rejects CONCURRENTLY inside transactions. For a table this size, a regular
-- CREATE UNIQUE INDEX is fine (brief lock during build).
CREATE UNIQUE INDEX IF NOT EXISTS idx_trade_orders_brokerage_dedup
    ON trade_orders(user_id, account_id, brokerage_order_id)
    WHERE brokerage_order_id IS NOT NULL;
```

**New helper on `TradeExecutionService`**: `_insert_new_remote_orders(account_id, remote_orders, provider, user_id)`:
- For each remote order NOT in local `trade_orders` (check by `brokerage_order_id` or `perm_id`):
  - Build insert row matching the **actual DB insert shape** at `trade_execution_service.py:1091` (includes `user_id`, `account_id`, `ticker`, `side`, `quantity`, `order_type`, `time_in_force`, `brokerage_name`, `brokerage_order_id`, `order_status`, `brokerage_response` JSONB)
  - **NOT** `_map_remote_order_row()` (which is an API-response mapper, not DB insert shape)
  - Upsert via: `INSERT ... ON CONFLICT (user_id, account_id, brokerage_order_id) WHERE brokerage_order_id IS NOT NULL DO UPDATE SET order_status=EXCLUDED.order_status, filled_quantity=EXCLUDED.filled_quantity, ...`
    Note: `ON CONFLICT` references the index expression columns directly (not `ON CONSTRAINT` — PostgreSQL partial unique indexes are not named constraints addressable that way).
  - Remote orders missing required fields (`side`, `order_type`, `time_in_force`) get defaults: `side` from quantity sign, `order_type='Market'`, `time_in_force='Day'`

After sync: `trade_orders` contains ALL orders (placed via UI + remote-only). `get_orders()` can now read entirely from `trade_orders`.

### Modified files

**`services/trade_execution_service.py`**:
- New `_insert_new_remote_orders()` helper.
- Line 2110-2328 `get_orders()`: when `ORDERS_VIA_CELERY`, read from `trade_orders` + annotate with `get_orders_freshness()`. No `adapter.get_orders()` call. For trading consumer (short-sell): `enqueue_and_wait` with 30s deadline first.
- Line 2279 `_get_orders_all_accounts()` sequential loop: when `ORDERS_VIA_CELERY`, read from store. When `ORDERS_VIA_CELERY=false`, original behavior.

**`services/order_watcher.py`**:
- When `ORDERS_VIA_CELERY=true`, `start()` becomes no-op. Beat owns scheduling.
- `poll_once()` stays for backward compat/tests.

**`workers/tasks/maintenance.py`** — add `sync_all_users_for_orders()` Beat entry.

**`workers/beat_schedule.py`** — add orders Beat entry at 300s interval.

**`routes/trading.py:198-229`** — when `ORDERS_VIA_CELERY`, read from store.

**`mcp_tools/trading.py:76-117`** — read from store.

**`mcp_server.py:2882-2886`** — `OrderWatcher` startup location (NOT `app.py`): guard with `if not ORDERS_VIA_CELERY` so Beat owns scheduling when Celery is active.

### Schema
None. `trade_orders` already exists with the right columns. New remote orders fit the existing schema. Freshness uses `sync_status` with composite key `orders:{provider}`.

### Feature flag
`ORDERS_VIA_CELERY=false` (default through burn-in).

### Tests

`tests/workers/test_orders_task.py` (new):
- `test_sync_inserts_new_remote_orders`
- `test_sync_updates_existing_orders`
- `test_sync_does_not_duplicate_on_conflict`
- `test_get_orders_store_backed_with_freshness`
- `test_short_sell_orders_uses_30s_wait_shim`

`tests/services/test_order_watcher_migration.py` (new):
- `test_order_watcher_noop_when_celery_enabled`
- `test_order_watcher_runs_when_celery_disabled`

`tests/services/test_insert_new_remote_orders.py` (new):
- `test_inserts_orphan_orders_not_in_trade_orders`
- `test_skips_existing_by_brokerage_order_id`
- `test_skips_existing_by_perm_id`
- `test_on_conflict_do_nothing_safety`

### Rollback
1. `ORDERS_VIA_CELERY=false` → `order_watcher.start()` resumes, routes use original live-call path.
2. Remove orders Beat entry, restart Beat. Stop `celery_worker_orders`.
3. No schema rollback (new rows in `trade_orders` are valid data, not harmful).

### Dependencies
Phase 2. Sequential after Phase 3 recommended (same bug class).

---

## 6. Phase 4 — Async Refresh UX + `sync_jobs` Table

**Goal:** `sync_jobs` table. Frontend async refresh with polling. MCP `wait_for_sync` tool. Restart recovery + DB-level coalescing.

### Schema
Migration `database/migrations/20260425_add_sync_jobs.sql` (§1).

### New files

**`services/sync_jobs_service.py`** (full, replaces Phase 2 stubs):
- `create_job(user_id, provider, trigger, deadline_seconds) -> UUID`:
  - Two-step (NOT `RETURNING id` on conflict — that returns empty):
    1. `INSERT ... ON CONFLICT (user_id, provider) WHERE status IN ('pending','running') DO NOTHING`
    2. If affected_rows == 0: `SELECT id FROM sync_jobs WHERE user_id=? AND provider=? AND status IN ('pending','running')`
  - Returns existing job_id on conflict (coalescing). Returns new job_id on insert.
- `mark_running(job_id, celery_task_id)`, `mark_completed(job_id, positions_count)`, `mark_failed(job_id, error)`, `mark_expired(job_id)`, `get_job(job_id)`
- `reconcile_on_startup()`: called from `worker_ready` signal. Marks `pending`/`running` rows with `expires_at < NOW()` as `expired`.
- No older-overwriting-newer guard needed — Redis SETNX lock (§0) serializes syncs per (user, provider). At most one task writes at a time.

**`routes/sync_jobs.py`** — REST:
- `POST /api/sync/{provider}/refresh` → 202 + `{job_id, status: 'pending'}`
- `GET /api/sync/jobs/{job_id}` → `{status, positions_count, error, as_of}`
- `GET /api/sync/status` → all providers for current user

**`frontend/packages/chassis/src/services/SyncService.ts`** — client for sync endpoints.

**`frontend/packages/chassis/src/hooks/useSyncJob.ts`** — React hook polling at 1s with exponential backoff.

**`mcp_tools/sync.py`** — MCP `wait_for_sync` tool.

### Modified files

**`workers/tasks/maintenance.py`** — activate `sweep_stale_sync_jobs()` at 60s interval.

**`services/sync_runner.py`** — `enqueue_sync` now calls `create_job` before `apply_async`. On DB conflict → returns existing job_id.

**Routes** (`plaid.py:1070`, `snaptrade.py:996`, `onboarding.py:616,665`): return 202 + `job_id` on timeout.

**Frontend** — ALL four refresh callers must handle 202 + job_id:
- `frontend/packages/chassis/src/services/PlaidService.ts:220` (`refreshPlaidHoldings`)
- `frontend/packages/chassis/src/services/SnapTradeService.ts:200` (`refreshHoldings`)
- `frontend/packages/chassis/src/services/APIService.ts:944` (`refreshSchwabHoldings`)
- `frontend/packages/chassis/src/services/APIService.ts:955` (`refreshIBKRHoldings`)
On 202 → `useSyncJob` polling → re-fetch on completion.

### Feature flag
`ASYNC_REFRESH_UX_ENABLED=false`. When `false`, routes return 200 + store (Phase 2 behavior).

### Tests

`tests/services/test_sync_jobs_service.py` (new):
- `test_create_job_idempotent_while_active`
- `test_create_job_returns_existing_on_conflict`
- `test_create_job_allows_new_after_completion`
- `test_reconcile_on_startup_expires_orphaned_jobs`

`tests/routes/test_sync_jobs_routes.py` (new): REST endpoints.

`tests/integration/test_multi_worker_coalescing.py` (new, `REDIS_TESTS=1`):
- Two simultaneous enqueues → one task runs → same job_id returned to both.

`tests/frontend/useSyncJob.test.ts` (new, Jest): polling + terminal states.

### Rollback
1. `ASYNC_REFRESH_UX_ENABLED=false` — routes return 200 (Phase 2 behavior).
2. Frontend tolerates 200 without job_id.
3. Stop `sweep_stale_sync_jobs` Beat entry.
4. `DROP TABLE sync_jobs;`

### Dependencies
Phase 2. Independent from Phase 3/3.5.

---

## 7. Phase 5 — Hardening + Dead Code Removal

**Goal:** Circuit breakers close the hang at the system level. Observability. Retention. Legacy code deleted.

### New files

**`services/circuit_breaker.py`** — state machine over `sync_status.circuit_state`:
- CLOSED → OPEN: `consecutive_failures >= 5`
- OPEN → HALF_OPEN: after 300s
- HALF_OPEN → CLOSED: canary success. → OPEN: canary failure.
- Canary serialization: Redis `SETNX` lock `circuit_canary:{user_id}:{provider}` with TTL.
- `is_circuit_open()` (Phase 2 stub becomes real)

**`workers/metrics.py`** — structured log events per task. Optional Prometheus.

### Modified files

**`workers/tasks/positions.py`** + `orders.py` — real circuit breaker checks.

**`workers/tasks/maintenance.py`** — activate `retention_truncate_sync_jobs()` (30-day retention, 86400s interval).

**`services/position_service.py`** — DELETE ThreadPoolExecutor fanout at lines 636-670. Replace with store-only read loop. Delete `_fetch_fresh_positions` inline call paths. Keep `refresh_provider_positions` (Celery tasks still use it).

**`data_sources.last_sync_at`** — populate on every successful sync. Closes TODO F17.

### Feature flag
`CIRCUIT_BREAKER_ENABLED=true`. Per-provider disable: `CIRCUIT_BREAKER_DISABLED_PROVIDERS=""`.

### Phase 5 scaling option
Split `celery_worker_slow` into separate `celery_worker_schwab` + `celery_worker_ibkr` for full per-provider bulkheads. Change only the `-Q` argument — no code changes.

### Tests
`tests/services/test_circuit_breaker.py`: state transitions, canary serialization, disable flag.
`tests/workers/test_retention.py`: 30-day truncation.
`tests/services/test_position_service_provider_registry.py`: verify thread fanout removed.

### Rollback
1. `CIRCUIT_BREAKER_ENABLED=false`.
2. Legacy code deletion requires `git revert`. Gate on 2+ weeks stability.

### Dependencies
Phases 2-4 stable in prod.

---

## 8. `wait=True` Transition Contract

| Caller | Phase | Consumer | Deadline | On timeout |
|---|---|---|---|---|
| `trade_execution_service.py:3437` short-sell | 2 | trading | 30s | raise `PreOrderVerificationError` |
| `routes/onboarding.py:616` Schwab refresh | 2 | dashboard | 10s | 200 + stale (Ph 2) → 202 + job_id (Ph 4) |
| `routes/onboarding.py:665` IBKR refresh | 3 | dashboard | 10s | same |
| `routes/plaid.py:1070` Plaid refresh | 3 | dashboard | 10s | same |
| `routes/snaptrade.py:996` SnapTrade refresh | 3 | dashboard | 10s | same |
| `mcp_tools/positions.py:60` `_refresh_and_load_positions` | 2 | dashboard | 10s | store + error flag |
| `mcp_tools/positions.py:553` `refresh_provider` param | 2 | dashboard | 10s | store + error flag |
| `mcp_tools/positions.py:458/578/584` `force_refresh=True` | 3 | dashboard | 10s | store + job_id |
| `routes/plaid.py:1635` disconnect cleanup | 2 | N/A | 10s | skip purge check |
| `routes/snaptrade.py:1131` disconnect cleanup | 2 | N/A | 10s | skip purge check |

**Shim semantics (`sync_runner.enqueue_and_wait`)**:
1. Acquire Redis lock via `SETNX`. If already locked → skip enqueue, poll existing task.
2. `apply_async(queue=f"sync.{provider}", expires=now+deadline*0.9, kwargs={..., lock_key=..., lock_token=...})`
3. `AsyncResult(task_id).get(timeout=deadline_seconds, propagate=False)`
4. On success (`{ok: True, ...}`): read store, annotate with `provider_freshness`, return `{state: 'success', ...}`.
5. On terminal failure (`{ok: False, reason: "empty_holdings_error"|"..."}` — non-exception task return): return `{state: 'failed', reason: ..., store_positions, provider_freshness}`. The route decides whether to proceed (disconnect purge check) or error (short-sell).
6. On timeout: return `{state: 'pending', store_positions, provider_freshness}`. **Never raises on timeout** (except short-sell path which raises explicitly).
6. On task failure: return `{state: 'failed', error, store_positions, provider_freshness}`.
7. On Redis unavailable: return `{state: 'redis_unavailable', store_positions, provider_freshness}`. **No live-provider fallback.**

---

## 9. Codex v2 Findings Resolution

| v2 finding | v3 fix |
|---|---|
| Queue routing broken (`sync.{provider}` template) | Removed `task_routes` dict. Routing via `apply_async(queue=...)` at callsites. |
| Maintenance queue has no consumer | Added `celery_worker_maint` with `-Q sync.maintenance`. |
| Snapshot cache process-local, can't invalidate from worker | Accept 30s TTL staleness. Brief SLAs are >>30s. Trading bypasses cache via `enqueue_and_wait`. |
| Disconnect cleanup drops last-connection purge semantics | Changed to `enqueue_and_wait` (not fire-and-forget). Route runs purge check after sync completes. |
| Phase 3.5: `reconcile_open_orders` only handles open orders | Redesigned: sync task calls `adapter.get_orders(state="all")` + new `_insert_new_remote_orders()` for full history. |
| `trade_orders` not a full store (missing orphan orders) | Migration adds unique index on `(user_id, account_id, brokerage_order_id)`. Sync task upserts via `ON CONFLICT`. Insert shape matches actual DB schema at `trade_execution_service.py:1091`, NOT `_map_remote_order_row()` (API mapper). |
| Celery task_id doesn't deduplicate | Redis `SETNX` distributed lock per `(user_id, provider)`. |
| `create_job ON CONFLICT DO NOTHING RETURNING id` returns empty | Two-step: INSERT then SELECT on conflict. |
| Older-overwriting-newer guard runs after destructive write | Removed — Redis lock serializes syncs per (user, provider). No concurrent races. |
| Redis-down fallback to live sync violates L1 | Removed. Redis down → return store + error flag. No live-provider calls ever. |
| One shared worker for all providers (weak bulkheads) | Split: `celery_worker_slow` (Schwab/IBKR) + `celery_worker_fast` (Plaid/SnapTrade). Phase 5 can split further. |
| MCP `refresh_provider` at `:60`/`:553` still live-calls | Migrated through `sync_runner.enqueue_and_wait`. |
| Frontend paths wrong (`frontend/src/` vs `frontend/packages/chassis/src/`) | Fixed: `frontend/packages/chassis/src/services/PlaidService.ts:220`, `SnapTradeService.ts:200`. |
| Redis KEYS rollback not real | Removed from all rollback procedures. |
| `worker_process_init` fires per task with `max_tasks_per_child=1` | Changed to `worker_ready` signal (fires once per main worker process). |
| **v3 findings** | |
| redis-py Lock class can't release cross-process without token | Replaced with raw `SETNX`+`EXPIRE` + Lua compare-and-delete. Token passed in task kwargs. |
| `autoretry_for` releases lock before retry → overwrite race | Removed `autoretry_for`. Retries at enqueue level (Beat re-fires). Lock lifecycle clean: one enqueue → one task → one release. |
| `trade_orders` no unique constraint on `brokerage_order_id` | New migration adds partial unique index `(user_id, account_id, brokerage_order_id) WHERE NOT NULL`. |
| `_map_remote_order_row()` is API mapper, not DB insert shape | New `_insert_new_remote_orders()` uses DB insert shape from `trade_execution_service.py:1091`. |
| Maintenance tasks have no explicit queue in Beat entries | All Beat entries include `"options": {"queue": "sync.maintenance"}`. |
| SnapTrade disconnect: task must handle empty-holdings failure | Task catches `ValueError` → returns `{ok: False, reason: "empty_holdings_error"}`. `enqueue_and_wait` wraps as `{state: "failed", reason: "empty_holdings_error"}`. Route purges only when `state=="failed" + reason=="empty_holdings_error"` (or `state=="success" + count==0`) AND no remaining connections. |
| `routes/onboarding.py:616/665` mislabeled as connect handlers | Fixed: they are refresh endpoints. First-sync-on-connect wired in separate connect handlers. |
| `OrderWatcher` not in `app.py` but `mcp_server.py:2882` | Fixed: guard in `mcp_server.py:2882-2886`, not `app.py`. |
| Schwab/IBKR frontend refresh in `APIService.ts:944/955` | Added to Phase 4 frontend changes alongside PlaidService/SnapTradeService. |
| Phase 2 stubs sync_jobs but Phase 4 has the table | Documented: Phase 2 stubs are no-ops. `create_job`/`mark_*` only active after Phase 4 migration. |
| **v4 findings** | |
| `CREATE UNIQUE INDEX CONCURRENTLY` fails inside transaction | Changed to regular `CREATE UNIQUE INDEX IF NOT EXISTS` (not CONCURRENTLY). |
| `ON CONFLICT ON CONSTRAINT` doesn't work with partial unique indexes | Changed to `ON CONFLICT (user_id, account_id, brokerage_order_id) WHERE ... DO UPDATE SET ...`. |
| Lock → apply_async gap: lock held with no task if apply_async fails | try/except around apply_async releases lock on failure. |
| "Lock exists but no task_id" for second caller | `wait_for_sync` handles: sleep 1s + retry once → return `{state: 'enqueuing'}` if still None. |
| Broker redelivery creates second execution | Acceptable: lock auto-expires, sync is idempotent (delete-and-rewrite). Documented. |
| Redis operations need `redis.exceptions.ConnectionError` catch too | All Redis ops in `sync_runner` wrapped to catch both `redis.exceptions.ConnectionError` and `kombu.exceptions.OperationalError`. |
| Schwab/IBKR `data_sources` rows not guaranteed | Beat fan-out queries BOTH `data_sources` AND `positions` table for user discovery (union). Matches existing `_get_scoped_position_providers()` pattern. |
| Header still said v3 | Fixed to v4. |
| Critical Files table mislabeled onboarding lines | Fixed: "refresh endpoints" not "first-sync-on-connect". |
| MCP `refresh_provider` doesn't support IBKR | Phase 3 expands allowed values at `positions.py:493/555/972` to include `ibkr`. |
| SnapTrade disconnect: wrong failure mode (not missing-secret) | Fixed: actual path is empty holdings → ValueError, not credential-deleted. Task catches ValueError as terminal. |
| §0 Redis section inconsistent with §3 on error handling | §0 updated to match: catches `redis.exceptions.ConnectionError` + `kombu.exceptions.OperationalError`. |

---

## 10. Implementation Sequencing

```
Phase 1 (Freshness Contract)
    │
    ▼
Phase 2 (Celery + Redis + Schwab + wait shim + MCP migration)
    │
    ├──► Phase 3 (IBKR/Plaid/SnapTrade)
    │
    ├──► Phase 3.5 (get_orders full sync)  [sequential after 3 recommended]
    │
    └──► Phase 4 (sync_jobs + UX)   [can begin after Phase 2]
           │
           ▼
       Phase 5 (hardening + legacy deletion)
```

---

## 11. Critical Files

| File | Changes |
|------|---------|
| `services/position_service.py` | Freshness (Ph1); store-read (Ph2); legacy deletion (Ph5) |
| `services/trade_execution_service.py` | Short-sell shim (Ph2); `_insert_new_remote_orders` (Ph3.5); orders store-read (Ph3.5) |
| `services/order_watcher.py` | Deprecate under flag (Ph3.5) |
| `services/position_snapshot_cache.py` | Document 30s TTL is acceptable (no code change) |
| `core/result_objects/positions.py` | `provider_freshness` field (Ph1) |
| `core/position_flags.py` | `stale_data` integration (Ph1) |
| `mcp_tools/positions.py` | Agent freshness (Ph1); `refresh_provider` migration (Ph2); `force_refresh` shim (Ph3) |
| `app.py` (lifespan 1048-1060) | Celery broker ping + shutdown (Ph2) |
| `routes/plaid.py` (1070, 1347, 382, 1635) | Refresh + webhook + disconnect (Ph2-3) |
| `routes/snaptrade.py` (996, 1273, 369, 1131) | Same (verified line numbers) |
| `routes/onboarding.py` (616, 665) | Schwab/IBKR refresh endpoints → `enqueue_and_wait` (Ph2) |
| `routes/trading.py` (198-229) | Orders store-read (Ph3.5) |
| `mcp_tools/trading.py` (76-117) | Orders store-read (Ph3.5) |
| `frontend/packages/chassis/src/services/PlaidService.ts` (220) | Async refresh (Ph4) |
| `frontend/packages/chassis/src/services/SnapTradeService.ts` (200) | Async refresh (Ph4) |

**New directories/files:**
- `workers/` — `celery_app.py`, `beat_schedule.py`, `tasks/{positions,orders,maintenance}.py`
- `services/sync_status_service.py`, `services/sync_runner.py`, `services/sync_jobs_service.py`, `services/freshness_policy.py`, `services/circuit_breaker.py`
- `routes/sync_jobs.py`, `mcp_tools/sync.py`
- `core/result_objects/provider_freshness.py`
- `database/migrations/20260410_add_sync_status.sql`, `20260425_add_sync_jobs.sql`

## Verification

**Phase 1:** `get_positions(format="agent")` → `provider_freshness` block present for all providers. Single-provider path too.

**Phase 2:** `CELERY_ENABLED=true, SYNC_PROVIDER_SCHWAB_VIA_CELERY=true`. Start Celery services. `get_positions` returns Schwab from store. Kill Schwab → no hang, `status: "degraded"`. Short-sell path → enqueue+wait → success or `PreOrderVerificationError`. MCP `refresh_provider="schwab"` → goes through `sync_runner`, not live call.

**Phase 3:** All providers via Celery. IBKR offline → no hang. SnapTrade webhook → `sync_status.last_attempt_at` updates.

**Phase 3.5:** `get_orders` with IBKR offline → returns store orders + freshness. Orphan orders (placed outside UI) appear in store after sync.

**Phase 4:** Refresh button → 202 + job_id → spinner → resolves. MCP `wait_for_sync` tool works.

**Phase 5:** Kill Schwab 5 times → circuit opens → syncs skipped → half_open after 5min → canary.

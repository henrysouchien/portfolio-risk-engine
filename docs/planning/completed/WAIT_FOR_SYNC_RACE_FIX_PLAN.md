# Fix: `wait_for_sync` race — persist `celery_task_id` at enqueue time

**Status:** Implementation-ready (v2 — Codex R1 FAIL, 3 findings addressed)
**Date:** 2026-04-11

## Context

E2E testing revealed a race condition in the MCP `wait_for_sync` tool. When called immediately after `enqueue_sync()`, the tool reads `celery_task_id` from the `sync_jobs` DB row — but that field is only populated later when the Celery worker calls `mark_running()`. During the gap (typically <1s), the MCP tool gets `celery_task_id = NULL`, can't resolve the Celery `AsyncResult`, and returns `{"state": "enqueuing"}` after a 1s sleep instead of actually waiting.

**Reproduction:** enqueue a Schwab sync, immediately call `mcp_wait_for_sync(job_id=..., timeout_seconds=30)`. Returns `{"state": "enqueuing", "task_id": null}` while the job's refreshed row shows `celery_task_id` populated (set by worker's `mark_running()` after the wait already returned).

The fix: `task_id` is already generated deterministically in `enqueue_sync()` _before_ `apply_async()` (line 159). Move it above `create_job()` and pass it through so it's written to the DB row at INSERT time.

## Codex R1 findings (all addressed)

1. **HIGH — test param assertion stale.** `test_create_job_returns_inserted_or_active_job_id` at `tests/services/test_sync_jobs_service.py:63` asserts `cursor.executed[0][1] == (7, "schwab", 10, "on_demand")`. After adding `celery_task_id` to the INSERT, this becomes a 5-tuple. Must update.
2. **MEDIUM — ON CONFLICT + celery_task_id mismatch.** If `create_job` hits `ON CONFLICT` (Redis lock expired but DB job still active), a new Celery task is dispatched but the job row keeps the old `celery_task_id`. `wait_for_sync(job_id)` would track the wrong task. Fix: add `celery_task_id = EXCLUDED.celery_task_id` to the `DO UPDATE` clause — since we're about to dispatch a new task, the job should track the new one.
3. **MEDIUM — `enqueue_order_sync` has the same race.** Same pattern at `services/sync_runner.py:342-363`. Apply the same `task_id` early-generation + `create_job(celery_task_id=...)` fix. Explicitly in scope.

## Files to modify

| File | Change |
|------|--------|
| `services/sync_runner.py` | (a) `enqueue_sync` lines 144-159: move `task_id` generation before `create_job`, pass `celery_task_id=task_id`. (b) `enqueue_order_sync` lines 348-363: same pattern — move `task_id` before `create_job`, pass kwarg. |
| `services/sync_jobs_service.py` | `create_job()` line 35: add `celery_task_id: str \| None = None` param. Add to INSERT columns/values AND to `DO UPDATE SET` clause (`celery_task_id = EXCLUDED.celery_task_id`). |
| `tests/services/test_sync_jobs_service.py` | Line 63: update param tuple assertion to include 5th element (None when not passed). Add new test verifying `celery_task_id` is persisted when provided. |
| `tests/services/test_sync_runner.py` | Verify existing tests still pass (no changes needed — `create_job` fails silently in these tests). |

## Detailed changes

### 1. `services/sync_runner.py` — `enqueue_sync()`

Current (lines 139-172):
```python
job_id = None
try:
    from services.sync_jobs_service import create_job
    from workers.tasks.positions import sync_provider_positions

    try:
        job_id = create_job(
            user_id=int(user_id),
            provider=provider_key,
            trigger=trigger,
            deadline_seconds=deadline_seconds,
        )
    except Exception as exc:
        ...
    task_id = f"sync:{int(user_id)}:{provider_key}:{uuid4()}"
    task = sync_provider_positions.apply_async(...)
```

After:
```python
job_id = None
try:
    from services.sync_jobs_service import create_job
    from workers.tasks.positions import sync_provider_positions

    task_id = f"sync:{int(user_id)}:{provider_key}:{uuid4()}"
    try:
        job_id = create_job(
            user_id=int(user_id),
            provider=provider_key,
            trigger=trigger,
            deadline_seconds=deadline_seconds,
            celery_task_id=task_id,
        )
    except Exception as exc:
        ...
    task = sync_provider_positions.apply_async(...)
```

### 2. `services/sync_runner.py` — `enqueue_order_sync()`

Same pattern. Current (lines 342-363):
```python
    try:
        job_id = create_job(
            user_id=int(user_id),
            provider=job_provider,
            trigger=trigger,
            deadline_seconds=deadline_seconds,
        )
    except Exception as exc:
        ...
    task_id = f"sync:{int(user_id)}:orders:{uuid4()}"
```

After:
```python
    task_id = f"sync:{int(user_id)}:orders:{uuid4()}"
    try:
        job_id = create_job(
            user_id=int(user_id),
            provider=job_provider,
            trigger=trigger,
            deadline_seconds=deadline_seconds,
            celery_task_id=task_id,
        )
    except Exception as exc:
        ...
```

### 3. `services/sync_jobs_service.py` — `create_job()`

Add `celery_task_id` param, include in INSERT + DO UPDATE:

```python
def create_job(
    user_id: int,
    provider: str,
    trigger: str,
    deadline_seconds: int = 120,
    celery_task_id: str | None = None,
) -> str | None:
```

```sql
INSERT INTO sync_jobs (
    user_id, provider, status, expires_at, trigger, celery_task_id
)
VALUES (
    %s, %s, 'pending',
    NOW() + (%s || ' seconds')::interval,
    %s, %s
)
ON CONFLICT (user_id, provider)
WHERE status IN ('pending', 'running')
DO UPDATE SET
    expires_at = GREATEST(sync_jobs.expires_at, EXCLUDED.expires_at),
    trigger = EXCLUDED.trigger,
    celery_task_id = EXCLUDED.celery_task_id
RETURNING id
```

Params tuple: `(int(user_id), provider_key, int(deadline_seconds), str(trigger or ""), celery_task_id)`

### 4. `mark_running()` — no change needed

Already does `celery_task_id = COALESCE(%s, celery_task_id)`. The worker passes the same task_id it was dispatched with — idempotent.

### 5. `tests/services/test_sync_jobs_service.py`

Update existing assertion at line 63:
```python
# Before:
assert cursor.executed[0][1] == (7, "schwab", 10, "on_demand")
# After:
assert cursor.executed[0][1] == (7, "schwab", 10, "on_demand", None)
```

Add new test:
```python
def test_create_job_persists_celery_task_id(monkeypatch) -> None:
    cursor = _FakeCursor(fetchone_results=[{"id": "job-2"}])
    conn = _FakeConn(cursor)
    monkeypatch.setattr("database.is_db_available", lambda: True)
    monkeypatch.setattr("database.get_db_session", lambda: _FakeSession(conn))

    job_id = sync_jobs_service.create_job(
        7, "schwab", "test", deadline_seconds=30,
        celery_task_id="sync:7:schwab:abc123",
    )

    assert job_id == "job-2"
    assert cursor.executed[0][1] == (7, "schwab", 30, "test", "sync:7:schwab:abc123")
    assert "celery_task_id" in cursor.executed[0][0]
```

## Verification

1. Run existing + new tests:
   ```
   python3 -m pytest tests/services/test_sync_runner.py tests/services/test_sync_jobs_service.py -xvs
   ```
2. E2E: enqueue a sync, immediately call MCP `wait_for_sync(job_id)`, verify it returns `state: "success"` (not `"enqueuing"`).
3. Verify DB: `SELECT celery_task_id FROM sync_jobs ORDER BY enqueued_at DESC LIMIT 1` should be non-null immediately after enqueue, before worker picks up.

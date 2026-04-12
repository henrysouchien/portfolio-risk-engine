# E20 Fix: DB Connection Pool Exhaustion + Silent Empty Portfolio

## Context

Discovered 2026-04-12 during aggregator E2E testing. 98 idle postgres connections accumulated from Celery worker forks + server restarts, hitting PostgreSQL's default `max_connections=100`. When connections exhaust, `_load_store_positions` silently returns an empty DataFrame — the user sees "Your portfolio is empty" with zero error indication.

**Two root causes, six changes.**

### Codex Review History

- **R1 FAIL** — 3 findings: (1-High) single-provider `get_positions()` path doesn't build `_cache_metadata`, routes using it still silent; (2-Med) `close_pool()` doesn't reset inherited DB availability cooldown globals post-fork; (3-Med) Group C test redundant, missing `_build_cache_info` propagation test. All addressed in R2.
- **R2 FAIL** — 1 finding: (High) Change 4 adds `_cache_metadata` to the `PositionResult` from single-provider path, but the REST route response builders (`routes/plaid.py:1181`, `routes/snaptrade.py`, `routes/onboarding.py`) never consume it — they build responses from `positions`, `from_cache`, `cache_age_hours`, `sync_result` only. Acknowledged as known limitation — see "Known Gaps" section.
- **R2 FAIL (cont)** — Codex also said the dashboard/Overview path is NOT the MCP agent format but `/api/positions/holdings`. Traced: `routes/positions.py:609` → `_build_cached_position_holdings_payload` → `_load_enriched_positions` → `get_all_positions()` → `_cache_metadata` built (Change 3) → `generate_position_flags(cache_info=getattr(result, "_cache_metadata", {}))` at line 504-512 → `provider_error` flag → annotated into `payload["portfolio_alert_details"]` at lines 528-532. **The dashboard holdings path IS covered by Change 3.** Separately, the `/api/positions/alerts` endpoint at line 712-718 hardcodes `cache_info={}`, dropping all cache errors — added as Change 6.

---

## Change 1: Celery `worker_process_init` handler (fixes the leak)

**File:** `workers/celery_app.py`

The primary connection leak. `worker_max_tasks_per_child=1` means every task runs in a forked child. The child inherits the parent's `PoolManager._default_manager` (class var at `app_platform/db/pool.py:13`) with stale file descriptors. No handler exists to reset the pool post-fork.

**Edit:**
- Line 8: Add `worker_process_init, worker_process_shutdown` to the signal import
- After the existing `on_worker_ready` handler (line 44), add:

```python
@worker_process_init.connect
def on_worker_process_init(**kwargs):
    del kwargs
    from app_platform.db.pool import close_pool
    from database import reset_db_availability

    close_pool()
    reset_db_availability()


@worker_process_shutdown.connect
def on_worker_process_shutdown(**kwargs):
    del kwargs
    from app_platform.db.pool import close_pool
    close_pool()
```

**Why it works:** `close_pool()` (`pool.py:99-106`) acquires `_default_lock`, calls `closeall()`, sets `_default_manager = None`. Next `get_pool()` call creates a fresh `PoolManager` + fresh `ThreadedConnectionPool`. The `SessionManager` in `database/session.py` delegates to `pool_module.get_pool()` so it picks up the new pool automatically — no session manager reset needed.

**Why `worker_process_init` (not `worker_ready`):** `worker_ready` fires in the parent process. The forked *children* need the reset. With `max_tasks_per_child=1`, `close_pool()` cost per child is negligible (closes 0 connections if child hasn't opened any yet, or closes inherited stale ones).

---

## Change 2: Add `reset_db_availability()` to database module (R1 finding #2)

**File:** `database/__init__.py`

After fork, the child inherits the parent's module-level globals `_db_available`, `_db_available_at`, `_db_unavailable_until`. If the parent recently marked DB unavailable (cooldown armed), the child will also see `is_db_available() == False` even though it has a fresh pool. This makes `_load_cached_positions()` raise `ValueError("Database unavailable")` unnecessarily in the forked child.

**Edit** — add after `is_db_in_cooldown()` (after line 101), before `__all__`:

```python
def reset_db_availability() -> None:
    """Reset DB availability state — call after fork to clear inherited cooldown."""

    global _db_available, _db_available_at, _db_unavailable_until
    with _db_lock:
        _db_available = None
        _db_available_at = 0.0
        _db_unavailable_until = 0.0
```

Add `"reset_db_availability"` to `__all__` (line 104-110).

Setting `_db_available = None` (not `True`) forces a fresh probe on first use in the child — the child doesn't assume DB is up, it checks with its own fresh pool.

---

## Change 3: Propagate `store_read_error` to `_cache_metadata` in `get_all_positions` (fixes the silence)

**File:** `services/position_service.py`

At lines 940-941, the `_cache_metadata` error field only reads `fetch_error`:

```python
"error": provider_errors.get(name)
or (self._provider_metadata.get(name, {}) or {}).get("fetch_error"),
```

**Edit** — add `store_read_error` as third fallback:

```python
"error": provider_errors.get(name)
or (self._provider_metadata.get(name, {}) or {}).get("fetch_error")
or (self._provider_metadata.get(name, {}) or {}).get("store_read_error"),
```

**Why it works — existing pipeline activates with no other changes on the two primary surfaces:**

**Dashboard/holdings path** (`/api/positions/holdings`):
1. `routes/positions.py:504-508` calls `generate_position_flags(cache_info=getattr(result, "_cache_metadata", {}))` — now non-empty
2. `core/position_flags.py:112-120` sees `info.get("error")` — emits `provider_error` flag (severity: `"error"`)
3. Flag annotated into `payload["portfolio_alert_details"]` at `routes/positions.py:528-532`

**MCP agent path** (`mcp_tools/positions.py`):
1. `_build_cache_info()` at line 137 reads `meta.get("error")` — now non-null
2. `generate_position_flags()` at `core/position_flags.py:112-120` emits `provider_error` flag
3. Flag included in agent response `flags` array

Precedence is correct: `provider_errors` (top-level catch) > `fetch_error` (live-fetch path) > `store_read_error` (store path). No masking risk.

---

## Change 4: Build `_cache_metadata` in single-provider `get_positions()` (R1 finding #1)

**File:** `services/position_service.py`

The single-provider `get_positions()` at lines 575-629 attaches `_provider_metadata` (lines 625-628) but never builds `_cache_metadata`. Routes that call this path (`routes/plaid.py:1112`, `routes/snaptrade.py:956,1050`, `routes/onboarding.py:647,718`) can still silently return empty holdings.

**Edit** — after line 624 (after enrichment, before provider_metadata attachment), add:

```python
meta = self._provider_metadata.get(provider, {}) or {}
result._cache_metadata = {
    provider: {
        "from_cache": from_cache,
        "cache_age_hours": cache_age,
        "error": meta.get("fetch_error") or meta.get("store_read_error"),
    }
}
```

This mirrors the `get_all_positions` pattern at lines 936-944 but for a single provider. `provider_errors` is not available in this path (exceptions propagate instead of being collected), so only `_provider_metadata` errors are checked.

---

## Change 5: Add WARNING log in `_load_store_positions`

**File:** `services/position_service.py`

At line 1296-1298, the exception is completely silent in logs. Add a warning before the metadata stash:

```python
except Exception as exc:
    portfolio_logger.warning(
        "Store read failed for %s: %s", provider, exc
    )
    self._provider_metadata[provider]["store_read_error"] = str(exc)
    return pd.DataFrame(), True, cache_age_hours
```

`portfolio_logger` is already imported at line 67.

---

## Tests

### Group A: Celery signal handlers

**File:** `tests/workers/test_celery_app_config.py`

Following existing pattern at lines 25-28 (`test_worker_ready_signal_registered_once`):

```python
def test_worker_process_init_signal_registered() -> None:
    from celery.signals import worker_process_init
    receivers = [receiver() for _receiver_key, receiver in worker_process_init.receivers]
    assert celery_app.on_worker_process_init in receivers


def test_worker_process_shutdown_signal_registered() -> None:
    from celery.signals import worker_process_shutdown
    receivers = [receiver() for _receiver_key, receiver in worker_process_shutdown.receivers]
    assert celery_app.on_worker_process_shutdown in receivers


def test_worker_process_init_calls_close_pool_and_resets_db(monkeypatch) -> None:
    close_calls = []
    reset_calls = []
    monkeypatch.setattr("app_platform.db.pool.close_pool", lambda: close_calls.append(1))
    monkeypatch.setattr("database.reset_db_availability", lambda: reset_calls.append(1))
    celery_app.on_worker_process_init()
    assert len(close_calls) == 1
    assert len(reset_calls) == 1
```

### Group B: `store_read_error` propagation (both paths)

**File:** `tests/services/test_position_service_store_error.py` (new, small focused file)

1. **`test_store_read_error_in_get_all_positions_cache_metadata`**: Mock `is_provider_sync_enabled` -> True, mock `_load_cached_positions` -> raise `ValueError("Database unavailable")`, call `get_all_positions`, assert `result._cache_metadata[provider]["error"]` contains the error string.

2. **`test_store_read_error_in_get_positions_cache_metadata`**: Same setup but call single-provider `get_positions(provider)`, assert `result._cache_metadata[provider]["error"]` is set. (Covers R1 finding #1.)

3. **`test_provider_errors_take_precedence_over_store_read_error`**: Set up a provider that raises at the `get_all_positions` level (into `provider_errors`) AND has a `store_read_error`. Assert the `provider_errors` value wins.

### Group C: `_build_cache_info` propagation (R1 finding #3 — replaces redundant test)

**File:** `tests/database/test_pool_exhaustion.py`

Test that `_build_cache_info()` (from `mcp_tools/positions.py:124`) correctly forwards the error field from `_cache_metadata` to the returned cache_info dict. Create a mock `PositionResult` with `_cache_metadata = {"ibkr": {"from_cache": True, "cache_age_hours": 1.0, "error": "Database unavailable"}}`, call `_build_cache_info(result)`, assert result contains `{"ibkr": {..., "error": "Database unavailable"}}`.

### Group D: `reset_db_availability` unit test

**File:** `tests/database/test_pool_exhaustion.py`

Test that `reset_db_availability()` clears all three globals. Call `mark_db_unavailable()`, assert `is_db_in_cooldown() == True`, call `reset_db_availability()`, assert `is_db_in_cooldown() == False` and `is_db_available()` triggers a fresh probe (returns based on actual DB state, not cached).

### Group E: WARNING log + alerts endpoint (Changes 5 & 6)

**`test_store_read_failure_logs_warning`** — in `tests/services/test_position_service_store_error.py`. Mock `_load_cached_positions` to raise, call `_load_store_positions`, assert `portfolio_logger.warning` was called with the provider name and error message.

**`test_alerts_endpoint_passes_cache_metadata`** — in `tests/routes/test_positions_alerts.py` (new, small focused file). Mock `get_position_result_snapshot` to return a `PositionResult` with `_cache_metadata = {"ibkr": {"error": "Database unavailable"}}`, call `_build_portfolio_alerts_payload`, assert the returned `alerts` list contains an entry with `flag_type == "provider_error"` and `severity == "critical"` (the builder maps `"error"` -> `"critical"` at `routes/positions.py:729`). This verifies Change 6 (line 716 now passes `_cache_metadata` instead of `{}`).

---

## Files touched

| File | Change |
|------|--------|
| `workers/celery_app.py` | Add `worker_process_init` + `worker_process_shutdown` handlers with `close_pool()` + `reset_db_availability()` |
| `database/__init__.py` | Add `reset_db_availability()` function + export |
| `services/position_service.py` | Add `store_read_error` to `_cache_metadata` in `get_all_positions` (line 940) + build `_cache_metadata` in `get_positions` (after line 624) + WARNING log (line 1296) |
| `routes/positions.py` | Pass `_cache_metadata` to alerts endpoint `generate_position_flags` (line 716) |
| `tests/workers/test_celery_app_config.py` | 3 new tests for signal registration + close_pool + reset_db call |
| `tests/services/test_position_service_store_error.py` | New: store_read_error propagation tests for both paths + precedence |
| `tests/database/test_pool_exhaustion.py` | `_build_cache_info` propagation test + `reset_db_availability` unit test |
| `tests/routes/test_positions_alerts.py` | New: alerts endpoint cache_metadata propagation test (Change 6) |

---

## Verification

1. `pytest tests/workers/test_celery_app_config.py -v` — signal handlers registered and functional
2. `pytest tests/services/test_position_service_store_error.py -v` — error propagation (both paths) + warning log
3. `pytest tests/database/test_pool_exhaustion.py -v` — cache_info forwarding + reset_db
4. `pytest tests/routes/test_positions_alerts.py -v` — alerts endpoint cache_metadata propagation
5. `pytest tests/ -x --timeout=120` — full suite, no regressions
5. Manual: start all services, check `SELECT count(*) FROM pg_stat_activity WHERE datname='risk_module_db'` before/after Celery tasks to confirm connection count stays bounded

---

## Change 6: Pass `_cache_metadata` to alerts endpoint (fixes `/api/positions/alerts` gap)

**File:** `routes/positions.py`

At line 716, the `/api/positions/alerts` endpoint hardcodes `cache_info={}`, dropping all cache/store errors from the flags:

```python
flags = generate_position_flags(
    positions=result.data.positions,
    total_value=result.total_value,
    cache_info={},  # <-- drops all cache errors
```

**Edit** — replace with:

```python
    cache_info=getattr(result, "_cache_metadata", {}),
```

This mirrors the pattern already used at line 508 in the `/holdings` endpoint. One-line fix.

---

## Known gaps (follow-up items)

### REST route error surfacing (not in scope)

Change 4 makes `_cache_metadata` available on the `PositionResult` from single-provider `get_positions()`, but the REST route response builders for provider-specific refresh endpoints never consume it. The affected response builders:
- `routes/plaid.py:1181` (`HoldingsResponse`)
- `routes/snaptrade.py:980` (SnapTrade non-refresh `HoldingsResponse`) and `:1089` (refresh path `HoldingsResponse`)
- `routes/onboarding.py:666` and `:737` (onboarding response builders — called from `:647` and `:718`)

These build responses from `positions`, `from_cache`, `cache_age_hours`, and `sync_result` — they don't check for DB errors. A store-read failure can still return `success=True` with empty holdings and a generic "showing cached holdings" message.

**Why out of scope:** The primary user-visible portfolio display goes through `/api/positions/holdings` (`routes/positions.py:609` -> `get_all_positions()` -> `_cache_metadata` built -> `generate_position_flags(cache_info=getattr(result, "_cache_metadata", {}))` at line 504 -> `provider_error` flag -> `payload["portfolio_alert_details"]` at line 528), which is fully covered by Change 3. The MCP agent path is also covered. The provider-refresh routes are called during explicit user actions (brokerage connection refresh, onboarding) and would each need individual response builder changes + per-route tests. That's a separate bug surface (REST route error surfacing) — not part of E20's "silent empty portfolio on Overview."

**Follow-up:** Each route should check `result._cache_metadata[provider]["error"]` (or `result.provider_metadata.get("store_read_error")`) and return `success=False` with the error message when the store read fails.

---

## What this does NOT address (multi-user follow-up)

- pgbouncer / connection proxy (needed for multi-user scale)
- `DB_POOL_MAX` tuning per process type
- Celery pool mode change (prefork -> solo)
- Connection recycling / idle timeout (psycopg2 pools lack this natively)

These are scoped for the multi-user readiness track.

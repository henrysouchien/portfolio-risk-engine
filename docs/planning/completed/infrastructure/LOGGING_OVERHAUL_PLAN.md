# Logging System Overhaul Plan

## Context

The logging system was built ~1 year ago as a guardrail to prevent AI coders from scattering ad-hoc debug statements everywhere. It served that purpose well, but the codebase is now mature and the logs have become noise themselves.

**Current state:** Two separate logging systems — `utils/logging.py` (2,200 lines, writes to `logs/`) and `app.py` local functions + `utils/json_logging.py` (write to `error_logs/`). Together they produce 10 named loggers, 19+ structured logging functions, 6 decorators, an architectural context system that walks 10 stack frames per log entry, and 17+ log files across two directories. A single FMP API call generates entries in 4 different files. Daily log output is ~3MB, mostly "FMP_API: healthy" spam.

**Goal:** Make logs optimized for AI-agent debugging — one place to look, high signal, enough context per entry to debug without cross-referencing files, no noise.

---

## Current State Details

### Dual Logging Systems

**System 1: `utils/logging.py`** — writes to `logs/`
- 10 named loggers, 19 structured functions, 6 decorators
- 131 files import from this module

**System 2: `app.py` + `utils/json_logging.py`** — writes to `error_logs/`
- `app.py:949` defines local `log_error_json()` → `error_logs/error_*.json`
- `app.py:983` defines local `log_usage()` → `error_logs/usage_*.json`
- `app.py:1018` defines local `log_request()` → delegates to `log_usage()`
- `utils/json_logging.py` defines `log_structured_event()` → `error_logs/{event_type}_*.json`
- `routes/frontend_logging.py` uses `json_logging.py` → `error_logs/frontend_events_*.json`, `error_logs/frontend_errors_*.json`
- `routes/admin.py:466` reads `error_logs/usage_*.json` for admin analytics dashboard

### Log Files (10 text + 7+ daily JSON in `logs/` + 4+ daily JSON in `error_logs/`)

**Text logs (in `logs/`):**
| File | Daily Size | Status |
|---|---|---|
| `portfolio.log` | 340KB | Active, noisy |
| `api.log` | 164KB | Active, mostly health-check spam |
| `database.log` | 150KB | Active, logs full SQL at INFO |
| `performance.log` | 141KB | Active, logs "wrapper: 2.1ms" |
| `trading.log` | 1.3KB | Active, good signal |
| `claude.log` | 0 | Always empty |
| `gpt.log` | 0 | Always empty |
| `frontend.log` | 0 | Always empty |
| `plaid.log` | 0 | Always empty |
| `schema.log` | 0 | Always empty |

**Daily JSON files (in `logs/`):**
| File | Daily Size | Content |
|---|---|---|
| `service_health_*.json` | 896KB | 99% "FMP_API: healthy" entries |
| `portfolio_operations_*.json` | 751KB | Every decorated function logs here |
| `performance_metrics_*.json` | 581KB | Timing for trivial functions |
| `resource_usage_*.json` | 97KB | psutil snapshots |
| `critical_alerts_*.json` | 51KB | 13 identical DB-down entries (no dedup) |
| `sql_queries_*.json` | 27KB | Full SQL query text |
| `workflow_states_*.json` | 18KB | Workflow step tracking |

**Daily JSON files (in `error_logs/`):**
| File | Content |
|---|---|
| `error_*.json` | API endpoint exceptions (from `app.py` local function) |
| `usage_*.json` | API usage metrics — **consumed by admin analytics** |
| `frontend_events_*.json` | Frontend client-side logs |
| `frontend_errors_*.json` | Frontend client-side errors |

### Structured Logging Functions (19 in `utils/logging.py` + 3 in `app.py` + 1 in `json_logging.py`)

**`utils/logging.py` functions:**
| Function | Call Sites | Disposition |
|---|---|---|
| `log_error_json` | 142 | See migration note below |
| `log_portfolio_operation` | 61 | Replace with `log_event()` |
| `log_critical_alert` | 61 | Replace with `log_alert()` (with dedup) |
| `log_request` / `log_usage` | 36/3 | Replace with `log_usage()` — preserve schema for admin analytics |
| `log_service_health` | 25 | Replace with `log_service_status()` (non-healthy only) |
| `log_auth_event` | 13 | Replace with `log_event()` |
| `log_claude_integration` | 5 | Remove (merge into `log_event()`) |
| `log_rate_limit_hit` | 4 | Merge into `log_alert()` |
| `log_sql_query` | 3 | Remove (use `logger.debug()` directly) |
| `log_performance_metric` | 3 | Replace with `log_slow_operation()` |
| `log_database_error` | 3 | Merge into `log_error()` |
| `log_api_request` | 3 | Merge into `log_event()` |
| `log_schema_validation` | 3 | Remove |
| `log_data_transformation` | 2 | Remove |
| `log_gpt_integration` | 0 | Delete |
| `log_test_execution` | 0 | Delete |
| `log_resource_usage` | 0 | Delete |
| `log_workflow_state` | 0 | Delete |

**`log_error_json` migration note:** This function is called with inconsistent argument types. Many callers pass actual exceptions, but some pass dicts (e.g., `routes/provider_routing.py:255` passes provider metadata), strings (e.g., `app.py:2027` passes `"ERROR"`), or informational data (e.g., `routes/snaptrade.py:899` logs webhook receipts). The migration must classify each call site:
- **Actual errors** (exception objects) → `log_error()`
- **Operational events logged through the error path** (webhook receipts, metadata) → `log_event()`
- **Structured failure reports** (provider routing failures with metadata dicts) → `log_alert()`

### Decorators (6 total)

| Decorator | Usage Count | Disposition |
|---|---|---|
| `@log_error_handling` | 237 | Replace with `@log_errors` (simplified, async-safe) |
| `@log_performance` | 213 | Replace with `@log_timing` (simplified, async-safe) |
| `@log_portfolio_operation_decorator` | 191 | Replace with `@log_operation` (simplified, async-safe) |
| `@log_cache_operations` | 56 | Remove |
| `@log_resource_usage_decorator` | 39 | Remove |
| `@log_api_health` | 34 | Remove (primary noise source) |
| `@log_workflow_state_decorator` | 5 | Remove |

### Key Problems

1. **Dual logging systems:** `logs/` and `error_logs/` directories with separate infrastructure, creating split observability.
2. **Quadruple logging:** A single FMP API call logs to `api.log`, `service_health_*.json`, `performance.log`, and `performance_metrics_*.json`.
3. **Healthy-call spam from all services:** FMP client (`fmp/client.py:_log_success`), PostgreSQL (`core/portfolio_config.py:81`), and Plaid (`plaid_loader.py:442,536`) all log every successful health check. FMP is the worst offender.
4. **Architectural context bloat:** Each JSON entry is ~1KB due to `architectural_context` fields (`call_path`, `patterns`, `dependencies`, `ai_guidance`) that are almost always empty.
5. **No dedup:** `critical_alerts` has 13 identical "DB connection failed" entries from one overnight outage.
6. **Decorator stacking on trivial functions:** `helpers_display.py` has triple-stacked decorators on functions like `format_percentage()`.
7. **No log rotation:** Files grow unbounded.
8. **Duplicate module:** `risk_module_secrets/logging.py` is a 2,185-line copy of `utils/logging.py`.
9. **`log_error_json` misuse:** Called with non-exception arguments (dicts, strings, webhook data) at many sites.
10. **`app.py` local logging bypasses central module:** Local `log_error_json`/`log_usage`/`log_request` in `app.py` write directly to `error_logs/`, bypassing `utils/logging.py` entirely.

---

## New Design

### Log Files: 5 instead of 21+

| File | Purpose | Format | Level |
|---|---|---|---|
| `logs/app.log` | Main application log | Text | INFO+ (all environments) |
| `logs/errors.jsonl` | Structured errors & alerts | JSON Lines | Errors + alerts only |
| `logs/usage.jsonl` | API usage tracking (for admin analytics) | JSON Lines | Usage events only |
| `logs/frontend.jsonl` | Frontend client-side structured events | JSON Lines | All frontend events |
| `logs/debug.log` | Verbose debug (dev only) | Text | DEBUG+ |

All use `RotatingFileHandler` (10MB/3 backups for app/debug; 5MB/5 backups for errors/frontend).

**Exception: `usage.jsonl` does NOT use rotation.** It uses a plain `FileHandler` (append-only) so that admin analytics can always read the complete file without scanning rotated backups. Usage volume is low (~36 requests/day based on current `log_request` call frequency), so unbounded growth is not a concern. If it ever becomes one, a date-based archival script can be added.

`app.log` is INFO+ in all environments so that `log_event()` calls (auth events, portfolio operations, audit breadcrumbs) are always captured. The noise reduction comes from eliminating the sources of spam (healthy-call logging, trivial decorator logging), not from level filtering.

The `error_logs/` directory is consolidated into `logs/`. `usage.jsonl` replaces `error_logs/usage_*.json`. `frontend.jsonl` replaces `error_logs/frontend_events_*.json` and `error_logs/frontend_errors_*.json`, preserving all structured fields (level, category, component, message, url, userAgent, data, session, userId).

**Admin analytics continuity:** At cutover (Phase 2c), existing `error_logs/usage_*.json` files are left in place. The updated admin endpoint reads from `logs/usage.jsonl` for new data. Historical totals from before cutover are not backfilled — the admin dashboard shows data from cutover onward. If historical continuity is needed, a one-time migration script can concatenate old files into `usage.jsonl`.

### Logging initialization

Logging is configured at module import time (top of `utils/logging.py`) to guarantee early boot logs are captured before full app initialization. Handlers are attached to the **true root logger** (`logging.getLogger()`), not just `risk_module.*`. This ensures that all loggers — including stdlib `logging.getLogger(__name__)` calls in files like `portfolio_risk.py`, `core/data_objects.py`, `inputs/database_client.py`, and `services/claude/function_executor.py` — route to `app.log` and `debug.log` without requiring migration.

```python
# Module-level initialization — runs on first import
_root_logger = logging.getLogger()  # true root logger
_root_logger.setLevel(logging.DEBUG)
# app.log and debug.log handlers attached to root — catches ALL loggers
# errors.jsonl handler is NOT on root — only written to by log_error()/log_alert()
```

**Idempotency requirement:** Handler attachment MUST be guarded against duplicate addition (e.g., on module reload, repeated imports, or test setup). Use the existing `_has_file_handler()` pattern: check if a handler for the target file path already exists before adding. This prevents duplicate log lines in reload/test scenarios.

The `risk_module.*` namespace is used for `get_logger()` callers but is not required for handler routing. Any logger in the process writes to `app.log`/`debug.log` via the root handlers.

### Logger: 1 hierarchical logger instead of 10

```python
def get_logger(name: str) -> logging.Logger:
    """Get a logger under the app hierarchy. Usage: get_logger(__name__)"""
    return logging.getLogger(f"risk_module.{name}")
```

### Functions: 7 instead of 23

| Function | Replaces | Output |
|---|---|---|
| `log_error(source, message, exc=None, **details)` | `log_error_json`, `log_database_error` | `errors.jsonl` |
| `log_alert(alert_type, severity, message, **details)` | `log_critical_alert`, `log_rate_limit_hit` | `errors.jsonl` (with 5-min dedup) |
| `log_event(event_type, message, **details)` | `log_portfolio_operation`, `log_auth_event`, `log_api_request`, `log_claude_integration` | `app.log` at INFO |
| `log_slow_operation(operation, duration_s, **details)` | `log_performance_metric` | `app.log` at WARNING |
| `log_service_status(service, status, **details)` | `log_service_health` | Only logs non-healthy (degraded/down/timeout) |
| `log_usage(ticker, year, quarter, key, source, status, tier, full_year_mode)` | `app.py:log_usage`, `app.py:log_request` | `usage.jsonl` |
| `log_frontend_event(event_data)` | `log_structured_event('frontend_events', ...)` | `frontend.jsonl` |

**`log_error()` signature compatibility:** Takes `exc` as optional (default `None`). When `exc` is a real exception, `exception_type` and `traceback` are extracted automatically. When `exc` is a dict, string, or None, the value is stored in `details["context"]` and no traceback is generated. This handles all existing call-site patterns without breaking.

**`log_usage()` is an exact signature match** with the current `app.py:log_usage(ticker, year, quarter, key, source, status="success", tier="public", full_year_mode=False)`. Same positional args, same defaults, same output schema (`timestamp`, `ticker`, `year`, `quarter`, `key`, `source`, `status`, `tier`, `full_year_mode`). No adapter layer needed — it's a drop-in replacement that writes to `logs/usage.jsonl` instead of `error_logs/usage_*.json`.

### Decorators: 3 instead of 6 (all async-safe)

All decorators use `asyncio.iscoroutinefunction()` to properly handle both sync and async functions. Async functions are awaited; sync functions are called directly. No blocking I/O is introduced in the async path — log writes use the same synchronous handler model as stdlib logging (which is standard practice; async logging queues are out of scope for this refactor).

| Decorator | Replaces | Behavior |
|---|---|---|
| `@log_errors(severity="medium")` | `@log_error_handling` | Catch, log to `errors.jsonl`, reraise (~20 lines) |
| `@log_timing(threshold_s=1.0)` | `@log_performance` | Only logs above threshold (~20 lines) |
| `@log_operation(name)` | `@log_portfolio_operation_decorator` | Logs start/end at INFO (~25 lines) |

### errors.jsonl Entry Format

```json
{
  "ts": "2026-02-19T04:09:16Z",
  "level": "ERROR",
  "type": "database_connection_failure",
  "severity": "high",
  "message": "Database connection failed for cash positions",
  "source": "core/portfolio_config.py:get_cash_positions",
  "error": "connection to localhost:5432 failed",
  "exception_type": "OperationalError",
  "traceback": "Traceback (most recent call last):\n  ...",
  "correlation_id": null,
  "user_id": null,
  "tier": null,
  "endpoint": null,
  "recovery": "Check database connectivity",
  "details": {"operation": "get_cash_mappings"},
  "dedup_key": "database_connection_failure:high:Database connection failed for cash positions",
  "suppressed_count": 12
}
```

Fields: `ts`, `level`, `type`, `severity`, `message`, `source` (file:function), `error`, `exception_type`, `traceback`, `correlation_id`, `user_id`, `tier`, `endpoint`, `recovery`, `details` (arbitrary dict), `dedup_key`, `suppressed_count` (how many identical alerts were suppressed since last logged).

`correlation_id` is extracted from kwargs or thread-local context if available (supports existing `correlation_id`, `request_id`, `plaid_req_id` patterns). `tier` and `endpoint` preserve the triage metadata from current `log_error_json` callers that pass `key`/`tier` arguments.

No `architectural_context`, no `call_path` array, no `patterns`, no `ai_guidance: ""`.

### Alert Deduplication

Thread-safe in-memory dedup with suppressed-count tracking:

```python
import threading

_dedup_lock = threading.Lock()
_recent_alerts: dict[str, tuple[float, int]] = {}  # key -> (last_logged_ts, suppressed_count)
DEDUP_WINDOW_S = 300  # 5 minutes
MAX_DEDUP_KEYS = 500  # evict oldest beyond this

def _check_dedup(key: str) -> tuple[bool, int]:
    """Returns (should_log, suppressed_count). Thread-safe."""
    now = time.time()
    with _dedup_lock:
        if key in _recent_alerts:
            last_ts, count = _recent_alerts[key]
            if (now - last_ts) < DEDUP_WINDOW_S:
                _recent_alerts[key] = (last_ts, count + 1)
                return False, 0
            else:
                # Window expired — log with suppressed count, reset
                _recent_alerts[key] = (now, 0)
                return True, count
        _recent_alerts[key] = (now, 0)
        # Evict oldest if over limit
        if len(_recent_alerts) > MAX_DEDUP_KEYS:
            oldest_key = min(_recent_alerts, key=lambda k: _recent_alerts[k][0])
            del _recent_alerts[oldest_key]
        return True, 0
```

**Process safety note:** Dedup is per-process. In the current deployment (single-process MCP servers, single Flask process), this is sufficient. Multi-worker deployments would need file-based or shared-memory dedup, which is out of scope — the worst case is duplicate alerts across workers, which is acceptable.

### Removed Entirely

- Architectural context system (190 lines: `get_architectural_context()`, `generate_ai_guidance()`, `detect_architectural_violations()`, layer/pattern/dependency dicts, `ArchitecturalContextFormatter`)
- All daily date-stamped JSON files in `logs/` (service_health, performance_metrics, portfolio_operations, etc.)
- All daily date-stamped JSON files in `error_logs/` (consolidated into `logs/`)
- `utils/json_logging.py` (replaced by `log_frontend_event()` and `log_event()`)
- Local logging functions in `app.py` (lines 949-1020) and `risk_module_secrets/app.py` (lines 940-1009)
- 5 empty log files (claude.log, gpt.log, frontend.log, plaid.log, schema.log)
- 13 dead/absorbed logging functions
- 4 decorators (`@log_api_health`, `@log_cache_operations`, `@log_resource_usage_decorator`, `@log_workflow_state_decorator`)

---

## Implementation Phases

### Phase 0: Audit and classify `log_error_json` call sites

Before any code changes, classify all `log_error_json` call sites (in `utils/logging.py` consumers, `app.py` local function consumers, AND `risk_module_secrets/app.py` local function consumers) into:
- **Actual errors** (exception objects) → will map to `log_error()`
- **Operational events** (webhook receipts, metadata) → will map to `log_event()`
- **Structured failure reports** (provider failures with metadata dicts) → will map to `log_alert()`

Additionally, classify `key` argument patterns at each `log_error_json` call site:
- **Actual correlation/request IDs** (e.g., plaid_req_id, API key identifier) → map to `correlation_id`
- **Error text or context strings** passed in the `key` position (e.g., `app.py:2027`, `app.py:2158`, `app.py:2359`) → map to `details["context"]`, NOT `correlation_id`
- **User IDs** passed in the `key` position (e.g., `app.py:2399`, `app.py:2497`, `app.py:2543`, `app.py:2592`, `app.py:2715`, `app.py:2846`) → map to `user_id` field
This distinction is critical — blindly mapping `key→correlation_id` would lose primary error context or misclassify user IDs at many sites.

Also inventory:
- `app.py` and `risk_module_secrets/app.py` local `log_error_json()` callers and their `key`/`tier` argument patterns
- `app.py` and `risk_module_secrets/app.py` local `log_usage()`/`log_request()` callers and their field usage
- `utils/json_logging.py` → `log_structured_event()` callers
- Any dynamic imports or string-based references to logging functions

**Output:** Classification list in a separate audit file (`docs/planning/LOGGING_AUDIT.md`).

### Phase 1: Rewrite logging core (non-breaking)

Rewrite `utils/logging.py` internals. All old exports remain as thin backward-compat aliases.

**Steps:**
1. Module-level logging initialization (runs on first import, before app code)
2. Create new logger hierarchy (`get_logger()`, single root `risk_module` logger)
3. Set up `RotatingFileHandler` for `app.log`, `errors.jsonl`, `frontend.jsonl`, `debug.log`; plain `FileHandler` (append-only, no rotation) for `usage.jsonl`
4. Implement 7 new functions (`log_error`, `log_alert`, `log_event`, `log_slow_operation`, `log_service_status`, `log_usage`, `log_frontend_event`)
5. Implement thread-safe dedup with suppressed-count tracking
6. Implement 3 new async-safe decorators (`@log_errors`, `@log_timing`, `@log_operation`)
7. Wire old 10 named loggers as aliases to new hierarchy
8. Wire old 19 structured functions as thin wrappers calling new functions, preserving argument signatures (especially `log_usage` positional args: `ticker, year, quarter, key, source, status, tier, full_year_mode`)
9. Wire old 6 decorators as aliases to new decorators
10. Delete architectural context system internals (wrappers just won't call it)

**Result:** 131 importing files keep working with zero changes. New log files start being written. Old handlers removed so old files stop growing. Module shrinks from 2,200 to ~450 lines.

**File:** `utils/logging.py`

### Phase 2: Consolidate `app.py` and `json_logging.py` logging

**2a — `app.py` and `risk_module_secrets/app.py` local functions:**
Both files define identical local `log_error_json()`, `log_usage()`, `log_request()` functions (at `app.py:949-1020` and `risk_module_secrets/app.py:940-1009`). Delete the local definitions in both files and replace with imports from `utils/logging.py`. The `log_usage()` and `log_request()` calls are drop-in replacements (identical signature).

For `log_error_json()` callers in both files, each call site must be individually rewritten (not just import-swapped) because the `key` argument is used heterogeneously. Using the Phase 0 classification as a guide, each call site gets a specific rewrite:
```python
# Example: key is a user_id (app.py:2399 pattern)
# Before: log_error_json("ENDPOINT", "context", exc, user_id, "paid")
# After:  log_error("ENDPOINT", "context", exc, user_id=user_id, tier="paid")

# Example: key is error text (app.py:2027 pattern)
# Before: log_error_json("WHAT_IF", "API", "ERROR", str(e), user_tier)
# After:  log_error("WHAT_IF", "API error", context=str(e), tier=user_tier)

# Example: key is a correlation ID (plaid pattern)
# Before: log_error_json("plaid", "fetch", exc, plaid_req_id, "system")
# After:  log_error("plaid", "fetch", exc, correlation_id=plaid_req_id, tier="system")
```

**Files:** `app.py`, `risk_module_secrets/app.py` (both require per-callsite rewrite, not bulk find-replace)

**2b — `utils/json_logging.py` + `routes/frontend_logging.py` + `risk_module_secrets/frontend_logging.py`:**
Replace all `log_structured_event()` calls with `log_frontend_event()` which writes the full structured event payload (level, category, component, message, url, userAgent, data, session, userId) to `frontend.jsonl`. Frontend error-level events are also written to `errors.jsonl` via `log_error()`. Must update ALL consumers including `risk_module_secrets/frontend_logging.py`.

**2c — Admin analytics (`routes/admin.py:466`):**
Update to read from `logs/usage.jsonl` instead of `error_logs/usage_*.json`. The schema is preserved: `timestamp`, `ticker`, `year`, `quarter`, `key`, `source`, `status`, `tier`, `full_year_mode`. The analytics endpoint (total requests, success rate, tier breakdown, last 50 requests) will work identically.

**Files:** `app.py`, `risk_module_secrets/app.py`, `utils/json_logging.py`, `routes/frontend_logging.py`, `risk_module_secrets/frontend_logging.py`, `routes/admin.py`

### Phase 3: Fix noise sources

**3a — Healthy-call spam:** Remove `log_service_health("...", "healthy", ...)` calls from:
- `fmp/client.py:_log_success()` (FMP — biggest offender)
- `core/portfolio_config.py:81` (PostgreSQL)
- `plaid_loader.py:442,536` (Plaid)
Keep error-path logging only at all three sites.

**3b — Decorator stacking:** Remove triple-stacked decorators from trivial display/formatting functions in `helpers_display.py`, `helpers_input.py`, `risk_helpers.py`, `risk_summary.py`.

**Files:** `fmp/client.py`, `core/portfolio_config.py`, `plaid_loader.py`, `helpers_display.py`, `helpers_input.py`, `risk_helpers.py`, `risk_summary.py`

### Phase 4: Migrate callers to new API

Incrementally update importing files using Phase 0 classification. Priority order:
1. `log_error_json` callers (142 sites) → `log_error()`, `log_event()`, or `log_alert()` per classification
2. Named logger imports → `get_logger(__name__)`
3. Removed decorator usages → delete decorator lines
4. `log_service_health` remaining healthy-path calls → delete
5. `log_critical_alert` callers → `log_alert()`
6. Remaining low-count functions

### Phase 5: Clean up

**Prerequisites (all must be true before starting Phase 5):**
1. Phase 0 audit is complete (all call sites classified)
2. Phase 4 migration is complete (all call sites updated, including `risk_module_secrets/` tree — e.g., `risk_module_secrets/api.py`, `risk_module_secrets/provider_routing.py`, `risk_module_secrets/claude/chat_service.py`)
3. Test files updated to use new API (move test migration from Phase 5 step 5 to Phase 4 — tests in `tests/api/test_logging.py` and `risk_module_secrets/test_logging.py` must be migrated before the gate check)
4. `grep -r` for each deprecated alias across all `.py` files (excluding `utils/logging.py` and `risk_module_secrets/logging.py`, where aliases are defined) returns zero results
5. Full test suite passes (`pytest tests/ -x`)

Note: grep does not guarantee safety against computed-name lookups (e.g., `getattr(module, f"log_{name}")`). No such patterns exist in the current codebase. Phase 0 audit explicitly checks for these; any found are refactored to explicit imports during Phase 4.

Also note: some files use `logging.getLogger(__name__)` directly (e.g., `portfolio_risk.py`, `core/data_objects.py`, `inputs/database_client.py`, `inputs/exceptions.py`). These are standard stdlib loggers outside the `risk_module.*` hierarchy. They are left as-is — they write to `app.log` via the root logger handler. No migration needed for these.

**Steps:**
1. Remove backward-compat aliases from `utils/logging.py` (only after all prerequisites pass)
2. Replace `risk_module_secrets/logging.py` (2,185-line duplicate) with `from utils.logging import *`
3. Delete `utils/json_logging.py` — grep-verify zero remaining imports first (including `risk_module_secrets/frontend_logging.py` and any other consumers, which must be updated in Phase 4)
4. Delete old empty log files

---

## Verification

### Automated (test suite)
1. Run existing test suite: `python -m pytest tests/ -x -q`
2. Add targeted tests for new behavior in `tests/api/test_logging.py`:
   - **Dedup:** Log the same alert 5x within 5 minutes → verify only 1 entry in `errors.jsonl` with `suppressed_count: 4`
   - **Async decorator:** Apply `@log_errors` to an async function that raises → verify error is logged and exception is re-raised
   - **Sink routing:** Call each of the 7 functions → verify output lands in the correct file (`errors.jsonl`, `app.log`, `usage.jsonl`, `frontend.jsonl`)
   - **`log_error` with non-exception exc:** Pass a dict and a string as `exc` → verify no crash, value stored in `details["context"]`

### Manual / integration
3. Trigger a portfolio analysis via MCP — verify `app.log` has clean output and no healthy-spam
4. Verify `errors.jsonl` captures actual errors with dedup, includes `exception_type`, `traceback`, `correlation_id` where available
5. Verify `usage.jsonl` captures API usage events — test admin analytics endpoint returns correct totals, tier breakdown, and recent activity
6. Verify `frontend.jsonl` captures frontend structured events with all fields (level, category, component, message, url, userAgent, data, session, userId)
7. Verify old daily JSON files stop growing / are no longer created
8. Check `debug.log` only appears when `ENVIRONMENT=development`
9. Confirm no import errors across all consuming files
10. Run alias removal gate (grep + full test suite) before Phase 5

## Scope Boundaries

The following are explicitly **out of scope** for this refactor:
- **Async logging queues:** Log writes remain synchronous (stdlib standard). If async latency becomes an issue, a `QueueHandler` can be added later.
- **Multi-process dedup:** Dedup is per-process. Current deployment is single-process. Multi-worker dedup (e.g., via file locks or shared memory) can be added if deployment model changes.
- **Log aggregation/shipping:** No ELK/Datadog/etc. integration. Logs are local files for AI-agent consumption.

## Key Files

- `utils/logging.py` — core module (2,208 lines -> ~450 lines)
- `app.py` — local logging functions (lines 949-1020) to consolidate
- `risk_module_secrets/app.py` — local logging functions (lines 940-1009) to consolidate
- `utils/json_logging.py` — secondary logging module to remove
- `routes/frontend_logging.py` — frontend log ingestion to update
- `routes/admin.py` — admin analytics to update (reads usage logs)
- `fmp/client.py` — primary noise source (healthy-call logging)
- `core/portfolio_config.py` — PostgreSQL healthy-call logging
- `plaid_loader.py` — Plaid healthy-call logging
- `helpers_display.py` — worst decorator abuse
- `risk_module_secrets/logging.py` — duplicate to replace
- `tests/api/test_logging.py` — logging tests to update

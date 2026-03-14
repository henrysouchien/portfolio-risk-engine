# Transaction Store Phase 3b — Make Store Default

## Context

Phases 1-3 complete. 6 PostgreSQL tables, `TransactionStore` class, 8 MCP tools, `TRANSACTION_STORE_READ` flag verified identical to live-fetch for all 3 institutions. Phase 3b makes the store the **default read path** with automatic staleness detection and re-ingest.

**Design choices:**
- Stale data → **auto-ingest** before reading (not warn-only, not fallback to live-fetch)
- Flag cleanup → **keep flag, default to `true`** (not remove entirely)

## Changes

### 1. Flip `TRANSACTION_STORE_READ` default to `true`

**File:** `settings.py:139`

```python
# Before:
TRANSACTION_STORE_READ = os.getenv("TRANSACTION_STORE_READ", "").strip().lower() in ("1", "true", "yes")

# After:
TRANSACTION_STORE_READ = os.getenv("TRANSACTION_STORE_READ", "true").strip().lower() in ("1", "true", "yes")
```

Live-fetch path retained behind `TRANSACTION_STORE_READ=false` as escape hatch.

### 2. Extract undecorated `_ingest_transactions_inner()` for programmatic use

**File:** `mcp_tools/transactions.py`

The current `ingest_transactions()` is wrapped with `@handle_mcp_errors`, which swallows exceptions into `{"status": "error"}` and swaps stdout. Internal callers need raw exceptions for proper error handling.

```python
def _ingest_transactions_inner(
    user_email: str,
    provider: str = "all",
) -> dict:
    """Core ingest logic — no MCP decorator. Raises on failure.

    Three DB session boundaries to avoid holding a pooled connection
    during network fetch:
    1. Short session: create batch record (status='ingesting')
    2. Network: fetch_transactions_for_source() — no DB conn held
    3. Long session: store raw, normalize, update batch to 'complete' or 'failed'

    Also detects swallowed fetch errors: when fetch_metadata contains
    error entries (provider returned FetchResult with error metadata
    instead of raising), treat single-provider ingest as failure.
    """
    # Sketch:
    #
    # --- Session 1: create batch ---
    # with get_db_session() as conn:
    #     store = TransactionStore(conn)
    #     batch_id = store.create_batch(user_id, provider, status="ingesting")
    #
    # --- Network: fetch (no DB conn held) ---
    # try:
    #     fetch_result = fetch_transactions_for_source(...)
    # except Exception as exc:
    #     with get_db_session() as conn:
    #         store = TransactionStore(conn)
    #         store.update_batch_status(batch_id, status="failed", error_message=str(exc))
    #     raise
    #
    # # Detect swallowed fetch errors (data_fetcher.py:983-994 catches
    # # provider exceptions and returns empty payload + error metadata
    # # instead of raising). For single-provider ingest, this means
    # # 0 raw rows + error in metadata — treat as failure.
    # # Only fail when error metadata AND empty payload — partial-data
    # # ingests (some rows fetched despite errors) should still persist.
    # fetch_metadata = list(getattr(fetch_result, "fetch_metadata", []) or [])
    # payload = getattr(fetch_result, "payload", fetch_result)
    # if provider != "all":
    #     has_fetch_error = any(
    #         m.get("status") == "error" or m.get("fetch_error")
    #         for m in fetch_metadata
    #     )
    #     # Check emptiness using the SAME provider_rows dict that the
    #     # ingest loop uses (keys: plaid, schwab, ibkr_flex, ibkr_flex_mtm,
    #     # snaptrade). Filter to allowed providers for this ingest, then
    #     # check if all row lists are empty.
    #     allowed = {provider}
    #     if provider == "ibkr_flex":
    #         allowed.add("ibkr_flex_mtm")
    #     payload_empty = not any(
    #         rows for rp, rows in provider_rows.items()
    #         if rp in allowed
    #     )
    #     if has_fetch_error and payload_empty:
    #         error_msg = "Provider fetch failed (no data): " + str(fetch_metadata)
    #         with get_db_session() as conn:
    #             store = TransactionStore(conn)
    #             store.update_batch_status(batch_id, status="failed",
    #                                      error_message=error_msg)
    #         raise RuntimeError(error_msg)
    #     # If has_fetch_error but payload NOT empty → partial success.
    #     # Proceed with ingest — store whatever data we got. Error metadata
    #     # is preserved in batch fetch_metadata for diagnostic visibility.
    #
    # --- Session 2: store + normalize ---
    # with get_db_session() as conn:
    #     store = TransactionStore(conn)
    #     try:
    #         ... store raw, normalize, update to 'complete' ...
    #     except Exception as exc:
    #         store.update_batch_status(batch_id, status="failed", error_message=str(exc))
    #         raise

@handle_mcp_errors
def ingest_transactions(
    user_email: Optional[str] = None,
    provider: Provider = "all",
) -> dict:
    """MCP entry point — delegates to _ingest_transactions_inner()."""
    return _ingest_transactions_inner(user_email=user_email, provider=provider)
```

Update `refresh_transactions()` (line 500) to call `_ingest_transactions_inner()` with per-provider try/except to preserve existing error-aggregation behavior:

```python
for provider_name in providers:
    started = time.perf_counter()
    try:
        ingest_result = _ingest_transactions_inner(user_email=user, provider=provider_name)
    except Exception as exc:
        errors.append({"provider": provider_name, "error_message": str(exc)})
        continue
    duration_seconds = round(time.perf_counter() - started, 3)
    # ... rest of success path unchanged
```

### 3. Add `get_latest_batch_time()` method on TransactionStore

**File:** `inputs/transaction_store.py`

```python
def get_latest_batch_time(self, user_id: int, provider: str | None = None) -> datetime | None:
    """Return completed_at of most recent successful batch."""
    # SELECT MAX(completed_at) FROM ingestion_batches
    # WHERE user_id = %s AND status = 'complete'
    # [AND provider = %s]
```

Note: status literal is `'complete'` (not `'completed'`), matching the enum used in `update_batch_status()` at line 161 and `load_fetch_metadata()` at line 1296.

### 4. Add `get_latest_failed_batch_time()` for retry cooldown

**File:** `inputs/transaction_store.py`

```python
def get_latest_failed_batch_time(self, user_id: int, provider: str | None = None) -> datetime | None:
    """Return timestamp of most recent failed batch (for retry cooldown)."""
    # SELECT MAX(COALESCE(updated_at, started_at)) FROM ingestion_batches
    # WHERE user_id = %s AND status = 'failed'
    # [AND provider = %s]
    # Uses updated_at (set on status change) with started_at fallback.
    # This measures when the failure was recorded, not when the attempt started,
    # so long-running failures don't cause premature cooldown expiry.
```

### 5. Add `ensure_store_fresh()` helper

**File:** `inputs/transaction_store.py`

```python
import logging

_logger = logging.getLogger(__name__)

_CONCRETE_PROVIDERS = ["plaid", "schwab", "ibkr_flex", "snaptrade"]

def ensure_store_fresh(
    user_id: int,
    user_email: str,
    provider: str | None = None,
    max_age_hours: float = 24.0,
    retry_cooldown_minutes: float = 15.0,
) -> list[dict] | None:
    """Check store freshness; auto-ingest if stale or empty.

    Returns list of ingest result dicts if ingestion ran, None if fresh.
    Per-provider staleness: when provider is None or 'all', checks each
    concrete provider individually and only re-ingests stale ones.
    Retry cooldown: if last ingest failed within retry_cooldown_minutes,
    skip re-ingest to avoid retry storms.
    """
    from mcp_tools.transactions import _ingest_transactions_inner  # local import to avoid circular

    # Normalize provider token — canonical lowercase, reject unsupported values early.
    norm_provider = str(provider).strip().lower() if provider else None
    if norm_provider == "all":
        norm_provider = None

    if norm_provider and norm_provider not in _CONCRETE_PROVIDERS:
        _logger.warning("ensure_store_fresh: unsupported provider %r — skipping", provider)
        return None

    providers_to_check = (
        [norm_provider] if norm_provider
        else _CONCRETE_PROVIDERS
    )

    now = datetime.utcnow()
    stale_providers = []

    with get_db_session() as conn:
        store = TransactionStore(conn)
        for p in providers_to_check:
            # Check retry cooldown FIRST — applies to both empty and stale paths.
            # Prevents retry storms when provider is down (empty store + repeated failures).
            last_fail = store.get_latest_failed_batch_time(user_id, provider=p)
            if last_fail:
                fail_age_min = (now - last_fail).total_seconds() / 60
                if fail_age_min < retry_cooldown_minutes:
                    _logger.info(
                        "Skipping auto-ingest for %s — last failure was %.1f min ago "
                        "(cooldown: %.1f min)", p, fail_age_min, retry_cooldown_minutes,
                    )
                    continue

            latest = store.get_latest_batch_time(user_id, provider=p)
            if latest is None:
                # Empty store for this provider — ingest needed
                stale_providers.append(p)
                continue
            age_hours = (now - latest).total_seconds() / 3600
            if age_hours > max_age_hours:
                stale_providers.append(p)

    if not stale_providers:
        return None

    results = []
    for p in stale_providers:
        try:
            result = _ingest_transactions_inner(user_email=user_email, provider=p)
            results.append(result)
        except Exception:
            _logger.warning("Auto-ingest failed for %s — proceeding with stale data", p, exc_info=True)
    return results or None
```

**Key design points:**
- **Function-local import** of `_ingest_transactions_inner` avoids circular import (`inputs/transaction_store.py` ↔ `mcp_tools/transactions.py`)
- **Per-provider staleness**: iterates `_CONCRETE_PROVIDERS` individually when `provider=None/'all'`, so one stale provider doesn't trigger unnecessary re-ingest of fresh ones
- **Retry cooldown**: checks `get_latest_failed_batch_time()` — if last failure was within `retry_cooldown_minutes` (default 15), skips that provider to avoid retry storms
- **Ingest errors don't block reads**: caught and logged, execution continues with stale data
- **Empty store + ingest failure**: caught by same try/except — `load_from_store()` will return empty lists, downstream tools handle empty data with their existing no-data paths (e.g., `trading_analysis.py:113` returns `{"status": "error", "message": "No transactions found"}`)

### 6. Wire `ensure_store_fresh()` at 4 call sites

All sites already have `user_email` available. Insert `ensure_store_fresh()` call **before** `load_from_store()` inside the `TRANSACTION_STORE_READ` branch.

**Site 1:** `core/realized_performance_analysis.py:3233` — `_analyze_realized_performance_single_scope()`
```python
if TRANSACTION_STORE_READ:
    ensure_store_fresh(user_id, user_email, source, max_age_hours=TRANSACTION_STORE_MAX_AGE_HOURS, retry_cooldown_minutes=TRANSACTION_STORE_RETRY_COOLDOWN_MINUTES)
    store_data = load_from_store(user_id, source, institution, account)
    ...
```

**Site 2:** `core/realized_performance_analysis.py:5323` — `_prefetch_fifo_transactions()`
```python
if TRANSACTION_STORE_READ:
    ensure_store_fresh(user_id, user_email, source, max_age_hours=TRANSACTION_STORE_MAX_AGE_HOURS, retry_cooldown_minutes=TRANSACTION_STORE_RETRY_COOLDOWN_MINUTES)
    store_data = load_from_store(user_id, source)
    ...
```

**Site 3:** `mcp_tools/trading_analysis.py:101` — `get_trading_analysis()`
```python
if TRANSACTION_STORE_READ:
    ensure_store_fresh(user_id, user_email, source, max_age_hours=TRANSACTION_STORE_MAX_AGE_HOURS, retry_cooldown_minutes=TRANSACTION_STORE_RETRY_COOLDOWN_MINUTES)
    store_data = load_from_store(user_id, source, institution, account)
    ...
```

**Site 4:** `mcp_tools/tax_harvest.py:110` — `_load_fifo_data()`
```python
if TRANSACTION_STORE_READ:
    ensure_store_fresh(user_id, user_email, source, max_age_hours=TRANSACTION_STORE_MAX_AGE_HOURS, retry_cooldown_minutes=TRANSACTION_STORE_RETRY_COOLDOWN_MINUTES)
    store_data = load_from_store(user_id, source, institution, account)
    ...
```

### 7. Add settings

**File:** `settings.py`

```python
TRANSACTION_STORE_MAX_AGE_HOURS = float(os.getenv("TRANSACTION_STORE_MAX_AGE_HOURS", "24"))
TRANSACTION_STORE_RETRY_COOLDOWN_MINUTES = float(os.getenv("TRANSACTION_STORE_RETRY_COOLDOWN_MINUTES", "15"))
```

### 8. Pin `TRANSACTION_STORE_READ=false` in test environment

**File:** `tests/conftest.py` (or equivalent test setup)

`TRANSACTION_STORE_READ` is evaluated at import time in `settings.py` and imported by value into callers (`from settings import TRANSACTION_STORE_READ`). Setting the env var at test runtime via `monkeypatch.setenv` is too late — the module-level value is already baked in.

**Approach:** Patch the module-level attribute in all importing modules:

```python
@pytest.fixture(autouse=True)
def _disable_store_read(monkeypatch):
    """Prevent tests from hitting the transaction store by default."""
    monkeypatch.setattr("settings.TRANSACTION_STORE_READ", False)
    monkeypatch.setattr("core.realized_performance_analysis.TRANSACTION_STORE_READ", False)
    monkeypatch.setattr("mcp_tools.trading_analysis.TRANSACTION_STORE_READ", False)
    monkeypatch.setattr("mcp_tools.tax_harvest.TRANSACTION_STORE_READ", False)
```

This patches all 4 locations where the flag is imported by value. Existing tests (which mock live-fetch paths) continue to work.

## Key Design Decisions

- **Per-provider staleness**: Check freshness per concrete provider (`plaid`, `schwab`, `ibkr_flex`, `snaptrade`), not globally. If only Schwab is stale, only Schwab re-ingests.
- **Retry cooldown**: If last ingest failed within 15 minutes (configurable), skip auto-ingest for that provider to prevent retry storms on every request.
- **No concurrent ingest guard**: If two requests trigger ingest simultaneously, the second upserts over the first. Safe because store uses ON CONFLICT DO UPDATE. Slight redundancy acceptable for simplicity.
- **Ingest errors don't block reads**: Caught and logged. Proceed with whatever store data exists (stale > nothing). Empty store + ingest failure = downstream tools' existing no-data error paths.
- **First-run experience**: Empty store auto-ingests on first `get_performance(mode='realized')` call. Slightly slower first call, but transparent to user.
- **Undecorated inner function**: `_ingest_transactions_inner()` gives programmatic callers raw exceptions instead of `@handle_mcp_errors` swallowing them into `{"status": "error"}`.
- **Function-local import**: `ensure_store_fresh()` imports `_ingest_transactions_inner` inside the function body to break the circular import between `inputs/transaction_store.py` and `mcp_tools/transactions.py`.
- **Status literal**: `'complete'` (not `'completed'`), matching the enum used throughout `TransactionStore`.

## Files to Modify

| File | Change |
|------|--------|
| `settings.py` | Flip `TRANSACTION_STORE_READ` default to `true`, add `TRANSACTION_STORE_MAX_AGE_HOURS`, add `TRANSACTION_STORE_RETRY_COOLDOWN_MINUTES` |
| `inputs/transaction_store.py` | Add `get_latest_batch_time()`, `get_latest_failed_batch_time()`, `ensure_store_fresh()` |
| `mcp_tools/transactions.py` | Extract `_ingest_transactions_inner()`, update `refresh_transactions()` to use it |
| `core/realized_performance_analysis.py` | Insert `ensure_store_fresh()` at 2 sites (lines ~3233, ~5323) |
| `mcp_tools/trading_analysis.py` | Insert `ensure_store_fresh()` at line ~101 |
| `mcp_tools/tax_harvest.py` | Insert `ensure_store_fresh()` at line ~110 |
| `tests/conftest.py` | Add autouse fixture to pin `TRANSACTION_STORE_READ=false` |

## What NOT to Change

- `load_from_store()` — unchanged, still the pure read function
- Live-fetch else-branches — kept intact as escape hatch
- No new tables or schema changes

## Verification

1. **Fresh store (no ingest):** Set `TRANSACTION_STORE_READ=true`, ingest manually, then call `get_performance(mode='realized')`. Should NOT trigger re-ingest. Check logs for absence of ingest messages.

2. **Stale store (auto-ingest):** Set `TRANSACTION_STORE_MAX_AGE_HOURS=0.001` (3.6 seconds), call `get_performance(mode='realized')`. Should auto-ingest then return results.

3. **Empty store (first run):** Clear ingestion_batches for a provider, call `get_trading_analysis()`. Should auto-ingest then return results.

4. **Escape hatch:** Set `TRANSACTION_STORE_READ=false`, call any tool. Should use live-fetch path, no store interaction.

5. **Ingest failure resilience:** Temporarily break provider credentials, call with stale data. Should log warning, return stale store data.

6. **Retry cooldown:** Break provider credentials, trigger auto-ingest (fails), immediately call again. Second call should skip ingest (within 15-min cooldown) and use stale data.

7. **Per-provider staleness:** Ingest only Schwab (fresh), wait >24h for IBKR. Call with `source=None`. Should re-ingest only IBKR, not Schwab.

8. **Regression:** Run `pytest tests/ -x -q` with `TRANSACTION_STORE_READ=false` pinned in conftest. All existing tests pass.

## Codex Review Findings

### Round 1

| ID | Severity | Issue | Resolution |
|----|----------|-------|------------|
| R1 | HIGH | Status literal wrong — plan says `'completed'` but DB uses `'complete'` | FIXED: corrected to `'complete'` (change #3) |
| R2 | HIGH | Per-provider staleness not guaranteed for `source='all'` — `MAX(completed_at)` hides stale providers | FIXED: iterate `_CONCRETE_PROVIDERS` individually (change #5) |
| R3 | MEDIUM | Retry storm — failed ingests don't update `completed_at`, so every request retries | FIXED: retry cooldown via `get_latest_failed_batch_time()` (changes #4, #5) |
| R4 | MEDIUM | Empty store + ingest failure = no data and no stale fallback | FIXED: exception caught, empty data → downstream no-data error paths (change #5) |
| R5 | MEDIUM | Circular import — `inputs/transaction_store.py` → `mcp_tools/transactions.py` → `inputs/transaction_store.py` | FIXED: function-local import (change #5) |
| R6 | MEDIUM | `ingest_transactions` is MCP-decorated, swallows exceptions | FIXED: extracted `_ingest_transactions_inner()` (change #2) |
| R7 | LOW | Tests don't set `TRANSACTION_STORE_READ` — flipping default could break CI | FIXED: autouse fixture pins `false` in tests (change #8) |

### Round 2

| ID | Severity | Issue | Resolution |
|----|----------|-------|------------|
| R8 | MEDIUM | R3 partial: cooldown only checked when successful batch exists; empty store + repeated failure retries every time | FIXED: moved cooldown check before `get_latest_batch_time` — applies to both empty and stale paths (change #5) |
| R9 | MEDIUM | R7 partial: `TRANSACTION_STORE_READ` evaluated at import time, `monkeypatch.setenv` too late | FIXED: patch module-level attribute in all 4 importing modules via `monkeypatch.setattr` (change #8) |
| R10 | MEDIUM | `refresh_transactions()` uses `@handle_mcp_errors` error dict; switching to `_ingest_transactions_inner()` would abort on first provider failure | FIXED: wrap in per-provider try/except, append to `errors` list (change #2) |
| R11 | LOW | Provider token not normalized before staleness check — mixed-case/alias input could cause repeated failures | FIXED: normalize to canonical lowercase, reject unsupported values early (change #5) |
| R12 | LOW | `TRANSACTION_STORE_RETRY_COOLDOWN_MINUTES` not passed at call sites | FIXED: all 4 call sites now pass both `max_age_hours` and `retry_cooldown_minutes` (change #6) |

### Round 3

| ID | Severity | Issue | Resolution |
|----|----------|-------|------------|
| R13 | MEDIUM | Pre-fetch failures don't create batch records — cooldown has no failure timestamp, retries every request | FIXED: move `create_batch()` before `fetch_transactions_for_source()` in `_ingest_transactions_inner()`, wrap entire body in try/except that updates batch to `'failed'` (change #2) |
| R14 | LOW | `get_latest_failed_batch_time()` uses `MAX(started_at)` — long-running failures cause premature cooldown expiry | FIXED: use `MAX(COALESCE(updated_at, started_at))` to measure when failure was recorded (change #4) |

### Round 4

| ID | Severity | Issue | Resolution |
|----|----------|-------|------------|
| R15 | MEDIUM | Swallowed fetch errors: `data_fetcher.py:983` catches provider exceptions and returns empty payload + error metadata instead of raising. Single-provider ingest completes with status `'complete'` despite no data, bypassing cooldown. | FIXED: `_ingest_transactions_inner()` checks `fetch_metadata` for error entries after fetch; for single-provider ingest, treats error metadata as failure → batch `'failed'` + raise (change #2) |
| R16 | MEDIUM | Batch creation before fetch holds pooled DB connection during network I/O | FIXED: three explicit DB session boundaries — (1) short session for create_batch, (2) network fetch with no conn held, (3) long session for store/normalize/status update (change #2) |

### Round 5

| ID | Severity | Issue | Resolution |
|----|----------|-------|------------|
| R17 | MEDIUM | Swallowed fetch error check too broad — partial-success fetches (some rows + error metadata) would be incorrectly marked as failed | FIXED: fail only when `has_fetch_error AND payload_empty`. Partial-data ingests proceed normally; error metadata preserved in batch for diagnostics (change #2) |

### Round 6

| ID | Severity | Issue | Resolution |
|----|----------|-------|------------|
| R18 | MEDIUM | `payload_empty` checked `payload.get(key)` against `provider_rows` keys (provider names), not payload keys — wrong lookup | FIXED: check emptiness from `provider_rows` dict directly, filtered to `allowed` providers (same logic as ingest loop). `ibkr_flex_mtm` alias included (change #2) |

## Post-Implementation: Data Quality Audit Fix

### IBKR Flex dedup key collision (25 missing income events)

**Problem**: IBKR interest charges (margin interest, `BROKER INTEREST PAID`) appear in **both** `ibkr_flex_trades` and `ibkr_flex_cash_rows` from the Flex query, sharing the same `transaction_id`. When concatenated into a single `ibkr_flex` bucket for storage (line 133 of `mcp_tools/transactions.py`), `ON CONFLICT (user_id, provider, dedup_key) DO UPDATE` causes one version to overwrite the other. Result: 287 live rows → 262 stored (25 lost).

**Impact**: 25 UNKNOWN interest income events missing from store path. FIFO unaffected (these are `type: INTEREST` with `symbol: UNKNOWN`, no lot matching). Flow events unaffected.

**Fix**: In `_dedup_key()`, append `_cash` suffix to dedup keys for rows identified as cash rows by `_looks_like_ibkr_cash_row()`. Trade and cash versions of the same transaction are now stored as separate rows.

```python
# inputs/transaction_store.py, _dedup_key(), ibkr_flex branch
is_cash = self._looks_like_ibkr_cash_row(row)
suffix = "_cash" if is_cash else ""
return f"ibkr_flex_{trade_id}{suffix}"
```

**Verification**: After fix, raw rows = 287 (was 262), income events = 118 (matches live-fetch, was 93). 680 tests pass.

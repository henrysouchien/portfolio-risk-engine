# E21: Provider-Refresh REST Routes — Surface DB Errors

## Context

Follow-up from E20 (`8abfe4d0`). E20 added `_cache_metadata` (with `error` field from `fetch_error or store_read_error`) to `PositionResult` from both `get_all_positions()` and single-provider `get_positions()`. The dashboard and MCP agent paths consume this and surface `provider_error` flags. But 5 provider-refresh REST route callsites never check `_cache_metadata` — they can return `success=True` with empty holdings when the error field is set.

### Codex Review History

- **R1 FAIL** — 3 findings: (1) `_cache_metadata[provider]["error"]` is not store-specific — it contains `fetch_error or store_read_error`, so "Database unavailable" message is wrong for fetch failures; (2) guard placement before `_record_refresh()` skips cooldown recording; (3) test plan missing edge cases. All addressed in R2.

## Approach

Add a `get_position_error()` helper in `routes/_sync_helpers.py` to extract the error from `_cache_metadata`. Each route checks it after `get_positions()` — if error + empty positions, return `success=False` with the raw error string (not hardcoded "Database unavailable"). Guards placed AFTER `_record_refresh()` to preserve cooldown behavior.

---

## Change 1: Add `get_position_error()` helper

**File:** `routes/_sync_helpers.py` — after `provider_refresh_message()` (after line 136)

```python
def get_position_error(result: Any, provider: str) -> str | None:
    """Extract position-load error from _cache_metadata, if any.

    The error field may come from a fetch failure (upstream provider)
    or a store-read failure (DB unavailable). Returns the raw error
    string so callers can surface it without misclassifying the cause.
    """
    cache_meta = getattr(result, "_cache_metadata", None)
    if not isinstance(cache_meta, dict):
        return None
    provider_meta = cache_meta.get(provider)
    if not isinstance(provider_meta, dict):
        return None
    return provider_meta.get("error")
```

---

## Change 2: Plaid refresh (`routes/plaid.py`)

**After** `_record_refresh()` at line 1118, before `from_cache` extraction. Insert after line 1118:

```python
from routes._sync_helpers import get_position_error
position_error = get_position_error(result, "plaid")
if position_error and not result.data.positions:
    return HoldingsResponse(
        success=False,
        message=position_error,
        provider="plaid",
    )
```

---

## Change 3: SnapTrade GET holdings (`routes/snaptrade.py`)

After `get_positions()` at line 956-961. No `_record_refresh()` on this path — insert after line 962:

```python
from routes._sync_helpers import get_position_error
position_error = get_position_error(result, "snaptrade")
if position_error and not result.data.positions:
    return HoldingsResponse(
        success=False,
        message=position_error,
        provider="snaptrade",
    )
```

---

## Change 4: SnapTrade POST refresh (`routes/snaptrade.py`)

**After** `_record_refresh()` at line 1056. Insert after line 1056:

```python
position_error = get_position_error(result, "snaptrade")
if position_error and not result.data.positions:
    return HoldingsResponse(
        success=False,
        message=position_error,
        provider="snaptrade",
    )
```

(`get_position_error` already imported from Change 3 in the same file.)

---

## Change 5: Onboarding — Schwab (`routes/onboarding.py`)

After `get_positions()` at line 647-652. No `_record_refresh()` on onboarding paths. Insert after line 652:

```python
from routes._sync_helpers import get_position_error
position_error = get_position_error(result, "schwab")
if position_error and not _extract_result_positions(result):
    return {"success": False, "error": position_error, "message": position_error}
```

Onboarding uses `_extract_result_positions(result)` (not `result.data.positions`) — follow the existing pattern. The normal positions extraction happens at line 665, so we check before it.

---

## Change 6: Onboarding — IBKR (`routes/onboarding.py`)

After `get_positions()` at line 718-723. Insert after line 723:

```python
position_error = get_position_error(result, "ibkr")
if position_error and not _extract_result_positions(result):
    return {"success": False, "error": position_error, "message": position_error}
```

(`get_position_error` already imported from Change 5 in the same file.)

---

## Tests

**File:** `tests/routes/test_provider_refresh_store_error.py` (new)

### Helper test
- `test_get_position_error_extracts_error`: pass result with `_cache_metadata = {"plaid": {"error": "DB down"}}` → returns `"DB down"`
- `test_get_position_error_returns_none_when_no_cache_metadata`: result without `_cache_metadata` → returns `None`
- `test_get_position_error_returns_none_when_cache_metadata_is_none`: `_cache_metadata = None` → returns `None`
- `test_get_position_error_returns_none_when_no_error`: `_cache_metadata = {"plaid": {"error": None}}` → returns `None`

### Route tests (one per callsite)
Each test mocks `PositionService.get_positions` to return empty positions + error in `_cache_metadata`, then asserts `success=False` + error in message.

### Edge case: error present but positions exist
- `test_error_with_positions_returns_normal_success`: mock positions + error → response is normal `success=True` (the guard only fires when positions are empty)

---

## Files touched

| File | Change |
|------|--------|
| `routes/_sync_helpers.py` | Add `get_position_error()` helper |
| `routes/plaid.py` | Early return on error + empty (after `_record_refresh`, line 1118) |
| `routes/snaptrade.py` | Early return on error + empty (2 callsites: line 962, line 1056) |
| `routes/onboarding.py` | Early return on error + empty (2 callsites: line 652, line 723) |
| `tests/routes/test_provider_refresh_store_error.py` | New: ~10 tests (helper + routes + edge cases) |

---

## Verification

1. `pytest tests/routes/test_provider_refresh_store_error.py -v`
2. `pytest tests/ -x -q` — no regressions

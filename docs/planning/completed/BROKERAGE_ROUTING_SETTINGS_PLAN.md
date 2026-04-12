# Plan: File-Based Brokerage Routing Settings

## Context

The three routing dicts in `providers/routing_config.py` (`POSITION_ROUTING`, `TRANSACTION_ROUTING`, `TRADE_ROUTING`) are hardcoded in Python. Switching Schwab from direct provider to SnapTrade requires editing code + restarting the service. This plan moves routing tables into a YAML config file — single source of truth, editable at runtime, hot-reloadable, manageable via MCP tool.

**Trigger:** Connected Schwab via SnapTrade, but position sync still routes to direct Schwab provider. Need a way to change routing without code edits.

## Codex Review Status

- **R1 (gpt-5.4):** FAIL — 9 findings. All addressed in v2.
- **R2 (gpt-5.4):** FAIL — 5 findings. All addressed in v3.
- **R3 (gpt-5.4):** FAIL — 3 findings (v2 findings confirmed resolved). All addressed in v4.
- **R4 (gpt-5.4):** FAIL — 3 remaining + 1 new. All addressed in v5.
- **R5 (gpt-5.4):** FAIL — 1 finding (v4 findings resolved). Addressed in v6.
- **R6 (gpt-5.4):** FAIL — 1 finding (manual YAML edits can introduce invalid providers). Addressed in v7.
- **R7 (gpt-5.4):** FAIL — 1 finding (loader uses shared provider set, not per-section). Addressed in v8.
- **R8 (gpt-5.4):** FAIL — 1 finding (invalid entries dropped without fallback to default). Addressed in v9.
- **R9 (gpt-5.4):** FAIL — 1 finding (`null` sections leak `None` to callers). Addressed in v10.
- **R10 (gpt-5.4):** FAIL — 1 finding (parse error replaces cache with defaults instead of keeping last-good). Addressed in v11.
- **R11 (gpt-5.4):** FAIL — 2 findings (write path clears cache before reload; missing test). Addressed in v12.
- **R12 (gpt-5.4):** FAIL — 2 findings (Python scoping bug in cross-module global access; concurrent readers see None during invalidate window). Addressed in v13.
- **R13 (gpt-5.4):** FAIL — 1 finding (write path skips semantic validation that runtime loader applies). Addressed in v14.
- **R14 (gpt-5.4):** FAIL — 1 finding (invalidate after write clears last-good, exposing cold-start fallback). Addressed in v15.
- **R15 (gpt-5.4):** FAIL — 1 finding (post-mutation data installed to cache without re-validation). Addressed in v16.
- **R16 (gpt-5.4):** FAIL — 1 finding (`remove` on default institution is silent no-op due to backfill). Addressed in v17.
- **R17 (gpt-5.4):** ✅ **PASS** — residual test recommendation incorporated.

## Change 1: Create `config/routing.yaml`

**New file:** `config/routing.yaml`

```yaml
# Brokerage routing — which provider handles each institution's data.
# Edit this file or use manage_brokerage_routing MCP tool.
# MCP tool writes take effect immediately for provider value changes.
# Manual file edits take effect within ~2s for value changes.
# Adding/removing institution keys requires a service restart
# (portfolio_scope.py snapshots routing keys at import time).

positions:
  charles_schwab: schwab
  interactive_brokers: ibkr

transactions:
  charles_schwab: schwab
  interactive_brokers: ibkr_flex

trades:
  charles_schwab: schwab
  interactive_brokers: ibkr
```

## Change 2: YAML loader in `routing_config.py`

**File:** `providers/routing_config.py`

### 2a. Hardcoded defaults remain as fallback

Keep the current dicts renamed as `_*_DEFAULTS` — used when the YAML file is missing or malformed. This addresses Codex R1 finding: "returning `{}` on missing file would silently drop production routing."

```python
_POSITION_ROUTING_DEFAULTS: dict[str, str] = {
    "charles_schwab": "schwab",
    "interactive_brokers": "ibkr",
}
_TRANSACTION_ROUTING_DEFAULTS: dict[str, str] = {
    "charles_schwab": "schwab",
    "interactive_brokers": "ibkr_flex",
}
_TRADE_ROUTING_DEFAULTS: dict[str, str] = {
    "charles_schwab": "schwab",
    "interactive_brokers": "ibkr",
}
```

### 2b. YAML loader with mtime_ns caching

Use `st_mtime_ns` (not `st_mtime`) per Codex finding. Use a **fixed path** (`Path(__file__).resolve().parent.parent / "config" / "routing.yaml"`) rather than `resolve_config_path()` since that's a search resolver unsuitable for writable files (Codex finding).

Cache the parsed dict + mtime_ns. Amortize stat calls: don't stat on every function call — cache for a short TTL (~2 seconds) so row-level callers in `partition_positions`/`partition_transactions` don't hit the filesystem per row.

```python
import time as _time
from pathlib import Path
import yaml

_ROUTING_YAML_PATH = Path(__file__).resolve().parent.parent / "config" / "routing.yaml"
_routing_cache: dict | None = None
_routing_mtime_ns: int = 0
_routing_check_at: float = 0.0
_ROUTING_CHECK_TTL = 2.0  # seconds between stat() calls

def _build_defaults() -> dict:
    return {
        "positions": dict(_POSITION_ROUTING_DEFAULTS),
        "transactions": dict(_TRANSACTION_ROUTING_DEFAULTS),
        "trades": dict(_TRADE_ROUTING_DEFAULTS),
    }

def _load_routing_yaml() -> dict:
    """Load routing from YAML with mtime_ns + TTL-amortized stat.
    
    R2 fix: on error paths (missing file, malformed YAML), cache the
    defaults dict so TTL amortization still applies. This prevents
    per-row stat() calls from partition_positions/partition_transactions.
    """
    global _routing_cache, _routing_mtime_ns, _routing_check_at
    now = _time.monotonic()
    if _routing_cache is not None and (now - _routing_check_at) < _ROUTING_CHECK_TTL:
        return _routing_cache
    _routing_check_at = now
    try:
        current_mtime_ns = _ROUTING_YAML_PATH.stat().st_mtime_ns
    except OSError:
        # Missing file → cache defaults (R2 fix: cache, don't just return)
        _routing_cache = _build_defaults()
        _routing_mtime_ns = 0
        return _routing_cache
    if _routing_cache is not None and current_mtime_ns == _routing_mtime_ns:
        return _routing_cache
    try:
        with open(_ROUTING_YAML_PATH) as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ValueError("routing.yaml root must be a mapping")
        # R2 fix: validate each section is a dict, fall back per-section
        # R13 fix: validation extracted to shared _validate_routing_data()
        # so both the loader and write path apply the same rules.
        data = _validate_routing_data(data)
    ...

def _validate_routing_data(data: dict) -> dict:
    """Shared validation for routing YAML — used by both loader and write path.
    
    R13 fix: ensures semantic validation (null sections, per-section provider
    validation, default institution backfill) is applied consistently.
    """
    _defaults_map = {
            "positions": _POSITION_ROUTING_DEFAULTS,
            "transactions": _TRANSACTION_ROUTING_DEFAULTS,
            "trades": _TRADE_ROUTING_DEFAULTS,
        }
        _VALID_PROVIDERS_BY_SECTION = {
            "positions": {"plaid", "snaptrade", "schwab", "ibkr"},
            "transactions": {"plaid", "snaptrade", "ibkr_flex", "schwab"},
            "trades": {"snaptrade", "schwab", "ibkr"},
        }
        for key in ("positions", "transactions", "trades"):
            section = data.get(key)
            # R9 fix: treat None same as non-dict (YAML `positions: null`)
            if not isinstance(section, dict):
                data[key] = dict(_defaults_map[key])
                continue
            if isinstance(section, dict):
                cleaned = {}
                defaults_for_key = _defaults_map[key]
                for inst, prov in section.items():
                    if not isinstance(prov, str) or prov not in _VALID_PROVIDERS_BY_SECTION[key]:
                        # R8 fix: fall back to hardcoded default for this institution
                        # instead of dropping the entry entirely
                        default_prov = defaults_for_key.get(str(inst))
                        if default_prov:
                            portfolio_logger.warning(
                                "routing.yaml: invalid provider %r for %s.%s, "
                                "falling back to default %r",
                                prov, key, inst, default_prov,
                            )
                            cleaned[str(inst)] = default_prov
                        else:
                            portfolio_logger.warning(
                                "routing.yaml: invalid provider %r for %s.%s, "
                                "no default — skipping",
                                prov, key, inst,
                            )
                        continue
                    cleaned[str(inst)] = prov
                # Also ensure all default institutions are present
                for inst, prov in defaults_for_key.items():
                    if inst not in cleaned:
                        cleaned[inst] = prov
                data[key] = cleaned
    return data
    # --- end _validate_routing_data ---
    # Back in _load_routing_yaml:
    except Exception as exc:
        # R10 fix: on parse error, keep last known-good cache if available.
        # Only fall back to defaults on cold start (no prior good cache).
        portfolio_logger.warning("routing.yaml parse error: %s", exc)
        if _routing_cache is not None:
            return _routing_cache  # preserve last-good
        _routing_cache = _build_defaults()
        _routing_mtime_ns = 0
        return _routing_cache
    _routing_cache = data
    _routing_mtime_ns = current_mtime_ns
    return data
```

### 2c. Getter functions + backward-compat module-level constants

```python
def get_position_routing() -> dict[str, str]:
    # R9 fix: use `or` — .get() returns None for present-but-null keys
    return _load_routing_yaml().get("positions") or dict(_POSITION_ROUTING_DEFAULTS)

def get_transaction_routing() -> dict[str, str]:
    return _load_routing_yaml().get("transactions") or dict(_TRANSACTION_ROUTING_DEFAULTS)

def get_trade_routing() -> dict[str, str]:
    return _load_routing_yaml().get("trades") or dict(_TRADE_ROUTING_DEFAULTS)

# Backward-compat module-level constants (initial load snapshot)
POSITION_ROUTING = get_position_routing()
TRANSACTION_ROUTING = get_transaction_routing()
TRADE_ROUTING = get_trade_routing()
```

### 2d. Cache invalidation helper (for MCP tool write path)

```python
def invalidate_routing_cache() -> None:
    """Force re-read on next access."""
    global _routing_cache, _routing_check_at
    _routing_cache = None
    _routing_check_at = 0.0

def _install_routing_cache(data: dict) -> None:
    """Install validated data directly into cache (R14 fix).
    
    Used by write path after os.replace() — installs the validated
    data as the new last-known-good cache instead of clearing to None.
    This preserves the last-good guarantee even if the file is
    subsequently corrupted before the next read.
    """
    global _routing_cache, _routing_mtime_ns, _routing_check_at
    import copy
    _routing_cache = copy.deepcopy(data)
    try:
        _routing_mtime_ns = _ROUTING_YAML_PATH.stat().st_mtime_ns
    except OSError:
        _routing_mtime_ns = 0
    _routing_check_at = _time.monotonic()
```

## Change 3: Update all consumers to use getter functions

### 3a. `providers/routing.py` — `_routing_for_data_type()` (line 93-99)

Change to call getter functions. This is the main gateway — most routing logic flows through it.

```python
from providers.routing_config import get_position_routing, get_transaction_routing

def _routing_for_data_type(data_type: str) -> dict[str, str]:
    data_type_lower = str(data_type or "").lower().strip()
    if data_type_lower == "transactions":
        return get_transaction_routing()
    if data_type_lower == "positions":
        return get_position_routing()
    raise ValueError(f"Unsupported data_type: {data_type}")
```

### 3b. `providers/routing.py` — `resolve_provider_token()` (line 155)

**Missed by original plan, caught by Codex.** Currently reads `TRANSACTION_ROUTING`/`POSITION_ROUTING` directly. Change to use `get_transaction_routing()`/`get_position_routing()`.

### 3c. `services/trade_execution_service.py:2924`

Change `TRADE_ROUTING.items()` → `get_trade_routing().items()`.

### 3d. `routes/provider_routing_api.py:173`

Change `POSITION_ROUTING` import → `get_position_routing`.

### 3e. `services/portfolio_scope.py` — leave as import-time

**R1 Codex caught** that `_KNOWN_AUTO_INSTITUTION_SLUGS` bakes routing keys at import time. **R2 Codex caught** that the proposed lazy function would break it — the set also includes static aliases (`csv`, `ibkr`, `manual`, etc.) and `INSTITUTION_PROVIDER_MAPPING` keys, length-sorted for prefix matching.

**Decision:** Leave `portfolio_scope.py` unchanged. It reads the module-level constants at import time, which is fine — routing key changes (adding/removing institutions) are rare and a service restart is acceptable for those. The hot-reload path matters for *value* changes (e.g., `charles_schwab: schwab` → `charles_schwab: snaptrade`), which don't affect `portfolio_scope.py` (it only uses the keys, not the values).

### 3f. `settings.py:391` — update re-exports

Keep re-exporting the module-level constants for backward compat. Also re-export the getter functions.

## Change 4: `manage_brokerage_routing` MCP tool

**New file:** `mcp_tools/brokerage_routing.py`

### 4a. Concurrency-safe read-modify-write

**R1 finding:** plain read-modify-write can lose updates and expose truncated YAML.
**R2 finding:** lock must cover the entire read-modify-write, not just the write. Same pattern as `mcp_tools/stress_scenarios.py:138`.

```python
import threading
import tempfile
import copy

_ROUTING_WRITE_LOCK = threading.Lock()

def _read_yaml_from_disk() -> dict:
    """Read routing.yaml directly from disk, bypassing the TTL cache.
    
    R12 fix: avoids cross-module global access to _routing_cache and
    avoids invalidate→reload window where concurrent readers see None.
    R13 fix: applies shared _validate_routing_data() so write path
    sees the same validated view as readers.
    On parse error, raises instead of falling back.
    """
    from providers.routing_config import _ROUTING_YAML_PATH, _validate_routing_data
    with open(_ROUTING_YAML_PATH) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError("routing.yaml root must be a mapping")
    return _validate_routing_data(data)

def _read_modify_write_routing(mutator: Callable[[dict], dict]) -> dict:
    """Atomic read-modify-write under lock.
    
    Lock covers load + mutate + save to prevent lost updates.
    Pattern: mcp_tools/stress_scenarios.py:138.
    
    R12 fix: reads file directly (not via cached _load_routing_yaml),
    so no cache invalidation needed before the read. After atomic
    write, invalidates cache so readers pick up the new file.
    No window where concurrent readers see None.
    """
    from providers.routing_config import _ROUTING_YAML_PATH, _install_routing_cache
    with _ROUTING_WRITE_LOCK:
        # Read directly from disk — bypasses cache entirely
        try:
            data = copy.deepcopy(_read_yaml_from_disk())
        except Exception:
            # File missing or malformed — refuse to write, don't fall back
            raise ValueError(
                "Cannot modify routing: config/routing.yaml is missing or malformed. "
                "Fix the file manually first."
            )
        data = mutator(data)
        # R15 fix: re-validate after mutation so backfill/cleanup
        # is applied before both disk write and cache install
        from providers.routing_config import _validate_routing_data
        data = _validate_routing_data(data)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(_ROUTING_YAML_PATH.parent),
            suffix=".yaml.tmp",
        )
        try:
            with os.fdopen(fd, "w") as f:
                yaml.safe_dump(data, f, default_flow_style=False, sort_keys=True)
            os.replace(tmp_path, str(_ROUTING_YAML_PATH))
        except Exception:
            os.unlink(tmp_path)
            raise
        # R14 fix: install validated data as new last-known-good cache
        # instead of clearing to None. Preserves last-good guarantee.
        _install_routing_cache(data)
    return data
```

Key R12 fixes:
- **No cross-module global access**: `_read_yaml_from_disk()` reads the file directly, never touches `_routing_cache`/`_routing_mtime_ns`
- **No concurrent reader window**: cache is only invalidated AFTER `os.replace()` succeeds — readers see old valid cache throughout the write
- **No silent fallback to defaults**: if file is corrupted, write path raises instead of persisting defaults over custom routing

The `set` and `remove` actions call `_read_modify_write_routing` with a mutator lambda, ensuring the entire read-modify-write is serialized.

### 4b. Actions

- **`list`** — reads current routing via getter functions, returns all 3 tables
- **`set(data_type, institution, provider)`** — validates, reads YAML, updates entry, atomic write
- **`remove(data_type, institution)`** — R16 fix: for default institutions (`charles_schwab`, `interactive_brokers`), resets to hardcoded default provider and returns `{reset_to_default: true, provider: "<default>"}`. For non-default institutions, removes entry entirely. Post-mutation validation (backfill) ensures defaults are always present.

### 4c. Provider validation (per data type)

**Codex finding:** `ALL_PROVIDERS` is wrong — transaction routing has additional tokens (`ibkr_statement`, `schwab_csv`), and trade routing shouldn't accept `plaid`.

R5 fix: `ibkr_statement` and `schwab_csv` are in `TRANSACTION_PROVIDERS` but NOT in `ALL_PROVIDERS` — `is_provider_enabled`/`is_provider_available` reject them, so routing would silently fall back. Only allow providers the runtime engine can actually honor:

```python
VALID_PROVIDERS_BY_TYPE = {
    "positions": {"plaid", "snaptrade", "schwab", "ibkr"},
    "transactions": {"plaid", "snaptrade", "ibkr_flex", "schwab"},  # no ibkr_statement/schwab_csv — not in ALL_PROVIDERS
    "trades": {"snaptrade", "schwab", "ibkr"},  # no plaid (read-only)
}
```

## Change 5: Register in `mcp_server.py`

Import near existing `manage_*` tool imports. Register with `@mcp.tool()` wrapper near other `manage_*` registrations.

**R3+R4 fix — tool surface sync:** Add `"manage_brokerage_routing"` to:
1. The `EXCLUDED_FROM_REGISTRY` set in `tests/test_tool_surface_sync.py`
2. The exclusion comment block in `services/agent_registry.py:24`

This is an admin/infra tool, not user-facing analysis — same as `manage_proxy_cache`, `manage_instrument_config`, etc.

## Change 6: Tests

### 6a. `tests/providers/test_routing_yaml.py` (new)

- Valid YAML → correct dicts for all 3 types
- Missing YAML → falls back to hardcoded defaults (not empty)
- Malformed YAML → falls back to hardcoded defaults
- Non-dict YAML root → falls back to defaults
- mtime_ns cache: unchanged file returns cached, no re-read
- mtime_ns cache: modified file triggers re-read
- TTL amortization: stat not called within TTL window
- `invalidate_routing_cache()` forces re-read

### 6b. `tests/mcp_tools/test_brokerage_routing.py` (new)

- `list` returns current routing from all 3 data types
- `set` writes correct YAML, atomic (temp file created)
- `set` validates data_type, institution, provider
- `set` rejects `plaid` for trade routing
- `remove` deletes entry, verifies fallback behavior
- Concurrent writes don't corrupt file
- R11 fix: warm cache → corrupt file → MCP set → preserves last-good routing (not defaults)
- R17 test: `remove(data_type="positions", institution="charles_schwab")` returns `{status: "success", reset_to_default: true, provider: "schwab"}` and YAML still has `charles_schwab: schwab`

### 6c. Update existing monkeypatch-based tests

**Codex finding:** tests that monkeypatch module-level constants will bypass getter-based consumers. Update:

- `tests/providers/test_routing.py:43` — monkeypatch the getter function or the YAML path
- `tests/providers/test_routing_ibkr.py:31` — also monkeypatches `routing.POSITION_ROUTING` (R2 finding)
- `tests/routes/test_provider_routing_api.py:23` — same
- `tests/services/test_trade_execution_service_preview.py:949` — same

### 6d. Consumer behavior tests

- `get_canonical_provider()` returns correct provider after YAML change
- `resolve_provider_token()` reflects YAML after change
- `partition_positions()` routes correctly after YAML change
- `partition_transactions()` routes correctly after YAML change
- `trade_execution_service` routing reflects YAML change

## Files Modified

| File | Change |
|------|--------|
| `config/routing.yaml` | **New** — routing tables |
| `providers/routing_config.py` | YAML loader + getters + defaults as fallback |
| `providers/routing.py` | `_routing_for_data_type()` + `resolve_provider_token()` use getters |
| `services/trade_execution_service.py` | `get_trade_routing()` |
| `routes/provider_routing_api.py` | `get_position_routing()` |
| `services/portfolio_scope.py` | No change (import-time is fine — only uses keys, not values) |
| `settings.py` | Re-export getters |
| `mcp_tools/brokerage_routing.py` | **New** — MCP tool with atomic writes |
| `mcp_server.py` | Tool registration |
| `tests/providers/test_routing_yaml.py` | **New** |
| `tests/mcp_tools/test_brokerage_routing.py` | **New** |
| `tests/providers/test_routing.py` | Update monkeypatches |
| `tests/providers/test_routing_ibkr.py` | Update monkeypatches |
| `tests/routes/test_provider_routing_api.py` | Update monkeypatches |
| `tests/services/test_trade_execution_service_preview.py` | Update monkeypatches |
| `tests/test_tool_surface_sync.py` | Add to `EXCLUDED_FROM_REGISTRY` |
| `services/agent_registry.py` | Add to exclusion comment block |

## Verification

1. `pytest tests/providers/` — existing routing tests + new YAML tests pass
2. `pytest tests/mcp_tools/test_brokerage_routing.py` — MCP tool works
3. `pytest tests/services/test_trade_execution_service*.py` — trade routing still works
4. `pytest tests/routes/test_provider_routing_api.py` — provider routing API still works
5. Live: `manage_brokerage_routing(action="list")` shows routing from YAML
6. Live: `manage_brokerage_routing(action="set", data_type="positions", institution="charles_schwab", provider="snaptrade")` → immediately effective, no restart
7. Live: trigger position sync → Schwab positions come from SnapTrade

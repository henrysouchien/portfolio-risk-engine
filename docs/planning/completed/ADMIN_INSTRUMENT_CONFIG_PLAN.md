# Admin MCP Tool: manage_instrument_config
**Status:** PLANNING

## Context

The YAML DB seed plan (in progress) creates `futures_contracts` and `exchange_resolution_config` tables with DB-first read paths. Currently, modifying contract specs or exchange mappings requires editing YAML and redeploying. This tool enables runtime CRUD via MCP — useful for quick fixes between deploys and essential for multi-user deployment where users lack filesystem access.

**Known limitation**: Admin DB changes are ephemeral — next `seed_all()` overwrites from YAML. For permanent changes, update YAML source and re-seed.

## Design

Single MCP tool `manage_instrument_config(action, ...)` with 6 actions:

| Action | Type | Params |
|--------|------|--------|
| `list_contracts` | READ | — |
| `get_contract` | READ | `symbol` |
| `upsert_contract` | WRITE | `symbol`, `contract_fields` |
| `delete_contract` | WRITE | `symbol` |
| `get_exchange_config` | READ | — |
| `update_exchange_section` | WRITE | `section_name`, `section_data` |

No user scoping — these are global reference tables. `@require_db` enforced.

## Implementation

### Step 1: DatabaseClient write methods

**File:** `inputs/database_client.py` (~line 1745, after existing `get_exchange_resolution_config`)

```python
def upsert_futures_contract(self, symbol: str, fields: Dict[str, Any]) -> Optional[str]:
    """UPSERT a futures contract spec. Returns symbol on success, None if table missing."""
    with self.get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO futures_contracts (symbol, multiplier, tick_size, currency, exchange,
                                               asset_class, fmp_symbol, margin_rate, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (symbol) DO UPDATE SET
                    multiplier = EXCLUDED.multiplier, tick_size = EXCLUDED.tick_size,
                    currency = EXCLUDED.currency, exchange = EXCLUDED.exchange,
                    asset_class = EXCLUDED.asset_class, fmp_symbol = EXCLUDED.fmp_symbol,
                    margin_rate = EXCLUDED.margin_rate, updated_at = NOW()
            """, (symbol, fields["multiplier"], fields["tick_size"], fields["currency"],
                  fields["exchange"], fields["asset_class"], fields.get("fmp_symbol"),
                  fields.get("margin_rate", 0.10)))
            conn.commit()
            return symbol
        except Exception as e:
            conn.rollback()
            error_msg = str(e).lower()
            if "futures_contracts" in error_msg and ("does not exist" in error_msg or "relation" in error_msg):
                return None  # table missing — graceful degrade (sentinel, not success)
            raise DatabaseError("Failed to upsert futures contract", original_error=e)

def delete_futures_contract(self, symbol: str) -> bool:
    """DELETE a futures contract. Returns True if row existed."""
    with self.get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM futures_contracts WHERE symbol = %s", (symbol,))
            deleted = cursor.rowcount > 0
            conn.commit()
            return deleted
        except Exception as e:
            conn.rollback()
            error_msg = str(e).lower()
            if "futures_contracts" in error_msg and ("does not exist" in error_msg or "relation" in error_msg):
                return False
            raise DatabaseError("Failed to delete futures contract", original_error=e)

def update_exchange_resolution_section(self, section_name: str, section_data: Any) -> bool:
    """Merge one section into the exchange_resolution_config JSONB document."""
    with self.get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("""
                UPDATE exchange_resolution_config
                SET mappings = mappings || jsonb_build_object(%s, %s::jsonb), updated_at = NOW()
                WHERE id = 1
            """, (section_name, json.dumps(section_data)))
            updated = cursor.rowcount > 0
            conn.commit()
            return updated
        except Exception as e:
            conn.rollback()
            error_msg = str(e).lower()
            if "exchange_resolution_config" in error_msg and ("does not exist" in error_msg or "relation" in error_msg):
                return False
            raise DatabaseError("Failed to update exchange resolution section", original_error=e)
```

Each write method owns its own commit/rollback (matching existing DatabaseClient write patterns like `save_workflow_action` at line 1783 and `save_target_allocations` at line 1933). Uses `with self.get_connection() as conn` internally. The MCP tool layer does NOT manage transactions — DatabaseClient does.

### Step 2: MCP tool implementation

**File (new):** `mcp_tools/instrument_config.py`

```python
"""Admin CRUD for futures contracts and exchange resolution config."""

import json, math, re
from typing import Any, Dict, Optional
from database import get_db_session
from inputs.database_client import DatabaseClient
from mcp_tools.common import handle_mcp_errors, require_db

VALID_ASSET_CLASSES = {"equity_index", "fixed_income", "metals", "energy", "agricultural", "fx"}
VALID_EXCHANGE_SECTIONS = {
    "mic_to_fmp_suffix", "us_exchange_mics", "minor_currencies",
    "currency_aliases", "currency_to_fx_pair", "currency_to_usd_fallback",
    "mic_to_exchange_short_name",
}
EPHEMERAL_NOTE = "Admin DB changes are ephemeral — next seed_all() overwrites from YAML."

def _clear_instrument_caches():
    try:
        from services.cache_adapters import InstrumentConfigLRUCacheAdapter
        InstrumentConfigLRUCacheAdapter().clear_cache()
    except Exception:
        pass

def _validate_contract_fields(fields):
    # Required: multiplier, tick_size, currency, exchange, asset_class
    # Optional: fmp_symbol, margin_rate (default 0.10)
    # Positive number checks for multiplier, tick_size, margin_rate
    # asset_class must be in VALID_ASSET_CLASSES
    ...

@handle_mcp_errors
@require_db
def manage_instrument_config(action, symbol=None, contract_fields=None,
                              section_name=None, section_data=None):
    action = str(action or "").strip().lower()
    # Dispatch to action handlers
    if action == "list_contracts": return _list_contracts()
    elif action == "get_contract": return _get_contract(symbol)
    elif action == "upsert_contract": return _upsert_contract(symbol, contract_fields)
    elif action == "delete_contract": return _delete_contract(symbol)
    elif action == "get_exchange_config": return _get_exchange_config()
    elif action == "update_exchange_section": return _update_exchange_section(section_name, section_data)
    else: return {"status": "error", "error": f"Unknown action: {action}. Valid: list_contracts, get_contract, upsert_contract, delete_contract, get_exchange_config, update_exchange_section"}
```

**Action handlers** (all private, within module):

- `_list_contracts()` — DB read → `{"status": "success", "contracts": [...], "count": N}`
- `_get_contract(symbol)` — validate symbol, DB read → single contract or `not_found`
- `_upsert_contract(symbol, fields)` — validate both, DB upsert + commit, clear caches → success + `EPHEMERAL_NOTE`
- `_delete_contract(symbol)` — validate, DB delete + commit, clear caches → success or `not_found`
- `_get_exchange_config()` — DB read → config dict with section list, or `not_found`
- `_update_exchange_section(section_name, section_data)` — validate section name, DB JSONB merge + commit, clear caches → success + `EPHEMERAL_NOTE`

Handle `contract_fields` arriving as JSON string (MCP may serialize dicts): `if isinstance(contract_fields, str): contract_fields = json.loads(contract_fields)`. Same for `section_data`.

**Per-section schema validation for `update_exchange_section`**: Downstream consumers assume specific shapes. Validate before writing:

| Section | Required shape | Consumer |
|---------|---------------|----------|
| `currency_aliases` | `dict[str, str]` | `ticker_resolver.py:68` |
| `minor_currencies` | `dict[str, {"base_currency": str, "divisor": int}]` | `ticker_resolver.py:113` |
| `us_exchange_mics` | `list[str]` (iterable) | `ticker_resolver.py:257` |
| `currency_to_fx_pair` | `dict[str, str \| {"symbol": str, "inverted": bool}]` | `fmp/fx.py:25-35` |
| `currency_to_usd_fallback` | `dict[str, float]` | `fmp/fx.py:27` |
| `mic_to_fmp_suffix` | `dict[str, str]` | `ticker_resolver.py` |
| `mic_to_exchange_short_name` | `dict[str, str]` | `ticker_resolver.py` |

Implement `_validate_exchange_section(section_name, section_data)` that checks the type and structure for each section. Return a clear error if shape doesn't match (e.g., "minor_currencies entries must have 'base_currency' (str) and 'divisor' (int) keys").

### Step 3: MCP registration

**File:** `mcp_server.py`

Import (near line 55, with other mcp_tools imports):
```python
from mcp_tools.instrument_config import manage_instrument_config as _manage_instrument_config
```

Thin wrapper (after audit tools, ~line 595):
```python
@mcp.tool()
def manage_instrument_config(
    action: str,
    symbol: str | None = None,
    contract_fields: dict | None = None,
    section_name: str | None = None,
    section_data: Any = None,
) -> dict:
    """Admin tool for futures contract specs and exchange resolution config.

    Actions: list_contracts, get_contract, upsert_contract, delete_contract,
    get_exchange_config, update_exchange_section.
    """
    return _manage_instrument_config(
        action=action, symbol=symbol, contract_fields=contract_fields,
        section_name=section_name, section_data=section_data,
    )
```

### Step 4: Tests

**File (new):** `tests/mcp_tools/test_instrument_config.py`

~22 tests following `test_audit.py` pattern (monkeypatch `get_db_session`, `DatabaseClient`, `is_db_available`):

| Test | Validates |
|------|-----------|
| `test_list_contracts_success` | Returns contract list with correct structure |
| `test_list_contracts_empty` | Returns count: 0 when no contracts |
| `test_get_contract_found` | Returns single contract |
| `test_get_contract_not_found` | Returns status: not_found |
| `test_get_contract_requires_symbol` | Error when symbol missing |
| `test_upsert_contract_success` | DB method called, cache cleared, ephemeral note |
| `test_upsert_validates_asset_class` | Rejects invalid asset_class |
| `test_upsert_validates_positive_multiplier` | Rejects zero/negative |
| `test_upsert_validates_positive_tick_size` | Rejects zero/negative |
| `test_upsert_validates_symbol_format` | Rejects lowercase/empty |
| `test_upsert_requires_fields` | Error when contract_fields missing |
| `test_upsert_requires_required_fields` | Error when required keys missing |
| `test_upsert_handles_json_string_fields` | Parses JSON string contract_fields |
| `test_delete_contract_success` | Returns success, cache cleared |
| `test_delete_contract_not_found` | Returns not_found |
| `test_get_exchange_config_success` | Returns config with sections list |
| `test_get_exchange_config_not_seeded` | Returns not_found |
| `test_update_exchange_section_success` | DB method called, cache cleared |
| `test_update_exchange_section_invalid_name` | Rejects unknown section |
| `test_update_exchange_section_requires_data` | Error when data missing |
| `test_update_exchange_section_not_seeded` | Returns not_found when no row exists (rowcount=0) |
| `test_update_exchange_section_validates_shape` | Rejects malformed section data (e.g., non-dict for currency_aliases) |
| `test_invalid_action` | Returns error with valid actions list |
| `test_write_ops_clear_caches` | Monkeypatch `_clear_instrument_caches`, verify called |
| `test_mcp_server_registers_tool` | Verify `manage_instrument_config` registered in mcp_server.py |

## Dependencies

This plan depends on the YAML DB seed plan (`YAML_DB_SEED_PLAN.md`) which creates:
- `futures_contracts` table
- `exchange_resolution_config` table
- `DatabaseClient.get_futures_contracts()` read method
- `DatabaseClient.get_exchange_resolution_config()` read method
- `InstrumentConfigLRUCacheAdapter` in `services/cache_adapters.py`

The seed plan must be implemented first. This tool adds write methods + MCP exposure on top.

## Files Changed

| File | Change |
|------|--------|
| `mcp_tools/instrument_config.py` **(new)** | Tool implementation (~120 lines) |
| `inputs/database_client.py` | 3 write methods (~35 lines) |
| `mcp_server.py` | Import + `@mcp.tool()` wrapper (~20 lines) |
| `tests/mcp_tools/test_instrument_config.py` **(new)** | ~22 tests |

## Verification

1. `python3 -m pytest tests/mcp_tools/test_instrument_config.py -x -v` — all new tests pass
2. `python3 -m pytest tests/mcp_tools/ -x -q` — existing MCP tool tests unaffected
3. `python3 -m pytest tests/ -x -q --timeout=120` — full suite no regressions

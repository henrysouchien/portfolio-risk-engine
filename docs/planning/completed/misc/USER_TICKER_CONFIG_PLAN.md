# Per-User Ticker Configuration (`user_ticker_config`)
**Status:** DONE (Phase 1) | **Commit:** `ba827e05`

## Context

FMP ticker mappings come from live brokerage position data (`fmp_ticker` field) and cash proxies are global (`cash_proxies` DB table / `cash_map.yaml`). Users can't customize these at runtime. In multi-user deployment, different users need different mappings (e.g., user A maps `AT → AT.L`, user B doesn't). This table adds per-user CRUD for FMP ticker aliases and (later) cash proxy preferences.

**Scope**: Phase 1 delivers FMP alias overrides + the CRUD tool. Cash proxy overrides deferred to Phase 2 (separate follow-up) because they require threading through `standardize_portfolio_input()` — a larger change for a niche feature.

## Design

Single action-dispatched MCP tool `manage_ticker_config(action, ...)` with 4 actions, user-scoped via `resolve_user_email()`. One table with `config_type` discriminator.

| Action | Params | Description |
|--------|--------|-------------|
| `list` | `config_type?` | List all user overrides, optionally filtered |
| `set` | `config_type`, `source_key`, `resolved_value`, `notes?` | Upsert override |
| `get` | `config_type`, `source_key` | Get single override |
| `delete` | `config_type`, `source_key` | Delete override |

Valid `config_type` values: `fmp_alias` (Phase 1), `cash_proxy` (Phase 2 — stored but returns `not_implemented` warning until wired).

**Integration**: In `_load_portfolio_for_analysis()` (`mcp_tools/risk.py`, line ~427), after `portfolio_data` is built from positions, merge user FMP alias overrides on top of `portfolio_data.fmp_ticker_map`. User overrides take precedence. Wrapped in try/except — non-fatal if DB unavailable.

## Implementation

### Step 1: Migration

**New file:** `database/migrations/20260311_add_user_ticker_config.sql`

```sql
CREATE TABLE IF NOT EXISTS user_ticker_config (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    config_type VARCHAR(20) NOT NULL,        -- 'fmp_alias' or 'cash_proxy'
    source_key VARCHAR(50) NOT NULL,         -- ticker (e.g. 'AT') or currency (e.g. 'USD')
    resolved_value VARCHAR(50) NOT NULL,     -- FMP symbol (e.g. 'AT.L') or proxy ETF (e.g. 'BIL')
    notes TEXT,                              -- optional user-provided reason
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (user_id, config_type, source_key)
);

CREATE INDEX IF NOT EXISTS idx_user_ticker_config_user_type
    ON user_ticker_config(user_id, config_type);
```

### Step 2: DatabaseClient methods

**File:** `inputs/database_client.py` (after existing `get_target_allocations`/`save_target_allocations`)

Three methods following existing user-scoped patterns (`with self.get_connection() as conn`, commit/rollback, graceful table-missing degradation):

```python
def get_user_ticker_configs(self, user_id: int, config_type: str | None = None) -> list[dict]:
    """Get user ticker configs. Returns list of {config_type, source_key, resolved_value, notes}.

    Query: SELECT config_type, source_key, resolved_value, notes
           FROM user_ticker_config WHERE user_id = %s [AND config_type = %s]
           ORDER BY config_type, source_key
    Returns empty list if table missing or no rows.
    """

def upsert_user_ticker_config(self, user_id: int, config_type: str, source_key: str,
                               resolved_value: str, notes: str | None = None) -> bool:
    """INSERT INTO user_ticker_config (user_id, config_type, source_key, resolved_value, notes, updated_at)
       VALUES (%s, %s, %s, %s, %s, NOW())
       ON CONFLICT (user_id, config_type, source_key) DO UPDATE SET
           resolved_value = EXCLUDED.resolved_value, notes = EXCLUDED.notes, updated_at = NOW()
       Returns True on success, False if table missing (graceful degrade).
    """

def delete_user_ticker_config(self, user_id: int, config_type: str, source_key: str) -> bool:
    """DELETE FROM user_ticker_config WHERE user_id = %s AND config_type = %s AND source_key = %s
       Returns True if row existed (rowcount > 0).
    """
```

All three own their own commit/rollback via `with self.get_connection() as conn`. Read-side table-missing errors call `conn.rollback()` before returning empty list (to avoid leaving pooled connections in aborted state). Write-side table-missing errors return `False` (matching `upsert_futures_contract` sentinel pattern). `_set_config` must check the `False` return and raise `ValueError("user_ticker_config table unavailable")` instead of reporting success.

### Step 3: MCP tool

**New file:** `mcp_tools/user_overrides.py`

Follows `mcp_tools/allocation.py` (user-scoped CRUD) + `mcp_tools/instrument_config.py` (action-dispatched) patterns.

```python
"""Per-user ticker configuration overrides (FMP aliases, cash proxies)."""

from __future__ import annotations
import re
from typing import Any

from database import get_db_session, is_db_available
from inputs.database_client import DatabaseClient
from mcp_tools.common import handle_mcp_errors, require_db
from settings import resolve_user_email, format_missing_user_error
from utils.user_resolution import resolve_user_id as _resolve_user_id

VALID_CONFIG_TYPES = ("fmp_alias", "cash_proxy")
VALID_ACTIONS = ("list", "set", "get", "delete")
# Config types that have runtime integration wired up
_WIRED_CONFIG_TYPES = {"fmp_alias"}

_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9._:-]{0,49}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")

@handle_mcp_errors
@require_db
def manage_ticker_config(
    action: Any,
    config_type: Any = None,
    source_key: Any = None,
    resolved_value: Any = None,
    notes: Any = None,
) -> dict:
    """Per-user ticker configuration overrides (FMP aliases, cash proxies)."""
    # Normalize action
    normalized_action = str(action or "").strip().lower()
    if normalized_action not in VALID_ACTIONS:
        raise ValueError(f"Unknown action: {normalized_action}. Valid: {', '.join(VALID_ACTIONS)}")

    # Dispatch
    if normalized_action == "list": return _list_configs(config_type)
    if normalized_action == "set": return _set_config(config_type, source_key, resolved_value, notes)
    if normalized_action == "get": return _get_config(config_type, source_key)
    if normalized_action == "delete": return _delete_config(config_type, source_key)
```

**Validation helpers** (private, within module):
- `_validate_config_type(config_type)` — must be in `VALID_CONFIG_TYPES`
- `_validate_source_key(config_type, source_key)` — uppercase + strip; for `fmp_alias` must match `_TICKER_RE`; for `cash_proxy` must match `_CURRENCY_RE` (3-letter ISO)
- `_validate_resolved_value(config_type, resolved_value)` — uppercase, strip, non-empty; for `fmp_alias` must match `_TICKER_RE` (same symbol regex as source_key — prevents persisting unusable FMP symbols); for `cash_proxy` must match `_TICKER_RE` (ETF ticker)

**Phase 1 `cash_proxy` handling**: `set` action for `cash_proxy` type stores the entry but returns a `warning` field: `"cash_proxy overrides are stored but not yet applied at runtime (Phase 2)"`. `list`/`get`/`delete` work normally for all types. This lets users pre-configure while making the limitation explicit.

**Action handlers** (all private, resolve user internally):
- `_list_configs(config_type)` — optional filter, returns `{status, configs: [...], count}`
- `_set_config(config_type, source_key, resolved_value, notes)` — validate all, upsert, return `{status: success, config_type, source_key, resolved_value}`
- `_get_config(config_type, source_key)` — validate, query, return entry or `{status: not_found}`
- `_delete_config(config_type, source_key)` — validate, delete, return `{deleted: True}` or `{status: not_found}`

Each handler calls `resolve_user_email(None)` → `_resolve_user_id(user)` → `DatabaseClient` method inside `get_db_session()`.

### Step 4: FMP alias merge in `_load_portfolio_for_analysis()`

**File:** `mcp_tools/risk.py`, after line 427 (`portfolio_data.user_id = user_id`)

```python
# 2b. Merge user FMP ticker overrides (user takes precedence over position data)
if is_db_available():
    try:
        from database import get_db_session
        from inputs.database_client import DatabaseClient

        with get_db_session() as conn:
            db = DatabaseClient(conn)
            user_fmp_configs = db.get_user_ticker_configs(user_id, config_type="fmp_alias")
        if user_fmp_configs:
            fmp_map = dict(portfolio_data.fmp_ticker_map or {})
            for entry in user_fmp_configs:
                fmp_map[entry["source_key"]] = entry["resolved_value"]
            portfolio_data.fmp_ticker_map = fmp_map
    except Exception:
        pass  # Non-fatal: position-data fmp_ticker_map still works
```

Note: `is_db_available` is already imported at the top of `risk.py` (line 32). `get_db_session` and `DatabaseClient` are imported locally inside the try block because they are NOT top-level imports in this file — the existing code only uses them indirectly via `PortfolioRepository` (line 477). Local imports match the pattern at line 449 (`from core.proxy_builder import ...`) and line 487 (`from brokerage.futures import ...`).

**Factor proxy staleness**: The merge happens before `ensure_factor_proxies()` (line 436), but `ensure_factor_proxies()` uses `tickers` from `portfolio_data.portfolio_input.keys()` — the raw position keys, not the FMP-resolved keys. So factor proxies are keyed by native ticker (e.g., `AT`), not the FMP alias (`AT.L`). The FMP alias only affects pricing/returns lookups downstream (via `select_fmp_symbol()`), not factor proxy generation. No proxy invalidation needed — the proxy is for the conceptual holding `AT`, and the FMP alias just tells the system where to get price data for it. If a user changes an alias for a ticker that already has saved proxies, the proxies remain valid (they're about the asset, not the data source).

### Step 5: MCP registration

**File:** `mcp_server.py`

Import (near line 58, with other mcp_tools imports):
```python
from mcp_tools.user_overrides import manage_ticker_config as _manage_ticker_config
```

Thin wrapper (after `manage_instrument_config`, ~line 608):
```python
@mcp.tool()
def manage_ticker_config(
    action: str,
    config_type: Optional[str] = None,
    source_key: Optional[str] = None,
    resolved_value: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict:
    """Per-user ticker overrides (FMP aliases like AT→AT.L, cash proxies like USD→BIL).

    Actions: list, set, get, delete.
    config_type: "fmp_alias" or "cash_proxy".
    """
    return _manage_ticker_config(
        action=action, config_type=config_type, source_key=source_key,
        resolved_value=resolved_value, notes=notes,
    )
```

### Step 6: Tests

**New file:** `tests/mcp_tools/test_user_overrides.py`

~22 tests following `test_instrument_config.py` pattern. Setup: monkeypatch `DATABASE_URL` env var, `database.is_db_available` → `True`, and patch `resolve_user_email` / `_resolve_user_id` on `mcp_tools.user_overrides` module (matching `test_audit.py` pattern). For the MCP tool tests, patch `get_db_session` on `mcp_tools.user_overrides` module. For risk loader integration tests, patch at source modules (`database.get_db_session`, `inputs.database_client.DatabaseClient`) since `_load_portfolio_for_analysis()` uses local imports:

| Test | Validates |
|------|-----------|
| `test_set_fmp_alias_success` | Upsert called with correct args, returns True, response has status: success |
| `test_set_fmp_alias_overwrites` | Second set wins (upsert semantics) |
| `test_set_cash_proxy_stores_with_warning` | Cash proxy upsert works but response includes `warning` field about Phase 2 |
| `test_set_rejects_invalid_config_type` | Error on unknown type |
| `test_set_rejects_missing_source_key` | Error when source_key empty/None |
| `test_set_rejects_missing_resolved_value` | Error when resolved_value empty/None |
| `test_set_validates_resolved_value_format` | Rejects invalid FMP symbol (e.g., spaces, special chars) |
| `test_set_table_unavailable` | Upsert returns False → error "table unavailable" (not false success) |
| `test_list_all_configs` | Returns both fmp_alias and cash_proxy entries |
| `test_list_filtered_by_type` | config_type filter returns only requested type |
| `test_list_empty` | Returns count: 0 |
| `test_get_existing` | Returns single entry |
| `test_get_not_found` | Returns status: not_found |
| `test_delete_existing` | Returns deleted: True |
| `test_delete_not_found` | Returns status: not_found |
| `test_invalid_action` | Error with valid actions list |
| `test_source_key_uppercase` | `at` stored as `AT` |
| `test_cash_proxy_validates_currency` | Rejects non-3-letter-alpha strings (e.g., "USDX", "us") |
| `test_risk_loader_merges_fmp_overrides` | Override appears in portfolio_data.fmp_ticker_map after `_load_portfolio_for_analysis()` |
| `test_risk_loader_override_precedence` | User override `AT→AT.L` wins over position-data `AT→AT.VI` |
| `test_risk_loader_nonfatal_on_db_error` | DB raises in merge block, fmp_ticker_map unchanged (try/except works) |
| `test_mcp_server_registers_tool` | String check on mcp_server.py for import + function name |

## Files Changed

| File | Change |
|------|--------|
| `database/migrations/20260311_add_user_ticker_config.sql` | **New** — migration |
| `inputs/database_client.py` | 3 methods (~40 lines) |
| `mcp_tools/user_overrides.py` | **New** — tool (~150 lines) |
| `mcp_tools/risk.py` | Merge overrides in `_load_portfolio_for_analysis()` (~12 lines) |
| `mcp_server.py` | Import + registration (~15 lines) |
| `tests/mcp_tools/test_user_overrides.py` | **New** — ~22 tests |

## Not in scope (Phase 2 — separate follow-up)

Cash proxy override runtime wiring (stored in Phase 1, but not applied until this). This is a larger change because cash proxy detection is deeply embedded:

**Injection points** (both needed):
1. **Position build stage**: `PositionsData.to_portfolio_data()` / `_load_cash_proxy_map()` (`portfolio_risk_engine/data_objects.py`, line ~485) — this is where `CUR:USD → SGOV` proxy mapping happens, BEFORE `standardize_portfolio_input()`. The override must replace the proxy ETF at this stage.
2. **Cash detection stage**: `standardize_portfolio_input()` (`portfolio_risk_engine/portfolio_config.py`, line ~106) uses global `_LazyCashPositions` singleton. Override needs per-request cash set. Direct callers (all need optional kwarg): `config_adapters.py:81`, `portfolio_config.py:498`, `core/portfolio_analysis.py:145`, `services/optimization_service.py:380`, `core/risk_orchestration.py:342`, `portfolio_risk_engine/optimization.py:98+186`, `performance_analysis.py:103`, `portfolio_risk_score.py:1841`, `scenario_analysis.py:135`.

**PortfolioData changes**: Add `cash_proxy_overrides: Optional[Dict[str, str]]` field + propagate through constructor, `from_yaml()`, `from_holdings()`, `to_yaml()`, `create_temp_file()` serialization methods. (Note: `to_dict()`/`from_dict()` belong to `RiskLimitsData`, not `PortfolioData`.)

**Approach**: Add optional `cash_proxy_overrides` kwarg to `standardize_portfolio_input()`. All ~10 call sites pass `None` by default (no behavior change). Only the MCP tool path (via `config_from_portfolio_data()`) passes user overrides.

**Additional Phase 2 details**:
- `_generate_cache_key()` (`data_objects.py:981`) must include `cash_proxy_overrides` — otherwise different override configs collide in `portfolio_service.py:656` cache.
- Temp-file/YAML paths (`portfolio_service.py:664` → `create_temp_file()`, `portfolio_config.py:466+498` → `load_portfolio_config()`) must also load and pass overrides, not just `config_from_portfolio_data()`.
- Remove `warning` field from `set` response for `cash_proxy` type once wired
- Separate commit after Phase 1 is validated

## Verification

1. `psql -f database/migrations/20260311_add_user_ticker_config.sql` — verify table created
2. `python3 -m pytest tests/mcp_tools/test_user_overrides.py -x -v` — all new tests pass
3. `python3 -m pytest tests/mcp_tools/ -x -q` — existing MCP tool tests unaffected
4. `python3 -m pytest tests/ -x -q --timeout=120` — full suite no regressions
5. Live test via MCP: `manage_ticker_config(action="set", config_type="fmp_alias", source_key="AT", resolved_value="AT.L")` then verify with `get_risk_analysis` that the override is applied

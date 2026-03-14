# Plan: Phase 1C Backend Hardening (1C.1 + 1C.2)

## Context

Two open bugs in `docs/planning/BUGS.md`:

**Bug 01 — PG "too many clients" on cash detection**: Six production callers query the `cash_proxies`/`cash_aliases` DB tables for data that is static and identical to `config/cash_map.yaml`. Investigation showed the code already uses the connection pool correctly — the error occurs when PG's global `max_connections` is saturated by other operations. Fix: eliminate the DB dependency entirely. Cash mappings are universal (not per-user), never change at runtime, and the YAML file is the canonical source. All callers already have YAML fallback that produces identical results.

**Bug 02 — Pandas FutureWarning**: `portfolio_risk.py:333` uses `.fillna(0.0)` on an object-dtype Series. Pandas 2.x deprecated implicit downcasting. This repo pins `pandas>=3.0.0`, so `infer_objects(copy=False)` is itself deprecated. Use `pd.to_numeric()` instead.

**1C.4 — Frontend logging userId fix**: Already implemented (verified in `routes/frontend_logging.py` lines 404-420, all 7 tests pass). No work needed.

## All Production Callers of `cash_proxies`/`cash_aliases` Tables

| # | File | Function | DB Method | Already in YAML fallback? |
|---|------|----------|-----------|--------------------------|
| 1 | `portfolio_risk_engine/portfolio_config.py` | `get_cash_positions()` | `get_cash_mappings()` | Yes |
| 2 | `services/security_type_service.py` | `_classify_cash_proxies()` | `get_cash_mappings()` | Yes |
| 3 | `inputs/portfolio_manager.py` | `_load_cash_mapping()` | `get_cash_mappings()` via repository | Yes |
| 4 | `inputs/portfolio_repository.py` | `load_full_portfolio()` | `get_cash_mappings()` | Yes (passes to #3) |
| 5 | `portfolio_risk_engine/data_objects.py` | `_load_cash_proxy_map()` | `get_cash_mappings()` | Yes |
| 6 | `services/returns_service.py` | `_is_cash_proxy()` | `get_cash_mappings()` | Yes |
| 7 | `core/factor_intelligence.py` | `load_cash_proxies()` | `get_cash_proxies()` (different method) | Yes |

Admin-only callers (non-production):

| # | File | Function | DB Method |
|---|------|----------|-----------|
| A1 | `admin/manage_reference_data.py` | `list_cash_mappings()` | `get_cash_mappings()` |
| A2 | `admin/verify_proxies.py` | proxy verification | `get_cash_mappings()` |
| A3 | `admin/migrate_reference_data.py` | `migrate_cash_mappings()` | writes to DB |

## Changes

### Step 1: `portfolio_risk_engine/portfolio_config.py` — YAML-only cash detection

Remove the DB try block in `get_cash_positions()` (lines 72-91). Go straight to YAML. Keep the hardcoded fallback.

**After**:
```python
    try:
        yaml_path = resolve_config_path("cash_map.yaml")
        with open(yaml_path, "r") as f:
            cash_map = yaml.safe_load(f)
            return set(cash_map.get("proxy_by_currency", {}).values())
    except FileNotFoundError:
        print("⚠️ cash_map.yaml not found, using default cash proxies")
        return {"SGOV", "IBGE.L", "ERNS.L", "CASH", "USD"}
```

Remove: `import time`, DB imports, DB try block, logging calls. Check whether `log_critical_alert` and `log_service_health` imports (line 31, 33) are used elsewhere in this file before removing them.

Update the docstring (lines 49-67) to remove the "Resolution order" section that describes DB-first behavior.

### Step 2: `services/security_type_service.py` — YAML-only in `_classify_cash_proxies()`

Remove the DB try block (lines 1390-1395). Go straight to YAML. Keep TTL cache.

**After**:
```python
            try:
                yaml_path = resolve_config_path("cash_map.yaml")
                with open(yaml_path, "r") as f:
                    cash_map = yaml.safe_load(f)
            except FileNotFoundError:
                portfolio_logger.warning("cash_map.yaml not found, using default cash proxy mappings")
                cash_map = {
                    "proxy_by_currency": {"USD": "SGOV", "EUR": "IBGE.L", "GBP": "ERNS.L"}
                }
```

Check whether `get_db_session` and `DatabaseClient` imports in this file are used elsewhere. Do NOT remove if other methods still use them.

### Step 3: `inputs/portfolio_manager.py` — YAML-only in `_load_cash_mapping()`

Simplify `_load_cash_mapping()` (lines 604-632). Remove the DB re-query path and the `preloaded_cash_map`/`preloaded_error` parameters.

**After**:
```python
    def _load_cash_mapping(self) -> Dict[str, Any]:
        try:
            yaml_path = resolve_config_path("cash_map.yaml")
            with open(yaml_path, "r", encoding="utf-8") as handle:
                return yaml.safe_load(handle)
        except FileNotFoundError:
            portfolio_logger.warning("⚠️ cash_map.yaml not found, using default USD mapping")
            return {
                "proxy_by_currency": {"USD": "SGOV"},
                "alias_to_currency": {"CUR:USD": "USD", "CASH": "USD"},
            }
```

Update the call site at line 320-324:
```python
# Before:
cash_map = self._load_cash_mapping(
    preloaded_cash_map=portfolio_payload.get("cash_mappings"),
    preloaded_error=portfolio_payload.get("cash_mappings_error"),
)
# After:
cash_map = self._load_cash_mapping()
```

### Step 4: `inputs/portfolio_repository.py` — Remove cash_mappings from payload

Remove the `cash_mappings`/`cash_mappings_error` block in `load_full_portfolio()` (lines 104-118) and the two dict keys from the return.

Remove `PortfolioRepository.get_cash_mappings()` method (lines 168-170) — no longer called.

### Step 5: `portfolio_risk_engine/data_objects.py` — YAML-only in `_load_cash_proxy_map()`

Remove DB path (lines 51-67). Go straight to YAML. Keep `_db_loader` injection for tests if any tests use it; otherwise remove `inject_cash_db_loader()` too.

**After**:
```python
def _load_cash_proxy_map() -> Tuple[Dict[str, str], Dict[str, str]]:
    try:
        yaml_path = resolve_config_path("cash_map.yaml")
        with open(yaml_path, "r") as f:
            cash_map = yaml.safe_load(f) or {}
            return (
                cash_map.get("proxy_by_currency", {}),
                cash_map.get("alias_to_currency", {}),
            )
    except Exception as e:
        logger.warning("Cash proxy map: YAML unavailable (%s), using hardcoded", e)

    return ({"USD": "SGOV"}, {"CUR:USD": "USD"})
```

Check callers of `set_db_loader()` (line 37) and `_db_loader` (line 34) — if only used in tests or the repository pipeline that's being removed, remove them along with the `Callable` import. If still called elsewhere, keep but document they're unused in production.

### Step 6: `services/returns_service.py` — YAML-only in `_is_cash_proxy()`

Remove DB path (lines 523-533). Go straight to YAML.

**After**:
```python
    def _is_cash_proxy(self, ticker: str) -> bool:
        try:
            yaml_path = resolve_config_path("cash_map.yaml")
            with open(yaml_path, "r") as f:
                cash_map = yaml.safe_load(f) or {}
                proxy_tickers = set(cash_map.get("proxy_by_currency", {}).values())
                return ticker in proxy_tickers
        except Exception:
            common_cash_proxies = {"SGOV", "IBGE.L", "ERNS.L"}
            return ticker in common_cash_proxies
```

Remove the `DatabaseClient` and `get_db_session` imports if no longer used elsewhere in this file.

### Step 7: `core/factor_intelligence.py` — YAML-only in `load_cash_proxies()`

Remove DB path (lines 141-148). Go straight to YAML. This uses `get_cash_proxies()` (a separate DatabaseClient method), not `get_cash_mappings()`.

**IMPORTANT**: The existing YAML fallback in `load_cash_proxies()` has a schema mismatch — it looks for top-level `USD` or `cash_proxies` key, but the actual YAML uses `proxy_by_currency`. Fix this by using the canonical schema:

**After**:
```python
@lru_cache(maxsize=DATA_LOADER_LRU_SIZE)
def load_cash_proxies() -> Tuple[Dict[str, str], str]:
    try:
        import yaml
        yaml_path = resolve_config_path("cash_map.yaml")
        if yaml_path.exists():
            with open(yaml_path, 'r') as f:
                data = yaml.safe_load(f) or {}
            proxy = data.get("proxy_by_currency", {})
            if proxy:
                return {k: str(v) for k, v in proxy.items()}, 'yaml'
    except Exception as e:
        log_portfolio_operation("cash_proxy_loader_yaml_failed", {"error": str(e)}, execution_time=0)

    return ({"USD": "SGOV"}, 'hardcoded')
```

Add a unit test for `load_cash_proxies()` that verifies it correctly reads `proxy_by_currency` from the canonical YAML schema (not the old top-level format).

Remove `DatabaseClient` and `get_db_session` imports if no longer used elsewhere in this file.

### Step 8: Dead code cleanup

**`inputs/database_client.py`**:
- Remove `get_cash_mappings()` method (lines 3767-3815)
- Remove `get_cash_proxies()` method (lines 2304-2319) — no production callers after Step 7
- Remove `update_cash_proxy()` and other cash write methods (tables are being dropped)

**`admin/migrate_reference_data.py`** — Remove `migrate_cash_mappings()` function and its call at line 357. Also update `verify_migration()` (line 309) which calls `db_client.get_cash_mappings()` — remove the cash mappings verification block or convert to YAML-based.

**`admin/manage_reference_data.py`** — Remove `list_cash_mappings()` function (line 57) and its call sites (lines 516, 526). Remove `sync_cash_from_yaml()` (line 128) and its call site (line 517-518). Remove or stub all cash-related CLI subcommands: `cash add`, `cash list`, `cash sync-from-yaml`, `cash-alias add`, `cash-alias list`.

**`admin/verify_proxies.py`** — Update cash proxy section (lines 204-215) to read from YAML instead of `db.get_cash_mappings()`. Update top-of-file docstring (line 12) to remove `cash_proxies` table reference.

Update stale top-of-file docstrings/help text in:
- `admin/migrate_reference_data.py` line 5: Remove "Cash mappings from cash_map.yaml" from description
- `admin/manage_reference_data.py` lines 5, 17: Remove cash mapping references from help text

### Step 9: Test updates

**`tests/inputs/test_portfolio_repository.py`** — `test_load_full_portfolio_uses_one_session_and_preserves_cash_mapping_fallback_signal` (line 142):
- Remove `get_cash_mappings` from the mock `DatabaseClient`
- Remove assertions on `payload["cash_mappings"]` and `payload["cash_mappings_error"]` (lines 198-199)
- Remove `"cash_mappings"` from `call_order` assertion (line 207)
- Rename test to reflect it no longer tests cash mapping fallback

**`tests/inputs/test_portfolio_assembler.py`**:
- `_build_full_portfolio_payload()` (line 12): Remove `cash_mappings` and `cash_mappings_error` keys
- `test_load_portfolio_from_database_uses_yaml_cash_mapping_fallback` (line 382): Update — manager now always loads from YAML. Remove `cash_mappings=None` / `cash_mappings_error=...` args. Remove assertion that `repository.get_cash_mappings` is not called (method no longer exists). Test should verify YAML is loaded (monkeypatch `resolve_config_path`).

**`tests/utils/test_final_status.py`** (line 71): Remove the `cash_mappings` check block (line 71-74). Also remove the `"cash_mappings": False` entry from the `issues_resolved` dict (line 31) so the summary count stays accurate.

**`tests/utils/show_db_data.py`** (line 441): Remove the cash mappings display section.

**`tests/services/test_cache_control.py`**: Keep `clear_cash_mappings_cache` references — TTL cache still exists.

### Step 10: Pandas FutureWarning fix

**`portfolio_risk_engine/portfolio_risk.py:333`**:

This repo pins `pandas>=3.0.0`. In pandas 3.x, `infer_objects(copy=False)` itself emits a deprecation warning on the `copy` parameter. Use explicit numeric coercion instead:

```python
# Before:
idio_var_series = pd.Series(idio_var_dict).reindex(w.index).fillna(0.0)
# After:
idio_var_series = pd.to_numeric(pd.Series(idio_var_dict).reindex(w.index), errors="coerce").fillna(0.0)
```

### Step 11: Update BUGS.md

Archive both bugs to `completed/BUGS_COMPLETED.md` (per BUGS.md contract: "Track only active bugs in this file. Resolved bugs archived in completed/BUGS_COMPLETED.md"). Update the "Current Status" count from 2 to 0. Include root cause notes:
- Bug 01: "Connection pool was correct; removed unnecessary DB dependency for static data"
- Bug 02: "Used pd.to_numeric() for pandas 3.x compatibility"

### Step 12: Docstring / comment cleanup

Update stale DB-first references:
- `portfolio_risk_engine/portfolio_config.py` lines 41, 49-67: Remove decorator comment and "Resolution order" docstring describing DB-first behavior
- `portfolio_risk_engine/data_objects.py` line 43: Update `_load_cash_proxy_map()` docstring (remove "3-tier fallback" / DB references)
- `core/factor_intelligence.py` lines 136, 556, 609: Update `load_cash_proxies()` docstring and "DB-first" comments
- `services/security_type_service.py` lines 54, 139, 848, 1360: Update hardcoded `SGOV/ESTR/IB01` examples and DB-first wording in docstrings/comments
- `config/cash_map.yaml` header comments: Update to reflect YAML is now the primary (not fallback) source
- `admin/README.md` lines 61, 88, 441: Remove cash_proxies table references and cash CLI examples
- `Readme.md` lines 1680, 1696, 1729: Remove DB-first cash mapping references
- `docs/guides/usage_notes.md` line 685: Remove DB-first cash mapping references
- `docs/guides/DEVELOPER_ONBOARDING.md` line 320: Remove cash DB references
- `docs/reference/DATABASE_REFERENCE.md` line 483: Remove cash_proxies/cash_aliases table documentation or mark as deprecated

**Comprehensive doc sweep**: Run `grep -rn "cash_proxies\|cash_aliases\|get_cash_mappings\|get_cash_proxies\|cash_map.*database\|DB.*cash\|cash.*DB" docs/ admin/README.md Readme.md --include="*.md"` and update any remaining stale references.

## DB Tables — Migration Script

Create `database/migrations/20260312_drop_cash_tables.sql`:

```sql
-- Remove cash_proxies and cash_aliases tables.
-- All callers now read from config/cash_map.yaml (static data).
-- See docs/planning/CASH_MAPPINGS_YAML_ONLY_PLAN.md for context.
DROP TABLE IF EXISTS cash_aliases;
DROP TABLE IF EXISTS cash_proxies;
```

Also remove the `CREATE TABLE cash_proxies` (line 557) and `CREATE TABLE cash_aliases` (line 565) from `database/schema.sql` so new deployments don't recreate them.

Also remove `update_cash_proxy()` and any remaining cash write methods from `inputs/database_client.py` (kept in Step 8 but now unnecessary since tables are being dropped).

## Key Files

| File | Change |
|------|--------|
| `portfolio_risk_engine/portfolio_config.py` | Remove DB path in `get_cash_positions()`, YAML-only |
| `services/security_type_service.py` | Remove DB path in `_classify_cash_proxies()`, YAML-only |
| `inputs/portfolio_manager.py` | Simplify `_load_cash_mapping()`, remove preloaded params |
| `inputs/portfolio_repository.py` | Remove `cash_mappings` from payload + `get_cash_mappings()` |
| `portfolio_risk_engine/data_objects.py` | Remove DB path in `_load_cash_proxy_map()`, YAML-only |
| `services/returns_service.py` | Remove DB path in `_is_cash_proxy()`, YAML-only |
| `core/factor_intelligence.py` | Remove DB path in `load_cash_proxies()`, YAML-only |
| `inputs/database_client.py` | Remove `get_cash_mappings()` + `get_cash_proxies()` methods |
| `admin/migrate_reference_data.py` | Remove `migrate_cash_mappings()` + call |
| `admin/manage_reference_data.py` | Remove cash mapping CLI commands + `list_cash_mappings()` |
| `admin/verify_proxies.py` | Update cash proxy section to read YAML |
| `database/migrations/20260312_drop_cash_tables.sql` | New — `DROP TABLE IF EXISTS` for both tables |
| `database/schema.sql` | Remove `CREATE TABLE cash_proxies` + `cash_aliases` |
| `portfolio_risk_engine/portfolio_risk.py` | `pd.to_numeric()` fix for pandas 3.x |
| `tests/inputs/test_portfolio_repository.py` | Update payload assertions |
| `tests/inputs/test_portfolio_assembler.py` | Update payload builder + YAML fallback test |
| `tests/utils/test_final_status.py` | Remove DB cash_mappings check |
| `tests/utils/show_db_data.py` | Remove cash mappings display |
| `docs/planning/BUGS.md` | Mark both resolved |

## Verification

1. `pytest tests/inputs/test_portfolio_assembler.py -v` — updated tests pass
2. `pytest tests/inputs/test_portfolio_repository.py -v` — updated tests pass
3. `pytest tests/services/test_cache_control.py -v` — cache adapter still works
4. `pytest tests/ -x --timeout=60 -q` — no regressions across full suite
5. Verify no remaining callers anywhere: `grep -rn "get_cash_mappings\|get_cash_proxies" --include="*.py" | grep -v '.claude/'` returns zero matches (production, admin, AND tests)
6. Verify no stale doc references in active docs: `grep -rn "get_cash_mappings\|get_cash_proxies" --include="*.md" | grep -v '.claude/' | grep -v CASH_MAPPINGS_YAML_ONLY | grep -v completed/ | grep -v _legacy/ | grep -v _archive/` returns zero matches (excludes archived/historical plans which intentionally preserve old state)

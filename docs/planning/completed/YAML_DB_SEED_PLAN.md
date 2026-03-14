# YAML → DB Seed: Reference Data Read Path Plan
**Status:** DONE

**Priority:** Medium | **Added:** 2026-03-09

## Context

11 YAML config files provide reference data (exchange mappings, futures contracts, cash proxies, etc.). 5 already have DB-first + YAML fallback read paths. 2 are YAML-only and need DB read paths for multi-user deployment (users won't have filesystem access).

**Principle:** YAML stays the single source of truth. DB is seeded FROM YAML on deploy. Read path checks DB first, falls back to YAML. No runtime CRUD — you edit YAML, re-seed, done. No divergence risk.

## Scope

### Already DB-first (no changes needed)

| YAML file | Loader | DB table |
|-----------|--------|----------|
| `config/cash_map.yaml` | `load_cash_proxies()` | `cash_proxies` + `cash_aliases` |
| `config/asset_etf_proxies.yaml` | `load_asset_class_proxies()` | `asset_etf_proxies` |
| `config/industry_to_etf.yaml` | `load_industry_etf_map()` | `industry_proxies` |
| `config/exchange_etf_proxies.yaml` | `load_exchange_proxy_map()` | `exchange_proxies` |
| `config/security_type_mappings.yaml` | `get_security_type_mappings()` | `security_type_mappings` + `security_type_scenarios` |

### Needs DB read path (this plan)

| YAML file | Loader | Callers | Caching |
|-----------|--------|---------|---------|
| `brokerage/futures/contracts.yaml` | `load_contract_specs()` → `get_contract_spec()` | 20+ | `@lru_cache(1)` on `_load_contracts_yaml()` |
| `config/exchange_mappings.yaml` | `load_exchange_mappings()` | 10+ | `@lru_cache(1)` on `load_exchange_mappings()` |

### Out of scope

| YAML file | Reason |
|-----------|--------|
| `ibkr/exchange_mappings.yaml` | IBKR-specific, 1 caller, low priority |
| `config/portfolio.yaml` | Per-user input, already loaded via `load_portfolio_config()` into PortfolioData |
| `config/risk_limits.yaml` | Per-user, already in `risk_limits` DB table |
| `config/strategy_templates.yaml` | REST endpoint only, low priority |

## Changes

### 1. DB Schema — Two new reference tables

**Migration file:** `database/migrations/20260309_add_instrument_reference_tables.sql`

```sql
-- Futures contract specifications (seeded from contracts.yaml)
CREATE TABLE IF NOT EXISTS futures_contracts (
    symbol VARCHAR(20) PRIMARY KEY,
    multiplier DECIMAL(20,8) NOT NULL,
    tick_size DECIMAL(20,8) NOT NULL,
    currency VARCHAR(10) NOT NULL,
    exchange VARCHAR(20) NOT NULL,
    asset_class VARCHAR(30) NOT NULL,
    fmp_symbol VARCHAR(30),
    margin_rate DECIMAL(10,6) NOT NULL DEFAULT 0.10,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Exchange resolution config (seeded from exchange_mappings.yaml)
-- Stores all 7 sections as a single JSONB document:
-- mic_to_fmp_suffix, us_exchange_mics, minor_currencies, currency_aliases,
-- currency_to_fx_pair, currency_to_usd_fallback, mic_to_exchange_short_name
CREATE TABLE IF NOT EXISTS exchange_resolution_config (
    id INT PRIMARY KEY DEFAULT 1,
    mappings JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT single_row CHECK (id = 1)
);
```

**Design choice — `exchange_resolution_config` as single JSONB row:**
The exchange_mappings.yaml has 7 heterogeneous sections. Normalizing into 7 tables for ~50 total rows is over-engineering. A single JSONB document mirrors the YAML structure exactly, is trivially seeded, and the read path just returns the dict (same as `yaml.safe_load()` does today). The `CHECK (id = 1)` constraint ensures at most one row.

Note: Table is named `exchange_resolution_config` (not `exchange_mappings`) to avoid collision with the existing `get_exchange_mappings()` DatabaseClient method which reads the `exchange_proxies` table (exchange → factor ETF proxy mappings, a different concept).

**Design choice — `futures_contracts` as normalized table:**
Contract specs are structured, queried by symbol, and have a natural primary key. Normalized table is the right fit. 27 rows currently.

### 2. Seed Script

**File:** `scripts/seed_reference_data.py`

Contains the 2 new seeders for `futures_contracts` and `exchange_resolution_config`, plus a unified `seed_all()` entry point that orchestrates all reference data seeding (existing 5 + new 2).

**New seeders (dedicated YAML-only loaders to avoid circular reads):**

```python
def _load_contracts_yaml_for_seed() -> dict:
    """Load contracts.yaml directly for seeding. Never reads from DB."""
    yaml_path = Path(__file__).resolve().parent.parent / "brokerage" / "futures" / "contracts.yaml"
    with yaml_path.open("r") as f:
        return yaml.safe_load(f).get("contracts", {})

def _load_exchange_mappings_yaml_for_seed() -> dict:
    """Load exchange_mappings.yaml directly for seeding. Never reads from DB."""
    yaml_path = resolve_config_path("exchange_mappings.yaml")
    with yaml_path.open("r") as f:
        return yaml.safe_load(f) or {}

def seed_futures_contracts(conn):
    """Seed futures_contracts from contracts.yaml.

    Transactional replace: DELETE all rows, INSERT from YAML.
    Does NOT commit — caller manages the transaction boundary.
    """
    contracts = _load_contracts_yaml_for_seed()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM futures_contracts")
    for symbol, meta in contracts.items():
        cursor.execute(
            """INSERT INTO futures_contracts
               (symbol, multiplier, tick_size, currency, exchange,
                asset_class, fmp_symbol, margin_rate)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (symbol, meta["multiplier"], meta["tick_size"], meta["currency"],
             meta["exchange"], meta["asset_class"], meta.get("fmp_symbol"),
             meta.get("margin_rate", 0.10)),
        )

def seed_exchange_resolution_config(conn):
    """Seed exchange_resolution_config from exchange_mappings.yaml.

    Does NOT commit — caller manages the transaction boundary.
    """
    mappings = _load_exchange_mappings_yaml_for_seed()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO exchange_resolution_config (id, mappings)
           VALUES (1, %s)
           ON CONFLICT (id) DO UPDATE SET mappings = EXCLUDED.mappings,
                                          updated_at = NOW()""",
        (json.dumps(mappings),),
    )
```

**Unified entry point — orchestrates, does not rewrite existing seeders:**

```python
def seed_all():
    """Seed ALL reference data from YAML to DB. Safe to run repeatedly.

    Two phases:
    Phase 1 — Existing 5 tables: Delegates to admin/migrate_reference_data.main().
              These seeders use DatabaseClient methods that commit internally
              (per-row UPSERT with individual error handling). This is the
              existing behavior and is NOT changed — it's battle-tested.

    Phase 2 — New 2 tables: Atomic transaction with explicit rollback.
              futures_contracts uses DELETE+INSERT (prunes stale rows).
              exchange_resolution_config uses UPSERT (single row).
    """
    # Phase 1: Existing 5 tables (existing transaction semantics preserved)
    from admin.migrate_reference_data import main as migrate_existing
    migrate_existing()

    # Phase 2: New 2 tables (atomic)
    with get_db_session() as conn:
        try:
            seed_futures_contracts(conn)
            seed_exchange_resolution_config(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # Clear all affected caches after successful seed
    _clear_all_reference_caches()

def verify_seed():
    """Verify all reference data tables are populated. Raises on failure."""
    with get_db_session() as conn:
        cursor = conn.cursor()
        checks = [
            "cash_proxies", "cash_aliases", "asset_etf_proxies",
            "industry_proxies", "exchange_proxies",
            "security_type_mappings", "security_type_scenarios",
            "futures_contracts", "exchange_resolution_config",
        ]
        for table in checks:
            cursor.execute(f"SELECT COUNT(*) AS c FROM {table}")
            count = cursor.fetchone()["c"]
            print(f"  {table}: {count} rows")
            if count == 0:
                raise RuntimeError(f"{table} is empty — seed failed")

if __name__ == "__main__":
    seed_all()
    verify_seed()
    print("Reference data seed complete.")
```

**Key design decisions:**

1. **Existing seeders are NOT refactored.** The 5 `migrate_*` functions in `admin/migrate_reference_data.py` stay as-is — they use DatabaseClient methods that commit per-row, catch row-level errors, and continue. This is intentional and battle-tested. Refactoring them for single-transaction atomicity would require changing ~7 DatabaseClient methods — out of scope.

2. **New seeders ARE atomic.** The 2 new tables (`futures_contracts`, `exchange_resolution_config`) use direct SQL in a single transaction with explicit rollback. This is the correct pattern for the new code.

3. **`admin/migrate_reference_data.py` is preserved unchanged.** It continues to work as a standalone script for seeding the existing 5 tables. `seed_all()` imports and calls its `main()` for Phase 1, then adds Phase 2. No sys.path changes, no wrapper rewrite.

4. **`verify_seed()` checks all 8 tables** (including `security_type_scenarios` which is seeded by `migrate_security_type_mappings` alongside `security_type_mappings`).

**Known limitation (pre-existing, not introduced by this plan):** The existing 5 seeders in `admin/migrate_reference_data.py` catch per-row errors and continue, so a partial failure can leave incomplete data. `verify_seed()` checks `COUNT(*) > 0` per table, which catches total failures but not partial ones. Strengthening the existing seeders (e.g. expected row counts, checksums) is a separate improvement — out of scope for this plan.

**Key design: seed reads YAML directly, never from runtime loaders.** The runtime loaders (`load_contract_specs()`, `load_exchange_mappings()`) will be DB-first after this plan. If the seed called them, it could read stale DB state and write it back (circular). Dedicated `_load_*_yaml_for_seed()` functions prevent this. The existing 5 seeders already load YAML directly.

**Key design: transactional replace for `futures_contracts`.** UPSERT alone would leave stale rows if a contract is removed from YAML. DELETE + INSERT in a single transaction ensures DB matches YAML exactly. The `exchange_resolution_config` table uses UPSERT (single row, always fully replaced). The existing 5 tables use UPSERT-only (stale row pruning is out of scope for this plan — tracked separately if needed).

Run as: `python3 -m scripts.seed_reference_data` (seeds all 7 tables + verifies).

### 3. DatabaseClient Methods

**File:** `inputs/database_client.py`

Add two read methods following existing patterns:

```python
def get_futures_contracts(self) -> Dict[str, Dict[str, Any]]:
    """Load all futures contract specs from DB. Returns {symbol: {fields...}}."""
    cursor.execute("SELECT * FROM futures_contracts ORDER BY symbol")
    return {row["symbol"]: dict(row) for row in cursor.fetchall()}

def get_exchange_resolution_config(self) -> Optional[Dict[str, Any]]:
    """Load exchange resolution config JSONB document. Returns None if table empty/missing."""
    cursor.execute("SELECT mappings FROM exchange_resolution_config WHERE id = 1")
    row = cursor.fetchone()
    return dict(row["mappings"]) if row else None
```

Note: Named `get_exchange_resolution_config()` to avoid collision with existing `get_exchange_mappings()` which reads the `exchange_proxies` table (exchange → factor ETF proxy mappings).

### 4. Read Path Updates — DB-first with YAML fallback

Follow the canonical pattern from `core/factor_intelligence.py` (`load_asset_class_proxies`, `load_cash_proxies`): try DB read directly, log failure, fall through to YAML. No `is_db_available()` preflight.

**File:** `brokerage/futures/contract_spec.py`

Add `@lru_cache(1)` to `load_contract_specs()` (not just `_load_contracts_yaml()`) so the DB path is also cached for process lifetime. This is critical: `get_contract_spec()` calls `load_contract_specs()` on every invocation, and there are hot-loop callers in `data_objects.py:709`, `nav.py:385`, `position_enrichment.py:55`.

```python
@lru_cache(maxsize=1)
def load_contract_specs() -> Dict[str, FuturesContractSpec]:
    """Load contract specs: DB-first, YAML fallback (cached for process lifetime)."""
    # DB-first
    try:
        from inputs.database_client import DatabaseClient
        from database import get_db_session
        with get_db_session() as conn:
            db_client = DatabaseClient(conn)
            rows = db_client.get_futures_contracts()
        if rows:
            return _rows_to_specs(rows)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("futures contracts DB read failed: %s", e)

    # YAML fallback (existing code)
    catalog = _load_contracts_yaml()
    return _parse_catalog(catalog)
```

Extract current parsing into `_parse_catalog()` and add `_rows_to_specs()` to convert DB rows → `FuturesContractSpec` dataclass instances.

**File:** `utils/ticker_resolver.py`

Update `load_exchange_mappings()` — already has `@lru_cache(1)`:

```python
@lru_cache(maxsize=1)
def load_exchange_mappings() -> dict:
    """Load exchange mappings: DB-first, YAML fallback (cached for process lifetime)."""
    # DB-first
    try:
        from inputs.database_client import DatabaseClient
        from database import get_db_session
        with get_db_session() as conn:
            db_client = DatabaseClient(conn)
            mappings = db_client.get_exchange_resolution_config()
        if mappings:
            return mappings
    except Exception as e:
        portfolio_logger.warning("exchange resolution config DB read failed: %s", e)

    # YAML fallback (existing code)
    config_path = resolve_config_path("exchange_mappings.yaml")
    try:
        with open(config_path, "r") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        portfolio_logger.warning(f"exchange_mappings.yaml not found at {config_path}")
        return {}
    except Exception as exc:
        portfolio_logger.warning(f"Failed to load exchange_mappings.yaml: {exc}")
        return {}
```

### 5. Schema File Update

Add the new tables to `database/schema.sql` in the "REFERENCE DATA TABLES" section (after `asset_etf_proxies`).

## Files Changed

| File | Change |
|------|--------|
| `database/migrations/20260309_add_instrument_reference_tables.sql` (new) | CREATE TABLE `futures_contracts` + `exchange_resolution_config` |
| `database/schema.sql` | Add new tables to reference data section |
| `scripts/seed_reference_data.py` (new) | Unified seed entry point: 2 new seeders + orchestrates existing 5 via `admin/migrate_reference_data.main()` + `verify_seed()` + `_clear_all_reference_caches()` |
| `inputs/database_client.py` | Add `get_futures_contracts()` + `get_exchange_resolution_config()` methods |
| `brokerage/futures/contract_spec.py` | DB-first read path in `load_contract_specs()`, add `@lru_cache(1)` |
| `utils/ticker_resolver.py` | DB-first read path in `load_exchange_mappings()` |
| `services/cache_adapters.py` | Add `InstrumentConfigLRUCacheAdapter` (5 caches: 2 primary + 3 derived) |
| `services/cache_control.py` | Register `InstrumentConfigLRUCacheAdapter` in `build_cache_manager()` |
| `services/service_manager.py` | Register `InstrumentConfigLRUCacheAdapter` in `_get_cache_manager()` |
| `tests/database/test_seed_reference_data.py` (new) | Seed script tests (idempotent, round-trip, prune, rollback) |
| `tests/brokerage/futures/test_contract_spec_db.py` (new) | DB-first read path + YAML fallback tests |
| `tests/utils/test_exchange_mappings_db.py` (new) | DB-first read path + YAML fallback tests |

## Tests

All tests that touch `load_exchange_mappings()` or `load_contract_specs()` must call `load_exchange_mappings.cache_clear()` / `load_contract_specs.cache_clear()` in setup/teardown to avoid `@lru_cache` poisoning across tests.

1. **Seed idempotency**: Run seed twice → same result, no duplicates, no errors.
2. **Seed prune**: Seed with 27 contracts, then seed with a modified YAML missing one contract → DB has 26 rows (stale row pruned).
3. **Seed failure rollback**: Mock an INSERT to raise mid-`seed_all()` → `conn.rollback()` called, neither table modified (atomic across both tables). Follows `app_platform/db/migration.py` pattern.
4. **Futures contracts round-trip**: Seed from YAML → read from DB → compare to direct YAML load. All 27 contracts match (symbol, multiplier, tick_size, currency, exchange, asset_class, fmp_symbol, margin_rate).
5. **Exchange mappings round-trip**: Seed from YAML → read from DB → compare to direct YAML load. All 7 sections match.
6. **Futures DB-first path**: Mock DB to return data → `load_contract_specs()` returns DB data, YAML not loaded.
7. **Futures YAML fallback**: Mock DB to raise → `load_contract_specs()` falls back to YAML, logs warning.
8. **FuturesContractSpec parity**: DB-sourced specs have same dataclass fields and computed properties as YAML-sourced specs.
9. **Exchange mappings DB-first path**: Mock DB to return data → `load_exchange_mappings()` returns DB data, YAML not loaded.
10. **Exchange mappings YAML fallback**: Mock DB to raise → `load_exchange_mappings()` falls back to YAML, logs warning.
11. **Exchange mappings consumers**: `normalize_currency()`, `normalize_fmp_price()`, `resolve_fmp_ticker()` work identically with DB-sourced vs YAML-sourced mappings. (Note: `select_fmp_symbol()` does not consume exchange mappings directly.)
12. **Futures cache clearing**: Verify `load_contract_specs.cache_clear()` forces re-read from DB on next call.
13. **Exchange mappings cache clearing**: Verify `load_exchange_mappings.cache_clear()` forces re-read from DB on next call.
14. **Existing `get_exchange_mappings()` unaffected**: Verify the existing `DatabaseClient.get_exchange_mappings()` method (reads `exchange_proxies` table) continues to work unchanged.

**Cache isolation in existing tests:** Existing test files that import `load_contract_specs` or `load_exchange_mappings` (e.g. `tests/brokerage/futures/test_contract_spec.py`, `tests/ibkr/test_compat.py`) must add `cache_clear()` calls in `setup`/`teardown` to prevent cross-test `@lru_cache` poisoning from the new DB-first path.

## Deploy Integration

**Single entry point:** `python3 -m scripts.seed_reference_data` seeds all reference data tables (existing 5 + new 2) and verifies all 8 tables.

**Prerequisite:** The migration SQL (`database/migrations/20260309_add_instrument_reference_tables.sql`) must be applied before seeding. The existing `admin/run_migration.py` takes a single migration file path as argv. Run the new migration explicitly before seeding:

```bash
python3 admin/run_migration.py database/migrations/20260309_add_instrument_reference_tables.sql
python3 -m scripts.seed_reference_data
```

For fresh installs, `database/schema.sql` already includes the new tables (Section 5 of this plan).

**Backward compatibility:** `admin/migrate_reference_data.py` is preserved unchanged — it still seeds the existing 5 tables independently. `seed_all()` calls it as Phase 1, so both entry points work.

**`_clear_all_reference_caches()`** clears all affected caches after successful seed (primary loaders + derived caches):

```python
def _clear_all_reference_caches():
    """Clear all reference data caches (primary + derived)."""
    try:
        from brokerage.futures.contract_spec import load_contract_specs
        from utils.ticker_resolver import load_exchange_mappings, _RESOLUTION_CACHE
        from ibkr.flex import _load_futures_root_symbols
        from fmp.compat import _minor_currency_divisor_for_symbol

        # Primary loader caches
        load_contract_specs.cache_clear()
        load_exchange_mappings.cache_clear()

        # Derived caches
        _RESOLUTION_CACHE.clear()
        _load_futures_root_symbols.cache_clear()
        _minor_currency_divisor_for_symbol.cache_clear()

        # Service-level caches (covers factor_intelligence LRUs etc.)
        from services.service_manager import ServiceManager
        ServiceManager().clear_all_caches()
    except Exception as e:
        print(f"Warning: could not clear all caches: {e}")
```

### Cache Invalidation

The new `@lru_cache(1)` on `load_contract_specs()` and the existing `@lru_cache(1)` on `load_exchange_mappings()` are process-lifetime caches. After re-seeding, running processes hold stale data until restart or cache clear.

**Mitigation (sufficient for current use):**
1. Deploy restarts all workers → caches cold → fresh DB reads.
2. MCP server reconnect (`/mcp`) restarts the process → caches cold.
3. `_clear_service_caches_after_migration()` in the admin migrator clears both caches (added above).
4. Add `InstrumentConfigLRUCacheAdapter` to `services/cache_adapters.py` (following `FactorIntelligenceLRUCacheAdapter` pattern) — clears all 5 caches (2 primary + 3 derived: `_RESOLUTION_CACHE`, `_load_futures_root_symbols`, `_minor_currency_divisor_for_symbol`). Register it in both `cache_control.py:build_cache_manager()` (line ~134, after `FactorIntelligenceLRUCacheAdapter`) and `service_manager.py:_get_cache_manager()` (line ~136, after `RedisCacheAdapter`).

No hot-reload invalidation needed — reference data changes are deploy-time events.

## Verification

1. `python3 -m scripts.seed_reference_data` — seed succeeds
2. `python3 -m pytest tests/database/test_seed_reference_data.py tests/brokerage/futures/test_contract_spec_db.py tests/utils/test_exchange_mappings_db.py -x -q`
3. `python3 -m pytest tests/ -x -q --ignore=tests/core/test_realized_cash_anchor.py` — full suite passes
4. Manual DB-path verification: After seeding, call `load_contract_specs()` and `load_exchange_mappings()` with `DEBUG` logging enabled. Both new read paths log a warning on DB failure before falling back to YAML ("futures contracts DB read failed" / "exchange resolution config DB read failed"). Absence of these warnings confirms DB read succeeded. Alternatively, temporarily disable YAML fallback and verify the loader still returns data (proving DB path works independently).

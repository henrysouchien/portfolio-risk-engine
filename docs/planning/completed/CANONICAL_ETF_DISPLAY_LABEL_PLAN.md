# Canonical ETF Display Label Plan (`is_primary` column)

**Status**: REVIEW v7 — aligns duplicate-primary policy (first-explicit-wins everywhere)
**Bug**: Pre-existing duplicate-ETF label non-determinism (related to F7)
**Severity**: Display-only — risk modeling unaffected

---

## Context

When multiple industries map to the same proxy ETF (e.g., 10 industries → KCE), the reverse lookup (ETF → industry name for display) must pick exactly one label. Today this is non-deterministic:

- **Path 1** (`get_etf_to_industry_map()` at `utils/etf_mappings.py:17`): reverses `get_industry_mappings()` via `{etf: industry for industry, etf in ...}` — last-write-wins, order depends on DB row ordering (no `ORDER BY`).
- **Path 2** (`_etf_to_sector_label()` at `services/factor_intelligence_service.py:1563`): builds `_etf_to_sector` dict from forward map iteration, picks "broad" (no ` - `) entries first.

**31 ETFs** are shared across multiple industries. Labels can change after DB maintenance or re-seeding. The fix: add `is_primary BOOLEAN` to `industry_proxies` so exactly one row per ETF is the canonical display label.

**Precedent**: `asset_etf_proxies` already uses `is_canonical BOOLEAN DEFAULT TRUE` (`database/schema.sql:672`).

---

## Design

### Separation of concerns

- **`update_industry_proxy()`**: manages data fields (proxy_etf, asset_class, sector_group). Has a **conditional pre-clear** that only fires when `proxy_etf` is changing on a primary row. Metadata-only edits (same proxy_etf) preserve `is_primary`.
- **`set_industry_primary()`**: manages the `is_primary` flag exclusively. Three-statement `FOR UPDATE` transaction: lock → clear → set. Validates target exists before any modification.

### No migration backfill

The migration adds the column and index only. The `get_canonical_etf_to_industry()` query's `ORDER BY is_primary DESC, industry ASC` provides deterministic alphabetical fallback when no rows have `is_primary = TRUE`. The bulk migrator sets real primaries (first-in-YAML) on first run.

### This PR vs follow-up

| This PR (infrastructure) | Follow-up (editorial) |
|---|---|
| Schema + migration | YAML `is_primary: true` markers for ~10 ETFs where first-in-YAML is wrong |
| DB client methods | Canonical label audit and user sign-off per ETF |
| Both reverse-map paths use canonical lookup | |
| Migrator + admin tool updates | |
| Tests | |

---

## Steps

### Step 1: Schema migration

**File**: `database/migrations/20260409_add_industry_proxies_is_primary.sql` (new)

```sql
-- Add is_primary column for canonical display label per proxy_etf.
-- No backfill — query fallback handles the all-FALSE case.
-- Migrator sets primaries on first run.

ALTER TABLE industry_proxies
    ADD COLUMN IF NOT EXISTS is_primary BOOLEAN NOT NULL DEFAULT FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS idx_industry_proxies_one_primary_per_etf
    ON industry_proxies(proxy_etf)
    WHERE is_primary = TRUE;
```

Also update `database/schema.sql:657-664` to include the new column and index.

### Step 2: Database client changes

**File**: `inputs/database_client.py`

#### 2a. New method: `get_canonical_etf_to_industry()`

```sql
SELECT DISTINCT ON (proxy_etf) proxy_etf, industry
FROM industry_proxies
ORDER BY proxy_etf, is_primary DESC, industry ASC
```

Returns `Dict[str, str]` (ETF → industry). `is_primary DESC` picks primary first; `industry ASC` is the deterministic fallback.

**Backward compat**: try/except. If column doesn't exist (pre-migration), fall back to old `get_industry_mappings()` reversal. Log warning.

#### 2b. `update_industry_proxy()` — conditional pre-clear

**Do NOT add `is_primary` to INSERT or SET clause.** Add a conditional pre-clear that only fires when the row is currently primary AND `proxy_etf` is changing:

```python
def update_industry_proxy(self, industry, proxy_etf, asset_class=None, sector_group=None):
    with self.get_connection() as conn:
        cursor = conn.cursor()
        # Conditional pre-clear: only clear is_primary when proxy_etf is changing
        # on a primary row. Prevents partial unique index violation when row moves
        # to an ETF that already has its own primary. Metadata-only edits on the
        # same proxy_etf preserve is_primary.
        cursor.execute(
            "UPDATE industry_proxies SET is_primary = FALSE "
            "WHERE industry = %s AND is_primary = TRUE AND proxy_etf != %s",
            (industry, proxy_etf)
        )
        # UPSERT data fields only
        cursor.execute("""
            INSERT INTO industry_proxies (industry, proxy_etf, asset_class, sector_group, updated_at)
            VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (industry) DO UPDATE SET
                proxy_etf    = EXCLUDED.proxy_etf,
                asset_class  = EXCLUDED.asset_class,
                sector_group = EXCLUDED.sector_group,
                updated_at   = CURRENT_TIMESTAMP
        """, (industry, proxy_etf, asset_class, sector_group))
        conn.commit()
```

**Behavior**:
- **New row (INSERT)**: pre-clear matches 0 rows. Row gets `is_primary = DEFAULT FALSE`.
- **Existing non-primary row**: pre-clear matches 0 rows. UPSERT updates data.
- **Existing primary row, same proxy_etf** (metadata edit): `proxy_etf != %s` is FALSE → pre-clear matches 0 rows. `is_primary` preserved.
- **Existing primary row, different proxy_etf**: pre-clear clears `is_primary`. UPSERT moves row. No index collision.

#### 2c. New method: `set_industry_primary(proxy_etf, industry)`

Three-statement `FOR UPDATE` transaction:

```python
def set_industry_primary(self, proxy_etf: str, industry: str) -> None:
    with self.get_connection() as conn:
        cursor = conn.cursor()
        # 1. Lock all rows for this ETF
        cursor.execute(
            "SELECT industry FROM industry_proxies WHERE proxy_etf = %s FOR UPDATE",
            (proxy_etf,)
        )
        available = [row['industry'] for row in cursor.fetchall()]
        if industry not in available:
            conn.rollback()
            raise DatabaseError(
                f"No row for industry '{industry}' with proxy_etf '{proxy_etf}'. "
                f"Available: {available}"
            )
        # 2. Clear all primaries for this ETF
        cursor.execute(
            "UPDATE industry_proxies SET is_primary = FALSE "
            "WHERE proxy_etf = %s AND is_primary = TRUE",
            (proxy_etf,)
        )
        # 3. Set the target as primary
        cursor.execute(
            "UPDATE industry_proxies SET is_primary = TRUE "
            "WHERE proxy_etf = %s AND industry = %s",
            (proxy_etf, industry)
        )
        conn.commit()
```

**Guarantees**: `FOR UPDATE` prevents concurrent modification. Clear-then-set avoids unique index violation. Validates target before any modification.

### Step 3: Reverse-map reader — `utils/etf_mappings.py`

#### 3a. `get_etf_to_industry_map()` (lines 9-50)

- **DB path**: call `get_canonical_etf_to_industry()` instead of reversing `get_industry_mappings()`.
- **YAML fallback**: fix broken dict comprehension. Handle structured entries. `setdefault` for first-wins. Override with explicit `is_primary: true`:

```python
etf_to_industry = {}
etf_explicit_primary = {}
for industry, mapping in raw.items():
    if isinstance(mapping, dict):
        etf_ticker = str(mapping.get("etf") or "").strip().upper()
        if mapping.get("is_primary"):
            etf_explicit_primary.setdefault(etf_ticker, industry)  # first explicit wins
    else:
        etf_ticker = str(mapping or "").strip().upper()
    if etf_ticker:
        etf_to_industry.setdefault(etf_ticker, industry)
etf_to_industry.update(etf_explicit_primary)
return etf_to_industry
```

- **Hardcoded fallback**: unchanged.

#### 3b. `format_ticker_with_label()` — no changes needed.

### Step 4: Reverse-map reader — `services/factor_intelligence_service.py`

**File**: lines 1560-1592

Call `get_etf_to_industry_map()` directly (same function Path 1 uses). One extra lightweight `DISTINCT ON` query per `recommend_portfolio_offsets()` call. Retain `_etf_to_sector` dict + "broad" heuristic as secondary fallback for ETFs not in the DB:

```python
from utils.etf_mappings import get_etf_to_industry_map
from portfolio_risk_engine.portfolio_config import is_cash_ticker

canonical_etf_map = get_etf_to_industry_map()

def _etf_to_sector_label(etf_ticker: Any) -> str:
    label_key = str(etf_ticker or "").strip().upper()
    if is_cash_ticker(label_key):
        return "Cash Proxy"
    canonical = canonical_etf_map.get(label_key)
    if canonical:
        return canonical
    # Fallback: broad-label heuristic for ETFs not in canonical map
    sector_names = _etf_to_sector.get(label_key, [])
    broad = [s for s in sector_names if " - " not in s]
    if broad:
        return broad[0]
    if sector_names:
        return sector_names[0]
    return label_key
```

The `_etf_to_sector` dict construction at lines 1580-1584 is unchanged.

### Step 5: Bulk migrator

**File**: `admin/migrate_reference_data.py` (lines 113-176)

Update `migrate_industry_mappings()`:

1. **Collect**: walk YAML, build `{etf: [(industry, is_primary_flag, asset_class, sector_group)]}`.
2. **Resolve primaries per ETF**: explicit `is_primary: true` wins; else first-in-YAML; multiple explicit → warning, use first.
3. **Write phase (two phases)**:
   - **3a**: `update_industry_proxy()` for all rows (data fields only). Conditional pre-clear handles any proxy_etf changes safely.
   - **3b**: `set_industry_primary(proxy_etf, resolved_industry)` for each ETF. Atomically sets the resolved canonical.

### Step 6: Admin tool

**File**: `admin/manage_reference_data.py`

- `industry add`: add `--primary` flag. When set, call `set_industry_primary()` after UPSERT.
- New `industry set-primary <industry> <proxy_etf>` subcommand for existing rows. Validates via `set_industry_primary()` — raises error with available industry names if target doesn't exist.

### Step 7: YAML editorial (Phase 2, deferred)

No `is_primary: true` YAML markers in this PR. Migrator's first-in-YAML default + query's alphabetical fallback covers most ETFs.

**ETFs needing explicit overrides** (actual YAML industry keys):

| ETF | First-in-YAML (migrator default) | Suggested canonical | Override? |
|---|---|---|---|
| KCE | Credit Services | Financial - Capital Markets | Yes |
| IYR | REIT - Specialty | REIT - Diversified | Yes |
| KIE | Insurance - Specialty | Insurance - Diversified | Yes |
| XME | Steel | Steel | OK ✓ |
| XRT | Specialty Retail | Specialty Retail | OK ✓ |
| IDRV | Auto - Parts | Auto - Manufacturers | Yes |
| XHS | Medical - Specialties | Medical - Equipment & Services | Yes |
| MOO | Agricultural Inputs | Agricultural Inputs | OK ✓ |
| IHF | Medical - Healthcare Plans | Medical - Healthcare Plans | OK ✓ |
| IYT | Railroads | Integrated Freight & Logistics | Yes |

---

## Files Changed

| File | Change |
|------|--------|
| `database/migrations/20260409_add_industry_proxies_is_primary.sql` | **New** — ALTER TABLE + partial unique index |
| `database/schema.sql` | Add `is_primary` column + index |
| `inputs/database_client.py` | New `get_canonical_etf_to_industry()`, `set_industry_primary()`. `update_industry_proxy()` gets conditional pre-clear. |
| `utils/etf_mappings.py` | Rewrite `get_etf_to_industry_map()` DB+YAML paths |
| `services/factor_intelligence_service.py` | `_etf_to_sector_label()` uses canonical map first, broad heuristic as fallback |
| `admin/migrate_reference_data.py` | Two-pass primary resolution + two-phase write |
| `admin/manage_reference_data.py` | `--primary` flag, `industry set-primary` subcommand |

---

## Tests

### New tests

1. **`test_get_canonical_etf_to_industry_prefers_primary`**: KCE rows with one is_primary=true. Assert canonical returned.
2. **`test_get_canonical_etf_to_industry_fallback_alphabetical`**: KCE rows all is_primary=false. Assert alphabetical-first returned.
3. **`test_get_canonical_etf_to_industry_pre_migration_fallback`**: Column doesn't exist → falls back to old reversal.
4. **`test_get_etf_to_industry_map_yaml_structured_entries`**: YAML with structured entries (SLV, XOP, REM) present with correct labels.
5. **`test_get_etf_to_industry_map_yaml_explicit_primary`**: Non-first entry with `is_primary: true` wins.
6. **`test_get_etf_to_industry_map_yaml_duplicate_primary`**: Two `is_primary: true` for same ETF → first-in-YAML wins (consistent with migrator policy).
7. **`test_etf_to_sector_label_canonical_then_broad_fallback`**: Canonical map resolves first; broad heuristic used for missing ETFs.
8. **`test_etf_to_sector_label_cash_guard`**: SGOV → "Cash Proxy".
9. **`test_migrate_auto_primary`**: 3 industries → same ETF, no explicit primary. First-in-YAML gets is_primary=true.
10. **`test_migrate_explicit_primary_wins`**: 2nd YAML entry has `is_primary: true`. Overrides first.
11. **`test_migrate_rerun_safe`**: Run migrator twice. No unique index violation.
12. **`test_set_industry_primary_switches`**: 3 KCE rows, set primary, switch to another. Exactly one TRUE each time.
13. **`test_set_industry_primary_invalid_target`**: Non-existent industry → DatabaseError raised, existing primary preserved.
14. **`test_set_industry_primary_etf_missing`**: No rows for ETF → DatabaseError with empty list.
15. **`test_set_industry_primary_single_row`**: ETF with one row → that row becomes primary.
16. **`test_update_industry_proxy_metadata_preserves_primary`**: Primary row, change asset_class (same proxy_etf). Assert `is_primary` preserved.
17. **`test_update_industry_proxy_etf_change_clears_primary`**: Primary row, change proxy_etf. Assert `is_primary` cleared, no index violation.
18. **`test_migrator_etf_reassignment_safe`**: Seed "Foo"→KCE (primary). YAML changes to "Foo"→XLF. No violation, correct primaries after.
19. **`test_yaml_mixed_scalar_and_structured_primary`**: Scalar "Foo": "KCE" + structured "Bar": {etf: "KCE", is_primary: true}. Structured wins.
20. **`test_admin_add_with_primary`**: `industry add "NewIndustry" KCE --primary` → row added + is_primary set.
21. **`test_admin_set_primary`**: `industry set-primary "Financial - Capital Markets" KCE` → switches primary.

### Existing test updates

- `test_build_risk_drivers_merges_sorts_and_keeps_all_positive_entries` (`tests/core/test_risk_analysis_result_getters.py:153`): mock `get_etf_to_industry_map` to return deterministic labels.

---

## Verification

### Automated
```bash
pytest tests/ -x -q
```

### Manual — DB path
After migration + migrator run:
```bash
python3 -c "
from utils.etf_mappings import get_etf_to_industry_map
m = get_etf_to_industry_map()
for t in ['KCE', 'KIE', 'REM', 'IGV', 'XLK', 'XLI', 'XLP']:
    print(f'{t}: {m.get(t, \"MISSING\")}')
"
```

### Manual — admin tool
```bash
python admin/manage_reference_data.py industry set-primary "Financial - Capital Markets" KCE
```

### Visual
After restarting `risk_module` service: risk view, hedge analysis, hedge workflow dialog — driver labels consistent.

---

## Codex Review History

| Round | Result | Findings | Key changes |
|-------|--------|----------|-------------|
| R1 | FAIL (6) | Display labels ≠ YAML keys; deploy-before-backfill window; migrator unique-index collision; set_industry_primary race; redundant DB call; broad-heuristic removal regresses labels | v2 |
| R2 | FAIL (4) | Validation wrong (rowcount>0 on miss); build_canonical_reverse_map dead on DB path; UPSERT default clears primary; migration not rerun-idempotent | v3 |
| R3 | FAIL (1) | proxy_etf change on primary row → partial unique index violation | v4: pre-clear guard |
| R4 | FAIL (2) | set_industry_primary per-row index check; inconsistent default policy | v5: FOR UPDATE lock; removed backfill |
| R5 | FAIL (3) | Pre-clear too broad (fires on metadata edits); test 15 codifies wrong behavior; stale v4 wording | v6: conditional pre-clear (`proxy_etf != %s`); clean rewrite |
| R6 | FAIL (1) | Duplicate is_primary:true policy inconsistent (YAML fallback=last wins, migrator=first wins) | v7: YAML fallback uses `setdefault` for explicit primaries → first-explicit-wins everywhere |

---

## Risk & Scope

- **Low risk**: additive schema change, no risk math changes.
- **Conditional pre-clear**: only fires when proxy_etf actually changes on a primary row. Metadata edits preserve primary.
- **Broad heuristic retained**: no label regressions until editorial overrides land.
- **Extra DB call in Path 2**: one lightweight `DISTINCT ON` per `recommend_portfolio_offsets()`.
- **Migrator rerun safe**: conditional pre-clear + `set_industry_primary()` handles all cases.
- **F7 integration**: supersedes F7 Steps 1 (YAML reversal fix) and 4 (SGOV cash guard). F7 retains Steps 2, 3, 5 (DSU-specific).
- **Estimated Codex implementation rounds**: 3-5

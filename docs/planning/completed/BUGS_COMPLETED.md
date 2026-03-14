# Completed Bugs

Resolved bugs archived from `docs/planning/BUGS.md`.

---

## Bug 01: PostgreSQL "too many clients" on cash position detection

**Status:** Resolved
**Severity:** Low
**Opened:** 2026-02-27
**Resolved:** 2026-03-12

**Symptom:**
`get_cash_positions()` in `portfolio_config.py` logged `⚠️ Database unavailable (too many clients already)` and fell back to `cash_map.yaml`.

**Root cause:**
Connection pool usage was correct; the cash mapping callers were still opening unnecessary database reads for static global data. Removing the DB dependency for cash mappings eliminated the failure mode.

**Resolution:**
- Removed all production reads from `cash_proxies` / `cash_aliases`
- Standardized runtime cash mapping reads on `config/cash_map.yaml`
- Added a migration to drop the obsolete cash tables

**Files:**
- `portfolio_risk_engine/portfolio_config.py`
- `services/security_type_service.py`
- `inputs/portfolio_manager.py`
- `inputs/portfolio_repository.py`
- `portfolio_risk_engine/data_objects.py`
- `services/returns_service.py`
- `core/factor_intelligence.py`
- `database/migrations/20260312_drop_cash_tables.sql`

---

## Bug 02: Pandas FutureWarning on fillna downcasting

**Status:** Resolved
**Severity:** Low
**Opened:** 2026-02-27
**Resolved:** 2026-03-12

**Symptom:**
`portfolio_risk.py` emitted a pandas FutureWarning for implicit downcasting on `.fillna(0.0)` applied to an object-dtype Series.

**Root cause:**
The code relied on pandas' deprecated implicit dtype coercion. The repo targets pandas 3.x compatibility, so explicit numeric conversion is required.

**Resolution:**
- Replaced the object-series `.fillna(0.0)` path with `pd.to_numeric(..., errors="coerce").fillna(0.0)`

**Files:**
- `portfolio_risk_engine/portfolio_risk.py`

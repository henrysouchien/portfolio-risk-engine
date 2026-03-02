# Open Bugs & Known Issues

Track only active bugs in this file. Resolved bugs archived in `completed/BUGS_COMPLETED.md`.

---

## Current Status
- 2 active bugs.

---

## Bug 01: PostgreSQL "too many clients" on cash position detection

**Status:** Open
**Severity:** Low
**Date:** 2026-02-27

**Symptom:**
`get_cash_positions()` in `portfolio_config.py` logs `⚠️ Database unavailable (too many clients already)` and falls back to `cash_map.yaml`. Functional impact is zero (YAML fallback works), but indicates connection pool exhaustion.

**Root cause:**
Other sessions/processes hold open DB connections, exceeding `max_connections`. `get_cash_positions()` opens a fresh connection each time instead of reusing a pooled one.

**Reproduction:**
- Run any portfolio analysis: `python3 -c "from portfolio_risk_engine.portfolio_config import load_portfolio_config; load_portfolio_config('portfolio.yaml')"`
- Observe the `⚠️ Database unavailable` warning in output.

**Fix plan:**
Either increase `max_connections` in PostgreSQL config, or use a connection pool (e.g., `sqlalchemy` pool) instead of opening ad-hoc connections. Alternatively, skip DB entirely and always use `cash_map.yaml` (simpler, no DB dependency for a static mapping).

**Files:**
- `portfolio_risk_engine/portfolio_config.py` (`get_cash_positions()`)
- `database.py` (`get_db_session()`)

---

## Bug 02: Pandas FutureWarning on fillna downcasting

**Status:** Open
**Severity:** Low
**Date:** 2026-02-27

**Symptom:**
```
FutureWarning: Downcasting object dtype arrays on .fillna, .ffill, .bfill is deprecated
and will change in a future version. Call result.infer_objects(copy=False) instead.
```

**Root cause:**
`portfolio_risk.py:239` uses `.fillna(0.0)` on an object-dtype Series. Pandas 2.x deprecated implicit downcasting.

**Reproduction:**
- Run `build_portfolio_view()` with any portfolio config.

**Fix plan:**
Change:
```python
idio_var_series = pd.Series(idio_var_dict).reindex(w.index).fillna(0.0)
```
To:
```python
idio_var_series = pd.Series(idio_var_dict).reindex(w.index).infer_objects(copy=False).fillna(0.0)
```

**Files:**
- `portfolio_risk_engine/portfolio_risk.py` (line ~239)

---

## Template For New Issues

## Bug XX: <short title>

**Status:** Open
**Severity:** Blocker | High | Medium | Low
**Date:** YYYY-MM-DD

**Symptom:**

**Root cause:**

**Reproduction:**
- Command(s):
- Result:

**Fix plan:**

**Files:**

**Validation:**
- Command(s):
- Result:

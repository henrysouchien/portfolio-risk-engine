# Hardcoded Date Audit — Fix Plan

**Status**: PLAN v12 — addressing Codex v11 review feedback
**Severity**: Low
**Scope**: 3 categories: (A) `PORTFOLIO_DEFAULTS` root fix in `settings.py` + `config.py`, (B) 6 `app.py` direct-mode handlers, (C) 1 frontend copyright
**Risk**: Minimal — direct-mode endpoints are unused by frontend; PORTFOLIO_DEFAULTS change is safe because the performance API already overrides these dates dynamically (app.py:1726-1732)

---

## Background

TODO.md flagged: "Hardcoded dates in portfolioData / analysis paths — audit for legacy hardcoded dates, ensure all date usage is fully dynamic."

Full audit performed 2026-03-18. Searched `.py`, `.ts/.tsx`, and config files (YAML) for hardcoded date literals. Found production issues in 3 categories:

- **Category A** (highest impact): `PORTFOLIO_DEFAULTS` hardcoded dates in `settings.py` and `config.py` — consumed by many production paths including portfolio assembly, provider loaders, MCP tools, and services.
- **Category B**: 6 `/api/direct/*` endpoint handlers with stale defaults and/or top-level date fields ignored. These are stateless public API endpoints marked `# UNUSED BY FRONTEND`.
- **Category C**: Copyright year in frontend footer.

---

## Changes

### Category A: `PORTFOLIO_DEFAULTS` root fix

The central source of hardcoded dates. These feed into multiple production paths.

#### A1. `settings.py:36-38` — PORTFOLIO_DEFAULTS

**Current**:
```python
PORTFOLIO_DEFAULTS = {
    "start_date": "2019-01-31",
    "end_date":   "2026-01-29",
    ...
}
```

**Problem**: Both dates are hardcoded literals. `end_date` will go stale. These are consumed across many production paths — not just the direct-mode API. Known consumers include `portfolio_manager.py:174`, `portfolio_assembler.py:318`, `routes/plaid.py:1079`, `providers/plaid_loader.py:483`, `inputs/legacy_portfolio_file_service.py:77`, `providers/snaptrade_loader.py:1317,1453`, and `core/proxy_builder.py:729`. The dates also flow through `portfolio_risk_engine/data_objects.py:694` into MCP tools and services.

**Fix**: Compute dynamically at module load time (these are read-once config, not per-request):
```python
from datetime import date
from dateutil.relativedelta import relativedelta

_today = date.today()

PORTFOLIO_DEFAULTS = {
    "start_date": (_today - relativedelta(years=7)).isoformat(),
    "end_date":   _today.isoformat(),
    ...
}
```

**Tradeoff**: Module-level computation means the date freezes at server start, not per-request. This is acceptable: the current literal `"2026-01-29"` is already months stale, while a module-level `date.today()` is stale by at most hours/days until the next server restart or deploy. Making every consumer compute dates per-request would require significant refactoring for marginal gain.

**Note**: The performance API path already overrides `PORTFOLIO_DEFAULTS` dates dynamically per-request (app.py:1726-1732 comment: "DB stores PORTFOLIO_DEFAULTS dates (2019-2026, 7-year range) which causes 'Insufficient data' failures"). Fixing the source means all other downstream consumers get reasonable defaults — no need to touch individual consumer files.

#### A2. Portfolio YAML files — `portfolio.yaml` (root) + `config/portfolio.yaml`

**Current** (both files, lines 33-34):
```yaml
start_date: '2019-01-31'
end_date: '2026-01-29'
```

**Note**: `resolve_config_path("portfolio.yaml")` (config/__init__.py:7) prefers the CWD-relative root file first (line 12: `candidate.exists()`), so the root `portfolio.yaml` is the one actually loaded at runtime — not `config/portfolio.yaml`.

**Problem**: The YAML file is loaded directly by two code paths that hard-require these keys:
- `portfolio_risk_engine/data_objects.py:1081-1082` — `PortfolioData.from_yaml()` indexes `config['start_date']` / `config['end_date']` directly (KeyError if absent)
- `portfolio_risk_engine/portfolio_config.py:433` — `load_portfolio_config()` returns the raw YAML dict; downstream consumers index dates directly: `performance_analysis.py:121-122`, `portfolio_risk_score.py:2110-2111`, `scenario_analysis.py:156-157`

**Fix** (4 edits):
1. Remove `start_date` / `end_date` from **both** `portfolio.yaml` (root) and `config/portfolio.yaml`
2. In `data_objects.py:1081-1082`, use `.get()` with `PORTFOLIO_DEFAULTS` fallback:
   ```python
   from portfolio_risk_engine.config import PORTFOLIO_DEFAULTS
   start_date=config.get('start_date', PORTFOLIO_DEFAULTS['start_date']),
   end_date=config.get('end_date', PORTFOLIO_DEFAULTS['end_date']),
   ```
3. In `portfolio_config.py`, inject defaults after YAML load (after line 446):
   ```python
   from portfolio_risk_engine.config import PORTFOLIO_DEFAULTS
   cfg.setdefault('start_date', PORTFOLIO_DEFAULTS['start_date'])
   cfg.setdefault('end_date', PORTFOLIO_DEFAULTS['end_date'])
   ```
   This ensures all downstream dict-indexing consumers (`performance_analysis.py`, `portfolio_risk_score.py`, `scenario_analysis.py`) get valid dates without needing individual changes.

**Import chain**: `portfolio_risk_engine.config` (line 124) exports `PORTFOLIO_DEFAULTS`. At load time, the engine first computes env-aware defaults (`_DEFAULTS`, lines 23-31), then at lines 114-121 overwrites with `settings.PORTFOLIO_DEFAULTS` if importable. So fixing A1 (`settings.py`) makes the engine config dynamic automatically via the merge. The engine's own env var defaults (`PORTFOLIO_DEFAULT_START_DATE`, `PORTFOLIO_DEFAULT_END_DATE`) serve as standalone fallback when `settings.py` isn't importable (e.g., package used outside the monorepo).

#### A3. `portfolio_risk_engine/config.py:25-26` — standalone engine defaults

**Current**:
```python
"start_date": os.getenv("PORTFOLIO_DEFAULT_START_DATE", "2019-01-31"),
"end_date": os.getenv("PORTFOLIO_DEFAULT_END_DATE", "2026-01-29"),
```

**Problem**: Hardcoded fallback when env vars are unset. In the monorepo this is overwritten by `settings.py` (lines 114-121), but when the engine is used standalone these stale literals are the actual defaults.

**Fix**: Same dynamic computation as A1 for the hardcoded fallbacks. Env var override still takes precedence.
```python
from datetime import date
from dateutil.relativedelta import relativedelta
_today = date.today()
_default_start = (_today - relativedelta(years=7)).isoformat()
_default_end = _today.isoformat()

# In _DEFAULTS:
"start_date": os.getenv("PORTFOLIO_DEFAULT_START_DATE", _default_start),
"end_date": os.getenv("PORTFOLIO_DEFAULT_END_DATE", _default_end),
```

### Category B: Direct-mode API endpoint handlers

### B1. `app.py:1459-1460` — `/api/direct/portfolio` date defaults

**Current** (line 1459-1460):
```python
start_date=portfolio_inline.get('start_date', '2014-01-01'),
end_date=portfolio_inline.get('end_date', '2024-01-01'),
```

**Problem**: `end_date` defaults to 2024-01-01 — over 2 years stale. Analysis silently stops in the past if caller omits the field. `start_date` is hardcoded to 2014-01-01 rather than a relative lookback.

**Fix**: Use dynamic defaults computed from today's date. Follow the existing pattern at `app.py:1709-1731` which already imports `from datetime import date` and `from dateutil.relativedelta import relativedelta`.

Note: `app.py:127` imports `from datetime import datetime` (the class, not the module), so `datetime.date.today()` would fail. Use `date.today()` via a local import, matching the existing pattern.

Use `relativedelta(years=10)` for the lookback — `date.replace(year=year-10)` is not leap-safe (fails on Feb 29).

```python
from datetime import date
from dateutil.relativedelta import relativedelta
_today = date.today()
_default_end = _today.isoformat()
_default_start = (_today - relativedelta(years=10)).isoformat()
```
Then:
```python
start_date=portfolio_inline.get('start_date', _default_start),
end_date=portfolio_inline.get('end_date', _default_end),
```

**Note**: This endpoint is marked `# UNUSED BY FRONTEND` (line 1398). MCP tools are the active path. This only affects direct API callers.

### B2. `app.py:5776-5777` — `/api/direct/what-if` date defaults

**Current** (line 5776-5777):
```python
start_date=portfolio.get('start_date', '2014-01-01'),
end_date=portfolio.get('end_date', '2024-01-01'),
```

**Problem**: Identical stale defaults as #1. Code is duplicated. Additionally, the handler reads top-level `what_if_request.start_date` / `what_if_request.end_date` at lines 5747-5748 but then ignores them — only `portfolio.get(...)` is used for the `PortfolioData.from_holdings()` call.

**Fix**: Same dynamic default pattern as #1, plus fix the precedence bug: top-level request dates should override nested portfolio dates, then fall back to dynamic defaults.

```python
from datetime import date
from dateutil.relativedelta import relativedelta
_today = date.today()
_default_end = _today.isoformat()
_default_start = (_today - relativedelta(years=10)).isoformat()

# Precedence: top-level request dates > nested portfolio dates > dynamic defaults
_start = start_date or portfolio.get('start_date', _default_start)
_end = end_date or portfolio.get('end_date', _default_end)
```
Then use `_start` / `_end` in the `PortfolioData.from_holdings()` call.

### B3-B6. Four additional `/api/direct/*` endpoints — same precedence bug + no fallback

All four share the same pattern: the request model has top-level `start_date`/`end_date` fields, but the handler only reads `portfolio_data.get('start_date')` from the nested portfolio dict — ignoring the top-level fields. And unlike #1/#2, these pass `None` (no default at all) if the caller omits dates, which can cause downstream validation failures (e.g., `validation_service.py:141-145`).

| # | Endpoint | Handler line | Model |
|---|----------|-------------|-------|
| 3 | `/api/direct/optimize/min-variance` | `app.py:5940-5943` | `DirectOptimizeRequest` (L723) |
| 4 | `/api/direct/optimize/max-return` | `app.py:6086-6089` | `DirectOptimizeRequest` (L723) |
| 5 | `/api/direct/performance` | `app.py:6197-6200` | `DirectPerformanceRequest` (L736) |
| 6 | `/api/direct/interpret` | `app.py:6374-6377` | `DirectInterpretRequest` (L749) |

**Fix**: Same pattern as #2 — add dynamic defaults + precedence resolution in each handler:
```python
from datetime import date
from dateutil.relativedelta import relativedelta
_today = date.today()
_default_end = _today.isoformat()
_default_start = (_today - relativedelta(years=10)).isoformat()

# Precedence: top-level request dates > nested portfolio dates > dynamic defaults
_start = optimize_request.start_date or portfolio_data.get('start_date') or _default_start
_end = optimize_request.end_date or portfolio_data.get('end_date') or _default_end
```
Then pass `_start` / `_end` to `PortfolioData.from_holdings()`.

### Category C: Frontend

### C1. `frontend/packages/ui/src/components/layouts/DashboardLayout.tsx:55` — copyright year

**Current**:
```tsx
<p>© 2024 Portfolio Risk Analysis. All rights reserved.</p>
```

**Fix**:
```tsx
<p>© {new Date().getFullYear()} Portfolio Risk Analysis. All rights reserved.</p>
```

---

## What NOT to change (audit found, no action needed)

| Location | What | Why skip |
|----------|------|----------|
| `app.py:1418-1419` | Docstring example dates | Illustrative only, not runtime |
| `mcp_server.py:1063` | Docstring example `"2024"` | LLM usage hint |
| `mcp_tools/performance.py:539` | Docstring example | LLM usage hint |
| `scripts/collect_all_schemas.py` | Schema sample dates | Dev script, not production |
| `scripts/ibkr_cash_backsolve.py` | Statement period | Diagnostic, intentionally pinned |
| `scripts/ibkr_nav_monkey.py` | Target dates | Diagnostic, intentionally pinned |
| `core/result_objects/*.py`, `data_objects.py` | Docstring examples | Illustrative only |
| `recovery/risk-analysis-dashboard.tsx` | Mock timeline data | Recovery artifact, not rendered |
| `charts/examples/ChartExamples.tsx` | Demo chart data | Example component |
| `frontend/openapi-schema.json`, `api-generated.ts` | Generated schema with example dates from docstrings | Generated artifacts — update if docstrings change, but not runtime |
| `/api/direct/stock` (`app.py:5606`, model L697) | Top-level `start_date`/`end_date` passed through | Not buggy — `analyze_stock()` resolves `None` dynamically (5y lookback + today) at `portfolio_risk_engine/stock_analysis.py:180-181` |
| `settings.py:204` — `FACTOR_INTELLIGENCE_DEFAULTS["start_date"]` | `"2010-01-31"` | Intentional long lookback for factor analysis — 15+ years of data needed for meaningful factor correlations. Not a "current window" date. Used by `services/factor_intelligence_service.py:129`. |

---

## Decisions

### Already-persisted DB portfolio rows
Existing DB rows were written with the legacy `PORTFOLIO_DEFAULTS` dates (`2019-01-31` / `2026-01-29`). Changing the defaults only affects future saves.

**Affected paths that read stored dates directly**:
- `/api/analyze` (app.py:1239) — loads portfolio snapshot with DB-stored dates
- `/api/risk-score` (app.py:1558) — same
- `config_adapters.py:65-66` — `resolve_portfolio_config()` uses stored dates
- `portfolio_service.py:769-776` — service layer reads stored dates
- `portfolio_risk_score.py:1158-1162` — risk score uses stored window

The performance API (app.py:1726-1732) already overrides stored dates dynamically per-request, but these other paths do not.

**Decision**: Accept for this plan. The stored `end_date: '2026-01-29'` is only ~2 months stale (not years), and the 7-year window is a reasonable analysis range. A one-time `UPDATE` to set `end_date = CURRENT_DATE` on existing rows would be safe but is a separate DB migration concern — not part of this code audit. If needed, it can be a follow-up one-liner.

---

## Implementation notes

- Tests:
  1. **`PORTFOLIO_DEFAULTS` dynamic** — verify `settings.PORTFOLIO_DEFAULTS["end_date"]` is not a hardcoded literal (i.e., matches today's date)
  2. **Engine config standalone** — reload `portfolio_risk_engine.config` with `settings` unimportable, verify `PORTFOLIO_DEFAULTS` dates are dynamic. Also test env var override: set `PORTFOLIO_DEFAULT_END_DATE=2099-01-01`, reload, verify it takes precedence.
  3. **YAML fallback** — load a portfolio YAML without `start_date`/`end_date` keys, verify `PortfolioData.from_yaml()` and `load_portfolio_config()` both produce dynamic dates (not KeyError)
  4. **Direct endpoint date precedence** — extract the date-resolution logic into a shared helper (e.g., `_resolve_direct_dates(top_level_start, top_level_end, portfolio_dict)`) and test it once. All 6 direct handlers call this helper. Test cases: (a) all None → dynamic defaults, (b) top-level set → overrides nested, (c) only nested set → used, (d) both set → top-level wins.
- The two `app.py` sites compute defaults inside the handler (not module-level) so the date is fresh per-request, not stale from server boot time.
- `app.py:127` imports `from datetime import datetime` (the class). Use `from datetime import date` locally in each handler, matching the existing pattern at line 1709.
- `dateutil.relativedelta` is already used in `app.py` (line 1710) — no new dependency.
- Use `relativedelta(years=10)` not `date.replace(year=year-10)` — the latter fails on Feb 29 leap years.
- After all changes are implemented and tested, update `docs/TODO.md:19` bug row status from `NEEDS AUDIT` to `DONE`.

## Codex review history

- **v1 FAIL**: (1) `datetime.date.today()` wrong — `datetime` is imported as the class, not the module. (2) `_today.replace(year=_today.year - 10)` not leap-safe. (3) `/api/direct/what-if` ignores top-level `start_date`/`end_date` — precedence bug. (4) Missing generated artifacts (`openapi-schema.json`, `api-generated.ts`) from "no action" list.
- **v2**: All 4 issues addressed.
- **v2 FAIL**: 4 additional `/api/direct/*` endpoints (`min-variance`, `max-return`, `performance`, `interpret`) have the same top-level-ignored + no-fallback date bug. Plan scope was understated.
- **v3**: Added endpoints 3-6. Scope updated to 7 edits across 2 files.
- **v3 FAIL**: `/api/direct/stock` also has date fields but is NOT buggy — `analyze_stock()` resolves `None` dynamically. Should be listed in "no action" table for audit completeness.
- **v4 FAIL**: `PORTFOLIO_DEFAULTS` in `settings.py:36` and `portfolio_risk_engine/config.py:23` are the root source of hardcoded dates, consumed by `portfolio_manager.py:174`, `portfolio_assembler.py:318`, `routes/plaid.py:1079`, `providers/plaid_loader.py:483`. Also stale "two affected API endpoints" text. Also `stock_analysis.py` path should be fully qualified.
- **v5 FAIL**: (1) Background still said "7 issues" and "only direct API callers" — Category A reaches active non-direct paths (MCP tools, services, provider loaders). (2) Consumer list incomplete — missing `legacy_portfolio_file_service.py`, `snaptrade_loader.py`, `proxy_builder.py`, `data_objects.py`. (3) `stock_analysis.py` line ref wrong (129→180-181). (4) `FACTOR_INTELLIGENCE_DEFAULTS["start_date"]` at `settings.py:204` not listed.
- **v6 FAIL**: Module-level computation freezes at server start, so "fresh dates automatically" wording is inaccurate for long-running servers.
- **v7 FAIL**: (1) `config/portfolio.yaml:33-34` has hardcoded dates, bypasses `PORTFOLIO_DEFAULTS` via YAML loader. (2) Already-persisted DB rows keep legacy dates — need explicit decision. (3) "No tests needed" not credible for this scope. (4) None→str failure reasoning inaccurate (actual failure at validation_service, not from_holdings). (5) TODO.md update premature.
- **v8 FAIL**: (1) A2 under-specified — didn't name concrete code edits for YAML loader fallback (`data_objects.py:1081-1082`, `portfolio_config.py:446`). (2) DB decision didn't name affected paths (`/api/analyze`, `/api/risk-score`, `config_adapters.py`, `portfolio_service.py`, `portfolio_risk_score.py`).
- **v9 FAIL**: (1) Root `portfolio.yaml` also exists with same hardcoded dates, and `resolve_config_path()` prefers it over `config/portfolio.yaml`. (2) Engine-side fallback should use `portfolio_risk_engine.config.PORTFOLIO_DEFAULTS` (with env var overrides), not `settings.PORTFOLIO_DEFAULTS`.
- **v10 FAIL**: (1) `get_config()` doesn't exist in `portfolio_risk_engine/config.py`. (2) `settings.PORTFOLIO_DEFAULTS` overwrites engine's env-derived `_DEFAULTS` at lines 114-121, so env vars are effectively dead when settings is importable — rationale for switching away from settings was false.
- **v11 FAIL**: (1) Test plan too weak — "one test" for direct endpoints doesn't cover 5 copy-pasted sites; should factor into helper + test helper. (2) No test for engine config standalone/env-var branch.
- **v12**: Test plan expanded to 4 specific tests. Direct endpoint date resolution factored into shared helper `_resolve_direct_dates()` — test helper once, all 6 handlers use it. Engine config standalone test with reload + env var override.

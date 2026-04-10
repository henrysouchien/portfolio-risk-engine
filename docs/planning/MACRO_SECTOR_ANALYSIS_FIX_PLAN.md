# Plan: Fix `get_sector_analysis` (macro-mcp) — FMP "endpoint unavailable"

> **Revised 2026-04-08 — addresses Codex review v1 (1 BLOCKING + 2 MAJOR + 1 MINOR).** Iteration 2.

**Bug**: E15 — `get_sector_analysis` in `macro-mcp` reports `"FMP sector performance unavailable"` (and intermittently `"FMP sector PE unavailable"`), so the analyst agent loses sector context.
**Where (cross-repo)**: The buggy code lives in `investment_tools/macro_mcp/_fmp.py`, NOT in `risk_module`. We track the bug here because the analyst agent that surfaces the error runs in this stack.
**Severity**: Medium. **Scope**: Small. Core fix (B1a + B1b + B2): ~15 LOC across one helper + two functions in `_fmp.py`. Optional 3d migration (C4): adds ~15 LOC. Plus tests. No API contract change for downstream callers.
**Status**: v2 — pending Codex re-review. Reopens E15 — the prior closure as `CLOSED — INVALID` was wrong (see Section 0).

---

## 0. Reopening Note (TODO Housekeeping)

`docs/TODO.md` currently lists E15 as `~~CLOSED — INVALID~~` with the rationale:

> "Stale reference. Function doesn't exist; actual `get_sector_overview` in `fmp/tools/market.py:508` works fine."

That closure is wrong. The closer confused two different tools:

| Tool | Server | Status |
|------|--------|--------|
| `get_sector_overview` | `fmp-mcp` (`fmp/tools/market.py:508`) | Works fine. Has its own `_last_trading_day()` defaulting and `fetch_params={"date": ...}` (see `fmp/tools/market.py:584-591`). |
| `get_sector_analysis` | `macro-mcp` (`investment_tools/macro_mcp/server.py:622`) | **Broken**. Calls `_fmp.fetch_sector_performance()` (line 631) and `_fmp.fetch_sector_pe()` (line 638), both of which either omit or mis-default the `date` param. |

`get_sector_analysis` is registered as an MCP tool name (verified by `tests/smoke/test_macro_mcp.py:14` which lists it in `EXPECTED_TOOL_NAMES`). The original E15 description from the TODO history was accurate:

> "FMP `fetch_sector_performance()` returns unavailable (`macro_mcp/_fmp.py`). PE endpoint works, but performance/changesPercentage is missing."

This plan reopens E15 and supersedes the bad closure.

---

## 1. Bug Summary

`get_sector_analysis` (macro-mcp) returns `status="error"` with `error="No sector analysis available"` and warnings of the form:

```
sector.performance: FMP sector performance unavailable
sector.pe: FMP sector PE unavailable
```

**Three distinct underlying failures** combine into the same observable symptom — the first two cause the HTTP 400 / `None` payloads; the third would still produce empty leaders/laggards even after the first two are fixed:

| # | Function | File:Line | Failure mode |
|---|----------|-----------|--------------|
| B1a | `fetch_sector_performance` | `investment_tools/macro_mcp/_fmp.py:55-59` | Calls `https://financialmodelingprep.com/stable/sector-performance-snapshot` with **no `date` query parameter**. FMP returns HTTP 400 with body `Query Error: Invalid or missing query parameter - date` (live-verified 2026-04-07). The bare `try/except: return None` swallows the error. |
| B1b | `fetch_sector_performance` | `investment_tools/macro_mcp/_fmp.py:64-76` | **Parser schema mismatch.** Even after B1a is fixed, the parser only reads `changesPercentage` / `changePercentage` / `changesPercentage1D` / `performance`. The live FMP `sector-performance-snapshot` response uses `averageChange` (live-verified 2026-04-07: `{"date":"2026-04-06","sector":"Basic Materials","exchange":"NASDAQ","averageChange":-0.749…}`). Without adding `averageChange`, every parsed row has `changesPercentage=None`, `_sorted_non_null` filters them all out, and `leaders`/`laggards` come back empty. |
| B2 | `fetch_sector_pe` | `investment_tools/macro_mcp/_fmp.py:79-85` | Defaults `date_value` to `date.today().isoformat()`. On weekends, holidays, and pre-close on a trading day, the snapshot for "today" does not yet exist and FMP returns HTTP 400 (or empty). |

**Why all three matter**: B1a alone returns 400. Fixing only B1a (passing `date=...`) gets the request through, but B1b means rows still parse as `None` and the tool silently degrades to empty leaders/laggards (the same observable broken state as before, just via a different failure mode). B2 is intermittent — fixing B1a/B1b gets weekday afternoons working, fixing B2 gets weekends and pre-market working.

The previous reviewer (Codex review v1, 2026-04-07) caught B1b live by querying the stable endpoint with `date=2026-01-19` and observing the `averageChange` rows. The working `fmp-mcp` sibling already handles this — see `fmp-mcp-dist/fmp/tools/market.py:1048` and `:1129`, both of which accept `changesPercentage`/`changePercentage`/`averageChange` as fallbacks.

---

## 2. Reproduction

### 2a. Live FMP probes (verify B1a and B1b)

**B1a — missing `date` returns 400** (live-verified 2026-04-07 via direct urllib call against the FMP key from `investment_tools/.env`):

```
GET https://financialmodelingprep.com/stable/sector-performance-snapshot?apikey=…
→ HTTP 400  Query Error: Invalid or missing query parameter - date

GET https://financialmodelingprep.com/stable/sector-performance-snapshot?date=2026-04-06&apikey=…
→ HTTP 200
→ [{"date":"2026-04-06","sector":"Basic Materials","exchange":"NASDAQ","averageChange":-0.749…}, …]   # 11 rows
```

**B1b — schema uses `averageChange`, not `changesPercentage`** (same probe, response keys: `["date", "sector", "exchange", "averageChange"]`). Cross-checked via `mcp__fmp-mcp__get_sector_overview(format="full", use_cache=False)` which returns the same `averageChange` values for 2026-04-07.

The current macro-mcp parser at `investment_tools/macro_mcp/_fmp.py:71-73` looks at `changesPercentage` / `changePercentage` / `changesPercentage1D` / `performance` — none of which exist in the live response, so every row parses with `changesPercentage=None`.

The fmp-mcp wrapper documents the date requirement (`fmp-mcp-dist/fmp/tools/market.py:584` comment: `# Build fetch params — FMP requires a date param for snapshot endpoints`) and always passes `date=_last_trading_day()`. It also handles the `averageChange` schema in two places:
- `_merge_sector_pe()` at `fmp-mcp-dist/fmp/tools/market.py:1048` — `row.get("changesPercentage", row.get("averageChange", row.get("change_pct")))`
- `_get_change_pct()` at `fmp-mcp-dist/fmp/tools/market.py:1129` — iterates `["changesPercentage", "changePercentage", "averageChange"]`

### 2b. Programmatic repro from macro-mcp (no FMP changes needed)

```python
from investment_tools.macro_mcp.server import get_sector_analysis
result = get_sector_analysis()
# Expected (broken):
# {"status": "error",
#  "as_of": "2026-04-07",
#  "warnings": ["sector.performance: FMP sector performance unavailable", ...],
#  "sectors": None, "leaders": None, "laggards": None,
#  "error": "No sector analysis available"}
```

### 2c. Why no test caught this

`tests/smoke/test_macro_mcp.py:32-77` (`test_fmp_wrapper_endpoints`) **mocks `get_json`** so it never validates URLs against real FMP — it only asserts that the URL string starts with `https://financialmodelingprep.com/stable/`. `tests/integration/test_macro_mcp_live.py` covers `get_macro_dashboard`, `get_economic_indicators`, and `get_positioning` — but NOT `get_sector_analysis` or `get_technical_summary`. The test gap is structural, not coincidental.

---

## 3. Root Cause (with file:line refs)

### 3a. B1a — missing `date` query parameter

```python
# investment_tools/macro_mcp/_fmp.py:55-59
def fetch_sector_performance() -> list[dict[str, Any]] | None:
    try:
        payload = get_json("https://financialmodelingprep.com/stable/sector-performance-snapshot")
    except Exception:
        return None
```

No `date_value` parameter, no `?date=...` in the URL. FMP's stable `sector-performance-snapshot` endpoint requires `date`. Live probe (Section 2a) shows HTTP 400 with body `Query Error: Invalid or missing query parameter - date`. Compare with the working sibling `fetch_sector_pe` on line 79 which does pass `?date=...`.

### 3b. B1b — parser doesn't read `averageChange`

```python
# investment_tools/macro_mcp/_fmp.py:64-76
results = []
for item in payload:
    if not isinstance(item, dict):
        continue
    results.append(
        {
            "sector": str(_pick(item, "sector", "name", "sectorName") or ""),
            "changesPercentage": _as_float(
                _pick(item, "changesPercentage", "changePercentage", "changesPercentage1D", "performance")
            ),
        }
    )
```

The live FMP `sector-performance-snapshot` response (verified 2026-04-07) ships rows with the keys `["date", "sector", "exchange", "averageChange"]` — note the absence of `changesPercentage` and any of the other three fallbacks the parser is looking for. After fixing B1a (so the request returns 200), every parsed row would have `changesPercentage=None`, and `_sorted_non_null(sectors, "changesPercentage", …)` in `server.py:648-649` would filter them all out. `leaders` and `laggards` come back as empty lists, `_merge_sector_rows` produces sector rows that only carry the `pe` half, and the end result is a "successful" `get_sector_analysis` call that the analyst agent still finds useless.

The fix is the same shape as fmp-mcp's two `_get_change_pct()` / `_merge_sector_pe()` helpers (`fmp-mcp-dist/fmp/tools/market.py:1048` and `:1129`): add `averageChange` to the `_pick(...)` fallback list. One-line change.

### 3c. B2 — defaulting to `date.today()` instead of last trading day

```python
# investment_tools/macro_mcp/_fmp.py:79-85
def fetch_sector_pe(date_value: str | None = None) -> list[dict[str, Any]] | None:
    target_date = date_value or date.today().isoformat()
    endpoint = f"https://financialmodelingprep.com/stable/sector-pe-snapshot?date={target_date}"
    try:
        payload = get_json(endpoint)
    except Exception:
        return None
```

`date.today()` resolves to the calendar date in the server's local time. The snapshot for "today" is not published until after market close (and not at all on weekends/holidays), so `get_sector_analysis` is intermittently broken even after B1a/B1b are fixed. The fmp-mcp project hit the same problem and resolved it by always defaulting to `_last_trading_day()` (`fmp-mcp-dist/fmp/tools/_helpers.py:6-12`):

```python
def _last_trading_day() -> str:
    """Return the most recent weekday as YYYY-MM-DD (skips weekends)."""
    d = date.today()
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()
```

The same default needs to land in `fetch_sector_performance` (after the B1a fix adds the `date_value` param) so both snapshot wrappers use one consistent fallback.

### 3d. Watch-item — `fetch_historical_price` (currently working v3 path)

```python
# investment_tools/macro_mcp/_fmp.py:135-149
def fetch_historical_price(symbol: str, limit: int) -> list[dict[str, Any]] | None:
    ...
    endpoint = f"historical-price-full/{clean_symbol}?serietype=line&limit={clean_limit}"
```

This path resolves to `https://financialmodelingprep.com/api/v3/historical-price-full/SPY?serietype=line&limit=200` because the bare URL falls through to `fmp/api.py`'s legacy `BASE_URL`. **Live-verified 2026-04-07 with the FMP key from `investment_tools/.env`:** the v3 endpoint still returns HTTP 200 with the `{"symbol": "...", "historical": [...]}` shape (8353 records returned for `SPY`). `get_technical_summary` succeeds today for SPY/QQQ/IWM/DIA.

So this is **not a verified root cause of E15**. The first version of this plan (Plan v1) treated it as B3 and assumed it was broken on the basis of the prior `screen_estimate_revisions` v3→stable migration. Codex review v1 caught the assumption and live-tested the endpoint. The deprecation is real and likely upcoming, but it has not happened yet.

**Decision**: keep this as opportunistic migration debt in scope (path B from Codex review v1 finding #2), tightly bounded to one-line `endpoint = …` and parser changes in `fetch_historical_price` only. **Reasoning**: we are already touching `_fmp.py` for the sector fixes, the migration is small (~10 LOC), and bundling it lets us add the `get_technical_summary` live integration test (T6) at the same time. It is **not** presented as a fix for E15 — it is a proactive migration that lets the file converge on the stable API and reduces the chance of an analyst-agent outage when FMP eventually retires the v3 path. If the next reviewer prefers to defer it, dropping it costs ~10 LOC in C4 and one test (T6).

### 3e. Watch-item — `fetch_index_quotes` on v3 base

```python
# investment_tools/macro_mcp/_fmp.py:33-34
payload = get_json(f"quote/{','.join(clean_symbols)}")
```

`quote/{symbols}` is registered in `fmp-mcp-dist/fmp/registry.py:986-991` as `api_version="v3"`, so the v3 base URL is intentional and currently works (verified live: `mcp__fmp-mcp__fmp_fetch(endpoint="quote", symbol="SPY")` returns 200). Not changing this in this plan, but flagged in Section 7 as a future migration target.

---

## 4. Fix Approach (with rationale)

Mirror the conventions already proven in `fmp-mcp` (`fmp/tools/market.py` and `_helpers.py`):

1. Always pass an explicit `date=_last_trading_day()` to the snapshot endpoints (fixes B1a + B2).
2. Add `averageChange` to the parser fallback list in `fetch_sector_performance` so the post-200 rows actually contain values (fixes B1b).
3. Opportunistically migrate `fetch_historical_price` to the stable `historical-price-eod/full` contract while we're already touching the file (3d — tech debt, not a verified root cause).

**Why a date helper instead of inlining `date.today() - timedelta(days=...)`:** the helper is the canonical pattern in `fmp-mcp-dist/fmp/tools/_helpers.py:6` and gets the weekend skip right. Inlining `date.today() - 1` would be wrong on Sundays (yields Saturday). Importing the fmp-mcp helper across repos creates an unwanted runtime coupling — re-implementing the 7-line helper locally is cleaner and matches how `fetch_treasury_rates` already does its own date math at line 109-110.

**Why touch `fetch_sector_pe` even though "the PE endpoint works":** B2 is intermittent. It works most of the time on a US-east weekday afternoon (which is when the original investigator probably tested), and breaks predictably on weekends/holidays/pre-market. Leaving B2 unfixed means the bug returns Saturday morning. The fmp-mcp wrapper learned this lesson; we should adopt it.

**Why B1b (parser) is non-negotiable:** B1a and B1b are independent failures. Fixing only B1a would change the symptom from "HTTP 400 → null payload → all-error envelope" to "HTTP 200 → all-`None` parser output → empty leaders/laggards". Both states look broken to the analyst agent. The Codex v1 review caught this by live-probing the schema, and `_sorted_non_null` in `server.py:648-649` confirms the failure mode by source-reading the call path.

**Why we still touch `fetch_historical_price` (3d) even though it works today:** the FMP stable migration is happening across multiple v3 endpoints (`screen_estimate_revisions` was the last casualty in `Edgar_updater/docs/plans/completed/FMP_STABLE_API_MIGRATION_PLAN.md`). Bundling the migration here is cheap because we're already in the file, and it lets us add a live integration test (T6) for `get_technical_summary` that closes a structural test gap. The plan is explicit that this is **opportunistic migration debt, not an E15 root cause** — if the reviewer or implementer wants to defer it, drop C4 and T6 and the rest of the plan still fixes E15.

---

## 5. Files to Change

| # | File | Function | Lines | Change |
|---|------|----------|-------|--------|
| C1 | `investment_tools/macro_mcp/_fmp.py` | new helper | after line 26 (`_as_float`) | Add `_last_trading_day()` returning the most recent weekday `YYYY-MM-DD` (subtract at least 1 day, then skip weekends). |
| C2a | `investment_tools/macro_mcp/_fmp.py` | `fetch_sector_performance` (signature/URL) | 55-59 | **Fixes B1a.** Add `date_value: str \| None = None` parameter; default to `_last_trading_day()`; build URL as `https://financialmodelingprep.com/stable/sector-performance-snapshot?date={target_date}`. |
| C2b | `investment_tools/macro_mcp/_fmp.py` | `fetch_sector_performance` (parser) | 64-76 | **Fixes B1b.** Add `"averageChange"` to the `_pick(...)` fallback list inside the `changesPercentage` accessor — i.e. `_pick(item, "changesPercentage", "changePercentage", "averageChange", "changesPercentage1D", "performance")`. Mirror the order/precedence used at `fmp-mcp-dist/fmp/tools/market.py:1129` for consistency. The output dict still keys it as `changesPercentage` because `_merge_sector_rows` and `_sorted_non_null` in `server.py` already read that key — no server-side changes needed. |
| C3 | `investment_tools/macro_mcp/_fmp.py` | `fetch_sector_pe` | 79-81 | **Fixes B2.** Replace `date.today().isoformat()` with `_last_trading_day()` as the default. (Function signature already accepts `date_value`, so external callers passing a date keep working.) |
| C4 | `investment_tools/macro_mcp/_fmp.py` | `fetch_historical_price` | 135-149 | **Opportunistic migration (3d).** Repoint to `https://financialmodelingprep.com/stable/historical-price-eod/full?symbol={symbol}&from={start}&to={end}`. Compute `from = today - (limit * 1.5)` calendar days, parse the flat-list response (live-verified shape: descending date order, keys `symbol/date/open/high/low/close/volume/change/changePercent/vwap`), reverse to ascending, then truncate to the last `limit` rows. **Drop this row if reviewer prefers to defer 3d** — see Section 4 reasoning. |
| C5 | `investment_tools/macro_mcp/server.py` | (no change) | n/a | Two callsites benefit automatically: (1) `get_sector_analysis` at `server.py:621-657` calls `_fmp.fetch_sector_performance()` (line 631) and `_fmp.fetch_sector_pe()` (line 638). (2) `get_macro_dashboard` at `server.py:282-…` uses the inner closures `_fetch_sector_perf()` (line 304-311) and `_fetch_sector_pe()` (line 313-320), which both call the same `_fmp.fetch_sector_performance()` / `_fmp.fetch_sector_pe()` wrappers. (3) `get_technical_summary` at `server.py:660-689` calls `_fmp.fetch_historical_price()` and benefits if C4 ships. No `server.py` edits required for any of these. |

### 5a. Note on C4 windowing

The current `fetch_historical_price(symbol, limit=200)` returns the last `limit` daily closes (used by `_compute_symbol_summary` for SMA-200 + RSI-14 calculations). The new stable endpoint takes `from`/`to` dates and returns rows in that window. Pick `from = today - (limit * 1.5)` calendar days to comfortably yield ≥200 trading days, then truncate to the last `limit` rows after parsing. The 1.5x buffer accounts for weekends + holidays without needing a full trading-day calculator. This matches the pattern in `fmp-mcp-dist/fmp/tools/market.py` for similar window-based fetches.

### 5b. Tests to add

> **Note on the existing test gap**: the current `test_fmp_wrapper_endpoints` mock at `tests/smoke/test_macro_mcp.py:47` returns `[{"sector": "Technology", "changesPercentage": 1.5, "pe": 28.0, "date": "2026-03-25"}]` — i.e. it uses `changesPercentage`, the same key the parser is looking for. That mock matches the parser's bug-for-bug, which is exactly why the test passes today even though production is broken. T1 below replaces the mock data with the real `averageChange` schema so the parser fix is actually exercised.

| # | File | Test | What it asserts |
|---|------|------|-----------------|
| T1 | `investment_tools/tests/smoke/test_macro_mcp.py` (rewrite the sector branch of `test_fmp_wrapper_endpoints`) | Parser returns non-`None` `changesPercentage` when the mock payload uses `averageChange` | **Regression guard for B1a + B1b.** Update `fake_get_json` so the sector-performance branch returns the real live shape: `[{"date": "2026-04-06", "sector": "Technology", "exchange": "NASDAQ", "averageChange": 1.5}]`. Assert (a) the recorded URL contains `?date=` (B1a), and (b) `_fmp.fetch_sector_performance()` returns `[{"sector": "Technology", "changesPercentage": 1.5}]` — i.e. the new `averageChange` fallback is wired through (B1b). The current assertion `== [{"sector": "Technology", "changesPercentage": 1.5}]` continues to hold but only because the parser change reads `averageChange` and re-keys it. If the parser fix is missing, this test will fail with `changesPercentage=None`. |
| T2 | `investment_tools/tests/smoke/test_macro_mcp.py` | `fetch_sector_pe()` (no arg) defaults to a weekday, never to Saturday/Sunday | Regression guard for B2. Freeze `date.today()` to a Sunday via monkeypatch (`monkeypatch.setattr("investment_tools.macro_mcp._fmp.date", FakeDate)` where `FakeDate.today() == date(2026, 4, 5)` Sunday) and assert the recorded URL contains `date=2026-04-03` (the prior Friday). Add a parallel assertion for `fetch_sector_performance()` once C2a/C3 land — both should land on the same Friday. |
| T3 | `investment_tools/tests/smoke/test_macro_mcp.py` (only if C4 ships) | `fetch_historical_price` request shape and parser | **Regression guard for 3d.** Update `fake_get_json` so the historical branch returns the real stable shape: a flat list `[{"symbol": "SPY", "date": "2026-04-07", "close": 659.22, "open": ..., "high": ..., "low": ..., "volume": ...}, {"symbol": "SPY", "date": "2026-04-04", "close": 657.50, ...}, ...]` in **descending** date order (live-verified shape). Assert (a) the recorded URL contains `historical-price-eod/full?symbol=SPY&from=` and is on the `https://financialmodelingprep.com/stable/` base, (b) the parser returns rows in **ascending** date order (current behavior — verified by the existing test asserting `[{"date": "2026-03-24", ...}, {"date": "2026-03-25", ...}]`), (c) the parser truncates to `limit` rows when the response has more rows than `limit`. **Drop this test if C4 is deferred.** |
| T4 | `investment_tools/tests/smoke/test_macro_mcp.py` | `_last_trading_day()` skips Saturday→Friday and Sunday→Friday and a Monday returns the prior Friday | Direct unit coverage of the new helper. Five frozen-`date` cases: Wednesday → prior Tuesday, Friday → prior Thursday, Saturday → prior Friday, Sunday → prior Friday, Monday → prior Friday. (The Monday case matters because `_last_trading_day()` always subtracts at least one day before checking weekday — verified against `fmp-mcp-dist/fmp/tools/_helpers.py:6-12`.) |
| T5 | `investment_tools/tests/integration/test_macro_mcp_live.py` (new test) | `get_sector_analysis()` returns `status="success"` **AND** non-empty `sectors` **AND** at least one row with non-`None` `changesPercentage` **AND** non-empty `leaders` **AND** non-empty `laggards` | **End-to-end proof for B1a + B1b + B2.** Mark with `@pytest.mark.live` like the existing tests in this file. The non-empty `leaders`/`laggards` assertions are the critical part — `status="success"` alone would still pass under the B1b-only failure mode. |
| T6 | `investment_tools/tests/integration/test_macro_mcp_live.py` (only if C4 ships) | `get_technical_summary()` returns `status="success"` for at least one of `["SPY", "QQQ", "IWM", "DIA"]` and the symbol payload contains numeric `sma_200` / `rsi_14` (or whatever fields `_compute_symbol_summary` produces) | Live integration coverage for the migrated `fetch_historical_price`. **Note**: this test would already pass before migration since the v3 `historical-price-full` endpoint still works today; its real value is locking in the new contract so a future v3 deprecation is caught loudly. **Drop this test if C4 is deferred.** |
| T7 | `risk_module/docs/TODO.md` | Edit | Reopen E15: replace the strikethrough `CLOSED — INVALID` row with `READY TO IMPLEMENT` and a `Plan: MACRO_SECTOR_ANALYSIS_FIX_PLAN.md` reference. |

---

## 6. Test Plan / Verification

### 6a. Local unit + smoke (no FMP key required)

```bash
cd ~/Documents/Jupyter/investment_tools
python3 -m pytest tests/smoke/test_macro_mcp.py -v -k "test_fmp_wrapper_endpoints or test_last_trading_day"  # T1-T4
```

### 6b. Live integration (requires FMP_API_KEY)

```bash
cd ~/Documents/Jupyter/investment_tools
python3 -m pytest tests/integration/test_macro_mcp_live.py -v -m live -k "sector_analysis or technical_summary"  # T5 (and T6 if C4 ships)
```

### 6c. End-to-end via the analyst agent

After the fix is deployed in `investment_tools`, restart any running `macro-mcp` MCP server process so the analyst agent picks up the new code. From a Claude session connected to the analyst agent, ask: *"What's the sector picture today?"* — expect a non-empty leaders/laggards summary, no `"FMP sector performance unavailable"` warnings.

### 6d. Weekend regression check

Run `get_sector_analysis()` on a Saturday or Sunday (or freeze `date.today()` in a manual REPL session). Pre-fix: `status="error"`. Post-fix: `status="success"` with the prior Friday's snapshot.

---

## 7. Risks / Out of Scope

### Risks (low)

- **C4 schema change** (only if C4 ships): the old `historical-price-full` response is `{"symbol": "...", "historical": [...]}` (live-verified 2026-04-07: 8353 records returned for SPY); the new `historical-price-eod/full` response is a flat list of `{"symbol", "date", "open", "high", "low", "close", "volume", "change", "changePercent", "vwap"}` records in **descending** date order (live-verified 2026-04-07: `from=2026-03-01&to=2026-04-07` returned 26 rows for SPY). The parser in `fetch_historical_price` currently reads `payload.get("historical")` and reverses to ascending — it needs to change to iterate the list directly and reverse for ascending order. The smoke test mock at `tests/smoke/test_macro_mcp.py:39-46` returns the OLD shape and must update in lockstep with the production change (T3).

- **Date alignment vs FMP cache**: `_last_trading_day()` (`fmp-mcp-dist/fmp/tools/_helpers.py:6-12`) **always returns the prior weekday** — it subtracts at least one day from `date.today()` before doing the weekend skip. So a Tuesday call returns Monday, a Friday call returns Thursday, etc. This means we never ask FMP for "today" and we sidestep the post-close publishing-lag scenario entirely. The remaining edge case is the morning after a market holiday (e.g. Tuesday following Memorial Day Monday): `_last_trading_day()` returns Monday, but FMP only has Friday's snapshot. Mitigation: the existing `_warning(warnings, "sector.performance", exc)` flow degrades gracefully — `get_sector_analysis` still returns `status="success"` if the PE half is present (and vice versa). The `_result_or_error` envelope in `server.py:115-125` handles this. Additional mitigation if it proves flaky: fall back to "trading day − 2" on first 400. **Not adding the fallback in this plan** — keep the change minimal; revisit only if the holiday-Tuesday case shows up in production logs.

- **Cross-repo coordination**: the fix lives in `investment_tools` but the bug is tracked in `risk_module/docs/TODO.md`. The `TODO.md` reopen (T7) and the `_fmp.py` patch (C1-C4) must land together or the closed-bug status will continue to mislead future investigators.

### Out of scope (or follow-up cleanup)

- **`fetch_historical_price` v3 → stable migration (3d / C4 / T3 / T6)** — included in this plan as **opportunistic migration debt**, not a verified E15 root cause. The v3 path returns HTTP 200 today (live-verified 2026-04-07). If the implementer prefers a tighter PR, drop C4 + T3 + T6 and re-file as a follow-up. **Tech-debt tracking**: log under `docs/TODO.md` as a watch item even if deferred — we know the v3 deprecation is coming based on the prior `screen_estimate_revisions` migration, and we don't want to lose track of it.
- **`fetch_index_quotes` v3 migration** (Section 3e). Currently working via the v3 base URL — `mcp__fmp-mcp__fmp_fetch(endpoint="quote", symbol="SPY")` returns 200 today. Migrating to the stable equivalent is a separate cleanup task and would risk widening this PR.
- **Adding a shared `_last_trading_day` utility across `risk_module`/`investment_tools`/`fmp-mcp`**. Three copies exist (one in fmp-mcp, one we're adding to macro-mcp, and possibly more in `risk_module`). De-duplication is a refactor, not a bug fix.
- **Caching the snapshot for the same trading day across multiple tool calls**. The macro-mcp dashboard (`get_macro_dashboard`) and `get_sector_analysis` both call `fetch_sector_performance` and `fetch_sector_pe` — there's no shared cache. Each call is one HTTP round-trip. Adding a request-scoped cache is a perf nit, not part of this bug fix.
- **Auditing `_fmp.py` for any other deprecated v3 paths beyond the three discovered here**. A clean sweep would be valuable but is its own deliverable; this plan is focused on getting the analyst agent unblocked.

---

## 8. Cross-Repo Note

**This fix happens in `investment_tools/macro_mcp/`, not in `risk_module/`.** The risk_module repo is the front-end stack that hosts the analyst agent which surfaces the "FMP endpoint unavailable" error to users — but the buggy code lives in the macro-mcp server, which is a separate Python project.

**Tools that benefit from C1-C3** (the sector fix):
- `get_sector_analysis` — `investment_tools/macro_mcp/server.py:622-657`. Direct callsite for both `_fmp.fetch_sector_performance()` (line 631) and `_fmp.fetch_sector_pe()` (line 638).
- `get_macro_dashboard` — `investment_tools/macro_mcp/server.py:282-…`. Calls the same two wrappers indirectly via the inner closures `_fetch_sector_perf()` (line 304-311) and `_fetch_sector_pe()` (line 313-320), which run inside the dashboard's parallel-fetch block. Without the sector fix, the dashboard's "sector" payload silently degrades the same way.

**Tools that benefit from C4** (only if the opportunistic 3d migration ships):
- `get_technical_summary` — `investment_tools/macro_mcp/server.py:660-689`. Calls `_fmp.fetch_historical_price()` once per symbol.

**What changes in `risk_module`**:
- `docs/TODO.md` — reopen E15 (revert the strikethrough, set readiness to `READY TO IMPLEMENT`, link to this plan).
- `docs/planning/MACRO_SECTOR_ANALYSIS_FIX_PLAN.md` — this document.

**What changes in `investment_tools`**:
- `macro_mcp/_fmp.py` — C1, C2a, C2b, C3 (always); C4 (if 3d migration kept).
- `tests/smoke/test_macro_mcp.py` — T1, T2, T4 (always); T3 (if 3d kept).
- `tests/integration/test_macro_mcp_live.py` — T5 (always); T6 (if 3d kept).

**Deployment sequencing**:
1. Land the `investment_tools` patch.
2. Restart the running `macro-mcp` MCP server process so the analyst agent picks up the change. Look up the launchctl/systemd service via `services-mcp` (`service_list` → search for `macro-mcp`).
3. Verify both `get_sector_analysis` and `get_macro_dashboard` (the latter via the analyst agent's morning briefing flow, since `get_macro_dashboard` is the more visible callsite for users).
4. Update `risk_module/docs/TODO.md` to reflect "FIXED — verified live".

---

## 9. Prior Art

- `Edgar_updater/docs/plans/completed/FMP_STABLE_API_MIGRATION_PLAN.md` — the 2026-03-24 fix for `screen_estimate_revisions`. Same underlying class of bug (FMP stable API contract drift), different file. Reference for the URL-construction patterns and verification approach.
- `fmp-mcp-dist/fmp/tools/market.py:584-591` — the comment `# FMP requires a date param for snapshot endpoints` and the `_last_trading_day()` defaulting that this plan replicates.
- `fmp-mcp-dist/fmp/tools/_helpers.py:6-12` — canonical implementation of `_last_trading_day()`.
- `fmp-mcp-dist/fmp/registry.py:1027-1063` — current registered paths for `sector_performance_snapshot` and `sector_pe_snapshot` (both `api_version="stable"`, both with optional `date` param that is in fact required by the upstream API).
- `fmp-mcp-dist/fmp/registry.py:219-224` — current registered path for `historical_price_eod` (the stable replacement for the deprecated `historical-price-full`).

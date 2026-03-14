# Bug Report: MCP Tool Failures

Ten errors found across `analyze_stock`, `get_factor_analysis`, `get_risk_analysis`, `run_optimization`, `get_factor_recommendations`, EDGAR filing lookup, and response size limits.

---

## Bug B-015: Single-stock weight limit treats funds/ETFs as single stocks ✅ Resolved (2026-02-19)

**Symptom:**
`max_single_stock_weight` check flags diversified funds (e.g., DSU — BlackRock Debt Strategies Fund, a closed-end bond fund) as concentration violations. DSU shows as ~35% weight, triggering the single-stock weight limit, but it's inherently diversified across many underlying holdings.

**Root cause:**
The weight check in `evaluate_portfolio_risk_limits()` and the leverage capacity calculator both use raw `Portfolio Weight` without distinguishing between single stocks and diversified vehicles (CEFs, ETFs, mutual funds).

**Resolution:** Implemented in two commits:
1. `8bec0629` — Risk analysis + leverage capacity paths (B-015 part 1)
2. `55ef6ad8` — Risk score path (B-015 part 2)

Uses `DIVERSIFIED_SECURITY_TYPES` (`{"etf", "fund", "mutual_fund"}`) from `core/constants.py` to filter weights before concentration checks. Filters applied in:
- `run_portfolio_risk.py` — `evaluate_portfolio_risk_limits()`
- `core/portfolio_analysis.py` — `compute_leverage_capacity()`
- `portfolio_risk_score.py` — `calculate_concentration_risk_loss()`, `analyze_portfolio_risk_limits()`

Plans: `FUND_WEIGHT_EXEMPTION_PLAN.md` (v3), `RISK_SCORE_FUND_WEIGHT_EXEMPTION_PLAN.md` (v4).

**Files changed:**
- `core/constants.py`, `run_portfolio_risk.py`, `core/portfolio_analysis.py`, `portfolio_risk_score.py`, `services/portfolio_service.py`, `run_risk.py`

---

## Bug 18: Circular Import Warning During App/Service Bootstrap ✅ Completed (2026-02-17)

**Symptom:** Startup and smoke-test executions logged:
```
Database unavailable for crash scenarios: cannot import name 'DatabaseClient' from partially initialized module 'inputs.database_client'
```

**Root cause:** Import chain re-entered `inputs/database_client.py` during module initialization:
`inputs.database_client -> settings -> utils.security_type_mappings -> inputs.database_client`.

**Resolution (implemented):**
1. Removed module-scope dependency on `settings.PORTFOLIO_DEFAULTS` in `inputs/database_client.py`.
2. Added lazy helper `_get_portfolio_defaults()` so defaults are loaded at method call time, not import time.
3. Updated portfolio-create/save paths to use lazy-loaded defaults without changing runtime behavior.

**Validation:**
- `python3 - <<'PY'\nimport inputs.database_client\nprint('imported')\nPY` -> no circular-import warning
- `python3 - <<'PY'\nfrom app import app\nprint(len(app.routes))\nPY` -> boots successfully, no circular-import warning
- `python3 - <<'PY'\nfrom services.claude.function_executor import ClaudeFunctionExecutor\nprint('ok')\nPY` -> imports successfully, no circular-import warning
- `python3 -m py_compile inputs/database_client.py` -> passed

**Files changed:**
- `inputs/database_client.py`

---

## Bug 13: Missing FX Pair for MXN — Cash Position Treated as USD ✅ Completed (2026-02-16)

**Symptom:** Portfolio risk analysis warned:
```
Missing FX pair for MXN; treating as USD
```
which caused MXN cash positions to be valued as if 1 MXN = 1 USD.

**Root cause:** `MXN` was missing from `currency_to_fx_pair` mapping, so `fmp/fx.py` fell back to `1.0` conversion. Also, FX fetch failures for mapped currencies used the same USD fallback.

**Resolution (implemented):**
1. Added MXN pair mapping in `exchange_mappings.yaml`:
   - `MXN -> USDMXN` with `inverted: true`
2. Added static fallback rate in `exchange_mappings.yaml`:
   - `currency_to_usd_fallback.MXN = 0.055`
3. Updated `fmp/fx.py` fallback behavior:
   - When FX mapping is missing or live fetch fails, use configured static fallback rate if present before defaulting to USD `1.0`.
   - Applied to month-end rate, month-end series, and spot FX paths.
4. Added regression tests in `tests/fmp/test_fx.py`.

**Validation:**
- `pytest -q tests/fmp/test_fx.py` -> `4 passed`

**Files changed:**
- `exchange_mappings.yaml`
- `fmp/fx.py`
- `tests/fmp/test_fx.py`

---

## Bug 14: Tickers Excluded for Insufficient Price History (<12 Months) ✅ Completed (2026-02-16)

**Symptom:** Portfolio risk analysis warned:
```
EXCLUDED 2 ticker(s) with INSUFFICIENT HISTORY (<12 months): [FIG(6mo), MRP(11mo)]
```

**Root cause:** The minimum-history threshold was interpreted as monthly return observations. A "12 month" requirement effectively needed 12 returns (13 month-end prices), which excluded near-threshold names like MRP at 11 returns.

**Resolution (implemented):**
1. Made `get_returns_dataframe()` default threshold configurable from `settings.DATA_QUALITY_THRESHOLDS`.
2. Set `min_observations_for_expected_returns` default to **11** to represent ~12 months of price history (11 monthly returns).
3. Clarified exclusion logs to report **observations** (`obs`) instead of ambiguous `mo`.
4. Added regression tests for default-threshold inclusion/exclusion behavior.

**Result:**
- Near-threshold positions with ~1 year of data (11 monthly returns) are included.
- Shorter-history names (e.g., 6-10 observations) are still excluded for covariance reliability.

**Validation:**
- `pytest -q tests/test_portfolio_risk.py` -> `12 passed`

**Files changed:**
- `portfolio_risk.py`
- `settings.py`
- `tests/test_portfolio_risk.py`

---

## Bug 15: Schwab Provider Fails — Missing App Credentials ✅ Completed (2026-02-16)

**Symptom:** Portfolio MCP `get_risk_analysis` failed with:
```
Missing SCHWAB_APP_KEY or SCHWAB_APP_SECRET in environment
```
when Schwab was enabled but not fully configured.

**Root cause:** `PositionService` registered Schwab using `is_provider_enabled("schwab")` only. That allowed provider registration with missing credentials/token, then runtime fetch failed and bubbled up as a fatal error for the full analysis call.

**Resolution (implemented):**
1. Updated `PositionService` default provider registration to gate Schwab on `is_provider_available("schwab")` (enabled + credentials + token file).
2. If Schwab is enabled but unavailable, service now logs a warning and skips Schwab registration instead of hard-failing analysis.
3. Added regression test covering enabled-but-unavailable Schwab behavior.

**Result:**
- `get_risk_analysis` no longer fails solely because Schwab env vars are missing.
- Other available providers (Plaid/SnapTrade) continue to load and analysis proceeds.

**Validation:**
- `pytest -q tests/providers/test_provider_switching.py tests/providers/test_routing.py` -> `39 passed`

**Files changed:**
- `services/position_service.py`
- `tests/providers/test_provider_switching.py`

---

## Bug 17: portfolio-mcp intermittently errors: "No user specified and RISK_MODULE_USER_EMAIL not configured" ✅ Resolved (2026-02-17)

**Symptom:** Portfolio MCP tool calls sometimes failed with:
```
No user specified and RISK_MODULE_USER_EMAIL not configured
```
even though `portfolio-mcp` was configured with `RISK_MODULE_USER_EMAIL`.

**Root cause:** User resolution relied on runtime MCP process environment only. In intermittent subprocess/session contexts where env propagation was missing, tools had no fallback and raised this error.

**Resolution (implemented):**
1. Added centralized user resolution in `settings.py` with explicit precedence:
   - `user_email` argument
   - environment `RISK_MODULE_USER_EMAIL`
   - project `.env` fallback
2. Added standardized, actionable missing-user error builder with source/path diagnostics.
3. Updated portfolio-aware MCP tools to use shared resolver/error handling.
4. Added MCP diagnostic tool `get_mcp_context` to inspect runtime user resolution source (`argument`/`env`/`dotenv`) and process context.

**Validation:**
- `python3 -m py_compile settings.py mcp_server.py mcp_tools/*.py` (targeted edited modules) passed.
- Resolver smoke tests confirmed fallback behavior:
  - env missing -> `.env` source
  - env set -> `env` source
  - explicit argument -> `argument` source

**Files changed:**
- `settings.py`
- `mcp_server.py`
- `mcp_tools/positions.py`
- `mcp_tools/risk.py`
- `mcp_tools/performance.py`
- `mcp_tools/factor_intelligence.py`
- `mcp_tools/trading_analysis.py`
- `mcp_tools/income.py`
- `mcp_tools/tax_harvest.py`
- `mcp_tools/trading.py`
- `mcp_tools/signals.py`

---

## Bug 1: `analyze_stock` — `KeyError: 'momentum'` ✅ Completed (2026-02-09)

**Symptom:** Every call to `analyze_stock` fails with:
```
Stock analysis failed for STWD: 'momentum'
```

**Affected tickers:** All — not ticker-specific.

**Root cause:** `get_detailed_stock_factor_profile()` in `risk_summary.py` unconditionally accesses `factor_proxies["momentum"]`, `factor_proxies["value"]`, `factor_proxies["industry"]`, and `factor_proxies["subindustry"]` (lines 139-168). But the upstream proxy generator (`get_stock_factor_proxies()` in `services/factor_proxy_service.py`) can fall back to just `{"market": "SPY"}` when the database is unavailable (line 230), which is missing those keys.

**Call chain:**
```
mcp_tools/stock.py:60  →  StockService.analyze_stock()
  services/stock_service.py:176  →  get_stock_factor_proxies(ticker)  # may return {"market": "SPY"}
  services/stock_service.py:179  →  core analyze_stock(factor_proxies=...)
    core/stock_analysis.py:170   →  get_detailed_stock_factor_profile(factor_proxies=...)
      risk_summary.py:139        →  factor_proxies["momentum"]  💥 KeyError
```

**Key files:**
- `risk_summary.py:93-168` — `get_detailed_stock_factor_profile()` hard-codes key access
- `services/factor_proxy_service.py:166-247` — `get_stock_factor_proxies()` fallback returns minimal dict
- `core/stock_analysis.py:168-172` — passes proxies through without validation

**Fix approach:** Either:
1. Make `get_detailed_stock_factor_profile()` tolerant of missing factor keys (skip factors that aren't in the dict), OR
2. Validate that all required keys exist in `factor_proxies` before calling the multi-factor path, and fall back to the simple regression path (Path B, `stock_analysis.py:251`) when they're missing.

Option 2 is probably cleaner — if we only have `{"market": "SPY"}`, there's no point running multi-factor analysis anyway.

---

## Bug 2: `get_factor_analysis` — `FileNotFoundError: 'industry_to_etf.yaml'` ✅ Completed (2026-02-09)

**Symptom:**
```
[Errno 2] No such file or directory: 'industry_to_etf.yaml'
```

**Root cause:** The YAML file path is relative in `core/factor_intelligence.py:42`:
```python
return "industry_to_etf.yaml"
```

When the MCP server process starts from a working directory other than the project root, Python can't resolve the relative path.

**Key files:**
- `core/factor_intelligence.py:42` — returns bare filename with no path resolution
- `industry_to_etf.yaml` — exists at project root

**Fix approach:** Use `Path(__file__).resolve().parent.parent / "industry_to_etf.yaml"` or a similar anchored path relative to the module location, consistent with how other config files are loaded in the project.

---

## Bug 3: `get_risk_analysis` — PostgreSQL connection pool exhaustion ✅ Completed (2026-02-09)

**Symptom:**
```
connection to server at "localhost" (::1), port 5432 failed: FATAL: sorry, too many clients already
```

**Root cause:** The `get_db_session()` calls throughout `factor_proxy_service.py` (lines 86, 119, 131, 140) each open connections inside loops. When `ensure_factor_proxies()` processes multiple missing tickers, it opens a new connection per ticker for peer lookups (line 119) and potentially another for saving peers (line 131). Under concurrent MCP requests, this can exceed PostgreSQL's `max_connections`.

**Key files:**
- `services/factor_proxy_service.py:115-134` — opens new DB sessions inside a per-ticker loop
- `database.py` — `get_db_session()` connection pool configuration

**Fix approach:** Either:
1. Restructure the loop in `ensure_factor_proxies()` to reuse a single connection for all tickers rather than opening one per iteration, OR
2. Increase the PostgreSQL `max_connections` setting and/or tune the connection pool (pool size, overflow, recycle settings), OR
3. Both — fix the per-ticker connection pattern AND ensure the pool is properly sized.

Option 1 is the real fix. The loop at lines 115-134 should use a single `with get_db_session() as conn:` wrapping the entire loop rather than opening/closing inside it.

---

## Relationship between bugs

Bug 3 (DB exhaustion) likely causes Bug 1 to trigger more frequently: when the DB is unavailable, `get_stock_factor_proxies()` falls back to the minimal `{"market": "SPY"}` dict, which then triggers the KeyError in `get_detailed_stock_factor_profile()`. Fixing Bug 3 would reduce the frequency of Bug 1, but Bug 1 should still be fixed independently since the fallback path should be resilient.

Bug 2 is independent.

---

## Bug 4: `run_optimization(optimization_type="max_return")` — `FileNotFoundError: 'portfolio.yaml'` ✅ Completed (2026-02-09)

**Symptom:**
```
[Errno 2] No such file or directory: 'portfolio.yaml'
```

**Root cause:** Same class of issue as Bug 2 — a relative file path that fails when the MCP server's working directory isn't the project root. The `max_return` optimization path loads a `portfolio.yaml` config file using a bare relative path. The `min_variance` path does not hit this because it doesn't need expected returns config.

**Note:** `min_variance` optimization works fine. Only `max_return` is broken.

**Fix approach:** Same as Bug 2 — anchor the file path relative to the module/project root using `Path(__file__)` resolution. Audit all YAML/config file loads for the same pattern (Bugs 2 and 4 suggest this is a systemic issue — there may be other relative paths lurking).

---

## Bug 5: `get_factor_recommendations` — factor name matching fails ✅ Completed (2026-02-09, patch)

**Symptom:**
```json
{"status": "success", "recommendations": [], "recommendation_count": 0,
 "note": "No matching factor found for 'Real Estate'. Try a different factor name or use industry_granularity='industry' for more granular matching."}
```

**Context:** The risk score tool flags "High REM exposure" as a violation and recommends "Reduce exposure to REM sector." But when you pass `overexposed_factor="Real Estate"` to `get_factor_recommendations`, it can't match the name to any factor.

**Root cause:** There's a mismatch between the factor/sector names used by `get_risk_score` (which flags "REM") and the names accepted by `get_factor_recommendations`. The user has no way to know what factor names are valid, and the obvious human-readable names ("Real Estate") don't work.

**Fix approach:** Either:
1. Make the factor name matching fuzzy/case-insensitive and support common aliases (e.g., "Real Estate" → "REM", "REIT" → "REM"), OR
2. Have `get_risk_score` return the exact factor names that `get_factor_recommendations` accepts, so the output of one tool can feed directly into the other, OR
3. Add a `list_factors` mode or parameter to `get_factor_recommendations` that returns all valid factor names.

**Current fix (patch):** Option 1 was implemented via a hardcoded `alias_map` dict (7 entries) inside `recommend_offsets()` in `services/factor_intelligence_service.py:791`, plus 4-level fuzzy matching (exact → normalized → alias → substring). This works but the alias map is a redundant subset of data we already have — `industry_to_etf.yaml` / `load_industry_etf_map()` (DB with YAML fallback) is the canonical sector→ETF mapping. A proper fix should use that reference data instead of a hardcoded dict.

---

## Relationship between bugs

Bug 3 (DB exhaustion) likely causes Bug 1 to trigger more frequently: when the DB is unavailable, `get_stock_factor_proxies()` falls back to the minimal `{"market": "SPY"}` dict, which then triggers the KeyError in `get_detailed_stock_factor_profile()`. Fixing Bug 3 would reduce the frequency of Bug 1, but Bug 1 should still be fixed independently since the fallback path should be resilient.

Bugs 2 and 4 are the same class of issue (relative file paths) and should be fixed together with an audit of all config file loads.

Bug 5 is independent.

---

## Bug 6: `get_risk_analysis(format="full")` — response exceeds MCP/LLM context limits ✅ Completed (2026-02-09)

**Symptom:**
```
Error: result (88,237 characters) exceeds maximum allowed tokens.
Output has been saved to /Users/henrychien/.claude/...tool-results/...txt
```

The tool result is too large for the LLM context window. Claude Code saves it to a file as a fallback, but the model never sees the data directly — it has to read the file in chunks separately, which is slow and lossy.

**Root cause:** The `full` format returns the entire covariance matrix (N×N), correlation matrix (N×N), all per-position risk contributions, factor breakdowns, stress tests, etc. in a single JSON response. With 25 positions, the covariance matrix alone is 625 entries. The total payload hit 88K characters.

**Impact:** MCP tool results that exceed the LLM's token budget get written to disk instead of being returned inline. The model has to then read the file in chunks, which:
- Adds multiple round-trips
- Risks missing data if not read completely
- Consumes context window on file reads instead of actual analysis
- Breaks the conversational flow

**Key files:**
- `mcp_tools/risk.py` — the `get_risk_analysis` tool that assembles the response
- Whatever builds the full response dict (likely in `services/` or `core/`)

**Fix approach:**
1. **Cap the `full` format response size** — exclude the raw covariance and correlation matrices from the default response. These are useful for programmatic consumers but not for LLM consumption.
2. **Add a `matrices` parameter** (default `False`) that optionally includes covariance/correlation data when explicitly requested.
3. **Consider an LLM-optimized format** — a format mode specifically designed to stay within token limits while including the most decision-relevant fields (risk contributions, factor betas, stress tests, top correlations only).
4. **General principle:** All MCP tool responses consumed by LLMs should target <20K characters. Audit other `format="full"` endpoints for the same issue.

---

## Bug 7: MCP tool responses return too much low-signal data, causing LLM confabulation ✅ Completed (2026-02-09/10)

**Symptom:** The LLM conflates unrelated data — e.g., seeing AMZN in the `get_market_context` most-active list and hallucinating that it's a portfolio holding when it isn't.

**Root cause:** Several MCP tools return far more data than an LLM can usefully process, flooding the context window with noise:
- `get_market_context(format="full")` returns **50 gainers, 50 losers, 50 most active**, and **500+ global economic events** in a single response. Most of this is irrelevant to the user's portfolio or question.
- `get_economic_data(mode="calendar")` returns events from all countries (US, JP, DE, BR, etc.) when the user almost always only cares about US events.
- The sheer volume of tickers in gainers/losers/actives creates false associations with portfolio holdings.

**Impact:** This isn't a crash bug — it's a **quality bug**. The LLM makes incorrect claims by pattern-matching against noise in its context window. Worse, the user may not catch it every time.

**Affected tools:**
- `get_market_context` — gainers/losers/actives lists are too long
- `get_economic_data` (calendar mode) — no country filtering, returns global events
- Potentially any tool with `format="full"` that returns unbounded lists

**Fix approach:**
1. **Reduce default list sizes for LLM consumption** — `summary` format should return top 5-10 items, not 50. The `full` format can keep 50 for programmatic use.
2. **Add country filtering to the economic calendar** — default to US-only or let the caller specify `country="US"`.
3. **Add portfolio-aware filtering** — `get_market_context` could accept a list of portfolio tickers and highlight/filter movers relevant to the user's holdings.
4. **General principle:** When an MCP tool is primarily consumed by an LLM, the default response should optimize for **signal-to-noise ratio**, not completeness. Less data with higher relevance is better than more data with lower relevance.

**Resolution:**
- `get_economic_data(mode="calendar")`: Added `country="US"` default parameter, filters events by country (2026-02-09).
- `get_market_context` events section: Now filters to US-only events before any format slicing (2026-02-10).
- `get_market_context` movers: Summary already capped at 5. Full format now capped at 20 (was unbounded ~50) for gainers, losers, actives (2026-02-10).
- Portfolio-aware filtering (item 3) not yet implemented — would be a separate feature.

---

## Bug 8: EDGAR filing lookup — empty filings for high-volume filers (JPM, GS, etc.) (2026-02-08) ✅ Completed (2026-02-10)

**Symptom:** `get_filings(ticker="JPM", year=2024, quarter=3)` returns `{"filings": []}`. Same for GS and other large financial institutions. AAPL, MSFT, and most other tickers work fine.

**Root cause:** `fetch_recent_10q_10k_accessions()` in `edgar_tools.py` only reads `data["filings"]["recent"]` from the SEC submissions JSON. For most companies this is sufficient — AAPL has 33 10-Qs in "recent" going back many years.

But JPM files ~20,000 forms (mostly 424B2 prospectus supplements for structured notes), so the "recent" list only contains the **3 most recent 10-Qs** (all 2025) and **1 10-K** (2024-12-31). The SEC splits older filings into 64 overflow archive files (`data["filings"]["files"]`), which the code never fetches.

When filtering for `year<=2024`, all 3 of JPM's 2025 10-Qs are excluded → 0 10-Qs remain → quarter labeling finds nothing → empty result.

**Key data:**
- AAPL: 1,000 recent filings → 33 10-Qs, 11 10-Ks (plenty of history)
- JPM: 22,624 recent filings → 3 10-Qs, 1 10-K (only last ~1 year of 10-Q/10-K filings)
- JPM has 64 additional archive files containing older 10-Qs

**Key files:**
- `edgar_updater/edgar_tools.py:97-132` — `fetch_recent_10q_10k_accessions()` only reads `data["filings"]["recent"]`
- SEC API: `data["filings"]["files"]` contains overflow archive file references

**Affected tickers:** Large financial institutions that file thousands of forms (JPM, GS, BAC, C, MS, WFC, etc.). Companies with fewer total filings (most tech, industrials, consumer) are unaffected because their "recent" list covers many years of 10-Q history.

**Verified overflow file contents for JPM:**
- Overflow file #2 (`submissions-003.json`): 10-Q `2024-09-30` (Q3 2024)
- Overflow file #5 (`submissions-006.json`): 10-Q `2024-06-30` (Q2 2024)
- Overflow file #7 (`submissions-008.json`): 10-Q `2024-03-31` (Q1 2024)

Each overflow file has the same structure as "recent" (arrays of `form`, `accessionNumber`, `reportDate`, etc.), so the scanning logic is identical.

**Fix approach:** In `edgar_tools.py:fetch_recent_10q_10k_accessions()`, after scanning `data["filings"]["recent"]`, check if enough 10-Qs/10-Ks were found (targets: N_10Q=12, N_10K=4 from `config.py`). If not, iterate through `data["filings"]["files"]`, fetching overflow archives one at a time and scanning for 10-Q/10-K entries. Stop as soon as enough are found — don't download all 64. Each fetch adds ~0.5s (SEC rate limit), so ~8 files ≈ 4s for JPM. Only triggers for high-volume filers; most tickers never hit the overflow path.

**Resolution (implemented):**
- Updated `/Users/henrychien/Documents/Jupyter/Edgar_updater/edgar_tools.py` so `fetch_recent_10q_10k_accessions()` scans overflow archives from `filings.files` when needed, dedupes by accession, and stops early once enough filings are found.
- Verified via MCP `get_filings`: `JPM 2024 Q3` now returns 10-Q accession `0000019617-24-000611` (`period_end=2024-09-30`) instead of an empty list.

**Note:** The original bug description assumed this was a CIK resolution issue (ticker passed as CIK string). That only happens when calling `fetch_recent_10q_10k_accessions()` directly with a ticker — the MCP flow (`get_filings`, `get_filing_sections`) properly resolves CIK via `lookup_cik_from_ticker()` first.

---

## Bug 8b: `edgar_pipeline.py` master index fallback is sequenced after the guard that raises (2026-02-08) ✅ Completed (2026-02-10)

**Symptom:** Same as Bug 8 — `run_edgar_pipeline(ticker="JPM", year=2024, quarter=3)` raises `FilingNotFoundError: No 10-Q filing found for 3Q24` even though the pipeline has a master index fallback.

**Root cause:** The pipeline has the right idea but the wrong ordering:
1. Line 623: Fetch from "recent" submissions → JPM gets 3 10-Qs (all 2025)
2. Line 627-628: Filter by `year<=2024` → 0 10-Qs remain
3. Line 631: Sets `use_fallback = True` (notices not enough filings)
4. Line 760: Label 10-Qs → nothing to label
5. **Line 770: `raise FilingNotFoundError("No 10-Q filing found for 3Q24")` — crashes here**
6. Line 1095: Master index fallback fetch → **never reached**

The fallback at line 1095 was intended for a different purpose (fetching additional historical data for fact extraction), not as a rescue for the initial filing lookup. The `use_fallback` flag is set but never checked before the guard at line 770.

**Key files:**
- `edgar_updater/edgar_pipeline.py:631` — sets `use_fallback = True`
- `edgar_updater/edgar_pipeline.py:770` — raises before fallback executes
- `edgar_updater/edgar_pipeline.py:1095` — master index fallback (never reached)

**Fix approach:** Either:
1. Move the master index fallback (line 1095) to execute **before** the label + guard logic (line 760-770), OR
2. Don't fix `edgar_pipeline.py` separately — once Bug 8 is fixed in `edgar_tools.py:fetch_recent_10q_10k_accessions()`, refactor the pipeline to use that same function instead of its own copy. This avoids maintaining two parallel fetch implementations.

Option 2 is cleaner long-term.

**Resolution (implemented):**
- Patched `/Users/henrychien/Documents/Jupyter/Edgar_updater/edgar_pipeline.py` with the same overflow archive logic used in `edgar_tools.py`.
- Verified `run_edgar_pipeline(ticker=\"JPM\", year=2024, quarter=3, return_json=True)` succeeds with source filing period end `September 30, 2024`.

---

## Bug 9: `get_factor_recommendations(mode="portfolio")` — NoneType error (2026-02-08) ✅ Completed (2026-02-09)

**Symptom:**
```
argument of type 'NoneType' is not iterable
```

**Root cause:** In the portfolio-mode recommendation path, a variable expected to be a list or dict is `None`. The single-factor mode (with `overexposed_factor`) was tested and works (see Bug 5 for a separate name-matching issue). The portfolio mode path has not been debugged.

**Key files:**
- Likely in `core/factor_intelligence.py` or `services/` — the portfolio-mode branch of the recommendation logic
- `mcp_tools/factor_intelligence.py` — `get_factor_recommendations()` entry point

**Fix approach:** Trace the portfolio-mode code path, find where a `None` value is being checked with `in` or iterated, and add a guard or fix the upstream function that should be returning a non-None value.

---

## Design Recommendation: Agent-intermediary pattern for high-volume tool responses

**Context:** Bugs 6 and 7 are both symptoms of the same fundamental problem — MCP tool responses going directly into the LLM's main context window. Bug 6 is about exceeding the window entirely (88K chars). Bug 7 is about staying within limits but degrading quality through noise. The short-term fixes (cap response sizes, filter defaults) help, but the longer-term architecture should address the root cause.

**Proposed pattern:**

```
Main Agent (conversation context)
  │
  ├── dispatches task: "get market context relevant to my portfolio"
  │
  └── Sub-Agent (disposable context)
        │
        ├── calls get_market_context(format="full")  ← raw firehose (50 gainers, 500 events, etc.)
        ├── calls get_positions(format="list")        ← portfolio tickers
        ├── cross-references, filters, summarizes
        │
        └── returns: concise, portfolio-relevant summary ← only this enters main context
```

**Why this is better:**
1. **Raw tool output never touches the main context** — the sub-agent's context absorbs the blast and is discarded after the task
2. **Tools can safely return rich, complete data** — no need to artificially truncate at the tool level, because the intermediary handles filtering
3. **Cross-referencing becomes possible** — the sub-agent can combine data from multiple tools (market movers × portfolio holdings × risk scores) before summarizing
4. **Main context stays clean** — only high-signal, pre-digested summaries enter the conversation, reducing confabulation risk

**Implementation notes:**
- This maps directly to the existing `Task` tool with `subagent_type` dispatch — no new infrastructure needed
- The MCP tools should still have sensible `summary` defaults (Bug 7 fixes) as a fallback for when tools are called directly
- Consider adding a `portfolio_tickers` parameter to market-facing tools so they can do basic relevance filtering even without the agent pattern
- The agent-intermediary pattern is especially important for: `get_market_context`, `get_economic_data(mode="calendar")`, `get_risk_analysis(format="full")`, and any future tools that aggregate large datasets

---

## Bug 10: SnapTrade trading reconnection — connection disabled after upgrade (2026-02-09) ✅ Resolved (2026-02-12)

**Symptom:** After upgrading a read-only Schwab connection to `connectionType=trade` via the reconnect flow, the connection becomes `disabled: true` and all API calls return 402 code 3003: "Unable to sync with brokerage account because the connection is disabled."

**Context:** The connection `type` field does update to `"trade"` (confirming the API accepted the upgrade), but the connection enters a disabled state. The SnapTrade portal shows "Reconnecting to Schwab" indefinitely (>2 minutes) and never completes.

**What happened:**
1. Called `login_snap_trade_user` with `reconnect=<auth_id>`, `connection_type="trade"`
2. SnapTrade portal opened → showed "Reconnecting to Schwab"
3. Made a premature API call (symbol search) while reconnection was in progress → triggered 500 error with `InvalidCredentials` (code 3004), which disabled the connection
4. Subsequent reconnection attempts (with fresh credentials entered in portal) show "Reconnecting to Schwab" but never complete — the connection stays `disabled: true`

**Root cause (likely):** The premature API call during reconnection may have permanently corrupted the connection state. Alternatively, the Schwab OAuth flow for trading upgrades may require additional steps that SnapTrade's portal handles silently, and the disabled state is a SnapTrade-side issue.

**Key data:**
```json
{
  "id": "70863d52-be32-40b3-8059-b91e84d83a5f",
  "type": "trade",
  "disabled": true,
  "disabled_date": "2026-02-09T17:07:57.094220Z"
}
```

**Key files:**
- `snaptrade_loader.py` — `upgrade_snaptrade_connection_to_trade()`, `_login_snap_trade_user_with_retry()`

**Lessons / code fixes made:**
1. `upgrade_snaptrade_connection_to_trade()` now passes `immediate_redirect=False` so the SnapTrade portal UI renders properly (not a blank page)
2. `_login_snap_trade_user_with_retry()` now accepts `connection_type` and `reconnect` params
3. `create_snaptrade_connection_url()` now defaults to `connection_type="trade"` for new connections
4. **Do not make API calls against a connection while reconnection is in progress** — this can disable the connection

**Open question:** May need to delete and recreate the connection from scratch, or contact SnapTrade support to re-enable the disabled authorization

---

## Bug 11: Currency mismatch in cost basis for foreign-denominated positions (2026-02-09) ✅ Completed (2026-02-10)

**Symptom:** Unrealized gain for AT (Ashtead Technology Holdings, AT.L) shows ~+49% when the actual gain is ~9%. Similar issue likely affects all non-USD positions.

**Root cause:** For GBP-denominated positions, `cost_basis` appears to be stored in local currency (GBP) while `value` is converted to USD. Comparing these directly produces an inflated gain figure.

**Example (AT — 400 shares):**
| Field | Value | Currency |
|---|---|---|
| `value` | 2,430 | USD (converted) |
| `local_value` | 1,776 | GBP |
| `cost_basis` | 1,630 | GBP (not converted) |
| Reported gain | ~$800 / +49% | **Incorrect** |
| Actual gain | ~£146 / +9% | Correct (GBP terms) |

**Affected positions:** AT (AT.L) confirmed. Likely affects any position where `currency != "USD"`.

**Key files:**
- Position data comes from Plaid — need to check whether Plaid returns cost_basis in local currency or USD
- Wherever gain/P&L is calculated, it needs to either convert cost_basis to USD or compare in local currency consistently

**Fix approach:** Either:
1. Convert `cost_basis` to USD using the same FX rate applied to `value` at fetch time, OR
2. Store cost_basis in both local and USD (like `value`/`local_value`), and ensure gain calculations compare like-for-like currencies

**Resolution:**
- `core/result_objects.py`: When `local_price` is missing (fallback path), swaps `cost_basis` to `cost_basis_usd` so P&L compares USD-to-USD. Adds `pnl_basis_currency` and `cost_basis_usd` to monitor output.
- `services/position_service.py`: Added `"cost_basis_usd": "sum"` to both cash and non-cash consolidation agg dicts. Backward-compat fallback copies `cost_basis` when column missing.
- Verified: AT (GBP) now shows 10.83% P&L (was 49%). 2 regression tests added.

---

## Bug 12: SnapTrade user secret silently lost — `store_snaptrade_user_secret()` swallows AWS errors (2026-02-11) ✅ Resolved (2026-02-12)

**Symptom:** All SnapTrade API calls fail with "No SnapTrade user secret found for hc@henrychien.com". The SnapTrade user exists on their side but the secret is not in AWS Secrets Manager. Schwab and IBKR brokerage connections are inaccessible.

**Root cause:** `store_snaptrade_user_secret()` in `snaptrade_loader.py:276-281` catches all exceptions and only logs a warning — it never raises. When the web UI registered the user, the secret was returned in-memory and used to generate connection URLs (so brokerage linking succeeded), but the AWS storage failed silently. On next server restart, the secret was gone.

```python
except Exception as e:
    # For development, just log the warning and continue
    portfolio_logger.warning(f"⚠️ Could not store user secret in AWS Secrets Manager: {e}")
    # Don't raise - continue without AWS storage for development
```

**Impact:** Complete loss of SnapTrade data access. All brokerage connections (Schwab, IBKR) exist on SnapTrade's side but are unreachable. Only recovery is delete + re-register (wipes connections, requires re-linking).

**Resolution:** Recovered by deleting and re-registering the SnapTrade user, then re-linking Schwab (OAuth, 3 accounts) and IBKR (Flex Queries). New secret stored successfully in AWS and verified.

**Remaining fix needed:** `store_snaptrade_user_secret()` should raise on failure in production, or at minimum return a success/failure bool that the caller checks. The "don't raise for development" pattern is dangerous for credential storage.

**Key file:** `snaptrade_loader.py:235-281` — `store_snaptrade_user_secret()`

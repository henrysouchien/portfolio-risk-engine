# FX Currency Conversion — Review Findings Log

27 findings across 8 review rounds (Codex, GPT, Claude/FMP client author).

## Round 1 (Codex)

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | **High** | `fetch_raw("quote", ...)` requires a registered endpoint — no `quote` in `fmp/registry.py` | Use `historical_price_eod` for both spot and historical. No new endpoint needed. |
| 2 | **High** | `standardize_portfolio_input()` uses `entry["dollars"]` directly — FX bypassed for cash and dollar-denominated entries | Add FX conversion in `standardize_portfolio_input()` for `"dollars"` entries. See Step 1.5b. |
| 3 | **High** | `build_portfolio_view` cache key doesn't include `currency_map` — stale results across portfolios differing only by currency | Add `currency_map_json` param to `_cached_build_portfolio_view()`. See Step 2.3. |
| 4 | **Medium** | Other analysis entry points (`performance_analysis.py`, `scenario_analysis.py`, `optimization.py` ×2, `portfolio_risk_score.py`) also call `standardize_portfolio_input` with `latest_price` — remain wrong for non-USD | Thread `currency_map` through all 5 entry points using same `price_fetcher` lambda pattern. See Step 1.7. |
| 5 | **Medium** | If `currency_map` absent (e.g., YAML portfolios), non-USD tickers silently treated as USD | `latest_price()` already calls `fetch_fmp_quote_with_currency()` and gets the FMP profile currency. Add fallback: if no `currency` arg passed, use the currency returned by `normalize_fmp_price()`. See Step 1.5. |
| 6 | **Medium** | GBX/GBp in `currency_map` would fail `currency_to_fx_pair` lookup, silently returning 1.0 | `get_fx_rate()` and `get_monthly_fx_series()` must call `normalize_currency()` before FX pair lookup. Also normalize in `to_portfolio_data()` when building `currency_map`. See Steps 1.2, 1.4. |
| 7 | **Low** | `latest_price()` returns month-end close, but plan says "spot FX" — timestamp mismatch | Use month-end FX consistently for the risk pipeline. True spot only for position monitor. See Steps 1.2, 1.6. |

## Round 2 (GPT)

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 8 | **Medium** | `get_fx_rate()` must resample to month-end — if it just takes the last daily `historical_price_eod` row, it'll be a daily rate while equity prices are month-end | Reuse `fetch_monthly_close()` from `fmp/compat.py` for FX symbols. This gives identical month-end resample logic (`.resample("ME")["close"].last()`) and LRU caching for free. See Step 1.2. |
| 9 | **Medium** | `_calculate_market_values()` uses profile prices (near-real-time via `fetch_fmp_quote_with_currency`) while plan proposes month-end FX — internal inconsistency in monitor view | Monitor uses near-real-time equity prices, so it should use near-real-time FX too. Add `get_spot_fx_rate()` that fetches last daily close from `historical_price_eod` (no month-end resample). `get_fx_rate()` (month-end) is for risk pipeline only. See Steps 1.2, 1.6. |
| 10 | **Medium** | `standardize_portfolio_input()` signature change must be backward-compatible — `currency_map` must default to `None` | Confirmed: `currency_map: Optional[Dict[str, str]] = None` as keyword-only arg. All existing callers pass positional `(raw_input, price_fetcher)` and won't break. See Step 1.5b. |
| 11 | **Low** | Plan says `get_fx_rate()` is "LRU-cached with TTL" but `functools.lru_cache` has no TTL | Drop TTL claim. `get_fx_rate()` delegates to `fetch_monthly_close()` which already uses `@lru_cache`. `get_spot_fx_rate()` uses its own `@lru_cache` (daily close rarely changes intraday). No custom TTL needed. See Step 1.2. |

## Round 3 (GPT follow-up)

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 12 | **High** | `get_spot_fx_rate()` can't use `fetch_fmp_quote_with_currency()` — that calls `/profile/{symbol}` which is equity-only, not FX pairs | Use `historical_price_eod` last daily close (no month-end resample) instead. Same registered endpoint, viable for FX symbols. See Step 1.2. |
| 13 | **Medium** | Function naming inconsistent across Steps 1.2, 1.6, Files Modified, and Edge Cases | Standardized: `get_fx_rate()` = month-end (risk pipeline), `get_spot_fx_rate()` = last daily close (monitor). Step 1.6 explicitly uses `get_spot_fx_rate()`. |
| 14 | **Medium** | Edge Cases reference Findings #8–#11 but only 7 are in Round 1 table — breaks traceability | Fixed: all findings numbered contiguously across rounds. Edge Cases reference correct numbers. |

## Round 4 (GPT follow-up)

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 15 | **High** | `get_spot_fx_rate()` takes `df["close"].iloc[-1]` but FMP may return data in descending date order — could return oldest FX value | Explicitly sort ascending by date and take `.iloc[-1]`, or sort descending and take `.iloc[0]`. See Step 1.2. |
| 16 | **High** | `@lru_cache` on `get_spot_fx_rate()` keyed only by currency will be stale across days (FMP client cache refreshes monthly). Monitor shows wrong FX for up to a month | Include `date.today().isoformat()` as a cache key component so cache auto-invalidates daily. See Step 1.2. |
| 17 | **Medium** | Cash path in `_calculate_market_values()` reads currency from DB via `row.get("currency")` — DB may store GBX/GBp, not normalized | Add `normalize_currency()` call on the cash path before FX lookup. See Step 1.6. |
| 18 | **Medium** | `standardize_portfolio_input()` "dollars" branch only converts via `currency_map`. YAML portfolios with non-USD dollar amounts but no `currency_map` silently remain wrong (no fallback like `latest_price()` has) | Acceptable limitation — document as explicit. YAML "dollars" entries are user-specified USD amounts by convention. If non-USD, user must provide `currency_map`. Add a log warning if `currency_map` is absent and ticker looks foreign (has an `fmp_ticker_map` entry with `.L`/`.TO` suffix). See Step 1.5b. |

## Round 5 (GPT follow-up)

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 19 | **Medium** | `get_spot_fx_rate()` says `df.sort_index().iloc[-1]` but `historical_price_eod` returns `date` as a column, not the index — `sort_index()` won't sort by date | Set index first: `df["date"] = pd.to_datetime(df["date"]); df = df.set_index("date").sort_index()` then `.iloc[-1]["close"]` — mirrors `_fetch_monthly_close_cached()` pattern. See Step 1.2. |
| 20 | **Low** | Equity path in `_calculate_market_values()` passes `base_currency` from `normalize_fmp_price()` to `get_spot_fx_rate()` without normalizing — GBp/GBX could slip through if `normalize_fmp_price()` returns an unnormalized base | Add `normalize_currency()` call on `base_currency` in the equity path, matching the cash path. See Step 1.6. |

## Round 6 (Claude — FMP client author)

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 21 | **High** | Plan assumes `latest_price()` already has minor-currency normalization (`fetch_fmp_quote_with_currency`, `normalize_fmp_price`). It doesn't — current code is a simple 3-liner: `fetch_monthly_close()` → `dropna().iloc[-1]`. Step 1.5 must add all three layers from scratch. | Rewrote Context section and Step 1.5 to show full from-scratch implementation including minor-currency normalization, currency inference fallback, and FX conversion. |
| 22 | **High** | `get_spot_fx_rate()` uses `FMPClient.fetch("historical_price_eod")` but `historical_price_eod` has `CacheRefresh.HASH_ONLY`. When called without a `to` date, `_build_cache_key()` adds a month token — disk cache refreshes monthly. The daily `@lru_cache` trick only invalidates in-memory; first call each day hits month-old disk cache. | Use `FMPClient.fetch("historical_price_eod", use_cache=False)` — bypasses disk cache while retaining `"historical"` key extraction and DataFrame conversion (see also Finding #27). The in-memory `@lru_cache` alone provides sufficient intraday deduplication. See Step 1.2. |
| 23 | **Medium** | `@lru_cache` with `date.today()` as key component needs a two-layer pattern — `@lru_cache` keys on function arguments, not external state | Showed explicit inner/outer function pattern: `_get_spot_fx_cached(currency, cache_date)` wrapped by `get_spot_fx_rate(currency)` that passes `date.today().isoformat()`. See Step 1.2. |
| 24 | **Low** | FX pair direction: FMP may only offer `USDCAD` (inverse) instead of `CADUSD` — would need `1 / rate` | Added `inverted` flag support in `exchange_mappings.yaml` config. Verify each symbol during implementation. See Step 1.1. |

## Round 7 (Claude — FMP client author, follow-up)

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 25 | **Medium** | `latest_price()` calls `fetch_fmp_quote_with_currency()` (uncached `/profile` API call) on every invocation — unnecessary for USD tickers in a mostly-USD portfolio | Add USD fast-path: if `currency` is explicitly `"USD"` (from `currency_map`), return `raw_price` immediately, skipping profile call and FX. Minor-currency issues only affect foreign exchanges. See Step 1.5. |
| 26 | **Low** | `get_spot_fx_rate()` uses `fetch_raw()` which returns `list[dict]`, not a DataFrame — implementer needs `pd.DataFrame(data)` before index/sort | Superseded by Finding #27 — switched to `fetch(..., use_cache=False)`. |

## Round 8 (GPT follow-up)

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 27 | **Medium** | `fetch_raw("historical_price_eod")` returns raw `dict` with nested `"historical"` key — `pd.DataFrame(data)` would fail or produce a one-row DataFrame. `fetch()` has built-in fallback that extracts `data["historical"]` (client.py:337-339), but `fetch_raw()` skips this. | Switch from `fetch_raw()` to `fetch("historical_price_eod", use_cache=False)`. This bypasses disk cache (same as `fetch_raw`) while retaining automatic `"historical"` extraction and DataFrame conversion. See Step 1.2. |

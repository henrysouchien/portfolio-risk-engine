# Stress Test Beta Quality — Returns Alignment + Exchange Normalization

## Context

GOLD (Gold.com / A-Mark Precious Metals — a financial services precious metals trading company) shows -77% estimated impact under a -20% market stress test. Investigation traced this to a **market beta of 2.99** (should be ~-0.02 with full 84-month data). With correct data, stress impact is ~0%.

Two root causes:

### Issue 1: Short-ticker data contaminates factor betas (PRIMARY)

`get_returns_dataframe()` at `portfolio_risk_engine/portfolio_risk.py:1012` does `pd.DataFrame(rets).dropna()` which trims ALL tickers to the shortest common date window. MRP (IPO'd Feb 2025, 13 months) caused the entire 28-ticker DataFrame to be trimmed from 84 rows to 13 rows.

The trimmed `df_ret` feeds into `_build_stock_return_cache(df_ret)` at line 1502 when `stock_return_cache` is None. This gives every ticker only 13 months of data for factor regression, inflating betas (GOLD's Jan 2026 +52% spike dominates the short window → 2.99 market beta).

**Current main path** (`build_portfolio_view()` line 1961) passes `raw_return_cache` (pre-dropna, full per-ticker data) as `stock_return_cache`, so the main caller is currently safe. But the fallback at line 1501-1502 is a vulnerability for any other caller of `compute_factor_exposures`.

### Issue 2: Exchange name mismatch

FMP returns full exchange names that don't match the DB/YAML abbreviation keys. The substring match in `map_exchange_proxies()` (`key.lower() in exchange.lower()`) fails for three exchange strings because the abbreviation is not a substring of the full name:

| FMP exchange string | Expected match | Substring works? | Result |
|---|---|---|---|
| `"New York Stock Exchange"` | NYSE → SPY | No (`"nyse"` not in string) | Falls to DEFAULT → ACWX |
| `"London Stock Exchange"` | LSE → EWU | No (`"lse"` not in string) | Falls to DEFAULT → ACWX |
| `"New York Stock Exchange Arca"` | NYSE/AMEX → SPY | No | Falls to DEFAULT → ACWX |

Affected tickers: GOLD, DHT, DSU, ENB, EQT, IT, MSCI, STWD, TKO, V (NYSE), ERNS.L (LSE), SGOV (Arca). Most of the portfolio.

**Note**: FMP's industry classification of GOLD as "Financial - Capital Markets" is **correct** — Gold.com/A-Mark is a precious metals trading company, not a gold miner. KCE is the right industry proxy. The `config/profile_overrides.yaml` file overrides GOLD to "Barrick Gold" with `industry: Gold` — **wrong**, actively changing KCE (correct) to GDX (wrong).

## Plan

### Fix 1: Add FMP exchange name variants to DB and YAML

The `exchange_proxies` DB table and `config/exchange_etf_proxies.yaml` only have abbreviations (`NYSE`, `Nasdaq`). FMP returns full names (`"New York Stock Exchange"`, `"Nasdaq Global Select Market"`). The `map_exchange_proxies()` substring match fails because `"nyse"` is not a substring of `"new york stock exchange"`.

**Fix**: Add the FMP full-name variants as additional rows in the DB and YAML, pointing to the same ETFs. No code changes.

**DB migration** (the `exchange` column is `varchar(10)` — too short for full names):

```sql
-- Step 1: Widen the column
ALTER TABLE exchange_proxies ALTER COLUMN exchange TYPE varchar(50);

-- Step 2: Insert FMP full-name variants (only the 3 that fail substring match)
INSERT INTO exchange_proxies (exchange, factor_type, proxy_etf) VALUES
  -- "New York Stock Exchange" — same as NYSE (SPY/MTUM/IWD)
  ('New York Stock Exchange', 'market', 'SPY'),
  ('New York Stock Exchange', 'momentum', 'MTUM'),
  ('New York Stock Exchange', 'value', 'IWD'),
  -- "London Stock Exchange" — same as LSE (EWU/IMTM/EFV)
  ('London Stock Exchange', 'market', 'EWU'),
  ('London Stock Exchange', 'momentum', 'IMTM'),
  ('London Stock Exchange', 'value', 'EFV'),
  -- "New York Stock Exchange Arca" — same as NYSE/AMEX (SPY/MTUM/IWD)
  ('New York Stock Exchange Arca', 'market', 'SPY'),
  ('New York Stock Exchange Arca', 'momentum', 'MTUM'),
  ('New York Stock Exchange Arca', 'value', 'IWD')
ON CONFLICT (exchange, factor_type) DO UPDATE SET proxy_etf = EXCLUDED.proxy_etf;
```

**YAML additions** to `config/exchange_etf_proxies.yaml` (only the 3 that fail substring match):

```yaml
# FMP full-name variants that fail substring match against abbreviation keys
"New York Stock Exchange":   # same as NYSE
  market: SPY
  momentum: MTUM
  value: IWD

"London Stock Exchange":     # same as LSE
  market: EWU
  momentum: IMTM
  value: EFV

"New York Stock Exchange Arca":  # same as NYSE/AMEX
  market: SPY
  momentum: MTUM
  value: IWD
```

### Fix 2: Delete `config/profile_overrides.yaml`

The untracked file overrides GOLD to "Barrick Gold" with `industry: Gold` — wrong. GOLD is A-Mark Precious Metals and FMP's classification is correct. GOLD is the only entry.

**Action**: Delete the file. The `_load_profile_overrides()` loader in `utils/profile_overrides.py:19` already handles `FileNotFoundError` gracefully (returns `{}`). No code changes needed.

### Fix 3: Build per-ticker full-length cache in `compute_factor_exposures()` fallback

**File**: `portfolio_risk_engine/portfolio_risk.py`

At line 1501-1502, when `stock_return_cache` is None, the function calls `_build_stock_return_cache(df_ret, ...)` which extracts per-ticker Series from the globally-trimmed `df_ret`. After `dropna()`, all columns have the same length (e.g. 13 rows), so there's no way to detect which ticker caused the trim.

The only production caller (`build_portfolio_view()` line 1953) already passes pre-dropna `raw_return_cache`, so this fallback only fires for direct/test callers. But it's the path that produced the 2.99 beta historically.

**Fix**: When the fallback triggers, fetch full per-ticker returns independently using the same `_fetch_ticker_returns()` helper that `get_returns_dataframe()` uses (line 948). This matches the return-construction semantics (total-return prices, FX adjustment) of the normal path.

Replace lines 1501-1502:
```python
if stock_return_cache is None:
    # df_ret is globally trimmed by dropna() — all columns have same
    # length, hiding which ticker caused the trim. Fetch full per-ticker
    # returns independently so each ticker gets its own full history
    # for factor regression.
    stock_return_cache = {}
    for ticker in weights:
        try:
            result = _fetch_ticker_returns(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
                fmp_ticker_map=fmp_ticker_map,
            )
            series = result["returns"]
            if series is not None and not series.empty:
                stock_return_cache[ticker] = series
        except Exception:
            pass  # ticker will be skipped in factor computation
```

**Why this approach**:
- Uses the same `_fetch_ticker_returns()` as `get_returns_dataframe()` — total-return prices, FX adjustment, same semantics
- Each ticker gets its own full date range (84 months for GOLD, 13 for MRP)
- No threshold heuristics — the root cause (trimmed data) is eliminated
- Only fires when `stock_return_cache` is None (direct callers), not the main path

**Existing test**: `test_compute_factor_exposures_reuses_df_ret_for_stock_returns` at `tests/core/test_portfolio_risk.py:1296` passes `stock_return_cache=None` and expects cache to be built from `df_ret` with no external fetches. This test will need updating: it should either (a) pass an explicit `stock_return_cache` to test the reuse path, or (b) mock `_fetch_ticker_returns` for the new fallback path. The test monkeypatches `fetch_monthly_close` and `fetch_monthly_total_return_price`, so the new `_fetch_ticker_returns` calls will route through those mocks — the test may pass as-is if the mocks cover the path. Needs verification.

## Files modified

| File | Change |
|------|--------|
| `config/exchange_etf_proxies.yaml` | Add FMP full-name exchange variants as additional keys |
| DB `exchange_proxies` table | `ALTER COLUMN exchange TYPE varchar(50)` + insert full-name rows |
| `config/profile_overrides.yaml` | Delete file (wrong GOLD override, only entry) |
| `portfolio_risk_engine/portfolio_risk.py` | Replace `_build_stock_return_cache(df_ret)` fallback with per-ticker `_fetch_ticker_returns()` |
| `tests/core/test_portfolio_risk.py` | Update `test_compute_factor_exposures_reuses_df_ret_for_stock_returns` — test now expects fetches via `_fetch_ticker_returns` when `stock_return_cache` is None |

## Verification

1. **Exchange normalization**: `map_exchange_proxies("New York Stock Exchange", exchange_map)` returns `{"market": "SPY", ...}` (not ACWX)
2. **Profile override removed**: `build_proxy_for_ticker('GOLD', ...)` should get `industry: KCE` (from "Financial - Capital Markets" mapping — correct for A-Mark)
3. **DB refresh**: Run `get_risk_analysis(use_cache=false)` — GOLD's market beta should be ~-0.02 (not 2.99)
4. **Stress test**: Market Crash (-20%) scenario — GOLD impact should be ~0% (not -77%)
5. **Existing tests**: `pytest tests/core/test_portfolio_risk.py::test_compute_factor_exposures_reuses_df_ret_for_stock_returns tests/services/test_factor_proxies.py tests/services/test_proxy_builder_paths.py -v`
6. **Regression**: Full risk analysis — other tickers' betas unchanged

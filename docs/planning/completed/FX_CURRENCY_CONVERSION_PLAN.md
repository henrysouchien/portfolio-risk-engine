# FX Currency Conversion Plan

**Status: COMPLETE** — All steps implemented and verified.

## Context

Non-USD positions (AT in GBP, ENB in CAD, LIFFF in CAD) have incorrect dollar exposure and risk calculations. There is currently no minor-currency normalization (GBX→GBP) or FX conversion (GBP→USD, CAD→USD) in `latest_price()` — it returns the raw month-end close from `fetch_monthly_close()`. FMP's existing `historical-price-eod` endpoint supports forex pairs (GBPUSD, CADUSD) — no new endpoint registration needed.

**Current state of `latest_price()`** (`run_portfolio_risk.py:228`): Simple 3-line function — `fetch_monthly_close()` → `dropna().iloc[-1]`. No `fetch_fmp_quote_with_currency()`, no `normalize_fmp_price()`, no currency handling at all. Step 1.5 must add all three layers (minor-currency normalization, currency inference, FX conversion) from scratch.

**Current state of positions:** Currency metadata flows through the position pipeline (Plaid, SnapTrade, DB all track it) but gets dropped at `_convert_shares_dollars()` in PortfolioData. The risk pipeline operates on local-currency prices as if they were USD.

**Architecture decision:** Instead of threading `currency_map` through every function call, we centralize FX conversion in the `fmp/` layer — specifically a new `fmp/fx.py` module. The FMP client already handles ticker resolution, caching, and data fetching. FX is a natural extension.

**Review log:** 27 findings across 8 rounds (Codex, GPT, Claude/FMP client author) — all resolved and baked into this plan. See `FX_CURRENCY_CONVERSION_REVIEW_LOG.md` for full history.

---

## Phase 1: Valuation (Correct Weights & Dollar Exposure) ✅

Fixes portfolio weights and dollar exposure. Highest impact — incorrect weights cascade into every downstream calculation.

### Step 1.1 — FX pair config in `exchange_mappings.yaml` ✅

Add `currency_to_fx_pair` section mapping ISO currency → FMP forex symbol:
```yaml
currency_to_fx_pair:
  GBP: GBPUSD
  CAD: CADUSD
  EUR: EURUSD
  JPY: JPYUSD
  AUD: AUDUSD
  CHF: CHFUSD
  HKD: HKDUSD
```

**FX pair direction:** FMP convention: `GBPUSD` = "how many USD per 1 GBP" (e.g., 1.24), so `price_gbp * rate = price_usd` — correct for direct multiplication. However, some pairs may only be available as inverse (e.g., `USDCAD` instead of `CADUSD`). During implementation, verify each symbol exists in FMP. If a pair is only available inverted, use this format instead:
```yaml
# If FMP only offers the inverse pair:
# CAD: { symbol: USDCAD, inverted: true }
```
And apply `1 / rate` in `fmp/fx.py` when `inverted: true`.

### Step 1.2 — New `fmp/fx.py` module ✅

Centralized FX conversion using the existing FMP client infrastructure. Two separate functions for two use cases:

**Risk pipeline (month-end, cached):**
- **`get_fx_rate(currency: str) -> float`** — Returns latest month-end FX rate (currency→USD). Delegates to `fetch_monthly_close()` from `fmp/compat.py` with the FX symbol (e.g., `GBPUSD`), then takes `series.dropna().iloc[-1]`. This reuses the same month-end resample logic (`.resample("ME")["close"].last()`) and `@lru_cache` as equity prices — no timestamp mismatch, no custom TTL needed. Returns `1.0` for USD.
- **`get_monthly_fx_series(currency: str, start_date, end_date) -> pd.Series`** — Returns month-end FX rate time series. Same `fetch_monthly_close()` delegation. Returns constant `1.0` series for USD.

**Position monitor (last daily close, daily-expiring in-memory cache):**
- **`get_spot_fx_rate(currency: str) -> float`** — Returns most recent daily close FX rate. Uses `FMPClient.fetch("historical_price_eod", symbol="GBPUSD", use_cache=False)` to bypass disk cache (the `historical_price_eod` endpoint has `CacheRefresh.HASH_ONLY` which adds a month token for "latest" calls — disk cache would be stale). `fetch(..., use_cache=False)` retains the built-in `"historical"` key extraction and DataFrame conversion that `fetch_raw()` lacks. Result is a DataFrame; set date index, sort ascending, take last row's close — no month-end resample.

  In-memory caching uses a two-layer pattern (`@lru_cache` keys on function arguments, not external state):
  ```python
  @lru_cache(maxsize=32)
  def _get_spot_fx_cached(currency: str, cache_date: str) -> float:
      fx_symbol, inverted = _resolve_fx_pair(currency)
      # fetch(use_cache=False) bypasses disk, returns DataFrame with "historical" extracted
      df = get_client().fetch("historical_price_eod", symbol=fx_symbol, use_cache=False)
      df["date"] = pd.to_datetime(df["date"])
      df = df.set_index("date").sort_index()
      rate = float(df["close"].iloc[-1])
      return 1.0 / rate if inverted else rate

  def get_spot_fx_rate(currency: str) -> float:
      return _get_spot_fx_cached(normalize_currency(currency), date.today().isoformat())
  ```
  The `date.today()` key component auto-invalidates daily. The inner `@lru_cache` deduplicates within the same day.

**Shared:**
- **`convert_price_to_usd(price: float, currency: str) -> float`** — Convenience: `price * get_fx_rate(currency)`. Composes with existing `normalize_fmp_price()` (minor currency first, then FX).

**FX pair resolution helper** (`_resolve_fx_pair`): All FX functions share a common helper that parses `currency_to_fx_pair` entries (which may be a plain string like `"GBPUSD"` or a dict like `{symbol: "USDCAD", inverted: true}`), returns `(fx_symbol, inverted)`. All callers apply `rate = 1 / rate` (or `series = 1 / series`) when `inverted` is true:
```python
def _resolve_fx_pair(currency: str) -> tuple[str, bool]:
    """Return (fx_symbol, inverted) from exchange_mappings.yaml."""
    entry = load_exchange_mappings()["currency_to_fx_pair"][currency]
    if isinstance(entry, str):
        return entry, False
    return entry["symbol"], entry.get("inverted", False)
```

**Currency normalization:** All FX functions call `normalize_currency()` from `utils/ticker_resolver.py` before looking up `currency_to_fx_pair`. This handles GBX→GBP, GBp→GBP, etc. before the FX pair mapping.

Loads `currency_to_fx_pair` from `exchange_mappings.yaml` via existing `load_exchange_mappings()`. Falls back to `1.0` with a warning if FMP lacks an FX pair for an exotic currency.

### Step 1.3 — Add `currency_map` to PortfolioData (`core/data_objects.py`) ✅

- Add field: `currency_map: Optional[Dict[str, str]] = None` (parallels `fmp_ticker_map`)
- Maps ticker → ISO currency code for non-USD tickers (e.g., `{"AT": "GBP", "ENB": "CAD"}`)
- USD tickers omitted (absent = USD convention)
- Update `from_holdings()` to accept and pass through `currency_map`
- Update `to_yaml()` / `from_yaml()` serialization to include `currency_map`
- Update `_generate_cache_key()` to include `currency_map`

### Step 1.4 — Populate `currency_map` in `to_portfolio_data()` (`core/data_objects.py`) ✅

The `holdings_dict` already carries `currency` per position. Build `currency_map` from it. Normalize currency codes before storing — GBX/GBp become GBP:
```python
from utils.ticker_resolver import normalize_currency

currency_map = {}
for ticker, entry in holdings_dict.items():
    raw_ccy = entry.get("currency", "USD")
    normalized = normalize_currency(raw_ccy) or "USD"
    if normalized != "USD":
        currency_map[ticker] = normalized
```
Pass to `PortfolioData.from_holdings(..., currency_map=currency_map or None)`.

### Step 1.5 — FX conversion in `latest_price()` (`run_portfolio_risk.py`) ✅

Current `latest_price()` is a simple 3-line function with zero currency handling. Must add all three layers from scratch: minor-currency normalization, currency inference, and FX conversion.

Add `currency` param. The full rewrite:
```python
from fmp.fx import get_fx_rate
from utils.ticker_resolver import (
    select_fmp_symbol,
    fetch_fmp_quote_with_currency,
    normalize_fmp_price,
)

def latest_price(
    ticker: str,
    *,
    fmp_ticker: str | None = None,
    fmp_ticker_map: dict[str, str] | None = None,
    currency: str | None = None,
) -> float:
    # 1. Fetch month-end close (existing behavior)
    prices = fetch_monthly_close(
        ticker, fmp_ticker=fmp_ticker, fmp_ticker_map=fmp_ticker_map,
    )
    raw_price = prices.dropna().iloc[-1]

    # 2. USD fast-path: skip /profile call entirely
    #    Minor-currency issues only affect foreign exchanges, safe to skip for USD.
    if currency and currency.upper() == "USD":
        return raw_price

    # 3. Minor-currency normalization (GBX pence → GBP pounds)
    #    Only needed for non-USD or unknown currency tickers.
    fmp_symbol = select_fmp_symbol(
        ticker, fmp_ticker=fmp_ticker, fmp_ticker_map=fmp_ticker_map,
    )
    _, fmp_currency = fetch_fmp_quote_with_currency(fmp_symbol)
    normalized_price, base_currency = normalize_fmp_price(raw_price, fmp_currency)

    # 4. FX conversion (GBP → USD)
    # Use explicit currency arg if provided, otherwise fall back to FMP profile currency
    effective_currency = currency or base_currency
    if effective_currency and effective_currency.upper() != "USD":
        fx_rate = get_fx_rate(effective_currency)
        normalized_price = normalized_price * fx_rate

    return normalized_price if normalized_price is not None else raw_price
```

**Currency inference fallback:** `fetch_fmp_quote_with_currency()` returns the FMP profile currency. After `normalize_fmp_price()`, the returned `base_currency` is used as fallback when no explicit `currency` arg is passed. This means non-USD tickers are correctly converted even when `currency_map` is absent (e.g., YAML portfolios without a `currency_map` section).

**Timing consistency:** `latest_price()` returns the last month-end close. `get_fx_rate()` delegates to `fetch_monthly_close()` which uses the same `.resample("ME")["close"].last()` logic. Timestamps are consistent.

Update call sites to pass currency:
- `_config_from_portfolio_data()` in `core/portfolio_analysis.py` — build `price_fetcher` lambda that passes `currency_map.get(ticker)` as the currency arg
- `load_portfolio_config()` in `run_portfolio_risk.py` — read `currency_map` from YAML if present

### Step 1.5b — FX conversion for "dollars" entries in `standardize_portfolio_input()` (`run_portfolio_risk.py`) ✅

`standardize_portfolio_input()` uses `entry["dollars"]` directly without calling `price_fetcher`, so FX conversion is bypassed. Fix:

Add `currency_map` param as keyword-only with default `None` (backward-compatible — all existing callers pass positional `(raw_input, price_fetcher)` and won't break):
```python
def standardize_portfolio_input(
    raw_input: dict,
    price_fetcher: Callable,
    *,
    currency_map: Optional[Dict[str, str]] = None,
) -> dict:
```

In the `"dollars"` branch:
```python
elif "dollars" in entry:
    raw_dollars = float(entry["dollars"])
    # Convert foreign-currency dollar amounts to USD
    ccy = currency_map.get(ticker) if currency_map else None
    if ccy and ccy.upper() != "USD":
        from fmp.fx import get_fx_rate
        raw_dollars = raw_dollars * get_fx_rate(ccy)
    dollar_exposure[ticker] = raw_dollars
```

**Foreign cash positions** (`CUR:CAD`, etc.) enter as `"dollars"` entries with the local-currency amount. The `currency_map` will map `CUR:CAD` → `CAD`, so the conversion above applies automatically.

**"dollars" without `currency_map`:** YAML "dollars" entries are user-specified USD amounts by convention. If a user has non-USD dollar amounts, they must provide `currency_map`. This is an acceptable limitation because `"dollars"` entries bypass `price_fetcher` entirely — there's no FMP call to infer currency from. Add a defensive log warning when `currency_map` is absent and `fmp_ticker_map` suggests a foreign ticker:
```python
if not currency_map and fmp_ticker_map:
    for ticker in dollar_exposure:
        fmp_sym = fmp_ticker_map.get(ticker, "")
        if any(fmp_sym.endswith(s) for s in (".L", ".TO", ".PA", ".DE", ".HK")):
            logger.warning(
                f"{ticker} appears foreign (FMP: {fmp_sym}) but no currency_map provided — "
                f"treating dollars entry as USD"
            )
```

### Step 1.6 — FX conversion in `_calculate_market_values()` (`services/position_service.py`) ✅

The monitor uses near-real-time equity prices via `fetch_fmp_quote_with_currency()`. Use `get_spot_fx_rate()` (last daily close from `historical_price_eod`) for FX conversion. Do **not** use `get_fx_rate()` here — that's month-end, for the risk pipeline only:

```python
from fmp.fx import get_spot_fx_rate
from utils.ticker_resolver import normalize_currency

current_price, base_currency = normalize_fmp_price(raw_price, fmp_currency)
base_currency = normalize_currency(base_currency)  # DB/FMP may return GBp/GBX
if base_currency and base_currency.upper() != "USD":
    fx_rate = get_spot_fx_rate(base_currency)
    current_price = current_price * fx_rate
```

The position data already carries `currency` per position, so no `currency_map` threading needed — read currency directly from `normalize_fmp_price()` output (same as `latest_price()` fallback).

**Cash path** (`services/position_service.py:523`): Currently sets `value = shares` (treats quantity as dollar value) and skips pricing. Add FX conversion using `get_spot_fx_rate()`. DB may store GBX/GBp, so normalize before FX lookup:
```python
from utils.ticker_resolver import normalize_currency

if position_type == "cash":
    value = shares
    currency = normalize_currency(row.get("currency"))
    if currency and currency.upper() != "USD":
        value = value * get_spot_fx_rate(currency)
    df.at[idx, "value"] = value
    df.at[idx, "price"] = None
    continue
```

### Step 1.7 — Thread `currency_map` through other analysis entry points ✅

Five other entry points use the same `latest_price()` + `standardize_portfolio_input()` pattern:

1. `core/performance_analysis.py:84` — `analyze_performance()`
2. `core/scenario_analysis.py:111` — `analyze_scenario()`
3. `core/optimization.py:69` — `optimize_min_variance()`
4. `core/optimization.py:145` — `optimize_max_return()`
5. `portfolio_risk_score.py:1682` — `calculate_risk_score()`

For each, update the `price_fetcher` lambda to pass currency:
```python
currency_map = config.get("currency_map")
if fmp_ticker_map:
    price_fetcher = lambda t: latest_price(
        t, fmp_ticker_map=fmp_ticker_map,
        currency=currency_map.get(t) if currency_map else None,
    )
else:
    price_fetcher = lambda t: latest_price(
        t, currency=currency_map.get(t) if currency_map else None,
    )
standardized_data = standardize_portfolio_input(
    config["portfolio_input"], price_fetcher, currency_map=currency_map,
)
```

Note: Because `latest_price()` has a currency inference fallback, these will also work correctly even if `currency_map` is not provided — the FMP profile currency kicks in. The explicit `currency_map` is still preferred because it avoids an extra FMP API call per ticker.

---

## Phase 2: Historical Returns FX Adjustment (Risk Accuracy) ✅

Converts local-currency monthly returns to USD for correct covariance/beta/volatility.

**Formula:** `R_usd = (1 + R_local) * (1 + R_fx) - 1`

### Step 2.1 — FX-adjusted return helper in `fmp/fx.py` ✅

Add `adjust_returns_for_fx(local_returns: pd.Series, currency: str, start_date, end_date) -> pd.Series`:
- Normalizes currency via `normalize_currency()`
- Fetches monthly FX series via `get_monthly_fx_series()` (which uses `fetch_monthly_close()` — same month-end resample as equity returns)
- Computes FX returns: `fx_returns = fx_series.pct_change()`
- Combines: `(1 + local_returns) * (1 + fx_returns) - 1`
- Aligns dates using `.reindex()` with forward-fill (existing pattern)
- Returns local returns unchanged for USD

### Step 2.2 — Integrate into `get_returns_dataframe()` (`portfolio_risk.py`) ✅

Add `currency_map` param. For each non-USD ticker, wrap local returns with `adjust_returns_for_fx()` before adding to the returns DataFrame. Factor proxy returns (SPY, MTUM, etc.) are USD-denominated ETFs — no adjustment needed.

### Step 2.3 — Thread `currency_map` through `build_portfolio_view()` → `analyze_portfolio()` ✅

- `build_portfolio_view()` in `portfolio_risk.py` — add `currency_map` param, pass to `get_returns_dataframe()`
- `_cached_build_portfolio_view()` — add `currency_map_json` param to cache key
- `_config_from_portfolio_data()` in `core/portfolio_analysis.py` — add `currency_map` to config dict from `portfolio_data.currency_map`
- `analyze_portfolio()` — pass `currency_map` from config to `build_portfolio_view()`
- `load_portfolio_config()` in `run_portfolio_risk.py` — read `currency_map` from YAML if present, add to config dict

Cache key update in `_cached_build_portfolio_view()`:
```python
@functools.lru_cache(maxsize=PORTFOLIO_RISK_LRU_SIZE)
def _cached_build_portfolio_view(
    weights_json: str,
    start_date: str,
    end_date: str,
    expected_returns_json: Optional[str] = None,
    stock_factor_proxies_json: Optional[str] = None,
    bond_mask_json: Optional[str] = "[]",
    cache_version: str = "rbeta_v1",
    fmp_ticker_map_json: Optional[str] = None,
    currency_map_json: Optional[str] = None,  # NEW
):
```

---

## Files Modified

| File | Phase | Changes |
|------|-------|---------|
| `exchange_mappings.yaml` | 1 | Add `currency_to_fx_pair` section |
| `fmp/fx.py` | 1+2 | **New file**: `get_fx_rate()`, `get_spot_fx_rate()`, `get_monthly_fx_series()`, `convert_price_to_usd()`, `adjust_returns_for_fx()` |
| `core/data_objects.py` | 1 | Add `currency_map` field to PortfolioData, populate in `to_portfolio_data()`, serialize in `to_yaml()`/`from_yaml()` |
| `run_portfolio_risk.py` | 1 | Add `currency` param to `latest_price()` with USD fast-path and FMP profile fallback; add `currency_map` keyword-only param to `standardize_portfolio_input()`; thread `currency_map` through `load_portfolio_config()` |
| `core/portfolio_analysis.py` | 1+2 | Thread `currency_map` through `_config_from_portfolio_data()` and `analyze_portfolio()` |
| `services/position_service.py` | 1 | FX conversion in `_calculate_market_values()` using `get_spot_fx_rate()` including cash path with `normalize_currency()` |
| `portfolio_risk.py` | 2 | Add `currency_map` to `get_returns_dataframe()`, `build_portfolio_view()`, and `_cached_build_portfolio_view()` cache key |
| `core/performance_analysis.py` | 1 | Thread `currency_map` through `analyze_performance()` |
| `core/scenario_analysis.py` | 1 | Thread `currency_map` through `analyze_scenario()` |
| `core/optimization.py` | 1 | Thread `currency_map` through `optimize_min_variance()` and `optimize_max_return()` |
| `portfolio_risk_score.py` | 1 | Thread `currency_map` through `calculate_risk_score()` |

## Edge Cases

- **USD-only portfolios**: `currency_map` is None/empty → all FX functions return 1.0 / passthrough, zero regression
- **Minor currency + FX**: GBX→GBP (`normalize_fmp_price`) then GBP→USD (FX conversion) — composable, independent steps. `normalize_currency()` called in `to_portfolio_data()` and inside `fmp/fx.py` to ensure GBX/GBp are mapped to GBP before FX pair lookup
- **Exotic currencies**: If FMP lacks an FX pair, `fmp/fx.py` logs warning and returns 1.0 (treat as USD) — fail gracefully
- **Date alignment**: FX series may differ from stock series — use `.reindex()` with forward-fill (existing pattern)
- **Foreign cash positions**: `CUR:CAD` enters as `"dollars"` entry in `standardize_portfolio_input()`. `currency_map` maps it to `CAD`, FX conversion applied in the `"dollars"` branch
- **Dollar-denominated entries**: Any `"dollars"` entry with a non-USD currency in `currency_map` gets FX-converted
- **YAML portfolios without `currency_map`**: `latest_price()` falls back to FMP profile currency from `fetch_fmp_quote_with_currency()` — non-USD tickers still get converted
- **YAML "dollars" without `currency_map`**: Treated as USD by convention. Log warning if `fmp_ticker_map` suggests foreign ticker but no `currency_map` provided
- **Timing consistency — risk pipeline**: Both `latest_price()` and `get_fx_rate()` use `fetch_monthly_close()` with `.resample("ME")["close"].last()` — identical month-end semantics
- **Timing consistency — position monitor**: Equity prices use `fetch_fmp_quote_with_currency()` (profile endpoint); FX rates use `get_spot_fx_rate()` (last daily close from `historical_price_eod`). Both represent most-recent-available prices. `get_spot_fx_rate()` cache invalidates daily via `date.today()` key component
- **Monitor cash currency from DB**: DB may store GBX/GBp — `normalize_currency()` applied before FX lookup in the cash path
- **Backward compatibility**: `standardize_portfolio_input()` adds `currency_map` as keyword-only arg with default `None` — existing callers unaffected

## Verification

**Phase 1:**
- `python3 run_positions.py --user-email hc@henrychien.com --consolidated --to-risk` — AT weight should reflect USD value (~$1,565 at GBP/USD ~1.24, not £1,262)
- `python3 run_positions.py --user-email hc@henrychien.com --monitor` — position values in USD (using spot FX)
- Verify CUR:CAD cash position is converted to USD in output

**Phase 2:**
- Compare risk output (vol, beta, correlations) before/after for a portfolio with AT — correlations with USD assets should change reflecting FX component
- `python3 tests/utils/show_api_output.py analyze` — verify API output includes correct USD weights
- Verify `_cached_build_portfolio_view` cache key differentiates portfolios with different `currency_map`

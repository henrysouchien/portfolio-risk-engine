# International Futures Support + Daily Bars + FX Attribution

*Created: 2026-02-19 | Status: Implemented + Live Tested (v2.3 — passed Codex review round 4)*

---

## Context

The portfolio strategy calls for macro overlay trades via international index futures (Brazil via IBV, Japan via NKD) alongside concentrated stock positions. The existing futures pipeline handles 22 US futures end-to-end (IBKR data, FMP fallback, FIFO tracking, realized performance). This plan extends it to international futures with proper exchange routing, FMP index fallback, FX conversion for non-USD contracts, daily bar support for risk analysis, and FX return attribution so you can see how much of a position's return comes from the underlying vs the currency move.

### Data Source Strategy

IBKR is the primary data source — it can fetch historical data for any tradeable contract. FMP provides fallback via index quotes (`^N225`, `^BVSP`, etc.) since FMP has no international futures commodity symbols.

| Layer | Source | Notes |
|-------|--------|-------|
| Primary pricing | IBKR historical data | Works for any tradeable contract |
| Fallback pricing | FMP index quotes (`^N225`, `^BVSP`) | For when gateway is offline; some may 402 depending on FMP plan (see Known Limitations) |
| FX rates | FMP (`fmp/fx.py`) | Already supports GBP, EUR, JPY, HKD; adding BRL |
| Live snapshots | IBKR snapshot | Bid/ask/last/volume/OI when gateway is running |

### International Futures Available on IBKR

**CME Globex (standard US futures permissions):**

| Symbol | Name | Multiplier | Currency | Notional (~) |
|--------|------|-----------|----------|-------------|
| NKD | Nikkei 225 (USD) | $5 | USD | ~$195K |
| MNK | Micro Nikkei (USD) | $0.50 | USD | ~$19.5K |
| NIY | Nikkei 225 (JPY) | ¥500 | JPY | ~$130K |
| IBV | USD Ibovespa | $1 | USD | ~$130K |

**Eurex (needs "All Europe" permission):**

| Symbol | Name | Multiplier | Currency |
|--------|------|-----------|----------|
| FESX | Euro Stoxx 50 | €10 | EUR |
| FDAX | DAX 40 | €25 | EUR |
| FDXM | Mini-DAX | €5 | EUR |

**ICE / HKEX (additional permissions):**

| Symbol | Name | Multiplier | Currency |
|--------|------|-----------|----------|
| Z | FTSE 100 | £10 | GBP |
| HSI | Hang Seng | HK$50 | HKD |

For the Brazil + Japan strategy: NKD and IBV are both USD-settled on CME — no FX complexity, simplest path.

---

## Implementation Plan

### Step 1. Add international futures to `ibkr/exchange_mappings.yaml`

Add 9 symbols to both mapping sections.

**`ibkr_futures_to_fmp`** (FMP fallback symbols):
```yaml
  # International Index Futures
  NKD: "^N225"       # Nikkei 225 (USD, CME)
  MNK: "^N225"       # Micro Nikkei (USD, CME)
  NIY: "^N225"       # Nikkei 225 Yen (JPY, CME)
  IBV: "^BVSP"       # Ibovespa (USD, CME)
  FESX: "^STOXX50E"  # Euro Stoxx 50 (EUR, EUREX)
  FDAX: "^GDAXI"     # DAX (EUR, EUREX)
  FDXM: "^GDAXI"     # Mini-DAX (EUR, EUREX)
  Z: "^FTSE"         # FTSE 100 (GBP, ICEEU)
  HSI: "^HSI"        # Hang Seng (HKD, HKFE)
```

**`ibkr_futures_exchanges`** (contract qualification):
```yaml
  # International Index Futures
  NKD: { exchange: CME, currency: USD }
  MNK: { exchange: CME, currency: USD }
  NIY: { exchange: CME, currency: JPY }
  IBV: { exchange: CME, currency: USD }
  FESX: { exchange: EUREX, currency: EUR }
  FDAX: { exchange: EUREX, currency: EUR }
  FDXM: { exchange: EUREX, currency: EUR }
  Z: { exchange: ICEEU, currency: GBP }
  HSI: { exchange: HKFE, currency: HKD }
```

NKD, MNK, IBV are USD-settled on CME (no FX needed). NIY/FESX/FDAX/FDXM/Z/HSI are non-USD.

**Recommendation from Codex review:** Verify FESX/FDAX IBKR symbols with live contract qualification when gateway is available, as Eurex roots in IBKR can sometimes differ from exchange product codes.

### Step 2. Add `futures_daily` profile in `ibkr/profiles.py`

Add new entry to `_PROFILES` dict:

```python
"futures_daily": InstrumentProfile(
    instrument_type="futures",
    what_to_show_chain=["TRADES"],
    bar_size="1 day",
    use_rth=True,
    duration="2 Y",
),
```

**Fix for Codex finding #1 — `get_profile()` routing bug:** The current `get_profile()` runs the key through `coerce_instrument_type()` which doesn't recognize `"futures_daily"` and would fall back to `"equity"` → `KeyError`. Fix by adding a direct dict lookup **before** coercion:

```python
def get_profile(instrument_type: str | InstrumentType) -> InstrumentProfile:
    """Return the configured profile for an instrument type."""
    raw = str(instrument_type or "").strip().lower()
    # Direct lookup first — handles compound keys like "futures_daily"
    if raw in _PROFILES:
        return _PROFILES[raw]
    # Then coerce + lookup for canonical types and aliases
    if raw in {"fx", "forex"}:
        return _PROFILES["fx"]
    normalized = coerce_instrument_type(instrument_type, default="unknown")
    if normalized == "fx_artifact":
        normalized = "fx"
    profile = _PROFILES.get(normalized)
    if profile is None:
        raise KeyError(f"No IBKR profile configured for instrument type '{instrument_type}'")
    return profile
```

This works because `"futures_daily"` is a **profile key**, not an instrument type. The profile's `instrument_type` field is still `"futures"`, which is what downstream code (contract resolution, duration logic) checks.

### Step 3. Add `fetch_daily_close_futures()` to `ibkr/market_data.py`

New convenience method on `IBKRMarketDataClient`, following the pattern of `fetch_monthly_close_futures()`:

```python
def fetch_daily_close_futures(self, symbol, start_date, end_date) -> pd.Series:
    """Fetch daily close series for futures contracts."""
    profile = get_profile("futures_daily")
    return self.fetch_series(
        symbol=symbol, instrument_type="futures",
        start_date=start_date, end_date=end_date, profile=profile,
    )
```

No month-end resampling — daily bars returned as-is. The `_normalize_bars` method only resamples when `"month" in bar_size.lower()`, so daily bars pass through cleanly.

**Note (Codex finding #4):** This step adds the daily bar *capability* but does not wire it into the monthly risk pipeline (`get_returns_dataframe()`). The risk pipeline continues to use monthly returns. Daily bars are available for direct use (e.g. future daily-VaR computation, ad-hoc analysis via MCP tools). Wiring daily bars into the core risk engine is a separate follow-up.

### Step 4. Export via `ibkr/compat.py`

Two new public functions:

**a) `fetch_ibkr_daily_close_futures(symbol, start_date, end_date)`** — Same wrapper pattern as `fetch_ibkr_monthly_close()` but delegates to `client.fetch_daily_close_futures()`.

**b) `get_futures_currency(symbol) -> str`** — Returns settlement currency for a futures root symbol from YAML. Defaults to `"USD"` if not found. Allows callers to auto-populate `currency_map` for futures.

Add both to `__all__`.

### Step 5. Add BRL FX pair to project-root `exchange_mappings.yaml`

The `currency_to_fx_pair` section already has GBP, EUR, JPY, HKD. Add:

```yaml
  BRL:
    symbol: USDBRL
    inverted: true
```

And add BRL fallback rate to `currency_to_usd_fallback`:
```yaml
  BRL: 0.18
```

IBV is USD-settled so this isn't strictly needed for the primary use case, but completes coverage for any BRL-denominated asset. Codex confirmed `fmp/fx.py` handles inverted pairs correctly (`1.0 / series` / `1.0 / rate` paths).

### Step 6. Auto-detect futures currency in `portfolio_risk.py`

**Fix for Codex finding #2 — ticker collision with `Z`:** The original plan checked `t.upper() in get_ibkr_futures_exchanges()` which is ticker-string-based and not instrument-type-aware. `Z` is both a futures root (FTSE 100) and a real equity ticker (Zillow). This could incorrectly apply GBP FX conversion to Zillow stock.

**Solution:** Add an optional `instrument_types: Dict[str, str]` parameter to `get_returns_dataframe()`. Only apply futures currency auto-detection when a ticker is explicitly tagged as futures:

```python
def get_returns_dataframe(
    weights, start_date, end_date,
    fmp_ticker_map=None, currency_map=None, min_observations=None,
    instrument_types=None,       # NEW: optional {ticker: instrument_type}
    fx_attribution_out=None,     # NEW: see Step 7
) -> pd.DataFrame:              # Return type UNCHANGED
```

At line ~559, after the existing FMP profile currency inference block:

```python
if not currency and instrument_types:
    itype = str(instrument_types.get(t) or "").strip().lower()
    if itype == "futures":
        from ibkr.compat import get_futures_currency
        fut_ccy = get_futures_currency(t)
        if fut_ccy != "USD":
            currency = fut_ccy
```

Note: normalize the instrument type string (`.strip().lower()`) to avoid case/whitespace mismatches.

This is explicit and safe — only tickers tagged as `"futures"` in the caller's `instrument_types` dict get futures currency detection. The `instrument_types` parameter is optional; all existing callers pass nothing and see zero behavior change.

**Threading `instrument_types` through the cache boundary (Codex v3 finding #1/#2):**

`asset_classes` cannot be used to derive `instrument_types` because:
- `VALID_ASSET_CLASSES` in `core/constants.py` doesn't include `"futures"` (only equity, bond, real_estate, commodity, crypto, cash, mixed, unknown)
- The cache layer in `_cached_build_portfolio_view()` reconstructs `asset_classes` as bond-only (`{t: 'bond' for t in bond_list}`), dropping all non-bond entries

Instead, `instrument_types` must be its own independent parameter chain, mirroring how `currency_map` flows:

1. `build_portfolio_view()` accepts `instrument_types: Optional[Dict[str, str]] = None`
2. Serializes it: `instrument_types_json = serialize_for_cache(instrument_types)`
3. Passes to `_cached_build_portfolio_view()` as a new cache-key param
4. `_cached_build_portfolio_view()` deserializes and passes to `_build_portfolio_view_computation()`
5. Which passes to `get_returns_dataframe(instrument_types=instrument_types, ...)`

Portfolio configs that include futures should specify: `instrument_types: {"NKD": "futures", "HSI": "futures"}`.

### Step 7. FX return attribution in `fmp/fx.py` and `portfolio_risk.py`

When you hold a non-USD position (e.g. HSI in HKD), the total USD return is a combination of the local-currency return and the FX return. Currently `adjust_returns_for_fx()` computes both internally but only returns the blended USD series — the FX component is discarded.

**a) Refactor `adjust_returns_for_fx()` in `fmp/fx.py`** to optionally return all three components:

```python
def adjust_returns_for_fx(
    local_returns: pd.Series,
    currency: str,
    start_date, end_date,
    *,
    decompose: bool = False,
) -> Union[pd.Series, dict]:
    # ... existing logic to compute fx_returns ...
    adjusted = (1 + local_returns) * (1 + fx_returns) - 1

    if decompose:
        return {
            "usd_returns": adjusted,
            "local_returns": local_returns,
            "fx_returns": fx_returns,
        }
    return adjusted  # backward compatible
```

The `decompose=False` default preserves backward compatibility — all existing callers are unaffected.

**Note on interaction term (Codex finding #6):** The relationship is multiplicative: `(1 + r_usd) = (1 + r_local) * (1 + r_fx)`, so `r_local + r_fx ≠ r_usd` exactly. The difference is the interaction term `r_local * r_fx`, which is typically tiny for monthly returns. All three series are returned so consumers can see the exact values. Document that the relationship is multiplicative, not additive.

**b) Collect FX decomposition via output parameter in `get_returns_dataframe()`** (`portfolio_risk.py`):

**Fix for Codex finding #3 — avoid breaking return type:** Instead of changing `get_returns_dataframe()` to return a dict (which would break 2 runtime callers, 10+ test mocks, and an import in `run_portfolio_risk.py`), use an **optional mutable output dict**:

```python
def get_returns_dataframe(
    weights, start_date, end_date,
    fmp_ticker_map=None, currency_map=None, min_observations=None,
    instrument_types=None,
    fx_attribution_out=None,     # NEW: if provided, populated with FX decomposition
) -> pd.DataFrame:              # Return type UNCHANGED
```

When FX adjustment fires and `fx_attribution_out` is not None:

```python
if currency and currency.upper() != "USD":
    if fx_attribution_out is not None:
        result = adjust_returns_for_fx(
            ticker_returns, currency, start_date, end_date, decompose=True
        )
        ticker_returns = result["usd_returns"]
        fx_attribution_out[t] = {
            "currency": currency,
            "fx_returns": result["fx_returns"],
            "local_returns": result["local_returns"],
        }
    else:
        ticker_returns = adjust_returns_for_fx(
            ticker_returns, currency, start_date, end_date
        )
```

**Zero breaking changes.** All existing callers pass nothing and get exactly the same DataFrame back. Only callers that opt in by passing a dict see FX attribution.

**c) Surface in `_build_portfolio_view_computation()`** (`portfolio_risk.py` ~line 1311):

```python
fx_attribution = {}
df_ret = get_returns_dataframe(
    weights, start_date, end_date,
    fmp_ticker_map=fmp_ticker_map,
    currency_map=currency_map,
    instrument_types=instrument_types,
    fx_attribution_out=fx_attribution,
)
# ...
return {
    ...existing keys...
    "fx_attribution": fx_attribution,
}
```

**d) Update test key assertion** in `tests/core/test_portfolio_risk.py`:

Add `"fx_attribution"` to the `EXPECTED_BUILD_KEYS` set (line 8). This is the only test that asserts exact key equality on `build_portfolio_view()` output:
```python
EXPECTED_BUILD_KEYS = {
    ...existing keys...
    "fx_attribution",
}
```

**e) Thread `instrument_types` through `build_portfolio_view()` → cache → computation:**

Add `instrument_types` as an independent parameter (not derived from `asset_classes`):

```python
# In build_portfolio_view():
def build_portfolio_view(
    weights, start_date, end_date,
    ...existing params...
    instrument_types=None,  # NEW
):
    instrument_types_json = serialize_for_cache(instrument_types)
    return _cached_build_portfolio_view(
        ...existing args...,
        instrument_types_json,
    )

# In _cached_build_portfolio_view():
def _cached_build_portfolio_view(
    ...existing params...,
    instrument_types_json=None,  # NEW — part of cache key
):
    instrument_types = json.loads(instrument_types_json) if instrument_types_json else None
    return _build_portfolio_view_computation(
        ...existing args...,
        instrument_types=instrument_types,
    )

# In _build_portfolio_view_computation():
def _build_portfolio_view_computation(
    ...existing params...,
    instrument_types=None,  # NEW
):
    fx_attribution = {}
    df_ret = get_returns_dataframe(
        ..., instrument_types=instrument_types,
        fx_attribution_out=fx_attribution,
    )
```

This mirrors exactly how `currency_map` flows through the same chain.

**f) Filter `fx_attribution` to match final returns (Codex v3 finding #3):**

Tickers with insufficient observations get excluded from `df_ret` at line ~570. But `fx_attribution_out` may already have entries for them. After `get_returns_dataframe()` returns, prune `fx_attribution` to only include tickers present in the final DataFrame:

```python
# After get_returns_dataframe() returns:
fx_attribution = {t: v for t, v in fx_attribution.items() if t in df_ret.columns}
```

Example output for HSI:
```python
{
    "HSI": {
        "currency": "HKD",
        "fx_returns": pd.Series(...),     # HKD/USD monthly returns
        "local_returns": pd.Series(...),  # HSI in HKD monthly returns
    }
}
# Note: usd_returns = (1 + local_returns) * (1 + fx_returns) - 1
# The relationship is multiplicative, not additive.
```

---

## Files Modified

| File | Change |
|------|--------|
| `ibkr/exchange_mappings.yaml` | Add 9 international futures to both mapping sections |
| `ibkr/profiles.py` | Add `futures_daily` profile + fix `get_profile()` direct dict lookup |
| `ibkr/market_data.py` | Add `fetch_daily_close_futures()` method |
| `ibkr/compat.py` | Add `fetch_ibkr_daily_close_futures()` + `get_futures_currency()`, update `__all__` |
| `exchange_mappings.yaml` (project root) | Add BRL FX pair + fallback rate |
| `portfolio_risk.py` | Add `instrument_types` + `fx_attribution_out` params to `get_returns_dataframe()`, thread `instrument_types` through `build_portfolio_view()` → cache → computation chain, futures currency auto-detection, FX decomposition collection, prune excluded tickers from `fx_attribution`, surface `fx_attribution` in output dict |
| `fmp/fx.py` | Add `decompose` kwarg to `adjust_returns_for_fx()` |
| `tests/core/test_portfolio_risk.py` | Add `"fx_attribution"` to `EXPECTED_BUILD_KEYS` set |

**No changes to**: `providers/ibkr_price.py`, `providers/symbol_resolution.py`, MCP tools, `core/realized_performance_analysis.py` — these all read from YAML dynamically so new futures "just work".

**No breaking changes**: `get_returns_dataframe()` return type stays as `pd.DataFrame`. All new parameters are optional with `None` defaults. Existing callers and tests work unchanged (only the key-assertion test needs the new key added).

---

## Live Testing Results (2026-02-19)

**Verification checks** — all passed:
- YAML validation: 9 international futures with correct exchange/currency
- Profile routing: `futures_daily` resolves correctly (`1 day`, `futures`)
- Contract resolution: NKD → ContFuture(NKD, CME, USD), FESX → ContFuture(FESX, EUREX, EUR)
- Futures currency lookup: correct currencies for all 9 symbols
- FX decompose: dict and Series modes both work correctly
- Tests: 32 portfolio risk + 24 IBKR/provider tests all pass

**FMP fallback** (gateway offline):
- Working: `^N225`, `^FTSE`, `^STOXX50E`, `^HSI` (35 months of data)
- HTTP 402: `^BVSP`, `^GDAXI` (FMP plan tier limitation, as expected)

**Bug found and fixed — currency detection priority:**

The original implementation had FMP profile inference running *before* futures YAML metadata detection in `get_returns_dataframe()`. For `^HSI`, the FMP profile returns no currency field, so `normalize_fmp_price()` defaulted to `"USD"` — this prevented futures YAML metadata from ever firing, silently suppressing FX attribution for HSI.

**Fix**: Reordered currency detection priority in `portfolio_risk.py` (lines 561–581):
1. Explicit `currency_map` (user-provided)
2. Futures YAML metadata (`ibkr_futures_exchanges` → currency field)
3. FMP profile inference (existing fallback)

After fix, HSI FX attribution works correctly:
- Cumulative local return (HKD): +17.34%
- Cumulative FX return (HKD/USD): +0.75%
- Cumulative USD return: +18.22%

All 32 tests still pass after the reorder.

---

## Known Limitations

1. **FMP fallback for `^BVSP` and `^GDAXI`**: These return HTTP 402 on the current FMP plan tier. IBKR is the primary source so this is acceptable — FMP fallback is best-effort for when the gateway is offline. Other index symbols (`^N225`, `^FTSE`, `^STOXX50E`, `^HSI`) work fine.

2. **Daily bars not in risk pipeline**: Step 3 adds daily bar fetching capability but does not wire it into `get_returns_dataframe()` (which remains monthly). Daily bars are available for direct use. Wiring into the risk engine is a follow-up.

3. **FX attribution math is multiplicative**: `r_usd ≠ r_local + r_fx`. The exact relationship is `(1+r_usd) = (1+r_local) * (1+r_fx)`. The interaction term is typically <0.01% for monthly returns but should be documented for users.

4. **Eurex/ICEEU/HKFE symbol verification**: Exchange routing for FESX, FDAX, Z, HSI should be verified with live IBKR contract qualification when the gateway is available.

5. **Config-driven `instrument_types` threading**: The `instrument_types` parameter is threaded through `build_portfolio_view()` → cache → computation → `get_returns_dataframe()`. However, upstream callers (`core/portfolio_analysis.py`, `core/config_adapters.py`, `core/data_objects.py`) don't yet pass it from portfolio config. For the primary use case (NKD/IBV are USD, no FX detection needed), this is fine. For non-USD futures (FESX, HSI, NIY), users can pass `currency_map` directly as a workaround until config-driven threading is added as a follow-up.

6. **`fx_attribution` not in `RiskAnalysisResult`**: The `fx_attribution` dict is available in `build_portfolio_view()` output and accessible to MCP tools, but not yet wired into `RiskAnalysisResult.from_core_analysis()`. Follow-up to expose via API result objects.

---

## Verification

1. **YAML validation**: `python -c "from ibkr.compat import get_ibkr_futures_exchanges; print(get_ibkr_futures_exchanges())"` — verify all 9 new symbols appear with correct exchange/currency
2. **Profile routing**: `python -c "from ibkr.profiles import get_profile; p = get_profile('futures_daily'); print(p.bar_size, p.instrument_type)"` — should print `1 day futures`
3. **Contract resolution**: `python -c "from ibkr.contracts import resolve_futures_contract; print(resolve_futures_contract('NKD'))"` — verify ContFuture(NKD, CME, USD)
4. **FX coverage**: `python -c "from fmp.fx import get_fx_rate; print(get_fx_rate('BRL'))"` — verify BRL rate resolves
5. **FX attribution**: Test `adjust_returns_for_fx(series, "HKD", ..., decompose=True)` returns dict with `usd_returns`, `local_returns`, `fx_returns` keys
6. **Backward compat**: `adjust_returns_for_fx(series, "GBP", ...)` without `decompose` still returns a plain Series
7. **No breaking changes**: `python -m pytest tests/core/test_portfolio_risk.py tests/core/test_performance_metrics_engine.py -v` — all existing tests pass unchanged
8. **Run all futures/FX tests**: `python -m pytest tests/ibkr/ tests/providers/ tests/ -k "futures or fx or returns" -v`
9. **Live test (when gateway running)**: `python run_ibkr_data.py NKD futures` — fetch NKD monthly closes from IBKR

# Wire IBKR Daily Bars into Provider Chain

## Context

IBKR daily bar fetchers exist and work (`IBKRMarketDataClient.fetch_daily_close_futures()`, compat wrappers) but `IBKRPriceProvider.fetch_daily_close()` is a stub that just calls `fetch_monthly_close()`. This means:

- Timing analysis falls back to monthly data for all IBKR instruments (futures/FX/options/bonds)
- Risk pipeline (`get_returns_dataframe()`) only gets monthly bars from IBKR
- Post-exit analysis gets coarse monthly lookups for non-FMP instruments

Wiring the existing futures daily fetcher would give daily-granularity data for futures. FX/options/bonds remain monthly.

## Current Architecture

```
IBKRMarketDataClient (ibkr/market_data.py)
  ├── fetch_daily_close_futures()   ← BUILT, uses bar_size="1 day"
  ├── fetch_monthly_close_futures() ← BUILT, used by provider
  ├── fetch_monthly_close_fx()      ← BUILT, used by provider
  ├── fetch_monthly_close_option()  ← BUILT, used by provider
  └── fetch_monthly_close_bond()    ← BUILT, used by provider

ibkr/compat.py (wrappers with error handling)
  ├── fetch_ibkr_daily_close_futures()   ← BUILT, UNUSED by provider
  ├── fetch_ibkr_monthly_close()         ← BUILT, used by provider
  ├── fetch_ibkr_fx_monthly_close()      ← BUILT, used by provider
  ├── fetch_ibkr_option_monthly_mark()   ← BUILT, used by provider
  └── fetch_ibkr_bond_monthly_close()    ← BUILT, used by provider

IBKRPriceProvider (providers/ibkr_price.py)
  ├── fetch_daily_close()  ← STUB: just calls fetch_monthly_close()
  └── fetch_monthly_close() ← WORKS: dispatches by instrument_type
```

## Plan

### 1. Replace IBKRPriceProvider.fetch_daily_close() stub

**File:** `providers/ibkr_price.py`

Replace the stub with actual dispatch by instrument_type, mirroring how `fetch_monthly_close()` already dispatches:

```python
def fetch_daily_close(
    self,
    symbol: str,
    start_date: datetime | str,
    end_date: datetime | str,
    *,
    instrument_type: str = "equity",
    contract_identity: dict[str, Any] | None = None,
    fmp_ticker_map: dict[str, str] | None = None,
) -> pd.Series:
    """Fetch daily close from IBKR. Dispatches by instrument type."""
    itype = (instrument_type or "").strip().lower()

    if itype == "futures":
        return self._futures_daily_fetcher(
            symbol,
            start_date=start_date,
            end_date=end_date,
        )
    # FX, options, bonds: no daily fetcher yet — fall back to monthly
    return self.fetch_monthly_close(
        symbol,
        start_date=start_date,
        end_date=end_date,
        instrument_type=instrument_type,
        contract_identity=contract_identity,
        fmp_ticker_map=fmp_ticker_map,
    )
```

### 2. Wire daily fetchers in __init__

**File:** `providers/ibkr_price.py`

Add a `futures_daily_fetcher` param, same pattern as existing monthly ones. The current constructor uses module-level compat functions as defaults (not class methods):

```python
from ibkr.compat import (
    fetch_ibkr_bond_monthly_close,
    fetch_ibkr_daily_close_futures,  # NEW
    fetch_ibkr_fx_monthly_close,
    fetch_ibkr_monthly_close,
    fetch_ibkr_option_monthly_mark,
)

# ...

def __init__(
    self,
    futures_fetcher: Callable[..., pd.Series] | None = None,
    fx_fetcher: Callable[..., pd.Series] | None = None,
    bond_fetcher: Callable[..., pd.Series] | None = None,
    option_fetcher: Callable[..., pd.Series] | None = None,
    futures_daily_fetcher: Callable[..., pd.Series] | None = None,  # NEW
) -> None:
    self._futures_fetcher = futures_fetcher or fetch_ibkr_monthly_close
    self._fx_fetcher = fx_fetcher or fetch_ibkr_fx_monthly_close
    self._bond_fetcher = bond_fetcher or fetch_ibkr_bond_monthly_close
    self._option_fetcher = option_fetcher or fetch_ibkr_option_monthly_mark
    self._futures_daily_fetcher = futures_daily_fetcher or fetch_ibkr_daily_close_futures  # NEW
```

### 3. Update bootstrap to pass daily fetchers

**File:** `providers/bootstrap.py`

Pass daily fetcher through both `_register_ibkr()` AND `build_default_registry()` (needed for test monkeypatching in realized-performance tests):

```python
# In build_default_registry():
def build_default_registry(
    *,
    ...,
    ibkr_futures_daily_fetcher=None,  # NEW
):

# In _register_ibkr():
def _register_ibkr(
    registry,
    futures_fetcher=None,
    fx_fetcher=None,
    bond_fetcher=None,
    option_fetcher=None,
    futures_daily_fetcher=None,  # NEW
):
    provider = IBKRPriceProvider(
        futures_fetcher=futures_fetcher,
        fx_fetcher=fx_fetcher,
        bond_fetcher=bond_fetcher,
        option_fetcher=option_fetcher,
        futures_daily_fetcher=futures_daily_fetcher,
    )
    registry.register_price_provider(provider, priority=20)
```

### 4. Thread daily fetcher through realized-performance pricing

**File:** `core/realized_performance/pricing.py`

`_build_default_price_registry()` currently threads 4 monthly IBKR shims into `build_default_registry()`. Add the daily futures shim:

```python
return build_default_registry(
    fmp_fetcher=monthly_close_fetcher,
    fmp_daily_fetcher=_fetch_daily_close_for_registry,
    ibkr_futures_fetcher=_helpers._shim_attr("fetch_ibkr_monthly_close", fetch_ibkr_monthly_close),
    ibkr_fx_fetcher=_helpers._shim_attr("fetch_ibkr_fx_monthly_close", fetch_ibkr_fx_monthly_close),
    ibkr_bond_fetcher=_helpers._shim_attr("fetch_ibkr_bond_monthly_close", fetch_ibkr_bond_monthly_close),
    ibkr_option_fetcher=_helpers._shim_attr("fetch_ibkr_option_monthly_mark", fetch_ibkr_option_monthly_mark),
    ibkr_futures_daily_fetcher=_helpers._shim_attr(  # NEW
        "fetch_ibkr_daily_close_futures", fetch_ibkr_daily_close_futures
    ),
)
```

This requires:
- Importing `fetch_ibkr_daily_close_futures` from `ibkr.compat` at the top of `pricing.py` (same pattern as the other 4 monthly imports)
- Adding `fetch_ibkr_daily_close_futures` to the `ibkr.compat` import block in `core/realized_performance/__init__.py` (line 18-24) — required for `_shim_attr()` to find it on the package object, which is how tests monkeypatch IBKR fetchers

### 5. Verify futures daily compat wrapper

**File:** `ibkr/compat.py`

Verify `fetch_ibkr_daily_close_futures(symbol, start_date, end_date)` exists and returns `pd.Series` (empty on error). It should already be there — just confirm signature matches what the provider calls.

### What this enables

**Timing analysis**: When the provider chain calls `fetch_daily_close()` for futures, it now gets actual daily bars from IBKR (instead of monthly). FX/options/bonds still fall back to monthly (no daily compat wrappers wired for those yet).

**Post-exit analysis**: Daily-granularity lookups for futures post-exit prices. The adaptive tolerance (`_detect_cadence`) will detect daily data and use ±5 day tolerance instead of ±20.

**Risk pipeline**: `get_returns_dataframe()` can now get daily futures returns (if it calls `fetch_daily_close` — currently it uses monthly. Wiring that is a separate concern, noted but not in scope).

### What doesn't change

- Monthly fallback for FX/options/bonds (no daily fetchers exist for those at any layer)
- FMP provider (unchanged — already returns daily data)
- Provider protocol (unchanged — `fetch_daily_close` already exists on the interface)
- Registry routing (unchanged — provider-level concern)
- IBKR Gateway requirement (unchanged — daily bars need Gateway running, same as monthly)

### FX/options/bonds daily — future work

IBKR's `reqHistoricalData` supports daily bars for FX, options, and bonds, but:
- FX: no daily fetcher exists at any layer yet — would need new market data method + compat wrapper
- Options need specific contract details (strike, expiry, right) — more complex than futures
- Bond daily bars may have limited lookback
- Building compat wrappers for these is a separate effort

For now, FX/options/bonds continue with monthly fallback via `fetch_monthly_close()`.

## Files Changed

| File | Change |
|------|--------|
| `providers/ibkr_price.py` | Replace `fetch_daily_close()` stub with instrument-type dispatch; add `futures_daily_fetcher` constructor param defaulting to `fetch_ibkr_daily_close_futures` |
| `providers/bootstrap.py` | Pass `ibkr_futures_daily_fetcher` param in `_register_ibkr()` and `build_default_registry()` |
| `core/realized_performance/pricing.py` | Thread daily futures shim via `_shim_attr()` into `_build_default_price_registry()` |
| `core/realized_performance/__init__.py` | Add `fetch_ibkr_daily_close_futures` to `ibkr.compat` import block (for `_shim_attr()` monkeypatch compatibility) |
| `ibkr/compat.py` | Verify `fetch_ibkr_daily_close_futures()` signature (read-only) |

## Tests

- `IBKRPriceProvider.fetch_daily_close(instrument_type="futures")` → calls futures daily fetcher (not monthly)
- `IBKRPriceProvider.fetch_daily_close(instrument_type="fx")` → falls back to monthly (no daily FX yet)
- `IBKRPriceProvider.fetch_daily_close(instrument_type="option")` → falls back to monthly
- `IBKRPriceProvider.fetch_daily_close(instrument_type="bond")` → falls back to monthly
- Gateway offline → empty Series returned (graceful degradation)
- Bootstrap passes daily fetchers correctly

## Verification

1. `pytest tests/providers/ -v` — provider tests pass
2. `pytest tests/trading_analysis/ -v` — timing/post-exit still work
3. With IBKR Gateway running: timing analysis for futures gets daily data (check _detect_cadence returns "daily")
4. Without Gateway: graceful fallback to FMP daily (existing behavior)

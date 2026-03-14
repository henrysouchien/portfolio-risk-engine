# IBKR Historical Data Fallback for Futures Pricing

## Context

The realized performance pipeline fetches monthly close prices via FMP for NAV computation. For futures symbols like MGC (Micro Gold) and ZF (5-Year Treasury), FMP returns HTTP 402 (subscription gating), causing those positions to be valued at $0 and distorting monthly returns, volatility, and Sharpe.

IBKR Gateway supports `reqHistoricalData()` via `ib_async` — it can fetch monthly bars for any contract IBKR trades, including all futures. This plan adds IBKR as a **fallback** when FMP fails for futures tickers.

**Scope**: Only futures tickers (tagged via `futures_mapped` set). Non-futures failures still degrade gracefully as before.

## Files to Modify

1. `exchange_mappings.yaml` — Add `ibkr_futures_exchanges` section (root symbol → exchange + currency)
2. `services/ibkr_historical_data.py` — **New file**: IBKR historical price fetch service
3. `core/realized_performance_analysis.py` — Wire IBKR fallback into price cache loop (lines 750-765)
4. `tests/services/test_ibkr_historical_data.py` — **New file**: Unit tests for IBKR service
5. `tests/core/test_realized_performance_analysis.py` — Add IBKR fallback integration tests

## Changes

### 1. Add `ibkr_futures_exchanges` to `exchange_mappings.yaml`

New section after `ibkr_futures_to_fmp`:

```yaml
# IBKR exchange routing for ContFuture qualification
# Used by services/ibkr_historical_data.py
ibkr_futures_exchanges:
  ES:  { exchange: CME,   currency: USD }
  MES: { exchange: CME,   currency: USD }
  NQ:  { exchange: CME,   currency: USD }
  MNQ: { exchange: CME,   currency: USD }
  YM:  { exchange: CBOT,  currency: USD }
  RTY: { exchange: CME,   currency: USD }
  GC:  { exchange: COMEX, currency: USD }
  MGC: { exchange: COMEX, currency: USD }
  SI:  { exchange: COMEX, currency: USD }
  HG:  { exchange: COMEX, currency: USD }
  PL:  { exchange: NYMEX, currency: USD }
  PA:  { exchange: NYMEX, currency: USD }
  CL:  { exchange: NYMEX, currency: USD }
  BZ:  { exchange: NYMEX, currency: USD }
  NG:  { exchange: NYMEX, currency: USD }
  ZB:  { exchange: CBOT,  currency: USD }
  ZN:  { exchange: CBOT,  currency: USD }
  ZF:  { exchange: CBOT,  currency: USD }
  ZT:  { exchange: CBOT,  currency: USD }
```

### 2. New file: `services/ibkr_historical_data.py`

Two-layer design matching `fmp/compat.py` pattern: cached internal function that **raises** on failure, public wrapper that catches and returns empty Series.

#### Public API

```python
def get_futures_exchange(symbol: str) -> Optional[dict]:
    """Look up IBKR exchange routing for a futures root symbol.
    Returns dict with 'exchange' and 'currency' keys, or None."""

def fetch_ibkr_monthly_close(
    symbol: str,
    start_date: Union[str, datetime],
    end_date: Union[str, datetime],
    currency: str = "USD",
) -> pd.Series:
    """Fetch monthly close prices for a futures contract via IBKR Gateway.
    Returns pd.Series (DatetimeIndex, float) on success, empty Series on failure.
    ConnectionRefusedError logged at info level (expected when Gateway not running)."""
```

#### Internal cached function

```python
@lru_cache(maxsize=64)
def _fetch_ibkr_monthly_close_cached(
    symbol: str,
    exchange: str,
    currency: str,
    start_date_str: str,
    end_date_str: str,
) -> pd.Series:
    """Cached IBKR historical data fetch. RAISES on failure (never caches empty results).
    Matches fmp/compat.py pattern where _fetch_monthly_close_cached raises on error."""
```

This ensures that transient failures (Gateway down, pacing limits, network errors) are **not** cached by `@lru_cache`. Only successful results are cached. The public `fetch_ibkr_monthly_close()` catches all exceptions and returns empty `pd.Series`.

#### Key design details

- **Exchange lookup**: Reads from `ibkr_futures_exchanges` in YAML via `load_exchange_mappings()`
- **Contract**: `ContFuture(symbol=symbol, exchange=exchange, currency=currency)` for continuous front-month data
- **Qualification**: `ib.qualifyContracts(contract)` — raises `ValueError` if returns empty list
- **Historical request**: Explicit parameters to avoid ambiguity:
  ```python
  bars = ib.reqHistoricalData(
      contract,
      endDateTime='',           # empty string = now (IBKR convention)
      durationStr=duration_str, # e.g. "5 Y"
      barSizeSetting='1 month',
      whatToShow='TRADES',
      useRTH=True,              # regular trading hours only
      formatDate=1,             # yyyyMMdd format
  )
  ```
- **Duration computation**: From `start_date` to now, rounded up to nearest year. No artificial cap — IBKR's own limit is the constraint (typically 15-20Y for most futures).
- **Resample**: `resample("ME").last()` to align with FMP's month-end convention
- **Returns**: `pd.Series` (DatetimeIndex, float) — same as `fetch_monthly_close()`
- **Date clipping**: After resampling, clip to `[start_date, end_date]` range to match requested window
- **Imports**: `ib_async` and `IBKRConnectionManager` deferred inside function body (not top-level)
- **Thread safety**: Module-level `threading.Lock` (`_ibkr_request_lock`) wraps the call to `_fetch_ibkr_monthly_close_cached()` inside the **public** `fetch_ibkr_monthly_close()` function. This prevents both (a) concurrent `qualifyContracts`/`reqHistoricalData` calls on the non-thread-safe `IB` client, and (b) dogpile/thundering herd on cache misses — concurrent identical calls are serialized so only the first executes, and subsequent calls hit the now-populated `@lru_cache`. Lock placement:
  ```python
  def fetch_ibkr_monthly_close(...) -> pd.Series:
      # ... exchange lookup, param validation ...
      with _ibkr_request_lock:
          try:
              return _fetch_ibkr_monthly_close_cached(symbol, exchange, currency, start_str, end_str)
          except ConnectionRefusedError:
              logger.info("IB Gateway not running")
              return pd.Series(dtype=float)
          except Exception as exc:
              logger.warning(f"IBKR historical data failed for {symbol}: {exc}")
              return pd.Series(dtype=float)
  ```
  With ~5 futures symbols per pipeline run, serialization has negligible performance impact.
- **Logging**: `ConnectionRefusedError` at `info` level (expected when Gateway not running); other errors at `warning`

### 3. Wire fallback into `core/realized_performance_analysis.py`

Modify the price cache loop (lines 750-765). After FMP fails or returns empty for a futures ticker, try IBKR:

```python
price_cache: Dict[str, pd.Series] = {}
for ticker in tickers:
    try:
        series = fetch_monthly_close(
            ticker, start_date=price_fetch_start, end_date=end_date,
            fmp_ticker_map=fmp_ticker_map or None,
        )
        norm = _series_from_cache(series)
    except Exception as exc:
        norm = pd.Series(dtype=float)
        if ticker in futures_mapped:
            warnings.append(f"FMP price fetch failed for futures {ticker}: {exc}; trying IBKR fallback.")
        else:
            warnings.append(f"Price fetch failed for {ticker}: {exc}")

    # IBKR fallback for futures tickers that FMP cannot price
    # Check both empty AND all-NaN: FMP may return a non-empty series with all NaN values
    # (e.g., partial data), which would skip fallback but still value at 0 downstream.
    if (norm.empty or norm.dropna().empty) and ticker in futures_mapped:
        try:
            from services.ibkr_historical_data import fetch_ibkr_monthly_close
            ibkr_series = fetch_ibkr_monthly_close(ticker, start_date=price_fetch_start, end_date=end_date)
            norm = _series_from_cache(ibkr_series)
            if not norm.empty and not norm.dropna().empty:
                warnings.append(f"Priced futures {ticker} via IBKR Gateway fallback ({len(norm)} monthly bars).")
        except Exception as ibkr_exc:
            warnings.append(f"IBKR fallback also failed for futures {ticker}: {ibkr_exc}")

    if norm.empty or norm.dropna().empty:
        warnings.append(f"No monthly prices found for {ticker}; valuing as 0 when unavailable.")
    price_cache[ticker] = norm
```

**Why here, not in `fetch_monthly_close()`**: The fallback is specific to the realized performance pipeline and futures tickers. `fetch_monthly_close()` is a general-purpose FMP function used across the codebase — adding IBKR logic there would violate its single responsibility.

**Note on benchmark**: The benchmark ticker (line ~885) remains FMP-only. This is intentional — benchmark is typically SPY (an equity ETF with full FMP coverage), not a futures contract. If a futures benchmark is set and FMP fails, the pipeline returns `{"status": "error", "message": "No overlapping monthly returns..."}` (line 901). This is a pre-existing behavior and acceptable — users should not set futures tickers as benchmarks. No change needed here.

### 4. Tests

**New file**: `tests/services/test_ibkr_historical_data.py`

1. `test_fetch_returns_monthly_series` — Mock IB connection + bars → verify pd.Series output, month-end aligned
2. `test_no_exchange_mapping` — Unknown symbol → empty Series + warning
3. `test_gateway_not_running` — ConnectionRefusedError → empty Series, info log
4. `test_qualify_fails` — qualifyContracts returns [] → empty Series + warning
5. `test_no_bars_returned` — reqHistoricalData returns [] → empty Series
6. `test_lru_caching` — Call twice with same args, verify reqHistoricalData called once
7. `test_failure_not_cached` — Call once (Gateway down, raises), then call again (Gateway up, succeeds). Verify second call hits IBKR, not cache. This confirms the raise-on-failure pattern prevents caching transient errors.
8. `test_get_futures_exchange` — YAML lookup returns correct exchange/currency dict, None for unknown
9. `test_date_clipping` — Returned series is clipped to [start_date, end_date] range
10. `test_explicit_ib_params` — Verify `reqHistoricalData` called with exact kwargs (`endDateTime=''`, `whatToShow='TRADES'`, `useRTH=True`, `formatDate=1`)
11. `test_duration_computation` — Verify duration string computed correctly (e.g., 3-year span → "3 Y", 6-month span → "1 Y")

**Added to**: `tests/core/test_realized_performance_analysis.py`

12. `test_ibkr_fallback_triggered_for_fmp_failure` — Futures ticker, FMP fails → IBKR called, price_cache populated
13. `test_ibkr_fallback_not_triggered_for_non_futures` — Non-futures ticker fails → IBKR never called
14. `test_ibkr_fallback_not_triggered_when_fmp_succeeds` — Futures ticker, FMP succeeds → IBKR never called
15. `test_both_fail_gracefully` — FMP + IBKR both fail → empty Series, both warnings present
16. `test_ibkr_fallback_warning_messages` — Verify warning messages contain ticker name and bar count on success, error details on failure
17. `test_ibkr_fallback_triggered_for_nan_only_fmp` — Futures ticker, FMP returns non-empty all-NaN series → IBKR fallback triggers
18. `test_request_lock_serialization` — Verify module-level `_ibkr_request_lock` is acquired around IBKR calls (mock lock, assert acquire/release called)

## Verification

1. Run new tests: `python3 -m pytest tests/services/test_ibkr_historical_data.py -v`
2. Run existing tests: `python3 -m pytest tests/core/test_realized_performance_analysis.py tests/services/test_ibkr_flex_client.py -v`
3. With IB Gateway running, restart MCP server, call `get_performance(mode="realized", format="full")`:
   - Check `data_warnings` for "Priced futures MGC via IBKR Gateway fallback" messages
   - Check `data_warnings` for "Priced futures ZF via IBKR Gateway fallback" messages
   - Verify MGC and ZF no longer show "Price fetch failed" warnings
   - Compare total_return/CAGR before and after
4. With IB Gateway NOT running: verify same behavior as before (empty series, "Price fetch failed" warnings) — no regression
5. With IB Gateway running, validate all YAML exchange mappings: call `get_futures_exchange()` for each symbol in `ibkr_futures_exchanges`, then attempt `fetch_ibkr_monthly_close()` for each. Any that fail `qualifyContracts` indicate incorrect exchange codes that need fixing.

## Edge Cases

- **IB Gateway not running**: Most common case. `ConnectionRefusedError` caught in public wrapper, logged at info level, returns empty Series. Same behavior as before this change. NOT cached by `@lru_cache` because the internal function raises.
- **IBKR pacing limits**: Max 60 requests per 10 min, 15-second identical request cooldown. With ~5 futures symbols and LRU cache preventing repeats, well within limits. If pacing error occurs, it raises in the cached function → not cached → will succeed on next pipeline run.
- **Micro contracts (MGC)**: `ContFuture(symbol='MGC', exchange='COMEX')` resolves correctly. Price per unit is same as GC (gold price/oz); multiplier already handled at normalization.
- **ContFuture rolls**: Continuous front-month auto-rolls between contract months. Portfolio-level NAV is correct; contract-level attribution was already accepted as lost (Phase 1 decision).
- **Monthly bar alignment**: IBKR monthly bars have date = first trading day. Resample to "ME" aligns with FMP convention. Date clipping ensures no out-of-range bars leak into results.
- **Non-USD futures**: YAML includes `currency` field for future extensibility. All current futures are USD.
- **Thread safety**: Module-level `_ibkr_request_lock` wraps the call to `_fetch_ibkr_monthly_close_cached()` in the public function. This serializes all IBKR calls AND prevents dogpile on cache misses (concurrent identical calls wait for the first to fill cache). `IBKRConnectionManager` only locks connect/disconnect — the `IB` client is not thread-safe for concurrent API calls. With ~5 futures symbols per run, serialization is negligible.
- **futures_mapped scope**: The fallback triggers on `ticker in futures_mapped` which is populated from the FIFO transaction tagging. This correctly limits fallback to tickers the user actually trades as futures. Stocks that happen to share a root symbol (unlikely) won't accidentally trigger IBKR fallback.
- **NaN-only FMP series**: FMP may return a non-empty series with all NaN values (partial/corrupt data). The fallback trigger checks `norm.empty or norm.dropna().empty` to catch this case.
- **YAML exchange correctness**: Exchange codes in `ibkr_futures_exchanges` are sourced from IBKR's contract database. If a mapping is wrong, `qualifyContracts` will return empty → raises in cached function → not cached → returns empty from public wrapper → same degraded behavior as before. Manual verification step (step 5 below) validates all mappings against live Gateway.

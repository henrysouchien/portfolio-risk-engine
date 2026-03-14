# Flex PriorPeriodPosition → Option Price Cache

## Context

The realized performance engine values options at $0 because `price_cache` has
no option price data. This causes a +6.08pp gap between engine TWR (+6.37%)
and IBKR statement TWR (+0.29%) — the $8,378 in option value at inception is
missing from NAV.

The Flex query already includes `PriorPeriodPosition` (all sections enabled).
This section provides **daily closing prices for every position held during
the Flex window** — including options. Confirmed: 614 option rows with daily
`price` values from 2025-03-05 to 2026-03-04 (252 business days). Also has
STK (equities) and FUT (futures) rows — 3,080 total.

**Goal**: Parse `PriorPeriodPosition` from the Flex report, build daily price
series for options, and inject them into the engine's `price_cache` so NAV
computation values options correctly.

## Data Shape

`PriorPeriodPosition` row fields (relevant subset):
```
accountId, currency, assetCategory, symbol, description,
conid, underlyingSymbol, multiplier, strike, expiry, putCall,
date, price, priorMtmPnl
```

- `assetCategory`: `STK`, `OPT`, `FUT`
- `date`: Business day (YYYYMMDD format string)
- `price`: Closing mark price **per share** (NOT multiplied by contract multiplier)
- `multiplier`: Contract multiplier (100 for equity options)
- `underlyingSymbol`: The underlying ticker (e.g., `NMM`, `PDD`)
- One row per symbol per day

Example option row:
```
symbol="NMM   260116C00070000", assetCategory="OPT",
underlyingSymbol="NMM", putCall="C", strike=70, expiry="20260116",
date="20250331", price=0.475, multiplier=100
```

Value = 1 contract × 0.475 × 100 = $47.50 ✓

## Multiplier Handling (RESOLVED)

**NAV formula** (`nav.py:502`): `position_value += sign * qty * price * fx`
No multiplier is applied in the NAV formula.

**Trade normalization** (`ibkr/flex.py:348-356`):
- Option quantity: stored as contracts (NOT multiplied). `qty=1` for 1 contract.
- Option price: `price = trade_price * multiplier if is_option and multiplier > 1`
  (line 356). So trade prices in `price_cache` are already multiplied by 100.
- Invalid multiplier guard (line 301-303): `if multiplier <= 0: multiplier = 1.0`

**Conclusion**: PriorPeriodPosition `price` is per-share (0.475). We must
multiply by the `multiplier` (100) before storing in `price_cache`, yielding
47.5. Then NAV: `1 × 47.5 × 1.0 = $47.50` ✓

## Data Flow (Current)

```
ibkr/flex.py::fetch_ibkr_flex_payload()
  → extracts: trades, cash_rows, futures_mtm
  → ignores: PriorPeriodPosition, OpenPosition, etc.

trading_analysis/data_fetcher.py::fetch_ibkr_flex_payload()
  → passes: ibkr_flex_trades, ibkr_flex_cash_rows, ibkr_flex_futures_mtm

engine.py — live path (line 363-377):
  → builds TradingAnalyzer from payload
  → reads futures_mtm directly from payload (line 377)
  → pricing loop: options try FIFO terminal → IBKR Gateway → empty

engine.py — store path (line 276-316):
  → loads from transaction_store: fifo_transactions, futures_mtm_events
  → no option price data available from store
```

## Data Flow (Proposed)

```
ibkr/flex.py::fetch_ibkr_flex_payload()
  → NEW: extracts PriorPeriodPosition → builds option_price_history
  → option_price_history: List[Dict] (serializable, not pd.Series)

trading_analysis/data_fetcher.py::fetch_ibkr_flex_payload()
  → NEW: passes ibkr_flex_option_prices in payload

providers/ibkr_transactions.py::fetch_transactions()
  → NEW: passes ibkr_flex_option_prices through

trading_analysis/data_fetcher.py — orchestration functions:
  → _empty_transaction_payload(): includes ibkr_flex_option_prices: []
  → _merge_payloads(): works automatically (key exists in base)
  → _filter_provider_payload_for_institution(): NOT needed (prices are
    universal — same option has same price regardless of account)
  → _filter_provider_payload_for_account(): NOT needed (same reason)

engine.py — live path:
  → reads option prices from payload (like futures_mtm at line 377)
  → converts to Dict[str, pd.Series] for price_cache seeding

engine.py — store path:
  → NEW: transaction_store stores/retrieves flex_option_price_rows
  → follows existing raw JSON pattern (like futures_mtm at store.py:1487)

engine.py — pricing loop:
  → option branch checks if Flex price exists BEFORE trying other sources

engine.py — institution/account filters (lines 397-426):
  → NOT applied to option prices (prices are universal, not account-specific)
```

## Changes

### 1. Add `normalize_flex_prior_positions()` in `ibkr/flex.py`

New function that extracts option prices from PriorPeriodPosition rows.

Key design decisions:
- Returns `List[Dict]` (not `Dict[str, pd.Series]`) to stay compatible with
  the `FetchResult.payload` type (`Dict[str, List[Dict]]`) and serialization
  requirements of the transaction store.
- Uses `_build_option_symbol()` (line 138) for ticker normalization — the
  same function used by `normalize_flex_trades()` (lines 312-318). This
  guarantees tickers match between trades and price history.
- Multiplies `price` by `multiplier` to match trade price convention.
  Guards invalid multiplier (`<= 0 → 1.0`), matching flex.py:301-303.
- Keeps `price=0` rows (expired worthless options are legitimately $0).
  Distinguishes missing/invalid prices from genuine zeros by checking
  `safe_float(..., default=None)` — returns `None` when value can't be
  parsed, `0.0` when genuinely zero.
- Only processes `assetCategory == "OPT"` rows.

```python
def normalize_flex_prior_positions(
    rows: list[dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Extract option price history from PriorPeriodPosition rows.

    Returns list of {ticker, date, price, currency} dicts.
    Price is multiplied by multiplier (matching trade price convention
    at flex.py:356).
    """
    result: List[Dict[str, Any]] = []

    for row in rows:
        row_dict = _row_to_dict(row)
        asset_cat = str(row_dict.get("assetCategory", "")).upper()
        if asset_cat != "OPT":
            continue

        underlying = str(
            row_dict.get("underlyingSymbol", "") or ""
        ).strip().upper()
        put_call = row_dict.get("putCall")
        strike = row_dict.get("strike")
        expiry = row_dict.get("expiry")
        date_str = str(row_dict.get("date", "")).strip()
        currency = str(row_dict.get("currency", "USD") or "USD").upper()

        if not underlying or not date_str:
            continue

        # Use None default to distinguish missing from zero
        raw_price = safe_float(row_dict.get("price"), default=None)
        if raw_price is None:
            continue

        ticker = _build_option_symbol(
            underlying=underlying,
            put_call=put_call,
            strike=strike,
            expiry=expiry,
        )
        if not ticker or ticker == underlying:
            # _build_option_symbol returns underlying on parse failure
            continue

        # Multiply by multiplier to match trade price convention
        # (ibkr/flex.py:356: price = trade_price * multiplier if is_option)
        multiplier = safe_float(row_dict.get("multiplier"), 1.0)
        if multiplier <= 0:
            multiplier = 1.0
        if multiplier > 1:
            price = raw_price * multiplier
        else:
            price = raw_price

        result.append({
            "ticker": ticker,
            "date": date_str,
            "price": price,
            "currency": currency,
        })

    return result
```

**Note on `safe_float` and zero prices**: `safe_float(value, default=None)`
returns `None` when `value` is `None` or unparseable, and `0.0` when
value is genuinely `"0"` or `0`. The `if raw_price is None: continue` check
only skips missing/invalid values, preserving legitimate zeros.

### 2. Extract in `fetch_ibkr_flex_payload()` — `ibkr/flex.py` (~line 1298)

After existing topic extraction:

```python
# Extract option price history from PriorPeriodPosition
raw_prior_positions = _extract_rows(report, "PriorPeriodPosition")
payload["option_price_history"] = normalize_flex_prior_positions(raw_prior_positions)
```

### 3. Thread through `data_fetcher.py`

**`fetch_ibkr_flex_payload()` — all three return paths:**

Path file (~line 144):
```python
"ibkr_flex_option_prices": list(payload.get("option_price_history") or []),
```

Live path (~line 179):
```python
"ibkr_flex_option_prices": list(payload.get("option_price_history") or []),
```

Unavailable path (~line 159):
```python
"ibkr_flex_option_prices": [],
```

**`_empty_transaction_payload()` (~line 572):**
```python
"ibkr_flex_option_prices": [],
```

**`TransactionPayload` TypedDict (~line 33):**
```python
ibkr_flex_option_prices: List[Dict[str, Any]]
```

This ensures `_merge_payloads()` (line 583) recognizes the key (it skips
keys not in base), and `_filter_provider_payload_for_institution()` /
`_filter_provider_payload_for_account()` do NOT need updates because option
prices are universal (same option has same price regardless of which account
holds it — prices are a property of the contract, not the holder).

### 4. Thread through `IBKRFlexTransactionProvider`

In `providers/ibkr_transactions.py::fetch_transactions()` (~line 56), add:

```python
"ibkr_flex_option_prices": list(payload.get("ibkr_flex_option_prices") or []),
```

### 5. Inject into engine — live path

In `engine.py::_analyze_realized_performance_single_scope()`, after the
analyzer is built (~line 377), read option prices from the payload:

```python
flex_option_price_rows = list(payload.get("ibkr_flex_option_prices") or [])
```

**No institution/account filtering needed** for option prices. The engine
filters `fifo_transactions` and `futures_mtm_events` at lines 397-426
because those are account-specific events. Option prices are universal
(contract-level, not account-level), so filtering would incorrectly drop
valid price data.

### 6. Inject into engine — store path

In the `transaction_store_read` block (~line 294), add:

```python
flex_option_price_rows = list(store_data.get("flex_option_price_rows") or [])
```

**Transaction store changes** (`inputs/transaction_store.py`):

The store already handles arbitrary raw JSON buckets for futures MTM data
(~line 1487). Option price rows follow the same pattern:

- **Ingest**: Add `flex_option_price_rows` as a new bucket alongside
  `futures_mtm_events`. Each row has a natural composite key:
  `{ticker}:{date}` for dedup (no `transaction_id` needed — this is price
  data, not transactional data). Store as raw JSON in the existing
  `raw_provider_data` table or equivalent.

- **Load**: Add to `load_from_store()` output dict (~line 2092) alongside
  existing keys.

- **No DB migration**: Uses existing raw JSON storage pattern, same as
  futures MTM. No new columns or tables.

- **Dedup**: Option price rows use `{ticker}:{date}` as the dedup key
  (not `transaction_id`). This avoids the `_dedup_key` fallback issue
  flagged in review. Add explicit dedup key generation for this bucket.

**`mcp_tools/transactions.py` ingest wiring** (~line 130):

The `provider_rows` dict at line 130 controls which payload keys get stored.
Add the option prices bucket:

```python
provider_rows = {
    "plaid": list(payload.get("plaid_transactions") or []),
    "snaptrade": list(payload.get("snaptrade_activities") or []),
    "ibkr_flex": list(payload.get("ibkr_flex_trades") or []) + list(payload.get("ibkr_flex_cash_rows") or []),
    "ibkr_flex_mtm": list(payload.get("ibkr_flex_futures_mtm") or []),
    "ibkr_flex_option_prices": list(payload.get("ibkr_flex_option_prices") or []),  # NEW
    "schwab": list(payload.get("schwab_transactions") or []),
}
```

And at line 142, add to the `allowed_providers` set for ibkr_flex:

```python
if provider == "ibkr_flex":
    allowed_providers.add("ibkr_flex_mtm")
    allowed_providers.add("ibkr_flex_option_prices")  # NEW
```

### 7. Build price_cache entries from option price rows

Add a helper in `core/realized_performance/_helpers.py`:

```python
def _build_option_price_cache(
    option_price_rows: List[Dict[str, Any]],
) -> Dict[str, pd.Series]:
    """Convert flat option price rows into {ticker: pd.Series} for price_cache."""
    grouped: Dict[str, list[tuple[str, float]]] = defaultdict(list)
    for row in option_price_rows:
        ticker = str(row.get("ticker", "")).strip()
        date_str = str(row.get("date", "")).strip()
        price = row.get("price")
        if not ticker or not date_str or price is None:
            continue
        try:
            price_float = float(price)
        except (ValueError, TypeError):
            continue
        grouped[ticker].append((date_str, price_float))

    result: Dict[str, pd.Series] = {}
    for ticker, entries in grouped.items():
        dates = pd.DatetimeIndex([pd.Timestamp(d) for d, _ in entries])
        values = [p for _, p in entries]
        series = pd.Series(values, index=dates, dtype=float, name=ticker)
        series = series.sort_index()
        series = series[~series.index.duplicated(keep="last")]
        result[ticker] = series
    return result
```

**Note**: Uses explicit `float(price)` with try/except instead of
`_as_float()` to avoid silently converting None/invalid to 0.0 (which
would create fake zero prices).

### 8. Use in pricing loop — inject INSIDE the option branch

The pricing loop unconditionally sets `price_cache[ticker] = norm` at line
913. Pre-seeding before the loop would be overwritten. Instead, inject Flex
prices **inside the option pricing branch** (lines 785-839).

Build `flex_option_cache` once before the loop (~line 768):

```python
flex_option_cache = _helpers._build_option_price_cache(flex_option_price_rows)
if flex_option_cache:
    warnings.append(
        f"Loaded {len(flex_option_cache)} option price series from IBKR Flex "
        f"PriorPeriodPosition."
    )
```

Replace the option block (~line 785). The ONLY change is wrapping the
existing logic in a Flex-first check. All existing code in the `else`
branch is preserved verbatim:

```python
elif instrument_type == "option":
    # Check for Flex PriorPeriodPosition daily marks first.
    # These are the broker's own daily closing marks — most authoritative.
    flex_series = flex_option_cache.get(ticker)
    if flex_series is not None and not flex_series.empty:
        norm = _helpers._series_from_cache(flex_series)
        warnings.append(
            f"Priced option {ticker} using IBKR Flex PriorPeriodPosition daily marks "
            f"({len(norm)} data points)."
        )
    else:
        # ---- BEGIN EXISTING LOGIC (preserved verbatim) ----
        # Check if option still has open lots — if so, prefer IBKR fallback
        # over stale FIFO terminal price. Timeline events are deltas
        # (BUY=+qty, SELL=-qty), so we must sum to get cumulative position.
        option_still_open = False
        for tl_key, tl_events in position_timeline.items():
            if tl_key[0] == ticker and tl_events:
                cumulative_qty = sum(float(ev[1]) for ev in tl_events)
                if abs(cumulative_qty) > 1e-9:
                    option_still_open = True
                    break

        fifo_terminal = _helpers._option_fifo_terminal_series(ticker, fifo_transactions, end_date)
        has_fifo_terminal = not fifo_terminal.empty and not fifo_terminal.dropna().empty
        option_expiry = _helpers._option_expiry_datetime(ticker, contract_identity)
        end_ts = pd.Timestamp(end_date).to_pydatetime().replace(tzinfo=None)
        option_expired = option_expiry is not None and option_expiry <= end_ts
        current_shares = _helpers._as_float((current_positions.get(ticker) or {}).get("shares"), 0.0)
        flat_current_holdings = abs(current_shares) <= 1e-9

        if has_fifo_terminal and (
            (not option_still_open)
            or (option_expired and flat_current_holdings)
        ):
            norm = _helpers._series_from_cache(fifo_terminal)
            if option_still_open and option_expired and flat_current_holdings and option_expiry is not None:
                warnings.append(
                    f"Priced expired option {ticker} using FIFO close-price terminal heuristic "
                    f"(expiry {option_expiry.date().isoformat()}, current holdings flat)."
                )
            else:
                warnings.append(
                    f"Priced option {ticker} using FIFO close-price terminal heuristic."
                )
        else:
            price_result = pricing._fetch_price_from_chain(
                price_registry.get_price_chain("option"),
                ticker,
                price_fetch_start,
                end_date,
                instrument_type="option",
                contract_identity=contract_identity,
                fmp_ticker_map=fmp_ticker_map or None,
            )
            norm = _helpers._series_from_cache(price_result.series)
            chain_reason = pricing._emit_pricing_diagnostics(
                ticker=ticker,
                instrument_type="option",
                contract_identity=contract_identity,
                result=price_result,
                warnings=warnings,
                ibkr_priced_symbols=ibkr_priced_symbols,
            )
            if norm.empty or norm.dropna().empty:
                unpriceable_reason = chain_reason
        # ---- END EXISTING LOGIC ----
```

**Precedence**: Flex PriorPeriodPosition daily marks > FIFO terminal price >
IBKR Gateway chain > empty. The Flex daily series is the most complete and
authoritative — it's the broker's own daily mark with coverage across all
months the position was held. FIFO terminal only has the close date price.

## Files Modified

| File | Change |
|------|--------|
| `ibkr/flex.py` | `normalize_flex_prior_positions()` + extract in `fetch_ibkr_flex_payload()` |
| `trading_analysis/data_fetcher.py` | Thread `ibkr_flex_option_prices` through 3 return paths + `_empty_transaction_payload()` |
| `providers/ibkr_transactions.py` | Thread `ibkr_flex_option_prices` through `fetch_transactions()` return |
| `core/realized_performance/_helpers.py` | `_build_option_price_cache()` helper |
| `core/realized_performance/engine.py` | Build `flex_option_cache` + inject in option branch of pricing loop + read from payload/store |
| `inputs/transaction_store.py` | Store/retrieve `flex_option_price_rows` (raw JSON pattern, no migration) |
| `mcp_tools/transactions.py` | Add `ibkr_flex_option_prices` bucket to `provider_rows` dict (~line 130) |

## Edge Cases

1. **Zero prices**: `price=0` is valid (expired worthless). The
   `safe_float(value, default=None)` + `if raw_price is None` pattern
   distinguishes missing values (skipped) from genuine zeros (kept).

2. **Invalid multiplier**: Guarded with `if multiplier <= 0: multiplier = 1.0`,
   matching `ibkr/flex.py:301-303`.

3. **Options not in PriorPeriodPosition**: Options opened and closed within
   a single day won't appear. The existing FIFO terminal fallback handles
   these (the `else` branch in the option pricing block).

4. **Symbol matching**: Uses `_build_option_symbol()` from flex.py for both
   trade normalization AND price normalization. Both paths use
   `underlyingSymbol`, `putCall`, `strike`, `expiry` from the Flex report.
   The raw OCC-style `symbol` field (`NMM   260116C00070000`) is NOT used.

5. **Multiple accounts**: PriorPeriodPosition includes `accountId`. Option
   prices are universal (contract-level, not account-level), so no
   account filtering is needed. Same option in different accounts has the
   same market price.

6. **Institution/account filters**: NOT applied to option prices (lines
   397-426 in engine.py only filter `fifo_transactions` and
   `futures_mtm_events`). Option prices are universal — filtering would
   incorrectly drop valid price data.

7. **STK/FUT rows**: Ignored for now (only OPT processed). Could supplement
   FMP equity prices as a future enhancement.

8. **Transaction store dedup**: Option price rows use composite key
   `{ticker}:{date}` for dedup, not `transaction_id`. This is price data,
   not transactional — standard dedup keys don't apply.

## Verification

### Regression tests
1. `python3 -m pytest tests/mcp_tools/test_performance.py -v` — no regressions
2. `python3 -m pytest tests/core/test_realized_cash_anchor.py -v` — still pass

### Integration / live test
3. MCP: `get_performance(mode="realized", source="ibkr_flex", debug_inference=True)`
   - Verify option tickers in `price_cache` have non-empty daily series
   - Verify inception NAV includes option value (~$8,378)
   - Verify TWR moves closer to +0.29% (IBKR statement)
4. Check month-end option position values are non-zero for months where
   options were held
5. Normal (non-debug) calls unchanged
6. Test `source="all"` merge path includes option prices
7. Test with `TRANSACTION_STORE_READ=true` path
8. Test option pricing fallback when Flex prices unavailable (non-IBKR source)

### Parser edge cases (unit tests for `normalize_flex_prior_positions`)
9. Valid option row → correct ticker, price × multiplier, date
10. `price=0` (expired worthless) → row preserved with price=0
11. Missing price (`price=None` or invalid string) → row skipped
12. Invalid multiplier (`multiplier=0` or negative) → defaults to 1.0
13. Missing `underlyingSymbol` → row skipped
14. Missing `putCall`/`strike`/`expiry` → row skipped (`_build_option_symbol`
    returns underlying, which triggers the `ticker == underlying` guard)
15. STK/FUT rows → ignored (only OPT processed)

### Symbol matching
16. Trade ticker matches price ticker for same contract (both use
    `_build_option_symbol` with same fields)

### Store dedup / idempotency
17. Re-ingest same Flex data → option price rows deduplicated by
    `{ticker}:{date}` composite key, no duplicates in store
18. Store load path returns `flex_option_price_rows` when option data was
    previously ingested

### Data flow type contract
19. `TransactionPayload` type alias in `data_fetcher.py:33` updated to
    include `ibkr_flex_option_prices` key

## Addendum: Option Expiration Flag Bug (2026-03-05)

### Problem

After option pricing was implemented and all 9 options were priced, NMM C70
and NMM C85 still had **no synthetic entries** in the position timeline.
Their only FIFO event was a SELL on 2026-01-16 at price=0 (expired worthless),
but the engine never created an opening position for them.

### Root Cause

The provider normalizer (`providers/normalizers/ibkr_flex.py`) did NOT include
the `option_expired` field in its FIFO transaction output. Two normalizer paths
existed:

1. `ibkr/flex.py:371` — sets `option_expired = is_option and price == 0 and
   trade_type in ("SELL", "COVER")` ✓
2. `providers/normalizers/ibkr_flex.py` — did NOT include `option_expired` ✗

The transaction store uses the provider normalizer (path 2), so all
store-ingested data had `option_expired=False`. The FIFO matcher at line 484
checks `if price == 0 and not is_expiration: continue` — silently dropping
the entire transaction. No `IncompleteTrade` created → no synthetic entry →
NMM C70/C85 missing from position timeline.

### Impact

- NMM C70 ($47.50) and NMM C85 ($21.42) missing from inception NAV
- Also affected: SLV C30 and SLV C35 expiration events (price=0 SELL/COVER
  on 2025-06-20)
- Total: 12 DB rows with incorrect `option_expired=FALSE`

### Fix

1. **Code**: Added `option_expired` computation to
   `providers/normalizers/ibkr_flex.py` (matching `ibkr/flex.py:371` logic)
2. **DB**: Updated 12 rows in `normalized_transactions` to set
   `option_expired=TRUE` for all option SELL/COVER at price=0

### Result

- NMM C70 and C85 now have synthetic entries at inception (2025-03-03T23:59:59)
- Option NAV at March 31, 2025: **$8,378.50 engine = $8,378.50 IBKR — zero gap**

| Option | Engine | IBKR | Gap |
|--------|--------|------|-----|
| NMM C70 | $47.50 | $47.50 | $0.00 |
| NMM C85 | $21.42 | $21.42 | $0.00 |
| NXT C30 | $2,812.22 | $2,812.22 | $0.00 |
| PDD C110 | $5,053.60 | $5,053.60 | $0.00 |
| PDD P60 | $443.76 | $443.76 | $0.00 |
| **Total** | **$8,378.50** | **$8,378.50** | **$0.00** |

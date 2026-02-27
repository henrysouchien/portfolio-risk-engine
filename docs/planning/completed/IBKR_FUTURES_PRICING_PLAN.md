# IBKR Futures Pricing via FMP Commodity Symbols

## Context

The `get_performance(mode="realized")` pipeline can't price IBKR futures positions because FMP doesn't recognize raw IBKR futures symbols (e.g., `ES`, `GC`, `SI`). This causes `V_adjusted<=0` warnings and incorrect NAV for 13+ months when futures positions are open.

FMP **does** support commodity/futures prices via the same `historical-price-eod` endpoint already in use — just with `{ROOT}USD` symbols (e.g., `ESUSD`, `GCUSD`, `SIUSD`). Confirmed working on current FMP plan: GCUSD, SIUSD, ESUSD, BZUSD.

**Goal**: Map IBKR futures symbols to FMP commodity symbols and correctly value futures positions in the NAV/return computation. This affects the realized performance pipeline only (IBKR data doesn't flow through PositionService).

## Key Design Decision: Quantity Adjustment

Futures contracts have multipliers (ES = $50/point, GC = $100/oz). A position of 2 ES contracts at index level 5000 = $500,000 notional value.

**Approach**: Multiply quantity by multiplier at normalization time (`normalize_flex_trades()`).
- `quantity = contracts * multiplier` (e.g., 2 contracts → 100 units for ES)
- Price stays as raw trade price / FMP index level
- NAV: `100 * $5000 = $500,000` ✓
- FIFO P&L: `100 * ($5100 - $5000) = $10,000` ✓ (same as 2 contracts * $50 * $100)
- Cash flows: `100 * $5000 = $500,000` outflow ✓

This is the same pattern used for options (line 174), but adjusting quantity instead of price — because FMP returns raw index/commodity prices, not multiplier-adjusted prices. No changes needed to `compute_monthly_nav()`, `derive_cash_and_external_flows()`, or any downstream code.

### Margin vs. Fully-Funded Cash Flow Model

Futures are margined instruments — the trader posts a fraction of notional value as margin, not the full notional. However, our NAV model uses a **fully-funded approach** where `position_value = qty * price` and `cash -= qty * price` at entry. This is intentionally consistent with how equities work in the model:

- **At entry**: position_value increases by $500k, cash decreases by $500k → NAV unchanged ✓
- **Price moves**: position_value changes → flows directly to NAV → P&L correct ✓
- **At exit**: position_value decreases, cash increases → net P&L correctly captured ✓

Returns reflect the **fully-funded notional model** — both legs (position value and cash) use the same notional basis, so the return computation is internally consistent. This is the same model used for equities and options: all BUY events create cash outflows of `qty * price`, regardless of the instrument's margin structure.

**Known limitation**: This approach overstates the actual cash commitment (margin ≈ 5-10% of notional). Returns represent fully-funded notional returns, not margin-capital returns. A margin-aware model would yield higher percentage returns (same P&L on smaller capital base) but would require tracking margin requirements per instrument, which is out of scope for v1. The important property — that P&L magnitudes are correct — is preserved.

## Key Design Decision: Contract Expiry Collapsing

All contract months for the same underlying (ESU5, ESZ5, ESH6) collapse to the root symbol `ES`. This means:

- **Rolls work correctly**: Sell ESU5 + Buy ESZ5 → SELL 100@5050 + BUY 100@5060 for symbol "ES". FIFO closes the first BUY with the SELL, opens new position. P&L captured correctly.
- **Calendar spreads**: Long ESU5 + Short ESZ5 both map to "ES". The position timeline keys on `(ticker, currency, direction)` — long and short legs are separate entries. Net directional exposure is correctly minimal.
- **Same-direction multi-expiry**: Buy ESU5 + Buy ESZ5 both map to BUY "ES". FIFO processes in chronological order — any subsequent SELL closes the oldest position first.

**Same-day ordering caveat**: The FIFO matcher sorts by date only (not intraday time, since `_parse_flex_date()` strips time). Same-day multi-leg sequences (e.g., roll = sell Sep + buy Dec on same day) may be processed in arbitrary order. This is a pre-existing limitation affecting all instruments, not specific to futures. For portfolio-level NAV computation, intraday ordering has no impact (same end-of-day position snapshot).

**Known limitation**: Contract-specific attribution is lost — you can't distinguish P&L from the Sep vs Dec contract. This is acceptable for portfolio-level NAV/return computation. Users needing contract-level detail should use IBKR's native reporting.

## Symbol Namespace: Equity vs. Futures Root Collision

Some futures root symbols match real equity tickers (e.g., `ES` = Eversource Energy, `SI` = Silvergate Capital). The plan uses three guards:

1. **`is_futures` guard on fmp_ticker_map augmentation**: Only transactions tagged `is_futures=True` by the flex client trigger the futures→FMP mapping. Equity trades with symbol "ES" from Plaid/SnapTrade never set `is_futures`.

2. **Current-position guard (`sym not in fmp_ticker_map`)**: If equity ES has a current FMP mapping from `_build_current_positions()` (PositionService), the futures mapping is skipped.

3. **Historical-equity guard (`sym not in equity_symbols`)**: Scans ALL `fifo_transactions` for non-futures/non-option trades with the same symbol. If equity ES was held historically (even if now closed), the futures mapping is skipped. This prevents mispricing historical equity periods with commodity prices.

**Collision scenario**: If a user has EVER held equity ES (current or historical) AND trades futures ES through IBKR Flex, the guards block the futures remapping → futures ES can't be priced → warning emitted. This is the correct v1 behavior: safely degrading rather than corrupting equity pricing.

**Deduplication**: Each futures root symbol is processed only once (via `futures_mapped` set) to avoid duplicate collision warnings from multiple transactions of the same root.

In practice, this collision is unlikely because PositionService doesn't carry IBKR positions, and the user's Plaid/SnapTrade accounts are unlikely to hold the same root ticker as their IBKR futures positions.

## Files to Modify

1. `exchange_mappings.yaml` — add `ibkr_futures_to_fmp` mapping section
2. `services/ibkr_flex_client.py` — detect futures, adjust symbol + quantity
3. `trading_analysis/analyzer.py` — forward `is_futures` flag in FIFO transactions
4. `core/realized_performance_analysis.py` — augment `fmp_ticker_map` with futures mappings (guarded by `is_futures`)
5. `tests/services/test_ibkr_flex_client.py` — add futures normalization tests
6. `tests/trading_analysis/test_analyzer.py` — add `is_futures` forwarding test (if file exists, else inline with flex tests)

## Changes

### 1. Add futures mapping to `exchange_mappings.yaml`

New section at bottom of file:

```yaml
# IBKR futures root symbol → FMP commodity symbol
# IBKR Flex reports use root symbols (ES, GC, SI) or contract codes (ESU5, GCZ5)
# FMP uses {ROOT}USD format for commodity/futures historical prices
ibkr_futures_to_fmp:
  # Index Futures
  ES: ESUSD      # E-Mini S&P 500 (mult: 50)
  NQ: NQUSD      # E-Mini Nasdaq 100 (mult: 20)
  YM: YMUSD      # Mini Dow Jones (mult: 5)
  RTY: RTYUSD    # Mini Russell 2000 (mult: 50)
  # Metals
  GC: GCUSD      # Gold (mult: 100)
  MGC: MGCUSD    # Micro Gold (mult: 10)
  SI: SIUSD      # Silver (mult: 5000)
  HG: HGUSD      # Copper (mult: 25000)
  PL: PLUSD      # Platinum (mult: 50)
  PA: PAUSD      # Palladium (mult: 100)
  # Energy
  CL: CLUSD      # Crude Oil (mult: 1000)
  BZ: BZUSD      # Brent Crude (mult: 1000)
  NG: NGUSD      # Natural Gas (mult: 10000)
  # Fixed Income
  ZB: ZBUSD      # 30Y Treasury Bond (mult: 1000)
  ZN: ZNUSD      # 10Y Treasury Note (mult: 1000)
```

### 2. Detect and normalize futures in `normalize_flex_trades()`

**File**: `services/ibkr_flex_client.py`, function `normalize_flex_trades()` (line 124)

**Change A** — Add `is_futures` detection after line 150:
```python
is_option = asset_category == "OPT"
is_futures = asset_category == "FUT"
```

**Change B** — Set symbol to underlying root for futures (after line 157, restructure the if/else):
```python
if is_option:
    built = _build_option_symbol(
        underlying=underlying,
        put_call=_get_attr(trade, "putCall", "right"),
        strike=_get_attr(trade, "strike"),
        expiry=_get_attr(trade, "expiry", "expirationDate"),
    )
    symbol = built or symbol or underlying
elif is_futures:
    symbol = underlying  # Use root symbol (ES, not ESU5)
    # Warn if underlyingSymbol was missing (defaulted to raw symbol)
    raw_underlying = _get_attr(trade, "underlyingSymbol", "underlying")
    if not raw_underlying or str(raw_underlying).strip() == "":
        trading_logger.warning(
            "FUT trade missing underlyingSymbol; using raw symbol %s "
            "(may not match FMP mapping)", symbol
        )
else:
    symbol = symbol or underlying
```

Note: The warning checks the raw `underlyingSymbol` attribute directly, not the defaulted `underlying` variable. This avoids false positives when `underlyingSymbol` is present and happens to equal the raw symbol (e.g., root-only symbols like "ES" where both fields are "ES").

**Change C** — Adjust quantity by multiplier for futures (after line 168, before the quantity guard):
```python
quantity = abs(safe_float(_get_attr(trade, "quantity", "qty"), 0.0))
if is_futures and multiplier != 1:
    quantity = quantity * multiplier  # Convert contracts to notional units
```

Note: Uses `!= 1` instead of `> 1` to handle any non-unity multiplier. The `multiplier <= 0` guard at line 148 ensures multiplier is positive. For standard IBKR futures contracts, multipliers are always integers ≥ 1.

**Change D** — Add `is_futures` flag to output dict (alongside `is_option` at line 202):
```python
"is_option": is_option,
"is_futures": is_futures,
```

### 3. Forward `is_futures` in TradingAnalyzer

**File**: `trading_analysis/analyzer.py`, line 753 (inside `_process_ibkr_flex()`)

Add `is_futures` to the `fifo_transactions.append()` dict, alongside the existing `is_option`:

```python
self.fifo_transactions.append({
    'symbol': symbol,
    'type': trade_type,
    'date': date,
    'quantity': quantity,
    'price': price,
    'fee': fee,
    'currency': currency,
    'source': 'ibkr_flex',
    'transaction_id': txn.get('transaction_id'),
    'is_option': bool(txn.get('is_option')),
    'is_futures': bool(txn.get('is_futures')),  # NEW
    'account_id': txn.get('account_id', ''),
    '_institution': institution,
})
```

### 4. Augment `fmp_ticker_map` with futures mappings (guarded)

**File**: `core/realized_performance_analysis.py`, function `analyze_realized_performance()`

After `_build_current_positions()` returns `fmp_ticker_map` (line ~707), and before `build_position_timeline()` is called (line ~748):

```python
# Augment fmp_ticker_map with IBKR futures→FMP commodity mappings.
# Three guards prevent equity ticker collision:
#   1. is_futures check (only FUT-tagged transactions)
#   2. fmp_ticker_map check (current equity positions)
#   3. equity_symbols check (historical equity transactions)
from utils.ticker_resolver import load_exchange_mappings
futures_map = load_exchange_mappings().get("ibkr_futures_to_fmp", {})

# Collect all equity symbols (non-futures, non-option) to guard against
# historical equities that share root symbols with futures.
equity_symbols = {
    txn.get("symbol", "")
    for txn in fifo_transactions
    if not txn.get("is_futures") and not txn.get("is_option") and txn.get("symbol")
}

futures_mapped: set[str] = set()  # Process each root once to avoid duplicate warnings
for txn in fifo_transactions:
    sym = txn.get("symbol", "")
    if txn.get("is_futures") and sym in futures_map and sym not in futures_mapped:
        futures_mapped.add(sym)
        if sym in fmp_ticker_map or sym in equity_symbols:
            # Equity ticker (current or historical) with same root — skip to preserve equity pricing
            warnings.append(
                f"Futures symbol {sym} collides with equity ticker; "
                f"futures pricing skipped (equity mapping preserved)."
            )
        else:
            fmp_ticker_map[sym] = futures_map[sym]
```

This ensures `fetch_monthly_close("ES", fmp_ticker_map={"ES": "ESUSD"})` resolves correctly. The lookup uses the existing `select_fmp_symbol()` → `fmp_ticker_map.get(ticker)` path — no changes needed downstream.

**Key guards**:
- `txn.get("is_futures")`: Only FUT-tagged transactions trigger mapping.
- `sym in fmp_ticker_map`: Protects currently-held equity tickers.
- `sym in equity_symbols`: Protects historically-held equity tickers (even if now closed). Prevents mispricing historical equity periods with commodity data.
- `futures_mapped` set: Processes each root symbol once, preventing duplicate collision warnings from multiple transactions of the same root.

**Why augment from `fifo_transactions` only**: IBKR data doesn't flow through PositionService, so `current_positions` won't contain futures tickers. All futures symbols originate from IBKR Flex trades → `fifo_transactions`.

**Why here and not in `normalize_flex_trades()`**: The mapping only matters for price fetching, which happens in `analyze_realized_performance()`. Keeping it here avoids adding a YAML dependency to the flex client for a concern that's specific to the realized performance pipeline.

### 5. Tests

**File**: `tests/services/test_ibkr_flex_client.py` (existing test file)

Add futures-specific tests:

1. **`test_normalize_flex_trades_futures_uses_underlying_symbol`** — FUT trade with `symbol="ESU5"`, `underlyingSymbol="ES"` → output symbol is `"ES"`
2. **`test_normalize_flex_trades_futures_multiplies_quantity`** — FUT trade with `quantity=2`, `multiplier=50` → output quantity is `100`
3. **`test_normalize_flex_trades_futures_preserves_price`** — FUT trade with `tradePrice=5000`, `multiplier=50` → output price is `5000` (not multiplied)
4. **`test_normalize_flex_trades_futures_flag`** — FUT trade → `is_futures=True`; STK trade → `is_futures=False`

Add regression tests to verify existing behavior is preserved:

5. **`test_normalize_flex_trades_stock_unaffected_by_futures_changes`** — STK trade with `symbol="ES"` → output symbol is `"ES"`, quantity unchanged, `is_futures=False`
6. **`test_normalize_flex_trades_option_multiplier_still_applies_to_price`** — OPT trade with `multiplier=100` → price is multiplied (not quantity). Ensures futures quantity-adjustment path doesn't interfere with option price-adjustment path.
7. **`test_normalize_flex_trades_futures_missing_underlying`** — FUT trade where `underlyingSymbol` is absent → uses raw `symbol`, logs warning

**File**: `tests/core/test_realized_performance_analysis.py`

8. **`test_futures_fmp_ticker_map_augmentation`** — Mock `load_exchange_mappings` to return futures map, create `fifo_transactions` with `is_futures=True` → verify `fmp_ticker_map` gets augmented
9. **`test_futures_map_does_not_remap_equity_tickers`** — Same futures map, but `fifo_transactions` with `is_futures=False` and `symbol="ES"` → verify `fmp_ticker_map` is NOT augmented (equity ticker preserved)
10. **`test_futures_map_collision_warning_current_equity`** — `fmp_ticker_map` already has `"ES": "ES"` (current equity), `fifo_transactions` has `is_futures=True` for `symbol="ES"` → verify mapping NOT overwritten AND warning emitted
11. **`test_futures_map_collision_warning_historical_equity`** — `fmp_ticker_map` is empty, but `fifo_transactions` has BOTH `is_futures=False` (equity STK) and `is_futures=True` (futures FUT) for `symbol="ES"` → verify mapping NOT set AND warning emitted (historical equity guard)
12. **`test_futures_map_no_duplicate_collision_warnings`** — `fifo_transactions` has equity `ES` (`is_futures=False`) AND three futures `ES` trades (`is_futures=True`) → verify exactly ONE collision warning emitted (not three)

**File**: `tests/trading_analysis/test_analyzer.py` (or add to existing flex test file if no analyzer tests exist)

13. **`test_analyzer_forwards_is_futures_flag`** — Create TradingAnalyzer with IBKR flex trades containing `is_futures=True`, verify `fifo_transactions` output includes `is_futures: True`

## Dedup Safety

The dedup logic in `TradingAnalyzer._deduplicate_transactions()` uses key `(symbol, type, date, quantity, price, currency)`. After futures normalization, both the symbol (root) and quantity (multiplied) are transformed BEFORE dedup runs. This is safe because:

1. **Within IBKR**: Each trade has a unique `tradeID`, and IBKR doesn't report the same trade twice in a Flex report.
2. **Cross-provider**: Dedup only removes Plaid/SnapTrade trades that match IBKR trades. Plaid doesn't report futures, so no false-match risk.
3. **Same-root collisions**: Two different futures trades (ESU5 + ESZ5) on the same day with identical `(qty*mult, price)` would have the same dedup key. This is extremely unlikely — different contract months have different prices. If it occurs, one Plaid-side duplicate would be removed (net zero impact since Plaid doesn't have the trade anyway).

## Verification

1. Run all futures tests (adjust path for test #13 based on where analyzer test is placed):
   ```
   pytest tests/services/test_ibkr_flex_client.py tests/core/test_realized_performance_analysis.py -v -k "futures"
   ```
   If test #13 is in a separate file, add its path to the command.
2. Restart MCP server, then call `get_performance(mode="realized", format="summary")`:
   - Check `data_warnings` for fewer "No monthly prices found" warnings
   - Compare total_return / CAGR before and after — should improve with futures properly valued
   - Verify `V_adjusted<=0` warning count decreases (was 13 months)
3. Verify FIFO P&L is unchanged for non-futures positions (futures P&L should now be correctly multiplied)

## Edge Cases

- **Unknown futures root**: If IBKR symbol not in `ibkr_futures_to_fmp`, falls through to raw ticker → FMP lookup fails → `price_cache` empty → valued as 0 with warning. Same behavior as today. New symbols can be added to `exchange_mappings.yaml` as needed — no code changes required.
- **FMP 402 (subscription limit)**: Some commodity symbols (CLUSD, NGUSD, etc.) return HTTP 402. Handled gracefully — falls through to empty price_cache with warning.
- **Micro contracts**: MGC (Micro Gold, mult=10) vs GC (Gold, mult=100) — different multipliers, both mapped to distinct FMP symbols. Each valued correctly.
- **Futures spreads**: Long ESU5 + Short ESZ5 both map to symbol "ES". Position timeline keys on `(ticker, currency, direction)` — long and short are separate entries. Net directional exposure is correctly minimal.
- **No `underlyingSymbol` field**: Falls back to `symbol` (line 154 of flex client). If raw symbol is a contract code like "ESU5", it won't match the mapping table → warning logged → valued as 0. IBKR Flex reports consistently include `underlyingSymbol`, so this is an unlikely edge case.
- **Equity ticker collision**: Equity tickers matching futures roots (e.g., ES=Eversource, SI=Silvergate) are protected by three guards: `is_futures` flag, current-position check, and historical-equity scan. If equity ES exists (current or historical), futures mapping is skipped with warning (equity pricing preserved). See "Symbol Namespace" section.
- **Contract expiry collapsing**: All contract months for the same root collapse to one symbol. P&L attribution is portfolio-level, not contract-specific. Rolls are correctly captured via FIFO ordering. Same-day multi-leg ordering is not guaranteed (pre-existing limitation for all instruments). See "Contract Expiry Collapsing" section.
- **Multiplier edge cases**: `multiplier <= 0` is already guarded (set to 1.0 at line 148). `multiplier == 1` skips adjustment (no-op). Non-standard fractional multipliers are handled by the `!= 1` check.

## Known Limitations (v1)

1. **Fully-funded cash model**: Futures are modeled as fully-funded positions rather than margined. Returns represent fully-funded notional returns, not margin-capital returns. P&L magnitudes are correct. See "Margin vs. Fully-Funded Cash Flow Model" section.
2. **No contract-level attribution**: All contract months for the same underlying are pooled. Portfolio-level NAV and returns are correct.
3. **Static mapping table**: The `ibkr_futures_to_fmp` table must be manually extended for new futures products. Graceful fallback for unmapped symbols (warning + value as 0).
4. **Equity/futures root collision**: If a user holds (currently or historically) both equity and futures of the same root symbol, futures pricing is skipped to preserve equity correctness. Warning emitted.
5. **Same-day ordering**: FIFO processes same-day trades in insertion order (no intraday time). This can affect lot-level attribution on same-day rolls but not portfolio-level NAV.

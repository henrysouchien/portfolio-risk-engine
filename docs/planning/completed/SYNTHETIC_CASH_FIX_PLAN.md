# Fix: Synthetic Position Cash Flow Mismatch in Realized Performance — COMPLETE

## Goal

`get_performance(mode="realized")` should return an accurate picture of the portfolio's actual historical performance based on transaction history. Specifically:
- Monthly returns should be mathematically valid (no -307% for long-only positions)
- NAV reconstruction should properly account for capital deployed — even when we lack full transaction history
- The TWR (time-weighted return) should reflect actual investment performance, stripping out the effect of deposits/withdrawals
- Where data is incomplete (synthetic positions), use inception-date market prices as the baseline — honest about what we don't know, accurate with what we do

This fix only affects the **return/performance metrics path**. Realized P&L, unrealized P&L, and income are computed from FIFO matching on real transactions and are already correct.

## Context

The `get_performance(mode="realized")` MCP tool produces impossible monthly returns (-139%, -149%, -307%) for an all-long portfolio. The root cause: when current holdings lack BUY transaction history (18 of 24 positions), synthetic position entries are created in the position timeline but **no corresponding cash outflows** are created. This means:

- **Position side**: $150K of holdings valued from inception day 1
- **Cash side**: $0 starting cash, only real transactions affect it
- **NAV = positions + cash** is wildly inflated, producing extreme Modified Dietz returns

The fix: when synthetic positions are created, also inject synthetic BUY/SHORT pseudo-transactions into the cash derivation so capital deployment is properly accounted for.

## Files to Modify

1. `core/realized_performance_analysis.py` — main fix (5 changes)
2. `mcp_tools/performance.py` — add `include_series` param, pass through to engine
3. `services/portfolio_service.py` — pass `include_series` through service layer, update cache key
4. `tests/core/test_realized_performance_analysis.py` — update 2 tests, add ~7 new core tests
5. `tests/mcp_tools/test_performance.py` (or existing test file) — add test #9 for MCP `include_series` passthrough
6. `tests/services/test_portfolio_service.py` (or existing test file) — add test #8 for service-layer `include_series` + cache key

## Changes

### 1. Extend `build_position_timeline()` return to include synthetic entry details

**Current** (line 164): Returns 3-tuple `(position_events, synthetic_positions, warnings)`
- `synthetic_positions` is metadata only: `[{"ticker", "currency", "direction"}]` — no quantity or date

**Change**: Return 4-tuple, adding `synthetic_entries: List[Dict]` with full details:
```python
# For current positions without history:
synthetic_entries.append({
    "ticker": ticker,
    "currency": currency,
    "direction": direction,
    "date": inception_date,
    "quantity": missing_openings,
    "source": "synthetic_current_position",
    "price_hint": None,  # will be looked up from price_cache at date
})

# For incomplete FIFO trades:
synthetic_entries.append({
    "ticker": symbol,
    "currency": currency,
    "direction": direction,
    "date": sell_date - timedelta(seconds=1),
    "quantity": qty,
    "source": "synthetic_incomplete_trade",
    "price_hint": sell_price,  # use exit price as neutral placeholder
})
```

Track `synthetic_entries` list alongside existing `synthetic_keys` set (line 212). Populate it in both code paths:
- Current positions without opening history (line 228-229)
- Incomplete FIFO trades (line 244-246)

**Dedup guard**: Track synthetic quantity already added per `(ticker, currency, direction)`. When an incomplete-trade synthetic is created for a key that already has a current-position synthetic, skip the incomplete-trade entry to avoid double-counting. The current-position synthetic already covers the full required quantity including exits.

Keep existing `synthetic_positions` metadata list unchanged for backward compat.

**Callers to update**: line 655 in `analyze_realized_performance()`, 2 tests at lines 39 and 65.

### 2. Add `_create_synthetic_cash_events()` helper function

New function (insert after `build_position_timeline`, ~line 262):

```python
def _create_synthetic_cash_events(
    synthetic_entries: List[Dict[str, Any]],
    price_cache: Dict[str, pd.Series],
    fx_cache: Dict[str, pd.Series],
) -> Tuple[List[Dict[str, Any]], List[str]]:
```

Returns `(pseudo_transactions, warnings)` tuple.

For each synthetic entry:
- Look up price at the **entry's own date** from `price_cache` using a **strict backward-only lookup** (`<= entry_date`, no forward fallback). Do NOT use `_value_at_or_before()` directly since it falls forward to the next available price when no prior exists (`core/realized_performance_analysis.py:79`). Instead, use just the `prior` branch logic (filter series to `<= date`).
- For incomplete-trade synthetics (`source == "synthetic_incomplete_trade"`): use the `price_hint` field (exit price) from the synthetic entry as a neutral placeholder — avoids inventing unknown P&L for the brief synthetic holding period
- If price <= 0 or no price found: skip and append warning explaining which ticker was skipped
- Create pseudo-transaction: `{"type": "BUY"/"SHORT", "symbol", "date", "quantity", "price", "fee": 0, "currency", "source": "synthetic_cash_event"}`
- These are compatible with `derive_cash_and_external_flows()` input format

### 3. Integrate synthetic cash events in `analyze_realized_performance()`

After price_cache and fx_cache are built (~line 711), before `derive_cash_and_external_flows()` call (line 713):

```python
# Create synthetic cash events for positions without transaction history
synthetic_cash_events, synth_cash_warnings = _create_synthetic_cash_events(
    synthetic_entries, price_cache, fx_cache
)
warnings.extend(synth_cash_warnings)

# Merge with real transactions for cash derivation ONLY (not FIFO — already ran)
transactions_for_cash = fifo_transactions + synthetic_cash_events

cash_snapshots, external_flows = derive_cash_and_external_flows(
    fifo_transactions=transactions_for_cash,  # was: fifo_transactions
    income_with_currency=income_with_currency,
    fx_cache=fx_cache,
)
```

This makes cash go negative at inception for synthetic buys → triggers external flow injection → proper capital accounting.

### 4. Expose NAV and growth-of-$1 series in output (opt-in)

In `analyze_realized_performance()`, after `monthly_returns` is computed, add two new series to `realized_metadata` — but only when requested, since they add a full time series to the response.

**Core engine** (`analyze_realized_performance()`): Add `include_series: bool = False` parameter. When True, include:

```python
# Monthly NAV (raw portfolio value including contributions)
"monthly_nav": {ts.date().isoformat(): round(float(val), 2) for ts, val in monthly_nav.items()}

# Growth of $1 (TWR — pure performance, strips out capital flows)
cumulative = (1 + monthly_returns).cumprod()
"growth_of_dollar": {ts.date().isoformat(): round(float(val), 4) for ts, val in cumulative.items()}
```

- **`monthly_nav`**: Raw portfolio value at each month-end (positions + cash). Useful for "how much is my portfolio worth" charts. Includes effect of contributions/withdrawals.
- **`growth_of_dollar`**: Cumulative product of (1 + monthly_return). Strips out capital flows — purely measures investment skill. Starts at ~1.0, value of 1.10 means +10% TWR.

No new computation needed — both are derived from data already computed in the pipeline.

**Service layer** (`services/portfolio_service.py`): Pass `include_series` through `analyze_realized_performance()`. Add to cache key to prevent stale cross-talk (cached result without series served when series requested, or vice versa).

**MCP layer** (`mcp_tools/performance.py`): Add `include_series` param to `get_performance()` tool. Default False. Only passed through when `mode="realized"`.

**Behavior by format**:
- `format="summary"`: Never includes series (regardless of `include_series`)
- `format="full"`: Includes series when `include_series=True`
- `format="report"`: Never includes series (text format)

This keeps the default response compact while allowing chart data on demand.

### 5. Add safety clamp for extreme returns in `analyze_realized_performance()`

Apply the clamp **after** `compute_monthly_returns()` returns, inside `analyze_realized_performance()` — NOT inside `compute_monthly_returns()` itself. This is where we have access to `data_coverage` and can detect long-only portfolios (no SHORT keys in `position_timeline`).

**Important**: The `data_coverage` calculation (currently at ~line 826) must be moved **before** the clamp. Extract the `opening_keys` / `current_position_keys` / coverage computation to run right after `monthly_returns` is computed, before the clamp logic.

```python
# After monthly_returns is computed (line ~732):
# Detect if portfolio is long-only (no SHORT direction keys)
is_long_only = all(direction != "SHORT" for _, _, direction in position_timeline.keys())

# Compute data_coverage early (moved from later in the function) so we can gate the clamp
# data_coverage = (positions with full buy history / total current positions) * 100

# Clamp extreme returns only when data is incomplete AND portfolio is long-only
if data_coverage < 100.0 and is_long_only:
    for ts in monthly_returns.index:
        raw = monthly_returns.loc[ts]
        if raw < -1.0:
            warnings.append(
                f"{ts.date().isoformat()}: Clamping return from {raw:.2%} to -100.0%. "
                "Likely caused by incomplete transaction history."
            )
            monthly_returns.loc[ts] = -1.0
        elif abs(raw) > 3.0:
            warnings.append(
                f"{ts.date().isoformat()}: Extreme return detected ({raw:.2%}). "
                "This may indicate missing transaction history."
            )
```

This is a **defensive safety net**, not the primary fix. It prevents impossible returns from propagating even if synthetic cash events are incomplete (e.g., no price data at inception). The clamp is gated to avoid masking legitimate extreme returns from fully-tracked leveraged/short portfolios.

## Tests

### Update 2 existing tests
- `test_build_position_timeline_adds_synthetic_for_current_without_opening_history` (line 39): Unpack 4-tuple, assert `synthetic_entries` has correct quantity/date
- `test_build_position_timeline_adds_synthetic_before_incomplete_trade_date` (line 65): Same

### Add new tests
1. **`test_create_synthetic_cash_events_generates_pseudo_buys`** — LONG → BUY, SHORT → SHORT pseudo-txns with correct prices; verify warnings list returned
2. **`test_synthetic_cash_events_skip_positions_without_prices`** — Graceful handling when no price data; verify warning emitted
3. **`test_synthetic_positions_with_cash_produce_correct_nav_and_returns`** — Integration: timeline → synthetic cash → NAV → returns are reasonable (not extreme)
4. **`test_analyze_realized_performance_clamps_extreme_negative_returns`** — Verify -100% clamp in `analyze_realized_performance()` when data_coverage < 100 and long-only; raw value in warning text
5. **`test_analyze_realized_performance_with_synthetic_positions`** — Full pipeline with NO transaction history, verify returns are bounded and warnings present
6. **`test_build_position_timeline_dedup_current_and_incomplete_same_key`** — Current position + incomplete sell on same ticker: only one synthetic entry created (not double-counted)
7. **`test_include_series_in_realized_metadata`** — Verify `monthly_nav` and `growth_of_dollar` present when `include_series=True`, absent when False
8. **`test_service_layer_passes_include_series`** — Verify `services/portfolio_service.py` passes `include_series` to engine and includes it in cache key
9. **`test_mcp_include_series_param_passthrough`** — Verify `mcp_tools/performance.py` passes `include_series` only for `mode="realized"`, strips it for summary/report formats

### Test patterns to follow (from existing tests)
- `SimpleNamespace` for PositionResult mocks
- `_constant_fx()` helper for FX series
- `monkeypatch` for I/O boundaries
- `pytest.approx()` for float comparisons

## Verification

1. Run tests: `pytest tests/core/test_realized_performance_analysis.py tests/mcp_tools/ -v -k "realized or performance or synthetic or include_series"`
2. MCP test: Call `get_performance(mode="realized", format="full")` and verify:
   - No monthly returns below -100%
   - Total return is bounded and reasonable
   - `data_warnings` includes synthetic cash event creation message
   - `synthetic_positions` list still populated correctly
3. Compare key metrics before/after: realized_pnl, unrealized_pnl, income totals should be unchanged (those come from FIFO, not NAV)
4. MCP test: Call `get_performance(mode="realized", format="full", include_series=True)` and verify `monthly_nav` and `growth_of_dollar` are present in `realized_metadata` with reasonable values
5. MCP test: Call `get_performance(mode="realized", format="summary")` and verify series are NOT included

## Edge Cases

- **No price at inception**: Synthetic cash event skipped, position still valued → may still produce some mismatch, but safety clamp prevents extreme returns. Warning emitted.
- **Multi-currency synthetics**: FX applied via existing `_event_fx_rate()` in `derive_cash_and_external_flows`
- **SHORT synthetics**: Pseudo-transaction type = "SHORT" (cash increases, position negative) — correct accounting
- **Incomplete trades**: Synthetic date = `sell_date - 1 second`, priced at exit price (neutral placeholder) — BUY and SELL nearly cancel out, avoiding invented P&L
- **Duplicate synthetic keys**: When both current-position and incomplete-trade paths create synthetics for the same `(ticker, currency, direction)`, the incomplete-trade entry is suppressed. The current-position synthetic already accounts for the full required quantity.
- **Cache key isolation**: `include_series` is part of the service-layer cache key, preventing stale cross-talk between series/no-series requests

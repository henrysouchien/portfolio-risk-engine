# Fix: Align synthetic TWR flow prices with NAV prices

## Context

After the synthetic TWR flow fix (commit `12966d69`), IBKR realized performance improved from -32.53% to -24.80% (broker actual: -9.35%). The remaining ~15pp gap is caused by a **price mismatch between synthetic TWR flows and NAV valuation**.

**Root cause:** For incomplete trades (17 of 18 synthetic positions), `_synthetic_events_to_flows()` uses the **sell price** from `evt.get("price")` (set by `_create_synthetic_cash_events()` at line 1535 from `incomplete.sell_price`). But `compute_monthly_nav()` values these same positions using **market prices from `price_cache`** via `_value_at_or_before()` (line 2022).

**Verified mismatch:** $3,042 across 7 stock tickers = 12.2% of portfolio. All sell prices < market prices at inception (stocks were sold at losses during April tariff crash), creating systematic +12% artificial March return that reverses as -12% artificial April loss.

**Example:** CBL — sell price $22.87, market price at inception $31.27. Flow = $2,287 but NAV = $3,127. TWR interprets the $840 gap as return.

## Fix

Align `_synthetic_events_to_flows()` to use the same price source as NAV: `price_cache` via `_value_at_or_before()`.

### Files to modify

| File | Change |
|------|--------|
| `core/realized_performance_analysis.py:866` | Add `price_cache` param to `_synthetic_events_to_flows()`, use `_value_at_or_before()` for price lookup |
| `core/realized_performance_analysis.py:4482` | Pass `price_cache` at call site |
| `tests/core/test_synthetic_twr_flows.py` | Update existing tests + add price_cache override tests |

### 1. Update `_synthetic_events_to_flows()` (line 866)

Add `price_cache` parameter. For each event, look up the NAV-aligned price from `price_cache` using `_value_at_or_before()`. Fall back to `evt.get("price")` if no price_cache entry.

```python
def _synthetic_events_to_flows(
    synthetic_cash_events: List[Dict[str, Any]],
    fx_cache: Dict[str, pd.Series],
    price_cache: Optional[Dict[str, pd.Series]] = None,
) -> List[Tuple[datetime, float]]:
    """Convert synthetic cash events to external flow tuples for TWR.
    ...
    When price_cache is provided, uses NAV-aligned market prices instead
    of the event's sell price. This ensures TWR flows match NAV valuation
    so inception-day return is ~0%.
    """
    flows: List[Tuple[datetime, float]] = []
    for evt in synthetic_cash_events:
        evt_date = _to_datetime(evt.get("date"))
        if evt_date is None:
            continue

        # Use NAV-aligned price from price_cache when available,
        # fall back to event price (sell price for incomplete trades).
        ticker = evt.get("symbol") or ""
        nav_price = None
        if price_cache and ticker:
            nav_price = _value_at_or_before(
                price_cache.get(ticker), evt_date, default=0.0
            )
            if nav_price <= 0:
                nav_price = None

        price = nav_price if nav_price is not None else _as_float(evt.get("price"), 0.0)
        qty = _as_float(evt.get("quantity"), 0.0)
        if price <= 0 or qty <= 0:
            continue

        currency = str(evt.get("currency") or "USD").upper()
        fx = _event_fx_rate(currency, evt_date, fx_cache)
        notional_usd = price * qty * fx

        evt_type = str(evt.get("type") or "BUY").upper()
        signed_amount = notional_usd if evt_type != "SHORT" else -notional_usd
        if abs(signed_amount) > 1e-6:
            flows.append((evt_date, signed_amount))

    return flows
```

Key details:
- `_value_at_or_before()` already exists (line ~830) — same function used by `compute_monthly_nav()` line 2022
- Synthetic cash events use `"symbol"` key (set at line 1573 of `_create_synthetic_cash_events()`)
- Falls back to event price if ticker not in price_cache (graceful degradation)
- `price_cache` is Optional so existing tests work without changes

### 2. Update call site (line 4482)

```python
# Before:
synthetic_twr_flows = _synthetic_events_to_flows(synthetic_cash_events, fx_cache)

# After:
synthetic_twr_flows = _synthetic_events_to_flows(
    synthetic_cash_events, fx_cache, price_cache=price_cache
)
```

`price_cache` is already in scope at this point (built at lines 3638-3787).

### 3. Update tests (`tests/core/test_synthetic_twr_flows.py`)

Existing tests pass `price_cache=None` implicitly (backward compat via Optional default). Add new tests:

- **`test_price_cache_overrides_sell_price`**: Synthetic event with price=22.87, price_cache has ticker at 31.27 on or before event date → flow uses 31.27
- **`test_price_cache_fallback_to_event_price`**: Ticker not in price_cache → falls back to event price
- **`test_price_cache_empty_series_fallback`**: Ticker in price_cache but series empty → falls back to event price
- **`test_price_cache_aligns_with_nav`**: Integration test — NAV-aligned price produces same flow as position NAV contribution → inception-day TWR return ~0%

## Verification

1. `python3 -m pytest tests/core/test_synthetic_twr_flows.py -v`
2. `python3 -m pytest tests/core/test_realized_performance_analysis.py -v --tb=short`
3. Live: `get_performance(mode="realized", source="ibkr_flex", use_cache=false)`
4. Expected: April -39% moderates significantly, total return closer to broker -9.35%
5. Schwab/Plaid: should be unchanged

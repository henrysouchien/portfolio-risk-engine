# Fix: Include synthetic cash events as TWR external flows

## Context

IBKR realized performance shows -32.53% vs broker actual -9.35%. The distortion comes from **19 synthetic positions** that appear in NAV but whose cash events are excluded from TWR external flows.

**The mechanism:**
- Synthetic positions are created for first-transaction-exits (e.g. CBL first trade is a SELL on April 8 → synthetic BUY placed at inception)
- `compute_monthly_nav()` includes synthetic position values in daily NAV
- `_create_synthetic_cash_events()` creates pseudo BUY/SHORT transactions (line 3794)
- These are **excluded from cash replay** at line 3810: `transactions_for_cash = fifo_transactions`
- The exclusion comment (line 3807): "avoid inflating the Modified Dietz denominator"
- `compute_twr_monthly_returns()` receives `external_flows` that lack synthetic events

**Result:** When a synthetic position appears, NAV jumps (e.g. $5K → $50K) but TWR sees no corresponding flow. The GIPS formula `R = (V_D + |CF_out|) / (V_{D-1} + CF_in) - 1` interprets the jump as a +900% daily return instead of a contribution.

**The fix:** Include synthetic cash events as flows in `external_flows` for the TWR path only. BUY synthetics become positive inflows (NAV increases by long position value), SHORT synthetics become negative outflows (NAV decreases by short position liability). This makes synthetic position appearances look like contributions (correct TWR behavior), yielding ~0% return on the day they appear. Subsequent price changes are still captured as returns.

Modified Dietz is unaffected — the exclusion was correct for that formula.

**Prior fixes already committed:**
- `fe297eda`: StmtFunds topic name fix
- `264c2940`: Ghost account filtering in `_discover_account_ids()`

## Files to Modify

| File | Change |
|------|--------|
| `core/realized_performance_analysis.py` | New `_synthetic_events_to_flows()` helper |
| `core/realized_performance_analysis.py:4437` | Build `synthetic_twr_flows`, create `twr_external_flows` |
| `core/realized_performance_analysis.py:4549` | Pass `twr_external_flows` to TWR call |
| `core/realized_performance_analysis.py:5144` | Store `twr_external_flows` in `_postfilter["external_flows"]` for aggregation |
| `tests/core/test_synthetic_twr_flows.py` | New tests for synthetic flow injection |

## Implementation

### 1. Build TWR-specific external flows (`core/realized_performance_analysis.py`)

After line 4437 (where `external_flows` is returned from `_compose_cash_and_external_flows`), convert synthetic cash events to flow tuples and create a TWR-specific flow list.

Add a module-level helper function:

```python
def _synthetic_events_to_flows(
    synthetic_cash_events: List[Dict[str, Any]],
    fx_cache: Dict[str, pd.Series],
) -> List[Tuple[datetime, float]]:
    """Convert synthetic cash events to external flow tuples for TWR.

    Synthetic positions appear in NAV but their cash events are excluded
    from the cash replay (to avoid inflating the Modified Dietz denominator).
    For TWR, we need matching flows so the GIPS formula treats position
    appearances as contributions rather than returns.

    Sign convention (matches TWR flow semantics):
    - BUY  → positive inflow  (NAV increases by long position value)
    - SHORT → negative outflow (NAV decreases by short position liability)
    """
    flows: List[Tuple[datetime, float]] = []
    for evt in synthetic_cash_events:
        evt_date = _to_datetime(evt.get("date"))
        if evt_date is None:
            continue
        price = _as_float(evt.get("price"), 0.0)
        qty = _as_float(evt.get("quantity"), 0.0)
        if price <= 0 or qty <= 0:
            continue
        currency = str(evt.get("currency") or "USD").upper()
        fx = _event_fx_rate(currency, evt_date, fx_cache)
        notional_usd = price * qty * fx
        # BUY = positive inflow, SHORT = negative outflow
        evt_type = str(evt.get("type") or "BUY").upper()
        signed_amount = notional_usd if evt_type != "SHORT" else -notional_usd
        if abs(signed_amount) > 1e-6:
            flows.append((evt_date, signed_amount))
    return flows
```

**Note:** `_event_fx_rate()` already exists in the module (line 858). `_to_datetime()` and `_as_float()` are existing helpers. The `type` field on synthetic cash events is `"BUY"` or `"SHORT"` (set at line 1533 of `_create_synthetic_cash_events`).

### 2. Wire it into the TWR path and create combined flow list

After line 4437, add:
```python
# Synthetic cash events as TWR flows — synthetic positions appear in
# NAV, so TWR needs matching flows to treat them as contributions
# rather than returns.  BUY → positive inflow, SHORT → negative outflow.
# Modified Dietz path (net_flows/tw_flows) is unaffected — the exclusion
# at line 3810 was correct for that formula.
synthetic_twr_flows = _synthetic_events_to_flows(synthetic_cash_events, fx_cache)
twr_external_flows = external_flows + synthetic_twr_flows
```

At line 4549, change:
```python
# Before:
monthly_returns, return_warnings = compute_twr_monthly_returns(
    daily_nav=daily_nav,
    external_flows=external_flows,
    month_ends=month_ends,
)

# After:
monthly_returns, return_warnings = compute_twr_monthly_returns(
    daily_nav=daily_nav,
    external_flows=twr_external_flows,
    month_ends=month_ends,
)
```

### 3. Carry synthetic flows through to `_postfilter` for aggregation

**Critical:** The aggregation path (`_build_aggregated_result` at line 5575) reads per-account `external_flows` from `_postfilter` via `_sum_account_daily_series()` (line 5486) and re-passes them to `compute_twr_monthly_returns()` at line 5646. If we only fix the single-account TWR call but store the original `external_flows` in `_postfilter`, the aggregated result will still be broken.

At line 5144, change:
```python
# Before:
"external_flows": _flows_to_dict(external_flows),

# After:
"external_flows": _flows_to_dict(twr_external_flows),
```

This ensures the aggregation path picks up synthetic flows automatically. No changes needed in `_build_aggregated_result` or `_sum_account_daily_series` themselves.

**Date alignment note:** Synthetic entries are timestamped at `inception - 1s` (line 1326/1377). `_flows_to_dict` normalizes to calendar date via `pd.Timestamp(dt).normalize().date()` (line 5401), so `inception - 1s` becomes the same calendar date as inception. When `_sum_account_daily_series` filters flows by `when >= first_viable` (line 5495), `_dict_to_flow_list` has already reconstructed flows at midnight of the inception date, which equals `first_viable`. So synthetic flows are not dropped. Additionally, the $500 `min_inception_nav` filter only activates for tiny-base accounts — IBKR starts well above $500.

**Note:** Modified Dietz paths (`net_flows`, `time_weighted_flows`) remain unchanged — they correctly use the non-synthetic `external_flows`.

### 4. SELL/COVER side analysis

When a synthetic position is unwound:
- **Synthetic BUY → real SELL**: The SELL is in `fifo_transactions` → flows through cash replay → already generates external flows if needed. NAV drops (position removed), cash increases. TWR handles this correctly.
- **Synthetic SHORT → real COVER**: The COVER is in `fifo_transactions` → flows through cash replay. COVER may generate an inferred positive external flow (line 1815) if opening SHORT proceeds weren't in the cash replay (they weren't — synthetic cash events are excluded). This is acceptable: the inferred injection on COVER day compensates for the missing SHORT proceeds, and the synthetic SHORT negative outflow on inception day compensated for the NAV decrease. The net effect is correct TWR behavior for the full lifecycle.

No additional handling needed for the unwind side — the combination of synthetic flows (inception) + inferred flows (unwind) produces correct TWR for both long and short synthetic lifecycles.

### 5. Tests (`tests/core/test_synthetic_twr_flows.py`)

**Helper unit tests:**
1. **`test_synthetic_events_to_flows_basic`** — 1 synthetic BUY with USD → returns correct (date, +amount) tuple
2. **`test_synthetic_events_to_flows_short_negative`** — 1 synthetic SHORT → returns (date, -amount) tuple (negative outflow)
3. **`test_synthetic_events_to_flows_fx`** — Synthetic BUY in GBP → amount converted to USD
4. **`test_synthetic_events_to_flows_skips_zero_price`** — Events with price=0 or qty=0 are skipped
5. **`test_synthetic_events_to_flows_empty`** — Empty list → empty result

**TWR integration tests:**
6. **`test_twr_with_synthetic_flows_neutralizes_inception`** — Build daily NAV with synthetic position, compute TWR with synthetic flows → inception day return ~0%
7. **`test_twr_without_synthetic_flows_shows_spike`** — Same setup but without synthetic flows → inception day return is extreme (confirms the problem)
8. **`test_twr_short_synthetic_lifecycle`** — SHORT synthetic at inception + COVER later: verify both inception day and cover day returns are reasonable (not extreme)

**Wiring/aggregation tests:**
9. **`test_twr_external_flows_includes_synthetics`** — Mock `_analyze_realized_performance_single_scope` internals: verify `twr_external_flows` (passed to TWR and stored in `_postfilter`) includes both `external_flows` and `synthetic_twr_flows`
10. **`test_postfilter_external_flows_carries_synthetics`** — Verify `_postfilter["external_flows"]` contains synthetic flow entries (so aggregation picks them up)
11. **`test_synthetic_flow_survives_aggregation_round_trip`** — Build a stub `_postfilter` with synthetic flow at inception date, run through `_sum_account_daily_series` → verify flow is NOT dropped by the `min_inception_nav` filter (date alignment: `inception - 1s` normalizes to same calendar date as first NAV)

## Verification

1. `python3 -m pytest tests/core/test_synthetic_twr_flows.py -v`
2. `python3 -m pytest tests/core/test_realized_performance_analysis.py -v --tb=short` (regression)
3. Live test after `/mcp` reconnect: `get_performance(mode="realized", source="ibkr_flex", use_cache=false)`
4. Confirm:
   - March extreme month reduced from +490%
   - April/May extreme months reduced from -64%/-75%
   - Total return closer to broker actual (-9.35%)
5. Schwab check: `get_performance(mode="realized", source="schwab", use_cache=false)` — should be unchanged (Schwab has matching position/transaction account names, fewer synthetic positions)

# Synthetic Position Cost-Basis Flow Injection Fix

**Target**: Schwab +33.13% → ≤ +12% (broker actual: -8.29%)

## Problem

Schwab reports +33.13% total return vs broker actual of -8.29% (41pp gap).

Six synthetic positions (CPPMF, DSU, GLBE, LIFFF, MSCI, PCTY) are placed at global inception (Apr 29, 2024) in the position timeline. `compute_monthly_nav()` values them at **FMP historical prices each month-end**, so their market appreciation shows up as portfolio returns. But the cash replay has no record of these "purchases" — synthetic cash events are intentionally excluded (P2A fix, `transactions_for_cash = fifo_transactions`).

### Distortion Breakdown

| Period | System Return | What Happened |
|--------|--------------|---------------|
| Apr-Dec 2024 | +23.7% | 100% synthetic positions, zero cash flows. FMP appreciation → phantom returns |
| Jan-Dec 2025 | +6.3% | After $65K contribution. Synthetic appreciation still inflates returns |
| Full period | +33.13% | Compounded phantom + real distortion |

### Root Cause: FMP inception price ≠ broker cost basis

The core distortion is a **price mismatch**, not repricing itself:

```
FMP inception (Apr 2024):  $38,269  ← what _create_synthetic_cash_events uses
Broker cost basis:         $44,933  ← what was actually paid
Current FMP value:         $42,085

FMP view:   +10.0% gain ($38K → $42K)
Broker view: -6.3% loss ($45K → $42K)
```

`_create_synthetic_cash_events()` currently prefers FMP backward lookup over `price_hint` (broker cost basis) for `synthetic_current_position` entries. Since the synthetic cash events are excluded from replay anyway (P2A), this mismatch is invisible — NAV sees FMP prices, denominator sees nothing.

### Why the previous "frozen NAV" approach was too conservative

An earlier plan (v1, 17 Codex reviews) proposed freezing synthetic positions at constant inception price — zero returns on synthetic capital. This works but kills real market movements. The positions are real holdings; the broker confirms them. We just have the wrong cost basis.

### Why naive flow injection with FMP prices doesn't help

Injecting synthetic cash events at FMP inception price into external flows produces 0.00pp delta:
- Month 1: `V_end = FMP_price * qty`, `flow = FMP_price * qty` → return = 0% (cancels out)
- Month 2+: `V_start = prev_nav` — identical with or without injection

The injection is invisible because both NAV and flow use the same FMP price.

### The fix: inject at broker cost basis

If we inject the flow at **broker cost basis** instead of FMP price:
- Month 1: `V_end = $38K (FMP)`, `flow = $45K (broker cost)` → return = (38-45)/45 = **-15.6%**
- Month 2+: `V_start = $38K`, normal FMP repricing continues

Month 1 captures the cost-basis-to-market gap. Months 2+ track real market movements on a properly capitalized base. This matches what the broker actually sees.

---

## Fix: Inject Synthetic Cash Events at Broker Cost Basis for Fully-Synthetic Keys

Two changes:
1. Flip `_create_synthetic_cash_events()` price priority for `synthetic_current_position` to prefer `price_hint` (broker cost basis) over FMP
2. Selectively inject synthetic cash events into `external_flows` for fully-synthetic keys only

### File: `core/realized_performance_analysis.py`

#### Change 1: Flip price priority in `_create_synthetic_cash_events()`

Currently, `synthetic_current_position` entries use FMP first, `price_hint` as fallback. Flip this (search: `def _create_synthetic_cash_events`):

```python
price = 0.0
if source == "synthetic_incomplete_trade":
    # Incomplete trades: use sell_price (price_hint) as before — this is correct.
    # The SELL enters cash replay at sell_price, so the synthetic opening
    # should match for neutral SELL→cash conversion.
    price = _as_float(entry.get("price_hint"), 0.0)
else:
    # synthetic_current_position: prefer broker cost basis (price_hint) over FMP.
    # price_hint comes from _synthetic_price_hint_from_position() which returns
    # cost_basis/qty (preferred) or value/qty for USD positions.
    # Using broker cost basis ensures the synthetic flow matches actual capital deployed,
    # so Modified Dietz month 1 captures the real cost-basis-to-market gap.
    price = _as_float(entry.get("price_hint"), 0.0)
    if price <= 0:
        # Fallback to FMP backward lookup if no broker cost basis available
        series = _series_from_cache(price_cache.get(ticker))
        prior = series[series.index <= pd.Timestamp(date)]
        if not prior.empty:
            price = _as_float(prior.iloc[-1], 0.0)
```

The existing fallback chain for `price <= 0` remains unchanged — it handles the case where neither price_hint nor FMP is available.

Also add `instrument_type` to the pseudo-transaction dict (in the `pseudo_transactions.append()` block) so the injection logic can filter futures:

```python
pseudo_transactions.append(
    {
        "type": "SHORT" if direction == "SHORT" else "BUY",
        "symbol": ticker,
        "date": date,
        "quantity": quantity,
        "price": price,
        "fee": 0.0,
        "currency": currency,
        "source": "synthetic_cash_event",
        "instrument_type": str(entry.get("instrument_type") or "equity"),  # NEW
    }
)
```

#### Change 2: Identify fully-synthetic keys and inject flows

After `_create_synthetic_cash_events()` returns (search: `synthetic_cash_events, synth_cash_warnings`), selectively inject synthetic cash events into `external_flows` for fully-synthetic keys.

**Step 2a: Get `opening_qty` from `build_position_timeline()`**

`opening_qty` (search: `opening_qty: Dict`) already tracks real opening quantities per key inside `build_position_timeline()`. Add it to the return tuple:

```python
# Current return (search: "return dict(position_events), synthetic_positions"):
return dict(position_events), synthetic_positions, synthetic_entries, instrument_meta, warnings
# New return:
return dict(position_events), synthetic_positions, synthetic_entries, instrument_meta, warnings, opening_qty
```

All call sites that destructure this return must be updated:

Production code (search: `build_position_timeline(` in `core/realized_performance_analysis.py`):
- Primary call (search: `position_timeline, synthetic_positions, synthetic_entries, instrument_meta, timeline_warnings = build_position_timeline(`) — add `opening_qty`
- Observed-only call (search: `observed_position_timeline, _, _, _, _ = build_position_timeline(`) — add `_` placeholder

Tests — find ALL sites with grep, do NOT rely on line numbers (they shift):

The safest approach is **compile-then-fix**: after adding `opening_qty` to the return tuple, run `pytest tests/ -x`. Every `ValueError: not enough values to unpack` or `too many values to unpack` error points to a missed site. Fix all before proceeding.

To proactively find sites beforehand:
```bash
# All references (direct calls + monkeypatches, even multi-line):
grep -rn 'build_position_timeline' tests/

# All 5-element tuple literals that look like return values (may span lines):
grep -rn 'instrument_type.*\], \[\]' tests/
grep -rn 'position_events.*\[\].*\[\].*{}.*\[\]' tests/
```

But the compile-then-fix loop is the authoritative method — grep may miss edge cases.

Known test files requiring arity updates:
- `tests/core/test_realized_performance_analysis.py` — many sites (direct calls + monkeypatches)
- `tests/core/test_realized_performance_bond_pricing.py` — monkeypatched lambda
- `tests/core/test_symbol_filtering.py` — direct calls
- `tests/diagnostics/diagnose_realized.py` — direct call

**Implementation rule**: After adding `opening_qty` to the return, run `pytest tests/ -x` immediately. Any `ValueError: not enough values to unpack` errors identify missed sites. Fix all before proceeding to subsequent changes.

**Step 2b: Build fully-synthetic key set and inject flows**

```python
# After _create_synthetic_cash_events() and before _compose_cash_and_external_flows():

# Identify fully-synthetic keys: keys with zero real opening transactions.
# opening_qty uses the same direction-aware key mapping as build_position_timeline:
#   BUY → (symbol, currency, "LONG"), SHORT → (symbol, currency, "SHORT")
fully_synthetic_keys: Set[Tuple[str, str, str]] = set()
for entry in synthetic_entries:
    ticker = str(entry.get("ticker") or "")
    currency = str(entry.get("currency") or "USD").upper()
    direction = str(entry.get("direction") or "LONG").upper()
    key = (ticker, currency, direction)
    if opening_qty.get(key, 0.0) < 1e-9:
        fully_synthetic_keys.add(key)

# Build synthetic external flows for fully-synthetic keys only.
# These seed the Modified Dietz denominator with broker cost basis so month 1
# captures the cost-basis-to-market gap instead of returning 0%.
synthetic_inception_flows: List[Tuple[datetime, float]] = []
synthetic_inception_nav = 0.0
for sce in synthetic_cash_events:
    sce_ticker = str(sce.get("symbol") or "")
    sce_currency = str(sce.get("currency") or "USD").upper()
    sce_direction = "SHORT" if str(sce.get("type","")).upper() == "SHORT" else "LONG"
    sce_key = (sce_ticker, sce_currency, sce_direction)

    if sce_key not in fully_synthetic_keys:
        continue  # Partially covered — don't inject (would double-count real BUYs)

    # Guard: skip futures synthetics. Cash replay already uses fee-only policy for
    # futures (fee-only cash policy). Injecting futures notional as external flow would regress.
    sce_instrument_type = str(sce.get("instrument_type") or "equity").lower()
    if sce_instrument_type == "futures":
        continue

    sce_qty = abs(_as_float(sce.get("quantity"), 0.0))
    sce_price = _as_float(sce.get("price"), 0.0)  # Now broker cost basis (from Change 1)
    sce_date = _to_datetime(sce.get("date"))
    if sce_price <= 0 or sce_qty <= 0 or sce_date is None:
        continue

    # Convert to USD for external flow.
    # SHORT positions: NAV uses sign = -1.0, so the SHORT position
    # has negative NAV contribution. However, the external flow must be POSITIVE
    # because it represents capital deployed (short sale proceeds received).
    # The compute_monthly_returns() V_start=0 branch uses:
    #   denom = flow_net; if denom <= 0: return 0.0
    # So a negative flow would be clamped to 0% — wrong.
    #
    # For SHORT synthetics, the flow represents the cash received from the short
    # sale, which is positive capital. The NAV will be negative (short liability),
    # so month 1: return = (V_end_negative - flow_positive) / flow_positive < 0
    # This correctly shows the cost of the short position.
    #
    # Actually, SHORT synthetic positions are extremely rare in this codebase
    # (Schwab/Plaid positions are all LONG). For safety, skip SHORT synthetics
    # from flow injection — they require careful sign analysis and the V_start=0
    # branch doesn't handle negative NAV + positive flow well (return would be
    # artificially negative). This is a known limitation.
    if sce_direction == "SHORT":
        continue  # Skip SHORT — V_start=0 branch can't handle negative NAV + positive flow

    sce_fx = _event_fx_rate(sce_currency, sce_date, fx_cache) if sce_currency != "USD" else 1.0
    flow_usd = sce_qty * sce_price * sce_fx  # Always positive for LONG

    # Flow date: use the synthetic entry's own date + 1s (sce_date is inception - 1s
    # or per-symbol inception - 1s, depending on use_per_symbol_inception).
    # Adding 1s back recovers the original inception/symbol-inception date.
    # This respects per-symbol inception (Schwab Fix F) — each symbol's flow
    # lands at its own inception, not the global one.
    # Month boundary guard: compute_monthly_external_flows() maps flows to
    # month_ends via month-end bucketing, so the exact date within the month
    # only affects Modified Dietz time-weighting (day_weight = days_remaining / total_days).
    flow_date = sce_date + timedelta(seconds=1)  # recover inception date from -1s offset
    synthetic_inception_flows.append((flow_date, flow_usd))
    synthetic_inception_nav += abs(flow_usd)

if synthetic_inception_flows:
    warnings.append(
        f"Injected {len(synthetic_inception_flows)} synthetic flow(s) totaling "
        f"${synthetic_inception_nav:,.2f} into external flows for fully-synthetic positions. "
        "Uses broker cost basis to seed Modified Dietz denominator."
    )
elif synthetic_cash_events:
    warnings.append(
        f"Detected {len(synthetic_cash_events)} synthetic position(s) but no flows injected "
        "(reasons: partial real openings, futures exclusion, SHORT exclusion, or invalid price/date)."
    )
```

**Step 2c: Inject into external_flows after `_compose_cash_and_external_flows()` returns**

```python
# After _compose_cash_and_external_flows() returns external_flows,
# before compute_monthly_external_flows() consumes it:
if synthetic_inception_flows:
    # Guard: synthetic inception flows are only for fully-synthetic keys (zero real
    # openings), so they cannot overlap with provider-authoritative external flows
    # (which track real deposits/withdrawals/transfers). The fully_synthetic_keys
    # filter in Step 2b ensures no key with any real opening gets injected.
    # Provider flows cover real capital movements; synthetic flows cover positions
    # that existed before transaction history began. These are disjoint by definition.
    external_flows.extend(synthetic_inception_flows)
```

**Important**: The observed-only track should NOT get these injected flows. It uses its own `observed_external_flows` from a separate `derive_cash_and_external_flows()` call. No change needed there.

#### Change 3: Update warning text (search: `if synthetic_cash_events:`)

Replace the existing warning block (the `if synthetic_cash_events:` block that emits "Detected N synthetic position(s) with estimated cash impact...") with the injection/no-injection warnings from Step 2b above. The Step 2b `if/elif` block is the SOLE warning logic for synthetic cash events — do NOT keep the old warning alongside it. Delete the old block and let the Step 2b block (which runs after injection logic) handle all cases:
- `if synthetic_inception_flows:` → "Injected N flows totaling $X..."
- `elif synthetic_cash_events:` → "Detected N positions but no flows injected (reasons: ...)"
- (implicitly: if no synthetic_cash_events at all, no warning needed)

#### Change 4: Add diagnostic metadata (in the `realized_metadata` dict construction)

```python
"synthetic_inception_flow_usd": round(synthetic_inception_nav, 2),
"synthetic_fully_synthetic_keys": sorted(
    f"{t}:{c}:{d}" for t, c, d in fully_synthetic_keys
),
```

Also update `RealizedMetadata` in `core/result_objects/realized_performance.py`:
- Field: `synthetic_inception_flow_usd: float` (after `synthetic_current_market_value`, line ~115)
- Field: `synthetic_fully_synthetic_keys: List[str]` (list of `"ticker:currency:direction"` strings)
- `to_dict()`: add serialization for both fields
- `from_dict()`: add deserialization with defaults (0.0 for float, [] for list)
- Agent snapshot builder (line ~595): include in data_quality section

#### Change 5: Handle new metadata fields in per-account aggregation (search: `realized_metadata = dict(first_meta)`)

In `_aggregate_per_account_results()`, the `realized_metadata` dict is built by merging
per-account metadata. New fields need explicit aggregation logic:

```python
# After existing _sum_field entries (near synthetic_current_market_value):
"synthetic_inception_flow_usd": round(_sum_field("synthetic_inception_flow_usd"), 2),
"synthetic_fully_synthetic_keys": sorted(set(
    key
    for meta in meta_dicts
    for key in (meta.get("synthetic_fully_synthetic_keys") or [])
)),
```

`synthetic_inception_flow_usd` is summed across accounts (total capital injected).
`synthetic_fully_synthetic_keys` is unioned (unique keys across all accounts).

---

## Why This Works

### Before (current behavior)
- `compute_monthly_nav()` values ALL positions at FMP month-end prices (correct)
- Synthetic cash events excluded from replay (P2A fix)
- Modified Dietz denominator has zero capital for synthetic positions
- Month 1: V_start=0, V_end=$38K (FMP), flows=0 → return = 0% (zero denom special case)
- Month 2+: returns = FMP monthly changes on uncapitalized base → phantom returns

### After (broker cost basis flow injection)
- `compute_monthly_nav()` unchanged — still uses FMP month-end prices (correct)
- Synthetic cash events for fully-synthetic keys injected into external_flows at **broker cost basis**
- Modified Dietz denominator properly capitalized

### Month-by-month (Schwab)

**Month 1 (Apr 2024)**: V_start=0, synthetic flow injected
- `V_end = $38,269` (FMP month-end prices)
- `flow_net = $44,933` (broker cost basis)
- `return = (38,269 - 44,933) / 44,933 = -14.8%`
- This correctly captures: "we paid $45K, it's now worth $38K at FMP prices"

**Month 2-9 (May-Dec 2024)**: Normal FMP repricing
- `V_start = prev_nav (FMP)`, `V_end = FMP month-end`, `flows = 0`
- Returns track actual monthly FMP price movements
- These are real market returns on properly capitalized positions

**Contribution month (Jan 2025)**: $65K injected
- `V_start = ~$21K` (synthetic FMP value at Dec 2024)
- `V_end = ~$86K` (synthetic + real)
- `flow_net = ~$65K`
- Return reflects real position changes only (synthetic NAV tracked by FMP as usual)

### Expected GoD calculation

```
Old:  1.000 × [months 2-9 compound] × [post-contrib] = 1.315 → +31.5%
New:  0.852 × [months 2-9 compound] × [post-contrib] = ~1.12 → ~+12%
```

Month 1 was previously 0% (GoD factor = 1.000). Now it's -14.8% (GoD factor = 0.852). Months 2+ are unchanged. The 0.852 factor propagates through the entire chain, reducing total from +33% to ~+12%.

Note: the V_start=0 branch uses `flow_net` as denominator, not `flow_weighted`. Since the flow lands on the inception date, `flow_weighted` gets a partial-month weight. But this only matters for the normal branch; the V_start=0 branch uses `flow_net` directly, so the weighting is irrelevant for month 1.

---

## Expected Impact

| Source | Before | After (estimated) | Broker Actual |
|--------|--------|-------------------|---------------|
| Schwab | +23.13% | ~+10-12% | -8.29% |
| IBKR | +15.27% | ~0-5% (24 synthetic entries get flow injection, March +308% should collapse) | -9.35% |
| Plaid | -12.93% | -12.93% (observed-only track, no synthetic flow injection) | -12.49% |
| Combined | +34.41% | ~+5-15% | -8 to -12% |

Note: IBKR impact is larger than originally estimated. The +308% March return is caused by
V_start=0 with $142K NAV and $0 flows. Injecting ~$142K of synthetic flows (24 entries × cost basis)
at inception should collapse March to near-zero, bringing the total close to the sum of Apr-Feb returns.

### Remaining gap (~20pp for Schwab)

After this fix, the remaining gap comes from:
- FMP month-end prices ≠ broker month-end prices (FMP is close prices, broker uses different valuation)
- `_synthetic_price_hint_from_position()` returns 0.0 for non-USD positions (`if ccy == "USD"` guard) — non-USD synthetics would still use FMP fallback
- Dividends, fees, corporate actions not captured in synthetic reconstruction
- Positions purchased at different times than inception date

## Known Limitations

### SHORT synthetic positions excluded from injection

SHORT synthetic positions are skipped from flow injection. The `compute_monthly_returns()` V_start=0 branch uses `flow_net` as denominator and clamps to 0% when `flow_net <= 0`. SHORT positions have negative NAV but the flow (cash from short sale) is positive — the math works but produces artificially large negative returns because `V_end` is negative and `flow_net` is positive. This edge case requires separate handling of the V_start=0 branch for SHORT-only portfolios. All 6 Schwab synthetic positions are LONG, so this doesn't affect the primary target.

### price_hint may be mark-to-market, not cost basis

`_synthetic_price_hint_from_position()` prefers `cost_basis / qty` but falls back to `value / qty` (current market value) when cost_basis is unavailable. With the priority flip, this means some positions may get mark-to-market as the "cost basis" flow. This is less accurate but still better than FMP inception price (which has a different date/source). The flow injection is conservative: if mark-to-market ≈ FMP price, month 1 return ≈ 0% (same as old behavior). If mark-to-market differs significantly, it captures a real gap.

### Non-USD synthetic positions get FMP fallback, not broker cost basis

`_synthetic_price_hint_from_position()` only returns cost_basis for USD positions (`if ccy == "USD"` guard). Non-USD positions return 0.0, falling back to FMP inception price. This is a pre-existing limitation — the `cost_basis` and `value` fields from brokers are USD-denominated, and dividing by qty would give a USD-per-share price, not local-currency-per-share. A future fix could use FX conversion, but all 6 Schwab synthetic positions are USD, so this doesn't affect the primary target.

### Multiple synthetic entries per key

When multiple `synthetic_cash_events` exist for the same fully-synthetic key, all are injected as separate flows. This is correct — each represents a distinct synthetic lot.

### Partially-covered keys excluded from injection

Keys with any real opening transactions (`opening_qty[key] > 0`) are excluded from flow injection. This avoids double-counting real BUY cash that's already in the replay. The trade-off: partially-covered synthetic lots don't get denominator seeding. This is conservative and correct — partial coverage means some real capital exists in the replay.

## Acceptance Gates

- Schwab gap ≤ 21pp (from 41pp)
- IBKR no regression > 5pp
- Plaid no regression > 5pp
- All existing tests pass

## Tests

### Existing tests

1. **`test_synthetic_positions_with_cash_produce_correct_nav_and_returns`** (search by name):
   Tests raw components without flow injection. Exercises the default path. Passes unchanged.

2. **`test_synthetic_cash_events_excluded_from_cash_replay_no_denominator_inflation`** (search by name):
   Tests cash replay exclusion for partially-covered keys. Still correct — only fully-synthetic keys get injected.

**Test requiring update** (search for CPPMF price assertion): The test for `_create_synthetic_cash_events` with CPPMF asserts `price == 0.51` (price_hint) and warning "Used synthetic price hint". With the priority flip, price_hint is now the PRIMARY source, not a fallback. The price assertion still passes (0.51), but the warning assertion needs updating — no "Used synthetic price hint" warning is emitted when price_hint is the primary path. Either:
- Remove the warning assertion, or
- Update to assert NO "Used synthetic price hint" warning (since it's now the normal path)

### New tests

3. **Cost-basis flow injection produces correct month 1 return**:
   - Fully-synthetic AAPL: broker cost basis $100/share, 10 shares
   - FMP month-end Apr: $90/share
   - Month 1 return = (900 - 1000) / 1000 = -10%
   - Verify this vs old behavior (0% with no injection)

4. **Month 2+ returns track FMP price movements normally**:
   - Same setup as #3
   - FMP month-end: Apr $90, May $95, Jun $100
   - Month 2 return = (950 - 900) / 900 = +5.6%
   - Month 3 return = (1000 - 950) / 950 = +5.3%
   - Verify returns are normal Modified Dietz on FMP prices

5. **Mixed synthetic + real positions**:
   - Fully-synthetic AAPL (broker cost $100) + real GOOG (BUY at $50)
   - AAPL flow injected, GOOG BUY already in cash replay
   - Verify both contribute correctly to Modified Dietz denominator
   - Verify no double-counting

6. **Partially-covered key NOT injected**:
   - Key with real BUY (5 shares) + synthetic fill (5 shares)
   - `opening_qty[key] = 5` → NOT in fully_synthetic_keys
   - Verify synthetic cash event NOT injected into external_flows
   - Verify warning about partial coverage

7. **price_hint preferred over FMP in _create_synthetic_cash_events**:
   - Synthetic entry with price_hint=$100, FMP inception=$90
   - Verify cash event price = $100 (broker cost basis), not $90

8. **price_hint unavailable → FMP fallback**:
   - Synthetic entry with price_hint=0 (no broker cost basis)
   - FMP inception price available at $90
   - Verify cash event uses FMP $90 as fallback

9. **Incomplete trade entries unchanged (still use sell_price)**:
   - `synthetic_incomplete_trade` with price_hint (sell_price) = $110
   - Verify cash event price = $110 (no change from current behavior)

10. **Observed-only track does not receive injected flows**:
    - Run with flow injection for enhanced track
    - Verify observed-only external_flows has no synthetic entries

11. **Direction-collision: LONG synthetic + real SHORT txn**:
    - Synthetic LONG entry for AAPL + real SHORT for AAPL
    - Keys: `("AAPL","USD","LONG")` vs `("AAPL","USD","SHORT")`
    - LONG is fully synthetic → flow injected
    - SHORT has real opening → NOT injected

12. **Metadata: synthetic_inception_flow_usd**:
    - Verify field in `RealizedMetadata.to_dict()` and `from_dict()`
    - Verify value matches sum of injected flows

13. **No injection when no eligible keys**:
    - All synthetic entries have partial real openings, or are futures, or are SHORT
    - Verify `synthetic_inception_flows` is empty
    - Verify warning lists possible reasons (partial openings, futures, SHORT, invalid price)

14. **GoD chain validation (end-to-end)**:
    - 3 months: month 1 all-synthetic, month 2 synthetic only, month 3 real contribution
    - Broker cost basis > FMP inception price (simulating Schwab scenario)
    - Verify GoD reflects month 1 loss, month 2 FMP movement, month 3 contribution
    - Verify total return < old frozen approach and < old no-injection approach

15. **build_position_timeline return arity (backward compat)**:
    - Verify all existing tests pass with 6-tuple return
    - Verify opening_qty dict has correct values for known test fixtures

16. **SHORT synthetic excluded from injection**:
    - Fully-synthetic SHORT position (e.g., short AAPL 10 shares)
    - Verify NOT injected into external_flows (SHORT exclusion)
    - Verify month 1 return = 0% (V_start=0, flow_net=0, zero denom special case)

17. **Per-symbol inception flow date alignment**:
    - Two synthetic entries: AAPL with per-symbol inception 2024-07-15, GOOG with global inception 2024-05-01
    - `use_per_symbol_inception=True`
    - Verify AAPL flow date = 2024-07-15 (not global inception)
    - Verify GOOG flow date = 2024-05-01 (falls back to global for symbols with no txn history)
    - Verify each flow lands in correct month bucket

18. **Futures synthetic excluded from injection**:
    - Fully-synthetic futures position (instrument_type="futures")
    - Verify NOT injected into external_flows (futures use fee-only cash policy)
    - Verify no regression on futures notional suppression

19. **Provider-authoritative flows + synthetic injection coexistence**:
    - Account with both provider-authoritative external flows and fully-synthetic positions
    - Verify both are present in external_flows (no mutual exclusion)
    - Verify no double-counting (synthetic flows are for keys with zero real openings)

20. **Non-USD synthetic with FMP fallback (no price_hint)**:
    - Non-USD synthetic position (price_hint = 0.0 from `if ccy == "USD"` guard)
    - Verify FMP inception price used as fallback for cash event
    - Verify flow injection uses FMP price × FX at inception

21. **Aggregation metadata: synthetic_inception_flow_usd summed across accounts**:
    - Two accounts: account A injects $10K, account B injects $5K
    - Verify aggregated `synthetic_inception_flow_usd` = $15K (sum, not first-account)
    - Verify `synthetic_fully_synthetic_keys` is union of both accounts' keys (no duplicates)

22. **Per-symbol inception: flow date respects symbol_inception - 1s + 1s recovery**:
    - Symbol with `use_per_symbol_inception=True` and earliest_txn = 2024-08-15
    - synthetic_date = 2024-08-14T23:59:59, flow_date = 2024-08-15T00:00:00
    - Verify flow lands in August bucket, not July

## Verification

```bash
pytest tests/ -x --timeout=120

python3 -c "
from mcp_tools.performance import get_performance
for inst in [None, 'charles_schwab', 'interactive_brokers']:
    label = inst or 'combined'
    r = get_performance(mode='realized', institution=inst, format='agent')
    s = r['snapshot']
    print(f'{label}: {s[\"returns\"][\"total_return_pct\"]}%')
"

# Check diagnostic metadata
python3 -c "
from mcp_tools.performance import get_performance
r = get_performance(mode='realized', institution='charles_schwab', format='full')
meta = r['realized_metadata']
print(f'synthetic_inception_flow_usd: {meta.get(\"synthetic_inception_flow_usd\")}')
print(f'fully_synthetic_keys: {meta.get(\"synthetic_fully_synthetic_keys\")}')
"
```

## Files to Modify

| File | Change |
|------|--------|
| `core/realized_performance_analysis.py` | Flip price priority in `_create_synthetic_cash_events()`, add `opening_qty` to `build_position_timeline()` return, inject flows for fully-synthetic keys, update warnings, add metadata, aggregation merge |
| `core/result_objects/realized_performance.py` | Add `synthetic_inception_flow_usd` + `synthetic_fully_synthetic_keys` to dataclass + serialization |
| `tests/core/test_realized_performance_analysis.py` | Update return arity, add new tests (22 total) |
| `tests/core/test_realized_performance_bond_pricing.py` | Update monkeypatched `build_position_timeline` return arity |
| `tests/core/test_symbol_filtering.py` | Update return arity (3 sites) |
| `tests/diagnostics/diagnose_realized.py` | Update return arity (1 site) |

## Key Search Patterns

Use these `grep -n` patterns to locate each edit target in `core/realized_performance_analysis.py`:

| What | Search pattern |
|------|---------------|
| `_create_synthetic_cash_events()` def | `def _create_synthetic_cash_events` |
| `_synthetic_price_hint_from_position()` | `def _synthetic_price_hint_from_position` |
| `opening_qty` dict init | `opening_qty: Dict` |
| `opening_qty` population | `opening_qty[key] +=` |
| `build_position_timeline()` return | `return dict(position_events), synthetic_positions` |
| `build_position_timeline()` primary call | `position_timeline, synthetic_positions, synthetic_entries, instrument_meta, timeline_warnings = build_position_timeline(` |
| `build_position_timeline()` observed-only call | `observed_position_timeline, _, _, _, _ = build_position_timeline(` |
| `_create_synthetic_cash_events()` call | `synthetic_cash_events, synth_cash_warnings = _create_synthetic_cash_events(` |
| Synthetic cash warning (to replace) | `if synthetic_cash_events:` (the warning block, NOT the metadata block) |
| `transactions_for_cash` assignment | `transactions_for_cash = fifo_transactions` |
| `_compose_cash_and_external_flows()` def | `def _compose_cash_and_external_flows(` |
| `compute_monthly_nav()` enhanced call | `monthly_nav = compute_monthly_nav(` |
| `compute_monthly_nav()` observed-only call | `observed_monthly_nav = compute_monthly_nav(` |
| `compute_monthly_returns()` V_start=0 branch | `if abs(v_start) < 1e-12:` |
| Aggregation metadata merge | `realized_metadata = dict(first_meta)` |
| `RealizedMetadata` dataclass | `class RealizedMetadata` in `core/result_objects/realized_performance.py` |

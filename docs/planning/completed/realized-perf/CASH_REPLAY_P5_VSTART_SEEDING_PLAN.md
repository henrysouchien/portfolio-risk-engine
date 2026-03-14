# P5 Fix: V_start Seeding for Synthetic Positions + Incomplete Trade Cash Suppression

## Sequencing Note (2026-02-27, updated)

This document captures **Phase 5** of the cash replay hardening series.
Prior phases (all implemented):
- **P1** (`efd8f1a6`): UNKNOWN/fx_artifact filtering + futures inference gating
- **P2A** (`eb9fc423`): Synthetic cash events excluded from replay + sensitivity gate diagnostic-only
- **P2B** (`1d943108`): Futures fee-only cash replay + income/provider overlap dedup
- **P3** (`0e533cb7`): Global inception for synthetics + futures incomplete trade filter
- **P3.1** (`6c2f6e89`): Futures compensating events + incomplete trade synthetics at inception
- **P3.2** (`ab0b137b`): Schwab cross-source attribution fix (native-over-aggregator tiebreaker)

**Current state (post-P3.2):** IBKR +10.45% (actual -9.35%), Schwab +33.13% (actual -8.29%), Plaid -7.96% (actual -12.49%).

P3.1 implemented compensating events for futures and incomplete trade synthetic placement at inception, which was one of the approaches considered in P4. P5 adds two orthogonal fixes on top: (1) V_start seeding so synthetic position capital anchors the Modified Dietz denominator, and (2) budget-based incomplete trade cash suppression to handle remaining unbalanced SELL cash in the replay.

## Problem

After P1-P3, two related distortions remain. Both stem from the same root cause: **positions exist in NAV but their capital is absent from the Modified Dietz calculation**.

### Distortion 1: Synthetic positions produce free appreciation (Schwab +33.13% vs actual -8.29%)

P2 correctly removed synthetic cash events from the cash replay to prevent fake contribution inference. But the position timeline still includes synthetic positions, and `compute_monthly_nav()` values them at actual market prices each month-end. Since no cost basis was deducted from cash, any position appreciation appears as pure gain on zero invested capital.

**Code path (verified):**
1. `build_position_timeline()` line 1244: synthetic positions added at `inception_date - 1s`
2. `compute_monthly_nav()` line 1803: values all positions at market price (including synthetics)
3. Line 3469: `transactions_for_cash = fifo_transactions` — synthetic cash events NOT included
4. `compute_monthly_returns()` line 1857: `prev_nav = 0.0` — first month V_start is always zero
5. Line 1860: `v_start = prev_nav if i > 0 else 0.0` — month 1 is hardcoded to zero regardless of `prev_nav`
6. Line 1883: `prev_nav = v_end` — from month 2 onward, V_start includes synthetic position value for free

**Effect:** Post-P3.2, Schwab synthetics (CPPMF, DSU, GLBE, LIFFF, MSCI, PCTY, STWD) are now in scope (P3.2 added DSU/MSCI/STWD via native-over-aggregator tiebreaker). These positions appreciate over 21 months against zero invested capital → phantom +33% return.

### Distortion 2: Incomplete trade SELLs inject unbalanced cash (IBKR +10.45% vs actual -9.35%)

When FIFO encounters a SELL with no prior BUY in the lookback window, the SELL enters the cash replay at full notional value. No budget-based suppression currently exists — `derive_cash_and_external_flows()` (line 1448) has no `incomplete_qty_budget` parameter. For futures incomplete trades, P3 removed them from the position timeline (lines 1298-1308) — so their SELL adds cash but no position offsets it.

**Code path (verified):**
1. `derive_cash_and_external_flows()` (line 1448): no incomplete trade suppression parameter or logic exists
2. `transactions_for_cash = fifo_transactions` (line 3469): all FIFO transactions including incomplete SELLs enter cash replay
3. `build_position_timeline()` lines 1298-1308: P3 filters futures incomplete trades from timeline
4. Incomplete SELL cash enters replay → inflates cash balance → distorts NAV and flows
5. NAV goes negative → V_adjusted <= 0 → returns clamped to -100%

**Effect:** 16 IBKR incomplete trades inject unbalanced cash. NAV goes negative by May 2025. 8 months have V_adjusted <= 0.

### Common root cause

Both distortions are amplified because `compute_monthly_returns()` starts with `prev_nav = 0.0` AND the month-1 logic hardcodes `v_start = 0.0`. The portfolio doesn't start at zero — it has pre-existing positions. Without proper V_start, any position value in the first month is either free gain (Distortion 1) or unanchored (Distortion 2).

## Fix: Two Changes

### Change 1: Seed V_start with initial NAV at inception

Instead of `prev_nav = 0.0` with month-1 hardcoded to zero, compute the portfolio's actual NAV at inception and use it as the starting value for ALL months including month 1.

**What to compute:** Sum position values at inception for positions that exist in the timeline at `inception_date - 1s` — i.e., only synthetic positions placed at `inception_date - 1 second`. Use market prices at inception from `price_cache`, not brokerage cost basis.

**Why `inception_date - 1s` (not `inception_date`):** Synthetic positions are placed at `inception_date - timedelta(seconds=1)`. Real first-day transactions occur at `inception_date` or later. By computing NAV at `inception_date - 1s`, we capture only pre-existing synthetic positions and exclude any real trades that happen on inception day. This prevents look-ahead contamination from first-day transactions.

**Why market price at inception, not cost basis:** If we used cost basis for V_start but market price for V_end, the first month would capture the entire unrealized gain from *before* our observation window. That's historical performance, not the period we're measuring. Market price at inception makes V_start consistent with the NAV valuation methodology.

**Price availability:** `price_cache` is fetched starting `inception_date - 62 days` (line 3268), so prices at inception are available. `_value_at_or_before()` (line 172) looks backward first, then falls forward to the next available price only if no prior price exists. For the inception date (which has a 62-day backward buffer), backward lookup should succeed for all symbols with FMP price history.

**Edge case — `_value_at_or_before` forward-fill risk:** If a synthetic position has no price history before inception (e.g., a newly listed stock), `_value_at_or_before` falls forward to the next available price (line 176-178). This could introduce minor look-ahead bias in V_start. Mitigation: this is rare and the impact is bounded — it only affects the first stub month's return, and the forward-filled price will be close to the true inception price for any recently-listed stock.

**Implementation:**

File: `core/realized_performance_analysis.py`

#### Change 1a: Add `compute_nav_at_date()` helper (new function, near `compute_monthly_nav`)

```python
def compute_nav_at_date(
    position_timeline: Dict[Tuple[str, str, str], List[Tuple[datetime, float]]],
    target_date: datetime,
    price_cache: Dict[str, pd.Series],
    fx_cache: Dict[str, pd.Series],
    cash_value: float = 0.0,
) -> float:
    """Compute NAV at a specific date using position timeline and price data.

    Used to seed V_start for Modified Dietz with the portfolio's actual value
    at inception, so synthetic positions are treated as pre-existing capital
    rather than free gains.

    Only includes position events at or before ``target_date``.  Callers
    should pass ``inception_date - timedelta(seconds=1)`` to capture only
    synthetic pre-existing positions and exclude first-day real trades.
    """
    target = pd.Timestamp(target_date).to_pydatetime().replace(tzinfo=None)
    position_value = 0.0

    for key, events in position_timeline.items():
        qty = 0.0
        for event_date, event_qty in sorted(events, key=lambda x: x[0]):
            event_dt = pd.Timestamp(event_date).to_pydatetime().replace(tzinfo=None)
            if event_dt <= target:
                qty += event_qty
            else:
                break

        if abs(qty) < 1e-9:
            continue

        ticker, currency, direction = key
        price = _value_at_or_before(price_cache.get(ticker), target, default=0.0)
        fx = _event_fx_rate(currency, target, fx_cache)
        sign = -1.0 if direction == "SHORT" else 1.0
        position_value += sign * qty * price * fx

    return position_value + cash_value
```

#### Change 1b: Add `initial_nav` keyword-only parameter to `compute_monthly_returns()` — line 1840

**Before:**
```python
def compute_monthly_returns(
    monthly_nav: pd.Series,
    net_flows: pd.Series,
    time_weighted_flows: pd.Series,
) -> Tuple[pd.Series, List[str]]:
```

**After:**
```python
def compute_monthly_returns(
    monthly_nav: pd.Series,
    net_flows: pd.Series,
    time_weighted_flows: pd.Series,
    *,
    initial_nav: float = 0.0,
) -> Tuple[pd.Series, List[str]]:
```

The `*` makes `initial_nav` keyword-only, preventing accidental positional passing.

**Monkeypatched stub update required:** There are ~16 monkeypatched stubs for `compute_monthly_returns` in `test_realized_performance_analysis.py` (lines 136, 275, 1535, 3547, 3665, 3783, 3962, 4243, 4429, 4560, 4707, 4861, 5177, 6152, 6313, 6545, 6694). Most are 3-arg lambdas like `lambda monthly_nav, net_flows, time_weighted_flows: (...)`. When the enhanced call site passes `initial_nav=value`, Python will raise `TypeError: unexpected keyword argument`.

All stubs must be updated to accept `**kwargs`. For lambda stubs:
```python
lambda monthly_nav, net_flows, time_weighted_flows, **kwargs: (...)
```
For named function stubs (e.g., `_fake_returns` at line 4810):
```python
def _fake_returns(monthly_nav, net_flows, time_weighted_flows, **kwargs):
```
This is a mechanical change — search for all `monkeypatch.setattr(rpa, "compute_monthly_returns", ...)` call sites and update each.

#### Change 1c: Use `initial_nav` for both `prev_nav` AND month-1 `v_start` — lines 1857, 1860

**Before:**
```python
    prev_nav = 0.0                                  # line 1857
    for i, ts in enumerate(nav.index):
        v_end = _as_float(nav.iloc[i], 0.0)
        v_start = prev_nav if i > 0 else 0.0        # line 1860
```

**After:**
```python
    prev_nav = initial_nav                           # line 1857
    for i, ts in enumerate(nav.index):
        v_end = _as_float(nav.iloc[i], 0.0)
        v_start = prev_nav if i > 0 else initial_nav # line 1860
```

This is the key fix that the v1 plan missed: line 1860 hardcodes month 1 to `0.0` regardless of `prev_nav`. Changing both lines ensures `initial_nav` is used for the first month.

#### Change 1d: Compute and pass `initial_nav` at the enhanced call site — near line 3986

After computing `position_timeline`, `price_cache`, `fx_cache`, and before calling `compute_monthly_returns`:

```python
        # Compute initial NAV at inception from pre-existing (synthetic) positions.
        # Use inception_date - 1s to capture only synthetic positions placed before
        # inception and exclude any real first-day transactions.
        _synthetic_cutoff = inception_date - timedelta(seconds=1)
        initial_nav = compute_nav_at_date(
            position_timeline=position_timeline,
            target_date=_synthetic_cutoff,
            price_cache=price_cache,
            fx_cache=fx_cache,
            cash_value=0.0,
        )
        # Count pre-existing positions and detect missing prices.
        _pre_existing_tickers = []
        _missing_price_tickers = []
        for _key, _evts in position_timeline.items():
            if any(
                pd.Timestamp(d).to_pydatetime().replace(tzinfo=None) <= _synthetic_cutoff
                for d, _ in _evts
            ):
                _ticker = _key[0]
                _pre_existing_tickers.append(_ticker)
                _price = _value_at_or_before(price_cache.get(_ticker), _synthetic_cutoff, default=0.0)
                if abs(_price) < 1e-9:
                    _missing_price_tickers.append(_ticker)

        if _missing_price_tickers:
            warnings.append(
                f"V_start seeding: no inception price for {_missing_price_tickers}. "
                f"These positions contribute $0 to initial NAV."
            )
        if initial_nav > 1e-6:
            warnings.append(
                f"V_start seeded with initial NAV at inception: ${initial_nav:,.2f} "
                f"(from {len(_pre_existing_tickers)} pre-existing position(s))."
            )
```

Pass to enhanced return calculation:
```python
        monthly_returns, return_warnings = compute_monthly_returns(
            monthly_nav=monthly_nav,
            net_flows=net_flows,
            time_weighted_flows=tw_flows,
            initial_nav=initial_nav,
        )
```

#### Change 1e: Observed-only branch — no initial_nav change needed (but for nuanced reasons)

The observed-only branch (`observed_position_timeline`, line 4010) uses `current_positions={}`, so it has no current-position synthetics. However, it DOES receive `incomplete_trades` (line 4014), and `build_position_timeline()` creates synthetic starts for non-futures incomplete exits (lines 1261-1307). So observed-only CAN have synthetic timeline entries from incomplete trades.

Despite this, no `initial_nav` change is needed for the observed branch because:
1. The observed branch does NOT call `compute_monthly_returns()` — it only computes NAV endpoints for `nav_pnl_observed_only_usd`.
2. Incomplete-trade synthetic entries are placed at `inception_date - 1s` (line 1278), same as current-position synthetics. However, the observed branch passes `current_positions={}`, so these only exist for incomplete trades — and the branch doesn't call `compute_monthly_returns()` anyway. They appear mid-timeline when their SELL occurs, not at inception. So they don't affect V_start regardless.

If a future refactor adds observed-only monthly returns, it should compute its own `initial_nav` from `observed_position_timeline`. But that's out of scope for P5.

#### Change 1f: Add `initial_nav` to metadata (analysis dict + typed dataclass + snapshot)

**Step 1:** Add to `realized_metadata` dict in `core/realized_performance_analysis.py` (near line 4511):
```python
            "initial_nav": round(initial_nav, 2),
```

**Step 2:** Add field to `RealizedMetadata` dataclass in `core/result_objects/realized_performance.py` (near line 146, alongside `futures_notional_suppressed_usd`):
```python
    initial_nav: float = 0.0
```

**Step 3:** Add to `to_dict()` method (follows pattern of other float fields like `futures_notional_suppressed_usd`):
```python
            "initial_nav": self.initial_nav,
```

**Step 4:** Add to `from_dict()` class method (with default):
```python
            initial_nav=float(d.get("initial_nav", 0.0)),
```

**Step 5:** Add to agent snapshot `data_quality` block (in `get_agent_snapshot()` near line 480, where `meta` is the `RealizedMetadata` instance — follows existing pattern like `meta.futures_notional_suppressed_usd` at line 496):
```python
            "initial_nav": meta.initial_nav,
```

Similarly for the Change 2 diagnostic fields (`incomplete_notional_suppressed_usd`, `incomplete_trade_count`) — add to `RealizedMetadata`, `to_dict()`, `from_dict()`, and agent snapshot. Follow the identical pattern used for `futures_notional_suppressed_usd` / `futures_txn_count_replayed`.

### Change 2: Implement budget-based incomplete trade cash suppression

Currently, `derive_cash_and_external_flows()` (line 1448) has **no** incomplete trade suppression. All SELL/COVER transactions enter cash replay at full notional value, regardless of whether FIFO matched them. This change adds budget-based quantity suppression — a mechanism that suppresses only the unmatched portion of each incomplete trade's cash impact.

**Why budget-based (not whole-transaction filtering):** If a SELL of 100 shares has only 30 shares unmatched (incomplete), we should suppress only 30 shares' worth of cash impact, not the full 100. Budget-based suppression handles partial incompletes correctly.

#### Change 2a: Add `incomplete_qty_budget` parameter to `derive_cash_and_external_flows()`

Add a new keyword-only parameter:
```python
def derive_cash_and_external_flows(
    fifo_transactions: List[Dict[str, Any]],
    income_with_currency: List[Dict[str, Any]],
    fx_cache: Dict[str, pd.Series],
    provider_flow_events: Optional[List[Dict[str, Any]]] = None,
    *,
    disable_inference_when_provider_mode: bool = True,
    force_disable_inference: bool = False,
    warnings: Optional[List[str]] = None,
    replay_diagnostics: Optional[Dict[str, Any]] = None,
    incomplete_qty_budget: Optional[Dict[Tuple[str, datetime, str], float]] = None,  # NEW — 3-tuple key
) -> Tuple[List[Tuple[datetime, float]], List[Tuple[datetime, float]]]:
```

#### Change 2b: Add suppression logic inside cash replay loop

In the non-futures branch (around line 1629-1637), before applying SELL/COVER cash impact, check the budget:
```python
        else:
            # Budget-based incomplete trade suppression.
            # For SELL/COVER, reduce quantity by the unmatched portion
            # tracked in incomplete_qty_budget.
            effective_qty = event["quantity"]
            if incomplete_qty_budget is not None and event_type in ("SELL", "COVER"):
                sym = str(event.get("symbol") or "").strip().upper()
                _dir = "LONG" if event_type == "SELL" else "SHORT"
                budget_key = (sym, event["date"], _dir)
                remaining_budget = incomplete_qty_budget.get(budget_key, 0.0)
                if remaining_budget > 1e-9:
                    suppressed_qty = min(effective_qty, remaining_budget)
                    incomplete_qty_budget[budget_key] = max(0.0, remaining_budget - suppressed_qty)
                    effective_qty -= suppressed_qty
                    incomplete_notional_suppressed_usd += abs(suppressed_qty * event["price"] * fx)

            if event_type == "BUY":
                cash -= (event["price"] * event["quantity"] + event["fee"]) * fx
            elif event_type == "SELL":
                cash += (event["price"] * effective_qty - event["fee"]) * fx
            elif event_type == "SHORT":
                cash += (event["price"] * event["quantity"] - event["fee"]) * fx
            elif event_type == "COVER":
                cash -= (event["price"] * effective_qty + event["fee"]) * fx
            ...
```

Add `incomplete_notional_suppressed_usd` accumulator (alongside existing `futures_notional_suppressed_usd` at line 1602) and surface it in `replay_diagnostics`.

#### Change 2c: Build the budget in the orchestration function

Near line 3469, after FIFO completes, build the budget from `fifo_result.incomplete_trades`.

**Budget key:** `(symbol, sell_date, direction)` — using direction prevents cross-contamination when the same symbol has both a SELL (long exit) and a COVER (short exit) on the same date. `IncompleteTrade` provides `direction` (line 140, "LONG" or "SHORT").

```python
        _incomplete_qty_budget: Dict[Tuple[str, datetime, str], float] = {}
        for _inc in fifo_result.incomplete_trades:
            _inc_sym = str(_inc.symbol).strip().upper()
            _inc_date = _to_datetime(_inc.sell_date)
            _inc_dir = str(_inc.direction or "LONG").upper()
            if _inc_sym and _inc_date is not None:
                _key = (_inc_sym, _inc_date, _inc_dir)
                _incomplete_qty_budget[_key] = (
                    _incomplete_qty_budget.get(_key, 0.0) + abs(_inc.quantity)
                )
        # Save a copy before mutation — observed-only branch needs its own budget.
        _incomplete_qty_budget_original = dict(_incomplete_qty_budget)
        transactions_for_cash = fifo_transactions
```

The suppression logic (Change 2b) must derive direction from `event_type`: SELL → "LONG", COVER → "SHORT":
```python
            if incomplete_qty_budget is not None and event_type in ("SELL", "COVER"):
                _dir = "LONG" if event_type == "SELL" else "SHORT"
                budget_key = (sym, event["date"], _dir)
```

#### Change 2d: Pass budget to all `derive_cash_and_external_flows()` call sites

Pass `incomplete_qty_budget=<budget_dict>` to every `derive_cash_and_external_flows()` call site. There are 9 total:

**8 inside `_compose_cash_and_external_flows()`:**
- Line 3547: non-partitioned path (when `not provider_first_mode`)
- Line 3613: deterministic no-flow authority
- Line 3637: no authoritative events fallback
- Line 3664: authoritative only, no fallback slices
- Line 3757: authoritative only, no fallback activity
- Line 3836: partitioned authoritative
- Line 3844: partitioned out-of-window
- Line 3861: partitioned fallback (per partition)

**1 outside (observed-only branch):**
- Line 4020: observed-only cash replay

**Non-partitioned path** (line 3547): pass a single mutable budget:
```python
        cash_snapshots, external_flows = derive_cash_and_external_flows(
            ...,
            incomplete_qty_budget=_incomplete_qty_budget,  # mutable, consumed
        )
```

**Provider-flow early-return branches** (lines 3613, 3637, 3664, 3757): Only one of these executes per invocation. Each receives a fresh budget copy: `incomplete_qty_budget=dict(_incomplete_qty_budget_original)`.

**Partitioned provider-flow path** (lines 3836, 3844, 3861): Multiple calls process disjoint transaction subsets. Use a **single shared mutable budget** across all partition calls to prevent double suppression:
```python
        _partition_budget = dict(_incomplete_qty_budget_original)
        authoritative_cash, ... = derive_cash_and_external_flows(
            ..., incomplete_qty_budget=_partition_budget,       # line 3836
        )
        out_of_window_cash, ... = derive_cash_and_external_flows(
            ..., incomplete_qty_budget=_partition_budget,       # line 3844 — same dict
        )
        for row in fallback_partitions.values():
            partition_cash, ... = derive_cash_and_external_flows(
                ..., incomplete_qty_budget=_partition_budget,   # line 3861 — same dict
            )
```

#### Change 2e: Observed-only branch gets a fresh budget copy

The observed-only branch (line 4020) runs AFTER the main replay, which mutates and exhausts the budget dict. Passing the same dict would make suppression ineffective.

```python
        # Observed-only: fresh budget copy since main replay already consumed the original.
        _observed_incomplete_budget = dict(_incomplete_qty_budget_original)
        observed_cash_snapshots, observed_external_flows = derive_cash_and_external_flows(
            fifo_transactions=fifo_transactions,
            income_with_currency=income_with_currency,
            fx_cache=fx_cache,
            warnings=warnings,
            incomplete_qty_budget=_observed_incomplete_budget,
        )
```

#### Change 2f: Add diagnostic metadata

Follow the full pipeline of `futures_notional_suppressed_usd`:

**Step 1:** Add accumulator and `replay_diagnostics` defaults in `derive_cash_and_external_flows()` (alongside line 1602):
```python
    incomplete_notional_suppressed_usd = 0.0
    # ... and in replay_diagnostics defaults:
    replay_diagnostics.setdefault("incomplete_notional_suppressed_usd", 0.0)
```

**Step 2:** Surface the accumulator at end of `derive_cash_and_external_flows()` (alongside lines 1704-1707):
```python
    replay_diagnostics["incomplete_notional_suppressed_usd"] = _as_float(
        replay_diagnostics.get("incomplete_notional_suppressed_usd"), 0.0
    ) + incomplete_notional_suppressed_usd
```

**Step 3:** Add to `replay_diag` init dict in `_compose_cash_and_external_flows()` (alongside line 3500):
```python
    "incomplete_notional_suppressed_usd": 0.0,
```

**Step 4:** Add to `_finalize_replay_diag()` (line 3512) — **this is critical** or the field is silently dropped:
```python
    "incomplete_notional_suppressed_usd": round(
        _as_float(replay_diag.get("incomplete_notional_suppressed_usd"), 0.0), 2
    ),
    "incomplete_trade_count": len(fifo_result.incomplete_trades),
```

**Step 5:** Add to `realized_metadata` dict (near line 4511):
```python
            "incomplete_notional_suppressed_usd": round(
                _as_float(cash_replay_diagnostics.get("incomplete_notional_suppressed_usd"), 0.0), 2
            ),
            "incomplete_trade_count": len(fifo_result.incomplete_trades),
```

#### Change 2g: No whole-transaction filtering

Do NOT replace `transactions_for_cash = fifo_transactions` with a filtered list. The budget-based approach is more correct for partial incompletes.

## Why Both Changes Are Needed Together

| Scenario | Change 1 only (V_start seeding) | Change 2 only (budget suppression) | Both |
|---|---|---|---|
| **Schwab synthetics** | Fixed — appreciation measured against starting capital | No effect — no incomplete trades | Fixed |
| **IBKR incomplete equity SELLs** | Partially fixed — V_start anchored, but unbalanced cash still distorts flows | Fixed — SELL cash suppressed proportionally | Fixed |
| **IBKR incomplete futures SELLs** | Partially fixed | Fixed — suppression already handles futures | Fixed |
| **IBKR synthetic current positions** | Fixed — V_start includes their value | No effect — not incomplete trades | Fixed |
| **Zero-synthetic portfolio** | No-op — `initial_nav` = 0.0, same as current behavior | Works as before | No-op — unchanged |

## Tests

### Unit Tests (`tests/core/test_realized_performance_analysis.py`)

#### Test 1: V_start seeded with synthetic position value
```python
def test_initial_nav_seeds_vstart_for_synthetic_positions():
    """V_start should equal synthetic position value at inception, not zero.

    Setup: one synthetic position (AAPL, 10 shares, $200/share at inception).
    No real transactions, no flows.
    Expected: month 1 return ≈ small% (price change inception→month-end),
    not the V_start=0 fallback that produces 0% or extreme values.
    """
```

#### Test 2: V_start=0 warning no longer fires when synthetics exist
```python
def test_no_vstart_zero_warning_when_synthetics_seeded():
    """The 'V_start=0 with no detected inflows' warning should not fire
    when initial_nav is seeded from synthetic positions."""
```

#### Test 3: Zero-synthetic portfolio is no-op
```python
def test_initial_nav_zero_when_no_synthetic_positions():
    """When all positions have opening trades in the window, initial_nav
    should be 0.0 and behavior should be identical to pre-P5."""
```

#### Test 4: First-day real trades excluded from initial_nav
```python
def test_initial_nav_excludes_first_day_real_trades():
    """compute_nav_at_date(inception_date - 1s) should NOT include positions
    from real trades that happen on inception_date itself.

    Setup: synthetic AAPL at inception-1s, real BUY of MSFT at inception.
    Expected: initial_nav includes only AAPL, not MSFT.
    """
```

#### Test 5: compute_nav_at_date correctness
```python
def test_compute_nav_at_date_sums_position_values():
    """compute_nav_at_date should sum qty * price * fx for positions at target date."""
```

#### Test 6: compute_nav_at_date with no positions returns cash_value
```python
def test_compute_nav_at_date_empty_timeline_returns_cash_only():
    """With no positions at target_date, result should equal cash_value."""
```

#### Test 7: Budget-based suppression for incomplete trades
```python
def test_incomplete_trade_budget_suppresses_unmatched_sell_cash():
    """Incomplete trade SELL quantity should be suppressed in cash replay
    via the budget-based approach (not whole-transaction exclusion).

    Setup: SELL 100 shares, 60 unmatched (incomplete). Budget = 60.
    Expected: only 40 shares' cash impact enters replay.
    """
```

#### Test 8: Partial incomplete — only unmatched portion suppressed
```python
def test_partial_incomplete_trade_suppresses_only_unmatched_portion():
    """When a SELL has both matched and unmatched shares, only the
    unmatched portion is suppressed.

    Setup: BUY 40 then SELL 100 of same stock. Incomplete qty = 60.
    Expected: BUY 40 cash deducted fully, SELL only 40 shares' worth of cash added.
    """
```

#### Test 9: No V_adjusted <= 0 cascade
```python
def test_no_v_adjusted_negative_cascade_with_vstart_seeding():
    """With V_start seeded and incomplete exits suppressed, NAV should not
    go persistently negative in a scenario mimicking the IBKR data."""
```

#### Test 10: Keyword-only initial_nav doesn't break existing stubs
```python
def test_compute_monthly_returns_works_without_initial_nav():
    """compute_monthly_returns() should work with only 3 positional args
    (backward compatibility for existing callers and test stubs)."""
    nav = pd.Series([100.0, 110.0], index=pd.DatetimeIndex([...]))
    net = pd.Series([0.0, 0.0], index=nav.index)
    tw = pd.Series([0.0, 0.0], index=nav.index)
    returns, warnings = rpa.compute_monthly_returns(nav, net, tw)
    # Should work — initial_nav defaults to 0.0
    assert len(returns) == 2
```

#### Test 11a: Missing inception price falls back gracefully (unit level)
```python
def test_compute_nav_at_date_missing_price_uses_zero():
    """If price_cache has no data for a ticker at target_date,
    _value_at_or_before returns 0.0 and position contributes $0 to NAV.
    This is safe — the position just doesn't anchor V_start."""
```

#### Test 11b: All prices missing — full path warning + deterministic fallback
```python
def test_all_synthetic_prices_missing_emits_warning_and_falls_back():
    """When ALL synthetic positions have no price data at inception,
    initial_nav falls back to 0.0 (same as pre-P5 behavior).
    A warning listing the missing-price tickers must be emitted.
    Returns should be deterministic and identical to pre-P5 zero-start behavior.

    Setup: 2 synthetic positions with empty price_cache entries.
    Expected: initial_nav == 0.0, warning contains both ticker names,
    monthly returns match the zero-start baseline.
    """
```

#### Test 12: Observed-only branch suppresses incomplete exits after main replay consumed budget
```python
def test_observed_only_branch_suppresses_incomplete_sells_after_main_replay():
    """The observed-only cash replay must receive a FRESH copy of incomplete_qty_budget
    (not the dict already consumed by the main replay).

    This exercises the real failure mode: main replay mutates budget dict to zero,
    then observed-only branch needs its own unconsumed copy.

    Setup: one incomplete SELL (100 shares, fully unmatched) in fifo_transactions.
    Step 1: Run main derive_cash_and_external_flows() with the original budget → budget consumed.
    Step 2: Run observed-only derive_cash_and_external_flows() with a fresh copy of the budget.
    Expected: observed-only SELL cash impact is fully suppressed (not leaked due to exhausted budget).
    Verify: passing the SAME (consumed) budget dict to step 2 would FAIL suppression.
    """
```

#### Test 13: Direction-partitioned budget prevents SELL/COVER cross-contamination
```python
def test_budget_direction_prevents_sell_cover_cross_contamination():
    """When the same symbol has both a SELL (long exit) and a COVER (short exit)
    on the same date, the budget should suppress each independently.

    Setup: AAPL incomplete SELL 50 (LONG) + AAPL incomplete COVER 30 (SHORT) on same date.
    Expected: SELL suppresses 50 shares' cash, COVER suppresses 30 shares' cash.
    Neither leaks into the other's budget.
    """
```

#### Test 14: Shared mutable budget across partitioned replay prevents double suppression
```python
def test_shared_budget_across_partitions_no_double_suppression():
    """When provider-flow mode partitions transactions into authoritative/fallback
    branches, the same incomplete SELL must only be suppressed once (in whichever
    partition it lands in).

    Setup: one incomplete SELL, transactions split across two partitions.
    Pass the same budget dict to both derive_cash_and_external_flows() calls.
    Expected: total suppressed = SELL qty (not 2x).
    """
```

#### Test 15: No call site passes initial_nav positionally
```python
def test_no_positional_initial_nav_in_codebase():
    """Grep the codebase to ensure no call site passes initial_nav as a
    positional 4th argument to compute_monthly_returns().

    Implementation: use ast.parse or a simple regex scan on
    core/realized_performance_analysis.py to verify all calls use either
    3 positional args or explicit initial_nav=... keyword syntax.
    Alternatively, assert via inspect that initial_nav is keyword-only.
    """
    import inspect
    sig = inspect.signature(rpa.compute_monthly_returns)
    param = sig.parameters["initial_nav"]
    assert param.kind == inspect.Parameter.KEYWORD_ONLY
```

### Contract Tests

#### `tests/core/test_performance_flags.py`
- Existing reliability warning tests should continue passing.
- No new flags introduced — V_start seeding is transparent to the flag layer.

#### `tests/mcp_tools/test_performance.py`
- Assert `initial_nav` present in full output metadata.
- Assert `incomplete_notional_suppressed_usd` and `incomplete_trade_count` present in full output metadata.

#### `tests/core/test_result_objects.py` (or inline)
- Assert `RealizedMetadata` round-trips `initial_nav`, `incomplete_notional_suppressed_usd`, `incomplete_trade_count` through `to_dict()` / `from_dict()`.
- Assert agent snapshot `data_quality` block includes the new fields.

## Expected Impact

| Source | Post-P3.2 (current) | Expected Post-P5 | Broker Actual |
|--------|---------------------|-------------------|---------------|
| **IBKR** | +10.45% | Closer to -9.35% | -9.35% |
| **Schwab** | +33.13% | Significantly lower (closer to -8%) | -8.29% |
| **Plaid** | -7.96% | ~Unchanged | -12.49% |
| **Combined** | +34.66% | Closer to -8 to -12% | -8 to -12% |

**IBKR**: P3.1 already fixed the -100% collapse via compensating events and inception placement. Remaining +10% vs -9% gap (~20pp) comes from: (1) budget-based suppression of remaining unbalanced incomplete trade SELL cash, (2) V_start seeding to anchor NAV denominator for synthetic positions.

**Schwab**: Primarily V_start seeding. After P3.2 included DSU/MSCI/STWD, the synthetics (CPPMF, DSU, GLBE, LIFFF, MSCI, PCTY, STWD) still enter at inception with current price_hint against V_start=0. V_start seeding will anchor the denominator at synthetic position market value at inception.

**Plaid**: Minimal change. Only 1 synthetic position after source scoping.

**Combined**: Improves as IBKR and Schwab improve. Currently dragged up by Schwab's +33%.

## Acceptance Gate

1. IBKR absolute error improves by >= 10pp (from 20pp gap to <= 10pp gap).
2. Schwab absolute error improves by >= 20pp (from 41pp gap to <= 21pp gap).
3. No source regresses by > 5pp.
4. Zero `V_adjusted<=0` warnings for IBKR in the common case.
5. Zero `V_start=0` warnings when synthetic positions exist at inception.
6. When ALL synthetic position prices are missing at inception (`_value_at_or_before` returns 0.0 for every ticker), `initial_nav` falls back to 0.0 deterministically — same as pre-P5 behavior. A warning is emitted listing the tickers with missing prices. No error is raised.

## Verification

1. `pytest tests/core/test_realized_performance_analysis.py -v` — all tests pass
2. `pytest tests/ --ignore=tests/api -q` — full suite green
3. Manual per-source check (use `format='full'` to access `realized_metadata` directly):
   ```bash
   python3 -c "
   from mcp_tools.performance import get_performance
   for source in ['all', 'plaid', 'schwab', 'ibkr_flex']:
       r = get_performance(mode='realized', source=source, format='full', use_cache=False)
       ret = r.get('returns', {})
       meta = r.get('realized_metadata', {})
       print(f'{source}: total={ret.get(\"total_return_pct\", \"?\")}%, initial_nav=\${meta.get(\"initial_nav\", \"?\")}')"
   ```
4. Update `RETURN_PROGRESSION_BY_FIX.md` with post-P5 measurements
5. Save live artifacts to `docs/planning/performance-actual-2025/live_test/`

## Not In Scope

- Backfill of missing BUY entries for incomplete trades (definitive fix, requires manual data or extended API lookback)
- Plaid security_id resolution for UNKNOWN symbols
- Synthetic lot construction policy changes
- Refactoring `compute_monthly_returns()` to use True Modified Dietz (sub-monthly flows)
- Observed-only monthly returns (currently only NAV endpoints are computed for the observed branch)

## Relationship to P3.1 and P4

- **P3.1** (`6c2f6e89`, implemented): Added futures compensating events and placed incomplete trade synthetics at inception. This fixed the -100% IBKR collapse. P5 builds on top of P3.1 — V_start seeding and budget-based suppression are complementary to the compensating events approach.
- **P4** (`CASH_REPLAY_P4_INCOMPLETE_TRADE_FIX_PLAN.md`): Proposed budget-based quantity suppression as the mechanism for incomplete trade handling. P4 was planned but not implemented as a standalone fix. P5 implements the budget mechanism described in P4, extending it with: (a) the `incomplete_qty_budget` parameter on `derive_cash_and_external_flows()`, (b) fresh budget copies for the observed-only branch, and (c) suppression diagnostics in metadata.

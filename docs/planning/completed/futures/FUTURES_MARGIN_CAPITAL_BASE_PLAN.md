# Futures Segment: Margin-Based Capital Base at Inception

## Context
The futures segment produces nonsensical returns (-298.77%) because cash starts at $0, futures trade notional is suppressed (fee-only policy), and MTM settlements push cash deeply negative. The cash anchor mechanism is disabled for all segments (`engine.py:1920`). We need a realistic capital base — estimated initial margin for the inception-date futures exposure.

## Key Discovery
IBKR Flex normalization (`flex.py:349`) already multiplies futures quantity by the contract multiplier. So `futures_notional_suppressed_usd` ($459,415) is true notional (price × qty × multiplier × fx), not raw price × qty. No multiplier fix needed.

## Approach
1. Add `margin_rate` to `contracts.yaml` per contract (approximate initial margin / notional)
2. During cash replay, compute **inception margin** — total estimated margin from positions open after processing all events on the first futures trade date
3. Upgrade `_futures_positions` to per-contract keying (fixes calendar spread inference suppression)
4. Use inception margin as the cash anchor for `segment="futures"`, respecting the `REALIZED_CASH_ANCHOR_NAV` feature flag

### Why Inception Margin, Not Peak Margin
Margin changes over time reflect changes in exposure, not additional capital contributions. Using peak margin would overstate the capital base and understate returns. Inception margin is the best estimate of what capital was actually deployed when futures trading began.

## Files to Modify

### 1. `brokerage/futures/contracts.yaml` — Add `margin_rate`
Add `margin_rate` field to each contract. Approximate IBKR initial margin rates (based on current CME requirements):

| Asset Class | Typical Rate | Contracts |
|---|---|---|
| equity_index (US) | 0.065 | ES, MES, NQ, MNQ, YM, RTY |
| equity_index (Asia) | 0.08–0.09 | NKD, MNK, NIY, HSI, MHI |
| equity_index (Europe) | 0.06–0.10 | ESTX50, DAX, Z |
| metals (precious) | 0.05–0.07 | GC, MGC, PL |
| metals (industrial) | 0.07–0.20 | HG, SI, PA |
| energy | 0.07–0.16 | CL, BZ, NG |
| fixed_income | 0.005–0.04 | ZB, ZN, ZF, ZT |

Per-contract values (not asset-class defaults) to handle variations like PA (0.20) vs GC (0.05).

### 2. `brokerage/futures/contract_spec.py` — Add `margin_rate` to dataclass
- Add `margin_rate: float = 0.10` to `FuturesContractSpec` (default 10% for unknown contracts)
- Add to `load_contract_specs()` constructor: `margin_rate=float(meta.get("margin_rate", 0.10))`
- Add to `to_contract_identity()` export

### 3. `core/realized_performance/nav.py` — Compute inception margin + fix position keying

In `derive_cash_and_external_flows()`:

**New import** (module-level):
```python
from brokerage.futures import get_contract_spec
```

**Thread expiry and con_id into event dict** (line 158-174, inside the event construction):
```python
"expiry": str((txn.get("contract_identity") or {}).get("expiry") or ""),
"con_id": str((txn.get("contract_identity") or {}).get("con_id") or ""),
```

**New constant + accumulators** (near line 249):
```python
_DEFAULT_MARGIN_RATE = 0.10
_futures_inception_margin_captured = False  # True once inception margin is snapshotted
futures_inception_margin_usd = 0.0
_futures_inception_date: Optional[date] = None  # calendar date of first futures trade
```

Note: `_futures_inception_margin_captured` is a dedicated boolean sentinel. Using `0.0` as a sentinel is wrong because all positions closing on inception date is a valid scenario where margin is legitimately 0.0.

**Per-contract tracking dicts** (near line 249):
```python
_futures_contract_price: Dict[Tuple[str, str], float] = {}
_futures_contract_fx: Dict[Tuple[str, str], float] = {}
_futures_contract_margin_rate: Dict[Tuple[str, str], float] = {}
```

**Upgrade `_futures_positions` keying** (line 248 and 333-342):
Change `_futures_positions: Dict[str, float]` to `Dict[Tuple[str, str], float]`.
This fixes calendar spread inference suppression — Jun ES and Sep ES tracked independently.

**Replace the position-tracking block** (lines 333-342). The current code uses `symbol` (assigned at line 334 as `str(event.get("symbol") or "").strip().upper()`). In the new code, use `normalized_symbol` (already assigned at line 261 as `str(event.get("symbol") or "").strip().upper()`) for consistency:

```python
if is_futures and event_type in ("BUY", "SELL", "SHORT", "COVER"):
    # Use .date() for calendar-day comparison (event["date"] is datetime,
    # may have intraday timestamps from some providers)
    event_cal_date = event["date"].date()

    # Detect transition past inception date → snapshot inception margin
    if (
        _futures_inception_date is not None
        and not _futures_inception_margin_captured
        and event_cal_date != _futures_inception_date
    ):
        _futures_inception_margin_captured = True
        futures_inception_margin_usd = sum(
            abs(cqty)
            * _futures_contract_price.get(ck, 0.0)
            * _futures_contract_margin_rate.get(ck, _DEFAULT_MARGIN_RATE)
            * _futures_contract_fx.get(ck, 1.0)
            for ck, cqty in _futures_positions.items()
        )

    # Update positions — use normalized_symbol (already assigned at line 261)
    contract_key_suffix = str(event.get("expiry") or "") or str(event.get("con_id") or "")
    contract_key = (normalized_symbol, contract_key_suffix)
    quantity = event["quantity"]
    if event_type in ("BUY", "COVER"):
        _futures_positions[contract_key] = _futures_positions.get(contract_key, 0.0) + quantity
    elif event_type in ("SELL", "SHORT"):
        _futures_positions[contract_key] = _futures_positions.get(contract_key, 0.0) - quantity

    if contract_key in _futures_positions and abs(_futures_positions[contract_key]) < 1e-9:
        del _futures_positions[contract_key]
        _futures_contract_price.pop(contract_key, None)
        _futures_contract_fx.pop(contract_key, None)
        _futures_contract_margin_rate.pop(contract_key, None)
    else:
        _futures_contract_price[contract_key] = event["price"]
        _futures_contract_fx[contract_key] = fx
        if contract_key not in _futures_contract_margin_rate:
            spec = get_contract_spec(normalized_symbol)
            _futures_contract_margin_rate[contract_key] = (
                spec.margin_rate if spec else _DEFAULT_MARGIN_RATE
            )

    # Track inception date (only set on actual position-changing trades)
    if _futures_inception_date is None:
        _futures_inception_date = event_cal_date
```

**After the event loop ends**, handle the case where all futures trades were on the same date (no date transition occurred):

```python
# If all futures trades were on one date, inception margin wasn't captured by date transition
if _futures_inception_date is not None and not _futures_inception_margin_captured:
    _futures_inception_margin_captured = True
    futures_inception_margin_usd = sum(
        abs(cqty)
        * _futures_contract_price.get(ck, 0.0)
        * _futures_contract_margin_rate.get(ck, _DEFAULT_MARGIN_RATE)
        * _futures_contract_fx.get(ck, 1.0)
        for ck, cqty in _futures_positions.items()
    )
```

**Why `abs(qty)` is correct**: Captures exposure for both longs and shorts:
- BUY opens long → qty positive → abs() = exposure
- SHORT opens short → qty negative → abs() = exposure

**Key design decisions**:
- **Boolean sentinel** (`_futures_inception_margin_captured`) instead of `== 0.0` check. Handles the "all positions close on inception date" edge case where margin is legitimately 0.0.
- **Calendar date comparison** (`event["date"].date()`) instead of string/datetime comparison. Events may have intraday timestamps from some providers; we want all trades on the same calendar date grouped together.
- **Position-changing events only** (`BUY/SELL/SHORT/COVER`). Non-trade futures rows (ADJUST, roll-style) don't change positions and shouldn't set inception date.
- **`normalized_symbol`** (line 261) instead of re-deriving `symbol` from `event.get("symbol")`. Both are equivalent (`str(event.get("symbol") or "").strip().upper()`), but using the already-assigned variable avoids scope confusion.

**Update `has_open_futures` check** (line 348): `bool(_futures_positions)` — unchanged, still works with tuple keys.

**Update end-of-replay warning** (lines 366-371): Format contract keys for display:
```python
open_contracts = ", ".join(
    f"{sym}({exp})" if exp else sym
    for sym, exp in sorted(_futures_positions.keys())
)
warnings.append(
    f"Cash replay: {len(_futures_positions)} open futures position(s) at end of "
    f"replay ({open_contracts}). Inference was suppressed during open period."
)
```

**Add to `replay_diagnostics.setdefault` block** (near line 77-93):
```python
replay_diagnostics.setdefault("futures_inception_margin_usd", 0.0)
replay_diagnostics.setdefault("futures_inception_trade_date", None)
```

**Store in replay_diagnostics** (near line 404):
```python
replay_diagnostics["futures_inception_margin_usd"] = max(
    _helpers._as_float(replay_diagnostics.get("futures_inception_margin_usd"), 0.0),
    futures_inception_margin_usd,
)
if _futures_inception_date is not None:
    existing = replay_diagnostics.get("futures_inception_trade_date")
    if existing is None:
        replay_diagnostics["futures_inception_trade_date"] = _futures_inception_date
    else:
        replay_diagnostics["futures_inception_trade_date"] = min(existing, _futures_inception_date)
```

**Why `max()` and `min()`**: For `segment="futures"`, `provider_first_mode = False` (engine.py:551), so there's only one replay pass. Multi-partition concern doesn't apply. Using `max()`/`min()` is a safe default.

### 4. `core/realized_performance/engine.py` — Use inception margin as anchor

**Add to `replay_diag` initialization** (line 1181-1198):
```python
"futures_inception_margin_usd": 0.0,
"futures_inception_trade_date": None,
```

**Add to `_finalize_replay_diag()`** (line 1200-1251):
```python
"futures_inception_margin_usd": round(
    _helpers._as_float(replay_diag.get("futures_inception_margin_usd"), 0.0),
    2,
),
"futures_inception_trade_date": replay_diag.get("futures_inception_trade_date"),
```

**Location**: Lines 1919-1953 (cash anchor block)

**Initialize all anchor-related locals unconditionally** before any branching, to avoid uninitialized variable bugs when branches are skipped (e.g., `segment="futures"` + `REALIZED_CASH_ANCHOR_NAV=False`):

```python
cash_anchor_requested = bool(_helpers._shim_attr("REALIZED_CASH_ANCHOR_NAV", True))
if segment != "all" and segment != "futures":
    cash_anchor_requested = False

# Initialize all anchor locals unconditionally — some branches may skip assignment
observed_end_cash = 0.0
back_solved_start_cash = 0.0
raw_observed_cash_anchor_offset = 0.0
_cash_anchor_matched_rows = 0
cash_anchor_source = "none"
cash_anchor_available = False
cash_anchor_applied_to_nav = False
cash_anchor_offset_usd = 0.0
observed_only_cash_anchor_offset_usd = 0.0
replay_final_cash = cash_snapshots[-1][1] if cash_snapshots else 0.0
anchor_snapshot: List[Tuple[datetime, float]] = []
_futures_margin_available = False  # True if inception margin > 0 (availability)
_futures_margin_anchor_usd = 0.0
_futures_margin_anchor_date: Optional[datetime] = None

# --- Compute availability first (independent of flag) ---
# This preserves the existing semantic: cash_anchor_available and
# cash_anchor_source report whether an anchor CAN be applied, even
# when the feature flag is off. See test_realized_cash_anchor.py:197.
if segment == "futures":
    _inception_margin = _helpers._as_float(
        cash_replay_diagnostics.get("futures_inception_margin_usd"), 0.0
    )
    _inception_trade_date = cash_replay_diagnostics.get("futures_inception_trade_date")
    if _inception_margin > 0 and _inception_trade_date is not None:
        # Convert date to datetime for anchor snapshot
        if isinstance(_inception_trade_date, date) and not isinstance(_inception_trade_date, datetime):
            _futures_margin_anchor_date = datetime.combine(_inception_trade_date, datetime.min.time())
        else:
            _futures_margin_anchor_date = _inception_trade_date
        _futures_margin_available = True
        _futures_margin_anchor_usd = _inception_margin
        raw_observed_cash_anchor_offset = _inception_margin
        back_solved_start_cash = _inception_margin
        cash_anchor_source = "futures_margin"
        cash_anchor_available = True
    # else: all defaults hold (available=False, source="none")

else:
    # --- Legacy observed-cash anchor path (non-futures only) ---
    statement_end_cash = (
        _statement_cash_from_metadata()
        if source == "ibkr_flex"
        else None
    )
    if statement_end_cash is not None:
        observed_end_cash = statement_end_cash
        _cash_anchor_matched_rows = 1
        cash_anchor_source = "ibkr_statement"
    else:
        observed_end_cash, _cash_anchor_matched_rows = _cash_anchor_offset_from_positions()
        cash_anchor_source = "snaptrade_cur"
    back_solved_start_cash = observed_end_cash - replay_final_cash
    raw_observed_cash_anchor_offset = back_solved_start_cash
    cash_anchor_available = abs(raw_observed_cash_anchor_offset) > 1e-9

# --- Apply anchor (shared path, gated on flag + availability) ---
# For futures: anchor at the first futures trade date (not engine inception_date)
# For non-futures: anchor at inception_date (existing behavior)
futures_margin_anchor_applied = False  # True only if margin anchor was actually applied
_anchor_date = _futures_margin_anchor_date if _futures_margin_available else inception_date
if cash_anchor_requested and cash_anchor_available:
    anchor_snapshot = [(_anchor_date, raw_observed_cash_anchor_offset)]
    cash_snapshots = _apply_cash_anchor(cash_snapshots, anchor_snapshot)
    cash_anchor_applied_to_nav = True
    cash_anchor_offset_usd = raw_observed_cash_anchor_offset
    observed_only_cash_anchor_offset_usd = raw_observed_cash_anchor_offset
    if _futures_margin_available:
        futures_margin_anchor_applied = True
elif cash_anchor_requested and not cash_anchor_available and segment != "futures":
    # Only warn for non-futures. For futures with zero margin, absence of anchor
    # is expected (all positions may have closed on inception date).
    warnings.append(
        "REALIZED_CASH_ANCHOR_NAV enabled but no observed cash snapshot is available; continuing without anchor."
    )
```

This structure ensures:
- All locals are initialized to safe defaults before any branch (including `replay_final_cash`)
- `segment == "futures"` **never** runs `_statement_cash_from_metadata()` or `_cash_anchor_offset_from_positions()`
- Availability is computed first (independent of flag): `cash_anchor_available`, `cash_anchor_source`, `_futures_margin_available` are set before checking `cash_anchor_requested`
- Application is gated on flag: `futures_margin_anchor_applied` is only True when both available AND the flag is on
- Zero-margin futures don't trigger the misleading "no observed cash snapshot" warning
- If `REALIZED_CASH_ANCHOR_NAV = False`, both paths skip application cleanly but still report availability
- The shared anchor application block uses the correct date: first trade date for futures, inception_date for non-futures
- `replay_final_cash` is always assigned before any branch reads it

**Fix observed-only branch** (replace lines 2014-2019):
```python
if cash_anchor_applied_to_nav:
    if futures_margin_anchor_applied:
        # Futures margin anchor: apply the same fixed offset to observed-only branch.
        # Don't backsolve from observed_end_cash — use the same inception margin directly.
        observed_only_cash_anchor_offset_usd = _futures_margin_anchor_usd
        observed_anchor_snapshot = [(_futures_margin_anchor_date, _futures_margin_anchor_usd)]
        observed_cash_snapshots = _apply_cash_anchor(observed_cash_snapshots, observed_anchor_snapshot)
    else:
        observed_replay_final = observed_cash_snapshots[-1][1] if observed_cash_snapshots else 0.0
        observed_back_solved_start = observed_end_cash - observed_replay_final
        observed_only_cash_anchor_offset_usd = observed_back_solved_start
        observed_anchor_snapshot = [(inception_date, observed_back_solved_start)]
        observed_cash_snapshots = _apply_cash_anchor(observed_cash_snapshots, observed_anchor_snapshot)
```

**Metadata output** (~line 2609):
```python
"futures_cash_policy": "fee_only",  # Cash replay policy is always fee_only — unchanged by anchor
"futures_margin_anchor_applied": bool(futures_margin_anchor_applied),
"futures_margin_anchor_usd": round(_futures_margin_anchor_usd if futures_margin_anchor_applied else 0.0, 2),
```

Note: `futures_cash_policy` stays `"fee_only"` — it describes the cash replay policy (notional suppressed, fees only), not anchor state. The anchor state is captured by the separate `futures_margin_anchor_applied` and `cash_anchor_applied_to_nav` fields.

### 5. `core/result_objects/realized_performance.py` — Add metadata fields
- `RealizedMetadata`: add `futures_margin_anchor_applied: bool = False`, `futures_margin_anchor_usd: float = 0.0`
- `to_dict()` / `from_dict()` / agent snapshot `data_quality` section: add the two fields

### 6. `core/realized_performance/aggregation.py` (~line 1032)
Use correct aggregation patterns for futures-margin fields and anchor fields whose meaning changes with this feature:
```python
"futures_margin_anchor_applied": any(
    bool(meta.get("futures_margin_anchor_applied", False)) for meta in meta_dicts
),
"futures_margin_anchor_usd": round(_sum_field("futures_margin_anchor_usd"), 2),
"futures_cash_policy": "fee_only",  # Always fee_only — describes cash replay policy, not anchor
"cash_anchor_source": (
    "futures_margin"
    if any(meta.get("cash_anchor_source") == "futures_margin" for meta in meta_dicts)
    else first_meta.get("cash_anchor_source", "none")
),
"cash_anchor_applied_to_nav": any(
    bool(meta.get("cash_anchor_applied_to_nav", False)) for meta in meta_dicts
),
"cash_anchor_available": any(
    bool(meta.get("cash_anchor_available", False)) for meta in meta_dicts
),
"cash_anchor_offset_usd": round(_sum_field("cash_anchor_offset_usd"), 2),
"observed_only_cash_anchor_offset_usd": round(
    _sum_field("observed_only_cash_anchor_offset_usd"), 2
),
```

The `any()` pattern is correct for booleans: if any account applied/has the anchor, aggregate reports True.
The `_sum_field()` pattern is correct for USD amounts: multi-account totals sum.

Also re-aggregate `cash_backsolve_*` fields, since the futures path repurposes `back_solved_start_cash` to hold inception margin (changing their semantics):
```python
"cash_backsolve_start_usd": round(_sum_field("cash_backsolve_start_usd"), 2),
"cash_backsolve_observed_end_usd": round(_sum_field("cash_backsolve_observed_end_usd"), 2),
"cash_backsolve_replay_final_usd": round(_sum_field("cash_backsolve_replay_final_usd"), 2),
"cash_backsolve_matched_rows": _sum_int_field("cash_backsolve_matched_rows"),
```

### 7. Tests — `tests/core/test_realized_performance_segment.py`

**Test A: `test_segment_futures_margin_anchor_applied`**
- Mock `derive_cash_and_external_flows` to populate `replay_diagnostics["futures_inception_margin_usd"] = 5000.0` and `replay_diagnostics["futures_inception_trade_date"] = date(2024, 6, 15)`
- Run with `segment="futures"`
- Assert: `cash_anchor_applied_to_nav = True`, `cash_anchor_source = "futures_margin"`, `futures_margin_anchor_applied = True`, `futures_margin_anchor_usd = 5000.0`
- Assert: observed-only anchor offset also equals 5000.0

**Test B: `test_segment_futures_zero_margin_no_anchor`**
- `futures_inception_margin_usd = 0.0` → assert anchor NOT applied, legacy paths NOT invoked

**Test C: `test_futures_inception_margin_computation`**
- Unit test for inception margin: multiple BUY events on day 1, verify margin computed from end-of-day-1 positions. Then trades on day 2 — verify inception margin is unchanged (only day 1 matters).

**Test D: `test_futures_inception_margin_calendar_spread`**
- Two contracts with same root but different expiries open on day 1. Verify independent margin (not netted). Also verify `_futures_positions` tracks them independently (inference suppression stays active).

**Test E: `test_segment_futures_anchor_respects_feature_flag`**
- Set `REALIZED_CASH_ANCHOR_NAV = False`, run with `segment="futures"`. Assert anchor NOT applied even with nonzero inception margin. Assert `cash_anchor_available = True` (availability reported regardless of flag) but `cash_anchor_applied_to_nav = False`. Assert no uninitialized variable errors — all metadata fields populated.

**Test F: `test_futures_inception_margin_single_day`**
- All futures trades on one date (no date transition during loop). Verify inception margin still computed correctly from the post-loop fallback.

**Test G: `test_futures_inception_margin_all_close_on_day1`**
- Open and close all positions on inception date. Verify `_futures_inception_margin_captured = True` with `futures_inception_margin_usd = 0.0`. Verify no anchor is applied (0 margin → no anchor).

**Test H: `test_futures_inception_date_only_set_on_trades`**
- Mix of ADJUST-type and BUY events. Verify inception date is set from the first BUY, not from ADJUST.

**Test I: `test_futures_anchor_uses_trade_date_not_inception_date`**
- Setup where engine `inception_date` (from first FUTURES_MTM) is earlier than the first actual futures trade date. Verify the margin anchor is injected at the trade date, not the MTM-derived inception date.

## What NOT to Change
- `nav.py` notional computation (line 275) — already correct (qty includes multiplier)
- `compute_monthly_nav()` — already excludes futures from position valuation
- Non-futures segments — anchor stays disabled
- `_apply_cash_anchor()` — reused as-is

## Known Limitations (Pre-existing, Out of Scope)
- **MTM before first trade**: A `FUTURES_MTM` row landing before the first actual futures trade can create a negative cash impact that triggers bogus inferred flow. This is pre-existing behavior (`FUTURES_MTM` events have `is_futures=False` in nav.py:220, so inference suppression via `has_open_futures` doesn't apply). Not introduced by this plan.

## Codex Review Findings Addressed (Reviews 1-9)
1. **Observed-only branch mismatch** → Fixed: futures path applies same fixed offset instead of backsolving
2. **Root symbol keying collapses calendar spreads** → Fixed: `_futures_positions` AND margin tracking both use (symbol, contract_key) tuple
3. **Peak accumulation uses `+`** → Fixed: uses `max()`. Safe because futures segment disables provider_first_mode
4. **Missing diagnostic key initialization** → Fixed: added to `replay_diag` init + `_finalize_replay_diag()`
5. **RTY misbucketed** → Fixed: RTY in US equity_index group at 0.065
6. **Short handling wrong** → Fixed: track net qty per contract, use `abs(qty)` × price × rate
7. **Expiry unreliable** → Fixed: use expiry if available, else con_id, else "" as fallback
8. **Multi-partition peak** → Documented: not applicable for futures segment
9. **Calendar spread inference suppression** → Fixed: upgraded `_futures_positions` to per-contract keying
10. **Aggregation wrong for multi-account** → Fixed: `any()` for bool, `_sum_field()` for amount
11. **Feature flag bypass** → Fixed: only apply anchor if `cash_anchor_requested` (from flag) is already True
12. **Backsolve metadata inconsistency** → Fixed: explicitly set `observed_end_cash = 0.0`, `cash_anchor_source = "futures_margin"` clarifies methodology
13. **Peak vs inception margin** → Resolved: inception-only margin. Margin changes over time are not capital contributions.
14. **Date comparison uses string vs datetime** → Fixed: use `event["date"].date()` for calendar-day comparison (handles intraday timestamps)
15. **`0.0` sentinel ambiguous** → Fixed: dedicated `_futures_inception_margin_captured` boolean sentinel. Correctly handles "all positions close on inception date" (margin = 0.0 is valid).
16. **Non-trade rows set inception date** → Fixed: position tracking block gated on `event_type in ("BUY", "SELL", "SHORT", "COVER")` only
17. **Engine anchor gate incomplete** → Fixed: restructured anchor block so `segment == "futures"` bypasses legacy paths entirely. Zero margin → `cash_anchor_requested = False` immediately.
18. **Aggregation `cash_anchor_*` fields use first-account** → Fixed: re-aggregate `cash_anchor_applied_to_nav`, `cash_anchor_source`, `cash_anchor_available`, `cash_anchor_offset_usd`, `observed_only_cash_anchor_offset_usd`.
19. **Variable initialization order** → Fixed: all anchor locals initialized to safe defaults before any branching, including `replay_final_cash`.
20. **MTM before first trade** → Documented as pre-existing known limitation (not introduced by this plan).
21. **`symbol` variable scope in nav.py** → Fixed: use `normalized_symbol` (already assigned at line 261) instead of re-deriving from event.
22. **Anchor at engine inception_date vs first trade date** → Fixed: surface `futures_inception_trade_date` from nav.py via replay_diagnostics. Engine uses this for the anchor snapshot date, not `inception_date` (which may include earlier MTM rows).
23. **`replay_final_cash` uninitialized** → Fixed: assigned unconditionally before branching in the defaults block.
24. **`cash_anchor_available` and `observed_only_cash_anchor_offset_usd` aggregation** → Fixed: added to re-aggregation block.
25. **Availability/source feature-flag-dependent for futures** → Fixed: compute availability first (independent of flag), then gate only application on the flag. `cash_anchor_available = True` and `cash_anchor_source = "futures_margin"` even when flag is off — matches existing test semantics.
26. **`cash_backsolve_*` aggregation changed semantics** → Fixed: re-aggregate `cash_backsolve_start_usd`, `cash_backsolve_observed_end_usd`, `cash_backsolve_replay_final_usd`, `cash_backsolve_matched_rows` since futures path repurposes these fields.
27. **`futures_margin_anchor` conflates availability with application** → Fixed: split into `_futures_margin_available` (availability, set before flag check) and `futures_margin_anchor_applied` (application, set only after anchor is actually applied). Metadata uses `futures_margin_anchor_applied`.
28. **`futures_cash_policy` repurposed incorrectly** → Fixed: stays `"fee_only"` always — describes cash replay policy, not anchor state. Anchor state captured by separate `futures_margin_anchor_applied` field.
29. **Zero-margin futures triggers misleading warning** → Fixed: "no observed cash snapshot" warning suppressed for `segment == "futures"`. Zero margin is expected when all positions close on inception date.

## Verification
1. `pytest tests/core/test_realized_performance_segment.py -x`
2. `pytest tests/core/test_realized_performance_analysis.py -x`
3. `pytest tests/mcp_tools/test_performance.py -x`
4. Live: `get_performance(mode="realized", segment="futures")` — returns meaningful, `cash_anchor_source = "futures_margin"`, NAV starts at estimated inception margin

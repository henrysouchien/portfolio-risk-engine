# Plan: Dual Cash Anchor + Fee Fix

**Status:** Fixes 1 & 2 COMPLETE (`c0ec8697`), Fix 3 (dual anchor) DEFERRED, Fix 4 (fee dedup) DEFERRED
**Goal:** Close the 5.2pp TWR gap vs IBKR statement (engine +5.52% → target ~0.3%)
**Decision (2026-03-08):** Deferring Fix 3+4. Using back-solve approach instead of dual anchor. The remaining TWR gap is acceptable given data coverage constraints.
**Depends on:** Fix 1 (cash anchor) COMPLETE, Fix 2a (MTM metadata) COMPLETE, Fix 2b (AT. pricing) COMPLETE

## Context

The realized performance engine TWR is +5.52% vs IBKR official +0.29% (gap ~5.2pp).
Post-Fix 2b, the gap was attributed to missing non-trade items (dividends, interest, fees).

**Key finding (2026-03-07 deep-dive):** Non-trade items are **already captured**:
- Dividends: +$182.41 (exact match with IBKR statement for Apr+ window, 33 events in store)
- Interest: -$276 (13 events, USD margin interest, close to IBKR's -$262)
- Fees: -$319 (35 events — **but includes -$155 double-count bug**)

The **entire** TWR gap is from the starting cash back-solve error. With an anchored
start cash of -$11,097, inception NAV moves from $18,358 → $22,371 (within $87 of
IBKR's $22,284). The monthly return path after inception is correct because all
trade flows, dividends, interest, and fees already flow through the cash replay.

## Fix 1: RealizedMetadata MTM Fields — COMPLETE (`c0ec8697`)

**File**: `core/result_objects/realized_performance.py`

Add two fields to the `RealizedMetadata` dataclass (after `futures_fee_cash_impact_usd` ~line 161):
```python
futures_mtm_event_count: int = 0
futures_mtm_cash_impact_usd: float = 0.0
```

Add to `to_dict()` and `from_dict()` methods correspondingly.

## Fix 2: Dynamic `futures_cash_policy` (uncommitted from prior session)

**File**: `core/realized_performance/engine.py:2472`

Change from:
```python
"futures_cash_policy": "fee_only",
```
To:
```python
"futures_cash_policy": "fee_and_mtm" if int(_helpers._as_float(cash_replay_diagnostics.get("futures_mtm_event_count"), 0.0)) > 0 else "fee_only",
```

## Fix 3: Dual Cash Anchor

### Step 1: Expand `_statement_cash_from_metadata()` return type

**File**: `core/realized_performance/engine.py:1757-1783`

Currently returns `float | None` (just `ending_cash_usd`). Change to return a dict:

```python
def _statement_cash_from_metadata() -> dict[str, float] | None:
    """Extract IBKR statement starting + ending cash from fetch_metadata."""
    for row in provider_fetch_metadata:
        if str(row.get("provider") or "").strip().lower() != "ibkr_flex":
            continue
        sc = row.get("statement_cash")
        if isinstance(sc, dict) and sc.get("ending_cash_usd") is not None:
            result = {"ending_cash_usd": float(sc["ending_cash_usd"])}
            if sc.get("starting_cash_usd") is not None:
                result["starting_cash_usd"] = float(sc["starting_cash_usd"])
            return result
    return None
```

Note: `extract_statement_cash()` in `ibkr/flex.py:1401` already extracts both `starting_cash_usd` and `ending_cash_usd` from the SQLite DB and stores them in the metadata dict. No changes to value extraction needed.

**Additionally:** Add `period_start` to the return dict by parsing the DB filename:

```python
import re
m = re.search(r'_(\d{8})_\d{8}', str(statement_db_path))
if m:
    result["period_start"] = f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:8]}"
```

This carries the statement period start date through metadata so the engine can
anchor the cash at the correct date (see Step 3).

### Step 2: Update caller site to consume both values

**File**: `core/realized_performance/engine.py:1785-1817`

Current flow:
1. `statement_end_cash = _statement_cash_from_metadata()` → single float
2. `observed_end_cash = statement_end_cash`
3. `back_solved_start_cash = observed_end_cash - replay_final_cash`
4. `anchor_snapshot = [(inception_date, back_solved_start_cash)]`

New flow:
```python
cash_anchor_requested = bool(_helpers._shim_attr("REALIZED_CASH_ANCHOR_NAV", True))
# Initialize dual-anchor variables with defaults (used by metadata emit + futures path)
cash_anchor_mode = "single"
observed_start_cash = None
residual = 0.0

statement_cash = (
    _statement_cash_from_metadata()
    if source == "ibkr_flex"
    else None
)
# Gate: statement cash activates ONLY for source="ibkr_flex" (explicit IBKR source).
# This is the existing gate at engine.py:1967 — unchanged from current behavior.
# For source="all" (any institution), returns None → snaptrade_cur back-solve.
if statement_cash is not None:
    observed_end_cash = statement_cash["ending_cash_usd"]
    observed_start_cash = statement_cash.get("starting_cash_usd")  # may be None
    _cash_anchor_matched_rows = 1
    cash_anchor_source = "ibkr_statement"
else:
    observed_end_cash, _cash_anchor_matched_rows = _cash_anchor_offset_from_positions()
    observed_start_cash = None
    cash_anchor_source = "snaptrade_cur"

replay_final_cash = cash_snapshots[-1][1] if cash_snapshots else 0.0

if observed_start_cash is not None and statement_cash.get("period_start"):
    # Start anchor: will be calibrated at period_start in Step 3
    cash_anchor_mode = "start_anchor"
else:
    # Legacy: back-solve from end (also used when period_start is missing)
    cash_anchor_mode = "single"

replay_final_cash_val = cash_snapshots[-1][1] if cash_snapshots else 0.0
raw_inception_cash = observed_end_cash - replay_final_cash_val  # legacy back-solve
back_solved_start_cash = raw_inception_cash
raw_observed_cash_anchor_offset = raw_inception_cash
# Note: for start_anchor mode, the actual offset is computed in Step 3
# using the period_start date. raw_inception_cash here is the legacy fallback.
cash_anchor_available = (
    cash_anchor_mode == "start_anchor"
    or abs(raw_observed_cash_anchor_offset) > 1e-9
)
# start_anchor mode is always available when statement cash + period_start present.
# single mode requires non-zero back-solve offset.
```

### Step 3: Calibrate anchor at statement period start date

**Critical:** The statement `starting_cash_usd` (-$11,097) is the cash balance on
**April 1, 2025** (the statement period start). The engine's `inception_date` is
**February 25, 2025** (when the first transaction occurred). These are ~5 weeks apart.
Anchoring April 1 cash at February 25 would corrupt the March/April opening NAV.

**Fix:** Find the replay cash at the statement start date and calibrate the anchor
offset there. The anchor is a constant offset applied to ALL cash snapshots:
`actual_cash(date) = replay_cash(date) + anchor_offset`

```python
if cash_anchor_requested and cash_anchor_available and cash_anchor_mode == "start_anchor":
    # Find the replay cash value BEFORE the statement period start date.
    # "Starting Cash" is the opening balance before any activity on that day.
    # Cash snapshots are midnight-normalized, so snap_dt == stmt_start_dt
    # includes that day's activity. Use strict < to get the pre-activity value.
    stmt_start_date = statement_cash.get("period_start")  # "YYYY-MM-DD"
    if stmt_start_date:
        stmt_start_dt = pd.Timestamp(stmt_start_date)
        # Guard: period_start must fall within the replay window
        if not (inception_date <= stmt_start_dt <= end_date):
            # Statement period doesn't overlap replay — fall back to end-anchor
            cash_anchor_mode = "single"
        else:
            replay_before_stmt_start = 0.0
            for snap_dt, snap_cash in cash_snapshots:
                if snap_dt < stmt_start_dt:
                    replay_before_stmt_start = snap_cash
                else:
                    break
            anchor_offset = observed_start_cash - replay_before_stmt_start
    if cash_anchor_mode != "start_anchor":
        # Fall back to legacy end-anchor
        anchor_offset = raw_inception_cash

    anchor_snapshot = [(inception_date, anchor_offset)]
    cash_snapshots = _apply_cash_anchor(cash_snapshots, anchor_snapshot)
    cash_anchor_applied_to_nav = True
    cash_anchor_offset_usd = anchor_offset
    observed_only_cash_anchor_offset_usd = anchor_offset
elif cash_anchor_requested and cash_anchor_available:
    # Legacy end-anchor path (back-solved from observed_end_cash)
    anchor_offset = raw_inception_cash
    anchor_snapshot = [(inception_date, anchor_offset)]
    cash_snapshots = _apply_cash_anchor(cash_snapshots, anchor_snapshot)
    cash_anchor_applied_to_nav = True
    cash_anchor_offset_usd = anchor_offset
    observed_only_cash_anchor_offset_usd = anchor_offset
```

**Why this works:** At `stmt_start_dt` (April 1): `replay_at_stmt_start + anchor_offset = observed_start_cash` (exact). At inception: the offset was computed from April 1 data, so inception cash is off by ~1 month of replay drift (small, vs 12 months before). At end: the offset drifts by the full replay error, but TWR computation uses monthly NAVs which are now anchored correctly from April onward.

### Step 4: Apply same anchor to observed-only track

**File**: `core/realized_performance/engine.py:1878-1883`

The observed-only track currently does its own independent back-solve. Apply the
same period-start calibrated anchor. Reuse `anchor_offset` computed in Step 3
(it's the same offset for both tracks since the anchor is a global constant):

```python
if cash_anchor_applied_to_nav:
    observed_only_cash_anchor_offset_usd = anchor_offset
    observed_anchor_snapshot = [(inception_date, anchor_offset)]
    observed_cash_snapshots = _apply_cash_anchor(observed_cash_snapshots, observed_anchor_snapshot)
```

### Step 5: Metadata updates

**File**: `core/realized_performance/engine.py:2395-2413`

Add new fields to the `realized_metadata` dict:
```python
"cash_anchor_mode": cash_anchor_mode,  # "start_anchor" | "single"
"cash_anchor_observed_start_usd": round(_helpers._as_float(observed_start_cash, 0.0), 2) if observed_start_cash is not None else None,
# Preserve legacy back-solve value as diagnostic even in start_anchor mode
"cash_backsolve_start_usd": round(observed_end_cash - replay_final_cash, 2),
```

**Important:** The existing `cash_backsolve_start_usd` field currently gets overwritten
when the anchor is applied. In start_anchor mode, preserve the original back-solve value
(`observed_end_cash - replay_final_cash`) as a diagnostic alongside the anchored
`cash_anchor_observed_start_usd`. This allows comparing the two approaches without
re-running.

**File**: `core/result_objects/realized_performance.py`

Add to `RealizedMetadata` dataclass:
```python
cash_anchor_mode: str = "single"  # "start_anchor" | "single"
cash_anchor_observed_start_usd: Optional[float] = None
```

Add to `to_dict()` and `from_dict()`.

### Step 6: Design rationale — start-only anchor, no residual

**Why start-only (no residual distribution):** Distributing a residual across cash
snapshots changes NAV without a corresponding flow, which TWR treats as performance.
Instead, we calibrate a constant offset at the statement period start date (Step 3)
and let the replay run forward naturally. The ending cash drifts but TWR is correct.

**Why apply the offset from inception (not just period_start onward):** The anchor
offset is a constant correction for missing transaction cash flows. Applying it from
inception ensures inception NAV is also corrected (with ~5 weeks of drift from
Feb 25 → Apr 1). The alternative — leaving pre-period data unanchored — would
mean inception NAV has no correction at all, defeating the primary purpose of the fix.

**Pre-period drift tradeoff:** Cash from inception (Feb 25) to period_start (Apr 1)
has ~5 weeks of uncalibrated drift. This is vastly better than the current 12-month
drift from the end-anchor approach. The Feb/March monthly returns may be slightly
off, but April onward (the statement-covered period) is exact at the calibration
point and accumulates drift going forward, not backward.

### Step 6b: Guard consolidated statement cash for account-scoped requests

**Problem:** The statement cash is consolidated (`cash_report__all`) and cannot
be attributed to a single account. Account-scoped requests arrive via:
1. The aggregation per-account fan-out (`aggregation.py:1282`)
2. Direct account-scoped calls (`aggregation.py:1417`, `account` param set)

Both paths would apply the full consolidated start cash to one account's
inception NAV, producing a materially wrong TWR.

**Approach:** Minimal change. The existing `source == "ibkr_flex"` gate at
engine.py:1967 is the only guard today and it works correctly for all current
paths. The ONLY new guard needed: disable statement cash for multi-account
aggregation fan-out.

**File:** `core/realized_performance/engine.py`

Add a single keyword param:
```python
def _analyze_realized_performance_single_scope(
    ...
    *,
    use_per_symbol_inception: bool = False,
    disable_statement_cash: bool = False,  # NEW: multi-account guard
) -> ...:
```

In `_statement_cash_from_metadata()`, add one line at the top:
```python
def _statement_cash_from_metadata() -> dict[str, float] | None:
    if disable_statement_cash:
        return None
    # ... existing source == "ibkr_flex" gate and metadata lookup (unchanged)
```

**File:** `core/realized_performance/aggregation.py`

Multi-account fan-out only (`aggregation.py:1282`):
```python
for account_id in account_ids:
    account_result = engine._analyze_realized_performance_single_scope(
        ...
        account=account_id,
        disable_statement_cash=(len(account_ids) > 1),
    )
```

**All other call sites unchanged.** The existing `source == "ibkr_flex"` gate
in the engine handles everything else. This means:
- `source="ibkr_flex"`, any account → statement cash used (existing behavior + new start anchor)
- `source="all"`, any account → gate returns None (existing behavior, unchanged)
- Multi-account fan-out → `disable_statement_cash=True` → gate returns None
- Single-account short-circuit → default `disable_statement_cash=False` → statement cash used
- Fallback paths (aggregation.py:1252, 1323) → default False → unchanged behavior

### Step 7: No feature flag needed

The start anchor activates automatically when `starting_cash_usd` is present in
the statement metadata. When absent (SnapTrade/Plaid), falls back to the existing
single-endpoint back-solve. This is a strict improvement with no behavioral change
for non-IBKR sources.

## Files Modified

| File | Change |
|------|--------|
| `core/result_objects/realized_performance.py` | Add `futures_mtm_event_count`, `futures_mtm_cash_impact_usd`, `cash_anchor_mode`, `cash_anchor_observed_start_usd` |
| `ibkr/flex.py:1401` | Add `period_start` to `extract_statement_cash()` return dict |
| `core/realized_performance/engine.py:1757` | `_statement_cash_from_metadata()` returns dict with both cash values |
| `core/realized_performance/engine.py:1785` | Dual anchor logic replacing single back-solve |
| `core/realized_performance/engine.py:1878` | Dual anchor for observed-only track |
| `core/realized_performance/engine.py:2395` | New metadata fields |
| `core/realized_performance/engine.py:2472` | Dynamic `futures_cash_policy` |
| `core/realized_performance/aggregation.py` | Thread new metadata fields; Step 6b `disable_statement_cash` in multi-account fan-out |
| `ibkr/flex.py` | Fix 4: `_remove_fee_subtotals()` in `normalize_flex_cash_rows()` |
| `ibkr/flex.py:794` | Fix 5a: Cross-currency dedup to preserve distinct HKD interest |
| `core/result_objects/realized_performance.py:548` | Wire new metadata fields into `get_agent_snapshot()` `data_quality` dict |
| `tests/core/test_realized_cash_anchor.py` | Start anchor tests (11 tests) |
| `tests/core/test_fee_dedup.py` | NEW: Fee subtotal dedup tests (8 tests) |
| `tests/ibkr/test_flex_cross_currency_dedup.py` | NEW: Cross-currency dedup tests (2 tests) |

## Tests

**Modify**: `tests/core/test_realized_cash_anchor.py`

Start anchor core:
1. Statement start cash + period_start available → `cash_anchor_mode == "start_anchor"`, cash at period_start date matches `starting_cash_usd` exactly
2. Only ending cash available → `cash_anchor_mode == "single"`, falls back to existing end-anchor back-solve behavior
3. Cash at period_start == `starting_cash_usd` (anchor calibrated at period_start, NOT at inception)
4. Single-snapshot edge case: no crash
5. Observed-only track uses same `anchor_offset` as main track

Zero start cash edge case:
6. Statement `starting_cash_usd == 0.0` + start_anchor mode → anchor IS applied (zero is valid), `cash_anchor_available == True`
7. Back-solve produces 0.0 + single mode → `cash_anchor_available == False` (zero from back-solve is suspicious)

Legacy diagnostic preservation:
8. In start_anchor mode, `cash_backsolve_start_usd` still reflects the raw back-solve value (`observed_end_cash - replay_final_cash`), NOT the anchored value. Verify both `cash_anchor_observed_start_usd` and `cash_backsolve_start_usd` are present and different.

Anchor calibration date:
9. Anchor calibrated using replay cash strictly BEFORE `period_start` — `replay_before_stmt_start` excludes any period_start-day activity (strict `<`, not `<=`)
10. Cash at period_start (after anchor) matches `starting_cash_usd` when no same-day activity precedes it
11. Inception date (Feb 25) cash differs from raw statement start cash (anchor is an offset, not direct injection)
12. No `period_start` in metadata → falls back to legacy end-anchor back-solve
17. `period_start` before `inception_date` → falls back to end-anchor (statement doesn't overlap replay)
18. `period_start` after `end_date` → falls back to end-anchor
19. Explicit `account="U2471778"` via direct call → default `disable_statement_cash=False` → existing source gate applies → start anchor activates (same as no-account call)
20. Fallback paths in aggregation (prefetch error, all-account error) → default False → unchanged behavior, no regression

Source gate:
12. `source="ibkr_flex"` → start anchor activates
13. `source="all"` (any institution) → start anchor does NOT activate (existing gate)
13. `disable_statement_cash=True` → `_statement_cash_from_metadata()` returns None, falls back to end-anchor
14. `disable_statement_cash=False` (default) → existing source gate applies, statement cash used for ibkr_flex
15. Multi-account aggregation → `disable_statement_cash=True` per account → each falls back to end-anchor
16. Single-account aggregation → default False → start anchor activates

**Modify**: `tests/core/test_fee_dedup.py` (new file)

Fee dedup:
13. `test_fee_subtotal_excluded` — 3 rows on same date/account/currency where one = sum of others → subtotal removed (even with different descriptions)
14. `test_fee_no_subtotal` — 2 rows on same date, neither is sum → both kept
15. `test_fee_single_row` — 1 row on a date → kept
16. `test_fee_cross_account_no_false_positive` — fee on account A equals sum of fees on account B → both kept (different groups)
17. `test_fee_cross_currency_no_false_positive` — USD fee equals sum of HKD fees → both kept
18. `test_fee_different_description_subtotal_detected` — subtotal with generic description ("OTHER/FEES") correctly detected even though individual items have different descriptions
19. `test_fee_subtotal_plus_unrelated` — 2 detail + 1 subtotal + 1 unrelated fee on same date → known limitation: heuristic may not detect subtotal (document behavior)
20. `test_fee_net_total_matches_ibkr` — after dedup, total ≈ -$164 (IBKR statement)

**Modify**: `tests/ibkr/test_flex_cross_currency_dedup.py` (new file)

HKD interest cross-currency dedup:
20. `test_cross_currency_dedup_keeps_distinct_amounts` — USD interest -$50 + HKD interest -$9.44 on same date → both kept (different USD amounts)
21. `test_cross_currency_dedup_drops_true_duplicate` — USD interest -$50 + HKD interest -$50 equivalent on same date → HKD row dropped (same USD amount)

**Modify**: `tests/mcp_tools/test_performance.py`
- Verify new metadata fields (`cash_anchor_mode`, `cash_anchor_observed_start_usd`, `cash_backsolve_start_usd`, `futures_mtm_event_count`, `futures_mtm_cash_impact_usd`) serialized correctly in agent format
- Verify aggregated multi-source metadata propagates `cash_anchor_mode` per scope

## Verification

```bash
# Unit tests
pytest tests/core/test_realized_cash_anchor.py -x -v
pytest tests/core/test_fee_dedup.py -x -v
pytest tests/ibkr/test_flex_cross_currency_dedup.py -x -v
pytest tests/mcp_tools/test_performance.py -x -v

# Regression — existing realized perf tests
pytest tests/core/test_realized*.py -x -q
pytest tests/ibkr/ -x -q

# Live verification (MCP)
# get_performance(mode="realized", source="ibkr_flex")
# Check: cash_anchor_mode="start_anchor", cash_anchor_observed_start_usd≈-11097,
#         cash_backsolve_start_usd≈-18750 (legacy value preserved),
#         TWR should be closer to IBKR's +0.29%
```

---

## Fix 4: Fee Double-Count Bug — HANDLED BY `FEE_SUBTOTAL_DEDUP_PLAN.md`

### Problem

The Flex CashTransaction section contains both individual fee line items
AND subtotal/aggregate rows. The normalizer ingests both, double-counting fees.

**Pattern observed in store** (35 fee flow events, total -$319):
```
2025-06-03  -$10.00  SNAPSHOTVALUENONPRO FOR JUN 2025    (individual)
2025-06-03   -$4.50  ABCOPRANP FOR JUN 2025               (individual)
2025-06-03  -$14.50  OTHER/FEES FOR JUN 2025              (subtotal = -10 + -4.50)
```

The subtotal row has a different description than the individual items. This means
grouping by `raw_description_prefix` alone would NOT detect the subtotal (it would
be in a separate group). The dedup must instead work at the **(date, account, currency)**
level — checking all fee rows on that date regardless of description.

This pattern repeats for most months. Impact: -$155 in extra fees
(engine -$319 vs IBKR statement -$164).

### Root Cause

The Flex XML CashTransaction section emits both detail rows and summary rows.
`normalize_flex_cash_rows()` in `ibkr/flex.py` does not distinguish between them.
All rows with a fee-like type get classified as `flow_type="fee"` and ingested
into the provider_flow_events table.

### Fix

**File:** `ibkr/flex.py` — `normalize_flex_cash_rows()`

**Preferred approach: `levelOfDetail` filter.** Before implementing any heuristic,
inspect the actual Flex XML for fee rows. IBKR Flex CashTransaction rows may include
a `levelOfDetail` attribute (values: `"DETAIL"`, `"SUMMARY"`, `"CURRENCY_SUMMARY"`).
If present, filter out `levelOfDetail != "DETAIL"` rows — this is definitive and
avoids all false-positive risks.

**File:** `ibkr/flex.py` — `normalize_flex_cash_rows()`

```python
# At the top of the normalization loop, skip non-detail rows:
level_of_detail = str(raw_row.get("levelOfDetail") or "DETAIL").strip().upper()
if level_of_detail != "DETAIL":
    continue  # skip SUMMARY / CURRENCY_SUMMARY subtotal rows
```

**Fallback (if `levelOfDetail` not available):** Group by `(date, account_id,
currency, raw_type)` — including `raw_type` to prevent false collapses across
different fee categories (e.g., ADVISORFEES vs FEES vs COMMADJ). The normalizer
at `flex.py:1117-1138` already distinguishes fee types, and a legitimate ADVISORFEES
row could equal FEES + COMMADJ amounts. Including `raw_type` in the key isolates
each fee category.

```python
def _remove_fee_subtotals(fee_rows: list[dict]) -> list[dict]:
    from collections import defaultdict

    def _group_key(row: dict) -> tuple:
        return (
            row.get("date"),
            row.get("account_id", ""),
            row.get("currency", "USD"),
            row.get("raw_type", ""),  # isolate fee categories
        )

    by_group = defaultdict(list)
    for row in fee_rows:
        by_group[_group_key(row)].append(row)

    keep = []
    for key, rows in by_group.items():
        if len(rows) < 3:
            keep.extend(rows)
            continue
        amounts = [r["amount"] for r in rows]
        excluded = set()
        for i, row in enumerate(rows):
            others_sum = sum(a for j, a in enumerate(amounts) if j != i and j not in excluded)
            if abs(row["amount"] - others_sum) < 0.01:
                excluded.add(i)
        keep.extend(r for i, r in enumerate(rows) if i not in excluded)
    return keep
```

**Implementation order:** Check `levelOfDetail` in the raw XML first. If present,
use the simple filter. Only fall back to the amount-matching heuristic if the XML
field is absent. The heuristic has known limitations (see tests) and is a last resort.

### Tests

1. `test_fee_subtotal_excluded` — 3 rows on same date where one = sum of others → subtotal removed
2. `test_fee_no_subtotal` — 2 rows on same date, neither is sum → both kept
3. `test_fee_single_row` — 1 row on a date → kept
4. `test_fee_net_total_matches_ibkr` — after dedup, total ≈ -$164 (IBKR statement)

---

## Fix 5: Minor Missing Items (Follow-up)

### 5a. HKD Margin Interest (-$9.44)

The Flex CashTransaction includes HKD interest charges. Two possible causes:

**Hypothesis A — Currency filter:** `normalize_flex_cash_income_trades()` may
skip non-USD rows. Check for explicit `currency == "USD"` filters in the
normalizer. If found, remove them — the cash replay already handles FX conversion.

**Hypothesis B — Flex normalizer cross-currency dedup (more likely):** The Flex
normalizer already has cross-currency dedup at `flex.py:794` that groups income rows
by `(date, symbol, type)` and keeps only the base-currency row when duplicates exist.
This is designed for legitimate cross-currency duplicates (IBKR sometimes reports the
same event in both base and local currency), but if HKD interest is a distinct charge
(not a duplicate of USD interest), this dedup incorrectly drops it.

**Investigation steps:**
1. Check `flex.py:794` cross-currency dedup — does it drop HKD MARGIN_INTEREST rows
   that share the same date as USD rows? The grouping key is `(date, symbol, type)`.
2. If so, the fix is to make the dedup smarter: only drop rows with the same USD
   equivalent amount (within tolerance), not all same-key rows.
3. Also check the transaction store upsert — `transaction_store.py:553`
   `store_normalized_income()` uses `ON CONFLICT (user_id, provider, transaction_id)`
   where `transaction_id` is a hash of `(income, provider, symbol, income_type, date,
   amount, account_id)` (line 577-584). Since amount differs between USD and HKD rows,
   this should NOT collide. The issue is upstream in the Flex normalizer.

**Fix:** Modify the cross-currency dedup to compare base-currency equivalents before
dropping. The current dedup (`flex.py:794`) stores raw native-currency amounts (e.g.,
USD -$3885 vs HKD -$30000 for the same event). Comparing raw amounts is meaningless
across currencies — true duplicates look wildly different in native amounts.

**Approach:** Extract `fxRateToBase` from the Flex CashTransaction XML and store it
in the normalized row dict. Then in the cross-currency dedup, compute
`amount * fxRateToBase` for each row and compare base-currency equivalents:

```python
# In normalize_flex_cash_income_trades(), add to the normalized dict:
"fx_rate_to_base": _parse_cash_amount(row.get("fxRateToBase"), default=None),

# In cross-currency dedup (flex.py:806-823), before dropping non-base rows:
# Check if the base-currency equivalent amounts are close (within $1).
# If yes → true duplicate, keep only base-currency row (existing behavior).
# If no → distinct charges, keep all rows.
base_amounts = {}
for row in grouped_rows:
    fx = row.get("fx_rate_to_base")
    if fx and fx != 0:
        base_amounts[id(row)] = abs(row["amount"] * fx)
    else:
        base_amounts[id(row)] = abs(row["amount"])  # assume base currency

# If all base amounts are within $1 of each other → true duplicates
unique_base = set(round(v, 0) for v in base_amounts.values())
if len(unique_base) <= 1:
    # True duplicates — keep only base-currency rows (existing behavior)
    if base_currency_rows:
        normalized.extend(base_currency_rows)
    else:
        # No base-currency row → keep ALL rows (preserve current behavior
        # from flex.py:822 — when no base-currency winner, all rows kept)
        normalized.extend(grouped_rows)
else:
    # Distinct charges — keep all
    normalized.extend(grouped_rows)
```

**If `fxRateToBase` is not available in CashTransaction:** Fall back to the existing
behavior (keep only base-currency rows). This preserves the current regression test
(`tests/ibkr/test_flex.py:888-899`) which expects USD+HKD duplicates to collapse.
The HKD interest fix becomes a follow-up pending Flex XML field investigation.

### 5b. UK Stamp Tax (-$11.04)

Transaction fees (regulatory taxes) may already be captured in the trade
`taxes` field. The Flex `Trade` element has a `taxes` attribute that the
normalizer may include in the trade cost basis.

**Investigation steps:**
1. Check `ibkr/flex.py` — does `normalize_flex_trades()` extract `taxes` from
   Trade rows? If yes, stamp tax is already included in the trade cost basis
   and the cash replay already accounts for it via the TRADE event outflow.
2. If NOT included in Trade rows, check the separate `TransactionTaxes` Flex
   section — this is a standalone report section with regulatory tax breakdowns.
3. If neither path captures it, options:
   - Add extraction from Flex TransactionTax section
   - Or accept as known gap (~$11/year for LSE trades)

### 5c. Cross-Provider Non-Trade Item Audit

Verified capture across all providers:

| Item | IBKR Flex | Schwab | Plaid | SnapTrade |
|------|-----------|--------|-------|-----------|
| Dividends | ✓ 33 events | ✓ 251 events | ✓ 33 events | ✓ |
| Interest | ✓ 13 (USD only) | ✓ 73 events | ✓ 16 events | ✓ |
| Fees | ✓ 35 (bug: dedup) | ✓ | Partial | Partial |
| Stamp Tax | ✗ | N/A | N/A | N/A |

All providers route income through `income_events` → `_income_with_currency()`
→ cash replay. Architecture is sound; data gaps are provider-specific.

---

## Expected Impact

| Fix | TWR Impact | NAV Impact |
|-----|-----------|-----------|
| Fix 3: Dual anchor | ~4.9pp | Inception NAV $18,358 → $22,371 |
| Fix 4: Fee dedup | ~0.7pp | +$155 over period |
| Fix 5: Minor items | ~0.1pp | -$20 over period |
| **Combined** | **~5.2pp** | **TWR → ~0.3% (vs IBKR 0.29%)** |

## Known Limitations

- **Consolidated statement cash is per-portfolio, not per-account (PRE-EXISTING):**
  The statement cash comes from `cash_report__all` (consolidated). The existing code
  (before this plan) already applies this consolidated value to account-scoped
  requests when `source="ibkr_flex"` — the `source == "ibkr_flex"` gate does not
  check `account`. This plan does NOT change that behavior. For multi-account setups,
  this is wrong, but it's a pre-existing issue. The `disable_statement_cash` param
  guards the multi-account aggregation fan-out (the only new multi-account path).
  **Our setup has 1 IBKR account — this limitation does not apply.**
- **End cash not forced to match:** The start-only anchor does not force the ending
  cash to match the statement. The ending cash drifts by the replay error. This is
  intentional — forcing endpoint match via residual distribution creates synthetic
  performance that distorts TWR.
- **Fee heuristic misses subtotal+unrelated:** See Fix 4 implementation note.
  The `levelOfDetail` approach is preferred if available in the Flex XML.
- **Pre-period drift:** The anchor is calibrated at the statement period start
  (April 1) but applied from inception (Feb 25). Cash for Feb 25-Mar 31 has ~5
  weeks of uncalibrated drift. This is much better than the current 12-month drift
  from the end-anchor approach.

## Priority

Fix 3 first (closes 95% of gap). Fix 4 next (fee accuracy). Fix 5 as follow-up.

## Data Points (Post-Fix 2b, Pre-Fix 3)

| Metric | Engine | IBKR Statement | Gap |
|--------|--------|---------------|-----|
| End cash | -$8,727 | -$8,727 | $0 |
| Start cash (back-solved) | -$18,750 | -$11,097 | $7,653 |
| Inception NAV | $18,358 | $22,284 | $3,926 |
| TWR | +5.52% | +0.29% | 5.2pp |
| Dividends (Apr+) | +$182.41 | +$182.41 | **$0** |
| Interest | -$276 | -$262 | -$14 (timing) |
| Fees | -$319 | -$164 | **-$155 (bug)** |
| Data coverage | 50% | — | — |

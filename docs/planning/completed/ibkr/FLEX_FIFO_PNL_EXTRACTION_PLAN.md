# Realized Performance: Extract fifoPnlRealized from Flex

**Date**: 2026-03-07
**Status**: Complete (commits `0a3b73fe`, `bd8cb895`)

## Context

Incomplete trades (exits without matching entries) currently contribute **zero**
to lot P&L. `_compute_realized_pnl_usd()` only iterates `closed_trades`, and
`_compute_unrealized_pnl_usd()` only iterates `open_lots`. The 19 incomplete
trades — which represent the majority of IBKR's actual trading activity in the
period — are invisible to lot P&L.

IBKR's Flex Trade XML provides `fifoPnlRealized` on every closing trade. This
is IBKR's own FIFO-matched P&L. For incomplete trades where we can't compute
P&L (no entry in our data window), we can use IBKR's number directly.

**Current lot P&L**: +$2,944 (only from closed trades our FIFO can match)
**IBKR actual**: -$7,978
**Gap**: +$10,922

The IBKR statement shows $3,691 in equity realized losses and $31,010 in
futures realized losses (mostly MHI). Futures are handled via cash replay
(fee_and_mtm), so the equity incomplete trades are the primary target.

## Architecture

Same 4-layer threading pattern as `broker_cost_basis` (commit `7e259a39`):

```
Flex XML → ibkr/flex.py → normalizer → FIFO matcher → realized perf engine
           (extract)      (pass-through)  (store on       (fold into
                                           IncompleteTrade) realized_pnl)
```

**Key design decisions**:

1. **Fold into `realized_pnl`** rather than adding a 4th lot P&L component.
   This preserves the invariant: `lot_pnl_usd = realized_pnl + unrealized_pnl
   + income_total`. The raw `incomplete_pnl` is a diagnostic metadata field.

2. **Drop `broker_pnl` on split exits**. The FIFO matcher can split a single
   exit into a `ClosedTrade` (matched portion) + `IncompleteTrade` (residual).
   The Flex `fifoPnlRealized` covers the FULL exit trade. Storing the full
   value on the incomplete fragment would double-count. Quantity pro-rating
   (`broker_pnl * residual/total`) is also wrong because IBKR's per-lot cost
   bases may differ from ours. The correct remainder (`broker_pnl -
   sum(closed_pnl)`) requires coupling FIFO matching with broker P&L, adding
   complexity for a rare edge case.

   **Solution**: When the incomplete quantity is less than the original trade
   quantity (split exit), set `broker_pnl = None`. The incomplete fragment
   contributes $0 to lot P&L. This is conservative (under-counts rather than
   double-counts) and safe because split exits on incomplete trades are rare
   — all 19 current IBKR incomplete trades are fully incomplete (first
   transaction is exit, zero matching lots).

## Fix 1: Extract `fifoPnlRealized` from Flex XML

**File**: `ibkr/flex.py:369-377`

After the existing `broker_cost_basis` extraction block, add `broker_pnl`:

```python
broker_cost_basis = None
broker_pnl = None
open_close = str(
    _get_attr(trade, "openCloseIndicator", "openClose", default="") or ""
).upper()
if trade_type in ("SELL", "COVER") and open_close != "O" and not is_futures:
    raw_cost = safe_float(_get_attr(trade, "cost"), 0.0)
    raw_qty = abs(safe_float(_get_attr(trade, "quantity", "qty"), 0.0))
    if abs(raw_cost) > 0 and raw_qty > 0:
        broker_cost_basis = abs(raw_cost) / raw_qty
    raw_pnl = safe_float(_get_attr(trade, "fifoPnlRealized"), 0.0)
    if raw_pnl != 0:
        broker_pnl = float(raw_pnl)
```

Then add to the normalized dict (line 396):

```python
"broker_cost_basis": broker_cost_basis,
"broker_pnl": broker_pnl,
```

**Why not futures**: Futures P&L is captured via cash replay (fee_and_mtm
policy). Including fifoPnlRealized for futures would double-count. The
`not is_futures` guard already exists from `broker_cost_basis`.

**Why safe**: Missing `fifoPnlRealized` → `_get_attr` returns `None` →
`safe_float(None, 0.0)` → `0.0` → no `broker_pnl` stored. Existing tests
unaffected because `_flex_trade()` helper doesn't include `fifoPnlRealized`.

**Tests** (in `tests/ibkr/test_flex.py`, after broker_cost_basis tests ~line 405):

1. `test_normalize_flex_trades_extracts_broker_pnl` — SELL with
   `fifoPnlRealized=-669.59` → `broker_pnl == -669.59`
2. `test_normalize_flex_trades_cover_broker_pnl` — COVER (BUY+C) with
   `fifoPnlRealized=-150.0` → `broker_pnl == -150.0`
3. `test_normalize_flex_trades_opening_trade_no_broker_pnl` — BUY with
   `openCloseIndicator="O"` → `broker_pnl is None`
4. `test_normalize_flex_trades_zero_pnl_no_broker_pnl` — SELL with
   `fifoPnlRealized=0` → `broker_pnl is None`
5. `test_normalize_flex_trades_futures_no_broker_pnl` — futures SELL →
   `broker_pnl is None` (guard against double-count)
6. `test_normalize_flex_trades_blank_open_close_broker_pnl` — SELL with
   blank `openCloseIndicator` and `fifoPnlRealized=-50.0` → `broker_pnl == -50.0`

## Fix 2: Thread through normalizer

**File**: `providers/normalizers/ibkr_flex.py:143`

Add to `fifo_transactions.append({...})`:

```python
"broker_pnl": txn.get("broker_pnl"),
```

**No test needed** — pass-through only.

## Fix 3: Store on IncompleteTrade (with split-exit guard)

**IMPORTANT**: There are TWO `IncompleteTrade(...)` construction sites, PLUS
the `_process_exit` path that creates incomplete trades from partial matches.
All must drop `broker_pnl` on split exits to avoid double-counting.

### 3a: IncompleteTrade dataclass

**File**: `trading_analysis/fifo_matcher.py:162`

Add field after `broker_cost_basis`:

```python
broker_cost_basis: Optional[float] = None
broker_pnl: Optional[float] = None       # ADD
```

### 3b: txn_meta dict

**File**: `trading_analysis/fifo_matcher.py:407-410`

Add to `txn_meta` dict:

```python
txn_meta = {
    "instrument_type": txn.get("instrument_type") or "equity",
    "contract_identity": txn.get("contract_identity"),
    "broker_cost_basis": txn.get("broker_cost_basis"),
    "broker_pnl": txn.get("broker_pnl"),              # ADD
}
```

### 3c: Inline IncompleteTrade constructor in `_process_exit` (line ~806-821)

**File**: `trading_analysis/fifo_matcher.py:806-821`

This is the primary path where split exits happen. At this point,
`quantity_to_close` is the RESIDUAL after partial FIFO matching. If any
lots were consumed (split exit), drop `broker_pnl` to avoid double-count:

```python
# Drop broker_pnl on split exits to avoid double-counting
full_broker_pnl = meta.get("broker_pnl")
original_qty = meta.get("_original_quantity", quantity)
# If residual < original, this is a split exit — drop broker_pnl
safe_broker_pnl = (
    full_broker_pnl
    if full_broker_pnl is not None and abs(quantity_to_close - original_qty) < 0.001
    else None
)

incomplete = IncompleteTrade(
    symbol=symbol,
    sell_date=date,
    sell_price=price,
    quantity=quantity_to_close,
    fee=(quantity_to_close / quantity) * fee if quantity > 0 else 0,
    source=source,
    transaction_id=transaction_id,
    currency=currency,
    direction=direction,
    broker_cost_basis=meta.get("broker_cost_basis"),
    broker_pnl=safe_broker_pnl,                         # ADD (None on split)
    instrument_type=meta.get("instrument_type") or "equity",
    multiplier=float(contract_identity.get("multiplier", 1.0) or 1.0),
    contract_quantity=_contract_qty(quantity_to_close, meta),
)
```

Store `_original_quantity` in txn_meta for the comparison:

```python
txn_meta = {
    "instrument_type": txn.get("instrument_type") or "equity",
    "contract_identity": txn.get("contract_identity"),
    "broker_cost_basis": txn.get("broker_cost_basis"),
    "broker_pnl": txn.get("broker_pnl"),
    "_original_quantity": abs(float(txn.get("quantity", 0))),  # ADD
}
```

### 3d: `_create_incomplete_trade()` helper (line ~871-903)

**File**: `trading_analysis/fifo_matcher.py:871-903`

This helper is called from MULTIPLE paths — both fully-incomplete exits AND
partial-match residuals (e.g., line 565 after `close_qty` was already FIFO-
matched at line 531). Apply the same split-exit guard:

```python
def _create_incomplete_trade(self, symbol, date, price, quantity, fee,
                              source, txn_id, currency, direction,
                              txn_meta=None):
    meta = txn_meta if isinstance(txn_meta, dict) else {}
    contract_identity = meta.get("contract_identity")
    if not isinstance(contract_identity, dict):
        contract_identity = {}

    # Drop broker_pnl on split exits to avoid double-counting
    full_broker_pnl = meta.get("broker_pnl")
    original_qty = meta.get("_original_quantity", quantity)
    safe_broker_pnl = (
        full_broker_pnl
        if full_broker_pnl is not None and abs(quantity - original_qty) < 0.001
        else None
    )

    incomplete = IncompleteTrade(
        ...
        broker_cost_basis=meta.get("broker_cost_basis"),
        broker_pnl=safe_broker_pnl,                     # ADD (None on split)
        ...
    )
    self.incomplete_trades.append(incomplete)
```

When the entire exit is incomplete (`quantity == original_qty`), the full
`broker_pnl` flows through. When it's a residual after partial FIFO
matching, `broker_pnl` is set to `None` (contributes $0 to lot P&L).
This is conservative — under-counts rather than double-counts.

**Tests** (in `tests/trading_analysis/test_instrument_tagging.py`, which has
existing FIFO wiring tests):

1. `test_incomplete_trade_carries_broker_pnl` — feed a SELL with
   `broker_pnl=-669.59` that has no prior BUY → `incomplete.broker_pnl == -669.59`
2. `test_incomplete_trade_drops_broker_pnl_on_split_exit` — BUY 60, then
   SELL 100 with `broker_pnl=-500` → ClosedTrade for 60 + IncompleteTrade
   for 40 with `broker_pnl is None` (dropped to avoid double-count)

## Fix 4: Fold into realized_pnl for lot P&L

### 4a: New computation function

**File**: `core/realized_performance/backfill.py` (after `_compute_realized_pnl_usd`)

```python
def _compute_incomplete_trade_pnl_usd(
    incomplete_trades: Iterable[Any],
    fx_cache: Dict[str, pd.Series],
) -> float:
    """Sum broker-reported P&L for incomplete trades (exits without entries).

    For IBKR Flex trades, this is the `fifoPnlRealized` value from the XML.
    For non-IBKR trades, broker_pnl is None and the trade contributes 0.
    Futures incomplete trades are skipped defensively (even though extraction
    already excludes them) to prevent double-counting with cash replay.
    """
    total = 0.0
    for trade in incomplete_trades:
        pnl = getattr(trade, "broker_pnl", None)
        if pnl is None:
            continue
        # Defensive: skip futures even if broker_pnl somehow set
        inst_type = str(getattr(trade, "instrument_type", "equity") or "equity").lower()
        if inst_type == "futures":
            continue
        currency = str(getattr(trade, "currency", "USD") or "USD").upper()
        trade_date = _helpers._to_datetime(getattr(trade, "sell_date", None))
        if trade_date is None:
            total += float(pnl)
            continue
        fx = fx_module._event_fx_rate(currency, trade_date, fx_cache)
        total += float(pnl) * fx
    return float(total)
```

### 4b: Engine integration — fold into realized_pnl

**File**: `core/realized_performance/engine.py:2301`

After existing `realized_pnl` computation:

```python
realized_pnl = float(backfill._compute_realized_pnl_usd(fifo_result.closed_trades, fx_cache))
incomplete_pnl = float(backfill._compute_incomplete_trade_pnl_usd(
    fifo_result.incomplete_trades, fx_cache
))
realized_pnl += incomplete_pnl   # Fold in to preserve lot decomposition invariant
```

**File**: `core/realized_performance/engine.py:2360`

`lot_pnl_usd` formula is UNCHANGED:

```python
lot_pnl_usd = float(realized_pnl + unrealized_pnl + income_total)
```

This works because `realized_pnl` now includes incomplete trade P&L.
The invariant `lot_pnl = realized + unrealized + income` is preserved.

### 4c: Metadata — add diagnostic field

**File**: `core/realized_performance/engine.py:2578`

Add `incomplete_pnl` to the metadata dict for transparency:

```python
"realized_pnl": round(realized_pnl, 2),
"incomplete_pnl": round(incomplete_pnl, 2),
```

Note: `realized_pnl` in metadata already includes `incomplete_pnl` (folded).
The separate `incomplete_pnl` field shows how much of `realized_pnl` came
from broker-reported incomplete trade P&L vs our FIFO matching.

### 4d: RealizedMetadata dataclass — declare field

**File**: `core/result_objects/realized_performance.py`

Add `incomplete_pnl` as a **defaulted field** in the `RealizedMetadata`
dataclass. Place it in the defaults section (after line 127, alongside
other `float = 0.0` fields like `cash_anchor_offset_usd`):

```python
incomplete_pnl: float = 0.0
```

**IMPORTANT**: Do NOT place it before non-default fields (`realized_pnl`,
`unrealized_pnl`, etc. at lines 96-97) — Python dataclasses require
non-default fields before default fields.

**File**: `core/result_objects/realized_performance.py:181` (in `to_dict`)

Add to the dict alongside other diagnostic fields:

```python
"incomplete_pnl": self.incomplete_pnl,
```

**File**: `core/result_objects/realized_performance.py:275` (in `from_dict`)

Add explicit parsing in the constructor call:

```python
incomplete_pnl=float(d.get("incomplete_pnl", 0.0) or 0.0),
```

### 4e: Aggregation — sum across scopes

**File**: `core/realized_performance/aggregation.py:967`

Add `incomplete_pnl` to the multi-scope aggregation:

```python
"incomplete_pnl": round(_sum_field("incomplete_pnl"), 2),
```

**Tests** (in `tests/core/test_realized_performance_analysis.py`):

1. `test_compute_incomplete_trade_pnl_usd_sums_broker_pnl` — two
   IncompleteTrades with `broker_pnl=-500, -200` → total `-700`
2. `test_compute_incomplete_trade_pnl_usd_skips_none` — IncompleteTrade
   with `broker_pnl=None` → total `0`
3. `test_compute_incomplete_trade_pnl_usd_fx_conversion` — IncompleteTrade
   with `broker_pnl=-100, currency="GBP"` → converted to USD
4. `test_compute_incomplete_trade_pnl_usd_skips_futures` — IncompleteTrade
   with `broker_pnl=-500, instrument_type="futures"` → total `0`

**Result object round-trip test** (in result_objects tests or inline):

5. `test_realized_metadata_incomplete_pnl_round_trip` — create
   `RealizedMetadata` with `incomplete_pnl=-700`, call `to_dict()` then
   `from_dict()` → verify `incomplete_pnl == -700`

## Expected Impact

With 19 incomplete equity closing trades contributing their IBKR
`fifoPnlRealized` (dropped on split exits for safety), the lot P&L should
shift significantly:

| Metric | Before | After (estimated) |
|--------|--------|--------------------|
| Lot P&L | +$2,944 | ~-$750 |
| Recon Gap | 21.2% | ~10% |
| Incomplete trade P&L | $0 | ~-$3,691 |
| realized_pnl | +$628 | ~-$3,063 |

Note: `realized_pnl` increases in magnitude because `incomplete_pnl` is
folded in. The `incomplete_pnl` diagnostic field shows the raw contribution.

The lot P&L won't match IBKR exactly because:
- Our closed trades P&L may differ from IBKR's (different FIFO lot matching)
- SLV exercise/assignment lot mismatch still exists (+$3,342 vs $0)
- FX timing differences on GBP-denominated trades

## Key Files

- `ibkr/flex.py:369-410` — extraction (Fix 1)
- `providers/normalizers/ibkr_flex.py:135-157` — pass-through (Fix 2)
- `trading_analysis/fifo_matcher.py:143-170` — IncompleteTrade dataclass (Fix 3a)
- `trading_analysis/fifo_matcher.py:407-410` — txn_meta dict (Fix 3b)
- `trading_analysis/fifo_matcher.py:799-821` — inline constructor in `_process_exit` with split-exit guard (Fix 3c)
- `trading_analysis/fifo_matcher.py:871-903` — `_create_incomplete_trade()` helper (Fix 3d)
- `core/realized_performance/backfill.py:278-321` — P&L computation (Fix 4a)
- `core/realized_performance/engine.py:2301, 2360, 2578` — lot P&L integration (Fix 4b-c)
- `core/result_objects/realized_performance.py:96+, 181, 275` — RealizedMetadata field (Fix 4d)
- `core/realized_performance/aggregation.py:967` — multi-scope sum (Fix 4e)

## Verification

### Unit tests
```bash
pytest tests/ibkr/test_flex.py -x -v -k "broker_pnl"
pytest tests/trading_analysis/test_instrument_tagging.py -x -v -k "broker_pnl"
pytest tests/core/test_realized_performance_analysis.py -x -v -k "incomplete_trade_pnl"
```

### Regression — existing tests must pass
```bash
pytest tests/ibkr/test_flex.py -x -v
pytest tests/trading_analysis/ -x -v
pytest tests/core/test_realized_performance_analysis.py -x -v
```

### Live test
```
get_performance(mode="realized", institution="ibkr", format="full", use_cache=False)
```
- `incomplete_pnl` should appear in `realized_metadata` (new diagnostic field)
- `realized_pnl` should be more negative (includes incomplete trade P&L)
- `lot_pnl_usd` should be significantly lower (closer to negative)
- `lot_pnl_usd == realized_pnl + unrealized_pnl + income_total` (invariant preserved)
- `reconciliation_gap_usd` should shrink
- NAV metrics should be UNCHANGED (this only affects lot P&L, not NAV)

## Not in Scope

- Using `fifoPnlRealized` for closed trades (our FIFO P&L is correct for those)
- Futures `fifoPnlRealized` (captured via cash replay, would double-count)
- SLV exercise/assignment lot reconciliation (separate issue)
- Non-IBKR providers (no equivalent field; `broker_pnl` stays None)

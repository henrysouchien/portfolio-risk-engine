# Fix: IBKR `get_orders` Returns EXECUTED with filled_quantity=0
**Status:** DONE

## Problem

`get_orders` returns `EXECUTED` status with `filled_quantity=0` and no fill price for GTC limit orders that were never filled. Cannot distinguish "submitted to IBKR" from "actually filled." Example: SLV #121 SELL 75 @ $74.50 GTC shows EXECUTED but market price never crossed the limit.

## Root Cause

**The root cause is in `ib_async`, not in our code.** The library's `wrapper.py:722-726` creates Trade objects for completed orders with zeroed-out fill data:

```python
# ib_async/wrapper.py:722-726
def completedOrder(self, contract, order, orderState):
    orderStatus = OrderStatus(orderId=order.orderId, status=orderState.status)
    trade = Trade(contract, order, orderStatus, [], [])
```

- `OrderStatus(orderId=..., status=...)` only sets `orderId` and `status`. `filled`, `remaining`, and `avgFillPrice` all default to `0.0`.
- `fills` list is always `[]` (empty) for completed orders.
- `log` list is always `[]` (empty) for completed orders.

However, the IBKR wire protocol DOES send fill data. The decoder at `ib_async/decoder.py:1334` parses `order.filledQuantity` from the wire. For filled orders, this contains the actual quantity. For cancelled orders, this is `0` or `UNSET_DOUBLE` (`sys.float_info.max`).

**Why SLV shows EXECUTED**: The raw `ibkr_status` from `trade.orderStatus.status` for completed orders comes from `orderState.status` on the wire. For cancelled GTC orders, IBKR Gateway may report `"Filled"` as the `orderState.status` even though fills are zero. (This is a known IBKR Gateway quirk — `completedOrder` callbacks merge filled and cancelled in the same stream, and status can be unreliable for orders that transitioned through multiple states.) Since `ibkr_to_common_status("Filled", 0.0, 0.0)` → `"EXECUTED"`, the SLV order shows EXECUTED with `filled_quantity=0`.

**Alternatively**, even if `ibkr_status="Cancelled"` (which correctly maps to CANCELED), the recovery probe at `trade_execution_service.py:2822` or the upsert path at line 3078 can overwrite a previously-correct status with EXECUTED from a different sync. The fix must handle both scenarios.

## Data Flow

```
IBKR Gateway wire protocol
  → ib_async.decoder.completedOrder()
    - st.status = "Filled" or "Cancelled"
    - o.filledQuantity = actual filled qty (from wire)
  → ib_async.wrapper.completedOrder()
    - Creates Trade with OrderStatus(filled=0.0, remaining=0.0)  ← BUG: ignores wire data
    - trade.fills = []  ← always empty for completed orders
  → IBKRBrokerAdapter._map_trade_to_status()
    - trade.orderStatus.filled = 0.0 (WRONG — zeroed by ib_async)
    - Fallback: _fill_data_from_trade(trade) → (0.0, None) because fills=[]
    - ibkr_to_common_status("Filled", 0.0, 0.0) → "EXECUTED"
  → Returns OrderStatus(status="EXECUTED", filled_quantity=0.0, execution_price=None)
  → TradeExecutionService._upsert_remote_order_statuses()
    - SET filled_quantity = COALESCE(0.0, filled_quantity) → overwrites with 0.0
    - SET order_status = "EXECUTED"
```

**Additional affected path**: `_run_ibkr_recovery_probe()` at `trade_execution_service.py:2782` also calls `ib.reqCompletedOrders()` and reads `trade.orderStatus.filled` directly (line 2826), producing the same zeroed data. This path writes to DB with the same `COALESCE` overwrite (line 2847).

Result: DB shows `order_status=EXECUTED, filled_quantity=0, average_fill_price=NULL`.

## Changes

### Fix 1: Read `order.filledQuantity` as second fallback + post-status override in `_map_trade_to_status()`

**File**: `brokerage/ibkr/adapter.py`

After the existing `_fill_data_from_trade` fallback (lines 1263-1269), add a second fallback using `trade.order.filledQuantity`:

```python
# Existing fallback (fills-based) at lines 1263-1269
if os_filled is not None and os_filled <= 0 and ibkr_status == "Filled":
    sec_type = getattr(trade.contract, "secType", "")
    if sec_type != "BAG":
        fill_filled, fill_avg_price = self._fill_data_from_trade(trade)
        if fill_filled > 0:
            filled = fill_filled
            execution_price = fill_avg_price

# NEW fallback: order.filledQuantity from IBKR completed order wire data.
# ib_async's reqCompletedOrders creates Trade objects with zeroed orderStatus
# fields and empty fills list, but order.filledQuantity IS parsed from wire.
# Include "ApiCancelled" alongside "Filled"/"Cancelled" — all are terminal
# completed-order statuses in IBKR_STATUS_MAP (adapter.py:57-59).
if filled <= 0 and ibkr_status in ("Filled", "Cancelled", "ApiCancelled"):
    sec_type = getattr(trade.contract, "secType", "")
    if sec_type != "BAG":
        order_filled_qty = _to_float(getattr(trade.order, "filledQuantity", None))
        if order_filled_qty is not None and 0 < order_filled_qty < _IBKR_MAX_FLOAT:
            filled = order_filled_qty
```

Also fix `remaining` which is zeroed for completed orders (used internally for status mapping, not exposed on `OrderStatus` dataclass):

```python
order_total_quantity = _to_float(getattr(trade.order, "totalQuantity", None)) or 0.0
if order_total_quantity <= 0 and filled > 0:
    order_total_quantity = filled

# Fix remaining for completed orders (ib_async defaults to 0.0)
if remaining <= 0 and filled > 0 and order_total_quantity > filled:
    remaining = order_total_quantity - filled
```

**Post-status override** — after `ibkr_to_common_status()` call at line 1290, override false-positive EXECUTED for non-BAG completed orders with no fill evidence:

```python
status = ibkr_to_common_status(ibkr_status, filled, remaining)

# Override false-positive EXECUTED: completed orders with "Filled" status
# but zero filled quantity are not actually filled.
# BAG orders excluded via secType guard — they legitimately show Filled+0
# at the combo level. Note: completed orders from reqCompletedOrders always
# have trade.fills=[] (ib_async passes empty fills), so we cannot rely on
# trade.fills for BAG safety — the secType check is the real guard.
if status == "EXECUTED" and filled <= 0:
    sec_type = getattr(trade.contract, "secType", "")
    if sec_type != "BAG":
        status = "CANCELED"
        portfolio_logger.warning(
            "IBKR order %s: Filled+0 with no fill evidence — overriding to CANCELED",
            trade.order.orderId,
        )
```

**Effect**: The SLV #121 example: `ibkr_status="Filled"`, `order.filledQuantity=0` (never filled) → fallback doesn't find fills → `filled=0` → `ibkr_to_common_status("Filled", 0, 0)` → "EXECUTED" → post-override: `EXECUTED and filled<=0 and secType!="BAG"` → **"CANCELED"**.

**BAG orders preserved**: Both the `order.filledQuantity` fallback and the post-status override are gated on `secType != "BAG"`. Completed BAG orders stay EXECUTED regardless of `trade.fills` contents.

### Fix 2: No change to `ibkr_to_common_status()`

`ibkr_to_common_status()` stays unchanged. It has no `secType` context, so adding a Filled+0 warning here would fire on every completed BAG order (which legitimately shows Filled+0). The warning is placed in `_map_trade_to_status()` (Fix 1's post-status override) where we have `secType` context.

### Fix 3: Prevent COALESCE regression on filled_quantity + fix recovery probe

**File**: `services/trade_execution_service.py`

**A) SQL only-increase guard** — In `_upsert_remote_order_statuses()`, `_reconcile_order_status()`, and `_run_ibkr_recovery_probe()`, change the filled_quantity update to only increase, never decrease:

```sql
-- Before:
filled_quantity = COALESCE(%s, filled_quantity),

-- After:
filled_quantity = CASE
    WHEN filled_quantity IS NULL THEN %s
    WHEN COALESCE(%s, 0) > COALESCE(filled_quantity, 0) THEN %s
    ELSE filled_quantity
END,
```

Note: The `filled_quantity IS NULL` branch allows first-write (NULL→0 for zero-fill cancels, NULL→N for fills). The `>` branch allows subsequent increases. Together they prevent positive→0 regression while permitting all legitimate transitions.

For `average_fill_price` — update when fills increase OR when the current price is NULL (allows late price backfills without requiring a quantity change):

```sql
-- Before:
average_fill_price = COALESCE(%s, average_fill_price),

-- After:
average_fill_price = CASE
    WHEN COALESCE(%s, 0) > COALESCE(filled_quantity, 0) THEN COALESCE(%s, average_fill_price)
    WHEN average_fill_price IS NULL THEN %s
    ELSE average_fill_price
END,
```

Also make `cancelled_at` idempotent at all sites — preserve first cancellation timestamp instead of updating on every sync:

```sql
-- Before (at all 4 sites):
cancelled_at = CASE WHEN %s = 'CANCELED' THEN NOW() ELSE cancelled_at END

-- After:
cancelled_at = CASE WHEN %s = 'CANCELED' THEN COALESCE(cancelled_at, NOW()) ELSE cancelled_at END
```

Apply to **all four** UPDATE sites:
1. `_upsert_remote_order_statuses` — brokerage_order_id match (line 3093)
2. `_upsert_remote_order_statuses` — perm_id fallback (line 3131)
3. `_reconcile_order_status` (line 2397)
4. `_run_ibkr_recovery_probe` (line 2847 — new clause, see Fix 3B)

**B) Recovery probe fill + status fix** — `_run_ibkr_recovery_probe()` at line 2782 reads `trade.orderStatus.filled` directly (line 2826) without going through `_map_trade_to_status()`. Apply the same `order.filledQuantity` fallback and post-status override.

Note: The service module already has its own `_to_float()` at line 3284. Add `import sys` and define `_IBKR_MAX_FLOAT = sys.float_info.max` at module level.

```python
import sys  # add to imports at top of file
_IBKR_MAX_FLOAT = sys.float_info.max  # add near other module-level constants

# ... inside _run_ibkr_recovery_probe, after matching:
raw_filled = _to_float(trade.orderStatus.filled if trade.orderStatus else None) or 0.0
ibkr_status_str = str(trade.orderStatus.status if trade.orderStatus else "PendingSubmit")

# Fallback to order.filledQuantity for completed orders (ib_async zeroes orderStatus)
if raw_filled <= 0 and ibkr_status_str in ("Filled", "Cancelled", "ApiCancelled"):
    sec_type = getattr(trade.contract, "secType", "")
    if sec_type != "BAG":
        order_filled_qty = _to_float(getattr(trade.order, "filledQuantity", None))
        if order_filled_qty is not None and 0 < order_filled_qty < _IBKR_MAX_FLOAT:
            raw_filled = order_filled_qty

# Compute remaining from totalQuantity (ib_async zeroes remaining for completed orders)
order_total_qty = _to_float(getattr(trade.order, "totalQuantity", None)) or 0.0
raw_remaining = max(order_total_qty - raw_filled, 0.0)

status = to_common_status(
    "ibkr", ibkr_status_str, filled=raw_filled, remaining=raw_remaining,
)

# Post-status override for false-positive EXECUTED (same logic as _map_trade_to_status)
if status == "EXECUTED" and raw_filled <= 0:
    sec_type = getattr(trade.contract, "secType", "")
    if sec_type != "BAG":
        status = "CANCELED"

# Guard zero avgFillPrice → None to prevent writing 0.0 as a real price
raw_fill_price = _to_float(trade.orderStatus.avgFillPrice if trade.orderStatus else None)
fill_price = raw_fill_price if raw_fill_price and raw_fill_price > 0 else None
```

Then pass `raw_filled`, `fill_price`, and `status` to the UPDATE parameters instead of the zeroed `trade.orderStatus` values.

Also add `cancelled_at` handling to the recovery probe's UPDATE — the existing UPDATE at line 2844 does not set `cancelled_at`, so if we now correctly set status=CANCELED, the timestamp should be recorded:

```sql
-- Add to the recovery probe UPDATE:
cancelled_at = CASE WHEN %s = 'CANCELED' THEN COALESCE(cancelled_at, NOW()) ELSE cancelled_at END
```

Pass `status` as the parameter for this clause.

### Fix 4: Add `order_filled_quantity` to broker_data

**File**: `brokerage/ibkr/adapter.py`

Include raw wire data in `broker_data` for diagnostics. Filter `UNSET_DOUBLE` sentinel to avoid storing `1.8e+308`:

```python
raw_order_filled = _to_float(getattr(trade.order, "filledQuantity", None))
if raw_order_filled is not None and raw_order_filled >= _IBKR_MAX_FLOAT:
    raw_order_filled = None

broker_data={
    "ibkr_status": ibkr_status,
    "order_filled_quantity": raw_order_filled,
},
```

## Edge Cases

- **BAG (combo) orders**: Excluded from both the `order.filledQuantity` fallback AND the post-status override via `secType != "BAG"` guard. Note: completed BAG orders from `reqCompletedOrders` also have `trade.fills=[]` (ib_async always passes empty fills for completed orders), so the `not trade.fills` check alone is NOT sufficient — the `secType != "BAG"` guard is the real safety net. Existing test at `test_ibkr_broker_adapter.py:192` uses populated fills (live trade scenario); a new test with `fills=[]` covers the completed-order BAG case.
- **Partial fill then cancel**: `ibkr_status="Cancelled"`, `order.filledQuantity=30`, `totalQuantity=75` → `filled=30` → `ibkr_to_common_status("Cancelled", 30, 45)` → "CANCELED". Fill data preserved.
- **ApiCancelled**: Treated same as `Cancelled` — both map to "CANCELED" via `IBKR_STATUS_MAP` (line 59). `order.filledQuantity` fallback applies to both.
- **`UNSET_DOUBLE` sentinel**: `order.filledQuantity` defaults to `sys.float_info.max`. Guard `0 < qty < _IBKR_MAX_FLOAT` filters this out.
- **Options/Futures**: Same treatment — `filledQuantity` is in contracts. No special handling.
- **avgFillPrice**: Not available from `order` object for completed orders. `execution_price` may be `None` for filled orders from `reqCompletedOrders`. This is an IBKR API limitation — Flex queries are the only source for historical fill prices. The `average_fill_price` SQL guard allows late NULL→value backfills when quantity is unchanged.
- **Recovery probe first-write**: `raw_filled` after fallback will be the true value (or 0 if no real fills). SQL NULL branch: `filled_quantity IS NULL THEN %s` → writes 0 (correct for zero-fill cancel) or N (correct for real fills). `fill_price` guarded to None when 0 → `average_fill_price IS NULL THEN NULL` → stays NULL.
- **`remaining` not on OrderStatus**: The `remaining` fix in Fix 1 is internal to `_map_trade_to_status()` — used only for `ibkr_to_common_status()` PARTIAL detection. The `OrderStatus` dataclass (`trade_objects.py:400`) does not expose a `remaining` field. Tests verify status and filled_quantity, not remaining directly.
- **SLV #121**: Raw `ibkr_status="Filled"`, `order.filledQuantity=0`. After Fix 1: filled=0, no fallback triggered. Post-status override: `EXECUTED and filled<=0 and secType!="BAG"` → **CANCELED**. Correct.

## Out of Scope

- **`total_cost` fallback** (`_to_float(remote.total_cost) or _to_float(remote.total_quantity)`): Pre-existing issue at `trade_execution_service.py:2405`, `3071`, `3335`, and initial INSERT sites at `950`, `1268`, `1553`. Can write share count as dollar amount. Not caused by or related to the completed-order zeroing bug — this is a separate data quality issue that predates these changes. Will address in a follow-up.
- **`_reconcile_order_status()` same-status updates**: This path only runs when `remote_status != local_status` (line 2375). Same-status updates (e.g., EXECUTED with updated fill price) are not handled by this path. This is a pre-existing limitation — the periodic sync via `_upsert_remote_order_statuses()` handles same-status fill updates. Not a regression from our changes.
- **Partial fill + stale "Filled" status**: If IBKR reports `ibkr_status="Filled"` for an order that was actually partially filled and then cancelled (e.g., `filledQuantity=30`, `totalQuantity=75`), our fix maps it to EXECUTED with `filled_quantity=30`. The post-status override only fires when `filled <= 0`, so this case is NOT caught. The correct status would be CANCELED or PARTIAL_CANCELED. However, `ib_async` discards `orderState.completedStatus` (which would distinguish "Filled" from "Cancelled") in `wrapper.completedOrder()`. Without `completedStatus`, we cannot reliably distinguish a fully-filled order from a partially-filled-then-cancelled order when `ibkr_status="Filled"`. `reqExecutions()` could provide fill data for recent orders but is not guaranteed for historical completed orders. This is a known limitation.
- **`cancel_order()` cancelled_at**: `cancel_order()` at line 2142 uses `cancelled_at = NOW()` for explicit user cancellations — this is intentional (records actual cancellation event). The idempotent `COALESCE(cancelled_at, NOW())` change only applies to sync paths that re-process the same order.
- **Recovery probe `filled_at`**: The recovery probe UPDATE at line 2844 has never set `filled_at`. Adding it would be an improvement but is a pre-existing gap, not caused by this fix. The other 3 UPDATE sites already handle `filled_at`.
- **Recovery probe `orderId=0`**: `reqCompletedOrders()` can return `orderId=0` for completed trades. The probe writes this as `brokerage_order_id="0"` — pre-existing issue, not introduced by this fix.
- **Recovery probe missing `perm_id`**: The recovery probe UPDATE has never stored `perm_id`. The uncertain-submission row (line 1664) also has no `perm_id`. This means the row may lack a durable reconciliation key — pre-existing gap.
- **Recovery probe secondary matcher `totalQuantity=0`**: `reqCompletedOrders()` can return `totalQuantity=0`, causing the secondary matcher (line 2807) to fail the quantity check. Pre-existing — our fix only adds fill/status handling to the probe, not matching logic.
- **PARTIAL_CANCELED passthrough**: Unrelated to IBKR completed order bug. `PARTIAL_CANCELED` is currently normalized to `CANCELED` via `SNAPTRADE_STATUS_MAP`. Introducing it as a new terminal status would require updating `cancelled_at` guards at 3 SQL sites.

## Files

| File | Change |
|------|--------|
| `brokerage/ibkr/adapter.py` | `_map_trade_to_status()`: add `order.filledQuantity` fallback for Filled/Cancelled/ApiCancelled, fix `remaining`, post-status override for EXECUTED+0 |
| `brokerage/ibkr/adapter.py` | `_map_trade_to_status()`: add `order_filled_quantity` to `broker_data` (sentinel-filtered) |
| `services/trade_execution_service.py` | `_upsert_remote_order_statuses()`: filled_quantity + average_fill_price only-increase guard (2 UPDATEs) |
| `services/trade_execution_service.py` | `_reconcile_order_status()`: same guard (1 UPDATE) |
| `services/trade_execution_service.py` | `_run_ibkr_recovery_probe()`: same SQL guard + order.filledQuantity fallback + post-status override + zero-price → None guard |
| `tests/services/test_ibkr_broker_adapter.py` | 7 new tests for completed order scenarios |
| `tests/services/test_trade_execution_service_order_sync.py` | 5 regression tests (upsert guard + recovery probe) |

## Tests

### Existing Tests — No Breakage

| Test | Why it still passes |
|------|-------------------|
| `test_map_trade_completed_bag_order_skips_fill_fallback` (line 192) | BAG orders excluded from `order.filledQuantity` fallback AND post-status override via `secType != "BAG"` guard. Status remains EXECUTED. |

### New Tests

| Test | What it verifies |
|------|-----------------|
| `test_map_trade_completed_order_uses_order_filled_quantity` | Filled+0 with `order.filledQuantity=75` → filled_quantity=75, status=EXECUTED (real fills found via fallback) |
| `test_map_trade_completed_filled_zero_no_fills_becomes_canceled` | Filled+0 with `order.filledQuantity=0`, `trade.fills=[]` → filled_quantity=0, status=CANCELED (post-status override) |
| `test_map_trade_completed_bag_order_with_empty_fills_stays_executed` | BAG + Filled+0 with `fills=[]` (completed-order scenario) → status=EXECUTED, filled_quantity=0, execution_price=None (secType guard prevents both fallback and override) |
| `test_map_trade_completed_cancelled_with_zero_fills` | Cancelled+0 with `order.filledQuantity=0` → filled_quantity=0, status=CANCELED |
| `test_map_trade_completed_cancelled_with_partial_fills` | Cancelled with `order.filledQuantity=30`, `totalQuantity=75` → filled_quantity=30, status=CANCELED |
| `test_map_trade_completed_order_unset_double_filtered` | `order.filledQuantity=sys.float_info.max` → filtered out, filled_quantity=0, broker_data["order_filled_quantity"]=None |
| `test_map_trade_completed_api_cancelled_with_partial_fills` | ApiCancelled with `order.filledQuantity=10`, non-BAG → filled_quantity=10, status=CANCELED |
| `test_upsert_does_not_overwrite_higher_filled_quantity` | DB has filled=75, remote returns filled=0 → DB retains 75 |
| `test_upsert_allows_null_to_zero_transition` | DB has filled=NULL, remote returns filled=0 → DB writes 0 (zero-fill cancel) |
| `test_upsert_allows_late_price_backfill` | DB has filled=75 + price=NULL, remote returns filled=75 + price=30.5 → DB updates price to 30.5 |
| `test_recovery_probe_completed_order_uses_order_filled_quantity` | Recovery probe with Filled+0 Trade, `order.filledQuantity=50` → DB gets filled=50, status=EXECUTED |
| `test_recovery_probe_completed_order_filled_zero_becomes_canceled` | Recovery probe with Filled+0 Trade, `order.filledQuantity=0`, `fills=[]` → DB gets status=CANCELED, cancelled_at set |

## Verification

1. `python3 -m pytest tests/services/test_ibkr_broker_adapter.py tests/services/test_trade_execution_service_order_sync.py -x -q`
2. Live: Place GTC limit order far from market → verify shows in `state="open"` as "ACCEPTED"
3. Live: Cancel from TWS → call `get_orders(state="cancelled")` → verify "CANCELED" with filled_quantity=0
4. Live: Place+fill market order → disconnect/reconnect → verify "EXECUTED" with correct filled_quantity
5. Check SLV #121 order after fix — should show "CANCELED" instead of "EXECUTED"

## Notes

- **avgFillPrice unavailable**: `reqCompletedOrders` does not populate fill prices. Filled orders from this API will have correct quantity but may lack `execution_price`. Historical fill prices can be obtained via Flex queries or `reqExecutions()` (for recent orders within the Gateway session).
- **ib_async library not modified**: The root cause is in `ib_async.wrapper.completedOrder()` which ignores `order.filledQuantity` when constructing the Trade. We work around it by reading `order.filledQuantity` directly. A PR to ib_async could fix this at the source.
- **`_IBKR_MAX_FLOAT`**: Already defined at `adapter.py:69` as `sys.float_info.max`. Used to detect IBKR's `UNSET_DOUBLE` sentinel values.

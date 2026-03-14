# Fix IBKR Completed Order Fill Data Bug

## Context
`get_orders` returns `EXECUTED` with `filled_quantity=0` and no fill price for IBKR orders that were actually filled (e.g., SLV #121). Root cause: `reqCompletedOrders` returns Trade objects with zeroed `orderStatus` fields (`filled=0`, `avgFillPrice=0`, `totalQuantity=0`), but the actual fill data is available in `trade.fills[].execution`. The adapter only reads from `orderStatus`.

### DB Evidence
SLV order #121 in local DB:
- `order_status: EXECUTED`, `filled_quantity: 0`, `average_fill_price: None`
- `brokerage_response`: `ibkr_status: "Filled"`, `brokerage_order_id: "0"`, `total_quantity: 0.0`, `filled_quantity: 0.0`, `execution_price: None`

### ib_async Execution Object Fields
- `execution.shares` — fill quantity per execution
- `execution.price` — fill price per execution
- `execution.avgPrice` — average execution price
- `execution.cumQty` — cumulative quantity

## Changes

### 1. Add `_fill_data_from_trade()` helper
**File:** `brokerage/ibkr/adapter.py` (insert before `_map_trade_to_status`, ~line 1222)

New private method that extracts `(filled_qty, weighted_avg_price)` from `trade.fills`:
- Iterates `trade.fills`, reads `fill.execution.shares` and `fill.execution.price`
- Sums quantities, computes volume-weighted average price: `sum(shares * price) / sum(shares)`
- Returns `(0.0, None)` when no fills present

### 2. Modify `_map_trade_to_status()` to use fills fallback
**File:** `brokerage/ibkr/adapter.py` (lines 1222-1262)

- Read `orderStatus` fields first as today (`os_filled`, `os_avg_price`, `os_remaining`)
- **Only fall back to fills when `orderStatus` looks zeroed:** `os_filled <= 0 AND ibkr_status == "Filled"` — this narrows the fallback to the specific `reqCompletedOrders` bug and does NOT change behavior for open trades
- **Skip BAG orders:** If `trade.contract.secType == "BAG"`, do NOT attempt fills fallback — BAG fills contain per-leg executions that can't be naively summed. Leave BAG completed orders with zeroed data (acceptable — combo orders are rare and this bug primarily affects simple stock/ETF orders)
- Call `_fill_data_from_trade()` only inside that condition (after BAG check)
- When `trade.order.totalQuantity == 0` but `filled > 0`, set `total_quantity = filled`
- Set BOTH `quantity` and `total_quantity` to the recovered value (keep consistent in returned `OrderStatus`)

**Safety:** Open trades are unaffected — fallback only triggers when status is "Filled" but `orderStatus.filled` is 0, which only happens for `reqCompletedOrders`.

### 3. Add tests
**File:** `tests/services/test_ibkr_broker_adapter.py`

Use `types.SimpleNamespace` mocks for Trade/OrderStatus/Fill/Execution objects. Test cases:

1. **Completed order, zeroed orderStatus, populated fills** → correct `filled_quantity`, `execution_price`, `status="EXECUTED"`
2. **Completed order, multiple partial fills** → correct weighted average price across fills
3. **Open order, no fills** → uses orderStatus fields (backward compat, no regression)
4. **Open order, partial fills + populated orderStatus** → uses orderStatus (NOT fills — fallback doesn't trigger)
5. **Completed order, `totalQuantity=0`** → recovers from fills, both `quantity` and `total_quantity` set correctly
6. **Completed BAG order** → fills fallback skipped, returns zeroed data (no crash, no double-count)
7. **`_fill_data_from_trade` with empty fills** → returns `(0.0, None)`
8. **`_fill_data_from_trade` with single fill** → returns exact values

### No migration needed
Existing stale DB rows self-heal on next `get_orders` call — `_upsert_remote_order_statuses` uses `COALESCE(%s, filled_quantity)` which will overwrite `0` with the corrected non-zero value. The perm_id fallback in the upsert matches completed orders (whose `brokerage_order_id` is "0") to local rows.

**Caveat:** Self-heal requires the local row to have `perm_id` stored. Rows inserted before perm_id was captured may not match. For SLV #121 specifically, `perm_id=1894311444` is present so it will self-heal.

## Key Files
| File | What | Lines |
|------|------|-------|
| `brokerage/ibkr/adapter.py` | `_map_trade_to_status()` — core bug | ~1222-1262 |
| `brokerage/ibkr/adapter.py` | `_commission_from_trade()` — existing fills iteration pattern | ~1264-1273 |
| `brokerage/ibkr/adapter.py` | `ibkr_to_common_status()` — status mapping (no changes needed) | ~82-88 |
| `brokerage/ibkr/adapter.py` | `get_orders()` — calls mapper for open + completed | ~1010-1061 |
| `brokerage/trade_objects.py` | `OrderStatus` dataclass (no changes needed) | ~400 |
| `services/trade_execution_service.py` | `_upsert_remote_order_statuses()` — self-heals (no changes needed) | ~3038 |
| `tests/services/test_ibkr_broker_adapter.py` | Tests to add | existing |

## What NOT to change
- `place_order()`, `execute_option_trade()`, `roll_position()` — use `orderStatus` after live placement where it IS populated
- `_upsert_remote_order_statuses()` — already correct once adapter returns correct values
- `ibkr_to_common_status()` — no changes needed; receives corrected `filled`/`remaining` values

## Verification
1. Run new tests: `cd risk_module && python -m pytest tests/services/test_ibkr_broker_adapter.py -v`
2. With IB Gateway running, call `get_orders(account_id="U2471778")` via MCP and confirm SLV #121 now shows correct fill quantity and price

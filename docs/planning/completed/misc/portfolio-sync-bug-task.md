# Fix Portfolio/Trade Sync Bug

## Context

Trades executed through the system (GLD hedge, SLV GTC, GOLD buy) aren't reflected in position counts. Orders show correct statuses (always fresh from broker), but positions are served from a 24h cache. The fix must be at the infrastructure level — no consumer should need to know to pass `force_refresh=True`.

**Four bugs found:**

1. **Position cache doesn't check for recent fills** — `_check_cache_freshness()` only checks time-based TTL (24h). If an order was filled 1 hour after the last cache sync, positions stay stale for the remaining 23 hours.
2. **IBKR completed orders lose data** — `ib.reqCompletedOrders()` returns orderId=0 and totalQuantity=0, so `_upsert_remote_order_statuses()` can't match them to local DB records.
3. **Zero-data ghost orders appear in output** — unmatched IBKR completed orders get appended as brokerage-sourced duplicates with quantity=0.
4. **IBKR cache invalidation is a no-op** — `_invalidate_positions_cache()` updates rows where `position_source='ibkr'`, but IBKR positions come via aggregators (SnapTrade/Plaid) per `POSITION_ROUTING` in `providers/routing_config.py:238-244`. The UPDATE matches zero rows.

---

## Fix 1: Smart cache invalidation in `_check_cache_freshness`

**File**: `services/position_service.py` — `_check_cache_freshness()` method (lines 672-704)

Currently this method only checks whether the position cache is older than `CACHE_HOURS` (24h). It has no awareness of trades that executed after the last sync.

**Change**: Two new checks, self-contained in `_check_cache_freshness()` with no callback wiring:

### 1a. Immediate invalidation on recent fills

After the existing TTL check obtains `last_sync` and `hours_ago`, query `trade_orders` for fills newer than the cache:

```python
# Check if any orders had fills after the cache was built (status-agnostic)
cursor.execute(
    """
    SELECT EXISTS(
        SELECT 1 FROM trade_orders
        WHERE user_id = %s
          AND filled_at > %s
          AND COALESCE(filled_quantity, 0) > 0
    ) AS has_newer_fills
    """,
    (user_id, last_sync),
)
result2 = cursor.fetchone()
if result2 and result2["has_newer_fills"]:
    portfolio_logger.info(
        f"🔄 {provider} cache invalidated: orders filled after last sync ({hours_ago:.1f}h ago)"
    )
    return False, hours_ago  # Force refresh
```

### 1b. Shorter TTL when active orders exist

If there are open orders (PENDING, ACCEPTED, PARTIAL, etc.), a fill could arrive at any time. Use a shorter TTL (2 hours) instead of the default 24h to ensure positions refresh frequently while orders are active:

```python
# If active orders exist, use shorter TTL
cursor.execute(
    """
    SELECT EXISTS(
        SELECT 1 FROM trade_orders
        WHERE user_id = %s
          AND order_status IN ('PENDING', 'ACCEPTED', 'PARTIAL', 'CANCEL_PENDING',
                               'QUEUED', 'TRIGGERED', 'ACTIVATED', 'PENDING_RISK_REVIEW',
                               'SUSPENDED', 'CONTINGENT_ORDER')
    ) AS has_active_orders
    """,
    (user_id,),
)
result3 = cursor.fetchone()
if result3 and result3["has_active_orders"]:
    cache_hours = min(cache_hours, 2)  # Shorten to 2h when orders are pending
    portfolio_logger.info(
        f"⏱️ {provider} using shortened TTL ({cache_hours}h) due to active orders"
    )
```

This replaces the callback approach entirely. No changes to `PositionService.__init__()`, no wiring needed. The `ACTIVE_ORDER_STATUSES` set is defined at `trade_execution_service.py:50-60` — import it rather than duplicating the literal values to prevent drift:

Use a lazy/local import inside the method body to avoid circular imports at module scope:

```python
def _check_cache_freshness(self, provider):
    from services.trade_execution_service import ACTIVE_ORDER_STATUSES
    ...
```

### 1c. Fix `filled_at` to also cover PARTIAL fills

**File**: `services/trade_execution_service.py`

Currently `filled_at` is only set when `order_status = 'EXECUTED'` (line 2732, line 2149). Partial fills also change positions but don't set `filled_at`.

Change the CASE expression in both `_upsert_remote_order_statuses()` (line 2732) and `_reconcile_order_status()` (line 2149):

```sql
-- Before:
filled_at = CASE WHEN %s = 'EXECUTED' THEN NOW() ELSE filled_at END

-- After (uses filled_quantity change detection, status-agnostic):
filled_at = CASE
    WHEN COALESCE(%s, 0) > 0 AND (
        filled_at IS NULL
        OR COALESCE(filled_quantity, 0) < COALESCE(%s, 0)
    ) THEN NOW()
    ELSE filled_at
END
```

Where both `%s` placeholders are the new `filled_quantity` value (same param bound twice). This is **status-agnostic** — it fires whenever `filled_quantity` increases, regardless of order status. This correctly handles:
- First fill (`filled_at IS NULL`)
- Partial fill growth (filled qty increases)
- PARTIAL→EXECUTED transitions (filled qty increases)
- PARTIAL_CANCELED with fills (SnapTrade maps this to CANCELED, but filled_qty > 0 still triggers)
- Repeated polls with same fill quantity (does NOT fire — no over-invalidation)

The parameter list for both `_upsert_remote_order_statuses()` and `_reconcile_order_status()` must pass `_to_float(remote.filled_quantity)` twice for the two `%s` placeholders in this CASE.

---

## Fix 2: IBKR completed order reconciliation

**Root cause**: IBKR's `ib.reqCompletedOrders()` API returns completed trade objects with `orderId=0` and `totalQuantity=0`. The system's reconciliation logic matches on `brokerage_order_id`, so "0" never matches the original order ID (e.g., "121").

### 2a. Add `perm_id` column to `trade_orders` with backfill

**File**: New migration `database/migrations/20260304_add_perm_id.sql`

```sql
-- Add perm_id column
ALTER TABLE trade_orders ADD COLUMN perm_id VARCHAR(255);
CREATE INDEX idx_trade_orders_perm_id ON trade_orders(perm_id) WHERE perm_id IS NOT NULL;

-- Backfill from brokerage_response JSON.
-- OrderResult.to_dict() stores perm_id under broker_data (initial placement):
UPDATE trade_orders
SET perm_id = brokerage_response->'broker_data'->>'perm_id'
WHERE brokerage_response->'broker_data'->>'perm_id' IS NOT NULL
  AND perm_id IS NULL;

-- OrderStatus.to_dict() stores perm_id at top level (status sync overwrites):
UPDATE trade_orders
SET perm_id = brokerage_response->>'perm_id'
WHERE brokerage_response->>'perm_id' IS NOT NULL
  AND perm_id IS NULL;
```

Two backfill paths because `brokerage_response` JSON has different shapes depending on what wrote it:
- `OrderResult.to_dict()` (from `place_order()`) nests `perm_id` under `broker_data` (`ibkr/adapter.py:1004`)
- `OrderStatus.to_dict()` (from `_upsert_remote_order_statuses()`) has `perm_id` at top level (`trade_objects.py:435`)

### 2b. Store `perm_id` on order creation

**File**: `services/trade_execution_service.py`

The IBKR adapter returns `OrderResult` from `place_order()`. `OrderResult` has no direct `perm_id` field, but stores it in `broker_data["perm_id"]` (`ibkr/adapter.py:1004-1005`).

In all three INSERT paths (`execute_order` line 1546, `execute_roll` line 951, `execute_multileg_option` line 1265):

1. Add `perm_id` to the INSERT column list and VALUES
2. Extract from `order_response.broker_data.get("perm_id")` if `broker_data` is not None

```python
# Extract perm_id from broker_data (IBKR stores it there)
perm_id = None
if order_response.broker_data:
    perm_id = order_response.broker_data.get("perm_id")

# In INSERT statement, add perm_id column + %s placeholder + perm_id param
```

### 2c. Fallback matching on `perm_id` in upsert + reconcile

**File**: `services/trade_execution_service.py`

**In `_upsert_remote_order_statuses()` (lines 2704-2749):**

After the existing UPDATE by `brokerage_order_id` (line 2722-2748), check `cursor.rowcount`. If 0 rows were updated AND `remote.perm_id` is set, retry with a second UPDATE matching on `perm_id` scoped to the same account:

```python
if cursor.rowcount == 0 and getattr(remote, 'perm_id', None):
    cursor.execute(
        """
        UPDATE trade_orders
        SET order_status = COALESCE(%s, order_status),
            filled_quantity = COALESCE(%s, filled_quantity),
            average_fill_price = COALESCE(%s, average_fill_price),
            total_cost = COALESCE(%s, total_cost),
            commission = COALESCE(%s, commission),
            brokerage_response = %s::jsonb,
            updated_at = NOW(),
            filled_at = CASE
                WHEN COALESCE(%s, 0) > 0 AND (
                    filled_at IS NULL
                    OR COALESCE(filled_quantity, 0) < COALESCE(%s, 0)
                ) THEN NOW()
                ELSE filled_at
            END,
            cancelled_at = CASE WHEN %s = 'CANCELED' THEN NOW() ELSE cancelled_at END
        WHERE user_id = %s AND account_id = %s AND perm_id = %s
        """,
        (
            status,                                                    # order_status
            _to_float(remote.filled_quantity),                         # filled_quantity
            _to_float(remote.execution_price),                         # average_fill_price
            _to_float(remote.total_cost) or _to_float(remote.total_quantity),  # total_cost
            _to_float(remote.commission),                              # commission
            json.dumps(remote.to_dict()),                              # brokerage_response
            _to_float(remote.filled_quantity),                         # filled_at CASE: new_filled_qty > 0 check
            _to_float(remote.filled_quantity),                         # filled_at CASE: filled_qty delta check
            status,                                                    # cancelled_at CASE
            self._get_user_id(),                                       # WHERE user_id
            account_id,                                                # WHERE account_id
            remote.perm_id,                                            # WHERE perm_id
        ),
    )
```

Note: `account_id` is included in the WHERE clause (passed as parameter to `_upsert_remote_order_statuses`) to prevent accidental cross-account updates.

**Self-heal `perm_id` on normal upserts**: In the *primary* UPDATE path (matching by `brokerage_order_id`, line 2722), also set `perm_id` if the remote has one and the local row doesn't yet:

```sql
perm_id = COALESCE(perm_id, %s)
```

This ensures rows that were created before the migration (or where initial `perm_id` capture was missed) self-heal on the next status sync without requiring the backfill migration.

**In `_reconcile_order_status()` (lines 2111-2118):**

After the `brokerage_order_id` match loop finds no match, add a fallback on `perm_id`:

```python
if not matching:
    local_perm_id = row.get("perm_id")
    if local_perm_id:
        for remote in remote_orders:
            if remote.perm_id and str(remote.perm_id) == str(local_perm_id):
                matching = remote
                break
```

### 2d. Filter zero-data brokerage duplicates + dedupe by `perm_id`

**File**: `services/trade_execution_service.py` (lines 1853-1862)

When building the merged order list, enhance deduplication:

```python
# Existing: collect local brokerage_order_ids
local_broker_ids = {
    str(r.get("brokerage_order_id"))
    for r in local_payload
    if r.get("brokerage_order_id")
}
# NEW: also collect local perm_ids for dedup
local_perm_ids = {
    str(r.get("perm_id"))
    for r in local_rows
    if r.get("perm_id")
}

for remote in remote_orders:
    remote_id = str(remote.brokerage_order_id or "")
    # Skip IBKR ghost orders with no useful data
    if remote_id == "0" and (_to_float(remote.quantity) or 0) == 0:
        continue
    # Dedupe by brokerage_order_id OR perm_id
    if remote_id and remote_id in local_broker_ids:
        continue
    if remote.perm_id and str(remote.perm_id) in local_perm_ids:
        continue
    local_payload.append(_map_remote_order_row(remote, provider=adapter.provider_name))
```

Note: ghost filter checks `quantity == 0` — legitimate external IBKR orders will have non-zero quantity and pass through. Only IBKR `reqCompletedOrders()` artifacts with zeroed-out fields are filtered.

---

## Fix 3: Fix IBKR cache invalidation provider mismatch

**File**: `services/trade_execution_service.py` — `_invalidate_positions_cache()` (lines 223-250)

Currently the IBKR branch updates rows where `position_source = 'ibkr'` and `account_id = %s`. But per `POSITION_ROUTING` in `providers/routing_config.py:238-244`, IBKR positions come via aggregators (SnapTrade/Plaid), not a direct `ibkr` source. The UPDATE matches zero rows.

**Fix**: For IBKR, invalidate ALL providers since IBKR positions could come from either SnapTrade or Plaid:

```python
if provider == "ibkr":
    # IBKR positions come via aggregators (snaptrade/plaid), not direct ibkr source.
    # Invalidate all providers to ensure the correct one gets refreshed.
    cursor.execute(
        """
        UPDATE positions
        SET created_at = NOW() - interval '2 days'
        WHERE user_id = %s
        """,
        (self._get_user_id(),),
    )
```

This broader invalidation only fires after a trade executes (rare event), so the cost of one extra refresh is negligible.

---

## Files Modified

| File | Change |
|------|--------|
| `services/position_service.py` | Smart cache: check `trade_orders` for fills newer than cache + shorter TTL when active orders exist |
| `database/migrations/20260304_add_perm_id.sql` | New: add `perm_id` column + dual-path backfill from `brokerage_response` JSON |
| `services/trade_execution_service.py` | (1) Store `perm_id` on order creation in all 3 INSERT paths; (2) fallback `perm_id` matching in `_upsert_remote_order_statuses()` and `_reconcile_order_status()`; (3) self-heal `perm_id` in primary upsert path; (4) filter zero-data ghost orders + `perm_id` dedup in `get_orders()`; (5) status-agnostic `filled_at` update using filled_quantity delta detection; (6) fix IBKR cache invalidation provider mismatch |

All paths relative to `risk_module/`.

---

## Verification

1. Run the DB migration — verify `perm_id` column exists and backfill populated existing IBKR orders from both JSON paths
2. Call `get_positions()` (no special params) after a recent fill → verify it auto-refreshes instead of returning stale cache
3. Call `get_positions()` when there are active orders → verify shorter TTL (2h) is used
4. Call `get_orders(account_id="U2471778")` → verify no ghost entries with qty=0 and id="0"
5. Place a test order via IBKR → verify `perm_id` is stored in `trade_orders` row
6. Simulate a completed IBKR order (orderId=0) → verify `perm_id` fallback matching updates the local order
7. Run analyst briefing → verify positions match current broker state
8. Verify SLV orders (#121, #133) reconcile correctly via `perm_id` after backfill
9. Verify `_invalidate_positions_cache()` for IBKR trades invalidates rows (check `cursor.rowcount > 0`)
10. Verify `filled_at` is set on first PARTIAL fill and not bumped on subsequent polls

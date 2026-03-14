# Plan: Auto-Populate Execution Result from Broker Data

## Context

When an agent executes a trade via `execute_trade()`, IBKR returns real fill data (price, quantity, commission). But when the agent then calls `update_action_status(status="executed")`, it manually constructs the `execution_result` dict — leading to errors like recording GLD at $245.30 (actually GOLD's price). The broker data already exists in `trade_orders`; we should use it as the source of truth.

## Approach

When `update_action_status(status="executed")` receives `linked_trade_ids`, look up the orders from `trade_orders` **before** the DB write and build `execution_result` from real broker data. The merged result is passed into the single `update_workflow_action_status()` call. Additionally, allow same-status `execution_result` enrichment so broker data can be backfilled if incomplete on the first call.

## Changes

### 1. Add bulk DB helper in `inputs/database_client.py`

- `get_trade_orders_by_ids(order_ids: list[str], user_id: int) -> list[dict]`
- Single query: `SELECT * FROM trade_orders WHERE id = ANY(%s) AND user_id = %s`
- Returns list of row dicts (empty list if none found)
- Keeps `audit.py` from importing `TradeExecutionService`

### 2. Allow same-status enrichment in `inputs/database_client.py`

- `update_workflow_action_status()` currently no-ops when current status == new status (idempotent guard at line ~1607)
- Add: when `current_status == new_status == "executed"` AND (`execution_result` is non-empty OR `linked_trade_ids` is provided):
  1. Read existing `execution_result` JSONB and existing `linked_trade_ids` from DB
  2. **Monotonic guard**: if existing `broker_verified` is already `true` AND the union trade set is unchanged (no new IDs added), skip the broker merge — existing authoritative data is preserved. Only agent-only keys from the new payload are added. But if the union set grew (new IDs), always re-verify the full set and update `trades`/`broker_verified` to reflect the new union, even if that means downgrading from `true` to `false`.
  3. Apply same strip logic as initial write: multi-order → always strip flat keys; single+verified → strip + apply; single+unverified → no strip, just add `trades`/`broker_verified`.
  5. Write the merged `execution_result`. Also update `linked_trade_ids`: union new IDs with existing IDs (deduplicated), so newly discovered IDs are always appended.
  6. No status change, no event emission.
- Gate: enter this path when EITHER `execution_result` is non-empty OR `linked_trade_ids` is provided. Both are optional but at least one must be present.
- This allows broker data to be backfilled on a retry without clobbering agent-authored keys, and correctly strips stale flat keys only when authoritative broker data replaces them. The monotonic guard prevents downgrade only when the trade set is unchanged; a grown union always triggers full re-verification (which may downgrade `broker_verified` if new orders lack fill evidence)

### 3. Add `_fetch_broker_execution_data()` helper in `mcp_tools/audit.py`

- Takes `linked_trade_ids: list[str]` and `user_id: int`
- Calls `DatabaseClient.get_trade_orders_by_ids()` in a single DB session
- For each found order, extracts: `ticker`, `side`, `filled_quantity`, `average_fill_price` (→ mapped to `fill_price`), `commission`, `order_status`, `brokerage_order_id`, `total_cost`
- **Fill-evidence gate** (not status-based): an order has authoritative fill data when `filled_quantity > 0` AND `average_fill_price` is not None/0. This catches partial fills under CANCELED orders and avoids trusting terminal-status rows with missing price data.
- `broker_verified: true` requires ALL linked orders found AND all have fill evidence (both `filled_quantity > 0` and `fill_price` present)
- Returns a dict:
  - `trades: list[dict]` — one entry per linked order (always a list)
  - `broker_verified: bool`
  - If single trade with fill evidence: also includes flat top-level fields for convenience
- Returns `None` if no trade IDs provided or all lookups fail
- Wraps in try/except — broker lookup failure should not block the status update

### 4. Modify `update_action_status()` in `mcp_tools/audit.py`

- **Before** the DB write, when `status == "executed"` and `linked_trade_ids` provided:
  - For same-status enrichment: read existing `linked_trade_ids` from DB, compute union with caller-provided IDs, fetch broker data for the **full union set**. This ensures `trades`, `broker_verified`, and `linked_trade_ids` all reflect the same complete set.
  - Call `_fetch_broker_execution_data()` with the union set
  - If broker data returned → merge into `execution_result`:
    - Define `BROKER_OWNED_KEYS = {"ticker", "side", "fill_price", "filled_quantity", "commission", "total_cost", "order_status", "brokerage_order_id"}`
    - **Multi-order (2+ linked trades, any verification status)**: ALWAYS strip `BROKER_OWNED_KEYS` from `execution_result` (flat top-level fields are ambiguous for multi-order). Apply `trades` + `broker_verified` only.
    - **Single-order, `broker_verified: true`**: Strip `BROKER_OWNED_KEYS`, then apply broker flat fields + `trades` + `broker_verified`.
    - **Single-order, `broker_verified: false`**: Do NOT strip — just ADD `trades` and `broker_verified: false`. Agent's original `ticker`/`fill_price` survive so `_check_fill_price()` can still validate them.
    - **Agent-owned keys** (everything NOT in `BROKER_OWNED_KEYS` and not `trades`/`broker_verified`): always preserved in both paths.
  - Pass the merged `execution_result` into the single `update_workflow_action_status()` call

**Top-level field contract by case:**
- **Single order with fill evidence**: flat broker fields (`ticker`, `fill_price`, etc.) populated at top level + `trades: [...]` + `broker_verified: true`
- **Single order WITHOUT fill evidence**: NO flat broker fields at top level (agent's original top-level fields survive for `_check_fill_price()`), `trades: [...]` with whatever data exists, `broker_verified: false`
- **Multiple orders, all with fill evidence**: NO flat top-level fields (ambiguous which ticker/price to show), `trades: [...]`, `broker_verified: true`, skip `_check_fill_price()`
- **Multiple orders, mixed fill evidence**: NO flat top-level fields, `trades: [...]`, `broker_verified: false`

**Price sanity check routing:**
- `broker_verified: true` → skip `_check_fill_price()`
- `broker_verified: false` AND top-level `fill_price` exists (agent-provided or single-order broker) → run `_check_fill_price()` + add warning about incomplete broker data
- No `linked_trade_ids` at all → existing `_check_fill_price()` path (unchanged)
- Broker lookup fails entirely → existing `_check_fill_price()` path + warning

### 5. Field naming convention

Use `fill_price` consistently in `execution_result` (matching existing audit convention). Map from DB column `average_fill_price` → `fill_price` in `_fetch_broker_execution_data()`.

`total_cost` may be a fallback value (service sometimes uses `total_quantity` when broker returns NULL). Include as informational but do NOT use it as a verification signal.

### 6. Response shape

When `broker_verified: true`:
```json
{
  "status": "success",
  "action_id": "...",
  "new_status": "executed",
  "execution_result": {
    "ticker": "GLD",
    "side": "BUY",
    "filled_quantity": 10.0,
    "fill_price": 476.24,
    "total_cost": 4762.40,
    "commission": 1.00,
    "order_status": "EXECUTED",
    "brokerage_order_id": "123456",
    "broker_verified": true,
    "trades": [{ ... }]
  }
}
```

When `broker_verified: false`:
```json
{
  "status": "success",
  "action_id": "...",
  "new_status": "executed",
  "execution_result": {
    "broker_verified": false,
    "trades": [{ ... }]
  },
  "warnings": ["Broker data incomplete — 0 of 1 linked orders have fill evidence."]
}
```

## Key Files

| File | Change |
|------|--------|
| `mcp_tools/audit.py` | `_fetch_broker_execution_data()` helper + pre-write merge in `update_action_status()` |
| `inputs/database_client.py` | `get_trade_orders_by_ids()` bulk query + same-status enrichment in `update_workflow_action_status()` |
| `tests/mcp_tools/test_audit.py` | Tests for broker-verified path, merge precedence, fallback to sanity check |

## Verification

1. **Broker-verified test**: Mock order with `filled_quantity > 0` and `average_fill_price` present → verify `broker_verified: true`, `_check_fill_price()` skipped
2. **Fallback test**: No `linked_trade_ids` → verify `_check_fill_price()` still fires
3. **Merge precedence test**: Agent provides `execution_result` with `ticker`/`notes` AND `linked_trade_ids` → broker wins for `ticker`/`fill_price`/`side`/etc., agent `notes` preserved
4. **Missing fill evidence test**: Linked order found but `average_fill_price` is None → `broker_verified: false`, `_check_fill_price()` runs, warning about incomplete data
5. **Partial resolution test**: 2 linked IDs, only 1 found → `broker_verified: false`, warning
6. **Canceled with fills test**: CANCELED order with `filled_quantity > 0` and valid `average_fill_price` → fill data IS used (fill-evidence gate, not status gate)
7. **Same-status enrichment test**: Call `update_action_status(status="executed")` twice with better broker data on second call → `execution_result` updated
8. **Same-status linked_trade_ids-only test**: Call `update_action_status(status="executed", linked_trade_ids=[...], execution_result=None)` on already-executed action → `linked_trade_ids` updated in DB
9. **Union growth re-verification test**: Action already executed with `linked_trade_ids=[A]` and `broker_verified: true`. Second call adds `[B]` where B lacks fill evidence → union `[A,B]` re-verified → `broker_verified` downgrades to `false`, `trades` reflects both A and B, `linked_trade_ids` is `[A,B]` — all three in sync
8. **DB failure test**: `get_trade_orders_by_ids` raises → falls through to sanity check with warning
9. **Live test**: Record action → accept → execute with `linked_trade_ids` from a real past order → verify broker data populates

# Stock Basket Phase 4: Multi-Leg Trade Execution

**Date**: 2026-02-27
**Status**: Complete (commit `7b3b78c2`)
**Depends on**: Phase 1 (CRUD, complete), Phase 2 (analysis, complete), Phase 3 (custom factor, complete)
**Risk**: Medium — composes existing single-leg trade infrastructure into multi-leg orchestration; no new DB tables

## Goal

Add two new MCP tools (`preview_basket_trade` and `execute_basket_trade`) that translate a named basket into a set of individual trade legs, preview them atomically, and execute them with best-effort semantics (partial fills tolerated).

## Design Decision: Lightweight Composition (No New DB Table)

Each basket trade decomposes into N individual `TradeExecutionService.preview_order()` / `execute_order()` calls. Each preview gets its own row in `trade_previews`; each execution in `trade_orders`. The basket grouping exists only in the MCP tool response (a list of preview_ids). No schema migration needed.

## Data Flow

```
preview_basket_trade(name, action="buy", total_value=10000)
    ↓
Load basket → _resolve_weights() → target weights per ticker
    ↓
_fetch_current_prices(tickers) → live prices from FMP profile
    ↓
_compute_buy_legs(weights, prices, total_value) → [(ticker, quantity), ...]
    ↓
TradeExecutionService.preview_order() per leg
    → each returns TradePreviewResult with preview_id
    ↓
BasketTradePreviewResult → snapshot + flags → MCP response
    (includes preview_ids list for execute step)
```

```
execute_basket_trade(preview_ids=[...])
    ↓
TradeExecutionService.execute_order(preview_id) per leg
    → best-effort: failures logged, execution continues
    ↓
BasketTradeExecutionResult → snapshot + flags → MCP response
    (status: completed / partial / failed / needs_confirmation)
```

## Implementation

### 1. Result objects: `core/result_objects/basket_trading.py` (NEW)

Four dataclasses following the `BasketAnalysisResult` pattern:

**`BasketTradeLeg`** — single leg of a preview
- Fields: `ticker, side, quantity, estimated_price, estimated_total, preview_id, pre_trade_weight, post_trade_weight, target_weight, status, error`
- `to_dict()` → serializable dict

**`BasketTradePreviewResult`** — aggregate preview
- Fields: `status, basket_name, action, preview_legs: List[BasketTradeLeg], total_estimated_cost, total_legs, buy_legs, sell_legs, skipped_legs, warnings, error`
- `get_agent_snapshot()` → compact dict with preview_ids list, legs summary, cost total
- `to_api_response()` → full serializable payload

**`BasketExecutionLeg`** — single leg of an execution
- Fields: `ticker, side, quantity, filled_quantity, average_fill_price, total_cost, order_status, brokerage_order_id, preview_id, error, new_preview_id: Optional[str]`
- `new_preview_id` is set when the preview expired and a new one was generated

**`BasketTradeExecutionResult`** — aggregate execution
- Fields: `status ("completed"/"partial"/"failed"/"needs_confirmation"), execution_legs: List[BasketExecutionLeg], reprieved_legs: List[BasketExecutionLeg], summary: Dict, warnings`
- `reprieved_legs`: legs where preview expired and a new preview was generated. These need user confirmation before re-execution.
- `get_agent_snapshot()` → status, filled/failed/reprieved counts, total_cost, legs summary, reprieved preview_ids
- `to_api_response()` → full payload

Re-export all four from `core/result_objects/__init__.py`.

### 2. Flags: `core/basket_trading_flags.py` (NEW)

**`generate_basket_trade_preview_flags(snapshot)`**:
- `preview_legs_failed` (error): N of M legs failed preview
- `legs_skipped` (warning): N legs skipped (quantity rounds to 0)
- `large_basket_order` (warning): total > $50k
- `all_legs_valid` (success): all legs passed
- `rebalance_summary` (info): N sells then M buys

**`generate_basket_trade_execution_flags(snapshot)`**:
- `basket_execution_failed` (error): all legs failed
- `basket_execution_partial` (warning): some legs failed
- `basket_execution_complete` (success): all legs executed

### 3. Core tool logic: `mcp_tools/basket_trading.py` (NEW)

**Helpers:**
- `_ensure_trading_enabled()` — checks `TRADING_ENABLED` setting
- `_fetch_current_prices(tickers, client)` → `(Dict[str, float], warnings)` via `FMPClient().fetch("profile", symbol=ticker, use_cache=False)`
- `_get_held_quantities(user, tickers)` → `Dict[str, float]` via `PositionService.get_all_positions(consolidate=True)`
- `_get_portfolio_total_value(user)` → `float` via PositionService
- `_get_position_values(user, tickers)` → `Dict[str, float]` current dollar values
- `_compute_buy_legs(weights, prices, total_value)` → `[(ticker, quantity), ...]`
- `_compute_sell_legs(weights, prices, held, total_value)` → `[(ticker, quantity), ...]`
- `_compute_rebalance_legs(weights, prices, position_values, portfolio_total)` → `[(ticker, side, quantity), ...]`

**`preview_basket_trade(name, action, total_value, account_id, format, user_email)`**:

Note: `order_type` is hardcoded to `"Market"` in Phase 4 and NOT exposed as a parameter. Limit/stop orders require per-ticker `limit_price`/`stop_price` which adds significant complexity — defer to a future enhancement.
1. Gate: `_ensure_trading_enabled()`
2. Resolve user + load basket from DB via `_resolve_user_and_id` + `get_factor_group`
3. Resolve weights via `_resolve_weights()`
4. Fetch live prices via `_fetch_current_prices()`
5. Compute legs based on action:
   - **buy**: `quantity = floor(weight × total_value / price)` per ticker
   - **sell**: `quantity = min(floor(weight × total_value / price), held_shares)` — if `total_value` is None, sell ALL held shares
   - **rebalance**: `delta = target_weight × portfolio_total - current_value` → BUY if positive, SELL if negative. Sell legs ordered first.
6. Call `TradeExecutionService(user).preview_order()` per leg
7. Build `BasketTradePreviewResult` with all preview_ids
8. If `format="agent"`: snapshot + flags

**`execute_basket_trade(preview_ids, format, user_email)`**:
1. Gate: `_ensure_trading_enabled()`
2. For each preview_id: `TradeExecutionService(user).execute_order(preview_id)`
3. **Expired preview handling**: `execute_order()` returns `new_preview` (a fresh `TradePreviewResult`) when a preview has expired (`trade_execution_service.py:831-848`). When this happens, add the leg to a `reprieved_legs` list with the new preview_id and set its status to `"reprieved"`. Include `reprieved_legs` in the response so the agent can present the new preview for user confirmation.
4. Best-effort: catch per-leg failures, continue
5. Aggregate into `BasketTradeExecutionResult`
6. Overall status logic based on `order_status` (not `status`), since `execute_order()` returns `status="success"` on submission before fills settle:
   - `"completed"`: all legs have `order_status` in `("EXECUTED", "ACCEPTED", "PENDING")`
   - `"partial"`: some legs succeeded, some failed or were reprieved
   - `"failed"`: all legs failed
   - `"needs_confirmation"`: all remaining legs were reprieved (expired previews)

### 4. Register tools: `mcp_server.py` (MODIFY)

Add imports (after line 64):
```python
from mcp_tools.basket_trading import preview_basket_trade as _preview_basket_trade
from mcp_tools.basket_trading import execute_basket_trade as _execute_basket_trade
```

Use `list[str]` (built-in generic, not `List`). Register two `@mcp.tool()` wrappers after the existing basket tools (~line 1261).

## Key Implementation Notes

- **`@handle_mcp_errors` decorator**: Both `preview_basket_trade` and `execute_basket_trade` MUST be decorated with `@handle_mcp_errors` from `mcp_tools/common.py`. This is the standard error envelope for all MCP tools.
- **Quantity rounding**: `math.floor()` for whole shares. Fractional shares not supported. Legs with quantity=0 are skipped with warning.
- **Price source**: `FMPClient().fetch("profile", use_cache=False)` for real-time prices. NOT `latest_price()` which uses monthly close data.
- **Missing/invalid prices**: `_fetch_current_prices()` skips tickers where price is `None`, `0`, or non-finite. The leg computation helpers (`_compute_buy_legs`, etc.) only iterate tickers present in the `prices` dict — tickers with missing prices are skipped and a warning is added.
- **`total_value` contract**: Required for `action="buy"` (raise `ValueError` if missing). Optional for `action="sell"` (None = sell all held shares). Ignored for `action="rebalance"` (uses portfolio total value).
- **Sell "all" mode**: `action="sell"` with `total_value=None` sells ALL held shares of each basket ticker. Use `math.floor()` on held quantities to handle fractional shares from positions — pass whole shares only. If held quantity is already whole (common for equities), `floor` is a no-op.
- **Empty positions**: If `action="sell"` or `action="rebalance"` and the user holds none of the basket tickers, return a success response with 0 legs, 0 cost, and a warning: "No positions found for any basket tickers". This is not an error — the portfolio may simply not hold those tickers.
- **Rebalance order**: Sell legs execute first (free up cash), then buy legs. Ordering is set at preview time.
- **Error isolation**: Each leg independently previewed/executed. One failure doesn't block others.
- **Existing validation**: Individual legs go through `TradeExecutionService.preview_order()` which runs buying power, concentration, and max order checks.
- **Trading gate**: Both tools check `TRADING_ENABLED` before proceeding.
- **Agent format**: Both tools support `format="agent"` with snapshot + interpretive flags.
- **Position loading and account scoping**: For sell/rebalance, positions MUST be scoped to the target `account_id`. Use `PositionService(user).get_all_positions(consolidate=False)` (import: `from services.position_service import PositionService`) and filter to `position["account_id"] == account_id` before computing sell quantities. Consolidated holdings span multiple accounts — a sell order targets a single account, so quantity must reflect that account's shares only. **`account_id` is required for sell and rebalance** — raise `ValueError("account_id is required for sell/rebalance actions")` if not provided. For buy, `account_id` is optional (TradeExecutionService resolves a default). For rebalance specifically, `_get_portfolio_total_value` and `_get_position_values` must ALSO be scoped to the same `account_id` — sum only positions matching that account. This ensures target_value = target_weight × account_total (not cross-account total).
- **DB access pattern**: Use `get_db_session()` context manager from `database` package + `DatabaseClient(conn)` — NOT bare `DatabaseClient()`.
- **Execution status semantics**: `execute_order()` returns `status="success"` on successful submission, but the order may not be filled yet. Use `order_status` field (`EXECUTED`, `ACCEPTED`, `PENDING`, `PARTIAL`, `REJECTED`, `CANCELED`) for actual fill state. The `new_preview` field on `TradeExecutionResult` (`trade_objects.py:183`) is set when a preview expired — handle this as a reprice event.
- **Classification precedence for execution legs**: Check `result.new_preview` first — if present AND `new_preview.status == "success"` AND `new_preview.preview_id` is not None, classify as `"reprieved"` and set `new_preview_id` on the execution leg. If `new_preview` is present but itself is an error (no valid preview_id), classify as `"failed"`. Then check `order_status` for fill state. Only fall back to `status` field as last resort.
- **Preview error legs exclusion**: `preview_order()` can return `status="error"` without a `preview_id` (`trade_execution_service.py:302`). The agent snapshot's `preview_ids` list MUST only include legs where `status="success"` and `preview_id` is not None. The `execute_basket_trade` tool should skip any preview_id that is None — never call `execute_order` for it.

## Reuse from existing code

- `mcp_tools/baskets.py:48` — `_resolve_user_and_id()` (user + DB ID resolution)
- `mcp_tools/baskets.py:393` — `_resolve_weights()` (weight resolution: equal/market_cap/custom)
- `mcp_tools/baskets.py:414` — `_serialize_basket()` (DB row → dict)
- `mcp_tools/trading.py:10` — `_ensure_trading_enabled()` pattern
- `services/trade_execution_service.py:260` — `preview_order()` (single-leg preview)
- `services/trade_execution_service.py:490` — `execute_order()` (single-leg execute)
- `services/position_service.py:265` — `get_all_positions()` (current holdings)
- `brokerage/trade_objects.py:71` — `TradePreviewResult` fields (preview_id, estimated_price, estimated_total, pre/post_trade_weight)
- `brokerage/trade_objects.py:162` — `TradeExecutionResult` fields (ticker, side, quantity, filled_quantity, order_status, brokerage_order_id)
- `core/result_objects/basket.py` — `BasketAnalysisResult` pattern for dataclass + `get_agent_snapshot()`
- `core/basket_flags.py` — flag generation pattern
- `mcp_tools/common.py` — `@handle_mcp_errors` decorator
- `utils/serialization.py` — `make_json_safe()`
- `database/__init__.py` — `get_db_session()` context manager (actual impl in `database/session.py`)
- `inputs/database_client.py:1890` — `get_factor_group(user_id, group_name)` (single basket lookup)

## Verification

1. `python3 -c "from mcp_tools.basket_trading import preview_basket_trade, execute_basket_trade"` — imports cleanly
2. `python3 -c "from core.result_objects import BasketTradePreviewResult, BasketTradeExecutionResult"` — imports cleanly
3. `python3 -c "from core.basket_trading_flags import generate_basket_trade_preview_flags"` — imports cleanly
4. **Buy preview**: `preview_basket_trade(name="test_api_group", action="buy", total_value=10000)` — returns preview_legs with preview_ids
5. **Sell all**: `preview_basket_trade(name="test_api_group", action="sell", account_id="<acct>")` — sells all held shares
6. **Rebalance**: `preview_basket_trade(name="test_api_group", action="rebalance", account_id="<acct>")` — shows sells first, then buys
7. **Agent format**: Both tools with `format="agent"` return snapshot + flags
8. **Trading disabled**: With `TRADING_ENABLED=false`, both tools return error
9. **Missing basket**: Non-existent basket name returns clean error
10. **Zero-quantity legs**: Small `total_value` where some legs round to 0 → skipped with warning

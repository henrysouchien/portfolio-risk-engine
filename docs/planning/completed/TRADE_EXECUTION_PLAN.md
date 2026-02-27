# Trade Execution via SnapTrade — Implementation Plan

> **Status:** All phases implemented. SnapTrade trading code is complete but **blocked by 403** (SnapTrade app-level trading permissions not approved). IBKR was added as an alternative — see `IBKR_TRADING_IMPLEMENTATION_PLAN.md`.

## Context

The portfolio-mcp system currently supports **read-only** position fetching from Schwab, Interactive Brokers, and BofA/Merrill Lynch via SnapTrade. The user wants to add **trade execution** capabilities so Claude can generate, preview, and (after user confirmation) submit orders through the same SnapTrade API. This is a "confirm then execute" model — no auto-trading.

## Architecture: Two-Tool Preview → Execute Pattern

```
User: "Buy 10 shares of AAPL in my Schwab account"
       │
       ▼
  preview_trade()
       │
       ├─ Validate inputs & resolve ticker on account
       ├─ Run pre-trade checks (buying power, concentration, risk limits)
       ├─ Call SnapTrade get_order_impact() → estimated fill, fees, buying power impact
       ├─ Compute portfolio risk impact (delta what-if)
       ├─ Store preview in DB (trade_previews table, 5-min expiry)
       └─ Return preview with preview_id
       │
       ▼
  Claude presents preview to user, user says "go ahead"
       │
       ▼
  execute_trade(preview_id)
       │
       ├─ Look up preview (scoped by user_id), check expiry
       │    ├─ If expired: return NEW preview with new preview_id (user must confirm again)
       │    └─ If valid: proceed
       ├─ Acquire row lock (SELECT ... FOR UPDATE on preview row)
       ├─ Call SnapTrade place_order(trade_id=snaptrade_trade_id)
       ├─ Record execution in DB (trade_orders table)
       ├─ Call refresh_brokerage_authorization() + invalidate position cache
       └─ Return fill confirmation
```

**Why two tools, not one:** Safety. The LLM cannot accidentally execute — it must present the preview first and get a separate explicit call to submit. The preview_id acts as a confirmation token.

**SnapTrade's built-in flow supports this:** `get_order_impact()` returns a `ManualTradeAndImpact` object with:
- `response.trade.id` — the trade ID for `place_order()`
- `response.trade_impacts` — list of `ManualTradeImpact` objects (fees, buying power effect per leg)
- `response.combined_remaining_balance` — remaining balance after trade

`place_order()` accepts the trade ID. We're mapping directly to their intended pattern.

**Expiry behavior:** If the SnapTrade `tradeId` has expired when `execute_trade` is called, we do NOT silently re-preview and execute. Instead, we return a **new preview** with a new `preview_id`, requiring the user to explicitly confirm again. This ensures the user always sees current pricing before execution.

## Pre-Requisite: Expose provider (Plaid vs SnapTrade) in position output — DONE

The `position_source` field (`"plaid"` or `"snaptrade"`) is now exposed in the MCP tool output:
- `by_account` format: `provider` at both account level and per-position
- `list` format: `provider` on each position entry
- `full` format: already passes through raw `position_source` field

## Implementation Phases

### Phase 1: Database — Trade tables ✅ DONE
**File:** `database/migrations/20260209_add_trade_tables.sql`

Two new tables:
- **`trade_previews`** — Stores preview state (order params, snaptrade_trade_id, expiry, validation results, risk impact). Keyed by UUID `preview_id`. Status: pending → executed | expired | cancelled.
- **`trade_orders`** — Audit trail for all executions (brokerage_order_id, fill details, commission, timestamps, error messages). Links back to preview via `preview_id` FK.

Both tables use the existing `users(id)` FK pattern with user isolation.

#### trade_previews schema

```sql
CREATE TABLE trade_previews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_id VARCHAR(100) NOT NULL,

    -- Order parameters (stored for re-preview if expired)
    ticker VARCHAR(100) NOT NULL,
    universal_symbol_id VARCHAR(255),       -- Resolved SnapTrade symbol ID (exact match, not substring)
    side VARCHAR(10) NOT NULL CHECK (side IN ('BUY', 'SELL')),
    quantity DECIMAL(20,8) NOT NULL CHECK (quantity > 0),
    order_type VARCHAR(20) NOT NULL CHECK (order_type IN ('Market', 'Limit', 'Stop', 'StopLimit')),
    limit_price DECIMAL(20,8),              -- Required when order_type IN ('Limit', 'StopLimit')
    stop_price DECIMAL(20,8),               -- Required when order_type IN ('Stop', 'StopLimit')
    time_in_force VARCHAR(10) NOT NULL DEFAULT 'Day' CHECK (time_in_force IN ('Day', 'GTC', 'FOK', 'IOC')),

    -- SnapTrade preview response (mapped from ManualTradeAndImpact)
    snaptrade_trade_id VARCHAR(255),        -- response.trade.id
    estimated_price DECIMAL(20,8),
    estimated_total DECIMAL(20,8),          -- Computed: price × quantity + commission
    estimated_commission DECIMAL(20,8),
    combined_remaining_balance JSONB,       -- response.combined_remaining_balance
    trade_impacts JSONB,                    -- response.trade_impacts (list of ManualTradeImpact)
    impact_response JSONB,                  -- Raw ManualTradeAndImpact for debugging

    -- Validation results
    validation_passed BOOLEAN NOT NULL DEFAULT TRUE,
    validation_warnings JSONB,

    -- Risk impact
    pre_trade_weight DECIMAL(8,6),
    post_trade_weight DECIMAL(8,6),

    -- Lifecycle
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'executed', 'expired', 'cancelled')),
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    executed_at TIMESTAMP
);

-- Indexes for common query patterns
CREATE INDEX idx_trade_previews_user_status ON trade_previews(user_id, status, expires_at);
CREATE INDEX idx_trade_previews_user_created ON trade_previews(user_id, created_at DESC);
```

#### trade_orders schema

```sql
CREATE TABLE trade_orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    preview_id UUID UNIQUE REFERENCES trade_previews(id),  -- UNIQUE: one execution per preview (idempotency)

    -- Order details
    account_id VARCHAR(100) NOT NULL,
    brokerage_name VARCHAR(100),
    ticker VARCHAR(100) NOT NULL,
    side VARCHAR(10) NOT NULL CHECK (side IN ('BUY', 'SELL')),
    quantity DECIMAL(20,8) NOT NULL CHECK (quantity > 0),
    order_type VARCHAR(20) NOT NULL CHECK (order_type IN ('Market', 'Limit', 'Stop', 'StopLimit')),
    limit_price DECIMAL(20,8),
    stop_price DECIMAL(20,8),
    time_in_force VARCHAR(10) NOT NULL DEFAULT 'Day' CHECK (time_in_force IN ('Day', 'GTC', 'FOK', 'IOC')),

    -- Brokerage response (status values match SnapTrade AccountOrderRecordStatus enum)
    brokerage_order_id VARCHAR(255),
    order_status VARCHAR(50),               -- SnapTrade enum: NONE | PENDING | ACCEPTED | FAILED | REJECTED | CANCELED | PARTIAL_CANCELED | CANCEL_PENDING | EXECUTED | PARTIAL | REPLACE_PENDING | REPLACED | STOPPED | SUSPENDED | EXPIRED | QUEUED | TRIGGERED | ACTIVATED | PENDING_RISK_REVIEW | CONTINGENT_ORDER
    filled_quantity DECIMAL(20,8),
    average_fill_price DECIMAL(20,8),
    total_cost DECIMAL(20,8),
    commission DECIMAL(20,8),
    brokerage_response JSONB,

    -- Timestamps
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    filled_at TIMESTAMP,
    cancelled_at TIMESTAMP,

    -- Error tracking
    error_message TEXT,
    retry_count INTEGER DEFAULT 0
);

-- Indexes for common query patterns
CREATE INDEX idx_trade_orders_user_created ON trade_orders(user_id, created_at DESC);
CREATE INDEX idx_trade_orders_status ON trade_orders(order_status) WHERE order_status IN ('PENDING', 'ACCEPTED', 'PARTIAL', 'CANCEL_PENDING', 'QUEUED', 'TRIGGERED', 'ACTIVATED', 'PENDING_RISK_REVIEW');
```

#### Concurrency & Idempotency

- **`preview_id UNIQUE`** on `trade_orders` ensures one execution per preview at the DB level.
- **`execute_order()`** acquires a row lock (`SELECT ... FOR UPDATE`) on the `trade_previews` row inside a transaction before checking status and inserting into `trade_orders`. This prevents race conditions from concurrent execute calls.
- **All queries scoped by `user_id`**: Every read/write on both tables filters by `(id, user_id)` to enforce user isolation, even though `preview_id` is a UUID.

### Phase 2: Settings — Trading config & kill switch ✅ DONE
**File:** `settings.py`

Add:
- `TRADING_ENABLED` env var (default: `false`) — **kill switch**. All trade tools return error unless explicitly enabled.
- `TRADING_DEFAULTS` dict:

```python
TRADING_ENABLED = os.getenv("TRADING_ENABLED", "false").lower() == "true"

TRADING_DEFAULTS = {
    "max_order_value": float(os.getenv("MAX_ORDER_VALUE", "100000")),
    "max_single_stock_weight_post_trade": 0.25,
    "preview_expiry_seconds": 300,           # 5 min (matches SnapTrade tradeId TTL)
    "default_time_in_force": "Day",
    "default_order_type": "Market",
    "log_all_previews": True,
    "log_all_executions": True,
}
```

### Phase 3: SnapTrade loader — Trading API functions ✅ DONE (code complete, blocked by 403)
**File:** `snaptrade_loader.py`

Add 5 retry-wrapped functions following the existing `@with_snaptrade_retry` pattern (line 1348):
- `_symbol_search_user_account_with_retry()` — Resolve ticker on a specific account. Returns list of matches; caller must filter for exact match.
- `_get_order_impact_with_retry()` — Preview order impact. Returns `ManualTradeAndImpact` (trade ID at `.trade.id`, impacts at `.trade_impacts`, remaining balance at `.combined_remaining_balance`).
- `_place_order_with_retry()` — Place a checked order using `client.trading.place_order(trade_id=...)`. Uses the trade ID from `get_order_impact`.
- `_get_user_account_orders_with_retry()` — List orders via `client.account_information.get_user_account_orders(...)` (NOT trading namespace).
- `_cancel_order_with_retry()` — Cancel open order via `client.trading.cancel_order(...)` (NOT the deprecated `cancel_user_account_order`).

**Note:** `place_force_order` is intentionally excluded from initial scope. It bypasses the impact check, which contradicts the mandatory preview flow. Can be added later behind an admin-only flag if needed for manual recovery.

Plus 5 high-level wrappers (matching the `fetch_snaptrade_holdings` pattern):
- `preview_snaptrade_order(user_email, account_id, ticker, ...)` — Returns parsed `ManualTradeAndImpact` with computed fields (estimated_total, commission)
- `place_snaptrade_checked_order(user_email, snaptrade_trade_id)` — Places order, returns fill details
- `get_snaptrade_orders(user_email, account_id, ...)` — Lists orders with status filtering
- `cancel_snaptrade_order(user_email, account_id, order_id)` — Cancels open order
- `search_snaptrade_symbol(user_email, account_id, ticker)` — Searches symbols, **requires exact ticker match**: filters `symbol_search_user_account` results to match `ticker.upper()` exactly against `symbol.symbol`. Returns the `universal_symbol_id` for use in order placement. If no exact match, returns error listing close matches for user disambiguation.

### Phase 4: Result objects ✅ DONE
**File:** `core/trade_objects.py` (new)

Following `core/result_objects.py` pattern with `to_api_response()` and `to_formatted_report()`:
- `PreTradeValidation` — validation results (is_valid, errors, warnings, buying_power, estimated_cost, post_trade_weight)
- `TradePreviewResult` — full preview response
- `TradeExecutionResult` — fill confirmation
- `OrderListResult` — order history

### Phase 5: Service layer ✅ DONE
**File:** `services/trade_execution_service.py` (new)

`TradeExecutionService(user_email)` with methods:
- `list_tradeable_accounts()` — List accounts that support trading (provider=snaptrade), with balances
- `preview_order(account_id, ticker, side, quantity, order_type, ...)` — Full pipeline: validate → resolve symbol → check buying power → get_order_impact → compute risk delta → store preview → return result
- `execute_order(preview_id)` — Look up preview **(scoped by user_id)** → acquire row lock → check expiry → place_order → log → refresh positions → return result. **If expired: returns a new preview, does NOT auto-execute.**
- `get_orders(account_id, state, days)` — Retrieve order history
- `cancel_order(account_id, order_id)` — Cancel open order
- `_validate_pre_trade(...)` — Input validation, buying power, position check (for sells), risk limits, concentration warning, order size sanity
- `_reconcile_order_status(order_id)` — Poll brokerage for order status updates; transition `trade_orders.order_status` to match SnapTrade's `AccountOrderRecordStatus` (e.g., PENDING → EXECUTED, PARTIAL, CANCELED, REJECTED, EXPIRED)

**User isolation:** All DB queries in this service filter by `(id, user_id)` — never by `id` alone.

#### Pre-Trade Validation Checks (in order)

1. **Input Validation**: Enforce `quantity > 0`, `limit_price` required when `order_type` is `Limit`/`StopLimit`, `stop_price` required when `order_type` is `Stop`/`StopLimit`, validate `time_in_force` and `order_type` are in allowed set, check fractional share support per brokerage
2. **Provider Check**: Verify account is connected via SnapTrade (not Plaid). Return clear error for Plaid-only accounts.
3. **Account Validation**: Verify account_id exists and is active for this user
4. **Symbol Validation**: Use `search_snaptrade_symbol` to resolve ticker — require exact match, persist `universal_symbol_id`. If no exact match, return close matches for disambiguation.
5. **Buying Power Check**: For BUY orders, check estimated cost vs available cash
6. **Position Check**: For SELL orders, verify user holds enough shares in the specified account
7. **Risk Limits Check**: Load user's risk limits from DB; compute post-trade weight; check against max_single_stock_weight
8. **Concentration Warning**: If post-trade weight > 10%, include warning (non-blocking)
9. **Order Size Sanity**: Reject if notional value exceeds max_order_value ($100K default)

#### Order Lifecycle & Reconciliation

Orders use SnapTrade's `AccountOrderRecordStatus` enum (20 values including `PENDING`, `ACCEPTED`, `EXECUTED`, `PARTIAL`, `CANCELED`, `REJECTED`, `FAILED`, `EXPIRED`, `QUEUED`, `TRIGGERED`, etc.). After `execute_order`:
- If the brokerage returns an immediate fill → record as `EXECUTED`
- If the brokerage returns `PENDING`/`ACCEPTED` → store status, poll on subsequent `get_orders` calls to update
- `get_orders` triggers a lightweight reconciliation: fetch current status from SnapTrade and update `trade_orders` if changed

#### Post-Execution Refresh

After successful order placement:
1. Call `client.connections.refresh_brokerage_authorization(authorization_id=...)` to trigger position sync
2. Invalidate position cache for the affected account
3. On next `get_positions` call, fresh data will be fetched

**`authorization_id` data flow:** SnapTrade accounts have an associated `brokerage_authorization` object. The existing `_list_user_accounts_with_retry()` helper (`snaptrade_loader.py:1421`) returns account records that include authorization metadata. The service layer will resolve `account_id` → `authorization_id` by calling `_list_user_accounts_with_retry()` and extracting the authorization from the account record. For the refresh call, we additionally need `list_brokerage_authorizations()` (via `client.connections.list_brokerage_authorizations()`). This account→authorization mapping should be cached in-memory (short TTL) since it rarely changes.

### Phase 6: MCP tools ✅ DONE
**File:** `mcp_tools/trading.py` (new)

4 tools following `mcp_tools/positions.py` pattern:
- `preview_trade(ticker, quantity, side, order_type, limit_price, stop_price, account_id, time_in_force)` — Returns preview with preview_id, estimated fill, fees, risk impact, validation
- `execute_trade(preview_id)` — Submits the order, returns fill details
- `get_orders(account_id, state, days, format)` — Order history
- `cancel_order(account_id, order_id)` — Cancel open order

### Phase 7: MCP server registration ✅ DONE
**File:** `mcp_server.py`

Add 4 `@mcp.tool()` wrappers delegating to `mcp_tools/trading.py`. Follow existing thin-wrapper pattern.

**File:** `mcp_tools/__init__.py` — Export new tools.

## Safety Design

| Guard | Description |
|-------|-------------|
| **Kill switch** | `TRADING_ENABLED=false` (default) blocks all trade tools |
| **Two-step flow** | Must preview before execute — no direct order placement |
| **Idempotent execution** | `preview_id UNIQUE` on `trade_orders` + row lock (`SELECT ... FOR UPDATE`) prevents double-order even under concurrent calls |
| **Expiry handling** | SnapTrade tradeId expires in 5 min. If expired, return a **new preview** requiring fresh user confirmation — never auto-execute on stale pricing |
| **Pre-trade validation** | Buying power, position check (sells), concentration warning (>10%), max order value ($100K), risk limits from DB |
| **Audit trail** | Every preview and execution logged to DB regardless of outcome |
| **Position refresh** | After execution, call `refresh_brokerage_authorization()` + invalidate position cache |
| **User isolation** | All DB queries scoped by `(id, user_id)` — never by `id` alone |

## Account Selection

When account_id is not specified:
- **One account**: Use it automatically
- **Multiple accounts**: Return error listing available accounts with balances, ask user to specify

## Tradeable Accounts

Only SnapTrade-connected accounts support trading. Plaid is read-only (positions/balances only) and has no order placement API.

| Account | Brokerage | Provider | Tradeable | Notes |
|---------|-----------|----------|-----------|-------|
| Schwab Individual | Schwab | snaptrade | Yes | Primary testing account |
| Schwab Rollover IRA | Schwab | snaptrade | Yes | |
| Schwab Contributory | Schwab | snaptrade | Yes | |
| U***1778 | Interactive Brokers | plaid | **No — needs SnapTrade reconnect** | Currently Plaid-only; reconnect via SnapTrade to enable trading |
| CMA-Edge | Merrill | plaid | **No — permanently read-only** | No Merrill trading API exists; Plaid is the only option |

**Testing plan:** Start with the 3 Schwab accounts (already on SnapTrade). IB can be added later by connecting it through SnapTrade.

**`preview_trade` behavior:** The tool checks the `provider` field (exposed via `get_positions`). If a user targets a Plaid-only account, return a clear error: "This account is connected via Plaid (read-only). Trading requires a SnapTrade connection."

## Error Handling

| Category | Example | Handling |
|----------|---------|----------|
| Validation errors | Insufficient buying power, ticker not found | Return in preview, block execution |
| SnapTrade API errors | 401/403 auth, 429 rate limit, 5xx | Use existing `with_snaptrade_retry` pattern |
| Preview expiry | User takes >5 min to confirm | Return new preview with new preview_id; user must confirm again |
| Brokerage rejection | Order rejected by Schwab/IB | Return brokerage error message, log to trade_orders |
| Partial fills | Market order partially fills | Return partial fill details, track in trade_orders |
| Duplicate orders | Rapid double-call scenario | Track preview_id status; reject if already executed |

## Key Files (Existing, for Reference)

| File | Why |
|------|-----|
| `snaptrade_loader.py:1348` | `with_snaptrade_retry` decorator pattern to follow |
| `mcp_tools/positions.py` | MCP tool implementation pattern |
| `services/position_service.py` | Service class pattern (user_email init, provider integration) |
| `core/result_objects.py` | Result object pattern (to_api_response, to_formatted_report) |
| `mcp_server.py` | Tool registration pattern (@mcp.tool() thin wrappers) |
| `database/schema.sql` | DB schema patterns (user FK, JSONB, indexing) |
| `settings.py:401-446` | Already has trading capability flags in brokerage metadata |

## Verification

1. **Unit tests**: Validate pre-trade checks, expiry handling, idempotent execution, input validation — ⬜ TODO
2. **Integration tests**: Mock SnapTrade API responses, verify full preview → execute flow, DB records — ⬜ TODO
3. **Safety tests**: Verify kill switch blocks trades, expired previews are handled, duplicate execution returns existing result — ⬜ TODO
4. **Manual E2E**: ✅ DONE (via IBKR) — BUY 1 AAPL Market → execute → cancel on IBKR account U2471778. SnapTrade E2E blocked by 403.

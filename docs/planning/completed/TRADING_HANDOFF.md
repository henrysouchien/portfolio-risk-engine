# Trading System — Handoff Document

**Date:** 2026-02-09
**Status:** Core implementation complete, live-tested on IBKR. MCP tool integration needs testing.

---

## What Was Built

A two-step **preview → execute** trade execution system supporting two broker backends (IBKR and SnapTrade) behind a common `BrokerAdapter` ABC. The MCP tools (`preview_trade`, `execute_trade`, `get_orders`, `cancel_order`) are broker-agnostic — account routing determines which adapter handles the request.

### Architecture

```
MCP Tool (preview_trade / execute_trade / get_orders / cancel_order)
    │
    ▼
TradeExecutionService  (orchestrator, broker-agnostic)
    │
    ├── _resolve_broker_adapter(account_id) → BrokerAdapter
    │
    ├── BrokerAdapter (ABC)
    │       ├── SnapTradeBrokerAdapter  →  snaptrade_loader.py
    │       └── IBKRBrokerAdapter       →  ib_async → TWS (port 7496)
    │
    ├── Pre-trade validation (shared)
    ├── DB persistence (trade_previews / trade_orders)
    └── Post-trade refresh
```

### Key Design Decisions

- **Two-step flow**: Preview returns a `preview_id`; execute requires that ID. No direct order placement.
- **Idempotent execution**: `preview_id UNIQUE` on `trade_orders` + row lock prevents double-orders.
- **Preview expiry**: 5-minute TTL. If expired but within 15 min, auto re-preview. Beyond 15 min, reject.
- **Kill switch**: `TRADING_ENABLED=false` (default) blocks all trade tools.
- **IBKR lazy connection**: TWS connection established on first IBKR trade, not at server startup.

---

## File Map

### New Files (Trading System)

| File | Purpose |
|------|---------|
| `services/broker_adapter.py` | Abstract `BrokerAdapter` ABC |
| `services/ibkr_broker_adapter.py` | IBKR adapter (557 lines). `ib_async` integration: `qualifyContracts`, `whatIfOrder`, `placeOrder`, `cancelOrder` |
| `services/ibkr_connection_manager.py` | Singleton managing persistent TCP socket to TWS. `threading.RLock()`, auto-reconnect |
| `services/snaptrade_broker_adapter.py` | SnapTrade adapter wrapping existing `snaptrade_loader.py` functions |
| `services/trade_execution_service.py` | Orchestrator: validation, DB persistence, broker routing, risk impact |
| `core/trade_objects.py` | Result objects: `TradePreviewResult`, `TradeExecutionResult`, `PreTradeValidation`, `OrderListResult` |
| `mcp_tools/trading.py` | 4 MCP tool implementations: `preview_trade`, `execute_trade`, `get_orders`, `cancel_order` |
| `database/migrations/20260209_add_trade_tables.sql` | Creates `trade_previews` and `trade_orders` tables |
| `database/migrations/20260210_add_broker_provider.sql` | Adds `broker_provider` columns, normalizes statuses, adds CHECK constraint |

### Modified Files

| File | Changes |
|------|---------|
| `settings.py` | Added `TRADING_ENABLED`, `TRADING_DEFAULTS`, `IBKR_ENABLED`, `IBKR_GATEWAY_*`, `IBKR_CLIENT_ID`, `IBKR_AUTHORIZED_ACCOUNTS` |
| `mcp_server.py` | Registered 4 trading tools. Added `load_dotenv(override=True)` so `.env` values take precedence |
| `mcp_tools/__init__.py` | Exports trading tools |
| `snaptrade_loader.py` | Added trading API functions (symbol search, order impact, place order, get orders, cancel order) |

---

## Configuration

### .env (current production values)

```bash
TRADING_ENABLED=true
IBKR_ENABLED=true
IBKR_GATEWAY_HOST=127.0.0.1
IBKR_GATEWAY_PORT=7496        # TWS live (not IB Gateway)
IBKR_CLIENT_ID=20             # Dedicated for MCP server
IBKR_TIMEOUT=10
IBKR_READONLY=false
IBKR_AUTHORIZED_ACCOUNTS=U2471778
```

### .claude.json MCP config

Only passes `RISK_MODULE_USER_EMAIL=hc@henrychien.com`. All other env vars come from `.env` via `load_dotenv(override=True)` in `mcp_server.py`. User explicitly wants IBKR vars in `.env` only, NOT in `.claude.json`.

---

## Database

Both migrations applied to `risk_module_db`:

- **`trade_previews`**: UUID PK, stores order params, broker preview data, validation results, expiry. Status: `pending` → `executed` | `expired` | `cancelled`.
- **`trade_orders`**: UUID PK, FK to preview. Stores fill details, commission, brokerage order ID. Status uses common enum: `PENDING`, `ACCEPTED`, `EXECUTED`, `PARTIAL`, `CANCELED`, `REJECTED`, `FAILED`, `EXPIRED`, `CANCEL_PENDING`.
- Both tables have `broker_provider` column (`snaptrade` or `ibkr`).
- Both tables scoped by `user_id` for isolation.

---

## What Works

### IBKR (via direct python3) — Fully tested
- Connect to TWS on port 7496, account U2471778
- `list_tradeable_accounts()` — returns 4 accounts (3 SnapTrade + 1 IBKR)
- `preview_order()` — BUY/SELL, Market/Limit orders
- `execute_order()` — placed BUY 1 AAPL Market (order ID 17, PENDING — markets closed)
- `cancel_order()` — cancelled successfully
- `get_orders()` — retrieves open and completed orders
- DB records verified (trade_previews + trade_orders)
- Pre-trade validation: SELL rejection when no position held

### SnapTrade — Code complete, blocked
- All trading functions implemented in `snaptrade_loader.py`
- `SnapTradeBrokerAdapter` wraps them behind the ABC
- **Blocked by SnapTrade 403 (code 1020)** — app-level trading permissions not approved
- Waiting on SnapTrade support

---

## What Doesn't Work Yet

### 1. MCP Tools + IBKR (highest priority)

The MCP tools (`preview_trade`, `execute_trade`) are registered in `mcp_server.py` but **have not been successfully tested with IBKR accounts**. The issue was TWS client ID conflicts:

- The MCP server process (spawned by Claude Code) connects to TWS with `IBKR_CLIENT_ID=20`
- Direct python3 test scripts also tried to connect with the same client ID
- TWS only allows one connection per client ID
- Client ID is now set to 20 in `.env`, dedicated for the MCP server

**To test:** Just call `preview_trade(ticker="AAPL", quantity=1, side="BUY", order_type="Market", account_id="U2471778")` through the MCP tool. If TWS is running and no other process holds client ID 20, it should work.

**If it fails with connection error:** Check for stale `mcp_server.py` processes (`ps aux | grep mcp_server`). The MCP server process doesn't restart on `/mcp` reconnect — it must be killed for env changes to take effect.

### 2. Timezone Bug (FIXED but worth knowing)

`trade_previews.expires_at` is `TIMESTAMP WITHOUT TIME ZONE`. The fix uses `datetime.now()` (naive local time) for both storage and comparison. Do NOT use `datetime.now(timezone.utc)` — psycopg2 converts tz-aware datetimes to local time before storing in naive columns, causing a timezone offset on read-back.

### 3. Known IBKR Quirks

- **`whatIfOrder()` doesn't return fill price for market orders** — the adapter requests a brief market data snapshot for price estimation. Outside trading hours, estimated price may be `None`.
- **`ib_async` sync mode** — all calls block the thread. Matches the MCP server's synchronous pattern but watch for timeouts.
- **TWS daily restart** — TWS restarts around 11:45 PM ET. Connection will drop and auto-reconnect should fire.
- **Weekly 2FA** — TWS requires re-authentication once per week (Sunday maintenance). Must approve IBKR Mobile notification.

---

## Remaining Work

### Must Do
- [ ] **Test MCP tools with IBKR** — verify `preview_trade` → `execute_trade` → `cancel_order` works through MCP
- [ ] **Test during market hours** — verify EXECUTED status and actual fill price for a market order

### Should Do
- [ ] **Automated tests** — unit tests for pre-trade validation, expiry handling, idempotent execution
- [ ] **Phase 8 safety hardening** — connection drop recovery probe, weekly 2FA error handling
- [ ] **Market hours live fill** — execute a small market order during trading hours to verify fill flow

### Blocked
- [ ] **SnapTrade trading** — waiting on SnapTrade support for app-level permissions (403 code 1020)

### Future
- [ ] **Trade tracking** — separate feature for transaction history, FIFO lot matching, P&L (see `docs/planning/TRADE_TRACKING_PLAN.md`)

---

## Completed Plan Docs

All in `docs/planning/completed/`:
- `TRADE_EXECUTION_PLAN.md` — Original SnapTrade-only plan, all phases marked done
- `IBKR_TRADING_IMPLEMENTATION_PLAN.md` — IBKR adapter plan, all phases marked done, test checklist partially checked
- `IBKR_TRADING_INTEGRATION_RESEARCH.md` — Research on ib_async vs ibind, TWS API, IB Gateway

## Common Order Status Enum

Both brokers map to this vocabulary (stored in `trade_orders.order_status`):

| Status | Meaning |
|--------|---------|
| PENDING | Submitted, awaiting broker ack |
| ACCEPTED | Broker acknowledged, working |
| EXECUTED | Fully filled |
| PARTIAL | Partially filled |
| CANCELED | Cancelled |
| REJECTED | Rejected by broker |
| FAILED | System-level failure |
| EXPIRED | Order expired |
| CANCEL_PENDING | Cancel request submitted |

---

## Quick Test Commands

```bash
# Test IBKR adapter directly (make sure TWS is running, no other process on client ID 20)
cd /Users/henrychien/Documents/Jupyter/risk_module
python3 -c "
from dotenv import load_dotenv; load_dotenv(override=True)
import importlib, settings; importlib.reload(settings)
from services.trade_execution_service import TradeExecutionService
svc = TradeExecutionService(user_email='hc@henrychien.com')
print('Accounts:', [(a['account_id'], a['provider']) for a in svc.list_tradeable_accounts()])
preview = svc.preview_order(ticker='AAPL', quantity=1, side='BUY', account_id='U2471778', order_type='Market', time_in_force='Day')
print(f'Preview: {preview.status}, id={preview.preview_id}, est_price={preview.estimated_price}')
if 'ibkr' in svc._adapters:
    svc._adapters['ibkr']._conn_manager.disconnect()
"
```

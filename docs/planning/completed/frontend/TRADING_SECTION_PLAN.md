# Trading Section Plan

**Status**: REVIEWED (v16 — Codex PASS after 16 review rounds)
**Date**: 2026-03-12
**Parent**: `FRONTEND_NAV_SYNTHESIS_PLAN.md` Phase 5
**Resolves**: New execution surface — most trading currently goes through AI chat, with the exception of the existing HedgeWorkflowDialog (4-step hedge trade flow)

---

## Overview

Build a dedicated Trading view (`ViewId: 'trading'`) that surfaces the existing 20+ trading MCP tools as structured UI. Four cards: Quick Trade, Open Orders, Baskets, Hedge Monitor.

**Key principle**: The backend is fully built. Every MCP tool already works through the AI chat (and the HedgeWorkflowDialog already covers hedge trade preview/execute via REST). This plan adds new REST endpoints for the remaining trading capabilities and builds the frontend Trading view to surface them.

---

## Inventory: What Exists

### Backend (complete — minor additions for REST layer)

| Capability | MCP Tool(s) | REST Endpoint |
|-----------|-------------|---------------|
| Tradeable accounts | `TradeExecutionService.list_tradeable_accounts()` | None (need to add) |
| Single-leg trade | `preview_trade`, `execute_trade` | None (need to add) |
| Orders | `get_orders`, `cancel_order` | None (need to add) |
| Baskets CRUD | `create_basket`, `list_baskets`, `get_basket`, `update_basket`, `delete_basket`, `create_basket_from_etf` | Partial — `/api/factor-groups` CRUD exists but returns different schemas (`{success, factor_groups}` vs MCP basket envelopes `{status, basket, warnings}`). Adding new `/api/baskets` routes that wrap MCP basket tools directly. |
| Basket analysis | `analyze_basket` | None (need to add) |
| Basket trading | `preview_basket_trade`, `execute_basket_trade` | None (need to add) |
| Option combos | `preview_option_trade`, `execute_option_trade` | None (MCP only — stays) |
| Futures rolls | `preview_futures_roll`, `execute_futures_roll` | None (MCP only — stays) |
| Hedge monitoring | `monitor_hedge_positions` | None (need to add) |
| Rebalance | `preview_rebalance_trades` | `POST /api/allocations/rebalance` |
| Hedging workflow | — | `POST /api/hedging/preview`, `POST /api/hedging/execute` |

### Frontend (partial)

| Component | Status |
|-----------|--------|
| `HedgeWorkflowDialog.tsx` (809 lines) | Complete — 4-step dialog (Review → Impact → Trades → Execute) |
| `useHedgePreview` hook | Complete — calls `/api/hedging/preview` |
| `useHedgeTradePreview` hook | Complete — calls `/api/hedging/execute` action=preview |
| `useHedgeTradeExecute` hook | Complete — calls `/api/hedging/execute` action=execute |
| `useRebalanceTrades` hook | Complete — calls `/api/allocations/rebalance` |
| NavigationIntents system | Complete — `IntentRegistry` event bus in `connectors/src/utils/NavigationIntents.ts` |
| Quick Trade UI | **Missing** |
| Orders UI | **Missing** |
| Basket management UI | **Missing** |
| Hedge Monitor UI | **Missing** |
| TradingContainer | **Missing** |

### API Layer Gap

Most trading tools are MCP-only — no REST endpoints. The frontend currently calls REST endpoints (via `APIService.ts`), not MCP tools directly. Two options:

1. **Add REST routes** for each trading capability (mirrors hedging pattern)
2. **Route through gateway** — use the Claude chat gateway to invoke MCP tools

Option 1 is the right approach. The new trading REST endpoints should be thin wrappers: auth check → call existing service/MCP function → return JSON. This gives us typed request/response, auth, and standard HTTP semantics. Note: `routes/hedging.py` is NOT a thin wrapper — it contains its own portfolio-building, rebalance-leg computation, and per-leg preview/execute loops. The new trading routes should avoid this anti-pattern and delegate entirely to existing functions in `TradeExecutionService`, `mcp_tools/baskets.py`, `mcp_tools/basket_trading.py`, and `mcp_tools/hedge_monitor.py`.

**HTTP status code policy**: All trading REST endpoints return **HTTP 200** for successful operations, even when the response contains `new_preview` (preview-expired reprieve) or `status: "partial"` (mixed basket execution). The `HttpClient` in `app-platform` throws on non-2xx responses and does not return the JSON body, so structured error payloads (validation failures, reprieve data, `new_preview`) would be lost if returned as 4xx. Only use HTTP 4xx/5xx for actual request failures (auth, missing params, server errors). Business-level error/warning states are communicated in the response body's `status` field, which the frontend inspects after receiving the 200.

---

## Architecture

### Account Resolution

**Problem**: The current `HedgeWorkflowDialog` calls `getSnapTradeConnections()` for accounts, which only returns SnapTrade-linked accounts. The `TradeExecutionService` supports multiple broker adapters (SnapTrade, IBKR, Schwab) via `list_tradeable_accounts()` → returns `BrokerAccount[]`.

**Solution**: New provider-agnostic account endpoint:

```
GET /api/trading/accounts → TradeExecutionService(user_email=user["email"]).list_tradeable_accounts()
```

Returns:
```json
[{
  "account_id": "abc123",
  "account_name": "Individual",
  "brokerage_name": "Interactive Brokers",
  "provider": "ibkr",
  "cash_balance": 50000.00,
  "available_funds": 48000.00,
  "account_type": "INDIVIDUAL",
  "meta": {}
}]
```

Source: `BrokerAccount` dataclass in `brokerage/trade_objects.py` (lines 411-436). `meta` is always present (provider-specific data). `authorization_id` is conditionally included when present (SnapTrade-specific).

All trade/order/basket cards use this endpoint for account selection. `list_tradeable_accounts()` aggregates accounts only from registered trading adapters (SnapTrade, IBKR, Schwab) — non-trading providers like Plaid are excluded. All returned accounts are tradeable.

### New REST Endpoints

```
GET  /api/trading/accounts         → list_tradeable_accounts() (provider-agnostic)
POST /api/trading/preview          → TradeExecutionService.preview_order() (single-leg)
POST /api/trading/execute          → TradeExecutionService.execute_and_reconcile() (by preview_id)
GET  /api/trading/orders           → TradeExecutionService.get_orders() (account_id optional but UI should always pass it; state/days filters)
POST /api/trading/orders/cancel    → TradeExecutionService.cancel_order(account_id, order_id) — order_id is the brokerage order ID

GET  /api/baskets                  → list_baskets
POST /api/baskets                  → create_basket
GET  /api/baskets/{name}           → get_basket
PUT  /api/baskets/{name}           → update_basket
DELETE /api/baskets/{name}         → delete_basket
POST /api/baskets/from-etf         → create_basket_from_etf (creates immediately, not draft)
POST /api/baskets/{name}/analyze   → analyze_basket
POST /api/baskets/preview          → preview_basket_trade (name in body, not URL)
POST /api/baskets/execute          → execute_basket_trade (preview_ids[] in body)

GET  /api/hedge-monitor            → monitor_hedge_positions (format=full)
```

**DTO decision**: REST endpoints return the same envelopes the MCP tools return (nested `{status, metadata, data}` for trades; flat dicts for baskets/hedge). Frontend types match these shapes exactly. No intermediate DTO layer.

Options and futures trades are advanced and rare — keep those as AI-chat-only for now.

### Frontend Component Tree

```
TradingContainer.tsx
├── QuickTradeCard.tsx
│   ├── Account selector (from /api/trading/accounts)
│   ├── Trade form (ticker, qty, side, order type)
│   ├── Preview panel (estimated cost, weight impact, validation)
│   ├── Preview-expired re-confirmation flow
│   └── Execute confirmation + result
├── OrdersCard.tsx
│   ├── Account selector (per-account scoped)
│   ├── Active orders table with cancel buttons
│   ├── State filter tabs (Open | Executed | Cancelled | All)
│   └── Auto-refresh polling
├── BasketsCard.tsx
│   ├── Basket list with expand/collapse
│   ├── Create basket form (+ "From ETF" immediate creation)
│   ├── Basket detail (weights, analysis summary)
│   └── Batch trade flow (preview → execute → reprieve handling)
└── HedgeMonitorCard.tsx
    ├── Expiring positions (3-tier: CRITICAL/SOON/APPROACHING)
    ├── Delta drift indicator
    ├── Greeks (total_delta, total_gamma, total_theta, total_vega)
    └── Roll recommendations with "Ask AI to roll →" handoff
```

### Data Flow Pattern

All four cards follow the same pattern:

```
User action → REST API call → Backend function → Response
                                    ↓
                              Same functions
                              the MCP tools call
```

The backend layer varies by card:
- **QuickTradeCard + OrdersCard**: `TradeExecutionService` (preview, execute, get_orders, cancel)
- **BasketsCard**: MCP tool functions in `mcp_tools/baskets.py` (CRUD, analyze) + `mcp_tools/basket_trading.py` (preview/execute)
- **HedgeMonitorCard**: `monitor_hedge_positions()` in `mcp_tools/hedge_monitor.py`

REST routes are thin wrappers around these existing functions. No business logic duplication.

---

## Card Specifications

### 1. QuickTradeCard

The primary direct trading interface. Follows the preview→execute pattern proven by `HedgeWorkflowDialog`.

**States**: `idle` → `form` → `previewing` → `preview` → `executing` → `result`
Additional states for edge cases: `preview_expired` → `re_previewing` → `preview`

```
┌─── Quick Trade ───────────────────────────────────────────┐
│                                                            │
│  Account: [Interactive Brokers - Individual ▾]             │
│                                                            │
│  [BUY ● / SELL ○]    Ticker: [GOOGL___]                   │
│                                                            │
│  Quantity: [10]  shares    Order: [Market ▾]               │
│                                                            │
│  ┌── Limit/Stop fields (conditional) ──────────────────┐  │
│  │  Limit Price: [$___]   Stop Price: [$___]           │  │
│  │  Time in Force: [Day ▾]                              │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                            │
│  [Preview Trade]                                           │
│                                                            │
│  ┌── Preview Result (appears after preview) ───────────┐  │
│  │  GOOGL  BUY  10 shares  @ $186.03  Market           │  │
│  │                                                      │  │
│  │  Estimated cost:    $1,860.30                        │  │
│  │  Commission:        ~$1.00                           │  │
│  │  Current weight:    21.5%                            │  │
│  │  Post-trade weight: 22.8%  (+1.3%)                   │  │
│  │                                                      │  │
│  │  ⚠ Warnings: Increases concentration in Tech sector  │  │
│  │                                                      │  │
│  │  [Execute Trade]  [Cancel]                           │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                            │
│  ┌── Execution Result (replaces preview) ──────────────┐  │
│  │  ✓ Order submitted                                   │  │
│  │  Order ID: 12345   Status: PENDING                   │  │
│  │  [View in Orders]  [New Trade]                       │  │
│  └─────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────┘
```

**Entry points** (pre-fill from exit ramps — see "Navigation Intent" section below):
- Research > Stock Lookup "Preview trade →" → pre-fills ticker
- Dashboard exit signal → pre-fills ticker + SELL side
- Scenarios > Tax Harvest "Sell for harvest →" → pre-fills ticker + SELL + quantity
- Scenarios > Rebalance "Preview all trades →" → batch mode (see below)

**Actual response envelope** from `TradePreviewResult.to_api_response()`:
```json
{
  "module": "trading",
  "version": "1.0",
  "timestamp": "...",
  "status": "success",
  "error": null,
  "metadata": {
    "user_email": "...",
    "account_id": "abc123",
    "expires_at": "2026-03-12T16:30:00Z",
    "requires_confirmation": true,
    "broker_provider": "ibkr"
  },
  "data": {
    "preview_id": "prev_abc",
    "ticker": "GOOGL",
    "side": "BUY",
    "quantity": 10,
    "order_type": "Market",
    "time_in_force": "Day",
    "limit_price": null,
    "stop_price": null,
    "estimated_price": 186.03,
    "estimated_total": 1860.30,
    "estimated_commission": 1.00,
    "pre_trade_weight": 0.215,
    "post_trade_weight": 0.228,
    "validation": {
      "is_valid": true,
      "errors": [],
      "warnings": ["Increases concentration in Technology sector"],
      "buying_power": 48000.0,
      "estimated_cost": 1860.30,
      "post_trade_weight": 0.228
    }
  }
}
```

**Actual execution response** from `TradeExecutionResult.to_api_response()`:
```json
{
  "module": "trading",
  "version": "1.0",
  "timestamp": "2026-03-12T14:30:00+00:00",
  "status": "success",
  "error": null,
  "message": null,
  "metadata": {
    "user_email": "...",
    "preview_id": "prev_abc",
    "order_id": "12345",
    "brokerage_order_id": "IB-67890",
    "broker_provider": "ibkr"
  },
  "data": {
    "account_id": "abc123",
    "ticker": "GOOGL",
    "side": "BUY",
    "quantity": 10,
    "order_status": "ACCEPTED",
    "filled_quantity": 0,
    "average_fill_price": null,
    "total_cost": null,
    "commission": null,
    "executed_at": "2026-03-12T14:30:05+00:00",
    "cancelled_at": null,
    "new_preview": null
  }
}
```

Note: `version`, `timestamp`, and `error` are present at the top level of both preview and execution envelopes. The `message` field is **execution-only** — it does not exist on `TradePreviewResult`. It carries human-readable context (e.g., "Preview expired, re-quoted at current market price"). The preview `data` object always includes additional provider-origin fields not shown above: `universal_symbol_id`, `snaptrade_trade_id`, `market_data`, `combined_remaining_balance`, `trade_impacts` — these are always emitted by the serializer (as `null` or empty when not applicable). The frontend should type them but only display the core fields listed above.

**Preview-expiry / re-confirmation flow**: When a preview expires and execution returns `data.new_preview` (a nested `TradePreviewResult`), the UI must:
1. Show "Preview expired — prices may have changed"
2. Display the new preview details (updated price/cost/weight)
3. Require explicit re-confirmation before executing with the `new_preview.data.preview_id`
4. State transition: `executing` → `preview_expired` → (user confirms) → `executing` → `result`

**Account selection**: Use `GET /api/trading/accounts` to load all tradeable accounts across providers. Auto-select if single account. Show selector at top of card if multiple. Account persists across trades within the session (stored in component state, not global store).

### 2. OrdersCard

View and manage open/recent orders. **Per-account display** — `get_orders()` accepts optional `account_id` (auto-resolves to the single eligible account when omitted; returns `status: "error"` if multiple accounts exist and none is specified). The UI should always pass the selected account for explicit scoping.

```
┌─── Orders ────────────────────────────────────────────────┐
│  Account: [Interactive Brokers - Individual ▾]             │
│                                                            │
│  [Open (3)] [Executed (12)] [Cancelled (2)] [All]          │
│                                                            │
│  ┌─────────────────────────────────────────────────────┐  │
│  │ Ticker  Side  Qty  Filled  Type    Status   Action  │  │
│  │ GOOGL   BUY   10   0/10   Market  PENDING   [✕]    │  │
│  │ AAPL    SELL  5    3/5    Limit   PARTIAL   [✕]    │  │
│  │ SPY     BUY   20   0/20   Market  ACCEPTED  [✕]    │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                            │
│  Last refreshed: 2 min ago  [↻ Refresh]                   │
└────────────────────────────────────────────────────────────┘
```

**Features**:
- Account selector synced with QuickTradeCard selection
- Tab filter by state (maps to `get_orders(state=...)` — values: `"open"`, `"executed"`, `"cancelled"`, `"all"`)
- Cancel button on open orders only (calls `cancel_order(account_id, order_id)` — the `order_id` param expects the broker's order ID value from `brokerage_order_id` in the order row, not the local DB `id`)
- Auto-refresh on 30s interval when Trading view is active
- Empty state: "No open orders" with link to Quick Trade
- Status badges — common statuses: PENDING (yellow), ACCEPTED (blue), PARTIAL (orange), EXECUTED (green), CANCELED (gray), CANCEL_PENDING (gray), REJECTED (red), FAILED (red), EXPIRED (gray). The backend passes stored `order_status` values through unchanged and can include broker-specific statuses (e.g., IBKR's QUEUED, TRIGGERED, ACTIVATED, PENDING_RISK_REVIEW, SUSPENDED, CONTINGENT_ORDER). The frontend must use a fallback badge (e.g., gray with raw status text) for any unrecognized status value.

**Actual order row fields** from `_map_local_order_row()` / `_map_remote_order_row()` in `trade_execution_service.py`:
```json
{
  "id": "123",
  "preview_id": "prev_abc",
  "account_id": "abc123",
  "brokerage_order_id": "IB-67890",
  "ticker": "GOOGL",
  "side": "BUY",
  "quantity": 10.0,
  "order_type": "Market",
  "order_status": "ACCEPTED",
  "filled_quantity": 0.0,
  "average_fill_price": null,
  "total_cost": null,
  "commission": null,
  "created_at": "2026-03-12T14:30:00+00:00",
  "updated_at": "2026-03-12T14:30:05+00:00",
  "source": "local"
}
```

Key corrections from v2: No `limit_price` field in order rows. No `broker_provider` field (only present in the execution envelope metadata). `source` is `"local"` (from DB) or `"brokerage"` (remote-only). Timestamps are `created_at`/`updated_at` (not `placed_at`/`executed_at`). For remote-only rows (`source: "brokerage"`), `id`, `preview_id`, and `account_id` are `null` — the frontend must handle these nullable fields gracefully.

### 3. BasketsCard

Manage stock baskets and execute batch trades.

```
┌─── Baskets ───────────────────────────────────────────────┐
│  [+ New Basket]  [Create from ETF]                         │
│                                                            │
│  ┌── Tech Leaders (4 stocks, equal-weight) ────────────┐  │
│  │  AAPL 25% | MSFT 25% | GOOGL 25% | NVDA 25%       │  │
│  │  [Analyze] [Trade ▾] [Edit] [Delete]                │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                            │
│  ┌── Bond Hedge (3 stocks, custom-weight) ─────────────┐  │
│  │  AGG 50% | TLT 30% | BND 20%                        │  │
│  │  [Analyze] [Trade ▾] [Edit] [Delete]                │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                            │
│  ┌── Create Basket ────────────────────────────────────┐  │
│  │  Name: [___________]                                 │  │
│  │  Tickers: [AAPL, MSFT, GOOGL]                       │  │
│  │  Weighting: [Equal ▾ | Market Cap | Custom]         │  │
│  │  [Create]                                            │  │
│  └─────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────┘
```

**Basket CRUD**:
- `create_basket(name, tickers, weighting_method, weights?, description?)` → creates immediately, returns `{status, action, basket, warnings}` envelope. `weights` required when `weighting_method="custom"`.
- `create_basket_from_etf(etf_ticker, name?, top_n?, min_weight?, description?)` → creates basket immediately from ETF top holdings (not a draft — creates and saves in one step). `name` is optional and auto-generated when omitted. UI: user enters ETF ticker + optional name + optional top_n → basket appears in list.
- `list_baskets()` → returns `{status, count, baskets: [...]}` envelope
- `get_basket(name)` → returns basket detail with resolved component weights
- `update_basket(name, tickers?, weights?, weighting_method?, description?)` → update tickers/weights/method/description (no rename — name is immutable)
- `delete_basket(name)` → delete

**Trade flow** (from "Trade ▾" dropdown):
1. Select action: Buy | Sell | Rebalance
2. For Buy: enter `total_value`; for all: select `account_id`
3. `POST /api/baskets/preview` with `{name, action, total_value?, account_id?}` → `preview_basket_trade()` returns `BasketTradePreviewResult` with `preview_legs[]` containing per-leg `preview_id`s. `account_id` is optional for `buy` (auto-resolves if single account) but required for `sell` and `rebalance`.
4. Execute: `POST /api/baskets/execute` with `{preview_ids: [...]}` → `execute_basket_trade()` with best-effort per-leg execution

**Basket execute routes are preview_id-based, not basket-name-based**: The execute endpoint takes `preview_ids[]` from the preview step. The basket name is not needed at execution time.

**Reprieve handling**: `execute_basket_trade` can return legs with `order_status: "reprieved"` and `new_preview_id`. The UI must check for reprieved legs whenever the response contains any `reprieved_legs` — not just when `status === "needs_confirmation"`. The backend returns:
- `"needs_confirmation"` when ALL legs are reprieved
- `"partial"` when reprieved legs are mixed with succeeded/failed legs
- `"completed"` when all legs succeeded
- `"failed"` when all legs failed

The `status` field values and their meanings:
- `"needs_confirmation"` — ALL legs reprieved (no completed/failed legs)
- `"partial"` — catch-all for any mixed outcome (some succeeded + some failed, or reprieved mixed with succeeded/failed, etc.)
- `"completed"` — zero failures, zero reprievals, and every leg in `{EXECUTED, ACCEPTED, PENDING}` (note: a leg with `PARTIAL` fill counts as succeeded for counting but keeps overall at `"partial"`, not `"completed"`)
- `"failed"` — all legs failed after execution processing (note: empty `preview_ids` raises a `ValueError` caught by `@handle_mcp_errors` → returns `{status: "error", error: ...}`, not `"failed"`)

In `"needs_confirmation"` and `"partial"` cases where `reprieved_legs` is non-empty, the UI must:
1. Show completed/failed legs as final (green checkmarks / red X)
2. Show reprieved legs with "Prices changed — re-confirm?" prompt
3. User confirms → re-execute with `new_preview_id` values from reprieved legs
4. The `reprieved_legs` array in the response is the canonical list to check (not just `status`)

**Analysis expand** (from "Analyze" button):
- Returns, volatility, Sharpe, max drawdown
- Correlation to portfolio
- Component attribution chart

### 4. HedgeMonitorCard

Surface the existing `monitor_hedge_positions` output as a read-only dashboard card.

```
┌─── Hedge Monitor ─────────────────────────────────────────┐
│                                                            │
│  Assessment: ⚠ DELTA_DRIFT                                │
│  "Delta drift 15.2% exceeds tolerance 10.0%"              │
│                                                            │
│  ┌── Expiring Positions ───────────────────────────────┐  │
│  │  🔵 APPROACH  SPY 240P  20 days                     │  │
│  │  🔵 APPROACH  QQQ 380P  28 days                     │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                            │
│  ┌── Greeks ───────────────────────────────────────────┐  │
│  │  Total Delta:  -$4,230   Gamma: $120                │  │
│  │  Total Theta:  -$42/day  Vega:  $1,230              │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                            │
│  ┌── Delta Drift ──────────────────────────────────────┐  │
│  │  Target: 0.0   Current: -0.152   Tolerance: ±0.10  │  │
│  │  ⚠ Deviation: 0.152 (exceeds tolerance)             │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                            │
│  ┌── Roll Recommendations ─────────────────────────────┐  │
│  │  No roll recommendations at this time.              │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                            │
│  Last checked: 5 min ago  [↻ Refresh]                     │
└────────────────────────────────────────────────────────────┘
```

**Actual response shape** from `monitor_hedge_positions(format="full")`:
```json
{
  "status": "success",
  "evaluated_at": "2026-03-12T14:30:00+00:00",
  "portfolio_value": 285000.0,
  "option_count": 5,
  "underlying_filter": null,
  "expiry_tiers": [
    {"days": 7, "severity": "error", "label": "CRITICAL"},
    {"days": 14, "severity": "warning", "label": "SOON"},
    {"days": 30, "severity": "info", "label": "APPROACHING"}
  ],
  "roll_lookahead_days": 14,
  "theta_drain_threshold": -50.0,
  "vega_pct_threshold": 0.05,
  "greeks": {
    "total_delta": -4230.0,
    "total_gamma": 120.0,
    "total_theta": -42.0,
    "total_vega": 1230.0,
    "position_count": 5,
    "failed_count": 0,
    "by_underlying": {
      "SPY": {"delta": -3100, "gamma": 80, "theta": -30, "vega": 800, "position_count": 3}
    },
    "source": "computed"
  },
  "delta_drift": {
    "target": 0.0,
    "current_ratio": -0.152,
    "deviation": 0.152,
    "tolerance": 0.10,
    "within_tolerance": false,
    "skipped": false
  },
  "expiring_positions": [
    {
      "ticker": "SPY  240403P00240000",
      "underlying": "SPY",
      "option_type": "put",
      "strike": 240.0,
      "expiry": "2026-04-03",
      "days_to_expiry": 20,
      "quantity": -2.0,
      "tier": "APPROACHING",
      "tier_severity": "info",
      "roll_recommended": false
    }
  ],
  "by_underlying": {
    "SPY": {"delta": -3100, "gamma": 80, "theta": -30, "vega": 800, "position_count": 3, "nearest_expiry_days": 20}
  },
  "roll_recommendations": [],
  "verdict": "Delta drift 15.2% exceeds tolerance 10.0%",
  "overall_assessment": "DELTA_DRIFT"
}
```

**Key field names** (corrected from v1):
- `overall_assessment` — the enum badge (not `verdict`): `OK`, `MONITOR`, `DELTA_DRIFT`, `ROLL_NEEDED`, `CRITICAL_EXPIRY`, `MULTIPLE_ALERTS`. Error responses from `@handle_mcp_errors` return `{status: "error", error: "..."}` without `overall_assessment` — the frontend should check `status` first and only read `overall_assessment` when `status === "success"`.
- `verdict` — the human-readable explanation string
- `expiring_positions[]` — not `alerts[]`
- `greeks` — raw totals from `compute_portfolio_greeks()` (not `greeks_summary`). `greeks.by_underlying` contains `{delta, gamma, theta, vega, position_count}` per symbol — does NOT include `nearest_expiry_days`.
- Top-level `by_underlying` — from `_build_underlying_snapshot()`, merges greeks with position data. Contains `{delta, gamma, theta, vega, position_count, nearest_expiry_days}` per symbol. This is the field to use for underlying-level display including expiry info.
- `delta_drift` — structured object with `target`, `current_ratio`, `deviation`, `tolerance`, `within_tolerance`
- `roll_recommendations[]` — each has `reasoning` string, no price/credit data (backend doesn't compute roll pricing)
- `overall_assessment` logic: Five primary alerts are checked: `[critical_count > 0, has_delta_drift, roll_count > 0, has_theta_drain, has_high_vega]`. If >1 triggered → `MULTIPLE_ALERTS`. If exactly 1, the code checks dedicated branches in order: `critical_count > 0` → `CRITICAL_EXPIRY`, `has_delta_drift` → `DELTA_DRIFT`, `roll_count > 0` → `ROLL_NEEDED`. `has_theta_drain` and `has_high_vega` do NOT have their own assessment types — if either is the sole primary alert, the code falls through to: `approaching_count > 0 or failed_count > 0` → `MONITOR`, else → `OK`. So theta/vega alone can result in `MONITOR` or `OK` depending on whether approaching positions or failed greeks computations exist. The wireframe example above shows a DELTA_DRIFT scenario: only delta drift is triggered (no CRITICAL positions, no rolls, theta above -50 threshold, vega ratio below 5% threshold).

**Roll action**: Since the backend doesn't compute roll pricing and option rolls require complex leg specification, "Preview Roll →" is **not** a native UI flow. Instead: "Ask AI to roll →" opens the AI chat panel pre-filled with context (e.g., "Roll SPY 240P from Mar to Apr expiry"). This is the pragmatic choice — option roll specification is inherently conversational.

**Assessment badges**: `OK` (green), `MONITOR` (blue), `DELTA_DRIFT` (amber), `ROLL_NEEDED` (amber), `CRITICAL_EXPIRY` (red), `MULTIPLE_ALERTS` (red). Error responses (`status: "error"`) should be displayed separately — they don't carry `overall_assessment`.

**Empty state**: "No option positions detected" (when `option_count === 0`).

---

## Navigation Intent System

**Design requirement**: Exit ramps from other sections (Research, Scenarios, Dashboard) need to pass context (ticker, side, quantity) to the Trading view. This requires a mechanism that works whether Trading is already mounted or not, handles both single-trade and batch/rebalance payloads, and avoids stale state.

**Solution**: A thin `pendingTradingIntent` store (zustand) that acts as a one-shot mailbox. Exit ramps write to it, TradingContainer reads and clears it on mount or when already mounted. This avoids the IntentRegistry timing problem where the handler isn't registered if Trading hasn't mounted yet.

### Step 1: Define typed payload

```ts
// In connectors/src/features/trading/tradingIntentStore.ts
import { create } from 'zustand';

export type TradingIntentPayload =
  | {
      mode: 'single';
      ticker: string;
      side?: 'BUY' | 'SELL';
      quantity?: number;
      source: 'research' | 'exit_signal' | 'tax_harvest' | 'direct';
    }
  | {
      mode: 'batch';
      legs: Array<{ ticker: string; side: 'BUY' | 'SELL'; quantity: number }>;
      source: 'rebalance';
    };

interface TradingIntentState {
  pending: TradingIntentPayload | null;
  setPending: (intent: TradingIntentPayload) => void;
  consume: () => TradingIntentPayload | null;
}

export const useTradingIntentStore = create<TradingIntentState>((set, get) => ({
  pending: null,
  setPending: (intent) => set({ pending: intent }),
  consume: () => {
    const current = get().pending;
    if (current) set({ pending: null });
    return current;
  },
}));
```

### Step 2: TradingContainer consumes on mount + subscribe for live updates

```ts
// In TradingContainer.tsx
const consume = useTradingIntentStore((s) => s.consume);
const pending = useTradingIntentStore((s) => s.pending);

// Consume on mount (covers: exit ramp fired before Trading mounted)
useEffect(() => {
  const intent = consume();
  if (intent) applyIntent(intent);
}, []);

// React to live updates (covers: exit ramp fired while Trading is already mounted)
useEffect(() => {
  if (pending) {
    const intent = consume();
    if (intent) applyIntent(intent);
  }
}, [pending]);
```

### Step 3: Exit ramps write intent + navigate

```ts
// In any exit ramp button handler
import { useTradingIntentStore } from '@risk/connectors';

useTradingIntentStore.getState().setPending({
  mode: 'single',
  ticker: 'GOOGL',
  side: 'SELL',
  quantity: 10,
  source: 'exit_signal',
});
setActiveView('trading');
```

**Why this works**:
- **No timing issue**: Store persists the payload regardless of whether TradingContainer is mounted. The component reads it on mount.
- **One-shot**: `consume()` atomically reads and clears — no stale state accumulation.
- **Live updates**: The `pending` subscription handles the case where Trading is already visible and a new exit ramp fires.
- **Typed**: `TradingIntentPayload` discriminated union handles single vs batch.
- **Minimal**: ~30 lines of store code, no new event system.

**Batch mode**: When `mode === 'batch'`, QuickTradeCard switches to a leg-table view (similar to basket trade preview) with per-leg preview→execute. Each leg gets its own `preview_id`. Uses the same reprieve handling as basket execution.

---

## Implementation Phases

### Phase 5A: REST Endpoints (backend)

**Scope**: Thin REST wrappers around existing services. All business logic already exists — routes should delegate entirely to service/MCP functions (do NOT replicate the `routes/hedging.py` pattern, which inlines business logic).

1. **Expand `routes/trading.py`** — add to existing file:
   - `GET /api/trading/accounts` → `list_tradeable_accounts()` → `BrokerAccount.to_dict()` array
   - `POST /api/trading/preview` → `TradeExecutionService.preview_order()` → `.to_api_response()`
   - `POST /api/trading/execute` → `TradeExecutionService.execute_and_reconcile()` → `.to_api_response()`
   - `GET /api/trading/orders` → `TradeExecutionService.get_orders()` → `.to_api_response()`
   - `POST /api/trading/orders/cancel` → `TradeExecutionService.cancel_order(account_id, order_id)` → `.to_api_response()` (note: `order_id` param expects the brokerage order ID value, not local DB `id`)

2. **New `routes/baskets_api.py`** — basket CRUD + trading:
   - `GET /api/baskets` → `list_baskets()`
   - `POST /api/baskets` → `create_basket()`
   - `GET /api/baskets/{name}` → `get_basket()`
   - `PUT /api/baskets/{name}` → `update_basket()`
   - `DELETE /api/baskets/{name}` → `delete_basket()`
   - `POST /api/baskets/from-etf` → `create_basket_from_etf()`
   - `POST /api/baskets/{name}/analyze` → `analyze_basket()`
   - `POST /api/baskets/preview` → `preview_basket_trade()` (name in body)
   - `POST /api/baskets/execute` → `execute_basket_trade()` (preview_ids in body)

3. **New `routes/hedge_monitor_api.py`** — `GET /api/hedge-monitor` → `monitor_hedge_positions(format="full")`

Each endpoint: auth check via `auth_service.get_user_by_session()` → call service/MCP tool function → return JSON. **HTTP status code policy for new trading routes**: return HTTP 200 for responses where the frontend needs to inspect the structured payload (including `status: "error"` with actionable context, `status: "partial"`, reprieve payloads with `new_preview`) because the `HttpClient` throws on non-2xx and discards the response body. HTTP 400 is acceptable for simple validation rejections (missing required params, malformed input) where the frontend only needs to show the error message. Note: "no matching positions" is NOT a 400 — the backend returns success with empty results plus a warning in that case. HTTP 4xx/5xx for auth failures and unhandled exceptions. Note: the existing `routes/trading.py` analysis endpoint converts `status=="error"` to HTTP 500 — the new trading endpoints should NOT follow that pattern. The hedging routes (`routes/hedging.py`) use a mixed approach: HTTP 400 for simple validation (no positions, missing IDs), HTTP 200 for complex business responses. The new trading routes should follow this same pattern, with the additional constraint that any response containing `new_preview`, reprieve legs, or partial execution results MUST be HTTP 200 to preserve the structured payload.

**Files**: `routes/trading.py` (expand), `routes/baskets_api.py` (new), `routes/hedge_monitor_api.py` (new), `app.py` (register routers)

### Phase 5B: Frontend Hooks + Types (connectors)

**Scope**: React Query hooks wrapping the new REST endpoints.

1. **Types** in `frontend/packages/chassis/src/services/APIService.ts`:
   - `BrokerAccountResponse` — matches `BrokerAccount.to_dict()` shape
   - `TradePreviewEnvelope` — `{module, version, timestamp, status, error, metadata, data}` from `TradePreviewResult.to_api_response()`
   - `TradeExecutionEnvelope` — `{module, version, timestamp, status, error, message, metadata, data}` from `TradeExecutionResult.to_api_response()` (note: `message` is execution-only)
   - `OrderListEnvelope` — nested `{module, version, timestamp, status, error, metadata: {user_email, account_id, state, days, order_count}, data: {orders[]}}` from `OrderListResult.to_api_response()`
   - `BasketResponse`, `BasketListResponse`, `CreateBasketParams`
   - `BasketTradePreviewEnvelope`, `BasketTradeExecuteEnvelope` — includes reprieve leg shape
   - `HedgeMonitorResponse` — matches full format shape above

2. **APIService methods**: `getTradingAccounts()`, `previewTrade()`, `executeTrade()`, `getOrders()`, `cancelOrder()`, `listBaskets()`, `createBasket()`, `getBasket()`, `updateBasket()`, `deleteBasket()`, `createBasketFromEtf()`, `analyzeBasket()`, `previewBasketTrade()`, `executeBasketTrade()`, `getHedgeMonitor()`

3. **Hooks** in `frontend/packages/connectors/src/features/trading/`:
   - `useTradingAccounts()` — query, staleTime 5min
   - `useTradePreview()` — mutation
   - `useTradeExecute()` — mutation
   - `useOrders(accountId, state, days)` — query with 30s refetchInterval
   - `useCancelOrder()` — mutation + invalidates orders query
   - `useBaskets()` — query
   - `useCreateBasket()` — mutation + invalidates baskets
   - `useBasketTradePreview()` — mutation
   - `useBasketTradeExecute()` — mutation
   - `useHedgeMonitor()` — query with 5-min stale time

4. **Trading intent store**: New `tradingIntentStore.ts` with `TradingIntentPayload` type + `useTradingIntentStore` zustand store

**Files**: ~8-10 new files in connectors + APIService additions + tradingIntentStore

### Phase 5C: TradingContainer + QuickTradeCard

**Scope**: The container shell + the most important card.

1. **`TradingContainer.tsx`** — Grid layout, 2-column on desktop (Quick Trade + Orders top, Baskets + Hedge Monitor bottom). Consumes `useTradingIntentStore` on mount + subscribes for live updates (see Navigation Intent section).
2. **`QuickTradeCard.tsx`** — Full preview→execute flow with:
   - Account selector (from `useTradingAccounts`)
   - Preview-expired re-confirmation via `data.new_preview`
   - Batch mode leg table (when intent `mode === 'batch'`)
   - Validation warnings display
3. Register `trading` ViewId in `uiStore.ts` (if not done in Phase 1)
4. Wire into `renderMainContent()` routing

**Files**: 2-3 new component files

### Phase 5D: OrdersCard + BasketsCard

**Scope**: Remaining two management cards.

1. **`OrdersCard.tsx`** — Per-account order table, tab-filtered, cancel actions, auto-refresh
2. **`BasketsCard.tsx`** — List view, create form (including "From ETF" immediate creation), expand for analysis, trade flow with preview_id-based execution and reprieve handling

**Files**: 2-3 new component files

### Phase 5E: HedgeMonitorCard

**Scope**: Read-only monitoring card with AI chat handoff for rolls.

1. **`HedgeMonitorCard.tsx`** — `overall_assessment` badge, `expiring_positions` list, `greeks` totals, `delta_drift` detail, `roll_recommendations` with "Ask AI to roll →" chat handoff
2. Empty state handling for `option_count === 0`

**Files**: 1-2 new component files

---

## Suggested Execution Order

1. **5A** (REST endpoints) — unblocks everything, backend-only
2. **5B** (hooks + types) — unblocks all cards. Can partially overlap with 5A.
3. **5C** (container + QuickTradeCard) — most important card, proves the pattern
4. **5D** (OrdersCard + BasketsCard) — parallel with 5E. BasketsCard has highest complexity due to reprieve flow.
5. **5E** (HedgeMonitorCard) — can start early (read-only, no trading flow complexity)

Phases 5A+5B could be one Codex task. 5C is the critical path. 5D and 5E can run in parallel. 5E could also start as early as after 5B since it's read-only.

---

## Exit Ramp Integration

How other sections pass context to Trading:

| Source | Action | Intent Payload |
|--------|--------|----------------|
| Research > Stock Lookup | "Preview trade →" | `{mode: 'single', ticker, side: 'BUY', source: 'research'}` |
| Dashboard > Exit Signal | Click exit signal | `{mode: 'single', ticker, side: 'SELL', quantity, source: 'exit_signal'}` |
| Scenarios > Tax Harvest | "Sell for harvest →" | `{mode: 'single', ticker, side: 'SELL', quantity, source: 'tax_harvest'}` |
| Scenarios > Rebalance | "Preview all trades →" | `{mode: 'batch', legs: [...], source: 'rebalance'}` |
| Research > Portfolio Risk | "Simulate hedge" | → Scenarios (not Trading) |
| Hedge Monitor | "Ask AI to roll →" | Opens AI chat panel (not a trading intent) |

---

## What This Plan Does NOT Cover

- Option combo trading UI (keep in AI chat — complex leg specification)
- Futures roll UI (keep in AI chat — rare operation)
- Roll pricing in hedge monitor (backend doesn't compute this — needs chain data)
- Order history / trade log (future — separate from active orders)
- P&L attribution by trade (future — lives in Performance section)
- Real-time streaming prices (would need WebSocket — not in scope)
- Trade confirmation notifications (future — via notify MCP)
- Cross-account order aggregation (orders are per-account by design)

---

## Risk Assessment

- **Lowest risk**: HedgeMonitorCard (read-only, data shape verified against actual backend code)
- **Medium risk**: OrdersCard (straightforward per-account CRUD, proven patterns)
- **Medium-high risk**: BasketsCard (most UI states — CRUD + trade preview + execute + reprieve handling for expired previews)
- **Highest risk**: QuickTradeCard (executes real trades, needs careful UX for confirmation flow, preview-expiry re-confirmation, error handling, account selection)

QuickTradeCard and BasketsCard both need preview-expiry and reprieve handling tested thoroughly before shipping. The two-step preview→execute pattern with explicit confirmation is critical — no auto-execute paths.

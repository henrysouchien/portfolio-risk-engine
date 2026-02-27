# IBKR Trading Integration -- Research Report

> **Status:** Research complete. Implementation done — see `IBKR_TRADING_IMPLEMENTATION_PLAN.md` for the plan and completion status.

**Date:** 2026-02-09
**Context:** Adding Interactive Brokers direct trade execution as a second execution path alongside the existing SnapTrade flow in the portfolio-mcp system.
**Current state:** IB account U\*\*\*1778 is connected via Plaid (read-only positions). SnapTrade does not support IBKR trading. Goal is direct IBKR order execution.

---

## 1. IBKR API Options Overview

Interactive Brokers offers three primary API paths for programmatic trading:

### 1A. TWS API (Socket-based, via `ibapi` or `ib_async`)

| Attribute | Detail |
|-----------|--------|
| **Protocol** | TCP socket (binary protocol) to a locally running TWS or IB Gateway process |
| **Authentication** | Login happens in the gateway/TWS GUI (username + password + optional 2FA via IBKR Mobile). The API itself authenticates via clientId on socket connect -- no tokens or API keys. |
| **Requires desktop app?** | Yes. Either TWS (full GUI) or IB Gateway (lightweight, can run headless with Xvfb). |
| **Can run headless?** | Yes, with IB Gateway + IBC (automation controller) + Xvfb (virtual framebuffer). Docker images exist. |
| **Python libraries** | `ib_async` (actively maintained fork of `ib_insync`), raw `ibapi` (IB's official but low-level SDK) |
| **Order types** | All order types supported by TWS: Market, Limit, Stop, StopLimit, Trailing Stop, Bracket, Adaptive, IB Algos, etc. |
| **Order preview** | `whatIfOrder()` returns commission and margin impact without placing the order. |
| **Maturity** | TWS API has been IB's primary programmatic trading interface for 20+ years. Extremely stable. |

### 1B. Client Portal API / Web API v1.0 (REST-based, via CP Gateway or OAuth)

| Attribute | Detail |
|-----------|--------|
| **Protocol** | REST (HTTPS) + optional WebSocket for streaming. |
| **Authentication** | **Retail/individual accounts:** Must run the Client Portal Gateway (a local Java app) and authenticate via browser. Session-based -- must re-authenticate periodically. **Institutional accounts:** OAuth 1.0a (fully headless). OAuth 2.0 for retail is "under consideration" with no ETA. |
| **Requires desktop app?** | For retail: Yes, the CP Gateway Java process must run locally. For institutional: No (OAuth 1.0a is headless). |
| **Can run headless?** | Retail: Partially. The CP Gateway runs headless, but periodic browser-based re-authentication is required. Institutional: Fully headless via OAuth 1.0a. |
| **Python libraries** | `ibind` (actively maintained, v0.1.22 as of Jan 2026), `EasyIB`, `interactive-broker-python-api` |
| **Order types** | All standard order types via `/iserver/account/{accountId}/orders` endpoint. |
| **Order preview** | Yes: `POST /iserver/account/{accountId}/order/whatif` returns commission and margin impact. |
| **Maturity** | Newer than TWS API. REST interface is cleaner but the CP Gateway auth requirement for retail accounts is a significant operational burden. |

### 1C. Summary Comparison

| Criterion | TWS API + ib_async | Client Portal API + ibind |
|-----------|-------------------|--------------------------|
| **Auth for retail** | IB Gateway login (once/week with 2FA) | CP Gateway + browser re-auth |
| **Headless?** | Yes (IB Gateway + IBC + Docker) | No (retail requires browser) |
| **Protocol** | TCP socket | REST/HTTPS |
| **Python library quality** | Excellent (`ib_async` 2.1.0) | Good (`ibind` 0.1.22, actively maintained) |
| **Order preview** | `whatIfOrder()` | `/order/whatif` endpoint |
| **Complexity** | Moderate (need running gateway process) | High (CP Gateway + session management) |
| **Reliability** | Very high (20+ years of TWS API stability) | Moderate (newer, session can expire) |

**Recommendation: TWS API via `ib_async` + IB Gateway is the clear winner for a retail individual account.** It avoids the CP Gateway browser-auth problem, has a battle-tested protocol, excellent Python support, and can be fully automated with weekly 2FA confirmation via IBKR Mobile.

---

## 2. ib_async -- Deep Dive

### 2A. Background and Maintenance Status

- **Original library:** `ib_insync` by Ewald de Wit. Last release: v0.9.86 (December 2023). The original author passed away and the project is no longer maintained.
- **Active fork:** `ib_async` by the `ib-api-reloaded` organization. Current version: **2.1.0**. Last updated: December 2025. Actively maintained with regular releases.
- **PyPI:** `pip install ib_async`
- **GitHub:** https://github.com/ib-api-reloaded/ib_async
- **Drop-in replacement:** `ib_async` is API-compatible with `ib_insync`. Import path changes from `ib_insync` to `ib_async`, but the class and method names are identical.

### 2B. Connection Model

```
ib_async (Python)  ---TCP socket--->  IB Gateway (port 4001 live / 4002 paper)
                                           |
                                      IB Servers (internet)
```

Connection code:

```python
from ib_async import IB, Stock, MarketOrder, LimitOrder

ib = IB()
ib.connect('127.0.0.1', 4001, clientId=1)  # 4001=live, 4002=paper
```

- Multiple clientIds can connect to the same gateway simultaneously (up to ~32).
- Connection is persistent (socket stays open). Disconnection events can be handled.
- `ib.disconnect()` to close.

### 2C. Order Placement Flow (Preview -> Place -> Monitor)

**Step 1: Qualify the contract**

```python
contract = Stock('AAPL', 'SMART', 'USD')
ib.qualifyContracts(contract)  # Fills in conId and other details in-place
```

**Step 2: Preview (whatIfOrder)**

```python
order = LimitOrder('BUY', 10, 150.00)
order_state = ib.whatIfOrder(contract, order)
# OrderState contains:
#   - commission (estimated)
#   - commissionCurrency
#   - initMarginBefore / initMarginAfter / initMarginChange
#   - maintMarginBefore / maintMarginAfter / maintMarginChange
#   - equityWithLoanBefore / equityWithLoanAfter / equityWithLoanChange
#   - warningText (if any)
```

This is the equivalent of SnapTrade's `get_order_impact()`. It returns commission and margin impact without submitting the order.

**Step 3: Place order**

```python
trade = ib.placeOrder(contract, order)
# Trade object is live-updated with:
#   - trade.orderStatus.status  (e.g., 'Submitted', 'Filled', 'Cancelled')
#   - trade.orderStatus.filled
#   - trade.orderStatus.avgFillPrice
#   - trade.fills  (list of Fill objects)
#   - trade.log  (list of TradeLogEntry objects with timestamps)
```

**Step 4: Monitor**

```python
# Event-based:
ib.orderStatusEvent += on_order_status_change
ib.newOrderEvent += on_new_order
ib.execDetailsEvent += on_execution

# Or polling:
while not trade.isDone():
    ib.sleep(1)
    print(trade.orderStatus.status)
```

### 2D. Order Types Supported

All TWS-supported order types are available through `ib_async`:

| Type | ib_async helper |
|------|----------------|
| Market | `MarketOrder('BUY', 100)` |
| Limit | `LimitOrder('BUY', 100, 150.00)` |
| Stop | `StopOrder('SELL', 100, 145.00)` |
| Stop Limit | `StopLimitOrder('SELL', 100, stop=145.00, limit=144.50)` |
| Trailing Stop | Via `Order` with `trailStopPrice` / `trailingPercent` |
| Bracket | `ib.bracketOrder(...)` (parent + take-profit + stop-loss) |
| Adaptive | Via `Order` with `algoStrategy='Adaptive'` |
| IB Algos | TWAP, VWAP, etc. via `algoStrategy` field |

For the existing system's `ALLOWED_ORDER_TYPES = ("Market", "Limit", "Stop", "StopLimit")`, all four are natively supported.

### 2E. Error Handling Patterns

Key error scenarios and how ib_async handles them:

| Scenario | Behavior |
|----------|----------|
| **Gateway not running** | `ConnectionRefusedError` on `ib.connect()` |
| **Connection timeout** | `asyncio.TimeoutError` (configurable timeout, default 2s) |
| **Connection lost mid-session** | `ib.disconnectedEvent` fires. Can implement auto-reconnect. |
| **Order rejected by IB** | `trade.orderStatus.status` becomes `'Inactive'`; `trade.log` contains rejection reason |
| **Insufficient funds** | Rejection with reason in `trade.log` |
| **Invalid contract** | `qualifyContracts()` returns empty or None for unresolved contracts |
| **2FA timeout** | Gateway refuses connections; IBC handles re-auth scheduling |

The library provides both sync and async interfaces. The sync interface wraps asyncio internally and is safe to use from non-async code (which matches the current MCP server's synchronous tool pattern).

---

## 3. IB Gateway -- Headless Operation

### 3A. What Is IB Gateway?

IB Gateway is a lightweight alternative to the full TWS desktop application. It provides the same API connectivity but without the full trading GUI. It is specifically designed for API-only usage.

### 3B. Running on macOS

IB Gateway runs natively on macOS. Setup:

1. **Download:** IB Gateway standalone installer from IBKR website (choose "stable" version for live trading).
2. **IBC (Interactive Brokers Controller):** Open-source automation tool (https://github.com/IbcAlpha/IBC) that:
   - Automates login (username + password)
   - Handles 2FA prompts (triggers IBKR Mobile notification)
   - Manages daily auto-restart (IB requires daily gateway restart)
   - Prevents duplicate instances
   - Supports macOS via launchd plist (runs on schedule)
3. **Ports:** Default 4001 (live) / 4002 (paper). API connections are localhost-only by default.

### 3C. Authentication and 2FA

- **First login:** Username + password + 2FA via IBKR Mobile app (seamless authentication -- phone notification).
- **Daily restarts:** IB requires the gateway to restart once per day (around 11:45 PM ET). With `auto-restart` mode (not auto-logoff), the gateway restarts without requiring re-authentication.
- **Weekly re-auth:** Full re-authentication (including 2FA) is required once per week, after the Sunday 01:00 ET maintenance window.
- **Practical impact:** You approve the IBKR Mobile 2FA notification once per week. The rest of the week is fully automated.

### 3D. Docker Images

Several Docker images wrap IB Gateway + IBC + Xvfb for fully headless operation:

**gnzsnz/ib-gateway-docker** (most popular, actively maintained):

| Feature | Detail |
|---------|--------|
| **GitHub** | https://github.com/gnzsnz/ib-gateway-docker |
| **Architecture** | amd64 + experimental aarch64 (Apple Silicon M1/M2/M3) |
| **Ports** | 4001 (live API), 4002 (paper API), 5900 (VNC for debugging) |
| **2FA** | Handled via IBC + IBKR Mobile seamless auth |
| **Auto-restart** | Built-in daily restart handling |
| **Trading mode** | Configurable via `TRADING_MODE` env var (live/paper) |

Key environment variables:

```yaml
environment:
  TWS_USERID: ${TWS_USERID}
  TWS_PASSWORD: ${TWS_PASSWORD}
  TRADING_MODE: live          # or 'paper'
  READ_ONLY_API: no           # Must be 'no' for trading!
  TWOFA_TIMEOUT_ACTION: restart
  AUTO_RESTART_TIME: 11:45 PM
  RELOGIN_AFTER_TWOFA_TIMEOUT: yes
  TIME_ZONE: America/New_York
```

### 3E. Recommendation for This Project

**For initial development and testing:** Run IB Gateway natively on macOS with IBC automation. No Docker needed. This keeps things simple and matches the existing development setup (MCP server runs locally).

**For production / always-on:** Docker (gnzsnz/ib-gateway-docker) with docker-compose. Provides clean restart handling and isolation.

**For paper trading:** Use port 4002. Note that 2FA cannot be disabled for paper accounts -- same auth flow as live.

---

## 4. ibind (Client Portal API) -- Alternative Assessment

### 4A. Overview

`ibind` is the best Python library for the IBKR Client Portal / Web API v1.0. Version 0.1.22 (Jan 2026), actively maintained.

### 4B. Why NOT Recommended for This Use Case

| Issue | Impact |
|-------|--------|
| **Retail accounts cannot use OAuth** | Must run CP Gateway Java app + browser-based login. Not truly headless. |
| **Session expiry** | CP Gateway sessions expire and require browser re-authentication. More fragile than IB Gateway's once-per-week 2FA. |
| **Extra dependency** | Requires running a Java gateway process AND the Python MCP server. Same operational overhead as IB Gateway but with less reliability. |
| **Newer, less battle-tested** | CP API is newer than TWS API. Edge cases in order handling are less well-documented. |

### 4C. When ibind Would Make Sense

- If you had an **institutional account** with OAuth 1.0a access (fully headless REST).
- If IBKR eventually ships OAuth 2.0 for retail accounts (no ETA).
- If you needed a pure REST architecture with no socket connections.

For a retail individual account, `ib_async` + IB Gateway is strictly superior.

---

## 5. Integration Architecture

### 5A. Current Architecture (SnapTrade Only)

```
MCP Tool (preview_trade / execute_trade)
    |
    v
TradeExecutionService
    |
    ├── preview_order()  -->  preview_snaptrade_order()  -->  SnapTrade REST API
    ├── execute_order()  -->  place_snaptrade_checked_order() --> SnapTrade REST API
    ├── get_orders()     -->  get_snaptrade_orders()     -->  SnapTrade REST API
    └── cancel_order()   -->  cancel_snaptrade_order()   -->  SnapTrade REST API
```

The `TradeExecutionService` is currently tightly coupled to SnapTrade:
- It calls SnapTrade-specific functions directly (`preview_snaptrade_order`, `place_snaptrade_checked_order`, etc.)
- It stores SnapTrade-specific fields (`snaptrade_trade_id`, `universal_symbol_id`)
- The DB schema has SnapTrade-specific columns (`snaptrade_trade_id`)

### 5B. Proposed Architecture (SnapTrade + IBKR)

Introduce a **broker adapter pattern** -- a common interface that both SnapTrade and IBKR implement:

```
MCP Tool (preview_trade / execute_trade)
    |
    v
TradeExecutionService  (orchestrator, broker-agnostic)
    |
    ├── Determines target broker from account_id/provider
    |
    ├── BrokerAdapter (abstract interface)
    │       |
    │       ├── SnapTradeBrokerAdapter  (existing SnapTrade logic)
    │       │       └── snaptrade_loader.py functions
    │       │
    │       └── IBKRBrokerAdapter  (new)
    │               └── ib_async connection to IB Gateway
    │
    ├── Pre-trade validation (shared across all brokers)
    ├── DB persistence (shared trade_previews / trade_orders tables)
    └── Post-trade refresh
```

### 5C. BrokerAdapter Interface

A common abstract interface that both adapters implement:

```
class BrokerAdapter (ABC):

    def preview_order(account_id, ticker, side, quantity, order_type,
                      limit_price, stop_price, time_in_force) -> dict
        # Returns: estimated_price, estimated_total, estimated_commission,
        #          broker_trade_id (for SnapTrade) or None (for IBKR),
        #          trade_impacts, remaining_balance

    def place_order(account_id, order_params) -> dict
        # For SnapTrade: uses snaptrade_trade_id from preview
        # For IBKR: constructs and places order via ib_async
        # Returns: brokerage_order_id, status, fill_details

    def get_orders(account_id, state, days) -> list[dict]
        # Returns normalized order list

    def cancel_order(account_id, order_id) -> dict
        # Returns cancellation status

    def search_symbol(account_id, ticker) -> dict
        # Returns resolved symbol info

    def get_account_balance(account_id) -> float
        # Returns available cash

    def refresh_after_trade(account_id) -> None
        # Trigger position refresh
```

### 5D. Key Differences Between SnapTrade and IBKR Flows

| Aspect | SnapTrade | IBKR (ib_async) |
|--------|-----------|-----------------|
| **Preview** | `get_order_impact()` returns a `trade_id` that must be passed to `place_order()`. Preview and execution are linked by this ID. | `whatIfOrder()` returns commission/margin impact. Preview and execution are independent -- you construct the order again for placement. |
| **Execution** | `place_order(trade_id=...)` using the preview's trade_id | `placeOrder(contract, order)` -- constructs order from scratch |
| **Preview expiry** | 5-minute TTL on `trade_id` | No expiry concept -- preview is stateless |
| **Connection** | Stateless REST calls | Persistent TCP socket to IB Gateway |
| **Symbol resolution** | `symbol_search_user_account()` returns `universal_symbol_id` | `qualifyContracts()` fills in `conId` |
| **Order monitoring** | Poll via `get_user_account_orders()` | Live events via `orderStatusEvent` / `execDetailsEvent` |

### 5E. Handling the Connection Lifecycle

The biggest architectural difference: SnapTrade is stateless REST; IBKR requires a persistent socket connection.

**Approach: Connection pool / singleton managed at the service level.**

```
IBKRConnectionManager (singleton)
    |
    ├── connect()         # Connect to IB Gateway on startup
    ├── disconnect()      # Clean shutdown
    ├── ensure_connected() # Lazy connect + health check
    ├── get_ib()          # Return the IB() instance
    └── Events:
        ├── on_disconnect  # Auto-reconnect logic
        └── on_error       # Log and alert
```

The `IBKRBrokerAdapter` would use this manager to get a connected `IB()` instance. The connection would be established lazily on first IBKR trade and kept alive. Reconnection on disconnect would be automatic.

This is fundamentally different from SnapTrade where each API call is independent. The connection manager abstracts this difference away from the `TradeExecutionService`.

### 5F. Database Schema Changes

The existing `trade_previews` and `trade_orders` tables can be reused with minimal changes:

**trade_previews:**
- `snaptrade_trade_id` --> Already nullable, works for IBKR (will be NULL)
- `universal_symbol_id` --> Reuse for IBKR's `conId` (contract ID), or add a `broker_symbol_id` column
- Add: `broker_provider VARCHAR(20) NOT NULL DEFAULT 'snaptrade'` -- to distinguish which broker path to use on execute
- Add: `broker_preview_data JSONB` -- generic column for broker-specific preview data (IBKR's `OrderState` from `whatIfOrder`, or SnapTrade's full impact response)

**trade_orders:**
- `brokerage_order_id` --> Works for both (SnapTrade's order ID or IBKR's `orderId`)
- `order_status` --> Need to map IBKR statuses to a common enum (see below)
- Add: `broker_provider VARCHAR(20)` -- to identify the execution broker
- `brokerage_response JSONB` --> Works for both

**Order status mapping:**

| SnapTrade Status | IBKR Status | Common Status |
|-----------------|-------------|---------------|
| PENDING | PreSubmitted | PENDING |
| ACCEPTED | Submitted | ACCEPTED |
| EXECUTED | Filled | EXECUTED |
| PARTIAL | PartiallyFilled | PARTIAL |
| CANCELED | Cancelled | CANCELED |
| REJECTED | Inactive | REJECTED |
| FAILED | ApiCancelled / Error | FAILED |
| EXPIRED | -- | EXPIRED |

### 5G. Preview -> Execute Flow for IBKR

The IBKR flow differs from SnapTrade because there is no linked `trade_id` between preview and execution:

```
preview_trade(ticker="AAPL", quantity=10, side="BUY", account_id=IB_ACCOUNT)
    |
    v
IBKRBrokerAdapter.preview_order()
    ├── qualifyContracts(Stock('AAPL', 'SMART', 'USD'))
    ├── whatIfOrder(contract, LimitOrder('BUY', 10, 150.00))
    ├── Returns: commission, margin impact, equity impact
    |
    v
TradeExecutionService stores preview in DB (with broker_provider='ibkr')
    - snaptrade_trade_id = NULL (not applicable)
    - broker_preview_data = {whatIfOrder response}
    - Stores all order params for re-construction at execute time
    |
    v
Returns preview_id to user

execute_trade(preview_id)
    |
    v
TradeExecutionService loads preview from DB
    ├── Checks expiry (our own 5-min window, even though IBKR has no expiry)
    ├── Sees broker_provider='ibkr'
    ├── Reconstructs order from stored params
    |
    v
IBKRBrokerAdapter.place_order()
    ├── qualifyContracts(contract)  # Re-qualify
    ├── placeOrder(contract, order)
    ├── Wait for fill (or return PENDING status)
    ├── Returns: orderId, status, fill details
    |
    v
TradeExecutionService stores execution in trade_orders
```

Key insight: Since IBKR's `whatIfOrder` is stateless (no trade_id linking preview to execution), we store the full order parameters in the preview row and reconstruct the order at execution time. Our own preview_id + expiry window provides the safety guarantee.

### 5H. What Can Be Shared vs. What Must Be Broker-Specific

**Shared (broker-agnostic):**
- Pre-trade validation logic (buying power check, position check for sells, concentration limits, order size limits)
- DB persistence layer (trade_previews, trade_orders)
- Preview expiry and idempotency controls (row locking, unique preview_id)
- Risk impact calculation (weight changes)
- MCP tool interface (same preview_trade / execute_trade tools)
- Kill switch and safety guards
- Audit trail

**Broker-specific (in adapter):**
- Symbol resolution (SnapTrade's `symbol_search` vs IBKR's `qualifyContracts`)
- Preview API call (SnapTrade's `get_order_impact` vs IBKR's `whatIfOrder`)
- Order placement (SnapTrade's `place_order(trade_id)` vs IBKR's `placeOrder(contract, order)`)
- Order status retrieval and status mapping
- Post-trade position refresh mechanism
- Connection management (stateless REST vs persistent socket)
- Account/balance resolution

---

## 6. Implementation Plan Sketch

### Phase 1: Infrastructure

1. **IBKRConnectionManager** -- Singleton managing ib_async connection to IB Gateway.
   - Lazy connect, auto-reconnect, health check.
   - Configuration via settings.py (`IBKR_GATEWAY_HOST`, `IBKR_GATEWAY_PORT`, `IBKR_CLIENT_ID`).

2. **BrokerAdapter abstract class** -- Define the common interface.

3. **SnapTradeBrokerAdapter** -- Extract existing SnapTrade logic from `TradeExecutionService` into this adapter. Should be a refactor with no behavior change.

4. **IBKRBrokerAdapter** -- New adapter implementing the interface via `ib_async`.

### Phase 2: Database

5. **Migration** -- Add `broker_provider` column to `trade_previews` and `trade_orders`. Add `broker_preview_data` JSONB column to `trade_previews`.

### Phase 3: Service Layer Refactor

6. **TradeExecutionService refactor** -- Route to the correct adapter based on account provider:
   - Detect provider from account_id (existing `_detect_account_provider()` method)
   - IB accounts --> `IBKRBrokerAdapter`
   - SnapTrade accounts --> `SnapTradeBrokerAdapter`

7. **Account resolution** -- Extend `list_tradeable_accounts()` to include IBKR accounts (fetched via `ib_async` `managedAccounts()`).

### Phase 4: Testing

8. **Paper trading** -- Test full flow against IB paper trading account (port 4002).
9. **Live small order** -- Verify with a minimal live order.

### Estimated Effort

| Phase | Work |
|-------|------|
| Phase 1 (Infrastructure) | 2-3 days |
| Phase 2 (Database) | 0.5 day |
| Phase 3 (Service refactor) | 2-3 days |
| Phase 4 (Testing) | 1-2 days |
| **Total** | **~6-8 days** |

---

## 7. Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| **IB Gateway goes down** | High | Auto-reconnect in `IBKRConnectionManager`. IBKR trades fail gracefully with clear error. SnapTrade trades unaffected. |
| **Weekly 2FA missed** | Medium | IBC sends 2FA to IBKR Mobile app with retry. If missed, gateway enters read-only mode. Orders fail with auth error -- no silent misbehavior. |
| **ib_async library maintenance** | Low | Actively maintained (v2.1.0, Dec 2025). Has 3.6k+ GitHub stars. Community-driven after original author's passing. Fallback: raw `ibapi` SDK from IB. |
| **Socket vs REST impedance mismatch** | Medium | `IBKRConnectionManager` encapsulates the persistent connection. Adapter pattern hides this from the service layer. |
| **Order status mapping** | Low | IBKR has fewer status values than SnapTrade. Mapping is straightforward. |
| **whatIfOrder limitations** | Low | `whatIfOrder` may not return estimated fill price for market orders (only commission/margin). Can supplement with last market price. |
| **MCP server startup** | Medium | IB Gateway connection should be lazy (not blocking server startup). First IBKR trade triggers connection. |

---

## 8. Open Questions — RESOLVED

1. **Account identification:** ✅ Resolved — IBKR uses native account IDs (e.g., `U2471778`). `BrokerAdapter.owns_account()` pattern routes correctly. IBKR account IDs (U-prefix) don't collide with SnapTrade UUIDs.

2. **Position data source:** ✅ Resolved — Positions continue via Plaid for IB (read-only). Trading goes via ib_async. Independent systems, no conflict.

3. **Simultaneous connections:** ✅ Confirmed — Plaid and ib_async coexist fine.

4. **Paper trading account:** ✅ Resolved — Tested directly against live TWS on port 7496 with account U2471778. No separate paper account needed.

5. **IB Gateway hosting:** ✅ Resolved — TWS runs natively on macOS alongside the MCP server. Docker is a future production option.

---

## 9. Sources

- [IBKR Trading API Solutions](https://www.interactivebrokers.com/en/trading/ib-api.php)
- [TWS API Documentation](https://interactivebrokers.github.io/tws-api/introduction.html)
- [IBKR Web API v1.0 Documentation](https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/)
- [ib_async GitHub (maintained fork of ib_insync)](https://github.com/ib-api-reloaded/ib_async)
- [ib_async API Documentation](https://ib-api-reloaded.github.io/ib_async/api.html)
- [ib_async PyPI](https://pypi.org/project/ib_async/)
- [ib_insync (original, unmaintained)](https://github.com/erdewit/ib_insync)
- [ib_insync PyPI](https://pypi.org/project/ib-insync/)
- [IBind -- IBKR Client Portal API Python client](https://github.com/Voyz/ibind)
- [IBind PyPI](https://pypi.org/project/ibind/)
- [IBC -- IB Gateway/TWS Automation](https://github.com/IbcAlpha/IBC)
- [gnzsnz/ib-gateway-docker](https://github.com/gnzsnz/ib-gateway-docker)
- [IBKR OAuth 1.0a Documentation](https://www.interactivebrokers.com/campus/ibkr-api-page/oauth-1-0a-extended/)
- [IBKR Campus -- Getting Started with APIs](https://www.interactivebrokers.com/campus/ibkr-api-page/getting-started/)
- [TWS API Order Types](https://interactivebrokers.github.io/tws-api/basic_orders.html)
- [IBKR Client Portal API Authentication](https://www.interactivebrokers.com/campus/trading-lessons/launching-and-authenticating-the-gateway/)

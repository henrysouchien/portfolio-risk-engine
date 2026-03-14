# Provider Cost Reduction Plan: Webhook-Driven Refresh Notification

> **Goal:** Add a push-notification layer on top of the existing database-cached position pipeline so users see an "Updates available" badge when Plaid/SnapTrade data changes at the source, and only trigger API calls when they explicitly click "Refresh".

---

## What Already Works (not part of this plan)

The core data pipeline is fully operational:
- **Positions DB**: Holdings from all providers are stored in the `positions` table with `position_source` tagging.
- **24-hour cache**: `PositionService` checks `MAX(created_at)` per provider — no API call if < 24h old.
- **`force_refresh=True`**: Programmatic bypass for the cache when needed.
- **Provider-safe writes**: Each provider only deletes/replaces its own rows.

This plan is solely about the **webhook → flag → frontend badge → user-initiated refresh** layer.

---

## Implementation Status

### ✅ Webhook Transport (COMPLETE)

Plaid webhook delivery pipeline is fully deployed:
- Public ingress endpoint live at `https://www.financialmodelupdater.com/plaid/webhook` (200 ACK contract).
- `risk_module` webhook handler (`POST /plaid/webhook`) implemented with fast ACK + structured logging.
- Relay hardening via forwarded-header/shared-secret validation in `routes/plaid.py`.
- Relay reliability via durable outbox + retry/replay controls on ingress host.
- `BACKEND_BASE_URL` updated for new Plaid Link token webhook registration.
- Existing Plaid item webhook URLs migrated (active items updated; stale item cleaned up).

### ✅ Webhook → DB Flag → Frontend UX (COMPLETE)

Implemented via `WEBHOOK_REFRESH_NOTIFICATION_PLAN.md`:

1. **DB schema** — Migration run. `has_pending_updates` columns + `provider_items` table live.
2. **SnapTrade webhook wiring** — HMAC-SHA256 auth, event routing, pending flag, POST refresh with cooldown, lazy backfill.
3. **Plaid parity** — Refresh cooldown + `/pending-updates` endpoint added.
4. **Frontend UX** — `usePendingUpdates()` polling hook, amber banner, toast feedback, `refreshHoldings()` with per-provider POST refresh, 429 handling end-to-end, `lastSynced` from real timestamp.

### 🟡 Remaining: SnapTrade Webhook Relay

One deployment step remains: add a SnapTrade route to the existing Plaid webhook relay so SnapTrade can reach the backend. See `docs/planning/WEBHOOK_RELAY_SETUP.md` for instructions.

---

## Problem Statement

**Original State (before Phase 1):**
- Every call to `GET /plaid/holdings` or `GET /snaptrade/holdings` triggers fresh API calls
- Plaid: 2 API calls per institution (`/investments/holdings` + `/accounts/balance`)
- With 3 connected institutions = 6 API calls per page load
- Plaid charges per API call, costs add up quickly
- Webhook endpoints exist but do nothing (just log)
- Webhook URL is `localhost` so Plaid can't reach it anyway

**Target State:**
- Page loads read from database (FREE, instant)
- Webhooks (FREE) notify us when data changes at the source
- User sees "Updates available" badge when webhook fires
- API calls ONLY when user clicks "Refresh" button
- User controls when to spend money on API calls

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     SIMPLIFIED FLOW                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   1. USER LOADS PAGE                                             │
│      └─→ GET /plaid/holdings                                     │
│          └─→ Read from database (FREE)                           │
│          └─→ Return cached data + has_pending_updates flag       │
│                                                                  │
│   2. WEBHOOK FIRES (when holdings change at brokerage)           │
│      └─→ POST /plaid/webhook (Plaid calls us - FREE to receive)  │
│          └─→ Look up user by item_id                             │
│          └─→ Set has_pending_updates = true                      │
│          └─→ Done (no API call)                                  │
│                                                                  │
│   3. USER CLICKS "REFRESH"                                       │
│      └─→ POST /plaid/holdings/refresh                            │
│          └─→ Call Plaid API ($$$ - only time we pay)             │
│          └─→ Store in database (positions.created_at = NOW)      │
│          └─→ Set has_pending_updates = false                     │
│          └─→ Return fresh data                                   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**Same pattern applies to SnapTrade.**

---

## Cost Impact

| Action | Before (Current) | After (New) |
|--------|------------------|-------------|
| Page load | 6 API calls (3 inst × 2) | 0 (FREE) |
| Webhook received | N/A (not working) | 0 (FREE) |
| User clicks Refresh | N/A | 6 API calls |

**Example savings (per user, per day):**
- Before: 10 page loads × 6 calls = **60 API calls/day**
- After: 1-2 manual refreshes × 6 calls = **6-12 API calls/day**
- **~80-90% reduction in API costs**

---

## Database Schema Changes

> **Note:** Cache timing is now handled via `MAX(created_at)` from the positions table
> (see Phase 1 implementation). The `*_synced_at` columns below are optional.
> Only the `*_has_pending_updates` columns are required for Phase 2 webhooks.

### Migration 1: Add webhook flags to `portfolios` table

```sql
-- Migration: 20250129_add_provider_webhook_flags.sql

ALTER TABLE portfolios
ADD COLUMN plaid_has_pending_updates BOOLEAN DEFAULT FALSE,
ADD COLUMN snaptrade_has_pending_updates BOOLEAN DEFAULT FALSE;

COMMENT ON COLUMN portfolios.plaid_has_pending_updates IS 'Webhook indicated new Plaid data available';
COMMENT ON COLUMN portfolios.snaptrade_has_pending_updates IS 'Webhook indicated new SnapTrade data available';

-- Note: Cache timing uses MAX(created_at) FROM positions WHERE position_source='provider'
-- No need for plaid_synced_at / snaptrade_synced_at columns
```

### Migration 2: Add `provider_items` table (for webhook → user lookup)

Webhooks only send `item_id`, we need to know which user it belongs to.

```sql
-- Migration: 20250129_add_provider_items.sql

CREATE TABLE provider_items (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider VARCHAR(50) NOT NULL,  -- 'plaid' or 'snaptrade'
    item_id VARCHAR(255) NOT NULL,  -- Plaid item_id or SnapTrade authorization_id
    institution_name VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    UNIQUE (provider, item_id)
);

CREATE INDEX idx_provider_items_lookup ON provider_items (provider, item_id);
CREATE INDEX idx_provider_items_user ON provider_items (user_id, provider);
```

---

## Backend Code Changes

### 1. `inputs/database_client.py` - New Methods

> **Note:** Cache timing is handled via `MAX(created_at)` from positions table.
> The methods below are only for webhook pending update flags (Phase 2).

```python
# ============================================================
# WEBHOOK PENDING UPDATES (Phase 2)
# ============================================================
# Cache timing uses: MAX(created_at) FROM positions WHERE position_source='provider'
# No additional database methods needed for cache timing.

def get_pending_updates(self, user_id: int, portfolio_name: str, provider: str) -> bool:
    """Check if webhook flagged pending updates."""
    column = f"{provider}_has_pending_updates"
    with self.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT {column} FROM portfolios WHERE user_id = %s AND name = %s",
            (user_id, portfolio_name)
        )
        result = cursor.fetchone()
        return bool(result[column]) if result else False


def set_pending_updates(self, user_id: int, portfolio_name: str, provider: str, has_updates: bool) -> None:
    """Set or clear the pending updates flag."""
    column = f"{provider}_has_pending_updates"
    with self.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"UPDATE portfolios SET {column} = %s WHERE user_id = %s AND name = %s",
            (has_updates, user_id, portfolio_name)
        )
        conn.commit()


# ============================================================
# PROVIDER ITEMS (for webhook lookup)
# ============================================================

def store_provider_item(self, user_id: int, provider: str, item_id: str, institution_name: str = None) -> None:
    """Store provider item_id → user mapping for webhook lookup."""
    with self.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO provider_items (user_id, provider, item_id, institution_name)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (provider, item_id) DO UPDATE SET
                user_id = EXCLUDED.user_id,
                institution_name = EXCLUDED.institution_name
            """,
            (user_id, provider, item_id, institution_name)
        )
        conn.commit()


def get_user_by_provider_item(self, provider: str, item_id: str) -> Optional[Dict]:
    """Look up user from provider item_id (used by webhook handler)."""
    with self.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT u.id as user_id, u.email
            FROM provider_items pi
            JOIN users u ON pi.user_id = u.id
            WHERE pi.provider = %s AND pi.item_id = %s
            """,
            (provider, item_id)
        )
        result = cursor.fetchone()
        return {'user_id': result['user_id'], 'email': result['email']} if result else None


def delete_provider_item(self, provider: str, item_id: str) -> None:
    """Remove provider item (when user disconnects)."""
    with self.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM provider_items WHERE provider = %s AND item_id = %s",
            (provider, item_id)
        )
        conn.commit()
```

---

### 2. `routes/plaid.py` - Modified Routes

#### A. Update Token Exchange (store item_id for webhook lookup)

```python
# In exchange_public_token(), after storing token, add:

# Store item_id → user mapping for webhook lookup
with get_db_session() as conn:
    db_client = DatabaseClient(conn)
    db_client.store_provider_item(
        user_id=user['user_id'],
        provider='plaid',
        item_id=item_id,
        institution_name=institution_name
    )
```

#### B. Modify GET /plaid/holdings (Database-First)

```python
@plaid_router.get("/holdings", response_model=get_response_model(HoldingsResponse))
@log_portfolio_operation_decorator("plaid_get_holdings_cached")
@log_performance(1.0)
async def get_plaid_holdings(request: Request):
    """
    Retrieve holdings from DATABASE (cached).

    This endpoint returns cached data WITHOUT calling Plaid API.
    Use POST /plaid/holdings/refresh to fetch fresh data.

    Response includes:
    - holdings: Cached positions from database
    - last_synced: When data was last refreshed (from MAX(created_at) of positions)
    - has_pending_updates: True if webhook indicated new data available
    """
    # Authentication
    session_id = request.cookies.get('session_id')
    user = auth_service.get_user_by_session(session_id)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        # Load from database only - NO API CALL
        portfolio_manager = PortfolioManager(use_database=True, user_id=user['user_id'])

        try:
            positions = portfolio_manager.load_portfolio("CURRENT_PORTFOLIO")
        except PortfolioNotFoundError:
            # No cached data yet
            return HoldingsResponse(
                success=True,
                holdings=None,
                message="No cached holdings. Click Refresh to sync from Plaid."
            )

        # Get sync metadata
        with get_db_session() as conn:
            db_client = DatabaseClient(conn)
            # Cache timing: MAX(created_at) FROM positions WHERE position_source='plaid'
            cursor = conn.cursor()
            cursor.execute(
                "SELECT MAX(created_at) as last_sync FROM positions WHERE portfolio_id = %s AND position_source = 'plaid'",
                (portfolio_id,)
            )
            result = cursor.fetchone()
            last_synced = result['last_sync'] if result else None
            has_pending_updates = db_client.get_pending_updates(user['user_id'], "CURRENT_PORTFOLIO", "plaid")

        # Build response (reuse existing format)
        # ... existing holdings formatting logic ...

        return HoldingsResponse(
            success=True,
            holdings={
                "portfolio_data": portfolio_data,
                "portfolio_metadata": {
                    "portfolio_name": "CURRENT_PORTFOLIO",
                    "source": "database",
                    "last_synced": last_synced.isoformat() if last_synced else None,
                    "has_pending_updates": has_pending_updates,
                }
            },
            message="Holdings retrieved from cache" + (" (updates available)" if has_pending_updates else "")
        )

    except Exception as e:
        log_error_json("plaid_holdings", "get_holdings_cached", e)
        raise HTTPException(status_code=500, detail=str(e))
```

#### C. Add POST /plaid/holdings/refresh (Triggers API Call)

```python
@plaid_router.post("/holdings/refresh", response_model=get_response_model(HoldingsResponse))
@log_portfolio_operation_decorator("plaid_refresh_holdings")
@log_api_health("Plaid", "holdings_refresh")
@log_performance(10.0)
async def refresh_plaid_holdings(request: Request):
    """
    Fetch FRESH holdings from Plaid API.

    This endpoint makes actual Plaid API calls (costs money).
    Called when user explicitly clicks "Refresh" button.
    """
    # Authentication
    session_id = request.cookies.get('session_id')
    user = auth_service.get_user_by_session(session_id)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        # ===== EXISTING PLAID FETCH LOGIC (moved from GET) =====

        # Step 1: Load all user holdings from all connected accounts
        holdings_df = load_all_user_holdings(
            user_id=user['email'],
            region_name="us-east-1",
            client=plaid_client
        )

        if holdings_df.empty:
            return HoldingsResponse(
                success=True,
                holdings=None,
                message="No holdings found. Connect a brokerage account first."
            )

        # Step 2: Process holdings (existing logic)
        institution_totals = holdings_df.groupby('institution')['value'].sum().to_dict()
        holdings_df = consolidate_holdings(holdings_df)

        # Step 3: Store in database
        portfolio_manager = PortfolioManager(use_database=True, user_id=user['user_id'])
        portfolio_data = convert_plaid_holdings_to_portfolio_data(
            holdings_df,
            user_email=user['email'],
            portfolio_name="CURRENT_PORTFOLIO"
        )
        portfolio_manager.save_portfolio_data(portfolio_data)

        # Step 4: Clear pending flag (sync time is automatic via positions.created_at)
        with get_db_session() as conn:
            db_client = DatabaseClient(conn)
            db_client.set_pending_updates(user['user_id'], "CURRENT_PORTFOLIO", "plaid", False)

        # Step 5: Return fresh data (existing format)
        # ... existing response building logic ...
        # Note: last_synced = NOW because positions were just inserted with created_at = NOW

        return HoldingsResponse(
            success=True,
            holdings={
                "portfolio_data": portfolio_data_dict,
                "portfolio_metadata": {
                    "portfolio_name": "CURRENT_PORTFOLIO",
                    "source": "plaid",
                    "last_synced": datetime.now().isoformat(),
                    "has_pending_updates": False,
                }
            },
            message="Holdings refreshed from Plaid"
        )

    except Exception as e:
        log_error_json("plaid_holdings", "refresh_holdings", e)
        raise HTTPException(status_code=500, detail=str(e))
```

#### D. Update Webhook Handler (Set Pending Flag)

```python
@plaid_router.post("/webhook")
@log_portfolio_operation_decorator("plaid_webhook")
async def plaid_webhook(webhook_data: WebhookRequest):
    """
    Handle Plaid webhook - FREE notification that data changed.

    When Plaid sends us a webhook, we just set a flag.
    User will see "Updates available" on next page load.
    """
    try:
        webhook_type = webhook_data.webhook_type
        webhook_code = webhook_data.webhook_code
        item_id = webhook_data.item_id

        portfolio_logger.info(f"📨 Plaid webhook: {webhook_type}.{webhook_code} for item {item_id}")

        # Handle holdings update webhooks
        if webhook_type == "INVESTMENTS" and webhook_code in ["DEFAULT_UPDATE", "HOLDINGS_UPDATE"]:

            # Look up user by item_id
            with get_db_session() as conn:
                db_client = DatabaseClient(conn)
                user_info = db_client.get_user_by_provider_item("plaid", item_id)

            if not user_info:
                portfolio_logger.warning(f"⚠️ No user found for Plaid item_id: {item_id}")
                return {"success": True}

            # Set pending updates flag
            with get_db_session() as conn:
                db_client = DatabaseClient(conn)
                db_client.set_pending_updates(
                    user_info['user_id'],
                    "CURRENT_PORTFOLIO",
                    "plaid",
                    True
                )

            portfolio_logger.info(f"🏷️ Set pending updates for user {user_info['user_id']}")

        # Handle error webhooks
        elif webhook_type == "ITEM" and webhook_code == "ERROR":
            portfolio_logger.error(f"❌ Plaid item error: {item_id} - {webhook_data.error}")

        return {"success": True}

    except Exception as e:
        log_error_json("plaid_webhook", "webhook_handler", e)
        return {"success": True}  # Always return 200 to prevent retries
```

---

### 3. `routes/snaptrade.py` - Same Pattern

Apply identical changes:

| Plaid | SnapTrade |
|-------|-----------|
| `GET /plaid/holdings` → DB only | `GET /snaptrade/holdings` → DB only |
| `POST /plaid/holdings/refresh` → API call | `POST /snaptrade/holdings/refresh` → API call |
| `POST /plaid/webhook` → set flag | `POST /snaptrade/webhook` → set flag |
| Store `item_id` on token exchange | Store `authorization_id` on connection |

**SnapTrade webhook types:**
- `ACCOUNT_HOLDINGS_UPDATED` - Holdings changed
- `CONNECTION_BROKEN` - Connection needs re-auth

**Note:** SnapTrade webhooks are disabled by default. Enable in SnapTrade Dashboard → Webhooks.

---

## API Response Format

### GET /plaid/holdings (Cached)

```json
{
  "success": true,
  "holdings": {
    "portfolio_data": {
      "holdings": [...],
      "total_portfolio_value": 150000.00
    },
    "portfolio_metadata": {
      "portfolio_name": "CURRENT_PORTFOLIO",
      "source": "database",
      "last_synced": "2025-01-29T10:30:00Z",
      "has_pending_updates": true
    }
  },
  "message": "Holdings retrieved from cache (updates available)"
}
```

### POST /plaid/holdings/refresh

```json
{
  "success": true,
  "holdings": {
    "portfolio_data": {
      "holdings": [...],
      "total_portfolio_value": 152000.00
    },
    "portfolio_metadata": {
      "portfolio_name": "CURRENT_PORTFOLIO",
      "source": "plaid",
      "last_synced": "2025-01-29T14:00:00Z",
      "has_pending_updates": false
    }
  },
  "message": "Holdings refreshed from Plaid"
}
```

---

## Frontend Changes

### Display Requirements

1. **Show sync time:** "Last synced: 2 hours ago"
2. **Show updates badge:** When `has_pending_updates: true`, show "Updates available" indicator
3. **Refresh button:** Calls `POST /holdings/refresh`
4. **Loading state:** Show spinner while refresh is in progress
5. **No data state:** For new users, show "Click Refresh to sync your holdings"

### Example UI

```
┌─────────────────────────────────────────────────────────────┐
│  Portfolio Holdings                                          │
│  Last synced: 2 hours ago  [Updates available!] [↻ Refresh] │
├─────────────────────────────────────────────────────────────┤
│  AAPL    100 shares    $18,500                              │
│  GOOGL    25 shares    $4,200                               │
│  ...                                                         │
└─────────────────────────────────────────────────────────────┘
```

---

## Deployment Requirements

### Webhook URL Must Be Public

For webhooks to work, Plaid/SnapTrade must be able to reach your backend:

```python
# settings.py - Set to your deployed URL
BACKEND_BASE_URL = os.getenv('BACKEND_BASE_URL', 'https://api.yourapp.com')
```

### Update Existing Connections

Users who connected before deployment have `localhost` as their webhook URL. Options:

1. **Re-link:** Have users disconnect and reconnect (registers new URL)
2. **Update via API:** Use Plaid's `/item/webhook/update` endpoint

```python
# One-time script to update existing items
from plaid.model.item_webhook_update_request import ItemWebhookUpdateRequest

for item in get_all_plaid_items():
    request = ItemWebhookUpdateRequest(
        access_token=item.access_token,
        webhook=f"{BACKEND_BASE_URL}/plaid/webhook"
    )
    plaid_client.item_webhook_update(request)
```

### SnapTrade Webhook Setup

1. Go to SnapTrade Dashboard → Webhooks
2. Add webhook URL: `{BACKEND_BASE_URL}/snaptrade/webhook`
3. Enable `ACCOUNT_HOLDINGS_UPDATED` webhook type

---

## Implementation Phases

### Phase 1: 24-Hour Cache ✅ COMPLETE
- [x] Implement cache check via `MAX(created_at)` from positions
- [x] Per-provider cache timing (Plaid/SnapTrade independent)
- [x] Provider-scoped filtering (`position_source='plaid'` or `'snaptrade'`)
- [x] Market value calculation (`shares × latest_price`)
- [x] Provider-safe database writes

### Phase 2: Database Schema (for webhooks) ✅ COMPLETE
- [x] Create migration for webhook flag columns (`has_pending_updates`)
- [x] Create migration for `provider_items` table
- [x] Run migrations

### Phase 3: DatabaseClient Methods (for webhooks)
- [x] Add `get_pending_updates()`
- [x] Add `set_pending_updates()`
- [x] Add `store_provider_item()`
- [x] Add `get_user_by_provider_item()`
- [x] Add `delete_provider_item()`

### Phase 4: Plaid Routes (for webhooks)
- [x] Update `exchange_public_token` to store item_id
- [x] Modify `GET /plaid/holdings` → database-first (done in Phase 1)
- [x] Add `POST /plaid/holdings/refresh` → force API call
  - Note: `PositionService.get_positions(force_refresh=True)` already exists
- [x] Update webhook handler to set pending flag
- [x] Ensure webhook ingress ACK contract (`POST /plaid/webhook` returns success quickly)
- [x] Add forwarded webhook auth guard (`X-Plaid-Forwarded`, shared secret)

### Phase 5: SnapTrade Routes (for webhooks) ✅ COMPLETE
- [x] Update connection flow to store authorization_id (lazy backfill on GET)
- [x] Modify `GET /snaptrade/holdings` → database-first (done in Phase 1)
- [x] Add `POST /snaptrade/holdings/refresh` → force API call with 60s cooldown
- [x] Update webhook handler to set pending flag (HMAC-SHA256 auth, replay rejection)
- [x] Add `GET /api/snaptrade/pending-updates` lightweight endpoint

### Phase 5: Frontend ✅ COMPLETE
- [x] Show sync timestamp (real backend `last_updated` via `PortfolioSummaryAdapter`)
- [x] Show "Updates available" banner (`usePendingUpdates()` hook, amber banner in `HoldingsView`)
- [x] Add Refresh button (calls POST refresh per-provider)
- [x] Handle loading/error/429 states (toast feedback, 429 preserved end-to-end)

### Phase 6: Deployment & Webhook Setup
- [x] Deploy backend with public URL
- [x] Update `BACKEND_BASE_URL` in production
- [ ] Add SnapTrade route to existing webhook relay (see `WEBHOOK_RELAY_SETUP.md`)
- [ ] Register webhook URL with SnapTrade (dashboard or API)
- [ ] Set `SNAPTRADE_WEBHOOK_SECRET` in `.env`
- [x] Update existing Plaid items with new webhook URL (optional)
  - Note: one stale `ITEM_NOT_FOUND` item was removed during cleanup.

### Phase 7: Testing
- [x] Test cached reads work
- [x] Test refresh triggers API call
- [x] Test webhook sets pending flag
- [x] Test flag clears after refresh
- [x] End-to-end test with real webhooks (ingress/forwarding transport)

---

## Related Documents

- [Position Module Plan](./POSITION_MODULE_PLAN.md) - Overall position architecture
- [Backend Architecture](../architecture/legacy/backend_architecture.md) - System design

---

*Created: 2025-01-29*
*Updated: 2026-02-19*
*Status: All code complete (Phases 1–5, 7). Remaining: deploy SnapTrade webhook relay route + register URL with SnapTrade + set SNAPTRADE_WEBHOOK_SECRET (Phase 6 — see WEBHOOK_RELAY_SETUP.md).*

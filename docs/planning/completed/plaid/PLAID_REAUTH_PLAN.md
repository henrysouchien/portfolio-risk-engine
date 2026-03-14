# Plaid Re-Authentication (Update Mode) — Implementation Plan

**Date:** 2026-02-24
**Status:** Complete — implemented and tested 2026-02-24. Passed 9 Codex review rounds.

## Problem

When a Plaid connection's OAuth token expires, the API returns `ITEM_LOGIN_REQUIRED`. The current codebase only supports creating **new** connections — there is no way to re-authenticate an existing one. This forces users to disconnect and reconnect, losing the original item history.

## How Plaid Update Mode Works

Plaid Link supports an "update mode" that lets users re-authenticate an existing connection:

1. Create a `LinkTokenCreateRequest` with the existing `access_token` and **without** `products`
2. Plaid generates a hosted Link URL in update mode
3. The user completes re-authentication in the browser
4. The existing `access_token` is automatically restored — **no token exchange needed**

Reference: [Plaid Link Update Mode docs](https://plaid.com/docs/link/update-mode/)

## Current State

| Component | Status |
|-----------|--------|
| `create_hosted_link_token()` | Create mode only — always passes `products`, never `access_token` |
| Webhook handler (`ITEM.ERROR`) | Logs errors but does not detect `ITEM_LOGIN_REQUIRED` |
| `/plaid/connections` endpoint | Returns `status: "active"` for all connections — no reauth awareness |
| `provider_items` table | Stores `item_id` + `institution_name` but no reauth flag |
| Secrets Manager payloads | Each secret stores `{ access_token, item_id, institution, user_id }` — keyed by institution slug but `item_id` is in the payload |
| Webhook auth | `_validate_plaid_webhook_forward_auth()` only enforces if `PLAID_WEBHOOK_FORWARD_SHARED_SECRET` is set |
| Frontend | No re-auth button or stale-connection detection |

## Global Convention: AWS Region

All Secrets Manager calls in this plan (Steps 2, 6, 7, 8, 10) must use `AWS_DEFAULT_REGION` from `brokerage.config` — never hardcoded `"us-east-1"`. This matches the existing pattern in `routes/plaid.py` which should also be migrated to use the config value (currently hardcoded, but that's a pre-existing issue outside this plan's scope).

The CLI script (Step 10) should import `AWS_DEFAULT_REGION` from `brokerage.config` or accept `--region` as a CLI arg with the config value as default.

## Implementation

### Step 1: `brokerage/plaid/client.py` — Add `create_update_link_token()`

New function alongside existing `create_hosted_link_token()`:

```python
def create_update_link_token(
    client: "plaid_api.PlaidApi",
    access_token: str,
    user_id: str,
    redirect_uri: str = "https://yourapp.com/plaid/complete",
    webhook_uri: str = "https://yourapp.com/plaid/webhook",
    client_name: str = "Risk Analysis App",
    is_mobile_app: bool = False,
) -> dict:
    """Create a Plaid Link token in update mode for re-authentication."""
    _require_plaid_sdk()

    req = LinkTokenCreateRequest(
        user=LinkTokenCreateRequestUser(client_user_id=user_id),
        client_name=client_name,
        # NO products — update mode must omit products
        access_token=access_token,  # Triggers update mode
        country_codes=[CountryCode("US")],
        language="en",
        hosted_link={
            "completion_redirect_uri": redirect_uri,
            "is_mobile_app": is_mobile_app,
        },
        webhook=webhook_uri,
    )

    resp = client.link_token_create(req)
    return {
        "link_token": resp.link_token,
        "hosted_link_url": resp.hosted_link_url,
    }
```

**Why a separate function** (not adding params to existing): Cleaner separation, no risk of accidentally passing `access_token` + `products` together (which Plaid rejects).

**Update `__all__`** in `brokerage/plaid/client.py` to export the new function.

### Step 1b: `plaid_loader.py` — Re-export the new function

Routes import Plaid helpers via `plaid_loader`, not directly from `brokerage/plaid/client.py`. Add `create_update_link_token` to the import/re-export in `plaid_loader.py`:

```python
from brokerage.plaid.client import (
    client,
    create_client,
    create_hosted_link_token,
    create_update_link_token,  # NEW
    ...
)
```

And add to `routes/plaid.py` import block (~line 154):

```python
from plaid_loader import (
    ...
    create_update_link_token,  # NEW
)
```

### Step 2: `brokerage/plaid/secrets.py` — Add `get_plaid_token_by_item_id()`

The existing `get_plaid_token()` looks up secrets by institution slug. But institution-slug lookup is ambiguous if duplicate items exist (Plaid docs acknowledge duplicate items can happen). Since each secret payload already contains `item_id`, we add a function that scans all user secrets and matches by `item_id`:

```python
def get_plaid_token_by_item_id(user_id: str, item_id: str, region_name: str) -> dict:
    """Retrieve Plaid token payload by item_id (unambiguous lookup).

    Iterates all secrets for the user and returns the one whose payload
    contains the matching item_id. Raises KeyError if not found.
    """
    _require_boto3()
    token_paths = list_user_tokens(user_id, region_name)

    session = boto3.session.Session()
    client = session.client("secretsmanager", region_name=region_name)

    for path in token_paths:
        try:
            response = client.get_secret_value(SecretId=path)
            payload = json.loads(response["SecretString"])
            if payload.get("item_id") == item_id:
                return payload
        except ClientError as exc:
            # Only swallow "not found" — propagate auth/infra errors
            if exc.response["Error"]["Code"] == "ResourceNotFoundException":
                continue
            raise

    raise KeyError(f"No Plaid token found for item_id={item_id}")
```

**Re-export** from `plaid_loader.py` and add to `routes/plaid.py` imports.

This eliminates the institution-name ambiguity entirely — we look up by `item_id` directly, not by institution slug.

### Step 3: `inputs/database_client.py` — New DB methods

Add two methods to `DatabaseClient`, following existing patterns (e.g. `store_provider_item`, `get_user_by_provider_item`):

```python
def list_provider_items_for_user(self, user_id: int, provider: str) -> List[Dict]:
    """List all provider items for a given user and provider."""
    with self.get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT item_id, institution_name, needs_reauth, created_at, updated_at
                FROM provider_items
                WHERE user_id = %s AND provider = %s
                ORDER BY created_at
                """,
                (user_id, str(provider or "").strip().lower()),
            )
            return [dict(r) for r in cursor.fetchall()]
        except Exception as e:
            msg = str(e).lower()
            if "relation" in msg and "does not exist" in msg and "provider_items" in msg:
                return []
            # If needs_reauth column missing, retry without it
            if "needs_reauth" in msg and "does not exist" in msg:
                cursor.execute(
                    """
                    SELECT item_id, institution_name, created_at, updated_at
                    FROM provider_items
                    WHERE user_id = %s AND provider = %s
                    ORDER BY created_at
                    """,
                    (user_id, str(provider or "").strip().lower()),
                )
                return [dict(r) for r in cursor.fetchall()]
            raise

def set_provider_item_reauth(self, provider: str, item_id: str, needs_reauth: bool) -> None:
    """Mark a provider item as needing re-authentication."""
    with self.get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE provider_items SET needs_reauth = %s, updated_at = NOW()
                WHERE provider = %s AND item_id = %s
                """,
                (needs_reauth, str(provider or "").strip().lower(), item_id),
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            msg = str(e).lower()
            if "needs_reauth" in msg and "does not exist" in msg:
                return  # Column not yet migrated — silent no-op
            raise
```

### Step 4: Database migration — Add `needs_reauth` column

**New file:** `database/migrations/20260224_add_provider_item_reauth_flag.sql`

```sql
-- Rollout-safe: ADD COLUMN IF NOT EXISTS is non-blocking on small tables.
-- provider_items is a low-row-count table (one row per brokerage connection),
-- so this is safe without concurrent index tricks.
ALTER TABLE provider_items
    ADD COLUMN IF NOT EXISTS needs_reauth BOOLEAN NOT NULL DEFAULT FALSE;
```

**Note:** `provider_items` is a tiny table (typically <10 rows per user, <100 rows total). `ADD COLUMN ... DEFAULT` is safe and fast at this scale. If this were a large table, we'd need `ADD COLUMN ... NULL` + backfill + `SET NOT NULL`, but that's unnecessary here.

### Step 5: `routes/plaid.py` — Webhook handler enhancement

**5a. Set `needs_reauth` on `ITEM_LOGIN_REQUIRED`**

In the `ITEM.ERROR` webhook branch (~line 1222):

```python
if webhook_code == "ERROR":
    error_data = webhook_data.error or {}
    error_code = error_data.get("error_code", "")
    if error_code == "ITEM_LOGIN_REQUIRED":
        portfolio_logger.warning(
            f"Plaid ITEM_LOGIN_REQUIRED for item_id={item_id} — marking for re-auth"
        )
        _set_provider_item_reauth(item_id, True)
    else:
        portfolio_logger.error(
            f"Plaid item error for item_id={item_id}: code={error_code}"
        )
```

**5b. Clear `needs_reauth` on `LOGIN_REPAIRED`**

Plaid sends `LOGIN_REPAIRED` after the user successfully re-authenticates. This is the **only** reliable signal of success (Hosted Link popup close is NOT reliable — user may cancel).

```python
elif webhook_code == "LOGIN_REPAIRED":
    portfolio_logger.info(
        f"Plaid LOGIN_REPAIRED for item_id={item_id} — clearing re-auth flag"
    )
    _set_provider_item_reauth(item_id, False)
```

**5c. Set flag on `PENDING_EXPIRATION`**

```python
elif webhook_code == "PENDING_EXPIRATION":
    portfolio_logger.warning(
        f"Plaid PENDING_EXPIRATION for item_id={item_id} — marking for re-auth"
    )
    _set_provider_item_reauth(item_id, True)
```

**Helper function** (follows existing `_store_plaid_item_mapping` pattern at line 244):

```python
def _set_provider_item_reauth(item_id: str, needs_reauth: bool) -> None:
    """Set or clear the needs_reauth flag for a provider item."""
    if not item_id:
        return
    try:
        with get_db_session() as conn:
            db_client = DatabaseClient(conn)
            db_client.set_provider_item_reauth("plaid", item_id, needs_reauth)
    except Exception as e:
        portfolio_logger.warning(
            f"Failed to set reauth flag for item_id={item_id}: {e}"
        )
```

**Webhook auth note:** Webhook authenticity is enforced by `_validate_plaid_webhook_forward_auth()` when `PLAID_WEBHOOK_FORWARD_SHARED_SECRET` is set. For production, this env var **must** be configured to prevent spoofed webhooks from clearing the reauth flag. This is an existing concern (not introduced by this feature) — document as a prerequisite in deployment notes.

### Step 6: `routes/plaid.py` — New endpoint `POST /plaid/create_update_link_token`

**Token lookup by `item_id` directly** using `get_plaid_token_by_item_id()` — no institution-name ambiguity.

```python
class UpdateLinkTokenRequest(BaseModel):
    item_id: str

@plaid_router.post("/create_update_link_token", response_model=get_response_model(LinkTokenResponse))
@log_operation("plaid_create_update_link_token")
@log_timing(3.0)
@log_errors("high")
async def create_update_link_token_endpoint(body: UpdateLinkTokenRequest, request: Request):
    # 1. Authenticate user (matches existing pattern at line 512)
    from services.auth_service import auth_service
    session_id = request.cookies.get('session_id')
    user = auth_service.get_user_by_session(session_id)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    # 2. Verify item belongs to this user via provider_items
    try:
        with get_db_session() as conn:
            db_client = DatabaseClient(conn)
            owner = db_client.get_user_by_provider_item("plaid", body.item_id)
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to verify item ownership")

    if not owner or owner["user_id"] != user["user_id"]:
        raise HTTPException(status_code=404, detail="Item not found")

    # 3. Fetch access_token by item_id (unambiguous — no institution slug needed)
    from brokerage.config import AWS_DEFAULT_REGION  # configured region, not hardcoded
    try:
        token_data = get_plaid_token_by_item_id(
            user["email"], body.item_id, region_name=AWS_DEFAULT_REGION
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Connection credentials not found")
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to retrieve connection credentials")

    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(status_code=500, detail="Connection credentials incomplete")

    # 4. Create update-mode link token
    user_hash = hashlib.sha256(user["email"].encode()).hexdigest()[:16]
    try:
        result = create_update_link_token(
            client=plaid_client,
            access_token=access_token,
            user_id=user_hash,
            redirect_uri=f"{FRONTEND_BASE_URL}/plaid/success",
            webhook_uri=f"{BACKEND_BASE_URL}/plaid/webhook",
            client_name="Portfolio Risk Engine",
        )
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to create re-authentication link")

    # 5. Return link token using existing LinkTokenResponse model
    #    (includes required request_id field — pass empty string to match create flow)
    return LinkTokenResponse(
        success=True,
        link_token=result["link_token"],
        hosted_link_url=result.get("hosted_link_url"),
        request_id=result.get("request_id", ""),
    )
```

**No `/reauth_complete` endpoint.** Re-auth success is confirmed server-side via Plaid's `LOGIN_REPAIRED` webhook (Step 5b). The frontend opens the hosted link URL; when the webhook fires, the flag is cleared automatically.

### Step 7: `routes/plaid.py` — Enhance `/plaid/connections`

Update the existing connections endpoint (~line 519). Instead of joining `provider_items` to secrets via institution-slug normalization (which can drift), read the `item_id` directly from each secret payload and use that to look up `needs_reauth` from `provider_items`:

```python
from brokerage.config import AWS_DEFAULT_REGION

# Create Secrets Manager client with configured region
secrets_client = boto3.client("secretsmanager", region_name=AWS_DEFAULT_REGION)

# Build provider_items lookup by item_id
try:
    with get_db_session() as conn:
        db_client = DatabaseClient(conn)
        provider_items = db_client.list_provider_items_for_user(user["user_id"], "plaid")
    # Keyed by item_id — no institution-slug normalization needed
    reauth_by_item_id = {
        item["item_id"]: item.get("needs_reauth", False)
        for item in provider_items
        if item.get("item_id")
    }
except Exception:
    reauth_by_item_id = {}

# Then in the connection building loop, fetch each secret to get item_id:
for path in token_paths:
    institution_slug = path.split("/")[-1]
    institution_name = institution_slug.replace("-", " ").title()

    # Read item_id directly from the secret payload by path (no slug normalization)
    secret_item_id = ""
    needs_reauth = False
    try:
        response = secrets_client.get_secret_value(SecretId=path)
        payload = json.loads(response["SecretString"])
        secret_item_id = payload.get("item_id", "")
        needs_reauth = reauth_by_item_id.get(secret_item_id, False)
    except Exception as e:
        portfolio_logger.warning(f"Failed to read secret for {institution_slug}: {e}")
        # Graceful degradation — show connection as active with empty item_id

    connections.append({
        "id": institution_slug,          # UNCHANGED — used by disconnect route
        "institution": institution_name,
        "status": "needs_reauth" if needs_reauth else "active",
        "item_id": secret_item_id,       # NEW field — needed for re-auth call
    })
```

**`id` field is unchanged** — it remains the institution slug used by the disconnect route. `item_id` is a separate new field.

**Join strategy:** `item_id` comes from the secret payload (source of truth), then used to look up `needs_reauth` from `provider_items`. No institution-slug normalization coupling.

### Step 8: Legacy/backfill — `provider_items` coverage

Existing connections may lack `provider_items` rows (the table was added after initial Plaid integration). `_store_plaid_item_mapping()` is only called during token exchange (line 747), NOT during holdings refresh — so legacy connections do not self-heal on refresh.

**Behavior without backfill:**
- `/connections` still works — it reads `item_id` from the secret payload directly. But `needs_reauth` defaults to `False` when no `provider_items` row exists (graceful degradation)
- `/create_update_link_token` requires a `provider_items` row for ownership verification. If a user's connection predates the table, the endpoint returns 404

**Backfill strategy (required for full re-auth support):**
Add a one-time backfill script that iterates all Secrets Manager payloads and upserts into `provider_items`:

```python
# scripts/backfill_provider_items.py
# For each user's Plaid secrets:
#   1. Read secret payload (contains item_id, institution, user_id)
#   2. Look up user in DB by email
#   3. Upsert into provider_items(user_id, provider='plaid', item_id, institution_name)
```

**Runtime backfill hook (new):**
Add a `_store_plaid_item_mapping()` call to the `/plaid/holdings/refresh` route handler (line 825+), **after** `PositionService` returns. The hook must be in the route (not in `plaid_loader.py`) because `_store_plaid_item_mapping()` requires a numeric DB `user_id`, which is available in the route handler but not in the loader (which only has the email-style `user_id`). Concretely: after the refresh succeeds, iterate the user's secret paths via `list_user_tokens(user["email"], region_name=AWS_DEFAULT_REGION)`, read each payload to get `item_id` and `institution`, and call `_store_plaid_item_mapping(user["user_id"], item_id, institution_name)`. This ensures the `provider_items` mapping exists for any connection that was created before the table was added.

### Step 9: Frontend changes (4 files)

**9a. `frontend/packages/chassis/src/services/PlaidService.ts`**

Add one service method:

```typescript
async createUpdateLinkToken(itemId: string): Promise<LinkTokenApiResponse> {
    return this.request<LinkTokenApiResponse>('/plaid/create_update_link_token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ item_id: itemId })
    });
}
```

**9b. `frontend/packages/chassis/src/services/APIService.ts`**

`usePlaid` calls methods on the `APIService` facade (e.g., `api.createLinkToken()`), not directly on `PlaidService`. Add a forwarding method to `APIService` (~line 303, after `createLinkToken`):

```typescript
async createUpdateLinkToken(itemId: string): Promise<LinkTokenApiResponse> {
    return this.plaidService.createUpdateLinkToken(itemId);
}
```

**9c. `frontend/packages/connectors/src/features/external/hooks/usePlaid.ts`**

Add `reauthConnection(itemId)` mutation:
1. Call `api.createUpdateLinkToken(itemId)` to get hosted link URL
2. Open popup window (same pattern as existing `PlaidLinkButton`)
3. On popup close, **refetch connections after a short delay** (do NOT assert success — wait for webhook to clear the flag via polling or refetch)
4. If the webhook hasn't fired yet, the connection still shows "needs_reauth" — correct behavior

**9d. `frontend/packages/ui/src/components/settings/AccountConnections.tsx`**

The `ConnectionInfo` type currently allows `status: "connected" | "error" | "syncing" | "disconnected"` (line 165). Changes needed:

1. **Add `itemId` field** to `ConnectionInfo` interface (the Plaid `item_id` — distinct from the `id` slug field used for disconnect):
   ```typescript
   itemId?: string  // Plaid item_id — used for re-auth, NOT the institution slug
   ```

2. **Extend the status union type** to include `"needs_reauth"`:
   ```typescript
   status: "connected" | "error" | "syncing" | "disconnected" | "needs_reauth"
   ```

3. **Add amber badge rendering** for `needs_reauth` status (alongside existing badge logic for connected/error/etc.)

4. **Add "Re-authenticate" action button** — appears only when `status === "needs_reauth"`. Calls `onReauth(itemId)` callback prop.

5. **Add `onReauth` callback prop** to `AccountConnections` component interface:
   ```typescript
   onReauth?: (itemId: string) => void
   ```

6. **`AccountConnectionsContainer.tsx`**:
   - Update `mapConnectionStatus()` to map backend `"needs_reauth"` to the new status value
   - Pass `item_id` from the connections API response through to each connection card
   - Wire `onReauth` prop: call `usePlaid().reauthConnection(itemId)` from the container, pass as callback to the presentational component

### Step 10: CLI re-authentication script

**New file:** `scripts/plaid_reauth.py`

A standalone CLI tool for re-authenticating Plaid connections from the terminal, without needing the frontend. Uses the same backend infrastructure (AWS Secrets Manager, database, Plaid API).

```python
#!/usr/bin/env python3
"""Plaid connection re-authentication CLI.

Usage:
    python scripts/plaid_reauth.py                    # List all connections + status
    python scripts/plaid_reauth.py --reauth           # Interactive: pick a stale connection to re-auth
    python scripts/plaid_reauth.py --reauth --item-id <id>  # Re-auth a specific item

Flow:
    1. Reads all Plaid secrets from AWS Secrets Manager for the configured user
    2. Cross-references provider_items for needs_reauth status
    3. For re-auth: calls create_update_link_token() to get a hosted link URL
    4. Prints the URL (or opens it in the default browser via webbrowser.open())
    5. Waits for user to confirm completion
    6. Optionally verifies item health via Plaid /item/get API
"""
import argparse
import os
import sys
import webbrowser

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brokerage.config import AWS_DEFAULT_REGION
from brokerage.plaid.client import create_client, create_update_link_token
from brokerage.plaid.secrets import list_user_tokens, get_plaid_token_by_item_id


def list_connections(user_email: str) -> list[dict]:
    """List all Plaid connections with their status."""
    # 1. Get all secret paths for user
    # 2. Read each secret payload (has item_id, institution, access_token)
    # 3. Cross-reference provider_items for needs_reauth flag
    # 4. Print table: institution | item_id | status
    ...


def reauth_connection(user_email: str, item_id: str) -> None:
    """Generate re-auth URL and open in browser."""
    # 1. get_plaid_token_by_item_id() — fetch access_token from Secrets Manager
    # 2. create_update_link_token() — get hosted link URL from Plaid
    # 3. Print URL + open in default browser via webbrowser.open()
    # 4. Wait for user input ("Press Enter after completing re-authentication...")
    # 5. Optionally: call Plaid /item/get to verify item is healthy
    #    and clear needs_reauth flag in DB if so
    ...


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Plaid connection re-authentication")
    parser.add_argument("--email", default=None, help="User email (defaults to settings)")
    parser.add_argument("--reauth", action="store_true", help="Start re-auth flow")
    parser.add_argument("--item-id", default=None, help="Specific item_id to re-auth")
    parser.add_argument("--region", default=AWS_DEFAULT_REGION, help="AWS region (default: from config)")
    parser.add_argument("--no-browser", action="store_true", help="Print URL only, don't open browser")
    args = parser.parse_args()
    ...
```

**Key design points:**

- **Same infrastructure:** Calls the same `create_update_link_token()` and `get_plaid_token_by_item_id()` functions as the HTTP endpoint — same AWS Secrets Manager, same Plaid SDK, same DB
- **No HTTP layer needed:** Imports Python functions directly, no need for the FastAPI server to be running
- **Browser opening:** Uses `webbrowser.open()` to launch the hosted link URL. Falls back to printing the URL if `--no-browser` is passed
- **Post-reauth verification:** After the user completes re-auth, can optionally call Plaid's `/item/get` to verify the item is healthy and clear the `needs_reauth` flag in the DB directly (doesn't have to wait for the webhook)
- **Usable from Claude Code / terminal sessions:** When an MCP `get_positions` call fails with `ITEM_LOGIN_REQUIRED`, you can run this script right from the terminal to fix it

## Edge Cases

| Case | Handling |
|------|----------|
| `needs_reauth` column not yet migrated | DB methods catch column-not-found errors and degrade gracefully (silent no-op for writes, omit field for reads) |
| Duplicate items at same institution | `get_plaid_token_by_item_id()` scans all secrets and matches by `item_id` payload field — no institution ambiguity |
| Item exists in DB but secret was deleted | `get_plaid_token_by_item_id()` raises `KeyError` → endpoint returns "Connection credentials not found" |
| Re-auth success confirmation | Server-side only via `LOGIN_REPAIRED` webhook. No client-asserted completion endpoint |
| User cancels or abandons re-auth popup | `needs_reauth` stays `True` — correct, since the connection is still broken |
| `PENDING_EXPIRATION` webhook | Sets `needs_reauth` flag as early warning |
| `LOGIN_REPAIRED` webhook arrives | Clears `needs_reauth` flag automatically |
| Ownership check on update_link_token | `get_user_by_provider_item()` verifies `user_id` matches session user before proceeding |
| Error response leaking internals | All `except` blocks return generic messages, never `str(e)` or internal paths |
| `id` field in `/connections` response | Unchanged (institution slug for disconnect). `item_id` is a separate new field |
| Legacy connections without `provider_items` rows | One-time backfill script required. Also add `_store_plaid_item_mapping()` call to `/holdings/refresh` for runtime self-heal going forward |
| `/connections` join stability | Join uses `item_id` from secret payload → `provider_items` lookup. No institution-slug normalization coupling |
| `get_plaid_token_by_item_id()` error handling | Only swallows `ResourceNotFoundException`. Auth/infra `ClientError`s propagate |
| Webhook auth enforcement | `LOGIN_REPAIRED` clearing the flag depends on webhook authenticity. `PLAID_WEBHOOK_FORWARD_SHARED_SECRET` must be set in production (existing requirement, not new) |
| Missed/delayed `LOGIN_REPAIRED` webhook | Frontend can offer manual "Check status" button that triggers a test API call to Plaid to verify item health (future enhancement, not blocking for v1) |

## File Change Summary

| File | Type | Change |
|------|------|--------|
| `brokerage/plaid/client.py` | Modify | Add `create_update_link_token()`, update `__all__` |
| `brokerage/plaid/secrets.py` | Modify | Add `get_plaid_token_by_item_id()`, update `__all__` |
| `plaid_loader.py` | Modify | Re-export `create_update_link_token` + `get_plaid_token_by_item_id` |
| `inputs/database_client.py` | Modify | Add `list_provider_items_for_user()` + `set_provider_item_reauth()` |
| `database/migrations/20260224_*.sql` | New | Add `needs_reauth` column to `provider_items` |
| `routes/plaid.py` | Modify | 1 new endpoint + webhook enhancement (3 codes) + `/connections` enhancement + `/holdings/refresh` item mapping hook + new imports |
| `frontend/.../PlaidService.ts` | Modify | 1 new service method (`createUpdateLinkToken`) |
| `frontend/.../APIService.ts` | Modify | 1 forwarding method to `PlaidService` |
| `frontend/.../usePlaid.ts` | Modify | `reauthConnection` mutation |
| `frontend/.../AccountConnections.tsx` | Modify | Extend status union type + amber badge + re-auth button |
| `frontend/.../AccountConnectionsContainer.tsx` | Modify | Map `needs_reauth` status + pass `item_id` prop + wire `onReauth` |
| `scripts/backfill_provider_items.py` | New | One-time backfill of `provider_items` from Secrets Manager payloads |
| `scripts/plaid_reauth.py` | New | CLI tool for listing connections + triggering re-auth from terminal |

## Deployment Prerequisites

**Required (in order):**
1. Run database migration: `20260224_add_provider_item_reauth_flag.sql` (safe on `provider_items` — tiny table)
2. Run backfill script: `scripts/backfill_provider_items.py` — populates `provider_items` for legacy connections so re-auth endpoint doesn't 404
3. Deploy backend code
4. Deploy frontend code

**Required (environment):**
5. Ensure `PLAID_WEBHOOK_FORWARD_SHARED_SECRET` is set in production (existing requirement — `LOGIN_REPAIRED` flag clearing depends on webhook authenticity)

## Operational Notes

- **Missed `LOGIN_REPAIRED` webhook:** If the webhook is lost or delayed, `needs_reauth` stays `True` even after successful re-auth. The user sees "Re-authenticate" but the connection actually works. Clicking re-auth again is harmless (Plaid will just succeed immediately). Future enhancement: add a "Check status" button that calls Plaid's `/item/get` to verify item health and clear the flag manually.
- **`get_plaid_token_by_item_id()` scans all user secrets:** This is an O(N) scan over Secrets Manager. For typical users (1-3 connections), this is negligible. If a user has many connections, consider caching the scan result for the duration of the request. Not needed for v1.
- **`client_user_id` derived from email hash:** This matches the existing pattern in `create_link_token` (line 613). If a user changes their email, Plaid sees a different `client_user_id`, but this is already the case for new connections — not a new risk introduced by this feature.

## Review Findings Addressed

| # | Round | Finding | Resolution |
|---|-------|---------|------------|
| 1 | R1 | `/reauth_complete` can clear flag on failed/canceled sessions | **Removed entirely.** Flag cleared server-side via `LOGIN_REPAIRED` webhook only |
| 2 | R1 | `/reauth_complete` missing ownership check | **N/A** — endpoint removed. `create_update_link_token` has ownership check |
| 3 | R1+R2 | Token lookup by institution_name ambiguous for multi-item | **New `get_plaid_token_by_item_id()`** scans secrets and matches by `item_id` payload field. No institution-slug ambiguity |
| 4 | R1 | Missing `plaid_loader` re-export | Step 1b: re-export through `plaid_loader.py` + route import wiring |
| 5 | R1 | `id` semantics in `/connections` must stay stable | `id` unchanged. `item_id` added as separate field |
| 6 | R1+R2 | Error responses leak internals via `str(e)` | All new `except` blocks return sanitized messages. Existing endpoints are out of scope but noted for future cleanup |
| 7 | R2 | Code snippets use non-existent patterns (`get_db_connection()`, `_get_authenticated_user()`) | **Fixed.** All snippets now use `with get_db_session() as conn: DatabaseClient(conn)` and `auth_service.get_user_by_session(session_id)` matching existing code |
| 8 | R2 | Webhook auth dependency for `LOGIN_REPAIRED` | **Documented as deployment prerequisite.** `PLAID_WEBHOOK_FORWARD_SHARED_SECRET` must be set in production |
| 9 | R2 | Legacy connections without `provider_items` rows | **Addressed in Step 8.** Backfill script required + runtime self-heal hook added to `/holdings/refresh` |
| 10 | R3 | `/connections` join relies on institution-slug normalization | **Fixed.** Join now reads `item_id` from secret payload and looks up `provider_items` by `item_id` directly |
| 11 | R3 | `get_plaid_token_by_item_id()` swallows all `ClientError`s | **Fixed.** Only swallows `ResourceNotFoundException`, propagates auth/infra errors |
| 12 | R3 | Step 8 self-heal claim incorrect (`_store_plaid_item_mapping` only called during exchange) | **Fixed.** Corrected claim. Added explicit runtime hook in `/holdings/refresh` + backfill script marked as required |

## Testing

- Unit test: `create_update_link_token()` builds correct request (no `products`, has `access_token`)
- Unit test: `get_plaid_token_by_item_id()` correctly matches by `item_id` payload field
- Integration test: `ITEM_LOGIN_REQUIRED` webhook sets `needs_reauth` flag
- Integration test: `LOGIN_REPAIRED` webhook clears `needs_reauth` flag
- Integration test: `/create_update_link_token` rejects requests for items not owned by session user (returns 404)
- Integration test: `/create_update_link_token` returns sanitized errors, never internal paths
- Integration test: `/connections` returns `needs_reauth` status and `item_id` when flag is set
- Integration test: `/connections` gracefully handles missing `provider_items` rows (returns `active` + empty `item_id`)
- Manual test: Full re-auth flow with Plaid sandbox (frontend)
- Manual test: CLI re-auth flow — `python scripts/plaid_reauth.py --reauth` lists stale connections and opens hosted link

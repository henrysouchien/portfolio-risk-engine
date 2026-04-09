# B1: Stripe Integration + Checkout Flow

> **Created**: 2026-03-19
> **Status**: Not started
> **Parent**: `docs/planning/launch/OPEN_SOURCE_LAUNCH_GAPS.md` (item B1)
> **Depends on**: A1 (Tier Enforcement — `90f52fe1`, DONE), A2 (Frontend Tier Awareness — `948f38f4`, DONE)
> **Goal**: Self-serve upgrade from Free to Pro via Stripe Checkout. Webhook-driven tier management. Billing portal for subscription lifecycle.

---

## Current State

**Already working (from A1 + A2)**:
- `users.tier` column: `VARCHAR(50) DEFAULT 'public'` — values: `public`, `registered`, `paid`
- `create_tier_dependency()` in `app_platform/auth/dependencies.py` — 403 `upgrade_required` response
- ~30 routes gated with `_require_paid_user = create_tier_dependency(auth_service, minimum_tier="paid")`
- Gateway proxy context-aware tier check (`purpose=normalizer` exempt, `purpose=chat` gated)
- `useTier()` hook in `frontend/packages/chassis/src/hooks/useTier.ts` — `{ tier, displayName, isPaid, isFree }`
- `UpgradePrompt` component in `frontend/packages/ui/src/components/common/UpgradePrompt.tsx`
- `UpgradeRequiredError` type + `classifyError.ts` 403 split (distinguishes auth vs upgrade)
- Admin `POST /admin/set-tier` endpoint with `_update_user_tier()` helper in `routes/admin.py`
- Frontend `User` type includes `tier?: 'public' | 'registered' | 'paid'`
- `mapAuthUser()` validates tier on every auth check, session store JOIN includes `u.tier`

**What's missing**:
- No Stripe SDK, no checkout flow, no webhook handler
- No `stripe_customer_id` or `stripe_subscription_id` on users table
- No self-serve upgrade path — tier changes require admin API call
- No billing portal link for subscription management
- No pricing page in frontend
- No subscription lifecycle handling (cancel, reactivate, payment failure)
- `UpgradePrompt` has no actionable button (no checkout URL to link to)

---

## Design Decisions

### D1: Stripe Checkout Sessions, not embedded Elements

Use Stripe Checkout (hosted page) rather than Stripe Elements (embedded form). Reasons:
- Zero PCI scope — Stripe handles the entire payment form
- Mobile-optimized out of the box
- Supports Apple Pay, Google Pay, Link automatically
- Less frontend code — redirect to Stripe, handle return
- Matches the product maturity stage — polish the embedded experience later if needed

### D2: Webhook-driven tier changes, not client-side

The client never directly sets `users.tier`. All tier transitions are driven by verified Stripe webhooks:
- `checkout.session.completed` → upgrade to `paid`
- `customer.subscription.deleted` → downgrade to `registered`
- `customer.subscription.updated` → handle plan changes
- `invoice.payment_failed` → grace period, then downgrade

This ensures the DB tier always reflects actual payment status, regardless of client behavior.

### D3: Store Stripe IDs on the users table, not a separate subscriptions table

For a single-product SaaS (Free/Pro), a separate `subscriptions` table adds join complexity with no benefit. Add `stripe_customer_id` and `stripe_subscription_id` columns to the existing `users` table. If we later add multiple products or per-seat billing (Business tier), we can extract a subscriptions table then.

### D4: Stripe Customer created at checkout time, not at signup

Do not create a Stripe Customer for every user at registration. Most free users will never upgrade. Create the Customer object when the user initiates checkout. Link it back to the user via the `checkout.session.completed` webhook (using `client_reference_id = user_id`).

### D5: Billing service lives in `app_platform/`, not as a route-level concern

The billing logic (create checkout session, handle webhooks, query subscription status) is reusable infrastructure. Place it in `app_platform/billing/` alongside `app_platform/auth/`. Route handlers in `routes/billing.py` are thin wrappers.

### D6: Environment-based Stripe key selection

Use `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` env vars. In development, these point to Stripe test mode keys. In production, live keys. No code-level mode switching — the key determines the mode.

### D7: No trial period in v1

Ship without a free trial for Pro. The free tier IS the trial — users experience the dashboard and manual analysis tools before deciding to upgrade. A time-limited trial adds billing complexity (trial-to-paid conversion, trial expiry handling) that can be added later.

### D8: Reuse `_update_user_tier()` from admin.py

The admin route already has a tested `_update_user_tier(email, tier)` function that does `UPDATE users SET tier = %s WHERE email = %s RETURNING email, tier`. The webhook handler should call this same function (or a refactored shared version) to avoid duplicating the tier update SQL.

---

## Database Changes

### Migration: `20260320_add_stripe_columns.sql`

```sql
-- Add Stripe billing columns to users table
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS stripe_customer_id VARCHAR(255) UNIQUE,
    ADD COLUMN IF NOT EXISTS stripe_subscription_id VARCHAR(255) UNIQUE,
    ADD COLUMN IF NOT EXISTS subscription_status VARCHAR(50),
    ADD COLUMN IF NOT EXISTS subscription_current_period_end TIMESTAMP;

-- Index for webhook lookups by stripe_customer_id
CREATE INDEX IF NOT EXISTS idx_users_stripe_customer_id
    ON users (stripe_customer_id)
    WHERE stripe_customer_id IS NOT NULL;

-- Index for subscription status queries (e.g., find users with expiring subs)
CREATE INDEX IF NOT EXISTS idx_users_subscription_status
    ON users (subscription_status)
    WHERE subscription_status IS NOT NULL;
```

**Column semantics**:
- `stripe_customer_id`: Stripe `cus_xxx` ID. Created on first checkout. Nullable (free users never have one).
- `stripe_subscription_id`: Stripe `sub_xxx` ID for the active subscription. Nullable. Cleared on cancellation after period end.
- `subscription_status`: Mirrors Stripe's `subscription.status` field: `active`, `past_due`, `canceled`, `unpaid`, `incomplete`. Nullable (free users).
- `subscription_current_period_end`: When the current billing period ends. Used for grace period logic on cancellation. Nullable.

**Why no separate table**: Single product (Pro), one subscription per user. The `users` table already drives session/tier lookups — adding these columns avoids a JOIN on every authenticated request. See D3.

---

## Backend Architecture

### Package: `app_platform/billing/`

```
app_platform/billing/
    __init__.py          # Barrel export
    service.py           # BillingService (Stripe operations)
    webhook_handler.py   # Webhook event processing + signature verification
    models.py            # Pydantic models for billing responses
```

### `app_platform/billing/service.py` — BillingService

```python
"""Stripe billing operations for checkout, portal, and subscription queries."""

import os
import logging
from typing import Optional

import stripe

logger = logging.getLogger(__name__)

# Stripe Product/Price IDs (configured via env vars)
STRIPE_PRO_PRICE_ID = os.getenv("STRIPE_PRO_PRICE_ID", "")

class BillingService:
    """Thin wrapper around Stripe SDK operations."""

    def __init__(self, secret_key: str | None = None):
        self._secret_key = secret_key or os.getenv("STRIPE_SECRET_KEY", "")
        if self._secret_key:
            stripe.api_key = self._secret_key

    def create_checkout_session(
        self,
        user_id: int,
        user_email: str,
        success_url: str,
        cancel_url: str,
        stripe_customer_id: str | None = None,
    ) -> stripe.checkout.Session:
        """Create a Stripe Checkout Session for Pro upgrade.

        If the user already has a stripe_customer_id (e.g., previously subscribed
        and cancelled), reuse it so Stripe shows their saved payment methods.
        """
        params: dict = {
            "mode": "subscription",
            "line_items": [{"price": STRIPE_PRO_PRICE_ID, "quantity": 1}],
            "success_url": success_url,
            "cancel_url": cancel_url,
            "client_reference_id": str(user_id),
            "metadata": {"user_id": str(user_id), "tier": "paid"},
        }

        if stripe_customer_id:
            params["customer"] = stripe_customer_id
        else:
            params["customer_email"] = user_email

        return stripe.checkout.Session.create(**params)

    def create_billing_portal_session(
        self,
        stripe_customer_id: str,
        return_url: str,
    ) -> stripe.billing_portal.Session:
        """Create a Stripe Billing Portal session for subscription management."""
        return stripe.billing_portal.Session.create(
            customer=stripe_customer_id,
            return_url=return_url,
        )

    def get_subscription(
        self,
        subscription_id: str,
    ) -> stripe.Subscription | None:
        """Retrieve a subscription by ID. Returns None if not found."""
        try:
            return stripe.Subscription.retrieve(subscription_id)
        except stripe.error.InvalidRequestError:
            return None
```

### `app_platform/billing/webhook_handler.py` — Webhook Processing

```python
"""Stripe webhook event handler with signature verification and idempotency."""

import logging
import os
from typing import Any, Callable

import stripe

logger = logging.getLogger(__name__)

STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

# Tier mapping from subscription status
_STATUS_TO_TIER = {
    "active": "paid",
    "trialing": "paid",     # future-proof for D7 reversal
    "past_due": "paid",     # grace period — still has access
    "canceled": "registered",
    "unpaid": "registered",
    "incomplete": "registered",
    "incomplete_expired": "registered",
}


def verify_webhook_signature(payload: bytes, sig_header: str) -> stripe.Event:
    """Verify Stripe webhook signature and construct event.

    Raises stripe.error.SignatureVerificationError on failure.
    """
    return stripe.Webhook.construct_event(
        payload, sig_header, STRIPE_WEBHOOK_SECRET
    )


def handle_webhook_event(
    event: stripe.Event,
    update_user_billing: Callable[..., Any],
) -> dict[str, str]:
    """Route a verified webhook event to the appropriate handler.

    Args:
        event: Verified Stripe event object.
        update_user_billing: Callback to persist billing state to the DB.
            Signature: (user_id: int, tier: str, stripe_customer_id: str,
                        stripe_subscription_id: str | None,
                        subscription_status: str | None,
                        current_period_end: datetime | None) -> None

    Returns:
        Dict with "status" key ("handled" or "ignored").
    """
    event_type = event["type"]
    data_object = event["data"]["object"]

    if event_type == "checkout.session.completed":
        return _handle_checkout_completed(data_object, update_user_billing)

    if event_type == "customer.subscription.updated":
        return _handle_subscription_updated(data_object, update_user_billing)

    if event_type == "customer.subscription.deleted":
        return _handle_subscription_deleted(data_object, update_user_billing)

    if event_type == "invoice.payment_failed":
        return _handle_payment_failed(data_object, update_user_billing)

    logger.debug("Ignoring unhandled webhook event: %s", event_type)
    return {"status": "ignored"}


def _handle_checkout_completed(session: dict, update_fn: Callable) -> dict:
    """checkout.session.completed — user completed payment."""
    user_id = session.get("client_reference_id")
    customer_id = session.get("customer")
    subscription_id = session.get("subscription")

    if not user_id or not customer_id:
        logger.warning("checkout.session.completed missing user_id or customer_id")
        return {"status": "ignored"}

    # Retrieve the subscription to get current_period_end
    sub = stripe.Subscription.retrieve(subscription_id) if subscription_id else None
    period_end = None
    if sub:
        from datetime import datetime, UTC
        period_end = datetime.fromtimestamp(sub["current_period_end"], tz=UTC)

    update_fn(
        user_id=int(user_id),
        tier="paid",
        stripe_customer_id=customer_id,
        stripe_subscription_id=subscription_id,
        subscription_status="active",
        current_period_end=period_end,
    )

    logger.info("User %s upgraded to paid via checkout", user_id)
    return {"status": "handled"}


def _handle_subscription_updated(subscription: dict, update_fn: Callable) -> dict:
    """customer.subscription.updated — status change, renewal, plan change."""
    customer_id = subscription.get("customer")
    subscription_id = subscription.get("id")
    status = subscription.get("status", "")

    tier = _STATUS_TO_TIER.get(status, "registered")

    from datetime import datetime, UTC
    period_end = None
    if subscription.get("current_period_end"):
        period_end = datetime.fromtimestamp(subscription["current_period_end"], tz=UTC)

    # Look up user by stripe_customer_id (not user_id — subscription events don't carry it)
    update_fn(
        stripe_customer_id=customer_id,
        tier=tier,
        stripe_subscription_id=subscription_id,
        subscription_status=status,
        current_period_end=period_end,
    )

    logger.info("Subscription %s updated: status=%s, tier=%s", subscription_id, status, tier)
    return {"status": "handled"}


def _handle_subscription_deleted(subscription: dict, update_fn: Callable) -> dict:
    """customer.subscription.deleted — subscription cancelled and period ended."""
    customer_id = subscription.get("customer")

    update_fn(
        stripe_customer_id=customer_id,
        tier="registered",
        stripe_subscription_id=None,
        subscription_status="canceled",
        current_period_end=None,
    )

    logger.info("Subscription deleted for customer %s — downgraded to registered", customer_id)
    return {"status": "handled"}


def _handle_payment_failed(invoice: dict, update_fn: Callable) -> dict:
    """invoice.payment_failed — payment retry failed.

    Stripe retries automatically (Smart Retries). We log but don't immediately
    downgrade — the subscription status will move to `past_due` or `unpaid`,
    which triggers _handle_subscription_updated with the appropriate tier mapping.
    """
    customer_id = invoice.get("customer")
    attempt_count = invoice.get("attempt_count", 0)

    logger.warning(
        "Payment failed for customer %s (attempt %d)",
        customer_id, attempt_count,
    )

    # No tier change here — Stripe's subscription.updated webhook handles it
    return {"status": "handled"}
```

### `app_platform/billing/models.py`

```python
"""Pydantic models for billing API responses."""

from pydantic import BaseModel
from typing import Optional

class CheckoutSessionResponse(BaseModel):
    checkout_url: str
    session_id: str

class BillingPortalResponse(BaseModel):
    portal_url: str

class SubscriptionStatusResponse(BaseModel):
    tier: str
    tier_display: str
    subscription_status: Optional[str] = None
    current_period_end: Optional[str] = None
    stripe_customer_id: Optional[str] = None
    can_manage_billing: bool = False
```

---

### Route: `routes/billing.py`

Thin wrappers over `BillingService`. Three endpoints:

```python
"""Billing routes — Stripe checkout, portal, and webhook."""

import os
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app_platform.auth.dependencies import create_auth_dependency
from app_platform.billing.service import BillingService
from app_platform.billing.webhook_handler import verify_webhook_signature, handle_webhook_event
from app_platform.billing.models import (
    CheckoutSessionResponse,
    BillingPortalResponse,
    SubscriptionStatusResponse,
)
from services.auth_service import auth_service
from database import get_db_session
from utils.logging import log_error

logger = logging.getLogger(__name__)

billing_router = APIRouter(prefix="/api/billing", tags=["billing"])
billing_service = BillingService()

_get_current_user = create_auth_dependency(auth_service)

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

TIER_DISPLAY = {"public": "Free", "registered": "Free", "paid": "Pro"}


# --- Checkout ---

@billing_router.post("/create-checkout-session", response_model=CheckoutSessionResponse)
async def create_checkout_session(
    request: Request,
    user: dict = Depends(_get_current_user),
):
    """Create Stripe Checkout session for Pro upgrade."""
    user_id = user.get("user_id")
    email = user.get("email", "")

    # Fetch stripe_customer_id from DB if it exists (returning subscriber)
    stripe_customer_id = _get_stripe_customer_id(user_id)

    try:
        session = billing_service.create_checkout_session(
            user_id=user_id,
            user_email=email,
            success_url=f"{FRONTEND_URL}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{FRONTEND_URL}/settings",
            stripe_customer_id=stripe_customer_id,
        )
    except Exception as exc:
        log_error("billing", "create_checkout_session", exc)
        raise HTTPException(status_code=500, detail="Failed to create checkout session")

    return CheckoutSessionResponse(
        checkout_url=session.url,
        session_id=session.id,
    )


# --- Billing Portal ---

@billing_router.post("/create-portal-session", response_model=BillingPortalResponse)
async def create_billing_portal_session(
    request: Request,
    user: dict = Depends(_get_current_user),
):
    """Create Stripe Billing Portal session for subscription management."""
    user_id = user.get("user_id")
    stripe_customer_id = _get_stripe_customer_id(user_id)

    if not stripe_customer_id:
        raise HTTPException(status_code=400, detail="No active billing account")

    try:
        portal_session = billing_service.create_billing_portal_session(
            stripe_customer_id=stripe_customer_id,
            return_url=f"{FRONTEND_URL}/settings",
        )
    except Exception as exc:
        log_error("billing", "create_portal_session", exc)
        raise HTTPException(status_code=500, detail="Failed to create portal session")

    return BillingPortalResponse(portal_url=portal_session.url)


# --- Subscription Status ---

@billing_router.get("/subscription-status", response_model=SubscriptionStatusResponse)
async def get_subscription_status(
    request: Request,
    user: dict = Depends(_get_current_user),
):
    """Get current subscription status for the authenticated user."""
    user_id = user.get("user_id")
    tier = user.get("tier", "registered")

    billing_info = _get_user_billing_info(user_id)

    return SubscriptionStatusResponse(
        tier=tier,
        tier_display=TIER_DISPLAY.get(tier, "Free"),
        subscription_status=billing_info.get("subscription_status"),
        current_period_end=(
            billing_info["subscription_current_period_end"].isoformat()
            if billing_info.get("subscription_current_period_end")
            else None
        ),
        stripe_customer_id=billing_info.get("stripe_customer_id"),
        can_manage_billing=bool(billing_info.get("stripe_customer_id")),
    )


# --- Webhook ---

@billing_router.post("/webhook")
async def stripe_webhook(request: Request):
    """Stripe webhook endpoint. No auth — verified by signature."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = verify_webhook_signature(payload, sig_header)
    except Exception as exc:
        logger.warning("Stripe webhook signature verification failed: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        result = handle_webhook_event(event, update_user_billing=_update_user_billing)
    except Exception as exc:
        log_error("billing", "webhook_handler", exc)
        raise HTTPException(status_code=500, detail="Webhook processing failed")

    return JSONResponse(content=result, status_code=200)


# --- DB Helpers ---

def _get_stripe_customer_id(user_id: int) -> str | None:
    """Look up stripe_customer_id for a user."""
    try:
        with get_db_session() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT stripe_customer_id FROM users WHERE id = %s",
                (user_id,),
            )
            row = cursor.fetchone()
            if row:
                return row["stripe_customer_id"] if isinstance(row, dict) else row[0]
    except Exception:
        pass
    return None


def _get_user_billing_info(user_id: int) -> dict:
    """Fetch billing-related columns for a user."""
    try:
        with get_db_session() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT stripe_customer_id, stripe_subscription_id,
                       subscription_status, subscription_current_period_end
                FROM users WHERE id = %s
                """,
                (user_id,),
            )
            row = cursor.fetchone()
            if row and isinstance(row, dict):
                return row
            if row:
                return {
                    "stripe_customer_id": row[0],
                    "stripe_subscription_id": row[1],
                    "subscription_status": row[2],
                    "subscription_current_period_end": row[3],
                }
    except Exception:
        pass
    return {}


def _update_user_billing(
    user_id: int | None = None,
    stripe_customer_id: str | None = None,
    tier: str = "registered",
    stripe_subscription_id: str | None = None,
    subscription_status: str | None = None,
    current_period_end=None,
) -> None:
    """Persist billing state to the users table.

    Can look up user by user_id OR stripe_customer_id (webhook events
    from subscription.updated/deleted don't carry user_id).
    """
    with get_db_session() as conn:
        cursor = conn.cursor()
        try:
            if user_id:
                cursor.execute(
                    """
                    UPDATE users
                    SET tier = %s,
                        stripe_customer_id = COALESCE(%s, stripe_customer_id),
                        stripe_subscription_id = %s,
                        subscription_status = %s,
                        subscription_current_period_end = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (tier, stripe_customer_id, stripe_subscription_id,
                     subscription_status, current_period_end, user_id),
                )
            elif stripe_customer_id:
                cursor.execute(
                    """
                    UPDATE users
                    SET tier = %s,
                        stripe_subscription_id = %s,
                        subscription_status = %s,
                        subscription_current_period_end = %s,
                        updated_at = NOW()
                    WHERE stripe_customer_id = %s
                    """,
                    (tier, stripe_subscription_id, subscription_status,
                     current_period_end, stripe_customer_id),
                )
            else:
                logger.error("_update_user_billing called with no user_id or stripe_customer_id")
                return

            conn.commit()
        except Exception:
            rollback = getattr(conn, "rollback", None)
            if callable(rollback):
                rollback()
            raise
        finally:
            close = getattr(cursor, "close", None)
            if callable(close):
                close()
```

### Router Registration in `app.py`

```python
from routes.billing import billing_router
app.include_router(billing_router)
```

The webhook endpoint (`/api/billing/webhook`) must NOT have session auth — it is called by Stripe servers. Signature verification replaces authentication.

---

## Frontend Architecture

### New Files

```
frontend/packages/ui/src/
    pages/
        PricingPage.tsx            # Standalone pricing page
        BillingSuccess.tsx         # Post-checkout success page
    components/
        settings/
            BillingSection.tsx     # Settings panel billing section
```

### Modified Files

```
frontend/packages/chassis/src/
    hooks/useTier.ts                # Add canManageBilling, checkoutUrl action
    services/APIService.ts          # Add billing API methods

frontend/packages/ui/src/
    components/common/UpgradePrompt.tsx    # Add checkout button
    components/settings/SettingsPanel.tsx  # Add billing section
    router/AppOrchestratorModern.tsx       # Add routes for pricing/billing pages
```

### `UpgradePrompt` Enhancement

The existing `UpgradePrompt` component currently shows feature copy but has no actionable button. Add a "Upgrade to Pro" button that calls the checkout session API and redirects to Stripe.

```typescript
// In UpgradePrompt.tsx — add to the card content:
<Button
  onClick={handleUpgrade}
  className="bg-gradient-to-r from-amber-500 to-amber-600 text-white shadow-md hover:from-amber-600 hover:to-amber-700"
>
  Upgrade to Pro
</Button>

// handleUpgrade:
const handleUpgrade = async () => {
  setLoading(true);
  try {
    const { checkout_url } = await apiService.createCheckoutSession();
    window.location.href = checkout_url;
  } catch (err) {
    // Show error toast
  } finally {
    setLoading(false);
  }
};
```

### `PricingPage.tsx`

A simple two-column pricing comparison (Free vs Pro) with feature lists matching the strategy doc tiers. The Pro column has a checkout button. Accessible from `/pricing` route and linked from upgrade prompts.

**Free column features**:
- Full dashboard (positions, performance, risk score)
- CSV import (any brokerage format)
- Manual analysis (what-if, stress test, optimization)
- Risk scoring + factor analysis

**Pro column features** (everything in Free, plus):
- AI portfolio analyst (chat, skills, memory)
- Live brokerage connections (Plaid, SnapTrade)
- Real-time market data
- AI insights + recommendations
- Scheduled workflows

### `BillingSection.tsx` in Settings

Shows current plan, subscription status, and a "Manage Billing" button (opens Stripe Portal) or "Upgrade to Pro" button (for free users). Added as a section in the existing settings panel.

```typescript
// Simplified structure:
function BillingSection() {
  const { tier, displayName, isPaid } = useTier();
  const { data: billing } = useSubscriptionStatus();

  return (
    <Card>
      <h3>Billing</h3>
      <p>Current plan: {displayName}</p>
      {billing?.subscription_status === 'active' && (
        <p>Renews: {formatDate(billing.current_period_end)}</p>
      )}
      {isPaid && billing?.can_manage_billing ? (
        <Button onClick={openBillingPortal}>Manage Billing</Button>
      ) : (
        <Button onClick={startCheckout}>Upgrade to Pro</Button>
      )}
    </Card>
  );
}
```

### `BillingSuccess.tsx`

Post-checkout landing page at `/billing/success`. Shows a confirmation message and polls the auth status endpoint until the tier updates (webhook may take 1-2 seconds). Then redirects to the dashboard.

```typescript
function BillingSuccess() {
  // Poll /auth/status every 2s until tier === 'paid'
  // Show "Activating your Pro subscription..." with a spinner
  // On tier change, show success message and redirect to dashboard
}
```

### API Service Methods

Add to the existing `APIService` (or a new `BillingService` class in the frontend):

```typescript
async createCheckoutSession(): Promise<{ checkout_url: string; session_id: string }> {
  return this.post('/api/billing/create-checkout-session');
}

async createBillingPortalSession(): Promise<{ portal_url: string }> {
  return this.post('/api/billing/create-portal-session');
}

async getSubscriptionStatus(): Promise<SubscriptionStatusResponse> {
  return this.get('/api/billing/subscription-status');
}
```

---

## Integration with Existing Tier Enforcement

The checkout flow completes the loop that A1 and A2 started:

```
                    A1 (Backend)                  A2 (Frontend)
                    ┌─────────────────────┐      ┌─────────────────────┐
                    │ create_tier_dependency│      │ useTier() hook      │
                    │ → 403 upgrade_required│      │ → UpgradePrompt     │
                    └───────────┬─────────┘      └────────┬────────────┘
                                │                          │
                    ┌───────────┴──────────────────────────┴─────────────┐
                    │                                                     │
                    │         B1 (Stripe Integration) — THIS PLAN        │
                    │                                                     │
                    │  User hits gated feature                           │
                    │    → 403 upgrade_required                          │
                    │    → UpgradePrompt with "Upgrade to Pro" button    │
                    │    → Click → POST /api/billing/create-checkout     │
                    │    → Redirect to Stripe Checkout                   │
                    │    → Payment → Stripe webhook                      │
                    │    → checkout.session.completed                    │
                    │    → _update_user_billing(tier="paid")             │
                    │    → Next request: session includes tier="paid"    │
                    │    → create_tier_dependency passes                 │
                    │    → useTier().isPaid === true                     │
                    │    → Feature unlocked                              │
                    │                                                     │
                    └─────────────────────────────────────────────────────┘
```

**Session refresh after upgrade**: The user's tier changes in the DB when the webhook fires. The next time `PostgresSessionStore.get_session()` runs (on any authenticated request), it JOINs `users` and picks up the new tier. No session invalidation needed — the tier is read live from the users table, not cached in the session row.

---

## Webhook Events to Handle

| Stripe Event | Action | Tier Transition |
|---|---|---|
| `checkout.session.completed` | Store `stripe_customer_id`, `stripe_subscription_id`, set tier | `registered` → `paid` |
| `customer.subscription.updated` | Update `subscription_status`, `current_period_end` | Depends on status (see `_STATUS_TO_TIER`) |
| `customer.subscription.deleted` | Clear subscription fields, downgrade | `paid` → `registered` |
| `invoice.payment_failed` | Log warning. Stripe handles retries. | No immediate change (subscription.updated handles it) |

**Events to configure in Stripe Dashboard** (webhook endpoint settings):
- `checkout.session.completed`
- `customer.subscription.created`
- `customer.subscription.updated`
- `customer.subscription.deleted`
- `invoice.payment_failed`

---

## Security

### Webhook Signature Verification

Every incoming webhook request is verified using `stripe.Webhook.construct_event()` with the `STRIPE_WEBHOOK_SECRET`. This proves the request came from Stripe, not a forged POST. Reject with 400 if verification fails.

### No Auth on Webhook Endpoint

The `/api/billing/webhook` endpoint must NOT require session auth or admin token. It is called by Stripe servers. The signature IS the authentication.

### Idempotency

Stripe may deliver the same event multiple times. The webhook handler must be idempotent:
- `_update_user_billing()` uses `UPDATE ... SET tier = %s` — reprocessing the same event produces the same result
- `COALESCE(%s, stripe_customer_id)` prevents overwriting an existing customer ID with NULL
- No side effects (emails, notifications) that would be harmful if repeated — those are deferred to a future phase

### HTTPS Only

Stripe requires HTTPS for production webhook endpoints. The production deployment already terminates TLS at the load balancer. In development, use Stripe CLI (`stripe listen --forward-to localhost:8000/api/billing/webhook`) to forward test webhooks over HTTP.

### Checkout Session Security

- `client_reference_id` links the session to our user ID — this is set server-side, not by the client
- The checkout session URL is single-use and expires after 24 hours
- After checkout, the client is redirected to our `success_url` — we do NOT trust the redirect alone for tier changes. The webhook is the source of truth.

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `STRIPE_SECRET_KEY` | Yes | `sk_test_...` (dev) or `sk_live_...` (prod) |
| `STRIPE_WEBHOOK_SECRET` | Yes | `whsec_...` from Stripe Dashboard or CLI |
| `STRIPE_PRO_PRICE_ID` | Yes | `price_...` ID for the Pro subscription price |
| `FRONTEND_URL` | Yes | `http://localhost:3000` (dev) or production URL |

---

## Execution Plan

### Step 1: Database Migration + Billing Service

**Scope**: Migration SQL + `app_platform/billing/` package (service, webhook handler, models).

**Files**:
- `database/migrations/20260320_add_stripe_columns.sql` — new
- `app_platform/billing/__init__.py` — new
- `app_platform/billing/service.py` — new
- `app_platform/billing/webhook_handler.py` — new
- `app_platform/billing/models.py` — new
- `requirements.txt` or `pyproject.toml` — add `stripe` dependency

**Tests**:
- Unit: `BillingService.create_checkout_session()` calls Stripe SDK correctly (mock `stripe.checkout.Session.create`)
- Unit: `verify_webhook_signature()` rejects invalid signatures
- Unit: `handle_webhook_event()` dispatches to correct handler per event type
- Unit: `_handle_checkout_completed()` calls `update_fn` with correct args
- Unit: `_handle_subscription_deleted()` downgrades tier
- Unit: `_STATUS_TO_TIER` mapping covers all Stripe subscription statuses
- Unit: Idempotency — calling handler twice with same event produces same DB state

### Step 2: Backend Routes

**Scope**: `routes/billing.py` with 4 endpoints, register in `app.py`.

**Files**:
- `routes/billing.py` — new
- `app.py` — add `app.include_router(billing_router)`

**Tests**:
- Integration: `POST /api/billing/create-checkout-session` returns `checkout_url` for authenticated user
- Integration: `POST /api/billing/create-checkout-session` returns 401 for unauthenticated request
- Integration: `POST /api/billing/create-portal-session` returns 400 when user has no `stripe_customer_id`
- Integration: `GET /api/billing/subscription-status` returns current tier and billing info
- Integration: `POST /api/billing/webhook` with valid signature + `checkout.session.completed` → user tier updated
- Integration: `POST /api/billing/webhook` with invalid signature → 400
- Integration: Full flow — registered user → checkout → webhook → tier is now `paid`

### Step 3: Frontend — UpgradePrompt + Billing API

**Scope**: Add checkout button to `UpgradePrompt`, add billing methods to API service.

**Files**:
- `frontend/packages/ui/src/components/common/UpgradePrompt.tsx` — modify (add button)
- `frontend/packages/chassis/src/services/APIService.ts` — modify (add billing methods)

**Tests**:
- Component: `UpgradePrompt` renders checkout button for free users
- Component: Clicking "Upgrade to Pro" calls `createCheckoutSession` and redirects

### Step 4: Frontend — Pricing Page + Billing Settings + Success Page

**Scope**: New pages and settings section.

**Files**:
- `frontend/packages/ui/src/pages/PricingPage.tsx` — new
- `frontend/packages/ui/src/pages/BillingSuccess.tsx` — new
- `frontend/packages/ui/src/components/settings/BillingSection.tsx` — new
- `frontend/packages/ui/src/components/settings/SettingsPanel.tsx` — modify (add billing section)
- `frontend/packages/ui/src/router/AppOrchestratorModern.tsx` — modify (add routes)

**Tests**:
- Component: `PricingPage` renders two tiers with correct feature lists
- Component: `BillingSection` shows "Manage Billing" for paid users, "Upgrade" for free
- Component: `BillingSuccess` polls auth status and redirects on tier change

### Step 5: End-to-End Verification

**Scope**: Stripe test mode end-to-end flow.

**Steps**:
1. Create Stripe test product + price in Stripe Dashboard
2. Set `STRIPE_PRO_PRICE_ID` to the test price ID
3. Run `stripe listen --forward-to localhost:8000/api/billing/webhook` for local webhook delivery
4. Log in as a `registered` user
5. Click "Upgrade to Pro" → redirected to Stripe Checkout (test mode)
6. Use test card `4242 4242 4242 4242` → complete payment
7. Verify webhook received → user tier updated to `paid` in DB
8. Verify frontend picks up new tier on next request
9. Verify gated features (AI chat, Plaid connection) now accessible
10. Open Billing Portal → verify subscription visible, can cancel
11. Cancel subscription → verify `subscription.deleted` webhook → tier reverts to `registered`
12. Verify gated features show upgrade prompt again

---

## Migration Path: Static Tiers to Stripe-Managed

**Current state**: Tiers are set via `admin/set-tier` API or directly in the DB. No payment linkage.

**After this plan**: New users upgrade via Stripe Checkout. Tier changes are webhook-driven.

**Transition for existing paid users**:
1. Existing users with `tier = 'paid'` who were manually upgraded (pre-Stripe) retain their tier
2. They have no `stripe_customer_id` or `stripe_subscription_id` (both NULL)
3. The billing settings section shows them as "Pro (Legacy)" with a note: "Your plan was activated manually. Contact support for billing questions."
4. If they visit the billing portal, they see "No active billing account" — harmless
5. No forced migration — these are early adopters / internal users. Handle case-by-case if needed.

**`_update_user_billing()` handles both paths**: It can update by `user_id` (checkout flow) or by `stripe_customer_id` (subscription events). Legacy users without Stripe IDs are unaffected by subscription webhooks.

---

## Out of Scope (Deferred)

| Item | Reason |
|---|---|
| **Business tier checkout** | Requires "Contact Us" flow, custom pricing, multi-seat. Different funnel. |
| **Free trial for Pro** | See D7. Free tier IS the trial. Add later if conversion data warrants it. |
| **Coupon / promo codes** | Stripe Checkout supports these natively — just needs a checkbox in the UI. Low priority. |
| **Usage-based billing** | Token budgets, metered API calls. Future optimization once we have cost-per-user data. |
| **Email notifications** | "Welcome to Pro" email, "Payment failed" email. Requires email service integration. |
| **Annual billing option** | Second price ID + toggle on pricing page. Simple to add once monthly is stable. |
| **Revenue dashboard** | Admin analytics for MRR, churn, conversion. Use Stripe Dashboard directly for now. |
| **Refund handling** | Handle via Stripe Dashboard manually. Automate only if volume warrants it. |
| **Multiple subscriptions per user** | Single product now. Extract `subscriptions` table when Business tier launches. |

---

## Dependencies

- **Python**: `stripe` PyPI package (add to requirements)
- **Stripe Dashboard Setup**: Create Product, Price, Webhook endpoint, Billing Portal configuration
- **Stripe CLI**: For local webhook testing (`stripe listen`)
- **Environment**: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRO_PRICE_ID`, `FRONTEND_URL`

# Webhook Relay Setup — SnapTrade

Instructions for setting up a public webhook relay so SnapTrade can deliver events to the local backend.

## Background

The backend runs locally at `http://localhost:5001`. SnapTrade needs a **public HTTPS URL** to POST webhook events to. We solve this the same way Plaid does: a lightweight relay at a public URL that forwards webhooks to the backend.

## Architecture

```
SnapTrade servers
    │
    ▼  POST https://<your-relay>/api/snaptrade/webhook
┌─────────────────────┐
│  Webhook Relay       │  (Cloudflare Worker / Vercel / etc.)
│  (public HTTPS)      │
└─────────┬───────────┘
          │  POST http://localhost:5001/api/snaptrade/webhook
          ▼
┌─────────────────────┐
│  FastAPI Backend     │  (routes/snaptrade.py)
│  localhost:5001      │
└─────────────────────┘
```

## What the Relay Needs to Do

The relay is a simple passthrough — **no business logic**:

1. Receive `POST` from SnapTrade at a public URL
2. Forward the **entire request body** (JSON) to `http://localhost:5001/api/snaptrade/webhook`
3. Forward the **`Signature` header** (used for HMAC-SHA256 verification on the backend)
4. Return the backend's response status to SnapTrade (200 = acknowledged)

### Headers to Forward

| Header | Purpose |
|--------|---------|
| `Signature` | SnapTrade HMAC-SHA256 signature — backend verifies this |
| `Content-Type` | Should be `application/json` |

### Minimal Pseudocode

```javascript
// Cloudflare Worker example
export default {
  async fetch(request) {
    if (request.method !== 'POST') {
      return new Response('Method not allowed', { status: 405 });
    }

    const body = await request.text();
    const signature = request.headers.get('Signature') || '';

    const response = await fetch('http://YOUR_BACKEND_URL/api/snaptrade/webhook', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Signature': signature,
      },
      body: body,
    });

    return new Response(response.body, { status: response.status });
  }
};
```

> **Note**: If the backend is on localhost, the relay needs network access to it. Options:
> - **Cloudflare Tunnel** (`cloudflared`) exposes localhost to the internet — relay can hit the tunnel URL instead
> - **Deployed backend** — if the backend is deployed somewhere, use that URL directly
> - **Tailscale / WireGuard** — if relay and backend are on the same private network

## Existing Pattern: Plaid Webhook Forwarding

Plaid uses a similar relay with extra auth headers:

| Header | Value | Purpose |
|--------|-------|---------|
| `X-Plaid-Forwarded` | `"1"` | Marks the request as forwarded |
| `X-Plaid-Forward-Secret` | shared secret | Verified by `_validate_plaid_webhook_forward_auth()` in `routes/plaid.py:186` |

For SnapTrade, we don't need these extra headers — the HMAC `Signature` header from SnapTrade itself serves as auth. The backend verifies it directly.

## Setup Steps

### Step 1: Deploy the Relay

**Recommended: Add to existing Plaid relay** (already deployed)

Add a second route to the existing Plaid webhook relay for `/api/snaptrade/webhook`. The forwarding logic is identical — the only difference is which headers to pass through:

| | Plaid Relay Route | SnapTrade Relay Route |
|---|---|---|
| **Path** | `/plaid/webhook` | `/api/snaptrade/webhook` |
| **Forward to** | `http://<backend>/plaid/webhook` | `http://<backend>/api/snaptrade/webhook` |
| **Headers to add** | `X-Plaid-Forwarded: 1`, `X-Plaid-Forward-Secret: <secret>` | *(none — just pass through existing headers)* |
| **Headers to forward** | `Content-Type` | `Content-Type`, `Signature` |

The `Signature` header comes from SnapTrade and is verified by the backend directly (HMAC-SHA256). No relay-side secret needed — just pass it through.

**Alternative options** (if you'd prefer a separate relay):

- **Cloudflare Tunnel** — `cloudflared tunnel --url http://localhost:5001` gives a public URL with zero code. Downside: URL changes on restart unless you set up a named tunnel.
- **Standalone Cloudflare Worker** — new Worker using the pseudocode above.

### Step 2: Register the Webhook URL with SnapTrade

Via the SnapTrade dashboard or API:

```bash
# Via SnapTrade API (if supported)
curl -X POST https://api.snaptrade.com/api/v1/snapTrade/registerWebhook \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://YOUR_RELAY_URL/api/snaptrade/webhook"
  }'
```

Or set it in the SnapTrade partner dashboard under webhook configuration.

The event types to subscribe to:
- `ACCOUNT_HOLDINGS_UPDATED` — triggers the pending-updates flow
- `CONNECTION_BROKEN` / `CONNECTION_FAILED` — logged for debugging

### Step 3: Configure Backend Environment

Add to your `.env`:

```bash
# SnapTrade webhook HMAC key — use your SnapTrade consumer key
SNAPTRADE_WEBHOOK_SECRET=<your SNAPTRADE_CONSUMER_KEY value>

# (Optional) Record the webhook URL for reference
SNAPTRADE_WEBHOOK_URL=https://YOUR_RELAY_URL/api/snaptrade/webhook
```

If `SNAPTRADE_WEBHOOK_SECRET` is empty, signature verification is **disabled** (all webhooks accepted). Fine for testing, not for production.

### Step 4: Verify

1. **Relay health**: `curl -X POST https://YOUR_RELAY_URL/api/snaptrade/webhook -H 'Content-Type: application/json' -d '{"eventType":"TEST"}'`
   - Should return 200 (backend logs "SnapTrade webhook event ignored: eventType=TEST")

2. **Signature verification**: POST with a bad/missing `Signature` header while `SNAPTRADE_WEBHOOK_SECRET` is set → should return 403

3. **End-to-end**: Make a trade in your brokerage → SnapTrade sends `ACCOUNT_HOLDINGS_UPDATED` → `GET /api/snaptrade/pending-updates` returns `{"has_pending_updates": true}` → frontend shows banner

## Backend Endpoints (already implemented)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/snaptrade/webhook` | POST | Receives SnapTrade webhook events |
| `/api/snaptrade/holdings` | GET | Returns holdings + `has_pending_updates` in metadata |
| `/api/snaptrade/holdings/refresh` | POST | Force-refreshes holdings, clears pending flag |
| `/api/snaptrade/pending-updates` | GET | Lightweight pending flag check (pure DB read) |
| `/plaid/webhook` | POST | Receives Plaid webhook events (already working) |
| `/plaid/holdings/refresh` | POST | Force-refreshes Plaid holdings |
| `/plaid/pending-updates` | GET | Lightweight Plaid pending flag check |

## Files Reference

- `routes/snaptrade.py` — Webhook handler, auth, refresh endpoint
- `routes/plaid.py` — Plaid equivalent (reference implementation)
- `settings.py:497-499` — `SNAPTRADE_WEBHOOK_SECRET`, `SNAPTRADE_WEBHOOK_URL`
- `database/migrations/20260217_add_provider_webhook_state.sql` — DB schema (already run)

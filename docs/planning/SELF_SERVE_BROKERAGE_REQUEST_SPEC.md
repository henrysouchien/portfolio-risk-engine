# Self-Serve Brokerage Request

## 1. Problem Statement

When a user opens the InstitutionPicker to connect a brokerage, they see a fixed list of ~18 institutions defined in `INSTITUTION_CONFIG`. If their brokerage is not listed, they hit a dead end with no way to tell us what they need. We lose the signal entirely -- we do not know which brokerages our users want, and users have no reason to believe the gap will ever be filled.

This feature closes that feedback loop with a lightweight request mechanism: users tell us which brokerage they want, we aggregate the requests, and we use the data to prioritize integrations.

## 2. User Flow

1. User clicks "Add Account" in AccountConnections, opening the InstitutionPicker dialog.
2. User scrolls through Popular Providers and All Providers but does not find their brokerage.
3. At the bottom of the "All Providers" list, a persistent link reads: **"Don't see your brokerage? Request it"**.
4. Clicking the link replaces the provider list with a compact inline form (same dialog, no new page).
5. User fills out the form and submits.
6. A success confirmation replaces the form: "Got it -- we'll notify you when [brokerage name] is available."
7. A "Back to providers" link returns the user to the normal InstitutionPicker view.

The form should also be reachable from the empty state of AccountConnections ("No accounts connected yet") as a secondary CTA below the "Add Account" button.

## 3. Request Form

Fields:

| Field | Type | Required | Notes |
|---|---|---|---|
| `brokerage_name` | text input | Yes | Free text. Autocomplete against known names is a nice-to-have but not MVP. |
| `user_email` | text input (pre-filled) | Yes | Pre-filled from `authStore.user.email`. Editable in case they want notifications at a different address. |
| `country` | dropdown | No | ISO 3166-1 alpha-2. Top entries: US, CA, GB, AU, DE. Default: empty (not specified). |
| `account_type` | dropdown | No | Options: Brokerage, Bank, Crypto, Retirement, Other. Helps us understand what kind of integration is needed. |
| `notes` | textarea | No | Max 500 chars. Free-form context ("I use them for options trading", "They have an API", etc.). |

The form is intentionally small. We want minimal friction -- brokerage name and email are the only required fields.

## 4. Storage

**Recommended approach: DB table.** An external form (Typeform, Google Form) adds a dependency and breaks the in-app flow. A simple DB table keeps everything self-contained and queryable.

### Table: `brokerage_requests`

```sql
CREATE TABLE IF NOT EXISTS brokerage_requests (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    user_email VARCHAR(255) NOT NULL,
    brokerage_name VARCHAR(255) NOT NULL,
    brokerage_name_normalized VARCHAR(255) NOT NULL,
    country VARCHAR(2),
    account_type VARCHAR(50),
    notes TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'requested',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_brokerage_requests_normalized
    ON brokerage_requests(brokerage_name_normalized);

CREATE INDEX IF NOT EXISTS idx_brokerage_requests_user
    ON brokerage_requests(user_id);

CREATE INDEX IF NOT EXISTS idx_brokerage_requests_status
    ON brokerage_requests(status);
```

Migration file: `database/migrations/YYYYMMDD_add_brokerage_requests.sql`

The `brokerage_name_normalized` column stores `lower(trim(brokerage_name))` for dedup/aggregation. Normalization happens server-side on insert.

## 5. Admin Visibility

Two levels, both using existing patterns:

### 5a. Admin API Endpoint

Add to `routes/admin.py` behind `require_admin_token`:

```
GET /admin/brokerage-requests
```

Returns aggregated request data:

```json
{
  "total_requests": 47,
  "unique_brokerages": 12,
  "requests": [
    {
      "brokerage_name": "Questrade",
      "request_count": 14,
      "countries": ["CA"],
      "account_types": ["brokerage"],
      "first_requested": "2026-03-01T...",
      "latest_requested": "2026-03-19T...",
      "status": "requested"
    },
    {
      "brokerage_name": "Degiro",
      "request_count": 8,
      "countries": ["DE", "NL"],
      "account_types": ["brokerage"],
      "first_requested": "2026-03-05T...",
      "latest_requested": "2026-03-18T...",
      "status": "under_review"
    }
  ]
}
```

Results are grouped by `brokerage_name_normalized`, sorted by `request_count` descending. This gives an instant prioritization view.

### 5b. Optional: Slack/Email Notification

On each new request submission, fire a notification (via the existing `notify-mcp` server or a simple webhook) to a Slack channel:

> New brokerage request: **Questrade** (14th request) -- user@example.com, CA, brokerage

This is a nice-to-have. The admin API endpoint is sufficient for MVP.

## 6. Request Status Lifecycle

```
requested  -->  under_review  -->  planned  -->  available
                     |
                     v
                  declined
```

| Status | Meaning |
|---|---|
| `requested` | Default. New submission, not yet reviewed. |
| `under_review` | Team is evaluating feasibility / demand. |
| `planned` | Integration is on the roadmap. |
| `available` | Integration shipped. Brokerage now in `INSTITUTION_CONFIG`. |
| `declined` | Not feasible or out of scope. Optional reason stored in a `status_reason` column (future). |

**User notification on status change:** When status moves to `available`, email the user (all users who requested that brokerage) that their requested brokerage is now supported. This is a post-MVP enhancement -- for MVP, the status is admin-only metadata.

Admin status update endpoint:

```
PATCH /admin/brokerage-requests/:brokerage_name_normalized/status
Body: { "status": "planned" }
```

This updates all rows matching the normalized name.

## 7. Voting / Dedup

We do **not** prevent duplicate submissions from the same user. If a user submits "Questrade" twice, both rows are stored. This is simpler than upsert logic and the aggregation query handles it naturally.

Aggregation query for admin:

```sql
SELECT
    brokerage_name_normalized,
    MAX(brokerage_name) AS display_name,
    COUNT(*) AS total_requests,
    COUNT(DISTINCT user_id) AS unique_users,
    ARRAY_AGG(DISTINCT country) FILTER (WHERE country IS NOT NULL) AS countries,
    ARRAY_AGG(DISTINCT account_type) FILTER (WHERE account_type IS NOT NULL) AS account_types,
    MIN(created_at) AS first_requested,
    MAX(created_at) AS latest_requested,
    MAX(status) AS status
FROM brokerage_requests
GROUP BY brokerage_name_normalized
ORDER BY unique_users DESC, total_requests DESC;
```

The key metric for prioritization is `unique_users` (not `total_requests`), since one persistent user submitting 10 times should not outweigh 10 different users each submitting once.

## 8. Frontend Integration Points

### Files to modify

| File | Change |
|---|---|
| `frontend/packages/ui/src/components/connections/InstitutionPicker.tsx` | Add "Don't see your brokerage?" link below "All Providers" list. Add inline request form state (toggled by the link). Success state after submission. |
| `frontend/packages/ui/src/components/settings/AccountConnections.tsx` | Add secondary CTA in the empty state ("No accounts connected yet") linking to the request flow. |
| `frontend/packages/connectors/src/services/APIService.ts` | Add `submitBrokerageRequest(data)` method calling `POST /api/brokerage-requests`. |

### New files

| File | Purpose |
|---|---|
| `frontend/packages/ui/src/components/connections/BrokerageRequestForm.tsx` | The inline form component. Receives `userEmail` prop (pre-filled), `onSubmit` callback, `onCancel` callback. Renders the 5 fields from section 3. |

### Component hierarchy

```
InstitutionPicker (existing dialog)
  +-- Provider grid (existing)
  +-- "Don't see your brokerage?" link (new)
  +-- BrokerageRequestForm (new, conditionally rendered)
       +-- Text input: brokerage name
       +-- Text input: email (pre-filled)
       +-- Select: country (optional)
       +-- Select: account type (optional)
       +-- Textarea: notes (optional)
       +-- Submit / Cancel buttons
  +-- Success confirmation (new, conditionally rendered)
```

The form uses existing UI primitives (`Button`, `Input`, `Select` from `../ui/`). No new dependencies.

## 9. Backend Integration Points

### New API endpoint

Add a new route file `routes/brokerage_requests.py` with a router `brokerage_requests_router`:

```
POST /api/brokerage-requests
```

- Auth: requires authenticated user (existing auth dependency)
- Rate limit: 5/minute per user (prevents spam)
- Request body: `{ brokerage_name, user_email?, country?, account_type?, notes? }`
- Response: `{ success: true, message: "Request submitted" }`
- Logic: normalize name, insert row, return success

### Admin endpoints (in `routes/admin.py`)

```
GET  /admin/brokerage-requests              -- aggregated list (section 5a)
PATCH /admin/brokerage-requests/:name/status -- update status (section 6)
```

Both require `X-Admin-Token`.

### DB migration

Single migration file: `database/migrations/YYYYMMDD_add_brokerage_requests.sql` (schema from section 4).

### Wire-up

Register `brokerage_requests_router` in `app.py` alongside other routers. No MCP tools needed -- this is a pure REST feature.

## 10. Effort Estimate

| Task | Estimate | Notes |
|---|---|---|
| **Backend: DB migration + POST endpoint** | 0.5 day | Simple table, simple insert. Pattern matches existing routes. |
| **Backend: Admin GET + PATCH endpoints** | 0.5 day | Aggregation query + status update. Add to existing `admin.py`. |
| **Frontend: BrokerageRequestForm component** | 0.5 day | 5 fields, validation, submit handler. Uses existing UI primitives. |
| **Frontend: InstitutionPicker integration** | 0.5 day | Add link, toggle form/success state, wire to API. |
| **Frontend: AccountConnections empty-state CTA** | 0.25 day | Small addition to existing component. |
| **Testing** | 0.5 day | Backend: 4-6 tests (submit, dedup query, status update, auth). Frontend: form render, submit, success state. |
| **Buffer** | 0.25 day | Edge cases, review, polish. |
| **Total** | **3 days** | |

Breakdown: ~1 day backend, ~1.25 days frontend, ~0.75 days testing/buffer.

## Non-Goals

- **Auto-creating integrations** from requests. This is a prioritization signal, not an automation system.
- **Public voting page** where users see other requests and upvote. Adds complexity for marginal value.
- **Real-time status tracking** in the UI. Users submit and forget. We email them when it ships (post-MVP).
- **Admin dashboard UI.** The admin API endpoint is sufficient. A UI can be built later if request volume justifies it.

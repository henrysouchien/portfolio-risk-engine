# Webhook-Driven Refresh Notification — Completion Plan

*Created: 2026-02-19 | Status: Completed 2026-02-19*

## Context

The webhook transport for Plaid is deployed and working — webhooks arrive, get relayed, and the backend handler sets `has_pending_updates` in the DB. But two gaps remain: (1) SnapTrade's webhook handler is a stub, and (2) the frontend never reads the pending flag or calls the POST refresh endpoint. This plan wires both to completion.

## What Already Works (no changes needed)

- **DB layer**: `DatabaseClient` has `get/set_pending_updates`, `store/get/delete_provider_item` — all with graceful degradation if schema missing
- **Schema**: `plaid_has_pending_updates`, `snaptrade_has_pending_updates` columns + `provider_items` table defined in `schema.sql` and migration file (`database/migrations/20260217_add_provider_webhook_state.sql`)
- **Plaid backend**: `GET /plaid/holdings` returns `has_pending_updates`, `POST /plaid/holdings/refresh` force-refreshes and clears flag, webhook sets flag via item_id lookup

## Route Prefix Reference

- Plaid router: `prefix='/plaid'` (`routes/plaid.py:430`)
- SnapTrade router: `prefix='/api/snaptrade'` (`routes/snaptrade.py:203`)
- Frontend PlaidService calls: `/plaid/*` (`PlaidService.ts:169`)
- Frontend SnapTradeService calls: `/api/snaptrade/*` (`SnapTradeService.ts:162`)

## Changes

### Step 0: Run DB Migration (if needed)

```bash
python3 admin/run_migration.py database/migrations/20260217_add_provider_webhook_state.sql
```

Idempotent (`IF NOT EXISTS`). Verify columns exist afterward.

---

### Step 1: SnapTrade Backend — `routes/snaptrade.py`

**1a. Add helper functions** (mirror `routes/plaid.py` lines 194-269):
- `_get_snaptrade_pending_updates(user_id) -> bool`
- `_set_snaptrade_pending_updates(user_id, has_updates)`
- `_store_snaptrade_item_mapping(user_id, snaptrade_user_hash)`
- `_set_snaptrade_pending_updates_for_webhook_user(snaptrade_user_id)` — resolves user via `get_user_by_provider_item("snaptrade", hash)`, then sets flag

All use existing `DatabaseClient` methods + `get_db_session()`. Wrap in try/except with warnings (same as Plaid helpers).

**1b. Update `WebhookRequest` model and wire webhook handler** (lines 179-182, 899-907):

SnapTrade webhook payload uses top-level fields (from [SnapTrade docs](https://docs.snaptrade.com/docs/webhooks)):
- `webhookId`, `clientId`, `eventTimestamp`, `userId`, `eventType`
- Event-specific: `brokerageId`, `accountId`, `brokerageAuthorizationId`

Update model:

```python
class WebhookRequest(BaseModel):
    model_config = ConfigDict(extra="allow")  # Accept any extra fields
    type: Optional[str] = None                # Legacy/normalized field
    eventType: Optional[str] = None           # SnapTrade native field
    userId: Optional[str] = None              # SnapTrade user hash (top-level)
    accountId: Optional[str] = None
    brokerageAuthorizationId: Optional[str] = None
    webhookId: Optional[str] = None
    clientId: Optional[str] = None
    eventTimestamp: Optional[str] = None
    data: Optional[Dict[str, Any]] = None     # Keep for backward compat
```

**Add webhook auth guard** — SnapTrade uses HMAC-SHA256 with the `Signature` header, keyed on the client secret:

```python
import base64, hashlib, hmac, json
from datetime import datetime, timezone

REPLAY_WINDOW_S = 300  # 5 minutes

def _verify_snaptrade_webhook(request: Request, body: bytes) -> None:
    """Verify SnapTrade webhook via HMAC-SHA256 Signature header.

    Disabled (no-op) when SNAPTRADE_WEBHOOK_SECRET is empty.
    Uses client secret as HMAC key. Rejects replays older than 5 minutes.
    Ref: https://docs.snaptrade.com/docs/webhooks
    """
    secret = settings.SNAPTRADE_WEBHOOK_SECRET.strip()
    if not secret:
        return  # Auth enforcement disabled

    # Signature check
    expected_sig = request.headers.get("Signature", "")
    canonical = json.dumps(
        json.loads(body), separators=(",", ":"), sort_keys=True
    ).encode()
    computed = base64.b64encode(
        hmac.new(secret.encode(), canonical, hashlib.sha256).digest()
    ).decode()
    if not hmac.compare_digest(computed, expected_sig):
        portfolio_logger.warning("Rejecting SnapTrade webhook: signature mismatch")
        raise HTTPException(status_code=403, detail="Forbidden")

    # Replay check
    event_ts = json.loads(body).get("eventTimestamp")
    if event_ts:
        try:
            ts = datetime.fromisoformat(event_ts.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - ts).total_seconds()
            if abs(age) > REPLAY_WINDOW_S:
                portfolio_logger.warning(f"Rejecting stale SnapTrade webhook: age={age:.0f}s")
                raise HTTPException(status_code=403, detail="Stale webhook")
        except (ValueError, TypeError):
            portfolio_logger.warning("Rejecting SnapTrade webhook: malformed eventTimestamp")
            raise HTTPException(status_code=403, detail="Invalid timestamp")
```

Update webhook handler signature to accept `request: Request` and read raw body. `SNAPTRADE_WEBHOOK_SECRET` already exists in `settings.py:498` — set it to the SnapTrade client secret.

Wire event types:
- `ACCOUNT_HOLDINGS_UPDATED` → extract `userId`, call `_set_snaptrade_pending_updates_for_webhook_user()`
- `CONNECTION_BROKEN` / `CONNECTION_FAILED` → log with user context
- Other events → log for debugging

**1c. Store mapping during connection** — in `create-connection-url` endpoint (line 338), after successful URL creation:
- Call `get_snaptrade_user_id_from_email(user['email'])` (from `snaptrade_loader.py:343`)
- Call `_store_snaptrade_item_mapping(user['user_id'], snaptrade_user_hash)`

**1c-backfill. Lazy backfill for existing users**: In `GET /api/snaptrade/holdings` (line ~543), after successful auth:
```python
snaptrade_user_hash = get_snaptrade_user_id_from_email(user['email'])
_store_snaptrade_item_mapping(user['user_id'], snaptrade_user_hash)
```
`store_provider_item` uses `ON CONFLICT ... DO UPDATE`, so repeated calls are safe.

**1d. Add `has_pending_updates` to GET response** (line ~608):
- Call `_get_snaptrade_pending_updates(user['user_id'])`
- Add to `portfolio_metadata` dict

**1e. Add `POST /api/snaptrade/holdings/refresh` endpoint** (after line 648):
- Mirror `routes/plaid.py:807-879`
- Guard: check `snaptrade_client` is available (return 503 if not, matching line 541)
- Apply refresh cooldown (Step 1f)
- `position_service.get_positions(provider='snaptrade', use_cache=False, force_refresh=True, consolidate=True)`
- Clear pending flag after success
- Extract shared holdings-building logic into `_build_snaptrade_holdings_payload()` helper
- **Response shape**: Return `HoldingsResponse` with `holdings.portfolio_data` containing flat `{ holdings: [...], total_portfolio_value, statement_date, account_type }` matching the `Portfolio` interface the frontend expects

**1f. Refresh rate limiting** — Per-user cooldown for both refresh endpoints:
```python
import time
_refresh_cooldowns: Dict[int, float] = {}
REFRESH_COOLDOWN_S = 60

def _check_refresh_cooldown(user_id: int) -> Optional[int]:
    last = _refresh_cooldowns.get(user_id)
    if last and (time.time() - last) < REFRESH_COOLDOWN_S:
        return int(REFRESH_COOLDOWN_S - (time.time() - last))
    return None

def _record_refresh(user_id: int) -> None:
    _refresh_cooldowns[user_id] = time.time()
```
Apply to both Plaid and SnapTrade refresh endpoints. Return 429 with `Retry-After`. **Limitation**: Process-local (in-memory dict) — acceptable for single-process deployment.

**1g. Add lightweight `/pending-updates` endpoints**:

Pure DB reads — no provider API calls:

```python
# routes/plaid.py
@plaid_router.get("/pending-updates")
async def get_plaid_pending_status(request: Request):
    session_id = request.cookies.get('session_id')
    user = auth_service.get_user_by_session(session_id)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return {"has_pending_updates": _get_plaid_pending_updates(user['user_id'])}

# routes/snaptrade.py — same pattern
```

---

### Step 2: Frontend — Fix Refresh Flow

**2a. Add `refreshPlaidHoldings()` to `PlaidService`** (`frontend/src/chassis/services/PlaidService.ts`):
- `POST /plaid/holdings/refresh`
- Returns `HoldingsApiResponse` (same shape as GET)

**2b. Add `refreshSnapTradeHoldings()` to `SnapTradeService`** (`frontend/src/chassis/services/SnapTradeService.ts`):
- `POST /api/snaptrade/holdings/refresh`

**2c. Update `PortfolioManager.refreshHoldings()`** (`frontend/src/chassis/managers/PortfolioManager.ts:524`):

Currently calls `this.apiService.getPlaidHoldings()` (GET, cache-only). Fix:

New signature accepts per-provider flags from `usePendingUpdates()`:
```typescript
public async refreshHoldings(
  providers?: { plaid?: boolean; snaptrade?: boolean }
): Promise<{ portfolio: any; error: string | null; status?: number }>
```

When `providers` is omitted (fallback), refresh all connected providers. When provided, only refresh providers where the flag is `true`.

1. Build refresh promise list from provider flags:
   ```typescript
   const promises: Promise<any>[] = [];
   if (!providers || providers.plaid)  promises.push(this.apiService.refreshPlaidHoldings());
   if (!providers || providers.snaptrade) promises.push(this.apiService.refreshSnapTradeHoldings());
   const results = await Promise.allSettled(promises);
   ```
2. **Response normalization**: Backend returns `{ success, holdings: { portfolio_data: {...}, portfolio_metadata: {...} } }`. The `Portfolio` interface (`frontend/src/chassis/types/index.ts:63`) expects `{ holdings: Holding[], total_portfolio_value, statement_date, account_type }`. Extract `response.holdings.portfolio_data` as the portfolio:
   ```typescript
   function extractPortfolio(raw: any): Portfolio | null {
     const pd = raw?.holdings?.portfolio_data;
     if (!pd) return null;
     return {
       holdings: pd.holdings || [],
       total_portfolio_value: pd.total_portfolio_value || 0,
       statement_date: pd.statement_date || new Date().toISOString().slice(0, 10),
       account_type: pd.account_type || 'investment',
     };
   }
   ```
   The `statement_date` and `account_type` fields are defaulted when missing to satisfy the `Portfolio` interface contract.
3. **Multi-provider merge**: If both providers are refreshed, merge holdings arrays and sum total values:
   ```typescript
   // Check for 429 in rejected results FIRST
   const rejected429 = results.find(
     r => r.status === 'rejected' && (r.reason as any)?.status === 429
   );
   if (rejected429) {
     return { portfolio: null, error: 'Please wait before refreshing again', status: 429 };
   }

   const portfolios = results
     .filter(r => r.status === 'fulfilled')
     .map(r => extractPortfolio(r.value))
     .filter(Boolean) as Portfolio[];

   if (portfolios.length === 0) {
     const firstError = results.find(r => r.status === 'rejected');
     const msg = firstError ? (firstError as PromiseRejectedResult).reason?.message : 'No provider data';
     return { portfolio: null, error: msg || 'No provider data' };
   }
   if (portfolios.length === 1) return { portfolio: portfolios[0], error: null };

   const merged: Portfolio = {
     holdings: portfolios.flatMap(p => p.holdings),
     total_portfolio_value: portfolios.reduce((s, p) => s + p.total_portfolio_value, 0),
     statement_date: portfolios[0].statement_date,
     account_type: portfolios[0].account_type,
   };
   return { portfolio: merged, error: null };
   ```
   `PortfolioRepository.add()` receives a `Portfolio`-shaped object with all required fields.

**2d. Expose in `APIService`** (`frontend/src/chassis/services/APIService.ts`):
- Add `refreshPlaidHoldings()` and `refreshSnapTradeHoldings()`

**2e. Handle 429 in `fetchWithRetry`** (`frontend/src/chassis/services/APIService.ts:184`):
- Add a 429 check at the TOP of the response-handling block, BEFORE the retry logic. This ensures the 429 is thrown immediately and never enters the retry loop:
  ```typescript
  // In fetchWithRetry, after `const response = await fetch(...)`:
  if (response.status === 429) {
    // Short-circuit: do NOT retry rate-limited responses
    const err: any = new Error('Please wait before refreshing again');
    err.status = 429;
    err.retryAfter = parseInt(response.headers.get('Retry-After') || '60', 10);
    throw err;  // Exits fetchWithRetry immediately, no retry
  }
  // ... existing retry logic for other non-2xx statuses follows
  ```
- The catch block in `fetchWithRetry` must NOT catch and retry this throw — the 429 error propagates directly to the caller
- This aligns with `usePortfolioSummary.ts:315` which checks `error?.status === 429` to skip retries

**2e-ii. Preserve 429 through `PortfolioManager.refreshHoldings()` return type**:

Update the return type to include `status`:
```typescript
public async refreshHoldings(
  providers?: { plaid?: boolean; snaptrade?: boolean }
): Promise<{ portfolio: any; error: string | null; status?: number }> {
  // ... (see 2c for body)
  catch (error) {
    const errorMessage = error instanceof Error ? error.message : String(error);
    const status = (error as any)?.status;
    return { portfolio: null, error: errorMessage, status };
  }
}
```

**2f. Fix 429 drop at `SessionServicesProvider.tsx:333`** (safety net — not the primary refresh path):

The primary refresh path is `handleRefresh` in `HoldingsViewModernContainer` (Step 3b), which directly calls `refreshHoldings()` and handles the result including 429. However, `SessionServicesProvider` also has a `refresh-holdings` intent handler that could be invoked from other UI paths. Fix it as a safety net:

Current code (line 331-334):
```typescript
const result = await manager.refreshHoldings();
if (result.error || !result.portfolio) {
  throw new Error(result.error || 'Failed to refresh holdings');
}
```

Fix by preserving status on the thrown error:
```typescript
const result = await manager.refreshHoldings();
if (result.error || !result.portfolio) {
  const err: any = new Error(result.error || 'Failed to refresh holdings');
  err.status = result.status;  // Preserve 429 status for upstream handling
  throw err;
}
```

**End-to-end 429 flow (two paths)**:
1. **Primary (Step 3b)**: `fetchWithRetry` (429 → throw .status) → `refreshHoldings()` (checks rejected results for 429, returns `{ status: 429 }`) → `handleRefresh` (checks `result.status === 429` → shows toast)
2. **Safety net (Step 2f)**: `fetchWithRetry` → `refreshHoldings()` → `SessionServicesProvider` handler (preserves `.status` on thrown Error) → intent caller

---

### Step 3: Frontend — "Updates Available" UI

**3a. Add `usePendingUpdates()` hook** (`frontend/src/features/portfolio/hooks/usePendingUpdates.ts`):
- Uses TanStack `useQueries` to fetch `GET /plaid/pending-updates` and `GET /api/snaptrade/pending-updates`
- `refetchInterval: 5 * 60 * 1000` (5 min) + `refetchIntervalInBackground: true` for real polling
- Returns **per-provider flags plus combined boolean**:
  ```typescript
  interface PendingUpdatesResult {
    hasPendingUpdates: boolean;        // Combined: plaid || snaptrade
    plaidPending: boolean;
    snaptradePending: boolean;
    refetch: () => void;
  }
  ```
- `hasPendingUpdates` drives the UI banner (combined); `plaidPending`/`snaptradePending` are passed to `refreshHoldings()` so it only refreshes providers with actual pending data

**3b. Thread into container** (`frontend/src/components/dashboard/views/modern/HoldingsViewModernContainer.tsx`):
- Import `usePendingUpdates()` hook
- Pass `hasPendingUpdates` (combined boolean) prop to `HoldingsView`
- In `handleRefresh`: pass per-provider flags to `refreshHoldings()`:
  ```typescript
  const { hasPendingUpdates, plaidPending, snaptradePending, refetch } = usePendingUpdates();

  const handleRefresh = async () => {
    const result = await manager.refreshHoldings({ plaid: plaidPending, snaptrade: snaptradePending });
    if (result.status === 429) {
      // Concrete user feedback: show toast notification
      toast({ title: 'Please wait', description: 'Refresh available again shortly.', variant: 'default' });
      return;
    }
    if (result.error || !result.portfolio) {
      toast({ title: 'Refresh failed', description: result.error || 'Unknown error', variant: 'destructive' });
      return;
    }
    // Success — save portfolio and re-poll pending status to clear banner
    const currentId = usePortfolioStore.getState().currentPortfolioId;
    const currentName = currentId ? PortfolioRepository.getName(currentId) : undefined;
    const updated = { ...result.portfolio, id: currentId ?? undefined, portfolio_name: currentName ?? 'CURRENT_PORTFOLIO' };
    const id = PortfolioRepository.add(updated);
    PortfolioRepository.setCurrent(id);
    refetch();
  };
  ```
- This ensures only providers with actual pending data are refreshed (avoids unnecessary SnapTrade syncs)

**3c. Add prop to `HoldingsView`** (`frontend/src/components/portfolio/HoldingsView.tsx`):
- Add `hasPendingUpdates?: boolean` to `HoldingsViewProps` (line ~394)
- Render amber banner when true:
  ```tsx
  {hasPendingUpdates && (
    <div className="flex items-center gap-2 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mb-4">
      <Badge variant="outline" className="bg-amber-100 text-amber-700">New</Badge>
      <span className="text-amber-700 text-sm">Updated data available from your broker</span>
      <button onClick={onRefresh} disabled={isRefreshing}
        className="ml-auto text-sm text-blue-600 hover:text-blue-800 font-medium">
        {isRefreshing ? 'Refreshing...' : 'Refresh Now'}
      </button>
    </div>
  )}
  ```

**3d. Fix `lastSynced` display**:

1. **`PortfolioSummaryAdapter.ts:411`** — Change from `new Date().toLocaleString()` to use real timestamp:
   ```typescript
   lastUpdated: rawData?.portfolio_metadata?.last_updated
     ? new Date(rawData.portfolio_metadata.last_updated).toLocaleString()
     : new Date().toLocaleString()
   ```
2. **`HoldingsView.tsx:1086`** — Change from `new Date().toLocaleTimeString()` to:
   ```tsx
   Updated {portfolioData?.summary?.lastUpdated || new Date().toLocaleTimeString(...)}
   ```

---

## Files Modified

| File | Changes |
|------|---------|
| `routes/snaptrade.py` | `WebhookRequest` model, HMAC-SHA256 auth guard, helpers, webhook handler, pending flag in GET, POST refresh, lazy backfill, `/pending-updates` |
| `routes/plaid.py` | Refresh cooldown, `/pending-updates` endpoint |
| `frontend/src/chassis/services/PlaidService.ts` | `refreshPlaidHoldings()` (POST) |
| `frontend/src/chassis/services/SnapTradeService.ts` | `refreshSnapTradeHoldings()` (POST) |
| `frontend/src/chassis/services/APIService.ts` | Expose refresh methods, 429 handling in `fetchWithRetry` |
| `frontend/src/chassis/managers/PortfolioManager.ts` | Fix `refreshHoldings()`: POST, multi-provider merge, response normalization to `Portfolio` shape |
| `frontend/src/features/portfolio/hooks/usePendingUpdates.ts` | **New** — polling `/pending-updates` endpoints |
| `frontend/src/components/dashboard/views/modern/HoldingsViewModernContainer.tsx` | Thread `hasPendingUpdates` via hook |
| `frontend/src/components/portfolio/HoldingsView.tsx` | "Updates available" banner |
| `frontend/src/adapters/PortfolioSummaryAdapter.ts` | `lastUpdated` from real timestamp |

## Tests

| Test file | Coverage |
|-----------|----------|
| `tests/api/test_snaptrade_webhook.py` | Webhook auth (403 on bad sig, 200 on valid/disabled), replay rejection, event routing, lazy backfill |
| `tests/api/test_refresh_cooldown.py` | 429 on rapid refresh, cooldown clears after interval, independent per-user |
| `tests/api/test_pending_updates.py` | `/pending-updates` returns correct flag after webhook + after refresh clear |

## Key Reuse

- `DatabaseClient.get_pending_updates()` / `set_pending_updates()` / `store_provider_item()` / `get_user_by_provider_item()` — `inputs/database_client.py`
- `get_snaptrade_user_id_from_email()` — `snaptrade_loader.py:343`
- `PositionService.get_positions(force_refresh=True)` — `services/position_service.py`
- `SNAPTRADE_WEBHOOK_SECRET` — `settings.py:498` (set to SnapTrade client secret for HMAC-SHA256)
- Plaid webhook auth pattern — `routes/plaid.py:168-186`
- Plaid helpers pattern — `routes/plaid.py:194-269`
- Plaid refresh endpoint pattern — `routes/plaid.py:807-879`
- `Badge` component — `frontend/src/components/ui/badge.tsx`
- TanStack Query — `frontend/src/features/portfolio/hooks/usePortfolioSummary.ts`
- `Portfolio` interface — `frontend/src/chassis/types/index.ts:63`

## Edge Cases

1. **Legacy SnapTrade users**: Lazy backfill on first `GET /api/snaptrade/holdings` after deploy.
2. **Refresh abuse**: Per-user 60s cooldown. 429 with `Retry-After`. Frontend stops retrying. Process-local only.
3. **Missing schema**: All DB methods gracefully degrade.
4. **SnapTrade webhook shape**: Model accepts native fields + legacy `{type, data}`.
5. **Multi-provider users**: `refreshHoldings(providers)` only refreshes providers with pending data (per-provider flags from `usePendingUpdates()`). Merges holdings arrays and sums total values. Defaults all `Portfolio` fields (`statement_date`, `account_type`) when backend omits them.
6. **Webhook auth**: HMAC-SHA256 with `Signature` header, keyed on client secret. Replay rejection (5min window). Malformed `eventTimestamp` → 403 (not silently skipped). Opt-in via `SNAPTRADE_WEBHOOK_SECRET`.
7. **Polling cost**: `/pending-updates` endpoints are pure DB reads.
8. **Response normalization**: `refreshHoldings()` extracts `response.holdings.portfolio_data` to match `Portfolio` interface. `extractPortfolio()` helper provides safe defaults for all required fields.
9. **429 end-to-end preservation**: `fetchWithRetry` → `refreshHoldings()` return → `SessionServicesProvider` thrown error all preserve `.status = 429`. No link in the chain drops it.

## Verification

1. **Migration**: `python3 admin/run_migration.py database/migrations/20260217_add_provider_webhook_state.sql`
2. **Webhook auth**: POST to `/api/snaptrade/webhook` with bad/missing `Signature` header → 403; with correct HMAC → 200
3. **Webhook fire**: `ACCOUNT_HOLDINGS_UPDATED` event → pending flag set in DB
4. **GET holdings**: `GET /api/snaptrade/holdings` includes `has_pending_updates` in `portfolio_metadata`
5. **Pending status**: `GET /api/snaptrade/pending-updates` → `{"has_pending_updates": true}`
6. **POST refresh**: `POST /api/snaptrade/holdings/refresh` → fresh data, flag cleared
7. **Rate limit**: Second refresh within 60s → 429 with `Retry-After`
8. **Lazy backfill**: First GET creates `provider_items` row
9. **Frontend**: Banner appears → refresh → banner disappears
10. **Frontend 429 toast**: Trigger rapid refresh → second click shows "Please wait" toast (not error toast)
11. **Frontend safety-net path**: Invoke `refresh-holdings` intent via SessionServicesProvider → verify 429 status preserved on thrown error
12. **Tests**: `pytest tests/api/test_snaptrade_webhook.py tests/api/test_refresh_cooldown.py tests/api/test_pending_updates.py`

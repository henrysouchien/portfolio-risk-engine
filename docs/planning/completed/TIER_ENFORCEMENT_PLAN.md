# A1: Tier Enforcement Middleware

> **Created**: 2026-03-16
> **Parent**: `docs/OPEN_SOURCE_LAUNCH_GAPS.md` (item A1)
> **Goal**: Gate routes by user tier so that cost-generating features (LLM, Plaid, real-time data) require a paid subscription.

---

## Current State

**What exists**:
- `users.tier` column: `VARCHAR(50) DEFAULT 'public'` — values: `public`, `registered`, `paid`
- Auth routes already return `tier` in user dict (`/auth/status`, `/auth/google`)
- `create_auth_dependency(auth_service)` in `app_platform/auth/dependencies.py` — shared session→user resolution, already used by gateway proxy
- `@require_db` decorator pattern in `mcp_tools/common.py` — proven gating pattern for MCP tools
- Rate limiting via `slowapi` on some routes
- New users created with tier `'registered'` (`PostgresUserStore.get_or_create_user`)

**What's missing**:
- Zero tier checks on any route
- No tier-aware FastAPI dependency
- No structured 403 response for upgrade prompts

---

## Design Decisions

### D1: Keep internal tier values, map display names in frontend

**Do NOT rename** `public`/`registered`/`paid` in the database. The blast radius is too large — it spans `auth/stores.py`, `rate_limiter.py` (both copies), `admin.py`, `app.py`, and the frontend. Instead:

- Backend keeps `public`, `registered`, `paid` internally
- Frontend maps to display names: `registered` → "Free", `paid` → "Pro"
- Add `business` as a new DB value when needed (future)

This avoids a risky cross-stack migration and lets us ship tier enforcement without touching auth internals.

**Tier ordering** (for gate checks):
```python
TIER_ORDER = {"public": 0, "registered": 1, "paid": 2, "business": 3}
```

Gate on `paid` (not a renamed "pro") — `registered` users are unpaid, `paid` users have upgraded.

### D2: Extend existing auth dependency, don't create a new one

The shared auth dependency already exists at `app_platform/auth/dependencies.py:create_auth_dependency()`. It resolves session→user with tier included. Build tier checking on top of this — don't create a parallel `_get_user_from_request()` path.

### D3: HTTP session gating and Agent API gating are separate problems

- **HTTP routes** (Plaid, gateway, positions, etc.): Use session cookie auth via `create_auth_dependency`. Tier comes from the user dict.
- **Agent API** (`/agent/call`): Uses static Bearer token (`AGENT_API_KEY`) + env-var user resolution (`RISK_MODULE_USER_EMAIL`). This is a single-user local tool, not a multi-user web endpoint. **Do not gate the agent API by tier in this phase.** It's an internal/admin boundary, not an end-user billing boundary.

MCP tools called directly via `mcp_server.py` (stdio) also don't need tier gating — they run locally.

### D4: Gate only true cost drivers — LLM calls and live brokerage API calls

The strategy says free tier includes "dashboard and manual analysis tools (what-if, stress test, optimization — via UI)." These are CPU-only computation endpoints — they cost us nothing to serve. Only gate endpoints that call external paid APIs:

- **LLM endpoints** (Anthropic API cost): `/api/analyze`, `/api/interpret`, `ai-recommendations`, `metric-insights`
- **Plaid connection/refresh** (Plaid API cost): `create_link_token`, `exchange_public_token`, `holdings/refresh`
- **Live broker operations** (broker API cost): trading execution, order management
- **Live data refresh** (FMP API cost): `refresh-prices`

**FREE** (no external API cost):
- Cached reads (positions, holdings, Plaid cached data)
- CPU computation (risk-score, performance, what-if, optimization, stress-test, monte-carlo, backtest)
- CRUD operations (portfolios, allocations, settings)

The principle: gate the **action that calls a paid external API**, not cached reads or local computation.

### D5: Gateway gating must distinguish normalizer from chat

The gateway proxy (`/api/gateway/chat`) serves two purposes:
1. **AI chat** (portfolio analyst) — high LLM cost, ongoing usage → **PAID**
2. **Normalizer builder** (CSV onboarding) — one-time LLM cost per format → **FREE**

Gating the entire router breaks free-tier CSV onboarding. Frontend-only hiding is insufficient — a free user can call the route directly.

**Solution**: Add a context-aware check inside the gateway flow. The request body already includes a `context.channel` field (set to `"web"` by `GatewayClaudeService`). Extend this with a `context.purpose` field:
- `context.purpose = "normalizer"` → allow for all authenticated users (existing `create_auth_dependency`)
- `context.purpose = "chat"` (or absent) → require `paid` tier

The `NormalizerBuilderPanel` sets `context.purpose = "normalizer"` when calling the gateway. The chat panel sends `context.purpose = "chat"` (or omits it, defaulting to chat).

**Implementation**: Add a check in `create_gateway_router()` or in the gateway proxy handler itself, after parsing the request body. This is a single check, not a full middleware refactor.

**Abuse mitigation**: Free users with `context.purpose = "normalizer"` are rate-limited to 20 requests/day (sufficient for CSV normalization, not for ongoing chat).

### D6: `/api/analyze` is FREE with graceful degradation

`/api/analyze` (`app.py` line ~1298) is the core dashboard risk analysis endpoint. Investigation shows:
- Core analysis (`get_analysis_result_snapshot`) is CPU computation → no external API cost
- Optional LLM usage: `get_factor_proxies_snapshot(allow_gpt=True)` uses LLM for factor proxy auto-detection
- The LLM step is already gated by a boolean flag

**Decision**: Keep `/api/analyze` FREE. For free users, pass `allow_gpt=False` (skip GPT-assisted factor proxies). Analysis works fully, just without auto-detected proxies. This matches the strategy: "manual analysis tools" are free.

### D7: Exclude `/api/direct/*` from this phase

The `/api/direct/stock` and `/api/direct/interpret` endpoints use API-key authentication, not session cookies. They are a separate auth model from `create_auth_dependency`. Gating them requires a different mechanism (API-key tier lookup). Defer to a future phase.

### D8: One 403 schema, owned by A1

A1 defines the canonical 403 upgrade response. A2 (frontend) consumes it.

```json
{
  "detail": {
    "error": "upgrade_required",
    "message": "This feature requires a paid subscription.",
    "tier_required": "paid",
    "tier_current": "registered"
  }
}
```

---

## Step 1: Create `require_paid_user` FastAPI Dependency

Extend the existing `create_auth_dependency` pattern. Add a tier-checking wrapper in the same file.

**File**: `app_platform/auth/dependencies.py`

```python
TIER_ORDER = {"public": 0, "registered": 1, "paid": 2, "business": 3}

def create_tier_dependency(
    auth_service: AuthServiceBase,
    minimum_tier: str = "paid",
    cookie_name: str = "session_id",
) -> Callable[[Request], dict[str, Any]]:
    """Return a FastAPI dependency that requires authentication + minimum tier."""

    get_user = create_auth_dependency(auth_service, cookie_name)

    def require_tier(request: Request) -> dict[str, Any]:
        user = get_user(request)  # raises 401 if not authenticated
        user_tier = user.get("tier", "registered")
        if TIER_ORDER.get(user_tier, 0) < TIER_ORDER.get(minimum_tier, 0):
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "upgrade_required",
                    "message": f"This feature requires a {minimum_tier} subscription.",
                    "tier_required": minimum_tier,
                    "tier_current": user_tier,
                },
            )
        return user

    return require_tier
```

**Usage at route level** (e.g., `routes/plaid.py`):
```python
from app_platform.auth.dependencies import create_tier_dependency
from services.auth_service import auth_service

_require_paid = create_tier_dependency(auth_service, minimum_tier="paid")

@plaid_router.post("/create_link_token")
async def create_link_token(request: Request, user=Depends(_require_paid)):
    ...
```

**Files**:
- `app_platform/auth/dependencies.py` — add `create_tier_dependency`, `TIER_ORDER`

---

## Step 2: Apply Tier Gates to Routes

### PAID-gated (external API cost drivers only)

**Plaid** (`routes/plaid.py`) — connection + refresh endpoints (NOT cached reads):
- `POST /plaid/create_link_token` — Plaid API call
- `POST /plaid/create_update_link_token` — Plaid API call
- `POST /plaid/exchange_public_token` — Plaid API call
- `POST /plaid/holdings/refresh` — Plaid API call
- `DELETE /plaid/connections/{slug}` — Plaid API call

**Plaid FREE** (cached, no API cost):
- `GET /plaid/connections` — cached read
- `GET /plaid/holdings` — 24hr cached read
- `GET /plaid/pending-updates` — local state
- `GET /plaid/connection_status` — local state
- `POST /plaid/webhook` — incoming, not outbound

**SnapTrade** (`routes/snaptrade.py`) — same pattern: gate connection + refresh, keep cached reads free

**Positions** (`routes/positions.py`) — gate only LLM endpoints:
- `GET /api/positions/ai-recommendations` — LLM cost → **PAID**
- `GET /api/positions/metric-insights` — LLM cost → **PAID**
- `GET /api/positions/market-intelligence` — FMP + LLM → **PAID**

**Positions FREE** (cached reads + local computation):
- `GET /api/positions/monitor` — cached → **FREE**
- `GET /api/positions/holdings` — cached → **FREE**
- `GET /api/positions/export` — cached → **FREE**
- `GET /api/positions/alerts` — cached → **FREE**

**app.py direct endpoints** — gate LLM interpretation + live data refresh only:
- `POST /api/interpret` — LLM → **PAID**
- `POST /api/portfolio/refresh-prices` — FMP live call → **PAID**
- `POST /api/analyze` — **FREE** (with degradation). Core analysis is CPU computation. LLM is only used optionally for factor proxy auto-detection (`allow_gpt=True` in `get_factor_proxies_snapshot`). For free users, call with `allow_gpt=False` — analysis works, just without GPT-assisted factor proxies. See D6.

**app.py FREE** (CPU computation, no external API):
- `POST /api/risk-score` — local computation → **FREE**
- `POST /api/performance` — local computation → **FREE**
- `POST /api/what-if`, `/api/min-variance`, `/api/max-return`, `/api/efficient-frontier` — local computation → **FREE**
- `POST /api/stress-test`, `/api/stress-test/run-all`, `/api/monte-carlo`, `/api/backtest` — local computation → **FREE**
- `POST /api/portfolio-analysis` — local computation → **FREE**

**Trading** (`routes/trading.py`) — broker API cost:
- `GET /api/trading/accounts` → **AUTH**
- `POST /preview`, `POST /execute`, `GET /orders`, `POST /cancel` → **PAID**
- `GET /api/trading/analysis` → **FREE** (transaction DB only)

**Factor Intelligence** (`routes/factor_intelligence.py`):
- 4 analysis endpoints (FMP API calls) → **PAID**
- Factor groups CRUD → **FREE**

**Other PAID**:
- `GET /api/income/projection` — FMP dividend data
- Baskets: `from-etf` (FMP ETF holdings), `analyze` (FMP pricing) → **PAID** (CRUD stays free)

### FREE (no cost to serve)

- Auth (all)
- Onboarding: status, ibkr-status, preview-csv, import-csv, stage-csv
- Portfolio CRUD
- Target allocations, scenario history, expected returns, risk settings
- Strategy templates, factor groups CRUD, basket CRUD
- Tax harvest (transaction DB only)
- Provider routing intelligence
- Frontend logging, health check
- Cached position reads, cached Plaid/SnapTrade reads
- All CPU-only analysis: risk-score, performance, what-if, optimization, stress-test, monte-carlo, backtest
- Realized performance (`POST /api/performance/realized` — uses cached data)
- Hedging preview (CPU computation), hedge monitor (cached)

### GATEWAY — context-aware gating (see D5)

- **Gateway proxy** (`/api/gateway/chat`) — context-aware: `purpose=normalizer` → free (rate-limited); `purpose=chat` or absent → paid. See Step 3.

### NOT GATED (separate auth boundary — defer)

- **Agent API** (`/agent/call`) — Bearer token auth, not session. Internal/admin. Defer.
- **`/api/direct/*`** — API-key auth, not session. Different auth model. Defer. See D7.
- **Admin routes** — already gated by `require_admin_token`

---

## Step 3: Gateway Context-Aware Tier Check

Add a purpose-based check in the gateway proxy flow. The request body includes `context` — extend with `purpose`.

**File**: `app_platform/gateway/proxy.py` (in the chat handler)

```python
# Inside the chat endpoint handler, after parsing request body:
purpose = body.get("context", {}).get("purpose", "chat")
if purpose != "normalizer":
    # This is a general chat request — require paid tier
    user_tier = user.get("tier", "registered")
    if TIER_ORDER.get(user_tier, 0) < TIER_ORDER.get("paid", 0):
        raise HTTPException(
            status_code=403,
            detail={
                "error": "upgrade_required",
                "message": "AI chat requires a paid subscription.",
                "tier_required": "paid",
                "tier_current": user_tier,
            },
        )
# Normalizer requests pass through with rate limiting for free users
```

**Frontend changes** (3 files):

1. `GatewayClaudeService.ts` — `sendMessageStream()` needs to accept and forward `purpose` in the context. Currently builds context at line 122-126. Add `purpose` to the `context` object:
   ```typescript
   // sendMessageStream() signature adds optional purpose param:
   async* sendMessageStream(
     message: string, history: ChatMessage[],
     portfolioName?: string, purpose?: string,
   )
   // In request body context (line 122-126):
   context: {
     channel: 'web',
     ...(portfolioName ? { portfolio_name: portfolioName } : {}),
     ...(purpose ? { purpose } : {}),
   },
   ```

2. `NormalizerBuilderPanel.tsx` — when calling gateway, pass `purpose: "normalizer"`. The normalizer builder calls `GatewayClaudeService` (lines 74, 94, 150) — add purpose param to these calls.

3. `usePortfolioChat.ts` — when calling gateway for chat, pass `purpose: "chat"` (or omit, defaulting to chat on backend). Line 646:
   ```typescript
   const streamGenerator = gatewayService.sendMessageStream(trimmed, messages, portfolioDisplayName, 'chat');
   ```

**Rate limit**: Add a per-user rate limit for free users on normalizer gateway requests (20/day via `slowapi`).

---

## Step 4: Admin Tier Management

Add ability to manually set user tier (testing, customer support, business onboarding).

**File**: `routes/admin.py`

```python
@admin_router.post("/set-tier")
async def set_user_tier(request: Request, body: dict = Body(...), _auth=Depends(require_admin_token)):
    email = body.get("email")
    tier = body.get("tier")
    if tier not in ("public", "registered", "paid", "business"):
        raise HTTPException(400, detail=f"Invalid tier: {tier}")
    # UPDATE users SET tier = %s, updated_at = NOW() WHERE email = %s
```

---

## Execution Order

1. **Step 1**: `create_tier_dependency` in `app_platform/auth/dependencies.py` — 1 file
2. **Step 2**: Apply gates to cost-driver routes — ~8 route files, mechanical
3. **Step 3**: Gateway context-aware tier check — 2 files (proxy handler + NormalizerBuilderPanel context)
4. **Step 4**: Admin tier management — 1 file

Steps 1-4 are backend-only (Step 3 has one frontend touch for context.purpose). Can be done in one session.

---

## Testing

- Unit test: `create_tier_dependency` returns user for `paid` user, raises 403 for `registered` user
- Unit test: 403 response body matches canonical schema (`upgrade_required`)
- Integration test: `registered` user hits paid endpoint → 403 with correct body
- Integration test: `paid` user hits paid endpoint → 200
- Integration test: free endpoints remain accessible to `registered` users
- Regression: existing tests still pass (no breakage on ungated endpoints)
- Gateway proxy: `registered` user with `purpose=chat` → 403. `purpose=normalizer` → 200 (rate-limited).
- Gateway proxy: `paid` user with any purpose → 200
- Normalizer builder: free user CSV onboarding flow works end-to-end through gateway

---

## Out of Scope (deferred)

- **Agent API tier gating**: `/agent/call` uses Bearer token auth, not session. Separate auth boundary. Gate when agent API becomes multi-user.
- **MCP tool tier gating**: MCP tools run locally via stdio. No tier concept needed for local execution.
- **Tier value rename**: Internal values stay `public`/`registered`/`paid`. Frontend maps display names.
- **Per-tier rate limits**: Binary access control only in this phase. Rate limits per tier are a future enhancement.
- **Stripe integration**: Separate plan (B1). This plan only enforces tiers — it doesn't handle payment.

---

## Codex Review Changelog

### Round 1 (2026-03-16) — 5 issues

| # | Finding | Fix |
|---|---------|-----|
| 1 | Plan invents new `_get_user_from_request()` instead of extending existing `create_auth_dependency` | Rebased on `create_auth_dependency`. New `create_tier_dependency` wraps it. |
| 2 | Agent API uses Bearer token, not session — tier gating doesn't fit | Explicitly deferred. Agent API is internal/admin boundary, not end-user billing. |
| 3 | Tier rename blast radius underestimated | Dropped rename entirely. Keep internal values, map display names in frontend (D1). |
| 4 | Over-gates free tier — cached Plaid reads don't cost money | Narrowed to true cost drivers. Cached reads are free. Detailed per-endpoint classification added (Step 2). |
| 5 | Error contract undefined — A1 and A2 both partly own 403 handling | A1 defines canonical 403 schema (D5). A2 consumes it. Clear ownership. |

### Round 2 (2026-03-16) — 3 issues

| # | Finding | Fix |
|---|---------|-----|
| 1 | Gateway gate too coarse — normalizer builder also uses `/api/gateway/chat` and is a free feature | Do NOT gate gateway router (D5). AI chat gated at frontend (A2). Normalizer builder stays accessible. |
| 2 | Over-gates analysis endpoints — strategy says dashboard + manual analysis tools are free | Moved risk-score, performance, what-if, optimization, stress-test, monte-carlo, backtest to FREE. Only LLM interpretation + live data refresh are PAID. |
| 3 | `/api/direct/*` uses API-key auth, not session — different auth model | Excluded from this phase (D6→D7). Separate auth mechanism needed. |

### Round 3 (2026-03-16) — 3 issues

| # | Finding | Fix |
|---|---------|-----|
| 1 | Frontend-only hiding is not backend enforcement — free user can call gateway directly | Added Step 3: context-aware gateway check. `purpose=normalizer` → free (rate-limited). `purpose=chat` → paid. Backend enforcement with normalizer carve-out. |
| 2 | `/api/analyze` may include LLM step, conflicts with "manual analysis is free" | Added D6: investigate during implementation. Split LLM sub-step if separable, gate if not. |
| 3 | Duplicate D5 numbering | Renumbered to D5/D6/D7. |

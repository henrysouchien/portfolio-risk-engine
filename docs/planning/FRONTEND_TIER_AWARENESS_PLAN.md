# A2: Frontend Tier Awareness

> **Created**: 2026-03-16
> **Parent**: `docs/OPEN_SOURCE_LAUNCH_GAPS.md` (item A2)
> **Depends on**: A1 (Tier Enforcement — specifically the 403 `upgrade_required` schema)
> **Goal**: UI conditionally shows features vs upgrade prompts based on user tier. Free tier feels complete; Pro features are visible but gated.

---

## Current State

**Already working**:
- `User` type has `tier?: 'public' | 'registered' | 'paid'`
- `mapAuthUser()` validates tier on every auth check
- `useUser()` hook gives access to `user.tier` in any component
- Backend returns `tier` in `/auth/status` and `/auth/google` responses
- Session store JOIN includes `u.tier` from users table

**What's missing**:
- No component checks `user.tier` for conditional rendering
- No upgrade prompt component
- 403s are all classified as `auth` errors in `classifyError.ts` (line 40) — no distinction between "not logged in" and "upgrade required"
- `GatewayClaudeService` uses raw `fetch()`, not `HttpClient` — separate 403 handling needed
- AI chat surfaces in multiple places: chat panel, floating Ask AI button (`ModernDashboardApp.tsx` lines 115, 153, 510, 651)
- Brokerage connection surfaces in onboarding AND settings (`AccountConnectionsContainer.tsx`)
- `SessionServicesProvider` recreates on `user.id` change but NOT `user.tier` change (line 201-202)

---

## Design Decisions

### D1: Work with existing tier values, map display names

Per A1's decision, backend keeps `public`/`registered`/`paid` internally. Frontend maps:
- `registered` → "Free" (display)
- `paid` → "Pro" (display)

No type changes needed — the existing `User.tier` union already includes these values.

### D2: Single `UpgradeRequiredError` shared by all HTTP paths

Both `HttpClient` and `GatewayClaudeService` need to detect the 403 upgrade response. Create a shared error type that both code paths throw, and that `classifyError.ts` recognizes.

### D3: Gate real entry points first, defer cosmetic badges

Focus on the surfaces that actually trigger cost:
1. AI chat (all mount points)
2. Brokerage connection (onboarding + settings)
3. AI-powered cards (recommendations, insights)

Defer: nav-wide "Pro" badges, teaser states for every panel, settings pricing page. Those are polish for after Stripe (B1) exists.

---

## Step 1: `UpgradeRequiredError` Type

Shared error type that both `HttpClient` and `GatewayClaudeService` throw on 403 upgrade responses.

**New file**: `frontend/packages/app-platform/src/errors/UpgradeRequiredError.ts`

```typescript
export class UpgradeRequiredError extends Error {
  readonly tierRequired: string;
  readonly tierCurrent: string;
  readonly status = 403;

  constructor(tierRequired: string, tierCurrent: string, message?: string) {
    super(message ?? `This feature requires a ${tierRequired} subscription.`);
    this.name = 'UpgradeRequiredError';
    this.tierRequired = tierRequired;
    this.tierCurrent = tierCurrent;
  }
}
```

Export from `app-platform` barrel.

---

## Step 2: Update `classifyError.ts`

Currently line 40 lumps 401 and 403 together as `auth`. Split them.

**File**: `frontend/packages/chassis/src/errors/classifyError.ts`

```typescript
// Before (line 40):
if (status === 401 || status === 403) {
  return new DataSourceError({ category: 'auth', ... });
}

// After:
if (status === 401) {
  return new DataSourceError({ category: 'auth', ... });
}

if (status === 403) {
  // Check if this is an upgrade_required response
  if (error instanceof UpgradeRequiredError) {
    return new DataSourceError({
      category: 'upgrade_required',
      sourceId,
      statusCode: 403,
      retryable: false,
      userMessage: error.message,
      cause: error,
    });
  }
  // Generic 403 (permission denied, not upgrade)
  return new DataSourceError({
    category: 'auth',
    sourceId,
    statusCode: 403,
    retryable: false,
    userMessage: 'You do not have permission to access this resource.',
    cause: error,
  });
}
```

Add `'upgrade_required'` to the `DataSourceError` category union type.

---

## Step 3: 403 Handling in `HttpClient`

Detect the `upgrade_required` 403 and throw `UpgradeRequiredError` instead of a generic error.

**File**: `frontend/packages/app-platform/src/http/HttpClient.ts`

In the response error handling path:

```typescript
if (response.status === 403) {
  const body = await response.json().catch(() => null);
  if (body?.detail?.error === 'upgrade_required') {
    throw new UpgradeRequiredError(
      body.detail.tier_required,
      body.detail.tier_current,
      body.detail.message,
    );
  }
  // Fall through to generic error handling
}
```

---

## Step 4: 403 Handling in `GatewayClaudeService`

The gateway chat uses raw `fetch()`, not `HttpClient`. It already handles non-ok responses at line 130-133 by yielding `{ type: 'error', content: ... }`. Add a dedicated `upgrade_required` chunk type.

**File**: `frontend/packages/chassis/src/services/GatewayClaudeService.ts`

In `sendMessageStream()`, the existing non-ok handler (line 130-133):

```typescript
// Before:
if (!response.ok) {
  const body = await response.text();
  yield { type: 'error', content: `Gateway error (${response.status}): ${body}` };
  return;
}

// After:
if (!response.ok) {
  if (response.status === 403) {
    const body = await response.json().catch(() => null);
    if (body?.detail?.error === 'upgrade_required') {
      yield {
        type: 'upgrade_required',
        tierRequired: body.detail.tier_required,
        tierCurrent: body.detail.tier_current,
        content: body.detail.message,
      };
      return;
    }
  }
  const body = await response.text();
  yield { type: 'error', content: `Gateway error (${response.status}): ${body}` };
  return;
}
```

Add `'upgrade_required'` to the `ClaudeStreamChunk` type union in `ClaudeStreamTypes.ts`.

**Note**: The gateway has context-aware gating per A1 Step 3 (`purpose=normalizer` → free, `purpose=chat` → paid). This 403 handler fires when a free user hits the gateway with `purpose=chat`.

**Chat UI rendering**: `ChatCore.tsx` (line ~1258) renders error blocks from `chatStatus.error`. When `error.type === 'upgrade_required'`, render the `UpgradePrompt` component (from Step 5) instead of the generic error message. This gives a dedicated upgrade CTA in the chat panel:

```typescript
// In ChatCore.tsx error rendering:
if (chatStatus.error?.type === 'upgrade_required') {
  return <UpgradePrompt feature="ai-chat" variant="inline" />;
}
// Fall through to generic error rendering for other error types
```

**Consumer handling in `usePortfolioChat.ts`**: The streaming loop (line 655) processes chunks. Add `upgrade_required` to the chunk processing:

```typescript
// In the for-await chunk loop:
if (chunk.type === 'upgrade_required') {
  const chatError: ChatError = {
    type: 'upgrade_required',
    message: chunk.content ?? 'This feature requires a paid subscription.',
    retryable: false,
  };
  setChatStatus({ state: 'error', error: chatError });
  // IMPORTANT: return, not break — avoid falling through to the
  // completion block after the loop which would overwrite the error state
  return;
}
```

Add `'upgrade_required'` to the `ChatError.type` union (line 112):
```typescript
type: 'network' | 'api' | 'auth' | 'rate_limit' | 'token_limit' | 'server' | 'upgrade_required' | 'unknown';
```

**NormalizerBuilderPanel** also uses `GatewayClaudeService`. Per A1 Step 3, it sends `purpose: "normalizer"` which the backend allows for all authenticated users. The normalizer builder will never see a 403 upgrade response. No changes needed there.

---

## Step 5: `useTier` Hook + `UpgradePrompt` Component

### `useTier` hook

**New file**: `frontend/packages/chassis/src/hooks/useTier.ts`

```typescript
import { useUser } from '../stores/authStore';

// Maps internal DB values to display names. Only uses values
// that exist in the current User.tier union: 'public' | 'registered' | 'paid'
const TIER_DISPLAY: Record<string, string> = {
  public: 'Free',
  registered: 'Free',
  paid: 'Pro',
};

export function useTier() {
  const user = useUser();
  const tier = user?.tier ?? 'registered';

  return {
    tier,
    displayName: TIER_DISPLAY[tier] ?? 'Free',
    isPaid: tier === 'paid',
    isFree: tier === 'public' || tier === 'registered',
  };
}
```

**Note**: No changes to `User.tier` type or `mapAuthUser()` in this phase. The existing `'public' | 'registered' | 'paid'` union is correct. `business` will be added to the type when the business tier ships (future).

### `UpgradePrompt` component

**New file**: `frontend/packages/ui/src/components/common/UpgradePrompt.tsx`

```typescript
interface UpgradePromptProps {
  feature: string;
  variant?: 'inline' | 'overlay';
}

const FEATURE_MESSAGES: Record<string, { title: string; description: string }> = {
  'ai-chat': {
    title: 'AI Investment Analyst',
    description: 'Chat with an AI that knows your portfolio.',
  },
  'live-brokerage': {
    title: 'Live Brokerage Connection',
    description: 'Connect to your brokerage for real-time positions.',
  },
  'ai-insights': {
    title: 'AI-Powered Insights',
    description: 'Get AI recommendations and analysis for your portfolio.',
  },
};
```

---

## Step 6: Gate Pro Features in UI

### 6a. AI Chat (all mount points)

AI chat surfaces in multiple places in `ModernDashboardApp.tsx`. Gate all of them.

**File**: `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx`

```typescript
const { isPaid } = useTier();

// Line ~115: Chat panel
{isPaid ? <AIChat /> : <UpgradePrompt feature="ai-chat" variant="inline" />}

// Line ~153: Floating Ask AI button
{isPaid && <AskAIButton />}

// Line ~510, 651: Any other chat entry points — same pattern
```

### 6b. Brokerage Connection (onboarding + settings)

**Onboarding**: `OnboardingWizard.tsx` — show CSV as primary for free, badge Plaid/SnapTrade/Schwab.

**Settings**: `AccountConnectionsContainer.tsx` (line 261) — gate "Connect" buttons for live brokerages.

```typescript
const { isPaid } = useTier();
// Plaid connect button:
{isPaid ? <PlaidConnect /> : <UpgradePrompt feature="live-brokerage" variant="overlay" />}
```

### 6c. AI-Powered Dashboard Cards

- `ai-recommendations` card → gate or show upgrade prompt
- `metric-insights` card → gate or show upgrade prompt
- `market-intelligence` card → gate or show upgrade prompt

These are the cards backed by LLM endpoints (gated in A1 Step 2).

---

## Step 7: Handle Mid-Session Tier Changes

`SessionServicesProvider` (line 201-202) recreates services when `user.id` changes. When a user upgrades mid-session, the tier changes but the services and cached queries are stale.

**File**: `frontend/packages/connectors/src/providers/SessionServicesProvider.tsx`

The actual dependency that triggers service recreation is at lines 201-202 and 318. Add `user.tier` to this dependency array / memo key:

```typescript
// Find the useMemo or useEffect that depends on user.id
// Add user?.tier to the dependency array so services recreate on upgrade

// Also: invalidate React Query cache on tier change
// so that previously-403'd queries retry with the new tier
useEffect(() => {
  if (user?.tier) {
    queryClient.invalidateQueries();
  }
}, [user?.tier]);
```

This ensures that when a user upgrades (tier changes from `registered` to `paid`), session services are recreated and previously-gated queries automatically retry.

---

## File Summary

| File | Change |
|------|--------|
| **New**: `frontend/packages/app-platform/src/errors/UpgradeRequiredError.ts` | Shared error type |
| `frontend/packages/chassis/src/errors/classifyError.ts` | Split 401/403, add `upgrade_required` category |
| `frontend/packages/app-platform/src/http/HttpClient.ts` | Detect 403 upgrade, throw `UpgradeRequiredError` |
| `frontend/packages/chassis/src/services/GatewayClaudeService.ts` | Detect 403 upgrade on chat fetch |
| **New**: `frontend/packages/chassis/src/hooks/useTier.ts` | Tier helper hook with display name mapping |
| **New**: `frontend/packages/ui/src/components/common/UpgradePrompt.tsx` | Upgrade prompt component |
| `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx` | Gate AI chat, Ask AI button, AI cards |
| `frontend/packages/ui/src/components/onboarding/OnboardingWizard.tsx` | Gate live brokerage options |
| `frontend/packages/ui/src/components/settings/AccountConnectionsContainer.tsx` | Gate brokerage connect buttons |
| `frontend/packages/connectors/src/providers/SessionServicesProvider.tsx` | Add `user.tier` to memo dependency |

---

## Execution Order

1. **Step 1**: `UpgradeRequiredError` type (standalone, no deps)
2. **Step 2**: Update `classifyError.ts` (needs Step 1)
3. **Step 3**: `HttpClient` 403 handling (needs Step 1)
4. **Step 4**: `GatewayClaudeService` 403 handling (needs Step 1)
5. **Step 5**: `useTier` hook + `UpgradePrompt` component (standalone)
6. **Step 6**: Gate Pro features (needs Steps 3-5 + A1 backend gates deployed)
7. **Step 7**: Mid-session tier change handling (standalone)

Steps 1-5 can be done before A1 backend is deployed (frontend is ready to handle the 403 when it comes). Step 6 depends on A1 being live so gates actually fire.

---

## Testing

- `UpgradeRequiredError`: construction, fields, instanceof checks
- `classifyError`: 401 → `auth`, 403 upgrade → `upgrade_required`, 403 generic → `auth`
- `HttpClient`: 403 with `upgrade_required` body throws `UpgradeRequiredError`
- `GatewayClaudeService`: 403 on chat yields `{ type: 'upgrade_required' }` chunk
- `useTier`: `registered` → isFree=true, `paid` → isPaid=true, display names correct
- `UpgradePrompt`: renders with correct feature messaging
- AI chat: renders for `paid` user, shows prompt for `registered` user
- Mid-session: changing `user.tier` in store triggers service recreation
- Regression: `paid` users see no change from current behavior

---

## Out of Scope (deferred)

- **Nav-wide Pro badges**: Cosmetic — add after Stripe (B1) when upgrade actually works
- **Settings pricing page**: Needs billing backend (B1)
- **Teaser states for every panel**: Polish — focus on real cost-driver entry points first

---

## Codex Review Changelog

### Round 1 (2026-03-16) — 5 issues

| # | Finding | Fix |
|---|---------|-----|
| 1 | Depends on A1's tier rename — riskiest part | Dropped rename dependency. Works with existing values, maps display names (D1). |
| 2 | `HttpClient` 403 handler misses chat surface — `GatewayClaudeService` uses raw `fetch()` | Added Step 4: explicit 403 handling in `GatewayClaudeService`. |
| 3 | `classifyError.ts` lumps 401+403 as `auth` — upgrade will look like "please log in" | Step 2 splits 401/403, adds `upgrade_required` category. |
| 4 | UI scope understated — AI chat in multiple mount points, brokerage in onboarding+settings | Step 6 explicitly lists all entry points with line references. |
| 5 | Mid-session tier changes not handled — `SessionServicesProvider` recreates on `user.id` only | Step 7 adds `user.tier` to memo dependency key. |

### Round 2 (2026-03-16) — 4 issues

| # | Finding | Fix |
|---|---------|-----|
| 1 | Step 4 uses `this.onError?.()` which doesn't exist — `GatewayClaudeService` yields chunks | Rewrote Step 4 to yield `{ type: 'upgrade_required' }` chunk, matching existing non-ok handler at line 130-133. |
| 2 | Gateway also used by normalizer builder — 403 contract must work there too | Gateway is NOT gated (A1 D5). NormalizerBuilderPanel never sees 403 upgrade. Noted explicitly. |
| 3 | `business` in `useTier` but not in current `User.tier` union | Removed `business` from first-pass `useTier` and `TIER_DISPLAY`. Only existing values used. |
| 4 | `usePortfolioChat` has closed `ChatError` type — needs `upgrade_required` | Added `'upgrade_required'` to `ChatError.type` union and chunk processing in streaming loop. |

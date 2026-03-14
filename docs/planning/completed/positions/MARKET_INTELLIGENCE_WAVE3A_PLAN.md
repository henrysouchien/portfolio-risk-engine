# Wave 3a: Market Intelligence — Wire Real Market Data

**Status**: COMPLETE — Commit `5151dd0a`
**Parent doc**: `completed/FRONTEND_PHASE2_WORKING_DOC.md` → Item 1 (Market Intelligence)
**Date**: 2026-03-03

## Context

The Portfolio Overview (`PortfolioOverview.tsx`) has a Market Intelligence section that currently renders nothing — `const marketEvents: MarketEvent[] = []` (line 569). The FMP tools already provide news (`get_news()`) and events calendar (`get_events_calendar()`) via `fmp/tools/news_events.py`, but these are only accessible through MCP — there are no REST API endpoints for market data.

**Goal:** Surface real portfolio-relevant news and upcoming earnings as Market Intelligence in the Overview tab.

## Scope

| Item | Layer | Effort |
|------|-------|--------|
| Shared `build_market_events()` builder | Backend shared logic | Medium |
| New `/api/positions/market-intelligence` endpoint | Backend route (thin) | Low |
| `getMarketIntelligence()` API method | Frontend chassis | Trivial |
| `marketIntelligenceKey` query key | Frontend chassis | Trivial |
| `useMarketIntelligence()` hook | Frontend connectors | Low |
| Wire events through container → component | Frontend UI | Low |

## Design Decisions

1. **Data sources**: Two FMP calls — `get_news(symbols=..., mode="stock")` for portfolio-relevant news + `get_events_calendar(event_type="earnings")` for upcoming earnings. Skip `get_market_context()` to keep scope manageable.
2. **Shared builder pattern**: `mcp_tools/news_events.py` already has `_load_portfolio_symbols()`, `get_portfolio_news()`, and `get_portfolio_events_calendar()` — portfolio-aware wrappers around FMP tools. The new `build_market_events()` composer goes here too, reusing `get_portfolio_news()` / `get_portfolio_events_calendar()`. Both the API endpoint and a future MCP tool call this shared function. No duplication of position-loading or FMP-calling logic.
3. **Endpoint location**: `routes/positions.py` as `GET /market-intelligence` — thin wrapper that calls `build_market_events()` from `mcp_tools/news_events.py`.
4. **Relevance scoring**: The `MarketEvent.relevance` interface comment says `0-1` but the rendering code at line 1092 displays `{event.relevance}% relevant` (expects 0-100 integer). Backend returns 0-100 integers to match existing rendering.
5. **Caching**: FMPClient has internal cache. Hook uses 5-minute `staleTime` (market data refreshes moderately).

---

## Step 1a: Shared Builder — `build_market_events()` in `mcp_tools/news_events.py`

**File**: `mcp_tools/news_events.py`

Add `build_market_events()` alongside the existing `get_portfolio_news()` and `get_portfolio_events_calendar()`. This function **reuses** those existing portfolio-aware wrappers (which already handle `_load_portfolio_symbols()`, ticker extraction, `fmp_ticker` mapping, `_NEWSWORTHY_TYPES` filtering, and account scoping) — no duplication.

```python
def build_market_events(
    user_email: Optional[str] = None,
    account: Optional[str] = None,
    use_cache: bool = True,
    news_limit: int = 8,
    earnings_days: int = 14,
    max_events: int = 8,
) -> list[dict]:
    """Build MarketEvent list from portfolio news + earnings calendar.

    Shared builder used by both API endpoint and MCP tools.
    Reuses get_portfolio_news() / get_portfolio_events_calendar() for
    portfolio-aware FMP data fetching.
    """
    from datetime import datetime, timedelta

    # Load portfolio weights for relevance scoring
    ticker_weights = _load_portfolio_weights(user_email=user_email, account=account, use_cache=use_cache)

    events: list[dict] = []

    # --- News-based events ---
    try:
        news_result = get_portfolio_news(
            user_email=user_email,
            account=account,
            mode="stock",
            limit=news_limit,
            use_cache=use_cache,
        )
        # Fall back to general news if no portfolio symbols
        if news_result.get("status") == "error" and "symbols is required" in news_result.get("error", ""):
            news_result = get_news(mode="general", limit=news_limit, quality="trusted")

        if news_result.get("status") == "success":
            for article in news_result.get("articles", [])[:6]:
                ticker = (article.get("symbol") or "").upper()
                weight = ticker_weights.get(ticker, 0)
                relevance = min(95, max(10, int(weight * 300 + 20))) if ticker else 15

                events.append({
                    "type": "sentiment",
                    "impact": _infer_news_impact(article),
                    "description": article.get("title", ""),
                    "relevance": relevance,
                    "timeframe": "Current",
                    "actionRequired": relevance > 60,
                    "ticker": ticker or None,
                })
    except Exception:
        pass  # News failure should not break the caller

    # --- Earnings calendar events ---
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        to_date = (datetime.now() + timedelta(days=earnings_days)).strftime("%Y-%m-%d")
        earnings_result = get_portfolio_events_calendar(
            user_email=user_email,
            event_type="earnings",
            from_date=today,
            to_date=to_date,
            account=account,
            use_cache=use_cache,
        )
        if earnings_result.get("status") == "success":
            for evt in earnings_result.get("events", [])[:4]:
                ticker = (evt.get("symbol") or "").upper()
                weight = ticker_weights.get(ticker, 0)
                relevance = min(95, max(20, int(weight * 300 + 30)))

                desc = f"{ticker} earnings report on {evt.get('date', 'upcoming')}"
                if evt.get("eps_estimated"):
                    desc += f" (EPS est: ${evt['eps_estimated']})"

                events.append({
                    "type": "earnings",
                    "impact": "neutral",
                    "description": desc,
                    "relevance": relevance,
                    "timeframe": evt.get("date", "Upcoming"),
                    "actionRequired": weight > 0.05,
                    "ticker": ticker or None,
                })
    except Exception:
        pass  # Earnings failure should not break the caller

    events.sort(key=lambda e: e.get("relevance", 0), reverse=True)
    return events[:max_events]
```

**Helper: `_load_portfolio_weights()`** — extract ticker weights from positions (companion to existing `_load_portfolio_symbols()`):

```python
def _load_portfolio_weights(
    user_email: Optional[str] = None,
    account: Optional[str] = None,
    use_cache: bool = True,
) -> dict[str, float]:
    """Load portfolio ticker weights for relevance scoring.

    Keys are fmp_ticker (falling back to ticker) to match the symbols
    returned by get_portfolio_news() / get_portfolio_events_calendar().
    Mirrors _load_portfolio_symbols() edge-case handling.
    """
    if account and not account.strip():
        account = None

    from services.position_service import PositionService
    from settings import get_default_user

    user = user_email or get_default_user()
    if not user:
        return {}

    try:
        position_service = PositionService(user)
        position_result = position_service.get_all_positions(
            use_cache=use_cache,
            force_refresh=False,
            consolidate=not bool(account),
        )
    except (ValueError, ConnectionError, OSError):
        return {}

    positions = position_result.data.positions
    if account:
        positions = [p for p in positions if match_brokerage(account, p.get("brokerage_name"))]

    total_value = sum(abs(float(p.get("value") or 0)) for p in positions) or 1.0
    weights: dict[str, float] = {}
    for pos in positions:
        ticker = (pos.get("ticker") or "").strip()
        ptype = (pos.get("type") or "").strip().lower()
        if ptype not in _NEWSWORTHY_TYPES:
            continue
        if not ticker or ticker.startswith("CUR:"):
            continue
        # Use fmp_ticker to match symbols in FMP news/calendar responses
        fmp_ticker = (pos.get("fmp_ticker") or ticker).strip().upper()
        if not fmp_ticker:
            continue
        weight = abs(float(pos.get("value") or 0)) / total_value
        weights[fmp_ticker] = weights.get(fmp_ticker, 0) + weight
    return weights
```

**Helper: `_infer_news_impact()`** — keyword-based sentiment heuristic:

```python
_NEGATIVE_KEYWORDS = {"downgrade", "loss", "decline", "crash", "warning", "miss", "layoff",
                      "default", "lawsuit", "investigation", "recall", "plunge", "cut"}
_POSITIVE_KEYWORDS = {"upgrade", "beat", "surge", "growth", "record", "raise", "gain",
                      "approval", "expansion", "breakout", "bullish", "rally"}

def _infer_news_impact(article: dict) -> str:
    """Simple keyword heuristic for news sentiment."""
    text = ((article.get("title") or "") + " " + (article.get("snippet") or "")).lower()
    neg = sum(1 for w in _NEGATIVE_KEYWORDS if w in text)
    pos = sum(1 for w in _POSITIVE_KEYWORDS if w in text)
    if neg > pos:
        return "negative"
    if pos > neg:
        return "positive"
    return "neutral"
```

---

## Step 1b: API Endpoint — Thin wrapper in `routes/positions.py`

**File**: `routes/positions.py`

Add after the existing `/alerts` endpoint (after line 235). The endpoint is now a thin auth + call wrapper — all logic lives in `build_market_events()`.

```python
@positions_router.get("/market-intelligence")
async def get_market_intelligence(request: Request):
    """Return market events relevant to the user's portfolio holdings."""
    session_id = request.cookies.get("session_id")
    user = auth_service.get_user_by_session(session_id)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        from mcp_tools.news_events import build_market_events
        events = build_market_events(user_email=user["email"])
        return {"success": True, "events": events, "total": len(events)}

    except Exception as e:
        portfolio_logger.error(f"Market intelligence failed: {e}")
        log_error("positions_api", "market_intelligence", e)
        raise HTTPException(status_code=500, detail="Failed to generate market intelligence")
```

**Why so thin**: All position loading, FMP calls, relevance scoring, and event merging live in `build_market_events()`. The endpoint just handles auth and HTTP response shaping. A future MCP `get_market_intelligence()` tool would call the same `build_market_events()` with no changes.

---

## Step 2: Frontend Chassis — API method + query key

### 2a. Query key

**File**: `frontend/packages/chassis/src/queryKeys.ts`

Add after `portfolioAlertsKey` (line 190):
```typescript
export const marketIntelligenceKey           = () => ['marketIntelligence'] as const;
```

Add to `AppQueryKey` union (line 225):
```typescript
  | ReturnType<typeof marketIntelligenceKey>
```

### 2b. APIService method

**File**: `frontend/packages/chassis/src/services/APIService.ts`

Add response interface and method after `getPortfolioAlerts()`:

```typescript
interface MarketIntelligenceResponse {
  success: boolean;
  events: Array<Record<string, unknown>>;
  total: number;
}

async getMarketIntelligence(): Promise<MarketIntelligenceResponse> {
  return this.request<MarketIntelligenceResponse>('/api/positions/market-intelligence');
}
```

---

## Step 3: Frontend Connectors — `useMarketIntelligence()` hook

**New file**: `frontend/packages/connectors/src/features/positions/hooks/useMarketIntelligence.ts`

Follows the exact `useSmartAlerts` pattern (same directory):

```typescript
import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';
import { frontendLogger, marketIntelligenceKey } from '@risk/chassis';
import { useSessionServices } from '../../../providers/SessionServicesProvider';

export interface MarketEvent {
  type: 'earnings' | 'fed' | 'economic' | 'geopolitical' | 'technical' | 'sentiment';
  impact: 'positive' | 'negative' | 'neutral';
  description: string;
  relevance: number;
  probability?: number;
  timeframe?: string;
  actionRequired?: boolean;
}

function transformEvents(payload: { events: Array<Record<string, unknown>> }): MarketEvent[] {
  return (payload.events || []).map((e) => ({
    type: (e.type as MarketEvent['type']) ?? 'sentiment',
    impact: (e.impact as MarketEvent['impact']) ?? 'neutral',
    description: String(e.description ?? ''),
    relevance: Number(e.relevance ?? 0),
    probability: e.probability != null ? Number(e.probability) : undefined,
    timeframe: e.timeframe ? String(e.timeframe) : undefined,
    actionRequired: Boolean(e.actionRequired),
  }));
}

export const useMarketIntelligence = () => {
  const { api } = useSessionServices();

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: marketIntelligenceKey(),
    queryFn: async (): Promise<MarketEvent[]> => {
      frontendLogger.adapter.transformStart('useMarketIntelligence', {
        source: '/api/positions/market-intelligence',
      });
      const payload = await api.getMarketIntelligence();
      const events = transformEvents(payload);
      frontendLogger.adapter.transformSuccess('useMarketIntelligence', {
        eventCount: events.length,
      });
      return events;
    },
    enabled: !!api,
    staleTime: 5 * 60 * 1000,  // 5 minutes — market data refreshes moderately
    retry: (failureCount) => failureCount < 2,
  });

  return useMemo(
    () => ({
      data: data ?? [],
      loading: isLoading,
      error: error instanceof Error ? error.message : null,
      refetch,
    }),
    [data, isLoading, error, refetch]
  );
};
```

**Export chain**:

**File**: `frontend/packages/connectors/src/features/positions/index.ts` — add:
```typescript
export { useMarketIntelligence } from './hooks/useMarketIntelligence';
```

**File**: `frontend/packages/connectors/src/index.ts` — update line 5:
```typescript
export { usePositions, useSmartAlerts, useMarketIntelligence } from './features/positions';
```

---

## Step 4: Frontend UI — Wire through container → component

### 4a. PortfolioOverviewContainer

**File**: `frontend/packages/ui/src/components/dashboard/views/modern/PortfolioOverviewContainer.tsx`

1. Update import (line 40):
```typescript
import { IntentRegistry, usePortfolioSummary, useSessionServices, useSmartAlerts, useMarketIntelligence } from '@risk/connectors';
```

2. Add hook call after line 72:
```typescript
const { data: marketEvents } = useMarketIntelligence();
```

3. Pass prop (line 209, after `smartAlerts`):
```typescript
<PortfolioOverview
  data={portfolioOverviewData}
  smartAlerts={smartAlerts}
  marketEvents={marketEvents}       // NEW
  onRefresh={handleRefresh}
  loading={isLoading}
  className={props.className}
  {...props}
/>
```

### 4b. PortfolioOverview component

**File**: `frontend/packages/ui/src/components/portfolio/PortfolioOverview.tsx`

1. **Add `marketEvents` to `PortfolioOverviewProps`** (line 308-326):
```typescript
interface PortfolioOverviewProps {
  data?: { summary: { ... } };
  smartAlerts?: SmartAlert[];
  marketEvents?: MarketEvent[];    // NEW — from container
  onRefresh?: () => void;
  loading?: boolean;
  className?: string;
}
```

2. **Destructure prop** (line 328-334): add `marketEvents: externalMarketEvents = []`:
```typescript
export default function PortfolioOverview({
  data,
  smartAlerts: externalAlerts = [],
  marketEvents: externalMarketEvents = [],  // NEW
  onRefresh: _onRefresh,
  loading: _loading = false,
  className: _className = ""
}: PortfolioOverviewProps) {
```

3. **Remove internal stub** (line 569):
   - Delete `const marketEvents: MarketEvent[] = []`

4. **Update rendering** (lines 1049-1109): replace all `marketEvents` references with `externalMarketEvents`:
   - Line 1049: `{externalMarketEvents.length > 0 && (`
   - Line 1065: `{externalMarketEvents.filter(e => e.actionRequired).length} Action Items`
   - Line 1071: `{externalMarketEvents.map((event, index) => (`

The existing rendering code uses `event.type`, `event.impact`, `event.description`, `event.relevance`, `event.timeframe`, `event.probability`, `event.actionRequired` — all match our backend response shape. No rendering changes needed.

---

## Step 5: CacheCoordinator — Add invalidation

**File**: `frontend/packages/chassis/src/services/CacheCoordinator.ts`

1. Add `marketIntelligenceKey` to import (line 52):
```typescript
import {
  portfolioSummaryKey, riskSettingsKey, positionsHoldingsKey,
  portfolioAlertsKey, marketIntelligenceKey    // ADD
} from '../queryKeys';
```

2. Add to `invalidatePortfolioData()` Promise.all (line 226-229):
```typescript
await Promise.all([
  this.queryClient.invalidateQueries({ queryKey: portfolioSummaryKey(portfolioId) }),
  this.queryClient.invalidateQueries({ queryKey: performanceKey(portfolioId) }),
  this.queryClient.invalidateQueries({ queryKey: positionsHoldingsKey() }),
  this.queryClient.invalidateQueries({ queryKey: portfolioAlertsKey() }),
  this.queryClient.invalidateQueries({ queryKey: marketIntelligenceKey() })  // ADD
]);
```

---

## Step 6: Edge cases

| Case | Behavior |
|------|----------|
| Empty portfolio | Falls back to `get_news(mode="general")` — general market news |
| FMP news fails | Earnings events still returned (and vice versa) |
| Both FMP calls fail | Empty list → section stays hidden |
| Loading state | Hook defaults to `[]`, section hidden until data arrives |
| No upcoming earnings | Only news events shown |

---

## Files Modified (Summary)

| File | Change |
|------|--------|
| `mcp_tools/news_events.py` | Add `build_market_events()` + `_load_portfolio_weights()` + `_infer_news_impact()` (shared builder) |
| `routes/positions.py` | Add thin `/market-intelligence` endpoint calling `build_market_events()` |
| `frontend/packages/chassis/src/queryKeys.ts` | Add `marketIntelligenceKey` + union type |
| `frontend/packages/chassis/src/services/APIService.ts` | Add `getMarketIntelligence()` method + response type |
| `frontend/packages/chassis/src/services/CacheCoordinator.ts` | Add `marketIntelligenceKey` to invalidation list |
| `frontend/packages/connectors/src/features/positions/hooks/useMarketIntelligence.ts` | **New file** — `useMarketIntelligence()` hook |
| `frontend/packages/connectors/src/features/positions/index.ts` | Export `useMarketIntelligence` |
| `frontend/packages/connectors/src/index.ts` | Export `useMarketIntelligence` |
| `frontend/packages/ui/src/.../PortfolioOverviewContainer.tsx` | Import hook, pass `marketEvents` prop |
| `frontend/packages/ui/src/.../PortfolioOverview.tsx` | Accept prop, remove internal stub, use external data |

## Verification

1. **Backend**: `curl http://localhost:8000/api/positions/market-intelligence` (with auth cookie) — returns `{ success: true, events: [...], total: N }` with real news and earnings
2. **Frontend build**: `cd frontend && pnpm typecheck && pnpm lint && pnpm build` — 0 errors
3. **Visual**: Load Overview tab in browser — Market Intelligence card appears with news articles (impact-colored badges: green/red/gray) and upcoming earnings events. Action Items counter badge visible.
4. **Edge case**: Empty portfolio — shows general market news instead of portfolio-specific
5. **Edge case**: FMP unavailable — section stays hidden (empty events)

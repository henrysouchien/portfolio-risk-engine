# Wave 3d: AI Recommendations — Wire Real Factor Recommendations

**Status**: COMPLETE (commit `aae47747`)
**Parent doc**: `completed/FRONTEND_PHASE2_WORKING_DOC.md` → Wave 3d (AI Recommendations)
**Date**: 2026-03-03

## Context

The Portfolio Overview (`PortfolioOverview.tsx`) has an AI Recommendations section (lines 1645-1736) that renders nothing — `generateAIRecommendations` (line 576) returns `[]`, and the section is gated behind `showAIInsights && (viewMode === "professional" || viewMode === "institutional")` which means even if data existed, the default `viewMode="detailed"` hides it.

The backend already has the data: `POST /api/factor-intelligence/portfolio-recommendations` calls `recommend_portfolio_offsets()` → `PortfolioOffsetRecommendationResult` which contains `drivers` (risk drivers) and `recommendations` (hedge suggestions with correlation, Sharpe, suggested weight). The MCP tool `get_factor_recommendations(mode="portfolio")` also uses this.

**Goal:** Wire real factor-based portfolio recommendations into the AI Recommendations section.

## Design Decisions

1. **Shared builder pattern**: Following Wave 3a's pattern, add `build_ai_recommendations()` in `mcp_tools/factor_intelligence.py` that loads positions → computes weights → calls `recommend_portfolio_offsets()` → transforms to `AIRecommendation[]` shape. Both the new API endpoint and MCP tools can call this.
2. **New GET endpoint**: Add `GET /api/positions/ai-recommendations` in `routes/positions.py` — thin wrapper that calls `build_ai_recommendations()`. This is cleaner than requiring the frontend to POST weights, since the backend already knows the portfolio.
3. **View mode gate removal**: Remove the `(viewMode === "professional" || viewMode === "institutional")` condition so the section shows for all view modes when data exists.
4. **Data mapping**: `PortfolioOffsetRecommendationResult` → `AIRecommendation` interface:
   - Each risk **driver** → `type: "risk_reduction"` recommendation
   - Each hedge **recommendation** → `type: "hedge"` recommendation
   - `confidence` = correlation × 100 (hedges) or portfolio weight-based (drivers)
   - `actionItems` derived from hedge/driver details
   - `priority` based on driver portfolio % or hedge correlation+Sharpe

---

## Step 1: Shared Builder — `build_ai_recommendations()` in `mcp_tools/factor_intelligence.py`

**File**: `mcp_tools/factor_intelligence.py` (add after `_build_factor_recs_agent_response()`, ~line 229)

Reuses existing `FactorIntelligenceService.recommend_portfolio_offsets()`. Loads positions internally (same pattern as `build_market_events()` in `mcp_tools/news_events.py`).

```python
def build_ai_recommendations(
    user_email: Optional[str] = None,
    max_recommendations: int = 6,
    use_cache: bool = True,
) -> list[dict]:
    """Build AIRecommendation list from portfolio factor analysis.

    Shared builder used by both API endpoint and MCP tools.
    Loads portfolio weights internally, runs factor recommendation engine,
    transforms to frontend AIRecommendation shape.
    """
    from services.position_service import PositionService
    from settings import get_default_user

    user = user_email or get_default_user()
    if not user:
        return []

    try:
        position_service = PositionService(user)
        position_result = position_service.get_all_positions(
            use_cache=use_cache, force_refresh=False, consolidate=True
        )
    except (ValueError, ConnectionError, OSError):
        return []

    positions = position_result.data.positions
    total_value = sum(abs(float(p.get("value") or 0)) for p in positions) or 1.0
    weights: dict[str, float] = {}
    for pos in positions:
        ticker = (pos.get("ticker") or "").strip().upper()
        if not ticker or ticker.startswith("CUR:"):
            continue
        w = abs(float(pos.get("value") or 0)) / total_value
        weights[ticker] = weights.get(ticker, 0) + w

    if not weights:
        return []

    # Run factor recommendation engine
    try:
        service = FactorIntelligenceService(cache_results=use_cache)
        result = service.recommend_portfolio_offsets(weights=weights)
    except Exception as exc:
        logger.warning("AI recommendations factor analysis failed: %s", exc)
        return []

    recommendations: list[dict] = []
    rec_id = 0

    # --- Risk driver recommendations ---
    # NOTE: percent_of_portfolio is a fraction (0.05 = 5%), not 0-100
    for driver in (result.drivers or []):
        label = driver.get("label") or "Unknown"
        pct = float(driver.get("percent_of_portfolio") or 0)  # fraction, e.g. 0.23 = 23%
        if pct < 0.05:  # Skip drivers below 5%
            continue
        pct_display = pct * 100  # Convert to display percentage
        priority = "critical" if pct > 0.25 else "high" if pct > 0.15 else "medium"
        rec_id += 1
        recommendations.append({
            "id": f"driver_{rec_id}",
            "type": "risk_reduction",
            "priority": priority,
            "title": f"High {label} Concentration",
            "description": f"Portfolio has {pct_display:.1f}% exposure to {label}. Consider diversifying to reduce concentration risk.",
            "expectedImpact": f"Reduce {label} exposure from {pct_display:.1f}%",
            "confidence": min(95, int(pct_display * 2 + 30)),
            "timeframe": "1-2 weeks",
            "actionItems": [
                f"Review {label} positions for trim candidates",
                f"Target reducing {label} weight to below {max(10, pct_display - 10):.0f}%",
                "Consider alternative sector/factor exposure",
            ],
            "riskLevel": "low",
        })

    # --- Hedge recommendations ---
    # NOTE: label is the primary field; ticker not guaranteed on recommendation entries
    for rec in (result.recommendations or []):
        label = rec.get("label") or "Unknown"
        corr = abs(float(rec.get("correlation") or 0))
        sharpe = float(rec.get("sharpe_ratio") or 0)
        category = rec.get("category", "unknown")
        suggested_wt = float(rec.get("suggested_weight") or 0)
        if corr < 0.2:
            continue
        priority = "high" if corr > 0.6 and sharpe > 0.5 else "medium" if corr > 0.4 else "low"
        rec_id += 1
        recommendations.append({
            "id": f"hedge_{rec_id}",
            "type": "hedge",
            "priority": priority,
            "title": f"Hedge with {label}",
            "description": f"{label} ({category}) shows {corr:.0%} negative correlation with risk drivers. Sharpe ratio: {sharpe:.2f}.",
            "expectedImpact": f"Reduce portfolio risk via {corr:.0%} offset correlation",
            "confidence": min(95, int(corr * 100)),
            "timeframe": "Ongoing",
            "actionItems": [
                f"Add {suggested_wt:.1%} allocation to {label}" if suggested_wt > 0 else f"Consider adding {label} position",
                f"Monitor correlation stability ({category} factor)",
            ],
            "riskLevel": "low" if corr > 0.5 else "medium",
        })

    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    recommendations.sort(key=lambda r: (priority_order.get(r["priority"], 9), -r["confidence"]))
    return recommendations[:max_recommendations]
```

---

## Step 2: API Endpoint — `routes/positions.py`

**File**: `routes/positions.py` — add after `/market-intelligence` endpoint (after line 254):

```python
@positions_router.get("/ai-recommendations")
async def get_ai_recommendations(request: Request):
    """Return AI-powered portfolio recommendations based on factor analysis."""
    session_id = request.cookies.get("session_id")
    user = auth_service.get_user_by_session(session_id)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        from mcp_tools.factor_intelligence import build_ai_recommendations
        recommendations = build_ai_recommendations(user_email=user["email"])
        return {"success": True, "recommendations": recommendations, "total": len(recommendations)}

    except Exception as e:
        portfolio_logger.error(f"AI recommendations failed: {e}")
        log_error("positions_api", "ai_recommendations", e)
        raise HTTPException(status_code=500, detail="Failed to generate AI recommendations")
```

---

## Step 3: Frontend Chassis — API method + query key

### 3a. Query key — `frontend/packages/chassis/src/queryKeys.ts`
```typescript
export const aiRecommendationsKey = () => ['aiRecommendations'] as const;
```
Add to `AppQueryKey` union.

### 3b. APIService — `frontend/packages/chassis/src/services/APIService.ts`
```typescript
interface AIRecommendationsResponse {
  success: boolean;
  recommendations: Array<Record<string, unknown>>;
  total: number;
}

async getAIRecommendations(): Promise<AIRecommendationsResponse> {
  return this.request<AIRecommendationsResponse>('/api/positions/ai-recommendations');
}
```

---

## Step 4: Frontend Connectors — `useAIRecommendations()` hook

**New file**: `frontend/packages/connectors/src/features/positions/hooks/useAIRecommendations.ts`

Same pattern as `useMarketIntelligence`. Transform function maps API response to `AIRecommendation` interface. `staleTime: 10 * 60 * 1000` (10 min — factor analysis is expensive).

```typescript
import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';
import { frontendLogger, aiRecommendationsKey } from '@risk/chassis';
import { useSessionServices } from '../../../providers/SessionServicesProvider';

export interface AIRecommendation {
  id: string;
  type: 'rebalance' | 'hedge' | 'opportunity' | 'risk_reduction' | 'optimization';
  priority: 'critical' | 'high' | 'medium' | 'low';
  title: string;
  description: string;
  expectedImpact: string;
  confidence: number;
  timeframe: string;
  actionItems: string[];
  riskLevel: 'low' | 'medium' | 'high';
  estimatedReturn?: number;
  requiredCapital?: number;
}

function transformRecommendations(
  payload: { recommendations: Array<Record<string, unknown>> }
): AIRecommendation[] {
  return (payload.recommendations || []).map((r) => ({
    id: String(r.id ?? ''),
    type: (r.type as AIRecommendation['type']) ?? 'optimization',
    priority: (r.priority as AIRecommendation['priority']) ?? 'medium',
    title: String(r.title ?? ''),
    description: String(r.description ?? ''),
    expectedImpact: String(r.expectedImpact ?? ''),
    confidence: Number(r.confidence ?? 0),
    timeframe: String(r.timeframe ?? ''),
    actionItems: Array.isArray(r.actionItems) ? r.actionItems.map(String) : [],
    riskLevel: (r.riskLevel as AIRecommendation['riskLevel']) ?? 'medium',
    estimatedReturn: r.estimatedReturn != null ? Number(r.estimatedReturn) : undefined,
    requiredCapital: r.requiredCapital != null ? Number(r.requiredCapital) : undefined,
  }));
}

export const useAIRecommendations = () => {
  const { api } = useSessionServices();

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: aiRecommendationsKey(),
    queryFn: async (): Promise<AIRecommendation[]> => {
      frontendLogger.adapter.transformStart('useAIRecommendations', {
        source: '/api/positions/ai-recommendations',
      });
      const payload = await api.getAIRecommendations();
      const recs = transformRecommendations(payload);
      frontendLogger.adapter.transformSuccess('useAIRecommendations', {
        recommendationCount: recs.length,
      });
      return recs;
    },
    enabled: !!api,
    staleTime: 10 * 60 * 1000,  // 10 minutes — factor analysis is expensive
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
export { useAIRecommendations } from './hooks/useAIRecommendations';
```

**File**: `frontend/packages/connectors/src/index.ts` — add `useAIRecommendations` to the positions export line.

---

## Step 5: Frontend UI — Wire through container → component

### 5a. PortfolioOverviewContainer

**File**: `frontend/packages/ui/src/components/dashboard/views/modern/PortfolioOverviewContainer.tsx`

1. Add `useAIRecommendations` to import (line 40).
2. Call `const { data: aiRecommendations } = useAIRecommendations();`
3. Pass `aiRecommendations={aiRecommendations}` prop.

### 5b. PortfolioOverview component

**File**: `frontend/packages/ui/src/components/portfolio/PortfolioOverview.tsx`

1. **Add** `aiRecommendations?: AIRecommendation[]` to `PortfolioOverviewProps` (after `marketEvents`).
2. **Destructure** as `aiRecommendations: externalAIRecommendations = []`.
3. **Remove** `const [aiRecommendations, setAIRecommendations] = useState<AIRecommendation[]>([])` (line 372).
4. **Remove** `const generateAIRecommendations = useCallback((): AIRecommendation[] => [], [])` (line 576).
5. **Remove** `setAIRecommendations(generateAIRecommendations())` calls (lines 585, 655).
6. **Remove** `generateAIRecommendations` from dependency arrays (lines 600, 673) — these useEffect/useCallback deps reference the deleted function and will cause compile errors if left.
7. **Remove view mode gate** (line 1649): Change to `{externalAIRecommendations.length > 0 && showAIInsights && (` — removing `(viewMode === "professional" || viewMode === "institutional")`.
8. **Replace** all `aiRecommendations` rendering refs with `externalAIRecommendations` (lines 1649-1736).

---

## Step 6: CacheCoordinator — `frontend/packages/chassis/src/services/CacheCoordinator.ts`

Add `aiRecommendationsKey` to import and `invalidatePortfolioData()` Promise.all.

---

## Files Modified (Summary)

| File | Change |
|------|--------|
| `mcp_tools/factor_intelligence.py` | Add `build_ai_recommendations()` shared builder |
| `routes/positions.py` | Add `GET /ai-recommendations` endpoint |
| `frontend/packages/chassis/src/queryKeys.ts` | Add `aiRecommendationsKey` + union |
| `frontend/packages/chassis/src/services/APIService.ts` | Add `getAIRecommendations()` + response type |
| `frontend/packages/chassis/src/services/CacheCoordinator.ts` | Add to invalidation |
| `frontend/packages/connectors/src/features/positions/hooks/useAIRecommendations.ts` | **New** — hook |
| `frontend/packages/connectors/src/features/positions/index.ts` | Export |
| `frontend/packages/connectors/src/index.ts` | Export |
| `frontend/packages/ui/src/.../PortfolioOverviewContainer.tsx` | Import hook, pass prop |
| `frontend/packages/ui/src/.../PortfolioOverview.tsx` | Accept prop, remove state/stub/gate, use external data |

## Edge Cases

| Case | Behavior |
|------|----------|
| Empty portfolio | No weights → empty list → section hidden |
| Factor analysis fails | Returns `[]` → section hidden |
| No significant drivers (< 5%) | Only hedge recommendations shown |
| Loading state | Hook defaults to `[]`, section hidden until data |

## Verification

1. **Backend**: `curl http://localhost:8000/api/positions/ai-recommendations` — returns `{ success: true, recommendations: [...], total: N }`
2. **Frontend build**: `cd frontend && pnpm typecheck && pnpm lint && pnpm build` — 0 errors
3. **Visual**: AI Recommendations card with priority badges, risk level dots, action items, confidence %
4. **Edge case**: Factor service down → section hidden

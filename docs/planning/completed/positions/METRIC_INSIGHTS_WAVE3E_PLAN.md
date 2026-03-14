# Wave 3e: Metric Card AI Insights — Wire Real Backend Flags

**Status**: COMPLETE (commit `bc107e04`)
**Parent doc**: `completed/FRONTEND_PHASE2_WORKING_DOC.md` → Wave 3e (AI Insights)
**Date**: 2026-03-03

## Context

The Portfolio Overview has 6 metric cards (Total Value, Daily P&L, Risk Score, Sharpe Ratio, Alpha Generation, ESG Score). Each card has `aiInsight`, `aiConfidence`, and `marketContext` fields — all currently empty strings/0. The AI insight panel (lines 1430-1510 in `PortfolioOverview.tsx`) renders on hover when `showAIInsights && metric.aiInsight` is truthy, but since `aiInsight` is always `""`, nothing ever shows.

The backend already generates rich interpretive text via flag generators:
- `core/risk_score_flags.py` → `generate_risk_score_flags(snapshot)` — e.g., "Risk score 45/100 indicates high portfolio risk"
- `core/performance_flags.py` → `generate_performance_flags(snapshot)` — e.g., "Portfolio is down 12.5% total", "Sharpe ratio is 0.18 (poor risk-adjusted returns)"
- `core/position_flags.py` → `generate_position_flags(positions, total_value, cache_info)` — e.g., "AAPL is 28.5% of exposure", "Portfolio is 2.15x levered"

These flags are only used in MCP agent-format responses. The REST API endpoints don't return them.

**Goal:** Create a new `build_metric_insights()` shared builder that runs the flag generators and maps their messages to metric card IDs, expose via `GET /api/positions/metric-insights`, and wire into the frontend to populate the existing empty AI insight fields.

## Flag → Metric Card Mapping

| Metric Card | Flag Source | Flag Types |
|-------------|-----------|------------|
| `totalValue` | position_flags | `single_position_concentration`, `leveraged_concentration`, `top5_concentration`, `cash_drag`, `low_position_count`, `large_fund_position`, `sector_concentration`, `low_sector_diversification`, `large_unrealized_loss`, `low_cost_basis_coverage` |
| `dayChange` | position_flags | `high_leverage`, `leveraged`, `margin_usage`, `stale_data`, `futures_high_notional`, `futures_notional`, `expired_options`, `near_expiry_options`, `options_concentration`, `provider_error` |
| `riskScore` | risk_score_flags | `high_risk`, `excellent_risk`, `non_compliant`, `compliant`, `weak_*` |
| `ytdReturn` | performance_flags | `negative_total_return`, `outperforming`, `benchmark_underperformance`, `high_confidence`, `realized_reliability_warning`, `low_data_coverage`, `data_quality_issues`, `provider_data_missing`, `provider_fetch_error` |
| `sharpeRatio` | performance_flags | `low_sharpe` |
| `maxDrawdown` | performance_flags | `deep_drawdown` |
| `volatilityAnnual` | performance_flags | `high_volatility` |

---

## Step 1: Shared Builder — `build_metric_insights()` in `mcp_tools/metric_insights.py`

**New file**: `mcp_tools/metric_insights.py`

The builder runs 3 flag generators and maps outputs to metric card IDs. For position flags, it only needs positions + total_value (lightweight). For risk score and performance flags, it needs their respective snapshots — which requires running `PortfolioService.analyze_risk_score()` and `PortfolioService.analyze_performance()`. Both use internal caching so this is fast when the frontend has already triggered the underlying API calls.

```python
"""Shared builder for metric card AI insights."""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Flag type → metric card ID mapping
_POSITION_FLAG_MAP = {
    # totalValue card — portfolio composition insights
    "single_position_concentration": "totalValue",
    "leveraged_concentration": "totalValue",
    "top5_concentration": "totalValue",
    "cash_drag": "totalValue",
    "low_position_count": "totalValue",
    "large_fund_position": "totalValue",
    "sector_concentration": "totalValue",
    "low_sector_diversification": "totalValue",
    "large_unrealized_loss": "totalValue",
    "low_cost_basis_coverage": "totalValue",
    # dayChange card — leverage, data freshness, options
    "high_leverage": "dayChange",
    "leveraged": "dayChange",
    "margin_usage": "dayChange",
    "stale_data": "dayChange",
    "futures_high_notional": "dayChange",
    "futures_notional": "dayChange",
    "expired_options": "dayChange",
    "near_expiry_options": "dayChange",
    "options_concentration": "dayChange",
    "provider_error": "dayChange",
}

_PERF_FLAG_MAP = {
    "negative_total_return": "ytdReturn",
    "outperforming": "ytdReturn",
    "benchmark_underperformance": "ytdReturn",
    "high_confidence": "ytdReturn",
    "realized_reliability_warning": "ytdReturn",
    "low_data_coverage": "ytdReturn",
    "data_quality_issues": "ytdReturn",
    "provider_data_missing": "ytdReturn",
    "provider_fetch_error": "ytdReturn",
    "low_sharpe": "sharpeRatio",
    "deep_drawdown": "maxDrawdown",
    "high_volatility": "volatilityAnnual",
}

# risk_score_flags use "flag" key, all map to riskScore
_RISK_SCORE_CARD = "riskScore"

_SEVERITY_CONFIDENCE = {"error": 95, "warning": 80, "info": 60, "success": 90}
_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2, "success": 3}


def build_metric_insights(
    user_email: Optional[str] = None,
    user_id: Optional[int] = None,
    use_cache: bool = True,
) -> dict[str, dict]:
    """Build AI insight per metric card from backend flag generators.

    Args:
        user_email: User email. Falls back to get_default_user().
        user_id: Database user ID (avoids DB lookup when called from API route).
        use_cache: Use cached data when available.

    Returns dict keyed by metric card ID:
    {
        "riskScore": {"aiInsight": "...", "aiConfidence": 85, "marketContext": "..."},
        "ytdReturn": {...},
        ...
    }
    """
    from settings import get_default_user

    user = user_email or get_default_user()
    if not user:
        return {}

    # Resolve user_id if not provided (DB lookup from email)
    if user_id is None:
        try:
            from database import get_db_session
            with get_db_session() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM users WHERE email = %s", (user,))
                row = cursor.fetchone()
                if row:
                    user_id = row["id"]
        except Exception:
            pass
    if user_id is None:
        return {}

    insights: dict[str, list[dict]] = {}  # card_id -> list of flags
    portfolio_data = None  # reuse across steps

    # --- 1. Position flags (lightweight — just needs positions) ---
    try:
        from services.position_service import PositionService
        from core.position_flags import generate_position_flags

        position_service = PositionService(user)
        position_result = position_service.get_all_positions(
            use_cache=use_cache, force_refresh=False, consolidate=True
        )
        positions = position_result.data.positions
        total_value = sum(abs(float(p.get("value") or 0)) for p in positions)

        pos_flags = generate_position_flags(
            positions=positions, total_value=total_value, cache_info={}
        )
        for flag in pos_flags:
            flag_type = flag.get("type", "")
            card_id = _POSITION_FLAG_MAP.get(flag_type)
            if card_id:
                insights.setdefault(card_id, []).append(flag)
    except Exception as exc:
        logger.warning("Metric insights: position flags failed: %s", exc)

    # --- 2. Risk score + performance flags (need portfolio analysis) ---
    # Build PortfolioData from DB (same pattern as /api/risk-score endpoint in app.py)
    portfolio_data = None
    try:
        from services.portfolio_service import PortfolioService
        from inputs.portfolio_manager import PortfolioManager
        from services.factor_proxy_service import ensure_factor_proxies

        pm = PortfolioManager(use_database=True, user_id=user_id)
        portfolio_data = pm.load_portfolio_data("CURRENT_PORTFOLIO")
        tickers = set(
            t for t in portfolio_data.portfolio_input.keys()
            if not t.startswith("CUR:")
        )
        portfolio_data.stock_factor_proxies = ensure_factor_proxies(
            user_id, "CURRENT_PORTFOLIO", tickers, allow_gpt=True
        ) or {}
    except Exception as exc:
        logger.warning("Metric insights: portfolio load failed: %s", exc)

    # 2a. Risk score flags
    try:
        if portfolio_data is not None:
            from inputs.risk_limits_manager import RiskLimitsManager
            from core.risk_score_flags import generate_risk_score_flags

            risk_limits_data = RiskLimitsManager(
                use_database=True, user_id=user_id
            ).load_risk_limits("CURRENT_PORTFOLIO")

            if risk_limits_data and not risk_limits_data.is_empty():
                risk_result = PortfolioService(cache_results=use_cache).analyze_risk_score(
                    portfolio_data, risk_limits_data
                )
                risk_snapshot = risk_result.get_agent_snapshot()
                risk_flags = generate_risk_score_flags(risk_snapshot)
                # NOTE: risk_score_flags use "flag" key (not "type")
                for flag in risk_flags:
                    insights.setdefault(_RISK_SCORE_CARD, []).append(flag)

                # Store verdict as market context for riskScore card
                verdict = risk_snapshot.get("verdict", "")
                if verdict:
                    insights.setdefault("_riskScore_verdict", []).append({"message": verdict})
    except Exception as exc:
        logger.warning("Metric insights: risk score flags failed: %s", exc)

    # 2b. Performance flags
    # Uses PortfolioService.analyze_performance() which returns PerformanceResult
    # (NOT compute_performance_metrics() which takes raw returns, not PortfolioData)
    try:
        if portfolio_data is not None:
            from core.performance_flags import generate_performance_flags

            perf_result = PortfolioService(cache_results=use_cache).analyze_performance(
                portfolio_data, benchmark_ticker="SPY"
            )
            perf_snapshot = perf_result.get_agent_snapshot()
            perf_flags = generate_performance_flags(perf_snapshot)
            for flag in perf_flags:
                flag_type = flag.get("type", "")
                card_id = _PERF_FLAG_MAP.get(flag_type)
                if card_id:
                    insights.setdefault(card_id, []).append(flag)
    except Exception as exc:
        logger.warning("Metric insights: performance flags failed: %s", exc)

    # --- 4. Transform to frontend shape ---
    result: dict[str, dict] = {}
    verdict_msg = ""
    verdict_list = insights.pop("_riskScore_verdict", [])
    if verdict_list:
        verdict_msg = verdict_list[0].get("message", "")

    for card_id, flags in insights.items():
        if not flags:
            continue
        # Sort by severity (error first)
        # Note: risk_score_flags use "flag" key, perf/position use "type" key — but
        # we only need "severity" and "message" here, which all generators provide.
        sorted_flags = sorted(
            flags,
            key=lambda f: _SEVERITY_ORDER.get(f.get("severity", "info"), 9)
        )
        top = sorted_flags[0]
        severity = top.get("severity", "info")

        result[card_id] = {
            "aiInsight": top["message"],
            "aiConfidence": _SEVERITY_CONFIDENCE.get(severity, 60),
            "marketContext": sorted_flags[1]["message"] if len(sorted_flags) > 1 else (
                verdict_msg if card_id == _RISK_SCORE_CARD else ""
            ),
        }

    return result
```

**Key design decisions:**
- Position flags are lightweight (just positions). Risk score and performance flags need heavier computation but benefit from `PortfolioService` cache.
- If risk score or performance computation fails (no risk limits, etc.), those metrics simply get no insight — section stays hidden.
- `portfolio_data` loaded via `PortfolioManager.load_portfolio_data()` (same pattern as `/api/risk-score` in `app.py`) is reused for both risk score and performance computation. Does NOT use private `_load_portfolio_for_analysis()` from `mcp_tools/risk.py`.
- Performance uses `PortfolioService.analyze_performance()` which returns `PerformanceResult` with `get_agent_snapshot()`. Does NOT use `compute_performance_metrics()` directly (that takes raw returns, not PortfolioData).
- Risk score flags use `"flag"` key; position/performance flags use `"type"` key. The transform step only reads `"severity"` and `"message"` which all generators provide.
- Each metric gets the highest-severity flag as `aiInsight`, second flag as `marketContext`.

---

## Step 2: API Endpoint — `routes/positions.py`

Add after `/ai-recommendations` endpoint (~line 286):

```python
@positions_router.get("/metric-insights")
async def get_metric_insights(request: Request):
    """Return AI insights for portfolio metric cards based on interpretive flags."""
    session_id = request.cookies.get("session_id")
    user = auth_service.get_user_by_session(session_id)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        from mcp_tools.metric_insights import build_metric_insights
        insights = build_metric_insights(
            user_email=user["email"], user_id=user.get("user_id")
        )
        return {"success": True, "insights": insights, "total": len(insights)}

    except Exception as e:
        portfolio_logger.error(f"Metric insights failed: {e}")
        log_error("positions_api", "metric_insights", e)
        raise HTTPException(status_code=500, detail="Failed to generate metric insights")
```

---

## Step 3: Frontend Chassis — Query key + API method

### 3a. Query key — `frontend/packages/chassis/src/queryKeys.ts`

```typescript
export const metricInsightsKey = () => ['metricInsights'] as const;
```

Add to `AppQueryKey` union.

### 3b. APIService — `frontend/packages/chassis/src/services/APIService.ts`

```typescript
interface MetricInsightsResponse {
  success: boolean;
  insights: Record<string, { aiInsight: string; aiConfidence: number; marketContext: string }>;
  total: number;
}

async getMetricInsights(): Promise<MetricInsightsResponse> {
  return this.request<MetricInsightsResponse>('/api/positions/metric-insights');
}
```

---

## Step 4: Frontend Hook — `useMetricInsights.ts`

**New file**: `frontend/packages/connectors/src/features/positions/hooks/useMetricInsights.ts`

Same pattern as `useMarketIntelligence.ts` / `useSmartAlerts.ts`.

```typescript
import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';
import { frontendLogger, metricInsightsKey } from '@risk/chassis';
import { useSessionServices } from '../../../providers/SessionServicesProvider';

export interface MetricInsight {
  aiInsight: string;
  aiConfidence: number;
  marketContext: string;
}

export type MetricInsightsMap = Record<string, MetricInsight>;

function transformInsights(
  payload: { insights: Record<string, Record<string, unknown>> }
): MetricInsightsMap {
  const result: MetricInsightsMap = {};
  for (const [cardId, raw] of Object.entries(payload.insights || {})) {
    result[cardId] = {
      aiInsight: String(raw.aiInsight ?? ''),
      aiConfidence: Number(raw.aiConfidence ?? 0),
      marketContext: String(raw.marketContext ?? ''),
    };
  }
  return result;
}

export const useMetricInsights = () => {
  const { api } = useSessionServices();

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: metricInsightsKey(),
    queryFn: async (): Promise<MetricInsightsMap> => {
      frontendLogger.adapter.transformStart('useMetricInsights', {
        source: '/api/positions/metric-insights',
      });
      const payload = await api.getMetricInsights();
      const insights = transformInsights(payload);
      frontendLogger.adapter.transformSuccess('useMetricInsights', {
        metricCount: Object.keys(insights).length,
      });
      return insights;
    },
    enabled: !!api,
    staleTime: 5 * 60 * 1000,  // 5 min — reuses cached backend data
    retry: (failureCount) => failureCount < 2,
  });

  return useMemo(
    () => ({
      data: data ?? {},
      loading: isLoading,
      error: error instanceof Error ? error.message : null,
      refetch,
    }),
    [data, isLoading, error, refetch]
  );
};
```

**Export chain**: Add to `features/positions/index.ts` and `connectors/src/index.ts`.

---

## Step 5: CacheCoordinator

**File**: `frontend/packages/chassis/src/services/CacheCoordinator.ts`

Add `metricInsightsKey` to import and to `invalidatePortfolioData()` Promise.all array.

---

## Step 6: Frontend UI Wiring

### 6a. PortfolioOverviewContainer

**File**: `frontend/packages/ui/src/components/dashboard/views/modern/PortfolioOverviewContainer.tsx`

- Import `useMetricInsights` from `@risk/connectors`
- Call `const { data: metricInsights } = useMetricInsights();`
- Pass `metricInsights={metricInsights}` prop to PortfolioOverview

### 6b. PortfolioOverview component

**File**: `frontend/packages/ui/src/components/portfolio/PortfolioOverview.tsx`

1. Add `metricInsights?: Record<string, { aiInsight: string; aiConfidence: number; marketContext: string }>` to `PortfolioOverviewProps` (around line 296)
2. Destructure as `metricInsights = {}` in component signature
3. In the `metrics` useMemo (lines 416-567), replace the hardcoded empty values with lookups:

   For each metric card, replace:
   ```typescript
   aiInsight: "",
   aiConfidence: 0,
   marketContext: "",
   ```
   With:
   ```typescript
   aiInsight: metricInsights["totalValue"]?.aiInsight ?? "",
   aiConfidence: metricInsights["totalValue"]?.aiConfidence ?? 0,
   marketContext: metricInsights["totalValue"]?.marketContext ?? "",
   ```

   Using the appropriate key for each card:
   - Card 1 (Total Portfolio Value) → `metricInsights["totalValue"]`
   - Card 2 (Daily P&L) → `metricInsights["dayChange"]`
   - Card 3 (Risk Score) → `metricInsights["riskScore"]`
   - Card 4 (Sharpe Ratio) → `metricInsights["sharpeRatio"]`
   - Card 5 (Alpha Generation) → no mapping (placeholder card)
   - Card 6 (ESG Score) → no mapping (placeholder card)

4. Add `metricInsights` to the useMemo dependency array.

---

## Files Modified (Summary)

| File | Change |
|------|--------|
| `mcp_tools/metric_insights.py` | **New** — `build_metric_insights()` shared builder |
| `routes/positions.py` | Add `GET /metric-insights` endpoint |
| `frontend/packages/chassis/src/queryKeys.ts` | Add `metricInsightsKey` + union |
| `frontend/packages/chassis/src/services/APIService.ts` | Add `getMetricInsights()` + response type |
| `frontend/packages/chassis/src/services/CacheCoordinator.ts` | Add to invalidation |
| `frontend/packages/connectors/src/features/positions/hooks/useMetricInsights.ts` | **New** — hook |
| `frontend/packages/connectors/src/features/positions/index.ts` | Export |
| `frontend/packages/connectors/src/index.ts` | Export |
| `frontend/packages/ui/src/.../PortfolioOverviewContainer.tsx` | Import hook, pass prop |
| `frontend/packages/ui/src/.../PortfolioOverview.tsx` | Accept prop, wire into metrics useMemo |

## Edge Cases

| Case | Behavior |
|------|----------|
| Empty portfolio | No flags → empty insights → all AI panels hidden |
| Risk limits not configured | Risk score flags skipped, only position/performance flags shown |
| Performance computation fails | Performance metrics get no insights, position/risk still work |
| No flags trigger for a metric | That metric's AI panel stays hidden (aiInsight remains "") |
| Alpha/ESG placeholder cards | No mapping → always hidden (placeholder cards) |

## Verification

1. **Backend**: `curl http://localhost:8000/api/positions/metric-insights` — returns `{ success: true, insights: { "riskScore": { "aiInsight": "...", ... }, "ytdReturn": { ... } }, total: N }`
2. **Frontend build**: `cd frontend && pnpm typecheck && pnpm lint && pnpm build` — 0 errors
3. **Visual**: Hover over metric cards → blue AI Analysis panel appears with insight text, confidence badge, market context
4. **Edge case**: No risk limits → riskScore card has no insight but other cards still work

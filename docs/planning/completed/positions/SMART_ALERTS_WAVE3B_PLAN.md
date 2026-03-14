# Wave 3b: Smart Alerts — Wire Real Portfolio Flags

**Status**: COMPLETE — Commit `1dea17ba`
**Parent doc**: `completed/FRONTEND_PHASE2_WORKING_DOC.md` → Item 2 (Smart Alerts)
**Date**: 2026-03-03

## Context

The Portfolio Overview (`PortfolioOverview.tsx`) has a Smart Alerts section that currently renders nothing — `generateSmartAlerts()` returns `[]`. The backend already computes 20+ position-level flags (concentration, leverage, expiring options, stale data, unrealized losses, etc.) via `generate_position_flags()` in `core/position_flags.py`. These flags are already used in `/api/positions/holdings` for per-position alert counts, but there's no portfolio-level alerts endpoint.

**Goal:** Surface real portfolio flags as Smart Alerts in the Overview tab.

## Scope

| Item | Layer | Effort |
|------|-------|--------|
| New `/api/positions/alerts` endpoint | Backend route | Low |
| `getPortfolioAlerts()` API method | Frontend chassis | Trivial |
| `portfolioAlertsKey` query key | Frontend chassis | Trivial |
| `useSmartAlerts()` hook | Frontend connectors | Low |
| Wire alerts through container → component | Frontend UI | Low |

---

## Step 1: Backend — New `/api/positions/alerts` endpoint

**File**: `routes/positions.py`

Add a new endpoint that generates position flags and returns them in the frontend `SmartAlert` shape. This follows the same pattern as `/api/positions/holdings` (lines 118-133) which already calls `generate_position_flags()`.

```python
@positions_router.get("/alerts")
async def get_portfolio_alerts(request: Request):
    """Return portfolio-level alerts derived from position flags."""
    # Auth (same pattern as holdings)
    session_id = request.cookies.get("session_id")
    user = auth_service.get_user_by_session(session_id)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        service = PositionService(user_email=user["email"], user_id=user["user_id"])
        result = service.get_all_positions(consolidate=True)

        from core.position_flags import generate_position_flags
        flags = generate_position_flags(
            positions=result.data.positions,
            total_value=result.total_value,
            cache_info={},
        )

        # Map backend flags → frontend SmartAlert shape
        alerts = []
        for flag in flags:
            severity = flag.get("severity", "info")
            alerts.append({
                "id": f"{flag['type']}_{flag.get('ticker', 'portfolio')}",
                "type": _map_alert_type(flag["type"]),
                "severity": "critical" if severity == "error" else severity,
                "message": flag["message"],
                "flag_type": flag["type"],
                "ticker": flag.get("ticker"),
                "actionable": severity in ("error", "warning"),
                "dismissible": True,
            })

        return {"success": True, "alerts": alerts, "total": len(alerts)}

    except ValueError as ve:
        if str(ve) == "consolidation input is empty":
            return {"success": True, "alerts": [], "total": 0}
        raise HTTPException(status_code=500, detail="Alert generation error")
    except Exception as e:
        portfolio_logger.error(f"Portfolio alerts failed: {e}")
        log_error("positions_api", "alerts", e)
        raise HTTPException(status_code=500, detail="Failed to generate alerts")
```

**Helper** (same file, module-level):

```python
_ALERT_TYPE_MAP = {
    "single_position_concentration": "risk",
    "leveraged_concentration": "risk",
    "top5_concentration": "risk",
    "large_fund_position": "risk",
    "high_leverage": "risk",
    "leveraged": "risk",
    "futures_high_notional": "risk",
    "futures_notional": "risk",
    "expired_options": "risk",
    "near_expiry_options": "risk",
    "options_concentration": "risk",
    "cash_drag": "performance",
    "margin_usage": "risk",
    "stale_data": "technical",
    "low_position_count": "risk",
    "sector_concentration": "risk",
    "low_sector_diversification": "risk",
    "large_unrealized_loss": "performance",
    "low_cost_basis_coverage": "technical",
    "provider_error": "technical",
}

def _map_alert_type(flag_type: str) -> str:
    return _ALERT_TYPE_MAP.get(flag_type, "risk")
```

**Why `/api/positions/alerts` (not a new route file):** Position flags are the primary data source and PositionService is already imported. Keeps it simple. The `positions_router` prefix means the URL is `/api/positions/alerts`.

---

## Step 2: Frontend Chassis — API method + query key

### 2a. APIService method

**File**: `frontend/packages/chassis/src/services/APIService.ts`

Add after `getPositionsHoldings()` (~line 420):

```typescript
interface PortfolioAlertsResponse {
  success: boolean;
  alerts: Array<Record<string, unknown>>;
  total: number;
}

async getPortfolioAlerts(): Promise<PortfolioAlertsResponse> {
  return this.request<PortfolioAlertsResponse>('/api/positions/alerts');
}
```

### 2b. Query key

**File**: `frontend/packages/chassis/src/queryKeys.ts`

Add after `positionsHoldingsKey` (line 189):

```typescript
export const portfolioAlertsKey = () => ['portfolioAlerts'] as const;
```

Add to `AppQueryKey` union (line 223):

```typescript
| ReturnType<typeof portfolioAlertsKey>
```

Export from chassis barrel (`index.ts`) if not already auto-exported via wildcard.

---

## Step 3: Frontend Connectors — `useSmartAlerts()` hook

**File**: `frontend/packages/connectors/src/features/positions/hooks/useSmartAlerts.ts` (new file)

Follows the exact `usePositions` pattern (same directory, `frontend/packages/connectors/src/features/positions/hooks/usePositions.ts`) — `useQuery` + `useSessionServices()` + `useMemo`:

```typescript
import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';
import { HOOK_QUERY_CONFIG, frontendLogger, portfolioAlertsKey } from '@risk/chassis';
import { useSessionServices } from '../../../providers/SessionServicesProvider';

export interface SmartAlert {
  id: string;
  type: 'performance' | 'risk' | 'opportunity' | 'market' | 'technical';
  severity: 'info' | 'warning' | 'critical';
  message: string;
  flagType: string;
  ticker?: string;
  actionable: boolean;
  dismissible: boolean;
}

function transformAlerts(payload: { alerts: Array<Record<string, unknown>> }): SmartAlert[] {
  return (payload.alerts || []).map((a) => ({
    id: String(a.id ?? ''),
    type: (a.type as SmartAlert['type']) ?? 'risk',
    severity: (a.severity as SmartAlert['severity']) ?? 'info',
    message: String(a.message ?? ''),
    flagType: String(a.flag_type ?? ''),
    ticker: a.ticker ? String(a.ticker) : undefined,
    actionable: Boolean(a.actionable),
    dismissible: Boolean(a.dismissible),
  }));
}

export const useSmartAlerts = () => {
  const { api } = useSessionServices();

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: portfolioAlertsKey(),
    queryFn: async (): Promise<SmartAlert[]> => {
      frontendLogger.adapter.transformStart('useSmartAlerts', { source: '/api/positions/alerts' });
      const payload = await api.getPortfolioAlerts();
      const alerts = transformAlerts(payload);
      frontendLogger.adapter.transformSuccess('useSmartAlerts', { alertCount: alerts.length });
      return alerts;
    },
    enabled: !!api,
    staleTime: HOOK_QUERY_CONFIG.usePerformance.staleTime,
    retry: (failureCount) => failureCount < 2,
  });

  return useMemo(() => ({
    data: data ?? [],
    loading: isLoading,
    error: error instanceof Error ? error.message : null,
    refetch,
  }), [data, isLoading, error, refetch]);
};
```

**Export chain**:
- Add to `frontend/packages/connectors/src/features/positions/index.ts`
- Add to `frontend/packages/connectors/src/index.ts`

---

## Step 4: Frontend UI — Wire through container → component

### 4a. PortfolioOverviewContainer

**File**: `frontend/packages/ui/src/components/dashboard/views/modern/PortfolioOverviewContainer.tsx`

1. Import and call `useSmartAlerts()`:
```typescript
import { useSmartAlerts } from '@risk/connectors';
// inside component:
const { data: smartAlerts } = useSmartAlerts();
```

2. Pass to PortfolioOverview:
```typescript
<PortfolioOverview
  data={portfolioOverviewData}
  smartAlerts={smartAlerts}       // NEW
  onRefresh={handleRefresh}
  loading={isLoading}
  className={props.className}
  {...props}
/>
```

### 4b. PortfolioOverview component

**File**: `frontend/packages/ui/src/components/portfolio/PortfolioOverview.tsx`

1. **Add `smartAlerts` to `PortfolioOverviewProps`** (line 308-325):
```typescript
interface PortfolioOverviewProps {
  data?: { summary: { ... } };
  smartAlerts?: SmartAlert[];  // NEW — from container
  onRefresh?: () => void;
  loading?: boolean;
  className?: string;
}
```

The existing `SmartAlert` interface at lines 296-305 has `timestamp: Date` and `relatedMetrics: string[]` which the backend doesn't provide. Update it to match what the backend actually returns:

```typescript
interface SmartAlert {
  id: string;
  type: "performance" | "risk" | "opportunity" | "market" | "technical";
  severity: "info" | "warning" | "critical";
  message: string;
  flagType?: string;       // WAS: timestamp: Date
  ticker?: string;         // WAS: relatedMetrics: string[]
  actionable: boolean;
  dismissible: boolean;
}
```

The rendering code (lines 1119-1162) only uses `id`, `severity`, `message`, `actionable`, and `dismissible` — so removing `timestamp` and `relatedMetrics` has no rendering impact. Adding `flagType` and `ticker` is additive.

2. **Destructure prop** (line 327-332): add `smartAlerts: externalAlerts = []`.

3. **Remove internal state + stub**:
   - Delete `const [smartAlerts, setSmartAlerts] = useState<SmartAlert[]>([])` (line 368)
   - Delete `const generateSmartAlerts = useCallback((): SmartAlert[] => [], [])` (line 579)
   - Remove `setSmartAlerts(generateSmartAlerts())` from the mount `useEffect` (line 589)
   - Remove `setSmartAlerts(generateSmartAlerts())` from `handleDataRefresh` (line 660)
   - Remove `generateSmartAlerts` from `useCallback` dependency array of `handleDataRefresh` (line 678)
   - Remove `generateSmartAlerts` from `useEffect` dependency array (line 604)

4. **Update rendering** (line 1119-1162): replace all `smartAlerts` references with `externalAlerts`:
   - `{externalAlerts.length > 0 && alertsEnabled && (` (line 1119)
   - `{externalAlerts.length} Active` (line 1127)
   - `{externalAlerts.slice(0, 3).map(` (line 1132)

---

## Step 5: Handle edge cases

### 5a. Empty state
When `externalAlerts` is empty (`[]`), the section is already hidden by `{externalAlerts.length > 0 && ...}`. No change needed.

### 5b. Loading state
The alerts hook loads independently from portfolio summary. If alerts are still loading, `data` defaults to `[]`, so the section stays hidden until data arrives. Acceptable UX.

### 5c. Refresh / Cache Invalidation
The `handleDataRefresh` function (line 651) currently calls `setSmartAlerts(generateSmartAlerts())`. After removing internal state, just remove that line.

**Important**: `staleTime` only marks freshness — it doesn't trigger refetch on manual refresh. Two changes needed to ensure alerts refresh when the user clicks refresh:

1. **CacheCoordinator** (`frontend/packages/chassis/src/services/CacheCoordinator.ts`, line ~224-228): Add `portfolioAlertsKey()` to the `invalidatePortfolioData` invalidation list alongside `positionsHoldingsKey()`:
```typescript
await Promise.all([
  this.queryClient.invalidateQueries({ queryKey: portfolioSummaryKey(portfolioId) }),
  this.queryClient.invalidateQueries({ queryKey: performanceKey(portfolioId) }),
  this.queryClient.invalidateQueries({ queryKey: positionsHoldingsKey() }),
  this.queryClient.invalidateQueries({ queryKey: portfolioAlertsKey() }),  // ADD
]);
```

2. Import `portfolioAlertsKey` at the top of `CacheCoordinator.ts` (add to the existing `queryKeys` import).

### 5d. Dismiss behavior
The dismiss button UI exists but has no handler. Keep as visual-only for now. Real dismiss persistence (localStorage or backend) is out of scope.

---

## Files Modified (Summary)

| File | Change |
|------|--------|
| `routes/positions.py` | Add `/alerts` endpoint + `_map_alert_type` helper |
| `frontend/packages/chassis/src/services/APIService.ts` | Add `getPortfolioAlerts()` method |
| `frontend/packages/chassis/src/queryKeys.ts` | Add `portfolioAlertsKey` + union type |
| `frontend/packages/connectors/src/features/positions/hooks/useSmartAlerts.ts` | **New file** — `useSmartAlerts()` hook |
| `frontend/packages/connectors/src/features/positions/index.ts` | Export `useSmartAlerts` |
| `frontend/packages/connectors/src/index.ts` | Export `useSmartAlerts` |
| `frontend/packages/ui/src/.../PortfolioOverviewContainer.tsx` | Import hook, pass `smartAlerts` prop |
| `frontend/packages/ui/src/.../PortfolioOverview.tsx` | Accept prop, remove internal state + stub |
| `frontend/packages/chassis/src/services/CacheCoordinator.ts` | Add `portfolioAlertsKey` to invalidation list |

## Verification

1. **Backend**: `curl http://localhost:8000/api/positions/alerts` (with auth cookie) — returns `{ success: true, alerts: [...], total: N }` with real position flags
2. **Frontend build**: `cd frontend && pnpm typecheck && pnpm lint && pnpm build` — 0 errors
3. **Visual**: Load Overview tab in browser — Smart Alerts card appears with real alerts (concentration warnings, leverage info, etc.). Severity colors: red (critical/error), amber (warning), blue (info).
4. **Edge case**: Empty portfolio — alerts section stays hidden
5. **Edge case**: No flags triggered (well-diversified portfolio) — section stays hidden (correct)

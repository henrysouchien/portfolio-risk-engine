# Data Providers Settings Card

## Context

The Settings page has an Account Connections card for brokerage accounts. We need a companion "Data Providers" card showing market data/pricing source status (FMP, IBKR). Must be generic — adding a new provider = one backend registry entry, zero frontend changes.

## Steps

### Step 1: Backend route with provider registry
**New file:** `routes/data_providers.py`

Registry pattern — dict of provider ID → status check callable:
```python
from pydantic import BaseModel
from typing import Literal

class DataProviderStatus(BaseModel):
    id: str
    name: str
    status: Literal["active", "inactive", "error"]
    detail: str

DATA_PROVIDER_REGISTRY: dict[str, Callable[[], DataProviderStatus]] = {
    "fmp": _check_fmp_status,
    "ibkr": _check_ibkr_status,
}
```

**FMP check:** If `FMP_API_KEY` env var present → `active`, detail="Configured — 700 calls/min". If missing → `inactive`, detail="API key not configured". On error → `error`. Note: "active" means "configured" — key validity is only checked on actual API calls (lazy validation in FMPClient). This is intentional; a real health ping would add latency for no user benefit on a settings page.

**IBKR check:** Use `is_provider_enabled('ibkr')` and `is_provider_available('ibkr')` from `providers/routing.py`. The `is_provider_available` function reuses the existing 60s probe cache (`_IBKR_PROBE_TTL = 60.0`) — no live gateway probe on every request. If not enabled → `inactive`, detail="Not enabled". If enabled + available → `active`, detail="Gateway connected". If enabled + not available → `inactive`, detail="Gateway not connected". Note: `is_provider_available()` catches probe exceptions internally and returns False, so the `error` status is not reachable for IBKR via this helper — probe failures collapse to `inactive`. This is acceptable for v1; a richer probe result can be added later if needed.

**Endpoint:** `GET /api/v2/data-providers` → `{"providers": [...]}`. No auth required (system-level config, matches existing provider-routing/status pattern).

### Step 2: Register route in app.py
**File:** `app.py` (line ~6720 area)
```python
from routes.data_providers import data_providers_router
app.include_router(data_providers_router)
```

### Step 3: Frontend types
**File:** `frontend/packages/chassis/src/types/index.ts`
```ts
export interface DataProviderInfo {
  id: string
  name: string
  status: 'active' | 'inactive' | 'error'
  detail: string
}
export interface DataProvidersResponse {
  providers: DataProviderInfo[]
}
```

### Step 4: Frontend service methods
**File:** `frontend/packages/chassis/src/services/RiskAnalysisService.ts`
```ts
async listDataProviders(): Promise<DataProvidersResponse> {
  return this.request<DataProvidersResponse>('/api/v2/data-providers', { method: 'GET' });
}
```

**File:** `frontend/packages/chassis/src/services/APIService.ts`
```ts
async listDataProviders() { return this.riskAnalysisService.listDataProviders(); }
```

### Step 5: useDataProviders hook
**New file:** `frontend/packages/connectors/src/features/settings/hooks/useDataProviders.ts`
```ts
import { useQuery } from '@tanstack/react-query';
import type { DataProvidersResponse } from '@risk/chassis';
import { useAPIService } from '../../../providers/SessionServicesProvider';

export const useDataProviders = () => {
  const api = useAPIService();
  return useQuery({
    queryKey: ['settings', 'data-providers'],
    enabled: !!api,
    staleTime: 60_000,
    refetchOnWindowFocus: true,
    queryFn: async () => {
      if (!api) throw new Error('API not available');
      return api.listDataProviders();
    },
  });
};
```

**Export chain:**
- New `frontend/packages/connectors/src/features/settings/index.ts` → `export { useDataProviders } from './hooks/useDataProviders'`
- `frontend/packages/connectors/src/index.ts` → add `export { useDataProviders } from './features/settings'`

### Step 6: Presentational component
**New file:** `frontend/packages/ui/src/components/settings/DataProviders.tsx`

Same card pattern as AccountConnections:
- `Card variant="glassTinted" hover="lift"`
- CardHeader: "Data Providers" / "Market data and pricing sources"
- CardContent: `divide-y` rows, each with status dot + name + detail string
- Status dots: active=emerald-500, inactive=neutral-400, error=red-500
- Loading state: skeleton or muted text
- No action buttons (v1 — read-only)

### Step 7: Container component
**New file:** `frontend/packages/ui/src/components/settings/DataProvidersContainer.tsx`

Minimal — calls `useDataProviders()` and passes to presentational, including error state:
```tsx
const DataProvidersContainer: React.FC = () => {
  const { data, isLoading, error } = useDataProviders();
  return <DataProviders providers={data?.providers ?? []} isLoading={isLoading} error={error?.message ?? null} />;
};
export default React.memo(DataProvidersContainer);
```

The presentational component accepts an optional `error?: string | null` prop. If present, renders an error banner (same pattern as AccountConnections — `border-red-200 bg-red-50` card with `AlertTriangle` icon). The presentational component normalizes the error message: always display the fixed copy "Failed to load provider status" regardless of what the raw error string says. This keeps implementation details out of the UI.

### Step 8: Mount on Settings page
**File:** `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx`

Add lazy import (line ~123):
```tsx
const DataProvidersContainer = React.lazy(() => import('../settings/DataProvidersContainer'));
```

Mount between AccountConnectionsContainer (line 545) and CsvImportCard (line 548):
```tsx
<div className="hover-lift-premium mb-8">
  <DataProvidersContainer />
</div>
```

## Files Modified
| File | Change |
|------|--------|
| `routes/data_providers.py` | **New**: registry + endpoint |
| `app.py` | Register router |
| `chassis/src/types/index.ts` | Add 2 interfaces |
| `chassis/src/services/RiskAnalysisService.ts` | Add `listDataProviders()` |
| `chassis/src/services/APIService.ts` | Add pass-through |
| `connectors/src/features/settings/hooks/useDataProviders.ts` | **New**: hook |
| `connectors/src/features/settings/index.ts` | **New**: barrel export |
| `connectors/src/index.ts` | Export useDataProviders |
| `ui/src/components/settings/DataProviders.tsx` | **New**: presentational |
| `ui/src/components/settings/DataProvidersContainer.tsx` | **New**: container |
| `ui/src/components/apps/ModernDashboardApp.tsx` | Lazy import + mount |
| `tests/routes/test_data_providers.py` | **New**: backend tests (FMP configured/missing/error, IBKR enabled/available/unavailable) |
| `tests/routes/test_phase5a_router_registration.py` | Add assertion that `/api/v2/data-providers` is registered |

## Verification
1. `pytest tests/routes/test_data_providers.py -x` — backend tests
2. `npx tsc --noEmit` — type check
3. Browser: Settings page shows Data Providers card below Account Connections with FMP (active) and IBKR status
4. Adding a new provider to `DATA_PROVIDER_REGISTRY` on backend → appears in card with no frontend changes

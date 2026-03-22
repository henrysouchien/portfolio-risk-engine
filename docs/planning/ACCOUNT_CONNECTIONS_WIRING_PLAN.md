# Wire Full Accounts List to Settings Account Connections

## Context

The Settings "Account Connections" section only shows Merrill (via Plaid). Charles Schwab and Interactive Brokers accounts are invisible because the frontend only queries Plaid and SnapTrade hooks. The backend `GET /api/v2/accounts` already returns all 12 accounts across all institutions, but the frontend never calls it.

**Prerequisite completed:** The connect flow bugs (postMessage, stale closure, void refresh) were fixed in commit `73b63e85`. Connect hooks now return discriminated union results (`confirmed | pending_sync | cancelled | ready`), refresh methods return promises, and AccountConnectionsContainer already handles the new contract.

## Codex Review Findings Addressed (from prior rounds)
- **#1 Mixed-provider institutions**: Filter by `data_source_provider`, group remaining by institution_key. One row per institution.
- **#2 source bucket**: Use actual `data_source_provider` value, not generic 'direct'.
- **#3 ID scheme**: `db-{institution_key}` — unique per institution.
- **#4 Cache invalidation**: `staleTime: 30_000` + invalidate `['accounts', 'list']` in connect/disconnect success paths. Connect hooks already invalidate their own queries (fixed in `73b63e85`).
- **#5 Timestamps**: Backend serializer adds `last_position_sync_at` + `updated_at` as ISO 8601 with Z suffix via `_to_iso_utc()`.
- **#7 Query key pattern**: Inline `['accounts', 'list']` matching `usePortfolioList`.
- **#8 Testing**: Named test files and cases.

## Steps

### Step 1: Add `last_position_sync_at` and `updated_at` to backend serializer
**File:** `mcp_tools/portfolio_management.py` — `_serialize_account()` (line 58)
```python
from datetime import timezone as _tz

def _to_iso_utc(dt) -> str | None:
    if dt is None:
        return None
    if hasattr(dt, 'tzinfo') and dt.tzinfo is not None:
        dt = dt.astimezone(_tz.utc)
    return dt.replace(tzinfo=None).isoformat() + "Z"
```
Add to payload:
```python
"last_position_sync_at": _to_iso_utc(account.get("last_position_sync_at")),
"updated_at": _to_iso_utc(account.get("updated_at")),
```

### Step 2: Add TypeScript types — `chassis/src/types/index.ts`
```ts
export interface AccountRecord {
  id: number
  institution_key: string
  institution_display_name: string
  account_id_external: string
  account_name: string | null
  account_type: string | null
  is_active: boolean
  data_source_provider: string | null
  linked_to_current_portfolio?: boolean
  last_position_sync_at: string | null
  updated_at: string | null
}
export interface AccountInstitutionGroup {
  institution_key: string
  institution_display_name: string
  accounts: AccountRecord[]
}
export interface AccountsListResponse {
  account_count: number
  institutions: AccountInstitutionGroup[]
}
```

### Step 3: Add `listAccounts()` to RiskAnalysisService
**File:** `frontend/packages/chassis/src/services/RiskAnalysisService.ts`
```ts
async listAccounts(activeOnly = true): Promise<AccountsListResponse> {
  const qs = activeOnly ? '' : '?active_only=false';
  return this.request<AccountsListResponse>(`/api/v2/accounts${qs}`, { method: 'GET' });
}
```

### Step 4: Expose on APIService
**File:** `frontend/packages/chassis/src/services/APIService.ts`
```ts
async listAccounts(activeOnly = true) { return this.riskAnalysisService.listAccounts(activeOnly); }
```

### Step 5: Create `useAccounts` hook
**New file:** `frontend/packages/connectors/src/features/portfolio/hooks/useAccounts.ts`
```ts
import { useQuery } from '@tanstack/react-query';
import type { AccountsListResponse } from '@risk/chassis';
import { useAPIService } from '../../../providers/SessionServicesProvider';

export const useAccounts = () => {
  const api = useAPIService();
  return useQuery({
    queryKey: ['accounts', 'list'],
    enabled: !!api,
    staleTime: 30_000,
    refetchOnWindowFocus: true,
    queryFn: async () => {
      if (!api) throw new Error('API not available');
      return api.listAccounts();
    },
  });
};
```
**Export chain:**
- `features/portfolio/index.ts` — add `export { useAccounts } from './hooks/useAccounts'`
- `connectors/src/index.ts` — add `useAccounts` to the portfolio re-export

### Step 6: Merge accounts in AccountConnectionsContainer
**File:** `frontend/packages/ui/src/components/settings/AccountConnectionsContainer.tsx`

**NOTE:** This file was already modified by the connect flow fix (`73b63e85`). The connect hooks now return `ConnectResult` with `status` field. Build on top of those changes.

Import `useAccounts` from `@risk/connectors`. Import `useQueryClient` from `@tanstack/react-query`.

**Extract `buildUnifiedAccountsList()` as a named pure function** for testability:

```ts
function buildUnifiedAccountsList(
  plaidInstitutionNames: Set<string>,  // institution names from Plaid connections (lowercase)
  snaptradeInstitutionNames: Set<string>,  // institution names from SnapTrade connections (lowercase)
  accountsData: AccountsListResponse | undefined,
): ConnectedAccount[] {
  const dbAccounts: ConnectedAccount[] = [];
  if (!accountsData?.institutions) return dbAccounts;

  for (const group of accountsData.institutions) {
    // Filter out accounts already covered by Plaid/SnapTrade hooks.
    // Primary: check data_source_provider field on each account record.
    // Fallback: if data_source_provider is NULL (ambiguous linking via LEFT JOIN),
    // check if this institution is already displayed via Plaid/SnapTrade by name.
    // This prevents duplicate rows for accounts where the DB join didn't resolve.
    // Use same normalize() as container's Plaid balance matching (handles dashes, spaces, suffixes)
    const instNameNorm = normalize(group.institution_display_name);
    // Also check substring both ways for partial matches (e.g., "Interactive Brokers" ↔ "Interactive Brokers - US")
    const coveredByPlaid = plaidInstitutionNames.has(instNameNorm) ||
      [...plaidInstitutionNames].some(n => n.includes(instNameNorm) || instNameNorm.includes(n));
    const coveredBySnapTrade = snaptradeInstitutionNames.has(instNameNorm) ||
      [...snaptradeInstitutionNames].some(n => n.includes(instNameNorm) || instNameNorm.includes(n));

    const remaining = group.accounts.filter(a => {
      if (a.data_source_provider === 'plaid' || a.data_source_provider === 'snaptrade') return false;
      // If provider is null AND institution is already shown via Plaid/SnapTrade, skip
      if (a.data_source_provider == null && (coveredByPlaid || coveredBySnapTrade)) return false;
      return true;
    });
    if (remaining.length === 0) continue;

    // Find most recent sync timestamp
    const timestamps = remaining
      .map(a => a.last_position_sync_at || a.updated_at)
      .filter(Boolean)
      .map(t => new Date(t!).getTime());
    const lastSync = timestamps.length > 0 ? new Date(Math.max(...timestamps)) : null;

    // Dominant provider
    const providers = remaining.map(a => a.data_source_provider).filter(Boolean);
    const source = providers.length > 0
      ? providers.sort((a, b) => providers.filter(v => v === b).length - providers.filter(v => v === a).length)[0]
      : 'manual';

    dbAccounts.push({
      id: `db-${group.institution_key}`,
      name: group.institution_display_name,
      type: inferAccountType(group.institution_display_name),
      provider: group.institution_key,
      logo: getProviderLogo(group.institution_display_name),
      connected: true,
      status: 'connected',
      source: source || 'manual',
      lastSync,
      accounts: remaining.length,
      permissions: [],
    });
  }
  return dbAccounts;
}
```

In the component, call `useAccounts()` and merge:
```ts
const { data: accountsData, isLoading: accountsLoading, error: accountsError } = useAccounts();

// After existing Plaid + SnapTrade connectedAccounts build (line ~507-631):
// Promote normalize() to module scope (currently block-scoped at line ~528).
// Move it above both buildUnifiedAccountsList() and the Plaid map callback so both can use it.
const normalize = (str: string) => str.toLowerCase().replace(/[-_]/g, ' ').replace(/\s+/g, ' ').trim();
// This handles "Interactive Brokers - US" ↔ "Interactive Brokers" matching.
// Filter out empty names to prevent ''.includes('') matching everything
const plaidNames = new Set((connections || []).map((c: any) => normalize(c.institution || c.institution_name || '')).filter(Boolean));
const snaptradeNames = new Set((snaptradeConnections || []).map((c: any) => normalize(c.brokerage_name || '')).filter(Boolean));
const dbAccounts = buildUnifiedAccountsList(plaidNames, snaptradeNames, accountsData);
const connectedAccounts = [...plaidAccounts, ...snaptradeAccounts, ...dbAccounts];
```

**Loading/error:** Add `accountsLoading` to `isLoading`, `accountsError?.message` to combined `error`.

**Cache invalidation on connect/disconnect:**

In **AccountConnectionsContainer**: Add `queryClient.invalidateQueries({ queryKey: ['accounts', 'list'] })` to:
- `handleConnectAccount` success path (both `confirmed` and `pending_sync` branches)
- `handleDisconnectAccount` success paths

In **connect hooks** (useConnectAccount.ts + useConnectSnapTrade.ts): Add `queryClient.invalidateQueries({ queryKey: ['accounts', 'list'] })` to:
- The immediate confirmation invalidation list (alongside plaidConnections, portfolios, etc.)
- The pending_sync recovery useEffect's confirmation invalidation list
This ensures the full accounts list refreshes whether confirmation happens immediately or via delayed retry.

**Error dismiss:** Add `queryClient.invalidateQueries({ queryKey: ['accounts', 'list'] })` to `onClearError`.

**Sync button:** The sync button (`handleSyncAccount`) is currently a no-op placeholder. Replace with:
```ts
const handleSyncAccount = useCallback(async (_accountId: string) => {
  await Promise.all([
    refreshConnections(),           // Plaid — from usePlaid() destructure
    refreshHoldings(),              // Plaid — from usePlaid() destructure
    ...(snaptradeEnabled ? [
      _refreshSnapTradeConnections(),  // from useSnapTrade() destructure
      _refreshSnapTradeHoldings(),     // from useSnapTrade() destructure
    ] : []),
    queryClient.invalidateQueries({ queryKey: ['accounts', 'list'] }),
  ]);
}, [refreshConnections, refreshHoldings, snaptradeEnabled, _refreshSnapTradeConnections, _refreshSnapTradeHoldings, queryClient]);
```
Note: refresh methods now return promises (fixed in `73b63e85`), so `await Promise.all` works correctly.

### Step 7: Update presentational component
**File:** `frontend/packages/ui/src/components/settings/AccountConnections.tsx`

- Add `source?: string` to `ConnectedAccount` interface
- Update `lastSync` type to `Date | null`
- Update `timeAgo()`: `if (!date) return 'Never'`

**Also update the container's `ConnectedAccount` interface** in `AccountConnectionsContainer.tsx` (line ~23):
- `lastSync: Date` → `lastSync: Date | null`
- Add `source?: string`
Both components must agree on the type.
- For accounts where source is NOT `'plaid'` and NOT `'snaptrade'`, hide delete and reauth buttons
- Keep sync/refresh button for all rows

### Step 8: Update disconnect handler
In `AccountConnectionsContainer.tsx`, add `db-` prefix guard:
```ts
} else if (accountId.startsWith('db-')) {
  toast({
    title: "Not Available",
    description: "This account was imported via CSV/Flex and cannot be disconnected from here.",
    variant: "default"
  });
}
```

## Files Modified
| File | Change |
|------|--------|
| `mcp_tools/portfolio_management.py` | Add timestamps to serializer |
| `chassis/src/types/index.ts` | Add 3 interfaces |
| `chassis/src/services/RiskAnalysisService.ts` | Add `listAccounts()` |
| `chassis/src/services/APIService.ts` | Add `listAccounts()` pass-through |
| `connectors/src/features/portfolio/hooks/useAccounts.ts` | **New**: useAccounts hook |
| `connectors/src/features/portfolio/index.ts` | Export useAccounts |
| `connectors/src/index.ts` | Export useAccounts |
| `ui/src/components/settings/AccountConnectionsContainer.tsx` | Merge logic, loading, cache invalidation, sync button |
| `ui/src/components/settings/AccountConnections.tsx` | source field, null-safe lastSync, conditional buttons |
| `connectors/src/features/auth/hooks/useConnectAccount.ts` | Add `['accounts','list']` to invalidation lists |
| `connectors/src/features/auth/hooks/useConnectSnapTrade.ts` | Add `['accounts','list']` to invalidation lists |

## Testing
**Backend:** `test_serialize_account_includes_sync_timestamps` in `tests/mcp_tools/test_portfolio_management.py`

**Frontend hook:** `useAccounts.test.tsx` following `usePortfolioList.test.tsx` pattern

**Merge logic:** Test `buildUnifiedAccountsList()` directly:
- Plaid/SnapTrade accounts excluded from DB entries
- Mixed-provider institution — snaptrade filtered, ibkr_flex kept
- All accounts covered → no duplicate row
- lastSync uses most recent timestamp
- source uses dominant provider
- Null timestamps → lastSync is null
- Account with data_source_provider: null at Plaid-covered institution → filtered (no duplicate)
- Account with data_source_provider: null at uncovered institution → included
- Fuzzy name dedup: "Interactive Brokers - US" (DB) vs "Interactive Brokers" (SnapTrade) → filtered

## Verification
1. `npx tsc --noEmit` — type check
2. `pytest tests/mcp_tools/test_portfolio_management.py -x` — backend tests
3. `npx vitest run useAccounts` — frontend tests
4. Browser: Settings → Account Connections shows Schwab, IBKR, Merrill
5. Merrill has reauth/disconnect buttons (Plaid-sourced)
6. Schwab/IBKR show as connected without disconnect button
7. No duplicate entries
8. Sync button refreshes all data

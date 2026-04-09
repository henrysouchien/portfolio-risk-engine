# F15: Hedge Workflow Dialog — All-Broker Account Support

**Bug**: `HedgeWorkflowDialog` only shows SnapTrade accounts in the execution account selector.

**Status**: Plan

---

## Root Cause

`HedgeWorkflowDialog.tsx:299` calls `api.getSnapTradeConnections()` which hits `/api/snaptrade/connections` and returns only SnapTrade-connected accounts. The response is wrapped in `{ connections: [...] }` with a `SnapTradeConnection` shape.

Every other trading surface in the app (QuickTradeCard, OrdersCard, BasketsCard, RebalanceTool, AssetAllocationContainer) uses the `useTradingAccounts()` hook from `@risk/connectors`, which calls `api.getTradingAccounts()` → `GET /api/trading/accounts`. That endpoint invokes `TradeExecutionService.list_tradeable_accounts()`, which aggregates accounts across **all** registered broker adapters (SnapTrade, IBKR, Schwab).

The HedgeWorkflowDialog is the only trading surface still using the old SnapTrade-only API.

## Response Shape Comparison

### Current (SnapTrade-only)
```
GET /api/snaptrade/connections
→ { success: bool, connections: SnapTradeConnection[], message?: string }

SnapTradeConnection {
  authorization_id: string     // brokerage_authorization — NOT used as account_id
  brokerage_name: string
  account_id: string           // ← the dialog reads this directly (line 307)
  account_name?: string
  account_number?: string
  account_type?: string
  status: string
}
```

The dialog casts each connection to a `ConnectionWithAccountId` interface and reads `account_id` directly (line 307), plus `brokerage_name`, `account_name`, `account_number`. It builds a label from the non-empty parts of `[brokerageName, accountName]` joined with ` • `, with `accountNumber` appended if present, falling back to raw `accountId` if all label parts are empty (line 316-323). The SnapTrade `/connections` endpoint returns `account_id` as a direct field from `account.get("id")` at `connections.py:140` — there is no `authorization_id`-to-`account_id` cast.

### Target (all-broker)
```
GET /api/trading/accounts
→ BrokerAccountResponse[]   (flat array, no wrapper)

BrokerAccountResponse {
  account_id: string          // ← direct field, no cast needed
  account_name: string
  brokerage_name: string
  provider: string            // "snaptrade" | "ibkr" | "schwab"
  cash_balance: number
  available_funds: number
  account_type: string
  meta: Record<string, unknown>
  authorization_id?: string
}
```

### Key Differences
1. **Wrapper**: SnapTrade wraps in `{ connections: [...] }`. Trading accounts is a flat array.
2. **Field availability**: `account_id` is a direct string field on both shapes (no cast on either). `account_number` does not exist on `BrokerAccountResponse` but is rarely populated on SnapTrade connections anyway.
3. **Extra fields**: `provider`, `cash_balance`, `available_funds` are available on `BrokerAccountResponse` — useful for richer labels.
4. **Null account_name**: The backend `BrokerAccount.account_name` is `Optional[str]` (`trade_objects.py:417`), and `to_dict()` serializes it as-is (can be `null`). The SnapTrade adapter explicitly passes `None` when the source account has no name (`adapter.py:84`). The frontend `BrokerAccountResponse` TypeScript interface declares `account_name: string` (not optional), but the runtime value can be `null`. The label helper must handle this.

## Correct Pattern: QuickTradeCard

`QuickTradeCard.tsx` is the reference implementation for the hook + rendering:
```tsx
// Import
import { useTradingAccounts } from '@risk/connectors';
import type { BrokerAccountResponse } from '@risk/chassis';

// Hook
const accountsQuery = useTradingAccounts();
const accounts = accountsQuery.data ?? [];

// Label helper (NOTE: existing pattern is NOT null-safe — see C2 below)
const getAccountLabel = (account: BrokerAccountResponse) =>
  `${account.brokerage_name} · ${account.account_name}`;

// Render
accounts.map((account) => (
  <SelectItem key={account.account_id} value={account.account_id}>
    {getAccountLabel(account)}
  </SelectItem>
))
```

The hook returns `UseQueryResult<BrokerAccountResponse[], Error>` with `staleTime: 5min`, `retry: 2`, and React Query caching (query key `['trading', 'accounts']`).

**Note**: QuickTradeCard's `getAccountLabel` produces `"Broker · null"` when `account_name` is null. The current HedgeWorkflowDialog is actually more robust — it filters empty parts and falls back to `accountId` (line 316-323). The new implementation must preserve this null-safety rather than blindly copying the QuickTradeCard pattern.

## Changes

### File: `frontend/packages/ui/src/components/portfolio/HedgeWorkflowDialog.tsx`

#### C1. Replace manual state + useEffect with `useTradingAccounts` hook

**Remove** the following manual state declarations (~lines 218-220):
```tsx
const [accounts, setAccounts] = useState<AccountOption[]>([]);
const [accountsLoading, setAccountsLoading] = useState(false);
const [accountsError, setAccountsError] = useState<string | null>(null);
```

**Remove** the `ConnectionWithAccountId` interface (~lines 77-82):
```tsx
interface ConnectionWithAccountId {
  account_id?: string;
  brokerage_name?: string;
  account_name?: string;
  account_number?: string;
}
```

**Remove** the `AccountOption` interface (~lines 39-42):
```tsx
interface AccountOption {
  accountId: string;
  label: string;
}
```

**Remove** the entire `useEffect` that calls `api.getSnapTradeConnections()` (~lines 288-349):
```tsx
useEffect(() => {
  if (!open || step < 3) { return; }
  let cancelled = false;
  const loadAccounts = async () => { ... };
  void loadAccounts();
  return () => { cancelled = true; };
}, [api, open, step]);
```

**Update `resetWorkflow()`** (~lines 235-250): Remove the three setter calls for the deleted state variables. The function currently has:
```tsx
const resetWorkflow = () => {
  setStep(1);
  setImpactData(null);
  setTradePreviewData(null);
  setExecuteData(null);
  setAccounts([]);           // ← REMOVE (state deleted)
  setAccountsLoading(false); // ← REMOVE (state deleted)
  setAccountsError(null);    // ← REMOVE (state deleted)
  setSelectedAccountId('');
  setImpactKey('');
  setTradePreviewKey('');
  setTradingDisabled(false);
  resetImpact();
  resetTradePreview();
  resetTradeExecute();
};
```
After edit:
```tsx
const resetWorkflow = () => {
  setStep(1);
  setImpactData(null);
  setTradePreviewData(null);
  setExecuteData(null);
  setSelectedAccountId('');
  setImpactKey('');
  setTradePreviewKey('');
  setTradingDisabled(false);
  resetImpact();
  resetTradePreview();
  resetTradeExecute();
};
```
Note: `accounts`, `accountsLoading`, and `accountsError` are now derived from the `useTradingAccounts` React Query hook, which manages its own cache lifecycle. When `enabled` toggles off (dialog closes / step < 3), the query naturally becomes idle. No manual reset is needed because React Query handles this via the `enabled` flag and `staleTime`.

**Add** import of the type (the `useTradingAccounts` named import is added via C5's consolidated import edit):
```tsx
import type { BrokerAccountResponse } from '@risk/chassis';  // add to existing import
```

**Add** hook call (alongside other hooks, ~line 210 area):
```tsx
const {
  data: accounts = [],
  isLoading,
  isFetching,
  isError,
  error: accountsQueryError,
} = useTradingAccounts({ enabled: open && step >= 3, staleTime: 0 });
const accountsLoading = isLoading || isFetching;
const accountsError = accountsQueryError?.message ?? null;
```

**Cache freshness via `staleTime: 0`**: With `staleTime: 0`, React Query considers data immediately stale. When `enabled` toggles from `false` to `true` (dialog opens to step 3, or step advances to 3), React Query automatically refetches in the background. No manual `refetch()` effect is needed. This eliminates the entire class of bugs from the manual refetch approach (double-fetch, refetch loops, mount semantics, step-transition re-triggers). Specifically:
- **No double-fetch**: React Query handles the initial fetch + stale refetch internally.
- **No refetch loop**: No effect to loop.
- **No step-4 re-trigger**: `enabled` doesn't change on step 3→4 transition (still `true`), so no spurious refetch.
- **Fresh data on reopen**: When the dialog closes, `enabled` becomes `false`. On reopen at step 3, `enabled` becomes `true` again, cached data is stale → automatic background refetch.
- **`isFetching` still works**: Background refetch sets `isFetching=true`, so all C3/C4 guards work.

The `useTradingAccounts` hook's options type needs to accept `staleTime`. **Important**: Use explicit property merging, not a generic `...options` spread, to prevent callers from overriding `enabled` and bypassing the `api` readiness guard (`useTradingAccounts.ts:5` uses `enabled: !!api && (options?.enabled ?? true)`):
```tsx
// In useTradingAccounts.ts, widen options type with explicit property merging:
export function useTradingAccounts(options?: { enabled?: boolean; staleTime?: number }) {
  const { api } = useSessionServices();
  return useQuery({
    queryKey: ['trading', 'accounts'],
    queryFn: () => api.getTradingAccounts(),
    enabled: !!api && (options?.enabled ?? true),    // api guard always applied
    staleTime: options?.staleTime ?? 5 * 60 * 1000,  // default 5min, overridable
    // ... rest unchanged
  });
}
```
This preserves the `api` guard while allowing `staleTime` override. A naive `...options` spread would let callers pass `enabled: true` and bypass the `!!api` check entirely.

**Why `isFetching` instead of `isLoading`**: With TanStack Query v5, when cached data exists, a background refetch keeps `isLoading` false while `isFetching` is true. The C3 auto-select guard uses `isFetching` to prevent selecting from stale cached data while a fresh fetch is in flight. If we used `accountsLoading` (aliased from `isLoading`), the guard would pass through during a background refetch, potentially auto-selecting an account that no longer exists in the fresh response.

**Refetch-error handling via `isError`**: When a background refetch fails, TanStack Query v5 drops `isFetching` to `false` but retains stale cached data in `data`. The `isRefetchError` flag is `true`, but `isError` is the simpler guard — it is `true` whenever the query is in an error state (initial or refetch). Without `isError` in the C3 guard and C4 disabled states, auto-select and trade preview would fire on stale cached accounts after a failed refetch. The `isError` guard ensures the dialog treats a failed refetch the same as a failed initial fetch: no auto-select, Select disabled, Continue disabled.

#### C2. Add null-safe label helper

Add a local helper that preserves the current dialog's null-safe fallback behavior. The existing QuickTradeCard pattern (`${brokerage_name} · ${account_name}`) produces `"Broker · null"` when `account_name` is null — which can happen because `BrokerAccount.account_name` is `Optional[str]` on the backend and the SnapTrade adapter passes `None` when the source account has no name.

The current dialog's label builder (lines 316-323) filters empty parts and falls back to the raw `accountId`:
```tsx
// Current (robust)
const labelParts = [brokerageName, accountName].filter(Boolean);
if (accountNumber) { labelParts.push(accountNumber); }
label: labelParts.length ? labelParts.join(' • ') : accountId,
```

Preserve this null-safety:
```tsx
const getAccountLabel = (account: BrokerAccountResponse) => {
  const brokerage = String(account.brokerage_name ?? '').trim();
  const name = String(account.account_name ?? '').trim();
  const parts = [brokerage, name].filter(Boolean);
  return parts.length > 0 ? parts.join(' · ') : account.account_id;
};
```

This handles all nullable combinations:
- null `account_name` → `"Broker"` (brokerage_name only)
- null `brokerage_name` → `"Joint Brokerage"` (account_name only)
- null both → `"acct-123"` (fallback to account_id)
- both present → `"Broker · Joint Brokerage"`
- whitespace-only values are trimmed then filtered (the current dialog at lines 312-316 uses `String(x ?? '').trim()` + `.filter(Boolean)` — this helper preserves that exact pattern)

The `account_number` field is dropped because `BrokerAccountResponse` does not have it.

**Why explicit `?? ''`**: The `BrokerAccountResponse` TypeScript interface declares `account_name: string` and `brokerage_name: string` (not optional), but at runtime either can be `null` because the backend `BrokerAccount` dataclass has `account_name: Optional[str] = None` (`trade_objects.py:417`) and `to_dict()` serializes `None` as JSON `null`. The SnapTrade adapter explicitly passes `None` when the source account has no name (`adapter.py:84`). The `?? ''` coerces `null` to empty string before `filter(Boolean)` removes it, preventing `"null"` from appearing in the label.

#### C3. Update account auto-select effect + invalid-selection clearing

The current auto-select is inside the removed `loadAccounts` useEffect. Replace with a standalone effect that matches the pattern used in `QuickTradeCard.tsx:218-227` and `OrdersCard.tsx:365-374`, **with an `open && step >= 3` guard** to prevent premature auto-selection when the dialog is closed or on an earlier step, and **using `isFetching`** (not `accountsLoading`/`isLoading`) to prevent auto-selecting from stale cached data during a background refetch (TanStack Query v5 keeps `isLoading` false when cached data exists and a background refetch is in progress — only `isFetching` reflects the in-flight request):
```tsx
useEffect(() => {
  if (!open || step < 3 || isFetching || isError) return;

  if (accounts.length === 1 && !selectedAccountId) {
    setSelectedAccountId(accounts[0].account_id);
    return;
  }

  if (selectedAccountId && !accounts.some(account => account.account_id === selectedAccountId)) {
    setSelectedAccountId('');
  }
}, [accounts, selectedAccountId, open, step, isFetching, isError]);
```

**Why the guards are necessary**:
- **`!open || step < 3`**: React Query does not clear cached `data` when `enabled` toggles to `false` — it only stops refetching. So when the dialog closes (`open = false`) or the user is on step 1/2, `accounts` can still be a non-empty cached array. Without the guard, the C3 effect would fire on every render where `accounts` is cached, immediately undoing `resetWorkflow()`'s `setSelectedAccountId('')` (line 243). This would cause the trade-preview effect (line 356) to fire with a stale account on dialog reopen. The guard ensures auto-select only runs when the user is actively on the trade execution step.
- **`isFetching`**: When `enabled` toggles true, React Query triggers a background refetch (due to `staleTime: 0`). With TanStack Query v5, `isLoading` stays false when cached data exists and a background refetch is in progress — only `isFetching` reflects the in-flight request. Without the `isFetching` guard, the auto-select effect could run with stale cached data before the refetch completes — selecting an account that may no longer exist. Gating on `isFetching` (not `accountsLoading`/`isLoading`) ensures auto-select waits for the fresh response in all cases, including background refetches with cached data. The trade preview effect at line 356 won't fire until `selectedAccountId` is set, so this doesn't introduce a timing gap.

The second branch clears `selectedAccountId` when the query result changes and the previously selected account is no longer in the list. This can happen when:
- A brokerage connection is removed between dialog opens
- The `useTradingAccounts` query refetches and returns a different set (e.g., after a connection repair)
- The dialog is re-opened after the account list has changed

Without this guard, the dialog would show a stale `selectedAccountId` that doesn't match any option in the Select, leading to an invisible selection that passes a non-existent account to trade preview.

#### C4. Update account selector rendering (~lines 625-655)

Replace references to the `AccountOption` shape with `BrokerAccountResponse` fields:

**Before:**
```tsx
{accounts.map((account) => (
  <SelectItem key={account.accountId} value={account.accountId}>
    {account.label}
  </SelectItem>
))}
```

**After:**
```tsx
<Select value={selectedAccountId} onValueChange={setSelectedAccountId} disabled={isFetching || isError || accounts.length === 0}>
```

```tsx
{accounts.map((account) => (
  <SelectItem key={account.account_id} value={account.account_id}>
    {getAccountLabel(account)}
  </SelectItem>
))}
```

Also add `|| isFetching || isError` to the existing step-3 Continue disabled condition (which already checks `!tradingDisabled && previewIds.length > 0 && !tradePreviewPending` at `HedgeWorkflowDialog.tsx:438` and `:798`), and add `|| !selectedAccountId` to prevent advancing to step 4 with a stale selection while a refetch is in flight or after a refetch error.

The `accountsLoading`, `accountsError`, and `accounts.length === 0` guards in the JSX continue to work unchanged because the variable names are preserved. Note that `accountsLoading` is now `isLoading || isFetching`, so JSX loading states (spinners, "Loading accounts..." text) display correctly during both initial loads AND background refetches — the old `isLoading`-only alias would show stale "No accounts" or stale errors during a background refetch when cached data exists.

#### C5. Remove dead `useSessionServices` / `api` imports

Once the SnapTrade fetch effect is removed (C1), `api` is dead code — it is only referenced at three sites, all within the removed effect:
- Line 192: `const { api } = useSessionServices();` — the destructuring call
- Line 299: `await api.getSnapTradeConnections()` — inside the removed effect body
- Line 349: `[api, open, step]` — the removed effect's dependency array

**Remove** the destructuring at line 192:
```tsx
// REMOVE this line entirely:
const { api } = useSessionServices();
```

**Update** the import at line 3 to remove `useSessionServices` (keep `type HedgeStrategy` and add `useTradingAccounts` from C1):
```tsx
// Before:
import { useSessionServices, type HedgeStrategy } from '@risk/connectors';
// After:
import { useTradingAccounts, type HedgeStrategy } from '@risk/connectors';
```

Note: `useTradingAccounts` (added in C1) internally calls `useSessionServices()` to get `api`, so the hook itself handles the `api` dependency. The component no longer needs to import or destructure `useSessionServices` directly. The `useTradingAccounts` import is consolidated here rather than as a separate import line (C1 adds `import { useTradingAccounts } from '@risk/connectors'` — this C5 edit replaces that with a single combined import).

**Test file cleanup**: See T1 for the full list of `mockUseSessionServices` removals and replacements.

#### C6. Tier gating fix — downgrade `/api/trading/accounts` to auth-only

**Issue**: `useTradingAccounts()` calls `api.getTradingAccounts()` which hits `GET /api/trading/accounts`. That endpoint uses `_require_paid_user` (a `create_tier_dependency(minimum_tier="paid")` guard at `routes/trading.py:123`). The current SnapTrade connections endpoint (`routes/snaptrade.py:627`) uses session-based auth only (no tier gate). The hedge routes (`routes/hedging.py:225`, `:282`) also use plain `get_current_user` (no tier gate).

**Impact**: If a non-paid user opens the hedge dialog, `useTradingAccounts()` will receive a 403 from the paid-gated endpoint, and the dialog will show an error instead of listing accounts.

**Resolution**: Downgrade the `/api/trading/accounts` endpoint from `_require_paid_user` to `_require_authenticated_user`. This is a one-line change in `routes/trading.py:123`.

**Rationale**: Account listing does make live broker API calls — `trade_execution_service.py:252` fans out to each adapter's `list_accounts()`, which fetches accounts + per-account balances from SnapTrade (`brokerage/snaptrade/adapter.py:69`), IBKR (`brokerage/ibkr/adapter.py:145`), and Schwab (`brokerage/schwab/adapter.py:339`). However, these are lightweight read-only calls (account metadata + balances), not trading actions. The paid gate was originally placed for cost control, but account listing is a prerequisite for ANY trading workflow — you cannot select an account to trade in without first listing available accounts. The auth downgrade is acceptable because: (a) the calls are read-only, (b) accounts are already exposed via SnapTrade endpoints (`routes/snaptrade.py:627`) which are ungated, and (c) the hedge workflow already requires authenticated users. The `_require_authenticated_user` dependency already exists in `routes/trading.py:22-29` and provides the right level of auth (session cookie → user dict with email). All actual trading actions (`/preview`, `/execute`, `/cancel`, `/status/{order_id}`) remain paid-gated via `_require_paid_user`. This is consistent with how `routes/hedging.py` already uses plain `get_current_user` for its endpoints while still calling `TradeExecutionService` methods directly.

**Alternatives rejected**:
- *Add `GET /api/hedging/accounts`*: Duplicates the same `TradeExecutionService.list_tradeable_accounts()` call under a different URL. Two endpoints returning identical data is a maintenance liability. Also requires a new `getHedgeAccounts()` API method and a new `useHedgeAccounts()` hook — 3 new files for the same data.
- *Use existing hedging endpoint's account data*: The hedging router has no account-listing endpoint. The closest are `/preview` and `/execute`, which take an `account_id` as input — they don't return account lists.
- *Catch 403 + fallback*: Complex, fragile, and `useTradingAccounts()` doesn't expose retry/fallback options without expanding the hook interface.

**Backend change** in `routes/trading.py`:
```python
# Before (line 123):
    user: dict[str, Any] = Depends(_require_paid_user),

# After:
    user: dict[str, Any] = Depends(_require_authenticated_user),
```

This resolves the conflict between C1 (switch to `useTradingAccounts()`) and the tier gate. The frontend uses `useTradingAccounts()` as-is with zero additional changes.

**Doc update required**: `docs/planning/completed/TIER_ENFORCEMENT_PLAN.md` line 217 lists `GET /api/trading/accounts` as `PAID`. This must be updated to reflect the new `AUTH` (authenticated-only) level after C6 is implemented. The change is an intentional policy override — account listing makes lightweight read-only broker API calls (account metadata + balances), but these are a prerequisite for any trading workflow and accounts are already exposed ungated via SnapTrade endpoints. `AUTH` is the correct tier.

### File: `frontend/packages/ui/src/components/portfolio/HedgeWorkflowDialog.test.tsx`

#### T0. Add Select component mock

The test file currently does NOT mock the `Select` family of components from `../ui/select`. Without mocking, Radix UI `Select` primitives do not render children in jsdom, making it impossible to assert on `SelectItem` labels. `QuickTradeCard.test.tsx:25-31` demonstrates the required pattern:
```tsx
vi.mock('../ui/select', () => ({
  Select: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectItem: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectTrigger: ({ children }: { children: ReactNode; id?: string; className?: string }) => <div>{children}</div>,
  SelectValue: ({ placeholder }: { placeholder?: string }) => <span>{placeholder ?? ''}</span>,
}));
```

The relative path for HedgeWorkflowDialog's test is `'../ui/select'` (same directory depth as the existing import at line 18-23 of the component). Add this mock block after the `vi.mock('@risk/connectors')` block. Add `import type { ReactNode } from 'react';` at the top.

#### T1. Update mock setup

**Remove all `mockUseSessionServices` references** — the component no longer imports `useSessionServices` (removed in C5), so the mock is dead test infrastructure:
- Remove `mockUseSessionServices` from the `vi.hoisted()` block (test line 7, 12)
- Remove `useSessionServices: mockUseSessionServices` from `vi.mock('@risk/connectors')` (test line 19)
- Remove `mockUseSessionServices.mockReturnValue(...)` at test line 76-80 (beforeEach in first describe)
- Remove `mockUseSessionServices.mockReturnValue(...)` at test line 152-164 (beforeEach in second describe — this sets up `getSnapTradeConnections` with an account, replaced by `mockUseTradingAccounts` below)

**Add `useTradingAccounts`** to the hoisted mocks and the `vi.mock('@risk/connectors')` block:
```tsx
const { ..., mockUseTradingAccounts } = vi.hoisted(() => ({
  ...,
  mockUseTradingAccounts: vi.fn(),
}));

vi.mock('@risk/connectors', () => ({
  ...,
  useTradingAccounts: mockUseTradingAccounts,
}));
```

**Default in `beforeEach`** (replaces the removed `mockUseSessionServices.mockReturnValue` calls):
```tsx
mockUseTradingAccounts.mockReturnValue({
  data: [],
  isLoading: false,
  isFetching: false,
  isError: false,
  error: null,
});
```

For the second describe block (test line 152-164) that previously set up a SnapTrade connection with `account_id: 'acct-1'`, replace with:
```tsx
mockUseTradingAccounts.mockReturnValue({
  data: [
    { account_id: 'acct-1', account_name: 'Margin', brokerage_name: 'Broker', provider: 'snaptrade', cash_balance: 0, available_funds: 0, account_type: 'MARGIN', meta: {} },
  ],
  isLoading: false,
  isFetching: false,
  error: null,
});
```

#### T2. Add test: accounts from multiple providers (labels + trade preview flow)

This test must verify **both** that labels render correctly **and** that a non-SnapTrade `account_id` flows through to `useHedgeTradePreview`. The `useHedgeTradePreview` hook receives `{ hedgeTicker, suggestedWeight, accountId }` — confirming the IBKR account_id reaches the trade preview is critical because the whole point of this fix is multi-broker support.

**Test approach**: The T0 Select mock (see above) replaces the Radix UI `Select` primitives with plain `<div>` wrappers, eliminating the portal-based rendering that would otherwise prevent `screen.getByText()` from finding `SelectItem` children. With the mock in place, `SelectItem` children render directly in the document tree and are accessible to standard RTL queries. Without this mock, `SelectContent` renders via `SelectPrimitive.Portal` (`select.tsx:74`), placing children outside the test container.

```tsx
it('shows accounts from all providers and passes non-SnapTrade account_id to trade preview', async () => {
  const tradePreviewMutate = vi.fn();
  mockUseTradingAccounts.mockReturnValue({
    data: [
      { account_id: 'st-1', account_name: 'Joint', brokerage_name: 'Alpaca', provider: 'snaptrade', cash_balance: 0, available_funds: 0, account_type: 'JOINT', meta: {} },
      { account_id: 'ibkr-1', account_name: 'Individual', brokerage_name: 'Interactive Brokers', provider: 'ibkr', cash_balance: 0, available_funds: 0, account_type: 'INDIVIDUAL', meta: {} },
    ],
    isLoading: false,
    isFetching: false,
    isError: false,
    error: null,
  });
  mockUseHedgeTradePreview.mockReturnValue({
    mutate: tradePreviewMutate,
    isPending: false,
    error: null,
    reset: vi.fn(),
  });

  // Render at step 3 (trade execution step) — requires advancing through steps
  // ... render + advance to step 3 ...

  // Verify both labels render (works because T0 mock replaces portal-based
  // Select with plain divs — SelectItem children are in the document tree)
  await waitFor(() => {
    expect(screen.getByText(/Interactive Brokers/)).toBeInTheDocument();
    expect(screen.getByText(/Alpaca/)).toBeInTheDocument();
  });

  // Verify IBKR account_id flows to trade preview via single-account auto-select:
  // Re-render with only the IBKR account → auto-select triggers → trade preview fires
  mockUseTradingAccounts.mockReturnValue({
    data: [
      { account_id: 'ibkr-1', account_name: 'Individual', brokerage_name: 'Interactive Brokers', provider: 'ibkr', cash_balance: 0, available_funds: 0, account_type: 'INDIVIDUAL', meta: {} },
    ],
    isLoading: false,
    isFetching: false,
    isError: false,
    error: null,
  });
  // Force re-render to trigger auto-select effect (single account → auto-selects ibkr-1)
  // The trade preview useEffect at line ~357 fires when selectedAccountId is set

  await waitFor(() => {
    expect(tradePreviewMutate).toHaveBeenCalledWith(
      expect.objectContaining({ accountId: 'ibkr-1' }),
      expect.anything(),
    );
  });
});
```

#### T3. Add test: null account_name fallback

Verify that when `account_name` is null, the label falls back gracefully (brokerage_name only, or account_id if both are empty). Depends on T0 Select mock for `SelectItem` children to be queryable.
```tsx
it('renders brokerage_name-only label when account_name is null', async () => {
  mockUseTradingAccounts.mockReturnValue({
    data: [
      { account_id: 'acct-1', account_name: null, brokerage_name: 'Fidelity', provider: 'snaptrade', cash_balance: 0, available_funds: 0, account_type: 'INDIVIDUAL', meta: {} },
    ],
    isLoading: false,
    isFetching: false,
    isError: false,
    error: null,
  });

  // ... render + advance to step 3 ...

  await waitFor(() => {
    // With T0 mock, SelectItem content renders in-document (no portal)
    expect(screen.getByText('Fidelity')).toBeInTheDocument();
    // Ensure "null" is NOT rendered as a literal string in any label
    expect(screen.queryByText(/null/)).not.toBeInTheDocument();
  });
});
```

Also add a test for the double-null case:
```tsx
it('renders account_id fallback when both brokerage_name and account_name are null', async () => {
  mockUseTradingAccounts.mockReturnValue({
    data: [
      { account_id: 'acct-fallback', account_name: null, brokerage_name: null, provider: 'snaptrade', cash_balance: 0, available_funds: 0, account_type: 'INDIVIDUAL', meta: {} },
    ],
    isLoading: false,
    isFetching: false,
    isError: false,
    error: null,
  });

  // ... render + advance to step 3 ...

  await waitFor(() => {
    expect(screen.getByText('acct-fallback')).toBeInTheDocument();
  });
});
```

#### T4. Add test: single account auto-selects

Verify that when only one account is returned, it is auto-selected without user interaction.

#### T4b. Add test: stale selection is cleared

Verify that when `selectedAccountId` points to an account no longer in the list, it is cleared:
```tsx
it('clears stale selection when account list changes', async () => {
  // Start with one account → auto-selects acct-1
  mockUseTradingAccounts.mockReturnValue({
    data: [
      { account_id: 'acct-1', account_name: 'Main', brokerage_name: 'Alpaca', provider: 'snaptrade', cash_balance: 0, available_funds: 0, account_type: 'INDIVIDUAL', meta: {} },
    ],
    isLoading: false,
    isFetching: false,
    isError: false,
    error: null,
  });
  const { rerender } = render(/* ... advance to step 3 ... */);

  // Auto-select fires for single account → selectedAccountId = 'acct-1'
  // Now change the account list to a different single account
  mockUseTradingAccounts.mockReturnValue({
    data: [
      { account_id: 'acct-2', account_name: 'New', brokerage_name: 'IBKR', provider: 'ibkr', cash_balance: 0, available_funds: 0, account_type: 'INDIVIDUAL', meta: {} },
    ],
    isLoading: false,
    isFetching: false,
    isError: false,
    error: null,
  });
  rerender(/* ... */);

  // The C3 effect should: (1) detect acct-1 is no longer in list → clear selection,
  // (2) detect single account → auto-select acct-2
  await waitFor(() => {
    expect(screen.getByText(/IBKR/)).toBeInTheDocument();
    // Verify acct-1 is gone (no stale "Alpaca" reference)
    expect(screen.queryByText(/Alpaca/)).not.toBeInTheDocument();
    // Verify selectedAccountId was actually reset — the auto-selected acct-2
    // should flow through to trade preview, proving stale acct-1 was cleared
    expect(tradePreviewMutate).toHaveBeenCalledWith(
      expect.objectContaining({ accountId: 'acct-2' }),
      expect.anything(),
    );
  });
});
```

**Note on testing `selectedAccountId`**: `selectedAccountId` is internal `useState` — it cannot be set from outside the component. Tests must use auto-select (single account) or the Select mock's click handler to set it. The above test uses sequential auto-selects to verify the stale-clearing logic. This matches the `QuickTradeCard.tsx:224-226` and `OrdersCard.tsx:371-373` pattern.

#### T5. Update existing tests

Any test that currently sets up `getSnapTradeConnections` mock responses should be migrated to use `mockUseTradingAccounts` with `BrokerAccountResponse[]` data shape. The existing "blocks at step 3 when a short hedge preview returns no preview ids" test (line 114) currently mocks `getSnapTradeConnections` returning a connection — update it to use `mockUseTradingAccounts` with a `BrokerAccountResponse` array instead.

#### T6. Backend route tests for C6 auth change

Existing tests at `tests/routes/test_trading_api_routes.py:29` and `:98` only cover unauthenticated 401 and paid-user happy path. C6 changes `GET /api/trading/accounts` from `_require_paid_user` to `_require_authenticated_user`, but the plan has no backend test proving the new behavior works. Add two tests:

1. **Authenticated non-paid user gets 200 on `/api/trading/accounts`**: Send a request with a valid session cookie for a non-paid user and assert 200 (not 403). This proves the auth downgrade works.
2. **`/api/trading/preview` remains paid-gated (regression guard)**: Send a request to `POST /api/trading/preview` with the same non-paid user and assert 403. This ensures the auth change is scoped to the accounts endpoint only and actual trading actions stay behind the paid gate.

## Risk Assessment

### Low Risk
- **Backend is already correct**: `/api/trading/accounts` aggregates all providers. The only backend change is a one-line auth downgrade (C6: `_require_paid_user` → `_require_authenticated_user`).
- **Field mapping is straightforward**: `account_id`, `brokerage_name`, `account_name` exist on both shapes. The dialog only uses these three fields for display + the `accountId` for trade preview/execution.
- **Proven pattern**: 5 other components already use `useTradingAccounts()` successfully.
- **React Query caching**: The query key `['trading', 'accounts']` is shared with QuickTradeCard. `staleTime: 0` ensures React Query automatically refetches when `enabled` toggles true, so the dialog always gets fresh data without manual refetch effects.

### Edge Cases to Verify
1. **IBKR accounts in hedge flow**: The hedge trade preview/execute endpoints must support `account_id` values from IBKR and Schwab, not just SnapTrade `authorization_id`. Verify that `TradeExecutionService.preview_order()` routes correctly based on `account_id` (it does — `_resolve_target_account()` at `trade_execution_service.py:2838` resolves the account across all adapters, then `_resolve_broker_adapter()` at line 2915 finds the correct broker adapter for the resolved account_id; both are called at lines 287+293 in `preview_order()`). Note: `execute_order()` (line 1543) does NOT call `_resolve_target_account()`/`_resolve_broker_adapter()` — it routes via the stored preview row's `broker_provider` (line 1629) and `account_id` (line 1634), looking up the adapter directly from `self._adapters`. Lines 639+641 are in `preview_roll()`, not `execute_order()`. The `account_id` on SnapTrade connections is already the direct account ID (from `account.get("id")` at `connections.py:140`), not a cast from `authorization_id`.
2. **No accounts connected**: Already handled — the "No connected trading accounts found" notice renders when `accounts.length === 0`. No change needed.
3. **Loading state**: `useTradingAccounts` returns `isLoading: true` during fetch. The existing `accountsLoading` guard in JSX works because we alias `isLoading || isFetching` to `accountsLoading`.
4. **`enabled` gating**: Pass `enabled: open && step >= 3` so the query does not fire while the dialog is closed or the user is on an earlier step. This preserves the original step-scoped fetch behavior — broker API calls only happen when the user reaches the trade execution step. `staleTime: 0` ensures fresh data when `enabled` toggles true.
5. **Null `account_name`**: `BrokerAccount.account_name` is `Optional[str]` and SnapTrade can emit `None`. The label helper must filter falsy values and fall back to `account_id`. See C2.
6. **Paid tier gate**: Resolved — C6 downgrades `GET /api/trading/accounts` from `_require_paid_user` to `_require_authenticated_user`. All actual trading endpoints (`/preview`, `/execute`, `/cancel`) remain paid-gated.
7. **`resetWorkflow()` compilation**: All three removed `useState` setter calls (`setAccounts`, `setAccountsLoading`, `setAccountsError`) must also be removed from `resetWorkflow()` (lines 240-242). React Query manages the account data lifecycle — no manual reset needed.
8. **Stale account selection**: If the user opens the dialog, selects account A, closes the dialog, disconnects account A externally, and re-opens the dialog, `selectedAccountId` still holds account A's ID but `useTradingAccounts` returns a list without it. The C3 effect's invalid-selection clearing branch (matching `QuickTradeCard.tsx:224-226`) detects this and resets to `''`. Test T4b covers this scenario.

## Scope

- **Frontend** (2 files) + **Backend** (1 file, 1-line auth change) + **Tests** (1 backend test file) + **Docs** (1 file)
- ~55 lines removed (manual fetch logic + interfaces + `resetWorkflow` setter calls), ~20 lines added (hook + null-safe helper + auto-select effect)
- Net reduction in code

## Files Modified

| File | Change |
|------|--------|
| `routes/trading.py` | C6: Downgrade `/accounts` endpoint from `_require_paid_user` to `_require_authenticated_user` (1 line) |
| `frontend/packages/ui/src/components/portfolio/HedgeWorkflowDialog.tsx` | C1-C5: Replace SnapTrade API call with `useTradingAccounts()` hook, null-safe label, resetWorkflow cleanup |
| `frontend/packages/ui/src/components/portfolio/HedgeWorkflowDialog.test.tsx` | T0-T5: Update mocks, add Select mock, multi-provider + null label + account_id flow tests |
| `tests/routes/test_trading_api_routes.py` | T6: Backend route tests for auth downgrade (non-paid 200 on `/accounts`, paid-gate regression guard on `/preview`) |
| `docs/planning/completed/TIER_ENFORCEMENT_PLAN.md` | Update `GET /api/trading/accounts` tier from `PAID` to `AUTH` |

---

## Codex Review Resolution Log

### Finding 1: authorization_id claim is wrong (FIXED)
The plan originally stated "authorization_id cast to account_id". Investigation confirmed the dialog reads `account_id` directly at line 307 and the SnapTrade endpoint returns `account_id` as a direct field from `account.get("id")` at `connections.py:140`. The `authorization_id` is a separate field populated from `account.get("brokerage_authorization")` at line 138. Fixed the Response Shape Comparison and Root Cause sections to remove the incorrect cast claim.

### Finding 2: Missing resetWorkflow() cleanup (FIXED)
The plan removed three `useState` declarations but did not remove their setter calls in `resetWorkflow()` at lines 240-242. Added explicit instructions in C1 to remove `setAccounts([])`, `setAccountsLoading(false)`, and `setAccountsError(null)` from `resetWorkflow()`, with before/after code blocks. Added edge case #7 in Risk Assessment.

### Finding 3: Auth/tier mismatch (FIXED — Round 4)
`GET /api/trading/accounts` uses `_require_paid_user` (`routes/trading.py:123`). Current SnapTrade connections uses session auth only (`routes/snaptrade.py:672-676`). Hedge routes use `get_current_user` (`routes/hedging.py:225, 282`). The hedge backend is NOT tier-gated, so switching to `useTradingAccounts()` would newly block non-paid users at account loading (403). **Resolution**: Downgrade the accounts endpoint from `_require_paid_user` to `_require_authenticated_user` (1-line change). Account listing is read-only; all actual trading endpoints remain paid-gated. See C6.

### Finding 4: Label helper is weaker than current (FIXED)
The proposed `${brokerage_name} · ${account_name}` does not handle null `account_name`. Backend `BrokerAccount.account_name` is `Optional[str]` (`trade_objects.py:417`), and SnapTrade adapter passes `None` (`adapter.py:84`). The frontend `BrokerAccountResponse.account_name` is typed as `string` but runtime can be `null`. The current dialog filters empty values and falls back to `accountId` (lines 316-323). Rewrote C2 with a null-safe helper that filters falsy parts and falls back to `account_id`. Added edge case #5 and test T3. Also noted that the existing QuickTradeCard pattern has the same null-safety bug.

### Finding 5: Test plan incomplete (FIXED)
- Added T0: Select component mock requirement (matching `QuickTradeCard.test.tsx:25-31` pattern) — without this, Radix Select children don't render in jsdom.
- Updated T2: Now verifies both label rendering AND that a non-SnapTrade `account_id` flows into `useHedgeTradePreview` via `tradePreviewMutate` assertion.
- Added T3: Null `account_name` fallback test (no "null" text in DOM).
- Renumbered T3→T4, T4→T5.

---

### Round 2 Findings

### R2-F1: Label helper is not null-safe for brokerage_name (FIXED)
The C2 helper originally only considered null `account_name`. But `brokerage_name` can also be null at runtime — `BrokerAccount.brokerage_name` is a required `str` field, but the SnapTrade adapter falls back to `"SnapTrade"` string (`adapter.py:85`), while other adapters might not. More importantly, the runtime JSON can have `null` despite the TypeScript type saying `string`. Updated the helper to use explicit `?? ''` coercion on both `brokerage_name` and `account_name` before filtering. Added a double-null test case in T3 that verifies fallback to `account_id`.

### R2-F2: Auto-select doesn't clear invalid selection (FIXED)
The C3 effect only auto-selected when `accounts.length === 1`. It did not clear `selectedAccountId` when the query result changes and the previously selected account is no longer in the list. Both `QuickTradeCard.tsx:224-226` and `OrdersCard.tsx:371-373` handle this case with:
```tsx
if (selectedAccountId && !accounts.some(account => account.account_id === selectedAccountId)) {
  setSelectedAccountId('');
}
```
Updated C3 to include this invalid-selection clearing branch (matching both reference implementations). Added test T4b to verify the behavior.

### R2-F3: Inaccurate response mapping description (VERIFIED — ALREADY FIXED)
The plan already correctly states that the dialog reads `account_id` directly at line 307 (fixed in Round 1, Finding 1). The additional context from this round: the frontend `SnapTradeConnection` type at `SnapTradeService.ts:55` is stale — it does NOT include `account_id` as a field, which is why the dialog casts to `ConnectionWithAccountId` interface. The backend `/api/snaptrade/connections` endpoint does return `account_id` (from `connections.py:140`), but the TypeScript type doesn't reflect it. This stale type is a pre-existing issue that becomes irrelevant after this fix (the dialog will use `BrokerAccountResponse` from `useTradingAccounts()` instead).

### R2-F4: Test assertion won't work with portal-based Select (VERIFIED — ALREADY FIXED)
The T0 mock (added in Round 1, Finding 5) replaces Radix UI `Select` primitives with plain `<div>` wrappers, eliminating the `SelectPrimitive.Portal` at `select.tsx:74`. With this mock, `SelectItem` children render directly in the document tree. Updated T2 and T3 test descriptions to explicitly note this dependency and explain why `screen.getByText()` works (because portal is mocked out, not because options are naturally in the DOM).

### R2-F5: Wrong backend method reference (FIXED)
Edge case #1 cited `_resolve_adapter()` which does not exist. The actual methods are `_resolve_target_account()` (`trade_execution_service.py:2838`) and `_resolve_broker_adapter()` (`trade_execution_service.py:2915`). Updated the edge case description with correct method names and line numbers for `preview_order()` (lines 287+293). Note: lines 639+641 were incorrectly attributed to `execute_order()` — see R3-F2 for the full correction.

---

### Round 3 Findings

### R3-F1: C3 auto-select effect needs step guard (FIXED)
The proposed C3 effect ran ungated — React Query cached `accounts` data persists when `enabled` toggles to `false` (dialog closed or step < 3). When `resetWorkflow()` clears `selectedAccountId` at line 235→243, the C3 effect would immediately undo it because `accounts` is still a non-empty cached array. This would cause the trade-preview effect (line 356) to fire with a stale account on dialog reopen. Added `if (!open || step < 3) return;` guard to the C3 effect, plus `open` and `step` to the dependency array. This matches the gating pattern used by the existing SnapTrade fetch effect (`if (!open || step < 3) { return; }` at line 262 of the original code).

### R3-F2: Backend method reference still wrong in edge case #1 (FIXED)
R2-F5 corrected `_resolve_adapter()` to `_resolve_target_account()`/`_resolve_broker_adapter()`, but still attributed lines 639+641 to `execute_order()`. Those lines are actually in `preview_roll()` (starts at line 605). The actual `execute_order()` starts at line 1543 and does NOT call `_resolve_target_account()`/`_resolve_broker_adapter()` — it routes via the stored preview row's `broker_provider` (line 1629) and `account_id` (line 1634), looking up the adapter directly from `self._adapters`. Corrected edge case #1 to describe both routing mechanisms accurately.

### R3-F3: C5 dead imports — `useSessionServices` / `api` cleanup (FIXED)
The original C5 was a vague "verify whether any other code path still uses `api`" note. Verified: `api` is only used at three sites (lines 192, 299, 349), all within or supporting the removed SnapTrade fetch effect. Rewrote C5 with explicit removal instructions: delete `const { api } = useSessionServices()` at line 192, update the import at line 3 to remove `useSessionServices` (keep `type HedgeStrategy`), and remove the corresponding test mock wiring (`mockUseSessionServices` hoisted mock, `vi.mock` entry, and both `mockReturnValue` calls at test lines 76-79 and 152-155).

---

### Round 4 Findings

### R4-F1: Paid-gate conflict between C1 and C6 (FIXED)
C1 switches the dialog to `useTradingAccounts()`, which hits `GET /api/trading/accounts` (paid-gated at `routes/trading.py:123`). But C6 noted the hedge backend is NOT tier-gated (`get_current_user` only). Non-paid users would get a 403 on account loading — a regression. **Resolution**: Downgrade the `/api/trading/accounts` endpoint from `_require_paid_user` to `_require_authenticated_user` (already exists at `routes/trading.py:22-29`). Account listing is read-only — all actual trading endpoints (`/preview`, `/execute`, `/cancel`, `/status/{order_id}`) remain paid-gated. This is a 1-line backend change and requires zero frontend adjustments. Alternatives (new `/api/hedging/accounts` endpoint, 403 fallback logic) were rejected as unnecessarily complex. Rewrote C6 with the resolved approach, updated Scope/Files Modified/Risk Assessment to reflect the backend change, updated edge case #6 and Finding 3 status.

### R4-F2: C5 import snippet drops `useTradingAccounts` (FIXED)
The C5 "After" import removed `useSessionServices` but also dropped the `useTradingAccounts` import that C1 adds:
```tsx
// C5 Before (broken): import { type HedgeStrategy } from '@risk/connectors';
// C5 After  (fixed):  import { useTradingAccounts, type HedgeStrategy } from '@risk/connectors';
```
Also updated C1's import instruction to note that `useTradingAccounts` is consolidated into the C5 import rather than added as a separate line.

### R4-F3: Test mock cleanup contradiction (FIXED)
C5's test cleanup said to remove all `mockUseSessionServices` references, but T1 still had `mockUseSessionServices.mockReturnValue({ api: {} })` in its "After" block. **Resolution**: Rewrote T1 to explicitly list all `mockUseSessionServices` removal sites (hoisted mock line 7/12, vi.mock entry line 19, both mockReturnValue calls at lines 76-80 and 152-164). The T1 "After" no longer references `mockUseSessionServices`. Added a replacement `mockUseTradingAccounts` setup for the second describe block (previously setting up a SnapTrade connection with `account_id: 'acct-1'`). Updated C5's test cleanup to reference T1 instead of redescribing the same removals.

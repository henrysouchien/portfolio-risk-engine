# Spec: Rebalance Trade Execution

## Context

The Asset Allocation container has a working rebalance **preview** flow — users can set target allocations, generate rebalance trades, and see a table of proposed SELL/BUY legs. But there is **no way to execute the trades**. The "Execute" button is missing.

**What's built:**
- Backend: `preview_rebalance_trades(preview=False)` in `mcp_tools/rebalance.py` — computes SELL/BUY legs as `RebalanceLeg` objects with prices, quantities, values. When `preview=True` + `account_id`, adds per-leg `preview_id` via IBKR `TradeExecutionService.preview_order()`.
- Backend: `execute_basket_trade(preview_ids)` in `mcp_tools/basket_trading.py` — executes a list of preview IDs with best-effort semantics. Returns `BasketTradeExecutionResult` with `status` (completed/partial/failed/needs_confirmation), `execution_legs`, `reprieved_legs`, `summary`, `warnings`.
- REST: `POST /api/allocations/rebalance` — accepts `{target_weights, min_trade_value, account_id}` via `RebalanceTradesRequest`. Currently hardcodes `format="full"` and does NOT pass `preview` param.
- REST: `POST /api/baskets/execute` — accepts `{preview_ids: string[]}`, returns `BasketTradeExecutionResult.to_api_response()`.
- Frontend: `useRebalanceTrades()` in `connectors/features/allocation/hooks/` — mutation calling `api.generateRebalanceTrades(params)`.
- Frontend: `useBasketTradeExecute()` in `connectors/features/trading/hooks/useBasketTrade.ts` — mutation calling `api.executeBasketTrade({previewIds})`, invalidates `['trading', 'baskets']` on success.
- Frontend: `APIService.ts` already has `previewBasketTrade(BasketTradePreviewParams)` and `executeBasketTrade(BasketTradeExecuteParams)` where `BasketTradePreviewParams = {name, action, totalValue?, accountId?}` and `BasketTradeExecuteParams = {previewIds: string[]}`. Routes: `/api/baskets/preview`, `/api/baskets/execute`.
- Frontend: `AssetAllocationContainer` — orchestrates targets, preview, and display. Calls `rebalanceMutation.mutateAsync({target_weights, min_trade_value})` with NO `account_id`.
- Frontend: `AssetAllocation` component — renders trade preview table (ticker, side, qty, price, value, status).
- Frontend: `BasketsCard` — has full reprieve handling pattern (execute → check `needs_confirmation` → show re-confirm UI for reprieved legs with `new_preview_id`).

**What's missing:**
1. REST `/api/allocations/rebalance` does not accept `preview: true` — cannot get IBKR preview_ids through the REST API.
2. No "Execute" or "Execute All" button in the trade preview UI.
3. No account selection in the rebalance flow — `account_id` is required for both `preview=True` and for sell/rebalance basket actions.
4. No confirmation dialog before execution.
5. No execution status tracking or reprieve handling.

---

## Architecture Decision

**Three-step flow**: Generate rebalance legs first (fast, no IBKR call, no account needed), then on "Execute" click:
1. User clicks "Execute All" → confirmation dialog opens with account selector.
2. User selects account → clicks "Preview Orders" → calls `preview_rebalance_trades(preview=True, account_id)` to get account-scoped legs with IBKR `preview_id`s. The dialog updates to show the **actual account-scoped order set** (which may differ from the portfolio-wide preview if the user has multiple accounts).
3. User reviews the account-scoped preview → clicks "Confirm Execute" → pipes `preview_id`s into `execute_basket_trade()` via `POST /api/baskets/execute`.

This avoids touching `preview_basket_trade()` (which is basket-name-based, not arbitrary-leg-based) and reuses the existing execution path that BasketsCard already uses. The two-step confirmation (select account → preview → confirm) ensures the user always sees the exact orders that will be submitted.

**Account selection**: Add an account selector to the rebalance execution flow. The Trading section's `QuickTradeCard` uses an `accounts` prop + `selectedAccountId` pattern — follow the same approach.

---

## Files

| File | Action |
|------|--------|
| `app.py` | **Edit** — add `preview` field to `RebalanceTradesRequest`, pass to backend, return 200 for preview failures |
| `frontend/packages/chassis/src/services/APIService.ts` | **Edit** — add `preview` to params type + method body, add `BasketExecutionLeg`/`BasketExecutionResponse` types |
| `frontend/packages/chassis/src/services/index.ts` | **Edit** — re-export `BasketExecutionLeg`, `BasketExecutionResponse` from chassis barrel |
| `frontend/packages/connectors/src/features/allocation/hooks/useExecuteRebalance.ts` | **Create** — two-step mutation: preview-rebalance → execute |
| `frontend/packages/connectors/src/features/trading/hooks/useBasketTrade.ts` | **Edit** — update `useBasketTradeExecute` generic from `Record<string, unknown>` to `BasketExecutionResponse` |
| `frontend/packages/ui/src/components/dashboard/views/modern/trading/BasketsCard.tsx` | **Edit** — delete local execution types, import shared types from `@risk/chassis` |
| `frontend/packages/connectors/src/features/allocation/hooks/index.ts` | **Edit** — re-export `useExecuteRebalance` |
| `frontend/packages/connectors/src/index.ts` | **Edit** — add `useExecuteRebalance` to explicit allocation export line (line 18) |
| `frontend/packages/ui/src/components/portfolio/AssetAllocation.tsx` | **Edit** — add Execute button, execution result banner, reprieve UI, update types |
| `frontend/packages/ui/src/components/dashboard/views/modern/AssetAllocationContainer.tsx` | **Edit** — wire execution hooks, three-step confirmation dialog with account selector, reprieve handler |

---

## Step 1: Expose `preview` param through REST

**File: `app.py`**

The `RebalanceTradesRequest` model (line 774) needs a `preview` field. The endpoint handler (line 2581) needs to pass it through.

### 1a: Update request model

```python
class RebalanceTradesRequest(BaseModel):
    """Request model for generating rebalance trade legs."""
    target_weights: Dict[str, float]
    min_trade_value: float = 100.0
    account_id: Optional[str] = None
    preview: bool = False  # Add — when True, gets IBKR preview_ids per leg
```

### 1b: Pass `preview` to backend

In the endpoint handler (~line 2581), add `preview` to the call:

```python
rebalance_result = preview_rebalance_trades(
    target_weights=rebalance_request.target_weights,
    min_trade_value=rebalance_request.min_trade_value,
    account_id=rebalance_request.account_id,
    preview=rebalance_request.preview,  # Add
    format="full",
    user_email=user_email,
)
```

**Note**: Backend `preview_rebalance_trades()` already validates `account_id is required when preview=True` (line 91-92).

### 1c: Handle all-preview-failed without HTTP 400

When `preview=True` and ALL legs fail IBKR preview, the backend sets `status="error"` (line 354), and the REST endpoint converts that to HTTP 400 (line 2589). But the response body contains per-leg failure details (full `RebalanceTradeResult` with `trades`, `summary`, etc.) that the frontend needs. The `HttpClient` throws a generic `HTTP 400: Bad Request` error, losing the detail.

**Important**: The backend uses `status="error"` for two distinct cases:
1. **Validation errors** (lines 88-97) — early returns from `_error_response()` with bare `{status, error}` dict, no `trades` key.
2. **All-preview-failed** (line 354) — full `RebalanceTradeResult` with `trades` array containing per-leg failure details.

**Fix**: Distinguish the two by checking for the `trades` key (only present in case 2):

```python
rebalance_result = preview_rebalance_trades(...)

if str(rebalance_result.get("status")) == "error":
    # All-preview-failed: has trades with per-leg errors — return 200 so frontend
    # can render per-leg details. Validation errors lack 'trades' and stay 400.
    if rebalance_request.preview and "trades" in rebalance_result:
        return rebalance_result  # 200 with status="error" + per-leg details
    # Validation errors / non-preview errors remain 400
    raise HTTPException(status_code=400, detail={...})
```

This way the dialog can render per-leg failure reasons when all legs fail preview, while genuine validation errors (missing params, etc.) still return 400.

---

## Step 2: Update frontend API types

**File: `frontend/packages/chassis/src/services/APIService.ts`**

### 2a: Update `GenerateRebalanceTradesParams` (line 167)

```typescript
export interface GenerateRebalanceTradesParams {
  target_weights: Record<string, number>;
  min_trade_value?: number;
  account_id?: string;
  preview?: boolean;  // Add
}
```

### 2b: Update the `generateRebalanceTrades` method body (line 1062)

The current method only serializes `target_weights`, `min_trade_value`, and `account_id`. It does NOT spread params — it cherry-picks fields. Add `preview`:

```typescript
async generateRebalanceTrades(params: GenerateRebalanceTradesParams): Promise<RebalanceTradesResponse> {
  return this.http.request('/api/allocations/rebalance', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      target_weights: params.target_weights,
      min_trade_value: params.min_trade_value,
      account_id: params.account_id,
      preview: params.preview,  // Add
    }),
  });
}
```

### 2c: Add execution response types

Add these types near the existing `RebalanceTradesResponse` (after line 165):

```typescript
export interface BasketExecutionLeg {
  ticker: string;
  side: string;
  quantity: number | null;
  filled_quantity: number | null;
  average_fill_price: number | null;
  total_cost: number | null;
  order_status: string | null;
  brokerage_order_id: string | null;
  preview_id: string | null;
  error: string | null;
  new_preview_id: string | null;
}

/** Intentionally omits `agent_snapshot` (MCP-only field, not used by frontend UI). */
export interface BasketExecutionResponse {
  analysis_type: string;
  status: 'completed' | 'partial' | 'failed' | 'needs_confirmation';
  execution_legs: BasketExecutionLeg[];
  reprieved_legs: BasketExecutionLeg[];
  summary: {
    requested_legs: number;
    succeeded_legs: number;
    failed_legs: number;
    reprieved_legs: number;
    total_cost: number;
  };
  warnings: string[];
}
```

### 2e: Update `executeBasketTrade` return type

The existing `executeBasketTrade` method (line 1470) returns `Record<string, unknown>`. Update it to use the new shared type:

```typescript
async executeBasketTrade(params: BasketTradeExecuteParams): Promise<BasketExecutionResponse> {
  return this.http.request<BasketExecutionResponse>('/api/baskets/execute', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ preview_ids: params.previewIds }),
  });
}
```

This eliminates the `as unknown as BasketExecutionResponse` cast in the hook. Also update `useBasketTradeExecute` in `connectors/features/trading/hooks/useBasketTrade.ts` to use the new return type:

```typescript
// Line 28 — change from:
const mutation = useMutation<Record<string, unknown>, Error, BasketTradeExecuteParams>({
// To:
const mutation = useMutation<BasketExecutionResponse, Error, BasketTradeExecuteParams>({
```

Add to the file's import: `import type { BasketTradeExecuteParams, BasketExecutionResponse } from '@risk/chassis';`

**Required**: `BasketsCard.tsx` has duplicate local interfaces (`BasketExecutionLeg` at line 136, `BasketTradeExecutionResponseShape` at line 150, `getExecutionResponse` parser at line 485). After adding the shared types to `APIService.ts`:
1. Delete the local interfaces from `BasketsCard.tsx`
2. Import `BasketExecutionLeg` and `BasketExecutionResponse` from `@risk/chassis`
3. Update `getExecutionResponse` to return `BasketExecutionResponse` (or remove it if the typed API response makes it unnecessary)

### 2d: Re-export new types from chassis barrel

**File: `frontend/packages/chassis/src/services/index.ts`** — The chassis barrel uses an explicit `export type` list (line 72). Add the new types:

```typescript
export type {
  // ... existing types ...
  RebalanceTradeLeg,
  RebalanceTradesResponse,
  BasketExecutionLeg,        // Add
  BasketExecutionResponse,   // Add
  SetTargetAllocationsResponse,
  // ... etc ...
```

---

## Step 3: Create `useExecuteRebalance` hook

**File: `frontend/packages/connectors/src/features/allocation/hooks/useExecuteRebalance.ts`** (new)

This hook exposes two separate mutations: (1) `previewMutation` — re-generate rebalance with `preview=True` to get account-scoped legs with IBKR preview_ids, (2) `executeMutation` — pipe those preview_ids into basket execute. Splitting them allows the confirmation dialog to show the account-scoped preview before the user confirms.

```typescript
import { useMutation } from '@tanstack/react-query';
import type {
  RebalanceTradesResponse,
  BasketExecutionResponse,
} from '@risk/chassis';
import { useSessionServices } from '../../../providers/SessionServicesProvider';
import { useCurrentPortfolio } from '@risk/chassis';

export interface PreviewRebalanceParams {
  targetWeights: Record<string, number>;
  minTradeValue?: number;
  accountId: string;
}

export const useExecuteRebalance = () => {
  const { api, cacheCoordinator } = useSessionServices();
  const currentPortfolio = useCurrentPortfolio();
  const portfolioId = currentPortfolio?.id ?? null;

  // Step 1: Account-scoped preview — gets IBKR preview_ids per leg
  const previewMutation = useMutation<RebalanceTradesResponse, Error, PreviewRebalanceParams>({
    mutationFn: async ({ targetWeights, minTradeValue, accountId }) => {
      return api.generateRebalanceTrades({
        target_weights: targetWeights,
        min_trade_value: minTradeValue ?? 100,
        account_id: accountId,
        preview: true,
      });
    },
  });

  // Step 2: Execute previewed legs
  const executeMutation = useMutation<BasketExecutionResponse, Error, string[]>({
    mutationFn: async (previewIds) => {
      if (previewIds.length === 0) {
        throw new Error('No preview IDs to execute');
      }
      return api.executeBasketTrade({ previewIds });
    },
    onSuccess: async () => {
      if (portfolioId) {
        await cacheCoordinator.invalidateRiskData(portfolioId);
      }
    },
  });

  return {
    previewMutation,
    executeMutation,
  };
};
```

### 3b: Re-export from barrel

**File: `frontend/packages/connectors/src/features/allocation/hooks/index.ts`**

```typescript
export { useTargetAllocation } from './useTargetAllocation';
export { useSetTargetAllocation } from './useSetTargetAllocation';
export { useRebalanceTrades } from './useRebalanceTrades';
export { useExecuteRebalance } from './useExecuteRebalance';  // Add
export type { SetTargetAllocationParams } from './useSetTargetAllocation';
export type { PreviewRebalanceParams } from './useExecuteRebalance';  // Add
```

**File: `frontend/packages/connectors/src/index.ts`** — The top-level barrel uses explicit named exports (line 18), NOT wildcard re-exports. Add `useExecuteRebalance` to the existing allocation export line:

```typescript
// Line 18 — update from:
export { useTargetAllocation, useSetTargetAllocation, useRebalanceTrades } from './features/allocation';
// To:
export { useTargetAllocation, useSetTargetAllocation, useRebalanceTrades, useExecuteRebalance } from './features/allocation';
export type { PreviewRebalanceParams } from './features/allocation';
```

---

## Step 4: Add Execute button + execution UI to AssetAllocation

**File: `frontend/packages/ui/src/components/portfolio/AssetAllocation.tsx`**

### 4a: Update types

Add `preview_id` to the local `RebalanceTradeLeg` interface (line 12) to match the chassis type:

```typescript
interface RebalanceTradeLeg {
  ticker: string;
  side: 'BUY' | 'SELL';
  quantity: number;
  estimated_value: number;
  current_weight: number;
  target_weight: number;
  weight_delta: number;
  price: number;
  status: string;
  preview_id?: string | null;  // Add
  error?: string | null;
}
```

Update `RebalancePreview.summary` to include sell/buy values (line 25):

```typescript
interface RebalancePreview {
  status: string;
  summary: {
    trade_count: number;
    buy_count?: number;
    sell_count?: number;
    total_sell_value?: number;  // Add
    total_buy_value?: number;   // Add
    total_trade_value?: number;
    net_cash_impact?: number;
    [key: string]: unknown;
  };
  trades: RebalanceTradeLeg[];
  warnings?: string[];
}
```

### 4b: Add execution props to `AssetAllocationProps` (line 54)

```typescript
interface AssetAllocationProps {
  // ... all existing props unchanged ...
  onExecuteRebalance?: () => void;
  isExecuting?: boolean;
  executionStatus?: 'completed' | 'partial' | 'failed' | 'needs_confirmation' | null;
  executionSummary?: {
    requested_legs: number;
    succeeded_legs: number;
    failed_legs: number;
    reprieved_legs: number;
    total_cost: number;
  } | null;
  executionError?: string | null;         // Add — surfaces gateway/preview/execute errors
  reprievedCount?: number;
  onConfirmReprieved?: () => void;
  executeDisabledReason?: string | null;  // e.g., "Select an account to execute"
}
```

### 4c: Add Execute button after trade preview table

Insert after the warnings section (~line 407), before the closing `</>` of the `rebalancePreview` block:

```tsx
{/* Execute section */}
{rebalancePreview.trades.length > 0 && (
  <div className="flex items-center justify-between border-t border-neutral-200/60 pt-3 mt-2">
    <div className="text-xs text-neutral-500">
      {rebalancePreview.summary.sell_count ?? 0} sells
      {' '}${formatCurrency(rebalancePreview.summary.total_sell_value as number | undefined)}
      {' · '}
      {rebalancePreview.summary.buy_count ?? 0} buys
      {' '}${formatCurrency(rebalancePreview.summary.total_buy_value as number | undefined)}
    </div>
    <Button
      onClick={onExecuteRebalance}
      disabled={isExecuting || !onExecuteRebalance || !!executeDisabledReason}
      size="sm"
      className="bg-emerald-600 hover:bg-emerald-700 text-white"
      title={executeDisabledReason || undefined}
    >
      {isExecuting ? (
        <>
          <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
          Executing…
        </>
      ) : (
        'Execute All'
      )}
    </Button>
  </div>
)}
```

Add `Loader2` to the `lucide-react` import at line 2.

### 4d: Add execution result + reprieve display

After the execute button section:

```tsx
{/* Execution result */}
{executionStatus && executionSummary && (
  <div className={`mt-2 rounded-md px-3 py-2 text-xs ${
    executionStatus === 'completed'
      ? 'bg-emerald-50 border border-emerald-200 text-emerald-800'
      : executionStatus === 'needs_confirmation'
        ? 'bg-blue-50 border border-blue-200 text-blue-800'
        : executionStatus === 'partial'
          ? 'bg-amber-50 border border-amber-200 text-amber-800'
          : 'bg-red-50 border border-red-200 text-red-800'
  }`}>
    <span className="font-medium">
      {executionSummary.succeeded_legs}/{executionSummary.requested_legs} legs executed
    </span>
    {executionSummary.failed_legs > 0 && (
      <span className="ml-2">({executionSummary.failed_legs} failed)</span>
    )}
    {executionSummary.total_cost > 0 && (
      <span className="ml-2">· ${formatCurrency(executionSummary.total_cost)}</span>
    )}
  </div>
)}

{/* Execution error — gateway offline, preview failures, execute failures */}
{executionError && (
  <div className="mt-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
    {executionError}
  </div>
)}

{/* Reprieve handling — show when reprieved legs exist, regardless of overall status.
   Backend returns "needs_confirmation" when ALL legs are reprieved, but "partial" when
   reprieved legs are mixed with succeeded/failed. Match BasketsCard pattern: key off
   reprievedCount, not executionStatus. */}
{(reprievedCount ?? 0) > 0 && onConfirmReprieved && (
  <div className="mt-2 rounded-md border border-blue-200 bg-blue-50 px-3 py-2">
    <div className="flex items-center justify-between">
      <div className="text-xs text-blue-800">
        <span className="font-medium">Prices changed</span> on {reprievedCount} leg{reprievedCount === 1 ? '' : 's'}.
        Re-confirm to continue.
      </div>
      <Button
        size="sm"
        variant="outline"
        onClick={onConfirmReprieved}
        disabled={isExecuting}
        className="border-blue-300 text-blue-700 hover:bg-blue-100"
      >
        Re-confirm
      </Button>
    </div>
  </div>
)}
```

---

## Step 5: Wire execution in AssetAllocationContainer

**File: `frontend/packages/ui/src/components/dashboard/views/modern/AssetAllocationContainer.tsx`**

### 5a: Imports

Update the existing `@risk/connectors` import (line 2-8) to add new hooks:

```typescript
import {
  useRebalanceTrades,
  useRiskAnalysis,
  useSessionServices,
  useSetTargetAllocation,
  useTargetAllocation,
  useExecuteRebalance,      // Add
  useTradingAccounts,       // Add
  useBasketTradeExecute,    // Add
} from '@risk/connectors';
import type { BasketExecutionResponse } from '@risk/chassis';  // Add
import { Button } from '../../../ui/button';  // Add if not already imported
```

The current container imports `useSessionServices` but only destructures `eventBus`. Update to also get `cacheCoordinator`:

```typescript
const { eventBus, cacheCoordinator } = useSessionServices();
```

Add `portfolioId` (same pattern as `useSetTargetAllocation`):

```typescript
const currentPortfolioForId = useCurrentPortfolio();  // If not already available
const portfolioId = currentPortfolioForId?.id ?? null;
```

**Note**: `currentPortfolio` is already available from `useRiskAnalysis()` (line 118). Reuse it:

```typescript
const portfolioId = (currentPortfolio as { id?: string } | null)?.id ?? null;
```

### 5b: Add state + hooks

After `const rebalanceMutation = useRebalanceTrades();` (line 126):

```typescript
const { previewMutation, executeMutation } = useExecuteRebalance();
const reprieveMutation = useBasketTradeExecute();
const [showConfirmation, setShowConfirmation] = useState(false);
const [selectedAccountId, setSelectedAccountId] = useState('');
const [reprievedPreviewIds, setReprievedPreviewIds] = useState<string[]>([]);
const [lastPreviewTargets, setLastPreviewTargets] = useState<Record<string, number>>({});
const [latestExecution, setLatestExecution] = useState<BasketExecutionResponse | null>(null);
```

### 5c: Account data

The rebalance flow needs broker accounts for execution. Reuse the existing `useTradingAccounts()` hook from `@risk/connectors` (used by `QuickTradeCard`, `BasketsCard`, etc.). This queries `['trading', 'accounts']` → `api.getTradingAccounts()` → `GET /api/trading/accounts` (route in `routes/trading.py:113`), returning `BrokerAccountResponse[]`.

```typescript
import { useTradingAccounts } from '@risk/connectors';

// Inside the component — destructure loading/error state to distinguish from empty:
const { data: accounts = [], isLoading: accountsLoading, error: accountsError } = useTradingAccounts();
```

Use these states in `executeDisabledReason`:
```typescript
accountsLoading
  ? 'Loading accounts…'
  : accountsError
    ? 'Failed to load broker accounts'
    : accounts.length === 0
      ? 'No broker accounts available'
      : null
```

Auto-select when there's only one account:

```typescript
useEffect(() => {
  if (accounts.length === 1 && !selectedAccountId) {
    setSelectedAccountId(accounts[0].account_id);
  }
}, [accounts, selectedAccountId]);
```

### 5d: Save preview targets and clear stale state

In the existing `handleGenerateRebalance` (line 301), clear stale execution state **before** the async call (so resets happen even if the new preview fails), then save the targets after success:

```typescript
// BEFORE the mutateAsync call — always runs regardless of outcome:
setLatestExecution(null);
setReprievedPreviewIds([]);
previewMutation.reset();
executeMutation.reset();
reprieveMutation.reset();

try {
  await rebalanceMutation.mutateAsync({ target_weights: tickerTargets, min_trade_value: 100 });
  // Save the targets that produced this preview (only on success)
  setLastPreviewTargets(tickerTargets);
} catch {
  // Mutation error exposed through rebalanceMutation.error
}
```

### 5d2: Account-scoped preview handler (dialog step 1)

When the user selects an account in the confirmation dialog and clicks "Preview Orders":

```typescript
const handlePreviewForAccount = useCallback(async () => {
  if (!selectedAccountId || Object.keys(lastPreviewTargets).length === 0) return;

  try {
    await previewMutation.mutateAsync({
      targetWeights: lastPreviewTargets,
      minTradeValue: 100,
      accountId: selectedAccountId,
    });
  } catch {
    // Error surfaced via previewMutation.error
  }
}, [selectedAccountId, lastPreviewTargets, previewMutation]);
```

### 5d3: Execute handler (dialog step 2)

After the user reviews the account-scoped preview and clicks "Confirm Execute":

```typescript
const handleConfirmExecute = useCallback(async () => {
  const previewData = previewMutation.data;
  if (!previewData) return;

  // Extract preview_ids from successfully previewed legs
  const previewIds = (previewData.trades ?? [])
    .filter((leg) => leg.preview_id && leg.status === 'previewed')
    .map((leg) => leg.preview_id!);

  if (previewIds.length === 0) return;  // Button should be disabled in this case

  try {
    const result = await executeMutation.mutateAsync(previewIds);
    setLatestExecution(result);

    // Handle reprieve
    const reprieved = (result.reprieved_legs ?? [])
      .map((leg) => leg.new_preview_id)
      .filter((id): id is string => !!id);
    setReprievedPreviewIds(reprieved);

    // Close dialog for all terminal states — result banners + reprieve UI are
    // rendered outside the dialog in AssetAllocation, so the user sees outcomes.
    // Only keep dialog open if the mutation itself threw (caught below).
    setShowConfirmation(false);
  } catch {
    // Error surfaced via executeMutation.error
  }
}, [previewMutation.data, executeMutation]);
```

### 5e: Reprieve re-confirmation handler

Uses the `reprieveMutation` (already declared in Step 5b via `useBasketTradeExecute()`) to get proper mutation state and cache invalidation. This is the same hook `BasketsCard` uses.

```typescript
const handleConfirmReprieved = useCallback(async () => {
  if (reprievedPreviewIds.length === 0) return;

  try {
    const result = await reprieveMutation.mutateAsync({ previewIds: reprievedPreviewIds });

    // Check if the re-confirm itself produced more reprieved legs
    const newReprieved = (result.reprieved_legs ?? [])
      .map((leg) => leg.new_preview_id)
      .filter((id): id is string => !!id);
    setReprievedPreviewIds(newReprieved);

    setLatestExecution(result);

    // Invalidate risk data after re-confirm execution
    if (portfolioId) {
      await cacheCoordinator.invalidateRiskData(portfolioId);
    }
  } catch {
    // Error surfaced via reprieveMutation.error
  }
}, [reprievedPreviewIds, reprieveMutation, portfolioId, cacheCoordinator]);
```

### 5f: Confirmation dialog

The dialog has two phases: (1) select account + preview orders, (2) review account-scoped preview + confirm execute.

```tsx
{showConfirmation && (() => {
  const accountPreview = previewMutation.data;
  const previewedLegs = (accountPreview?.trades ?? []).filter(
    (leg) => leg.preview_id && leg.status === 'previewed'
  );
  const failedPreviewLegs = (accountPreview?.trades ?? []).filter(
    (leg) => leg.status === 'preview_failed'
  );
  const hasAccountPreview = !!accountPreview;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-xl p-6 max-w-lg mx-4 max-h-[80vh] overflow-y-auto">
        <h3 className="text-lg font-semibold mb-2">Confirm Rebalance Execution</h3>

        {/* Phase 1: Account selection */}
        {accounts.length > 1 && (
          <div className="mb-4">
            <label className="text-sm font-medium text-neutral-700 mb-1 block">Execute in account:</label>
            <select
              value={selectedAccountId}
              onChange={(e) => {
                setSelectedAccountId(e.target.value);
                previewMutation.reset();  // Clear stale account preview
              }}
              className="w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm"
              disabled={executeMutation.isPending}
            >
              <option value="">Select account…</option>
              {accounts.map((acc) => (
                <option key={acc.account_id} value={acc.account_id}>
                  {acc.account_name || acc.account_id} ({acc.brokerage_name})
                </option>
              ))}
            </select>
          </div>
        )}

        {/* Phase 1 → 2 transition: Preview Orders button */}
        {!hasAccountPreview && (
          <>
            <p className="text-sm text-neutral-600 mb-4">
              Preview will generate account-scoped orders via IBKR for{' '}
              {rebalanceMutation.data?.summary?.trade_count ?? 0} trade legs.
            </p>
            {previewMutation.error && (
              <div className="mb-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
                {previewMutation.error.message}
              </div>
            )}
            <div className="flex gap-3 justify-end">
              <Button variant="outline" onClick={() => setShowConfirmation(false)}>Cancel</Button>
              <Button
                className="bg-blue-600 text-white hover:bg-blue-700"
                onClick={handlePreviewForAccount}
                disabled={!selectedAccountId || previewMutation.isPending}
              >
                {previewMutation.isPending ? 'Previewing…' : 'Preview Orders'}
              </Button>
            </div>
          </>
        )}

        {/* Phase 2: Show account-scoped preview + confirm */}
        {hasAccountPreview && (
          <>
            <div className="text-sm mb-3 space-y-1 p-3 bg-neutral-50 rounded-lg">
              <div className="font-medium">
                {previewedLegs.length} of {accountPreview.trades.length} legs ready
              </div>
              <div>Sells: ${(accountPreview.summary?.total_sell_value ?? 0).toLocaleString()}</div>
              <div>Buys: ${(accountPreview.summary?.total_buy_value ?? 0).toLocaleString()}</div>
            </div>

            {/* Show per-leg details */}
            <div className="mb-3 space-y-1 max-h-40 overflow-y-auto">
              {(accountPreview.trades ?? []).map((leg) => (
                <div
                  key={`${leg.ticker}-${leg.side}`}
                  className="flex justify-between text-xs px-2 py-1 rounded border border-neutral-200 bg-white"
                >
                  <span className="font-medium">{leg.ticker}</span>
                  <span className={leg.side === 'SELL' ? 'text-amber-700' : 'text-blue-700'}>{leg.side}</span>
                  <span>{leg.quantity}</span>
                  <span className={leg.status === 'previewed' ? 'text-emerald-700' : 'text-red-700'}>
                    {leg.status === 'previewed' ? 'Ready' : leg.error || 'Failed'}
                  </span>
                </div>
              ))}
            </div>

            {/* Warning for partial preview failures */}
            {failedPreviewLegs.length > 0 && (
              <div className="mb-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                {failedPreviewLegs.length} leg{failedPreviewLegs.length === 1 ? '' : 's'} failed IBKR preview
                and will be skipped: {failedPreviewLegs.map((l) => l.ticker).join(', ')}
              </div>
            )}

            {executeMutation.error && (
              <div className="mb-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
                {executeMutation.error.message}
              </div>
            )}

            <p className="text-xs text-neutral-500 mb-4">
              This will submit {previewedLegs.length} market order{previewedLegs.length === 1 ? '' : 's'} through IBKR.
              This action cannot be undone.
            </p>
            <div className="flex gap-3 justify-end">
              <Button variant="outline" onClick={() => setShowConfirmation(false)}>Cancel</Button>
              <Button
                className="bg-emerald-600 text-white hover:bg-emerald-700"
                onClick={handleConfirmExecute}
                disabled={executeMutation.isPending || previewedLegs.length === 0}
              >
                {executeMutation.isPending ? 'Executing…' : `Execute ${previewedLegs.length} Orders`}
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
})()}
```

### 5g: Track latest execution response for UI

Since both the initial execute and re-confirm flows produce execution responses, maintain a single source of truth:

```typescript
const [latestExecution, setLatestExecution] = useState<BasketExecutionResponse | null>(null);
```

Update `handleConfirmExecute` to set it (already shown in Step 5d3 — `setLatestExecution(result)` after `executeMutation.mutateAsync()`).

Update `handleConfirmReprieved` to set it (already shown in Step 5e — `setLatestExecution(result)` after `reprieveMutation.mutateAsync()`).

### 5h: Pass execution props to `AssetAllocation`

The Execute button must be disabled while editing (targets may not match the displayed preview). The `executeDisabledReason` prop handles this:

```tsx
<AssetAllocation
  // ... all existing props unchanged ...
  onExecuteRebalance={() => {
    previewMutation.reset();  // Clear stale account-scoped preview from previous dialog open
    executeMutation.reset();
    setShowConfirmation(true);
  }}
  isExecuting={executeMutation.isPending || reprieveMutation.isPending}
  executionStatus={latestExecution?.status ?? null}
  executionSummary={latestExecution?.summary ?? null}
  executionError={
    (executeMutation.error instanceof Error ? executeMutation.error.message : null)
    ?? (reprieveMutation.error instanceof Error ? reprieveMutation.error.message : null)
  }
  reprievedCount={reprievedPreviewIds.length}
  onConfirmReprieved={reprievedPreviewIds.length > 0 ? handleConfirmReprieved : undefined}
  executeDisabledReason={
    isEditing
      ? 'Save targets before executing'
      : !rebalanceMutation.data?.trades?.length
        ? 'No trades to execute'
        : accountsLoading
          ? 'Loading accounts…'
          : accountsError
            ? 'Failed to load broker accounts'
            : accounts.length === 0
              ? 'No broker accounts available'
              : null
  }
/>
```

---

## Verification

```bash
cd frontend && npx tsc --noEmit  # Zero TS errors
```

Visual checks at localhost:3000 (requires IBKR Gateway running):

1. Set target allocations → save → click "Rebalance" → see preview table (existing flow, unchanged)
2. "Execute All" button visible below preview table. Disabled with tooltip if no broker accounts.
3. Click Execute All → confirmation dialog with trade summary + account selector (if multiple accounts)
4. Select account (auto-selected if only one) → Confirm Execute
5. Spinner on button → two-step: preview with IBKR → execute → result banner
6. **Completed**: green banner with leg count + total cost
7. **Partial**: amber banner with succeeded/failed counts
8. **Failed**: red banner with error details
9. **Needs confirmation (reprieve)**: blue banner with re-confirm button for price-changed legs
10. After execution, risk data invalidated via `cacheCoordinator.invalidateRiskData()`

**Edge cases:**
- IBKR Gateway offline → preview step fails → error surfaced via mutation.error
- All legs fail IBKR preview → dialog shows "0 of N legs ready" + per-leg failure reasons in amber banner. Execute button disabled.
- Multi-account user → must select account in confirmation dialog before executing
- Single-account user → account auto-selected, selector hidden

---

## Summary

| What | Action |
|------|--------|
| `app.py` — `RebalanceTradesRequest` | Add `preview: bool = False`, pass to backend (~3 lines) |
| `APIService.ts` — types | Add `preview`/`account_id` to params, add `BasketExecutionLeg`/`BasketExecutionResponse` types (~30 lines) |
| `useExecuteRebalance.ts` | New hook (~60 lines) — preview-rebalance → extract preview_ids → execute |
| `allocation/hooks/index.ts` | Re-export new hook (~2 lines) |
| `AssetAllocation.tsx` | Add Execute button, result banner, reprieve UI, update types (~60 lines) |
| `AssetAllocationContainer.tsx` | Wire hook + confirmation dialog + account selector + reprieve handler (~80 lines) |
| **Net new code** | **~235 lines** |
| **Prerequisite** | IBKR Gateway must be running for live execution |

### Codex Review Finding Coverage

| # | Finding | Resolution |
|---|---------|------------|
| 1 | `preview_basket_trade` is basket-name-based, not arbitrary-leg | Switched to `preview_rebalance_trades(preview=True)` which previews arbitrary legs |
| 2 | REST paths wrong (`/api/trading/basket/*`) | Corrected: `/api/allocations/rebalance` for preview, `/api/baskets/execute` for execution |
| 3 | Response shapes wrong | Using actual `BasketTradeExecutionResult.to_api_response()` shape with `execution_legs`, `reprieved_legs`, `summary` |
| 4 | Multi-account unresolved | Account selector via `useTradingAccounts()` (existing hook, `['trading', 'accounts']` query key), auto-select if single account |
| 5 | Missing reprieve handling | Reprieve UI keyed on `reprievedCount > 0` (not just `needs_confirmation` status), matching BasketsCard pattern. Re-confirm uses `useBasketTradeExecute` mutation with cache invalidation. |
| 6 | REST `/api/allocations/rebalance` doesn't expose `preview` | Step 1 adds `preview` field to `RebalanceTradesRequest` and passes through |
| 7 | `APIService.ts` method signatures mismatch | Not changing existing `previewBasketTrade`/`executeBasketTrade` — using `generateRebalanceTrades` + existing `executeBasketTrade` instead |
| 8 | `AssetAllocation.tsx` types missing fields | Step 4a adds `preview_id`, `total_sell_value`, `total_buy_value` |
| 9 | Hook export path incomplete | Step 3b exports from `allocation/hooks/index.ts` + explicit named export added to `connectors/src/index.ts` line 18 |
| 10 | Cache invalidation uses wrong keys | Using `cacheCoordinator.invalidateRiskData(portfolioId)` matching existing `useSetTargetAllocation` pattern |

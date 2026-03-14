# Codex Spec: Refresh Button UX Feedback (T2 #3)

**Goal:** Refresh button should give clear visual feedback — bigger spinner, success/error toast, last-updated tooltip.

---

## Context & Key Facts

- `ViewControlsHeader.tsx` is 53 lines total. The `RefreshCw` icon is on **line 39** with `w-3 h-3`.
- `button.tsx` applies `[&_svg]:size-4` globally on all buttons, which forces child SVGs to `size-4` (16px). The explicit `w-3 h-3` (12px) on the icon fights this — Tailwind specificity means the last utility wins, but `[&_svg]:size-4` uses a descendant selector that can override depending on cascade. To guarantee our intended size, use `!w-4 !h-4` with the important modifier.
- `refetch()` in `useDataSource.ts` (line 147-149) is fire-and-forget: `() => { void query.refetch(); }`. It returns `void`, not a Promise. You **cannot** `await refetch()` and place a toast after it.
- `usePortfolioSummary` already exposes `isRefetching` (from `resolved.isRefetching`). This transitions `false→true→false` during a refetch cycle. Use a `useEffect` on `isRefetching` to detect completion and fire the toast.
- `data.summary.lastUpdated` is already built in the container (line 228) as part of `portfolioOverviewData`. To get it to `ViewControlsHeader`, we pass it as a lightweight `lastUpdated` prop through `PortfolioOverview` (see Step 3a).
- `PortfolioOverview.tsx` already imports `TooltipProvider` and wraps its entire render. The overview barrel (`./overview`) already re-exports `ViewControlsHeader`. The tooltip components are at `../../ui/tooltip` relative to `ViewControlsHeader.tsx`.
- This codebase uses **relative imports** within `@risk/ui`. Package-path imports like `@risk/ui/hooks/use-toast` do not exist. Sibling containers (e.g., `HoldingsViewModernContainer.tsx`, `RiskSettingsContainer.tsx`) import toast as:
  ```ts
  import { toast } from '../../../../hooks/use-toast';
  ```
- The `toast()` function can be imported standalone (no hook needed) for fire-and-call usage. Use `toast()` not `useToast()` in the container.
- `<Toaster />` is already mounted in `App.tsx` (line 173). No setup needed.

---

## Step 1: Increase spinner size in ViewControlsHeader

**File:** `frontend/packages/ui/src/components/portfolio/overview/ViewControlsHeader.tsx`

**Line 39** — Change the `RefreshCw` className to use `!w-4 !h-4` (important modifier overrides the button's `[&_svg]:size-4`):

```diff
-          <RefreshCw className={`w-3 h-3 mr-1 ${loading ? "animate-spin" : ""}`} />
+          <RefreshCw className={`!w-4 !h-4 mr-1 ${loading ? "animate-spin" : ""}`} />
```

Also update the `Brain` icon (line 29) and `Settings` icon (line 48) to `!w-4 !h-4` for visual consistency within the control bar.

---

## Step 2: Add success/error toast on refresh completion

**File:** `frontend/packages/ui/src/components/dashboard/views/modern/PortfolioOverviewContainer.tsx`

### Why not `await refetch()`?

`usePortfolioSummary().refetch` delegates to `useDataSource`'s refetch, which is:
```ts
refetch: () => {
  void query.refetch();
},
```
This is fire-and-forget (returns `void`). Placing a toast after calling it would fire immediately, not on completion.

### Correct approach: `manualRefreshRef` + watch `isRefetching` transition

`usePortfolioSummary` exposes `isRefetching` (backed by TanStack Query's `isRefetching`). It goes `false → true → false` during a refetch. However, refetches can also be triggered by event-driven cache invalidation (lines 112, 124) or error retry (line 189), not just manual refresh. A bare `wasRefetchingRef` would fire a toast for ALL refetches, including background ones.

**Solution:** Use a `manualRefreshRef` that is ONLY set to `true` inside `handleRefresh()`. The `useEffect` checks `manualRefreshRef.current && !isRefetching` to fire the toast only for manual user-initiated refreshes.

**Changes:**

1. Add import (relative path, matching sibling containers):
```ts
import { toast } from '../../../../hooks/use-toast';
```

2. Add `useRef` to the React import:
```ts
import React, { useEffect, useMemo, useRef, useState } from 'react';
```

3. Destructure `isRefetching` from `usePortfolioSummary()` (add to existing destructure at line 63):
```ts
const {
  data,
  isLoading,
  isRefetching,     // ← add this
  error,
  ...
} = usePortfolioSummary();
```

4. Add a ref + effect after the existing hooks (after line 73, before the smartAlerts hooks):
```ts
// Track manual refresh for toast feedback (not background refetches)
const manualRefreshRef = useRef(false);

useEffect(() => {
  if (manualRefreshRef.current && !isRefetching) {
    manualRefreshRef.current = false;
    if (error) {
      toast({
        title: 'Refresh failed',
        description: 'Some data sources may be unavailable.',
        variant: 'destructive',
      });
    } else {
      toast({
        title: 'Portfolio refreshed',
        description: `Updated ${new Date().toLocaleTimeString()}`,
      });
    }
  }
}, [isRefetching, error]);
```

5. Set `manualRefreshRef.current = true` inside `handleRefresh` (line ~165), BEFORE the refetch call:
```ts
const handleRefresh = async () => {
  manualRefreshRef.current = true;
  try {
    const result = await IntentRegistry.triggerIntent('refresh-holdings');
    if (result.success) {
      await refetch();
    }
  } catch {
    await refetch();
  }
};
```

6. Wire `isRefetching` into the button loading state. In the `<PortfolioOverview>` JSX (line ~246), change:
```diff
-        loading={isLoading}
+        loading={isLoading || isRefetching}
```
This makes the refresh button spinner animate during the actual data refetch, not just on initial load.

**Why this works:** When the user clicks Refresh, `handleRefresh` sets `manualRefreshRef.current = true` then calls `refetch()`. TanStack Query sets `isRefetching=true`, then `false` on completion. The `useEffect` fires only when `manualRefreshRef.current` is true AND `isRefetching` transitions to false — meaning it fires exactly once per manual refresh. Background refetches (event-driven invalidation, error retry) never set the ref, so no spurious toasts.

---

## Step 3: Add last-updated tooltip to refresh button

### 3a. Thread `lastUpdated` into ViewControlsHeader

`data.summary.lastUpdated` is already available inside `PortfolioOverview` via the `data` prop (the container builds it at line 228). Rather than adding a separate `lastUpdated` prop to `PortfolioOverviewProps`, `PortfolioOverview` simply reads `data?.summary?.lastUpdated` directly and passes it to `ViewControlsHeader`.

**File:** `frontend/packages/ui/src/components/portfolio/PortfolioOverview.tsx`

Pass `lastUpdated` to `ViewControlsHeader` from existing data:
```diff
         <ViewControlsHeader
           showAIInsights={showAIInsights}
           onToggleAIInsights={() => setShowAIInsights(!showAIInsights)}
           onRefresh={handleDataRefresh}
           onOpenSettings={() => setSettingsPanelOpen(true)}
           loading={loading}
+          lastUpdated={data?.summary?.lastUpdated}
         />
```

No new prop on `PortfolioOverviewProps` needed. No container changes needed — the data is already in the tree.

### 3b. Add Tooltip in ViewControlsHeader

**File:** `frontend/packages/ui/src/components/portfolio/overview/ViewControlsHeader.tsx`

Add imports and prop:
```diff
-import { Brain, RefreshCw, Settings } from "lucide-react"
-
-import { Button } from "../../ui/button"
+import { Brain, RefreshCw, Settings } from "lucide-react"
+
+import { Button } from "../../ui/button"
+import { Tooltip, TooltipContent, TooltipTrigger } from "../../ui/tooltip"
```

Add `lastUpdated` to the interface:
```diff
 interface ViewControlsHeaderProps {
   showAIInsights: boolean
   onToggleAIInsights: () => void
   onRefresh: () => void
   onOpenSettings: () => void
   loading: boolean
+  lastUpdated?: string
 }
```

Destructure it:
```diff
 export function ViewControlsHeader({
   showAIInsights,
   onToggleAIInsights,
   onRefresh,
   onOpenSettings,
-  loading
+  loading,
+  lastUpdated
 }: ViewControlsHeaderProps) {
```

Wrap the refresh `<Button>` in a Tooltip (note: `TooltipProvider` is already rendered by the parent `PortfolioOverview`):
```tsx
<Tooltip>
  <TooltipTrigger asChild>
    <Button
      variant="ghost"
      size="sm"
      onClick={onRefresh}
      disabled={loading}
      className="text-xs"
    >
      <RefreshCw className={`!w-4 !h-4 mr-1 ${loading ? "animate-spin" : ""}`} />
      Refresh
    </Button>
  </TooltipTrigger>
  <TooltipContent>
    {lastUpdated
      ? `Last updated: ${new Date(lastUpdated).toLocaleTimeString()}`
      : "Click to refresh portfolio data"}
  </TooltipContent>
</Tooltip>
```

---

## Files Changed (Summary)

| File | Change |
|------|--------|
| `overview/ViewControlsHeader.tsx` | Tooltip wrapper, `!w-4 !h-4` icons, `lastUpdated` prop |
| `portfolio/PortfolioOverview.tsx` | Pass `data?.summary?.lastUpdated` to `ViewControlsHeader` |
| `modern/PortfolioOverviewContainer.tsx` | `isRefetching` destructure, `manualRefreshRef` + toast effect, `loading={isLoading \|\| isRefetching}` |

## Verification

```bash
cd frontend && npx tsc --noEmit && npx vitest run --reporter=verbose 2>&1 | tail -20
```

## Design Decisions

1. **`manualRefreshRef` — manual-only toasts** — Since `refetch()` is void (fire-and-forget), we cannot await it. Watching `isRefetching` transition `true→false` is the idiomatic TanStack Query approach. However, refetches also fire from event-driven cache invalidation (lines 112, 124) and error retry (line 189). Using a bare `wasRefetchingRef` would toast on ALL refetches. The `manualRefreshRef` is only set inside `handleRefresh()`, so the effect only fires toasts for user-initiated refreshes.
2. **`loading={isLoading || isRefetching}`** — Wiring `isRefetching` into the button loading prop makes the spinner animate during the actual data fetch, giving clear visual feedback that the refresh is in progress.
3. **`!w-4 !h-4` important modifier** — `button.tsx` applies `[&_svg]:size-4` which sets both width and height to 16px via a descendant selector. Without `!important`, our inline classes may lose depending on CSS cascade order. The `!` prefix in Tailwind ensures our explicit size wins.
4. **`lastUpdated` from existing data** — `data.summary.lastUpdated` is already in the component tree (built at line 228 of the container, passed via the `data` prop). `PortfolioOverview` reads it directly as `data?.summary?.lastUpdated` and passes it to `ViewControlsHeader` — no new prop on `PortfolioOverviewProps` needed.
5. **`toast()` function import, not `useToast()` hook** — Sibling containers (`HoldingsViewModernContainer`, `RiskSettingsContainer`) use the direct `toast()` function import. The hook is only needed if you want to read current toast state. We only need to fire toasts, so the function import is correct.

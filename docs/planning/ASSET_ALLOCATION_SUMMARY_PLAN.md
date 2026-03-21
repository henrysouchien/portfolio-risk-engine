# Asset Allocation — Read-Only Overview Card

## Context
The Overview's Asset Allocation card embeds the full `AssetAllocationContainer` (643 lines) with target editing, rebalance trade generation, order execution, and account selection. This is a complete trading workflow crammed into a dashboard summary. The same component is already available as a dedicated tool in Scenarios → Rebalance.

## Codex Findings (all addressed)
1. **Fixed:** Navigation — `setActiveView('scenarios')` + `setActiveTool('rebalance')` for deep-link
2. **Clarified:** Removes UI complexity, not query weight
3. **Fixed:** Transform — extract to neutral shared location alongside `AssetAllocation.tsx`
4. **Fixed:** Target fallback — merges `useTargetAllocation()` with `item.target_pct`
5. **Fixed:** State handling — thin container with loading/error/no-data
6. **Fixed:** Component boundary — it's a container
7. **Fixed:** Verification — verify rebalance tool opens directly
8. **Fixed:** No duplicate row rendering — add `readOnly` prop to existing `AssetAllocation` component. When true, hide tabs/edit/rebalance UI. Reuse same rows.
9. **Fixed:** Transform location — `frontend/packages/ui/src/components/portfolio/assetAllocationTransform.ts` (domain home, neutral between cards and views)
10. **Fixed:** Export `AllocationItem` interface from `AssetAllocation.tsx` so the shared transform can type its return value
11. **Fixed:** Wrap summary in `DashboardErrorBoundary` (matches current container pattern)
12. **Fixed:** Targets are non-blocking — summary renders allocations from `useRiskAnalysis()` immediately, enriches with targets from `useTargetAllocation()` when available. Does not block on target query loading/error

## Plan

### Change 1: Add `readOnly` prop to `AssetAllocation.tsx`

**File:** `frontend/packages/ui/src/components/portfolio/AssetAllocation.tsx`

Export `AllocationItem` interface (currently private). Add `readOnly?: boolean` to `AssetAllocationProps`. When `readOnly=true`:
- Hide tab toggle buttons (Allocation / Performance)
- Hide "Set Targets" and "Rebalance" header buttons
- Hide edit mode UI (target inputs, save/cancel)
- Hide rebalance preview section
- Keep allocation rows with: color dot, category, percentage, dollar value, day change, target badge, drift status, GradientProgress bar
- Add "Manage Allocation" button at the bottom (only when `readOnly=true`)

This reuses ALL existing row rendering, badge formatting, progress bars. Zero duplication.

The `onManageAllocation?: () => void` callback prop handles navigation — the container provides the implementation.

### Change 2: Extract shared transform utility

**New file:** `frontend/packages/ui/src/components/portfolio/assetAllocationTransform.ts`

Extract the allocation transform logic from `AssetAllocationContainer` lines 109-172 into a pure function:
```typescript
export function transformAllocations(
  rawAllocations: any[],
  targetAllocations: Record<string, number> | null,
): AllocationItem[]
```

Handles: color mapping, label formatting, target merging with `item.target_pct` fallback, drift calculation, negative-cash-as-margin.

### Change 3: Create `AssetAllocationSummary` thin container

**New file:** `frontend/packages/ui/src/components/dashboard/cards/AssetAllocationSummary.tsx`

A thin container (~80 lines) wrapped in `DashboardErrorBoundary`:

**Hooks:**
- `useRiskAnalysis()` — allocation data (cached) — **primary, drives loading/error states**
- `useTargetAllocation()` — saved targets (read-only) — **non-blocking enrichment, does not gate rendering**
- `useUIStore()` — navigation

**State handling (driven by `useRiskAnalysis()` only):**
- Loading → skeleton card
- Error → error message with retry
- No data → placeholder

**Target enrichment:** When `useTargetAllocation()` returns data, merge into allocations. When it's still loading or fails, render allocations without targets (drift badges omitted). Does NOT block on target query.

**Renders:**
```tsx
<DashboardErrorBoundary>
  <AssetAllocation
    allocations={transformedAllocations}
    readOnly
    onManageAllocation={handleManageAllocation}
  />
</DashboardErrorBoundary>
```

**Navigation:**
```tsx
const handleManageAllocation = () => {
  setActiveView('scenarios');
  setActiveTool('rebalance');
};
```

### Change 4: Update `AssetAllocationContainer` to use shared transform

**File:** `frontend/packages/ui/src/components/dashboard/views/modern/AssetAllocationContainer.tsx`

Replace inline transform logic (lines 109-172) with:
```tsx
import { transformAllocations } from '../../../portfolio/assetAllocationTransform';
```

No behavioral change — same input, same output. Container keeps all mutation hooks and edit/rebalance UI.

### Change 5: Replace on Overview

**File:** `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx`

Replace:
```tsx
<div className="hover-lift-premium animate-magnetic-hover">
  <AssetAllocationContainer />
</div>
```

With:
```tsx
<AssetAllocationSummary />
```

### Change 6: Export from cards barrel

**File:** `frontend/packages/ui/src/components/dashboard/cards/index.ts`

Add export for `AssetAllocationSummary`.

## Files Modified
1. `frontend/packages/ui/src/components/portfolio/AssetAllocation.tsx` — add `readOnly` prop, hide tabs/edit/rebalance when true, add "Manage Allocation" button
2. `frontend/packages/ui/src/components/portfolio/assetAllocationTransform.ts` — **NEW** (shared transform)
3. `frontend/packages/ui/src/components/dashboard/cards/AssetAllocationSummary.tsx` — **NEW** (thin container)
4. `frontend/packages/ui/src/components/dashboard/views/modern/AssetAllocationContainer.tsx` — use shared transform
5. `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx` — swap for summary
6. `frontend/packages/ui/src/components/dashboard/cards/index.ts` — export

## Files NOT Modified
- `ScenariosRouter.tsx` — no changes
- `uiStore.ts` — no changes (setActiveTool already exists)

## Verification
1. `cd frontend && npx tsc --noEmit` — no type errors
2. Visual: Overview shows read-only allocation (no tabs, no edit, no rebalance)
3. "Manage Allocation" opens Scenarios → Rebalance tool directly
4. Scenarios → Rebalance still works with full workflow
5. Allocation rows, targets, drift badges match between Overview and Scenarios
6. Loading/error states render on Overview
7. Bottom grid `items-start` still works

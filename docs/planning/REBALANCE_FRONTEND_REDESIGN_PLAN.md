# Rebalance Frontend Redesign Plan

## Context

The backend for rebalance diagnostic + target setting shipped (`606bd06a`). Three new data sources are available: asset-class risk attribution (`asset_class_risk` in risk analysis response), allocation presets (`GET /api/allocations/presets`), and diagnostic flags (in rebalance agent/REST response). This plan builds the frontend to consume that data.

**Goal**: Transform the rebalance tool from a bare trade generator into a 3-phase diagnostic + decision + execution flow, matching the design quality of other audited scenario tools (Monte Carlo, Backtest, Optimization, What-If).

---

## Prerequisite: Expose `asset_class_risk` Through Frontend Adapter

The backend emits `asset_class_risk` in `to_api_response()` (`core/result_objects/risk.py:1405`), but the frontend adapter/types don't pass it through. Must update:

1. **`frontend/packages/chassis/src/catalog/types.ts`** (~line 112): Add `asset_class_risk` to the risk analysis response type:
   ```ts
   asset_class_risk?: {
     risk_contributions: Array<{
       asset_class: string; risk_pct: number; weight_pct: number;
       risk_weight_ratio: number | null;
       top_contributors: Array<{ ticker: string; risk_pct: number }>;
     }>;
     factor_betas: Record<string, Record<string, number>>;
   };
   ```
2. **`frontend/packages/connectors/src/adapters/RiskAnalysisAdapter.ts`** (~line 162, 279): Pass `asset_class_risk` through in both input/output mapping (no transformation needed, just forwarding the raw object).
3. **`frontend/packages/connectors/src/adapters/RiskAnalysisAdapter.ts`** (~line 540): Also pass through `analysis_metadata.asset_classes` (the ticker → asset class mapping, type `Record<string, string>`). The backend emits it at `core/result_objects/risk.py:1402`, but the adapter currently doesn't surface it. Add to `RiskAnalysisSourceData` type alongside `asset_class_risk`. Needed for "From Optimizer" ticker-to-asset-class aggregation.
4. **`frontend/packages/chassis/src/services/APIService.ts`**: Add `AllocationPresetsResponse` type:
   ```ts
   interface AllocationPreset {
     id: string; name: string; description: string;
     risk_level: number | null;
     allocations: Record<string, number>;
   }
   interface AllocationPresetsResponse {
     status: string; presets: AllocationPreset[];
     count: number; portfolio_name: string;
   }
   ```

---

## Component Architecture

```
tools/
├── RebalanceTool.tsx              ← Top-level lazy entrypoint (matches *Tool.tsx pattern)
└── rebalance/
    ├── RebalanceDiagnostic.tsx    ← Phase 1: Risk-informed allocation health
    │   ├── AllocationHealthCard.tsx
    │   ├── RiskWeightChart.tsx
    │   └── FactorDriverStrip.tsx
    ├── RebalanceTargets.tsx       ← Phase 2: Preset selection + customization
    │   ├── PresetSelector.tsx
    │   ├── AllocationCompare.tsx
    │   └── TargetEditor.tsx
    ├── RebalanceResults.tsx       ← Phase 3: Trade preview + actions
    │   ├── RebalanceInsightCard.tsx
    │   ├── TradeSummaryStrip.tsx
    │   ├── TradeTable.tsx
    │   └── RebalanceActionBar.tsx
    └── RebalanceExecution.tsx     ← Execution flow (account selection, preview, reprieve)
```

**Location**: `frontend/packages/ui/src/components/portfolio/scenarios/tools/`

Top-level `RebalanceTool.tsx` is at `tools/RebalanceTool.tsx` (matching `WhatIfTool.tsx`, `OptimizeTool.tsx` pattern). Subcomponents go in `tools/rebalance/` directory.

**Execution flow preservation**: `RebalanceExecution.tsx` extracts the existing account selection modal, preview-by-account, execution, and reprieve/re-confirm logic from `AssetAllocationContainer.tsx` (lines 231-546). This is NOT new — it's a lift-and-refactor of existing code. The existing `AssetAllocationContainer.tsx` stays for non-scenario allocation views.

---

## Phase 1: Diagnostic — "What's wrong with my allocation?"

Renders immediately on load using data from `useRiskAnalysis()` (already called). No user action needed.

### AllocationHealthCard

Uses shared `ScenarioInsightCard` (from `scenarios/shared/ScenarioInsightCard.tsx`). The actual props are `icon`, `title`, `body`, `colorScheme`, `size`, `actionLabel`, `secondaryActionLabel`, `onAction`, `onSecondaryAction`:

```tsx
<ScenarioInsightCard
  size="lg"
  icon={AlertTriangle}   // Component TYPE, not element — no JSX angle brackets
  title="Allocation Health"
  body={topImbalance.message}
  colorScheme={hasCompliance ? "red" : hasImbalance ? "amber" : "emerald"}
  secondaryActionLabel="Ask AI about this"
  onSecondaryAction={handleAskAI}
/>
```

Color scheme tokens are `"red"`, `"amber"`, `"emerald"`, `"neutral"` (defined in `insight-banner.tsx:10`). The component hardcodes `variant="glass"` internally — do not pass a variant prop. Icon prop takes a component type (e.g., `AlertTriangle`), not a JSX element.

**Verdict logic** (computed from `asset_class_risk.risk_contributions`):
1. If compliance violations: "Rebalancing needed to resolve N compliance violations"
2. If any class has `risk_weight_ratio > 1.2`: "Real Estate contributes 43% of risk at 32% weight (1.3x ratio)"
3. If all balanced: "Allocation is well-balanced — no significant risk/weight imbalances"

**Loading state**: Gate on `useRiskAnalysis()` `isLoading` / `hasData` flags (matching `AssetAllocationContainer.tsx` line 444 pattern). Show a skeleton or "Loading allocation health..." until data arrives.

**Data source**: `riskAnalysis.data.asset_class_risk.risk_contributions` — passthrough from adapter (see Prerequisite section above).

### RiskWeightChart

New component. Horizontal diverging bar chart using Recharts `BarChart` with `layout="vertical"`:

- Two bar series per asset class: `risk_pct` (warm/amber fill) and `weight_pct` (asset class theme color)
- Sorted by `risk_weight_ratio` descending (worst imbalances first)
- Each row labeled with asset class name on left, percentages on right
- When `risk_pct > weight_pct`, the risk bar extends further — the visual gap IS the problem
- Container: `variant="glassTinted"` card, chart height = `asset_class_count * 64px`

**Data source**: `riskAnalysis.data.asset_class_risk.risk_contributions`

### FactorDriverStrip

Compact inline badges below the chart:

- For each asset class with `risk_weight_ratio > 1.0`, show top 2 factor betas
- Format: `RE: interest_rate 1.4 · market 1.26`
- `bg-muted/40` inline badges, `text-xs font-mono`
- Skip well-balanced classes

**Data source**: `riskAnalysis.data.asset_class_risk.factor_betas`

---

## Phase 2: Target Selection — "What should I rebalance to?"

### PresetSelector

Horizontal scrollable card row:

- Each preset: `min-w-[140px] p-3 rounded-xl border cursor-pointer`
- Shows: name, risk level (dot indicator 1-8), top-line allocation split
- Active: `ring-2 ring-primary bg-primary/5`
- Cards:
  - "Current Targets" — if saved targets exist (from `useTargetAllocation()`)
  - 6 strategy templates — from `useAllocationPresets()` hook
  - "From Optimizer" — shown only when `scenarioContext` has weights. Since workflow context passes **ticker-level weights** (not asset-class), this preset needs a ticker-to-asset-class aggregation step: group `scenarioContext.weights` by asset class using the `asset_classes` mapping from risk analysis metadata, sum weights per class, display as an allocation preset. When selected for trade generation, pass the original ticker weights directly to the API (bypass asset-class decomposition).
  - "Custom" — opens inline editor
- Selecting a preset populates `AllocationCompare` below

**Data source**: New `useAllocationPresets()` hook → `GET /api/allocations/presets`

### AllocationCompare

Appears when a preset is selected:

- Grid: asset class name | current % | arrow | target % | delta
- Delta colored: green for reduction in overweight, red for increase
- `bg-muted/40 rounded-xl p-4` container
- "Generate Trades" primary button at bottom
- **Trade generation**: When the user clicks "Generate Trades" with an asset-class preset selected, the frontend sends `asset_class_targets` directly to the backend API (using the new param shipped in the backend plan) instead of doing client-side ticker decomposition. The existing `buildTickerTargetWeights()` in `AssetAllocationContainer` is no longer needed for this path. For "From Optimizer" (ticker-level weights), send `target_weights` directly. Add `include_diagnostics: true` to get diagnostic flags in the response.

### TargetEditor

Refinement of existing `AssetAllocation` edit mode:

- Only shown when "Custom" selected or user clicks "Edit" on a preset
- Compact input rows matching compare layout
- Total validation badge (100% ±0.5%)
- "Save as Targets" option to persist via `useSetTargetAllocation()`

---

## Phase 3: Trade Preview — "What trades does this require?"

Rendered after "Generate Trades" triggers `useRebalanceTrades()`.

### RebalanceInsightCard

Uses `ScenarioInsightCard`:

- Narrative: "24 trades to reduce Real Estate from 32%→10% and increase Equity from 46%→60%"
- Computed from trade data: identify the 2 biggest asset class shifts
- Includes diagnostic flags from backend response (`diagnostic_flags` array)
- Severity from flags: error (compliance) > warning (imbalance) > success

### TradeSummaryStrip

Horizontal metric row (matching optimization's impact strip):

| Sells | Buys | Net Cash | Turnover |
|-------|------|----------|----------|
| 5 · $32.6K | 19 · $38.5K | -$5.8K | 44% |

- Uses metric tile pattern: `text-xs uppercase tracking label`, `text-lg font-semibold value`
- Single row with dividers

### TradeTable

Enhanced from current raw table:

- **Columns**: Ticker, Side (BUY/SELL badge), Qty, Price, Est. Value, Current Weight, Target Weight, Delta Weight
- **Sorting**: By `estimated_value` descending within sell/buy groups
- **Row tinting**: Sells get `bg-red-50/50 dark:bg-red-950/20`, buys get `bg-green-50/50 dark:bg-green-950/20`
- **Remove "computed" status column** — every row says "computed", dead visual weight
- Uses `DataTable` component from `components/blocks/data-table.tsx` (the higher-level table used by other scenario tools like `WeightChangesTable.tsx` in optimize), not the raw `Table` primitive
- Skipped trades: collapsible disclosure at bottom ("3 trades skipped")

**Data source**: `rebalanceMutation.data.trades` — `current_weight`, `target_weight`, `weight_delta` are already on each `RebalanceLeg` from the backend.

### RebalanceActionBar

Footer with exit ramps (matching optimization's 3-button pattern):

- "What-If" — navigates to What-If passing **complete portfolio target weights** as `{ weights: tickerTargets }` in `toolContext`. The source of these weights depends on the input mode:
  - **Ticker-level input** (From Optimizer): use the original `target_weights` dict that was sent to the API (stored in component state as `lastPreviewTargets`). This is complete.
  - **Asset-class preset input**: the API's `asset_class_targets` decomposition produces complete ticker weights internally. However, the `trades` array may omit zero-delta and below-threshold legs, so it is NOT a reliable source. Instead, reconstruct complete weights by: taking current `portfolio_weights` from risk analysis, then applying each trade's `weight_delta` to get the target state. Alternatively, compute from the preset's asset-class percentages + current holdings proportions (same logic as `_decompose_asset_class_targets` but client-side for the handoff only).
  - Matches the `OptimizeTool.tsx:617` pattern for the `toolContext` shape.
- "Simulate Outcomes" — navigates to Monte Carlo with weights
- "Go to Trading" — navigates to Trading view
- Right-aligned "Execute" button (primary, gated by account selection modal)

---

## New Hook: useAllocationPresets

**File**: `frontend/packages/connectors/src/features/allocation/hooks/useAllocationPresets.ts`

```tsx
export const useAllocationPresets = (portfolioName?: string) => {
  const { api } = useSessionServices();
  return useQuery({
    queryKey: ['allocation-presets', portfolioName ?? 'CURRENT_PORTFOLIO'],
    queryFn: () => api.getAllocationPresets(portfolioName),
    staleTime: 5 * 60 * 1000,
  });
};
```

**APIService addition** in `frontend/packages/chassis/src/services/APIService.ts` (the real service, not the connectors re-export):
```ts
async getAllocationPresets(portfolioName?: string): Promise<AllocationPresetsResponse> {
  const params = new URLSearchParams();
  if (portfolioName) params.set('portfolio_name', portfolioName);
  return this.http.request(`/api/allocations/presets?${params.toString()}`);
}
```
Follow the existing `APIService` pattern using `this.http.request()` + `URLSearchParams` (see `getStrategyTemplates()` at line ~815 for reference).

**Export**: Add to `features/allocation/hooks/index.ts`

---

## State Management

Follow the existing scenario tool pattern using `toolRunParams` in `uiStore.ts` with `runPortfolioId` + `runId` scoping (matching `usePortfolioOptimization`, `useWhatIfAnalysis`, `useStressTest`):

```tsx
// toolRunParams['rebalance'] stores:
{
  selectedPresetId: string | null,
  customTargets: Record<string, number> | null,
  runPortfolioId: string | null,
  runId: string | null,
}
```

Since `useRebalanceTrades()` is a mutation (not a query), trade results are stored in mutation state (not React Query cache). On remount, the hook reinitializes — so the `runId` + `toolRunParams` store the selected preset/targets, and the user re-triggers "Generate Trades" if needed. This matches how other mutation-based tools handle persistence.

---

## Router Integration

**File**: `frontend/packages/ui/src/components/portfolio/scenarios/ScenariosRouter.tsx`

- Change rebalance from direct import to `React.lazy()` (matching other tools)
- Point to new `RebalanceTool` component instead of `AssetAllocationContainer`
- Pass `scenarioContext` as prop (unchanged)

The existing `AssetAllocationContainer` remains available for non-scenario allocation views.

---

## Typography & Card Hierarchy

| Element | Style |
|---------|-------|
| Phase headers | `text-lg font-semibold` with `border-t pt-6 mt-6` separator |
| ScenarioInsightCard verdict | `text-base` body |
| Metric tile label | `text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground` |
| Metric tile value | `text-lg font-semibold` |
| Preset card name | `text-sm font-medium` |
| Table headers | `text-xs font-medium text-muted-foreground` |
| Table values | `text-sm tabular-nums` |

| Section | Card Treatment |
|---------|---------------|
| AllocationHealthCard | ScenarioInsightCard (hardcodes `variant="glass"` internally) |
| RiskWeightChart | `variant="glassTinted"` wrapper card |
| PresetSelector | Plain cards with `ring-2 ring-primary` on selection |
| AllocationCompare | `bg-muted/40 rounded-xl` containment |
| TradeSummaryStrip | Inline, no card wrapper |
| TradeTable | DataTable component (no card variant needed) |

---

## Implementation Sequence

| Phase | Work | Files |
|-------|------|-------|
| 1 | New hook + APIService method | `hooks/useAllocationPresets.ts`, `APIService.ts` |
| 1 | RebalanceTool orchestrator shell | `tools/RebalanceTool.tsx` |
| 2 | Phase 1 components (diagnostic) | `AllocationHealthCard.tsx`, `RiskWeightChart.tsx`, `FactorDriverStrip.tsx` |
| 2 | Phase 1 container | `RebalanceDiagnostic.tsx` |
| 3 | Phase 2 components (targets) | `PresetSelector.tsx`, `AllocationCompare.tsx`, `TargetEditor.tsx` |
| 3 | Phase 2 container | `RebalanceTargets.tsx` |
| 4 | Phase 3 components (results) | `RebalanceInsightCard.tsx`, `TradeSummaryStrip.tsx`, `TradeTable.tsx`, `RebalanceActionBar.tsx` |
| 4 | Phase 3 container | `RebalanceResults.tsx` |
| 5 | Router update + state persistence | `ScenariosRouter.tsx`, Zustand toolRunParams |
| 6 | Tests | Component tests for each phase |

---

## Critical Files

| File | Changes |
|------|---------|
| `frontend/packages/chassis/src/catalog/types.ts` | Add `asset_class_risk` to risk analysis type |
| `frontend/packages/connectors/src/adapters/RiskAnalysisAdapter.ts` | Pass through `asset_class_risk` in input/output |
| `frontend/packages/chassis/src/services/APIService.ts` | `getAllocationPresets()` method |
| `frontend/packages/connectors/src/features/allocation/hooks/useAllocationPresets.ts` | New hook |
| `frontend/packages/connectors/src/features/allocation/hooks/index.ts` | Export new hook |
| `frontend/packages/ui/src/components/portfolio/scenarios/tools/RebalanceTool.tsx` | New top-level lazy entrypoint (at `tools/` level, NOT inside `tools/rebalance/`) |
| `frontend/packages/ui/src/components/portfolio/scenarios/tools/rebalance/` | New subdirectory for ~10 subcomponent files |
| `frontend/packages/ui/src/components/portfolio/scenarios/ScenariosRouter.tsx` | Lazy-load RebalanceTool |

## Existing Code to Reuse

- `ScenarioInsightCard` from `scenarios/shared/ScenarioInsightCard.tsx` — diagnostic + results insight cards
- `DataTable` component from `components/blocks/data-table.tsx` — trade table (higher-level, used by other scenario tools)
- `useRiskAnalysis()` — already called, provides `asset_class_risk` data
- `useTargetAllocation()` / `useSetTargetAllocation()` — existing target CRUD
- `useRebalanceTrades()` / `useExecuteRebalance()` — existing trade generation + execution
- `useScenarioState()` — for toolRunParams persistence
- `useWorkflowStepCompletion()` — scenario workflow reporting
- Recharts `BarChart` with `layout="vertical"` — for risk/weight chart (used in other tools)
- `assetAllocationTransform.ts` — existing allocation data transformer

## Verification

1. **TypeScript**: `npx tsc --noEmit` — zero errors
2. **Browser**: Navigate to `#scenarios/rebalance`:
   - Phase 1 renders with risk/weight data on load
   - Preset selector shows presets (count varies: 6 templates + current_targets if saved + From Optimizer if context + Custom)
   - Selecting a preset shows before/after comparison
   - "Generate Trades" produces trade table with weight columns
   - Exit ramps navigate to correct tools with context
3. **State persistence**: Navigate away and back — selected preset and custom targets preserved (trade results require re-running "Generate Trades" since they're mutation state)
4. **Scenario context**: Navigate from Optimization → Rebalance — imported weights show as "From Optimizer" preset

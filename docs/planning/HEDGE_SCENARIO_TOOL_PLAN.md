# Hedge Scenario Tool

## Context

We decoupled the hedge workflow from the Risk Drivers tab (now purely analytical). The hedge infrastructure is all intact but unwired from the UI. This creates a dedicated Hedge tool in the Scenarios page, following the existing tool pattern, and wires the "Simulate hedge" button to it.

## Existing infrastructure to reuse

- **`HedgeWorkflowDialog.tsx`** (779 lines) — full 4-step flow. Takes `HedgeStrategy` prop. No changes needed.
- **`useHedgingRecommendations(weights, portfolioValue)`** — fetches recommendations. Returns `{ data: HedgeStrategy[], loading, error, hasData }`.
- **`StressTestTool.tsx`** already has hedge recommendation fetch + display logic (lines 136-171). This is the reference pattern for how to get weights and display the best hedge.

## Changes

### Step 1: Add `'hedge'` to `ScenarioToolId` type

**File:** `frontend/packages/connectors/src/stores/uiStore.ts` (line 81)

Add `'hedge'` to the type union:

```typescript
export type ScenarioToolId =
  | 'landing'
  | 'what-if'
  | 'optimize'
  | 'backtest'
  | 'stress-test'
  | 'monte-carlo'
  | 'rebalance'
  | 'tax-harvest'
  | 'hedge';  // NEW
```

### Step 2: Add breadcrumb label

**File:** `frontend/packages/ui/src/components/portfolio/scenarios/shared/ToolBreadcrumb.tsx` (line 8)

Add to the exhaustive `TOOL_LABELS` map:

```typescript
const TOOL_LABELS: Record<SelectableScenarioTool, string> = {
  // ... existing entries ...
  'hedge': 'Hedge Analysis',
};
```

### Step 3: Create HedgeTool component

**File:** `frontend/packages/ui/src/components/portfolio/scenarios/tools/HedgeTool.tsx` (new)

Follow the `StressTestTool` pattern exactly for props, portfolio data access, and hedge hook usage.

**Import paths** (verified):
- `useScenarioState` from `../../scenario/useScenarioState` (at `portfolio/scenario/useScenarioState.ts`)
- `HedgeWorkflowDialog` from `../../HedgeWorkflowDialog` (at `portfolio/HedgeWorkflowDialog.tsx`)
- `useStressTest`, `useHedgingRecommendations` from `@risk/connectors`
- `HedgeStrategy` type from `@risk/connectors`

**Props** (same as all tools):
```typescript
interface HedgeToolProps {
  context: Record<string, unknown>;
  onNavigate: (tool: SelectableScenarioTool, context?: Record<string, unknown>) => void;
}
```

**Portfolio weights + value** — follow StressTestTool exactly (lines 98-146):

```typescript
// useStressTest() gives currentPortfolio with total_portfolio_value
const stressTest = useStressTest();

// useScenarioState() gives initialPositions (derived from positions hook)
const { initialPositions } = useScenarioState({
  whatIfData: undefined,
  stressTestData: undefined,
  monteCarloResult: undefined,
  runStressTest: () => {},
  runMonteCarlo: () => {},
  currentPortfolioId: stressTest.currentPortfolio?.id,
});

// Derive weights from positions (same as StressTestTool line 136-142)
const hedgingWeights = useMemo(
  () => Object.fromEntries(
    initialPositions
      .filter((p) => p.ticker.trim().length > 0 && Number.isFinite(p.weight))
      .map((p) => [p.ticker.toUpperCase(), p.weight / 100] as const)
  ),
  [initialPositions]
);

const portfolioValue = stressTest.currentPortfolio?.total_portfolio_value;
```

Note: `useStressTest()` is used solely for `currentPortfolio` — the stress test functionality itself is not invoked.

**Fetch recommendations:**
```typescript
const { data: strategies, loading, error, hasData } =
  useHedgingRecommendations(hedgingWeights, portfolioValue);
```

**Selected hedge + dialog:**
```typescript
const [selectedHedge, setSelectedHedge] = useState<HedgeStrategy | null>(null);
```

**Rendering** — show a list of all strategy cards (not just the best one like StressTestTool does). Each card shows:
- `strategy` label (e.g., "Hedge Financial - Mortgages exposure")
- `hedgeTicker` (the ETF)
- `efficiency` badge (High/Medium/Low)
- `cost` + `protection` strings
- `details.riskReduction` percentage
- `details.marketImpact.beforeVaR` / `afterVaR` if available
- "Analyze & Execute" button -> `setSelectedHedge(strategy)`

**Loading state**: Skeleton cards (same pattern as other tools)
**Error state**: Error card with message
**Empty state**: When no strategies available — "No hedge strategies identified for your current portfolio. Your risk exposures may be below the threshold for actionable hedges."
**No weights state**: When `initialPositions` is empty — "Load portfolio positions to generate hedge recommendations."

**Dialog:**
```tsx
<HedgeWorkflowDialog
  strategy={selectedHedge}
  open={!!selectedHedge}
  onOpenChange={(open) => { if (!open) setSelectedHedge(null); }}
/>
```

### Step 4: Register tool in ScenariosRouter

**File:** `frontend/packages/ui/src/components/portfolio/scenarios/ScenariosRouter.tsx`

Add lazy import and entry in the `fallbackByTool` record (matching the existing pattern exactly):

```typescript
const HedgeTool = lazy(() => import("./tools/HedgeTool"));

// Inside the component, add to fallbackByTool:
const fallbackByTool: Record<SelectableScenarioTool, React.ReactNode> = {
  // ... existing entries ...
  'hedge': <HedgeTool context={toolContext} onNavigate={setActiveTool} />,
};
```

### Step 5: Add tool card to ScenariosLanding

**File:** `frontend/packages/ui/src/components/portfolio/scenarios/ScenariosLanding.tsx`

Add to `TOOL_CARDS` array (Shield is already imported):

```typescript
{
  toolId: 'hedge',
  icon: Shield,
  title: 'Hedge Analysis',
  description: 'Explore hedging strategies for your risk exposures',
},
```

### Step 6: Wire "Simulate hedge" button

**File:** `frontend/packages/ui/src/components/dashboard/views/modern/FactorsContainer.tsx`

Currently both "Simulate hedge" and "Run stress test" use the same `handleOpenScenarios` handler which just calls `setActiveView('scenarios')`. The hedge button needs its own handler:

```typescript
const handleSimulateHedge = () => {
  setActiveView('scenarios');
  setActiveTool('hedge');
};
```

Update the "Simulate hedge" button's `onClick` to use `handleSimulateHedge` instead of `handleOpenScenarios`.

### Step 7: Update StressTestTool hedge navigation

**File:** `frontend/packages/ui/src/components/portfolio/scenarios/tools/StressTestTool.tsx` (line 167)

The "Hedge this risk" button currently navigates to `what-if` with delta context. Update to navigate to `'hedge'`:

```typescript
const handleHedgeNavigation = () => {
  onNavigate("hedge");
};
```

The hedge tool fetches its own recommendations — no need to pass delta context.

## What does NOT change

- `HedgeWorkflowDialog.tsx` — reused as-is
- `useHedgingRecommendations` / `HedgingAdapter` — reused as-is
- Backend endpoints — all intact
- Risk Drivers tab — stays analytical-only
- `HedgeStrategy` type — used as-is (has `efficiency`, `hedgeTicker`, `cost`, `protection`, `details`)

## Files to modify

1. `frontend/packages/connectors/src/stores/uiStore.ts` — add `'hedge'` to `ScenarioToolId`
2. `frontend/packages/ui/src/components/portfolio/scenarios/shared/ToolBreadcrumb.tsx` — add breadcrumb label
3. `frontend/packages/ui/src/components/portfolio/scenarios/tools/HedgeTool.tsx` (new) — hedge tool component
4. `frontend/packages/ui/src/components/portfolio/scenarios/ScenariosRouter.tsx` — register tool
5. `frontend/packages/ui/src/components/portfolio/scenarios/ScenariosLanding.tsx` — add tool card
6. `frontend/packages/ui/src/components/dashboard/views/modern/FactorsContainer.tsx` — wire hedge button to `'hedge'`
7. `frontend/packages/ui/src/components/portfolio/scenarios/tools/StressTestTool.tsx` — update "Hedge this risk" to navigate to `'hedge'`

## Verification

1. Navigate to Scenarios page -> should see "Hedge Analysis" card on landing
2. Click it -> HedgeTool loads, fetches recommendations, shows strategy cards
3. Click a strategy -> HedgeWorkflowDialog opens at Step 1 (Review)
4. Continue through Step 2 (Impact) -> verify what-if preview works
5. Continue through Step 3 (Trades) -> verify account fetch, trade leg preview
6. Step 4 (Execute) -> verify execution flow (or "trading disabled" handling)
7. Navigate to Risk page -> click "Simulate hedge" -> lands on HedgeTool (not what-if)
8. StressTestTool -> "Hedge this risk" button -> navigates to HedgeTool
9. No weights/empty portfolio -> shows appropriate empty state message
10. Frontend typecheck passes

# Phase 3: Scenarios Overhaul — Implementation Spec

**Status**: READY (revised post-prep-refactors)
**Parent plan**: `FRONTEND_NAV_SYNTHESIS_PLAN.md` (Phase 3)
**Prerequisite**: `SCENARIOS_PREP_REFACTOR_SPEC.md` — 3 prep refactors (DONE)
**Resolves**: T3 #32 (Scenario Analysis cramped), #33 (Strategy Builder confusing)
**Informed by**: `ADVISOR_WORKFLOW_RESULTS.md` — Q7 (stress), Q18 (what-if), Q20 (rebalance), Q23 (tax harvest)
**Codex review R1**: Original spec FAIL'd (4H/3M). Prep refactors resolved 5/7.
**Codex review R2**: Revised spec FAIL'd (3H/3M/1L). R2 revision addressed adapter shape, backtest hook, cache keys.
**Codex review R3**: Revised spec FAIL'd (3H/3M/1L). R3 revision addressed routing, extraction model, backtest isolation.
**Codex review R4**: Revised spec FAIL'd (2H/3M/1L). R4 revision addressed sidebar/uiStore, Trading deferral, hedging hook, bulk init, tax hook table.
**Codex review R5**: Revised spec FAIL'd (2H/3M/1L). R5 revision addressed fallback mechanism, reset condition, hook APIs, backtest contradictions, exit ramp completeness.
**Codex review R6**: Revised spec FAIL'd (1H/3M/1L). R6 revision addressed Trading deferral, exit ramp table, hedging signature, wireframe YTD, alias timing.
**Codex review R7**: Revised spec FAIL'd (2H/2M). R7 revision addressed fallback map, rebalance dual-mode, cross-section nav, wireframe sell buttons.
**Codex review R8**: Revised spec FAIL'd (1H/1M). R8 revision addressed weight units and tax harvest execution trigger.
**Codex review R9**: Revised spec FAIL'd (2H/2M). R9 revision addressed weight per-source rules, template dual-field, history tracking, loss sign.
**Codex review R10**: Revised spec FAIL'd (2H). R10 revision addressed template deployment path and hedge conversion contract.
**Codex review R11**: Revised spec FAIL'd (2H). R11 revision addressed stale optimizationData.weights refs and What-If delta-mode weight resolution.
**Codex review R12**: Revised spec FAIL'd (1H). R12 revision addressed hedge sort order.
**Codex review R13**: Revised spec FAIL'd (2H). R13 revision addressed hedge-overlay backend rejection and hook return shape.
**Codex review R14**: Revised spec FAIL'd (1H/1M). This revision addresses all R14 findings.

---

## Goal

Replace the cramped 6-tab ScenarioAnalysisContainer + 3-tab StrategyBuilderContainer with a **card-based landing page** that routes to **full-width tool views**. Each tool gets the full viewport instead of being squeezed into a tab within a card.

---

## Current State (What Exists)

### Containers (to be replaced)
| Container | Lines (post-prep) | Tabs | Location |
|-----------|-------------------|------|----------|
| `ScenarioAnalysisContainer` | 515 | portfolio-builder, optimizations, stress-tests, monte-carlo, efficient-frontier, (historical — hidden) | `dashboard/views/modern/ScenarioAnalysisContainer.tsx` |
| `StrategyBuilderContainer` | 132 | builder, marketplace, performance | `dashboard/views/modern/StrategyBuilderContainer.tsx` |
| `ScenarioAnalysis` (presentational) | 420 | (tab panels — editable positions, template apply, reset, simulation controls, compare/history) | `portfolio/ScenarioAnalysis.tsx` |
| `AssetAllocationContainer` | 407 | (no tabs — inline rebalance workflow) | `dashboard/views/modern/AssetAllocationContainer.tsx` |

### Hooks

#### Extracted by Prep Refactors (NEW — call directly from tool views)
| Hook | Provides | Source Prep |
|------|----------|-------------|
| `useScenarioState(args)` | initialPositions, scenarioTemplates, optimizationData*, addRun/clearHistory/getRuns, pendingHistoryTracking, handleRunStressTest/handleRunMonteCarlo | Prep A |
| `useOptimizationWorkflow()` | optimize→backtest pipeline, deferred execution, template deployment, export-to-scenario | Prep B |
| `useTaxHarvest()` | harvest candidates, wash sale tickers, flags/verdict, deferred execution via `runTaxHarvest()` | Prep C |

**\*Optimization data cache key fix needed**: `useScenarioState()` reads cached optimization data via `buildDataSourceQueryKey("optimization", { portfolioId, strategy })` (no `_runId`), but after Prep B's deferred execution fix, `usePortfolioOptimization` stores results with `_runId` in the query params (`{ portfolioId, strategy, _runId }`). Since `serializeParams` includes all non-undefined params, the keys don't match. **Fix (in Phase 3b)**: Change `useScenarioState`'s optimization data read to use `queryClient.getQueriesData({ queryKey: ['sdk', 'optimization'] })` for prefix-matching, then filter by `portfolioId`/`strategy` from the deserialized params. This is a ~10-line change in `useScenarioState.ts` lines 127-155.

#### Existing (reuse as-is)
| Hook | Lines | MCP Tool | Location |
|------|-------|----------|----------|
| `useWhatIfAnalysis` | 262 | `run_whatif` | `connectors/features/whatIf/hooks/` |
| `useStressTest` | 104 | stress scenarios API | `connectors/features/stressTest/hooks/` |
| `usePortfolioOptimization` | 45 | `run_optimization` (now deferred — Prep B) | `connectors/features/optimize/hooks/` |
| `useEfficientFrontier` | — | `get_efficient_frontier` | `connectors/features/efficientFrontier/hooks/` |
| `useBacktest` | 126 | `run_backtest` | `connectors/features/backtest/hooks/` |
| `useRebalanceTrades` | 20 | `generate_rebalance_trades` | `connectors/features/allocation/hooks/` |
| `useScenarioHistory` | 246 | (client state) | `portfolio/scenario/useScenarioHistory.ts` |

### Remaining Gaps
- **Compare Scenarios UI** — no frontend component. Backend: `compare_scenarios` MCP tool. (Deferred — not in Phase 3 scope.)

> **Parent plan deviation**: The parent plan (`FRONTEND_NAV_SYNTHESIS_PLAN.md`) Phase 3 originally scoped "Scenario Comparison" as part of the overhaul. This spec explicitly defers it because: (1) no existing UI component to extract — it's 100% new build, (2) the backend `compare_scenarios` MCP tool exists but has no adapter/resolver/hook plumbing, and (3) the 7 tool views already cover the advisor workflow questions (Q7/Q18/Q20/Q23). Compare can be added as Phase 3.5 after the core overhaul ships. This deviation should be acknowledged when updating the parent plan.

### ViewId Routing
- `scenarios` (⌘8) → `ScenarioAnalysisContainer` (lazy)
- `strategies` (⌘5) → `StrategyBuilderContainer`

After Phase 1 (nav items 7→5), both route to `scenarios` ViewId.

---

## Target State

### Landing Page: Card Grid

When user navigates to Scenarios (⌘4), they see a card grid:

```
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  ⚡ What-If       │  │  📊 Optimize      │  │  📈 Backtest      │
│                  │  │                  │  │                  │
│  Edit weights,   │  │  Find optimal    │  │  Test allocation │
│  simulate risk   │  │  allocation for  │  │  against history │
│  impact          │  │  your risk       │  │                  │
│                  │  │  tolerance       │  │                  │
│  [most used]     │  │                  │  │                  │
└──────────────────┘  └──────────────────┘  └──────────────────┘
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  💥 Stress Test   │  │  🎲 Monte Carlo   │  │  ⚖️ Rebalance     │
│                  │  │                  │  │                  │
│  See how crashes │  │  Simulate 1000s  │  │  Generate trades │
│  would affect    │  │  of possible     │  │  to hit target   │
│  your portfolio  │  │  futures         │  │  weights         │
└──────────────────┘  └──────────────────┘  └──────────────────┘
┌──────────────────┐
│  🏷️ Tax Harvest   │
│                  │
│  Find losers to  │
│  sell, estimate  │
│  tax savings     │
└──────────────────┘
```

Each card click → full-width tool view with breadcrumb nav back.

### Full-Width Tool Views

Each tool replaces the card grid with a full-viewport tool interface:

```
┌──────────────────────────────────────────────────────────┐
│  ← Scenarios  /  What-If Simulator                       │  ← Breadcrumb
├──────────────────────────────────────────────────────────┤
│                                                          │
│  (full-width tool content — inputs, results, actions)    │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

---

## Component Architecture

### New Components

```
ui/src/components/portfolio/scenarios/
├── ScenariosLanding.tsx          ← Card grid (landing page)
├── ScenariosRouter.tsx           ← State-driven router (landing vs tool view)
├── ToolBreadcrumb.tsx            ← "← Scenarios / Tool Name" header
├── tools/
│   ├── WhatIfTool.tsx            ← Full-width What-If (extracts from ScenarioAnalysis portfolio-builder tab)
│   ├── OptimizeTool.tsx          ← Full-width Optimize (extracts from ScenarioAnalysis optimizations tab + StrategyBuilder builder tab)
│   ├── BacktestTool.tsx          ← Full-width Backtest (extracts from StrategyBuilder performance tab)
│   ├── StressTestTool.tsx        ← Full-width Stress Test (extracts from ScenarioAnalysis stress-tests tab)
│   ├── MonteCarloTool.tsx        ← Full-width Monte Carlo (extracts from ScenarioAnalysis monte-carlo tab)
│   ├── RebalanceTool.tsx         ← Full-width Rebalance (extracts from AssetAllocationContainer)
│   └── TaxHarvestTool.tsx        ← NEW — no existing UI to extract from
└── shared/
    ├── ToolCard.tsx              ← Card component for landing grid
    ├── ScenarioResultsPanel.tsx  ← Shared before/after metrics display
    └── ExitRampButton.tsx        ← Contextual navigation button ("Generate trades →")
```

### Routing Strategy

State-driven routing via **UI store** (not local state), enabling cross-section deep-linking:

```tsx
type ScenarioToolId =
  | 'landing'
  | 'what-if'
  | 'optimize'
  | 'backtest'
  | 'stress-test'
  | 'monte-carlo'
  | 'rebalance'
  | 'tax-harvest';

// In uiStore (Zustand) — lifted from component state per Codex finding #7
interface ScenarioRouterState {
  activeTool: ScenarioToolId;
  toolContext: Record<string, unknown>;  // pre-filled tickers, weights from exit ramps
  setActiveTool: (tool: ScenarioToolId, context?: Record<string, unknown>) => void;
  resetToLanding: () => void;
}

function ScenariosRouter() {
  const { activeTool, toolContext, setActiveTool, resetToLanding } = useScenarioRouterState();

  if (activeTool === 'landing') return <ScenariosLanding onSelectTool={setActiveTool} />;

  return (
    <>
      <ToolBreadcrumb tool={activeTool} onBack={resetToLanding} />
      {activeTool === 'what-if' && <WhatIfTool context={toolContext} onNavigate={setActiveTool} />}
      {activeTool === 'optimize' && <OptimizeTool context={toolContext} onNavigate={setActiveTool} />}
      {/* ... etc */}
    </>
  );
}
```

**Why UI store, not local state**: Other sections (Dashboard, Research) may deep-link into a specific scenario tool via exit ramps (e.g., "Run What-If →" from stock analysis). With local state, the caller would need to set ViewId to `scenarios` but has no way to also set `activeTool`. With store state, cross-section navigation is: `setActiveView('scenarios'); setActiveTool('what-if', { weights })`.

The store resets `activeTool` to `'landing'` when the user navigates away from the scenarios section. **Important**: The reset condition must treat both `scenarios` and `strategies` ViewIds as "inside the section" — i.e., reset only when `activeView` is neither `'scenarios'` nor `'strategies'`. Otherwise, navigating from `scenarios` to `strategies` (or vice versa) would clobber the `activeTool` state.

**`toolContext` clearing semantics**: Stale `toolContext` must not leak between tool launches:
- `setActiveTool(tool, context?)`: If `context` is provided, store it. If `context` is omitted/undefined, **clear `toolContext` to `{}`**. This ensures landing-page card clicks (no context) and direct navigation don't inherit stale exit-ramp data from a previous tool.
- `resetToLanding()`: Clears both `activeTool` → `'landing'` and `toolContext` → `{}`.
- Tools that branch on `toolContext.weights` or `toolContext.deltas` must check for presence (e.g., `Object.keys(toolContext.weights ?? {}).length > 0`) rather than truthiness.

### Routing Alias & Legacy Path Plan

The `strategies` ViewId is a live route that must keep working until parent plan Phase 7 cleanup. Files that reference it:

| File | Line | What It Does | Phase 3 Change |
|------|------|-------------|----------------|
| `connectors/src/stores/uiStore.ts` L80 | `export type ViewId = '...' \| 'strategies' \| 'scenarios' \| ...` | ViewId type union (source of truth) | **No change in Phase 3.** `strategies` stays in the union until parent plan Phase 7. Phase 3a adds `ScenarioRouterState` slice to this store. |
| `ui/src/components/dashboard/AppSidebar.tsx` L37 | `{ id: 'strategies', label: 'Strategy', icon: Layers, shortcut: '⌘5' }` | Sidebar nav item (primary nav — default layout is sidebar) | **Phase 1** (nav merge) removes this item. No change in Phase 3. |
| `ui/src/components/dashboard/NavBar.tsx` L40 | `{ id: 'strategies', label: 'Strategy', icon: Layers, shortcut: '⌘5' }` | Header nav item (fallback layout) | **Phase 1** (nav merge) removes this item. No change in Phase 3. |
| `ui/src/components/apps/ModernDashboardApp.tsx` L274 | `case '5': setActiveView('strategies')` | ⌘5 keyboard shortcut | **Phase 1** remaps ⌘5. No change in Phase 3. |
| `ui/src/components/apps/ModernDashboardApp.tsx` L440-447 | `case 'strategies': return <StrategyBuilderContainer />` | View renderer | **Phase 3a**: `case 'strategies':` renders `<ScenariosRouter defaultTool='optimize' />`. The `defaultTool` prop only applies on **initial entry** (when `activeTool` is still `'landing'`); if the user already has an active tool (e.g., navigated away and back), the current `activeTool` is preserved. `case 'scenarios':` renders `<ScenariosRouter />` with no defaultTool (lands on card grid). |
| `connectors/src/utils/NavigationIntents.ts` L35+ (active — not the legacy `navigation/NavigationIntents.ts`) | `'navigate-to-strategy-builder'`, `'navigate-to-scenario-analysis'` | Intent type union | **Phase 3e**: Add `'navigate-to-scenario-tool'` to the union. Keep legacy intents as aliases. |
| `connectors/src/providers/SessionServicesProvider.tsx` L439-486 | `navigateToScenarioAnalysisHandler`, `navigateToStrategyBuilderHandler` | Intent handlers | **Phase 3e**: Update handlers (see Phase 3e spec below). |

**Key principle**: `strategies` stays as a valid ViewId that renders `ScenariosRouter`. It's not removed until parent plan Phase 7. Phase 3 only changes what it renders (ScenariosRouter instead of StrategyBuilderContainer).

### Cross-Tool Navigation (Exit Ramps)

Each tool has `onNavigate(toolId, context)` callback for exit ramps:

| From | Action | To | Context Passed | Status |
|------|--------|----|----------------|--------|
| What-If | "Backtest this →" | Backtest | resolved post-scenario weights as `toolContext.weights` (see What-If weight resolution below) | Phase 3e |
| What-If | "Generate trades →" | Rebalance | resolved post-scenario weights (see What-If weight resolution below) | Phase 3e |
| Optimize | "Backtest this →" | Backtest | `activeWeights` as `toolContext.weights` | Phase 3e |
| Optimize | "Apply as what-if →" | What-If | `activeWeights` as starting point | Phase 3e |
| Optimize | "Set target →" | Rebalance | `activeWeights` as target | Phase 3e |
| Backtest | "Set as target →" | Rebalance | backtested weights | Phase 3e |
| Stress Test | "Hedge this risk →" | What-If | hedge context (see conversion below) | Phase 3e |
| Stress Test | "Run Monte Carlo →" | Monte Carlo | (no context — just navigates) | Phase 3e |
| What-If | "Compare scenarios" | Scenario Comparison | scenario results | **Deferred** — Phase 3.5 |
| Rebalance | "Preview all trades →" | Trading (cross-section) | trade legs | **Deferred** — Phase 5 |
| Tax Harvest | "Sell for harvest →" | Trading (cross-section) | sell orders | **Deferred** — Phase 5 |

**Deferred exit ramps** (see Status column in table above): Trading exits require a `trading` ViewId that doesn't exist yet (`uiStore.ts` L80 has no `'trading'`). Parent plan places Trading in Phase 5. "Compare scenarios" requires Scenario Comparison (Phase 3.5). These buttons are omitted from Phase 3 tool views and added when their target phases ship.

---

## Tool Specifications

### WhatIfTool.tsx

**Extracts from**: ScenarioAnalysis `portfolio-builder` tab content
**Hooks**: `useWhatIfAnalysis` (reuse) + `useScenarioState()` (Prep A — provides initialPositions, scenarioTemplates, history tracking)
**Experiment reference**: Q18 used `run_whatif` + `compare_scenarios` for graduated modeling

```
┌──────────────────────────────────────────────────────────┐
│  ← Scenarios / What-If Simulator                         │
├──────────────────────────────┬───────────────────────────┤
│                              │                           │
│  Input Mode: [Weights|Deltas]│   Results                 │
│                              │                           │
│  Current positions:          │   Before    After   Delta │
│  NVDA  21.5% → [__]%  [-+]  │   Vol  20.1%  15.3%  ↓   │
│  DSU   29.1% → [__]%  [-+]  │   Beta 1.02   0.80   ↓   │
│  MSCI  21.5% → [__]%  [-+]  │   HHI  0.15   0.12   ↓   │
│  ...                         │   Max  29.1%  20.3%  ↓   │
│                              │   Pass  NO    YES    ✓   │
│  + Add ticker: [____]        │                           │
│                              │   Risk checks:            │
│  Templates:                  │   ✓ Volatility            │
│  [60/40] [All-weather]       │   ✓ Max weight            │
│  [Defensive] [Custom...]     │   ✗ Industry variance     │
│                              │                           │
│  [Run Simulation]            │                           │
│                              │                           │
├──────────────────────────────┴───────────────────────────┤
│  [Generate trades →]  [Save scenario]  [Backtest this →] │
└──────────────────────────────────────────────────────────┘
```

**Extraction model — two layers to reconcile**:

`ScenarioAnalysis.tsx` owns an **editable-position model** (lines 61-268):
- `currentPositions` state — array of `{ ticker, name, weight, price, shares }`, initialized from `initialPositions` prop
- `updatePositionWeight()`, `addNewPosition()`, `removePosition()`, `resetToPortfolio()` — direct position mutation
- `applyTemplateAndRun()` — rebuilds position list with normalized template weights, then runs
- `applyOptimizationAsWhatIf()` — applies optimization weights as positions

`useWhatIfAnalysis` hook owns a **record-based input model** (lines 43-212):
- `weightInputs` / `deltaInputs` — `Record<string, string>` keyed by ticker
- `addAssetInput()`, `removeAssetInput()`, `updateAssetName()`, `updateAssetValue()` — record mutation
- `runScenarioFromInputs()` — converts records to API format and calls `runScenario()`

**These are different models.** WhatIfTool must choose one:
- **Option A (recommended)**: Use the hook's record-based input model directly. This is simpler and matches the API contract. The editable-position table in WhatIfTool renders `weightInputs` as rows. Templates call a helper that populates `weightInputs` from template weights. No `currentPositions` state needed.
- **Option B**: Port the ScenarioAnalysis position-editing model into WhatIfTool. More familiar UX but requires maintaining a separate `currentPositions` array that syncs to `weightInputs` before calling `runScenario()`.

**Decision: Option A.** The record model is already in the hook and eliminates the sync problem.

**Weight unit conversion**: Two different unit conventions exist:
- `initialPositions.weight` from `useScenarioState()` (sourced from `usePositions()` → `PositionsAdapter`) is in **percentage points** (e.g., `60` = 60%).
- `useWhatIfAnalysis().weightInputs` stores **string representations of decimal fractions** (e.g., `"0.60"` — the hook test asserts values like `"0.25"`). `createScenarioFromInputs()` parses these to numbers and passes them directly to the API.
- Templates from `buildScenarioTemplates()` are already **decimal fractions** (the builder calls `holding.weight / 100` at `templates.ts:78` and then normalizes).

**Conversion rules for WhatIfTool**:
- **From initialPositions**: Divide `weight` by 100 before storing in `weightInputs` (e.g., `60` → `"0.60"`).
- **From templates**: Store as-is (already decimal fractions in `apiScenario.new_weights`).
- **From user input**: UI displays percentage (user types "60"), store as `"0.60"` in `weightInputs`.

**StressTestTool**: Must also divide `initialPositions.weight` by 100 when building the weight record for `useHedgingRecommendations(weights, portfolioValue)`.

This is a critical correctness requirement — without the conversion, the API receives `60` instead of `0.60`.

**Bulk initialization gap**: `useWhatIfAnalysis()` exposes `weightInputs` (read) and per-entry mutation APIs (`addAssetInput`, `removeAssetInput`, `updateAssetName`, `updateAssetValue`) but does **not** expose a bulk `setWeightInputs()` or reset/init API. To populate `weightInputs` from `initialPositions` (useScenarioState) or templates, WhatIfTool needs one of:
- **(a) Hook extension** (~5 lines): Add `initWeightInputs(inputs: Record<string, string>)` to `useWhatIfAnalysis()` that calls the internal `setWeightInputs`. This is the cleanest option.
- **(b) Bridge effect**: A `useEffect` in WhatIfTool that iterates `addAssetInput()` + `updateAssetName()` + `updateAssetValue()` for each initial position. Functional but awkward.

**Recommendation**: Option (a) — extend the hook with two bulk init methods in Phase 3b:
- `initWeightInputs(inputs: Record<string, string>)` — replaces `weightInputs`, sets `inputMode` to `'weights'`
- `initDeltaInputs(inputs: Record<string, string>)` — replaces `deltaInputs`, sets `inputMode` to `'deltas'`

Both are ~5-line additions calling the internal `setWeightInputs`/`setDeltaInputs`/`setInputMode`. The delta init is needed for: (a) StressTest → What-If hedge exit ramp (pre-fills `deltaInputs` from hedge strategy), (b) `hedge-overlay` template (delta-only after Phase 3b fix).

**Template execution path**: Templates carry a pre-built `apiScenario` object. Most templates have only `new_weights`. The `hedge-overlay` template has **both** `new_weights` AND `delta: { SPY: "-5%" }` (`templates.ts:188`).

**Backend constraint**: `scenario_service.py:198` rejects requests with both `target_weights` and `delta_changes` — exactly one must be provided. The `hedge-overlay` template is therefore **broken as-is** (pre-existing bug). **Fix in Phase 3b**: Modify `hedge-overlay` to use `delta`-only mode (remove `new_weights`, keep only `delta: { SPY: "-5%" }`). The backend applies deltas relative to current portfolio, so omitting `new_weights` achieves the same "overlay" intent.

Templates call `runScenario()` directly (not `runScenarioFromInputs()`):
```tsx
const applyTemplate = (template: ScenarioTemplate) => {
  if (template.apiScenario.new_weights) {
    initWeightInputs(template.apiScenario.new_weights);
  }
  runScenario({ scenarioName: template.name, modifications: [], apiScenario: template.apiScenario });
};
```

**Changes from current portfolio-builder tab**:
- Full width (currently ~50% of a card)
- Templates promoted to visible buttons (currently hidden)
- Results panel shows compliance check detail (currently summarized)
- Position editing uses hook's record-based model (not ScenarioAnalysis.tsx's array model)
- Exit ramp buttons at bottom

**History tracking contract**: `useScenarioState()` records history via a two-step pattern: (1) call `pendingHistoryTracking.trackWhatIf(params)` to set a pending ref, (2) when `whatIfData` changes in a `useEffect`, the hook matches the pending ref and calls `addRun()`. WhatIfTool must call `trackWhatIf()` **before** calling `runScenario()`/`runScenarioFromInputs()`:
```tsx
const handleRun = () => {
  pendingHistoryTracking.trackWhatIf({ inputs: weightInputs, mode: inputMode });
  runScenarioFromInputs();  // or runScenario() for templates
};
```
This requires `useScenarioState()` to receive `whatIfData` as an arg (it already does — see `UseScenarioStateArgs`). WhatIfTool passes `whatIfAnalysis.data` as the `whatIfData` arg. Same pattern applies to StressTestTool (`trackStress`) and MonteCarloTool (`trackMonteCarlo`).

**What-If weight resolution for exit ramps**: `useWhatIfAnalysis()` tracks inputs (`weightInputs`/`deltaInputs`) but does **not** expose resolved post-scenario weights. After a delta-based run (e.g., from hedge overlay template or StressTest exit ramp), the inputs are deltas, not absolute weights. The resolved weights live in the API response at `whatIfData.scenario_results.position_changes[].after`.

To extract resolved weights for "Backtest this →" and "Generate trades →" exit ramps, WhatIfTool uses the existing `deriveOptimizedPositions()` helper from `useScenarioOrchestration.ts`:
```tsx
import { deriveOptimizedPositions } from '../scenario/useScenarioOrchestration';

// After a successful what-if run:
const resolvedPositions = deriveOptimizedPositions(
  whatIfData?.scenario_results?.position_changes,
  initialPositions  // from useScenarioState
);
// Convert to weight record (÷100 because deriveOptimizedPositions returns percentage points)
const resolvedWeights = Object.fromEntries(
  resolvedPositions.map(p => [p.ticker, p.weight / 100])
);
// Pass to exit ramp: setActiveTool('backtest', { weights: resolvedWeights })
```
Exit ramp buttons are disabled until `whatIfData` is available (a scenario has been run).

### OptimizeTool.tsx

**Extracts from**: ScenarioAnalysis `optimizations` tab + StrategyBuilder `builder` tab
**Hooks**: `useOptimizationWorkflow()` (Prep B — deferred execution, template deployment, backtest gating), `useEfficientFrontier`
**Includes**: Efficient Frontier chart (currently a separate tab)
**Note**: `usePortfolioOptimization` is now deferred (Prep B fix) — no auto-fetch on mount. Shows "Run Optimization" prompt initially.

```
┌──────────────────────────────────────────────────────────┐
│  ← Scenarios / Optimize                                  │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  Strategy: [Min Variance ▾] [Max Return ▾] [Custom]     │
│                                                          │
│  [Run Optimization]                                      │
│                                                          │
│  ┌─── Optimal Weights ───────────────────────────────┐  │
│  │ Ticker  Current  Optimal  Delta                   │  │
│  │ NVDA    21.5%    12.0%    -9.5%                   │  │
│  │ DSU     29.1%    15.0%    -14.1%                  │  │
│  │ AGG     0.0%     10.0%    +10.0%  (new)           │  │
│  │ ...                                               │  │
│  │                                                   │  │
│  │ HHI: 0.152 → 0.098 (improved)                    │  │
│  └───────────────────────────────────────────────────┘  │
│                                                          │
│  ┌─── Efficient Frontier ────────────────────────────┐  │
│  │ (scatter chart — current portfolio dot + frontier) │  │
│  │ (from EfficientFrontierTab, reused as-is)         │  │
│  └───────────────────────────────────────────────────┘  │
│                                                          │
│  [Apply as What-If →]  [Backtest this →]  [Set target →] │
└──────────────────────────────────────────────────────────┘
```

**What gets merged**: StrategyBuilder's "marketplace" becomes a Templates dropdown within the strategy selector. StrategyBuilder's "performance" tab becomes the "Backtest this" exit ramp.

**Template deployment path**: `useOptimizationWorkflow().handleOptimize()` has two branches (see `useOptimizationWorkflow.ts` L75-114):
- If `constraints.weights` is present (template path): it calls `backtest.runBacktest({ weights })` and **returns immediately** — it does NOT populate `optimizationData` or `optimizationResults`.
- If no weights (optimization path): it calls `optimization.optimizeMinVariance()` or `optimizeMaxReturn()`, which populates `optimizationData` with weights/results.

This means when a user selects a Marketplace template, the "Optimal Weights" table and exit ramps (`Apply as What-If`, `Set target`) won't have data from `optimizationData`. **Solution for OptimizeTool**: Maintain local `activeWeights` state that's populated from either source:
- After optimization: `activeWeights = optimizationData.weights`
- After template selection: `activeWeights = template.tickerWeights` (from `useOptimizationWorkflow().templates[i].tickerWeights`)
- The weights table, exit ramps, and "Backtest this →" all read from `activeWeights`, not from `optimizationData.weights` directly.

Template selection also triggers a backtest (existing behavior from `handleOptimize`). The Optimal Weights table shows `activeWeights` regardless of source.

### BacktestTool.tsx

**Extracts from**: StrategyBuilder `performance` tab
**Hooks**: `useBacktest()` (directly — not through `useOptimizationWorkflow()`).

**Why direct `useBacktest()`**: `useOptimizationWorkflow().handleBacktest()` always backtests `optimization.data?.weights` and bails if empty (line 120-127 of `useOptimizationWorkflow.ts`). Also, `usePortfolioOptimization()` only exposes results for runs it started — a standalone BacktestTool mounting its own hook instance won't see another component's optimization results.

BacktestTool gets weights from two sources only:
1. **From `toolContext.weights`** (exit ramp from OptimizeTool passes `activeWeights`, or from What-If passes resolved scenario weights). This is the primary path.
2. **From manual entry** (user types ticker weights directly in BacktestTool).

There is **no optimization cache read** — BacktestTool does not call `useOptimizationWorkflow()` or `usePortfolioOptimization()`. If the user navigates directly to BacktestTool (not via exit ramp), they see an empty weight table with manual entry.

The tool calls `backtest.runBacktest({ weights, benchmark, period })` directly. The `canBacktest` check is: `Object.keys(activeWeights).length > 0` where `activeWeights` comes from toolContext or manual input.

```
┌──────────────────────────────────────────────────────────┐
│  ← Scenarios / Backtest                                  │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  Allocation: [from exit ramp / manual entry]             │
│  Benchmark: [SPY ▾]     Period: [3Y ▾] [5Y] [MAX]      │
│                                                          │
│  [Run Backtest]                                          │
│                                                          │
│  ┌─── Cumulative Return Chart ────────────────────────┐ │
│  │ (portfolio vs benchmark line chart)                 │ │
│  └────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌─── Key Metrics ────────────────────────────────────┐ │
│  │ Total Return | Sharpe | Max DD | Win Rate | Alpha  │ │
│  └────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌─── Annual Breakdown ──────────────────────────────┐  │
│  │ Year | Return | Benchmark | Excess | Max DD       │  │
│  │ 2024 | +32%   | +24%      | +8%    | -8%         │  │
│  │ 2025 | +18%   | +12%      | +6%    | -12%        │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  [Set as target allocation →]                            │
└──────────────────────────────────────────────────────────┘
```

### StressTestTool.tsx

**Extracts from**: ScenarioAnalysis `stress-tests` tab
**Hooks**: `useStressTest` (reuse), `useStressScenarios()` (scenario catalog for dropdown — separate query hook exported from same file, L93-102), `useScenarioState()` (Prep A — history tracking), `useHedgingRecommendations(weights, portfolioValue?)` (from `connectors/features/hedging/hooks/` — signature requires current portfolio weights and optional portfolio value; only enables when weights are present; returns transformed `strategies` array for the "Hedge this risk →" exit ramp. StressTestTool gets `weights` from positions data via `useScenarioState().initialPositions` converted to a weight record.)
**Experiment reference**: Q7 used `run_backtest` + `run_whatif`(×2) for stress modeling

```
┌──────────────────────────────────────────────────────────┐
│  ← Scenarios / Stress Test                               │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  Scenario: [2008 GFC ▾] [COVID ▾] [Rate Shock ▾]       │
│                                                          │
│  [Run Stress Test]                                       │
│                                                          │
│  ┌─── Impact Summary ────────────────────────────────┐  │
│  │ Portfolio Loss: -$29,700 (-58%)                   │  │
│  │ Worst Position: DSU (-70%)                        │  │
│  │ Margin Call Risk: YES (at -35% drawdown)          │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  ┌─── Per-Position Impact ────────────────────────────┐ │
│  │ Ticker | Weight | Est. Loss | Sector Risk          │ │
│  └────────────────────────────────────────────────────┘ │
│                                                          │
│  [Hedge this risk →]  [Run Monte Carlo →]                │
└──────────────────────────────────────────────────────────┘
```

**"Hedge this risk →" conversion**: `useHedgingRecommendations(weights, portfolioValue)` returns `{ data: HedgeStrategy[] | undefined, ... }` — note: `.data` is the strategies array (not the hook return directly). Each `HedgeStrategy` has `{ hedgeTicker, suggestedWeight, details: { riskReduction } }`. The array is **not sorted cross-strategy** — `HedgingAdapter` picks the best recommendation per driver but returns strategies in `drivers` order (up to 3).

StressTestTool selects the best strategy and converts to a What-If–compatible `toolContext`:
```tsx
const { data: hedgeStrategies } = useHedgingRecommendations(weights, portfolioValue);

// Sort by risk reduction and pick best
const sorted = [...(hedgeStrategies ?? [])].sort(
  (a, b) => b.details.riskReduction - a.details.riskReduction
);
const bestHedge = sorted[0];

// Navigate to What-If with delta pre-fill
if (bestHedge) {
  setActiveTool('what-if', {
    mode: 'deltas',
    deltas: { [bestHedge.hedgeTicker]: `+${(bestHedge.suggestedWeight * 100).toFixed(1)}%` },
    label: bestHedge.strategy,
  });
}
```
WhatIfTool receives this in `toolContext` and calls `initDeltaInputs(toolContext.deltas)` on mount (which populates `deltaInputs` and sets `inputMode` to `'deltas'`). The user can adjust before running. If no hedge strategies are returned (empty/undefined `.data`), the button is disabled.

### MonteCarloTool.tsx

**Extracts from**: ScenarioAnalysis `monte-carlo` tab
**Hooks**: `useMonteCarlo` (reuse), `useScenarioState()` (Prep A — history tracking)
**Full width** allows proper fan chart visualization.

### RebalanceTool.tsx

**Extracts from**: `AssetAllocationContainer` rebalance workflow
**Hooks**: `useTargetAllocation`, `useSetTargetAllocation`, `useRebalanceTrades`, `useRiskAnalysis`

```
┌──────────────────────────────────────────────────────────┐
│  ← Scenarios / Rebalance                                 │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  ┌─── Drift Table ────────────────────────────────────┐ │
│  │ Asset Class   Target   Current   Drift    $ Gap    │ │
│  │ Equity        60%      76.5%     +16.5    +$8,503  │ │
│  │ Bond          25%      29.1%     +4.1     +$2,093  │ │
│  │ Real Estate   10%      17.8%     +7.8     +$4,019  │ │
│  │ Cash          5%       -28.2%    -33.2    -$17,087 │ │
│  │                                                    │ │
│  │ [Edit Targets]  [Save Targets]                     │ │
│  └────────────────────────────────────────────────────┘ │
│                                                          │
│  [Generate Rebalance Trades]                             │
│                                                          │
│  ┌─── Trade Legs ─────────────────────────────────────┐ │
│  │ Action | Ticker | Shares | Value   | Weight Δ     │ │
│  │ SELL   | STWD   | 400    | $3,400  | -7.8%        │ │
│  │ SELL   | SLV    | 25     | $1,900  | -4.8%        │ │
│  │ BUY    | AGG    | 50     | $5,300  | +10.0%       │ │
│  └────────────────────────────────────────────────────┘ │
│                                                          │
│  [Preview all trades →] (deferred — Phase 5 Trading)     │
└──────────────────────────────────────────────────────────┘
```

**Note**: `AssetAllocationContainer` stays in Dashboard/Overview for the allocation donut/bar display. The rebalance *workflow* (edit targets → generate trades) moves here. The container can share the same hooks.

**Two input modes for RebalanceTool**:

1. **Asset-class mode** (default, from drift table): User edits asset-class targets. `useRebalanceTrades()` accepts **ticker-level** weights, so the tool must convert. AssetAllocationContainer handles this at lines 266-299: `buildTickerTargetWeights()` maps asset-class targets to ticker weights using the portfolio's current composition (proportional split within each asset class). Extract this helper:
   - `effectiveTargetMap` (L163-180): merged asset-class targets from `useTargetAllocation()` + local edits
   - `buildTickerTargetWeights(effectiveTargetMap, positions)` (L266-299): distributes class-level targets to tickers proportionally by current market value within each class
   - Drift computation: `target - current` per asset class for the drift table
   - Validation: weights sum to ~100%, no negative values
   - This is ~80 lines of logic that moves from AssetAllocationContainer into RebalanceTool.

2. **Ticker-weight mode** (from exit ramps): When `toolContext.weights` is provided (from What-If, Optimize, or Backtest exit ramps), the weights are already at the ticker level. In this mode, RebalanceTool **bypasses** the asset-class editor and passes `toolContext.weights` directly to `useRebalanceTrades()`. The drift table shows ticker-level drift instead of asset-class drift. This avoids the impossible ticker→asset-class reverse mapping (e.g., a new ticker like `AGG` from optimization has no asset class assignment in the current portfolio).

RebalanceTool detects the mode from `toolContext`: if `toolContext.weights` is present and non-empty, start in ticker-weight mode with a toggle to switch to asset-class mode (which discards the incoming weights and uses the drift table).

**Codex finding #6**: AssetAllocationContainer subscribes to `risk-data-invalidated` events via `eventBus.on()` to auto-refetch when risk data changes (lines 193-211). RebalanceTool must replicate this pattern — subscribe to `eventBus` and `refetch()` on invalidation. Use `useSessionServices()` to access the eventBus.

### TaxHarvestTool.tsx (NEW UI — backend plumbing complete)

**Hook**: `useTaxHarvest()` (Prep C — APIService method, adapter, resolver, and hook all exist)
**Experiment reference**: Q23 showed tiered output (clean / wash-sale / small) with estimated tax savings

```
┌──────────────────────────────────────────────────────────┐
│  ← Scenarios / Tax Harvest Scanner                       │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  ┌─── Summary ────────────────────────────────────────┐ │
│  │ Total harvestable losses: $11,605                  │ │
│  │ Estimated tax savings: ~$3,480 (client approx)      │ │
│  │ Positions analyzed: 12 / 15 (80% coverage)         │ │
│  └────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌─── Tier 1: Harvest Now (no wash sale risk) ────────┐ │
│  │ ☐ PCTY   -$1,967  (-30%)  Long-term               │ │
│  │ ☐ STWD   -$1,364  (-7%)   Mixed                   │ │
│  │ ☐ ENB    -$1,093  (-11%)  Long-term               │ │
│  │ ☐ SFM    -$916    (-47%)  Short-term              │ │
│  └────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌─── Tier 2: After Wash Window Clears ───────────────┐ │
│  │ ⚠ DSU   -$5,232  (-10%)  Wash: 45 shares Feb 27  │ │
│  │ ⚠ FIG   -$618    (-18%)  Wash: 3 shares recent   │ │
│  └────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌─── Tier 3: Small but Clean ────────────────────────┐ │
│  │ ☐ RNMBY  -$182   (-15%)  Short-term               │ │
│  │ ☐ AT.L   -$132   (-6%)   Short-term               │ │
│  │ ☐ LIFFF  -$101   (-20%)  Long-term                │ │
│  └────────────────────────────────────────────────────┘ │
│                                                          │
│  [Sell selected for harvest →] (deferred — Phase 5)      │
└──────────────────────────────────────────────────────────┘
```

**Hook exists** (Prep C): `useTaxHarvest()` — deferred execution via `runTaxHarvest()`, calls `suggest_tax_loss_harvest` via real API resolver. The hook mounts idle (`enabled: false`, `data` is `undefined`) and only fetches when `runTaxHarvest()` is explicitly called.

**Execution trigger**: TaxHarvestTool should **auto-run on mount** via a `useEffect` that calls `runTaxHarvest()` when the component mounts and a portfolio is loaded. This is the expected UX — the user clicks "Tax Harvest" from the landing page and sees results immediately (with a loading spinner during fetch), not an empty screen with a manual "Run" button. The deferred execution model prevents double-fetching when navigating away and back (the hook only refetches when `runTaxHarvest()` is called again).

**Adapter output shape** (`TaxHarvestSourceData`):
```typescript
{
  totalHarvestableLoss: number;       // Sum of all harvestable losses
  shortTermLoss: number;              // Short-term component
  longTermLoss: number;               // Long-term component
  candidateCount: number;
  topCandidates: Array<{
    ticker: string;
    totalLoss: number;                // Per-candidate loss amount
    lotCount: number;
    holdingPeriods: string[];         // e.g. ["long", "short"]
    washSaleRisk: boolean;            // Wash sale flag
  }>;
  washSaleTickers: string[];          // Tickers with wash sale risk
  washSaleTickerCount: number;
  dataCoveragePct: number;
  positionsAnalyzed: number;
  positionsWithLots: number;
  verdict: string;                    // e.g. "opportunities_found"
  flags: Array<{ flag: string; severity: 'error'|'warning'|'info'; message: string }>;
}
```

**UI-side tier computation** (not in adapter — computed in TaxHarvestTool):
- **Tier 1** (Harvest Now): `washSaleRisk === false && Math.abs(totalLoss) >= threshold` (totalLoss is negative)
- **Tier 2** (After Wash Window): `washSaleRisk === true`
- **Tier 3** (Small but Clean): `washSaleRisk === false && Math.abs(totalLoss) < threshold` (totalLoss is negative)
- **Estimated tax savings**: approximated **entirely client-side** as `Math.abs(totalHarvestableLoss) * 0.30` (displayed with "~" prefix). **Important**: `totalHarvestableLoss` and per-candidate `totalLoss` are **negative numbers** in the adapter output (losses are negative). Use `Math.abs()` for display values and savings calculation. Neither the adapter (`TaxHarvestAdapter.ts`) nor the `TaxHarvestSourceData` type has an `estimatedTaxSavings` field. If a backend-computed savings figure is added later, extend `TaxHarvestSourceData` and the adapter's `performTransformation()`.
- **YTD realized gains**: not available from the tax harvest endpoint or adapter. Omitted from the summary card wireframe. Could be added in a future iteration via cross-hook call to trading analysis.

---

## Implementation Sub-Phases

### Phase 3a: Scaffold + Landing + Router State

**Create**:
1. `scenarios/ScenariosRouter.tsx` — renders landing or tool view based on store state
2. `scenarios/ScenariosLanding.tsx` — card grid (7 tool cards)
3. `scenarios/shared/ToolCard.tsx` — card component
4. `scenarios/shared/ToolBreadcrumb.tsx` — breadcrumb nav ("← Scenarios / Tool Name")

**Add to uiStore**: `ScenarioRouterState` slice (activeTool, toolContext, setActiveTool, resetToLanding). Reset activeTool to `'landing'` when activeView changes away from **both** `scenarios` and `strategies` (both ViewIds map to ScenariosRouter).

**Wire**: In `ModernDashboardApp.tsx`:
- `case 'scenarios':` renders `<ScenariosRouter />` (replaces `<ScenarioAnalysisContainer />`)
- `case 'strategies':` renders `<ScenariosRouter />` with `defaultTool='optimize'` (replaces `<StrategyBuilderContainer />`)

**Fallback mechanism during migration**: `ScenariosRouter` renders the landing page when `activeTool === 'landing'`. When a card is clicked for a tool that hasn't been built yet (3b/3c/3d), the router renders a fallback:
```tsx
// Phase 3a temporary fallback map — each removed as its tool view ships
const FALLBACK: Record<ScenarioToolId, React.ReactNode> = {
  'what-if':     <ScenarioAnalysisContainer />,     // removed in 3b
  'stress-test': <ScenarioAnalysisContainer />,     // removed in 3b
  'monte-carlo': <ScenarioAnalysisContainer />,     // removed in 3b
  'optimize':    <StrategyBuilderContainer />,      // removed in 3c
  'backtest':    <StrategyBuilderContainer />,      // removed in 3c
  'rebalance':   <AssetAllocationContainer />,      // removed in 3d
  'tax-harvest': <TaxHarvestPlaceholder />,         // removed in 3d (no legacy UI exists)
};
```
`TaxHarvestPlaceholder` is a simple "Coming soon" card — Tax Harvest has no existing UI surface. As each tool view ships in 3b-3d, its fallback branch is replaced with the real component. Phase 3f deletes all fallback branches and the old containers.

**Why not route to old tabs (Codex finding #1)**: The old containers don't expose an `initialTab` prop, and adding one creates coupling we'll just delete. The fallback renders the full old container (all tabs), not a specific tab — good enough for the migration window.

**Files**: ~4 new, 2 modified (ModernDashboardApp + uiStore)
**Risk**: Minimal — old containers render as fallback, no functionality loss

### Phase 3b: Extract What-If + Stress Test + Monte Carlo

**Create**:
1. `scenarios/tools/WhatIfTool.tsx` — calls `useWhatIfAnalysis()` + `useScenarioState()` directly
2. `scenarios/tools/StressTestTool.tsx` — calls `useStressTest()` + `useScenarioState()` for history
3. `scenarios/tools/MonteCarloTool.tsx` — calls `useMonteCarlo()` + `useScenarioState()` for history
4. `scenarios/shared/ScenarioResultsPanel.tsx` — shared before/after metrics display
5. `scenarios/shared/ExitRampButton.tsx` — navigation button component

**State extraction is done** (Prep A). However, the JSX extraction is not trivial — `ScenarioAnalysis.tsx` (420 lines) owns:
- Editable-position workflow (weight/delta input table with add/remove/rename)
- Template application logic (click template → populate inputs)
- Reset/clear controls
- Simulation controls (Run button with input validation)
- Compare/history panel UI (recent runs list, comparison mode toggle)
- Tab-level state (which tab is active, tab transition)

Each tool view must extract its relevant tab's JSX plus the shared simulation controls. The `useWhatIfAnalysis` hook's input management API (`inputMode`, `weightInputs`, `addAssetInput`, etc.) maps 1:1 to the editable-position workflow, so WhatIfTool consumes these directly. StressTestTool and MonteCarloTool are simpler — they only need scenario selection + run button + results display.

**Also in this phase**: Fix the optimization cache key mismatch in `useScenarioState` (see note above).

**Files**: ~5 new, 2 modified (ScenariosRouter + useScenarioState cache fix)
**Risk**: Medium — WhatIfTool extraction involves 420-line presentational component; Stress/MonteCarlo are simpler

### Phase 3c: Extract Optimize + Backtest + Efficient Frontier

**Create**:
1. `scenarios/tools/OptimizeTool.tsx` — calls `useOptimizationWorkflow()` + `useEfficientFrontier()`. Strategy selector (min_variance / max_return / template dropdown). "Run Optimization" button triggers deferred execution. Maintains local `activeWeights` state (see Template deployment path above). Exit ramp "Backtest this →" passes `activeWeights` to toolContext.
2. `scenarios/tools/BacktestTool.tsx` — calls `useBacktest()` directly (not through `useOptimizationWorkflow()`). Accepts weights from two sources: (a) `toolContext.weights` from exit ramps (OptimizeTool passes optimization weights, WhatIfTool passes scenario weights), (b) manual entry. Calls `backtest.runBacktest({ weights, benchmark, period })` with whichever source is active. No optimization cache read.

**Why BacktestTool uses `useBacktest()` directly**: `useOptimizationWorkflow().handleBacktest()` hardcodes `optimization.data?.weights` as the weight source and bails if empty. BacktestTool needs to support arbitrary weights from exit ramps (What-If, Optimize) and manual entry.

**Kill**: `StrategyBuilderContainer` becomes unused. Marketplace tab becomes a Templates dropdown within OptimizeTool.

**Files**: ~2 new, 1 modified
**Risk**: Medium — BacktestTool weight-source routing adds UI complexity (source selector + validation)

### Phase 3d: Rebalance + Tax Harvest

**Create**:
1. `scenarios/tools/RebalanceTool.tsx` — calls `useTargetAllocation()`, `useSetTargetAllocation()`, `useRebalanceTrades()`, `useRiskAnalysis()`. Must subscribe to `risk-data-invalidated` eventBus events (same pattern as AssetAllocationContainer lines 193-211).
2. `scenarios/tools/TaxHarvestTool.tsx` — calls `useTaxHarvest()` (Prep C). UI-only work: tier grouping, wash sale badges, selection checkboxes, summary card.

**Modify**: `AssetAllocationContainer` keeps the allocation donut/bar display but removes the rebalance trade generation workflow (it moves to RebalanceTool). Replace with a "Rebalance →" exit ramp button that calls **both** `setActiveView('scenarios')` and `setActiveTool('rebalance')` — since `AssetAllocationContainer` renders under the `score` ViewId, the button must navigate cross-section to the scenarios view first, then set the active tool.

**Files**: ~2 new, 1 modified
**Risk**: Low-Medium — Rebalance needs eventBus wiring; Tax Harvest is new UI but hook/API exist

### Phase 3e: Exit Ramps + Cross-Tool Navigation + Intent Handlers

**Modify**:
1. Add exit ramp buttons to all 7 tool views (see exit ramp table above). **Exclude** deferred Trading exit ramps (Rebalance "Preview all trades →" and Tax Harvest "Sell for harvest →") — these are disabled/hidden until Phase 5. Also exclude "Compare scenarios" (Scenario Comparison deferred to Phase 3.5).
2. Wire intra-section navigation via `setActiveTool(toolId, context)` from uiStore
3. Pre-fill `toolContext` when navigating between tools (e.g., what-if weights → rebalance targets)
5. **Update navigation intent handlers** in `SessionServicesProvider.tsx` (lines 439-486):
   - `navigate-to-scenario-analysis` handler: currently calls only `setActiveView('scenarios')`. Must also accept optional `toolId` + `context` params and call `setActiveTool(toolId, context)` when provided.
   - `navigate-to-strategy-builder` handler: update to `setActiveView('scenarios'); setActiveTool('optimize')` since StrategyBuilder is absorbed into OptimizeTool.
   - New intent: `navigate-to-scenario-tool` — accepts `{ toolId, context }`, calls `setActiveView('scenarios'); setActiveTool(toolId, context)`. This is the primary deep-link entry point for cross-section navigation.

**Files**: ~8 modified (7 tool views + SessionServicesProvider)
**Risk**: Low-Medium — intent handler changes affect cross-section navigation contract

### Phase 3f: Cleanup

1. Delete `ScenarioAnalysisContainer` (515 lines)
2. Delete `StrategyBuilderContainer` (132 lines)
3. Delete `ScenarioAnalysis.tsx` presentational component (420 lines) — replaced by tool views
4. Remove old scenario type imports
5. Update lazy loading in `ModernDashboardApp.tsx` (ScenariosRouter is the lazy boundary)
6. Remove parallel old-container rendering added in 3a

**Note on `strategies` ViewId**: The parent plan (`FRONTEND_NAV_SYNTHESIS_PLAN.md`) keeps old ViewId aliases through Phases 1-6 and removes them in Phase 7 (cleanup). Therefore, do **not** remove the `strategies` → `scenarios` redirect in this phase. It stays as a dead alias until the parent plan's Phase 7 removes all legacy aliases together.

**Files**: ~5 modified/deleted
**Risk**: Low — deleting dead code after all tool views are live

---

## What Gets Killed

| Element | Lines | Reason |
|---------|-------|--------|
| `ScenarioAnalysisContainer` | 515 | Replaced by ScenariosRouter + tool views calling hooks directly |
| `StrategyBuilderContainer` | 132 | Absorbed into OptimizeTool + BacktestTool |
| `ScenarioAnalysis.tsx` (presentational) | 420 | Tab panels replaced by standalone tool views |
| Historical Scenarios tab | — | Was placeholder/disabled |
| Active Strategies tab | — | Was always empty |
| Strategy Marketplace tab | — | Becomes dropdown in OptimizeTool |
| `strategies` ViewId | — | Kept as redirect alias (removed in parent plan Phase 7) |

**Net**: ~1,067 lines of container/presentational code deleted. ~700-900 lines of tool view code created (thinner — no state management, just hook calls + JSX + layout). Roughly neutral on line count with dramatically better UX.

---

## What Does NOT Change

- All data-fetching hooks reused as-is, with three minor extensions: (1) `useWhatIfAnalysis` gains `initWeightInputs()` and `initDeltaInputs()` for bulk population (~10 lines total, Phase 3b), (2) `useScenarioState` gets optimization cache key fix (~10 lines, Phase 3b). No hook API breaking changes.
- Prep refactor hooks used directly (useScenarioState, useOptimizationWorkflow, useTaxHarvest)
- No backend changes, no new API endpoints
- AssetAllocationContainer stays in Dashboard (just loses the rebalance workflow, gains exit ramp)
- Lazy loading preserved (ScenariosRouter is the lazy boundary)
- Theme system (`data-visual-style`) respected in all new components
- useScenarioHistory works across tool views via useScenarioState (Prep A)

---

## Codex Review Findings — Resolution Status

### R1 Findings (original spec, 4H/3M) — All resolved:

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | High | Phase 3a can't route to old tabs (no initialTab prop) | **Revised**: 3a no longer routes to old tabs. Old containers render in parallel; tool views replace placeholders in 3b-3d. |
| 2 | High | OptimizeTool extraction source wrong (real control in StrategyBuilderContainer) | **Prep B**: `useOptimizationWorkflow()` extracts the pipeline. |
| 3 | High | usePortfolioOptimization auto-fetches on mount | **Prep B**: Deferred execution (runId pattern). No auto-fetch. |
| 4 | High | Tax Harvest missing all frontend plumbing | **Prep C**: APIService method, adapter, resolver, hook all exist. |
| 5 | Medium | What-If extraction understated (container owns currentPositions) | **Prep A**: `useScenarioState()` provides initialPositions, templates, history. |
| 6 | Medium | Rebalance depends on risk-data invalidation listener | **Addressed**: RebalanceTool spec requires eventBus subscription. |
| 7 | Medium | Router state too local for cross-section deep-linking | **Addressed**: Router state lifted to uiStore. |

### R2 Findings (revised spec, 3H/3M/1L) — All addressed in this revision:

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| R2-1 | High | TaxHarvestTool not truly UI-only — adapter shape doesn't match tiered wireframe | **Addressed**: Documented actual `TaxHarvestSourceData` shape. Tier computation (wash sale / loss threshold) is client-side in TaxHarvestTool. Estimated savings approximated as `totalHarvestableLoss * 0.30`. YTD realized gains omitted (not available from this endpoint). |
| R2-2 | High | BacktestTool specified against `useOptimizationWorkflow()` API that only backtests optimization weights | **Addressed**: BacktestTool now calls `useBacktest()` directly. Accepts weights from `toolContext.weights` (exit ramps) or manual entry only — no optimization cache read. Phase 3c updated. |
| R2-3 | High | `useScenarioState()` optimization cache key mismatch (missing `_runId`) | **Addressed**: Documented fix — change to `queryClient.getQueriesData({ queryKey: ['sdk', 'optimization'] })` prefix matching. ~10-line fix scheduled in Phase 3b. |
| R2-4 | Medium | Phase 3b risk understated — ScenarioAnalysis.tsx owns editable-position workflow, template apply, simulation controls | **Addressed**: Phase 3b risk upgraded to Medium. Documented the 420-line presentational component's internal complexity and that WhatIfTool must extract tab JSX + simulation controls. |
| R2-5 | Medium | Deep-linking incomplete — intent handlers only call `setActiveView`, not `setActiveTool` | **Addressed**: Phase 3e now includes intent handler updates in SessionServicesProvider.tsx. New `navigate-to-scenario-tool` intent. Updated existing `navigate-to-scenario-analysis` and `navigate-to-strategy-builder` handlers. |
| R2-6 | Medium | Cleanup timing — `strategies` ViewId removal conflicts with parent plan Phase 7 | **Addressed**: Phase 3f no longer removes `strategies` redirect. Kept as alias until parent plan Phase 7. |
| R2-7 | Low | Line counts stale (containers shrank from prep refactors) | **Addressed**: Updated all line counts to post-prep-refactor actuals (515, 132, 420, 407). |

### R3 Findings (revised spec, 3H/3M/1L) — All addressed in this revision:

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| R3-1 | High | Routing contract incomplete — no per-file plan for strategies alias, NavBar, keyboard shortcut, intent handlers | **Addressed**: Added "Routing Alias & Legacy Path Plan" table documenting all 5 files with per-file Phase 3 change plan. |
| R3-2 | High | What-If extraction model mismatch — spec says "extract from ScenarioAnalysis" but ScenarioAnalysis owns array-based position model vs hook's record model | **Addressed**: Added "Extraction model — two layers to reconcile" section. Decision: Option A (use hook's record-based model directly). ScenarioAnalysis.tsx position model not ported. |
| R3-3 | High | BacktestTool fallback wrong — cannot read optimization cache from another hook instance post-Prep B | **Addressed**: Removed optimization cache read entirely. BacktestTool only gets weights from `toolContext.weights` (exit ramps) or manual entry. No `useOptimizationWorkflow()` or `usePortfolioOptimization()` calls. |
| R3-4 | Medium | StressTestTool missing `useStressScenarios()` — needs separate hook for scenario catalog dropdown | **Addressed**: Added `useStressScenarios()` to StressTestTool hook specification (L93-102, separate query hook from same file). |
| R3-5 | Medium | RebalanceTool under-specified — `useRebalanceTrades()` accepts ticker-level weights but drift table is asset-class level | **Addressed**: Documented `buildTickerTargetWeights()` extraction from AssetAllocationContainer (L266-299), `effectiveTargetMap` logic, drift computation, validation. ~80 lines to extract. |
| R3-6 | Medium | Tax Harvest `estimatedTaxSavings` note inaccurate — adapter has no such field | **Addressed**: Corrected to state savings are computed entirely client-side (`totalHarvestableLoss * 0.30`). Neither adapter nor type has `estimatedTaxSavings`. |
| R3-7 | Low | Scenario Comparison deferral = parent plan deviation — not called out | **Addressed**: Added explicit deviation note with rationale (no UI to extract, no plumbing, not blocking advisor workflows). Recommend Phase 3.5. |

### R4 Findings (revised spec, 2H/3M/1L) — All addressed in this revision:

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| R4-1 | High | Routing alias table misses `AppSidebar.tsx` L37 (primary nav, default layout is sidebar) and `uiStore.ts` L80 (`ViewId` type union — source of truth) | **Addressed**: Added both files to routing alias table. AppSidebar is the primary nav surface (sidebar is default layout). uiStore owns the ViewId type. |
| R4-2 | High | Phase 3e exit ramps reference `Trading` route that doesn't exist — no `trading` ViewId, parent plan places Trading in Phase 5 | **Addressed**: Rebalance "Preview all trades →" and Tax Harvest "Sell for harvest →" marked as deferred/disabled until Phase 5 delivers the Trading view. Note added to exit ramp table. |
| R4-3 | Medium | StressTestTool "Hedge this risk →" exit ramp needs hedge recommendations from `useHedgingRecommendations()`, not from stress test hooks | **Addressed**: Added `useHedgingRecommendations()` to StressTestTool hook list. Exit ramp table updated to show defensive ETFs come from this hook. |
| R4-4 | Medium | `useWhatIfAnalysis()` has no bulk `setWeightInputs`/init API — can't populate from `initialPositions` or templates without per-entry iteration | **Addressed**: Documented bulk initialization gap. Recommended extending hook with `initWeightInputs()` method (~5 lines) in Phase 3b. Alternative bridge-effect approach documented. |
| R4-5 | Medium | Hook table says `useTaxHarvest()` provides "estimated savings" but hook returns `data`/`flags`/`runTaxHarvest` — no savings field | **Addressed**: Corrected hook table description to match actual return shape. Estimated savings are client-side (documented in TaxHarvestTool section). |
| R4-6 | Low | `NavigationIntents.ts` path ambiguous — legacy `navigation/NavigationIntents.ts` exists separately | **Addressed**: Specified full path `connectors/src/utils/NavigationIntents.ts` with note distinguishing from legacy file. |

### R5 Findings (revised spec, 2H/3M/1L) — All addressed in this revision:

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| R5-1 | High | Phase 3a fallback path not implementable — replacing ScenarioAnalysisContainer with ScenariosRouter loses functionality until 3b-3d ship | **Addressed**: Added explicit fallback mechanism — ScenariosRouter renders old containers inline for tools not yet built. Each fallback branch is replaced as tool views ship in 3b-3d. Phase 3f deletes all fallback branches. |
| R5-2 | High | Router state reset clobbers `activeTool` when navigating between `scenarios` and `strategies` ViewIds | **Addressed**: Reset condition now treats both `scenarios` and `strategies` as "inside the section". Reset only fires when activeView is neither. Documented in routing strategy and Phase 3a uiStore spec. |
| R5-3 | Medium | `useScenarioState` hook table says "optimizationCache" but hook returns `optimizationData`, plus undocumented APIs (`pendingHistoryTracking`, `handleRunStressTest`, `handleRunMonteCarlo`) | **Addressed**: Hook table updated to match actual `UseScenarioStateReturn` interface. Cache key note renamed to "optimizationData". |
| R5-4 | Medium | BacktestTool weight sources contradicted — R2 resolution row says 3 sources, wireframe says "from optimization / manual entry / current" | **Addressed**: R2 resolution row corrected to 2 sources only. Wireframe label changed to "from exit ramp / manual entry". |
| R5-5 | Medium | Exit ramp table missing What-If → Backtest ("Backtest this →" in wireframe but not in table) | **Addressed**: Added What-If → Backtest row to exit ramp table with `toolContext.weights` context. |
| R5-6 | Low | "All hooks reused as-is" contradicts planned `initWeightInputs()` extension and `useScenarioState` cache fix | **Addressed**: Updated to "reused as-is with two minor extensions" and listed both. No breaking changes. |

---

### R6 Findings (revised spec, 1H/3M/1L) — All addressed in this revision:

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| R6-1 | High | Trading deferral contradictory — Phase 3e says "wire cross-section to Trading", wireframes show active trading buttons, but no `trading` ViewId exists | **Addressed**: Phase 3e updated to explicitly exclude deferred exit ramps. Wireframe buttons marked "(deferred — Phase 5)". Exit ramp table now has Status column showing which phase each ramp ships in. |
| R6-2 | Medium | Exit ramp table incomplete/inconsistent — includes deferred "Compare scenarios", missing Optimize "Set target →" and StressTest "Run Monte Carlo →" from wireframes | **Addressed**: Added all missing exit ramps to table. Added Status column. Deferred items clearly marked with target phase. |
| R6-3 | Medium | `useHedgingRecommendations(weights, portfolioValue?)` signature undocumented — spec doesn't say what StressTestTool passes | **Addressed**: Full signature documented in StressTestTool hook spec. Weights sourced from `initialPositions` converted to weight record. |
| R6-4 | Medium | Tax Harvest wireframe shows "YTD realized gains" but spec says it's not available from the endpoint | **Addressed**: Wireframe updated to show "Positions analyzed" (from `positionsAnalyzed`/`dataCoveragePct`) instead. YTD gains note updated to say "omitted from wireframe". |
| R6-5 | Low | `strategies` alias `defaultTool='optimize'` unclear when it applies — could clobber active tool on re-entry | **Addressed**: Routing table specifies `defaultTool` only applies on initial entry (when `activeTool` is `'landing'`). If user already has an active tool, it's preserved. |

### R7 Findings (revised spec, 2H/2M) — All addressed in this revision:

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| R7-1 | High | Phase 3a only defines fallbacks for what-if and optimize, but there are 7 cards — stress-test, monte-carlo, backtest, rebalance, and tax-harvest have no defined fallback | **Addressed**: Expanded fallback map to all 7 tools. Stress-test/monte-carlo → ScenarioAnalysisContainer. Backtest → StrategyBuilderContainer. Rebalance → AssetAllocationContainer. Tax-harvest → TaxHarvestPlaceholder (simple "Coming soon" card since no legacy UI exists). |
| R7-2 | High | Rebalance exit ramps pass ticker-level weights but RebalanceTool is an asset-class editor — no ticker→asset-class reverse mapping | **Addressed**: RebalanceTool now has two input modes. Asset-class mode (default, from drift table) uses extracted `buildTickerTargetWeights()`. Ticker-weight mode (from exit ramps) bypasses asset-class editor and passes weights directly to `useRebalanceTrades()`. Mode detected from `toolContext.weights` presence. |
| R7-3 | Medium | AssetAllocationContainer exit ramp calls `setActiveTool('rebalance')` but is rendered under `score` ViewId — doesn't navigate to scenarios | **Addressed**: Exit ramp now calls both `setActiveView('scenarios')` and `setActiveTool('rebalance')` for cross-section navigation. |
| R7-4 | Medium | Tax Harvest wireframe per-row `[Sell →]` buttons are Trading exits not in exit ramp table and not marked deferred | **Addressed**: Removed per-row `[Sell →]` buttons from wireframe. Selection checkboxes remain — bulk sell is already marked deferred at bottom. |

### R8 Findings (revised spec, 1H/1M) — All addressed in this revision:

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| R8-1 | High | Weight unit mismatch — `initialPositions.weight` is percentage points (60), APIs expect decimal fractions (0.60). Current ScenarioAnalysis.tsx divides by 100 at L190; spec doesn't mention this conversion | **Addressed**: Added "Weight unit conversion" section to WhatIfTool spec. Documented that `initialPositions.weight` must be divided by 100 before storing in `weightInputs` or passing to `useHedgingRecommendations()`. Flagged as critical correctness requirement. |
| R8-2 | Medium | TaxHarvestTool has no execution trigger — hook mounts idle, wireframe shows results but no "Run" button or auto-run behavior | **Addressed**: Documented auto-run-on-mount behavior via `useEffect` calling `runTaxHarvest()` when component mounts with a loaded portfolio. Loading spinner during fetch. Deferred execution prevents double-fetch on re-navigation. |

### R9 Findings (revised spec, 2H/2M) — All addressed in this revision:

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| R9-1 | High | Weight unit rules incomplete — spec says "divide by 100" but templates are already decimal, and hook tests expect decimal strings like "0.25". Following spec literally over-converts templates or under-converts user input | **Addressed**: Replaced single conversion rule with explicit per-source rules: initialPositions ÷100, templates as-is (already decimal), user input "60" → "0.60". Documented that `weightInputs` stores decimal string representations. |
| R9-2 | High | `hedge-overlay` template carries both `new_weights` and `delta` but `runScenarioFromInputs()` only emits one. Following Option A literally drops half the template | **Addressed**: Added "Template execution path" section. Templates call `runScenario()` directly with `apiScenario` (not `runScenarioFromInputs()`). `initWeightInputs()` populates display only. Matches existing ScenarioAnalysis.tsx pattern (L258). |
| R9-3 | Medium | History tracking requires `pendingHistoryTracking.trackWhatIf(params)` before running — spec says tools "call hooks directly" but doesn't document the tracking contract | **Addressed**: Added "History tracking contract" section documenting the two-step pattern. WhatIfTool calls `trackWhatIf()` before `runScenario()`. Same pattern for StressTestTool/MonteCarloTool. `useScenarioState()` args include result data for effect-based recording. |
| R9-4 | Medium | `totalHarvestableLoss` and per-candidate `totalLoss` are negative numbers — spec's savings formula yields negative result without `Math.abs()` | **Addressed**: Added `Math.abs()` to savings formula. Documented that loss values are negative throughout. Tier computation notes updated. |

### R10 Findings (revised spec, 2H) — All addressed in this revision:

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| R10-1 | High | OptimizeTool template path not implementable — `handleOptimize()` with template weights calls `backtest.runBacktest()` and returns, never populates `optimizationData`. Weights table and exit ramps have no data source for template selections | **Addressed**: Added "Template deployment path" section. OptimizeTool maintains local `activeWeights` state populated from either `optimizationData.weights` (after optimization) or `template.tickerWeights` (after template selection). All downstream reads (table, exit ramps, backtest) use `activeWeights`. |
| R10-2 | High | StressTest → What-If hedge exit ramp has no conversion contract — `useHedgingRecommendations()` returns `HedgeStrategy[]` with `{ hedgeTicker, suggestedWeight }`, not a What-If payload. Spec doesn't say which strategy to pick or how to convert | **Addressed**: Added hedge conversion section after StressTestTool wireframe. Sorts by `details.riskReduction` descending, picks best. Converts to delta scenario: `{ [hedgeTicker]: "+X%" }`. WhatIfTool receives in `toolContext`, populates `deltaInputs`, sets `inputMode='deltas'`. Button disabled if no strategies returned. |

### R11 Findings (revised spec, 2H) — All addressed in this revision:

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| R11-1 | High | OptimizeTool still references `optimizationData.weights` in exit ramp descriptions and Phase 3c, contradicting the `activeWeights` local state pattern | **Addressed**: All downstream references changed to `activeWeights`. Exit ramp table, Phase 3c description, BacktestTool source #1 all updated. |
| R11-2 | High | What-If exit ramps (Backtest, Rebalance) have no resolved weight source after delta-based runs — `weightInputs`/`deltaInputs` are inputs, not post-scenario weights | **Addressed**: Added "What-If weight resolution" section. Uses existing `deriveOptimizedPositions()` from `useScenarioOrchestration.ts` to extract resolved weights from `whatIfData.scenario_results.position_changes[].after`. Exit ramps disabled until scenario is run. |

### R12 Finding (revised spec, 1H) — Addressed in this revision:

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| R12-1 | High | Hedge strategies array not sorted cross-strategy — `HedgingAdapter` picks best per driver but returns in `drivers` order. `hedgingStrategies[0]` is arbitrary, not deterministically "best" | **Addressed**: StressTestTool now sorts by `details.riskReduction` descending before picking. Sort code added to hedge conversion section. |

Also updated R10-2 resolution to remove stale "pre-sorted by adapter" claim.

### R13 Findings (final review, 2H) — All addressed in this revision:

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| R13-1 | High | `hedge-overlay` template has both `new_weights` and `delta` but backend (`scenario_service.py:198`) rejects requests with both — template is broken as-is | **Addressed**: Documented as pre-existing bug. Phase 3b fix: modify `hedge-overlay` to delta-only mode (remove `new_weights`). Backend applies deltas relative to current portfolio, achieving same overlay intent. |
| R13-2 | High | Hedge exit ramp code sample still uses `hedgingStrategies[0]` (unsorted) and claims hook returns `HedgeStrategy[]` directly, but hook returns `{ data: HedgeStrategy[] | undefined, ... }` | **Addressed**: Rewrote entire hedge conversion section. Correct hook destructuring `{ data: hedgeStrategies }`. Sort by `riskReduction` descending, then pick `sorted[0]`. Complete code sample with guard for empty/undefined. |

### R14 Findings (confirmation review, 1H/1M) — All addressed in this revision:

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| R14-1 | High | Delta-prefill into What-If not implementable — spec adds `initWeightInputs()` but not `initDeltaInputs()`. Hedge exit ramp and delta-only hedge-overlay template have no bulk delta setter | **Addressed**: Added `initDeltaInputs()` alongside `initWeightInputs()` (~10 lines total). Both set respective inputs and switch `inputMode`. Hedge exit ramp updated to call `initDeltaInputs(toolContext.deltas)`. |
| R14-2 | Medium | `toolContext` clearing semantics unspecified — stale exit-ramp data can leak into later tool launches | **Addressed**: Added clearing contract. `setActiveTool(tool)` without context clears `toolContext` to `{}`. `resetToLanding()` clears both. Tools check for presence, not truthiness. |

## Verification

After each sub-phase:
```bash
cd frontend && npx tsc --noEmit  # Zero TypeScript errors
cd frontend && pnpm exec vitest run  # All tests pass
```

Final verification: manual walkthrough of all 7 tool cards → full-width views → exit ramps.

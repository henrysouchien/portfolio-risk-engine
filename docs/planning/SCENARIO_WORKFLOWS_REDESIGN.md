# Scenario Workflows Redesign — Architecture Document

## Vision

Transform the Scenarios page from a collection of disconnected tools into **purpose-driven workflows** where users describe what they're trying to accomplish, receive curated tool sequences, and get contextual interpretation at every step.

**Three layers, one experience:**
1. **Purpose-driven entry** — hybrid landing: curated workflow cards + open-ended AI chat
2. **Contextual interpretation** — layered: inline flag-based callouts (deterministic, no API call) + AI chat for deeper questions
3. **Connected end-to-end flows** — workflow templates that chain tools with typed context passing

## Current State

### What works well
- 8 scenario tools (6 implemented, 2 placeholder) with clean tool pattern
- Tools can pass context via `onNavigate(tool, {weights, deltas, ...})` — chaining already exists
- All MCP tools return agent-format responses with interpretive flags
- `:::ui-blocks` + artifact mode for AI→React rendering
- Gateway SSE chat with full tool access
- Cross-view deep linking (`setActiveView` + `setActiveTool`)

### What's missing
- Landing page is "pick a tool" — requires users to know which tool they need
- Results have no interpretation — user sees numbers, has to figure out meaning
- Exit ramps are static ("Backtest this →") — no context-aware next-step suggestion
- AI chat is disconnected from tool context — opening chat doesn't know what you just ran

## Architecture

### Tool Contract

Before workflows can chain tools, each tool needs a standardized contract. Today tools have ad-hoc props and informal context passing. The contract formalizes this:

```typescript
/**
 * Every scenario tool implements this contract.
 * Tools remain standalone components — the contract just standardizes
 * how workflows interact with them.
 */
interface ScenarioToolContract {
  // What the tool accepts as input (from previous step or landing)
  inputSchema: {
    weights?: Record<string, number>;     // portfolio weights
    deltas?: Record<string, number>;      // weight changes
    scenarioId?: string;                  // pre-selected scenario
    mode?: 'absolute' | 'deltas';         // tool mode
    [key: string]: unknown;               // tool-specific params
  };

  // What the tool produces as output (for next step)
  outputSchema: {
    weights?: Record<string, number>;     // resulting weights
    riskMetrics?: {                       // risk impact
      volatility?: number;
      sharpe?: number;
      maxDrawdown?: number;
      beta?: number;
    };
    flags?: Array<{                       // interpretive flags
      type: string;
      severity: 'error' | 'warning' | 'info' | 'success';
      message: string;
      details?: string;
    }>;
    raw?: unknown;                        // full tool-specific result
  };

  // Tool completion state
  status: 'idle' | 'loading' | 'complete' | 'error';
}
```

**Implementation**: Tools don't need to be rewritten. A thin adapter layer (`useToolContract(toolResult)`) extracts the standardized output from each tool's existing result hook. This is a new shared hook, not changes to individual tools.

### Snapshot Semantics

Workflows operate on a **frozen portfolio snapshot** taken at workflow entry:

```typescript
interface WorkflowSession {
  id: string;
  workflowId: string;
  startedAt: string;
  portfolioSnapshot: {                    // frozen at workflow start
    weights: Record<string, number>;
    totalValue: number;
    positionCount: number;
  };
  currentStep: number;
  stepResults: Array<{                    // accumulated results
    toolId: ScenarioToolId;
    output: ScenarioToolContract['outputSchema'];
    completedAt: string;
  }>;
  status: 'active' | 'completed' | 'abandoned';
}
```

**Snapshot scope**: The snapshot captures portfolio weights and value at workflow entry for **context passing between steps** (e.g., "these are the weights we're analyzing"). It does NOT override backend execution — `useStressTest`, `useMonteCarlo`, etc. still run against the live portfolio on the backend. This is intentional: the snapshot ensures UI consistency across workflow steps, while the backend always uses current market data for accurate calculations. A future enhancement could pass snapshot weights to backend tools, but this is not required for v1.

**Storage**: `WorkflowSession` lives in a dedicated Zustand slice (not jammed into `uiStore`). Persists across tab switches within the session. Not persisted to localStorage — workflows are ephemeral.

### State Architecture

Workflow state is separated from UI navigation state:

```
uiStore (existing)
  ├─ activeView: ViewId
  ├─ activeTool: ScenarioToolId
  └─ toolContext: Record<string, unknown>

workflowStore (new, separate Zustand slice)
  ├─ activeSession: WorkflowSession | null
  ├─ chatContext: ToolSnapshotContext | null    // for AI chat pre-seeding
  └─ actions:
      ├─ startWorkflow(definition, portfolioSnapshot)
      ├─ completeStep(output)
      ├─ goToStep(index)
      ├─ abandonWorkflow()
      └─ setChatContext(snapshot)
```

The workflow store manages session state. The UI store manages navigation. They coordinate but don't entangle — `startWorkflow` calls `setActiveTool(firstStep)` as a side effect.

## Layer 1: Purpose-Driven Entry

### Hybrid Landing Page

Two entry paths on the redesigned landing:

**A. Workflow Cards** — curated, purpose-driven sequences:

| Workflow | Description | Steps | Prerequisite |
|----------|-------------|-------|--------------|
| Recession Prep | "How would my portfolio handle a downturn?" | Stress Test → Hedge | None |
| Optimize & Backtest | "Find a better allocation and test it" | Optimize → What-If → Backtest | None |
| Rebalance & Execute | "Model a change, then generate trades" | What-If → Rebalance | None |
| Hedge My Risk | "Find and implement hedges for current exposures" | Hedge | None |
| Portfolio Checkup | "Full health check" | Stress Test → Monte Carlo | None |

Cards only appear when their prerequisites are met and their constituent tools are fully implemented.

**Note**: Only workflows whose constituent tools are fully implemented are offered. Workflows touching Tax Harvest or other placeholder tools are excluded until those tools ship.

**B. AI Entry Point** — prominent "Ask AI" input at top:
- Routes to the existing AI chat with Scenarios context
- AI has access to all scenario MCP tools and can orchestrate them
- Not a new intent classifier — it's the existing chat with a focused prompt
- Examples shown as placeholder text: "What would happen if rates rise 2%?"

**C. All Tools** — existing tool grid below, for direct access.

### Workflow Definition

```typescript
interface WorkflowDefinition {
  id: string;
  title: string;
  description: string;
  icon: LucideIcon;
  prerequisite?: () => boolean;           // hide card if unmet
  steps: WorkflowStep[];
}

interface WorkflowStep {
  toolId: ScenarioToolId;
  label: string;
  contextFromPrevious?: (                 // typed transform — prevOutput is null if step was skipped
    prevOutput: ScenarioToolContract['outputSchema'] | null,
    session: WorkflowSession,
  ) => Record<string, unknown>;
  optional?: boolean;                     // can be skipped
}
```

`contextFromPrevious` replaces the untyped `contextBuilder(prevResult: unknown)`. It receives typed output from the previous step's contract and the full session (for access to the portfolio snapshot).

### Context consumption reality

Not all tools consume inbound context today:

| Tool | Consumes `context` prop? | Notes |
|------|--------------------------|-------|
| What-If | **Yes** — reads `context.weights`, `context.deltas`, `context.mode` | Full context consumer |
| Backtest | **Yes** — reads `context.weights` | Full context consumer |
| Optimize | **Partial** — reads some context but mostly self-driven | |
| Rebalance | **Yes** — reads `context.weights` into trade generation via `AssetAllocationContainer` | Full context consumer for ticker targets |
| Stress Test | **No** — derives all state from `useStressTest()` + `useScenarioState()` | Ignores inbound context |
| Monte Carlo | **No** — derives from its own hooks | Ignores inbound context |
| Hedge | **No** — derives from `useStressTest()` + `useHedgingRecommendations()` | Ignores inbound context |

**v1 workflow model**: Workflows are **guided sequential navigation**, not piped data chains. The value is: a curated sequence of tools with progress tracking, insight interpretation, and suggested next steps. Tools that don't consume context simply run against the live portfolio — which is correct for most workflows (Stress Test → Hedge: "stress test your portfolio, then explore hedges for it" — both use the same live portfolio).

**True data chaining** (e.g., "optimize, then backtest the optimized weights") only works between tools that already consume context (What-If ↔ Backtest ↔ Optimize). These are the tools where `contextFromPrevious` is meaningful. For other tools, `contextFromPrevious` is omitted and the tool runs standalone.

**Future enhancement**: Add context consumption to StressTest/MonteCarlo/Hedge tools so they can receive weights from a previous step. This would enable flows like "optimize → stress test the optimized allocation" where the stress test runs against proposed weights instead of current holdings.

## Layer 2: Contextual Interpretation

### Inline Insight Cards (flag-based, not AI)

Every tool result page gets an **Insight Card** — a compact callout rendered from the tool's interpretive flags. This is **deterministic template rendering**, not AI generation. No API call, no latency.

```
┌──────────────────────────────────────────────┐
│ Key Finding                                   │
│                                               │
│ Your portfolio's worst-case loss (-22%) is    │
│ driven by interest rate exposure (67.6%).     │
│ The mortgage REIT concentration amplifies it. │
│                                               │
│ [Ask AI about this →]    [Hedge Analysis →]   │
└──────────────────────────────────────────────┘
```

**Flag priority**: Render the highest-severity flag first (`error` > `warning` > `info` > `success`). If multiple flags at the same severity, show them in the order the backend emits them (backend already sorts by relevance). Max 2 flags shown (truncate with "N more findings"). Ranking does not depend on metadata fields like `percent_of_portfolio` — flag ordering is delegated to the backend's existing `_sort_flags()` logic.

**Next-step suggestions**: Each flag type maps to a suggested next tool. When multiple flags suggest different tools, show the one matching the highest-severity flag. If inside a workflow, the next step from the workflow definition takes priority over the flag suggestion.

```typescript
interface InsightMapping {
  flagType: string;
  render: (flag: Flag, context: ToolOutput) => string;
  suggestedTool?: ScenarioToolId;
  suggestedLabel?: string;
}
```

**When no flags exist**: Show a positive summary ("Portfolio is within risk limits. No significant issues detected.") with no next-step suggestion.

### Chat Integration

"Ask AI about this →" opens the existing AI chat with structured context:

```typescript
interface ToolSnapshotContext {
  toolId: ScenarioToolId;
  toolLabel: string;
  timestamp: string;
  summary: string;                        // 1-line result summary
  flags: Array<{ type: string; severity: string; message: string }>;
  keyMetrics: Record<string, number>;     // tool-specific metrics
}
```

This context is passed as a **structured user message** (not system prompt injection) when the chat opens:

```
[Scenario context: User ran Stress Test. Result: -22% market crash impact.
Key metrics: worst_loss=-22%, interest_rate_contribution=67.6%.
Flags: high_interest_rate_exposure (warning), concentration_warning (warning).]

How can I help you understand these results?
```

**Why user message, not system prompt**: Avoids prompt bloat, stale context, and precedence conflicts. The context is visible in the chat history. If the user runs another tool, a new context message is sent — no cleanup needed.

## Layer 3: Connected End-to-End Flows

### Workflow Progress Bar

When inside a workflow, a persistent bar appears above the tool view:

```
┌──────────────────────────────────────────────────────────┐
│ Recession Prep                                    Exit ✕ │
│ ● Stress Test  ○ Hedge Analysis                          │
│ Step 1 of 2                         [Next: Hedge →]      │
└──────────────────────────────────────────────────────────┘
```

- Step dots: filled = completed, outlined = pending, highlighted = current
- "Next" button: disabled until current tool status is `'complete'`
- Back navigation: click completed steps to revisit. **Rerunning a step invalidates all downstream `stepResults`** — later steps are marked incomplete and must be re-executed with fresh context.
- "Exit": confirms if results exist ("You have unsaved results. Leave workflow?"), then `abandonWorkflow()`
- Optional steps show a "Skip →" alternative to "Next →"

### Execution Boundary

Workflows that end in execution (Rebalance, Hedge) have an **explicit approval checkpoint** before any trades:

```
┌──────────────────────────────────────────────────────────┐
│ ⚠ Review Before Executing                                │
│                                                          │
│ This workflow will generate real trades.                  │
│ Review the proposed trades carefully before proceeding.   │
│                                                          │
│ [Review Trades →]                    [Cancel]             │
└──────────────────────────────────────────────────────────┘
```

The `HedgeWorkflowDialog` and rebalance execution dialogs already have their own review steps (Steps 3-4 in the hedge dialog). The workflow progress bar transitions to "Execute" which opens the appropriate execution dialog — the workflow never auto-executes.

### Error Handling

| Failure | Behavior |
|---------|----------|
| Tool API error | Tool shows its own error state. Workflow bar shows "Retry" instead of "Next". Step result not saved. |
| Tool timeout | Same as API error. No automatic retry. |
| Portfolio changes mid-workflow | Tools that consume context (What-If, Backtest) use the passed weights, unaffected by live changes. Tools that ignore context (Stress Test, Monte Carlo, Hedge) will reflect live portfolio changes. This is acceptable for v1 — the workflow bar provides continuity but does not guarantee identical portfolio state across all steps. |
| Skip + downstream dependency | If a step is skipped, `contextFromPrevious` receives `null` as `prevOutput`. The function must handle this — return empty context `{}` so the downstream tool runs standalone (same as launching from landing). Tools already handle missing context gracefully (they derive state from their own hooks). |
| Browser refresh mid-workflow | Workflow session lost (not persisted). Tool reopens standalone (no workflow bar) via hash restore. Acceptable for v1. |
| Navigate to rebalance with weights | The rebalance route consumes `context.weights` as imported ticker targets. Users can reset back to saved asset-class targets before generating trades. |

## Implementation Phases

### Phase 0: Tool Contract + Snapshot + Flag Threading (foundation)
- Define `ScenarioToolContract` types
- Create `useToolContract()` shared hook that extracts standardized output from each tool's result
- Create `workflowStore` Zustand slice with `WorkflowSession`
- **Flag threading**: Scenario source types (`WhatIfSourceData`, `BacktestSourceData`, etc.) in `catalog/types.ts` currently don't carry `flags`. Phase 0 must add optional `flags` to these types and thread backend flags through adapters. Without this, Phase 2 (Insight Cards) has no data. The backend already returns flags in agent-format responses — the gap is adapter/type-level, not backend.
- **Rebalance tool support**: The `rebalance` route consumes inbound scenario `weights` as imported ticker targets, keeping scenario-to-trade flows intact while preserving a reset path back to saved asset-class targets.
- **Refresh behavior**: On browser refresh, `activeTool` is restored from URL hash but `WorkflowSession` is lost. Phase 0 adds orphan detection: if `activeTool` is set but no `activeSession` exists in `workflowStore`, the tool renders standalone (no workflow bar). This is the current behavior and is acceptable.
- Audit existing flags across all 6 implemented tools — document flag types, severity, coverage gaps
- **This phase has no UI changes but establishes the architecture. Phase 1 depends on it.**
- ~5-7 files

### Phase 1: Workflow Cards + Progress Bar
- Redesign `ScenariosLanding.tsx` — workflow cards section + "All Tools" section
- Define 4-5 `WorkflowDefinition` objects (only using implemented tools)
- Create `WorkflowProgressBar` component
- Wire `startWorkflow` → `completeStep` → `goToStep` flow
- Execution boundary checkpoint for trade-ending workflows
- ~5-6 files

### Phase 2: Inline Insight Cards
- Create shared `InsightCard` component
- Define `InsightMapping` registry (flag type → narrative + next step)
- Integrate into each tool's result view (6 tools)
- Flag priority logic (severity ordering, backend emission order for same-severity)
- ~8-10 files (shared component + per-tool integration)

### Phase 3: Chat Context
- Add `chatContext` to `workflowStore`
- Tools populate `chatContext` on result
- AI chat reads context on open and sends as structured user message
- "Ask AI about this →" button in InsightCard
- ~3-4 files

### Phase 4: AI Entry Point
- Add "Ask AI" input to landing page
- Routes to existing AI chat with Scenarios-focused system prompt
- AI uses existing MCP tools to orchestrate
- ~2-3 files

### Phase 5: Comparison View
- Add a landing-level recent-run comparison panel backed by persisted scenario history
- Reuse existing run metadata and normalized comparison rows for What-If, Stress, and Monte Carlo
- Dedicated `compare_scenarios` MCP orchestration can remain optional for a later richer compare surface

## What does NOT change

- Individual tool components — they stay as-is, workflow is an overlay
- MCP tools / backend — no changes
- HedgeWorkflowDialog — reused as-is within the hedge tool
- Existing exit ramp buttons — remain functional, insight cards supplement them

## Key Design Decisions

1. **Workflows are sequences, not new tools.** They orchestrate existing tools with a progress overlay. No tool logic duplication.

2. **Inline insights are deterministic, not AI.** Flag-based template rendering. Fast, predictable, no latency. AI is available on demand via chat.

3. **Chat context is a user message, not system prompt injection.** Visible in history, no bloat, no stale context.

4. **Portfolio snapshot is advisory, not enforced.** The snapshot captures weights at workflow start for context-passing tools (What-If, Backtest). Tools that derive state from live data (Stress Test, Monte Carlo, Hedge) may reflect portfolio changes mid-workflow. This is acceptable for v1.

5. **Explicit execution boundary.** Workflows never auto-execute trades. The existing execution dialogs (HedgeWorkflowDialog, etc.) serve as the approval checkpoint.

6. **Phase 0 establishes architecture before UI.** Tool contracts and state management come first. Progress bar and cards build on a real foundation, not cosmetic wiring.

7. **Only implemented tools in workflows.** Workflows touching placeholder tools (Tax Harvest) are excluded until those tools are properly implemented. No broken paths.

8. **Separate state stores.** Workflow session state lives in its own Zustand slice, not crammed into `uiStore`. Clean lifecycle, no entanglement.

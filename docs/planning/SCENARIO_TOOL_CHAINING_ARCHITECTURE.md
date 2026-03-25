# Scenario Tool Chaining Architecture

> **v1** — Codex-reviewed FAIL (6 findings). **STATUS: DEFERRED** — revisit after MC cross-view context plan + individual tool redesigns (backtest, optimization) land. Building bottom-up: let each tool wire its own chaining first, then extract the common protocol from what actually works.
>
> **Depends on**: `MONTE_CARLO_CROSS_VIEW_CONTEXT_PLAN.md` (frontend threading), `BACKTEST_TOOL_REDESIGN_PLAN.md`, `OPTIMIZATION_TOOL_REDESIGN_PLAN.md`.
>
> **Codex findings to address on revisit**: (1) MC frontend threading is required, not "zero backend changes"; (2) legacy source strings need compat layer; (3) workflow store `ScenarioWorkflowStepOutput` needs `nextContext` field; (4) context envelope needs provenance metadata (`portfolioId`, `createdAt`); (5) missing Backtest→What-If path; (6) rename discriminant to avoid `mode` collision with `ScenarioToolContractInput`.

## Context

The 6 scenario tools (What-If, Optimize, Backtest, Stress Test, Monte Carlo, Hedge) work individually but chain poorly. Today, only the **right half** of the analytical flow works: Optimize -> What-If -> Backtest -> Rebalance (weight passing). The **left half** — where risk intelligence flows from Stress Test/Monte Carlo into downstream tools — is broken: empty contexts, ignored props, missing `contextFromPrevious` in workflows.

This plan defines a **typed chaining protocol** that each tool redesign adopts incrementally. No big-bang migration — each tool picks up its piece as it gets redesigned.

**Key finding: zero backend changes needed.** All tools already accept the parameters they need on the backend. The gaps are purely frontend context wiring.

### Current State Audit

**What works (weight-based chaining):**
- Optimize -> What-If: `{ weights }` via `onNavigate`
- Optimize -> Backtest: `{ weights }` via `onNavigate`
- What-If -> Backtest: `{ weights }` via `onNavigate`
- Hedge -> What-If: `{ mode: "deltas", deltas, label, source }` via `onNavigate`
- All above -> Rebalance: `{ weights, label, source }` via `onNavigate`

**What's broken:**
- Stress Test -> Hedge: passes `{ label, source }` only — no impact data, no shocks, no weights
- Stress Test -> Monte Carlo: passes `{}` (empty)
- Monte Carlo -> Optimize: passes `{}` (empty)
- Optimize ignores incoming context: `context: _context`
- Monte Carlo ignores incoming context: `void context`
- Stress Test ignores incoming context: `context: _context`
- Workflow `contextFromPrevious`: only "Optimize & Validate" wires context; "Recession Prep" and "Portfolio Checkup" pass nothing

**Backend parameter support:**

| Tool | Accepts weights in? | Returns resolved_weights? | Agent format? | delta_changes? |
|------|:---:|:---:|:---:|:---:|
| What-If | `target_weights` / `delta_changes` | Yes | Yes | Yes |
| Backtest | `weights` / `delta_changes` | Yes | Yes | Yes |
| Monte Carlo | `resolved_weights` | No (terminal) | Yes | No |
| Optimization | No | Yes | Yes | No |
| Stress Test | No | No | No | No |

---

## The Protocol: 4 Context Shapes

Today's `toolContext: Record<string, unknown>` is untyped. The protocol adds a `mode` discriminant that makes contexts self-describing. Backward compatible — tools that check `context.weights` directly keep working.

### Shape 1: `WeightsContext` (allocation passing)
```typescript
interface WeightsContext {
  mode: 'weights';
  weights: Record<string, number>;
  label: string;
  source: ToolChainSource;
  riskMetrics?: {
    volatility?: number;
    sharpe?: number;
    maxDrawdown?: number;
  };
}
```
**Used by:** Optimize/What-If/Backtest -> any tool that accepts weights

### Shape 2: `DeltaContext` (overlay modifications)
```typescript
interface DeltaContext {
  mode: 'deltas';
  deltas: Record<string, string>;
  label: string;
  source: ToolChainSource;
}
```
**Used by:** Hedge -> What-If

### Shape 3: `RiskFindingContext` (risk intelligence)
```typescript
interface RiskFindingContext {
  mode: 'risk-finding';
  label: string;
  source: ToolChainSource;
  finding: {
    severity: 'low' | 'moderate' | 'severe';
    impactPct?: number;
    impactDollar?: number;
    probabilityOfLoss?: number;
    var95?: number;
    cvar95?: number;
    worstPosition?: { ticker: string; impactPct: number };
    scenarioName?: string;
    scenarioShocks?: Record<string, number>;
  };
  suggestedAction?: string;
}
```
**Used by:** Stress Test -> Hedge, Monte Carlo -> Optimize

### Shape 4: `SimConfigContext` (simulation parameter hints)
```typescript
interface SimConfigContext {
  mode: 'sim-config';
  label: string;
  source: ToolChainSource;
  weights?: Record<string, number>;
  simParams?: {
    portfolioValue?: number;
    volScale?: number;
    distribution?: 'normal' | 't' | 'bootstrap';
  };
}
```
**Used by:** Stress Test -> Monte Carlo, What-If/Optimize -> Monte Carlo

### Helper utilities

```typescript
type ToolChainSource = 'optimize' | 'what-if' | 'backtest' | 'stress-test' | 'monte-carlo' | 'hedge';
type ToolChainContext = WeightsContext | DeltaContext | RiskFindingContext | SimConfigContext;

// Type guards
const isWeightsContext = (ctx: Record<string, unknown>): ctx is WeightsContext => ctx.mode === 'weights' && !!ctx.weights;
const isDeltaContext = (ctx: Record<string, unknown>): ctx is DeltaContext => ctx.mode === 'deltas' && !!ctx.deltas;
const isRiskFindingContext = (ctx: Record<string, unknown>): ctx is RiskFindingContext => ctx.mode === 'risk-finding' && !!ctx.finding;
const isSimConfigContext = (ctx: Record<string, unknown>): ctx is SimConfigContext => ctx.mode === 'sim-config';

// Universal extractors
const extractWeights = (ctx: Record<string, unknown>): Record<string, number> | null => {
  if (isWeightsContext(ctx)) return ctx.weights;
  if (isSimConfigContext(ctx) && ctx.weights) return ctx.weights;
  return null;
};
const extractLabel = (ctx: Record<string, unknown>): string | null => typeof ctx.label === 'string' ? ctx.label : null;
const extractSource = (ctx: Record<string, unknown>): ToolChainSource | null => typeof ctx.source === 'string' ? ctx.source as ToolChainSource : null;
```

---

## Producer/Consumer Contract Per Tool

### Stress Test
| Role | Today | After |
|------|-------|-------|
| **Consumes** | `_context` (ignored) | Nothing (runs on live portfolio — correct) |
| **Produces -> Hedge** | `{ label, source }` | `RiskFindingContext` with impact data, worst position, scenario shocks |
| **Produces -> MC** | `{}` (empty) | `SimConfigContext` with portfolio value |

### Monte Carlo
| Role | Today | After |
|------|-------|-------|
| **Consumes** | `void context` (ignored) | `SimConfigContext` (auto-populate weights, volScale, distribution) or `WeightsContext` (weights only) |
| **Produces -> Optimize** | `{}` (empty) | `RiskFindingContext` with probability_of_loss, VaR, CVaR |

### Optimize
| Role | Today | After |
|------|-------|-------|
| **Consumes** | `_context` (ignored) | `WeightsContext` (show comparison), `RiskFindingContext` (suggest optimization goal + banner) |
| **Produces -> What-If** | `{ weights }` | `WeightsContext` with riskMetrics |
| **Produces -> Backtest** | `{ weights }` | `WeightsContext` with riskMetrics |
| **Produces -> MC** | N/A (no exit ramp) | `SimConfigContext` with optimized weights (exit ramp from MC cross-view plan) |

### What-If
| Role | Today | After |
|------|-------|-------|
| **Consumes** | `context.weights`, `context.deltas`, `context.mode`, `context.label` | Same + type guard narrowing, source-aware banner |
| **Produces -> Backtest** | `{ weights }` | `WeightsContext` |
| **Produces -> MC** | N/A (no exit ramp) | `SimConfigContext` with scenario weights (exit ramp from MC cross-view plan) |

### Backtest
| Role | Today | After |
|------|-------|-------|
| **Consumes** | `context.weights` | `WeightsContext` with source-aware banner |
| **Produces -> Rebalance** | `{ weights, label, source }` | `WeightsContext` |

### Hedge
| Role | Today | After |
|------|-------|-------|
| **Consumes** | `context.label` only | `RiskFindingContext` (show impact data in banner) |
| **Produces -> What-If** | `{ mode: 'deltas', deltas, label, source }` | `DeltaContext` (same shape, already correct) |

---

## Flow Diagram

```
                    ┌──────────────┐
                    │  Stress Test  │
                    │  (live port.) │
                    └──┬───────┬───┘
          RiskFinding  │       │  SimConfig
                       v       v
              ┌────────┐  ┌──────────┐
              │ Hedge   │  │Monte     │
              │         │  │Carlo     │
              └───┬─────┘  └───┬──────┘
          Deltas  │    RiskFinding │
                  v            v
              ┌────────┐  ┌──────────┐
              │What-If │  │Optimize  │
              │        │  │          │
              └─┬──┬┬──┘  └──┬──┬┬──┘
       Weights  │  ││Weights  │  ││ Weights
    SimConfig   │  ││         │  ││ SimConfig
                v  vv         v  vv
           ┌─────┐┌───────┐ ┌─────────┐
           │MC   ││Backtest│ │Rebalance│
           └─────┘└───┬───┘ └─────────┘
                      │ Weights
                      v
                 ┌─────────┐
                 │Rebalance│
                 └─────────┘
```

---

## Migration Strategy

Each tool redesign picks up its chaining piece independently. No tool depends on another being migrated first (backward compatible via type guards returning `false` for old-style contexts).

| Phase | Scope | Layered Into |
|-------|-------|-------------|
| **A** | Define `ToolChainContext` types + guards + helpers | New file: `connectors/src/features/scenario/toolChainContext.ts` |
| **B1** | Stress Test exit ramps produce `RiskFindingContext` + `SimConfigContext` | Stress Test redesign plan (when created) |
| **B2** | Monte Carlo consumes `SimConfigContext`/`WeightsContext`, produces `RiskFindingContext` | MC cross-view context plan (already approved) |
| **B3** | Optimize consumes `WeightsContext`/`RiskFindingContext` | Optimization redesign plan (already approved) |
| **C** | What-If, Backtest, Hedge add `mode` to exit ramps, source-aware banners | Individual tool polishes or backtest redesign plan |
| **D** | Wire workflow `contextFromPrevious` for all 5 workflows | After B1-B3 tools produce typed contexts |

---

## Workflow `contextFromPrevious` Updates (Phase D)

**Recession Prep** (Stress -> Hedge) — currently has NO `contextFromPrevious`:
```typescript
contextFromPrevious: (prev) => {
  const impactPct = prev?.metrics?.estimatedImpactPct;
  if (typeof impactPct !== 'number') return {};
  return {
    mode: 'risk-finding',
    source: 'stress-test',
    label: prev?.summary ?? 'Stress Test',
    finding: {
      severity: impactPct <= -10 ? 'severe' : impactPct <= -5 ? 'moderate' : 'low',
      impactPct,
      impactDollar: prev?.metrics?.estimatedImpactDollar,
    },
  } satisfies RiskFindingContext;
}
```

**Portfolio Checkup** (Stress -> MC) — currently has NO `contextFromPrevious`:
```typescript
contextFromPrevious: (prev, session) => {
  if (!prev) return {};
  return {
    mode: 'sim-config',
    source: 'stress-test',
    label: prev?.summary ?? 'Stress Test',
    simParams: {
      portfolioValue: session.portfolioSnapshot.totalValue,
    },
  } satisfies SimConfigContext;
}
```

**Optimize & Validate** (Optimize -> What-If -> Backtest) — add `mode` to existing:
```typescript
contextFromPrevious: (prev) => {
  const weights = getWeights(prev);
  return weights
    ? { mode: 'weights', weights, label: 'Optimized allocation', source: 'optimize' } satisfies WeightsContext
    : {};
}
```

---

## Shared `ContextBanner` Component

Replace the 3+ ad-hoc inline banners (WhatIfTool line ~472, BacktestTool line ~411, HedgeTool line ~211) with a shared component:

**File**: `frontend/packages/ui/src/components/portfolio/scenarios/shared/ContextBanner.tsx`

```typescript
function ContextBanner({ context }: { context: Record<string, unknown> }) {
  const label = extractLabel(context);
  const source = extractSource(context);
  if (!label) return null;

  const sourceLabel = source ? TOOL_LABELS[source] : undefined;
  const isRisk = isRiskFindingContext(context);
  // amber for risk findings, emerald for weight imports, blue for sim configs
  const colorClasses = isRisk
    ? 'border-amber-200 bg-amber-50 text-amber-800'
    : isSimConfigContext(context)
    ? 'border-blue-200 bg-blue-50 text-blue-800'
    : 'border-emerald-200 bg-emerald-50 text-emerald-800';

  return (
    <div className={`rounded-2xl border px-4 py-3 text-sm ${colorClasses}`}>
      Running with context from {sourceLabel ?? 'previous tool'}: {label}
    </div>
  );
}
```

---

## Files Summary

### New files (2)
1. `frontend/packages/connectors/src/features/scenario/toolChainContext.ts` — type definitions, guards, helpers
2. `frontend/packages/ui/src/components/portfolio/scenarios/shared/ContextBanner.tsx` — shared context banner

### Modified per-tool (layered into redesigns)
- `StressTestTool.tsx` — exit ramp context objects (Phase B1)
- `MonteCarloTool.tsx` — context consumption + exit ramp production (Phase B2, per MC cross-view plan)
- `OptimizeTool.tsx` — context consumption + mode on exit ramps (Phase B3)
- `WhatIfTool.tsx` — add mode to exit ramps, MC exit ramp (Phase C)
- `BacktestTool.tsx` — add mode to exit ramps, source-aware banner (Phase C)
- `HedgeTool.tsx` — consume RiskFindingContext for richer banner (Phase C)
- `workflows.ts` — wire contextFromPrevious for all workflows (Phase D)

### Backend changes
**None.** All tools already accept the parameters needed for chaining on the backend.

---

## What This Enables

After full adoption, these chains work end-to-end:

1. **Stress Test -> Monte Carlo -> Optimize -> Backtest -> Rebalance**
   Risk identification -> Forward simulation -> Risk mitigation -> Historical validation -> Execution

2. **Stress Test -> Hedge -> What-If -> Backtest**
   Vulnerability found -> Hedge strategy -> Compliance check -> Historical test

3. **Monte Carlo -> Optimize -> What-If -> Monte Carlo** (loop)
   High risk detected -> Optimize allocation -> Check risk profile -> Re-simulate to confirm improvement

4. All 5 guided workflows pass meaningful context between every step.

---

## Verification

1. **Type safety**: `tsc --noEmit` clean after each phase
2. **Backward compat**: Tools that haven't been migrated yet still work (type guards return false for old-style contexts)
3. **Each phase**: Run the specific tool, verify context banner appears, verify exit ramp passes typed context
4. **Workflows**: Run each guided workflow end-to-end, verify context propagates through all steps
5. **Frontend tests**: `cd frontend && npx vitest run --reporter=verbose`

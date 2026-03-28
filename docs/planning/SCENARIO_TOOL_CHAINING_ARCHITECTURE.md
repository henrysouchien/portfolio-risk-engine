# Scenario Tool Chaining Architecture

> **v2** — revised after bottom-up implementation. Re-submitting for Codex review.
>
> **v1 Codex review**: FAIL (6 findings). **4 of 6 addressed by shipped code** (MC cross-view `cf7a14c4`, backtest redesign, optimization redesign, what-if redesign). **2 remaining**: workflow `contextFromPrevious` gaps + MC→Optimize exit ramp.

## Context

The 6 scenario tools (What-If, Optimize, Backtest, Stress Test, Monte Carlo, Hedge) now chain well for **weight-based flows** but still have gaps in **risk intelligence flows** and **workflow auto-wiring**.

### What Works Today (shipped)

| Chain | Context Passed | Commit |
|-------|---------------|--------|
| Optimize → What-If | `{ weights }` | existing |
| Optimize → Backtest | `{ weights }` | existing |
| Optimize → Monte Carlo | `{ weights, source, label }` | `cf7a14c4` |
| What-If → Backtest | `{ weights }` | existing |
| What-If → Monte Carlo | `{ weights, source, label }` | `cf7a14c4` |
| What-If → Rebalance | `{ weights, label, source }` | existing |
| Backtest → What-If | `{ weights }` | backtest redesign |
| Backtest → Rebalance | `{ weights, label, source }` | backtest redesign |
| Hedge → What-If | `{ mode: "deltas", deltas, label, source }` | existing |
| Stress Test → Monte Carlo | `{ portfolioValue, volScale, distribution, source, label }` | `cf7a14c4` |
| Stress Test → Hedge | `{ label, source }` (label only) | existing |
| MC context consumption | Normalizes weights, volScale, distribution, portfolioValue; auto-runs | `cf7a14c4` |
| "Optimize & Validate" workflow | `contextFromPrevious` wired for all 3 steps | existing |
| "Rebalance & Execute" workflow | `contextFromPrevious` wired for step 2 | existing |

### What's Still Broken

1. **Monte Carlo → Optimize**: exit ramp passes `{}` (empty) — no risk finding context
2. **Stress Test → Hedge**: passes label only — no impact data, shocks, or worst position
3. **"Recession Prep" workflow**: Stress → Hedge has NO `contextFromPrevious`
4. **"Portfolio Checkup" workflow**: Stress → MC has NO `contextFromPrevious`

---

## Remaining Work: 3 Items

### Item 1: Monte Carlo → Optimize exit ramp

**File**: `MonteCarloTool.tsx` (exit ramp section, currently `onNavigate("optimize")`)

Pass risk finding context so Optimize can show "MC identified high risk" banner:

```typescript
onNavigate("optimize", {
  source: "monte-carlo",
  label: "Monte Carlo risk assessment",
  probabilityOfLoss: terminal?.probability_of_loss,
  var95: terminal?.var_95,
  cvar95: terminal?.cvar_95,
})
```

**OptimizeTool.tsx**: Read `context.probabilityOfLoss` etc. to show a context banner and optionally auto-select `min_variance` when risk is high.

### Item 2: Stress Test → Hedge exit ramp enrichment

**File**: `StressTestTool.tsx` (line ~359, `handleHedgeNavigation`)

Currently passes `{ label, source }`. Enrich with impact data:

```typescript
onNavigate("hedge", {
  label: lastRunScenarioName ?? stressTest.data?.scenarioName ?? "Stress Test",
  source: "stress-test",
  impactPct: stressTest.data?.estimatedImpactPct,
  impactDollar: stressTest.data?.estimatedImpactDollar,
  scenarioName: lastRunScenarioName,
})
```

**HedgeTool.tsx**: Read `context.impactPct` etc. to show "Hedging against [scenario]: [X]% estimated impact" banner.

### Item 3: Wire 2 workflow `contextFromPrevious` callbacks

**File**: `workflows.ts`

**Recession Prep** (Stress → Hedge) — line 38, add `contextFromPrevious`:
```typescript
{
  toolId: 'hedge',
  label: 'Hedge Analysis',
  contextFromPrevious: (previousOutput) => {
    const impactPct = previousOutput?.metrics?.estimatedImpactPct;
    if (typeof impactPct !== 'number') return {};
    return {
      label: previousOutput?.summary ?? 'Stress Test',
      source: 'stress-test',
      impactPct,
      impactDollar: previousOutput?.metrics?.estimatedImpactDollar,
    };
  },
},
```

**Portfolio Checkup** (Stress → MC) — line 106, add `contextFromPrevious`:
```typescript
{
  toolId: 'monte-carlo',
  label: 'Monte Carlo',
  contextFromPrevious: (previousOutput, session) => {
    if (!previousOutput) return {};
    return {
      source: 'stress-test',
      label: previousOutput?.summary ?? 'Stress Test',
      portfolioValue: session.portfolioSnapshot.totalValue ?? undefined,
    };
  },
},
```

---

## Deferred: Formal Typed Protocol

The original v1 plan proposed 4 typed context shapes (`WeightsContext`, `DeltaContext`, `RiskFindingContext`, `SimConfigContext`) with discriminated union on `mode`. This is **deferred** — the current property-based approach works without friction:

- Tools check `context.weights`, `context.portfolioValue`, `context.impactPct` directly
- MonteCarloTool normalizes via `normalizeContextWeights()`, `normalizeContextNumber()`, `normalizeContextDistribution()`
- No collision issues found in practice
- Type safety is nice-to-have but not blocking any feature work

If we add formal types later, it's additive — a `toolChainContext.ts` file with type guards that wrap existing property checks. No tool code changes needed.

### Provenance metadata (portfolioId, createdAt)

Also deferred. Low priority — tools currently run against the active portfolio, and stale context is cleared on navigation. Would matter more if we had cross-session context persistence.

---

## Flow Diagram (current state)

```
                    ┌──────────────┐
                    │  Stress Test  │
                    │  (live port.) │
                    └──┬───────┬───┘
           label+      │       │  portfolioValue+
           impact*     │       │  volScale+dist
                       v       v
              ┌────────┐  ┌──────────┐
              │ Hedge   │  │Monte     │◄── weights from Optimize/WhatIf
              │         │  │Carlo     │
              └───┬─────┘  └───┬──────┘
          Deltas  │     (empty)*│
                  v            v
              ┌────────┐  ┌──────────┐
              │What-If │  │Optimize  │
              │        │  │          │
              └─┬──┬┬──┘  └──┬──┬┬──┘
       Weights  │  ││Weights  │  ││ Weights
       +simCtx  │  ││         │  ││ +simCtx
                v  vv         v  vv
           ┌─────┐┌───────┐ ┌─────────┐
           │MC   ││Backtest│ │Rebalance│
           └─────┘└───┬───┘ └─────────┘
                      │ Weights
                      v
              ┌────────┐  ┌─────────┐
              │What-If │  │Rebalance│
              └────────┘  └─────────┘

  ✓ = shipped    * = remaining gap (Items 1-2)
```

---

## Files to Modify

| File | Change | Item |
|------|--------|------|
| `MonteCarloTool.tsx` | Pass risk metrics in "Optimize" exit ramp | 1 |
| `OptimizeTool.tsx` | Read `context.probabilityOfLoss` etc., show banner | 1 |
| `StressTestTool.tsx` | Enrich Hedge exit ramp with impact data | 2 |
| `HedgeTool.tsx` | Read `context.impactPct`, show enriched banner | 2 |
| `workflows.ts` | Add `contextFromPrevious` to Recession Prep + Portfolio Checkup | 3 |

**Backend changes: None.** All chaining is frontend context wiring.

---

## Verification

1. **Item 1**: Run MC → click "Optimize for better outcomes" → Optimize shows "MC found X% probability of loss" banner
2. **Item 2**: Run Stress Test → click "Find a hedge" → Hedge shows "Hedging against [scenario]: -X% impact" banner
3. **Item 3a**: Start "Recession Prep" workflow → complete Stress Test → advance → Hedge receives impact data via `contextFromPrevious`
4. **Item 3b**: Start "Portfolio Checkup" workflow → complete Stress Test → advance → MC receives `portfolioValue` via `contextFromPrevious`, auto-runs
5. **Type safety**: `tsc --noEmit` clean
6. **Tests**: `cd frontend && npx vitest run --reporter=verbose`
7. **E2E chaining**: Run Scenarios 1 and 4 from `SCENARIO_CHAINING_TEST_DESIGN.md` on Frontend surface

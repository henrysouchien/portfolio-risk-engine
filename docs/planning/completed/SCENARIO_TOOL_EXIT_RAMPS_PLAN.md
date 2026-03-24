# Scenario Tool Exit Ramps — Accurate Audit + Gap Fixes

## Current State (Accurate)

8 exit ramps exist across 6 tools. The tools are more connected than initially assessed.

| Tool | Ramp | Target | Passes context? |
|---|---|---|---|
| What-If | "Backtest this" | Backtest | Yes (resolvedWeights) |
| What-If | "Generate trades" | Rebalance | Yes (resolvedWeights) |
| Optimize | "Apply as What-If" | What-If | Yes (activeWeights) |
| Optimize | "Backtest this" | Backtest | Yes (activeWeights) |
| Optimize | "Set target" | Rebalance | Yes (activeWeights) |
| Backtest | "Set as target allocation" | Rebalance | Yes (activeWeights) |
| Stress Test | "Hedge this risk" | Hedge | No context |
| Stress Test | "Run Monte Carlo" | Monte Carlo | No context |

## Gaps Identified

### Gap 1: Rebalance ignores toolContext (HIGH)
**Impact:** 3 tools (What-If, Optimize, Backtest) pass ticker weights to Rebalance via `onNavigate('rebalance', { weights })`, but `AssetAllocationContainer` is rendered bare in ScenariosRouter with no props. The context goes into the UI store and is never read.

**Additional complication:** Rebalance works on **asset-class targets** (Equity 60%, Fixed Income 25%), not ticker weights (AAPL 15%, MSFT 10%). The tools output ticker weights. There's a model mismatch — can't just wire the context through.

**Possible fix:** The container's `buildTickerTargetWeights()` already converts asset-class targets to ticker weights. The reverse mapping (ticker weights → asset-class allocation) could be computed, but it's lossy — multiple tickers map to the same asset class. This may need a different approach: show a "Review trades" preview instead of feeding into the target editor.

### Gap 2: Monte Carlo has 0 exit ramps (MEDIUM)
**Impact:** Monte Carlo shows probability distributions but the user can't act on what they see. Natural next step: "Can I improve these outcomes?" → Optimize.

**Fix:** Add "Optimize for better outcomes" exit ramp. Monte Carlo currently ignores both `context` and `onNavigate` (props discarded with `_`). Need to accept `onNavigate` and add an ExitRampButton.

### Gap 3: Hedge Tool has 0 exit ramps (MEDIUM)
**Impact:** Hedge shows hedge strategies but can't chain forward. Natural next step: "Let me test this hedge" → What-If.

**Fix:** Add "Test with What-If" exit ramp. Hedge currently ignores `context` and `onNavigate`. Need to accept `onNavigate` and add an ExitRampButton. Context: pass the recommended hedge as a weight delta.

### Gap 4: Optimize ignores incoming context (LOW)
**Impact:** What-If → Optimize chain is one-way. If you run What-If first and want to optimize from that starting point, Optimize starts fresh instead of seeding from your What-If weights.

**Fix:** Read `context.weights` in OptimizeTool and use as initial state for the optimizer (or show as "starting from What-If scenario" indicator). Currently `_context` is explicitly ignored.

### Gap 5: Stress Test passes no context forward (LOW)
**Impact:** "Hedge this risk" navigates to Hedge but doesn't tell Hedge which scenario triggered it. "Run Monte Carlo" navigates to Monte Carlo with no portfolio context.

**Fix:** Pass scenario name/parameters to Hedge. Pass portfolio weights to Monte Carlo.

## Recommended Priority

| Priority | Gap | Effort | Impact |
|---|---|---|---|
| 1 | Monte Carlo exit ramp | Small (1 button + accept props) | Unblocks the most isolated tool |
| 2 | Hedge Tool exit ramp | Small (1 button + accept props) | Completes Stress Test → Hedge → What-If chain |
| 3 | Rebalance context (investigation) | Medium-Large (model mismatch) | Fixes 3 broken connections but needs design |
| 4 | Optimize context reading | Small | Nice-to-have for What-If → Optimize flow |
| 5 | Stress Test context passing | Small | Nice-to-have for scenario continuity |

## Codex Review Findings
- Monte Carlo fix is clean — no issues
- Hedge exit ramp has 2 problems:
  1. What-If reads `context.weights` as full portfolio replacement, not overlay. Need `context.mode = "deltas"` format for hedge overlay
  2. HedgeTool has no single "recommended hedge" — it shows a list of strategies per-card. Exit ramp needs to be per-strategy, not tool-level
- Hedge deferred to Phase 2 due to complexity

## Plan — Phase 1: Monte Carlo Exit Ramp

### Fix Monte Carlo exit ramp

**File:** `frontend/packages/ui/src/components/portfolio/scenarios/tools/MonteCarloTool.tsx`

- Accept `onNavigate` prop (currently entire props discarded with `_`)
- Destructure: `{ context, onNavigate }: MonteCarloToolProps`
- Add ExitRampButton "Optimize for better outcomes" → `onNavigate('optimize')`
- Show only after simulation results are displayed (when `hasResults` or equivalent state is true)
- No context passed (Optimize runs against current portfolio anyway, ignores context)

### Deferred: Hedge Tool exit ramp (Phase 2)

Needs per-strategy "Test with What-If" buttons on each hedge card, using `context.mode = "deltas"` + `context.deltas` format so What-If adds the hedge as an overlay (not a replacement). HedgeTool currently has no tool-level selection state to carry forward — each strategy card would need its own button.

### Deferred: Rebalance context consumption (Phase 2+)

Model mismatch: scenario tools output ticker weights, Rebalance works on asset-class targets. Options to investigate:
- A) "Review trades" preview bypassing the target editor
- B) Compute implied asset-class targets from ticker weights (lossy)
- C) Separate "Apply scenario" mode accepting ticker weights directly

## Files Modified (Phase 1)
1. `frontend/packages/ui/src/components/portfolio/scenarios/tools/MonteCarloTool.tsx` — accept onNavigate, add exit ramp

## Verification
1. `cd frontend && npx tsc --noEmit` — no type errors
2. Monte Carlo: run simulation → "Optimize for better outcomes" navigates to Optimize
3. Monte Carlo: exit ramp hidden/disabled when no simulation results
4. Existing exit ramps on all other tools still work (regression check)

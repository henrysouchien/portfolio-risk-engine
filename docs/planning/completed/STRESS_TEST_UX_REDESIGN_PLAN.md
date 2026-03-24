# StressTestTool UI/UX Redesign — Hedge Card Reorder

## Context

Commit `37362d6d` ("polish: stress test results section") already shipped the gradient verdict card, tightened impact summary cards, inline scenario selector, and removed the separate "Ask AI" button. The ONE remaining UX issue from the original conversation:

**The hedge suggestion card sits between the impact summary and per-position table** (lines 456–488), breaking the stress-test results reading flow. User feedback: it "stands out and seems out of place."

**Goal**: Move the hedge suggestion card below the main Card, next to the exit ramps — so the results flow is: verdict → impact summary → position table → hedge suggestion → exit ramps.

## Single change

### Move hedge suggestion card near exit ramps

**Current order** (lines 401–570):
```
CardContent:
  ├─ No-portfolio placeholder
  ├─ Verdict card (gradient, already polished)
  ├─ Impact summary grid (4 stat cards)
  ├─ Hedge suggestion card          ← out of place
  ├─ Per-position impact table
Exit ramps:
  ├─ "Hedge this risk"
  └─ "Run Monte Carlo"
```

**New order**:
```
CardContent:
  ├─ No-portfolio placeholder
  ├─ Verdict card (unchanged)
  ├─ Impact summary grid (unchanged)
  ├─ Per-position impact table      ← now directly follows summary
</Card>
Hedge suggestion card               ← moved here, near exit ramps
Exit ramps:
  ├─ "Hedge this risk"
  └─ "Run Monte Carlo"
```

### Edit sequence

1. **Cut** the hedge suggestion block (lines 456–488: the `{bestHedge ? (<Card>...</Card>) : null}` block) from inside the `<>...</>` fragment within `CardContent`
2. **Paste** it between the closing `</Card>` (line 570) and the exit ramp `<div>` (line 572), wrapped in a standalone guard: `{stressTest.hasPortfolio && initialPositions.length > 0 && bestHedge ? (...) : null}`
3. **Remove** the `mt-8` from the Per-Position Impact Card (line 490) since it now directly follows the impact summary

## What does NOT change

- Verdict card (gradient styling, icon, title/body text, action button) — keep exactly as committed
- Impact summary cards — keep exactly as committed
- Scenario selector / run button — keep exactly as committed
- Per-position impact table — keep exactly as committed (except removing mt-8)
- Exit ramp buttons — keep exactly as committed
- No new imports needed
- `getVerdictTone()` stays — it's used by the verdict card

## File modified

| File | Change |
|------|--------|
| `frontend/packages/ui/src/components/portfolio/scenarios/tools/StressTestTool.tsx` | Move hedge card block, remove mt-8 |

## Verification

1. Visual: stress test page at `localhost:3000/#scenarios/stress-test` — verdict + impact summary + position table flow unbroken, hedge card appears below main card near exit ramps
2. Edge cases: no portfolio (placeholder, no hedge card), no hedge data (hedge card hidden), no position impacts (empty state)
3. TypeScript: `cd frontend && npx tsc --noEmit`

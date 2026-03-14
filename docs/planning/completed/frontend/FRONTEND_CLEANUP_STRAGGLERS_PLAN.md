# Frontend Cleanup Stragglers

**Date:** 2026-03-04
**Status:** ✅ COMPLETE (2026-03-04, commit `044ebe7c`)
**Source:** Post-P5 sweep of remaining issues

---

## Item 1. PerformanceView: Inert AI insight action button

**File:** `frontend/packages/ui/src/components/portfolio/PerformanceView.tsx` lines 967-972

**Problem:** Each AI insight card renders a ghost button with no onClick handler:
```tsx
<div className="flex items-center justify-end">
  <Button variant="ghost" size="sm" className="text-xs px-2 py-1 h-auto">
    {insight.action}
  </Button>
</div>
```
The button displays text like "Review allocation" but clicking it does nothing.

**Fix:** Delete lines 966-972 (the comment, wrapping `<div>`, and `<Button>`). The insight text (`insight.text`) above it remains — only the dead action footer is removed.

---

## Item 2. StrategyBuilder: Stale 153-line header

**File:** `frontend/packages/ui/src/components/portfolio/StrategyBuilder.tsx` lines 1-153

**Problem:** Massive docblock with:
- Line 48: `Backtesting Engine: ❌ TODO` — backtesting is fully implemented (`run_backtest` MCP tool, `/api/backtest` endpoint, `useBacktest` hook, Backtest tab in StrategyBuilder)
- Line 49: `Advanced Constraints: ❌ TODO` — still genuinely TODO
- Lines 78-90: Interface TODO comments for `backtestResults`, `constraints` — backtestResults is implemented via separate hook, not via props (so the TODO interface is misleading)
- Lines 93-94: `onBacktest` and `onSave` marked `❌ TODO` — `onBacktest` is integrated via `useBacktest`

The header is 153 lines of ASCII art, emoji decoration, and integration status that's largely stale.

**Fix:** Replace lines 1-153 with a clean JSDoc header (~10 lines):
```typescript
/**
 * StrategyBuilder — Portfolio optimization & strategy building dashboard
 *
 * Data flow: usePortfolioOptimization() → PortfolioOptimizationAdapter → StrategyBuilderContainer → props
 * Tabs: Build (strategy templates + custom builder), Optimize (min-variance/max-return),
 *        Backtest (historical backtesting via useBacktest)
 * Integration: Cross-container strategy export to ScenarioAnalysis
 */
```

---

## Item 3. ScenarioAnalysis: Stale 167-line header

**File:** `frontend/packages/ui/src/components/portfolio/ScenarioAnalysis.tsx` lines 1-167

**Problem:** Massive docblock with:
- Line 49: `Historical Scenarios: ❌ TODO` — scenario history is implemented (`useScenarioHistory` hook, History tab)
- Line 50: `Stress Test Templates: ❌ TODO` — stress tests are fully implemented (Stress Tests tab, `useStressTests` hook, `run_stress_test` backend)
- Lines 94-106: Interface TODO comments for `scenarios` and `stressTests` — both implemented via separate hooks/tabs, not via the main props interface
- Line 159: `Monte Carlo Analysis` listed as enhancement — fully implemented (`useMonteCarlo` hook, Monte Carlo tab)

The header is 167 lines with stale status markers that contradict reality.

**Fix:** Replace lines 1-167 with a clean JSDoc header (~10 lines):
```typescript
/**
 * ScenarioAnalysis — What-if scenario analysis dashboard
 *
 * Data flow: useWhatIfAnalysis() → WhatIfAnalysisAdapter → ScenarioAnalysisContainer → props
 * Tabs: Scenarios (what-if builder), Stress Tests (historical stress scenarios),
 *        Monte Carlo (simulation engine), History (session scenario log),
 *        Optimization (cached portfolio optimization read)
 * Integration: Receives strategies from StrategyBuilder for cross-container analysis
 */
```

---

## Files Modified

| File | Changes |
|------|---------|
| `PerformanceView.tsx` | Delete insight action button (~6 lines) |
| `StrategyBuilder.tsx` | Replace 153-line header with ~8-line JSDoc |
| `ScenarioAnalysis.tsx` | Replace 167-line header with ~9-line JSDoc |

## Verification

1. `cd frontend && pnpm typecheck` — must pass (no code logic changes, only comment/UI deletion)
2. Visual check: AI insights in PerformanceView still show text, just no dead button

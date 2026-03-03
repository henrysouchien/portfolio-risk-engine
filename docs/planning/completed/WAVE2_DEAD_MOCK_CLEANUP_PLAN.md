# Wave 2: Remove Dead Mock Fallback Arrays

**Date**: 2026-03-02
**Status**: COMPLETE (implemented in commit `25cbe2fb`)

## Context

Wave 1 fixed the 6 dashboard cards showing fake numbers. Wave 2 was supposed to address 5 more components with inline mock data. Investigation reveals that 3 of 5 already show real data with appropriate "no data" fallbacks, and 2 have completely dead mock code that can be deleted.

## Findings

| Component | Mock Status | Action |
|-----------|------------|--------|
| HoldingsView | DORMANT — real holdings flow via `usePositions()`, mock only on empty portfolio | No change needed |
| RiskAnalysis | DORMANT — container builds factors from real `component_scores` | No change needed |
| PerformanceView | DORMANT — real sector attribution flows from API | No change needed |
| **RiskMetrics** | DEAD CODE — container pre-transforms all metrics, fallback array unreachable | **Delete** |
| **FactorRiskModel** | DEAD CODE — container builds from real betas, fallback array unreachable | **Delete** |

---

## Implementation

### Step 1: Delete `fallbackMetrics` and `fallbackSummary` from RiskMetrics.tsx

**File**: `packages/ui/src/components/portfolio/RiskMetrics.tsx` (lines ~191-238)

Delete the `fallbackMetrics` and `fallbackSummary` constant arrays. The container (`RiskMetricsContainer`) pre-transforms all metrics from `useRiskAnalysis()` before passing to the component — these arrays are never referenced in the render path.

### Step 2: Delete `fallbackFactorExposures` and `fallbackRiskAttribution` from FactorRiskModel.tsx

**File**: `packages/ui/src/components/portfolio/FactorRiskModel.tsx` (lines ~220-320)

Delete the `fallbackFactorExposures` and `fallbackRiskAttribution` constant arrays. The container (`FactorRiskModelContainer`) dynamically builds factor exposures from `data.portfolio_factor_betas` — these arrays are never used.

### Step 3: Remove any references to the deleted constants

Search each file for usage of the deleted constant names. If any references exist (e.g., `const factors = data?.factors || fallbackFactorExposures`), replace with appropriate empty defaults (`[]`, `null`, etc.).

---

## Files Modified

| File | Change |
|------|--------|
| `packages/ui/src/components/portfolio/RiskMetrics.tsx` | Delete dead `fallbackMetrics` + `fallbackSummary` arrays |
| `packages/ui/src/components/portfolio/FactorRiskModel.tsx` | Delete dead `fallbackFactorExposures` + `fallbackRiskAttribution` arrays |

---

## Verification

1. `cd frontend && npx eslint packages/ui/src/components/portfolio/RiskMetrics.tsx packages/ui/src/components/portfolio/FactorRiskModel.tsx` — no errors
2. Load dashboard — Risk Metrics and Factor Risk sections should display identically (real data unchanged)

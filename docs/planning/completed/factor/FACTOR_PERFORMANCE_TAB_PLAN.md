# Wave 2e: FactorRiskModel Performance Tab — Wire Real Data

**Status**: COMPLETE — commit `dbcee8c9` (plan v2 implemented)

## Context

FactorRiskModel (⌘3) Performance tab shows entirely hardcoded values:
- Factor Alpha: `+2.3%` (hardcoded)
- Information Ratio: `0.72` (hardcoded)
- R²: `84.7%` (hardcoded, also in header badge as `R² = 0.847`)
- Key Risk Insights: 3 bullet points with hardcoded factor values (0.31, -0.23, 0.22)

All data already exists in the backend — no backend changes needed:
- Alpha + IR → `usePerformance()` hook (already exported from `@risk/connectors`)
- R² → derivable from `variance_decomposition.factor_variance / 100` (already in `useRiskAnalysis()`)
- Factor betas for insights → already passed as `factorExposures` prop

## Changes

### 1. Container: Add `usePerformance()` hook + compute metrics

**File**: `frontend/packages/ui/src/components/dashboard/views/modern/FactorRiskModelContainer.tsx`

- Import `usePerformance` from `@risk/connectors`
- Call `usePerformance()` alongside existing `useRiskAnalysis()`
- Extract performance metrics:
  - `alpha`: from `performanceData?.performanceSummary?.riskMetrics?.alpha` — **already in percentage points** (PerformanceAdapter multiplies by 100 at line 785). Do NOT multiply again.
  - `informationRatio`: from `performanceData?.performanceSummary?.riskMetrics?.informationRatio` (raw number)
  - `rSquared`: from `variance_decomposition.factor_variance / 100` (already available from risk data — e.g., 84.7 → 0.847)
- **Loading state**: Performance metrics prop should be `null` (not default values) when `usePerformance` is still loading or has errors. The component shows `—` for null values. Risk data loading/error continues to drive the overall container loading/error state — performance data is supplementary.
- **Error resilience**: Wrap performance data extraction in a try/catch or null-chain so that if PerformanceAdapter throws on partial data, the Performance tab gracefully falls back to `—` for all three metrics.
- Pass as new `performanceMetrics` prop to `<FactorRiskModel>`

### 2. Component: Add `performanceMetrics` prop + wire Performance tab

**File**: `frontend/packages/ui/src/components/portfolio/FactorRiskModel.tsx`

**Props update** — add to `FactorRiskModelProps` interface:
```typescript
performanceMetrics?: {
  factorAlpha: number | null;      // e.g., 2.3 (already in %)
  informationRatio: number | null;  // e.g., 0.72
  rSquared: number | null;          // e.g., 0.847 (0-1 scale)
}
```

**Performance tab metric cards** (lines 416-426) — replace hardcoded values:
- Factor Alpha: `performanceMetrics?.factorAlpha` → format as `+X.X%` (fallback: show `—`)
- Information Ratio: `performanceMetrics?.informationRatio` → format as `X.XX` (fallback: show `—`)
- R²: `performanceMetrics?.rSquared` → format as `XX.X%` (fallback: show `—`)

**Header R² badge** (line 273) — replace hardcoded `R² = 0.847`:
- Use `performanceMetrics?.rSquared` → format as `R² = X.XXX`

**Key Risk Insights** (lines 436-450) — generate from actual factor exposures:
- Use `factorExposures` prop (already passed, has real factor betas)
- Replace hardcoded text with dynamic insights based on actual exposure values
- Template: pick top 2-3 factors by absolute exposure, generate interpretive text
- e.g., "High market exposure (β={exposure}) indicates..."

### 3. t-stat — leave as-is

Container already passes `tStat: 0`. Backend doesn't compute regression p-values. Low priority — no change needed.

## Files Modified

| File | Change |
|------|--------|
| `frontend/packages/ui/src/components/dashboard/views/modern/FactorRiskModelContainer.tsx` | Add `usePerformance()` hook, compute + pass `performanceMetrics` prop |
| `frontend/packages/ui/src/components/portfolio/FactorRiskModel.tsx` | Add `performanceMetrics` prop, wire Performance tab cards + header badge + dynamic insights |

## Data Flow

```
useRiskAnalysis() → variance_decomposition.factor_variance → R² (factor_variance / 100)
                  → portfolio_factor_betas → factorExposures → Key Risk Insights text

usePerformance()  → performanceSummary.riskMetrics.alpha → Factor Alpha
                  → performanceSummary.riskMetrics.informationRatio → Information Ratio
```

## What Goes From Hardcoded → Real

| Field | Before | After |
|-------|--------|-------|
| Factor Alpha | `+2.3%` | Real from performance benchmark analysis |
| Information Ratio | `0.72` | Real from performance risk metrics |
| R² (Performance tab) | `84.7%` | Real from variance_decomposition |
| R² (header badge) | `0.847` | Real from variance_decomposition |
| Key Risk Insights | 3 hardcoded bullets with static values | Dynamic from actual factor exposures |
| t-stat | `0` | Stays 0 (low priority, needs backend work) |

## Codex v1 Findings (Addressed)

1. **Alpha unit**: PerformanceAdapter already multiplies `alpha_annual * 100` (line 785). Plan now says do NOT multiply again.
2. **Loading/error coordination**: Performance data is supplementary — null when loading/errored, component shows `—`. Risk hook drives overall loading state.
3. **hasError vs error**: Container checks `hasError` from `usePerformance`, not just error string (can be true while error is null).
4. **Adapter throw on partial data**: Container wraps performance extraction in try/catch, falls back to null metrics.

## Verification

1. `cd frontend && pnpm typecheck` passes
2. `cd frontend && pnpm lint` passes (our files)
3. Navigate to Factor Analysis (⌘3) → Performance tab
4. Factor Alpha, IR, R² show real values (not hardcoded)
5. Header badge shows real R² value
6. Key Risk Insights reference actual factor names and exposures from the portfolio

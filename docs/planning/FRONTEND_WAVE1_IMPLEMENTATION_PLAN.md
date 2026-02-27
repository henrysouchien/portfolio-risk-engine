# Wave 1: Pure Frontend Mock Data Wiring

**Date**: 2026-02-25
**Status**: COMPLETE — implemented by Codex, verified in Chrome, post-fixes applied (2026-02-27)
**Parent doc**: `FRONTEND_PHASE2_WORKING_DOC.md`

### Related Docs
| Doc | Purpose |
|-----|---------|
| `FRONTEND_PHASE2_WORKING_DOC.md` | Phase 2 master doc — 16 mock items, 3-wave plan, this is Wave 1 |
| `FRONTEND_COMPONENT_VISUAL_MAP.md` | Visual guide: what you see on screen → code component names used here |
| `COMPOSABLE_APP_FRAMEWORK_PLAN.md` | Phase 3 — the SDK this work feeds into |

## Context

Phase 2 of the frontend packaging project identified 16 mock data items across 8 dashboard views. Wave 1 tackles the 4 items that can be fixed purely in frontend code — no backend changes needed. All required data already flows through existing hooks and adapters; it's just not being consumed by the presentation components.

## Codex Review (v1 → v2 fixes)

Codex reviewed v1 and returned FAIL with 6 issues. All addressed below:

1. **Unit handling**: `risk_metrics.annual_volatility` is already in percent (adapter does `× 100` at line 529). Plan updated — no extra `× 100`. VaR formula divides by 100.
2. **FactorRiskModel props**: Added `tStat` (number, 0 when unavailable) and `description` (string) to props interface — component renders both.
3. **Max drawdown extraction**: `historical_analysis.worst_per_proxy` is `Record<string, number>` — extract as `Math.min(...Object.values(worst_per_proxy))`.
4. **Container pattern completeness**: All new containers must include: `DashboardErrorBoundary`, `React.memo` with smart comparison, loading/error/no-portfolio/no-data states, EventBus cache invalidation, lifecycle logging.
5. **Task 1d scope**: Expanded to include `StrategyBuilderContainer.tsx` — container already transforms adapter output into the `StrategyBuilderProps.optimizationData` shape (`currentStrategy`, `optimizedStrategy`, `backtestResults`, `templates`). Component just needs to consume those props instead of ignoring them.
6. **Barrel imports**: New containers must be added to `frontend/packages/ui/src/components/dashboard/views/modern/index.ts` — `ModernDashboardApp.tsx` imports all containers from that barrel (line 81-90).
7. **Max drawdown units**: `worst_per_proxy` values are decimals (e.g. `-0.15`). Must multiply by 100 before display and status thresholds.

---

## Task 1a: Replace mock PerformanceChart with real PerformanceViewContainer

**Problem**: `ModernDashboardApp.tsx:419` renders `<PerformanceChart />` directly — a self-contained mock component with hardcoded sine-wave data and no props. Meanwhile, `<PerformanceViewContainer />` on line 457 already serves real performance data.

**Layout risk**: `PerformanceChart` is a compact card; `PerformanceView` is a full analytics dashboard. May cause layout shift in the 2-column grid on the 'score' view. Mitigation: visually verify in Chrome after swap; if too large, add a `compact` prop to PerformanceView or constrain with CSS.

**Fix**:
1. In `ModernDashboardApp.tsx` line 419 ('score' view), replace `<PerformanceChart />` with `<PerformanceViewContainer />`
2. Remove the `PerformanceChart` import (line 55)
3. Delete `packages/ui/src/components/portfolio/PerformanceChart.tsx`

**Note**: AssetAllocation.tsx is NOT a dead duplicate — it's correctly wired through `AssetAllocationContainer`. No action needed on it.

**Files**:
- `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx` (edit)
- `frontend/packages/ui/src/components/portfolio/PerformanceChart.tsx` (delete)

---

## Task 1b: Wire FactorRiskModel to useRiskAnalysis()

**Problem**: `FactorRiskModel.tsx` has zero props — all 8 factor exposures and 5 risk attribution sources are hardcoded arrays. Used on line 444 (factors view).

**Data available from `RiskAnalysisAdapter` output** (via `useRiskAnalysis().data`):
- `portfolio_factor_betas`: `Record<string, number>` — all factor betas (market, value, momentum, quality, etc.)
- `weighted_factor_var`: `Record<string, number>` — factor risk contributions
- `variance_decomposition`: `{ factor_variance, idiosyncratic_variance }` — already in 0-100 range
- `risk_metrics.annual_volatility`: total portfolio volatility — **already in percent** (adapter does `× 100`)
- `historical_analysis` — worst monthly losses

**Field mapping**:

| Component field | Adapter source | Notes |
|---|---|---|
| `factor` (name) | key from `portfolio_factor_betas` | Capitalize + add label (e.g. "market" → "Market (Beta)") |
| `exposure` (beta) | `portfolio_factor_betas[factor]` | Direct value |
| `contribution` (%) | `weighted_factor_var[factor]` / sum × 100 | Normalize to percentages |
| `tStat` | Not available from adapter | Pass `0`; component renders `t-stat: 0.00` — acceptable for now |
| `significance` | Derive from `\|beta\|`: >0.3=High, >0.15=Medium, else Low | Heuristic |
| `description` | Static map keyed by factor name | e.g. "market" → "Broad equity market exposure" |
| Risk Attribution: Systematic vs Idiosyncratic | `variance_decomposition.factor_variance` / `idiosyncratic_variance` | 2-source split |
| Total Risk % | `risk_metrics.annual_volatility` | Already in percent — use directly |
| Performance tab metrics | `historical_analysis` | Partial |

**Implementation**:
1. Add props interface to `FactorRiskModel.tsx` matching the existing internal interfaces:
   ```typescript
   interface FactorRiskModelProps {
     factorExposures?: FactorExposure[];  // Reuse existing FactorExposure interface
     riskAttribution?: RiskAttribution[];  // Reuse existing RiskAttribution interface
     totalRisk?: number;
     loading?: boolean;
     error?: string | null;
     className?: string;
   }
   ```
   The existing `FactorExposure` interface already includes `tStat: number`, `significance`, and `description`.
2. Keep current hardcoded arrays as fallback defaults when no props provided
3. Create `FactorRiskModelContainer.tsx` following `RiskAnalysisModernContainer` pattern:
   - Use `useRiskAnalysis()` + `useSessionServices()` hooks
   - Transform `portfolio_factor_betas` + `weighted_factor_var` into `FactorExposure[]`
   - Transform `variance_decomposition` into `RiskAttribution[]`
   - Full container pattern: `DashboardErrorBoundary`, `React.memo` with smart comparison, loading/error/no-portfolio/no-data states, EventBus `risk-data-invalidated` + `cache-updated` handlers, `frontendLogger` lifecycle logging
4. Update `ModernDashboardApp.tsx` line 444: replace `<FactorRiskModel />` with `<FactorRiskModelContainer />`

**Files**:
- `frontend/packages/ui/src/components/portfolio/FactorRiskModel.tsx` (add props, keep interfaces)
- `frontend/packages/ui/src/components/dashboard/views/modern/FactorRiskModelContainer.tsx` (new)
- `frontend/packages/ui/src/components/dashboard/views/modern/index.ts` (add barrel export)
- `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx` (add to barrel import + swap usage)

**Pattern reference**: `RiskAnalysisModernContainer.tsx` — same hook, same adapter, same container skeleton.

---

## Task 1c: Wire RiskMetrics to useRiskAnalysis()

**Problem**: `RiskMetrics.tsx` has zero props — 4 metrics are hardcoded (VaR -$42,891, Beta 1.23, Volatility 18.4%, Max Drawdown -8.7%). Used on lines 423 (score view) AND 447 (factors view).

**Data available from adapter** (all on `useRiskAnalysis().data`):
- `risk_metrics.annual_volatility` — volatility, **already in percent**
- `portfolio_factor_betas?.market` — market beta (direct)
- `historical_analysis.worst_per_proxy` — `Record<string, number>` (values are decimals like -0.15), extract max drawdown as `Math.min(...Object.values(worst_per_proxy)) * 100` to get percent
- `portfolio_summary.total_value` + `risk_metrics.annual_volatility` — VaR estimate: `total_value × (annual_volatility / 100) × 1.645 / sqrt(252)` (divide by 100 since adapter stores as percent)
- `variance_decomposition` — for risk summary section

**Implementation**:
1. Add props interface to `RiskMetrics.tsx`:
   ```typescript
   interface RiskMetricsProps {
     metrics?: Array<{
       label: string; value: string; percentage: number;
       description: string; status: 'high' | 'medium' | 'low';
       icon: LucideIcon; insight: string; trend: 'increasing' | 'decreasing' | 'stable';
     }>;
     riskSummary?: { efficiency: string; rating: string; analysis: string };
     loading?: boolean;
     error?: string | null;
     className?: string;
   }
   ```
2. Keep current hardcoded array as fallback default
3. Create `RiskMetricsContainer.tsx` with full container pattern:
   - Use `useRiskAnalysis()` + `useSessionServices()` hooks
   - Build 4-metric array from adapter data with status derivation logic:
     - Volatility >25% = high, >15% = medium, else low
     - Beta >1.3 = high, >0.8 = medium, else low
     - Drawdown < -15 (after `× 100` conversion) = high, < -8 = medium, else low
     - VaR > 5% of portfolio = high, > 2% = medium, else low
   - Set trends to `'stable'` (no time-series comparison available yet)
   - Build `riskSummary` from `variance_decomposition` percentages
   - Full pattern: `DashboardErrorBoundary`, `React.memo`, loading/error/no-portfolio/no-data, EventBus, lifecycle logging
4. Update `ModernDashboardApp.tsx` lines 423 and 447: replace `<RiskMetrics />` with `<RiskMetricsContainer />`

**Files**:
- `frontend/packages/ui/src/components/portfolio/RiskMetrics.tsx` (add props)
- `frontend/packages/ui/src/components/dashboard/views/modern/RiskMetricsContainer.tsx` (new)
- `frontend/packages/ui/src/components/dashboard/views/modern/index.ts` (add barrel export)
- `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx` (add to barrel import + swap usage, 2 locations)

---

## Task 1d: Wire StrategyBuilder to its existing props

**Problem**: `StrategyBuilder.tsx` receives props from `StrategyBuilderContainer` but ignores all of them — every prop is destructured with `_` prefix (lines 264-271): `_optimizationData`, `_onOptimize`, `_onBacktest`, `_onSaveStrategy`, `_onExportToScenario`, `_loading`, `_className`. The component uses internal mock state instead.

**Data shape already available**: `StrategyBuilderContainer.tsx` (line 172) already transforms adapter output into the correct `StrategyBuilderProps.optimizationData` shape:
```typescript
{
  currentStrategy: { allocation, metrics: { expectedReturn, volatility, sharpeRatio, maxDrawdown }, riskLevel },
  optimizedStrategy: { allocation, expectedReturn, expectedRisk, improvementMetrics },
  backtestResults: [{ period, return, benchmark, alpha, sharpe }],
  templates: [{ id, name, description, riskLevel, allocation }]
}
```
The container also provides real `onOptimize` (calls `optimizeMinVariance`/`optimizeMaxReturn`) and `loading` state. No container changes needed.

**Implementation**:
1. Remove `_` prefixes from destructured props (lines 264-271)
2. Wire `optimizationData` into the Optimize tab:
   - When `optimizationData?.currentStrategy` exists, display real metrics instead of mock
   - When `optimizationData?.optimizedStrategy` exists, show real optimized allocation
   - When `optimizationData?.templates` exists, use those instead of hardcoded `prebuiltStrategies`
3. Wire `onOptimize` callback to replace the mock `setTimeout` timer (lines ~435-438)
4. Wire `loading` prop to show real loading state during optimization
5. Wire `className` prop to outer container
6. Keep `prebuiltStrategies` array as fallback when `optimizationData?.templates` is empty
7. Keep mock backtesting timer for `onBacktest` (backend backtesting not yet available)

**Files**:
- `frontend/packages/ui/src/components/portfolio/StrategyBuilder.tsx` (edit props usage)
- `frontend/packages/ui/src/components/dashboard/views/modern/StrategyBuilderContainer.tsx` (no changes needed — already transforms correctly)

---

## Execution Order

1. **Task 1a** first (smallest, validates the pattern of swapping mock→container)
2. **Task 1c** second (RiskMetrics is simpler — 4 flat metrics, no tabs)
3. **Task 1b** third (FactorRiskModel is more complex — 3 tabs, nested data transforms)
4. **Task 1d** last (StrategyBuilder — unwiring the `_` prefixes and connecting callbacks)

## Verification — COMPLETE (2026-02-27)

| Check | Result |
|-------|--------|
| `pnpm typecheck` | 0 errors |
| `pnpm lint` | No new errors (existing warnings OK) |
| Chrome visual audit | All 4 tasks verified |

### Visual Verification Results

**Task 1a — PerformanceViewContainer**: PASS
- Score view renders real performance data ($1M portfolio, +1735% 1Y, 1.714 Sharpe)
- No layout breakage in 2-col grid
- Old PerformanceChart.tsx deleted

**Task 1b — FactorRiskModelContainer**: PASS (with known gaps)
- Factor Exposure tab: 6 real factors (Industry +0.95, Market +1.05, Subindustry +0.63, Interest Rate, Value +0.32, Momentum -0.28)
- Risk Contribution: Real percentages (37.6%, 24.4%, 23.3%, 11.5%, 2.3%, 0.9%)
- Risk Attribution tab: Real data (Systematic 77.3%, Idiosyncratic 22.7%, Total Risk 8.5%)
- Performance tab: Still mock (Factor Alpha, IR, R², Key Risk Insights) — backend data gap
- t-stat: Shows 0.00 (expected — not available from backend)

**Task 1c — RiskMetricsContainer**: PASS
- VaR -$1,255 (LOW), Beta 1.05 (MEDIUM), Volatility 8.5% (LOW), Max Drawdown -55.9% (HIGH)
- Progress bar percentages: clean integers (15%, 58%, 24%, 100%)
- Risk Summary: Real variance decomposition, Efficiency 45%, Rating High
- Dev badges confirm "Real Data | Source: useRiskAnalysis"

**Task 1d — StrategyBuilder props**: PASS (code review)
- Props consumed without `_` prefixes
- `optimizationData` used for currentStrategy, optimizedStrategy, templates, backtestResults
- Graceful fallback to mock data when no props

### Post-Implementation Fixes (2026-02-27)

Two bugs found during visual verification and fixed:

1. **Percentage rounding** (`RiskMetricsContainer.tsx`): Progress bar percentages showed raw floats (e.g. "14.70129355005772%"). Fixed by wrapping all `percentage` values with `Math.round()`.

2. **Risk Contribution 0.0%** (`FactorRiskModelContainer.tsx`): Backend serializes `weighted_factor_var` DataFrame as `{factor: {ticker: value}}` (nested dict), but container expected `{factor: value}` (flat). Fixed by summing per-ticker values into portfolio-level factor contributions.

### Known Remaining Gaps (not Wave 1 scope — backend enrichment needed)

| Gap | Location | Notes |
|-----|----------|-------|
| FactorRiskModel Performance tab | Performance sub-tab | Factor Alpha, IR, R², Key Risk Insights still hardcoded |
| R² badge | FactorRiskModel header | Uses 0.847 fallback (no backend source) |
| t-stat column | Factor Exposure tab | Shows 0.00 (not available from backend) |

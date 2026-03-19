# Enrich Factor Risk Model Tabs

## Context
The Factor Risk Model card has 3 tabs: Factor Exposure, Risk Attribution, Performance. Risk Attribution is sparse (4 items, empty space). The Performance tab shows Alpha/IR (redundant with Performance view) and generic templated "insights" that feel like placeholders. The backend already provides rich data flowing through `useRiskAnalysis()` — just not rendered.

## Data Availability (Codex-verified)

### Available in adapter output today:
- `risk_contributions`: `Array<{ticker, contribution, contributionDisplay, rawValue}>` — position-level risk contributions, already transformed
- `top_stock_variance_euler`: `Array<{ticker, contribution}> | Record<string, number>` — top positions by Euler variance
- `variance_decomposition`: factor_variance + idiosyncratic_variance (already used)
- `weighted_factor_var`: per-factor risk contributions (already used for Factor Exposure tab)

### NOT available without adapter changes:
- `factor_vols`: serialized as DataFrame (ticker × factor), not passed through adapter. Skipping for now — would need aggregation logic + adapter change.
- `euler_variance_pct`: raw dict transformed internally, exposed as `risk_contributions` instead.

## Changes

### Files to modify
- `frontend/packages/ui/src/components/dashboard/views/modern/FactorRiskModelContainer.tsx` — pass `risk_contributions`, remove `usePerformance()`
- `frontend/packages/ui/src/components/portfolio/FactorRiskModel.tsx` — render enriched tabs, update props/types

### Tab 2: Risk Attribution → Enriched

**Keep:** Total Risk / Active Risk summary cards at top, Systematic/Idiosyncratic split with progress bars.

**Add: Top Risk Contributors section** below the systematic/idiosyncratic split.
- Source: `risk_contributions` array from `useRiskAnalysis()` data — already transformed by adapter
- Show top 5 positions sorted by contribution descending
- Each row: ticker, contribution %, `GradientProgress` bar
- Section header: "Top Risk Contributors" with compact styling
- Container passes `risk_contributions` slice as new prop `topRiskContributors`

### Tab 3: Performance → Rename "Model Insights"

**Remove:** Factor Alpha and Information Ratio metric cards + their tooltips (redundant with Performance view).

**Keep:** R-Squared card (model fit metric, belongs here). Widen to full-width or 1-col since it's alone.

**Replace: Key Risk Insights** — rewrite `buildRiskInsight()` to generate data-driven insights from actual numbers:
- Insight 1 (dominant factor): Find top factor by contribution → "Interest Rate contributes 67.5% of factor risk — dominant risk driver"
- Insight 2 (systematic vs idiosyncratic): From riskAttribution → "89.5% systematic risk — portfolio variance largely explained by factors" or "High idiosyncratic risk (X%) — significant stock-specific risk"
- Insight 3 (concentration): If topRiskContributors available, top contributor → "DSU accounts for 32.8% of position-level risk"
- Color-code by severity: red for concentrated/high, amber for moderate, green for diversified/low

**Wrap in ScrollArea** to handle overflow.

### Props changes (FactorRiskModel)

```typescript
// Updated FactorRiskModelProps:
interface FactorRiskModelProps {
  factorExposures?: FactorExposure[]
  riskAttribution?: RiskAttribution[]
  topRiskContributors?: Array<{ ticker: string; contribution: number }>  // NEW
  performanceMetrics?: {
    rSquared: number | null  // SIMPLIFIED — removed factorAlpha, informationRatio
  }
  totalRisk?: number
  loading?: boolean
  error?: string | null
  className?: string
}
```

### Container changes (FactorRiskModelContainer)

1. **Widen `RiskAnalysisLike`** to include `risk_contributions` (or access from `data` directly)
2. **Extract top risk contributors**: from `data.risk_contributions`, sort by contribution desc, take top 5, map to `{ticker, contribution}[]`. Note: adapter `contribution` is 0-1 fraction — multiply by 100 for percentage display.
3. **Remove `usePerformance()` hook** — no longer needed (Alpha/IR removed)
4. **Simplify `performanceMetrics`** — only pass `rSquared` (already derived from `variance_decomposition.factor_variance`)
5. **Clean up** `nullPerformanceMetrics`, `PerformanceDataLike` interface, related imports

### Display component changes (FactorRiskModel)

1. **Risk Attribution tab**: Add "Top Risk Contributors" section after existing content
2. **Rename tab**: "Performance" → "Model Insights"
3. **Remove**: Alpha/IR cards, their tooltip entries, `factorAlphaDisplay`/`informationRatioDisplay` vars
4. **Rewrite**: `buildRiskInsight()` → `generateModelInsights()` that takes factorExposures + riskAttribution + topRiskContributors and produces 2-3 data-driven insights. Guard against empty/zero data gracefully.
5. **R-Squared**: Keep card, widen to take more space (full width or prominent placement)
6. **Add ScrollArea** wrapper on Model Insights tab content

## Verification
1. Visual: Risk Attribution tab shows Total Risk/Active Risk + Systematic/Idiosyncratic + Top 5 Risk Contributors with bars
2. Visual: Model Insights tab shows R² prominently + 2-3 data-driven insights (no Alpha/IR)
3. No horizontal scroll or overflow issues
4. TypeScript compiles clean (no unused imports/types)

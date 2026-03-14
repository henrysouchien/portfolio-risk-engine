# Codex Spec: Risk Assessment Hover Explanations (T2 #16)

**Status: IMPLEMENTED.** All tooltip placements, imports, TooltipProvider wrappers, and METRIC_TOOLTIPS/RISK_ANALYSIS_TOOLTIPS/FACTOR_TOOLTIPS objects are already in the source files. The remaining work is tooltip COPY accuracy — corrected directly in the source files (RiskAnalysis.tsx, FactorRiskModel.tsx).

**Goal:** Add tooltip explanations to all risk metrics so users understand what they're looking at.

**Pattern:** Radix Tooltip components are at `frontend/packages/ui/src/components/ui/tooltip.tsx`, exporting `Tooltip`, `TooltipTrigger`, `TooltipContent`, `TooltipProvider`. Working example in `RiskAnalysisTab.tsx` (lines 31-44) uses `<Tooltip>` + `<TooltipTrigger asChild>` + `<TooltipContent>` with an `<Info>` icon.

**Key constraint:** `<Tooltip>` requires a `<TooltipProvider>` ancestor. All three target components now wrap their own return in `<TooltipProvider>`.

---

## Step 1: Add tooltips to RiskMetrics component

**File:** `frontend/packages/ui/src/components/portfolio/RiskMetrics.tsx`

### 1a. Imports (after existing imports, around line 141)

```typescript
import { Info } from "lucide-react"
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from "../ui/tooltip"
```

All imports in this file use relative paths from `components/portfolio/` to `components/ui/`. The existing `Card` import on line 137 confirms: `from "../ui/card"`.

### 1b. Tooltip definitions (add after the `RiskMetricsProps` interface, before the function body -- around line 177)

```typescript
const METRIC_TOOLTIPS: Record<string, { title: string; description: string }> = {
  "Est. 1-Day VaR": {
    title: "Value at Risk (VaR)",
    description: "Loss threshold at the 95th percentile over one trading day. There is a 5% chance of exceeding this loss. Parametric estimate using portfolio volatility and normal distribution assumption."
  },
  "Beta Coefficient": {
    title: "Beta",
    description: "Sensitivity to market movements. Beta of 1.0 = moves in line with market. Above 1.0 = amplified response to market moves. Below 1.0 = dampened response."
  },
  "Volatility": {
    title: "Annualized Volatility",
    description: "Standard deviation of portfolio returns, annualized. Higher values mean wider range of expected outcomes. Typical equity portfolio: 12-20%."
  },
  "Worst Monthly Factor Return": {
    title: "Worst Monthly Factor Return",
    description: "Largest single-month loss observed across factor proxies used in the portfolio model. Historical observation, not a forward-looking estimate."
  },
}
```

### 1c. Wrap return in TooltipProvider

The component's `return` starts at line 241 with `<Card ...>`. Wrap the entire return:

```tsx
return (
  <TooltipProvider>
    <Card className={...}>
      {/* ... existing content ... */}
    </Card>
  </TooltipProvider>
)
```

### 1d. Add tooltip to each metric label (line 301)

Current code at line 301:
```tsx
<span className="font-bold text-neutral-900 tracking-tight">{metric.label}</span>
```

Replace with:
```tsx
<Tooltip>
  <TooltipTrigger asChild>
    <span className="font-bold text-neutral-900 tracking-tight cursor-help">
      {metric.label} <Info className="inline h-3 w-3 text-neutral-400" />
    </span>
  </TooltipTrigger>
  <TooltipContent>
    <div className="max-w-xs">
      <div className="mb-1 font-semibold">{METRIC_TOOLTIPS[metric.label]?.title ?? metric.label}</div>
      <div className="text-sm text-neutral-300">{METRIC_TOOLTIPS[metric.label]?.description ?? ""}</div>
    </div>
  </TooltipContent>
</Tooltip>
```

This is the only tooltip target in RiskMetrics. The label line is unique because it's the only `<span>` containing `{metric.label}` inside the `.map()` callback (line 283).

---

## Step 2: Add tooltips to RiskAnalysis component

**File:** `frontend/packages/ui/src/components/portfolio/RiskAnalysis.tsx`

### 2a. Imports (add to existing import block, lines 11-20)

```typescript
import { Info } from "lucide-react"
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from "../ui/tooltip"
```

Relative path from `components/portfolio/` to `components/ui/` -- same pattern as existing imports (e.g., line 17: `from "../ui/badge"`).

### 2b. Tooltip definitions (add before the component function, around line 94)

```typescript
const RISK_ANALYSIS_TOOLTIPS = {
  riskScore: "Individual risk factor score from 0-100. Score ≥ 80 = Low risk (safe), 60-79 = Medium (caution), 40-59 = High (danger), below 40 = Extreme (critical).",
  stressScenario: "Portfolio impact scenario based on the worst historical monthly return observed for each factor proxy, plus a synthetic high-volatility scenario.",
  potentialLoss: "Displayed percentage loss for each scenario. Factor scenarios show worst historical monthly factor return. The volatility scenario shows a scaled estimate based on annualized portfolio volatility.",
  hedgeStrategy: "Suggested hedge to offset specific factor exposure. Efficiency rating reflects correlation strength between the hedge instrument and the portfolio factor (High = |corr| > 0.5).",
}
```

### 2c. Wrap return in TooltipProvider

The component's `return` starts at line 131. The outermost element is `<div className="space-y-6">`. Wrap it:

```tsx
return (
  <TooltipProvider>
    <div className="space-y-6">
      {/* ... existing content ... */}
    </div>
  </TooltipProvider>
)
```

### 2d. Tooltip on risk factor score display (line 200)

**Important context:** Line 200 shows `{risk.score}/100` for each individual risk factor -- this is NOT an overall portfolio risk score. The `overallRiskScore` prop exists in the interface (line 83) but is never rendered anywhere in the component.

Current code at line 200:
```tsx
<span className="text-lg font-bold text-neutral-700">{risk.score}/100</span>
```

Replace with:
```tsx
<Tooltip>
  <TooltipTrigger asChild>
    <span className="text-lg font-bold text-neutral-700 cursor-help">
      {risk.score}/100 <Info className="inline h-3 w-3 text-neutral-400" />
    </span>
  </TooltipTrigger>
  <TooltipContent>
    <div className="max-w-xs text-sm text-neutral-300">
      {RISK_ANALYSIS_TOOLTIPS.riskScore}
    </div>
  </TooltipContent>
</Tooltip>
```

### 2e. Tooltip on stress test scenario names (line 253-254)

Current code at line 253-254:
```tsx
<h4 className="font-semibold text-neutral-900 mb-1">
  {test.scenario.replace(/\b\w/g, (c) => c.toUpperCase())}
</h4>
```

Replace with:
```tsx
<h4 className="font-semibold text-neutral-900 mb-1">
  <Tooltip>
    <TooltipTrigger asChild>
      <span className="cursor-help">
        {test.scenario.replace(/\b\w/g, (c) => c.toUpperCase())}
        {" "}<Info className="inline h-3 w-3 text-neutral-400" />
      </span>
    </TooltipTrigger>
    <TooltipContent>
      <div className="max-w-xs text-sm text-neutral-300">
        {RISK_ANALYSIS_TOOLTIPS.stressScenario}
      </div>
    </TooltipContent>
  </Tooltip>
</h4>
```

### 2f. Tooltip on Potential Loss display (line 262-264)

Current code at line 262-264:
```tsx
<p className="text-xl font-bold text-red-600">
  {formatPercent(test.impact, { decimals: 1 })}
</p>
```

Replace with:
```tsx
<Tooltip>
  <TooltipTrigger asChild>
    <p className="text-xl font-bold text-red-600 cursor-help">
      {formatPercent(test.impact, { decimals: 1 })}
    </p>
  </TooltipTrigger>
  <TooltipContent>
    <div className="max-w-xs text-sm text-neutral-300">
      {RISK_ANALYSIS_TOOLTIPS.potentialLoss}
    </div>
  </TooltipContent>
</Tooltip>
```

### 2g. Tooltip on hedge strategy names (line 307)

Current code at line 307:
```tsx
<h4 className="font-semibold text-neutral-900 mb-1">{hedge.strategy}</h4>
```

Replace with:
```tsx
<h4 className="font-semibold text-neutral-900 mb-1">
  <Tooltip>
    <TooltipTrigger asChild>
      <span className="cursor-help">
        {hedge.strategy}{" "}<Info className="inline h-3 w-3 text-neutral-400" />
      </span>
    </TooltipTrigger>
    <TooltipContent>
      <div className="max-w-xs text-sm text-neutral-300">
        {RISK_ANALYSIS_TOOLTIPS.hedgeStrategy}
      </div>
    </TooltipContent>
  </Tooltip>
</h4>
```

---

## Step 3: Add tooltips to FactorRiskModel component

**File:** `frontend/packages/ui/src/components/portfolio/FactorRiskModel.tsx`

### 3a. Imports (add to existing import block, lines 167-175)

```typescript
import { Info } from "lucide-react"
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from "../ui/tooltip"
```

Same relative path pattern as existing imports (e.g., line 172: `from "../ui/card"`).

### 3b. Tooltip definitions (add before the component function, around line 206)

```typescript
const FACTOR_TOOLTIPS: Record<string, string> = {
  factorExposure: "How much the portfolio tilts toward this factor. Higher absolute values = stronger tilt.",
  tStatistic: "Factor significance indicator. Currently derived from beta magnitude (|β| > 0.3 = High, > 0.15 = Medium, otherwise Low). The t-stat value itself is a placeholder (always 0).",
  riskContribution: "Share of portfolio variance from this factor bucket, normalized so all factor contributions sum to 100%. Derived from weighted factor variance sums across holdings.",
  totalRisk: "Annualized portfolio volatility (standard deviation of returns).",
  activeRisk: "Idiosyncratic volatility — the portion of portfolio risk not explained by systematic factors. Computed as totalRisk × (idiosyncratic variance share / 100). Not benchmark tracking error.",
  factorAlpha: "Annualized benchmark alpha — the regression intercept measuring portfolio skill beyond benchmark exposure (sourced from benchmark_analysis.alpha_annual). Positive = outperformance.",
  informationRatio: "Annualized excess return vs. benchmark divided by tracking error. Higher = better risk-adjusted outperformance per unit of active risk.",
  rSquared: "Factor variance share from the risk model's variance decomposition (factor_variance / 100). Represents how much of portfolio variance is explained by systematic factors.",
}
```

### 3c. Wrap return in TooltipProvider

The component's `return` starts at line 295 with `<Card className={...}>`. Wrap it:

```tsx
return (
  <TooltipProvider>
    <Card className={...}>
      {/* ... existing content ... */}
    </Card>
  </TooltipProvider>
)
```

### 3d. Tooltip on factor card labels (line 359)

Current code at line 359:
```tsx
<h4 className="font-semibold text-sm text-neutral-900">{factor.factor}</h4>
```

Replace with:
```tsx
<Tooltip>
  <TooltipTrigger asChild>
    <h4 className="font-semibold text-sm text-neutral-900 cursor-help">
      {factor.factor} <Info className="inline h-3 w-3 text-neutral-400" />
    </h4>
  </TooltipTrigger>
  <TooltipContent>
    <div className="max-w-xs text-sm text-neutral-300">
      {FACTOR_TOOLTIPS.factorExposure}
    </div>
  </TooltipContent>
</Tooltip>
```

### 3e. Tooltip on t-statistic display (line 370-372)

Current code at lines 370-372:
```tsx
<div className="text-xs text-neutral-500">
  t-stat: {formatNumber(factor.tStat,{ decimals: 2 })}
</div>
```

Replace with:
```tsx
<Tooltip>
  <TooltipTrigger asChild>
    <div className="text-xs text-neutral-500 cursor-help">
      t-stat: {formatNumber(factor.tStat,{ decimals: 2 })} <Info className="inline h-3 w-3 text-neutral-400" />
    </div>
  </TooltipTrigger>
  <TooltipContent>
    <div className="max-w-xs text-sm text-neutral-300">
      {FACTOR_TOOLTIPS.tStatistic}
    </div>
  </TooltipContent>
</Tooltip>
```

### 3f. Tooltips on Risk Attribution StatusCell components (lines 403-416)

**StatusCell constraint:** `StatusCell.label` is typed as `string` (see `status-cell.tsx` line 89: `label: string`). You cannot pass JSX (like an Info icon) into the label prop.

**Approach: Wrap each StatusCell externally with a Tooltip.** The StatusCell itself becomes the trigger.

Current code at lines 403-416:
```tsx
<StatusCell
  label="Total Risk"
  value={formatPercent(resolvedTotalRisk,{ decimals: 1 })}
  description="Annualized Volatility"
  icon={Target}
  colorScheme="purple"
/>
<StatusCell
  label="Active Risk"
  value={formatPercent(activeRisk,{ decimals: 1 })}
  description="Tracking Error"
  icon={Activity}
  colorScheme="emerald"
/>
```

Replace with:
```tsx
<Tooltip>
  <TooltipTrigger asChild>
    <div className="cursor-help">
      <StatusCell
        label="Total Risk"
        value={formatPercent(resolvedTotalRisk,{ decimals: 1 })}
        description="Annualized Volatility"
        icon={Target}
        colorScheme="purple"
      />
    </div>
  </TooltipTrigger>
  <TooltipContent>
    <div className="max-w-xs text-sm text-neutral-300">
      {FACTOR_TOOLTIPS.totalRisk}
    </div>
  </TooltipContent>
</Tooltip>
<Tooltip>
  <TooltipTrigger asChild>
    <div className="cursor-help">
      <StatusCell
        label="Active Risk"
        value={formatPercent(activeRisk,{ decimals: 1 })}
        description="Idiosyncratic Vol"
        icon={Activity}
        colorScheme="emerald"
      />
    </div>
  </TooltipTrigger>
  <TooltipContent>
    <div className="max-w-xs text-sm text-neutral-300">
      {FACTOR_TOOLTIPS.activeRisk}
    </div>
  </TooltipContent>
</Tooltip>
```

Note: The wrapping `<div>` is needed because `TooltipTrigger asChild` merges its ref onto the child, and `StatusCell` is a plain function component (not `forwardRef`). The `<div>` acts as the ref target. This does NOT change the grid layout because each tooltip+div pair occupies one grid cell, same as before.

### 3g. Tooltips on Performance tab metric cards (lines 458-470)

Current code at lines 458-470 (three metric `<Card>` elements in a 3-col grid):
```tsx
<Card className="p-4 text-center bg-gradient-to-br from-blue-50 ...">
  <div className="text-lg font-bold text-blue-900">{factorAlphaDisplay}</div>
  <div className="text-xs text-blue-700">Factor Alpha</div>
</Card>
<Card className="p-4 text-center bg-gradient-to-br from-amber-50 ...">
  <div className="text-lg font-bold text-amber-900">{informationRatioDisplay}</div>
  <div className="text-xs text-amber-700">Information Ratio</div>
</Card>
<Card className="p-4 text-center bg-gradient-to-br from-green-50 ...">
  <div className="text-lg font-bold text-green-900">{rSquaredPercentDisplay}</div>
  <div className="text-xs text-green-700">R-Squared</div>
</Card>
```

For each card, add a tooltip to the label `<div>`. Example for Factor Alpha (line 460):

Replace the label line:
```tsx
<div className="text-xs text-blue-700">Factor Alpha</div>
```
with:
```tsx
<Tooltip>
  <TooltipTrigger asChild>
    <div className="text-xs text-blue-700 cursor-help">
      Factor Alpha <Info className="inline h-3 w-3 text-blue-500" />
    </div>
  </TooltipTrigger>
  <TooltipContent>
    <div className="max-w-xs text-sm text-neutral-300">
      {FACTOR_TOOLTIPS.factorAlpha}
    </div>
  </TooltipContent>
</Tooltip>
```

Same pattern for Information Ratio (line 464, icon color `text-amber-500`, tooltip key `informationRatio`) and R-Squared (line 468, icon color `text-green-500`, tooltip key `rSquared`).

### 3h. Tooltip on Risk Contribution label in factor cards (line 378)

Current code at line 378:
```tsx
<span className="text-neutral-600">Risk Contribution</span>
```

Replace with:
```tsx
<Tooltip>
  <TooltipTrigger asChild>
    <span className="text-neutral-600 cursor-help">
      Risk Contribution <Info className="inline h-3 w-3 text-neutral-400" />
    </span>
  </TooltipTrigger>
  <TooltipContent>
    <div className="max-w-xs text-sm text-neutral-300">
      {FACTOR_TOOLTIPS.riskContribution}
    </div>
  </TooltipContent>
</Tooltip>
```

This appears once per factor card inside the `.map()` loop (line 340), so it covers all factor cards dynamically.

---

## TooltipProvider Placement Summary

| Component | Has TooltipProvider ancestor? | Action |
|-----------|------------------------------|--------|
| RiskMetrics | No (RiskMetricsContainer has no provider) | Add `<TooltipProvider>` wrapping the `<Card>` return |
| RiskAnalysis | No (RiskAnalysisModernContainer has no provider) | Add `<TooltipProvider>` wrapping the `<div className="space-y-6">` return |
| FactorRiskModel | No (FactorRiskModelContainer has no provider) | Add `<TooltipProvider>` wrapping the `<Card>` return |

The existing working example (`RiskAnalysisTab.tsx`) works because its parent `PerformanceView.tsx` wraps its entire return in `<TooltipProvider>` (line 113).

---

## Verification

```bash
cd frontend && npx tsc --noEmit
```

All three files should compile with zero new errors. No logic changes -- tooltip additions are purely additive UI.

## Summary

- 3 files modified
- ~21 tooltip placements total:
  - RiskMetrics: 1 placement (metric labels in `.map()` loop, covers all 4 metrics dynamically)
  - RiskAnalysis: 4 placements (factor score, stress scenario name, potential loss, hedge strategy name)
  - FactorRiskModel: 9 placements (factor card labels, t-stat, risk contribution label, 2 StatusCell wrappers, 3 performance metric labels)
- 3 new `<TooltipProvider>` wrappers (one per component)
- StatusCell tooltips use external `<div>` wrapper approach (no interface change needed)
- All imports use relative paths (`../ui/tooltip`)
- Content-only changes -- no logic modifications

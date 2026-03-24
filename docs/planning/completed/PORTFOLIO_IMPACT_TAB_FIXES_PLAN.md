# Portfolio Impact Tab — PM Review Fixes

## Context

PM/analyst review of the Portfolio Impact tab in Research view identified 6 issues. Three are actionable as frontend-only fixes; the rest are deferred (no backend Sharpe data available, absolute level emphasis is nice-to-have).

## Changes

### A. Neutral colors for factor exposure deltas

**Why:** Factor exposures (Market, Momentum, Value, etc.) aren't inherently good/bad when they go up or down — a PM might *want* more momentum. Red/green is misleading.

**File:** `frontend/packages/ui/src/components/portfolio/stock-lookup/PortfolioFitTab.tsx`

In the factor exposure `map` block (line ~227, the `{factorExposures.map(...)}`), change the impact column from:
```tsx
<span className={`font-semibold ${getMetricDeltaTone(metric)}`}>
```
to:
```tsx
<span className="font-semibold text-muted-foreground">
```

One line. The risk metrics table above continues using `getMetricDeltaTone`.

---

### B. Surface risk violation details

**Why:** "1 violations" badge doesn't say *which* limit failed. The data exists in `whatIfData.scenario_results.risk_analysis.risk_violations` — each row has `{Metric, Actual, Limit, Pass}`. Currently only the `.length` is used.

#### B1. Add type — `types.ts`

```ts
export interface RiskViolationDetail {
  metric: string
  actual: number | null
  limit: number | null
}
```

Add `riskViolations?: RiskViolationDetail[]` to `PortfolioFitAnalysisData`.

#### B2. Pass data through — `StockLookupContainer.tsx` (line ~848)

After `riskViolationCount`:
```ts
riskViolations: toRows(riskAnalysis.risk_violations).map((row) => {
  const r = toRecord(row);
  return {
    metric: toString(r.Metric, 'Unknown'),
    actual: toOptionalNumber(r.Actual) ?? null,
    limit: toOptionalNumber(r.Limit) ?? null,
  };
}),
```

Uses `toOptionalNumber` (already defined in this file) to preserve nulls for missing/malformed data instead of coercing to 0.

#### B3. Render violation details — `PortfolioFitTab.tsx`

After the compliance badges `</div>`, render:

```tsx
{portfolioFitAnalysis.riskViolations && portfolioFitAnalysis.riskViolations.length > 0 && (
  <div className="mt-2 space-y-1">
    {portfolioFitAnalysis.riskViolations.map((v) => (
      <div key={v.metric} className="text-xs text-red-600">
        {v.metric}: {formatPortfolioMetric(v.actual, 'percent')} (limit {formatPortfolioMetric(v.limit, 'percent')})
      </div>
    ))}
  </div>
)}
```

Also fix badge detail pluralization: `violation${count === 1 ? '' : 's'}`.

#### B4. Fix `renderCheckBadge` unavailable-state detail text

When `passes === null` (unavailable), the badge currently still appends the `detail` string, producing misleading text like "Unavailable · Factor beta exceeded". Fix: suppress detail when status is null.

In `renderCheckBadge`, change the `<span>` content from:
```tsx
{label}: {isUnavailable ? "Unavailable" : isPass ? "Pass" : "Fail"}
{detail ? ` · ${detail}` : ""}
```
to:
```tsx
{label}: {isUnavailable ? "Unavailable" : isPass ? "Pass" : "Fail"}
{!isUnavailable && detail ? ` · ${detail}` : ""}
```

---

### C. Clarify "Re-run analysis" label

**File:** `PortfolioFitTab.tsx` (line ~123)

- Change "Re-run analysis" to `<RefreshCw className="mr-1 h-3.5 w-3.5" /> Refresh`
- Add `RefreshCw` to lucide-react import

---

## Files Changed

| File | Changes |
|------|---------|
| `frontend/.../stock-lookup/types.ts` | Add `RiskViolationDetail`, add field to `PortfolioFitAnalysisData` |
| `frontend/.../modern/StockLookupContainer.tsx` | Map `risk_violations` → `riskViolations` array (null-preserving) |
| `frontend/.../stock-lookup/PortfolioFitTab.tsx` | (A) Neutral factor colors, (B) violation details + badge fix, (C) Refresh label |
| `frontend/.../stock-lookup/PortfolioFitTab.test.tsx` | Fix stale assertions, add violation + null edge-case tests |
| `frontend/.../modern/StockLookupContainer.test.tsx` | Add assertion that `riskViolations` array is passed through |

## Test Updates — `PortfolioFitTab.test.tsx`

### Stale assertions to fix (line refs from current file)

- **Line 38**: `"Systematic Risk Share"` → `"Factor-Driven Risk"` (label renamed in StockLookupContainer)
- **Line 127**: `/Re-run analysis/i` → `/Refresh/i` (Change C)
- **Line 140**: `"Systematic Risk Share"` → `"Factor-Driven Risk"`
- **Line 141**: `"Risk: Fail · 2 violations"` → `"Risk Limits: Fail · 2 violations"` (matches actual badge label)
- **Line 142**: `"Beta: Pass"` → `"Factor Beta Limits: Pass · All betas within limits"` (matches actual badge label + detail)
- **Line 143**: `"FACTOR EXPOSURE CHANGES"` → `"Factor Exposure Changes"` (component uses CSS `uppercase`; DOM text is title-case; JSDOM does not apply text-transform)
- **Line 162**: Same fix — `queryByText("FACTOR EXPOSURE CHANGES")` → `queryByText("Factor Exposure Changes")`

### Fixture update

Add to `portfolioFitAnalysis` fixture:
```ts
riskViolations: [
  { metric: 'Max Position Weight', actual: 0.05, limit: 0.045 },
  { metric: 'Annual Volatility', actual: 0.125, limit: 0.12 },
],
```

### New assertions to add

1. **Violation detail rendering**: Assert exact violation detail strings, e.g. `screen.getByText("Max Position Weight: 5.0% (limit 4.5%)")` — avoids ambiguity with the existing "Max Position Weight" metric row and "Risk Limits" / "within limits" badge text
2. **Null violation values**: Add a test case rendering with `riskViolations: [{ metric: 'Test', actual: null, limit: null }]` — assert exact string `"Test: — (limit —)"` (via `formatPortfolioMetric(null, 'percent')` which returns "—")
3. **Unavailable badge suppression**: Add a test case with `riskPasses: null, betaPasses: null` — assert detail suffixes like " · 2 violations" and " · All betas within limits" are NOT present in the rendered badges

### `StockLookupContainer.test.tsx` updates

- **Line 465**: `'Systematic Risk Share'` → `'Factor-Driven Risk'` (label renamed in container)
- **Flip `risk_passes`** (line ~54): change `risk_passes: true` → `risk_passes: false` to match the added violations
- **Add violation row to fixture** (line ~55): change `risk_violations: []` to include at least one row: `risk_violations: [{ Metric: 'Max Weight', Actual: 0.05, Limit: 0.045, Pass: false }]`
- **Add assertion**: verify `riskViolations` array is present in the assembled result with `expect.arrayContaining([expect.objectContaining({ metric: 'Max Weight', actual: 0.05, limit: 0.045 })])`

## Not Doing

- **Sharpe/return impact**: What-if engine doesn't compute returns. Would need backend work.
- **Absolute level emphasis**: Nice-to-have but adds complexity for marginal gain.

## Verification

1. Load AAPL on Research → Portfolio Impact tab
2. Confirm factor exposure deltas are all gray/neutral (not red/green)
3. Confirm risk violation details show metric name + actual vs limit below the badge
4. Confirm "Refresh" button with icon replaces "Re-run analysis"
5. Run frontend tests: `cd frontend && npx vitest run`

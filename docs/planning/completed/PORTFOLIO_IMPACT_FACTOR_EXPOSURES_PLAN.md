# Add Factor Exposure Changes to Portfolio Impact Tab

## Context
The what-if analysis already returns per-factor exposure changes (`factor_exposures_comparison` with market, momentum, value, industry, interest_rate, subindustry — each with current/scenario/delta). This data is extracted in the container (line 753) but only the market factor is used. The rest is thrown away. An investor wants to see how adding a stock changes their factor exposures — "adding AAPL increases market beta by 0.01 but decreases momentum exposure by 0.04."

## Approach
Add factor exposure changes as a separate section below the existing risk metrics table in the Portfolio Impact tab. Use the same `PortfolioFitMetricRow` format so it renders consistently. Keep it separate from the risk metrics so the investor can distinguish "risk impact" from "factor exposure changes."

## Implementation

### Step 1: Extract all factor exposures in the container
**File:** `frontend/.../StockLookupContainer.tsx` (~line 753)

`factorExposuresComparison` is already extracted. Build an array of factor exposure rows:

```typescript
const factorExposureMetrics: PortfolioFitMetricRow[] = Object.entries(
  factorExposuresComparison
).filter(([name]) => name !== '__proto__')
  .map(([name, rawValue]) => {
    const exposure = toRecord(rawValue)
    return {
      label: formatFactorName(name),
      before: toOptionalNumber(exposure.current) ?? null,
      after: toOptionalNumber(exposure.scenario) ?? null,
      format: 'beta' as const,
    }
  })
  .filter(row => row.before !== null || row.after !== null)
```

Add `factorExposureMetrics` to the `portfolioFitAnalysis` return object.

### Step 2: Update PortfolioFitAnalysisData type
**File:** `frontend/.../stock-lookup/types.ts`

Add `factorExposures` to the interface:
```typescript
export interface PortfolioFitAnalysisData {
  scenarioName: string
  deltaLabel: string
  metrics: PortfolioFitMetricRow[]
  factorExposures?: PortfolioFitMetricRow[]  // new
  riskPasses: boolean | null
  riskViolationCount: number
  betaPasses: boolean | null
}
```

### Step 3: Render factor exposures in PortfolioFitTab
**File:** `frontend/.../stock-lookup/PortfolioFitTab.tsx`

Below the existing Impact Analysis metrics table and risk badges, add a "Factor Exposure Changes" section:

```
FACTOR EXPOSURE CHANGES
                Current  With Position  Impact
Market          0.37     0.38           +0.01
Momentum        0.46     0.43           -0.04
Value          -0.15    -0.16           -0.00
Industry        0.62     0.62           -0.01
Interest Rate   1.69     1.65           -0.04
```

- Same table format as the risk metrics above
- Small uppercase section label "FACTOR EXPOSURE CHANGES" (same style as "MARKET BETA" / "FACTOR DRIVERS" labels)
- Only show when `factorExposures` array is non-empty
- Format values as beta (2 decimal places, no % suffix)
- Color the Impact column: green for decrease (reducing exposure), red for increase — but this depends on context, so use neutral coloring (just show the delta without color judgment, since increasing market beta isn't necessarily bad)

### Step 4: Export formatFactorName from helpers
**File:** `frontend/.../stock-lookup/helpers.ts`

`formatFactorName` is currently a private `const` (not exported). Add `export` so the container can import it. No logic changes.

### Step 5: Sort factor exposures deterministically
Backend builds `factor_exposures_comparison` from a Python dict (order not guaranteed). Sort the factor rows in a fixed order in the container:

```typescript
const FACTOR_DISPLAY_ORDER = ['market', 'momentum', 'value', 'industry', 'subindustry', 'interest_rate']

// After building factorExposureMetrics, sort:
factorExposureMetrics.sort((a, b) => {
  const aIdx = FACTOR_DISPLAY_ORDER.indexOf(a.rawName)
  const bIdx = FACTOR_DISPLAY_ORDER.indexOf(b.rawName)
  return (aIdx === -1 ? 99 : aIdx) - (bIdx === -1 ? 99 : bIdx)
})
```

(Include `rawName` temporarily for sorting, strip before returning.)

### Step 6: Use neutral delta coloring for factor exposures
**File:** `frontend/.../stock-lookup/PortfolioFitTab.tsx`

The existing metrics table uses `getMetricDeltaTone` which colors increases red and decreases green. For factor exposures, use **neutral coloring** (muted text, no red/green) since increasing a factor beta isn't inherently bad or good. Use `text-muted-foreground` for the impact column in the factor exposures section.

## Files Changed

| File | Changes |
|------|---------|
| `StockLookupContainer.tsx` | Build factorExposureMetrics array, sort deterministically, add to portfolioFitAnalysis |
| `types.ts` | Add `factorExposures?: PortfolioFitMetricRow[]` to PortfolioFitAnalysisData |
| `PortfolioFitTab.tsx` | Render factor exposure changes table with neutral delta coloring |
| `helpers.ts` | Export `formatFactorName` (add `export` keyword) |

| `StockLookupContainer.test.tsx` | Add fixture for factor_exposures_comparison, assert factorExposures populated |
| `PortfolioFitTab.test.tsx` | Assert factor exposure section renders, order is deterministic, hidden when empty |

6 files. No backend changes — data already flows from the what-if response.

## Verification
1. Load Stock Lookup → AAPL → Portfolio Impact tab
2. Impact Analysis should show risk metrics table (existing) + factor exposure changes table (new)
3. Factor exposures should match MCP: market ~0.37→0.38, momentum ~0.46→0.43, etc.
4. Factor order is consistent: Market, Momentum, Value, Industry, Subindustry, Interest Rate
5. Factor deltas use neutral coloring (no red/green)
6. Change size to 5% — both tables should update with new analysis
7. Empty state: if no factor exposures in response, section is hidden

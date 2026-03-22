# Risk Drivers: Two-Tier Bivariate Layout

## Context
The multi-factor variance attribution (previous commit) produces confusing results — negative Industry contribution, sign flips — because Market and Industry are too correlated for joint regression. Reverting the frontend to use bivariate R² (which is consistent with the MCP beta calculations) with a two-tier layout that gives a clean Market vs Non-Market split plus factor detail.

Backend `variance_attribution` stays (useful for MCP/AI context). Only the frontend rendering changes.

## Target Layout

**Tier 1 — Clean 100% split (Market vs Non-Market):**
- Market: R² from the market factor regression (e.g., 48%)
- Non-Market: 1 - market R² (e.g., 52%) — includes industry, factor, and company-specific risk
- These two always sum to exactly 100%
- Label: "Non-Market" (NOT "Company-Specific" — that's misleading since it includes industry/value/momentum)

**Tier 2 — Factor Detail (independent regressions, may overlap):**
- Other factors sorted by R² descending (Industry, Value, Momentum, Subindustry)
- Each shows bivariate R² — "how much this single factor explains independently"
- Labeled as "Factor Correlations" with note "Independent — may overlap"

## Implementation

### Step 1: Update `buildRiskDriverDisplay` in helpers.ts
**File:** `frontend/packages/ui/src/components/portfolio/stock-lookup/helpers.ts`

Replace the current `buildRiskDriverDisplay` (which uses varianceAttribution with clamping/renormalization) with a simpler bivariate-based version:

```typescript
export const buildRiskDriverDisplay = ({
  factorSummary,
}: {
  varianceAttribution?: Record<string, number> | null  // keep param for compat, ignore
  factorSummary?: FactorSummary | null
}): RiskDriverDisplayData => {
  if (!factorSummary?.beta) {
    // No factor data → empty state (don't show fake 0%/100%)
    return { riskFactors: [], marketR2Pct: undefined, idiosyncraticPct: undefined }
  }

  // Build ALL bivariate factors BEFORE bucketing (don't use buildBivariateRiskFactors
  // which already buckets to top-3 — we need to extract market first)
  const allFactors = Object.entries(factorSummary.beta).map(([name, rawBeta]) => {
    const betaValue = toFiniteNumber(rawBeta) ?? 0
    const rSquaredRaw = toFiniteNumber(factorSummary.r_squared?.[name])
    const rSquared = rSquaredRaw !== null ? Math.max(0, rSquaredRaw) : null  // null = missing, not 0
    const displayName = formatFactorName(name)
    return {
      name: displayName,
      rawName: name,
      exposure: toExposurePct(betaValue),
      risk: rSquared !== null ? Math.round(rSquared * 100) : null,  // null = unknown
      description: `${displayName} factor: β=${betaValue.toFixed(2)}, R²=${(rSquared * 100).toFixed(1)}%`,
    }
  })

  // Tier 1: Market R² → Non-Market = 1 - market R²
  // Only compute when market has a real finite R² (not defaulted from missing data)
  const marketRSquared = toFiniteNumber(factorSummary.r_squared?.["market"])
  const marketR2 = marketRSquared !== null ? Math.round(marketRSquared * 100) : undefined
  const idiosyncraticPct = marketR2 !== undefined ? 100 - marketR2 : undefined

  // Tier 2: Non-market factors with valid R², sorted descending (omit unknown)
  const otherFactors = allFactors
    .filter(f => f.rawName !== "market" && f.risk !== null)
    .sort((a, b) => (b.risk ?? 0) - (a.risk ?? 0))

  return {
    riskFactors: otherFactors,
    marketR2Pct: marketR2,
    idiosyncraticPct,
  }
}
```

Update `RiskDriverDisplayData` type: `marketR2Pct` and `idiosyncraticPct` are both `number | undefined` (undefined when no factor data or no market factor available).

### Step 2: Update StockLookup.tsx
**File:** `frontend/packages/ui/src/components/portfolio/StockLookup.tsx`

Update the destructuring to get `marketR2Pct` and pass all three to RisksSignalsTab:
```typescript
const { riskFactors, marketR2Pct, idiosyncraticPct } = buildRiskDriverDisplay({
  factorSummary: selectedStock?.factorSummary,
})
```

### Step 3: Update RisksSignalsTab.tsx
**File:** `frontend/packages/ui/src/components/portfolio/stock-lookup/RisksSignalsTab.tsx`

Add `marketR2Pct` prop. Restructure the Risk Drivers card into two tiers:

**Tier 1 — "Market vs Non-Market"** (only renders when `marketR2Pct` is defined):
- Two bars: Market (blue, `marketR2Pct`%) and Non-Market (neutral/gray, `idiosyncraticPct`%)
- Small label: "= 100%"

**Tier 2 — "Factor Correlations":**
- Section header: "Factor Correlations" with subtitle "Independent — may overlap"
- All non-market factors as compact rows with single bar each, sorted by R²
- These use the bivariate R² values (same as current `risk` field)
- Tooltip on each: `factor.description` (shows beta + R²)

**Empty state:** When no factor data, show "Factor analysis not available" inside the card (same as current).

### Step 4: Update helpers.test.ts
**File:** `frontend/packages/ui/src/components/portfolio/stock-lookup/helpers.test.ts`

Update tests for the new `buildRiskDriverDisplay` shape:
- Test with valid factorSummary: marketR2Pct populated, otherFactors sorted, idiosyncratic = 100 - market
- Test with missing factor data: all fields undefined, empty riskFactors
- Test with no market factor: marketR2Pct undefined, other factors still populated
- Test with beta present but r_squared missing/partial: Tier 1 undefined, Tier 2 omits factors with missing R² (not fake 0%)
- Remove variance attribution tests (no longer used in display)

## Files Changed

| File | Changes |
|------|---------|
| `frontend/.../helpers.ts` | Simplify `buildRiskDriverDisplay` to bivariate two-tier, unbucketed |
| `frontend/.../StockLookup.tsx` | Pass `marketR2Pct` to RisksSignalsTab |
| `frontend/.../RisksSignalsTab.tsx` | Two-tier layout: Market/Non-Market + Factor Correlations |
| `frontend/.../helpers.test.ts` | Update tests for new shape |

4 frontend files. No backend changes.

## Verification
1. Risk Drivers card: Tier 1 shows Market X% + Non-Market Y% = 100%
2. Tier 2 shows remaining factors with bivariate R² (may sum to >100%, that's expected)
3. Subtitle says "Independent — may overlap"
4. Empty state works when no factor data
5. `npm test -- --run helpers.test.ts` passes

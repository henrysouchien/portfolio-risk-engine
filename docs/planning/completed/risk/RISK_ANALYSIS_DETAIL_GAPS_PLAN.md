# Risk Analysis Detail Gaps — Computed Text + Hedging Data

**Status**: COMPLETE
**Date**: 2026-03-04

## Context

The Risk Analysis view has two categories of hardcoded placeholder content:

1. **Risk factor descriptions** — 4 risk factors (Concentration, Volatility, Factor, Sector) have hardcoded `description`, `mitigation`, and `timeline` strings in `RiskAnalysisModernContainer.tsx:305-365`. The `impact` field already uses real component scores from `useRiskScore()`. The backend provides `industry_variance_absolute`, `portfolio_factor_betas`, `annual_volatility`, and `portfolio_weights` — all available in the container via `useRiskAnalysis()` but unused for text generation.

2. **Hedging detail overrides** — Two layers of hardcoded values:
   - **HedgingAdapter.ts:149-164** hardcodes `expectedCost: 0`, `protectedValue: 0`, `beforeVaR: "N/A"`, `afterVaR: "N/A"`, `portfolioBeta: "N/A"`.
   - **RiskAnalysis.tsx:314-339** overwrites adapter `details` with a second set of hardcoded values: `riskReduction: 25`, `expectedCost: 12500`, `protectedValue: 450000`, `beforeVaR: "-$100K"`, `afterVaR: "-$75K"`, `portfolioBeta: "1.00 → 0.85"`, `duration: "3 months"`, and hardcoded `implementationSteps`.

   Both layers must be fixed — the container enriches adapter output with portfolio context via `useMemo`, and `RiskAnalysis.tsx` passes through the enriched output instead of overriding it.

**Goal:** Replace all hardcoded text with computed values from available backend data. No backend changes required.

---

## Part 1: Risk Factor Computed Descriptions (container only)

### 1a. Add helper functions to RiskAnalysisModernContainer.tsx

Add a `buildRiskFactorDescription()` helper (above the `transformedData` block, ~line 232) that takes the available data and returns computed `description`, `mitigation`, and `timeline` for each factor.

**Data available in the container (all from `useRiskAnalysis()` → `RiskAnalysisAdapter.transform()`):**
- `data?.portfolio_weights` — `Record<string, number>` (ticker → weight decimal)
- `data?.industry_variance_absolute` — `Record<string, number>` (industry ETF → **absolute variance**, e.g., `{ IGV: 0.004394, KCE: 0.003031 }`. These are NOT percentages — must sum all values and compute each as `value / totalVariance * 100` to get percentage contribution.)
- `data?.portfolio_factor_betas` — `Record<string, number>` (factor name → beta)
- `data?.risk_metrics?.annual_volatility` — `number` (**already percent**, e.g., 18.4 = 18.4%. Adapter multiplies by 100 at `RiskAnalysisAdapter.ts:536-537`. Do NOT multiply again.)
- `data?.variance_decomposition` — `{ factor_variance: number, idiosyncratic_variance: number }` (0-100 scale)
- `riskScoreData?.component_scores` — `Array<{ name, score, maxScore }>` (0-100 scale)

### 1b. Concentration Risk — computed from `portfolio_weights`

```
description: "Top 3 positions: {T1} ({W1}%), {T2} ({W2}%), {T3} ({W3}%) — {sumTop3}% of portfolio"
mitigation:  score < 60 → "Reduce {T1} from {W1}% toward {target}% target"
             score >= 60 → "Portfolio is reasonably diversified across {N} positions"
timeline:    "Actionable immediately via rebalancing"
```

Compute from `data?.portfolio_weights`: sort by absolute weight descending, pick top N tickers + weights (where N = min(3, count)). If fewer than 3 holdings, show what's available (e.g., "Top position: AAPL (52%)"). If no weight data or empty, fall back to current hardcoded strings. Handle short/negative weights by using absolute values for sorting but showing signed values. Weight values are decimals (0.15 = 15%) — multiply by 100 for display.

### 1c. Volatility Risk — computed from `risk_metrics.annual_volatility`

```
description: "Annual portfolio volatility: {vol}% — {characterization}"
  characterization: <12 → "low", 12-20 → "moderate", 20-30 → "elevated", >30 → "high"
mitigation:  score < 60 → "Consider lower-volatility assets or protective hedges to reduce portfolio vol"
             score >= 60 → "Volatility within acceptable range for current risk profile"
timeline:    "Ongoing — volatility fluctuates with market conditions"
```

Use `data?.risk_metrics?.annual_volatility` directly (already percent — e.g., 18.4). Do NOT multiply by 100. Fallback to hardcoded if `!Number.isFinite(vol) || vol <= 0`.

### 1d. Factor Risk — computed from `portfolio_factor_betas`

```
description: "Dominant exposure: {factor} (β={beta}) — {factorVariance}% of risk from factor exposure"
  Pick the factor with the largest absolute beta from portfolio_factor_betas
  factorVariance from variance_decomposition.factor_variance
mitigation:  score < 60 → "Reduce {dominantFactor} exposure — consider factor-neutral hedges"
             score >= 60 → "Factor exposures are balanced across {N} factors"
timeline:    "Systematic — requires active factor management to reduce"
```

Compute from `data?.portfolio_factor_betas` + `data?.variance_decomposition?.factor_variance`. If `portfolio_factor_betas` is empty or missing `market` key, fall back. Handle edge case where all betas are zero.

### 1e. Sector Risk — computed from `industry_variance_absolute`

```
description: "Top sector risk: {sector} ({contribution}% of variance) — {N} sectors tracked"
  Pick the industry with highest variance contribution from industry_variance_absolute
mitigation:  score < 60 → "Reduce {topSector} concentration — currently dominates portfolio variance"
             score >= 60 → "Sector risk well-distributed across {N} industries"
timeline:    "Can be reduced through sector rebalancing within 1-2 trades"
```

**Unit conversion required:** `industry_variance_absolute` values are raw absolute variance (e.g., 0.004394), NOT percentages. To compute `{contribution}%`:
```typescript
const totalVariance = Object.values(industryVariance).reduce((sum, v) => sum + v, 0);
const contributionPct = totalVariance > 0 ? (topValue / totalVariance) * 100 : 0;
```
Fallback if empty or `totalVariance === 0`.

### 1f. Wire into factor construction

Replace the hardcoded strings at lines 317-319, 332-334, 347-349, 362-364 with calls to the helper, passing the relevant data + component score.

---

## Part 2: Hedging — Post-Transform Enrichment in Container

**Approach:** All hedging enrichment happens in `RiskAnalysisModernContainer.tsx` via a `useMemo` that enriches the already-transformed `HedgeStrategy[]`. The `HedgingAdapter.ts` and `useHedgingRecommendations.ts` are NOT modified. This avoids the stale-cache problem where threading context through `useHedgingRecommendations` wouldn't trigger re-transform (the query key is `hedgingRecommendationsKey(portfolioId)` — context values aren't in the key, so context changes are invisible to TanStack Query).

### 2a. Add `enrichedHedgingData` useMemo in RiskAnalysisModernContainer.tsx

After line 145 (`useHedgingRecommendations` call), add:

```typescript
const enrichedHedgingData = useMemo(() => {
  if (!hedgingData?.length) return hedgingData ?? [];
  const pv = data?.portfolio_summary?.total_value;
  const beta = data?.portfolio_factor_betas?.market;
  const volPct = data?.risk_metrics?.annual_volatility; // already percent (e.g., 18.4)
  // If no portfolio context at all, return raw adapter output (keeps adapter defaults)
  if (pv == null && beta == null && volPct == null) return hedgingData;

  return hedgingData.map(strategy => {
    const riskReduction = Math.max(0, Math.min(100, strategy.details.riskReduction));
    const expectedCost = pv ? Math.round(pv * (strategy.suggestedWeight ?? 0.05)) : 0;

    // VaR: parametric 95% 1-day, matching RiskMetricsContainer.tsx:132
    // Formula: portfolioValue × (volPct / 100) × (1.645 / √252)
    let beforeVaR: string = 'N/A';
    let afterVaR: string = 'N/A';
    if (pv && volPct && Number.isFinite(volPct) && volPct > 0) {
      const dailyVaR = pv * (volPct / 100) * (1.645 / Math.sqrt(252));
      beforeVaR = `-$${Math.round(dailyVaR).toLocaleString()}`;
      const reducedVaR = dailyVaR * (1 - riskReduction / 100);
      afterVaR = `-$${Math.round(reducedVaR).toLocaleString()}`;
    }

    return {
      ...strategy,
      details: {
        ...strategy.details,
        expectedCost,
        beforeVaR,
        afterVaR,
        portfolioBeta: beta != null ? beta.toFixed(2) : 'N/A',
      },
    };
  });
}, [hedgingData, data?.portfolio_summary?.total_value, data?.portfolio_factor_betas?.market, data?.risk_metrics?.annual_volatility]);
```

Then pass `enrichedHedgingData` instead of `hedgingData` to `transformedData.hedgingStrategies` (line 412).

**Note on `protectedValue`:** The raw `driver.percent_of_portfolio` (decimal, e.g., 0.28) is consumed by the adapter to build the `protection` string (e.g., "28% of portfolio") but is NOT preserved as a numeric field in `HedgeStrategy`. Rather than modifying the adapter interface, leave `protectedValue` at the adapter's default (`0`). The `protection` string already communicates the percentage to the user. If we later want a numeric `protectedValue`, we would need to either (a) add a `protectionPct` field to `HedgeStrategy` in the adapter, or (b) parse the protection string. Both are out of scope for this pass.

### 2b. Update `RiskAnalysisProps` type and remove overrides in RiskAnalysis.tsx

**Type update:** The `hedgingStrategies` array in `RiskAnalysisProps` (line 210) currently omits `duration` and `details`. The local `HedgeStrategy` interface (line 174) requires them. Update the props type to include all fields:

```typescript
// RiskAnalysis.tsx line 210 — update hedgingStrategies prop type
hedgingStrategies: Array<{
  strategy: string;
  cost: string;
  protection: string;
  duration: string;          // ADD — from adapter ("Rebalance")
  efficiency: 'High' | 'Medium' | 'Low';
  hedgeTicker: string;
  suggestedWeight: number;
  details: {                 // ADD — from enriched adapter output
    description: string;
    riskReduction: number;
    expectedCost: number;
    protectedValue: number;
    implementationSteps: string[];
    marketImpact: {
      beforeVaR: string;
      afterVaR: string;
      riskReduction: string;
      portfolioBeta: string;
    };
  };
}>;
```

**Remove hardcoded override (lines 314-339):** Replace the mapping that constructs hardcoded `duration`, `details`, etc. with a simple pass-through:

```typescript
// RiskAnalysis.tsx line 314 — replace hardcoded mapping
const hedgingStrategies: HedgeStrategy[] = (data?.hedgingStrategies && data.hedgingStrategies.length > 0) ?
  data.hedgingStrategies.map(hs => ({
    ...hs,  // Pass through all fields from enriched adapter output
  })) : [
    // ... keep existing fallback mock data (lines 340-400) for no-data case
  ]
```

**Fallback branch (line 340+):** Keep the existing mock data in the else branch. This only fires when `data?.hedgingStrategies` is empty/missing, which means the backend returned no hedging data. The mock ensures the UI isn't blank during development or if the hedging API is unavailable.

### 2c. Also update container's `transformedData.hedgingStrategies`

In `RiskAnalysisModernContainer.tsx` at line 412, the container currently passes:
```typescript
hedgingStrategies: hedgingData ?? []
```

This must also include `duration` and `details` in the passed objects. Since `enrichedHedgingData` already contains these (from the adapter → enrichment), just change to:
```typescript
hedgingStrategies: enrichedHedgingData
```

The container's `transformedData` type at this point maps `HedgeStrategy[]` from the adapter. The enriched data preserves all fields. No additional mapping needed.

---

## Files Summary

| Part | File | Action |
|------|------|--------|
| 1 | `frontend/.../views/modern/RiskAnalysisModernContainer.tsx` | Add `buildRiskFactorDescription()` helper; replace 12 hardcoded strings with computed text |
| 2 | `frontend/.../views/modern/RiskAnalysisModernContainer.tsx` | Add `enrichedHedgingData` useMemo for post-transform enrichment; pass to `transformedData` |
| 2 | `frontend/.../components/portfolio/RiskAnalysis.tsx` | Update `RiskAnalysisProps.hedgingStrategies` type to include `duration` + `details`; remove hardcoded override at lines 314-339; keep fallback mock data at lines 340+ |

**NOT modified:** `HedgingAdapter.ts`, `useHedgingRecommendations.ts` — all enrichment is post-transform in the container.

---

## Edge Cases

1. **Fewer than 3 holdings** — Concentration description shows available positions (1 or 2), not "top 3"
2. **Non-finite / NaN weights** — Filter with `Number.isFinite()` before sorting
3. **Short positions (negative weights)** — Sort by absolute value, display signed
4. **Missing `market` key in `portfolio_factor_betas`** — Factor Risk falls back to generic text
5. **Zero portfolio value** — Hedging shows `expectedCost: 0`, VaR fields show `'N/A'` (not `'$0'`)
6. **`riskReduction` > 100 or < 0** — Clamp to [0, 100] before VaR computation
7. **Risk data loads after hedging data** — `enrichedHedgingData` useMemo recomputes reactively
8. **`industry_variance_absolute` is absolute, not percent** — Must sum all values and divide each by total to get percentage
9. **`protectedValue` stays at adapter default (0)** — `driver.percent_of_portfolio` not exposed as numeric in `HedgeStrategy`. The `protection` string already shows the percentage to users. Numeric `protectedValue` deferred to a future pass that adds `protectionPct` to the adapter.

---

## Verification

1. `pnpm typecheck && pnpm build` — clean
2. Chrome: Risk Analysis view → Risk Factors tab:
   - Concentration Risk description shows top positions with real weights from portfolio
   - Volatility Risk shows actual annual volatility % (should match Risk Metrics card)
   - Factor Risk shows dominant factor beta
   - Sector Risk shows top industry by variance percentage (computed from absolute values)
3. Chrome: Risk Analysis view → Hedging tab:
   - Strategy cards show computed expectedCost (not 0 or 12500)
   - VaR before/after show dollar amounts (not "N/A" or "-$100K")
   - Portfolio beta shows real number (not "1.00 → 0.85")
   - `protectedValue` shows 0 (acceptable — deferred)
4. Fallback: If risk data hasn't loaded, descriptions fall back to current generic text (no blank/broken UI)
5. Fallback: If no hedging data from backend, mock data (lines 340+) still renders (not blank)
6. VaR consistency: `beforeVaR` in hedging tab should roughly match `Value at Risk` shown in Risk Metrics cards (both use same formula: `portfolioValue × (volPct/100) × 1.645/√252`)
7. TypeScript: `RiskAnalysisProps.hedgingStrategies` type includes `duration` and `details` — no type errors when passing enriched data from container

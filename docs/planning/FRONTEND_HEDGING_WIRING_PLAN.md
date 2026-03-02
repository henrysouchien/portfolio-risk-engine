# Wave 2b: Hedging Suggestions — Wire Frontend to Existing Backend

**Date**: 2026-02-27
**Status**: COMPLETE — fully end-to-end functional. Frontend wiring (commit `1c66dae7`): `useHedgingRecommendations` hook + `HedgingAdapter` + container wiring. Backend fixes (commit `475a67e5`): ETF→sector label resolution in `_resolve_label()`, `correlation_threshold` -0.2→0.3 (equity sectors can't have negative correlations), driver labels resolved to readable sector names. Verified in Chrome 2026-02-28: real strategies display (e.g. "Hedge Financial - Mortgages exposure").
**Parent doc**: `FRONTEND_PHASE2_WORKING_DOC.md` (Wave 2, task 2b)

## Context

The RiskAnalysis.tsx hedging tab shows 3 hardcoded mock strategies (Put Options on QQQ, VIX Calls, Gold Position). The `RiskAnalysisModernContainer` passes `hedgingStrategies: []` with a TODO comment saying "requires separate analysis endpoint."

**Key discovery**: The backend endpoint **already exists**:
- `POST /api/factor-intelligence/portfolio-recommendations` — takes `{weights: {ticker: weight}}`, detects portfolio risk drivers, returns correlation-based hedge recommendations with suggested weights
- Served by `FactorIntelligenceService.recommend_portfolio_offsets()` → `PortfolioOffsetRecommendationResult`
- Returns: `{drivers: [{type, label, percent_of_portfolio?, market_beta?}], recommendations: [{label, category, correlation, sharpe_ratio?, suggested_weight?}], analysis_metadata, formatted_report}`
- Driver types: `{"type": "industry", "label": "Financial Services", "percent_of_portfolio": 0.52}` or `{"type": "market", "label": "SPY", "market_beta": 1.35}` — industry drivers have `percent_of_portfolio`, market drivers have `market_beta` instead
- Not all recommendations have `sharpe_ratio` — treat as optional (default 0)

The frontend already has `portfolio_weights` available from the risk analysis response (via `RiskAnalysisAdapter`).

**Goal**: Wire the frontend to call the existing portfolio-recommendations endpoint and transform the response into the `HedgeStrategy[]` format the component expects. No backend changes needed.

---

## Current Frontend Hedging Data Flow

```
RiskAnalysis.tsx
  ↓ expects data.hedgingStrategies (HedgeStrategy[])
  ↓ falls back to 3 hardcoded strategies when empty
RiskAnalysisModernContainer.tsx (line 411)
  ↓ hedgingStrategies: []  // TODO
RiskAnalysisAdapter.ts
  ↓ no hedging fields mapped
```

## Target Data Flow

```
RiskAnalysisModernContainer.tsx
  ↓ gets portfolio_weights from useRiskAnalysis() data
  ↓ calls useHedgingRecommendations(weights) — new hook
     ↓ POST /api/factor-intelligence/portfolio-recommendations {weights}
     ↓ returns PortfolioOffsetRecommendationResult.to_api_response()
  ↓ transforms response → HedgeStrategy[] via HedgingAdapter
  ↓ passes to RiskAnalysis.tsx
```

---

## Implementation Plan

### Step 1: Add API method to `chassis/src/services/APIService.ts`

Add `getHedgingRecommendations(weights)` method. APIService has no `post()` helper — use the private `request()` method with POST config (same pattern as `getMinVarianceOptimization` and `getWhatIfAnalysis`):
```typescript
async getHedgingRecommendations(weights: Record<string, number>): Promise<PortfolioHedgingResponse> {
  return this.request('/api/factor-intelligence/portfolio-recommendations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ weights }),
  });
}
```

### Step 2: Define types in `chassis/src/types/index.ts`

Match the actual backend response shape from `FactorIntelligenceService.recommend_portfolio_offsets()`:

```typescript
export interface HedgingDriver {
  type: string;                     // "industry" or "market"
  label: string;                    // e.g. "Financial Services" or "SPY"
  percent_of_portfolio?: number;    // present on industry drivers only
  market_beta?: number;             // present on market drivers only
}

export interface HedgingRecommendation {
  label: string;
  category: string;
  correlation: number;
  sharpe_ratio?: number;            // not guaranteed on every item
  suggested_weight?: number;
  rationale?: string;
  overexposed_label?: string;       // links recommendation to its driver — use for grouping by driver
}

export interface PortfolioHedgingResponse {
  drivers: HedgingDriver[];
  recommendations: HedgingRecommendation[];
  analysis_metadata: Record<string, unknown>;
  formatted_report: string;
}
```

### Step 3: Create `HedgingAdapter` in `connectors/src/adapters/HedgingAdapter.ts`

Transform `PortfolioHedgingResponse` → `HedgeStrategy[]` (the interface `RiskAnalysis.tsx` expects).

**Important**: The component's mapping conditional (lines 314-338) hardcodes `duration: "3 months"` and replaces all `details` fields with generic values when `data.hedgingStrategies` is present. So the adapter only needs to supply the fields the component actually uses from the incoming data: `strategy`, `cost`, `protection`, `efficiency`. The `details` fields are still required by the `HedgeStrategy` interface, so we provide reasonable defaults, but the component overwrites them anyway.

**HedgeStrategy interface** (from RiskAnalysis.tsx):
```typescript
interface HedgeStrategy {
  strategy: string;
  cost: string;
  protection: string;
  duration: string;
  efficiency: "High" | "Medium" | "Low";
  details: {
    description: string;
    riskReduction: number;
    expectedCost: number;
    protectedValue: number;
    implementationSteps: string[];
    marketImpact: { beforeVaR: string; afterVaR: string; riskReduction: string; portfolioBeta: string; };
  };
}
```

**Mapping logic** — group recommendations by driver using `recommendation.overexposed_label` → match to `driver.label`. Each driver becomes a strategy card, using its best recommendation (highest `|correlation|`):

- **strategy**: `"Hedge {driver.label} exposure"` (e.g., "Hedge Financial Services exposure")
- **cost**: `"~{suggested_weight * 100}% allocation"` or `"N/A"` if no weight
- **protection**: For industry drivers: `"{percent_of_portfolio * 100}% of portfolio"`. For market drivers: `"Beta {market_beta}"`.
- **duration**: `"Rebalance"` (correlation-based hedges aren't time-limited like options). Note: component currently overwrites with "3 months".
- **efficiency**: Map from correlation strength: `|corr| > 0.5` → `"High"`, `> 0.3` → `"Medium"`, else `"Low"`
- **details.description**: `"{strategy} — top candidate: {recommendation.label} ({recommendation.category})"`
- **details.riskReduction**: `Math.round(Math.abs(correlation) * 100)`
- **details.expectedCost**: `0` (correlation hedges don't have a direct cost like options)
- **details.protectedValue**: `0` (same reasoning)
- **details.implementationSteps**: Generate from recommendation label + category: `["Allocate to {label} ({category})", "Rebalance portfolio to target weights", "Monitor correlation effectiveness"]`
- **details.marketImpact**: `{ beforeVaR: "N/A", afterVaR: "N/A", riskReduction: "{riskReduction}%", portfolioBeta: "N/A" }`

**Driver type handling**: Industry drivers have `percent_of_portfolio`, market drivers have `market_beta` instead — adapter must check `driver.type` and branch accordingly.

**`sharpe_ratio` handling**: Not guaranteed on every recommendation — default to `0` when missing.

Limit to top 3 strategies (matching current UI layout).

### Step 4: Create `useHedgingRecommendations` hook in `connectors/src/features/`

```typescript
function useHedgingRecommendations(weights: Record<string, number> | undefined) {
  // TanStack Query hook
  // Only fires when weights is non-empty (enabled: !!weights && Object.keys(weights).length > 0)
  // Longer staleTime (10min) — hedge recommendations don't change rapidly
  // Returns memoized object matching established hook contract:
  // { data, loading, isLoading, isRefetching, error, refetch, hasData, hasError }
}
```
Follow the same return shape as `usePositions` — `useMemo` wrapping query results with dual `loading`/`isLoading`, `hasData`, `hasError`, `refetch`, `isRefetching`.

Query key: add `hedgingRecommendationsKey` to `queryKeys.ts` using the existing scoped factory pattern. The key must be scoped to `portfolioId` so hedging results are not reused across different portfolios/weights:
```typescript
export const hedgingRecommendationsKey = (portfolioId?: string | null) => scoped('hedgingRecommendations', portfolioId);
```
This follows the same convention as `riskScoreKey`, `riskAnalysisKey`, `performanceKey`, etc.

### Step 5: Wire into `RiskAnalysisModernContainer.tsx`

Replace the TODO line:
```typescript
// Before:
hedgingStrategies: [], // TODO

// After:
hedgingStrategies: hedgingData ?? [],
```

Where `hedgingData` comes from the new `useHedgingRecommendations(data?.portfolio_weights)` hook.

### Step 6: Verify `RiskAnalysis.tsx` conditional — no changes needed

The existing conditional (lines 314-338) handles `data?.hedgingStrategies?.length > 0` → maps incoming data to `HedgeStrategy[]`. It reads `strategy`, `cost`, `protection`, and `efficiency` from the incoming data, but hardcodes `duration: "3 months"` and all `details` sub-fields (description, riskReduction=25, expectedCost=12500, protectedValue=450000, generic implementationSteps, generic marketImpact).

**No changes to RiskAnalysis.tsx in this wave.** The adapter provides all required fields (satisfying the TypeScript interface), but the component overrides `duration` and `details` with its own defaults. This is acceptable for now — a future iteration can update the component to use the adapter's driver-specific details instead of hardcoding them. Keep the fallback mock strategies as graceful degradation for when the endpoint fails.

---

## Files Modified

| File | Action |
|------|--------|
| `chassis/src/services/APIService.ts` | **Edit** — add `getHedgingRecommendations()` method |
| `chassis/src/types/index.ts` | **Edit** — add `HedgingDriver`, `HedgingRecommendation`, `PortfolioHedgingResponse` types |
| `chassis/src/queryKeys.ts` | **Edit** — add `hedgingRecommendationsKey` |
| `connectors/src/adapters/HedgingAdapter.ts` | **New** — transform backend response → `HedgeStrategy[]` |
| `connectors/src/features/hedging/hooks/useHedgingRecommendations.ts` | **New** — TanStack Query hook |
| `connectors/src/index.ts` | **Edit** — export new hook |
| `ui/src/components/dashboard/views/modern/RiskAnalysisModernContainer.tsx` | **Edit** — wire hook, pass hedgingStrategies |

No backend changes. No changes to `RiskAnalysis.tsx` (existing conditional handles real data).

---

## Key Design Decisions

1. **Separate hook, not embedded in useRiskAnalysis**: Hedging recommendations are a distinct API call with different caching needs. Don't bloat the risk analysis response.

2. **Keep fallback strategies**: If the hedging endpoint fails or returns empty, the hardcoded strategies still show. Better UX than an empty tab.

3. **Portfolio-aware mode only**: Use `portfolio-recommendations` (auto-detects drivers) rather than `recommendations` (requires specifying a single factor). The portfolio mode is what users want — "what should I hedge?" not "how do I hedge Technology specifically?"

4. **Weights from risk analysis**: `portfolio_weights` is already in the risk analysis response. No need for a separate positions call.

---

## Verification

1. **Chrome visual test**: Navigate to Risk Analysis → Hedging tab. Should see real driver-based strategies instead of hardcoded QQQ/VIX/Gold.
2. **Empty portfolio**: If `portfolio_weights` is empty/undefined, hook doesn't fire, falls back to hardcoded strategies.
3. **Backend error**: If endpoint returns error, hook error state → falls back to hardcoded strategies.
4. **Network tab**: Verify `POST /api/factor-intelligence/portfolio-recommendations` fires with correct weights payload.
5. **TypeScript**: `npx tsc --noEmit` passes.

---

## Codex Review Log

| Round | Result | Issues |
|-------|--------|--------|
| R1 | FAIL | (1) Driver field is `type` not `driver_type` in actual backend. (2) Market driver has `market_beta` but no `percent_of_portfolio`. (3) `sharpe_ratio` not guaranteed on every recommendation. (4) Plan didn't cover all HedgeStrategy required fields (description, expectedCost, protectedValue). (5) Component hardcodes duration/details in mapping conditional. (6) APIService has no `post()` method — uses `request()` with POST config. (7) Query key should use factory pattern. |
| R2 | FAIL | (1) Query key not scoped to portfolioId — hedging results could be reused across different portfolios. (2) `HedgingRecommendation` type missing `overexposed_label` field needed for grouping by driver. (3) Hook return contract thinner than established pattern — should include `loading`, `isRefetching`, `refetch`, `hasData`, `hasError`. |
| R3 | PASS | All 9 checks verified against codebase. Plan implementable as-is. |

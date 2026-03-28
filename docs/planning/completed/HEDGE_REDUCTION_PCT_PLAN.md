# Hedge Tool — Reduction Percentage Control

> **Codex review**: R1 FAIL (1H/2M/1L) → **R2 PASS**

## Context

The hedge tool's Direct Offset strategies use a `reduction_pct` parameter (default 0.5 = 50%) to compute suggested weights: `suggested_weight = -(driver_beta × reduction_pct)`. This parameter exists in the backend (`_compute_direct_offsets()` in `factor_intelligence_service.py`) but is hardcoded — not exposed through the REST API, resolver, or frontend.

Adding a UI control lets users adjust how aggressively they want to offset each driver (25% light hedge → 100% full neutralization), making the tool more interactive and the recommendations more actionable.

## Changes

### 1. Backend — Add `reduction_pct` to REST request model

**File**: `models/factor_intelligence_models.py`

Add to `PortfolioOffsetRecommendationRequest`:
```python
reduction_pct: float = Field(default=0.5, ge=0.0, le=1.0, description="Fraction of driver exposure to offset via direct shorts")
```

### 2. Backend — Thread through route handler

**File**: `routes/factor_intelligence.py`

In the `POST /api/factor-intelligence/portfolio-recommendations` handler (~line 257), pass `reduction_pct=rec_request.reduction_pct` to `service.recommend_portfolio_offsets()`.

### 3. Backend — Thread through service method

**File**: `services/factor_intelligence_service.py`

Add `reduction_pct: float = 0.5` parameter to `recommend_portfolio_offsets()` (~line 1377). Pass it to `self._compute_direct_offsets(..., reduction_pct=reduction_pct)` at ~line 1640 (currently called without it).

### 4. Frontend — Add to resolver/API layer (3 files)

**File 1**: `frontend/packages/chassis/src/catalog/types.ts` (~line 759)

Add `reductionPct?: number` to the `hedging-recommendations` source params type so `useDataSource` accepts it.

**File 2**: `frontend/packages/chassis/src/services/APIService.ts` (~line 1485)

Add `reductionPct?: number` parameter to `getHedgingRecommendations()`. Include `reduction_pct: reductionPct` in the POST body (camelCase → snake_case at the HTTP boundary).

**File 3**: `frontend/packages/connectors/src/resolver/registry.ts` (~line 841)

Thread `params?.reductionPct` through to `api.getHedgingRecommendations(...)`.

**Optional**: Update `frontend/packages/chassis/src/catalog/descriptors.ts` (~line 530) if catalog metadata should reflect the new parameter.

### 5. Frontend — Add to hook

**File**: `frontend/packages/connectors/src/features/hedging/hooks/useHedgingRecommendations.ts`

Add `reductionPct?: number` as a third parameter. Include it in the resolver params object. It must also be part of the query key so changing the value triggers a re-fetch.

### 6. Frontend — Add preset selector to HedgeTool

**File**: `frontend/packages/ui/src/components/portfolio/scenarios/tools/HedgeTool.tsx`

Add a simple preset selector above the Per-Driver Recommendations section. Four options:

```
Light (25%)  |  Moderate (50%)  |  Aggressive (75%)  |  Full (100%)
```

Implementation: a row of 4 small buttons (toggle group pattern). Default: "Moderate (50%)" selected. Selecting a different preset updates `reductionPct` state and passes it to `useHedgingRecommendations`, which triggers a re-fetch.

**Styling**: Match the existing scenario tool pattern — small `rounded-full` pill buttons in a flex row, selected state uses `bg-foreground text-background`, unselected uses `bg-muted/50 text-muted-foreground`. Place below the metrics strip, above the separator.

```jsx
const REDUCTION_PRESETS = [
  { label: "Light", value: 0.25 },
  { label: "Moderate", value: 0.5 },
  { label: "Aggressive", value: 0.75 },
  { label: "Full", value: 1.0 },
] as const

const [reductionPct, setReductionPct] = useState(0.5)
```

**Note**: `reductionPct` only affects **industry** Direct Offset strategies. The market/SPY branch in `_compute_direct_offsets()` (~line 1238) uses `scale_factor` instead and ignores `reduction_pct`. Beta Alternatives and Diversification use fixed small allocations. The UI label should make this clear: "Offset strength" or "How much industry exposure to neutralize" with a subtitle "Applies to industry direct offset strategies."

### 7. State reset

When `reductionPct` changes, the diagnosis re-fetches (new query key). The existing `diagnosisIdentity` reset logic in HedgeTool already clears expanded rows, preview cache, etc. — no additional reset code needed as long as `reductionPct` flows into `hedgingWeights` or is part of the resolver params that change the query key. However, `diagnosisIdentity` currently includes only `portfolioId`, `hedgingWeights`, and `portfolioValue`. Since `reductionPct` changes the response but not those keys, we need to add it to `diagnosisIdentity` so transient state resets on re-fetch.

## Files to Modify

| File | Change |
|------|--------|
| `models/factor_intelligence_models.py` | Add `reduction_pct` field to request model |
| `routes/factor_intelligence.py` | Thread `reduction_pct` to service call |
| `services/factor_intelligence_service.py` | Add param to `recommend_portfolio_offsets()`, pass to `_compute_direct_offsets()` |
| `frontend/packages/connectors/src/features/hedging/hooks/useHedgingRecommendations.ts` | Add `reductionPct` param, include in query key |
| Resolver registry (wherever `hedging-recommendations` is registered) | Pass `reductionPct` to API call |
| `frontend/packages/ui/src/components/portfolio/scenarios/tools/HedgeTool.tsx` | Add preset selector UI, state, pass to hook |

## Test Updates

Existing tests that need updating for the new parameter:

| Test file | Update needed |
|-----------|---------------|
| `tests/factor_intelligence/test_request_models.py` | Add `reduction_pct` field validation test (range 0.0–1.0, default 0.5) |
| `tests/services/test_factor_intelligence_service.py` | Add test that `reduction_pct=0.25` produces half the weight of `reduction_pct=0.5` |
| `frontend/packages/connectors/src/resolver/__tests__/hedgingResolver.test.ts` | Verify `reductionPct` is threaded to API call |
| `frontend/packages/connectors/src/features/hedging/__tests__/useHedgingRecommendations.test.tsx` | Verify hook accepts and passes `reductionPct` |

**Note**: No existing route test for `POST /api/factor-intelligence/portfolio-recommendations` — adding one is out of scope for this change but should be tracked.

**MCP tool**: Not updated in this plan. The MCP tool (`mcp_tools/factor_intelligence.py`) calls `recommend_portfolio_offsets()` without `reduction_pct`, which will continue using the 0.5 default. MCP parity can be added separately if needed.

## Verification

1. `pytest tests/ -k "factor_intelligence or hedge"` — backend tests pass
2. `npx tsc --noEmit` from `frontend/` — zero TS errors
3. Open `localhost:3000/#scenarios/hedge`, select "Light (25%)" → verify industry Direct Offset weights halve (e.g., DSU -14.3% → ~-7.1%)
4. Select "Full (100%)" → verify weights double (e.g., DSU -14.3% → ~-28.6%)
5. Verify market Direct Offset (SPY) weights are unchanged across presets (uses `scale_factor`, not `reduction_pct`)
6. Verify Beta Alternatives and Diversification rows are unchanged across presets
7. Verify switching presets clears preview cache and resets expanded rows

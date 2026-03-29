# Scenario-Aware Hedge Recommendations

> **v2** — revised after Codex review (6 findings addressed).

## Context

The hedge engine (`recommend_portfolio_offsets()`) currently recommends hedges based on **portfolio composition** — it ranks industry groups by variance share and recommends offsets per group. It doesn't know *why* you're hedging or *what scenario* you're protecting against.

When a user runs a stress test showing "Market Crash: -15% impact, AAPL worst position" and clicks "Find a hedge", the hedge tool shows the same generic recommendations it would show without the stress test. The scenario intelligence is lost.

This plan makes hedge recommendations scenario-aware: when stress test context is available, **re-rank drivers by scenario impact** instead of variance share. The industry that gets hit hardest in *this scenario* becomes the top hedge priority.

**Key insight**: The stress test and hedge systems use different factor namespaces (stress: rate/market/style factors; hedge: industry groups/market). The bridge is **position-level data** — aggregate `position_impacts` by industry group to get scenario-weighted industry rankings.

### Codex v1 Findings Addressed

1. **F1 — Driver REPLACE is unsafe**: Changed to overlay/rerank with coverage-gated fallback. Only replaces when ≥50% of scenario impact is mapped; otherwise falls back to variance-share drivers.
2. **F2 — camelCase/snake_case mismatch**: Added typed Pydantic `ScenarioContext` model with explicit snake_case fields + `model_config = ConfigDict(extra="forbid")`. Frontend serialization converts camelCase→snake_case in APIService.
3. **F3 — `percent_of_portfolio` overloaded**: Scenario drivers use separate `scenario_impact_pct` field; `percent_of_portfolio` retains original variance-share meaning from the full `industry_pct` dict (not pruned drivers).
4. **F4 — Market driver threshold underspecified**: Market driver uses `abs(contribution) > 10.0` (10% of total scenario impact), with explicit `abs()`. Justification: stress test market contributions can be large negative values; 10% threshold filters noise while keeping material market exposure.
5. **F5 — Frontend navigation path unresolved**: Documented the full Zustand flow: `onNavigate("hedge", {scenarioContext})` → `setActiveTool` → `uiStore.toolContext` → `HedgeTool context prop` → `context.scenarioContext`.
6. **F6 — Missing test cases**: Added 5 additional tests for serialization, partial coverage fallback, signed ranking, market factor normalization, and navigation integration.

### Codex v2 Findings Addressed

7. **F7 — `scenario_aware=True` on fallback**: Flag now only set to `True` when overlay was actually applied (coverage ≥ 0.5 and drivers replaced). When falling back, `scenario_aware=False` with `scenario_fallback_reason` explaining why.
8. **F8 — `percent_of_portfolio` for novel industries**: Lookup uses the full `industry_pct` dict from `view["industry_variance"]["percent_of_portfolio"]`, not the already-pruned top-5 drivers. Novel industries get `0.0` (they exist in scenario but below variance threshold).
9. **F9 — camelCase rejection not guaranteed**: All three nested Pydantic models use `model_config = ConfigDict(extra="forbid")`. This produces 422 on unknown/camelCase keys.
10. **F10 — Coverage formula false fallback**: Coverage computed per-position before industry netting: `mapped_coverage = sum(abs(pct) for mapped positions) / sum(abs(pct) for all positions)`. Industry aggregation happens after coverage check.

### Codex v3 Findings Addressed

11. **F11 — Market driver not merged into scenario_drivers**: Clarified that the market driver check is inside the `if scenario_overlay_applied` block, appended to `scenario_drivers` list BEFORE `drivers = scenario_drivers`. The code block in Step 1c already shows this flow but the summary was ambiguous.
12. **F12 — Zero-signal scenario misclassified**: Added `any(abs(v) > 0 for v in scenario_impact.values())` gate. If all industries net to zero after aggregation, overlay is not applied; fallback_reason = "no_net_scenario_impact".
13. **F13 — Stale context regression**: Fixed properly — all navigation paths to HedgeTool now explicitly set `source`. Direct hedge opens use `onNavigate("hedge")` which sets `toolContext = {}` (no source field). The `context.source === "stress-test"` check works because `setActiveTool(tool, context)` replaces `toolContext` entirely (not merged). Every navigation overwrites the previous context.
14. **F14 — Missing edge case tests**: Added tests for exact `mapped_coverage == 0.5` boundary (should apply overlay) and `total_abs == 0` (should fallback with reason "empty_position_impacts").

### Codex v4 Findings Addressed

15. **F15 — Stale context deeper fix**: The key insight is that `setActiveTool` always replaces `toolContext` entirely (`set({ toolContext: context ?? {} })`). When HedgeTool tab is clicked directly, it navigates with `setActiveTool("hedge")` → `toolContext = {}` → `context.source` is `undefined`. The check `context.source === "stress-test"` is therefore safe against stale Zustand state because every navigation call overwrites. Added explicit documentation of this Zustand replacement behavior.
16. **F16 — HedgingAdapter missing fields**: Added `scenario_impact_pct` and `scenario_mapped_coverage` to the adapter pass-through alongside `scenario_aware`, `scenario_name`, `scenario_fallback_reason`.
17. **F17 — Serialization test missing**: Added frontend unit test for APIService that verifies the camelCase→snake_case serialization produces correct request body (position_impacts, factor_contributions, scenario_name, estimated_portfolio_impact_pct).

### Codex v5 Findings Addressed

18. **F18 — Fallback scenario invisible to user**: When user navigates from stress test but overlay fails (insufficient coverage, zero signal), HedgeTool now shows a fallback info banner explaining why generic recommendations are shown instead. Maps fallback_reason to user-friendly copy.

---

## Step 1: Backend — Add `scenario_context` parameter

### 1a. Request model — typed Pydantic models (F2 fix)

**File**: `models/factor_intelligence_models.py`

Add typed nested models instead of `Dict[str, Any]`. All use `extra="forbid"` (F9) to reject camelCase/unknown keys:
```python
from pydantic import ConfigDict

class ScenarioPositionImpact(BaseModel):
    """Single position's stress-test contribution."""
    model_config = ConfigDict(extra="forbid")
    ticker: str
    portfolio_contribution_pct: float

class ScenarioFactorContribution(BaseModel):
    """Single factor's stress-test contribution."""
    model_config = ConfigDict(extra="forbid")
    factor: str
    contribution_pct: float

class ScenarioContext(BaseModel):
    """Stress test context for scenario-aware hedge driver re-ranking."""
    model_config = ConfigDict(extra="forbid")
    position_impacts: List[ScenarioPositionImpact] = Field(
        default_factory=list,
        description="Per-position scenario P&L contributions (from stress test).",
    )
    factor_contributions: List[ScenarioFactorContribution] = Field(
        default_factory=list,
        description="Per-factor scenario contributions (from stress test).",
    )
    scenario_name: str = ""
    estimated_portfolio_impact_pct: float = 0.0
```

Add field to `PortfolioOffsetRecommendationRequest` (after `industry_granularity`):
```python
scenario_context: Optional[ScenarioContext] = Field(
    default=None,
    description="Stress test context for scenario-aware driver re-ranking.",
)
```

### 1b. Route threading

**File**: `routes/factor_intelligence.py`

Thread `scenario_context=rec_request.scenario_context` to `service.recommend_portfolio_offsets()`.

### 1c. Core logic — `recommend_portfolio_offsets()`

**File**: `services/factor_intelligence_service.py`

**Signature change**: Add `scenario_context: Optional[ScenarioContext] = None` (import from models).

**New helper method** `_build_scenario_industry_impact()`:
1. Takes `position_impacts: List[ScenarioPositionImpact]` and `ticker_industry_map: Dict[str, str]`
2. The `ticker_industry_map` maps each portfolio ticker to its industry ETF proxy (e.g. `"AAPL" → "XLK"`)
3. **F10 — Coverage computed per-position before industry netting**:
   - First pass: for each position, check if ticker is in ticker_industry_map
   - `mapped_abs = sum(abs(p.portfolio_contribution_pct) for p where ticker in map)`
   - `total_abs = sum(abs(p.portfolio_contribution_pct) for all p)`
   - `mapped_coverage = mapped_abs / total_abs` (0.0 if total_abs == 0)
4. Second pass: aggregate mapped positions' `portfolio_contribution_pct` by industry ETF (signed values preserved for display)
5. Returns `(Dict[str, float], float)` — `({industry_etf: total_scenario_contribution_pct}, mapped_coverage)`

The `ticker_industry_map` comes from `analysis_result.factor_proxies` when available — each entry has an `"industry"` key with the proxy ETF ticker.

**Driver re-ranking with coverage-gated fallback** (F1 fix — after existing driver detection, ~line 1573):
```python
if scenario_context and scenario_context.position_impacts:
    # Build ticker → industry ETF map from analysis_result.factor_proxies
    ticker_industry_map = {}
    if analysis_result and hasattr(analysis_result, "factor_proxies"):
        for tkr, proxies in (analysis_result.factor_proxies or {}).items():
            if isinstance(proxies, dict):
                ind = proxies.get("industry")
                if ind:
                    ticker_industry_map[str(tkr).upper()] = str(ind).upper()

    scenario_impact, mapped_coverage = self._build_scenario_industry_impact(
        scenario_context.position_impacts, ticker_industry_map
    )

    # F1: Only replace drivers when ≥50% of scenario impact is mapped.
    # F12: Also require at least one non-zero impact after industry netting.
    # Otherwise fall back to variance-share drivers (better than empty/degraded).
    scenario_overlay_applied = False
    has_nonzero_impact = any(abs(v) > 0 for v in scenario_impact.values()) if scenario_impact else False
    if mapped_coverage >= 0.5 and scenario_impact and has_nonzero_impact:
        scenario_overlay_applied = True
        # F8: Use full industry_pct dict for variance-share lookup, not pruned drivers
        # industry_pct is the full dict from view["industry_variance"]["percent_of_portfolio"]
        # already computed above during normal driver detection

        scenario_drivers = []
        for etf_ticker, impact_pct in sorted(
            scenario_impact.items(), key=lambda kv: abs(kv[1]), reverse=True
        )[:5]:
            display_label = _etf_to_sector_label(etf_ticker)
            scenario_drivers.append({
                "type": "industry",
                "driver_type": "industry",
                "label": display_label,
                # F8: percent_of_portfolio from full industry_pct, not pruned drivers
                "percent_of_portfolio": round(float(industry_pct.get(etf_ticker, 0)), 4),
                # F3: separate field for scenario impact
                "scenario_impact_pct": round(impact_pct, 4),
                "proxy_ticker": etf_ticker,
            })

        # F4/F11: Market driver from factor contributions — appended to scenario_drivers
        # before replacing drivers list, so market signal reaches recommendation generation
        fc = scenario_context.factor_contributions
        market_contrib = next(
            (f.contribution_pct for f in fc
             if f.factor.lower() in ("market", "mkt", "spy")),
            None
        )
        if market_contrib is not None and abs(market_contrib) > 10.0:
            scenario_drivers.append({
                "type": "market", "driver_type": "market",
                "label": "Market", "proxy_ticker": "SPY",
                "market_beta": round(market_beta, 3) if market_beta else None,
                "scenario_market_contribution_pct": round(market_contrib, 2),
            })

        # F11: scenario_drivers now contains industry + optional market driver
        drivers = scenario_drivers
    # else: mapped_coverage < 0.5 or zero-signal → keep original variance-share drivers
```

**Scenario metadata on output** (add to `analysis_metadata`):
```python
if scenario_context:
    analysis_metadata["scenario_name"] = scenario_context.scenario_name
    analysis_metadata["scenario_impact_pct"] = scenario_context.estimated_portfolio_impact_pct
    # F7: scenario_aware = True only when overlay was applied, not just when context was present
    analysis_metadata["scenario_aware"] = scenario_overlay_applied
    analysis_metadata["scenario_mapped_coverage"] = round(mapped_coverage, 4) if 'mapped_coverage' in dir() else None
    if not scenario_overlay_applied:
        if not scenario_context.position_impacts:
            analysis_metadata["scenario_fallback_reason"] = "empty_position_impacts"
        elif 'mapped_coverage' in dir() and mapped_coverage < 0.5:
            analysis_metadata["scenario_fallback_reason"] = "insufficient_coverage"
        elif 'has_nonzero_impact' in dir() and not has_nonzero_impact:
            analysis_metadata["scenario_fallback_reason"] = "no_net_scenario_impact"
        else:
            analysis_metadata["scenario_fallback_reason"] = "unknown"
```

When `scenario_context` is `None`, all behavior is unchanged.

---

## Step 2: Frontend — Thread scenario context through

### 2a. Types

**File**: `frontend/packages/chassis/src/catalog/types.ts`

Add `scenarioContext` to `SDKSourceParamsMap['hedging-recommendations']`:
```typescript
scenarioContext?: {
  positionImpacts: Array<{ ticker: string; portfolioContributionPct: number }>;
  factorContributions: Array<{ factor: string; contributionPct: number }>;
  scenarioName: string;
  estimatedPortfolioImpactPct: number;
};
```

### 2b. API service — explicit camelCase→snake_case serialization (F2 fix)

**File**: `frontend/packages/chassis/src/services/APIService.ts`

Add `scenarioContext` parameter to `getHedgingRecommendations()`. When present, serialize to snake_case for the backend Pydantic model:
```typescript
if (scenarioContext) {
  requestBody.scenario_context = {
    position_impacts: scenarioContext.positionImpacts.map(p => ({
      ticker: p.ticker,
      portfolio_contribution_pct: p.portfolioContributionPct,
    })),
    factor_contributions: scenarioContext.factorContributions.map(f => ({
      factor: f.factor,
      contribution_pct: f.contributionPct,
    })),
    scenario_name: scenarioContext.scenarioName,
    estimated_portfolio_impact_pct: scenarioContext.estimatedPortfolioImpactPct,
  };
}
```

### 2c. Resolver

**File**: `frontend/packages/connectors/src/resolver/registry.ts`

Thread `params?.scenarioContext` to `api.getHedgingRecommendations()`.

### 2d. Hook

**File**: `frontend/packages/connectors/src/features/hedging/hooks/useHedgingRecommendations.ts`

Add optional `scenarioContext` parameter. Pass through to `useDataSource` params.

---

## Step 3: Frontend — StressTest exit ramp + HedgeTool UI

### Navigation context flow (F5 — documented)

The full data path from StressTestTool to HedgeTool:
1. StressTestTool calls `onNavigate("hedge", { scenarioContext, label, source })`
2. `onNavigate` = `setActiveTool` from `useScenarioRouterState()` (Zustand selector)
3. `setActiveTool` updates `uiStore`: `set({ activeTool: "hedge", toolContext: { scenarioContext, ... } })`
4. `ScenariosRouter` re-renders, passes `toolContext` as `context` prop to HedgeTool
5. HedgeTool reads `context.scenarioContext` — the full stress test payload

### 3a. StressTestTool exit ramp enrichment

**File**: `frontend/packages/ui/src/components/portfolio/scenarios/tools/StressTestTool.tsx`

Change `handleHedgeNavigation` (~line 366) to pass scenario data:
```typescript
onNavigate("hedge", {
  label: lastRunScenarioName ?? stressTest.data?.scenarioName ?? "Stress Test",
  source: "stress-test",
  scenarioContext: stressTest.data ? {
    positionImpacts: stressTest.data.positionImpacts.map(p => ({
      ticker: p.ticker,
      portfolioContributionPct: p.portfolioContributionPct,
    })),
    factorContributions: stressTest.data.factorContributions.map(f => ({
      factor: f.factor,
      contributionPct: f.contributionPct,
    })),
    scenarioName: stressTest.data.scenarioName,
    estimatedPortfolioImpactPct: stressTest.data.estimatedImpactPct,
  } : undefined,
})
```

### 3b. HedgeTool scenario-aware UI

**File**: `frontend/packages/ui/src/components/portfolio/scenarios/tools/HedgeTool.tsx`

1. Extract `scenarioContext` from `context` prop, guarded by source check (F13/F15 — prevents stale context):
   ```typescript
   // F13/F15: Only use scenarioContext when navigated from stress-test.
   // Safe against stale Zustand state because setActiveTool always REPLACES toolContext
   // entirely: set({ toolContext: context ?? {} }). Every navigation overwrites.
   // Direct hedge tab click → setActiveTool("hedge") → toolContext = {} → source undefined.
   const scenarioContext = context?.source === "stress-test"
     ? (context?.scenarioContext as SDKSourceParamsMap['hedging-recommendations']['scenarioContext'] | undefined)
     : undefined
   ```
2. Pass to `useHedgingRecommendations(weights, portfolioValue, reductionPct, scenarioContext)`
3. Show scenario banner when scenario-aware, or fallback info when overlay was not applied (F18):
```typescript
{isScenarioAware && (
  <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
    <span className="font-semibold">Scenario-aware:</span>{' '}
    Hedging against {scenarioName} ({impactPct.toFixed(1)}% impact)
  </div>
)}
{/* F18: When navigated from stress test but overlay failed, explain why */}
{hasScenarioContext && !isScenarioAware && (
  <div className="rounded-2xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800">
    <span className="font-semibold">Note:</span>{' '}
    {scenarioFallbackReason === 'insufficient_coverage'
      ? 'Not enough position data could be mapped to industries for scenario-specific hedging. Showing general recommendations.'
      : scenarioFallbackReason === 'no_net_scenario_impact'
      ? 'The scenario has no net impact on any industry. Showing general recommendations.'
      : 'Showing general recommendations.'}
  </div>
)}
```

### 3c. HedgingAdapter pass-through (F16)

**File**: `frontend/packages/connectors/src/adapters/HedgingAdapter.ts`

Pass through all scenario metadata from `analysis_metadata` into adapter output:
- `scenario_aware` → `scenarioAware: boolean`
- `scenario_name` → `scenarioName: string`
- `scenario_impact_pct` → `scenarioImpactPct: number`
- `scenario_mapped_coverage` → `scenarioMappedCoverage: number`
- `scenario_fallback_reason` → `scenarioFallbackReason: string | undefined`

Add optional `scenarioImpactPct` to driver data when present.

---

## Step 4: Tests

### Backend tests (`tests/services/test_scenario_aware_hedging.py`)

**Original tests:**
- `test_no_scenario_context_unchanged` — verify None = identical behavior
- `test_scenario_reranks_drivers_by_impact` — position_impacts concentrated in one industry → that industry driver is first
- `test_scenario_market_driver_from_factor_contributions` — significant market factor contribution → market driver added even with low portfolio beta
- `test_scenario_metadata_in_output` — `scenario_aware: True` + `scenario_name` + `scenario_mapped_coverage` in analysis_metadata
- `test_empty_position_impacts_fallback` — empty list → falls back to variance-share ranking
- `test_unmapped_positions_ignored` — positions without industry mapping (cash, futures) don't break aggregation
- `test_scenario_driver_has_impact_pct` — `scenario_impact_pct` field present on scenario-ranked drivers

**F6 — Additional tests for high-risk failures:**
- `test_partial_proxy_coverage_fallback` — when <50% of scenario impact maps to industries, falls back to variance-share drivers (not empty), `scenario_aware=False`, `scenario_fallback_reason="insufficient_coverage"`
- `test_negative_contributions_ranked_by_abs` — negative `portfolio_contribution_pct` values ranked by `abs()` (e.g. -15% ranks above +8%)
- `test_market_factor_name_normalization` — factor names "market", "mkt", "SPY" all match the market driver rule
- `test_scenario_context_pydantic_validation` — typed ScenarioContext model with `extra="forbid"` rejects malformed input (wrong types, missing fields, camelCase keys)
- `test_full_coverage_replaces_drivers` — when 100% mapped, scenario drivers fully replace variance-share drivers, `scenario_aware=True`

**F7-F10 — Additional tests:**
- `test_scenario_aware_false_on_fallback` — scenario_context present but coverage < 0.5 → `scenario_aware=False` in metadata, `scenario_fallback_reason` present (F7)
- `test_novel_industry_gets_zero_variance_share` — scenario highlights industry not in original top-5 drivers → `percent_of_portfolio` from full `industry_pct` dict, defaults to 0.0 (F8)
- `test_coverage_computed_per_position_not_post_netting` — two positions in same industry with opposite signs both count toward mapped coverage (F10)

**F11-F14 — Additional tests:**
- `test_zero_signal_scenario_fallback` — all position impacts net to zero within industries → `scenario_aware=False`, `scenario_fallback_reason="no_net_scenario_impact"` (F12)
- `test_exact_50pct_coverage_applies_overlay` — mapped_coverage exactly 0.5 → overlay is applied (boundary, F14)
- `test_total_abs_zero_fallback` — all positions have `portfolio_contribution_pct=0.0` → `total_abs=0`, `mapped_coverage=0.0`, fallback with "empty_position_impacts" (F14)

### Route test
- `test_endpoint_accepts_scenario_context` — POST with scenario_context in body (snake_case) → 200, threads to service
- `test_endpoint_scenario_context_camelcase_rejected` — POST with camelCase keys in scenario_context → 422 (`extra="forbid"` rejects; confirms frontend must serialize)

### Frontend tests (7)
- Integration test: stress test navigation populates HedgeTool with scenarioContext
- Stale-context test: HedgeTool opened directly (no source="stress-test" in context) → scenarioContext is undefined, vanilla hedge behavior (F13/F15)
- Serialization test: APIService.getHedgingRecommendations() with scenarioContext produces correct snake_case request body — verifies position_impacts, factor_contributions, scenario_name, estimated_portfolio_impact_pct (F17)
- Adapter metadata test: HedgingAdapter.transform() passes all 5 scenario metadata fields (scenarioAware, scenarioName, scenarioImpactPct, scenarioMappedCoverage, scenarioFallbackReason) (F16)
- Fallback banner test: when scenarioAware=false and scenarioFallbackReason is present (stress-test source), HedgeTool renders blue info banner with correct user-facing message per reason code (F18)
- Success banner test: when scenarioAware=true, HedgeTool renders amber scenario-aware banner with scenario name and impact percentage
- No-banner test: ordinary hedge request (no scenarioContext, no source="stress-test") → neither amber nor blue banner renders

---

## Files Summary

**Backend (4 files)**:
1. `models/factor_intelligence_models.py` — add `scenario_context` to request model
2. `routes/factor_intelligence.py` — thread to service call
3. `services/factor_intelligence_service.py` — `_build_scenario_industry_impact()` + driver re-ranking logic
4. `tests/services/test_scenario_aware_hedging.py` — 7+ tests

**Frontend (7 files)**:
5. `chassis/src/catalog/types.ts` — add `scenarioContext` to params type
6. `chassis/src/services/APIService.ts` — add param to `getHedgingRecommendations()`
7. `connectors/src/resolver/registry.ts` — thread to API call
8. `connectors/src/features/hedging/hooks/useHedgingRecommendations.ts` — add param
9. `ui/src/.../tools/StressTestTool.tsx` — exit ramp enrichment
10. `ui/src/.../tools/HedgeTool.tsx` — scenario banner + pass to hook
11. `connectors/src/adapters/HedgingAdapter.ts` — scenario metadata pass-through

---

## Verification

1. **Without scenario**: Run hedge tool directly → same behavior as today
2. **With scenario**: Run stress test (Market Crash) → click "Find a hedge" → Hedge shows "Scenario-aware: Hedging against Market Crash (-15.2% impact)" banner, drivers ranked by scenario impact
3. **Driver re-ranking visible**: Compare driver order with/without scenario — worst-hit industry should be first in scenario mode
4. **Type safety**: `tsc --noEmit` clean
5. **Backend tests**: `python3 -m pytest tests/services/test_scenario_aware_hedging.py -x -v`
6. **Frontend tests**: `cd frontend && npx vitest run --reporter=verbose`
7. **E2E**: Run Scenario 4 from `SCENARIO_CHAINING_TEST_DESIGN.md` — "Find and hedge my biggest risk"

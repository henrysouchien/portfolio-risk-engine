# Risk Score Per-Component Insights

## Context

The Risk Score tab cards (Concentration, Volatility, Factor, Sector) expand to show "Mitigation Strategy" and "Implementation Timeline" — both are placeholder text generated in the frontend container. The backend already generates specific, data-driven findings and recommendations per category in `run_detailed_limits_analysis()`, but emits them as flat lists. The category information is lost by the time it reaches the frontend.

**Fix**: Build a per-component insights dict in the backend (same pattern as `_build_risk_drivers()`), pass it through the API/adapter, and render it directly. No keyword matching, no string parsing.

## Changes

### Step 1: Build per-component insights in backend

**File:** `portfolio_risk_engine/portfolio_risk_score.py` — `run_detailed_limits_analysis()` (~line 761)

Currently the function appends to flat `risk_factors` and `recommendations` lists. Add a parallel `per_component` dict that captures findings and actions by component as they're generated:

```python
risk_factors = []
recommendations = []
violation_details = []
per_component = {
    "factor_risk": {"findings": [], "actions": []},
    "concentration_risk": {"findings": [], "actions": []},
    "volatility_risk": {"findings": [], "actions": []},
    "sector_risk": {"findings": [], "actions": []},
}
```

Then in each section, append to both the flat list AND the per-component dict:

```python
# Section 1: Factor Beta Limit Analysis (line ~788)
if beta_ratio > beta_violation_ratio:
    finding = f"High {factor} exposure: β={actual_beta:.2f} vs {max_beta:.2f} limit"
    risk_factors.append(finding)
    per_component["factor_risk"]["findings"].append(finding)
    action = "Reduce market exposure..." if factor == "market" else f"Reduce {factor} factor exposure"
    recommendations.append(action)
    per_component["factor_risk"]["actions"].append(action)

# Section 2: Concentration (line ~847)
# ... append to per_component["concentration_risk"]

# Section 3: Volatility (line ~877)
# ... append to per_component["volatility_risk"]

# Section 4: Variance (line ~900) — maps to factor_risk
# ... append to per_component["factor_risk"]

# Section 5: Industry (line ~960) — maps to sector_risk
# ... append to per_component["sector_risk"]

# Section 6: Leverage (line ~992) — maps to concentration_risk
# ... append to per_component["concentration_risk"]
```

Industry proxy beta violations (section at line ~808) map to `sector_risk`.

Before returning, deduplicate each component's findings and actions (multiple sections can emit overlapping entries for the same component):

```python
for comp in per_component.values():
    comp["findings"] = list(dict.fromkeys(comp["findings"]))  # preserve order, remove dupes
    comp["actions"] = list(dict.fromkeys(comp["actions"]))
```

Include in the return dict:
```python
return {
    "risk_factors": risk_factors,
    "recommendations": recommendations,
    "compliance_violations": violation_details,
    "limit_violations": {...},
    "component_insights": per_component,  # NEW
}
```

The component keys (`factor_risk`, `concentration_risk`, `volatility_risk`, `sector_risk`) match the existing card IDs used in `RiskAnalysisModernContainer.tsx` (lines 447, 467, 488, 508).

### Step 2: Thread through RiskScoreResult API response

**File:** `core/result_objects/risk.py` — `RiskScoreResult.to_api_response()` (~line 2107)

Nest `component_insights` inside the existing `limits_analysis` response field (not top-level) to avoid needing to update `RiskScoreResponse` Pydantic model:

```python
# In the limits_analysis section of to_api_response():
"limits_analysis": {
    # ... existing fields ...
    "component_insights": self.limits_analysis.get("component_insights", {}),
}
```

This avoids updating `models/riskscoreresponse.py` and `models/response_models.py` since `limits_analysis` is already a dict with flexible schema.

### Step 3: Pass through in RiskScoreAdapter + Zod schema

**File:** `frontend/packages/connectors/src/schemas/api-schemas.ts` (~line 152)

Update `RiskScoreResponseSchema` (Zod) to passthrough unknown keys on `limits_analysis`, OR add `component_insights` explicitly. The simplest approach: if `limits_analysis` is already declared with `.passthrough()` or as `z.record()`, the field survives. If not, add it.

**File:** `frontend/packages/connectors/src/adapters/RiskScoreAdapter.ts`

Add `component_insights` to the raw input type and transformed output. Use nullish coalescing (`??`) not `||`:

```typescript
// In the raw input type (limitsData shape):
component_insights?: Record<string, { findings: string[]; actions: string[] }>;

// In the transform output — read from limitsData (where it's nested):
componentInsights: limitsData?.component_insights ?? {},
```

### Step 4: Thread to RiskAnalysis component

**File:** `frontend/packages/ui/src/components/dashboard/views/modern/RiskAnalysisModernContainer.tsx`

Update `RiskScoreDataLike` type to include `componentInsights`:

```typescript
componentInsights?: Record<string, { findings: string[]; actions: string[] }>;
```

When building each risk factor card, attach the matched insights directly by component ID — no keyword matching, direct key lookup:

```typescript
const componentInsights = resolvedRiskScoreData?.componentInsights ?? {};

{
  id: 'concentration_risk',
  name: 'Concentration Risk',
  // ... existing fields ...
  backendInsights: componentInsights['concentration_risk'] ?? null,
}
```

### Step 5: Render per-component insights in RiskAnalysis.tsx

**File:** `frontend/packages/ui/src/components/portfolio/RiskAnalysis.tsx`

**5a. Update RiskFactor interface:**
```typescript
backendInsights?: { findings: string[]; actions: string[] } | null;
```

**5b. Update expanded section** — show backend insights when available, fall back to existing content:

- **Findings present**: Show as bullet list (amber dots), truncated to 3 items max
- **Actions present**: Show as action list (emerald arrows), truncated to 3 items max
- **No findings**: Fall back to existing `risk.description`
- **No actions**: Fall back to existing `risk.mitigation`
- **Both fallbacks active**: This means the portfolio is within all limits for this component — the existing description/mitigation text serves as the "all clear" message
- **Timeline field**: Remove the separate "Implementation Timeline" row. The old `risk.timeline` was static placeholder text ("Actionable immediately", "Ongoing"). When backend insights exist, the actions are self-explanatory. When falling back, `risk.mitigation` already contains the guidance. The timeline label adds no value.

## What does NOT change

- Flat `risk_factors` and `recommendations` lists — still emitted for existing consumers (MCP agent, CLI)
- `buildRiskFactorDescription()` — kept as fallback for when no violations exist
- Risk Drivers tab — separate, already done
- Backend risk score calculation logic — unchanged

## Files to modify

1. `portfolio_risk_engine/portfolio_risk_score.py` — add `per_component` dict to `run_detailed_limits_analysis()`, deduplicate, populate alongside flat lists
2. `core/result_objects/risk.py` — nest `component_insights` inside `limits_analysis` in `RiskScoreResult.to_api_response()`
3. `frontend/packages/connectors/src/schemas/api-schemas.ts` — update Zod schema to allow `component_insights` through `limits_analysis`
4. `frontend/packages/connectors/src/adapters/RiskScoreAdapter.ts` — pass through `componentInsights` from `limitsData`
5. `frontend/packages/ui/src/components/dashboard/views/modern/RiskAnalysisModernContainer.tsx` — update type, attach `backendInsights` per card via direct key lookup
6. `frontend/packages/ui/src/components/portfolio/RiskAnalysis.tsx` — update interface, render per-component insights with fallback, remove timeline row

## Verification

1. Navigate to Risk → Risk Score → click Factor Risk card. If portfolio has factor violations, should show specific findings + recommendations from backend. If within limits, fall back to existing description.
2. Click Concentration Risk — concentration-specific findings if any.
3. Click Volatility Risk — volatility findings if any.
4. Click Sector Risk — industry/proxy violations if any.
5. When portfolio is well within all limits, all 4 cards gracefully fall back to existing text.
6. Backend: flat `risk_factors`/`recommendations` still work for MCP agent.
7. Backend tests + frontend typecheck pass.

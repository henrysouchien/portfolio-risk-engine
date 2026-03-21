# Unified Risk Drivers: Factor + Industry Ranking

## Context

The Risk Drivers tab currently only shows industry-level drivers and embeds a full hedge workflow. This mixes analysis with action. The hedge recommender is being decoupled — hedging moves to the Scenarios page (separate future task).

**This plan**: Make the Risk Drivers tab purely analytical. Show a unified ranking of all risk drivers (factor + industry) sorted by risk contribution. No hedge engine, no "Implement Strategy" buttons. Build the unified driver list in the backend so it's available to all consumers (frontend, MCP agent, API).

## Changes

### Step 1: Build unified driver list in `RiskAnalysisResult`

**File:** `core/result_objects/risk.py`

Add a `_build_risk_drivers()` method on `RiskAnalysisResult` (same pattern as `_build_industry_group_betas_table()`, `_build_factor_variance_percentage_table()`, etc.):

```python
FACTOR_DISPLAY_NAMES = {
    "market": "Market (Beta)",
    "interest_rate": "Interest Rate",
    "momentum": "Momentum",
    "value": "Value (HML)",
    "growth": "Growth",
    "size": "Size (SMB)",
    "quality": "Quality",
    "dividend": "Dividend Yield",
}

def _build_risk_drivers(self) -> List[Dict[str, Any]]:
    """
    Build a unified, sorted list of all risk drivers (factor + industry)
    ranked by contribution to portfolio variance.

    Returns list of:
        {"type": "factor"|"industry", "label": str, "raw_key": str,
         "percent_of_portfolio": float, "beta": float|None}


    Returns ALL drivers sorted by contribution — no threshold filtering.
    Consumers apply their own threshold (e.g., frontend uses 5%).
    """
    drivers = []

    # Factor drivers from factor_variance_percentage (already excludes industry/subindustry)
    factor_pct = self._build_factor_variance_percentage_table()  # reuse existing method
    pfb = self.portfolio_factor_betas if self.portfolio_factor_betas is not None else {}
    # pfb may be a pandas Series — convert to dict for safe .get() access
    if hasattr(pfb, 'to_dict'):
        pfb = pfb.to_dict()
    for factor_name, pct in factor_pct.items():
        try:
            num_pct = float(pct)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(num_pct) or num_pct <= 0:
            continue
        beta_val = None
        try:
            raw = pfb.get(factor_name) if hasattr(pfb, "get") else None
            beta_val = round(float(raw), 3) if raw is not None else None
        except Exception:
            pass
        drivers.append({
            "type": "factor",
            "label": FACTOR_DISPLAY_NAMES.get(factor_name, factor_name.replace("_", " ").title()),
            "raw_key": factor_name,
            "percent_of_portfolio": round(num_pct, 4),
            "beta": beta_val,
        })

    # Industry drivers from industry_variance_percentage
    industry_pct = self._build_industry_variance_percentage_table()  # reuse existing method
    industry_betas = self._build_industry_group_betas_table()  # reuse existing method
    # Build lookup: ETF ticker → {labeled_etf, beta}
    beta_lookup = {}
    for row in industry_betas:
        ticker = row.get("ticker")
        if ticker and ticker not in beta_lookup:
            beta_lookup[ticker] = {
                "label": row.get("labeled_etf", ticker),
                "beta": row.get("beta"),
            }
    for industry_key, pct in industry_pct.items():
        # industry_key may be an ETF ticker (REM) or a label (Technology) depending on proxy config
        try:
            num_pct = float(pct)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(num_pct) or num_pct <= 0:
            continue
        info = beta_lookup.get(industry_key)
        drivers.append({
            "type": "industry",
            "label": info["label"] if info else industry_key,
            "raw_key": industry_key,
            "percent_of_portfolio": round(num_pct, 4),
            "beta": info["beta"] if info else None,
        })

    # Sort by risk contribution descending
    drivers.sort(key=lambda d: d.get("percent_of_portfolio", 0), reverse=True)
    return drivers
```

Include in `to_api_response()` (~line 1133):
```python
"risk_drivers": self._build_risk_drivers(),
```

Include in `get_summary()` so the MCP agent can access it via `format="summary"`:
```python
"risk_drivers": self._build_risk_drivers()[:5],  # top 5 for summary brevity
```

Note: `RiskAnalysisResult` does NOT have `get_agent_snapshot()` — that belongs to `RiskScoreResult`. The agent path in `mcp_tools/risk.py:147` uses `result.get_summary()`.

**Also update `RISK_ANALYSIS_SECTIONS`** in `mcp_tools/risk.py` (~line 47) to include `"risk_drivers"` so it appears in `include=[...]` filtered responses.

### Step 2: Pass through in frontend adapter

**File:** `frontend/packages/connectors/src/adapters/RiskAnalysisAdapter.ts`

Add `risk_drivers` to the raw input type `RiskAnalysisData` (~line 126):
```typescript
risk_drivers?: Array<{
  type: 'factor' | 'industry';
  label: string;
  raw_key: string;
  percent_of_portfolio: number;
  beta: number | null;
}>;
```

Pass through in the transform output:
```typescript
riskDrivers: (payload.risk_drivers ?? []).map(d => ({
  type: d.type as 'factor' | 'industry',
  label: d.label,
  rawKey: d.raw_key,
  percentOfPortfolio: d.percent_of_portfolio,
  beta: d.beta,
})),
```

Also add `riskDrivers` to the adapter's **transformed output type** (if declared separately).

**File:** `frontend/packages/chassis/src/catalog/types.ts` — `RiskAnalysisSourceData`

Add:
```typescript
riskDrivers?: Array<{
  type: 'factor' | 'industry';
  label: string;
  rawKey: string;
  percentOfPortfolio: number;
  beta: number | null;
}>;
```

### Step 3: Simplify container — remove hedging, use backend drivers

**File:** `frontend/packages/ui/src/components/dashboard/views/modern/RiskAnalysisModernContainer.tsx`

Remove `useHedgingRecommendations()` call and all hedging data threading (`hedgingStrategies`, `hedgingMetadata`, `hedgingLoading`, `hedgingError`, `hedgingHasLoaded`).

The unified driver list now comes directly from the risk analysis response — no frontend construction needed. Apply the 5% threshold in the frontend (backend returns all drivers unfiltered):

```typescript
const THR = 0.05;
const significantDrivers = (data?.riskDrivers ?? []).filter(d => d.percentOfPortfolio >= THR);

// In transformedData:
riskDrivers: significantDrivers,
riskSummary: {
  annualVolatility: data?.risk_metrics?.annual_volatility ?? null,
  marketBeta: data?.portfolio_factor_betas?.market ?? null,
  driverCount: significantDrivers.length,
},
```

### Step 4: Simplify RiskAnalysis.tsx — remove hedging, render backend drivers

**File:** `frontend/packages/ui/src/components/portfolio/RiskAnalysis.tsx`

**4a. Remove all hedge-related code:**
- Delete `HedgeWorkflowDialog` import and `<HedgeWorkflowDialog>` JSX
- Delete `selectedHedge` state, `driverHedgeMap` useMemo
- Delete `hedgingStrategies` from props
- Remove `hedgingMetadata`, `hedgingLoading`, `hedgingError`, `hedgingHasLoaded` from props
- Remove `HedgeStrategy` import from `@risk/connectors`

**4b. Update `RiskDriver` type** — now matches the backend shape (camelCased by adapter):
```typescript
interface RiskDriver {
  type: 'industry' | 'factor';
  label: string;
  rawKey: string;             // factor name ("interest_rate") or ETF ticker ("REM")
  percentOfPortfolio: number;
  beta: number | null;
}

interface RiskSummary {
  annualVolatility: number | null;  // whole-percent (8.3 = 8.3%)
  marketBeta: number | null;
  driverCount: number;
}
```

Also update `RiskAnalysisProps.data` to include `riskDrivers?: RiskDriver[]` and `riskSummary?: RiskSummary`.

**4c. Simplify `getDriverSeverity()`** — unified for both types:
```typescript
const getDriverSeverity = (driver: RiskDriver): "High" | "Medium" | "Low" => {
  const pct = driver.percentOfPortfolio;
  if (!Number.isFinite(pct)) return "Low";
  if (pct >= 0.15) return "High";
  if (pct >= 0.08) return "Medium";
  return "Low";
};
```

**4d. Update `getDriverProgressValue()`** — unified:
```typescript
const getDriverProgressValue = (driver: RiskDriver): number => {
  if (!Number.isFinite(driver.percentOfPortfolio)) return 0;
  return Math.min(driver.percentOfPortfolio * 100, 100);
};
```

**4e. Update driver card rendering:**
- **Header**: Label + severity badge + type pill ("Factor" in blue/indigo, "Industry" in default)
- **Subtitle**: "X% of portfolio risk". Append "| Beta: Y.YY" if `beta` is non-null.
- **GradientProgress**: Same for both types
- **Click to expand**: Informational text only, using `driver.rawKey`:
  - Factor: "Your portfolio has significant sensitivity to {driver.label}. This exposure comes from positions with high {driver.rawKey} beta."
  - Industry: "Concentrated industry exposure tracked via {driver.rawKey} proxy."
  - NO hedge buttons, NO "Implement Strategy"

**4f. Use `${type}:${rawKey}` as stable React key and expansion state key:**
```typescript
const stableKey = (d: RiskDriver) => `${d.type}:${d.rawKey}`;
```

**4g. Simplify loading/error/empty states:**
- Shares risk analysis data lifecycle (same as Risk Score and Stress Tests tabs)
- Empty: If `riskDrivers.length === 0` → "No significant risk drivers detected."

**4h. Remove the in-tab CTA for hedging.** Page-level CTA in `FactorsContainer.tsx` already exists.

**4i. Keep summary card** using `data.riskSummary`:
- `annualVolatility` — display with `formatPercent(vol, { decimals: 1 })`. Already whole-percent. Do NOT × 100.
- `marketBeta` — display with `.toFixed(2)`.
- `driverCount` — displayed drivers only.
- Only render each metric when non-null.

### Step 5: Clean up ConnectedRiskAnalysis

**File:** `frontend/packages/ui/src/components/portfolio/ConnectedRiskAnalysis.tsx`

Remove `hedgingStrategies` from `RiskAnalysisViewData` and any hedging-related prop threading.

## What does NOT change

- `core/proxy_builder.py` — no proxy changes
- `portfolio_risk_engine/portfolio_risk.py` — no variance math changes
- `services/factor_intelligence_service.py` — no changes
- `HedgeWorkflowDialog.tsx` — file kept intact for future Scenarios page
- `useHedgingRecommendations` hook / `HedgingAdapter` — kept for future Scenarios page
- `FactorsContainer.tsx` — existing Scenarios CTA stays

## Files to modify

1. `core/result_objects/risk.py` — add `_build_risk_drivers()`, include in `to_api_response()` + `get_summary()`
1b. `mcp_tools/risk.py` — add `"risk_drivers"` to `RISK_ANALYSIS_SECTIONS`
2. `frontend/packages/connectors/src/adapters/RiskAnalysisAdapter.ts` — add `risk_drivers` to raw input type + pass through with camelCase
3. `frontend/packages/chassis/src/catalog/types.ts` — add `riskDrivers` to `RiskAnalysisSourceData`
4. `frontend/packages/ui/src/components/dashboard/views/modern/RiskAnalysisModernContainer.tsx` — remove hedging hook, pass through `riskDrivers` + `riskSummary`
5. `frontend/packages/ui/src/components/portfolio/RiskAnalysis.tsx` — remove hedge UI, render backend-provided driver cards
6. `frontend/packages/ui/src/components/portfolio/ConnectedRiskAnalysis.tsx` — remove hedging from view data

## Test updates

1. **Backend tests** — add test for `_build_risk_drivers()`: verify factor+industry merge, sort order (descending by pct), label resolution, beta passthrough, empty/null handling, all drivers returned (no threshold filtering — consumers filter)
2. **RiskAnalysisAdapter tests** — verify `riskDrivers` passed through, handles missing gracefully
3. **RiskAnalysis component tests** — remove hedge assertions, add factor driver tests, severity/progress for both types, empty state
4. **Agent snapshot tests** — verify `risk_drivers` included in snapshot

## Verification

1. Navigate to Factors → Risk Drivers. Unified list: Interest Rate (~67%) at top, then industry drivers, then smaller factors. Sorted by contribution.
2. Factor drivers show "Factor" pill, beta value, expand to informational text.
3. Industry drivers use `labeled_etf` from backend — not lossy reverse mapping.
4. No "Implement Strategy" buttons anywhere on the tab.
5. No hedging API call in network tab when viewing Risk Drivers.
6. MCP: `get_risk_analysis(format="summary")` includes `risk_drivers` top 5. `get_risk_analysis(include=["risk_drivers"])` returns full unfiltered list.
7. Page-level "Simulate hedge →" CTA at bottom of Factors page still works.
8. Risk Score and Stress Tests tabs unaffected.
9. Frontend typecheck + backend tests pass.

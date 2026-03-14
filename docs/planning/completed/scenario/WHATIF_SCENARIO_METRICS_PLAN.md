# B-001: What-If Scenario — Expose Scenario Metrics

**Status**: COMPLETE — commit `937bc9e2`, verified in browser

## Context

The What-If Scenario view (⌘4) runs real scenarios via `WhatIfResult.to_api_response()`, but the frontend `ScenarioMetrics` interface defines 7 metrics and only 2 are ever populated:

| Metric | Frontend field | Status |
|--------|---------------|--------|
| Volatility | `volatility` | WORKS (from `risk_checks` "Volatility" row) |
| Concentration | `concentration` | WORKS (from `risk_checks` "Max Weight" row) |
| Expected Return | `expectedReturn` | Always "N/A" — no backend field |
| Sharpe Ratio | `sharpeRatio` | Always "N/A" — no backend field |
| VaR 95% | `var95` | Always "N/A" — no backend field |
| VaR 99% | `var99` | Always "N/A" — no backend field |
| Max Drawdown | `maxDrawdown` | Always "N/A" — no backend field |

**Root cause**: `RiskAnalysisResult` doesn't compute VaR, Sharpe, expected return, or max drawdown. These would require additional calculations. The `risk_comparison` formatted table only has 5 metrics (Annual/Monthly Volatility, Concentration, Factor Var %, Idiosyncratic Var %).

Additionally, there's a scaling inconsistency: `deriveMetricsFromComparison()` applies `Math.abs(value) <= 1 ? value * 100 : value` — this works by coincidence for volatility (0.185 → 18.5) but would break for values like HHI (0.05 → 5.0 when it should stay 0.05).

## Approach

Add a `scenario_summary` dict to `to_api_response()` with raw numeric metrics for both current and scenario portfolios, sourced from already-computed `RiskAnalysisResult` fields. Then update the frontend to read from this new structured field instead of parsing formatted tables.

**Out of scope**: VaR 95/99, Sharpe, expected return, max drawdown — these require real computation work (historical VaR simulation, benchmark returns). Rather than fake them, we'll remove those cards from the UI and only show metrics we can actually compute. This keeps the UI honest.

## Changes

### 1. Backend: Add `scenario_summary` to `to_api_response()`

**File**: `core/result_objects/whatif.py` — `to_api_response()` method (line 645)

Add a new `scenario_summary` field after the existing `deltas` field:

```python
"scenario_summary": {
    "current": {
        "volatility": self.current_metrics.volatility_annual,         # float: raw decimal e.g. 0.185
        "volatility_monthly": self.current_metrics.volatility_monthly, # float: raw decimal
        "herfindahl": self.current_metrics.herfindahl,                 # float: HHI index e.g. 0.052
        "factor_variance_pct": self.current_metrics.variance_decomposition.get('factor_pct', 0) * 100,  # float: e.g. 72.3 (factor_pct is 0-1 ratio)
        "idiosyncratic_variance_pct": self.current_metrics.variance_decomposition.get('idiosyncratic_pct', 0) * 100,
    },
    "scenario": {
        "volatility": self.scenario_metrics.volatility_annual,
        "volatility_monthly": self.scenario_metrics.volatility_monthly,
        "herfindahl": self.scenario_metrics.herfindahl,
        "factor_variance_pct": self.scenario_metrics.variance_decomposition.get('factor_pct', 0) * 100,
        "idiosyncratic_variance_pct": self.scenario_metrics.variance_decomposition.get('idiosyncratic_pct', 0) * 100,
    }
},
```

**Unit note**: `factor_pct` and `idiosyncratic_pct` are stored as ratios [0,1] in `variance_decomposition` (from `portfolio_risk.py` line 347). Multiply by 100 here so the frontend receives true percentages (e.g. 72.3 not 0.723). `volatility_annual` is also a raw decimal (0.185 = 18.5%). `herfindahl` is an index (0.052), not a percentage.

This uses only fields already computed on `RiskAnalysisResult`. No new calculations.

### 2. Frontend: Pass `scenarioSummary` through the container

**File**: `frontend/packages/ui/src/components/dashboard/views/modern/ScenarioAnalysisContainer.tsx`

The container at line ~246 manually builds the `results` object that gets passed to `ScenarioAnalysis`. It must be updated to include `scenarioSummary`:

- Add `scenario_summary` (snake_case, matching backend JSON) to the `ScenarioResultsData` interface (line ~85)
- When building the results object at line ~252, map `scenario_summary` → `scenarioSummary` (camelCase prop for the React component)

### 3. Frontend: Read from `scenario_summary` in `deriveMetricsFromComparison()`

**File**: `frontend/packages/ui/src/components/portfolio/ScenarioAnalysis.tsx`

Update `deriveMetricsFromComparison()` (lines 536-591) to prefer `scenarioSummary` when available:

```typescript
const deriveMetricsFromComparison = (results: ScenarioRunResults): ScenarioMetrics => {
    const summary = results.scenarioSummary?.scenario;

    if (summary) {
        return {
            volatility: summary.volatility != null ? summary.volatility * 100 : "N/A",
            concentration: summary.herfindahl != null ? summary.herfindahl : "N/A",
            factorVariance: summary.factor_variance_pct != null ? summary.factor_variance_pct : "N/A",
        };
    }

    // Fallback: parse from formatted tables (old path, returns new 3-field shape)
    const findMetric = /* ... existing findRiskCheck + findComparison logic ... */;
    return {
        volatility: findMetric(["volatility"]),
        concentration: findMetric(["max weight", "max_weight", "herfindahl", "hhi", "concentration"]),
        factorVariance: findMetric(["factor var"]),
    };
};
```

**Important**: The fallback MUST return the new 3-field `ScenarioMetrics` shape (`volatility`, `concentration`, `factorVariance`), not the old 7-field shape. The old `expectedReturn`, `sharpeRatio`, `var95`, `var99`, `maxDrawdown` fields are removed from the interface entirely.

**Unit handling**: `volatility` arrives as raw decimal (0.185), multiply by 100 → 18.5. `factor_variance_pct` arrives already as percentage (72.3), use as-is. `herfindahl` is an index (0.052), use as-is.

### 4. Frontend: Update `ScenarioMetrics` interface

**File**: `frontend/packages/ui/src/components/portfolio/ScenarioAnalysis.tsx` (line 227)

Replace the current 7-field interface with the 3 metrics we can actually compute:

```typescript
interface ScenarioMetrics {
    volatility: number | "N/A"        // Annual volatility in % (e.g. 18.5)
    concentration: number | "N/A"     // HHI index (e.g. 0.052)
    factorVariance: number | "N/A"    // Factor variance % (e.g. 72.3)
}
```

Remove `expectedReturn`, `sharpeRatio`, `var95`, `var99`, `maxDrawdown` — they were always "N/A".

### 5. Frontend: Update metrics cards display

**File**: `frontend/packages/ui/src/components/portfolio/ScenarioAnalysis.tsx`

Update the scenario results rendering to show 3 real metrics instead of 7 mostly-N/A ones:

- **Volatility**: `{volatility.toFixed(1)}%` — e.g. "18.5%"
- **Concentration (HHI)**: `{concentration.toFixed(4)}` — e.g. "0.0520" (NOT formatted as percent — HHI is an index, not a percentage)
- **Factor Variance**: `{factorVariance.toFixed(1)}%` — e.g. "72.3%"

**HHI formatting**: Currently concentration is rendered with `formatPercent()` in multiple places (lines ~900, ~1070, ~1154). These must be changed to use a plain number formatter since HHI is an index value (0.052), not a percentage. Using `formatPercent()` on 0.052 would show "0.05%" which is wrong.

These replace the current metric cards that show expectedReturn, sharpeRatio, var95, var99 (all "N/A").

### 6. Frontend: Add `scenarioSummary` to types

**File**: `frontend/packages/ui/src/components/portfolio/ScenarioAnalysis.tsx` (or wherever `ScenarioRunResults` is defined)

Add `scenarioSummary` to the `ScenarioRunResults` interface:

```typescript
scenarioSummary?: {
    current: { volatility: number; volatility_monthly: number; herfindahl: number; factor_variance_pct: number; idiosyncratic_variance_pct: number };
    scenario: { volatility: number; volatility_monthly: number; herfindahl: number; factor_variance_pct: number; idiosyncratic_variance_pct: number };
}
```

## Files Modified

| File | Change |
|------|--------|
| `core/result_objects/whatif.py` | Add `scenario_summary` dict to `to_api_response()` (~15 lines) |
| `frontend/.../ScenarioAnalysisContainer.tsx` | Add `scenarioSummary` to `ScenarioResultsData` interface + pass through to component |
| `frontend/.../ScenarioAnalysis.tsx` | Update `ScenarioMetrics` interface, `deriveMetricsFromComparison()`, metric cards display, HHI formatting |

## Data Flow

```
WhatIfResult.to_api_response()
  → scenario_summary.current.volatility  = current_metrics.volatility_annual (0.185)
  → scenario_summary.scenario.volatility = scenario_metrics.volatility_annual (0.195)

Frontend:
  scenarioSummary.scenario.volatility * 100 → 19.5 → "19.5%"
  scenarioSummary.scenario.herfindahl       → 0.052 (displayed as-is)
  scenarioSummary.scenario.factor_variance_pct → 72.3 → "72.3%" (already multiplied by 100 in backend)
```

## What Changes From "N/A" → Real

| Field | Before | After |
|-------|--------|-------|
| Volatility | Worked (via table parsing with scaling hack) | Works (direct from `scenario_summary`, explicit `*100`) |
| Concentration | Worked (via "Max Weight" row) | Works (direct HHI from `scenario_summary`) |
| Factor Variance | Not shown | NEW — real from `variance_decomposition` |
| Expected Return | "N/A" | Removed from UI (no backend source) |
| Sharpe Ratio | "N/A" | Removed from UI (no backend source) |
| VaR 95% | "N/A" | Removed from UI (no backend source) |
| VaR 99% | "N/A" | Removed from UI (no backend source) |
| Max Drawdown | "N/A" | Removed from UI (no backend source) |

## Codex v1+v2 Findings (Addressed)

1. **`factor_pct` is a ratio [0,1], not percent**: `variance_decomposition['factor_pct']` from `portfolio_risk.py` line 347 is a ratio. Plan now multiplies by 100 in the backend `scenario_summary` so frontend receives true percentages.
2. **Container doesn't pass `scenario_summary`**: `ScenarioAnalysisContainer.tsx` manually builds results at line ~246 and would not include the new field. Added Step 2 to update the container and `ScenarioResultsData` interface.
3. **HHI displayed with `formatPercent()`**: Concentration cards use `formatPercent()` at lines ~900, ~1070, ~1154. HHI (0.052) would render as "0.05%" which is wrong. Plan now specifies plain number formatting for HHI.
4. **Fallback returns old 7-field shape**: The `deriveMetricsFromComparison()` fallback path (when `scenarioSummary` is absent) must return the new 3-field `ScenarioMetrics` shape, not the old 7-field shape. Plan now explicitly specifies this.
5. **Snake/camelCase convention**: `ScenarioResultsData` (raw API shape) uses `scenario_summary` (snake_case matching backend JSON). React component prop uses `scenarioSummary` (camelCase). Container maps between them.

## Verification

1. `cd frontend && pnpm typecheck` passes
2. `cd frontend && pnpm lint` passes
3. Run a what-if scenario in browser (⌘4) → metrics show real volatility, concentration, factor variance instead of "N/A"
4. `curl -X POST localhost:5001/api/what-if -d '...'` → response includes `scenario_summary` with raw numeric values

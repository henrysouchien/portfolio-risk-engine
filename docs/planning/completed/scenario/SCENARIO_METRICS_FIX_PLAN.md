# Scenario Analysis — Fix N/A Metrics (Frontend-Only)

**Status**: COMPLETE — implemented and verified in browser (commit `8a5d111a`)

## Context

Wave 3 Phase A wired ScenarioAnalysis to real backend data, but all 4 impact metrics (Expected Return, Volatility, Sharpe Ratio, VaR 95%) show "N/A" after running an analysis. Root causes:

1. **Data shape mismatch**: `comparison_analysis.risk_comparison` is a DataFrame-style dict (`{column: {index: value}}`), not an array of row objects. `deriveMetricsFromComparison()` calls `Array.isArray()` on it → returns `false` → `riskComparison = []` → all `findMetric()` calls return `"N/A"`.
2. **Hardcoded N/A**: `expectedReturn`, `sharpeRatio`, `var95`, `var99` are hardcoded to `"N/A"` — the backend's risk table doesn't include those metrics (tracked as B-001 in `BACKEND_EXTENSION_WORKING_DOC.md`).

### Actual Backend Data Shape (from `docs/schemas/api/api_what_if.json`)

`risk_analysis.risk_checks` — DataFrame dict with raw numeric values:
```json
{
  "Metric": {"0": "Volatility", "1": "Max Weight", "2": "Factor Var %", ...},
  "Actual": {"0": 0.2051893, "1": 0.25316214, "2": 0.62425747, ...},
  "Limit": {"0": 0.4, "1": 0.4, "2": 0.3, ...},
  "Pass": {"0": true, "1": true, "2": false, ...}
}
```

`comparison_analysis.risk_comparison` — DataFrame dict with raw numeric Old/New/Δ:
```json
{
  "Metric": {"0": "Volatility", "1": "Max Weight", ...},
  "Old": {"0": 0.19930529, ...},
  "New": {"0": 0.2051893, ...},
  "Δ": {"0": 0.00588401, ...}
}
```

Top-level `risk_comparison` — array of formatted strings (NOT used by container):
```json
[{"metric": "Volatility", "old": "19.9%", "new": "20.5%", "delta": "+0.6%", ...}]
```

## Changes

### 1. Add DataFrame → rows helper in ScenarioAnalysis.tsx

New utility to convert DataFrame-style dicts to row arrays:
```typescript
const dataFrameToRows = (df: unknown): Array<Record<string, unknown>> => {
  if (!df || typeof df !== "object" || Array.isArray(df)) return []
  const columns = Object.keys(df as Record<string, unknown>)
  if (columns.length === 0) return []
  const firstCol = (df as Record<string, Record<string, unknown>>)[columns[0]]
  if (!firstCol || typeof firstCol !== "object") return []
  const indices = Object.keys(firstCol)
  return indices.map((idx) => {
    const row: Record<string, unknown> = {}
    for (const col of columns) {
      row[col] = (df as Record<string, Record<string, unknown>>)[col]?.[idx]
    }
    return row
  })
}
```

### 2. Fix container DataFrame handling + thread `risk_checks`

**File**: `ScenarioAnalysisContainer.tsx`

**2a. Update `ScenarioResultsData` interface** (~line 92):
```typescript
risk_analysis?: {
  risk_passes?: boolean;
  risk_violations?: unknown;  // DataFrame dict OR empty array — use dataFrameToRows()
  risk_checks?: unknown;      // DataFrame dict OR empty array — use dataFrameToRows()
};
```

**2b. Fix `riskViolations` count** (~line 148). Currently `Array.isArray(risk_violations)` always returns false because backend sends DataFrame dict. Fix:
```typescript
const riskViolationRows = dataFrameToRows(scenarioResults.risk_analysis?.risk_violations);
const riskViolations = riskViolationRows.length;
```
(Import or inline `dataFrameToRows` — same helper as Step 1. Can extract to a shared util or duplicate in container.)

**2c. Fix `riskComparison` extraction** (~line 228). Currently `Array.isArray(comparison_analysis.risk_comparison)` drops the DataFrame dict to `[]`. Fix:
```typescript
const riskComparison = dataFrameToRows(scenarioResults.comparison_analysis?.risk_comparison);
const betaComparison = dataFrameToRows(scenarioResults.comparison_analysis?.beta_comparison);
```

**2d. Pass `riskChecks` through** in `results` object (~line 261):
```typescript
riskChecks: dataFrameToRows(scenarioResults.risk_analysis?.risk_checks)
```

**File**: `ScenarioAnalysis.tsx` — add to `ScenarioRunResults` interface (~line 237):
```typescript
riskChecks?: Array<Record<string, unknown>>  // Converted from DataFrame dict by container
```

Note: `dataFrameToRows()` gracefully handles both DataFrame dicts and empty arrays (returns `[]` for both non-object inputs and empty dicts).

### 3. Rewrite `deriveMetricsFromComparison()` — convert DataFrame dicts to rows

**File**: `ScenarioAnalysis.tsx` (line ~521)

Use `dataFrameToRows()` to convert both `riskChecks` and `riskComparison` from DataFrame dicts to row arrays, then search by metric name.

Priority chain: `riskChecks` rows (absolute `Actual` values) → `riskComparison` rows (before/after `New` values) → `"N/A"`.

Both sources are now pre-converted to row arrays by the container (Step 2c/2d), so `deriveMetricsFromComparison()` can iterate them directly without DataFrame conversion.

Values ≤ 1 are assumed to be decimals and multiplied by 100 for percentage display (existing logic).

### 4. Fix `toNumber()` — strip `%` for defensive parsing

**File**: `ScenarioAnalysis.tsx` (line ~445)

Add `value.replace(/%/g, "").replace(/\+/g, "")` before `Number()`. While the primary data sources now have raw numbers, the top-level `risk_comparison` still has formatted strings — this makes `toNumber()` robust for any source.

### 5. Replace unavailable metrics in UI with available ones

**File**: `ScenarioAnalysis.tsx`

**Results banner** (line ~828): Change from 4-col grid (Expected Return, Volatility, Sharpe, VaR) → 3-col grid:
- Volatility (absolute, from riskChecks)
- Concentration / Max Weight (from riskChecks)
- Risk Status (pass/fail with violation count, from riskMetrics)

**Sidebar impact panel** (line ~1005): Same swap — show Volatility, Concentration, Vol Delta, Risk Violations instead of the 4 unavailable metrics.

Note: `volatilityDelta` is a decimal (e.g., 0.005) — must multiply by 100 for `%` display. Access it from `latestScenarioResults.riskMetrics.volatilityDelta` (available on the component's `data?.scenarios?.[0]?.results`).

Keep `ScenarioMetrics` interface shape unchanged (backward compat) — just stop rendering the always-N/A fields.

## Files Modified

| File | Change |
|------|--------|
| `frontend/packages/ui/src/components/portfolio/ScenarioAnalysis.tsx` | Add dataFrameToRows helper, fix toNumber, add riskChecks to interface, rewrite deriveMetrics, update 2 UI panels |
| `frontend/packages/ui/src/components/dashboard/views/modern/ScenarioAnalysisContainer.tsx` | Add dataFrameToRows (or import), fix ScenarioResultsData interface types, fix riskViolations/betaViolations count, fix riskComparison/betaComparison extraction, pass riskChecks through |

## Data Flow (After Fix)

```
Backend risk_analysis.risk_checks (DataFrame dict):
  {"Metric": {"0": "Volatility"}, "Actual": {"0": 0.205}}
    ↓ (pass-through adapter)
Container: dataFrameToRows() → [{Metric: "Volatility", Actual: 0.205}]
Container: results.riskChecks = converted rows
    ↓ (props)
ScenarioAnalysis.deriveMetricsFromComparison()
    ↓ findRiskCheck(["volatility"]) → row.Actual = 0.205 → 20.5%
UI renders real value

Container also fixes:
  risk_violations (DataFrame dict → rows → .length for count)
  riskComparison (DataFrame dict → rows for fallback metric lookup)
```

## Verification

1. `cd frontend && pnpm typecheck` passes
2. `cd frontend && pnpm lint` passes
3. Start frontend (`cd frontend && pnpm dev`) + backend (`uvicorn app:app --port 5001 --reload`)
4. Navigate to Scenario Analysis (Analytics → Scenario Analysis, or ⌘8)
5. Click "Run Analysis" — verify impact metrics show real numbers (not N/A)
6. Verify results banner shows Volatility, Concentration, Risk Status with real values
7. Verify sidebar panel shows matching data

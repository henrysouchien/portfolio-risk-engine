# Monte Carlo Frontend Polish — Distribution Selector + Chart Fix

> **v5** — revised after Codex review rounds 1-4 (4 + 3 + 3 + 1 findings addressed).

## Context

The Monte Carlo backend now supports 3 distributions (Normal, Student-t, Bootstrap) and scenario conditioning (`ba241bf6`), but the frontend has no way to access these. Additionally, the fan chart Y-axis starts at $0 making the probability cone nearly invisible. This plan wires the new backend capabilities to the UI and fixes the chart.

**Three changes, ordered by impact:**
1. Fan chart Y-axis fix (trivial prop fix)
2. Distribution selector (new UI + full data flow threading)
3. VaR $0 context (not a bug — add label clarity when VaR is 0)

---

## Step 1: Fan Chart Y-axis Auto-Scale

**File**: `frontend/packages/ui/src/components/portfolio/scenarios/tools/MonteCarloTool.tsx`

**Line 289-292** — current YAxis:
```tsx
<YAxis
  {...axis}
  tickFormatter={(value) => `$${(Number(value) / 1000).toFixed(0)}k`}
/>
```

**Fix**: Add `domain` with padding:
```tsx
<YAxis
  {...axis}
  domain={[(min: number) => Math.floor(min * 0.98), (max: number) => Math.ceil(max * 1.02)]}
  tickFormatter={(value) => `$${(Number(value) / 1000).toFixed(0)}k`}
/>
```

This zooms the Y-axis to the actual data range with 2% padding, making the probability cone clearly visible instead of compressed into a thin band at the top. The chart is NOT stacked (no `stackId`), so `dataMin`/`dataMax` will work correctly.

---

## Step 2: Distribution Selector

Thread `distribution` and `df` params through the entire stack. The chain:
`MonteCarloTool` → `useMonteCarlo` → resolver → `PortfolioManager` → chassis `PortfolioCacheService` → `APIService` → REST endpoint → `ScenarioService` → engine.

### 2a. MonteCarloParams interface
**File**: `frontend/packages/connectors/src/features/monteCarlo/hooks/useMonteCarlo.ts`

```typescript
export interface MonteCarloParams {
  numSimulations?: number;
  timeHorizonMonths?: number;
  distribution?: 'normal' | 't' | 'bootstrap';  // NEW
  df?: number;                                     // NEW (Student-t only)
}
```

### 2b. SDK catalog types
**File**: `frontend/packages/chassis/src/catalog/types.ts` (line ~744)

Update `SDKSourceParamsMap['monte-carlo']` to include the new fields:
```typescript
'monte-carlo': {
  numSimulations?: number;
  timeHorizonMonths?: number;
  distribution?: 'normal' | 't' | 'bootstrap';
  df?: number;
  portfolioId?: string;
  _runId?: number;
}
```

**File**: `frontend/packages/chassis/src/catalog/descriptors.ts` (line ~569)

Update the monte-carlo catalog descriptor `params` to document the new fields.

### 2c. Resolver registry
**File**: `frontend/packages/connectors/src/resolver/registry.ts` (lines 825-842)

Thread distribution params to manager call:
```typescript
const result = await manager.analyzeMonteCarlo({
  numSimulations: params?.numSimulations,
  timeHorizonMonths: params?.timeHorizonMonths,
  distribution: params?.distribution,    // NEW
  df: params?.df,                        // NEW
});
```

### 2d. PortfolioManager
**File**: `frontend/packages/connectors/src/managers/PortfolioManager.ts`

Update `analyzeMonteCarlo()` method signature to accept and pass through `distribution` and `df`.

### 2e. PortfolioCacheService (chassis, not connectors)
**File**: `frontend/packages/chassis/src/services/PortfolioCacheService.ts` (line ~622)

**Note**: The `connectors` package re-exports this. The real implementation is in `chassis`. `getMonteCarlo()` calls `APIService.runMonteCarlo()` directly inside `getOrFetch`. Thread `distribution` and `df` through.

### 2f. APIService
**File**: `frontend/packages/chassis/src/services/APIService.ts` (lines 1258-1272)

Add `distribution` and `df` to the request body:
```typescript
body: JSON.stringify({
  portfolio_name: portfolioName,
  num_simulations: params?.numSimulations,
  time_horizon_months: params?.timeHorizonMonths,
  distribution: params?.distribution,    // NEW
  df: params?.df,                        // NEW
}),
```

### 2g. API response types
**File**: `frontend/packages/chassis/src/types/api.ts` (line ~93)

Update `MonteCarloApiResponse` to include the new response fields the engine returns:
```typescript
interface MonteCarloApiResponse {
  // ...existing fields...
  distribution?: string;
  requested_distribution?: string;
  distribution_fallback_reason?: string | null;
  distribution_params?: Record<string, unknown>;
  bootstrap_sample_size?: number | null;
  warnings?: string[];
}
```

### 2h. REST endpoint + request model
**File**: `models/response_models.py` (line 148)

Add fields to `MonteCarloRequest` with proper validation:
```python
class MonteCarloRequest(BaseModel):
    portfolio_name: str = "CURRENT_PORTFOLIO"
    num_simulations: Optional[int] = 1000
    time_horizon_months: Optional[int] = 12
    distribution: Optional[Literal["normal", "t", "bootstrap"]] = "normal"  # Literal, not str
    df: Optional[int] = 5

    @validator("df", always=True)
    def validate_df(cls, v, values):
        if v is None:
            v = 5  # coerce None to default — engine requires numeric df
        if values.get("distribution") == "t" and v < 3:
            raise ValueError("df must be >= 3 for Student-t distribution")
        return v
```

Update `MonteCarloResponse` to include the new engine output fields:
```python
class MonteCarloResponse(BaseModel):
    # ...existing fields...
    distribution: Optional[str] = None
    requested_distribution: Optional[str] = None
    distribution_fallback_reason: Optional[str] = None
    distribution_params: Optional[Dict[str, Any]] = None
    bootstrap_sample_size: Optional[int] = None
    warnings: Optional[List[str]] = None
```

**File**: `app.py` (lines 3080-3096)

**No manual validation needed at the route level** — the `Literal["normal", "t", "bootstrap"]` on `MonteCarloRequest` and the Pydantic `@validator("df")` handle REST input validation. Invalid values produce `RequestValidationError` → HTTP 422 (this app's global handler at line 1021). The validator coerces `df=None` to `5` so the engine always gets a numeric value.

Thread `distribution` and `df` through `_run_monte_carlo_workflow()` → `scenario_service.run_monte_carlo_simulation()` → engine.

**Engine-level hardening** (defense-in-depth): In `portfolio_risk_engine/monte_carlo.py`, at the top of `run_monte_carlo()`, coerce `df` to a safe default:
```python
df = int(df) if df is not None else 5
```
This protects all callers (REST, MCP tool, building block) from `df=None` reaching `float(df)`. This is a one-line fix at the engine level, not a behavioral change.

**File**: `services/scenario_service.py` (lines 498-514)

Add `distribution` and `df` params to `run_monte_carlo_simulation()`, pass to `run_monte_carlo()` engine call.

### 2i. UI — Distribution selector dropdown
**File**: `frontend/packages/ui/src/components/portfolio/scenarios/tools/MonteCarloTool.tsx`

New state:
```tsx
const [distribution, setDistribution] = useState<'normal' | 't' | 'bootstrap'>('normal')
const [df, setDf] = useState(5)
```

**Layout fix**: Keep the grid at 3 columns. Put Distribution + conditional df on a second row below Simulations and Horizon. This avoids the wrapping bug when df shows/hides. Use a `flex flex-wrap gap-4` wrapper for the second row:

```tsx
{/* Row 1: Simulations + Horizon + Run button */}
<div className="grid gap-4 lg:grid-cols-[minmax(220px,220px)_minmax(220px,220px)_auto]">
  {/* ...existing Simulations, Horizon, Run button... */}
</div>

{/* Row 2: Distribution + conditional df */}
<div className="flex flex-wrap gap-4">
  <div className="w-[220px] space-y-2">
    <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">Distribution</div>
    <Select value={distribution} onValueChange={...}>...</Select>
  </div>
  {distribution === 't' ? (
    <div className="w-[140px] space-y-2">
      <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">Degrees of Freedom</div>
      <Input type="number" min="3" max="30" value={df} ... />
    </div>
  ) : null}
</div>
```

Add imports for Select components (from `../../../ui/select`).

Update `handleRun` to include distribution:
```tsx
const handleRun = () => {
  const params = {
    numSimulations,
    timeHorizonMonths,
    distribution,
    ...(distribution === 't' ? { df } : {}),
  }
  pendingHistoryTracking.trackMonteCarlo(params)
  handleRunMonteCarlo(params)
}
```

### 2j. Distribution label on results (from response, not UI state)

After the metric cards, add a badge that reads from the **response** (not local UI state), so it's correct for reruns, fallbacks, and history replays:
```tsx
{monteCarlo.result?.distribution ? (
  <div className="text-xs text-muted-foreground">
    {monteCarlo.result.distribution === 't'
      ? `Student-t (df=${monteCarlo.result.distribution_params?.df ?? '?'})`
      : monteCarlo.result.distribution === 'bootstrap'
        ? 'Historical Bootstrap'
        : 'Normal (Gaussian)'}
    {monteCarlo.result.requested_distribution && monteCarlo.result.requested_distribution !== monteCarlo.result.distribution
      ? ` (requested ${monteCarlo.result.requested_distribution}, fell back)`
      : ''}
    {` · ${(monteCarlo.result.num_simulations ?? 0).toLocaleString()} simulations · ${monteCarlo.result.time_horizon_months} months`}
  </div>
) : null}
```

### 2k. Surface engine warnings in UI

The engine returns `warnings: string[]` for bootstrap fallback messages (e.g., "Bootstrap requested but fell back to normal: only 8 months of history available").

**Important**: The REST/frontend path does **not** generate interpretive flags (`small_bootstrap_sample`, `vol_regime_adjustment`, etc.). Those are generated only in the MCP/agent layer (`core/monte_carlo_flags.py` → `mcp_tools/monte_carlo.py`). The REST endpoint returns raw engine output. The `mergeScenarioResolverFlags()` in `useMonteCarlo.ts:57-59` merges resolver-level flags (e.g., stale data warnings from `useDataSource`) with `result?.flags`, but the REST response has no `flags` field.

For the frontend, we surface condition-specific information through two mechanisms:
1. **`warnings[]` banner** — bootstrap fallback messages rendered as amber banners (below)
2. **Response fields** — `bootstrap_sample_size`, `distribution`, `requested_distribution`, `distribution_fallback_reason` are in the response and used by the distribution badge (step 2j)

In `MonteCarloTool.tsx`, after the insight card and before the metric cards, render any warnings:
```tsx
{(monteCarlo.result?.warnings ?? []).length > 0 ? (
  <div className="space-y-2">
    {monteCarlo.result!.warnings!.map((warning, i) => (
      <div key={i} className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        {warning}
      </div>
    ))}
  </div>
) : null}
```

### 2l. Scenario history rerun + labels (code changes)
**File**: `frontend/packages/ui/src/components/portfolio/scenario/useScenarioHistory.ts`

The rerun path drops `distribution` and `df` because the rerun handler at line ~166 reconstructs a new params object with only `simulations` and `horizon`. The history params themselves are typed as `unknown`, so they carry through — but the rerun reconstruction drops them. Fix:
- Line ~166: Update the rerun handler to pass through all stored params (including distribution/df) when replaying a history entry

**File**: `frontend/packages/ui/src/components/portfolio/scenario/useScenarioHistory.ts` (line ~67)

History run labels currently ignore distribution/df, so two runs with different distributions look identical in the comparison UI. Update the MC run name builder to include distribution:
- Line ~67: Append distribution label to run name (e.g., "1,000 sims · 12mo · Student-t" instead of just "1,000 sims · 12mo")

This ensures the `ScenarioRunComparisonPanel` and `ScenariosLanding` display distinct labels for different distribution runs.

---

## Step 3: VaR $0 Context

**File**: `MonteCarloTool.tsx` (line 250-252)

When VaR is 0, show "No loss at 95%" in green instead of "$0":
```tsx
<div className="mt-2 text-lg font-semibold text-amber-700">
  {(terminal?.var_95 ?? 0) === 0 ? (
    <span className="text-emerald-700">No loss at 95%</span>
  ) : (
    formatCurrency(terminal?.var_95)
  )}
</div>
```

---

## Files Summary

**Frontend (9 files)**:
1. `frontend/packages/ui/src/components/portfolio/scenarios/tools/MonteCarloTool.tsx` — Y-axis fix, distribution selector UI, VaR label, distribution badge
2. `frontend/packages/connectors/src/features/monteCarlo/hooks/useMonteCarlo.ts` — extend MonteCarloParams
3. `frontend/packages/connectors/src/resolver/registry.ts` — thread distribution/df in resolver
4. `frontend/packages/connectors/src/managers/PortfolioManager.ts` — thread distribution/df
5. `frontend/packages/chassis/src/services/PortfolioCacheService.ts` — thread distribution/df (real impl, not re-export)
6. `frontend/packages/chassis/src/services/APIService.ts` — add distribution/df to request body
7. `frontend/packages/chassis/src/types/api.ts` — update MonteCarloApiResponse with new fields
8. `frontend/packages/chassis/src/catalog/types.ts` — update SDKSourceParamsMap['monte-carlo']
9. `frontend/packages/chassis/src/catalog/descriptors.ts` — update catalog descriptor params

**Backend (4 files)**:
10. `models/response_models.py` — Literal validation on MonteCarloRequest, new fields on MonteCarloResponse
11. `app.py` — thread distribution/df through workflow (validation via Pydantic → 422)
12. `services/scenario_service.py` — thread distribution/df to engine
13. `portfolio_risk_engine/monte_carlo.py` — one-line `df` coercion at top of `run_monte_carlo()` (defense-in-depth)

**Frontend — history (1 file)**:
14. `frontend/packages/ui/src/components/portfolio/scenario/useScenarioHistory.ts` — extend stored MC params type + rerun handler to include distribution/df

---

## Verification

1. **Fan chart**: Run MC → chart should zoom to data range, cone clearly visible
2. **Distribution selector**: Select "Student-t (fat tails)" → verify wider distribution, higher CVaR
3. **Bootstrap**: Select "Historical Bootstrap" → verify results render. If history < 12 months, verify amber warning banner from `warnings[]` and distribution badge shows fallback
4. **Bootstrap fallback**: If history too short, amber warning banner shows fallback message from `warnings[]` + badge shows "requested bootstrap, fell back" from response fields
5. **VaR $0**: When prob of loss is very low, VaR card shows "No loss at 95%" in green
6. **Distribution badge**: Reads from response (not UI state) — correct for reruns and fallbacks
7. **Bad input**: Invalid distribution or df<3 returns 422 (Pydantic validation), not 500
8. **Default unchanged**: Normal distribution selected by default, existing behavior preserved
9. **TypeScript**: `tsc --noEmit` passes with no new errors
10. **Frontend tests**: `npm run test` in frontend workspace

## Test Updates

**Backend tests to extend:**
- `tests/test_monte_carlo.py` — add test for `df=None` coercion to 5 (engine defense-in-depth)
- `tests/services/test_scenario_service.py` — add test that `run_monte_carlo_simulation()` accepts and threads `distribution`/`df` params

**Frontend tests to extend:**
- `frontend/packages/connectors/src/features/monteCarlo/__tests__/useMonteCarlo.test.tsx` — add test that `MonteCarloParams` with `distribution`/`df` flows through to resolver
- `frontend/packages/ui/src/components/portfolio/scenario/__tests__/useScenarioHistory.test.tsx` (or create if not exists) — add test that `rerunHistoryEntry()` for a Monte Carlo run preserves `distribution`/`df` params in the replayed params object

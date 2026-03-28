# Stress Test Shocks → Monte Carlo Scenario Conditioning

> **v6** — adds MonteCarloResponse.scenario_conditioning (FastAPI would strip field without it).

## Context

When a user runs a stress test and navigates to Monte Carlo via "Simulate recovery," the MC simulation currently uses a rough approximation (`vol_scale=1.5` + Student-t). This loses the specific scenario — which factors are shocked, by how much, and how each position is affected.

This plan wires stress factor shocks through stock_betas into per-ticker drift overrides for MC, enabling scenario-conditioned forward simulation.

---

## Key Design Decisions (addressing v1 findings)

### D1: Units — shocks as annualized drift (Finding 1)

Stress shocks (e.g., `market: -0.15`) × stock_betas produce a **one-shot scenario impact** per ticker. MC `drift_overrides` interpret values as **annual expected returns**. These are not the same unit.

**Decision**: Treat the shock-derived values as annualized drift assumptions. This is an explicit modeling choice: "simulate forward assuming this stress environment persists for the projection horizon." Document this in the function docstring. The alternative (scaling by horizon) is less intuitive for users who think "market drops 15%" means ongoing poor environment.

### D2: Composition lives inside the engine (Finding 2)

v1 claimed "no engine changes" — this was wrong. `_resolve_monthly_drift()` is private inside the engine, so additive mode (stress drift on top of base drift) can't be done from the wrapper without duplicating logic.

**Decision**: Add `scenario_shocks` and `scenario_stock_betas` as optional params to `_resolve_monthly_drift()`, and `scenario_shocks` to `run_monte_carlo()`. The engine composes them with the base drift internally. This is a small, clean extension to the existing drift pipeline — not a refactor. `stock_betas` is read from `risk_result.stock_betas` (set by `compute_factor_exposures()` in `portfolio_risk.py`).

### D3: Frontend uses executed scenario, not selection (Finding 3)

`selectedScenario?.shocks` can diverge from the last-run scenario if the user changes the dropdown after running.

**Decision**: Source shocks from the last-executed scenario. Track `lastRunScenarioShocks` in UI cache alongside existing `lastRunScenarioId`/`lastRunScenarioName`. The exit ramp reads from this tracked state, not the current dropdown.

---

## Step 1: Engine — Extend `_resolve_monthly_drift()` and `run_monte_carlo()`

### 1a. Add scenario_shocks to `_resolve_monthly_drift()`

**File**: `portfolio_risk_engine/monte_carlo.py` (line 238)

Add two optional params:

```python
def _resolve_monthly_drift(
    risk_result: RiskAnalysisResult,
    tickers: list[str],
    drift_model: str = "historical",
    expected_returns: Optional[Dict[str, float]] = None,
    risk_free_rate: Optional[float] = None,
    drift_overrides: Optional[Dict[str, float]] = None,
    scenario_shocks: Optional[Dict[str, float]] = None,       # NEW
    scenario_stock_betas: Optional[pd.DataFrame] = None,       # NEW
) -> tuple[np.ndarray, int]:
```

**Mutual exclusion** — add at top of function:

```python
    if scenario_shocks and drift_overrides:
        raise ValueError("scenario_shocks and drift_overrides are mutually exclusive")
```

After the existing drift_overrides block (after line 311), add scenario_shocks composition:

```python
    if isinstance(scenario_shocks, dict) and scenario_shocks and isinstance(scenario_stock_betas, pd.DataFrame):
        ticker_to_index = {
            str(t).strip().upper(): i for i, t in enumerate(tickers)
        }
        for ticker in tickers:
            ticker_upper = str(ticker).strip().upper()
            if ticker_upper not in scenario_stock_betas.index:
                continue
            idx = ticker_to_index.get(ticker_upper)
            if idx is None:
                continue
            row = scenario_stock_betas.loc[ticker_upper]
            stress_drift_annual = sum(
                _safe_float(row.get(factor), default=0.0) * _safe_float(shock, default=0.0)
                for factor, shock in scenario_shocks.items()
            )
            # Additive: convert current monthly base to annual, add stress drift, convert back
            base_monthly = monthly_drift[idx]
            base_annual = (1.0 + base_monthly) ** 12 - 1.0
            combined_annual = base_annual + stress_drift_annual
            monthly_drift[idx] = _annual_to_monthly_compound(combined_annual)
            applied_override_count += 1
```

This is always additive — stress drift layers on top of the base drift model (historical, industry_etf, etc.). The math: convert monthly base back to annual, add the annual stress component, re-compound to monthly. This preserves the compounding semantics.

### 1b. Thread through `run_monte_carlo()`

**File**: `portfolio_risk_engine/monte_carlo.py` (line 502)

Add to signature:

```python
def run_monte_carlo(
    ...
    drift_overrides: Optional[Dict[str, float]] = None,
    scenario_shocks: Optional[Dict[str, float]] = None,  # NEW
    seed: Optional[int] = None,
) -> Dict[str, Any]:
```

Add bootstrap guard (after line ~549):

```python
    if requested_distribution == "bootstrap" and scenario_shocks is not None:
        raise ValueError("scenario_shocks is not supported with bootstrap distribution")
```

Extract `stock_betas` from risk_result and thread to drift resolution (line ~577):

```python
    scenario_stock_betas = (
        getattr(risk_result, "stock_betas", None)
        if scenario_shocks else None
    )
    monthly_drift, drift_overrides_count = _resolve_monthly_drift(
        risk_result,
        tickers,
        drift_model=drift_model_value,
        expected_returns=expected_returns,
        risk_free_rate=risk_free_rate,
        drift_overrides=drift_overrides,
        scenario_shocks=scenario_shocks,
        scenario_stock_betas=scenario_stock_betas,
    )
```

Add `scenario_conditioning` metadata to result dict (where result is assembled):

```python
    if scenario_shocks:
        result["scenario_conditioning"] = {
            "shocks": scenario_shocks,
            "overrides_applied": drift_overrides_count,
            "drift_model_base": drift_model_value,
        }
```

---

## Step 2: MonteCarloResult — Add scenario_conditioning field

**File**: `core/result_objects/monte_carlo.py` (line 12)

Add field to `MonteCarloResult` dataclass:

```python
    scenario_conditioning: Optional[Dict[str, Any]] = None
```

Update `from_engine_output()`:

```python
    scenario_conditioning=data.get("scenario_conditioning"),
```

Update `get_agent_snapshot()` conditioning dict (line ~126):

```python
    "conditioning": {
        "weights_overridden": self.weights_overridden,
        "resolved_weights": self.resolved_weights,
        "vol_scale": self.vol_scale,
        "scenario_conditioning": self.scenario_conditioning,
    },
```

Update `get_summary()` and `to_api_response()` to include `scenario_conditioning`.

---

## Step 3: Thread through all backend surfaces

**Where what happens (F4 clarification)**:
- **Computation** (scenario→drift composition, metadata injection): Engine only (Step 1a–1b). No wrapper resolves `stock_betas`, computes overrides, or injects `scenario_conditioning` — the engine owns all of that.
- **Input validation** (mutual exclusion, bootstrap rejection): Duplicated at two layers for defense in depth. The MCP wrapper (3b) and agent wrapper (3d) validate early for clear error messages. The engine (Step 1b) validates again as the authoritative guard. The REST layer validates in the Pydantic model (3e) for 422 responses. The service layer (3a) and app layer (3f) are pure pass-through with no validation.
- **Threading**: All layers (3a–3f) add `scenario_shocks` to their signatures and forward it unchanged to the next layer.

### 3a. `services/scenario_service.py` (line 508)

Add `scenario_shocks` param to `run_monte_carlo_simulation()`:

```python
def run_monte_carlo_simulation(
    self,
    ...
    drift_overrides: Dict[str, float] | None = None,
    scenario_shocks: Dict[str, float] | None = None,  # NEW
    ...
) -> Dict[str, Any]:
```

Thread to `run_monte_carlo()` engine call (line ~526). Pass-through only — engine handles composition.

### 3b. `mcp_tools/monte_carlo.py` (line 58)

Add `scenario_shocks: Optional[dict] = None` param. Add validation:
- `scenario_shocks` + `drift_overrides` → `ValueError` (mutual exclusion)
- `scenario_shocks` + `bootstrap` → `ValueError`

Thread to `_run_monte_carlo_engine()` kwargs.

### 3c. `mcp_server.py` (line 1128)

Add `scenario_shocks: Optional[dict] = None` param. Thread to `_run_monte_carlo()`.

### 3d. `services/agent_building_blocks.py` (line 469)

Add `scenario_shocks: dict[str, float] | None = None` param. Add same validation as mcp_tools. Thread to `_run_monte_carlo_engine()`.

### 3e. `models/response_models.py` (line 164)

Add to `MonteCarloRequest`:

```python
    scenario_shocks: Optional[Dict[str, float]] = None

    @validator("scenario_shocks")
    def validate_scenario_shocks(cls, v, values):
        if v is not None and values.get("drift_overrides"):
            raise ValueError("scenario_shocks and drift_overrides are mutually exclusive")
        if v is not None and values.get("distribution") == "bootstrap":
            raise ValueError("scenario_shocks is not supported with bootstrap distribution")
        return v
```

### 3f. `models/response_models.py` (line 206) — MonteCarloResponse

Add `scenario_conditioning` to `MonteCarloResponse` so FastAPI doesn't strip it from API responses (the route uses `response_model=get_response_model(MonteCarloResponse)`):

```python
scenario_conditioning: Optional[Dict[str, Any]] = None
```

Without this, the engine computes and returns `scenario_conditioning`, but FastAPI's response_model filtering would silently drop it from the `/api/monte-carlo` response body.

### 3g. `app.py` (line 3223)

Add `scenario_shocks: Dict[str, float] | None = None` to `_run_monte_carlo_workflow()` signature. Extract from `monte_carlo_request.scenario_shocks` in endpoint (line ~3330). Thread through `run_in_threadpool()` and to `scenario_service.run_monte_carlo_simulation()`.

---

## Step 4: Frontend — StressTestTool exit ramp

**File**: `frontend/packages/ui/src/components/portfolio/scenarios/tools/StressTestTool.tsx`

### 4a. Track executed scenario shocks

Add `lastRunScenarioShocks` state alongside existing `lastRunScenarioId`/`lastRunScenarioName` (line 194):

```typescript
const [lastRunScenarioShocks, setLastRunScenarioShocks] = useState<Record<string, number> | null>(
  validUiCache?.lastRunScenarioShocks ?? null
)
```

In the effect that tracks executed scenario (lines 205-217), also capture shocks:

```typescript
useEffect(() => {
    if (!stressTest.data) return
    const pinnedScenarioId = stressTest.data.scenarioId ?? null
    const pinnedScenarioName = scenarioOptions.find(
      (s) => s.id === stressTest.data?.scenarioId
    )?.name ?? stressTest.data.scenarioName ?? "Stress scenario"
    const pinnedShocks = scenarioOptions.find(
      (s) => s.id === stressTest.data?.scenarioId
    )?.shocks ?? null

    setLastRunScenarioId(pinnedScenarioId)
    setLastRunScenarioName(pinnedScenarioName)
    setLastRunScenarioShocks(pinnedShocks)
}, [scenarioOptions, stressTest.data])
```

### 4b. Pass executed shocks in exit ramp

Update the exit ramp (line 658):

```typescript
onNavigate("monte-carlo", {
  ...(normalizedStressedValue !== undefined ? { portfolioValue: normalizedStressedValue } : {}),
  volScale: 1.5,
  distribution: "t",
  source: "stress-test",
  label: `Post-${pinnedScenarioName} recovery`,
  scenarioShocks: lastRunScenarioShocks ?? undefined,
})
```

### 4c. Persist in UI cache

Add `lastRunScenarioShocks` to the `StressTestUiCache` type and the cache write effect.

---

## Step 5: Frontend — MonteCarloTool context consumption

**File**: `frontend/packages/ui/src/components/portfolio/scenarios/tools/MonteCarloTool.tsx`

### 5a. Capture in initialContext (line 219)

Add `scenarioShocks` to context normalization:

```typescript
const incomingScenarioShocks = (
  context.scenarioShocks && typeof context.scenarioShocks === "object"
    ? context.scenarioShocks as Record<string, number>
    : undefined
)
return { ...existing fields, scenarioShocks: incomingScenarioShocks }
```

### 5b. Add context state

```typescript
const [contextScenarioShocks, setContextScenarioShocks] = useState<Record<string, number> | undefined>(
  initialContext.scenarioShocks
)
```

### 5c. Update hasActiveContext (line 375)

```typescript
const hasActiveContext = !!(contextWeights || contextPortfolioValue || contextVolScale || contextScenarioShocks)
```

### 5d. Update contextKey (line 408)

Add `ss: contextScenarioShocks` to the JSON.stringify object. Add `contextScenarioShocks` to useMemo deps. Include in the empty-check guard:

```typescript
if (!incomingWeights && !incomingPortfolioValue && !incomingVolScale && !incomingDistribution && !contextScenarioShocks) {
  return ""
}
```

### 5e. Update handleRun (line 450)

```typescript
...(contextScenarioShocks ? { scenarioShocks: contextScenarioShocks } : {}),
```

### 5f. Update context banner (line 613)

```typescript
{contextScenarioShocks ? " · Scenario-conditioned drift" : ""}
```

### 5g. Update clear-context (line 627)

Add `setContextScenarioShocks(undefined)` to the onClick handler.

### 5h. Bootstrap coercion

In the distribution initializer (line 244), extend the bootstrap guard:

```typescript
if (
  cachedDistribution === "bootstrap"
  && (incomingWeights || (incomingVolScale !== undefined && incomingVolScale !== 1) || incomingScenarioShocks)
) {
  return "normal"
}
```

---

## Step 6: Frontend threading

### 6a. `MonteCarloParams` type

**File**: `frontend/packages/connectors/src/features/monteCarlo/hooks/useMonteCarlo.ts` (line 7)

Add `scenarioShocks?: Record<string, number>` to `MonteCarloParams`.

### 6b. `PortfolioManager.ts` (line 674)

Add `scenarioShocks?: Record<string, number>` to `analyzeMonteCarlo` params type. Pass through to cache service.

### 6c. `PortfolioCacheService.ts` (line 688)

Add `scenarioShocks` to params type. Include in `generateMonteCarloHash()` for cache invalidation.

### 6d. `APIService.ts` (line 1345)

Add `scenarioShocks` to params type. Map to snake_case in request body:

```typescript
scenario_shocks: params?.scenarioShocks,
```

### 6e. `catalog/types.ts` (line 765) — F9

Add `scenarioShocks` to `SDKSourceParamsMap['monte-carlo']`:

```typescript
'monte-carlo': {
  ...existing fields...
  scenarioShocks?: Record<string, number>;   // NEW
};
```

This is what `registry.ts` reads for type-safe param access. Without this, `params?.scenarioShocks` would be a type error.

### 6f. `catalog/descriptors.ts` (line 584) — F9

Add `scenarioShocks` to `monteCarloDescriptor.params`:

```typescript
{
  name: 'scenarioShocks',
  type: 'object',
  required: false,
  description: 'Factor-level stress shocks to apply as scenario-conditioned drift overrides.',
},
```

### 6g. `registry.ts` (line 874)

Thread `scenarioShocks` from resolver params to `manager.analyzeMonteCarlo()`:

```typescript
scenarioShocks: params?.scenarioShocks,
```

### 6h. `types/api.ts` (line 95)

Add to `MonteCarloApiResponse`:

```typescript
scenario_conditioning?: {
  shocks: Record<string, number>;
  overrides_applied: number;
  drift_model_base: string;
} | null;
```

---

## Files Summary

**Backend (8 files)**:
1. `portfolio_risk_engine/monte_carlo.py` — engine: `scenario_shocks` in `_resolve_monthly_drift()` + `run_monte_carlo()`
2. `core/result_objects/monte_carlo.py` — `scenario_conditioning` field on MonteCarloResult
3. `mcp_tools/monte_carlo.py` — `scenario_shocks` param + validation
4. `mcp_server.py` — thread param
5. `services/agent_building_blocks.py` — `scenario_shocks` param + validation
6. `services/scenario_service.py` — thread param
7. `models/response_models.py` — `MonteCarloRequest` field + validators + `MonteCarloResponse.scenario_conditioning`
8. `app.py` — thread through workflow + endpoint

**Frontend (10 files)**:
9. `StressTestTool.tsx` — track `lastRunScenarioShocks`, pass in exit ramp
10. `MonteCarloTool.tsx` — full context wiring (capture, hasActiveContext, contextKey, handleRun, banner, clear, bootstrap coercion)
11. `useMonteCarlo.ts` — `MonteCarloParams.scenarioShocks`
12. `PortfolioManager.ts` — thread param
13. `PortfolioCacheService.ts` — thread param + cache hash
14. `APIService.ts` — thread to request body
15. `catalog/types.ts` — `SDKSourceParamsMap['monte-carlo'].scenarioShocks` (F9)
16. `catalog/descriptors.ts` — `monteCarloDescriptor.params` (F9)
17. `registry.ts` — thread from resolver
18. `types/api.ts` — response type

**Tests (9 files)**:
19. `tests/test_monte_carlo.py` — engine unit tests
20. `tests/mcp_tools/test_monte_carlo_mcp.py` — MCP tool tests
21. `tests/api/test_monte_carlo_api.py` — REST API tests
22. `tests/services/test_scenario_service.py` — service threading test
23. `tests/services/test_agent_building_blocks.py` — agent-building-blocks threading + validation
24. `tests/test_monte_carlo_result.py` — result object serialization
25. `frontend/packages/connectors/src/features/monteCarlo/__tests__/useMonteCarlo.test.tsx` — frontend hook test
26. `frontend/packages/ui/src/components/portfolio/scenarios/tools/__tests__/StressTestTool.test.tsx` — exit ramp shocks test
27. `frontend/packages/ui/src/components/portfolio/scenarios/tools/__tests__/MonteCarloTool.test.tsx` — context wiring tests

---

## Tests

### Engine (`tests/test_monte_carlo.py`)

1. `test_scenario_shocks_basic` — 2 tickers, 1 factor shock → verify per-ticker drift shifts by beta × shock
2. `test_scenario_shocks_multi_factor` — 2 tickers, 3 factor shocks → verify drift = Σ(beta × shock)
3. `test_scenario_shocks_additive_on_base_drift` — scenario_shocks with `drift_model="historical"` → stress drift adds to base, not replaces
4. `test_scenario_shocks_missing_factor` — shock factor not in stock_betas columns → 0 contribution (no error)
5. `test_scenario_shocks_missing_ticker` — ticker not in stock_betas index → skipped
6. `test_scenario_shocks_empty_dict_noop` — `scenario_shocks={}` → identical to no shocks
7. `test_scenario_shocks_nan_beta_ignored` — NaN beta for a factor → treated as 0
8. `test_scenario_shocks_bootstrap_rejected` — `scenario_shocks + bootstrap` → ValueError
9. `test_scenario_shocks_drift_overrides_mutual_exclusion` — both provided → ValueError
10. `test_scenario_shocks_none_unchanged` — no scenario_shocks → identical behavior to today
11. `test_scenario_conditioning_metadata_in_result` — verify `scenario_conditioning` dict in output

### MCP tool (`tests/mcp_tools/test_monte_carlo_mcp.py`)

12. `test_scenario_shocks_thread_to_engine` — verify shocks reach engine kwargs
13. `test_scenario_shocks_bootstrap_validation` — rejection at MCP layer
14. `test_scenario_shocks_mutual_exclusion_validation` — rejection at MCP layer

### REST API (`tests/api/test_monte_carlo_api.py`)

15. `test_scenario_shocks_request_threads_to_workflow` — verify shocks flow from MonteCarloRequest to workflow
16. `test_scenario_shocks_bootstrap_422` — rejection returns 422
17. `test_scenario_shocks_mutual_exclusion_422` — rejection returns 422
18. `test_scenario_conditioning_preserved_in_response` — verify `scenario_conditioning` survives FastAPI response_model filtering (MonteCarloResponse has the field)

### Service (`tests/services/test_scenario_service.py`)

19. `test_scenario_shocks_thread_to_engine` — verify shocks pass through service

### Agent building blocks (`tests/services/test_agent_building_blocks.py`)

20. `test_scenario_shocks_thread_to_engine` — verify shocks reach engine kwargs via agent surface
21. `test_scenario_shocks_bootstrap_validation` — rejection at agent-building-blocks layer
22. `test_scenario_shocks_mutual_exclusion_validation` — rejection at agent-building-blocks layer

### Result object (`tests/test_monte_carlo_result.py`)

23. `test_scenario_conditioning_in_agent_snapshot` — verify `scenario_conditioning` appears under `conditioning`
24. `test_scenario_conditioning_in_api_response` — verify serialization
25. `test_scenario_conditioning_none_when_no_shocks` — backward compat

### Frontend hook (`useMonteCarlo.test.tsx`)

26. `test_scenario_shocks_thread_to_manager` — verify scenarioShocks reaches analyzeMonteCarlo

### Frontend StressTestTool (`StressTestTool.test.tsx`)

27. `test_exit_ramp_passes_last_run_shocks` — after running stress test, "Simulate recovery" passes `lastRunScenarioShocks` (not current selection) to onNavigate
28. `test_exit_ramp_omits_shocks_when_no_run` — before any run, exit ramp navigates without scenarioShocks

### Frontend MonteCarloTool (`MonteCarloTool.test.tsx`)

29. `test_scenario_shocks_activates_context` — incoming scenarioShocks sets hasActiveContext=true, shows context banner with "Scenario-conditioned drift"
30. `test_scenario_shocks_in_context_key` — different scenarioShocks produce different contextKeys (cache invalidation)
31. `test_scenario_shocks_thread_to_run_params` — handleRun includes scenarioShocks in params passed to hook
32. `test_clear_context_removes_scenario_shocks` — clicking "Clear context" removes scenarioShocks from state
33. `test_bootstrap_coerced_when_scenario_shocks` — incoming scenarioShocks with cached bootstrap distribution → coerces to "normal"

---

## Verification

1. **Engine unit tests**: `python3 -m pytest tests/test_monte_carlo.py -x -v -k scenario`
2. **MCP tests**: `python3 -m pytest tests/mcp_tools/test_monte_carlo_mcp.py -x -v -k scenario`
3. **API tests**: `python3 -m pytest tests/api/test_monte_carlo_api.py -x -v -k scenario`
4. **Service tests**: `python3 -m pytest tests/services/test_scenario_service.py -x -v -k scenario`
5. **Agent building blocks tests**: `python3 -m pytest tests/services/test_agent_building_blocks.py -x -v -k scenario`
6. **Result tests**: `python3 -m pytest tests/test_monte_carlo_result.py -x -v -k scenario`
7. **All MC backend tests**: `python3 -m pytest tests/test_monte_carlo.py tests/mcp_tools/test_monte_carlo_mcp.py tests/api/test_monte_carlo_api.py tests/services/test_scenario_service.py tests/services/test_agent_building_blocks.py tests/test_monte_carlo_result.py -x -v`
8. **Frontend hook tests**: `cd frontend && npx vitest run --reporter=verbose packages/connectors/src/features/monteCarlo`
9. **Frontend component tests**: `cd frontend && npx vitest run --reporter=verbose packages/ui/src/components/portfolio/scenarios/tools/__tests__`
10. **Full backend regression**: `python3 -m pytest tests/ -x --timeout=60`
11. **Manual E2E**: Run stress test → click "Simulate recovery" → verify MC runs with scenario-conditioned drift, context banner shows "Scenario-conditioned drift", results differ from unconditioned run

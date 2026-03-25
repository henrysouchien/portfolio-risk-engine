# Monte Carlo Drift Model — Configurable Expected Returns

> **v3** — revised after Codex review rounds 1-2 (6 + 3 findings addressed).

## Context

The Monte Carlo engine currently uses a portfolio-wide monthly mean return (from `risk_result.portfolio_returns`) as drift fallback, or `risk_result.expected_returns` if populated (with annual/monthly heuristic). This is noisy and disconnected from the optimization pipeline, which uses `ReturnsService` to compute expected returns from industry ETF CAGRs. This plan makes the drift source configurable.

**Four drift models:**

| Model | Drift source | Use case |
|-------|-------------|----------|
| `"historical"` | Current behavior — portfolio-wide monthly mean fallback or `risk_result.expected_returns` with heuristic | Default, backward-compatible |
| `"industry_etf"` | Industry proxy ETF CAGR via `ReturnsService` (same as optimizer) | Stable, sector-driven, optimizer-consistent |
| `"risk_free"` | Treasury rate (uniform across all assets) | Conservative/risk-neutral baseline |
| `"zero"` | No drift | Pure risk analysis — "how wide is the cone?" |

Plus `drift_overrides: dict` for inline per-asset overrides (e.g., agent says "assume NVDA returns 15% annualized").

---

## Step 1: Engine Extension

**File**: `portfolio_risk_engine/monte_carlo.py`

### 1a. New parameters on `run_monte_carlo()`

Add after the existing `resolved_weights` param:
```python
drift_model: str = "historical",                       # NEW
expected_returns: Optional[Dict[str, float]] = None,   # NEW: pre-computed annual returns (for industry_etf)
risk_free_rate: Optional[float] = None,                # NEW: annual rate, pre-resolved by caller
drift_overrides: Optional[Dict[str, float]] = None,    # NEW: per-ticker annual return overrides
```

### 1b. Refactor `_resolve_monthly_drift()`

Current function (lines 188-222). Refactor to dispatch on `drift_model`:

```python
def _resolve_monthly_drift(
    risk_result: RiskAnalysisResult,
    tickers: list[str],
    drift_model: str = "historical",
    expected_returns: Optional[Dict[str, float]] = None,
    risk_free_rate: Optional[float] = None,
    drift_overrides: Optional[Dict[str, float]] = None,
) -> np.ndarray:
```

**Dispatch logic:**

- `"historical"` — **exact current behavior, no change**. Uses `risk_result.portfolio_returns.mean()` as portfolio-wide monthly mean fallback, or `risk_result.expected_returns` with the existing `_infer_annual_expected_returns()` heuristic. This preserves backward compatibility.

- `"industry_etf"` — use the `expected_returns` dict (pre-loaded by caller from `ReturnsService`). These are annual CAGR returns. Convert to monthly via compound formula: `monthly = (1 + annual) ** (1/12) - 1` (NOT simple `annual / 12`). **Skip `_infer_annual_expected_returns()` heuristic** — units are known to be annual. Tickers in the simulation universe but missing from `expected_returns` get 0 drift with a logged warning.

- `"risk_free"` — uniform drift = `(1 + risk_free_rate) ** (1/12) - 1` for all assets. `risk_free_rate` is **pre-resolved by the caller** (MCP tool, REST endpoint, or building block). The engine does NOT call `_get_risk_free_rate()` itself — that function requires `start_date`/`end_date` which the engine doesn't have. If `risk_free_rate` is None when `drift_model="risk_free"`, raise `ValueError("risk_free_rate required when drift_model='risk_free'")`.

- `"zero"` — return `np.zeros(len(tickers))`. No drift at all.

**After model dispatch**, apply `drift_overrides` on top (any model). For each ticker in `drift_overrides`:
- If the ticker is in the simulation universe (`tickers` list), replace its monthly drift with `(1 + override_value) ** (1/12) - 1` (override values are annual).
- If the ticker is NOT in the simulation universe, **silently ignore it** (the override is for a ticker not in the portfolio — this is not an error, just a no-op).

### 1c. Validation at engine level

```python
if drift_model not in ("historical", "industry_etf", "risk_free", "zero"):
    raise ValueError(f"Unknown drift_model: {drift_model}. Must be one of: historical, industry_etf, risk_free, zero")
if drift_model == "industry_etf" and not expected_returns:
    raise ValueError("expected_returns dict required when drift_model='industry_etf'")
if drift_model == "risk_free" and risk_free_rate is None:
    raise ValueError("risk_free_rate required when drift_model='risk_free'")
```

### 1d. Return dict metadata

Add to the output dict:
```python
"drift_model": drift_model,
"drift_overrides_count": <count of overrides actually applied>,  # only tickers in simulation universe
```

**Important**: `drift_overrides_count` must count only the overrides that were actually applied (i.e., tickers present in the `tickers` list), NOT the raw input dict length. Unknown tickers are silently ignored but should not inflate the count. Track the applied count inside `_resolve_monthly_drift()` and return it alongside the drift array (or compute it in `run_monte_carlo()` by intersecting override keys with tickers).

---

## Step 2: MCP Tool

**File**: `mcp_tools/monte_carlo.py`

### 2a. New parameters

```python
drift_model: Literal["historical", "industry_etf", "risk_free", "zero"] = "historical",
drift_overrides: Optional[dict] = None,  # {"AAPL": 0.15} = 15% annual
```

### 2b. Pre-resolve drift dependencies

Between portfolio load (line 95) and engine call (line 102), the MCP tool pre-resolves all drift dependencies so the engine receives clean inputs:

```python
expected_returns_for_engine = None
risk_free_rate_for_engine = None

if drift_model == "industry_etf":
    if not is_db_available():
        raise ValueError("industry_etf drift model requires database for expected returns")
    scope = getattr(portfolio_data, "_portfolio_scope", None)
    er_portfolio_name = getattr(scope, "expected_returns_portfolio_name", portfolio_name) if scope else portfolio_name
    pm = PortfolioManager(use_database=True, user_id=_user_id)
    returns_service = ReturnsService(portfolio_manager=pm)
    coverage_result = returns_service.ensure_returns_coverage(
        portfolio_name=er_portfolio_name,
        auto_generate=True,
    )
    if not coverage_result.get("success"):
        raise ValueError("Expected returns auto-generation failed")
    expected_returns_for_engine = returns_service.get_complete_returns(
        er_portfolio_name, ensure_coverage=False  # already ensured above
    )
    if not expected_returns_for_engine:
        raise ValueError("No expected returns available after auto-generation")

elif drift_model == "risk_free":
    from portfolio_risk_engine.portfolio_risk import _get_risk_free_rate
    risk_free_rate_for_engine = _get_risk_free_rate(
        risk_free_rate=None,
        start_date=portfolio_data.start_date,
        end_date=portfolio_data.end_date,
    )
```

### 2c. Imports

Add:
```python
from database import is_db_available
from inputs.portfolio_manager import PortfolioManager
from services.returns_service import ReturnsService
```

---

## Step 3: MonteCarloResult + Flags

### 3a. Result class
**File**: `core/result_objects/monte_carlo.py`

Add fields:
```python
drift_model: str = "historical"
drift_overrides_count: int = 0
```

Update `from_engine_output()` to extract `drift_model` and `drift_overrides_count` from the engine output dict (these are set in Step 1d). Include in `get_summary()`, `get_agent_snapshot()`, and `to_api_response()`.

Agent snapshot gains:
```python
"simulation": {
    ...existing...,
    "drift_model": str,
    "drift_overrides_count": int,
}
```

### 3b. Flags
**File**: `core/monte_carlo_flags.py`

Add flags:
| Condition | Type | Severity | Message |
|-----------|------|----------|---------|
| drift_model == "zero" | `zero_drift` | info | "Zero drift — simulation shows pure risk with no return expectation" |
| drift_model == "risk_free" | `risk_free_drift` | info | "Risk-free drift — all assets drift at the treasury rate" |
| drift_overrides_count > 0 | `drift_overrides` | info | "Custom drift overrides applied to {n} ticker(s)" |

---

## Step 4: REST Endpoint

**File**: `models/response_models.py`

Add to `MonteCarloRequest`:
```python
drift_model: Optional[Literal["historical", "industry_etf", "risk_free", "zero"]] = "historical"
drift_overrides: Optional[Dict[str, float]] = None
```

Add to `MonteCarloResponse`:
```python
drift_model: Optional[str] = None
drift_overrides_count: Optional[int] = None
```

**File**: `app.py`

`_run_monte_carlo_workflow()` (lines 3080-3096) has access to `user["user_id"]` and can instantiate DB-backed services. Add `drift_model` and `drift_overrides` params. For `industry_etf`, pre-load expected returns via `ReturnsService` (same pattern as MCP tool). For `risk_free`, pre-resolve via `_get_risk_free_rate()` using `portfolio_data.start_date`/`end_date`. Pass pre-resolved values to `scenario_service.run_monte_carlo_simulation()`.

**File**: `services/scenario_service.py`

Pure param-threading. Add `drift_model`, `expected_returns`, `risk_free_rate`, `drift_overrides` params to `run_monte_carlo_simulation()`. Pass directly to `run_monte_carlo()` engine call. No DB or service dependencies in the scenario service — caller pre-resolves everything.

---

## Step 5: Frontend

**File**: `MonteCarloTool.tsx`

Add a drift model dropdown on the same flex-wrap row as the distribution selector:

```tsx
const [driftModel, setDriftModel] = useState<'historical' | 'industry_etf' | 'risk_free' | 'zero'>('historical')
```

```tsx
<div className="w-[220px] space-y-2">
  <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">Drift Model</div>
  <Select value={driftModel} onValueChange={...}>
    <SelectContent>
      <SelectItem value="historical">Historical Average</SelectItem>
      <SelectItem value="industry_etf">Industry ETF</SelectItem>
      <SelectItem value="risk_free">Risk-Free Rate</SelectItem>
      <SelectItem value="zero">Zero Drift</SelectItem>
    </SelectContent>
  </Select>
</div>
```

Thread through the same stack as `distribution`:
- `useMonteCarlo.ts` — extend `MonteCarloParams` with `driftModel`
- `registry.ts` — thread to manager
- `PortfolioManager.ts` → `PortfolioCacheService.ts` → `APIService.ts` — thread
- `api.ts` — add `drift_model` and `drift_overrides_count` to `MonteCarloApiResponse`
- `catalog/types.ts` — add `driftModel` to `SDKSourceParamsMap['monte-carlo']`
- `catalog/descriptors.ts` — add drift_model param descriptor
- `useScenarioHistory.ts` — preserve in rerun + include in label

Update the distribution badge to include drift model (read from response):
```
"Interactive Brokers U2471778 · Normal (Gaussian) · Industry ETF drift · 1,000 simulations · 12 months"
```

---

## Step 6: Building Block + Agent Registry

**File**: `services/agent_building_blocks.py`

Add `drift_model: Literal[...]` and `drift_overrides: Optional[dict]` params. For `industry_etf`, the building block has access to `_user_id` (from `_load_portfolio_for_analysis`) and can instantiate `ReturnsService`. For `risk_free`, pre-resolve via `_get_risk_free_rate()` using `portfolio_data.start_date`/`end_date`.

**Important**: The building block currently discards `_user_id` from `_load_portfolio_for_analysis()`. Must retain it for `ReturnsService` instantiation.

---

## Step 7: Tests (~20 new)

### Engine tests (extend `tests/test_monte_carlo.py`, ~11):
- `test_drift_model_historical_default` — existing behavior unchanged (backward compat)
- `test_drift_model_industry_etf` — uses provided expected_returns dict, compound monthly conversion
- `test_drift_model_industry_etf_skips_infer_heuristic` — does not apply `_infer_annual_expected_returns`
- `test_drift_model_industry_etf_missing_tickers_get_zero` — tickers not in expected_returns → 0 drift
- `test_drift_model_risk_free` — uniform drift = `(1+rate)^(1/12) - 1` for all assets
- `test_drift_model_risk_free_no_rate_raises` — risk_free_rate=None → ValueError
- `test_drift_model_zero` — all drift = 0, median path is flat (seed + 5000 sims for stability)
- `test_drift_overrides_applied` — overrides replace specific tickers, unknown tickers ignored
- `test_drift_overrides_with_industry_etf` — overrides on top of ETF returns
- `test_drift_model_invalid_raises` — unknown model → ValueError
- `test_drift_metadata_in_output` — output has `drift_model`, `drift_overrides_count`

### Flag tests (extend `tests/test_monte_carlo_flags.py`, ~3):
- `test_zero_drift_flag`
- `test_risk_free_drift_flag`
- `test_drift_overrides_flag` — verifies count in message

### Result tests (extend `tests/test_monte_carlo_result.py`, ~2):
- `test_drift_model_in_snapshot` — snapshot includes drift_model + drift_overrides_count
- `test_drift_model_in_summary` — summary includes drift_model + drift_overrides_count

### MCP tool tests (extend `tests/mcp_tools/test_monte_carlo_mcp.py`, ~2):
- `test_drift_model_param_threads_to_engine` — drift_model passes through
- `test_drift_overrides_param_threads_to_engine` — drift_overrides passes through

### Building block tests (extend `tests/services/test_agent_building_blocks.py`, ~2):
- `test_drift_model_param_threads_to_engine` — drift_model passes through
- `test_building_block_retains_user_id` — user_id not discarded (needed for ReturnsService)

---

## Files Summary

**Engine (1 file)**:
1. `portfolio_risk_engine/monte_carlo.py` — drift_model param, refactor `_resolve_monthly_drift()`, compound conversion, validation, metadata

**MCP + agent (3 files)**:
2. `mcp_tools/monte_carlo.py` — drift_model/drift_overrides, pre-resolve industry_etf + risk_free
3. `mcp_server.py` — update `@mcp.tool()` wrapper to expose drift_model + drift_overrides params and forward to `_run_monte_carlo()`
4. `services/agent_building_blocks.py` — drift_model/drift_overrides, retain user_id, pre-resolve

**Result + flags (2 files)**:
4. `core/result_objects/monte_carlo.py` — drift_model/drift_overrides_count fields
5. `core/monte_carlo_flags.py` — 3 new drift flags

**Backend REST (3 files)**:
6. `models/response_models.py` — drift_model/drift_overrides on request, drift fields on response
7. `app.py` — pre-resolve + thread through workflow
8. `services/scenario_service.py` — pure param-threading to engine

**Frontend (9 files)**:
9. `MonteCarloTool.tsx` — drift model dropdown + badge update
10. `useMonteCarlo.ts` — extend MonteCarloParams
11. `registry.ts` — thread drift_model
12. `PortfolioManager.ts` — thread
13. `PortfolioCacheService.ts` — thread
14. `APIService.ts` — add to request body
15. `api.ts` — add to response type
16. `catalog/types.ts` + `descriptors.ts` — SDK catalog
17. `useScenarioHistory.ts` — preserve in rerun + label

---

## Verification

1. **Historical (default)**: Run MC → same results as before (backward compat)
2. **Industry ETF**: Select "Industry ETF" drift → verify auto-generates expected returns on first run, uses them for drift. Median path should differ from historical.
3. **Risk-free**: Select "Risk-Free Rate" → verify low uniform drift, nearly flat median
4. **Zero**: Select "Zero Drift" → verify flat median path, symmetric cone
5. **Drift overrides via MCP**: `run_monte_carlo(drift_model="industry_etf", drift_overrides={"NVDA": 0.30})` → verify NVDA drift differs
6. **Badge**: Shows drift model in the label (from response, not UI state)
7. **TypeScript**: `tsc --noEmit` clean
8. **Backend tests**: `pytest tests/test_monte_carlo.py tests/test_monte_carlo_flags.py tests/test_monte_carlo_result.py tests/mcp_tools/test_monte_carlo_mcp.py tests/services/test_agent_building_blocks.py -v`

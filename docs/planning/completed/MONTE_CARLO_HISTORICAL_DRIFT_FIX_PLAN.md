# Fix Historical Drift + Default to Industry ETF

> **v12** — revised after Codex review rounds 1-11.

## Context

Two issues with the current drift model implementation:

1. **`"historical"` drift is wrong** — uses portfolio-wide monthly mean (single number for all assets) or opportunistically reads `risk_result.expected_returns` (which is industry ETF data, not historical). Should use actual per-asset historical annual returns from `risk_result.asset_vol_summary["Annual Return"]`.

2. **Default should be `industry_etf`** — more stable, sector-driven, optimizer-consistent. But needs graceful fallback to `historical` when expected returns cannot be resolved. This covers: DB unavailable (caught by `is_db_available()` guard in the try block — note that MCP/building-block paths CAN reach this block even in DB outage because `CURRENT_PORTFOLIO` resolves to a virtual scope without DB), auto-generation failure, no returns available, and coverage validation errors. The REST path (`app.py`) also has this fallback for completeness, though it may fail earlier at portfolio load when the DB is fully down.

## Step 1: Fix `_resolve_historical_monthly_drift()`

**File**: `portfolio_risk_engine/monte_carlo.py` (lines 195-229)

**Current behavior** (wrong):
- Uses `risk_result.portfolio_returns.mean()` — a single portfolio-wide number
- Falls back to `risk_result.expected_returns` if populated — which is industry ETF data, not historical
- Applies `_infer_annual_expected_returns()` heuristic

**New behavior** (correct):
- Extract per-asset annual returns from `risk_result.asset_vol_summary["Annual Return"]`
- Convert each to monthly via compound formula: `(1 + annual) ** (1/12) - 1`
- For tickers missing from `asset_vol_summary`, fall back to portfolio-wide monthly mean (current fallback, but only for gaps)
- Do NOT read `risk_result.expected_returns` — that's the industry ETF path's job

```python
def _resolve_historical_monthly_drift(
    risk_result: RiskAnalysisResult,
    tickers: list[str],
) -> np.ndarray:
    # Fallback: portfolio-wide monthly mean
    portfolio_returns = getattr(risk_result, "portfolio_returns", None)
    portfolio_monthly_mean = 0.0
    if isinstance(portfolio_returns, pd.Series) and not portfolio_returns.empty:
        portfolio_monthly_mean = _safe_float(portfolio_returns.mean(), default=0.0)

    # Primary: per-asset annual returns from asset_vol_summary
    asset_vol = getattr(risk_result, "asset_vol_summary", None)
    if asset_vol is None or not isinstance(asset_vol, pd.DataFrame) or "Annual Return" not in asset_vol.columns:
        return np.full(len(tickers), portfolio_monthly_mean, dtype=float)

    # Clamp extreme annual returns to [-0.95, 2.0] (-95% to +200%).
    # asset_vol_summary fills NaN/inf to 0.0 upstream, so NaN fallback rarely fires.
    # But short-history tickers can produce extreme annualized values (e.g., 3 months
    # of +20%/month → +500% annualized). Clamping prevents unrealistic drift.
    _MAX_ANNUAL_RETURN = 2.0   # +200%
    _MIN_ANNUAL_RETURN = -0.95  # -95%

    monthly_drift = []
    for ticker in tickers:
        if ticker in asset_vol.index:
            annual_return = _safe_float(asset_vol.loc[ticker, "Annual Return"], default=np.nan)
            if np.isfinite(annual_return):
                clamped = max(_MIN_ANNUAL_RETURN, min(_MAX_ANNUAL_RETURN, annual_return))
                monthly_drift.append(_annual_to_monthly_compound(clamped))
            else:
                monthly_drift.append(portfolio_monthly_mean)
        else:
            monthly_drift.append(portfolio_monthly_mean)

    return np.asarray(monthly_drift, dtype=float)
```

## Step 2: Change Default to `industry_etf` with Fallback

### 2a. Engine default stays `"historical"`

The engine itself keeps `drift_model: str = "historical"` as default — it has no access to DB/ReturnsService. The default change happens at the **caller layer**.

### 2b. MCP tool + REST endpoint + frontend default to `"industry_etf"`

**Files to change default**:
- `mcp_tools/monte_carlo.py` — param default `"historical"` → `"industry_etf"`
- `mcp_server.py` — wrapper default `"historical"` → `"industry_etf"`
- `services/agent_building_blocks.py` — param default `"historical"` → `"industry_etf"`
- `services/scenario_service.py` — **keep default as `"historical"`** (thin pass-through, no DB access to resolve industry_etf). Callers (MCP tool, app.py, building block) pre-resolve and pass the concrete drift_model.
- `models/response_models.py` — `MonteCarloRequest.drift_model` default `"historical"` → `"industry_etf"`
- `app.py` — workflow default
- `frontend/.../MonteCarloTool.tsx` — `useState` default `"historical"` → `"industry_etf"`
- `frontend/.../useScenarioHistory.ts` — **NO CHANGE needed**. The file itself IS used by the live `ScenariosLanding` for history display/labels, but the `rerunHistoryEntry()` branch (line ~198) is only called from `RecentRunsPanel` which is part of the legacy stack (not rendered in live `ScenariosRouter`). The label path (line ~76) already coalesces missing driftModel to `"historical"`. No code change required.
- ~~`frontend/.../ScenarioAnalysis.tsx`~~ — **NO CHANGE (dead code)**. `ScenarioAnalysis` is imported by `ScenarioAnalysisContainer`, but `ScenarioAnalysisContainer` is never rendered — `ModernDashboardApp` uses `<ScenariosRouter />` (line 566) for the scenarios view. The legacy tab-based UI is unreachable.

### 2c. Graceful fallback in MCP tool

**File**: `mcp_tools/monte_carlo.py`

Wrap the `industry_etf` ReturnsService block in try/except. On failure (DB unavailable, auto-generation failed, no returns), fall back to `"historical"` with a warning in the response:

```python
_drift_fallback_warning = None

if drift_model == "industry_etf":
    try:
        if not is_db_available():
            raise RuntimeError("database unavailable")
        # ... existing ReturnsService logic ...
        if not expected_returns_for_engine:
            raise RuntimeError("no expected returns available")
    except Exception as exc:
        # The try block contains ONLY our industry_etf resolution logic:
        # is_db_available(), ensure_returns_coverage(), get_complete_returns(),
        # and our own RuntimeError guards. Every exception path in this block
        # indicates an availability/coverage failure (including ValidationError
        # from ReturnsService wrapping internal errors). There is no unrelated
        # business logic in scope, so catch-all is safe here and ensures the
        # fallback works for all ReturnsService failure modes.
        logger.warning("industry_etf drift unavailable (%s), falling back to historical", exc)
        _drift_fallback_warning = f"Industry ETF drift unavailable ({exc}), using Historical Average instead"
        drift_model = "historical"
        expected_returns_for_engine = None
```

Then after building `MonteCarloResult`, inject the warning:
```python
if _drift_fallback_warning:
    result.warnings = list(result.warnings or []) + [_drift_fallback_warning]
```

Add `import logging` and `logger = logging.getLogger(__name__)`.

This surfaces the fallback in the response `warnings[]` field, which the frontend already renders as amber banners.

The response will show `drift_model: "historical"` when fallback occurs, so the badge and flags correctly reflect what actually ran.

### 2d. Graceful fallback in REST endpoint

**File**: `app.py`

Same try/except pattern in `_run_monte_carlo_workflow()`. **Important**: the REST path returns the raw engine dict (not `MonteCarloResult`), so the fallback warning must be injected directly into the raw dict:
```python
result = scenario_service.run_monte_carlo_simulation(...)
if _drift_fallback_warning:
    existing_warnings = result.get("warnings") or []
    result["warnings"] = existing_warnings + [_drift_fallback_warning]
```

Also change the handler fallback line `monte_carlo_request.drift_model or "historical"` (line ~3187) to `monte_carlo_request.drift_model or "industry_etf"` — this is where the request's optional `None` gets resolved.

### 2e. Graceful fallback in building block

**File**: `services/agent_building_blocks.py`

Same try/except pattern. **Important**: the building block returns the raw engine payload nested under `"simulation"` key. The fallback warning must be injected into `result["simulation"]["warnings"]` before `make_json_safe()`:
```python
if _drift_fallback_warning:
    sim = result.get("simulation", {})
    existing_warnings = sim.get("warnings") or []
    sim["warnings"] = existing_warnings + [_drift_fallback_warning]
```

## Step 3: Tests

### Engine tests (extend `tests/test_monte_carlo.py`, ~4 new):
- `test_historical_drift_uses_per_asset_returns` — verify historical drift reads from `asset_vol_summary["Annual Return"]`, produces different drift per asset (not uniform)
- `test_historical_drift_compound_conversion` — verify `(1 + annual)^(1/12) - 1` applied, not `annual / 12`
- `test_historical_drift_missing_asset_uses_portfolio_mean` — ticker not in asset_vol_summary → falls back to portfolio-wide mean
- `test_historical_drift_no_asset_vol_summary_uses_portfolio_mean` — if asset_vol_summary is None/empty, falls back entirely
- `test_historical_drift_clamps_extreme_returns` — annual return of +500% clamped to +200%, -99% clamped to -95%

### MCP tool tests (extend `tests/mcp_tools/test_monte_carlo_mcp.py`, ~2 new):
- `test_industry_etf_fallback_to_historical` — mock DB unavailable, verify drift_model in response is "historical" and warnings[] contains fallback message
- `test_default_drift_model_is_industry_etf` — verify the function signature default is "industry_etf"

### Building block tests (extend `tests/services/test_agent_building_blocks.py`, ~2 new):
- `test_building_block_industry_etf_fallback` — mock DB unavailable, verify drift_model in response simulation is "historical" and warnings contains fallback message
- `test_building_block_default_drift_model_is_industry_etf` — verify function signature default is "industry_etf"

### MCP server wrapper test (in `tests/mcp_tools/test_monte_carlo_mcp.py`, ~1 new):
- `test_mcp_server_run_monte_carlo_default_drift_is_industry_etf` — verify the `@mcp.tool()` wrapper default for drift_model is "industry_etf"

### API-level test (in `tests/api/test_monte_carlo_api.py` or extend existing API tests, ~1 new):
- `test_rest_monte_carlo_default_drift_is_industry_etf` — call `/api/monte-carlo` without `drift_model` in the body, verify response `drift_model` is "industry_etf" (or "historical" on fallback with warning)
- `test_rest_monte_carlo_null_drift_model_resolves` — call `/api/monte-carlo` with `"drift_model": null`, verify the handler `or "industry_etf"` resolution produces the correct default (not staying null)

---

## Files Summary

**Engine (1 file)**:
1. `portfolio_risk_engine/monte_carlo.py` — rewrite `_resolve_historical_monthly_drift()` to use per-asset returns

**Default change (8 files)**:
2. `mcp_tools/monte_carlo.py` — default → `"industry_etf"`, add fallback + logger + warning injection
3. `mcp_server.py` — wrapper default → `"industry_etf"`
4. `services/agent_building_blocks.py` — default → `"industry_etf"`, add fallback + warning injection
5. `services/scenario_service.py` — keep default `"historical"` (no change, thin pass-through)
6. `models/response_models.py` — request default → `"industry_etf"`
7. `app.py` — workflow default → `"industry_etf"`, add fallback + warning injection
8. `frontend/.../MonteCarloTool.tsx` — useState default → `"industry_etf"`
~~9. `frontend/.../useScenarioHistory.ts`~~ — NO CHANGE (dead code path)

**Tests (4 files)**:
8. `tests/test_monte_carlo.py` — 5 new historical drift tests
9. `tests/mcp_tools/test_monte_carlo_mcp.py` — 3 new (fallback, default, mcp wrapper default)
10. `tests/services/test_agent_building_blocks.py` — 2 new building block fallback/default tests
11. `tests/api/test_monte_carlo_api.py` — 2 new REST tests (default omitted + explicit null)

---

## Verification

1. **Historical drift per-asset**: Run MC with `drift_model="historical"` → verify different assets get different drift (not uniform)
2. **Industry ETF default**: Run MC with no drift_model specified → verify badge shows "Industry ETF drift"
3. **Fallback**: Temporarily disable DB → run MC → verify it falls back to "Historical Average drift" without error
4. **Backward compat**: All existing tests pass (the engine default is still "historical", only caller defaults changed)
5. **Backend tests**: `python3 -m pytest tests/test_monte_carlo.py tests/mcp_tools/test_monte_carlo_mcp.py tests/services/test_agent_building_blocks.py tests/api/test_monte_carlo_api.py -x -v` (create API test file if needed)
6. **Frontend tests**: `cd frontend && npx vitest run --reporter=verbose`

# Rebalance Diagnostic + Target Setting — Backend Plan

## Context

The rebalance tool can generate trades from ticker-level weights, but is missing the "why rebalance" and "to what targets" layers. The key gap: **risk analysis data (concentration, factor exposures, compliance) is completely disconnected from asset allocation decisions.** The risk engine knows "Real Estate is your biggest risk contributor" but the allocation system only knows "you're 21pp overweight Real Estate vs your arbitrary target."

This plan builds the backend infrastructure to bridge that gap. Frontend will follow in a separate plan.

**Goal**: Enable a flow where risk analysis findings → inform asset allocation diagnosis → drive target recommendations → generate rebalance trades.

---

## Workstream 1: Asset-Class Risk Attribution

**Why**: Position-level risk data exists (`euler_variance_pct`, `stock_betas`) but nobody aggregates it to the asset-class level. This is the foundation for risk-informed allocation decisions.

### 1a. `get_asset_class_risk_contributions()` on `RiskAnalysisResult`

**File**: `core/result_objects/risk.py` — add after `get_top_risk_contributors()` (line ~294)

**Pattern**: Follow `get_top_risk_contributors()` which reads `self.euler_variance_pct` (pd.Series, 0-1 scale) and `self._get_weight()`.

```python
def get_asset_class_risk_contributions(self, top_n_contributors: int = 3) -> List[Dict[str, Any]]:
```

**Logic**:
1. Read `asset_classes` from `self.analysis_metadata` (same pattern as `_build_asset_allocation_breakdown()` line 1026)
2. Read `weights` from `self.analysis_metadata.get('weights', {})`
3. Iterate `self.euler_variance_pct.items()` — group by asset class, summing `risk_pct` and `weight_pct`
4. Compute `risk_weight_ratio = risk_pct / weight_pct` per class
5. For each class, identify top N contributing tickers (by euler variance within that class)
6. Sort by `risk_pct` descending

**Return shape**:
```python
[{
    "asset_class": "real_estate",
    "risk_pct": 42.1,           # % of total portfolio variance
    "weight_pct": 31.6,         # % of portfolio weight
    "risk_weight_ratio": 1.33,  # >1 means disproportionate risk
    "top_contributors": [{"ticker": "VNQ", "risk_pct": 22.5}, ...]
}]
```

**Edge cases**: Return `[]` if no `asset_classes` or empty `euler_variance_pct`. Unmapped tickers → "unknown".

### 1b. `get_asset_class_factor_betas()` on `RiskAnalysisResult`

**File**: `core/result_objects/risk.py` — add after 1a

```python
def get_asset_class_factor_betas(self) -> Dict[str, Dict[str, float]]:
```

**Logic**:
1. Read `asset_classes` and `weights` from `self.analysis_metadata`
2. `self.stock_betas` is a DataFrame (tickers × factors). Use `_safe_float()` pattern from line 290.
3. For each asset class, gather tickers and their position weights. Compute weight-averaged beta per factor: `sum(w_i * beta_i_f) / sum(w_i)` within class.
4. Discover factor columns from `self.stock_betas.columns` (don't hardcode)

**Return shape**:
```python
{
    "equity": {"market": 1.05, "interest_rate": 0.1, "growth": 0.3, ...},
    "real_estate": {"market": 0.8, "interest_rate": 1.4, ...},
}
```

**Edge cases**: Return `{}` if `stock_betas` is None/empty. Skip tickers not in `stock_betas.index`. Use `pd.notna()` for NaN filtering.

### 1c. Surface in API + Agent Response

**File**: `core/result_objects/risk.py` — in `to_api_response()` (before line 1293 cache set):
```python
"asset_class_risk": {
    "risk_contributions": self.get_asset_class_risk_contributions(),
    "factor_betas": self.get_asset_class_factor_betas(),
},
```

**File**: `mcp_tools/risk.py` — in `_build_agent_response()` (line ~150):
- Add `"asset_class_risk"` as a **top-level key** in the agent response dict alongside `snapshot` and `flags` — NOT in `RISK_ANALYSIS_SECTIONS` (which only affects `include=[...]` filtering on full responses)
- The agent snapshot comes from `result.get_summary()` which excludes attribution detail, so `asset_class_risk` must be a separate top-level bucket:
```python
return {
    "status": "success",
    "format": "agent",
    "snapshot": result.get_summary(),
    "asset_class_risk": {
        "risk_contributions": result.get_asset_class_risk_contributions(),
        "factor_betas": result.get_asset_class_factor_betas(),
    },
    "flags": flags,
}
```

**Note on weights source**: Both new methods should read weights from `self.analysis_metadata.get('weights', {})` with fallback to `self.portfolio_weights` — matching the exact order used in `_build_asset_allocation_breakdown()` (line ~1020 reads `analysis_metadata["weights"]` first, falls back to `self.portfolio_weights`).

---

## Workstream 2: Strategy Template Integration

**Why**: 6 strategy templates exist in YAML with `asset_class_allocation` but are disconnected from the target allocation system. Key mapping mismatch: templates use `stocks`/`bonds`/`alternatives`, system uses `equity`/`bond`/`real_estate`.

### 2a. Key Mapping Constant

**File**: `portfolio_risk_engine/constants.py` — add after `SECURITY_TYPE_TO_ASSET_CLASS` (~line 104)

```python
TEMPLATE_TO_SYSTEM_ASSET_CLASS = {
    'stocks': 'equity',
    'bonds': 'bond',
    'commodities': 'commodity',
    'cash': 'cash',
    'alternatives': 'real_estate',
}
```

### 2b. `get_allocation_presets()` Helper

**File**: `mcp_tools/allocation.py` — add after `get_target_allocation()`

```python
def get_allocation_presets(
    portfolio_name: str = "CURRENT_PORTFOLIO",
    user_email: str | None = None,
) -> dict:
```

**Logic**:
1. **Reuse the existing template loader** from `GET /api/strategies/templates` (app.py line ~2991) which already loads `strategy_templates.yaml`. Don't duplicate loading logic — either extract a shared `_load_strategy_templates()` helper or import from the existing surface.
2. For each template: extract `asset_class_allocation`, remap keys via `TEMPLATE_TO_SYSTEM_ASSET_CLASS`
3. **Collision validation**: after remapping, verify no duplicate asset class keys. If a template had both `alternatives` and `real_estate` mapped to the same system key, raise or warn.
4. Include saved targets as "current_targets" pseudo-preset if they exist
5. Return `{"status": "success", "presets": [...], "count": N}`

**Preset shape**:
```python
{
    "id": "balanced_core",
    "name": "Balanced Core",
    "description": "Global 60/40-style core...",
    "risk_level": 6,
    "allocations": {"equity": 45, "bond": 35, "commodity": 7, "cash": 5, "real_estate": 8}
}
```

**Note on existing template surface**: `GET /api/strategies/templates` already serves raw templates with ticker-level weights for the backtest/optimizer. The new `GET /api/allocations/presets` serves a different shape — asset-class-level allocations remapped to system keys. Both load from the same YAML but serve different consumers. Shared loader, different transformations.

### 2c. REST Endpoint

**File**: `app.py` — `GET /api/allocations/presets` near existing allocation endpoints (~line 2515)

Pattern follows existing `GET /api/allocations/target`. Calls `get_allocation_presets()` via `asyncio.to_thread()`. Rate limited.

### 2d. MCP Tool + Registration

**File**: `mcp_server.py` — register `get_allocation_presets` tool after existing allocation tools

**File**: `mcp_tools/__init__.py` — add `get_allocation_presets` to exports in `__all__` (line ~33)

**File**: `services/agent_registry.py` — add `get_allocation_presets` to the agent allowlist (line ~79) and function registry (line ~189) so agents can call it via code execution

---

## Workstream 3: Asset-Class Targets on Rebalance

**Why**: The rebalance MCP tool only accepts ticker-level weights. Agents and the frontend need to say "rebalance to 60% equity, 25% bonds" without manually decomposing. The frontend already does this (AssetAllocationContainer lines 296-329) — the backend version gives MCP/agent parity.

### 3a. New Parameter

**File**: `mcp_tools/rebalance.py` — add to `generate_rebalance_trades()`:

```python
asset_class_targets: Optional[Dict[str, float]] = None,
```

Validation: exactly one of `target_weights`, `weight_changes`, `asset_class_targets` must be provided. Change current XOR check (line ~89) to count-based: `sum(x is not None for x in [...]) != 1`.

### 3b. Decomposition Helper

**File**: `mcp_tools/rebalance.py` — new function:

```python
def _decompose_asset_class_targets(
    asset_class_targets: Dict[str, float],
    positions: List[Dict],  # enriched positions from PositionService
) -> Dict[str, float]:
```

**Logic**:
1. Group positions by asset class using the **enriched `position["asset_class"]` field**. The current rebalance path fetches raw positions via `PositionService` which does NOT have enriched `asset_class`. Two options:
   - **Option A (recommended)**: Within `_decompose_asset_class_targets()`, call `SecurityTypeService.get_asset_class(ticker)` for each ticker in positions. This service is already imported/available in the codebase and returns the canonical classification via FMP industry data.
   - **Option B**: Accept an explicit `asset_classes: Dict[str, str]` parameter (ticker → asset_class mapping) from the caller, populated from risk analysis `analysis_metadata["asset_classes"]` which the frontend/agent already has.

   Do NOT use raw `position["type"]` + `SECURITY_TYPE_TO_ASSET_CLASS` which coarsely maps ETFs/funds to "mixed".
2. **Cash handling**: Strip `cash` from `asset_class_targets` before decomposition. The rebalance engine (mcp_tools/rebalance.py lines 137-155) already drops cash from current weights and portfolio value. Asset-class targets must be non-cash only — if the caller includes `cash`, normalize the remaining targets to sum to 100% excluding cash, and document that cash is implicitly "whatever's left after trades." Reuse `_validate_and_normalize_allocations()` from `mcp_tools/allocation.py` for sum validation.
3. For each non-cash class in `asset_class_targets`: distribute class target proportionally across tickers within that class based on current values.
4. **Empty classes**: If a target specifies a class with no currently held positions (e.g., `commodity: 10` but no commodity holdings), skip it and add a warning. The user would need to add specific tickers via `target_weights` mode.
5. Classes not in targets → tickers get 0.0 weight (sell via `unmanaged` param behavior).
6. Return ticker-level `target_weights` dict in 0-1 scale.

**Integration**: When `asset_class_targets` provided, decompose first, then continue with existing `compute_rebalance_legs()` logic.

### 3c. REST + MCP Updates

- **`app.py`**: Make `target_weights` Optional on `RebalanceTradesRequest`, add `asset_class_targets: Optional[Dict[str, float]] = None`.
- **`mcp_server.py`**: Add `asset_class_targets` param to registered `generate_rebalance_trades` tool
- **`frontend/packages/chassis/src/services/APIService.ts`**:
  - Request type (line ~172): make `target_weights` optional, add `asset_class_targets?: Record<string, number>`, add `include_diagnostics?: boolean`
  - Request builder `generateRebalanceTrades()` (line ~1259): serialize `asset_class_targets` and `include_diagnostics` in the body alongside existing fields
  - Response type: add `diagnostic_flags?: Array<{type: string, severity: string, message: string, [key: string]: any}>`

---

## Workstream 4: Rebalance Diagnostic Flags

**Why**: The existing `generate_rebalance_flags()` only produces POST-rebalance flags (trade count, turnover). Need PRE-rebalance diagnostic flags that explain why the portfolio needs rebalancing using risk attribution data.

### 4a. New Flag Generator

**File**: `core/rebalance_flags.py` — new function alongside existing:

```python
def generate_rebalance_diagnostic_flags(
    risk_contributions: List[Dict[str, Any]],
    factor_betas: Dict[str, Dict[str, float]],
    compliance_summary: Dict[str, Any],
) -> List[Dict[str, Any]]:
```

**Flag types**:

| Flag | Severity | Trigger | Message example |
|------|----------|---------|-----------------|
| `risk_weight_imbalance` | warning (>1.5x) / info (>1.2x) | `risk_weight_ratio > 1.2` for any class | "Real Estate contributes 42% of risk at 32% weight (1.3x ratio)" |
| `factor_exposure_driver` | warning (systemic factors) / info | High beta × high weight dominates portfolio factor | "Real Estate drives 68% of interest rate exposure (beta 1.4)" |
| `compliance_driven_rebalance` | error | violation_count > 0 | "Rebalancing needed to resolve 2 compliance violations" |

Follows existing flag pattern: `{"type": str, "severity": str, "message": str, ...additional_fields}`. Use `_sort_flags()` for ordering.

### 4b. Integration — Agent AND REST Surfaces

**Agent format** (`mcp_tools/rebalance.py`): add optional `risk_snapshot: Optional[Dict[str, Any]] = None` param. When provided + `format="agent"`, generate diagnostic flags and merge with trade flags.

**MCP surface** (`mcp_server.py`): add `include_diagnostics: bool = False` to the registered `generate_rebalance_trades` tool. When `True`, the MCP wrapper fetches risk analysis internally by calling `get_risk_analysis(format="full")` (must use `format="full"` or `format="agent"` — the default `format="summary"` does NOT include `asset_class_risk`). Extract `asset_class_risk` contributions and compliance data from the result to build the `risk_snapshot`, then pass to the underlying tool. This means MCP agents don't need to pass raw risk data — they just set a flag.

**REST/full format** (`core/result_objects/rebalance.py`): The current `to_api_response()` (line ~77) has no `flags` field — diagnostic flags would be invisible to REST/frontend callers. Add an optional `diagnostic_flags` field to `RebalanceTradeResult`:
```python
diagnostic_flags: List[Dict[str, Any]] = field(default_factory=list)
```
Include in `to_api_response()`:
```python
"diagnostic_flags": self.diagnostic_flags,
```
**REST diagnostic wiring**: The `/api/allocations/rebalance` endpoint (app.py:2785) currently only forwards trade inputs. To populate diagnostic flags:
1. Add `include_diagnostics: bool = False` to `RebalanceTradesRequest`
2. When `include_diagnostics=True`, the endpoint attempts a **non-blocking cache peek** via `peek_analysis_result_snapshot()` (`services/portfolio/result_cache.py:247`). This returns a cached risk analysis result if one exists for the current user/portfolio, or `None` if not cached. **If not cached, skip diagnostics** — set `diagnostic_flags=[]` and proceed with trade generation. Do NOT block on a full risk computation.
3. From the cached risk result, call `get_asset_class_risk_contributions()` and `get_asset_class_factor_betas()` to build the `risk_snapshot`
4. Pass `risk_snapshot` to `generate_rebalance_trades()`
5. The MCP tool generates diagnostic flags and populates `RebalanceTradeResult.diagnostic_flags`
6. `to_api_response()` includes the populated flags

**Scoping**: The rebalance endpoint is scoped by `account_id` (optional), while risk analysis is scoped by `portfolio_name`. For diagnostics, use the default portfolio scope (matching the frontend's `useRiskAnalysis()` hook which uses the active portfolio). If `account_id` is provided and differs from the full portfolio scope, skip diagnostics — the cached risk result may not match the account subset.

When `include_diagnostics=False` (default), `diagnostic_flags` is an empty list — backward compatible.

**Alternative simpler approach (recommended for Phase 1)**: The frontend already calls `get_risk_analysis()` before rendering the rebalance view. The `asset_class_risk` data (from Workstream 1) is already in that response. The frontend can compute/render diagnostic insights **client-side** from the risk analysis data it already has, without needing the rebalance endpoint to duplicate the lookup. The `diagnostic_flags` field on `RebalanceTradeResult` would then only be populated for MCP/agent callers (who pass `include_diagnostics=True` and where the wrapper fetches risk data internally). This avoids coupling the REST rebalance endpoint to the risk cache in Phase 1.

This ensures diagnostic flags are visible to both agent and frontend consumers.

---

## Implementation Sequence

| Phase | Files | Work |
|-------|-------|------|
| 1 | `portfolio_risk_engine/constants.py` | `TEMPLATE_TO_SYSTEM_ASSET_CLASS` mapping |
| 1 | `core/result_objects/risk.py` | `get_asset_class_risk_contributions()`, `get_asset_class_factor_betas()` |
| 1 | `core/rebalance_flags.py` | `generate_rebalance_diagnostic_flags()` |
| 2 | `core/result_objects/risk.py` | Update `to_api_response()` with `asset_class_risk` |
| 2 | `mcp_tools/risk.py` | Update agent response + sections |
| 2 | `mcp_tools/allocation.py` | `get_allocation_presets()` |
| 3 | `mcp_tools/rebalance.py` | `asset_class_targets` param + decomposition + diagnostic flags |
| 3 | `app.py` | REST endpoint updates + `GET /api/allocations/presets` |
| 3 | `mcp_server.py` | Tool registration updates |
| 4 | `tests/` | All test files (see below) |

---

## Critical Files

| File | Changes |
|------|---------|
| `core/result_objects/risk.py` | 2 new methods + `to_api_response()` update |
| `core/result_objects/rebalance.py` | Add `diagnostic_flags` field + include in `to_api_response()` |
| `core/rebalance_flags.py` | 1 new function (diagnostic flags) |
| `portfolio_risk_engine/constants.py` | 1 new mapping constant |
| `mcp_tools/allocation.py` | 1 new function (presets) |
| `mcp_tools/__init__.py` | Export `get_allocation_presets` in `__all__` |
| `mcp_tools/rebalance.py` | New param + decomposition helper + diagnostic integration |
| `mcp_tools/risk.py` | Agent response top-level `asset_class_risk` key |
| `services/agent_registry.py` | Add `get_allocation_presets` to allowlist + function registry |
| `app.py` | 1 new endpoint + 1 updated request model |
| `mcp_server.py` | 2 tool registrations (presets + rebalance update) |
| `frontend/packages/chassis/src/services/APIService.ts` | Update `RebalanceTradesRequest` TS type (add `asset_class_targets`) |

## Existing Code to Reuse

- `get_top_risk_contributors()` in `core/result_objects/risk.py:274` — exact pattern for iterating `euler_variance_pct`
- `_safe_num()`, `_safe_float()`, `_get_weight()` — numeric safety helpers on `RiskAnalysisResult`
- `_build_asset_allocation_breakdown()` line 1020-1026 — pattern for reading `asset_classes` from metadata + `portfolio_weights` fallback
- `_validate_and_normalize_allocations()` in `mcp_tools/allocation.py:22` — reuse for asset-class target validation (sum check, key normalization)
- Enriched `position["asset_class"]` from `PortfolioService` (services/portfolio_service.py:1409) — canonical classification for decomposition
- `resolve_config_path()` in `config/` — YAML loading (for templates)
- Existing template loader at `GET /api/strategies/templates` (app.py:2991) — share YAML loading, don't duplicate
- `compute_rebalance_legs()` in `mcp_tools/trading_helpers.py` — existing trade generation (unchanged)
- `_sort_flags()` in flag files — standard severity sort

## Tests

| Test file | Cases |
|-----------|-------|
| `tests/core/test_asset_class_risk_attribution.py` | risk contributions aggregation, empty data, ratio calc, unknown tickers, factor betas averaging, NaN handling, API response inclusion |
| `tests/mcp_tools/test_allocation_presets.py` | template loading, key remapping, current targets inclusion, preset shape validation |
| `tests/mcp_tools/test_rebalance_asset_class_targets.py` | decomposition to ticker weights, mutual exclusivity validation, sum validation, trade generation end-to-end, agent format |
| `tests/core/test_rebalance_diagnostic_flags.py` | each flag type triggered/not triggered, severity ordering, empty inputs |

## Verification

1. **Unit tests**: `pytest tests/core/test_asset_class_risk_attribution.py tests/core/test_rebalance_diagnostic_flags.py tests/mcp_tools/test_allocation_presets.py tests/mcp_tools/test_rebalance_asset_class_targets.py -v`
2. **MCP live test**: Call `get_risk_analysis(format="agent")` → verify `asset_class_risk` in response. Call `get_allocation_presets()` → verify 6+ presets with system-format keys. Call `generate_rebalance_trades(asset_class_targets={"equity": 60, "bond": 25, "real_estate": 10, "cash": 5})` → verify trade legs generated.
3. **Regression**: `pytest tests/ -x --timeout=120` — full suite, no regressions

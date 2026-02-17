# Plan: Eliminate Temp-File Pattern from Core Analysis Functions

**Status:** REVISED — Unified plan (merged from TEMP_FILE_REFACTOR_PLAN + RISK_LIMITS_YAML_REFACTOR_PLAN). Codex findings addressed (12/12).

---

## Problem

Core analysis functions accept file paths, forcing callers to serialize in-memory objects (`PortfolioData`, `RiskLimitsData`) to temporary YAML files, pass the paths, then clean up. This creates unnecessary serialize-deserialize round trips with error-prone temp file lifecycle management (17 call sites across 7 files).

The reference pattern already exists: `core/portfolio_analysis.py::analyze_portfolio()` accepts `Union[str, PortfolioData]` and branches via `_config_from_portfolio_data()`. This plan extends that pattern to all remaining core functions and also eliminates risk-limits temp files using `RiskLimitsData.to_dict()`.

## Scope

### In scope
- `core/optimization.py` — `optimize_min_variance()`, `optimize_max_return()`
- `core/scenario_analysis.py` — `analyze_scenario()`
- `core/portfolio_analysis.py` — `analyze_portfolio()` (risk_yaml parameter only)
- `portfolio_optimizer.py` — `run_what_if_scenario()`, `run_max_return_portfolio()`
- `portfolio_risk_score.py` — `run_risk_score_analysis()`
- `run_risk.py` — all wrapper functions
- All service-layer callers (`services/portfolio_service.py`, `services/optimization_service.py`, `services/scenario_service.py`)
- All MCP callers (`mcp_tools/optimization.py`)
- Flask API endpoints (`app.py`)
- Shared config adapter extraction (`core/config_adapters.py`)
- `RiskLimitsData.to_dict()` safety normalization

### Out of scope (future work)
- `run_portfolio_performance()` portfolio temp file — requires `inject_all_proxies()` file mutation
- `app.py` lines 1346, 4333 — use `create_safe_temp_file()` for `inject_all_proxies()` which mutates files on disk

## Complete Temp-File Call Site Inventory

### Risk limits temp files (`create_risk_limits_temp_file`)

| # | File:Line | Caller | Phase |
|---|-----------|--------|-------|
| 1 | `services/portfolio_service.py:231` | `analyze_portfolio()` | 3 |
| 2 | `services/portfolio_service.py:487` | `analyze_risk_score()` | 3 |
| 3 | `services/optimization_service.py:201` | `optimize_minimum_variance()` | 3 |
| 4 | `services/optimization_service.py:305` | `optimize_maximum_return()` | 3 |
| 5 | `services/scenario_service.py:306` | `analyze_what_if()` | 3 |
| 6 | `mcp_tools/optimization.py:83` | `run_optimization()` | 3 |
| 7 | `app.py:1364` | `/api/direct/portfolio` | 3 |
| 8 | `app.py:3907` | `/api/direct/what-if` | 3 |

### Portfolio temp files (`create_temp_file`)

| # | File:Line | Caller | Phase |
|---|-----------|--------|-------|
| 9 | `services/optimization_service.py:198` | `optimize_minimum_variance()` | 3 |
| 10 | `services/optimization_service.py:302` | `optimize_maximum_return()` | 3 |
| 11 | `services/portfolio_service.py:501` | `analyze_risk_score()` | 3 |
| 12 | `services/portfolio_service.py:570` | `analyze_performance()` | deferred |
| 13 | `services/scenario_service.py:259,298,301` | `analyze_what_if()` | 3 |
| 14 | `services/scenario_service.py:399` | `analyze_delta_scenario()` | 3 |
| 15 | `services/scenario_service.py:475` | `analyze_scenario_file()` | 3 |
| 16 | `mcp_tools/optimization.py:82` | `run_optimization()` | 3 |
| 17 | `app.py:3889` | `/api/direct/what-if` | 3 |

### Scenario temp files (`create_safe_temp_file`) — retained

| # | File:Line | Caller | Note |
|---|-----------|--------|------|
| A | `services/scenario_service.py:231` | scenario content | Retained: ephemeral content, not serialized object |
| B | `app.py:1346` | portfolio + proxy injection | Retained: `inject_all_proxies()` mutates file on disk |
| C | `app.py:3899` | scenario content | Retained: ephemeral content |
| D | `app.py:4333` | portfolio + proxy injection | Retained: `inject_all_proxies()` mutates file on disk |

## Unified Input Resolution Strategy

All core functions will use a single resolver pattern that accepts multiple input types with explicit precedence. This avoids the conflicting `Union[str, RiskLimitsData]` vs `risk_config: Optional[Dict]` API styles from the original separate plans.

### Portfolio input resolver

```python
# core/config_adapters.py

def resolve_portfolio_config(
    portfolio: Union[str, PortfolioData],
) -> Tuple[Dict[str, Any], Optional[str]]:
    """Resolve portfolio input to (config_dict, filepath_or_none)."""
    if isinstance(portfolio, str):
        return load_portfolio_config(portfolio), portfolio
    else:
        return config_from_portfolio_data(portfolio), None
```

### Risk limits resolver

```python
# core/config_adapters.py

def resolve_risk_config(
    risk_limits: Union[str, RiskLimitsData, Dict[str, Any], None],
    *,
    default_path: str = "risk_limits.yaml",
) -> Dict[str, Any]:
    """Resolve risk limits input to a validated config dict.

    Accepts: Dict -> validate and return; RiskLimitsData -> .to_dict() with
    normalization; str -> load from file; None -> load from default_path.
    """
    if isinstance(risk_limits, dict):
        return normalize_risk_config(risk_limits)
    elif isinstance(risk_limits, RiskLimitsData):
        return normalize_risk_config(risk_limits.to_dict())
    elif isinstance(risk_limits, str):
        with open(risk_limits, "r") as f:
            return normalize_risk_config(yaml.safe_load(f))
    else:
        with open(default_path, "r") as f:
            return normalize_risk_config(yaml.safe_load(f))


def normalize_risk_config(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure all expected top-level keys exist with safe defaults.

    RiskLimitsData.to_dict() omits None fields — core functions access
    keys directly (risk_config["portfolio_limits"]) which would KeyError.
    """
    return {
        "portfolio_limits": raw.get("portfolio_limits", {}),
        "concentration_limits": raw.get("concentration_limits", {}),
        "variance_limits": raw.get("variance_limits", {}),
        "max_single_factor_loss": raw.get("max_single_factor_loss"),
        **{k: v for k, v in raw.items() if k not in (
            "portfolio_limits", "concentration_limits",
            "variance_limits", "max_single_factor_loss",
        )},
    }
```

### Precedence rules

Core functions accept a **single** `risk_limits` parameter (not separate `risk_yaml` + `risk_config`). Callers resolve which input to pass before calling:

```python
# Service layer pattern — RiskLimitsData takes precedence over default file:
effective_risk = risk_limits_data if (risk_limits_data and not risk_limits_data.is_empty()) else "risk_limits.yaml"
risk_config = resolve_risk_config(effective_risk)
```

For services like `optimization_service.py` that currently have both a `risk_file` path and a `risk_limits_data` object (lines 206, 309), the migration replaces both with just the in-memory object. The `risk_file` variable is eliminated — `RiskLimitsData` is the authoritative source when available, otherwise the default YAML path is used.

## Metadata Behavior for Object Inputs

When core functions receive `PortfolioData` instead of a filepath, `"portfolio_file"` in `analysis_metadata` is set to `None`. Result objects already handle None for this field. Display: `"Portfolio file: (in-memory)"`.

## Implementation

### Phase 1: Shared Infrastructure

**Step 1.1: Create `core/config_adapters.py`**

Extract `_config_from_portfolio_data()` from `core/portfolio_analysis.py` into new shared module. Rename to `config_from_portfolio_data()` (public). Add `resolve_portfolio_config()`, `resolve_risk_config()`, and `normalize_risk_config()`.

**Also update all existing importers of `_config_from_portfolio_data`:**
- `core/portfolio_analysis.py` — replace local definition with import from `config_adapters`
- `run_risk.py:50,347` — update import to use `core.config_adapters.config_from_portfolio_data`

Search for any other importers with `grep -r "_config_from_portfolio_data"` during implementation.

**Step 1.2: Add `normalize_risk_config()` validation**

`RiskLimitsData.to_dict()` at `core/data_objects.py:1160` omits keys when fields are None. Core functions crash with `KeyError`. The normalizer fills missing keys with empty dicts.

### Phase 2: Core Function Signatures (Backward-Compatible)

**Step 2.1: `core/portfolio_analysis.py:analyze_portfolio()`**

Change `risk_yaml` to `Union[str, RiskLimitsData, Dict[str, Any], None]`. Use resolvers.

**Step 2.2: `core/optimization.py:optimize_min_variance()`**

Accept `Union` types for both `portfolio` and `risk_limits`. Use resolvers.

**Step 2.3: `core/optimization.py:optimize_max_return()`**

Same pattern.

**Step 2.4: `core/scenario_analysis.py:analyze_scenario()`**

Accept `Union` types. `risk_limits` defaults to `None` (resolver falls back to `"risk_limits.yaml"`).

**Step 2.5: `portfolio_risk_score.py:run_risk_score_analysis()`**

Accept `Union` types for both parameters. Use resolvers.

**Step 2.6: `portfolio_optimizer.py:run_what_if_scenario()`**

Remove `portfolio_yaml_path` and `risk_yaml_path` parameters. Pass config values directly to `calc_max_factor_betas()`:
```python
max_betas, max_betas_by_proxy, historical_analysis = calc_max_factor_betas(
    lookback_years=lookback_years, echo=False,
    stock_factor_proxies=proxies, fmp_ticker_map=fmp_ticker_map,
    max_single_factor_loss=risk_config.get("max_single_factor_loss"),
)
```

**Must ship in same commit as Step 2.4** — `core/scenario_analysis.py` caller must be updated simultaneously.

**Step 2.7: `portfolio_optimizer.py:run_max_return_portfolio()`**

Fix hardcoded `"portfolio.yaml"` / `"risk_limits.yaml"` bug at lines 1312-1316. Pass `stock_factor_proxies`, `fmp_ticker_map`, `max_single_factor_loss` directly. Add `risk_config` parameter.

**Step 2.8: `run_risk.py` wrapper signatures**

Update all 5 wrappers (`run_portfolio`, `run_min_variance`, `run_max_return`, `run_what_if`, `run_risk_score`) to accept and forward `Union` types.

### Phase 3: Service/MCP/API Callers — Remove Temp Files

**Step 3.1: `services/portfolio_service.py:analyze_portfolio()`** — pass `risk_limits_data` directly

**Step 3.2: `services/portfolio_service.py:analyze_risk_score()`** — pass both `portfolio_data` and `risk_limits_data` directly (eliminates sites #2, #11)

**Step 3.3: `services/optimization_service.py`** — both optimize methods pass objects directly (eliminates sites #3, #4, #9, #10)

**Step 3.4: `services/scenario_service.py`** — all 3 scenario methods pass objects directly. `create_safe_temp_file()` for scenario YAML content is **retained**. (eliminates sites #5, #13, #14, #15)

**Step 3.5: `mcp_tools/optimization.py:run_optimization()`** — pass objects directly (eliminates sites #6, #16)

**Step 3.6: `app.py` API endpoints** — eliminate risk limits temp files at lines 1364, 3907. Eliminate portfolio temp file at line 3889. Lines 1346, 4333 **retained** (proxy injection).

### Phase 4: Cleanup

**Step 4.1:** Remove `create_risk_limits_temp_file()` from `PortfolioData`. Keep `create_temp_file()` (still needed for `analyze_performance` + proxy injection) and `create_safe_temp_file()` (scenario YAML + proxy injection).

**Step 4.2:** Update metadata formatting — `"(in-memory)"` when `portfolio_file` is None.

**Step 4.3:** Update `core/portfolio_analysis.py` import to use `core/config_adapters`.

## Sequencing

### PR 1: Infrastructure + Core Signatures (Phase 1 + Phase 2)
Backward-compatible. String paths still work.

Order:
1. Step 1.1 — create `core/config_adapters.py` (includes migrating all `_config_from_portfolio_data` importers)
2. Step 1.2 — `normalize_risk_config()` safety layer
3. Steps 2.1-2.3, 2.5 — core function signatures (portfolio_analysis, optimization, risk_score)
4. Steps 2.4 + 2.6 — `analyze_scenario()` + `run_what_if_scenario()` shipped together (signature dependency)
5. Step 2.7 — `run_max_return_portfolio()` hardcoded paths fix
6. Step 2.8 — `run_risk.py` wrappers

### PR 2: Service/MCP/API Migration (Phase 3)
Depends on PR 1. Each step independently testable.

### PR 3: Cleanup (Phase 4)
Depends on PR 2.

## Testing

- All existing tests pass (string paths preserved)
- New tests for each core function with `PortfolioData` input
- New tests for each core function with `RiskLimitsData` input
- Test `normalize_risk_config()` fills missing keys
- Test `resolve_risk_config()` with all four input types (str, RiskLimitsData, dict, None)
- Test `resolve_portfolio_config()` with both input types
- Verify `run_max_return_portfolio` hardcoded path bug fix
- Test metadata `portfolio_file` is None for PortfolioData inputs
- Test `PortfolioService.analyze_risk_score()` works without temp files

## Codex Finding Cross-Reference

| # | Finding | Resolution | Step |
|---|---------|-----------|------|
| 1 | Missing callers: `optimization_service.py`, `app.py` | Added to inventory | All |
| 2 | Conflicting API styles | Unified resolver: `str \| RiskLimitsData \| Dict \| None` | 1.1 |
| 3 | `run_what_if_scenario` signature affects `scenario_analysis.py` | Ship 2.4 + 2.6 together | 2.4, 2.6 |
| 4 | `_config_from_portfolio_data` private helper cross-module | Move to `core/config_adapters.py` | 1.1 |
| 5 | `run_risk.py` wrapper signatures not updated | All 5 wrappers updated | 2.8 |
| 6 | Cleanup under-scoped — `create_safe_temp_file` still needed | Retained with documented use cases | 4.1 |
| 7 | Metadata undefined for object inputs | `portfolio_file=None`, display `"(in-memory)"` | 4.2 |
| 8 | `analyze_risk_score` not in migration list | Explicitly included | 3.2 |
| 9 | `run_max_return_portfolio` hardcoded paths bug | Fixed | 2.7 |
| 10 | `RiskLimitsData.to_dict()` omits None → KeyError | `normalize_risk_config()` fills defaults | 1.2 |
| 11 | Need precedence rules for dual params | Single resolver, one input per call | 1.1 |
| 12 | Missing: migrate `analyze_risk_score` | Included as Step 3.2 | 3.2 |

## Critical Files

| File | Change |
|------|--------|
| `core/config_adapters.py` | NEW: shared resolvers, config adapter, risk normalizer |
| `core/optimization.py` | Accept Union inputs for both optimize functions |
| `core/scenario_analysis.py` | Accept Union inputs for `analyze_scenario` |
| `core/portfolio_analysis.py` | Extend `risk_yaml` to Union; import from config_adapters |
| `portfolio_optimizer.py` | Fix `run_what_if_scenario` + `run_max_return_portfolio` |
| `portfolio_risk_score.py` | Accept Union inputs for `run_risk_score_analysis` |
| `run_risk.py` | Update all 5 wrapper signatures |
| `services/portfolio_service.py` | Remove temp files (2 methods) |
| `services/optimization_service.py` | Remove temp files (2 methods) |
| `services/scenario_service.py` | Remove temp files (3 methods) |
| `mcp_tools/optimization.py` | Remove temp file creation/cleanup |
| `app.py` | Remove temp files (3 migratable endpoints) |
| `core/data_objects.py` | Remove `create_risk_limits_temp_file()` (Phase 4) |

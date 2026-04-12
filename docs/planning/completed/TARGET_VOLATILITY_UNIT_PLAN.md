# A5.3: target_volatility_unit parameter

**Codex review**: v1 FAIL (5 findings), v2 FAIL (4 findings), v3 addresses all.

## Context

During A5 Compare Scenarios eval, we found that `target_volatility: 3.0` is interpreted as 300% (not 3%) because the engine expects decimal form (0.03 = 3%). An agent naturally writes `3.0` meaning 3%. Adding an explicit `target_volatility_unit` param makes the interface agent-friendly without ambiguity.

The engine layer (`portfolio_risk_engine/`) always works in decimal internally. The conversion happens once at the MCP tool boundary.

## v1 Codex Findings (addressed in v2)

1. **HIGH: Breaking change** — default `"percent"` would silently convert existing decimal callers (`0.12` → `0.0012`).
2. **HIGH: risk_context internal path** — `_apply_risk_context()` sets `target_volatility` to a derived decimal value at line 193. Normalization must not touch this.
3. **HIGH: `mcp_server.py` wrappers missing** — MCP server has its own function signatures that pass through to `mcp_tools/`. New param must be added there too.
4. **MEDIUM: Invalid unit values** — `target_volatility_unit="foo"` would silently behave as decimal.
5. **MEDIUM: REST endpoints** — `app.py` has `/api/target-volatility` route. Out of scope (stays decimal), but must document.

## Design Decision: `"auto"` default

To avoid breaking existing callers while supporting agent-friendly usage:

```python
target_volatility_unit: Literal["auto", "percent", "decimal"] = "auto"
```

- `"percent"`: always divide by 100 (`5.0` → `0.05`)
- `"decimal"`: never divide (`0.05` → `0.05`)
- `"auto"` (default): values > 1.0 are treated as percent, values ≤ 1.0 as decimal

This means:
- Existing callers passing `0.12` → still `0.12` (auto detects decimal) ✓
- Agent passing `5.0` → auto detects percent → `0.05` ✓
- Edge case: `1.0` = 100%? No — auto treats ≤ 1.0 as decimal, so `1.0` = 100%. For exactly 1%, pass `target_volatility_unit="percent"`.

## v2 Codex Findings (addressed in v3)

1. **HIGH**: Normalize called before validation — NaN/inf/non-numeric could reach helper. Fix: validate first, then normalize.
2. **MEDIUM**: Auto boundary — `1.2` as decimal (120% vol) silently becomes `0.012`. Documented edge; use explicit `"decimal"` for > 100% vol targets.
3. **MEDIUM**: Per-scenario unit in compare — agent may put `target_volatility_unit` inside a scenario dict. Support it as per-scenario override with top-level as default.
4. **LOW**: More test cases needed for boundary and non-finite values.

## Shared normalization helper

Add to `mcp_tools/optimization.py`:

```python
def _validate_and_normalize_target_volatility(
    value: Any,
    unit: str,
) -> tuple[float | None, str | None]:
    """Validate and convert target_volatility to decimal form for the engine.

    Returns:
        (normalized_value, error_message). On success error_message is None.
    """
    # Validate unit
    if unit not in ("auto", "percent", "decimal"):
        return None, f"Invalid target_volatility_unit '{unit}'. Valid: auto, percent, decimal."

    # Validate value: must be positive finite number (reject bool, NaN, inf)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, "target_volatility must be a positive number."
    if not math.isfinite(value) or value <= 0:
        return None, "target_volatility must be a positive finite number."

    fval = float(value)

    # Normalize to decimal
    if unit == "percent":
        return fval / 100.0, None
    if unit == "decimal":
        return fval, None
    # "auto": > 1.0 treated as percent
    if fval > 1.0:
        return fval / 100.0, None
    return fval, None
```

**Auto boundary note**: Values in (0, 1.0] are treated as decimal. This means `1.0` = 100% vol, not 1%. For sub-1% targets (rare), callers must use `target_volatility_unit="percent"`. Values > 1.0 like `1.2` are treated as 1.2% (percent), not 120% (decimal). Existing callers passing `0.12` for 12% are unaffected.

## Changes

### 1. `mcp_tools/optimization.py` — `run_optimization()`

**Add parameter** (after `target_volatility`, line ~140):
```python
target_volatility_unit: Literal["auto", "percent", "decimal"] = "auto",
```

**Add validation + normalization** — BEFORE the `_apply_risk_context` block (line ~189):
```python
# Validate and normalize caller-provided target_volatility to decimal form.
if target_volatility is not None:
    target_volatility, tv_error = _validate_and_normalize_target_volatility(
        target_volatility, target_volatility_unit
    )
    if tv_error:
        return {"status": "error", "error": tv_error}
```

This goes at ~line 186, BEFORE the `if optimization_type == "min_variance":` block. The risk_context path at line 193 (`target_volatility = derived_target_volatility`) then overwrites with an already-decimal value — correct.

Also validate unit when `target_volatility` is None (early, before any work):
```python
if target_volatility_unit not in ("auto", "percent", "decimal"):
    return {"status": "error", "error": f"Invalid target_volatility_unit '{target_volatility_unit}'. Valid: auto, percent, decimal."}
```

**Update docstring** and error messages to reflect all three units.

### 2. `mcp_tools/compare.py` — `compare_scenarios()`

**Add parameter** to function signature:
```python
target_volatility_unit: Literal["auto", "percent", "decimal"] = "auto",
```

**Replace raw validation** in the scenario block (lines ~242-247) with the shared helper. Support per-scenario `target_volatility_unit` as override:
```python
if optimization_type == "target_volatility":
    tv = scenario.get("target_volatility")
    # Per-scenario unit overrides top-level default
    scenario_unit = scenario.get("target_volatility_unit", target_volatility_unit)
    tv_normalized, tv_error = _validate_and_normalize_target_volatility(tv, scenario_unit)
    if tv_error:
        return _error_response(f"Scenario '{name}': {tv_error}")
    normalized["target_volatility"] = tv_normalized
```

Import `_validate_and_normalize_target_volatility` from `mcp_tools.optimization`.

**Add unit validation** at the top of the function (same pattern as optimization tool).

### 3. `mcp_server.py` — MCP tool wrappers

**`run_optimization` wrapper** (line ~1708): Add `target_volatility_unit` param and pass through:
```python
def run_optimization(
    ...
    target_volatility_unit: Literal["auto", "percent", "decimal"] = "auto",
    ...
) -> dict:
    return _run_optimization(
        ...
        target_volatility_unit=target_volatility_unit,
        ...
    )
```

**`compare_scenarios` wrapper** (line ~1921): Same — add param and pass through.

### 4. No engine changes

`portfolio_risk_engine/` remains untouched — always receives decimal.

### 5. REST endpoints — OUT OF SCOPE

`/api/target-volatility` in `app.py` stays decimal. It's a frontend-facing endpoint with its own Pydantic model (`TargetVolatilityRequest`). No change needed — frontend already sends decimal.

### 6. Tests

**Unit tests for `_validate_and_normalize_target_volatility()`** (new test file or in existing):
- `(5.0, "auto")` → `(0.05, None)` — auto detects percent
- `(0.05, "auto")` → `(0.05, None)` — auto detects decimal
- `(1.0, "auto")` → `(1.0, None)` — boundary: decimal = 100%
- `(0.5, "auto")` → `(0.5, None)` — decimal = 50%
- `(5.0, "percent")` → `(0.05, None)` — explicit percent
- `(0.5, "percent")` → `(0.005, None)` — sub-1% edge case
- `(0.05, "decimal")` → `(0.05, None)` — explicit decimal
- `(1.2, "decimal")` → `(1.2, None)` — 120% vol, decimal mode
- `(True, "auto")` → `(None, error)` — reject bool
- `(float("nan"), "auto")` → `(None, error)` — reject NaN
- `(float("inf"), "auto")` → `(None, error)` — reject inf
- `(-5.0, "auto")` → `(None, error)` — reject negative
- `(0, "auto")` → `(None, error)` — reject zero
- `(5.0, "foo")` → `(None, error)` — reject invalid unit
- `("5.0", "auto")` → `(None, error)` — reject string

**`tests/mcp_tools/test_compare_new_opt_types.py`**:
- Update existing test: add `target_volatility_unit="decimal"` to preserve current `0.12` assertion
- Add: `target_volatility=12.0, unit="auto"` → engine receives `0.12`
- Add: `target_volatility=12.0, unit="percent"` → engine receives `0.12`
- Add: `target_volatility=0.12, unit="auto"` → engine receives `0.12` (unchanged)
- Add: per-scenario unit override: scenario dict has `"target_volatility_unit": "percent"` with top-level `"decimal"` → per-scenario wins
- Add: invalid per-scenario unit → error response
- Add: invalid top-level unit → error response

**`tests/mcp_tools/test_optimization_new_types.py`**:
- Add: `target_volatility=5.0` (default auto) → engine receives `0.05`
- Add: `target_volatility=0.05, unit="decimal"` → engine receives `0.05`
- Add: `target_volatility=5.0, unit="percent"` → engine receives `0.05`
- Add: invalid unit `"foo"` → error response
- Add: `target_volatility=NaN` → error response
- Add: `target_volatility=True` → error response

**`tests/mcp_tools/test_optimization_risk_context.py`**:
- Verify: risk_context derived `target_volatility=0.117` is NOT re-normalized (stays `0.117`)

## Files to modify

| File | Change |
|------|--------|
| `mcp_tools/optimization.py` | Add `_normalize_target_volatility()`, add `target_volatility_unit` param to `run_optimization()`, normalize before risk_context block |
| `mcp_tools/compare.py` | Add `target_volatility_unit` param, normalize in scenario loop |
| `mcp_server.py` | Add `target_volatility_unit` param to both `run_optimization` and `compare_scenarios` wrappers, pass through |
| `tests/mcp_tools/test_compare_new_opt_types.py` | Add auto/percent/decimal unit tests |
| `tests/mcp_tools/test_optimization_new_types.py` | Add auto/percent/decimal/invalid unit tests |
| `tests/mcp_tools/test_optimization_risk_context.py` | Verify risk_context path not re-normalized |

## Verification

1. Run tests: `python -m pytest tests/mcp_tools/test_compare_new_opt_types.py tests/mcp_tools/test_optimization_new_types.py tests/mcp_tools/test_optimization_risk_context.py -v`
2. Live MCP test after restart:
   - `run_optimization(optimization_type="target_volatility", target_volatility=5.0)` → succeeds (auto: 5.0 > 1.0 → 0.05)
   - `run_optimization(optimization_type="target_volatility", target_volatility=0.05, target_volatility_unit="decimal")` → same result
   - `compare_scenarios(mode="optimization", scenarios=[{"name":"5%","optimization_type":"target_volatility","target_volatility":5.0}])` → succeeds
   - `compare_scenarios(mode="optimization", scenarios=[{"name":"5%","optimization_type":"target_volatility","target_volatility":0.05}], target_volatility_unit="decimal")` → same result
   - Existing `0.12` callers with no unit param → still works (auto: 0.12 ≤ 1.0 → decimal)

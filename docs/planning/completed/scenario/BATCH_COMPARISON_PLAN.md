# Batch Scenario/Optimization Comparison

## Context

Three workflows need to compare multiple scenarios or optimizations side-by-side and pick the best one: Hedging (Step 4 — compare hedge candidates by risk reduction), Scenario Analysis (Step 3 — compare variants like "defensive rotation" vs "growth tilt"), Strategy Design (Step 3 — compare optimization profiles). Today each `run_whatif()` or `run_optimization()` call is independent — the agent must manually run N calls, extract metrics, and rank them. This tool automates that.

---

## Changes

### 1. Do NOT extract core helpers — call existing tools' internals directly

**Why no extraction**: The original plan proposed `_run_whatif_core()` and `_run_optimization_core()` returning only snapshot/flags. But existing `run_whatif()` and `run_optimization()` still need the full `WhatIfResult`/`OptimizationResult` objects for summary/full/report output modes. Extracting a core helper that returns only snapshot would either break those modes or require maintaining two return paths. Instead, the compare tool calls the same `ScenarioService` and `optimize_*` functions directly — no refactoring of existing tools needed.

**`compare.py` calls directly:**
```python
# What-if: same as whatif.py line 154
result = ScenarioService(cache_results=use_cache).analyze_what_if(
    portfolio_copy, target_weights=..., delta_changes=...,
    scenario_name=..., risk_limits_data=risk_limits_data)
snapshot = result.get_agent_snapshot()
flags = generate_whatif_flags(snapshot)
ranking_data = {k: v for k, v in snapshot.items() if k.startswith("_")}
clean = {k: v for k, v in snapshot.items() if not k.startswith("_")}

# Optimization: same as optimization.py line 128-131
result = optimize_min_variance(portfolio_copy, risk_limits_data)  # or optimize_max_return
original_weights = result.optimization_metadata.get("original_weights", {})
snapshot = result.get_agent_snapshot(original_weights)
flags = generate_optimization_flags(snapshot)
```

**No changes to `mcp_tools/whatif.py` or `mcp_tools/optimization.py`.** Existing tools remain untouched.

### 2. Deep-copy portfolio_data per scenario

**Critical**: `ScenarioService.analyze_what_if()` mutates `portfolio_data` in-place (modifies `stock_factor_proxies` at line 243/279, adds tickers via `add_ticker()` at line 266). Running N scenarios on the same object would corrupt later scenarios.

**Fix**: `copy.deepcopy(portfolio_data)` before each scenario run:
```python
import copy

for scenario in scenarios:
    portfolio_copy = copy.deepcopy(portfolio_data)
    # ... run scenario on portfolio_copy
```

This ensures all scenarios evaluate against the same baseline.

### 3. New file: `mcp_tools/compare.py`

```python
@handle_mcp_errors
def compare_scenarios(
    mode: Literal["whatif", "optimization"] = "whatif",
    scenarios: Optional[List[Dict]] = None,
    rank_by: Optional[str] = None,        # None = mode-specific default
    rank_order: Literal["asc", "desc"] = "asc",
    portfolio_name: str = "CURRENT_PORTFOLIO",
    use_cache: bool = True,
    user_email: Optional[str] = None,
) -> dict:
```

**Input format** — list of named scenario dicts:
```python
# What-if mode:
scenarios = [
    {"name": "Hedge with GLD", "delta_changes": {"GLD": "+10%", "AAPL": "-10%"}},
    {"name": "Hedge with TLT", "delta_changes": {"TLT": "+10%", "AAPL": "-10%"}},
    {"name": "Full defensive", "target_weights": {"SGOV": 0.40, "AAPL": 0.30, "MSFT": 0.30}},
]
# Optimization mode:
scenarios = [
    {"name": "Min variance"},
    {"name": "Max return", "optimization_type": "max_return"},
]
```

**Validation:**
- `scenarios` must be non-empty list, max 10 entries
- Each scenario must have a unique `name` (string)
- `mode` must be `"whatif"` or `"optimization"`
- `rank_order` must be `"asc"` or `"desc"`
- `rank_by` validated against mode-specific allowlist (see Ranking Keys below); invalid key → error
- What-if: each scenario needs `target_weights` or `delta_changes` (not both, not neither)
- Optimization: `optimization_type` defaults to `"min_variance"` if absent; must be `"min_variance"` or `"max_return"` if provided

**Execution flow:**
1. Validate inputs (mode, scenarios list, per-scenario params, rank_by allowlist)
2. Load portfolio data ONCE via `_load_portfolio_for_analysis()`
3. Load risk limits ONCE:
   - What-if mode: DB with file fallback (matches `whatif.py` lines 128-143). If no limits found, return error
   - Optimization mode: DB only, require non-empty (matches `optimization.py` lines 101-110)
4. If optimization mode has any `max_return` scenario: load expected returns once, attach to `portfolio_data`. If expected returns not found, mark only `max_return` scenarios as failed (do NOT fail the entire batch — `min_variance` scenarios can still run)
5. For each scenario: `copy.deepcopy(portfolio_data)` → call `ScenarioService.analyze_what_if()` or `optimize_*()` directly. Catch exceptions per-scenario → `{"status": "error", "error": str(e)}`
6. Extract ranking value from each successful result, sort by `rank_by`. Ties broken by scenario name (alphabetical)
7. Failed scenarios: assigned `rank_value = None`, sorted to bottom of ranking regardless of `rank_order`
8. Missing/non-numeric rank values from successful scenarios: treated as `float('inf')` for asc, `float('-inf')` for desc (sort to bottom)
9. Generate comparison-level flags
10. Return assembled response

**Ranking keys (allowlists):**

What-if valid keys — default `vol_delta` (ascending = biggest risk reduction first):
- `vol_delta` → `_ranking_data["_raw_vol_delta_pct"]` (from `get_agent_snapshot()` `_raw_*` keys)
- `conc_delta` → `_ranking_data["_raw_conc_delta"]`
- `total_violations` → sum of `snapshot["compliance"]["risk_violation_count"]` + `snapshot["compliance"]["factor_violation_count"]` + `snapshot["compliance"]["proxy_violation_count"]` (numeric counts from existing snapshot, not flag counting)
- `factor_var_delta` → `snapshot["risk_deltas"]["factor_variance_pct"]["delta"]`

Optimization valid keys — default `trades_required` (ascending = simplest first):
- `trades_required` → `snapshot["trades_required"]`
- `total_violations` → sum of `snapshot["compliance"]["risk_violation_count"]` + `snapshot["compliance"]["factor_violation_count"]` + `snapshot["compliance"]["proxy_violation_count"]`
- `hhi` → `snapshot["positions"]["hhi"]`
- `largest_weight_pct` → `snapshot["positions"]["largest_weight_pct"]`

Invalid `rank_by` → return `{"status": "error", "error": "Invalid rank_by '...' for mode '...'. Valid keys: ..."}`.

**Response shape:**
```python
{
    "status": "success",
    "mode": "whatif",
    "scenario_count": 3,
    "ranking": [
        {"rank": 1, "name": "Hedge with GLD", "rank_value": -3.2, "rank_by": "vol_delta", "verdict": "improves risk"},
        {"rank": 2, "name": "Hedge with TLT", "rank_value": -1.8, "rank_by": "vol_delta", "verdict": "improves risk"},
        {"rank": 3, "name": "Full defensive", "rank_value": 0.5, "rank_by": "vol_delta", "verdict": "increases risk"},
    ],
    "scenarios": {
        "Hedge with GLD": {"status": "success", "snapshot": {...}, "flags": [...]},
        ...
    },
    "summary": {
        "best": "Hedge with GLD",
        "worst": "Full defensive",
        "succeeded": 3,
        "failed": 0,
    },
    "flags": [...]  # comparison-level flags
}
```

**Verdict logic** (what-if mode, `vol_delta`/`conc_delta`/`factor_var_delta`):
- `rank_value < 0` → `"improves risk"`
- `rank_value == 0` → `"neutral"`
- `rank_value > 0` → `"increases risk"`

For `total_violations`: `0` → `"no violations"`, `> 0` → `"has violations"`.

For optimization mode: `trades_required` → always `"N trades required"`. `hhi`/`largest_weight_pct` → lower is `"more diversified"`, higher is `"more concentrated"`.

**Partial failure:** Failed scenarios sort to bottom of ranking with `status: "error"` and `rank_value: null`. Tool succeeds if >= 1 scenario succeeds. All fail → tool returns `status: "error"`.

### 4. New file: `core/comparison_flags.py`

```python
def generate_comparison_flags(response: dict) -> list[dict]:
```

Flag types:
- `clear_winner` (success) — best scenario dominates on primary metric. For 3+ scenarios: gap between 1st and 2nd must be >2x the gap between 2nd and 3rd, AND absolute gap between 1st and 2nd > 0.5. For exactly 2 scenarios: absolute gap between 1st and 2nd > 1.0. Direction-aware: for `rank_order="asc"`, lower rank_value is better; for `"desc"`, higher is better
- `marginal_differences` (info) — top 2 scenarios within 10% of each other on ranking metric (using `abs(v1 - v2) / max(abs(v1), abs(v2), 1e-9) < 0.10`). Mutually exclusive with `clear_winner`
- `partial_failures` (warning) — some (but not all) scenarios failed to run
- `best_has_violations` (warning) — top-ranked scenario has `total_violations > 0` (using snapshot compliance counts)
- `all_have_violations` (warning) — every successful scenario has `total_violations > 0`

### 5. Register in `mcp_server.py`

Add import + `@mcp.tool()` wrapper. Docstring:
> Compare multiple what-if scenarios or optimization variants side by side.
> Runs all scenarios on the same portfolio, ranks by risk impact, and identifies
> the best option. Use for hedge candidate evaluation, scenario comparison,
> or strategy variant selection.

---

## Files Changed

| File | Change |
|------|--------|
| `mcp_tools/compare.py` | NEW — `compare_scenarios()` MCP tool |
| `core/comparison_flags.py` | NEW — `generate_comparison_flags()` (5 flag types) |
| `mcp_server.py` | Register `compare_scenarios` tool |
| `tests/mcp_tools/test_compare_scenarios.py` | NEW — tool + ranking tests |
| `tests/core/test_comparison_flags.py` | NEW — flag tests |

**No changes to existing tools** — `mcp_tools/whatif.py` and `mcp_tools/optimization.py` are NOT modified.

---

## Key Design Decisions

1. **Single tool for both modes** — `compare_scenarios(mode="whatif"|"optimization")`. Ranking/formatting logic is shared; only the inner execution differs
2. **Portfolio loaded once, deep-copied per scenario** — load once via `_load_portfolio_for_analysis()`, `copy.deepcopy()` before each scenario run. `ScenarioService.analyze_what_if()` mutates `portfolio_data.stock_factor_proxies` and calls `portfolio_data.add_ticker()` — deep copy prevents cross-scenario contamination
3. **No new result object** — comparison is a thin orchestrator composing existing snapshots. No `ComparisonResult` class needed
4. **No refactoring of existing tools** — `compare.py` calls `ScenarioService` and `optimize_*()` directly (same call patterns as `whatif.py` and `optimization.py`). Avoids risk of breaking existing output modes (summary/full/report)
5. **`_ranking_data` carries raw values** — what-if snapshots' `_raw_*` keys (stripped for clean agent output) are preserved in a separate dict for ranking before discarding
6. **Max 10 scenarios** — prevents runaway computation. Each scenario takes 1-3 seconds; 10 = 10-30 seconds max
7. **Sequential execution** — no parallelism needed for N=3-5. Could add `concurrent.futures` later
8. **Mode-specific risk limit loading** — what-if uses DB+file fallback (matching `whatif.py`); optimization uses DB-only with non-empty requirement (matching `optimization.py`)
9. **Graceful expected-returns handling** — missing expected returns fails only `max_return` scenarios, not the entire batch. `min_variance` scenarios still run
10. **Deterministic ranking** — ties broken by scenario name (alphabetical). Failed scenarios always sort to bottom. Missing/non-numeric rank values treated as worst-case

---

## Verification

### Flag tests (`tests/core/test_comparison_flags.py`)
- `clear_winner` fires when gap is large (>2x AND abs gap > 0.5 for 3+ scenarios)
- `clear_winner` fires for 2-scenario comparison with absolute gap > 1.0
- `clear_winner` does NOT fire when abs gap ≤ threshold (0.5 for 3+, 1.0 for 2)
- `clear_winner` respects `rank_order` direction (asc vs desc)
- `marginal_differences` fires when top 2 are close (<10% relative difference)
- `clear_winner` and `marginal_differences` are mutually exclusive
- `partial_failures` fires when some scenarios errored
- `best_has_violations` fires when winner has snapshot compliance count > 0
- `all_have_violations` fires when every scenario has snapshot compliance count > 0

### Tool tests (`tests/mcp_tools/test_compare_scenarios.py`)
- What-if mode: 3 scenarios ranked correctly by vol_delta
- Optimization mode: 2 variants ranked correctly by trades_required
- Custom `rank_by` key (conc_delta, hhi, etc.)
- Invalid `rank_by` key → validation error with valid keys listed
- `rank_order` asc vs desc
- Partial failure: 1 of 3 fails, tool succeeds, failed sorts last with `rank_value: null`
- All failures: tool returns error
- Empty scenarios list → validation error
- Duplicate names → validation error
- Max 10 limit enforced
- What-if input validation (missing target_weights/delta_changes; both provided)
- Portfolio loaded exactly once (mock assertion)
- Portfolio deep-copied per scenario (mock assertion on `copy.deepcopy`)
- Response shape: ranking, scenarios, summary, flags all present
- max_return optimization loads expected returns once
- Missing expected returns fails only max_return scenarios, min_variance still runs
- Risk limits: what-if uses DB+file fallback; optimization uses DB-only
- Ties broken by scenario name
- Missing/non-numeric rank values sort to bottom

### Behavioral parity tests (in `test_compare_scenarios.py`)
- Single what-if scenario via `compare_scenarios()` produces same snapshot+flags as calling `ScenarioService.analyze_what_if()` directly with same inputs
- Single min_variance optimization scenario via `compare_scenarios()` produces same snapshot+flags as calling `optimize_min_variance()` directly with same inputs
- Single max_return optimization scenario via `compare_scenarios()` produces same snapshot+flags as calling `optimize_max_return()` directly with same inputs
- Existing `run_whatif()` and `run_optimization()` are NOT imported or modified by `compare.py`

### Integration test (manual)
After `/mcp` reconnect, call `compare_scenarios` with 3 what-if hedging scenarios on live portfolio. Verify ranking makes sense vs individual `run_whatif()` calls.

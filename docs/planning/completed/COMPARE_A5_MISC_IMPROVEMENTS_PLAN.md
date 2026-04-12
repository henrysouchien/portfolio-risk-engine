# Compare A5 Misc Improvements Plan

**Status**: DRAFT (v3 — R2 Codex review findings addressed)
**Type**: Bug fix batch — five small improvements to `compare_scenarios` and related result objects
**Bugs**: A5.4, A5.5, A5.6, A5.11, A5.12

---

## 1. Overview

Five bugs affecting the `compare_scenarios` MCP tool and the scenario result pipeline. All are low-risk, additive changes. No architectural changes — each is a targeted fix in one or two files plus tests. A5.4/A5.11 share the summary block in `compare.py`; A5.6/A5.12 share `whatif.py` — see Implementation Sequence for coordination notes.

| Bug | Summary | Severity | Files |
|-----|---------|----------|-------|
| A5.4 | `best`/`worst` identical when 1 scenario succeeds | Low | `mcp_tools/compare.py` |
| A5.5 | No indication of arbitrary tie-break | Low | `core/comparison_flags.py` |
| A5.6 | No flag when `delta_changes` references unknown ticker | Info | `core/whatif_flags.py`, `core/result_objects/whatif.py`, `services/scenario_service.py` |
| A5.11 | No baseline comparison — user must hack `{"DSU": "+0%"}` | Enhancement | `mcp_tools/compare.py`, `mcp_server.py` |
| A5.12 | `resolved_weights` unrounded (15 decimal places) | Low | `core/result_objects/whatif.py`, `core/result_objects/backtest.py`, `core/result_objects/monte_carlo.py`, `core/result_objects/basket.py` |

---

## 2. Bug A5.4 — `best`/`worst` identical when only 1 scenario succeeds

### Root Cause

`mcp_tools/compare.py:429-432`:

```python
successful_ranked = [row for row in ranking_output if row.get("status") == "success"]
summary = {
    "best": successful_ranked[0]["name"] if successful_ranked else None,
    "worst": successful_ranked[-1]["name"] if successful_ranked else None,
    ...
}
```

When `len(successful_ranked) == 1`, `successful_ranked[0]` and `successful_ranked[-1]` are the same element. The summary reports the same scenario as both best and worst, which is misleading.

### Fix

Set `worst = None` when fewer than 2 successful scenarios:

```python
successful_ranked = [row for row in ranking_output if row.get("status") == "success"]
summary = {
    "best": successful_ranked[0]["name"] if successful_ranked else None,
    "worst": successful_ranked[-1]["name"] if len(successful_ranked) >= 2 else None,
    "succeeded": succeeded,
    "failed": failed,
}
```

### Files Modified

- `mcp_tools/compare.py` (~line 432): Conditional on `len(successful_ranked) >= 2`

---

## 3. Bug A5.5 — No indication when tie-break is arbitrary

### Root Cause

`core/comparison_flags.py:60-75` emits a `marginal_differences` flag when the top two scenarios are within 10% relative difference, but does not flag the degenerate case where rank values are numerically identical (`abs(v1 - v2) < 1e-9`). When values are equal, the sort falls through to the `name` tiebreaker (alphabetical), which is arbitrary. The agent has no way to know the ranking is meaningless between those entries.

### Fix

Add an `arbitrary_tiebreak` info flag in `generate_comparison_flags()` when the top two successful scenarios have identical rank values. Insert this check before the existing `marginal_differences` block (line 60), inside the `if not has_clear_winner:` branch:

```python
if not has_clear_winner:
    v1 = first["rank_value"]
    v2 = second["rank_value"]

    # Exact tie — ranking is alphabetical, not meaningful
    if abs(v1 - v2) < 1e-9:
        flags.append(
            {
                "type": "arbitrary_tiebreak",
                "severity": "info",
                "message": (
                    f"{first['name']} and {second['name']} are tied on "
                    f"{first.get('rank_by', 'primary metric')} — ranking is alphabetical"
                ),
                "tied_scenarios": [first["name"], second["name"]],
            }
        )
    else:
        relative_diff = abs(v1 - v2) / max(abs(v1), abs(v2), 1e-9)
        if relative_diff < 0.10:
            flags.append(...)  # existing marginal_differences flag
```

The `arbitrary_tiebreak` flag is mutually exclusive with `marginal_differences` — an exact tie is a stronger signal, and `marginal_differences` would be redundant. Use `else` branching to ensure only one fires.

### Files Modified

- `core/comparison_flags.py` (~line 60-75): Add `arbitrary_tiebreak` flag, restructure into `if exact_tie / else if marginal`

---

## 4. Bug A5.6 — No flag when `delta_changes` references ticker not in portfolio

### Root Cause

`services/scenario_service.py:291-293` already computes `new_tickers`:

```python
current_tickers = {str(ticker).upper() for ticker in portfolio_data.get_tickers()}
requested_tickers = {str(ticker).upper() for ticker in delta_changes.keys()}
new_tickers = requested_tickers - current_tickers
```

But this value is used only for proxy generation and is never surfaced to the caller. The `WhatIfResult` object has no field for it, and `core/whatif_flags.py` has no corresponding flag. When a user references an unknown ticker in `delta_changes`, the analysis silently adds it with 0.001 shares — no transparency.

### Fix

Three changes:

**4a. Thread `new_tickers` into WhatIfResult**

Add an optional `new_tickers` field to `WhatIfResult.__init__()`:

```python
def __init__(self,
             current_metrics: RiskAnalysisResult,
             scenario_metrics: RiskAnalysisResult,
             scenario_name: str = "Unknown",
             risk_comparison: Optional[pd.DataFrame] = None,
             beta_comparison: Optional[pd.DataFrame] = None,
             new_tickers: Optional[List[str]] = None):
    ...
    self.new_tickers = new_tickers or []
```

Expose in `get_agent_snapshot()` (after `resolved_weights`, ~line 345):

```python
"resolved_weights": getattr(self.scenario_metrics, "portfolio_weights", None) or {},
"new_tickers": self.new_tickers,
```

**4b. Set `new_tickers` in ScenarioService**

In `services/scenario_service.py`, after the `analyze_scenario()` call returns the `WhatIfResult` (~line 377-395), attach the computed `new_tickers`:

```python
result = analyze_scenario(...)
if scenario_name != "what_if_scenario":
    result.scenario_name = scenario_name

# Expose new tickers introduced by delta_changes
if delta_param and new_tickers:
    result.new_tickers = sorted(new_tickers)
```

This is set after `analyze_scenario` returns because `analyze_scenario` (in `portfolio_risk_engine`) does not know about ticker resolution — that happens at the service layer. Setting it as a post-hoc attribute on `WhatIfResult` is consistent with how `scenario_name` is already set post-construction (~line 387).

**4c. Emit info flag in whatif_flags.py**

Add to `generate_whatif_flags()`, after the existing compliance flags:

```python
new_tickers = snapshot.get("new_tickers", [])
if new_tickers:
    flags.append(
        {
            "type": "new_tickers_added",
            "severity": "info",
            "message": (
                f"Scenario introduces {len(new_tickers)} ticker(s) not in current portfolio: "
                f"{', '.join(new_tickers)}"
            ),
            "new_tickers": new_tickers,
        }
    )
```

This benefits both standalone `run_whatif` and `compare_scenarios` (which calls `generate_whatif_flags` per scenario at `compare.py:319`).

### Files Modified

- `core/result_objects/whatif.py`: Add `new_tickers` field to `__init__`, expose in `get_agent_snapshot()`
- `services/scenario_service.py`: Set `result.new_tickers` after `analyze_scenario()` in delta path
- `core/whatif_flags.py`: Emit `new_tickers_added` info flag

---

## 5. Bug A5.11 — No baseline comparison

### Root Cause

`compare_scenarios()` requires the user to provide at least one scenario in the `scenarios` list. There is no way to include the current portfolio as a reference row. Users work around this by passing `{"name": "Current", "delta_changes": {"DSU": "+0%"}}` — a no-op delta that returns the baseline. This is unintuitive and wastes a scenario slot.

### Fix

Add `include_baseline: bool = False` parameter to `compare_scenarios()`. When `True`, prepend a synthetic "Current" row that uses the current portfolio's risk metrics without any delta.

**5a. Add parameter to function signature**

```python
@handle_mcp_errors
def compare_scenarios(
    mode: Literal["whatif", "optimization"] = "whatif",
    scenarios: Optional[list[dict]] = None,
    rank_by: Optional[str] = None,
    rank_order: Literal["asc", "desc"] = "asc",
    portfolio_name: str = "CURRENT_PORTFOLIO",
    use_cache: bool = True,
    user_email: Optional[str] = None,
    include_baseline: bool = False,
) -> dict:
```

**5b. Validate: only valid for whatif mode**

After mode validation (~line 175):

```python
if include_baseline and mode != "whatif":
    return _error_response("include_baseline is only supported for whatif mode")
```

**5c. Inject baseline scenario before the loop**

After loading `portfolio_data` and `risk_limits_data` but before the scenario loop (~line 298), when `include_baseline` is True:

```python
if include_baseline and mode == "whatif":
    try:
        # Run a no-op scenario to get baseline metrics in the same format
        baseline_result = scenario_service.analyze_what_if(
            copy.deepcopy(portfolio_data),
            delta_changes={"_baseline_": "+0%"},
            scenario_name="Current",
            risk_limits_data=risk_limits_data,
        )
```

Wait — using a fake ticker `_baseline_` is fragile. A better approach: run with an existing ticker and a `+0%` delta. But we don't know which ticker exists. Instead, use `target_weights` mode with the current portfolio weights:

Actually, the cleanest approach is to use the current portfolio's own analysis. The `ScenarioService` has a `portfolio_service.analyze_portfolio()` that returns a `RiskAnalysisResult`. But we need a `WhatIfResult`-shaped snapshot. The simplest correct approach is to run a no-op whatif using the first ticker in the portfolio with `+0%`:

```python
if include_baseline and mode == "whatif":
    baseline_name = "Current"
    try:
        # Get current tickers for a no-op delta
        current_tickers = portfolio_data.get_tickers()
        if current_tickers:
            noop_ticker = str(current_tickers[0])
            baseline_result = scenario_service.analyze_what_if(
                copy.deepcopy(portfolio_data),
                delta_changes={noop_ticker: "+0%"},
                scenario_name=baseline_name,
                risk_limits_data=risk_limits_data,
            )
            snapshot = baseline_result.get_agent_snapshot()
            flags = generate_whatif_flags(snapshot)
            ranking_data = {k: v for k, v in snapshot.items() if str(k).startswith("_")}
            clean_snapshot = {k: v for k, v in snapshot.items() if not str(k).startswith("_")}
            rank_value = _extract_rank_value(
                mode=mode, rank_by=rank_by_resolved,
                snapshot=snapshot, ranking_data=ranking_data,
            )
            scenario_results[baseline_name] = {
                "status": "success",
                "snapshot": clean_snapshot,
                "flags": flags,
                "is_baseline": True,
            }
            ranking_rows.append({
                "name": baseline_name,
                "status": "success",
                "rank_value": rank_value,
                "rank_by": rank_by_resolved,
                "is_baseline": True,
            })
            succeeded += 1
    except Exception as exc:
        logger.warning("Baseline scenario failed: %s", exc)
        # Non-fatal — continue with user scenarios
```

**5d. Don't count baseline against _MAX_SCENARIOS**

The existing validation at line 183-184 checks `len(scenarios) > _MAX_SCENARIOS` — this only counts user-provided scenarios, so the baseline (injected separately) naturally doesn't count against the limit. No change needed.

**5e. Mark baseline in ranking output**

In the ranking output loop (~line 404-427), propagate `is_baseline`:

```python
ranking_entry = {
    "rank": index,
    "name": row["name"],
    ...
}
if row.get("is_baseline"):
    ranking_entry["is_baseline"] = True
```

**5f. Exclude baseline from best/worst**

The baseline should not be "best" or "worst" — it's a reference point. Filter it out of `successful_ranked`:

```python
successful_ranked = [
    row for row in ranking_output
    if row.get("status") == "success" and not row.get("is_baseline")
]
```

**5g. Add `include_baseline` to the MCP server wrapper**

`mcp_server.py:1921` defines the user-facing MCP tool `compare_scenarios()`. It currently has no `include_baseline` parameter and does not forward it to `_compare_scenarios`. Without this change, MCP callers cannot request a baseline.

```python
@mcp.tool()
def compare_scenarios(
    mode: Literal["whatif", "optimization"] = "whatif",
    scenarios: Optional[str] = None,
    rank_by: Optional[str] = None,
    rank_order: Literal["asc", "desc"] = "asc",
    portfolio_name: str = "CURRENT_PORTFOLIO",
    use_cache: bool = True,
    include_baseline: bool = False,
) -> dict:
```

And forward it:

```python
    return _compare_scenarios(
        user_email=None,
        mode=mode,
        scenarios=parsed_scenarios,
        rank_by=rank_by,
        rank_order=rank_order,
        portfolio_name=portfolio_name,
        use_cache=use_cache,
        include_baseline=include_baseline,
    )
```

The docstring should also mention the new parameter: `"include_baseline: Include current portfolio as a 'Current' reference row (whatif mode only)."`.

**5h. Track baseline separately from user scenario counts**

The plan currently increments `succeeded += 1` when baseline succeeds. This breaks the existing `succeeded == 0` → all-failed semantics: if all user scenarios fail but include_baseline=True, the baseline success would make `succeeded == 1` and skip the all-failed error response. Baseline success must not mask user scenario failures.

Fix: Do NOT increment `succeeded` for the baseline. Instead, track baseline status separately. The `succeeded`/`failed` counters and the `summary.succeeded`/`summary.failed` fields reflect only user scenarios.

Replace the `succeeded += 1` line in the baseline injection block (5c) with:

```python
            # Do NOT increment succeeded/failed — baseline is tracked separately
            baseline_succeeded = True
    except Exception as exc:
        logger.warning("Baseline scenario failed: %s", exc)
        baseline_succeeded = False
        # Non-fatal — continue with user scenarios
```

The all-failed check at line 437 (`if succeeded == 0`) continues to work correctly because it only counts user scenarios.

**5i. Reserve the "Current" baseline name**

A user scenario named "Current" would collide with the baseline key in `scenario_results`. This check must run AFTER the existing normalization loop (which validates inputs and strips names), not before — running it against raw `scenarios` would fail on `None` inputs or non-dict entries before validation catches them.

Add the guard after the normalization loop produces `normalized_scenarios`, checking the already-stripped names:

```python
# After normalization loop completes:
if include_baseline:
    reserved = {s["name"] for s in normalized_scenarios} & {"Current"}
    if reserved:
        return _error_response(
            "Scenario name 'Current' is reserved when include_baseline=True. "
            "Rename the scenario or disable include_baseline."
        )
```

**5j. Filter baseline rows before passing to comparison flags**

`generate_comparison_flags()` treats every ranking row as a candidate. If the baseline ranks first, flags like `best_has_violations` or `clear_winner` may describe "Current" as the top scenario, which is misleading — the baseline is a reference point, not a candidate.

Fix: Before calling `generate_comparison_flags()`, filter `is_baseline` rows from the ranking in the `flags_input`:

```python
flags_input = dict(response)
flags_input["rank_order"] = rank_order
# Exclude baseline from comparison flags — it's a reference, not a candidate
flags_input["ranking"] = [
    row for row in ranking_output if not row.get("is_baseline")
]
response["flags"] = generate_comparison_flags(flags_input)
```

This keeps the baseline in the response's `ranking` list (for display) but excludes it from flag generation (for interpretation).

### Files Modified

- `mcp_tools/compare.py`: Add `include_baseline` parameter, inject baseline before loop, propagate `is_baseline`, exclude from best/worst, filter baseline from flag input
- `mcp_server.py` (~line 1921): Add `include_baseline` parameter to MCP wrapper, forward to `_compare_scenarios`

---

## 6. Bug A5.12 — `resolved_weights` include ~15 decimal places

### Root Cause

`optimization.py:321` rounds to 6 decimal places:
```python
"resolved_weights": {k: round(v, 6) for k, v in self.optimized_weights.items()},
```

The other three result objects do not:
- `whatif.py:345`: `getattr(self.scenario_metrics, "portfolio_weights", None) or {}`
- `backtest.py:145`: `self.weights`
- `monte_carlo.py:85` and `:133` and `:160`: `self.resolved_weights`

Agent consumers see weights like `0.234567890123456` instead of `0.234568`. This wastes tokens and creates visual noise. The optimization object already established the 6-decimal precedent.

### Fix

Apply `round(v, 6)` in each location. Weights are guaranteed numeric from the computation pipeline, so no `None` guard is needed — just round directly.

**whatif.py:345** — in `get_agent_snapshot()`:
```python
"resolved_weights": {
    k: round(v, 6) for k, v in (
        getattr(self.scenario_metrics, "portfolio_weights", None) or {}
    ).items()
},
```

**backtest.py:145** — in `get_agent_snapshot()`:
```python
"resolved_weights": {k: round(v, 6) for k, v in self.weights.items()},
```

**monte_carlo.py** — `resolved_weights` appears in 3 places (`get_summary:85`, `get_agent_snapshot:133`, `to_api_response:160`). Since `self.resolved_weights` is `Optional[Dict[str, float]]`, apply rounding at all 3 emission sites:

```python
"resolved_weights": (
    {k: round(v, 6) for k, v in self.resolved_weights.items()}
    if self.resolved_weights else self.resolved_weights
),
```

**basket.py:142** — `to_api_response()` emits `dict(self.resolved_weights)` unrounded. The `get_agent_snapshot()` method does not emit `resolved_weights` directly (it uses percentage-converted `max_weight_pct`), so only the API response needs rounding:

```python
"resolved_weights": {k: round(v, 6) for k, v in self.resolved_weights.items()},
```

**Not chosen**: Rounding at assignment time in `__init__` or `from_engine_output` — this would change the stored precision, which could affect downstream computation (e.g., if `resolved_weights` is passed back to another tool). Rounding at emission is safer and consistent with the optimization pattern.

### Files Modified

- `core/result_objects/whatif.py` (~line 345): Round in `get_agent_snapshot()`
- `core/result_objects/backtest.py` (~line 145): Round in `get_agent_snapshot()`
- `core/result_objects/monte_carlo.py` (~lines 85, 133, 160): Round in all 3 emission methods
- `core/result_objects/basket.py` (~line 142): Round in `to_api_response()`

---

## 7. Test Plan

### A5.4 Tests

**File**: `tests/mcp_tools/test_compare_scenarios.py`

```python
def test_single_success_worst_is_none(mock_compare_dependencies):
    """When only 1 scenario succeeds, worst should be None, not same as best."""
    # Set up 2 scenarios where 1 fails
    result = compare_scenarios(
        mode="whatif",
        scenarios=[
            {"name": "A", "delta_changes": {"AAPL": "+5%"}},
            {"name": "B", "delta_changes": {"AAPL": "+10%"}},
        ],
    )
    # Mock B to fail — or alternatively, provide 1 scenario
    # Simpler: test with the mock infrastructure returning 1 success + 1 failure
    assert result["summary"]["best"] is not None
    assert result["summary"]["worst"] is None  # NOT same as best


def test_two_successes_best_worst_differ(mock_compare_dependencies):
    """When 2+ scenarios succeed, best and worst should differ."""
    result = compare_scenarios(...)
    assert result["summary"]["best"] != result["summary"]["worst"]
```

### A5.5 Tests

**File**: `tests/core/test_comparison_flags.py`

```python
def test_exact_tie_fires_arbitrary_tiebreak_flag():
    """Two scenarios with identical rank values produce arbitrary_tiebreak flag."""
    resp = _response(rank_values=[1.5, 1.5])
    flags = generate_comparison_flags(resp)
    types = [f["type"] for f in flags]
    assert "arbitrary_tiebreak" in types
    assert "marginal_differences" not in types  # mutually exclusive


def test_exact_tie_not_fired_when_values_differ():
    """Close but not identical values produce marginal_differences, not arbitrary_tiebreak."""
    resp = _response(rank_values=[1.5, 1.6])
    flags = generate_comparison_flags(resp)
    types = [f["type"] for f in flags]
    assert "arbitrary_tiebreak" not in types
```

### A5.6 Tests

**File**: `tests/core/test_whatif_flags.py`

```python
def test_new_tickers_flag_fires():
    """Snapshot with new_tickers list emits new_tickers_added info flag."""
    snapshot = _base_snapshot()
    snapshot["new_tickers"] = ["NEWCO", "XYZ"]
    flags = generate_whatif_flags(snapshot)
    match = [f for f in flags if f["type"] == "new_tickers_added"]
    assert len(match) == 1
    assert match[0]["severity"] == "info"
    assert "NEWCO" in match[0]["message"]


def test_no_new_tickers_flag_when_empty():
    """No flag when new_tickers is empty or absent."""
    snapshot = _base_snapshot()
    flags = generate_whatif_flags(snapshot)
    assert not any(f["type"] == "new_tickers_added" for f in flags)

    snapshot["new_tickers"] = []
    flags = generate_whatif_flags(snapshot)
    assert not any(f["type"] == "new_tickers_added" for f in flags)
```

**File**: `tests/services/test_scenario_service.py`

```python
def test_delta_with_unknown_ticker_sets_new_tickers(monkeypatch):
    """WhatIfResult.new_tickers populated when delta references non-portfolio tickers."""
    # Stub analyze_scenario to return a WhatIfResult
    # Set up portfolio_data with tickers ["AAPL", "MSFT"]
    # Call analyze_what_if with delta_changes={"AAPL": "+5%", "NEWCO": "+3%"}
    # Assert result.new_tickers == ["NEWCO"]
```

### A5.11 Tests

**File**: `tests/mcp_tools/test_compare_scenarios.py`

```python
def test_include_baseline_adds_current_row(mock_compare_dependencies):
    """include_baseline=True prepends 'Current' row in results."""
    result = compare_scenarios(
        mode="whatif",
        scenarios=[{"name": "Aggressive", "delta_changes": {"AAPL": "+10%"}}],
        include_baseline=True,
    )
    assert "Current" in result["scenarios"]
    assert result["scenarios"]["Current"]["is_baseline"] is True
    # Current should appear in ranking
    baseline_rows = [r for r in result["ranking"] if r["name"] == "Current"]
    assert len(baseline_rows) == 1
    assert baseline_rows[0].get("is_baseline") is True


def test_include_baseline_excluded_from_best_worst(mock_compare_dependencies):
    """Baseline row should not be best or worst."""
    result = compare_scenarios(
        mode="whatif",
        scenarios=[{"name": "A", "delta_changes": {"AAPL": "+5%"}}],
        include_baseline=True,
    )
    assert result["summary"]["best"] != "Current"
    assert result["summary"]["worst"] != "Current"


def test_include_baseline_not_counted_against_max(mock_compare_dependencies):
    """Baseline does not count toward _MAX_SCENARIOS limit."""
    scenarios = [{"name": f"S{i}", "delta_changes": {"AAPL": f"+{i}%"}} for i in range(10)]
    result = compare_scenarios(
        mode="whatif",
        scenarios=scenarios,
        include_baseline=True,
    )
    assert result["status"] == "success"  # 10 user + 1 baseline = 11, but OK


def test_include_baseline_rejected_for_optimization():
    """include_baseline only valid for whatif mode."""
    result = compare_scenarios(
        mode="optimization",
        scenarios=[{"name": "A", "optimization_type": "min_variance"}],
        include_baseline=True,
    )
    assert result["status"] == "error"
    assert "whatif" in result["error"]


def test_include_baseline_current_name_reserved(mock_compare_dependencies):
    """User scenario named 'Current' rejected when include_baseline=True."""
    result = compare_scenarios(
        mode="whatif",
        scenarios=[{"name": "Current", "delta_changes": {"AAPL": "+5%"}}],
        include_baseline=True,
    )
    assert result["status"] == "error"
    assert "reserved" in result["error"].lower()


def test_include_baseline_not_counted_in_succeeded(mock_compare_dependencies):
    """Baseline success does not increment succeeded count in summary."""
    # All user scenarios fail, but baseline succeeds
    # summary.succeeded should be 0, triggering all-failed error
    result = compare_scenarios(
        mode="whatif",
        scenarios=[{"name": "Fail", "delta_changes": {"NONEXISTENT": "+100%"}}],
        include_baseline=True,
    )
    # Assert the full contract — status error, succeeded 0, failed matches user scenarios
    assert result["status"] == "error"
    assert result["summary"]["succeeded"] == 0
    assert result["summary"]["failed"] == 1  # the one user scenario


def test_include_baseline_excluded_from_comparison_flags(mock_compare_dependencies):
    """Baseline row should not appear in comparison flag reasoning."""
    result = compare_scenarios(
        mode="whatif",
        scenarios=[
            {"name": "A", "delta_changes": {"AAPL": "+5%"}},
            {"name": "B", "delta_changes": {"AAPL": "+10%"}},
        ],
        include_baseline=True,
    )
    # Flags like clear_winner/best_has_violations should never reference "Current"
    for flag in result.get("flags", []):
        if "winner" in flag:
            assert flag["winner"] != "Current"
        if "name" in flag:
            assert flag["name"] != "Current"
```

### A5.12 Tests

**File**: `tests/core/test_result_objects.py` (or per-object test files)

```python
def test_whatif_resolved_weights_rounded():
    """WhatIfResult.get_agent_snapshot() resolved_weights have at most 6 decimals."""
    result = _make_whatif_result_with_weights({"AAPL": 0.1234567890123456})
    snapshot = result.get_agent_snapshot()
    for v in snapshot["resolved_weights"].values():
        assert v == round(v, 6)


def test_backtest_resolved_weights_rounded():
    """BacktestResult.get_agent_snapshot() resolved_weights have at most 6 decimals."""
    result = BacktestResult(weights={"AAPL": 0.1234567890123456}, ...)
    snapshot = result.get_agent_snapshot()
    for v in snapshot["resolved_weights"].values():
        assert v == round(v, 6)


def test_monte_carlo_resolved_weights_rounded():
    """MonteCarloResult resolved_weights rounded in all emission methods."""
    result = MonteCarloResult(resolved_weights={"AAPL": 0.1234567890123456}, ...)
    summary = result.get_summary()
    assert summary["resolved_weights"]["AAPL"] == round(0.1234567890123456, 6)

    snapshot = result.get_agent_snapshot()
    assert snapshot["conditioning"]["resolved_weights"]["AAPL"] == round(0.1234567890123456, 6)

    api = result.to_api_response()
    assert api["resolved_weights"]["AAPL"] == round(0.1234567890123456, 6)


def test_monte_carlo_none_resolved_weights_unchanged():
    """MonteCarloResult with None resolved_weights stays None."""
    result = MonteCarloResult(resolved_weights=None, ...)
    summary = result.get_summary()
    assert summary["resolved_weights"] is None


def test_basket_resolved_weights_rounded():
    """BasketAnalysisResult.to_api_response() resolved_weights have at most 6 decimals."""
    result = BasketAnalysisResult(resolved_weights={"AAPL": 0.1234567890123456}, ...)
    api = result.to_api_response()
    for v in api["resolved_weights"].values():
        assert v == round(v, 6)
```

---

## 8. Files Modified (Summary)

| File | Bugs | Change |
|------|------|--------|
| `mcp_tools/compare.py` | A5.4, A5.11 | `worst` guard + `include_baseline` parameter + baseline injection + baseline flag filtering |
| `mcp_server.py` | A5.11 | Add `include_baseline` param to MCP wrapper, forward to `_compare_scenarios` |
| `core/comparison_flags.py` | A5.5 | `arbitrary_tiebreak` info flag |
| `core/whatif_flags.py` | A5.6 | `new_tickers_added` info flag |
| `core/result_objects/whatif.py` | A5.6, A5.12 | `new_tickers` field + `resolved_weights` rounding |
| `core/result_objects/backtest.py` | A5.12 | `resolved_weights` rounding |
| `core/result_objects/monte_carlo.py` | A5.12 | `resolved_weights` rounding (3 sites) |
| `core/result_objects/basket.py` | A5.12 | `resolved_weights` rounding in `to_api_response()` |
| `services/scenario_service.py` | A5.6 | Set `result.new_tickers` in delta path |

**Test files** (new or modified):
| File | Bugs |
|------|------|
| `tests/mcp_tools/test_compare_scenarios.py` | A5.4, A5.11 (incl. name reservation, baseline count, flag filtering) |
| `tests/core/test_comparison_flags.py` | A5.5 |
| `tests/core/test_whatif_flags.py` | A5.6 |
| `tests/services/test_scenario_service.py` | A5.6 |
| `tests/core/test_result_objects.py` (or per-object files) | A5.12 (incl. basket rounding) |

---

## 9. Implementation Sequence

The five bugs are mostly independent but have two coordination points:

- **A5.4 and A5.11** both edit the summary block in `mcp_tools/compare.py` (~lines 429-435). A5.4 changes the `worst` conditional; A5.11 adds `is_baseline` filtering to `successful_ranked` and adds baseline tracking. Implement A5.4 first, then A5.11 builds on the same block.
- **A5.6 and A5.12** both edit `core/result_objects/whatif.py` `get_agent_snapshot()`. A5.6 adds the `new_tickers` field; A5.12 adds rounding to `resolved_weights`. No conflict, but apply both in one pass to avoid merge churn.

Suggested sequence (least to most risk):

1. **A5.12** (resolved_weights rounding) — Pure output formatting, zero logic change
2. **A5.4** (best/worst guard) — One-line conditional
3. **A5.5** (arbitrary_tiebreak flag) — Additive flag, restructure of one existing block
4. **A5.6** (new_tickers flag) — Three files, but all additive
5. **A5.11** (include_baseline) — Most complex, adds a parameter + pre-loop injection

---

## 10. Risk Assessment

| Dimension | Assessment |
|---|---|
| **Blast radius** | All changes are additive. No existing fields removed, no signatures changed (only added). Agent consumers that ignore new fields are unaffected. |
| **A5.4 risk** | Nil. Consumers reading `worst: null` already handle `null` for the 0-success case. |
| **A5.5 risk** | Nil. New flag type. Agents that don't recognize `arbitrary_tiebreak` skip it. |
| **A5.6 risk** | Low. `new_tickers` field is additive on `WhatIfResult`. The `from_core_scenario` factory doesn't set it (it doesn't know about ticker resolution), so `new_tickers` defaults to `[]` for that path. Only the service-layer delta path sets it post-hoc. |
| **A5.11 risk** | Low-medium. The baseline uses a no-op delta on an existing ticker, which exercises the full whatif pipeline. Edge case: if `portfolio_data.get_tickers()` returns empty, no baseline is injected (non-fatal). The `try/except` ensures baseline failures don't block user scenarios. Baseline tracked separately from user scenario counts (won't mask all-failed). "Current" name reserved when `include_baseline=True`. Baseline filtered from comparison flags to prevent misleading `clear_winner`/`best_has_violations`. MCP server wrapper forwards the parameter. |
| **A5.12 risk** | Nil. Rounding at emission time, not storage time. Internal precision preserved for any downstream tool-chaining. Matches optimization.py precedent exactly. Basket's `to_api_response()` also covered (the agent snapshot does not emit raw weights). |
| **Backward compat** | All changes are strictly additive or refine edge-case behavior. No API contract breaks. |
| **Rollback** | Each bug is independently revertable. |

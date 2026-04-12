# Plan: Fix A5.3 target_volatility Error Message + A5.9 factor_var_delta Verdict Semantics

**Bugs**: A5.3 (opaque `target_volatility` error message) and A5.9 (`factor_var_delta` verdict treats higher systematic risk as worse).
**Severity**: Both Medium. **Scope**: Small-medium (~30 lines of logic + tests across 4 source files).

---

## 1. A5.3 — Opaque target_volatility Error Message

### Root Cause

`portfolio_risk_engine/efficient_frontier.py:398-399`:

```python
if target_volatility > data["max_vol"]:
    raise ValueError("Target volatility exceeds max_vol risk limit")
```

The error message does not include either the requested target or the configured limit. The user sees "exceeds max_vol risk limit" with no way to know what the limit is. Worse, when the target is below the portfolio's current vol (e.g., 3% target vs 7.75% current), "exceeds" sounds like the target is too risky — but the actual issue is the target exceeds a configured *ceiling* in the risk profile, which may itself be lower than the current vol (unlikely but possible), or the user confused target_volatility with something else.

`data["max_vol"]` comes from `risk_config["portfolio_limits"]["max_volatility"]` (line 123 of the same file).

### Fix

**File**: `portfolio_risk_engine/efficient_frontier.py`
**Location**: Line 399

**Current code**:
```python
raise ValueError("Target volatility exceeds max_vol risk limit")
```

**New code**:
```python
raise ValueError(
    f"Target volatility {target_volatility:.2%} exceeds configured limit "
    f"({data['max_vol']:.2%}). Adjust risk profile or lower target."
)
```

Single line change. The f-string includes both the requested target and the configured limit so the user can see exactly what went wrong and what to change.

### Downstream Impact

One existing test hardcodes the old error string:

**File**: `tests/mcp_tools/test_optimization_new_types.py`, line 230 and 241

The test at line 225-241 (`test_target_volatility_above_max_vol`) manually raises `ValueError("Target volatility exceeds max_vol risk limit")` in a mock and then asserts the exact string appears in the response. This test mocks `optimize_target_volatility` entirely — it never calls the real `solve_single_volatility_target`. The mock's raised message should be updated to match the new format, and the assertion should match a substring that will appear in the real error:

```python
# Line 230: update mock error message
raise ValueError(
    "Target volatility 50.00% exceeds configured limit (35.00%). "
    "Adjust risk profile or lower target."
)

# Line 241: update assertion to match key substring
assert "exceeds configured limit" in out["error"]
```

There is also a test in `test_efficient_frontier_targets.py:104` (`test_solve_single_volatility_target_infeasible_raises`) but this tests the *infeasible solver* path (target=0.10, which is below max_vol=0.35), not the limit check path. No change needed there.

---

## 2. A5.9 — factor_var_delta Verdict Semantics

### Root Cause

`mcp_tools/compare.py:137-142`:

```python
if rank_by in {"vol_delta", "conc_delta", "factor_var_delta"}:
    if rank_value < 0:
        return "improves risk"
    if math.isclose(rank_value, 0.0, abs_tol=1e-12):
        return "neutral"
    return "increases risk"
```

All three delta metrics are treated as lower=better. This is correct for `vol_delta` (lower portfolio volatility = less risk) and `conc_delta` (lower concentration = more diversified). But `factor_var_delta` measures the change in the percentage of portfolio variance explained by systematic factors. Higher factor variance % means more of the risk is systematic (market/sector/factor-driven) and therefore hedgeable. Lower factor variance % means more idiosyncratic (stock-specific) risk. Neither direction is universally "better" or "worse" — it depends on the portfolio's goals.

The current code says a scenario that shifts risk toward systematic factors "increases risk", which is misleading. A Heavy Bonds scenario with +14.47pp factor variance delta gets labeled "increases risk" when it's actually making the portfolio more systematically driven (and potentially easier to hedge).

### Fix

**File**: `mcp_tools/compare.py`
**Location**: `_build_verdict()`, lines 137-142

**Current code**:
```python
if rank_by in {"vol_delta", "conc_delta", "factor_var_delta"}:
    if rank_value < 0:
        return "improves risk"
    if math.isclose(rank_value, 0.0, abs_tol=1e-12):
        return "neutral"
    return "increases risk"
```

**New code**:
```python
if rank_by in {"vol_delta", "conc_delta"}:
    if rank_value < 0:
        return "improves risk"
    if math.isclose(rank_value, 0.0, abs_tol=1e-12):
        return "neutral"
    return "increases risk"
if rank_by == "factor_var_delta":
    if math.isclose(rank_value, 0.0, abs_tol=1e-12):
        return "neutral"
    if rank_value > 0:
        return "more systematic"
    return "more idiosyncratic"
```

The verdicts are descriptive rather than judgmental. "more systematic" and "more idiosyncratic" inform the agent/user about the direction of the shift without implying one is better. The agent can interpret the meaning in context (e.g., "more systematic = easier to hedge" or "more idiosyncratic = more stock-picking risk").

### Summary Labels (best/worst) Neutralization

**File**: `mcp_tools/compare.py`
**Location**: Lines 429-435

`summary.best` and `summary.worst` are set from the first and last successful ranked entries. For directional metrics like `vol_delta`, "best" and "worst" are meaningful. For `factor_var_delta`, they impose a value judgment on a non-directional metric.

**Current code** (lines 429-435):
```python
summary = {
    "best": successful_ranked[0]["name"] if successful_ranked else None,
    "worst": successful_ranked[-1]["name"] if successful_ranked else None,
    "succeeded": succeeded,
    "failed": failed,
}
```

**New code** (sort-order-aware):
```python
if rank_by_resolved == "factor_var_delta":
    if rank_order == "asc":
        first_label, last_label = "most_idiosyncratic", "most_systematic"
    else:
        first_label, last_label = "most_systematic", "most_idiosyncratic"
else:
    first_label, last_label = "best", "worst"
summary = {
    first_label: successful_ranked[0]["name"] if successful_ranked else None,
    last_label: successful_ranked[-1]["name"] if successful_ranked else None,
    "succeeded": succeeded,
    "failed": failed,
}
```

This removes the value judgment from summary labels while preserving backward compatibility for all other `rank_by` values.

### Comparison Flags Neutralization

**File**: `core/comparison_flags.py`
**Location**: Lines 26-57 (`clear_winner` flag) and line 89 (`best_has_violations` flag)

The `clear_winner` flag at lines 35-57 uses language like "is a clear winner" and "clearly outperforms". For `factor_var_delta`, this implies one direction of systematic/idiosyncratic shift is better. The `best_has_violations` flag at line 89 references the "Top-ranked scenario" which for `factor_var_delta` carries no inherent quality judgment.

**Fix**: Thread `rank_by` through the flags input (it's already available in `flags_input` at line 456-457 of `compare.py`) and adjust wording for non-directional metrics.

**File**: `core/comparison_flags.py`
**Location**: Inside `generate_comparison_flags()`, after extracting `rank_order`

**Add**:
```python
rank_by = response.get("rank_by", "")
is_non_directional = rank_by == "factor_var_delta"
```

**File**: `mcp_tools/compare.py`
**Location**: Line 456-457, where `flags_input` is built

**Current code**:
```python
flags_input = dict(response)
flags_input["rank_order"] = rank_order
```

**New code**:
```python
flags_input = dict(response)
flags_input["rank_order"] = rank_order
flags_input["rank_by"] = rank_by_resolved
```

**File**: `core/comparison_flags.py`
**Location**: Lines 35-57 (clear_winner messages)

For the 3+ scenario case (line 35-44), change the message:
```python
# Current:
f"{first['name']} is a clear winner on {first.get('rank_by', 'primary metric')}"

# New (non-directional):
(
    f"{first['name']} is most distinct on {first.get('rank_by', 'primary metric')}"
    if is_non_directional
    else f"{first['name']} is a clear winner on {first.get('rank_by', 'primary metric')}"
)
```

For the 2-scenario case (line 46-57), change the message:
```python
# Current:
f"{first['name']} clearly outperforms {second['name']} on "
f"{first.get('rank_by', 'primary metric')}"

# New (non-directional):
(
    f"{first['name']} differs significantly from {second['name']} on "
    f"{first.get('rank_by', 'primary metric')}"
    if is_non_directional
    else f"{first['name']} clearly outperforms {second['name']} on "
    f"{first.get('rank_by', 'primary metric')}"
)
```

Also change the flag `type` from `"clear_winner"` to `"clear_separation"` when `is_non_directional`, and the key from `"winner"` to `"first_ranked"`. This avoids the word "winner" entirely for non-directional metrics. Additionally, set the flag severity to `"info"` (instead of inheriting `"success"` from the `clear_winner` path) — a clear separation on a non-directional metric is informational, not a successful outcome.

**File**: `core/comparison_flags.py`
**Location**: Line 89-105 (`best_has_violations` flag)

Change message wording AND flag type for non-directional metrics:
```python
# Current:
f"Top-ranked scenario '{best_entry['name']}' still has "
f"{best_total_violations} violation(s)"

# New (non-directional):
(
    f"First-ranked scenario '{best_entry['name']}' has "
    f"{best_total_violations} violation(s)"
    if is_non_directional
    else f"Top-ranked scenario '{best_entry['name']}' still has "
    f"{best_total_violations} violation(s)"
)
```

Also conditionally rename the flag **type** from `best_has_violations` to `first_ranked_has_violations` when `is_non_directional`. The flag type is agent-visible metadata — keeping "best" in the type name for a non-directional metric is misleading even if the message text is neutralized:
```python
# Flag type selection:
flag_type = "first_ranked_has_violations" if is_non_directional else "best_has_violations"
```

### Sort Key Analysis

`_ranking_sort_key()` at lines 106-117 is a generic sort function that takes `rank_order` ("asc" or "desc") and applies it uniformly to the `rank_value`. It does not special-case any `rank_by` value. With `rank_order="asc"` (default), lower `factor_var_delta` sorts first — meaning more-idiosyncratic scenarios rank first.

The sort key itself is fine — it's a generic comparator. The value judgment previously leaked through summary labels ("best"/"worst") and comparison flags ("winner"/"outperforms"), both of which are now neutralized above.

**No changes to `_ranking_sort_key()`.**

### MCP Tool Description Fix

**File**: `mcp_server.py`
**Location**: Lines 1929-1936 (docstring of `compare_scenarios()`)

**Current docstring**:
```python
"""
Compare multiple what-if scenarios or optimization variants side by side.
Runs all scenarios on the same portfolio, ranks by risk impact, and identifies
the best option. Use for hedge candidate evaluation, scenario comparison,
or strategy variant selection.

scenarios accepts a JSON array string of scenario objects.
"""
```

"ranks by risk impact" is misleading for `factor_var_delta` (and for optimization-mode metrics like `trades_required`). "identifies the best option" imposes a value judgment that doesn't apply to non-directional metrics.

**New docstring**:
```python
"""
Compare multiple what-if scenarios or optimization variants side by side.
Runs all scenarios on the same portfolio, ranks by a selected metric, and
summarizes the results. Use for hedge candidate evaluation, scenario comparison,
or strategy variant selection.

scenarios accepts a JSON array string of scenario objects.
"""
```

Single-line change: "ranks by risk impact, and identifies the best option" → "ranks by a selected metric, and summarizes the results". Accurate for all rank_by values.

---

## 3. Test Plan

### File: `tests/portfolio_risk_engine/test_efficient_frontier_targets.py`

**Test A5.3-1: Error message includes target and limit values**

```python
def test_solve_single_volatility_target_exceeding_limit_shows_values(monkeypatch):
    _patch_synthetic_market_data(monkeypatch)

    with pytest.raises(ValueError, match=r"50\.00%.*exceeds configured limit.*35\.00%"):
        frontier_mod.solve_single_volatility_target(
            weights={"LOW": 0.5, "HIGH": 0.5},
            config=_base_config(),
            risk_config=_base_risk_config(),
            proxies={"LOW": {}, "HIGH": {}},
            expected_returns={"LOW": 0.03, "HIGH": 0.12},
            target_volatility=0.50,
        )
```

Uses `_base_risk_config()` which sets `max_volatility: 0.35`. Target 0.50 > 0.35 triggers the limit check. The regex verifies both the target (50.00%) and the limit (35.00%) appear in the error.

### File: `tests/mcp_tools/test_optimization_new_types.py`

**Update existing test** (`test_target_volatility_above_max_vol`, line 225):

Update the mock error string at line 230 and the assertion at line 241 to match the new format. See section 1 above.

### File: `tests/mcp_tools/test_compare_scenarios.py`

**Test A5.9-1: factor_var_delta positive → "more systematic"**

```python
def test_verdict_factor_var_delta_positive_is_more_systematic():
    verdict = compare_tool._build_verdict(
        mode="whatif",
        rank_by="factor_var_delta",
        rank_value=5.0,
    )
    assert verdict == "more systematic"
```

**Test A5.9-2: factor_var_delta negative → "more idiosyncratic"**

```python
def test_verdict_factor_var_delta_negative_is_more_idiosyncratic():
    verdict = compare_tool._build_verdict(
        mode="whatif",
        rank_by="factor_var_delta",
        rank_value=-5.0,
    )
    assert verdict == "more idiosyncratic"
```

**Test A5.9-3: factor_var_delta zero → "neutral"**

```python
def test_verdict_factor_var_delta_zero_is_neutral():
    verdict = compare_tool._build_verdict(
        mode="whatif",
        rank_by="factor_var_delta",
        rank_value=0.0,
    )
    assert verdict == "neutral"
```

**Test A5.9-4: Regression — vol_delta verdicts unchanged**

```python
def test_verdict_vol_delta_unchanged():
    assert compare_tool._build_verdict(mode="whatif", rank_by="vol_delta", rank_value=-1.0) == "improves risk"
    assert compare_tool._build_verdict(mode="whatif", rank_by="vol_delta", rank_value=0.0) == "neutral"
    assert compare_tool._build_verdict(mode="whatif", rank_by="vol_delta", rank_value=1.0) == "increases risk"
```

**Test A5.9-5: Regression — conc_delta verdicts unchanged**

```python
def test_verdict_conc_delta_unchanged():
    assert compare_tool._build_verdict(mode="whatif", rank_by="conc_delta", rank_value=-0.03) == "improves risk"
    assert compare_tool._build_verdict(mode="whatif", rank_by="conc_delta", rank_value=0.0) == "neutral"
    assert compare_tool._build_verdict(mode="whatif", rank_by="conc_delta", rank_value=0.01) == "increases risk"
```

**Test A5.9-6: Integration — compare_scenarios with rank_by=factor_var_delta exercises ranking, summary, and flags**

This is an integration-style test that mocks `ScenarioService.analyze_what_if` to return controlled results, then calls `compare_scenarios()` end-to-end with `rank_by="factor_var_delta"` and verifies:
- Ranking verdicts use "more systematic" / "more idiosyncratic" (not "improves risk" / "increases risk")
- Summary uses `most_systematic` / `most_idiosyncratic` keys (not `best` / `worst`)
- Comparison flags avoid "winner" / "outperforms" language for this metric

```python
def test_compare_scenarios_factor_var_delta_integration(monkeypatch):
    """End-to-end: ranking, summary labels, and comparison flags are all
    neutralized when rank_by=factor_var_delta."""
    # Mock _load_portfolio_for_analysis to return a fake portfolio
    # Mock ScenarioService.analyze_what_if to return two results with
    # different factor_variance_pct deltas (one positive, one negative)

    result = compare_scenarios(
        mode="whatif",
        scenarios=[
            {"name": "Heavy Bonds", "delta_changes": {"TLT": 0.20}},
            {"name": "Heavy Tech", "delta_changes": {"QQQ": 0.20}},
        ],
        rank_by="factor_var_delta",
        rank_order="asc",
    )

    assert result["status"] == "success"

    # Verify ranking verdicts
    verdicts = {r["name"]: r["verdict"] for r in result["ranking"]}
    for v in verdicts.values():
        assert v in {"more systematic", "more idiosyncratic", "neutral"}
        assert v not in {"improves risk", "increases risk"}

    # Verify summary uses neutral keys
    assert "best" not in result["summary"]
    assert "worst" not in result["summary"]
    assert "most_systematic" in result["summary"] or "most_idiosyncratic" in result["summary"]

    # Verify comparison flags avoid winner/outperforms language
    for flag in result.get("flags", []):
        assert "winner" not in flag.get("type", "").lower()
        assert "outperforms" not in flag.get("message", "").lower()
```

The mock setup follows the same pattern as other tests in `test_compare_scenarios.py`. The exact mock wiring depends on the test file's existing fixtures but should:
1. Patch `_load_portfolio_for_analysis` to return `(None, 1, mock_portfolio_data)`
2. Patch `RiskLimitsManager.load_risk_limits` to return a valid risk limits object
3. Patch `ScenarioService.analyze_what_if` with two calls returning results whose `get_agent_snapshot()` includes `risk_deltas.factor_variance_pct.delta` values of +14.0 and -3.0 respectively

**Test A5.9-7: Comparison flags use neutral language for factor_var_delta**

Unit test for `generate_comparison_flags` directly:

```python
def test_comparison_flags_factor_var_delta_neutral_language():
    """clear_winner flag uses 'distinct' not 'winner' for factor_var_delta."""
    # rank_values chosen so gap_12=9.0 >> gap_23=0.2, triggering clear_separation
    response = {
        "ranking": [
            {"name": "A", "status": "success", "rank_value": -10.0, "rank_by": "factor_var_delta"},
            {"name": "B", "status": "success", "rank_value": -1.0, "rank_by": "factor_var_delta"},
            {"name": "C", "status": "success", "rank_value": -0.8, "rank_by": "factor_var_delta"},
        ],
        "scenarios": {
            "A": {"status": "success", "snapshot": {"compliance": {}}},
            "B": {"status": "success", "snapshot": {"compliance": {}}},
            "C": {"status": "success", "snapshot": {"compliance": {}}},
        },
        "summary": {"succeeded": 3, "failed": 0},
        "rank_order": "asc",
        "rank_by": "factor_var_delta",
    }
    flags = generate_comparison_flags(response)
    # With gap_12=9.0 > 2*gap_23=0.4, the clear_separation flag should fire
    sep_flags = [f for f in flags if f.get("type") == "clear_separation"]
    assert len(sep_flags) == 1, f"Expected clear_separation flag, got types: {[f.get('type') for f in flags]}"
    assert "most distinct" in sep_flags[0]["message"]
    assert sep_flags[0]["severity"] == "info"  # informational, not "success"
    for flag in flags:
        assert "winner" not in flag.get("type", "")
        assert "outperforms" not in flag.get("message", "").lower()
```

**Test A5.9-8: first_ranked_has_violations fires for factor_var_delta with violations**

The existing flag tests use empty `compliance` payloads, so `first_ranked_has_violations` never fires. This test verifies the non-directional violation flag path.

```python
def test_comparison_flags_factor_var_delta_first_ranked_has_violations():
    """first_ranked_has_violations fires (not best_has_violations) when
    rank_by=factor_var_delta and the first-ranked scenario has violations."""
    response = {
        "ranking": [
            {"name": "A", "status": "success", "rank_value": -10.0, "rank_by": "factor_var_delta"},
            {"name": "B", "status": "success", "rank_value": -1.0, "rank_by": "factor_var_delta"},
            {"name": "C", "status": "success", "rank_value": -0.8, "rank_by": "factor_var_delta"},
        ],
        "scenarios": {
            "A": {"status": "success", "snapshot": {"compliance": {"risk_violation_count": 2}}},
            "B": {"status": "success", "snapshot": {"compliance": {}}},
            "C": {"status": "success", "snapshot": {"compliance": {}}},
        },
        "summary": {"succeeded": 3, "failed": 0},
        "rank_order": "asc",
        "rank_by": "factor_var_delta",
    }
    flags = generate_comparison_flags(response)
    flag_types = [f.get("type") for f in flags]
    assert "first_ranked_has_violations" in flag_types
    assert "best_has_violations" not in flag_types
```

---

## 4. Files Modified

| File | Change |
|------|--------|
| `portfolio_risk_engine/efficient_frontier.py` | Line 399: f-string with target + limit values |
| `mcp_tools/compare.py` | Lines 137-142: split `factor_var_delta` out of lower-is-better set; lines 429-435: neutral summary labels for `factor_var_delta`; lines 456-457: thread `rank_by` into `flags_input` |
| `core/comparison_flags.py` | Lines 35-57: neutral `clear_winner`→`clear_separation` wording for non-directional metrics; line 89-105: neutral `best_has_violations`→`first_ranked_has_violations` type + wording |
| `mcp_server.py` | Lines 1929-1936: docstring fix ("ranks by a selected metric" instead of "ranks by risk impact") |
| `tests/portfolio_risk_engine/test_efficient_frontier_targets.py` | Add 1 test (error message content) |
| `tests/mcp_tools/test_optimization_new_types.py` | Update 1 test (mock error string + assertion) |
| `tests/mcp_tools/test_compare_scenarios.py` | Add 8 tests (5 verdict unit + 1 integration + 2 comparison_flags unit) |

---

## 5. Risk Assessment

- **A5.3 regression risk**: Very low. The error is raised at a single site. The only downstream consumer that pattern-matches on this error string is the mock in `test_optimization_new_types.py`, which is updated in this plan. The MCP `run_optimization` tool and `compare_scenarios` tool both catch generic `Exception` and pass `str(exc)` through — they don't match on the error text.
- **A5.9 regression risk**: Low. `_build_verdict()` is only called from `compare_scenarios()` (line 407-415). The verdict string appears in the `ranking[].verdict` field of the response. No frontend component consumes this (compare is agent-only per A5.7). The agent reads the verdict as natural language, so "more systematic" / "more idiosyncratic" is more informative than "increases risk" / "improves risk".
- **Summary label change**: The `summary` dict keys change from `best`/`worst` to `most_systematic`/`most_idiosyncratic` ONLY when `rank_by="factor_var_delta"`. All other `rank_by` values are unchanged. Agent consumers that destructure `summary.best` will get `undefined` for `factor_var_delta` — this is correct behavior (the concept of "best" doesn't apply). The integration test (A5.9-6) verifies this contract.
- **Comparison flags change**: The `clear_winner` flag type becomes `clear_separation`, and `best_has_violations` becomes `first_ranked_has_violations`, both using neutral language ONLY when `rank_by="factor_var_delta"`. All other metrics are unchanged. The `is_non_directional` guard is keyed on `rank_by` from the response dict, which is already populated by `compare_scenarios()`.
- **MCP docstring change**: Purely cosmetic. No behavioral impact.
- **Sort key unchanged**: The `_ranking_sort_key` function is generic and user-controlled via `rank_order`. Not changing it avoids breaking the sort contract for other rank_by values. Users who care about factor_var_delta ranking direction can specify `rank_order="desc"`.

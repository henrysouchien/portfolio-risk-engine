# Compare A5.8: Inherited vs New Violations Plan

**Bug**: Verdict "introduces violations" is misleading when the base portfolio already has violations. Scenarios inherit these but the verdict implies the scenario caused them.
**Status**: DRAFT (v4 — addresses R1 + R2 + R3 Codex review findings)
**Type**: Bug fix — verdict accuracy in whatif snapshot + compare tool + flags
**Severity**: Medium (misleading agent output; no data corruption)

---

## 1. Root Cause

The violation counting in `WhatIfResult.get_agent_snapshot()` (line 217-296 of `core/result_objects/whatif.py`) only examines `self.scenario_metrics` checks. It never compares against `self.current_metrics` to determine which violations already existed in the base portfolio. At line 295:

```python
if total_violations > 0:
    verdict = "introduces violations"
```

The word "introduces" implies the scenario *caused* new violations, but the base portfolio may already have the same 2 risk violations + 1 proxy violation.

**Why base violations aren't available today**: The pipeline discards them at two levels:

1. **Engine layer** (`portfolio_risk_engine/portfolio_optimizer.py:961-964`): `run_what_if_scenario()` computes both `risk_base` and `beta_base` DataFrames but only returns `risk_new` and `beta_new`. The base checks are used solely for building comparison tables (`cmp_risk`, `cmp_beta`), then discarded.

2. **Scenario analysis layer** (`portfolio_risk_engine/scenario_analysis.py:200-208`): `raw_tables` dict includes `risk_new`, `beta_f_new`, `beta_p_new` but no base equivalents.

3. **Result object factory** (`core/result_objects/whatif.py:117-118`): `from_core_scenario()` creates `current_metrics` with `current_risk_checks = []` and `current_beta_checks = []` because no base check data is available.

The compare tool (`mcp_tools/compare.py:59-72`) has the same blind spot — `_total_violations()` counts from scenario compliance only. Its verdict at line 143-144 uses "has violations" (slightly better wording than "introduces"), but `_build_verdict` still treats any violations as uniformly negative.

The `whatif_flags.py` messages say "Scenario portfolio has N violation(s)" — accurate but missing context about whether these are inherited or new.

---

## 2. Design

### Approach: Thread base checks through the pipeline + compute inherited vs new at snapshot level

**Option A (chosen): Thread base risk/beta check DataFrames through `raw_tables`**

Add `risk_base`, `beta_f_base`, `beta_p_base` to `raw_tables` alongside the existing `risk_new`, `beta_f_new`, `beta_p_new`. Then `from_core_scenario()` populates `current_metrics.risk_checks` and `current_metrics.beta_checks` with real data. The snapshot builder uses these to compute base violation counts.

This is the correct approach because:
- The data already exists at line 962-964 of `portfolio_optimizer.py` — we just need to stop discarding it
- It follows the existing pattern (same DataFrame format for base and scenario)
- It enables base compliance reporting in the snapshot for other consumers, not just verdicts
- No new computation — just plumbing

**Option B (rejected): Re-derive base violations from `cmp_risk`/`cmp_beta` comparison tables**

The comparison DataFrames contain "Current" columns that show pass/fail. We could parse these. Rejected because:
- Fragile coupling to display-oriented table format
- The comparison tables may not include proxy checks
- Indirect when the source data is available upstream

**Option C (rejected): Compute base violations at `get_agent_snapshot()` from `current_metrics`**

Can't work today because `current_metrics.risk_checks` is always `[]` (see root cause). Would require the same pipeline threading as Option A anyway.

### Verdict taxonomy

Current state:
- `"introduces violations"` — any violation present (misleading)

Proposed verdicts (in priority order, evaluated before existing risk/concentration verdicts):

| Priority | Condition | Verdict |
|----------|-----------|---------|
| 1 | `new > 0 AND resolved > 0` | `"resolves N violation(s), introduces M new"` |
| 2 | `new > 0` | `"introduces N new violation(s)"` |
| 3 | `resolved > 0 AND total == 0` | `"resolves N violation(s)"` (resolves-all) |
| 4 | `resolved > 0` | `"resolves N violation(s), inherits M"` (partial resolve, rest inherited) |
| 5 | `total > 0` | `"inherits N violation(s)"` |
| 6+ | _(fall through to existing risk/concentration logic)_ | unchanged |

Where:
- `new` = `|scenario_fail_keys - base_fail_keys|` (set difference)
- `resolved` = `|base_fail_keys - scenario_fail_keys|` (set difference)
- `total` = `risk_violation_count + factor_violation_count + proxy_violation_count`

When `new == 0`, `resolved == 0`, and `total == 0`, violations do not affect the verdict — existing risk/concentration logic takes over (unchanged).

**Key correctness properties** (from Codex findings):
- Priority 1 (mixed) IS reachable because set operations allow both `new` and `resolved` to be non-empty simultaneously (finding #2)
- Priority 3 (resolves-all) IS reachable because the `resolved > 0` check is BEFORE the `total > 0` guard (finding #3)
- All verdicts use violation identity (stable keys), not just counts, so same-count-different-identity cases are handled correctly (finding #1)

### Set-based violation identity (Codex finding #1, #2)

Count-based comparison (`max(0, total - base)`) cannot distinguish inherited from replaced violations. Example: base fails `{Max Weight, Market Var}` and scenario fails `{Market Var, proxy:CUR}` — counts are both 2, so it would report "inherits 2", but actually resolves 1 (Max Weight) and introduces 1 (proxy:CUR).

**Solution**: Build a **stable violation key** for each failed check, then use set operations.

Key format by category:
- **Risk checks** (from `risk_checks` list of `{"Metric": str, "Pass": bool, ...}`):
  Key = `risk:{Metric}` — e.g. `risk:Volatility`, `risk:Max Weight`, `risk:Factor Var %`, `risk:Market Var %`, `risk:Max Industry Var %`
- **Factor beta checks** (from `beta_checks` list of `{"factor": str, "pass": bool, ...}`; note lowercase `pass`):
  Key = `factor:{factor}` — e.g. `factor:market`, `factor:momentum`, `factor:value`
- **Proxy/industry checks** (from `_*_portfolio_industry_checks` DataFrame, index = proxy ticker, column `pass`):
  Key = `proxy:{ticker}` — e.g. `proxy:SOXX`, `proxy:KCE`, `proxy:CUR:USD`

Helper function (added to `whatif.py` as a module-level utility):
```python
def _violation_keys(risk_checks: list, beta_checks: list, industry_df: pd.DataFrame | None) -> set[str]:
    """Build stable identity keys for all failed checks."""
    keys: set[str] = set()
    for check in risk_checks:
        if not check.get("Pass", True):
            keys.add(f"risk:{check.get('Metric', 'unknown')}")
    for check in beta_checks:
        if not check.get("pass", True):
            # beta_checks are dicts from DataFrame.to_dict('records');
            # the factor name is either the 'factor' key or index-based
            keys.add(f"factor:{check.get('factor', 'unknown')}")
    if industry_df is not None and not industry_df.empty and "pass" in industry_df.columns:
        for ticker in industry_df.index[~industry_df["pass"]]:
            keys.add(f"proxy:{ticker}")
    return keys
```

Then the attribution is:
```python
base_fail_keys = _violation_keys(base_risk_checks, base_beta_checks, base_industry_df)
scenario_fail_keys = _violation_keys(scenario_risk_checks, scenario_beta_checks, scenario_industry_df)

inherited_keys = base_fail_keys & scenario_fail_keys
new_keys = scenario_fail_keys - base_fail_keys
resolved_keys = base_fail_keys - scenario_fail_keys

new_violation_count = len(new_keys)
resolved_violation_count = len(resolved_keys)
inherited_violation_count = len(inherited_keys)
base_violation_count = len(base_fail_keys)
```

With set operations, `new_keys` and `resolved_keys` CAN both be non-empty simultaneously (Codex finding #2 — mixed verdict is now reachable). And when base has 3 and scenario has 0, `resolved_keys` = 3 and `scenario_fail_keys` is empty, so we hit the resolves path correctly (Codex finding #3).

### Snapshot additions

New fields in `compliance` dict (backward compatible — additive):
```python
"compliance": {
    # existing fields unchanged
    "risk_passes": ...,
    "risk_violation_count": ...,
    "factor_passes": ...,
    "factor_violation_count": ...,
    "proxy_passes": ...,
    "proxy_violation_count": ...,
    # new fields (set-based)
    "base_violation_count": 2,         # |base_fail_keys|
    "new_violation_count": 1,          # |scenario_fail_keys - base_fail_keys|
    "resolved_violation_count": 1,     # |base_fail_keys - scenario_fail_keys|
    "inherited_violation_count": 1,    # |base_fail_keys & scenario_fail_keys|
}
```

---

## 3. Implementation Steps

### Step 1: Thread base check DataFrames through the engine return

**File**: `portfolio_risk_engine/portfolio_optimizer.py`
**Function**: `run_what_if_scenario()` (line 977)

Currently returns: `summary_new, risk_new, beta_new, cmp_risk, cmp_beta`

Change to return: `summary_new, risk_new, beta_new, cmp_risk, cmp_beta, risk_base, beta_base`

`risk_base` and `beta_base` are already computed at lines 961-964. Just add them to the return tuple.

**Callers**: Only one — `analyze_scenario()` in `portfolio_risk_engine/scenario_analysis.py:170`. Update the unpacking there.

**Docstring update** (Codex finding #6): Update the `run_what_if_scenario()` docstring to document the 7-tuple return shape:
```
Returns:
    tuple: (summary_new, risk_new, beta_new, cmp_risk, cmp_beta, risk_base, beta_base)
        - summary_new: Dict — build_portfolio_view() output for scenario weights
        - risk_new: DataFrame — risk limit checks for scenario portfolio
        - beta_new: DataFrame — beta limit checks for scenario portfolio
        - cmp_risk: DataFrame — side-by-side risk comparison (base vs scenario)
        - cmp_beta: DataFrame — side-by-side beta comparison (base vs scenario)
        - risk_base: DataFrame — risk limit checks for base portfolio
        - beta_base: DataFrame — beta limit checks for base portfolio
```
Future cleanup: consider replacing the bare tuple with a `WhatIfEngineResult` NamedTuple. Out of scope for this fix (single caller, manageable size).

### Step 2: Include base checks in `raw_tables`

**File**: `portfolio_risk_engine/scenario_analysis.py`
**Function**: `analyze_scenario()` (line 170 and 200-208)

Update unpacking at line 170:
```python
summary, risk_new, beta_new, cmp_risk, cmp_beta, risk_base, beta_base = run_what_if_scenario(...)
```

Split `beta_base` into factor and industry (same pattern as lines 182-197 for `beta_new`):
```python
beta_f_base = beta_base.copy()
beta_p_base = pd.DataFrame()
if hasattr(beta_base.index, 'str') and len(beta_base) > 0:
    try:
        industry_mask = beta_base.index.str.startswith("industry_proxy::")
        beta_f_base = beta_base[~industry_mask]
        beta_p_base = beta_base[industry_mask].copy()
        if not beta_p_base.empty:
            beta_p_base.index = beta_p_base.index.str.replace("industry_proxy::", "")
    except Exception:
        beta_f_base = beta_base.copy()
        beta_p_base = pd.DataFrame()
```

Add to `raw_tables`:
```python
raw_tables = {
    # existing keys unchanged
    "summary": summary,
    "summary_base": summary_base,
    "risk_new": risk_new,
    "beta_f_new": beta_f_new,
    "beta_p_new": beta_p_new,
    "cmp_risk": cmp_risk,
    "cmp_beta": cmp_beta,
    # new keys
    "risk_base": risk_base,
    "beta_f_base": beta_f_base,
    "beta_p_base": beta_p_base,
}
```

### Step 3: Populate `current_metrics` with real base checks

**File**: `core/result_objects/whatif.py`
**Function**: `from_core_scenario()` (lines 115-133)

Replace the hardcoded empty lists:
```python
# BEFORE (lines 117-118):
current_risk_checks = []
current_beta_checks = []

# AFTER:
current_risk_checks = (
    raw_tables["risk_base"].to_dict('records')
    if "risk_base" in raw_tables and not raw_tables["risk_base"].empty
    else []
)
current_beta_checks = (
    raw_tables["beta_f_base"].reset_index().to_dict('records')
    if "beta_f_base" in raw_tables and not raw_tables["beta_f_base"].empty
    else []
)
```

**R2 fix — `reset_index()` is critical here**: The `beta_f_base` DataFrame has `factor` as its index (set by the engine at `portfolio_optimizer.py`). Plain `to_dict('records')` drops the index, so all factor failure keys would become `factor:unknown` in `_violation_keys()`. Using `reset_index().to_dict('records')` promotes the index to a regular `"factor"` column in each record dict. This matches the existing pattern at `core/portfolio_analysis.py:222` (`df_beta.reset_index().to_dict('records')`).

The same fix must be applied to the **scenario** beta checks path. Wherever `beta_f_new` is converted to `scenario_metrics.beta_checks` (currently at `from_core_scenario()` line ~140), it must also use `reset_index().to_dict('records')`. Verify this is already the case; if not, add `reset_index()` there too.

Also store `_current_portfolio_industry_checks` (parallel to existing `_new_portfolio_industry_checks` at line 168):
```python
# After line 168, add:
if "beta_p_base" in raw_tables and not raw_tables["beta_p_base"].empty:
    result._current_portfolio_industry_checks = raw_tables["beta_p_base"]
```

### Step 4: Set-based violation attribution in `get_agent_snapshot()`

**File**: `core/result_objects/whatif.py`
**Function**: `get_agent_snapshot()` (around lines 217-296)

**4a. Add `_violation_keys()` helper** (module-level, before the class):

```python
def _violation_keys(
    risk_checks: list[dict],
    beta_checks: list[dict],
    industry_df: pd.DataFrame | None,
) -> set[str]:
    """Build stable identity keys for all failed checks.

    Key taxonomy:
      risk:{Metric}      — e.g. risk:Volatility, risk:Max Weight
      factor:{factor}    — e.g. factor:market, factor:momentum
      proxy:{ticker}     — e.g. proxy:SOXX, proxy:CUR:USD
    """
    keys: set[str] = set()
    for check in risk_checks:
        if not check.get("Pass", True):
            keys.add(f"risk:{check.get('Metric', 'unknown')}")
    for check in beta_checks:
        if not check.get("pass", True):
            keys.add(f"factor:{check.get('factor', 'unknown')}")
    if industry_df is not None and not industry_df.empty and "pass" in industry_df.columns:
        for ticker in industry_df.index[~industry_df["pass"]]:
            keys.add(f"proxy:{ticker}")
    return keys
```

**4b. Compute set-based attribution** after the existing scenario violation count code (lines 221-243):

```python
# --- Set-based violation attribution ---
current_risk = self.current_metrics
base_risk_checks = getattr(current_risk, "risk_checks", None) or []
base_beta_checks = getattr(current_risk, "beta_checks", None) or []
base_industry_df = getattr(self, "_current_portfolio_industry_checks", None)

base_fail_keys = _violation_keys(base_risk_checks, base_beta_checks, base_industry_df)

# Scenario checks — reuse the already-computed lists from above
scenario_risk_checks = scenario_risk.risk_checks if has_risk_checks else []
scenario_beta_checks = scenario_risk.beta_checks if has_factor_checks else []
scenario_industry_df = getattr(self, "_new_portfolio_industry_checks", None)

scenario_fail_keys = _violation_keys(scenario_risk_checks, scenario_beta_checks, scenario_industry_df)

new_keys = scenario_fail_keys - base_fail_keys
resolved_keys = base_fail_keys - scenario_fail_keys
inherited_keys = base_fail_keys & scenario_fail_keys

new_violation_count = len(new_keys)
resolved_violation_count = len(resolved_keys)
inherited_violation_count = len(inherited_keys)
base_violation_count = len(base_fail_keys)
```

**4c. Update verdict logic** (replacing lines 293-306).

Note the ordering change vs v1 (Codex finding #3): the `resolved_violation_count > 0` check comes BEFORE the `total_violations > 0` guard, so the "resolves-all" case (base=3, scenario=0 → total=0, resolved=3) is reached correctly:

```python
total_violations = risk_violation_count + factor_violation_count + proxy_violation_count
is_marginal = abs(raw_vol_delta_pct) < 0.1 and abs(raw_conc_delta) < 0.001

# Verdict priority: mixed > introduces > resolves-all > inherits > risk/concentration
if new_violation_count > 0 and resolved_violation_count > 0:
    # Mixed: resolves some AND introduces others — both sets non-empty (finding #2)
    verdict = f"resolves {resolved_violation_count} violation(s), introduces {new_violation_count} new"
elif new_violation_count > 0:
    verdict = f"introduces {new_violation_count} new violation(s)"
elif resolved_violation_count > 0 and total_violations == 0:
    # Resolves-all: base had violations, scenario has 0 (finding #3)
    verdict = f"resolves {resolved_violation_count} violation(s)"
elif resolved_violation_count > 0:
    # Partial resolve: some resolved, rest inherited, no new
    verdict = f"resolves {resolved_violation_count} violation(s), inherits {inherited_violation_count}"
elif total_violations > 0:
    verdict = f"inherits {total_violations} violation(s)"
elif is_marginal:
    verdict = "marginal impact"
elif self.risk_improvement and self.concentration_improvement:
    verdict = "improves risk and concentration"
elif self.risk_improvement:
    verdict = "improves risk"
elif self.concentration_improvement:
    verdict = "improves concentration"
else:
    verdict = "increases risk"
```

**4d. Add new fields to the `compliance` dict** in the snapshot:
```python
"compliance": {
    # existing fields
    "risk_passes": risk_passes,
    "risk_violation_count": risk_violation_count,
    "factor_passes": factor_passes,
    "factor_violation_count": factor_violation_count,
    "proxy_passes": proxy_passes,
    "proxy_violation_count": proxy_violation_count,
    # new fields (set-based attribution)
    "base_violation_count": base_violation_count,
    "new_violation_count": new_violation_count,
    "resolved_violation_count": resolved_violation_count,
    "inherited_violation_count": inherited_violation_count,
},
```

### Step 5: Update `whatif_flags.py` messages to distinguish inherited vs new

**File**: `core/whatif_flags.py`
**Function**: `generate_whatif_flags()` (lines 22-53)

Update the three violation flag blocks to include inherited context when `base_violation_count` is available:

```python
base_violation_count = compliance.get("base_violation_count", 0)

risk_violations = compliance.get("risk_violation_count", 0)
if risk_violations > 0:
    base_risk = min(risk_violations, base_violation_count)  # approximate attribution
    if compliance.get("new_violation_count", risk_violations) == 0:
        msg = f"Scenario inherits {risk_violations} risk limit violation(s) from base portfolio"
    else:
        msg = f"Scenario has {risk_violations} risk limit violation(s)"
    flags.append({
        "type": "risk_violations",
        "severity": "warning",
        "message": msg,
        "risk_violation_count": risk_violations,
    })
```

**Simpler alternative** (preferred — keep per-category flags unchanged, add one summary flag):

Leave the three per-category flag blocks unchanged (they already say "Scenario portfolio has N violation(s)" — factually correct). Add a single summary flag when all violations are inherited:

```python
new_violation_count = compliance.get("new_violation_count")
if new_violation_count is not None and new_violation_count == 0 and total_violations > 0:
    base_count = compliance.get("base_violation_count", 0)
    flags.append({
        "type": "inherited_violations",
        "severity": "info",
        "message": f"All {total_violations} violation(s) are inherited from the base portfolio ({base_count} base violations)",
    })
elif new_violation_count is not None and new_violation_count > 0:
    flags.append({
        "type": "new_violations",
        "severity": "warning",
        "message": f"Scenario introduces {new_violation_count} new violation(s) not present in the base portfolio",
        "new_violation_count": new_violation_count,
    })
```

Add the resolved case:
```python
resolved_count = compliance.get("resolved_violation_count", 0)
if resolved_count > 0:
    flags.append({
        "type": "resolved_violations",
        "severity": "success",
        "message": f"Scenario resolves {resolved_count} violation(s) present in the base portfolio",
        "resolved_violation_count": resolved_count,
    })
```

### Step 6: Compare tool contract (Codex finding #5 — resolve internal inconsistency)

**Contract**: `mcp_tools/compare.py` reads compliance data from whatif snapshots. It does NOT compute its own violation attribution. The richer compliance fields from Step 4 flow through automatically.

**File**: `mcp_tools/compare.py`

**No changes to `_total_violations()` or `_build_verdict()` or `_extract_rank_value()`.**

- Ranking still uses `_total_violations()` which sums `risk_violation_count + factor_violation_count + proxy_violation_count` from the snapshot. This is correct — a scenario with 5 inherited violations is still worse than one with 0, regardless of inheritance.
- Per-scenario verdicts are already in each scenario's `flags` (from Step 5). The compare tool's ranking verdict is a relative label ("has violations" / "no violations"), not an attribution statement.
- The `_new_violations()` helper from v1 is **removed** — it was unused (ranking doesn't use it, verdict doesn't use it).

**File**: `core/comparison_flags.py`

**6a.** Add `_scenario_new_violations()` helper (parallel to existing `_scenario_total_violations()`):

```python
def _scenario_new_violations(scenario_payload: Any) -> int:
    """Return new (non-inherited) violations from a scenario payload."""
    if not isinstance(scenario_payload, dict):
        return 0
    snapshot = scenario_payload.get("snapshot")
    if not isinstance(snapshot, dict):
        snapshot = scenario_payload
    compliance = snapshot.get("compliance", {}) if isinstance(snapshot, dict) else {}
    if not isinstance(compliance, dict):
        return 0
    new_count = compliance.get("new_violation_count")
    if new_count is not None:
        return int(new_count)
    # Fallback: all violations are new (backward compat with pre-v2 snapshots)
    return _scenario_total_violations(scenario_payload)
```

**6b.** Update `best_has_violations` flag (line 91-106) to distinguish inherited vs new:

```python
best_total_violations = _scenario_total_violations(
    scenarios.get(best_entry["name"], {}) if isinstance(scenarios, dict) else {}
)
best_new_violations = _scenario_new_violations(
    scenarios.get(best_entry["name"], {}) if isinstance(scenarios, dict) else {}
)
if best_total_violations > 0:
    if best_new_violations == 0:
        msg = (
            f"Top-ranked scenario '{best_entry['name']}' inherits "
            f"{best_total_violations} violation(s) from the base portfolio"
        )
        severity = "info"
    else:
        msg = (
            f"Top-ranked scenario '{best_entry['name']}' has "
            f"{best_new_violations} new violation(s)"
        )
        severity = "warning"
    flags.append({
        "type": "best_has_violations",
        "severity": severity,
        "message": msg,
        "name": best_entry["name"],
        "total_violations": best_total_violations,
        "new_violations": best_new_violations,
    })
```

**6c.** Update `all_have_violations` flag (line 108-123):

```python
new_totals = [
    _scenario_new_violations(scenarios.get(name, {})) if isinstance(scenarios, dict) else 0
    for name in successful_names
]
if totals and all(total > 0 for total in totals):
    all_inherited = all(nv == 0 for nv in new_totals)
    flags.append({
        "type": "all_have_violations",
        "severity": "info" if all_inherited else "warning",
        "message": (
            "All scenarios inherit compliance violations from the base portfolio"
            if all_inherited
            else "All successful scenarios have compliance violations"
        ),
        "scenario_count": len(successful_names),
    })
```

---

## 4. Test Plan

### New tests in `tests/core/test_whatif_agent_snapshot.py`

Note: `_make_result` helper needs to accept `current_risk_checks`, `current_beta_checks`, and `current_proxy_passes` parameters to populate base checks on `current_metrics`. See Step 3 — once the pipeline threads base checks through, the test helper constructs `current_metrics` with them.

**Important**: All test checks MUST include `Metric` / `factor` keys so `_violation_keys()` can build stable identity keys. Tests that omit these keys will produce `risk:unknown` / `factor:unknown` collisions that mask real bugs.

**Test 1: Verdict "inherits" when base and scenario fail the SAME named violations**
```python
def test_agent_snapshot_verdict_inherits_violations():
    """Base fails {Max Weight, Market Var %}, scenario fails same 2 → 'inherits 2 violation(s)'."""
    base_checks = [
        {"Metric": "Volatility", "Pass": True},
        {"Metric": "Max Weight", "Pass": False},
        {"Metric": "Market Var %", "Pass": False},
    ]
    scenario_checks = [
        {"Metric": "Volatility", "Pass": True},
        {"Metric": "Max Weight", "Pass": False},
        {"Metric": "Market Var %", "Pass": False},
    ]
    result = _make_result(
        current_risk_checks=base_checks,
        risk_checks=scenario_checks,
    )
    snapshot = result.get_agent_snapshot()
    assert snapshot["verdict"] == "inherits 2 violation(s)"
    assert snapshot["compliance"]["base_violation_count"] == 2
    assert snapshot["compliance"]["new_violation_count"] == 0
    assert snapshot["compliance"]["resolved_violation_count"] == 0
    assert snapshot["compliance"]["inherited_violation_count"] == 2
```

**Test 2: Verdict "introduces" when base is clean, scenario adds 2 named violations**
```python
def test_agent_snapshot_verdict_introduces_new_violations():
    """Base passes all, scenario fails {Max Weight, Factor Var %} → 'introduces 2 new violation(s)'."""
    result = _make_result(
        current_risk_checks=[
            {"Metric": "Volatility", "Pass": True},
            {"Metric": "Max Weight", "Pass": True},
            {"Metric": "Factor Var %", "Pass": True},
        ],
        risk_checks=[
            {"Metric": "Volatility", "Pass": True},
            {"Metric": "Max Weight", "Pass": False},
            {"Metric": "Factor Var %", "Pass": False},
        ],
    )
    snapshot = result.get_agent_snapshot()
    assert snapshot["verdict"] == "introduces 2 new violation(s)"
    assert snapshot["compliance"]["new_violation_count"] == 2
```

**Test 3: Verdict "resolves" when base has 3, scenario has 0 (resolves-all, Codex finding #3)**
```python
def test_agent_snapshot_verdict_resolves_all_violations():
    """Base fails {Volatility, Max Weight, Market Var %}, scenario passes all → 'resolves 3 violation(s)'.
    Regression: count-based logic fell through because total=0 guarded the resolves path."""
    result = _make_result(
        current_risk_checks=[
            {"Metric": "Volatility", "Pass": False},
            {"Metric": "Max Weight", "Pass": False},
            {"Metric": "Market Var %", "Pass": False},
        ],
        risk_checks=[
            {"Metric": "Volatility", "Pass": True},
            {"Metric": "Max Weight", "Pass": True},
            {"Metric": "Market Var %", "Pass": True},
        ],
    )
    snapshot = result.get_agent_snapshot()
    assert snapshot["verdict"] == "resolves 3 violation(s)"
    assert snapshot["compliance"]["resolved_violation_count"] == 3
    assert snapshot["compliance"]["new_violation_count"] == 0
```

**Test 4: Mixed — same count, different identities (Codex finding #1 + #2)**
```python
def test_agent_snapshot_verdict_mixed_same_count_different_identities():
    """Base fails {Max Weight, Market Var %}, scenario fails {Market Var %, proxy:CUR:USD}.
    Count-based would report 'inherits 2' since both have 2 violations.
    Set-based correctly reports: resolves 1 (Max Weight), introduces 1 (proxy:CUR:USD)."""
    result = _make_result(
        current_risk_checks=[
            {"Metric": "Max Weight", "Pass": False},
            {"Metric": "Market Var %", "Pass": False},
        ],
        risk_checks=[
            {"Metric": "Max Weight", "Pass": True},
            {"Metric": "Market Var %", "Pass": False},
        ],
        current_proxy_passes={"CUR:USD": True},
        proxy_passes={"CUR:USD": False},
    )
    snapshot = result.get_agent_snapshot()
    assert "resolves 1 violation(s)" in snapshot["verdict"]
    assert "introduces 1 new" in snapshot["verdict"]
    assert snapshot["compliance"]["resolved_violation_count"] == 1
    assert snapshot["compliance"]["new_violation_count"] == 1
    assert snapshot["compliance"]["inherited_violation_count"] == 1  # Market Var %
```

**Test 5: Category-crossing — risk resolved, factor introduced (Codex finding #4)**
```python
def test_agent_snapshot_verdict_category_crossing():
    """Base fails risk:Volatility, scenario passes Volatility but fails factor:momentum.
    Different categories — set keys distinguish them correctly."""
    result = _make_result(
        current_risk_checks=[{"Metric": "Volatility", "Pass": False}],
        risk_checks=[{"Metric": "Volatility", "Pass": True}],
        current_beta_checks=[],
        beta_checks=[{"factor": "momentum", "pass": False}],
    )
    snapshot = result.get_agent_snapshot()
    assert "resolves 1 violation(s)" in snapshot["verdict"]
    assert "introduces 1 new" in snapshot["verdict"]
    assert snapshot["compliance"]["resolved_violation_count"] == 1
    assert snapshot["compliance"]["new_violation_count"] == 1
```

**Test 6: Backward compat — base checks empty (legacy behavior)**
```python
def test_agent_snapshot_verdict_no_base_checks_treats_all_as_new():
    """When base checks are not populated (legacy), all violations are 'new'."""
    result = _make_result(
        risk_checks=[{"Metric": "Max Weight", "Pass": False}],
    )
    # Don't set current_risk_checks → defaults to []
    snapshot = result.get_agent_snapshot()
    assert snapshot["compliance"]["base_violation_count"] == 0
    assert snapshot["compliance"]["new_violation_count"] == 1
    assert "introduces 1 new violation(s)" in snapshot["verdict"]
```

**Test 7: Compliance dict has all new fields**
```python
def test_agent_snapshot_compliance_includes_set_based_fields():
    result = _make_result(
        current_risk_checks=[{"Metric": "Max Weight", "Pass": False}],
        risk_checks=[{"Metric": "Max Weight", "Pass": False}],
    )
    compliance = result.get_agent_snapshot()["compliance"]
    assert "base_violation_count" in compliance
    assert "new_violation_count" in compliance
    assert "resolved_violation_count" in compliance
    assert "inherited_violation_count" in compliance
```

**Test 8: Partial inherit + partial resolve + no new**
```python
def test_agent_snapshot_verdict_partial_resolve_no_new():
    """Base fails {Volatility, Max Weight, Market Var %}, scenario fails {Volatility}.
    Resolves 2 (Max Weight, Market Var %), inherits 1 (Volatility), introduces 0."""
    result = _make_result(
        current_risk_checks=[
            {"Metric": "Volatility", "Pass": False},
            {"Metric": "Max Weight", "Pass": False},
            {"Metric": "Market Var %", "Pass": False},
        ],
        risk_checks=[
            {"Metric": "Volatility", "Pass": False},
            {"Metric": "Max Weight", "Pass": True},
            {"Metric": "Market Var %", "Pass": True},
        ],
    )
    snapshot = result.get_agent_snapshot()
    assert snapshot["verdict"] == "resolves 2 violation(s), inherits 1"
    assert "introduces" not in snapshot["verdict"]  # no new violations
    assert snapshot["compliance"]["resolved_violation_count"] == 2
    assert snapshot["compliance"]["inherited_violation_count"] == 1
    assert snapshot["compliance"]["new_violation_count"] == 0
```

### Unit test for `_violation_keys()` helper

**Test 9: Stable key generation across all categories**
```python
def test_violation_keys_builds_correct_taxonomy():
    from core.result_objects.whatif import _violation_keys
    import pandas as pd

    risk_checks = [
        {"Metric": "Volatility", "Pass": True},
        {"Metric": "Max Weight", "Pass": False},
    ]
    beta_checks = [
        {"factor": "market", "pass": True},
        {"factor": "momentum", "pass": False},
    ]
    industry_df = pd.DataFrame(
        {"pass": [True, False]}, index=["SOXX", "CUR:USD"]
    )

    keys = _violation_keys(risk_checks, beta_checks, industry_df)
    assert keys == {"risk:Max Weight", "factor:momentum", "proxy:CUR:USD"}
```

**Test 9b: Factor beta keys survive DataFrame index→records conversion (R2 regression guard)**

R3 finding: The original test called `WhatIfResult.from_core_scenario(raw_tables=raw_tables, ...)` but the actual factory signature is `from_core_scenario(scenario_result, scenario_name=...)` — the test was not runnable as written. Additionally, passing `summary={}`/`summary_base={}` would fail inside `RiskAnalysisResult.from_core_analysis()`.

**Fix**: Test `_violation_keys()` directly with DataFrame-derived inputs. This is simpler, still proves the `reset_index()` fix works, and avoids coupling to the full `from_core_scenario()` construction contract.

```python
def test_violation_keys_from_real_dataframe_preserves_factor():
    """R2 finding: beta DataFrames have 'factor' as the index.
    Plain to_dict('records') drops it → all keys become 'factor:unknown'.
    This test builds actual DataFrames (as the engine produces them),
    converts via reset_index().to_dict('records'), and passes the records
    to _violation_keys() — proving the conversion preserves factor names."""
    from core.result_objects.whatif import _violation_keys
    import pandas as pd

    # Simulate engine output: beta DataFrame with factor as index
    beta_f_base = pd.DataFrame(
        {"beta": [1.05, 0.3, -0.1], "limit": [1.5, 0.5, 0.5], "pass": [True, True, False]},
        index=pd.Index(["market", "momentum", "value"], name="factor"),
    )
    beta_f_new = pd.DataFrame(
        {"beta": [1.05, 0.6, 0.0], "limit": [1.5, 0.5, 0.5], "pass": [True, False, True]},
        index=pd.Index(["market", "momentum", "value"], name="factor"),
    )

    # Convert as from_core_scenario() should: reset_index() promotes factor to column
    base_beta_records = beta_f_base.reset_index().to_dict("records")
    new_beta_records = beta_f_new.reset_index().to_dict("records")

    base_keys = _violation_keys([], base_beta_records, None)
    new_keys = _violation_keys([], new_beta_records, None)

    # Base fails value, scenario fails momentum
    assert base_keys == {"factor:value"}
    assert new_keys == {"factor:momentum"}

    # Set operations prove correct attribution
    resolved = base_keys - new_keys
    introduced = new_keys - base_keys
    inherited = base_keys & new_keys

    assert resolved == {"factor:value"}
    assert introduced == {"factor:momentum"}
    assert inherited == set()

    # Counter-proof: WITHOUT reset_index(), both would produce 'factor:unknown'
    bad_base_records = beta_f_base.to_dict("records")  # no reset_index
    bad_new_records = beta_f_new.to_dict("records")
    bad_base_keys = _violation_keys([], bad_base_records, None)
    bad_new_keys = _violation_keys([], bad_new_records, None)
    # Both produce the same degenerate key → inherited=1, resolved=0, introduced=0
    assert bad_base_keys == {"factor:unknown"}
    assert bad_new_keys == {"factor:unknown"}
```

Note: This test MUST use actual `pd.DataFrame` objects with `factor` as the index name, NOT pre-built dicts. The counter-proof at the end demonstrates exactly what goes wrong without `reset_index()`: both DataFrames collapse to the same `factor:unknown` key, making resolved/introduced detection impossible.

### New tests in `tests/core/test_whatif_flags.py`

**Test 10: Inherited violations flag**
```python
def test_inherited_violations_flag():
    snapshot = _base_snapshot()
    snapshot["compliance"]["risk_violation_count"] = 2
    snapshot["compliance"]["base_violation_count"] = 2
    snapshot["compliance"]["new_violation_count"] = 0
    flags = generate_whatif_flags(snapshot)
    assert "inherited_violations" in _flag_types(flags)
```

**Test 11: New violations flag**
```python
def test_new_violations_flag():
    snapshot = _base_snapshot()
    snapshot["compliance"]["risk_violation_count"] = 2
    snapshot["compliance"]["base_violation_count"] = 0
    snapshot["compliance"]["new_violation_count"] = 2
    flags = generate_whatif_flags(snapshot)
    assert "new_violations" in _flag_types(flags)
```

**Test 12: Resolved violations flag**
```python
def test_resolved_violations_flag():
    snapshot = _base_snapshot()
    snapshot["compliance"]["resolved_violation_count"] = 2
    flags = generate_whatif_flags(snapshot)
    assert "resolved_violations" in _flag_types(flags)
```

### New tests in `tests/core/test_comparison_flags.py`

**Test 13: `best_has_violations` downgraded to info when all inherited**
```python
def test_best_has_violations_inherited_is_info():
    response = _response(rank_values=[1.0, 2.0], violation_names={"A"})
    # Patch scenario A's snapshot to have new_violation_count=0
    response["scenarios"]["A"]["snapshot"]["compliance"]["new_violation_count"] = 0
    response["scenarios"]["A"]["snapshot"]["compliance"]["base_violation_count"] = 1
    flags = generate_comparison_flags(response)
    best_flag = next(f for f in flags if f["type"] == "best_has_violations")
    assert best_flag["severity"] == "info"
```

**Test 14: `all_have_violations` when all inherited**
```python
def test_all_have_violations_inherited_is_info():
    response = _response(rank_values=[1.0, 2.0], violation_names={"A", "B"})
    for name in ("A", "B"):
        response["scenarios"][name]["snapshot"]["compliance"]["new_violation_count"] = 0
        response["scenarios"][name]["snapshot"]["compliance"]["base_violation_count"] = 1
    flags = generate_comparison_flags(response)
    all_flag = next(f for f in flags if f["type"] == "all_have_violations")
    assert all_flag["severity"] == "info"
    assert "inherit" in all_flag["message"]
```

### Regression: existing tests must still pass

- `tests/core/test_whatif_agent_snapshot.py` — 20 existing tests. Key: `test_agent_snapshot_verdict_introduces_violations` (line 139) and `test_agent_snapshot_verdict_proxy_only_violations` (line 146) currently assert `verdict == "introduces violations"`. These must be updated:
  - Both use `_make_result` with `risk_checks` on scenario but no base checks → `base_fail_keys = {}`, so all scenario violations are "new". Verdict becomes `"introduces N new violation(s)"`.
  - **Important**: existing test `_make_result` calls may not include `Metric`/`factor` keys on check dicts. The implementation must add them, or `_violation_keys()` will produce `risk:unknown` keys. Either (a) update existing test data to include `Metric` fields, or (b) ensure `_make_result` helper generates synthetic metric names when not provided.
- `tests/core/test_whatif_flags.py` — 18 existing tests. Unchanged behavior since flags don't depend on base counts (new flags are additive).
- `tests/core/test_comparison_flags.py` — 9 existing tests. `test_best_has_violations_flag` and `test_all_have_violations_flag` still pass because `new_violation_count` is absent from old-format test data, triggering the fallback path in `_scenario_new_violations()`.
- `tests/mcp_tools/test_compare_scenarios.py` — integration tests. Must still pass (additive snapshot fields).

### Updated existing test assertions

```python
# test_agent_snapshot_verdict_introduces_violations (line 139-143):
# OLD: assert snapshot["verdict"] == "introduces violations"
# NEW: assert snapshot["verdict"] == "introduces 1 new violation(s)"
# Also update the test's risk_checks to include Metric field:
#   {"Pass": False} → {"Metric": "Volatility", "Pass": False}

# test_agent_snapshot_verdict_proxy_only_violations (line 146-154):
# OLD: assert snapshot["verdict"] == "introduces violations"
# NEW: assert snapshot["verdict"] == "introduces 1 new violation(s)"
```

---

## 5. Files Modified

| File | Change |
|------|--------|
| `portfolio_risk_engine/portfolio_optimizer.py` | Return `risk_base, beta_base` from `run_what_if_scenario()` (5-tuple → 7-tuple); update docstring to document return shape |
| `portfolio_risk_engine/scenario_analysis.py` | Unpack + split + include base check DataFrames in `raw_tables` |
| `core/result_objects/whatif.py` | Populate `current_metrics` with real base checks; add `_violation_keys()` helper; set-based attribution (`new_violation_count`, `resolved_violation_count`, `inherited_violation_count`, `base_violation_count`); update verdict logic with correct priority ordering |
| `core/whatif_flags.py` | Add `inherited_violations`, `new_violations`, `resolved_violations` summary flags |
| `core/comparison_flags.py` | Add `_scenario_new_violations()` helper; update `best_has_violations` and `all_have_violations` flag severity/message |
| `mcp_tools/compare.py` | No changes — reads richer compliance fields from snapshots automatically; ranking uses `_total_violations()` unchanged; per-scenario attribution is in each scenario's flags from whatif_flags.py |
| `tests/core/test_whatif_agent_snapshot.py` | 10 new tests (including `_violation_keys` unit test + DataFrame index regression guard) + update 2 existing assertions |
| `tests/core/test_whatif_flags.py` | 3 new tests |
| `tests/core/test_comparison_flags.py` | 2 new tests |

---

## 6. Risks

| Dimension | Assessment |
|-----------|------------|
| **Blast radius** | Engine return signature change affects 1 caller (`analyze_scenario`). All downstream snapshot changes are additive fields. See "Return signature" row below for mitigation. |
| **Backward compat** | New compliance fields are additive. Existing consumers that don't read `base_violation_count` / `new_violation_count` / `resolved_violation_count` are unaffected. Fallback behavior when base checks are absent (empty list) treats all violations as new — matches current behavior exactly. |
| **Verdict string changes** | Two existing verdicts change: `"introduces violations"` becomes `"introduces N new violation(s)"` or `"inherits N violation(s)"`. Any downstream code that matches on the exact string `"introduces violations"` will need updating. Grep for this string to confirm callsites. |
| **Performance** | Zero. Base risk/beta checks are already computed in `run_what_if_scenario()` — we just stop discarding them. No new computation. |
| **Compare tool ranking** | Ranking still uses `total_violations` (inherited + new). This is correct — a scenario with 5 inherited violations is worse than one with 0, regardless of inheritance. |
| **Return signature** (Codex finding #6) | `run_what_if_scenario()` is currently a 5-tuple return (`summary_new, risk_new, beta_new, cmp_risk, cmp_beta`). Adding `risk_base, beta_base` makes it a 7-tuple. **Mitigation**: (1) Only 1 caller (`analyze_scenario`), confirmed via grep. (2) Update the docstring to document the new return shape. (3) Future cleanup (out of scope): consider returning a `WhatIfEngineResult` NamedTuple/dataclass instead of a bare tuple. Not blocking this fix — the 7-tuple is still manageable and the single-caller blast radius is minimal. |
| **Beta DataFrame index dropping** (R2 finding #1) | **HIGH**. `beta_f_base` and `beta_f_new` DataFrames have `factor` as the index. Plain `to_dict('records')` silently drops it, causing all factor failures to key as `factor:unknown`. **Mitigation**: Use `reset_index().to_dict('records')` at conversion sites in `from_core_scenario()`. Matches existing pattern at `core/portfolio_analysis.py:222`. Test 9b is a targeted regression guard — it builds real DataFrames with factor-as-index and fails if `reset_index()` is omitted. |
| **Test helper changes** | `_make_result()` in test file needs new optional params for base checks. Existing test calls don't pass these params, so they get empty base checks (backward compat: base_violation_count=0, all violations are "new"). Existing check dicts should be updated to include `Metric`/`factor` keys to avoid `_violation_keys()` producing `unknown` collisions. Test 9b uses actual DataFrames (not hand-built dicts) to cover the conversion path that hand-built tests miss (R2 finding #2). |

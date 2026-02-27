# Plan: Agent-Optimized What-If Analysis Output

_Created: 2026-02-25_
_Status: **COMPLETE** (5 Codex review rounds, 64 new tests, live-tested)_
_Reference: `OPTIMIZATION_AGENT_FORMAT_PLAN.md`, `STOCK_ANALYSIS_AGENT_FORMAT_PLAN.md` (same three-layer pattern)_

## Context

`run_whatif` compares a proposed portfolio allocation (via `target_weights` or `delta_changes`) against the current portfolio, producing before/after risk metrics, compliance checks, and factor exposure deltas. The current `format="summary"` returns volatility/concentration/factor deltas and improvement booleans but no single decision verdict or trade-off interpretation. The agent can't answer "is this scenario worth doing?" in one phrase.

Goal: Apply the same `format="agent"` + `output="file"` pattern.

## Current State

### Output formats

| Format | Size | What agent gets |
|--------|------|-----------------|
| `summary` | ~1-3KB | volatility_change, concentration_change, factor_variance_change (each with current/scenario/delta), risk_improvement, concentration_improvement, factor_exposures. No interpretation. |
| `full` | ~10-30KB | Everything: risk_analysis, beta_analysis, comparison_analysis, position_changes, all check tables, formatted_report. Too much. |
| `report` | ~3-8KB | Human-readable CLI text. Good for display, not for agent reasoning. |

### What the agent actually needs

1. **Verdict** — Is this scenario better or worse? One phrase.
2. **Risk deltas** — Volatility, concentration, factor variance changes (as percentages).
3. **Compliance status** — Scenario portfolio passes risk/factor/proxy checks?
4. **Top position changes** — What moves the most and by how much.
5. **Factor exposure deltas** — Key factor beta changes.
6. **Flags** — Risk improved, concentration worsened, violations introduced, marginal change.

### What the agent does NOT need in-context

- Full risk_analysis/beta_analysis sections with all checks
- Complete comparison DataFrames
- Position changes for every ticker
- Formatted CLI report text
- Raw risk_checks and beta_checks lists

These belong in the file output for deep dives.

## Proposed Design

### Layer 1: Data accessor (on `WhatIfResult` in `core/result_objects.py`)

New `get_agent_snapshot()` method.

```python
def get_agent_snapshot(self) -> dict:
    """Compact metrics for agent consumption."""
    # Risk deltas (as percentages for readability)
    vol_current_pct = round(self.current_metrics.volatility_annual * 100, 2)
    vol_scenario_pct = round(self.scenario_metrics.volatility_annual * 100, 2)
    vol_delta_pct = round(self.volatility_delta * 100, 2)

    conc_current = round(self.current_metrics.herfindahl, 4)
    conc_scenario = round(self.scenario_metrics.herfindahl, 4)
    conc_delta = round(self.concentration_delta, 4)

    # factor_pct is 0-1 (e.g., 0.72 = 72%), multiply by 100 for readability
    factor_var_current = round(
        self.current_metrics.variance_decomposition.get('factor_pct', 0) * 100, 2)
    factor_var_scenario = round(
        self.scenario_metrics.variance_decomposition.get('factor_pct', 0) * 100, 2)
    factor_var_delta = round(self.factor_variance_delta * 100, 2)

    # Scenario compliance (derived from raw risk_checks and beta_checks lists)
    scenario_risk = self.scenario_metrics
    has_risk_checks = bool(scenario_risk.risk_checks)
    has_factor_checks = bool(scenario_risk.beta_checks)

    if has_risk_checks:
        risk_fails = [c for c in scenario_risk.risk_checks if not c.get("Pass", True)]
        risk_passes = len(risk_fails) == 0
        risk_violation_count = len(risk_fails)
    else:
        risk_passes = None
        risk_violation_count = 0

    if has_factor_checks:
        factor_fails = [c for c in scenario_risk.beta_checks if not c.get("pass", True)]
        factor_passes = len(factor_fails) == 0
        factor_violation_count = len(factor_fails)
    else:
        factor_passes = None
        factor_violation_count = 0

    # Proxy checks (from _new_portfolio_industry_checks if available)
    proxy_passes = None
    proxy_violation_count = 0
    if hasattr(self, '_new_portfolio_industry_checks'):
        industry_df = self._new_portfolio_industry_checks
        if not industry_df.empty and "pass" in industry_df.columns:
            proxy_passes = bool(industry_df["pass"].all())
            proxy_violation_count = int((~industry_df["pass"]).sum())

    # Top position changes (compute from raw weights to avoid rounding issues)
    # Output format: {"position": "AAPL", "before": "15.0%", "after": "5.0%", "change": "-10.0%"}
    position_changes = []
    try:
        if not hasattr(self, '_scenario_metadata') or not self._scenario_metadata.get("base_weights"):
            raise ValueError("No baseline weights available")
        base_weights = self._scenario_metadata.get("base_weights", {})
        scenario_weights = getattr(self.scenario_metrics, 'portfolio_weights', None) or {}
        all_tickers = set(base_weights.keys()) | set(scenario_weights.keys())
        parsed = []
        for ticker in all_tickers:
            before = base_weights.get(ticker, 0.0)
            after = scenario_weights.get(ticker, 0.0)
            change = after - before
            if abs(change) >= 0.005:
                parsed.append({
                    "position": ticker,
                    "before": f"{before:.1%}",
                    "after": f"{after:.1%}",
                    "change": f"{change:+.1%}",
                    "_abs_change": abs(change),
                })
        parsed.sort(key=lambda x: (-x["_abs_change"], x["position"]))
        for p in parsed:
            del p["_abs_change"]
        position_changes = parsed[:5]
    except Exception:
        pass

    # Factor exposure deltas (top 3 by abs delta)
    factor_deltas = {}
    try:
        factor_comparison = self.get_factor_exposures_comparison()
        sorted_factors = sorted(
            factor_comparison.items(),
            key=lambda x: (-abs(x[1].get("delta", 0)), x[0]),
        )
        for factor, vals in sorted_factors[:3]:
            factor_deltas[factor] = {
                "current": vals.get("current", 0),
                "scenario": vals.get("scenario", 0),
                "delta": vals.get("delta", 0),
            }
    except Exception:
        pass

    # Verdict (use raw deltas for thresholds to avoid rounding artifacts)
    raw_vol_delta_pct = self.volatility_delta * 100  # unrounded
    raw_conc_delta = self.concentration_delta  # unrounded
    total_violations = risk_violation_count + factor_violation_count + proxy_violation_count
    is_marginal = abs(raw_vol_delta_pct) < 0.1 and abs(raw_conc_delta) < 0.001
    if total_violations > 0:
        verdict = "introduces violations"
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

    snapshot = {
        "verdict": verdict,
        "is_marginal": is_marginal,  # for flags to consume
        # Raw deltas for flags (avoid rounding artifacts at thresholds)
        "_raw_vol_delta_pct": raw_vol_delta_pct,
        "_raw_conc_delta": raw_conc_delta,
        "scenario_name": self.scenario_name,
        "risk_deltas": {
            "volatility_annual_pct": {
                "current": vol_current_pct,
                "scenario": vol_scenario_pct,
                "delta": vol_delta_pct,
            },
            "herfindahl": {
                "current": conc_current,
                "scenario": conc_scenario,
                "delta": conc_delta,
            },
            "factor_variance_pct": {
                "current": factor_var_current,
                "scenario": factor_var_scenario,
                "delta": factor_var_delta,
            },
        },
        "improvements": {
            "risk": self.risk_improvement,
            "concentration": self.concentration_improvement,
        },
        "compliance": {
            "risk_passes": risk_passes,
            "risk_violation_count": risk_violation_count,
            "factor_passes": factor_passes,
            "factor_violation_count": factor_violation_count,
            "proxy_passes": proxy_passes,
            "proxy_violation_count": proxy_violation_count,
        },
        "top_position_changes": position_changes,
        "top_factor_deltas": factor_deltas,
    }

    return snapshot
```

### Layer 2: Flag rules (new — `core/whatif_flags.py`)

```python
def generate_whatif_flags(snapshot: dict) -> list[dict]:
    """
    Generate actionable flags from what-if snapshot.

    Input: dict from WhatIfResult.get_agent_snapshot()
    """
    if not snapshot:
        return []

    flags = []
    compliance = snapshot.get("compliance", {})
    improvements = snapshot.get("improvements", {})
    risk_deltas = snapshot.get("risk_deltas", {})
    vol = risk_deltas.get("volatility_annual_pct", {})
    conc = risk_deltas.get("herfindahl", {})

    # --- Compliance flags ---

    risk_violations = compliance.get("risk_violation_count", 0)
    if risk_violations > 0:
        flags.append({
            "type": "risk_violations",
            "severity": "warning",
            "message": f"Scenario portfolio has {risk_violations} risk limit violation(s)",
            "risk_violation_count": risk_violations,
        })

    factor_violations = compliance.get("factor_violation_count", 0)
    if factor_violations > 0:
        flags.append({
            "type": "factor_violations",
            "severity": "warning",
            "message": f"Scenario portfolio has {factor_violations} factor beta violation(s)",
            "factor_violation_count": factor_violations,
        })

    proxy_violations = compliance.get("proxy_violation_count", 0)
    if proxy_violations > 0:
        flags.append({
            "type": "proxy_violations",
            "severity": "warning",
            "message": f"Scenario portfolio has {proxy_violations} proxy constraint violation(s)",
            "proxy_violation_count": proxy_violations,
        })

    # --- Risk impact flags (use raw deltas to avoid rounding artifacts) ---

    vol_delta = snapshot.get("_raw_vol_delta_pct", vol.get("delta", 0))
    if vol_delta > 2.0:
        flags.append({
            "type": "volatility_increase",
            "severity": "warning",
            "message": f"Scenario increases annual volatility by {vol_delta:+.2f}pp",
            "vol_delta_pct": vol_delta,
        })
    elif vol_delta < -2.0:
        flags.append({
            "type": "volatility_decrease",
            "severity": "success",
            "message": f"Scenario reduces annual volatility by {abs(vol_delta):.2f}pp",
            "vol_delta_pct": vol_delta,
        })

    conc_delta = snapshot.get("_raw_conc_delta", conc.get("delta", 0))
    if conc_delta > 0.02:
        flags.append({
            "type": "concentration_increase",
            "severity": "info",
            "message": f"Scenario increases portfolio concentration (HHI delta: {conc_delta:+.4f})",
            "hhi_delta": conc_delta,
        })

    # --- Marginal change flag (uses precomputed is_marginal from raw deltas) ---

    total_violations = (compliance.get("risk_violation_count", 0)
                        + compliance.get("factor_violation_count", 0)
                        + compliance.get("proxy_violation_count", 0))
    is_marginal = snapshot.get("is_marginal", False)
    if is_marginal and total_violations == 0:
        flags.append({
            "type": "marginal_impact",
            "severity": "info",
            "message": "Scenario has negligible impact on volatility and concentration",
        })

    # --- Positive signals (suppressed when marginal or violations present) ---
    if (improvements.get("risk") and improvements.get("concentration")
            and not is_marginal and total_violations == 0):
        flags.append({
            "type": "overall_improvement",
            "severity": "success",
            "message": "Scenario improves both risk and concentration with no violations",
        })

    # Sort: warnings first, then info, then success
    severity_order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    flags.sort(key=lambda f: severity_order.get(f.get("severity"), 9))

    return flags
```

### Threshold constants

| Rule | Threshold | Rationale |
|------|-----------|-----------|
| Risk violations | > 0 violations | Scenario breaks constraints |
| Factor violations | > 0 violations | Factor betas exceed limits |
| Proxy violations | > 0 violations | Proxy constraints not met |
| Volatility increase | > 2.0pp increase | Significant risk increase |
| Volatility decrease | > 2.0pp decrease | Significant risk reduction |
| Concentration increase | HHI delta > 0.02 | Noticeable concentration shift |
| Marginal impact | abs(vol_delta_pp) < 0.1 AND abs(HHI_delta) < 0.001 | Change is negligible |
| Overall improvement | risk+concentration improve + 0 violations + not marginal | Clearly beneficial scenario |

### Layer 3: Agent format composer (in `mcp_tools/whatif.py`)

```python
from core.result_objects import WhatIfResult
from pathlib import Path

_WHATIF_OUTPUT_DIR = Path("logs/whatif")


def _build_agent_response(
    result: WhatIfResult,
    file_path: str | None = None,
) -> dict:
    """Compose decision-oriented what-if result for agent use."""
    from core.whatif_flags import generate_whatif_flags

    snapshot = result.get_agent_snapshot()
    flags = generate_whatif_flags(snapshot)

    # Strip internal raw fields (prefixed with _) before returning
    clean_snapshot = {k: v for k, v in snapshot.items() if not k.startswith("_")}

    return {
        "status": "success",
        "format": "agent",
        "snapshot": clean_snapshot,
        "flags": flags,
        "file_path": file_path,
    }
```

### File output

When `output="file"`:

1. Run what-if analysis as normal
2. Write full payload to `logs/whatif/whatif_{YYYYMMDD}_{HHMMSS}.json`
3. Attach `file_path` to whatever format response is returned

```python
def _save_full_whatif(result: WhatIfResult) -> str:
    """Save full what-if data to disk and return absolute path."""
    output_dir = _WHATIF_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    file_path = output_dir / f"whatif_{timestamp}.json"

    try:
        payload = result.to_api_response()
    except Exception:
        # Fallback if tables lack expected columns
        payload = {
            "scenario_name": result.scenario_name,
            "risk_improvement": result.risk_improvement,
            "concentration_improvement": result.concentration_improvement,
        }
    payload["status"] = "success"

    with file_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)

    return str(file_path.resolve())
```

## Files to Modify

### 1. Modify: `core/result_objects.py`

**Add `get_agent_snapshot()` to `WhatIfResult`:**
- Returns compact dict: verdict, is_marginal, scenario_name, risk_deltas, improvements, compliance, top_position_changes, top_factor_deltas (plus internal `_raw_*` fields stripped by Layer 3)
- Verdict derived from violations + improvements + delta magnitude
- Risk deltas as percentages for readability
- Compliance from scenario_metrics (the proposed portfolio)
- Proxy compliance from `_new_portfolio_industry_checks` DataFrame
- Position changes computed from raw weights (`_scenario_metadata["base_weights"]` vs `scenario_metrics.portfolio_weights`), filtered to >= 50bps, sorted by abs change, top 5, formatted in getter-compatible shape
- Factor deltas from existing `get_factor_exposures_comparison()`, top 3 by abs delta

### 2. New: `core/whatif_flags.py`

- `generate_whatif_flags(snapshot) -> list[dict]`
- All flag rules from the threshold table
- Accepts snapshot dict (decoupled from result object)
- Sorted by severity

### 3. Modify: `mcp_tools/whatif.py`

**Add `_build_agent_response(result, file_path)`:**
- Calls `get_agent_snapshot()` and `generate_whatif_flags()`

**Add `_save_full_whatif(result)`:**
- Writes `to_api_response()` to `_WHATIF_OUTPUT_DIR`
- try/except fallback for broken tables

**Update `run_whatif()` signature:**
- Add `format="agent"` to the Literal enum
- Add `output: Literal["inline", "file"] = "inline"` parameter
- File write happens BEFORE format dispatch
- Wrap `format="full"` dispatch in try/except with same minimal fallback

### 4. Modify: `mcp_server.py`

- Add "agent" to the format enum for run_whatif
- Add output parameter
- Pass through to underlying function

## Agent format example output

```json
{
  "status": "success",
  "format": "agent",

  "snapshot": {
    "verdict": "improves risk and concentration",
    "is_marginal": false,
    "scenario_name": "Reduce TSLA, Add SGOV",
    "risk_deltas": {
      "volatility_annual_pct": {
        "current": 22.50,
        "scenario": 18.30,
        "delta": -4.20
      },
      "herfindahl": {
        "current": 0.0920,
        "scenario": 0.0850,
        "delta": -0.0070
      },
      "factor_variance_pct": {
        "current": 85.20,
        "scenario": 82.10,
        "delta": -3.10
      }
    },
    "improvements": {
      "risk": true,
      "concentration": true
    },
    "compliance": {
      "risk_passes": true,
      "risk_violation_count": 0,
      "factor_passes": true,
      "factor_violation_count": 0,
      "proxy_passes": null,
      "proxy_violation_count": 0
    },
    "top_position_changes": [
      {"position": "SGOV", "before": "5.0%", "after": "15.0%", "change": "+10.0%"},
      {"position": "TSLA", "before": "15.0%", "after": "5.0%", "change": "-10.0%"}
    ],
    "top_factor_deltas": {
      "MKT": {"current": 1.050, "scenario": 0.850, "delta": -0.200},
      "SMB": {"current": -0.120, "scenario": -0.080, "delta": 0.040}
    }
  },

  "flags": [
    {
      "type": "volatility_decrease",
      "severity": "success",
      "message": "Scenario reduces annual volatility by 4.20pp",
      "vol_delta_pct": -4.20
    },
    {
      "type": "overall_improvement",
      "severity": "success",
      "message": "Scenario improves both risk and concentration with no violations"
    }
  ],

  "file_path": null
}
```

### What each section answers for the agent:

| Section | Agent question |
|---------|---------------|
| `snapshot.verdict` | "Is this scenario better or worse?" |
| `snapshot.scenario_name` | "What scenario was analyzed?" |
| `snapshot.risk_deltas` | "How do risk metrics change?" |
| `snapshot.improvements` | "Does risk/concentration improve?" |
| `snapshot.compliance` | "Does the scenario portfolio meet constraints?" |
| `snapshot.top_position_changes` | "What positions change the most?" |
| `snapshot.top_factor_deltas` | "How do factor exposures shift?" |
| `flags` | "What deserves attention?" |
| `file_path` | "Where's the full analysis for deep dives?" |

## Compatibility

- All existing formats (`full`, `summary`, `report`) success-path unchanged; `full` error-path now degrades gracefully with fallback
- `format="agent"` is purely additive
- `output="file"` works with any format
- Default format stays `"summary"` (no breaking change)
- `output` defaults to `"inline"` (no breaking change)

## Decisions

1. **Snapshot nested under `"snapshot"` key.** Consistent with all other agent formats.
2. **Verdict is improvement-oriented.** "improves risk and concentration" / "improves risk" / "improves concentration" / "marginal impact" / "increases risk" / "introduces violations". Tells the agent whether to recommend the scenario.
3. **Risk deltas as percentages.** Volatility is `* 100` for readability (e.g., 22.50% not 0.225). HHI stays as decimal (0-1 scale). Factor variance `factor_pct` is 0-1 (e.g., 0.72 = 72%), multiplied by 100 for the snapshot.
4. **Compliance derived from raw check lists.** `RiskAnalysisResult` has `risk_checks` (list with `"Pass"` capital P) and `beta_checks` (list with `"pass"` lowercase). Compliance is derived by counting failures, not from computed attributes. Proxy compliance from `_new_portfolio_industry_checks` DataFrame.
5. **Proxy compliance from `_new_portfolio_industry_checks`.** This DataFrame has a `"pass"` column (lowercase). It's set via `from_core_scenario()` as a private attribute.
6. **Position changes computed from raw weights.** Uses `_scenario_metadata["base_weights"]` and `scenario_metrics.portfolio_weights` to compute changes with true 50bps filtering. Formatted in getter-compatible shape (`position`, `before`, `after`, `change`).
7. **Factor deltas from existing getter.** `get_factor_exposures_comparison()` returns `{factor: {current, scenario, delta}}`. Top 3 by abs delta.
8. **Marginal impact threshold.** vol < 0.1pp AND HHI < 0.001. These are tiny changes that don't warrant action.
9. **Overall improvement flag requires 0 violations.** Don't signal "overall improvement" if the scenario breaks constraints.
10. **File save has fallback.** If `to_api_response()` fails, falls back to minimal scenario name + improvements payload.
11. **`format="full"` uses same fallback pattern.** Wraps `to_api_response()` in try/except with same minimal fallback as file save.
12. **Empty snapshot early return.** `generate_whatif_flags({})` returns `[]`.
13. **Marginal check before improvement in verdict.** Prevents contradictory signals (e.g., "improves risk" when the delta is 0.01pp). Also suppresses `overall_improvement` flag when marginal.
14. **"increases risk" is catch-all verdict.** When not marginal and neither risk nor concentration improves, verdict is "increases risk". The agent can read `risk_deltas` for nuance (e.g., concentration worsens but volatility is flat). Adding more verdict variants would complicate without adding value.
15. **Positive verdicts don't require compliance_known.** Unlike optimization, what-if verdicts are about risk impact (volatility, concentration). Violations already gate the top verdict. An improvement can be real even without compliance checks available.
16. **Position changes computed from raw weights.** Avoids rounding issues from `get_position_changes_table()` which formats to 1 decimal percent. Raw `abs(change) >= 0.005` matches true 50bps.
17. **Verdict thresholds use raw (unrounded) deltas.** `self.volatility_delta * 100` and `self.concentration_delta` are used directly, not the rounded `vol_delta_pct`/`conc_delta` snapshot fields. Prevents rounding artifacts at threshold boundaries.
18. **Internal `_raw_*` fields stripped before API return.** `get_agent_snapshot()` includes `_raw_vol_delta_pct` and `_raw_conc_delta` for flags to use with exact thresholds. The Layer 3 composer strips keys prefixed with `_` before returning to the agent.
19. **Marginal thresholds use strict `<` (not `<=`).** `vol < 0.1pp` and `HHI < 0.001` are strict. At exactly 0.1pp or 0.001, the scenario is not considered marginal. The format is `{"position": "AAPL", "before": "15.0%", "after": "5.0%", "change": "-10.0%"}` (lowercase keys). Sorted by abs change descending, filtered to >= 50bps, top 5.

## Test Plan

### `core/result_objects.py` — get_agent_snapshot tests

- `test_agent_snapshot_keys` — all expected top-level keys present (verdict, is_marginal, scenario_name, risk_deltas, improvements, compliance, top_position_changes, top_factor_deltas)
- `test_agent_snapshot_verdict_improves_risk` — volatility decreases → "improves risk"
- `test_agent_snapshot_verdict_improves_both` — risk + concentration improve → "improves risk and concentration"
- `test_agent_snapshot_verdict_improves_concentration` — only concentration improves → "improves concentration"
- `test_agent_snapshot_verdict_increases_risk` — volatility increases significantly → "increases risk"
- `test_agent_snapshot_verdict_marginal_impact` — tiny deltas → "marginal impact"
- `test_agent_snapshot_verdict_introduces_violations` — risk violations present → "introduces violations"
- `test_agent_snapshot_verdict_proxy_only_violations` — proxy violations only (risk/factor pass or absent) → "introduces violations"
- `test_agent_snapshot_risk_deltas_as_pct` — volatility converted to percentage
- `test_agent_snapshot_compliance_all_pass` — all checks pass
- `test_agent_snapshot_compliance_with_violations` — counts violations correctly
- `test_agent_snapshot_compliance_includes_proxy` — proxy_passes present in compliance
- `test_agent_snapshot_top_position_changes_filtered` — only >= 50bps changes included
- `test_agent_snapshot_top_factor_deltas_top3` — at most 3 factors returned
- `test_agent_snapshot_top_factor_deltas_sorted` — sorted by abs delta descending, then name
- `test_agent_snapshot_factor_variance_pct_conversion` — factor_pct 0.72 → 72.0 in snapshot
- `test_agent_snapshot_compliance_no_checks` — empty risk_checks/beta_checks → passes is None
- `test_agent_snapshot_position_changes_keys` — uses lowercase keys: position, before, after, change
- `test_agent_snapshot_position_changes_sorted` — sorted by abs change descending
- `test_agent_snapshot_position_changes_max5` — at most 5 entries
- `test_agent_snapshot_position_changes_50bps_boundary` — exactly 50bps included, below excluded
- `test_agent_snapshot_verdict_marginal_overrides_improvement` — tiny improvement → "marginal impact" not "improves risk"
- `test_agent_snapshot_verdict_positive_without_compliance` — risk improves, no checks available (all None), 0 violations → positive verdict (not "introduces violations")
- `test_agent_snapshot_verdict_marginal_boundary_exact` — exactly 0.1pp vol delta (self.volatility_delta=0.001, raw_vol_delta_pct=0.1) → not marginal (strict `<`)
- `test_agent_snapshot_verdict_uses_raw_deltas` — raw 0.0996pp rounds to 0.10 in snapshot but verdict uses raw → marginal

### `core/whatif_flags.py` tests

- `test_risk_violations_flag` — violations > 0 triggers warning
- `test_factor_violations_flag` — factor violations > 0 triggers warning
- `test_proxy_violations_flag` — proxy violations > 0 triggers warning
- `test_volatility_increase_flag` — > 2.0pp increase triggers warning
- `test_volatility_decrease_flag` — > 2.0pp decrease triggers success
- `test_concentration_increase_flag` — HHI delta > 0.02 triggers info
- `test_marginal_impact_flag` — tiny deltas triggers info
- `test_overall_improvement_flag` — both improve + 0 violations → success
- `test_overall_improvement_suppressed_with_violations` — both improve but violations → no overall_improvement
- `test_flags_sorted_by_severity` — warnings before info before success
- `test_empty_snapshot_no_crash` — empty dict produces no flags
- `test_marginal_suppresses_overall_improvement` — marginal scenario with both improvements → no overall_improvement flag
- `test_volatility_boundary_2pp` — exactly 2.0pp delta → no flag (threshold is > 2.0)
- `test_marginal_boundary_exact` — exactly 0.1pp vol or 0.001 HHI → marginal flag does NOT fire (strict `<`)
- `test_marginal_just_below` — 0.09pp vol and 0.0009 HHI → marginal flag fires
- `test_volatility_increase_raw_boundary` — raw _raw_vol_delta_pct=2.004 (rounds to 2.00 in display) → still triggers volatility_increase flag
- `test_concentration_increase_raw_boundary` — raw _raw_conc_delta=0.02004 → still triggers concentration_increase flag
- `test_concentration_increase_exact_boundary` — raw _raw_conc_delta=0.02 → no concentration_increase flag (threshold is > 0.02)
- `test_marginal_suppressed_with_violations` — marginal + violations → no marginal_impact flag

### `mcp_tools/whatif.py` agent format tests

- `test_agent_format_structure` — top-level keys: status, format, snapshot, flags, file_path
- `test_agent_format_calls_getter` — verify delegation to get_agent_snapshot()
- `test_agent_format_has_flags` — flags list present
- `test_agent_format_snapshot_nested` — snapshot is nested dict
- `test_agent_format_marginal_integration` — marginal snapshot → marginal_impact flag present, overall_improvement absent
- `test_agent_format_raw_fields_stripped` — returned snapshot has no keys starting with `_`
- `test_agent_format_raw_boundary_flags_fire` — raw vol_delta=2.004pp (rounds to 2.00) → volatility_increase flag present

### File output tests

- `test_file_output_creates_file` — file written to logs/whatif/
- `test_file_output_returns_file_path` — file_path is valid path
- `test_inline_output_no_file` — output="inline" does not create file
- `test_file_output_attaches_path_to_summary` — format="summary" + output="file" includes file_path
- `test_file_output_attaches_path_to_agent` — format="agent" + output="file" includes file_path
- `test_file_output_attaches_path_to_full` — format="full" + output="file" includes file_path
- `test_file_output_attaches_path_to_report` — format="report" + output="file" includes file_path
- `test_full_format_fallback_on_error` — format="full" returns minimal payload when to_api_response() fails
- `test_file_save_fallback_on_error` — file save produces minimal payload when to_api_response() fails

### MCP server registration tests

- `test_mcp_server_format_enum_includes_agent` — verify "agent" in format enum
- `test_mcp_server_output_param_exists` — verify output parameter registered
- `test_summary_format_unchanged` — format="summary" returns same shape as before (backward compat)
- `test_report_format_unchanged` — format="report" returns same shape as before (backward compat)

## Implementation Order

1. Add `get_agent_snapshot()` to `WhatIfResult` in `core/result_objects.py`
2. Create `core/whatif_flags.py` with `generate_whatif_flags()`
3. Add `_build_agent_response()` and `_save_full_whatif()` to `mcp_tools/whatif.py`
4. Add `format="agent"` and `output` parameter to `run_whatif()` in `mcp_tools/whatif.py`
5. Update format dispatch + wrap `format="full"` in try/except fallback
6. Update `mcp_server.py` registration (add agent to format enum, add output param)
7. Write tests (getters → flags → composer)
8. Verify via MCP live call: `run_whatif(format="agent")`

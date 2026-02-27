# B-016: Risk Score Methodology Review

**Status:** Completed
**Date:** 2026-02-19
**Related:** B-015 (fund/ETF weight exemption — resolved)

---

## Completion Note (2026-02-19)

Implementation completed with all planned items shipped.

### Implemented in

- `settings.py`
  - Added `RISK_ANALYSIS_THRESHOLDS["risk_score_critical_threshold"] = 2.0`
- `portfolio_risk_score.py`
  - Replaced `score_excess_ratio()` step function with piecewise linear interpolation
  - Updated stale methodology comments/docstrings for scoring and suggested limits
  - Updated `calculate_suggested_risk_limits()`:
    - Added keyword-only `security_types` parameter
    - Applied `_get_single_issuer_weights()` in concentration path
    - Applied `get_crash_scenario_for_security_type()` when `security_types` is provided
    - Preserved raw `single_stock_crash` fallback when `security_types` is `None`
    - Applied the same concentration scenario logic to leverage-limit math
    - Added guards for non-positive `max_loss` and `current_leverage`
  - Threaded `security_types` into the `calculate_suggested_risk_limits()` call from `run_risk_score_analysis()`
- `tests/core/test_portfolio_risk_score_fund_weight_exemption.py`
  - Added regression tests for Item 1:
    - `test_suggested_limits_exempts_diversified_positions()`
    - `test_suggested_limits_all_diversified_fallback()`
    - `test_suggested_limits_no_security_types_fallback()`
    - `test_suggested_limits_leverage_uses_filtered_weights()`
    - `test_suggested_limits_guards_invalid_inputs()`
  - Added regression tests for Item 2:
    - `test_score_excess_ratio_anchor_points()`
    - `test_score_excess_ratio_interpolation()`
    - `test_score_excess_ratio_continuity()`
    - `test_score_excess_ratio_monotonicity()`
  - Added validation tests for Item 3:
    - `test_risk_score_tighter_tolerance_lower_score()`
    - `test_risk_score_monotonic_with_tolerance()`
    - `test_risk_score_higher_leverage_lower_score()`
  - Extended orchestration threading assertion:
    - `test_run_risk_score_analysis_threads_security_types()` now asserts `security_types` is passed into `calculate_suggested_risk_limits()`

### Verification Run

- `python3 -m pytest tests/core/test_portfolio_risk_score_fund_weight_exemption.py -v`
  - Result: `18 passed`
- `python3 portfolio_risk_score.py`
  - Result: smoke test completed successfully

---

## Background

B-015 added fund/ETF weight exemptions to `calculate_concentration_risk_loss()` and `analyze_portfolio_risk_limits()` in `portfolio_risk_score.py`, but `calculate_suggested_risk_limits()` was missed. Additionally, the scoring function uses a step function with harsh cliff effects, and the risk profile interaction hasn't been validated.

---

## Item 1: Fund Exemption Gap in `calculate_suggested_risk_limits()`

### Problem

Lines 932-933 in `portfolio_risk_score.py` use raw `weights.abs().max()` + `WORST_CASE_SCENARIOS["single_stock_crash"]` (80%) without:
- Filtering out diversified types (ETFs, funds) via `_get_single_issuer_weights()`
- Using security-type-aware crash scenarios via `SECURITY_TYPE_CRASH_MAPPING`

The same issue exists in the leverage limit calculation at line 998 (`max_position * single_stock_crash`).

This means `calculate_suggested_risk_limits()` suggests overly aggressive concentration and leverage limits when the largest position is a fund/ETF.

### Fix

1. Add `security_types` as a **keyword-only** parameter: `*, security_types: Optional[Dict[str, str]] = None` — placed after existing keyword args to avoid positional breakage
2. Use `_get_single_issuer_weights(weights, security_types)` to filter weights before computing `max_position` in the concentration limit section (line 932)
3. Determine the crash scenario for the largest position using `get_crash_scenario_for_security_type()` instead of hardcoded `single_stock_crash`. When `security_types` is None, fall back to `single_stock_crash` (conservative default, preserves current behavior)
4. Apply the same fix to the leverage limit calculation (line 998) — use filtered `max_position` and the resolved crash scenario
5. Thread `security_types` from `run_risk_score_analysis()` into the `calculate_suggested_risk_limits()` call (line 1825) as a keyword argument
6. **All-diversified fallback**: When all positions are diversified types, `_get_single_issuer_weights()` returns raw weights (same behavior as `calculate_concentration_risk_loss()`). The crash scenario will be the appropriate type-specific one (e.g. 40% for funds instead of 80%)
7. **Guard against invalid inputs**: Add guards for zero/negative `max_loss` and `current_leverage` to avoid divide-by-zero in suggestion math. Behavior: if `max_loss <= 0`, clamp to a small positive value (e.g. 0.01) with a warning log; if `current_leverage <= 0`, clamp to 1.0 with a warning log. This preserves function execution rather than raising — consistent with the module's graceful-fallback pattern (see FX fallback in `fmp/fx.py`)

### Files
- `portfolio_risk_score.py` — `calculate_suggested_risk_limits()`, `run_risk_score_analysis()`

### Tests (dedicated regression tests for this path)
- `test_suggested_limits_exempts_diversified_positions()` — mixed fund/equity portfolio: concentration limit uses equity crash (not fund crash) for the largest single-issuer position
- `test_suggested_limits_all_diversified_fallback()` — all-diversified portfolio: falls back to raw weights with type-specific crash scenario
- `test_suggested_limits_no_security_types_fallback()` — no security_types: uses raw weights + `single_stock_crash` (80%), preserving current behavior
- `test_suggested_limits_leverage_uses_filtered_weights()` — leverage limit section uses filtered weights + type-specific crash, not raw weights + 80%
- `test_suggested_limits_guards_invalid_inputs()` — zero/negative `max_loss` clamps to 0.01, zero/negative `current_leverage` clamps to 1.0 (no exceptions raised)

---

## Item 2: Piecewise Linear Scoring Curve

### Problem

`score_excess_ratio()` (line 191) uses a 4-bucket step function with 25-point cliffs:

| Excess Ratio | Current Score | Cliff |
|---|---|---|
| ≤ 0.80 | 100 | — |
| 0.81 | 75 | -25 |
| 1.01 | 50 | -25 |
| 1.51 | 0 | -50 |

A portfolio at 0.79 excess ratio scores 100, but at 0.81 it drops to 75. This creates unstable behavior near boundaries.

### Fix

1. Add `risk_score_critical_threshold: 2.0` to `RISK_ANALYSIS_THRESHOLDS` in `settings.py` — makes the new breakpoint explicit and configurable alongside the existing safe/caution/danger thresholds
2. Replace the step function with piecewise linear interpolation using all 4 configurable thresholds:

| Excess Ratio | New Score | Transition |
|---|---|---|
| ≤ safe (0.80) | 100 | flat |
| safe – caution (0.80 – 1.00) | 100 → 75 | linear |
| caution – danger (1.00 – 1.50) | 75 → 50 | linear |
| danger – critical (1.50 – 2.00) | 50 → 0 | linear |
| ≥ critical (2.00) | 0 | flat |

3. Update docstring for `score_excess_ratio()` to document the piecewise linear behavior (remove step-function references)
4. Update all stale step-function references in comments/docstrings, including:
   - `score_excess_ratio()` docstring (line 191) — update to describe piecewise linear behavior
   - `calculate_suggested_risk_limits()` docstring (line 835) — currently says concentration "always uses `single_stock_crash` (80%)", update to reflect security-type-aware behavior
   - Module-level comment block (lines 53-54) — update `calculate_suggested_risk_limits` usage note

Example values under new curve:
- 0.80 → 100 (unchanged anchor)
- 0.90 → 87.5 (was 75)
- 1.00 → 75 (unchanged anchor)
- 1.25 → 62.5 (was 50)
- 1.50 → 50 (unchanged anchor)
- 1.75 → 25 (was 0)
- 2.00 → 0 (unchanged anchor)

### Files
- `settings.py` — add `risk_score_critical_threshold` to `RISK_ANALYSIS_THRESHOLDS`
- `portfolio_risk_score.py` — `score_excess_ratio()`

### Tests (boundary and continuity tests)
- `test_score_excess_ratio_anchor_points()` — exact values at each threshold (0.8→100, 1.0→75, 1.5→50, 2.0→0)
- `test_score_excess_ratio_interpolation()` — midpoint values (0.9→87.5, 1.25→62.5, 1.75→25)
- `test_score_excess_ratio_continuity()` — values just above/below each threshold are close (no cliffs)
- `test_score_excess_ratio_monotonicity()` — score is monotonically non-increasing as ratio increases

---

## Item 3: Risk Profile Interaction Validation

### Problem

Need to verify the score responds appropriately to different risk profile configurations (`max_loss` values, leverage).

### Approach

Add test cases to `tests/core/test_portfolio_risk_score_fund_weight_exemption.py`:

1. **Risk tolerance sensitivity**: Same portfolio produces different scores with different `max_loss` values — tighter tolerance → lower score
2. **Score monotonicity**: As `max_loss` decreases (tighter), score should decrease or stay the same
3. **Leverage amplification**: Same portfolio with higher leverage → lower score

### Tests
- `test_risk_score_tighter_tolerance_lower_score()` — same portfolio, max_loss=0.25 vs max_loss=0.10: tighter tolerance produces lower or equal score
- `test_risk_score_monotonic_with_tolerance()` — sweep max_loss from 0.50 to 0.05: scores are monotonically non-increasing
- `test_risk_score_higher_leverage_lower_score()` — same portfolio, leverage 1.0 vs 2.0: higher leverage produces lower or equal score

### Files
- `tests/core/test_portfolio_risk_score_fund_weight_exemption.py`

---

## Implementation Order

1. **Item 2** (scoring curve) — independent change, no downstream dependencies. Add `risk_score_critical_threshold` to settings, update `score_excess_ratio()`, add boundary tests
2. **Item 1** (fund exemption) — builds on existing `_get_single_issuer_weights()` pattern from B-015. Add keyword param, fix both code paths, add dedicated regression tests
3. **Item 3** (validation tests) — verifies overall risk score behavior with profiles

## Verification

1. Run existing tests: `python -m pytest tests/core/test_portfolio_risk_score_fund_weight_exemption.py -v`
2. Run all new tests (Items 1-3)
3. Smoke test: `python portfolio_risk_score.py`

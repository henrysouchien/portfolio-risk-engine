# Cash Replay P3.1 Implementation Plan: Incomplete-Trade Symmetry Fix

## Summary

This plan addresses the remaining realized-performance distortion caused by timeline/cash asymmetry on incomplete trades (especially IBKR futures incompletes).

Current failure signature:
- orphan timeline exposure from incomplete exits
- repeated `V_adjusted<=0` warnings
- NAV path collapse and extreme return clamping (for example, IBKR `-100%`)

This plan ships two selectable symmetry strategies behind a mode switch and sets a default mode after validation.

## Goals

1. Remove incomplete-trade asymmetry between cash replay and position timeline valuation.
2. Eliminate persistent negative NAV artifacts caused by orphan incomplete trade legs.
3. Improve IBKR gap versus broker actual by at least 25 percentage points.
4. Avoid regressions larger than 10 percentage points on other sources.

## Locked Decisions

1. Implement both symmetry strategies behind a mode switch.
2. Apply scope to all incomplete trades (not futures-only).
3. Default mode: `drop_raw_legs`.
4. Acceptance gate: keep default only if IBKR improves >=25pp and no source regresses >10pp.

## In Scope

- Timeline reconstruction behavior for incomplete trades.
- Mode switch and diagnostics plumbing in realized analysis.
- Result metadata/agent snapshot additive fields.
- Unit + contract tests.
- Live validation and baseline comparison artifacts.

## Out of Scope

- FIFO matcher redesign.
- Broad synthetic policy redesign.
- Provider normalization redesign.

## Implementation Plan

### 1) Mode Switch

Add a realized-analysis mode switch with values:
- `drop_raw_legs` (default)
- `inject_neutralizing_open`

Suggested internal constant name:
- `REALIZED_INCOMPLETE_TIMELINE_MODE`

### 2) Build Incomplete Key Map

Before timeline assembly, derive normalized incomplete key metadata from `fifo_result.incomplete_trades`:
- key: `(symbol, currency, direction)`
- fields: quantity, sell_date, sell_price, instrument_type

### 3) Strategy A: `drop_raw_legs` (Default)

For incomplete keys:
- exclude raw timeline transaction legs that create orphan residual exposure
- keep warnings and diagnostics for dropped keys/rows
- do not modify cash replay logic

### 4) Strategy B: `inject_neutralizing_open`

For incomplete keys:
- keep raw timeline legs
- inject a synthetic balancing entry at `sell_date - 1s`
- mark source as `synthetic_incomplete_neutralizer` for diagnostics

### 5) Diagnostics (Additive)

Add realized metadata fields:
- `incomplete_timeline_mode`
- `incomplete_timeline_raw_legs_dropped_count`
- `incomplete_timeline_neutralizers_added_count`
- `incomplete_timeline_affected_symbols`

Expose these in:
- realized metadata (`format='full'`)
- agent snapshot `data_quality`

### 6) Guardrails

1. No double application when key is also handled by current-position synthetic logic.
2. Preserve deterministic ordering with `-1s` synthetic insertion.
3. Keep existing P2B futures fee-only cash replay behavior unchanged.

## Tests

### Unit Tests (`tests/core/test_realized_performance_analysis.py`)

1. `test_incomplete_mode_drop_raw_legs_removes_residual_qty`
2. `test_incomplete_mode_neutralizing_open_nets_residual_qty_to_zero`
3. `test_futures_incomplete_no_persistent_negative_nav_drop_raw`
4. `test_non_futures_incomplete_symmetry_under_both_modes`
5. `test_incomplete_mode_diagnostics_fields_populated`

### Contract / MCP Tests

1. `tests/mcp_tools/test_performance.py`
- assert new incomplete-timeline diagnostics in full output

2. `tests/mcp_tools/test_performance_agent_format.py`
- assert new diagnostics in agent `snapshot.data_quality`

3. `tests/core/test_performance_flags.py`
- keep additive-key assertions robust

### Regression Retention

- Keep P1/P2A/P2B regression coverage green.

## Live Validation Procedure

Run both modes and compare against broker actuals:
- sources: `all`, `ibkr_flex`, `schwab`, `plaid`, `snaptrade`
- mode values: `drop_raw_legs`, `inject_neutralizing_open`

Compare to extracted actuals in:
- `docs/planning/performance-actual-2025/baseline_extracted_data.json`
- `docs/planning/performance-actual-2025/RETURN_PROGRESSION_BY_FIX.md`

## Acceptance Gate

Keep `drop_raw_legs` as default only if:
1. IBKR absolute error improves by >=25pp.
2. No source worsens by >10pp absolute error.

If gate fails:
- keep dual-mode support
- set default to better-performing mode
- record rationale in progression doc

## Deliverables

1. Code updates for symmetry mode + diagnostics.
2. Unit and contract tests passing.
3. Live artifacts per mode:
- `live_summary_post_p3_1_<mode>.json`
- `live_delta_post_p3_vs_post_p3_1_<mode>.json`

4. Update progression tracking:
- `docs/planning/performance-actual-2025/RETURN_PROGRESSION_BY_FIX.md`

## Assumptions

1. Broker extracted baselines remain the acceptance reference.
2. Incomplete-trade asymmetry is the primary IBKR residual distortion source.
3. P2B futures fee-only and income/flow dedupe remain unchanged by this plan.

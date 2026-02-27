# Plan: Apply Fund/ETF Exemption to Risk Score Concentration Checks

_Created: 2026-02-19_
_Last updated: 2026-02-19 (v5 — implemented and verified)_

## Status

Completed on 2026-02-19.

Implementation shipped in:
- `portfolio_risk_score.py`
- `tests/core/test_portfolio_risk_score_fund_weight_exemption.py`

Verification run:
- `pytest -q tests/core/test_portfolio_risk_score_fund_weight_exemption.py tests/core/test_temp_file_refactor.py` → `14 passed`
- `pytest -q tests/core/test_run_portfolio_risk_limits.py tests/core/test_leverage_capacity.py` → `7 passed`

## Context

The risk analysis path now exempts diversified vehicles (`etf`, `fund`, `mutual_fund`) from `max_single_stock_weight` checks.
The risk score path still uses raw max position weight in concentration logic, which creates inconsistent outputs between:

- `get_risk_analysis(include=["compliance"])`
- `get_risk_score(...)`

Goal: make the risk score path use the same single-issuer concentration policy as risk analysis.

## Current State

In `portfolio_risk_score.py`, the following still use unfiltered max weight:

- `analyze_portfolio_risk_limits()` concentration section (line 628: `weights.abs().max()`)
- `calculate_concentration_risk_loss()` picks largest raw position (line 360: `weights.abs().max()`)

Notes:
- `calculate_concentration_risk_loss()` (line 305) is already security-type-aware for crash severity via an internal `SecurityTypeService.get_security_types()` call (line 367), but still starts from the largest raw position.
- `calculate_concentration_risk_loss()` already has a `portfolio_data` parameter (line 305), but the caller at line 1240 does not pass it.
- Risk score entrypoint (`run_risk_score_analysis`) does not currently thread a full `security_types` map into downstream concentration checks.
- `SecurityTypeService` is already imported at module level (line 29).

## Scope

In scope:

- Risk score concentration calculations and compliance-style concentration warnings.
- Threading `security_types` through risk score call chain.
- Reconciling the existing internal `SecurityTypeService` call with the new threaded map.
- Tests for exempted and fallback behaviors.

Out of scope:

- Optimizer path updates.
- Changes to Herfindahl methodology.
- MCP tool signature changes.
- `calculate_suggested_risk_limits()` (line 893) — also uses raw max weight + `single_stock_crash` without diversified-type exemption. Noted as follow-up work for full risk-score-output consistency.

## Proposed Approach

Use the same security-type exemption criterion as risk analysis:

- Exempt types: `{"etf", "fund", "mutual_fund"}`
- Source of truth: `core.constants.DIVERSIFIED_SECURITY_TYPES`
- Classification API: `SecurityTypeService.get_security_types()` (already imported in module; consistent with existing usage in this file)

Concentration checks should operate on **single-issuer weights only** when `security_types` are available.
Fallback behavior remains unchanged when `security_types` are missing.

**Empty-filter policy**: When all positions are exempt and the filtered set is empty, fall back to raw weights (consistent with B-015 in `run_portfolio_risk.py:439`). This is the conservative choice — avoids silently zeroing out concentration checks.

## File-by-File Changes

### 1) `portfolio_risk_score.py`

1. Import and reuse shared exemption constant:
- `from core.constants import DIVERSIFIED_SECURITY_TYPES`

2. Add helper to filter concentration universe:
- `_get_single_issuer_weights(weights: pd.Series, security_types: Optional[Dict[str, str]]) -> pd.Series`
- Behavior:
  - If no `security_types`: return original `weights` (backward-compatible fallback).
  - If available: drop tickers where type is in `DIVERSIFIED_SECURITY_TYPES`.
  - If all are exempt and filtered is empty: **return original `weights`** (conservative fallback, consistent with B-015).

3. Update `run_risk_score_analysis(...)` (line 1587):
- Derive `portfolio_data` for downstream use:
  `portfolio_data = portfolio if isinstance(portfolio, PortfolioData) else None`
- Resolve `security_types` once from `SecurityTypeService.get_security_types(tickers, portfolio_data)`.
  - Note: use `get_security_types()` (not `get_full_classification()`) — this file only needs security types, and `get_security_types()` is already imported and used elsewhere in this module.
  - Wrap in `try/except` with fallback to `security_types = None` on failure (consistent with existing `SecurityTypeService` guard pattern at module level).
- Pass `security_types` and `portfolio_data` into:
  - `calculate_portfolio_risk_score(..., security_types=security_types, portfolio_data=portfolio_data)`
  - `analyze_portfolio_risk_limits(..., security_types=security_types)`
- Store `security_types` in `RiskScoreResult.analysis_metadata`.

4. Update `calculate_portfolio_risk_score(...)` signature (line 1184):
- Add `security_types: Optional[Dict[str, str]] = None`
- Add `portfolio_data = None` (to thread through to concentration loss for fallback classification)
- Pass both through to `calculate_concentration_risk_loss(..., security_types=security_types, portfolio_data=portfolio_data)`.

5. Update `calculate_concentration_risk_loss(...)` signature and logic (line 305):
- Add `security_types: Optional[Dict[str, str]] = None` **in addition to** existing `portfolio_data` parameter.
- Use `_get_single_issuer_weights()` to filter weights before picking `max_position` and `largest_ticker`.
- **Reconcile with existing internal `SecurityTypeService` call** (line 367):
  - If `security_types` map is provided and contains the `largest_ticker`: use its value directly for crash scenario lookup. Skip the internal `SecurityTypeService.get_security_types()` call.
  - If `security_types` is `None` or doesn't contain `largest_ticker`: fall back to existing internal call (current behavior preserved).
  - This avoids redundant service calls and ensures the threaded map is the single source of truth when available.
- If filtered weights series is non-empty, use it; if empty, fall back to raw weights (per empty-filter policy above).

6. Update `analyze_portfolio_risk_limits(...)` signature and concentration block (line 543):
- Add `security_types: Optional[Dict[str, str]] = None`
- Use `_get_single_issuer_weights()` to filter before computing max weight for concentration warning/violation logic.
- Filtered-empty fallback: use raw weights (consistent with above).

7. Fix existing gap at call site (line 1240):
- `calculate_portfolio_risk_score()` currently calls `calculate_concentration_risk_loss(summary, leverage_ratio)` without `portfolio_data` or `security_types`. With the signature changes in steps 4-5 above, this call becomes:
  `calculate_concentration_risk_loss(summary, leverage_ratio, portfolio_data=portfolio_data, security_types=security_types)`
- This threads both the precomputed `security_types` map and `portfolio_data` (for fallback classification) through the full call chain: `run_risk_score_analysis → calculate_portfolio_risk_score → calculate_concentration_risk_loss`.

### 2) `run_risk.py` (only if needed)

No external interface change required for `run_risk_score(...)` because `run_risk_score_analysis(...)` handles internal classification resolution.

### 3) `services/portfolio_service.py` (only if needed)

No service method signature changes required.
`analyze_risk_score(...)` already delegates to `run_risk_score(...)`; score metadata enrichment is handled in `portfolio_risk_score.py`.

## Backward Compatibility

- All new parameters default to `None`.
- If `security_types` cannot be resolved, behavior remains current (raw max-weight concentration logic).
- Existing MCP/tooling call signatures remain unchanged.

## Edge Cases

1. All positions are funds/ETFs/mutual funds:
- Filtered set is empty → fall back to raw weights (conservative, consistent with B-015).
- Concentration loss uses largest position with its actual security-type crash scenario.

2. Missing security type for a ticker:
- Treat as single-issuer (safe default): not in exemption set.

3. Mixed portfolio where largest raw position is fund:
- Concentration should use largest non-exempt ticker instead.

4. SecurityTypeService failure:
- Fallback to existing behavior via `security_types=None`.

5. Empty or invalid weight series:
- Guard `idxmax()` call against empty series to avoid exceptions.

6. Unknown/None security type values in threaded map:
- Treat as single-issuer (not in `DIVERSIFIED_SECURITY_TYPES`), consistent with edge case #2.

## Tests

Add/extend tests in `tests/core`:

1. `test_calculate_concentration_risk_loss_exempts_diversified_positions`
- Largest fund position should not drive concentration loss.

2. `test_calculate_concentration_risk_loss_all_diversified_falls_back`
- All exempt types → falls back to raw weights (not 0.0), consistent with B-015.

3. `test_analyze_portfolio_risk_limits_exempts_diversified_positions`
- Concentration warnings/violations use largest single-issuer weight.

4. `test_risk_score_path_fallback_without_security_types`
- No `security_types` → legacy behavior unchanged.

5. `test_run_risk_score_analysis_threads_security_types`
- Verify `security_types` is passed into both `calculate_portfolio_risk_score` and `analyze_portfolio_risk_limits`, and stored in result metadata.

6. `test_concentration_loss_uses_threaded_types_over_service_call`
- When `security_types` map is provided, concentration loss should use it for crash scenario lookup rather than re-calling `SecurityTypeService`.

Update any pass-through tests in `tests/core/test_temp_file_refactor.py` if mocks need new optional kwargs.

## Verification

1. Run targeted tests for risk score module and modified tests.
2. Compare outputs for a fund-heavy portfolio (e.g., DSU-heavy) across:
- `get_risk_analysis(include=["compliance"])`
- `get_risk_score(format="summary")`

Expected:
- Concentration interpretation should no longer be driven by diversified-fund positions.
- Risk score and compliance concentration signals should be directionally consistent.

## Rollout Notes

- This is a low-risk change with safe fallbacks.
- Primary functional impact: reduced false-positive concentration penalties for diversified-fund-heavy portfolios in risk score outputs.

# Plan: Remove `min_inception_nav` Filter from Account Aggregation

**Status**: REVERTED (attempted 2026-03-03, revert `6742f471`). Let account 252's $11 NAV into aggregate from inception, but phantom GLBE returns (+39%/+103% monthly) still compound. The filter was masking the symptom; root cause is unhandled RECEIVE_AND_DELIVER. See `docs/planning/performance-actual-2025/RETURN_PROGRESSION_BY_FIX.md`.

## Context

Schwab aggregated return is +17.53% vs broker actual -8.29%. Investigation revealed account 252 starts at $11 (cash-back rewards), then receives a $65K deposit on Jan 30 2025. The `min_inception_nav=500` filter defers 252's entry into the aggregate until it crosses $500 — which happens to be the same day as the $65K deposit ($65,191). After that point, 252 is 3x the size of account 165 ($55K vs $18K) and dominates the NAV-weighted aggregate with its inflated per-account returns (+274%, driven by synthetic positions with fabricated cost basis).

The hypothesis: removing the filter lets 252 enter from inception at $11. Since $11 is negligible vs the $19K combined NAV, it contributes nothing to returns during the tiny-base period. When the $65K deposit arrives, it's already captured as an external flow and neutralized by TWR. This should produce better aggregate returns than the current approach where 252 suddenly appears at $65K.

## Current Behavior (with filter)

Per-account monthly returns side-by-side (measured 2026-03-03):

| Month | 252 | 013 | 165 | AGG |
|-------|-----|-----|-----|-----|
| 2024-09-30 | +38.50% | +10.01% | +1.69% | +1.69% |
| 2024-11-30 | +103.13% | +25.57% | +7.72% | +7.72% |
| 2025-01-31 | +16.95% | +8.34% | +1.34% | +0.68% |
| 2025-08-31 | +5.99% | +0.01% | -0.29% | +4.33% |

Before Jan 2025, AGG = 165 (252 and 013 excluded by filter). After Jan 2025 when 252 enters at $65K, it dominates the aggregate (3x size of 165).

Per-account chain-linked: 252 = +273.92%, 013 = +22.04%, 165 = -7.97%. AGG = +17.53%.

## Changes

### 1. Remove filter from `_sum_account_daily_series()`
**File**: `core/realized_performance_analysis.py` ~line 5606

- Remove `min_inception_nav` parameter (line 5609)
- Remove the filter block (lines 5627-5632)

### 2. Remove filter from `_sum_account_monthly_series()`
**File**: `core/realized_performance_analysis.py` ~line 5653

- Remove `min_inception_nav` parameter (line 5656)
- Remove the filter block and comment (lines 5668-5679)

### 3. Update test
**File**: `tests/core/test_synthetic_twr_flows.py` ~line 562

- Remove explicit `min_inception_nav=500.0` kwarg from `_sum_account_daily_series()` call (line 564)

### 4. No other callers pass the param explicitly
- `_build_aggregated_result()` calls `_sum_account_daily_series` at line 5728 (default) and `_sum_account_monthly_series` at line 5777 (default)
- `_build_aggregated_result()` also calls `_sum_account_daily_series` at line 6096 for observed-only aggregation (default, no change needed)
- `test_sum_account_monthly_series_alignment` uses default — no change needed

## Codex Review Findings

### R1: Missed caller at line 6096 — ADDRESSED
Observed-only aggregation path also calls `_sum_account_daily_series` with default params. No explicit kwarg, so removing the param is safe. Added to caller list above.

### R2: Flow alignment risk — ACCEPTED
`fillna(0.0)` means $0 NAV for pre-inception periods. This is safe only if external flows align with NAV jumps. For account 252, the $65K deposit IS captured as an external flow on Jan 30 (verified in investigation). The TWR denominator guard in `compute_twr_monthly_returns` (line ~2191) returns 0.0 for near-zero denominators, preventing div-by-zero. Risk is low but not zero — if a future account has a NAV jump without a matching flow, it would appear as return. This is the same risk that exists today for any flow timing mismatch.

### R3: TWR denominator safety — PASS
`compute_twr_monthly_returns` guards `prev_nav + cf_in` near zero → returns 0.0 (lines 2191-2199). No NaN/div-zero risk.

### R4: Test impact — PASS
Only `test_synthetic_twr_flows.py:564` passes explicit kwarg (addressed in change #3). Other tests use defaults and will pass.

## Risk Assessment

**Low risk**: The filter only affects the account aggregation path (triggered by `institution` param + 2+ accounts). Per-account analysis and single-source analysis are unaffected. TWR has denominator guards for near-zero NAV. The main risk is flow-misalignment on future accounts, which is pre-existing and not introduced by this change.

## Verification

1. **Run existing tests**: `python3 -m pytest tests/core/test_synthetic_twr_flows.py tests/core/test_realized_performance_analysis.py -x -q`
2. **Run Schwab aggregated perf** and compare:
   ```
   get_performance(mode='realized', institution='schwab', format='agent')
   ```
   Before: +17.53%. Check if it moves closer to -8.29%.
3. **Run IBKR and Plaid** to confirm no regression:
   - IBKR should stay near -8.04%
   - Plaid should stay near -11.77%
4. **Run combined**: check overall number

## Acceptance Criteria

- [ ] All existing tests pass
- [ ] Schwab aggregated return improves (moves toward -8.29%)
- [ ] IBKR and Plaid returns don't regress
- [ ] No new extreme monthly returns in aggregate series

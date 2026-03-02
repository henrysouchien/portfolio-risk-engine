# Remove Extreme Month Exclusion Filter

**Status**: COMPLETE (2026-03-01)

## Context

IBKR realized performance regressed from +10.45% to -71.78% (82pp swing). Root cause: the `extreme_month_filter_active` gate at line 4220 of `core/realized_performance_analysis.py` NaN-ifies months with >300% absolute returns when `synthetic_current_tickers` is truthy. IBKR's March 2025 (+308%) gets excluded, causing the total return to compound from April's -52% onward without the correct base.

This filter was introduced in commit `25165d7c` as a band-aid for pre-P1 data quality bugs. Now that root causes have been addressed (P1-P3.2 + Schwab Fixes A/E/F/G), the extreme returns that remain are structurally expected artifacts of incomplete transaction history — not bugs. The proper fix for these is the cost-basis flow injection plan, not suppression.

**Impact note**: Plaid currently benefits from this filter (Aug 2024 +5447% excluded → Plaid at -12.93% vs broker -12.49%). Removing the filter will revert Plaid to ~-7.96%. This is acceptable — the +5447% is the same synthetic inception issue affecting all sources, and the cost-basis flow injection plan will address it properly.

## File: `core/realized_performance_analysis.py`

### Change 1: Delete `extreme_month_filter_active` variable (lines 4220-4224)

Delete:
```python
extreme_month_filter_active = bool(
    data_coverage < low_coverage_threshold
    or synthetic_current_tickers
    or unpriceable_symbols_sorted
)
```

### Change 2: Delete the NaN-ification branch (lines 4241-4248)

Delete:
```python
elif abs(raw) > extreme_abs_return_threshold and extreme_month_filter_active:
    warnings.append(
        f"{ts.date().isoformat()}: Excluding extreme return from chain-link metrics "
        f"({raw:.2%}, |r|>{extreme_abs_return_threshold:.2f}) due to low-confidence data coverage."
    )
    monthly_returns.loc[ts] = np.nan
    action = "excluded_from_chain_linking"
    reason = "extreme-return low-confidence filter"
```

The warning-only branch (currently line 4249) becomes the `elif` after the long-only clamp:
```python
elif abs(raw) > extreme_abs_return_threshold:
    warnings.append(...)
    action = "warned"
    reason = "extreme return"
```

### Change 3: Remove dead `EXTREME_MONTHLY_RETURNS_EXCLUDED` flag construction (lines 4277-4289)

Since `action` will never be `"excluded_from_chain_linking"`, the `excluded_extreme_months` list will always be empty. Delete:
```python
excluded_extreme_months = [
    row for row in extreme_return_months
    if str(row.get("action")) == "excluded_from_chain_linking"
]
if excluded_extreme_months:
    data_quality_flags.append(
        {
            "code": "EXTREME_MONTHLY_RETURNS_EXCLUDED",
            "severity": "high" if data_coverage < low_coverage_threshold else "medium",
            "count": len(excluded_extreme_months),
            "threshold_abs_return": round(extreme_abs_return_threshold, 4),
            "months": excluded_extreme_months,
        }
    )
```

### Change 4: Clean up `extreme_abs_return_threshold` variable (lines 4216-4219)

This is still used by the long-only clamp (line 4233) and the warning branch — **keep it**.

## File: `tests/core/test_realized_performance_analysis.py`

### Change 5: Delete test `test_analyze_realized_performance_excludes_extreme_month_when_low_confidence` (line 3860)

This test specifically asserts the exclusion behavior which no longer exists. Delete the entire test function (lines 3860-3997).

The long-only clamp test (`test_analyze_realized_performance_clamps_extreme_negative_returns` at line 3453) still covers the remaining safety guard.

## What stays unchanged

- **Long-only clamp to -100%** (line 4233-4240): Legitimate safety guard for impossible returns on long-only portfolios
- **Warning for extreme returns** (line 4249-4255): Informational, doesn't modify data
- **`extreme_return_months` list**: Still populated for telemetry with `action="warned"` or `action="clamped_to_-100pct"`
- **`extreme_abs_return_threshold` variable**: Still used by clamp and warning branches

## Expected impact

| Source | Before | After (expected) | Broker Actual |
|--------|--------|-------------------|---------------|
| IBKR | -71.78% | ~+10% (March +308% restored) | -9.35% |
| Schwab | +23.13% | +23.13% (no extreme months) | ~0-11% |
| Plaid | -12.93% | ~-7.96% (Aug +5447% restored) | -12.49% |
| Combined | +34.41% | ~+34% | -8 to -12% |

## Verification

```bash
# Unit tests
pytest tests/core/test_realized_performance_analysis.py -q

# Live test all sources via MCP
# get_performance(mode='realized', source='ibkr_flex', format='summary', use_cache=false)
# get_performance(mode='realized', source='schwab', format='summary', use_cache=false)
# get_performance(mode='realized', source='plaid', format='summary', use_cache=false)
# get_performance(mode='realized', source='all', format='summary', use_cache=false)
```

Acceptance: IBKR returns to ~+10% range. No other source regresses beyond expected (Plaid reverts to -7.96%).

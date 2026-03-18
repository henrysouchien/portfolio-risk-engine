# Holdings Value Fix — Missing `value` Column in VIRTUAL_FILTERED Path

## Context

The `/api/positions/holdings` endpoint returns 500 for scoped (VIRTUAL_FILTERED) portfolios with error `positions[0] missing required field: value`. This causes the frontend dashboard to show incorrect portfolio values ($158K vs actual $21K for IBKR, $133K vs $51K for All Accounts) because it falls back to stale performance time series data.

**Introduced by**: `530e463e` ("Reduce cold dashboard setup and cached repricing work")
**Bisected**: Passes at `192ecaf9`, fails at `530e463e`. Doc-only commits in between.

## Root Cause

`get_all_positions()` in `position_service.py` has two repricing layers:

1. **Provider-level**: `_calculate_market_values()` inside `_get_positions_df()` (lines 792, 811, 854)
2. **Central**: `_calculate_market_values()` after all providers are fetched (lines 667-674)

Commit `530e463e` introduced `_should_reprice_cached_provider()` which conditionally skips central repricing for providers with `cache_age_hours < 6`. But provider-level repricing is always deferred (`_defer_cached_repricing = True`, line 487) inside `get_all_positions()`. When both are skipped, `_calculate_market_values()` never runs, and the `value` column is never computed.

**Before `530e463e`**: Central repricing ran for ALL cached providers → `value` always computed.
**After `530e463e`**: Central repricing only runs when `cache_age_hours >= 6` → recently-cached providers get no repricing → no `value` column → `PositionResult.from_dataframe()` raises `ValueError`.

## Fix

The `_should_reprice_cached_provider` optimization is correct in intent — don't re-fetch market prices for recently-cached positions. But it must not skip repricing entirely when `value` is missing. The fix ensures `value` always exists.

### File: `services/position_service.py`

**Change**: After the conditional repricing block (line 674), add a guard that ensures the `value` column exists. If any positions are still missing `value` after the conditional reprice, compute it.

```python
# After line 674 (end of conditional repricing block):
# Ensure value column exists — deferred repricing may have skipped it
# for recently-cached providers that _should_reprice_cached_provider excluded
if not combined.empty and ("value" not in combined.columns or combined["value"].isna().any()):
    missing_mask = combined["value"].isna() if "value" in combined.columns else pd.Series(True, index=combined.index)
    if missing_mask.any():
        repriced = self._calculate_market_values(combined.loc[missing_mask])
        for column in repriced.columns:
            combined.loc[missing_mask, column] = repriced[column]
```

This is minimal and surgical — it only runs `_calculate_market_values` on rows that are actually missing `value`, and only when the conditional repricing left gaps.

## Additional Fix: Frontend NAV Display

**Root cause**: `PortfolioSummaryAdapter` computed `totalValue` by summing `holdings[].market_value` (which was empty because the API uses `gross_exposure` not `market_value`), then fell back to the performance time series `portfolioValue` — a hypothetical $100K growth curve, not actual NAV.

**Fix**: Use `portfolioRecord.total_portfolio_value` (actual NAV from `portfolio_totals_usd`) as the primary source. No fallback to performance time series.

**Result**: All Accounts: $133,777 → $105,868 (correct NAV).

## Verification

- `python3 -m pytest tests/ -x -q` — 3789 passed
- Manual: `get_all_positions(consolidate=False)` succeeds with valid `value` fields
- Browser: `/api/positions/holdings` returns 200 for scoped portfolios
- Browser: All Accounts shows correct NAV ($105,868)
- IBKR scoped portfolio shows $0 — runtime issue (IBKR Gateway not accessible from FastAPI server), not a code bug

## Files Modified

| File | Change |
|------|--------|
| `services/position_service.py` | Add value column guard after conditional repricing |
| `frontend/.../PortfolioSummaryAdapter.ts` | Source totalValue from NAV, not performance time series |

# Replace Fake Stress Test Probabilities with Real Worst-Month Dates

## Context

The stress test tab shows hardcoded fake probabilities (`loss < -0.15 ? 0.1 : 0.05`). The backend computes worst monthly returns per factor from real price data — the date exists in the pandas Series index but is discarded. We want to show "Worst month: Mar 2020" instead.

## Design Principle

**Do NOT change ANY existing function signatures, return types, or data shapes.** All existing callers remain untouched. Dates are collected by a new standalone function and added as a new key in `historical_analysis`.

## Changes

### 1. Backend: `portfolio_risk_engine/risk_helpers.py`

**Add one new function** `_get_worst_dates_for_proxies()`:
```python
def _get_worst_dates_for_proxies(
    stock_factor_proxies: Dict[str, Dict[str, Union[str, List[str]]]],
    start_date: str,
    end_date: str,
    fmp_ticker_map: Dict[str, str] | None = None,
) -> Dict[str, str]:
    """Return {proxy: "YYYY-MM"} for the month of worst return per proxy."""
```
- Collects unique proxies the same way `get_worst_monthly_factor_losses()` does
- Fetches returns via `fetch_monthly_total_return_price` + `calc_monthly_returns` (same as `_fetch_single_proxy_worst`)
- Uses `returns.idxmin()` to get the date, with safety: `if hasattr(idx, 'strftime')` guard
- Returns `{proxy: "YYYY-MM"}` dict

**In `calc_max_factor_betas()` only** (line ~305 area):
- After existing `worst_per_proxy` and `worst_by_factor` are computed, call `_get_worst_dates_for_proxies()`
- Build `worst_factor_dates: Dict[str, str]` by looking up which proxy won per factor (from `worst_by_factor`) and mapping to its date
- Add `'worst_factor_dates': worst_factor_dates` to the `historical_analysis` dict (line ~367)

**What does NOT change:**
- `_fetch_single_proxy_worst()` — unchanged
- `get_worst_monthly_factor_losses()` — unchanged, still returns `Dict[str, float]`
- `aggregate_worst_losses_by_factor_type()` — unchanged, still returns `Dict[str, Tuple[str, float]]`
- `compute_max_betas()` — unchanged
- All 6 callers of `get_worst_monthly_factor_losses()`: `risk_helpers.py:191`, `risk_helpers.py:305`, `portfolio_risk_score.py:1162`, `efficient_frontier.py:98`, `portfolio_optimizer.py:300`, `portfolio_optimizer.py:1198` — **all unchanged**
- Echo/print block — unchanged
- `_format_historical_analysis()` in `core/result_objects/risk.py` — unchanged. It iterates known keys (`worst_per_proxy`, `worst_by_factor`, `analysis_period`) and ignores any extra keys like `worst_factor_dates`. Optionally, add a new section to format `worst_factor_dates` if present (e.g., `"market → 2020-03"`), but this is cosmetic and not required for the feature to work.

**Performance note:** This does re-fetch price data for the proxies. The FMP cache (`@lru_cache`) means no extra API calls — just recomputes monthly returns from cached prices. Could optimize later by having `_fetch_single_proxy_worst` also return dates, but that changes the signature and is not worth the blast radius now.

### 2. Frontend adapter: `frontend/packages/connectors/src/adapters/RiskAnalysisAdapter.ts`

Add optional type for the new field (additive, no breaking change):
```typescript
historical_analysis?: {
  worst_per_proxy?: Record<string, number>;              // UNCHANGED
  worst_by_factor?: Record<string, [string, number]>;    // UNCHANGED
  worst_factor_dates?: Record<string, string>;           // NEW: {factor_type: "YYYY-MM"}
  analysis_period?: { ... };
  loss_limit?: number;
};
```

### 3. Frontend container: `frontend/packages/ui/src/components/dashboard/views/modern/RiskAnalysisModernContainer.tsx`

```typescript
// Read dates from the new field
// Keys in worst_factor_dates are lowercase ("market", "momentum", "value", "industry")
// matching the keys from worst_by_factor (both come from factor_types = ["market", ...])
const worstDates = histAnalysis?.worst_factor_dates;

// factor variable comes from Object.entries(worst_by_factor) — already lowercase
tests.push({
  scenario: `${factor} Stress Test`,
  impact: loss * 100,
  probability: loss < -0.15 ? 0.1 : 0.05,  // Keep for compat
  worstDate: worstDates?.[factor],  // Direct lookup, same casing
});
```

### 4. Frontend component: `frontend/packages/ui/src/components/portfolio/RiskAnalysis.tsx`

- Add `worstDate?: string` to the stress test type (keep `probability` optional for compat)
- Display logic:
```typescript
{test.worstDate
  ? `Worst month: ${(() => {
      const [y, m] = test.worstDate.split('-');
      const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
      return `${months[parseInt(m, 10) - 1]} ${y}`;
    })()}`
  : 'Synthetic scenario'}
```
- No `new Date()` constructor — avoids timezone bugs entirely. Parse "YYYY-MM" manually.

## Files to Modify

| File | Change | Blast radius |
|------|--------|-------------|
| `portfolio_risk_engine/risk_helpers.py` | Add `_get_worst_dates_for_proxies()` function; add `worst_factor_dates` key in `calc_max_factor_betas()` | **Zero** — no existing signatures changed |
| `frontend/packages/connectors/src/adapters/RiskAnalysisAdapter.ts` | Add optional `worst_factor_dates` type | **Zero** — additive |
| `frontend/packages/ui/.../RiskAnalysisModernContainer.tsx` | Read dates, pass `worstDate` | **Low** — new optional field |
| `frontend/packages/ui/.../RiskAnalysis.tsx` | Add `worstDate?` to type, display date | **Low** — backward compat |

## Tests to Add

1. **`tests/core/test_portfolio_risk.py`**: Add test for `_get_worst_dates_for_proxies()`:
   - Mock `fetch_monthly_total_return_price` to return a Series with known DatetimeIndex
   - Assert returned date matches the month of the minimum return
   - Test with non-datetime index → returns empty dict (no crash)
   - Test with empty returns → returns empty dict

2. **`tests/core/test_portfolio_risk.py`**: Add test for `calc_max_factor_betas()` `worst_factor_dates` key:
   - Mock the price fetchers
   - Assert `historical_analysis['worst_factor_dates']` contains expected factor types with valid "YYYY-MM" strings

3. **Frontend test** in the existing RiskAnalysis or container test file:
   - Test that stress test row renders "Worst month: Mar 2020" when `worstDate: "2020-03"` is provided
   - Test that stress test row renders "Synthetic scenario" when `worstDate` is undefined
   - Test that "YYYY-MM" string-split formatting produces correct month name (no `new Date()` timezone issue)

## Verification

1. `pytest tests/core/test_portfolio_risk.py -k "worst_date" --no-header -q` — new backend tests pass
2. `pytest tests/core/test_portfolio_risk.py --no-header -q` — no regressions in existing tests
3. `npx tsc --noEmit --project packages/ui/tsconfig.json` — clean (type check)
4. `cd frontend && npm run lint 2>&1 | tail -5` — frontend lint clean
5. Browser: Factors → Stress Tests tab shows real dates like "Worst month: Mar 2020"
6. Backward compat: If backend hasn't been restarted yet (no `worst_factor_dates` in response), frontend falls back to "Synthetic scenario" — no crash

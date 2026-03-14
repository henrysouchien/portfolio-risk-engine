# Fix: TWR Inception Deferral for Tiny-Base Accounts

**Status**: REVERTED (attempted 2026-03-02, revert `deb9495b`). Band-aid that hid the tiny-base phase rather than fixing the root cause (phantom GLBE from unhandled RECEIVE_AND_DELIVER). Also had a bug: deferred `external_flows` but `twr_external_flows` remained un-deferred. See `docs/planning/performance-actual-2025/RETURN_PROGRESSION_BY_FIX.md`.

## Context

Schwab aggregate realized performance is +17.53% vs actual -8.29%. Per-account breakdown:

| Account | Our TWR | Actual | Status |
|---------|---------|--------|--------|
| 87656165 | -7.97% | -8.29% | SOLVED (0.32pp gap) |
| 51388013 | +22.04% | -14.69% | BROKEN |
| 25524252 | +273.92% | +10.65% | BROKEN |

**Root cause**: Accounts 013 and 252 start with tiny NAVs ($86 and $11 respectively — cash-back rewards). Daily TWR compounds extreme percentage returns on these tiny bases:

- Account 252: $11 → $163 over 10 months (tiny cash-back deposits), then $65K deposit on Jan 30 2025. TWR from $11 inception = +273.92%. Actual +10.65%.
- Account 013: $86 inception, small deposits, NAV doesn't cross $500 until Feb 25 2025.

The existing `min_inception_nav=$500` filter in `_sum_account_daily_series()` (line 5490) defers these accounts in the **aggregate** computation but does NOT apply to **individual** per-account TWR. The aggregate is still distorted because account 252 enters with $65K NAV (3x account 165's $21K), dominating the combined portfolio from Jan 30 onwards.

## Fix

Apply the same `min_inception_nav` deferral at the caller site before `compute_twr_monthly_returns()` so **per-account** TWR skips the tiny-base phase. The aggregate path in `_sum_account_daily_series()` already has a $500 filter (line 5490) — this fix ensures per-account TWR is consistent with the aggregate behavior, and that `_postfilter["daily_nav"]` is pre-deferred so the aggregate filter is a no-op rather than the sole line of defense.

### Approach: Caller-Side Deferral

**Step 1. Add a helper function** (near `_sum_account_daily_series`, ~line 5467)

```python
def _defer_inception(
    daily_nav: pd.Series,
    external_flows: List[Tuple[datetime, float]],
    min_inception_nav: float = 500.0,
) -> Tuple[pd.Series, List[Tuple[datetime, float]], Optional[str]]:
    """Defer TWR inception until daily NAV crosses min_inception_nav.

    Returns (deferred_nav, deferred_flows, warning_or_None).
    """
    if min_inception_nav <= 0 or daily_nav.empty:
        return daily_nav, external_flows, None
    nav_sorted = daily_nav.sort_index()  # ensure chronological order for idxmax
    mask = nav_sorted.abs() >= min_inception_nav
    if not mask.any():
        return pd.Series(dtype=float), [], f"NAV never reached {min_inception_nav:.0f}; TWR not computed."
    first_viable = mask.idxmax()
    deferred_nav = nav_sorted.loc[first_viable:]
    deferred_flows = [(when, amt) for when, amt in external_flows
                      if pd.Timestamp(when).normalize() >= pd.Timestamp(first_viable).normalize()]
    return deferred_nav, deferred_flows, None
```

**Step 2. Call `_defer_inception` before `compute_twr_monthly_returns`** (around line 4546, inside the `else` branch for daily TWR)

```python
        else:
            # Defer TWR inception for tiny-base accounts — skip the phase
            # where NAV is below $500 to avoid compounding extreme % returns
            # on tiny cash-back balances.
            daily_nav, external_flows, defer_warning = _defer_inception(
                daily_nav, external_flows, min_inception_nav=500.0,
            )
            if defer_warning:
                warnings.append(defer_warning)
                # Deferral emptied the series — short-circuit with a specific
                # diagnostic.  Falls through to the existing empty-monthly_returns
                # error handler at line 4704, which returns {"status": "error"}.
                # The multi-account aggregation loop (line 6321) drops errored
                # accounts gracefully, so this account is simply excluded.
                monthly_returns = pd.Series(dtype=float)
                return_warnings = [defer_warning]
            else:
                # Either deferral trimmed the series (but it's non-empty),
                # or daily_nav was already empty before deferral.  In both
                # cases, pass through to compute_twr_monthly_returns which
                # has its own empty-NAV diagnostics (lines 2081-2086).
                monthly_returns, return_warnings = compute_twr_monthly_returns(
                    daily_nav=daily_nav,
                    external_flows=external_flows,
                    month_ends=month_ends,
                )
```

**Why this is the right insertion point:** The deferral reassigns `daily_nav` and `external_flows` in the local scope. These same variables are later serialized into `_postfilter` at lines 5128 and 5144, so the deferred series automatically flow through to aggregation storage without any additional changes.

**Empty-NAV handling:** The short-circuit branch is keyed on `defer_warning` (not `daily_nav.empty`), so it only fires when deferral caused the emptiness. If `daily_nav` was already empty before deferral (a pre-existing condition), `_defer_inception` returns `defer_warning=None` and the code falls through to `compute_twr_monthly_returns`, which has its own empty-NAV diagnostics at lines 2081-2086. This preserves the existing distinction between "empty series" and "no valid values after dropna".

When deferral does empty the series (NAV never crosses $500), `monthly_returns` is set to an empty Series and `return_warnings` carries the specific deferral message. The existing guard at line 4703-4709 catches this and returns `{"status": "error", ...}`. The multi-account aggregation loop at line 6321 drops errored accounts gracefully — the account is simply excluded.

**Step 3. `_postfilter` consistency analysis**

The `_postfilter` dict (line 5107) stores both daily and monthly series. After deferral:

| `_postfilter` key | Source variable | Deferred? | Used by | Correct? |
|---|---|---|---|---|
| `daily_nav` (line 5128) | `daily_nav` | YES — reassigned at Step 2 | `_sum_account_daily_series()` for TWR aggregate | YES |
| `external_flows` (line 5144) | `external_flows` | YES — reassigned at Step 2 | `_sum_account_daily_series()` for TWR aggregate | YES |
| `monthly_nav` (line 5124) | `monthly_nav` | NO — computed at line 4477, before deferral | `_sum_account_monthly_series()` for Dietz aggregate | YES — Dietz doesn't need deferral |
| `net_flows` (line 5140) | `net_flows` | NO — computed at line 4483, before deferral | `_sum_account_monthly_series()` for Dietz aggregate | YES — Dietz doesn't need deferral |
| `time_weighted_flows` (line 5150) | `tw_flows` | NO — computed at line 4483, before deferral | `_sum_account_monthly_series()` for Dietz aggregate | YES — Dietz doesn't need deferral |

The split is intentional: `daily_nav`/`external_flows` are used for TWR aggregation (needs deferral), while `monthly_nav`/`net_flows`/`tw_flows` are used for Dietz aggregation (doesn't need deferral — Dietz returns are proportional to invested capital, not compounded daily). No additional changes needed.

**Step 4. No changes needed to observed-only path**

The observed-only path (`observed_daily_nav`, `observed_external_flows`) does NOT have its own `compute_twr_monthly_returns` call — it's only stored in `_postfilter` for the SYNTHETIC_PNL_SENSITIVITY flag comparison. No deferral needed there.

**Step 5. No changes to `compute_twr_monthly_returns`**

The function remains unchanged — the deferral happens at the caller.

**Step 6. No changes to `_sum_account_daily_series`**

The existing $500 filter there (line 5490) is still needed as a safety net — it operates on `_postfilter` data from each account. After this fix, the per-account deferral means `_postfilter["daily_nav"]` is already deferred, so the aggregate-level filter at line 5490 becomes a no-op for deferred accounts. But it still protects against any future code path that might store un-deferred daily NAV.

**Aggregate impact clarification:** The primary benefit of this fix is correcting **per-account reported TWR** (e.g., account 252 going from +273.92% to ~+12%). The aggregate path was already partially protected by the $500 filter in `_sum_account_daily_series`. However, the per-account deferral also ensures cleaner `_postfilter` data flows into the aggregate, making the two layers consistent rather than relying solely on the aggregate-level filter.

### What NOT to Change

- **`compute_twr_monthly_returns`**: No signature change needed — caller does the deferral.
- **`_sum_account_daily_series`**: Already has $500 filter for aggregation — leave as is.
- **`_sum_account_monthly_series`**: Same — already has the filter.
- **Legacy monthly return path**: The `compute_monthly_returns` (Modified Dietz) path at line 4540 doesn't need deferral since Dietz handles tiny bases more gracefully (returns proportional to invested capital).
- **Account 165**: Not affected — its first NAV is $19K, well above $500.

## Expected Result

| Account | Before Fix | After Fix | Actual |
|---------|-----------|-----------|--------|
| 87656165 | -7.97% | -7.97% (unchanged) | -8.29% |
| 51388013 | +22.04% | ~short-period return from Feb 25 | -14.69% |
| 25524252 | +273.92% | ~+12% (from Jan 30 inception) | +10.65% |
| **Aggregate** | **+17.53%** | **TBD** | **-8.29%** |

Account 252's deferred TWR should be close to actual (+10.65%) since the post-$65K-deposit period has straightforward returns. Account 013's return will cover only a ~1-month period (Feb 25 2025 onward).

The aggregate may still not match -8.29% exactly since that's just account 165's return and the aggregate naturally includes 252's contribution. But it should be much more reasonable than +17.53%.

## Verification

1. Run per-account Schwab:
   ```python
   get_performance(source='schwab', mode='realized', institution='schwab', account='25524252')
   ```
   - Account 252 should be ~+10-12% (not +273.92%)
   - Account 013 should be a short-period return (not +22.04%)
   - Account 165 unchanged at -7.97%

2. Run Schwab aggregate:
   ```python
   get_performance(source='schwab', mode='realized', institution='schwab')
   ```
   - Aggregate should be significantly less than +17.53%

3. Verify other sources unaffected (they don't have tiny-base accounts):
   - IBKR: should still be -11.37%
   - Plaid: should still be -11.77%

4. Run existing tests: `python -m pytest tests/core/test_realized_performance*.py -x`

# Generalize Per-Account Realized Performance Aggregation

**Status**: Ready for review

## Problem

Merrill (via Plaid) shows a 2pp gap vs broker (-10.46% system vs -12.49% broker). Root cause: cross-source holding exclusion.

DSU, MSCI, STWD are held at both Merrill (reported by Plaid) and Schwab (reported by Schwab API). The system's cross-source logic classifies Schwab as "native" and Plaid as "aggregator mirroring native" — so it excludes those symbols from Plaid scope. This hides ~85% of Merrill's portfolio NAV, leaving only IT ($3,610) visible in the position timeline.

The cross-source exclusion is designed for when the same position appears through multiple providers (e.g., Schwab position seen via both Schwab API and Plaid). But here, these are **genuinely separate positions at different brokerages** that happen to hold the same stocks.

## Solution

Run per-account analysis (like Schwab already does), not per-provider. Each account gets its own isolated analysis — positions and transactions scoped to that account only. No cross-source exclusion needed because each account only sees its own data.

Per-account aggregation already works for Schwab (commit `8ce1a340`, plan: `docs/planning/SCHWAB_PER_ACCOUNT_PLAN.md`). The aggregation machinery is fully provider-agnostic. The only thing gating it to Schwab is hardcoded institution checks.

## Architecture

```
analyze_realized_performance(source="plaid", institution="merrill")
  → _analyze_realized_performance_account_aggregated()   # CURRENTLY: Schwab-only gate
    → _discover_account_ids(institution="merrill")       # CURRENTLY: _discover_schwab_account_ids()
      → finds ["CMA-Edge"]                               # Merrill account
    → for each account:
        → _analyze_realized_performance_single_scope(account="CMA-Edge")
          → _build_source_scoped_holdings(source="plaid", account="CMA-Edge")
            → account filter runs FIRST → only Merrill positions
            → cross-source detection sees only Plaid → no overlap → DSU/MSCI/STWD INCLUDED
          → runs cash replay with full Merrill portfolio
    → _build_aggregated_result()                         # Combine per-account results
```

## File to Modify

**`core/realized_performance_analysis.py`** — all changes in one file (~20 lines changed).

## Changes

### 1. Rename `_discover_schwab_account_ids()` → `_discover_account_ids()` (line 5177)

Current: hardcodes `match_institution(..., "schwab")`, ignores `institution` param.

New: use the `institution` parameter for matching. No fallback by `position_source` — institution must be set for aggregation to trigger.

```python
def _discover_account_ids(
    positions: "PositionResult",
    fifo_transactions: List[Dict[str, Any]],
    institution: str,
) -> List[str]:
```

- Match positions by `match_institution(brokerage_name, institution)`, match txns by `match_institution(txn_institution, institution)`
- Collect `account_name` values; also collect `account_id` as fallback
- Return sorted unique values

### 2. Auto-resolve institution from source + generalize gate in `analyze_realized_performance()` (line 6219)

Add source→institution auto-resolution and source/institution conflict validation at the top of the function, before the gate check.

**Conflict validation** — reject mismatched source + institution (e.g., `source="schwab", institution="merrill"`):
```python
_SOURCE_TO_INSTITUTION = {
    "schwab": "schwab",
    "ibkr_flex": "ibkr",
}

if institution is not None and source not in {"all"}:
    expected_inst = _SOURCE_TO_INSTITUTION.get(source)
    if expected_inst and not match_institution(institution, expected_inst):
        return {"status": "error", "message": f"source={source!r} conflicts with institution={institution!r}"}
```

**Auto-resolution** — when `source` maps unambiguously to a single institution and `institution` is not already set:
```python
if institution is None and source not in {"all"}:
    institution = _SOURCE_TO_INSTITUTION.get(source)
```

This preserves existing Schwab behavior (`source="schwab"` → `institution="schwab"` → aggregation). Plaid/SnapTrade still require explicit `institution` param for aggregation.

Then the gate becomes:
```python
should_aggregate = not account and institution is not None
```

Keep `use_per_symbol_inception` Schwab-only — it's unsafe for IBKR's limited history window:
```python
use_per_symbol_inception = bool(
    institution and match_institution(institution, "schwab")
)
```

### 3. Update `_analyze_realized_performance_account_aggregated()` (line 6061)

- Add defensive guard at top: `assert institution is not None` (caller gate ensures this, but guard against direct callers)
- Line 6101: `_discover_schwab_account_ids(...)` → `_discover_account_ids(positions, prefetch_fifo, institution)`
- Line 6151: Change hardcoded `use_per_symbol_inception=True` → `use_per_symbol_inception=bool(match_institution(institution, "schwab"))` (unsafe for non-Schwab institutions with limited history windows)
- Line 6193: Replace hardcoded "Schwab" in fallback warning → generic message using `institution`

### 4. No changes needed to `_build_source_scoped_holdings()` or aggregation math

The fmp_ticker_map call in the aggregation path (line 6080) is safe — it's just for ticker resolution. Each per-account `_analyze_realized_performance_single_scope()` call re-builds its own scoped holdings with `account=account_id`, which filters by account BEFORE cross-source detection.

## Behavior Matrix

| Call | Before | After | Notes |
|------|--------|-------|-------|
| `source="schwab"` | aggregation | aggregation | Auto-resolves `institution="schwab"` |
| `institution="schwab"` | aggregation | aggregation | Unchanged |
| `source="plaid"` | single-scope | single-scope | Plaid can't auto-resolve institution |
| `source="plaid", institution="merrill"` | single-scope | **aggregation** | **NEW** — discovers 1 account (CMA-Edge), `<=1` fallback runs single-scope with `account="CMA-Edge"` |
| `source="ibkr_flex"` | single-scope | single-scope | Auto-resolves `institution="ibkr"`, discovers 1 account → `<=1` fallback to single-scope |
| `source="all"` | single-scope | single-scope | No institution → gate not triggered |
| `source="all", institution="merrill"` | single-scope | **aggregation** | **NEW** — fetches all txns, filters by institution |
| `source="snaptrade"` | single-scope | single-scope | SnapTrade can't auto-resolve institution |
| `source="schwab", institution="merrill"` | N/A | **error** | **NEW** — conflict validation rejects |

No breaking changes. Schwab preserved via auto-resolution. IBKR effectively unchanged (1 account → single-scope fallback).

## Verification

```bash
# 1. Existing tests pass (Schwab per-account + all others)
python3 -m pytest tests/core/test_realized_performance_analysis.py -x -q -k "account"
python3 -m pytest tests/ -x -q 2>&1 | tail -5

# 2. Schwab unchanged — source="schwab" auto-resolves institution, aggregation with 3 accounts
# Verify account_aggregation metadata shows 3 accounts, same returns

# 3. IBKR effectively unchanged — source="ibkr_flex" auto-resolves institution="ibkr",
#    enters aggregation, discovers 1 account, falls back to single-scope via <=1 check

# 4. Plaid/Merrill — source="plaid", institution="merrill" triggers aggregation (when Plaid API is back up)
# Discovers "CMA-Edge" account, runs single-scope with account="CMA-Edge"
# DSU/MSCI/STWD included in position timeline
# TWR should be closer to broker -12.49%

# 5. source="plaid" without institution → single-scope (same as today, no regression)

# 6. Conflict validation — source="schwab", institution="merrill" returns error
```

## Future Work

See backlog item in `docs/planning/TODO.md`: **Institution-Based Realized Performance Routing**. The next step is to make the MCP `get_performance` tool route purely by institution (e.g., `institution="merrill"`), with the backend automatically resolving which provider pipeline to use. The `source` parameter becomes an internal implementation detail rather than a user-facing concept.

# Portfolio Selector Scope Fix Plan

**Status**: DONE (Steps 2-5 implemented `72842f57`). Live test findings below.

## Live Test Findings (2026-03-15)

### ~~Selector persistence issue~~ `NOT A BUG — stale localStorage`
Initially appeared that single-account selection reverted to Combined. Root cause: stale `lastPortfolio_hc@henrychien.com` key from previous Google OAuth session conflicted with dev auth's `lastPortfolio_1` key. After clearing stale keys, bootstrap correctly restores IBKR portfolio. The `portfolio_name` field IS preserved through the full PortfolioRepository chain (confirmed by code trace). Verified working 2026-03-15.

### ~~Concentration score still 100 in Combined~~ `NOT A BUG`
Investigated: the dual-metric fix IS working. Combined portfolio's top-N concentration loss = 14.8%, well below the 25% max_loss tolerance. `excess_ratio = 0.592` < safe threshold `0.8` → score = 100. The earlier E2E finding was based on a different portfolio state (MSFT 30% + AAPL 25.7%) that no longer matches the current Combined weights. Score is mathematically correct.
**Created**: 2026-03-14
**Reviewed**: 5 Codex rounds → all PASS. Implemented in `72842f57`. Live tested 2026-03-15.
**Source**: `FRONTEND_E2E_FINDINGS_2026_03_14.md` — issues N2, N3, N5
**Goal**: Fix single-account portfolio selector so all views work correctly when a specific account is selected.

---

## Root Cause

When the portfolio selector switches to a single IBKR account, the backend receives `portfolio_name=_auto_interactive_brokers_interactive_brokers_henry_chien`. Scope resolution finds it as `single_account`, builds account filters. Two failures:

1. **Blank `account_id_external`**: `resolve_portfolio_scope()` at line ~219 drops accounts with blank external IDs from the filter set. The name fallback can never fire for those accounts.
2. **Account ID format mismatch**: Even when IDs exist, different providers report different formats for the same account. No alias resolution is applied.

---

## Step 1: Display name fix (N1) `DONE — 2f83eef5`

---

## Step 2: Fix account filter matching (N2)

### 2a: Include blank-ID accounts via name field

**File**: `services/portfolio_scope.py` ~line 219

The current `AccountFilter` contract uses 3-tuples: `(institution_key, account_id_external, account_name)` (line ~15, ~86). Preserve this shape.

```python
# BEFORE (~line 219): drops accounts with no external ID
for acct in linked_accounts:
    if acct.get("account_id_external"):
        filters.append((
            normalize_institution_slug(acct["institution_key"]),
            acct["account_id_external"].strip().lower(),
            (acct.get("account_name") or "").strip().lower(),
        ))

# AFTER: include blank-ID accounts with empty string ID (name fallback will match)
for acct in linked_accounts:
    ext_id = (acct.get("account_id_external") or "").strip().lower()
    inst = normalize_institution_slug(acct.get("institution_key", ""))
    name = (acct.get("account_name") or "").strip().lower()
    filters.append((inst, ext_id, name))
    # Blank ext_id is allowed — _position_matches() will try name fallback
```

### 2b: Add alias expansion to `_position_matches()`

**File**: `services/portfolio_scope.py` ~line 101

Import `resolve_account_aliases()` from `providers/routing_config.py:279` (returns `frozenset[str]`). Expand matching to check aliases while preserving institution scoping + ambiguity guard:

```python
from providers.routing_config import resolve_account_aliases

def _position_matches(position, filter_by_id, filter_by_name):
    inst_slug = normalize_institution_slug(
        position.get("brokerage_name") or position.get("institution")
    )
    acct_id = (position.get("account_id") or "").strip().lower()
    acct_name = (position.get("account_name") or "").strip().lower()

    # Direct ID match (existing)
    if acct_id and (inst_slug, acct_id) in filter_by_id:
        return True

    # Alias-expanded ID match (new)
    if acct_id:
        for alias in resolve_account_aliases(acct_id):
            if (inst_slug, alias.lower()) in filter_by_id:
                return True

    # Name fallback with ambiguity guard (existing, now also fires for blank-ID accounts)
    if acct_name and (inst_slug, acct_name) in filter_by_name:
        if not _is_ambiguous_name(acct_name, filter_by_name):
            return True

    return False
```

### 2c: Extract shared helper for transaction_store.py

`inputs/transaction_store.py:2247` has the same matching pattern using the same 3-tuple `AccountFilter` shape. Extract the improved `_position_matches()` into a public function in `services/portfolio_scope.py` and import from both files.

**Effort**: Medium (1-2 hrs)

---

## Step 3: Risk settings CURRENT_PORTFOLIO fallback (N3)

**Codex correction**: `config_portfolio_name` on `PortfolioScope` defaults to `CURRENT_PORTFOLIO` (line ~42) and is NOT overridden for manual, single_account, or combined portfolios (lines ~193, ~224). So `scope.config_portfolio_name` is always `CURRENT_PORTFOLIO` currently — this does not distinguish manual portfolios from auto portfolios.

**Fix**: Update the legacy `app.py` callers to use scope resolution. There are 3 sites that call `load_risk_limits(portfolio_name)` directly:
- `app.py` ~line 1213
- `app.py` ~line 1509
- `app.py` ~line 1741

Change all to:
```python
scope = resolve_portfolio_scope(user_id, portfolio_name)
risk_limits = risk_limits_manager.load_risk_limits(scope.config_portfolio_name)
```

Note: `load_risk_limits()` takes a single `portfolio_name` argument (see `inputs/risk_limits_manager.py:176`), not `(user_id, portfolio_name)`.

**Future**: If manual portfolios need distinct risk limits, `resolve_portfolio_scope()` should override `config_portfolio_name` for `manual` type. But that's a separate feature — for now, all portfolios inherit from `CURRENT_PORTFOLIO`, which is the correct behavior since risk preferences are user-level, not portfolio-level.

**Effort**: Quick (15 min)

---

## Step 4: Fix trading analysis 500 (N5)

### 4a: Apply shared matching fix from Step 2

Once `_position_matches()` is extracted as a shared helper (Step 2c), `transaction_store.py:2247` uses it. This fixes the underlying scope mismatch for the transaction-store branch.

### 4b: Normalize no-data exits to empty success

**Codex correction**: The endpoint uses `format="full"` (line ~101 in `routes/trading.py`), and full-mode returns top-level `summary`, `trade_scorecard`, `income_analysis` (not `data.trades`). The frontend reads `summary` and `income_analysis` at `APIService.ts:520` and `registry.ts:436`.

Change all 4 no-data error exits (lines 154, 201, 240, 318) to return an empty full-format success matching `TradingAnalysisResult.to_api_response()` shape (see `trading_analysis/models.py:862`):

```python
# At each no-data exit in trading_analysis.py:
return {
    "status": "success",
    "format": "full",
    "summary": {},
    "trade_scorecard": [],          # list, not dict (matches models.py)
    "income_analysis": {},
    "realized_performance": {},
    "timing_analysis": [],          # list, not dict (matches models.py:883)
    "behavioral_analysis": {},
    "return_statistics": {},
    "return_distribution": {},
    "generated_at": "",              # string timestamp (matches models.py:863)
    "message": "No transaction data for this portfolio scope",
}
```

This prevents `routes/trading.py` from converting empty-data into HTTP 500, and matches the frontend's expected response shape (`APIService.ts:520` reads `summary`/`income_analysis`; `registry.ts:436` reads top-level fields).

### 4c: Document live-fetch branch

The live-fetch branch (line ~214) is the fallback when the transaction-store path is not taken (line ~168). It does NOT apply `scope.account_filters`. Add a comment:

```python
# NOTE: Live-fetch branch does not apply portfolio scope account_filters.
# It runs as fallback when TRANSACTION_STORE_READ is disabled or store
# lookup fails. Account-level filtering is handled by the store branch only.
```

**Effort**: Medium (30-60 min, depends on Step 2)

---

## Step 5: Fix DashboardHoldingsCard setState warning (N4) `PASS`

**File**: `frontend/packages/ui/src/components/dashboard/cards/DashboardHoldingsCard.tsx` ~line 50

**Fix**: Move both state updates into the event handler. Include `sortField` in `useCallback` dependency list:

```typescript
const handleSort = useCallback((field: HoldingSortKey) => {
  if (field === sortField) {
    setSortDirection(d => d === 'asc' ? 'desc' : 'asc');
  } else {
    setSortField(field);
    setSortDirection('asc');
  }
}, [sortField]);
```

**Effort**: Quick (10 min)

---

## Step 6: Auto-load after bootstrap (N7) — Handled separately

See `E2E_REAUDIT_FIX_PLAN.md` Step 7. Another session investigating/implementing.

---

## Execution Order

| Step | Issue | Fix | Effort | Dependencies |
|------|-------|-----|--------|--------------|
| 1 | N1 | ~~Display name~~ | **DONE** | `2f83eef5` |
| 5 | N4 | DashboardHoldingsCard sort state | Quick (10 min) | None |
| 3 | N3 | Risk settings — scope resolution in 3 app.py sites | Quick (15 min) | None |
| 2 | N2 | Blank account_id + alias resolution + shared helper | Medium (1-2 hrs) | None |
| 4 | N5 | Trading analysis empty-success + shared matching | Medium (30-60 min) | Step 2 |

**Batch 1** (Steps 3, 5): Independent quick fixes. ~25 min.
**Batch 2** (Steps 2, 4): Account filter fix + trading analysis. ~1.5-2.5 hrs.

**Total effort**: ~2-3 hours

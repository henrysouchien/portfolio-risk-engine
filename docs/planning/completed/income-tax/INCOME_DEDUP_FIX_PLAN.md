# Income Dedup & Data Quality Fix Plan

**Created**: 2026-03-07
**Priority**: High (income dedup), Low (UNKNOWN label, missing symbols)
**Status**: Planning
**Reviewed by**: Codex (2026-03-07) — v2: 4 findings addressed; v3: 3 findings addressed

## Problem Summary

Three IBKR realized performance data quality issues:

| Issue | Impact | Root Cause |
|-------|--------|------------|
| Income duplication | 285 rows / 60 unique = 4.75x inflation. Dividends $307 vs $182 actual, interest -$332 vs -$262 actual | Unstable `{index}` in transaction_id + raw dedup key |
| UNKNOWN interest label | Cosmetic — margin interest shows symbol "UNKNOWN" | IBKR CashTransaction has no symbol for margin interest |
| Missing symbols (DSU, TW) | -$290 in untracked realized losses | Trades predate Flex query window |

## Issue 1: Income Duplication (High Priority)

### Root Cause Analysis

Income events are duplicated at **two layers**:

**Layer 1 — Raw transactions (`raw_transactions` table):**
- `ibkr/flex.py:728-731` generates `transaction_id` with `{index}` from `enumerate()`:
  ```
  income:U2471778:2025-03-15T00:00:00:USD:DIVIDEND:2.50000000:3
  ```
- Row enumeration order varies across Flex queries → same event gets different index → different `transaction_id`
- `transaction_store.py:1792-1809` uses this `transaction_id` as the raw dedup key
- Result: raw rows accumulate across ingestion runs

**Layer 2 — Normalized income (`normalized_income` table):**
- `IBKRFlexNormalizer` creates `NormalizedIncome` objects (no `transaction_id` field — `trading_analysis/models.py:232`)
- Store falls back to `_hash_key("income", provider, symbol, income_type, date, amount, account_id)` at `transaction_store.py:571`
- `account_id` can vary between ingestion runs because the segment dedup winner in `normalize_flex_cash_income_trades()` is selected by min `transaction_id` string (`_select_dedup_winner` at `flex.py:672`), which depends on the unstable `{index}` — different winner → potentially different `account_id` value (e.g., "U2471778" vs None)
- Result: normalized rows accumulate across ingestion runs

**Note:** The `ibkr_flex_mtm` provider already has the correct fix pattern at `transaction_store.py:1810-1822` — content-based dedup key that ignores the volatile index.

### Fix Strategy

**Three code changes + delete-and-rebuild cleanup:**

#### Fix A: Stable transaction_id in `ibkr/flex.py`

**File**: `ibkr/flex.py:727-731`

Replace the unstable `{index}` with a content-based hash. Match the segment dedup key semantics at `flex.py:757-766` — which excludes `account_id` and uses the signed amount:

```python
# BEFORE (line 727-731):
if transaction_id is None:
    transaction_id = (
        f"income:{account_id or account_name or 'unknown'}:{event_dt.isoformat()}:"
        f"{_normalize_flex_currency(row.get('currency'))}:{trade_type}:{abs(amount):.8f}:{index}"
    )

# AFTER:
if transaction_id is None:
    import hashlib
    _content = (
        f"income:{event_dt.date().isoformat()}:{symbol}:"
        f"{_normalize_flex_currency(row.get('currency'))}:{trade_type}:{amount:.8f}"
    )
    transaction_id = f"income:{hashlib.sha256(_content.encode()).hexdigest()[:16]}"
```

Key differences from current:
- **Excludes `account_id`** — matches segment dedup which groups across account variants (Codex finding #3)
- Uses **signed `amount`** (not `abs(amount)`) — prevents collision between equal-and-opposite interest events (Codex finding #3)
- Uses `event_dt.date().isoformat()` — `_parse_flex_date()` already truncates to day, but explicit for safety
- Includes `symbol` instead of `index`
- Content-hashed for fixed length
- Prefix `income:` preserved for synthetic ID detection

**Edge case — same-day same-symbol same-amount**: For IBKR income events this is impossible (same dividend from same symbol on same day would be a single CashTransaction row). If IBKR ever reports two legitimate same-day same-amount events, they would have different `transactionID` fields and skip the synthetic path entirely.

**Scope assumption — single-account Flex query**: This fix assumes the Flex query covers a single account (our setup: U2471778). The segment dedup in `normalize_flex_cash_income_trades()` already excludes `account_id` by design (line 757) because IBKR reports the same event with different account variants per segment. If multi-account Flex queries are ever used, the synthetic ID would need `account_id` re-added to prevent cross-account collisions. This is consistent with `docs/planning/completed/FLEX_INCOME_FEE_DEDUP_PLAN.md:228`.

**DO NOT apply to `_normalize_cash_transaction_row()`** at line 987-991. Cash flow rows go to `provider_flow_events` table (different dedup path via `transaction_store.py:651`). Keep separate — changes to cash flow IDs would need audit of that table first.

#### Fix A2: Deterministic segment dedup winner in `_select_dedup_winner()`

**File**: `ibkr/flex.py:677-692`

After Fix A, all segment duplicates of the same income event share the same `transaction_id`. The current tiebreaker is `min(rows, key=lambda row: str(row.get("transaction_id") or ""))` — when IDs are equal, Python's `min()` returns the first element found, which depends on input order (nondeterministic across Flex queries).

Add a secondary sort key that prefers rows with a real `account_id` (not empty/"-"). Use existing `_dedup_account_id()` helper at `flex.py:666` which already normalizes "-" → "":

```python
# BEFORE:
    return min(rows, key=lambda row: str(row.get("transaction_id") or ""))

# AFTER:
    def _dedup_sort_key(row: dict[str, Any]) -> tuple[str, int, str, int, str]:
        tid = str(row.get("transaction_id") or "")
        acct = _dedup_account_id(row)
        acct_name = str(row.get("account_name") or "").strip()
        # Prefer rows with a real account_id, then real account_name
        has_acct = 0 if acct else 1
        has_name = 0 if acct_name else 1
        return (tid, has_acct, acct, has_name, acct_name)
    return min(rows, key=_dedup_sort_key)
```

Apply the same change to the `real_rows` branch (line 691). This ensures:
- Primary: sort by `transaction_id` (unchanged behavior for distinct IDs)
- Secondary: prefer rows with a real `account_id` over empty/"-" (uses `_dedup_account_id()` which already handles "-" normalization)
- Tertiary: alphabetical `account_id`
- Quaternary: prefer rows with `account_name` populated
- Quinary: alphabetical `account_name`

This makes account metadata fully deterministic across re-ingests, which matters for account-scoped reads at `transaction_store.py:1003`. (Codex v4 finding #1, v5 finding #2)

#### Fix B: Content-based raw dedup key in `transaction_store.py`

**File**: `inputs/transaction_store.py:1792-1809`

Add income-specific dedup handling **only for synthetic income IDs** (those with `income:` prefix). Preserve native IBKR `transactionID` when present — those are already stable.

```python
if provider == "ibkr_flex":
    trade_id = self._text_or_none(
        row.get("tradeID") or row.get("tradeId") or row.get("transactionID")
        or row.get("transaction_id") or row.get("id")
    )

    # Income rows with synthetic IDs: content-based dedup key
    # (same pattern as ibkr_flex_mtm at line 1810).
    # Synthetic income IDs from normalize_flex_cash_income_trades() historically
    # contained a volatile enumerate() index. Use content key instead.
    if trade_id and str(trade_id).startswith("income:"):
        dt_raw = row.get("date")
        dt = dt_raw.date().isoformat() if hasattr(dt_raw, "date") else str(dt_raw or "")[:10]
        sym = self._text_or_none(row.get("symbol")) or ""
        amt = row.get("amount")
        ccy = self._text_or_none(row.get("currency")) or "USD"
        row_type = str(row.get("type") or "").strip().upper()
        if not dt or amt is None:
            return None
        return f"ibkr_flex_income:{dt}:{sym}:{amt}:{ccy}:{row_type}"

    if not trade_id:
        return None
    # ... rest of existing logic
```

Key differences from original plan:
- **Only triggers for synthetic `income:` prefix** — native IBKR transactionIDs pass through unchanged (Codex finding #4)
- **Excludes `account_id`** from key — matches segment dedup semantics (Codex finding #3)

#### Fix C: Pass stable transaction_id through `NormalizedIncome`

**Files**: `trading_analysis/models.py`, `providers/normalizers/ibkr_flex.py`, `inputs/transaction_store.py`

The v2 approach (removing `account_id` from `_hash_key()`) is unsafe — it modifies the **generic** fallback used by ALL providers, risking false merges for legitimate distinct income events from different accounts or for `PAYMENTINLIEU` vs dividend collisions (Codex v3 finding #1).

Instead, propagate Fix A's stable `transaction_id` through the normalizer so the store can use it directly:

**Step 1**: Add optional `transaction_id` to `NormalizedIncome` (`trading_analysis/models.py:232`):
```python
@dataclass
class NormalizedIncome:
    """Standardized income record for analysis"""
    symbol: str
    income_type: str  # 'dividend', 'interest', 'distribution'
    date: datetime
    amount: float
    source: str = "unknown"
    institution: Optional[str] = None
    account_id: Optional[str] = None
    account_name: Optional[str] = None
    currency: Optional[str] = None
    transaction_id: Optional[str] = None  # NEW — stable ID from source
```

**Step 2**: Pass `transaction_id` in `IBKRFlexNormalizer` (`providers/normalizers/ibkr_flex.py:75-87`):
```python
income_events.append(
    NormalizedIncome(
        symbol=symbol,
        income_type=income_type,
        date=date,
        amount=signed_amount,
        source="ibkr_flex",
        institution=institution,
        account_id=str(txn.get("account_id") or "").strip() or None,
        account_name=str(txn.get("account_name") or "").strip() or None,
        currency=currency,
        transaction_id=txn.get("transaction_id"),  # NEW — from Fix A
    )
)
```

**Step 3**: `store_normalized_income()` at `transaction_store.py:569` already reads `payload.get("transaction_id")`. With `NormalizedIncome` now carrying it, `_as_dict()` will include it → the store uses the stable ID directly → `_hash_key()` fallback only fires for non-IBKR providers (where it remains correct with `account_id` intact).

**No change to `_hash_key()` fallback** — it stays as-is with `account_id`. The fix is provider-specific: IBKR income gets a stable `transaction_id` from the source, other providers keep the generic fallback. (Codex v3 finding #1)

#### Fix D: User-scoped delete-and-rebuild cleanup

**Critical insight from Codex finding #2**: Pruning duplicates leaves survivor rows with OLD dedup keys. Re-ingesting then creates NEW rows with the stable keys → doubles the data. Instead, **delete ALL ibkr_flex income rows for the affected user and re-ingest from scratch**.

**Important**: Scope to `user_id` to avoid touching other users' data. The re-ingest fetches a fresh Flex report which covers the full query window (~12 months), so all income events within that window will be repopulated. Income events outside the window (older than ~12 months) are not recoverable from Flex — but this is already a known limitation of the Flex query window constraint. (Codex v3 finding #2)

```sql
-- Step 1: Delete ibkr_flex income from normalized_income for affected user
DELETE FROM normalized_income
WHERE provider = 'ibkr_flex'
  AND user_id = :user_id;

-- Step 2: Delete ibkr_flex raw rows with synthetic income IDs for affected user
DELETE FROM raw_transactions
WHERE provider = 'ibkr_flex'
  AND user_id = :user_id
  AND dedup_key LIKE '%income:%';
```

Then re-ingest:
```python
_ingest_transactions_inner(user_email="<user_email>", provider="ibkr_flex")
```

This produces ~60 clean rows in `normalized_income` with stable keys. Verify row count before and after.

### Tests

**File**: `tests/ibkr/test_flex.py`

1. **`test_income_transaction_id_stable_across_reorder`**: Feed same income rows in different order → verify all output `transaction_id` values are identical (not dependent on enumerate index)
2. **`test_income_transaction_id_deterministic`**: Same input twice → same output
3. **`test_income_transaction_id_uses_signed_amount`**: Verify positive and negative interest with same abs value get different IDs
4. **`test_segment_dedup_winner_deterministic_account`**: Feed segment duplicates with same content but different account_ids in varying order → verify winner always has the real account_id and stable account metadata

**File**: `tests/inputs/test_transaction_store.py`

4. **`test_ibkr_income_dedup_key_content_based`**: Verify `_dedup_key()` for synthetic income rows returns content-based key, not transaction_id-based
5. **`test_ibkr_income_native_id_preserved`**: Verify `_dedup_key()` for income rows WITH native IBKR transactionID uses the native ID (not content key)
6. **`test_ibkr_income_reingest_no_duplicates`**: Ingest same income events twice → verify row count doesn't increase
7. **`test_normalized_income_transaction_id_passthrough`**: Verify NormalizedIncome with `transaction_id` set → store uses it directly (no `_hash_key()` fallback)
8. **`test_normalized_income_different_accounts_stay_separate`**: Two NormalizedIncome events with same (symbol, date, amount) but different account_id and NO transaction_id → verify they produce different hash keys (generic fallback preserves account distinction)
9. **`test_normalized_income_paymentinlieu_no_collision`**: NormalizedIncome with `income_type="dividend"` amount=+5.00 and `income_type="dividend"` amount=-5.00 (PAYMENTINLIEU) → verify distinct keys

## Issue 2: UNKNOWN Interest Label (Low Priority)

### Root Cause

IBKR margin interest CashTransaction rows have no `symbol` field. `flex.py:710-716` falls back to "UNKNOWN". The `description` field contains identifiable text like "USD Debit Interest for Mar-2025".

### Fix

**File**: `ibkr/flex.py:710-716`

After the existing description-based extraction and before the UNKNOWN fallback, add:
```python
# Extract currency from margin interest description
if not symbol:
    desc_lower = desc.lower() if desc else ""
    if "debit interest" in desc_lower or "credit interest" in desc_lower:
        symbol = "MARGIN_INTEREST"
```

This labels margin interest distinctly from truly unknown symbols, improving readability in income reports.

### Tests

Add assertion to existing `test_normalize_flex_cash_income_trades_maps_dividend_and_interest_rows` or new test:
- Input with `description="USD Debit Interest for Mar-2025"`, no symbol → verify `symbol == "MARGIN_INTEREST"`

## Issue 3: Missing Symbols DSU, TW (Known Limitation)

### Status

DSU (sold 2024-12-31, loss -$104.35) and TW (sold 2025-02-11, loss -$186.05) predate the Flex query window. These trades exist in the IBKR statement SQLite backfill files at `docs/planning/performance-actual-2025/ibkr_statement_frames/`.

### Resolution

No code fix needed. These are part of the broader "19 missing opening trades" issue documented in `TODO.md` under "Realized Performance: Data Quality & Accuracy". The statement SQLite backfill feature (Futures Phase 8 backlog) would address this class of issue.

**Impact**: -$290 in untracked realized losses. Low priority relative to the income duplication bug.

## Implementation Order

1. Fix A (flex.py stable transaction_id) — eliminates root cause at source
2. Fix A2 (deterministic segment dedup winner) — stable account metadata
3. Fix B (store raw dedup key) — defense in depth for synthetic income IDs
4. Fix C (NormalizedIncome transaction_id passthrough) — carries stable ID to normalized layer
5. Tests — all 10 test cases
6. Fix D (user-scoped delete-and-rebuild) — clean slate for existing data
6. Issue 2 (UNKNOWN → MARGIN_INTEREST) — cosmetic improvement
7. Re-ingest IBKR to verify

## Verification

1. `pytest tests/ibkr/test_flex.py -x`
2. `pytest tests/inputs/test_transaction_store.py -x`
3. Live: `fetch_provider_transactions(provider="ibkr_flex")` → verify income row count ≈ 60 (not 285)
4. Live: `get_performance(mode="realized", segment="equities")` → verify dividend/interest totals match actuals

## Codex Review Findings

### v2 Review (4 findings)

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 1 | Fix A/B only fix raw layer; `NormalizedIncome` has no `transaction_id` → store `_hash_key()` still drifts on `account_id` | Blocking | Added Fix C: remove `account_id` from `_hash_key()` fallback |
| 2 | Cleanup migration keeps survivor with old key → re-ingest creates second row | Blocking | Changed to delete-and-rebuild (Fix D) |
| 3 | Content key includes `account_id` + uses `abs(amount)` — mismatches segment dedup semantics | High | Fix A/B now exclude `account_id`, use signed amount |
| 4 | Fix B replaces native IBKR IDs for income rows | Medium | Fix B now only triggers for synthetic `income:` prefix |

### v3 Review (3 findings)

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 1 | Fix C (remove `account_id` from `_hash_key()`) modifies generic fallback — unsafe for multi-account, non-IBKR providers, PAYMENTINLIEU collisions | Blocking | Replaced Fix C: add `transaction_id` field to `NormalizedIncome`, pass stable ID through normalizer. Generic `_hash_key()` fallback stays unchanged. |
| 2 | Fix D has no `user_id` scope and assumes full-history re-ingest. Can delete other users' data, loses out-of-window income | Blocking | Scoped cleanup SQL to `:user_id`. Documented that Flex window is the recovery boundary. |
| 3 | Tests miss correctness at normalized identity boundary: different accounts staying separate, PAYMENTINLIEU collisions, native ID passthrough | Medium | Added tests 7-9: transaction_id passthrough, different-account separation, PAYMENTINLIEU non-collision |

### v4 Review (1 finding)

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 1 | After Fix A, segment duplicates share same `transaction_id` → `_select_dedup_winner()` tiebreak is nondeterministic → `account_id`/`account_name` metadata flips across re-ingests → affects account-scoped reads | Medium | Added Fix A2: secondary sort key in `_select_dedup_winner()` preferring rows with real `account_id`. Added test 4 for deterministic winner. |

### v5 Review (2 findings)

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 1 | Multi-account Flex collision: excluding `account_id` from synthetic ID could merge distinct cross-account events | High | Documented single-account scope assumption. Consistent with existing segment dedup design. Multi-account would need ID redesign. |
| 2 | Fix A2 tiebreaker incomplete: same `account_id` but different `account_name` completeness → input-order dependent. Should also use `_dedup_account_id()` instead of ad-hoc "-" handling | Medium | Extended sort key to include `account_name` (populated > empty). Use `_dedup_account_id()` for "-" normalization. |

## Files Changed

| File | Change |
|------|--------|
| `ibkr/flex.py` | Stable content-hash transaction_id for income (Fix A); deterministic dedup winner (Fix A2); MARGIN_INTEREST symbol (Issue 2) |
| `trading_analysis/models.py` | Add optional `transaction_id` field to `NormalizedIncome` (Fix C) |
| `providers/normalizers/ibkr_flex.py` | Pass `transaction_id` from source dict to `NormalizedIncome` (Fix C) |
| `inputs/transaction_store.py` | Content-based raw dedup key for synthetic income (Fix B) |
| `tests/ibkr/test_flex.py` | 4 tests: stability, determinism, signed amount, dedup winner account stability |
| `tests/inputs/test_transaction_store.py` | 6 tests: content key, native ID preserved, reingest, passthrough, account separation, PAYMENTINLIEU |

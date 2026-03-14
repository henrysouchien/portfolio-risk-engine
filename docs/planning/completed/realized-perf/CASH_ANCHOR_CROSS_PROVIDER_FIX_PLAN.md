# Plan: Fix Cash Anchor Cross-Provider Position Matching

## Context

`_cash_anchor_offset_from_positions()` in `engine.py:1675-1693` scans position rows to find current cash balances, then back-solves the starting cash to anchor inception NAV. **Bug**: When `source="ibkr_flex"`, the function filters position rows by provider source — but IBKR cash positions come through SnapTrade (source=`snaptrade`), not `ibkr_flex`. Result: `observed_end_cash = 0`, which produces a wrong anchor and distorts the entire TWR chain (engine shows -20% vs IBKR statement +0.29%).

The root issue: source-based matching is the wrong abstraction. Positions and transactions can come from different providers for the same account. The function should match by **account identity**, not provider source.

**Known secondary issue (out of scope)**: SnapTrade doesn't expose IBKR's USD margin balance. Even with this fix, the observed cash will be incomplete (~-$2,196 vs real -$8,727). User plans to address separately by switching to IBKR API for positions.

## The Fix

For source-scoped queries (`source != "all"`), replace source-based position matching with **account-alias matching**. FIFO transactions carry `account_id` (e.g., IBKR native `U2471778`). Position rows carry their own `account_id` (e.g., SnapTrade UUID `cb7a1987`). `TRADE_ACCOUNT_MAP` maps these via `resolve_account_aliases()` from `providers/routing_config.py` (already imported at `engine.py:34`).

For `source="all"`, the existing behavior (accept all rows) is preserved — alias scoping would unnecessarily exclude accounts that have positions but no transactions (e.g., bank accounts with cash).

### Double-counting safety

When `source != "all"`, consolidation is disabled (`performance_helpers.py:46-47`), so duplicate cash rows from multiple providers CAN coexist in the position list. To prevent double-counting **in alias-matching mode**, the function deduplicates cash rows by `(alias_group, ticker)`. The alias group is derived from whichever row `account_id` actually matched the alias set. This means:
- Same account via two providers (e.g., SnapTrade CUR:GBP + Plaid CUR:GBP for IBKR) → deduplicated (same alias group)
- Two different accounts with the same currency (e.g., two IBKR accounts each with CUR:USD) → both counted (different alias groups)
- In fallback mode (no aliases, alias matching found 0 rows, or `source="all"`), no dedup — preserving existing behavior

### Step 1: Build transaction alias set

**File:** `core/realized_performance/engine.py` — inside `_analyze_realized_performance_single_scope()`, before `_cash_anchor_offset_from_positions()` definition (~line 1674). Both functions are siblings nested under the same outer function.

Build aliases from `account_id` only (not `account_name` — generic names like "Individual Account" could over-match via `resolve_account_aliases()` which returns singletons for unmapped values):

```python
_txn_account_aliases: set[str] = set()
if source != "all":
    for txn in fifo_transactions:
        aid = str(txn.get("account_id") or "").strip().lower()
        if aid:
            for alias in resolve_account_aliases(aid):
                _txn_account_aliases.add(alias)
```

Note: `resolve_account_aliases` is already imported at `engine.py:34`. The alias set is only built for source-scoped queries; `source="all"` skips this entirely and uses the existing all-rows behavior.

**Edge case — empty aliases**: Backfill entries (`backfill.py:145`) omit `account_id`. If `fifo_transactions` contains only backfill entries, `_txn_account_aliases` will be empty. In that case, the function falls back to the existing source/institution matching — which is correct, since backfill-only scenarios don't have the cross-provider mismatch.

### Step 2: Rewrite `_cash_anchor_offset_from_positions()` with account-first matching

**File:** `core/realized_performance/engine.py:1675-1693`

When we have transaction account aliases (source-scoped), use them as the primary matching strategy. Deduplicate by `(alias_group, ticker)` to prevent double-counting. Fall back to old source/institution logic when no aliases exist. `source="all"` bypasses alias matching entirely.

```python
def _cash_anchor_offset_from_positions() -> Tuple[float, int]:
    rows = list(getattr(getattr(positions, "data", None), "positions", []) or [])

    def _scan_cash(use_aliases: bool) -> Tuple[float, int]:
        cash = 0.0
        count = 0
        seen_cash_keys: set[Tuple[frozenset, str]] = set()
        for row in rows:
            row_account = str(row.get("account_id") or "").strip().lower()

            if use_aliases:
                if not row_account or row_account not in _txn_account_aliases:
                    continue
            elif institution:
                brokerage_name = str(row.get("brokerage_name") or "")
                if not match_institution(brokerage_name, institution):
                    continue
            elif source != "all":
                matches, _ = holdings._provider_matches_from_position_row(row)
                if source not in matches:
                    continue

            if account and not holdings._match_account(row, account):
                continue

            ticker = str(row.get("ticker") or "").strip().upper()
            kind = str(row.get("type") or "").strip().lower()
            if ticker.startswith("CUR:") or kind in {"cash", "currency", "fx", "forex"}:
                if use_aliases:
                    # Deduplicate by (alias_group, ticker) to prevent
                    # double-counting from unconsolidated multi-provider rows.
                    alias_group = resolve_account_aliases(row_account)
                    dedup_key = (alias_group, ticker)
                    if dedup_key in seen_cash_keys:
                        continue
                    seen_cash_keys.add(dedup_key)
                cash += _helpers._as_float(row.get("value"), 0.0)
                count += 1
        return float(cash), count

    # Primary: try alias-based matching (cross-provider safe)
    if _txn_account_aliases:
        result = _scan_cash(use_aliases=True)
        if result[1] > 0:
            return result
        # Alias matching found no cash — fall back to source/institution
        warnings.append(
            "Cash anchor: alias matching found no cash rows; "
            "falling back to source/institution matching."
        )
    return _scan_cash(use_aliases=False)
```

**Priority order:**
1. If `source != "all"` and we have transaction account aliases → match by account identity (cross-provider safe)
2. If alias matching found 0 rows → fall back to source/institution matching with warning
3. If no aliases (backfill-only or `source="all"`) → existing behavior:
   - `institution` filter → match by institution name
   - `source != "all"` → match by provider source
   - `source == "all"` → accept all rows

### Step 3: Update caller

**File:** `core/realized_performance/engine.py` ~line 1718

```python
observed_end_cash, _cash_anchor_matched_rows = _cash_anchor_offset_from_positions()
```

### Step 4: Add diagnostic metadata

**File:** `core/realized_performance/engine.py` ~line 2325

Add after `cash_backsolve_start_usd`:
```python
"cash_backsolve_matched_rows": _cash_anchor_matched_rows,
```

**File:** `core/result_objects/realized_performance.py`

Add field to `RealizedMetadata` dataclass (~line 132, after `cash_backsolve_start_usd`):
```python
cash_backsolve_matched_rows: int = 0
```

Add to `to_dict()` (~line 212, after `cash_backsolve_start_usd`):
```python
"cash_backsolve_matched_rows": self.cash_backsolve_matched_rows,
```

Add to `from_dict()` (~line 297, after `cash_backsolve_start_usd`):
```python
cash_backsolve_matched_rows=int(d.get("cash_backsolve_matched_rows", 0) or 0),
```

### Step 5: Tests

**File:** `tests/core/test_realized_performance_analysis.py`

Tests must monkeypatch `resolve_account_aliases` directly (or patch `_ACCOUNT_EQUIV` dict) since `TRADE_ACCOUNT_MAP` equivalence classes are built at import time.

1. **Cross-provider matching**: Position rows with `account_id="cb7a1987"`, FIFO transactions with `account_id="U2471778"`, alias resolver patched to return equivalence class `{cb7a1987, u2471778}`. Verify cash rows found.
2. **Unrelated account exclusion**: Position rows from a different account (e.g., Schwab `4AE3...`) excluded when aliases only contain IBKR accounts.
3. **No-alias fallback**: When `_txn_account_aliases` is empty (e.g., backfill-only), source/institution matching still works as before.
4. **Dedup same account**: Two unconsolidated position rows for `CUR:GBP` from different providers for the same account (same alias group) — only one contributes to observed_cash.
5. **Multi-account same currency**: Two different matched accounts each with `CUR:USD` — both counted (different alias groups, same ticker).
6. **Alias-to-fallback**: Aliases exist but no position rows match any alias — function falls back to source/institution matching and emits a warning.
7. **source="all" skips aliases**: Even with non-empty aliases, `source="all"` accepts all cash rows (existing behavior preserved).

## Files Modified

| File | Change |
|------|--------|
| `core/realized_performance/engine.py` (~1674) | Build `_txn_account_aliases` set (account_id only, source != "all" only) |
| `core/realized_performance/engine.py:1675-1693` | Account-first matching + alias-group dedup |
| `core/realized_performance/engine.py` (~1718) | Unpack `(cash, count)` tuple |
| `core/realized_performance/engine.py` (~2325) | Add `cash_backsolve_matched_rows` diagnostic |
| `core/result_objects/realized_performance.py` | Add `cash_backsolve_matched_rows` to dataclass + `to_dict` + `from_dict` |
| `tests/core/test_realized_performance_analysis.py` | 7 tests |

## Verification

```bash
pytest tests/core/test_realized_performance_analysis.py -x -q
pytest tests/core/ -x -q -k "realized"
```

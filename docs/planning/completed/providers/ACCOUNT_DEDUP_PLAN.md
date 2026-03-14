# Deduplicate and Filter Tradeable Accounts in Trade Preview

## Context

When `preview_trade` is called without an `account_id`, it lists all tradeable accounts from all adapters. Two problems:

1. **Duplicate IBKR account** — SnapTrade returns `cb7a1987-...` (its UUID for the linked IBKR account) and IBKR returns `U2471778` (native ID). These are the same account. `TRADE_ACCOUNT_MAP` already maps `cb7a1987:U2471778` but this is only used during routing, not during listing.

2. **Dormant accounts** — Accounts with `$0.00` cash appear in the list (e.g., `87656165`, `51388013`). These are likely inactive but still clutter the selection.

From an agent's perspective, the current list is confusing — 5 accounts when only 2-3 are actively used, with duplicates.

## Implementation

### 1. Apply dedup + dormant filtering in `_resolve_target_account()`, NOT in `list_tradeable_accounts()`

**Important:** `_resolve_target_account()` uses `list_tradeable_accounts()` for both explicit `account_id` lookup AND auto-selection. If we filter the list itself, explicitly passing a deduped/dormant account ID would fail with "not authorized." The filtering must only apply to the **auto-select path** (no `account_id` provided).

**`services/trade_execution_service.py`** — `_resolve_target_account()` (~line 1795)

`list_tradeable_accounts()` stays unchanged. Instead, add a module-level helper and apply it in the auto-select branch:

```python
def _filter_for_auto_select(accounts: List[BrokerAccount]) -> List[BrokerAccount]:
    """Dedup + dormant filter for the auto-select path (no explicit account_id)."""
    # Dedup: if a SnapTrade account maps to a native account also in the list, drop the SnapTrade entry
    native_ids_present = {a.account_id for a in accounts if a.provider != "snaptrade"}
    deduped = []
    for account in accounts:
        if account.provider == "snaptrade" and account.account_id in TRADE_ACCOUNT_MAP:
            native_id = TRADE_ACCOUNT_MAP[account.account_id]
            if native_id in native_ids_present:
                continue  # Skip — native adapter already provides this account
        deduped.append(account)

    # Filter dormant accounts (keep if any non-dormant exist)
    active = [a for a in deduped if not _is_dormant(a)]
    return active if active else deduped
```

Then in `_resolve_target_account()`, when no `account_id` is provided (~line 1827):

```python
# No account_id provided: auto-select from filtered list
filtered = _filter_for_auto_select(accounts)
if len(filtered) == 1:
    return filtered[0]
if not filtered:
    raise ValueError("No tradeable accounts found")

# Multiple accounts require selection — show filtered list
choices = [
    f"{a.account_name or 'Unnamed'} ({a.account_id}) cash=${(a.cash_balance or 0):,.2f}"
    for a in filtered
]
raise ValueError("Multiple tradeable accounts found. Please specify account_id. Available: " + "; ".join(choices))
```

**Why this works:** Explicit `account_id` lookups still use the full unfiltered list (lines 1799-1825). Only the "pick for me" path uses the cleaned-up list.

### 2. Module-level `_is_dormant()` helper

```python
def _is_dormant(account: BrokerAccount) -> bool:
    cash = account.cash_balance or 0.0
    funds = account.available_funds or 0.0
    return cash == 0.0 and funds == 0.0
```

Accounts with negative cash (margin) are NOT dormant — they're active.

## Notes

- **`TRADE_ACCOUNT_MAP` is already imported** in `trade_execution_service.py` (line 29). No new import needed.
- **`_is_dormant` should be module-level** (not instance method), matching existing helper patterns like `_to_float()` in the same file.
- **Metadata loss on dedup is acceptable** — SnapTrade entries have richer metadata (`institution_name`, `authorization_id`) vs IBKR's generic entries, but we're only filtering the *listing* for account selection. Routing and execution still use the full adapter data. The native IBKR entry is preferred because trades route there directly.

## Files Modified

| File | Change |
|------|--------|
| `services/trade_execution_service.py` | `_resolve_target_account()`: filter auto-select path with `_filter_for_auto_select()`. Add module-level `_is_dormant()` + `_filter_for_auto_select()` helpers (~20 lines). `list_tradeable_accounts()` unchanged. |

### Tests

Add to `tests/services/test_trade_execution_service_preview.py` (or new file):

1. **Dedup test** — Mock two adapters returning overlapping accounts (SnapTrade UUID + IBKR native for same account via TRADE_ACCOUNT_MAP). Verify only native entry returned.
2. **Dedup fallback test** — When IBKR adapter is down (native not in list), SnapTrade entry preserved.
3. **Dormant filter test** — Accounts with `$0.0` cash and funds filtered out.
4. **Dormant fallback test** — When all accounts are dormant, return full list (don't filter everything away).
5. **Negative cash preserved** — Margin accounts with negative cash are NOT filtered.

## Verification

1. `pytest tests/` — existing tests pass
2. `preview_trade(ticker="FIG", quantity=10, side="BUY")` without `account_id` — should show fewer accounts in the error, no duplicate IBKR entry, no $0 accounts
3. With IBKR down: SnapTrade IBKR account should still appear (not deduped since native isn't in list)

# Provider Routing Gaps — 6 Fixes

**Status**: COMPLETE — commit `66e85369`

## Context
Audit (`docs/planning/completed/PROVIDER_ROUTING_AUDIT.md`, 2026-03-03) found 6 minor gaps in provider routing consistency. None are blocking — all have workarounds. Fixes are ordered by effort (lightest first).

---

## Fix 1: Transaction Providers Missing `is_provider_available()` Check
**Severity:** Very Low | **Effort:** ~5 min | **File:** `trading_analysis/data_fetcher.py`

`_build_default_transaction_registry()` (lines 674-691) only checks `is_provider_enabled()`. Position service checks both `is_provider_enabled()` AND `is_provider_available()` (at least for Schwab). Without the availability check, transaction providers register even when credentials are missing, causing fetch-time failures instead of clean skips.

**Change:** Add `is_provider_available()` guard to each provider registration in `_build_default_transaction_registry()`:

```python
if is_provider_enabled("schwab") and is_provider_available("schwab"):
    registry.register_transaction_provider(SchwabTransactionProvider())
if is_provider_enabled("ibkr_flex") and is_provider_available("ibkr_flex"):
    registry.register_transaction_provider(IBKRFlexTransactionProvider())
# plaid and snaptrade: keep enabled-only (no credential check needed — they use per-user tokens from AWS)
```

Note: Only Schwab and IBKR Flex need the availability guard — they require env-level credentials. Plaid and SnapTrade use per-user tokens fetched at runtime.

**Test:** Add 1 test in `tests/providers/test_provider_switching.py` (existing provider routing test file) — mock `is_provider_available("schwab")` → False, verify Schwab not registered in transaction registry.

---

## Fix 2: Ephemeral IBKR `owns_account()` — Docstring Clarification
**Severity:** Low | **Effort:** ~2 min | **File:** `brokerage/ibkr/adapter.py`

`owns_account()` (lines 114-125) returns `False` when `IBKR_AUTHORIZED_ACCOUNTS` is empty. This is intentional — ephemeral mode shouldn't auto-claim accounts. But the behavior isn't documented.

**Change:** Expand the docstring on `owns_account()` to clarify:

```python
def owns_account(self, account_id: str) -> bool:
    """Check if this adapter handles the given account.

    Uses the static IBKR_AUTHORIZED_ACCOUNTS env var. Returns False when
    the list is empty (ephemeral connection mode) — this is intentional to
    prevent auto-claiming accounts without explicit configuration. Production
    deployments must set IBKR_AUTHORIZED_ACCOUNTS.
    """
```

No behavioral change. No test needed.

---

## Fix 3: Account Alias Resolution — Clarifying Comment
**Severity:** Very Low | **Effort:** ~2 min | **File:** `brokerage/ibkr/adapter.py`

`_resolve_native_account()` (line 112) uses `TRADE_ACCOUNT_MAP.get()` (one-way directional lookup), while `match_account()` in `routing_config.py` uses `resolve_account_aliases()` (bidirectional equivalence classes). These are intentionally different: write path needs directional mapping (aggregator→native), read path needs bidirectional matching.

**Change:** Add clarifying comment on `_resolve_native_account()`:

```python
def _resolve_native_account(self, account_id: str) -> str:
    """Translate aggregator account ID to native IBKR account ID if mapped.

    Uses directional TRADE_ACCOUNT_MAP lookup (aggregator → native), not
    resolve_account_aliases() equivalence classes. This is intentional:
    trade submission needs the specific native ID, not all aliases.
    """
    return TRADE_ACCOUNT_MAP.get(account_id, account_id)
```

No behavioral change. No test needed.

---

## Fix 4: Account Filtering on Transaction Fetcher
**Severity:** Low | **Effort:** ~15 min | **File:** `trading_analysis/data_fetcher.py`

`get_all_positions()` supports `account` filter (position_service.py:322-332 with `resolve_account_aliases()`). `fetch_transactions_for_source()` only supports `institution` filter — no `account` param.

**Change:** Add optional `account` parameter to `fetch_transactions_for_source()` (line 857). After the institution filter, apply account-level filter using `resolve_account_aliases()`:

```python
def fetch_transactions_for_source(
    user_email: str,
    source: str,
    institution: Optional[str] = None,
    account: Optional[str] = None,  # NEW
    registry=None,
) -> FetchResult:
    ...
    # After existing institution filter (line ~888):
    if account:
        _filter_provider_payload_for_account(result.payload, account)
    return result
```

New helper `_filter_provider_payload_for_account()` — same pattern as `_filter_provider_payload_for_institution()` (lines 618-646) but filters on `account_id`/`account_name` fields using `resolve_account_aliases()`:

```python
def _filter_provider_payload_for_account(
    provider_payload: dict, account_filter: str
) -> None:
    from providers.routing_config import resolve_account_aliases
    aliases = resolve_account_aliases(account_filter)
    _ACCOUNT_FIELDS = {
        "plaid_transactions": ("_account_id", "_account_name"),
        "snaptrade_activities": ("_account_id", "_account_name"),
        "ibkr_flex_trades": ("account_id",),
        "ibkr_flex_cash_rows": ("account_id",),
        "ibkr_flex_futures_mtm": ("account_id",),
        "schwab_transactions": ("_account_hash", "_account_number"),
    }
    for key, fields in _ACCOUNT_FIELDS.items():
        records = provider_payload.get(key)
        if not records:
            continue
        provider_payload[key] = [
            row for row in records
            if any(
                str(row.get(f) or "").strip().lower() in aliases
                for f in fields
            )
        ]
```

**Thread `account` through callers of `fetch_transactions_for_source()`:**
- `_prefetch_fifo_transactions()` in `core/realized_performance_analysis.py:5281` — add `account` param, pass to `fetch_transactions_for_source()`
- `core/realized_performance_analysis.py:3216` — call site passes `institution`, add `account` pass-through
- `mcp_tools/trading_analysis.py:102` — already has `account` in scope from tool params, pass to `fetch_transactions_for_source()`
- `mcp_tools/tax_harvest.py:118` — already has `account` in scope from tool params, pass to `fetch_transactions_for_source()`
- `run_trading_analysis.py:122` — CLI script, no account param needed (no change)

**Test:** 2 tests — account filter keeps matching rows, account filter with alias resolves correctly.

---

## Fix 5: Positions Direct-First Optimization
**Severity:** Low | **Effort:** ~2 min | **File:** `services/position_service.py`

Transactions use `direct_first` fetch policy — direct providers run first, aggregators skip institutions with healthy direct coverage. Positions fetch all providers equally. For explicitly-routed institutions (e.g., Schwab), `partition_positions()` filters to the preferred provider source. For others, multiple provider sources may remain. Adding pre-fetch skipping adds complexity for minimal gain — position fetches are fast and cached.

**Change:** Add a comment in `get_all_positions()` explaining why direct-first is not implemented for positions:

```python
# Fetch all position providers. Unlike transactions (which use direct_first
# to avoid redundant aggregator fetches), positions are fetched from all
# providers equally. partition_positions() filters by routing preference
# for explicitly-routed institutions (e.g., Schwab direct over aggregator).
# Direct-first optimization is not worth the complexity here — position
# fetches are fast and cached.
```

No behavioral change. No test needed.

---

## Fix 6: No IBKR Direct Position Provider
**Severity:** Low | **Effort:** ~2 min | **File:** `providers/routing_config.py`

`IBKRClient.get_positions()` exists but no `IBKRPositionProvider` wraps it. IBKR positions come via aggregators only. Adding a direct provider would create a third data source for the same positions, requiring careful dedup for minimal benefit.

**Change:** Add a comment in `POSITION_ROUTING`:

```python
POSITION_ROUTING = {
    "charles_schwab": "schwab",
    # "interactive_brokers": "ibkr" — not implemented. IBKR positions come via
    # aggregators (SnapTrade/Plaid). IBKRClient.get_positions() exists but adding
    # a direct provider would create dedup complexity for minimal benefit.
}
```

No behavioral change. No test needed.

---

## Summary

| Fix | Type | Behavioral Change? | Files |
|-----|------|-------------------|-------|
| 1. Transaction `is_provider_available()` | Guard | Yes — skip unconfigured providers | `data_fetcher.py` |
| 2. `owns_account()` docstring | Documentation | No | `adapter.py` |
| 3. `_resolve_native_account()` comment | Documentation | No | `adapter.py` |
| 4. Transaction `account` filter | Feature | Yes — new param | `data_fetcher.py` |
| 5. Position direct-first comment | Documentation | No | `position_service.py` |
| 6. IBKR position provider comment | Documentation | No | `routing_config.py` |

## Files to Modify
- `trading_analysis/data_fetcher.py` — Fix 1 (availability guard) + Fix 4 (account filter + helper)
- `brokerage/ibkr/adapter.py` — Fix 2 (docstring) + Fix 3 (comment)
- `services/position_service.py` — Fix 5 (comment)
- `providers/routing_config.py` — Fix 6 (comment)
- `core/realized_performance_analysis.py` — Fix 4 (thread `account` through `_prefetch_fifo_transactions()` and its call site at line 3216)
- `mcp_tools/trading_analysis.py` — Fix 4 (pass `account` to `fetch_transactions_for_source()`)
- `mcp_tools/tax_harvest.py` — Fix 4 (pass `account` to `fetch_transactions_for_source()`)

## Tests
- Fix 1: 1 test in `tests/providers/test_provider_switching.py` (unavailable provider skipped)
- Fix 4: 2 tests (account filter keeps matching rows, account filter with alias resolves correctly)
- Total: 3 new tests

## Verification
1. `python -m pytest tests/trading_analysis/ tests/providers/ tests/services/ -x -v`
2. Existing routing tests still pass
3. `get_performance(mode="realized", institution="merrill")` still returns results

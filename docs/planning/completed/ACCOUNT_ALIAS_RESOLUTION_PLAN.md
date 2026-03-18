# Account Alias Resolution Fix

## Context
IBKR realized account filtering splits one logical account into two scopes because position identities (SnapTrade UUIDs/display names) and transaction identities (IBKR U-numbers) never resolve to the same canonical account. Result: `get_performance(account="U2471778")` finds IBKR Flex transactions but zero SnapTrade positions — the account appears split.

`TRADE_ACCOUNT_MAP` (env var) already maps SnapTrade UUIDs → IBKR U-numbers for trade routing, but this mapping is never used by account matching functions that filter positions/transactions.

## Root Cause
Seven independent account matchers all do pure string comparison with no alias resolution:

**Core matchers (3):**
1. `core/realized_performance_analysis.py:651` — `_match_account(row, filter)` for position/transaction filtering
2. `trading_analysis/analyzer.py:473` — `_match_account(filter, account_id=, account_name=)` for FIFO filtering
3. `services/position_service.py:321-329` — inline pandas `.eq()` for position loading

**Local copies in mcp_tools/ (3) — identical logic, not imported from core:**
4. `mcp_tools/trading_analysis.py:21` — `_match_account()` for trade/transaction re-filtering
5. `mcp_tools/tax_harvest.py:109` — `_match_account()` for FIFO/position filtering
6. `mcp_tools/positions.py:35` — `_match_account()` for position monitor view

**Different pattern (1):**
7. `mcp_tools/basket_trading.py:54` — direct `account_id == target_account` equality (no account_name check)

## Fix

### Step 1 — Centralized alias resolver (`providers/routing_config.py`)
Build equivalence classes from existing `TRADE_ACCOUNT_MAP`. Groups all aggregator IDs that map to the same native ID. For example, if `uuid1→U123` and `uuid2→U123`, then filtering by any of `{uuid1, uuid2, U123}` matches all three. (Note: `TRADE_ACCOUNT_MAP` is always flat aggregator→native, so simple grouping by native ID is sufficient — no graph traversal needed.)

```python
# Build equivalence classes: group all IDs that map to the same native ID.
_ACCOUNT_EQUIV: Dict[str, frozenset[str]] = {}
_groups: Dict[str, set[str]] = {}  # native_id → {all aliases including self}
for agg_id, native_id in TRADE_ACCOUNT_MAP.items():
    agg_norm = agg_id.strip().lower()
    native_norm = native_id.strip().lower()
    group = _groups.setdefault(native_norm, {native_norm})
    group.add(agg_norm)
for group in _groups.values():
    frozen = frozenset(group)
    for member in group:
        _ACCOUNT_EQUIV[member] = frozen

def resolve_account_aliases(account: str) -> frozenset[str]:
    """Return full equivalence class of account identifiers (including input)."""
    norm = account.strip().lower()
    return _ACCOUNT_EQUIV.get(norm, frozenset({norm}))
```

### Step 2 — Add shared `match_account()` to `providers/routing_config.py`
Co-locate with `resolve_account_aliases()` to avoid import cycles (`mcp_tools/` imports from `trading_analysis/` which would create a cycle if we put it in `mcp_tools/common.py`):

```python
def match_account(account_filter: str, *, account_id: Any, account_name: Any) -> bool:
    """Match account filter against account_id or account_name with alias resolution."""
    normalized_filter = str(account_filter or "").strip().lower()
    if not normalized_filter:
        return True
    aliases = resolve_account_aliases(normalized_filter)
    account_id_norm = str(account_id or "").strip().lower()
    account_name_norm = str(account_name or "").strip().lower()
    return bool(aliases & {account_id_norm, account_name_norm} - {""})
```

### Step 3 — Replace all 7 matching sites
Replace all local `_match_account()` copies and inline comparisons with imports from `providers/routing_config.py`:

- `core/realized_performance_analysis.py:651` — replace `_match_account()` body with alias-aware version (keep local function, call `resolve_account_aliases` internally since it takes `row` dict, different signature)
- `trading_analysis/analyzer.py:473` — import `match_account` from `providers/routing_config.py`, replace local `_match_account`
- `services/position_service.py:321-329` — use `resolve_account_aliases()` with `.isin(aliases)` instead of `.eq()`
- `mcp_tools/trading_analysis.py:21` — delete local `_match_account`, import from `providers/routing_config.py`
- `mcp_tools/tax_harvest.py:109` — delete local `_match_account`, import from `providers/routing_config.py`
- `mcp_tools/positions.py:35` — delete local `_match_account`, import from `providers/routing_config.py`
- `mcp_tools/basket_trading.py:54` — add alias resolution to the direct equality check

### Step 4 — Fix `_discover_account_ids` in `core/realized_performance_analysis.py:5286`
After collecting `from_positions` and `from_transactions`:
- For each pair of entries that are aliases (via `resolve_account_aliases`), merge into one canonical ID
- Canonical preference: U-numbers over UUIDs (check `_IBKR_ACCOUNT_ID_RE` pattern)
- Preserve existing `_looks_like_display_name()` heuristic — display names should still be filtered when they have zero matching transactions
- Handle case where rows have both `account_name` and `account_id` — collect both, then canonicalize

### Step 5 — Tests (~18)
**Alias resolver:**
1. `resolve_account_aliases("U2471778")` returns `{"u2471778", "<uuid>"}`
2. `resolve_account_aliases("<uuid>")` returns both directions
3. `resolve_account_aliases("unknown")` returns `{"unknown"}` only
4. Many-to-one grouping: `uuid1→U123, uuid2→U123` — filtering by `uuid1` returns `{uuid1, uuid2, u123}` (full equivalence class)

**Shared match_account:**
5. `match_account("U2471778", account_id="<uuid>", account_name="")` → True
6. `match_account("<uuid>", account_id="U2471778", account_name="")` → True
7. `match_account("U2471778", account_id="other", account_name="")` → False
8. Empty filter always returns True
9. Display name filter: `match_account("Interactive Brokers (Henry)", account_id="uuid", account_name="Interactive Brokers (Henry)")` → True (still works via account_name)

**Integration (per-site verification):**
10. `core/realized_performance_analysis._match_account(row_with_uuid, "U2471778")` → True
11. `TradingAnalyzer._apply_account_filter` with U-number filter matches transactions with UUID account_id
12. Position service filter with U-number matches UUID positions (pandas path)
13. `mcp_tools/trading_analysis` re-filter path with alias → matches
14. `mcp_tools/tax_harvest` FIFO filter path with alias → matches
15. `mcp_tools/positions` monitor filter path with alias → matches
16. `basket_trading` direct equality with alias resolution works
17. `_discover_account_ids` merges aliased accounts into one canonical
18. `_discover_account_ids` with both `account_name` and `account_id` on rows — canonical preference works

## Files to Modify
- `providers/routing_config.py` — `_ACCOUNT_EQUIV` + `resolve_account_aliases()` + `match_account()`
- `core/realized_performance_analysis.py` — `_match_account()` + `_discover_account_ids()`
- `trading_analysis/analyzer.py` — replace local `_match_account` with import from `providers/routing_config.py`
- `services/position_service.py` — account filter block (lines 321-329)
- `mcp_tools/trading_analysis.py` — delete local `_match_account`, import from `providers/routing_config.py`
- `mcp_tools/tax_harvest.py` — delete local `_match_account`, import from `providers/routing_config.py`
- `mcp_tools/positions.py` — delete local `_match_account`, import from `providers/routing_config.py`
- `mcp_tools/basket_trading.py` — add alias resolution to direct equality check
- New test file `tests/providers/test_account_aliases.py`

## Fallback Behavior
- Accounts **without** `TRADE_ACCOUNT_MAP` entries: `resolve_account_aliases()` returns `{input}` — same behavior as before (pure string match). No regression.
- Display name filters (e.g., `"Interactive Brokers (Henry Chien)"`): still match via `account_name` field as before. Alias resolution adds UUID/U-number bridging on top.

## Verification
1. `python -m pytest tests/providers/ tests/core/ tests/services/ tests/trading_analysis/ tests/mcp_tools/ -x`
2. Run new alias resolution tests
3. Live: `get_performance(mode="realized", institution="ibkr", account="U2471778")` — verify both positions AND transactions present

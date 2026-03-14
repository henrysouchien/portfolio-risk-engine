# Plan: MCP Brokerage Alias Resolution

**Status:** COMPLETE
**Created:** 2026-02-16

## Context

MCP tools that filter by brokerage name (`get_positions`, `get_portfolio_news`, `get_portfolio_events_calendar`) use plain substring matching on the `brokerage_name` field. This means `"ibkr"` doesn't match "Interactive Brokers" — you have to type `"interactive"` or `"brokers"`.

A separate alias system already exists for transaction routing (`INSTITUTION_SLUG_ALIASES` in `settings.py`), but that maps formal institution names to canonical slugs for internal infrastructure. MCP shorthands are a different concern — user-facing convenience for casual tool queries. These should be kept separate.

## Design

### New file: `mcp_tools/aliases.py`

Centralized MCP-level brokerage shorthand resolution. Small module — a dict + a helper function.

```python
# Common shorthands users/Claude might use for brokerages.
_BROKERAGE_SHORTHANDS: dict[str, str] = {
    "ibkr": "interactive brokers",
    "bofa": "merrill",
    "ml": "merrill",
}

def match_brokerage(query: str, brokerage_name: str) -> bool:
    """Check if query matches brokerage_name (substring, case-insensitive, alias-aware).

    Handles normalization: strip, lowercase, safe string coercion for None/non-string.
    Returns False for empty/whitespace-only query or brokerage_name.
    """
```

Note: `"ib"` omitted — too short, risks accidental substring matches on future brokerage names.

Logic:
1. Normalize both inputs: `str(value or "").strip().lower()`. Return False if either is empty after normalization.
2. If `query` substring-matches `brokerage_name` directly → True (existing behavior preserved)
3. If `query` is a known shorthand, also try the expanded form as substring → True if that matches
4. Otherwise → False

### Callers

| File | Current code | Change |
|------|-------------|--------|
| `mcp_tools/positions.py:131-136` | `brokerage_lower in p.get('brokerage_name', '').lower()` | Use `match_brokerage(brokerage, name)` |
| `mcp_tools/news_events.py:74-78` | `account_lower in (p.get("brokerage_name") or "").lower()` | Use `match_brokerage(account, name)` |

In `news_events.py`, the existing whitespace guard (`if account and not account.strip(): account = None`) can be kept as-is — `match_brokerage` also handles it, but belt-and-suspenders is fine.

### Tests: `tests/mcp_tools/test_brokerage_aliases.py`

Unit tests for `match_brokerage()` (~8 tests):
1. Direct substring match: `"interactive"` matches "Interactive Brokers" → True
2. Shorthand resolves: `"ibkr"` matches "Interactive Brokers" → True
3. Shorthand resolves: `"bofa"` matches "Merrill" → True
4. Shorthand resolves: `"ml"` matches "Merrill" → True
5. No match: `"fidelity"` vs "Interactive Brokers" → False
6. Case insensitive: `"IBKR"` matches "Interactive Brokers" → True
7. None/empty handling: `match_brokerage(None, "Interactive Brokers")` → False
8. None/empty handling: `match_brokerage("ibkr", None)` → False

### Integration tests for `news_events.py`

Update `test_load_portfolio_symbols_account_filter` to use `account="ibkr"` against positions with `brokerage_name="Interactive Brokers"` (no "ibkr" substring in the name). This proves the alias expansion path, not just substring matching.

### Integration test for `positions.py`

Add `test_get_positions_brokerage_alias` in `tests/mcp_tools/test_brokerage_aliases.py`:
- Mock `PositionService.get_all_positions` returning positions with mixed `brokerage_name` values ("Interactive Brokers", "Merrill")
- Call `get_positions(brokerage="ibkr")` → only "Interactive Brokers" positions returned
- Proves the wiring in `positions.py` actually uses `match_brokerage()`

## Files

| File | Action |
|------|--------|
| `mcp_tools/aliases.py` | **New** — shorthand dict + `match_brokerage()` |
| `mcp_tools/positions.py` | Edit — use `match_brokerage()` in brokerage filter |
| `mcp_tools/news_events.py` | Edit — use `match_brokerage()` in account filter |
| `tests/mcp_tools/test_brokerage_aliases.py` | **New** — 8 unit tests + 1 positions integration test |
| `tests/mcp_tools/test_news_events_portfolio.py` | Edit — update account filter test to use `"ibkr"` against "Interactive Brokers" |

## Verification

1. `pytest tests/mcp_tools/test_brokerage_aliases.py -v` — all pass
2. `pytest tests/mcp_tools/test_news_events_portfolio.py -v` — all pass (26+)
3. MCP: `get_portfolio_news(account="ibkr")` → IBKR-only symbols
4. MCP: `get_positions(brokerage="ibkr")` → IBKR-only positions

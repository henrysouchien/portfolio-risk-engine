# Plan: Account Filter for Portfolio News/Events

**Status:** COMPLETE
**Created:** 2026-02-16

## Context

`get_portfolio_news()` and `get_portfolio_events_calendar()` auto-fill symbols from all portfolio positions when no explicit symbols are provided. Currently there's no way to scope the auto-fill to a specific brokerage or account (e.g., "news for my IBKR holdings only" or "earnings for my Schwab account").

Position data carries `brokerage_name` on each row (normalized in `services/position_service.py:311-313`), so the filtering infrastructure exists — it just needs to be threaded through the auto-fill pipeline.

## Design

### Filter semantics
- **Case-insensitive substring match** on `brokerage_name` field
- `"ibkr"` matches "Interactive Brokers", `"schwab"` matches "Charles Schwab"
- Filter applies **only to auto-fill** — when explicit `symbols` are provided, the `account` param is ignored
- Also effectively ignored for `mode="general"` (news) and `event_type` in `{"ipos", "all"}` (events), since those modes skip auto-fill entirely
- When the filter matches no positions:
  - **News** (`get_portfolio_news`): falls back to "symbols required" error (same as empty portfolio)
  - **Events** (`get_portfolio_events_calendar`): falls back to market-wide calendar (no symbol filter applied — existing behavior when auto-fill returns None)
- **Whitespace-only guard**: if `account.strip()` is empty, treat as None (no filter)

### Response metadata
When account filter is active and auto-fill succeeds, add `"account_filter": "<value>"` to the response dict alongside the existing `auto_filled_from_portfolio: true`.

## Files Modified

| File | Change |
|------|--------|
| `mcp_tools/news_events.py` | Add `account` param to `_load_portfolio_symbols()`, `get_portfolio_news()`, `get_portfolio_events_calendar()` |
| `mcp_server.py` | Add `account` param to both MCP tool wrappers, update docstrings |
| `tests/mcp_tools/test_news_events_portfolio.py` | Add 5 account filter tests |

## Implementation Details

### 1. `mcp_tools/news_events.py`

#### `_load_portfolio_symbols()` (line 37)

Add `account: Optional[str] = None` parameter.

**Critical fix**: When `account` is provided, fetch positions with `consolidate=False` to preserve `brokerage_name` metadata. The current `consolidate=True` call (line 61) drops `brokerage_name` from the aggregation dict (`services/position_service.py:408`), so filtering would match nothing.

```python
def _load_portfolio_symbols(
    user_email: Optional[str] = None,
    use_cache: bool = True,
    account: Optional[str] = None,
) -> Optional[str]:
```

After the `account` param, normalize whitespace-only to None:

```python
if account and not account.strip():
    account = None
```

Change the `get_all_positions` call to disable consolidation when filtering:

```python
position_result = position_service.get_all_positions(
    use_cache=use_cache,
    force_refresh=False,
    consolidate=not bool(account),  # Disable consolidation to preserve brokerage_name
)
```

After `positions = position_result.data.positions` (line 67), insert the filter:

```python
if account:
    account_lower = account.strip().lower()
    positions = [
        p for p in positions
        if account_lower in (p.get("brokerage_name") or "").lower()
    ]
```

The rest of the function (ticker extraction, value sorting, cap at 25) works the same on the filtered list.

#### `get_portfolio_news()` (line 403)

Add `account: Optional[str] = None` parameter. Thread to `_load_portfolio_symbols()`:

```python
symbols = _load_portfolio_symbols(user_email=user_email, use_cache=use_cache, account=account)
```

Add `account_filter` to response when active:

```python
if auto_filled and result.get("status") == "success":
    result["auto_filled_from_portfolio"] = True
    if account and account.strip():
        result["account_filter"] = account.strip()
```

#### `get_portfolio_events_calendar()` (line 437)

Same pattern — add `account` param, thread to `_load_portfolio_symbols()`, add `account_filter` to response.

### 2. `mcp_server.py`

#### `get_portfolio_news()` wrapper (~line 646)

Add param:
```python
account: Optional[str] = None,
```

Add to docstring Args section:
```
account: Optional brokerage/account name filter for auto-fill
    (substring match, e.g. "ibkr", "schwab"). Only affects
    auto-filled symbols, ignored when explicit symbols provided.
    Also ignored for mode="general".
```

Add example:
```
"IBKR portfolio news" -> get_portfolio_news(account="ibkr")
```

Thread to `_get_portfolio_news(account=account, ...)`.

#### `get_portfolio_events_calendar()` wrapper (~line 700)

Same pattern. Note in docstring that account is also ignored for `event_type` in `{"ipos", "all"}`.

### 3. Tests — `tests/mcp_tools/test_news_events_portfolio.py`

Add 5 new tests:

1. **`test_load_portfolio_symbols_account_filter`** — Mock positions with mixed brokerages (IBKR + Schwab). Filter by `"ibkr"` → only IBKR tickers returned. **Verify `consolidate=False` is passed** to `get_all_positions` when account is set.

2. **`test_load_portfolio_symbols_account_filter_no_match`** — Filter by `"fidelity"` when no positions match → returns None.

3. **`test_load_portfolio_symbols_account_filter_case_insensitive`** — Filter by `"INTERACTIVE"` matches "Interactive Brokers".

4. **`test_load_portfolio_symbols_account_filter_whitespace_only`** — `account="   "` treated as no filter (consolidation stays True, all positions returned).

5. **`test_portfolio_news_account_filter_ignored_with_explicit_symbols`** — When `symbols="AAPL"` is provided, `account="ibkr"` is ignored (symbols pass through unchanged, `_load_portfolio_symbols` not called).

## Verification

1. `pytest tests/mcp_tools/test_news_events_portfolio.py -v` — all existing + new tests pass
2. MCP sanity checks:
   - `get_portfolio_news()` — all positions (existing behavior unchanged)
   - `get_portfolio_news(account="ibkr")` — only IBKR holdings
   - `get_portfolio_news(symbols="AAPL")` — explicit symbols, account ignored
   - `get_portfolio_events_calendar(account="ibkr")` — only IBKR earnings

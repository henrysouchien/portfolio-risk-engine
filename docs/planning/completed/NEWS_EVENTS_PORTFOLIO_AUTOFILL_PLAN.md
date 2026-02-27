# Plan: Portfolio Auto-Fill for `get_news` and `get_events_calendar`

**Status:** REVISED — Codex findings addressed (6/6)

---

## Problem Statement

`get_news()` and `get_events_calendar()` currently require explicit `symbols` from the user. When the user asks "what's the news on my portfolio?" or "any upcoming earnings for my holdings?", the AI must first call `get_positions` on portfolio-mcp, extract tickers, then call news/calendar on fmp-mcp. This is the "cross-server chaining" problem.

## Architecture Analysis

- `get_news` and `get_events_calendar` live in `mcp_tools/news_events.py` (core logic)
- They are registered on `fmp_mcp_server.py` (fmp-mcp) — no access to portfolio/position data
- Portfolio data is loaded via `PositionService` in tools on `mcp_server.py` (portfolio-mcp)

## Approach: Portfolio-Aware Wrappers on portfolio-mcp

Add portfolio-aware wrapper versions of both tools to `mcp_server.py` (portfolio-mcp), while keeping the existing fmp-mcp versions unchanged. This follows the existing pattern where portfolio-mcp already imports from `mcp_tools/` and wraps with portfolio context.

## File Changes

### 1. `mcp_tools/news_events.py`

**a. Add `_load_portfolio_symbols()` helper:**

[FINDING #3] — Catch specific exceptions (`ValueError`, `ConnectionError`) and log warnings via `_logger` instead of bare `except Exception: return None`. Let truly unexpected errors propagate so they surface during development.

[FINDING #5] — Use an allowlist of position types (`_NEWSWORTHY_TYPES`) instead of a fragile exclusion list. Only equity-like types with FMP ticker symbols produce meaningful news/calendar results.

[FINDING #4] — Cap symbols at top 25 by position market value to avoid excessively long FMP API query strings.

```python
import logging

_logger = logging.getLogger(__name__)

# Position types that have meaningful FMP news/calendar coverage.
_NEWSWORTHY_TYPES = {"equity", "etf", "stock", "mutual_fund", "fund"}

# Maximum symbols to auto-fill. Caps API query size and keeps results relevant.
_MAX_AUTOFILL_SYMBOLS = 25


def _load_portfolio_symbols(user_email=None, use_cache=True):
    """Load equity/ETF/fund ticker symbols from current portfolio positions.

    Returns comma-separated ticker string (e.g., "AAPL,MSFT,GOOGL") or None.
    Filters to newsworthy position types and caps at top 25 by market value.

    Uses lazy imports so fmp_mcp_server.py (which also imports this module)
    does not pull in portfolio dependencies at import time.
    """
    from services.position_service import PositionService
    from settings import get_default_user

    user = user_email or get_default_user()
    if not user:
        _logger.warning("Portfolio auto-fill: no user configured, skipping")
        return None

    try:
        position_service = PositionService(user)
        position_result = position_service.get_all_positions(
            use_cache=use_cache, force_refresh=False, consolidate=True,
        )
    except (ValueError, ConnectionError, OSError) as exc:
        _logger.warning("Portfolio auto-fill: failed to load positions: %s", exc)
        return None

    if not position_result.data.positions:
        _logger.warning("Portfolio auto-fill: no positions found")
        return None

    # Filter to newsworthy types and collect (ticker, abs_value) pairs
    candidates = []
    for p in position_result.data.positions:
        ticker = p.get("ticker", "")
        ptype = (p.get("type") or "").lower()
        if ptype not in _NEWSWORTHY_TYPES:
            continue
        if ticker.startswith("CUR:"):
            continue
        fmp_ticker = p.get("fmp_ticker") or ticker
        if fmp_ticker:
            value = abs(float(p.get("value") or 0))
            candidates.append((fmp_ticker, value))

    if not candidates:
        _logger.warning("Portfolio auto-fill: no newsworthy positions after filtering")
        return None

    # Sort by value descending and cap at _MAX_AUTOFILL_SYMBOLS
    candidates.sort(key=lambda x: x[1], reverse=True)
    top_tickers = [t for t, _ in candidates[:_MAX_AUTOFILL_SYMBOLS]]

    return ",".join(sorted(top_tickers))
```

Key decisions:
- **Lazy imports** inside function body — `fmp_mcp_server.py` also imports this module and doesn't have portfolio dependencies
- **`fmp_ticker` preferred** over raw `ticker` (handles exchange-mapped tickers like `SHEL.L`)
- **Allowlist filtering** (`_NEWSWORTHY_TYPES`) — only `equity`, `etf`, `stock`, `mutual_fund`, `fund` produce meaningful FMP news. Excludes `bond`, `derivative`, `crypto`, `cash`, `other` without needing to enumerate every exclusion.
- **Top-25 cap** — sorts by market value and limits to 25 symbols, preventing excessively long FMP API queries
- **Specific exception handling** — catches `ValueError` (bad config), `ConnectionError`/`OSError` (network/DB), logs warnings; lets code bugs (`TypeError`, `AttributeError`) propagate

**b. Add `get_portfolio_news()` wrapper:**

```python
def get_portfolio_news(user_email=None, symbols=None, mode="stock",
                       limit=10, from_date=None, to_date=None,
                       format="summary", use_cache=True):
    """Fetch news with portfolio auto-fill when symbols not provided."""
    auto_filled = False
    if mode in ("stock", "press") and not symbols:
        symbols = _load_portfolio_symbols(user_email=user_email, use_cache=use_cache)
        if symbols:
            auto_filled = True

    result = get_news(symbols=symbols, mode=mode, limit=limit,
                      from_date=from_date, to_date=to_date, format=format)

    if auto_filled and result.get("status") == "success":
        result["auto_filled_from_portfolio"] = True
    return result
```

**c. Add `get_portfolio_events_calendar()` wrapper:**

[FINDING #1] — Skip auto-fill for `event_type="ipos"` and `"all"`. IPO calendars are inherently market-wide discovery tools — filtering to existing portfolio symbols would suppress all results. `"all"` includes IPOs and is typically used for broad market scanning. Only auto-fill for `earnings`, `dividends`, and `splits` where portfolio filtering makes sense.

```python
# Event types where portfolio symbol filtering is meaningful.
_PORTFOLIO_CALENDAR_TYPES = {"earnings", "dividends", "splits"}


def get_portfolio_events_calendar(user_email=None,
                                  event_type="earnings",
                                  from_date=None, to_date=None,
                                  symbols=None, limit=50,
                                  format="summary", use_cache=True):
    """Fetch calendar events with portfolio auto-fill when appropriate.

    Auto-fills symbols only for earnings/dividends/splits. IPOs and "all"
    are market-wide by nature and skip auto-fill.
    """
    auto_filled = False
    if not symbols and event_type in _PORTFOLIO_CALENDAR_TYPES:
        symbols = _load_portfolio_symbols(user_email=user_email, use_cache=use_cache)
        if symbols:
            auto_filled = True

    result = get_events_calendar(event_type=event_type, from_date=from_date,
                                 to_date=to_date, symbols=symbols,
                                 limit=limit, format=format)

    if auto_filled and result.get("status") == "success":
        result["auto_filled_from_portfolio"] = True
    return result
```

### 2. `mcp_server.py`

[FINDING #2] — Use distinct tool names `get_portfolio_news` and `get_portfolio_events_calendar` on portfolio-mcp to avoid behavioral ambiguity with identically-named tools on fmp-mcp. The `get_portfolio_` prefix signals portfolio context and makes agent routing deterministic:
- User says "AAPL news" → agent picks `fmp-mcp/get_news` (explicit ticker)
- User says "news on my portfolio" → agent picks `portfolio-mcp/get_portfolio_news`

```python
from mcp_tools.news_events import get_portfolio_news as _get_portfolio_news
from mcp_tools.news_events import get_portfolio_events_calendar as _get_portfolio_events_calendar
```

Register as `get_portfolio_news` and `get_portfolio_events_calendar` with full docstrings documenting auto-fill behavior, event-type-aware logic, and examples.

### 3. `fmp_mcp_server.py`

No functional changes. Optionally add a one-line note to docstrings:
```
Note: For portfolio-aware auto-fill, use get_portfolio_news / get_portfolio_events_calendar on portfolio-mcp.
```

### 4. `tests/mcp_tools/test_news_events_portfolio.py` (new)

[FINDING #6] — Expanded test coverage to 15 tests addressing all reviewer concerns.

**`_load_portfolio_symbols` tests (7):**

1. `test_load_portfolio_symbols_success` — Mixed types (equity, etf, cash, derivative, bond, crypto). Verify only `_NEWSWORTHY_TYPES` returned, `CUR:` filtered.
2. `test_load_portfolio_symbols_no_user` — No user configured → returns None, logs warning.
3. `test_load_portfolio_symbols_connection_error` — `ConnectionError` → returns None, logs warning.
4. `test_load_portfolio_symbols_value_error` — `ValueError` → returns None, logs warning.
5. `test_load_portfolio_symbols_unexpected_error_propagates` — `TypeError` → exception propagates (not swallowed).
6. `test_load_portfolio_symbols_uses_fmp_ticker` — `fmp_ticker="SHEL.L"` preferred over `ticker="SHEL"`.
7. `test_load_portfolio_symbols_caps_at_25` — 40 positions, verify only top 25 by value returned.

**`get_portfolio_news` tests (3):**

8. `test_portfolio_news_auto_fill` — Symbols auto-populated, verify `auto_filled_from_portfolio` flag.
9. `test_portfolio_news_explicit_symbols_override` — Explicit `symbols="TSLA"` → `_load_portfolio_symbols` NOT called.
10. `test_portfolio_news_general_mode_skips_autofill` — `mode="general"` doesn't load positions.

**`get_portfolio_events_calendar` tests (5):**

11. `test_portfolio_events_calendar_auto_fill_earnings` — `event_type="earnings"` → auto-fills.
12. `test_portfolio_events_calendar_auto_fill_dividends` — `event_type="dividends"` → auto-fills.
13. `test_portfolio_events_calendar_ipos_no_autofill` — `event_type="ipos"` → `_load_portfolio_symbols` NOT called.
14. `test_portfolio_events_calendar_all_no_autofill` — `event_type="all"` → no auto-fill.
15. `test_portfolio_events_calendar_empty_portfolio_fallback` — `_load_portfolio_symbols` returns None → standard behavior.

## Design Decisions

1. **Dual registration, not cross-server RPC** — each MCP server is a separate process; inter-server IPC adds substantial complexity. Portfolio-mcp gets portfolio-aware versions, fmp-mcp keeps FMP-only versions.
2. **[FINDING #2] Distinct tool names** — `get_portfolio_news` and `get_portfolio_events_calendar` on portfolio-mcp. The `get_portfolio_` prefix is unambiguous and makes agent routing deterministic.
3. **Lazy imports** — prevents import-time failures when fmp-mcp imports the module.
4. **[FINDING #3] Specific exception handling** — catches `ValueError`, `ConnectionError`, `OSError` and logs warnings. Unexpected exceptions propagate.
5. **[FINDING #5] Allowlist filtering** — `_NEWSWORTHY_TYPES` positive allowlist. New unknown types excluded by default (safe).
6. **[FINDING #4] Top-25 symbol cap** — sorted by market value, capped at 25. Module constant for easy adjustment.
7. **[FINDING #1] Event-type-aware auto-fill** — only `earnings`, `dividends`, `splits` trigger auto-fill. `ipos` and `all` skip (market-wide discovery).
8. **Cache-first** — `use_cache=True` default since this is convenience, not precision.
9. **`auto_filled_from_portfolio` flag** — transparency for the AI and user.

## Potential Concerns

- **Large portfolios beyond the cap**: Positions ranked 26+ by value are excluded from auto-fill. Acceptable trade-off — top 25 covers the vast majority of portfolio value. Users can always provide explicit symbols.
- **`_NEWSWORTHY_TYPES` maintenance**: If new canonical position types are added (e.g., `"reit"`, `"preferred"`), the allowlist needs updating. Intentionally conservative — new unknown types excluded by default.

## Reference Patterns

- `mcp_tools/income.py` → `_load_positions_for_income()` (PositionService + filter, raises on error)
- `mcp_tools/factor_intelligence.py` → `_load_portfolio_weights()` (PositionService + CUR:/cash filter, lazy imports)
- `mcp_tools/risk.py` → `_load_portfolio_for_analysis()` (raises `ValueError` on missing user/positions)

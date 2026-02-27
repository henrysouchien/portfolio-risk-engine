# News & Events Calendar MCP Tools - Implementation Plan

> **Status:** PLANNED
> **Created:** 2026-02-07

## Overview

Add 2 MCP tools to the `portfolio-mcp` server: `get_news` and `get_events_calendar`. Both wrap FMP endpoints and support a "portfolio mode" that auto-scopes results to current holdings.

These are Tier 1 tools from the research doc (single FMP endpoint wrapping, no complex analysis logic). The new pattern introduced here is **direct FMP client fetching** inside the MCP tool layer (no intermediate service class needed since these are pass-through data tools, not analysis engines).

## Use Cases & Example Queries

These tools answer questions about recent news, upcoming earnings, dividends, and other corporate events. Example natural language queries:

- **"Any news on my top holdings?"** -- `get_news()` with no symbols auto-fills from the top 10 portfolio holdings by market value
- **"What's the latest on NVDA?"** -- `get_news(symbols="NVDA")` fetches recent stock-specific news articles
- **"Which of my positions have earnings in the next 2 weeks?"** -- `get_events_calendar(event_type="earnings", portfolio_only=True, to_date="<2 weeks out>")` filters the earnings calendar to portfolio holdings
- **"When are the next ex-dividend dates for my portfolio?"** -- `get_events_calendar(event_type="dividends", portfolio_only=True)` shows upcoming dividend dates for holdings
- **"Show me recent press releases from AAPL and MSFT"** -- `get_news(symbols="AAPL,MSFT", mode="press")` fetches official company press releases
- **"Any upcoming IPOs?"** -- `get_events_calendar(event_type="ipos")` shows the market-wide IPO calendar

### Tool Chaining Example

A broad question like **"Should I be worried about any of my holdings?"** would chain multiple tools:

1. `get_news()` -- check recent headlines for portfolio holdings (auto-fills top 10 tickers)
2. `get_events_calendar(event_type="earnings", portfolio_only=True)` -- identify holdings with upcoming earnings (potential volatility catalysts)
3. `get_risk_analysis(include=["compliance", "risk_metrics"])` -- check for any risk limit breaches or elevated risk flags

The agent combines news sentiment, upcoming event catalysts, and risk metrics to flag holdings that warrant attention.

---

## FMP Endpoints Required

### News Endpoints (3)
| Endpoint Name | FMP Path | Params | Notes |
|---------------|----------|--------|-------|
| `news_stock` | `/stable/news/stock` | `symbols` (comma-sep), `from`, `to`, `page`, `limit` | Per-symbol news |
| `news_general` | `/stable/news/general-latest` | `page`, `limit` | Broad market news |
| `news_press_releases` | `/stable/news/press-releases` | `symbols` (comma-sep), `from`, `to`, `page`, `limit` | Official press releases |

### Calendar Endpoints (4)
| Endpoint Name | FMP Path | Params | Notes |
|---------------|----------|--------|-------|
| `earnings_calendar` | `/stable/earnings-calendar` | `from`, `to` | 90-day max window |
| `dividends_calendar` | `/stable/dividends-calendar` | `from`, `to` | Ex-dividend dates |
| `splits_calendar` | `/stable/splits-calendar` | `from`, `to` | Stock splits |
| `ipos_calendar` | `/stable/ipos-calendar` | `from`, `to` | Upcoming IPOs |

**Total: 7 new FMP endpoint registrations**

---

## Tool 1: `get_news`

### Purpose
Fetch news articles for specific tickers, portfolio holdings, or broad market. Three modes: stock-specific news, general market news, and company press releases.

### MCP Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `symbols` | `Optional[str]` | `None` | Comma-separated tickers (e.g., `"AAPL,MSFT"`). If omitted and portfolio mode possible, auto-fills from top holdings |
| `mode` | `Literal["stock", "general", "press"]` | `"stock"` | News source: stock-specific, general market, or press releases |
| `limit` | `int` | `10` | Max articles to return (1-50) |
| `from_date` | `Optional[str]` | `None` | Start date YYYY-MM-DD |
| `to_date` | `Optional[str]` | `None` | End date YYYY-MM-DD |
| `format` | `Literal["summary", "full"]` | `"summary"` | Output detail level |
| `use_cache` | `bool` | `True` | Use cached position data for portfolio mode |

**Note:** No `user_email` exposed to MCP — uses `RISK_MODULE_USER_EMAIL` env var internally (same pattern as all portfolio-aware tools). No `"report"` format because news is already text-native; summary vs full is sufficient.

### Data Flow

```
get_news(symbols=None, mode="stock")
    │
    ├─ symbols provided?
    │   YES → use directly
    │   NO  → mode == "general"?
    │         YES → no symbols needed, fetch general news
    │         NO  → _get_portfolio_tickers(use_cache) → top 10 holdings by weight
    │               if fails (no user, no positions) → return error
    │
    ├─ Build FMPClient().fetch_raw() call for appropriate endpoint
    │   mode="stock"  → fetch_raw("news_stock", symbols=..., limit=..., from=..., to=...)
    │   mode="general" → fetch_raw("news_general", limit=...)
    │   mode="press"  → fetch_raw("news_press_releases", symbols=..., limit=..., from=..., to=...)
    │
    └─ Format response
        summary → headline + date + source + snippet (first 200 chars of text)
        full    → all fields from FMP response
```

### Portfolio Mode Detail

When `symbols` is `None` and `mode` is `"stock"` or `"press"`:
1. Call `_get_portfolio_tickers(use_cache)` — a new shared helper in `mcp_tools/news_events.py`
2. Helper fetches positions via `PositionService`, filters out cash (`type=="cash"` or `ticker.startswith("CUR:")`), sorts by absolute market value descending
3. Takes top 10 tickers (FMP accepts comma-separated list; too many symbols dilutes results)
4. Returns as comma-separated string: `"AAPL,MSFT,NVDA,..."`

If portfolio loading fails, return a clear error: `"No symbols provided and could not load portfolio. Specify symbols directly or connect a brokerage account."`

### Summary Output Structure

```python
{
    "status": "success",
    "mode": "stock",
    "symbols": "AAPL,MSFT",
    "article_count": 10,
    "portfolio_mode": True,  # True if symbols were auto-filled from holdings
    "articles": [
        {
            "title": "Apple Reports Record Q4 Revenue",
            "date": "2026-02-06",
            "source": "Reuters",
            "symbol": "AAPL",
            "snippet": "Apple Inc. reported quarterly revenue of...",
            "url": "https://..."
        },
        ...
    ]
}
```

### Full Output Structure

```python
{
    "status": "success",
    "mode": "stock",
    "symbols": "AAPL,MSFT",
    "article_count": 10,
    "portfolio_mode": False,
    "articles": [
        {
            # All fields from FMP response (title, text, url, image,
            # publishedDate, site, symbol, etc.)
        },
        ...
    ]
}
```

---

## Tool 2: `get_events_calendar`

### Purpose
Fetch upcoming corporate events (earnings, dividends, splits, IPOs) with optional filtering to portfolio holdings.

### MCP Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `event_type` | `Literal["earnings", "dividends", "splits", "ipos", "all"]` | `"earnings"` | Calendar type |
| `from_date` | `Optional[str]` | `None` | Start date YYYY-MM-DD. Default: today |
| `to_date` | `Optional[str]` | `None` | End date YYYY-MM-DD. Default: today + 30 days |
| `symbols` | `Optional[str]` | `None` | Comma-separated tickers to filter results. If omitted and portfolio mode possible, auto-fills from holdings |
| `portfolio_only` | `bool` | `False` | When True and symbols not provided, only show events for portfolio holdings |
| `format` | `Literal["summary", "full"]` | `"summary"` | Output detail level |
| `use_cache` | `bool` | `True` | Use cached position data for portfolio filtering |

**Design note on `portfolio_only`:** Unlike `get_news` where omitting symbols auto-triggers portfolio mode, the events calendar can legitimately be used to see ALL upcoming earnings/IPOs market-wide. The `portfolio_only` flag makes the intent explicit. When `portfolio_only=True` and no symbols provided, it fetches the full calendar then client-side filters to holdings.

### Data Flow

```
get_events_calendar(event_type="earnings", portfolio_only=True)
    │
    ├─ Resolve date range
    │   from_date defaults to today
    │   to_date defaults to today + 30 days
    │   Validate: max 90-day window (FMP limit)
    │
    ├─ Resolve symbols filter
    │   symbols provided? → parse to set for filtering
    │   portfolio_only=True? → _get_portfolio_tickers(use_cache) → all holdings as set
    │   neither? → no filtering (return full calendar)
    │
    ├─ Fetch calendar data
    │   event_type == "all"?
    │     YES → fetch all 4 endpoints, merge results
    │     NO  → fetch single endpoint
    │
    │   Each fetch: FMPClient().fetch_raw("earnings_calendar", **{"from": from_date, "to": to_date})
    │
    ├─ Apply symbol filter (if any)
    │   Filter events where event["symbol"] is in the symbols set
    │
    └─ Format response
        summary → event date + symbol + key info (varies by type)
        full    → all fields from FMP response
```

### Calendar Fetch Strategy

For `event_type="all"`:
- Fetch all 4 calendar endpoints in sequence (not parallel — avoid rate limiting on free tier)
- Tag each event with `"event_type"` field
- Merge into single list sorted by date
- Apply symbol filter once on merged results

For single event type:
- Single `fetch_raw` call
- Tag with `"event_type"` for consistency

### Event Type Summary Fields

| Event Type | Summary Fields |
|------------|---------------|
| `earnings` | `symbol`, `date`, `eps_estimated`, `eps_actual` (if reported), `revenue_estimated` |
| `dividends` | `symbol`, `date` (ex-date), `dividend`, `record_date`, `payment_date` |
| `splits` | `symbol`, `date`, `numerator`, `denominator` (e.g., 4:1) |
| `ipos` | `symbol`, `company`, `date`, `price_range`, `shares` |

### Summary Output Structure

```python
{
    "status": "success",
    "event_type": "earnings",
    "from_date": "2026-02-07",
    "to_date": "2026-03-09",
    "portfolio_only": True,
    "event_count": 5,
    "events": [
        {
            "event_type": "earnings",
            "symbol": "AAPL",
            "date": "2026-02-15",
            "eps_estimated": 2.35,
            "revenue_estimated": 124500000000
        },
        ...
    ]
}
```

### Full Output Structure

```python
{
    "status": "success",
    "event_type": "all",
    "from_date": "2026-02-07",
    "to_date": "2026-03-09",
    "portfolio_only": False,
    "event_count": 150,
    "events": [
        {
            "event_type": "earnings",
            # All fields from FMP response
        },
        {
            "event_type": "dividends",
            # All fields from FMP response
        },
        ...
    ]
}
```

---

## Files to Create/Modify

### New Files

1. **`mcp_tools/news_events.py`** — Tool implementations (`get_news`, `get_events_calendar`, `_get_portfolio_tickers` helper)

### Modified Files

2. **`fmp/registry.py`** — 7 new endpoint registrations (3 news + 4 calendar)
3. **`mcp_server.py`** — Import + 2 `@mcp.tool()` registrations
4. **`mcp_tools/__init__.py`** — Import + export
5. **`mcp_tools/README.md`** — Document new tools

---

## Implementation Details

### `fmp/registry.py` — New Endpoint Registrations

```python
# --- News ---

register_endpoint(
    FMPEndpoint(
        name="news_stock",
        path="/news/stock",
        description="Stock-specific news articles for given symbols",
        fmp_docs_url="https://site.financialmodelingprep.com/developer/docs#stock-news",
        category="news",
        api_version="stable",
        params=[
            EndpointParam("symbols", ParamType.STRING, required=True, description="Comma-separated symbols"),
            EndpointParam("from", ParamType.DATE, description="Start date (YYYY-MM-DD)"),
            EndpointParam("to", ParamType.DATE, description="End date (YYYY-MM-DD)"),
            EndpointParam("limit", ParamType.INTEGER, default=10, description="Max results"),
            EndpointParam("page", ParamType.INTEGER, default=0, description="Page number"),
        ],
        cache_dir="cache/news",
        cache_refresh=CacheRefresh.TTL,
        cache_ttl_hours=1,  # News is time-sensitive
    )
)

register_endpoint(
    FMPEndpoint(
        name="news_general",
        path="/news/general-latest",
        description="Latest general market news",
        fmp_docs_url="https://site.financialmodelingprep.com/developer/docs#general-news",
        category="news",
        api_version="stable",
        params=[
            EndpointParam("limit", ParamType.INTEGER, default=10, description="Max results"),
            EndpointParam("page", ParamType.INTEGER, default=0, description="Page number"),
        ],
        cache_dir="cache/news",
        cache_refresh=CacheRefresh.TTL,
        cache_ttl_hours=1,
    )
)

register_endpoint(
    FMPEndpoint(
        name="news_press_releases",
        path="/news/press-releases",
        description="Official company press releases",
        fmp_docs_url="https://site.financialmodelingprep.com/developer/docs#press-releases",
        category="news",
        api_version="stable",
        params=[
            EndpointParam("symbols", ParamType.STRING, required=True, description="Comma-separated symbols"),
            EndpointParam("from", ParamType.DATE, description="Start date (YYYY-MM-DD)"),
            EndpointParam("to", ParamType.DATE, description="End date (YYYY-MM-DD)"),
            EndpointParam("limit", ParamType.INTEGER, default=10, description="Max results"),
            EndpointParam("page", ParamType.INTEGER, default=0, description="Page number"),
        ],
        cache_dir="cache/news",
        cache_refresh=CacheRefresh.TTL,
        cache_ttl_hours=1,
    )
)

# --- Calendars ---

register_endpoint(
    FMPEndpoint(
        name="earnings_calendar",
        path="/earnings-calendar",
        description="Upcoming and recent earnings dates with estimates",
        fmp_docs_url="https://site.financialmodelingprep.com/developer/docs#earnings-calendar",
        category="calendar",
        api_version="stable",
        params=[
            EndpointParam("from", ParamType.DATE, description="Start date (YYYY-MM-DD)"),
            EndpointParam("to", ParamType.DATE, description="End date (YYYY-MM-DD)"),
        ],
        cache_dir="cache/calendar",
        cache_refresh=CacheRefresh.TTL,
        cache_ttl_hours=6,  # Calendars update a few times per day
    )
)

register_endpoint(
    FMPEndpoint(
        name="dividends_calendar",
        path="/dividends-calendar",
        description="Upcoming ex-dividend dates and amounts",
        fmp_docs_url="https://site.financialmodelingprep.com/developer/docs#dividends-calendar",
        category="calendar",
        api_version="stable",
        params=[
            EndpointParam("from", ParamType.DATE, description="Start date (YYYY-MM-DD)"),
            EndpointParam("to", ParamType.DATE, description="End date (YYYY-MM-DD)"),
        ],
        cache_dir="cache/calendar",
        cache_refresh=CacheRefresh.TTL,
        cache_ttl_hours=6,
    )
)

register_endpoint(
    FMPEndpoint(
        name="splits_calendar",
        path="/splits-calendar",
        description="Upcoming stock split dates",
        fmp_docs_url="https://site.financialmodelingprep.com/developer/docs#splits-calendar",
        category="calendar",
        api_version="stable",
        params=[
            EndpointParam("from", ParamType.DATE, description="Start date (YYYY-MM-DD)"),
            EndpointParam("to", ParamType.DATE, description="End date (YYYY-MM-DD)"),
        ],
        cache_dir="cache/calendar",
        cache_refresh=CacheRefresh.TTL,
        cache_ttl_hours=6,
    )
)

register_endpoint(
    FMPEndpoint(
        name="ipos_calendar",
        path="/ipos-calendar",
        description="Upcoming IPO dates and pricing",
        fmp_docs_url="https://site.financialmodelingprep.com/developer/docs#ipos-calendar",
        category="calendar",
        api_version="stable",
        params=[
            EndpointParam("from", ParamType.DATE, description="Start date (YYYY-MM-DD)"),
            EndpointParam("to", ParamType.DATE, description="End date (YYYY-MM-DD)"),
        ],
        cache_dir="cache/calendar",
        cache_refresh=CacheRefresh.TTL,
        cache_ttl_hours=6,
    )
)
```

### `mcp_tools/news_events.py` — Full Implementation

```python
"""
MCP Tools: get_news, get_events_calendar

Exposes FMP news and event calendar data as MCP tools for AI invocation.

Usage (from Claude):
    "What's the latest news on AAPL?" -> get_news(symbols="AAPL")
    "Show me news for my portfolio" -> get_news()
    "Any upcoming earnings for my holdings?" -> get_events_calendar(portfolio_only=True)
    "Show me this week's IPOs" -> get_events_calendar(event_type="ipos")

Architecture note:
- These are data pass-through tools (no analysis engine or service class needed)
- Fetches directly from FMP via FMPClient.fetch_raw()
- Portfolio mode uses PositionService to resolve holdings
- stdout is redirected to stderr to protect MCP JSON-RPC channel from stray prints
"""

import sys
from datetime import datetime, timedelta
from typing import Optional, Literal

from fmp.client import FMPClient


# ---------------------------------------------------------------------------
# Shared helper: load portfolio tickers for auto-scoping
# ---------------------------------------------------------------------------

def _get_portfolio_tickers(use_cache: bool = True, max_tickers: int = 10) -> list[str]:
    """
    Load top portfolio tickers sorted by market value (descending).

    Uses PositionService to fetch current holdings, filters out cash,
    and returns up to max_tickers symbols.

    Raises:
        ValueError: If no user configured or no non-cash positions found.
    """
    from settings import get_default_user
    from services.position_service import PositionService

    user = get_default_user()
    if not user:
        raise ValueError("No user specified and RISK_MODULE_USER_EMAIL not configured")

    position_service = PositionService(user)
    position_result = position_service.get_all_positions(
        use_cache=use_cache,
        force_refresh=not use_cache,
        consolidate=True,
    )

    positions = position_result.data.positions
    if not positions:
        raise ValueError("No brokerage positions found. Connect a brokerage account first.")

    # Filter out cash positions
    equity_positions = [
        p for p in positions
        if p.get("type") != "cash" and not p["ticker"].startswith("CUR:")
    ]
    if not equity_positions:
        raise ValueError("No non-cash positions found.")

    # Sort by absolute market value descending, take top N
    equity_positions.sort(key=lambda p: abs(float(p.get("value", 0))), reverse=True)
    return [p["ticker"] for p in equity_positions[:max_tickers]]


# ---------------------------------------------------------------------------
# Tool 1: get_news
# ---------------------------------------------------------------------------

def get_news(
    symbols: Optional[str] = None,
    mode: Literal["stock", "general", "press"] = "stock",
    limit: int = 10,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    format: Literal["summary", "full"] = "summary",
    use_cache: bool = True,
) -> dict:
    """
    Fetch news articles for stocks, portfolio holdings, or the broad market.

    Args:
        symbols: Comma-separated tickers (e.g., "AAPL,MSFT"). If not provided
            and mode is "stock" or "press", auto-fills from top portfolio holdings.
        mode: News source:
            - "stock": Per-symbol news articles
            - "general": Broad market news (symbols ignored)
            - "press": Official company press releases
        limit: Max articles to return, 1-50 (default: 10).
        from_date: Start date in YYYY-MM-DD format (optional).
        to_date: End date in YYYY-MM-DD format (optional).
        format: Output format:
            - "summary": Headline, date, source, snippet per article
            - "full": Complete article data from FMP
        use_cache: Use cached position data for portfolio mode (default: True).

    Returns:
        dict: News data with status field ("success" or "error")

    Examples:
        "What's the news on AAPL?" -> get_news(symbols="AAPL")
        "Show me portfolio news" -> get_news()
        "Latest market news" -> get_news(mode="general")
        "TSLA press releases" -> get_news(symbols="TSLA", mode="press")
    """
    _saved = sys.stdout
    sys.stdout = sys.stderr
    try:
        # Clamp limit to 1-50
        limit = max(1, min(50, limit))

        portfolio_mode = False

        # Resolve symbols for stock/press modes
        if mode in ("stock", "press") and not symbols:
            try:
                tickers = _get_portfolio_tickers(use_cache=use_cache)
                symbols = ",".join(tickers)
                portfolio_mode = True
            except ValueError as e:
                return {
                    "status": "error",
                    "error": (
                        f"No symbols provided and could not load portfolio: {e}. "
                        "Specify symbols directly (e.g., symbols='AAPL,MSFT') "
                        "or connect a brokerage account."
                    ),
                }

        # Build FMP request params
        fmp = FMPClient()
        fetch_kwargs = {"limit": limit}
        if from_date:
            fetch_kwargs["from_date"] = from_date
        if to_date:
            fetch_kwargs["to_date"] = to_date

        # Fetch from appropriate endpoint
        if mode == "general":
            raw = fmp.fetch_raw("news_general", **fetch_kwargs)
        elif mode == "press":
            raw = fmp.fetch_raw("news_press_releases", symbols=symbols, **fetch_kwargs)
        else:  # stock
            raw = fmp.fetch_raw("news_stock", symbols=symbols, **fetch_kwargs)

        # Normalize to list
        articles = raw if isinstance(raw, list) else [raw] if raw else []

        # Format response
        if format == "summary":
            formatted_articles = []
            for article in articles:
                snippet = (article.get("text") or "")[:200]
                if len(article.get("text") or "") > 200:
                    snippet += "..."
                formatted_articles.append({
                    "title": article.get("title", ""),
                    "date": (article.get("publishedDate") or "")[:10],
                    "source": article.get("site") or article.get("source", ""),
                    "symbol": article.get("symbol", ""),
                    "snippet": snippet,
                    "url": article.get("url", ""),
                })
            articles_out = formatted_articles
        else:  # full
            articles_out = articles

        return {
            "status": "success",
            "mode": mode,
            "symbols": symbols or "",
            "article_count": len(articles_out),
            "portfolio_mode": portfolio_mode,
            "articles": articles_out,
        }

    except Exception as e:
        return {"status": "error", "error": str(e)}
    finally:
        sys.stdout = _saved


# ---------------------------------------------------------------------------
# Tool 2: get_events_calendar
# ---------------------------------------------------------------------------

# Maps event_type to FMP endpoint name
_CALENDAR_ENDPOINTS = {
    "earnings": "earnings_calendar",
    "dividends": "dividends_calendar",
    "splits": "splits_calendar",
    "ipos": "ipos_calendar",
}


def _fetch_calendar(fmp: FMPClient, endpoint_name: str, from_date: str, to_date: str) -> list[dict]:
    """Fetch a single calendar endpoint, returning list of events."""
    try:
        raw = fmp.fetch_raw(endpoint_name, from_date=from_date, to_date=to_date)
        if isinstance(raw, list):
            return raw
        elif raw:
            return [raw]
        return []
    except Exception:
        # Individual calendar fetch failure should not break "all" mode
        return []


def _summarize_event(event: dict, event_type: str) -> dict:
    """Extract summary fields for an event based on its type."""
    base = {
        "event_type": event_type,
        "symbol": event.get("symbol", ""),
        "date": event.get("date", ""),
    }

    if event_type == "earnings":
        base["eps_estimated"] = event.get("epsEstimated")
        base["eps_actual"] = event.get("eps")
        base["revenue_estimated"] = event.get("revenueEstimated")
        base["revenue_actual"] = event.get("revenue")
    elif event_type == "dividends":
        base["dividend"] = event.get("dividend") or event.get("adjDividend")
        base["record_date"] = event.get("recordDate", "")
        base["payment_date"] = event.get("paymentDate", "")
    elif event_type == "splits":
        base["numerator"] = event.get("numerator")
        base["denominator"] = event.get("denominator")
    elif event_type == "ipos":
        base["company"] = event.get("company", "")
        base["price_range"] = event.get("priceRange", "")
        base["shares"] = event.get("shares")

    return base


def get_events_calendar(
    event_type: Literal["earnings", "dividends", "splits", "ipos", "all"] = "earnings",
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    symbols: Optional[str] = None,
    portfolio_only: bool = False,
    format: Literal["summary", "full"] = "summary",
    use_cache: bool = True,
) -> dict:
    """
    Fetch upcoming corporate events: earnings, dividends, splits, or IPOs.

    Args:
        event_type: Calendar type:
            - "earnings": Earnings dates with EPS estimates
            - "dividends": Ex-dividend dates and amounts
            - "splits": Stock split dates
            - "ipos": Upcoming IPO dates
            - "all": All event types merged and sorted by date
        from_date: Start date in YYYY-MM-DD format (default: today).
        to_date: End date in YYYY-MM-DD format (default: today + 30 days).
            Max 90-day window (FMP limit).
        symbols: Comma-separated tickers to filter results (e.g., "AAPL,MSFT").
            Only events for these symbols are returned.
        portfolio_only: When True and symbols not provided, filter events to
            current portfolio holdings only (default: False).
        format: Output format:
            - "summary": Key event info (date, symbol, type-specific fields)
            - "full": Complete event data from FMP
        use_cache: Use cached position data for portfolio filtering (default: True).

    Returns:
        dict: Calendar events with status field ("success" or "error")

    Examples:
        "Upcoming earnings?" -> get_events_calendar()
        "Any earnings for my holdings?" -> get_events_calendar(portfolio_only=True)
        "Dividend calendar for AAPL" -> get_events_calendar(event_type="dividends", symbols="AAPL")
        "All events this month" -> get_events_calendar(event_type="all")
        "Upcoming IPOs" -> get_events_calendar(event_type="ipos")
    """
    _saved = sys.stdout
    sys.stdout = sys.stderr
    try:
        # Default date range: today to +30 days
        today = datetime.now()
        if not from_date:
            from_date = today.strftime("%Y-%m-%d")
        if not to_date:
            to_date = (today + timedelta(days=30)).strftime("%Y-%m-%d")

        # Validate 90-day max window
        try:
            dt_from = datetime.strptime(from_date, "%Y-%m-%d")
            dt_to = datetime.strptime(to_date, "%Y-%m-%d")
            if (dt_to - dt_from).days > 90:
                return {
                    "status": "error",
                    "error": "Date range exceeds 90-day maximum. Narrow the from_date/to_date window.",
                }
            if dt_to < dt_from:
                return {
                    "status": "error",
                    "error": "to_date must be after from_date.",
                }
        except ValueError:
            return {
                "status": "error",
                "error": "Invalid date format. Use YYYY-MM-DD.",
            }

        # Resolve symbol filter
        symbol_filter = None
        if symbols:
            symbol_filter = set(s.strip().upper() for s in symbols.split(",") if s.strip())
        elif portfolio_only:
            try:
                tickers = _get_portfolio_tickers(use_cache=use_cache, max_tickers=50)
                symbol_filter = set(tickers)
            except ValueError as e:
                return {
                    "status": "error",
                    "error": (
                        f"portfolio_only=True but could not load portfolio: {e}. "
                        "Specify symbols directly or connect a brokerage account."
                    ),
                }

        # Fetch calendar data
        fmp = FMPClient()
        all_events = []

        if event_type == "all":
            for etype, endpoint_name in _CALENDAR_ENDPOINTS.items():
                events = _fetch_calendar(fmp, endpoint_name, from_date, to_date)
                for evt in events:
                    evt["_event_type"] = etype
                all_events.extend(events)
        else:
            endpoint_name = _CALENDAR_ENDPOINTS[event_type]
            events = _fetch_calendar(fmp, endpoint_name, from_date, to_date)
            for evt in events:
                evt["_event_type"] = event_type
            all_events = events

        # Apply symbol filter
        if symbol_filter:
            all_events = [
                e for e in all_events
                if (e.get("symbol") or "").upper() in symbol_filter
            ]

        # Sort by date
        all_events.sort(key=lambda e: e.get("date", ""))

        # Format response
        if format == "summary":
            formatted_events = [
                _summarize_event(evt, evt.pop("_event_type", event_type))
                for evt in all_events
            ]
        else:  # full
            formatted_events = []
            for evt in all_events:
                etype = evt.pop("_event_type", event_type)
                evt["event_type"] = etype
                formatted_events.append(evt)

        return {
            "status": "success",
            "event_type": event_type,
            "from_date": from_date,
            "to_date": to_date,
            "portfolio_only": portfolio_only and symbol_filter is not None,
            "event_count": len(formatted_events),
            "events": formatted_events,
        }

    except Exception as e:
        return {"status": "error", "error": str(e)}
    finally:
        sys.stdout = _saved
```

### `mcp_server.py` — Additions

```python
# Add imports (at top, within stdout redirect block)
from mcp_tools.news_events import get_news as _get_news
from mcp_tools.news_events import get_events_calendar as _get_events_calendar

# Add tool registrations

@mcp.tool()
def get_news(
    symbols: Optional[str] = None,
    mode: Literal["stock", "general", "press"] = "stock",
    limit: int = 10,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    format: Literal["summary", "full"] = "summary",
    use_cache: bool = True,
) -> dict:
    """
    Fetch news articles for stocks, portfolio holdings, or the broad market.

    Three modes: stock-specific news, general market news, and company press
    releases. When no symbols are provided and mode is "stock" or "press",
    automatically fetches news for top portfolio holdings.

    Args:
        symbols: Comma-separated tickers (e.g., "AAPL,MSFT"). If not provided
            and mode is "stock" or "press", auto-fills from top portfolio holdings.
        mode: News source:
            - "stock": Per-symbol news articles (default)
            - "general": Broad market news (symbols ignored)
            - "press": Official company press releases
        limit: Max articles to return, 1-50 (default: 10).
        from_date: Start date in YYYY-MM-DD format (optional).
        to_date: End date in YYYY-MM-DD format (optional).
        format: Output format:
            - "summary": Headline, date, source, snippet per article
            - "full": Complete article data
        use_cache: Use cached position data for portfolio mode (default: True).

    Returns:
        News data with status field ("success" or "error").

    Examples:
        "What's the news on AAPL?" -> get_news(symbols="AAPL")
        "Show me portfolio news" -> get_news()
        "Latest market news" -> get_news(mode="general")
        "TSLA press releases" -> get_news(symbols="TSLA", mode="press")
        "News for AAPL and MSFT" -> get_news(symbols="AAPL,MSFT")
    """
    return _get_news(
        symbols=symbols,
        mode=mode,
        limit=limit,
        from_date=from_date,
        to_date=to_date,
        format=format,
        use_cache=use_cache,
    )


@mcp.tool()
def get_events_calendar(
    event_type: Literal["earnings", "dividends", "splits", "ipos", "all"] = "earnings",
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    symbols: Optional[str] = None,
    portfolio_only: bool = False,
    format: Literal["summary", "full"] = "summary",
    use_cache: bool = True,
) -> dict:
    """
    Fetch upcoming corporate events: earnings, dividends, splits, or IPOs.

    Can show market-wide calendars or filter to specific symbols / portfolio
    holdings. Useful for tracking upcoming catalysts and corporate actions.

    Args:
        event_type: Calendar type:
            - "earnings": Earnings dates with EPS estimates (default)
            - "dividends": Ex-dividend dates and amounts
            - "splits": Stock split dates
            - "ipos": Upcoming IPO dates
            - "all": All event types merged and sorted by date
        from_date: Start date in YYYY-MM-DD format (default: today).
        to_date: End date in YYYY-MM-DD format (default: today + 30 days).
            Max 90-day window.
        symbols: Comma-separated tickers to filter results (e.g., "AAPL,MSFT").
        portfolio_only: When True and no symbols provided, filter to portfolio
            holdings only (default: False).
        format: Output format:
            - "summary": Key event info (date, symbol, type-specific fields)
            - "full": Complete event data from FMP
        use_cache: Use cached position data for portfolio filtering (default: True).

    Returns:
        Calendar events with status field ("success" or "error").

    Examples:
        "Upcoming earnings?" -> get_events_calendar()
        "Any earnings for my holdings?" -> get_events_calendar(portfolio_only=True)
        "Dividend calendar for AAPL" -> get_events_calendar(event_type="dividends", symbols="AAPL")
        "All events this month" -> get_events_calendar(event_type="all")
        "Upcoming IPOs" -> get_events_calendar(event_type="ipos")
    """
    return _get_events_calendar(
        event_type=event_type,
        from_date=from_date,
        to_date=to_date,
        symbols=symbols,
        portfolio_only=portfolio_only,
        format=format,
        use_cache=use_cache,
    )
```

### `mcp_tools/__init__.py` — Additions

```python
# Add import
from mcp_tools.news_events import get_news, get_events_calendar

# Add to __all__
"get_news",
"get_events_calendar",
```

### `mcp_tools/README.md` — Additions

Add `news_events.py` to the file organization listing and add documentation sections for both tools following the existing format (parameters table, examples, return structure).

---

## Error Handling

| Error Case | Handling |
|------------|----------|
| No symbols + no portfolio (stock/press mode) | Clear error message suggesting manual symbols or brokerage connection |
| FMP API error (rate limit, auth, timeout) | Caught by `FMPClient` exception hierarchy, surfaced as `{"status": "error", ...}` |
| FMP returns empty response | `fetch_raw` returns empty list, tool returns `article_count: 0` or `event_count: 0` (not an error) |
| Invalid date format | Pre-validated with `datetime.strptime`, returns error before FMP call |
| Date range > 90 days (calendar) | Pre-validated, returns error with guidance |
| `to_date` before `from_date` | Pre-validated, returns error |
| `portfolio_only=True` but no positions | Error from `_get_portfolio_tickers` caught and surfaced |
| Individual calendar fetch fails in "all" mode | `_fetch_calendar` catches exceptions and returns `[]`, other calendars still returned |
| Unexpected FMP response shape | Normalized: if dict instead of list, wrapped in `[dict]`; if empty, returns `[]` |

---

## Design Decisions

### 1. Single file for both tools (`mcp_tools/news_events.py`)
Both tools share the `_get_portfolio_tickers` helper and are in the same domain (market information / catalysts). This follows the pattern of `factor_intelligence.py` which hosts two related tools.

### 2. `fetch_raw` instead of `fetch`
News and calendar data is consumed as JSON dicts, not DataFrames. Using `fetch_raw` avoids the DataFrame conversion overhead and is more natural for pass-through data. The FMP endpoint registrations are still needed for `build_params` validation, URL building, and `_make_request` error handling.

### 3. No service class
Unlike risk analysis or factor intelligence, news/events are pure data retrieval with no computation. A service class would be an unnecessary abstraction layer. The MCP tool calls `FMPClient.fetch_raw()` directly.

### 4. Portfolio mode: opt-in for calendar, auto for news
- `get_news`: If you ask for stock news without specifying which stocks, it is reasonable to default to your portfolio. Auto-filling is the expected UX.
- `get_events_calendar`: The calendar is useful as a market-wide view. Asking "what earnings are coming up?" should not be limited to your holdings. The `portfolio_only` flag makes filtering explicit.

### 5. No `"report"` format
News and calendar data are already human-readable (titles, dates, amounts). A `"report"` format with extra prose would add minimal value over `"summary"`. Two formats (summary/full) keeps it clean.

### 6. Cache strategy: TTL-based
News uses 1-hour TTL (time-sensitive). Calendars use 6-hour TTL (update a few times daily). Both use `cache_enabled=True` so repeated calls within the window avoid FMP rate limits.

### 7. `symbols` as comma-separated string (not list)
FMP endpoints accept `symbols` as a comma-separated string. Passing a Python list through MCP would require JSON array parsing. A simple string is more ergonomic for both the LLM and direct usage: `symbols="AAPL,MSFT"`.

### 8. Top 10 tickers for news portfolio mode
Sending all 20+ holdings to FMP would return a diluted news feed. Top 10 by market value gives focused, relevant results. The `max_tickers` parameter on `_get_portfolio_tickers` makes this tunable.

---

## Verification Steps

### Import Tests
1. `from mcp_tools.news_events import get_news, get_events_calendar` — no import errors
2. `from fmp.registry import get_endpoint; get_endpoint("news_stock")` — endpoint registered

### News Tool Tests
3. `get_news(symbols="AAPL")` — status: success, articles present
4. `get_news(symbols="AAPL", format="full")` — complete article data
5. `get_news(mode="general")` — market news, no symbols needed
6. `get_news(symbols="TSLA", mode="press")` — press releases
7. `get_news()` — portfolio mode auto-fills symbols (requires connected brokerage)
8. `get_news(limit=3)` — respects limit

### Calendar Tool Tests
9. `get_events_calendar()` — earnings calendar, default 30-day window
10. `get_events_calendar(event_type="dividends")` — dividend dates
11. `get_events_calendar(event_type="all")` — all 4 calendars merged
12. `get_events_calendar(symbols="AAPL")` — filtered to single symbol
13. `get_events_calendar(portfolio_only=True)` — filtered to holdings
14. `get_events_calendar(from_date="2026-01-01", to_date="2026-06-01")` — 90-day error
15. `get_events_calendar(event_type="ipos")` — IPO calendar

### Error Cases
16. `get_news(mode="stock")` with no brokerage — clear error message
17. `get_events_calendar(from_date="invalid")` — date validation error
18. `get_events_calendar(from_date="2026-03-01", to_date="2026-02-01")` — to < from error

---

## Patterns Followed

| Pattern | Implementation |
|---------|---------------|
| stdout redirection | `sys.stdout = sys.stderr` in try/finally |
| Error handling | `try/except -> {"status": "error", "error": str(e)}` |
| Format switching | summary/full consistent structure |
| Tool registration | `@mcp.tool()` in `mcp_server.py` with full docstrings |
| Exports | `mcp_tools/__init__.py` imports + `__all__` |
| User resolution | `get_default_user()` via env var (no `user_email` MCP param for portfolio mode) |
| Portfolio loading | `_get_portfolio_tickers()` helper uses `PositionService` directly (same pattern as `_load_portfolio_weights()` in `factor_intelligence.py`) |
| FMP endpoints | Registered in `fmp/registry.py` with proper caching config |
| Parameter aliases | `from_date`/`to_date` auto-aliased to `from`/`to` by `PARAM_ALIASES` in `fmp/registry.py` |

---

## Estimated Complexity

| Component | Effort | Notes |
|-----------|--------|-------|
| `fmp/registry.py` — 7 endpoint registrations | Low | Boilerplate, follow existing pattern |
| `mcp_tools/news_events.py` — `get_news` | Low-Medium | Straightforward fetch + portfolio mode |
| `mcp_tools/news_events.py` — `get_events_calendar` | Medium | Multiple endpoints, merge, filter, date validation |
| `mcp_tools/news_events.py` — `_get_portfolio_tickers` | Low | Reuses `_load_portfolio_weights` pattern |
| `mcp_server.py` — 2 tool registrations | Low | Copy docstrings, wire params |
| `mcp_tools/__init__.py` + `README.md` updates | Low | Boilerplate |
| **Total** | **~2-3 hours** | No new services, no analysis logic, no temp files |

---

*Created: 2026-02-07*

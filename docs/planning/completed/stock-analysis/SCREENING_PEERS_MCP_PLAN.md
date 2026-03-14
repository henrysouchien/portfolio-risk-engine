# Implementation Plan: `screen_stocks` and `compare_peers` MCP Tools

**Date:** 2026-02-07
**Status:** Planning
**Depends on:** FMP client/registry infrastructure (already in place)

---

## Overview

Two new standalone MCP tools (no portfolio loading required) that wrap FMP endpoints for stock screening and peer comparison. Both follow the `analyze_stock` pattern: stateless, ticker-oriented, no user context needed.

After implementation the portfolio-mcp server will have **11 tools** (up from 9).

---

## Use Cases & Example Queries

These tools answer stock discovery and comparison questions. Example natural language queries:

- **"Find me healthcare stocks with dividend yield > 3% and market cap over $10B"** -- `screen_stocks(sector="Healthcare", dividend_min=3.0, market_cap_min=10000000000)`
- **"Show me undervalued tech stocks with P/E below 15"** -- `screen_stocks(sector="Technology")`, then the agent filters results by P/E from the returned data
- **"How does AAPL compare to its peer group on margins and growth?"** -- `compare_peers(symbol="AAPL", metrics=["grossProfitMarginTTM", "operatingProfitMarginTTM", "netProfitMarginTTM", "priceEarningsToGrowthRatioTTM"])`
- **"Which small-cap energy stocks have the lowest beta?"** -- `screen_stocks(sector="Energy", market_cap_max=2000000000, beta_max=1.0)`
- **"Compare NVDA's valuation against peers"** -- `compare_peers(symbol="NVDA")`

### Tool Chaining Example

A multi-step research workflow like **"Find high-dividend healthcare stocks, compare the top 3, and analyze the best one"** would chain tools together:

1. `screen_stocks(sector="Healthcare", dividend_min=3.0, market_cap_min=10000000000)` -- find candidates
2. `compare_peers(symbol="<top result>")` -- compare the top result against its peers on valuation, margins, and yield
3. `analyze_stock(ticker="<best candidate>")` -- deep-dive into the most attractive candidate's risk profile and fundamentals

The agent uses the output of each step to select inputs for the next, narrowing from a broad universe to a single actionable pick.

---

## Files to Create/Modify

### New Files
| File | Purpose |
|------|---------|
| `mcp_tools/screening.py` | `screen_stocks` and `compare_peers` tool implementations |

### Modified Files
| File | Change |
|------|--------|
| `fmp/registry.py` | Register 3 new endpoints: `company_screener`, `stock_peers`, `ratios_ttm` |
| `mcp_server.py` | Register 2 new `@mcp.tool()` wrappers |
| `mcp_tools/__init__.py` | Export `screen_stocks`, `compare_peers` |
| `mcp_tools/README.md` | Document both tools |

### Why One File (Not Two)
Both tools are stateless stock-discovery tools in the same domain (screening / idea generation). Grouping them in `mcp_tools/screening.py` follows the pattern of `mcp_tools/risk.py` (two related tools in one file) and `mcp_tools/factor_intelligence.py` (two tools in one file).

---

## FMP Endpoint Registrations

### 1. `company_screener`

```python
register_endpoint(
    FMPEndpoint(
        name="company_screener",
        path="/company-screener",
        description="Screen stocks by market cap, sector, beta, price, dividend, volume, country, exchange",
        fmp_docs_url="https://site.financialmodelingprep.com/developer/docs#stock-screener",
        category="screening",
        api_version="stable",
        params=[
            EndpointParam("marketCapMoreThan", ParamType.FLOAT, description="Min market cap (USD)"),
            EndpointParam("marketCapLowerThan", ParamType.FLOAT, description="Max market cap (USD)"),
            EndpointParam("sector", ParamType.STRING, description="Sector filter (e.g., Technology)"),
            EndpointParam("industry", ParamType.STRING, description="Industry filter (e.g., Software)"),
            EndpointParam("betaMoreThan", ParamType.FLOAT, description="Min beta"),
            EndpointParam("betaLowerThan", ParamType.FLOAT, description="Max beta"),
            EndpointParam("priceMoreThan", ParamType.FLOAT, description="Min stock price"),
            EndpointParam("priceLowerThan", ParamType.FLOAT, description="Max stock price"),
            EndpointParam("dividendMoreThan", ParamType.FLOAT, description="Min annual dividend"),
            EndpointParam("dividendLowerThan", ParamType.FLOAT, description="Max annual dividend"),
            EndpointParam("volumeMoreThan", ParamType.FLOAT, description="Min average volume"),
            EndpointParam("country", ParamType.STRING, description="Country filter (e.g., US)"),
            EndpointParam("exchange", ParamType.STRING, description="Exchange filter (e.g., NASDAQ)"),
            EndpointParam("isEtf", ParamType.BOOLEAN, description="Filter for ETFs only"),
            EndpointParam("isFund", ParamType.BOOLEAN, description="Filter for funds only"),
            EndpointParam("isActivelyTrading", ParamType.BOOLEAN, default=True, description="Only actively trading"),
            EndpointParam("limit", ParamType.INTEGER, default=50, description="Max results"),
        ],
        cache_dir="cache/screening",
        cache_refresh=CacheRefresh.TTL,
        cache_ttl_hours=6,  # Screener data refreshes intraday
    )
)
```

**Design note:** The FMP API uses `marketCapMoreThan`/`marketCapLowerThan` style naming. The MCP tool will expose friendlier `market_cap_min`/`market_cap_max` params and map them internally. The registry uses the FMP-native names so that `build_params()` passes them through directly.

### 2. `stock_peers`

```python
register_endpoint(
    FMPEndpoint(
        name="stock_peers",
        path="/stock-peers",
        description="Get peer companies for a stock (same sector, similar market cap)",
        fmp_docs_url="https://site.financialmodelingprep.com/developer/docs#stock-peers",
        category="screening",
        api_version="stable",
        params=[
            EndpointParam("symbol", ParamType.STRING, required=True, description="Stock symbol"),
        ],
        cache_dir="cache/screening",
        cache_refresh=CacheRefresh.TTL,
        cache_ttl_hours=168,  # Peers change slowly (1 week)
    )
)
```

### 3. `ratios_ttm`

```python
register_endpoint(
    FMPEndpoint(
        name="ratios_ttm",
        path="/ratios-ttm",
        description="Trailing twelve month financial ratios (P/E, ROE, margins, leverage)",
        fmp_docs_url="https://site.financialmodelingprep.com/developer/docs#company-financial-ratios",
        category="fundamentals",
        api_version="stable",
        params=[
            EndpointParam("symbol", ParamType.STRING, required=True, description="Stock symbol"),
        ],
        cache_dir="cache/fundamentals",
        cache_refresh=CacheRefresh.TTL,
        cache_ttl_hours=24,  # TTM ratios update daily
    )
)
```

---

## Tool 1: `screen_stocks`

### MCP Tool Function Signature

```python
# mcp_tools/screening.py

def screen_stocks(
    sector: Optional[str] = None,
    industry: Optional[str] = None,
    market_cap_min: Optional[float] = None,
    market_cap_max: Optional[float] = None,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    dividend_min: Optional[float] = None,
    dividend_max: Optional[float] = None,
    beta_min: Optional[float] = None,
    beta_max: Optional[float] = None,
    volume_min: Optional[float] = None,
    country: Optional[str] = None,
    exchange: Optional[str] = None,
    is_etf: Optional[bool] = None,
    limit: int = 50,
    format: Literal["full", "summary"] = "summary",
) -> dict:
```

### Data Flow

```
MCP params (user-friendly)
    ↓
_build_screener_params()           ← maps market_cap_min → marketCapMoreThan, etc.
    ↓
FMPClient.fetch_raw("company_screener", **mapped_params)
    ↓
Raw JSON list of dicts
    ↓
format == "summary" → _format_screener_summary()
format == "full"    → raw results with status
```

### Parameter Mapping (MCP -> FMP)

The tool exposes user-friendly snake_case params and maps them to FMP API names internally:

| MCP Param | FMP API Param |
|-----------|---------------|
| `market_cap_min` | `marketCapMoreThan` |
| `market_cap_max` | `marketCapLowerThan` |
| `price_min` | `priceMoreThan` |
| `price_max` | `priceLowerThan` |
| `dividend_min` | `dividendMoreThan` |
| `dividend_max` | `dividendLowerThan` |
| `beta_min` | `betaMoreThan` |
| `beta_max` | `betaLowerThan` |
| `volume_min` | `volumeMoreThan` |
| `sector` | `sector` (pass-through) |
| `industry` | `industry` (pass-through) |
| `country` | `country` (pass-through) |
| `exchange` | `exchange` (pass-through) |
| `is_etf` | `isEtf` |
| `limit` | `limit` (pass-through) |

This mapping happens in a `_build_screener_params()` helper inside `screening.py`. Only non-None values are included.

### Why `fetch_raw` Instead of `fetch`

The screener returns a flat list of company objects. Using `fetch_raw()` avoids the unnecessary DataFrame conversion since the MCP tool returns JSON dicts directly. This follows the pattern of returning structured dicts, not DataFrames.

### Output Formats

#### Summary Format
```python
{
    "status": "success",
    "result_count": 25,
    "filters_applied": {
        "sector": "Technology",
        "market_cap_min": 10_000_000_000,
        "beta_max": 1.5
    },
    "results": [
        {
            "symbol": "AAPL",
            "name": "Apple Inc.",
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "market_cap": 3_000_000_000_000,
            "price": 189.50,
            "beta": 1.24,
            "volume": 55_000_000,
            "dividend": 0.96,
            "exchange": "NASDAQ",
            "country": "US"
        },
        # ... up to `limit` results
    ]
}
```

**Summary formatting:** Market cap values are passed through as raw numbers (not formatted strings) so the LLM can reason about them numerically. The `filters_applied` dict echoes back which filters were active for context.

#### Full Format
```python
{
    "status": "success",
    "result_count": 25,
    "filters_applied": {...},
    "results": [
        # Raw FMP response objects (all fields)
    ]
}
```

### Error Handling

1. **No filters provided:** Return a helpful error suggesting at least one filter. The screener without any filters returns thousands of results, which is not useful and wastes an API call.
2. **Empty results:** Return `{"status": "success", "result_count": 0, "results": [], "filters_applied": {...}}` with a note suggesting broader filters.
3. **FMP API errors:** Caught by top-level try/except, returned as `{"status": "error", "error": str(e)}`.
4. **Invalid sector/industry/exchange names:** FMP returns empty results for unknown values. No pre-validation needed; the empty-result handler covers this.

### Validation Logic

```python
def _build_screener_params(...) -> dict:
    """Map user-friendly params to FMP API names. Only includes non-None values."""
    params = {}
    PARAM_MAP = {
        "market_cap_min": "marketCapMoreThan",
        "market_cap_max": "marketCapLowerThan",
        "price_min": "priceMoreThan",
        "price_max": "priceLowerThan",
        "dividend_min": "dividendMoreThan",
        "dividend_max": "dividendLowerThan",
        "beta_min": "betaMoreThan",
        "beta_max": "betaLowerThan",
        "volume_min": "volumeMoreThan",
        "is_etf": "isEtf",
    }
    # Pass-through params (same name in MCP and FMP)
    PASSTHROUGH = ["sector", "industry", "country", "exchange", "limit"]

    for mcp_name, fmp_name in PARAM_MAP.items():
        value = locals_dict.get(mcp_name)  # passed as kwargs
        if value is not None:
            params[fmp_name] = value

    for name in PASSTHROUGH:
        value = locals_dict.get(name)
        if value is not None:
            params[name] = value

    # Always include isActivelyTrading=True
    params["isActivelyTrading"] = True

    return params
```

---

## Tool 2: `compare_peers`

### MCP Tool Function Signature

```python
# mcp_tools/screening.py

def compare_peers(
    symbol: str,
    metrics: Optional[list[str]] = None,
    include_subject: bool = True,
    format: Literal["full", "summary"] = "summary",
) -> dict:
```

### Data Flow

```
symbol
    ↓
Step 1: FMPClient.fetch_raw("stock_peers", symbol=symbol)
    ↓
peer_list: list[str]    e.g., ["MSFT", "GOOGL", "META", "AMZN"]
    ↓
if include_subject: prepend symbol to list
    ↓
Step 2: For each ticker in list:
        FMPClient.fetch_raw("ratios_ttm", symbol=ticker)
    ↓
ratios_by_ticker: dict[str, dict]
    ↓
Step 3: _build_comparison_table(ratios_by_ticker, metrics)
    ↓
format == "summary" → filtered to DEFAULT_METRICS
format == "full"    → all ratios returned
```

### Peer List Handling

The `/stable/stock-peers` endpoint returns a response like:
```json
[{"symbol": "AAPL", "peersList": ["MSFT", "GOOGL", "META", "AMZN", ...]}]
```

Steps:
1. Extract `peersList` from the first item.
2. If `include_subject` is True, prepend the input `symbol` to the list so it appears first in the comparison.
3. Cap the peer list to a reasonable maximum (10 peers) to avoid excessive API calls.

### Default Metrics (Summary)

When `metrics` is None and `format="summary"`, use this curated subset:

```python
DEFAULT_PEER_METRICS = [
    "peRatioTTM",
    "priceToBookRatioTTM",
    "priceToSalesRatioTTM",
    "returnOnEquityTTM",
    "returnOnAssetsTTM",
    "grossProfitMarginTTM",
    "operatingProfitMarginTTM",
    "netProfitMarginTTM",
    "debtEquityRatioTTM",
    "currentRatioTTM",
    "dividendYieldTTM",
    "priceEarningsToGrowthRatioTTM",
]
```

These cover valuation, profitability, margins, leverage, and yield. The user can override with the `metrics` param to request specific ratios.

### Metric Name Mapping

The FMP ratios-ttm endpoint returns camelCase keys (e.g., `peRatioTTM`, `returnOnEquityTTM`). For the summary format, we provide display-friendly labels:

```python
METRIC_LABELS = {
    "peRatioTTM": "P/E Ratio",
    "priceToBookRatioTTM": "P/B Ratio",
    "priceToSalesRatioTTM": "P/S Ratio",
    "returnOnEquityTTM": "ROE",
    "returnOnAssetsTTM": "ROA",
    "grossProfitMarginTTM": "Gross Margin",
    "operatingProfitMarginTTM": "Operating Margin",
    "netProfitMarginTTM": "Net Margin",
    "debtEquityRatioTTM": "Debt/Equity",
    "currentRatioTTM": "Current Ratio",
    "dividendYieldTTM": "Dividend Yield",
    "priceEarningsToGrowthRatioTTM": "PEG Ratio",
}
```

### Output Formats

#### Summary Format
```python
{
    "status": "success",
    "subject": "AAPL",
    "peers": ["MSFT", "GOOGL", "META", "AMZN"],
    "peer_count": 4,
    "comparison": [
        {
            "metric": "P/E Ratio",
            "metric_key": "peRatioTTM",
            "AAPL": 28.5,
            "MSFT": 34.2,
            "GOOGL": 25.1,
            "META": 22.8,
            "AMZN": 58.3
        },
        {
            "metric": "ROE",
            "metric_key": "returnOnEquityTTM",
            "AAPL": 1.61,
            "MSFT": 0.38,
            "GOOGL": 0.27,
            "META": 0.30,
            "AMZN": 0.22
        },
        # ... one row per metric
    ],
    "failed_tickers": []  # tickers where ratios fetch failed
}
```

This "pivoted" structure (one row per metric, one column per ticker) is the natural comparison table shape. The LLM can easily present it as a table.

#### Full Format
```python
{
    "status": "success",
    "subject": "AAPL",
    "peers": ["MSFT", "GOOGL", "META", "AMZN"],
    "peer_count": 4,
    "ratios": {
        "AAPL": {
            "peRatioTTM": 28.5,
            "priceToBookRatioTTM": 45.2,
            # ... all ~60 TTM ratios
        },
        "MSFT": { ... },
        # ...
    },
    "failed_tickers": []
}
```

### Error Handling

1. **No peers found:** FMP returns empty `peersList` for some tickers (small-caps, foreign stocks, ETFs). Return a clear message: `"No peers found for {symbol}. This endpoint works best for US large/mid-cap stocks."`.
2. **Ratios fetch failure for individual peers:** Collect errors in `failed_tickers` list but continue with remaining peers. Do not fail the entire comparison because one peer's ratios are unavailable.
3. **Invalid symbol:** FMP returns empty response; caught as `FMPEmptyResponseError` or empty list. Return helpful error.
4. **Custom metrics validation:** If `metrics` is provided but contains unknown keys, include a `"note"` field listing unrecognized metrics (they will simply be absent from the comparison rows). Do not fail.
5. **All peers fail ratios fetch:** Return error if zero valid ratio sets were retrieved.

### API Call Pattern (Sequential vs. Parallel)

Ratios are fetched sequentially in a loop. For a typical peer list of 5-10 tickers, this means 5-10 API calls taking ~1-3 seconds total. This is acceptable for an MCP tool call. If performance becomes a concern later, `concurrent.futures.ThreadPoolExecutor` could parallelize the fetches, but this is out of scope for the initial implementation.

---

## mcp_server.py Registration

### screen_stocks

```python
from mcp_tools.screening import screen_stocks as _screen_stocks

@mcp.tool()
def screen_stocks(
    sector: Optional[str] = None,
    industry: Optional[str] = None,
    market_cap_min: Optional[float] = None,
    market_cap_max: Optional[float] = None,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    dividend_min: Optional[float] = None,
    dividend_max: Optional[float] = None,
    beta_min: Optional[float] = None,
    beta_max: Optional[float] = None,
    volume_min: Optional[float] = None,
    country: Optional[str] = None,
    exchange: Optional[str] = None,
    is_etf: Optional[bool] = None,
    limit: int = 50,
    format: Literal["full", "summary"] = "summary",
) -> dict:
    """
    Screen stocks by fundamental criteria (sector, market cap, beta, dividend, etc.).

    Searches the full universe of stocks and ETFs using financial filters.
    Combine multiple criteria to narrow results.

    Args:
        sector: Sector filter (e.g., "Technology", "Healthcare", "Energy").
        industry: Industry filter (e.g., "Software", "Biotechnology").
        market_cap_min: Minimum market capitalization in USD (e.g., 10000000000 for $10B).
        market_cap_max: Maximum market capitalization in USD.
        price_min: Minimum stock price.
        price_max: Maximum stock price.
        dividend_min: Minimum annual dividend per share.
        dividend_max: Maximum annual dividend per share.
        beta_min: Minimum beta (market sensitivity).
        beta_max: Maximum beta.
        volume_min: Minimum average daily volume.
        country: Country filter (e.g., "US", "GB", "JP").
        exchange: Exchange filter (e.g., "NASDAQ", "NYSE", "LSE").
        is_etf: Set to true to screen ETFs only, false for stocks only.
        limit: Maximum number of results (default: 50).
        format: Output format:
            - "summary": Key metrics per result (symbol, name, sector, market cap, price, beta)
            - "full": All available fields from the screener

    Returns:
        Screening results with status field ("success" or "error").

    Examples:
        "Find large-cap tech stocks" -> screen_stocks(sector="Technology", market_cap_min=10000000000)
        "Low beta dividend stocks" -> screen_stocks(beta_max=0.8, dividend_min=2.0)
        "Show me biotech stocks under $50" -> screen_stocks(industry="Biotechnology", price_max=50)
        "Screen for ETFs" -> screen_stocks(is_etf=True)
        "High volume NASDAQ stocks" -> screen_stocks(exchange="NASDAQ", volume_min=5000000)
    """
    return _screen_stocks(
        sector=sector,
        industry=industry,
        market_cap_min=market_cap_min,
        market_cap_max=market_cap_max,
        price_min=price_min,
        price_max=price_max,
        dividend_min=dividend_min,
        dividend_max=dividend_max,
        beta_min=beta_min,
        beta_max=beta_max,
        volume_min=volume_min,
        country=country,
        exchange=exchange,
        is_etf=is_etf,
        limit=limit,
        format=format,
    )
```

### compare_peers

```python
from mcp_tools.screening import compare_peers as _compare_peers

@mcp.tool()
def compare_peers(
    symbol: str,
    metrics: Optional[list[str]] = None,
    include_subject: bool = True,
    format: Literal["full", "summary"] = "summary",
) -> dict:
    """
    Compare a stock against its peers on key financial ratios.

    Fetches the peer group for a stock (companies in the same sector with
    similar market cap) and builds a side-by-side comparison of financial
    ratios including valuation, profitability, margins, and leverage.

    Args:
        symbol: Stock symbol to compare (e.g., "AAPL", "MSFT").
        metrics: Optional list of specific ratio keys to compare.
            Default summary metrics: P/E, P/B, P/S, ROE, ROA, gross margin,
            operating margin, net margin, debt/equity, current ratio,
            dividend yield, PEG ratio.
            Use format="full" to see all available ratio keys.
        include_subject: Include the input stock in the comparison table
            (default: True). Set to False to see only peers.
        format: Output format:
            - "summary": Comparison table with default or selected metrics
            - "full": All TTM ratios for each peer (60+ metrics)

    Returns:
        Peer comparison data with status field ("success" or "error").

    Examples:
        "Compare AAPL to its peers" -> compare_peers(symbol="AAPL")
        "How does MSFT stack up against peers?" -> compare_peers(symbol="MSFT")
        "Compare TSLA peers on P/E and ROE" -> compare_peers(symbol="TSLA", metrics=["peRatioTTM", "returnOnEquityTTM"])
        "Show me NVDA's peer group ratios" -> compare_peers(symbol="NVDA", format="full")
    """
    return _compare_peers(
        symbol=symbol,
        metrics=metrics,
        include_subject=include_subject,
        format=format,
    )
```

---

## Implementation Details: `mcp_tools/screening.py`

### File Structure

```python
"""
MCP Tools: screen_stocks, compare_peers

Exposes stock screening and peer comparison as MCP tools for AI invocation.

Usage (from Claude):
    "Find large-cap tech stocks" -> screen_stocks(sector="Technology", market_cap_min=10000000000)
    "Compare AAPL to its peers" -> compare_peers(symbol="AAPL")

Architecture note:
- Standalone tools (no portfolio loading, no user context required)
- Wraps FMP company-screener, stock-peers, and ratios-ttm endpoints
- stdout is redirected to stderr to protect MCP JSON-RPC channel from stray prints
"""

import sys
from typing import Optional, Literal

from fmp.client import FMPClient


# === Constants ===

# MCP param name -> FMP API param name
_SCREENER_PARAM_MAP = { ... }

# Default metrics for compare_peers summary
DEFAULT_PEER_METRICS = [ ... ]

# Display labels for metric keys
METRIC_LABELS = { ... }

# Max peers to fetch ratios for (prevents excessive API calls)
MAX_PEERS = 10


# === Helpers ===

def _build_screener_params(**kwargs) -> dict:
    """Map user-friendly MCP params to FMP screener API params."""
    ...

def _format_screener_summary(results: list[dict]) -> list[dict]:
    """Extract key fields from raw screener results for summary format."""
    ...

def _build_comparison_table(
    ratios_by_ticker: dict[str, dict],
    metrics: list[str],
) -> list[dict]:
    """Pivot ratios into comparison rows (one row per metric, one column per ticker)."""
    ...


# === Tools ===

def screen_stocks(...) -> dict:
    ...

def compare_peers(...) -> dict:
    ...
```

### Key Implementation Notes

1. **stdout redirect:** Both tools use the standard `_saved = sys.stdout; sys.stdout = sys.stderr` pattern with try/finally, matching `stock.py` and all other MCP tools.

2. **FMPClient instantiation:** Use `FMPClient()` directly (not `get_client()` singleton) since the screener and peer tools have no state. Alternatively, `from fmp.client import get_client; fmp = get_client()` is fine too. Either works; `get_client()` is marginally more efficient for repeated calls within the same process.

3. **`fetch_raw` vs `fetch`:** Both tools use `fetch_raw()` since they return JSON dicts to the MCP caller, not DataFrames. The `fetch()` method converts to DataFrame which is unnecessary overhead.

4. **No `use_cache` MCP param:** Unlike portfolio-dependent tools, these are pure FMP lookups. Caching is handled at the FMP client layer (TTL-based, configured in the endpoint registration). No need to expose a `use_cache` toggle at the MCP level since:
   - Screener results with 6-hour TTL are fresh enough
   - Peers with 1-week TTL change rarely
   - Ratios with 24-hour TTL update daily

   If a user needs fresh data, the TTL expiration handles it automatically.

5. **`isActivelyTrading=True`:** Always injected for the screener to avoid returning delisted/suspended stocks. This is a sensible default that the MCP user should not need to think about.

6. **Screener requires at least one filter:** Validated before the API call. An unfiltered screener request returns thousands of results and is likely a mistake.

---

## `__init__.py` Update

```python
from mcp_tools.screening import screen_stocks, compare_peers

__all__ = [
    # ... existing ...
    "screen_stocks",
    "compare_peers",
]
```

---

## `README.md` Updates

Add entries for both tools following the existing format (MCP Tool Parameters table, examples, return format). Add `screening.py` to the File Organization section. Update the architecture diagram to show 11 tools.

---

## Estimated Complexity

| Component | Effort | Notes |
|-----------|--------|-------|
| FMP endpoint registrations (3) | Small | Copy-paste pattern from existing endpoints |
| `_build_screener_params` helper | Small | Dict mapping, ~20 lines |
| `screen_stocks` tool | Small | Straightforward API call + format, ~50 lines |
| `compare_peers` tool | Medium | Multi-step (peers -> ratios loop -> pivot), ~80 lines |
| `_build_comparison_table` helper | Small | List comprehension with metric filtering, ~20 lines |
| `mcp_server.py` registration (2) | Small | Copy-paste pattern, docstrings are the main work |
| `__init__.py` + `README.md` | Small | Boilerplate updates |
| **Total** | **~200-250 lines new code** | Mostly in `mcp_tools/screening.py` |

**Estimated implementation time:** 1-2 hours. No new services, no database access, no portfolio loading. Both tools are thin wrappers around FMP endpoint calls with formatting logic.

---

## Testing Approach

### Manual Testing

```python
# Test screen_stocks
from mcp_tools.screening import screen_stocks

# Basic sector screen
result = screen_stocks(sector="Technology", market_cap_min=10_000_000_000)
assert result["status"] == "success"
assert result["result_count"] > 0

# No filters (should error)
result = screen_stocks()
assert result["status"] == "error"

# ETF screening
result = screen_stocks(is_etf=True, limit=10)
assert result["status"] == "success"

# Test compare_peers
from mcp_tools.screening import compare_peers

# Basic peer comparison
result = compare_peers(symbol="AAPL")
assert result["status"] == "success"
assert len(result["comparison"]) == len(DEFAULT_PEER_METRICS)

# Custom metrics
result = compare_peers(symbol="MSFT", metrics=["peRatioTTM", "returnOnEquityTTM"])
assert result["status"] == "success"
assert len(result["comparison"]) == 2

# Without subject
result = compare_peers(symbol="AAPL", include_subject=False)
assert result["status"] == "success"
assert "AAPL" not in result.get("peers", []) or "AAPL" not in result["comparison"][0]

# Full format
result = compare_peers(symbol="GOOGL", format="full")
assert "ratios" in result
```

### MCP Protocol Testing

```bash
# Verify tools are registered
cd /path/to/risk_module
RISK_MODULE_USER_EMAIL=test@example.com python3 mcp_server.py 2>/dev/null << 'EOF'
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}
EOF
# Should list 11 tools including screen_stocks and compare_peers
```

---

## Open Questions / Future Enhancements

1. **Sort order for screener results:** FMP returns results in an unspecified order. Could add a `sort_by` param (e.g., `market_cap`, `beta`, `dividend`) with client-side sorting. Not needed for v1 since the LLM can sort the returned data.

2. **Available sectors/industries/exchanges reference:** FMP has `/stable/available-sectors`, `/stable/available-industries`, `/stable/available-exchanges` endpoints. These could be registered and used for param validation or exposed as a helper. Deferred to a later iteration.

3. **Parallel ratio fetching for `compare_peers`:** Sequential fetching is fine for 5-10 peers. If we add a "custom peer list" feature (user provides arbitrary list of 20+ tickers), parallel fetching would be worth adding.

4. **`compare_peers` with custom ticker list:** Currently only supports FMP's automatic peer detection. A future enhancement could accept `tickers: list[str]` as an alternative to `symbol`, allowing arbitrary comparisons (e.g., "compare AAPL, MSFT, GOOGL on margins").

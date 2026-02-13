# Macro & Market Context MCP Tools — Implementation Plan

**Date:** 2026-02-07
**Status:** Plan ready for implementation
**Tools:** `get_economic_data`, `get_sector_overview`, `get_market_context`
**Predecessor research:** `docs/planning/NEW_MCP_TOOLS_RESEARCH.md` (Gap 2: Macro & Market Context)

---

## Overview

Three new MCP tools that provide macro-economic, sector, and market context data by combining multiple FMP endpoints. These tools complement the existing portfolio-centric tools (risk, performance, optimization) with market-level intelligence.

| Tool | Complexity | FMP Endpoints | New Registrations | Estimated LoC |
|------|-----------|---------------|-------------------|---------------|
| `get_economic_data` | Low | 2 | 2 | ~200 |
| `get_sector_overview` | Medium | 3-4 | 4 | ~300 |
| `get_market_context` | Medium-High | 6-7 | 4 (reuses sector) | ~350 |
| **Total** | | | **10** | **~850** |

---

## Use Cases & Example Queries

These tools answer questions about economic conditions, sector dynamics, and daily market activity. Example natural language queries:

- **"What's the latest CPI reading and is inflation trending up or down?"** -- `get_economic_data(indicator_name="CPI")` returns the latest value, trend direction, and recent history
- **"Give me a market summary for today"** -- `get_market_context()` provides index levels, sector heatmap, top movers, and upcoming events in one call
- **"Which sectors are cheap right now and am I overweight any of them?"** -- `get_sector_overview(include_portfolio=True)` overlays portfolio sector weights on top of sector P/E ratios and performance
- **"How is the economy doing? Is a recession likely?"** -- `get_economic_data(indicator_name="smoothedUSRecessionProbabilities")` plus `get_economic_data(indicator_name="unemploymentRate")` for key recession indicators
- **"What economic events are coming up this month?"** -- `get_economic_data(mode="calendar")` returns upcoming releases with forecasts and impact ratings

### Tool Chaining Example

A complex question like **"How is my portfolio positioned for rising rates?"** would chain multiple tools:

1. `get_economic_data(indicator_name="federalFunds")` -- check the fed funds rate trend to confirm the rate environment
2. `get_sector_overview(include_portfolio=True)` -- see portfolio sector exposure and identify rate-sensitive sectors (Utilities, Real Estate)
3. `get_risk_analysis(include=["factor_analysis"])` -- check portfolio factor exposures, particularly interest rate sensitivity

The agent synthesizes outputs from all three tools to assess whether the portfolio is defensively or aggressively positioned relative to the rate trajectory.

---

## Files to Create/Modify

### New Files
| File | Purpose |
|------|---------|
| `mcp_tools/market.py` | All three tool implementations (`get_economic_data`, `get_sector_overview`, `get_market_context`) |

### Modified Files
| File | Change |
|------|--------|
| `fmp/registry.py` | Register 10 new FMP endpoints (macro, sector, market movers) |
| `mcp_server.py` | Register 3 new `@mcp.tool()` wrappers (tools 10-12) |
| `mcp_tools/__init__.py` | Export the 3 new tools |
| `mcp_tools/README.md` | Document the 3 new tools |

### Why One File (`mcp_tools/market.py`)

All three tools share a common domain (market context), common FMP client usage, and common helper functions (date defaults, FMP error mapping). Grouping follows the precedent of `mcp_tools/risk.py` (2 tools) and `mcp_tools/factor_intelligence.py` (2 tools + shared helper).

---

## FMP Endpoint Registrations (10 new endpoints)

All registered in `fmp/registry.py`. Grouped by usage.

### Economic (2 endpoints)

```python
# 1. Economic Indicators
register_endpoint(FMPEndpoint(
    name="economic_indicators",
    path="/economic-indicators",
    description="Economic indicator time series (GDP, CPI, unemployment, etc.)",
    category="macro",
    api_version="stable",
    params=[
        EndpointParam("name", ParamType.STRING, required=True,
                      description="Indicator name (GDP, CPI, federalFunds, unemploymentRate, etc.)"),
        EndpointParam("from", ParamType.DATE, description="Start date (YYYY-MM-DD)"),
        EndpointParam("to", ParamType.DATE, description="End date (YYYY-MM-DD)"),
    ],
    cache_dir="cache/macro",
    cache_refresh=CacheRefresh.TTL,
    cache_ttl_hours=24,  # Economic data updates infrequently but worth refreshing daily
))

# 2. Economic Calendar
register_endpoint(FMPEndpoint(
    name="economic_calendar",
    path="/economic-calendar",
    description="Upcoming/recent economic events with prior/forecast/actual values",
    category="macro",
    api_version="stable",
    params=[
        EndpointParam("from", ParamType.DATE, description="Start date (YYYY-MM-DD)"),
        EndpointParam("to", ParamType.DATE, description="End date (YYYY-MM-DD)"),
    ],
    cache_dir="cache/macro",
    cache_refresh=CacheRefresh.TTL,
    cache_ttl_hours=6,  # Calendar events update throughout the day
))
```

### Sector (4 endpoints)

```python
# 3. Sector Performance Snapshot
register_endpoint(FMPEndpoint(
    name="sector_performance_snapshot",
    path="/sector-performance-snapshot",
    description="Daily sector percentage change snapshot",
    category="sector",
    api_version="stable",
    params=[
        EndpointParam("date", ParamType.DATE, description="Snapshot date (YYYY-MM-DD)"),
    ],
    cache_dir="cache/sector",
    cache_refresh=CacheRefresh.TTL,
    cache_ttl_hours=1,  # Intraday snapshots change frequently
))

# 4. Sector P/E Snapshot
register_endpoint(FMPEndpoint(
    name="sector_pe_snapshot",
    path="/sector-pe-snapshot",
    description="Sector aggregate P/E ratio snapshot",
    category="sector",
    api_version="stable",
    params=[
        EndpointParam("date", ParamType.DATE, description="Snapshot date (YYYY-MM-DD)"),
    ],
    cache_dir="cache/sector",
    cache_refresh=CacheRefresh.TTL,
    cache_ttl_hours=24,  # P/E changes slowly
))

# 5. Historical Sector Performance
register_endpoint(FMPEndpoint(
    name="historical_sector_performance",
    path="/historical-sector-performance",
    description="Historical sector performance time series",
    category="sector",
    api_version="stable",
    params=[
        EndpointParam("sector", ParamType.STRING, required=True, description="Sector name (e.g., Energy)"),
        EndpointParam("from", ParamType.DATE, description="Start date (YYYY-MM-DD)"),
        EndpointParam("to", ParamType.DATE, description="End date (YYYY-MM-DD)"),
    ],
    cache_dir="cache/sector",
    cache_refresh=CacheRefresh.HASH_ONLY,
))

# 6. Historical Sector P/E
register_endpoint(FMPEndpoint(
    name="historical_sector_pe",
    path="/historical-sector-pe",
    description="Historical sector P/E ratio time series",
    category="sector",
    api_version="stable",
    params=[
        EndpointParam("sector", ParamType.STRING, required=True, description="Sector name (e.g., Energy)"),
        EndpointParam("from", ParamType.DATE, description="Start date (YYYY-MM-DD)"),
        EndpointParam("to", ParamType.DATE, description="End date (YYYY-MM-DD)"),
    ],
    cache_dir="cache/sector",
    cache_refresh=CacheRefresh.HASH_ONLY,
))
```

### Market Movers (4 endpoints)

```python
# 7. Biggest Gainers
register_endpoint(FMPEndpoint(
    name="biggest_gainers",
    path="/biggest-gainers",
    description="Top gaining stocks by percentage change",
    category="market_movers",
    api_version="stable",
    params=[],
    cache_dir="cache/market",
    cache_refresh=CacheRefresh.TTL,
    cache_ttl_hours=1,  # Changes throughout the trading day
))

# 8. Biggest Losers
register_endpoint(FMPEndpoint(
    name="biggest_losers",
    path="/biggest-losers",
    description="Top losing stocks by percentage change",
    category="market_movers",
    api_version="stable",
    params=[],
    cache_dir="cache/market",
    cache_refresh=CacheRefresh.TTL,
    cache_ttl_hours=1,
))

# 9. Most Actives
register_endpoint(FMPEndpoint(
    name="most_actives",
    path="/most-actives",
    description="Most actively traded stocks by volume",
    category="market_movers",
    api_version="stable",
    params=[],
    cache_dir="cache/market",
    cache_refresh=CacheRefresh.TTL,
    cache_ttl_hours=1,
))

# 10. Batch Index Quotes
register_endpoint(FMPEndpoint(
    name="batch_index_quotes",
    path="/batch-index-quotes",
    description="Batch quotes for major market indices (S&P 500, DJIA, Nasdaq, Russell)",
    category="market_movers",
    api_version="stable",
    params=[],
    cache_dir="cache/market",
    cache_refresh=CacheRefresh.TTL,
    cache_ttl_hours=1,
))
```

---

## Tool 1: `get_economic_data`

### Function Signature

```python
def get_economic_data(
    mode: Literal["indicator", "calendar"] = "indicator",
    indicator_name: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    format: Literal["full", "summary"] = "summary",
    use_cache: bool = True,
) -> dict:
```

### Parameters

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `mode` | `"indicator"` or `"calendar"` | `"indicator"` | Which data type to fetch |
| `indicator_name` | `str` (optional) | `None` | Required for indicator mode. One of: `GDP`, `realGDP`, `CPI`, `inflationRate`, `federalFunds`, `unemploymentRate`, `totalNonfarmPayroll`, `initialClaims`, `consumerSentiment`, `retailSales`, `durableGoods`, `industrialProductionTotalIndex`, `housingStarts`, `totalVehicleSales`, `smoothedUSRecessionProbabilities`, `30YearFixedRateMortgageAverage`, `tradeBalanceGoodsAndServices` |
| `from_date` | `str` (optional) | `None` | Start date (YYYY-MM-DD). Defaults: indicator mode = 2 years ago; calendar mode = today |
| `to_date` | `str` (optional) | `None` | End date (YYYY-MM-DD). Defaults: indicator mode = today; calendar mode = 30 days from now |
| `format` | `"full"` or `"summary"` | `"summary"` | Output level |
| `use_cache` | `bool` | `True` | Use cached data |

### Data Flow

```
mode="indicator":
  1. Validate indicator_name is provided and is in VALID_INDICATORS list
  2. Apply date defaults (2 years back if no from_date)
  3. FMPClient.fetch("economic_indicators", name=indicator_name, from_date=..., to_date=...)
  4. Returns DataFrame with columns: date, value, ...
  5. Format as summary or full

mode="calendar":
  1. Apply date defaults (today to +30 days)
  2. Validate date range <= 90 days (FMP limit)
  3. FMPClient.fetch("economic_calendar", from_date=..., to_date=...)
  4. Returns DataFrame with: event, date, country, previous, estimate, actual, impact, ...
  5. Format as summary or full
```

### Output Structures

#### Summary — Indicator Mode

```python
{
    "status": "success",
    "mode": "indicator",
    "indicator": "CPI",
    "latest_value": 314.175,
    "latest_date": "2026-01-01",
    "previous_value": 312.855,
    "change": 1.32,
    "change_pct": 0.42,
    "trend": "rising",         # "rising", "falling", "stable" (based on 3-month slope)
    "data_points": 24,
    "period": {"from": "2024-02-01", "to": "2026-02-01"},
}
```

#### Summary — Calendar Mode

```python
{
    "status": "success",
    "mode": "calendar",
    "event_count": 47,
    "upcoming_high_impact": [    # Top 5 upcoming high-impact events
        {
            "event": "Non Farm Payrolls",
            "date": "2026-02-07",
            "country": "US",
            "previous": 256000,
            "estimate": 170000,
            "actual": null,      # null if not yet released
            "impact": "High",
        },
        ...
    ],
    "recent_surprises": [        # Events where actual != estimate (last 7 days)
        {
            "event": "Initial Claims",
            "date": "2026-02-06",
            "estimate": 215000,
            "actual": 219000,
            "surprise_pct": 1.86,
        },
        ...
    ],
    "period": {"from": "2026-02-07", "to": "2026-03-09"},
}
```

#### Full (both modes)

```python
{
    "status": "success",
    "mode": "indicator",  # or "calendar"
    "data": [...],       # Full list of records from FMP
    "row_count": 24,
    "columns": ["date", "value"],
}
```

### Error Handling

- Missing `indicator_name` in indicator mode: return `{"status": "error", "error": "indicator_name is required when mode='indicator'. Available: GDP, CPI, ..."}`
- Invalid `indicator_name`: return error with list of valid indicator names
- Calendar date range > 90 days: return error with explanation of FMP limit
- FMP API errors: caught via try/except at tool boundary, mapped to `{"status": "error", "error": str(e)}`
- Empty response: return success with `data_points: 0` and appropriate message

### Trend Computation Logic

```python
def _compute_trend(values: list[float], window: int = 3) -> str:
    """Determine trend from last N data points."""
    if len(values) < 2:
        return "insufficient_data"
    recent = values[-window:] if len(values) >= window else values
    if all(recent[i] <= recent[i+1] for i in range(len(recent)-1)):
        return "rising"
    elif all(recent[i] >= recent[i+1] for i in range(len(recent)-1)):
        return "falling"
    else:
        # Net direction over window
        pct_change = (recent[-1] - recent[0]) / abs(recent[0]) * 100 if recent[0] != 0 else 0
        if abs(pct_change) < 0.5:
            return "stable"
        return "rising" if pct_change > 0 else "falling"
```

---

## Tool 2: `get_sector_overview`

### Function Signature

```python
def get_sector_overview(
    date: Optional[str] = None,
    sector: Optional[str] = None,
    include_portfolio: bool = False,
    user_email: Optional[str] = None,
    format: Literal["full", "summary"] = "summary",
    use_cache: bool = True,
) -> dict:
```

### Parameters

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `date` | `str` (optional) | `None` | Snapshot date (YYYY-MM-DD). Defaults to latest available |
| `sector` | `str` (optional) | `None` | Filter to one sector (e.g., "Technology", "Energy") |
| `include_portfolio` | `bool` | `False` | Overlay portfolio sector weights from positions |
| `user_email` | `str` (optional) | `None` | User for portfolio overlay (uses env var default) |
| `format` | `"full"` or `"summary"` | `"summary"` | Output level |
| `use_cache` | `bool` | `True` | Use cached data |

### Data Flow

```
1. Fetch sector performance: FMPClient.fetch("sector_performance_snapshot", date=date)
   -> DataFrame with: sector, changesPercentage
2. Fetch sector P/E: FMPClient.fetch("sector_pe_snapshot", date=date)
   -> DataFrame with: sector, pe
3. Merge performance + P/E on sector name
4. If sector is specified, filter to that sector only
5. If include_portfolio=True:
   a. Load positions via PositionService (same pattern as _load_portfolio_weights in factor_intelligence.py)
   b. Look up sector for each position via FMP profile (cached) or position data
   c. Compute portfolio weight per sector
   d. Add portfolio_weight column to merged data
6. Sort by changesPercentage descending
7. Format as summary or full
```

### Portfolio Sector Mapping

The sector overlay needs to map each position ticker to its GICS sector. Two approaches, in priority order:

1. **Position data**: Some positions already have a `sector` field from the brokerage data
2. **FMP profile**: For positions without sector data, use `FMPClient.fetch("profile", symbol=ticker)` which includes `sector` field. This is already cached with 168-hour TTL.

```python
def _get_portfolio_sector_weights(user_email: Optional[str], use_cache: bool) -> dict[str, float]:
    """
    Compute portfolio weight per GICS sector from live positions.
    Returns: {"Technology": 0.35, "Healthcare": 0.20, ...}
    """
    from services.position_service import PositionService
    from settings import get_default_user
    from fmp.client import get_client

    user = user_email or get_default_user()
    if not user:
        raise ValueError("No user specified and RISK_MODULE_USER_EMAIL not configured")

    position_service = PositionService(user)
    result = position_service.get_all_positions(use_cache=use_cache, consolidate=True)
    positions = result.data.positions

    # Filter out cash
    equity_positions = [p for p in positions if p.get("type") != "cash" and not p["ticker"].startswith("CUR:")]
    total_value = sum(abs(float(p.get("value", 0))) for p in equity_positions)
    if total_value <= 0:
        return {}

    fmp = get_client()
    sector_weights = {}
    for p in equity_positions:
        ticker = p["ticker"]
        weight = float(p.get("value", 0)) / total_value
        # Try position data first, then FMP profile
        sector = p.get("sector")
        if not sector:
            try:
                profile_df = fmp.fetch("profile", symbol=ticker, use_cache=True)
                if not profile_df.empty:
                    sector = profile_df.iloc[0].get("sector", "Unknown")
            except Exception:
                sector = "Unknown"
        sector = sector or "Unknown"
        sector_weights[sector] = sector_weights.get(sector, 0) + weight

    return sector_weights
```

### Output Structures

#### Summary

```python
{
    "status": "success",
    "date": "2026-02-07",
    "sectors": [
        {
            "sector": "Technology",
            "change_pct": 1.45,
            "pe_ratio": 32.1,
            "portfolio_weight": 0.35,   # Only when include_portfolio=True
        },
        {
            "sector": "Energy",
            "change_pct": -0.82,
            "pe_ratio": 14.2,
            "portfolio_weight": 0.05,
        },
        ...
    ],
    "best_sector": {"sector": "Technology", "change_pct": 1.45},
    "worst_sector": {"sector": "Utilities", "change_pct": -1.12},
    "sector_count": 11,
    "include_portfolio": true,
}
```

#### Full

```python
{
    "status": "success",
    "date": "2026-02-07",
    "performance": [...],       # Raw sector performance data
    "valuation": [...],         # Raw sector P/E data
    "portfolio_sectors": {...}, # Portfolio sector weights (when include_portfolio=True)
    "row_count": 11,
}
```

### Error Handling

- FMP errors: caught at tool boundary
- Empty performance or P/E data: return success with empty sectors list and a `note` field
- `include_portfolio=True` but no positions: return sector data without portfolio overlay, add `portfolio_note: "No positions found for overlay"`
- Invalid sector name in `sector` filter: return empty list with `note: "No data found for sector 'X'. Use get_sector_overview() without sector filter to see available sectors."`

---

## Tool 3: `get_market_context`

### Function Signature

```python
def get_market_context(
    date: Optional[str] = None,
    include_portfolio: bool = False,
    user_email: Optional[str] = None,
    format: Literal["full", "summary"] = "summary",
    use_cache: bool = True,
) -> dict:
```

### Parameters

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `date` | `str` (optional) | `None` | Context date. Defaults to today |
| `include_portfolio` | `bool` | `False` | Include portfolio holdings overlap with movers |
| `user_email` | `str` (optional) | `None` | User for portfolio overlap |
| `format` | `"full"` or `"summary"` | `"summary"` | Output level |
| `use_cache` | `bool` | `True` | Use cached data |

### Data Flow

```
1. Parallel FMP fetches (6 calls, all independent):
   a. batch_index_quotes -> major index levels and daily changes
   b. sector_performance_snapshot -> sector rotation heatmap
   c. economic_calendar (today to +7 days) -> upcoming events
   d. biggest_gainers -> top movers up
   e. biggest_losers -> top movers down
   f. most_actives -> highest volume names

2. If include_portfolio=True:
   a. Load portfolio tickers via PositionService
   b. Cross-reference gainers/losers/actives with portfolio holdings
   c. Flag any portfolio holdings that appear in mover lists

3. Assemble "morning briefing" summary
4. Format as summary or full
```

### Parallel Fetch Strategy

All 6 FMP calls are independent. Use a helper to fetch all in sequence (no threading needed at this layer -- the FMP client handles caching, and most calls will hit 1-hour TTL cache). The fetches are wrapped individually so a failure in one does not block others:

```python
def _safe_fetch(client, endpoint_name, **params):
    """Fetch from FMP, returning empty DataFrame on error."""
    try:
        return client.fetch(endpoint_name, **params)
    except Exception:
        return pd.DataFrame()
```

### Portfolio Holdings Overlap

When `include_portfolio=True`, check if any portfolio ticker appears in the gainers, losers, or most-active lists. This uses a simple set intersection -- no expensive computation needed.

```python
def _find_portfolio_movers(portfolio_tickers: set[str], gainers: list, losers: list, actives: list) -> dict:
    """Find portfolio holdings that appear in today's mover lists."""
    result = {"in_gainers": [], "in_losers": [], "in_actives": []}
    for g in gainers:
        if g.get("symbol") in portfolio_tickers:
            result["in_gainers"].append(g)
    for l in losers:
        if l.get("symbol") in portfolio_tickers:
            result["in_losers"].append(l)
    for a in actives:
        if a.get("symbol") in portfolio_tickers:
            result["in_actives"].append(a)
    return result
```

### Output Structures

#### Summary

```python
{
    "status": "success",
    "date": "2026-02-07",
    "indices": [
        {"symbol": "^GSPC", "name": "S&P 500", "price": 6025.50, "change_pct": 0.35},
        {"symbol": "^DJI", "name": "Dow Jones", "price": 44850.12, "change_pct": 0.18},
        {"symbol": "^IXIC", "name": "Nasdaq", "price": 19280.44, "change_pct": 0.52},
        {"symbol": "^RUT", "name": "Russell 2000", "price": 2285.10, "change_pct": -0.15},
    ],
    "sector_heatmap": [                # Top 3 + bottom 3 sectors by change
        {"sector": "Technology", "change_pct": 1.45},
        {"sector": "Consumer Discretionary", "change_pct": 0.92},
        {"sector": "Healthcare", "change_pct": 0.55},
        ...
        {"sector": "Utilities", "change_pct": -1.12},
    ],
    "top_gainers": [                   # Top 5 gainers
        {"symbol": "XYZ", "name": "XYZ Corp", "change_pct": 15.2, "price": 45.30},
        ...
    ],
    "top_losers": [                    # Top 5 losers
        {"symbol": "ABC", "name": "ABC Inc", "change_pct": -12.5, "price": 22.10},
        ...
    ],
    "most_active": [                   # Top 5 by volume
        {"symbol": "AAPL", "name": "Apple Inc", "volume": 85000000, "change_pct": 0.8},
        ...
    ],
    "upcoming_events": [               # Next 3 high-impact economic events
        {"event": "CPI", "date": "2026-02-12", "estimate": 3.1, "impact": "High"},
        ...
    ],
    "portfolio_movers": {              # Only when include_portfolio=True
        "in_gainers": [{"symbol": "NVDA", "change_pct": 4.2}],
        "in_losers": [],
        "in_actives": [{"symbol": "AAPL", "volume": 85000000}],
    },
}
```

#### Full

```python
{
    "status": "success",
    "date": "2026-02-07",
    "indices": [...],                  # Complete index quotes
    "sector_performance": [...],       # All sectors with full data
    "economic_calendar": [...],        # All upcoming events
    "gainers": [...],                  # Full gainers list
    "losers": [...],                   # Full losers list
    "most_active": [...],              # Full actives list
    "portfolio_movers": {...},         # When include_portfolio=True
}
```

### Error Handling

- Individual FMP endpoint failures: logged but do not fail the tool. Missing sections are returned as empty lists with a `warnings` array noting which data sources failed
- All FMP calls fail: return `{"status": "error", "error": "Unable to fetch market data. Check FMP API key and connectivity."}`
- `include_portfolio=True` but positions fail: return market data without portfolio overlay, add `portfolio_note`
- Graceful degradation pattern:

```python
warnings = []
if indices_df.empty:
    warnings.append("Index quotes unavailable")
if sector_df.empty:
    warnings.append("Sector performance unavailable")
# ... etc.

# Only error if ALL sources failed
if all sources empty:
    return {"status": "error", "error": "..."}

response = {...}
if warnings:
    response["warnings"] = warnings
return response
```

---

## mcp_server.py Registration

Three new `@mcp.tool()` wrappers following the existing pattern. The `user_email` param is hidden from MCP (uses env var).

```python
from mcp_tools.market import get_economic_data as _get_economic_data
from mcp_tools.market import get_sector_overview as _get_sector_overview
from mcp_tools.market import get_market_context as _get_market_context


@mcp.tool()
def get_economic_data(
    mode: Literal["indicator", "calendar"] = "indicator",
    indicator_name: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    format: Literal["full", "summary"] = "summary",
    use_cache: bool = True,
) -> dict:
    """
    Get economic indicators or upcoming economic events.

    Fetches macroeconomic data from FRED via FMP. Use indicator mode for
    time series data (GDP, CPI, unemployment, etc.) or calendar mode for
    upcoming/recent economic releases.

    Args:
        mode: Data type to fetch:
            - "indicator": Economic indicator time series (requires indicator_name)
            - "calendar": Upcoming economic events with forecasts and actuals
        indicator_name: Indicator to fetch (required for indicator mode).
            Available: GDP, realGDP, CPI, inflationRate, federalFunds,
            unemploymentRate, totalNonfarmPayroll, initialClaims,
            consumerSentiment, retailSales, durableGoods,
            industrialProductionTotalIndex, housingStarts, totalVehicleSales,
            smoothedUSRecessionProbabilities, 30YearFixedRateMortgageAverage,
            tradeBalanceGoodsAndServices.
        from_date: Start date in YYYY-MM-DD format (optional).
        to_date: End date in YYYY-MM-DD format (optional).
        format: Output format:
            - "summary": Latest value, trend, and key context
            - "full": Complete time series or event list
        use_cache: Use cached data when available (default: True).

    Returns:
        Economic data with status field ("success" or "error").

    Examples:
        "What's the latest GDP?" -> get_economic_data(indicator_name="GDP")
        "Show me CPI trend" -> get_economic_data(indicator_name="CPI")
        "What's the fed funds rate?" -> get_economic_data(indicator_name="federalFunds")
        "Upcoming economic events" -> get_economic_data(mode="calendar")
        "Economic calendar this week" -> get_economic_data(mode="calendar")
    """
    return _get_economic_data(
        mode=mode,
        indicator_name=indicator_name,
        from_date=from_date,
        to_date=to_date,
        format=format,
        use_cache=use_cache,
    )


@mcp.tool()
def get_sector_overview(
    date: Optional[str] = None,
    sector: Optional[str] = None,
    include_portfolio: bool = False,
    format: Literal["full", "summary"] = "summary",
    use_cache: bool = True,
) -> dict:
    """
    Get sector performance and valuation overview with optional portfolio overlay.

    Combines sector daily performance and P/E ratios into a heatmap view.
    Optionally overlays your portfolio's sector allocation for context.

    Args:
        date: Snapshot date in YYYY-MM-DD format (optional, defaults to latest).
        sector: Filter to one sector (e.g., "Technology", "Energy", "Healthcare").
            If not provided, returns all sectors.
        include_portfolio: Overlay portfolio sector weights from brokerage
            positions (default: False).
        format: Output format:
            - "summary": Sector heatmap with performance + valuation
            - "full": Complete raw data from all endpoints
        use_cache: Use cached data when available (default: True).

    Returns:
        Sector overview with status field ("success" or "error").

    Examples:
        "How are sectors performing?" -> get_sector_overview()
        "Technology sector overview" -> get_sector_overview(sector="Technology")
        "Sector performance vs my portfolio" -> get_sector_overview(include_portfolio=True)
        "Which sectors are cheapest?" -> get_sector_overview()
    """
    return _get_sector_overview(
        date=date,
        sector=sector,
        include_portfolio=include_portfolio,
        user_email=None,  # Uses RISK_MODULE_USER_EMAIL from env
        format=format,
        use_cache=use_cache,
    )


@mcp.tool()
def get_market_context(
    date: Optional[str] = None,
    include_portfolio: bool = False,
    format: Literal["full", "summary"] = "summary",
    use_cache: bool = True,
) -> dict:
    """
    Get a morning-briefing-style market overview.

    Combines index levels, sector rotation, market movers, and upcoming
    economic events into a single contextual view. Optionally highlights
    portfolio holdings that appear in today's mover lists.

    Args:
        date: Context date in YYYY-MM-DD format (optional, defaults to today).
        include_portfolio: Check if portfolio holdings appear in gainers,
            losers, or most-active lists (default: False).
        format: Output format:
            - "summary": Concise market narrative with key numbers
            - "full": Complete data from all sources
        use_cache: Use cached data when available (default: True).

    Returns:
        Market context with status field ("success" or "error").

    Examples:
        "What's happening in the market today?" -> get_market_context()
        "Morning market briefing" -> get_market_context()
        "Market overview with my holdings" -> get_market_context(include_portfolio=True)
        "Are any of my stocks big movers today?" -> get_market_context(include_portfolio=True)
    """
    return _get_market_context(
        date=date,
        include_portfolio=include_portfolio,
        user_email=None,  # Uses RISK_MODULE_USER_EMAIL from env
        format=format,
        use_cache=use_cache,
    )
```

---

## mcp_tools/__init__.py Update

```python
# Add to imports:
from mcp_tools.market import get_economic_data, get_sector_overview, get_market_context

# Add to __all__:
__all__ = [
    # ... existing ...
    "get_economic_data",
    "get_sector_overview",
    "get_market_context",
]
```

---

## Shared Helpers in `mcp_tools/market.py`

The module will contain these private helpers used across all three tools:

```python
VALID_INDICATORS = [
    "GDP", "realGDP", "CPI", "inflationRate", "federalFunds",
    "unemploymentRate", "totalNonfarmPayroll", "initialClaims",
    "consumerSentiment", "retailSales", "durableGoods",
    "industrialProductionTotalIndex", "housingStarts",
    "totalVehicleSales", "smoothedUSRecessionProbabilities",
    "30YearFixedRateMortgageAverage", "tradeBalanceGoodsAndServices",
]


def _default_date_range(from_date, to_date, default_lookback_days=730, default_forward_days=0):
    """Apply default date range if not specified."""
    from datetime import date, timedelta
    today = date.today()
    if from_date is None:
        from_date = (today - timedelta(days=default_lookback_days)).isoformat()
    if to_date is None:
        to_date = (today + timedelta(days=default_forward_days)).isoformat()
    return from_date, to_date


def _safe_fetch(client, endpoint_name, use_cache=True, **params):
    """Fetch from FMP, returning empty DataFrame on error."""
    import pandas as pd
    try:
        return client.fetch(endpoint_name, use_cache=use_cache, **params)
    except Exception:
        return pd.DataFrame()


def _compute_trend(values, window=3):
    """Determine trend direction from recent values."""
    # See implementation in Tool 1 section above
    ...


def _get_portfolio_sector_weights(user_email, use_cache):
    """Compute portfolio weight per GICS sector from live positions."""
    # See implementation in Tool 2 section above
    ...


def _get_portfolio_tickers(user_email, use_cache):
    """Get set of portfolio tickers for mover overlap check."""
    from services.position_service import PositionService
    from settings import get_default_user

    user = user_email or get_default_user()
    if not user:
        return set()
    try:
        service = PositionService(user)
        result = service.get_all_positions(use_cache=use_cache, consolidate=True)
        return {
            p["ticker"] for p in result.data.positions
            if p.get("type") != "cash" and not p["ticker"].startswith("CUR:")
        }
    except Exception:
        return set()
```

---

## stdout Redirection

All three tools follow the established MCP pattern of redirecting stdout to stderr during execution to protect the MCP JSON-RPC channel:

```python
def get_economic_data(...) -> dict:
    _saved = sys.stdout
    sys.stdout = sys.stderr
    try:
        # ... tool logic ...
    except Exception as e:
        return {"status": "error", "error": str(e)}
    finally:
        sys.stdout = _saved
```

---

## Implementation Order

### Phase 1: FMP Endpoint Registration (~30 min)
1. Register all 10 endpoints in `fmp/registry.py`
2. Verify with `FMPClient().list_endpoints(category="macro")` etc.
3. Quick smoke test: `FMPClient().fetch("economic_indicators", name="GDP")`

### Phase 2: `get_economic_data` (~1 hour)
1. Implement in `mcp_tools/market.py` with shared helpers
2. Register in `mcp_server.py`
3. Test indicator mode (GDP, CPI, federalFunds)
4. Test calendar mode
5. Test error cases (missing indicator_name, invalid name, >90 day range)

### Phase 3: `get_sector_overview` (~1.5 hours)
1. Implement sector fetch + merge logic
2. Implement `_get_portfolio_sector_weights()` helper
3. Register in `mcp_server.py`
4. Test without portfolio overlay
5. Test with portfolio overlay
6. Test sector filter
7. Test empty/missing data paths

### Phase 4: `get_market_context` (~1.5 hours)
1. Implement 6-source parallel fetch with `_safe_fetch`
2. Implement portfolio mover overlap
3. Register in `mcp_server.py`
4. Test full summary output
5. Test with portfolio overlay
6. Test graceful degradation (simulate endpoint failures)

### Phase 5: Integration (~30 min)
1. Update `mcp_tools/__init__.py`
2. Update `mcp_tools/README.md` with tool documentation
3. Restart Claude Code and verify all 12 tools appear
4. End-to-end test each tool via MCP

**Total estimated time: ~5 hours**

---

## Design Decisions

### 1. No `"report"` format (only `"summary"` and `"full"`)

Unlike portfolio tools that have rich result objects with `to_formatted_report()`, these market data tools return relatively flat data structures. A formatted report adds complexity without much value -- the LLM can format the summary data into natural language directly. If report format is needed later, it can be added without breaking changes.

### 2. Single file for all three tools

All three tools share: FMP client usage, date defaulting logic, portfolio position loading, safe-fetch patterns. Splitting into three files would create unnecessary import complexity for ~850 total lines.

### 3. `_safe_fetch` pattern for `get_market_context`

Market context combines 6 independent data sources. Failing one (e.g., biggest_gainers) should not block the others. The `_safe_fetch` wrapper returns an empty DataFrame on error, and the tool reports which sources were unavailable via a `warnings` array.

### 4. Portfolio overlay is opt-in (`include_portfolio=False` default)

Portfolio loading adds latency (PositionService + potential profile lookups). Most market context queries do not need portfolio overlay, so it defaults to off. This also means the tools work without any brokerage connection.

### 5. FMP endpoint caching strategy

- **Economic indicators**: TTL 24h (data updates monthly/quarterly, daily refresh is fine)
- **Economic calendar**: TTL 6h (actuals get filled in throughout the day)
- **Sector snapshots**: TTL 1h (intraday changes during market hours)
- **Market movers**: TTL 1h (changes throughout trading day)
- **Historical sector data**: HASH_ONLY (immutable for given date range)

### 6. No new service layer

These tools fetch directly from `FMPClient` and do lightweight formatting. There is no complex business logic that warrants a separate service class (unlike risk analysis which has `PortfolioService`). If analysis logic grows (e.g., computing cross-sector momentum signals), a service can be extracted later.

---

## Testing Strategy

### Unit Tests (future, not part of initial implementation)

- `_compute_trend()` with rising/falling/stable/edge cases
- `_default_date_range()` with various None combinations
- `_safe_fetch()` with simulated exceptions

### Manual Smoke Tests

```python
# Quick test after implementation
from mcp_tools.market import get_economic_data, get_sector_overview, get_market_context

# Economic data
print(get_economic_data(indicator_name="GDP"))
print(get_economic_data(indicator_name="CPI", format="full"))
print(get_economic_data(mode="calendar"))
print(get_economic_data(mode="indicator"))  # Should error: missing indicator_name

# Sector overview
print(get_sector_overview())
print(get_sector_overview(sector="Technology"))
print(get_sector_overview(include_portfolio=True))

# Market context
print(get_market_context())
print(get_market_context(include_portfolio=True))
print(get_market_context(format="full"))
```

---

## Memory Update (after implementation)

Add to `MEMORY.md`:

```markdown
## Completed: Macro & Market Context MCP Tools
Three MCP tools (`get_economic_data`, `get_sector_overview`, `get_market_context`) on `portfolio-mcp` server.
- `get_economic_data` — wraps `economic-indicators` + `economic-calendar` via `mode` param
- `get_sector_overview` — combines sector performance + P/E + optional portfolio sector overlay
- `get_market_context` — "morning briefing": indices + sectors + movers + calendar + portfolio overlap
- 10 new FMP endpoints registered (2 macro, 4 sector, 4 market_movers)
- Stateless: uses FMPClient directly, no service layer
- Portfolio overlay opt-in (include_portfolio=False default)
- Graceful degradation: _safe_fetch returns empty DataFrame, warnings array for missing sources
- Files: `mcp_tools/market.py`, `fmp/registry.py`, `mcp_server.py`, `mcp_tools/__init__.py`
- Plan: `docs/planning/MACRO_MARKET_MCP_PLAN.md`
```

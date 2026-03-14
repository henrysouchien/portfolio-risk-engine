# `get_market_context` MCP Tool -- Implementation Plan

## Current State

The original MACRO_MARKET_MCP_PLAN.md (now in `docs/planning/completed/`) described three tools: `get_economic_data`, `get_sector_overview`, and `get_market_context`. The first two were implemented and shipped. The third (`get_market_context`) was deferred to the backlog as a Tier 3 tool.

Key differences from the original plan:
- `get_sector_overview` was implemented without `include_portfolio` (moved to pure FMP data, no portfolio context). It uses a `level` parameter instead.
- `get_sector_overview` is registered on `fmp-mcp`, not `portfolio-mcp`.
- The 4 market mover endpoints (biggest_gainers, biggest_losers, most_actives, batch_index_quotes) were never registered in `fmp/registry.py`.

## Overview

`get_market_context` is a thin orchestration tool that combines 6 independent FMP fetches into a single "morning briefing" snapshot. It answers "what's happening in the market?" in one call instead of 3-5 separate tool calls.

**Sections returned:**
1. **Indices** -- S&P 500, DJIA, Nasdaq, Russell 2000 price + daily change
2. **Sector heatmap** -- All 11 GICS sectors sorted by daily change
3. **Top gainers** -- Top 5 stocks by percentage gain today
4. **Top losers** -- Top 5 stocks by percentage loss today
5. **Most active** -- Top 5 stocks by trading volume today
6. **Upcoming events** -- Next 3-5 high-impact economic events

**Estimated lines of code:** ~250-300 (tool function + formatting helpers)

## Design Decisions

### 1. Server placement: fmp-mcp (NOT portfolio-mcp)

The original plan placed this on `portfolio-mcp` to support `include_portfolio` (cross-referencing movers against holdings). However:
- `get_sector_overview` was ultimately placed on `fmp-mcp` without portfolio overlay
- Keeping it on `fmp-mcp` avoids cross-server coupling and keeps the tool stateless
- The agent can naturally chain `get_market_context()` + `get_positions(format="list")` if it wants portfolio overlap
- This is consistent with how `get_news` and `get_events_calendar` were placed on `fmp-mcp` without portfolio auto-fill

**Decision: Register on `fmp-mcp` server. No `include_portfolio` parameter. No user context required.**

### 2. No new file -- add to existing `mcp_tools/market.py`

The `mcp_tools/market.py` file already contains `get_economic_data`, `get_sector_overview`, and the shared `_safe_fetch` helper. Adding `get_market_context` here follows the domain grouping pattern and reuses `_safe_fetch` directly.

### 3. Use `client.fetch()` for all endpoints (caching support)

**[Codex review fix]** `FMPClient.fetch_raw()` has no caching support. All endpoints must use `client.fetch(..., use_cache=use_cache)` which returns DataFrames, then convert to dicts via `.to_dict("records")`. This ensures the `use_cache` parameter is respected for movers/indices/events. Sector data already uses `_safe_fetch` (which wraps `client.fetch`).

### 4. Index quotes via `batch_index_quotes`

Use `batch_index_quotes` endpoint which returns all index quotes in a single call. Filter client-side to the 4 tracked indices (^GSPC, ^DJI, ^IXIC, ^RUT).

**[Codex review fix]** Deferred `batch_quote` endpoint — not used by this tool. Will register it when an actual consumer needs it.

### 5. `include` parameter for section filtering

Following the pattern from `get_risk_analysis`, add an optional `include` parameter to let the agent request only specific sections. Available sections: `indices`, `sectors`, `gainers`, `losers`, `actives`, `events`. Default (None) returns all sections.

### 6. Graceful degradation with structured source status

**[Codex review fix]** Each data source returns a structured result `{ok: bool, data: list, error: str|None}` instead of bare lists. This distinguishes "endpoint failed" from "valid empty response" (e.g., no upcoming events is normal, not an error).

- `source_status` dict in output reports per-section fetch outcome
- "All sources failed" only triggers when ALL *requested* sections have `ok=False` (actual fetch failures), not when filtered data is empty
- Each section includes `count` field for LLM trust assessment

## FMP Endpoint Registrations (4 new endpoints)

All in `fmp/registry.py`. The stable API paths are:

| # | Name | Path | Category | Cache | Params | Description |
|---|------|------|----------|-------|--------|-------------|
| 1 | `biggest_gainers` | `/biggest-gainers` | `market_movers` | TTL 1h | none | Top gaining stocks |
| 2 | `biggest_losers` | `/biggest-losers` | `market_movers` | TTL 1h | none | Top losing stocks |
| 3 | `most_actives` | `/most-actives` | `market_movers` | TTL 1h | none | Most actively traded |
| 4 | `batch_index_quotes` | `/batch-index-quotes` | `quotes` | TTL 1h | `short` (bool, optional — verify in Phase 1) | All index quotes |

**[Codex review fix]** Removed `batch_quote` (not used by this tool — defer to future need). 4 endpoints total.
**[Codex R2 fix]** `short` param default not forced until Phase 1 smoke test verifies which fields are included/excluded.

## Tool Function Signature

```python
def get_market_context(
    include: Optional[list[str]] = None,
    format: Literal["full", "summary"] = "summary",
    use_cache: bool = True,
) -> dict:
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `include` | `Optional[list[str]]` | `None` | Sections to include. Default (None) = all. Options: `indices`, `sectors`, `gainers`, `losers`, `actives`, `events` |
| `format` | `Literal["full", "summary"]` | `"summary"` | Summary = curated top items per section. Full = complete data from all sources |
| `use_cache` | `bool` | `True` | Use TTL-cached data |

### Section Definitions

**[Codex review fix]** Include names and response keys are now 1:1 to reduce LLM confusion:

```python
# Include param values = response dict keys (1:1 mapping)
MARKET_CONTEXT_SECTIONS = ["indices", "sectors", "gainers", "losers", "actives", "events"]
```

## Data Flow

```
1. Determine which sections to fetch (based on include param)

2. Fetch each section independently (all via client.fetch for caching):
   a. indices: _safe_fetch_records("batch_index_quotes") -> filter to 4 major indices
   b. sectors: _safe_fetch_records("sector_performance_snapshot") -> NO hardcoded date (API returns latest)
   c. gainers: _safe_fetch_records("biggest_gainers") -> summary: top 5; full: all
   d. losers: _safe_fetch_records("biggest_losers") -> summary: top 5; full: all
   e. actives: _safe_fetch_records("most_actives") -> summary: top 5; full: all
   f. events: _safe_fetch_records("economic_calendar", from_date=today, to_date=today+7) -> summary: filter high-impact + top 5; full: all events in window

3. Track warnings for any failed fetches

4. Assemble response dict based on format

5. Return {status: "success", date: today, ...sections..., warnings: [...]}
```

## Output Structures

### Summary Format

```python
{
    "status": "success",
    "date": "2026-02-07",
    "generated_at": "2026-02-07T14:30:00",
    "indices": [
        {"symbol": "^GSPC", "name": "S&P 500", "price": 6025.50, "change_pct": 0.35},
        {"symbol": "^DJI", "name": "Dow Jones", "price": 44850.12, "change_pct": 0.18},
        {"symbol": "^IXIC", "name": "Nasdaq", "price": 19280.44, "change_pct": 0.52},
        {"symbol": "^RUT", "name": "Russell 2000", "price": 2285.10, "change_pct": -0.15},
    ],
    "sectors": [
        {"sector": "Technology", "change_pct": 1.45},
        {"sector": "Consumer Discretionary", "change_pct": 0.92},
        # ... all 11 sectors sorted by change_pct descending
        {"sector": "Utilities", "change_pct": -1.12},
    ],
    "gainers": [
        {"symbol": "XYZ", "name": "XYZ Corp", "change_pct": 15.2, "price": 45.30},
        # ... top 5
    ],
    "losers": [
        {"symbol": "ABC", "name": "ABC Inc", "change_pct": -12.5, "price": 22.10},
        # ... top 5
    ],
    "actives": [
        {"symbol": "AAPL", "name": "Apple Inc", "volume": 85000000, "change_pct": 0.8},
        # ... top 5
    ],
    "events": [
        {"event": "CPI", "date": "2026-02-12", "estimate": 3.1, "impact": "High"},
        # ... next 5 high-impact events
    ],
    "source_status": {
        "indices": {"ok": true, "count": 4},
        "sectors": {"ok": true, "count": 11},
        "gainers": {"ok": true, "count": 5},
        "losers": {"ok": true, "count": 5},
        "actives": {"ok": true, "count": 5},
        "events": {"ok": true, "count": 3},
    },
    "requested_sections": ["indices", "sectors", "gainers", "losers", "actives", "events"],
    "warnings": [],
}
```

### Full Format

**[Codex R2 fix]** Full format uses the same normalized field names as summary (not raw API payloads). The only difference is no `limit` applied — all items returned per section. This keeps the contract consistent and predictable for LLM consumers.

**[Codex R2 fix]** Per-section `as_of` timestamp added where available from the API payload (e.g., index quote timestamp). Top-level `generated_at` added for cache staleness detection.

## Internal Helpers

### `_safe_fetch_records`

**[Codex review fix]** Replaced `_safe_fetch_raw` with `_safe_fetch_records` that uses `client.fetch()` (cached) and returns structured result:

```python
from fmp.exceptions import FMPEmptyResponseError

def _safe_fetch_records(client, endpoint_name, use_cache=True, **params):
    """Fetch from FMP via client.fetch (cached), return structured result.

    [Codex review R2 fix] Explicitly catches FMPEmptyResponseError as valid
    empty (ok=True), not a failure. This is critical for sections like events
    where empty is a normal state.

    Returns:
        {"ok": bool, "data": list[dict], "error": str|None}
    """
    try:
        df = client.fetch(endpoint_name, use_cache=use_cache, **params)
        if df is not None and not df.empty:
            return {"ok": True, "data": df.to_dict("records"), "error": None}
        return {"ok": True, "data": [], "error": None}  # Valid empty
    except FMPEmptyResponseError:
        return {"ok": True, "data": [], "error": None}  # Valid empty from API
    except Exception as e:
        return {"ok": False, "data": [], "error": str(e)}
```

### Field Normalization

**[Codex review fix]** FMP field names vary across endpoints. Define explicit fallback mappings:

```python
def _safe_float(val, default=None):
    """Parse numeric value with fallback."""
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default

def _get_change_pct(record):
    """Extract change percentage from FMP record (field name varies)."""
    for key in ["changesPercentage", "changePercentage", "averageChange"]:
        val = _safe_float(record.get(key))
        if val is not None:
            return val
    return None
```

### Index Name Mapping

```python
_INDEX_NAMES = {
    "^GSPC": "S&P 500",
    "^DJI": "Dow Jones",
    "^IXIC": "Nasdaq",
    "^RUT": "Russell 2000",
}
```

## Error Handling

**[Codex review fix]** Structured per-source error tracking:

- **Per-source failure:** Each `_safe_fetch_records` call returns `{ok, data, error}`. Failures set `source_status[section].ok = False` and add to `warnings` list with section name and error message.
- **All-sources failure:** Only triggers when ALL *requested* sections have `ok=False` (actual fetch failures). Empty data with `ok=True` (e.g., no upcoming events) is NOT a failure.
- **Section filtering:** Invalid section names in `include` are reported in `invalid_sections` list. **[Codex R2 fix]** If ALL requested sections are invalid, return `status: "error"` with message listing valid section names.
- **Outer try/except:** The entire tool function is wrapped in try/except with stdout redirection.

## Files to Modify

| File | Change |
|------|--------|
| `fmp/registry.py` | Register 4 new endpoints (3 market_movers, 1 quotes) |
| `mcp_tools/market.py` | Add `get_market_context()` function + helpers (~250-300 LoC) |
| `fmp_mcp_server.py` | Add `@mcp.tool()` wrapper for `get_market_context` |
| `mcp_tools/__init__.py` | Add `get_market_context` to imports and `__all__` |
| `mcp_tools/README.md` | Document `get_market_context` tool |

No new files needed.

## Implementation Order

### Phase 1: FMP Endpoint Registration
1. Register 4 new endpoints in `fmp/registry.py` (biggest_gainers, biggest_losers, most_actives, batch_index_quotes)
2. Smoke test: `FMPClient().fetch("biggest_gainers")` and `FMPClient().fetch("batch_index_quotes")`
3. Verify the response structure — document actual field names for `changesPercentage` vs `changePercentage` etc.
4. Test sector endpoint with no date param (should return latest, handling weekends/holidays)

### Phase 2: Tool Implementation
1. Add `_safe_fetch_records`, `_safe_float`, `_get_change_pct`, `_INDEX_NAMES`, constants to `mcp_tools/market.py`
2. Add summary formatter helpers
3. Implement `get_market_context()` main function
4. Test each section independently
5. Test `include` filtering
6. Test graceful degradation

### Phase 3: Server Registration
1. Add import + `@mcp.tool()` wrapper to `fmp_mcp_server.py`
2. Update `mcp_tools/__init__.py` with new export
3. Update `mcp_tools/README.md` with tool documentation
4. Update fmp-mcp server instructions string

### Phase 4: End-to-end Testing
1. Test via MCP: "What's happening in the market?"
2. Test section filtering: "Just show me indices and gainers"
3. Test full format
4. Verify response size is reasonable for LLM context

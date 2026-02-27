# FMP MCP Server Implementation Plan

## Goal

Create an MCP server that wraps the existing FMP package, allowing Claude to directly call financial data endpoints without writing/executing Python scripts.

| Workflow | Steps |
|----------|-------|
| **Current** | Agent reads docs → writes Python script → executes → parses output |
| **New (MCP)** | Agent calls `mcp__fmp__fetch(endpoint="income_statement", symbol="AAPL")` → gets data |

---

## Design Decisions

### 1. Tool Design: Hybrid Approach (5 tools)

| Tool | Purpose |
|------|---------|
| `fmp_fetch` | Generic fetch for any of the 16 registered endpoints |
| `fmp_search` | Convenience wrapper for company search |
| `fmp_profile` | Convenience wrapper for company profile |
| `fmp_list_endpoints` | Discovery: list available endpoints |
| `fmp_describe` | Discovery: get endpoint parameter details |

**Rationale:** 16 individual tools would clutter the tool list. A single generic `fmp_fetch` + discovery tools + 2 common convenience tools is cleaner.

### 2. Return Format: Records with Metadata

```python
{
    "status": "success",
    "endpoint": "income_statement",
    "params": {"symbol": "AAPL", "period": "annual"},
    "row_count": 3,
    "columns": ["date", "revenue", "netIncome", ...],
    "data": [{"date": "2024-09-28", "revenue": 383285000000, ...}, ...]
}
```

### 3. Error Handling: Structured Responses (never throw)

```python
{
    "status": "error",
    "error_type": "rate_limit",  # validation, api, auth, empty_data, unknown_endpoint
    "message": "FMP API rate limit exceeded",
    "endpoint": "income_statement",
    "params": {...}
}
```

### 4. Caching

Use FMP's existing caching by default (HASH_ONLY, MONTHLY, TTL strategies). Add optional `use_cache=False` parameter for fresh data.

---

## Files to Create

### 1. `mcp_tools/fmp.py` — Tool implementations

Core functions that wrap `fmp.fetch()` and return structured dicts:

```python
def fmp_fetch(endpoint, symbol=None, period=None, limit=None, ...) -> dict:
    """Generic fetch for any endpoint."""

def fmp_search(query, limit=10) -> dict:
    """Search for companies."""

def fmp_profile(symbol) -> dict:
    """Get company profile."""

def fmp_list_endpoints(category=None) -> dict:
    """List available endpoints."""

def fmp_describe(endpoint) -> dict:
    """Get endpoint documentation."""
```

### 2. `fmp_mcp_server.py` — MCP server entry point

Following the existing `mcp_server.py` pattern:

```python
#!/usr/bin/env python3
import sys
_real_stdout = sys.stdout
sys.stdout = sys.stderr

from fastmcp import FastMCP
from mcp_tools.fmp import (
    fmp_fetch as _fmp_fetch,
    fmp_search as _fmp_search,
    ...
)

sys.stdout = _real_stdout

mcp = FastMCP("fmp-mcp", instructions="...")

@mcp.tool()
def fmp_fetch(...) -> dict:
    """..."""
    return _fmp_fetch(...)

# ... other tools

if __name__ == "__main__":
    mcp.run()
```

---

## Implementation Steps

1. **Create `mcp_tools/fmp.py`** — tool implementations with error handling
2. **Create `fmp_mcp_server.py`** — FastMCP server with `@mcp.tool()` decorators
3. **Register with Claude:** `claude mcp add fmp-mcp -- python3 fmp_mcp_server.py`
4. **Test with Claude**

---

## Verification

After implementation, test these queries in Claude:

| Test | Expected Tool Call |
|------|-------------------|
| "What FMP endpoints are available?" | `fmp_list_endpoints()` |
| "How do I use the income_statement endpoint?" | `fmp_describe(endpoint="income_statement")` |
| "Get Apple's income statement for the last 3 years" | `fmp_fetch(endpoint="income_statement", symbol="AAPL", limit=3)` |
| "Search for semiconductor companies" | `fmp_search(query="semiconductor")` |
| "Get income statement for INVALIDTICKER" | Should return structured error |

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `mcp_server.py` | Existing portfolio-mcp (pattern to follow) |
| `mcp_tools/positions.py` | Existing tool implementation (pattern to follow) |
| `fmp/client.py` | `FMPClient.fetch()` to wrap |
| `fmp/registry.py` | Endpoint definitions for discovery tools |
| `fmp/exceptions.py` | Exceptions to map to error responses |

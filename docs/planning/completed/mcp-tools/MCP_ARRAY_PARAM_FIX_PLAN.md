# MCP Array Parameter Serialization Fix

## Context

Claude Code/Desktop serialize `list[T]` MCP tool parameters as JSON strings (e.g. `'[75.0, 80.0, 85.0]'` instead of `[75.0, 80.0, 85.0]`). Client-side schema validation rejects these before they reach the server, producing errors like:

```
Input validation error: '[75.0, 80.0, 85.0]' is not of type 'array'
```

FastMCP 2.1.2 has `pre_parse_json()` that would handle this server-side, but the validation happens at the MCP client layer before the request is sent.

**Triggered by**: `get_ibkr_option_prices(strikes=[75.0, 80.0, 85.0])` failing during live testing.

## Approach

Change all `list[T]` parameters in MCP tool signatures to `str`, and parse them in handlers using a shared `_parse_list()` helper. This is the same pattern already used by `get_portfolio_news`, `get_portfolio_events_calendar`, and `get_news` (comma-separated `str` instead of `list[str]`).

The helper accepts JSON array strings (`'[1,2,3]'`), comma-separated strings (`'1,2,3'`), or actual lists (passthrough).

## Affected Parameters (19 total across 3 servers)

### ibkr/server.py — 2 params
| Tool | Param | Current Type | New Type |
|------|-------|-------------|----------|
| `get_ibkr_market_data` | `symbols` | `list[str]` | `str` |
| `get_ibkr_option_prices` | `strikes` | `list[float]` | `str` |

### mcp_server.py — 11 params
| Tool | Param | Current Type | New Type |
|------|-------|-------------|----------|
| `get_risk_analysis` | `include` | `Optional[list[str]]` | `Optional[str]` |
| `update_action_status` | `linked_trade_ids` | `Optional[list[str]]` | `Optional[str]` |
| `analyze_option_strategy` | `legs` | `list[dict[str, Any]]` | `str` |
| `analyze_option_chain` | `strikes` | `Optional[list[float]]` | `Optional[str]` |
| `compare_scenarios` | `scenarios` | `Optional[list[dict]]` | `Optional[str]` |
| `get_factor_analysis` | `categories` | `Optional[list[str]]` | `Optional[str]` |
| `get_factor_analysis` | `windows` | `Optional[list[str]]` | `Optional[str]` |
| `get_factor_analysis` | `include` | `Optional[list[str]]` | `Optional[str]` |
| `create_basket` | `tickers` | `list[str]` | `str` |
| `update_basket` | `tickers` | `Optional[list[str]]` | `Optional[str]` |
| `execute_basket_trade` | `preview_ids` | `list[str]` | `str` |

### fmp/server.py — 6 params
| Tool | Param | Current Type | New Type |
|------|-------|-------------|----------|
| `fmp_fetch` | `columns` | `Optional[list[str]]` | `Optional[str]` |
| `screen_estimate_revisions` | `tickers` | `Optional[list[str]]` | `Optional[str]` |
| `get_sector_overview` | `symbols` | `Optional[list[str]]` | `Optional[str]` |
| `get_market_context` | `include` | `Optional[list[str]]` | `Optional[str]` |
| `get_etf_holdings` | `include` | `Optional[list[str]]` | `Optional[str]` |
| `get_technical_analysis` | `indicators` | `Optional[list[str]]` | `Optional[str]` |

### Special case: `legs` and `scenarios`

`analyze_option_strategy.legs` is `list[dict[str, Any]]` and `compare_scenarios.scenarios` is `Optional[list[dict]]` — these are complex nested structures. Same fix: accept `str`, `json.loads()` to get the list of dicts.

## Implementation

### Step 1: Add helpers to `mcp_tools/common.py`

Two helpers — `parse_list()` for scalar lists, `parse_json_list()` for complex (dict) lists:

```python
def parse_list(value: Any, *, coerce: type = str) -> list | None:
    """Parse a list param that MCP clients may send as a JSON string.

    Returns None when value is None or empty string (preserves "unset" semantics
    for optional params). Returns a non-empty list otherwise.
    Raises ValueError for non-list JSON input (e.g. a dict).
    """
    if value is None:
        return None
    if isinstance(value, list):
        return [coerce(v) for v in value]
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [coerce(v) for v in parsed]
        raise ValueError(f"Expected JSON array, got {type(parsed).__name__}")
    except json.JSONDecodeError:
        pass
    # Fallback: comma-separated
    return [coerce(v.strip()) for v in text.split(",") if v.strip()]


def parse_json_list(value: Any) -> list | None:
    """Parse a list-of-dicts param that MCP clients may send as a JSON string.

    Returns None when value is None/empty. No comma-split fallback (dicts can't
    be comma-separated).
    """
    if value is None:
        return None
    if isinstance(value, list):
        return value
    text = str(value).strip()
    if not text:
        return None
    parsed = json.loads(text)  # let JSONDecodeError propagate
    if not isinstance(parsed, list):
        raise ValueError(f"Expected JSON array, got {type(parsed).__name__}")
    return parsed
```

Key design decisions (addressing Codex R1 findings):
- **`None` passthrough**: `None` in → `None` out. Preserves "unset" semantics for optional params where `None` means "use defaults" and `[]` means "empty set". Callers use `parse_list(value) or []` when they want guaranteed list.
- **Strict non-list JSON rejection**: `json.loads('{"a":1}')` → `ValueError`, not silent one-element list.
- **No comma fallback for dicts**: `parse_json_list` only accepts JSON arrays or passthrough lists.

### Step 2: Copy helpers to `ibkr/server.py` and `fmp/server.py`

These are standalone server files (ibkr/ is a self-contained package, fmp/ syncs to PyPI). Copy the same helpers directly rather than creating cross-package imports. Both helpers are ~15 lines — small enough that duplication is acceptable.

### Step 3: Update MCP tool signatures + handler call sites

**Pattern for required params:**
```python
# Signature: strikes: str
# Handler:   parsed = parse_list(strikes, coerce=float) or []
#            if not parsed: raise ValueError("strikes required")
```

**Pattern for optional params (None = "use defaults"):**
```python
# Signature: include: Optional[str] = None
# Handler:   parsed_include = parse_list(include)  # None stays None
#            ... pass parsed_include to downstream handler
```

**Pattern for complex list params (legs, scenarios):**
```python
# Signature: legs: str
# Handler:   parsed_legs = parse_json_list(legs)
#            if not parsed_legs: raise ValueError("legs required")
```

Parse errors propagate as exceptions. In `ibkr/server.py`, explicit `try/except` blocks catch them. In `mcp_server.py` and `fmp/server.py`, `@mcp.tool()` functions are wrapped by FastMCP which catches unhandled exceptions and returns MCP error responses. All three servers are covered.

### Step 4: Parse at the MCP boundary, not in downstream handlers

The `mcp_server.py` wrappers pass list params through to `mcp_tools/*.py` handlers. Parse in `mcp_server.py` wrapper, pass the parsed list to the handler — handler signatures and internal logic stay unchanged. This isolates the workaround to the MCP layer.

### Step 5: Update docstrings

For each changed parameter, update the docstring to mention accepted formats. Example:
```
strikes: Strike prices — JSON array or comma-separated (e.g. '[75,80,85]' or '75,80,85').
```

## Files Modified

| File | Changes |
|------|---------|
| `mcp_tools/common.py` | Add `parse_list()`, `parse_json_list()` |
| `ibkr/server.py` | Copy helpers, fix 2 params |
| `mcp_server.py` | Fix 11 params (parse in wrappers before passing to handlers) |
| `fmp/server.py` | Copy helpers, fix 6 params |

**No changes to internal handlers** (`mcp_tools/*.py`) — parsing happens at the MCP boundary.

## fmp-mcp PyPI Note

`fmp/server.py` syncs to the `fmp-mcp` PyPI package. After this change lands, bump version and publish so external installs get the fix. Not blocking for this PR — tracked separately.

## Verification

1. `pytest tests/` — existing tests pass (no behavioral change for correctly-typed inputs)
2. `/mcp` reconnect all three servers
3. Live test: `get_ibkr_option_prices(symbol="SLV", expiry="20260320", strikes="[75,80,85]", right="P")` — should work
4. Live test: `get_ibkr_market_data(symbols="ES", ...)` — single symbol string works
5. Live test: `analyze_option_chain(symbol="SLV", expiry="20260320", strikes="[75,80,85]")` — should work

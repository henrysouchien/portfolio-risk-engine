# Stock Basket Phase 5: ETF Seeding

**Date**: 2026-02-27
**Status**: Complete (commit `4d98b43d`)
**Depends on**: Phase 1 (CRUD, complete)
**Risk**: Low — thin wrapper over existing `create_basket()` + FMP ETF holdings endpoint

## Goal

Add a `create_basket_from_etf` MCP tool that fetches an ETF's top holdings from FMP and creates a basket with those tickers and their weights. Enables customized ETF replication, factor analysis on ETF slices, and direct stock ownership without expense ratios.

## Design: Thin Wrapper Over Existing Infrastructure

No new DB tables, result objects, or flag generators needed. The tool:
1. Fetches ETF holdings via `FMPClient().fetch("etf_holdings", symbol=etf_ticker)`
2. Extracts top N tickers and their weights (normalized to sum to 1.0)
3. Calls the existing `create_basket()` function with `weighting_method="custom"`

## Data Flow

```
create_basket_from_etf(etf_ticker="SPY", name="sp500_top20", top_n=20)
    ↓
FMPClient().fetch("etf_holdings", symbol="SPY") → raw holdings DataFrame
    ↓
Extract symbol + weightPercentage per holding (same column resolution as _summarize_holdings)
    ↓
Filter: skip holdings without valid symbol or weight, apply min_weight filter
    ↓
Dedupe: aggregate weights for duplicate symbols (e.g., multiple share classes)
    ↓
Take top_n by weight, re-normalize weights to sum to 1.0
    ↓
create_basket(name="sp500_top20", tickers=[...], weights={...},
              weighting_method="custom", description="Seeded from SPY top 20 holdings")
    ↓
Check result status — only add ETF metadata if status="success"
    ↓
Standard create_basket response + ETF metadata
```

## Implementation

### 1. New function: `mcp_tools/baskets.py` — `create_basket_from_etf()` (ADD)

Add after `delete_basket()` (~line 993):

```python
@handle_mcp_errors
def create_basket_from_etf(
    etf_ticker: str,
    name: Optional[str] = None,
    top_n: int = 20,
    min_weight: float = 0.0,
    description: Optional[str] = None,
    format: Literal["full", "agent"] = "full",
    user_email: Optional[str] = None,
) -> dict:
```

**Parameters:**
- `etf_ticker` (required): ETF symbol to seed from (e.g., "SPY", "QQQ", "XLF")
- `name` (optional): Basket name. Defaults to `"{etf_ticker}_top{top_n}"` (e.g., `"SPY_top20"`)
- `top_n` (int, default 20): Number of top holdings to include. Clamped to `[2, 50]` (50 is the `max_length` on `CreateFactorGroupRequest.tickers`).
- `min_weight` (float, default 0.0): Minimum weight percentage to include (e.g., `0.5` = skip holdings under 0.5%). Applied before `top_n`.
- `description` (optional): Basket description. Defaults to `"Seeded from {etf_ticker} top {top_n} holdings"`
- `format`: Standard `"full"` / `"agent"` format
- `user_email`: Standard MCP user context

**Logic:**
1. Normalize `etf_ticker` (uppercase, strip)
2. Validate `top_n` (clamp to `[2, 50]`)
3. Fetch holdings with 402 fallback: Try `FMPClient().fetch("etf_holdings", symbol=etf_ticker, use_cache=True)`. If that raises a 402 error, fall back to `FMPClient().fetch("etf_holdings_v3", symbol=etf_ticker, use_cache=True)`. This mirrors the `_safe_fetch_records()` fallback pattern in `fmp/tools/etf_funds.py:88`.
4. If DataFrame is empty → raise `ValueError(f"No holdings data found for ETF '{etf_ticker}'")`
5. Extract holdings from DataFrame — each row has columns like `symbol`, `weightPercentage`/`weight`. Use same column resolution pattern as `_summarize_holdings()` in `fmp/tools/etf_funds.py:119`:
   - Symbol: first non-null of `["symbol", "assetSymbol", "ticker"]`
   - Weight: first non-null of `["weightPercentage", "weight", "allocation"]`
6. Filter out rows with no valid symbol (empty/null) or no valid weight (None/0/non-finite)
7. **Dedupe duplicate symbols**: If the same ticker appears multiple times (e.g., different share classes), aggregate their weights by summing. This prevents distorted weights and avoids the `<2 unique tickers` validation failure in `create_basket()`.
8. Apply `min_weight` filter: skip holdings where `weight_pct < min_weight`. Note: `min_weight` is in **percentage** units to match FMP's raw data (e.g., `min_weight=0.5` means skip holdings under 0.5%).
9. Sort by weight descending, take top `top_n`
10. If fewer than 2 holdings remain → raise `ValueError(f"ETF '{etf_ticker}' has fewer than 2 valid holdings after filtering")`
11. Convert FMP percentage weights to decimals (e.g., 7.2 → 0.072), then re-normalize so weights sum to 1.0
12. Generate default `name` if not provided: `f"{etf_ticker}_top{top_n}"`
13. Generate default `description` if not provided: `f"Seeded from {etf_ticker} top {len(tickers)} holdings"`
14. Call `create_basket(name=name, tickers=tickers, weights=weights, weighting_method="custom", description=description, format=format, user_email=user_email)`
15. **Check result status**: `create_basket()` is decorated with `@handle_mcp_errors`, so errors return `{"status": "error", ...}` dicts instead of raising. Only add `etf_source` metadata if `result.get("status") == "success"`. If error, return the error dict as-is.

**ETF metadata added to response:**
```python
result["etf_source"] = {
    "etf_ticker": etf_ticker,
    "total_etf_holdings": total_holdings_count,
    "holdings_used": len(tickers),
    "weight_coverage_pct": round(sum_of_selected_raw_weights, 2),
    "min_weight_filter": min_weight,
}
```

### 2. Register tool: `mcp_server.py` (MODIFY)

Add import (alongside existing basket imports, after line ~55):
```python
from mcp_tools.baskets import create_basket_from_etf as _create_basket_from_etf
```

Register `@mcp.tool()` wrapper after existing basket tools (~line 1261).

**IMPORTANT**: Do NOT expose `user_email` as a parameter. All existing basket MCP wrappers pass `user_email=None` and let `resolve_user_email()` resolve from `RISK_MODULE_USER_EMAIL` env var. This prevents cross-user access.

```python
@mcp.tool()
def create_basket_from_etf(
    etf_ticker: str,
    name: str = "",
    top_n: int = 20,
    min_weight: float = 0.0,
    description: str = "",
    format: str = "full",
) -> dict:
    """Create a stock basket seeded from an ETF's top holdings.

    Fetches the ETF's holdings, takes the top N by weight, and creates
    a basket with custom weights matching the ETF allocation.
    """
    return _create_basket_from_etf(
        etf_ticker=etf_ticker,
        name=name or None,
        top_n=top_n,
        min_weight=min_weight,
        description=description or None,
        format=format,
        user_email=None,  # Uses RISK_MODULE_USER_EMAIL from env
    )
```

## Key Implementation Notes

- **Holdings data source**: `FMPClient().fetch("etf_holdings", symbol=...)` returns a DataFrame. Key columns: `symbol` (or `assetSymbol`/`ticker`), `weightPercentage` (or `weight`/`allocation`). Use the same column resolution pattern as `_summarize_holdings()` in `fmp/tools/etf_funds.py:119`.
- **Weight normalization**: FMP weights are percentages (e.g., 7.2 = 7.2%). Convert to decimal (0.072) before passing to `create_basket()`. After taking top_n, re-normalize so weights sum to 1.0.
- **Reuse `create_basket()` directly**: Don't duplicate validation, DB writes, or response building. Call `create_basket()` which handles ticker validation, normalization, DB persistence, and response formatting.
- **`@handle_mcp_errors` decorator**: Required on `create_basket_from_etf()`.
- **Symbol cleaning**: Some ETF holdings may have symbols like `BRK.B` or empty strings for non-equity holdings (bonds, cash, derivatives). Skip rows with empty/invalid symbols.
- **Non-equity filtering**: ETFs may hold bonds, cash, or derivatives. Primary filter is "no valid symbol" (empty/null). Additionally, `create_basket()` runs `_validate_tickers()` which does FMP profile lookups — non-equity symbols that can't be resolved get warning-only flags but are still persisted. This is acceptable: the basket is a user-editable starting point, and unknown tickers won't break anything (they just won't have price data for analysis).
- **Duplicate symbol aggregation**: Some ETFs list the same ticker multiple times (e.g., different share classes or split entries). Aggregate weights by summing before the top_n cut. Use `_normalize_ticker()` on each symbol first so that case differences don't create false duplicates.
- **`create_basket()` error handling**: `create_basket()` is wrapped with `@handle_mcp_errors`, so it returns error dicts (`{"status": "error", ...}`) rather than raising. Check `result.get("status")` before appending `etf_source` metadata — return error responses unchanged.
- **`min_weight` units**: `min_weight` is in percentage units matching FMP's raw data (e.g., `min_weight=1.0` filters out holdings under 1%). The conversion to decimals happens after the `min_weight` filter is applied.
- **`use_cache=True`**: ETF holdings don't change frequently. Cache is fine (24h TTL per FMP registry).
- **DB access**: No direct DB access needed — `create_basket()` handles all DB operations internally.

## Reuse from existing code

- `mcp_tools/baskets.py:480` — `create_basket()` (full basket creation with validation, DB, response)
- `mcp_tools/baskets.py:227` — `_normalize_ticker()` (uppercase + strip)
- `mcp_tools/common.py` — `@handle_mcp_errors` decorator
- `fmp/client.py` — `FMPClient().fetch("etf_holdings", symbol=...)`
- `fmp/registry.py:1223` — `"etf_holdings"` endpoint (path `/etf/holdings`, 24h cache)
- `fmp/tools/etf_funds.py:119` — `_summarize_holdings()` for column name resolution pattern

## Verification

1. `python3 -c "from mcp_tools.baskets import create_basket_from_etf"` — imports cleanly
2. **Basic ETF seeding**: `create_basket_from_etf(etf_ticker="SPY", name="spy_test", top_n=10)` — creates basket with 10 tickers
3. **Auto-naming**: `create_basket_from_etf(etf_ticker="QQQ")` — creates basket named `"QQQ_top20"`
4. **Min weight filter**: `create_basket_from_etf(etf_ticker="SPY", name="spy_large", min_weight=1.0, top_n=50)` — only includes holdings ≥1%
5. **Agent format**: `create_basket_from_etf(etf_ticker="XLF", name="xlf_test", format="agent")` — returns snapshot with etf_source metadata
6. **Invalid ETF**: `create_basket_from_etf(etf_ticker="NOTANETF")` — clean error
7. **Duplicate name**: `create_basket_from_etf(etf_ticker="SPY", name="existing_basket")` — error from `create_basket()` validation
8. **Weight coverage**: Verify `weight_coverage_pct` in response reflects actual ETF weight captured

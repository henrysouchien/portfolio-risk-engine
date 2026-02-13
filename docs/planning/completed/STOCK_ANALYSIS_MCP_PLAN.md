# Stock Analysis MCP Tool

**Status:** COMPLETE
**Parent:** [MCP Extensions Plan](./MCP_EXTENSIONS_PLAN.md)

---

## Overview

Add an `analyze_stock` MCP tool to the `portfolio-mcp` server. Unlike the portfolio-level tools (risk, performance), this is a standalone single-ticker analysis tool. It uses `StockService.analyze_stock()` to compute volatility, market beta, factor exposures, and risk decomposition for any individual stock.

**Key difference from other MCP tools:** No portfolio loading, no PositionService, no `_resolve_user_id`. Just takes a ticker and optional parameters. Much simpler.

---

## Files to Change

| Action | File | Change |
|--------|------|--------|
| **Create** | `mcp_tools/stock.py` | Tool implementation (~80 lines) |
| **Modify** | `mcp_tools/__init__.py` | Add import + export |
| **Modify** | `mcp_server.py` | Add import + `@mcp.tool()` registration |
| **Modify** | `mcp_tools/README.md` | Add `analyze_stock` to tools list |

---

## File 1: `mcp_tools/stock.py` (new)

### No portfolio helper needed

Unlike risk/performance tools, stock analysis doesn't need positions or PortfolioData. It takes a ticker directly and uses `StockService` which handles everything internally (data fetching, factor proxy generation, caching).

### Tool: `analyze_stock()`

**Parameters:**
- `ticker: str` — required, the stock/ETF symbol to analyze
- `start_date: Optional[str] = None` — YYYY-MM-DD, defaults to ~5 years ago internally
- `end_date: Optional[str] = None` — YYYY-MM-DD, defaults to today internally
- `format: Literal["full", "summary", "report"] = "summary"`
- `use_cache: bool = True`

**Note on `factor_proxies`:** Not exposed as an MCP parameter. Auto-generated factor proxies work well for most cases and the dict structure (`{"market": "SPY", "momentum": "MTUM", ...}`) is complex for AI to construct. If needed in the future, can be added.

**Flow:**
1. Create `StockData.from_ticker(ticker, start_date, end_date)`
2. Call `StockService(cache_results=use_cache).analyze_stock(stock_data)` → `StockAnalysisResult`
3. Format response:

**Summary format** (built from accessors since no `get_summary()` exists):
```
status, ticker, analysis_type (from result.analysis_type),
annual_volatility, monthly_volatility (from get_volatility_metrics()),
beta, alpha, r_squared, idiosyncratic_volatility (from get_market_regression(),
    with fallback to result.risk_metrics if regression_metrics is empty — handles
    simple-regression path where data is in risk_metrics instead),
factor_exposures (dict of factor → beta from get_factor_exposures(), if multi-factor),
analysis_period (from result.analysis_period),
+ conditionally: interest_rate_beta, effective_duration (if bond, when present)
```

**Regression metrics fallback:** The simple-regression path in `core/stock_analysis.py` populates `risk_metrics` instead of `regression_metrics`. Since auto-generated factor proxies almost always trigger multi-factor, this is rare, but the summary should fall back to `result.risk_metrics` when `result.regression_metrics` is empty for robustness.

**Full format:** `result.to_api_response()` + `status: "success"`

**Report format:** `{"status": "success", "report": result.to_formatted_report()}`

**Error handling:** Same pattern — `try/except → {"status": "error", "error": str(e)}`
**Stdout protection:** Same pattern — `sys.stdout = sys.stderr` in try/finally

---

## File 2: `mcp_tools/__init__.py` (modify)

- Add `from mcp_tools.stock import analyze_stock`
- Add `"analyze_stock"` to `__all__`
- Update module docstring

---

## File 3: `mcp_server.py` (modify)

- Add `from mcp_tools.stock import analyze_stock as _analyze_stock`
- Add `@mcp.tool()` wrapper exposing `ticker`, `start_date`, `end_date`, `format`, `use_cache`
- Docstring with examples: "Analyze AAPL stock risk", "What's TSLA's beta?", "Factor analysis for NVDA"

---

## Reused Existing Code

| What | File | Used For |
|------|------|----------|
| `StockService.analyze_stock()` | `services/stock_service.py` | Service layer with caching |
| `StockData.from_ticker()` | `core/data_objects.py:73-257` | Input validation + construction |
| `StockAnalysisResult.to_api_response()` | `core/result_objects.py:5255+` | Full format |
| `StockAnalysisResult.to_formatted_report()` | `core/result_objects.py` | Report format |
| `StockAnalysisResult.get_volatility_metrics()` | `core/result_objects.py:5348` | Summary: vol metrics |
| `StockAnalysisResult.get_market_regression()` | `core/result_objects.py:5355` | Summary: beta/alpha/R² |
| `StockAnalysisResult.get_factor_exposures()` | `core/result_objects.py:5364` | Summary: factor betas |

---

## Edge Cases

- **Invalid ticker**: `StockService` will raise when FMP returns no data. Surfaces via error pattern.
- **Ticker with no history**: Same — raises, caught by except.
- **Bond tickers**: Auto-detected, returns interest rate beta and duration in addition to standard metrics. Summary conditionally includes `interest_rate_beta` and `effective_duration` when present.
- **OTC/foreign tickers**: May have limited data. FMP may return partial history — core analysis handles gracefully.

---

## Verification

1. **Direct call test** — Import `analyze_stock`, call with each format (summary/full/report) for a known ticker (e.g., "AAPL"), verify `status: "success"` and expected fields
2. **Different tickers** — Test with ETF ("SPY"), small cap, etc.
3. **Error case** — Call with invalid ticker like "ZZZZZ"
4. **MCP integration** — Restart Claude Code, verify tool in `claude mcp list`, test via natural language ("Analyze AAPL", "What's TSLA's beta?")

---

## Related Documents

- [MCP Extensions Plan](./MCP_EXTENSIONS_PLAN.md) — Parent roadmap
- [Risk MCP Plan](./completed/RISK_MCP_PLAN.md) — Pattern reference
- [Performance MCP Plan](./PERFORMANCE_MCP_PLAN.md) — Recent implementation
- [MCP Tools README](../../mcp_tools/README.md) — Guidelines for adding tools

---

*Document created: 2026-02-06*
*Status: COMPLETE*

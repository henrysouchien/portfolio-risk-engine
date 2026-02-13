# Performance MCP Tool

**Status:** COMPLETE
**Parent:** [MCP Extensions Plan](./MCP_EXTENSIONS_PLAN.md)

---

## Overview

Add a `get_performance` MCP tool to the `portfolio-mcp` server. Performance analysis already works end-to-end via `PortfolioService.analyze_performance()` and `PerformanceResult`. This plan wraps it as an MCP tool following the same pattern as `get_risk_score`/`get_risk_analysis`.

**Key difference from risk tools:** Performance does NOT need factor proxies or risk limits — just positions + PortfolioData + a benchmark ticker.

---

## Files to Change

| Action | File | Change |
|--------|------|--------|
| **Create** | `mcp_tools/performance.py` | Tool implementation (~100 lines) |
| **Modify** | `mcp_tools/__init__.py` | Add import + export |
| **Modify** | `mcp_server.py` | Add import + `@mcp.tool()` registration |
| **Modify** | `mcp_tools/README.md` | Add `get_performance` to tools list |

---

## File 1: `mcp_tools/performance.py` (new)

### Helper: `_load_portfolio_for_performance()`

Simplified version of `_load_portfolio_for_analysis()` — skips factor proxies and risk limits:

1. Resolve user from `user_email` or env var
2. `_resolve_user_id()` — imported from `mcp_tools.risk` (avoids duplication)
3. Fetch live positions via `PositionService.get_all_positions(use_cache=use_cache, force_refresh=not use_cache, consolidate=True)` — mirrors risk tool params
4. Guard: empty positions → raise
5. Convert to `PortfolioData` via `to_portfolio_data(portfolio_name=...)`
6. Set `user_id` for temp file isolation
7. Return `(user, user_id, portfolio_data)`

### Tool: `get_performance()`

**Parameters:**
- `user_email: Optional[str] = None`
- `portfolio_name: str = "CURRENT_PORTFOLIO"`
- `benchmark_ticker: str = "SPY"` — unique to performance
- `format: Literal["full", "summary", "report"] = "summary"`
- `use_cache: bool = True`

**Flow:**
1. `_load_portfolio_for_performance()` → `(user, user_id, portfolio_data)`
2. `PortfolioService(cache_results=use_cache).analyze_performance(portfolio_data, benchmark_ticker)` → `PerformanceResult`
3. Format response:

**Summary format** (custom build from `get_summary()` + benchmark fields):
```
status, total_return, annualized_return, volatility, sharpe_ratio,
max_drawdown, win_rate, analysis_years, benchmark_ticker, alpha_annual,
beta, performance_category, key_insights
```

**Full format:** `result.to_api_response()` + `status: "success"`

**Report format:** `{"status": "success", "report": result.to_formatted_report()}`

**Error handling:** Same pattern — `try/except → {"status": "error", "error": str(e)}`
**Stdout protection:** Same pattern — `sys.stdout = sys.stderr` in try/finally

**Note on private method usage:** Summary calls `_categorize_performance()` and `_generate_key_insights()` directly. These are already used by `to_api_response()` (lines 3488-3489) so the coupling is pre-existing. Pulling from `to_api_response()` and trimming would be wasteful (it generates the full formatted report string).

---

## File 2: `mcp_tools/__init__.py` (modify)

- Add `from mcp_tools.performance import get_performance`
- Add `"get_performance"` to `__all__`
- Update module docstring

---

## File 3: `mcp_server.py` (modify)

- Add `from mcp_tools.performance import get_performance as _get_performance`
- Add `@mcp.tool()` wrapper with `benchmark_ticker` parameter, passes `user_email=None`
- Docstring with examples: "How has my portfolio performed?", "What's my return vs QQQ?"

---

## Reused Existing Code

| What | File | Used For |
|------|------|----------|
| `_resolve_user_id()` | `mcp_tools/risk.py:85-97` | Import to avoid duplication |
| `PositionService.get_all_positions()` | `services/position_service.py` | Fetch live positions |
| `PositionsData.to_portfolio_data()` | `core/data_objects.py` | Convert positions → PortfolioData |
| `PortfolioService.analyze_performance()` | `services/portfolio_service.py:547-603` | Run analysis |
| `PerformanceResult.get_summary()` | `core/result_objects.py:3241` | Summary format |
| `PerformanceResult.to_api_response()` | `core/result_objects.py:3353` | Full format |
| `PerformanceResult.to_formatted_report()` | `core/result_objects.py` | Report format |
| `PerformanceResult._categorize_performance()` | `core/result_objects.py:3271` | Summary context |
| `PerformanceResult._generate_key_insights()` | `core/result_objects.py:3289` | Summary context |

---

## Edge Cases

- **All-cash portfolio**: `to_portfolio_data()` may raise if no equity positions remain after cash proxy mapping. Surfaces cleanly via the `try/except → {"status": "error"}` pattern.
- **Invalid benchmark ticker**: `analyze_performance()` will fail with a `PortfolioAnalysisError`. Surfaces via same error pattern.
- **Date range**: Uses static `PORTFOLIO_DEFAULTS` (same as risk tools). Optional `start_date`/`end_date` params deferred for now to keep parity with existing tools.
- **Import overhead from `mcp_tools.risk`**: Importing `_resolve_user_id` pulls in risk module dependencies at import time. Acceptable for now; extract to shared utility when adding the next tool.

---

## Verification

1. **Direct call test** — Import `get_performance`, call with each format (summary/full/report), verify `status: "success"` and expected fields
2. **Custom benchmark** — Call with `benchmark_ticker="QQQ"`, verify it appears in response
3. **Error case** — Call with bad portfolio name or invalid benchmark
4. **MCP integration** — Restart Claude Code, verify tool in `claude mcp list`, test natural language ("How has my portfolio performed?")

---

## Related Documents

- [MCP Extensions Plan](./MCP_EXTENSIONS_PLAN.md) — Parent roadmap
- [Risk MCP Plan](./completed/RISK_MCP_PLAN.md) — Pattern to follow
- [MCP Tools README](../../mcp_tools/README.md) — Guidelines for adding tools

---

*Document created: 2026-02-06*
*Completed: 2026-02-06*
*Status: COMPLETE — All 3 formats verified (summary/full/report)*

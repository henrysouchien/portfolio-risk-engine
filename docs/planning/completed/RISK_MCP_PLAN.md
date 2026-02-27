# Risk Analysis MCP Tools

**Status: COMPLETE** — All core implementation done. Future enhancements (`include` filter, cash proxy mapping) tracked separately.

## Overview

Add two MCP tools (`get_risk_score`, `get_risk_analysis`) to the existing `portfolio-mcp` server, following the same pattern as `get_positions`. Both are all-in-one tools that use a **hybrid data approach**: live brokerage positions for holdings, database for factor proxies, and database for risk limits. The agent just calls the tool with an optional `portfolio_name`.

## Design Decisions

- **Two tools**: `get_risk_score` (0-100 score + compliance) and `get_risk_analysis` (30+ metrics)
- **All-in-one**: Each tool loads everything internally — no manual chaining needed
- **Hybrid data approach**:
  - **Holdings**: Live brokerage positions via `PositionService.get_all_positions()` (not stale saved configs)
  - **Factor proxies**: From database via `ensure_factor_proxies()` (auto-generates missing)
  - **Expected returns**: Not loaded — not needed for risk analysis or risk scoring (only used in optimization)
  - **Risk limits**: From database via `RiskLimitsManager`
  - **Dates**: From `PORTFOLIO_DEFAULTS` (start_date, end_date)
- **Portfolio switching**: `portfolio_name` parameter selects saved config for factor proxies, risk limits
- **User from env**: Same `RISK_MODULE_USER_EMAIL` env var pattern as `get_positions`
- **stdout protection**: Wrap tool bodies in stdout→stderr redirect to protect MCP JSON-RPC channel from stray `print()` calls in dependencies

## Data Flow

```
PositionService.get_all_positions(use_cache, force_refresh)
  → filter out cash positions (CUR:*)                       ← simple filter, defers proper cash mapping to FX plan
  → PositionResult.data.to_portfolio_data(portfolio_name)   ← live holdings + default dates
      + ensure_factor_proxies(user_id, tickers)             ← from DB (auto-generates missing)
      + RiskLimitsManager.load_risk_limits()                ← from DB (for risk score only)
  → PortfolioService.analyze_*()
  → RiskScoreResult / RiskAnalysisResult
```

## Files

| Action | File | What | Status |
|--------|------|------|--------|
| **Create** | `mcp_tools/risk.py` | Core implementation (~267 lines) | ✅ |
| **Modify** | `mcp_tools/__init__.py` | Export new tools | ✅ |
| **Modify** | `mcp_server.py` | Register tools with `@mcp.tool()` | ✅ |

## File 1: `mcp_tools/risk.py` (new) ✅

### Helpers

**`_resolve_user_id(user_email)`** — Reuse pattern from `services/position_service.py:680-690`:
```python
def _resolve_user_id(user_email: str) -> int:
    from database import get_db_session
    with get_db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE email = %s", (user_email,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"User not found: {user_email}")
        return row["id"]
```

**`_load_portfolio_for_analysis(user_email, portfolio_name, use_cache)`** — Shared setup using hybrid data approach. Raises on error (callers catch at tool boundary):
```python
def _load_portfolio_for_analysis(user_email, portfolio_name, use_cache=True):
    user = user_email or get_default_user()
    if not user:
        raise ValueError("No user specified and RISK_MODULE_USER_EMAIL not configured")

    user_id = _resolve_user_id(user)

    # 1. Fetch live brokerage positions (use_cache flows through)
    position_service = PositionService(user)
    position_result = position_service.get_all_positions(
        use_cache=use_cache,
        force_refresh=not use_cache,
        consolidate=True
    )

    # Guard: empty positions → friendly error before PortfolioData validation blows up
    if not position_result.data.positions:
        raise ValueError("No brokerage positions found. Connect a brokerage account first.")

    # 2. Filter out cash positions (CUR:USD etc.) — they can't be priced or have
    #    factor proxies. Cash has near-zero risk contribution so excluding is acceptable.
    #    Proper cash proxy mapping (CUR:USD → SGOV) will be added to to_portfolio_data()
    #    in a future change coordinated with the FX plan (not in this implementation).
    position_result.data.positions = [
        p for p in position_result.data.positions
        if not (p.get("type") == "cash" or p.get("ticker", "").startswith("CUR:"))
    ]

    # Re-check after filtering — portfolio might be all cash
    if not position_result.data.positions:
        raise ValueError("No non-cash positions found. Portfolio contains only cash holdings.")

    # 3. Convert to PortfolioData
    portfolio_data = position_result.data.to_portfolio_data(
        portfolio_name=portfolio_name
    )

    # Set user_id for temp file isolation in multi-user environments
    portfolio_data.user_id = user_id

    # 4. Load factor proxies from DB (auto-generates missing via GPT)
    tickers = set(portfolio_data.portfolio_input.keys())
    portfolio_data.stock_factor_proxies = ensure_factor_proxies(
        user_id, portfolio_name, tickers, allow_gpt=True
    )

    # 5. Expected returns NOT loaded — not needed for risk analysis/scoring
    #    (only used in optimization). Avoids ticker mismatch between live
    #    positions and DB-stored portfolio tickers in ReturnsService.

    return user, user_id, portfolio_data
```

### `get_risk_score(user_email, portfolio_name, format, use_cache) -> dict` ✅

Parameters:
- `user_email: Optional[str] = None`
- `portfolio_name: str = "CURRENT_PORTFOLIO"`
- `format: Literal["full", "summary", "report"] = "summary"`
- `use_cache: bool = True`

Flow:
1. Call `_load_portfolio_for_analysis(use_cache=use_cache)` → `(user, user_id, portfolio_data)`
2. Load risk limits: `RiskLimitsManager(use_database=True, user_id=user_id).load_risk_limits(portfolio_name)`
3. **Guard**: If `risk_limits_data` is None or `.is_empty()`, return `{"status": "error", "error": "No risk limits configured for portfolio '...'. Set up risk limits first."}` — because `analyze_risk_score()` raises ValueError on empty limits.
4. Call `PortfolioService(cache_results=use_cache).analyze_risk_score(portfolio_data, risk_limits_data)`
5. Format response:
   - `"summary"`: Build from `result.get_summary()` + `result.is_compliant()` + `result.get_recommendations()`:
     ```python
     summary = result.get_summary()
     return {
         "status": "success",
         "overall_score": summary["overall_score"],
         "risk_category": result.risk_score.get("category", "Unknown"),  # human-readable ("Excellent", "Good", ...)
         "component_scores": summary["component_scores"],
         "is_compliant": result.is_compliant(),
         "total_violations": summary["total_violations"],
         "recommendations": result.get_recommendations()[:5],
         "risk_factors": result.get_risk_factors()[:5]
     }
     ```
   - `"full"`: `result.to_api_response()` with `status: "success"` added
   - `"report"`: `{"status": "success", "report": result.to_formatted_report()}`

### `get_risk_analysis(user_email, portfolio_name, format, use_cache) -> dict` ✅

Same parameters. Flow differs:
1. Same `_load_portfolio_for_analysis(use_cache=use_cache)` setup
2. Risk limits optional — load them, but if unavailable or empty, set to `None` (don't fail)
3. Call `PortfolioService(cache_results=use_cache).analyze_portfolio(portfolio_data, risk_limits_data)`
4. Format response:
   - `"summary"`: volatility, herfindahl, factor/idiosyncratic %, top risk contributors, factor betas (via `result.get_summary()`)
   - `"full"`: `result.to_api_response()` with `status: "success"` added
   - `"report"`: `{"status": "success", "report": result.to_formatted_report()}`

### Error handling ✅

Never throw — always return `{"status": "error", "error": "..."}`. The helper `_load_portfolio_for_analysis` raises exceptions; both tool functions wrap everything in try/except and convert to error dicts.

### stdout protection ✅

Both tool functions wrap their body in:
```python
import sys
_saved = sys.stdout
sys.stdout = sys.stderr
try:
    # ... all work ...
finally:
    sys.stdout = _saved
```
This prevents stray `print()` calls in `RiskLimitsManager`, `PortfolioManager`, etc. from corrupting the MCP JSON-RPC channel.

## File 2: `mcp_tools/__init__.py` (modify) ✅

Add imports and exports for `get_risk_score`, `get_risk_analysis`.

## File 3: `mcp_server.py` (modify) ✅

Add two `@mcp.tool()` registrations after the existing `get_positions` tool. Each is a thin wrapper that calls the `mcp_tools/risk.py` implementation with `user_email=None`.

**`get_risk_score` tool** — defaults to `format="summary"`:
```
Args: portfolio_name, format (full/summary/report), use_cache
Examples in docstring:
  "What's my portfolio risk score?" -> get_risk_score()
  "Am I compliant with risk limits?" -> get_risk_score()
  "Full risk score report" -> get_risk_score(format="report")
  "Risk score for retirement portfolio" -> get_risk_score(portfolio_name="RETIREMENT")
```

**`get_risk_analysis` tool** — defaults to `format="summary"`:
```
Args: portfolio_name, format (full/summary/report), use_cache
Examples in docstring:
  "Analyze my portfolio risk" -> get_risk_analysis()
  "What's my portfolio volatility?" -> get_risk_analysis()
  "Full risk report with all metrics" -> get_risk_analysis(format="full")
```

## Review Fixes Applied ✅

Issues identified by code review and their resolutions (all applied or intentionally deferred):

| # | Severity | Issue | Fix |
|---|----------|-------|-----|
| 1 | Critical | `get_positions()` requires `provider` arg — would TypeError | Changed to `get_all_positions()` matching `mcp_tools/positions.py` pattern |
| 2 | High | `_load_portfolio_for_analysis` returns dict on error but callers unpack as tuple | Helper now raises exceptions; tool functions catch at boundary |
| 3 | High | `analyze_risk_score` throws on empty risk limits | Added `is_empty()` guard before calling, returns friendly error |
| 4 | Medium | `to_portfolio_data()` ignores `portfolio_name` param | Now passes `portfolio_name` through |
| 5 | Medium | `use_cache` only controls `PortfolioService`, not position fetch | Now flows to `get_all_positions(use_cache=, force_refresh=)` |
| 6 | Medium | Summary shape mismatch (`score` vs `overall_score`, missing `is_compliant`) | Custom summary built from `get_summary()` + `is_compliant()` + `get_recommendations()` |
| 7 | Data | `ReturnsService.get_complete_returns()` resolves tickers from DB, not live positions | Removed — expected returns not needed for risk analysis/scoring |
| 8 | Medium | Empty positions blow up in `PortfolioData.__post_init__` with unfriendly error | Guard before `to_portfolio_data()` — "No brokerage positions found" |
| 9 | Low | Temp files lack user isolation without `user_id` on PortfolioData | Set `portfolio_data.user_id = user_id` after construction |
| 10 | High | CUR:USD stays in portfolio_input — can't be priced, triggers GPT proxy generation | **Deferred**: Simple cash filter in MCP helper for now. Proper cash proxy mapping in `to_portfolio_data()` deferred to coordinate with FX plan (see below). |
| 11 | Medium | Future `include` filter drops `status` wrapper field | Always re-add `status` after filtering |
| 12–21 | Various | Cash mapping in `to_portfolio_data()`: import path, stale state, fmp_ticker corruption, YAML fallback, SGOV merge, CUR: detection, test updates | **Deferred to FX plan**: All `to_portfolio_data()` cash mapping changes will be done together with FX `currency_map` population (Step 1.4 of `FX_CURRENCY_CONVERSION_PLAN.md`). The designs are documented in review history below for reference. |

## Key references to reuse

| What | File | Line |
|------|------|------|
| MCP tool pattern | `mcp_tools/positions.py` | entire file |
| MCP registration pattern | `mcp_server.py` | 39-90 |
| API risk-score wiring | `app.py` | 1452-1508 |
| User ID lookup | `services/position_service.py` | 680-690 |
| Live positions fetch | `services/position_service.py:get_all_positions()` | 157-190 |
| Positions → PortfolioData | `core/data_objects.py:PositionsData.to_portfolio_data()` | 374-491 |
| Factor proxy loading | `services/factor_proxy_service.py:ensure_factor_proxies()` | 51-54 |
| Risk limits loading | `inputs/risk_limits_manager.py:load_risk_limits()` | 152-222 |
| PortfolioService.analyze_risk_score | `services/portfolio_service.py` | 456-546 |
| PortfolioService.analyze_portfolio | `services/portfolio_service.py` | 104-323 |
| RiskScoreResult.get_summary | `core/result_objects.py` | ~3852 |
| RiskScoreResult.is_compliant | `core/result_objects.py` | ~3886 |
| RiskScoreResult.get_recommendations | `core/result_objects.py` | ~3874 |
| RiskAnalysisResult.get_summary | `core/result_objects.py` | ~1171 |

## Verification ✅

All verified via API simulation (`show_api_output.py`) and end-to-end CLI tests. Both tools return `status: "success"` with correct data shapes in all 3 formats.

1. **Unit test** — import and call directly:
```python
from mcp_tools.risk import get_risk_score, get_risk_analysis
# Test risk score
result = get_risk_score(user_email="henry@....", format="summary")
assert result["status"] == "success"
assert "overall_score" in result
assert "is_compliant" in result

# Test risk analysis
result = get_risk_analysis(user_email="henry@....", format="summary")
assert result["status"] == "success"
assert "volatility_annual" in result
```

2. **All formats** — test full, summary, report for each tool

3. **Error cases** — test with bad portfolio_name, missing env var, missing risk limits

4. **Cash filtering** — verify cash positions (CUR:USD, type=cash) are excluded and don't trigger price fetching or factor proxy generation. Test all-cash portfolio returns friendly error. **Known limitations**: (a) Excluding positive cash inflates risk metrics (volatility, leverage, concentration) because the cash allocation no longer dilutes equity weights. For example, a 70% equity / 30% cash portfolio will be analyzed as 100% equity. (b) Excluding negative cash (margin debt) understates risk — margin debt increases leverage and should amplify risk metrics, but is also filtered out. Both are acceptable for now — proper cash proxy mapping (CUR:USD → SGOV) will restore correct weighting (positive and negative) when coordinated with the FX plan.

5. **MCP integration** — restart Claude Code, verify tools appear in `claude mcp list`, test via natural language ("What's my risk score?")

---

## Future: Selective Section Filtering

Extracted to separate plan: [`docs/planning/MCP_SECTION_FILTERING_PLAN.md`](../MCP_SECTION_FILTERING_PLAN.md)

---

## Deferred: Cash Proxy Mapping in `to_portfolio_data()` (coordinate with FX plan)

**Status: Deferred — implement together with FX `currency_map` (Step 1.4 of `FX_CURRENCY_CONVERSION_PLAN.md`)**

The FX currency conversion plan also modifies `to_portfolio_data()` to populate a `currency_map` (ticker → ISO currency code) for non-USD positions. Cash proxy mapping (CUR:USD → SGOV) and FX currency tracking are complementary changes to the same method and the same `is_cash` branch. Doing them together avoids merge conflicts and two rounds of test updates.

**What was designed (reviews #10, #12–21) — to be implemented with FX:**
- Cash mapping inside `to_portfolio_data()`: CUR:USD → SGOV via `_load_cash_map()` (DB → YAML → hardcoded)
- Move `fmp_ticker_map` population after `is_cash` check (prevent corruption)
- 3 test updates: `test_positions_data.py:36`, `test_position_chain.py:56,63` (CUR:USD → SGOV)
- SGOV merge edge case documented (shares + dollars conflict)
- `_load_cash_map()` with 3-tier fallback

**Current workaround (in MCP helper):**
Simple filter excluding cash positions from the positions list before `to_portfolio_data()`. Cash has near-zero risk contribution, so excluding it is acceptable for risk analysis.

**TODO when FX lands:** Remove the cash filter from `_load_portfolio_for_analysis()` in `mcp_tools/risk.py` — once `to_portfolio_data()` maps CUR:USD → SGOV internally, the filter becomes unnecessary and would incorrectly exclude cash that should now flow through as a proxy ticker.

**Cash detection note:** The filter checks `type == "cash"` or `ticker.startswith("CUR:")`. Our brokerage providers (Plaid, SnapTrade) normalize cash to `CUR:XXX` format with `type="cash"` in `PositionService`. If a future provider emits non-standard cash tickers (e.g., `CASH`, `USD CASH`) without `type="cash"`, they'd slip through — but that's a provider normalization issue, not an MCP concern.

---

## Related Documents

- [FX Currency Conversion Plan](./FX_CURRENCY_CONVERSION_PLAN.md) — FX conversion, overlaps with cash mapping in `to_portfolio_data()`
- [Modular CLI Architecture Plan](./MODULAR_CLI_ARCHITECTURE_PLAN.md) — CLI extraction and module pattern
- [Modular Architecture Refactor Plan](./MODULAR_ARCHITECTURE_REFACTOR_PLAN.md) — Target folder structure
- [MCP Extensions Plan](./MCP_EXTENSIONS_PLAN.md) — Planned MCP tools roadmap
- [Position Module MCP Spec](./completed/POSITION_MODULE_MCP_SPEC.md) — Completed positions MCP (pattern to follow)

---

*Document created: 2026-02-05*
*Updated: 2026-02-06 — All 3 files implemented. 10 review fixes applied, 11 deferred to cash proxy mapping plan. Future `include` parameter designed but not yet built.*
*Status: COMPLETE*

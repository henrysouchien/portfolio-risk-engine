# Enriched Stock Lookup MCP Tool

## Context

The frontend stock lookup card gets rich data via `enrich_stock_data()` (profile + quote + ratios + forward P/E + quality signals + chart + technicals), but there's no MCP equivalent. The AI agent has to piece together many raw `fmp_fetch` calls (profile, quote, ratios, estimates, quality statements, technicals) to get what the frontend gets in one call. This tool fills that gap.

Complements existing `analyze_stock()` (risk/factors) — this covers fundamentals/pricing/quality. Together they give the full picture.

**Dependency**: Forward P/E Standardization (done, `37e58617`).

---

## Design Decisions

1. **Name**: `get_stock_fundamentals()` — precise, complements `analyze_stock()`. Not `stock_lookup` (too vague) or `get_enriched_stock` (leaks internal naming).

2. **Location**: `fmp/tools/stock_fundamentals.py` — FMP data tool, not portfolio tool. Uses `FMPClient` directly (not `stock_service.py` which has portfolio-context dependencies).

3. **No batch mode** — single ticker per call. `compare_peers()` already handles multi-ticker comparison.

4. **Section-based `include` param** — agents can select which sections they want. Default: all. This avoids parameter proliferation while giving flexibility.

5. **Nested response** — sections group related fields (valuation, profitability, quality, etc.) rather than a flat dump. Matches how agents reason about data.

6. **Chart data only in `format="full"`** — 2yr daily data is ~30-50KB. Summary format stays compact (~1-2KB).

7. **Fully best-effort** — mirrors `enrich_stock_data()` behavior. Every section is independently failable. No single section failure (including profile) kills the response. Failed sections go in `sections_failed`, warnings describe what went wrong. This matches the frontend's tolerance model and avoids breaking the tool for tickers with partial FMP coverage.

8. **`_last_trading_day` shared helper** — move the existing `_last_trading_day()` from `fmp/tools/market.py` to `fmp/tools/_helpers.py` (new shared helpers module within the fmp/tools package). Both `market.py` and `stock_fundamentals.py` import from there. This avoids importing private functions across sibling modules.

---

## Response Shape

### Summary format (default):

```python
{
    "status": "success",
    "symbol": "AAPL",
    "as_of": "2026-03-22",
    "profile": {
        "company_name": "Apple Inc.",
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "exchange": "NASDAQ",
    },
    "quote": {
        "price": 247.99,
        "change": -0.97,
        "change_percent": -0.4,
        "market_cap": 3640000000000,
        "volume": 58000000,
        "eps": 6.42,
    },
    "valuation": {
        "forward_pe": 26.6,
        "pe_ratio_ttm": 28.5,
        "pe_source": "forward",
        "ntm_eps": 9.33,
        "analyst_count_eps": 28,
        "pb_ratio": 41.5,
        "price_to_fcf": 29.6,
        "peg_ratio": 2.1,
        "ev_ebitda": 22.0,
        "dividend_yield": 0.005,
        "sector_avg_pe": 30.1,
    },
    "profitability": {
        "roe": 1.61,
        "roic": 0.51,
        "gross_margin": 0.46,
        "operating_margin": 0.32,
        "net_profit_margin": 0.25,
    },
    "balance_sheet": {
        "debt_to_equity": 1.87,
        "current_ratio": 0.99,
        "net_debt_to_ebitda": 0.45,
    },
    "quality": {
        "signals": { "revenue_growth": true, ... },
        "score": 6,
        "evaluated": 6,
        "max_signals": 6,
    },
    "technicals": {
        "rsi": 34.9,
        "rsi_signal": "oversold",
        "macd_signal": "bearish",
        "bollinger_position": "Lower",
        "composite_signal": "sell",
        "support": 244.55,
        "resistance": 254.42,
    },
    "sections_included": ["profile", "quote", "valuation", "profitability", "balance_sheet", "quality", "technicals"],
    "sections_failed": [],
    "warnings": [],
}
```

**Technical signal enums** (passthrough from `get_technical_analysis()`):
- RSI signal: `overbought | bullish | oversold | bearish | neutral`
- Composite signal: `strong_buy | buy | strong_sell | sell | neutral`

Full format adds `"chart"` section with 2yr daily price/volume data (volume zero-filled for missing days).

---

## Data Fetching (8-10 FMP calls, parallelized)

| # | Endpoint | Provides | Phase |
|---|----------|----------|-------|
| 1 | `profile` | company_name, sector, industry, exchange | 1 (parallel) |
| 2 | `quote` | price, change, changesPercentage, marketCap, volume, eps | 1 (parallel) |
| 3 | `ratios_ttm` | P/E, P/B, ROE, D/E, margins, dividend yield | 1 (parallel) |
| 4 | `key_metrics_ttm` | ROIC, net_debt/EBITDA, EV/EBITDA, PEG | 1 (parallel) |
| 5 | `income_statement` (limit=3) | For quality signals | 1 (parallel) |
| 6 | `cash_flow` (limit=3) | For quality signals | 1 (parallel) |
| 7 | `analyst_estimates` + `income_statement` (q, limit=1) | Forward P/E | 1 (parallel) |
| 8 | `sector_pe_snapshot` | Sector avg P/E (filtered to finite positive) | 2 (needs sector from #1) |
| 9 | `get_technical_analysis()` (internal, fans out to ~4-6 FMP calls internally) | RSI, MACD, Bollinger, S/R | 1 (parallel) |
| 10 | `historical_price_adjusted` | Chart (format="full" only) | 1 (parallel, conditional) |

Phase 1: fire all independent calls (1-7, 9, optionally 10). Phase 2: sector P/E once sector known from profile.

**Note**: `get_technical_analysis()` is counted as 1 call in the table but internally fans out to ~4-6 FMP technical endpoints via its own `ThreadPoolExecutor`. Total network calls per invocation: ~12-16.

---

## Implementation Steps

### Step 0: `fmp/tools/_helpers.py` (new shared helpers)

Move `_last_trading_day()` from `fmp/tools/market.py` into `fmp/tools/_helpers.py`. Update `market.py` to import from `_helpers`. This avoids cross-module private imports.

### Step 1: `fmp/tools/stock_fundamentals.py` (new file)

**Function:**
```python
def get_stock_fundamentals(
    symbol: str,
    include: list[str] | None = None,
    format: Literal["full", "summary"] = "summary",
) -> dict:
```

**Available sections:** `profile`, `quote`, `valuation`, `profitability`, `balance_sheet`, `quality`, `technicals`, `chart` (full only)

**Internal section builders** (each returns `(section_dict | None, warnings_list)`):
- `_build_profile(profile_data)` — company name, sector, industry, exchange from FMP profile
- `_build_quote(quote_data)` — price, change, change%, market cap, volume, eps from FMP quote endpoint
- `_build_valuation(ratios, key_metrics, forward_pe_result, sector_pe)` — merges TTM + forward + sector. Filters sector_avg_pe to finite positive only.
- `_build_profitability(ratios, key_metrics)` — ROE (with fallback: `returnOnEquity` if `returnOnEquityTTM` missing), ROIC, margins
- `_build_balance_sheet(ratios, key_metrics)` — leverage metrics
- `_build_quality(income_stmts, cashflow_stmts, metrics_ttm)` — delegates to `compute_quality_signals()`
- `_build_technicals(tech_result)` — extracts signal summary from `get_technical_analysis()` response. Passes through enum values directly (no remapping).
- `_build_chart(chart_df)` — converts DataFrame to date/price/volume list. Zero-fills missing volume.

**Failure semantics**: Every section builder catches its own exceptions. Failed sections → `None` + warning string. The tool always returns `status: "success"` unless the symbol is empty/invalid. All-sections-failed is still `status: "success"` with empty data + warnings (matches `enrich_stock_data()` behavior).

**Reused helpers:**
- `compute_forward_pe()` from `utils/fmp_helpers.py`
- `_get_last_reported_fiscal_date()` from `utils/fmp_helpers.py`
- `compute_quality_signals()` from `fmp/quality_signals.py`
- `get_technical_analysis()` from `fmp/tools/technical.py` (internal call, not MCP)
- `parse_fmp_float()` from `utils/fmp_helpers.py`
- `_last_trading_day()` from `fmp/tools/_helpers.py`

**Patterns to follow:** `fmp/tools/peers.py` (ThreadPoolExecutor, stdout redirect, error handling, FMPClient usage)

### Step 2: `fmp/server.py`

- Import: `from fmp.tools.stock_fundamentals import get_stock_fundamentals as _get_stock_fundamentals`
- Add tool description to `instructions` string
- Add `@mcp.tool()` wrapper with full docstring (args, returns, examples)
- Parse `include` from comma-separated string via existing pattern

### Step 3: Tests — `tests/mcp_tools/test_stock_fundamentals.py`

Test cases (~18-22):
- Happy path: all sections, summary + full format
- Section filtering: `include=["profile","valuation"]` returns only those
- Partial failure: ratios fail → response has profile+quote, valuation in sections_failed + warning
- All-sections failure: every fetch fails → `status: "success"`, all in sections_failed, all warnings
- Profile failure: still `status: "success"`, profile in sections_failed (not tool-level error)
- Quote failure: other sections still work, quote in sections_failed
- Forward P/E scenarios: positive eps, negative eps, no estimates, missing price
- Sector P/E: match found, no match, endpoint failure, non-finite values filtered
- Technicals: success + failure
- Chart: only in full format, excluded from summary, volume zero-fill
- Chart requested in summary mode: ignored (not in sections_included)
- Invalid symbol: empty/whitespace → `status: "error"`
- Invalid include sections: unrecognized names → warning
- Quality signals integration
- ROE fallback: `returnOnEquityTTM` missing, falls back to `returnOnEquity`

**Mock strategy:**
- Patch `fmp.tools.stock_fundamentals.FMPClient` for direct FMP calls
- Patch `fmp.tools.stock_fundamentals.get_technical_analysis` (imported name) for nested technical calls — this isolates from technical.py's own FMPClient instantiation

---

## File Change Summary

| File | Change |
|------|--------|
| `fmp/tools/_helpers.py` | New — `_last_trading_day()` moved here from market.py |
| `fmp/tools/market.py` | Import `_last_trading_day` from `_helpers` instead of defining locally |
| `fmp/tools/stock_fundamentals.py` | New — core tool implementation (~350-450 lines) |
| `fmp/server.py` | Add import + `@mcp.tool()` wrapper + instructions update |
| `tests/mcp_tools/test_stock_fundamentals.py` | New — 18-22 test cases |

---

## Verification

1. **Unit tests**: `pytest tests/mcp_tools/test_stock_fundamentals.py -x -q`
2. **Market tests**: `pytest tests/mcp_tools/test_market.py -x -q` — verify `_last_trading_day` refactor didn't break
3. **Full suite**: `pytest -x -q` — no regressions
4. **Live MCP test**: Restart fmp-mcp server, call `get_stock_fundamentals(symbol="AAPL")` via Claude
5. **Section filtering**: `get_stock_fundamentals(symbol="AAPL", include=["valuation","quality"])`
6. **Full format**: `get_stock_fundamentals(symbol="AAPL", format="full")` — verify chart data present
7. **Fallback ticker**: Try a small-cap with no analyst estimates — verify forward P/E falls back to TTM

# Plan: Trading Analysis MCP Tool

**Status:** COMPLETE

## Context
`TradingAnalyzer.run_full_analysis()` produces comprehensive trade analytics (P&L scorecard, timing, behavioral patterns, income, grades) but is only accessible via CLI (`run_trading_analysis.py`). We want to expose it as an MCP tool. First, we'll standardize `FullAnalysisResult` with serialization methods matching the result object pattern used throughout the codebase (`to_api_response()`, `to_summary()`, `to_cli_report()`).

## Step 1: Add serialization methods to `FullAnalysisResult`

**File:** `trading_analysis/models.py`

Add three methods to `FullAnalysisResult`:

### `to_api_response(meta: Optional[dict] = None) -> dict`
Full structured dict with all sections. Port the serialization logic from `run_trading_analysis.py:_results_to_dict()` (lines 28-167). Includes:
- `generated_at` (ISO timestamp)
- `summary`: total_trading_pnl, total_pnl_by_currency, win_rate, avg_win_score, avg_timing_score, total_regret, conviction_aligned, grades
- `realized_performance`: win/loss counts, net_pnl, profit_factor, expectancy, by_currency
- `trade_scorecard`: list of per-trade dicts (via `TradeResult.to_dict()`)
- `timing_analysis`: list of per-trade timing dicts (via `TimingResult.to_dict()`)
- `income_analysis`: totals, by_year, top 10 by_symbol
- `behavioral_analysis`: averaging_down_success_rate, position sizing stats, top 5 high_activity_days
- `return_statistics`: all % and $ stats, skewness, kurtosis
- `return_distribution`: buckets with range_label, count, frequency, cumulative_frequency
- `meta` (optional): preserved from caller for CLI backward compat (user_email, source, provider counts, incomplete count)

### `to_summary() -> dict`
Condensed view for MCP summary format:
- `total_trades`, `total_trading_pnl`, `total_pnl_by_currency`, `win_rate`, `avg_win_score`, `avg_timing_score`
- `grades`: all 5 grades (conviction, timing, position_sizing, averaging_down, overall)
- `top_winners`: top 5 trades by pnl_dollars (symbol, pnl_dollars, pnl_percent, direction)
- `top_losers`: bottom 5 trades by pnl_dollars (same fields)
- `realized_performance`: condensed (net_pnl, profit_factor, expectancy, win_percent)

### `to_cli_report() -> str`
Human-readable text report. Consolidate `_print_*()` helpers from `run_trading_analysis.py` (lines 179-451) into a single string builder.

**Full section parity checklist** (all sections from current CLI, EXCLUDING summary header which stays in CLI):
- Top winners (top 5 by pnl_dollars)
- Top losers (bottom 5 by pnl_dollars)
- Grades (conviction, timing, position sizing, averaging down, overall)
- Metrics (avg win score, avg timing score, total regret)
- Conviction analysis (high/low conviction win rates, alignment)
- Trade statistics (winner/loser counts, avg winner/loser, grade distribution)
- Realized performance (win/loss counts, totals, ratios, expectancy, by currency)
- Return statistics (% and $ table with avg, median, std dev, best, worst, skewness, kurtosis)
- Return distribution (bucket table with range, count, freq, cumul freq)
- Timing analysis (top 5 by regret, filtered: skip regret > $100k treasury artifacts)
- Income analysis (dividends, interest, monthly rate, projected annual, by year, top 5 sources)
- Behavioral analysis (averaging down success, position sizing stats, top 3 high activity days)

**Note:** There is NO `summary_only` flag. The `to_cli_report()` method always emits all analysis sections. The CLI's `--summary` mode is handled by the CLI itself: it prints `_print_summary()` (the context header) and then simply does NOT call `to_cli_report()`. This matches current behavior where `--summary` only shows the header.

**Note:** The `--incomplete` flag in the CLI requires data from `FIFOMatcher` (incomplete trades), which is separate from `FullAnalysisResult`. The CLI will continue to handle `--incomplete` separately — it is NOT part of `to_cli_report()`.

### `to_dict()` on nested types
Add `to_dict()` to all nested types used in serialization:
- `TradeResult.to_dict()` — symbol, name, currency, direction, dates, prices, pnl, win_score, grade, status
- `TimingResult.to_dict()` — symbol, timing_score, regret_dollars, actual/best/worst pnl
- `RealizedPerformanceSummary.to_dict()` — all win/loss stats, ratios, by_currency
- `ReturnStatistics.to_dict()` — all % and $ stats, skewness, kurtosis
- `ReturnDistribution.to_dict()` — total_trades, min/max_return, buckets list
- `ReturnBucket.to_dict()` — range_label, count, frequency, cumulative_frequency
- `IncomeAnalysis.to_dict()` — totals, monthly rate, projected annual, by_year, top 10 by_symbol
- `BehavioralAnalysis.to_dict()` — success rate, sizing stats, top 5 high activity days

### CLI refactor
Update `run_trading_analysis.py` to use the new methods:
- `--output` JSON mode: `results.to_api_response(meta=meta)` (preserves existing `meta` dict with user_email, source, provider counts, incomplete count). Console report output ALSO still prints (current behavior: CLI prints report AND writes JSON when `--output` is provided).
- Default mode: CLI prints its own summary header (user, source, provider counts, incomplete count — this is CLI-specific context NOT available to `FullAnalysisResult`), then `print(results.to_cli_report())`
- `--summary` mode: CLI prints its own summary header ONLY (does NOT call `to_cli_report()`)
- `--incomplete` mode: stays as-is (prints incomplete trades from FIFOMatcher separately)

**Important: `_print_summary()` stays in the CLI.** It contains CLI-specific context (user email, source name, provider counts, incomplete count) that `FullAnalysisResult` does not and should not have. The `to_cli_report()` method starts AFTER the summary header — it covers grades, metrics, trade statistics, and all analysis sections. The summary header is the CLI's responsibility.

Remove the now-redundant helpers from the CLI: `_results_to_dict()`, `_realized_performance_to_dict()`, `_return_statistics_to_dict()`, `_return_distribution_to_dict()`, and all `_print_*()` functions EXCEPT `_print_summary()` and `_print_incomplete_trades()` which stay in the CLI. Also keep `_format_currency()` and `_compute_pnl_by_currency()` since `_print_summary()` uses them.

## Step 2: Create MCP tool

**New file:** `mcp_tools/trading_analysis.py` (NOT `trading.py` — that file already exists with trade execution tools)

```python
def get_trading_analysis(
    user_email: Optional[str] = None,
    source: Literal["all", "snaptrade", "plaid", "ibkr_flex"] = "all",
    format: Literal["full", "summary", "report"] = "summary",
) -> dict:
```

**Flow:**
1. Resolve user via `get_default_user()` — error if no user
2. Fetch transactions via `fetch_transactions_for_source(user_email, source)`
3. Guard: count total transactions, return `{"status": "error", "error": "No transaction data found for source '{source}'"}` if zero
4. Run `TradingAnalyzer(...).run_full_analysis()`
5. Format dispatch:
   - `summary` → `{"status": "success", **results.to_summary()}`
   - `full` → `{"status": "success", **results.to_api_response()}`
   - `report` → `{"status": "success", "report": results.to_cli_report()}`

Follows existing patterns: stdout→stderr redirect, try/except returning `{"status": "error", "error": str(e)}`, `get_default_user()` for user resolution.

**Edit:** `mcp_server.py` — Import from `mcp_tools.trading_analysis` and register `@mcp.tool()` wrapper.

## Step 3: Tests

**New file:** `tests/mcp_tools/test_trading_analysis.py`
- Build a small fixture with known trades (2 buys, 2 sells, 1 dividend) that produce deterministic results
- Test `summary` format: returns `status=success`, has `grades`, `top_winners`, `total_trades`, etc.
- Test `full` format: returns all sections (`trade_scorecard`, `timing_analysis`, `income_analysis`, etc.)
- Test `report` format: returns `status=success` with string `report` key
- Test no-transactions error: mock returns empty data → `status=error`
- Test tool registration: verify `get_trading_analysis` is registered in `mcp_server.py` imports

**New file:** `tests/trading_analysis/test_result_serialization.py`
- Create `FullAnalysisResult` with known fixture data
- Test `to_api_response()`: verify top-level keys, `summary` sub-keys, `trade_scorecard` list structure, `meta` passthrough
- Test `to_summary()`: verify keys, top_winners/losers length, grades dict
- Test `to_cli_report()`: verify contains section headers ("GRADES", "REALIZED PERFORMANCE", "TIMING ANALYSIS", "INCOME ANALYSIS", "BEHAVIORAL ANALYSIS")
- Test `TradeResult.to_dict()`, `TimingResult.to_dict()` etc. for key presence and rounding
- Test JSON output parity: `to_api_response()` keys match the old `_results_to_dict()` contract

## Files to modify
| Action | File | Changes |
|--------|------|---------|
| Edit | `trading_analysis/models.py` | Add `to_api_response()`, `to_summary()`, `to_cli_report()` to `FullAnalysisResult`; add `to_dict()` on all nested types |
| Edit | `run_trading_analysis.py` | Use new serialization methods, remove redundant helpers (keep `_print_summary`, `_print_incomplete_trades`, `_format_currency`, `_compute_pnl_by_currency`) |
| New | `mcp_tools/trading_analysis.py` | MCP tool implementation |
| Edit | `mcp_server.py` | Register `get_trading_analysis` tool |
| New | `tests/mcp_tools/test_trading_analysis.py` | MCP tool tests |
| New | `tests/trading_analysis/test_result_serialization.py` | Serialization + parity tests |

## Key files to reference
- `trading_analysis/models.py` — `FullAnalysisResult` and nested dataclasses (lines 253-476)
- `trading_analysis/analyzer.py` — `TradingAnalyzer.run_full_analysis()` (line 1395)
- `trading_analysis/data_fetcher.py` — `fetch_transactions_for_source()`
- `run_trading_analysis.py` — Existing serialization helpers (lines 28-167) and print helpers (lines 179-451)
- `mcp_tools/performance.py` — Reference MCP tool pattern (stdout redirect, format dispatch, error handling)
- `mcp_tools/trading.py` — Existing trade execution tools (DO NOT modify)
- `mcp_server.py` — Tool registration pattern
- `core/result_objects.py` — `to_api_response()`/`to_cli_report()` pattern reference

## Verification
1. `python -m pytest tests/trading_analysis/test_result_serialization.py -v`
2. `python -m pytest tests/mcp_tools/test_trading_analysis.py -v`
3. `python run_trading_analysis.py --summary` — verify CLI still works
4. `python run_trading_analysis.py --output /tmp/test.json` — verify JSON output preserves meta and all keys
5. `python -m pytest tests/ -k trading --no-header -q` — verify no regressions in existing trading tests

## Codex Review Log

### Round 1 feedback (7 items)
1. **HIGH — File collision**: `mcp_tools/trading.py` already exists → **Fixed**: renamed to `mcp_tools/trading_analysis.py`
2. **HIGH — CLI behavior regression**: `--summary` and default modes collapsed → **Fixed**: `to_cli_report(summary_only=True)` param preserves separate behavior; `--incomplete` stays as separate CLI-only path
3. **HIGH — JSON meta loss**: `to_api_response()` didn't preserve meta → **Fixed**: added `meta` param to `to_api_response(meta=None)`; CLI passes context dict
4. **MED — No-transactions guard**: MCP tool had no empty-data check → **Fixed**: explicit count guard with descriptive error payload in Step 2
5. **MED — Section parity unclear**: `to_cli_report()` omitted sections → **Fixed**: added full parity checklist including conviction analysis, return distribution, timing regret filter (>$100k)
6. **MED — Tests too light**: Missing parity/registration tests → **Fixed**: added JSON parity test, CLI mode tests, tool registration check
7. **LOW — Incomplete nested to_dict()**: Missing some types → **Fixed**: expanded to all 8 nested types including ReturnBucket, IncomeAnalysis, BehavioralAnalysis

### Round 2 feedback (2 items)
1. **HIGH — CLI parity risk from `_print_summary` removal**: Summary header has CLI-only context (user, source, provider counts) → **Fixed**: `_print_summary()` stays in CLI. `to_cli_report()` covers everything AFTER the summary header. Clean separation: CLI owns context header, model owns analysis report.
2. **LOW — `--output` behavior ambiguity**: Unclear if console output still prints alongside JSON write → **Fixed**: clarified that both print and write happen (matching current behavior).

### Round 3 feedback (3 items)
1. **HIGH — `summary_only` contradicts "CLI owns header"**: `to_cli_report(summary_only=True)` would re-emit the summary header from model → **Fixed**: removed `summary_only` param entirely. CLI `--summary` mode just prints `_print_summary()` and does NOT call `to_cli_report()`. `to_cli_report()` always emits all analysis sections.
2. **MED — Helper removal conflicts**: Plan removed `_format_currency()` and `_compute_pnl_by_currency()` but `_print_summary()` uses them → **Fixed**: explicitly kept both helpers in the CLI.
3. **LOW — File-change table inconsistent**: Didn't mention keeping `_print_summary()` → **Fixed**: table now lists all kept helpers.

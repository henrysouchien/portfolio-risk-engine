# Trading Analysis: Date Range Parameters

## Context

`get_trading_analysis()` currently analyzes ALL available transaction history with no date scoping. Users may want to analyze only a specific period (e.g., "how did my trades perform in 2025?" or "show me just this quarter's activity"). The `get_performance()` MCP tool already supports `start_date`/`end_date` — this adds the same to trading analysis.

**Critical constraint**: FIFO lot matching requires the full chronological transaction sequence. If you remove early buys, later sells become "orphaned" and produce incorrect P&L. Date filtering must happen **post-analysis on the output**, not on the FIFO input.

## Approach

1. Add `start_date` and `end_date` optional params to `get_trading_analysis()`
2. Run the full FIFO analysis unchanged (all transactions, all lot matching)
3. Filter `FullAnalysisResult` output objects by date after analysis
4. Re-compute aggregate metrics (win_rate, total_pnl, timing scores) on the filtered set

## Implementation

### 1. Add params to MCP tool (`mcp_tools/trading_analysis.py`)

Add to `get_trading_analysis()` signature:
```python
def get_trading_analysis(
    ...existing params...,
    start_date: Optional[str] = None,   # YYYY-MM-DD
    end_date: Optional[str] = None,     # YYYY-MM-DD
) -> dict:
```

Validate dates using `pd.Timestamp()` (same pattern as `mcp_tools/performance.py:673-690`). Include explicit `start_date <= end_date` ordering check — raise `ValueError` if inverted.

### 2. `filter_by_date_range()` on `FullAnalysisResult` (`trading_analysis/models.py`)

Add a method to filter results in-place after `run_full_analysis()` completes.

**What to filter by date:**

| Object | Date field | Filter logic |
|--------|-----------|--------------|
| `TradeResult` | `exit_date` (str, YYYY-MM-DD) | Include if exit_date falls within [start_date, end_date]. For OPEN/PARTIAL trades (no exit), include if `entry_date` is within window. |
| `TimingResult` | `sell_date` (str, YYYY-MM-DD) | Include if sell_date falls within window |
| `ConvictionResult` | (no date) | Filter to match remaining trade symbols |

**What NOT to filter:**
- `analyzer.fifo_transactions` — FIFO input must stay complete

**Date matching helpers:**
```python
def _date_in_range(date_str: str, start: str | None, end: str | None) -> bool:
    if not date_str:
        return True  # keep trades with no date
    if start and date_str < start:
        return False
    if end and date_str > end:
        return False
    return True

def _trade_in_range(trade: TradeResult, start: str | None, end: str | None) -> bool:
    ref_date = trade.exit_date if trade.status == "CLOSED" else trade.entry_date
    return _date_in_range(ref_date, start, end)
```

**Aggregate recomputation** after filtering `trade_results` and `timing_results`:

Core trade metrics:
- `total_trading_pnl` — sum of filtered trade P&L
- `win_rate` — wins / closed trades in filtered set
- `avg_win_score` — mean win_score of filtered closed trades

Timing metrics:
- `avg_timing_score` — mean of filtered timing results
- `total_regret` — sum of filtered timing regret

Derived analytics (set to `None` since they can't be cheaply recomputed from filtered trades alone):
- `realized_performance` → `None`
- `return_statistics` → `None`
- `return_distribution` → `None`
- `behavioral_analysis` → `None`
- `conviction_results` → `[]` (currently always empty in analyzer, but clear for consistency)
- `high_conviction_win_rate`, `low_conviction_win_rate` → `0.0`
- `conviction_aligned` → `False`

Grades (set to empty string — grades from partial data would be misleading):
- `timing_grade`, `conviction_grade`, `position_sizing_grade`, `averaging_down_grade`, `overall_grade` → `""`

### 3. Income events pre-filter

Income events (`analyzer.income_events`) don't affect FIFO, so they're safe to pre-filter before `run_full_analysis()`. Filter using `NormalizedIncome.date_str` against the date range. This ensures `income_analysis` in the result reflects only the requested window.

### 4. Wire in MCP tool

In `get_trading_analysis()`:

```python
# Pre-filter income events (safe — doesn't affect FIFO)
if start_date or end_date:
    analyzer.income_events = [
        e for e in analyzer.income_events
        if _date_in_range(e.date_str, start_date, end_date)
    ]

results = analyzer.run_full_analysis()

# Post-filter trade results + recompute aggregates
if start_date or end_date:
    results.filter_by_date_range(start_date, end_date)
```

## Files Modified

| File | Change |
|------|--------|
| `mcp_tools/trading_analysis.py` | Add `start_date`/`end_date` params, date validation, income pre-filter, wire post-filter (~25 lines) |
| `trading_analysis/models.py` | Add `filter_by_date_range()` + `_date_in_range()` + `_trade_in_range()` on `FullAnalysisResult` (~40 lines) |

## What This Does NOT Do

- Does NOT filter FIFO input transactions (would break lot matching)
- Does NOT recompute grades/behavioral/return-stats from filtered set — these are nulled out (grades set to empty string, `realized_performance`/`return_statistics`/`return_distribution`/`behavioral_analysis` set to `None`) since partial-window grades would be misleading
- Does NOT change `get_agent_snapshot()` — it reads from the already-filtered `trade_results` list, so it works automatically

## Verification

1. **Unit test**: `tests/trading_analysis/test_date_filter.py` — test `filter_by_date_range()` directly with known trades, verify filtering and aggregate recomputation
2. **Edge cases**: No dates passed (no-op), only start_date, only end_date, no trades in window (empty), all trades in window (unchanged), OPEN trades (use entry_date)
3. **Live MCP test**: `get_trading_analysis(start_date="2025-06-01", end_date="2025-12-31", format="agent")` — verify only trades within window appear, P&L/win_rate reflect filtered set

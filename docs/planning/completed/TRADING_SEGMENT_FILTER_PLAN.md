# Add `segment` Parameter to `get_trading_analysis()`

## Context

Phase 5 added futures metadata (`instrument_type`, `multiplier`, `contract_quantity`) to all trade objects and a `futures_breakdown` section to the agent snapshot. `get_risk_analysis()` already has a `segment` parameter (Phase 4) for filtering to equities-only or futures-only views. Adding the same to `get_trading_analysis()` lets the agent run futures-specific or equities-specific trading analysis.

## Approach

Filter **before** `run_full_analysis()`, following the existing `institution`/`account` filter pattern in `mcp_tools/trading_analysis.py` (lines 111-141). This means grades, behavioral analysis, and all aggregates naturally reflect only the filtered segment.

The filter operates on `analyzer.fifo_transactions` (which has `instrument_type` field from Phase 5), then derives symbol sets for filtering `analyzer.trades` (which lacks `instrument_type`) and `analyzer.income_events`.

## Changes

### 1. `mcp_tools/trading_analysis.py` — Add segment filter

Add `segment` parameter to function signature (line 61):
```python
def get_trading_analysis(
    ...
    account: Optional[str] = None,
    segment: Literal["all", "equities", "futures"] = "all",  # NEW
    format: ...
```

Add filter block after the existing `account` filter (after line 141, before `if not analyzer.fifo_transactions`):
```python
if segment and segment != "all":
    if segment == "futures":
        keep_txns = [t for t in analyzer.fifo_transactions if t.get("instrument_type") == "futures"]
    else:  # "equities"
        keep_txns = [t for t in analyzer.fifo_transactions if t.get("instrument_type") not in ("futures",)]

    keep_symbols = {t.get("symbol") for t in keep_txns}
    analyzer.fifo_transactions = keep_txns
    # NormalizedTrade doesn't have instrument_type — filter by symbol
    analyzer.trades = [t for t in analyzer.trades if t.symbol in keep_symbols]
    analyzer.income_events = [e for e in analyzer.income_events if e.symbol in keep_symbols]
```

### 2. `mcp_server.py` — Register new parameter

Add `segment` parameter to the MCP wrapper function (line 472) and pass through to `_get_trading_analysis()` (line 510). Update docstring with segment options and examples.

## Files Changed

| File | Change |
|------|--------|
| `mcp_tools/trading_analysis.py` | Add `segment` param + pre-analysis filter block |
| `mcp_server.py` | Add `segment` param to MCP wrapper, pass through, update docstring |

## Tests

1. **Segment=futures** — Mock fifo_transactions with mix of futures + equity `instrument_type`, verify only futures trades/transactions remain after filter
2. **Segment=equities** — Same mock, verify futures excluded, equities + options retained
3. **Segment=all (default)** — No filtering applied
4. **Income filtered by segment symbols** — Equity dividends excluded when segment=futures
5. **Empty after filter** — segment=futures with no futures transactions → error message

## Verification

1. `python3 -m pytest tests/ -x -q` — all tests pass
2. `/mcp` reconnect
3. `get_trading_analysis(source="ibkr_flex", segment="futures", format="agent")` — only MGC/MHI trades
4. `get_trading_analysis(source="ibkr_flex", segment="equities", format="agent")` — excludes MGC/MHI

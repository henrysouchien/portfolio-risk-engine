# Bug: Portfolio Performance Fails on London-Listed Stocks

**Date:** 2026-02-11
**Component:** portfolio-mcp / get_performance
**Severity:** Medium

## Summary

`get_performance()` fails when the portfolio contains London-listed stocks (e.g., AT.L). The FMP historical price lookup appends an extra `.L`, producing an invalid symbol.

## Error

```
Performance analysis failed: Error during performance analysis:
FMP returned empty data for endpoint 'historical_price_eod' (symbol: AT.L.L)
```

## Root Cause

The system appears to append `.L` to the ticker assuming it needs a London exchange suffix, but the ticker is already stored as `AT.L` — resulting in the double-suffixed `AT.L.L`.

## Additional Issues

- `get_positions(format="monitor")` returns `current_price: 0` and `pnl_percent: -100%` for AT.L, suggesting the price lookup also fails in the positions flow (but silently, rather than crashing).

## Expected Behavior

- London-listed tickers (*.L) should be handled correctly in both price lookups and performance analysis.
- If a single position's price is unavailable, performance analysis should degrade gracefully (exclude or flag it) rather than failing entirely.

## Repro

```
get_performance(format="report", benchmark_ticker="SPY")
```

With AT.L (Ashtead Technology, 400 shares) in the portfolio.

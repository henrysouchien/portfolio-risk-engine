# Bug: Realized Mode Report Missing Benchmark Comparison Table

**Date:** 2026-02-11
**Component:** portfolio-mcp / get_performance (realized mode)
**Severity:** Low

## Summary

The `get_performance(mode="realized")` report does not include a side-by-side benchmark comparison table, unlike the `mode="hypothetical"` report which shows portfolio vs benchmark return, volatility, and Sharpe.

## Current Behavior

Realized mode report only shows:
- Alpha (annual): 23.17%
- Beta: 0.495

No SPY return, volatility, or Sharpe displayed for comparison.

## Expected Behavior

Should include the same comparison table as hypothetical mode:

```
📊 PORTFOLIO vs SPY COMPARISON
────────────────────────────────────────
Metric               Portfolio    Benchmark
────────────────────────────────────────
Return                  34.44%       XX.XX%
Volatility              30.06%       XX.XX%
Sharpe Ratio            0.989        X.XXX
```

## Repro

```python
get_performance(format="report", benchmark_ticker="SPY", mode="realized")
```

Compare output to:

```python
get_performance(format="report", benchmark_ticker="SPY", mode="hypothetical")
```

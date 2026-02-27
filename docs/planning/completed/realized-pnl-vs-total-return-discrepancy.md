# Bug: Realized P&L vs Total Return Discrepancy

**Date:** 2026-02-11
**Component:** portfolio-mcp / get_performance (realized mode)
**Severity:** Medium

## Summary

Realized mode reports a +174.9% total return (34.4% annualized) but both realized and unrealized P&L are negative. These numbers are inconsistent and suggest a data or calculation issue.

## Details

From `get_performance(mode="realized")`:

| Metric | Value |
|--------|-------|
| Total Return | +174.87% |
| Annualized Return | +34.44% |
| Realized P&L | -$17,157 |
| Unrealized P&L | -$26,564 |
| Income | +$11,046 |
| Data Coverage | 70.83% |

## Possible Causes

1. **Missing transaction data** — 71% coverage means ~29% of transactions are unaccounted for. Winning trades may be missing from the P&L calculation but reflected in the return calculation (or vice versa).
2. **Return vs P&L calculated differently** — total return may use a time-weighted or IRR approach on portfolio NAV, while P&L is a simple sum of trade-level gains/losses. If the two methods pull from different data sources, they can diverge.
3. **Dividend reinvestment / cash flow handling** — income of $11k helps but doesn't close the gap between negative P&L and +175% return.

## Investigation Steps

- [ ] Check which transactions are missing from the 29% uncovered
- [ ] Compare the data sources used for total return vs P&L calculations
- [ ] Verify how cash deposits/withdrawals are handled in the return calc
- [ ] Check if the return calculation is using portfolio NAV snapshots vs transaction-level P&L

## Repro

```python
get_performance(format="report", benchmark_ticker="SPY", mode="realized")
```

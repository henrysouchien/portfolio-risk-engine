# Bug: Realized Return Inflated by Synthetic Positions and First-Month Formula

**Date:** 2026-02-11
**Component:** portfolio-mcp / realized_performance_analysis.py
**Severity:** High

## Summary

`get_performance(mode="realized")` reports +90.5% total return while dollar P&L sums to -$33k. The discrepancy is caused by three interacting issues in the return calculation.

## Issue 1: First-Month Return Formula (Lines 546-574)

When `v_start = 0` (always true for month 1), the return is calculated as:

```python
return = (V_end - Flow_net) / Flow_weighted  # line 561
```

`Flow_weighted` is a time-weighted fraction of the actual capital contributed. If an injection happens mid-month, the denominator is only half the real contribution, inflating the return. Should use `Flow_net` as denominator instead.

**File:** `core/realized_performance_analysis.py:546-574`

## Issue 2: Synthetic Positions Inflate Returns but Not P&L

With 71% transaction coverage, the system creates synthetic opening positions at inception (lines 218-247) and generates pseudo-buy transactions via `_create_synthetic_cash_events()` (lines 296-349).

- **Return calculation** includes these synthetics in NAV → inflated growth
- **FIFO P&L** only uses actual transactions → incomplete, shows losses

The two calculations operate on different data sets, so they diverge.

**File:** `core/realized_performance_analysis.py:218-247, 296-349`

## Issue 3: Inferred Cash Injections Compound the Problem

`derive_cash_and_external_flows()` (lines 352-432) infers capital injections whenever cash goes negative. Synthetic positions generate large pseudo-buys, which trigger large inferred injections, which then get time-weighted in the first-month formula — amplifying Issue 1.

**File:** `core/realized_performance_analysis.py:352-432`

## How They Combine

1. 71% coverage → 29% missing history
2. System creates synthetic opening positions to fill gaps
3. `_create_synthetic_cash_events()` creates pseudo-BUY transactions
4. `derive_cash_and_external_flows()` infers large capital injections from pseudo-buys
5. `compute_monthly_returns()` applies buggy first-month formula with time-weighted denominator
6. Result: **+90.5% return** from NAV that includes synthetics
7. Meanwhile FIFO P&L only sees actual trades → **-$33k**

## Issue 4: FIFO P&L Corrupted by Missing Opening Lots

When positions lack opening BUY transactions, the FIFO matcher either:
- Records sells as **incomplete trades** (18 found) — their P&L is lost entirely
- Matches exits against wrong lots, producing incorrect realized P&L

**Evidence from live data:**

The FIFO matcher produced 18 incomplete trades (sells with no matching buy):
- `AT.` (300 shares sold) — ticker mismatch (`AT.` vs `AT.L`)
- `GLBE` (90 shares sold + 47 short) — partial history
- `NMM`, `SE`, `VBNK`, `CUBI`, `MES` — buys outside lookback window
- `PCTY_C180_250221` (2 contracts) — options with no opening lot

Meanwhile, the biggest realized loss is `MHI` (Hang Seng Mini Futures) at **-$30,664** from a single trade — but there's also a +$9,136 MHI winner. Without complete lot history, the FIFO pairing may be incorrect.

**Result:** The -$17,157 realized P&L is unreliable. It's not that the portfolio actually lost money on trades — it's that missing opening lots cause sells to either vanish (incomplete) or match incorrectly.

**File:** `trading_analysis/fifo_matcher.py` (process_transactions, _process_exit)

## Issue 5: Low Data Coverage Root Causes

Coverage is 70.83% (17/24 positions). The 7 uncovered positions and why:

| Position | Root Cause |
|----------|-----------|
| AT.L | Ticker mismatch — IBKR Flex stores as `AT.`, positions show `AT.L` |
| CPPMF | No BUY in any provider (Plaid/SnapTrade/IBKR Flex) |
| IGIC | No BUY in any provider |
| KINS | No BUY in any provider |
| NVDA | No BUY in any provider |
| TKO | No BUY in any provider |
| V | No BUY in any provider |

CPPMF, IGIC, KINS, NVDA, TKO, V were likely purchased before all lookback windows (Plaid 2yr, SnapTrade 5yr) or transferred in from another account.

**Additional finding:** IBKR Flex credentials had an import-order bug where `settings.py` read `os.getenv()` at import time before `load_dotenv()` ran. Fixed by reading env vars at call time in `data_fetcher.py:47-65`.

## Suggested Fixes

1. **First-month formula**: Use `Flow_net` as denominator when `v_start = 0`, not `Flow_weighted`
2. **Synthetic positions**: Either exclude synthetics from return calculation, or flag returns as "estimated" when coverage < 100%
3. **Reconciliation check**: Add a sanity check that compares dollar P&L direction with return direction — warn if they disagree
4. **Coverage threshold**: Consider refusing to compute returns when coverage is below a minimum (e.g., 85%)
5. **Ticker normalization**: Normalize IBKR Flex symbols to match position symbols (e.g., `AT.` → `AT.L` for London-listed)
6. **CSV backfill**: Use existing `load_and_merge_backfill()` in `fifo_matcher.py` to import older transactions for the 6 positions with no history
7. **Dual-track P&L** (Codex proposal): Report both NAV-basis `official_pnl_usd` and FIFO `lot_pnl_usd` with explicit `reconciliation_gap_usd` so the discrepancy is transparent

## Repro

```python
get_performance(format="report", benchmark_ticker="SPY", mode="realized")
```

## Key Code References

| Component | File | Lines |
|-----------|------|-------|
| First-month formula | `core/realized_performance_analysis.py` | 546-574 |
| Synthetic positions | `core/realized_performance_analysis.py` | 218-247 |
| Synthetic cash events | `core/realized_performance_analysis.py` | 296-349 |
| Cash flow inference | `core/realized_performance_analysis.py` | 352-432 |
| Return vs P&L separation | `core/realized_performance_analysis.py` | 1009-1070 |

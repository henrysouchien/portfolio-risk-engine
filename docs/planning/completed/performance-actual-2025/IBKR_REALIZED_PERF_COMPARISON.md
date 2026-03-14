# IBKR Realized Performance: Engine vs Statement Comparison

**Date**: 2026-03-08 (updated)
**Account**: U2471778
**Statement Period**: Apr 1, 2025 – Mar 3, 2026 (U2471778_20250401_20260303)
**Engine Run**: `get_performance(mode="realized", source="ibkr_flex", start_date="2025-04-01")`

## Period-Matched Reconciliation (Mar 8)

### 1. Income — MATCHED

Engine reports all-time FIFO income. Period-matching requires removing
pre-window (Mar 2025: CBL $120 + TKO $4.56 = $124.56 dividends) and
post-window (Mar 4+: $31.44 interest) amounts. Engine correctly FX-converts
HKD/GBP interest to USD.

| Item | Engine (period-adj) | IBKR Statement | Gap |
|------|---------------------|----------------|-----|
| Dividends | +$182.41 | +$182.41 | **$0.00** |
| Interest | -$261.82 | -$261.84 | **$0.02** |
| **Income Total** | **-$79.41** | **-$79.43** | **$0.02** |

### 2. Fees & Commissions

| Item | Engine | IBKR Statement | Gap |
|------|--------|----------------|-----|
| Other Fees (data/snapshot) | -$174.03 | -$164.00 | -$10.03 |
| Commissions | in trade fees | -$61.99 | n/a |
| Transaction Fees (stamp tax) | in trade fees | -$11.04 | n/a |

Engine folds commissions + stamp tax into per-trade `fee` field (captured in
cost basis). Other fees gap of $10.03 is likely the pre-period Mar 2025 PNP
charge (-$0.03) and Mar 2026 charges straddling period boundary.

### 3. Lot P&L — Period Mismatch

Engine lot P&L is **all-time FIFO** (not windowed to statement period).
Key mismatch: SLV stock sold Mar 4 (1 day AFTER statement end).

| Item | Engine (all-time) | IBKR (Apr 1–Mar 3) | Gap |
|------|-------------------|---------------------|-----|
| Realized P&L | -$5,172 | -$7,978 | +$2,806 |
| Unrealized P&L | +$2,347 | +$6,086 | -$3,739 |
| **Lot Total** | **-$2,825** | **-$1,892** | **-$933** |

**SLV period mismatch** (biggest single factor):
- Engine: SLV sold Mar 4 → +$3,476 in realized
- IBKR: SLV open at Mar 3 → +$4,289 in unrealized
- After adjusting SLV realized→unrealized: realized gap narrows to -$671, unrealized gap to +$551

**IBKR Realized P&L by Category:**

| Category | IBKR | Engine (est.) | Gap | Notes |
|----------|------|---------------|-----|-------|
| Stocks | -$2,129 | incomplete | — | 19 symbols, many are incomplete trades |
| Options | -$1,562 | incomplete | — | NMM, PDD, NXT, SLV, PLTR options |
| Futures | -$4,294 | -$3,596 (MTM) | +$698 | MGC, MHI, ZF via cash replay |
| Forex | +$8 | not tracked | — | GBP, HKD minor amounts |
| **TOTAL** | **-$7,978** | **-$5,172** | **+$2,806** | |

### 4. NAV Change

| Item | Engine | IBKR Statement | Gap |
|------|--------|----------------|-----|
| Starting Cash | -$15,093 | -$11,097 | -$3,996 |
| Ending Cash (observed) | -$8,727 | -$8,727 | $0 |
| NAV P&L (synth-enhanced) | +$7,890 | +$65 | +$7,825 |
| NAV P&L (observed-only) | +$5,158 | +$65 | +$5,093 |
| Synthetic impact | +$2,732 | — | — |
| Cash start gap effect | ~$3,996 | — | — |
| **NAV adj for cash gap** | **+$1,162** | **+$65** | **+$1,097** |

IBKR NAV waterfall: Starting $22,284 + MTM +$328 + Dividends +$182 +
Interest -$262 + Accruals +$54 + Fees -$164 + Commissions -$62 +
Stamp Tax -$11 + FX +$0.11 = Ending $22,349 (change +$65).

### 5. TWR

| Metric | Engine | IBKR Statement | Gap |
|--------|--------|----------------|-----|
| TWR | -1.19% | +0.29% | -1.48 pp |
| Period | Apr 30 – Feb 28 | Apr 1 – Mar 3 | 3-day gap |
| Method | Month-end returns | Daily compounding | — |
| April return | -41.42% | n/a (not broken out) | — |

## What Matches

- **Dividends**: $182.41 exact match (period-adjusted)
- **Interest**: within $0.02 (FX rounding)
- **Ending cash**: -$8,727 matched
- **Unpriceable symbols**: 0 (AT.L fixed)
- **All positions priced**: IBKR PriorPeriodPosition for options
- **Futures MTM**: -$3,596 (engine) vs -$4,294 (IBKR) — directionally correct, $698 gap
  from open position margin inference suppression

## True Remaining Gaps

### Gap 1: Starting Cash (-$3,996)
**Engine**: -$15,093. **IBKR**: -$11,097.
**Root cause**: 19 synthetic opening positions add phantom cash outflows
to the back-solve. The back-solve correctly solves for
`starting_cash = ending_cash - sum(all_cash_flows)`, but the synthetic
positions inflate the outflow side by ~$4k.

### Gap 2: NAV P&L (+$5,093 observed, +$1,097 after cash adjustment)
**Engine**: +$5,158 (observed-only). **IBKR**: +$65.
After correcting for the $3,996 cash start error, residual gap is ~$1,097.
This comes from synthetic position mark-to-market changes during the period
(6 synthetic current positions valued at $15,112 contribute unrealized
gains/losses that IBKR doesn't see).

### Gap 3: Lot P&L (+$2,806)
**Engine**: -$5,172. **IBKR**: -$7,978.
Contributors:
- **SLV exercise/assignment** (~$3,342): Engine FIFO assigns $30/share cost
  (strike price). IBKR includes option premium in exercise cost basis,
  giving ~$31.79/share. Over 100 shares, this is ~$179 difference.
  Additionally, IBKR shows $0 realized for SLV stock vs engine's +$3,476.
- **Incomplete trade broker_pnl**: Engine has -$5,800 from `fifoPnlRealized`.
  This captures most of the IBKR realized loss but may miss some
  split-exit trades where broker_pnl was dropped to avoid double-counting.

### Gap 4: TWR (-1.48 pp)
**Engine**: -1.19%. **IBKR**: +0.29%.
The April -41.42% return is the main driver. Synthetic opening positions
valued at inception prices crash when positions are sold in April, creating
a phantom drawdown that doesn't exist in IBKR's NAV.

## Root Cause Summary

All four gaps trace to the same root cause: **19 incomplete trades** (exits
without matching opening buys in the Flex data window). This causes:
1. Synthetic opening positions with estimated values
2. Cash back-solve distortion from phantom outflows
3. April phantom drawdown from synthetic → real transition
4. Lot P&L misalignment from missing cost basis

**Fix**: Statement trade backfill — ingest opening transactions from IBKR
statement SQLite to provide actual buy prices and dates.

**Coverage**: 57.14% (48/84 complete) → target 95%+

## Fixes Applied (Mar 6-8)

### Fix 8: TWR inception fix (commit `2aac7180`)
Two bugs: (1) benchmark pct_change().dropna() dropped inception month,
(2) synthetic TWR flows on inception day produced -64.4% return. Now
inception day = 0% baseline. **Impact**: TWR 53.9% → -1.19%.

### Fix 7: Cross-currency dedup (commit `7b70bcbb`)
`_cross_currency_dedup()` helper uses `fxRateToBase` to cluster
same-event duplicates while preserving distinct HKD interest charges.
Flat $0.10 signed-amount tolerance. **Impact**: Interest -$276 → -$293.

### Fix 6: Extract fifoPnlRealized from Flex (commits `0a3b73fe`, `bd8cb895`)
Extracted IBKR's `fifoPnlRealized` from Flex Trade XML for incomplete trades.
**Impact**: lot P&L +$2,944 → -$2,708, incomplete_pnl = -$5,800.

### Fix 5: Flex taxes + trailing-dot pricing (commit `867b46fd`)
UK Stamp Tax in fee extraction. AT.L pricing fixed.
**Impact**: NAV return 6.95% → 4.58%, coverage 42.9% → 53.9%.

### Fix 4: Broker cost basis extraction (commit `7e259a39`)
`broker_cost_basis` threaded through 4 layers. No NAV impact (price_cache
lookups succeed). Available for future lot-level fixes.

### Fix 3: Segment filter (commit `b3f3c1ff`)
Per-asset-class analysis. Options segment: -2.33%.

### Fix 2: MHI futures contract (commit `63cdc652`)
Added MHI to contracts.yaml and exchange_mappings.yaml.

### Fix 1: Forward price lookup for synthetic positions (commit `5432a4c5`)
NMM_C70/C85 options now use inception-day PriorPeriodPosition marks.

### Additional fixes (parallel sessions, Mar 7-8)
- **FMP ticker position key fix** (commit `af7643f8`): AT→AT.L reconciliation
- **Inception alignment** (commit `2aac7180`): `start_date` → `inception_override`
- **Fee subtotal dedup** (commit `80184915`): Filter Flex SUMMARY rows

## Data Quality Metrics

| Metric | Pre-fix | Post-fix 5 | Post-fix 6 | Current (Mar 8) | Target |
|--------|---------|------------|------------|-----------------|--------|
| Data Coverage | 42.86% | 53.85% | 53.85% | 57.14% | 95% |
| Incomplete Trades | 24 | 24 | 24 | 24 | 0 |
| Incomplete P&L | $0 | $0 | -$5,800 | -$5,800 | — |
| TWR | +53.9% | +4.58% | +2.60% | -1.19% | +0.29% |
| NAV P&L (obs) | +$8,399 | +$7,907 | +$5,158 | +$5,158 | +$65 |
| Lot P&L | +$765 | +$2,944 | -$2,708 | -$2,825 | -$7,978 |
| Unpriceable | 1 (AT.) | 0 | 0 | 0 | 0 |
| Reliable | No | No | No | No | Yes |

## Source Files

- IBKR Statement (raw): `U2471778_20250401_20260303.csv`
- IBKR Parsed Tables: `ibkr_statement_frames/U2471778_20250401_20260303/tables/`
- IBKR Realized/Unrealized: `tables/realized_unrealized_performance_summary__01.csv`
- IBKR MTM Summary: `tables/mark_to_market_performance_summary__01.csv`
- IBKR Trades: `tables/trades__01.csv`, `trades__02.csv`, `trades__03.csv`
- IBKR NAV: `tables/net_asset_value__01.csv`
- IBKR NAV Change: `tables/change_in_nav__01.csv`
- IBKR Dividends: `tables/dividends__01.csv`
- Engine Output (Mar 8): `logs/performance/performance_realized_20260308_135821.json`
- Trading Analysis (Mar 8): `logs/trading/trading_ibkr_flex_20260308_135639.json`

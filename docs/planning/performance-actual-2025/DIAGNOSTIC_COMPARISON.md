# Realized Performance Diagnostic Comparison

_Generated: 2026-02-25 11:05:06_

## 1) System Outputs Captured

- `all`: ok=True, status=success, file=`system_output_all.json`
- `schwab`: ok=True, status=success, file=`system_output_schwab.json`
- `plaid`: ok=True, status=success, file=`system_output_plaid.json`
- `snaptrade`: ok=True, status=success, file=`system_output_snaptrade.json`
- `ibkr_flex`: ok=True, status=success, file=`system_output_ibkr_flex.json`

All calls succeeded (no runtime exceptions).

## 2) Synthetic Position to Broker Mapping (source="all")

| Symbol | Position Source(s) | Broker Classification | In IBKR Open Positions Baseline | System Qty | System Cost Basis (USD) | System Value (USD) |
|---|---|---|---|---:|---:|---:|
| CBL | schwab | schwab | no | 186.2791 | 5792.39 | 6947.28 |
| CPPMF | schwab | schwab | no | 2.0000 | 1.31 | 0.66 |
| EQT | snaptrade | ibkr (via snaptrade positions) | yes | 40.0000 | 2001.00 | 2353.40 |
| GLBE | schwab | schwab | no | 6.0000 | 193.08 | 206.22 |
| IGIC | snaptrade | ibkr (via snaptrade positions) | yes | 100.0000 | 2376.00 | 2523.00 |
| IT | plaid | merrill/plaid | no | 23.0000 | 9657.59 | 3395.49 |
| KINS | snaptrade | ibkr (via snaptrade positions) | yes | 150.0000 | 2196.51 | 2490.00 |
| LIFFF | schwab | schwab | no | 103.0000 | 509.00 | 532.52 |
| MSCI | plaid, schwab | mixed (plaid, schwab) | no | 33.5426 | 16836.23 | 18638.28 |
| NVDA | snaptrade | ibkr (via snaptrade positions) | yes | 25.0000 | 2883.97 | 4904.01 |
| PCTY | schwab | schwab | no | 40.0000 | 6517.74 | 4108.93 |
| TKO | snaptrade | ibkr (via snaptrade positions) | yes | 12.0000 | 2078.20 | 2513.64 |
| V | snaptrade | ibkr (via snaptrade positions) | yes | 3.0000 | 943.54 | 940.26 |

Note: `source` filtering applies to transactions, not holdings; this is explicitly flagged in `data_warnings`, so per-source synthetic lists include cross-source holdings.

## 3) IBKR Cost Basis Comparison (overlap: synthetic + IBKR open positions)

| Symbol | Broker | IBKR Actual Cost Basis (USD) | System Cost Basis (USD) | Delta (System-Actual) |
|---|---|---:|---:|---:|
| EQT | snaptrade | 2001.001400 | 2001.001400 | 0.000000 |
| IGIC | snaptrade | 2376.004800 | 2376.004800 | 0.000000 |
| KINS | snaptrade | 2200.074925 | 2196.505249 | -3.569675 |
| NVDA | snaptrade | 2883.965895 | 2883.965895 | 0.000000 |
| TKO | snaptrade | 2078.200552 | 2078.200552 | -0.000000 |
| V | snaptrade | 943.540105 | 943.540105 | -0.000000 |

Interpretation: IBKR-overlap synthetic symbols are mostly seeded close to broker cost basis; KINS shows a meaningful mismatch (~$3.57).

Method note: `get_performance(..., format="agent"|"full")` does not expose per-position cost-basis rows. System cost basis above is taken from non-consolidated `PositionService.get_all_positions(...)` output in the same runtime, which is the holdings input used by the realized analyzer.

## 4) Per-Account Summary (Actual TWR vs System TWR)

| Institution | Account | Actual Statement Period | Actual TWR % | System Source | System TWR % | Gap (pp) |
|---|---|---|---:|---|---:|---:|
| Charles Schwab | 165 | Jan 1, 2025 -> Dec 31, 2025 | -8.2900 | schwab | 176.1900 | 184.4800 |
| Charles Schwab | 013 | Jan 1, 2025 -> Dec 31, 2025 | -14.6900 | schwab | 176.1900 | 190.8800 |
| Charles Schwab | 252 | Jan 1, 2025 -> Dec 31, 2025 | 10.6500 | schwab | 176.1900 | 165.5400 |
| Merrill Edge | CMA-Edge 42X-71X13 | January 1, 2025 -> January 31, 2026 | -12.4900 | plaid | 8.0000 | 20.4900 |
| Interactive Brokers LLC | U2471778 | December 31, 2024 -> December 31, 2025 | -9.3533 | ibkr_flex | -100.0000 | -90.6467 |

Root-cause summary:
- Schwab: system `source="schwab"` reports +176.19% while statements are mixed and mostly negative because 19 synthetic openings are injected and coverage is only 37.5%.
- Merrill/Plaid: system +8.00% vs statement -12.49%; coverage is 12.5% and almost all holdings are synthetic in this path.
- IBKR Flex: system -100.00% vs statement -9.35%; first-transaction exit gaps and synthetic reconstruction dominate the NAV path (coverage 20.83%).
- Cross-source leakage: warnings confirm source filters scope transactions only; holdings stay consolidated, contaminating per-source realized runs.

## 5) Top Distortion Drivers (Synthetic Notional)

| Rank | Symbol | Broker Classification | System Value (USD) | System Cost Basis (USD) |
|---:|---|---|---:|---:|
| 1 | MSCI | mixed (plaid, schwab) | 18638.28 | 16836.23 |
| 2 | CBL | schwab | 6947.28 | 5792.39 |
| 3 | NVDA | ibkr (via snaptrade positions) | 4904.01 | 2883.97 |
| 4 | PCTY | schwab | 4108.93 | 6517.74 |
| 5 | IT | merrill/plaid | 3395.49 | 9657.59 |

## 6) Sources with Zero Transactions

| Source | Coverage % | Synthetic Count | Transaction Rows | Reason |
|---|---:|---:|---:|---|
| all | 58.33 | 13 | 224 | n/a |
| schwab | 37.50 | 19 | 88 | n/a |
| plaid | 12.50 | 24 | 54 | n/a |
| snaptrade | 0.00 | 24 | 0 | No transaction history found; using 12-month synthetic inception for current holdings. SnapTrade transaction reporting is unavailable for Interactive Brokers (Interactive Brokers (Henry Chien)); account activities returned zero rows. Use provider-native transaction feeds (for example, IBKR Flex for Interactive Brokers) for realized-performance history. |
| ibkr_flex | 20.83 | 19 | 82 | n/a |

Observed result: only `snaptrade` returned 0 transaction rows in this run; warning explicitly states Interactive Brokers via SnapTrade returned zero activities.

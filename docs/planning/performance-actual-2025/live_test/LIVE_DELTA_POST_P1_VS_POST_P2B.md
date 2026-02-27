# Live Delta: Post-P1 vs Post-P2B

- Generated: 2026-02-25T22:19:23.219647+00:00
- Baseline: `post_p1` artifacts
- Candidate: `post_p2b` artifacts

## Source Deltas

| Source | Total Return P1 | Total Return P2B | Delta | Annualized P1 | Annualized P2B | Delta | Futures Notional Suppressed (P2B) | Income Overlap Dropped (P2B) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| all | 83.91 | 188.08 | 104.17 | 41.65 | 83.05 | 41.40 | 518,945.37 | 40.00 |
| ibkr_flex | 126.32 | -68.88 | -195.20 | 166.48 | -75.36 | -241.84 | 519,047.58 | 25.00 |
| schwab | 142.79 | 51.36 | -91.43 | 66.01 | 26.73 | -39.28 | 0.00 | 0.00 |
| plaid | 1.32 | -7.96 | -9.28 | 0.93 | -5.69 | -6.62 | 0.00 | 15.00 |
| snaptrade | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |

## Notes
- `all`: futures fee-only suppression active; income/provider overlap dedupe active
- `ibkr_flex`: futures fee-only suppression active; income/provider overlap dedupe active
- `schwab`: no major metadata status change
- `plaid`: income/provider overlap dedupe active
- `snaptrade`: no major metadata status change

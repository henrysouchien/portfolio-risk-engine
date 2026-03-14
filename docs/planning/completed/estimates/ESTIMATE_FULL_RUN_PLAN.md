# Estimate Collection — First Full Run Plan

## Overview

First production run of the estimate collection system against the full bulk-intersected universe (~4,900 tickers). Running in batches to verify data quality before committing to the full run.

## Batched rollout

| Batch | Command | Tickers | Purpose |
|---|---|---|---|
| 1 | `--universe-limit 100 --force` | 1-100 | Verify inserts, failure tracking, data shape |
| 2 | `--universe-limit 300 --force` | 101-300 | Confirm at scale, check for rate limiting |
| 3 | `--universe-limit 500 --force` | 301-500 | Final spot check |
| 4 | `--force` (no limit) | 501-4,900 | Full remaining universe |

Resume logic handles continuation — each batch picks up from `last_ticker_processed`.

## Verification between batches

After each batch, check:
1. `SELECT count(*) FROM estimate_snapshots;` — row count growing as expected
2. `SELECT ticker, period, error_type FROM collection_failures ORDER BY ticker;` — failures are reasonable
3. Spot check a ticker: `get_estimate_revisions(ticker="AAPL")` via MCP

## Resource budget

- ~4,900 tickers × 3 API calls = ~14,700 calls total
- ~600 calls/min at 100ms delay (under 750/min plan limit)
- ~25 min for full universe
- ~45GB bandwidth remaining (negligible impact)

## Rollback

If something goes wrong: `TRUNCATE collection_failures, estimate_snapshots, snapshot_runs RESTART IDENTITY CASCADE;` and start over.

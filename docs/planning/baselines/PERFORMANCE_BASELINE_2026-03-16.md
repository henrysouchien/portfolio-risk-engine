# Performance Baseline — 2026-03-16
**Status:** ACTIVE

## Measurement Conditions

- Backend: local FastAPI on `localhost:5001` via `uvicorn --reload`
- Auth: `POST /auth/dev-login` with local dev bypass
- Cache reset for cold runs: authenticated `POST /admin/clear_cache` using the repo `.env` token
- Single-account scope: `_auto_interactive_brokers_u2471778` with `17` bootstrap holdings
- Combined scope: `CURRENT_PORTFOLIO` with `30` bootstrap holdings
- Cold pattern: clear cache, log in, bootstrap, then fire the dashboard burst in parallel
- Warm pattern: repeat the same bootstrap + burst flow `3` times without another cache clear
- Dashboard performance request uses the current frontend shape: `POST /api/performance` with `include_attribution=false`
- Response size is measured from raw HTTP body bytes and shown in KB

## Key Findings

- Single-account dashboard total is now **1.35s cold**, **470.50ms warm p50**, and **486.59ms warm p95**.
- Combined `CURRENT_PORTFOLIO` dashboard total is now **2.89s cold**, **394.52ms warm p50**, and **407.35ms warm p95**.
- The original warm-path goal is no longer the main story. The local cold path is also now well under the earlier `<8s` target.
- Combined cold outliers are now a tight cluster rather than catastrophic tails: `metric-insights` **2436.05ms**, `risk-score` **2393.43ms**, `ai-recommendations` **2311.95ms**, `holdings` **2309.35ms**, and `analyze` **2285.45ms**.
- Warm combined repeat behavior is now uniformly cheap. The whole burst is about **300.53ms p50** at the parallel request wall.
- `market-intelligence`, `income`, `holdings`, and `metric-insights` no longer show the earlier multi-second warm behavior; their repeat medians are now **41.50ms**, **38.71ms**, **51.86ms**, and **41.36ms** respectively.

## Burst Totals

| Scope | Cold Total (ms) | Warm Samples (ms) | Warm p50 (ms) | Warm p95 (ms) |
|---|---:|---|---:|---:|
| Single Account | 1,348.51 | 390.38, 470.50, 488.38 | 470.50 | 486.59 |
| All Accounts | 2,892.87 | 408.77, 359.60, 394.52 | 394.52 | 407.35 |

## Parallel Burst Wall

| Scope | Cold Parallel Wall (ms) | Warm Parallel Samples (ms) | Warm Parallel p50 (ms) | Warm Parallel p95 (ms) |
|---|---:|---|---:|---:|
| Single Account | 1,273.19 | 299.30, 385.80, 391.28 | 385.80 | 390.73 |
| All Accounts | 2,799.47 | 300.53, 277.36, 309.23 | 300.53 | 308.36 |

## Bootstrap + Scoped Dashboard Endpoints

| Endpoint | Single Cold (ms) | Single Warm p50 | Single Warm p95 | Single Size (KB) | All Cold (ms) | All Warm p50 | All Warm p95 | All Size (KB) | Notes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `GET /api/v2/portfolios` | 25.90 | 34.83 | 37.46 | 1.8 | 27.63 | 36.81 | 42.14 | 1.8 | user-scoped bootstrap list |
| `GET /api/portfolios/{name}` | 35.71 | 39.49 | 49.80 | 2.8 | 48.83 | 37.12 | 51.56 | 4.6 | priced bootstrap response |
| `POST /api/portfolio/refresh-prices` | 13.41 | 14.28 | 16.32 | 2.4 | 16.62 | 11.14 | 11.96 | 4.3 | still cheap; dashboard already skips it when GET priced holdings |
| `POST /api/analyze` | 285.91 | 90.28 | 157.96 | 59.5 | 2,285.45 | 94.04 | 111.84 | 119.1 | no longer a dominant repeat-path cost |
| `POST /api/risk-score` | 308.03 | 105.18 | 136.38 | 46.0 | 2,393.43 | 94.64 | 133.74 | 90.0 | cold path still overlaps with analysis, but warm path is cheap |
| `POST /api/performance` | 164.67 | 107.64 | 156.33 | 11.7 | 365.30 | 90.65 | 119.25 | 11.6 | reflects the current summary-only dashboard request |
| `GET /api/positions/holdings` | 1,125.72 | 130.58 | 164.91 | 20.2 | 2,309.35 | 51.86 | 56.88 | 34.3 | cold path still tracks shared positions + enrichment |
| `GET /api/positions/alerts` | 755.81 | 124.85 | 184.13 | 0.6 | 399.30 | 44.91 | 65.59 | 1.0 | repeat path is now cheap |
| `GET /api/income/projection` | 927.50 | 34.47 | 100.37 | 10.6 | 882.45 | 38.71 | 62.79 | 20.3 | cold path still pays dividend-history work |
| `GET /api/allocations/target` | 89.63 | 82.68 | 164.20 | 0.1 | 293.13 | 80.75 | 90.53 | 0.1 | endpoint itself remains cheap |
| `GET /api/risk-settings` | 92.65 | 88.22 | 145.35 | 0.3 | 298.95 | 68.74 | 85.26 | 0.7 | endpoint itself remains cheap |

## Combined-Only Dashboard Auxiliaries

| Endpoint | Cold (ms) | Warm p50 | Warm p95 | Size (KB) | Notes |
|---|---:|---:|---:|---:|---|
| `GET /api/positions/market-intelligence` | 599.66 | 41.50 | 42.09 | 5.4 | cold and warm path are now both comfortably below 1s |
| `GET /api/positions/ai-recommendations` | 2,311.95 | 43.59 | 45.29 | 0.0 | still one of the larger cold widgets, but the repeat path is cheap |
| `GET /api/positions/metric-insights` | 2,436.05 | 41.36 | 59.96 | 0.4 | one of the remaining cold combined outliers |

## Later Cold-Path Spot Checks

Direct service-level profiling on the same March 16 code after the latest repricing batch showed:

- `PositionService.get_all_positions(use_cache=True)` at roughly **1.54s** wall for the current user.
- Cached provider stage timings at roughly:
  - `schwab`: **805.92ms**
  - `ibkr`: **365.64ms**
  - `plaid`: **338.58ms**
  - `csv`: **1.93ms**
- The shared cached repricing pass for `40` rows dropped from roughly **1.31s** to roughly **679ms** after batching FMP profile quote fetches.

These spot checks line up with the much better cold `holdings`, `income`, and auxiliary endpoint numbers in the authenticated localhost rerun above.

## Interpretation

- The earlier March 16 authenticated baseline in this file is now superseded by this rerun.
- Both the warm repeat path and the cold first-hit path are now in a good local state.
- The current dashboard bottlenecks are no longer broad architectural problems. The remaining cold outliers are a few specific endpoints, especially combined `metric-insights`, `ai-recommendations`, `risk-score`, `holdings`, and `analyze`.
- The repeat-path dashboard problem is effectively closed in localhost measurements.

## Recommendation

If more perf work continues after this checkpoint, it should be incremental rather than a new broad perf phase:

1. Trim the remaining combined cold outliers, especially `metric-insights` and `ai-recommendations`.
2. Keep the provider-side cached repricing path under observation, since that is still the largest direct service-level cold cost.
3. Re-measure only after a concrete cold-path change rather than reopening a whole-dashboard dedupe effort.

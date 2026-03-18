# Performance Baseline — 2026-03-18
**Status:** ACTIVE

## Measurement Conditions

- Backend: local FastAPI on `localhost:5001` via `uvicorn`
- Auth: `POST /auth/dev-login` with local dev bypass
- Cache reset for cold runs: authenticated `POST /admin/clear_cache` using the repo `.env` token
- Single-account scope: `_auto_interactive_brokers_u2471778`
- Combined scope: `CURRENT_PORTFOLIO`
- Cold pattern: clear cache, log in, fetch `/api/v2/portfolios`, fetch `GET /api/portfolios/{name}`, then fire the dashboard burst in parallel
- Warm pattern: repeat the same bootstrap + burst flow `3` times without another cache clear
- Dashboard performance request uses the current frontend shape: `POST /api/performance` with `include_attribution=false`
- Important correctness note: virtual portfolio bootstrap now reuses the live scoped holdings path, so cold bootstrap includes the first real holdings load instead of the older synthetic proxy-pricing path

## Key Findings

- Single-account dashboard total is now **1.40s cold**, **162.72ms warm p50**, and **216.98ms warm p95**.
- Combined `CURRENT_PORTFOLIO` dashboard total is now **1.53s cold**, **257.86ms warm p50**, and **349.10ms warm p95**.
- Combined parallel dashboard wall is now **500.38ms cold** and **178.54ms warm p50**.
- The warm path is comfortably below the earlier March 16 baseline, and the cold path is now dominated by the intentional live-bootstrap correctness work rather than duplicate backend recomputation.
- The biggest combined cold costs are now `bootstrap` **994.91ms**, `income` **494.93ms**, `analyze` **396.65ms**, `market-intelligence` **345.50ms**, and `performance` **336.15ms**.
- Combined warm repeat behavior is uniformly cheap. Every endpoint in the measured burst is below **177ms p50**, and the three portfolio auxiliaries are all around **70ms p50**.

## Post-Baseline Correctness Note

- After this baseline was recorded, a real UI selector check surfaced one regression on `_auto_interactive_brokers_u2471778`: the selected IBKR account rendered as `$0` because scoped-provider pruning had excluded `ibkr` when the live gateway probe was unavailable.
- The fix kept `ibkr` in the scoped provider registry for cache-backed fallback and let the scoped provider set override the generic default-provider gate.
- Revalidation after the fix:
  - authenticated `GET /api/positions/holdings?portfolio_name=_auto_interactive_brokers_u2471778` returned **18** positions and **$21,522.85** total value
  - real browser spot-check on `http://localhost:3000` showed **Interactive Brokers U2471778** with **$21,523** and populated holdings
  - authenticated backend smoke across all six listed portfolios showed bootstrap and holdings totals matching exactly for each selector-backed portfolio
- This did not reopen the broad perf problem; it was a correctness regression in the later scoped-provider optimization.

## Burst Totals

| Scope | Cold Total (ms) | Warm Samples (ms) | Warm p50 (ms) | Warm p95 (ms) |
|---|---:|---|---:|---:|
| Single Account | 1,396.65 | 162.72, 147.14, 216.98 | 162.72 | 216.98 |
| All Accounts | 1,526.14 | 349.10, 257.86, 226.84 | 257.86 | 349.10 |

## Parallel Burst Wall

| Scope | Cold Parallel Wall (ms) | Warm Parallel Samples (ms) | Warm Parallel p50 (ms) | Warm Parallel p95 (ms) |
|---|---:|---|---:|---:|
| Single Account | 382.69 | 124.89, 102.82, 172.12 | 124.89 | 172.12 |
| All Accounts | 500.38 | 282.08, 160.31, 178.54 | 178.54 | 282.08 |

## Bootstrap + Scoped Dashboard Endpoints

| Endpoint | Single Cold (ms) | Single Warm p50 | Single Warm p95 | Single Size (KB) | All Cold (ms) | All Warm p50 | All Warm p95 | All Size (KB) | Notes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `GET /api/v2/portfolios` | 27.77 | 29.89 | 33.35 | 2.1 | 30.84 | 43.07 | 78.55 | 2.1 | user-scoped bootstrap list |
| `GET /api/portfolios/{name}` | 986.20 | 10.96 | 15.46 | 3.6 | 994.91 | 19.00 | 23.95 | 6.0 | virtual bootstrap now reflects live scoped holdings |
| `POST /api/portfolio/refresh-prices` | 18.18 | 11.00 | 13.80 | 2.9 | 14.72 | 34.45 | 46.57 | 5.2 | still cheap; dashboard already skips it when GET priced holdings |
| `POST /api/analyze` | 216.93 | 123.84 | 170.51 | 59.5 | 396.65 | 176.41 | 279.46 | 119.1 | warm path remains comfortably below 300ms |
| `POST /api/risk-score` | 72.84 | 59.49 | 83.28 | 46.0 | 165.98 | 109.04 | 207.12 | 90.0 | no longer a cold or warm outlier |
| `POST /api/performance` | 234.90 | 63.35 | 81.31 | 11.5 | 336.15 | 110.80 | 204.99 | 5.6 | summary-only dashboard path remains cheap |
| `GET /api/positions/holdings` | 50.53 | 53.03 | 65.80 | 20.7 | 26.53 | 41.45 | 148.22 | 35.1 | cold holdings itself is no longer the bottleneck |
| `GET /api/positions/alerts` | 100.27 | 100.42 | 167.62 | 0.6 | 87.87 | 41.79 | 161.94 | 1.0 | still a little noisy warm, but not expensive |
| `GET /api/income/projection` | 378.46 | 52.45 | 63.80 | 10.6 | 494.93 | 61.24 | 171.67 | 20.4 | main remaining cold widget after bootstrap |
| `GET /api/allocations/target` | 136.27 | 73.32 | 152.26 | 0.1 | 265.61 | 108.97 | 239.22 | 0.1 | endpoint itself is still small |
| `GET /api/risk-settings` | 148.89 | 83.83 | 135.68 | 0.3 | 265.67 | 95.37 | 196.20 | 0.7 | endpoint itself is still small |

## Combined-Only Dashboard Auxiliaries

| Endpoint | Cold (ms) | Warm p50 | Warm p95 | Size (KB) | Notes |
|---|---:|---:|---:|---:|---|
| `GET /api/positions/market-intelligence` | 345.50 | 72.50 | 170.58 | 5.2 | no longer a meaningful warm-path issue |
| `GET /api/positions/ai-recommendations` | 160.56 | 71.52 | 172.99 | 0.0 | cold and warm are both small now |
| `GET /api/positions/metric-insights` | 248.70 | 69.82 | 172.13 | 0.4 | now well under the earlier March 16 outlier class |

## Interpretation

- The old broad dashboard perf problem remains closed.
- The new cold-path shape is different from the March 16 baseline because virtual bootstrap now intentionally waits for the same live scoped holdings source used by the holdings screen.
- That correctness-aligned bootstrap is now the largest cold cost at roughly **1.0s**, but it still leaves the total dashboard cold path around **1.5s**.
- The remaining backend perf work, if any, should stay tactical: bootstrap cold load, income cold load, and smaller analysis-path trims.

## Recommendation

If perf work continues after this checkpoint, it should be narrow:

1. Treat the dashboard warm-path optimization as done.
2. Keep the March 18 virtual-bootstrap correctness path in place; do not reintroduce the old synthetic bootstrap source just to make cold bootstrap look cheaper.
3. Only pursue additional perf work if the remaining cold costs matter in practice, starting with bootstrap and `income`.

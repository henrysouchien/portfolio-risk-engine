# Performance Baseline — 2026-03-15
**Status:** ACTIVE

## Measurement Conditions

- Backend: local FastAPI on `localhost:5001`
- Frontend: local Vite app on `localhost:3000`
- Auth: `POST /auth/dev-login` using local dev bypass
- Cache reset: `POST /admin/clear_cache` before each cold scope run
- Single-account scope: `_auto_interactive_brokers_u2471778` (Interactive Brokers U2471778)
- Combined scope: `CURRENT_PORTFOLIO` (All Accounts, 51 positions across 5 accounts)
- Cold measurement pattern: clear caches, fetch bootstrap routes, then fire the dashboard burst in parallel
- Warm measurement pattern: repeat the same bootstrap + burst flow 3 times without clearing caches
- Response size is measured from raw HTTP body bytes and shown in KB
- This is a controlled script baseline, not a browser waterfall capture

## Key Findings

- Combined-account cold dashboard burst is **16.4s**, materially better than the ~49s March 10 baseline, but still above the `<15s` target.
- Single-account cold dashboard burst is **6.6s**. Warm repeats land between **4.2s** and **5.3s**.
- The slowest combined-account cold endpoints are `market-intelligence` (**16.4s**), `metric-insights` (**12.0s**), `positions-holdings` (**10.6s**), `positions-alerts` (**10.5s**), and `performance` (**9.2s**).
- `POST /api/analyze` and `POST /api/risk-score` are no longer the dominant cold-path failures, but under the combined burst they still show warm `p50` around **8.9s** and **8.7s** respectively.
- `GET /api/v2/portfolios` has a very slow first hit (**4.0s**) and then drops sharply on subsequent calls (`2.76s`, `41.86ms`, `12.68ms`).
- Bootstrap pricing duplication still exists in code, but in this local run `GET /api/portfolios/{name}` and `POST /api/portfolio/refresh-prices` were both cheap once warm (<`0.06s` for GET, <`0.02s` for refresh).
- `market-intelligence`, `ai-recommendations`, and `metric-insights` are still effectively user-scoped in the current frontend contract; they are not passed a portfolio name by the resolver.

## Burst Totals

| Scope | Cold Total (ms) | Warm Samples (ms) | Warm p50 (ms) | Warm p95 (ms) |
|---|---:|---|---:|---:|
| Single Account | 6616.50 | 4162.88, 5261.60, 5054.69 | 5054.69 | 5240.91 |
| All Accounts | 16416.09 | 18552.52, 32185.35, 17168.11 | 18552.52 | 30822.07 |

## Bootstrap + Scoped Dashboard Endpoints

| Endpoint | Single Cold (ms) | Single Warm p50 | Single Warm p95 | Single Size (KB) | All Cold (ms) | All Warm p50 | All Warm p95 | All Size (KB) | Notes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `GET /api/v2/portfolios` | 3,966.91 | 41.86 | 2,491.82 | 1.8 | — | — | — | — | user-scoped bootstrap list |
| `GET /api/portfolios/{name}` | 33.84 | 44.67 | 54.67 | 2.8 | 40.26 | 51.95 | 52.83 | 4.6 | priced bootstrap response |
| `POST /api/portfolio/refresh-prices` | 16.17 | 11.56 | 12.01 | 2.6 | 10.32 | 9.53 | 12.36 | 4.4 | frontend currently may call this immediately after bootstrap GET |
| `POST /api/analyze` | 6,615.84 | 4,159.64 | 4,964.49 | 63.9 | 7,178.69 | 8,886.88 | 17,882.43 | 124.5 | risk analysis |
| `POST /api/risk-score` | 6,615.55 | 4,128.87 | 4,941.52 | 53.7 | 4,958.54 | 8,708.46 | 15,777.83 | 97.0 | risk scoring |
| `POST /api/performance` | 6,615.32 | 4,100.20 | 4,958.60 | 17.0 | 9,193.67 | 8,694.29 | 27,860.59 | 20.2 | hypothetical performance vs SPY |
| `GET /api/positions/holdings` | 3,252.19 | 2,859.31 | 3,612.82 | 20.1 | 10,618.01 | 9,024.34 | 14,485.37 | 20.0 | holdings monitor payload |
| `GET /api/positions/alerts` | 3,251.88 | 3,696.35 | 5,104.17 | 0.6 | 10,507.06 | 10,606.45 | 18,763.10 | 0.6 | portfolio alert payload |
| `GET /api/income/projection` | 3,248.59 | 2,855.85 | 3,609.56 | 10.6 | 2,745.40 | 3,331.11 | 13,906.65 | 10.6 | income card data |
| `GET /api/allocations/target` | 3,315.06 | 2,921.42 | 3,672.75 | 0.1 | 4,525.83 | 5,921.72 | 14,233.81 | 0.1 | target allocation read |
| `GET /api/risk-settings` | 3,317.76 | 2,906.29 | 3,668.82 | 0.3 | 4,512.73 | 5,942.60 | 14,205.84 | 0.7 | risk profile/settings read |

## Combined-Only User-Scoped Dashboard Auxiliaries

| Endpoint | Cold (ms) | Warm p50 | Warm p95 | Size (KB) | Notes |
|---|---:|---:|---:|---:|---|
| `GET /api/positions/market-intelligence` | 16414.78 | 18551.11 | 30819.82 | 2.9 | not portfolio-scoped in current resolver/API contract |
| `GET /api/positions/ai-recommendations` | 4451.15 | 11026.15 | 19443.04 | 1.0 | not portfolio-scoped in current resolver/API contract |
| `GET /api/positions/metric-insights` | 11972.52 | 11006.44 | 26076.28 | 0.4 | not portfolio-scoped in current resolver/API contract |

## Server Timing Cross-Check

Top request groups from `/api/debug/timing?minutes=30&kind=request` after the scripted run:

| Endpoint | Avg (ms) | Count | p50 (ms) | p95 (ms) |
|---|---:|---:|---:|---:|
| `GET /api/positions/market-intelligence` | 16647.40 | 8 | 14886.51 | 26605.83 |
| `GET /api/trading/accounts` | 10327.40 | 2 | 10327.40 | 16878.65 |
| `POST /api/performance` | 7243.87 | 10 | 4676.88 | 20403.85 |
| `GET /api/positions/metric-insights` | 6978.27 | 8 | 6824.11 | 10860.55 |
| `POST /api/analyze` | 5522.59 | 10 | 4604.14 | 13613.56 |
| `POST /api/risk-score` | 5488.99 | 10 | 4987.45 | 12176.86 |
| `GET /api/positions/holdings` | 4735.46 | 14 | 3552.74 | 13360.04 |
| `GET /api/positions/ai-recommendations` | 4393.63 | 6 | 4560.23 | 5255.88 |
| `GET /api/positions/alerts` | 4348.19 | 16 | 3415.45 | 8428.26 |
| `GET /api/income/projection` | 3383.08 | 12 | 3120.64 | 5055.27 |
| `GET /api/allocations/target` | 3219.87 | 12 | 108.90 | 10726.29 |
| `GET /api/risk-settings` | 2095.74 | 10 | 64.47 | 9608.44 |

## Interpretation

- The March 10 baseline is no longer representative of the current codebase for core risk endpoints. Combined `analyze`, `risk-score`, and `performance` are slower than target but not catastrophic anymore.
- The next optimization pass should focus on the endpoints that remain slow in the current burst: `market-intelligence`, `metric-insights`, `positions-holdings`, `positions-alerts`, and combined `performance`.
- The server timing data also shows `allocations-target` and `risk-settings` inflate under the burst even though they should be cheap, which supports the plan item around reducing duplicate competing work during dashboard load.
- Because this baseline is burst-oriented and parallel, some warm `p50` values are slower than the first cold hit. That is a sign of burst contention and shared downstream work, not a measurement bug.

# Performance Baseline — 2026-03-16
**Status:** ACTIVE

## Measurement Conditions

- Backend: local FastAPI on `localhost:5001`
- Frontend: not required for this scripted run
- Auth: `POST /auth/dev-login` using local dev bypass
- Cache reset for cold runs: `POST /admin/clear_cache` with `X-Admin-Token` from repo `.env`
- Single-account scope: `_auto_interactive_brokers_u2471778` (bootstrap returned 18 holdings)
- Combined scope: `CURRENT_PORTFOLIO` (bootstrap returned 31 holdings)
- Cold measurement pattern: clear caches, log in, fetch bootstrap routes, then fire the dashboard burst in parallel
- Warm measurement pattern: repeat the same bootstrap + burst flow 3 times without another cache clear
- Response size is measured from raw HTTP body bytes and shown in KB
- This rerun supersedes the earlier March 16 reload-based draft; the numbers below use the correct admin cache-clear boundary

## Key Findings

- Single-account warm dashboard burst `p50` is **1.78s** and `p95` is **2.09s**.
- Combined-account warm dashboard burst `p50` is **7.86s** and `p95` is **9.04s**.
- The original combined warm-path target of `<10-12s` is now met under the correct admin cache-clear reset.
- Bootstrap is no longer a meaningful bottleneck. `GET /api/portfolios/{name}` already returns priced holdings with `price_refresh_attempted=true` and `prices_refreshed=true`, and the redundant scripted `POST /api/portfolio/refresh-prices` stays cheap.
- The remaining combined warm offenders are `market-intelligence`, `metric-insights`, `income`, `performance`, and `holdings`.
- `analyze` and `risk-score` are no longer the main bottlenecks in the warm burst. Their medians are now sub-second for `CURRENT_PORTFOLIO`, but their `p95` tails still spike under contention.
- Workflow timing shows that duplicate setup is no longer the dominant problem. The remaining cost is concentrated in attribution enrichment, dividend-history fetches, holdings market-data enrichment, and user-scoped intelligence work.

## Later March 16 Spot Checks

The tables below remain the formal authenticated admin-clear baseline. Additional optimization work landed later on March 16, 2026, and the latest localhost spot checks are materially better than this baseline. Those later checks are not a full replacement baseline; they are supporting evidence for the current state of the code.

### Warm Repeat Spot Checks

- Combined dashboard-style warm repeat burst dropped to roughly **533ms** end-to-end.
- Latest warm per-endpoint repeat timings were approximately:
  - `POST /api/analyze`: **531ms**
  - `GET /api/positions/market-intelligence`: **523ms**
  - `GET /api/income/projection`: **510ms**
  - `GET /api/positions/ai-recommendations`: **487ms**
  - `POST /api/performance`: **126ms**
  - `POST /api/risk-score`: **119ms**
  - `GET /api/positions/metric-insights`: **84ms**
  - `GET /api/positions/holdings`: **50ms**

### Cold Path Spot Checks

- Concurrent fresh `PositionService(...)` construction dropped from roughly **10.05s** to roughly **371ms** after default-registry build dedupe.
- First-hit `ensure_factor_proxies` in the `risk-score` workflow dropped from roughly **2.29s** to roughly **199ms** after parallel base-proxy generation.
- Direct cold `get_all_positions()` probes dropped from roughly **6.7s** to roughly **1.8s** after setup dedupe, FX memoization, provider pruning, provider-scoped order invalidation, cached stale-provider fallback, and shared quote caching.
- In the latest probe, Plaid stayed on cache at roughly **289ms** instead of refetching for roughly **6.1s** because unrelated broker `trade_orders` no longer shorten Plaid's TTL.
- Expired Schwab auth now fast-fails on repeat probes in-process, dropping a second invalid-grant attempt from roughly **807ms** to roughly **3ms** in the live check.
- In the latest live positions probe, IBKR stayed on cache as well because unchanged old `PENDING` rows no longer invalidate a newer positions snapshot.
- Real `GET /api/positions/holdings` after authenticated `POST /admin/clear_cache` now lands around **1.50s**, with an immediate repeat around **17ms**.
- The current user-scoped cold positions path now correctly fetches `plaid`, `schwab`, `ibkr`, and `csv`, and skips `snaptrade`.
- Full cold `CURRENT_PORTFOLIO` dashboard spot checks are still variable, roughly **7s** to **13s**, which now points mostly to live IBKR fetch latency and the stale Schwab attempt rather than broad local duplicate work.

## Burst Totals

| Scope | Cold Total (ms) | Warm Samples (ms) | Warm p50 (ms) | Warm p95 (ms) |
|---|---:|---|---:|---:|
| Single Account | 15,830.24 | 2,119.50, 1,724.71, 1,779.77 | 1,779.77 | 2,085.53 |
| All Accounts | 9,108.99 | 7,856.68, 3,856.51, 9,168.92 | 7,856.68 | 9,037.70 |

## Bootstrap + Scoped Dashboard Endpoints

| Endpoint | Single Cold (ms) | Single Warm p50 | Single Warm p95 | Single Size (KB) | All Cold (ms) | All Warm p50 | All Warm p95 | All Size (KB) | Notes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `GET /api/v2/portfolios` | 39.26 | 54.25 | 84.50 | 1.8 | 34.12 | 36.77 | 43.93 | 1.8 | user-scoped bootstrap list |
| `GET /api/portfolios/{name}` | 31.29 | 46.28 | 59.91 | 2.9 | 32.34 | 43.41 | 43.69 | 4.7 | priced bootstrap response; GET already refreshed prices |
| `POST /api/portfolio/refresh-prices` | 14.58 | 12.69 | 19.96 | 2.6 | 15.53 | 10.96 | 12.15 | 4.4 | redundant after Phase 2; still cheap in scripted flow |
| `POST /api/analyze` | 371.16 | 251.92 | 1,478.80 | 63.9 | 7,644.71 | 737.38 | 2,166.15 | 124.5 | warm median is now low; burst-tail variance remains |
| `POST /api/risk-score` | 326.14 | 96.45 | 1,425.99 | 53.3 | 7,144.51 | 348.17 | 2,060.28 | 97.0 | warm median is now low; burst-tail variance remains |
| `POST /api/performance` | 2,317.89 | 1,441.91 | 2,050.72 | 17.0 | 8,108.34 | 2,694.90 | 2,917.24 | 20.1 | attribution enrichment is still the main cost |
| `GET /api/positions/holdings` | 15,463.54 | 1,360.40 | 1,370.44 | 18.6 | 5,722.43 | 1,575.73 | 2,138.64 | 23.1 | first-hit positions + market-data enrichment still matter |
| `GET /api/positions/alerts` | 15,172.10 | 206.60 | 248.93 | 0.6 | 5,126.05 | 57.10 | 72.22 | 1.2 | snapshot reuse is working; follow-up path is now cheap |
| `GET /api/income/projection` | 15,827.57 | 1,778.47 | 1,901.66 | 10.6 | 9,107.67 | 2,781.35 | 3,312.17 | 14.9 | dominated by positions load + dividend history |
| `GET /api/allocations/target` | 71.90 | 98.85 | 184.12 | 0.1 | 5,168.52 | 245.20 | 409.04 | 0.1 | endpoint itself is cheap; some burst contention remains |
| `GET /api/risk-settings` | 73.11 | 102.55 | 119.72 | 0.3 | 5,191.64 | 321.56 | 440.10 | 0.7 | endpoint itself is cheap; some burst contention remains |

## Combined-Only User-Scoped Dashboard Auxiliaries

| Endpoint | Cold (ms) | Warm p50 | Warm p95 | Size (KB) | Notes |
|---|---:|---:|---:|---:|---|
| `GET /api/positions/market-intelligence` | 6,889.39 | 7,855.52 | 9,036.55 | 4.6 | still the slowest combined warm widget; current API contract is still user-scoped |
| `GET /api/positions/ai-recommendations` | 5,578.84 | 714.35 | 816.01 | 1.4 | shared positions helped materially; no longer a primary blocker |
| `GET /api/positions/metric-insights` | 8,996.50 | 3,940.21 | 4,032.74 | 0.4 | still heavy; mostly performance flags + portfolio context |

## Workflow Step Cross-Check

Average step timings from `logs/timing.jsonl` entries written during this baseline run:

| Workflow | Main Expensive Steps |
|---|---|
| `api_analyze_workflow` | `ensure_factor_proxies` `580.52ms`, `build_response` `204.76ms`, `load_portfolio_data` `142.50ms` |
| `api_risk_score_workflow` | `ensure_factor_proxies` `580.26ms`, `load_portfolio_data` `140.80ms` |
| `api_performance_workflow` | `enrich_attribution_with_analyst_data` `1982.50ms`, `load_portfolio_data` `142.25ms`, `analyze_performance` `77.13ms` |
| `positions_holdings_workflow` | `get_all_positions` `1710.14ms`, `enrich_positions_with_market_data` `891.07ms`, `resolve_scope` `191.35ms`, `enrich_positions_with_sectors` `164.88ms` |
| `income_position_load_workflow` | `get_all_positions` `1882.84ms`, `resolve_scope` `32.90ms` |
| `income_dividend_data_fetch` | `fetch_dividend_history` `2305.64ms`, `fetch_dividend_calendar` `3.84ms` |
| `metric_insights_workflow` | `load_performance_flags` `1968.33ms`, `load_portfolio_context` `1727.97ms`, `load_risk_score_flags` `176.23ms` |
| `market_intelligence_symbol_load` | `get_all_positions` `1056.90ms` average during this run |
| `market_intelligence_weight_load` | `get_all_positions` `636.89ms` average during this run |
| `ai_recommendations_workflow` | `recommend_portfolio_offsets` `580.30ms`, `get_all_positions` `0.24ms` |

Interpretation:

- `analyze` and `risk-score` are no longer dominated by repeated setup or heavy core analysis.
- `performance` is now mostly about attribution enrichment rather than the core performance analysis call.
- `income` is split between position loading and dividend-history fetch cost.
- `metric-insights` is still effectively a derived stack on top of portfolio context plus performance/risk flag generation.
- `market-intelligence` request latency is much higher than its measured symbol/weight-load steps. This suggests the downstream event/news fetch path now dominates after position reuse landed.

## Server Timing Cross-Check

Top request groups from `logs/timing.jsonl` entries written during this scripted run:

| Endpoint | Avg (ms) | Count | p50 (ms) | p95 (ms) |
|---|---:|---:|---:|---:|
| `GET /api/positions/market-intelligence` | 6,664.62 | 4 | 7,353.19 | 8,963.49 |
| `GET /api/income/projection` | 4,248.93 | 8 | 2,742.36 | 11,671.18 |
| `GET /api/positions/metric-insights` | 3,904.10 | 4 | 3,878.85 | 4,006.55 |
| `GET /api/positions/holdings` | 3,049.39 | 8 | 1,363.05 | 10,806.52 |
| `POST /api/performance` | 2,258.22 | 8 | 2,366.24 | 2,938.27 |
| `GET /api/positions/alerts` | 1,979.96 | 8 | 85.11 | 9,938.49 |
| `POST /api/analyze` | 1,697.39 | 8 | 574.25 | 5,781.03 |
| `POST /api/risk-score` | 843.92 | 8 | 308.81 | 2,158.22 |
| `GET /api/allocations/target` | 784.29 | 8 | 157.44 | 3,499.59 |
| `GET /api/positions/ai-recommendations` | 613.44 | 4 | 593.64 | 798.87 |
| `GET /api/risk-settings` | 143.47 | 8 | 78.81 | 363.27 |

## Interpretation

- This admin-cache-clear rerun is the correct March 16 checkpoint. The earlier reload-based draft should no longer be treated as the source of truth.
- The Phase 1 through Phase 5 backend pass met its original warm-path goal: the combined dashboard burst is now below `8s` `p50` and below `10s` `p95`.
- The remaining problem is not global dashboard setup duplication. It is tail latency inside a handful of downstream operations:
  - `market-intelligence` event/news fetch work
  - `performance` attribution enrichment
  - `income` dividend-history loading
  - `metric-insights` reuse of performance/context outputs
- Single-account behavior is now in a good place. The combined overview path still has enough jitter that the next pass should focus on a few specific widgets rather than another broad dedupe sweep.

## Interpretation Update After Later March 16 Work

- The original warm-path dashboard problem is effectively closed. Later repeat-path spot checks are well below the formal baseline numbers.
- The main remaining issue is now cold first-hit latency inside the shared provider positions load and a few cold downstream external fetches layered on top of it.
- The cold path no longer looks dominated by local duplicate setup. The shared positions load is much cheaper now; the next remaining cold owners are downstream enrichments like holdings risk enrichment and endpoint-specific fetch work such as income / intelligence.

## Recommendation

If work continues beyond this checkpoint, the highest-value next pass is:

1. Reduce cold first-hit provider latency inside `PositionService.get_all_positions()`.
2. Further reduce cold downstream fetch work inside `market-intelligence`.
3. Further reduce cold dividend-history cost inside `income`.
4. Re-measure cold burst consistency before considering any larger API-shape change.

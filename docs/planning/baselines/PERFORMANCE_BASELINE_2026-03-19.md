# Performance Baseline — 2026-03-19
**Status:** ACTIVE

## Measurement Conditions

- Backend: local FastAPI on `localhost:5001` via `uvicorn`
- Auth: `POST /auth/dev-login` with local dev bypass
- Cache reset for cold runs: authenticated `POST /admin/clear_cache` using the repo `.env` token
- Single-account scope: `_auto_interactive_brokers_u2471778`
- Combined scope: `CURRENT_PORTFOLIO`
- Cold pattern: clear cache, log in, fetch `/api/v2/portfolios`, fetch `GET /api/portfolios/{name}`, then fire the current default overview burst in parallel
- Warm pattern: repeat the same bootstrap + burst flow `3` times without another cache clear
- Current default overview burst:
  - `GET /api/positions/holdings?portfolio_name=...`
  - `GET /api/positions/alerts?portfolio_name=...`
  - `POST /api/analyze`
  - `POST /api/risk-score`
  - `POST /api/performance/realized` with `include_attribution=false`
  - `GET /api/allocations/target?portfolio_name=...`
  - `GET /api/income/projection?portfolio_name=...`
  - `GET /api/positions/market-intelligence?portfolio_name=...`
  - `GET /api/positions/ai-recommendations?portfolio_name=...`
- Optional routes `metric-insights` and `trading-analysis` were measured separately after the default burst
- Important correctness note: virtual portfolio bootstrap still reuses the live scoped holdings path and remains intentionally correctness-aligned
- Important new perf note in this checkpoint:
  - month-end analysis series now have their own cache store (`close_me`, `total_return_me`)
  - computed peer-median proxy series are now cached directly
  - virtual portfolios can now reuse cached live snapshots during `resolve_config`

## Key Findings

- Single-account overview total is now **1.57s cold**, **149.07ms warm p50**, and **156.93ms warm p95**.
- Combined `CURRENT_PORTFOLIO` overview total is now **1.64s cold**, **114.66ms warm p50**, and **129.75ms warm p95**.
- Single-account parallel overview wall is now **1.57s cold** and **156.32ms warm p50**.
- Combined parallel overview wall is now **1.64s cold** and **115.45ms warm p50**.
- This is an improvement over the March 18 post-cache-change checkpoint on both cold scopes and on the warm combined path.
- The remaining default-overview cold owners are now:
  - summary-only realized performance
  - holdings risk enrichment
  - cold single-account bootstrap
  - cold AI recommendations

## Comparison To March 18 Post-Cache-Change Baseline

| Scope | March 18 Cold (ms) | March 19 Cold (ms) | March 18 Warm p50 (ms) | March 19 Warm p50 (ms) |
|---|---:|---:|---:|---:|
| Single Account | 2,349.28 | 1,565.02 | 152.94 | 149.07 |
| All Accounts | 2,079.98 | 1,636.25 | 152.29 | 114.66 |

## Burst Totals

| Scope | Cold Total (ms) | Warm Samples (ms) | Warm p50 (ms) | Warm p95 (ms) |
|---|---:|---|---:|---:|
| Single Account | 1,565.02 | 139.97, 149.07, 156.93 | 149.07 | 156.93 |
| All Accounts | 1,636.25 | 112.99, 114.66, 129.75 | 114.66 | 129.75 |

## Parallel Burst Wall

| Scope | Cold Parallel Wall (ms) | Warm Parallel Samples (ms) | Warm Parallel p50 (ms) | Warm Parallel p95 (ms) |
|---|---:|---|---:|---:|
| Single Account | 1,569.12 | 141.52, 156.32, 157.92 | 156.32 | 157.92 |
| All Accounts | 1,640.15 | 114.50, 115.45, 132.04 | 115.45 | 132.04 |

## Bootstrap + Default Overview Endpoints

| Endpoint | Single Cold (ms) | Single Warm p50 | Single Warm p95 | Single Size (KB) | All Cold (ms) | All Warm p50 | All Warm p95 | All Size (KB) | Notes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `GET /api/v2/portfolios` | 23.22 | 20.21 | 22.88 | 1.8 | 26.20 | 27.22 | 29.03 | 1.8 | user-scoped bootstrap list |
| `GET /api/portfolios/{name}` | 1,191.21 | 39.04 | 989.25 | 3.2 | 408.68 | 10.84 | 14.76 | 5.4 | single-account cold bootstrap is still the most obvious bootstrap outlier |
| `POST /api/performance/realized` `include_attribution=false` | 1,564.12 | 207.00 | 1,416.85 | 21.2 | 1,636.25 | 71.02 | 1,330.21 | 21.5 | still the largest cold overview endpoint |
| `POST /api/analyze` | 621.72 | 265.86 | 621.13 | 55.9 | 1,322.11 | 136.33 | 381.29 | 113.9 | combined cold analysis remains expensive, but improved versus March 18 |
| `POST /api/risk-score` | 619.59 | 221.95 | 620.79 | 43.9 | 1,319.40 | 119.77 | 250.91 | 85.9 | still coupled to the cold analysis path |
| `GET /api/positions/holdings` | 1,470.61 | 48.53 | 1,140.39 | 20.1 | 1,227.34 | 11.34 | 301.72 | 34.8 | warm holdings are excellent; cold risk enrichment still dominates |
| `GET /api/positions/ai-recommendations` | 1,565.02 | 219.51 | 1,185.38 | 0.0 | 1,201.07 | 75.21 | 188.65 | 0.0 | cold recommendation generation still matters |
| `GET /api/income/projection` | 297.87 | 207.20 | 217.39 | 10.3 | 483.33 | 75.88 | 687.02 | 20.1 | remains moderate on cold, cheap after the first warmed repeat |
| `GET /api/positions/market-intelligence` | 1,249.93 | 219.83 | 1,210.84 | 5.3 | 368.80 | 76.30 | 137.51 | 5.3 | single-account cold still pays for first event load |
| `GET /api/allocations/target` | 253.23 | 222.21 | 281.19 | 0.1 | 209.96 | 80.90 | 211.93 | 0.1 | still small but not free |
| `GET /api/positions/alerts` | 369.43 | 238.76 | 335.91 | 0.4 | 106.33 | 11.80 | 91.99 | 1.0 | single-account warm alerts are still noisier than combined |

## Recent Workflow Timing Breakdown

From `/api/debug/timing?minutes=2` immediately after the rerun:

- `realized_performance_workflow`: **363.31ms avg**
  - `load_realized_performance_payload`: **362.15ms**
- `positions_holdings_workflow`: **1,303.81ms avg**
  - `enrich_positions_with_risk`: **973.75ms**
  - `apply_scope_filter`: **172.71ms**
  - `enrich_positions_with_market_data`: **102.92ms**
- `analyze_portfolio`: **704.09ms avg**
  - `build_view_and_betas`: **572.18ms**
  - inside `build_portfolio_view`, `factor_exposures`: **555.71ms**
- `api_analyze_workflow`: **283.56ms avg**
  - `apply_cached_virtual_standardization`: **50.19ms**
  - `analyze_portfolio`: **160.53ms**
  - `build_response`: **72.31ms**
- `api_risk_score_workflow`: **238.53ms avg**
  - `apply_cached_virtual_standardization`: **43.78ms**
  - `load_analysis_result`: **165.52ms**
- `ai_recommendations_workflow`: **1,198.85ms avg**
  - `load_portfolio_snapshot`: **173.46ms**
  - `recommend_portfolio_offsets`: **1,025.37ms**
- `income_projection_workflow`: **507.66ms avg**
  - `load_positions`: **21.91ms**
  - `fetch_dividend_data`: **483.14ms**

## Exploratory Optional Routes

These were measured outside the default overview burst:

- `GET /api/positions/metric-insights`
  - single-account: **1.03s**
  - combined: **16.63ms**
- `GET /api/trading/analysis`
  - single-account: **1.69s**
  - combined: **2.20s**

The default overview path is now in a much better class than these optional routes. If more work continues, these are separate follow-on targets, not blockers for the overview baseline.

## Interpretation

- The month-end analysis store, cached peer-median proxy series, and cached virtual-snapshot reuse all landed cleanly enough to improve the default overview baseline.
- Warm behavior is now clearly healthy again, with combined warm p50 down to **114.66ms**.
- The remaining cost is concentrated in a few narrow cold owners:
  1. summary-only realized-performance payload load
  2. holdings risk enrichment
  3. cold analysis factor-exposure work
  4. cold AI recommendation generation
  5. single-account virtual bootstrap

## Recommendation

If perf work continues after this checkpoint, it should stay tactical:

1. Keep the month-end analysis store, computed peer-median cache, and cached virtual-snapshot reuse in place.
2. Target cold summary-only realized-performance payload load next if the performance view still feels slow in practice.
3. After that, decide between holdings risk enrichment and cold factor-exposure work in `analyze`.
4. Treat `metric-insights` and `trading-analysis` as separate optional-route follow-ons, not default overview blockers.

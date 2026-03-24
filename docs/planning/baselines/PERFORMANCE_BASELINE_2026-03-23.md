# Performance Baseline — 2026-03-23
**Status:** ACTIVE

## Measurement Conditions

- Backend: local FastAPI on `localhost:5001` via `uvicorn`
- Auth: `POST /auth/dev-login` with local dev bypass
- Cache reset for cold runs: authenticated `POST /admin/clear_cache`
- Single-account scope: `_auto_interactive_brokers_u2471778`
- Combined scope: `CURRENT_PORTFOLIO`
- Harness: [`scripts/perf_measurement.py`](/Users/henrychien/Documents/Jupyter/risk_module/scripts/perf_measurement.py)
- Cold pattern: clear cache, log in, fetch `/api/v2/portfolios`, fetch `GET /api/portfolios/{name}`, then fire the default overview burst in parallel
- Warm pattern: repeat the same burst `3` times without another cache clear
- Default overview burst:
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
- Important interpretation note:
  - the harness prints both endpoint-sum totals and parallel wall time
  - for comparison with the March 19 baseline, **parallel wall time is the meaningful number**
  - endpoint-sum totals are still useful for spotting which routes are expensive inside the burst

## Key Findings

- The March 19 cold/warm shape has regressed on the combined cold path and on single-account warm behavior.
- The current kept-state overview baseline is:
  - single-account parallel wall: **1.36s cold**, **335.95ms warm p50**
  - combined parallel wall: **4.08s cold**, **156.06ms warm p50**
- Combined warm behavior is still acceptable, but no longer in the March 19 class.
- Combined cold is now dominated by a shared cold analysis/holdings path again.
- Single-account cold wall is still good, but single-account warm p50 wall is materially noisier than March 19.

## Comparison To March 19 Baseline

| Scope | March 19 Cold Wall (ms) | March 23 Cold Wall (ms) | March 19 Warm Wall p50 (ms) | March 23 Warm Wall p50 (ms) |
|---|---:|---:|---:|---:|
| Single Account | 1,569.12 | 1,356.55 | 156.32 | 335.95 |
| All Accounts | 1,640.15 | 4,075.04 | 115.45 | 156.06 |

## Burst Wall

| Scope | Cold Parallel Wall (ms) | Warm Parallel Samples (ms) | Warm Parallel p50 (ms) | Warm Parallel p95 (ms) |
|---|---:|---|---:|---:|
| Single Account | 1,356.55 | 273.46, 335.95, 485.50 | 335.95 | 485.50 |
| All Accounts | 4,075.04 | 150.69, 156.06, 162.08 | 156.06 | 162.08 |

## Bootstrap + Default Overview Endpoints

| Endpoint | Single Cold (ms) | Single Warm p50 | Single Size (KB) | All Cold (ms) | All Warm p50 | All Size (KB) | Notes |
|---|---:|---:|---:|---:|---:|---:|---|
| `GET /api/v2/portfolios` | 84.61 | n/a | 1.8 | 102.60 | n/a | 1.8 | bootstrap list |
| `GET /api/portfolios/{name}` | 776.73 | n/a | 3.0 | 623.39 | n/a | 4.4 | combined virtual bootstrap is noticeably slower than March 19 |
| `POST /api/analyze` | 1,241.60 | 272.40 | 0.3 | 4,073.88 | 149.17 | 118.6 | dominant combined cold owner |
| `POST /api/risk-score` | 1,240.87 | 269.86 | 0.3 | 3,995.71 | 74.36 | 86.6 | waits on the cold shared analysis path |
| `GET /api/positions/holdings` | 1,355.91 | 8.40 | 17.1 | 3,857.42 | 12.56 | 33.8 | cold risk enrichment is the main holdings owner |
| `GET /api/positions/ai-recommendations` | 1,237.98 | 72.07 | 0.0 | 3,837.99 | 43.57 | 0.0 | cold AI recommendation generation is back in the critical path |
| `POST /api/performance/realized` | 828.62 | 70.65 | 21.2 | 2,679.51 | 73.28 | 21.5 | still cold-expensive on combined |
| `GET /api/income/projection` | 254.68 | 78.52 | 10.2 | 2,939.39 | 71.84 | 20.0 | combined cold now pays both position load and dividend history fetch |
| `GET /api/positions/market-intelligence` | 447.13 | 77.63 | 0.1 | 1,920.98 | 70.36 | 2.9 | no longer the worst cold owner, but still nontrivial |
| `GET /api/allocations/target` | 471.53 | 83.25 | 0.1 | 444.45 | 73.51 | 0.1 | small endpoint, but currently noisier than expected |
| `GET /api/positions/alerts` | 507.03 | 111.76 | 0.0 | 1,306.20 | 14.36 | 1.0 | shares the cold holdings load path |

## Optional Routes

- `GET /api/positions/metric-insights`
  - single-account: **721.74ms**
  - combined: **1,313.56ms**
- `GET /api/trading/analysis`
  - single-account: **2,382.92ms**
  - combined: **2,846.32ms**

These remain follow-on routes, not overview blockers, but they are still slow enough to matter for the Performance view.

## Recent Workflow Timing Breakdown

From `/api/debug/timing?kind=step&minutes=15` immediately after the rerun:

- `api_get_portfolio_workflow`: **879.23ms avg**
  - `build_portfolio_display_data`: **710.69ms**
- `positions_holdings_workflow`: **2,656.27ms avg**
  - `enrich_positions_with_risk`: **1,448.61ms**
  - `get_all_positions`: **475.22ms**
  - `enrich_positions_with_market_data`: **302.14ms**
  - `apply_scope_filter`: **282.12ms**
  - `enrich_positions_with_sectors`: **161.38ms**
- `api_analyze_workflow`: **963.30ms avg**
  - `analyze_portfolio`: **714.60ms**
  - `build_response`: **136.23ms**
- `api_risk_score_workflow`: **860.29ms avg**
  - `load_analysis_result`: **745.20ms**
- `build_portfolio_view`: **2,272.71ms avg**
  - `factor_exposures`: **1,905.77ms**
  - `get_returns`: **336.09ms**
- `realized_performance_workflow`: **395.00ms avg**
  - `load_realized_performance_payload`: **392.59ms**
- `portfolio_service_realized_performance`: **1,298.86ms avg**
  - `run_aggregation`: **1,297.90ms**
- `income_projection_workflow`: **2,034.00ms avg**
  - `load_positions`: **978.96ms**
  - `fetch_dividend_data`: **1,050.92ms**
- `ai_recommendations_workflow`: **3,565.02ms avg**
  - `recommend_portfolio_offsets`: **3,564.38ms**
- `metric_insights_workflow`: **797.96ms avg**
  - `load_alpha_flags`: **757.58ms**
- `market_intelligence_workflow`: **997.15ms avg**
  - `load_analyst_rating_events`: **779.61ms**
  - `load_insider_trade_events`: **485.07ms**
  - `load_estimate_revisions`: **374.29ms**

## Attempted And Reverted During This Pass

Two prewarm experiments were tested and explicitly backed out:

1. auth-time combined-dashboard prewarm
2. bootstrap-time AI recommendations prewarm

Both made startup noisier by adding more competing background work during the same cold window. The kept code does **not** include either experiment.

## Interpretation

- The remaining problem is no longer basic route duplication.
- The current cold wall is concentrated in four places:
  1. factor-exposure work inside `build_portfolio_view`
  2. AI recommendation generation inside `recommend_portfolio_offsets`
  3. holdings risk enrichment
  4. income position+dividend cold load
- More prewarm fan-out is not the right next move. The March 23 failed experiments showed that clearly.

## Recommendation

If perf work continues after this checkpoint, the next pass should avoid more startup prewarm breadth and instead target the inner cold computations directly:

1. `build_portfolio_view.factor_exposures`
2. `recommend_portfolio_offsets`
3. holdings risk enrichment reuse
4. income dividend-history fetch strategy

The best next engineering direction is likely a deeper factor-analysis/proxy optimization, not another dashboard orchestration change.

# Backend Performance Optimization Plan

**Status:** ACTIVE  
**Updated:** 2026-03-16  
**Primary Goal:** Reduce the remaining `"All Accounts"` dashboard tail latency after the shared-snapshot and bootstrap-deduplication pass.  
**Related Docs:** `docs/planning/PERFORMANCE_BASELINE_2026-03-10.md`, `docs/planning/PERFORMANCE_BASELINE_2026-03-15.md`, `docs/planning/PERFORMANCE_BASELINE_2026-03-16.md`, `docs/planning/REVIEW_FINDINGS.md`, `docs/planning/completed/performance/BACKEND_PERFORMANCE_PLAN.md`, `docs/planning/completed/performance/BACKEND_PERFORMANCE_PHASE2_PLAN.md`

## Checkpoint — 2026-03-16

This plan has now completed the original Phase 1 through Phase 6 execution sequence.

The current March 16 checkpoint is the authenticated admin-cache-clear rerun in `docs/planning/PERFORMANCE_BASELINE_2026-03-16.md`. It supersedes the earlier March 16 reload-based draft.

### Landed

- Phase 1 workflow-level timing instrumentation is in place.
- Phase 2 bootstrap pricing deduplication is in place.
- Phase 3 short-lived shared workflow setup caching for `analyze` / `risk-score` / `performance` is in place.
- Phase 4 short-lived shared position snapshots across holdings / alerts / income / intelligence are in place.
- Phase 5 threadpool cleanup for `routes/income.py`, `routes/realized_performance.py`, and `routes/factor_intelligence.py` is in place.
- Phase 6 remeasurement is captured in `docs/planning/PERFORMANCE_BASELINE_2026-03-16.md`.

### Current Outcome

- Single-account warm dashboard burst `p50` is now **1.78s** and `p95` is **2.09s**.
- Combined-account warm dashboard burst `p50` is now **7.86s** and `p95` is **9.04s**.
- The original combined warm-path target is now met under the correct admin cache-clear reset.
- Bootstrap is no longer a meaningful warm-path bottleneck.
- The remaining slow surfaces are `market-intelligence`, `metric-insights`, `income`, `performance`, and `holdings`. `analyze` and `risk-score` are now mostly out of the critical path except for occasional tail spikes.

### Implication

The next pass should stop framing this as a whole-dashboard setup problem. The remaining work is endpoint-level tail latency:

- instrument and reduce the downstream fetch path inside `market-intelligence`
- reduce or defer `performance` attribution enrichment
- make `metric-insights` consume existing `performance` / portfolio-context outputs
- reduce `income` dividend-history cost and holdings market-data enrichment cost before considering any API-shape change

## Scope

This plan replaces the earlier task-style draft in this file.

It is intentionally limited to work that still appears to be relevant in the current repo:

- refresh the baseline on current code
- eliminate duplicate bootstrap pricing
- share portfolio/position snapshots across the main dashboard endpoints
- close the remaining heavy sync-in-async route gaps

It should **not** spend time redoing already-completed perf phases.

## Current State

### Already Landed

These items are already present in the codebase and should not be re-planned as new work:

- Core analysis routes in `app.py` already use `run_in_threadpool()` for `/api/analyze`, `/api/risk-score`, `/api/performance`, and other heavy handlers.
- `routes/positions.py` already wraps holdings/alerts/export/market-intelligence/AI-insights work in `run_in_threadpool()`.
- Workflow-level backend timing instrumentation is already in place for the main burst paths.
- Bootstrap pricing deduplication is already in place between `GET /api/portfolios/{name}` and `PortfolioInitializer`.
- Shared workflow setup caching is already in place for `analyze`, `risk-score`, and `performance`.
- Shared position snapshot caching is already in place for holdings / alerts / income / intelligence.
- Remaining active sync route gaps in `routes/income.py`, `routes/realized_performance.py`, and `routes/factor_intelligence.py` have already been moved off the event loop.
- Session `last_accessed` writes are already throttled in `app_platform/auth/stores.py`.
- `PortfolioService.analyze_portfolio()` already does cache-before-classification and Redis/L1 backfill handling.
- `core/portfolio_analysis.py` already runs `build_portfolio_view()` and `calc_max_factor_betas()` concurrently.
- Request timing middleware and `/api/debug/timing` already exist.

### Existing Evidence

- `docs/planning/PERFORMANCE_BASELINE_2026-03-10.md` still shows cold dashboard load at roughly 49s and slow `POST /api/analyze`, `POST /api/risk-score`, and `POST /api/performance`.
- `docs/planning/REVIEW_FINDINGS.md` still records user-visible pain at portfolio switch (`R3`), initial holdings/race behavior (`R4`), and excessive request volume (`R17`).
- The March 10 baseline predates some later fixes, so it is directionally useful but must be refreshed before new optimization work starts.
- `docs/planning/PERFORMANCE_BASELINE_2026-03-16.md` is now the current checkpoint baseline after rerunning with authenticated `POST /admin/clear_cache`. It shows single-account warm burst `p50` at `1.78s` and combined-account warm burst `p50` at `7.86s`, with the remaining combined warm pressure led by `market-intelligence`, `metric-insights`, `income`, and `performance`.

## Current Request Graph

### Bootstrap

1. `usePortfolioList()` calls `GET /api/v2/portfolios`.
2. `PortfolioInitializer` calls `GET /api/portfolios/{portfolio_name}`.
3. That backend route already goes through `transform_portfolio_for_display()`, which calls `PortfolioService.refresh_portfolio_prices()`.
4. Current `PortfolioInitializer` skips the immediate `POST /api/portfolio/refresh-prices` call when the GET response already reports `prices_refreshed=true`.

### Main Dashboard Load

Once a current portfolio exists, the frontend schedules or mounts:

- `positions`
- `risk-score`
- `risk-analysis`
- `risk-profile`
- `performance`
- `portfolio-summary`
- `smart-alerts`
- `market-intelligence`
- `ai-recommendations`
- `metric-insights`

The main issue is no longer bootstrap duplication or missing caching infrastructure. The remaining pain is downstream enrichment, dividend/event fetch work, and a few user-scoped intelligence endpoints that still contend badly inside the combined burst.

## Confirmed Remaining Bottlenecks

### 1. `metric-insights` Still Recomputes Heavy Derived Layers

Confirmed paths:

- `build_metric_insights()` in `mcp_tools/metric_insights.py`
- `generate_position_flags()` in `core/position_flags.py`
- `_run_risk_score_workflow()` in `app.py`
- `_run_performance_workflow()` in `app.py`

Current behavior:

- `metric-insights` still layers position-flag generation, portfolio-context loading, risk-score flags, and performance flags into one request
- the authenticated March 16 baseline shows `metric_insights_workflow` averaging roughly `2.0s` in `load_performance_flags`, `1.7s` in `load_portfolio_context`, and `0.18s` in `load_risk_score_flags`

Impact:

- it is still one of the slowest combined warm auxiliaries at roughly `3.94s` `p50`
- it likely duplicates work that the dashboard already paid for elsewhere in the burst

### 2. Holdings / Income Still Pay For Data Fetches After Snapshot Reuse

Confirmed paths:

- `_load_enriched_positions()` in `routes/positions.py`
- `_build_portfolio_alerts_payload()` in `routes/positions.py`
- `_load_positions_for_income()` in `mcp_tools/income.py`
- `PositionService.get_all_positions()` in `services/position_service.py`
- `PortfolioService.enrich_positions_with_risk()` in `services/portfolio_service.py`

Current behavior:

- the shared position snapshot now collapses chained follow-up calls, but holdings still pays for first-hit position and market-data work, and income still pays for both positions and dividend history
- holdings risk enrichment is no longer the main issue; market-data enrichment is now more expensive than risk enrichment in the measured path
- the authenticated March 16 baseline shows holdings averaging roughly `1.71s` in `get_all_positions` and `0.89s` in `enrich_positions_with_market_data`; income averages roughly `1.88s` in `get_all_positions` and `2.31s` in `fetch_dividend_history`

Impact:

- holdings and income remain material contributors to the combined burst
- the position snapshot work helped, but it did not eliminate the underlying first-hit provider, pricing, and dividend-history cost

### 3. Performance Still Spends Material Time In Attribution Enrichment

Confirmed paths:

- `_run_performance_workflow()` in `app.py`
- `PortfolioService.analyze_performance()` in `services/portfolio_service.py`

Current behavior:

- core performance analysis is no longer the only cost
- the authenticated March 16 baseline shows `api_performance_workflow` averaging roughly `1.98s` in `enrich_attribution_with_analyst_data` and only `0.08s` in `analyze_performance`

Impact:

- combined warm `POST /api/performance` is still around `2.69s` `p50`
- performance remains one of the main overview blockers even after setup reuse landed

### 4. User-Scoped Intelligence Endpoints Still Inflate The Combined Burst

Confirmed gaps:

- `build_market_events()` in `mcp_tools/news_events.py`
- `build_ai_recommendations()` in `mcp_tools/factor_intelligence.py`
- `build_metric_insights()` in `mcp_tools/metric_insights.py`

Current behavior:

- `market-intelligence`, `ai-recommendations`, and `metric-insights` are still user-scoped in the current frontend contract
- they are not aligned with the portfolio-scoped resolver path, so they can still miss some reuse opportunities or contend badly with the main burst

Impact:

- even after the snapshot and threadpool work, combined warm `market-intelligence` is still `7.86s`, `metric-insights` is `3.94s`, and `ai-recommendations` is `0.71s`
- `market-intelligence` is now the clearest remaining combined warm blocker. Its measured position-load substeps are much smaller than the end-to-end request time, which implies downstream event/news fetching is now the main cost.

## Non-Primary Observations

- `portfolio-summary` is eager and bypasses part of the resolver dependency graph, but `PortfolioCacheService` already coalesces in-flight `riskAnalysis`, `riskScore`, and `performance` requests. Treat this as sequencing cleanup, not the main backend target.
- Bootstrap double pricing and the remaining active async/threadpool gaps are no longer the primary issues for this plan.
- `POST /api/factor-intelligence/portfolio-recommendations` is still not part of the main dashboard path. Only optimize it if product usage changes.

## Success Metrics

| Metric | Current Reference | Target For Next Pass |
|---|---:|---:|
| Warm CURRENT_PORTFOLIO dashboard burst | 7.86s p50 / 9.04s p95 | keep p50 <8s and p95 <10s |
| Warm single-account dashboard burst | 1.78s p50 / 2.09s p95 | keep <2.5s |
| Warm `GET /api/portfolios/{name}` bootstrap | ~43ms | keep <100ms |
| Warm combined `POST /api/analyze` | 0.74s p50 / 2.17s p95 | keep p50 <1.5s and reduce p95 tail |
| Warm combined `POST /api/risk-score` | 0.35s p50 / 2.06s p95 | keep p50 <1s and reduce p95 tail |
| Warm combined `POST /api/performance` | 2.69s p50 / 2.92s p95 | <2s |
| Warm combined holdings / alerts / income | 1.58s / 0.06s / 2.78s | <1.5s / <0.25s / <2s |
| Warm combined intelligence endpoints | 7.86s / 0.71s / 3.94s | <5s / <1s / <3s |
| Heavy sync work inside active `async` routes | removed | keep at none |

## Workstreams

### Phase 0. Refresh the Baseline on Current Code [DONE]

Do this before changing behavior.

Measure:

- single account
- `CURRENT_PORTFOLIO`
- cold cache and warm cache

Use:

- `/api/debug/timing`
- a fresh browser waterfall
- request counts, p50/p95, response sizes

Deliverable:

```
| Endpoint | Single p50 | All Accounts p50 | p95 | Size | Notes |
```

This replaces the March 10 baseline as the source of truth for the new pass.

### Phase 1. Add Workflow-Level Timers [DONE]

Add step timing around the current workflow boundaries rather than only the inner math functions.

Primary files:

- `app.py`
- `routes/positions.py`
- `routes/income.py`
- `routes/realized_performance.py`
- `services/performance_helpers.py`
- `mcp_tools/income.py`

Minimum step breakdowns to add:

- analyze: `load_portfolio_data`, `resolve_risk_limits`, `ensure_factor_proxies`, `service_analyze_portfolio`
- risk-score: `load_portfolio_data`, `resolve_risk_limits`, `ensure_factor_proxies`, `service_analyze_risk_score`
- performance: `load_portfolio_data`, `performance_service_call`
- holdings: `get_all_positions`, `sector_enrichment`, `market_data_enrichment`, `risk_enrichment`, `flag_generation`
- income: `get_all_positions`, `fetch_dividend_history`, `fetch_dividend_calendar`, `build_projection`
- realized performance: `load_portfolio_for_performance`, `analyze_realized_performance`, optional attribution enrichment

Acceptance:

- `/api/debug/timing` can show where duplicate work still lives
- the top offenders can be ranked by real workflow cost, not guesswork

### Phase 2. Remove Bootstrap Double Pricing [DONE]

Preferred direction:

- keep `GET /api/portfolios/{name}` as the priced bootstrap response
- make `PortfolioInitializer` skip the immediate `refreshPortfolioPrices()` call when the GET response already contains priced holdings/market values

Alternative:

- strip pricing out of the GET route and make the frontend own refresh explicitly

The alternative is higher risk because it changes the meaning of the bootstrap route.

Acceptance:

- only one pricing pass occurs during initial portfolio bootstrap
- no regression in displayed holdings values or total portfolio value

### Phase 3. Share Portfolio Context Across Analyze / Risk-Score / Performance [DONE]

Introduce a short-lived backend snapshot keyed by:

- `user_id`
- `portfolio_name`
- scope
- period/benchmark where relevant

Snapshot contents should include at least:

- `PortfolioData`
- resolved `RiskLimitsData`
- ensured factor proxies
- any safe reusable standardized weights or summary object

Adopt it in:

- `_run_analyze_workflow()` in `app.py`
- `_run_risk_score_workflow()` in `app.py`
- `_run_performance_workflow()` in `app.py`

Explicit investigation items:

1. `run_risk_score_analysis()` currently appears to rebuild the heavy portfolio view.
2. `analyze_performance()` still uses temp-file indirection even though the route already has `PortfolioData`.

Acceptance:

- the dashboard burst no longer performs three independent portfolio-load/proxy-ensure passes
- request timing shows prep work is shared rather than repeated

### Phase 4. Share Position Snapshots Across Holdings / Alerts / Income / Intelligence [DONE]

Introduce a short-lived `PositionSnapshotService` keyed by:

- `user_id`
- `portfolio_name`
- resolved scope
- institution/account filters when present

Use it in:

- `routes/positions.py`
- `mcp_tools/income.py`
- `mcp_tools/news_events.py`
- `mcp_tools/factor_intelligence.py`
- `mcp_tools/metric_insights.py`

Specific requirements:

- holdings should reuse an existing risk-analysis snapshot when possible instead of triggering a fresh `analyze_portfolio()` inside `enrich_positions_with_risk()`
- income projection should accept preloaded positions rather than fetching them again after the page already loaded positions
- market intelligence / AI recommendations / metric insights should accept injected `PositionResult` or a shared normalized holdings payload

Acceptance:

- one position snapshot can feed the main monitor-style endpoints during a refresh window
- page-load timing shows fewer repeated `get_all_positions()` chains

### Phase 5. Close the Remaining `async` Route Threadpool Gaps [DONE]

Wrap heavy sync route bodies with `run_in_threadpool()` or `asyncio.to_thread()` in:

- `routes/income.py`
- `routes/realized_performance.py`
- `routes/factor_intelligence.py`

Do not spend time re-wrapping the endpoints already fixed in `app.py` and `routes/positions.py`.

Acceptance:

- no active performance-sensitive route executes long-running sync work directly in `async def`

### Phase 6. Re-Measure and Decide Whether a Bigger API Shape Change Is Still Needed [DONE]

After Phases 2-5:

- rerun the fresh baseline
- compare request latency before/after
- confirm dashboard and portfolio-switch behavior manually

Only if targets are still missed should we consider a larger change such as a dedicated dashboard snapshot endpoint.

That endpoint is explicitly a fallback, not the first move.

## Next Pass Candidates

If optimization work continues, the next pass should be narrower and deeper:

1. Instrument and reduce the downstream event/news fetch path inside `market-intelligence`.
2. Cache, defer, or reuse `performance` attribution enrichment outputs.
3. Feed those same outputs into `metric-insights` instead of rebuilding portfolio-context and performance-derived layers.
4. Reduce `income` dividend-history fetch cost and holdings market-data enrichment cost.
5. Only if those do not move the combined p95 enough, introduce a dedicated dashboard snapshot endpoint for the overview path.

## File Map

| Workstream | Likely Files |
|---|---|
| Baseline + timers | `app_platform/middleware/timing.py`, `routes/debug.py`, `app.py`, `routes/positions.py`, `routes/income.py`, `routes/realized_performance.py`, `services/performance_helpers.py`, `mcp_tools/income.py` |
| Bootstrap pricing dedupe | `app.py`, `frontend/packages/connectors/src/providers/PortfolioInitializer.tsx` |
| Shared portfolio snapshot | `app.py`, `services/portfolio_service.py`, `services/portfolio/context_service.py` or a new helper module |
| Shared position snapshot | `services/position_service.py`, `routes/positions.py`, `mcp_tools/income.py`, `mcp_tools/news_events.py`, `mcp_tools/factor_intelligence.py`, `mcp_tools/metric_insights.py` |
| Async gap cleanup | `routes/income.py`, `routes/realized_performance.py`, `routes/factor_intelligence.py` |

## Execution Order

1. Keep the authenticated March 16 admin-cache-clear baseline as the current source of truth.
2. Instrument and optimize the downstream `market-intelligence` path.
3. Reduce or defer `performance` attribution enrichment and reuse those outputs in `metric-insights`.
4. Reduce `income` dividend-history cost and holdings market-data enrichment cost.
5. Re-measure before considering any larger API-shape change.

## Explicitly Out of Scope

- redoing the already-completed phase-2 backend perf items
- optimizing unused endpoints purely because they are slow
- changing public API response shapes in the first pass
- adding a monolithic dashboard endpoint before shared snapshot reuse has been attempted

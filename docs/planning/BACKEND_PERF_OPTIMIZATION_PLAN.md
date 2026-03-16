# Backend Performance Optimization Plan

**Status:** ACTIVE  
**Updated:** 2026-03-15  
**Primary Goal:** Reduce dashboard cold-load and `"All Accounts"` portfolio-switch latency by removing duplicate backend work in the current request burst.  
**Related Docs:** `docs/planning/PERFORMANCE_BASELINE_2026-03-10.md`, `docs/planning/PERFORMANCE_BASELINE_2026-03-15.md`, `docs/planning/REVIEW_FINDINGS.md`, `docs/planning/completed/performance/BACKEND_PERFORMANCE_PLAN.md`, `docs/planning/completed/performance/BACKEND_PERFORMANCE_PHASE2_PLAN.md`

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
- Session `last_accessed` writes are already throttled in `app_platform/auth/stores.py`.
- `PortfolioService.analyze_portfolio()` already does cache-before-classification and Redis/L1 backfill handling.
- `core/portfolio_analysis.py` already runs `build_portfolio_view()` and `calc_max_factor_betas()` concurrently.
- Request timing middleware and `/api/debug/timing` already exist.

### Existing Evidence

- `docs/planning/PERFORMANCE_BASELINE_2026-03-10.md` still shows cold dashboard load at roughly 49s and slow `POST /api/analyze`, `POST /api/risk-score`, and `POST /api/performance`.
- `docs/planning/REVIEW_FINDINGS.md` still records user-visible pain at portfolio switch (`R3`), initial holdings/race behavior (`R4`), and excessive request volume (`R17`).
- The March 10 baseline predates some later fixes, so it is directionally useful but must be refreshed before new optimization work starts.

## Current Request Graph

### Bootstrap

1. `usePortfolioList()` calls `GET /api/v2/portfolios`.
2. `PortfolioInitializer` calls `GET /api/portfolios/{portfolio_name}`.
3. That backend route already goes through `transform_portfolio_for_display()`, which calls `PortfolioService.refresh_portfolio_prices()`.
4. `PortfolioInitializer` may then immediately call `POST /api/portfolio/refresh-prices` for the same holdings.

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

The main issue is not missing caching infrastructure. The issue is that the backend still performs overlapping portfolio-load and position-load work across these entry points during the same burst.

## Confirmed Remaining Bottlenecks

### 1. Bootstrap Does Two Pricing Passes

Confirmed paths:

- `GET /api/portfolios/{portfolio_name}` in `app.py`
- `transform_portfolio_for_display()` in `app.py`
- `frontend/packages/connectors/src/providers/PortfolioInitializer.tsx`

Current behavior:

- the GET route already prices the holdings
- the frontend may immediately price them again

Impact:

- unnecessary FMP/pricing work before first useful render
- extra latency during portfolio bootstrap and portfolio switching

### 2. Analyze / Risk-Score / Performance Rebuild the Same Portfolio Context

Confirmed paths:

- `_run_analyze_workflow()` in `app.py`
- `_run_risk_score_workflow()` in `app.py`
- `_run_performance_workflow()` in `app.py`

Current behavior:

- `/api/analyze` loads portfolio data, resolves scope/risk limits, ensures factor proxies, then runs risk analysis
- `/api/risk-score` does the same portfolio load/proxy prep again, then `run_risk_score_analysis()`
- `/api/performance` loads portfolio data again and still goes through a temp-file-based performance path

Impact:

- the dashboard burst rebuilds the same portfolio context three times in parallel
- `/api/risk-score` appears to recompute the heavy `build_portfolio_view()` path instead of consuming `RiskAnalysisResult`

### 3. Holdings / Alerts / Income / Intelligence Rebuild the Same Position Snapshot

Confirmed paths:

- `_load_enriched_positions()` in `routes/positions.py`
- `PositionService.get_all_positions()` in `services/position_service.py`
- `get_income_projection()` in `mcp_tools/income.py`
- `build_market_events()` in `mcp_tools/news_events.py`
- `build_ai_recommendations()` in `mcp_tools/factor_intelligence.py`
- `build_metric_insights()` in `mcp_tools/metric_insights.py`

Current behavior:

- holdings loads positions and then calls `PortfolioService.enrich_positions_with_risk()`
- that risk enrichment converts positions back into a portfolio and runs `analyze_portfolio()` again
- alerts, income, market intelligence, AI recommendations, and metric insights all start from their own `get_all_positions()` call chain

Impact:

- CURRENT_PORTFOLIO page load fans out into repeated position fetch and enrichment work
- the holdings path may trigger a second full risk analysis on top of the dashboard risk-analysis request

### 4. Newer Heavy Routes Still Execute Sync Work Directly Inside `async def`

Confirmed gaps:

- `routes/income.py`
- `routes/realized_performance.py`
- `routes/factor_intelligence.py`

Current behavior:

- these route handlers are `async`, but they directly call heavy synchronous helpers/services without `run_in_threadpool()` or `asyncio.to_thread()`

Impact:

- they can still starve the event loop when used
- the old completed perf docs do not reflect these later-added gaps

### 5. Workflow-Level Timing Is Still Too Coarse

`/api/debug/timing` is useful, but it currently does not break out enough workflow boundaries to answer:

- how much time is portfolio load vs factor-proxy ensure vs analysis cache hit
- how much time is positions load vs risk enrichment vs dividend fetch
- whether page-load pain is dominated by duplicate prep work or by the final compute step

## Non-Primary Observations

- `portfolio-summary` is eager and bypasses part of the resolver dependency graph, but `PortfolioCacheService` already coalesces in-flight `riskAnalysis`, `riskScore`, and `performance` requests. Treat this as sequencing cleanup, not the main backend target.
- `POST /api/factor-intelligence/portfolio-recommendations` was the slowest endpoint in the March 10 baseline, but it is not part of the main dashboard path. Only do threadpool hygiene there unless product usage changes.

## Success Metrics

| Metric | Current Reference | Target For This Pass |
|---|---:|---:|
| Cold CURRENT_PORTFOLIO dashboard load | ~49s | <15s |
| All Accounts switch | ~30s timeout / error state | no timeout, p50 <10s cold |
| `GET /api/portfolios/{name}` bootstrap | ~2.2s plus second pricing call | single pricing pass, <1s warm |
| `POST /api/analyze` | 29.9s avg | <5s cold, <1s warm |
| `POST /api/risk-score` | 37.8s avg | <5s cold, <1s warm |
| `POST /api/performance` | 44.4s avg | <5s cold, <1s warm |
| Holdings / alerts / income endpoints | multi-second | <1.5s warm |
| Heavy sync work inside active `async` routes | present | none on active portfolio/performance surfaces |

## Workstreams

### Phase 0. Refresh the Baseline on Current Code

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

### Phase 1. Add Workflow-Level Timers

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

### Phase 2. Remove Bootstrap Double Pricing

Preferred direction:

- keep `GET /api/portfolios/{name}` as the priced bootstrap response
- make `PortfolioInitializer` skip the immediate `refreshPortfolioPrices()` call when the GET response already contains priced holdings/market values

Alternative:

- strip pricing out of the GET route and make the frontend own refresh explicitly

The alternative is higher risk because it changes the meaning of the bootstrap route.

Acceptance:

- only one pricing pass occurs during initial portfolio bootstrap
- no regression in displayed holdings values or total portfolio value

### Phase 3. Share Portfolio Context Across Analyze / Risk-Score / Performance

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

### Phase 4. Share Position Snapshots Across Holdings / Alerts / Income / Intelligence

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

### Phase 5. Close the Remaining `async` Route Threadpool Gaps

Wrap heavy sync route bodies with `run_in_threadpool()` or `asyncio.to_thread()` in:

- `routes/income.py`
- `routes/realized_performance.py`
- `routes/factor_intelligence.py`

Do not spend time re-wrapping the endpoints already fixed in `app.py` and `routes/positions.py`.

Acceptance:

- no active performance-sensitive route executes long-running sync work directly in `async def`

### Phase 6. Re-Measure and Decide Whether a Bigger API Shape Change Is Still Needed

After Phases 2-5:

- rerun the fresh baseline
- compare request latency before/after
- confirm dashboard and portfolio-switch behavior manually

Only if targets are still missed should we consider a larger change such as a dedicated dashboard snapshot endpoint.

That endpoint is explicitly a fallback, not the first move.

## File Map

| Workstream | Likely Files |
|---|---|
| Baseline + timers | `app_platform/middleware/timing.py`, `routes/debug.py`, `app.py`, `routes/positions.py`, `routes/income.py`, `routes/realized_performance.py`, `services/performance_helpers.py`, `mcp_tools/income.py` |
| Bootstrap pricing dedupe | `app.py`, `frontend/packages/connectors/src/providers/PortfolioInitializer.tsx` |
| Shared portfolio snapshot | `app.py`, `services/portfolio_service.py`, `services/portfolio/context_service.py` or a new helper module |
| Shared position snapshot | `services/position_service.py`, `routes/positions.py`, `mcp_tools/income.py`, `mcp_tools/news_events.py`, `mcp_tools/factor_intelligence.py`, `mcp_tools/metric_insights.py` |
| Async gap cleanup | `routes/income.py`, `routes/realized_performance.py`, `routes/factor_intelligence.py` |

## Execution Order

1. Refresh baseline on current code.
2. Add workflow-level timers.
3. Remove bootstrap double pricing.
4. Share portfolio context across analyze/risk-score/performance.
5. Share position snapshots across holdings/income/intelligence.
6. Close remaining async/threadpool gaps.
7. Re-measure and decide whether a larger API-shape change is still necessary.

## Explicitly Out of Scope

- redoing the already-completed phase-2 backend perf items
- optimizing unused endpoints purely because they are slow
- changing public API response shapes in the first pass
- adding a monolithic dashboard endpoint before shared snapshot reuse has been attempted

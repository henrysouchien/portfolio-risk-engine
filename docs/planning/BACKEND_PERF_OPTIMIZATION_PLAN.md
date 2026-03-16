# Backend Performance Optimization Plan

**Status:** ACTIVE  
**Updated:** 2026-03-16  
**Primary Goal:** Reduce the remaining cold first-hit `"All Accounts"` dashboard latency now that the warm-path deduplication pass is largely complete.  
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
- This authenticated rerun should remain the formal baseline checkpoint even though later March 16 spot checks are materially faster.

### Implication

The next pass should stop framing this as a whole-dashboard setup problem. The remaining work is endpoint-level tail latency:

- instrument and reduce the downstream fetch path inside `market-intelligence`
- reduce or defer `performance` attribution enrichment
- make `metric-insights` consume existing `performance` / portfolio-context outputs
- reduce `income` dividend-history cost and holdings market-data enrichment cost before considering any API-shape change

## Post-Baseline Progress — Later 2026-03-16

Additional optimization work landed after the authenticated baseline rerun. Those later changes should be treated as a post-baseline checkpoint, not a replacement for the baseline document.

### Landed Since The Baseline

- `market-intelligence` switched back onto cacheable FMP fetch paths and now parallelizes its independent downstream loaders.
- `metric-insights` now reuses shared `risk-score` / `performance` outputs instead of rebuilding its own full derived stack.
- `performance` supports a lighter no-attribution path for `metric-insights`, and analyst enrichment now reuses short-lived snapshots.
- warm dashboard snapshots and result caches now live long enough to make immediate repeat loads actually reuse them.
- `PositionService` cold setup work was tightened substantially: concurrent default-registry construction is deduped, missing factor-proxy base builds are parallelized, missing ticker resolution is deduped/parallelized, FX lookups are memoized, and provider fetches are pruned to active user providers.
- stale provider refresh failures now fall back to cached positions instead of dropping the provider entirely.
- cached provider quote lookups now use a short-lived shared FMP quote cache with in-flight dedupe.
- dividend-history loading now dedupes the repeated warm path instead of refetching it every time.

### Current Outcome

- later localhost warm-repeat spot checks brought the combined dashboard burst down to roughly **533ms** end-to-end.
- the latest warm per-endpoint spot checks were roughly: `analyze` **531ms**, `market-intelligence` **523ms**, `income` **510ms**, `ai-recommendations` **487ms**, `performance` **126ms**, `risk-score` **119ms**, `metric-insights` **84ms**, and `holdings` **50ms**.
- concurrent fresh `PositionService(...)` initialization dropped from roughly **10.05s** to roughly **371ms**.
- first-hit `ensure_factor_proxies` work in the `risk-score` path dropped from roughly **2.29s** to roughly **199ms**.
- direct cold `get_all_positions()` probes dropped from roughly **6.7s** to roughly **1.8s**. Plaid now stays on its intended cache path instead of paying for unrelated broker-order invalidation, IBKR can reuse a recent cached snapshot when no order state changed since the last sync, and the current-user scope still correctly skips `snaptrade`.
- expired Schwab auth now fast-fails on repeat probes in the same process instead of re-paying the full token failure path each time.
- real cold `GET /api/positions/holdings` after authenticated cache clear now lands around **1.50s**, with an immediate repeat around **17ms**.
- full cold dashboard spot checks are still variable, roughly **7s** to **13s**, and now track live provider latency much more than local duplicate setup.

### Implication

The original warm-path dashboard problem is effectively closed. The remaining work is narrower:

- cold first-hit provider fetch latency inside `PositionService.get_all_positions()`
- cold downstream fetch work layered on top of positions, especially `market-intelligence` and `income`
- only secondarily, any residual response-assembly overhead once the provider path is under control

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
- `docs/planning/PERFORMANCE_BASELINE_2026-03-16.md` is the formal authenticated checkpoint baseline after rerunning with authenticated `POST /admin/clear_cache`. It shows single-account warm burst `p50` at `1.78s` and combined-account warm burst `p50` at `7.86s`.
- Later March 16 spot checks after the follow-on optimization commits show the warm-repeat path is now far faster than the formal baseline. The remaining issue is cold first-hit provider latency, not broad dashboard duplication.

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

The main issue is no longer bootstrap duplication or missing caching infrastructure. After the later March 16 follow-on work, the remaining pain is mostly the first shared cold `get_all_positions()` chain plus downstream fetch work layered on top of that cold path.

## Confirmed Remaining Bottlenecks

### 1. Cold `get_all_positions()` Is Now Dominated By Real Provider Fetch Latency

Confirmed paths:

- `PositionService.get_all_positions()` in `services/position_service.py`
- `PositionService._get_positions_df()` in `services/position_service.py`
- `PositionService._fetch_fresh_positions()` in `services/position_service.py`
- active provider loaders for `plaid`, `schwab`, and `ibkr`

Current behavior:

- the major local duplicate setup has already been removed
- current cold probes now spend about **1.8s** inside the first shared positions load after provider pruning, setup dedupe, provider-scoped order invalidation, cached fallback reuse, and shared quote caching
- the remaining providers for the current local user are `plaid`, `schwab`, `ibkr`, and `csv`; `snaptrade` is now skipped correctly
- Plaid and IBKR now both stay on cache in the measured cold path when nothing changed since the snapshot, and stale Schwab auth no longer drops Schwab rows from the combined result

Impact:

- the first cold positions load still dominates multiple downstream endpoints because holdings, alerts, income, and intelligence all depend on it
- further dashboard-level caching will not move this much unless the provider path itself changes

### 2. Cold `market-intelligence` Still Pays For External Fetch Work After Position Reuse

Confirmed paths:

- `build_market_events()` in `mcp_tools/news_events.py`
- downstream FMP/news/event loaders in `fmp/tools/news_events.py`

Current behavior:

- the warm path is now fast, but cold `market-intelligence` still lands around **6.7s** after cache clear
- warm follow-ups are already down in the low hundreds of milliseconds, which means the remaining issue is the first-hit external fetch path rather than repeated local recompute
- position loading is no longer the dominant warm cost here; the downstream news/event fetch layer is

Impact:

- `market-intelligence` remains one of the clearest cold first-hit blockers once the shared positions load completes
- this is now a fetch-policy / caching problem more than a workflow-duplication problem

### 3. Cold `income` Still Pays For Dividend-History Fetches After Position Reuse

Confirmed paths:

- `_load_positions_for_income()` in `mcp_tools/income.py`
- dividend-history loaders in `mcp_tools/income.py`

Current behavior:

- the shared positions path now helps repeated loads, and the warm-repeat income path is much better than the baseline
- the remaining cold income cost is no longer position rebuilding by itself; it is the combination of first-hit positions plus dividend-history fetches
- immediate repeat income calls now drop sharply once the shared snapshot survives long enough, which confirms the remaining cost is mostly first-hit work

Impact:

- cold dashboard bursts still inherit this extra dividend-history cost even after the broader dedupe pass
- income no longer justifies a broad architecture change, but it still has targeted first-hit fetch work left

### 4. Warm Repeat Performance / Holdings Are Good Enough; Further Work Should Stay Cold-Path Focused

Confirmed paths:

- `_run_analyze_workflow()` in `app.py`
- `_run_risk_score_workflow()` in `app.py`
- `_run_performance_workflow()` in `app.py`
- `_load_enriched_positions()` in `routes/positions.py`

Current behavior:

- latest warm-repeat spot checks are already well below the original target envelope
- `performance`, `risk-score`, `metric-insights`, and `holdings` all have credible sub-second warm paths now
- the main remaining warm owners are narrower auxiliary endpoints like `market-intelligence`, `income`, and `ai-recommendations`, not the core risk stack

Impact:

- additional broad snapshot layers or API-shape changes are unlikely to be the highest-value next move
- the plan should stay focused on provider-specific cold fetch behavior and a few cold external loaders

## Non-Primary Observations

- `portfolio-summary` is eager and bypasses part of the resolver dependency graph, but `PortfolioCacheService` already coalesces in-flight `riskAnalysis`, `riskScore`, and `performance` requests. Treat this as sequencing cleanup, not the main backend target.
- Bootstrap double pricing, warm snapshot reuse, and the remaining active async/threadpool gaps are no longer the primary issues for this plan.
- `POST /api/factor-intelligence/portfolio-recommendations` is still not part of the main dashboard path. Only optimize it if product usage changes.

## Success Metrics

| Metric | Current Reference | Target For Next Pass |
|---|---:|---:|
| Warm CURRENT_PORTFOLIO dashboard burst | 7.86s p50 / 9.04s p95 formal baseline; ~0.53s later warm spot check | keep the repeat path sub-second |
| Warm single-account dashboard burst | 1.78s p50 / 2.09s p95 | keep <2.5s |
| Warm `GET /api/portfolios/{name}` bootstrap | ~43ms | keep <100ms |
| Warm combined `POST /api/analyze` | 0.74s p50 / 2.17s p95 formal baseline; ~531ms later spot check | keep <1s repeat |
| Warm combined `POST /api/risk-score` | 0.35s p50 / 2.06s p95 formal baseline; ~119ms later spot check | keep <500ms repeat |
| Warm combined `POST /api/performance` | 2.69s p50 / 2.92s p95 formal baseline; ~126ms later spot check | keep <500ms repeat |
| Warm combined holdings / alerts / income | 1.58s / 0.06s / 2.78s formal baseline; later repeat spot checks ~50ms / cheap / ~510ms | keep repeat holdings <250ms and repeat income <1s |
| Warm combined intelligence endpoints | 7.86s / 0.71s / 3.94s formal baseline; later repeat spot checks ~523ms / ~487ms / ~84ms | keep repeat path <1s each |
| Cold direct `get_all_positions()` | ~1.8s latest spot check | <1.5s |
| Cold CURRENT_PORTFOLIO dashboard burst | ~7-13s latest spot checks | keep first hit consistently <8s |
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

If optimization work continues, the next pass should stay narrow and cold-path focused:

1. Reduce first-hit provider latency in `PositionService.get_all_positions()`, starting with provider-specific freshness shortcuts or scoped fetch-policy changes.
2. Further trim cold downstream fetch work in `market-intelligence`.
3. Further trim cold dividend-history work in `income`.
4. Re-measure cold burst consistency before considering any larger API-shape change.
5. Only if those do not move the cold first-hit enough, introduce a dedicated dashboard snapshot endpoint for the overview path.

## File Map

| Workstream | Likely Files |
|---|---|
| Baseline + timers | `app_platform/middleware/timing.py`, `routes/debug.py`, `app.py`, `routes/positions.py`, `routes/income.py`, `routes/realized_performance.py`, `services/performance_helpers.py`, `mcp_tools/income.py` |
| Bootstrap pricing dedupe | `app.py`, `frontend/packages/connectors/src/providers/PortfolioInitializer.tsx` |
| Shared portfolio snapshot | `app.py`, `services/portfolio_service.py`, `services/portfolio/context_service.py` or a new helper module |
| Shared position snapshot | `services/position_service.py`, `routes/positions.py`, `mcp_tools/income.py`, `mcp_tools/news_events.py`, `mcp_tools/factor_intelligence.py`, `mcp_tools/metric_insights.py` |
| Async gap cleanup | `routes/income.py`, `routes/realized_performance.py`, `routes/factor_intelligence.py` |

## Execution Order

1. Keep the authenticated March 16 admin-cache-clear baseline as the formal checkpoint and the later March 16 spot checks as supporting evidence.
2. Reduce cold first-hit provider latency in `PositionService.get_all_positions()`.
3. Reduce cold downstream `market-intelligence` fetch work.
4. Reduce cold `income` dividend-history cost.
5. Re-measure before considering any larger API-shape change.

## Explicitly Out of Scope

- redoing the already-completed phase-2 backend perf items
- optimizing unused endpoints purely because they are slow
- changing public API response shapes in the first pass
- adding a monolithic dashboard endpoint before shared snapshot reuse has been attempted

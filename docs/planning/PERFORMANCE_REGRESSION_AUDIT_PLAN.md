# Performance Regression Audit Plan

**Status:** ACTIVE  
**Updated:** 2026-03-22  
**Primary Goal:** Re-run the March 2026 performance optimization playbook against the current frontend/backend stack, with equal emphasis on latency regressions and startup/state bugs that surfaced after recent UI and service changes.  
**Related Docs:** `docs/planning/PERFORMANCE_OPTIMIZATION_PLAYBOOK.md`, `docs/planning/BACKEND_PERF_OPTIMIZATION_PLAN.md`, `docs/planning/PERFORMANCE_BASELINE_2026-03-19.md`, `docs/TODO.md`

## Why This Pass Exists

The previous perf pass materially improved the default overview path, but the codebase has changed again:

- redesigned dashboard cards and views
- new settings/provider surfaces
- more startup orchestration around auth, services, portfolio bootstrap, and eager data prefetch
- reports of refresh-time regressions, false empty states, and auth/bootstrap hangs

This is no longer just a backend timing question. The active risk is a combined startup-state problem:

- auth status can feel hung
- page bootstrap can fail or stall on refresh
- some cards can present an empty/no-data state before the underlying state machine has fully settled

## Baseline Reference

The last known good backend reference remains `docs/planning/PERFORMANCE_BASELINE_2026-03-19.md`:

- single-account overview: **1.57s cold**, **149.07ms warm p50**
- combined overview: **1.64s cold**, **114.66ms warm p50**

This audit should compare current behavior against those numbers, but it must also track startup correctness:

- auth transition duration
- service readiness duration
- portfolio bootstrap duration
- request count on first authenticated load
- whether any startup card renders an incorrect empty state

## Initial Findings

### Startup Is The Highest-Risk Regression Surface

The current app gates startup across four layers:

1. auth initialization
2. session service creation
3. portfolio bootstrap
4. eager query prefetch

That means the user-visible “page hung” report can come from multiple places even when no single route is catastrophically slow.

### Startup-Critical Requests Were Too Willing To Wait

Initial audit found that several startup-critical calls were allowed to sit in retry/backoff paths longer than they should for first-load UX:

- `GET /auth/status`
- `GET /api/v2/portfolios`
- `GET /api/portfolios/{portfolio_name}`
- `POST /api/portfolio/refresh-prices`

This pass tightens those paths so startup fails fast instead of feeling indefinitely stuck.

### Loading Semantics Need Another Consistency Sweep

The repo now has mixed patterns for “still resolving” vs “truly empty”:

- some hooks/views explicitly guard initial pending state
- some rely directly on raw query loading state
- some cards present empty-state copy immediately once data is absent

This is a likely source of “data not loaded” style regressions even when the backend eventually succeeds.

### Dependency Readiness Was Not Scoped Tightly Enough

Initial audit also found a resolver-state bug:

- dependent sources were treating dependency readiness too globally
- cached dependency data from one portfolio could satisfy readiness for another
- waiting on dependencies could look idle instead of loading

That combination is a plausible cause of stale or incorrect first-render cards after refreshes and portfolio switches.

### Measured Rerun Confirms A Real Regression

Local authenticated rerun on **2026-03-22** against `127.0.0.1:5001` confirms this is not just a perception issue:

- `CURRENT_PORTFOLIO`
  - auth bootstrap remained healthy: `POST /auth/dev-login` **6.9ms** server, `GET /auth/status` **1.1ms**
  - bootstrap endpoints were also fine once the app was authenticated: `GET /api/v2/portfolios` **12.6ms**, `GET /api/portfolios/CURRENT_PORTFOLIO` **47.8ms**
  - the default overview burst regressed badly: **18.0s cold**, warm samples **580ms / 1038ms / 560ms**, warm **p50 580ms**
- `_auto_interactive_brokers_u2471778`
  - bootstrap remained acceptable: `GET /api/v2/portfolios` **19.1ms**, `GET /api/portfolios/{name}` **41.9ms**
  - the default overview burst regressed even harder: **31.0s cold**, warm samples **454ms / 2508ms / 848ms**, warm **p50 848ms**

Compared with the March 19 reference:

- combined warm overview regressed from **114.66ms** to **580.44ms p50**
- single-account warm overview regressed from **149.07ms** to **848.44ms p50**
- combined cold overview regressed from **1.64s** to **18.0s**
- single-account cold overview regressed from **1.57s** to **31.0s**

### Regression Owners Are Now Clearer

The rerun and `/api/debug/timing?minutes=5` point to two different classes of problems:

- **Cold path:** repeated `get_all_positions` work is extremely expensive again
  - `positions_holdings_workflow.get_all_positions`: ~**15.7s** avg inside the measured window
  - `load_portfolio_for_performance.get_all_positions`: ~**10.5s** avg
  - `market_intelligence_weight_load.get_all_positions`: ~**11.6s** avg
- **Warm path:** shared analysis work is too slow even after caches warm
  - `api_analyze_workflow` p50 landed around **500-1033ms** in the rerun
  - `api_risk_score_workflow` p50 landed around **194-968ms**
  - `build_portfolio_view.factor_exposures` averaged ~**1.65s** across actual builds in the timing window

The key conclusion from this slice:

- auth startup is no longer the dominant latency owner
- portfolio bootstrap itself is mostly healthy
- the current regression is concentrated in backend position loading plus warm analysis compute

### Shared Dashboard Prewarm Was Stalling First Interactive Calls

Follow-up repro on **2026-03-22** found a specific cache/prefetch bug in the bootstrap sequence:

- on the long-lived local dev server at `127.0.0.1:5001`, `GET /api/portfolios/CURRENT_PORTFOLIO` stayed fast, but the first interactive shared-future consumer could still hang behind background prewarm work
- before the fix, one repro showed `POST /api/analyze` at **842ms** followed by `POST /api/risk-score` at **15.03s**
- root cause: dashboard prewarm registered shared analysis/risk/performance futures, but those futures were still waiting on the cold live-position prewarm future to resolve before they built their snapshots
- request-time analyze/risk-score paths do **not** wait that way; they only reuse a cached position snapshot if it already exists

That mismatch meant the first user-triggered analyze/risk-score request could inherit a slow background future that was blocked on cold `get_all_positions`, even though the request-time path itself was designed to fail fast.

The fix in this slice aligns dashboard prewarm with request-time behavior:

- keep `prewarm_position_result_snapshot()` running in the background
- stop shared analysis/risk/performance futures from calling `.result()` on that cold position future
- only reuse the position snapshot if it is already warm in cache

Fresh-process validation on a clean server at `127.0.0.1:5002` after the fix:

- `GET /api/portfolios/CURRENT_PORTFOLIO`: **331ms**
- `POST /api/analyze`: **172ms**
- `POST /api/risk-score`: **10ms**

Note: a long-lived dev process that already has an old in-flight snapshot future can still show one stale wait until the process is restarted or the short-lived snapshot TTL rolls over.

### Startup-Facing Position Reads Now Decouple From Slow Live Refresh

Follow-up validation on **2026-03-22** addressed the remaining cold-path owner: startup-facing holdings, income, and realized-performance requests were still able to inherit a slow strict `get_all_positions` refresh when providers were stale.

The fix in this slice adds an explicit stale-tolerant read mode for startup-facing consumers:

- `PositionService.get_all_positions(... allow_stale_cache=True)` can now return cached provider data immediately even when the live freshness window has expired
- shared position snapshots now key on `allow_stale_cache`, so stale-tolerant and strict readers do not reuse the same in-flight future
- realized-performance and income payload caches now also key on a `position_load_policy`, which prevents a route-level `stale_ok` request from attaching to a strict background prewarm future
- startup-facing routes now opt into the stale-tolerant path where that tradeoff is acceptable:
  - holdings
  - portfolio alerts
  - market-intelligence symbol/weight loads
  - default realized-performance payload
  - income projection

Fresh-process HTTP validation against `127.0.0.1:5002` after this change:

- `GET /api/positions/holdings?portfolio_name=CURRENT_PORTFOLIO`
  - cold: **1527.59ms**
  - warm: **5.87ms**
- `POST /api/performance/realized`
  - cold: **3473.17ms**
  - warm: **1331.44ms**
- `GET /api/income/projection?portfolio_name=CURRENT_PORTFOLIO`
  - cold: **507.37ms**
  - warm: **4.24ms**
- `GET /api/positions/market-intelligence`
  - cold: **427.57ms**
  - warm: **2.33ms**

Raw timing evidence confirms the intended cache split:

- strict background work still exists and can remain slow
  - at **2026-03-22T19:19:24Z**, `load_portfolio_for_performance.get_all_positions` took **15509.37ms**
  - at **2026-03-22T19:19:24Z**, `income_position_load_workflow.get_all_positions` took **15531.57ms**
- but route-facing stale-tolerant calls no longer wait on that work
  - at **2026-03-22T19:21:39Z**, realized-performance `load_portfolio_for_performance.get_all_positions` took **0.37ms**
  - at **2026-03-22T19:21:42Z**, income `get_all_positions` took **0.25ms**
  - at **2026-03-22T19:21:38Z**, holdings `get_all_positions` took **1105.30ms** instead of the earlier **14.6s+** cold stall

This changes the current owner picture:

- the worst startup-facing cold `get_all_positions` stalls are no longer gating the first user-visible holdings/income/market-intelligence paths
- realized performance still has meaningful latency, but it is now mostly downstream compute:
  - cold request: `load_realized_performance_payload` **1310.52ms**, `enrich_attribution` **2154.17ms**
  - warm request: `load_realized_performance_payload` **8.66ms**, `enrich_attribution` **1317.58ms**

One additional frontend-side regression also surfaced during this validation:

- the direct `realized-performance` resolver path left `includeAttribution` undefined
- `APIService.getRealizedPerformance()` treated that omission as `true`
- that meant some callers could pay the full attribution cost even when they never explicitly requested attribution

This slice flips the default back to summary-first behavior:

- `realized-performance` resolver now defaults `includeAttribution` to `false`
- `useRealizedPerformance()` now carries that default explicitly in resolver params
- `APIService.getRealizedPerformance()` now only requests attribution when the caller opts in

Live route check after that frontend-side default alignment:

- `POST /api/performance/realized` with `include_attribution=false`
  - first request: **1520.80ms**
  - warm request: **9.42ms**

### Warm Realized-Performance Attribution Is Now Cached

The remaining warm realized-performance cost was not in payload loading anymore; it was route-level attribution enrichment being recomputed on every `include_attribution=true` request.

This slice adds a short-lived attribution snapshot for the realized-performance route:

- sector/security/factor attribution is now cached independently of the already-cached realized payload
- repeated identical `include_attribution=true` requests can reuse that attribution result instead of rerunning `get_returns_dataframe()` and the attribution builders

Fresh-process validation on **2026-03-22** at `127.0.0.1:5002`:

- direct realized-performance request with attribution
  - first request: **4310.99ms**
  - second request: **12.56ms**
- timing log confirmation for the same pair:
  - first request at **2026-03-22T19:33:44Z**:
    - `load_realized_performance_payload`: **2285.95ms**
    - `enrich_attribution`: **2015.83ms**
  - second request at **2026-03-22T19:33:44Z**:
    - `load_realized_performance_payload`: **6.05ms**
    - `enrich_attribution`: **0.11ms**

Dashboard prewarm was also updated to warm the same `stale_ok` realized/income cache keys that the startup-facing routes now use.

That matters because the earlier prewarm path was still warming the old strict keys, which no longer matched the route reads after the stale-cache split.

Validation after `GET /api/portfolios/CURRENT_PORTFOLIO` on a fresh process and a short wait:

- bootstrap request: **326.69ms**
- first `POST /api/performance/realized` with attribution after bootstrap: **2239.43ms**
- timing log at **2026-03-22T19:36:01Z**:
  - `load_realized_performance_payload`: **5.64ms**
  - `enrich_attribution`: **2225.64ms**

So the current picture is:

- dashboard prewarm now successfully removes the realized payload rebuild from the first post-bootstrap performance request
- the main remaining owner for that path is cold attribution compute itself

### Bootstrap Now Starts Factor-Proxy Warmup Before Dashboard Prewarm

The next warm-path owner after the realized-performance fixes was the first analyze/risk-score call still paying factor-proxy work even after bootstrap:

- earlier fresh-process validation on **2026-03-22** still showed:
  - `api_analyze_workflow`: **345.25ms**
    - `ensure_factor_proxies`: **201.49ms**
  - `api_risk_score_workflow`: **181.78ms**
    - `ensure_factor_proxies`: **71.37ms**

Root cause in this slice:

- factor proxies were only being warmed once the background dashboard-prewarm worker had already started running
- that meant the first interactive analyze/risk-score request could still arrive before proxy warmup finished and inherit the in-flight work

The fix in this slice adds a dedicated workflow-cache prewarm path for factor proxies and starts it directly from `GET /api/portfolios/{portfolio_name}` before the dashboard prewarm worker is scheduled.

Fresh validation on an isolated updated server process at `127.0.0.1:5003` on **2026-03-22** after login, bootstrap, and a **1s** pause:

- `GET /api/portfolios/CURRENT_PORTFOLIO`
  - server timing: **355.20ms**
  - client wall time: **362.26ms**
- `POST /api/analyze`
  - server timing: **68.44ms**
  - client wall time: **75.82ms**
  - `ensure_factor_proxies`: **0.28ms**
- `POST /api/risk-score`
  - server timing: **6.70ms**
  - client wall time: **10.54ms**
  - `ensure_factor_proxies`: **0.25ms**

This materially changes the owner picture for the default analysis path:

- first analyze/risk-score after bootstrap are no longer meaningfully blocked on factor-proxy generation
- warm analysis is now mostly response serialization / formatting, not proxy or portfolio-view compute
- the heavier remaining backend owners are back to the background paths:
  - realized-performance attribution build
  - cold income / realized position loads when no stale snapshot exists yet

### Realized Attribution Now Reuses Bootstrap Analyst Warmup

Follow-up work on **2026-03-22** fixed a correctness gap in the warm path:

- holdings/bootstrap metadata prewarm was populating analyst snapshots on one `PortfolioService` instance
- the later realized-performance request built attribution on a different instance
- analyst snapshots lived in per-instance cache state, so the first realized-performance request still missed the prewarm and re-fetched `price_target*` / `analyst_grades`

This slice moved analyst snapshots to shared process-level cache/in-flight state, added cross-instance regression coverage, and widened only the bootstrap analyst prewarm scope so the first realized-performance request is less likely to miss on mid-tier names.

Measured validation on isolated fresh processes:

- fresh run at `127.0.0.1:5006` after login, bootstrap, and a **1s** pause:
  - `POST /api/performance/realized`: **3281.70ms**
  - timing:
    - `load_realized_performance_payload`: **1270.77ms**
    - `enrich_attribution`: **1993.74ms**
    - `realized_performance_attribution_build.compute_security_attribution`: **338.20ms**
- fresh run at `127.0.0.1:5007` after the broader bootstrap analyst prewarm:
  - `POST /api/performance/realized`: **3745.39ms**
  - timing:
    - `load_realized_performance_payload`: **2596.56ms**
    - `enrich_attribution`: **1092.59ms**
    - `realized_performance_attribution_build.compute_security_attribution`: **12.79ms**

What changed in practice:

- the request-time analyst-enrichment slice dropped sharply once the shared cache/prefetch path was active
- total first-request time is now dominated by variable cold `get_all_positions` latency plus returns-data loading, not repeated analyst endpoint fan-out

### Auth Status Now Starts Position Snapshot Warmup

One more low-risk overlap change landed on **2026-03-22**:

- authenticated `GET /auth/status` now kicks off the shared consolidated `prewarm_position_result_snapshot(..., allow_stale_cache=True)` in the background
- this does not block the auth-status response and is safe to repeat because the snapshot warmup is already in-flight deduped

Fresh-process validation on `127.0.0.1:5008` using the more realistic sequence `dev-login -> /auth/status -> bootstrap -> realized`:

- `GET /auth/status`: **2.69ms**
- `GET /api/portfolios/CURRENT_PORTFOLIO`: **382.93ms**
- first `POST /api/performance/realized`: **3708.06ms**
- timing:
  - `load_realized_performance_payload`: **1933.29ms**
  - `enrich_attribution`: **1621.16ms**

Conclusion from that run:

- auth-status overlap is safe and cheap, but it is not sufficient by itself to remove the remaining cold realized-performance stall
- the main remaining owner is still cold consolidated position loading (`get_all_positions`) when there is no usable snapshot yet
- after that, the next meaningful owner is `realized_performance_attribution_build.load_returns_dataframe`

### Stale Startup Loads Can Now Skip Cached Repricing

Another backend slice landed on **2026-03-22**:

- stale-tolerant startup snapshot loads can now skip cached repricing instead of recalculating market values before every route-facing read
- the snapshot cache key now distinguishes stale loads that skip repricing from stale loads that still require repriced values
- this removes the remaining hidden repricing tax from stale `get_all_positions` startup reads

Fresh-process validation on `127.0.0.1:5010` for `dev-login -> /auth/status -> bootstrap -> realized`:

- `POST /auth/dev-login`: **50.01ms**
- `GET /auth/status`: **3.32ms**
- `GET /api/portfolios/CURRENT_PORTFOLIO`: **408.70ms**
- first `POST /api/performance/realized`: **1481.32ms**
- second `POST /api/performance/realized`: **10.15ms**
- timing:
  - `load_realized_performance_payload`: **941.97ms**
  - second-hit `load_realized_performance_payload`: **5.27ms**

Important follow-up from that same run:

- correctness regressed for realized-performance attribution because stale cached DB positions do not persist `price` / `value`
- the first realized response came back with empty attribution arrays even though the request asked for `include_attribution=true`
- root cause: stale cached positions now loaded fast, but their `value` fields were all `0.0`, so attribution weight aggregation short-circuited

### Realized Attribution Now Reprices Only When Needed

That correctness gap is now fixed without reintroducing the old stale `get_all_positions` bottleneck:

- realized attribution now reprices only the already-filtered in-memory positions when the stale snapshot has zero gross exposure
- this restores correct non-empty sector/security/factor attribution while keeping the main stale payload load fast

Correctness validation on `127.0.0.1:5011`:

- first `POST /api/performance/realized`: **3758.59ms**
- second `POST /api/performance/realized`: **10.90ms**
- response now includes populated attribution:
  - `sector_attribution`: **9**
  - `security_attribution`: **26**
  - `factor_attribution`: **4**
- timing:
  - `load_realized_performance_payload`: **1439.16ms**
  - `realized_performance_attribution_build.reprice_position_values`: **953.18ms**
  - `realized_performance_attribution_build.load_returns_dataframe`: **1090.18ms**
  - `realized_performance_attribution_build.compute_security_attribution`: **9.59ms**

Conclusion from that corrected run:

- the stale `get_all_positions` regression is still removed from the hot path
- the remaining cold realized-performance owners are now explicit:
  - repricing missing position values for attribution weights
  - loading the monthly returns dataframe

### Auth Status Now Starts Realized Payload And Attribution Warmup

One more overlap change landed on **2026-03-22**:

- authenticated `GET /auth/status` now also starts stale-tolerant realized payload and realized-attribution prewarm for `CURRENT_PORTFOLIO`
- this reuses the same short-lived snapshot/in-flight caches as the real route
- the goal is to let the app overlap corrected attribution work with bootstrap instead of starting that work only after the user opens the performance view

Fresh-process validation on `127.0.0.1:5012` using the same sequence `dev-login -> /auth/status -> bootstrap -> realized`:

- `POST /auth/dev-login`: **41.55ms**
- `GET /auth/status`: **3.14ms**
- `GET /api/portfolios/CURRENT_PORTFOLIO`: **893.22ms**
- first `POST /api/performance/realized`: **3159.29ms**
- second `POST /api/performance/realized`: **15.72ms**
- response attribution stayed populated:
  - `sector_attribution`: **9**
  - `security_attribution`: **26**
  - `factor_attribution`: **4**
- timing:
  - `load_realized_performance_payload`: **500.79ms**
  - `realized_performance_attribution_build.reprice_position_values`: **953.73ms**
  - `realized_performance_attribution_build.load_returns_dataframe`: **851.66ms**
  - `realized_performance_attribution_build.compute_security_attribution`: **388.04ms**

Conclusion from that run:

- moving realized prewarm forward to auth-status cut the corrected first realized request from **3758.59ms** to **3159.29ms**
- the payload/load side is now substantially improved again; the remaining first-hit owners are entirely inside corrected attribution enrichment
- next backend work should focus on:
  - reducing `reprice_position_values`
  - reducing `load_returns_dataframe`
  - making analyst/security enrichment consistently hit the warmed path

## What Landed In This Slice

- startup-critical auth and portfolio-bootstrap service calls now use explicit fast-fail timeouts
- those same startup-critical service calls now disable HTTP-level retries
- `usePortfolioList()` disables React Query retries for the initial authenticated bootstrap path
- `PortfolioInitializer` disables bootstrap-query retries so the app surfaces a real startup failure quickly instead of stretching the refresh path
- `useDataSource()` now scopes dependency readiness to exact dependency query keys instead of any cached source match
- `useDataSource()` now reports dependency-wait as loading, but stays idle when the source lacks required portfolio context
- `PortfolioEarningsCard` now stays in a loading state while portfolio bootstrap or holdings-backed trading data are still resolving, instead of flashing a false “No earnings data available” empty state
- the top-level auth store timeout wrapper now matches the fast-fail startup policy instead of waiting significantly longer than the underlying auth service
- dashboard prewarm no longer lets shared analyze/risk/performance futures wait on a cold live-position future before the first interactive request
- startup-facing position readers can now opt into a stale-tolerant cached load instead of blocking on stale provider refresh
- position/result caches now separate strict vs `stale_ok` position-load policy so route traffic does not inherit slow background prewarm futures
- direct realized-performance frontend callers no longer request attribution by default unless they explicitly opt in
- realized-performance attribution is now cached across identical warm route requests
- dashboard prewarm now warms the same stale-tolerant realized/income keys that route traffic reads
- factor proxies now have a dedicated workflow prewarm path, and bootstrap starts that warmup before the background dashboard prewarm worker runs

These are guardrails, not the full audit.

## Audit Checklist

### 1. Rebaseline Current Startup

- [x] measure auth transition time on hard refresh
- [ ] measure time to session services ready
- [x] measure time to current portfolio selected
- [ ] measure time to first meaningful dashboard paint
- [x] capture backend-equivalent authenticated initial-load request burst timings

### 2. Inspect Request Topology

- verify the request burst still matches the intended eager-query set
- look for duplicate first-load calls after recent UI work
- confirm optional AI/settings/trading routes are not leaking onto the default hot path

### 3. Audit Startup-State Correctness

- check cards for false empty states during first load
- verify refresh does not get stuck on auth or portfolio bootstrap
- verify switching portfolios does not leave stale placeholder data in the wrong card

### 4. Re-Measure After Each Slice

- capture cold and warm timings after every material change
- update this plan with measured impact, not just code summaries

## Next Candidates

If more fixes are justified after the fast-fail guardrails:

1. instrument auth/services/portfolio bootstrap timings end-to-end
2. reduce remaining cold attribution cost for the first realized-performance request after bootstrap, especially `reprice_position_values` and `load_returns_dataframe`
3. inspect why warm `build_portfolio_view.factor_exposures` is materially slower than the March 19 checkpoint
4. decide whether strict background prewarm should keep doing a full live position refresh or move to the same stale-tolerant startup policy
5. inspect eager data-source scheduling for duplicate or non-critical first-load work once backend hot owners are reduced

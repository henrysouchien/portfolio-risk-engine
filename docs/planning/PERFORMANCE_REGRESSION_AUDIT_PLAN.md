# Performance Regression Audit Plan

**Status:** ACTIVE  
**Updated:** 2026-03-23  
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

### March 23 Re-Run: Cold Realized Aggregation Is Now Split And Measured

I instrumented the realized engine itself so the remaining cold path is no longer a single opaque `analyze_realized_performance` block.

Fresh-process validation on `127.0.0.1:5021` after `dev-login -> /auth/status -> bootstrap -> realized` showed:

- `POST /auth/dev-login`: **10.38ms**
- `GET /auth/status`: **3.46ms**
- `GET /api/portfolios/CURRENT_PORTFOLIO`: **492.47ms**
- first `POST /api/performance/realized`: **9892.20ms**

The important timing split from that run:

- `realized_aggregation.total`: **5922.00ms**
- `load_transaction_store`: **3618.45ms**
- `build_price_cache`: **1415.95ms**
- `build_benchmark_returns`: **474.07ms**
- `compose_cash_and_external_flows`: **9.50ms**
- `build_primary_nav_series`: **10.33ms**
- `build_observed_nav_series`: **17.03ms**
- `build_monthly_returns`: **7.07ms**
- `realized_performance_attribution_build.total`: **5222.55ms**
  - `load_returns_dataframe`: **3098.90ms**
  - `compute_security_attribution`: **1199.58ms**

Conclusion from that split:

- FIFO, cash replay, and NAV reconstruction are no longer the problem
- the cold payload owner moved up to transaction-store loading plus price fetch
- the user-visible realized route was also duplicating attribution work while the shared prewarm was still in flight

### March 23 Fixes: Shared Attribution Reuse And Faster Realized Startup

Two more backend fixes landed after that measurement:

- realized attribution now always reuses the shared short-lived cache/in-flight snapshot instead of bypassing it and recomputing locally when a prewarm is already running
- successful login now starts the same stale-tolerant portfolio/realized warmup path that `/auth/status` starts, so the warmup can overlap a little earlier in the session

Fresh-process validation on `127.0.0.1:5022` after the transaction-store/path cleanup:

- `POST /auth/dev-login`: **21.22ms**
- `GET /auth/status`: **3.45ms**
- `GET /api/portfolios/CURRENT_PORTFOLIO`: **568.97ms**
- first `POST /api/performance/realized`: **2919.76ms**
- timing:
  - `realized_aggregation.total`: **2331.88ms**
  - `load_transaction_store`: **1898.48ms**
  - `build_price_cache`: **282.50ms**
  - `realized_performance_workflow.load_realized_performance_payload`: **781.54ms**
  - `realized_performance_attribution_build.total`: **1917.83ms**
    - `load_returns_dataframe`: **1409.30ms**
    - `compute_security_attribution`: **349.88ms**

Fresh-process validation on `127.0.0.1:5023` after removing duplicate attribution rebuilds:

- first `POST /api/performance/realized`: **2780.19ms**
- only one `realized_performance_attribution_build` ran
- `realized_performance_workflow.enrich_attribution`: **1788.54ms**

Fresh-process validation on `127.0.0.1:5024` after also starting warmup on login:

- `POST /auth/dev-login`: **53.91ms**
- `GET /auth/status`: **8.25ms**
- `GET /api/portfolios/CURRENT_PORTFOLIO`: **641.99ms**
- first `POST /api/performance/realized`: **2787.18ms**

Current conclusion:

- the first realized request after bootstrap is down from roughly **9.9s** to roughly **2.8s**
- duplicate attribution work is gone
- the remaining interactive owner is now a single shared attribution build, especially:
  - `load_returns_dataframe`
  - the residual `load_transaction_store` time inside the payload prewarm

### March 23 Fixes: Nonblocking Analyst Enrichment On The Stale Startup Path

The next regression turned out to be inside the `compute_security_attribution` timing bucket, not the return math itself. That timing step was also waiting on `PortfolioService.enrich_attribution_with_analyst_data()`, which still fans out multiple FMP analyst endpoints per symbol.

For the `stale_ok` startup path, that wait was not necessary. The first realized request only needs the attribution rows themselves; analyst fields are optional. I changed the stale startup path to use already-cached analyst snapshots when they exist, but to stop blocking on new analyst fetches.

Fresh-process validation on `127.0.0.1:5032` after that change:

- `POST /auth/dev-login`: **17.23ms** server
- `GET /auth/status`: **1.97ms** server
- `GET /api/portfolios/CURRENT_PORTFOLIO`: **881.75ms** server
- first `POST /api/performance/realized`: **203.99ms** server / **214.01ms** client

Timing split:

- `realized_performance_attribution_build.total`: **449.72ms**
  - `load_returns_dataframe`: **364.20ms**
  - `compute_sector_attribution`: **23.98ms**
  - `compute_security_attribution`: **1.99ms**
  - `compute_factor_attribution`: **58.57ms**
- `realized_performance_workflow.total`: **8.02ms**
  - `load_realized_performance_payload`: **7.09ms**
  - `enrich_attribution`: **0.12ms**

Behavioral note:

- the first stale-startup realized response no longer waits for analyst metadata
- analyst fields stay optional and begin appearing on later requests once the background prewarm finishes

### March 23 Fixes: Portfolio Bootstrap Reuses The Auth-Prewarmed Stale Snapshot

The remaining cold bootstrap cost was in `GET /api/portfolios/CURRENT_PORTFOLIO`. The auth status prewarm was already building stale-tolerant position snapshots, but the portfolio bootstrap display path only peeked the strict cache key. That meant bootstrap could miss an already-warmed stale snapshot and fall back to the slower `transform_portfolio_for_display()` / `refresh_portfolio_prices()` path.

I changed the virtual bootstrap display path to prefer the stale auth-prewarmed position snapshots first, and only fall back to the slower display rebuild when none of those snapshots are ready.

Fresh-process validation on `127.0.0.1:5033` after that change:

- `POST /auth/dev-login`: **31.93ms** server / **65.77ms** client
- `GET /auth/status`: **6.02ms** server / **13.73ms** client
- `GET /api/portfolios/CURRENT_PORTFOLIO`: **115.61ms** server / **117.84ms** client
- first `POST /api/performance/realized`: **12.92ms** server / **14.35ms** client

Timing split:

- `api_get_portfolio_workflow.total`: **108.61ms**
  - `load_portfolio_data`: **107.46ms**
  - `build_portfolio_display_data`: **0.76ms**
- `realized_performance_workflow.total`: **6.63ms**
  - `load_realized_performance_payload`: **5.78ms**
  - `enrich_attribution`: **0.11ms**

Current startup conclusion:

- the authenticated bootstrap flow is back in the same class as the March 19 target again for the main default path
- `CURRENT_PORTFOLIO` bootstrap is no longer paying the slow fallback display build on a fresh session
- the first realized-performance request after bootstrap is effectively warm on the default path
- the main remaining cold technical owner in the background is now the stale-path `load_returns_dataframe` work, but it is no longer gating the default first interactive request

## March 22 Follow-Up: Lean Performance View Path

The next cold regression was `POST /api/performance`. On a fresh local server at `127.0.0.1:5035`, the default interactive path still looked wrong:

- `POST /api/performance` with `include_attribution=false`: **441.09ms**
- `POST /api/performance` with `include_attribution=true`: **6050.33ms**

The important finding was that the frontend performance view was not using the route's optional dividend payload, but the backend was still coupling `include_optional_metrics` to `include_attribution`. That meant the first performance-view load was paying the full dividend-yield fan-out even though the UI did not need it.

Changes landed:

- `PerformanceRequest` now accepts explicit `include_optional_metrics`, defaulting to `false`
- `_run_performance_workflow()` now keys the performance snapshot cache by lean-vs-extra scope:
  - `summary_only`
  - `summary_with_extras`
  - `attr_core`
  - `attr_with_extras`
- dashboard prewarm now warms both:
  - summary performance (`summary_only`)
  - lean attributed performance (`attr_core`)
- lean attributed performance now treats analyst enrichment as non-blocking on the request path; the explicit extras path still waits for missing analyst snapshots

Fresh-process measurements after that split:

- On `127.0.0.1:5035` after login, auth-status, portfolio bootstrap, summary request, then performance:
  - `GET /api/portfolios/CURRENT_PORTFOLIO`: **319.47ms**
  - `POST /api/performance` `include_attribution=false`: **1336.68ms**
  - `POST /api/performance` default lean attributed path: **1312.70ms**
  - `POST /api/performance` with `include_optional_metrics=true`: **5271.91ms**

Then, after making lean analyst enrichment non-blocking, the direct fresh `portfolio -> performance` path improved further on `127.0.0.1:5037`:

- `POST /auth/dev-login`: **33.42ms**
- `GET /auth/status`: **3.13ms**
- `GET /api/portfolios/CURRENT_PORTFOLIO`: **337.25ms**
- first `POST /api/performance` default lean attributed path: **1156.13ms**
- first `POST /api/performance` with `include_optional_metrics=true`: **5724.12ms**

Current performance conclusion:

- the default first interactive performance-view path is back in the ~`1.1s` class instead of the ~`6s` class
- the remaining slow path is now clearly the explicit opt-in extras build, not the default UI workload
- dividend-yield and other optional performance extras should stay opt-in unless a caller explicitly needs them

## March 22 Follow-Up: Parallel Dividend Yield Fan-Out

The explicit extras path was still too expensive even after the lean/default split:

- On `127.0.0.1:5037`
  - first `POST /api/performance` default lean attributed path: **1156.13ms**
  - first `POST /api/performance` with `include_optional_metrics=true`: **5724.12ms**

The remaining owner was `calculate_portfolio_dividend_yield()`, which was still fetching current dividend yield serially, one ticker at a time.

Change landed:

- `calculate_portfolio_dividend_yield()` now fans out per-ticker dividend-yield fetches through a bounded `ThreadPoolExecutor`
- result ordering and `failed_tickers` ordering remain stable against the original holdings order

Fresh-process validation on `127.0.0.1:5038` after that change:

- `POST /auth/dev-login`: **21.52ms**
- `GET /auth/status`: **2.50ms**
- `GET /api/portfolios/CURRENT_PORTFOLIO`: **307.44ms**
- first `POST /api/performance` default lean attributed path: **1218.65ms**
- first `POST /api/performance` with `include_optional_metrics=true`: **1215.24ms**

Current extras-path conclusion:

- the opt-in performance-extras route is no longer a separate `5s+` class regression
- dividend-yield enrichment is now in the same rough latency class as the default performance path

## March 22 Follow-Up: Stock Lookup View

After the dashboard/default-performance regressions were back under control, the next user-visible hotspot was the stock lookup view.

First stock-lookup correctness/perf slice:

- suppress typeahead `stock-search` work once a symbol is already selected
- normalize blank ticker input back to idle state instead of leaving an empty-string analysis state
- keep peer-comparison props hidden until the primary stock payload is ready, so the stock view does not consume mismatched peer data

Direct backend measurements on fresh local servers:

- on `127.0.0.1:5041` before the new stock-lookup backend work:
  - `POST /api/direct/stock` for `AAPL`: **1778.24ms** first hit, **3064.02ms** second hit
  - `GET /api/direct/stock/AAPL/peers?limit=5`: **6518.66ms** first hit, **5234.66ms** second hit
- on `127.0.0.1:5042` after adding backend peer-result caching plus per-ticker peer-metric fan-out:
  - isolated `GET /api/direct/stock/MSFT/peers?limit=5`: **3513.07ms** first hit, **0.74ms** second hit
  - `POST /api/direct/stock` for `AAPL`: **955.51ms** first hit, **549.89ms** second hit
  - full stock-lookup sequence `POST /api/direct/stock` then `GET /api/direct/stock/AAPL/peers?limit=5`: **960.92ms** then **4956.84ms**

Current stock-lookup conclusion:

- the main stock payload is back in roughly the `0.5-1.0s` class locally
- peer comparison remains the cold-path owner for stock lookup, but repeated same-symbol peer lookups are now effectively free due to backend result caching
- because the cold peer path is still materially slower than the main stock payload, the frontend should overlap peer fetch with stock analysis where possible while still gating peer data consumption on primary stock readiness

## March 22 Follow-Up: Stock Lookup Cache Reuse And Stale-State Guard

The next stock-lookup slice targeted two remaining issues:

- repeated direct stock lookups were still paying full quote/profile/technical enrichment cost even after the underlying analysis result was warm
- symbol switches could briefly render stale stock payloads if `selectedSymbol` moved ahead of the resolved stock payload

Changes landed:

- `StockService.enrich_stock_data()` now caches the computed ticker enrichment bundle so repeat direct-stock requests can reuse the expensive post-analysis quote/profile/technical work
- `POST /api/direct/stock` now reuses the shared direct-endpoint `stock_service` instance instead of creating a fresh `StockService` per request
- peer comparison now reuses cached per-ticker metric snapshots across different compare-peers requests, not just exact same-symbol result-cache hits
- `StockLookupContainer` now treats stock payload readiness as `selectedSymbol`, `currentTicker`, and `stockData.ticker` alignment, so the UI stays loading instead of rendering stale stock data during a ticker switch

Fresh-process validation on `127.0.0.1:5044`:

- `POST /api/direct/stock` for `AAPL`: **1400.86ms** first hit, **3.82ms** second hit
- `GET /api/direct/stock/AAPL/peers?limit=5`: **4058.53ms** first hit
- switching immediately to `GET /api/direct/stock/MSFT/peers?limit=5` after the `AAPL` peer load: **2534.36ms** first hit, **2.60ms** second hit

Current stock-lookup conclusion after this slice:

- repeated direct stock lookups are no longer a meaningful hot path
- first peer-comparison load for a new symbol is still the dominant stock-lookup owner
- cross-symbol stock lookup is materially better now because overlapping peer tickers reuse cached per-ticker metric snapshots
- stale-symbol rendering during stock switches is guarded; the view stays loading until the selected ticker and resolved payload agree

## March 22 Follow-Up: Stock Lookup Reuses Cached FMP Reads

The next stock-lookup slice targeted an avoidable cold peer cost on the subject ticker itself.

Changes landed:

- peer-metric hydration now uses `FMPClient.fetch()` when the caller is a real client, so the peer path can reuse the same disk-backed FMP caches that direct stock analysis already populated
- mock-based peer tests stay on the old `fetch_raw()` path so the existing unit fixtures and call assertions remain stable

Fresh-process validation on `127.0.0.1:5045`:

- `POST /api/direct/stock` for `AAPL`: **1712.03ms** first hit, **2.29ms** second hit
- `GET /api/direct/stock/AAPL/peers?limit=5`: **3435.55ms** first hit, **2.96ms** second hit
- switching immediately to `GET /api/direct/stock/MSFT/peers?limit=5` after the `AAPL` peer load: **2836.44ms** first hit, **1.31ms** second hit

Current stock-lookup conclusion after this slice:

- the first cold peer load improved again, from roughly **4058ms** to **3436ms**, because the subject ticker can now reuse cached ratios/profile/estimate reads populated by the direct stock route
- warm peer loads remain effectively free
- the remaining cold stock-lookup owner is now mostly the uncached peer-ticker fan-out, not repeated work on the primary selected symbol

## March 22 Follow-Up: Stock Lookup Shares In-Flight Peer Work

The next stock-lookup slice targeted the actual user flow instead of isolated endpoint hits.

Changes landed:

- `StockService.get_peer_comparison()` now deduplicates same-key in-flight peer-comparison requests, so adjacent callers reuse the same future instead of running duplicate cold fan-out work
- `POST /api/direct/stock` now starts the default peer-comparison warmup immediately, before the main stock analysis begins, so the stock lookup peer tab can attach to that in-flight work

Fresh-process validation:

- on `127.0.0.1:5048`, starting `POST /api/direct/stock` for `AAPL` and `GET /api/direct/stock/AAPL/peers?limit=5` concurrently:
  - stock response: **1528.89ms**
  - peer response: **1529.15ms**
- on `127.0.0.1:5049`, sequential stock lookup flow:
  - `POST /api/direct/stock` for `AAPL`: **2498.18ms**
  - immediate follow-up `GET /api/direct/stock/AAPL/peers?limit=5`: **16.32ms**
  - warm repeat peer request: **2.24ms**

Current stock-lookup conclusion after this slice:

- the real stock-lookup flow is now materially better than the isolated cold peer baseline
- when stock and peer requests start together, the peer request now rides the same in-flight work instead of paying a separate ~3.4s cold path
- when the user reaches peers after the main stock card is already loaded, the peer tab is effectively warm

## March 23 Follow-Up: Stock Lookup Parallelizes Heavy Enrichment

The next stock-lookup slice targeted the remaining direct-stock owner after peer warmup was fixed.

What the breakdown showed:

- `analyze_stock()` itself was only about **130-150ms**
- the real owner was `StockService.enrich_stock_data()`
- inside enrichment, the heavy calls were the registry quote-provider batch quote lookup and the technical-analysis summary, both in the **~600ms** class

Changes landed:

- `StockService.enrich_stock_data()` now starts quote enrichment and technical-summary enrichment in parallel
- the serial profile/sector/fundamental path stays intact, and forward-P/E still waits for quote data before it is derived

Fresh-process validation:

- in-process breakdown:
  - `analyze_stock()`: **129.87ms**
  - `enrich_stock_data()`: **1445.15ms**
  - warm enrichment reuse: **1.83ms**
- on `127.0.0.1:5050`, sequential stock lookup flow:
  - `POST /api/direct/stock` for `AAPL`: **1327.94ms**
  - immediate follow-up `GET /api/direct/stock/AAPL/peers?limit=5`: **1.99ms**
  - warm repeat `POST /api/direct/stock`: **2.15ms**
- on `127.0.0.1:5051`, starting stock + peers together:
  - stock response: **1316.06ms**
  - peer response: **1316.43ms**

Current stock-lookup conclusion after this slice:

- the default stock lookup card is now materially faster than the earlier `2.5s+` class cold path
- the peer tab remains aligned with the main stock card in the concurrent flow
- remaining cold-path work is mostly inside the quote-provider and technical-summary calls themselves rather than in the stock-analysis core or peer coordination

## March 23 Follow-Up: Stock Lookup Reuses Real FMP Technical Cache

The next stock-lookup regression turned out to be a cache miss hidden inside the technical-summary helper itself.

Root cause:

- `get_technical_analysis(..., use_cache=True)` still routed real clients through `fetch_raw()`
- that bypassed the shared disk-backed FMP cache even when the caller explicitly asked for cached reads
- warm technical summaries could stay in the `~1s` class instead of collapsing after the first hit

Changes landed:

- real FMP clients now use `FMPClient.fetch(..., use_cache=use_cache)` inside the technical tool
- mock-based tests stay on the old `fetch_raw()` path so unit fixtures and call assertions remain stable

Validation:

- repeated `get_technical_analysis("AAPL", indicators=["rsi","macd","bollinger"])`
  - first hit: **1431.02ms**
  - second hit: **53.26ms**
  - third hit: **21.99ms**

Conclusion after this slice:

- the technical-summary helper now behaves like the rest of the FMP-backed stock-lookup stack
- remaining stock-card latency is no longer explained by accidental cache bypass in technical enrichment

## March 23 Follow-Up: Peer Warmup No Longer Starves The Main Stock Card

The next stock-lookup issue was a regression in the opposite direction: starting peer warmup too early could help the peer tab, but it also created pathological main-card stalls for some symbols.

What the repro showed:

- when peer warmup started before the main stock analysis, `AAPL` was acceptable but some names regressed badly
- fresh-process repros showed:
  - `POST /api/direct/stock` for `JPM` at `127.0.0.1:5054`: **9207.56ms**
  - `GET /api/direct/stock/search?query=jpm&limit=8` then `POST /api/direct/stock` for `JPM` at `127.0.0.1:5055`: **1015.89ms** then **8564.78ms**
- in-process timing for the same symbol showed the stock-analysis core itself was not the problem:
  - `analyze_stock()`: **131.31ms**
  - `enrich_stock_data()`: **413.06ms**
  - isolated technical summary: **63.31ms**

Changes landed:

- `POST /api/direct/stock` now keeps the main stock card first and schedules peer warmup after the response via `BackgroundTasks`
- the shared FMP metadata provider now keeps short-lived profile snapshots as well as quote snapshots, so `fetch_batch_quotes()` and later `fetch_profile()` can reuse the same profile payload instead of refetching it inside the same stock request

Fresh validation after that route-ordering and provider-cache fix:

- direct stock then immediate peers:
  - `AAPL`: stock **416.82ms**, peers **270.53ms**
  - `JPM`: stock **166.16ms**, peers **107.86ms**
- exact-ticker search-to-select flow:
  - `GET /api/direct/stock/search?query=aapl&limit=8` then `POST /api/direct/stock`: **348.56ms** then **221.94ms**
  - `GET /api/direct/stock/search?query=jpm&limit=8` then `POST /api/direct/stock`: **398.62ms** then **111.00ms**
- isolated enrichment check after the provider-cache reuse:
  - `AAPL`: **110.18ms**
  - `JPM`: **108.19ms**

Conclusion after this slice:

- the main stock card is back in the sub-`500ms` class locally instead of suffering symbol-dependent multi-second stalls
- peer follow-up remains reasonably warm without letting peer work block the first stock card
- profile reuse is now aligned across search, stock enrichment, and quote fetches

## March 23 Follow-Up: Repeated Stock Search Queries Are Now Effectively Warm

The final stock-lookup slice in this pass targeted the typeahead path itself.

Even after the quote/profile caches warmed, repeated identical search queries still reran search-provider lookup plus quote merge work and stayed around `~100ms`.

Changes landed:

- `StockService.search_stocks()` now keeps a short-lived in-process result cache keyed by normalized query + limit
- this is intentionally much shorter-lived than the general service cache so search results do not stay stale for long

Validation on repeated identical search queries:

- `aapl`: **314.63ms**, **1.73ms**, **1.20ms**
- `jpm`: **285.29ms**, **1.48ms**, **1.32ms**
- `apple`: **280.73ms**, **1.57ms**, **1.14ms**

Current stock-lookup conclusion after the March 23 follow-ups:

- repeated typeahead queries are effectively free after the first hit
- exact-ticker search-to-select is down into the low hundreds of milliseconds for the stock load itself
- the earlier slow-symbol regression from eager peer warmup is gone
- the remaining stock-lookup latency is now mostly just the unavoidable first-hit search/provider/network work for genuinely new symbols

## March 23 Follow-Up: Stock Lookup Frontend State And Retry Semantics

The final stock-lookup slice in this pass was frontend correctness rather than backend timing.

Issues addressed:

- selecting the same ticker again was a no-op in `useStockAnalysis()`, so the user could not re-run the same stock lookup from the search UI without first switching to a different symbol
- stock-search cache keys were still case-sensitive on the frontend, which meant `AAPL` and `aapl` could split resolver/query reuse even though the backend search path already normalized them
- a failed stock lookup replaced the whole stock-lookup shell with a retry-only error block, which hid the search header and made it harder to pivot to a different symbol after one bad response

Changes landed:

- `useStockAnalysis()` now refetches when the user selects the currently active ticker again
- `useStockSearch()` now normalizes query casing before it reaches the resolver/query layer
- stock lookup errors now render inline inside the normal stock-lookup shell, keeping search available while still exposing retry
- selecting or clearing a stock now also clears the parent search-term state immediately, which avoids reviving stale typeahead results after the selection is dismissed

Frontend verification:

- focused Vitest run:
  - `useStockAnalysis`
  - `useStockSearch`
  - `usePeerComparison`
  - `StockLookupContainer`
  - stock-lookup helpers
- result: **36 tests passed**
- `npm run typecheck`: clean

## March 23 Follow-Up: Exact-Ticker Search Now Warms The Direct Stock Payload

One more stock-lookup perf slice targeted the common search-to-select path.

Problem:

- typeahead search had become fast and cache-friendly, but an immediate click on an exact ticker match still had to start the direct stock build from scratch
- warming that payload blindly on every search was risky; an earlier experiment showed that eager background work can hurt the main request if it races the interactive path

Changes landed:

- exact symbol matches from `GET /api/direct/stock/search` now start a background warm for the default direct-stock payload
- the warm path uses shared in-flight state, so the follow-up `POST /api/direct/stock` request reuses the same stock build instead of racing a duplicate analysis/enrichment pass
- non-exact search queries do not start the prewarm path

Validation:

- route and service coverage stayed green after this change:
  - focused backend pytest: **107 passed**
- fresh local server on `127.0.0.1:5061`:
  - `query=aapl` then `POST /api/direct/stock` for `AAPL`: **283.84ms** then **190.05ms**
  - `query=jpm` then `POST /api/direct/stock` for `JPM`: **292.96ms** then **92.23ms**
  - non-exact `query=apple` then `POST /api/direct/stock` for `AAPL`: **299.31ms** then **3.24ms** after the earlier exact-match warm path had already populated the caches

Current stock-lookup conclusion after this slice:

- repeated search queries are effectively free
- exact-ticker search-to-select now has a shared warm path instead of paying a separate stock build after typeahead
- the remaining first-hit latency is now mostly genuine provider/network cost for truly new symbols and not avoidable duplicate work between search, stock lookup, and peers

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

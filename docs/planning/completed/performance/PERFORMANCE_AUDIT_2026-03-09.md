# Performance Audit — 2026-03-09
**Status:** DONE — Audit complete, led to BACKEND_PERFORMANCE_PLAN.md (all phases implemented)

## Context

This document captures a read-only performance audit of the risk module across backend and frontend.

Audit constraints:

- Goal: make the system as fast and responsive as possible across frontend and backend.
- Preserve behavior and outputs.
- Do not change core logic unless absolutely necessary.
- Refactors are acceptable when they are behavior-preserving.
- No code changes were made as part of this audit.

## Executive Summary

The highest-leverage opportunities are not deep algorithm rewrites. The main wins are concentrated in a few structural areas:

1. Frontend startup cost is too high.
2. The frontend bundle is too large and not split aggressively enough.
3. Logging is doing too much work in hot paths on both frontend and backend.
4. Backend request paths still do duplicated and serial work before their cache fast-paths.
5. Auth/session lookup currently turns most authenticated traffic into write traffic.
6. Some holdings/positions paths appear to reprice and re-enrich data repeatedly, with cost that scales with row count.

If these areas are addressed first, they should produce the largest speedup without changing core product behavior.

## Evidence Collected

### Frontend build evidence

I ran a production frontend build in the main workspace:

- Command: `npm --prefix frontend run build`
- Result: success
- Main JS bundle: `build/assets/index-CLuAXqwH.js`
- Size: `2,176.17 kB` minified / `598.53 kB` gzip
- CSS bundle: `build/assets/index-Bc7xuLR4.css`
- CSS size: `167K`
- Vite warning: some chunks are larger than `500 kB` after minification

Large static assets observed in the built output:

- Main app JS is effectively one large chunk.
- KaTeX font assets are present in the production build.

### Repo-level signal counts

These counts are not problems by themselves, but they show where performance overhead is likely concentrated:

- Frontend `console.*` calls in source: `58`
- `frontendLogger.*` call sites in frontend source: `570`
- `PortfolioService(...)` instantiations across the repo: `86`
- `PortfolioManager(...)` instantiations in `app.py`, `routes`, and `services`: `22`
- `api_logger.*` call sites in `app.py`: `54`

## Highest-Impact Findings

### 1. Frontend bundle is too large and too eager

The production frontend currently ships a very large initial JS payload, and the main application path eagerly imports heavy dashboard, chat, markdown, and KaTeX-related code.

Primary evidence:

- `2.1M` main JS asset in production build
- Root/dashboard path imports large feature surfaces eagerly
- No meaningful view-level chunking visible in the current Vite config

Relevant files:

- `frontend/packages/ui/src/router/AppOrchestratorModern.tsx`
- `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx`
- `frontend/packages/ui/src/components/chat/shared/MarkdownRenderer.tsx`
- `frontend/vite.config.ts`

Suggested direction:

- Split by route and by active dashboard view.
- Lazy-load chat UI.
- Lazy-load markdown and KaTeX only when needed.
- Add explicit `manualChunks` for large vendor groups and feature groups.

Expected impact:

- Faster first load
- Lower JS parse/execute cost
- Faster route/view transitions on cold start

Regression risk:

- Low to medium, mostly around loading boundaries and Suspense fallbacks

### 2. Frontend startup is overfetching and partially blocking

The dashboard bootstrap path does too much before the user sees useful content.

Observed pattern:

- `PortfolioInitializer` fetches the default portfolio.
- It then immediately refreshes prices before rendering children.
- After that, the scheduler prefetches all eager sources.
- The default dashboard path mounts multiple expensive containers immediately.
- Chat-related context is also initialized globally.

Relevant files:

- `frontend/packages/connectors/src/providers/PortfolioInitializer.tsx`
- `frontend/packages/connectors/src/resolver/scheduler.ts`
- `frontend/packages/chassis/src/catalog/descriptors.ts`
- `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx`
- `frontend/packages/ui/src/components/chat/ChatContext.tsx`

Suggested direction:

- Render from the initial portfolio payload first.
- Push price refresh after first paint.
- Prefetch only above-the-fold data initially.
- Defer lower-priority sources to idle time or on view activation.
- Initialize chat only when chat is opened.

Expected impact:

- Faster time-to-interactive
- Lower backend request burst after login
- Less contention during dashboard startup

Regression risk:

- Low if data freshness semantics are preserved carefully

### 3. Root dashboard shell rerenders unnecessarily

`ModernDashboardApp` updates `currentTime` every second at the top level. That forces the whole dashboard shell to reconcile once per second.

Relevant file:

- `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx`

Suggested direction:

- Move the clock into a small isolated component.
- Keep it outside the heavy content subtree.

Expected impact:

- Lower idle CPU usage
- Smoother interactions
- Fewer avoidable rerenders across the shell

Regression risk:

- Very low

### 4. Logging is on hot paths across the system

There is substantial logging overhead on both frontend and backend.

Frontend:

- `frontendLogger` is enabled for all non-test builds.
- Logs are sanitized, truncated, queued, and shipped back to the backend.
- Logging occurs in render-adjacent and high-frequency paths.
- API request/response logging is verbose.

Backend:

- Some hot endpoints stringify raw request bodies and large response structures.
- Validation failure logging captures and parses full raw bodies.
- The frontend log ingestion route reparses JSON and stringifies structured log payloads.

Relevant files:

- `frontend/packages/chassis/src/services/frontendLogger.ts`
- `frontend/packages/chassis/src/services/APIService.ts`
- `frontend/packages/ui/src/router/AppOrchestratorModern.tsx`
- `routes/frontend_logging.py`
- `app.py`

Suggested direction:

- In production, ship only errors and sampled slow-operation logs by default.
- Remove render-path logging.
- Gate raw body and response-body debug logs behind an env flag.
- Reduce frontend log delivery frequency and volume.
- Consider sampling or disabling frontend log POSTs entirely in normal production flows.

Expected impact:

- Lower CPU overhead on both client and server
- Fewer allocations and less JSON serialization
- Fewer extra network requests

Regression risk:

- Very low for product behavior
- Medium operationally if teams currently depend on high-volume debug logs

### 5. Backend cache fast-path is weakened by pre-cache work

`PortfolioService.analyze_portfolio()` performs classification work before checking whether the analysis result is already cached. That means cache hits still pay for classification-related work.

Relevant file:

- `services/portfolio_service.py`

Observed pattern:

- Extract tickers
- Call `SecurityTypeService.get_full_classification(...)`
- Build asset/security type maps
- Only then check the service cache

Suggested direction:

- Move the analysis cache lookup earlier if possible.
- If classification must remain separate, cache classifications independently and reuse them.

Expected impact:

- Better warm-cache performance on repeat analysis

Regression risk:

- Low to medium depending on cache-key design

### 6. Portfolio DB loading fans out into multiple round trips

One logical portfolio load is currently assembled from several repository calls, and each repository method opens its own DB session/connection.

Relevant files:

- `inputs/portfolio_manager.py`
- `inputs/portfolio_repository.py`

Observed pattern:

- Load positions
- Load metadata
- Load factor proxies
- Load expected returns
- Load target allocations

Suggested direction:

- Add one repository method that loads the full portfolio payload in one connection scope.
- If full consolidation is too large, at minimum keep all subqueries within one shared connection/session.

Expected impact:

- Lower request latency
- Lower DB connection churn
- Better throughput under concurrency

Regression risk:

- Medium because it changes data access structure, though not intended behavior

### 7. Security classification work is duplicated and serial

The security-type/asset-class pipeline is doing more work than necessary.

Observed pattern:

- `get_full_classification()` calls both `get_security_types()` and `get_asset_classes()`.
- `get_asset_classes()` may call `get_security_types()` again for remaining tickers.
- Missing/stale work then proceeds through serial FMP and AI fallback loops.

Relevant file:

- `services/security_type_service.py`

Suggested direction:

- Collapse into one pipeline that computes both labels together.
- Use bounded concurrency for remote lookups.
- Batch DB writes/UPSERTs instead of one transaction per ticker.

Expected impact:

- Lower cold-cache latency for analysis and positions flows
- Lower external API overhead

Regression risk:

- Medium because classification behavior must remain identical

### 8. Auth/session lookup is a write-heavy hot path

Every authenticated request effectively does:

1. `SELECT session`
2. `UPDATE last_accessed`
3. `COMMIT`

Relevant files:

- `app_platform/auth/stores.py`
- `app.py`
- `routes/auth.py`

Suggested direction:

- Touch `last_accessed` only every 5 to 15 minutes.
- Or move touch behavior off the request path.
- Or batch/defer touches asynchronously.

Expected impact:

- Lower write load
- Lower latency on all authenticated endpoints
- Reduced lock/transaction churn

Regression risk:

- Low if session-expiry semantics are preserved

### 9. Positions/holdings enrichment likely repeats expensive repricing work

An independent backend pass flagged the positions/holdings path as a high-impact latency source, especially when row counts are large.

Observed pattern:

- Positions are repriced and enriched on top of cached position loads.
- Holdings routes appear to add more market, sector, and risk enrichment after the base positions payload is loaded.
- Work likely scales with row count and may repeat quote resolution for the same symbols.

Relevant files:

- `services/position_service.py`
- `utils/ticker_resolver.py`
- `routes/positions.py`

Suggested direction:

- Batch by unique symbol.
- Build one per-request quote snapshot.
- Reuse the enriched payload across holdings, export, alerts, and related views.

Expected impact:

- Large for bigger portfolios
- Lower request amplification across holdings-related routes

Regression risk:

- Medium because quote freshness and enrichment ordering must remain consistent

### 10. Client-side caching layers overlap and add overhead

React Query exists, but the app also has additional custom cache, coordination, monitor, warmer, and resolver layers. Some of these are adding overhead and invalidation complexity.

Observed pattern:

- `APIService` in-flight dedupe key includes `Date.now()`, which defeats request coalescing.
- React Query sits alongside `PortfolioCacheService`, `UnifiedAdapterCache`, `CacheWarmer`, and a full resolver/prefetch layer.
- `useDataSource()` subscribes to the entire query cache for dependency tracking.

Relevant files:

- `frontend/packages/chassis/src/services/APIService.ts`
- `frontend/packages/chassis/src/services/PortfolioCacheService.ts`
- `frontend/packages/chassis/src/services/UnifiedAdapterCache.ts`
- `frontend/packages/connectors/src/resolver/useDataSource.ts`
- `frontend/packages/connectors/src/providers/SessionServicesProvider.tsx`

Suggested direction:

- Fix in-flight dedupe first.
- Make React Query the primary server-state cache for common flows.
- Remove or narrow overlapping caches where they do not add clear value.
- Avoid whole-cache subscriptions in hooks.

Expected impact:

- Lower CPU and memory overhead
- Less invalidation complexity
- Fewer duplicate requests

Regression risk:

- Medium because cache behavior is distributed across many paths

### 11. Hidden/background work stays active too often

Notifications, pending-update polling, and related refresh behavior remain active globally, including in background tabs.

Relevant files:

- `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx`
- `frontend/packages/connectors/src/features/portfolio/hooks/usePendingUpdates.ts`

Suggested direction:

- Pause non-critical polling when the tab is hidden.
- Mount notification-heavy hooks only where they are actually needed.
- Keep background refresh for only the narrowest set of critical data.

Expected impact:

- Lower idle load
- Fewer background requests

Regression risk:

- Low

### 12. Per-user backend service registries may grow without eviction

Per-user service instances are stored in module-level dictionaries, and each service carries in-process TTL caches.

Relevant files:

- `app.py`
- `services/cache_mixin.py`

Suggested direction:

- Add eviction or TTL to the service registry.
- Or centralize caches using user-scoped keys instead of one long-lived service object per user.

Expected impact:

- Better memory profile over time
- More predictable process behavior under larger user counts

Regression risk:

- Low to medium

### 13. Compression may be missing at the app layer

The FastAPI app adds CORS and session middleware but no response-compression middleware in the application code.

Relevant file:

- `app.py`

Note:

- If gzip or brotli is already handled by the reverse proxy or CDN, this is not an application issue.
- If not, large JSON responses are paying avoidable transfer cost.

Suggested direction:

- Verify whether compression is already handled at the edge.
- If not, add compression at the appropriate layer.

Expected impact:

- Moderate on large JSON responses, especially over slower links

Regression risk:

- Low

## Recommended Execution Order

This order is optimized for performance gain versus regression risk.

### Phase 1: Low-risk, high-leverage wins

1. Reduce production logging overhead across frontend and backend.
2. Isolate the live clock from the dashboard root.
3. Render initial portfolio data before forcing price refresh.
4. Reduce startup prefetching to above-the-fold or immediately visible data.
5. Throttle or defer session `last_accessed` writes.

### Phase 2: Frontend load and responsiveness

1. Add route-level and view-level code splitting.
2. Lazy-load chat, markdown, and KaTeX.
3. Reduce global initialization of chat and notification subsystems.
4. Fix API in-flight dedupe.
5. Narrow query-cache subscriptions and remove unnecessary whole-app observers.

### Phase 3: Backend request-path cleanup

1. Move backend cache lookup ahead of classification work where possible.
2. Collapse portfolio-load fan-out into one repository path or one connection scope.
3. Unify security classification work into one pass.
4. Add bounded concurrency and batch writes in classification/proxy pipelines.
5. Reuse request-scoped quote/enrichment data in holdings/positions flows.

### Phase 4: Longer-tail cleanup

1. Add lifecycle management to per-user service registries.
2. Reevaluate overlapping cache layers and remove redundant ones.
3. Verify edge compression and add app-level compression only if needed.
4. Revisit table virtualization and large-list rendering paths after bigger blockers are addressed.

## Suggested Verification Plan

### Backend metrics to capture

- p50 and p95 latency for:
  - `/api/analyze`
  - `/api/risk-score`
  - `/api/performance`
  - holdings/positions endpoints
- DB queries and DB time per request
- Session lookup reads/writes per minute
- Classification cold-cache latency
- External FMP calls per request

### Frontend metrics to capture

- Time to first useful paint
- Time to interactive
- JS transferred, parsed, and executed on initial load
- Number of requests in the first 5 seconds after login
- Dashboard rerender frequency at idle
- Chat streaming frame drops or commit delays

### Logging metrics to capture

- Frontend logs shipped per minute
- `/api/log-frontend` request volume
- Average log batch size
- Time spent stringifying large request/response payloads

## What Not To Do First

These are lower priority than the issues above:

- Deep rewrites of core risk math
- Large async rewrites of the application
- Micro-optimizing isolated numerical functions before fixing the startup/request-graph issues
- Premature tuning of background systems before reducing the main-path load

## Working Conclusion

The system’s biggest performance tax appears to come from structural request and render overhead rather than one catastrophic algorithmic bottleneck.

The strongest near-term path is:

1. reduce hot-path logging
2. shrink and split the frontend
3. reduce startup overfetching
4. restore true backend cache fast-paths
5. collapse backend fan-out and duplicated enrichment/classification work
6. remove unnecessary write traffic from auth/session lookup

That sequence should produce large user-visible gains while keeping behavior stable.

## Audit Notes

- No code changes were made.
- This document is intended as a pickup point for later implementation planning.
- A useful next step would be to convert the items above into an implementation matrix with:
  - expected impact
  - regression risk
  - estimated effort
  - owner
  - verification method

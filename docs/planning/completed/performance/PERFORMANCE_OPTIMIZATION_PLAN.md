# Performance Optimization Plan
**Status:** DONE

## Context

Profiling identified three bottleneck areas: frontend page load (~103 HTTP requests, duplicate calls, 500 errors), gateway AI chat (~20.5s for a simple "hey", dominated by MCP startup + memory search + TTFT), and backend heavy endpoints (~5-10s for `analyze_portfolio()`). This plan prioritizes quick wins first, then larger structural improvements.

## Problem Summary

### Frontend Page Load
- **~103 HTTP requests** on initial load — ~55 are `POST /api/log-frontend` (one per log entry)
- **`frontendLogger.processQueue()`** sends each log as an individual `fetch()` — "batch of 10" means 10 parallel fetches, not a single batched POST
- **Dual data-fetching paths (legacy + resolver)**: `ModernDashboardApp.tsx:165-166` mounts both `usePortfolioSummary()` and `useRiskAnalysis()` at the app level, firing legacy-key queries. Container components separately mount resolver-based hooks (`useRiskAnalysis`, `useRiskScore`, `usePerformance`) with different TanStack keys. Both paths converge on `PortfolioCacheService` which deduplicates in-flight requests, but the fragmented cache namespaces cause redundant query-layer work and potential timing-gap duplicate HTTP calls.
- **`/api/positions/market-intelligence`** returning 500 errors at `routes/positions.py:411`, retried 4× per load (nested retry: `APIService.ts:335` retry + resolver `useDataSource.ts:91` retry)
- **Eager prefetch key mismatch**: `useDataSourceScheduler` (`scheduler.ts:89`) prefetches with `buildDataSourceQueryKey(sourceId)` (no params), but consumers pass `portfolioId`/`portfolioName` — prefetch cache misses because query keys don't match

### Gateway AI Chat
- **~20.5s total** for first "hey" (3 API turns)
- **`thinking.type = "enabled"`** → deprecated, should be `"adaptive"`. 10k budget_tokens always allocated even for trivial messages
- **System prompt ~16.8k tokens** (dynamic sections: market context, workspace context, tool manifest, portfolio context)
- **`memory_recall` ~3.5s** — SQLite + OpenAI embeddings hybrid search (767 chunks, 1536-dim vectors, cosine similarity)
- **MCP server startup is sequential** — `for name in servers: await connect()` with 15s timeout each. 6+ servers connected on startup
- **TTFT ~2.9s** per turn (3 turns = ~9s just waiting for first tokens)

### Backend
- **`analyze_portfolio()` ~5-10s** — FMP API calls + covariance matrix + factor model
- **2-worker Uvicorn** — one heavy request blocks half capacity
- **Efficient frontier cold cache ~2s** (CVXPY solver init) — acceptable, noted only

## Phase 1 — Quick Wins (No Architecture Changes)

### 1A. Batch `frontendLogger` into true single-POST batches
**Impact**: ~55 requests → ~6 requests | **Effort**: Small | **Files**: `frontend/packages/chassis/src/services/frontendLogger.ts`

The backend already supports batched `{ logs: [...], sessionId }` payloads (`routes/frontend_logging.py:287`). The frontend just needs to use it:

```ts
// Before (line 772): batch.map(payload => this.sendToBackend(payload))  // 10 individual POSTs
// After: single POST with batch payload
private async sendBatch(payloads: LogPayload[]): Promise<void> {
  await fetch(`${this.baseUrl}/api/log-frontend`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      logs: payloads,
      sessionId: this.sessionId,
      flushTime: new Date().toISOString()
    }),
    credentials: 'include'
  });
}
```

The backend batch path reads `sessionId` from the wrapper object (`frontend_logging.py:291`) and passes it to `process_individual_log()`, so `sessionId` must be included.

Add a 200ms idle-timer debounce so logs accumulate before sending, rather than flushing on every `queueLog()` call. **Important**: also update the `handleBeforeUnload` handler (`frontendLogger.ts:138`) to flush any pending queued logs via `navigator.sendBeacon()` in addition to the session summary — otherwise logs from the final 200ms before navigation are lost. Similarly add a `visibilitychange` listener to flush when the tab goes hidden.

### 1B. Fix `/api/positions/market-intelligence` 500 error
**Impact**: Eliminates up to 12 retry requests + error noise | **Effort**: Small | **Files**: `routes/positions.py:411`

The endpoint at `routes/positions.py:411` (`get_market_intelligence`) is throwing unhandled exceptions. Investigate root cause and fix. If the endpoint requires data that's unavailable (e.g. no positions loaded yet), return an empty/graceful `200` response instead of crashing.

**Retry amplification**: The frontend has two nested retry layers — `APIService.ts:335` (up to 4 HTTP attempts per query execution) and `useDataSource.ts:91` (TanStack Query adds 2 retries on top). Worst case: a single 500 triggers up to **12 actual HTTP requests** (4 fetch retries × 3 TanStack attempts). Fix must either eliminate 500s entirely or add the endpoint to a no-retry/reduced-retry policy.

### 1C. Switch `thinking.type` from `"enabled"` to `"adaptive"`
**Impact**: Faster trivial responses, lower token usage | **Effort**: Trivial | **Files**: `AI-excel-addin/packages/claude-gateway/claude_gateway/runner.py:559`

```python
# Before:
base_kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget_tokens}
# After:
base_kwargs["thinking"] = {"type": "adaptive", "budget_tokens": budget_tokens}
```

This lets Claude skip thinking entirely for simple messages like "hey", reducing TTFT from ~2.9s to potentially <1s on trivial turns.

### 1D. Parallelize MCP server startup
**Impact**: ~45-90s worst case → ~15s startup | **Effort**: Small | **Files**: `AI-excel-addin/packages/claude-gateway/claude_gateway/mcp_client.py:98-116`

Replace sequential `for name: await connect()` with `asyncio.gather()`:

```python
# Before (line 98-116):
for server_name, server_config in mcp_servers.items():
    ...
    state = await self._connect(server_name, server_config)
# After:
async def _try_connect(name, config):
    try:
        return name, await self._connect(name, config)
    except Exception as exc:
        log.warning("MCP server %s failed to connect: %s", name, exc)
        return name, None

tasks = [
    _try_connect(name, config)
    for name, config in mcp_servers.items()
    if self._is_allowed(name, config)
]
results = await asyncio.gather(*tasks)
for name, state in results:
    if state is not None:
        self._servers[name] = state
```

Handle partial failures — some servers may timeout without blocking others. `_apply_collision_filtering()` runs after all connections complete (unchanged).

## Phase 2 — Frontend Request Reduction

### 2A. Eliminate duplicate data-fetching between legacy and resolver hooks
**Impact**: Eliminates redundant query-layer work and fragmented cache (potential timing-gap duplicate HTTP calls) | **Effort**: Medium | **Files**: `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx`, `frontend/packages/connectors/src/features/portfolio/hooks/usePortfolioSummary.ts`, container components

Two independent data-fetching systems fire on initial load:

1. **Legacy hooks**: `usePortfolioSummary()` fires legacy-key queries for `risk-score`, `risk-analysis`, and `performance` (`usePortfolioSummary.ts:237`). Called from both `ModernDashboardApp.tsx:165` and `PortfolioOverviewContainer.tsx:71`.
2. **Resolver hooks** (mounted in containers): `useRiskAnalysis()` (`RiskAnalysisModernContainer.tsx:299`), `useRiskScore()` (same container), and `usePerformance()` (`PerformanceViewContainer.tsx:322`) all go through `useDataSource` with resolver-key queries.

These two systems use **different TanStack Query keys** (legacy vs resolver), so TanStack does NOT deduplicate them at the query layer. However, both paths converge on the same `PortfolioManager` → `PortfolioCacheService`, which coordinates in-flight requests by `portfolioId + operation`. So the duplication is primarily **query-layer overhead and fragmented cache namespaces** rather than guaranteed duplicate HTTP requests. The real cost is: double query function execution, double state management, and potential timing gaps where one path's cache doesn't satisfy the other.

Additionally, within the resolver system itself there's a param-mismatch duplicate: `AssetAllocationContainer.tsx:104` passes `performancePeriod: '1M'` to `useRiskAnalysis()`, while other consumers call it without params. The backend treats omitted `performance_period` as `'1M'` (`portfolio_service.py:117`), so these are semantically identical but generate different cache keys (`useDataSource.ts:88` keys on raw params).

Fix options:
- **Option A (preferred)**: Migrate `usePortfolioSummary()` consumers to use the resolver system so all queries go through the same key space. This eliminates the legacy/resolver duplicate. For the within-resolver param-mismatch, normalize defaults so omitted `performancePeriod` and `performancePeriod: '1M'` produce the same cache key.
- **Option B (quick)**: Remove `usePortfolioSummary()` calls from `ModernDashboardApp.tsx` (line 165) — but note `PortfolioOverviewContainer.tsx:71` still needs it for portfolio overview data. Would need to verify which consumers actually depend on legacy-key cache entries vs can switch to resolver hooks.
- **Option C (diagnostic first)**: Add timing instrumentation to confirm both systems actually hit the backend (not just cache) before choosing A or B.

### 2B. Fix eager prefetch cache key alignment
**Impact**: Prefetch actually warms the cache for consumers | **Effort**: Medium | **Files**: `frontend/packages/connectors/src/resolver/scheduler.ts`, `frontend/packages/connectors/src/resolver/core.ts`

The scheduler prefetches with `buildDataSourceQueryKey(sourceId)` (no params → `core.ts:31` serializes `{}` as the params component), but consumers resolve with portfolio-scoped params (e.g. `{ portfolioId: '...' }` or `{ portfolioName: '...' }`). Result: prefetch populates `['sdk', sourceId, '{}']` but consumers query `['sdk', sourceId, '{"portfolioId":"..."}']` — cache miss every time.

Fix: Build per-source default params from `currentPortfolio` (already in scope at `scheduler.ts:64`). `buildDataSourceQueryKey` takes `params?: Partial<SDKSourceParamsMap[Id]>` — pass the portfolio-scoped params each source expects:

```ts
const buildDefaultParams = (sourceId: DataSourceId, portfolio: Portfolio) => {
  // Map each source to the params its consumers pass
  const portfolioParam = { portfolioId: portfolio.id };
  const paramsBySource: Partial<Record<DataSourceId, Record<string, unknown>>> = {
    'risk-analysis': portfolioParam,
    'risk-score': portfolioParam,
    'performance': portfolioParam,   // usePerformance keys by portfolioId
    'positions': portfolioParam,
    // ... other eager sources
  };
  return paramsBySource[sourceId] ?? {};
};

// In prefetch loop:
const params = buildDefaultParams(sourceId, currentPortfolio);
await queryClient.prefetchQuery({
  queryKey: buildDataSourceQueryKey(sourceId, params),
  queryFn: ({ signal }) => resolveWithCatalog(sourceId, params, services, currentPortfolio, signal),
  staleTime: dataCatalog.describe(sourceId).refresh.defaultTTL * 1000,
});
```

Once keys align, **then** parallelize independent sources by dependency level:

```ts
const levels = groupByDependencyLevel(orderedSourceIds);
for (const level of levels) {
  await Promise.all(level.map(sourceId => prefetchSource(sourceId)));
}
```

### 2C. Throttle/disable `frontendLogger` for `network` category in production
**Impact**: Further reduces log noise | **Effort**: Small | **Files**: `frontend/packages/chassis/src/services/frontendLogger.ts`

Auto-logged API request/response entries dominate log volume. Options:
- Sample network logs (1 in 10) in production
- Only log errors and slow requests (>2s) for network category
- Add a `VITE_LOG_LEVEL` env var to control verbosity

## Phase 3 — Gateway Chat Optimization

### 3A. Reduce system prompt size
**Impact**: ~5-8k fewer input tokens per turn, faster TTFT | **Effort**: Medium | **Files**: `AI-excel-addin/api/analyst/config.py`

The ~16.8k system prompt includes dynamic sections (market context, workspace context, tool manifest) that are rebuilt per conversation. Strategies:
- Move tool manifest to tool descriptions (already sent as tools param)
- Lazy-load market context only when relevant (first financial question, not "hey")
- Cache and reuse workspace context within a session
- Use prompt caching (already using `cache_control: ephemeral` on system blocks — verify it's working)

### 3B. Optimize `memory_recall` latency
**Impact**: 3.5s → <1s per recall | **Effort**: Medium-Large | **Files**: `AI-excel-addin/api/memory/store.py`

Current: 767 chunks × 1536-dim OpenAI embeddings + SQLite FTS5 hybrid search. Options:
- Pre-compute and cache embeddings (avoid re-embedding on every query)
- Reduce chunk count by merging small chunks
- Use a vector index (FAISS/Annoy) instead of brute-force cosine similarity
- Skip memory_recall entirely for trivial messages (length < 20 chars, no question marks)

### 3C. Defer non-essential MCP servers
**Impact**: Fewer servers to connect on startup | **Effort**: Small | **Files**: Gateway MCP config

Classify servers into tiers:
- **Tier 1 (always connect)**: portfolio-mcp, fmp-mcp (core tools)
- **Tier 2 (connect on first use)**: edgar-financials, ibkr-mcp, model-engine, etc.

Lazy-connect Tier 2 servers on first tool call instead of startup.

## Phase 4 — Backend (Lower Priority)

### 4A. Profile `analyze_portfolio()` breakdown
**Impact**: Identify specific slow paths | **Effort**: Small (profiling only)

Add timing instrumentation to identify the split between:
- FMP API calls (price data, profiles)
- Covariance matrix computation
- Factor model fitting
- Result object construction

### 4B. Evaluate Uvicorn worker count
**Impact**: Better concurrency | **Effort**: Trivial

Current: 2 workers. Profile memory usage and evaluate bumping to 4 workers. One heavy `analyze_portfolio()` currently blocks 50% capacity.

## Priority Order

| # | Item | Impact | Effort | Repo |
|---|------|--------|--------|------|
| 1 | 1C — `thinking: adaptive` | High | Trivial | AI-excel-addin |
| 2 | 1D — Parallel MCP startup | High | Small | AI-excel-addin |
| 3 | 1A — Batch frontendLogger | Medium | Small | risk_module/frontend |
| 4 | 1B — Fix market-intelligence 500 | Medium | Small | risk_module |
| 5 | 2A — Dedup legacy vs resolver hooks | Medium | Medium | risk_module/frontend |
| 6 | 2B — Fix prefetch key alignment + parallelize | Medium | Medium | risk_module/frontend |
| 7 | 3A — Reduce system prompt | High | Medium | AI-excel-addin |
| 8 | 3B — Optimize memory_recall | High | Med-Large | AI-excel-addin |
| 9 | 3C — Defer MCP servers | Medium | Small | AI-excel-addin |
| 10 | 2C — Throttle network logs | Low | Small | risk_module/frontend |
| 11 | 4A — Profile analyze_portfolio | Info | Small | risk_module |
| 12 | 4B — Uvicorn workers | Low | Trivial | risk_module |

## Verification

After each phase:
1. **Frontend**: Count total HTTP requests on page load (target: <30 from current ~103)
2. **Gateway**: Measure time-to-first-response for "hey" (target: <5s from current ~20.5s)
3. **Backend**: Profile `POST /api/analyze` response time (baseline: 5-10s)

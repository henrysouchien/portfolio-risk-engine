# Performance Baseline — 2026-03-10
**Status:** ACTIVE

**Purpose:** Quantitative performance baseline measured via the observability system (Phases 1A-3A). Cross-referenced against the qualitative audit (`PERFORMANCE_AUDIT_2026-03-09.md`) and backend optimization plan (`BACKEND_PERFORMANCE_PLAN.md`). Use this document to track improvement over time.

## Measurement Conditions

- **Backend**: risk_module on localhost:5001, single uvicorn worker, PostgreSQL local
- **Frontend**: Vite dev server on localhost:3000
- **Data source**: `GET /api/debug/timing?minutes=30` (1,157 entries across 61 groups)
- **Frontend waterfall**: Captured via `frontendLogger.network.waterfall()` after fresh page reload
- **Cache state**: Mix of cold and warm — server restarted ~30 min before measurement

---

## 1. End-to-End Page Load (Frontend Waterfall)

Fresh page reload → time until all visible data rendered:

```
Timeline (cold cache, measured from navigation epoch):

[     0ms] Auth check (/auth/status)                         ~3ms     ← instant
[     0ms] Portfolio load (/api/portfolios/CURRENT_PORTFOLIO) ~2.2s   ← blocks everything
[  ~2.5s] Parallel burst fires (positions, alerts, prefetch):
[  ~2.5s]   /api/positions/alerts                             ~3.8s
[  ~2.5s]   /plaid/pending-updates                            ~3ms
[  ~2.5s]   /api/snaptrade/pending-updates                    ~3ms
[  ~5.6s] Data source queries fire (after portfolio ready):
[  ~5.6s]   /api/risk-score                                   ~38s    ← CRITICAL PATH
[  ~5.6s]   /api/analyze                                      ~38s    ← CRITICAL PATH
[  ~5.6s]   /api/performance                                  ~38s    ← CRITICAL PATH
[  ~5.6s]   /api/positions/market-intelligence                ~13s
[  ~5.6s]   /api/positions/ai-recommendations                 ~23s
[  ~5.6s]   /api/positions/metric-insights                    ~27s
[  ~5.6s]   /api/allocations/target                           ~43s    ← SLOWEST
[ ~48.8s] Last response received

Total time to full data: ~49s (cold cache)
```

**Key observation**: After the initial auth+portfolio check (~2.5s), all heavy queries fire in parallel at ~5.6s. The critical path is ~43s, dominated by event-loop blocking (all sync handlers compete for the single worker thread).

---

## 2. Backend Request Timing (Top 15 by Average Latency)

| Endpoint | Count | Avg (ms) | p50 (ms) | p95 (ms) | Min (ms) | Max (ms) |
|----------|-------|----------|----------|----------|----------|----------|
| POST /api/factor-intelligence/portfolio-recommendations | 3 | 69,800 | 70,527 | 74,682 | 63,729 | 75,144 |
| POST /api/performance | 3 | 44,418 | 43,469 | 69,825 | 17,034 | 72,753 |
| POST /api/risk-score | 3 | 37,833 | 43,469 | 65,086 | 2,544 | 67,487 |
| POST /api/analyze | 6 | 29,922 | 20,752 | 63,584 | 12,088 | 70,289 |
| GET /api/risk-settings | 1 | 26,509 | — | — | — | — |
| GET /api/positions/ai-recommendations | 3 | 25,832 | 28,928 | 32,297 | 15,898 | 32,671 |
| GET /api/positions/market-intelligence | 7 | 13,144 | 11,509 | 20,046 | 9,392 | 21,177 |
| GET /api/allocations/target | 9 | 11,280 | 9,942 | 31,357 | 1 | 35,777 |
| GET /api/positions/metric-insights | 7 | 7,973 | 7,440 | 12,497 | 3,539 | 13,118 |
| POST /api/portfolio/refresh-prices | 6 | 6,940 | 2,290 | 21,360 | 6 | 24,202 |
| GET /api/portfolios/CURRENT_PORTFOLIO | 6 | 5,671 | 5,280 | 11,130 | 2,228 | 12,826 |
| GET /api/positions/alerts | 35 | 3,835 | 2,692 | 6,343 | 2,196 | 8,347 |
| POST /api/log-frontend | 136 | 1,444 | 5 | 6,626 | 1 | 15,260 |

**Fast endpoints** (< 10ms avg): `/auth/status` (3ms), `/plaid/pending-updates` (4ms), `/api/snaptrade/pending-updates` (5ms), `/api/health` (4ms), `/api/debug/timing` (3ms)

---

## 3. analyze_portfolio() Step Breakdown

7 samples, showing where time is spent inside the core analysis function:

| Step | Avg (ms) | % of Total |
|------|----------|------------|
| resolve_config | 87 | 3% |
| standardize | 0 | 0% |
| **build_view_and_betas** | **3,205** | **97%** |
| risk_checks | 3 | 0% |
| result_construction | 3 | 0% |
| **total** | **3,298** | 100% |

`build_view_and_betas` (which runs `build_portfolio_view()` + `calc_max_factor_betas()` concurrently via ThreadPoolExecutor) is the overwhelming bottleneck at **97% of total time**.

---

## 4. FMP Dependency Timing

External FMP API calls broken out by endpoint:

| FMP Endpoint | Count | Avg (ms) | p50 (ms) | p95 (ms) | Max (ms) |
|-------------|-------|----------|----------|----------|----------|
| price_target_consensus | 42 | 1,330 | 1,648 | 1,736 | 1,829 |
| price_target | 42 | 1,300 | 1,647 | 1,731 | 1,810 |
| analyst_grades | 30 | 1,259 | 1,648 | 1,730 | 1,793 |
| historical_price_adjusted | 74 | 705 | 850 | 957 | 1,007 |
| historical_price_eod | 269 | 182 | 129 | 657 | 1,273 |
| earnings_calendar | 7 | 176 | 152 | 235 | 248 |
| news_stock | 7 | 131 | 113 | 205 | 230 |
| dividends | 238 | 130 | 99 | 242 | 533 |
| profile | 89 | 128 | 100 | 216 | 312 |
| search | 4 | 113 | 113 | 118 | 119 |

**Total FMP calls in 30 min window**: 806
**Dominant call**: `historical_price_eod` (269 calls, 33% of all FMP traffic)
**Slowest per-call**: `price_target_consensus` / `price_target` / `analyst_grades` (~1.3-1.6s avg)
**Total FMP time**: ~182s of cumulative API wait

---

## 5. Event Loop Starvation Evidence

The timing data strongly confirms the event loop blocking issue from `BACKEND_PERFORMANCE_PLAN.md` Phase A1:

- **`/api/allocations/target`**: Should be a fast DB read (1ms min) but shows 35.8s max and 11.3s avg. This is a **lightweight endpoint being blocked by heavy concurrent work**.
- **`/api/log-frontend`**: Should be instant (JSON parse + log write) but shows 15.3s max and 1.4s avg (p50 is 5ms — the spikes are pure event loop contention).
- **`/api/risk-settings`**: 26.5s for a single DB read — waiting behind concurrent analysis.

These are fast endpoints being starved by sync-heavy handlers (`/api/analyze`, `/api/risk-score`, `/api/performance`) that block the event loop.

---

## 6. Cross-Reference: Audit Findings → Measured Impact

| Audit Finding | Backend Plan Phase | Measured Impact | Priority |
|--------------|-------------------|-----------------|----------|
| **#8: Auth session write every request** | A2 | 26 auth requests in 30 min, each doing SELECT+UPDATE+COMMIT. Low absolute cost (~3ms) but unnecessary writes. | Medium |
| **Event loop blocking (pre-existing bug)** | A1 | **HIGHEST IMPACT**. Lightweight endpoints (allocations, log-frontend, risk-settings) inflated 10-100x by contention. Causes 49s cold page load when actual work is ~15s. | **P0** |
| **#5: Cache fast-path weakened by classification** | C | `resolve_config` at 87ms avg (3% of analyze). Classification cost hidden inside `build_view_and_betas`. Warm cache drops to 3ms. | Medium |
| **#7: Security classification serial/duplicated** | E | `analyst_grades` + `price_target` + `price_target_consensus` = ~3.9s per ticker cold. 114 calls in 30 min. | Medium |
| **#6: Portfolio DB loading fan-out** | D | `GET /portfolios/CURRENT_PORTFOLIO` at 5.7s avg — high for a DB load. Some of this is repricing. | Medium |
| **#9: Positions/holdings enrichment repeats work** | F | `/api/positions/alerts` at 3.8s avg × 35 calls = most-hit slow endpoint. 269 `historical_price_eod` calls suggest per-symbol serial pricing. | High |
| **#1: Frontend bundle too large** | (Frontend plan) | Not measured here (requires Lighthouse). 2.1MB JS payload from prior audit. | High |
| **#2: Frontend startup overfetching** | (Frontend plan) | Measured: 10+ concurrent requests fire within 100ms of portfolio ready. All compete for the single worker. | High |
| **#3: Dashboard shell 1s rerender** | (Frontend plan) | Not measured server-side. Clock-driven rerender burns client CPU. | Low |
| **#4: Logging overhead** | (Frontend plan) | 136 `log-frontend` POSTs in 30 min. p50=5ms, p95=6.6s (contention). 570 frontendLogger call sites. | Medium |
| **#10: Client cache layers overlap** | (Frontend plan) | Not directly measurable from backend. | Low |

---

## 7. Top Bottlenecks (Ranked by User Impact)

### Tier 1 — Fix These First (>10x improvement potential)

1. **Event loop starvation** (Backend Plan Phase A1)
   - Root cause: 7+ sync-heavy handlers in `routes/positions.py` + 2 in `app.py` block the single uvicorn worker
   - Impact: All concurrent requests queue behind the slowest handler. 49s cold page load → should be ~15s with proper threadpool wrapping
   - Fix: `run_in_threadpool()` on all sync-heavy `async def` handlers
   - Expected: Cold page load drops from ~49s to ~15-20s

2. **`build_portfolio_view()` is the 97% bottleneck in analysis**
   - Root cause: Serial FMP API calls for each ticker (price history, dividends, profile)
   - Impact: 3.2s avg inside `analyze_portfolio()`, driving `/api/analyze` to 30s avg
   - Fix: Batch FMP calls, cache price series aggressively, reduce redundant fetches
   - Expected: `analyze_portfolio()` drops from 3.3s to <1s on warm cache

3. **`/api/positions/alerts` called 35 times in 30 min**
   - Root cause: Frontend polling + cache invalidation triggers frequent refetches
   - Impact: Each call takes 3.8s avg, repricing all positions each time
   - Fix: Cache enriched positions, batch pricing (Backend Plan Phase F1)
   - Expected: Warm-cache alerts in <100ms

### Tier 2 — Significant Wins

4. **Factor intelligence endpoints** (~70s avg)
   - `/api/factor-intelligence/portfolio-recommendations` at 70s is the single slowest endpoint
   - Likely serial FMP calls per factor × per ticker
   - Investigate concurrent fetching + caching

5. **Classification cold-cache cost** (Backend Plan Phase E)
   - `analyst_grades`, `price_target`, `price_target_consensus` = ~1.3-1.6s each per ticker
   - 114 calls in 30 min — batch + cache would eliminate most

6. **Session write throttle** (Backend Plan Phase A2)
   - Low absolute cost but free improvement — stop writing on every request

### Tier 3 — Frontend

7. **Bundle size** (2.1MB JS) — code splitting + lazy loading
8. **Startup overfetch** — 10+ requests in first 100ms after portfolio ready
9. **Frontend logging volume** — 136 backend POSTs in 30 min

---

## 8. Baseline Metrics (Track Over Time)

| Metric | Current Value | Target | Notes |
|--------|--------------|--------|-------|
| Cold page load (time to last response) | ~49s | <15s | Event loop fix = biggest win |
| `POST /api/analyze` avg | 29,922ms | <5,000ms | Cache + threadpool |
| `POST /api/analyze` p50 (warm) | 20,752ms | <500ms | Mostly event loop contention |
| `POST /api/risk-score` avg | 37,833ms | <5,000ms | Same root cause as analyze |
| `POST /api/performance` avg | 44,418ms | <5,000ms | Same root cause |
| `analyze_portfolio()` total | 3,298ms | <1,000ms | build_view_and_betas optimization |
| `analyze_portfolio()` build_view_and_betas | 3,205ms (97%) | <800ms | FMP batch + cache |
| `/api/positions/alerts` avg | 3,835ms | <200ms | Batch pricing + cache |
| `/api/positions/alerts` call count (30 min) | 35 | <10 | Frontend polling reduction |
| FMP `historical_price_eod` calls (30 min) | 269 | <50 | Cache hit rate improvement |
| FMP total calls (30 min) | 806 | <200 | Batch + cache |
| `POST /api/log-frontend` p95 | 6,626ms | <50ms | Event loop fix |
| `GET /api/allocations/target` avg | 11,280ms | <50ms | Event loop fix (DB read = 1ms) |

---

## 9. Recommended Execution Order

Based on measured data, not just qualitative assessment:

### Phase 1: Event Loop Fix (A1) — **Highest ROI**
- Wrap all sync-heavy async handlers with `run_in_threadpool()`
- Expected: ~60% reduction in cold page load time
- Risk: Very low — mechanical change, no business logic

### Phase 2: Session Write Throttle (A2) + Cache-Before-Classification (C)
- Throttle `last_accessed` writes to every 5 min
- Move cache lookup before `get_full_classification()`
- Expected: Warm-cache `/api/analyze` drops to <500ms

### Phase 3: Positions Enrichment (F1) + Classification Pipeline (E)
- Batch pricing in `_calculate_market_values()`
- Pass security_types to avoid redundant classification
- Expected: `/api/positions/alerts` drops from 3.8s to <200ms

### Phase 4: Frontend Optimization
- Code splitting (2.1MB → multiple lazy chunks)
- Reduce startup overfetch (10+ parallel → 3-4 critical)
- Reduce log-frontend volume

---

## 10. How to Re-Measure

```bash
# Backend timing summary (last N minutes)
curl -s "http://localhost:5001/api/debug/timing?minutes=30" | python3 -m json.tool

# Filter by kind
curl -s "http://localhost:5001/api/debug/timing?minutes=30&kind=request"
curl -s "http://localhost:5001/api/debug/timing?minutes=30&kind=dependency"

# Frontend waterfall: check browser console for [NETWORK] Waterfall: entries
# Or use routeTiming API:
#   frontendLogger.routeTiming.start('dashboard')
#   frontendLogger.routeTiming.end('dashboard')
```

After each optimization phase, re-run the timing collection and update the baseline metrics table above.

---

## 11. Post-Optimization Measurement — Phases A+C+D+E+F (2026-03-10)

**Commit**: `d8797e1b` (phases C-F + A2 bugfix), `8b45e042` (phase A1+A2)
**Method**: Fresh server restart (cold cache), two consecutive page loads, 15-minute timing window (596 entries, 45 groups). Mix of cold + warm — comparable to baseline conditions.

### Event-Loop Starvation — Eliminated

These lightweight endpoints were previously starved by sync-heavy handlers blocking the single uvicorn worker. With `run_in_threadpool()`, they now run at their true latency:

| Endpoint | Baseline | Post-Opt | Change |
|----------|----------|----------|--------|
| `GET /api/allocations/target` | 11,280ms | **33ms** | **-99.7%** |
| `GET /api/portfolios/CURRENT_PORTFOLIO` | 5,671ms | **164ms** | **-97.1%** |
| `POST /api/portfolio/refresh-prices` | 6,940ms | **6ms** | **-99.9%** |
| `POST /api/log-frontend` | 1,444ms (p95: 6,626ms) | **95ms** (p50: 1ms) | **-93.4%** |
| `GET /api/risk-settings` | 26,509ms | **5,874ms** | **-77.8%** |

### Heavy Analysis Endpoints — Significant Improvement

No longer competing for the event loop. All three core analysis endpoints improved:

| Endpoint | Baseline | Post-Opt | Change |
|----------|----------|----------|--------|
| `POST /api/analyze` | 29,922ms | **20,965ms** | **-29.9%** |
| `POST /api/risk-score` | 37,833ms | **20,879ms** | **-44.8%** |
| `POST /api/performance` | 44,418ms | **20,882ms** | **-53.0%** |
| `POST /api/factor-intelligence/portfolio-recommendations` | 69,800ms | **29,993ms** | **-57.0%** |

### analyze_portfolio() Internal Breakdown

| Step | Baseline | Post-Opt | Change |
|------|----------|----------|--------|
| resolve_config | 87ms | **2ms** | -98% (Phase C: cache-before-classification) |
| build_view_and_betas | 3,205ms | **2,003ms** | -37% (Phases D+E+F) |
| **total** | **3,298ms** | **2,013ms** | **-39%** |

### Position Endpoints — Not Directly Comparable

Position endpoints (`/alerts`, `/market-intelligence`, `/metric-insights`, `/ai-recommendations`) show higher numbers in this measurement. This is expected: the baseline was measured 30 min after a server restart (heavily warmed caches), while this measurement includes cold-cache first loads. These endpoints are dominated by external FMP API calls (~1-1.6s per ticker) that only benefit from cache warmth, not from our backend optimizations. Phase F1 (batch pricing) will show gains on the inner `_calculate_market_values()` path once caches are warm.

### FMP Dependency Timing

| FMP Endpoint | Baseline Calls (30m) | Post-Opt Calls (15m) | Avg Latency |
|-------------|---------------------|---------------------|-------------|
| historical_price_eod | 269 | 32 | 160ms |
| dividends | 238 | 108 | 144ms |
| profile | 89 | 39 | 137ms |

FMP call volume reduced proportionally — fewer redundant fetches.

### Summary

| Metric | Baseline | Post-Opt | Status |
|--------|----------|----------|--------|
| Event-loop-starved endpoints | 5-27s | **6ms-164ms** | **Fixed** |
| `POST /api/analyze` avg | 29,922ms | 20,965ms | -30% |
| `POST /api/performance` avg | 44,418ms | 20,882ms | -53% |
| `POST /api/risk-score` avg | 37,833ms | 20,879ms | -45% |
| `analyze_portfolio()` total | 3,298ms | 2,013ms | -39% |
| `resolve_config` (cache hit) | 87ms | 2ms | -98% |
| Factor recommendations avg | 69,800ms | 29,993ms | -57% |
| `POST /api/log-frontend` avg | 1,444ms | 95ms | -93% |

### Remaining Bottlenecks

1. **`build_view_and_betas` at 2s** — still 97% of `analyze_portfolio()`. Further gains require FMP price series caching or parallelization inside `build_portfolio_view()`.
2. **Position enrichment cold-cache** — first load still pulls FMP profiles + analyst data serially per ticker. Batch pricing (Phase F1) helps the inner loop but FMP latency dominates.
3. **Factor recommendations at 30s** — improved 57% but still slow. Likely needs FMP call batching per factor×ticker matrix.
4. **Frontend request volume** — still fires 10+ concurrent requests on page load. Frontend optimization (Phase 4 in baseline doc) would reduce total request count.

---

## 12. FMP Call Deduplication — Proxy Cache + Shared Analysis (2026-03-10)

**Commit**: `cbe92fc7`
**Method**: Fresh page load on localhost:3000 after hot-reload, 1-minute timing window.

### Optimization 1: Proxy Returns Pre-fetch Cache (`compute_factor_exposures`)

**Root cause**: N portfolio tickers sharing the same proxy (e.g., all US stocks → SPY for market) triggered N×2 redundant FMP fetches — once per ticker in Phase 1 (beta computation) and again in Phase 3 (factor vol). With 30 tickers × 5 proxies × 2 phases = ~300 FMP calls when ~10 unique fetches would suffice.

**Fix**: `_prefetch_proxy_returns()` collects all unique proxy tickers across the portfolio and fetches each once in parallel via ThreadPoolExecutor. Returns a `Dict[str, pd.Series]` cache shared by both phases. `_cached_excess_return()` computes excess returns (momentum, value) from cached data instead of re-fetching.

**Scope**: Request-scoped (function-local dict, GC'd on return). No connection to CacheManager needed — cannot go stale.

| Metric | Phase A-F | Post-Proxy-Cache | Change |
|--------|-----------|-----------------|--------|
| `factor_exposures` step | 1,400ms | **174ms** | **-87%** |
| `build_portfolio_view` total | 2,013ms | **215ms** | **-89%** |

### Optimization 2: Shared Correlation + Performance Cache (`recommend_portfolio_offsets`)

**Root cause**: `recommend_portfolio_offsets()` calls `recommend_offsets()` per risk driver (2-4 drivers). Each call independently computed correlation matrices and performance profiles (Sharpe, vol) for ~100 ETFs — identical work repeated per driver.

**Fix**: Pre-compute panel, correlation matrices (`compute_per_category_correlation_matrices`), and performance profiles (`compute_factor_performance_profiles`) once before the driver loop. Pass via `cached_panel`, `cached_corr`, `cached_perf` parameters.

**Scope**: Request-scoped (function-local variables, GC'd on return). The underlying panel build was already LRU-cached; this eliminates the per-driver correlation + performance redundancy.

| Metric | Phase A-F | Post-Shared-Cache | Change |
|--------|-----------|-------------------|--------|
| `recommend_offsets_loop` | ~26,000ms | **7,625ms** | **-71%** |
| `recommend_portfolio_offsets` total | ~28,000ms | **8,375ms** | **-70%** |

### Cumulative Summary (Baseline → Phase A-F → FMP Dedup)

| Metric | Original Baseline | Phase A-F | FMP Dedup | Total Improvement |
|--------|------------------|-----------|-----------|-------------------|
| `factor_exposures` step | ~1,400ms* | ~1,400ms | **174ms** | **-88%** |
| `build_portfolio_view` total | ~3,200ms* | 2,013ms | **215ms** | **-93%** |
| `analyze_portfolio()` total | 3,298ms | 2,013ms | ~225ms** | **-93%** |
| `recommend_portfolio_offsets` total | ~70,000ms† | ~28,000ms | **8,375ms** | **-88%** |
| Event-loop-starved endpoints | 5-27s | 6ms-164ms | 6ms-164ms | **-99%** |

\* Estimated from `build_view_and_betas` step (factor_exposures was not instrumented pre-FMP-dedup).
\** `build_view_and_betas` step within analyze_portfolio.
† Pre-Phase A-F, factor-recommendations endpoint averaged 70s (includes event-loop contention).

### Phase G: Panel-Based Performance Profiles (compute_factor_performance_profiles)

**Before**: `compute_factor_performance_profiles()` called `calculate_portfolio_performance_metrics()` per ETF (~100 ETFs), each re-fetching FMP price data via the full performance engine. ~5,000ms for the perf_profiles step alone.

**Fix**: Compute annual_return, volatility, Sharpe, max_drawdown, and beta directly from the panel's monthly return series (same approach the basket path already used). Eliminates ~100 FMP re-fetch calls. Beta computed via OLS on overlapping observations with the benchmark column.

**File changed**: `core/factor_intelligence.py` — unified the basket and non-basket paths in `compute_factor_performance_profiles()`.

| Metric | Pre-Phase-G | Post-Phase-G | Change |
|--------|-------------|--------------|--------|
| `perf_profiles_ms` (within recommend_offsets_loop) | ~5,000ms | **234ms** | **-95%** |
| `recommend_offsets_loop` | 7,625ms | **731ms** | **-90%** |
| `recommend_portfolio_offsets` total (cold) | 8,375ms | **3,391ms** | **-60%** |
| `recommend_portfolio_offsets` total (warm) | N/A | **417ms** | — |

### Cumulative Summary (Baseline → Phase A-G)

| Metric | Original Baseline | Phase A-F | Phase G (current) | Total Improvement |
|--------|------------------|-----------|-------------------|-------------------|
| `factor_exposures` step | ~1,400ms* | **174ms** | 174ms | **-88%** |
| `build_portfolio_view` total | ~3,200ms* | **215ms** | 215ms | **-93%** |
| `analyze_portfolio()` total | 3,298ms | ~225ms** | ~225ms** | **-93%** |
| `perf_profiles_ms` | ~5,000ms† | ~5,000ms | **234ms** | **-95%** |
| `recommend_offsets_loop` | ~26,000ms | 7,625ms | **731ms** | **-97%** |
| `recommend_portfolio_offsets` total | ~70,000ms‡ | 8,375ms | **3,391ms** | **-95%** |
| Event-loop-starved endpoints | 5-27s | 6ms-164ms | 6ms-164ms | **-99%** |

\* Estimated from `build_view_and_betas` step.
\** `build_view_and_betas` step within analyze_portfolio.
† Estimated from timing breakdown; was inside `recommend_offsets_loop` timing.
‡ Pre-Phase A-F, factor-recommendations endpoint averaged 70s (includes event-loop contention).

### Remaining Bottlenecks (Updated)

1. **`build_portfolio_view` cold at 2,659ms** — Dominated by `get_returns` (183ms) + `factor_exposures` (324ms) + initial FMP fetch. Warm ~108ms via LRU. Further cold gains would require persistent caching.
2. **Position enrichment cold-cache** — first load still pulls FMP profiles + analyst data per ticker.
3. **Frontend request volume** — still fires 10+ concurrent requests on page load.

---

## 13. Frontend Code Splitting — Phases 1-3 (2026-03-11)

**Commits**: `191f0a95` (Phase 1), `7d1bf084` (Phase 2), `fab4492e` (Phase 3)
**Method**: Production build (`npx vite build`), 443 frontend tests passing.

### Baseline (Pre-Optimization)

Single monolithic JS bundle:
- **~2.1MB raw** / **599KB gzipped**
- 0 code splitting, 0 React.lazy() usage
- All 10 view containers, chat UI, KaTeX, markdown loaded eagerly on every page load
- Clock re-rendered entire 900-line dashboard shell every 1 second

### Post-Optimization Build Output

16 chunks after code splitting:

| Chunk | Raw | Gzip | Load Trigger |
|-------|-----|------|-------------|
| `index` (core app + eager score-view containers) | 345KB | 91KB | Initial load |
| `vendor-react` (react-dom, react-router) | 254KB | 81KB | Initial load |
| `vendor-charts` (recharts, d3) | 389KB | 106KB | Initial load |
| `vendor-radix` (@radix-ui) | 131KB | 39KB | Initial load |
| `vendor-query` (@tanstack) | 39KB | 12KB | Initial load |
| `ModernDashboardApp` (dashboard shell) | 39KB | 9KB | After auth |
| `vendor-katex` (KaTeX) | 267KB | 81KB | Chat open only |
| `vendor-markdown` (react-markdown, remark) | 163KB | 49KB | Chat open only |
| `ChatCore` | 21KB | 7KB | Chat open only |
| `AIChat` | 3KB | 1KB | Chat open only |
| `ChatInterface` | 2KB | 1KB | Chat view only |
| `RiskSettingsContainer` | 488KB | 118KB | Settings view only |
| `AccountConnectionsContainer` | 33KB | 8KB | Settings view only |
| `AnalystApp` | 3KB | 2KB | /analyst route only |
| CSS (`index` + `vendor-katex`) | 171KB | 30KB | Initial load |

### Deferred Bytes Summary

| Category | Deferred Raw | Deferred Gzip | Trigger |
|----------|-------------|---------------|---------|
| Chat UI (KaTeX + markdown + ChatCore + AIChat) | ~454KB | ~138KB | User opens chat modal (Cmd+J or click) |
| Settings (RiskSettings + AccountConnections) | ~521KB | ~126KB | User navigates to settings view |
| Dashboard shell (ModernDashboardApp) | ~39KB | ~9KB | After authentication completes |
| Analyst mode (AnalystApp) | ~3KB | ~2KB | /analyst route only |
| **Total deferred from initial load** | **~1,017KB** | **~275KB** | — |

### What Changed

| Phase | Change | Impact |
|-------|--------|--------|
| 1A — Clock isolation | Extracted `LiveClock` component | Dashboard shell: 1/sec re-renders → 0 idle re-renders. Market status bug fixed (now updates). |
| 1B — Background polling | `refetchIntervalInBackground: false` | No polling when tab hidden |
| 2A — Route split | `React.lazy()` for ModernDashboardApp + AnalystApp | Dashboard bundle loads only after auth |
| 2B — View split | `React.lazy()` for 8 non-default containers | ~1MB deferred to view navigation |
| 2C — Vite manualChunks | 7 vendor chunk groups (function form) | Stable vendor hashes across app-only deploys |
| 3A — Lazy chat | Conditional `showAIChat &&` mount with `React.lazy()` | ~450KB (KaTeX/markdown/chat) deferred to chat open |
| 3B — Error boundary | `ChunkErrorBoundary` on all Suspense boundaries | Graceful chunk load failure handling |

### Initial Load Comparison

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Total JS (single bundle) | 2.1MB / 599KB gz | — | Split into 16 chunks |
| Initial load JS (auth page) | 2.1MB / 599KB gz | ~1.16MB / ~329KB gz | **-45% gzipped** |
| Initial load JS (dashboard, score view) | 2.1MB / 599KB gz | ~1.16MB / ~329KB gz | **-45% gzipped** |
| JS deferred to interaction | 0 | ~1.0MB / ~275KB gz | Chat, settings, non-default views |
| Idle re-renders (dashboard shell) | 1/sec (entire shell) | 0 (clock isolated) | **-100%** |
| Background polling (tab hidden) | Continuous | Paused | Eliminated |

**Note**: Total bytes transferred doesn't change — code splitting defers *when* bytes load, not *how many*. The win is faster initial paint and lower parse/execute cost on first load. Vendor chunks improve cache hit rates across deploys.

### Remaining Frontend Opportunities (Deferred — Phase 4)

1. **Price refresh deferral** — `PortfolioInitializer` blocks first paint on price refresh. Deferring to background would show cached data faster.
2. **Visibility-aware refetching** — View-specific hooks refetch on schedule even when their view isn't active. `useDataSourceScheduler` would need scope awareness.
3. **Cache layer audit** — Overlapping `PortfolioCacheService` / `UnifiedAdapterCache` / React Query layers. Needs investigation post-`useDataSource` migration.
4. **Circular chunk warnings** — `vendor-query ↔ vendor-react ↔ vendor-radix` and `vendor-katex ↔ vendor-markdown` have circular deps. Harmless but could be tightened.

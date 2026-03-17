# Backend Performance Optimization Plan

**Status:** ACTIVE  
**Updated:** 2026-03-16  
**Primary Goal:** Preserve the now-fast dashboard path and only target the few remaining cold combined-account outliers.  
**Related Docs:** `docs/planning/PERFORMANCE_BASELINE_2026-03-10.md`, `docs/planning/PERFORMANCE_BASELINE_2026-03-15.md`, `docs/planning/PERFORMANCE_BASELINE_2026-03-16.md`, `docs/planning/REVIEW_FINDINGS.md`

## Checkpoint — 2026-03-16

The latest authenticated localhost rerun in `docs/planning/PERFORMANCE_BASELINE_2026-03-16.md` is now the source of truth.

### Current Outcome

- Single-account dashboard total is now **1.35s cold**, **470.50ms warm p50**, and **486.59ms warm p95**.
- Combined `CURRENT_PORTFOLIO` dashboard total is now **2.89s cold**, **394.52ms warm p50**, and **407.35ms warm p95**.
- The original warm-path target is met by a wide margin.
- The earlier cold-path target is also now met locally.
- Bootstrap is no longer a meaningful bottleneck.
- The dashboard no longer needs another broad duplication-removal phase.

### What Landed

- Phase 1 workflow-level timing instrumentation.
- Phase 2 bootstrap pricing deduplication.
- Phase 3 shared workflow setup caching for `analyze`, `risk-score`, and `performance`.
- Phase 4 shared position snapshots across holdings, alerts, income, and intelligence.
- Phase 5 threadpool cleanup for the remaining heavy async routes.
- Phase 6 authenticated remeasurement.
- Later follow-on cold-path work:
  - `market-intelligence` cacheable fetch paths plus parallel downstream loaders.
  - `metric-insights` reuse of shared `risk-score` and `performance` outputs.
  - summary-only dashboard `performance` path.
  - longer-lived warm workflow/result snapshot reuse.
  - `compute_factor_exposures()` reuse of in-memory stock returns plus single-pass factor-vol generation.
  - `PositionService` provider pruning, blocked-provider exclusion, cached fallback reuse, shared cached repricing, and batched FMP quote fetches.

## Current Bottlenecks

The remaining work is narrow and cold-path focused.

### Combined Cold Outliers

From the latest authenticated rerun:

- `GET /api/positions/metric-insights`: **2436.05ms**
- `POST /api/risk-score`: **2393.43ms**
- `GET /api/positions/ai-recommendations`: **2311.95ms**
- `GET /api/positions/holdings`: **2309.35ms**
- `POST /api/analyze`: **2285.45ms**

These are now the main candidates if perf work continues.

### Provider-Side Cold Cost

Direct service-level profiling after the latest repricing batch shows:

- `PositionService.get_all_positions(use_cache=True)` at roughly **1.54s** wall for the current user.
- Cached provider stage timings at roughly:
  - `schwab`: **805.92ms**
  - `ibkr`: **365.64ms**
  - `plaid`: **338.58ms**
  - `csv`: **1.93ms**
- The shared cached repricing pass for `40` rows dropped from roughly **1.31s** to roughly **679ms** after batched FMP profile quote fetches.

This is now a concrete local hotspot, but it is much smaller than the old dashboard-wide duplication problem.

## What Is No Longer A Problem

- Warm repeat latency across the dashboard.
- Bootstrap double-pricing.
- Repeated `analyze` / `risk-score` / `performance` setup work.
- Repeated `get_all_positions()` chains across the main burst.
- Event-loop blocking in the previously known async routes.
- `market-intelligence` and `income` as repeat-path offenders.

## Success Metrics

| Metric | Current Reference | Practical Target |
|---|---:|---:|
| Warm CURRENT_PORTFOLIO dashboard total | 394.52ms p50 / 407.35ms p95 | keep <750ms |
| Warm single-account dashboard total | 470.50ms p50 / 486.59ms p95 | keep <750ms |
| Cold CURRENT_PORTFOLIO dashboard total | 2.89s | keep <4s |
| Warm combined `POST /api/analyze` | 94.04ms p50 / 111.84ms p95 | keep <250ms |
| Warm combined `POST /api/risk-score` | 94.64ms p50 / 133.74ms p95 | keep <250ms |
| Warm combined `POST /api/performance` | 90.65ms p50 / 119.25ms p95 | keep <250ms |
| Warm combined holdings / alerts / income | 51.86ms / 44.91ms / 38.71ms | keep <250ms |
| Warm combined intelligence endpoints | 41.50ms / 43.59ms / 41.36ms | keep <250ms |
| Cold direct `get_all_positions()` | ~1.5s | keep <=1.5s |

## Recommendation

If more backend perf work continues after this checkpoint, it should be tactical:

1. Trim the remaining combined cold outliers, especially `metric-insights` and `ai-recommendations`.
2. Keep watching the provider-side cached repricing path in `PositionService`.
3. Re-measure after each concrete cold-path change instead of reopening another broad dashboard perf phase.

## Execution Posture

The original Phase 1 through Phase 6 plan is effectively complete.

The repo no longer needs:

- a new broad caching layer for the dashboard
- a large API-shape rewrite for dashboard perf alone
- another generic “remove duplicate setup” pass

The next changes, if any, should be justified by a specific measured cold endpoint rather than by the older baseline documents.

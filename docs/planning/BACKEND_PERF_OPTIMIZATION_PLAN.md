# Backend Performance Optimization Plan

**Status:** ACTIVE  
**Updated:** 2026-03-18  
**Primary Goal:** Preserve the fast dashboard path, keep the virtual-bootstrap correctness fix in place, and only target any remaining cold-path costs if they matter in practice.  
**Related Docs:** `docs/planning/PERFORMANCE_BASELINE_2026-03-10.md`, `docs/planning/PERFORMANCE_BASELINE_2026-03-15.md`, `docs/planning/PERFORMANCE_BASELINE_2026-03-16.md`, `docs/planning/PERFORMANCE_BASELINE_2026-03-18.md`, `docs/planning/REVIEW_FINDINGS.md`

## Checkpoint — 2026-03-18

The latest authenticated localhost rerun in `docs/planning/PERFORMANCE_BASELINE_2026-03-18.md` is now the source of truth.

### Current Outcome

- Single-account dashboard total is now **1.40s cold**, **162.72ms warm p50**, and **216.98ms warm p95**.
- Combined `CURRENT_PORTFOLIO` dashboard total is now **1.53s cold**, **257.86ms warm p50**, and **349.10ms warm p95**.
- Combined parallel dashboard wall is now **500.38ms cold** and **178.54ms warm p50**.
- The original warm-path goal is met by a wide margin.
- The earlier cold-path target is also still met locally.
- Virtual portfolio bootstrap is now correctness-aligned with scoped holdings, so the cold bootstrap route intentionally does more real work than the earlier synthetic path.
- A post-baseline UI validation caught one scoped IBKR regression from the later provider-pruning work: `ibkr` was being dropped when the live gateway probe was unavailable even though cached IBKR rows still existed in the DB.
- That regression is now fixed, and an authenticated selector smoke confirms bootstrap and holdings totals match for all six listed portfolios.
- The dashboard still does not need another broad duplication-removal phase.

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
  - short-lived resolved-config caching for repeated `PortfolioData` shaping.
  - cached holdings payload reuse for burst-local dashboard reads.
  - income and market-intelligence loader overlap / faster date parsing in the remaining cold widgets.
  - virtual portfolio bootstrap alignment with the live scoped holdings route, eliminating the old selected-account value mismatch.
  - scoped `PositionService` provider selection now preserves cached IBKR rows for virtual portfolios when the gateway is unavailable, instead of dropping the selected account to zero.

## Current Bottlenecks

The remaining work is narrow and cold-path focused.

### Combined Cold Outliers

From the latest authenticated rerun:

- `GET /api/portfolios/{name}`: **994.91ms**
- `GET /api/income/projection`: **494.93ms**
- `POST /api/analyze`: **396.65ms**
- `GET /api/positions/market-intelligence`: **345.50ms**
- `POST /api/performance`: **336.15ms**
- `GET /api/risk-settings`: **265.67ms**
- `GET /api/allocations/target`: **265.61ms**
- `GET /api/positions/metric-insights`: **248.70ms**

These are now the main candidates if perf work continues. The first item is the intentional live-bootstrap correctness path, not a duplicate-work regression.

### Warm Path State

The warm path remains comfortably closed:

- Warm combined dashboard total is **257.86ms p50 / 349.10ms p95**.
- Warm combined parallel wall is **178.54ms p50 / 282.08ms p95**.
- Warm combined auxiliaries are all around **70ms p50**.
- Warm single-account dashboard total is **162.72ms p50 / 216.98ms p95**.

## What Is No Longer A Problem

- Warm repeat latency across the dashboard.
- Bootstrap double-pricing.
- Repeated `analyze` / `risk-score` / `performance` setup work.
- Repeated `get_all_positions()` chains across the main burst.
- Event-loop blocking in the previously known async routes.
- `market-intelligence` and `income` as repeat-path offenders.
- Selected-account virtual bootstrap drift versus scoped holdings.
- The selected IBKR account collapsing to zero because scoped-provider pruning excluded cached IBKR rows.

## Success Metrics

| Metric | Current Reference | Practical Target |
|---|---:|---:|
| Warm CURRENT_PORTFOLIO dashboard total | 257.86ms p50 / 349.10ms p95 | keep <750ms |
| Warm single-account dashboard total | 162.72ms p50 / 216.98ms p95 | keep <750ms |
| Cold CURRENT_PORTFOLIO dashboard total | 1.53s | keep <4s |
| Warm combined `POST /api/analyze` | 176.41ms p50 / 279.46ms p95 | keep <300ms |
| Warm combined `POST /api/risk-score` | 109.04ms p50 / 207.12ms p95 | keep <250ms |
| Warm combined `POST /api/performance` | 110.80ms p50 / 204.99ms p95 | keep <250ms |
| Warm combined holdings / alerts / income | 41.45ms / 41.79ms / 61.24ms | keep <250ms |
| Warm combined intelligence endpoints | 72.50ms / 71.52ms / 69.82ms | keep <250ms |
| Cold virtual bootstrap | ~1.0s | keep <=1.25s unless correctness requires more |

## Recommendation

If more backend perf work continues after this checkpoint, it should stay tactical:

1. Do not revert the virtual-bootstrap correctness path just to make cold bootstrap appear cheaper.
2. If more perf work is justified, start with cold bootstrap and `income`, not another broad dashboard caching phase.
3. Re-measure after each concrete cold-path change instead of reopening another broad dashboard perf phase.

## Execution Posture

The original Phase 1 through Phase 6 plan is effectively complete.

The repo no longer needs:

- a new broad caching layer for the dashboard
- a large API-shape rewrite for dashboard perf alone
- another generic “remove duplicate setup” pass

The next changes, if any, should be justified by a specific measured cold endpoint or by correctness/UI behavior, not by the older baseline documents.

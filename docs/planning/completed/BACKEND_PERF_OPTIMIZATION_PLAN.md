# Backend Performance Optimization Plan

**Status:** ACTIVE  
**Updated:** 2026-03-19  
**Primary Goal:** Keep the corrected virtual-bootstrap path and the date-aware FMP cache, while narrowing the remaining cold-path owners after the month-end store and proxy-cache follow-on work.  
**Related Docs:** `docs/planning/PERFORMANCE_BASELINE_2026-03-10.md`, `docs/planning/PERFORMANCE_BASELINE_2026-03-15.md`, `docs/planning/PERFORMANCE_BASELINE_2026-03-16.md`, `docs/planning/PERFORMANCE_BASELINE_2026-03-18.md`, `docs/planning/PERFORMANCE_BASELINE_2026-03-18_FMP_CACHE_REFRESH.md`, `docs/planning/PERFORMANCE_BASELINE_2026-03-19.md`, `docs/planning/REVIEW_FINDINGS.md`

## Checkpoint — 2026-03-19

The latest authenticated localhost rerun in `docs/planning/PERFORMANCE_BASELINE_2026-03-19.md` is now the source of truth for the current default overview path.

### Current Outcome

- Single-account default overview total is now **1.57s cold**, **149.07ms warm p50**, and **156.93ms warm p95**.
- Combined `CURRENT_PORTFOLIO` default overview total is now **1.64s cold**, **114.66ms warm p50**, and **129.75ms warm p95**.
- Combined parallel overview wall is now **1.64s cold** and **115.45ms warm p50**.
- The post-cache-change regression remains closed, and the March 19 follow-on work improved both cold scopes plus the combined warm path.
- The key new follow-on work was:
  - month-end analysis stores in the FMP cache
  - cached computed peer-median proxy series
  - reuse of cached live virtual snapshots during `resolve_config`
- Virtual portfolio bootstrap remains correctness-aligned with scoped holdings and should stay that way.
- The earlier scoped IBKR regression remains fixed, and an authenticated selector smoke still confirms bootstrap and holdings totals match for all six listed portfolios.

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
  - FMP time-series coverage tracking now records requested boundaries separately from actual trading rows, fixing repeated empty weekend/holiday boundary refetches.
  - canonical month-end analysis stores for `close_me` and `total_return_me`.
  - cached computed peer-median proxy series keyed by resolved peer baskets.
  - cached live virtual-snapshot reuse in `resolve_config`, including the foreign-cash alias normalization fix needed to make the fast path engage on real portfolios.

## Current Bottlenecks

The remaining work is narrow again, but it is no longer just cold-bootstrap work.

### Current Default Overview Outliers

From the latest authenticated rerun in `docs/planning/PERFORMANCE_BASELINE_2026-03-19.md`:

- `POST /api/performance/realized` with `include_attribution=false`: **1.56s cold** single-account and **1.64s cold** combined
- `GET /api/positions/holdings`: **1.47s cold** single-account and **1.23s cold** combined
- `GET /api/positions/ai-recommendations`: **1.57s cold** single-account and **1.20s cold** combined
- `POST /api/risk-score`: **1.32s cold** on `CURRENT_PORTFOLIO`
- `POST /api/analyze`: **1.32s cold** on `CURRENT_PORTFOLIO`
- Single-account cold bootstrap is now the standout bootstrap issue at **1.19s**

The main tactical implication is narrower again: the warm path is fine, and the remaining work is mostly cold-path.

### Warm Path State

The warm path is back in good shape:

- Warm combined default overview total is **114.66ms p50 / 129.75ms p95**.
- Warm single-account default overview total is **149.07ms p50 / 156.93ms p95**.
- Warm combined parallel wall is **115.45ms p50 / 132.04ms p95**.
- The exploratory sweep still showed `trading-analysis` expensive when its view is enabled, but the default overview no longer has a warm-path performance problem.

## What Is No Longer A Problem

- Bootstrap double-pricing.
- Repeated `analyze` / `risk-score` / `performance` setup work.
- Repeated `get_all_positions()` chains across the main burst.
- Event-loop blocking in the previously known async routes.
- `market-intelligence` and `income` as repeat-path offenders.
- Selected-account virtual bootstrap drift versus scoped holdings.
- The selected IBKR account collapsing to zero because scoped-provider pruning excluded cached IBKR rows.
- Repeated empty weekend/holiday FMP boundary fetches after the date-aware cache rollout.

## What Is Reopened

- Single-account virtual bootstrap is still expensive on the cold path.
- Holdings risk enrichment is still in the outlier class on cold `CURRENT_PORTFOLIO`.
- Cold summary-only realized-performance payload load is still significant.
- Cold AI recommendation generation is still non-trivial.
- Optional `trading-analysis` remains expensive when the performance view is opened.

## Success Metrics

| Metric | Current Reference | Practical Target |
|---|---:|---:|
| Warm CURRENT_PORTFOLIO default overview total | 114.66ms p50 / 129.75ms p95 | keep <500ms |
| Warm single-account default overview total | 149.07ms p50 / 156.93ms p95 | keep <500ms |
| Cold CURRENT_PORTFOLIO default overview total | 1.64s | keep <1.75s |
| Warm combined `POST /api/performance/realized` `include_attribution=false` | 18.76ms p50 / 1.64s cold outlier | keep warm <250ms and reduce cold |
| Warm combined holdings / alerts / income | 8.05ms / 94.44ms / 21.75ms | keep <250ms |
| Warm combined intelligence endpoints | 64.30ms / 67.51ms | keep <250ms |
| Cold virtual bootstrap | 408.68ms combined / 1.19s single | keep <=1.0s unless correctness requires more |

## Recommendation

If more backend perf work continues after this checkpoint, it should stay tactical:

1. Do not revert the virtual-bootstrap correctness path just to make cold bootstrap appear cheaper.
2. Keep the summary-only overview performance path, month-end analysis store, peer-median proxy cache, and cached virtual-snapshot reuse in place.
3. If more work is still justified, then target cold summary-only realized-performance payload load, holdings `enrich_positions_with_risk`, and cold factor-exposure work in `analyze`.
4. Re-measure after each concrete cold-path change instead of reopening another broad dashboard phase.

## Execution Posture

The original Phase 1 through Phase 6 plan is still complete, but the post-cache-change baseline justifies a narrow follow-on pass.

The repo no longer needs:

- a new broad caching layer for the dashboard
- a large API-shape rewrite for dashboard perf alone
- another generic “remove duplicate setup” pass

The next changes, if any, should be justified by the current measured cold-path gaps:

- holdings should not wait so long on risk enrichment
- all-accounts `analyze` / `risk-score` should come back down further
- optional AI insight routes should remain off the hot path unless explicitly enabled

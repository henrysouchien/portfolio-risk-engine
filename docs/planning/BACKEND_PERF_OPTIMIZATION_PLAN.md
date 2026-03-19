# Backend Performance Optimization Plan

**Status:** ACTIVE  
**Updated:** 2026-03-18  
**Primary Goal:** Recover the post-cache-change overview regression without backing out the virtual-bootstrap correctness fix or the date-aware FMP coverage fix.  
**Related Docs:** `docs/planning/PERFORMANCE_BASELINE_2026-03-10.md`, `docs/planning/PERFORMANCE_BASELINE_2026-03-15.md`, `docs/planning/PERFORMANCE_BASELINE_2026-03-16.md`, `docs/planning/PERFORMANCE_BASELINE_2026-03-18.md`, `docs/planning/PERFORMANCE_BASELINE_2026-03-18_FMP_CACHE_REFRESH.md`, `docs/planning/REVIEW_FINDINGS.md`

## Checkpoint — 2026-03-18 (Post FMP Cache Change)

The latest authenticated localhost rerun in `docs/planning/PERFORMANCE_BASELINE_2026-03-18_FMP_CACHE_REFRESH.md` is now the source of truth for the current default overview path.

### Current Outcome

- Single-account default overview total is now **2.35s cold**, **152.94ms warm p50**, and **167.38ms warm p95**.
- Combined `CURRENT_PORTFOLIO` default overview total is now **2.08s cold**, **152.29ms warm p50**, and **155.27ms warm p95**.
- Combined parallel overview wall is now **1.72s cold** and **125.72ms warm p50**.
- The initial post-cache-change regression was real, but the warm-path regression is now closed again.
- The key follow-on fix was making `performance` default to summary-only unless attribution is explicitly requested, plus canonicalizing the summary-only query key so overview loaders share the same cache entry.
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

## Current Bottlenecks

The remaining work is narrow again, but it is no longer just cold-bootstrap work.

### Current Default Overview Outliers

From the latest authenticated rerun in `docs/planning/PERFORMANCE_BASELINE_2026-03-18_FMP_CACHE_REFRESH.md`:

- `POST /api/performance/realized` with `include_attribution=false`: **1.71s cold** on both scopes, but only **50.69ms** single-account warm p50 and **56.13ms** combined warm p50
- `POST /api/risk-score`: **1.36s cold** on `CURRENT_PORTFOLIO`
- `POST /api/analyze`: **1.35s cold** on `CURRENT_PORTFOLIO`
- `GET /api/positions/holdings`: **1.17s cold** on `CURRENT_PORTFOLIO`
- `GET /api/positions/ai-recommendations`: **1.15s cold** on `CURRENT_PORTFOLIO`
- `GET /api/income/projection`: **782.97ms cold** on `CURRENT_PORTFOLIO`
- Single-account cold bootstrap is still elevated at **581.57ms**

The main tactical implication is narrower again: the warm path is fine, and the remaining work is mostly cold-path.

### Warm Path State

The warm path is back in good shape:

- Warm combined default overview total is **152.29ms p50 / 155.27ms p95**.
- Warm single-account default overview total is **152.94ms p50 / 167.38ms p95**.
- Warm combined parallel wall is **125.72ms p50 / 130.04ms p95**.
- The exploratory sweep still showed `metric-insights` and `trading-analysis` expensive when their views are enabled, but the default overview no longer has a warm-path performance problem.

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

- Holdings risk enrichment is back in the outlier class on cold `CURRENT_PORTFOLIO`.
- Optional `metric-insights` remains expensive if AI insights are re-enabled.
- Cold summary-only realized-performance payload load is still significant.
- Cold all-accounts `analyze` / `risk-score` regressed versus the earlier March 18 checkpoint.

## Success Metrics

| Metric | Current Reference | Practical Target |
|---|---:|---:|
| Warm CURRENT_PORTFOLIO default overview total | 152.29ms p50 / 155.27ms p95 | keep <500ms |
| Warm single-account default overview total | 152.94ms p50 / 167.38ms p95 | keep <500ms |
| Cold CURRENT_PORTFOLIO default overview total | 2.08s | recover <1.75s |
| Warm combined `POST /api/performance/realized` `include_attribution=false` | 56.13ms p50 / 67.44ms p95 | keep <250ms |
| Warm combined holdings / alerts / income | 14.04ms / 24.17ms / 67.59ms | keep <250ms |
| Warm combined intelligence endpoints | 66.89ms / 65.64ms | keep <250ms |
| Cold virtual bootstrap | 345.38ms combined / 581.57ms single | keep <=1.0s unless correctness requires more |

## Recommendation

If more backend perf work continues after this checkpoint, it should stay tactical:

1. Do not revert the virtual-bootstrap correctness path just to make cold bootstrap appear cheaper.
2. Keep the summary-only overview performance path and canonical query key in place.
3. If more work is still justified, then target holdings `enrich_positions_with_risk`, cold all-accounts `analyze` / `risk-score`, and finally the optional `metric-insights` path.
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

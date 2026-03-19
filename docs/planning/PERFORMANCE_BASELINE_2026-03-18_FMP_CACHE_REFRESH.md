# Performance Baseline — 2026-03-18 (Post FMP Cache Change)
**Status:** ACTIVE

## Measurement Conditions

- Backend: local FastAPI on `localhost:5001` via `uvicorn`
- Auth: `POST /auth/dev-login` with local dev bypass
- Cache reset for cold runs: authenticated `POST /admin/clear_cache` using the repo `.env` token
- Single-account scope: `_auto_interactive_brokers_u2471778`
- Combined scope: `CURRENT_PORTFOLIO`
- Cold pattern: clear cache, log in, fetch `/api/v2/portfolios`, fetch `GET /api/portfolios/{name}`, then fire the current default overview burst in parallel
- Warm pattern: repeat the same bootstrap + burst flow `3` times without another cache clear
- Current default overview burst:
  - `GET /api/positions/holdings?portfolio_name=...`
  - `GET /api/positions/alerts?portfolio_name=...`
  - `POST /api/analyze`
  - `POST /api/risk-score`
  - `POST /api/performance/realized` with `include_attribution=false`
  - `GET /api/allocations/target?portfolio_name=...`
  - `GET /api/income/projection?portfolio_name=...`
  - `GET /api/positions/market-intelligence`
  - `GET /api/positions/ai-recommendations`
- Important current frontend note: every selector portfolio now advertises `performance_realized`, so overview no longer uses the older summary-only `POST /api/performance` path
- Follow-on fix included in this baseline: `performance` now defaults to summary-only unless a caller explicitly requests attribution, and the `performance` query key treats `includeAttribution=false` as its canonical default so overview loaders dedupe correctly
- Important correctness note: virtual portfolio bootstrap still reuses the live scoped holdings path and remains intentionally correctness-aligned
- Optional routes such as `metric-insights` and `trading-analysis` were measured separately in an exploratory sweep, but they are not part of the default overview totals below

## Key Findings

- Single-account overview total is now **2.35s cold**, **152.94ms warm p50**, and **167.38ms warm p95**.
- Combined `CURRENT_PORTFOLIO` overview total is now **2.08s cold**, **152.29ms warm p50**, and **155.27ms warm p95**.
- Single-account parallel overview wall is now **1.71s cold** and **103.80ms warm p50**.
- Combined parallel overview wall is now **1.72s cold** and **125.72ms warm p50**.
- The temporary warm-path regression was closed by removing the unnecessary full-attribution realized-performance path from overview.
- Warm overview behavior is now back in the same class as the earlier March 18 checkpoint, and combined warm p50 is now materially better than the older `257.86ms` reference.
- The remaining costs are mostly cold-path: summary-only realized-performance payload load, cold `analyze` / `risk-score`, holdings risk enrichment, and cold AI recommendation generation.

## Comparison To Earlier March 18 Baseline

| Scope | Earlier Cold (ms) | Current Cold (ms) | Earlier Warm p50 (ms) | Current Warm p50 (ms) |
|---|---:|---:|---:|---:|
| Single Account | 1,396.65 | 2,349.28 | 162.72 | 152.94 |
| All Accounts | 1,526.14 | 2,079.98 | 257.86 | 152.29 |

## Mid-Checkpoint Regression That Was Fixed

The first rerun immediately after the date-aware cache change exposed a real overview regression before the follow-on resolver fix landed:

| Scope | Temporary Cold (ms) | Fixed Cold (ms) | Temporary Warm p50 (ms) | Fixed Warm p50 (ms) |
|---|---:|---:|---:|---:|
| Single Account | 3,592.32 | 2,349.28 | 1,208.82 | 152.94 |
| All Accounts | 3,750.97 | 2,079.98 | 1,376.76 | 152.29 |

Root cause:

- overview was paying both a summary-only realized-performance request and a full-attribution realized-performance request
- the full-attribution request came from nested `portfolio-summary` resolution and dominated the warm path
- the `performance` query key also treated `includeAttribution=false` as distinct from the bare default key, which reduced sharing across overview loaders

## Burst Totals

| Scope | Cold Total (ms) | Warm Samples (ms) | Warm p50 (ms) | Warm p95 (ms) |
|---|---:|---|---:|---:|
| Single Account | 2,349.28 | 142.34, 152.94, 168.98 | 152.94 | 167.38 |
| All Accounts | 2,079.98 | 155.60, 131.59, 152.29 | 152.29 | 155.27 |

## Parallel Burst Wall

| Scope | Cold Parallel Wall (ms) | Warm Parallel Samples (ms) | Warm Parallel p50 (ms) | Warm Parallel p95 (ms) |
|---|---:|---|---:|---:|
| Single Account | 1,712.71 | 102.99, 103.80, 123.50 | 103.80 | 121.53 |
| All Accounts | 1,718.97 | 125.72, 103.16, 130.52 | 125.72 | 130.04 |

## Bootstrap + Default Overview Endpoints

| Endpoint | Single Cold (ms) | Single Warm p50 | Single Warm p95 | Single Size (KB) | All Cold (ms) | All Warm p50 | All Warm p95 | All Size (KB) | Notes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `GET /api/v2/portfolios` | 55.00 | 24.73 | 28.65 | 2.1 | 15.63 | 22.86 | 23.85 | 2.1 | user-scoped bootstrap list |
| `GET /api/portfolios/{name}` | 581.57 | 20.75 | 22.93 | 3.3 | 345.38 | 5.67 | 5.89 | 5.5 | cold bootstrap is improved again, but still above the earlier single-account reference |
| `POST /api/performance/realized` `include_attribution=false` | 1,707.81 | 50.69 | 57.50 | 21.2 | 1,713.63 | 56.13 | 67.44 | 21.5 | now the only overview performance request |
| `POST /api/analyze` | 651.81 | 102.64 | 120.46 | 59.5 | 1,347.55 | 124.74 | 128.83 | 119.0 | cold all-accounts analyze is still the main analysis-side owner |
| `POST /api/risk-score` | 640.89 | 52.13 | 66.63 | 45.9 | 1,355.12 | 92.12 | 100.63 | 90.0 | still coupled to cold all-accounts analysis load |
| `GET /api/positions/holdings` | 981.51 | 38.29 | 46.95 | 20.7 | 1,168.14 | 14.04 | 22.05 | 35.0 | warm holdings recovered; cold holdings still matter |
| `GET /api/positions/ai-recommendations` | 1,222.28 | 53.24 | 56.08 | 0.1 | 1,152.30 | 65.64 | 91.07 | 0.1 | warm path recovered; cold path still pays recommendation generation |
| `GET /api/income/projection` | 428.61 | 56.81 | 56.90 | 10.6 | 782.97 | 67.59 | 78.76 | 20.4 | remaining cold widget, but warm is cheap again |
| `GET /api/positions/market-intelligence` | 384.45 | 49.48 | 53.14 | 6.0 | 665.60 | 66.89 | 103.69 | 6.0 | warm path recovered; cold remains moderate |
| `GET /api/allocations/target` | 344.50 | 65.93 | 73.32 | 0.1 | 358.38 | 90.52 | 113.27 | 0.1 | still small but not free |
| `GET /api/positions/alerts` | 448.79 | 96.97 | 114.93 | 0.6 | 79.41 | 24.17 | 47.16 | 1.0 | single-account alerts still noisier than combined |

## Recent Workflow Timing Breakdown

From `/api/debug/timing?minutes=1` immediately after the rerun:

- `realized_performance_workflow`: **405.30ms avg**
  - `load_realized_performance_payload`: **404.54ms**
  - `enrich_attribution`: **0.00ms**
- `positions_holdings_workflow`: **1,047.51ms avg**
  - `enrich_positions_with_risk`: **525.91ms**
  - `enrich_positions_with_market_data`: **266.88ms**
- `ai_recommendations_workflow`: **936.07ms avg**
  - `recommend_portfolio_offsets`: **772.09ms**
- `income_projection_workflow`: **868.85ms avg**
  - `load_positions`: **221.92ms**
  - `fetch_dividend_data`: **644.38ms**
- `analyze_portfolio`: **354.44ms avg**
  - `resolve_config`: **198.61ms**
  - `build_view_and_betas`: **148.91ms**

## Exploratory Optional Routes

These were measured in a wider follow-up sweep, not the default overview burst:

- `GET /api/positions/metric-insights` is still expensive when AI insights are enabled:
  - combined cold around **3.76s**
  - combined warm p50 around **2.32s**
- `GET /api/trading/analysis` is also non-trivial when the performance view opens:
  - combined cold around **2.24s**
  - combined warm p50 around **2.27s**

## Interpretation

- The date-aware cache change did surface a real regression, but the warm-path regression was fixed inside the same checkpoint by removing the unnecessary full-attribution overview load.
- The current default overview is now back in the broadly acceptable class on the warm path.
- The remaining work is now mostly cold-path again:
  1. cold summary-only realized-performance payload load
  2. holdings `enrich_positions_with_risk`
  3. cold all-accounts `analyze` / `risk-score`
  4. cold AI recommendation generation

## Recommendation

If perf work continues after this checkpoint, the next pass should be narrow and ordered:

1. Keep the summary-only overview performance path and the canonicalized performance query key in place.
2. If more work is justified, target holdings risk enrichment and cold all-accounts `analyze` / `risk-score` next.
3. After that, decide whether cold AI recommendations or cold income still matter enough to justify more work.
4. Keep the virtual-bootstrap correctness path and the new date-aware FMP coverage semantics in place.

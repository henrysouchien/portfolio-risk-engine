# Performance Baseline — 2026-04-14
**Status:** ACTIVE (supersedes 2026-03-23)

## Measurement Conditions

- Backend: local FastAPI on `localhost:5001` via `uvicorn`
- Frontend: Vite dev server on `localhost:3000`
- Auth: `POST /auth/dev-login` with local dev bypass
- Portfolio: `CURRENT_PORTFOLIO` — 29 positions, ~$279K total value
- Method: curl with `-w "%{time_total}s"`, cold = first request after service restart, warm = second request (cached)
- Instrumented step timing via `workflow_timer` in `/api/analyze`

## Recent Changes Since Last Baseline (2026-03-23)

Major features shipped between baselines:
- Brokerage aggregator (Celery-based provider fanout, replaces ThreadPoolExecutor)
- Editorial pipeline Phase 1 (overview brief generators + orchestrator)
- Gateway per-conversation session locks (F23)
- Overview editorial pipeline (Lane C Phase 1)
- Multiple research workspace bug fixes
- F20 portfolio loading race condition fix

## Backend API Response Times

### Individual Endpoints

| Endpoint | Cold (ms) | Warm (ms) | Notes |
|----------|----------:|----------:|-------|
| `GET /api/v2/portfolios` | 82 | — | Portfolio list |
| `GET /api/portfolios/CURRENT_PORTFOLIO` | 156 | — | Portfolio data load |
| `GET /api/positions/holdings` | 56 | — | Position holdings |
| `POST /api/risk-score` | 44 | 12 | Risk score |
| `POST /api/performance` | 478 | 8 | Realized performance |
| **`POST /api/analyze`** | **2,100** | **83** | **Primary bottleneck cold** |

### /api/analyze Step Breakdown (from `workflow_timer`)

Typical cold call (~2.1s):

| Step | Time (ms) | % of Total | Notes |
|------|----------:|----------:|-------|
| `analyze_portfolio` | 1,500–1,700 | 80–84% | Core risk engine computation (VaR, factor analysis, correlations) |
| `ensure_factor_proxies` | 164–280 | 9–13% | DB lookup + optional GPT peer generation on first-ever call |
| `build_response` | 76–79 | 4% | `to_api_response()` + `get_summary()` serialization |
| `load_portfolio_data` | 39–63 | 2–3% | DB read |
| `load_risk_limits` | 3–4 | ~0% | DB read |

Warm call (~68ms): `build_response` dominates (66ms) — everything else is cache hits.

### Comparison to March 23 Baseline

| Metric | Mar 23 | Apr 14 | Delta |
|--------|-------:|-------:|-------|
| Combined cold parallel wall | 4,075ms | ~2,100ms | -48% (improved) |
| Combined warm p50 | 156ms | ~83ms | -47% (improved) |
| `/api/analyze` cold | ~4,000ms | ~2,100ms | -48% |
| `/api/analyze` warm | — | 83ms | — |

Note: Mar 23 regression was attributed to "shared cold analysis/holdings path." The April 14 numbers suggest the brokerage aggregator (Celery) and cache improvements resolved this.

## Frontend Bundles

47 JS chunks, 3.1 MB total uncompressed:

| Chunk | Raw (KB) | Gzip (KB) | Notes |
|-------|-------:|----------:|-------|
| `index` (entry) | 524 | 139 | Main entry |
| `RiskSettingsContainer` | 386 | 97 | Largest view chunk |
| `vendor-charts` | 380 | 103 | Recharts |
| `vendor-katex` | 261 | 78 | KaTeX — **loaded globally, should be deferred** |
| `vendor-react` | 247 | 78 | React + React DOM |
| `vendor-markdown` | 159 | 47 | Markdown renderer |
| `ModernDashboardApp` | 158 | 43 | Main dashboard shell |
| `vendor-radix` | 132 | 39 | Radix UI components |

Estimated initial load (entry + vendor-react + ModernDashboardApp): ~260KB gzipped.
KaTeX (78KB gz) + markdown (47KB gz) are deferred to chat open (Phase 3 frontend perf).

## Outstanding Optimization Opportunities

### High Impact (identified, not yet implemented)

1. **KaTeX conditional font loading** — ~1.1MB of KaTeX fonts loaded globally regardless of chat state. Font files are separate from the JS chunk. Deferred from Frontend Performance Phase 3.

2. **Legacy `/api/portfolio-analysis` endpoint** — Contains a ~20s `interpret_portfolio_risk()` GPT call. The modern frontend never calls this endpoint (uses `/api/analyze` instead). Dead code risk — should be removed or gated to prevent accidental use.

3. **`RiskSettingsContainer` chunk size** (386KB / 97KB gz) — Largest view-specific chunk. Candidate for further splitting or lazy sub-component loading.

### Medium Impact (deferred from prior plans)

4. **Radix tree-shaking audit** — 27 Radix components bundled (132KB). Unknown how many are actually used. Potential for targeted imports.

5. **Chassis hooks memoization** — 0 `useMemo`/`useCallback` in `@risk/chassis`. Could reduce unnecessary re-renders in deep component trees.

6. **SessionServicesContext refactor** — Context updates re-render entire tree. Split into granular contexts or use Zustand slices.

### Low Impact / Monitoring

7. **`build_response` at 76ms cold** — `to_api_response()` + `get_summary()` serialization. Not urgent but could be lazy-evaluated if the frontend doesn't need the summary field.

8. **`ensure_factor_proxies` at 164–280ms cold** — DB lookup with optional GPT fallback. Already fast for cached proxies. First-ever call for a new ticker can be 4s+ (GPT peer generation).

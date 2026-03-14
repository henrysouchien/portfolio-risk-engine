# Event Loop Blocking Fix — `run_in_threadpool` for Heavy Endpoints

## Context

Uvicorn runs with `--workers 2`. Nine `async def` API endpoints call heavy synchronous functions (portfolio analysis, optimization, Monte Carlo, GPT interpretation) directly, blocking the event loop. While one request runs `analyze_portfolio()` (5-30s), ALL other requests on that worker are starved — including lightweight endpoints like health checks and chat.

Three endpoints already use `run_in_threadpool` correctly (backtest, min-variance, max-return). This plan applies the same proven pattern to the remaining 9.

## Proven Pattern (from `/api/min-variance`)

Extract blocking work into a sync `_run_*_workflow()` helper, call via `await run_in_threadpool()`:

```python
def _run_min_variance_workflow(optimization_request, user, optimization_service):
    pm = PortfolioManager(use_database=True, user_id=user['user_id'])
    portfolio_data = pm.load_portfolio_data(portfolio_name)
    # ... all blocking setup + computation ...
    result = optimization_service.optimize_minimum_variance(...)
    return {'success': True, 'optimization_results': result.to_api_response(), ...}

@app.post("/api/min-variance")
async def min_variance(request, optimization_request, user, api_key, optimization_service):
    try:
        response_payload = await run_in_threadpool(
            _run_min_variance_workflow, optimization_request, user, optimization_service
        )
        log_request(...)
        return response_payload
    except Exception as e:
        # error handling stays in async function
```

Import already exists: `from starlette.concurrency import run_in_threadpool` (line 180).

## File to Modify

`app.py` — add 9 `_run_*_workflow` helpers, refactor 9 async handlers.

## 9 Endpoints

| # | Endpoint | Helper Name | Service Method | Notes |
|---|----------|-------------|----------------|-------|
| 1 | `/api/analyze` | `_run_analyze_workflow` | `portfolio_service.analyze_portfolio()` | Standard pattern |
| 2 | `/api/risk-score` | `_run_risk_score_workflow` | `portfolio_service.analyze_risk_score()` | Standard pattern |
| 3 | `/api/performance` | `_run_performance_workflow` | `portfolio_service.analyze_performance()` | + `enrich_attribution_with_analyst_data()` |
| 4 | `/api/interpret` | `_run_interpret_workflow` | `portfolio_service.interpret_with_portfolio_service()` | Standard pattern |
| 5 | `/api/portfolio-analysis` | `_run_portfolio_analysis_workflow` | `analyze_portfolio()` + `interpret_portfolio_risk()` | Two blocking calls |
| 6 | `/api/what-if` | `_run_what_if_workflow` | `scenario_service.analyze_what_if()` | Input validation stays in async |
| 7 | `/api/stress-test` | `_run_stress_test_workflow` | `scenario_service.analyze_stress_scenario()` | Input validation stays in async |
| 8 | `/api/stress-test/run-all` | `_run_stress_test_run_all_workflow` | `analyze_portfolio()` + `run_all_stress_tests()` | Two blocking calls |
| 9 | `/api/monte-carlo` | `_run_monte_carlo_workflow` | `scenario_service.run_monte_carlo_simulation()` | Range validation stays in async |

## What Goes Where

**Into the `_run_*_workflow` helper (sync):**
- `PortfolioManager` instantiation + `load_portfolio_data()`
- `ensure_factor_proxies()` (where used)
- `RiskLimitsManager` instantiation + `load_risk_limits()` with fallback
- The heavy service method call
- `result.to_api_response()` / `result.get_summary()` / response dict construction
- Inline imports (cached by Python import system after first call)
- Progress `api_logger.info()` calls that log blocking work stages

**Stays in the async handler:**
- `user_tier` extraction, request model field extraction
- `await request.body()` debug logging (endpoints 5 and 6 — must remain async)
- Input validation that raises HTTPException BEFORE blocking work (endpoints 6, 7, 9)
- `await run_in_threadpool(helper, ...)` call
- `log_request()` success logging
- Error handling: preserve each endpoint's existing error handling pattern exactly (see below)

## Error Handling — Preserve Existing Behavior

Each endpoint's error handling must be preserved exactly as-is. Two distinct patterns exist:

**PortfolioService endpoints (1-5):** Catch generic `Exception` → return 500. These do NOT have `PortfolioNotFoundError → 404` mapping today. Do not add it — keep the existing `except Exception` → 500 pattern.

**ScenarioService endpoints (6-9):** Catch `PortfolioNotFoundError` → 404, then generic `Exception` → 500. These already have the 404 mapping.

**HTTPException from inside helpers:** The existing optimization endpoints catch broad `Exception` which swallows `HTTPException` into 500. This is the current behavior and should be preserved. Do NOT add `except HTTPException: raise` guards unless the endpoint already has one. Endpoints 6 (`/api/what-if`), 7 (`/api/stress-test`), 8 (`/api/stress-test/run-all`), 9 (`/api/monte-carlo`) already have `except HTTPException: raise` — keep those.

**Risk-score `None` fallback:** `/api/risk-score` currently passes `None` for `risk_limits_data` when loading fails. Preserve this behavior exactly — do not change the fallback logic.

## Rules

1. **Never pass `request` object** into sync helper. Extract all needed fields in async handler, pass primitives.
2. **Never move `await` calls** into sync helpers.
3. **Input validation with HTTPException** stays in async handler, before `run_in_threadpool`.
4. **Preserve each endpoint's existing error handling** exactly — do not add/remove `PortfolioNotFoundError` checks or `HTTPException` guards.
5. **Place each helper immediately before its endpoint** (matching existing convention for `_run_min_variance_workflow`).

## Thread Safety

- All service objects use `threading.Lock()` via `ServiceCacheMixin` — safe from threadpool threads
- `PortfolioManager` and `RiskLimitsManager` are instantiated fresh per request inside helpers — no shared state
- Starlette threadpool default: 40 threads per worker, 80 total with 2 workers — more than sufficient

## Scope Exclusion

The 9 `/api/direct/*` endpoints are also blocking but lower priority (less traffic, different code pattern). Excluded from this plan — can be a follow-up.

## Verification

1. **TypeScript/lint**: N/A (Python only)
2. **Smoke test each endpoint** via `curl` or API simulator: `python3 tests/utils/show_api_output.py <endpoint>` — confirm identical response shape
3. **Concurrency test**: Fire 2 simultaneous `/api/analyze` requests, confirm second doesn't wait for first (before fix: sequential; after fix: concurrent in threadpool)
4. **Error test**: Request with invalid portfolio name → confirm error response matches pre-change behavior (500 for PortfolioService endpoints, 404 for ScenarioService endpoints)
5. **Frontend**: Load dashboard, trigger analysis, verify all views still render correctly

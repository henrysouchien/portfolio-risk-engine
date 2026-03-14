# Backend Performance Optimization — Phase 2 (Deferred)
**Status:** DONE — All phases implemented. A1+A2 (`8b45e042`), C-F (`d8797e1b`)

**Context:** The high-impact FMP I/O optimizations are complete (Phases 4A-4D, FMP dedup Phases A-G). The remaining items below target event loop contention, DB overhead, and the positions enrichment pipeline. These are lower urgency but carry meaningful breakage risk, so they're parked here for future implementation when needed.

**Prerequisite:** Phase A1 is a hard prerequisite for any frontend deferred-refresh work.

---

## Phase A1: Async Handler Event Loop Fixes (Low Risk)

Wrap ~17 sync-heavy `async def` handlers with `run_in_threadpool`. Prevents event loop starvation when multiple endpoints fire concurrently.

**Files**: `app.py`, `routes/positions.py`

**Heavy endpoints in `app.py`** (`run_in_threadpool` already imported):
| Endpoint | Line | Sync Work |
|----------|------|-----------|
| `POST /api/portfolio/refresh-prices` | 3683 | `portfolio_service.refresh_portfolio_prices()` |
| `GET /api/portfolios/{name}` | 3727-3731 | `PortfolioManager.load_portfolio_data()` + `transform_portfolio_for_display()` |

**Heavy endpoints in `routes/positions.py`** (needs `run_in_threadpool` import):
| Endpoint | Line | Sync Work |
|----------|------|-----------|
| `GET /positions/monitor` | 247 | `PositionService.get_all_positions()` |
| `GET /positions/holdings` | 280 | `_load_enriched_positions(user)` — 5+ chained service calls |
| `GET /positions/export` | 311 | `_load_enriched_positions(user)` + CSV generation |
| `GET /positions/alerts` | 357 | `PositionService.get_all_positions()` + `SecurityTypeService` |
| `GET /positions/market-intelligence` | 423 | `build_market_events()` |
| `GET /positions/ai-recommendations` | 452 | `build_ai_recommendations()` |
| `GET /positions/metric-insights` | 470 | `build_metric_insights()` |

**Lightweight DB-only endpoints in `app.py`** (< 50ms each, lower priority):
| Endpoint | Line |
|----------|------|
| `GET /api/portfolios` | 3587 |
| `DELETE /api/portfolios/{name}` | 3773 |
| `POST /api/portfolios` | 3850 |
| `PUT /api/portfolios/{name}` | 3965 |
| `GET /api/target-allocations` | 2204 |
| `GET /api/scenario-history` | 2348 |
| `GET /api/expected-returns/{name}` | 4206 |
| `GET /api/risk-settings/{name}` | 4643 |

**Note**: A fix for `refresh_prices` exists in `git stash` ("temp: run_in_threadpool fix for refresh_prices").

**Pattern**: Same as existing core analysis endpoints:
```python
# Before:
result = portfolio_service.refresh_portfolio_prices(holdings)
# After:
result = await run_in_threadpool(portfolio_service.refresh_portfolio_prices, holdings)
```

---

## Phase A2: Session Write Throttle (Low Risk)

Throttle session `last_accessed` DB writes to once per 5 minutes.

**File**: `app_platform/auth/stores.py:31-64`
**Impact**: Every authenticated request currently does SELECT + UPDATE + COMMIT. Throttle reduces write traffic ~99%.
**Safety**: Session expiry uses `expires_at`, NOT `last_accessed`. A stale `last_accessed` cannot cause premature session expiry.

**Change**: Add `s.last_accessed` to the SELECT, conditionally UPDATE only when `(now - last_accessed) > 5 minutes`.

**Test update**: `tests/app_platform/test_auth_protocols.py:59-84` — add warm-session test case (1 statement, 0 commits).

---

## Phase C: Cache-Before-Classification (Medium Risk)

Move analysis cache lookup before `SecurityTypeService.get_full_classification()` in `portfolio_service.py`.

**File**: `services/portfolio_service.py:206-274`
**Impact**: Cache hits currently still pay for classification (~50-200ms cold). Cache key does NOT depend on classification output, so reordering is safe.

**Risk**: Must handle old cached results missing `analysis_metadata` (used by `to_api_response()` for asset allocation breakdown). Incomplete metadata → `[]` for asset allocation → user-visible regression.

**Approach**: Check cache first. If hit + metadata complete → return immediately. If hit + metadata incomplete → hold reference, classify, backfill metadata, write-through to L1+L2. Also fixes existing gap where Redis L2 hits never got metadata backfill.

---

## Phase D: Portfolio DB Loading Consolidation (Medium Risk)

Consolidate ~6 separate DB pool checkouts during portfolio load into one connection scope.

**Files**: `inputs/portfolio_manager.py`, `inputs/portfolio_repository.py`
**Impact**: One logical portfolio load fans out into ~6 separate repository calls (lines 287-319), each opening its own pooled DB session.

**Investigation needed before implementation**:
1. Map the exact ~6 repository calls and their ordering dependencies
2. Measure actual overhead of ~6 pooled checkouts vs 1 (may be small if pool is warm)
3. `DatabaseClient` already accepts injected connection via `app_platform/db/client_base.py:23`

**Change**: Add `load_full_portfolio()` method with single `with get_db_session() as conn:` scope.

---

## Phase E: Security Classification Pipeline (High Risk)

Reduce redundant classification work in `get_full_classification()`.

**File**: `services/security_type_service.py`
**Impact**: `get_full_classification()` calls `get_security_types()` then `get_asset_classes()`. `get_asset_classes()` may re-call `get_security_types()` internally for security-type-to-asset-class fallback.

**Risk**: HIGH — `get_security_types()` and `get_asset_classes()` have fundamentally different resolution pipelines (3-tier vs 5-tier), different DB cache semantics, and different FMP API usage. Do NOT merge into one pipeline.

**Scoped changes** (does NOT merge pipelines):
1. Add optional `security_types` param to `get_asset_classes()` to skip internal re-fetch
2. Update `get_full_classification()` to pass its result into `get_asset_classes(security_types=...)`
3. Parallelize FMP profile lookups in `get_asset_classes()` (lines 892-904, currently sequential)

**8 known callers** (all must continue to work):
- `services/portfolio_service.py:212`
- `routes/positions.py:190, 380`
- `services/factor_intelligence_service.py:242, 1149`
- `core/risk_orchestration.py:359`
- `services/trade_execution_service.py:3145`
- `core/realized_performance/engine.py:595`

---

## Phase F: Positions/Holdings Enrichment (Medium-High Risk)

### F1: Batch pricing in `_calculate_market_values()`
**File**: `services/position_service.py:834-889`
**Impact**: Per-row FMP quote fetch for ~50 positions → pre-fetch dict lookup.

Three pricing paths by position type:
- **Cash**: No quote fetch (FX only) — skip in batch
- **Derivatives**: `get_spot_price()` keyed by `(ticker, fmp_ticker)`
- **Equities**: `fetch_fmp_quote_with_currency()` keyed by `fmp_symbol`

**Change**: Scan rows, build two batch-fetch dicts (equity + derivative), then look up in the per-row loop.

### F2: Fix `PortfolioData._cache_key` alignment
**File**: `services/portfolio_service.py:996-1027`
**Impact**: `enrich_positions_with_risk()` mutates `user_id` and `stock_factor_proxies` on `PortfolioData` after `__post_init__` computes `_cache_key`, so the cache key never matches a prior `/api/analyze` result → always cache miss.

**Investigation needed**: Confirm `_cache_key` timing, determine whether to recompute after mutations or construct with final values upfront.

---

## Implementation Order (if resumed)

```
Phase A (A1 + A2) → Phase C → Phase D → Phase E → Phase F
```

**Rationale**: A is zero business logic risk + prerequisite for frontend deferred-refresh. C is straightforward reordering. D needs investigation. E is scoped but high-risk pipeline. F is largest scope.

## Verification

| Phase | Test Method |
|-------|------------|
| A1 | `curl` concurrent requests — no timeouts; existing tests pass |
| A2 | Auth tests (fresh + warm paths); rapid `curl` shows throttled UPDATEs |
| C | Timing log on warm path — skips classification; response JSON identical |
| D | Pool checkout count drops ~6 → 1; portfolio load tests pass |
| E | Classification output identical before/after; cold-cache latency drops |
| F | Holdings response identical; FMP quote call count drops |

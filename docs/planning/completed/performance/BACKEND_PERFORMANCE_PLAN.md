# Backend Performance Optimization Plan
**Status:** COMPLETE — FMP I/O optimizations done (Phases 4A-4D + FMP dedup A-G). Remaining items (event loop fixes, cache reordering, DB consolidation, classification pipeline, batch pricing) extracted to `BACKEND_PERFORMANCE_PHASE2_PLAN.md` for future implementation.

## Context

Performance audit (`docs/planning/PERFORMANCE_AUDIT_2026-03-09.md`) identified 13 findings. Phase 4 backend parallelization items (4A/4B/4C/4D from `PERFORMANCE_PHASE4_PLAN.md`) are already committed. Frontend Phase 1 (logging batch) and Phase 2 (request reduction) are done. A combined frontend+backend Phase 1 attempt (commit `e82db300`) was reverted due to an event loop blocking regression.

This plan covers **backend-only** changes in small, independently verifiable phases. Each phase can be tested with curl/pytest — no browser needed until the final integration test. Frontend changes (deferred price refresh, lazy chat, code splitting) are deferred to a separate plan.

## Pre-existing Bug: Async Handlers Blocking the Event Loop

Multiple `async def` endpoints execute heavy synchronous work without `run_in_threadpool`, blocking the single-worker uvicorn event loop. The core analysis endpoints (`/api/analyze`, `/api/risk-score`, `/api/performance`, etc.) correctly use `await run_in_threadpool(...)`, but several others do not.

**Heavy endpoints** (block for seconds — pricing, analysis, enrichment):

**`app.py`** (already imports `run_in_threadpool` at line 184):
| Endpoint | Line | Sync Work |
|----------|------|-----------|
| `POST /api/portfolio/refresh-prices` | 3683 | `portfolio_service.refresh_portfolio_prices()` (FMP pricing loop) |
| `GET /api/portfolios/{name}` | 3727-3731 | `PortfolioManager.load_portfolio_data()` + `transform_portfolio_for_display()` (DB + pricing) |

**`routes/positions.py`** (does NOT import `run_in_threadpool` — needs adding):
| Endpoint | Line | Sync Work |
|----------|------|-----------|
| `GET /positions/monitor` | 247 | `PositionService.get_all_positions()` |
| `GET /positions/holdings` | 280 | `_load_enriched_positions(user)` — 5+ chained service calls |
| `GET /positions/export` | 311 | `_load_enriched_positions(user)` + CSV generation |
| `GET /positions/alerts` | 357 | `PositionService.get_all_positions()` + `SecurityTypeService` |
| `GET /positions/market-intelligence` | 423 | `build_market_events()` (external service) |
| `GET /positions/ai-recommendations` | 452 | `build_ai_recommendations()` (factor intelligence) |
| `GET /positions/metric-insights` | 470 | `build_metric_insights()` (MCP tools) |

**Lightweight DB-only endpoints** (complete in <50ms — lower priority but still blocking):

**`app.py`**:
| Endpoint | Line | Sync Work |
|----------|------|-----------|
| `GET /api/portfolios` | 3587 | `PortfolioManager.get_portfolio_names()` (single DB query) |
| `DELETE /api/portfolios/{name}` | 3773 | `pm.delete_portfolio()` (DB write) |
| `POST /api/portfolios` | 3850 | `pm.get_portfolio_names()` + portfolio creation (DB read+write) |
| `PUT /api/portfolios/{name}` | 3965 | Portfolio update (DB read+write) |
| `GET /api/target-allocations` | 2204 | `PortfolioRepository().get_target_allocations()` (DB read) |
| `GET /api/scenario-history` | 2348 | `PortfolioRepository().get_scenario_history()` (DB read) |
| `GET /api/expected-returns/{name}` | 4206 | `pm.get_expected_returns()` (DB read) |
| `GET /api/risk-settings/{name}` | 4643 | `RiskLimitsManager.load_risk_limits()` (DB read) |

A fix for `refresh_prices` exists in `git stash` ("temp: run_in_threadpool fix for refresh_prices").

## Current State

### Already Done
| Item | Commit | Status |
|------|--------|--------|
| Phase 4A: `compute_max_betas()` `worst_losses` kwarg | Pre-revert | In main |
| Phase 4B: `get_worst_monthly_factor_losses()` ThreadPoolExecutor | Pre-revert | In main |
| Phase 4C: Concurrent `build_portfolio_view()` + `calc_max_factor_betas()` | Pre-revert | In main |
| Phase 4D: Makefile dev/serve split + app.py __main__ workers | Pre-revert | In main |
| Frontend Phase 1: Logger batching (55 to 11 requests) | `4d8ca07e` | In main |
| Frontend Phase 2: Request reduction (45 to 26 requests) | `5429d81e` | In main |

### Remaining Targets (This Plan)
| Phase | Target | File(s) | Audit Finding |
|-------|--------|---------|---------------|
| A1 | Async handler event loop fixes | `app.py`, `routes/positions.py` | Pre-existing bug |
| A2 | Session write throttle | `app_platform/auth/stores.py` | #8 |
| C | Cache-before-classification | `services/portfolio_service.py` | #5 |
| D | Portfolio DB loading consolidation | `inputs/portfolio_manager.py`, `inputs/portfolio_repository.py` | #6 |
| E | Security classification pipeline | `services/security_type_service.py` | #7 |
| F | Positions/holdings enrichment | `services/position_service.py`, `services/portfolio_service.py`, `routes/positions.py` | #9 |

## Phase A: Event Loop & Session Fixes (Low Risk)

Two independent fixes that don't touch business logic.

### A1. Wrap sync-heavy async handlers with `run_in_threadpool`
**Files**: `app.py`, `routes/positions.py`
**Impact**: Prevents event loop starvation when multiple endpoints fire concurrently. Prerequisite for any future frontend deferred-refresh work.
**Risk**: Very low — identical pattern used by every core analysis endpoint.

**Scope**: Two tiers. **Tier 1** (this phase) covers heavy endpoints that block for seconds (pricing, analysis, enrichment) — these are the ones that cause user-visible timeouts. **Tier 2** covers lightweight DB-only endpoints that complete in <50ms — these also block the event loop but the practical impact is much lower. Both tiers are implemented together since the change is mechanical.

**Tier 1 — Heavy endpoints in `app.py`** (`run_in_threadpool` already imported at line 184):

1. `refresh_prices` (line 3683):
```python
# Before:
result = portfolio_service.refresh_portfolio_prices(holdings)
# After:
result = await run_in_threadpool(portfolio_service.refresh_portfolio_prices, holdings)
```

2. `enrich_holdings_with_metadata` (line 3687) — does I/O via `get_cash_positions()` which loads from DB or YAML:
```python
# Before:
result['holdings'] = enrich_holdings_with_metadata(result['holdings'])
# After:
result['holdings'] = await run_in_threadpool(enrich_holdings_with_metadata, result['holdings'])
```

3. `get_portfolio` (lines 3727-3731) — `portfolio_service` is already a resolved FastAPI dependency object, safe to capture in closure:
```python
# Before:
pm = PortfolioManager(use_database=True, user_id=user['user_id'])
portfolio_data = pm.load_portfolio_data(portfolio_name)
transformed_data = transform_portfolio_for_display(portfolio_data, portfolio_service)
# After:
def _load_and_transform():
    pm = PortfolioManager(use_database=True, user_id=user['user_id'])
    pd = pm.load_portfolio_data(portfolio_name)
    return transform_portfolio_for_display(pd, portfolio_service)
transformed_data = await run_in_threadpool(_load_and_transform)
```

**Tier 1 — Heavy endpoints in `routes/positions.py`**:

Add import at top (line 19 area):
```python
from starlette.concurrency import run_in_threadpool
```

Wrap the sync-heavy body of each handler. `_load_enriched_positions()` takes a single `user: dict` argument (line 155) and internally instantiates `PositionService` and `PortfolioService`. Example for `/holdings`:
```python
# Before (line ~283):
result, payload = _load_enriched_positions(user)
# After:
result, payload = await run_in_threadpool(_load_enriched_positions, user)
```

Same pattern for `/monitor`, `/export`, `/alerts`, `/market-intelligence`, `/ai-recommendations`, `/metric-insights` — wrap each sync call in `run_in_threadpool`.

**Tier 2 — Lightweight DB-only endpoints in `app.py`**:

Same `run_in_threadpool` wrapping for all endpoints listed in the "Lightweight DB-only" table above: `list_portfolios` (3587), `delete_portfolio` (3773), `create_portfolio` (3850), `update_portfolio` (3965), `get_target_allocations` (2204), `get_scenario_history` (2348), `get_expected_returns` (4206), `get_risk_settings` (4643). Example:
```python
# Before (list_portfolios, line 3587):
pm = PortfolioManager(use_database=True, user_id=user['user_id'])
portfolios = pm.get_portfolio_names()
# After:
def _list():
    pm = PortfolioManager(use_database=True, user_id=user['user_id'])
    return pm.get_portfolio_names()
portfolios = await run_in_threadpool(_list)
```

**Verification**:
1. `make dev` — server starts
2. `curl` each modified endpoint — returns 200
3. Fire concurrent requests (refresh-prices + analyze) — both complete without timeout
4. Existing tests pass

### A2. Throttle session `last_accessed` writes
**File**: `app_platform/auth/stores.py:31-64`
**Impact**: Every authenticated request currently does SELECT + UPDATE + COMMIT. This turns read traffic into write traffic. Throttle to once per 5 minutes.
**Risk**: Very low — session expiry uses `expires_at` (line 41), NOT `last_accessed`. A stale `last_accessed` cannot cause premature session expiry.

**Current SELECT (lines 36-43)** does not fetch `last_accessed`:
```sql
SELECT s.session_id, s.user_id, s.expires_at,
       u.email, u.name, u.tier, u.google_user_id
FROM user_sessions s JOIN users u ON s.user_id = u.id
WHERE s.session_id = %s AND s.expires_at > %s
```

**Change**: Add `s.last_accessed` to the SELECT, then conditionally UPDATE:
```python
from datetime import timedelta

_TOUCH_INTERVAL = timedelta(minutes=5)

def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
    with self._get_session_fn() as conn:
        cursor = conn.cursor()
        now = _utcnow()
        cursor.execute(
            """
            SELECT s.session_id, s.user_id, s.expires_at, s.last_accessed,
                   u.email, u.name, u.tier, u.google_user_id
            FROM user_sessions s
            JOIN users u ON s.user_id = u.id
            WHERE s.session_id = %s AND s.expires_at > %s
            """,
            (session_id, now),
        )
        result = cursor.fetchone()
        if not result:
            return None

        # Only touch if stale (reduces write traffic ~99%)
        last_accessed = result.get("last_accessed")
        if last_accessed is None or (now - last_accessed) > _TOUCH_INTERVAL:
            cursor.execute(
                "UPDATE user_sessions SET last_accessed = %s WHERE session_id = %s",
                (now, session_id),
            )
            conn.commit()

        return {
            "user_id": result["user_id"],
            "google_user_id": result["google_user_id"],
            "email": result["email"],
            "name": result["name"],
            "tier": result["tier"],
        }
```

**Test update required**: `tests/app_platform/test_auth_protocols.py:59-84` expects exactly 2 SQL statements (`len(cursor.executed) == 2`) and 1 commit (`conn.commit_count == 1`) per `get_session()`. Update to:
- Existing test: mock `last_accessed` as `None` (or omit) in `fetchone_results` — still triggers UPDATE → 2 statements, 1 commit (test passes as-is with minor mock update)
- New test: mock `last_accessed` as `now - timedelta(seconds=30)` (recent) — skips UPDATE → 1 statement, 0 commits

**Verification**:
1. Updated auth tests pass (both fresh and warm paths)
2. `curl` an authenticated endpoint 10x rapidly — DB shows at most 1 UPDATE (not 10)
3. Live test: dashboard loads normally, session stays valid

## Phase C: Cache-Before-Classification (Medium Risk)

### C1. Move analysis cache lookup before classification
**File**: `services/portfolio_service.py:206-274`
**Impact**: Cache hits currently still pay for `SecurityTypeService.get_full_classification()` (~50-200ms cold, ~5ms warm). Moving the cache check first eliminates this overhead on repeat requests.
**Risk**: Medium — must handle old cached results that lack `analysis_metadata` without breaking user-visible output.

**Cache key invariant**: The cache key formula is `portfolio_analysis_{portfolio_data.get_cache_key()}_{risk_cache_key}_{normalized_period}`. `get_cache_key()` hashes portfolio input, dates, and ticker maps (`data_objects.py:981`). Classification output is NOT in the key — reordering is safe.

**Current flow** (lines 206-274):
```
1. Extract tickers                           # line 207
2. get_full_classification(tickers)          # line 212 — EXPENSIVE
3. Build asset_classes, security_types maps  # lines 213-229
4. Build cache_key                           # line 236
5. Check L1 cache                           # line 246
   → backfill asset_classes/security_types/target_allocation if missing (lines 251-262)
6. Check L2 cache (Redis)                   # line 270
   → no backfill (existing gap)
7. Run analysis if miss
```

**Critical constraints**:
- `to_api_response()` in `core/result_objects/risk.py:846` calls `_build_asset_allocation_breakdown()` which reads `analysis_metadata['asset_classes']`. If metadata is absent, returns `[]` — a **user-visible regression**.
- `analysis_metadata` is `Optional[Dict[str, Any]]` (risk.py:166) — can be `None`.
- `target_allocation` in `analysis_metadata` is used for drift calculation (risk.py:890-892). Must also be present.
- Redis L2 hits currently bypass the metadata backfill — an existing gap this change should fix.

**New flow**:
```
1. Build cache_key (no classification dependency)
2. Check L1 cache
   → if hit AND metadata complete (asset_classes + security_types + target_allocation) → return
   → if hit BUT incomplete → hold reference, fall through to classify + backfill
3. Check L2 cache (Redis) — same logic
4. Extract tickers
5. get_full_classification(tickers)
6. If we have a cached result needing backfill → inject metadata, write-through to L1+L2, return
7. Otherwise → run full analysis
```

**Change**:
```python
# Helper for metadata completeness
def _metadata_complete(result) -> bool:
    """Check if cached result has all required metadata fields."""
    metadata = getattr(result, 'analysis_metadata', None)
    if not metadata or not isinstance(metadata, dict):
        return False
    return (
        'asset_classes' in metadata
        and 'security_types' in metadata
        and 'target_allocation' in metadata
    )

# 1. Build cache key FIRST
normalized_period = (performance_period or "1M").upper()
if normalized_period not in {"1M", "3M", "6M", "1Y", "YTD"}:
    normalized_period = "1M"
if risk_limits_data and not risk_limits_data.is_empty():
    risk_cache_key = risk_limits_data.get_cache_key()
    cache_key = f"portfolio_analysis_{portfolio_data.get_cache_key()}_{risk_cache_key}_{normalized_period}"
else:
    cache_key = f"portfolio_analysis_{portfolio_data.get_cache_key()}_{normalized_period}"

# 2. Check L1 cache — fast path for complete entries
cached_result = None
with self._lock:
    if self.cache_results and cache_key in self._cache:
        candidate = self._cache[cache_key]
        if hasattr(candidate, 'to_api_response'):
            if _metadata_complete(candidate):
                return candidate
            else:
                cached_result = candidate  # will backfill after classification
        else:
            del self._cache[cache_key]

# 3. Check L2 (Redis) — same pattern
if cached_result is None and self._redis and self.cache_results:
    l2_result = self._redis.get(cache_key)
    if l2_result is not None and hasattr(l2_result, 'to_api_response'):
        if _metadata_complete(l2_result):
            with self._lock:
                self._cache[cache_key] = l2_result  # promote to L1
            return l2_result
        else:
            cached_result = l2_result

# 4. Cache miss or metadata-incomplete — classify now
tickers = portfolio_data.get_tickers()
full_classification = SecurityTypeService.get_full_classification(tickers, portfolio_data)
asset_classes = {t: labels.get("asset_class") for t, labels in full_classification.items()}
# ... futures override, security_types extraction (existing lines 217-229) ...
security_types = {t: labels.get("security_type") for t, labels in full_classification.items()}

# 5. If we had a cached result needing backfill, inject and return
if cached_result is not None:
    if not hasattr(cached_result, 'analysis_metadata') or cached_result.analysis_metadata is None:
        cached_result.analysis_metadata = {}
    cached_result.analysis_metadata['asset_classes'] = asset_classes
    cached_result.analysis_metadata['security_types'] = security_types
    cached_result.analysis_metadata['target_allocation'] = portfolio_data.target_allocation
    # Write-through to L1 and L2
    with self._lock:
        self._cache[cache_key] = cached_result
    if self._redis:
        self._redis.set(cache_key, cached_result)
    return cached_result

# 6. Full cache miss — run analysis (existing code)
```

**Why this is safe**: Complete cached results (the common case after first run with this code) return immediately without classification. Only old entries missing metadata fall through to classify — same behavior as today, just reordered. Once old entries rotate out, the backfill path becomes dead code. This also fixes the existing Redis L2 gap where metadata was never backfilled.

**Verification**:
1. Existing tests: `python -m pytest tests/core/test_portfolio_risk.py -x -q`
2. Cold cache: `POST /api/analyze` — classification + analysis runs, response includes `asset_allocation` and drift
3. Warm cache: `POST /api/analyze` — skips classification (add timing log), response still includes `asset_allocation` and drift
4. Diff response JSON between cold and warm — must be identical (especially `asset_allocation` and `analysis_metadata`)
5. Restart server (clear L1), repeat — L2 hit should also return complete response

## Phase D: Portfolio DB Loading Consolidation (Medium Risk)

### D1. Single-connection portfolio load
**Files**: `inputs/portfolio_manager.py`, `inputs/portfolio_repository.py`
**Impact**: One logical portfolio load fans out into ~6 separate repository calls (`portfolio_manager.py:287-319`), each opening its own pooled DB session via `portfolio_repository.py:43`. This means ~6 pool checkouts and ~9 SQL statements across `database_client.py` methods (lines 581, 706, 3025, 3240).
**Risk**: Medium — changes data access structure but not behavior. The current pool is managed by `app_platform/db/session.py:48`, so these are pooled checkouts (not raw connections), which partially mitigates the overhead.

**Investigation needed before implementation**:
1. Map the exact ~6 repository calls in `portfolio_manager.py:287-319` (positions, metadata, factor proxies, expected returns, target allocations, etc.)
2. Confirm ordering dependencies — expected returns derive tickers from `positions` (`database_client.py:734`), and cash mapping has DB-then-YAML fallback (`portfolio_manager.py:597`)
3. Measure actual overhead of ~6 pooled checkouts vs 1 (if pool is warm and contention is low, the win may be small)
4. `DatabaseClient` already accepts an injected connection (`app_platform/db/client_base.py:23`) — can reuse this

**Change**: Add a `load_full_portfolio(portfolio_name)` method to `PortfolioRepository` that runs all sub-queries within one `with get_db_session() as conn:` block, passing the connection to `DatabaseClient`. Respect ordering: load positions first (needed by expected returns), then remaining queries. Update `PortfolioManager` to use it.

**Verification**:
1. Existing portfolio load tests pass
2. Pool checkout count during load drops from ~6 to 1 (instrument with pool event logging or counter)
3. `POST /api/analyze` response is identical before/after
4. Verify cash-mapping DB-then-YAML fallback still works

## Phase E: Security Classification Pipeline (High Risk)

### E1. Reduce redundant classification work
**File**: `services/security_type_service.py`
**Impact**: `get_full_classification()` (line 1008) calls `get_security_types()` then `get_asset_classes()`. `get_asset_classes()` may re-call `get_security_types()` internally (line 912) for tickers it needs to map via security-type-to-asset-class fallback. This results in redundant DB+FMP work.
**Risk**: **High** — `get_security_types()` and `get_asset_classes()` have fundamentally different resolution pipelines:

- `get_security_types()` (line 270): 3-tier (provider types → DB cache → FMP fetch). Values can be `None`.
- `get_asset_classes()` (line 840): 5-tier (cash proxy → CUR/futures → DB cache → FMP industry → security-type mapping → AI fallback → "unknown"). Guarantees all tickers classified (no `None`).

These have different precedence rules, different DB cache semantics (security_type upserts per-ticker at line 515; asset_class batches at line 958 and writes `security_type='unknown'` in that batch), and different FMP API usage. **Do NOT merge into one pipeline.**

**Known callers of classification methods** (all must continue to work):
- `services/portfolio_service.py:212` — `get_full_classification()` in analysis path
- `routes/positions.py:190` — via `_load_enriched_positions()`
- `routes/positions.py:380` — alerts route
- `services/factor_intelligence_service.py:242` — factor recommendations
- `services/factor_intelligence_service.py:1149` — additional factor intelligence
- `core/risk_orchestration.py:359` — risk orchestration
- `services/trade_execution_service.py:3145` — trade execution
- `core/realized_performance/engine.py:595` — realized performance

**Changes** (scoped — does NOT merge the two pipelines):
1. Add an optional `security_types: Dict[str, str] | None = None` parameter to `get_asset_classes()`. When provided, skip the internal re-call of `get_security_types()` at line 912. The Tier 3-before-Tier 4 ordering (FMP industry before security-type mapping) must be preserved — the `security_types` parameter only replaces the Tier 4 internal fetch, not the earlier tiers.
2. Update `get_full_classification()` to pass the result of its `get_security_types()` call into `get_asset_classes(security_types=...)`.
3. Use bounded `ThreadPoolExecutor` for FMP profile lookups in `get_asset_classes()` (lines 892-904, currently sequential loop over missing tickers).
4. Leave DB upsert patterns as-is — merging would risk the `security_type='unknown'` write hazard at line 960.

All external callers are unaffected — they don't pass `security_types`, so the internal fetch runs as before.

**Verification**:
1. Capture classification output for a test portfolio before/after — must be identical
2. Cold-cache latency should drop (measure with timing logs)
3. Existing tests pass
4. Verify all callers listed above still get correct classifications

## Phase F: Positions/Holdings Enrichment (Medium-High Risk)

### F1. Batch pricing in `_calculate_market_values()`
**File**: `services/position_service.py:834-889`
**Impact**: `_calculate_market_values()` iterates per-row with `df.iterrows()`, calling `fetch_fmp_quote_with_currency(fmp_symbol)` for equities or `get_spot_price(ticker, fmp_ticker=...)` for derivatives. For a 50-position portfolio, this is up to 50 separate FMP API/cache lookups.
**Risk**: Medium — different position types use different pricing paths:

- **Cash** (line 840-856): No quote fetch. FX conversion via `fx_provider.get_spot_fx_rate(currency)`. Skip entirely in batch.
- **Derivatives** (line 859-864): `get_spot_price(ticker, instrument_type="futures", fmp_ticker=row.get("fmp_ticker"))`. Key is `(ticker, fmp_ticker)`.
- **Equities** (line 866): `fetch_fmp_quote_with_currency(fmp_symbol)`. Key is `fmp_symbol` (which is `row.get("fmp_ticker") or ticker`).

**Change**: Before the per-row loop, scan all rows and build two separate batch-fetch dicts by position type:

1. **Equity batch**: Collect unique `fmp_symbol` values (where `fmp_symbol = row.get("fmp_ticker") or ticker`). Pre-fetch via `fetch_fmp_quote_with_currency(fmp_symbol)` for each unique key. Store results in `equity_quotes: Dict[str, Tuple[float, str]]` keyed by `fmp_symbol`.
2. **Derivative batch**: Collect unique `(ticker, fmp_ticker)` pairs. Pre-fetch via `get_spot_price(ticker, instrument_type="futures", fmp_ticker=fmp_ticker)` for each unique pair. Store results in `derivative_quotes: Dict[Tuple[str, Optional[str]], Tuple[float, str]]`.
3. **Cash**: Skip entirely — no quote fetch needed (FX-only conversion).

In the per-row loop, look up from the appropriate pre-fetched dict instead of calling the pricing function per row. FX normalization (`normalize_fmp_price` + `fx_provider.get_spot_fx_rate`) still runs per-row since it depends on per-position currency.

### F2. Reduce redundant risk analysis in holdings flow
**File**: `services/portfolio_service.py:996-1027`
**Impact**: `enrich_positions_with_risk()` converts `PositionResult` → `PortfolioData` (line 1009), mutates `user_id` (line 1010) and `stock_factor_proxies` (line 1015), then calls `self.analyze_portfolio(portfolio_data)` (line 1027). This runs the full analysis pipeline including `build_portfolio_view()`, covariance, factor exposures, etc.
**Risk**: Medium-high — the mutations to `PortfolioData` after `__post_init__` mean the `_cache_key` (computed in `data_objects.py:832` during `__post_init__`) does NOT reflect the mutated `user_id` and `stock_factor_proxies`. This strongly suggests the analysis cache is always missed for the holdings path, even if a prior `/api/analyze` call computed the same result. This is the single most expensive step in the holdings pipeline.

**Investigation needed**:
1. Confirm that `PortfolioData._cache_key` is computed in `__post_init__` and does not update when fields are mutated afterward
2. If confirmed, determine whether `user_id` and `stock_factor_proxies` should be included in the cache key (they affect the analysis result)
3. Determine the correct fix: either recompute `_cache_key` after mutations, or construct `PortfolioData` with all fields upfront

**Changes** (after investigation):
- If cache key can be aligned: ensure `PortfolioData` is constructed with final field values before `_cache_key` is computed, so that a prior `/api/analyze` call warms the cache for `/positions/holdings`
- If alignment is not safe: add a separate holdings-specific analysis cache that keys on the mutated `PortfolioData`

### F3. Positions routes `run_in_threadpool` wrapping
**Note**: Covered by Phase A1 — listed here for completeness. The positions enrichment pipeline (`_load_enriched_positions`) is the heaviest sync path in these routes.

**Verification**:
1. Holdings/positions response identical before/after
2. Latency drops proportional to portfolio size (especially F1)
3. External API call count drops (FMP quotes)
4. Asset classes, risk scores, and betas still populate correctly in the response
5. Test with both small (5 positions) and large (50+ positions) portfolios

## Implementation Order

```
Phase A (A1 + A2) → Phase C → Phase D → Phase E → Phase F
```

**Rationale**:
- **A first**: Zero business logic risk, fixes pre-existing bugs, and reduces write load. A1 is a prerequisite for future frontend deferred-refresh work. A1 also covers positions routes (F3).
- **C second**: Straightforward reordering with a clear cache-key invariant. Measurable on every warm-cache request. Fixes the existing Redis L2 metadata gap.
- **D third**: Requires investigation but has a clear shape (consolidate DB calls into one pool checkout).
- **E fourth**: Scoped down to passing security_types to avoid re-fetch + parallelizing FMP lookups. Does NOT merge the two pipelines.
- **F last**: Largest scope, most files touched, requires understanding the full enrichment pipeline and cache alignment. F2 requires careful investigation of `PortfolioData._cache_key` behavior.

## Verification Strategy

Each phase is independently verifiable:

| Phase | Test Method |
|-------|------------|
| A1 | `curl` concurrent requests — no timeouts; existing endpoint tests pass |
| A2 | Updated auth tests (fresh + warm paths); rapid `curl` shows throttled UPDATEs |
| C | Timing log on warm-cache path — skips classification; response JSON identical including `asset_allocation` and drift |
| D | Pool checkout count drops from ~6 to 1; portfolio load tests pass |
| E | Classification output identical before/after; cold-cache latency drops |
| F | Holdings response identical; FMP quote call count drops; cache hit rate improves (F2) |

**Existing test suites** to run after each phase:
```bash
python -m pytest tests/core/test_portfolio_risk.py tests/core/test_efficient_frontier.py -x -q
python -m pytest tests/app_platform/ -x -q
python -m pytest tests/ -x -q --timeout=60  # full suite
```

## Files to Modify

| Phase | File | Changes |
|-------|------|---------|
| A1 | `app.py` | Tier 1: Wrap `refresh_prices`, `get_portfolio` in `run_in_threadpool`. Tier 2: Wrap `list_portfolios`, `delete_portfolio`, `create_portfolio`, `update_portfolio`, `get_target_allocations`, `get_scenario_history`, `get_expected_returns`, `get_risk_settings` |
| A1 | `routes/positions.py` | Add `run_in_threadpool` import; wrap sync calls for all 7 async handlers (`monitor`, `holdings`, `export`, `alerts`, `market-intelligence`, `ai-recommendations`, `metric-insights`) |
| A2 | `app_platform/auth/stores.py` | Add `s.last_accessed` to SELECT, conditional UPDATE with 5-min threshold |
| A2 | `tests/app_platform/test_auth_protocols.py` | Update existing test mock to include `last_accessed`; add test case for warm session path (1 statement, 0 commits) |
| C | `services/portfolio_service.py` | Reorder cache check before classification; handle incomplete metadata backfill with L1+L2 write-through; add `_metadata_complete()` helper |
| D | `inputs/portfolio_manager.py`, `inputs/portfolio_repository.py` | Add `load_full_portfolio()`, single connection scope |
| E | `services/security_type_service.py` | Add optional `security_types` param to `get_asset_classes()`; update `get_full_classification()` to pass it; parallelize FMP profile lookups |
| F | `services/position_service.py` | Batch quote fetch before per-row loop in `_calculate_market_values()` |
| F | `services/portfolio_service.py` | Investigate and fix `PortfolioData._cache_key` alignment for `enrich_positions_with_risk()` |

## Relationship to Frontend Plan

Phase A1 (`run_in_threadpool` fix) is a **hard prerequisite** for the frontend deferred-refresh pattern (rendering children before price refresh completes). Without A1, concurrent frontend requests will block the event loop. All other backend phases are independent of frontend changes.

Frontend performance work (code splitting, lazy chat, deferred prefetch, clock isolation) should be planned separately after Phase A is verified.

# Completed TODO Items

Items moved from `docs/planning/TODO.md` as they were completed. Most recent first.

---

### 2026-03-10 — Multi-User Deployment: Phase 3 Code Changes

Production deployment code changes (Phase 3 of `MULTI_USER_DEPLOYMENT_PLAN.md`). CORS origins configurable via `CORS_ALLOWED_ORIGINS` env var (was hardcoded localhost). Session cookie `secure=True` in production via `ENVIRONMENT` env var (`routes/auth.py` + `SessionMiddleware`). Admin auth switched from query param (`?admin_token=`) to `X-Admin-Token` header (prevents token leaking in access logs/browser history). `POST /generate_key` now requires admin auth (was unauthenticated). `POST /auth/cleanup` now requires admin auth with `HTTPException` pass-through fix. New `scripts/run_migrations.py` (per-file transactions, `_migrations` tracking table, atomic rollback). New `scripts/deploy.sh` (rsync + pip install + source .env + migrate + restart + health check). 8 Codex review rounds on the deployment plan. 3149 tests pass. Live-tested: health, auth, CORS allow/deny, endpoint auth enforcement. Commits `15138d6e`, `eb8fd989`.

---

### 2026-03-10 — Per-User Ticker Configuration (`user_ticker_config`)

Per-user FMP ticker alias overrides via `manage_ticker_config` MCP tool. Action-dispatched CRUD (list/set/get/delete), user-scoped. One table with `config_type` discriminator (`fmp_alias` wired, `cash_proxy` stored with warning for Phase 2). FMP alias overrides merged into `portfolio_data.fmp_ticker_map` in `_load_portfolio_for_analysis()` — applies to all 8+ risk/perf/optimization MCP tools. User overrides take precedence over position-data mappings. Non-fatal if DB unavailable. 3 `DatabaseClient` methods (get/upsert/delete with table-missing degradation). Validation: ticker regex, currency regex, resolved_value format. 22 tests. 5 Codex review rounds. Plan: `USER_TICKER_CONFIG_PLAN.md`. Commit `ba827e05`.

---

### 2026-03-10 — Frontend App Platform Extraction (`@risk/app-platform`)

Extracted generic, domain-agnostic frontend infrastructure from `@risk/chassis` into new `@risk/app-platform` package, mirroring the backend `app_platform/` extraction pattern. 5 phases: (1) scaffold + pre-init-safe logger, (2) EventBus + cache + utilities with `portfolioId→scopeId` generalization, (3) HttpClient from APIService + QueryProvider with lazy client + `initQueryConfig()`, (4) auth store factories (`createAuthStore<TUser>()`, `createAuthSelectors<TUser>()`, `createAuthProvider<TUser>()`) with callback injection for all side effects, (5) `createRuntimeConfigLoader<T>()` with injectable Zod schema. Chassis re-exports are permanent backward-compat layer. Deleted `AuthProvider.tsx` + `AuthInitializer.tsx` (absorbed into factory). APIService broken dedup dropped. 47 files, 443 tests, `tsc -b` clean. Published to npm as `web-app-platform@0.1.0`. tsup build (ESM+CJS+DTS). Sync: `scripts/sync_frontend_app_platform.sh`. Publish: `scripts/publish_web_app_platform.sh`. GitHub: `henrysouchien/web-app-platform`. Plan: `FRONTEND_APP_PLATFORM_PLAN.md`. Commits: `eb23f3e6`, `c3a2efe9`, `473cfe45`.

---

### 2026-03-10 — Admin MCP Tool: `manage_instrument_config`

Admin CRUD tool for futures contract specs and exchange resolution config. 6 actions: `list_contracts`, `get_contract`, `upsert_contract`, `delete_contract`, `get_exchange_config`, `update_exchange_section`. Input validation (symbol regex, positive numbers, asset_class whitelist, section name whitelist, JSON string parsing), Decimal/datetime serialization, cache invalidation via `InstrumentConfigLRUCacheAdapter` on all writes, ephemeral-change warning. 3 new `DatabaseClient` methods. 28 tests. Plan: `ADMIN_INSTRUMENT_CONFIG_PLAN.md`. Commit `8e4ace39`.

---

### 2026-03-10 — Frontend Logging userId Spoofing Fix

`frontend_logging_auth_check()` resolved user from session cookie but returned `True` instead of user dict, allowing authenticated clients to spoof `userId` and `session` in log payloads. Fix: return full user dict in production, thread `auth_result` through `process_individual_log()`, override `userId` with `str(auth_result['user_id'])` and `session` with cookie-sourced `session_id` (not body). Dev mode preserves client-supplied values. 3 new tests (spoofed userId, spoofed session, dev passthrough). 2 Codex review rounds. Plan: `FRONTEND_LOGGING_USERID_FIX_PLAN.md`. Commit `5027a351`.

---

### 2026-03-10 — YAML → DB Seed: Reference Data Read Paths

Added DB-first + YAML fallback read paths for the last 2 YAML-only reference data configs (`contracts.yaml`, `exchange_mappings.yaml`). 2 new DB tables (`futures_contracts` normalized, `exchange_resolution_config` JSONB). Unified `scripts/seed_reference_data.py` orchestrates all 7 reference data seeders (existing 5 + new 2) with atomic Phase 2 seeding, verification of all 9 tables, and full cache invalidation (5 caches + service caches). `InstrumentConfigLRUCacheAdapter` registered in both cache-manager assembly paths. 14 new tests, cache isolation fixtures in 4 existing test files. 10 Codex review rounds. Plan: `YAML_DB_SEED_PLAN.md`. Commit `1f18ae90`.

---

### 2026-03-10 — Hook Migration: usePositions (Batch E, 17/18)

Migrated `usePositions` from direct TanStack Query to `useDataSource('positions-enriched')` pattern. Added new `positions-enriched` data source with API+adapter resolver — raw `positions` resolver stays untouched for 5 downstream resolvers that depend on the store-based shape. Hook 57→26 lines. 3 Codex review rounds (catalog registration sites, refetch void-return, retry behavior). Plan: `HOOK_MIGRATION_USEPOSITIONS_PLAN.md`. Commit `4665b964`.

**Hook Migration complete**: 17/18 hooks migrated (Batches A-E). `useScenarioHistory` permanently deferred (90% mutations, doesn't fit read-only `useDataSource` pattern). Performance Optimization also complete (all 4 phases).

---

### 2026-03-09 — Performance Optimization Phase 4C: Concurrent Analysis Steps

Final piece of backend performance optimization. `build_portfolio_view()` and `calc_max_factor_betas()` in `analyze_portfolio()` are independent — Step 3 needs only config, not Step 2's output. Wrapped both in `ThreadPoolExecutor(max_workers=2)`. FMP rate limiter confirmed thread-safe (`threading.Lock`, 700 calls/min sliding window).

Fix (`e82db300`): Added `concurrent.futures.ThreadPoolExecutor` to `core/portfolio_analysis.py`. LRU-miss warm-disk: ~1.14s → ~0.74s (~35% improvement). All 4 phases of performance optimization now complete (P1: frontend logger, P2: request dedup, P3: gateway prompt caching, P4: backend).

---

### 2026-03-09 — Futures Phase 9: Live Futures Pricing in Trade Preview

`preview_futures_roll` MCP tool had zero live pricing — Market orders returned `estimated_price=None`. Fix (`bb9b5e00`): Added `_fetch_roll_market_data()` helper to `TradeExecutionService` that calls `IBKRMarketDataClient.fetch_snapshot()` for both roll legs BEFORE the adapter's `whatIfOrder()` call (avoiding `ibkr_shared_lock` deadlock). Market orders derive `estimated_price` from calendar spread mid (back_mid − front_mid for long_roll, negated for short_roll). Always recomputes `estimated_total` with contract multiplier from `get_contract_spec()` (fixes pre-existing bug where adapter formula missed multiplier). Graceful degradation when market closed. Added `market_data` field to `TradePreviewResult` (surfaced in API response + formatted report). 3 Codex review rounds. 10 new tests. Plan: `FUTURES_LIVE_PRICING_PLAN.md`.

---

### 2026-03-09 — Futures Phase 8b: instrument_types DB Read Path

Closed the gap where `_load_portfolio_from_database()` → `PortfolioAssembler.build_portfolio_data()` never passed `instrument_types` or `contract_identities` to `PortfolioData.from_holdings()`, even though the DB `positions.type` column already stored correct values from brokerage normalizers.

Fix (`f138ffe6`): Added `build_instrument_types_map()` (detects futures/option/bond from DB type, promotes IBKR-direct `derivative` → `futures` via exchange mappings, falls through to option symbol parsing for Plaid-style derivative options). Made `filter_positions()` derivative-aware via `promoted_derivatives` set (promoted futures/options pass, warrants/structured products dropped). Added `build_contract_identities_map()` (uppercased keys matching downstream lookups), `enrich_futures_fmp_tickers()` (fills missing FMP symbols from contract specs). Threaded `instrument_types` through `_ensure_factor_proxies()` to prevent bogus proxy lookups. Reordered `_load_portfolio_from_database()`: detect types on raw positions before filtering. 8 Codex review rounds. 15 new tests. Plan: `INSTRUMENT_TYPES_DB_READ_PATH_PLAN.md`.

---

### 2026-03-09 — Multi-User Isolation Audit Fixes

Audit found 3 gaps in multi-user readiness. Fix (`15219d03`): Added `user_id` param + WHERE clause to `delete_provider_item()` and `set_provider_item_reauth()` in `database_client.py`. Added `_resolve_item_owner()` helper for Plaid ITEM webhook user resolution (scoped to 3 mutating codes only). Implemented production session auth on `POST /api/log-frontend` (health endpoint stays public). Threaded `user_id` through all callers (`routes/plaid.py`, `scripts/plaid_reauth.py`). 17 new tests. 3 Codex review rounds. Plan: `MULTI_USER_AUDIT_FIX_PLAN.md`.

---

### 2026-03-09 — PostgreSQL Connection Leak — Root Cause Fix

Root cause: MCP stdio processes died without closing their `psycopg2` connection pools. Each `/mcp` reconnect orphaned `DB_POOL_MIN` connections. Over days, 85 idle connections accumulated (17 pools × 5 connections), approaching `max_connections=100`.

Fix (`0b8b100d`): `SimpleConnectionPool` → `ThreadedConnectionPool` (thread-safe). Pool defaults 5/20 → 2/10. Added `close_pool()` in `app_platform/db/pool.py`. Wired cleanup into MCP lifespan (`@mcp_lifespan`), FastAPI lifespan, and `atexit`. Hardened `putconn()` with `PoolError` catch for shutdown races. Fixed use-after-release bug in `routes/factor_intelligence.py` (`delete_factor_group` was outside `with` block). Updated `.env.example` and 5 doc files. 4 new test files. Plan: `PG_CONNECTION_LEAK_FIX_PLAN.md`.

Live-tested: 85 → 2 connections after deploy. Two `/mcp` reconnects confirmed cleanup handler fires reliably (old pool cleaned, new pool creates 2).

---

### 2026-03-09 — Performance Optimization Phase 4 (Backend)

Phase 4 (`2f4e3f0c`): 3 items optimizing the `analyze_portfolio()` cold-cache path. Plan: `PERFORMANCE_PHASE4_PLAN.md`.
- **4A — Eliminate redundant fetch**: Added optional `worst_losses` kwarg to `compute_max_betas()`. `calc_max_factor_betas()` passes precomputed data, skipping redundant `get_worst_monthly_factor_losses()` call. 7 external callers unchanged (backward-compatible).
- **4B — Parallelize proxy fetches**: Replaced sequential `for` loop in `get_worst_monthly_factor_losses()` with `ThreadPoolExecutor` + `as_completed`. Mirrors existing `get_returns_dataframe()` pattern.
- **4D — Fix Makefile worker config**: Split `dev` (reload, single worker) from `serve` (multi-worker, no reload) — uvicorn `--workers` and `--reload` are mutually exclusive. Updated `app.py` `__main__` to use import string `"app:app"` and env-configurable `UVICORN_WORKERS`.
- **4C — Concurrent steps**: Deferred pending FMP rate limiter concurrent access testing.

Live test: `analyze_portfolio()` cold cache 1.14s (15-pos YAML), warm cache 26ms. 4 new tests. 6 Codex review rounds.

---

### 2026-03-09 — PostgreSQL Connection Pool Exhaustion — Cascading Failure Fix

Fix (`2dca72fd`): TTL (5min) + cooldown (30s) on `is_db_available()`, `PoolError`→`PoolExhaustionError` + `OperationalError`→`ConnectionError` wrapping in `get_db_session()`, `on_pool_error` callback wired via `database/session.py` shim, 503 handler in `app_platform/db/handlers.py`, defense-in-depth in `@handle_mcp_errors` + 3-way `@require_db` messaging. System self-heals after pool recovery instead of requiring `pg_ctl restart`. 30 tests. Live-tested with real pool exhaustion + recovery. Plan: `PG_POOL_EXHAUSTION_FIX_PLAN.md`.

---

### 2026-03-09 — Performance Optimization Phase 2 (Frontend Request Reduction)

Phase 2 (`5429d81e`): 4 items reducing page load from ~45 → 26 API requests. Plan: `PERFORMANCE_PHASE2_PLAN.md`.
- **2C — Normalize performancePeriod default**: `stripDefaults()` in `buildDataSourceQueryKey()` strips `performancePeriod: '1M'` before cache key serialization, eliminating 1 duplicate HTTP request at both TanStack and `PortfolioCacheService` layers (`.p1M` suffix mismatch).
- **2B — Fix prefetch cache key alignment**: Scheduler now passes `{ portfolioId }` for all 5 eager sources (positions, risk-score, risk-analysis, risk-profile, performance), so prefetch actually warms consumer cache instead of building mismatched keys.
- **2B-ii — Parallelize eager sources**: `groupByDependencyLevel()` + `Promise.allSettled` runs Level 1 sources concurrently instead of sequentially.
- **2A — Remove app-level hooks**: Removed redundant `usePortfolioSummary()` + `useRiskAnalysis()` from `ModernDashboardApp.tsx` — containers already mount their own hooks.
- **2D — Throttle network logs**: Production-mode filter skips fast successful network requests in `frontendLogger.ts`.

Cumulative: **103 → 45 → 26 API requests** across Phases 1+2 (75% total reduction).

---

### 2026-03-09 — Performance Optimization Phase 1 (Items 1A + 1B)

- **1A — Batch frontendLogger** (`4d8ca07e`): `processQueue()` now sends single batched POST using backend's existing `{ logs, sessionId }` format instead of N individual fetches. 200ms idle-timer debounce. Beacon flush on `beforeunload` and `visibilitychange`. Result: ~55 log requests → ~11 per page load.
- **1B — Fix market-intelligence 500** (`4d8ca07e`): `_coerce_symbol()` handles NaN/float `fmp_ticker` values in `mcp_tools/news_events.py`. Endpoint returns graceful empty payload on error instead of HTTP 500. Eliminated 12-request retry storms. 32 tests. Plan: `PERFORMANCE_OPTIMIZATION_PLAN.md`.

---

### 2026-03-09 — Efficient Frontier (Phases 1+2 Complete)

- **Phase 1 — Backend** (`33f2d33d`): CVXPY parametric volatility sweep engine, `get_efficient_frontier` MCP tool, `POST /api/efficient-frontier` REST endpoint, `EfficientFrontierResult`, 5 tests. Live-verified 10-point frontier in 2.2s. Plan: `EFFICIENT_FRONTIER_PLAN.md`.
- **Phase 2 — Frontend** (`66ac39a7`): New "Efficient Frontier" tab in ScenarioAnalysis. Recharts ScatterChart (emerald frontier + orange current portfolio marker). 19 files across 3 packages (chassis/connectors/ui). `useEfficientFrontier()` hook, metric cards, 10/15/20 n_points selector, detail table. Codex-reviewed (2 rounds). Live-verified 15 points in 1.7s. Plan: `EFFICIENT_FRONTIER_PHASE2_PLAN.md`.

---

### 2026-03-09 — IBKR Order Status Fix (Completed Orders)

- **IBKR completed order zeroed fills**: `order.filledQuantity` fallback when `orderStatus.filled` is zeroed by ib_async for completed orders. Post-status override: EXECUTED+0+non-BAG→CANCELED. SQL only-increase guard for `filled_quantity`, late `average_fill_price` backfill, `cancelled_at` idempotency (`COALESCE(cancelled_at, NOW())`). Recovery probe rewritten with same fallback. 12 Codex review iterations, 12 new tests. Commit `e0b55569`. Plan: `IBKR_ORDER_STATUS_FIX_PLAN.md`.

---

### 2026-03-09 — Idea Ingestion Scheduling (Phase 3 Complete)

Configured 10 recurring job schedules in jobs-mcp for automated idea ingestion. Screens run at 04:30 local, results flow to workspace markdown, analyst triages at 06:00 (step 3.5, 8 ideas/run). Updated 8 existing schedules (increased frequency, moved earlier) and created 2 new ones. Pipeline: jobs-mcp scheduler → `ingest.py` CLI → memory connectors → workspace `tickers/*.md` → analyst triage.

Schedules: daily estimate_revisions, 2x/week insider_buying (Mon+Thu) + special_situations (Tue+Fri), weekly quality_screen (Sun) + fingerprint_screen (Wed) + ownership (Mon) + biotech_pipeline (Mon). Portfolio estimate alert kept monthly (separate purpose).

---

### 2026-03-08 — IBKR get_orders Fill Bug + Risk Score Redesign

- **IBKR `get_orders` fill bug**: `_fill_data_from_trade()` extracts from `trade.fills[]` when `orderStatus` is zeroed (reqCompletedOrders bug). BAG order safe. 8 tests. Commit `102c1722`.
- **Risk Analysis Card: Risk Score View redesign**: Cards now show top positions+weights, actual vol %, dominant factor+beta, top sector+variance instead of redundant score display. `buildRiskFactorDescription()` computes contextual descriptions. Commit `5831c982`. Formatting fix: `46dd030e`.

### 2026-03-08 — Frontend Phase 5 Visual Polish (Complete)

- **Batch 1 — StockLookup + Risk Analysis** (`05bb1241`): `glassTinted` on 11 Cards, `hover-lift-subtle` on 12 metric cards, `animate-stagger-fade-in` on 4 card lists. Plan: `FRONTEND_STOCKLOOKUP_RISK_POLISH_PLAN.md`.
- **Batch 2 — Chart Polish** (`e3570800`): MonteCarloTab 9 hex colors → `chartSemanticColors` system. Plan: `FRONTEND_CHART_POLISH_PLAN.md`.
- **Batch 3 — Typography + CSS Pruning** (`26831157`): `text-balance-optimal` on SectionHeader + 5 CardTitle headings. Removed unused `dashboard-layout` CSS. Plan: `FRONTEND_TYPOGRAPHY_CSS_PRUNE_PLAN.md`.
- **Batch 4 — Dark Mode Audit + Morph Border** (`02ee0a3a`): Dark mode fixes for `morph-border` + premium hover shadows. `morph-border` on MarketplaceTab Featured Strategy card. 26-class audit. Plan: `FRONTEND_DARKMODE_MORPHBORDER_PLAN.md`.

---

### 2026-03-08 — Backend Bug Fixes (fetch_monthly_close 500s, Risk Score NaN, FMP Cache, Date Range)

- **Backend Bug: `fetch_monthly_close` 500s**: Three root causes — float NaN in fmp_ticker_map (`bd0d57fa`), unmapped CUR: cash tickers + trailing-dot key mismatch (`a7f2f25c`). Plans: `FMP_TICKER_MAP_FLOAT_BUG_PLAN.md`, `PERFORMANCE_500_CUR_AND_TRAILING_DOT_PLAN.md`.
- **`/api/performance` Default Date Range**: 7-year DB range → 1-year lookback default. Commit `a6b76b4d`. Plan: `PERFORMANCE_DEFAULT_DATE_RANGE_FIX_PLAN.md`.
- **FMP Pricing Cache Audit**: Split `fetch_fmp_quote_with_currency()` into cached `infer_fmp_currency()` + uncached price path. ~60-70% reduction in profile API calls. Commit `3076e595`. Plan: `FMP_PRICING_CACHE_AUDIT_PLAN.md`.
- **Volatility Risk Score NaN**: `_safe_finite()` helper, NaN→conservative fallback, `.get()` guards in formatters. 17 tests. Commit `ab41ecd1`. Plan: `VOLATILITY_RISK_SCORE_FIX_PLAN.md`.

### 2026-03-08 — Risk Analysis Card Formatting Fix

- **Risk Analysis Card: Fix Formatting & Remove Redundancy**: Removed redundant "Risk Level" / impact row from Risk Score tab (was echoing score already in header). Stress Tests tab: formatted raw floats as percentages via `formatPercent` from `@risk/chassis`, title-cased scenario names, formatted probability decimals. Hedging tab already fine. Commit `46dd030e`. Plan: `RISK_ANALYSIS_CARD_FIX_PLAN.md`.

### 2026-03-08 — Exercise Cost Basis Linkage

- **Exercise Cost Basis Linkage**: Option exercise/assignment pre-FIFO linkage. Flex `code` field parsing, four-way right×side matrix, store round-trip via contract_identity JSONB. SLV live-tested: exercised option P&L $-179 → $0, stock cost basis adjusted by premium. Feature-flagged `EXERCISE_COST_BASIS_ENABLED`. 23 tests. Commit `67fd47f5`. Plan: `EXERCISE_COST_BASIS_PLAN.md`.

### 2026-03-08 — Chat UI Markdown + LaTeX Rendering

- **Chat UI: Markdown Rendering**: Wired up `react-markdown` + `remark-gfm` for assistant messages in ChatCore. MarkdownRenderer component + `.chat-markdown` CSS styles (headers, tables, code blocks, blockquotes, lists). User messages stay plain text. Commit `1f04969a`.
- **Chat UI: LaTeX Math Rendering**: Added `remark-math` + `rehype-katex` + `katex` for LaTeX math in assistant messages. `$inline$` and `$$block$$` syntax renders as typeset math (fractions, subscripts, superscripts, square roots). Verified with Sharpe ratio and Black-Scholes formulas. Commit `0aff4ff7`.

### 2026-03-08 — Realized Performance Data Quality Investigation Complete

- **Realized Performance: Data Quality & Accuracy**: 20 fixes across Feb 25 – Mar 8. All major accounts within ~1pp of broker actuals (IBKR 0.48pp, Plaid 1.13pp, Schwab 165 0.94pp). Schwab 252 structural gap (2.48pp) = TWR vs XIRR + FMP vs Schwab pricing. Investigation doc: `completed/REALIZED_PERF_DATA_QUALITY.md`. Full progression: `completed/performance-actual-2025/RETURN_PROGRESSION_BY_FIX.md`.
- **drive-mcp: Apostrophe in Filename Breaks `gdrive_read_file`**: Added `_escape_query()` helper. Commit `c9257ea` (drive-mcp repo). Published PyPI 0.1.3 (`7252aa1`).

### 2026-03-08 — Frontend SDK Testing Wave 3

- **Frontend: SDK Testing — Wave 3 (Complex Hooks)**: 16 hook test files, 200 new tests (446 total, 50 files). All complex hooks with external SDK deps, auth flows, streaming, and multi-query composition. Commit `205b4bf7`. Plan: `FRONTEND_SDK_TESTING_WAVE3_PLAN.md`.

---

### 2026-03-07 — Batch cleanup

- **EDGAR FastAPI Migration — Phase 4 Cleanup**: Removed 4 dead Flask `/api/*` routes + 2 helpers from `app.py` (-1,628 lines). Deleted obsolete test files, ported 3 assertions to FastAPI suite, updated docs. Commit `b3635ee` (Edgar_updater repo).
- **Docs Cleanup (all repos)**: Archived completed plans across 4 repos — ai-excel-addin (28 docs, `d694ff4`), investment_tools (16 docs, `844a7c9`), finance_cli (103 docs, `971859d`), risk_module (done 2026-03-06).
- **drive-mcp: OneDrive Re-Auth**: Already committed and pushed. Commit `f4b8f37` in drive-mcp repo.
- **Options: Continuous Hedge Monitoring**: MCP tool `monitor_hedge_positions()` — 3-tier expiry alerts, delta drift, theta drain, vega, roll recommendations. 25 tests. Commit `201a3a69`. Plan: `completed/HEDGE_MONITOR_PLAN.md`.

---

### 2026-03-06 — Docs Cleanup (risk_module)
Archived completed planning docs and removed stale completed items from active TODO tracking.

Archived plan docs moved to `docs/planning/completed/`:
- `ASSET_ALLOCATION_WORKFLOW_PLAN.md`
- `BACKTESTING_ENGINE_PLAN.md`
- `EVENT_LOOP_BLOCKING_FIX_PLAN.md`
- `FRONTEND_CLEANUP_P4P5_PLAN.md`
- `FRONTEND_SDK_TESTING_WAVE2_PLAN.md`
- `OPTION_CASH_REPLAY_MULTIPLIER_PLAN.md`
- `OPTION_PRICING_SYSTEM_WIDE_PLAN.md`
- `ORPHANED_COMPONENT_CLEANUP_PLAN.md`
- `PERFORMANCE_ATTRIBUTION_TAB_PLAN.md`
- `SHARED_REDIS_CACHE_PLAN.md`
- `STALE_TODO_CLEANUP_PLAN.md`
- `STOCK_LOOKUP_WORKFLOW_PLAN.md`
- `STRESS_TEST_ENGINE_PLAN.md`

Moved from `TODO.md` ("Recently Completed"):
- Frontend: Visual Audit (V1-V32) — all waves complete (`7a7d326c`, `c419a812`, `765435b1`, `9b895ac3`, `20be3311`, `281f6c31`, `7cc9e275`)
- Frontend: Adapter Data Gaps (P6) (`fa3ddc75`, `a2cce363`)
- Frontend: Holdings Export CSV (`ebb71edf`)
- Frontend: Stock Lookup — Price Chart (`20be3311`)
- Architecture: Break Up Large Monolithic Files (`11a26922`)
- Production: Shared Cache for Multi-Worker Uvicorn (`631c8b6e`)
- MCP: `get_performance` response size too large (`94cd5087`)
- API ↔ MCP alignment audit reviewed on 2026-03-04 (8 core pairs working; trading analysis + income projection REST endpoints added)

### 2026-03-06 — Docs Cleanup (risk_module, sweep 2)
Archived an additional batch of completed plan documents from `docs/planning/` to `docs/planning/completed/`:
- `FRONTEND_CLEANUP_P1_PLAN.md`
- `FRONTEND_CLEANUP_P2_PLAN.md`
- `FRONTEND_CLEANUP_P3_PLAN.md`
- `FRONTEND_CLEANUP_STRAGGLERS_PLAN.md`
- `FRONTEND_REDESIGN_PHASE1A_PLAN.md`
- `FRONTEND_VISUAL_AUDIT_P1_PLAN.md`
- `HEDGING_WORKFLOW_PLAN.md`
- `HOLDINGS_EXPORT_CSV_PLAN.md`
- `PERFORMANCE_BACKEND_GAPS_PLAN.md`
- `PERFORMANCE_VIEW_CLEANUP_PLAN.md`
- `PER_POSITION_RISK_SCORE_PLAN.md`
- `PLAID_GHOST_TXN_FILTER_PLAN.md`
- `REST_TRADING_INCOME_ENDPOINTS_PLAN.md`
- `RISK_ANALYSIS_DETAIL_GAPS_PLAN.md`
- `SCENARIO_ANALYSIS_OVERHAUL_PLAN.md`

### 2026-03-06 — Docs Cleanup (risk_module, sweep 3)
Archived completed frontend audit docs from `docs/planning/` to `docs/planning/completed/`:
- `FRONTEND_CLEANUP_AUDIT.md`
- `FRONTEND_DATA_WIRING_AUDIT.md`
- `FRONTEND_ORPHANED_COMPONENTS.md`
- `FRONTEND_VISUAL_AUDIT.md`

### 2026-03-06 — Docs Cleanup (risk_module, sweep 4)
Archived historical cleanup audit doc:
- `PLAN_CLEANUP_AUDIT_2026-03-03.md`

### 2026-03-06 — Docs Cleanup (risk_module, sweep 5)
Archived additional implemented plans/audits:
- `CASH_ANCHOR_NAV_PLAN.md`
- `REALIZED_AUDIT_TRAIL_PLAN.md`
- `PROVIDER_ROUTING_AUDIT.md`

### 2026-03-05 — Option Cash Replay Multiplier Fix
Cash replay in `nav.py` `derive_cash_and_external_flows()` computed `price × quantity` without the 100x contract multiplier for non-IBKR option trades, undervaluing cash impact by 100x (e.g. $12.50 instead of $1,250). IBKR Flex trades already have per-contract prices (×100 at `flex.py:356`) and are correctly skipped. Fix threads `instrument_type`, `source`, `multiplier` into event dict and applies multiplier for non-IBKR options in both trade cash impact and `unpriceable_suppressed_usd` tracking. Guards trade math behind event_type check to prevent KeyError on INCOME/PROVIDER_FLOW/FUTURES_MTM events. Gated by `OPTION_MULTIPLIER_NAV_ENABLED`. Completes the option multiplier system — with this fix plus commits `62110090`/`e2c33f5f`, the flag is safe for production. Commit `ea5382d1`. Plan: `OPTION_CASH_REPLAY_MULTIPLIER_PLAN.md`.

### 2026-03-05 — Option Multiplier NAV Fix
Fix 100x undervaluation of option positions in realized performance NAV when prices come from IBKR market data or B-S fallback (per-share premiums vs per-contract convention). Two fix sites in `engine.py`: (1) price chain results (source 3, all providers) and (2) FIFO terminal heuristic (source 2, non-IBKR only — IBKR Flex already per-contract). New `_option_fifo_terminal_source()` helper in `_helpers.py` mirrors terminal event selection to check source. Feature-flagged via `OPTION_MULTIPLIER_NAV_ENABLED` (default false). Known follow-up: cash replay multiplier fix in `nav.py:288` must be done before enabling flag in production. Commits `62110090`, `e2c33f5f`. Plan: `OPTION_PRICING_SYSTEM_WIDE_PLAN.md`.

### 2026-03-05 — System-Wide Option Pricing
Made option prices available across all providers: (1) Phase 1 — fixed Schwab (3 sites), SnapTrade (4 sites), and Plaid (1 site) normalizers to populate `contract_identity` for options using `parse_option_contract_identity_from_symbol()` + `enrich_option_contract_identity()` (adds `multiplier: 100`). Fixed OCC parser to strip internal whitespace for Schwab space-padded symbols. (2) Phase 2 — new `OptionBSPriceProvider` in `providers/bs_option_price.py` (~210 lines) implementing `PriceSeriesProvider` protocol. Uses DI for underlying/treasury fetchers. Registered at priority 25 (after IBKR at 20) in both registries. Computes rolling 12m realized vol, risk-free rate from treasury, calls `black_scholes_price()` per month-end, intrinsic value after expiry. Feature-flagged via `OPTION_BS_FALLBACK_ENABLED` (default false). Verified live with real SLV option data (6 monthly B-S prices). Commit `6c1fe46b`. Plan: `OPTION_PRICING_SYSTEM_WIDE_PLAN.md`.

### 2026-03-05 — Shared Redis Cache for Multi-Worker Uvicorn
Redis L2 write-through cache behind `PortfolioService.analyze_portfolio()`. Both uvicorn workers share expensive analysis results (~30-60s compute → ~5ms Redis hit). pickle+zlib serialization, graceful fallback when Redis unavailable. Feature-flagged via `REDIS_CACHE_ENABLED` (default false). New file `services/redis_cache.py`, `RedisCacheAdapter` registered in both `build_cache_manager()` and `ServiceManager._get_cache_manager()`. 34 targeted tests pass. Commit `631c8b6e`. Plan: `SHARED_REDIS_CACHE_PLAN.md`.

### 2026-03-05 — Frontend SDK Testing Wave 2
26 new hook test files, 246 total tests (up from 54). Covers useDataSource wrappers (useRiskAnalysis, usePerformance, useRiskMetrics, useAnalysisReport), useQuery/API hooks (useSmartAlerts, useMetricInsights, useAIRecommendations, useMarketIntelligence, usePositions, useHedgingRecommendations), mutation hooks (useHedgePreview, useHedgeTrade, useRealizedPerformance, useSetTargetAllocation, useRebalanceTrades), query+state hooks (useTargetAllocation, useStockSearch, usePeerComparison, useStockAnalysis, useStrategyTemplates, useNotificationStorage), and composition hooks (useNotifications, useMonteCarlo, useStressTest, useBacktest, useScenarioHistory). +3,814 lines. Commit `54b82f63`. Plan: `FRONTEND_SDK_TESTING_WAVE2_PLAN.md`.

### 2026-03-04 — Frontend Cleanup Audit P1-P5 COMPLETE
All 5 priority tiers of the frontend cleanup audit are done. P1 (active harmful code, `62106f7b`), P2 (mock data rendering, `62106f7b`+`1ee96537`), P3 (inert buttons, `b99dc188`+`396da1c3`), P4 (dead code, `f0073bc9`+`396da1c3`), P5 (stale comments, `396da1c3`). P6 (adapter gaps) deferred — needs backend work. Orphaned components also deleted (`39380859`, -7,118 lines). Full audit: `completed/FRONTEND_CLEANUP_AUDIT.md`.

### 2026-03-04 — Orphaned Component Cleanup
Deleted 41 orphaned frontend files (-7,118 lines) across 6 categories: dead InstantTryPage + 3 dependencies (no route), superseded infrastructure (AppOrchestrator, DashboardLayout, ConnectedRiskAnalysis), entire orphaned charts/ subsystem (6 charts, 8 slots, 2 examples, 1 adapter, 1 constants, 2 docs), unused shared UI primitives (MetricsCard, StatusIndicator, LoadingView), legacy Plaid/SnapTrade provider wrappers (4 components bypassed by AccountConnectionsContainer), debug recovery artifact. Cleaned 4 barrel exports. Deleted 6 directories. `pnpm typecheck` + `pnpm build` clean. Live-verified: Overview, Holdings, Performance all render correctly. Commit `39380859`. Plan: `ORPHANED_COMPONENT_CLEANUP_PLAN.md`.

### 2026-03-04 — Event Loop Blocking Fix: `run_in_threadpool` for 9 Heavy Endpoints
Wrapped 9 blocking `async def` API endpoints with `run_in_threadpool` to prevent event loop starvation under `--workers 2`. Pattern: extract blocking work into `_run_*_workflow()` sync helper, call via `await run_in_threadpool()`. Endpoints: `/api/analyze`, `/api/risk-score`, `/api/performance`, `/api/interpret`, `/api/portfolio-analysis`, `/api/what-if`, `/api/stress-test`, `/api/stress-test/run-all`, `/api/monte-carlo`. 3 endpoints already done (backtest, min-variance, max-return) → 12 total. Error handling preserved per-group: PortfolioService endpoints (1-5) catch generic `Exception → 500`; ScenarioService endpoints (6-9) have `PortfolioNotFoundError → 404` + `except HTTPException: raise`. All 9 tested live via curl. Remaining: 9 `/api/direct/*` variants (lower priority). Commit `55605c76`. Plan: `EVENT_LOOP_BLOCKING_FIX_PLAN.md`.

### 2026-03-04 — PortfolioOverview Alpha/Concentration Metrics
Alpha Generation wired to CAPM alpha from performance engine. ESG Score replaced with Concentration metric (risk score component, 0-100, higher=safer). Unused `_prefixed` setters cleaned up. Commit `671d41de`.

### 2026-03-04 — Performance Attribution Tab Rebuild
Replaced inconsistent card/list rendering with clean attribution tables matching StrategyBuilder backtest pattern. 4 tables: Sector Attribution (name, allocation%, return%, contribution%), Factor Attribution (Market/Value/Momentum betas + contributions), Top Contributors, Top Detractors. Removed unused `getTrendIcon()` and `getAnalystRatingBadgeColor()`. Added `formatOptionalPercent`/`formatOptionalNumber` helpers. Live-verified: 10 sectors, 4 factors, contributors (SLV +14.18%) and detractors (IT -1.53%). Commit `df9de726`. Plan: `PERFORMANCE_ATTRIBUTION_TAB_PLAN.md`.

### 2026-03-04 — Frontend Wiring Gaps (Pre-Redesign) — SECTION COMPLETE
All 14 items complete. 9/9 views wired to real APIs with zero mock data. Final items: Stale TODO Cleanup (`f58c6d21`), Alpha/Concentration (`671d41de`), Performance Attribution (`df9de726`). Full audit: `completed/FRONTEND_DATA_WIRING_AUDIT.md`.

### 2026-03-04 — Frontend Views → Defined Workflows (Phase 4) — SECTION COMPLETE
All 5 workflow upgrades complete: Stock Lookup Research (`3337f2d1`), Hedging Real Workflow (`18aa43ae`), Asset Allocation Target+Rebalance (`f2dc9b55`), Performance Realized Mode (`ae290b35`), Scenario Analysis Full Overhaul (5 phases, `627c167f`→`b6f3e45e`→`b0194df1`).

### 2026-03-04 — Workflow Gaps: Scenario & Strategy — 5/7 COMPLETE
Predefined scenario templates (`627c167f`), stress test presets (`d1df3fee`→`a1d598fb`), scenario persistence (`c3e4eb56`), return attribution/Brinson (`df9de726`), backtesting engine (Wave 3g, 4 commits). Remaining: efficient frontier visualization, strategy versioning.

### 2026-03-04 — Stale TODO Cleanup (PortfolioOverview & PerformanceView)
Removed stale TODO comments and unused state variables from 3 frontend files. PortfolioOverview: 6 `TODO:ADD to PortfolioSummaryAdapter` comments replaced with `✅` (all fields already wired), 5 unused `useState` declarations deleted (`_personalizedView`, `_predictiveMode`, `_correlationAnalysis`, `_riskRadar`, `_selectedTimeframe`). PerformanceView: stale `❌ TODO` status markers updated to `✅ INTEGRATED` (attribution + benchmarks), aspirational TODO block updated (sector/security `✅`, factor backlog, benchmarks `✅`), mock data TODOs relabeled as fallback/backlog, unused `_activeTab` state removed, architecture diagram and Enhancement Opportunities updated. PerformanceViewContainer: stale "MINOR ENHANCEMENTS NEEDED" block removed (all 3 items wired), stale `TODO: Enhance` comment removed. This closes the "Frontend Wiring Gaps (Pre-Redesign)" section. Commit `f58c6d21`. Plan: `STALE_TODO_CLEANUP_PLAN.md`.

### 2026-03-04 — Stress Test Engine (Wave 3h)
Full stress test computation engine wired end-to-end. Backend: `portfolio_risk_engine/stress_testing.py` with 8 predefined multi-factor scenarios (interest rate shock, credit spread widening, equity vol spike, currency devaluation, oil price shock, correlation breakdown, market crash, stagflation). Math reuses existing factor-beta infrastructure: `portfolio_impact = Σ(factor_beta × shock) × leverage_ratio`, per-position impacts via `stock_betas` DataFrame, factor contribution breakdown. `services/scenario_service.py` implements `analyze_stress_scenario()` (previously declared but never built). 3 API endpoints: `POST /api/stress-test` (single scenario), `GET /api/stress-test/scenarios` (catalog), `POST /api/stress-test/run-all` (comparison matrix). Pydantic `StressTestRequest`/`StressTestResponse` models. 5 unit tests. Frontend: `APIService` (3 methods with response unwrapping), `PortfolioCacheService` (cache method), `PortfolioManager` (analyzeStressTest), `StressTestAdapter` (snake→camel transform with `generateContentHash`/`generateStandardCacheKey`), `useStressTest`/`useStressScenarios` hooks, `ScenarioAnalysisContainer` wiring, `ScenarioAnalysis` UI (dynamic scenario cards with severity badges, shock factor display, Live/Coming Soon indicators, Run button, results panel with position impacts sorted worst-first + factor contributions). Live-verified: Market Crash (-20%) → -26.0% portfolio impact (-$38,069), NVDA worst at -35.6%, factor contribution Market -26.0% (beta 1.04). Also added `make dev` target with `--workers 2` default to prevent single-worker blocking. Commits `f89dad23` (plan), `d1df3fee` (backend), `9e43e547` (Phase 3 plan), `6644b810` (frontend), `a1d598fb` (API unwrapping fix), `3b0f4972` (make dev). Plan: `STRESS_TEST_ENGINE_PLAN.md`.

### 2026-03-03 — Asset Allocation → Interactive Workflow (Phase 4)
Asset Allocation upgraded from data-display to interactive **monitor → set targets → rebalance** workflow. Backend: 3 REST endpoints in `app.py` — `GET /api/allocations/target` (read targets from DB), `POST /api/allocations/target` (validate via `_validate_and_normalize_allocations()` + persist via `PortfolioRepository`), `POST /api/allocations/rebalance` (delegates to `preview_rebalance_trades()` from `mcp_tools/rebalance.py`). Frontend: `targetAllocationKey` in queryKeys.ts, 3 APIService methods, 3 TanStack hooks (`useTargetAllocation`, `useSetTargetAllocation` with `cacheCoordinator.invalidateRiskData()`, `useRebalanceTrades`). UI: inline target editing with running total validation (100% ± 0.5%, green/red), "Set Targets" + "Rebalance" action buttons, rebalance preview panel with sequenced trade legs (sells first, buys second), summary stats (trade count, net cash, total value). Canonical asset-class key preservation for backend compatibility. 10 files (1 backend + 9 frontend), 6 backend tests. Live-verified in Chrome: set targets → save → drift updates → rebalance → 23 trade preview (5 sells, 18 buys). Commit `f2dc9b55`. Plan: `ASSET_ALLOCATION_WORKFLOW_PLAN.md`.

### 2026-03-03 — Stock Lookup → Full Research Workflow (Phase 4)
Stock Lookup upgraded from 4-tab data display to 6-tab research→evaluate→size→execute workflow. Backend: `GET /api/direct/stock/{symbol}/peers` endpoint delegating to `fmp.tools.peers.compare_peers()` via `stock_service.get_peer_comparison()`. Frontend: `peerComparisonKey` in queryKeys.ts, `getPeerComparison()` in APIService, `usePeerComparison` hook, 2 new tabs. **Peer Comparison**: ratio table (P/E, P/B, P/S, margins, debt/equity) with ranking badges (#N/M, Best/Worst). **Portfolio Fit**: 1%/2.5%/5% size selector, what-if via existing `useWhatIfAnalysis` with string delta format (`"+2.5%"`), before/after risk metrics (volatility, concentration, factor variance), risk check pass/fail, MVP trade preview (computed shares + estimated cost from portfolio value × size ÷ price). 11 files, 877 insertions, 2 backend tests. Live-verified in Chrome with real FMP data. Commit `3337f2d1`. Plan: `STOCK_LOOKUP_WORKFLOW_PLAN.md`.

### 2026-03-03 — Strategy Builder Backtesting Engine (Wave 3g)
Real historical backtesting engine for the Strategy Builder. Replays target ticker weights over historical price data to show what-would-have-happened performance vs benchmark. 5 phases: (1) Core engine `portfolio_risk_engine/backtest_engine.py` reusing `get_returns_dataframe()`, `compute_portfolio_returns_partial()`, `compute_performance_metrics()` with dynamic observation gating and ticker filtering. (2) `BacktestResult` dataclass + `backtest_flags.py` (5 flag types: excluded tickers, short window, deep drawdown, benchmark relative, positive risk-adjusted). (3) `POST /api/backtest` endpoint in `app.py`. (4) MCP tool `run_backtest` in `mcp_tools/backtest.py` with agent/summary/full format. (5) Frontend: `useBacktest` hook, `BacktestAdapter`, period selector (1Y/3Y/5Y/10Y/MAX), wired into `StrategyBuilderContainer.tsx` using real optimization weights. Verified end-to-end: 30% AAPL / 30% MSFT / 40% SGOV → 38% return vs 67.6% SPY over 3Y, 4-year annual breakdown, cumulative/monthly returns. Commits `42473036` (plan), `76bf0121` (backend), `6e007162` (frontend), `733b8c9e` (API endpoint fix). Plan: `BACKTESTING_ENGINE_PLAN.md`.

### 2026-03-03 — Smart Alerts Fund/ETF Concentration Fix (DSU)
Schwab's `_ASSET_TYPE_MAP` mapped `MUTUAL_FUND` → `"equity"` in both `providers/schwab_positions.py` and `providers/normalizers/schwab.py`. This caused funds like DSU (BlackRock Debt Strategies Fund) to bypass the `_is_diversified()` concentration exemption (`774e673e`), triggering false concentration risk alerts. Fix: map `MUTUAL_FUND` → `"mutual_fund"` (matches `DIVERSIFIED_SECURITY_TYPES`). Commit `f9135ff6`.

### 2026-03-03 — Performance View Mock Fallback Removal (Wave 3f)
Deleted 5 hardcoded fallback arrays (`fallbackSectors`, `fallbackTopContributors`, `fallbackTopDetractors`, `fallbackMetrics`, hardcoded `monthlyReturns`) from `PerformanceView.tsx`. Refactored `buildInsights()` to detect no-data via `=== 0` checks instead of comparing against deleted `fallbackMetrics`. Wired real monthly returns by computing per-month deltas from cumulative `timeSeries` data (inverse compounding). Added empty-state guards for sectors, contributors, detractors, monthly sections. Changed "AI Enhanced" badge to "Portfolio Data". Timezone-safe date parsing via string split. Unique React keys via date string. Commit `52c6d95a`. Plan: `PERFORMANCE_MOCK_REMOVAL_PLAN.md`.

### 2026-03-03 — Silent Transaction Provider Failure Fix
Three-part fix: (1) `_detect_skipped_providers()` in `fetch_transactions_for_source()` emits `FetchMetadata` for enabled-but-unavailable providers (`1dc1c8b8`, `277cbc40`). (2) `fetch_errors` surfaced in `get_agent_snapshot()` data_quality dict → readable by performance flags. (3) Two new flags: `provider_data_missing` (credentials gap, user-actionable) and `provider_fetch_error` (runtime failure, transient). Both `warning` severity. (4) `IBKR_FLEX_ENABLED` toggle separates enablement from credentials (`2e76d26f`) — previously ibkr_flex used credential presence as enablement signal, preventing skip detection from distinguishing "missing" from "intentionally disabled". Plan: `SILENT_PROVIDER_FAILURE_PLAN.md`.

### 2026-03-03 — Notification Center Wired to Real Data (Wave 3c / B-018)
Frontend composition hook `useNotifications()` composing `useSmartAlerts()` + `usePendingUpdates()` into `Notification[]` shape for the existing `NotificationCenter` UI component. `alertMappings.ts` maps ~20 backend flag types to human-readable titles + navigation actions. `useNotificationStorage.ts` persists dismissed/read IDs to localStorage. Session-only dismissal for pending update notifications. Backend fix: `_build_alert_id()` for alert ID uniqueness (`ticker || provider || sector || 'portfolio'`). Removed hardcoded mock notifications from `ModernDashboardApp.tsx`. Verified in Chrome: 5 real alerts render with correct titles, severity colors, action buttons navigate to correct views. Commits `1505c1f1` (implementation), `d0c2cb22` (plan). Plan: `NOTIFICATION_CENTER_WIRING_PLAN.md`.

### 2026-03-03 — Provider Routing Gaps (6 Findings) — All Closed
All 6 gaps from audit (`completed/PROVIDER_ROUTING_AUDIT.md`) fixed. 2 behavioral: transaction `is_provider_available()` guard (Schwab/IBKR Flex), `account` filter on `fetch_transactions_for_source()` with `_filter_provider_payload_for_account()` helper (correct per-provider field names). 4 documentation: `owns_account()` ephemeral docstring, `_resolve_native_account()` directional-vs-bidirectional comment, position direct-first comment, IBKR position provider comment. 3 new tests. Commit `66e85369`. Plan: `PROVIDER_ROUTING_GAPS_FIX_PLAN.md`.

### 2026-03-03 — Institution-Based Realized Performance Routing (Already Working)
Investigated and confirmed: `get_performance(institution="merrill", mode="realized")` already works end-to-end. `INSTITUTION_SLUG_ALIASES` covers all Merrill variants. `resolve_providers_for_institution("merrill")` correctly falls back to default aggregators (snaptrade+plaid) since Merrill has no direct provider — this is by design, not a gap. Two-stage filtering (provider-level narrowing + row-level `match_institution`) handles all cases. `source` param already defaults to "all", making it an internal detail. No code changes needed.

### 2026-03-03 — Plaid CUSIP → Bond Pricing Chain Fix
Wired `PlaidSecurity.cusip`/`isin` into `contract_identity` for bonds in Plaid normalizer, connecting to existing IBKR bond pricing chain (FMP→IBKR fallback via `resolve_bond_contract()`). Fixed `_infer_plaid_instrument_type()` metadata-first ordering so bonds aren't blocked by UNKNOWN early return. 8 new tests (20 total in test_plaid.py). Commit `2baba27f`. Plan: `PLAID_CUSIP_BOND_PRICING_PLAN.md`.

### 2026-03-03 — Account Alias Resolution Fix
Canonical account alias resolution across all 7 matching sites. `resolve_account_aliases()` builds equivalence classes from `TRADE_ACCOUNT_MAP` (UUID↔U-number). Shared `match_account()` in `providers/routing_config.py`. Fixes `_discover_account_ids` to merge aliased accounts. 18 new tests. Commit `f1161d0b`. Plan: `ACCOUNT_ALIAS_RESOLUTION_PLAN.md`.

### 2026-03-02 — Live Options Pricing (3 Phases)
Live IBKR bid/ask/mid surfaced in strategy + chain tools. Phase 1: `LegAnalysis` market price fields, `net_market_premium` property, agent snapshot + summary. Phase 2: `pricing_by_strike` in chain output, `atm_pricing` summary, `wide_atm_spread` flag. Phase 3: `underlying_price` optional in `preview_option_trade` with auto-fetch. 16 new tests (79 total). Commit `3ed26f80`. Plan: `LIVE_OPTIONS_PRICING_PLAN.md`.

### 2026-03-02 — Frontend: Dashboard Cards Wiring (Wave 1)
Fixed 6 dashboard metric cards showing fake hardcoded values. Three frontend fixes + backend `refresh_portfolio_prices()`. Commits: `d1e2b665`, `efb83229`, `b61658eb`, `17e1ee59`. Plans: `DASHBOARD_CARDS_WIRING_PLAN.md`, `PORTFOLIO_PRICING_FIX_PLAN.md`.

### 2026-03-02 — Per-Account Realized Performance Aggregation
Generalized Schwab-only per-account aggregation to any institution. Fixes Merrill/Plaid cross-source exclusion. Commit `af30d415`. Plan: `PER_ACCOUNT_AGGREGATION_PLAN.md`.

### 2026-03-02 — IBKR Package: Connection Infrastructure (4 phases)
Option snapshot fix, config centralization + structured logging, ephemeral connection mode, MCP diagnostics. Plans: `IBKR_CONNECTION_FIXES_PLAN.md`, `IBKR_CONFIG_LOGGING_PLAN.md`, `IBKR_EPHEMERAL_CONNECTION_PLAN.md`.

### 2026-03-02 — IBKR Trading: Ephemeral Connection Migration
`IBKRBrokerAdapter` migrated to ephemeral `_connected()` context manager. Commit `385c4787`. Plan: `IBKR_EPHEMERAL_TRADING_PLAN.md`.

### 2026-03-02 — IBKR Direct Trading via IB Gateway
Connection singleton fix + `TRADE_ROUTING`/`TRADE_ACCOUNT_MAP`. Commits `ab8bff60`, `8a20f4b8`. Plan: `IBKR_DIRECT_TRADING_PLAN.md`.

### 2026-03-01 — Frontend: Package Formalization + Component Data Wiring (3 phases)
Package formalization, data wiring audit (9/9 containers wired), backend data enrichment (7 items). Audit: `completed/FRONTEND_DATA_WIRING_AUDIT.md`.

### 2026-03-01 — Frontend: Block Component Refactoring (3 waves)
5 block components across 9 views. Commits: `9506643d`, `93e5ed9e`, `750dea25`. Plan: `FRONTEND_BLOCK_REFACTOR_PLAN.md`.

### 2026-03-01 — Frontend: TypeScript Cleanup
16 TS errors→0, `no-explicit-any` 590→0, `as any` 180→5, lint warnings 704→114. Plan: `FRONTEND_TYPESCRIPT_CLEANUP_PLAN.md`.

### 2026-03-01 — Performance: Short Portfolio Return History Fix
Fixed `compute_portfolio_returns()` truncation. Added `compute_portfolio_returns_partial()`. Plan: `PORTFOLIO_RETURN_HISTORY_FIX_PLAN.md`.

### 2026-03-01 — Trading Analysis: Date Range Parameters
Added `start_date`/`end_date` to `get_trading_analysis()`. Commit `5919122e`. Plan: `TRADING_DATE_RANGE_PLAN.md`.

### 2026-03-01 — Target Allocations: DB Migration + MCP Set/Get Tools
Write path complete. 12 tests. Commit `55967d7b`. Plan: `TARGET_ALLOCATIONS_PLAN.md`.

### 2026-03-01 — Architecture: Fix Circular Imports in app.py
Extracted rate limiter to `utils/rate_limiter.py`. Commit `5c4d3995`. Plan: `CIRCULAR_IMPORT_FIX_PLAN.md`.

### 2026-03-01 — Frontend: SDK Testing (Phase 1+2)
75 Vitest tests across 8 files. Plan: `FRONTEND_SDK_TESTING_PLAN.md`.

### 2026-03-01 — Frontend: Analyst Mode
Chat-focused UI at `/analyst`. Commit `ea9f2fd3`. Plan: `ANALYST_MODE_PLAN.md`.

### 2026-03-01 — Rebalance Trade Generator
`preview_rebalance_trades()` MCP tool. 26 tests. Commit `e19f9e28`. Plan: `REBALANCE_TRADE_GENERATOR_PLAN.md`.

### 2026-03-01 — Concentration: Leverage-Aware Flag
`leveraged_concentration` flag. 8 new tests. Commit `8741d6ac`. Plan: `LEVERAGED_CONCENTRATION_FLAG_PLAN.md`.

### 2026-03-01 — Workflow Skills (All 7 Complete)
Allocation review, risk review, hedging, scenario analysis, strategy design, stock research, performance review. Plans: `WORKFLOW_SKILLS_PLAN.md`, `WORKFLOW_SKILLS_PHASE4_PLAN.md`, `WORKFLOW_SKILLS_STOCK_RESEARCH_PLAN.md`.

---

### 2026-03-02 — Batch Scenario/Optimization Comparison MCP Tool
New `compare_scenarios()` MCP tool in `mcp_tools/compare.py`. Compares N what-if scenarios or optimization variants side-by-side on the same portfolio. Portfolio loaded once via `_load_portfolio_for_analysis()`, deep-copied per scenario to prevent `ScenarioService` mutation contamination. Two modes: `whatif` (ranks by vol_delta, conc_delta, total_violations, factor_var_delta) and `optimization` (ranks by trades_required, total_violations, hhi, largest_weight_pct). Configurable `rank_by` + `rank_order` with mode-specific allowlists. Deterministic tie-breaking by name. Failed scenarios sort to bottom. 5 comparison-level flags in `core/comparison_flags.py`: clear_winner, marginal_differences, partial_failures, best_has_violations, all_have_violations. Mode-specific risk limit loading (what-if: DB+file fallback; optimization: DB-only). Graceful expected-returns handling (missing fails only max_return scenarios). No changes to existing `run_whatif()` or `run_optimization()`. 32 tests (10 flag + 22 tool incl. behavioral parity). Plan: `docs/planning/completed/BATCH_COMPARISON_PLAN.md` (3 Codex review rounds: R1 FAIL 7 issues, R2 FAIL 3 issues, R3 PASS). Commit: `56d773a8`.

---

### 2026-03-01 — Rebalance Trade Generator MCP Tool
New `preview_rebalance_trades()` MCP tool converts target weights from any source (optimization, what-if, manual) into sequenced BUY/SELL trade legs with share quantities. Sells ordered before buys to free buying power. Two input modes: `target_weights` (absolute) and `weight_changes` (signed deltas). Optional `account_id` filtering (required for `preview=True`). `unmanaged` param controls held positions not in targets (hold/sell). Shared helpers extracted to `mcp_tools/trading_helpers.py` from `basket_trading.py`. Three-layer agent format: `RebalanceLeg`/`RebalanceTradeResult` → `generate_rebalance_flags(snapshot)` (9 flags) → `_build_agent_response()`. 26 tests (10 flag + 16 MCP). Plan: `docs/planning/completed/REBALANCE_TRADE_GENERATOR_PLAN.md` (4 Codex review rounds). Commits: `d0e1e72a` (plan), `a61f6a3d` (plan fix), `e19f9e28` (implementation).

### 2026-03-01 — Workflow Design Phase 1: All 7 Workflows Defined
Audited all 7 frontend views and defined complete 5-step workflows with tool mappings, inputs/outputs, and gap analysis. Design doc: `docs/planning/WORKFLOW_DESIGN.md` (2,457 lines). Workflows: Hedging, Scenario Analysis, Allocation Review, Risk Review, Performance Review, Stock Research, Strategy Design. Cross-cutting gaps identified: rebalance trade generator (all 7), batch comparison (3), action audit trail (3). Workflow-specific gaps catalogued (templates, backtesting, attribution, frontier, versioning). Commits: `5df192f2` through `92f99987`.

### 2026-03-01 — Trading Analysis: Date Range Parameters
Added `start_date`/`end_date` to `get_trading_analysis()` MCP tool. FIFO runs on full history, results filtered post-analysis. Income pre-filtered. Aggregates recomputed; grades/behavioral/return-stats nulled for partial windows. 33 tests. Commit `5919122e`.
See: `docs/planning/completed/TRADING_DATE_RANGE_PLAN.md`

### Earnings Estimates: Investigate Collection Failures — COMPLETE (2026-03-01)
Investigated 142 failures from first snapshot run. Breakdown: `no_estimates` 136 records (95 tickers — warrants, preferred shares, Toronto-listed, micro-caps with no analyst coverage), `no_income_statement` 6 records (6 tickers). Zero `api_error` — infra healthy. All failures benign, no systemic bugs or ticker format issues. 2.9% failure rate out of 4,880 tracked tickers.

Implemented skip-list: `get_skip_set()` on `EstimateStore` queries `collection_failures` for tickers failing 2+ runs with persistent error types, within 180-day decay window. Wired into `run_collection()` after universe build, before freshness check. CLI flags: `--ignore-skip-list`, `--skip-min-runs`. Stored `universe_snapshot` NOT modified (auditability). Tests: 6 passing. Plan: `docs/planning/completed/ESTIMATE_SKIP_LIST_PLAN.md`. Codex review: R1 FAIL, R2 FAIL, R3 PASS. Commits: `5b8268d` (edgar_updater), `6f14ceb6` (risk_module sync).

---

### 2026-03-01 — Options Portfolio Risk Integration (Phases 1-2)
Option position enrichment + portfolio Greeks aggregation. `enrich_option_positions()` adds contract metadata (strike, expiry, underlying, DTE) to option positions at 3 call sites. `compute_portfolio_greeks()` aggregates dollar-scaled delta/gamma/theta/vega across all option positions, wired into `get_exposure_snapshot()`. 3 position flags (near_expiry, expired, concentration) + 4 Greeks flags (theta_drain, net_delta, high_vega, computation_failures). IBKR live Greeks path deferred. 76 tests. Commit `6e62c5d6`.
See: `docs/planning/completed/OPTIONS_PORTFOLIO_RISK_PLAN.md`

### 2026-03-01 — Environment Variable & Config Consolidation
Removed redundant `load_dotenv()` from 4 library modules, eliminated duplicate IBKR env var reads in `brokerage/config.py` (now imports from `ibkr/config.py`), deleted 12 dead Schwab/SnapTrade credential vars from `settings.py`, moved `FRONTEND_BASE_URL` to single source, standardized `ibkr/server.py` override semantics, fixed frontend `VITE_API_BASE_URL` → `VITE_API_URL` naming mismatch. 16 files, 2084 tests passing. Commit `def8fd3f`.
See: `docs/planning/completed/ENV_CONFIG_CONSOLIDATION_PLAN.md`

### 2026-02-28 — Realized Performance: Bond/Treasury Pricing via CUSIP
Security identifiers (CUSIP/ISIN/FIGI) captured and threaded into `PortfolioData.security_identifiers`. `resolve_bond_contract()` extended with CUSIP fallback. CUSIP → IBKR conId resolver via `reqContractDetails()` + `secIdList` matching. Live-tested: CUSIP 912810EW4 → conId 15960420 → 7 monthly closes. US Treasury bonds supported (prefix 912 → symbol US-T). Corporate bonds deferred. 18 new tests.
See: `docs/planning/completed/BOND_PRICING_CUSIP_RESOLVER_PLAN.md`, `docs/planning/completed/BOND_CUSIP_REQCONTRACTDETAILS_PLAN.md`

### 2026-02-28 — Futures Phase 7: Contract Verification (ESTX50, DAX)
Live-tested ESTX50 and DAX against TWS (port 7496). Both resolve, qualify, and return monthly close data. ESTX50 priced via FMP `^STOXX50E`; DAX via IBKR fallback (`^GDAXI` returns 402). IBV removed from catalog — no CME Ibovespa futures product found on IBKR (27→26 contracts). Added repeatable verification runbook.
See: `docs/reference/FUTURES_CONTRACT_VERIFICATION.md`, `docs/planning/FUTURES_DESIGN.md`

### 2026-02-28 — Schwab Per-Account Realized Performance Aggregation
Per-account aggregation for Schwab realized performance. Investigation + implementation. Commit `8ce1a340`.
See: `docs/planning/completed/SCHWAB_ACCOUNT_AGGREGATION_PLAN.md`

### 2026-02-28 — P4 Hedging Strategies (Frontend Wiring)
Frontend hedging tab wired to backend `portfolio-recommendations` endpoint. `useHedgingRecommendations` hook + `HedgingAdapter` + container wiring. Backend fixes: ETF→sector label resolution, correlation threshold adjustment, driver label resolution. Commits `1c66dae7`, `475a67e5`.
See: `docs/planning/completed/FRONTEND_HEDGING_WIRING_PLAN.md`

### 2026-02-28 — Futures Phase 5: Performance + Trading
Futures P&L metadata threading + segment filter on `get_trading_analysis()`. Commits `a5f82977`, `0a7b2691`.
See: `docs/planning/FUTURES_DESIGN.md`

### 2026-02-28 — Earnings Estimates: AWS Migration Complete (All 9 Steps)
All 9 steps done. Local fallback removed (`7d9dab24`), HTTP-only with hardcoded default URL. EC2 systemd timer active. fmp-mcp 0.2.0 on PyPI. Commit `08febe10`.
See: `docs/planning/completed/EARNINGS_ESTIMATE_AWS_MIGRATION_PLAN.md`, `docs/planning/completed/ESTIMATE_CLEANUP_PLAN.md`

### 2026-02-27 — Stock Basket / Custom Index (All 5 Phases Complete)
Full basket feature: CRUD, analysis, custom factor injection, multi-leg trading, and ETF seeding.
- Phase 1: CRUD MCP tools — `create_basket`, `list_baskets`, `get_basket`, `update_basket`, `delete_basket` (commit `39930617`)
- Phase 2: Basket returns analysis — `analyze_basket` with Sharpe, drawdown, alpha/beta, component attribution, portfolio correlation (commit `240f00ea`)
- Phase 3: Basket as custom factor — inject into `get_factor_analysis()` alongside standard factors (commit `509326b0`)
- Phase 4: Multi-leg trade execution — `preview_basket_trade`, `execute_basket_trade` (commit `7b3b78c2`)
- Phase 5: ETF seeding — `create_basket_from_etf` from FMP holdings (commit `4d98b43d`)
See: `docs/planning/completed/STOCK_BASKET_PLAN.md`

### 2026-02-27 — Option Chain Analysis MCP Tool
`analyze_option_chain` on portfolio-mcp. Exposes OI/volume concentration, put/call ratio, max pain via live IBKR chain data. Raw-dict agent format with 9 interpretive flags. 19 tests, 53 total options tests. Codex-reviewed plan (2 rounds, 8/8 PASS).
See: `docs/planning/completed/OPTION_CHAIN_MCP_PLAN.md`

### 2026-02-27 — MCP Positions Enrichment (P1-MCP)
Added sector breakdown, P&L summary, enriched top holdings, and 4 new flags to `get_positions(format="agent")`. Reuses holdings enrichment `to_monitor_view()` + `enrich_positions_with_sectors()`. Commit `d37bcdbc`.
See: `docs/planning/completed/MCP_POSITIONS_ENRICHMENT_PLAN.md`

### 2026-02-27 — Futures Phase 3: Portfolio Integration
Futures in holdings view with margin + notional overlay. Commit `dcf481a0`.
See: `docs/planning/FUTURES_DESIGN.md`

### 2026-02-27 — Futures Phase 4: Risk Integration
Notional weights, proxy factors (macro/asset-class instead of equity), segment view. Commit `a1c4aefc`.
See: `docs/planning/FUTURES_DESIGN.md`

### 2026-02-27 — Earnings Estimates: AWS Migration Steps 1-8
RDS created, estimates package, API routes, systemd timer, MCP HTTP migration, data migrated (59,546 snapshots), deployment scripts, API live + fmp-mcp 0.2.0 on PyPI. Only Step 9 cleanup remaining.
See: `docs/planning/completed/EARNINGS_ESTIMATE_AWS_MIGRATION_PLAN.md`

### 2026-02-27 — Options Tools: Core Module
Full `options/` package with `OptionLeg`/`OptionStrategy` class framework, payoff calculator (max profit/loss, breakevens, P&L at various DTE), Greeks computation, and `analyze_option_strategy` MCP tool with `format="agent"` support. Remaining: IBKR OI integration, IBKR chains/Greeks as data source, portfolio risk integration.

### 2026-02-27 — Architecture: Pricing Provider Pluggability Review
Completed the pricing provider refactor plan across equity/general pricing paths. Legacy `PriceProvider` now delegates to registry-backed providers, FX routing goes through `get_fx_provider()`, scattered `fmp.fx` pricing-path imports were reduced, and provider integration tests were added for registry custom-provider handling, `set_price_provider()` override behavior, and `data_loader.fetch_monthly_close()` registry flow.
See: `PRICING_PROVIDER_REFACTOR_PLAN.md`

### 2026-02-27 — Futures Phase 2: Pricing Dispatch + Pluggable Pricing Chain
Decoupled contract catalog from IBKR into `brokerage/futures/contracts.yaml` (27 contracts). Built pluggable `FuturesPricingChain` protocol with broker-agnostic `alt_symbol` parameter — default chain: FMP commodity endpoints → IBKR historical data fallback. Added futures dispatch to `latest_price()` and `get_returns_dataframe()` via `instrument_types` dict. Threaded `instrument_types` through ~20 call sites (config_adapters, optimization, performance, risk score, scenario, portfolio_optimizer full chain, portfolio_service special case, factor_intelligence). Second pass in `to_portfolio_data()` populates `fmp_ticker_map` from contract specs. Slimmed `ibkr/exchange_mappings.yaml` (removed multiplier/tick_size/fmp mapping). Live tested: ES $6,874.75, GC $5,257.40 via FMP. 11/27 FMP symbols working (rest 402 — IBKR fallback). 56 new tests, 1943 total passing. Codex-reviewed plan (18 rounds).
See: `docs/planning/completed/FUTURES_P2_PRICING_DISPATCH_PLAN.md`, `docs/planning/FUTURES_DESIGN.md`

### 2026-02-26 — Futures Phase 1: Data Foundation
Created `brokerage/futures/` package with `FuturesContractSpec` frozen dataclass (27 contracts), notional/P&L/tick value calculations, and asset class taxonomy (equity_index, fixed_income, metals, energy). Extended `ibkr/exchange_mappings.yaml` with multiplier + tick_size. Added `get_ibkr_futures_contract_meta()` to `ibkr/compat.py` (backward compatible). 34 new tests, 1814 total passing. Codex-reviewed plan (2 rounds, 3 spec corrections: IBV, DAX, ZT).
See: `docs/planning/completed/FUTURES_P1_DATA_FOUNDATION_PLAN.md`, `docs/planning/FUTURES_DESIGN.md`

### 2026-02-26 — Security Identifier Capture + Currency Classification
Captured CUSIP/ISIN from Plaid, CUSIP from Schwab, FIGI from SnapTrade — threaded through PositionService consolidation into new `PortfolioData.security_identifiers` field. Added explicit CUR:XXX → cash detection in SecurityTypeService `get_security_types()` and `get_asset_classes()`. Extended `to_portfolio_data()` is_cash check to honor provider `is_cash_equivalent` flag. Bond positions now log available identifiers. 1794 tests passing. Codex-reviewed plan (3 rounds).
See: `docs/planning/completed/SECURITY_IDENTIFIERS_PLAN.md`

### 2026-02-25 — Architecture: MCP Error Handling Decorator
Extracted shared `@handle_mcp_errors` decorator into `mcp_tools/common.py`. Applied to 20 tool functions across 12 files, removing ~200 lines of duplicated stdout-redirect + try/except boilerplate. 603 tests passing.
See: `docs/planning/completed/MCP_ERROR_DECORATOR_PLAN.md`

### 2026-02-25 — Architecture: Break Up result_objects.py
Converted `core/result_objects.py` (355KB) into `core/result_objects/` package with 10 domain submodules + `__init__.py` re-exports (commit `3758c186`).

### 2026-02-25 — Architecture: Consolidate Config Files
Extracted cohesive groups from `settings.py` (853→454 lines) into natural package homes with backward-compatible re-exports. Phase 1: user resolution → `utils/user_context.py`. Phase 2: routing tables → `providers/routing_config.py`. Phase 3: IBKR gateway vars re-exported from `ibkr/config.py`. No cross-package coupling. 3 Codex review rounds.
See: `docs/planning/completed/CONFIG_CONSOLIDATION_PLAN.md`

### 2026-02-25 — Architecture: Clarify IBKR Dual Entry Points
`ibkr/client.py` (facade for data) vs `brokerage/ibkr/adapter.py` (trade execution) confirmed as architecturally correct. Added adapter docstring cross-reference and removed dead shim `services/ibkr_broker_adapter.py`.
See: `docs/planning/completed/IBKR_DUAL_ENTRY_CLEANUP_PLAN.md`

### 2026-02-25 — Gateway Channel Integration (All Phases Complete)
Full gateway channel migration across both repos. Risk-module: backend proxy + frontend wiring (Phase 0+3). AI-excel-addin: portfolio-mcp allowlist, channel filtering, prompt awareness (Phases 1-2), AgentRunner sole chat path cutover (Phase 4).
See: `docs/planning/completed/portfolio-channel-task.md`, `docs/design/portfolio-tool-parity.md`

### 2026-02-25 — Surface IBKR TWS Connection Status + Graceful Provider Auth Failures
Implemented in `8a38713a`. Provider status surfaced in both positions and performance agent responses. IBKR pricing degradation detected via `IBKR_PRICING_REASON_CODES`. Per-provider try/except in `get_all_positions()`, errors in `_cache_metadata`, `provider_error` flags in `position_flags.py`, `provider_status` dict in agent responses.
See: `docs/planning/completed/PROVIDER_STATUS_PLAN.md`

### 2026-02-25 — Gateway Channel Integration Phase 0+3
Backend proxy (`routes/gateway_proxy.py`) + frontend `GatewayClaudeService` for web-channel chat through the shared AI gateway. Per-user session stickiness, SSE passthrough, stream locking, 401 token refresh, tool-approval flow (approve/deny banner in ChatCore). Feature flag `VITE_CHAT_BACKEND=legacy|gateway` for coexistence. Parity audit: 10/16 legacy tools mapped, 6 intentionally dropped, 0 gaps. 11 unit tests, live end-to-end verified.
See: `docs/planning/completed/portfolio-channel-task.md`, `docs/design/portfolio-tool-parity.md`

### 2026-02-25 — All 7 Agent Format Tools Live-Tested
Live-tested all 7 `format="agent"` tools against real portfolio data: `get_positions`, `get_performance`, `get_trading_analysis`, `analyze_stock`, `run_optimization`, `run_whatif`, `get_factor_analysis`. All returning structured snapshots + flags. MCP agent audit updated — all HIGH+MEDIUM priority tools now grade A.
See: `docs/planning/completed/MCP_AGENT_AUDIT.md`

### 2026-02-25 — Agent-Optimized Factor Analysis Output
Added `format="agent"` + `output="file"` to `get_factor_analysis()`. Three-layer architecture across all 3 analysis modes. Interpretive flags in `core/factor_flags.py` dispatch by `analysis_type`. 21 Codex review rounds, 90 new tests.
See: `docs/planning/completed/FACTOR_ANALYSIS_AGENT_FORMAT_PLAN.md`

### 2026-02-25 — Agent-Optimized What-If Output
Added `format="agent"` + `output="file"` to `run_whatif()`. Three-layer architecture: `get_agent_snapshot()` on `WhatIfResult` → `core/whatif_flags.py`. 5 Codex review rounds, 64 new tests.
See: `docs/planning/completed/WHATIF_AGENT_FORMAT_PLAN.md`

### 2026-02-25 — Agent-Optimized Optimization Output
Added `format="agent"` + `output="file"` to `run_optimization()`. Three-layer architecture: `get_agent_snapshot()` on `PortfolioOptimizationResult` → `core/optimization_flags.py`. 7 Codex review rounds, 51 new tests.
See: `docs/planning/completed/OPTIMIZATION_AGENT_FORMAT_PLAN.md`

### 2026-02-25 — Factor Performance Double-Scaling Bug Fix
Fixed `FactorPerformanceResult.get_agent_snapshot()` double-scaling `annual_return_pct` and `volatility_pct`. Upstream `compute_performance_metrics()` already returns values in percent. 2 tests updated.

### 2026-02-24 — NaN → null in Agent JSON Output
Fixed `make_json_safe()` in `utils/serialization.py` to coerce `float('nan')` and `np.float64('nan')` to `None`. All callers of `make_json_safe` benefit from the fix.

### 2026-02-24 — Frontend Logging Overhaul
Overhauled frontend logging system (`frontendLogger.ts`). JWT token sanitization, EventBus/UnifiedAdapterCache suppression (~43% noise removed), React StrictMode dedup, silent cache warming, semantic data summaries, session summaries via `sendBeacon`, error context enrichment, data truncation. 7 files changed, ~60-70% log volume reduction.
See: `docs/planning/completed/FRONTEND_LOGGING_PLAN.md`

### 2026-02-24 — Agent-Optimized Performance Output
Added `format="agent"` + `output="file"` to `get_performance()`. 12 interpretive flags in `core/performance_flags.py`. Also fixed pre-existing `_categorize_performance()` bug. 10 Codex review rounds, 43 new tests.
See: `docs/planning/completed/PERFORMANCE_AGENT_FORMAT_PLAN.md`

### 2026-02-24 — Agent-Optimized Positions Output
Added `format="agent"` + `output="file"` to `get_positions()`. Interpretive flags in `core/position_flags.py`. 4 Codex review rounds. Also created MCP agent audit doc.
See: `docs/planning/completed/POSITIONS_AGENT_FORMAT_PLAN.md`, `docs/planning/completed/MCP_AGENT_AUDIT.md`

### 2026-02-24 — Plaid Re-Authentication via Link Update Mode
Full re-auth flow for expired Plaid OAuth connections (`ITEM_LOGIN_REQUIRED`). Backend, frontend, CLI, DB migration. 9 Codex review rounds, tested end-to-end.
See: `docs/planning/completed/PLAID_REAUTH_PLAN.md`

### 2026-02-24 — Frontend Three-Package Split
Split frontend monolith into pnpm workspace with three packages: `@risk/chassis`, `@risk/connectors`, `@risk/ui`. Includes CRA → Vite migration, 32 wrapper shim cleanup, ESLint standalone config migration, render bug fix, ticker validation fix. 400 files changed.
See: `docs/planning/completed/FRONTEND_PACKAGE_SPLIT_PLAN.md`, `docs/planning/completed/FRONTEND_WRAPPER_CLEANUP_PLAN.md`

### 2026-02-23 — Brokerage Package Extraction
Extracted pure broker API layer into standalone `brokerage/` package. Three-layer split. 1143 tests passing, live smoke tests verified.
See: `docs/planning/completed/BROKERAGE_CONNECT_PLAN.md`

### 2026-02-19 — Plaid/SnapTrade Cost Reduction
Full webhook-driven refresh notification pipeline. Phases 1-5+7 complete. Only remaining: deploy SnapTrade relay route (Phase 6 infra — see `WEBHOOK_RELAY_SETUP.md`).
See: `docs/planning/completed/PLAID_COST_REDUCTION_PLAN.md`, `docs/planning/completed/WEBHOOK_REFRESH_NOTIFICATION_PLAN.md`

### 2026-02-19 — Logging System Overhaul
Rewrote logging from 2,208 to 856 lines. 104 files changed, -4,327 net lines.
See: `docs/planning/completed/LOGGING_OVERHAUL_PLAN.md`

### 2026-02-18 — Risk Preferences Config Layer
Moved from baked-in limits to preferences-first model. User intent stored as first-class config, limits derived at analysis time.

### 2026-02-18 — RiskAnalysisResult Redundancy Cleanup
Removed `risk_checks`, `beta_checks`, and nested `industry_variance` from `to_api_response()`.
See: `docs/planning/completed/RISK_ANALYSIS_RESULT_CLEANUP_PLAN.md`

### 2026-02-18 — Profile-Based Risk Limits
Added 4 risk profiles with `set_risk_profile()` and `get_risk_profile()` MCP tools.
See: `docs/planning/completed/RISK_LIMITS_PROFILE_PLAN.md`

### 2026-02-18 — Agent-Optimized Risk Analysis Output
Implemented `format="agent"` + `output="file"` for `get_risk_analysis()`.
See: `docs/planning/completed/RISK_ANALYSIS_AGENT_FORMAT_PLAN.md`

### 2026-02-17 — Interface Documentation Debt Cleanup
Cleared stale MCP tool count references, documented OpenAPI and CI posture.
See: `docs/interfaces/README.md`, `docs/interfaces/mcp.md`, `docs/interfaces/test-matrix.md`

### 2026-02-17 — Provider-Native Flows: Plaid, SnapTrade, IBKR
Extended provider-native flows to all remaining providers. Coverage gating and validation complete.
See: `docs/planning/completed/PROVIDER_NATIVE_FLOWS_EXPANSION_IMPLEMENTATION_PLAN.md`

### 2026-03-04 — Frontend Cleanup P4+P5: Dead Code & Stale Comments
Removed dead code (unused props in RiskAnalysis/StockLookup, `animationEnabled` in PerformanceView) and stale comments (13 header TODOs in HoldingsView, 164-line ASCII header in RiskAnalysis, 70-line header in StockLookup, mock data block in StrategyBuilder, 8 "Coming Soon" locations in ScenarioAnalysis, misleading "Excel Workbook" label in PerformanceView). -501 lines across 6 files. Commit `396da1c3`. Plan: `FRONTEND_CLEANUP_P4P5_PLAN.md`.

### 2026-02-17 — Schwab Dividend Description → Ticker Resolution (Bug 23)
Fixed unresolved ENB dividends ($612).
See: `docs/planning/completed/SCHWAB_DIVIDEND_RESOLUTION_PLAN.md`

### 2026-02-17 — Portfolio Manager Complexity Audit + Refactor (Phase 1)
Extracted repository, assembler, and legacy file helper services. PortfolioManager is now a thin facade.
See: `docs/planning/completed/PORTFOLIO_MANAGER_COMPLEXITY_AUDIT.md`

# Factor Intelligence – Phased Implementation Plan (AI‑Friendly)

> **Status:** ✅ Backend complete (PRs 0–8 all implemented). PR 9 (docs) partially done. PR 10 (frontend) not started.

This document turns the approved Factor Intelligence design into a clear, phased execution plan optimized for small PRs, high testability, and AI assist.

## Goals
- Deliver segmented factor intelligence (matrices, overlays, performance) without disrupting existing flows.
- Keep performance predictable for ~25 ETFs + macro groups via caching and curated views.
- Maintain DB‑first reference data with YAML fallback and admin tooling for ops.

## Scope Summary (Already Agreed in Design)
- Per‑category correlation matrices: industry/style/market/fixed_income/cash/commodity/crypto.
- Overlays: rate_sensitivity (ETF ↔ Δy), market_sensitivity (ETF ↔ benchmarks).
- Performance profiles: per‑ETF + composite performance (macro and per‑category).
- Macro matrices: macro_composite_matrix (default on) and macro_etf_matrix (opt‑in, curated top‑N per group). 
- Industry granularity: group (DB‑first `industry_proxies.sector_group`), industry, subindustry. No ETF inference.
- Asset ETF proxies: DB‑first `asset_etf_proxies` with YAML fallback + admin sync.
- Lifecycle & stability: rolling windows (optional), stale factor detection, moving end date in prod.

## Phase Plan (Small, Testable PRs)

Prerequisites
- SlowAPI is already referenced in `app.py` and declared in `requirements.txt` (slowapi>=0.1.9). Verify the runtime environment has it installed; if your deploy uses a separate lockfile, ensure it includes SlowAPI.

### PR 0 — Migrations + DB Client (1–2 days) ✅
- Migrations
  - `20250901_add_asset_etf_proxies.sql`: Create canonical asset‑class→ETF proxy catalog (idempotent).
    - Schema (idempotent, with indexes):
      ```sql
      CREATE TABLE IF NOT EXISTS asset_etf_proxies (
          id SERIAL PRIMARY KEY,
          asset_class VARCHAR(50) NOT NULL,   -- 'fixed_income', 'commodity', 'crypto', etc.
          proxy_key   VARCHAR(100) NOT NULL,  -- e.g., 'UST10Y', 'gold', 'BTC'
          etf_ticker  VARCHAR(20) NOT NULL,   -- canonical ETF ticker
          is_canonical BOOLEAN DEFAULT TRUE,  -- allow alternates with lower priority
          priority    INT DEFAULT 100,        -- lower number = higher priority
          description TEXT,
          updated_at  TIMESTAMP DEFAULT NOW(),
          UNIQUE(asset_class, proxy_key, etf_ticker)
      );

      CREATE INDEX IF NOT EXISTS idx_asset_etf_proxies_class ON asset_etf_proxies(asset_class);
      CREATE INDEX IF NOT EXISTS idx_asset_etf_proxies_priority ON asset_etf_proxies(asset_class, priority);
      ```
  - `20250902_alter_industry_proxies_add_sector_group.sql`: add `sector_group` to `industry_proxies` + index.
- DatabaseClient
  - Add `get_asset_etf_proxies() -> Dict[str, Dict[str, str]]` (canonical only): returns `{asset_class: {proxy_key: etf_ticker}}` ordered by priority.
  - Add `upsert_asset_etf_proxy(asset_class, proxy_key, etf_ticker, is_canonical=True, priority=100, description=None)` with `ON CONFLICT` upsert and validation against `core.constants.VALID_ASSET_CLASSES`.
  - Extend `update_industry_proxy(..., asset_class=None, sector_group=None)` to upsert `sector_group`.
- YAML fallback
  - Add `asset_etf_proxies.yaml` (root) with sections for asset classes whose keys MATCH `core/constants.VALID_ASSET_CLASSES` (use `bond`, not `fixed_income`) → used by loaders when DB unavailable.
- Admin tools
  - `manage_reference_data.py`: add `asset-proxy` commands (list/add/sync-from-yaml/export); extend `industry add ... --group`.
  - `migrate_reference_data.py`: `migrate_asset_etf_proxies()`; extend `migrate_industry_mappings()` to upsert `sector_group` when `group:` exists.
- DoD
  - Migrations are idempotent and create indexes.
  - DB client: `get_asset_etf_proxies()` and `upsert_asset_etf_proxy(...)` smoke‑tested.
  - YAML fallback present and admin commands can list/add/sync/export.
  - Industry upsert with `sector_group` works.

Quick test
- Run migration: `python database/run_migration.py` and verify new tables/columns exist.
- Shell smoke: start Python REPL, create `DatabaseClient` and call `get_asset_etf_proxies()` (should return dict or empty), then `upsert_asset_etf_proxy('fixed_income','UST2Y','SHY')` and re‑read.
- Industry upsert: set `sector_group='defensive'` for a test industry and verify via a SELECT.

Example verification SQL
```sql
-- Validate table exists and indexes are present
\d+ asset_etf_proxies;

-- After upsert, confirm canonical row
SELECT * FROM asset_etf_proxies WHERE asset_class='fixed_income' AND proxy_key='UST2Y';
```

### PR 1 — Core Engine: Returns Panel + Caching Scaffold (2–3 days) ✅
- Build aligned monthly returns panel (prefer total‑return; fallback to close). Enforce min‑obs from settings.
- **Global caching**: Add `@functools.lru_cache(maxsize=DATA_LOADER_LRU_SIZE)` decorators to core data fetching functions (`build_factor_returns_panel()`, `fetch_factor_universe()`) for shared market data caching across all users.
- **Core functions to implement** (see ENGINE_DESIGN for detailed implementations):
  - `fetch_factor_universe()`: Load ETF universe from DB + YAML, categorized by asset class (include 'cash' via cash_proxies for macro composites; exclude from per‑category matrices/overlays).
  - `build_factor_returns_panel()`: Build aligned monthly returns matrix with parallel ETF data loading
  - Helpers: `load_asset_class_proxies()` (DB‑first → YAML → hardcoded) and `load_industry_buckets()` (DB‑first sector_group map) with LRU caching.
  - DatabaseClient: add `get_cash_proxies()` returning `{currency: proxy_etf}`; universe builder uses the set of distinct ETF proxies for 'cash' category.
- Cache key: `f"factor_returns_panel_{universe_hash}_{start_date}_{end_date}_{total_return_flag}"`; consider `price_data_version` later.
- Universe hash determinism: build the universe deterministically (sort by category, then ticker), include category membership in the hash inputs, and emit the final `universe_hash` in `analysis_metadata` to avoid cache churn and ease debugging.
- Record `returns_panel_build_ms` in `analysis_metadata.performance`.
- DoD: alignment + min‑obs unit tests; cache rebuild on key change.

Quick test
- Python REPL: `universe = fetch_factor_universe()`; confirm essential categories exist.
- `panel = build_factor_returns_panel(universe, '2019-01-01', '2024-12-31')`; print shape and confirm columns > 0 and index monotonic increasing monthly.
- Print `panel._factor_intelligence_metadata` and confirm `returns_panel_build_ms` and `universe_hash` present.

### PR 2 — Per‑Category Matrices + Industry Granularity (3–4 days) ✅
- Correlation matrices for industry/style/market/fixed_income/cash/commodity/crypto.
- Industry granularity
  - `industry_granularity='group'`: build group composites from member industry ETF returns (equal‑weight default) using `industry_proxies.sector_group` when present; otherwise leave entry at industry.
  - `industry` / `subindustry`: render at requested detail.
- Data quality: exclusions, counts, coverage per category.
- DoD: snapshot + property tests (symmetry, range); coverage shown in `data_quality`.

Quick test
- Service or notebook: compute matrices for `industry` and `style`; assert matrix is square, symmetric, and values in [-1, 1].
- If `industry_granularity='group'`, verify group labels appear and industry count decreases.

### PR 3 — Sensitivity Overlays (Rate + Market) (2–3 days) ✅
- rate_sensitivity: corr(ETF returns, Δy maturities) with defaults from `RATE_FACTOR_CONFIG`.
- market_sensitivity: corr(ETF returns, benchmarks; exclude ‘market’ category and skip ETFs used as benchmarks). Default benchmarks=['SPY'] with optional ACWX/EEM.
- Optional rolling summaries hooks (flags only for now).
- DoD: unit + snapshot tests; defaults respected.

Quick test
- Compute `rate_sensitivity` for a few ETFs; check maturities from `RATE_FACTOR_CONFIG` are present and correlations in [-1, 1].
- Compute `market_sensitivity` with benchmarks=['SPY']; ensure entries for non‑benchmark ETFs include 'SPY'.

### PR 4 — Performance Profiles + Composite Performance (3–4 days) ✅
- Per‑ETF profiles: annualized return, volatility, Sharpe, max drawdown, beta_vs_benchmark, dividend_yield.
- Composite performance tables:
  - Macro composites: equity/fixed_income/cash/commodity/crypto.
  - Per‑category composites: industry/style/market.
- Asset‑class aware yield usage: equity/fixed_income/cash considered; commodity/crypto ignored by default. Sanity clamps; `data_quality` for missing yields.
- DoD: snapshot on fixtures; yield logic verified.

Quick test
- Call performance engine for a small universe; verify per‑ETF metrics include `annualized_return`, `volatility`, `sharpe_ratio`, and composites include macro groups.

### PR 5 — Macro Matrices (Composite + Optional ETF) (2–4 days) ✅
- macro_composite_matrix (default on): compact cross‑asset view.
- macro_etf_matrix (opt‑in): curated top‑N per group with `macro_max_per_group`, `macro_deduplicate_threshold`, `macro_min_group_coverage_pct`.
- Fallback to composites when budget exceeded; record in `data_quality`.
- Settings: add centralized defaults in `settings.py` for `macro_max_per_group`, `macro_deduplicate_threshold`, and `macro_min_group_coverage_pct` with clear docstrings.
- DoD: size controlled, de‑dup applied; coverage reported; settings wired and testable.

Quick test
- Generate macro_composite_matrix; verify a compact square with expected group labels.
- Enable macro_etf_matrix with `macro_max_per_group=3`; confirm total columns/rows within budget and de‑dup dropped near‑duplicates.

### PR 6 — Service + Router Integration (2–3 days) ✅
- FactorIntelligenceService (ServiceCacheMixin): reuse returns panel cache; per‑section caches; timing/size metrics collection.
- Update `services/service_manager.py`: register `FactorIntelligenceService`, expose cache stats/clearers, and ensure DI points (`get_user_factor_intelligence_service`) align with router usage.
- /routes/factor_intelligence.py
  - POST /correlations: request model with `sections`, `format`, `top_n_per_matrix`, macro params, sensitivities, rolling options, `industry_granularity`.
  - POST /performance: request model with per‑ETF profiles + composite performance toggles.
  - POST /recommendations: portfolio‑aware offset recommendations.
  - Rate limiting: import existing `limiter` from `app.py` directly (follows established pattern).
    - Rate limits: `@limiter.limit("100/day;200/day;500/day")` for correlations, `@limiter.limit("50/day;100/day;200/day")` for performance, `@limiter.limit("30/day;60/day;120/day")` for recommendations (as specified in architecture doc).
  - DI: `get_user_factor_intelligence_service(user)`; logging/auth wrappers consistent with existing routes.
- Database
  - Migration: `20250903_add_factor_intelligence.sql` to create `user_factor_groups` (with `weights`, `weighting_method`, uniqueness per user) and optional `factor_proxies.user_factor_group_id` FK. Idempotent with indexes and update trigger.
  - DatabaseClient: add CRUD for factor groups: `get_user_factor_groups(user_id)`, `get_factor_group(user_id, group_name)`, `create_factor_group(...)`, `update_factor_group(...)`, `delete_factor_group(user_id, group_name)`.
- DoD: endpoints use POST with request models; migration applied; DB client CRUD covered by unit tests; no circular imports; integration tests; analysis_metadata.performance included. Note: factor‑groups CRUD endpoints may ship in a follow‑up PR if needed.

Quick test
- Launch API; POST `/api/factor-intelligence/correlations` with minimal body (dates only). Expect 200, matrices in response, and `analysis_metadata` populated.
- POST `/api/factor-intelligence/performance`; verify profiles returned.
- POST `/api/factor-intelligence/recommendations` with a dummy overexposed factor; ensure recommendations array present (may be empty in dev).

### PR 6c — Request Models Alignment (0.5–1 day) ✅
- Align Pydantic request models with route parameters for correlations/performance:
  - Add optional fields used by routes: `factor_universe`, `max_factors`, `min_observations`, `correlation_threshold`, `asset_class_filters`,
    `rate_sensitivity_categories`, `market_sensitivity_categories`, `macro_groups`, `sections`, `format`, `top_n_per_matrix`,
    `include_rolling_summaries`, `rolling_windows`, `regime`.
  - For performance: add `factor_universe`, `min_observations`, `asset_class_filters`, `factor_categories`, `industry_granularity`, `composite_weighting_method`, `composite_max_per_group`.
- Documentation: clearly mark advanced fields as optional with sensible defaults.
- DoD: OpenAPI reflects new fields; routes accept the request bodies without extra keys.

Quick test
- Inspect `/docs` to confirm models list the new optional fields; POST sample payloads including a subset of advanced fields.

### PR 6d — Wire Advanced Options (1–2 days) ✅
- Honor overlay and macro options in service implementation:
  - `rate_sensitivity_categories` and `market_sensitivity_categories`: filter tickers for overlays.
  - `macro_groups`: limit curated macro ETF matrix selection to chosen groups.
  - `sections` and `format`: allow filtering response sections (e.g., only 'matrices' or 'overlays') and keep `format='json'` default (table optional later).
  - `top_n_per_matrix`: optionally trim returned matrices for display contexts (no change to stored results).
- DoD: Options alter outputs deterministically; integration tests assert section filtering and category scoping.

Quick test
- POST correlations with `sections=['matrices']` only and confirm overlays omitted; pass `rate_sensitivity_categories=['bond']` and verify overlay restricts to bonds.

### PR 6e — Factor Group Validate Endpoint (0.5–1 day) ✅
- Add POST `/api/factor-groups/{group_name}/validate`:
  - Validates: tickers exist (basic or DB check), weights sum to 1.0 for 'custom', acceptable weighting methods.
  - Returns: success flag, issues list, normalized weights (when applicable).
- DoD: Endpoint returns actionable validation info; integrates with existing factor group storage.

Quick test
- Create a test group with invalid weights; call validate and confirm issues are reported.

### PR 7a — Admin FI Cache Invalidation (optional, 0.5 day) ✅
- After successful asset-proxy or industry mapping writes in admin CLI, trigger FI cache clear:
  - Option A: call an internal admin endpoint to `ServiceManager.clear_all_caches()`.
  - Option B: local import and call with clear messaging.
- DoD: Next API call uses fresh universes without restart.

Quick test
- Add an asset proxy; clear caches; POST correlations; confirm `analysis_metadata.universe_hash` changes.
### PR 7 — Admin/Operational UX (1–2 days) ✅
- `verify_proxies` CLI: check active proxies; print `stale_factor_candidates` report.
- Docs: moving end date defaults; lifecycle metadata fields.
- Cache invalidation: admin commands call `ServiceManager.clear_all_caches()` after successful reference data updates (asset proxies/industry mappings) to ensure fresh universes.
- DoD: CLI utility works; docs updated.

Quick test
- `python admin/manage_reference_data.py asset-proxy list --format json` returns JSON.
- `python admin/manage_reference_data.py asset-proxy add fixed_income duration_short SHY --force` then list to verify.
- `python admin/manage_reference_data.py asset-proxy sync-from-yaml asset_etf_proxies.yaml --dry-run` shows intended changes.

### PR 8 — Utilities & Settings Hardening (0.5–1 day) ✅
- Date helper: add `utils/date_utils.py` with `last_month_end()` and centralize production default end_date resolution; services call this when request omits end_date.
- Settings wiring: add macro matrix defaults (`macro_max_per_group`, `macro_deduplicate_threshold`, `macro_min_group_coverage_pct`) and `DEFAULT_INDUSTRY_GRANULARITY` to `settings.py` with documentation. For cache sizes/TTLs, prefer `utils/config.py` (already defines `DATA_LOADER_LRU_SIZE`, `SERVICE_CACHE_MAXSIZE`, `SERVICE_CACHE_TTL`); if adding `FACTOR_INTELLIGENCE_CACHE_TTL_MINUTES`, place it in `utils/config.py` for consistency.
- DoD: helpers covered by unit tests; settings verified via a smoke test.

Quick test
- Import and call `utils/date_utils.last_month_end()`; ensure value equals last calendar month end.
- From a service default path, omit `end_date` and confirm it resolves to last month‑end.
- Read new settings in REPL; verify macro defaults present and consumed by macro matrix generation.

### PR 9 — Documentation Updates (0.5–1 day) 🔄 Partial
- Update user‑facing and developer docs to reflect new features and endpoints:
  - Backend: `docs/API_REFERENCE.md` (new POST factor‑intelligence endpoints), `docs/architecture/legacy/backend_architecture.md` (service + router), `docs/DATA_SCHEMAS.md` (asset_etf_proxies, industry_proxies.sector_group), `docs/DATABASE_REFERENCE.md` (admin CLI and migrations).
  - Planning: Link FACTOR_INTELLIGENCE_ENGINE_DESIGN, IMPLEMENTATION_ARCHITECTURE, and EXECUTION_PLAN from the README and add a short overview.
  - Admin: `admin/README.md` (asset‑proxy CLI usage, examples, dry‑run guidance).
  - Frontend: add/adjust the client service docs where applicable.
- Update inline docstrings for new core/service/router functions with examples.
- DoD: all references accurate, endpoints tested via curl examples, diagrams updated where present.

Quick test
- Open `/docs` OpenAPI UI and verify new endpoints described (POST with request models).
- Spot‑check `docs/API_REFERENCE.md` examples with curl; confirm responses match.

- Add module‑level documentation and detailed docstrings in code:
  - Modules: `core/factor_intelligence.py`, `services/factor_intelligence_service.py`, `routes/factor_intelligence.py`, `inputs/database_client.py` (new methods), `admin/manage_reference_data.py`, `admin/migrate_reference_data.py`.
  - For each module, include a top‑of‑file docstring summarizing purpose, key functions/classes, dependencies (DB‑first loaders, YAML fallbacks), and caching/logging considerations.
  - For each public function/class, add Google‑style or NumPy‑style docstrings with Args/Returns/Raises, side effects (DB writes, cache usage), and small usage examples.
  - Note rate‑limiting expectations on route handlers and cache TTLs on service methods where applicable.
  - DoD: modules contain clear headers and function/class docstrings; examples render correctly in IDE tooltips.

### PR 10 — Frontend Integration (2–3 days) ❌ Not started
- Add a client service to call new endpoints: `/api/factor-intelligence/correlations`, `/performance`, `/recommendations`.
- Container + View components to render matrices/overlays and performance tables; adapter to map API → UI structures.
- Add controls for industry granularity, macro options, and sensitivity overlays.
- DoD: view renders matrices and overlays, fetches update on option change, basic error states.

Quick test
- Render container/view with a mock response; verify tables appear and options control API parameters. Smoke test against live API in dev.

## API Options (for CLI/AI Customization)
- Correlations request options (subset)
  - `factor_categories`, `asset_class_filters`
  - `include_rate_sensitivity`, `rate_maturities`, `rate_sensitivity_categories`
  - `include_market_sensitivity`, `market_benchmarks`, `market_sensitivity_categories`
  - `include_macro_composite`, `include_macro_etf`, `macro_groups`, `macro_max_per_group`, `macro_deduplicate_threshold`, `macro_min_group_coverage_pct`
  - `industry_granularity` ('group' | 'industry' | 'subindustry')
  - `sections` (e.g., ['matrices:industry','overlays:rate','macro:composite']), `format` ('json'|'table'|'both'), `top_n_per_matrix`
  - `include_rolling_summaries`, `rolling_windows`, `regime` (future)

- Performance request options (subset)
  - `include_macro_composite_performance`, `include_factor_composite_performance`
  - `composite_weighting_method` ('equal'|'cap'|'custom'), `composite_max_per_group`

## Defaults (Production)
- end_date: latest month‑end (resolved at runtime, centralized in settings).
- industry_granularity: 'group' (uses sector_group where present; fallback to industry for that entry).
- macro_composite: on; macro_etf: off (opt‑in).
- market_sensitivity: categories ['industry','style'] (exclude 'market'; skip benchmark ETFs).
- rate_sensitivity: categories ['bond','industry','market'] (cash excluded from overlays; appears in macro composites); maturities from `RATE_FACTOR_CONFIG`.
- macro controls: expose `macro_max_per_group` (e.g., 3–5), `macro_deduplicate_threshold` (e.g., 0.95), and `macro_min_group_coverage_pct` (e.g., 0.6) in `settings.py`; use consistently across service/core.

## Performance & Monitoring
- **Global function-level caching**: Core data fetching functions use `@functools.lru_cache(maxsize=DATA_LOADER_LRU_SIZE)` for shared market data (prices, correlations, reference data) cached across all users.
- **User-scoped service caching**: Each user's service instance uses `ServiceCacheMixin` with TTL caches for user-specific analysis results and preferences.
- Shared returns panel cache; section‑level caches (30‑min TTL default).
- Timers collected in `analysis_metadata.performance`:
  - `returns_panel_build_ms`, `per_category_corr_ms` (per category), `total_corr_ms`.
  - `macro_composite_ms`, `macro_etf_ms`, `rate_sensitivity_ms`, `market_sensitivity_ms`.
  - `performance_profiles_ms`, `composite_performance_ms`.
- Size/coverage metrics: counts per category, macro coverage, de‑dup pairs.
- Optional soft thresholds + warnings for slow sections.

## Data Quality & Lifecycle
- Centralized thresholds (`settings.DATA_QUALITY_THRESHOLDS`); exclusions printed and returned.
- Lifecycle signals: `stale_factor_candidates` (no_data/fetch_failed/thin_history), admin flows to replace/deactivate.

## Migration Notes (Idempotence & Consistency)
- Make migrations idempotent: use `IF NOT EXISTS` on table/column/index creation for `asset_etf_proxies` and `industry_proxies.sector_group`.
- Keep asset‑class naming consistent with `core/constants.py` (use `real_estate`, not `reit`) across SQL, YAML, and API responses.

## Testing Strategy
- Unit: alignment/min‑obs; symmetry/range for corr; compositing math; yield handling.
- Snapshot: matrices/overlays/profiles on a fixed universe/window.
- Integration: endpoints + options; default views.
- Performance: time fences per section; cache hit rate sanity.

## Ownership & Process
- Small PRs; migrations first.
- Service owns returns panel build; reuse across all sections.
- Presets (optional doc later): overview, macro_focus, equity_factors, income_focus, light.

---

This plan tracks exactly to the approved design and incorporates review feedback (caching, stability, lifecycle). It’s deliberately broken into small, AI‑assist friendly phases that can be landed independently with strong test coverage.

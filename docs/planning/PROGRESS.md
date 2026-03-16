# Progress Log

**STATUS:** REFERENCE

Daily log of completed work. Most recent first.

---

## 2026-03-13

### Summary: March 5-13 (200+ commits)

Massive execution push across all workstreams. Full detail in `docs/TODO.md` and MEMORY `completed_features.md`.

**Phase 1 — Unblock Everything: ALL DONE** (except 1B infra deploy)
- 1C.1+1C.2: Cash YAML-only + Pandas fix (`a16c346d`)
- 1C.3+3b: Mutual fund E2E + remediation (`ff78e74c`)
- 1C4: Market intelligence improvements (`191cd4ca`, `2861f677`, `396e415e`)
- Security audit + remediation (`770be0bf`)

**Phase 2 — Build the Product: MOSTLY DONE**
- 2D.0-2D.6: Full nav restructure (7 phases) — `fcc9e02b`→`fe5ebb7d`
  - Layout toggle, sidebar nav, research merge, scenarios overhaul, dashboard enrichment, trading section, performance cards
- 2E-a: C4 web CSV import + normalizer builder (`22d59176`) — backend tools, onboarding route, AI chat panel
- Frontend Release Tracker: Tiers 0-3 ALL DONE (38 issues triaged, delete pass + 3 fix tiers + nav restructure)

**Frontend Architecture**
- Redesign decomposition (6 monoliths → orchestrator + subdirs)
- Redesign migration Batches 1-3 (block components)
- Theme system (classic/premium toggle)
- Visual polish Phase 5 (4 batches)
- Frontend performance Phases 1-3 (2.1MB→16 chunks, 45% gzip reduction)
- Hook migration Batches A-D (18/18 data-fetch hooks → `useDataSource`)
- App-platform extraction + npm publish

**Backend Architecture**
- Root cleanup: 32→3 root .py files (4 rounds of shim removal + reorg)
- App platform extraction v0.2.0 (db, logging, middleware, auth, gateway)
- Backend performance Phases 1-4 (event-loop -99%, factor recs -95%)
- Efficient frontier (CVXPY + frontend)
- No-DB mode
- Core shim removal (19 files)

**Trading + Data**
- IBKR order status fix (`e0b55569`)
- Option pricing chain (system-wide, multiplier NAV, cash replay, portfolio analysis)
- Exercise cost basis linkage
- Cross-currency dedup fix, income dedup fix
- TWR inception month fix
- Futures margin capital base, phases 8b-9
- Transaction store phases A-B
- Continuous hedge monitoring

**Remaining for ship:**
- 1B: Multi-user infra deploy (needs domain name)
- 2E: Portfolio selector (backend in progress)
- 2E-b: CSV import settings path + live test
- ~~2F: Tier 4 features~~ — **ALL DONE**. AI insights toggle (`774459ca`), rebalance execution (`98217b77`)
- 3G: Tier 5 polish (toggle, settings, connections)
- 3I: Onboarding E2E test
- 3J: Final deploy + verify
- 3K: Release scrub execution

---

## 2026-03-04

### Risk Analysis — Detail Gaps: Computed Text + Hedging Enrichment

Replaced all hardcoded placeholder content in the Risk Analysis view with computed values from real backend data.

**Part 1 — Risk Factor Descriptions** (RiskAnalysisModernContainer.tsx):
- `buildRiskFactorDescription()` helper computes `description`, `mitigation`, `timeline` for 4 risk factors
- Concentration: top 3 positions from `portfolio_weights` (e.g., "DSU (31.3%), STWD (13.4%), MSCI (13.4%) — 58.1% of portfolio")
- Volatility: `annual_volatility` directly (already percent from adapter, 8.6% = low)
- Factor: dominant beta from `portfolio_factor_betas` + `variance_decomposition.factor_variance` (Market β=1.05, 76.4%)
- Sector: `industry_variance_absolute` converted from absolute to percentage (REM 41.2% of variance, 21 sectors)
- All fall back to generic text if data missing

**Part 2 — Hedging Enrichment** (container-only, no adapter/hook changes):
- `enrichedHedgingData` useMemo computes `expectedCost`, `beforeVaR`/`afterVaR` (parametric 95% daily, matching RiskMetricsContainer formula), `portfolioBeta`
- Removed hardcoded override layer in RiskAnalysis.tsx (lines 314-339 → `...hs` spread)
- Updated `RiskAnalysisProps.hedgingStrategies` type to include `duration` + `details`

**Plan:** `completed/RISK_ANALYSIS_DETAIL_GAPS_PLAN.md` (4 Codex review rounds)
**Commit:** `5831c982`
**Verification:** Live in Chrome — all 4 risk factors show real data, hedging cards show adapter values (Duration: "Rebalance", real protection percentages), no hardcoded placeholders visible.

### Scenario Analysis: Full Overhaul (Phases 2-5) — Complete

All 5 tabs of the Scenario Analysis view are now functional with real data. Phase 1 (Stress Test wiring) was completed previously in Wave 3h.

**Phase 2 — What-If Preset Templates (frontend only):**
- `buildScenarioTemplates()` computes 5 presets from live portfolio positions:
  - Equal Weight (1/N across non-cash holdings)
  - Conservative 60/40 (bond/cash 60%, equity 40%)
  - Risk Parity (inverse-volatility weighting with equal-weight fallback)
  - Concentrated Growth (top 5 positions at 20% each)
  - Hedge Overlay (current weights + SPY -5% delta)
- Uses `holding.type` and `holding.volatility` from `PositionsAdapter` (enriched in Wave 2.5)
- Templates produce `new_weights` dict → auto-run via `runScenario()` from `useWhatIfAnalysis`
- Commit: `627c167f`

**Phase 3 — Monte Carlo Simulation Engine (backend + frontend):**
- New `portfolio_risk_engine/monte_carlo.py`: Cholesky decomposition on monthly covariance, `nearest_psd()` fix for non-PSD matrices, -99% return floor, configurable simulations (500/1000/5000) and horizon (6/12/24/36 months)
- Returns percentile paths (p5/p25/p50/p75/p95), terminal distribution (mean, median, VaR 95%, CVaR 95%, probability of loss)
- `POST /api/monte-carlo` endpoint in `app.py` + `MonteCarloRequest`/`MonteCarloResponse` models
- Frontend: `useMonteCarlo` hook, `monteCarloKey(portfolioId)`, full UI with parameter controls + results display
- 5 unit tests (output shape, percentile ordering, terminal stats, single asset edge case, zero vol)
- Commit: `078aed92`

**Phase 4 — Scenario Session History (frontend only):**
- `useScenarioHistory` hook with `sessionStorage` (clears on tab close), max 20 entries FIFO
- Auto-captures runs from what-if, stress test, and Monte Carlo hooks via `useEffect` ref comparison
- Collapsible "Recent Runs" panel per tab with re-run and compare mode
- Commit: `c3e4eb56`

**Phase 5 — Optimizations Tab (frontend only):**
- Reads cached optimization data via `queryClient.getQueryData(portfolioOptimizationKey(...))` — avoids auto-fetching `usePortfolioOptimization()` which takes 60+ seconds
- Checks both `min_variance` and `max_return` strategies, picks most recently cached
- Shows optimized weights vs current + "Apply as What-If" cross-link, or "Run in Strategy Builder" prompt
- Commit: `b6f3e45e`

**Plan:** `completed/SCENARIO_ANALYSIS_OVERHAUL_PLAN.md` (6 Codex review rounds for plan, 4 Codex implementation rounds)
**Verification:** All 5 tabs live-tested in Chrome — stress tests (8 scenarios, Market Crash -26.0%/-$38,069), templates (25 assets), Monte Carlo (1000 sims, $164,900 expected, 2.2% loss probability), session history tracking, optimization tab wired.

---

## 2026-03-01

### Trading Analysis: Date Range Parameters — Complete
- Added `start_date`/`end_date` optional params to `get_trading_analysis()` MCP tool
- FIFO runs on full transaction history (preserves lot matching integrity)
- Post-analysis filtering on `FullAnalysisResult`: trades by exit_date (closed) or entry_date (open), timing by sell_date
- Income events pre-filtered before `run_full_analysis()` (safe — not used in FIFO)
- Aggregates recomputed on filtered set (total_pnl, win_rate, timing scores)
- Non-recomputable fields nulled: grades → `""`, realized_performance/behavioral/return_stats → `None`
- Date validation via `pd.Timestamp()` with `start_date <= end_date` enforcement
- Plan: `docs/planning/completed/TRADING_DATE_RANGE_PLAN.md` (3 Codex review rounds)
- Commit: `5919122e`
- Tests: 33 passing (model filter, MCP validation, agent format)
- Live MCP test: `get_trading_analysis(start_date="2025-06-01", end_date="2025-12-31")` → 18 trades, $1,483 P&L

### Options Portfolio Risk Integration (Phases 1-2 Complete)

**Phase 1 — Option Position Enrichment:**
- `enrich_option_positions()` in `services/position_enrichment.py` — in-place mutation following futures enrichment pattern
- Detection: `type == "option"` primary, symbol parser fallback via `parse_option_contract_identity_from_symbol()`
- Fields added: `option_type`, `strike`, `expiry`, `underlying`, `days_to_expiry`, `is_option`
- Unparseable symbols: `option_parse_failed: True` (counted in exposure, excluded from Greeks)
- `options_exposure` section in `get_exposure_snapshot()` (count, calls/puts, nearest expiry, by underlying)
- 3 position flags: `expired_options` (error), `near_expiry_options` (warning), `options_concentration` (info)

**Phase 2 — Portfolio Greeks Aggregation:**
- `PortfolioGreeksSummary` + `compute_portfolio_greeks()` in `options/portfolio_greeks.py`
- Dollar Greeks scaling: delta×qty×mult×S, gamma×qty×mult, theta×qty×mult, vega×qty×mult
- IV solved from option market price via `implied_volatility()`, fallback to 30% default
- Risk-free rate from treasury provider, fallback to 5%
- Wired into `get_exposure_snapshot()` in `core/result_objects/positions.py` (core layer, not MCP)
- 4 Greeks flags in `core/option_portfolio_flags.py`: `theta_drain`, `significant_net_delta`, `high_vega_exposure`, `greeks_computation_failures`
- IBKR live Greeks path deferred (comment placeholder)

**Plan:** `docs/planning/completed/OPTIONS_PORTFOLIO_RISK_PLAN.md` (2 Codex review rounds)
**Commit:** `6e62c5d6`
**Tests:** 76 passing (portfolio Greeks, enrichment, flags, position result)

---

## 2026-02-24

### Frontend Three-Package Split (Phase A Complete)

**1. Three-Package Architecture — Complete**
- Split frontend monolith (~312 files, ~80K LOC) into three pnpm workspace packages:
  - `@risk/chassis` — auth, caching (6-piece), API client, service container, logging, stores
  - `@risk/connectors` — 9 adapters, 15+ feature hooks, managers, domain services, types/schemas
  - `@risk/ui` — 40+ Radix components, dashboard views, chat, pages, theming
- Strict dependency direction enforced: `ui → connectors → chassis`
- Plans: `FRONTEND_PACKAGE_SPLIT_PLAN.md` (3 Codex review rounds)
- Executed by Codex

**2. CRA → Vite Migration — Complete**
- Replaced `react-scripts` with Vite 7 + `@vitejs/plugin-react` + `vite-tsconfig-paths`
- Moved entry from `public/index.html` → `frontend/index.html`
- Proxy config: `/api`, `/auth`, `/plaid` → localhost:5001
- `pnpm` replaces `npm` as package manager (`pnpm-workspace.yaml`)

**3. Compatibility Wrapper Cleanup — Complete**
- Removed all 32 one-liner re-export shim files left by the split
- Updated all import paths in UI consumers to use `@risk/chassis` / `@risk/connectors` directly
- Deleted 9 empty directories (stores/, providers/, services/, lib/, config/, utils/, repository/, chassis/, features/)
- Plans: `FRONTEND_WRAPPER_CLEANUP_PLAN.md` (3 Codex review rounds)
- Executed by Codex

**4. ESLint Migration — Complete**
- Replaced `eslint-config-react-app` (CRA dependency) with standalone plugins
- Installed: `eslint-plugin-react`, `eslint-plugin-react-hooks`, `@typescript-eslint/eslint-plugin`, `@typescript-eslint/parser`
- Disabled React Compiler rules from react-hooks v7 (purity, set-state-in-effect, immutability)
- Result: 0 errors, 1,850 warnings

**5. Bug Fixes**
- `rawData → portfolioHoldings` typo in `PortfolioSummaryAdapter.ts:386` — crashed React render silently (caused blank page, no error boundary caught it)
- `CUR:XXX` ticker validation in `portfolio_risk_score.py` — added `:` to allowed regex characters so currency positions (`CUR:CAD`, `CUR:HKD`, etc.) pass validation
- Stale CRA `node_modules` causing dual React instance — resolved by clean `pnpm install`

**6. Frontend Remaining Cleanup — Complete**
- Fixed `pnpm typecheck`: added `emitDeclarationOnly`, `declarationDir: "dist"`, `tsBuildInfoFile` to all 3 package tsconfigs. Deleted 3 stale `.js` duplicates. Changed script from `tsc -b --noEmit` to `tsc -b`. TS6310/TS5055 config errors resolved.
- Reduced ESLint warnings from 1,850 → 708 (0 errors): auto-fix JSDoc formatting, turned off aspirational JSDoc rules globally (kept strict for chassis/services), removed all unused vars/imports across 95 files
- Cleaned up stale legacy references in docs/comments
- Plan: `FRONTEND_REMAINING_CLEANUP_PLAN.md` (3 Codex review rounds)
- Executed by Codex + manual fixes for 6 JSDoc/@param + React hooks errors

### Codebase Stats
- Split commit: 400 files changed, 9,236 insertions, 39,861 deletions
- Cleanup commit: 95 files changed, 860 insertions, 1,179 deletions
- Build: `pnpm build` passes
- Lint: `pnpm lint` — 0 errors, 708 warnings
- Typecheck: TS6310/TS5055 config errors gone (pre-existing TS type errors remain)
- Dev server: verified rendering in Chrome (portfolio value, risk scores, charts, all views working)

### Plans Reviewed (Codex Review Process)
| Plan | Rounds | Result |
|------|--------|--------|
| Frontend Package Split (Phase A) | 3 | Passed |
| Wrapper Cleanup | 3 | Passed |
| Remaining Cleanup | 3 | Passed |

---

## 2026-02-19

### Features Implemented

**12. Plaid/SnapTrade Cost Reduction — Complete (all code phases)**
- Closes out the full Plaid Cost Reduction Plan (started 2025-01-29). All 7 phases of code complete.
- Phase 1 (24h cache) was already done. This session completed Phases 2–5 + 7:
- DB migration run: `has_pending_updates` columns + `provider_items` table
- SnapTrade webhook handler: HMAC-SHA256 signature verification, replay rejection (5-min window), `ACCOUNT_HOLDINGS_UPDATED` event routing to set DB pending flag
- `POST /api/snaptrade/holdings/refresh` with per-user 60s cooldown (429 + Retry-After)
- `GET /api/snaptrade/pending-updates` + `GET /plaid/pending-updates` (pure DB reads for frontend polling)
- Plaid parity: added refresh cooldown to `POST /plaid/holdings/refresh`
- Shared `_build_snaptrade_holdings_payload()` helper for `Portfolio`-compatible response shape
- Lazy backfill of `provider_items` mapping on first `GET /api/snaptrade/holdings`
- Frontend: `usePendingUpdates()` hook with per-provider flags, 5-min polling via TanStack `useQueries`
- Frontend: `refreshHoldings(providers)` with per-provider POST, `Promise.allSettled`, 429 detection, `extractPortfolio()` normalization, multi-provider merge
- Frontend: amber "Updates available" banner, toast feedback for 429/errors, `lastSynced` from real backend timestamp
- Frontend: 429 preserved end-to-end through `fetchWithRetry` → `PortfolioManager` → `handleRefresh` (toast)
- 9 new backend tests (webhook auth, cooldown, pending status)
- Remaining (Phase 6 infra only): add SnapTrade route to existing webhook relay, register URL with SnapTrade, set `SNAPTRADE_WEBHOOK_SECRET`
- Plans: `PLAID_COST_REDUCTION_PLAN.md`, `WEBHOOK_REFRESH_NOTIFICATION_PLAN.md` (8 Codex review rounds)
- Plan: `WEBHOOK_REFRESH_NOTIFICATION_PLAN.md` (v8, 8 Codex review rounds)

**11. Logging System Overhaul (Phases 0–5)**
- Rewrote `utils/logging.py` from 2,208 to 856 lines
- Consolidated dual logging systems (`utils/logging.py` + `app.py` locals + `utils/json_logging.py`) into single module
- Reduced 21+ log files to 5: `app.log`, `errors.jsonl`, `usage.jsonl`, `frontend.jsonl`, `debug.log`
- New API: 7 functions (`log_error`, `log_alert`, `log_event`, `log_slow_operation`, `log_service_status`, `log_usage`, `log_frontend_event`) + 3 async-safe decorators (`@log_errors`, `@log_timing`, `@log_operation`)
- Added alert deduplication with thread-safe 5-min window and suppressed-count tracking
- Suppressed healthy-service-status noise (FMP, PostgreSQL, Plaid healthy-call spam eliminated)
- Removed decorator stacking from trivial display/formatting functions
- Migrated all 142 `log_error_json` call sites to typed API with semantic key classification (user_id vs correlation_id vs context)
- Replaced `risk_module_secrets/logging.py` (2,185-line duplicate) with re-export shim
- Deleted `utils/json_logging.py` and `risk_module_secrets/json_logging.py`
- Removed 6 deprecated decorator aliases from all call sites (104 files changed, -4,327 net lines)
- Plan: `LOGGING_OVERHAUL_PLAN.md` (10 Codex review rounds before implementation)
- Commit: `ca5eb46c`

**1. Leverage Capacity Analysis (`get_leverage_capacity` MCP tool)**
- New `compute_leverage_capacity()` function in `core/portfolio_analysis.py` (~200 lines)
- Calculates maximum leverage before risk limit breach using 4 scaling constraints:
  - Volatility vs `max_volatility` limit
  - Implied max-loss via parametric VaR (95%, 1Y) vs `max_loss` limit
  - Max single-stock weight vs `max_single_stock_weight` limit
  - Factor/proxy betas vs derived beta limits
- Plus 3 invariant (non-scaling) constraints: factor, market, and industry variance contributions
- Reports binding constraint, headroom, and per-constraint breakdown
- MCP tool: `get_leverage_capacity()` in `mcp_tools/risk.py`
- Plan: `LEVERAGE_CAPACITY_PLAN.md` (v4, 4 Codex review rounds)
- Commits: `2b34be08`, `b50f4a6d`

**2. Fund/ETF Weight Exemption — Risk Analysis + Leverage Capacity (B-015 part 1)**
- Discovered DSU (closed-end bond fund) at ~35% was falsely triggering `max_single_stock_weight` limit
- Added `DIVERSIFIED_SECURITY_TYPES = {"etf", "fund", "mutual_fund"}` constant in `core/constants.py`
- Filters weights by `security_type` before concentration checks in:
  - `evaluate_portfolio_risk_limits()` in `run_portfolio_risk.py`
  - `compute_leverage_capacity()` in `core/portfolio_analysis.py`
- Switched `services/portfolio_service.py` from `get_asset_classes()` to `get_full_classification()` for both security_type and asset_class in one call
- Threaded `security_types` through `run_risk.py` dual-mode entry point
- Plan: `FUND_WEIGHT_EXEMPTION_PLAN.md` (v3, 3 Codex review rounds)
- Commit: `8bec0629`

**3. Fund/ETF Weight Exemption — Risk Score Path (B-015 part 2)**
- Extended the same exemption to `portfolio_risk_score.py`:
  - `_get_single_issuer_weights()` helper with conservative fallback (empty filtered set → raw weights)
  - `calculate_concentration_risk_loss()` — filters before picking largest position, reconciles with existing `SecurityTypeService` call
  - `analyze_portfolio_risk_limits()` — filters before concentration warning/violation logic
  - `calculate_portfolio_risk_score()` — threads `security_types` + `portfolio_data`
  - `run_risk_score_analysis()` — resolves `security_types` once, threads downstream, stores in metadata
- Plan: `RISK_SCORE_FUND_WEIGHT_EXEMPTION_PLAN.md` (v4, 4 Codex review rounds)
- Commit: `55ef6ad8`

**4. Custom Risk Profiles (`set_risk_profile` / `get_risk_profile` MCP tools)**
- Profile-based risk limit presets (income, growth, trading, balanced)
- User-configurable structural parameters (max_loss, vol_target, max_single_stock_weight, etc.)
- Auto-detection of portfolio leverage for limit scaling
- Commit: `21451aa4`

**5. Agent-Optimized Risk Analysis Format**
- New `format="agent"` output for `get_risk_analysis()` — decision-oriented buckets with flags
- File output mode (`output="file"`) for large analysis results
- Plan v4.1 after Codex review
- Commits: `20138f05`, `1505ca2f`, `608d2a6f`

**6. Risk-Enriched Monitor View**
- Added risk metrics overlay to position monitor output
- Commit: `a5e22648`

**7. RiskAnalysisResult Cleanup**
- Removed redundant fields from `to_api_response()`
- Plan reviewed by Codex meta-review
- Commits: `9c52880c`, `47cc665b`, `d78e5f6e`

**8. International Futures Support + Daily Bars + FX Attribution**
- Implemented plan: `INTERNATIONAL_FUTURES_PLAN.md` (approved v2.3)
- Added international futures support in IBKR mapping + routing, daily futures profile/fetch path, and FX attribution plumbing:
  - `ibkr/exchange_mappings.yaml` (international futures mappings)
  - `ibkr/profiles.py` (`futures_daily` + `get_profile()` direct-key routing fix)
  - `ibkr/market_data.py` (`fetch_daily_close_futures()`)
  - `ibkr/client.py` + `ibkr/compat.py` + `ibkr/__init__.py` exports
  - `portfolio_risk.py` (`instrument_types` threading through cache boundary, `fx_attribution` output, futures currency auto-detection gated by instrument type)
  - `fmp/fx.py` (`adjust_returns_for_fx(..., decompose=True)` with backward compatibility)
  - Root `exchange_mappings.yaml` (BRL FX pair + fallback rate)
- Added targeted tests for profile routing, compat wrappers, FX decomposition, and ticker-collision safety (`Z` equity vs futures root)
- Validation run: 56 tests + 18 tests passed in targeted suites
- Commit: `5b3bc41c`

**9. Live IBKR Symbol Verification + Eurex Root Correction**
- Live gateway smoke tests showed placeholder Eurex roots (`FESX`, `FDAX`, `FDXM`) were not contract-qualifiable in this IBKR environment.
- Switched mappings to live-valid IBKR roots:
  - `ESTX50` (Euro Stoxx 50)
  - `DAX` (DAX futures)
- Verified with live fetches (monthly + daily bars available for both symbols)
- Searched YAML/user configs and Postgres portfolio tables for old placeholders; none found
- Commit: `765cc141`

**10. `instrument_types` Threading Through MCP → Core Analysis Chain**
- Wired `instrument_types` from `PortfolioData` through the full MCP chain so futures are auto-detected from live positions
- Plan: `INSTRUMENT_TYPES_THREADING_PLAN.md` (v1.2, 3 Codex review rounds)
- Changes (3 files, ~25 lines):
  - `core/data_objects.py` — added `instrument_types` field to `PortfolioData`, `from_holdings()`, `_generate_cache_key()`, `from_yaml()`, `to_yaml()`. Auto-detection in `to_portfolio_data()` cross-references tickers against IBKR futures YAML with derivative type guard (prevents Z/Zillow collision)
  - `core/config_adapters.py` — added `instrument_types` to `config_from_portfolio_data()` dict
  - `core/portfolio_analysis.py` — extracted `instrument_types` from config, passed to `build_portfolio_view()`
- No CLI or MCP tool changes needed — flows automatically through existing chain
- Verified: auto-detection works (NKD tagged, Z equity safe, Z derivative tagged), cache keys differ, 313 tests pass
- Live MCP test: full risk analysis runs, FX attribution fires for non-USD futures (HSI +72.46% local / +0.08% FX, Z +39.23% local / +5.94% FX)
- Commit: `95812768`

**Live IBKR Gateway Testing Results (International Futures)**
- Tested all 9 international futures contracts against live gateway:
  - Working: NKD (534 bars), MNK (331 bars), NIY (534 bars), Z (542 bars), HSI (525 bars)
  - Failed: IBV (contract not found — removed from catalog, not available on IBKR)
  - Phase 7 verified: ESTX50 (conId=621358639), DAX (conId=621358482) — both working after Eurex subscription added
- Currency detection priority fix found during testing: reordered to futures YAML → FMP profile (was FMP first, which defaulted ^HSI to USD)

### Codebase Cleanup & Organization

**Major repo reorganization** — 25+ commits moving files to proper locations:
- Archived stale tools: tracer/living-map tools (14 files), Playwright e2e tests, AI test orchestrator, unused metrics/exports/error_logs
- Moved docs: `MCP_SERVERS.md` → `reference/`, `AUTONOMOUS_WORKFLOW.md` → `standards/`, design docs → `architecture/`
- Consolidated backlogs: merged `BACKLOG.md`, `TODO-options-tools.md` into `TODO.md`
- Organized bugs: `bugs/` → `docs/planning/` (open) + `docs/planning/completed/` (resolved)
- Moved test files to natural subfolders, migration files to `database/migrations/`
- Moved `prototype/` out of repo, archived stale admin/tools scripts
- Updated backup script and doc references for new structure

### Bug Tracking
- **B-015 resolved** — fund/ETF weight exemption across all paths
- **B-016 opened** (backlog) — risk score methodology review:
  1. `calculate_suggested_risk_limits()` still uses raw max weight
  2. Broader 0-100 scoring calibration review
  3. Risk score interaction with risk profile presets

### Plans Reviewed (Codex Review Process)
| Plan | Rounds | Result |
|------|--------|--------|
| Leverage Capacity (v4) | 4 | Passed |
| Fund Weight Exemption — Risk Analysis (v3) | 3 | Passed |
| Fund Weight Exemption — Risk Score (v4) | 4 | Passed |
| International Futures (v2.3) | 4 | Passed |
| Instrument Types Threading (v1.2) | 3 | Passed |

---

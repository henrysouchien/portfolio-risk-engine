# Frontend Release Tracker — Issue Detail

> **Created**: 2026-03-11 | **Updated**: 2026-03-15
> **Full issue list**: `FRONTEND_ISSUES_2026_03_10.md` (38 issues from live walkthrough)
> **Execution plan**: `docs/PUBLISH_PLAN.md` — Phase 2D (nav restructure), 2E (features), 3G (polish)
> **Sequence**: Fix crashes → fix lies → make it understandable → restructure → add features → polish

---

## Delete Pass `DONE` — commit `631fe4cb`

Removed 16 categories of fake/broken/duplicate/placeholder UI.
**Plan**: `completed/frontend/FRONTEND_DELETE_PASS_PLAN.md`

Resolved issues: #4 (view mode toggle), #5 (hover clutter), #7 (stray "0"), #8 (hardcoded metadata), #13 (period selector crash), #18 (fake risk efficiency), #21 (Standard/Detailed toggle), #27 (duplicate risk card), #31 (duplicate perf view), #32-partial (Historical tab), #33c (Active Strategies tab).

---

## Tier 0 — Ship Blockers (crashes / data loss) `DONE` — live verified 2026-03-11

| # | Issue | Status |
|---|-------|--------|
| 22 | ~~Benchmark selector crashes on non-SPY~~ | **DONE** — `67ad0915` (localStorage validation + error boundary + reset-to-SPY) |
| 25 | ~~Provider disconnect silently drops positions~~ | **DONE** — `67ad0915` (PartialRefreshWarningBanner, per-provider tracking) |
| 37b | ~~Error banner color + card crash from client state~~ | **DONE** — `67ad0915` (blue→emerald, keepPreviousData on 4 containers) |
| 13 | ~~Asset Allocation period selector crashes card~~ | **DONE** — delete pass `631fe4cb` |
| 7 | ~~Stray "0" rendered on metric cards~~ | **DONE** — delete pass `631fe4cb` |

Review follow-up (`60542582`): benchmark regex allowlist (any 1-5 char ticker), stale data opacity indicator on 4 containers, error boundary soft retry before nuclear reset, typed test factories.

---

## Tier 1 — Data Trust (wrong/fake numbers) `DONE`

| # | Issue | Fix | Commit |
|---|-------|-----|--------|
| 24 | Performance Insights wrong numbers + misleading impact labels | `_generate_structured_insights()` with data-driven impact scoring | `5ee37879` |
| 10 | AI Recommendations fake confidence/timeframe/priority | Stripped fabricated fields from backend + frontend types | `5ee37879` |
| 23 | Percentage formatting — use 1dp, Sharpe 2dp | 4 performance view files standardized | `5ee37879` |
| 15 | Risk Assessment VaR vs Max Drawdown methodology inconsistency | Investigated — no inconsistency. VaR + Worst Monthly Factor Return correctly labeled distinct | N/A |
| 17 | VaR horizon mismatch | Removed placeholder "VaR (95%): --" and "Downside Deviation: --" from RiskAnalysisTab | `5ee37879` |
| 18 | "Risk Efficiency" metric is fake | Removed in delete pass | `631fe4cb` |
| 8 | Bottom 3 metric cards hardcoded placeholder metadata + "Updated0" | Removed in delete pass | `631fe4cb` |
| — | Risk score ignores violations | Severity-weighted penalty + ceiling at 89 | `d332db47` |

---

## Tier 2 — UX Fundamentals (usable without confusion) `DONE`

| # | Issue | Fix | Commit |
|---|-------|-----|--------|
| 3 | Refresh button no visual feedback | Bigger spinner, success/error toast, last-updated tooltip, isRefetching loading | `98a11e2c` |
| 16 | Risk Assessment metrics no hover explanations | 21 tooltip placements across RiskMetrics, RiskAnalysis, FactorRiskModel | `98a11e2c` |
| 9 | Performance Trend chart lacks fundamentals | Y-axis labels, hover tooltip, legend swatch, "Cumulative return" label | `98a11e2c` |
| 26 | Attribution column headers ambiguous — need tooltips | Info icon + tooltip on all DataTable columns | `2909dda4` |
| 19 | Alpha Generation card — number without benchmark/period context | Dynamic benchmark ticker + "annualized" label | `afefd51c` |
| 29 | Factor Risk Model card — fixed height truncates + sloppy hover | min-h, larger scroll area, purple hover border | `5ad3ff7c` |
| 6 | Daily P&L card redundant with Total Portfolio Value | Replaced with YTD Return card | `afefd51c` |
| 5 | Metric card hover clutter | Removed in delete pass | `631fe4cb` |
| 21 | Standard/Detailed toggle does nothing | Removed in delete pass | `631fe4cb` |
| 30 | Factor Risk Model Performance tab — metrics unexplained | **Deferred** — future Claude integration surface | — |

---

## Tier 3 — Information Architecture `ALL DONE` → Publish Plan Phase 2D

**Synthesis plan**: `completed/frontend/FRONTEND_NAV_SYNTHESIS_PLAN.md` (master plan, 7 phases — ALL DONE)
**Sub-specs**: `completed/frontend/CODEX_SIDEBAR_NAV_SPEC.md`, `completed/frontend/SCENARIOS_OVERHAUL_SPEC.md`, `completed/frontend/SCENARIOS_PREP_REFACTOR_IMPL_PLAN.md`, `completed/frontend/TRADING_SECTION_PLAN.md` (v8)
**Source plans**: `completed/frontend/NAVIGATION_RESTRUCTURE_PLAN.md`, `completed/frontend/FRONTEND_LAYOUT_SPEC.md`, `completed/frontend/CODEX_FLATTEN_NAV_SPEC.md`

| # | Issue | Stage | Status |
|---|-------|-------|--------|
| 28 | Analytics dropdown hides too much functionality | **DONE** — Research merge (2D.2) + layout toggle (2D.0b) `c0055b54` | [x] |
| 35-37a | Stock Lookup: 7 oversized tabs → flatten, show chart default, promote Portfolio Fit | **DONE** — Research merge (2D.2) `c0055b54` | [x] |
| 32 | Scenario Analysis: 5 tabs (Historical removed), needs guided workflow | **DONE** — Scenarios overhaul (2D.3) `fe5ebb7d` | [x] |
| 33 | Strategy Builder: 3 tabs (Active removed), user doesn't know what they're building | **DONE** — Trading section (2D.5) `d5f4c981` | [x] |
| — | Card-Based Navigation — top-level card grid with summary stats, click → detail views | **DONE** — Dashboard enrichment (2D.4) `c0055b54` | [x] |
| 4 | ~~View mode toggle (Compact/Detailed/Pro/Institutional)~~ | **DONE** — delete pass `631fe4cb` | [x] |
| 27 | ~~Factor Analysis duplicate Risk Assessment card~~ | **DONE** — delete pass `631fe4cb` | [x] |
| 31 | ~~Performance view duplicate on overview~~ | **DONE** — delete pass `631fe4cb` | [x] |

---

## Tier 4 — Features & Onboarding `OPEN` → Publish Plan Phase 2E/2F

| # | Issue | Stage | Status |
|---|-------|-------|--------|
| — | ~~Onboarding Wizard — Phases 0-3~~ | **DONE** — `61bdb81f`, `de315bf3`, `8a319786`, `ce484901`. Phase 4 (polish) in backlog | [x] |
| 11 | ~~Market Intelligence — relevance scoring + action items~~ | **DONE** — `191cd4ca`, `2861f677`, `396e415e` | [x] |
| 12 | ~~Asset Allocation targets~~ | **DONE** — targets UI exists (edit/save/preview) | [x] |
| — | C4 Web CSV Import + Normalizer Builder (Phases 1-3) | **DONE** — `22d59176`. Backend tools, onboarding route, AI chat panel. Spec: `completed/frontend/SPEC_C4_WEB_CSV_IMPORT.md` | [x] |
| — | ~~C4 follow-up: CSV Import Settings Path~~ | **DONE** — `cb06e670`. `/import-csv-full` endpoint from Settings page. | [x] |
| 2 | ~~AI Insights toggle wiring~~ | **DONE** — `774459ca`. uiStore state, conditional fetch, ViewControlsHeader mount. Spec: `completed/frontend/AI_INSIGHTS_TOGGLE_SPEC.md` | [x] |
| 14 | ~~Rebalance trade execution~~ | **DONE** — `98217b77`. Three-step flow (generate→preview→execute), IBKR event loop fix. Live tested. Spec: `completed/REBALANCE_EXECUTION_SPEC.md` | [x] |
| 34 | AI Assistant intro — portfolio-aware greeting | **Defer post-launch** — current welcome functional | [ ] |

---

## Tier 5 — Polish & Packaging `OPEN` → Publish Plan Phase 3G

| # | Issue | Stage | Status |
|---|-------|-------|--------|
| 1 | ~~Classic ↔ Premium toggle — preview cards~~ | **DONE** — ToggleGroup + merged Appearance section (`c73b2866`) | [x] |
| 36b | ~~Risk Management Settings — fix metrics~~ | **DONE** — sensible defaults, removed Compliance tab (`c73b2866`) | [x] |
| 38 | ~~Account Connections — simplify~~ | **DONE** — major rewrite 316→~14 lines (`c73b2866`) | [x] |
| — | ~~Hook Migration Batch D (useWhatIfAnalysis — 499 lines)~~ | **DONE** — `f6c1e94b`. All 18/18 hooks migrated (usePositions: `4665b964`). | [x] |
| — | ~~Publish `web-app-platform` npm~~ | **DONE** — v0.1.0 on npm. Pipeline: `scripts/publish_web_app_platform.sh`. Commits: `c3a2efe9`, `473cfe45`. | [x] |
| — | Dynamic UI stretch goals (component registry, schema renderer, workflow templates) | Backlog | [ ] |

---

## E2E Re-Audit (2026-03-14) — 16 New Issues

**Source**: `FRONTEND_E2E_FINDINGS_2026_03_14.md` (Sessions 1+2)
**Fix plan**: `E2E_REAUDIT_FIX_PLAN.md`

| # | Severity | Issue | Status |
|---|----------|-------|--------|
| N6 | Blocker | Auth hang on fresh tab — no timeout | **FIXED** — 10s timeout in `createAuthStore.ts` (`edd9b8a4`) |
| N7 | Blocker | Dashboard "Mock" data after re-auth | **RESOLVED** — verified via live test 2026-03-15, shows "Overview: Real" |
| N8 | Major | Rebalance Preview 401 | **RESOLVED** — N13 fix provides 401 interceptor |
| N9 | Major | Plaid holdings 500 | Not a bug (expired credentials) |
| N10 | Major | Portfolio selector click triggers page reload | **FIXED** — verified live 2026-03-15, client-side switch works |
| N11 | Major | Alerts cross-scope tickers | **FIXED** — portfolio scoping (`edd9b8a4`) |
| N12 | Major | Position count mismatch (21 vs 15) | **FIXED** — exclude cash from count (`3ff6d9cf`) |
| N13 | Major | No session expiry recovery UX (401 interceptor) | **FIXED** — `e6f0b7dd` (onUnauthorized callback, 7 files) |
| N14 | Minor | Total Allocation 100.1% rounding | **FIXED** — backend per-bucket rounding (`06822618`) |
| N15 | Minor | Cash -12.1% not labeled as margin | **FIXED** — margin label (`3ff6d9cf`) |
| N16 | Major | Concentration "100 / Well Diversified" on concentrated portfolio | **FIXED** — `fd2a135b` (dual-metric). Combined view score=100 is correct (max pos 11.8%, top-3 30.6%). IBKR single shows 59. |
| N1 | Major | Portfolio selector shows raw internal name | **FIXED** — verified live 2026-03-15, shows "Interactive Brokers U2471778" |
| N2 | Major | Holdings empty for single-account portfolio | **FIXED** — verified live 2026-03-15, shows real positions |
| N3 | Minor | Risk settings stuck loading | **FIXED** — verified live 2026-03-15, loads with sliders and metrics |
| N4 | Minor | 7× setState-during-render warnings | Deferred |
| N5 | Minor | Trading analysis 500 | **TODO** — same scope issue as N2 |

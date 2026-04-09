# Publish Plan — Path to Production

> **Created**: 2026-03-12
> **Goal**: Ship risk_module as a multi-user production app.
> **Canonical TODO**: `docs/TODO.md` — this doc is the execution plan + task tracker.

---

## Execution Overview

```
Phase 1 (parallel, start now)         Phase 2 (parallel, after 1A)      Phase 3 (sequential, last)
──────────────────────────────        ──────────────────────────────    ──────────────────────────
A. Nav spec reconciliation            D. Nav restructure impl           G. Tier 5 polish
B. Multi-user infra deploy            E. Tier 4 feature impl            H. Security review
C. Backend hardening + bugs           F. Tier 4 feature specs           I. Final deploy + verify
   C4. Market intelligence
```

**Critical path**: 1A (nav spec) → 2D (nav implementation) → 3G (polish) → 3I (deploy)

**Parallel tracks**: B (infra) and C (backend) run independently of the frontend critical path.

---

## Phase 1 — Unblock Everything

### 1A. Nav Spec Reconciliation `DONE`

**What**: Synthesize competing nav specs into implementation-ready plan.
**Status**: All specs written, Codex-reviewed, and implemented. Nav restructure (2D) complete.

**Specs produced**:
- `FRONTEND_NAV_SYNTHESIS_PLAN.md` — master plan (7 phases, merges all three source specs)
- `CODEX_SIDEBAR_NAV_SPEC.md` — sidebar layout (Phases 0-1)
- `FRONTEND_NAV_PHASES_2_6_SPEC.md` — Research/Scenarios/Trading/Performance/Polish implementation specs (Phases 2-6)
- `CODEX_NAV_LAYOUT_TOGGLE_SPEC.md` — layout toggle
- `SCENARIOS_OVERHAUL_SPEC.md` — scenarios section overhaul
- `SCENARIOS_PREP_REFACTOR_SPEC.md` + `SCENARIOS_PREP_REFACTOR_IMPL_PLAN.md` (Codex PASS v3, 3 prep refactors)
- `TRADING_SECTION_PLAN.md` (v8, 7 Codex review rounds)

---

### 1B. Multi-User Infrastructure Deploy `READY TO EXECUTE`

**What**: Deploy backend + frontend to production. All code changes are done — this is pure infra.

**Plan**: `docs/deployment/MULTI_USER_DEPLOYMENT_PLAN.md`

**Execution order** (sequential — each step depends on the previous):

| Step | Task | Est. | Notes |
|------|------|------|-------|
| 1B.0 | EBS expansion 7→20 GB | 15 min | **BLOCKER** — only 2.5 GB free. `growpart` + `resize2fs` |
| 1B.1 | Production schema: `pg_dump` → `schema_prod.sql` | 30 min | From local dev DB |
| 1B.2 | RDS: create `risk_module_db`, apply schema, seed reference data | 30 min | `scripts/seed_reference_data.py` |
| 1B.3 | EC2: rsync code, create venv, install deps, `.env`, systemd service | 1 hr | Port 5001, uvicorn 1 worker |
| 1B.4 | Nginx: reverse proxy + certbot SSL | 30 min | `api.yourdomain.com` → :5001 |
| 1B.5 | Vercel: deploy frontend, env vars, SPA routing | 30 min | `app.yourdomain.com` |
| 1B.6 | Google OAuth: production consent screen + verification | 15 min + 1-2 day wait | Privacy policy required |
| 1B.7 | DNS: A record (API) + CNAME (frontend) | 15 min | Route 53 |
| 1B.8 | Monitoring: CloudWatch alarms, health check | 45 min | CPU, memory, disk, instance status |

**Prerequisite**: Domain name registered. **Ask user if they have one.**

**Total**: ~6-7 hours hands-on + OAuth verification wait.

**Key files**:
- `docs/deployment/MULTI_USER_DEPLOYMENT_PLAN.md` (full step-by-step)
- `scripts/seed_reference_data.py`
- `scripts/deploy.sh` (to be created in Phase 2)

---

### 1C. Backend Hardening + Bug Fixes `DONE`

**What**: Fix known bugs and harden backend before deploy.

#### 1C.1+1C.2 Bugs: Cash DB + Pandas Warning `DONE`

**Plan**: `docs/planning/completed/CASH_MAPPINGS_YAML_ONLY_PLAN.md` (12 steps, 16 files)
**Commit**: `a16c346d`

#### 1C.3 Mutual Fund E2E Verification + Remediation `DONE`

**What**: Verify mutual funds work end-to-end (pricing, CSV import, risk scoring, performance).
**Result** (2026-03-12): Core pipeline PASSES. Three gaps found and remediated.
**Remediation commit**: `ff78e74c` — InstrumentType `"mutual_fund"`, timing skip with try/finally, 5 normalizer updates (SnapTrade OEF/CEF, Plaid, IBKR statement, realized perf helpers), Schwab position CSV normalizer, 143 tests.
**Plan**: `docs/planning/completed/MUTUAL_FUND_SUPPORT_PLAN.md` (13 Codex review rounds → PASS)
**GAP 3** (factor proxies for fund tickers): Deferred to post-launch.

#### 1C.4 Frontend Logging userId Fix `DONE`

**What**: Server-side userId override in frontend logging (prevents log spoofing in multi-user).
**Status**: Already implemented and verified in `routes/frontend_logging.py:404-420`. All 7 tests pass.

**All 1C tasks DONE.**

---

### 1C4. Market Intelligence Improvements `DONE`

**Commits**: `191cd4ca` (implementation), `2861f677` (NaN fix), `396e415e` (relevance→portfolioRelevance rename)
**Plan**: `docs/planning/completed/frontend/MARKET_INTELLIGENCE_IMPROVEMENTS_PLAN.md`
Expanded from 2 to 6 event sources + portfolio-weighted relevance scoring.

---

## Phase 2 — Build the Product

### 2D. Nav Restructure Implementation `DONE`

**What**: Implement the reconciled nav spec. Biggest frontend change — touches the app shell, routing, and container organization.

**Master plan**: `FRONTEND_NAV_SYNTHESIS_PLAN.md`. **Implementation specs**: `FRONTEND_NAV_PHASES_2_6_SPEC.md`.

| Phase | Task | Spec | Spec status | Impl status | Est. |
|-------|------|------|-------------|-------------|------|
| 2D.0 | Scenarios prep refactors | `completed/frontend/SCENARIOS_PREP_REFACTOR_IMPL_PLAN.md` | PASS | **DONE** | — |
| 2D.0b+1 | Layout toggle + sidebar nav | `CODEX_NAV_LAYOUT_TOGGLE_SPEC.md` + `CODEX_SIDEBAR_NAV_SPEC.md` | Done | **DONE** — `fcc9e02b` | — |
| 2D.2 | Research merge (Factor + Risk + Stock Lookup) | `FRONTEND_NAV_PHASES_2_6_SPEC.md` Phase 2 | Done | **DONE** — `c0055b54` | — |
| 2D.3 | Scenarios overhaul (5 tool views + landing + router) | `SCENARIOS_OVERHAUL_SPEC.md` | Done | **DONE** — `fe5ebb7d` | — |
| 2D.4 | Dashboard enrichment | `CODEX_DASHBOARD_ENRICHMENT_SPEC.md` | Passed review | **DONE** — `c0055b54`, `54239a8c` | — |
| 2D.5 | Trading section | `TRADING_SECTION_PLAN.md` v8 | Passed review | **DONE** — `d5f4c981` | — |
| 2D.6 | Performance enrichment | `FRONTEND_NAV_PHASES_2_6_SPEC.md` Phase 6 | Done | **DONE** — `c0055b54` | — |

**All 2D phases DONE.** Nav restructure complete.

**Key files**:
- `frontend/packages/ui/src/components/dashboard/ModernDashboardApp.tsx`
- `frontend/packages/chassis/src/stores/uiStore.ts`
- `frontend/packages/ui/src/components/containers/` (existing containers to merge)
- `frontend/packages/connectors/src/features/` (hooks for new sections)

---

### 2E-a. C4 Web CSV Import + Normalizer Builder `DONE`

**What**: Full CSV import pipeline with AI-driven normalizer builder for unknown formats.
**Commit**: `22d59176` (Phases 1-3)
**Spec**: `docs/planning/completed/frontend/SPEC_C4_WEB_CSV_IMPORT.md`
**Details**: Backend normalizer builder tools (sample/stage/test/activate/list) + onboarding route rewrite (auto-detect, `needs_normalizer` → chat) + `NormalizerBuilderPanel` frontend (streaming AI, stage→test→activate).
**Follow-up**: Settings path — DONE (`cb06e670`, `/import-csv-full` endpoint).

---

### 2E. Portfolio Selector `DONE`

**What**: Dropdown in header to switch between portfolios.
**Commit**: `0cf65b2c` (infra), `81666402` (scope fixes) — 68 files, 3-layer model, full MCP scoping.
**Spec**: `docs/planning/completed/frontend/PORTFOLIO_SELECTOR_SPEC.md`
**Scope fixes in progress**: Display name resolution (N1), Holdings empty for single account (N2), selector reload (N10). Plan: `PORTFOLIO_SELECTOR_SCOPE_FIX_PLAN.md`.

---

### 2F. Tier 4 Features `DONE`

| # | Feature | Stage | Effort | Spec |
|---|---------|-------|--------|------|
| 11 | ~~Market Intelligence~~ | **DONE** — `191cd4ca` | — | — |
| 2 | ~~AI Insights toggle wiring~~ | **DONE** — `774459ca` | — | `completed/frontend/AI_INSIGHTS_TOGGLE_SPEC.md` |
| 14 | ~~Rebalance trade execution~~ | **DONE** — `98217b77`. Three-step flow, IBKR event loop fix. Live tested. | — | `completed/REBALANCE_EXECUTION_SPEC.md` |
| 12 | Asset Allocation targets | Done — targets UI exists | — | — |
| 34 | AI Assistant intro | **Defer** — current welcome functional | Post-launch | — |

---

## Phase 3 — Ship

### 3G. Tier 5 Polish `DONE`

| # | Task | Stage | Effort |
|---|------|-------|--------|
| 1 | ~~Classic/Premium toggle — preview cards~~ | **DONE** — ToggleGroup + merged Appearance section (`c73b2866`) | — |
| 36b | ~~Risk Management Settings — fix metrics~~ | **DONE** — sensible defaults, removed Compliance tab (`c73b2866`) | — |
| 38 | ~~Account Connections — simplify~~ | **DONE** — major rewrite 316→~14 lines (`c73b2866`) | — |
| — | ~~Hook Migration Batch D (useWhatIfAnalysis)~~ | **DONE** — `f6c1e94b`. 18/18 hooks migrated. | — |
| — | ~~Publish `web-app-platform` npm~~ | **DONE** — v0.1.0 on npm (`c3a2efe9`, `473cfe45`) | — |

**Plan**: `docs/planning/TIER5_POLISH_PLAN.md` (Codex-reviewed)

**Parallelism**: All independent, can run 3-5 Claudes simultaneously.

---

### 3H. Security Review `DONE`

**Audit findings**: `docs/planning/completed/SECURITY_AUDIT_FINDINGS.md` (14-item checklist, completed 2026-03-12)
**Remediation**: `docs/planning/completed/SECURITY_REMEDIATION_PLAN.md` — all 11 steps executed in commit `770be0bf`.
**Scope**: Session secret enforcement, admin auth fix, CORS method/header whitelist, IP-based rate limiting on auth/admin, generic error messages in prod, dep upgrades (47→11 pip audit vulns, happy-dom 17.6.1→20.8.3 RCE fix).

---

### 3I. Final Deploy + Verify

**After** all frontend + backend changes are landed:
1. Final rsync to EC2
2. Run migrations
3. Verify all 7 checks (health, frontend, OAuth, API, CORS, SSL, restart)
4. Smoke test: create account, connect provider, view portfolio

---

### 3K. Public Release Scrub `INVESTIGATION DONE — EXECUTION PENDING`

**Findings**: `docs/deployment/RELEASE_SCRUB_FINDINGS.md` (dry-run completed 2026-03-12)
**Exclusion checklist**: `docs/deployment/PUBLIC_RELEASE_EXCLUSION_CHECKLIST.md`

**Next**: Execute the scrub — remove personal data, hardcoded paths, API key references.
**Reference**: `docs/DEPLOY.md` (package sync), `docs/deployment/PACKAGE_DEPLOY_CHECKLIST.md` (package publish)
**Effort**: 1-2 Claude sessions (execute scrub + verify)

---

## Parallel Execution Map (updated 2026-03-15)

```
COMPLETED: Phase 1 (1A, 1C, 1C4), Phase 2 (2D.0-2D.6, 2E-a, 2E, 2F#2, 2F#14),
           Security (3H), Landing page (3H4), Copy review (3H3),
           E2E review (3H2, 27 issues → ALL FIXED), Onboarding E2E (3I),
           Hook migration (18/18), npm publish (v0.1.0),
           Rebalance execution (98217b77), CSV settings path (cb06e670),
           Portfolio selector core (0cf65b2c), Dev auth bypass (d4bedba8),
           Frontend code execution (007a337e)

VERIFIED (live tested 2026-03-15):
N1, N2, N3, N7, N10 — all working in browser

VERIFIED (live tested 2026-03-15):
N16 ──── Concentration 100 on Combined is CORRECT (max pos 11.8%, top-3 30.6%)

REMAINING:
  ──── 3K release scrub execution
  ──── 1B infra deploy (needs domain name)
  ──── 3J final deploy + verify (last)
```

---

## Progress Tracker

### Phase 1
- [x] **1A** Nav spec reconciliation — DONE (all specs + Phases 2-6 spec written)
- [ ] **1B.0** EBS expansion
- [ ] **1B.1** Production schema dump
- [ ] **1B.2** RDS setup + seed
- [ ] **1B.3** EC2 deploy (code + venv + systemd)
- [ ] **1B.4** Nginx + SSL
- [ ] **1B.5** Vercel frontend deploy
- [ ] **1B.6** Google OAuth production
- [ ] **1B.7** DNS records
- [ ] **1B.8** Monitoring
- [x] **1C.1+1C.2** Cash YAML-only + Pandas fix — DONE (`a16c346d`, all 12 steps)
- [x] **1C.3** Mutual fund E2E verification — VERIFIED, gaps found, remediation plan written
- [x] **1C.3b** Mutual fund gap remediation — DONE (`ff78e74c`, InstrumentType + timing skip + Schwab normalizer, 143 tests)
- [x] **1C.4** Frontend logging userId fix — DONE (already implemented, verified)
- [x] **1C4** Market intelligence — DONE (`191cd4ca`, `2861f677`, `396e415e`)

### Phase 2
- [x] **2D.0** Scenarios prep refactors — DONE (`a595c59f`, `87f3902e`, `5e72235f`)
- [x] **2D.0b+1** Layout toggle + sidebar nav — DONE (`fcc9e02b`, toggle subsumed sidebar spec)
- [x] **2D.2** Research merge — DONE (`c0055b54`)
- [x] **2D.3** Scenarios overhaul — DONE (`fe5ebb7d`, Phases 3a-3c, 5 tool views, 484 tests)
- [x] **2D.4** Dashboard enrichment — DONE (`c0055b54`, `54239a8c`)
- [x] **2D.5** Trading section — DONE (`d5f4c981`, 5 trading + 9 basket + hedge endpoints, 10 hooks, 4-card UI)
- [x] **2D.6** Performance enrichment — DONE (`c0055b54`)
- [x] **2E-a** C4 Web CSV Import + Normalizer Builder — DONE (`22d59176`, Phases 1-3)
- [x] **2E** Portfolio selector — DONE (`0cf65b2c`, `81666402` — 68 files, 3-layer model, full MCP scoping)
- [x] **2E-b** CSV Import Settings Path — DONE (`cb06e670`, `/import-csv-full` endpoint)
- [x] **2F#2** AI Insights toggle — DONE (`774459ca`)
- [x] **2F#14** Rebalance trade execution — DONE (`98217b77`, three-step flow, live tested)

### Phase 3
- [x] **3G.1** Classic/Premium toggle — DONE (`c73b2866`)
- [x] **3G.2** Risk Management Settings — DONE (`c73b2866`)
- [x] **3G.3** Account Connections — DONE (`c73b2866`)
- [x] **3G.4** Hook Migration Batch D — DONE (`f6c1e94b`, 18/18 hooks)
- [x] **3G.5** Publish web-app-platform npm — DONE (v0.1.0, `c3a2efe9`)
- [x] **3H** Security audit + remediation — DONE (`770be0bf`, all 11 steps)
- [x] **3H2** Frontend E2E Review — DONE (27 issues: 1 blocker, 7 major, 15 minor, 4 suggestion)
- [x] **3H2b** Frontend E2E Issue Fixes — DONE (all 27 original issues fixed across 8 batches)
- [x] **3H2c** E2E Re-Audit Fixes (N1-N16) — DONE. All 16 issues resolved. N4 setState warnings fixed (`d455a9fd`). N5 trading 500 fixed (`861c24b0`). Live tested 2026-03-15.
- [x] **3H3** Copy Review — DONE (`173ee3da`, 30 string edits, 14 files)
- [x] **3H4** Landing Page Review — DONE (`7451ed91`, `46a058ad`)
- [x] **3I** Onboarding E2E test — DONE (8 phases pass). Auth fix `c52f2492`.

- [ ] **3J** Final deploy + verify
- [x] **3K.audit** Release scrub investigation — DONE (findings + exclusion checklist written)
- [ ] **3K.exec** Release scrub execution

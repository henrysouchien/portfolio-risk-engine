# Planning TODO — Detailed Implementation Context

**STATUS:** REFERENCE
**Canonical TODO**: [`docs/TODO.md`](../TODO.md) — single source of truth for all work items.

This file contains detailed implementation context for active work items — specs, file paths, architecture notes that help another Claude session pick up work. For the high-level task list, see `docs/TODO.md`.

---

## Brokerage Statement Import — Filesystem Transaction Store — DONE

**Plans**: `completed/transactions/BROKERAGE_STATEMENT_IMPORT_PLAN.md`

### Phase A — Storage + Import Tool: DONE (commit `cb9ba87f`)
### Phase B — Analysis Pipeline Integration: DONE (commit `1699a83d`)
### Pluggable Normalizer + Schwab CSV: DONE (commits `ca69c47e`, `b9a10e0a`)

---

## Workflow Action Price Sanity Check (GLD vs GOLD bug) — MOSTLY DONE

**Status**: Root cause fixed — auto-populate `execution_result` from broker data (commit `f1c6a8cd`).

**Remaining**: Optional price deviation warning in `update_action_status()` (>10% fill vs market → warning). Low priority since the auto-populate fix prevents the original GLD/GOLD ticker mismatch.

---

## Onboarding Wizard — Architecture Notes

**Plan**: `ONBOARDING_WIZARD_PLAN.md` (Codex-reviewed, 35 rounds, PASS)

Key architecture decisions:
- `onboardingFallback` prop on `PortfolioInitializer`
- Deferred exit pattern (`resetQueries` only on "Go to Dashboard")
- Direct `refreshHoldings()` call with store-write guard
- Backend CSV cleanup in `save_positions_from_dataframe()` transaction
- Fail-closed wizard routing lookup

| Phase | Description | Status | Commit |
|-------|-------------|--------|--------|
| 0 | Extract shared components + routing extension | **DONE** | `61bdb81f` |
| 1 | Wizard MVP (Plaid + SnapTrade) | **DONE** | `de315bf3` |
| 2 | Schwab + IBKR flows | **DONE** | `8a319786` |
| 3 | CSV import path | **DONE** | `ce484901` |
| 3b | CSV import + normalizer builder (C4) | **DONE** | Phases 1-3 implemented |
| 3c | CSV import settings path (post-onboarding access) | **DONE** — `cb06e670` | `C4_CSV_IMPORT_SETTINGS_PATH.md` |
| 4 | Polish (error recovery, multi-account, mobile) | Backlog | — |

---

## Multi-User Deployment — Completed Code Items

These subsections are **done** and kept for reference only:

### A. Multi-User Isolation Audit Fix — DONE
Plan: `completed/infrastructure/MULTI_USER_AUDIT_FIX_PLAN.md`. Commit `5027a351`.

### B. DB-Backed Instrument & Ticker Mappings — DONE
Plan: `YAML_DB_SEED_PLAN.md`. Admin tool commit `8e4ace39`. Per-user overrides commit `ba827e05`.

### C. Deployment Code Changes — DONE
Plan: `MULTI_USER_DEPLOYMENT_PLAN.md`. Commits `15138d6e`, `eb8fd989`.

### Gateway User Routing — DONE
Server-side user_id injection into gateway context. Commit `b93a2bd5`.

## Recent Commits (since c73b2866, 2026-03-14/15)

- `be993b71` fix: E2E F9/F10 — enrich position names from FMP profile
- `13bea6de` fix: E2E audit batch 3 — data consistency labels and Settings vol bug
- `8afbe759` fix: E2E audit batch 4 — final Tier 2 quick fixes
- `5fafad59` fix: E2E F11+F27 — partial risk score, historical position labels
- `1f3420c9` fix: E2E audit batch 5 — risk score "Limited data" + hide placeholder t-stats
- `9fa4c9a2` fix: E2E F3 — clarify Holdings scope vs Dashboard total
- `4afa533c` fix: E2E F24 — enrich Dashboard Income Projection card
- `cb06e670` feat: C4 — CSV import from settings page via /import-csv-full endpoint
- `80480a48` fix: E2E F24 — income projection resolver mapping + top contributor sort
- `d4bedba8` feat: dev auth bypass — auto-login without Google OAuth for local testing
- `09a9e311` fix: dev auth — log in as real DB user, not dummy dev@example.com
- `0f6498cf` fix: dev auth bypass — production guard, DB lookup, and observability
- `a6cf9124` test: frontend tests for accounts/portfolios feature (75 tests)
- `2f83eef5` fix: deduplicate portfolio display names when account name includes institution
- `a2998d7a` feat: account activate/deactivate MCP tools with sync-durable deactivation
- `861c24b0` fix: E2E N7 scheduler re-auth reset + N5 graceful empty for trading/income
- `1911fec8` fix: move useMemo above early returns in PortfolioOverviewContainer
- `98217b77` feat: rebalance execution flow + fix IBKR event loop conflict
- `6cb901d4` docs: mark rebalance execution DONE, move spec to completed/
- `3ff6d9cf` fix: E2E re-audit batch 1 — position count excludes cash, margin label
- `06822618` fix: E2E re-audit — allocation rounding + selector invalidation scope
- `007a337e` feat: frontend code execution support — map gateway SSE events to chat UI
- `edd9b8a4` fix: E2E re-audit — alerts portfolio scoping + auth timeout split
- `e6f0b7dd` fix: E2E re-audit N13 — 401 interceptor for session expiry recovery
- `fd2a135b` fix: concentration score uses dual-metric (single-position + top-N basket)

## E2E Re-Audit (2026-03-14) — In Progress

**Findings**: `FRONTEND_E2E_FINDINGS_2026_03_14.md` (16 issues across 2 sessions)
**Fix plan**: `E2E_REAUDIT_FIX_PLAN.md`

### Fixed
- N6 (Blocker): Auth hang — 10s timeout added (`edd9b8a4`)
- N11 (Major): Alerts cross-scope — portfolio scoping (`edd9b8a4`)
- N12 (Major): Position count mismatch — exclude cash (`3ff6d9cf`)
- N14 (Minor): Allocation rounding 100.1% — backend fix (`06822618`)
- N15 (Minor): Cash margin label (`3ff6d9cf`)

### Recently Fixed
- N13 (Major): 401 interceptor / session expiry UX — `e6f0b7dd`
- N16 (Major): Concentration score dual-metric fix — `fd2a135b`
- N5 (Minor): Trading/income 500 on single-account → graceful empty (`861c24b0`)
- N7 (Blocker): Scheduler re-auth reset → no more "Mock" dashes (`861c24b0`)
- PortfolioOverviewContainer hooks crash — useMemo above early returns (`1911fec8`)

### Verified Fixed (live tested 2026-03-15)
- N1 (Major): Portfolio selector display name — shows "Interactive Brokers U2471778" (`2f83eef5`)
- N3 (Minor): Risk settings — loads with sliders and metrics
- N5 (Minor): Trading/income endpoints return 200 (not 500) for single-account portfolios
- N10 (Major): Selector switch — client-side, no page reload
- N16 (Major): Concentration score correct after account deactivation

### Verified Fixed (not a code bug)
- N2 (Major): Holdings empty for single-account — was IBKR Gateway being down (runtime, not code). Works when gateway is up. Verified live 2026-03-15.

### Deferred (accepted)
- N4 (Minor): 7× setState-during-render warnings
- N8 (Major): Rebalance 401 — resolves with N13 (already fixed)
- N9 (Major): Plaid 500 — not a bug (expired credentials)

## Account Activate/Deactivate — DONE

**Plan**: `ACCOUNT_ACTIVATE_DEACTIVATE_PLAN.md` (Codex-reviewed, 5 rounds, PASS)
**Commit**: `a2998d7a`
**What**: MCP tools to deactivate duplicate accounts. `user_deactivated` column survives sync cycles (5 guard points). Atomic cascade via raw cursor SQL. Position filtering reuses `filter_positions_to_accounts()` from portfolio_scope. 14 tests.
**Live tested**: Deactivated SnapTrade IBKR account 4 — combined portfolio 61→51 positions, dropdown 7→6 portfolios. No duplicate IBKR positions.

---

## Bugs — All Resolved (2026-03-17)

All 4 bugs fixed in commit `d6ce4dc6`. Plan: `BUG_FIX_PLAN.md`. Migration tracking fixed separately.

- ~~SLV oversized SELL order~~ — **Fixed**: Live IBKR holdings check via `IBKRClient.get_positions()` at preview + execution time, DB fallback for non-IBKR.
- ~~Schwab token silent invisibility~~ — **Fixed**: Auth errors surfaced before empty-position guard, `auth_warnings` attached to risk tool responses, ERROR-level logging for auth failures.
- ~~`get_orders` perm_id DB error~~ — **Fixed**: `perm_id` column already existed but migration wasn't tracked. All 28 migrations now tracked in `_migrations` table.
- ~~`get_risk_score` consolidation empty~~ — **Fixed**: Post-filter `rebuild_position_result()` in `_load_portfolio_for_analysis()` and `load_portfolio_for_performance()`. Rebuild logic moved to service layer.

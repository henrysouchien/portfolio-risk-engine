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
| 3c | CSV import settings path (post-onboarding access) | **TODO** | `C4_CSV_IMPORT_SETTINGS_PATH.md` |
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

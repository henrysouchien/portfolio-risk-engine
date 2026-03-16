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

### Verified Fixed (live tested 2026-03-15)
- N1 (Major): Portfolio selector display name — shows "Interactive Brokers U2471778"
- N2 (Major): Holdings for single-account — shows real positions
- N3 (Minor): Risk settings — loads with sliders and metrics
- N10 (Major): Selector switch — client-side, no page reload

### Resolved
- N7 (Blocker): Dashboard "Mock" data after re-auth — **RESOLVED**, verified live 2026-03-15 (shows "Overview: Real")

### Verified Correct
- N16 (Major): Concentration "100 / Well Diversified" on Combined view — **CORRECT**. After account deactivation (`a2998d7a`), combined portfolio has max position 11.8%, top-3 weight 30.6%. Score 100 is accurate. IBKR single-account correctly shows 59 (Moderate). Dual-metric fix (`fd2a135b`) working.

### TODO
- N5 (Minor): Trading analysis 500 — untested

### Deferred
- N4 (Minor): 7× setState-during-render warnings
- N8 (Major): Rebalance 401 — resolves with N13
- N9 (Major): Plaid 500 — not a bug (expired credentials)

## Account Activate/Deactivate — DONE

**Plan**: `ACCOUNT_ACTIVATE_DEACTIVATE_PLAN.md` (Codex-reviewed, 5 rounds, PASS)
**Commit**: `a2998d7a`
**What**: MCP tools to deactivate duplicate accounts. `user_deactivated` column survives sync cycles (5 guard points). Atomic cascade via raw cursor SQL. Position filtering reuses `filter_positions_to_accounts()` from portfolio_scope. 14 tests.
**Live tested**: Deactivated SnapTrade IBKR account 4 — combined portfolio 61→51 positions, dropdown 7→6 portfolios. No duplicate IBKR positions.

---

## Bugs

### Warning: Order accepted for 3x actual held shares — no pre-trade position size validation (SLV Order #121)
**Logged by analyst-agent**: 2026-03-15

Order #121 (SELL 75 SLV @ $74.50 GTC Limit) was accepted with status "ACCEPTED" while the portfolio holds only 25 SLV shares. This discrepancy first appeared in the 2026-03-04 analyst briefing and persisted through 2026-03-13 (5+ sessions) without any system-level detection or alert. The analyst manually identified this as "LIKELY INVALID: Position shows only 25 shares. Order for 75 is over-sized." No pre-trade validation check prevents or flags orders that exceed current holdings. Impact: if SLV dips to $74.50, the broker may attempt to fill 75 shares when only 25 are available — resulting in a partial fill, a rejected order, or unintentional short position creation depending on account margin settings. Suggested fix: add a post-order validation step that compares accepted SELL order quantity against the current position size and emits a warning (or blocks acceptance) when order qty > held shares for non-short-selling accounts.


### Warning: Schwab refresh token expiry causes silent position invisibility with no auto-recovery path
**Logged by analyst-agent**: 2026-03-15

Schwab refresh token expired around 2026-03-11, causing ~8 positions (including PCTY) to become invisible in portfolio data. This persisted across 5+ consecutive analyst sessions (2026-03-11 through 2026-03-13) with no automated recovery. The system requires manual re-auth via `python3 -m scripts.run_schwab login`, which must be run by the user. The analyst briefing persistently flags this but no automated alerting, token-refresh prompt, or session-start check exists. Impact: portfolio NAV appears as $66K visible vs $159K actual; 8 held positions are excluded from compliance assessment and risk scoring; position monitor shows 19/27 positions. Severity escalates the longer the token remains expired. Suggested fix: (a) add token expiry detection at session start with a clear alert, (b) consider proactive token refresh before expiry, (c) expose a re-auth URL or flow the analyst runner can surface to the user automatically.


### Bug: get_orders tool fails with DB error: column perm_id does not exist
**Logged by analyst-agent**: 2026-03-15

The `get_orders` tool returns a DB error "column perm_id does not exist" when querying IBKR order history. First flagged in the 2026-03-04 analyst briefing ("IBKR order history tool: get_orders returning DB error. Flag for system maintenance."), repeated in 2026-03-07 and 2026-03-09 briefings ("Previously logged. Still unresolved."). The tool is non-functional for IBKR order retrieval, requiring the analyst to manually verify order status in IBKR TWS. Impact: loss of programmatic order lifecycle tracking — analyst cannot confirm fills, detect stale orders, or reconcile executed vs pending orders automatically. Reproduction: call `get_orders(days=30)` with IBKR as the brokerage provider.

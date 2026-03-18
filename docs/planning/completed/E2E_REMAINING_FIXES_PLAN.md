# E2E Remaining Fixes Plan

**Status**: R6b fixed (`e4e5442a`), R7 not reproducible, R17/R19 done (`2d4a5d06`, `bcd85e6f`), R18 open
**Date**: 2026-03-16
**Source**: `docs/planning/REVIEW_FINDINGS.md` — 4 open items from 22-finding E2E review
**Context**: 18/22 findings fixed across 4 parallel sessions. These are the remaining items.

---

## Task A: R7 — Portfolio Value: Single Account > Combined Total (Critical) — NOT REPRODUCIBLE

**Status**: Not reproducible (2026-03-16). Likely fixed by R8 cash dedup (`8531a6f3`).

**Investigation**: Ran `scripts/diag_portfolio_value.py` against real multi-provider user (id=1, 12 accounts, 4 institutions: interactive_brokers, charles_schwab, merrill, manual). Tested both positions endpoint path (PositionService → consolidation → to_monitor_view) and analyze endpoint path (PortfolioManager → standardize_portfolio_input). Both produce combined ≥ single. No structural code bug found — both paths use the same consolidation logic and `total_portfolio_value = net_exposure + cash_value_usd` formula. CUR:USD correctly summed across providers (ibkr + plaid). R8 noted the same intermittent behavior with margin debt ("changed from $11,212 to $5,606 on subsequent load"). Diagnostic script left in place to catch recurrence.

---

## Task B: R6b — Alert Weight ≠ Table Weight on Same Page (Medium)

**The Problem**: After the R6 fix changed the weight denominator to `total_portfolio_value`, the holdings table shows DSU at 49.5%. But the Smart Alert says "DSU is 38.0% of exposure." Two different weight numbers for the same position on the same page. Also, table weights sum to >100% for levered portfolios (130.1%).

**Root cause** (confirmed by code investigation):

Two code paths use **different denominators**:

| Component | Denominator | File:Line | Includes Cash? |
|-----------|-------------|-----------|----------------|
| **Table weights** | `total_portfolio_value` = `net_exposure + cash_value_usd` | `PositionsAdapter.ts:102-107` | YES |
| **Alert texts** | `gross_non_cash` = sum(abs(non-cash position values)) | `core/position_flags.py:105` | NO |

The alert computes `abs_weight = abs(value) / gross_non_cash * 100.0` at `position_flags.py:125,131`.
The table computes `weight = grossExposure / totalPortfolioValue * 100` at `PositionsAdapter.ts:69`.

**The >100% issue**: For a levered portfolio, `net_exposure > total_portfolio_value` when margin is negative. Weights computed against `total_portfolio_value` (which includes negative cash/margin) will sum to >100%. This is technically correct for a levered portfolio but confusing for users.

**Fix — two changes needed**:

1. **Align alert denominator** (`core/position_flags.py:105`): Change `gross_non_cash` to use `total_portfolio_value` from the payload's `portfolio_totals_usd`. The `_build_monitor_payload()` in `core/result_objects/positions.py:562-564` already computes this value and passes it in the response. Thread it into `build_position_flags()` and use it as the denominator.

2. **Cap weight display at 100% total** or **label column as "% of Equity"**: Either:
   - (a) Use `gross_exposure` (always positive, sums to ~100%) as denominator for both table and alerts — reverting R6's denominator change but keeping the new field available, OR
   - (b) Keep `total_portfolio_value` but add "(leveraged)" label when weights sum >100%, OR
   - (c) Change column header from "Weight" to "% of NAV" to signal it can exceed 100% for margin accounts

**Files**:
- `core/position_flags.py:105,125,131,178,402` — alert weight computation using `gross_non_cash`
- `core/result_objects/positions.py:539-564` — `portfolio_totals_usd` with `total_portfolio_value`
- `frontend/packages/connectors/src/adapters/PositionsAdapter.ts:69,102-107` — table weight denominator

**Testing**:
- Alert % should match table weight % for the same position
- Weights should sum to ≤100% for unleveraged portfolios
- For leveraged portfolios, either weights sum to ≤100% (if using gross_exposure) or the UI clearly indicates leverage

---

## Task C: R17 — Deduplicate Remaining API Requests (Medium) — ✅ DONE

**Commit**: `2d4a5d06`
**Result**: 31 → 20 data requests (target ≤20). Remaining 2× for lazy sources is React.StrictMode dev-only (~15 in production).
**Plan**: `docs/planning/API_REQUEST_DEDUP_PLAN.md` (v3, Codex-reviewed, all phases PASS)

**What was done** (6 phases):
1. `usePortfolioList` staleTime 0→30s + removed unnecessary mount from DashboardIncomeCard
2. Fixed scheduler query-key mismatch for portfolio-summary + cache seeding from resolver
3. Removed PortfolioInitializer broad `['sdk']` invalidation
4. Removed redundant manual EventBus handlers from 6 containers
5. Consolidated useSmartAlerts ownership (3 mounts → 1 via useNotifications)
6. Deferred useTradingAccounts in AssetAllocationContainer

---

## Task D: R19 — Dark Mode CSS Completion (Medium) — ✅ DONE

**Commits**: `2d4a5d06`, `bcd85e6f`
**Plan**: `docs/planning/DARK_MODE_COMPLETION_PLAN.md` (v3, Codex-reviewed, all phases PASS)

**What was done** (6 phases):
1. 38 dark CSS var overrides + destructive tokens (WCAG AA) + sidebar tokens + gradient dark overrides
2. Theme toggle in SettingsPanel (draft-then-commit) + localStorage persistence + SettingsPanel class migration
3. Navigation shell migration (AppSidebar, NavBar, ModernDashboardApp)
4. Dashboard components + chart theming (overview, cards, holdings, chart-theme.ts)
5. Content view components (scenarios, trading, performance, research)
6. Block components + shared UI (gradient-progress, notification-center, LoadingSpinner, etc.)

Also fixed: notification dropdown hidden behind content (glass-premium overflow:hidden → visible, fixed positioning with z-[200])

---

## Execution Notes

- **Task A (R7)**: Not reproducible — closed.
- **Task B (R6b)**: Fixed (`e4e5442a`).
- **Task C (R17)**: ✅ Done (`2d4a5d06`).
- **Task D (R19)**: ✅ Done (`2d4a5d06`, `bcd85e6f`).
- **R18 (spontaneous logout)**: Remains open — multi-layer auth issue requiring backend + frontend changes.

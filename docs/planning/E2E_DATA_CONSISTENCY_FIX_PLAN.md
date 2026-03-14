# E2E Data Consistency Fix Plan

**Status**: TODO
**Created**: 2026-03-14
**Reviewed**: 2026-03-14 (Codex review)
**Source**: `FRONTEND_ISSUES_2026_03_13.md` — issues F3, F4, F5, F6, F8
**Goal**: Resolve the data inconsistency issues found in the E2E audit so every view shows coherent, correctly-labeled numbers.

---

## Root Cause Summary (post-review)

| Issue | What user sees | Root cause (verified) |
|-------|---------------|------------|
| F3 | Portfolio value $109K (Dashboard) vs $27K (Holdings) | Dashboard uses `PortfolioSummaryAdapter` → `app.py` pipeline (includes cash/proxy holdings). Holdings uses `routes/positions.py` → `portfolio_scope.py` scope resolution + `to_monitor_view()` which drops cash. Different pipelines, different scopes. |
| F4 | Alpha -2.2% (Dashboard) vs -9.3% (Performance) | Dashboard = CAPM alpha (annualized OLS). Performance = `portfolio_return - benchmark_return` (naive excess). Both valid, mislabeled. |
| F5 | Volatility 47.7% / 8.3% / 0.1% across 3 views | Holdings = avg of individual stock vols. Performance = portfolio std dev. Settings = divides already-percentage by 100 (**bug**). |
| F6 | DSU, STWD, MSCI in analytics but not in holdings | **Cross-source holding leakage** — realized performance engine flags these as `cross_source_holding_leakage_symbols` (positions leaking from another provider/account scope). |
| F8 | React setState-during-render warning | Down from 6 to 1 after batch 1. Remaining warning in `ModernDashboardApp` — **could not reproduce in current code**. May need fresh stack trace. |

---

## Step 1: Fix Settings volatility display bug (F5c) `PASS`

**The bug**: `RiskSettingsViewModern.tsx:141-142` divides `portfolio_volatility` by 100. Backend returns **percentages already** (confirmed: `performance_metrics_engine.py:262` multiplies by 100 before serializing, passed through unchanged by `PerformanceAdapter.ts:734` and `useRiskMetrics.ts:84`).

**File**: `frontend/packages/ui/src/components/dashboard/views/modern/RiskSettingsViewModern.tsx`

**Changes**:
- Line 136-137: Fix comment (says "basis points" — wrong, data is percentages)
- Line 141-142: Remove `/ 100` for `portfolioVolatility` → display `rawMetrics.portfolio_volatility.toFixed(1)%`
- Line 144-146: Same fix for `max_drawdown`

**Verify**: Settings should show ~8.3% (matching Performance), not 0.1%.

**Effort**: Quick (5 min)

---

## Step 2: Relabel Holdings "AVG VOLATILITY" (F5a) `PASS`

**The problem**: `useHoldingsData.ts:89` computes arithmetic mean of individual stock volatilities. Label misleads users into thinking it's portfolio-level.

**Files**:
- `frontend/packages/ui/src/components/portfolio/holdings/useHoldingsData.ts:89` — calculation (correct, just mislabeled)
- `frontend/packages/ui/src/components/portfolio/holdings/HoldingsSummaryCards.tsx:48` — **render target** for the label

**Change**: In `HoldingsSummaryCards.tsx:48`, change title from "AVG VOLATILITY" to "Avg. Stock Vol" and add subtitle "Mean of individual positions" so it's clear this is not portfolio-level volatility.

**Effort**: Quick (10 min)

---

## Step 3: Label alpha metrics distinctly (F4) `PASS (with file corrections)`

**The problem**: Both labeled "Alpha" but compute different things.

**Files to change** (corrected by Codex review):
- `frontend/packages/ui/src/components/portfolio/performance/PerformanceHeaderCard.tsx:210` — main "Alpha" label
- `frontend/packages/ui/src/components/portfolio/performance/PeriodAnalysisTab.tsx:62` — period alpha label
- `frontend/packages/ui/src/components/portfolio/performance/BenchmarksTab.tsx:61` — benchmark alpha label
- `frontend/packages/ui/src/components/portfolio/performance/helpers.ts:46` — tooltip text
- `frontend/packages/ui/src/components/dashboard/views/modern/PerformanceViewContainer.tsx:352` — field name in data mapping

**Changes**:
1. In all Performance view files above: rename "Alpha" → "Excess Return" (or "Active Return")
2. Update tooltip in `helpers.ts:46`: "Excess return measures portfolio return minus benchmark return"
3. Dashboard alpha (`useOverviewMetrics.ts`) stays as "Alpha Generation" (already qualified with "risk-adjusted" subtitle)

**Effort**: Quick (20 min)

---

## Step 4: Fix portfolio value mismatch (F3) `NEEDS DEEPER INVESTIGATION`

**Codex finding**: The $109K vs $27K gap is NOT caused by frontend asset-class filtering. The two numbers come from **completely different backend pipelines**:

- **Dashboard $109K**: `PortfolioSummaryAdapter` → `app.py` pipeline. May include cash, proxy holdings, and merged refresh state from `PortfolioManager`/`SessionServicesProvider`.
- **Holdings $27K**: `routes/positions.py` → `portfolio_scope.py` scope resolution → `to_monitor_view()` (drops cash positions).

**Root causes to investigate**:
1. **Scope resolution**: `portfolio_scope.py:141` — how does scope differ between the two pipelines?
2. **Cash treatment**: `to_monitor_view()` in `core/result_objects/positions.py:570` drops cash — Dashboard includes it?
3. **Refresh state merge**: `PortfolioManager.ts:840` and `SessionServicesProvider.tsx:320` may merge stale/live data

**Interim fix** (Quick):
- Add subtitle to Dashboard "Total Portfolio Value" card: "Across all accounts"
- This sets expectation that Dashboard is a broader view

**Proper fix** (Medium-Large):
- Align both pipelines to use the same scope resolution
- Or clearly label each view's scope (e.g., Holdings shows "IBKR Equity" vs Dashboard shows "All Accounts")

**Effort**: Quick (interim, 10 min) / Medium-Large (proper fix, 2-3 hrs investigation + implementation)

---

## Step 5: Fix phantom positions (F6) `ROOT CAUSE IDENTIFIED`

**Codex finding**: The phantom positions (DSU, STWD, MSCI) are caused by **cross-source holding leakage** in the realized performance engine.

**Evidence**:
- `core/realized_performance/engine.py:2443` flags `CROSS_SOURCE_HOLDING_LEAKAGE`
- `core/realized_performance/engine.py:2914` emits `cross_source_holding_leakage_symbols` — explicitly names DSU, MSCI, STWD
- Confirmed in test output: `docs/planning/completed/performance-actual-2025/live_test/system_output_post_latest_full.json:1879`

**What's happening**: Positions from one brokerage/provider are leaking into another provider's scope during realized performance calculation. The leakage detection exists but doesn't prevent the leaked positions from appearing in the UI.

**Fix options**:

**Option A (recommended)**: Filter leaked positions from the frontend display.
- The engine already identifies `cross_source_holding_leakage_symbols` — pass this list through the API response
- Frontend filters these out of attribution/contributor tables, or labels them as "excluded — cross-source"

**Option B**: Fix the leakage at the engine level.
- Investigate why positions leak across sources in `engine.py`
- This is a deeper fix that addresses the root cause but is higher risk
- Note: `CROSS_SOURCE_HOLDING_LEAKAGE` detection was already built (commit `357aebe4`) — the fix may just need to be more aggressive in excluding leaked positions

**Option C**: Suppress in the UI only.
- Performance attribution views filter out any position not in the current holdings list
- Quick but masks the underlying issue

**Recommendation**: Option A — use the existing leakage detection to filter/label in the API response.

**Effort**: Medium (1-2 hrs)

---

## Step 6: Fix remaining React setState warning (F8) `DEFERRED — CANNOT REPRODUCE`

**Codex finding**: No setState-during-render pattern found in current `ModernDashboardApp.tsx`. State updates are already inside `useEffect` blocks (lines 210, 329).

**Status**: The warning was observed during the E2E audit but may have been fixed in subsequent commits, or may only trigger under specific timing/data conditions.

**Action**: Defer until reproducible. If the warning reappears:
1. Capture the full stack trace from the console
2. Identify which setState call fires during render
3. Wrap in `useEffect`

**Effort**: Deferred (0 min now, Quick when reproducible)

---

## Execution Plan

### Batch 1: Quick fixes (Steps 1-3 + interim Step 4) — ~45 min

All frontend label/formatting changes. One commit.

| File | Change |
|------|--------|
| `RiskSettingsViewModern.tsx:141-146` | Remove `/ 100` for vol and drawdown |
| `HoldingsSummaryCards.tsx:48` | "AVG VOLATILITY" → "Avg. Stock Vol" + subtitle |
| `PerformanceHeaderCard.tsx:210` | "Alpha" → "Excess Return" |
| `PeriodAnalysisTab.tsx:62` | "Alpha" → "Excess Return" |
| `BenchmarksTab.tsx:61` | "Alpha" → "Excess Return" |
| `helpers.ts:46` | Update tooltip text |
| Dashboard Total Portfolio Value card | Add "Across all accounts" subtitle |

### Batch 2: Phantom positions fix (Step 5) — ~1-2 hrs

Use existing `cross_source_holding_leakage_symbols` detection to filter leaked positions from performance API responses.

### Batch 3: Portfolio scope investigation (Step 4 proper fix) — ~2-3 hrs

Investigate `portfolio_scope.py` + `PortfolioSummaryAdapter` pipeline divergence. Align or label clearly.

**Total effort**: ~4-6 hours across 3 batches
**Step 6**: Deferred until reproducible.

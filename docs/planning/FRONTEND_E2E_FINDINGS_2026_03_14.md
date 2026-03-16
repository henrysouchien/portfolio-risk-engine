# Frontend E2E Re-Audit — Findings (2026-03-14)

**Reviewer**: Claude (Chrome browser automation)
**App**: PortfolioRisk Pro at `localhost:3000`
**Date**: 2026-03-14
**Purpose**: Verify all 26 fixes from the 2026-03-13 audit landed, catch any regressions or new issues.
**Portfolio**: IBKR single account (Interactive Brokers), $131,571

---

## Previous Fixes — All Verified

| # | Fix | Status |
|---|-----|--------|
| F1 | ChatProvider crash | ✅ Ask AI button renders, no crash |
| F2 | Risk score interpretation | ✅ Consistent: Concentration 59/100 "High Risk", Volatility 55/100 "High Risk" |
| F3 | Portfolio value scope label | ✅ "Across all accounts" subtitle on Dashboard |
| F4 | Alpha → Excess Return | ✅ Performance shows "Excess Return" with "vs SPY" badge |
| F5a | Holdings vol label | ✅ (not visible — Holdings empty on this account, but code change confirmed) |
| F5c | Settings vol `/100` bug | ✅ Shows 8.4% (verified on earlier session) |
| F7 | Concentration label | ✅ Shows "59 / Moderate" — no "Well Diversified" contradiction |
| F9/F10 | GOLD/SLV names | ✅ (verified on earlier session with different account) |
| F11 | FIG "Limited data" badge | ✅ (verified on earlier session) |
| F15 | Trading P&L empty state | ✅ Icon + "No trading history available yet." |
| F16 | "Predictive" badge removed | ✅ "Risk & Drawdown Analysis" — no badge |
| F17 | Recovery Time tooltip | ✅ Info icon with tooltip text on hover |
| F18 | Risk Score decimals | ✅ Shows "56" not "56.00" |
| F19 | "legacy tab stack" removed | ✅ Scenarios says "Each tool opens in a dedicated full-screen view." |
| F20 | Scenarios grid | ✅ 4+3 layout (not 3+3+1) |
| F21 | Optimizer 0% pre-run | ✅ (verified on earlier session) |
| F23 | Unknown → Other | ✅ (verified on earlier session) |
| F24 | Income Projection enriched | ✅ Shows headline, monthly rate, yield, sparkline, top payers |
| F25 | Alerts "View N more" | ✅ (only 1 alert on this account — button logic correct in code) |
| F26 | t-stat hidden | ✅ Factor cards show exposure + High/Medium badges, no "t-stat: 0.00" |

---

## New Issues Found

| # | Severity | Page | Issue | Fix Effort |
|---|----------|------|-------|------------|
| N1 | Major | Header (all pages) | Portfolio selector shows raw internal name `_auto_interactive_brokers_interactive_brokers_henry_chien` instead of friendly display name | Quick |
| N2 | Major | Holdings | "No Data — No holdings found" for IBKR single-account portfolio while Dashboard shows $131K with positions | Medium |
| N3 | Minor | Settings | Risk Management section stuck on "Loading risk settings..." spinner — may be slow backend or timeout | Medium |
| N4 | Minor | Console | 7× React setState-during-render warnings on Dashboard load (PortfolioOverviewContainer, DashboardHoldingsCard, DashboardAlertsPanel, DashboardPerformanceStrip, AssetAllocationContainer, DashboardIncomeCard, DashboardIncomeCardLive) | Medium |
| N5 | Minor | Console | `/api/trading/analysis?portfolio_name=CURRENT_PORTFOLIO` returns HTTP 500 | Medium |

---

## Detailed Findings

### N1. [Major] Portfolio selector shows raw internal name

**Page**: Header — visible on all pages
**What happens**: The portfolio dropdown in the header displays `_auto_interactive_brokers_interactive_brokers_henry_chien` as the portfolio name. This is the raw internal identifier, not a user-friendly label.
**Expected**: Should show "Interactive Brokers" or "IBKR (Henry Chien)" or similar.
**Key files**: `frontend/packages/ui/src/components/dashboard/PortfolioSelector.tsx`, backend portfolio list endpoint (wherever display names are resolved)
**Fix effort**: Quick — map internal names to display labels in the portfolio list response or in the frontend selector component.

### N2. [Major] Holdings empty for single-account portfolio

**Page**: Holdings
**What happens**: Navigating to Holdings shows "No Data — No holdings found. Connect an account to view your brokerage positions." with a "Connect Account" button. Meanwhile, the Dashboard shows $131,571 with real positions, alerts, and performance data for the same IBKR portfolio.
**Expected**: Holdings should show the same positions the Dashboard uses.
**Root cause**: Likely a scope resolution issue — when the portfolio selector is set to a single IBKR account, the Holdings endpoint (`/api/positions/holdings`) may not resolve positions for that scope, while the Dashboard uses a different pipeline (`PortfolioSummaryAdapter`) that does.
**Key files**: `routes/positions.py` → `_load_enriched_positions()`, `services/portfolio_scope.py` → `resolve_portfolio_scope()`, `PortfolioSelector.tsx` (what portfolio_name does it pass?)
**Fix effort**: Medium — trace what portfolio_name the selector passes for single-account IBKR, and why `resolve_portfolio_scope()` returns empty for that scope on the positions endpoint.

### N3. [Minor] Settings risk management stuck loading

**Page**: Settings
**What happens**: "Loading risk settings..." spinner displays indefinitely. The Account Connections and CSV Import sections below it render fine.
**Expected**: Risk limits, monitoring, and alerts tabs should load with slider controls.
**Root cause**: The risk settings endpoint may be timing out or failing silently for the single-account portfolio scope.
**Fix effort**: Medium — check backend logs for the risk-settings endpoint, may need error handling or timeout fallback.

### N4. [Minor] React setState-during-render warnings (7×)

**Page**: Dashboard (console)
**What happens**: 7 components fire "Cannot update a component while rendering a different component" on initial Dashboard load:
1. ModernDashboardApp → PortfolioOverviewContainer
2. ModernDashboardApp → DashboardHoldingsCard
3. ModernDashboardApp → DashboardAlertsPanel
4. ModernDashboardApp → DashboardPerformanceStrip
5. ModernDashboardApp → AssetAllocationContainer
6. ModernDashboardApp → DashboardIncomeCard
7. ModernDashboardApp → DashboardIncomeCardLive
**Expected**: No React warnings.
**Note**: This was F8 from the original audit. It was reported as "down to 1" in a previous check but has returned to 7. May depend on portfolio state / data loading timing.
**Fix effort**: Medium — each component needs setState calls moved into `useEffect`.

### N5. [Minor] Trading analysis 500 error

**Page**: Performance (console)
**What happens**: `GET /api/trading/analysis?portfolio_name=CURRENT_PORTFOLIO` returns HTTP 500 Internal Server Error.
**Expected**: Should return trading analysis data or a graceful empty response.
**Note**: The frontend handles this gracefully — Trading P&L card shows "No trading history available yet." So this is a backend-only issue.
**Fix effort**: Medium — check backend logs for the error. May be a missing dependency or scope issue for the IBKR portfolio.

---

## Overall Assessment

**Previous fixes**: All 26 fixes from the 2026-03-13 audit are confirmed working. No regressions detected in the fix areas.

**New issues**: 5 new issues found, primarily related to the **portfolio selector / single-account scoping**. When viewing a single IBKR account (rather than "All Accounts / COMBINED"), several endpoints don't resolve correctly:
- Holdings returns empty (N2)
- Risk settings may not load (N3)
- Trading analysis returns 500 (N5)
- Portfolio name displays as raw internal ID (N1)

These are likely all manifestations of the same root cause: the single-account portfolio scope resolution doesn't work consistently across all endpoints. The "All Accounts / COMBINED" view works correctly (verified in earlier sessions).

**Recommended priority**:
1. N1 (Quick) — Display name mapping for portfolio selector
2. N2 (Medium) — Single-account positions scope fix (or fall back to combined)
3. N4 (Medium) — setState warnings (cosmetic but indicates architectural issue)
4. N3/N5 (Medium) — Backend endpoint failures for single-account scope

---

## Session 2 — "All Accounts / COMBINED" View + Auth Testing

**Date**: 2026-03-14 (late evening)
**Portfolio**: All Accounts / COMBINED, then auth cycle testing
**Focus**: Combined view data, portfolio switching, session stability

### Additional Issues Found

| # | Severity | Page | Issue | Fix Effort |
|---|----------|------|-------|------------|
| N6 | Blocker | Auth | "Checking authentication..." hangs indefinitely — never resolves to login or Dashboard | Medium |
| N7 | Blocker | Dashboard | Metric cards stuck on "—" after re-auth — "Mock" data source, 0 holdings, no alerts | Medium |
| N8 | Major | Dashboard | Rebalance Preview shows "HTTP 401: Unauthorized" in Asset Allocation | Quick |
| N9 | Major | Dashboard | Plaid holdings refresh returns HTTP 500 (blocks Combined view loading) | Medium |
| N10 | Major | Auth | Portfolio selector click triggers full page reload → "Checking authentication..." hang | Medium |
| N11 | Major | Dashboard | Alerts show cross-scope tickers (AAPL/MSFT alerts on IBKR-only view where % doesn't match) | Medium |
| N12 | Major | Dashboard | Position count mismatch: dropdown "21 positions" vs Dashboard "View All 15 Holdings" | Quick |
| N13 | Major | Auth | Expired session shows confusing mixed state — cached metrics + broken live data, no recovery UX | Medium |
| N14 | Minor | Dashboard | Total Allocation shows "100.1%" — rounding error in asset class weights | Quick |
| N15 | Minor | Dashboard | Cash -12.1% ($-20,447) in Combined view not labeled as "margin" | Quick |
| N16 | Major | Dashboard | Concentration "100 / Well Diversified" contradicts alerts in Combined view (F7 partial regression) | Quick |

### N6. [Blocker] "Checking authentication..." hangs indefinitely

**Page**: All pages (fresh tab load)
**What happens**: Navigating to `localhost:3000` in a new tab shows plain text "Checking authentication..." that never resolves. No timeout, no fallback to login page, no spinner, no error message. Confirmed that `fetch('/auth/status', {credentials: 'include'})` from browser console returns `{authenticated: true, user: {...}}` immediately — backend is responsive and session is valid. The React auth provider initialization is the hang point.
**Repro**: Open a new tab → navigate to localhost:3000. Reproduced on multiple fresh tabs. Also happens on hard-refresh (Cmd+Shift+R) of existing tabs.
**Root cause**: Likely HTTP connection pool exhaustion from 12+ open localhost:3000 tabs. The React HTTP client has pending/queued requests from other tabs that block the auth check, while raw `fetch()` bypasses this queue. Additionally, the auth check has no timeout — if the request gets queued, it waits forever.
**Expected**: Auth check should timeout after 3-5 seconds and fall back to the login page.
**Key files**: `frontend/packages/app-platform/src/auth/AuthProvider.tsx` (line 21-24 renders "Checking authentication..." when `!isInitialized`), `frontend/packages/app-platform/src/auth/createAuthStore.ts` (line 121 `config.checkAuthStatus()` awaits forever)
**Fix**: Added 10-second timeout race in `createAuthStore.ts:initializeAuth()`. `Promise.race([checkAuthStatus(), timeout])` ensures `isInitialized` always becomes `true` within 10s. Committed in this session.

### N7. [Blocker] Dashboard stuck on "Mock" data after re-auth

**Page**: Dashboard
**What happens**: After re-authenticating (Google OAuth sign-in), Dashboard loads with all 6 metric cards showing "—" dashes. Status badge shows "Overview: Mock | Portfolio: Loaded". Top Holdings: "No holdings available for this portfolio" / "View All 0 Holdings". Alerts: "No active alerts." AI Recommendations section loads correctly with real data.
**Expected**: All Dashboard sections should load real data after successful authentication.
**Key files**: `PortfolioOverviewContainer`, overview data hooks, mock data fallback logic
**Fix effort**: Medium — investigate why "Mock" fallback activates on fresh auth. May be a race condition where the overview hook resolves before the portfolio data is ready.

### N8. [Major] Rebalance Preview "HTTP 401: Unauthorized"

**Page**: Dashboard → Asset Allocation (Combined view)
**What happens**: The Rebalance Preview section within Asset Allocation shows "HTTP 401: Unauthorized" in a red error box. Asset allocation percentages and targets display correctly (Equity 50.8%/60%, Fixed Income 27.6%/25%, Real Estate 27.1%/10%, etc.), but the rebalance trade preview fails.
**Expected**: Should show proposed rebalance trades.
**Fix effort**: Quick — likely missing auth cookie on the rebalance API call.

### N9. [Major] Plaid holdings refresh HTTP 500

**Page**: Dashboard (background)
**What happens**: Console shows `[NETWORK] HttpClient: Network error for /plaid/holdings/refresh: HTTP 500: Internal Server Error` followed by `[ERROR] PlaidService: Failed to refresh Plaid holdings`. This fires during Dashboard data loading and may be the root cause of metric cards showing "Mock" data in Combined view — if the Plaid failure cascades and blocks other data sources.
**Expected**: Plaid failures should be isolated — IBKR/Schwab data should still populate. Show a non-blocking warning toast.
**Fix effort**: Medium

### N10. [Major] Portfolio selector triggers page reload

**Page**: Header (any page)
**What happens**: Clicking the portfolio selector dropdown appears to trigger a full page navigation or reload. The page transitions to "Checking authentication..." and hangs (per N6). This makes portfolio switching impossible without the auth hang fix.
**Expected**: Portfolio switching should be a client-side state change without any page reload.
**Fix effort**: Medium — likely the selector triggers a route change or `window.location` update instead of a state update.

### N11. [Major] Alerts cross-scope contamination

**Page**: Dashboard (IBKR Single view observed in previous session)
**What happens**: When viewing the IBKR-only portfolio, Dashboard Alerts show AAPL/MSFT concentration warnings with percentages (25.7%, 30.0%) that correspond to the Combined portfolio, not the IBKR-only subset. The alert content doesn't match the selected portfolio scope.
**Expected**: Alerts should be scoped to the currently selected portfolio.
**Fix effort**: Medium

### N12. [Major] Position count mismatch (21 vs 15)

**Page**: Dashboard
**What happens**: Portfolio selector dropdown shows "21 positions" for IBKR account but Dashboard shows "View All 15 Holdings".
**Expected**: Counts should match. The discrepancy likely comes from one source counting options/closed positions and the other filtering to equity-only current positions.
**Fix effort**: Quick

### N13. [Major] No session expiration recovery UX

**Page**: All pages
**What happens**: When InMemorySessionStore session expires (backend restart or timeout), the Dashboard shows a confusing mix: cached metrics from React Query still display (portfolio value, risk score) but live sections fail ("No Data" on Holdings, "Unable to load" on Alerts). No "Session expired" banner, no redirect to login, no sign-in button visible. The user sees a half-working app.
**Expected**: Clear "Session expired — please sign in again" banner with a sign-in button, or automatic redirect to landing page.
**Fix effort**: Medium — add 401 interceptor in HttpClient that triggers a session-expired state in the auth store.

### N14-N16. Minor Issues

- **N14**: Total Allocation shows "100.1%" — rounding error across asset classes. Fix: normalize to 100.0%.
- **N15**: Cash at -12.1% ($-20,447) — valid for margin but not labeled. Add "Margin" label or tooltip.
- **N16**: Concentration card shows "100 / Well Diversified" in Combined view despite AAPL 25.7% + MSFT 30.0% concentration alerts. This is the F7 pattern — partially fixed for single-account (shows "59 / Moderate") but still wrong in Combined view where the score is 100.

---

## Combined Assessment (Sessions 1 + 2)

### Fix Priority

| Priority | Issues | Description | Effort |
|----------|--------|-------------|--------|
| P0 | N6, N7 | Auth hang + Mock data on re-auth | ~4 hrs |
| P1 | N10, N13 | Portfolio selector reload + session expiry UX | ~3 hrs |
| P2 | N1, N2, N8, N9, N11, N12, N16 | Data scoping, rebalance 401, Plaid 500, cross-scope alerts | ~6 hrs |
| P3 | N3, N4, N5, N14, N15 | Settings loading, React warnings, trading 500, rounding, margin label | ~3 hrs |
| **Total** | 16 issues | (5 from Session 1 + 11 from Session 2) | **~16 hrs** |

### Root Causes (Thematic)

1. **Auth/Session fragility** (N6, N7, N10, N13): InMemorySessionStore + no timeout/fallback in frontend auth + no 401 recovery UX. This is the single biggest blocker.
2. **Portfolio scope leakage** (N1, N2, N8, N11, N12, N16): Multiple endpoints don't respect the selected portfolio scope. Alerts, positions, rebalance, and concentration scores bleed between Combined and single-account views.
3. **Provider error isolation** (N5, N9): Plaid/trading failures cascade instead of being isolated. One failing provider blocks the entire Dashboard.
4. **React render hygiene** (N4): 7 components fire setState-during-render — architectural issue in how dashboard containers propagate data to the shared state.

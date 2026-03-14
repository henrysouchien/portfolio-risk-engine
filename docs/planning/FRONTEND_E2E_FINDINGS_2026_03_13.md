# Frontend E2E Review — Findings (2026-03-13)

**Reviewer**: Claude (Chrome browser automation)
**App**: PortfolioRisk Pro at `localhost:3000`
**Date**: 2026-03-13
**Status**: Complete — all pages reviewed

---

## Summary Table

| # | Severity | Page | Issue | Fix Effort |
|---|----------|------|-------|------------|
| 1 | Blocker | Dashboard | `useSharedChat` crash — AskAIButton outside ChatProvider (36+ console errors) | Medium |
| 2 | Major | Dashboard / Research | Risk score interpretation inverted: 100/100 = warning on Dashboard, "Low Risk" on Research | Medium |
| 3 | Major | Dashboard vs Holdings | Total Portfolio Value $109,808 (Dashboard) vs $27,187 (Holdings) — 4x mismatch | Large |
| 4 | Major | Performance vs Dashboard | Alpha shows -2.2% on Dashboard, -9.3% on Performance | Medium |
| 5 | Major | Multiple | Volatility inconsistency: 47.7% (Holdings), 8.3% (Performance), 0.1% (Settings) | Medium |
| 6 | Major | Research / Performance | Phantom positions: DSU, STWD, MSCI, ENB, CBL appear in analytics but not in 15 holdings | Large |
| 7 | Major | Dashboard | Concentration card says "100 / Well Diversified" but alerts say "Concentration Risk: 100/100" with warning | Quick |
| 8 | Major | Dashboard | 6x React setState-during-render warnings on initial load (PortfolioOverviewContainer, DashboardHoldingsCard, etc.) | Medium |
| 9 | Minor | Holdings | GOLD ticker shows "Gold.com, Inc." (Financial Services) — should be Barrick Gold (Materials) | Quick |
| 10 | Minor | Holdings | SLV shows "BlackRock Institutional Trus..." (Financial Services) — should be iShares Silver Trust ETF | Quick |
| 11 | Minor | Holdings | FIG risk score shows "—" (missing data) while all other positions have scores | Quick |
| 12 | Minor | Holdings | Footer badge shows "Accounts: 0" despite 15 real holdings loaded | Quick |
| 13 | Minor | Sidebar Nav | Icon-only navigation with no tooltips on hover — users can't discover what each icon does | Quick |
| 14 | Minor | Holdings | Company names truncated without hover tooltips (e.g., "Figma Inc. Class ...", "Ashtead Technolog...") | Quick |
| 15 | Minor | Performance | Trading P&L card shows "Trading analysis data is unavailable." — poor empty state, no icon or CTA | Quick |
| 16 | Minor | Performance | Risk Analysis tab — "Predictive" badge on Maximum Drawdown, which is a historical metric | Quick |
| 17 | Minor | Performance | Recovery Time and Tracking Error both show "--" with no explanation | Quick |
| 18 | Minor | Dashboard | Risk Score "89.00" — unnecessary decimal places for a round number | Quick |
| 19 | Minor | Scenarios | "Choose a full-width workflow" subtitle mentions "legacy tab stack" — developer-facing language | Quick |
| 20 | Minor | Scenarios | Tax Harvest card alone on third row — unbalanced 3+3+1 grid layout | Quick |
| 21 | Minor | Strategy | Optimize view shows all "Optimal" weights at 0.0% before running — misleading pre-run state | Quick |
| 22 | Minor | Settings | No visual style toggle (classic/premium) or benchmark selector visible | Quick |
| 23 | Minor | Performance | Sector Attribution shows "Unknown" sector at -0.6% — uncategorized holdings | Quick |
| 24 | Suggestion | Dashboard | Income Projection section ($122/yr, $10/mo) is very sparse — could use breakdown or trend | Quick |
| 25 | Suggestion | Dashboard | Alerts section: "View all 7" link — 5 shown, 7 total, consider showing count remaining | Quick |
| 26 | Suggestion | Research | Factor Exposure t-stat values all show 0.00 — check if these are being computed | Medium |
| 27 | Suggestion | Performance | Top Contributors/Detractors include historical positions without labeling them as "closed" | Quick |

---

## Detailed Findings

### 1. [Blocker] AskAIButton crashes — useSharedChat outside ChatProvider

**Page**: All pages (Dashboard observed)
**What happens**: `ArtifactAwareAskAIButton` in `ModernDashboardApp.tsx` calls `useSharedChat()` but is rendered outside a `ChatProvider`. This triggers 36+ `Error: useSharedChat must be used within a ChatProvider` console errors. The component falls back to `ChunkErrorBoundary`.
**Expected**: The "Ask AI" FAB button should render without errors.
**Key files**: `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx:114`, `frontend/packages/ui/src/components/chat/ChatContext.tsx:23`
**Fix effort**: Medium — wrap `ArtifactAwareAskAIButton` in `ChatProvider` or add a guard to check for context.

### 2. [Major] Risk score interpretation inverted between Dashboard and Research

**Page**: Dashboard Alerts vs Research → Risk Analysis
**What happens**: Dashboard Alerts shows "Concentration Risk: 100/100" with a **warning triangle** icon (implying danger). Research → Advanced Risk Analysis shows the same "Concentration Risk: 100/100" with a **"Low Risk" green badge** (implying safety). Same pattern for Volatility Risk and Sector Risk.
**Expected**: Risk scores should have consistent interpretation across all views.
**Key files**: Dashboard alert rendering, `core/risk_score_flags.py`, Research risk score component
**Fix effort**: Medium — need to align the score scale (is 100 = high risk or 100 = low risk?) and update all rendering sites.

### 3. [Major] Total Portfolio Value mismatch — $109,808 vs $27,187

**Page**: Dashboard vs Holdings
**What happens**: Dashboard "Total Portfolio Value" card shows **$109,808**. Holdings page header shows "Total Holdings: **$27,187**" and the bottom confirms "Total Value: $27,187" with "15 of 15 holdings." The individual position values in Holdings sum to ~$27K.
**Expected**: Both views should show the same total, or the difference should be explained (e.g., multi-account, gross vs net).
**Key files**: Dashboard portfolio overview data source, Holdings data source
**Fix effort**: Large — likely a data source mismatch (Dashboard may include multiple accounts/segments while Holdings shows only one).

### 4. [Major] Alpha inconsistency across views

**Page**: Dashboard vs Performance
**What happens**: Dashboard shows Alpha = **-2.2%** ("risk-adjusted vs SPY, annualized"). Performance Analytics shows Alpha = **-9.3%** ("vs SPY, Weak"). Performance Insights text says "underperforming benchmark by **2.17%**."
**Expected**: Alpha should be consistent, or the different calculation methods should be labeled.
**Key files**: Dashboard metric computation, `services/performance_helpers.py`, Performance view
**Fix effort**: Medium

### 5. [Major] Volatility shows 3 different values

**Page**: Holdings (47.7%), Performance Risk Analysis (8.3%), Settings (0.1%)
**What happens**: Three completely different volatility figures across the app. Holdings shows "AVG VOLATILITY: 47.7%" (average of individual stock vols). Performance shows "8.3% Annualized standard deviation" (portfolio-level). Settings shows "Portfolio Volatility: 0.1%" (unclear source).
**Expected**: Each should be clearly labeled as different metrics, or use consistent methodology.
**Fix effort**: Medium — primarily a labeling/naming issue.

### 6. [Major] Phantom positions in analytics

**Page**: Performance Attribution, Research Risk Analysis, Settings
**What happens**: Tickers like DSU (27.6%), STWD (11.8%), MSCI (11.2%), ENB, CBL, IT, PCTY appear in performance attribution and risk analysis but are NOT in the 15 current holdings. These are likely historical/closed positions still affecting analytics.
**Expected**: Current-only views should use current positions. Historical views should label closed positions differently.
**Key files**: Performance data source, factor analysis data source
**Fix effort**: Large — requires separating current vs historical position data in the frontend.

### 7. [Major] "Well Diversified" contradicts concentration alerts

**Page**: Dashboard
**What happens**: The Concentration card shows "100" with "Well Diversified" badge. But the Alerts section shows "Concentration Risk: 100/100" with a warning triangle, and AI Recommendations flag "High Semiconductors Concentration" as HIGH priority.
**Expected**: If concentration is flagged as a risk, the summary card should not say "Well Diversified."
**Key files**: Dashboard Concentration card, `core/risk_score_flags.py`
**Fix effort**: Quick — fix the label/badge logic.

### 8. [Major] React setState-during-render warnings

**Page**: Dashboard
**What happens**: 6 "Cannot update a component while rendering a different component" errors fire on initial Dashboard load, affecting: `PortfolioOverviewContainer`, `DashboardHoldingsCard`, `DashboardAlertsPanel`, `DashboardPerformanceStrip`, `AssetAllocationContainer`, `DashboardIncomeCard`.
**Expected**: No React warnings. State updates should happen in effects, not during render.
**Key files**: Each of the 6 container components listed above
**Fix effort**: Medium — each component needs the setState call moved into a `useEffect`.

### 9-14. [Minor] Holdings data quality and UX

- **GOLD** labeled "Financial Services" → should be Materials/Mining (#9)
- **SLV** shows fund manager name instead of ETF name → misleading (#10)
- **FIG** risk score missing (shows "—") (#11)
- **"Accounts: 0"** in footer despite 15 real holdings (#12)
- **No sidebar tooltips** on icon-only nav (#13)
- **Name truncation** without hover tooltips (#14)

### 15-23. [Minor] Various UX issues

- Trading P&L empty state has no icon/CTA (#15)
- "Predictive" badge on historical Maximum Drawdown metric (#16)
- Recovery Time / Tracking Error show "--" without explanation (#17)
- Risk Score "89.00" — unnecessary decimals (#18)
- "Legacy tab stack" in Scenarios subtitle (#19)
- Tax Harvest alone on third grid row (#20)
- Optimizer shows 0% optimal weights before running (#21)
- Missing visual style toggle / benchmark selector in Settings (#22)
- "Unknown" sector in attribution (#23)

### 24-27. [Suggestion] Polish opportunities

- Income Projection section is sparse (#24)
- Alerts "View all 7" could show remaining count (#25)
- Factor t-stats all 0.00 — may not be computed (#26)
- Historical positions in Contributors/Detractors not labeled as closed (#27)

---

## Overall Assessment

**Design quality**: The app looks professional with a clean, modern aesthetic. Card-based layouts, green accent colors, and consistent typography give it a polished feel. The premium visual style is working well.

**Critical issues**: The biggest concern is **data inconsistency across views**. The same metric (portfolio value, alpha, volatility, risk scores) shows different numbers on different pages. This undermines user trust in the entire platform. The root cause appears to be that some views use a broader dataset (multiple accounts/historical positions) while others use only current holdings.

**Blocker**: The `useSharedChat` error spams the console 36+ times and crashes the `ArtifactAwareAskAIButton` component. While the chat panel itself works via the sidebar nav button, the floating FAB version is broken.

**Recommended priority**:
1. Fix the data source alignment (findings 3, 4, 5, 6) — this is the #1 trust issue
2. Fix risk score interpretation (findings 2, 7) — contradictory risk labels
3. Fix ChatProvider crash (finding 1) — blocker-level console spam
4. Fix React warnings (finding 8) — performance and correctness
5. Address minor UX issues in subsequent passes

# Frontend Issues — 2026-03-13 E2E Audit

**Source**: `FRONTEND_E2E_FINDINGS_2026_03_13.md`
**Total**: 27 issues (1 Blocker, 7 Major, 15 Minor, 4 Suggestion)

---

## Tier 0 — Blocker (fix immediately)

### F1. `useSharedChat` crash — AskAIButton outside ChatProvider
- **Page**: All (Dashboard observed)
- **Symptom**: 36+ console errors: `Error: useSharedChat must be used within a ChatProvider`. `ArtifactAwareAskAIButton` crashes → `ChunkErrorBoundary` fallback.
- **Root cause**: Component calls `useSharedChat()` but is rendered outside `ChatProvider`.
- **Key files**: `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx:114`, `ChatContext.tsx:23`
- **Fix**: Wrap in `ChatProvider` or add a context-availability guard.
- **Effort**: Medium

---

## Tier 1 — Major data inconsistencies (trust-breaking)

### F2. Risk score interpretation inverted
- **Page**: Dashboard Alerts vs Research → Risk Analysis
- **Symptom**: Same score (Concentration Risk 100/100) shown with **warning triangle** on Dashboard but **"Low Risk" green badge** on Research. Same for Volatility and Sector Risk.
- **Root cause**: Two rendering paths interpret the 0-100 scale in opposite directions.
- **Key files**: Dashboard alert component, Research risk score component, `core/risk_score_flags.py`
- **Effort**: Medium

### F3. Portfolio value mismatch — $109,808 vs $27,187
- **Page**: Dashboard vs Holdings
- **Symptom**: Dashboard shows $109,808. Holdings shows $27,187 (confirmed by individual position sum and footer). 4x discrepancy.
- **Root cause**: Dashboard likely includes multiple accounts/segments; Holdings shows only the IBKR equity portfolio.
- **Key files**: Dashboard overview data source, Holdings data source, portfolio config
- **Effort**: Large — investigate which data source each view calls

### F4. Alpha inconsistency — -2.2% vs -9.3%
- **Page**: Dashboard vs Performance
- **Symptom**: Dashboard: -2.2%. Performance Analytics: -9.3%. Performance Insights text: "underperforming by 2.17%."
- **Root cause**: Different calculation methods or time periods. Dashboard may use annualized risk-adjusted alpha; Performance may use raw excess return.
- **Key files**: Dashboard metric computation, `mcp_tools/performance.py`, Performance view adapter
- **Effort**: Medium

### F5. Volatility shows 3 different values
- **Page**: Holdings (47.7%), Performance (8.3%), Settings (0.1%)
- **Symptom**: Same label "volatility" shows wildly different numbers.
- **Root cause**: Holdings = avg individual stock vol. Performance = portfolio-level annualized std dev. Settings = unclear (possibly daily vol not annualized?).
- **Fix**: At minimum, label each distinctly. Ideally, standardize on portfolio-level vol everywhere.
- **Effort**: Medium

### F6. Phantom positions in analytics
- **Page**: Performance Attribution, Research Risk Analysis, Settings
- **Symptom**: DSU (27.6%), STWD (11.8%), MSCI (11.2%), ENB, CBL, IT, PCTY appear in analytics but are absent from the 15 current holdings.
- **Root cause**: Analytics views use the full historical/multi-account portfolio. Holdings shows only current equity positions.
- **Fix**: Either filter analytics to current holdings, or label historical/cross-account positions.
- **Effort**: Large

### F7. "Well Diversified" contradicts concentration alerts
- **Page**: Dashboard
- **Symptom**: Concentration card: "100 / Well Diversified". Alerts: "Concentration Risk: 100/100" ⚠. AI Recommendations: "High Semiconductors Concentration" HIGH.
- **Root cause**: The diversification score label logic is wrong — 100 concentration risk should NOT map to "Well Diversified."
- **Key files**: Dashboard Concentration card rendering, `core/risk_score_flags.py`
- **Effort**: Quick

### F8. React setState-during-render warnings (×6)
- **Page**: Dashboard
- **Symptom**: 6 components fire "Cannot update a component while rendering a different component" on initial load.
- **Affected**: `PortfolioOverviewContainer`, `DashboardHoldingsCard`, `DashboardAlertsPanel`, `DashboardPerformanceStrip`, `AssetAllocationContainer`, `DashboardIncomeCard`
- **Root cause**: setState called during render instead of in `useEffect`.
- **Effort**: Medium

---

## Tier 2 — Minor bugs and UX issues

### F9. GOLD sector misclassification
- **Page**: Holdings
- **Symptom**: GOLD shows "Gold.com, Inc." / Financial Services. Should be Barrick Gold / Materials.
- **Effort**: Quick — FMP data or sector mapping fix

### F10. SLV name shows fund manager, not ETF name
- **Page**: Holdings
- **Symptom**: "BlackRock Institutional Trus..." instead of "iShares Silver Trust".
- **Effort**: Quick — display name resolution

### F11. FIG missing risk score
- **Page**: Holdings
- **Symptom**: Shows "—" while all other 14 positions have scores.
- **Effort**: Quick — investigate why `analyze_stock` fails for FIG

### F12. "Accounts: 0" in Holdings footer
- **Page**: Holdings
- **Symptom**: Badge says "Holdings: Real | Count: 15 | Accounts: 0" — count should reflect connected accounts.
- **Effort**: Quick

### F13. Sidebar nav has no tooltips
- **Page**: All
- **Symptom**: Icon-only navigation with no labels or hover tooltips. Users must guess what each icon means.
- **Fix**: Add `title` attributes or tooltip components to each nav button.
- **Effort**: Quick

### F14. Truncated company names lack tooltips
- **Page**: Holdings
- **Symptom**: "Figma Inc. Class ...", "Ashtead Technolog...", etc. with no way to see full name.
- **Fix**: Add `title` attribute or tooltip on hover.
- **Effort**: Quick

### F15. Trading P&L poor empty state
- **Page**: Performance
- **Symptom**: Just text "Trading analysis data is unavailable." — no icon, no help link, no CTA.
- **Effort**: Quick

### F16. "Predictive" badge on historical metric
- **Page**: Performance → Risk Analysis
- **Symptom**: Maximum Drawdown (a historical metric) is labeled "Predictive."
- **Effort**: Quick — change label

### F17. Missing data shows "--" without explanation
- **Page**: Performance → Risk Analysis
- **Symptom**: Recovery Time and Tracking Error show "--" with no tooltip or help text.
- **Effort**: Quick

### F18. Risk Score unnecessary decimals
- **Page**: Dashboard
- **Symptom**: Shows "89.00" — should be "89" for a round number.
- **Effort**: Quick — format as integer

### F19. Developer-facing language in Scenarios
- **Page**: Scenarios
- **Symptom**: Subtitle says "...instead of working inside the legacy tab stack."
- **Fix**: Reword to user-friendly copy.
- **Effort**: Quick

### F20. Unbalanced Scenarios grid
- **Page**: Scenarios
- **Symptom**: 3+3+1 grid — Tax Harvest alone on last row.
- **Fix**: Consider 4+3 or 2+2+2+1 layout, or add an 8th card.
- **Effort**: Quick

### F21. Optimizer misleading pre-run state
- **Page**: Strategy → Optimize
- **Symptom**: All "Optimal" weights show 0.0% before running, suggesting sell everything.
- **Fix**: Show "—" or "Run to calculate" instead of 0.0%.
- **Effort**: Quick

### F22. Missing Settings features
- **Page**: Settings
- **Symptom**: No visual style toggle (classic/premium) or benchmark selector visible. Spec expects both.
- **Effort**: Quick — may just need to surface existing components

### F23. "Unknown" sector in attribution
- **Page**: Performance → Attribution
- **Symptom**: "Unknown" at -0.6% — uncategorized holdings.
- **Effort**: Quick — classify or label as "Other"

---

## Tier 3 — Suggestions

### F24. Sparse Income Projection
- **Dashboard**: Just 3 numbers ($122, $10, 0.5%) with lots of whitespace. Could show breakdown by holding or monthly trend.

### F25. Alerts count UX
- **Dashboard**: "View all 7" — shows 5 of 7, could say "View 2 more."

### F26. Factor t-stats all 0.00
- **Research**: Every factor shows t-stat: 0.00 — likely not being computed or passed from backend.

### F27. Historical positions unlabeled
- **Performance**: Top Contributors/Detractors include closed positions (ENB, CBL, IT, PCTY) without marking them as historical.

---

## Recommended Fix Order

1. **F1** (Blocker) — ChatProvider wrap. Stops 36+ errors per page load.
2. **F7** (Quick) — Fix "Well Diversified" label. Most visible contradiction.
3. **F2** (Medium) — Align risk score interpretation across Dashboard/Research.
4. **F3 + F6** (Large) — Investigate data source divergence. Root cause of value mismatch + phantom positions.
5. **F8** (Medium) — Fix 6 setState-during-render warnings.
6. **F4 + F5** (Medium) — Align alpha/volatility labels and calculations.
7. **F13** (Quick) — Add sidebar tooltips. High-impact usability fix.
8. **Tier 2 Quick fixes** (F9-F12, F14-F23) — batch in a single pass.
9. **Tier 3 suggestions** — backlog for polish phase.

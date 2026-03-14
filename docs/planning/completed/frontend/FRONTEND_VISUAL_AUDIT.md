# Frontend Visual Audit

**Date:** 2026-03-05
**Status:** COMPLETE — Visual + code-level audit of all 7 views
**Method:** Chrome screenshot walkthrough + code-level analysis of StrategyBuilder, StockLookup, ScenarioAnalysis

---

## Priority 1: Broken / Clipped UI (Things that don't work) ✅ DONE (`7a7d326c`) — Chrome-verified

Plan: `completed/FRONTEND_VISUAL_AUDIT_P1_PLAN.md`. 7 items implemented, Codex-reviewed (2 rounds), Chrome-verified all 7.

### V1. Stock Research: Search dropdown clipped by parent overflow ✅
**View:** Stock Research (StockLookup.tsx)
**Problem:** When typing a stock ticker, the search results dropdown renders inside a `CardContent` with `overflow-hidden` (line 516). The dropdown (`absolute z-20`, line 475) gets clipped by the card boundary, cutting off results that extend below the card edge.
**Fix:** Either remove `overflow-hidden` from the CardContent, or move the dropdown to render via a Portal (outside the card DOM tree). The simplest fix is removing `overflow-hidden` from line 516's CardContent since the dropdown already has `z-20`.

### V2. Overview: Performance card cramped/unreadable in sidebar layout ✅
**View:** Overview (PortfolioOverview.tsx) — all modes
**Problem:** The Performance Analytics card is squeezed into a ~50% width right column alongside Asset Allocation. The 4 metric boxes (Benchmark Return, Period Return, Alpha, Sharpe Ratio) are crammed together with overlapping text. Labels like "Benchmark Return" and "-1.05%" collide. The sub-labels ("vs +18.47%", "Weak", "Excellent") are barely readable.
**Root cause:** The metrics are designed for full-width display (they look fine on the dedicated Performance page) but the Overview sidebar column is too narrow.
**Fix:** Either: (a) simplify the Overview performance card to show fewer, larger metrics (just Period Return + Alpha), or (b) switch to a vertical stack layout for the metrics in the narrow column, or (c) make the Performance section full-width instead of side-by-side with Asset Allocation.

### V3. Stock Research: Broken dynamic Tailwind classes on risk score card ✅
**View:** Stock Research (StockLookup.tsx, line 708)
**Problem:** The risk score card dynamically constructs Tailwind classes using chained `.replace()` calls on a base class string. This produces invalid/incomplete class names like `border-` (no color suffix) and `bg-emerald-700` paired with no text color. Tailwind's JIT compiler cannot match these dynamically generated classes, resulting in unstyled or broken risk score display.
**Fix:** Replace the dynamic `.replace()` chain with a lookup map: `{ low: 'border-green-200 bg-green-50 text-green-700', medium: 'border-yellow-200 bg-yellow-50 text-yellow-700', high: 'border-red-200 bg-red-50 text-red-700' }`.

### V4. Strategy Builder: ScrollArea height chain broken ✅
**View:** Strategy Builder (StrategyBuilder.tsx)
**Problem:** The outer card is `h-[700px]` (line 415), but inner flex containers lack `min-h-0`, preventing `ScrollArea` from calculating correct scrollable height. Content overflows or gets clipped instead of scrolling. The `overflow-hidden` at line 479 compounds the issue by hiding overflow without enabling scroll.
**Fix:** Add `min-h-0` to all flex containers in the height chain between the `h-[700px]` card and the `ScrollArea`. Remove `overflow-hidden` from containers that should scroll.

### V5. Strategy Builder: NaN values in Marketplace tab ✅
**View:** Strategy Builder, Marketplace tab (lines 700-714)
**Problem:** `formatPercent()` and `formatNumber()` render literal "NaN" text when strategy metrics are undefined/null. Visible as "NaN%" or "NaN" in metric cards.
**Fix:** Guard with null checks: `value != null && !isNaN(value) ? formatPercent(value) : '—'`.

### V6. Scenario Analysis: Fixed height causes content clipping ✅
**View:** Scenario Analysis (ScenarioAnalysis.tsx, line 1265)
**Problem:** The main card is `h-[700px]` fixed. Content in several tabs (especially Historical and Portfolio Builder) exceeds this, causing clipping. The Historical tab has a `ScrollArea h-[680px]` (line 1721) that itself exceeds the available space after tab headers consume ~80px.
**Fix:** Switch to `min-h-[700px]` or `max-h-[calc(100vh-200px)]` with proper ScrollArea sizing that accounts for tab header height.

### V7. Scenario Analysis: Nested/missing ScrollArea confusion ✅
**View:** Scenario Analysis, Portfolio Builder + Historical tabs
**Problem:** Portfolio Builder tab has nested `ScrollArea` components (lines 1367, 1439) creating scroll-within-scroll UX. Historical tab (lines 1696-1802) is missing a top-level `ScrollArea` entirely, so long history lists just clip. Inconsistent scroll behavior across tabs.
**Fix:** Use a single `ScrollArea` per tab at the top level. Remove nested `ScrollArea` from Portfolio Builder sub-sections.

---

## Priority 2: Layout & Spacing Issues ✅ DONE (`c419a812`)

Plan: `FRONTEND_VISUAL_AUDIT_P2_PLAN.md`. 8 items implemented, Codex-reviewed.

### V8. Overview: Metric cards — cramped labels and unclear hierarchy ✅
**View:** Overview, scrolled to metric cards row (Total Portfolio Value, Daily P&L, Risk Score, Sharpe Ratio, Alpha Generation, Concentration)
**Problem:** Six metric cards in a row. Labels like "TOTAL PORTFOLIO VALUE" and "ALPHA GENERATION" wrap to 2-3 lines in ALL CAPS, making them hard to scan. The secondary text ("today's performance", "portfolio volatility", "excess return vs benchmark") is small and grey. The "Updated" timestamp at the bottom of each card adds visual noise without value. The "0" next to badges like "Excellent 0" is confusing (what does it mean?).
**Fix:** Reduce to 4 cards max per row (or make responsive), use sentence-case labels, remove "Updated" footer, clarify the "0" display.

### V9. Overview: Market Intelligence dominates above the fold ✅
**View:** Overview (both Compact and Detailed modes)
**Problem:** Market Intelligence is the first thing shown, taking up the entire viewport above the fold. The key portfolio metrics (value, P&L, risk) require scrolling to reach. For a portfolio dashboard, the user's own portfolio metrics should be front and center.
**Fix:** Move Market Intelligence below the metric cards, or collapse it into a compact row/banner. Portfolio value + P&L + risk score should be the hero section.

### V10. Factor Analysis: Left panel has excessive empty space ✅ (resolved by prior tabbed refactor)
**View:** Factor Analysis (RiskAnalysis.tsx)
**Problem:** The left column shows only 3 factor cards (Industry, Market Beta, Subindustry) but takes up ~60% of width. Below the 3rd card is a large empty area. The right "Risk Assessment" column (VaR, Beta, Volatility, Max Drawdown) is squeezed into ~40%.
**Fix:** Better column proportioning, or switch to a different layout (e.g., factors in a table, risk metrics as a row).

### V11. Scenario Analysis: Portfolio Impact Analysis shows all N/A ✅
**View:** Scenario Analysis, Portfolio Builder tab
**Problem:** The "Portfolio Impact Analysis" sidebar shows 4 yellow cards all displaying "N/A" (Volatility, Concentration HHI, Factor Variance, Risk Violations). This is the default state before running any analysis, but it looks broken — like data failed to load.
**Fix:** Show a "Run an analysis to see impact metrics" placeholder instead of N/A cards. Or hide the panel until an analysis has been run.

### V12. Stock Research: Fixed heights prevent responsive layout ✅
**View:** Stock Research (StockLookup.tsx)
**Problem:** The main card is `h-[800px]` (line 438) and the tab content area is `h-[480px]` (line 609). On smaller screens or with more content, these fixed heights clip. The 6-column tab bar (Fundamentals, Peers, Portfolio Fit, Risk Factors, Financials, Price Chart — line 611) gets cramped on narrower viewports.
**Fix:** Use `min-h` instead of `h` for the card. Add responsive breakpoints for the tab bar (stack or scroll on narrow screens).

### V13. Stock Research: Search dropdown min-width overflows card ✅
**View:** Stock Research (StockLookup.tsx, line 475)
**Problem:** The search dropdown has `min-w-[22rem]` which can exceed the card's content width on narrow viewports, causing horizontal overflow.
**Fix:** Use `max-w-full` or `min-w-0 w-full` to constrain the dropdown within the card boundary.

### V14. Strategy Builder: No responsive breakpoints on grids ✅
**View:** Strategy Builder
**Problem:** The Marketplace tab uses a 3-column grid (line 495) with no medium-screen breakpoint — jumps from `sm:grid-cols-2` straight to `lg:grid-cols-3`. The Active Strategies metrics use a 4-column grid (line 812) with no responsive fallback. On tablet-width viewports, content gets cramped.
**Fix:** Add `md:grid-cols-2` intermediate breakpoints. For metrics, use `grid-cols-2 lg:grid-cols-4`.

### V15. Strategy Builder: Empty Active Strategies tab ✅
**View:** Strategy Builder, Active tab (lines 793-841)
**Problem:** When no strategies are active, the tab shows a completely empty area with no guidance. No empty state illustration, no "Create your first strategy" CTA.
**Fix:** Add an empty state component with a brief message and a button to navigate to the Builder tab.

### V16. Scenario Analysis: 5-tab bar cramped on narrow viewports ✅
**View:** Scenario Analysis (lines 1355-1361)
**Problem:** Five tabs (Stress Tests, Monte Carlo, Historical, Portfolio Builder, Optimization) in a horizontal row. On narrower viewports, tab labels truncate or wrap.
**Fix:** Use scrollable tabs or truncation with tooltip on narrow viewports.

---

## Priority 3: Visual Polish & Readability — 11/12 DONE — Chrome-verified

### V17. Overview: Risk score bars are all red regardless of score ✅
**View:** Overview, Advanced Risk Analysis section
**Problem:** Concentration Risk (100/100 "Low Risk"), Volatility Risk (100/100 "Low Risk"), and Factor Risk (79/100 "Medium Risk") all show red progress bars. A score of 100/100 marked "Low Risk" with a red bar sends contradictory signals. The color should reflect the risk level, not always be red.
**Fix:** Color-code the bars: green for Low Risk, yellow/orange for Medium, red for High. The 100/100 "Low Risk" items should have green bars.

### V18. Overview: Data source badges visible in production — SKIP (keeping for dev use)
**View:** Overview (multiple sections)
**Problem:** Debug/diagnostic badges are visible: "Asset Allocation: Real Data | Source: useRiskAnalysis 2026", "Risk Analysis: Real | Portfolio: Loaded", "Overview: Real | Portfolio: Loaded", "Scenarios: No Data | Backend: PRODUCTION | Templates: 5 | StrategyIntegration: ✅". These are development aids, not user-facing information.
**Status:** Kept intentionally — useful during active development.

### V19. Holdings: Alert badge tooltip overlaps column headers ✅
**View:** Holdings (HoldingsView.tsx)
**Problem:** The alert badge (e.g., "1 alert") on position rows — when the tooltip plan was recently added (commit `d644687f`) — the tooltip positioning may overlap with adjacent column headers on narrow viewports.
**Fix:** Changed tooltip `side="right"` to `side="bottom"` with `collisionPadding={8}` for auto-flip. Already portal-based (Radix).

### V20. Performance: Top Contributors/Detractors tables too long ✅
**View:** Performance, lower tabs
**Problem:** The Sector Attribution and Factor Attribution tables look good, but the Top Contributors / Top Detractors tables show ALL positions (15+ rows each) without pagination or a "show more" pattern. On smaller screens this creates very long scroll.
**Fix:** Default to top 5, with "Show all" expander.

### V21. Overview: AI Recommendations cards have inconsistent height ✅
**View:** Overview, AI Recommendations section
**Problem:** The 3 HIGH/MEDIUM recommendation cards ("High DSU Concentration", "High Financial - Mortgages Concentration", "High Asset Management Concentration") are in a 3-column grid, but the middle card's "Expected Impact" text wraps differently, creating uneven card heights. The "ACTION ITEMS" sections also have varying heights.
**Fix:** Use `min-h` or equal-height cards in the grid. Or collapse action items into an expandable section.

### V22. Stock Research: Portfolio Fit metrics lack column headers ✅
**View:** Stock Research, Portfolio Fit tab (lines 1170-1181)
**Problem:** The metrics grid shows values in columns but has no column headers explaining what each column represents (e.g., "Current", "With Position", "Impact"). User must guess what the numbers mean.
**Fix:** Add a header row above the metrics grid.

### V23. Stock Research: No price chart despite `chartData` prop ✅
**View:** Stock Research (StockLookup.tsx, lines 198-202)
**Problem:** The component accepts a `chartData` prop but never renders a chart. The "Price Chart" tab exists in the tab bar but the content area is empty or shows placeholder text.
**Fix:** Recharts 90-day AreaChart (price + volume). Commit `20be3311`. Chrome-verified.

### V24. Strategy Builder: Duplicate "Run Backtest" buttons ✅
**View:** Strategy Builder
**Problem:** There's a "Run Backtest" button in the card header AND another in the Builder tab content. Two identical CTAs create confusion about which to click.
**Fix:** Keep only one — the header button (always visible) or the in-content button (contextual), not both.

### V25. Strategy Builder: Performance tab has no charts ✅
**View:** Strategy Builder, Performance tab
**Problem:** The Performance tab shows only numeric metrics with no equity curve chart, drawdown chart, or benchmark comparison visualization. For a backtesting feature, visual performance charts are expected.
**Fix:** Recharts equity curve LineChart (portfolio vs benchmark). Commit `20be3311`. Chrome-verified.

### V26. Scenario Analysis: Monte Carlo has no visualization ✅
**View:** Scenario Analysis, Monte Carlo tab
**Problem:** Monte Carlo simulation results are shown as numeric statistics only. No fan chart, probability distribution, or percentile bands. The core value of Monte Carlo is visual — seeing the spread of outcomes.
**Fix:** Recharts fan chart with 5 percentile bands (P5/P25/P50/P75/P95). Commit `20be3311`. Chrome-verified.

### V27. Scenario Analysis: Inconsistent empty states across tabs ✅
**View:** Scenario Analysis, various tabs
**Problem:** Different tabs handle "no data" differently — some show "N/A" cards, some show blank space, some show loading spinners that never resolve. No consistent empty state pattern.
**Fix:** Standardize empty state: icon + message + action button (e.g., "Run a stress test to see results").

### V28. Scenario Analysis: Optimization metrics grid overflow ✅
**View:** Scenario Analysis, Optimization tab (line 1617)
**Problem:** The optimization results metrics grid can overflow its container width when all metrics are populated, causing horizontal scroll or clipping.
**Fix:** Use responsive grid with `grid-cols-2 lg:grid-cols-4` and allow text wrapping in metric labels.

---

## Priority 4: Functional Gaps (not visual bugs, but UX gaps noticed during audit) — DONE (`281f6c31`) — Chrome-verified

### V29. Strategy Builder: Chrome extension redirect — N/A
**View:** Strategy Builder
**Problem:** Navigating to Strategy Builder via the Analytics dropdown caused the tab to redirect to a chrome-extension:// URL during testing.
**Status:** Not applicable — caused by Claude-in-Chrome extension intercepting keyboard shortcuts, not a product bug.

### V30. Overview: No chart/visualization for performance ✅
**View:** Overview, Performance Analytics card
**Problem:** The Performance section on Overview shows only numbers — no sparkline, trend line, or mini chart. A small chart showing portfolio vs benchmark over the selected period would make the card much more informative at a glance.
**Fix:** Wired `usePerformance()` into PortfolioOverviewContainer, extracted `portfolioCumReturn` time series, rendered `SparklineChart` after metrics grid. Green when positive, red when negative.
**Status:** DONE (`7cc9e275`) — Chrome-verified.

### V31. Strategy Builder: `hover:shadow-xl` on 700px card ✅
**View:** Strategy Builder (line 415)
**Problem:** The main 700px-tall card has `hover:shadow-xl` which creates a jarring visual effect on a large fixed-size card. Shadow transitions are designed for small interactive cards, not page-level containers.
**Fix:** Removed `hover:shadow-xl` from the main card wrapper.

### V32. Scenario Analysis: Deprecated `onKeyPress` usage ✅
**View:** Scenario Analysis
**Problem:** Uses `onKeyPress` event handler which is deprecated in React. Should use `onKeyDown` instead.
**Fix:** Replaced `onKeyPress` with `onKeyDown` on the ticker input in Portfolio Builder tab.

---

## Summary

| Priority | Count | Theme |
|----------|-------|-------|
| P1: Broken/Clipped | 7 ✅ | Dropdown clipped, cards too cramped, broken classes, scroll chains, NaN rendering — ALL DONE (`7a7d326c`), Chrome-verified |
| P2: Layout/Spacing | 9 ✅ | Wrong hierarchy, fixed heights, empty states, missing breakpoints — ALL DONE (`c419a812`) |
| P3: Visual Polish | 11/12 ✅ | All done. V18 SKIP (dev badges). CSS fixes (`765435b1`), V19 tooltip (`9b895ac3`), V23/V25/V26 charts (`20be3311`) — all Chrome-verified. |
| P4: Functional Gaps | 3/4 ✅ | V31 shadow fix, V32 onKeyPress→onKeyDown — Chrome-verified (`281f6c31`). V29 N/A (extension artifact). V30 sparkline (`7cc9e275`) Chrome-verified. |
| **Total** | **32** | |

## Views Audited

| View | Method | Status | Key Issues |
|------|--------|--------|------------|
| Overview (Compact) | Chrome screenshots | Complete | V2, V8, V9, V17, V18, V21, V30 |
| Overview (Detailed) | Chrome screenshots | Complete | Same as Compact |
| Holdings | Chrome screenshots | Complete | Clean — V19 minor |
| Performance | Chrome screenshots | Complete | Good in full-width, V20 density |
| Factor Analysis | Chrome screenshots | Complete | V10 empty space |
| Scenario Analysis | Chrome + code audit | Complete | V6, V7, V11, V16, V26, V27, V28, V32 |
| Strategy Builder | Code audit | Complete | V4, V5, V14, V15, V24, V25, V29, V31 |
| Stock Research | Code audit | Complete | V1, V3, V12, V13, V22, V23 |

# Frontend Comprehensive E2E Test Plan

**Status**: DRAFT
**Created**: 2026-03-14
**Goal**: Systematic, repeatable end-to-end testing of the entire frontend — functionality, data correctness, visual/design quality, interactivity, error handling, and cross-cutting concerns.

---

## Context

The app has undergone major restructuring since the last full audit (2026-03-13, 27 findings). Two fix batches landed (F1/F2/F7/F18 in `2d1e1551`, F15/F16/F20/F21/F23 in `66810bd8`). Several issues remain open (F3-F6, F8, ~10 minor). This plan covers a **fresh, comprehensive pass** — not just regression on known issues but a full functional + visual audit.

### Previous Audits
- `FRONTEND_E2E_FINDINGS_2026_03_13.md` — 27 issues (1 Blocker, 7 Major, 15 Minor, 4 Suggestion)
- `FRONTEND_ISSUES_2026_03_10.md` — 38 issues (pre-restructure, all resolved)
- `ONBOARDING_E2E_TEST_PLAN.md` — 8 phases, all pass

### Frontend Architecture
- **4 packages**: `chassis` (services), `connectors` (hooks/data), `ui` (components), `app-platform` (infra)
- **9 main views**: Overview, Holdings, Research, Performance, Scenarios, Strategies, Trading, Chat, Settings
- **66+ data hooks**, 50+ UI primitives, 3-tier caching, SSE streaming for Claude chat
- **67 existing unit tests** (hooks + components) — no E2E framework configured

---

## Test Execution Method

Each section is designed to be executed via Chrome browser automation (Claude-in-Chrome) against `localhost:3000` with the backend on `localhost:5001`. Tests are manual/semi-automated — no Playwright/Cypress framework (yet).

### Per-View Checklist
1. **Navigate** to the view
2. **Screenshot** the default state
3. **Verify data** — real numbers, no NaN/undefined/$0/placeholder
4. **Click every interactive element** — buttons, tabs, toggles, dropdowns, cards
5. **Check loading states** — skeletons, spinners, no flash of empty
6. **Check error handling** — what happens if backend is slow/down
7. **Check console** — React warnings, failed requests, JS errors
8. **Check dark mode** — toggle and verify
9. **Check responsive** — narrow viewport (375px)
10. **Rate visual quality** — polished or rough? Professional or toy?

---

## Phase 1: Prerequisites & Environment

| Step | Check | Pass Criteria |
|------|-------|---------------|
| 1.1 | Backend running on localhost:5001 | `curl localhost:5001/health` returns 200 |
| 1.2 | Frontend dev server on localhost:3000 | Page loads without build errors |
| 1.3 | User authenticated with real portfolio | Dashboard renders with real position data |
| 1.4 | Chrome DevTools Console open | Ready to monitor errors |
| 1.5 | Network tab open | Ready to monitor API calls |

---

## Phase 2: Authentication & Session

| # | Test | Steps | Expected | Severity |
|---|------|-------|----------|----------|
| 2.1 | Fresh login | Navigate to `/`, click Sign In, complete Google OAuth | Redirect to Dashboard with portfolio data | Blocker |
| 2.2 | Session persistence | Refresh page after login | Still authenticated, no re-login required | Blocker |
| 2.3 | Portfolio selector | Click portfolio dropdown in header | Shows list of portfolios, switching loads different data | Major |
| 2.4 | Logout | Click logout | Redirects to landing, clears state | Major |
| 2.5 | Cross-tab sync | Login in Tab A, check Tab B | Tab B reflects auth state | Minor |
| 2.6 | Expired session | Wait for token expiry or manually clear | Graceful redirect to login, no crash | Major |

---

## Phase 3: Dashboard / Overview (⌘1)

### 3A. Data Correctness

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 3A.1 | Total Portfolio Value | Compare Dashboard value vs Holdings total | Values match (or difference explained) |
| 3A.2 | Risk Score | Check score renders as integer (no unnecessary decimals) | Integer display, correct color coding |
| 3A.3 | Performance strip | Check 1D/1W/1M/3M/YTD/1Y returns | All render with real %, no NaN |
| 3A.4 | Holdings summary card | Verify top holdings match Holdings view | Consistent names, weights, values |
| 3A.5 | Income projection | Verify annual/monthly income figures | Real numbers, reasonable for portfolio size |
| 3A.6 | Alerts panel | Check alert content | Real alerts, not placeholder text |
| 3A.7 | Concentration score | "Well Diversified" vs warning alerts | Consistent interpretation (not contradictory) |
| 3A.8 | Alpha metric | Compare alpha here vs Performance view | Same value, or clearly different calculation labeled |
| 3A.9 | Market intelligence | Events loading with portfolio relevance scores | Real events, relevance % visible |

### 3B. Interactivity

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 3B.1 | Card click-through | Click each summary card | Navigates to corresponding detail view |
| 3B.2 | Refresh button | Click refresh / ⌘R | Spinner, toast, data updates |
| 3B.3 | Alerts "View all" | Click "View all" link | Shows remaining alerts or navigates |
| 3B.4 | AI Recommendations | Check AI panel renders | Recommendations load, priority labels visible |

### 3C. Visual / Design

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 3C.1 | Card layout | Verify grid alignment | Cards align properly, no orphans |
| 3C.2 | Dark mode | Toggle theme | All cards readable, no contrast issues |
| 3C.3 | Loading skeleton | Reload page, observe | Skeletons appear during data fetch |
| 3C.4 | No React warnings | Check console | Zero setState-during-render warnings |

---

## Phase 4: Holdings View (⌘2)

### 4A. Data Correctness

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 4A.1 | Position count | Verify "X of Y holdings" footer | Matches actual row count |
| 4A.2 | Account count | Check "Accounts: N" footer badge | > 0 if positions exist |
| 4A.3 | Position values | Spot-check 3-5 positions against known prices | Within 1% of expected (market hours variance ok) |
| 4A.4 | Weight percentages | Sum of all weights | ~100% (±1% for rounding) |
| 4A.5 | Sector/industry labels | Check GOLD, SLV, FIG specifically | Correct industry (not "Financial Services" for metals ETFs) |
| 4A.6 | Risk scores | All positions have scores | No missing "—" without explanation |
| 4A.7 | Option positions | If options held, check display | Strike, expiry, multiplier visible |
| 4A.8 | Cash positions | If cash held | Labeled correctly, no P&L computed |
| 4A.9 | Company name display | Check for truncation | Hover tooltip shows full name |

### 4B. Interactivity

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 4B.1 | Column sorting | Click each column header | Sorts ascending/descending correctly |
| 4B.2 | Row click → stock detail | Click a position row | Opens stock lookup or detail view |
| 4B.3 | CSV export | Click export button | Downloads CSV with correct data |
| 4B.4 | Search/filter | If search exists, type a ticker | Filters table correctly |

### 4C. Visual

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 4C.1 | Sector color badges | Visual consistency | Distinct colors per sector |
| 4C.2 | P&L coloring | Green for gains, red for losses | Correct color coding |
| 4C.3 | Table responsiveness | Narrow viewport | Horizontal scroll or stacked layout, no overflow |

---

## Phase 5: Research View (⌘6)

### 5A. Factor Analysis Tab

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 5A.1 | Factor betas | Check all factor exposures | Real values, not all 0.00 |
| 5A.2 | T-statistics | Check t-stat column | Non-zero values (or explain "Limited data") |
| 5A.3 | Variance decomposition | Pie/bar chart renders | Shows factor vs idiosyncratic split |
| 5A.4 | Factor chart | Chart renders without errors | Axes labeled, data plotted |

### 5B. Risk Analysis Tab

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 5B.1 | VaR metrics | 95% and 99% VaR displayed | Reasonable values for portfolio |
| 5B.2 | Risk tooltips | Hover over risk metrics | Tooltip explanations appear (21 placements) |
| 5B.3 | Hedging strategies | If displayed, check content | Real recommendations, not placeholder |
| 5B.4 | Risk score consistency | Score here vs Dashboard | Same interpretation / scale |

### 5C. Stock Lookup Tab

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 5C.1 | Search | Type a ticker (e.g., "AAPL") | Autocomplete appears, select loads data |
| 5C.2 | Overview tab | Check fundamentals | Market cap, P/E, sector — real data |
| 5C.3 | Fundamentals tab | Revenue, earnings data | Charts/tables render |
| 5C.4 | Peer Comparison tab | Compare against peers | Peer list loads, ratios displayed |
| 5C.5 | Portfolio Fit tab | Check portfolio impact | VaR impact, correlation data |
| 5C.6 | Price Chart tab | Chart renders | Price history plotted, hover tooltip |
| 5C.7 | Technicals tab | Technical indicators | RSI, MACD, etc. display |

---

## Phase 6: Performance View (⌘4)

### 6A. Data Correctness

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 6A.1 | Return periods | 1D, 1W, 1M, 3M, YTD, 1Y | All render, no NaN |
| 6A.2 | Performance chart | Main chart renders | Hover tooltip with dates and values |
| 6A.3 | Sharpe ratio | Check value | Reasonable (typically -2 to 3) |
| 6A.4 | Alpha consistency | Compare with Dashboard | Same or labeled differently |
| 6A.5 | Volatility label | Check what "Volatility" means | Labeled as "Portfolio" vs "Average Position" |
| 6A.6 | Benchmark | Correct benchmark displayed | SPY or user-selected |

### 6B. Analysis Tabs

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 6B.1 | Period Analysis tab | Click, check data | Returns by sub-period |
| 6B.2 | Risk Analysis tab | Click, check metrics | Drawdown, recovery, tracking error — values or "--" with explanation |
| 6B.3 | Attribution tab | Click, check sector/position breakdown | Top contributors/detractors labeled (historical positions marked as closed) |
| 6B.4 | Benchmarks tab | Click, compare | Benchmark returns alongside portfolio |
| 6B.5 | Trading P&L tab | Click, check data | Real P&L data or clear empty state with icon |

### 6C. Mode Toggle

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 6C.1 | Hypothetical vs Realized | Toggle if visible | Different data loads, labels change |
| 6C.2 | Income projection | Click income card if present | Dividend/interest breakdown |

---

## Phase 7: Scenarios View (⌘8)

### 7A. Landing Page

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 7A.1 | Card grid | 7 scenario cards render | Balanced grid (no lone card on last row) |
| 7A.2 | Card descriptions | Read all text | No developer-facing language ("legacy tab stack") |
| 7A.3 | Card click | Click each card | Navigates to corresponding tool |
| 7A.4 | Back navigation | From tool view, go back | Returns to landing |

### 7B. Stress Test

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 7B.1 | Scenario list | Scenarios load | Named scenarios with descriptions |
| 7B.2 | Run stress test | Select scenario, run | Results table with position-level impacts |
| 7B.3 | Results display | Check output | Portfolio impact %, position breakdown |

### 7C. What-If Analysis

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 7C.1 | Template presets | Select a preset | Weights pre-populate |
| 7C.2 | Custom weights | Enter custom allocation | Validates to 100%, runs analysis |
| 7C.3 | Results comparison | Check before/after | Side-by-side metrics |

### 7D. Monte Carlo

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 7D.1 | Run simulation | Click run | Fan chart renders with confidence bands |
| 7D.2 | Percentile table | Check 5th/25th/50th/75th/95th | Reasonable values |
| 7D.3 | Simulation params | Horizon, paths visible | Defaults or user-configurable |

### 7E. Optimization

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 7E.1 | Run optimization | Click run | Optimal weights computed |
| 7E.2 | Pre-run state | Before running | Shows "—" not misleading "0.0%" |
| 7E.3 | Efficient frontier | Chart renders | Scatter with current portfolio marked |
| 7E.4 | Recommendation table | Position-level changes | Direction (buy/sell), amounts |

### 7F. Backtest

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 7F.1 | Date range | Select start/end dates | Picker works, validates range |
| 7F.2 | Run backtest | Click run | Equity curve renders |
| 7F.3 | Attribution | Sector/position attribution | Charts/tables populate |
| 7F.4 | Metrics | Sharpe, drawdown, return | Reasonable values |

### 7G. Tax-Loss Harvest

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 7G.1 | Harvest candidates | View loads | FIFO lots with gain/loss |
| 7G.2 | Wash sale warnings | If applicable | Clear warning labels |
| 7G.3 | Total harvestable | Summary metric | Dollar amount displayed |

### 7H. Rebalance

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 7H.1 | Target allocation | Set target weights | Validates to 100% |
| 7H.2 | Generate trades | Click generate | Trade legs with amounts |
| 7H.3 | Review trades | Check each leg | Correct direction (buy/sell) and amounts |

---

## Phase 8: Strategies View (⌘5)

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 8.1 | Builder tab | Optimization interface | Same as Phase 7E optimization |
| 8.2 | Templates tab | Strategy templates | Preset strategies load |
| 8.3 | Active strategies | If any active | Display with current performance |
| 8.4 | Marketplace tab | If populated | Strategy cards with descriptions |

---

## Phase 9: Trading View

### 9A. Quick Trade

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 9A.1 | Ticker input | Type a ticker | Autocomplete, validates |
| 9A.2 | Trade preview | Enter qty, click preview | Commission estimate, total cost |
| 9A.3 | Trade execution | Click execute (if safe to test) | Order submitted, confirmation |
| 9A.4 | Error handling | Invalid ticker or qty | Clear error message |

### 9B. Orders

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 9B.1 | Order list | View pending/completed | Table renders with status |
| 9B.2 | Order details | Click an order | Details expand or modal |
| 9B.3 | Cancel order | If pending order exists | Cancel flow works |

### 9C. Baskets

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 9C.1 | Basket list | View existing baskets | Names, position counts |
| 9C.2 | Create basket | Click create, add tickers | Basket created |
| 9C.3 | Edit basket | Modify existing | Changes saved |
| 9C.4 | Execute basket | Preview → execute flow | Multi-leg order submitted |

### 9D. Hedge Monitor

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 9D.1 | Hedge positions | View current hedges | Option positions with greeks |
| 9D.2 | Expiry alerts | If near-expiry options | Warning badges visible |
| 9D.3 | Delta drift | If applicable | Current vs target delta shown |
| 9D.4 | Roll recommendations | If applicable | Suggested roll actions |

---

## Phase 10: Settings

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 10.1 | Account connections | View connected providers | Status indicators (connected/disconnected) |
| 10.2 | Add connection | Plaid/SnapTrade flow | Opens link flow, returns to settings |
| 10.3 | Visual style toggle | Classic ↔ Premium | UI updates immediately |
| 10.4 | Benchmark selector | If present, change benchmark | Performance recalculates |
| 10.5 | Risk settings | Modify risk limits | Saved, reflected in risk analysis |
| 10.6 | CSV import | Upload a CSV | Preview → normalizer or import |

---

## Phase 11: AI Chat / Assistant (⌘7)

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 11.1 | Open chat | Click chat nav or ⌘7 | Chat interface opens cleanly |
| 11.2 | Send message | Type and send | Response streams in (SSE) |
| 11.3 | Markdown rendering | Ask a question that generates markdown | Headers, lists, bold render correctly |
| 11.4 | KaTeX rendering | Ask for a formula | Math renders correctly |
| 11.5 | Tool approval | Trigger a tool use (e.g., "what's my risk score?") | Approval modal appears, approve → result |
| 11.6 | Artifact panel | If response generates artifact | Side panel slides out (480px) |
| 11.7 | UI blocks | If response generates `:::ui-blocks` | React components render in chat |
| 11.8 | Close chat | Click X or Escape | Chat closes, no state leak |
| 11.9 | FAB button | AskAIButton floating action button | Renders without console errors |
| 11.10 | Chat persistence | Close and reopen | Chat history preserved |

---

## Phase 12: Navigation & Cross-Cutting

### 12A. Navigation

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 12A.1 | Sidebar nav | Click each nav icon | Correct view loads, active state updates |
| 12A.2 | Sidebar tooltips | Hover over nav icons | Tooltip with view name appears |
| 12A.3 | Keyboard shortcuts | ⌘1 through ⌘8, ⌘, | Each navigates to correct view |
| 12A.4 | Command palette | ⌘K | Opens palette, can search and navigate |
| 12A.5 | Active state | Navigate between views | Correct nav item highlighted |

### 12B. Loading & Error States

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 12B.1 | Initial page load | Hard refresh | Skeletons during data fetch, no flash of empty |
| 12B.2 | View transition | Switch between views | Smooth transition, no blank flash |
| 12B.3 | Backend offline | Stop backend, navigate | Error boundaries catch, user-friendly message |
| 12B.4 | Slow endpoint | Throttle network | Loading states hold, no timeout crash |
| 12B.5 | ChunkErrorBoundary | If lazy load fails (kill dev server briefly) | Error boundary with retry button |
| 12B.6 | Empty portfolio | Login with no positions | EmptyPortfolioLanding or onboarding wizard |

### 12C. Console Health

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 12C.1 | React warnings | Check console after full navigation | Zero "Cannot update component while rendering" |
| 12C.2 | Failed requests | Check Network tab | No 4xx/5xx on normal flow |
| 12C.3 | JS errors | Check console | No uncaught exceptions |
| 12C.4 | Deprecation warnings | Check console | No critical deprecations |

---

## Phase 13: Visual / Design Quality

### 13A. Theme & Style

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 13A.1 | Light mode | Switch to light | All components readable, proper contrast |
| 13A.2 | Dark mode | Switch to dark | No white flashes, text legible, charts readable |
| 13A.3 | Premium style | Toggle premium mode | Glass effects, gradients, hover animations |
| 13A.4 | Classic style | Toggle classic | Clean, minimal, professional |
| 13A.5 | Typography | Inspect fonts | Inter font, consistent sizing hierarchy |
| 13A.6 | Color consistency | Compare accent colors | Consistent green (#22c55e or similar) across components |

### 13B. Layout & Spacing

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 13B.1 | Card alignment | Check grid on Dashboard | Consistent gap, no orphan cards |
| 13B.2 | Table alignment | Holdings, Performance tables | Column alignment, consistent padding |
| 13B.3 | Chart sizing | All chart components | Responsive, proper aspect ratios |
| 13B.4 | Scrolling | Long content areas | Smooth scroll, no jumpiness |
| 13B.5 | Overflow | Long text/numbers | Truncation with tooltip, no layout break |

### 13C. Responsive Design

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 13C.1 | Desktop (1440px) | Full-width browser | Optimal layout, sidebar visible |
| 13C.2 | Laptop (1024px) | Medium viewport | Sidebar collapses or adjusts |
| 13C.3 | Tablet (768px) | Narrow viewport | Grid reflows, no horizontal overflow |
| 13C.4 | Mobile (375px) | Mobile width | Stacked layout, touch-friendly targets |

### 13D. Animations & Polish

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 13D.1 | Hover effects | Hover over cards, buttons | Subtle lift/glow (premium mode) |
| 13D.2 | Page transitions | Navigate between views | No jarring content shift |
| 13D.3 | Loading transitions | Data loads in | Smooth fade-in, no CLS |
| 13D.4 | Toast notifications | Trigger a toast (e.g., refresh) | Appears, auto-dismisses, positioned correctly |

---

## Phase 14: Data Consistency Audit

This is a **dedicated pass** to verify the same metric shows the same value across all views where it appears. This was the #1 issue class in the 2026-03-13 audit.

| # | Metric | Views to Compare | Expected |
|---|--------|-----------------|----------|
| 14.1 | Total Portfolio Value | Dashboard, Holdings, Performance | Same value (or explained difference) |
| 14.2 | Alpha | Dashboard, Performance, Risk Analysis | Same or labeled differently |
| 14.3 | Volatility | Holdings (avg), Performance (portfolio), Settings | Each clearly labeled with scope |
| 14.4 | Risk Score | Dashboard, Research, Settings | Same score, same interpretation |
| 14.5 | Sharpe Ratio | Performance, Optimization | Same (for same period) |
| 14.6 | Beta | Performance, Risk Analysis | Same |
| 14.7 | Position weights | Holdings, Asset Allocation, Optimization | Same current weights |
| 14.8 | Position count | Holdings footer, Portfolio selector | Same count |
| 14.9 | Concentration | Dashboard card, Risk Score, Alerts | Consistent label (not "Well Diversified" + "Concentration Risk") |
| 14.10 | Phantom positions | Performance Attribution, Factor Analysis | Only current positions, or historical labeled as such |

---

## Phase 15: Performance & Network

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 15.1 | Initial load API count | Hard refresh, count requests | ≤ 30 API requests (Phase 2 target was 26) |
| 15.2 | View switch requests | Navigate Overview → Holdings | ≤ 5 new requests (data should be cached) |
| 15.3 | Duplicate requests | Check for same endpoint called 2x | None (React Query dedup working) |
| 15.4 | Request timing | Check slowest endpoint | No single request > 10s |
| 15.5 | Memory after navigation | Navigate all 9 views, check memory | No unbounded growth |
| 15.6 | Idle re-renders | Leave on Dashboard 60s | No unnecessary API calls or re-renders |
| 15.7 | Background tab | Switch to other tab, return | No burst of requests on return |

---

## Phase 16: Regression Checks (Previous Findings)

Verify fixes from the 2026-03-13 audit haven't regressed.

| # | Original Finding | Fix Commit | Check |
|---|-----------------|-----------|-------|
| 16.1 | F1: useSharedChat crash | `2d1e1551` | No "useSharedChat must be used within ChatProvider" errors |
| 16.2 | F2+F7: Risk score inverted | `2d1e1551` | Dashboard alerts use correct thresholds (low score = warning) |
| 16.3 | F18: Risk Score decimals | `2d1e1551` | Integer display, no "89.00" |
| 16.4 | F16: "Predictive" on drawdown | `66810bd8` | Badge removed from historical metrics |
| 16.5 | F21: Pre-run 0.0% | `66810bd8` | Shows "—" before optimization runs |
| 16.6 | F23: "Unknown" sector | `66810bd8` | Shows "Other" instead |
| 16.7 | F20: Scenarios grid | `66810bd8` | 4-column layout, no orphan card |
| 16.8 | F15: Trading P&L empty state | `66810bd8` | Has icon and helpful message |

### Still-Open Findings to Re-evaluate

| # | Finding | Status | Action |
|---|---------|--------|--------|
| 16.9 | F3: Portfolio Value $109K vs $27K | Open | Check if portfolio selector scoping fixed it |
| 16.10 | F4: Alpha -2.2% vs -9.3% | Open | Check if still inconsistent |
| 16.11 | F5: Volatility 47.7% vs 8.3% vs 0.1% | Open | Check if labeled properly now |
| 16.12 | F6: Phantom positions | Open | Check if historical positions labeled |
| 16.13 | F8: 6× setState-during-render | Open | Check console on Dashboard load |
| 16.14 | F9-14: Minor data quality | Mixed | Re-check GOLD, SLV, FIG, Accounts:0, tooltips |

---

## Execution Plan

### Recommended Order
1. **Phase 1** (Prerequisites) — 5 min
2. **Phase 14** (Data Consistency) — 30 min — highest-priority class of bugs
3. **Phase 16** (Regressions) — 20 min — verify fixes hold
4. **Phase 3** (Dashboard) — 30 min — most-used view
5. **Phase 4** (Holdings) — 20 min
6. **Phase 6** (Performance) — 25 min
7. **Phase 5** (Research) — 25 min
8. **Phase 7** (Scenarios) — 40 min — 7 sub-tools
9. **Phase 9** (Trading) — 25 min — involves real orders, careful
10. **Phase 11** (AI Chat) — 20 min
11. **Phase 10** (Settings) — 15 min
12. **Phase 12** (Navigation) — 15 min
13. **Phase 13** (Visual) — 30 min
14. **Phase 15** (Performance) — 20 min
15. **Phase 2** (Auth) — 15 min — disruptive (logout required)
16. **Phase 8** (Strategies) — 10 min — overlaps with Scenarios

**Total estimated time**: ~5-6 hours for full coverage

### Output Format

Same as `FRONTEND_E2E_FINDINGS_2026_03_13.md`:

```
## Summary Table
| # | Severity | Page | Issue | Fix Effort |

## Detailed Findings (per issue)
## [Severity] Short description
**Page**: Which view
**What happens**: Description
**Expected**: What should happen
**Screenshot**: (if applicable)
**Key files**: Likely files involved
**Fix effort**: Quick (< 30 min) / Medium (1-2 hrs) / Large (3+ hrs)
```

### Severity Levels
- **Blocker**: Crashes, data loss, completely broken functionality
- **Major**: Wrong data displayed, misleading UI, broken user flow
- **Minor**: Visual glitches, minor UX friction, cosmetic issues
- **Suggestion**: Design improvements, polish opportunities

---

## Future: Automated E2E Framework

After this manual pass, consider setting up Playwright for automated regression:

### Priority Smoke Tests (automate first)
1. Login → Dashboard loads with data
2. All 9 views render without errors
3. Holdings table has > 0 rows
4. Risk score renders as number
5. Performance chart renders
6. Stock search returns results
7. Console has 0 errors after full navigation
8. API request count ≤ threshold on page load

### Framework Setup (future work)
- Playwright + `@playwright/test`
- Page object model for each view
- Mock server (MSW) for deterministic data
- Visual regression with `playwright-visual-regression`
- CI/CD integration (GitHub Actions)
- Lighthouse performance budgets

---

## Notes

- **Trading tests (Phase 9)**: Be cautious with real order execution. Use paper trading account or skip execute step.
- **Auth tests (Phase 2)**: These require logout/login cycles. Run last to avoid disrupting the session.
- **Data-dependent tests**: Results vary by portfolio composition. Document the portfolio used for each run.
- **Timing**: Market hours vs after-hours affects some data (1D returns, real-time prices).

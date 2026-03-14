# Frontend E2E Review — Design, Usability & Bug Audit

**Status**: DONE — findings in `FRONTEND_E2E_FINDINGS_2026_03_13.md`
**Created**: 2026-03-13
**Goal**: Comprehensive page-by-page walkthrough of the entire app. Test every view, click every button, note all bugs, design issues, and usability problems. Produce a prioritized findings list.

---

## Context

The app underwent a major restructuring (nav overhaul, 7 new view phases, trading section, scenarios overhaul, dashboard enrichment) since the last frontend audit (2026-03-10, 38 issues — all resolved through Tiers 0-3). The current app has never been evaluated end-to-end in its post-restructure state.

**Previous audit**: `docs/planning/FRONTEND_ISSUES_2026_03_10.md` (pre-restructure, 38 issues)
**Previous visual audit**: Completed in 4 batches (V8-V30), all Chrome-verified

This is a fresh audit of the current app.

---

## Prerequisites

- [ ] Backend running on `localhost:5001` (or wherever configured)
- [ ] Frontend dev server running (`cd frontend && npm run dev`)
- [ ] Chrome open with Claude extension active
- [ ] User logged in with a real portfolio loaded (IBKR or Schwab — need real data to evaluate)
- [ ] Both light and dark mode should be tested

---

## Evaluation Method

For each page/view:
1. **Screenshot** the page in its default state
2. **Read all text** — is anything wrong, misleading, or placeholder?
3. **Check data** — are numbers real and reasonable? Any NaN, undefined, $0, or obviously wrong values?
4. **Click every interactive element** — buttons, toggles, tabs, dropdowns, cards, links
5. **Check loading states** — what does the user see while data loads? Skeleton? Spinner? Flash of empty?
6. **Check error states** — what happens if backend is slow or returns an error?
7. **Check responsive** — does it work at mobile width (375px)?
8. **Check dark mode** — does it look good in both themes?
9. **Note the overall feel** — does it feel polished or rough? Professional or toy?

---

## Pages to Review

### 1. Dashboard / Overview
The main landing page after auth. Card-based layout with summary stats.

**Check**:
- [ ] All summary cards render with real data
- [ ] Card click-through navigation works (each card → detail view)
- [ ] Performance strip / sparkline renders
- [ ] Holdings summary card — data correct?
- [ ] Alerts card — are alerts real or placeholder?
- [ ] Income card — real data?
- [ ] Market intelligence section — events loading, relevance scoring visible?
- [ ] Layout toggle (sidebar ↔ header) works
- [ ] Refresh button — spinner, toast, data updates

### 2. Research View
Merged view: Factor Analysis + Risk Analysis + Stock Lookup.

**Check**:
- [ ] Tab navigation between sub-views
- [ ] Factor Analysis — factor betas, variance decomposition, chart
- [ ] Risk Analysis — VaR, metrics, hedging strategies, risk factor descriptions
- [ ] Risk tooltips (21 placements from Tier 2) — still working?
- [ ] Stock Lookup — search works, chart loads, portfolio fit tab
- [ ] Stock analysis data — real numbers, no placeholders

### 3. Scenarios View
Overhauled in 2D.3 — card landing + 5 tool views.

**Check**:
- [ ] Landing page — 5 scenario cards render with descriptions
- [ ] **Stress Test** — scenarios load, run button works, results display
- [ ] **What-If** — preset templates work, custom weights, results table
- [ ] **Monte Carlo** — simulation runs, fan chart renders, percentile table
- [ ] **Optimization** — runs, efficient frontier chart, recommendation table
- [ ] **Backtest** — date range picker, run, equity curve + attribution
- [ ] Navigation between tools (card click → tool → back to landing)
- [ ] Session history (if implemented)

### 4. Trading View
New in 2D.5 — 4-card layout.

**Check**:
- [ ] Quick Trade card — ticker input, preview, execute flow
- [ ] Orders card — pending/completed orders display
- [ ] Baskets card — basket list, create/edit/delete, execute
- [ ] Hedge card — hedge positions, recommendations
- [ ] Real-time data refresh
- [ ] Error handling on trade failures

### 5. Performance View
Enriched in 2D.6.

**Check**:
- [ ] Performance metrics — returns (1D, 1W, 1M, 3M, YTD, 1Y) correct?
- [ ] Performance trend chart — renders, hover tooltip, legend
- [ ] Attribution breakdown — table renders, tooltips
- [ ] Trading P&L card — real data from trading analysis
- [ ] Income card — dividend/interest data
- [ ] Realized vs hypothetical toggle (if visible)
- [ ] Benchmark comparison — correct benchmark displayed

### 6. Holdings View
Core data table.

**Check**:
- [ ] All positions render with correct data
- [ ] Sector color badges
- [ ] Sort/filter works on columns
- [ ] Holdings CSV export button works
- [ ] Click-through to stock detail
- [ ] Cash positions handled correctly
- [ ] Option positions display correctly (if any)

### 7. Settings Page
**Check**:
- [ ] Account connections — list providers, connection status
- [ ] Visual style toggle (classic/premium)
- [ ] Benchmark selector
- [ ] CSV import section (if wired — 2E-b)
- [ ] Any placeholder or broken sections?

### 8. AI Chat / Assistant
**Check**:
- [ ] Chat opens/closes cleanly
- [ ] Markdown rendering in responses
- [ ] LaTeX/KaTeX math rendering
- [ ] Tool approval flow (if gateway mode)
- [ ] Artifact panel (slide-out reports)
- [ ] Dynamic UI blocks render correctly
- [ ] Chat doesn't cause parent re-renders

### 9. Cross-Cutting Concerns
- [ ] **Navigation** — sidebar and header nav both work, active state correct
- [ ] **Loading states** — no flash of unstyled content, skeletons where expected
- [ ] **Error boundaries** — ChunkErrorBoundary catches lazy load failures
- [ ] **Empty states** — what does each view show with no data?
- [ ] **Console errors** — open DevTools, check for React warnings, failed requests, JS errors
- [ ] **Network tab** — excessive API calls? Failed requests? Slow endpoints?
- [ ] **Memory** — does the app feel sluggish after navigating between views?

---

## Output Format

Produce a findings document organized by severity:

### Severity Levels
- **Blocker**: Crashes, data loss, completely broken functionality
- **Major**: Wrong data displayed, misleading UI, broken user flow
- **Minor**: Visual glitches, minor UX friction, cosmetic issues
- **Suggestion**: Design improvements, polish opportunities

### Per Finding
```
## [Severity] Short description

**Page**: Which view
**What happens**: Description of the issue
**Expected**: What should happen
**Screenshot**: (if applicable)
**Key files**: Likely files involved
**Fix effort**: Quick (< 30 min) / Medium (1-2 hrs) / Large (3+ hrs)
```

### Summary Table
At the top, include a summary table:
```
| # | Severity | Page | Issue | Fix Effort |
|---|----------|------|-------|------------|
```

---

## Scope

- **In scope**: Every page in the authenticated app. Design, data correctness, interactivity, responsiveness, dark mode, loading/error states, console errors.
- **Out of scope**: Pre-auth landing page (separate spec: `LANDING_PAGE_REVIEW_SPEC.md`), onboarding wizard (separate: 3I), backend logic, performance profiling.
- **Bias**: Note everything, even small things. Better to over-report than miss something. Severity labels help prioritize later.

# User-Perspective E2E Review Plan

**Status**: READY TO EXECUTE
**Created**: 2026-03-15
**Output**: `docs/planning/REVIEW_FINDINGS.md` — append findings as R5, R6, R7, etc.
**Existing findings**: R1 (popover transparency), R2 (squashed chart), R3 (All Accounts 30s timeout), R4 (All Accounts holdings/income empty)

---

## Goal

Walk the entire app as a real user would — not checking boxes on a QA sheet, but asking "does this make sense? does this look right? would I trust this?" at every step. When something looks wrong, investigate the code to produce a root-cause write-up (not just "this looks off").

This plan is designed for a Claude session with Chrome browser automation + code investigation agents.

---

## Prerequisites

1. Backend running on `localhost:5001` — verify: `curl localhost:5001/health`
2. Frontend running on `localhost:3000` — verify: page loads
3. Chrome browser open with Claude extension active
4. User authenticated with a real portfolio (IBKR + Schwab positions)

Before starting, call `mcp__claude-in-chrome__tabs_context_mcp` to get browser state.

---

## Methodology

### For Each View
1. **Navigate** to the view using the sidebar or URL
2. **Screenshot** the page (`mcp__claude-in-chrome__read_page`)
3. **Look at it as a user** — ask yourself:
   - Does every number look reasonable? Would a portfolio manager trust this?
   - Is anything confusing, misleading, or requiring explanation?
   - Is anything clearly wrong (NaN, $0, undefined, placeholder text)?
   - Is the visual hierarchy clear? Do I know what to look at first?
   - Are there elements that look broken, misaligned, or ugly?
4. **Interact** — click every button, tab, toggle, dropdown
5. **Check dark mode** — toggle and look for contrast/readability issues
6. **Check console** — `mcp__claude-in-chrome__read_console_messages` for errors/warnings
7. **Check network** — `mcp__claude-in-chrome__read_network_requests` for failed requests

### When You Find Something Wrong
1. Note it immediately with severity + screenshot
2. **Spawn an Explore agent** to investigate the code:
   - Find the component file, trace the data flow
   - Identify the root cause (not just symptom)
   - Find the exact files and line numbers involved
   - Suggest a fix direction
3. Write it up in the R-format (see Output Format below) and append to `REVIEW_FINDINGS.md`

### Severity Levels
- **Critical**: App crashes, data loss, completely broken core flow
- **High**: Wrong data displayed, broken user flow, major visual issue that undermines trust
- **Medium**: Misleading UI, confusing UX, visual bugs that look unprofessional
- **Low**: Minor polish, small inconsistencies, nice-to-haves

---

## Journey 1: First Impressions (Dashboard)

Navigate to `localhost:3000`. This is what the user sees every day.

### 1A. The Numbers
Look at the 6 metric cards at the top. For each one:
- Is the number reasonable for a ~$100K portfolio?
- Is the formatting correct (currency, percentage, decimals)?
- Does the color coding make sense (green=good, red=bad)?
- Are labels clear — would a non-technical investor understand them?
- Does "Total Portfolio Value" match what you'd expect from the holdings?

### 1B. Performance Trend
The chart below the metric cards:
- Is it readable? Can you see the trend?
- Are axes labeled? Can you tell the time range?
- Is it tall enough to be useful? (Known issue R2 — verify status)
- Does it match the YTD return shown in the cards?

### 1C. Dashboard Cards (below the fold)
Scroll down. Look at each card:
- **Top Holdings**: Are these the actual top positions? Do weights sum reasonably?
- **Smart Alerts**: Are alerts actionable? Do they contradict each other?
- **Income Projection**: Are the numbers reasonable? Monthly vs Annual consistent?
- **Market Intelligence**: Are events loading? Is relevance scoring visible?
- **AI Recommendations**: Is content real or placeholder?

### 1D. Portfolio Selector
Click the portfolio dropdown in the header:
- Is the dropdown readable? (Known issue R1 — verify status)
- Does switching portfolios reload data correctly?
- Does "All Accounts" work? (Known issues R3, R4 — verify status)
- Is the switch fast enough? Does it show a loading state?

### 1E. Refresh
Click the refresh button:
- Does it show a spinner?
- Does data actually update?
- Is there a toast/confirmation?

---

## Journey 2: Understanding My Holdings

Navigate to Holdings view.

### 2A. The Table
- Does position count match what you expect?
- Are position names correct (not ticker-only)?
- Are values, weights, and P&L reasonable?
- Do weights sum to ~100%?
- Is cash displayed correctly?
- Are options displayed with strike/expiry (if any)?

### 2B. Data Consistency
Compare key numbers between Dashboard and Holdings:
- Total portfolio value — same?
- Position count — same?
- Top holdings — same order and weights?

### 2C. Interactivity
- Click column headers — does sorting work?
- Click a position row — does it navigate to stock detail?
- Try CSV export — does it download?
- Check sector color badges — distinct and correct?

### 2D. Edge Cases
- Look for positions with $0 value, missing sector, "Unknown" labels
- Look for extremely small or large weights that seem wrong
- Check if closed/exercised options are still showing

---

## Journey 3: How Am I Performing?

Navigate to Performance view.

### 3A. Return Metrics
- Do 1D, 1W, 1M, 3M, YTD, 1Y returns all render?
- Are they plausible? (e.g., YTD shouldn't be +500%)
- Does the main chart render and is it readable?
- Is the benchmark shown and labeled?

### 3B. Tab-by-Tab
Click each tab (Period Analysis, Risk Analysis, Attribution, Benchmarks, Trading P&L):
- Does each tab load data?
- Are empty tabs handled gracefully (icon + message, not blank)?
- Does Attribution show current positions only, or are there phantom/closed positions?

### 3C. Cross-Check
- Does Alpha here match Alpha on Dashboard?
- Does Sharpe here match Sharpe on Dashboard?
- Does Volatility make sense given the portfolio composition?

---

## Journey 4: What Are My Risk Exposures?

Navigate to Research view.

### 4A. Factor Analysis Tab
- Do factor betas render with real values?
- Is the variance decomposition chart readable?
- Are factor names understandable (not code-level names)?

### 4B. Risk Analysis Tab
- VaR metrics — reasonable for portfolio size?
- Risk tooltips — hover over metrics, do explanations appear?
- Risk score — consistent with Dashboard?

### 4C. Stock Lookup Tab
- Search for a ticker (e.g., AAPL) — does autocomplete work?
- Do all sub-tabs load (Overview, Fundamentals, Peer Comparison, Portfolio Fit, Charts, Technicals)?
- Is the data real and current?
- Search for a position in the portfolio — does Portfolio Fit show meaningful data?

---

## Journey 5: What-If Scenarios

Navigate to Scenarios view.

### 5A. Landing Page
- Do all scenario cards render? Count them.
- Are descriptions user-friendly (no developer jargon)?
- Click each card — does it navigate correctly?
- Can you get back to the landing from each tool?

### 5B. Stress Test
- Run a stress test scenario
- Do results show position-level impacts?
- Is the portfolio impact percentage reasonable?

### 5C. What-If
- Try a preset template
- Enter custom weights — validates to 100%?
- Results show before/after comparison?

### 5D. Monte Carlo
- Run simulation — fan chart renders?
- Percentile table shows reasonable values?
- Can you read the chart? Are axes labeled?

### 5E. Optimization
- Run optimization — does it complete?
- Pre-run state: shows "—" not misleading zeros?
- Efficient frontier chart renders?
- Recommended trades make sense?

### 5F. Backtest
- Select date range — picker works?
- Run — equity curve renders?
- Metrics (Sharpe, drawdown) are reasonable?

### 5G. Tax-Loss Harvest
- Does it show harvest candidates?
- Are gain/loss amounts reasonable?
- Wash sale warnings visible if applicable?

### 5H. Rebalance
- Can you set target weights?
- Generated trades make sense (direction, amounts)?
- Does the three-step flow work (generate → preview → execute)?

---

## Journey 6: Trading

Navigate to Trading view.

### 6A. Overview
- Do all 4 cards render (Quick Trade, Orders, Baskets, Hedge)?
- Are there real orders or is it empty?
- Empty states — helpful message or just blank?

### 6B. Quick Trade (look only, don't execute)
- Ticker input works? Autocomplete?
- Can you preview a trade? Commission estimate shown?

### 6C. Orders
- Pending/completed orders display?
- Order details accessible?

### 6D. Baskets
- Basket list loads?
- Can you create/view a basket?

### 6E. Hedge Monitor
- If options exist: greeks displayed?
- Expiry alerts visible for near-term options?

---

## Journey 7: Settings & Configuration

Navigate to Settings.

### 7A. Account Connections
- Connected providers listed with status?
- Connection/disconnect/reauth buttons work?
- Is the simplified design clean (post-08c4ed91)?

### 7B. Appearance
- Visual style toggle (Classic/Premium) — works, preview swatches visible?
- Navigation layout toggle — works?

### 7C. Risk Settings
- Sliders have sensible defaults (not all 0%)?
- Save works?
- 3 tabs only (no Compliance tab)?

### 7D. CSV Import
- Import button visible?
- Upload flow works?

---

## Journey 8: AI Assistant

Open the AI Chat (sidebar or keyboard shortcut).

### 8A. Basic Chat
- Chat opens cleanly?
- Can you send a message?
- Response streams in?
- Markdown renders correctly?

### 8B. Tool Use
- Ask "what's my risk score?" — tool approval flow?
- Ask "analyze AAPL" — tool executes, result displays?

### 8C. Close & Reopen
- Close chat — no state leak?
- Reopen — history preserved?

---

## Journey 9: Cross-Cutting Checks

### 9A. Navigation
- Click every sidebar icon — correct view loads?
- Keyboard shortcuts (Cmd+1 through Cmd+8) work?
- Active state highlights correctly?

### 9B. Dark Mode
Toggle dark mode and revisit:
- Dashboard — all cards readable?
- Charts — lines/labels visible against dark background?
- Tables — row alternation/borders visible?
- Dropdowns/popovers — no transparency issues?
- No white flashes during transitions?

### 9C. Console Health
Check browser console:
- Zero React "setState during render" warnings?
- Zero uncaught exceptions?
- No failed API requests during normal navigation?
- No deprecated API warnings?

### 9D. Network Efficiency
Check Network tab:
- Count API requests on initial page load (target: ≤ 30)
- Count requests on view switch (target: ≤ 5)
- No duplicate requests to same endpoint?
- No requests > 10s?

### 9E. Data Consistency Matrix
The #1 issue class from prior audits. Check these metrics across views:

| Metric | Dashboard | Holdings | Performance | Research | Should Match? |
|--------|-----------|----------|-------------|----------|---------------|
| Total Value | metric card | sum of positions | — | — | Yes |
| Position Count | "X holdings" | table row count | — | — | Yes |
| Risk Score | metric card | — | — | Risk tab | Yes |
| Alpha | metric card | — | Performance tab | — | Yes (or labeled differently) |
| Sharpe | metric card | — | Performance tab | — | Yes |
| Volatility | metric card | — | Performance tab | Risk tab | Labeled clearly (portfolio vs position avg) |
| Concentration | alerts | — | — | — | Not contradictory |

---

## Output Format

Each finding goes in `docs/planning/REVIEW_FINDINGS.md` using this format:

```markdown
### RN. Short description

**Severity**: Critical / High / Medium / Low
**Location**: View → specific area

**Symptom**: What the user sees that's wrong.

**Root cause**: What's actually happening in the code (from investigation).

**Files**:
- `path/to/file.tsx:line` — what this file does
- `path/to/other.py:line` — backend counterpart if relevant

**Fix direction**: Concrete suggestion for how to fix it.

**Reproduction**: Step-by-step to see the issue.
```

At the top of REVIEW_FINDINGS.md, maintain a summary table:

```markdown
| # | Severity | Location | Issue | Status |
|---|----------|----------|-------|--------|
| R1 | Medium | Header → dropdown | Popover transparency | Open |
```

---

## Execution Notes

- **Work in batches**: Do Journeys 1-3 first (Dashboard, Holdings, Performance) — these are the most-used views. Then Journeys 4-6 (Research, Scenarios, Trading). Then 7-9 (Settings, Chat, Cross-cutting).
- **Don't just screenshot** — actually read the numbers and think about whether they make sense. A chart that "renders" but shows garbage data is worse than one that errors.
- **Investigate immediately**: When you find something, spawn an Explore agent right then to find the root cause. Don't defer investigation — the finding is 10x more useful with code context.
- **Prioritize trust-breaking issues**: Wrong numbers > ugly UI > minor polish. A user who sees conflicting data will not trust the tool.
- **Check both portfolios**: Test with a single-account portfolio (IBKR only) AND "All Accounts" — they exercise different code paths.
- **Note what's good too**: If a view is well-executed, say so briefly. This helps calibrate severity of issues.

---

## Reference

- **Previous findings**: `docs/planning/completed/frontend/FRONTEND_E2E_FINDINGS_2026_03_13.md` (27 issues), `docs/planning/completed/frontend/FRONTEND_E2E_FINDINGS_2026_03_14.md` (re-audit)
- **QA checklist** (for thoroughness): `docs/planning/FRONTEND_COMPREHENSIVE_E2E_PLAN.md` (16 phases, 450+ checks)
- **Known issues already found**: R1-R4 in `docs/planning/REVIEW_FINDINGS.md`
- **Architecture**: 4 frontend packages (chassis, connectors, ui, app-platform), 9 main views, backend on FastAPI

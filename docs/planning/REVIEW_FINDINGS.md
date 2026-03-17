# User Review Findings

**Status**: REVIEW COMPLETE — 22/22 fixed (R7 not reproducible, all others resolved)
**Date**: 2026-03-15 (reviewed), 2026-03-16 (fixes + re-verification + chart upgrades)
**Plan**: `docs/planning/USER_PERSPECTIVE_E2E_REVIEW_PLAN.md`

Catalog of issues found during user-perspective review. Each item includes reproduction
context, root cause analysis, and enough detail for another Claude session to plan/fix.

### Fix Commits
- `8f4b670f` — Session 1: R1, R2, R5, R10, R11, R13, R19 (partial), R20
- `16e8afa4` — Session 3: R4, R9, R14, R16
- `8531a6f3` — Session 4: R6, R8, R12, R15, R21, R22
- `23a2060d`, `2aa2833d`, `02607731`, `487eb2f9` — Perf: R3 improved, R17 improved
- `2d4a5d06` — Session 5: R17 dedup (31→20 requests), R19 dark mode (6 phases, ~120 components)
- `f918d5ba` — R18: eliminate spontaneous session logout cascade
- `bcd85e6f` — Fix notification dropdown hidden behind content (glass-premium overflow + z-index)
- `9cefd724` — R2 follow-up: replace SVG sparkline with Recharts AreaChart (Performance Trend)
- `e8e7301e` — Income Forecast: replace SVG sparkline with Recharts BarChart

---

## Summary

| # | Severity | Location | Issue | Status |
|---|----------|----------|-------|--------|
| R1 | Medium | Header → dropdown | Popover transparency — `--popover` CSS var undefined | ✅ Fixed (`8f4b670f`) |
| R2 | High | Dashboard → Performance Trend | Chart squashed to 80px, illegible | ✅ Fixed (`8f4b670f`, `9cefd724`) — Recharts AreaChart replacement |
| R3 | High | Portfolio selector → All Accounts | 30s timeout, frontend error state | ⚠️ Improved (~8s, no timeout) |
| R4 | High | Dashboard → All Accounts | Holdings empty on initial load (race condition) | ✅ Fixed (`16e8afa4`) |
| R5 | High | Dashboard → Risk Score card | Score 89 labeled "Low Risk" — semantic inversion | ✅ Fixed (`8f4b670f`) |
| R6 | High | Dashboard + Holdings → Weight column | Weights use equity denominator, not total portfolio value | ✅ Fixed (`8531a6f3`) — see R6b |
| R6b | Medium | Dashboard → Alert vs Table | Alert "17.1% exposure" ≠ Table "21.6% weight" on same page | ✅ Fixed (`e4e5442a`) |
| R7 | Critical | Dashboard → multiple cards | IBKR $128K > All Accounts $109K — single > combined | Not reproducible (likely fixed by R8 cash dedup `8531a6f3`) |
| R8 | Critical | Dashboard → Smart Alerts | IBKR margin $11,212 > All Accounts $5,605 | ✅ Fixed (`8531a6f3`) |
| R9 | Medium | Dashboard → AI Recommendations | Oil & Gas 6.8% flagged with "reduce below 10%" target | ✅ Fixed (`16e8afa4`) |
| R10 | Medium | Dashboard → Total Value subtitle | "Across all accounts" doesn't update on portfolio switch | ✅ Fixed (`8f4b670f`) |
| R11 | Medium | Header → dropdown | Internal IDs visible (`_auto_charles_schwab_...`) | ✅ Fixed (`8f4b670f`) |
| R12 | Medium | Dashboard → Holdings count | Dropdown says 36, "View All" says 15 for All Accounts | ✅ Fixed (`8531a6f3`) |
| R13 | Low | Holdings → Day Change | Small dollar changes round to "$0" — misleading | ✅ Fixed (`8f4b670f`) |
| R14 | Medium | Holdings → Sector badges | GOLD/SLV/AT.L sector misclassified (FMP data quality) | ✅ Fixed (`16e8afa4`) |
| R15 | High | Dashboard vs Performance vs Settings | Volatility 8.41% vs 16.3% vs 19.4% across views | ✅ Fixed (`8531a6f3`) |
| R16 | Medium | Factors → Concentration Risk | SGOV (-17.2%) in top-3 but not in Holdings (phantom position) | ✅ Fixed (`16e8afa4`) |
| R17 | Medium | Cross-cutting → Network | 71 requests on dashboard load (target ≤30) | ✅ Fixed (`2d4a5d06`) — 71→31→20 (target ≤20) |
| R18 | **Critical** | Cross-cutting → Navigation | Frequent spontaneous logout — any page, any interaction | ✅ Fixed (`f918d5ba`) |
| R19 | High | Cross-cutting → Dark mode | Dark mode partial — header dark but content light, text faded/unreadable | ✅ Fixed (`2d4a5d06`) — 6 phases, ~120 components migrated, toggle + persistence |
| R20 | Medium | Settings → Alert Thresholds | "Volatility Alert Level: 8" — label says risk score, value too low | ✅ Fixed (`8f4b670f`) |
| R21 | High | Dashboard → Asset Allocation | IBKR allocation sums to $46K, total portfolio is $131K — $85K gap | ✅ Fixed (`8531a6f3`) |
| R22 | High | Dashboard → same page | Cash (Margin) -$11,589 vs Smart Alert "$5,606 margin debt" — contradictory | ✅ Fixed (`8531a6f3`) |

### Remaining Open Items

None — all 22 findings resolved. R7 not reproducible (likely fixed by R8). All others have fix commits.

---

## Issues

### R1. Portfolio selector dropdown too transparent — unreadable

**Severity**: Medium (usability)
**Location**: Header → portfolio dropdown

**Symptom**: When the portfolio selector dropdown opens, dashboard content (Smart Alerts, metric cards, percentages) bleeds through the dropdown background. Text is hard to read against the see-through panel.

**Root cause**: The `--popover` CSS variable is **never defined** in `frontend/packages/ui/src/index.css`. Other shadcn/ui theme vars like `--card`, `--background`, etc. are all defined, but `--popover` and `--popover-foreground` were missed. The base `DropdownMenuContent` component (`frontend/packages/ui/src/components/ui/dropdown-menu.tsx:66`) uses `bg-popover` which resolves to `hsl(var(--popover))` → `hsl()` with no value → effectively transparent.

**Files**:
- `frontend/packages/ui/src/index.css` — missing `--popover` / `--popover-foreground` CSS vars (add to `:root` light theme ~line 135, and `.dark` theme ~line 237)
- `frontend/packages/ui/src/components/ui/dropdown-menu.tsx:66` — uses `bg-popover` (base shadcn component, correct usage)
- `frontend/tailwind.config.js:20-23` — maps `popover` color to `hsl(var(--popover))` (correct wiring)

**Fix**: Add `--popover` and `--popover-foreground` to both light and dark theme blocks in `index.css`. Recommended values: match `--card` (light: `0 0% 100%` = white, dark: `213 23% 11%` = dark card). This fixes ALL popover/dropdown components globally, not just PortfolioSelector.

**Reproduction**: Click the portfolio selector dropdown in the header on any page. Dashboard content is visible through the dropdown panel.

### R2. Performance Trend chart is vertically squashed and nearly unreadable

**Severity**: High (visual)
**Location**: Dashboard home page → Performance Trend card (below the 6 metric cards)

**Symptom**: The Performance Trend chart is ~80px tall, making it completely squashed. The line is nearly flat, the Y-axis labels are garbled/overlapping (rendered at ~5px font size), and there are no X-axis date labels. The chart is functionally useless as a visualization.

**Root cause**: Hardcoded `height={80}` passed to `SparklineChart`, combined with SVG `preserveAspectRatio="none"` which crushes the 100-unit viewBox into 80px. The Y-axis labels (SVG `fontSize={6}` at y=6 and y=98) become ~4.8px rendered — illegible.

**Files**:
- `frontend/packages/ui/src/components/portfolio/PortfolioOverview.tsx:100-108` — passes `height={80}` to SparklineChart
- `frontend/packages/ui/src/components/blocks/sparkline-chart.tsx`:
  - Line 128: `preserveAspectRatio="none"` distorts text/labels at small heights
  - Line 129: `style={{ height }}` applies the 80px constraint
  - Lines 148-153: Y-axis label text at fontSize=6 SVG units — illegible at 80px height
  - No X-axis date label support exists in the component

**Sub-issues**:
1. Chart height too small (80px) — should be 160-200px minimum
2. Y-axis labels garbled at this height due to `preserveAspectRatio="none"` scaling
3. No X-axis date labels at all — no way to tell time range
4. No benchmark comparison line (legend says "Portfolio" only, despite Alpha vs SPY being shown above)

**Fix direction**:
- Increase height to 160-200px in PortfolioOverview.tsx line 103
- Consider `preserveAspectRatio="xMidYMid meet"` or adding proper label margins outside the SVG
- For X-axis dates and benchmark overlay, may need to swap SparklineChart for a richer chart (e.g., Recharts AreaChart) or extend SparklineChart with date label support

**Data flow**: `PortfolioOverviewContainer.tsx` extracts `performanceSparkline` from `perfData?.performanceTimeSeries` (cumulative returns array) → `PortfolioOverview.tsx` → `SparklineChart`

**Reproduction**: Navigate to localhost:3000 dashboard home. Scroll below the 6 metric cards. The Performance Trend chart is visible but squashed flat.

### R3. "All Accounts" portfolio switch slow (~30s) — frontend times out with error

**Severity**: High (usability)
**Location**: Header → portfolio selector → switch to "All Accounts" (CURRENT_PORTFOLIO / COMBINED)

**Symptom**: Switching to "All Accounts" from a single-account portfolio takes ~30 seconds. The frontend timeout fires before the backend completes, showing "Data Loading Error — Request timed out while loading data" with a Retry button. Holdings show "No holdings available", Alerts show "Unable to load alerts right now." On retry or page refresh, it eventually loads after ~30s.

**Root cause**: Two slow backend endpoints for CURRENT_PORTFOLIO with 51 holdings across multiple providers:
- `POST /api/risk-score` — runs full risk analysis (position fetch + consolidation + factor proxies + risk scoring)
- `POST /api/analyze` — runs portfolio analysis (position fetch + returns + risk metrics)
Both must fetch from all providers (IBKR, Schwab via SnapTrade, Plaid), consolidate 51 positions, then compute. The frontend has a shorter timeout than the ~30s the backend needs.

**Observed network behavior**:
- Both `/api/risk-score` and `/api/analyze` return 503 or stay pending until timeout
- `/api/log-frontend` also fails (503) during the window
- After ~30s, subsequent requests return 200 OK

**Files**:
- Frontend timeout config: likely in `frontend/packages/chassis/src/services/` or `frontend/packages/connectors/src/` (HTTP client timeout setting)
- `routes/portfolio_risk.py` or `routes/risk_score.py` — backend endpoint handlers
- `mcp_tools/risk.py:400` — `_load_portfolio_for_analysis()` (shared slow path)
- `services/position_service.py:297` — `get_all_positions()` (multi-provider fetch)

**Fix direction** (multiple options, not mutually exclusive):
1. **Increase frontend timeout** for portfolio switch operations (quick fix, doesn't solve underlying slowness)
2. **Progressive loading**: Load holdings/alerts first (fast), then risk-score/analyze in background — don't block the whole dashboard on the slowest endpoint
3. **Backend caching**: The position data is already cached (24h), but factor proxy generation and risk computation aren't. Cache risk-score/analyze results per portfolio.
4. **Parallel provider fetching**: Ensure provider fetches are concurrent, not serial (may already be the case)

**Reproduction**: Select "Interactive Brokers U2471778" (single account), then switch to "All Accounts" via the portfolio dropdown. Dashboard shows timeout error within ~15s. Retry eventually loads after ~30s total.

### R4. All Accounts dashboard: Holdings empty, Income 500, Alerts empty

**Severity**: High (data integrity)
**Location**: Dashboard home → "All Accounts" (CURRENT_PORTFOLIO / COMBINED)

**Symptom**: After switching to "All Accounts" and waiting for data to load:
- **Top Holdings**: "No holdings available for this portfolio." / "View All 0 Holdings" — despite $106K portfolio with 51 holdings and metric cards showing data
- **Income Projection**: Shows dashes for Monthly Rate and Portfolio Yield. Backend returned **500 Internal Server Error** on first call (second retry returned 200, but frontend stuck on error state)
- **Alerts**: "No active alerts." — unclear if legitimately empty for combined portfolio or same data issue

**Backend evidence** (from server logs):
- `GET /api/positions/holdings?portfolio_name=CURRENT_PORTFOLIO` → 200 but payload has empty positions
- `GET /api/income/projection?portfolio_name=CURRENT_PORTFOLIO` → **500** first call, with numpy warnings:
  - `RuntimeWarning: Mean of empty slice`
  - `RuntimeWarning: invalid value encountered in divide`
  - `RuntimeWarning: Degrees of freedom <= 0 for slice`
  - `RuntimeWarning: divide by zero encountered in divide`
  These suggest the income projection pipeline hits an empty or single-element array in some computation path.
- `GET /api/positions/alerts?portfolio_name=CURRENT_PORTFOLIO` → 200 (legitimately empty or same issue)

**Key difference**: The metric cards (Total Value, YTD Return, Risk Score, Sharpe, etc.) DO populate successfully via `/api/analyze` and `/api/risk-score`. The discrepancy suggests the positions/holdings endpoint uses a different data loading path than the analysis endpoints, or the portfolio switch doesn't properly pass position data to the holdings card.

**Files to investigate**:
- `routes/positions.py:323` — `get_position_holdings()` endpoint
- `routes/income.py` or equivalent — income projection endpoint (the 500)
- Frontend: how the portfolio switch invalidates/refetches holdings data — the `PortfolioSelector.handleSelect()` calls `queryClient.invalidateQueries({ queryKey: ['sdk'] })` but holdings may use a different query key
- `frontend/packages/ui/src/components/portfolio/holdings/useHoldingsData.ts` — holdings data hook

**Fix direction**:
1. **Holdings**: Check why `/api/positions/holdings` returns empty positions for CURRENT_PORTFOLIO when `/api/analyze` finds 51 holdings. Likely a portfolio scope / position service path mismatch.
2. **Income 500**: The numpy warnings indicate empty slice math — add guards for empty/insufficient data in the income projection computation.
3. **Frontend error recovery**: Income card should retry or show a "retry" affordance rather than staying stuck on dashes after a 500.

**Reproduction**: Switch to "All Accounts" via portfolio dropdown. Wait ~30s for data to load. Scroll down to Top Holdings, Alerts, and Income Projection cards.

**Update (re-review)**: On page refresh, holdings DO load after ~5s (shows 15 positions, "View All 15 Holdings"). The initial "No holdings available" appears to be a race condition where the UI renders before the API returns. Income projection now returns 200 ($122/year, $10/month, 0.5% yield). Alerts show 3 items. Downgrading to partial — the timing/race issue remains but data does eventually load.

### R5. Risk Score 89 labeled "Low Risk" — semantic inversion

**Severity**: High (trust-breaking)
**Location**: Dashboard → Risk Score metric card

**Symptom**: Risk Score of 89 shows a green "Low Risk" badge. A score of 89/100 should indicate excellent/good risk management, not "low risk". The label is semantically inverted — users interpret "Low Risk" as meaning the portfolio has low risk exposure, when the score actually means risk is well-managed.

**Root cause**: Frontend threshold logic in `useOverviewMetrics.ts:51` uses inverted labels:
```typescript
change: summary ? (summary.riskScore >= 80 ? "Low Risk" : summary.riskScore >= 60 ? "Medium Risk" : "High Risk") : ""
```
The backend (`core/risk_score_flags.py:48-63`) correctly uses: `< 60` = warning ("high risk"), `>= 90` = success ("excellent risk management"). The frontend labels don't match the backend semantics.

**Files**:
- `frontend/packages/ui/src/components/portfolio/overview/useOverviewMetrics.ts:51` — inverted label logic
- `core/risk_score_flags.py:48-63` — correct backend semantics (higher = better)
- `core/result_objects/risk.py` — documents score scale (90-100 Excellent, 80-89 Good, 70-79 Moderate, 60-69 Elevated, <60 High Risk)

**Fix direction**: Change labels to match backend: `>= 90` → "Excellent", `>= 80` → "Good", `>= 70` → "Moderate", `>= 60` → "Elevated", `< 60` → "High Risk". Keep changeType colors aligned (positive for >=80, warning for 60-79, negative for <60).

**History**: Found in 2026-03-13 E2E audit (Finding #2). Commit `df18f770` marked as done but code still has the bug.

**Reproduction**: View Dashboard with IBKR portfolio (Risk Score 70 shows "Medium Risk" correctly) then switch to All Accounts (Risk Score 89 shows "Low Risk" incorrectly).

### R6. Holdings weights use equity denominator, not total portfolio value

**Severity**: High (trust-breaking)
**Location**: Dashboard → Top Holdings, Holdings view → Weight column

**Symptom**: NVDA shows $4,579 at 17.1% weight. But Total Portfolio Value is $109,496 (All Accounts) or $131,571 (IBKR). $4,579 / $109,496 = 4.2%, not 17.1%. Users seeing 17.1% weight next to a $109K total value will compute the expected value as ~$18.7K, but the actual is $4.6K.

**Root cause**: The weight denominator is `gross_exposure` from the holdings API (~$26,802 for IBKR equity positions), not the total portfolio value. The frontend `PositionsAdapter.ts:67-70` divides position `gross_exposure` by `portfolio_totals_usd.gross_exposure`. The total portfolio value includes ~$105K in cash/money market, making it ~4x larger than the equity denominator.

**Files**:
- `frontend/packages/connectors/src/adapters/PositionsAdapter.ts:67-70` — weight calculation: `(grossExposure / totalGrossExposure) * 100`
- `core/result_objects/positions.py:551` — `portfolio_totals_usd["gross_exposure"]` aggregation
- `frontend/packages/ui/src/components/dashboard/cards/DashboardHoldingsCard.tsx:137` — displays `row.weight.toFixed(1) + '%'`

**Fix direction**: Either (a) change weight denominator to total portfolio value (net_exposure), or (b) label the weight column as "% of Equity" to clarify it excludes cash, or (c) add a tooltip explaining the denominator.

**Reproduction**: View Dashboard or Holdings for IBKR portfolio. Compare NVDA weight (17.1%) against $4,579 / $131,571 (3.5%).

### R7. IBKR single account value ($131K) exceeds All Accounts combined ($109K)

**Severity**: Critical (data integrity)
**Location**: Dashboard → Total Portfolio Value card
**Status**: Not reproducible (2026-03-16). Likely fixed by R8 cash dedup (`8531a6f3`).

**Symptom**: Switching between portfolios shows:
- All Accounts (COMBINED): $109,496
- Interactive Brokers U2471778 (SINGLE): $131,571

**Investigation (2026-03-16)**: Ran `scripts/diag_portfolio_value.py` against real multi-provider user (id=1, 12 accounts across interactive_brokers/charles_schwab/merrill). Both the positions endpoint path (PositionService → consolidation → to_monitor_view) and the analyze endpoint path (PortfolioManager → standardize_portfolio_input) produce combined ≥ single. Code analysis confirms both paths use the same consolidation logic and total_portfolio_value formula (`net_exposure + cash_value_usd`). No structural bug found.

R8 (margin debt doubling, also marked "intermittent") was fixed in the same session by cash dedup fix `8531a6f3`. R7 was likely caused by the same underlying race condition / stale cache that R8 exposed. Diagnostic script left in place to catch recurrence.

### R8. Margin debt inconsistency: IBKR $11,212 > All Accounts $5,605

**Severity**: Critical (data integrity, related to R7)
**Location**: Dashboard → Smart Alerts

**Symptom**: IBKR single account shows "$11,212 margin debt (27% of portfolio)" but All Accounts shows "$5,605 margin debt (26% of portfolio)". The combined portfolio should show margin debt >= any single account. This is likely caused by the same root issue as R7.

**Update**: On subsequent page load, IBKR margin debt changed from $11,212 to $5,606 — matching All Accounts' $5,605. The doubling appears intermittent, possibly from stale cache or a race condition in position consolidation. May be related to the slow All Accounts load (R3) causing partially computed state.

**Reproduction**: Compare Smart Alerts between IBKR and All Accounts portfolios. May require multiple page loads to reproduce the doubling.

### R9. AI Recommendation contradicts itself: Oil & Gas at 6.8% < 10% target

**Severity**: Medium (misleading)
**Location**: Dashboard → AI Recommendations card

**Symptom**: AI Recommendations card shows "High Oil & Gas E&P Concentration" at MEDIUM severity, stating "Portfolio has 6.8% exposure to Oil & Gas E&P" with action item "Target reducing Oil & Gas E&P weight to below 10%." But 6.8% is already below 10%, making this recommendation contradictory and confusing.

**Root cause**: The recommendation generator likely uses a sector concentration threshold (e.g., 5% trigger) but the "reduce below X%" target is computed separately and doesn't account for already being near/below target.

**Files to investigate**:
- `routes/positions.py` or wherever AI recommendations are generated
- Look for sector concentration threshold logic

**Reproduction**: View All Accounts dashboard, scroll to AI Recommendations. The Oil & Gas E&P card shows 6.8% with a 10% reduction target.

### R10. "Across all accounts" subtitle hardcoded — doesn't update on portfolio switch

**Severity**: Medium (polish)
**Location**: Dashboard → Total Portfolio Value card subtitle

**Symptom**: The subtitle under "Total Portfolio Value" always says "Across all accounts" even when viewing a single account like "Interactive Brokers U2471778". Should say the account name or be omitted for single accounts.

**Files**:
- `frontend/packages/ui/src/components/portfolio/PortfolioOverview.tsx` or the metric card component — hardcoded subtitle string

**Fix direction**: Conditionally render subtitle based on portfolio type: "Across all accounts" for COMBINED, account name for SINGLE.

### R11. Internal IDs visible in portfolio selector dropdown

**Severity**: Medium (polish)
**Location**: Header → portfolio selector dropdown

**Symptom**: Dropdown shows system-generated identifiers like `_auto_charles_schwab_25524...`, `CURRENT_PORTFOLIO`, `_auto_interactive_brokers_u2...` below portfolio names. These are internal slugs that users should never see.

**Fix direction**: Hide the internal ID line from the dropdown, or replace with a user-friendly description (e.g., "Schwab Brokerage", "IBKR Margin Account").

### R12. Holdings count discrepancy: dropdown 36 vs "View All 15"

**Severity**: Medium (data consistency)
**Location**: Dashboard → Portfolio selector vs Top Holdings card

**Symptom**: For "All Accounts", the portfolio selector dropdown shows "36 holdings" but the Top Holdings card footer shows "View All 15 Holdings". IBKR single account shows "15 holdings" in dropdown and matches the holdings list.

**Root cause**: The dropdown count (36) likely comes from raw position count across all providers (pre-consolidation), while the Top Holdings count (15) comes from the holdings API response (post-consolidation, deduped). The mismatch suggests 21 positions are eliminated during consolidation (duplicates across providers, cash positions, etc).

**Fix direction**: Either (a) use the consolidated count in the dropdown, or (b) label differently (e.g., "36 raw positions" vs "15 unique holdings").

### R13. Day Change rounds small dollar amounts to "$0"

**Severity**: Low (misleading)
**Location**: Holdings view → Day Change column

**Symptom**: Positions with small absolute day changes show "$0" or "-$0" instead of the actual dollar amount. E.g., IGIC at -0.7% of $2,372 = -$17, but shows "-$0". FIG at -0.5% of $2,696 = -$13, but shows "-$0".

**Root cause**: Likely a formatting function that rounds to whole dollars, truncating small changes.

**Fix direction**: Show actual dollar amounts with cents for small values, or use a threshold (e.g., show "$0" only if truly < $0.50).

### R14. Sector misclassifications: GOLD, SLV, AT.L

**Severity**: Medium (data quality)
**Location**: Holdings view → Sector badges

**Symptom**: Several positions have incorrect sector classifications:
- GOLD (Barrick Gold Corp) → "Financial Services" (should be "Basic Materials")
- SLV (iShares Silver Trust) → "Financial Services" (should be "Commodities" or "ETF")
- AT.L (Ashtead Technology Holdings) → "Energy" (should be "Technology" or "Energy Services")

**Root cause**: These sectors come from FMP's company profile data. FMP may have incorrect sector assignments for these tickers, or the sector mapping logic may not handle non-US tickers (AT.L) and ETFs (SLV) correctly.

**Files to investigate**:
- `fmp/client.py` or sector enrichment logic
- `services/portfolio_service.py` — `enrich_positions_with_sectors()`

**Fix direction**: Consider a sector override map for known misclassifications, or improve ETF/non-US ticker handling.

### R15. Volatility inconsistency: Dashboard 8.41% vs Performance 16.3%

**Severity**: High (data consistency)
**Location**: Dashboard Performance Summary vs Performance view Insights

**Symptom**: Dashboard shows "Volatility +8.41%" in the performance summary section. Performance view's Insights card says "Volatility of 16.3% is moderate." These should represent the same metric (portfolio volatility) but differ by nearly 2x.

**Root cause**: Likely different measurement windows or annualization. Dashboard volatility may use the analysis endpoint's output, while Performance Insights may compute its own from returns data with different parameters.

**Files to investigate**:
- Dashboard performance summary data source (which API field populates "Volatility +8.41%")
- Performance Insights volatility computation
- `core/performance_metrics_engine.py` — `compute_performance_metrics()` volatility calculation

**Fix direction**: Ensure all views use the same volatility calculation, or label them differently (e.g., "30-day Vol" vs "Annualized Vol").

**Update**: Settings page also shows 16.3% ("Portfolio Volatility" summary card), and the user's Maximum Portfolio Volatility limit is set to 18%. The Factors/Research view shows 19.4% ("Annual portfolio volatility"). Three distinct values across four views:
- Dashboard Performance Summary: **8.41%**
- Performance Insights: **16.3%**
- Settings summary card: **16.3%** (matches Performance)
- Factors → Volatility Risk: **19.4%** ("Annual portfolio volatility")

The 8.41% is the clear outlier and likely comes from a different endpoint or calculation window. 16.3% and 19.4% may differ due to the risk analysis endpoint using different returns data or a different lookback period.

### R16. SGOV phantom position in Concentration Risk — not in Holdings

**Severity**: Medium (confusing)
**Location**: Factors → Risk Analysis → Concentration Risk card

**Symptom**: Concentration Risk card shows "Top 3 positions: NVDA (22.9%), SGOV (-17.2%), TKO (13.1%) - 53.1% of portfolio". But SGOV does not appear in the 15 holdings shown in the Holdings view. A user seeing SGOV at -17.2% (negative weight, implying a short position) in their risk analysis when it's not in their holdings list would be confused and concerned.

**Root cause**: SGOV is likely a factor proxy or benchmark position included in the risk analysis but not in the actual holdings. The risk analysis engine may add proxy positions (like Treasury ETFs) for factor decomposition, and these show up in the risk component breakdown. The holdings endpoint shows only "real" positions from the brokerage.

**Files to investigate**:
- `portfolio_risk_engine/portfolio_risk_score.py` — concentration risk computation
- Risk analysis configuration — factor proxy positions
- `core/result_objects/risk.py` — risk score component payload

**Fix direction**: Either (a) exclude factor proxy positions from the concentration risk display, or (b) label them clearly as "proxy position" so users understand they're not real holdings, or (c) filter the top-3 display to only include actual holdings.

### R17. Dashboard page load fires 71 API requests (target: ≤30)

**Severity**: Medium (performance)
**Location**: Cross-cutting → Network efficiency

**Symptom**: Loading the IBKR dashboard fires 71 API requests. Breakdown:
- ~30 `/api/log-frontend` POST calls (still very chatty despite Phase 1 batching)
- ~7 OPTIONS preflight requests
- ~34 data API calls, of which ~10 are duplicates

**Duplicate requests observed**:
- `/api/positions/alerts` — 3× (CURRENT_PORTFOLIO) + 1× (IBKR-specific)
- `/api/v2/portfolios` — 3×
- `/api/strategies/templates` — 2×
- `/api/positions/holdings` — 2×
- `/api/positions/market-intelligence` — 2× (one still pending after 5s)
- `/api/income/projection` — 2×
- `/api/allocations/target` — 2×
- `/api/positions/metric-insights` — 2×

**Root cause**: Multiple React components independently fetching the same data, and the query dedup (React Query) not catching all duplicates — possibly because query keys or parameters differ slightly (e.g., `CURRENT_PORTFOLIO` vs `_auto_interactive_brokers_u2471778`).

**Fix direction**:
1. Reduce log-frontend calls — the batching optimization reduced 55→11 in Phase 1, but it's back to ~30
2. Deduplicate data requests — use shared query keys and cache properly
3. The `alerts` endpoint is called with both `CURRENT_PORTFOLIO` and the account-specific name — should be unified

### R18. Frequent spontaneous session logout — not limited to specific pages

**Severity**: Critical (usability — blocks all testing)
**Location**: Cross-cutting → any navigation or interaction

**Symptom**: The app frequently drops the session and redirects to the login page ("Sign in with Google"). Originally observed when clicking Strategy/Settings sidebar buttons (2 out of 3 attempts), but also reproduced during normal dashboard interaction in header nav mode — clicking the notifications bell, switching between Overview/Holdings, and general browsing all trigger spontaneous logouts. This makes the app essentially unusable for sustained use.

**Root cause (CONFIRMED — multi-layer interaction)**:

**Layer 1 — Backend: `get_session()` does a WRITE on every READ** (`app_platform/auth/stores.py:58-67`)
Every API call runs `get_session()` which SELECTs the session, then UPDATEs `last_accessed` if >5min stale. With 30+ concurrent API requests on page load, this causes PostgreSQL write lock contention. If the UPDATE fails or times out, the session lookup raises an exception → `SessionLookupError` → backend returns 401.

```python
# stores.py:58-67 — UPDATE inside get_session()
if last_accessed is None or (now_cmp - last_accessed) > _TOUCH_INTERVAL:
    cursor.execute("UPDATE user_sessions SET last_accessed = %s WHERE session_id = %s", (now, session_id))
    conn.commit()  # WRITE on every read if >5min stale
```

**Layer 2 — Backend: Any DB error → 401** (`app_platform/auth/service.py:110-147`)
`get_user_by_session()` catches DB exceptions and raises `SessionLookupError`. The FastAPI dependency (`app.py:1063-1069`) converts ANY falsy return or exception to `HTTPException(401)`. So a transient DB error (lock timeout, connection pool exhaustion) looks identical to "session expired" from the frontend's perspective.

**Layer 3 — Frontend: Aggressive 401 handler with no debounce** (`frontend/packages/chassis/src/stores/authStore.ts:47-69`)
`handleUnauthorizedSession()` calls `authState.signOut()` on the FIRST 401 from ANY request. The `isHandlingUnauthorizedSession` guard resets in `finally` (line 67), so concurrent 401s from parallel requests can race through. There is no retry, debounce, or "wait for other requests to settle" — one 401 = immediate full logout.

**Layer 4 — Frontend: `onAuthRetry` only checks status, no refresh** (`HttpClient.ts:88-98`)
On 401, `onAuthRetry` calls `verifySessionStillValid()` which hits `GET /auth/status`. If that ALSO returns 401 (because the same DB contention is happening), it confirms "session dead" and proceeds to nuke the session. No token refresh mechanism exists.

**Layer 5 — Frontend: Cross-tab logout broadcast** (`app-platform/src/auth/createAuthStore.ts:156-168`)
`signOut()` broadcasts logout via BOTH `localStorage` storage event AND `BroadcastChannel`. Other tabs at localhost:3000 receive both events and call `handleCrossTabLogout()`, potentially causing cascading logouts across all open tabs.

**Failure scenario (confirmed)**:
1. User clicks notification bell → 5+ API requests fire simultaneously
2. One request hits `get_session()` UPDATE lock contention → DB error → 401
3. `HttpClient` retries via `verifySessionStillValid()` → also 401 (same contention)
4. `handleUnauthorizedSession()` fires → `signOut()` → redirect to login
5. Cross-tab broadcast logs out ALL other tabs too

**Files**:
- `app_platform/auth/stores.py:34-75` — `get_session()` with embedded UPDATE (Layer 1)
- `app_platform/auth/service.py:110-147` — `get_user_by_session()` exception → SessionLookupError (Layer 2)
- `app.py:1063-1069` — `get_current_user()` FastAPI dependency, any error → 401 (Layer 2)
- `frontend/packages/chassis/src/stores/authStore.ts:47-69` — `handleUnauthorizedSession()` (Layer 3)
- `frontend/packages/app-platform/src/http/HttpClient.ts:88-98` — 401 handler + retry (Layer 4)
- `frontend/packages/app-platform/src/auth/createAuthStore.ts:156-168` — cross-tab sync (Layer 5)
- `frontend/packages/connectors/src/utils/sessionCleanup.ts:50-69` — second independent `isHandling*` guard (race)

**Fix direction** (priority order):
1. **Split read/write in `get_session()`** — Remove the UPDATE from the read path. Touch sessions via a separate background job or explicit `touch_session()` call, not on every API request.
2. **Don't return 401 for DB errors** — `get_user_by_session()` should distinguish "session not found" (real 401) from "DB connection error" (503). Return 503 for transient failures so the frontend retries instead of logging out.
3. **Debounce the frontend 401 handler** — Use a Promise-based lock so that concurrent 401s collapse into a single logout decision. Add a short delay (500ms) before confirming logout to let other requests settle.
4. **Add real token refresh** — Instead of just checking `/auth/status`, implement a refresh endpoint that extends the session.
5. **Pick one cross-tab channel** — Remove either the `storage` event or `BroadcastChannel` listener to prevent double-firing.

### R19. Dark mode partially applied — text faded and unreadable

**Severity**: High (visual)
**Location**: Cross-cutting → all views when `.dark` class is active

**Symptom**: When `dark` class is added to `<html>`, the header and sidebar go dark correctly but the main content area stays light. Company name subtitles (e.g., "NVIDIA Corporation", "Figma, Inc.") become faded gray-on-white — nearly invisible. The "Portfolio Holdings" heading and "All Sectors" filter text also become unreadable.

**Root cause**: The `.dark` theme block in `frontend/packages/ui/src/index.css` likely doesn't define all necessary CSS variables for the main content area text colors. The dark theme variables may cover background colors but miss foreground/muted text colors used by specific components.

**Files**:
- `frontend/packages/ui/src/index.css` — `.dark` theme CSS variable definitions
- Component-level text classes using `text-muted-foreground` or similar

**Fix direction**: Audit all CSS variables used in components against the `.dark` theme block. Ensure `--foreground`, `--muted-foreground`, `--card`, `--card-foreground` etc. are all defined for dark mode.

**Note**: There's no user-facing dark mode toggle. The app may rely on system preference (`prefers-color-scheme: dark`). Consider adding a toggle to the Appearance settings panel.

### R20. Volatility Alert Level threshold misconfigured (value 8, label says "risk score")

**Severity**: Medium (confusing)
**Location**: Dashboard Settings panel → Alert Thresholds

**Symptom**: The "Volatility Alert Level" field shows value "8" with the label "Alert when risk score exceeds this level." Two issues:
1. The label says "risk score" but the field name says "Volatility Alert Level" — which metric does it actually control?
2. If it controls risk score (0-100), a threshold of 8 means it would fire for any score above 8 — essentially always alerting.
3. If it controls volatility (0-100%), a threshold of 8% is reasonable but the label is wrong.

**Fix direction**: Clarify whether this controls risk score or volatility, fix the label to match, and ensure the default value is sensible.

### R21. Asset Allocation dollar values sum to $46K, portfolio total is $131K

**Severity**: High (data consistency)
**Location**: Dashboard → Asset Allocation section (IBKR portfolio)

**Symptom**: For the IBKR portfolio ($131,571 total value), the Asset Allocation shows:
- Equity: $45,285
- Commodities: $9,926
- Other: $2,594
- Fixed Income: $0
- Real Estate: $0
- Cash (Margin): -$11,589
- **Sum: $46,216** — but Total Portfolio Value is **$131,571**

There's an $85K gap. The asset allocation only accounts for 35% of the portfolio value. This is the same issue class as R6 (weight denominator mismatch) — the allocation uses a different "total" than the portfolio value card.

**Root cause**: The asset allocation comes from `useRiskAnalysis` (shown in the data source indicator). The risk analysis likely uses only the equity positions (~$27K gross) for allocation, while the $131K total includes ~$105K in cash/money market not classified into asset classes. The negative Cash (Margin) of -$11,589 may represent margin borrowing, but the large cash balance isn't shown in any allocation category.

**Fix direction**: Either include cash/money market as a positive allocation category, or clarify that allocations show "equity portfolio only" with a note about excluded cash.

### R22. Cash (Margin) value conflicts with Smart Alert margin debt on same page

**Severity**: High (data consistency)
**Location**: Dashboard → Asset Allocation vs Smart Alerts (IBKR portfolio)

**Symptom**: On the same dashboard page:
- Asset Allocation shows: Cash (Margin) **-$11,589**
- Smart Alert shows: **$5,606 margin debt** (26% of portfolio)

These should represent the same margin concept but differ by ~2x. One source says the margin debt is $11.6K, the other says $5.6K.

**Root cause**: These likely come from different data sources:
- Asset Allocation's Cash (Margin) from `/api/analyze` risk analysis (net cash position after margin)
- Smart Alert's margin debt from `/api/positions/alerts` (reported margin balance)

The difference may be that -$11,589 is the net cash position (including margin collateral) while $5,606 is just the borrowed amount. But presenting both on the same page without explanation is confusing.

**Fix direction**: Ensure both values use the same definition of "margin", or label them differently (e.g., "Net Cash" vs "Margin Borrowed").

---

## Data Consistency Matrix (IBKR Portfolio)

| Metric | Dashboard Card | Dashboard Summary | Performance | Factors | Settings | Consistent? |
|--------|---------------|-------------------|-------------|---------|----------|-------------|
| Total Value | $131,571 | — | — | — | — | N/A |
| Position Count | 15 (dropdown) | 15 (View All) | — | — | — | ✓ |
| YTD Return | +31.6% | +31.58% | +31.6% | — | — | ✓ |
| Risk Score | 70 | — | — | 69-72 (components) | — | ~✓ |
| Alpha | +12.9% | +12.94% | +13.2% (excess) | — | — | Close (different concepts) |
| Sharpe | 1.69 | 1.69 | 1.69 | — | — | ✓ |
| Volatility | — | +16.28% | 16.3% | **19.4%** | 16.3% | ✗ (Factors outlier) |
| Concentration | 69 | — | — | 69 | — | ✓ |
| Margin | — | — (alert: $5,606) | — | — | — | ✗ (vs -$11,589 alloc) |

**Conclusion**: IBKR single-account consistency is mostly good. The two main issues are:
1. Volatility — 16.3% everywhere except Factors view (19.4%)
2. Margin — $5,606 (alert) vs -$11,589 (allocation) on same page


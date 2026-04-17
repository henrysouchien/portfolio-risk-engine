# Frontend Issues & Polish — 2026-03-10

Captured during live walkthrough. Each issue has enough context for an independent Claude session to pick up and fix.

---

## Issue 1: Classic ↔ Premium visual style toggle has no visible effect

**Severity:** Medium
**Type:** Visual / Wiring gap
**Page:** Portfolio Overview (Settings gear)

**What happens:** Clicking the gear icon → toggling between "Classic" and "Premium" → Save — nothing visually changes on the page.

**Root cause:** The plumbing works end-to-end (SettingsPanel → uiStore → `data-visual-style` attr on `<html>` → CSS rules in `index.css`), but most dashboard components don't apply the premium CSS utility classes (`glass-premium`, `hover-lift-premium`, `hover-glow-premium`, `morph-border`, etc.). The CSS rules exist to differentiate modes, but the HTML elements they target aren't using those classes.

Additionally, the toggle uses a draft + Save pattern (not instant preview), which makes it feel even more broken.

**Key files:**
- `frontend/packages/ui/src/components/portfolio/overview/SettingsPanel.tsx` — toggle UI (lines ~78-105, save ~571-582)
- `frontend/packages/connectors/src/stores/uiStore.ts` — `visualStyle` state + `setVisualStyle()` action + localStorage persistence
- `frontend/packages/ui/src/App.tsx` — `useEffect` that sets `document.documentElement.dataset.visualStyle`
- `frontend/packages/ui/src/index.css` — CSS rules for `[data-visual-style="premium"]` and `[data-visual-style="classic"]`

**Fix approach:**
1. Audit Overview page components and apply premium utility classes where appropriate (cards, stat boxes, charts)
2. Consider making the toggle an instant preview (apply `setVisualStyle` on click, revert on cancel) instead of requiring Save
3. If the feature isn't ready for users, consider hiding the toggle until it's wired up

---

## Issue 2: AI Insights toggle feels broken + opportunity for Claude integration

**Severity:** Medium (UX) / High (feature opportunity)
**Type:** UX + Feature enhancement
**Page:** Portfolio Overview

**What happens:** Clicking "AI Insights" toggle does technically work — it shows/hides the AI Recommendations panel (concentration warnings from factor analysis) and per-metric hover insights. But it **feels** broken because:
1. The panel it controls is far down the page — toggling from the top toolbar has no visible effect in viewport
2. The button highlight state is hard to distinguish (green either way)
3. Per-metric hover insights (blue "AI Analysis" boxes on OverviewMetricCard) may not be triggering

**Current state:** Backend generates real rule-based recommendations using factor analysis (concentration thresholds, correlation filters) and metric insights from position/performance/risk flags. **No LLM integration** — all deterministic.

**Feature opportunity — Claude integration pass:**
The embedded Claude assistant could generate richer, contextual insights:
- **Portfolio narrative**: Have Claude summarize the portfolio state in natural language (e.g., "Your portfolio is heavily tilted toward real estate at 27% vs your 10% target, and margin debt is elevated at 25% of portfolio value")
- **Per-section explanations**: Inject Claude-generated context into each dashboard section (Risk Assessment, Performance, Asset Allocation) explaining what the numbers mean and what to watch
- **Actionable recommendations**: Replace or augment the rule-based recommendations with Claude-powered analysis that considers the full portfolio context together
- **Market context integration**: Combine Market Intelligence events with portfolio exposure to surface relevant impacts

**Key files:**
- `frontend/packages/ui/src/components/portfolio/overview/ViewControlsHeader.tsx` — button (line ~69-77)
- `frontend/packages/ui/src/components/portfolio/PortfolioOverview.tsx` — `showAIInsights` state (line 29)
- `frontend/packages/ui/src/components/portfolio/overview/AIRecommendationsPanel.tsx` — recommendation cards
- `frontend/packages/ui/src/components/portfolio/overview/OverviewMetricCard.tsx` — per-metric hover insights (lines 250-319)
- `frontend/packages/connectors/src/features/positions/hooks/useAIRecommendations.ts` — fetches from `/api/positions/ai-recommendations`
- `mcp_tools/factor_intelligence.py` — `build_ai_recommendations()` backend builder
- `mcp_tools/metric_insights.py` — `build_metric_insights()` per-card insight builder

**Fix approach:**
1. **Quick UX fix**: Make the toggle state more obvious (e.g., different icon/color for on vs off, or show a brief toast "AI Insights hidden/shown")
2. **Integration pass**: Route portfolio snapshot through Claude API to generate natural-language insights, inject into the existing AI Recommendations panel and per-metric insight slots
3. Consider always-visible brief insights (no toggle needed) with a "detailed AI analysis" expandable section

---

## Issue 3: Refresh button gives no visual feedback (feels like nothing happened)

**Severity:** Medium
**Type:** UX feedback gap
**Page:** Portfolio Overview (top-right Refresh button)

**What happens:** Clicking the Refresh button triggers real data calls and updates portfolio values, but the user perceives nothing is happening. There's no toast, no "data refreshed" confirmation, and the loading spinner is a tiny 12px icon animation that's easy to miss.

**Confirmed working:** Chrome network inspection confirms the button fires real requests (`POST /plaid/holdings/refresh`, `POST /api/analyze`, `POST /api/performance`, `POST /api/risk-score`). Values did change ($22,139 → $30,024). The issue is purely UX feedback.

**Why it feels broken:**
- The `RefreshCw` icon spins at `w-3 h-3` (12px) — barely noticeable
- No success toast after data loads
- No timestamp update like "Last refreshed: just now"
- If the value delta is small or zero, the user has no way to know the refresh completed

**Sub-issue: SnapTrade refresh silently returning 500**
- `POST /api/snaptrade/holdings/refresh` returns HTTP 500 on every attempt (4 retries observed via Chrome network tab)
- `Promise.allSettled` in `PortfolioManager.refreshHoldings()` (line ~700) correctly prevents Plaid success from being blocked, but the SnapTrade failure is completely invisible to the user
- No error toast, no partial-failure indicator

**Key files:**
- `frontend/packages/ui/src/components/portfolio/overview/ViewControlsHeader.tsx` — Refresh button (lines 78-87), spinner is `w-3 h-3`
- `frontend/packages/ui/src/components/dashboard/views/modern/PortfolioOverviewContainer.tsx` — `handleRefresh()` (lines 145-156), intent trigger + refetch
- `frontend/packages/connectors/src/managers/PortfolioManager.ts` — `refreshHoldings()` (lines 670-752), `Promise.allSettled` swallows provider errors
- `frontend/packages/connectors/src/providers/SessionServicesProvider.tsx` — `refresh-holdings` intent handler (lines 313-328)

**Fix approach:**
1. Add a success toast after refresh completes (e.g., "Portfolio refreshed" or "Holdings updated")
2. If any provider fails, show a warning toast: "Refreshed from Plaid. SnapTrade unavailable."
3. Consider adding a "Last updated: X min ago" timestamp to the header
4. Make the loading state more visible (larger spinner or full-button loading state)
5. Investigate and fix the SnapTrade 500 error separately

---

## Issue 4: View mode toggle (Compact/Detailed/Pro/Institutional) — mostly cosmetic, no new content

**Severity:** Medium
**Type:** Feature / Design decision
**Page:** Portfolio Overview (top bar — Compact / Detailed / Pro / Institutional buttons)

**What happens:** Switching between the 4 modes changes card padding and font sizes but doesn't surface meaningfully different information. Pro and Institutional modes are supposed to show extra data (correlations, technical signals, market sentiment, future projections) but those fields are empty — so the cards just get bigger with no added value.

**How it works today:**
- `ViewControlsHeader.tsx` renders 4 buttons, sets `viewMode` state
- `OverviewMetricCard.tsx` uses `viewMode` to scale padding (`p-4` → `p-6` → `p-8` → `p-10`), font size (`text-lg` → `text-3xl` → `text-4xl` → `text-5xl`), and conditionally show institutional extras (CORR badges, sentiment, projections)
- The conditional data (`metric.correlations`, `metric.technicalSignals`, `metric.marketSentiment`, `metric.futureProjection`) is empty on real data, so Pro/Institutional look identical to Detailed but bigger

**Key files:**
- `frontend/packages/ui/src/components/portfolio/overview/ViewControlsHeader.tsx` — 4-button toggle UI
- `frontend/packages/ui/src/components/portfolio/overview/OverviewMetricCard.tsx` — viewMode-conditional rendering (padding lines 117-121, font size lines 185-189, institutional extras lines 101-107, 136-140, 159-164, 215-229, 266-276, 278-316)
- `frontend/packages/ui/src/components/portfolio/overview/types.ts` — `ViewMode` type definition

**Decision needed:**
1. **Keep or remove?** Four modes is excessive if only 1-2 have real content. If keeping, reduce to 2 modes (e.g. "Summary" vs "Detailed").
2. **What differentiates them?** Be intentional about what information each mode shows/hides rather than just scaling card sizes. E.g., Summary = key stats only; Detailed = adds sparklines, change descriptions, AI insights.
3. If the institutional/pro data (correlations, signals, projections) is permanently gone, remove those code paths to reduce dead code.

---

## Issue 5: Metric card hover state — cluttered metadata + AI insight is just a Smart Alert rehash

**Severity:** Medium
**Type:** UX / Content quality
**Page:** Portfolio Overview — 6 metric cards (Total Portfolio Value, Daily P&L, Risk Score, Sharpe Ratio, Alpha Generation, Concentration)

**What happens on hover (Detailed view):**

1. **Tiny metadata text** appears in the card header: "Volatility: Low", "Updated 3/10/2026, 11:36:25 PM", "AI: 80%" — crammed into a single row in ~10px text. Not useful information for most users and adds visual clutter to an otherwise clean card.

2. **Black tooltip** pops up titled "{Metric} Intelligence" showing: Current value, Change, Volatility, AI Confidence %. At the bottom it shows `metric.aiInsight` text — but this is literally the same content as the Smart Alert above (e.g., "NVDA is 16.4% of exposure"). It's not a unique insight for that metric, it's a **rehash of the position flag**.

3. **"Critical" badge** appears next to the change % on hover — context-free, doesn't explain why it's critical.

**Root cause (tooltip/aiInsight):**
- `metric.aiInsight` is populated from `metricInsights["totalValue"]?.aiInsight` (in `useOverviewMetrics.ts`)
- Backend `mcp_tools/metric_insights.py` maps position flags → metric cards via `_POSITION_FLAG_MAP`
- The highest-severity flag for a card becomes its `aiInsight` text
- Same flags also feed the Smart Alerts — so the tooltip just repeats what's already visible above

**Root cause (tiny metadata):**
- `OverviewMetricCard.tsx` lines 143-166: conditionally rendered on `isHovered || isFocused` when not compact
- Shows `metric.volatility`, `metric.lastUpdate` timestamp, `metric.aiConfidence`
- Information is either redundant (volatility shown in Risk Score card) or too granular (exact timestamp)

**Key files:**
- `frontend/packages/ui/src/components/portfolio/overview/OverviewMetricCard.tsx` — hover metadata (lines 143-166), tooltip (lines 383-411), Critical badge (lines 209-213)
- `frontend/packages/ui/src/components/portfolio/overview/useOverviewMetrics.ts` — metric data construction (lines 16-153)
- `mcp_tools/metric_insights.py` — backend insight builder (maps flags → cards)

**Fix approach:**
1. **Remove or simplify hover metadata**: The tiny text row adds clutter without value. Either remove it or reduce to just the timestamp.
2. **Make AI insights actually insightful**: Instead of rehashing Smart Alerts, generate per-metric context:
   - **Total Value**: "Down $649 today, driven primarily by NVDA (-2.3%) and STWD (-1.1%)"
   - **Risk Score**: "Score elevated due to 27% real estate overweight vs 10% target"
   - **Sharpe**: "0.74 is below the 1.0 threshold — consider reducing volatility drag from commodity positions"
3. **Claude integration opportunity**: Use the embedded assistant to generate these contextual per-metric summaries from the full portfolio snapshot, rather than mapping individual flags
4. **Critical badge**: Either show always with explanation, or remove — showing on hover without context is confusing

---

## Issue 6: Daily P&L card is redundant with Total Portfolio Value — wasted card slot

**Severity:** Medium
**Type:** Information architecture
**Page:** Portfolio Overview — 6 metric cards (top row)

**What happens:** The Daily P&L card shows `-$649` and `-0.59%`. The Total Portfolio Value card right next to it shows the exact same numbers: `-0.59%` badge and `-$648.9` change value. Two of six card slots are conveying identical information.

**Code evidence:**
- `useOverviewMetrics.ts` line 18-21: Total Portfolio Value uses `summary.dayChangePercent` (badge) + `summary.dayChange` (changeValue)
- `useOverviewMetrics.ts` line 40-44: Daily P&L uses `summary.dayChange` (main value) + `summary.dayChangePercent` (badge)
- Same two data points, just swapped between primary display and badge

**Also:** The "Critical" badge on Total Portfolio Value (Issue 5) is hardcoded `priority: "critical"` (line 28) — not data-driven. Every other card has `priority: "high"` or `"medium"`, also hardcoded.

**Fix approach:**
Replace the Daily P&L card with something more insightful. Candidates:
1. **YTD Return** — `summary.ytdReturn` is already available but not displayed in any card
2. **Max Drawdown** — `summary.maxDrawdown` is available, useful risk context
3. **Beta** — available from performance data, gives market sensitivity at a glance
4. **Income / Yield** — dividend income or portfolio yield if realized data is available
5. Alternatively, reduce to 5 cards (or 4) and use the space for a small sparkline chart or summary row

---

## Design Note A: Market Intelligence Banner is a differentiator — lean into it

**Type:** Positive feedback / Product direction
**Page:** Portfolio Overview — "Market Intelligence" banner (blue, with Bell icon)

**What the user likes:** The Market Intelligence banner surfaces genuinely portfolio-relevant events — earnings dates for held tickers, news sentiment weighted by position size, action flags for >5% holdings. It feels like real, personalized analysis rather than generic market noise.

**What powers it:**
- `mcp_tools/news_events.py` → `build_market_events(user_email)` combines two FMP data sources:
  - **News sentiment**: `get_portfolio_news()` → keyword-based sentiment scoring on news for held tickers, relevance weighted by portfolio weight
  - **Earnings calendar**: `get_portfolio_events_calendar(event_type="earnings", days=14)` → upcoming earnings with EPS estimates for holdings
- Events scored by `weight * 300 + base`, capped at 8, sorted by relevance
- `actionRequired=true` for holdings >5% weight or relevance >60
- Component: `MarketIntelligenceBanner.tsx`, hook: `useMarketIntelligence.ts`, endpoint: `GET /api/positions/market-intelligence`

**Product direction:**
- This is the kind of feature that makes the dashboard unique — portfolio-aware intelligence, not a generic news feed
- Consider expanding: macro events that impact sector exposure, dividend ex-dates, option expiry warnings, earnings surprises (post-report delta vs estimates)
- Could be the primary surface for Claude-generated portfolio narratives (Issue 2's integration opportunity)
- Consider promoting it visually — currently easy to scroll past

---

## Issue 7: Stray "0" rendered on bottom 3 metric cards (React `&&` short-circuit bug)

**Severity:** High (visual bug, easy fix)
**Type:** Bug
**Page:** Portfolio Overview — Sharpe Ratio, Alpha Generation, Concentration cards

**What happens:** Each of the bottom 3 metric cards displays a stray "0" next to the status badge:
- Sharpe Ratio: "Fair **0**"
- Alpha Generation: "Underperforming **0**"
- Concentration: "Well Diversified **0**"

**Root cause:** Classic React gotcha. `OverviewMetricCard.tsx` line 215:
```tsx
{metric.aiConfidence && metric.aiConfidence > 90 && (
  <Badge>High Confidence</Badge>
)}
```
When `metric.aiConfidence` is `0` (number), `{0 && ...}` short-circuits to `{0}`. React renders the number `0` as visible text. The top 3 cards have non-zero `aiConfidence` (from the metric insights API), so they don't show this bug.

**Data source:** In `useOverviewMetrics.ts`:
- Sharpe (line 99): `aiConfidence: metricInsights["sharpeRatio"]?.aiConfidence ?? 0` — returns `0` when no insight
- Alpha (line 122): `aiConfidence: 0` (hardcoded)
- Concentration (line 145): `aiConfidence: 0` (hardcoded)

**Key files:**
- `frontend/packages/ui/src/components/portfolio/overview/OverviewMetricCard.tsx` — line 215, the `&&` expression
- `frontend/packages/ui/src/components/portfolio/overview/useOverviewMetrics.ts` — lines 99, 122, 145

**Fix (one-liner):**
Change line 215 from:
```tsx
{metric.aiConfidence && metric.aiConfidence > 90 && (
```
to:
```tsx
{metric.aiConfidence > 90 && (
```
The `> 90` check already handles the `0` case, so the first truthy guard is redundant and causes the bug.

---

## Issue 8: Bottom 3 metric cards have hardcoded placeholder metadata + "Updated0" rendering bug

**Severity:** Medium (visual bug + data quality)
**Type:** Bug + Data gap
**Page:** Portfolio Overview — Sharpe Ratio, Alpha Generation, Concentration cards (hover state)

**What happens:**
1. **"Updated0"** — Sharpe card hover shows "Volatility: Stable · Updated0". The "0" is the `aiConfidence` stray zero (Issue 7) bleeding into the metadata row. The empty `lastUpdate` string concatenates with the rendered `0`.
2. **Fake volatility labels** — Bottom 3 cards show hardcoded strings ("Stable", "Stable", "Very Low") that don't reflect actual data. Top 3 cards compute real labels from `summary.volatilityAnnual` thresholds. This inconsistency is confusing.

**Code evidence in `useOverviewMetrics.ts`:**
- Top 3 cards (Total Value, Daily P&L, Risk Score): `volatility` computed from `summary.volatilityAnnual` (>20→"High", >10→"Medium", else "Low"), `lastUpdate` from `summary.lastUpdated`
- Sharpe (line 95-96): `volatility: "Stable"`, `lastUpdate: ""`
- Alpha (line 118-119): `volatility: "Stable"`, `lastUpdate: ""`
- Concentration (line 141-142): `volatility: "Very Low"`, `lastUpdate: ""`

These are placeholder strings left from initial scaffolding — not connected to any real data source.

**Key files:**
- `frontend/packages/ui/src/components/portfolio/overview/useOverviewMetrics.ts` — lines 95-96, 118-119, 141-142
- `frontend/packages/ui/src/components/portfolio/overview/OverviewMetricCard.tsx` — hover metadata rendering (lines 143-166)

**Fix approach:**
1. Fix the stray "0" (Issue 7 fix resolves the "Updated0" concatenation)
2. Either compute meaningful volatility labels for bottom 3 cards (e.g., Sharpe stability over time, alpha trend direction, concentration change rate) or remove the volatility metadata from cards where it doesn't apply
3. If `lastUpdate` is empty, don't render the "Updated" text at all — guard with `{metric.lastUpdate && <span>Updated {metric.lastUpdate}</span>}`

---

## Issue 9: Performance Trend chart lacks basic chart fundamentals

**Severity:** Medium
**Type:** UX / Polish
**Page:** Portfolio Overview — "Performance Trend" sparkline card

**What the user sees:** A simple line chart with a percentage on the right — clean and readable at a glance. But:
1. **No time axis** — no dates, no month labels. User has no idea if this is 1 week, 1 month, or 1 year of data.
2. **No value axis** — no percentage scale markers. Can't tell the range (is it 0-5% or 0-50%?).
3. **No period label** — header just says "Performance Trend" with no "1M", "YTD", "1Y" indicator.
4. **Green outline artifact** — the emerald gradient fill (`emerald-400` → `emerald-600`) combined with the `emerald-500` stroke creates a visible green border/outline around portions of the filled area that looks unintentional and unprofessional.

**What the user likes:** The simplicity — a clear number on the right, not overloaded. Keep this quality.

**Technical details:**
- Chart is a **custom SVG sparkline** (`SparklineChart.tsx`), not a charting library (no Recharts/D3)
- `PortfolioOverview.tsx` lines 88-108 render it inside a `glassTinted` Card
- Data comes from `usePerformance()` → `perfData.performanceTimeSeries`
- `SparklineChart` uses `preserveAspectRatio="none"`, no gridlines, no axis rendering
- Color scheme defaults to "emerald" — stroke `stroke-emerald-500`, gradient `stop-emerald-400` → `stop-emerald-600`

**Key files:**
- `frontend/packages/ui/src/components/portfolio/PortfolioOverview.tsx` — chart container (lines 88-108)
- `frontend/packages/ui/src/components/portfolio/overview/SparklineChart.tsx` — custom SVG sparkline (lines 5-48), color scheme, gradient fill
- `frontend/packages/connectors/src/features/portfolio/hooks/usePerformance.ts` — data source

**Fix approach (keep the simplicity):**
1. Add a small period label in the header: "Performance Trend · 1Y" or a period selector (1M/3M/YTD/1Y)
2. Add minimal X-axis labels — just first and last date, or month abbreviations (Jan, Apr, Jul, Oct)
3. Add 2-3 Y-axis gridlines with percentage labels (e.g., 0%, 10%, 20%) — light, unobtrusive
4. Fix the green outline: either remove the gradient fill entirely (clean line only) or set `stroke="none"` when fill is active to avoid the double-green border effect
5. Consider switching to Recharts `<AreaChart>` for tooltips on hover (show date + value at cursor) while keeping the compact form factor

---

## Issue 10: AI Recommendations — confidence/timeframe are fake, priority vs riskLevel signals conflict

**Severity:** Medium
**Type:** Data quality + UX confusion
**Page:** Portfolio Overview — AI Recommendations panel

**Two sub-issues:**

### 10a: Confidence and Timeframe are not real model outputs

The confidence % and timeframe displayed on each recommendation card are not meaningful:

- **Confidence (concentration recs):** `min(95, int(pct_display * 2 + 30))` — linear mapping of concentration %. 18.6% exposure → 67% confidence. Not a model confidence score.
- **Confidence (hedge recs):** `min(95, int(corr * 100))` — raw correlation → "confidence". 55% correlation → 55% confidence.
- **Timeframe:** Hardcoded `"1-2 weeks"` for all concentration recs, `"Ongoing"` for all hedge recs. No computation.

These numbers look authoritative but are arbitrary formulas. Either make them meaningful or remove them.

### 10b: "HIGH" priority badge vs "low risk" dot sends contradictory signals

Each card displays two severity indicators:
- **Left:** Priority badge (HIGH / MEDIUM) — how urgent the issue is, based on concentration %
- **Right:** Risk level dot + label ("low risk" / "medium risk") — intended as risk of taking the recommended action

The disconnect: "High Financial - Mortgages Concentration" shows **HIGH priority** (amber badge) + **low risk** (green dot). A user reads this as "high risk but low risk?" — the two signals appear to conflict.

**Root cause:** `riskLevel` is hardcoded `"low"` for ALL concentration recs (line 313) because the *action* of trimming is low-risk. But this semantic distinction (priority = urgency, riskLevel = execution risk) is never explained to the user.

**Key files:**
- `mcp_tools/factor_intelligence.py` — `build_ai_recommendations()` (lines 240-346): confidence formula (306, 335), timeframe (307, 336), riskLevel (313, 341)
- `frontend/packages/ui/src/components/portfolio/overview/AIRecommendationsPanel.tsx` — card rendering with both badges (lines 40-55)

**Fix approach:**
1. **Confidence**: Either derive from actual model output (e.g., backtest hit rate, factor stability score) or relabel as "Severity" / "Impact Score" to honestly reflect what the number means
2. **Timeframe**: Either compute dynamically (e.g., based on position liquidity, rebalance frequency) or remove if it's always the same
3. **Priority vs riskLevel**: Pick one signal or clearly differentiate them:
   - Option A: Remove `riskLevel` — priority alone is sufficient for concentration recs
   - Option B: Rename to make the distinction clear: "Urgency: HIGH" + "Action Risk: Low"
   - Option C: Merge into a single composite score

---

## Issue 11: Market Intelligence relevance scoring + action items are placeholder logic

**Severity:** Medium (enhancement)
**Type:** Data quality / Feature depth
**Page:** Portfolio Overview — Market Intelligence banner

**Current state — the skeleton is right, but scoring is fake:**

The UI surfaces portfolio-relevant news and earnings events with "% relevant" scores and an "Action Items" count. The concept is great. But the underlying logic is just position weight math, not real relevance analysis.

**Relevance % — position weight only:**
- News formula: `relevance = min(95, max(10, int(weight * 300 + 20)))` (line ~306 in `news_events.py`)
- Earnings formula: `relevance = min(95, max(20, int(weight * 300 + 30)))` (line ~336)
- A 20% position = 80% relevant, a 1% position = 23% — regardless of what the news says
- No analysis of news content, magnitude, or portfolio impact

**Action Items — two simple thresholds:**
- News: `relevance > 60` (effectively ~13%+ position weight)
- Earnings: `weight > 0.05` (5%+ position)
- Currently showing "0 Action Items" because no events cross thresholds for current holdings

**Sentiment — keyword counting:**
- 11 negative keywords ("downgrade", "crash", "layoff"...) vs 11 positive ("upgrade", "surge", "rally"...)
- Counts occurrences in title+snippet, majority wins
- No NLP, no context understanding

**What real relevance could look like:**
1. **Content relevance**: Does the news actually affect the company's fundamentals? (e.g., "AAPL launches new product" vs "AAPL employee wins local award")
2. **Portfolio impact scoring**: Earnings surprise magnitude × position weight × sector beta
3. **Cross-holding effects**: News about a sector peer should propagate relevance to your holdings in that sector
4. **Action specificity**: Instead of just flagging "actionable", suggest what action — "Consider trimming ahead of earnings" or "Positive catalyst, review position size"
5. **Claude integration**: Route events + portfolio context through Claude to generate real relevance assessments and action recommendations

**Key files:**
- `mcp_tools/news_events.py` — `build_market_events()` (scoring formulas), `_load_portfolio_weights()`, `_NEGATIVE_KEYWORDS`/`_POSITIVE_KEYWORDS`
- `frontend/packages/ui/src/components/portfolio/overview/MarketIntelligenceBanner.tsx` — display component
- `routes/positions.py` — API route (~line 429)

---

## Issue 12: Asset Allocation targets — useful feature, needs agent-guided workflow

**Severity:** Low (enhancement / product direction)
**Type:** Workflow / Feature opportunity
**Page:** Portfolio Overview — Asset Allocation card ("Set Targets" button)

**Current state:** The Asset Allocation card displays targets (e.g., Equity 60%, Fixed Income 25%, Real Estate 10%, Cash 5%) alongside actual allocations, with overweight/underweight drift indicators. Targets are persisted in the DB via `set_target_allocation` MCP tool and can be edited via a "Set Targets" inline editor in the UI.

**What works well:**
- The drift visualization (overweight/underweight labels + colored bars) is clear and useful
- The "Rebalance" button connects to `preview_rebalance_trades` to produce actionable trade legs
- Targets are persisted per-user per-portfolio in the DB

**What's missing — guided target-setting workflow:**
The current UX is "type percentages into boxes and save." There's no guidance on *what* the targets should be. This is a prime opportunity for the AI assistant to help:

1. **Agent-guided target setting**: "Help me set my asset allocation targets" → Claude asks about risk tolerance, investment horizon, income needs, tax situation → suggests a target allocation with rationale
2. **Template-based starting points**: Offer common allocation templates (e.g., "Conservative: 30/50/10/10", "Growth: 70/20/5/5", "Income-focused: 40/40/15/5") as starting points the user can customize
3. **Context-aware suggestions**: Agent can look at current holdings, realized performance, risk score, and suggest adjustments — "Your real estate is 27% vs 10% target, and your risk score is 94.5. Consider reducing to 15% to lower concentration risk while maintaining income exposure."
4. **Periodic review prompts**: "Your targets were last set 6 months ago — want to review given current market conditions?"

**Key files:**
- `mcp_tools/allocation.py` — `set_target_allocation()`, `get_target_allocation()` MCP tools (DB-backed)
- `frontend/packages/ui/src/components/dashboard/views/modern/AssetAllocationContainer.tsx` — "Set Targets" editor UI, `useTargetAllocation()` hook, `useSetTargetAllocation()` mutation
- `frontend/packages/ui/src/components/portfolio/AssetAllocation.tsx` — display component with drift bars

**Not a bug** — this is about making an existing feature more accessible and intelligent. The plumbing works; the workflow needs elevation.

---

## Issue 13: Asset Allocation period selector crashes card — period buttons disappear

**Severity:** High (bug, 100% reproducible)
**Type:** Bug — broken state recovery
**Page:** Portfolio Overview — Asset Allocation card period tabs (1M, 3M, 6M, 1Y, YTD)

**What happens:**
1. Asset Allocation card loads normally with "1M" selected (default)
2. Click any other period (e.g., "3M" or "6M")
3. Card immediately collapses to "No asset allocation data available for this portfolio." empty state
4. **The period selector tabs disappear** — user is stranded with no way to switch back
5. "Refresh Analysis" button works (fires `POST /api/analyze`, returns 200), card reloads with data — but resets to 1M

**100% reproducible** — confirmed in Chrome. No JS errors in console. No API call fires when clicking the period tab.

**Root cause:**
1. `setPerformancePeriod('3M')` updates state → `useRiskAnalysis({ performancePeriod: '3M' })` gets a new query key
2. No cached data exists for the new key → `resolved.data` is `undefined` → `hasData` = false
3. `AssetAllocationContainer.tsx` lines 347-357: the `!hasData` early return renders the "No Data" message
4. **The period selector buttons (lines 366-381) are ONLY in the success render path** — they're inside the final `return` block that only executes when data exists
5. So the buttons vanish, and the user can't switch back

**Additionally:** The period change doesn't even trigger an API call with the new period — it just looks for cached data under the new query key, finds nothing, and gives up.

**Key files:**
- `frontend/packages/ui/src/components/dashboard/views/modern/AssetAllocationContainer.tsx`:
  - Period state: line 104 (`useState('1M')`)
  - Hook: line 118 (`useRiskAnalysis({ performancePeriod })`)
  - No-data early return: lines 347-357 (renders without period buttons)
  - Period buttons: lines 366-381 (only in success path)
- `frontend/packages/connectors/src/features/analysis/hooks/useRiskAnalysis.ts` — `useDataSource('risk-analysis', ...)` with period in query key

**Sub-issue: Period selector causes visual imbalance with Risk Assessment card**

The Asset Allocation and Risk Assessment cards sit in a `grid-cols-2` layout (`ModernDashboardApp.tsx` lines 466-472). The period selector buttons are rendered INSIDE `AssetAllocationContainer` (lines 366-381, with `mb-3`) above the card content, adding ~40px of vertical offset. `RiskMetricsContainer` has no equivalent element, so its card body starts higher — the two cards look visually unbalanced.

```
Grid (xl:grid-cols-2 gap-8)
├── AssetAllocationContainer
│   ├── Period Buttons (1M 3M 6M 1Y YTD) ← extra ~40px
│   └── <AssetAllocation /> card
└── RiskMetricsContainer
    └── <RiskMetrics /> card  ← starts higher, looks misaligned
```

**Fix approach:**
1. **Recommended: Remove the period selector entirely** — asset allocation is a point-in-time snapshot, not period-dependent. The selector doesn't fetch period-specific data, crashes the card (see above), AND causes layout imbalance. Three reasons to remove.
2. **If keeping**: Move it inside the `<Card>` component (as a header row within the card border) so both cards share the same outer alignment. Also fix the crash (move outside early returns).
3. Ensure the loading/error/empty render paths include the period buttons so the user is never stranded

---

## Issue 14: Asset Allocation card — Performance tab, Set Targets, and Rebalance button problems

**Severity:** High (UX safety) / Medium (feature gaps)
**Type:** UX / Feature
**Page:** Portfolio Overview — Asset Allocation card action buttons

### 14a: "Performance" tab shows tickers, not performance

Clicking "Performance" switches the view to show ticker badges under each asset class (e.g., which tickers are in "Equity"). No actual return data, no charts, no metrics — just a flat list of holdings. The label "Performance" is misleading; this is really a "Holdings" view.

**Code:** `AssetAllocation.tsx` lines 329-337 — `viewMode === 'performance'` just renders `allocation.holdings.map()` as badges.

### 14b: "Set Targets" is too casual for a dashboard placement

Inline target editing on the main overview page encourages uninformed changes. Target allocation is a considered decision that should involve understanding risk tolerance, time horizon, income needs. Having it as a quick-edit form next to the allocation bars trivializes the decision.

(Already captured in more detail in Issue 12 with agent-guided workflow recommendation.)

### 14c: "Rebalance" button — no confirmation, scary UX, broke the card

**What happened:**
1. User clicked "Rebalance" on the Asset Allocation card
2. No confirmation dialog appeared
3. Card transitioned to "No Data" / empty state (likely the rebalance preview pane failed to render)
4. User was left wondering if real trades were executed

**Reality:** The backend `preview_rebalance_trades()` only computes a trade plan — it does NOT execute orders. `preview=False` by default, which counter-intuitively means "don't generate IBKR preview IDs" not "execute live." The result is a list of computed trade legs with status "computed."

**But the UX is dangerous:**
- No confirmation dialog: "This will generate a rebalance plan for your portfolio. Continue?"
- No preview pane appeared (may have rendered off-screen or errored silently)
- The button says "Rebalance" not "Preview Rebalance" or "Generate Plan"
- After clicking, the card broke to "No Data" state — user is stranded
- Zero indication that no real trades happened

**Key files:**
- `frontend/packages/ui/src/components/portfolio/AssetAllocation.tsx` — button (lines 206-217), Performance view (lines 329-337)
- `frontend/packages/ui/src/components/dashboard/views/modern/AssetAllocationContainer.tsx` — `handleGenerateRebalance()` (lines 296-315), `showRebalance` state, `rebalanceMutation`
- `mcp_tools/rebalance.py` — `preview_rebalance_trades()` (line 70+) — preview-only, no order execution

**Fix approach:**
1. **Rename button**: "Rebalance" → "Preview Rebalance" or "Generate Plan"
2. **Add confirmation dialog** before calling the mutation
3. **Fix the broken state**: The card shouldn't collapse to "No Data" after generating a rebalance — investigate why `showRebalance=true` isn't rendering the preview pane
4. **Performance tab**: Either wire up actual per-asset-class return data, or rename to "Holdings" to match what it shows
5. **Consider removing Set Targets + Rebalance from the Overview page entirely** — these are workflow actions that belong in a dedicated "Rebalance" or "Planning" view, not the at-a-glance dashboard

### 14d: Rebalance preview exists but execution is not wired up

The rebalance preview pane does render and shows computed trade legs. But:
- **No "Execute" / "Place Orders" button** in the preview UI — it's display-only
- **No account selector** — backend supports `account_id` param, but frontend doesn't expose it
- **Partial plumbing exists**: backend can generate IBKR `preview_id`s (when `preview=True`), and separate `execute_trade()`/`execute_basket_trade()` MCP tools can execute by preview ID — but the rebalance UI doesn't call them
- **The rebalance tool is useful** — user likes the concept. It just needs:
  1. Account picker (which brokerage account to rebalance)
  2. An "Execute" button that sends the preview IDs to `execute_basket_trade()`
  3. Confirmation dialog before execution with order summary
  4. A better home — probably a dedicated "Rebalance" page or modal, not embedded in the Overview Asset Allocation card

---

## Issue 15: Risk Assessment metrics are methodologically inconsistent — VaR vs Max Drawdown disconnect

**Severity:** High (data quality / methodology)
**Type:** Backend methodology + Frontend display
**Page:** Portfolio Overview — Risk Assessment card (right column, RiskMetricsContainer)

**What the user sees:**
- **VaR**: -$1,418 (LOW, 0.83% of portfolio)
- **Beta**: 1.02 (MEDIUM)
- **Volatility**: 8.0% (LOW)
- **Max Drawdown**: -55.9% (HIGH, 100% on risk bar)

Low VaR + low volatility + moderate beta but 55.9% max drawdown is incoherent. A portfolio with 8% annualized vol shouldn't have a 55.9% drawdown.

**Root cause — metrics are measuring different things:**

1. **VaR** (`RiskMetricsContainer.tsx` line 132): Parametric VaR computed from **portfolio-level annualized volatility**:
   ```
   totalValue * (annualVolatility / 100) * (1.645 / √252)
   ```
   This is diversified, portfolio-level, forward-looking.

2. **Max Drawdown** (`RiskMetricsContainer.tsx` lines 128-131): Takes `riskData.historical_analysis.worst_per_proxy` — the worst historical drawdown of **each individual ticker** — then picks `Math.min(...)` across all tickers. So -55.9% is likely the worst single holding's historical peak-to-trough, NOT a portfolio-level drawdown.

3. **Volatility** (line 125): From `risk_metrics.annual_volatility` — portfolio-level, diversification-adjusted.

4. **Beta** (line 126): From `portfolio_factor_betas.market` — portfolio-level.

So VaR, volatility, and beta are all **portfolio-level** (diversified), but max drawdown is **worst single-ticker** (undiversified). That's apples vs oranges on the same card.

**Key files:**
- `frontend/packages/ui/src/components/dashboard/views/modern/RiskMetricsContainer.tsx` — transformation logic (lines 121-176)
- `portfolio_risk_engine/portfolio_risk.py` — per-ticker drawdown computation (lines 1046-1049)
- `portfolio_risk_engine/portfolio_risk.py` — `build_portfolio_view()` populates `historical_analysis.worst_per_proxy`
- `services/factor_intelligence_service.py` — alternative VaR computation from monthly percentiles (lines 1310-1312)

**Fix approach:**
1. **Compute portfolio-level max drawdown**: Use the weighted portfolio return series (not individual ticker series) to compute a single portfolio-level drawdown. This would be consistent with VaR and volatility.
2. **If keeping per-ticker worst drawdown**: Relabel it clearly — e.g., "Worst Single-Position Drawdown" and show which ticker it came from.
3. **Consider showing both**: "Portfolio Max Drawdown: -12%" (portfolio-level) and separately "Worst Position Drawdown: -55.9% (TICKER)" — so the user understands both the diversified risk and the tail risk from individual holdings.
4. **Investigate the specific ticker**: -55.9% is extreme — could be a pricing data issue, a delisted ticker, or a legitimate crash. Worth checking which holding drives this.

---

## Issue 16: Risk Assessment metrics have no hover explanations — user can't understand what VaR means

**Severity:** Medium
**Type:** UX / Accessibility
**Page:** Portfolio Overview — Risk Assessment card (VaR, Beta, Volatility, Max Drawdown)

**What happens:** The four risk metrics display values (e.g., VaR: -$1,418, Beta: 1.02) with tiny descriptions ("95% confidence, 1-day") but no explanation of what they mean or how they affect the user's portfolio. A user who doesn't know what VaR is gets zero help.

**What's missing per metric:**
- **VaR**: "This means on 95% of days, your portfolio won't lose more than $1,418. On 1 in 20 trading days, losses could exceed this amount."
- **Beta**: "Your portfolio moves roughly in line with the market. A beta of 1.02 means a 1% market drop → ~1.02% portfolio drop."
- **Volatility**: "8% annualized volatility is low — your portfolio's value typically fluctuates within ±8% per year."
- **Max Drawdown**: "The worst historical peak-to-trough decline across your holdings was -55.9%."

**Existing infrastructure (ready to use):**
- `Tooltip` / `TooltipTrigger` / `TooltipContent` components already exist (`frontend/packages/ui/components/ui/tooltip.tsx`)
- Pattern already used in `RiskAnalysisTab.tsx` (lines 31-44): Info icon → hover → explanation text
- `OverviewMetricCard.tsx` has a similar hover insight pattern (lines 250-318)

**Current state in `RiskMetrics.tsx`:**
- Card-level hover gives a subtle lift animation + progress bar label
- No `<Tooltip>` or `<Info>` icon on any of the 4 metrics
- No personalized insight (e.g., "Your VaR is low relative to your portfolio size" or "Your beta suggests you're close to market exposure")

**Key files:**
- `frontend/packages/ui/src/components/portfolio/RiskMetrics.tsx` — metric cards (no tooltips currently)
- `frontend/packages/ui/src/components/dashboard/views/modern/RiskMetricsContainer.tsx` — data transformation (lines 121-199), status thresholds (lines 54-64)
- `frontend/packages/ui/components/ui/tooltip.tsx` — reusable Tooltip components

**Fix approach:**
1. Add an `<Info>` icon next to each metric label with a `<Tooltip>` containing:
   - **Plain-language explanation** of the metric (1-2 sentences)
   - **Personalized context**: "Your VaR of $1,418 is X% of portfolio" (already partially computed)
   - **What to do**: "Consider reducing if this exceeds your daily risk tolerance"
2. Keep explanations concise — this is a tooltip, not a textbook
3. **Claude integration opportunity**: Generate dynamic, portfolio-aware explanations that tie multiple metrics together (e.g., "Your low VaR and low volatility are consistent, but the -55.9% max drawdown suggests tail risk from concentrated positions — see Asset Allocation for details")

---

## Issue 17: VaR calculation audit — methodology is sound, but frontend/backend compute different horizons

**Severity:** Medium (methodology)
**Type:** Backend correctness + Frontend/Backend mismatch
**Page:** Risk Assessment card — VaR metric

**Audit summary: VaR calculation is fundamentally correct**

The parametric VaR implementation properly:
- Uses full covariance matrix (`w^T Σ w`) to capture diversification/correlations
- Applies z-score of 1.645 for 95% confidence (correct one-tailed critical value)
- Annualizes monthly volatility via `× √12` (standard)
- Uses 10-year lookback (120 monthly observations — adequate)
- Validates inputs (finite leverage, non-zero volatility)

**Issue: Frontend and backend compute VaR on different time horizons**

| | Backend (`portfolio_analysis.py`) | Frontend (`RiskMetricsContainer.tsx`) |
|---|---|---|
| Formula | `σ_annual × 1.65` | `totalValue × (σ_annual/100) × (1.645/√252)` |
| Horizon | **Annual** (1-year VaR) | **Daily** (1-day VaR, scaled down by √252) |
| Label | "VaR (95%, 1Y)" | "95% confidence, 1-day" |
| Used for | Leverage capacity constraints | Dashboard display |

The frontend divides annual volatility by √252 to derive a 1-day VaR, then labels it "1-day". The backend uses annual VaR for leverage capacity. Both are valid — but they're different numbers answering different questions, and neither communicates this clearly.

**Known model limitations (not bugs, but worth documenting):**
1. **Normal distribution assumption** — parametric VaR underestimates tail risk. 2008/COVID losses were 2-4× beyond 1.65σ
2. **No fat-tail adjustment** — no Cornish-Fisher expansion or Student-t distribution
3. **Static lookback** — 10-year fixed window doesn't adapt to current volatility regime (GARCH would)
4. **No concentration adjustment** — VaR doesn't penalize concentrated portfolios beyond what the covariance matrix captures
5. **Arithmetic returns** — uses `pct_change()` (arithmetic) rather than log returns. Difference is minor for monthly data but slightly underestimates left-tail risk

**Key files:**
- `core/portfolio_analysis.py` — backend VaR (lines 349-362), annual horizon, used for leverage capacity
- `portfolio_risk_engine/portfolio_risk.py` — `compute_portfolio_volatility()` (lines 216-226), `compute_covariance_matrix()` (lines 192-198)
- `portfolio_risk_engine/factor_utils.py` — `calc_monthly_returns()` (lines 53-64)
- `frontend/packages/ui/src/components/dashboard/views/modern/RiskMetricsContainer.tsx` — frontend VaR (line 132), daily horizon

**Fix approach:**
1. **Pick one source of truth**: Either compute VaR on the backend and pass it through the API (preferred — keeps math server-side), or keep the frontend computation but ensure it matches the backend
2. **Be explicit about horizon**: If showing daily VaR, label it clearly: "1-Day VaR (95%): -$1,418 — on 19 out of 20 trading days, your loss won't exceed this"
3. **Consider adding stress VaR**: Use the existing Monte Carlo engine (`portfolio_risk_engine/monte_carlo.py`) to compute a stress-adjusted VaR that captures fat tails, and show it alongside parametric VaR
4. **Document model limitations** in the tooltip (Issue 16) — users should know VaR is a model, not a guarantee

---

## Issue 18: Risk Assessment summary card — fake "Risk Efficiency" metric + wasted space

**Severity:** High (misleading data)
**Type:** Methodology / Feature opportunity
**Page:** Portfolio Overview — Risk Assessment card, amber "Portfolio Risk Analysis" summary box at bottom

**What the user sees:**
- "Systematic variance is 69.9% and idiosyncratic variance is 30.1%."
- "60% RISK EFFICIENCY"
- "Medium OVERALL RATING"

**Problem 1: "Risk Efficiency" is a made-up metric with no financial basis**

Formula (`RiskMetricsContainer.tsx` lines 136-138):
```
Risk Efficiency = 100 - |factor_variance% - idiosyncratic_variance%|
```
This measures how close to a 50/50 split between systematic and idiosyncratic risk you are. A 50/50 split = 100% "efficient." This is not a real concept in finance. In fact, modern portfolio theory says the opposite — a well-diversified portfolio should have mostly systematic risk (high factor %) and minimal idiosyncratic risk. By this formula, a perfectly diversified portfolio (90% factor, 10% idio) would score only 20% "efficient," while a poorly diversified one (50/50) would score 100%.

**Problem 2: "Overall Rating" inherits the fake metric**

Thresholds (`RiskMetricsContainer.tsx` line 185):
- ≥75% → "Low"
- ≥50% → "Medium"
- <50% → "High"

Since it's based on the meaningless efficiency number, the rating is also meaningless.

**Problem 3: The variance decomposition IS useful but underutilized**

The systematic/idiosyncratic split comes from a proper computation (`compute_portfolio_variance_breakdown()` in `portfolio_risk.py` lines 316-365). This is genuine risk attribution — knowing that 70% of your risk comes from market factors vs 30% from stock-specific risk is valuable. It's just being presented through a nonsensical "efficiency" lens.

**What this space could be instead — a real risk assessment:**

This summary card sits in a prominent position. Instead of fake metrics, use it for:

1. **Plain-language risk narrative**: "Your portfolio risk is dominated by market exposure (70% systematic). Your main risk drivers are: market beta (1.02), real estate concentration (27%), and margin leverage (1.5x). Idiosyncratic risk is moderate at 30%, mostly from NVDA (16% position)."
2. **Actionable risk summary**: Pull the top 2-3 risk flags from the existing `risk_score_flags.py` system and present them as bullet points
3. **Risk attribution breakdown**: Show the factor breakdown (market, size, value, momentum) as a small bar chart instead of just the aggregate split
4. **Claude-generated assessment**: Route the full risk analysis through Claude to produce a contextual summary paragraph

**Key files:**
- `frontend/packages/ui/src/components/dashboard/views/modern/RiskMetricsContainer.tsx` — lines 136-138 (efficiency formula), line 185 (rating threshold)
- `frontend/packages/ui/src/components/portfolio/RiskMetrics.tsx` — lines 364-396 (summary card rendering)
- `portfolio_risk_engine/portfolio_risk.py` — lines 316-365 (`compute_portfolio_variance_breakdown()`, real variance decomposition)
- `core/risk_score_flags.py` — existing risk flag system that could feed the summary

**Fix approach:**
1. **Remove "Risk Efficiency" and "Overall Rating"** — they are misleading
2. **Keep the systematic/idiosyncratic split** — it's real and useful
3. **Replace the summary with a risk narrative** using existing flag/analysis infrastructure
4. **Long-term**: Use Claude to generate a dynamic, portfolio-aware risk assessment paragraph

---

## Issue 19: Alpha Generation card — number shown without context, not actionable

**Severity:** Medium
**Type:** UX / Missing context
**Page:** Portfolio Overview — top 6 metric cards (card 5 of 6)

**What the user sees:** A card labeled "Alpha Generation" showing "-1.91" with subtext "Underperforming" and description "excess return vs benchmark". No indication of what benchmark, what time period, or what alpha means. The number alone is not actionable or interpretable for most users.

**What the number actually is:** Jensen's alpha from an OLS regression of portfolio monthly excess returns vs benchmark (SPY) excess returns over the full performance lookback period. Computed in `performance_metrics_engine.py` lines 126-138:
```python
X = pd.DataFrame({"const": ..., "benchmark_excess": benchmark_excess})
model = sm.OLS(portfolio_excess, X).fit()
alpha_monthly = model.params.iloc[0]
alpha_annual = alpha_monthly * 12.0
```
The value -1.91 means the portfolio underperforms SPY by 1.91% annualized after adjusting for market beta exposure. It's already multiplied by 100 in the backend (`round(alpha_annual * 100, 2)`).

**Data flow:**
1. Backend: `compute_performance_metrics()` → `benchmark_analysis.alpha_annual` (already in %)
2. Adapter: `PortfolioSummaryAdapter.ts` line 368 → `derivedAlpha = this.toNumber(perfRiskMetrics.alpha, 0)`
3. Hook: `useOverviewMetrics.ts` line 110 → `formatPercent(summary.alphaAnnual, { decimals: 1, sign: true })`
4. Card: renders with label "Alpha Generation", description "excess return vs benchmark"

**Problems:**
1. **No benchmark label** — doesn't say "vs SPY" or "vs S&P 500". User doesn't know what they're being compared against.
2. **No time period** — doesn't indicate the lookback window (e.g., "over 18 months"). Alpha over 3 months vs 3 years means very different things.
3. **No explanation of alpha** — "excess return vs benchmark" is vague. Alpha is risk-adjusted excess return (after removing beta exposure), not raw outperformance. The description undersells the metric.
4. **Not actionable** — knowing alpha is -1.91% doesn't tell the user what to do. Is this bad? How does it compare to typical alpha? Should they change strategy?
5. **Questionable top-6 card slot** — alpha is a sophisticated CAPM metric. For many users, a simpler metric (e.g., portfolio return vs benchmark return over trailing 1Y) would be more intuitive in a prime dashboard position.

**Key files:**
- `frontend/packages/ui/src/components/portfolio/overview/useOverviewMetrics.ts` — line 110 (alpha card data)
- `frontend/packages/ui/src/components/portfolio/overview/OverviewMetricCard.tsx` — card rendering
- `frontend/packages/connectors/src/adapters/PortfolioSummaryAdapter.ts` — line 368 (`derivedAlpha`)
- `portfolio_risk_engine/performance_metrics_engine.py` — lines 112-160 (CAPM regression producing alpha)

**Fix approach:**
1. **Add benchmark context** — show "vs SPY" or the actual benchmark ticker below the number
2. **Add time period** — show "18-month" or whatever the lookback is
3. **Add tooltip/hover explanation** — "Jensen's alpha: your risk-adjusted annual return above/below the benchmark after accounting for market exposure"
4. **Consider replacing** — if the target audience isn't quant-savvy, swap for a simpler relative metric like "Portfolio vs Benchmark: -1.91% trailing 1Y" or use the card for something more actionable (e.g., top risk flag, rebalance drift %)

---

## Design Note C: Advanced Risk Analysis card is strong — promote it and add stress test context

**Type:** Positive feedback + Enhancement suggestions
**Page:** Portfolio Overview — "Advanced Risk Analysis" card (Shield icon, RiskAnalysis.tsx)

**What the user likes:**
- **Risk Score summary** — 4 component scores (Concentration, Volatility, Factor, Sector) with clear color-coded levels. Feels like a genuine high-level assessment.
- **Stress Tests tab** — instant, portfolio-relevant factor impact information. Clean, scannable.
- **Overall look** — clean card design, good information density without clutter.

**Suggestion 1: Promote this card higher on the page**

Currently positioned 3rd in the layout order. The risk score is a high-level summary metric — arguably more important at a glance than asset allocation.

Current layout in `ModernDashboardApp.tsx` 'score' view (lines 342-372):
1. PortfolioOverviewContainer (metric cards, performance trend)
2. AssetAllocationContainer + RiskMetricsContainer (side-by-side grid)
3. **RiskAnalysisModernContainer** ← user thinks this should be higher
4. PerformanceViewContainer

Consider: Move into the 2-column grid alongside Asset Allocation, or immediately after the metric cards row. The risk score naturally complements the 6 overview metrics.

**Suggestion 2: Add context to stress test scenarios**

The backend defines 8 detailed scenarios (`portfolio_risk_engine/stress_testing.py` lines 12-66) with descriptions, severity, and explicit factor shocks — but only the name and loss % reach the frontend:

| Frontend Label | Backend Definition | What User Sees | What's Missing |
|---|---|---|---|
| "Market Stress" | `market_crash`: -20% broad equity decline (extreme) | "-12.3% loss" | What % decline? What historical analog? |
| "Interest Rate Risk" | `interest_rate_shock`: 300bp parallel shift (high) | "-4.1% loss" | How many bps? What does that look like? |
| "Correlation Breakdown" | All correlations → 1, -25% market (extreme) | "-18.7% loss" | What does this mean practically? |

The backend `description` fields (e.g., "Broad equity decline of 20%", "VIX doubles — broad equity selloff") exist but aren't passed to the frontend.

**Fix approach:**
1. Pass `description` and `severity` from backend scenario definitions through to the frontend
2. Add a subtitle or hover tooltip per scenario: "Market Stress: 20% broad equity decline" or "Interest Rate: +300bp rate shock"
3. Consider showing historical analogs: "Similar to: March 2020 COVID crash"
4. Factor shocks are useful for advanced users on hover: "Shocks: Market -20%, Momentum -10%"

**Key files:**
- `frontend/packages/ui/src/components/portfolio/RiskAnalysis.tsx` — stress test display (lines 239-289)
- `frontend/packages/ui/src/components/dashboard/views/modern/RiskAnalysisModernContainer.tsx` — data hook + risk score (lines 415-436)
- `portfolio_risk_engine/stress_testing.py` — scenario definitions (lines 12-66), `description` and `severity` fields available
- `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx` — layout order (lines 342-372)

---

## Issue 20a: Hedging tab — "Implement Strategy" is misleading + hedge info is confusing

**Severity:** Medium (UX clarity)
**Type:** UX / Labeling / Information design
**Page:** Portfolio Overview — Advanced Risk Analysis → Hedging tab

**What the user sees:**
Three hedge suggestions (e.g., "Hedge Financial - Mortgages exposure"), each with:
- Cost: ~2% allocation
- Protection: 17.1% of portfolio
- Duration: Rebalance
- Low Efficiency
- A big green "Implement Strategy" button

**Problem 1: "Implement Strategy" sounds like it will execute trades immediately**

The button actually opens a 4-step workflow dialog (Review → Impact → Trades → Execute). That's a good workflow! But the button label is alarming — "Implement" implies immediate action. Users hesitate or click nervously.

**Fix:** Rename to "Review Strategy" or "Explore Hedge" — something that signals it's a review process, not one-click execution.

**Problem 2: "Hedge Ticker" shows a category name, not a tradeable instrument**

In the workflow Step 1 (Review), the "Hedge Ticker" field shows "AGRICULTURAL - COMMODITIES/MILLING" — this is a factor/category label, not an actual ticker symbol. The user can't understand what they'd actually be buying.

**Root cause:** The backend `recommend_portfolio_offsets()` returns factor labels from the correlation matrix. The `HedgingAdapter.ts` tries to extract a ticker from the label but falls back to the raw category string when no ticker is embedded.

**Fix:** Show the actual tradeable instrument (e.g., "DBA - Invesco DB Agriculture Fund") or map factor categories to representative ETFs. If no specific instrument exists, say so: "Suggested exposure: Agricultural Commodities (e.g., DBA)"

**Problem 3: No plain-language explanation of the strategy**

The card shows raw numbers (correlation, weight, efficiency) but doesn't explain the trade in human terms. A user needs to understand: "We suggest BUYING a 2% position in an agricultural commodities ETF because it tends to move opposite to your mortgage REIT holdings, reducing your overall portfolio risk."

**Problem 4: Low efficiency hedges probably shouldn't be shown at all**

Correlation of ~0.18 is barely negative — this hedge would have minimal effect. The "Low Efficiency" label is honest but the question is: why show it? Either filter to Medium+ efficiency hedges, or clearly deprioritize low-efficiency ones with a dimmed/collapsed presentation.

**Problem 5: "Duration: Rebalance" is meaningless to users**

This is hardcoded (`HedgingAdapter.ts` line 157) and means "implemented via portfolio rebalancing" (not options/futures). But a user reads "Duration" as a time period. Either remove it or clarify: "Method: Portfolio Rebalance" or "Type: ETF Allocation."

**Key files:**
- `frontend/packages/ui/src/components/portfolio/RiskAnalysis.tsx` — Hedging tab, "Implement Strategy" button (line 335-341)
- `frontend/packages/ui/src/components/portfolio/HedgeWorkflowDialog.tsx` — 4-step workflow (Review → Impact → Trades → Execute)
- `frontend/packages/connectors/src/adapters/HedgingAdapter.ts` — transforms backend response, `toEfficiency()` (lines 41-46), duration hardcoded (line 157)
- `services/factor_intelligence_service.py` — `recommend_portfolio_offsets()` (line 1073+) — driver detection + hedge selection
- `routes/hedging.py` — `/api/hedging/preview` and `/api/hedging/execute` endpoints

**Fix approach:**
1. Rename "Implement Strategy" → "Review Strategy" or "Explore Hedge"
2. Show actual tradeable tickers or representative ETFs, not factor category names
3. Add a 1-sentence plain-language explanation of each hedge: "Buy X to offset your Y exposure"
4. Filter or deprioritize Low Efficiency hedges (correlation < 0.3)
5. Replace "Duration: Rebalance" with "Method: ETF Allocation" or remove
6. The 4-step workflow itself is good — keep it, just improve the entry point and hedge presentation

---

## Issue 20b: Performance Analytics — Hypothetical/Realized toggle is oversized, jarring, and half-finished

**Severity:** High (UX, unfinished feature)
**Type:** UX / Unfinished feature
**Page:** Portfolio Overview — Performance Analytics section (PerformanceViewContainer)

**Three problems:**

### 20a: The toggle card wastes massive vertical space

A full-width `Card` component with "Performance Mode" header + two toggle buttons sits above the entire Performance section. It takes ~80px in hypothetical mode and **expands to ~280px in realized mode** (adds institution/account form fields + Analyze button). This is a mode selector — it should be a small inline toggle or tab, not a hero card.

### 20b: Clicking "Realized" is jarring — sudden view change, blank form, no data

When the user clicks "Realized":
1. The card expands with institution and account dropdown fields — **both are blank/empty**
2. No data loads until the user manually clicks "Analyze"
3. The performance charts below go to empty/no-data state
4. The user has no idea what institution or account to select, or why they need to
5. It feels like landing on an unfinished page — "all of a sudden it's another view, it's not really finished"

The realized mode requires `POST /api/performance/realized` with optional institution/account filters, but the UI doesn't auto-populate available options or explain the workflow.

### 20c: Recommendation — default to realized, remove the toggle

The user's instinct is right: **just show realized performance and remove the hypothetical/realized distinction**. The reasoning:

- **Realized is what matters** — actual returns from actual trades, not theoretical buy-and-hold
- **Hypothetical is confusing** — users don't understand why they're seeing two different return numbers for the same portfolio
- **The toggle adds cognitive load** for zero benefit to most users
- If hypothetical data is useful (e.g., as a baseline comparison), show it as a secondary reference line on the realized chart, not as a separate mode

**Current code structure:**
- `PerformanceViewContainer.tsx` line 308: `useState<'hypothetical' | 'realized'>('hypothetical')` — defaults to hypothetical
- Lines 434-493: `modeControls` card with toggle buttons + conditional realized form
- Lines 360-368: Data routing — `isRealizedMode ? realizedMutation.data : hypotheticalData`
- Realized mode uses `useRealizedPerformance()` mutation (on-demand, no cache) vs hypothetical uses `usePerformance()` (auto-fetch, 5-min cache)

**Key files:**
- `frontend/packages/ui/src/components/dashboard/views/modern/PerformanceViewContainer.tsx` — mode toggle (lines 434-493), mode state (line 308), data routing (lines 360-368)
- `frontend/packages/ui/src/components/portfolio/PerformanceView.tsx` — tabbed view that receives data from either mode
- `frontend/packages/connectors/src/features/portfolio/hooks/useRealizedPerformance.ts` — realized data hook (mutation, requires manual trigger)
- `routes/realized_performance.py` — `POST /api/performance/realized` backend endpoint

**Fix approach:**
1. **Short-term**: Default to realized mode, auto-trigger the analysis on page load (no manual "Analyze" click needed), remove the institution/account form (use defaults)
2. **Medium-term**: Remove the toggle entirely. Show realized performance as the primary view. If hypothetical is useful, show it as a benchmark line overlay.
3. **If keeping both modes**: Shrink the toggle to a small tab pair (like the Attribution/Benchmarks/Risk tabs below it), not a full-width card. Auto-fetch realized data on toggle instead of requiring form submission.

---

## Issue 21: Standard ↔ Detailed toggle does nothing on 3 of 4 tabs

**Severity:** Medium
**Type:** Dead UI / Misleading control
**Page:** Portfolio Overview — Performance Analytics header (PerformanceHeaderCard)

**What happens:** The Standard / Detailed toggle buttons in the Performance Analytics header (line 104-105 in `PerformanceHeaderCard.tsx`) appear to toggle between two view modes. Clicking them changes the button highlight but nothing visibly changes on the page — unless the user is on the "Period Analysis" tab.

**Root cause:** The `viewMode` state (`"standard" | "detailed"`) is only consumed by `PeriodAnalysisTab` (line 73-78 in `PeriodAnalysisTab.tsx`). In "detailed" mode, it shows a small "Market Event" text block in each monthly return card. On the other 3 tabs (Attribution, Benchmarks, Risk Analysis), `viewMode` is not passed or used at all.

So clicking Standard ↔ Detailed:
- **Attribution tab**: no change
- **Benchmarks tab**: no change
- **Risk Analysis tab**: no change
- **Period Analysis tab**: shows/hides "Market Event" text on monthly cards — a very minor difference

**The toggle is prominently placed** in the header bar alongside Period and Benchmark selectors, suggesting it should have a significant effect. A user clicking it and seeing nothing change will assume it's broken.

**Key files:**
- `frontend/packages/ui/src/components/portfolio/performance/PerformanceHeaderCard.tsx` — lines 104-105 (toggle buttons)
- `frontend/packages/ui/src/components/portfolio/performance/PeriodAnalysisTab.tsx` — lines 73-78 (only consumer of viewMode)
- `frontend/packages/ui/src/components/portfolio/performance/types.ts` — line 1 (`ViewMode = "standard" | "detailed"`)
- `frontend/packages/ui/src/components/portfolio/performance/usePerformanceState.ts` — line 23 (state initialization)

**Fix approach:**
1. **Option A: Remove the toggle** — if there's no meaningful "detailed" variant for most tabs, remove the toggle entirely to avoid confusion. The "Market Event" info can always be shown or moved to tooltips.
2. **Option B: Make it meaningful** — add a "detailed" variant to each tab (e.g., Attribution shows additional columns, Benchmarks shows rolling metrics, Risk Analysis shows raw numbers). This is more work but would justify the toggle's presence.
3. **Option C: Move it** — make the toggle local to the Period Analysis tab only, where it actually has an effect.

---

## Issue 22: Benchmark selector crashes when selecting non-SPY benchmark

**Severity:** High
**Type:** Bug / Crash
**Page:** Portfolio Overview — Performance Analytics header (PerformanceHeaderCard)

**What happens:** Selecting a benchmark other than SPY (e.g., QQQ, VTI) from the benchmark dropdown causes the Performance Analytics section to crash or show an error state.

**Data flow when benchmark changes:**
1. User clicks benchmark dropdown → selects e.g. "QQQ"
2. `PerformanceHeaderCard` calls `onBenchmarkChange("QQQ")`
3. `usePerformanceState` → `handleBenchmarkChange` → calls container's `setBenchmarkTicker("QQQ")`
4. Container: `benchmarkParam = benchmarkTicker === 'SPY' ? undefined : 'QQQ'`
5. `usePerformance({ benchmarkTicker: 'QQQ' })` → new TanStack Query key → triggers fresh API call
6. Backend: `calculate_portfolio_performance_metrics()` is called with `benchmark_ticker='QQQ'`

**Likely crash causes:**
1. **Backend failure**: The performance API may fail or return unexpected data for non-SPY benchmarks (e.g., shorter history, missing data)
2. **Adapter mismatch**: `PerformanceAdapter.transform()` may not handle the response shape differences when a different benchmark is used
3. **"CUSTOM" option**: The fallback benchmarks list includes `{ symbol: "CUSTOM", name: "Custom" }` (line 54 in PerformanceHeaderCard.tsx) — "CUSTOM" is not a valid ticker and would definitely cause a backend error if selected

**Also note:** The benchmark selection is persisted to `localStorage` (line 89 in `usePerformanceState.ts`), so if the user selects a crashing benchmark, it will crash on every subsequent page load until localStorage is cleared.

**Key files:**
- `frontend/packages/ui/src/components/portfolio/performance/PerformanceHeaderCard.tsx` — lines 130-140 (benchmark dropdown), line 54 (fallback benchmarks including "CUSTOM")
- `frontend/packages/ui/src/components/dashboard/views/modern/PerformanceViewContainer.tsx` — lines 306-307 (benchmarkParam routing), line 322 (usePerformance call)
- `frontend/packages/ui/src/components/portfolio/performance/usePerformanceState.ts` — lines 38-44 (handleBenchmarkChange), line 89 (localStorage persist)
- `frontend/packages/connectors/src/features/analysis/hooks/usePerformance.ts` — hook that passes benchmarkTicker to API

**Fix approach:**
1. **Investigate crash** — check browser console / network tab for the actual error when QQQ is selected. Is it a 500 from backend, adapter transform error, or rendering error?
2. **Remove "CUSTOM" option** — it's not a valid ticker, shouldn't be in the dropdown
3. **Add error boundary / fallback** — if the API call fails for a benchmark, show an error message instead of crashing, and offer to reset to SPY
4. **Don't persist invalid selections** — add validation before saving benchmark to localStorage

---

## Issue 23: Performance Analytics — percentage display uses too many decimal places, Sharpe ratio formatting inconsistent

**Severity:** Low
**Type:** Polish / Readability
**Page:** Portfolio Overview — Performance Analytics header cards + tabs

**What the user sees:** Percentages throughout the Performance Analytics section display with 2 decimal places (e.g., "+2.34%", "-1.91%"). The user prefers 1 decimal place for percentages and 2 decimal places for the Sharpe ratio.

**Current formatting:**
- Period Return: `formatPercent(performanceData.periodReturn, { decimals: 2, sign: true })` — shows e.g. "+2.34%"
- Benchmark Return: `formatPercent(performanceData.benchmarkReturn, { decimals: 2, sign: true })`
- Alpha: `formatPercent(performanceData.alpha, { decimals: 2, sign: true })`
- Sharpe Ratio: `{performanceData.sharpeRatio}` — raw number, no explicit formatting (line 241)
- Monthly cards in PeriodAnalysisTab: `formatPercent(month.portfolio, { decimals: 2, sign: true })`

**Desired formatting:**
- All percentages: 1 decimal place (e.g., "+2.3%", "-1.9%")
- Sharpe ratio: 2 decimal places (e.g., "0.85", "1.23")

**Key files:**
- `frontend/packages/ui/src/components/portfolio/performance/PerformanceHeaderCard.tsx` — lines 195-196, 216-217, 227-228, 241 (header card metrics)
- `frontend/packages/ui/src/components/portfolio/performance/PeriodAnalysisTab.tsx` — lines 56, 62, 69 (monthly card percentages)
- `frontend/packages/ui/src/components/portfolio/performance/BenchmarksTab.tsx` — benchmark comparison percentages
- `frontend/packages/ui/src/components/portfolio/performance/RiskAnalysisTab.tsx` — risk metric percentages

**Fix approach:**
1. Change all `{ decimals: 2 }` to `{ decimals: 1 }` for percentage displays in the performance section
2. Format Sharpe ratio explicitly: `performanceData.sharpeRatio.toFixed(2)` instead of raw interpolation
3. Consider making this a consistent convention across the entire dashboard (not just Performance Analytics)

---

## Issue 24: Performance Insights cards — impact labels meaningless, numbers likely wrong, template text is misleading

**Severity:** High
**Type:** Bad data / Misleading UI
**Page:** Portfolio Overview — Performance Analytics → Insights panel (toggled by lightbulb icon)

**What the user sees:** Three insight cards (Performance, Risk, Opportunity) each with:
- A text summary containing specific numbers (e.g., "underperforming the benchmark by 17.15%", "Beta of 0.16")
- An impact badge ("high impact", "medium impact", "low impact")
- An action suggestion

**Problem 1: The impact badges don't connect to the insight text**

The impact level is determined by hardcoded threshold functions in `usePerformanceData.ts`:
- `getImpactFromAlpha()` (line 21): alpha < 0 → "high" (because underperforming = high impact finding)
- `getImpactFromRiskMetrics()` (line 27): vol > 20 || drawdown > 20 || beta > 1.2 → "high"
- `getImpactFromSharpe()` (line 34): sharpe < 1 → "high"

But "high impact" is semantically confusing — it reads as "this insight has high impact on your portfolio" when it actually means "this is a noteworthy finding." A user seeing "high impact" next to "underperforming by 17%" thinks the insight itself is causing high impact, not that it's flagging an important observation.

**Problem 2: The "alpha" used in insights is NOT CAPM alpha — it's raw period excess return**

The `alpha` fed into `buildInsights()` comes from `performanceData.alpha` (line 141 in `usePerformanceData.ts`):
```javascript
const alpha = periodMetrics?.alpha ?? 0
```
This is computed in `PerformanceViewContainer.tsx` line 514:
```javascript
alpha: pr - br  // portfolio period return minus benchmark period return
```
So if the portfolio returned -10% and SPY returned +7% over the selected period, "alpha" = -17%. This is **raw excess return, not Jensen's alpha** (which accounts for beta). The text saying "underperforming by 17%" may be numerically correct as a raw return gap but is misleading because it's labeled "alpha."

**Problem 3: Beta of 0.16 seems wrong or needs verification**

The `beta` in the insights comes from `data?.beta` → `performanceSummary.riskMetrics.beta`, which originates from the OLS regression in `performance_metrics_engine.py`. A portfolio beta of 0.16 means the portfolio barely moves with the market, which is unusual unless heavily in non-correlated assets. This needs verification — it might be correct for the user's specific portfolio, or it might be a data issue.

**Problem 4: `hasNoAlpha`/`hasNoSharpe` guard logic is broken**

Lines 42-43:
```javascript
const hasNoAlpha = alpha === 0
const hasNoSharpe = sharpeRatio === 0
```
These variables suggest "no data available" but actually just check if the value is exactly zero. When `hasNoAlpha` is true (alpha === 0), the code enters a branch that checks `alpha > 5` (always false since alpha is 0), then `alpha >= 0` (always true since 0 >= 0), resulting in "modestly outperforming" — which is wrong when data is actually missing. Similarly, when `hasNoRiskMetric` is true (all zeros), lines 61-67 check `volatility > 20` (always false) and fall through to "Volatility appears low, indicating conservative positioning" — also wrong for missing data.

**Problem 5: The insights are pure frontend templates, not AI-generated**

Despite the lightbulb icon and "AI insights" toggle label, these are hardcoded string templates with `if/else` thresholds. There's no Claude or AI model involved. The text says things like "indicates strong active management performance" regardless of context.

**Key files:**
- `frontend/packages/ui/src/components/portfolio/performance/usePerformanceData.ts` — `buildInsights()` (lines 40-110), impact threshold functions (lines 21-38), alpha/beta/sharpe sourcing (lines 137-145)
- `frontend/packages/ui/src/components/portfolio/performance/PerformanceHeaderCard.tsx` — insights rendering (lines 250-265), lightbulb toggle (lines 108-115)
- `frontend/packages/ui/src/components/portfolio/performance/types.ts` — `InsightImpact`, `InsightCard`, `PerformanceInsights` types
- `frontend/packages/ui/src/components/dashboard/views/modern/PerformanceViewContainer.tsx` — line 514 (alpha = pr - br raw computation)

**Fix approach:**
1. **Fix the alpha label** — either use real CAPM alpha from the backend (`benchmark_analysis.alpha_annual`) or relabel as "excess return" / "active return"
2. **Replace impact badges** — use severity labels that connect to the text: "Action Needed" / "Monitor" / "On Track" instead of ambiguous "high/medium/low impact"
3. **Fix zero-guard logic** — check for `null`/`undefined` (actual missing data) instead of `=== 0` (valid zero values)
4. **Verify beta** — cross-check the beta value against the backend CAPM regression output
5. **Long-term** — route these insights through Claude for genuine AI-generated, context-aware commentary instead of template strings

---

## Issue 25: Provider disconnect silently drops positions — portfolio value changes without warning

**Severity:** High (data integrity / trust)
**Type:** Bug — silent data degradation
**Page:** All pages (observed on Holdings, affects Overview too)

**What happens:**
1. User navigates to Holdings page
2. Briefly loses connection to a brokerage provider (Plaid, SnapTrade, or IBKR)
3. Page loads with partial data — fewer positions, lower portfolio value
4. **No error message, no warning banner, no indication that data is incomplete**
5. Connection recovers and full data returns on next load

**Evidence of inconsistency across the session:**
- First Overview load: **$112,332** (full data, all providers)
- Later Overview load: **$30,024** (likely one provider dropped)
- Holdings page: **$27,776** with 15 positions (partial data)

These swings suggest different provider responses at different times, with the UI silently showing whatever it gets.

**What should happen instead:**
1. **Stale data fallback**: If a provider fails, show the last-known-good data for those positions with a "stale" indicator (e.g., grayed out rows with "Last updated: 2 hours ago")
2. **Warning banner**: "Unable to reach SnapTrade — showing cached data for X positions" (similar pattern to Issue 3's partial-refresh toast)
3. **Portfolio value annotation**: If the total is based on incomplete data, show it: "$27,776 (partial — SnapTrade unavailable)"
4. **Don't let total value swing silently** — this destroys user trust. If you showed $112K and now show $30K, the user thinks they lost $80K.

**Related infrastructure:**
- `PortfolioManager.refreshHoldings()` uses `Promise.allSettled()` which correctly handles individual provider failures — but the result is silently merged without flagging which providers succeeded/failed
- Issue 3 already noted SnapTrade returning 500 on refresh — this may be the same underlying provider instability
- The `is_db_available()` positive-only cache and Phase A no-DB mode may also interact here

**Key files to investigate:**
- `frontend/packages/connectors/src/managers/PortfolioManager.ts` — `refreshHoldings()` (lines 670-752), provider error handling
- `frontend/packages/connectors/src/providers/SessionServicesProvider.tsx` — refresh intent handler
- `services/portfolio_service.py` — backend position aggregation across providers
- `providers/routing.py` — provider enablement + institution routing

**Fix approach:**
1. **Track provider status per-refresh**: Return metadata with each position fetch indicating which providers responded successfully
2. **Surface partial data warnings**: Add a banner or toast when any provider fails
3. **Cache last-known-good positions**: When a provider drops out, keep showing its cached positions (marked stale) rather than removing them
4. **Consistent portfolio value**: Either always use the same data source across pages, or clearly annotate differences

---

## Issue 26: Attribution tables — "Return" and "Contribution" columns are ambiguous, no explanations

**Severity:** Medium
**Type:** UX / Clarity
**Page:** Portfolio Overview — Performance Analytics → Attribution tab (Sector + Factor tables)

**What the user sees:** Clean tables with columns Weight / Return / Contribution (sector) and Beta / Return / Contribution (factor). The user said: "I get the weight, but Return — is that my return? And Contribution — I'm a little confused on that."

**What the columns actually show:**

### Sector Attribution
| Column | Actual meaning | Formula |
|---|---|---|
| **Weight** | Portfolio allocation to that sector | Sum of ticker weights in sector × 100 |
| **Return** | Weighted avg return of your holdings in that sector | contribution ÷ weight |
| **Contribution** | How much that sector added/subtracted from total portfolio return | Σ(weight_i × return_i) for tickers in sector |

### Factor Attribution
| Column | Actual meaning | Formula |
|---|---|---|
| **Beta** | Regression sensitivity to that factor | OLS coefficient (portfolio ~ factor returns) |
| **Return** | The factor proxy's own cumulative return | (1+r₁)(1+r₂)...(1+rₙ)-1 for SPY/MTUM/IWD |
| **Contribution** | How much factor exposure drove your returns | Σ(beta × monthly_factor_return) |

Factor proxies: Market=SPY, Momentum=MTUM, Value=IWD.

**Methodology note:** This is NOT Brinson-Fachler attribution (allocation + selection vs benchmark). Sector is simple weight × return contribution. Factor is regression-based decomposition. Both answer "what drove my returns?" but NOT "where did I beat/lag the benchmark?"

**Key files:**
- `frontend/packages/ui/src/components/portfolio/performance/AttributionTab.tsx` — table rendering
- `portfolio_risk_engine/portfolio_risk.py` — sector attribution (lines 2196-2286), factor attribution (lines 2312-2430)
- `portfolio_risk_engine/factor_utils.py` — `compute_multifactor_betas()` (lines 536-618)

**Fix approach:**
1. **Column tooltips**: Hover "Return" → "The weighted average return of your holdings in this sector over the selected period"
2. **Better column headers**: "Sector Return" instead of "Return". "Portfolio Contribution" instead of "Contribution"
3. **One-line explanation** above each table: "How much did each sector contribute to your total return?" / "How much did systematic factor exposures drive your returns?"
4. **Consider benchmark comparison**: Show sector weights vs SPY sector weights → Brinson allocation/selection effects

---

## Design Note E: Period Analysis is good + Benchmarks and Risk Analysis tabs are duplicative

**Type:** Positive feedback + Consolidation opportunity
**Page:** Portfolio Overview — Performance Analytics tabs

**Period Analysis — user likes it, confirmed real data:**
Monthly return grid showing portfolio vs benchmark is clean and useful. Data IS real — `compute_performance_metrics()` in `performance_metrics_engine.py` calculates actual monthly returns from FMP price data. Each month shows portfolio return, benchmark return, delta. Only placeholder: "Market Event" text in detailed mode.

**Benchmarks tab — duplicates content already shown elsewhere:**
Shows portfolio return vs benchmark, cumulative comparison, information ratio, up/down capture. But this is already covered by:
- Performance header cards (portfolio return, benchmark return, alpha, tracking error)
- Period Analysis tab (monthly portfolio vs benchmark)
- Overview metric cards (alpha generation)
The tab adds a cumulative chart but the core question "how am I doing vs benchmark?" is answered in 3+ places.

**Risk Analysis tab — duplicates the Risk Assessment card:**
Shows VaR, Beta, Volatility, Max Drawdown — the exact same four metrics as the Risk Assessment card (RiskMetricsContainer) already on the page. Adds a drawdown tooltip and correlation heatmap, but core metrics are fully redundant.

**Opportunity — replace with something more interesting:**
These two tab slots could show unique, high-value content instead:

1. **"What Drove Returns" tab**: Waterfall chart — Starting value → Factor contributions → Sector contributions → Stock selection → Ending value. One visual answering "why did I make/lose money?"
2. **"Risk Scenarios" tab**: Forward-looking risk instead of repeating VaR/beta. Monte Carlo distribution, stress test impacts, tail risk. Uses existing `monte_carlo.py` + `stress_testing.py` engines.
3. **"Income & Cash Flow" tab**: Dividend income, interest, option premium — income attribution and projected forward income. Uses `get_income_projection()`.
4. **"Position Attribution" tab**: Top contributors/detractors with sparklines, drill into individual position P&L.

**Key files:**
- `frontend/packages/ui/src/components/portfolio/performance/BenchmarksTab.tsx` — duplicative benchmark tab
- `frontend/packages/ui/src/components/portfolio/performance/RiskAnalysisTab.tsx` — duplicative risk tab
- `frontend/packages/ui/src/components/portfolio/performance/PeriodAnalysisTab.tsx` — monthly grid (good, keep)
- `frontend/packages/ui/src/components/portfolio/performance/AttributionTab.tsx` — sector/factor tables (good, keep)

---

## Issue 27: Factor Analysis view — right column is a duplicate Risk Assessment card, wasted space

**Severity:** Medium
**Type:** Redundancy / Wasted space
**Page:** Factor Analysis view (`/factors` route)

**What happens:** The Factor Analysis view uses a 2/3 + 1/3 grid layout. The left column has the actual factor analysis content (`FactorRiskModelContainer` with Factor Exposures, Risk Attribution, Performance tabs). The right column is **literally the same `RiskMetricsContainer`** component from the Overview page — same VaR, Beta, Volatility, Max Drawdown card, same `useRiskAnalysis()` data source, same everything.

**Layout (`ModernDashboardApp.tsx` lines 386-393):**
```
Grid (xl:grid-cols-3 gap-8)
├── xl:col-span-2: FactorRiskModelContainer  ← actual factor content
└── xl:col-span-1: RiskMetricsContainer      ← duplicate from Overview
```

A user who just came from the Overview page sees the same 4 risk metrics again. No new information.

**What should be there instead — factor-relevant context:**

The right column should show information contextual to factor analysis:

1. **Factor Risk Summary**: "Your portfolio's risk is 70% systematic (factor-driven) and 30% idiosyncratic. Top factor exposures: Market (1.02β), Real Estate (0.45β), Momentum (-0.12β)"
2. **Factor Concentration Warning**: "Your real estate factor exposure is 3x the benchmark weight — this is your largest factor bet"
3. **Factor Recommendations**: The backend `get_factor_recommendations()` tool already computes actionable factor tilt suggestions — surface them here instead of burying them in MCP-only access
4. **Factor Correlation Matrix**: A small heatmap showing how your factor exposures correlate — helps identify if your "diversification" is actually all the same bet
5. **Historical Factor Performance**: How your factor tilts have performed over the last 1Y — "Your momentum underweight cost ~2.3% vs a neutral portfolio"

**Key files:**
- `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx` — layout (lines 386-393), `RiskMetricsContainer` in right column
- `frontend/packages/ui/src/components/dashboard/views/modern/FactorRiskModelContainer.tsx` — left column container
- `frontend/packages/ui/src/components/portfolio/FactorRiskModel.tsx` — factor analysis UI (tabs: Exposures, Risk Attribution, Performance)
- `frontend/packages/ui/src/components/dashboard/views/modern/RiskMetricsContainer.tsx` — the duplicated component
- `mcp_tools/factor_intelligence.py` — `get_factor_recommendations()` (already exists, not surfaced in UI)
- `core/factor_recommendation_flags.py` — interpretive flags for factor recommendations

**Fix approach:**
1. **Replace `RiskMetricsContainer`** in the Factor Analysis right column with a new `FactorSummaryCard` or similar component
2. **Surface `get_factor_recommendations()`** output — the backend already computes factor tilt suggestions, they just need a frontend component
3. **Show factor-specific risk metrics** — variance decomposition (systematic vs idiosyncratic), factor concentration, largest factor bets
4. This is a broader pattern: each view's sidebar should show context relevant to that view, not a copy of the Overview risk card

---

## Issue 28: Analytics dropdown hides too much functionality

**Severity:** Medium
**Type:** Information architecture / Navigation
**Page:** Global nav — Analytics dropdown

**What happens:** Five full views are hidden behind a single "Analytics" dropdown in the top nav:
1. Factor Analysis (⌘3)
2. Performance (⌘4)
3. Scenario Analysis (⌘8)
4. Strategy Builder (⌘5)
5. Stock Research (⌘6)

These are major features — not sub-options. A user who doesn't explore the dropdown will never discover them. The current nav shows: Overview | Holdings | Analytics ▾ | AI Assistant — making the app look like it has 3 pages when it actually has 8.

**Fix approach:**
1. **Promote 1-2 key views to top-level nav**: Performance and Stock Research are likely the most-used after Overview/Holdings
2. **Or use a sidebar**: If there are 8+ views, a collapsible sidebar is more discoverable than a dropdown
3. **At minimum**: Add visual cues that Analytics has sub-pages (e.g., badge count, expanded state on hover)

---

## Issue 29: Factor Risk Model card — fixed height truncates content + sloppy hover outline

**Severity:** Medium (visual bug)
**Type:** CSS / Layout
**Page:** Factor Analysis view — Factor Risk Model card

### 29a: Card content is truncated despite available space below

The card has a fixed `h-[600px]` constraint (`FactorRiskModel.tsx` line 300). Inside, `TabContentWrapper` defaults to `h-[450px]` (`tab-content-wrapper.tsx` line 28), and the Risk Attribution ScrollArea is hardcoded to `h-[300px]` (line 420). With 8+ factor cards at ~120-140px each, content exceeds the available scroll area and appears cut off — even though there's plenty of viewport space below.

**Fix:** Remove `h-[600px]` or change to `min-h-[600px]` with `h-auto`. Replace hardcoded heights in TabContentWrapper and ScrollArea with `flex-1 min-h-0` to let content expand naturally.

### 29b: Hover/focus outline extends past card boundaries

When hovering or focusing on tabs inside the card, a focus ring (`focus-visible:ring-2 focus-visible:ring-offset-2`) extends beyond the card's rounded border. The `ring-offset-2` creates 2px of space outside the element, and the card's `overflow-hidden` doesn't clip it because it's rendered as `box-shadow`.

Global `:focus-visible` in `index.css` (lines 317-319) also applies `outline-offset: 2px`, compounding the overflow.

**Fix:** Remove `ring-offset-2` from TabsTrigger/TabsContent in `tabs.tsx`. Use `ring-inset` or `ring-1` without offset.

**Key files:**
- `frontend/packages/ui/src/components/portfolio/FactorRiskModel.tsx` — line 300 (`h-[600px]`), line 420 (`h-[300px]`)
- `frontend/packages/ui/src/components/blocks/tab-content-wrapper.tsx` — line 28 (default `h-[450px]`)
- `frontend/packages/ui/src/components/ui/tabs.tsx` — lines 30, 45 (`ring-offset-2`)
- `frontend/packages/ui/src/index.css` — lines 317-319 (global `:focus-visible`)

---

## Issue 30: Factor Risk Model "Performance" tab — metrics unexplained + insights disconnected

**Severity:** Medium
**Type:** UX / Content quality
**Page:** Factor Analysis view — Factor Risk Model → Performance tab

**What the user sees:**
- **Factor Alpha: +9%** — "what is factor alpha?"
- **Information Ratio** — "I don't understand what that means"
- **R-Squared** — "I don't understand what that means"
- **Key Risk Insights** — looks like template text, not related to the numbers above

**The data IS real** (not placeholders):
- **Factor Alpha** = CAPM alpha from `usePerformance()` → `performanceSummary.riskMetrics.alpha`. Annualized excess return vs benchmark.
- **Information Ratio** = alpha / tracking error. Measures risk-adjusted excess return consistency.
- **R-Squared** = `variance_decomposition.factor_variance / 100`. % of portfolio variance explained by the factor model.

**Key Risk Insights** are dynamically generated from top 3 factors by exposure via `buildRiskInsight()` (lines 255-293) — template strings based on factor name matching.

**Problems:**
1. **No explanations**: These are sophisticated quant metrics with no tooltips, no descriptions, no context
2. **No qualitative labels**: Is 9% alpha good? Is 0.65 R-squared high? No reference points
3. **Insights disconnect**: The "Key Risk Insights" describe factor *exposures* ("market sensitivity", "large-cap bias") but the metrics above are about factor *performance* (alpha, IR, R²). Different topics on the same tab.
4. **Tab framing**: "Performance" tab in a "Factor Risk Model" card — this is really factor return attribution, not generic performance

**Key files:**
- `frontend/packages/ui/src/components/portfolio/FactorRiskModel.tsx` — Performance tab (lines 449-488), metrics (lines 242-253), `buildRiskInsight()` (lines 255-293)
- `frontend/packages/ui/src/components/dashboard/views/modern/FactorRiskModelContainer.tsx` — `performanceMetrics` computation (lines 245-274)

**Fix approach:**
1. **Add explanations**: Tooltip per metric — "Factor Alpha: Your annualized excess return above benchmark after adjusting for factor exposures. >5% is strong."
2. **Add qualitative labels**: "Information Ratio > 0.5 = good, > 1.0 = excellent"
3. **Fix the disconnect**: Make Key Risk Insights reference the performance metrics ("Your 9% alpha is primarily driven by Market exposure"), or move insights to the Exposure tab
4. **Rename tab**: "Factor Attribution" or "Factor Returns" would be clearer
5. **Claude opportunity**: Generate a narrative tying alpha, IR, R², and exposures into one coherent story

---

## Issue 31: Performance view (Analytics dropdown) is an exact duplicate of the home page section — wasted opportunity

**Severity:** Medium
**Type:** Wasted real estate / Missed opportunity
**Page:** Analytics → Performance (nav dropdown item, `activeView === 'performance'`)

**What happens:** Clicking "Performance" under the Analytics dropdown navigates to a view that renders the exact same `<PerformanceViewContainer />` component already embedded on the home page (`'score'` view). It's a 1:1 duplicate — same component, same hook (`usePerformance()`), same data, same tabs.

**Code evidence:**
```tsx
// Home page ('score' view) — ModernDashboardApp.tsx line 369:
<PerformanceViewContainer />

// Performance view — ModernDashboardApp.tsx line 401:
<PerformanceViewContainer />  {/* Real data from usePerformance() */}
```

Both render the identical component. The only difference is the home page also shows PortfolioOverview, AssetAllocation, RiskAnalysis, and RiskMetrics above it.

**Why this is a problem:**
1. Users navigating to a dedicated "Performance" page expect deeper, more focused content than the home page summary
2. The home page already shows the full PerformanceViewContainer (with all 4 tabs: Attribution, Benchmarks, Risk Analysis, Period Analysis)
3. There's zero unique content — no reason to navigate here instead of scrolling down on the home page

**What the dedicated Performance page could show instead:**

This is prime real estate for deeper performance analysis that doesn't belong on a dashboard overview:

1. **Realized vs Hypothetical comparison** — side-by-side instead of a toggle, with reconciliation detail
2. **Full position-level P&L table** — per-ticker returns, cost basis, holding period returns (data exists in `TradingAnalyzer`)
3. **Rolling return charts** — 3M/6M/12M rolling returns vs benchmark (data exists: `rolling_sharpe`, `rolling_volatility` from `performance_metrics_engine.py` lines 224-241)
4. **Drawdown analysis** — full drawdown chart over time (not just the single max drawdown number), peak/trough dates, recovery visualization
5. **Calendar heatmap** — monthly returns as a color-coded calendar grid (the data is already available in `monthly_returns`)
6. **Income & yield tracking** — dividend/interest income over time, yield-on-cost trends (data from `get_income_projection()`)
7. **Tax lot detail** — unrealized gains/losses by lot, wash sale flags, holding period for long-term vs short-term (data from `suggest_tax_loss_harvest()`)

**Key files:**
- `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx` — lines 397-404 (performance view case), lines 342-372 (score view with same component)
- `frontend/packages/ui/src/components/dashboard/views/modern/PerformanceViewContainer.tsx` — the duplicated component
- `portfolio_risk_engine/performance_metrics_engine.py` — rolling metrics (lines 224-241) that exist but aren't surfaced in a dedicated view

**Fix approach:**
1. **Short-term**: Either remove the Performance nav item (since it's on the home page already) or redirect to the home page's performance section with anchor scroll
2. **Medium-term**: Build a dedicated deep-dive Performance page with unique content — position-level P&L, rolling charts, drawdown visualization, calendar heatmap — leveraging existing backend data that currently has no frontend surface

---

## Issue 32: Scenario Analysis — powerful engines crammed into one card with 6 tabs, feels like a display placeholder

**Severity:** High (UX / Discoverability)
**Type:** Information architecture / Feature presentation
**Page:** Analytics → Scenario Analysis (`activeView === 'scenarios'`)

**User feedback:** "There's a lot of potential here, especially with simulations — but it's all jammed into one card with a ton of tabs. I don't really know how to use it."

**What's actually there (5 of 6 tabs fully wired to real backends):**

| Tab | Status | What it does | Backend engine |
|---|---|---|---|
| **Portfolio Builder** | ✅ Wired | Edit position weights, apply templates (Equal Weight, 60/40, etc.), run what-if analysis | `scenario_analysis.py` |
| **AI Optimization** | ✅ Wired (cache) | Shows cached optimization results from Strategy Builder, "Apply as What-If" | `optimization.py` (CVXPY) |
| **Historical Scenarios** | ❌ Placeholder | Dropdown for 2008/COVID/Dot-Com/Black Monday — all disabled, "coming soon" | None yet |
| **Stress Tests** | ✅ Wired | Run 8 predefined stress scenarios, see position-level + factor-level impacts | `stress_testing.py` |
| **Monte Carlo** | ✅ Wired | 500-5000 simulations, 6-36mo horizon, probability cone chart, VaR/CVaR | `monte_carlo.py` (Cholesky) |
| **Efficient Frontier** | ✅ Wired | CVXPY parametric sweep, scatter chart with current portfolio marker | `efficient_frontier.py` |

**The problem is entirely presentation, not capability:**

1. **Single card, fixed height**: Everything is inside one `Card` with `h-[calc(100vh-12rem)]`. 6 tabs compete for space in a horizontal tab bar that overflows on smaller screens.
2. **No guided workflow**: User lands on Portfolio Builder tab with no context. There's no "start here" guidance, no suggested flow (e.g., "Run a stress test → See vulnerabilities → Optimize → Backtest the result").
3. **Tabs don't cross-reference**: Running a Monte Carlo doesn't connect to running an optimization. Results from one tab don't inform another. Each feels isolated.
4. **No explanations**: What does "500 simulations" mean? What is an efficient frontier? Why would I run a stress test? Zero educational content.
5. **Historical tab is broken**: Disabled buttons with "coming soon" erode trust in the other tabs.

**Key files:**
- `frontend/packages/ui/src/components/portfolio/ScenarioAnalysis.tsx` — main component (433 lines), 6 tabs
- `frontend/packages/ui/src/components/dashboard/views/modern/ScenarioAnalysisContainer.tsx` — container (840 lines), integrates 6 hooks
- `frontend/packages/ui/src/components/portfolio/scenario/` — individual tab components (PortfolioBuilderTab, StressTestsTab, MonteCarloTab, EfficientFrontierTab, etc.)

**Fix approach:**
1. **Break out of one card**: Give each analysis type its own section/card. A Monte Carlo simulation deserves a full-width section, not a tab pane.
2. **Add guided entry points**: "What do you want to explore?" → Cards with descriptions: "Stress Test: See how your portfolio would perform in a market crash" / "Monte Carlo: Simulate 1000 possible futures for your portfolio"
3. **Connect the workflow**: After a stress test reveals a vulnerability, offer "Optimize to reduce this risk" → After optimization, offer "Backtest this allocation"
4. **Remove or hide Historical tab** until it's implemented — a disabled placeholder hurts credibility
5. **Add brief explanations** to each section header: "Monte Carlo simulation runs thousands of random market scenarios based on historical patterns to estimate the range of possible outcomes for your portfolio"
6. **Claude integration**: Let the AI assistant guide users through scenario analysis — "I see your portfolio has high concentration risk. Want me to run a stress test to see how a market crash would affect you?"

---

## Issue 33: Strategy Builder — powerful but confusing, user doesn't know what they're building or backtesting

**Severity:** High (UX / Discoverability)
**Type:** Information architecture / Feature presentation
**Page:** Analytics → Investment Strategies (`activeView === 'strategies'`)

**User feedback:** "A strategy builder sounds great — but what am I actually building? I feel like there's more potential here — it could be a playground to try different combinations. And the backtest button — what am I backtesting? I'd love to backtest a strategy but I don't understand how to use it."

**What's actually there (4 tabs):**

| Tab | Status | What it does | Issue |
|---|---|---|---|
| **Strategy Builder** | Partially wired | Name/type/risk tolerance + asset allocation sliders → "Create Strategy" | Create button doesn't persist (TODO in code). Backtest disabled until optimization runs. |
| **Marketplace** | Wired | Pre-built templates (Growth, Value, Balanced, Income, Momentum) → "Deploy" triggers optimization | Templates may be placeholders if optimization hasn't run. |
| **Active Strategies** | Placeholder | Shows "No Active Strategies" — read-only, no actions | Can't activate, edit, or deactivate anything. |
| **Performance** | Wired | Backtest results with equity curve, annual breakdown, security/sector/factor attribution | Only works after optimization → backtest chain. Shows "Run a backtest" button that's just a single button with no context. |

**Core UX problems:**

### 33a: "What am I building?"
The Builder tab has asset allocation sliders (Stocks/Bonds/Commodities/Cash/Alternatives) but the user doesn't understand the output. Is this a target allocation? A paper portfolio? A rebalancing rule? The tab doesn't explain what happens after you click "Create Strategy."

Reality: "Create Strategy" logs the action but **doesn't save anything** (line 341: `// TODO: Implement strategy saving functionality with backend API`). The strategy vanishes on page reload.

### 33b: "What am I backtesting?"
The Performance tab shows a "Run a backtest" button with no context:
- What portfolio is being tested? (Answer: the optimized weights from the last optimization run)
- Over what period? (Answer: selectable 1Y/3Y/5Y/10Y/MAX, but not obvious)
- Against what benchmark? (Answer: hardcoded SPY)
- The button is **disabled** unless `hasTickerWeights=true` — which requires running an optimization first. No message explains this prerequisite.

### 33c: Active Strategies is empty and non-functional
Shows "No Active Strategies" with a message to browse the marketplace. But even if you deploy a marketplace strategy, it doesn't appear here because strategy persistence isn't implemented.

### 33d: Everything crammed into one 700px-tall card
Same problem as Scenario Analysis — 4 tabs in a fixed-height card. The Strategy Builder tab alone has a 3-column layout (config + allocation + preview) that's cramped at 700px.

**What this could be — "the playground":**
The user's instinct is right. This should be a sandbox where you can:
1. **Build**: Drag sliders to create an allocation → see instant preview of expected risk/return
2. **Compare**: Side-by-side comparison of 2-3 strategies (current vs proposed vs template)
3. **Backtest**: One-click "How would this have performed?" with clear results
4. **Iterate**: Tweak and re-run without losing previous results (session history)
5. **Deploy**: When satisfied, export to target allocation or generate rebalance trades

**Key files:**
- `frontend/packages/ui/src/components/portfolio/StrategyBuilder.tsx` — main component, 4 tabs, fixed 700px height
- `frontend/packages/ui/src/components/dashboard/views/modern/StrategyBuilderContainer.tsx` — container (hooks, handlers, TODO on line 341)
- `frontend/packages/ui/src/components/portfolio/strategy/BuilderTab.tsx` — allocation sliders + create button
- `frontend/packages/ui/src/components/portfolio/strategy/PerformanceTab.tsx` — backtest results + "Run a backtest" button
- `frontend/packages/ui/src/components/portfolio/strategy/ActiveStrategiesTab.tsx` — empty placeholder
- `frontend/packages/ui/src/components/portfolio/strategy/MarketplaceTab.tsx` — pre-built templates

**Fix approach:**
1. **Explain the workflow**: Add a brief intro: "Build a portfolio allocation → Backtest it against history → Deploy as your target"
2. **Remove the optimization prerequisite for backtesting**: Let users backtest any custom allocation directly from the Builder tab — they shouldn't need to run an optimization first
3. **Remove Active Strategies tab** until persistence is built — an always-empty tab is worse than no tab
4. **Inline the backtest**: Instead of a separate Performance tab, show backtest results directly below the Builder when the user clicks "Test This Allocation"
5. **Break out of the card**: Each function (build, marketplace, backtest) should be its own section with room to breathe
6. **Add strategy comparison**: Side-by-side cards showing current portfolio vs proposed strategy vs template
7. **Connect to execution**: After backtesting, offer "Set as Target Allocation" → connects to existing `set_target_allocation()` + `preview_rebalance_trades()`

---

## Issue 34: AI Assistant intro text is generic/technical + quick-action buttons vastly understate capabilities

**Severity:** High (first impression / product positioning)
**Type:** UX / Content / Feature gap
**Page:** AI Assistant view

### 34a: Intro text reads like a feature spec, not a value proposition

The current welcome message (`ChatCore.tsx` lines 532-551):
```
Hello! I'm your AI Portfolio Assistant. I can help you with comprehensive
portfolio analysis, risk management, and investment decisions.

What I can do for you:
- Portfolio Analysis — Deep dive into performance, risk metrics, and allocation
- Factor Risk Modeling — Advanced factor exposure and attribution analysis
- Stress Testing — Monte Carlo simulations and scenario analysis
- Stock Research — Individual security analysis and portfolio impact
- Smart Rebalancing — AI-driven optimization recommendations
- Market Intelligence — Real-time insights and predictive analytics
```

This reads like a bullet-point feature list, not an invitation. A user seeing "Factor Risk Modeling — Advanced factor exposure and attribution analysis" doesn't know why they'd want that. The intro should answer "what can this do **for me**?" not "what technical capabilities exist."

**What it should say instead** — user-centric framing:
- "How is my portfolio doing?" instead of "Portfolio Analysis"
- "What should I be worried about?" instead of "Risk Management"
- "What should I buy or sell?" instead of "Smart Rebalancing"
- "What's happening in the market that affects me?" instead of "Market Intelligence"
- "Run a scenario — what if the market drops 20%?" instead of "Stress Testing"

### 34b: Quick-action buttons are just 4 navigation links

Current buttons (`ChatCore.tsx` lines 556-561):
1. **Portfolio Overview** → navigates to Overview view
2. **Risk Analysis** → navigates to Risk view
3. **Factor Models** → navigates to Factor view
4. **Stock Lookup** → navigates to Stock Research view

These are page links, not AI actions. They don't invoke the assistant at all — they just switch views.

### 34c: The actual capability is 60+ MCP tools — massive gap

The assistant has access to **60+ real tools** via the portfolio-mcp server, including:

**What users would actually want to ask:**
- "Show me my biggest risks right now" → `get_risk_analysis` + `get_risk_score`
- "How would a 20% market crash affect me?" → stress testing via `run_whatif`
- "What should I sell for tax loss harvesting?" → `suggest_tax_loss_harvest`
- "What's my income projection for this year?" → `get_income_projection`
- "Compare my portfolio to an equal-weight version" → `compare_scenarios`
- "Analyze NVDA — should I add more?" → `analyze_stock` + `get_quote`
- "What are my factor exposures and what should I change?" → `get_factor_analysis` + `get_factor_recommendations`
- "Run a Monte Carlo simulation — what's my 5-year outlook?" → scenario analysis
- "Show me my realized P&L by position" → `get_trading_analysis`
- "Place a trade: buy 10 shares of AAPL" → `preview_trade` + `execute_trade`
- "Monitor my option hedges" → `monitor_hedge_positions`
- "Create a basket tracking the top 10 S&P stocks" → `create_basket_from_etf`

**Plus the full FMP data suite** (via fmp-mcp): earnings transcripts, estimate revisions, institutional ownership, insider trades, technical analysis, sector overview, economic data.

### 34d: The buttons should be contextual conversation starters, not nav links

Instead of 4 view links, show **contextual quick prompts** that actually invoke the AI:

**For a new user:**
- "What's my portfolio's biggest risk?" (invokes risk analysis + flags)
- "How am I performing vs the S&P?" (invokes performance comparison)
- "What upcoming events affect my holdings?" (invokes market intelligence)
- "Help me optimize my allocation" (invokes optimization workflow)

**For a returning user (context-aware):**
- "Your NVDA position is up 58% — review exit strategy?" (based on current data)
- "Earnings for AT.L in 6 days — want a pre-earnings analysis?" (from market intelligence)
- "Portfolio risk score is 92.8 (High) — want to see what's driving it?" (from risk score)

**Key files:**
- `frontend/packages/ui/src/components/chat/shared/ChatCore.tsx` — intro text (lines 532-551), quick-action buttons (lines 556-561)
- `frontend/packages/chassis/src/services/GatewayClaudeService.ts` — gateway SSE client + tool approval
- `mcp_server.py` — 60+ registered MCP tools (the actual capability set)

**Fix approach:**
1. **Rewrite intro text** — user-centric, conversational, outcome-focused. "I can help you understand your portfolio, find risks, plan trades, and make better investment decisions."
2. **Replace nav buttons with prompt starters** — clicking should send a message to the AI, not switch views
3. **Make buttons contextual** — use current portfolio data to generate relevant suggestions (e.g., if risk is high, suggest "Let's look at what's driving your risk score")
4. **Show capability breadth gradually** — don't list 60 tools upfront, but after a few interactions, suggest: "Did you know I can also run backtests, analyze option strategies, and monitor your hedges?"
5. **Add example conversations** — show 2-3 mini-transcripts of what a real interaction looks like, so users understand the depth

---

## Issue 35: Stock Risk Lookup — great data buried in 7 oversized tabs, no interpretation, just a wall of statistics

**Severity:** High
**Type:** Information architecture / UX density
**Page:** Analytics → Stock Research (`activeView === 'research'`)

**User feedback:** "It looks like it has some great data — but even for me it's like, ok what do I do with all these numbers? It's just like a list of statistics. I'd rather just get all the numbers at once if I want them, rather than clicking around all these buttons and huge boxes that don't tell me anything."

**Current layout: 7 tabs, each with oversized gradient cards**

| Tab | What it shows | Density |
|---|---|---|
| **Overview** | VaR 95%, Beta, Volatility, Sharpe + VaR 99%, Max Drawdown, Correlation, Sector | 4 big cards + 1 detail card + 1 risk rating card |
| **Risk Factors** | Factor beta/R² per factor (Market, Momentum, Value, etc.) | 1 card per factor with progress bars |
| **Technicals** | RSI, MACD, Support/Resistance, Bollinger Bands | 2 big cards + 2 detail cards |
| **Fundamentals** | P/E, ROE, D/E, Profit Margin + P/B, Financial Health Scores | 4 big cards + 2 detail cards |
| **Peer Comparison** | Comparison table vs peers | Separate API call, on-demand |
| **Portfolio Fit** | What-if impact of adding this stock | Separate API call, on-demand |
| **Price Chart** | Candlestick / line chart | Chart only |

**The problems:**

### 35a: Information is too spread out — 7 clicks to see everything
Each tab shows 4-6 metrics in large gradient cards. A user looking up AAPL has to click through 7 tabs to build a complete picture. Most finance professionals would want a single dense summary.

### 35b: Cards are oversized — one number per giant gradient box
Each metric gets its own `Card` with a gradient background, large font number, and a tiny label. For example, the Overview tab has 4 `StatusCell` cards in a 2×2 grid — that's ~320px of height for 4 numbers (VaR, Beta, Volatility, Sharpe). A simple table row could show all 4 in ~40px.

### 35c: No interpretation or context
- VaR 95% shows "2.3%" — is that good? Bad? How does it compare to the market?
- Beta shows "1.12" — what does that mean for my portfolio?
- RSI shows "45.2 — Neutral" — ok, but so what?
- Financial Health Score shows "Profitability: 72/100" — what drove that score?

Every number is shown without context, comparison, or actionable guidance.

### 35d: Fundamentals tab duplicates metrics within itself
The Fundamentals tab shows ROE, P/E, Profit Margin as big cards at the top, then shows the exact same ROE, Profit Margin again in the "Valuation Metrics" section below (lines 133-163 in `FundamentalsTab.tsx`). The Financial Health Scores then score the same metrics again (Profitability = f(ROE, Margin)).

### 35e: The data IS real and good — it's a presentation problem
All numbers come from real backend analysis (`analyze_stock` MCP tool → FMP data + factor analysis). The backend returns a rich payload with everything needed. The issue is purely how it's displayed.

**What this should look like instead:**

**Option A: Dense summary card + expandable detail**
Show a single card with all key metrics in a compact table/grid format — like a Bloomberg terminal snippet. One glance, all numbers. Click to expand any section for detail.

| Metric | Value | Context |
|---|---|---|
| Price | $178.50 (+1.2%) | vs 52W: $124 – $199 |
| Beta | 1.12 | Slightly above market |
| Volatility | 28.3% | vs S&P: 16.2% |
| VaR (95%) | 2.3% | ~$4,100 daily risk |
| Sharpe | 0.85 | Fair risk-adjusted return |
| RSI | 45.2 | Neutral (30-70 range) |
| P/E | 28.3x | vs Sector avg: 22x |

**Option B: AI-generated narrative + data appendix**
At the top: Claude-generated 2-3 sentence assessment: "AAPL shows moderate risk with slightly above-market beta (1.12) and elevated volatility (28.3% vs S&P's 16.2%). RSI at 45 is neutral. The stock is trading at a premium to sector peers (28.3x vs 22x P/E) but has strong profitability (ROE 147%)."

Below: Collapsible sections for Risk Metrics, Technicals, Fundamentals with all the raw numbers for users who want them.

**Option C: Keep tabs but make them dense**
If keeping tabs, condense each to a data table instead of one-number-per-card. The Overview tab could be a single compact table with 10 metrics instead of 4 oversized cards + 2 detail cards.

**Key files:**
- `frontend/packages/ui/src/components/portfolio/StockLookup.tsx` — main component, 7-tab layout (lines 279-289)
- `frontend/packages/ui/src/components/portfolio/stock-lookup/OverviewTab.tsx` — 4 StatusCell cards + 2 detail cards
- `frontend/packages/ui/src/components/portfolio/stock-lookup/TechnicalsTab.tsx` — RSI, MACD, Support/Resistance, Bollinger
- `frontend/packages/ui/src/components/portfolio/stock-lookup/FundamentalsTab.tsx` — P/E, ROE, D/E + duplicated metrics + health scores
- `frontend/packages/ui/src/components/portfolio/stock-lookup/PeerComparisonTab.tsx` — peer table
- `frontend/packages/ui/src/components/portfolio/stock-lookup/PortfolioFitTab.tsx` — what-if impact
- `frontend/packages/ui/src/components/portfolio/stock-lookup/PriceChartTab.tsx` — chart
- `frontend/packages/ui/src/components/dashboard/views/modern/StockLookupContainer.tsx` — container (data hooks)

**Fix approach:**
1. **Flatten the tabs** — show a dense summary with all key metrics on one screen. Use tabs only for genuinely separate workflows (Peer Comparison, Portfolio Fit)
2. **Condense the cards** — replace one-number gradient cards with a compact data table or grid. Save the card treatment for the 2-3 most important metrics.
3. **Add interpretation** — next to each number, show a brief context line: "vs sector avg", "vs S&P 500", "30-70 neutral range"
4. **Remove duplication** — Fundamentals tab shows ROE/Margin three times
5. **Add a narrative summary** — either template-based or Claude-generated, giving a 2-3 sentence assessment at the top
6. **Consider two-panel layout** — left: dense metric summary, right: chart + portfolio fit context

---

## Issue 36: Stock Lookup — Portfolio Fit is the most useful feature but it's hidden in tab 6 of 7, and shows too few metrics

**Severity:** Medium
**Type:** Feature buried / Incomplete data
**Page:** Analytics → Stock Research → Portfolio Fit tab

**User feedback:** "The portfolio fit is quite hidden — but that is probably most interesting, right? Like, this tool can tell me how it will impact my portfolio's numbers? That's probably useful — but it's just hidden. And when I do it — ok I see a what-if analysis — but there could be more interesting stuff, like what would it do to my Sharpe ratio? My risk?"

**Current state:**
Portfolio Fit is tab 6 of 7 in the Stock Lookup component. The user has to:
1. Search for a stock
2. Wait for analysis to load
3. Scroll through 5 other tabs to find "Portfolio Fit"
4. Select a position size (1%, 2.5%, 5%)
5. Click "Run Portfolio Fit"
6. Wait for what-if API call

**When results arrive, only 3 metrics are shown** (`StockLookupContainer.tsx` lines 511-530):

| Metric | What it shows |
|---|---|
| Annual Volatility | Current → With Position |
| Concentration (Herfindahl) | Current → With Position |
| Factor Variance | Current → With Position |

**What the backend what-if engine actually computes** (but isn't surfaced):
The `run_whatif` MCP tool returns a full `scenario_summary` that includes volatility, Sharpe ratio, expected return, beta, sector concentration, factor exposures, and complete risk analysis. The container cherry-picks only 3 metrics and discards the rest.

**What the user would want to see:**
- Sharpe ratio impact (current → with position)
- Portfolio beta impact
- Expected return change
- Sector concentration shift (am I overweight a sector?)
- Correlation to existing holdings (is this diversifying or concentrating?)
- VaR impact
- A plain-language verdict: "Adding 2.5% AAPL would slightly increase your tech concentration but improve your Sharpe ratio from 0.85 → 0.92"

**Key files:**
- `frontend/packages/ui/src/components/portfolio/stock-lookup/PortfolioFitTab.tsx` — display (lines 92-105, metric table)
- `frontend/packages/ui/src/components/dashboard/views/modern/StockLookupContainer.tsx` — lines 487-535 (only extracts volatility, herfindahl, factor_variance from what-if result)
- `mcp_tools/whatif.py` — `run_whatif()` returns full scenario_summary with many more metrics

**Fix approach:**
1. **Promote Portfolio Fit** — make it visible immediately (not tab 6 of 7). Show a "How would this affect my portfolio?" section right after the stock header, before the detail tabs.
2. **Surface more metrics** — extract Sharpe, beta, expected return, sector weights from the what-if response. Show a comprehensive before/after comparison table.
3. **Add a verdict** — template or Claude-generated summary: "Adding 2.5% AAPL improves diversification (Herfindahl drops 5%) but increases tech weight from 32% → 35%."
4. **Auto-run** — consider running portfolio fit automatically at the default size when a stock is selected, so results are already visible without a manual click.

---

## Issue 37: Stock Lookup — Price chart should be visible by default, not buried in a tab

**Severity:** Low
**Type:** UX / Layout
**Page:** Analytics → Stock Research → Price Chart tab

**User feedback:** "The price chart should probably not be a tab. Might be better to just show it off the bat."

**Current state:** The price chart is tab 7 of 7 — the last tab in the Stock Lookup component. The user has to click through to "Price Chart" to see it. A price chart is the most basic, expected element of any stock analysis view — users expect to see it immediately.

**Suggested layout redesign for the entire Stock Lookup:**
The user's overall feedback points to a structural rethink. Instead of 7 equal tabs, consider a layout like:

```
┌─────────────────────────────────────────────────────────┐
│ AAPL — Apple Inc.  $178.50 (+1.2%)  Medium Risk         │  ← Stock header
├──────────────────────────┬──────────────────────────────┤
│ Price Chart              │ Key Metrics (dense table)    │  ← Always visible
│ [candlestick/line]       │ Beta: 1.12  VaR: 2.3%       │
│                          │ Sharpe: 0.85  RSI: 45        │
│                          │ P/E: 28.3x  ROE: 147%       │
│                          │ Volatility: 28.3%            │
├──────────────────────────┴──────────────────────────────┤
│ Portfolio Impact: Adding 2.5% → Sharpe +0.07, Vol -0.2% │  ← Auto-run fit
├─────────────────────────────────────────────────────────┤
│ [Peer Comparison] [Detailed Fundamentals] [Technicals]  │  ← Optional drill-down
└─────────────────────────────────────────────────────────┘
```

- **Top row**: Stock header + price chart + dense metrics — always visible on load
- **Middle row**: Portfolio Fit result — auto-computed or one-click
- **Bottom row**: Optional drill-down tabs for users who want deeper detail

**Key files:**
- `frontend/packages/ui/src/components/portfolio/StockLookup.tsx` — line 288 (Price Chart as 7th tab)
- `frontend/packages/ui/src/components/portfolio/stock-lookup/PriceChartTab.tsx` — chart component

**Fix approach:**
1. **Show chart by default** — display the price chart in the main view alongside the stock header, not as a tab
2. **Consider two-column layout** — chart left, dense metrics right
3. **Reduce tabs from 7 to 3-4** — merge Overview + Technicals + Risk Factors into one dense summary; keep Peer Comparison, Portfolio Fit, and Fundamentals as drill-down tabs

---

## Issue 36: Risk Management Settings page — wrong metrics + mostly placeholder tabs

**Severity:** High (data bug) / Medium (placeholder cleanup)
**Type:** Bug + Placeholder/dead UI
**Page:** Risk Management Settings (via "..." → Settings, or `activeView === 'risk-settings'`)

### 36a: Metric cards show wildly wrong values (double-conversion bug)

| Metric | Settings Page | Overview Page | Off by |
|--------|--------------|---------------|--------|
| Portfolio Volatility | **0.1%** | **8.0%** | ~80x |
| Max Drawdown | **-0.0%** | **-55.9%** | completely wrong |
| Top Risk Contributor | **STWD 15.0%** | **DSU 27.4%** | different ticker |

**Root cause:** Double percentage conversion.
- `PerformanceAdapter` returns volatility/drawdown already as percentages (8.0, -55.9)
- `RiskSettingsViewModern.tsx` (lines 141-146) divides by 100 *again*: `(rawMetrics.portfolio_volatility / 100).toFixed(1)` → 8.0 / 100 = 0.08 → "0.1%"
- `useRiskMetrics.ts` (line 67) multiplies `largestPosition` by 100 when data is already in percentage form

**Fix:** Remove the `/100` in `RiskSettingsViewModern` for volatility/maxDrawdown. Remove `*100` in `useRiskMetrics` for largestPosition. Or better: use the same data source as Overview (`useRiskAnalysis`) instead of the separate `useRiskMetrics` hook.

**Key files:**
- `frontend/packages/connectors/src/features/riskMetrics/hooks/useRiskMetrics.ts` — line 67 (`* 100` on largestPosition), lines 84-85 (metric extraction)
- `frontend/packages/ui/src/components/dashboard/views/modern/RiskSettingsViewModern.tsx` — lines 141-155 (`/ 100` conversions)
- `frontend/packages/connectors/src/adapters/PerformanceAdapter.ts` — returns values already as percentages

### 36b: Risk Limits tab — all sliders maxed out, unclear what they control

The Risk Limits tab shows configurable limits (max position size, max sector exposure, etc.) but:
- All values are at maximum/default with no guidance on what reasonable limits are
- No explanation of what happens when a limit is breached — is it a warning? A hard block? Just a notification?
- Should be agent-assisted: "Based on your portfolio's current risk profile, I'd suggest setting max position size to 15% and max sector exposure to 25%"

### 36c: Monitoring tab — toggles for features that don't exist

- **Real-time Monitoring** toggle (off) — what does this monitor? Where do alerts go? Not connected to any backend service.
- **Daily Risk Reports** toggle (on) — we don't actually send daily risk reports. No email/notification integration exists.
- **Monitoring Frequency: Hourly** dropdown — frequency of what? Nothing is actually polling or monitoring.
- **Compliance Status** card shows "No compliance rules configured" — the compliance system doesn't exist.

### 36d: Compliance tab — empty, duplicate of the Monitoring sub-card

A separate "Compliance" tab exists alongside the "Compliance Status" card already visible on the Monitoring tab. Both are empty placeholders with "No compliance rules configured."

### 36e: Alerts tab — mixing config with monitoring with no real functionality

The Alerts tab conflates alert configuration (what triggers an alert) with alert display (active alerts) with alert history. None of these are connected to a real alerting backend.

### 36f: Settings & Privacy section — non-functional security theater

- **Two-Factor Authentication** — not implemented, toggle does nothing
- **End-to-End Encryption** — unclear what this means for a portfolio app, not implemented
- **Auto Logout Timer** — not connected to session management
- **Data Retention** — "30 days / 90 days / 1 year" selector with no backend enforcement. Potentially confusing — users might think changing this deletes their data.
- **Sync Frequency** — should be automatic on login, not a user-configurable setting

**Overall assessment:**

This entire settings page is ~80% placeholder UI. The only real functionality is the Risk Limits tab (which does persist to the DB via `set_risk_profile`). Everything else — monitoring, compliance, alerts, privacy settings — creates the appearance of features that don't exist, which damages trust.

**Fix approach:**
1. **Fix the metrics bug** (36a) — one-liner, highest priority
2. **Strip placeholder tabs**: Remove Monitoring, Compliance, and Alerts tabs until real functionality exists. An honest "Risk Limits" page is better than a fake "Risk Management Suite."
3. **Remove fake security settings**: 2FA, E2E encryption, auto-logout, data retention — none are real. Remove them. Add them back when implemented.
4. **Remove Sync Frequency**: Auto-sync on login instead. Don't expose plumbing as a user setting.
5. **Keep Risk Limits**: This tab works and is useful. Enhance with agent-guided suggestions.
6. **Rename the page**: "Risk Management Settings" → "Risk Limits" to match what it actually does.

---

## Issue 37: "Refresh Analysis" error state — blue doesn't match color scheme + cards shouldn't crash from client-side state

**Severity:** Low (visual) / Medium (principle)
**Type:** Visual polish + Error handling philosophy
**Page:** Any card that shows "No data" / "Refresh Analysis" after a client-side state change

**Visual issue:** When a card crashes to the empty/error state (e.g., Asset Allocation after clicking a period tab — Issue 13), the "Refresh Analysis" button and surrounding empty state use a blue color that feels off-brand. The rest of the dashboard uses emerald/green for positive actions, amber for warnings, and neutral grays for secondary UI. The blue stands out as mismatched.

**Deeper principle:** Cards should never crash to an error state from a client-side interaction like clicking a tab or changing a period selector. Error states should be reserved for actual backend failures (API down, network error, auth expired). When a user clicks a UI control:
- **Loading state** (spinner) → if fetching new data
- **Stale data** (keep showing current data, dim it) → if the new fetch hasn't returned yet
- **Graceful empty** → only if the backend genuinely has no data for that query

Currently, several cards collapse to the "No Data" error state because of React Query cache misses on new query keys (Issue 13, Issue 22), not because of actual backend failures. The fix is to use `keepPreviousData: true` (TanStack Query v5: `placeholderData: keepPreviousData`) so the existing data stays visible while the new query loads.

**Key files:**
- Components that render "No Data" / "Refresh Analysis": `AssetAllocationContainer.tsx`, `RiskMetricsContainer.tsx`, `PerformanceViewContainer.tsx`
- Error/empty state styling — grep for "Refresh Analysis" button styling across these containers
- TanStack Query config — `useDataSource.ts` or individual hooks where `keepPreviousData` could be added

**Fix approach:**
1. **Color**: Align the error state button with the dashboard palette — use neutral gray or the existing emerald action color, not blue
2. **Prevent client-side crashes**: Add `placeholderData: keepPreviousData` to hooks where query keys change from user interaction (period selectors, benchmark selectors)
3. **Reserve error states for real errors**: Only show "Refresh Analysis" when the backend actually returns an error, not when cached data is missing

---

## Issue 38: Account Connections — permissions are hardcoded, not from providers

**Severity:** Medium (misleading UI)
**Type:** Placeholder data
**Page:** Settings → Account Connections

**What happens:**
Each connected account card shows permission badges like "read positions", "read transactions", "read balances". These appear to reflect what the provider granted, but they're entirely hardcoded:

| Source | Permissions shown | Source of data |
|--------|------------------|----------------|
| Plaid | read_positions, read_transactions, read_balances | Hardcoded fallback (line 668) — `conn.permissions` field doesn't exist in API response |
| SnapTrade | read_positions, read_transactions | Hardcoded (line 706) — never fetched from SnapTrade API |

The container even has a TODO comment (line 45): `permissions?: string[] // ❌ TODO: Add permissions field to connections response`

**Why this matters:**
- Users see "read_positions" as a real permission grant — it's not
- SnapTrade actually does support `trade` capabilities for some brokerages, but the UI never reflects this
- If a provider connection loses access to transactions (e.g., Plaid re-auth needed), the badges still show "read_transactions" as if everything is fine

**Key files:**
- `frontend/packages/ui/src/components/settings/AccountConnectionsContainer.tsx` — lines 668, 706 (hardcoded permissions)
- `frontend/packages/ui/src/components/settings/AccountConnections.tsx` — lines 447-458 (renders permission badges)

**Fix approach:**
1. **Option A (quick):** Remove permission badges entirely until real data exists. An honest "Connected" status is better than fake capability badges.
2. **Option B (proper):** Add `permissions` field to the Plaid connections API response (from `plaid.Item.get()` → `billed_products`). For SnapTrade, query the authorization's granted permissions. Display what's actually granted.
3. **Option C (hybrid):** Show provider-level capabilities (Plaid = read-only always, SnapTrade = read-only or read+trade depending on brokerage) rather than pretending to have per-connection granularity.

---

## Design Note F: Overall visual design is clean and professional

**Type:** Positive feedback
**Page:** All pages

The user's overall impression of the visual design is positive — clean, professional look with good information density. No major complaints about colors, typography, spacing, or card styling. The premium/glass-tinted card style works well.

The issues documented above are primarily about **content, wiring, and information architecture** — not visual design. The foundation is solid; the work is in making the content behind the clean UI match its polish.

---

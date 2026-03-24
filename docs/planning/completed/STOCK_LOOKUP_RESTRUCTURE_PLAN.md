# Stock Risk Lookup — Decision-Oriented Restructure

## Context
The Stock Risk Lookup page is currently organized by data category (7 tabs: Overview, Risk Factors, Technicals, Fundamentals, Peer Comparison, Portfolio Fit, Price Chart). This is a data dump — an investor evaluating a stock to buy/sell thinks in terms of decisions, not data buckets. The user likes the current look and feel but wants the information architecture restructured to align with how an investor/analyst/PM actually evaluates a stock.

Additionally, the price chart should be always visible (not buried in a tab) since it's the most instinctive thing to look at when pulling up a stock.

## Target Layout

**Always-visible top section (above tabs):**
1. Stock header — ticker, name, price, change, market cap, risk badge (keep as-is)
2. Compact price chart (~160px, price line only, no volume) — extracted from PriceChartTab
3. Verdict strip — Buy/Hold/Sell recommendation + 1-line rationale + target price (from `selectedStock.analysis`). **Note:** Backend currently returns synthetic defaults (`'Analysis not available'`, targetPrice=0, confidence=50). The VerdictStrip must be **gated** — only render when `analysis.summary !== 'Analysis not available'` AND `analysis.targetPrice > 0`. Show nothing (not even a placeholder) when data is synthetic. Real analyst-consensus wiring is a separate future task.

**4 decision-oriented tabs (down from 7):**
1. **"Snapshot"** — Merge Overview + Fundamentals
2. **"Risks & Signals"** — Merge Risk Factors + Technicals
3. **"vs Peers"** — PeerComparisonTab (keep as-is)
4. **"Portfolio Impact"** — PortfolioFitTab (keep as-is)

## Implementation Steps

### Step 1: Create `CompactPriceChart.tsx` (~45 lines)
**Path:** `frontend/packages/ui/src/components/portfolio/stock-lookup/CompactPriceChart.tsx`

Extract price-only chart from `PriceChartTab.tsx` (lines 30-66):
- recharts `AreaChart` with `Area` for price data
- `ChartContainer` with `height={160}`, `minHeight={120}`
- Same gradient + stroke styling for visual continuity
- No volume chart, no header text
- Gradient ID: `"compactPriceGradient"` (avoid collision)

Props: `{ chartData: Array<{date, price, volume}> }`

### Step 2: Create `VerdictStrip.tsx` (~55 lines)
**Path:** `frontend/packages/ui/src/components/portfolio/stock-lookup/VerdictStrip.tsx`

New component using `InsightBanner` block pattern (`frontend/packages/ui/src/components/blocks/insight-banner.tsx`):
- Color: Buy=emerald, Hold=amber, Sell=red
- Title: recommendation text + confidence badge
- Subtitle: `analysis.summary` (1-line rationale)
- Right side: target price display
- Icons: TrendingUp (Buy), Minus (Hold), TrendingDown (Sell)

Props: `{ analysis: { summary, recommendation, targetPrice, confidence } }`

**Gating logic:** Only render if `analysis.summary !== 'Analysis not available'` AND `analysis.targetPrice > 0`. Return `null` otherwise. This prevents showing synthetic/mock data as authoritative.

### Step 3: Create `SnapshotTab.tsx` (~90 lines)
**Path:** `frontend/packages/ui/src/components/portfolio/stock-lookup/SnapshotTab.tsx`

Merges Overview + Fundamentals into a glanceable view:

**Section A — Two-column grid:**
- Left: Valuation card (P/E, P/B) with "Cheap/Fair/Expensive" label (thresholds from FundamentalsTab line 90-94)
- Right: Quality card (ROE, margins, D/E) with financial health score (copy `financialHealthScores` useMemo from FundamentalsTab lines 19-73)

**Section B — Compact 4-column risk metric row:**
- VaR95, Beta, Volatility, Sharpe as `grid-cols-4` compact stats (from OverviewTab lines 21-55, flattened from 2x2 to 1x4)

Props: `{ selectedStock: SelectedStockData }`

### Step 4: Create `RisksSignalsTab.tsx` (~60 lines)
**Path:** `frontend/packages/ui/src/components/portfolio/stock-lookup/RisksSignalsTab.tsx`

Merges Technicals + Risk Factors:

**Section A — "Technical Signals" (near-term):**
- RSI + MACD cards, support/resistance, Bollinger bands (from TechnicalsTab.tsx)

**Section B — "Factor Exposures" (structural):**
- Factor exposure bars with risk contribution (from inline Risk Factors JSX in StockLookup.tsx lines 298-343)
- **Must preserve the no-data fallback:** When `riskFactors` is empty (no `factorSummary.beta`), show the existing "Factor analysis not available for this stock" empty state from StockLookup.tsx line 299

Props: `{ selectedStock: SelectedStockData, riskFactors: RiskFactor[] }`

### Step 5: Update `StockLookup.tsx` — core restructure
**Path:** `frontend/packages/ui/src/components/portfolio/StockLookup.tsx`

Changes:
- **Imports:** Add CompactPriceChart, VerdictStrip, SnapshotTab, RisksSignalsTab. Remove OverviewTab, FundamentalsTab, TechnicalsTab, PriceChartTab.
- **Header zone** (after stock header div, before `<Tabs>`): Insert CompactPriceChart + VerdictStrip
- **TabsList:** `grid-cols-7` → `grid-cols-4`. Tab values must match exactly:
  - `<TabsTrigger value="snapshot">` → `<TabsContent value="snapshot">`
  - `<TabsTrigger value="risks-signals">` → `<TabsContent value="risks-signals">`
  - `<TabsTrigger value="peer-comparison">` → keeps existing value in PeerComparisonTab.tsx
  - `<TabsTrigger value="portfolio-fit">` → keeps existing value in PortfolioFitTab.tsx
- **Tab contents:** 7 blocks → 4 blocks (SnapshotTab, RisksSignalsTab, PeerComparisonTab, PortfolioFitTab)
- **Remove** inline Risk Factors JSX (lines 298-343) — moves to RisksSignalsTab
- **Default tab:** `useState("overview")` → `useState("snapshot")`
- Net: ~385 lines → ~310 lines

### Step 6: Update barrel export `stock-lookup/index.ts`
Add: CompactPriceChart, VerdictStrip, SnapshotTab, RisksSignalsTab
Remove: OverviewTab, FundamentalsTab, TechnicalsTab, PriceChartTab

### Step 7: Delete obsolete files
- `OverviewTab.tsx` (absorbed into SnapshotTab)
- `FundamentalsTab.tsx` (absorbed into SnapshotTab)
- `TechnicalsTab.tsx` (absorbed into RisksSignalsTab)
- `PriceChartTab.tsx` (replaced by CompactPriceChart)

## Files — No Changes Needed
- `StockLookupContainer.tsx` — no data/hook changes
- `PeerComparisonTab.tsx` — used as-is
- `PortfolioFitTab.tsx` — used as-is
- `helpers.ts` — still used
- `types.ts` — no changes (selectedStock shape unchanged)

## File Change Summary

| File | Action |
|------|--------|
| `stock-lookup/CompactPriceChart.tsx` | Create (~45 lines) |
| `stock-lookup/VerdictStrip.tsx` | Create (~55 lines) |
| `stock-lookup/SnapshotTab.tsx` | Create (~90 lines) |
| `stock-lookup/RisksSignalsTab.tsx` | Create (~60 lines) |
| `StockLookup.tsx` | Edit (restructure tabs + header) |
| `stock-lookup/index.ts` | Edit (update exports) |
| `stock-lookup/OverviewTab.tsx` | Delete |
| `stock-lookup/FundamentalsTab.tsx` | Delete |
| `stock-lookup/TechnicalsTab.tsx` | Delete |
| `stock-lookup/PriceChartTab.tsx` | Delete |

## Verification
1. Load `localhost:3000` → Research → Stock Lookup
2. Search/select a stock (e.g., AAPL)
3. Verify always-visible section: stock header + compact price chart. Verdict strip should NOT appear for most stocks (backend returns synthetic defaults). It will only render when real analyst data is wired in the future.
4. Verify 4 tabs render correctly:
   - Snapshot: valuation + quality + compact risk row
   - Risks & Signals: technicals on top, factor exposures below
   - vs Peers: peer comparison table (unchanged)
   - Portfolio Impact: position sizing + what-if (unchanged)
5. Verify no duplicate data across sections
6. Verify search/selection still works (loading states, dropdown dismiss)

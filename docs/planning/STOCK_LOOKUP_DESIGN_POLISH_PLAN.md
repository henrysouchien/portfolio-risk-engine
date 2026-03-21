# Stock Lookup — Design Polish Pass

## Context
The Stock Lookup restructure (7→4 tabs, chart in header) is functionally complete. Now the page needs a design tightening pass — the stock header card is oversized, the chart axes are cluttered, and spacing can be compressed. The goal is a denser, more professional feel that matches how a Bloomberg terminal or Koyfin presents stock data — information-dense without feeling cramped.

## Issues & Fixes

### 1. Compact the stock header card
**File:** `frontend/packages/ui/src/components/portfolio/StockLookup.tsx` (lines 246-267)

**Current:** `p-4`, `mb-3`, `text-xl` ticker, `text-2xl` price, badge on its own line with `mt-2`
**Fix:**
- Reduce padding: `p-4` → `px-4 py-3`
- Inline the risk badge next to the ticker (same row): wrap the `<h2>` and `<Badge>` in a `flex items-center gap-2` div, remove `mt-2` from Badge. This requires minor JSX restructure — moving the Badge from below the company name to beside the ticker.
- Reduce price size: `text-2xl` → `text-xl`
- Remove `mb-3` from inner flex (no children below it in the card)

### 2. Clean up chart Y-axis
**File:** `frontend/packages/ui/src/components/portfolio/stock-lookup/CompactPriceChart.tsx` (line 49)

**Current:** `formatCurrency(value, { compact: true })` → shows `$279.00` for stock prices (compact only kicks in at $1K+)
**Fix:** Use existing `formatCurrency` with `decimals: 0`: `(value: number) => formatCurrency(value, { decimals: 0 })` — shows `$279`, `$270`, etc. This preserves thousand separators for 4-digit prices and handles negatives correctly via Intl.NumberFormat.

### 3. Reduce chart X-axis clutter
**File:** `frontend/packages/ui/src/components/portfolio/stock-lookup/CompactPriceChart.tsx` (lines 41-45)

**Current:** No `interval` or `tickCount` — recharts shows too many date labels
**Fix:** Add `interval="preserveStartEnd"` and `minTickGap={50}` to XAxis. Shows fewer evenly-spaced labels.

### 4. Reduce chart wrapper padding
**File:** `frontend/packages/ui/src/components/portfolio/stock-lookup/CompactPriceChart.tsx` (line 26)

**Current:** `rounded-lg border bg-card p-4`
**Fix:** `rounded-lg border bg-card px-3 py-2` — tighter padding, especially vertical

### 5. Tighten header-to-chart-to-tabs spacing
**File:** `frontend/packages/ui/src/components/portfolio/StockLookup.tsx` (line 245)

**Current:** `<div className="mb-6 space-y-4">` — 24px bottom, 16px gaps
**Fix:** `<div className="mb-4 space-y-3">` — 16px bottom, 12px gaps

## Files Changed

| File | Changes |
|------|---------|
| `StockLookup.tsx` | Header card padding/sizing, badge inline, section spacing |
| `CompactPriceChart.tsx` | Y-axis formatter, X-axis interval, wrapper padding |

## Verification
1. Load Stock Lookup, select AAPL
2. Header should feel tighter — ticker + badge on same line, smaller price, less padding
3. Chart Y-axis: `$243`, `$252`, `$261` etc. (no decimals)
4. Chart X-axis: ~5-6 date labels, well-spaced
5. Spacing between header→chart→tabs should feel snugger
6. All tabs still render correctly

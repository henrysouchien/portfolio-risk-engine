# Stock Lookup — Peer-Relative Valuation Bars (Part A)

## Context
The Snapshot tab's valuation bars (P/E, P/B) use hardcoded scales (P/E max=40, P/B max=10) and hardcoded thresholds for the "Cheap/Fair/Expensive" label (P/E <15 / 15-25 / >25). These are meaningless without context — a P/E of 30 is cheap for a high-growth tech stock but expensive for a utility.

This is Part A: peer-relative bars using data already loaded. Part B (sector average reference line) requires backend-to-frontend wiring and will be a separate plan.

## Data Already Available
Peer comparison data is already loaded via `usePeerComparison()` in StockLookupContainer. The `comparison` array contains rows keyed by `metric_key` (e.g., `priceToEarningsRatioTTM`, `priceToBookRatioTTM`) with numeric values per ticker. This data is already passed to StockLookup as `peerComparison` — it just needs to be threaded to SnapshotTab.

## Implementation

### Step 1: Thread peerComparison to SnapshotTab
**File:** `frontend/packages/ui/src/components/portfolio/StockLookup.tsx` (line 285)

Change:
```tsx
<SnapshotTab selectedStock={selectedStock} />
```
To:
```tsx
<SnapshotTab selectedStock={selectedStock} peerComparison={peerComparison} />
```

### Step 2: Update SnapshotTab props
**File:** `frontend/packages/ui/src/components/portfolio/stock-lookup/SnapshotTab.tsx` (line 8)

Add `peerComparison` to the local `SnapshotTabProps` interface:
```typescript
interface SnapshotTabProps {
  selectedStock: SelectedStockData
  peerComparison?: PeerComparisonData | null
}
```

Import `PeerComparisonData` from `./types`.

### Step 3: Extract peer ranges
**File:** `frontend/packages/ui/src/components/portfolio/stock-lookup/SnapshotTab.tsx`

Add a `useMemo` that extracts P/E and P/B data from peer comparison rows. Returns **two separate structures** for bar rendering and label ranking:

```typescript
const peerMetrics = useMemo(() => {
  if (!peerComparison?.comparison?.length) return null
  const extract = (metricKey: string) => {
    const row = peerComparison.comparison.find(r => r.metric_key === metricKey)
    if (!row) return null

    // Peer values only (for bar range)
    const peerValues = peerComparison.peers
      .map(t => toNumericValue(row[t]))
      .filter((v): v is number => v !== null && v > 0)
    peerValues.sort((a, b) => a - b)

    // Subject value (for positioning + ranking)
    const subjectValue = toNumericValue(row[peerComparison.subject])

    // All positive values (for ranking — includes subject)
    const allPositive = subjectValue !== null && subjectValue > 0
      ? [...peerValues, subjectValue].sort((a, b) => a - b)
      : peerValues

    // Bar data: needs ≥2 peers, positive subject, non-zero range
    const barData = (peerValues.length >= 2 && subjectValue !== null && subjectValue > 0 && peerValues[0] !== peerValues[peerValues.length - 1])
      ? { min: peerValues[0], max: peerValues[peerValues.length - 1], subjectValue }
      : null

    // Rank data: needs positive subject + ≥2 distinct positive values
    const uniquePositive = [...new Set(allPositive)]
    const rankData = (subjectValue !== null && subjectValue > 0 && uniquePositive.length >= 2)
      ? { subjectValue, allValues: allPositive, uniqueValues: uniquePositive }
      : null

    return { barData, rankData }
  }
  return { pe: extract('priceToEarningsRatioTTM'), pb: extract('priceToBookRatioTTM') }
}, [peerComparison])
```

Use `toNumericValue()` from `./helpers`. Filter out non-positive values (loss-making companies should not skew ranges).

Key: `barData` and `rankData` have **independent eligibility**. Label can show peer-relative rank even when bar falls back to hardcoded (e.g., all peers identical but subject differs).

### Step 4: Replace hardcoded bars with peer-relative positioning
**File:** `frontend/packages/ui/src/components/portfolio/stock-lookup/SnapshotTab.tsx`

For each metric (P/E, P/B), replace the `GradientProgress` with a range bar:

**Important**: Use the subject's value from the comparison row (`row[peerComparison.subject]`), NOT from `selectedStock.fundamentals`. This ensures the Snapshot card agrees with the vs Peers table.

**When peer-relative bar renders** (uses `peerMetrics?.pe?.barData`):
- barData is non-null (≥2 positive peer values, positive subject, min !== max)

Bar rendering:
- Full bar represents peer min → peer max
- Stock position: `((subjectValue - min) / (max - min)) * 100`, clamped 0-100
- Show min/max labels at bar ends (small text, e.g. "15.2x" and "35.6x")
- Use a marker/dot for the subject's position
- Stock value outside peer range → clamp to 0% or 100% (outlier indicator)

**Bar fallback** (when `barData` is null → use hardcoded bar):
- `peerComparison` is null/undefined
- No metric row found
- Fewer than 2 positive peer values
- Subject value null/missing/non-positive
- `min === max` (can't position within zero-width range)

Fallback bar: current hardcoded (P/E / 40 * 100, P/B * 10)

**Label fallback** (when `rankData` is null → show "No data"):
- Subject value null/missing/non-positive → "No data"
- Fewer than 2 distinct positive values → "No data"
- No hardcoded thresholds as fallback — the old P/E <15/>25 thresholds are removed entirely. The badge is either peer-relative or "No data".

**Note on display text vs bar source**: The displayed P/E/P/B text (e.g. "31.1x") continues to come from `selectedStock.fundamentals`. The bar position and label use the comparison-row value. These are typically very close but may differ slightly due to data source timing. Acceptable trade-off.

### Step 5: Replace hardcoded "Cheap/Fair/Expensive" with peer-relative label
**File:** `frontend/packages/ui/src/components/portfolio/stock-lookup/SnapshotTab.tsx`

Replace `getValuationLabel(peRatio)` with a peer-aware version using `peerMetrics?.pe?.rankData`.

**Peer-relative label renders when** (uses `peerMetrics?.pe?.rankData`):
- rankData is non-null (positive subject + ≥2 distinct positive values in allValues)
- Note: this is less strict than bar — ranking doesn't require a non-zero peer range. If all peers are 10x and subject is 30x, uniqueValues = [10, 30], subject ranks 2/2 → "Expensive"

**Label logic:**
- Dense ranking: ties get the same rank (e.g., [15, 15, 20, 25, 30, 31] → unique sorted [15, 20, 25, 30, 31], subject at value 31 → denseRank 5)
- Percentile: `(denseRank - 1) / (uniqueValueCount - 1)`. `uniqueValueCount` = number of distinct positive P/E values, `denseRank` = subject's 1-indexed position in the sorted unique list
- Percentile < 0.33 → "Cheap", < 0.67 → "Fair", else "Expensive"
- This works for any count ≥ 2

**Label fallback** (when peer-relative label does NOT render):
- rankData is null → show "No data" badge (existing style from `valuationToneClasses`)

## Files Changed

| File | Changes |
|------|---------|
| `SnapshotTab.tsx` | Add peerComparison prop, peer range extraction useMemo, peer-relative bar rendering, peer-relative labeling with edge case handling |
| `StockLookup.tsx` | Pass peerComparison to SnapshotTab |

Only 2 files. No new hooks, no backend changes, no new packages.

## Verification
1. Load Stock Lookup, select AAPL
2. Snapshot Valuation card should show:
   - P/E bar with AAPL positioned within peer range, min/max labels at ends
   - P/B bar same
   - "Expensive" or "Fair" badge based on peer rank, not hardcoded P/E >25
3. Select a different stock (e.g., MSFT, JPM) — badge should reflect peer-relative position
4. If peer data hasn't loaded yet (brief loading window), bars should show old hardcoded behavior
5. Edge cases: subject outside peer range → clamped to 0% or 100% with outlier visual
6. Edge case: all peers identical P/E → bar falls back to hardcoded, but label still shows ranking (e.g. "Expensive" if subject is higher)
7. vs Peers tab still works (we only read peerComparison, don't modify it)
8. No regressions on other tabs

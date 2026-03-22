# Add P/FCF Metric to Stock Lookup Valuation Card

## Context
The Snapshot valuation card currently shows P/E and P/B. Adding P/FCF (Price to Free Cash Flow) gives investors a cash-flow-based valuation lens — less prone to accounting distortions than earnings-based P/E. FMP's `ratios_ttm` response already includes `priceToFreeCashFlowRatioTTM`, so no new API calls needed.

## Implementation

### Step 1: Backend — Extract P/FCF from ratios
**File:** `services/stock_service.py` — `enrich_stock_data()` ratio_field_map (~line 441)

Add to the ratio field map:
```python
"price_to_fcf": ("priceToFreeCashFlowRatioTTM",),
```

### Step 2: Add P/FCF to peer comparison metrics
**File:** `fmp/tools/peers.py`

Add to `DEFAULT_PEER_METRICS` list:
```python
"priceToFreeCashFlowRatioTTM",
```

Add to `METRIC_LABELS` dict:
```python
"priceToFreeCashFlowRatioTTM": "P/FCF",
```

Add to `LOWER_IS_BETTER_METRICS` in `frontend/packages/ui/src/components/portfolio/stock-lookup/helpers.ts` (P/FCF lower = cheaper, like P/E).

### Step 2b: Guard negative valuation multiples in peer comparison ranking
**File:** `frontend/packages/ui/src/components/portfolio/stock-lookup/PeerComparisonTab.tsx`

The peer table ranks values and labels best/worst. For *valuation multiples* (P/E, P/B, P/S, P/FCF, PEG, EV/EBITDA), a non-positive value is economically meaningless for ranking — negative P/E doesn't mean "cheapest."

Define a new set `NON_POSITIVE_EXCLUDES_RANKING` in `helpers.ts`:
```typescript
export const NON_POSITIVE_EXCLUDES_RANKING = new Set([
  "priceToEarningsRatioTTM",
  "priceToBookRatioTTM",
  "priceToSalesRatioTTM",
  "priceToFreeCashFlowRatioTTM",
  "priceToEarningsGrowthRatioTTM",
  "enterpriseValueMultipleTTM",
])
```

Note: `debtToEquityRatioTTM` is intentionally excluded — D/E of 0 is genuinely best (no debt).

In `PeerComparisonTab.tsx`, when computing rank for metrics in `NON_POSITIVE_EXCLUDES_RANKING`, exclude non-positive values from the sorted set. Excluded tickers get no rank badge. The raw value still displays in the cell (e.g., "-16.1x") — only the ranking is suppressed.

### Step 3: Frontend types — Add priceToFcf
**File:** `frontend/packages/ui/src/components/portfolio/stock-lookup/types.ts`

Add to the fundamentals object in the selectedStock type:
```typescript
priceToFcf?: number
```

### Step 4: Frontend container — Map price_to_fcf
**File:** `frontend/packages/ui/src/components/dashboard/views/modern/StockLookupContainer.tsx`

Add to the fundamentals section of `transformedStockData`:
```typescript
priceToFcf: toOptionalNumber(fundamentalsRecord.price_to_fcf) ?? toOptionalNumber(stockRecord.price_to_fcf),
```

### Step 5: SnapshotTab — Add P/FCF row to valuation card
**File:** `frontend/packages/ui/src/components/portfolio/stock-lookup/SnapshotTab.tsx`

Add a third metric row below P/B, following the same pattern:
- StatPair label: "P/FCF"
- Value: `formatMultiple(fundamentals?.priceToFcf)`
- PeerRelativeRangeBar with `peerMetrics` extraction for `priceToFreeCashFlowRatioTTM`
- Same non-positive handling (N/A + "Negative free cash flow" when <= 0) — consistent with peer range extraction which uses `> 0`
- Tooltip: "Price per dollar of free cash flow. Measures what the market pays for the company's cash generation."

### Step 6: Add P/FCF to peer range extraction
**File:** `frontend/packages/ui/src/components/portfolio/stock-lookup/SnapshotTab.tsx`

Update `peerMetrics` useMemo to extract a third metric:
```typescript
return {
  pe: extract("priceToEarningsRatioTTM"),
  pb: extract("priceToBookRatioTTM"),
  pFcf: extract("priceToFreeCashFlowRatioTTM"),
}
```

Update the `PeerMetrics` interface to include `pFcf`.

## Files Changed

| File | Changes |
|------|---------|
| `services/stock_service.py` | Add `price_to_fcf` to ratio_field_map (1 line) |
| `fmp/tools/peers.py` | Add to DEFAULT_PEER_METRICS + METRIC_LABELS (2 lines) |
| `frontend/.../types.ts` | Add `priceToFcf` to fundamentals type (1 line) |
| `frontend/.../StockLookupContainer.tsx` | Map `price_to_fcf` → `priceToFcf` (1 line) |
| `frontend/.../SnapshotTab.tsx` | Add P/FCF row + peer extraction + negative handling |
| `frontend/.../helpers.ts` | Add `priceToFreeCashFlowRatioTTM` to LOWER_IS_BETTER_METRICS |
| `frontend/.../PeerComparisonTab.tsx` | Guard non-positive values from ranking for `NON_POSITIVE_EXCLUDES_RANKING` metrics only |
| `frontend/.../helpers.ts` | Add `NON_POSITIVE_EXCLUDES_RANKING` set |
| `tests/mcp_tools/test_peers.py` | Update metric count assertion (12 → 13), add P/FCF to peer fixtures |
| `tests/services/test_stock_service_provider_registry.py` | Add `price_to_fcf` to enrichment assertions |

## Verification
1. Load Stock Lookup → AAPL → Snapshot tab should show P/E, P/B, and P/FCF with peer range bars
2. P/FCF value should be a positive multiple for AAPL (exact value varies with market data)
3. vs Peers tab should include P/FCF row in the comparison table
4. Test with MSCI — if FCF is negative, should show "N/A — Negative free cash flow"
5. Hover tooltip on P/FCF should show description
6. vs Peers tab: verify negative P/FCF values do NOT rank as "Best" for any peer

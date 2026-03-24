# Replace TTM PEG with Forward PEG in Peer Comparison

## Context

The peer comparison table's PEG ratio (`priceToEarningsGrowthRatioTTM`) is backward-looking. FMP already provides `forwardPriceToEarningsGrowthRatioTTM` in `ratios_ttm` (already fetched). Just swap the metric key.

**Scope**: Peer comparison only. The stock fundamentals tool (`fmp/tools/stock_fundamentals.py`) still uses TTM PEG — that's a separate concern, out of scope for this change.

## Verified

- `forwardPriceToEarningsGrowthRatioTTM` exists in `ratios_ttm` (AAPL: 3.20 vs TTM PEG: 5.28)
- No custom computation needed — FMP provides it
- Already fetched — `ratios_ttm` is the primary endpoint

## Changes

### 1. Backend: `fmp/tools/peers.py`

In `DEFAULT_PEER_METRICS`:
```python
# Change:
"priceToEarningsGrowthRatioTTM",
# To:
"forwardPriceToEarningsGrowthRatioTTM",
```

In `METRIC_LABELS`:
```python
# Change:
"priceToEarningsGrowthRatioTTM": "PEG Ratio",
# To:
"forwardPriceToEarningsGrowthRatioTTM": "PEG (Fwd)",
```

### 2. Frontend: `helpers.ts`

In `LOWER_IS_BETTER_METRICS`:
- Remove `priceToEarningsGrowthRatioTTM`
- Add `forwardPriceToEarningsGrowthRatioTTM`

In `NON_POSITIVE_EXCLUDES_RANKING`:
- Remove `priceToEarningsGrowthRatioTTM`
- Add `forwardPriceToEarningsGrowthRatioTTM`

### 3. Frontend: `PeerComparisonTab.tsx`

In `METRIC_GROUP`:
- Remove `priceToEarningsGrowthRatioTTM: "Valuation"`
- Add `forwardPriceToEarningsGrowthRatioTTM: "Valuation"`

### 4. Tests: `tests/mcp_tools/test_peers.py`

- Update mock data references from `priceToEarningsGrowthRatioTTM` to `forwardPriceToEarningsGrowthRatioTTM`
- Add explicit assertion: `forwardPriceToEarningsGrowthRatioTTM` IN `DEFAULT_PEER_METRICS`
- Add explicit assertion: `priceToEarningsGrowthRatioTTM` NOT IN `DEFAULT_PEER_METRICS`
- Add assertion that label is `"PEG (Fwd)"` in `METRIC_LABELS`
- Fix stale assertions from prior Net Debt/EBITDA swap: update `debtToEquityRatioTTM` → `netDebtToEBITDATTM` and `"Debt/Equity"` → `"Net Debt/EBITDA"` in mock data and summary label assertions

## Files to Modify

| File | Change |
|------|--------|
| `fmp/tools/peers.py` | Swap metric key + label |
| `frontend/.../helpers.ts` | Swap in LOWER_IS_BETTER + NON_POSITIVE sets |
| `frontend/.../PeerComparisonTab.tsx` | Swap in METRIC_GROUP |
| `tests/mcp_tools/test_peers.py` | Update mock data + assertions |

### 5. Frontend test: `helpers.test.ts`

Add assertions:
- `forwardPriceToEarningsGrowthRatioTTM` is in `LOWER_IS_BETTER_METRICS`
- `forwardPriceToEarningsGrowthRatioTTM` is in `NON_POSITIVE_EXCLUDES_RANKING`
- `priceToEarningsGrowthRatioTTM` is NOT in either set

## Verification

1. `pytest tests/mcp_tools/test_peers.py -q` — passes
2. Frontend tests pass for helpers
3. Browser: vs Peers → "PEG (Fwd)" shows forward PEG values
4. Ranking correct (lower = better, non-positive excluded)

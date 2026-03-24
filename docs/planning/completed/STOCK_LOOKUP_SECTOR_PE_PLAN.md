# Stock Lookup — Sector Average P/E on Valuation Bar (Part B)

## Context
Part A added peer-relative valuation bars. Part B adds a sector average P/E marker to give broader market context. Instead of building a whole new frontend→backend pipeline (resolver, hook, catalog, descriptor), we piggyback on the existing stock analysis response — the backend already fetches the stock's sector from FMP, so it can also fetch the sector average P/E in the same enrichment call.

## Approach: Enrich stock analysis response with sector_avg_pe

### Step 1: Backend — Add sector PE to stock enrichment
**File:** `services/stock_service.py` — `enrich_stock_data()` method (around line 354-361)

After extracting `sector` from the FMP profile, fetch `sector_pe_snapshot` and find the matching sector's P/E:

```python
# After sector extraction (line 356)
if sector is not None:
    data["sector"] = str(sector)
    # Fetch sector average P/E
    try:
        from fmp.tools.market import _last_trading_day
        snapshot_date = _last_trading_day()
        sector_pe_df = self.fmp_client.fetch("sector_pe_snapshot", date=snapshot_date)
        # fmp_client.fetch() returns a DataFrame-like object — convert to records
        if sector_pe_df is not None and hasattr(sector_pe_df, 'to_dict'):
            rows = sector_pe_df.to_dict("records") if hasattr(sector_pe_df, 'to_dict') else []
        elif isinstance(sector_pe_df, list):
            rows = sector_pe_df
        else:
            rows = []
        sector_lower = sector.strip().lower()
        for row in rows:
            if isinstance(row, dict) and str(row.get("sector", "")).strip().lower() == sector_lower:
                pe = row.get("pe") or row.get("peRatio")
                if pe is not None:
                    pe_float = parse_fmp_float(pe)  # already imported at stock_service.py:47
                    import math
                    if pe_float is not None and math.isfinite(pe_float) and pe_float > 0:
                        data["sector_avg_pe"] = pe_float
                break
    except Exception:
        logger.debug("Sector PE snapshot fetch failed for sector=%s", sector)
```

Notes:
- `self.fmp_client` is available via lazy property (line 92/104 of stock_service.py)
- `fmp_client.fetch()` returns DataFrame-like, not a raw list — handle both via `to_dict("records")` with list fallback
- `date` param uses `_last_trading_day()` from `fmp/tools/market.py` — handles weekends (not holidays, but this is the established pattern in the codebase and FMP returns closest available data)
- Sector matching uses case-insensitive `strip().lower()` (existing pattern from `fmp/tools/market.py:746`)
- PE field may be `pe` or `peRatio` (existing fallback pattern from `fmp/tools/market.py:972`)
- Cached 6 hours per endpoint definition, so negligible perf impact after first call

### Step 2: Frontend container — Map sector_avg_pe to selectedStock
**File:** `frontend/packages/ui/src/components/dashboard/views/modern/StockLookupContainer.tsx`

In the `transformedStockData` computation (around line 384-473), add:
```typescript
sectorAvgPE: toOptionalNumber(stockRecord.sector_avg_pe) ?? null,
```

### Step 3: Frontend types — Add sectorAvgPE to SelectedStockData
**File:** `frontend/packages/ui/src/components/portfolio/stock-lookup/types.ts`

Add `sectorAvgPE` to the inline `selectedStock` object type in the `StockLookupProps` interface (line 76 of types.ts — `SelectedStockData` is a type alias derived from this):
```typescript
sectorAvgPE?: number | null
```

### Step 4: SnapshotTab — Add sector average marker to P/E bar
**File:** `frontend/packages/ui/src/components/portfolio/stock-lookup/SnapshotTab.tsx`

When `selectedStock.sectorAvgPE` is available and `barData` exists:
- Calculate sector position: `((sectorAvgPE - min) / (max - min)) * 100`, clamped 0-100
- Render a small triangle/line marker on the bar at that position
- Label: "Sector" or "Sector avg" in small text below the marker
- If sectorAvgPE is null/undefined, don't show the marker (graceful degradation)

The marker should be visually distinct from the stock's dot — use a different shape (triangle vs dot) or color (muted gray vs the indigo bar color).

### Step 5: Update the valuation label to incorporate sector context
**File:** `frontend/packages/ui/src/components/portfolio/stock-lookup/SnapshotTab.tsx`

Optional enhancement: when both peer rankData AND sectorAvgPE are available, add a secondary signal. For example, if the peer-relative label says "Fair" but the stock's P/E is 50% above the sector average, the investor gets useful context. This could be a subtitle below the badge like "1.2x sector avg" — but only if both values are available.

Keep the primary badge driven by peer ranking (Part A logic unchanged).

## Files Changed

| File | Changes |
|------|---------|
| `services/stock_service.py` | Add sector_pe_snapshot fetch in `enrich_stock_data()` (~15 lines) |
| `StockLookupContainer.tsx` | Map `sector_avg_pe` to `sectorAvgPE` via `toOptionalNumber` (1 line) |
| `stock-lookup/types.ts` | Add `sectorAvgPE` field (1 line) |
| `stock-lookup/SnapshotTab.tsx` | Add sector marker on P/E bar + optional "vs sector" subtitle |
| `tests/services/test_stock_service_provider_registry.py` | Update FMP fetch sequence assertion: verify `sector_pe_snapshot` called with `date` kwarg, assert `data["sector_avg_pe"]` populated from mocked snapshot row, verify non-finite/negative values are excluded |

## Verification
1. Load Stock Lookup, select AAPL (Technology sector)
2. P/E bar should show sector average marker (triangle) positioned within the peer range
3. Marker should be labeled "Sector" or similar
4. Select a stock from a different sector (e.g., JPM — Financial Services) — sector marker should shift to reflect that sector's average P/E
5. If FMP sector PE fetch fails — no marker shown, no errors, bar works normally
6. Peer-relative bar and label still work correctly (Part A unchanged)

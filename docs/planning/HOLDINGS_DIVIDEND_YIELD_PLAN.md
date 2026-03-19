# Add Yield on Cost Column to Holdings View

## Context
User's portfolio is income-focused. The Holdings table has 7 columns (Symbol, Market Value, Weight, Total Return, Day Change, Volatility, Risk Score). There's room for a compact "YOC" column. The `Holding` interface already has a `dividend` field (hardcoded to `0`). The user wants **yield on cost** (annual dividend / their entry price), not market yield — it's the metric that matters for income investors.

## Approach
Piggyback on the existing FMP **profile** fetch in `enrich_positions_with_sectors()` — it already calls `fetch_batch_fmp_profile_metadata()` which returns `lastDiv` from the FMP profile endpoint. Extract `lastDiv` there, compute yield on cost as `(lastDiv / avgCost) * 100` using the position's entry price, and carry it through the enrichment merge + frontend pipeline.

**Key finding from Codex review**: FMP's `quote` endpoint does NOT return `lastDiv` — it's only on `profile`. The sector enrichment already fetches profile data, so we add `lastDiv` extraction there instead. The positions route merge whitelist at `routes/positions.py` line 378 must also be updated to include the new field.

## Files to Modify

### 1. Backend: `utils/ticker_resolver.py` — Include `lastDiv` in profile snapshot

In `_empty_profile_snapshot()` (line ~210), add `"last_div": None`.
In `_profile_snapshot_from_row()` (line ~219), add `"last_div": row.get("lastDiv")`.

This ensures `fetch_batch_fmp_profile_metadata()` returns `lastDiv` for every symbol.

### 2. Backend: `services/portfolio_service.py` — Extract `lastDiv` from profile fetch

**a)** In `_fetch_missing_profile_map()` (~line 1537), add `lastDiv` to the extracted fields:
```python
return {
    symbol: {
        "sector": ...,
        "company_name": ...,
        "last_div": (fetched_profiles.get(symbol) or {}).get("last_div"),  # NEW — already converted by ticker_resolver
    }
    for symbol in missing_symbols
}
```
(`_to_optional_float` already exists in `enrich_positions_with_market_data` — extract or duplicate a small helper.)

**b)** In `enrich_positions_with_sectors()` (~line 1487), in the `for position in positions` loop, look up the profile for the current position's symbol and compute yield on cost. Note: `profile` from the earlier symbol loop is NOT available here — must look up from `profile_map` per position:
```python
symbol = str(position.get("ticker", "")).strip().upper()
market_symbol = position_symbols.get(symbol, symbol)
profile = profile_map.get(market_symbol, {})
position["sector"] = sector_map.get(symbol)
if symbol in name_map:
    position["name"] = name_map[symbol]

# Yield on cost: lastDiv / entry_price (skip shorts)
direction = str(position.get("direction") or "").upper()
last_div = profile.get("last_div")
entry_price = position.get("entry_price")
if last_div and entry_price and entry_price > 0 and direction != "SHORT":
    position["dividend_yield"] = round((float(last_div) / float(entry_price)) * 100, 2)
else:
    position["dividend_yield"] = None
```
Uses `entry_price` (avg cost basis per share) instead of `current_price` — this gives yield on cost, not market yield. Skips SHORT positions to avoid misleading positive YOC.

**c)** Also need a small helper or inline float conversion for `lastDiv` since `_to_optional_float` is defined inside `enrich_positions_with_market_data`. Simplest: define a module-level `_safe_float()` or just inline the conversion.

### 3. Backend: `routes/positions.py` — Add to merge whitelist

At line ~372, the sector enrichment merge whitelist is `("sector", "name")`. Add `"dividend_yield"`:
```python
_merge_position_enrichment_fields(
    payload,
    sector_future.result(),
    ("sector", "name", "dividend_yield"),
)
```

### 4. Frontend type: `frontend/packages/chassis/src/types/index.ts`

Add `dividend_yield?: number | null;` to `PositionsMonitorPosition` interface (after `max_drawdown`, line ~145).

### 5. Frontend adapter: `frontend/packages/connectors/src/adapters/PositionsAdapter.ts`

- Add `dividendYield?: number;` to `PositionsHolding` interface (line ~27)
- In `normalizeHolding()` (line ~101), add: `dividendYield: toOptionalNumber(position.dividend_yield),`

### 6. Frontend holdings types: `frontend/packages/ui/src/components/portfolio/holdings/types.ts`

- Add `dividendYield?: number` to `PortfolioHolding` interface (line ~29)
- Change `dividend: number` → `dividendYield: number` in `Holding` interface (line ~52)
- Add `"dividendYield"` to `HoldingsSortField` union (line ~60)

### 7. Frontend data hook: `frontend/packages/ui/src/components/portfolio/holdings/useHoldingsData.ts`

In `mapHolding()` (line ~33), change `dividend: 0` → `dividendYield: holding.dividendYield ?? 0`

### 8. Frontend table: `frontend/packages/ui/src/components/portfolio/holdings/HoldingsTable.tsx`

Add column header between Volatility and Risk Score:
```typescript
{ key: "dividendYield", label: "YOC", width: "w-20" },
```

Tighten widths: Volatility `w-28` → `w-24`, Risk Score `w-28` → `w-24`.

Add cell renderer after Volatility `<td>`:
```tsx
<td className="px-6 py-4">
  {holding.dividendYield > 0 ? (
    <span className="font-semibold text-emerald-600">
      {formatPercent(holding.dividendYield, { decimals: 1 })}
    </span>
  ) : (
    <span className="text-sm text-muted-foreground">—</span>
  )}
</td>
```

### 9. Tests: `tests/routes/test_positions_lazy_service.py`

Update the merge whitelist assertion at line ~123 to include `"dividend_yield"` in the expected sector enrichment fields tuple.

## Notes
- **Yield on cost** = `lastDiv / entry_price * 100`. Shows what YOUR cost basis earns, not the market yield.
- FMP profile `lastDiv` = last annual dividend per share.
- `entry_price` comes from the position's avg cost basis (falls back to `weighted_entry_price`).
- Non-dividend payers and positions without cost basis show "—" (dash).
- Cash positions also show "—" (market enrichment skips `CUR:` symbols).
- Column is sortable via existing sort infrastructure — no extra code needed.
- No new API calls — `lastDiv` is extracted from the existing profile fetch that already runs for sector enrichment.
- Profile cache includes the new `last_div` field — old cache entries will be `None` until cache expires (~30s).

## Verification
1. `cd frontend && npx tsc --noEmit --project packages/ui/tsconfig.json && npx tsc --noEmit --project packages/connectors/tsconfig.json`
2. Open Chrome → Holdings tab → verify YOC column appears with real yield values
3. Click YOC column header → verify sorting works
4. Confirm non-dividend payers show "—"
5. Verify a known dividend payer shows yield on cost (lastDiv / your avg cost), not market yield

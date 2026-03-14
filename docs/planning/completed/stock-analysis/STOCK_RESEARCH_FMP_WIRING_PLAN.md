# Wave 2d: Stock Research — Real FMP Data Wiring

**Status**: COMPLETE — commits `4ae8115f` + `941c92e0` (plan v4 implemented)

## Context

Stock Research (⌘6) has a working risk analysis flow (`useStockAnalysis` → `/api/direct/stock` → volatility, beta, factor exposures), but all market data is hardcoded:
- Search results show fake price ($150), name ("${ticker} Inc."), exchange ("NASDAQ")
- Selected stock header shows 0 for price, market cap, volume, day change
- Fundamentals tab falls back to hardcoded values (P/E=15, P/B=3)
- Chart data is empty

FMP already has all this data via registered endpoints (`search`, `profile`, `ratios_ttm`, `historical_price_adjusted`). Just needs wiring.

## Approach

**Two-part backend change + one frontend change:**

1. **New GET endpoint** `/api/direct/stock/search` — fast typeahead (FMP search + batch quote)
2. **Enrich existing POST** `/api/direct/stock` — add profile, quote, ratios, chart data to response
3. **Frontend** — new `useStockSearch` hook, replace mock search results in container

The container transform (lines 254-332 of `StockLookupContainer.tsx`) already reads `company_name`, `current_price`, `market_cap`, `pe_ratio`, `chart_data`, etc. via `toRecord()`/`toNumber()` with safe fallbacks — once backend populates these fields, the UI "just works."

## Codex Findings (Addressed)

**v1 findings:**
1. **Adapter gap**: `StockAnalysisAdapter` only extracts risk-centric fields. Enriched fields dropped. **Fix**: Spread `...data` in adapter output so all backend fields pass through.
2. **Search UI gap**: `StockLookup.tsx` ignores `searchResults`/`isSearching` (prefixed `_`). No dropdown UI. **Fix**: Wire search dropdown + un-ignore props.
3. **Caching**: `fetch_raw()` bypasses FMP disk cache. **Fix**: Use `fetch()` for profile/ratios/historical, `fetch_raw()` only for quote.

**v2 findings:**
4. **Search/selection state management**: Multiple interacting issues — input `onChange` doesn't call `onSearchChange` (line 378), `handleSearchChange` doesn't clear `selectedSymbol`, and `selectedStock` is derived from cached `stockData` so clearing `selectedSymbol` alone doesn't hide the detail view. **Fix**: These are all UX state management fixes in StockLookup + container. The approach: (a) input `onChange` calls `onSearchChange` to propagate typing to container, (b) container's `handleSearchChange` clears `selectedSymbol`, (c) transform block gates on `selectedSymbol` being non-null (already partially true — `symbol: stockData.ticker || selectedSymbol || ''`), (d) StockLookup shows dropdown when search results exist and no stock is actively selected. Implementation will handle exact state transitions.
5. **Search rate limit too low**: 200/day at debounced typing could hit 429. **Fix**: Raise to 1000/day for search endpoint.
6. **Per-source error handling**: One broad try/except could lose all enrichment on single FMP failure. **Fix**: Wrap each FMP call in its own try/except.
7. **Adapter output**: Use top-level `...data` spread only (no `raw` nesting). Index signature on `StockRiskDisplayData`.

## Changes

### 1. Register FMP `quote` endpoint

**File**: `fmp/registry.py`

Register `/quote/{symbol}` (v3, no disk cache — data is near-real-time). Returns: price, change, changesPercentage, marketCap, volume, eps, exchange. Supports comma-separated batch (`/quote/AAPL,MSFT`). Path param `{symbol}` works same as existing `profile` endpoint.

### 2. New search endpoint

**File**: `app.py` (next to existing `direct_stock` at line 3600)

`GET /api/direct/stock/search?query=AAPL&limit=8`

Note: This is GET (not POST like other `/api/direct/*` routes) because search is idempotent and benefits from browser/proxy caching. FastAPI supports mixed methods on the same prefix.

1. FMP `fetch_raw("search", query=..., limit=...)` → `[{symbol, name, exchangeShortName}]`
2. FMP `fetch_raw("quote", symbol=comma_separated)` → `[{price, change, changesPercentage, marketCap}]`
3. Merge and return `{success: true, results: [{symbol, name, price, change, changePercent, exchange, marketCap}]}`

Both FMP calls are fast (<100ms each). `fetch_raw` is fine here — search results are ephemeral, no disk cache needed. Rate limit: 1000/day (higher than analysis endpoint since search is cheap and debounced typing can generate many requests).

### 3. Enrich `/api/direct/stock` response

**File**: `app.py` (inside `direct_stock` function, after `result.to_api_response()`)

After existing risk analysis, fetch FMP data (all wrapped in try/except so risk analysis never fails):

| FMP Call | Method | Fields Added | Disk Cache |
|----------|--------|-------------|------------|
| `profile` | `fetch()` → DataFrame → `.to_dict('records')[0]` | `company_name`, `sector`, `industry` | Yes (~1 week) |
| `quote` | `fetch_raw()` → dict | `current_price`, `price_change`, `price_change_percent`, `market_cap`, `volume`, `eps` | No (real-time) |
| `ratios_ttm` | `fetch()` → DataFrame → `.to_dict('records')[0]` | `pe_ratio`, `pb_ratio`, `roe`, `debt_to_equity`, `profit_margin`, `dividend_yield`, `current_ratio` | Yes (24h) |
| `historical_price_adjusted` (90 days) | `fetch()` → DataFrame → iterate rows | `chart_data` [{date, price, volume}] | Yes (hash-based) |

Each FMP call wrapped in its own try/except so a single failure doesn't lose all enrichment. Merge fields into `api_response["data"]` dict. Container's `toRecord()` / `toNumber()` pattern picks them up automatically.

### 4. Frontend: Adapter pass-through for enriched fields

**File**: `frontend/packages/connectors/src/adapters/StockAnalysisAdapter.ts`

The adapter currently only extracts risk-centric fields (volatility_metrics, regression_metrics, factor_summary) and drops everything else. The container uses `toRecord(stockData)` which flattens to a generic record — so any top-level keys on the output will be accessible.

**Fix**: In `performTransformation()` (line 176), spread the raw `data` dict at the top level, then override with typed fields:

```typescript
const transformedData: StockRiskDisplayData = {
  ...data,  // Pass through ALL backend fields (company_name, current_price, pe_ratio, chart_data, etc.)
  // Override with typed fields:
  success: apiResponse.success,
  ticker,
  volatility_metrics: { ... },
  regression_metrics: { ... },
  // ... rest of existing typed fields
};
```

Update `StockRiskDisplayData` interface to allow extra keys: add `[key: string]: unknown` index signature (or extend with `Record<string, unknown>`). The container already accesses fields via `toRecord()`/`toNumber()` which handles unknown types safely.

### 5. Frontend: `useStockSearch` hook

**New file**: `frontend/packages/connectors/src/features/stockAnalysis/hooks/useStockSearch.ts`

TanStack Query hook calling `GET /api/direct/stock/search?query=...&limit=8`.
- `enabled: query.length >= 1`
- `staleTime: 60_000` (1 min)
- Returns `{ results: StockSearchResult[], isSearching: boolean }`
- Uses `useSessionServices()` for API access (matching existing hook patterns)

**File**: `frontend/packages/chassis/src/services/APIService.ts`

Add `searchStocks(query, limit)` method — simple GET request.

**File**: `frontend/packages/chassis/src/queryKeys.ts`

Add `stockSearchKey(query)` query key factory + add to key union type.

**Exports**: Wire through `connectors/src/features/stockAnalysis/hooks/index.ts` and `connectors/src/index.ts`.

### 6. Frontend: Wire search input + dropdown in StockLookup component

**File**: `frontend/packages/ui/src/components/portfolio/StockLookup.tsx`

The component currently ignores `searchResults` and `isSearching` (prefixed with `_`), and the input `onChange` (line 378) only updates local state without calling `onSearchChange`. Fix:

1. Remove `_` prefix from `searchResults`, `isSearching`, `onClearSelection` destructuring (line 292-295)
2. Fix input `onChange` (line 378) to also call `onSearchChange(value)` — this propagates typing to the container's `debouncedTerm` which drives `useStockSearch`
3. Add a search results dropdown below the search input:
   - Renders each result: symbol, name, exchange, price, change (green/red)
   - Clicking a result calls `onSelectStock(result.symbol)`
   - Shows loading spinner when `isSearching`
4. Keep `handleSearch()` Enter-key behavior as primary UX (direct lookup by typed symbol). Dropdown is secondary for discovery.
5. State management: when user starts typing after a selection, the input onChange → onSearchChange → container clears selectedSymbol → detail view hides → dropdown shows. Container's `handleSearchChange` needs `setSelectedSymbol(null)` added (see Step 7).

### 7. Frontend: Replace mock search in container

**File**: `frontend/packages/ui/src/components/dashboard/views/modern/StockLookupContainer.tsx`

- Import `useStockSearch` from `@risk/connectors`
- Replace lines 182-194 (mock `searchResults` + `isSearching = false`) with:
  ```
  const { results: searchResults, isSearching } = useStockSearch(debouncedTerm);
  ```
- Remove the 7 TODO comments
- In `handleSearchChange` (line 206), add `setSelectedSymbol(null)` so typing clears the current selection
- Gate `transformedStockData` on `selectedSymbol` being set (line 254): change `stockData ?` to `stockData && selectedSymbol ?` so clearing the symbol also hides the detail view (even if cached `stockData` persists from TanStack Query)
- Transform block fields (lines 254-332) unchanged — already reads all the enriched fields (now accessible via adapter pass-through)

## Files Modified

| File | Change |
|------|--------|
| `fmp/registry.py` | Register `quote` endpoint |
| `app.py` | Add search endpoint + enrich stock response with FMP data |
| `frontend/packages/connectors/src/adapters/StockAnalysisAdapter.ts` | Spread raw data through to preserve enriched fields |
| `frontend/packages/chassis/src/services/APIService.ts` | Add `searchStocks()` method |
| `frontend/packages/chassis/src/queryKeys.ts` | Add `stockSearchKey` + update key union |
| `frontend/packages/connectors/src/features/stockAnalysis/hooks/useStockSearch.ts` | New hook |
| `frontend/packages/connectors/src/features/stockAnalysis/hooks/index.ts` | Export new hook |
| `frontend/packages/connectors/src/index.ts` | Export new hook |
| `frontend/packages/ui/src/components/portfolio/StockLookup.tsx` | Wire search dropdown (un-ignore searchResults/isSearching) |
| `frontend/packages/ui/src/components/dashboard/views/modern/StockLookupContainer.tsx` | Use real search hook |

## What Goes From Mock → Real

| Field | Before | After |
|-------|--------|-------|
| Search: name, exchange | `"${ticker} Inc."`, `"NASDAQ"` | Real from FMP search |
| Search: price, change | `150.00`, `2.50`, `1.69%` | Real from FMP quote |
| Company name | Fallback `"${ticker} Inc."` | Real from FMP profile |
| Price, change, % | 0 | Real from FMP quote |
| Market cap, volume | 0 | Real from FMP quote |
| Sector | "Technology" | Real from FMP profile |
| P/E, P/B | 15, 3 | Real from FMP ratios_ttm |
| ROE, D/E, margin | undefined | Real from FMP ratios_ttm |
| EPS, dividend yield | 0 | Real from FMP ratios_ttm + quote |
| Chart (90-day) | Empty | Real from FMP historical prices |
| Risk metrics | Already real | Unchanged |

## What Stays Mock

- Analysis summary/recommendation/targetPrice — needs FMP analyst consensus (separate feature)
- Technical indicators (RSI, MACD, support/resistance) — derived from risk data with fallbacks
- Risk Factors tab content — hardcoded in component (not from container)
- Fundamental performance scores (85/100, 72/100, 45/100) — hardcoded in component

## Data Flow (After Fix)

```
SEARCH (fast, ~200ms):
  User types → debounce 300ms → useStockSearch(query)
    → GET /api/direct/stock/search?query=AAPL&limit=8
    → FMP search + batch quote (fetch_raw, no disk cache)
    → [{symbol, name, price, change, changePercent, exchange}]
    → StockLookup search dropdown renders real results

SELECTION (existing + enriched, ~1-2s):
  User clicks dropdown result → analyzeStock(symbol)
    → POST /api/direct/stock {ticker: "AAPL"}
    → StockService.analyze_stock() (existing — risk analysis)
    → FMP profile + quote + ratios_ttm + historical_price_adjusted (new enrichment)
    → Combined response: risk + market data + fundamentals + chart
    → StockAnalysisAdapter spreads raw data through (enriched fields preserved)
    → Container toRecord(stockData) accesses company_name, current_price, pe_ratio, chart_data, etc.
    → StockLookup renders real data in header + fundamentals + chart
```

## Verification

1. `curl "localhost:5001/api/direct/stock/search?query=AAPL&limit=5"` → returns results with real prices
2. `curl -X POST localhost:5001/api/direct/stock -H 'Content-Type: application/json' -d '{"ticker":"AAPL"}'` → response includes `company_name`, `current_price`, `chart_data`, `pe_ratio`, etc.
3. `cd frontend && pnpm typecheck` passes
4. `cd frontend && pnpm lint` passes (our files)
5. Start frontend + backend, navigate to Stock Research (⌘6)
6. Type "AAPL" → search dropdown shows real company name, price, exchange
7. Click result → header shows real price, market cap, volume
8. Fundamentals tab shows real P/E, ROE, etc.
9. Chart shows 90-day price history

# Refactor: Move FMP Stock Enrichment from app.py → StockService

**Status**: COMPLETE — committed as `941c92e0`. Backend verified via curl (search + enrichment both working).

## Context

Wave 2d wired real FMP data (search, profile, quote, ratios, historical prices) into Stock Research, but the enrichment logic was placed directly in `app.py` route handlers (~180 lines, two endpoints). This violates the project architecture: `app.py` (thin route) → `services/` (business logic) → `core/result_objects/` (data). Additionally, `_to_float()` is duplicated across both endpoints.

## Changes

### 1. New file: `utils/fmp_helpers.py` (~40 lines)

Extract three helpers from app.py into a reusable module:

- `parse_fmp_float(value)` → `Optional[float]` — from app.py `_to_float` (lines 3620, 3797). Deduplicates two copies. Handles `%`, commas, `()` negatives, NaN, bools.
- `pick_value(record, *keys)` → `Any` — from app.py `_pick_value` (line 3825). Tries multiple FMP field aliases, returns first non-empty.
- `first_dataframe_record(df)` → `dict` — from app.py `_first_dataframe_record` (line 3832). DataFrame → first row dict, handles None/empty.

### 2. Add methods to `services/stock_service.py`

**Add lazy `fmp_client` property** — `StockService.__init__` (line 87) currently takes only `cache_results`. Add optional `fmp_client` param, lazy-import `get_client()` on first use.

**Add `search_stocks(query, limit)`** — extracted from app.py lines 3648-3709:
- Includes input validation: strip whitespace, empty-query fast return (`[]`), clamp limit to 1..20
- FMP `search` → batch `quote` → merge results
- Quote batch failure logged but non-fatal (search results returned without prices)
- Returns `list[dict]` with symbol, name, price, change, changePercent, exchange, marketCap

**Add `enrich_stock_data(ticker, data)`** — extracted from app.py lines 3841-3977:
- Four try/except blocks: profile, quote, ratios_ttm, historical_price_adjusted
- Mutates `data` dict in place (same behavior as current inline code)
- Cache semantics preserved: `fetch()` (cached) for profile/ratios/historical, `fetch_raw()` (uncached) for quote
- Uses `parse_fmp_float`, `pick_value`, `first_dataframe_record` from utils

### 3. Slim down `app.py` routes (~170 lines removed)

**Search endpoint** (`GET /api/direct/stock/search`, lines 3603-3725) → ~15 lines:
```python
stock_service = StockService()
results = stock_service.search_stocks(query, limit)
log_request("DIRECT_STOCK_SEARCH", "API", "EXECUTE", api_key, "direct", "success", user_tier)
return {"success": True, "results": results}
```
Route keeps: rate limiting, API key extraction, `log_request` telemetry, error response formatting. Service handles: input validation, FMP calls, data merging.

**Stock enrichment** in POST handler (lines 3797-3977) → ~3 lines:
```python
api_response = result.to_api_response()
stock_service.enrich_stock_data(ticker, api_response)
```
Note: `to_api_response()` returns a flat dict — enrich directly, no `.get("data")` needed.

Delete all inline `_to_float`, `_pick_value`, `_first_dataframe_record` definitions.

## Files Modified

| File | Change |
|------|--------|
| `utils/fmp_helpers.py` | **NEW** — 3 helper functions (~40 lines) |
| `services/stock_service.py` | Add `fmp_client` property, `search_stocks()`, `enrich_stock_data()` (~100 lines) |
| `app.py` | Delete ~170 lines of inline FMP logic, replace with service calls (~15 lines) |

## Design Notes

- **No StockAnalysisResult changes** — enrichment fields stay as a flat dict merge. They're market data, not risk analytics. The result object models risk analysis only.
- **No API response shape changes** — same fields, same types, just sourced from service instead of inline.
- **Error handling preserved** — each FMP source stays in its own try/except within the service method.
- **Lazy fmp_client** — imported on first use to avoid circular imports.
- **Cache semantics preserved** — `fetch()` (disk-cached) for profile/ratios/historical, `fetch_raw()` (uncached) for quote. Explicitly documented in `enrich_stock_data` docstring.
- **Logging stays in routes** — `log_request` telemetry with `api_key`/`user_tier` stays in app.py route handlers. Service methods use standard `logger.error()` for FMP failures (no API key context needed).
- **Cleanup** — remove unused `from fmp import get_client` in app.py (line 220) after extraction.

## Codex v1 Findings (Addressed)

1. **Search input validation**: `search_stocks()` includes strip, empty-query fast return, limit clamp (1..20) — not just the core FMP logic.
2. **Logging/telemetry**: `log_request` stays in app.py routes. Service uses `logger.error()` for FMP failures. No api_key leaking into service layer.
3. **Cache semantics**: Explicitly documented `fetch()` vs `fetch_raw()` usage per FMP source.
4. **Enrichment target**: Changed from `api_response.get("data", api_response)` to just `api_response` — `to_api_response()` returns a flat dict.
5. **Import cleanup**: Plan now includes removing unused `from fmp import get_client` from app.py.

## Current Code References

### app.py inline helpers (to be extracted)
- `_to_float()`: lines 3620-3646 (search), lines 3797-3823 (stock) — DUPLICATED
- `_pick_value()`: lines 3825-3830
- `_first_dataframe_record()`: lines 3832-3839

### app.py search endpoint (to be moved to service)
- `direct_stock_search()`: lines 3603-3725
- Core logic: FMP search (line 3660) → batch quote (line 3685) → merge (lines 3695-3709)

### app.py enrichment (to be moved to service)
- Profile enrichment: lines 3844-3865
- Quote enrichment: lines 3867-3896
- Ratios enrichment: lines 3898-3935
- Historical chart enrichment: lines 3937-3977

### StockService current state
- `services/stock_service.py`: `__init__` at line 87, `analyze_stock()` at line 100
- Only takes `cache_results` param, no `fmp_client`
- Already has `ServiceCacheMixin`, logging decorators

## Verification

1. `curl "localhost:5001/api/direct/stock/search?query=AAPL&limit=3"` → same results as before
2. `curl -X POST localhost:5001/api/direct/stock -H 'Content-Type: application/json' -d '{"ticker":"AAPL"}'` → response still includes `company_name`, `current_price`, `pe_ratio`, `chart_data`
3. Compare before/after API responses — field names and types identical

# Stock Lookup Wiring Gaps — Fix Plan

**Date:** 2026-03-04
**Status:** Codex-reviewed, PASS

## Context

The Stock Lookup view is 95% wired to real backend data. Search dropdown, stock analysis, peer comparison, and portfolio fit all use real APIs. However, several areas still have stale comments, hardcoded values, or missing integrations. This plan addresses all remaining gaps.

## Gaps to Fix

### 1. Technical Indicators — Wire Real FMP Data (HIGH)

**Problem:** RSI, MACD, support/resistance, Bollinger all fall back to defaults (RSI=50, MACD=0, support/resistance=price±10%, bollinger='Middle') because `enrich_stock_data()` doesn't fetch technical data.

**Fix:** Add technical indicator enrichment to `services/stock_service.py:enrich_stock_data()` using `get_technical_analysis()` from `fmp/tools/technical.py`.

**Codex review findings (addressed):**
- `get_technical_analysis()` returns nested structure, NOT flat keys. Must map:
  - `response["momentum"]["rsi"]["value"]` → `technical_indicators.rsi`
  - `response["momentum"]["macd"]["macd_line"]` → `technical_indicators.macd`
  - `response["volatility"]["bollinger"]["signal"]` → `technical_indicators.bollinger_position` (map `"near_upper_band"/"above_upper_band"` → `"Upper"`, `"near_lower_band"/"below_lower_band"` → `"Lower"`, else → `"Middle"`)
  - `response["support_resistance"]["support"][0]["price"]` → `technical_levels.support`
  - `response["support_resistance"]["resistance"][0]["price"]` → `technical_levels.resistance`
- **Latency risk**: Full `get_technical_analysis()` fans out to ~9 FMP endpoints (SMA×3, EMA×2, RSI, ADX, Williams, StdDev). Call with `indicators=["rsi", "macd", "bollinger"]` to limit to ~5 fetches. They run in parallel via ThreadPoolExecutor internally.
- **sys.stdout mutation**: The function redirects stdout→stderr during execution. Safe for single-request but noted.
- Wrap in try/except — graceful fallback to existing defaults on failure.

**Implementation:**
```python
# In enrich_stock_data(), after chart_data enrichment:
try:
    from fmp.tools.technical import get_technical_analysis
    tech = get_technical_analysis(ticker, indicators=["rsi", "macd", "bollinger"], format="summary")
    if tech.get("status") == "success":
        ti = {}
        momentum = tech.get("momentum", {})
        if "rsi" in momentum:
            ti["rsi"] = momentum["rsi"]["value"]
        if "macd" in momentum:
            ti["macd"] = momentum["macd"]["macd_line"]
        vol = tech.get("volatility", {})
        if "bollinger" in vol:
            boll = vol["bollinger"]
            sig = boll.get("signal", "")
            if "upper" in sig:
                ti["bollinger_position"] = "Upper"
            elif "lower" in sig:
                ti["bollinger_position"] = "Lower"
            else:
                ti["bollinger_position"] = "Middle"
        if ti:
            data["technical_indicators"] = ti
        sr = tech.get("support_resistance", {})
        tl = {}
        supports = sr.get("support", [])
        resistances = sr.get("resistance", [])
        if supports:
            tl["support"] = supports[0]["price"]
        if resistances:
            tl["resistance"] = resistances[0]["price"]
        if tl:
            data["technical_levels"] = tl
except Exception:
    logger.exception("FMP technical enrichment failed for ticker=%s", ticker)
```

**Files:**
- `services/stock_service.py` — add technical enrichment block to `enrich_stock_data()`

### 2. Financial Health Scores — Compute from Real Data (MEDIUM)

**Problem:** Lines 1071-1087 of `StockLookup.tsx` hardcode Profitability=85/100, Leverage=72/100, Valuation=45/100.

**Fix:** Compute scores from available fundamentals data already passed via props:
- **Profitability score**: Based on `roe` and `profitMargin` (higher = better, scale to 0-100)
- **Leverage score**: Based on `debtToEquity` and `currentRatio` (lower D/E + higher CR = better)
- **Valuation score**: Based on `peRatio` and `pbRatio` (lower = more attractive, capped)

Compute in `StockLookup.tsx` from `selectedStock.fundamentals` — no backend change needed. Use `useMemo` for derived scores.

**Files:**
- `frontend/packages/ui/src/components/portfolio/StockLookup.tsx` — compute health scores from fundamentals

### 3. Search History — Add localStorage Recent Searches (LOW)

**Problem:** Search history mentioned in container comments but not implemented.

**Fix:** Add recent searches (last 8 unique tickers) stored in localStorage. Show in empty state below quick-access buttons as "Recent" chips. Update on each stock selection.

**Files:**
- `frontend/packages/ui/src/components/portfolio/StockLookup.tsx` — render recent searches in empty state
- `frontend/packages/ui/src/components/dashboard/views/modern/StockLookupContainer.tsx` — manage localStorage state, pass as prop

### 4. Stale Comments & TODOs — Cleanup (LOW)

**Problem:**
- Component header says "Mock search results" — search is real
- 4 TODOs say "Add X field to StockAnalysisAdapter" for var95/var99/maxDrawdown/correlationToSP500 — these are computed in container and work fine
- Fundamentals TODOs for peRatio/roe/debtToEquity/profitMargin/pbRatio — all passed from container
- Tab data comments say "Mock" for risk factors, technicals, fundamentals — all real or about to be

**Fix:** Remove stale TODO comments and update "Mock" comments to reflect real data status.

**Files:**
- `frontend/packages/ui/src/components/portfolio/StockLookup.tsx` — clean stale TODOs and comments
- `frontend/packages/ui/src/components/dashboard/views/modern/StockLookupContainer.tsx` — clean stale comment on line 538

### 5. Unused Variables Cleanup (LOW)

**Problem:** `_hasData`, `_hasError`, `_hasTicker` unused in container (line 194-196).

**Fix:** Remove the unused destructured variables.

**Files:**
- `frontend/packages/ui/src/components/dashboard/views/modern/StockLookupContainer.tsx`

### 6. Additional Codex Findings (MEDIUM)

**a) Synthetic valuation defaults mask missing data:**
`StockLookupContainer.tsx:362-363` defaults `peRatio=15`, `pbRatio=3` when backend returns nothing. Should default to `undefined` so UI shows "N/A" instead of fake values.

**b) ROE/profit margin percent/decimal mismatch:**
FMP `ratios_ttm` returns ROE as decimal (e.g., 0.25 = 25%). Backend stores raw decimal in `data["roe"]`. Container passes through via `toOptionalNumber(fundamentalsRecord.roe)`. Component renders `{roe?.toFixed(1)}%`. **Fix:** Multiply by 100 in the container transform for `roe` and `profitMargin` (same pattern as `annualVolatility` on line 338). Apply in `StockLookupContainer.tsx` fundamentals block.

**c) Support/resistance price bar zero-division guard:**
`StockLookup.tsx:915` computes `(price - support) / (resistance - support) * 100` with no guard for `resistance === support`. Add clamp.

**Files:**
- `frontend/packages/ui/src/components/dashboard/views/modern/StockLookupContainer.tsx` — fix default values
- `frontend/packages/ui/src/components/portfolio/StockLookup.tsx` — add zero-division guard

## Implementation Order

1. **Technical indicators** (backend enrichment — biggest real gap)
2. **Codex findings 6a-6c** (valuation defaults, percent/decimal, zero-div guard)
3. **Financial health scores** (frontend compute from existing data)
4. **Search history** (new feature, self-contained)
5. **Stale comments & TODOs** (cleanup pass)
6. **Unused variables** (trivial cleanup)

## Codex Review Summary

**First review: FAIL** — 4 issues found:
1. Return shape mismatch for `get_technical_analysis()` → fixed with explicit field mapping
2. Latency risk from ~9 parallel fetches → mitigated by limiting to `["rsi", "macd", "bollinger"]`
3. Synthetic valuation defaults, percent mismatch, zero-div guard → added as gap #6
4. `sys.stdout` mutation in technical tool → noted, acceptable for single-request path

## Key Files Reference

| File | Role |
|------|------|
| `services/stock_service.py` | Backend stock service — `enrich_stock_data()` adds FMP data |
| `fmp/tools/technical.py` | `get_technical_analysis()` — existing FMP technical indicator tool |
| `frontend/packages/ui/src/components/portfolio/StockLookup.tsx` | Main component (1340 lines) |
| `frontend/packages/ui/src/components/dashboard/views/modern/StockLookupContainer.tsx` | Container (580 lines) — transforms hook data to props |
| `frontend/packages/connectors/src/features/stockAnalysis/hooks/useStockSearch.ts` | Search hook — already wired to real API |
| `frontend/packages/connectors/src/adapters/StockAnalysisAdapter.ts` | Adapter — transforms API response |
| `app.py:direct_stock` | POST /api/direct/stock endpoint — calls `enrich_stock_data()` |

## Verification

1. Backend: verify `enrich_stock_data('AAPL', data)` populates `technical_indicators` dict
2. Frontend typecheck: `cd frontend && pnpm typecheck`
3. Frontend lint: `cd frontend && pnpm lint`
4. Existing tests: `cd frontend && pnpm test`
5. Manual: Load Stock Lookup → search "AAPL" → verify Technicals tab shows real RSI/MACD/support/resistance

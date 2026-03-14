# B-014: Performance View — Wire Real Analyst Data (Target Prices + Ratings)

**Status**: COMPLETE — commit `3f14a56b`, verified in browser

## Context

The Performance view (⌘4) has a Top Contributors / Top Detractors section with entirely hardcoded data: AAPL Buy $225, MSFT Strong Buy $450, etc. with fake confidence scores and AI insights. FMP has analyst endpoints (`price_target_consensus`, `analyst_grades`) already registered in `fmp/registry.py` with 24h caching.

The performance response already has a `security_attribution` field in `PerformanceResult` that is populated by `_compute_security_attribution()` in `portfolio_risk.py` line ~2045, producing `[{name, allocation, return, contribution}]` sorted by absolute contribution. The frontend `PerformanceAdapter` already has plumbing for `security_attribution` → `performanceSummary.attribution.security`.

## Approach

Enrich the already-computed `security_attribution` with real FMP analyst data (target price, rating, analyst count) for the top/bottom contributors, then wire through to the frontend.

**Out of scope**: The AI `insight` text and `confidence` scores — FMP has no equivalent. Replace `confidence` with analyst count (number of analysts covering the stock) which is a real metric. The AI insights section (performance/risk/opportunity cards) is B-013 — separate item.

## Changes

### 1. Backend: Add analyst enrichment method

**File**: `services/portfolio_service.py` — add `enrich_attribution_with_analyst_data()` method

For each ticker in the security_attribution list (already sorted by absolute contribution), batch-fetch two FMP endpoints:

**`price_target_consensus`** (symbol=ticker) → response shape:
```json
{"symbol": "AAPL", "targetHigh": 350, "targetLow": 220, "targetConsensus": 304.23, "targetMedian": 315}
```

**`price_target`** (symbol=ticker) → response shape (for analyst count):
```json
{"symbol": "AAPL", "lastYearCount": 48, "lastQuarterCount": 15, ...}
```

**`analyst_grades`** (symbol=ticker, limit=1) → response shape:
```json
{"symbol": "AAPL", "gradingCompany": "Wedbush", "newGrade": "Outperform", "action": "maintain"}
```

Pattern follows `enrich_positions_with_market_data()` — parallel fetches via `ThreadPoolExecutor`, graceful fallback on exception.

Fields added to each attribution entry:
```python
{
    # existing fields from _compute_security_attribution():
    "name": "AAPL",              # NOTE: this is the ticker symbol, not company name
    "allocation": 8.7,           # weight %
    "return": 31.2,              # return %
    "contribution": 4.23,        # contribution points
    # new fields from FMP:
    "target_price": 304.23,      # from price_target_consensus["targetConsensus"]
    "analyst_rating": "Outperform",  # from analyst_grades[0]["newGrade"]
    "analyst_count": 48,         # from price_target["lastYearCount"]
}
```

### 2. Backend: Wire into performance response

**File**: `app.py` — in the `/api/performance` handler (~line 1400)

After `portfolio_service.analyze_performance()` returns the `PerformanceResult`, its `security_attribution` is already populated. Call `enrich_attribution_with_analyst_data()` on the result's `security_attribution` list to add analyst fields before serializing the response.

### 3. Frontend: Replace hardcoded data with props

**File**: `frontend/packages/ui/src/components/portfolio/PerformanceView.tsx`

- Add `topContributors` and `topDetractors` to `PerformanceViewProps` interface
- Replace the hardcoded `performanceData.topContributors` / `topDetractors` local objects (~lines 550-690) with props
- Keep hardcoded data as fallback when props are undefined (graceful degradation)
- Replace `confidence` display with `analystCount` ("38 analysts")
- Remove fake AI `insight` text from contributor cards

**File**: `frontend/packages/ui/src/components/dashboard/views/modern/PerformanceViewContainer.tsx`

- Map `security_attribution` from the adapter into `topContributors` (positive contribution) / `topDetractors` (negative contribution), sorted by magnitude
- Pass to `PerformanceView` as props

**File**: `frontend/packages/connectors/src/adapters/PerformanceAdapter.ts`

- Already has `security_attribution` → `performanceSummary.attribution.security` mapping
- Extend the type to include `target_price`, `analyst_rating`, `analyst_count` fields

### 4. Frontend: Type interfaces

Add to the security attribution type:
```typescript
interface SecurityAttribution {
    symbol: string;
    name: string;
    allocation: number;
    return: number;
    contribution: number;
    targetPrice?: number;
    analystRating?: string;
    analystCount?: number;
}
```

## Files Modified

| File | Change |
|------|--------|
| `services/portfolio_service.py` | Add `enrich_attribution_with_analyst_data()` method |
| `app.py` | Wire analyst enrichment into `/api/performance` response |
| `frontend/.../PerformanceView.tsx` | Replace hardcoded contributors/detractors with props |
| `frontend/.../PerformanceViewContainer.tsx` | Map security_attribution → topContributors/topDetractors |
| `frontend/.../PerformanceAdapter.ts` | Extend security attribution type with analyst fields |

## Key Facts

- **`security_attribution` is already computed**: `_compute_security_attribution()` in `portfolio_risk.py` line ~2045 produces `[{name, allocation, return, contribution}]` sorted by absolute contribution. Populated on `PerformanceResult` via `from_core_analysis()`. No new computation needed — just enrich with analyst data.
- **FMP endpoints (verified with live data)**:
  - `price_target_consensus` → `{targetHigh, targetLow, targetConsensus, targetMedian}` (no analyst count)
  - `price_target` → `{lastYearCount, lastQuarterCount, lastMonthCount, ...AvgPriceTarget}` (has analyst count)
  - `analyst_grades` → `[{newGrade, gradingCompany, action, date}]` (grades are "Outperform"/"Hold"/"Underperform", not "Buy"/"Sell")
- **Rate limiting**: Fetching for ~8 tickers × 3 endpoints = ~24 FMP calls. All have 24h caching, so first load may be slightly slow but subsequent loads are instant.
- **`name` field is ticker symbol**: `_compute_security_attribution()` sets `name=ticker` at `portfolio_risk.py` line ~2057, not company name.

## Codex v1 Findings (Addressed)

1. **FMP response field names not validated**: Verified with live `fmp_fetch` calls. `price_target_consensus` has no analyst count — use `price_target` endpoint's `lastYearCount` instead. `analyst_grades` returns `newGrade` (e.g. "Outperform"), not `grade`. Plan updated with exact verified field names.

## Verification

1. `cd frontend && pnpm typecheck` passes
2. `cd frontend && pnpm lint` passes on modified files
3. Performance view (⌘4) shows real target prices and analyst ratings for top contributors
4. Contributors/detractors section shows real contribution data from portfolio, not hardcoded AAPL/MSFT/NVDA
5. Backend: `curl localhost:5001/api/performance` → response includes `security_attribution` with `target_price`, `analyst_rating` fields

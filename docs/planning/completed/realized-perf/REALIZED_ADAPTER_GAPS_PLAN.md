# Fix Realized Performance Adapter Data Gaps (#2 and #3)

## Context

The `RealizedPerformanceAdapter` has two data gaps where backend data exists but the frontend ignores it:
- **#2**: `data_availability` hardcoded to all `false` / `'minimal'` — backend sends `data_coverage`, `reliable`, `high_confidence_realized`, `nav_metrics_estimated`
- **#3**: Benchmark line always flat (hardcoded `0`) — backend computes `benchmark_monthly_returns` but strips it in `to_api_response()` via `_postfilter` pop

## Changes

### 1. Backend: Expose `benchmark_monthly_returns` in realized API response

**File:** `core/result_objects/realized_performance.py` — `to_api_response()` (line 628)

Extract `benchmark_monthly_returns` from `_postfilter` before stripping it, and promote to top-level response field:

```python
def to_api_response(self, benchmark_ticker: str = "SPY") -> Dict[str, Any]:
    response = self.to_dict()
    postfilter = response.get("realized_metadata", {}).get("_postfilter") or {}
    benchmark_monthly = postfilter.get("benchmark_monthly_returns") or {}
    response.get("realized_metadata", {}).pop("_postfilter", None)
    response["benchmark_monthly_returns"] = benchmark_monthly
    response["status"] = "success"
    ...
```

This mirrors how hypothetical mode already exposes `benchmark_monthly_returns` at the top level.

### 2. Frontend type: Add `benchmark_monthly_returns` to realized response

**File:** `frontend/packages/chassis/src/types/index.ts` — `RealizedPerformanceApiResponse` (after line 408)

```typescript
benchmark_monthly_returns?: Record<string, number>;
```

### 3. Frontend: Wire benchmark into `buildTimeSeries`

**File:** `frontend/packages/connectors/src/adapters/RealizedPerformanceAdapter.ts`

a) Change `buildTimeSeries` signature to accept benchmark returns:
```typescript
const buildTimeSeries = (
  monthlyReturns: Record<string, number>,
  benchmarkMonthlyReturns: Record<string, number>,
) => {
```

b) Replace `const benchmarkReturn = 0` (line 42) with:
```typescript
const benchmarkReturn = toNumber(benchmarkMonthlyReturns[month], 0);
```

c) Update call site (line 126):
```typescript
const benchmarkMonthlyReturns = apiResponse.benchmark_monthly_returns || {};
const timeSeries = buildTimeSeries(monthlyReturns, benchmarkMonthlyReturns);
```

### 4. Frontend: Compute `data_availability` from real backend fields

**File:** `frontend/packages/connectors/src/adapters/RealizedPerformanceAdapter.ts` — lines 134-139

Replace hardcoded block:
```typescript
data_availability: {
  has_formatted_report: false,
  has_summary: false,
  has_portfolio_metadata: false,
  data_quality: 'minimal',
},
```

With computed values. Note: type union is `'complete' | 'partial' | 'minimal'` (not `'full'`). Realized mode does not include `formatted_report`, `summary`, or `portfolio_metadata` fields, so those stay `false`:
```typescript
data_availability: {
  has_formatted_report: false,
  has_summary: false,
  has_portfolio_metadata: false,
  data_quality: toNumber(apiResponse.data_coverage, 0) >= 50
    ? (apiResponse.realized_metadata?.reliable ? 'complete' : 'partial')
    : 'minimal',
},
```

## Files Modified

| File | Change |
|------|--------|
| `core/result_objects/realized_performance.py` | Promote `benchmark_monthly_returns` from `_postfilter` to top-level |
| `frontend/packages/chassis/src/types/index.ts` | Add `benchmark_monthly_returns?` to `RealizedPerformanceApiResponse` |
| `frontend/packages/connectors/src/adapters/RealizedPerformanceAdapter.ts` | Wire benchmark into `buildTimeSeries`, compute `data_availability` |

## Verification

1. **Backend import**: `python3 -c "import app; print('OK')"`
2. **Frontend**: `cd frontend && pnpm typecheck && pnpm build`
3. **API test**: curl realized performance, verify `benchmark_monthly_returns` present in response
4. **Visual**: Performance view in realized mode — benchmark line should show real SPY returns

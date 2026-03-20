# Fix Capture Ratio Display Bug

## Context

Up Capture and Down Capture display as "0.4%" and "0.9%" in the Benchmarks tab instead of "41.1%" and "85.4%". The backend computes capture ratios as raw ratios (0.41 = 41% capture, 1.0 = benchmark parity). The frontend's `formatPercent()` just appends `%` without multiplying by 100. So 0.411 → "0.4%" instead of "41.1%".

## Why the Adapter Layer

- **Backend must stay as-is**: `alpha_flags.py` compares capture ratios against 1.0 and formats as "1.14x". Changing the backend scale would break flag logic.
- **Display layer is wrong**: Adding a local `* 100` in BenchmarksTab breaks the pattern — `formatOptionalPercent` should receive values already in percentage scale.
- **Adapter layer is the normalization boundary**: It already exists to bridge backend conventions to frontend conventions. Other percentage metrics (tracking_error, volatility, max_drawdown) are already multiplied by 100 in the backend before the adapter sees them. Capture ratios are the exception — the adapter should handle the conversion.

## Changes

### 1. `frontend/packages/connectors/src/adapters/RealizedPerformanceAdapter.ts` (lines 402-403)

This is the active production path. Multiply by 100 when extracting:

```typescript
// Before:
upCaptureRatio: toNullableNumber(riskAdjusted.up_capture_ratio),
downCaptureRatio: toNullableNumber(riskAdjusted.down_capture_ratio),

// After:
upCaptureRatio: toNullablePercent(riskAdjusted.up_capture_ratio),
downCaptureRatio: toNullablePercent(riskAdjusted.down_capture_ratio),
```

Add helper near existing `toNullableNumber`:
```typescript
const toNullablePercent = (value: unknown): number | null => {
  const n = toNullableNumber(value);
  return n != null ? n * 100 : null;
};
```

### 2. `frontend/packages/connectors/src/adapters/PerformanceAdapter.ts`

Two sub-changes:

**2a. Add fields to the `risk_adjusted_returns` type (line 191-196):**

The local `PerformanceApiResponse` type for `risk_adjusted_returns` is missing these fields even though the backend returns them. Add:

```typescript
risk_adjusted_returns: {
  sharpe_ratio: number;
  sortino_ratio: number;
  information_ratio: number;
  calmar_ratio: number;
  up_capture_ratio?: number | null;    // ADD
  down_capture_ratio?: number | null;  // ADD
};
```

**2b. Extract into `riskMetrics` object (lines 846-856):**

Add to the `riskMetrics` object after `trackingError`:

```typescript
const riskAdjusted = performance.risk_adjusted_returns || {};
const toNullablePercent = (v: number | null | undefined): number | null =>
  v != null ? v * 100 : null;
const riskMetrics = {
  sharpeRatio: riskAdjusted.sharpe_ratio || 0,
  informationRatio: riskAdjusted.information_ratio || 0,
  sortino: riskAdjusted.sortino_ratio || 0,
  maxDrawdown: performance.risk_metrics.maximum_drawdown,
  calmar: riskAdjusted.calmar_ratio || 0,
  beta: benchmark.beta || 0,
  alpha: benchmark.alpha_annual || 0,
  trackingError: performance.risk_metrics.tracking_error,
  upCaptureRatio: toNullablePercent(riskAdjusted.up_capture_ratio),      // ADD
  downCaptureRatio: toNullablePercent(riskAdjusted.down_capture_ratio),  // ADD
};
```

### No changes needed:
- `BenchmarksTab.tsx` — `formatOptionalPercent` will now receive 41.1 and display "41.1%" correctly
- `usePerformanceData.ts` — pure passthrough
- `PerformanceViewContainer.tsx` — pure passthrough
- Backend — stays as raw ratios

## Verification

1. TypeScript check: `npx tsc --noEmit` for both `packages/connectors` and `packages/ui`
2. Adapter tests: Add tests in both adapter test files confirming:
   - Input `up_capture_ratio: 0.411` → output `upCaptureRatio: 41.1`
   - Input `down_capture_ratio: 0.854` → output `downCaptureRatio: 85.4`
   - Input `up_capture_ratio: null` → output `upCaptureRatio: null`
3. Browser: Navigate to Performance → Benchmarks tab, confirm Up Capture shows ~41% and Down Capture shows ~85%
4. Confirm no other metrics are affected (Sharpe, Beta, etc. should remain unchanged)

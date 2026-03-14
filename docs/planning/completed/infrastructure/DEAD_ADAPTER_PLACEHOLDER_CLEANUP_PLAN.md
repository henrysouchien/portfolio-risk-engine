# Remove Dead Adapter Placeholder Code (P6 Cleanup)

## Context

Two remaining P6 adapter gaps are dead placeholder code — not real backend gaps:
1. **1D/1W/3M period returns** hardcoded to `0` in both performance adapters. The UI period selector was trimmed to 1M/1Y in P1 cleanup. The zero entries are unreachable but still referenced by `PerformanceViewContainer` which iterates over all supported keys.
2. **HedgingAdapter placeholder fields** — `expectedCost: 0`, `protectedValue: 0`, `beforeVaR: 'N/A'`, `afterVaR: 'N/A'`, `portfolioBeta: 'N/A'`. The `RiskAnalysisModernContainer` overrides all of these with real computed values. `protectedValue` is never read anywhere.

Note: `PerformanceChart.tsx` has entirely mock data (hardcoded sine waves for ALL timeframes). That's a separate P2-level issue, out of scope here.

## Changes

### 1. Remove 1D/1W zero entries from PerformanceAdapter

**File:** `frontend/packages/connectors/src/adapters/PerformanceAdapter.ts` — lines 789-801

Delete the `"1D"` and `"1W"` entries from the `periods` object:

```typescript
// DELETE these 12 lines (789-801):
"1D": {
  portfolioReturn: 0,
  benchmarkReturn: 0,
  activeReturn: 0,
  volatility: 0
},
"1W": {
  portfolioReturn: 0,
  benchmarkReturn: 0,
  activeReturn: 0,
  volatility: 0
},
```

Keep `"1M"` and `"1Y"` which have real data.

### 2. Remove 1D/1W/3M zero entries from RealizedPerformanceAdapter

**File:** `frontend/packages/connectors/src/adapters/RealizedPerformanceAdapter.ts` — lines 169-170, 177

Delete 3 zero-entry lines:

```typescript
// DELETE these 3 lines:
'1D': { portfolioReturn: 0, benchmarkReturn: 0, activeReturn: 0, volatility: 0 },
'1W': { portfolioReturn: 0, benchmarkReturn: 0, activeReturn: 0, volatility: 0 },
'3M': { portfolioReturn: 0, benchmarkReturn: 0, activeReturn: 0, volatility: 0 },
```

Keep `"1M"`, `"1Y"`, `"YTD"` which have real data.

### 3. Update PerformanceViewContainer supportedKeys

**File:** `frontend/packages/ui/src/components/dashboard/views/modern/PerformanceViewContainer.tsx` — line 507

Change:
```typescript
const supportedKeys: PerformancePeriodKey[] = ['1D', '1W', '1M', '3M', '1Y', 'YTD'];
```
To:
```typescript
const supportedKeys: PerformancePeriodKey[] = ['1M', '1Y', 'YTD'];
```

### 4. Remove `protectedValue` from HedgingAdapter

**File:** `frontend/packages/connectors/src/adapters/HedgingAdapter.ts`

a) Remove from `HedgeStrategy` interface (line 21):
```typescript
// DELETE:
protectedValue: number;
```

b) Remove from adapter output (line 153):
```typescript
// DELETE:
protectedValue: 0,
```

### 5. Update duplicate type definitions

**File:** `frontend/packages/ui/src/components/portfolio/HedgeWorkflowDialog.tsx` — line 49

Remove `protectedValue: number;` from the local `HedgeStrategy` interface.

**File:** `frontend/packages/ui/src/components/portfolio/RiskAnalysis.tsx` — lines 32, 68

Remove `protectedValue: number` from both `HedgeStrategyDetails` interface (line 32) and the inline type (line 68).

## Files Modified

| File | Change |
|------|--------|
| `frontend/packages/connectors/src/adapters/PerformanceAdapter.ts` | Remove 1D/1W zero entries |
| `frontend/packages/connectors/src/adapters/RealizedPerformanceAdapter.ts` | Remove 1D/1W/3M zero entries |
| `frontend/packages/ui/src/components/dashboard/views/modern/PerformanceViewContainer.tsx` | Trim supportedKeys to 1M/1Y/YTD |
| `frontend/packages/connectors/src/adapters/HedgingAdapter.ts` | Remove `protectedValue` from interface + output |
| `frontend/packages/ui/src/components/portfolio/HedgeWorkflowDialog.tsx` | Remove `protectedValue` from local type |
| `frontend/packages/ui/src/components/portfolio/RiskAnalysis.tsx` | Remove `protectedValue` from 2 type definitions |

## Out of Scope

- **PerformanceChart.tsx** — Entirely mock data (sine waves). Separate P2 issue, not a placeholder removal.
- **PortfolioOverview timeframe selector** (lines 1820-1841) — Part of P4-1 dead settings state. Separate cleanup.
- **HedgingAdapter `expectedCost`/`beforeVaR`/`afterVaR`/`portfolioBeta`** — Kept as-is. `RiskAnalysisModernContainer` overrides them with real computed values (VaR from portfolio value + volatility, beta from factor data, cost from portfolio value × weight). The adapter placeholders serve as fallback values when risk data is unavailable.

## Verification

1. **Frontend typecheck**: `cd frontend && pnpm typecheck`
2. **Frontend build**: `cd frontend && pnpm build`
3. **No runtime references**: grep confirms no UI component reads `protectedValue`, no component renders 1D/1W period data

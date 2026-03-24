# Risk Drivers Tab Redesign

## Context

The Factors page has two panels: **Factor Risk Model** (left) and **Risk Analysis** (right). The right panel has three tabs: Risk Score, Stress Tests, and Hedging. The Hedging tab currently jumps straight to "here's a hedge → Implement Strategy" without giving the user context on what they're exposed to and why it matters. As a PM/analyst, you need to understand the exposure before deciding to act.

The redesign transforms "Hedging" into a **"Risk Drivers"** tab — the actionable interpretation layer, parallel to how "Model Insights" works on the left panel. The flow becomes: understand exposure → see contributing context → optionally explore hedging.

**Key finding:** The backend already returns `drivers` (type, label, percent_of_portfolio, market_beta) and `analysis_metadata` in the API response, but the frontend `HedgingAdapter` discards both — only passing through `recommendations` as `strategies`. No backend changes needed.

## Shared HedgeStrategy type

`HedgeStrategy` is currently duplicated in 3 files: `HedgingAdapter.ts`, `RiskAnalysis.tsx`, `HedgeWorkflowDialog.tsx`. As part of this change, consolidate to a **single canonical definition** exported from `HedgingAdapter.ts` (where it's already defined with the adapter). The other two files import from there. The canonical type gains `driverLabel` and `driverType`:

```typescript
// In HedgingAdapter.ts — canonical definition
export interface HedgeStrategy {
  strategy: string;
  cost: string;
  protection: string;
  duration: string;
  efficiency: 'High' | 'Medium' | 'Low';
  hedgeTicker: string;
  suggestedWeight: number;
  driverLabel: string;              // NEW: explicit join key from overexposed_label
  driverType: 'industry' | 'market'; // NEW: driver type for composite key matching
  details: { /* ... existing shape ... */ };
}
```

`RiskAnalysis.tsx` and `HedgeWorkflowDialog.tsx` delete their local copies and `import { HedgeStrategy } from '@risk/connectors'` (re-exported from connectors barrel).

## Changes

### Step 1: Update chassis type contract + descriptor

**File:** `frontend/packages/chassis/src/catalog/types.ts` (line 343)

Extend `HedgingRecommendationsSourceData` to include `drivers` and `analysisMetadata` alongside existing `strategies`. Add `driverLabel: string` to the strategy shape:

```typescript
export interface HedgingRecommendationsSourceData {
  strategies: Array<{
    // ... existing HedgeStrategy shape unchanged ...
    driverLabel: string;  // explicit join key (from overexposed_label)
    driverType: 'industry' | 'market';  // driver type for composite key
  }>;
  drivers: Array<{
    type: 'industry' | 'market';
    label: string;
    percentOfPortfolio: number | null;  // 0-1 scale (variance contribution)
    marketBeta: number | null;
  }>;
  analysisMetadata: {
    annualVolatility: number | null;
    marketBeta: number | null;
    beforeVar: number | null;
  };
}
```

**File:** `frontend/packages/chassis/src/catalog/descriptors.ts` (line 546)

Update `fields` array to declare the full output shape:

```typescript
fields: [
  { name: 'strategies', type: 'array', description: 'Top hedging strategies derived from the portfolio exposures.' },
  { name: 'drivers', type: 'array', description: 'Detected risk drivers (industry/market) with variance contribution.' },
  { name: 'analysisMetadata', type: 'object', description: 'Portfolio-level risk metrics (volatility, beta, VaR).' },
],
```

### Step 2: Update HedgingAdapter to pass through drivers + metadata

**File:** `frontend/packages/connectors/src/adapters/HedgingAdapter.ts`

Currently `transform()` returns `HedgeStrategy[]`. Change to return `HedgingRecommendationsSourceData`.

Key changes:
- **Add `driverLabel` and `driverType` to each strategy** using `driver.label` and `driver.type` (explicit join key from `overexposed_label`). This replaces the fragile approach of parsing "Hedge X exposure" text. The composite `driverType:driverLabel` key is used for joining.
- **Pass through ALL drivers** from the API response, not just ones with matching recommendations. Drivers without hedges are still valuable context.
- **Remove the `.slice(0, 3)` truncation** on strategies — let the UI decide how many to show.
- **Map `analysis_metadata`** using `toFiniteNumber()` guards (already in adapter) — all fields nullable.

```typescript
static transform(payload: PortfolioHedgingResponse | null | undefined): HedgingRecommendationsSourceData {
  if (!payload) {
    return { strategies: [], drivers: [], analysisMetadata: { annualVolatility: null, marketBeta: null, beforeVar: null } };
  }

  // ... existing strategy selection logic per driver ...
  // ADD driverLabel: driver.label to each strategy object

  // NEW: pass through ALL drivers (including those without hedge recommendations)
  const drivers = (payload.drivers ?? []).map(d => ({
    type: d.type as 'industry' | 'market',
    label: d.label,
    percentOfPortfolio: toFiniteNumber(d.percent_of_portfolio),
    marketBeta: toFiniteNumber(d.market_beta),
  }));

  const rawMeta = payload.analysis_metadata ?? {};
  const analysisMetadata = {
    annualVolatility: toFiniteNumber(rawMeta.annual_volatility),
    marketBeta: toFiniteNumber(rawMeta.market_beta),
    beforeVar: toFiniteNumber(rawMeta.before_var),
  };

  return { strategies, drivers, analysisMetadata };
}
```

### Step 3: Update resolver + hook to expose new fields

**File:** `frontend/packages/connectors/src/resolver/registry.ts` (line ~746)

Change from:
```typescript
const strategies = HedgingAdapter.transform(response);
return { strategies } as SDKSourceOutputMap['hedging-recommendations'];
```
To:
```typescript
const result = HedgingAdapter.transform(response);
return result as SDKSourceOutputMap['hedging-recommendations'];
```

**File:** `frontend/packages/connectors/src/features/hedging/hooks/useHedgingRecommendations.ts`

Expose `drivers`, `analysisMetadata`, loading/error state, and a `hasLoaded` flag to distinguish "never fetched" from "fetched with empty result":

```typescript
return useMemo(() => ({
  data: resolved.data?.strategies ?? undefined,
  drivers: resolved.data?.drivers ?? [],
  analysisMetadata: resolved.data?.analysisMetadata ?? { annualVolatility: null, marketBeta: null, beforeVar: null },
  loading: resolved.loading,
  error: resolved.error,
  hasLoaded: resolved.hasData,  // true only after a successful response
  // ... rest unchanged ...
}), [...]);
```

### Step 4: Thread new data through RiskAnalysisModernContainer

**File:** `frontend/packages/ui/src/components/dashboard/views/modern/RiskAnalysisModernContainer.tsx`

Destructure new fields from hook and thread inside the `data` prop (consistent with existing pattern):

```typescript
const {
  data: hedgingData,
  drivers: riskDrivers,
  analysisMetadata: hedgingMeta,
  loading: hedgingLoading,
  error: hedgingError,
  hasLoaded: hedgingHasLoaded,
} = useHedgingRecommendations(data?.portfolio_weights, data?.portfolio_summary?.total_value);
```

Add to `transformedData` (inside the existing `data` prop):
```typescript
hedgingStrategies: hedgingData ?? [],
riskDrivers: riskDrivers,
hedgingMetadata: hedgingMeta,
hedgingLoading: hedgingLoading,
hedgingError: hedgingError ?? null,
hedgingHasLoaded: hedgingHasLoaded,   // NEW: distinguishes "not fetched" from "empty"
```

### Step 5: Redesign the tab in RiskAnalysis.tsx

**File:** `frontend/packages/ui/src/components/portfolio/RiskAnalysis.tsx`

**5a. Rename tab label** (line 204): "Hedging" → "Risk Drivers"
Keep `value="hedging"` internally for backward compat.

**5b. Delete local `HedgeStrategy` interface** (lines 23-43). Import from `@risk/connectors` instead.

**5c. Update `data` prop interface** (add new fields inside existing `data`):
```typescript
data?: {
  // ... existing fields unchanged ...
  riskDrivers?: Array<{
    type: 'industry' | 'market';
    label: string;
    percentOfPortfolio: number | null;
    marketBeta: number | null;
  }>;
  hedgingMetadata?: {
    annualVolatility: number | null;
    marketBeta: number | null;
    beforeVar: number | null;
  };
  hedgingLoading?: boolean;
  hedgingError?: string | null;
  hedgingHasLoaded?: boolean;  // true only after successful response — distinguishes "not fetched" from "empty"
};
```

**5d. Add state** using composite key `${type}:${label}` (stable across refetches, unique across type/label combinations):
```typescript
const [expandedDriverKey, setExpandedDriverKey] = useState<string | null>(null)

// Helper to derive key from driver
const driverKey = (d: { type: string; label: string }) => `${d.type}:${d.label}`;
```

**5e. Build driver-to-hedge mapping** using composite `driverType:driverLabel` key (matches the same composite key used for UI state, prevents cross-type label collisions):
```typescript
const driverHedgeMap = useMemo(() => {
  const map = new Map<string, HedgeStrategy>();  // one best hedge per driver
  for (const hedge of hedgingStrategies) {
    if (!hedge.driverLabel || !hedge.driverType) continue;
    const key = `${hedge.driverType}:${hedge.driverLabel}`;
    // Keep only the first (best) hedge per driver — adapter already sorted by correlation then Sharpe
    if (!map.has(key)) {
      map.set(key, hedge);
    }
  }
  return map;
}, [hedgingStrategies]);
```

**Multiple hedges per driver:** The adapter already selects the single best recommendation per driver (via `byCorrelationThenSharpe` reducer). The map stores one `HedgeStrategy` per driver, not an array. If the adapter ever returns multiple per driver, only the first (best) is shown — the expanded section displays one "Suggested Hedge" with one "Implement Strategy" button.

**5f. Replace tab content** (lines 372-440). Two sections: driver cards, then summary.

```
┌──────────────────────────────────────────────┐
│ Financial - Mortgages          !! High       │
│ 24.6% of portfolio variance                 │
│ ████████████████████░░░░  (GradientProgress) │
├──────────────────────────────────────────────┤
│  [Expanded on click]                         │
│  Suggested Hedge: XYZ ETF                    │
│  Cost: ~2% allocation | Efficiency: Low      │
│  [Implement Strategy]                        │
├──────────────────────────────────────────────┤
│ Asset Management               -- Moderate   │
│ 6.8% of portfolio variance                  │
│ ████░░░░░░░░░░░░░░░░░░░  (GradientProgress) │
└──────────────────────────────────────────────┘

┌──────────────────────────────────────────────┐
│ Risk Driver Summary                          │
│ Portfolio vol: 8.3% | Beta: 0.59             │
│ 2 active risk drivers detected               │
└──────────────────────────────────────────────┘
```

Each driver card:
- **Header row:** Driver label + severity badge (High/Medium/Low)
- **Subtitle:** "X% of portfolio variance" or "Beta X.XX" for market drivers
- **GradientProgress bar** (same component as Risk Score tab)
  - For industry: scale `percentOfPortfolio` (already 0-1) × 100 for display
  - For market: scale `Math.abs(marketBeta)` × 50 (capped at 100)
- **Click to expand** (toggled via `driverKey(driver)`): If `driverHedgeMap.has(driverKey(driver))`, shows matched hedge with "Implement Strategy" button → `HedgeWorkflowDialog`. If no hedge available: show "No hedge candidates identified for this driver."

**5g. Severity classification** (using correct 0-1 scale, handling negative beta):

For industry drivers (`percentOfPortfolio` is 0-1):
- >= 0.15 → High (red)
- >= 0.08 → Medium (amber)
- < 0.08 → Low (emerald)

For market drivers (use `Math.abs(marketBeta)`):
- abs > 1.3 → High (red)
- abs > 1.0 → Medium (amber)
- abs <= 1.0 → Low (emerald)

**5h. Null metric handling:** When `percentOfPortfolio` or `marketBeta` is null for a driver:
- **Severity:** Default to "Low" (emerald)
- **Subtitle:** Show "Exposure detected" (no numeric claim)
- **GradientProgress:** Show empty bar (value=0)
- **Summary card:** Only render metric values that are non-null. If all null, show just the driver count.

**5i. Four distinct states** (not conflated). Use `hedgingHasLoaded` (threaded from hook's `hasLoaded` through container) as the discriminator:
- **Loading** (`data.hedgingLoading === true`): Show skeleton/spinner
- **Error** (`data.hedgingError` is truthy): Show error message
- **Not fetched** (`!data.hedgingHasLoaded && !data.hedgingLoading`): Show nothing (hook hasn't run yet, e.g., no weights available). Note: `riskDrivers` defaults to `[]` from the hook, so cannot be used to detect "not fetched" — `hedgingHasLoaded` is the only reliable signal.
- **Empty (successful response, zero drivers)** (`data.hedgingHasLoaded === true && data.riskDrivers?.length === 0`): Show positive card: "No significant risk drivers detected. Your portfolio variance is well-distributed."

**5j. Summary card** at bottom (like Stress Tests): Always render when `hedgingHasLoaded && riskDrivers.length > 0`. Shows driver count unconditionally. Shows portfolio vol and beta only when their respective `hedgingMetadata` values are non-null (omit the metric label entirely if null, don't show "N/A").

### Step 6: Update HedgeWorkflowDialog to use driverLabel

**File:** `frontend/packages/ui/src/components/portfolio/HedgeWorkflowDialog.tsx`

- **Delete local `HedgeStrategy` interface** (lines 37-55). Import from `@risk/connectors`.
- **Replace `inferDriverLabel()` function** (lines 165-170) which regex-parses `strategy.strategy` with direct access to `strategy.driverLabel`. This eliminates the last string-parsing fragility.
- Update any display sites that called `inferDriverLabel(strategy.strategy)` to use `strategy.driverLabel` directly.

### What does NOT change

- Backend API / service / result objects — zero changes
- Risk Score tab, Stress Tests tab — untouched
- `useHedgePreview`, `useHedgeTrade` hooks — untouched
- `HedgeWorkflowDialog` internal workflow (steps 1-4) — untouched, only type import + inferDriverLabel removal

## Files to modify

1. `frontend/packages/chassis/src/catalog/types.ts` — extend `HedgingRecommendationsSourceData` with drivers + metadata + driverLabel
2. `frontend/packages/chassis/src/catalog/descriptors.ts` — update fields array to declare drivers + analysisMetadata
3. `frontend/packages/connectors/src/adapters/HedgingAdapter.ts` — return full result with drivers + metadata + driverLabel, remove .slice(0,3), export canonical `HedgeStrategy`
4. `frontend/packages/connectors/src/resolver/registry.ts` — pass through full result
5. `frontend/packages/connectors/src/features/hedging/hooks/useHedgingRecommendations.ts` — expose drivers, metadata, loading, error
6. `frontend/packages/connectors/src/index.ts` — re-export `HedgeStrategy` from connectors barrel
7. `frontend/packages/ui/src/components/dashboard/views/modern/RiskAnalysisModernContainer.tsx` — thread all new fields inside `data` prop
8. `frontend/packages/ui/src/components/portfolio/RiskAnalysis.tsx` — delete local HedgeStrategy, import from connectors, redesign tab content + rename label
9. `frontend/packages/ui/src/components/portfolio/HedgeWorkflowDialog.tsx` — delete local HedgeStrategy, import from connectors, replace inferDriverLabel with driverLabel field

## Test plan

Update existing tests and add new cases:

1. **HedgingAdapter tests** — verify `drivers` and `analysisMetadata` are passed through; verify `driverLabel` is set on each strategy; verify drivers without recommendations are preserved; verify null/missing metadata fields handled
2. **useHedgingRecommendations tests** — update mock data to include drivers/metadata; verify loading/error states exposed; verify empty response returns typed defaults
3. **RiskAnalysis component tests** — test loading state renders skeleton; test error state renders error; test empty drivers renders "well-distributed" card; test driver cards render with correct severity badges; test expand/collapse by composite key; test driver with no hedge shows "no candidates"; test driver with hedge shows strategy + Implement button
4. **HedgeWorkflowDialog tests** — verify `driverLabel` is used (not `inferDriverLabel` string parsing)
5. **Resolver tests** — update mock to match new output shape

## Verification

1. Navigate to Factors page → Risk Drivers tab should show driver cards with variance context
2. Click a driver with a hedge → should expand to show matched hedge with "Implement Strategy"
3. Click a driver without a hedge → should expand to show "No hedge candidates identified"
4. Click "Implement Strategy" → HedgeWorkflowDialog opens and shows correct driver name (via driverLabel, not string parsing)
5. Loading state → shows spinner/skeleton (not "well-distributed")
6. Error state → shows error message (not "well-distributed")
7. Empty portfolio / no drivers (successful response) → shows "well-distributed" message
8. Run updated frontend tests to ensure no regressions

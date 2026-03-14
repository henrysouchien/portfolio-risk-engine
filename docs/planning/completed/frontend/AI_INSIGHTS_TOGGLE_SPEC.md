# Spec: AI Insights Toggle Wiring

## Context

The AI Insights feature is ~90% built. Backend generates insights from interpretive flags, API endpoint exists, frontend hook fetches data, metric cards render insights on hover — but **the toggle is not wired**. The `ViewControlsHeader` toggle component exists but isn't mounted, and `showAIInsights` is hardcoded to `true` in `PortfolioOverview`.

**What's built:**
- Backend: `mcp_tools/metric_insights.py` — `build_metric_insights()` aggregates position/risk/perf flags → per-card insights
- API: `GET /api/positions/metric-insights` → `{ insights: { totalValue: {aiInsight, aiConfidence, marketContext}, ... } }`
- Hook: `useMetricInsights()` in `connectors/src/features/positions/hooks/useMetricInsights.ts` (zero-arg today)
- Toggle component: `ViewControlsHeader` in `ui/src/components/portfolio/overview/ViewControlsHeader.tsx` (Brain icon button)
- Card rendering: `OverviewMetricCard` shows insights when `showAIInsights=true` and card is hovered
- Metrics mapping: `useOverviewMetrics.ts` maps API response to 6 metric cards (4 have insight keys; Alpha + Concentration are hardcoded empty — out of scope for this task)

**What's broken:**
1. `PortfolioOverview.tsx` line 57 — `showAIInsights` is **hardcoded `true`** (should come from toggle state)
2. `uiStore` has **no `showAIInsights` flag** — nowhere to persist toggle state
3. `ViewControlsHeader` is **not mounted** anywhere in the modern nav
4. Toggle callback `onToggleAIInsights` is **not connected** to any state
5. `useMetricInsights()` is **always called** (no `enabled` gate) — wastes an API call when insights are off

---

## Files

| File | Action |
|------|--------|
| `frontend/packages/connectors/src/stores/uiStore.ts` | **Edit** — add `showAIInsights` state + `toggleAIInsights` action + localStorage persistence |
| `frontend/packages/connectors/src/index.ts` | **Edit** — re-export `useShowAIInsights` selector |
| `frontend/packages/connectors/src/features/positions/hooks/useMetricInsights.ts` | **Edit** — accept `options?: { enabled?: boolean }`, pass to `useDataSource` |
| `frontend/packages/ui/src/components/dashboard/views/modern/PortfolioOverviewContainer.tsx` | **Edit** — read store state, pass `showAIInsights` + `onToggleAIInsights` props, gate `useMetricInsights` |
| `frontend/packages/ui/src/components/portfolio/PortfolioOverview.tsx` | **Edit** — mount `ViewControlsHeader`, accept `showAIInsights` + `onToggleAIInsights` props, replace hardcoded `true` |
| `frontend/packages/ui/src/components/portfolio/overview/types.ts` | **Edit** — add `showAIInsights?` + `onToggleAIInsights?` to `PortfolioOverviewProps` |
| `frontend/packages/ui/src/components/portfolio/overview/ViewControlsHeader.tsx` | **Edit** — add `aria-pressed` to toggle button |

---

## Step 1: Add toggle state to uiStore

**File: `frontend/packages/connectors/src/stores/uiStore.ts`**

The store uses manual `localStorage` (not Zustand `persist` middleware). Follow the same pattern as `visualStyle` / `navLayout`.

### 1a: Add localStorage reader (near `getStoredNavLayout()` ~line 123)

```typescript
function getStoredAIInsights(): boolean {
  try {
    return window.localStorage.getItem('showAIInsights') === 'true';
  } catch {
    return false;
  }
}
```

### 1b: Add to UIState interface (~line 148)

```typescript
showAIInsights: boolean;
```

### 1c: Add action to UIState interface (~line 216)

```typescript
toggleAIInsights: () => void;
```

### 1d: Add to initial state (~line 256)

```typescript
showAIInsights: getStoredAIInsights(),
```

### 1e: Add action implementation (after `setNavLayout` ~line 295)

```typescript
toggleAIInsights: () => {
  const next = !get().showAIInsights;
  try {
    window.localStorage.setItem('showAIInsights', String(next));
  } catch {
    // Ignore storage write failures and still update in-memory state.
  }
  set({ showAIInsights: next });
},
```

### 1f: Add selector export (after `useNavLayout` ~line 402)

```typescript
export const useShowAIInsights = () => useUIStore((state) => state.showAIInsights);
```

### 1g: Add to useUIActions (~line 417)

```typescript
toggleAIInsights: state.toggleAIInsights,
```

---

## Step 2: Re-export selector from connectors index

**File: `frontend/packages/connectors/src/index.ts`**

Add `useShowAIInsights` to the existing uiStore re-export block (~line 45):

```typescript
export {
  useUIStore,
  useUIActions,
  useActiveView,
  useActiveScenarioTool,
  useScenarioToolContext,
  useScenarioRouterState,
  useVisualStyle,
  useNavLayout,
  useNavigationContext,
  useShowAIInsights,        // ← add
} from './stores/uiStore';
```

---

## Step 3: Add `enabled` option to useMetricInsights

**File: `frontend/packages/connectors/src/features/positions/hooks/useMetricInsights.ts`**

The hook is currently zero-arg. `useDataSource` already supports `enabled` via its options parameter (`Pick<UseQueryOptions, 'enabled' | 'placeholderData'>`).

Change signature from:

```typescript
export const useMetricInsights = () => {
  const resolved = useDataSource('metric-insights');
```

To:

```typescript
export const useMetricInsights = (options?: { enabled?: boolean }) => {
  const resolved = useDataSource('metric-insights', undefined, {
    enabled: options?.enabled,
  });
```

---

## Step 4: Wire toggle in PortfolioOverviewContainer

**File: `frontend/packages/ui/src/components/dashboard/views/modern/PortfolioOverviewContainer.tsx`**

### 4a: Import store selector (~line 40)

```typescript
import { ..., useShowAIInsights, useUIStore } from '@risk/connectors';
```

### 4b: Read store state (inside component, after existing hooks ~line 60)

```typescript
const showAIInsights = useShowAIInsights();
const toggleAIInsights = useUIStore((s) => s.toggleAIInsights);
```

### 4c: Gate metric insights fetch (change line 80)

From:
```typescript
const { data: metricInsights } = useMetricInsights();
```

To:
```typescript
const { data: metricInsights } = useMetricInsights({ enabled: showAIInsights && hasPortfolio });
```

### 4d: Pass props to PortfolioOverview (~line 262)

Add `showAIInsights` and `onToggleAIInsights` to existing props:

```tsx
<PortfolioOverview
  data={portfolioOverviewData}
  smartAlerts={smartAlerts}
  marketEvents={marketEvents}
  aiRecommendations={aiRecommendations}
  metricInsights={metricInsights}
  performanceSparkline={performanceSparkline}
  refreshWarning={refreshWarning}
  showAIInsights={showAIInsights}
  onToggleAIInsights={toggleAIInsights}
  onRefresh={handleRefresh}
  loading={isLoading || isRefetching}
  className={props.className}
  {...props}
/>
```

---

## Step 5: Mount ViewControlsHeader inside PortfolioOverview

**File: `frontend/packages/ui/src/components/portfolio/PortfolioOverview.tsx`**

`ViewControlsHeader` is mounted here (not in the container) because `SettingsPanel` state (`settingsPanelOpen`) is local to this component (line 30). Mounting in the container would leave the Settings button dead.

### 5a: Add props to destructuring (~line 17)

```typescript
export default function PortfolioOverview({
  data,
  smartAlerts: externalAlerts = [],
  marketEvents: externalMarketEvents = [],
  aiRecommendations: externalAIRecommendations = [],
  onRefresh,
  loading = false,
  refreshWarning,
  metricInsights = {},
  performanceSparkline,
  showAIInsights = false,
  onToggleAIInsights,
}: PortfolioOverviewProps) {
```

### 5b: Mount ViewControlsHeader (at top of JSX, before alerts ~line 41)

```tsx
<div className="space-y-8">
  {onToggleAIInsights && (
    <ViewControlsHeader
      showAIInsights={showAIInsights}
      onToggleAIInsights={onToggleAIInsights}
      onRefresh={onRefresh ?? (() => {})}
      onOpenSettings={() => setSettingsPanelOpen(true)}
      loading={loading}
      lastUpdated={data?.summary?.lastUpdated}
    />
  )}
  {refreshWarning && (
```

### 5c: Replace hardcoded `showAIInsights` (~line 57)

From:
```tsx
showAIInsights
```

To:
```tsx
showAIInsights={showAIInsights}
```

### 5d: Add import for ViewControlsHeader

`ViewControlsHeader` is already exported from the `./overview` barrel — add to existing import:

```typescript
import {
  AIRecommendationsPanel,
  MarketIntelligenceBanner,
  OverviewMetricCard,
  PartialRefreshWarningBanner,
  SettingsPanel,
  SmartAlertsPanel,
  useOverviewMetrics,
  ViewControlsHeader,       // ← add
} from "./overview"
```

---

## Step 6: Update PortfolioOverviewProps type

**File: `frontend/packages/ui/src/components/portfolio/overview/types.ts`**

Add to `PortfolioOverviewProps` (~line 98):

```typescript
export interface PortfolioOverviewProps {
  data?: PortfolioOverviewData
  smartAlerts?: SmartAlert[]
  marketEvents?: MarketEvent[]
  aiRecommendations?: AIRecommendation[]
  metricInsights?: Record<string, MetricInsight>
  performanceSparkline?: number[]
  refreshWarning?: PortfolioRefreshWarning | null
  onRefresh?: () => void
  loading?: boolean
  className?: string
  showAIInsights?: boolean          // ← add
  onToggleAIInsights?: () => void   // ← add
}
```

---

## Step 7: Add aria-pressed to ViewControlsHeader

**File: `frontend/packages/ui/src/components/portfolio/overview/ViewControlsHeader.tsx`**

Add `aria-pressed` to the AI Insights toggle button for accessibility (~line 28):

```tsx
<Button
  variant="ghost"
  size="sm"
  onClick={onToggleAIInsights}
  aria-pressed={showAIInsights}
  className={`text-xs ${showAIInsights ? "bg-blue-100 text-blue-700" : ""}`}
>
```

---

## Verification

```bash
cd frontend && npx tsc --noEmit  # Zero TS errors
```

Visual checks at localhost:3000:
- Dashboard loads with AI Insights toggle **off** by default
- Metric cards show NO insight overlays
- Click Brain icon → toggle turns blue → 4 metric cards show insights on hover (totalValue, ytdReturn, riskScore, sharpeRatio — Alpha + Concentration have no insights, known out of scope)
- Click Brain icon again → toggle turns off → insights disappear
- Refresh page → toggle state persists via localStorage
- No API call to `/api/positions/metric-insights` when toggle is off (check Network tab)

---

## Known limitations (out of scope)

- **4/6 card coverage**: `useOverviewMetrics` only maps insight keys for `totalValue`, `ytdReturn`, `riskScore`, `sharpeRatio`. Alpha and Concentration cards have hardcoded empty insights. Expanding coverage requires `useOverviewMetrics` changes — separate task.
- **Backend key mismatch**: Backend emits keys like `dayChange`, `maxDrawdown`, `volatilityAnnual` that no card currently renders. Aligning these is a separate task.

---

## Summary

| What | Action |
|------|--------|
| `uiStore.ts` (connectors) | Add `showAIInsights` boolean + `toggleAIInsights()` + localStorage + `useShowAIInsights` selector (~12 lines) |
| `connectors/index.ts` | Re-export `useShowAIInsights` (~1 line) |
| `useMetricInsights.ts` | Accept `options?: { enabled?: boolean }`, pass to `useDataSource` (~3 lines) |
| `PortfolioOverviewContainer.tsx` | Read store, gate fetch, pass props (~6 lines) |
| `PortfolioOverview.tsx` | Mount `ViewControlsHeader`, accept + pass props (~10 lines) |
| `types.ts` | Add `showAIInsights?` + `onToggleAIInsights?` to props (~2 lines) |
| `ViewControlsHeader.tsx` | Add `aria-pressed` (~1 line) |
| **Net change** | **~35 lines across 7 files** |

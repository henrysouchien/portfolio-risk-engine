# Codex Spec: Dashboard Enrichment (Phase 4)

**Goal**: Upgrade the Overview (`score`) view from hero + 2-column grid into a morning-briefing surface with holdings, alerts, performance strip, and income projection.

**Depends on**: Phase 2 (ResearchContainer must exist for holding-row exit ramps)

---

## Step 0: Store Plumbing — NavigationContext

Cross-view exit ramps (click holding row → Research with ticker, click alert → relevant view) need a typed store mechanism.

### File: `frontend/packages/connectors/src/stores/uiStore.ts`

**0a. Add typed interface** (above `UIState` interface, ~line 75):

```typescript
export interface NavigationContext {
  ticker?: string;
  direction?: 'buy' | 'sell';
  source?: string;
  [key: string]: unknown;
}
```

**0b. Add to UIState interface** (~line 80):

```typescript
navigationContext: NavigationContext | null;
setNavigationContext: (ctx: NavigationContext | null) => void;
```

**0c. Add initial state + action in `create()` call** (~line 196):

```typescript
navigationContext: null,
setNavigationContext: (ctx) => set({ navigationContext: ctx }),
```

**0d. Add to `useUIActions` selector** (~line 347). This selector is **manually assembled** — new actions are NOT auto-included:

```typescript
setNavigationContext: s.setNavigationContext,
```

**0e. Add selector:**

```typescript
export const useNavigationContext = () => useUIStore((s) => s.navigationContext);
```

### File: `frontend/packages/connectors/src/index.ts`

Add root barrel exports (~line 41, alongside existing uiStore exports):

```typescript
export { useNavigationContext } from './stores/uiStore';
export type { NavigationContext } from './stores/uiStore';
```

### Verification

```bash
cd frontend && npx tsc --noEmit  # Zero errors
```

Test in browser console or a quick component:
```typescript
const { setNavigationContext } = useUIActions();
setNavigationContext({ ticker: 'AAPL' });
// useNavigationContext() should return { ticker: 'AAPL' }
```

---

## Step 1: DashboardHoldingsCard

### File: `frontend/packages/ui/src/components/dashboard/cards/DashboardHoldingsCard.tsx` (~130 lines)

**Create** — compact holdings table for the dashboard.

#### Data

```typescript
import { usePositions, useUIActions } from '@risk/connectors';

const { data: positionsData, loading } = usePositions();
const { setActiveView, setNavigationContext } = useUIActions();
const holdings = positionsData?.holdings ?? [];
```

`usePositions()` returns `{ data: PositionsData | undefined, loading, ... }` where `PositionsData.holdings` is `PositionsHolding[]`.

**Type import note**: `PositionsHolding` is exported from `PositionsAdapter.ts` but NOT re-exported from the `@risk/connectors` barrel. Either:
- Add `export type { PositionsHolding } from './adapters/PositionsAdapter';` to `connectors/src/index.ts`, OR
- Infer the type: `type Holding = NonNullable<ReturnType<typeof usePositions>['data']>['holdings'][number]`

Recommended: add the barrel export. Same applies to `SmartAlert` from `useSmartAlerts.ts` — add:
```typescript
// In connectors/src/index.ts:
export type { PositionsHolding } from './adapters/PositionsAdapter';
export type { SmartAlert } from './features/positions/hooks/useSmartAlerts';
```

#### Props on each PositionsHolding (from PositionsAdapter)

Relevant fields:
- `ticker: string`, `name: string`, `value: number`, `weight: number`
- `dayChange?: number`, `dayChangePercent?: number`
- `alerts?: number` (count), `alertDetails?: Array<{ severity: string; message: string }>`

#### Structure

```tsx
import { DataTable, type DataTableColumn } from '../../blocks/data-table';
import { Card, CardContent, CardHeader, CardTitle } from '../../ui/card';
import { Button } from '../../ui/button';
import { Badge } from '../../ui/badge';
import { ChevronRight } from 'lucide-react';

// Sort by weight descending, take top 10
const topHoldings = useMemo(() =>
  [...holdings].sort((a, b) => b.weight - a.weight).slice(0, 10),
  [holdings]
);

const handleRowClick = (holding: PositionsHolding) => {
  setNavigationContext({ ticker: holding.ticker, source: 'dashboard-holdings' });
  setActiveView('research');
};
```

**Important**: `DataTable` does NOT have an `onRowClick` prop. It only supports `hoveredRow`/`onHoveredRowChange` for hover state. To make rows clickable, wrap the ticker cell in a clickable element within the column's `render` function.

Columns for DataTable:
| Key | Label | Render |
|-----|-------|--------|
| `ticker` | Ticker | Clickable link-styled text that calls `handleRowClick(row)` + alert badge if `alerts > 0` |
| `name` | Name | Truncated to ~20 chars |
| `value` | Value | Formatted currency |
| `weight` | Weight | `{weight.toFixed(1)}%` |
| `dayChangePercent` | Day | Green/red with `+`/`-` prefix |

Ticker column render (clickable):
```tsx
{
  key: 'ticker',
  label: 'Ticker',
  sortable: true,
  render: (row) => (
    <button
      className="font-semibold text-left hover:text-emerald-600 hover:underline transition-colors"
      onClick={() => handleRowClick(row)}
    >
      {row.ticker}
      {row.alerts && row.alerts > 0 && (
        <Badge variant="destructive" className="ml-1 text-xs">{row.alerts}</Badge>
      )}
    </button>
  ),
}
```

DataTable props:
```typescript
<DataTable
  columns={columns}
  data={topHoldings}
  keyExtractor={(row) => row.id}
  sortField="weight"
  sortDirection="desc"
  onSort={handleSort}
/>
```

Footer: `<Button variant="ghost" onClick={() => setActiveView('holdings')}>View All {holdings.length} Holdings <ChevronRight /></Button>`

#### Loading state

When `loading` is true, render a skeleton placeholder (use existing `Skeleton` from `../../ui/skeleton`).

---

## Step 2: DashboardAlertsPanel

### File: `frontend/packages/ui/src/components/dashboard/cards/DashboardAlertsPanel.tsx` (~160 lines)

**Create** — aggregated alerts panel with navigation actions.

#### Data

```typescript
import { useSmartAlerts, useRiskScore, useUIActions } from '@risk/connectors';
import { FLAG_TYPE_NAVIGATION, FLAG_TYPE_TITLES } from '@risk/connectors';
// Note: alertMappings exports may need to be added to connectors barrel if not already

const { data: alerts, loading: alertsLoading } = useSmartAlerts();
const { data: riskData, loading: riskLoading } = useRiskScore();
const { setActiveView } = useUIActions();
```

**alertMappings barrel check**: `FLAG_TYPE_NAVIGATION` and `FLAG_TYPE_TITLES` are in `connectors/src/features/notifications/alertMappings.ts`. Verify they're exported from the connectors root barrel. If not, add:
```typescript
// In connectors/src/index.ts:
export { FLAG_TYPE_NAVIGATION, FLAG_TYPE_TITLES } from './features/notifications/alertMappings';
```

#### Risk score → alert derivation

`useRiskScore().data` has `component_scores` typed as `Array<{ name: string; score: number; maxScore: number }>` (NOT a Record). The adapter transforms the backend dict into this array in `RiskScoreAdapter.ts` lines 387-426. Names are human-readable: `"Concentration Risk"`, `"Volatility Risk"`, `"Factor Risk"`, `"Sector Risk"`.

```typescript
const riskAlerts = useMemo(() => {
  const scores = riskData?.component_scores;
  if (!Array.isArray(scores)) return [];
  return scores
    .filter((cs) => cs.score > 75)
    .map((cs) => ({
      id: `risk-${cs.name}`,
      type: 'risk' as const,
      severity: cs.score > 90 ? 'critical' as const : 'warning' as const,
      message: `${cs.name}: ${cs.score}/${cs.maxScore}`,
      flagType: cs.name,  // Note: human-readable name, not snake_case
      actionable: true,
      dismissible: false,
    }));
}, [riskData]);
```

#### Combined + sorted alerts

```typescript
const allAlerts = useMemo(() => {
  const combined = [...alerts, ...riskAlerts];
  const severityOrder = { critical: 0, warning: 1, info: 2 };
  return combined.sort((a, b) =>
    (severityOrder[a.severity] ?? 3) - (severityOrder[b.severity] ?? 3)
  );
}, [alerts, riskAlerts]);
```

#### Structure

```tsx
<Card>
  <CardHeader><CardTitle>Alerts</CardTitle></CardHeader>
  <CardContent>
    {allAlerts.slice(0, maxVisible).map(alert => (
      <AlertRow key={alert.id} alert={alert} />
    ))}
    {allAlerts.length > maxVisible && (
      <Button variant="ghost" onClick={() => setExpanded(!expanded)}>
        {expanded ? 'Show less' : `View all ${allAlerts.length}`}
      </Button>
    )}
  </CardContent>
</Card>
```

Local state: `const [expanded, setExpanded] = useState(false);` — `maxVisible = expanded ? allAlerts.length : 5`

#### AlertRow subcomponent

Risk-derived alerts use human-readable `flagType` values (e.g., `"Concentration Risk"`) which are NOT keys in `FLAG_TYPE_NAVIGATION` (which uses snake_case like `"sector_concentration"`). For risk-derived alerts, hardcode navigation to `'research'` (where RiskAnalysisModernContainer lives after Phase 2).

For `useSmartAlerts()` alerts, `FLAG_TYPE_NAVIGATION` keys match because they come from the backend flag system.

```tsx
function AlertRow({ alert }: { alert: { id: string; severity: string; message: string; flagType?: string; ticker?: string; type?: string } }) {
  const { setActiveView } = useUIActions();

  // Risk-derived alerts (from component_scores) → navigate to research
  // SmartAlerts (from backend flags) → use FLAG_TYPE_NAVIGATION lookup
  const getNav = () => {
    if (alert.type === 'risk') {
      return { view: 'research' as const, label: 'View risk analysis' };
    }
    return alert.flagType ? FLAG_TYPE_NAVIGATION[alert.flagType] : null;
  };
  const nav = getNav();

  return (
    <div className="flex items-center gap-3 py-2 border-b last:border-0">
      <SeverityIcon severity={alert.severity} />
      <span className="flex-1 text-sm">{alert.message}</span>
      {alert.ticker && <Badge variant="outline">{alert.ticker}</Badge>}
      {nav && (
        <Button variant="ghost" size="sm" onClick={() => setActiveView(nav.view)}>
          {nav.label}
        </Button>
      )}
    </div>
  );
}
```

Severity icons: `AlertTriangle` (critical, red), `AlertCircle` (warning, amber), `Info` (info, blue) from `lucide-react`.

**Note on `FLAG_TYPE_NAVIGATION` stale routing**: After Phase 4, `RiskAnalysisModernContainer` is no longer on the `score` view — it moves to Research (Phase 2). Five entries in `alertMappings.ts` (lines 39-43) still point to `view: 'score'` with label `"View risk analysis"`. Update these to `view: 'research'`:

```typescript
// alertMappings.ts — update lines 39-43:
high_leverage: { view: 'research', label: 'View risk analysis' },
leveraged: { view: 'research', label: 'View risk analysis' },
futures_high_notional: { view: 'research', label: 'View risk analysis' },
sector_concentration: { view: 'research', label: 'View risk analysis' },
low_sector_diversification: { view: 'research', label: 'View risk analysis' },
```

---

## Step 3: DashboardPerformanceStrip

### File: `frontend/packages/ui/src/components/dashboard/cards/DashboardPerformanceStrip.tsx` (~90 lines)

**Create** — horizontal metrics strip.

#### Data

```typescript
import { usePerformance, useUIActions } from '@risk/connectors';
import { StatPair } from '../../blocks/stat-pair';

const { data: perfData, loading } = usePerformance();
const { setActiveView } = useUIActions();
```

`usePerformance()` returns `{ data: PerformanceData, loading, ... }`. The performance data is already called by `PortfolioOverviewContainer` — TanStack Query shared cache means no duplicate API call.

#### PerformanceData field paths

`PerformanceData` (from `PerformanceAdapter.ts`) has nested fields, NOT flat top-level ones:

| Metric | Field path | Type |
|--------|-----------|------|
| Annualized Return | `data.returns.annualizedReturn` | `number` (decimal) |
| Alpha | `data.performanceSummary.riskMetrics.alpha` | `number` (raw) |
| Sharpe Ratio | `data.performanceSummary.riskMetrics.sharpeRatio` | `number` |
| Volatility | `data.risk.volatility` | `number` (decimal) |

`data.benchmark.*` fields are pre-formatted strings (e.g., `alpha: "1.23%"`). Use `performanceSummary.riskMetrics.*` for raw numbers suitable for formatting.

#### Structure

```tsx
<Card
  className="cursor-pointer hover:bg-neutral-50 transition-colors"
  onClick={() => setActiveView('performance')}
>
  <CardContent className="py-4">
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      <StatPair
        label="Annualized Return"
        value={formatPercent(perfData?.returns?.annualizedReturn)}
        valueColor={(perfData?.returns?.annualizedReturn ?? 0) >= 0 ? 'positive' : 'negative'}
      />
      <StatPair
        label="Alpha"
        value={formatPercent(perfData?.performanceSummary?.riskMetrics?.alpha)}
        valueColor={(perfData?.performanceSummary?.riskMetrics?.alpha ?? 0) >= 0 ? 'positive' : 'negative'}
      />
      <StatPair
        label="Sharpe Ratio"
        value={perfData?.performanceSummary?.riskMetrics?.sharpeRatio?.toFixed(2) ?? '—'}
        valueColor="neutral"
      />
      <StatPair
        label="Volatility"
        value={formatPercent(perfData?.risk?.volatility)}
        valueColor="muted"
      />
    </div>
  </CardContent>
</Card>
```

StatPair props: `{ label: string; value: ReactNode; valueColor?: 'positive' | 'negative' | 'warning' | 'neutral' | 'muted' }`.

Helper:
```typescript
const formatPercent = (v?: number) => v != null ? `${v >= 0 ? '+' : ''}${v.toFixed(2)}%` : '—';
```

---

## Step 4: DashboardIncomeCard

### File: `frontend/packages/ui/src/components/dashboard/cards/DashboardIncomeCard.tsx` (~80 lines)

**Create** — income summary card using the placeholder resolver.

#### Data

```typescript
import { useDataSource } from '@risk/connectors';
import { StatPair } from '../../blocks/stat-pair';

// Uses placeholder resolver directly — no dedicated hook needed in Phase 4.
// Phase 6 will upgrade the resolver to call the real backend.
const resolved = useDataSource('income-projection');
const income = resolved.data;
```

The placeholder resolver (registry.ts lines 740-760) returns:
```typescript
{
  annual_income: number;           // sum of each holding's market_value * 0.015
  projected_cashflow: {
    monthly: number;
    quarterly: number;
    yearly: number;
  };
  assumptions: {
    dividendYield: number;         // 0.015
    source: 'frontend-estimate';
  };
}
```

#### Structure

**Type safety note**: `IncomeProjectionSourceData.assumptions` is typed as `Record<string, unknown>` in `chassis/catalog/types.ts`. Fields like `dividendYield` and `source` are `unknown`, requiring explicit type narrowing or number guards.

```tsx
// Narrow the assumptions fields safely
const dividendYield = typeof income?.assumptions?.dividendYield === 'number'
  ? income.assumptions.dividendYield
  : null;
const isEstimate = income?.assumptions?.source === 'frontend-estimate';

<Card>
  <CardHeader><CardTitle>Income Projection</CardTitle></CardHeader>
  <CardContent>
    <div className="grid grid-cols-3 gap-4">
      <StatPair
        label="Annual Income"
        value={income ? formatCurrency(income.annual_income) : '—'}
        valueColor="positive"
      />
      <StatPair
        label="Monthly Rate"
        value={income?.projected_cashflow?.monthly != null
          ? formatCurrency(income.projected_cashflow.monthly as number)
          : '—'}
        valueColor="neutral"
      />
      <StatPair
        label="Est. Yield"
        value={dividendYield != null
          ? `${(dividendYield * 100).toFixed(1)}%`
          : '—'}
        valueColor="muted"
      />
    </div>
    {isEstimate && (
      <p className="text-xs text-neutral-400 mt-2">Estimated from 1.5% average yield</p>
    )}
  </CardContent>
</Card>
```

**`projected_cashflow` type note**: The chassis type defines it as `Record<string, number>`, so accessing `.monthly` returns `number | undefined`. The cast to `number` is safe after the `!= null` guard.

Helper:
```typescript
const formatCurrency = (v?: number) => v != null
  ? `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
  : '—';
```

---

## Step 5: Barrel Export

### File: `frontend/packages/ui/src/components/dashboard/cards/index.ts`

**Create**:

```typescript
export { default as DashboardHoldingsCard } from './DashboardHoldingsCard';
export { default as DashboardAlertsPanel } from './DashboardAlertsPanel';
export { default as DashboardPerformanceStrip } from './DashboardPerformanceStrip';
export { default as DashboardIncomeCard } from './DashboardIncomeCard';
```

Each card component must `export default` for this to work.

---

## Step 6: Update Dashboard Layout

### File: `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx`

**6a. Add imports** (near top, after existing imports):

```typescript
import { DashboardHoldingsCard, DashboardAlertsPanel, DashboardPerformanceStrip, DashboardIncomeCard } from '../dashboard/cards';
```

These are directly imported (not React.lazy) — they're small and on the primary view.

**6b. Replace `case 'score':` block** (currently lines 373-391).

Before:
```tsx
<div className="space-organic animate-stagger-fade-in">
  <div className="hover-lift-premium">
    <PortfolioOverviewContainer />
  </div>
  <div className="grid grid-cols-1 xl:grid-cols-2 gap-8">
    <div className="hover-lift-premium animate-magnetic-hover">
      <AssetAllocationContainer />
    </div>
    <div className="glass-premium rounded-3xl morph-border hover-lift-premium">
      <RiskAnalysisModernContainer />
    </div>
  </div>
</div>
```

After:
```tsx
<div className="space-organic animate-stagger-fade-in">
  {/* Hero — existing */}
  <div className="hover-lift-premium">
    <PortfolioOverviewContainer />
  </div>

  {/* Holdings + Alerts — new */}
  <div className="grid grid-cols-1 xl:grid-cols-2 gap-8">
    <DashboardHoldingsCard />
    <DashboardAlertsPanel />
  </div>

  {/* Performance strip — new */}
  <DashboardPerformanceStrip />

  {/* Asset Allocation + Income — modified row */}
  <div className="grid grid-cols-1 xl:grid-cols-2 gap-8">
    <div className="hover-lift-premium animate-magnetic-hover">
      <AssetAllocationContainer />
    </div>
    <DashboardIncomeCard />
  </div>
</div>
```

**RiskAnalysisModernContainer** is removed from the dashboard. It now lives in Research > Portfolio Risk (Phase 2). The dashboard keeps the hero risk score from `PortfolioOverviewContainer`.

**6c. Update `default:` branch** (lines 470-485). `RiskAnalysisModernContainer` is also rendered in the `default` case — replace it with the same enriched layout:

```tsx
default:
  return (
    <div className="space-organic animate-stagger-fade-in">
      <div className="hover-lift-premium">
        <PortfolioOverviewContainer />
      </div>
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-8">
        <DashboardHoldingsCard />
        <DashboardAlertsPanel />
      </div>
      <DashboardPerformanceStrip />
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-8">
        <div className="hover-lift-premium animate-magnetic-hover">
          <AssetAllocationContainer />
        </div>
        <DashboardIncomeCard />
      </div>
    </div>
  );
```

**6d. Remove RiskAnalysisModernContainer import** — after both `case 'score':` and `default:` are updated, the import is unused. Remove from the import block (line ~74):

```typescript
// In the named import from '../dashboard/views/modern':
// REMOVE: RiskAnalysisModernContainer
```

---

## Step 7: ResearchContainer — NavigationContext Consumer

**⚠ PHASE 2 PREREQUISITE**: Steps 7 and 8 can only be implemented AFTER Phase 2 lands `ResearchContainer.tsx`. If Phase 2 is not yet merged, skip Steps 7-8 entirely — the dashboard cards (Steps 1-6) are self-contained and work without exit-ramp navigation. When Phase 2 merges, apply Steps 7-8 as a follow-up.

### File: `frontend/packages/ui/src/components/dashboard/views/modern/ResearchContainer.tsx` (Phase 2 file)

Add ticker prefill support. This must be done AFTER Phase 2 creates the file.

**7a. Add imports:**

```typescript
import { useNavigationContext, useUIActions } from '@risk/connectors';
import type { NavigationContext } from '@risk/connectors';
```

**7b. Add context consumer logic:**

```typescript
const navCtx = useNavigationContext();
const { setNavigationContext } = useUIActions();

// On mount or context change, switch to stock-lookup and pass ticker
useEffect(() => {
  if (navCtx?.ticker) {
    setSubView('stock-lookup');
    setInitialTicker(navCtx.ticker as string);
    setNavigationContext(null);  // clear after consuming
  }
}, [navCtx, setNavigationContext]);

const [initialTicker, setInitialTicker] = useState<string | null>(null);
```

**7c. Pass to StockLookupContainer:**

```tsx
<StockLookupContainer initialTicker={initialTicker} />
```

### File: `frontend/packages/ui/src/components/dashboard/views/modern/StockLookupContainer.tsx`

**7d. Add `initialTicker` prop:**

`StockLookupContainer` currently spreads `...props` to the inner `StockLookup` component. The new `initialTicker` prop must NOT be spread to the child (since `StockLookupProps` doesn't define it). Destructure it out.

At the component definition (~line 157), extend the existing props:

```typescript
interface StockLookupContainerProps {
  className?: string;
  initialTicker?: string | null;
}

export default function StockLookupContainer({ className, initialTicker, ...props }: StockLookupContainerProps) {
  // ... existing body
```

**Important**: `initialTicker` must be destructured separately so it does NOT spread into child component props.

**7e. Add mount-time effect** (~after state declarations, line 178):

```typescript
useEffect(() => {
  if (initialTicker) {
    setSelectedSymbol(initialTicker);
    setSearchTerm(initialTicker);
  }
}, [initialTicker]);
```

This triggers the existing `useEffect` that calls `analyzeStock()` when `selectedSymbol` changes (lines 251-255), so the stock loads automatically.

---

## Step 8: Alert Routing Consistency

### 8a. Update stale navigation mappings

### File: `frontend/packages/connectors/src/features/notifications/alertMappings.ts`

Five entries (lines 39-43) still point to `view: 'score'` with label `"View risk analysis"`. Since `RiskAnalysisModernContainer` moves from the dashboard to Research in Phase 2, update these:

```typescript
// BEFORE (lines 39-43):
high_leverage: { view: 'score', label: 'View risk analysis' },
leveraged: { view: 'score', label: 'View risk analysis' },
futures_high_notional: { view: 'score', label: 'View risk analysis' },
sector_concentration: { view: 'score', label: 'View risk analysis' },
low_sector_diversification: { view: 'score', label: 'View risk analysis' },

// AFTER:
high_leverage: { view: 'research', label: 'View risk analysis' },
leveraged: { view: 'research', label: 'View risk analysis' },
futures_high_notional: { view: 'research', label: 'View risk analysis' },
sector_concentration: { view: 'research', label: 'View risk analysis' },
low_sector_diversification: { view: 'research', label: 'View risk analysis' },
```

### 8b. Add barrel exports

### File: `frontend/packages/connectors/src/index.ts`

Add (if not already exported):
```typescript
export { FLAG_TYPE_NAVIGATION, FLAG_TYPE_TITLES } from './features/notifications/alertMappings';
```

The DashboardAlertsPanel uses these to determine click-through navigation for each alert, ensuring consistency with the existing notification system's routing.

---

## Import Summary

| Card | Hooks Used | Shared Cache? |
|------|-----------|--------------|
| DashboardHoldingsCard | `usePositions()` | Yes — HoldingsViewModernContainer uses same query key |
| DashboardAlertsPanel | `useSmartAlerts()`, `useRiskScore()` | `useSmartAlerts()` shared with PortfolioOverviewContainer; `useRiskScore()` is a new call on this view (previously only in RiskAnalysisModernContainer, now removed from dashboard) |
| DashboardPerformanceStrip | `usePerformance()` | Yes — PortfolioOverviewContainer uses same query key |
| DashboardIncomeCard | `useDataSource('income-projection')` | Standalone (placeholder resolver) |

All hooks use TanStack Query shared cache. Even `useRiskScore()` — while not shared with another component on the same view — will use the TanStack Query cache if already fetched by another view. All data loads in parallel.

---

## Files Changed

| File | Action |
|------|--------|
| `connectors/src/stores/uiStore.ts` | Edit — add NavigationContext type, state, action, useUIActions entry, selector |
| `connectors/src/index.ts` | Edit — add useNavigationContext, NavigationContext, PositionsHolding, SmartAlert, alertMappings exports |
| `ui/src/components/dashboard/cards/DashboardHoldingsCard.tsx` | **Create** |
| `ui/src/components/dashboard/cards/DashboardAlertsPanel.tsx` | **Create** |
| `ui/src/components/dashboard/cards/DashboardPerformanceStrip.tsx` | **Create** |
| `ui/src/components/dashboard/cards/DashboardIncomeCard.tsx` | **Create** |
| `ui/src/components/dashboard/cards/index.ts` | **Create** |
| `ui/src/components/apps/ModernDashboardApp.tsx` | Edit — import cards, replace `case 'score':` + `default:` layouts, remove RiskAnalysisModernContainer import |
| `ui/src/components/dashboard/views/modern/ResearchContainer.tsx` | Edit — add navigationContext consumer (Phase 2 prerequisite) |
| `ui/src/components/dashboard/views/modern/StockLookupContainer.tsx` | Edit — add initialTicker prop (destructured, not spread) + mount effect |
| `connectors/src/features/notifications/alertMappings.ts` | Edit — update 5 entries from `view: 'score'` to `view: 'research'` |

---

## Verification

```bash
cd frontend && npx tsc --noEmit  # Zero TS errors
```

Visual checks at localhost:3000:
- Dashboard shows: hero metrics → holdings table + alerts → performance strip → asset allocation + income
- Holdings table shows top 10 by weight, sorted descending
- Alert badges appear on holdings with `alerts > 0`
- Click holding row → navigates to Research, Stock Lookup sub-view, ticker pre-filled
- Alerts panel shows severity-sorted list (critical → warning → info)
- Click alert action button → navigates to correct view per `FLAG_TYPE_NAVIGATION`
- Performance strip shows 4 metrics, click anywhere → navigates to Performance
- Income card shows placeholder estimate with "Estimated from 1.5% average yield" note
- All cards load data in parallel (no waterfall)
- RiskAnalysisModernContainer no longer appears on dashboard (lives in Research)

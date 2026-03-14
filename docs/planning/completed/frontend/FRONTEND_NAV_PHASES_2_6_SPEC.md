# Frontend Navigation Restructure — Implementation Specs (Phases 2-6)

## Context

The `FRONTEND_NAV_SYNTHESIS_PLAN.md` defines a 7-phase frontend restructure from 7 nav items to 5 sections. Phases 0-1 (sidebar creation + nav item reduction) are already specified in `CODEX_SIDEBAR_NAV_SPEC.md`. This plan provides Codex-level implementation specs for **Phases 2-6**: the content-area work that reorganizes, decomposes, and enriches the views.

Each phase is designed as a self-contained spec that can be handed to a Codex agent for execution.

---

## Phase 2: Research Merge

**Goal**: Combine Factor Analysis + Risk Analysis + Stock Lookup into one Research section with two sub-views: Portfolio Risk | Stock Lookup.

### Files to Create

**1. `frontend/packages/ui/src/components/dashboard/views/modern/ResearchContainer.tsx` (~120 lines)**

Orchestrator with segmented control. No data hooks of its own — purely a routing shell.

```typescript
interface ResearchContainerProps {
  className?: string;
}
type ResearchSubView = 'portfolio-risk' | 'stock-lookup';
```

Structure:
- Local state: `useState<ResearchSubView>('portfolio-risk')`
- Segmented control using existing `Tabs`/`TabsList`/`TabsTrigger` from `../../../ui/tabs`
- When `portfolio-risk`: render `FactorRiskModelContainer` + `RiskAnalysisModernContainer` in a `grid grid-cols-1 xl:grid-cols-2 gap-8` (side-by-side on wide viewports, stacked on narrow). Each section gets a `SectionHeader` (icon badge + title) for visual hierarchy — "Factor Exposure" (BarChart3, blue scheme) and "Risk Analysis" (Shield, amber scheme).
- Exit ramp strip below the grid (see below)
- When `stock-lookup`: render `StockLookupContainer` as-is
- All children wrapped in `DashboardErrorBoundary`
- Export as default for React.lazy() compatibility
- Apply `animate-stagger-fade-in` with `animationDelay` on each section for cascading entrance

Exit ramp strip (bottom of Portfolio Risk sub-view):
- Wrap in `Card variant="glassTinted"` with `flex gap-4 p-4` to visually separate from analysis content above
- "Simulate hedge →" — calls `useUIActions().setActiveView('scenarios')`
- "Run stress test →" — calls `useUIActions().setActiveView('scenarios')`
- Style: `Button variant="outline"` with emerald `ChevronRight` icon (`text-emerald-600`), `hover-lift-subtle` class for tactile feedback. This exit ramp pattern is reused in Phases 4 and 5 — keep it consistent.

Imports:
- `FactorRiskModelContainer` from `./FactorRiskModelContainer`
- `RiskAnalysisModernContainer` from `./RiskAnalysisModernContainer`
- `StockLookupContainer` from `./StockLookupContainer`
- `DashboardErrorBoundary` from `../../shared` (barrel export from `dashboard/shared/index.ts`)
- `useUIActions` from `@risk/connectors`
- `Tabs, TabsList, TabsTrigger, TabsContent` from `../../../ui/tabs`
- `Button` from `../../../ui/button`
- `ChevronRight` from `lucide-react`

### Files to Modify

**2. `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx`**

- Add lazy import: `const ResearchContainer = React.lazy(() => import('../dashboard/views/modern/ResearchContainer'));`
- In `renderMainContent()`:
  - `case 'research':` → render `<ResearchContainer />` (currently renders `<StockLookupContainer />`)
  - `case 'factors':` → redirect to `research` (add `useEffect` that calls `setActiveView('research')` when `activeView === 'factors'`, matching the existing `connections` → `score` redirect pattern at lines 214-217)
- Remove separate lazy import of `FactorRiskModelContainer` (line ~105) — BUT only AFTER the `'factors'` render branch (line ~402) is rewritten to redirect. The redirect `useEffect` must be added first, then the old `case 'factors':` branch that renders `FactorRiskModelContainer` directly can be removed, then the import can be removed. Order matters — removing the import before changing the render path will break the build.
- **Important**: In `case 'score':` (lines 373-391), `RiskAnalysisModernContainer` remains for now. It will be removed from the score view in Phase 4 when the dashboard is recomposed. Do NOT remove it in Phase 2 — otherwise the dashboard loses risk analysis before Research is wired as its new home.

**3. `frontend/packages/connectors/src/utils/NavigationIntents.ts`**

- Add `'navigate-to-scenario-tool'` to the `NavigationIntent` union type (line ~35)
- This intent carries payload `{ tool: 'whatif' | 'stress-tests' | 'monte-carlo' | ... }` for Phase 3 exit ramps
- **Note**: This file change is a Phase 2 prerequisite that Phase 3 depends on. The intent type must exist before the handler can be registered in Phase 3.

### Files to Delete

None. All existing containers are reused as-is.

### Verification

```bash
cd frontend && npx tsc --noEmit  # Zero TS errors
```
- Navigate to Research → see Portfolio Risk sub-view (factor model + risk analysis)
- Switch to Stock Lookup → see existing stock lookup
- Click "Simulate hedge →" → navigate to Scenarios
- Navigate to old `factors` URL/shortcut → should redirect to Research

---

## Phase 3: Scenarios Overhaul

> **Superseded by dedicated spec.** See `CODEX_SCENARIOS_OVERHAUL_SPEC.md` for the current implementation plan. The containers referenced here (`ScenarioAnalysisContainer`, `StrategyBuilderContainer`) have been significantly refactored since this doc was written (e.g., `useScenarioState` extraction in `a595c59f`, `useOptimizationWorkflow` extraction in `5e72235f`). Line counts and line references below are stale.
>
> **Key dependency on Phase 2**: Phase 3 requires the `'navigate-to-scenario-tool'` intent type added to `NavigationIntents.ts` in Phase 2.

---

## Phase 4: Dashboard Enrichment

**Goal**: Upgrade Overview into the layout spec's morning briefing surface with integrated holdings, alerts, performance strip, and income.

### Review notes (2026-03-12)

1. **DashboardIncomeCard shows fake data.** The Phase 4 income card uses the placeholder resolver (`portfolioValue * 0.015` hardcoded yield). Displaying synthetic numbers that look real is misleading. Either add a visible "Estimated" badge/indicator, or defer this card to Phase 6 when the real backend resolver is wired.
2. **`navigationContext` vs `scenarioToolTarget`** — Phase 3's dedicated spec may add its own `scenarioToolTarget` store field for tool-level routing. Consider using `navigationContext` for both (it's more general and avoids two parallel store-based routing mechanisms). Coordinate with the scenarios spec author.
3. **`useNavigationContext` clear-on-consume pattern is correct.** The `useEffect` that reads context then immediately clears it prevents stale state. Good defensive choice.

### Design Decisions

- **Compact holdings card** (not full HoldingsViewModernContainer) — dashboard needs a concise top-N table, not Plaid connection management. Reuses `usePositions()` hook directly.
- **Alerts panel** — new component consuming existing `useSmartAlerts()` + position-level data. Positions expose `alerts` (number) and `alertDetails` (array of `{severity, message}`) via `PositionsAdapter` — NOT generic "flags". Risk score `component_scores` are numeric scores (0-100), not violation objects — derive violations by checking scores against thresholds (>75 = warning, >90 = critical). **No hedge expiry data** in `usePortfolioSummary()` — hedge alerts come from position-level `alertDetails` only (which already includes option expiry warnings from the backend).
- **Navigation context for exit ramps** — add lightweight `navigationContext` to uiStore with setter, consumer, and **clear-on-consume** behavior. The consuming component reads the context on mount then immediately clears it to prevent stale state on subsequent navigations.
- **Destination components must consume navigationContext** — `ResearchContainer` (Phase 2) must be updated in Phase 4 to read `navigationContext.ticker` on mount and, if present, switch to Stock Lookup sub-view and pass the ticker to `StockLookupContainer`. This requires `StockLookupContainer` to accept an optional `initialTicker` prop OR `ResearchContainer` to imperatively trigger the stock search. **Existing alert-to-view routing** in `alertMappings.ts` (`connectors/src/features/notifications/alertMappings.ts`) should be consulted — it maps flag types to ViewId destinations. New alert click-through should be consistent with this existing pattern.

### Files to Create

**1. `frontend/packages/ui/src/components/dashboard/cards/DashboardHoldingsCard.tsx` (~120 lines)**

Compact holdings table for the dashboard. This is a **data card** (standard `Card`, not glass) — see card hierarchy below.

Data: `usePositions()` from `@risk/connectors` (same hook HoldingsViewModernContainer uses, TanStack Query cached)

Structure:
- Use `DataTable` block with header gradient (`from-muted/50 to-background`) and staggered row fade-in (`animationDelay: ${index * 0.03}s`)
- Columns: ticker, name, value, weight%, dayChange% (use `PercentageBadge` with auto-coloring for dayChange)
- Max 10 rows, "View All →" link at bottom (`Button variant="ghost"` with `ChevronRight`)
- Click row → `setNavigationContext({ ticker }); setActiveView('research')`. Visual affordance: subtle `ChevronRight` icon on hover (opacity-0 → opacity-100 transition), `hover:bg-muted/30` row treatment, `cursor-pointer`
- Alert badges on rows: use `PercentageBadge` component with tone mapping from `alertDetails` severity (critical → red tone, warning → amber tone). Show count badge inline with ticker column, not a separate column

**2. `frontend/packages/ui/src/components/dashboard/cards/DashboardAlertsPanel.tsx` (~150 lines)**

Aggregated alerts panel. This is the highest-impact new component — the primary signal surface on the dashboard.

Data sources:
- `useSmartAlerts()` — position-level alerts (already aggregated by backend). These include option expiry warnings from backend risk analysis.
- `useRiskScore()` → `component_scores` array (numeric 0-100 scores for concentration, volatility, factor, sector). Derive violations: score > 75 = warning, score > 90 = critical. Do NOT treat scores as violation objects directly.
- **Note**: `usePortfolioSummary()` does NOT contain hedge expiry data. Hedge/option expiry alerts already come through `useSmartAlerts()` from the backend risk analysis pipeline. No separate hedge data source needed.

Structure:
- Severity-sorted list (critical → warning → info)
- Each alert row: render as a mini `StatusCell`-style row using the existing color scheme families — critical = red scheme (`from-red-50 to-red-100/50 border-red-200/60`), warning = amber scheme, info = blue scheme. Each row gets the gradient background treatment, not plain text.
- Row content: severity icon (lucide `AlertTriangle` for critical, `AlertCircle` for warning, `Info` for info) + message + optional ticker `PercentageBadge` + action `Button variant="ghost" size="icon"` with `ChevronRight` (h-8 w-8, matching sidebar button sizing)
- Click alert → navigate to relevant detail view. Consult existing `alertMappings.ts` for flag-type → ViewId routing.
- Max 8 visible (not 5 — too aggressive), with "View All" expandable toggle below
- Apply `animate-stagger-fade-in` with `animationDelay: ${index * 0.05}s` on each alert row

**3. `frontend/packages/ui/src/components/dashboard/cards/DashboardPerformanceStrip.tsx` (~90 lines)**

Horizontal metrics strip. Acts as a visual breather between the dense holdings/alerts row and the allocation/income row below. This is a **summary card** (glass-tinted treatment).

Data: `usePerformance()` from `@risk/connectors` (already called by PortfolioOverviewContainer — shared cache)

Structure:
- Wrap in `Card variant="glassTinted"` with `cursor-pointer hover-lift-subtle`
- Single row of 4 `StatPair` blocks in `flex justify-between`: YTD Return, vs Benchmark, Sharpe, Volatility
- YTD Return is the primary metric — use emerald `StatPair` color scheme to pop as the visual anchor. Other three use neutral scheme.
- Use `PercentageBadge` with auto-coloring for YTD and vs Benchmark values
- Click anywhere on strip → `setActiveView('performance')`
- Subtle `ChevronRight` icon at far right (muted, always visible) to signal navigability

**4. `frontend/packages/ui/src/components/dashboard/cards/DashboardIncomeCard.tsx` (~80 lines)**

Income summary card. Use **blue color scheme** (`--chart-2`) — income is passive/projected, distinct from emerald (portfolio action) and amber (warnings). This color choice must match Phase 6's `IncomeProjectionCard` for consistency.

Data: Uses `useDataSource('income-projection')` directly (inline, no dedicated hook). The `income-projection` data source ID already exists in `chassis/catalog/types.ts` with a placeholder resolver that returns `{ annual_income: portfolioValue * 0.015, ... }`. This is sufficient for Phase 4 — the card renders placeholder data until Phase 6 upgrades the resolver to call the real backend.

**Note**: The dedicated `useIncomeProjection()` hook is created in Phase 6. Phase 4 intentionally uses the raw `useDataSource` call to avoid a cross-phase dependency. Phase 6 can refactor this card to use the new hook.

Structure:
- Projected annual income, monthly rate (annual / 12), yield
- Uses `StatPair` block with blue color scheme
- **Estimated data indicator**: Since Phase 4 uses the synthetic resolver, render a small `text-xs text-blue-400` badge "Est." next to the card title. Phase 6 removes this badge when real backend data is wired.
- Renders correctly with placeholder data (Phase 4) and upgrades to real data when Phase 6 swaps the resolver

**5. `frontend/packages/ui/src/components/dashboard/cards/index.ts` — barrel export**

### Files to Modify

**6. `frontend/packages/connectors/src/stores/uiStore.ts`**

Add navigation context for exit ramps (FIVE changes required):

```typescript
// 1. Add typed context interface (above UIState, ~line 75):
export interface NavigationContext {
  ticker?: string;
  direction?: 'buy' | 'sell';
  source?: string;
  [key: string]: unknown;  // extensible for future exit ramps
}

// 2. Add to UIState interface (~line 80):
navigationContext: NavigationContext | null;
setNavigationContext: (ctx: NavigationContext | null) => void;

// 3. Add initial state + action in create() call (~line 196):
navigationContext: null,
setNavigationContext: (ctx) => set({ navigationContext: ctx }),

// 4. Add selector:
export const useNavigationContext = () => useUIStore((s) => s.navigationContext);
```

**Critical**: `useUIActions()` is a **manually assembled selector** at ~line 323 — it does NOT auto-include new actions. Must explicitly add `setNavigationContext` to the `useUIActions` selector:
```typescript
// In useUIActions selector (~line 323), add:
setNavigationContext: s.setNavigationContext,
```

**5. `frontend/packages/connectors/src/index.ts`** — Add root barrel exports (~line 40):
```typescript
export { useNavigationContext } from './stores/uiStore';
export type { NavigationContext } from './stores/uiStore';
```
Without these, `useNavigationContext` is not importable from `@risk/connectors`.

Using a typed `NavigationContext` interface instead of `Record<string, unknown>` ensures `ctx.ticker` is `string | undefined` (not `unknown`) under strict TypeScript.

Consumer pattern (in destination components):
```typescript
const ctx = useNavigationContext();
const { setNavigationContext } = useUIActions();
useEffect(() => {
  if (ctx) {
    // use ctx.ticker, ctx.direction, etc.
    setNavigationContext(null);  // clear after consuming
  }
}, [ctx, setNavigationContext]);
```

**7. `frontend/packages/ui/src/components/dashboard/views/modern/ResearchContainer.tsx`** (created in Phase 2)

Add navigationContext consumer:
- On mount, read `useNavigationContext()` from uiStore
- If `ctx?.ticker` is present:
  - Switch to `'stock-lookup'` sub-view
  - Pass `ctx.ticker` to StockLookupContainer (add optional `initialTicker?: string` prop to ResearchContainer → StockLookupContainer)
  - Clear context: `setNavigationContext(null)`
- StockLookupContainer needs a new `initialTicker` prop that triggers `handleSelectStock(initialTicker)` via `useEffect` on mount

**8. `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx`**

Update `case 'score':` block (currently lines 373-391) from:
```
PortfolioOverviewContainer
grid[AssetAllocationContainer, RiskAnalysisModernContainer]
```
To:
```
PortfolioOverviewContainer                              (hero — glass-premium, full-width)
grid[DashboardHoldingsCard(3/5), DashboardAlertsPanel(2/5)]  (asymmetric — holdings wider, alerts narrower)
DashboardPerformanceStrip                               (glass-tinted breather strip)
grid[AssetAllocationContainer, DashboardIncomeCard]     (equal halves)
```

**Layout details:**
- Hero row: `PortfolioOverviewContainer` stays as-is (glass-premium, full-width)
- Holdings + Alerts row: Use `grid grid-cols-1 xl:grid-cols-5 gap-6` — holdings gets `col-span-3` (wider, more data), alerts gets `col-span-2` (narrower, high-urgency signal). This asymmetry prevents two equally-weighted boxes competing for attention.
- Performance strip: Full-width `glass-tinted` card (see component spec above)
- Allocation + Income row: `grid grid-cols-1 md:grid-cols-2 gap-6` (equal halves)
- Apply `animate-stagger-fade-in` on each row with `animationDelay` stepping (0s, 0.08s, 0.16s, 0.24s) for the cascading entrance that is the app's signature motion.

**Card hierarchy** (applies to all new dashboard cards across phases):
- **Hero cards** (full-width, glass-premium): PortfolioOverviewContainer
- **Summary cards** (glass-tinted, StatPair-based): PerformanceStrip, IncomeCard
- **Data cards** (standard Card, DataTable-based): HoldingsCard, AlertsPanel

Note: `RiskAnalysisModernContainer` moves out of the default dashboard — it now lives in Research > Portfolio Risk (Phase 2). The dashboard keeps the hero risk score from `PortfolioOverviewContainer`.

New cards are directly imported (not React.lazy) since they're on the primary view and are small (~80-150 lines each).

### Verification

- Dashboard shows hero metrics + holdings table + alerts panel + performance strip + sector allocation + income
- Click holding row → navigates to Research with ticker context
- Click alert → navigates to relevant view
- Performance strip click → navigates to Performance
- All data loads in parallel (no waterfall)

---

## Phase 5: Trading Section

> **Superseded by dedicated spec.** See `TRADING_SECTION_PLAN.md` for the current implementation plan. This is the only phase requiring backend changes (new endpoints in `routes/trading.py`). The dedicated spec covers the full end-to-end path: backend endpoints, chassis types/API methods, connectors resolvers/hooks, and UI cards.
>
> **Key dependency on Phase 4**: Requires `navigationContext` (added in Phase 4) for exit ramp pre-fill (e.g., Tax Harvest → Trading with sell ticker).

---

## Phase 6: Performance Enrichment

**Goal**: Add Trading P&L summary and Income projection cards to Performance section.

### Review notes (2026-03-12)

1. **`trading_summary` rename must be documented prominently.** The resolver maps backend `response.summary` → frontend `trading_summary` to avoid collision with the existing client-side `summary: string` field. This is the kind of field mapping that causes bugs months later. Add a comment in the resolver and in the type definition.
2. **Backend endpoints verified.** Both `GET /api/trading/analysis` (`routes/trading.py`) and `GET /api/income/projection` (`routes/income.py`) exist and are functional. No backend work needed.
3. **Resolver line references verified.** `trading-analysis` resolver at lines 337-378 and `income-projection` resolver at lines 740-760 in `registry.ts` are confirmed synthetic/placeholder. Accurate.
4. **`income-projection` backward-compat alias** (`annual_income` for `total_projected_annual_income`) is a good defensive choice — Phase 4's DashboardIncomeCard will consume this field.

### Prerequisite: Data Plumbing

The current frontend resolvers for `trading-analysis` and `income-projection` return **placeholder/synthetic data**, not real backend data. This phase must upgrade them before the UI cards can show real information.

**Current state:**
- `trading-analysis` resolver (`registry.ts` lines 336-377): Returns synthetic `{ signals, summary, confidence }` derived client-side from positions + risk-score + performance. Does NOT call the backend.
- `income-projection` resolver (`registry.ts` lines 739-759): Returns hardcoded `{ annual_income: portfolioValue * 0.015, projected_cashflow: { monthly, quarterly, yearly }, assumptions: { dividendYield: 0.015, source: 'frontend-estimate' } }`.

### Step 6.1: Upgrade trading-analysis plumbing

**`frontend/packages/chassis/src/catalog/types.ts`** — Update `TradingAnalysisSourceData` (line ~191):
```typescript
// Current: { signals, summary, confidence }
// New: add backend fields from to_api_response()
// Backend response has top-level keys: summary, realized_performance, trade_scorecard,
// timing_analysis, income_analysis, behavioral_analysis, return_statistics, return_distribution
{
  // Existing client-side fields (kept for backward compat):
  signals: unknown[];
  confidence: number;
  // Backend top-level `summary` object (P&L, grades, win rate all live here):
  trading_summary?: {
    total_trading_pnl: number;
    total_trading_pnl_usd: number;
    win_rate: number;
    avg_win_score: number;
    avg_timing_score: number;
    total_regret: number;
    conviction_aligned: number;
    grades: {
      conviction: string;
      timing: string;
      position_sizing: string;
      averaging_down: string;
      overall: string;
    };
  };
  // Note: `realized_performance` is a SEPARATE top-level key with different data
  // (position-level realized P&L). Don't confuse with trading_summary.
  income_analysis?: {
    total_income: number;
    total_dividends: number;
    current_monthly_rate: number;
    projected_annual: number;
  };
}
```

**Field mapping note**: The backend's `to_api_response()` returns `summary` as the key containing P&L, win rate, and grades. The frontend type renames it to `trading_summary` to avoid collision with the existing client-side `summary: string` field. The resolver must map `response.summary` → `trading_summary` during transform.

**`frontend/packages/chassis/src/catalog/types.ts`** — Update `SDKSourceParamsMap['trading-analysis']` (line ~566):
```typescript
// Current: { portfolioId?: string }
// Keep as-is — no additional params needed. Backend GET /api/trading/analysis has no query params.
```

**`frontend/packages/chassis/src/types/api.ts`** — Add response type (or regenerate from OpenAPI):
```typescript
export interface TradingAnalysisApiResponse { status: string; [key: string]: unknown }
```

**`frontend/packages/chassis/src/services/APIService.ts`** — Add method (import type from `../types/api`):
```typescript
async getTradingAnalysis(): Promise<TradingAnalysisApiResponse>
// Calls: GET /api/trading/analysis (already exists in backend routes/trading.py)
// No params needed — backend uses authenticated user's portfolio
```

**`frontend/packages/connectors/src/resolver/registry.ts`** — Update `trading-analysis` resolver (lines 336-377) to call `api.getTradingAnalysis()` and merge with existing client-side signal synthesis. Keep synthetic signals as fallback if backend call fails.

**`frontend/packages/connectors/src/features/trading/hooks/useTradingAnalysis.ts`** (new) — Following `useBacktest.ts` pattern:
```typescript
export const useTradingAnalysis = () => {
  const resolved = useDataSource('trading-analysis');
  return useMemo(() => ({
    data: resolved.data,
    loading: resolved.loading,
    error: resolved.error?.userMessage ?? null,
    refetch: resolved.refetch,
  }), [resolved]);
};
```

### Step 6.2: Upgrade income-projection plumbing

**Backend endpoint already exists**: `GET /api/income/projection` in `routes/income.py`. Accepts `projection_months` query param (int, 1-24, default 12). Returns full result from `get_income_projection()` MCP tool with fields: `total_projected_annual_income`, `portfolio_yield_on_value`, `monthly_calendar`, `quarterly_summary`, `positions`.

**`frontend/packages/chassis/src/catalog/types.ts`** — Update `IncomeProjectionSourceData` to match real backend shape:
```typescript
// Current placeholder: { annual_income, projected_cashflow: { monthly, quarterly, yearly }, assumptions }
// New: match backend get_income_projection output
{
  total_projected_annual_income: number;
  portfolio_yield_on_value: number;  // percentage points (3.31 = 3.31%)
  portfolio_yield_on_cost?: number;
  positions?: Array<{ ticker: string; annual_income: number; yield: number }>;
  // Backend returns these as DICTS keyed by month/quarter strings, NOT arrays:
  monthly_calendar?: Record<string, { confirmed: number; estimated: number; total: number; payments: unknown[] }>;
  quarterly_summary?: Record<string, { total: number; payments: unknown[] }>;
  income_by_frequency?: Record<string, number>;
  metadata?: { projection_months: number; positions_with_dividends: number; positions_without_dividends: number };
  // Keep backward-compat fields for Phase 4 DashboardIncomeCard:
  annual_income?: number;  // alias for total_projected_annual_income (set by resolver transform)
  projected_cashflow?: Record<string, number>;
}
```

**`frontend/packages/chassis/src/catalog/types.ts`** — Update `SDKSourceParamsMap['income-projection']` (line ~599):
```typescript
// Current: { portfolioId?: string }
// New: add projectionMonths
{ portfolioId?: string; projectionMonths?: number }
```

**`frontend/packages/chassis/src/types/api.ts`** — Add response type (or regenerate from OpenAPI):
```typescript
export interface IncomeProjectionApiResponse { status: string; [key: string]: unknown }
```

**`frontend/packages/chassis/src/services/APIService.ts`** — Add method (import type from `../types/api`):
```typescript
async getIncomeProjection(params?: { projectionMonths?: number }): Promise<IncomeProjectionApiResponse>
// Calls: GET /api/income/projection?projection_months=N (ALREADY EXISTS in routes/income.py)
```

**`frontend/packages/connectors/src/resolver/registry.ts`** — Replace placeholder income-projection resolver (lines 739-759) with one that calls `api.getIncomeProjection()`. Map backend response to `IncomeProjectionSourceData` shape. **Important**: Existing consumers (Phase 4 DashboardIncomeCard, any current code using placeholder data) expect `annual_income` field — add as alias for `total_projected_annual_income` in the resolver transform.

**`frontend/packages/connectors/src/features/income/hooks/useIncomeProjection.ts`** (new):
```typescript
export const useIncomeProjection = (projectionMonths?: number) => {
  const resolved = useDataSource('income-projection', { projectionMonths });
  return useMemo(() => ({
    data: resolved.data,
    loading: resolved.loading,
    error: resolved.error?.userMessage ?? null,
    refetch: resolved.refetch,
  }), [resolved]);
};
```

**`frontend/packages/connectors/src/features/income/index.ts`** — barrel export
**`frontend/packages/connectors/src/features/index.ts`** — add `export * from './income'`

**`frontend/packages/connectors/src/index.ts`** — **CRITICAL**: Add explicit named re-exports (root barrel uses explicit exports, not wildcard):
```typescript
export { useTradingAnalysis } from './features/trading/hooks/useTradingAnalysis';
export { useIncomeProjection } from './features/income/hooks/useIncomeProjection';
```
Without these, the hooks are not importable from `@risk/connectors`.

### Step 6.3: UI Cards

**1. `frontend/packages/ui/src/components/portfolio/performance/TradingPnLCard.tsx` (~100 lines)**

Data: `useTradingAnalysis()` hook (from Step 6.1)

Use **emerald color scheme** — trading is portfolio action, matches the app's primary accent. This differentiates it from the blue IncomeProjectionCard beside it.

Structure:
- Lead with Total Trading P&L as a prominent hero number: large font (`text-2xl font-bold tabular-nums`), green/red coloring via `PercentageBadge` auto-coloring logic (positive = emerald, negative = red)
- Secondary metrics row: Win Rate (`StatPair`, neutral scheme) + Overall Grade
- **Overall Grade as circular badge**: Render the letter grade (A/B/C/D/F) in a `h-10 w-10 rounded-full` circle with color-coded background (A = emerald-100/emerald-700, B = blue-100/blue-700, C = amber-100/amber-700, D/F = red-100/red-700). `text-lg font-bold` centered. This is the visual anchor that differentiates this card from a generic StatPair grid.
- Fields from `data.trading_summary`: `total_trading_pnl_usd`, `win_rate`, `grades.overall`
- Graceful fallback: if `trading_summary` is undefined (backend hasn't returned it yet), show the synthetic `confidence` + `signals.length` as a placeholder with muted styling

**2. `frontend/packages/ui/src/components/portfolio/performance/IncomeProjectionCard.tsx` (~100 lines)**

Data: `useIncomeProjection()` hook (from Step 6.2)

Use **blue color scheme** (`--chart-2`) — income is passive/projected, consistent with Phase 4's DashboardIncomeCard color choice. The two income-related cards across the app share the same color identity.

Structure:
- Lead with Total Projected Annual Income as hero number (`text-2xl font-bold tabular-nums`, blue-700)
- Secondary: Portfolio Yield on Value (`StatPair`, blue scheme), Monthly Rate (derived: annual / 12, `StatPair`, neutral scheme)
- **Mini sparkline differentiator**: If `monthly_calendar` data is available, render a `SparklineChart` (blue color scheme, ~40px tall) showing the 12-month projected income curve below the metrics. This visually distinguishes the card from the TradingPnLCard and adds information density without extra text. If no monthly data, omit the sparkline gracefully.
- Fields from `data`: `total_projected_annual_income`, `portfolio_yield_on_value` (percentage points — display as-is with % suffix), `monthly_calendar` (for sparkline)
- Remove the "Est." badge that Phase 4's DashboardIncomeCard uses — this card has real data.

### Step 6.4: Integration

**`frontend/packages/ui/src/components/dashboard/views/modern/PerformanceViewContainer.tsx`**

Add above the `PerformanceView` render:
```tsx
<div className="mb-8 space-y-4">
  <SectionHeader
    icon={TrendingUp}
    title="Portfolio Insights"
    colorScheme="emerald"
    size="md"
  />
  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
    <div className="animate-stagger-fade-in" style={{ animationDelay: '0s' }}>
      <TradingPnLCard />
    </div>
    <div className="animate-stagger-fade-in" style={{ animationDelay: '0.08s' }}>
      <IncomeProjectionCard />
    </div>
  </div>
</div>
```

The `SectionHeader` creates visual hierarchy — "Portfolio Insights" header → summary cards → detailed performance tabs. Without it, the cards float above the tabs with no context. Cards are self-contained (own hooks), so no data threading from container.

### Verification

- Navigate to Performance → see Trading P&L + Income cards above existing tabs
- Trading P&L shows real `trading_summary.total_trading_pnl_usd`, `trading_summary.win_rate`, `trading_summary.grades.overall` (not just synthetic signals)
- Income card shows real `total_projected_annual_income`, `portfolio_yield_on_value` (not hardcoded 1.5% yield)
- Cards load independently (no blocking the main performance data)
- All existing tabs still work
- Fallback: if backend returns no `realized_performance`, card shows synthetic `summary` string gracefully

---

## Dependency Graph & Execution Order

```
Phase 2 (Research merge)     — standalone, no deps                          ← THIS DOC
Phase 3 (Scenarios overhaul) — depends on Phase 2                           ← see CODEX_SCENARIOS_OVERHAUL_SPEC.md
Phase 4 (Dashboard)          — depends on Phase 2 (Research for exit ramps) ← THIS DOC
Phase 5 (Trading)            — depends on Phase 4 (navigationContext)       ← see TRADING_SECTION_PLAN.md
Phase 6 (Performance)        — depends on Phase 4 (income plumbing)         ← THIS DOC
```

**Recommended order**: 2 → 3 → 4 → 5 → 6

Phases 2, 4, 6 are fully specified here. Phases 3 and 5 are pointer-only — use their dedicated specs.

---

## Key Reusable Patterns & Files

| Pattern | Reference File | Used In |
|---------|---------------|---------|
| Container + presentational | Any `*Container.tsx` in `views/modern/` | Phases 2, 4, 6 |
| DashboardErrorBoundary wrapper | `dashboard/shared/DashboardErrorBoundary` | All new containers |
| useDataSource hook | `connectors/src/resolver/useDataSource.ts` | New data hooks |
| IntentRegistry cross-nav | `connectors/src/utils/NavigationIntents.ts` | Exit ramps |
| ViewId redirect via useEffect | ModernDashboardApp.tsx lines 214-217 (connections → score) | Phase 2 |
| Block components (StatPair, DataTable, GradientProgress) | `ui/src/components/blocks/` | Phase 4, 6 cards |

## Cross-Phase Design Conventions

These apply to every new component across Phases 2, 4, and 6:

**Card hierarchy** (three tiers, defined in Phase 4, used everywhere):
- **Hero**: full-width, `glass-premium` — reserved for `PortfolioOverviewContainer`
- **Summary**: `Card variant="glassTinted"`, `StatPair`-based — PerformanceStrip, IncomeCard, PnLCard
- **Data**: standard `Card`, `DataTable`-based — HoldingsCard, AlertsPanel

**Color identity by domain** (prevents visual confusion when cards are side-by-side):
- Emerald (`--chart-1`): portfolio action — trading P&L, primary metrics, active nav state
- Blue (`--chart-2`): passive/projected — income, dividends
- Amber (`--chart-4`): warnings — risk alerts, threshold violations
- Red (`--chart-5`): critical — drawdowns, negative P&L, critical alerts
- Neutral: secondary metrics, supporting data

**Stagger animation on every card grid**: Wrap each card in `animate-stagger-fade-in` with `animationDelay: ${index * 0.08}s`. This is the app's signature entrance motion — cascading cards from top.

**Exit ramp pattern** (consistent across all phases): `Card variant="glassTinted"` strip containing `Button variant="outline"` with emerald `ChevronRight` icon and `hover-lift-subtle`. Used in Phase 2 (Research → Scenarios), Phase 4 (Dashboard → detail views), Phase 5 (Scenarios → Trading).

**Navigable elements**: Any clickable row or card that navigates to another view gets: `cursor-pointer`, `hover:bg-muted/30` (or `hover-lift-subtle` for cards), and a subtle `ChevronRight` affordance (opacity transition on hover for rows, always-visible muted icon for cards).

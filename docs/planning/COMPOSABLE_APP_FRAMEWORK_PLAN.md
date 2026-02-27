# Composable App Framework (SDK)

**Date**: 2026-02-25
**Status**: Draft
**Goal**: Turn chassis/connectors/UI into an SDK that AI agents can code against to build any UI — dashboards, workflows, novel visualizations — with zero boilerplate.
**Implementation plan**: `FRONTEND_SDK_PLAN.md` (phases, sequencing, source list)

### Prerequisites (Phase 2 — must complete before this)
| Doc | Purpose |
|-----|---------|
| `FRONTEND_PHASE2_WORKING_DOC.md` | Phase 2 master doc — wire all components to real data + evaluate what to keep/kill |
| `FRONTEND_WAVE1_IMPLEMENTATION_PLAN.md` | Wave 1 of Phase 2 — pure frontend wiring (Codex-reviewed, in progress) |
| `FRONTEND_COMPONENT_VISUAL_MAP.md` | Visual guide mapping on-screen UI elements to code components |
| `FRONTEND_DATA_WIRING_AUDIT.md` | Container/adapter-level audit (ported into Phase 2 working doc) |

## Core Idea

The AI writes real React/TSX code, not constrained JSON manifests. The SDK handles all plumbing (auth, data fetching, caching, loading/error states, cross-component communication). The AI focuses purely on **what to show** and **how it behaves**.

Assumption: the AI/agent can write good code. The SDK's job is to make that code **short, correct, and composable** by eliminating infrastructure concerns.

```
AI Agent
  ↓ discovers
Data Catalog ("what data exists and what shape is it?")
  ↓ codes against
SDK Primitives (useDataSource, components, shared state, layout)
  ↓ produces
React Components (real TSX — no artificial ceiling)
  ↓ rendered by
Framework Runtime (chassis provides auth, caching, error handling)
```

## What Exists Today

| Layer | What's There | Gap |
|-------|-------------|-----|
| **Chassis** | ServiceContainer, auth, caching, API, stores | No data catalog, no universal data hook |
| **Connectors** | 9 adapters, 18 hooks, 4 managers | Manual wiring, each hook is 50+ lines of bespoke code |
| **UI** | 50+ Radix primitives, 12 portfolio components, 8 charts | Domain-specific, not reusable building blocks |
| **Backend** | 25 MCP tools, consistent `snapshot + flags` agent format | Frontend doesn't consume agent format directly |

## SDK Surface Area

The SDK exposes **four categories** of primitives. Together they let an AI build anything from a simple metric card to a multi-step trade execution workflow.

### 1. Data Layer

#### Data Catalog — discovery
```typescript
import { dataCatalog } from "@risk/chassis";

// AI discovers available data sources
dataCatalog.list()
// → [{ id: "positions", label: "Portfolio Positions", category: "portfolio", ... }, ...]

dataCatalog.describe("risk-analysis")
// → { params: [...], schema: { fields: [...] }, flagTypes: [...] }

dataCatalog.search("performance returns")
// → [{ id: "performance", ... }, { id: "trading-analysis", ... }]
```

#### useDataSource — universal data hook
```typescript
import { useDataSource } from "@risk/connectors";

// One hook to access any data source. Handles caching, loading, errors, refresh.
function MyComponent() {
  const { data, loading, error, flags, refetch } = useDataSource("risk-analysis", {
    include: ["risk_metrics", "factor_analysis"],
  });

  if (loading) return <Skeleton />;
  if (error) return <ErrorDisplay message={error} />;

  return <div>{data.snapshot.volatility_annual}</div>;
}
```

Under the hood: catalog lookup → adapter resolution → API call → cache → normalized response.

Existing hooks become thin wrappers (backward compatible):
```typescript
export const useRiskAnalysis = (params) => useDataSource("risk-analysis", params);
export const usePerformance = (params) => useDataSource("performance", params);
```

### 2. Component Primitives

Generic building blocks that work with any data source. The AI can use these as-is OR build entirely custom components — these just save time for common patterns.

```typescript
import { MetricGrid, DataTable, ChartPanel, FlagBanner, DataBoundary } from "@risk/ui/primitives";

// Metric cards from any source
<MetricGrid source="risk-score" fields={["risk_score", "overall_status", "compliance_status"]} columns={3} />

// Table from any array field
<DataTable source="positions" field="top_holdings" columns={["ticker", "value", "weight"]} sortable />

// Chart from any series
<ChartPanel source="risk-analysis" field="risk_attribution" chartType="bar" xKey="ticker" yKey="contribution_pct" />

// Flags/alerts
<FlagBanner source="risk-score" severityFilter={["warning", "error"]} />

// Loading/error boundary (auto-resolves data)
<DataBoundary source="risk-analysis" fallback={<Skeleton />}>
  {(data) => <CustomVisualization data={data} />}
</DataBoundary>
```

These are **convenience, not constraints**. AI can always drop down to `useDataSource` + raw JSX for anything novel.

### 3. Interaction Primitives

For cross-component communication, multi-step flows, and shared state.

#### Shared State
```typescript
import { useSharedState } from "@risk/connectors";

// Component A: sets selected ticker
function PositionsTable() {
  const [, setTicker] = useSharedState<string>("selectedTicker");
  const { data } = useDataSource("positions");

  return (
    <DataTable
      data={data.snapshot.top_holdings}
      onRowClick={(row) => setTicker(row.ticker)}
    />
  );
}

// Component B: reacts to selection, fetches new data
function StockDetail() {
  const [ticker] = useSharedState<string>("selectedTicker");
  const { data, loading } = useDataSource("stock-analysis", { ticker });

  if (!ticker) return <EmptyState message="Select a position" />;
  return <StockCard data={data} loading={loading} />;
}
```

`useSharedState` is a thin Zustand-backed primitive. Scoped per app/page, garbage-collected when unmounted.

#### Event Bus (existing, exposed as SDK primitive)
```typescript
import { useEvent, useEmit } from "@risk/connectors";

// Listen for events
useEvent("trade-executed", (event) => {
  // Refetch positions, update portfolio summary, show notification
  refetchPositions();
  showToast(`Trade executed: ${event.ticker}`);
});

// Emit events
const emit = useEmit();
emit("trade-executed", { ticker: "AAPL", side: "SELL", quantity: 100 });
```

#### Multi-Step Flow
```typescript
import { useFlow } from "@risk/connectors";

function TradeFlow() {
  const flow = useFlow({
    steps: ["select", "preview", "confirm", "result"],
    initial: "select",
  });

  return (
    <>
      {flow.step === "select" && (
        <StockSelector onSelect={(ticker) => flow.next({ ticker })} />
      )}
      {flow.step === "preview" && (
        <TradePreview
          ticker={flow.context.ticker}
          onConfirm={(previewId) => flow.next({ previewId })}
          onBack={flow.back}
        />
      )}
      {flow.step === "confirm" && (
        <TradeConfirmation
          previewId={flow.context.previewId}
          onExecute={async () => {
            const result = await executeTrade(flow.context.previewId);
            flow.next({ result });
          }}
        />
      )}
      {flow.step === "result" && (
        <TradeResult result={flow.context.result} onDone={flow.reset} />
      )}
    </>
  );
}
```

### 4. Layout Utilities

Simple layout components so the AI doesn't waste time on CSS grid boilerplate.

```typescript
import { Grid, Stack, Split, Tabs, Page } from "@risk/ui/layout";

<Page title="Risk Dashboard" subtitle="Real-time portfolio risk monitoring">
  <Grid columns={3} gap="md">
    <MetricGrid source="risk-score" fields={["risk_score", "overall_status"]} />
    <MetricGrid source="performance" fields={["total_return_pct", "sharpe_ratio"]} />
    <MetricGrid source="positions" fields={["total_value", "position_count"]} />
  </Grid>

  <Split ratio={[2, 1]}>
    <ChartPanel source="risk-analysis" field="risk_attribution" chartType="bar" />
    <FlagBanner source="risk-score" />
  </Split>

  <Tabs>
    <Tabs.Tab label="Holdings">
      <DataTable source="positions" field="top_holdings" />
    </Tabs.Tab>
    <Tabs.Tab label="Factor Exposure">
      <ChartPanel source="factor-analysis" field="factor_exposures" chartType="radar" />
    </Tabs.Tab>
  </Tabs>
</Page>
```

## What the AI Sees

When an AI agent is asked to build a UI, it gets:

1. **Data catalog dump** — list of all sources with schemas, params, field types
2. **SDK reference** — `useDataSource`, primitives, shared state, layout, flow
3. **Existing component examples** — patterns it can reference or extend

That's enough context to build anything from a simple card to a complex workflow. No manifest translation layer needed — the AI writes TSX directly.

## Example: AI Builds a Complete Dashboard

User: "Build me a dashboard that shows my risk score, top holdings with click-to-detail, and a performance chart vs benchmark"

AI generates:
```tsx
import { useDataSource, useSharedState } from "@risk/connectors";
import { Page, Grid, Split } from "@risk/ui/layout";
import { MetricGrid, DataTable, ChartPanel, DataBoundary } from "@risk/ui/primitives";

export function RiskDashboard() {
  const [selectedTicker, setSelectedTicker] = useSharedState<string | null>("selectedTicker", null);

  return (
    <Page title="Risk Overview">
      {/* Top metrics row */}
      <Grid columns={3} gap="md">
        <MetricGrid source="risk-score" fields={["risk_score", "overall_status", "compliance_status"]} />
        <MetricGrid source="performance" fields={["total_return_pct", "sharpe_ratio", "max_drawdown_pct"]} />
        <MetricGrid source="positions" fields={["total_value", "position_count"]} />
      </Grid>

      {/* Main content */}
      <Split ratio={[3, 2]}>
        {/* Holdings table with click-to-detail */}
        <DataTable
          source="positions"
          field="top_holdings"
          columns={["ticker", "value", "weight"]}
          sortable
          onRowClick={(row) => setSelectedTicker(row.ticker)}
          highlightRow={(row) => row.ticker === selectedTicker}
        />

        {/* Detail panel — reacts to selection */}
        {selectedTicker ? (
          <DataBoundary source="stock-analysis" params={{ ticker: selectedTicker }}>
            {(data) => (
              <div>
                <h3>{selectedTicker}</h3>
                <MetricGrid
                  data={data}
                  fields={["volatility_pct", "beta", "alpha_pct", "sector"]}
                  columns={2}
                />
              </div>
            )}
          </DataBoundary>
        ) : (
          <div className="text-muted-foreground p-8 text-center">
            Click a holding to see details
          </div>
        )}
      </Split>

      {/* Performance chart */}
      <ChartPanel
        source="performance"
        field="cumulative_returns"
        chartType="line"
        title="Performance vs Benchmark"
      />
    </Page>
  );
}
```

That's a complete, working dashboard — real data, cross-component interaction, loading/error handling — in ~40 lines. The AI didn't need to know about API calls, caching, auth, or error states.

## Implementation Phases

### Phase 0: Data Catalog + Descriptors
- Define `DataSourceDescriptor`, `ParamDescriptor`, `FieldDescriptor`, `FlagDescriptor` types
- Create `DataCatalog` class (register, list, describe, search)
- Write descriptors for all 14 agent-format backend tools + 4 non-agent tools
- Export from `@risk/chassis`

**Where:** `packages/chassis/src/catalog/`
**Size:** ~400 lines (types + catalog class + 18 descriptors)

### Phase 1: Data Resolver (useDataSource)
- Implement `useDataSource` hook: catalog lookup → adapter → cache → normalized response
- Implement resolver registry: maps source IDs to existing adapter functions
- Migrate existing hooks to thin wrappers (backward compatible)
- Wire to existing `UnifiedAdapterCache` + `CacheCoordinator` + TanStack Query

**Where:** `packages/connectors/src/resolver/`
**Size:** ~300 lines (resolver + hook + registry), plus updating 18 existing hooks

### Phase 2: Interaction Primitives
- `useSharedState` — Zustand-backed scoped shared state
- `useEvent` / `useEmit` — typed wrapper around existing EventBus
- `useFlow` — multi-step flow state machine

**Where:** `packages/connectors/src/primitives/`
**Size:** ~200 lines

### Phase 3: Component Primitives + Layout
- `MetricGrid` — renders key-value metric cards from any data source
- `DataTable` — renders sortable/filterable table from any array field
- `ChartPanel` — renders chart (line, bar, radar, pie) from any series field
- `FlagBanner` — renders flags/alerts from any source
- `DataBoundary` — loading/error wrapper with automatic data resolution
- Layout: `Page`, `Grid`, `Split`, `Stack`, `Tabs`

**Where:** `packages/ui/src/primitives/`, `packages/ui/src/layout/`
**Size:** ~600 lines (building on existing Radix + Recharts components)

### Phase 4 (future): Manifest Layer
Optional: define `AppManifest` schema + `ManifestRenderer` for saving/sharing/versioning layouts as JSON. Not required for AI building — it's a serialization format on top of the SDK.

### Phase 5 (future): Persistence + Template Library
Save AI-generated components/pages. Version history. Template marketplace.

## Backward Compatibility

- Existing containers (PortfolioOverviewContainer, etc.) keep working unchanged
- Existing hooks become thin wrappers — no breaking changes
- ModernDashboardApp stays as-is; new views can use SDK primitives alongside old views
- Migration is per-component, not big-bang

## Relation to Existing Backlog

This plan subsumes:
- **Frontend: Package Formalization** — Phase 0-1 formalizes package contracts
- **Frontend: Component Data Wiring** — Phase 1+3 wires everything via resolver + primitives
- **Frontend: Agent-Driven Dynamic UI** — Phase 0-3 is the enabling infrastructure
- **Frontend: AI-Assisted UI Development** — this IS the enabling infrastructure

# Frontend SDK — Design & Planning

**Date**: 2026-02-26
**Status**: Draft
**Related**: `COMPOSABLE_APP_FRAMEWORK_PLAN.md` (full vision), `FRONTEND_PHASE2_WORKING_DOC.md` (current wiring audit)

## What Is This

A lightweight developer interface on top of our existing APIs and data layer. The SDK makes our backend data **discoverable**, **uniform to consume**, and **trivial to wire** — so an AI agent (or developer) can build any UI without reading implementation code.

It's not a new framework. It's a thin typed layer over the infrastructure we already have (chassis services, connectors adapters, MCP tools). The chassis is the engine; the SDK is the steering wheel.

The SDK is **data-layer only**. No component primitives, no layout system. The AI already knows React, Radix, Recharts, and Tailwind — it doesn't need us to wrap those. The SDK gives it data access; the AI builds whatever UI it wants.

## Why

Today, building a new frontend view requires:
1. Reading adapter source code to understand what data is available
2. Finding the right hook (18 bespoke hooks, each 50+ lines)
3. Understanding caching, loading states, error handling per hook
4. Manually wiring data → component props

With the SDK:
1. Query the data catalog ("what data exists?")
2. Call `useDataSource("risk-analysis")` — one hook, handles everything
3. Write any UI using React + Radix + Recharts + Tailwind

## SDK Layers

### Layer 1: Data Catalog (chassis)

Machine-readable registry of all available data sources. Each source describes its params, return schema, field types, cache behavior, loading strategy, and error config. Descriptor types are **derived from adapter output types** — the adapter is the single source of truth, so the catalog can't drift.

```
dataCatalog.list()        → all available sources
dataCatalog.describe(id)  → params, fields, flags, refresh, loading, errors
dataCatalog.search(query) → keyword search for AI discovery
```

Lives in `@risk/chassis` because it's infrastructure — no React dependency.

**Type derivation:**
```typescript
// Adapter defines the source of truth
type RiskAnalysisOutput = {
  volatility_annual: number;
  leverage: number;
  factor_exposures: Record<string, number>;
  // ...
};

// Descriptor fields are typed against the output — can't drift
const riskAnalysisSource: DataSourceDescriptor<RiskAnalysisOutput> = {
  id: "risk-analysis",
  label: "Portfolio Risk Analysis",
  category: "risk",
  fields: [
    { name: "volatility_annual", ... },  // ← TS enforces this key exists on RiskAnalysisOutput
    { name: "fake_field", ... },          // ← TS error at compile time
  ],
  // ...refresh, loading, errors config (see below)
};
```

If an adapter changes its output shape, TypeScript flags every descriptor and component that references the old fields.

**Drift detection:** Beyond compiler enforcement, a build-time conformance test iterates all registered descriptors and asserts every `field.name` exists as a key on the corresponding adapter output type. This catches cases where a descriptor is registered with a loose `Record<string, unknown>` instead of the real adapter type. See Phase 0 deliverables.

**Full descriptor shape:**
```typescript
interface DataSourceDescriptor<T> {
  id: string;
  label: string;
  category: DataCategory;
  params: ParamDescriptor[];
  fields: FieldDescriptor<T>[];
  flagTypes: FlagDescriptor[];

  refresh: {
    defaultTTL: number;                // seconds
    staleWhileRevalidate: boolean;
    invalidatedBy?: string[];          // event names that trigger refetch
  };

  loading: {
    strategy: "eager" | "lazy";        // eager = fetch on app init, lazy = fetch on demand
    dependsOn?: string[];              // source IDs that must load first
    priority?: number;                 // lower = higher priority (for eager sources)
  };

  errors: {
    retryable: boolean;                // whether to auto-retry on failure
    maxRetries: number;                // retry count (default 2)
    timeout: number;                   // ms before timeout (default 30000)
    fallbackToStale: boolean;          // show stale cached data on error
  };
}

type DataCategory = "portfolio" | "risk" | "trading" | "research";
```

**Sources to register (18 total):**

| Source ID | Backend | Agent Format | Category |
|-----------|---------|:---:|----------|
| `positions` | `/api/portfolio/summary` + MCP `get_positions` | Yes | portfolio |
| `risk-score` | `/api/risk-score` + MCP `get_risk_score` | Yes | risk |
| `risk-analysis` | `/api/analyze` + MCP `get_risk_analysis` | Yes | risk |
| `leverage-capacity` | MCP `get_leverage_capacity` | Yes | risk |
| `risk-profile` | MCP `get_risk_profile` / `set_risk_profile` | — | risk |
| `performance` | `/api/performance` + MCP `get_performance` | Yes | portfolio |
| `trading-analysis` | MCP `get_trading_analysis` | Yes | trading |
| `exit-signals` | MCP `check_exit_signals` | Yes | trading |
| `optimization` | `/api/min-variance`, `/api/max-return` + MCP `run_optimization` | Yes | portfolio |
| `what-if` | `/api/what-if` + MCP `run_whatif` | Yes | portfolio |
| `stock-analysis` | `/api/direct/stock` + MCP `analyze_stock` | Yes | research |
| `option-strategy` | MCP `analyze_option_strategy` | Yes | trading |
| `factor-analysis` | MCP `get_factor_analysis` | Yes | research |
| `factor-recommendations` | MCP `get_factor_recommendations` | Yes | research |
| `income-projection` | MCP `get_income_projection` | Yes | portfolio |
| `tax-harvest` | MCP `suggest_tax_loss_harvest` | Yes | trading |
| `portfolio-news` | MCP `get_portfolio_news` | — | research |
| `events-calendar` | MCP `get_portfolio_events_calendar` | — | research |

### Layer 2: Data Resolver (connectors)

Universal data hook that resolves any catalog source to data + loading + error + flags.

```typescript
const { data, loading, error, flags, stale, refetch } = useDataSource("risk-analysis", params);
```

Under the hood: catalog lookup → adapter/API call → cache (existing UnifiedAdapterCache) → normalized response.

**Resolver return shape:**
```typescript
interface ResolvedData<T> {
  /** The resolved data, null if loading or errored (unless fallbackToStale) */
  data: T | null;

  /** True during initial fetch */
  loading: boolean;

  /** Structured error if the request failed, null on success */
  error: DataSourceError | null;

  /** Interpretive flags from the backend (warnings, alerts, etc.) */
  flags: Flag[];

  /** True if showing cached data while refetching or after error with fallbackToStale */
  stale: boolean;

  /** Manual refetch trigger */
  refetch: () => void;

  /** When the data was last successfully fetched */
  lastUpdated: Date | null;

  /** Data quality indicator */
  quality: "complete" | "partial" | "stale" | "error";
}
```

**Bootstrap & execution model:**

The resolver integrates with the existing app lifecycle:

```
1. App mounts → SessionServicesProvider creates per-user services
2. PortfolioInitializer fires → resolver scheduler activates
3. Scheduler reads all descriptors with strategy: "eager"
4. Sorts by priority (lower = first), validates dependsOn (no cycles)
5. Fetches in dependency order using TanStack Query
6. Lazy sources fetch on first useDataSource() call

Runtime:
- useDataSource("risk-analysis") → checks catalog → TanStack useQuery
  - queryKey: ["sdk", sourceId, serializedParams]
  - queryFn: resolverRegistry.resolve(sourceId, params)
  - enabled: all dependsOn sources have data (prefix match via queryClient.getQueriesData)
  - staleTime: descriptor.refresh.defaultTTL * 1000
  - retry: descriptor.errors.retryable ? descriptor.errors.maxRetries : 0
  - signal: AbortController for timeout (descriptor.errors.timeout)
- EventBus listens for descriptor.refresh.invalidatedBy events
  → queryClient.invalidateQueries(["sdk", sourceId])
```

**Dependency resolution:**
- `dependsOn` maps to TanStack Query `enabled` flag. Dependencies are checked by query key prefix match: `enabled: dependsOn.every(dep => queryClient.getQueriesData({ queryKey: ["sdk", dep] }).some(([, data]) => data != null))`. This handles parameterized dependencies — any successful query for the dependency source ID satisfies the gate, regardless of which params were used.
- Cycles detected at registration time: `DataCatalog.register()` throws if adding a descriptor would create a circular dependency (topological sort on the `dependsOn` graph).
- Cancellation: TanStack Query's built-in `AbortSignal` propagation. If a component unmounts, the query is cancelled.

**Hook migration — resolver-friendly vs workflow hooks:**

Not all existing hooks can become thin wrappers. Hooks are classified into two tiers:

| Hook | Tier | Reason |
|------|------|--------|
| useRiskScore | Resolver | Maps to `risk-score`. Simple fetch → adapt → cache |
| useRiskAnalysis | Resolver | Maps to `risk-analysis`. Simple fetch → adapt → cache |
| usePerformance | Resolver | Maps to `performance`. Simple fetch → adapt → cache |
| useAnalysisReport | Composite | Aggregates data from `risk-analysis` + `positions`. Becomes multi-source composition using two `useDataSource` calls, not a single thin wrapper |
| useRiskMetrics | Composite | Aggregates `usePerformance` + `useRiskAnalysis`. Same pattern — two `useDataSource` calls internally |
| useChat | Workflow | Alias for usePortfolioChat which is SSE streaming + tool approval |
| useRiskSettings | Workflow | Bidirectional mutations, cache invalidation across layers |
| usePortfolioOptimization | Workflow | Local strategy state, multiple optimize callbacks |
| useWhatIfAnalysis | Workflow | Local scenario state, input management, manual trigger |
| useStockAnalysis | Workflow | Local ticker state, analyzeStock callback |
| usePortfolioSummary | Workflow | Parallel multi-source useQueries (3 queries + 3 adapters) |
| useInstantAnalysis | Workflow | File extraction, store management, side effects |
| usePendingUpdates | Workflow | 5-min polling, per-provider state |
| usePlaid | Workflow | Multiple mutations, popup management, polling |
| useSnapTrade | Workflow | Multiple mutations, feature flags |
| usePortfolioChat | Workflow | SSE streaming, tool approval flow |
| useAuthFlow | Workflow | OAuth flow, token management |
| useConnectAccount | Workflow | Account linking orchestration |

**Migration approach:**
- **3 resolver hooks** (useRiskScore, useRiskAnalysis, usePerformance) → become thin wrappers: `(params) => useDataSource(sourceId, params)`. Each maps 1:1 to a catalog source ID.
- **2 composite hooks** (useAnalysisReport, useRiskMetrics) → rewritten to compose multiple `useDataSource` calls internally. Not thin wrappers, but still benefit from the resolver for each underlying source.
- **13 workflow hooks** → stay as custom hooks, coexist alongside `useDataSource`. They may internally adopt `useDataSource` for their fetch logic over time but retain their bespoke state/mutation/orchestration code.
- All tiers benefit from the data catalog (discovery) and error model (structured errors).

### Layer 3: Error Model

Typed, categorized errors so the AI can handle different failure modes appropriately.

**Error classes:**
```typescript
/** Base error — all SDK errors extend this */
class DataSourceError extends Error {
  /** Machine-readable category for programmatic handling */
  category: ErrorCategory;

  /** HTTP status code if applicable */
  statusCode?: number;

  /** Whether a retry button should be shown */
  retryable: boolean;

  /** Human-readable message safe to show to users */
  userMessage: string;

  /** Which data source failed */
  sourceId: string;

  /** Original error for debugging */
  cause?: Error;
}

type ErrorCategory =
  | "network"       // connection failed, timeout, DNS
  | "auth"          // 401/403, token expired, not logged in
  | "not_found"     // 404, source or resource doesn't exist
  | "validation"    // adapter transform failed, unexpected data shape
  | "rate_limit"    // 429, too many requests
  | "server"        // 500+, backend error
  | "timeout"       // request exceeded configured timeout
  | "partial"       // some fields loaded, others failed
  | "unknown";      // unclassified
```

**How the AI uses error categories:**
```tsx
function MyComponent() {
  const { data, error, loading, quality, stale, refetch } = useDataSource("risk-analysis");

  if (loading) return <Skeleton />;

  if (error) {
    switch (error.category) {
      case "auth":
        return <div>Please log in to view risk analysis.</div>;
      case "network":
      case "timeout":
        return (
          <div>
            <p>Connection issue: {error.userMessage}</p>
            <button onClick={refetch}>Retry</button>
          </div>
        );
      case "rate_limit":
        return <div>Too many requests. Please wait a moment.</div>;
      case "validation":
        return <div>Data format error. Contact support.</div>;
      case "partial":
        // Some data available — render what we have WITH a visible warning
        return <PartialView data={data} warning={error.userMessage} />;
      default:
        return <div>Something went wrong: {error.userMessage}</div>;
    }
  }

  // Stale data must always be visually indicated
  return (
    <div>
      {stale && <Banner variant="warning">Showing cached data. Refreshing...</Banner>}
      <RiskDashboard data={data} />
    </div>
  );
}
```

**Stale and partial data UX rules (mandatory):**
- `quality === "stale"`: The AI **must** render a visible indicator (banner, badge, or dimmed styling). Silent stale display is a bug.
- `quality === "partial"`: The AI **must** render a warning identifying which data is missing. Available fields render normally; missing fields show placeholders.
- `fallbackToStale` on descriptors defaults to `false`. Only enabled for sources where showing old data is better than showing nothing (e.g., positions, portfolio summary). Never enabled for real-time sources (e.g., exit-signals, trade preview).

**Error construction — inside the resolver, invisible to AI:**
```typescript
function classifyError(e: unknown, sourceId: string): DataSourceError {
  if (e instanceof Response || (e as any)?.status) {
    const status = (e as any).status;
    if (status === 401 || status === 403)
      return new DataSourceError({ category: "auth", retryable: false, userMessage: "Authentication required", sourceId });
    if (status === 404)
      return new DataSourceError({ category: "not_found", retryable: false, userMessage: "Resource not found", sourceId });
    if (status === 429)
      return new DataSourceError({ category: "rate_limit", retryable: true, userMessage: "Rate limit exceeded — try again shortly", sourceId });
    if (status >= 500)
      return new DataSourceError({ category: "server", retryable: true, userMessage: "Server error — retrying", sourceId });
  }
  if (e instanceof TypeError && String(e.message).includes("fetch"))
    return new DataSourceError({ category: "network", retryable: true, userMessage: "Network connection failed", sourceId });
  if (e instanceof DOMException && e.name === "AbortError")
    return new DataSourceError({ category: "timeout", retryable: true, userMessage: "Request timed out", sourceId });
  if (e instanceof ValidationError)
    return new DataSourceError({ category: "validation", retryable: false, userMessage: "Unexpected data format", sourceId });
  return new DataSourceError({ category: "unknown", retryable: false, userMessage: String(e), sourceId });
}
```

### Layer 4: Interaction Primitives (connectors)

Cross-component communication and multi-step flows.

- `useSharedState(key)` — scoped shared state (Zustand-backed)
- `useEvent(name, handler)` / `useEmit()` — typed wrapper on existing EventBus
- `useFlow({ steps, initial })` — state machine for multi-step workflows

### Layer 5: Context Hooks (connectors)

Thin accessors for chassis state that the AI may need:

- `useCurrentPortfolio()` — which portfolio is active
- `useCurrentUser()` — who's logged in
- `useNavigate()` — move between views

## Implementation Phases

### Phase 0: Data Catalog + Descriptors
- Define types: `DataSourceDescriptor<T>`, `ParamDescriptor`, `FieldDescriptor<T>`, `FlagDescriptor`
- Define loading config types (`strategy`, `dependsOn`, `priority`)
- Define error config types (`retryable`, `maxRetries`, `timeout`, `fallbackToStale`)
- Type-derive descriptor fields from adapter output types
- Build `DataCatalog` class:
  - `register()` — validates no dependency cycles, enforces unique IDs
  - `list()`, `listByCategory()`, `describe()`, `search()`
- Write descriptors for all 18 sources (referencing adapter output types)
- Build-time conformance test: iterates all descriptors, asserts every `field.name` is a key of `T`
- Export from `@risk/chassis`

**Where:** `packages/chassis/src/catalog/`
**Size:** ~500 lines (types + catalog class + 18 descriptors + conformance test)
**Depends on:** Nothing — pure type definitions + registration

### Phase 1: Data Resolver + Error Model
- Define `DataSourceError` class with `ErrorCategory` in `@risk/chassis`
- Implement `classifyError()` — maps APIService/adapter errors to categories
- Build resolver registry: maps source IDs → existing adapter/API calls
- Implement `useDataSource<T>` hook:
  - Wraps TanStack `useQuery` with SDK-specific config from descriptors
  - `enabled` derived from `dependsOn` (check queryClient for dependency data)
  - `staleTime` from `refresh.defaultTTL`
  - `retry` from `errors.retryable` + `errors.maxRetries`
  - Timeout via `AbortController` + `errors.timeout`
  - EventBus integration for `refresh.invalidatedBy` → `queryClient.invalidateQueries`
  - Returns `ResolvedData<T>` with `quality` indicator
- Implement resolver scheduler for eager sources:
  - Reads descriptors with `strategy: "eager"`, sorts by `priority`
  - Prefetches via `queryClient.prefetchQuery` in dependency order
  - Runs in `PortfolioInitializer` after session services are ready
- Migrate 3 resolver hooks to thin wrappers (useRiskScore, useRiskAnalysis, usePerformance)
- Rewrite 2 composite hooks to use multiple `useDataSource` calls (useAnalysisReport, useRiskMetrics)
- 13 workflow hooks stay as-is (may adopt `useDataSource` internally over time)

**Where:** `packages/chassis/src/errors/`, `packages/connectors/src/resolver/`
**Size:** ~500 lines + updating 6 hooks
**Depends on:** Phase 0

### Phase 2: Interaction Primitives + Context Hooks
- `useSharedState` — Zustand-backed, scoped per page/app, garbage-collected on unmount
- `useEvent`/`useEmit` — typed wrapper on existing EventBus
- `useFlow` — step state machine with context accumulation
- `useCurrentPortfolio`, `useCurrentUser`, `useNavigate`

**Where:** `packages/connectors/src/primitives/`
**Size:** ~250 lines
**Depends on:** Phase 0

## Sequencing with Frontend Phase 2

```
Wave 1 (cleanup + wire existing)     ← do first, no SDK needed
SDK Phase 0-1 (catalog + resolver)   ← in parallel or right after Wave 1
Wave 2-3 (new wiring + features)     ← use useDataSource
SDK Phase 2 (interactions)           ← enables Wave 3 cross-component features
```

Wave 1 is pure frontend cleanup that doesn't depend on SDK. Once Phase 0-1 is in place, Wave 2-3 items become much simpler to wire.

## What This Enables

An AI agent building a view needs only:
1. `dataCatalog.list()` — discover available data
2. `useDataSource(id, params)` — fetch any data source (typed, cached, with structured errors)
3. `error.category` — handle failures appropriately (auth, network, timeout, partial, etc.)
4. `quality` / `stale` — always visually indicate degraded data states
5. React + Radix + Recharts + Tailwind — build whatever UI it wants

No adapter code to read, no hook internals to understand, no caching to configure. The SDK handles all plumbing. The AI handles all presentation.

See `COMPOSABLE_APP_FRAMEWORK_PLAN.md` for the extended vision (manifest renderer, persistence, template library) if we ever want to add a declarative composition layer on top.

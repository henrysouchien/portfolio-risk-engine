# Frontend Package Design

## Vision

Clean, self-describing frontend packages that an AI analyst agent can compose into
custom applications on the fly. Each package has a clear contract, minimal coupling,
and no unnecessary indirection.

```
┌─────────────────────────────────────────────────────┐
│  Custom App (assembled by analyst Claude per task)   │
├─────────────────────────────────────────────────────┤
│  @risk/ui         Presentational components          │
│                   (Radix + Tailwind, stateless)       │
├─────────────────────────────────────────────────────┤
│  @risk/connectors Domain hooks, adapters, managers   │
│                   (React Query, Zustand, business     │
│                    logic — the "wiring")              │
├─────────────────────────────────────────────────────┤
│  @risk/chassis    Services, auth, types, caching     │
│                   (pure infra — no React dependency   │
│                    except providers)                  │
├─────────────────────────────────────────────────────┤
│  Backend APIs + MCP Services                         │
└─────────────────────────────────────────────────────┘
```

## Current State (Problems)

### 1. Connectors re-exports all of chassis (line 1: `export * from '@risk/chassis'`)

This means `@risk/connectors` and `@risk/chassis` have identical public APIs from the
consumer's perspective. UI code can import chassis symbols from either package
interchangeably, making the boundary meaningless.

**Today in UI code:**
```ts
import { frontendLogger } from '@risk/chassis';        // direct
import { ProviderRoutingService } from '@risk/connectors'; // pass-through from chassis
import { useRiskAnalysis } from '@risk/connectors';       // actually owned by connectors
```

No consumer can tell what lives where without reading source.

### 2. ~60 proxy/shim files in connectors

Two overlapping shim layers:

- **33 stub files** (`connectors/src/services/APIService.ts`, etc.) — each just
  `export * from '@risk/chassis'`. Created during the monolith split so internal
  relative imports kept working.

- **29 files in `connectors/src/chassis/`** (untracked) — another forwarding layer
  for the same purpose.

These exist because connectors code (managers, adapters, hooks) imports chassis
symbols via relative paths to local shim files instead of using `@risk/chassis`
package imports directly.

### 3. Managers live in connectors but import through shims

```ts
// connectors/src/managers/PortfolioManager.ts — today
import { APIService } from '../services/APIService';           // shim → chassis
import { PortfolioCacheService } from '../services/PortfolioCacheService'; // shim → chassis
```

Should be:
```ts
import { APIService, PortfolioCacheService } from '@risk/chassis';
```

### 4. UI imports chassis-owned symbols from connectors barrel

Because connectors re-exports everything from chassis, UI components import chassis
types/services from `@risk/connectors`. When we stop the re-export, these break.

**Affected UI imports** (chassis symbols currently imported via connectors):
- `ProviderRoutingService` — chassis service class
- `usePortfolioStore`, `useCurrentPortfolio` — chassis store hooks
- `useAuthActions`, `useAuthStore` — chassis auth store
- `User` — chassis type
- `INSTITUTION_CONFIG` — currently in connectors config, may need to move

---

## Target State

### Package Contracts

**`@risk/chassis`** — Infrastructure. No domain logic.
- Services: API, Auth, Claude, Gateway, Plaid, SnapTrade, Cache, etc.
- Stores: auth store, portfolio store (raw state)
- Types: API types, cache types, domain model types
- Config: environment, query config
- Utils: cn, logger, serialization, runtime config
- Providers: AuthProvider, QueryProvider

**`@risk/connectors`** — Domain logic. Depends on chassis.
- Hooks: `useRiskAnalysis`, `usePerformance`, `usePortfolioChat`, etc.
- Adapters: 9 adapters transforming API → UI models
- Managers: Portfolio, Auth, RiskSettings, Stock (orchestration layer)
- Providers: `SessionServicesProvider` (DI container)
- Stores: `uiStore` (UI state — active view, navigation)
- Config: provider config, portfolio config (domain-specific)
- Does NOT re-export chassis. Consumers import chassis directly.

**`@risk/ui`** — Presentational components. Depends on both.
- Components: dashboard views, settings, auth, chat, portfolio
- Imports infrastructure from `@risk/chassis`
- Imports hooks/adapters from `@risk/connectors`
- Stateless where possible; state via hooks from connectors

### Import Rules (enforced by convention, later by lint)

```
@risk/ui        → can import from @risk/chassis AND @risk/connectors
@risk/connectors → can import from @risk/chassis only
@risk/chassis   → imports nothing from the workspace
```

No package re-exports another package's barrel.

---

## Phase 1: Clean Package Boundaries — COMPLETE (cd75978e)

### Step 1 — Remove connectors barrel re-export of chassis

Delete `export * from '@risk/chassis'` from `connectors/src/index.ts` line 1.

This will surface every place that imports a chassis symbol through connectors.

### Step 2 — Fix connectors internal imports

Replace all relative imports to shim files with direct `@risk/chassis` imports.

**Scope:** ~30 files in connectors (managers, adapters, hooks, providers) that
import from `../services/APIService`, `../chassis/services/...`, etc.

```ts
// Before (through shim)
import { APIService } from '../services/APIService';

// After (direct package import)
import { APIService } from '@risk/chassis';
```

### Step 3 — Delete shim/proxy files

Remove all ~60 proxy files:
- `connectors/src/services/*.ts` (shim re-exports)
- `connectors/src/chassis/` (entire directory)
- `connectors/src/types/api.ts`, `types/api-generated.ts`, `types/cache.ts` (re-exports)
- `connectors/src/config/environment.ts`, `config/queryConfig.ts` (re-exports)
- `connectors/src/stores/authStore.ts`, `stores/portfolioStore.ts` (re-exports)
- `connectors/src/repository/PortfolioRepository.ts` (re-export)
- `connectors/src/utils/cacheConfig.ts`, `utils/CacheDebugger.ts`, `utils/AdapterRegistry.ts` (re-exports)
- `connectors/src/providers/QueryProvider.tsx` (re-export)
- `connectors/src/queryKeys.ts` (re-export)

### Step 4 — Fix UI imports

UI files that import chassis symbols from `@risk/connectors` need to switch to
`@risk/chassis`. Affected symbols (from audit):

| Symbol | True owner | UI files using it |
|--------|-----------|-------------------|
| `ProviderRoutingService` | chassis | AccountConnectionsContainer |
| `usePortfolioStore` | chassis | HoldingsViewModernContainer |
| `useCurrentPortfolio` | chassis | ModernDashboardApp |
| `useAuthActions` | chassis | (TBD — audit needed) |
| `User` | chassis | DashboardLayout |
| `INSTITUTION_CONFIG` | connectors config | AccountConnectionsContainer |
| `PortfolioRepository` | chassis | (TBD) |

For each: add `import { Symbol } from '@risk/chassis'` alongside existing connectors import.

### Step 5 — Update connectors barrel to export only owned symbols

Final `connectors/src/index.ts` should contain ONLY connectors-owned exports:
- Hooks (useRiskAnalysis, usePerformance, etc.)
- Adapters (type exports)
- Providers (SessionServicesProvider + hooks)
- UI store (useUIStore, useActiveView)
- Connectors-owned config (providers, portfolio)
- Connectors-owned types
- IntentRegistry

### Step 6 — Fix remaining TS errors

1. `useChat.ts` TS4023 — export `UsePortfolioChatReturn` type from connectors barrel
2. `HoldingsViewModernContainer.tsx` TS2769/TS2322 — type narrowing fixes
3. Any new errors from import changes

### Step 7 — Verify

- `pnpm typecheck` passes (0 errors)
- `pnpm build` succeeds
- `pnpm dev` starts and renders

---

## Phase 2: Wire to Backend + Review UI (future)

- Audit which UI components are wired to real backend endpoints vs stubs
- Review component quality, identify gaps
- Ensure all MCP tool results render correctly in dashboard views

## Phase 3: Agent-Composable App Generation (future)

- Package manifests describing each package's capabilities
- Template system for analyst Claude to assemble apps
- Runtime configuration for selecting which hooks/components to include
- Possibly extract a `@risk/core` package for pure types + schemas (no React)

---

## File Inventory

### Connectors files to DELETE (shims only — no real logic)

```
# Barrel re-exports of @risk/chassis (33 files)
connectors/src/services/APIService.ts
connectors/src/services/AuthService.ts
connectors/src/services/CacheCoordinator.ts
connectors/src/services/CacheMonitor.ts
connectors/src/services/CacheWarmer.ts
connectors/src/services/ClaudeService.ts
connectors/src/services/EventBus.ts
connectors/src/services/PlaidPollingService.ts
connectors/src/services/PlaidService.ts
connectors/src/services/PortfolioCacheService.ts
connectors/src/services/ProviderRoutingService.ts
connectors/src/services/RiskAnalysisService.ts
connectors/src/services/RiskManagerService.ts
connectors/src/services/ServiceContainer.ts
connectors/src/services/SnapTradeService.ts
connectors/src/services/StockCacheService.ts
connectors/src/services/UnifiedAdapterCache.ts
connectors/src/services/index.ts
connectors/src/types/api-generated.ts
connectors/src/types/api.ts
connectors/src/types/cache.ts
connectors/src/types/index.ts
connectors/src/config/environment.ts
connectors/src/config/queryConfig.ts
connectors/src/stores/authStore.ts
connectors/src/stores/portfolioStore.ts
connectors/src/repository/PortfolioRepository.ts
connectors/src/utils/cacheConfig.ts
connectors/src/utils/CacheDebugger.ts
connectors/src/utils/AdapterRegistry.ts
connectors/src/providers/QueryProvider.tsx
connectors/src/queryKeys.ts
connectors/src/services/frontendLogger.ts

# Untracked chassis proxy (29 files)
connectors/src/chassis/  (entire directory)
```

### Connectors files to KEEP (real logic)

```
connectors/src/index.ts              (barrel — will be rewritten)
connectors/src/adapters/             (9 adapters — real transform logic)
connectors/src/features/             (15+ hooks — real domain logic)
connectors/src/managers/             (4 managers — real orchestration)
connectors/src/providers/            (SessionServicesProvider, PortfolioInitializer)
connectors/src/stores/uiStore.ts     (real UI state store)
connectors/src/schemas/              (Zod schemas — real validation)
connectors/src/navigation/           (intent registry — real routing logic)
connectors/src/config/providers.ts   (domain config)
connectors/src/config/portfolio.ts   (domain config)
connectors/src/services/frontendLogger.ts  (if it has real logic — verify)
```

### UI files to MODIFY (import path changes)

```
App.tsx
AccountConnectionsContainer.tsx
HoldingsViewModernContainer.tsx
ModernDashboardApp.tsx
DashboardLayout.tsx
(+ any others importing chassis symbols from @risk/connectors)
```

# Frontend Three-Package Split: Implementation Plan

**Date**: 2026-02-24
**Status**: ✅ Complete (Phase A)
**Scope**: Split `frontend/src/` into `@risk/chassis`, `@risk/connectors`, `@risk/ui`

## Overview

Split the frontend monolith (~312 files, ~80K LOC) into three packages with strict dependency direction: `ui → connectors → chassis`. This enables:

- **`@risk/chassis`** — Multi-user web app infrastructure. Auth with cross-tab sync, coordinated caching (6-piece), API client with streaming, service container with DI, React Query setup. Not portfolio-specific — this is the foundation for building any multi-user app.

- **`@risk/connectors`** — Typed connection layer to the portfolio risk backend. Adapters that know the API response shapes, hooks that fetch/cache/return typed data, services that call backend endpoints. Install this + chassis, point at a compatible backend, and you have all the data plumbing — just build your UI.

- **`@risk/ui`** — Our specific dashboard implementation. Fully swappable. Someone else could build a completely different frontend on chassis + connectors.

**The product**: Install chassis + connectors, point at a compatible backend (aligned with risk_module/portfolio system), and you have a fully functional multi-user app — just build your UI. The backend handles all the complexity (providers, risk calculations, portfolio management). The connectors just know how to talk to it.

Phase B: gateway channel integration for shared AI chat across surfaces (dashboard, Excel, TUI).

## Current State

- **Build**: Create React App (react-scripts 5.0.1) — no monorepo support
- **No path aliases**: all relative imports
- **No monorepo tooling**: no Nx, Turbo, pnpm workspaces
- **Clean layering**: mostly clean with a few boundary violations identified and addressed in Step 0.5
- **Provider hierarchy**: QueryProvider → AuthProvider → SessionServicesProvider → App

## Prerequisites

### CRA → Vite Migration

CRA doesn't support monorepo packages. Migrate to Vite first — this is a prerequisite, not optional.

**Why Vite**:
- Native monorepo/workspace support
- Faster dev server (ESM-based, no webpack bundling)
- Simple config — `vite.config.ts` replaces hidden CRA webpack
- First-class TypeScript path alias support
- Mature ecosystem, Tailwind/React/Radix all work out of the box

**Migration steps**:
1. Install Vite + plugins: `vite`, `@vitejs/plugin-react`, `vite-tsconfig-paths`
2. Create `vite.config.ts` at `frontend/` root
3. Move `public/index.html` to `frontend/index.html` (Vite convention), add `<script type="module" src="/src/index.tsx">`
4. Replace `react-scripts` scripts in package.json: `vite` (dev), `vite build`, `vite preview`
5. Remove `react-scripts`, `react-app-rewired` if present
6. Replace any `process.env.REACT_APP_*` with `import.meta.env.VITE_*`
7. Update `tsconfig.json`: target ES2020+, module ESNext, moduleResolution bundler
8. Verify: dev server starts, build succeeds, all features work

**Risk**: Medium (revised from Low after Codex review). Specific issues to address:
- `process.env.NODE_ENV` used in ~15 files for dev-mode checks — Vite replaces this automatically, but verify
- `process.env.REACT_APP_*` used in ~5 files (`REACT_APP_API_URL`, `REACT_APP_GOOGLE_CLIENT_ID`, `REACT_APP_PORTFOLIO_CACHE_TTL`, `REACT_APP_ENABLE_LOGGING`, `REACT_APP_API_TIMEOUT`, `REACT_APP_CACHE_TIMEOUT`) — must rename to `VITE_*`
- CommonJS `require()` calls in `SessionServicesProvider.tsx` (6 occurrences) — convert to dynamic `import()` or standard ESM imports
- Proxy config needs to cover `/auth/*` and `/plaid/*` endpoints in addition to `/api`
- Entry point is `index.js` (not `.tsx`) — verify Vite resolves this correctly

---

## Phase A: Package Split

### Step 0: Archive Legacy Code

Move `frontend/src/legacy/` to `frontend/archive/legacy/`. ~6,500 LOC of deprecated components, views, and routing.

**Known live reference**: `components/apps/index.ts:113` re-exports `DashboardApp` from `../../legacy/apps/DashboardApp`. Fix this before archiving — either remove the export (if unused) or inline the component.

```
# 1. Fix live legacy reference in components/apps/index.ts
# 2. Then archive
mkdir -p frontend/archive
mv frontend/src/legacy frontend/archive/legacy
# 3. Grep for any remaining imports from legacy/ — fix or remove
```

### Step 0.5: Untangle Boundary Violations

Before the mechanical file moves, fix imports that would violate the `ui → connectors → chassis` direction. These must be resolved first or the split will have circular dependencies. (Note: the live legacy export from `components/apps/index.ts` is handled in Step 0 before archiving.)

#### Violation 1: AuthProvider → AuthInitializer (chassis → UI)

`AuthProvider.tsx` (planned for chassis) imports `AuthInitializer` (a UI component that renders a loading spinner).

**Fix**: Merge `AuthInitializer` logic into `AuthProvider` directly. `AuthInitializer` is small (~20 lines of logic) — it just calls `initializeAuth()` in a useEffect and shows a loading div. Inline this into `AuthProvider` so chassis has no UI dependency. The loading indicator becomes a simple inline `<div>` (already is — no external component needed).

#### Violation 2: sessionCleanup → portfolioStore + uiStore (chassis → connectors)

`sessionCleanup.ts` (planned for chassis) imports `portfolioStore`, `uiStore`, `AdapterRegistry`, and `resetQueryClient` to clear all state on logout.

**Fix**: Make `sessionCleanup` accept a cleanup callback instead of importing stores directly. Move `sessionCleanup.ts` to `@risk/connectors` (it's session-scoped business logic, not generic infrastructure). The chassis `authStore` calls a registered cleanup function rather than importing session cleanup directly.

```typescript
// Chassis: authStore provides a hook point
let onSessionCleanup: (() => void) | null = null;
export const registerSessionCleanup = (fn: () => void) => { onSessionCleanup = fn; };

// Connectors: registers the cleanup that knows about stores
registerSessionCleanup(() => {
  usePortfolioStore.getState().clearAll();
  useUIStore.getState().clearNotifications();
  AdapterRegistry.clear();
  resetQueryClient();
});
```

#### Violation 3: authStore → sessionCleanup cycle

`authStore.ts` imports `onCrossTabLogout` from `sessionCleanup`, and `sessionCleanup` imports `useAuthStore`. This is a circular dependency.

**Fix**: Same as Violation 2 — once `sessionCleanup` moves to connectors and uses the registered callback pattern, the cycle breaks. `authStore` (chassis) calls `onSessionCleanup()` without importing anything from connectors.

#### Violation 4: PortfolioInitializer → LoadingView (connectors → UI)

`PortfolioInitializer.tsx` (planned for connectors) imports `LoadingView` component for its loading state.

**Fix**: Replace the `LoadingView` import with inline JSX (it's just a centered spinner div). Or: accept a `loadingComponent` prop so the UI layer can inject its own loading indicator. The render props pattern keeps connectors UI-agnostic:

```typescript
// Connectors: PortfolioInitializer accepts optional render props
interface PortfolioInitializerProps {
  children: ReactNode;
  loadingFallback?: ReactNode;  // UI layer provides this
  errorFallback?: (error: Error) => ReactNode;
}
```

#### Violation 5: SessionServicesProvider → uiStore via require()

`SessionServicesProvider.tsx` uses `require('../stores/uiStore')` in 5 places (CommonJS dynamic imports to avoid circular deps). These access `uiStore` for error state and notifications.

**Fix**: Convert `require()` to standard ESM imports. The `uiStore` is planned for connectors alongside `SessionServicesProvider`, so once both are in the same package this is an internal import — no boundary violation. The `require()` calls were a workaround for import ordering, not a real architectural issue. Clean these up to standard imports during the move.

#### Violation 6: Cross-feature imports in hooks

`useRiskMetrics` imports from `../../analysis/hooks/usePerformance` and `../../analysis/hooks/useRiskAnalysis`. This is cross-feature coupling.

**Fix**: Acceptable — both `riskMetrics` and `analysis` are in `@risk/connectors`. These become internal imports within the same package. No boundary violation, just update the relative paths. The barrel export from `@risk/connectors` flattens this for external consumers.

#### Violation 7: Missing file allocations

Files not allocated in the plan:
- `utils/CacheDebugger.ts` → **chassis** (debugging tool for coordinated caching)
- `chassis/services/index.ts` → **chassis** (barrel export, merge with new barrel)
- `data/index.ts` → **UI** (chart color constants, imports from `theme/colors`)
- `features/scenario/index.ts` → **connectors** (feature barrel, even if minimal)
- `chassis/hooks/usePortfolio.ts` → **connectors** (if still used) or delete

### Step 1: Set Up Monorepo Workspace

Use pnpm workspaces (lightweight, fast, good monorepo support).

**Directory structure**:
```
frontend/
├── package.json              # Root workspace config
├── pnpm-workspace.yaml       # Workspace definition
├── vite.config.ts            # App-level Vite config (builds @risk/ui as the app)
├── tsconfig.json             # Root tsconfig with project references
├── index.html                # Vite entry
│
├── packages/
│   ├── chassis/              # @risk/chassis
│   │   ├── package.json
│   │   ├── tsconfig.json
│   │   └── src/
│   │
│   ├── connectors/           # @risk/connectors
│   │   ├── package.json
│   │   ├── tsconfig.json
│   │   └── src/
│   │
│   └── ui/                   # @risk/ui (also the app entry point)
│       ├── package.json
│       ├── tsconfig.json
│       └── src/
│
└── archive/
    └── legacy/               # Archived deprecated code
```

**pnpm-workspace.yaml**:
```yaml
packages:
  - 'packages/*'
```

**Root package.json** (workspace root):
```json
{
  "private": true,
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview",
    "lint": "eslint packages/*/src --ext .ts,.tsx",
    "test": "vitest"
  }
}
```

### Step 2: Define Package Boundaries

Each package gets its own `package.json`, `tsconfig.json`, and barrel `index.ts`.

#### `@risk/chassis` — Generic App Framework

**package.json** (no React dependency — pure TypeScript where possible):
```json
{
  "name": "@risk/chassis",
  "private": true,
  "main": "src/index.ts",
  "peerDependencies": {
    "react": "^19.0.0",
    "@tanstack/react-query": "^5.0.0",
    "zustand": "^4.5.0"
  }
}
```

**Files to move** (`frontend/src/` → `packages/chassis/src/`):

```
# API & HTTP
chassis/services/APIService.ts
chassis/services/AuthService.ts

# Caching system (6-piece)
chassis/services/EventBus.ts
chassis/services/UnifiedAdapterCache.ts
chassis/services/CacheCoordinator.ts
chassis/services/CacheMonitor.ts
chassis/services/CacheWarmer.ts
chassis/services/PortfolioCacheService.ts
chassis/services/StockCacheService.ts

# DI container
chassis/services/ServiceContainer.ts

# Auth
stores/authStore.ts
providers/AuthProvider.tsx          # After Step 0.5: AuthInitializer logic inlined
providers/QueryProvider.tsx
utils/broadcastLogout.ts
services/SecureStorage.ts
# Note: sessionCleanup.ts moves to @risk/connectors (see Step 0.5)

# Logging
services/frontendLogger.ts
utils/ArchitecturalLogger.ts

# Config & utilities
utils/cacheConfig.ts
utils/AdapterRegistry.ts
utils/ErrorAdapter.ts
utils/loadRuntimeConfig.ts
utils/CacheDebugger.ts
config/environment.ts
config/queryConfig.ts
lib/utils.ts
```

**Barrel export** (`packages/chassis/src/index.ts`):
```typescript
// API
export { APIService } from './services/APIService';
export { AuthService } from './services/AuthService';

// Caching
export { EventBus } from './services/EventBus';
export { UnifiedAdapterCache } from './services/UnifiedAdapterCache';
export { CacheCoordinator } from './services/CacheCoordinator';
export { CacheMonitor } from './services/CacheMonitor';
export { CacheWarmer } from './services/CacheWarmer';
export { PortfolioCacheService } from './services/PortfolioCacheService';
export { StockCacheService, stockCacheService } from './services/StockCacheService';

// DI
export { ServiceContainer } from './services/ServiceContainer';

// Auth & state
export { useAuthStore } from './stores/authStore';
export { AuthProvider } from './providers/AuthProvider';
export { QueryProvider } from './providers/QueryProvider';

// Utilities
export { frontendLogger } from './services/frontendLogger';
export { SecureStorage } from './services/SecureStorage';
export * from './utils/cacheConfig';
export * from './utils/ErrorAdapter';
export * from './config/environment';
```

#### `@risk/connectors` — Backend Connection Layer

**package.json**:
```json
{
  "name": "@risk/connectors",
  "private": true,
  "main": "src/index.ts",
  "dependencies": {
    "@risk/chassis": "workspace:*"
  },
  "peerDependencies": {
    "react": "^19.0.0",
    "@tanstack/react-query": "^5.0.0",
    "zustand": "^4.5.0"
  }
}
```

**Files to move** (`frontend/src/` → `packages/connectors/src/`):

```
# Managers
chassis/managers/PortfolioManager.ts
chassis/managers/AuthManager.ts
chassis/managers/RiskSettingsManager.ts
chassis/managers/StockManager.ts

# Domain services
chassis/services/ClaudeService.ts
chassis/services/PlaidService.ts
chassis/services/SnapTradeService.ts
chassis/services/PlaidPollingService.ts
chassis/services/ProviderRoutingService.ts
chassis/services/RiskAnalysisService.ts
chassis/services/RiskManagerService.ts

# Adapters (all 9)
adapters/AnalysisReportAdapter.ts
adapters/PerformanceAdapter.ts
adapters/PortfolioOptimizationAdapter.ts
adapters/PortfolioSummaryAdapter.ts
adapters/RiskAnalysisAdapter.ts
adapters/RiskScoreAdapter.ts
adapters/RiskSettingsAdapter.ts
adapters/StockAnalysisAdapter.ts
adapters/WhatIfAnalysisAdapter.ts

# Feature hooks (all 11 feature modules)
features/analysis/hooks/          → useAnalysisReport, usePerformance, useRiskAnalysis
features/auth/hooks/              → useAuthFlow, useConnectAccount, useConnectSnapTrade
features/external/hooks/          → useChat, usePortfolioChat, usePlaid, useSnapTrade
features/optimize/hooks/          → usePortfolioOptimization
features/portfolio/hooks/         → useInstantAnalysis, usePendingUpdates, usePortfolioSummary
features/riskMetrics/hooks/       → useRiskMetrics
features/riskScore/hooks/         → useRiskScore
features/riskSettings/hooks/      → useRiskSettings
features/stockAnalysis/hooks/     → useStockAnalysis
features/utils/hooks/             → useCancelableRequest, useCancellablePolling, usePlaidPolling
features/whatIf/hooks/            → useWhatIfAnalysis
features/scenario/index.ts        → scenario barrel export

# Stores (domain-specific)
stores/portfolioStore.ts
stores/uiStore.ts

# Providers (domain-specific)
providers/SessionServicesProvider.tsx
providers/PortfolioInitializer.tsx

# Repository
repository/PortfolioRepository.ts

# Session cleanup (moved here from chassis — uses stores, see Step 0.5)
utils/sessionCleanup.ts

# Navigation
chassis/navigation/NavigationIntents.ts
chassis/navigation/NavigationResolver.ts
utils/NavigationIntents.ts

# Types & schemas
chassis/types/index.ts
chassis/schemas/api-schemas.ts
types/api-generated.ts
types/api.ts
types/cache.ts
types/snaptrade-react.d.ts

# Query keys
queryKeys.ts

# Config
config/portfolio.ts
config/providers.ts
```

**Barrel export** (`packages/connectors/src/index.ts`):
```typescript
// Re-export chassis for convenience
export * from '@risk/chassis';

// Hooks (primary consumer API)
export { useRiskScore } from './features/riskScore';
export { useRiskAnalysis, usePerformance, useAnalysisReport } from './features/analysis';
export { usePortfolioSummary, useInstantAnalysis, usePendingUpdates } from './features/portfolio';
export { usePortfolioOptimization } from './features/optimize';
export { useWhatIfAnalysis } from './features/whatIf';
export { useRiskSettings } from './features/riskSettings';
export { useStockAnalysis } from './features/stockAnalysis';
export { usePortfolioChat, useChat } from './features/external';
export { usePlaid, useSnapTrade } from './features/external';
export { useAuthFlow } from './features/auth';
export { useRiskMetrics } from './features/riskMetrics';

// Providers
export { SessionServicesProvider, useSessionServices } from './providers/SessionServicesProvider';
export { PortfolioInitializer } from './providers/PortfolioInitializer';

// Stores
export { usePortfolioStore } from './stores/portfolioStore';
export { useUiStore } from './stores/uiStore';

// Types (re-exported for UI consumption)
export * from './types';
export * from './queryKeys';
```

#### `@risk/ui` — Dashboard Frontend

**package.json**:
```json
{
  "name": "@risk/ui",
  "private": true,
  "main": "src/index.ts",
  "dependencies": {
    "@risk/connectors": "workspace:*"
  },
  "peerDependencies": {
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  }
}
```

**Files to move** (`frontend/src/` → `packages/ui/src/`):

```
# Radix component library (40+ components)
components/ui/                    → Full directory

# Dashboard views
components/dashboard/             → All view containers, charts, shared
components/portfolio/             → PortfolioOverview, RiskAnalysis, PerformanceView, etc.

# Chat UI
components/chat/                  → ChatCore, AIChat, ChatContext

# Auth UI
components/auth/                  → LandingPage, GoogleSignInButton

# Settings
components/settings/              → AccountConnections

# External service UI
components/plaid/                 → PlaidLinkButton, ConnectedAccounts
components/snaptrade/             → SnapTradeLaunchButton, ConnectedSnapTradeAccounts

# Shared UI
components/shared/                → LoadingSpinner, ErrorDisplay, etc.
components/transitions/           → AuthTransition

# App orchestration
components/apps/                  → ModernDashboardApp, LandingApp
router/                           → AppOrchestrator, AppOrchestratorModern

# Pages
pages/                            → LandingPage, InstantTryPage, PlaidSuccess, SnapTradeSuccess

# Layout
components/layout/                → ChatInterface
components/layouts/               → DashboardLayout

# Misc UI files
components/AnalysisSection.tsx
components/AuthInitializer.tsx
components/FileUploadSection.tsx

# Presentational hooks
hooks/use-mobile.tsx
hooks/use-toast.ts

# Chart data constants
data/index.ts                     # CHART_COLORS, imports from theme/colors

# Theming
theme/colors.ts

# Entry points
App.tsx
index.tsx (or index.js)
index.css
```

### Step 3: Update Import Paths

This is the most mechanical part. Every file that currently does:
```typescript
import { APIService } from '../../chassis/services/APIService';
import { useRiskScore } from '../../features/riskScore';
```

Changes to:
```typescript
import { APIService } from '@risk/chassis';
import { useRiskScore } from '@risk/connectors';
```

**Strategy**:
1. Start from the bottom: update `@risk/chassis` files first (internal imports only)
2. Then `@risk/connectors` files (import from `@risk/chassis` + internal)
3. Then `@risk/ui` files (import from `@risk/connectors` + internal)
4. Use find-and-replace with manual review — most patterns are consistent

**TypeScript path resolution**:
Each package's `tsconfig.json` uses project references:
```json
// packages/connectors/tsconfig.json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "rootDir": "src",
    "outDir": "dist"
  },
  "references": [
    { "path": "../chassis" }
  ]
}
```

Root `tsconfig.json` with `vite-tsconfig-paths` plugin handles resolution during dev.

### Step 4: Dependency Allocation

Split the current `package.json` dependencies across packages. Each package only declares what it directly uses.

#### `@risk/chassis` dependencies
```
zustand                          # authStore
@tanstack/react-query            # QueryProvider
@tanstack/react-query-devtools   # DevTools (conditional, dev only)
zod                              # schema validation (if used in chassis)
```

#### `@risk/connectors` (backend connection layer) dependencies
```
@risk/chassis                    # workspace dependency
react-plaid-link                 # PlaidService
ai, @ai-sdk/anthropic, @ai-sdk/react  # ClaudeService (until Phase B removes these)
zod                              # schemas
```

#### `@risk/ui` dependencies
```
@risk/connectors                 # workspace dependency
@radix-ui/*                      # All Radix components
tailwindcss                      # Styling
framer-motion                    # Animations
recharts                         # Charts
sonner                           # Toast notifications
embla-carousel-react             # Carousel
lucide-react                     # Icons
react-router-dom                 # Routing
class-variance-authority         # CVA for component variants
clsx, tailwind-merge             # Utility classes
react-hook-form                  # Forms (used in UI form components)
snaptrade-react                  # SnapTrade launch button UI component
```

#### Root (dev dependencies)
```
vite, @vitejs/plugin-react       # Build
vitest                           # Testing
typescript                       # Shared
eslint, eslint plugins           # Linting
tailwindcss, postcss, autoprefixer  # CSS build
msw                              # Mocking
openapi-typescript               # Type generation
```

### Step 5: Vite Config for Monorepo

```typescript
// frontend/vite.config.ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tsconfigPaths from 'vite-tsconfig-paths';

export default defineConfig({
  plugins: [react(), tsconfigPaths()],
  root: '.',
  build: {
    outDir: 'build',
  },
  server: {
    port: 3000,
    proxy: {
      '/api': 'http://localhost:5001',
      '/auth': 'http://localhost:5001',
      '/plaid': 'http://localhost:5001',
    },
  },
});
```

The app entry point (`index.html` → `packages/ui/src/index.tsx`) imports from `@risk/connectors` and `@risk/chassis` — Vite resolves via workspace links.

### Step 6: Boundary Enforcement

Add ESLint rules to enforce the dependency direction:

```javascript
// .eslintrc.js (per-package overrides)
{
  overrides: [
    {
      // Chassis: cannot import from domain or ui
      files: ['packages/chassis/src/**/*'],
      rules: {
        'no-restricted-imports': ['error', {
          patterns: ['@risk/connectors', '@risk/connectors/*', '@risk/ui', '@risk/ui/*']
        }]
      }
    },
    {
      // Connectors: can import chassis, cannot import ui
      files: ['packages/connectors/src/**/*'],
      rules: {
        'no-restricted-imports': ['error', {
          patterns: ['@risk/ui', '@risk/ui/*']
        }]
      }
    }
  ]
}
```

### Step 7: Verify

1. `pnpm install` — workspace links resolve
2. `pnpm dev` — Vite dev server starts, app loads
3. `pnpm build` — production build succeeds
4. `pnpm lint` — no boundary violations
5. Manual smoke test — all dashboard views, auth flow, chat, Plaid/SnapTrade still work
6. No behavioral changes — this is purely structural

---

## Phase B: Gateway Channel Integration (Future)

After Phase A is stable, swap the chat layer:

1. **Define frontend tool contract** in `@risk/connectors` (or `@risk/ui`):
   ```typescript
   interface DashboardTools {
     navigate_view(params: { view: string }): void;
     get_dashboard_state(): { active_view: string; portfolio_id: string; ... };
     show_notification(params: { message: string; severity: string }): void;
     highlight_holding(params: { ticker: string }): void;
     open_what_if(params: { scenario: object }): void;
   }
   ```

2. **Build gateway channel client** in `@risk/chassis`:
   - SSE connection (~80 lines, same as Excel taskpane `ChatService.ts`)
   - Tool request/result protocol with nonce + expiry
   - Channel registration with tool declarations
   - Heartbeat handling

3. **Wire tool handlers** in `@risk/ui`:
   ```typescript
   channel.registerTool('navigate_view', ({ view }) => setActiveView(view));
   channel.registerTool('get_dashboard_state', () => ({ active_view, portfolio_id }));
   ```

4. **Remove old chat plumbing** from `@risk/connectors` and `@risk/ui`:
   - Delete: `ClaudeService.ts`, `usePortfolioChat.ts`, `useChat.ts`
   - Remove: `ai`, `@ai-sdk/anthropic`, `@ai-sdk/react` dependencies
   - ChatCore UI in `@risk/ui` switches from hook-based streaming to gateway SSE events

5. **Register** `RISK_DASHBOARD` channel type in AI-excel-addin gateway's `ChannelRegistry`

---

## Phase C: Publishable Packages (Future)

After Phase A, chassis and connectors work as internal workspace packages (Vite resolves raw TypeScript source via workspace links). To make them publishable (npm or private registry):

1. **Build step** — Add `tsup` or Vite library mode to compile TypeScript → JavaScript + `.d.ts` type declarations. Each package gets a `dist/` output.

2. **Externalize configuration** — Currently some config is implicit (env vars, hardcoded URLs, default TTLs). For a publishable package, these need to be explicit constructor params or a config object the consumer passes in:
   ```typescript
   // Internal (implicit — reads VITE_API_URL)
   const api = new APIService();

   // Publishable (explicit — consumer provides config)
   const api = new APIService({ baseUrl: 'https://my-backend.com' });
   ```
   Key items to externalize:
   - API base URL and endpoint paths
   - Auth endpoint configuration
   - Cache TTL defaults
   - Environment detection (dev vs prod)

3. **README + docs** — Installation, configuration, what each export does.

4. **Peer dependency ranges** — Verify React, React Query, Zustand version ranges are correct and not overly restrictive.

5. **Tests** — Ensure core chassis functionality has unit test coverage independent of the app.

This is a moderate-effort follow-on, not a prerequisite for Phase A or B. The split itself is what matters — publishability is incremental.

---

## Execution Sequence

```
Step 0:   Archive legacy/                              (~30 min)
          - Fix live export in components/apps/index.ts first
          - Move legacy/ to archive/
          - Grep for remaining legacy imports

Step 0.5: Untangle boundary violations                 (~2-3 hours)
          - Inline AuthInitializer into AuthProvider
          - Move sessionCleanup to connectors, use registered callback pattern
          - Break authStore ↔ sessionCleanup cycle
          - Add render props to PortfolioInitializer (remove LoadingView import)
          - Convert require() calls in SessionServicesProvider to ESM imports
          - Allocate missing files (CacheDebugger, data/index, scenario/index)
          - Verify no new boundary violations

Step 1:   CRA → Vite migration                         (~2-3 hours)
          - Install Vite, create config
          - Move index.html, rename index.js → index.tsx
          - Rename REACT_APP_* env vars to VITE_* (6 vars)
          - Proxy config: /api, /auth, /plaid
          - Remove react-scripts
          - Verify dev + build

Step 2:   Set up monorepo workspace                    (~1 hour)
          - pnpm-workspace.yaml
          - Package directories + package.json files
          - tsconfig project references

Step 3:   Move chassis files + update imports          (~2-3 hours)
          - Move ~27 files to packages/chassis/ (including CacheDebugger)
          - Update internal imports
          - Create barrel export
          - Verify build

Step 4:   Move connectors files + update imports       (~3-4 hours)
          - Move ~65+ files to packages/connectors/ (including sessionCleanup)
          - Update imports to use @risk/chassis
          - Update internal imports
          - Create barrel export
          - Verify build

Step 5:   Move UI files + update imports               (~3-4 hours)
          - Move ~200+ files to packages/ui/ (including data/index.ts)
          - Update imports to use @risk/connectors
          - Create barrel export
          - Verify build

Step 6:   Dependency allocation                        (~1 hour)
          - Split package.json across three packages
          - react-query-devtools → chassis, snaptrade-react + react-hook-form → ui
          - pnpm install, verify resolution

Step 7:   Boundary enforcement + final verification    (~1 hour)
          - ESLint rules (chassis: no connectors/ui, connectors: no ui)
          - Full smoke test
          - Commit
```

**Total estimated effort**: ~3-4 sessions of focused work

---

## Risks & Mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| CRA → Vite: `process.env` references | Medium | ~30 occurrences total. `NODE_ENV` is auto-replaced by Vite. `REACT_APP_*` (6 vars) → rename to `VITE_*`. Finite set, grep-and-replace. |
| CRA → Vite: CommonJS `require()` calls | Medium | 6 `require()` calls in SessionServicesProvider.tsx. Convert to ESM `import` during Step 0.5 violation fixes. |
| CRA → Vite: proxy config incomplete | Low | Current CRA proxy only covers `/api`. Vite config must also proxy `/auth/*` and `/plaid/*`. Addressed in plan. |
| CRA → Vite: `index.js` entry point | Low | Current entry is `index.js` not `index.tsx`. Rename or configure Vite to resolve. |
| Boundary violations during split | High → Low | 7 violations identified and fix strategies documented in Step 0.5. Must complete before mechanical moves. |
| Import path updates missed | Medium | TypeScript compiler will catch missing imports; incremental verification at each step. |
| Tailwind stops working across packages | Low | Single Tailwind config at root with content paths covering all packages. |
| Test setup breaks | Medium | Migrate from react-scripts test to Vitest (native Vite test runner); MSW setup stays the same. |
| Dependency misallocation | Low | Validated against actual imports (Codex review). `snaptrade-react` and `react-hook-form` in UI, `react-query-devtools` in chassis. |

---

## Success Criteria

- [x] `pnpm dev` starts and all features work
- [x] `pnpm build` produces production bundle
- [ ] `pnpm lint` passes with boundary enforcement (0 errors; ESLint boundary rules not yet added)
- [x] No behavioral changes from user perspective
- [x] `@risk/chassis` has zero imports from domain or ui
- [x] `@risk/connectors` has zero imports from ui
- [x] Chassis + connectors are usable as standalone packages (someone could build a different UI on top)
- [ ] `legacy/` archived and removed from active source (moved out of `src/`, not yet archived)

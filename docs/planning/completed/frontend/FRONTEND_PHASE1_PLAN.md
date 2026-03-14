# Phase 1: Clean Package Boundaries — Execution Plan

**Goal:** Remove all ~60 shim/proxy re-export files from `@risk/connectors`. Every file
imports chassis symbols directly from `@risk/chassis`. The connectors barrel exports only
connectors-owned code.

**Parent doc:** `FRONTEND_PACKAGE_DESIGN.md`

---

## Classification Key

Every file in `connectors/src/` falls into one of two categories:

| Category | Action | Example |
|----------|--------|---------|
| **SHIM** — `export * from '@risk/chassis'` (1 line) | Delete after dependents are updated | `services/APIService.ts` |
| **REAL** — Contains actual logic | Keep, update its imports | `managers/PortfolioManager.ts` |

---

## Step 1: Update connectors-internal imports (REAL files → `@risk/chassis`)

Every REAL connectors file that imports through a SHIM path needs to switch to
`@risk/chassis`. Relative imports to other REAL connectors files stay unchanged.

### 1A. Managers (4 files)

**`managers/AuthManager.ts`**
```
L19: import { APIService } from '../services/APIService'          → '@risk/chassis'
L20: import { User } from '../types/index'                        → '@risk/chassis'
L21: import { frontendLogger } from '../services/frontendLogger'  → '@risk/chassis'
```
Collapse to: `import { APIService, User, frontendLogger } from '@risk/chassis';`

**`managers/PortfolioManager.ts`**
```
L22: import { PortfolioRepository } from '../repository/PortfolioRepository'  → '@risk/chassis'
L23: import { APIService } from '../services/APIService'                       → '@risk/chassis'
L24: import { frontendLogger } from '../services/frontendLogger'               → '@risk/chassis'
L25: import { PortfolioCacheService } from '../services/PortfolioCacheService' → '@risk/chassis'
L26: import { usePortfolioStore } from '../stores/portfolioStore'              → '@risk/chassis'
L27: import { Portfolio,RiskAnalysis,RiskScore } from '../types/index'         → '@risk/chassis'
```
Collapse to: `import { PortfolioRepository, APIService, frontendLogger, PortfolioCacheService, usePortfolioStore, Portfolio, RiskAnalysis, RiskScore } from '@risk/chassis';`

**`managers/RiskSettingsManager.ts`**
```
L35: import { PortfolioCacheService } from '../services/PortfolioCacheService' → '@risk/chassis'
L36: import { APIService } from '../services/APIService'                       → '@risk/chassis'
L37: import { frontendLogger } from '../services/frontendLogger'               → '@risk/chassis'
L38: import { usePortfolioStore } from '../stores/portfolioStore'              → '@risk/chassis'
```
Collapse to: `import { PortfolioCacheService, APIService, frontendLogger, usePortfolioStore } from '@risk/chassis';`

**`managers/StockManager.ts`**
```
L35: import { frontendLogger } from '../services/frontendLogger'    → '@risk/chassis'
L36: import { StockCacheService } from '../services/StockCacheService' → '@risk/chassis'
```
Collapse to: `import { frontendLogger, StockCacheService } from '@risk/chassis';`

### 1B. Providers (2 files)

**`providers/SessionServicesProvider.tsx`** (heaviest — 16 shim imports)
```
L87: import { useAuthStore } from '../stores/authStore'                            → '@risk/chassis'
L88: import { APIService } from '../chassis/services/APIService'                   → '@risk/chassis'
L89: import { PortfolioCacheService } from '../chassis/services/PortfolioCacheService' → '@risk/chassis'
L93: import { EventBus } from '../chassis/services/EventBus'                       → '@risk/chassis'
L94: import { UnifiedAdapterCache } from '../chassis/services/UnifiedAdapterCache' → '@risk/chassis'
L95: import { CacheCoordinator } from '../chassis/services/CacheCoordinator'       → '@risk/chassis'
L96: import { CacheMonitor } from '../chassis/services/CacheMonitor'               → '@risk/chassis'
L97: import { CacheWarmer } from '../chassis/services/CacheWarmer'                 → '@risk/chassis'
L98: import { stockCacheService } from '../chassis/services'                       → '@risk/chassis'
L100: import { frontendLogger } from '../services/frontendLogger'                  → '@risk/chassis'
L101: import { ServiceContainer } from '../chassis/services/ServiceContainer'      → '@risk/chassis'
L103: import { PlaidPollingService } from '../chassis/services/PlaidPollingService' → '@risk/chassis'
L104: import { usePortfolioStore } from '../stores/portfolioStore'                 → '@risk/chassis'
L106: import { PortfolioRepository } from '../repository/PortfolioRepository'      → '@risk/chassis'
```
Keep as local (REAL connectors files):
```
L90: import { PortfolioManager } from '../chassis/managers/PortfolioManager'       → '../managers/PortfolioManager'
L91: import { RiskSettingsManager } from '../chassis/managers/RiskSettingsManager'  → '../managers/RiskSettingsManager'
L92: import { StockManager } from '../chassis/managers/StockManager'                → '../managers/StockManager'
L99: import { CacheDebugger } from '../utils/CacheDebugger'                        → KEEP (connectors-owned shim)
L102: import { IntentRegistry } from '../utils/NavigationIntents'                  → KEEP
L105: import { useUIStore } from '../stores/uiStore'                               → KEEP
```
Note: `CacheDebugger` is currently a shim — will also need to change to `@risk/chassis`.

**`providers/PortfolioInitializer.tsx`**
```
L5: import { useAuthStore } from '../stores/authStore'                 → '@risk/chassis'
L6: import { usePortfolioStore } from '../stores/portfolioStore'       → '@risk/chassis'
L7: import { PortfolioRepository } from '../repository/PortfolioRepository' → '@risk/chassis'
L9: import { frontendLogger } from '../services/frontendLogger'        → '@risk/chassis'
L10: import { initialPortfolioKey } from '../queryKeys'                → '@risk/chassis'
```
Keep: `L4: import { useAPIService } from './SessionServicesProvider'` (connectors-owned)
Keep: `L8: import { DEFAULT_PORTFOLIO_NAME } from '../config/portfolio'` (connectors-owned)

### 1C. Stores (1 file)

**`stores/uiStore.ts`**
```
L57: import { frontendLogger } from '../services/frontendLogger'    → '@risk/chassis'
```

### 1D. Utils (2 files)

**`utils/sessionCleanup.ts`**
```
L6:  import { registerSessionCleanup, useAuthStore } from '../stores/authStore' → '@risk/chassis'
L7:  import { usePortfolioStore } from '../stores/portfolioStore'               → '@risk/chassis'
L9:  import { AdapterRegistry } from './AdapterRegistry'                        → '@risk/chassis'
L10: import { resetQueryClient } from '../providers/QueryProvider'              → '@risk/chassis'
L11: import { frontendLogger } from '../services/frontendLogger'                → '@risk/chassis'
```
Keep: `L8: import { useUIStore } from '../stores/uiStore'` (connectors-owned)

**`utils/NavigationIntents.ts`**
```
L30: import { frontendLogger } from '../services/frontendLogger'    → '@risk/chassis'
```

### 1E. Adapters (9 files)

All 9 adapters follow the same pattern. Shim imports to replace:

| Import target | Adapter files using it |
|---------------|----------------------|
| `../services/frontendLogger` → `@risk/chassis` | All 9 |
| `../utils/cacheConfig` (getCacheTTL) → `@risk/chassis` | All 9 |
| `../types/cache` (generateStandardCacheKey, generateContentHash, CacheKeyMetadata) → `@risk/chassis` | All 9 |
| `../types/api` (response types) → `@risk/chassis` | RiskSettings, StockAnalysis, PortfolioOptimization, WhatIfAnalysis |
| `../chassis/schemas/api-schemas` (RiskScoreResponseSchema) → local `../schemas/api-schemas` | RiskScore only |
| `../chassis/services/UnifiedAdapterCache` → `@risk/chassis` | All 9 (type-only import) |

Files (shim import lines):
- `adapters/AnalysisReportAdapter.ts` — L89 frontendLogger, L90 getCacheTTL, L91 cache types, L90 UnifiedAdapterCache
- `adapters/PerformanceAdapter.ts` — L148 frontendLogger, L150 getCacheTTL, L149 cache types, L147 UnifiedAdapterCache
- `adapters/PortfolioOptimizationAdapter.ts` — L56 frontendLogger, L57 api types, L58 getCacheTTL, L60 cache types, L59 UnifiedAdapterCache
- `adapters/PortfolioSummaryAdapter.ts` — L153 frontendLogger, L155 getCacheTTL, L154 cache types, L152 UnifiedAdapterCache
- `adapters/RiskAnalysisAdapter.ts` — L110 frontendLogger, L111 cache types, L109 UnifiedAdapterCache (getCacheTTL via cacheConfig)
- `adapters/RiskScoreAdapter.ts` — L157 frontendLogger, L158 schema import, L160 getCacheTTL, L162 cache types, L161 UnifiedAdapterCache
- `adapters/RiskSettingsAdapter.ts` — L119 frontendLogger, L121 getCacheTTL, L122 cache types, L123 api types, L120 UnifiedAdapterCache
- `adapters/StockAnalysisAdapter.ts` — L55 frontendLogger, L56 api types, L57 getCacheTTL, L59 cache types, L58 UnifiedAdapterCache
- `adapters/WhatIfAnalysisAdapter.ts` — L84 frontendLogger, L86 getCacheTTL, L87 cache types, L88 api types, L85 UnifiedAdapterCache

### 1F. Feature hooks (17 files)

Nearly every feature hook imports through shims. The common patterns:

| Shim path | Replace with | Hooks using it |
|-----------|-------------|---------------|
| `../../../services/frontendLogger` | `@risk/chassis` | All 18 hooks |
| `../../../stores/portfolioStore` (useCurrentPortfolio) | `@risk/chassis` | useRiskAnalysis, usePerformance, useAnalysisReport, usePortfolioSummary, usePortfolioOptimization, useWhatIfAnalysis, useRiskScore, useRiskSettings, usePortfolioChat |
| `../../../stores/authStore` (useAuthStore, useAuthActions) | `@risk/chassis` | useAuthFlow, useSnapTrade, usePlaid, usePendingUpdates |
| `../../../config/queryConfig` (HOOK_QUERY_CONFIG) | `@risk/chassis` | useRiskAnalysis, usePerformance, useAnalysisReport, usePortfolioSummary, usePortfolioOptimization, useRiskScore, useRiskSettings, useStockAnalysis |
| `../../../queryKeys` | `@risk/chassis` | useRiskAnalysis, usePerformance, useAnalysisReport, usePortfolioSummary, usePortfolioOptimization, useRiskScore, useRiskSettings, useStockAnalysis, useWhatIfAnalysis, useSnapTrade, usePlaid, usePortfolioChat, usePendingUpdates, useConnectAccount |
| `../../../utils/AdapterRegistry` | `@risk/chassis` | useRiskAnalysis, usePerformance, useAnalysisReport, usePortfolioSummary, usePortfolioOptimization, useRiskScore, useRiskSettings, useStockAnalysis, useWhatIfAnalysis |
| `../../../utils/cacheConfig` (CACHE_CONFIG) | `@risk/chassis` | useAnalysisReport, usePortfolioChat |
| `../../../repository/PortfolioRepository` | `@risk/chassis` | useInstantAnalysis |
| `../../../config/environment` (config) | `@risk/chassis` | useSnapTrade |
| `../../../repository/PortfolioRepository` | `@risk/chassis` | useInstantAnalysis |
| `../../../types/api` (Plaid types) | `@risk/chassis` | usePlaid |
| `../../../chassis/types` (ChatMessage etc.) | `@risk/chassis` | usePortfolioChat, useInstantAnalysis |
| `../../../chassis/services/SnapTradeService` (types) | `@risk/chassis` | useSnapTrade |
| `../../../chassis/managers/AuthManager` | `../../../managers/AuthManager` (REAL connectors file) | useAuthFlow |
| `../../../chassis/services/APIService` | `@risk/chassis` | useAuthFlow |

Note: `useAuthFlow` imports `AuthManager` from `../../../chassis/managers/AuthManager`
(a proxy). After cleanup, this should import from `../../../managers/AuthManager` (the
real connectors-owned manager), NOT from `@risk/chassis`.

Keep unchanged (REAL connectors files):
- `../../../providers/SessionServicesProvider`
- `../../../stores/uiStore` (useUIActions)
- `../../../adapters/*`
- `../../../utils/sessionCleanup`
- `../../../utils/NavigationIntents`
- `../../riskScore/hooks/useRiskScore` (cross-feature)

---

## Step 2: Fix UI imports

UI files that import chassis-owned symbols from `@risk/connectors` need splitting.

**`ui/src/components/layouts/DashboardLayout.tsx`**
```
L2: import { User } from '@risk/connectors'  →  import type { User } from '@risk/chassis'
```

**`ui/src/components/dashboard/views/modern/HoldingsViewModernContainer.tsx`**
```
// Currently:
L61: import { frontendLogger,PortfolioRepository } from '@risk/chassis';  // already correct
L63-70: import { IntentRegistry, useConnectAccount, usePendingUpdates, usePlaid,
         usePortfolioStore, usePortfolioSummary, useSessionServices } from '@risk/connectors';

// usePortfolioStore is chassis-owned. Move it:
→ import { frontendLogger, PortfolioRepository, usePortfolioStore } from '@risk/chassis';
→ import { IntentRegistry, useConnectAccount, usePendingUpdates, usePlaid,
           usePortfolioSummary, useSessionServices } from '@risk/connectors';
```

**`ui/src/components/apps/ModernDashboardApp.tsx`**
```
// Currently:
L41-48: import { PortfolioInitializer, useActiveView, useCurrentPortfolio,
         usePortfolioSummary, useRiskAnalysis, useUIActions } from '@risk/connectors';
L51: import { frontendLogger } from '@risk/chassis';

// useCurrentPortfolio is chassis-owned. Move it:
→ import { frontendLogger, useCurrentPortfolio } from '@risk/chassis';
→ import { PortfolioInitializer, useActiveView,
           usePortfolioSummary, useRiskAnalysis, useUIActions } from '@risk/connectors';
```

**`ui/src/components/settings/AccountConnectionsContainer.tsx`**
```
// Currently:
L104: import { frontendLogger } from '@risk/chassis';
L105-112: import { INSTITUTION_CONFIG, ProviderRoutingService,
           useConnectAccount, useConnectSnapTrade, usePlaid, useSnapTrade } from '@risk/connectors';

// ProviderRoutingService is chassis-owned. INSTITUTION_CONFIG is connectors-owned. Move:
→ import { frontendLogger, ProviderRoutingService } from '@risk/chassis';
→ import { INSTITUTION_CONFIG, useConnectAccount, useConnectSnapTrade,
           usePlaid, useSnapTrade } from '@risk/connectors';
```

**Files already correct (no changes needed):**
- `App.tsx` — `QueryProvider, AuthProvider, teardownAuth` from `@risk/chassis`; `SessionServicesProvider, useUIStore` from `@risk/connectors` — both correct
- `AppOrchestrator.tsx` — `useAuthStore, frontendLogger` from `@risk/chassis`; `useServicesReady` from `@risk/connectors` — both correct
- `AppOrchestratorModern.tsx` — same as above, correct
- `LandingPage.tsx` — `useAuthStore, frontendLogger` from `@risk/chassis`; `useAuthFlow` from `@risk/connectors` — correct
- `InstantTryPage.tsx` — `useInstantAnalysis, useUIStore` from `@risk/connectors` — correct (both connectors-owned)

---

## Step 3: Delete shim files

After all imports are updated, delete these files:

### Services shims (19 files)
```
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
connectors/src/services/frontendLogger.ts
```

### Type/store/config/schema shims (11 files)
```
connectors/src/types/api-generated.ts
connectors/src/types/api.ts
connectors/src/types/cache.ts
connectors/src/types/index.ts
connectors/src/stores/authStore.ts
connectors/src/stores/portfolioStore.ts
connectors/src/repository/PortfolioRepository.ts
connectors/src/config/environment.ts
connectors/src/config/queryConfig.ts
connectors/src/queryKeys.ts
connectors/src/schemas/index.ts
```

### Util shims (3 files)
```
connectors/src/utils/cacheConfig.ts
connectors/src/utils/CacheDebugger.ts
connectors/src/utils/AdapterRegistry.ts
```

### Provider shim (1 file)
```
connectors/src/providers/QueryProvider.tsx
```

### Entire chassis proxy directory (~29 files)
```
connectors/src/chassis/   (rm -rf)
```

### Possibly unused navigation files (verify first)
```
connectors/src/navigation/NavigationIntents.ts   — marked "UNUSED/LEGACY" in comments
connectors/src/navigation/NavigationResolver.ts  — marked "UNUSED/LEGACY" in comments
```

**Total: ~63 files deleted**

---

## Step 4: Rewrite connectors barrel

New `connectors/src/index.ts`:

```ts
// Hooks — domain logic
export { useRiskScore } from './features/riskScore';
export { useRiskAnalysis, usePerformance, useAnalysisReport } from './features/analysis';
export { usePortfolioSummary, useInstantAnalysis, usePendingUpdates } from './features/portfolio';
export { usePortfolioOptimization } from './features/optimize';
export { useWhatIfAnalysis } from './features/whatIf';
export { useRiskSettings } from './features/riskSettings';
export { useStockAnalysis } from './features/stockAnalysis';
export { usePortfolioChat, useChat, usePlaid, useSnapTrade } from './features/external';
export { useAuthFlow, useConnectAccount, useConnectSnapTrade } from './features/auth';
export { useRiskMetrics } from './features/riskMetrics';
export { useCancelableRequest, useCancellablePolling, usePlaidPolling } from './features/utils';

// Providers — DI container
export {
  SessionServicesProvider,
  useSessionServices,
  useServicesReady,
  useAPIService,
  usePortfolioCache,
  usePortfolioManager,
} from './providers/SessionServicesProvider';
export { default as PortfolioInitializer } from './providers/PortfolioInitializer';

// UI state
export { useUIStore, useUIActions, useActiveView } from './stores/uiStore';
export { IntentRegistry } from './utils/NavigationIntents';

// Domain config
export * from './config/providers';
export * from './config/portfolio';

// Adapter types (for consumers that need the transformed data shapes)
export type { AnalysisReportData } from './adapters/AnalysisReportAdapter';
export type { PerformanceData } from './adapters/PerformanceAdapter';
export type { RiskAnalysisTransformedData } from './adapters/RiskAnalysisAdapter';
export type { PortfolioSummaryData } from './adapters/PortfolioSummaryAdapter';

// Hook return types (for TS declaration emit)
export type { UsePortfolioChatReturn } from './features/external/hooks/usePortfolioChat';
```

Note: NO `export * from '@risk/chassis'` line.

---

## Step 5: Fix remaining TS errors

1. **TS4023 `useChat`** — Fixed by exporting `UsePortfolioChatReturn` type from barrel (Step 4)
2. **TS2769/TS2322 `HoldingsViewModernContainer.tsx`** — Type narrowing fix:
   - L168: `new Date({})` → needs proper date parsing
   - L339: `name: unknown` → cast or narrow to string
3. **Any new errors** from the import migration

---

## Step 6: Verify

```bash
cd frontend
pnpm typecheck    # 0 errors
pnpm build        # succeeds
pnpm dev          # starts, renders correctly
```

---

## Execution Order

The steps above are numbered for clarity but should be executed in this order
to avoid intermediate broken states:

1. **Step 1** (update connectors imports) + **Step 2** (update UI imports) — can be done in parallel
2. **Step 4** (rewrite barrel) — remove the `export * from '@risk/chassis'` line
3. **Step 3** (delete shims) — now safe since no code references them
4. **Step 5** (fix TS errors)
5. **Step 6** (verify)

---

## Metrics

| Metric | Before | After |
|--------|--------|-------|
| Shim files in connectors | ~62 | 0 |
| Connectors barrel re-exports chassis | Yes | No |
| Files with real logic in connectors | ~35 | ~35 |
| Import rule violations | Everywhere | 0 |
| TS errors | 3 | 0 |

---

## Codex Review Log

### Review 1 — FAIL → patched

Codex verified shim classification (all correct), line numbers (managers/providers match),
and UI import splits (all 4 correct, no others missed).

**Gaps found and patched:**
1. `PortfolioInitializer.tsx` — missed L7 `PortfolioRepository` and L10 `initialPortfolioKey` shim imports
2. `sessionCleanup.ts` — missed L9 `AdapterRegistry` and L10 `resetQueryClient` shim imports
3. All 9 adapters — missed `getCacheTTL` import from `../utils/cacheConfig` shim
4. `useAuthFlow` — clarified that `AuthManager` import should point to connectors-owned
   `../../../managers/AuthManager`, not `@risk/chassis`

All gaps now addressed in plan above.

### Review 2 — PASS

Codex confirmed:
- All 36 non-shim files with shim imports are accounted for in the plan
- Patched items (PortfolioInitializer, sessionCleanup, adapter getCacheTTL, useAuthFlow) verified correct
- `schemas/api-schemas.ts` confirmed as real Zod schemas (not a shim) — rewrite is valid
- Navigation files confirmed safe to delete (no active imports)
- `schemas/index.ts` added to deletion list (safe — no active non-proxy imports)
- Minor doc fix: hook count corrected from 18 → 17

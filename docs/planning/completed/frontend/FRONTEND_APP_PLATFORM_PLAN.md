# Frontend App Platform Extraction Plan

**Goal:** Extract a clean, reusable frontend infrastructure package (`@risk/app-platform`) from `@risk/chassis`, mirroring the backend `app_platform/` extraction pattern. The new package contains only generic, domain-agnostic frontend infrastructure. The existing `@risk/chassis` becomes a thinner layer that imports from `@risk/app-platform` and adds domain-specific services/types/stores.

**Review history:** v1 FAIL (phase ordering, hidden coupling, underspecified auth). v2 FAIL (logger init timing, devtools hard import, cacheConfig domain leakage, CacheCoordinator/Warmer contradiction, workspace wiring omitted). v3 PASS (without auth). v4 adds auth store as Phase 4 with factory pattern.

---

## Current State

`@risk/chassis` is ~50% generic infra and ~50% domain-specific portfolio/risk code, all mixed together. There is no clean boundary — generic services like `EventBus` and domain services like `RiskAnalysisService` live side by side.

### File Classification

**GENERIC (extract to `@risk/app-platform`):**

| File | What it does | Coupling to remove |
|------|-------------|-------------------|
| `services/frontendLogger.ts` | Structured logger with batched backend piping, sanitization, session stats | Reads `import.meta.env.VITE_API_URL` at construction — redesign to pre-init-safe pattern |
| `services/EventBus.ts` | Pub/sub event bus with typed events | `CacheEvent` type has `portfolioId` — generalize to `scopeId` |
| `services/ServiceContainer.ts` | DI container with lazy init, lifecycle mgmt | Clean — no domain coupling |
| `services/UnifiedAdapterCache.ts` | TTL cache with metadata tagging, perf metrics | `portfolioId` in metadata — rename to `scopeId` |
| `utils/ErrorAdapter.ts` | Error → ErrorEnvelope transformation | Clean |
| `utils/formatting.ts` | Intl.NumberFormat currency/number formatting | Clean |
| `lib/utils.ts` | `cn()` — clsx + tailwind-merge | Clean |

**MIXED (extract generic core, domain wrapper stays in chassis):**

| File | Generic part | Domain coupling | Resolution |
|------|-------------|----------------|------------|
| `services/CacheMonitor.ts` | Cache perf monitoring framework | Hardcodes `risk-data-invalidated`, `portfolio-data-invalidated` event names | Extract generic monitor that accepts event names via config; chassis passes domain events |
| `utils/AdapterRegistry.ts` | Singleton registry with lifecycle | Imports `UnifiedAdapterCache` type | Move after cache extraction (Phase 2) |
| `utils/CacheDebugger.ts` | Cache inspection UI | References `UnifiedAdapterCache` | Move with cache system (Phase 2) |
| `types/cache.ts` | Cache key metadata, hash utils | `CacheKeyMetadata` has `portfolioId` field | Rename to `scopeId`, move with cache system |
| `utils/broadcastLogout.ts` | Cross-tab logout via BroadcastChannel | Clean | Move in Phase 2 |
| `providers/QueryProvider.tsx` | TanStack QueryClientProvider wrapper | Hard static import of `@tanstack/react-query-devtools` | Dynamic import behind `import.meta.env.DEV` check, or make devtools a direct dependency |
| `utils/loadRuntimeConfig.ts` | Zod-based runtime config validation | Schema hardcoded to app fields | Make schema injectable via generic |

**DOMAIN-SPECIFIC (stays in `@risk/chassis`):**

| File | Why it stays |
|------|-------------|
| `services/APIService.ts` | 1100-line god class with every API endpoint hardcoded |
| `services/AuthService.ts` | Google OAuth API calls via domain types |
| `services/PlaidService.ts` | Plaid-specific API calls |
| `services/PlaidPollingService.ts` | Plaid polling logic |
| `services/SnapTradeService.ts` | SnapTrade API calls |
| `services/RiskAnalysisService.ts` | Risk analysis API calls |
| `services/RiskManagerService.ts` | Risk settings API calls |
| `services/PortfolioCacheService.ts` | Portfolio-specific cache logic |
| `services/StockCacheService.ts` | Stock data caching |
| `services/CacheCoordinator.ts` | Domain query keys (`riskScoreKey`, etc.), `PortfolioCacheService` — fully domain-bound |
| `services/CacheWarmer.ts` | Portfolio/risk warming strategies, domain query keys — fully domain-bound |
| `services/ClaudeService.ts` | Claude AI integration |
| `services/GatewayClaudeService.ts` | Gateway SSE for Claude |
| `services/ClaudeStreamTypes.ts` | Claude stream types |
| `services/parse-ui-blocks.ts` | UI block parsing for Claude |
| `services/ProviderRoutingService.ts` | Provider routing |
| `stores/portfolioStore.ts` | Portfolio state |
| `stores/authStore.ts` | Uses `createAuthStore<User>()` from app-platform (Phase 4), but domain callbacks (`APIService`, `AdapterRegistry.clear`, logger userId) and `User` type stay |
| `types/api.ts` | Auto-generated API response types |
| `types/index.ts` | Domain type definitions |
| `catalog/types.ts` | 31 domain `DataSourceId` values — real coupling lives here |
| `catalog/descriptors.ts` | Domain descriptor definitions bound to `DataSourceId` |
| `catalog/DataCatalog.ts` | Tied to `DataSourceId`, descriptor shape (`category`, `loading.dependsOn`, `params`, `fields`, `flagTypes`) |
| `catalog/conformance.ts` | Domain conformance checks |
| `repository/PortfolioRepository.ts` | Portfolio data repository |
| `queryKeys.ts` | Domain-specific query key factories |
| `services/index.ts` | Domain service barrel export |
| `config/environment.ts` | Hardcoded `googleClientId`, `enableSnapTrade` fields |
| `errors/DataSourceError.ts` | Imports `DataSourceId` from catalog |
| `errors/classifyError.ts` | Imports `DataSourceId` from catalog |
| `providers/AuthProvider.tsx` | **Deleted in Phase 4** — replaced by `createAuthProvider<User>(useAuthStore)` in `stores/authStore.ts` |
| `utils/cacheConfig.ts` | Reads `VITE_PORTFOLIO_CACHE_TTL`, portfolio-specific messaging, domain env var name |
| `config/queryConfig.ts` | `HOOK_QUERY_CONFIG` encodes domain hook names (`useRiskScore`, `useWhatIfAnalysis`) |

---

## Target Architecture

```
frontend/packages/
├── app-platform/             # NEW — generic frontend infra
│   ├── package.json          # @risk/app-platform
│   ├── tsconfig.json
│   └── src/
│       ├── index.ts
│       ├── auth/
│       │   ├── createAuthStore.ts    # createAuthStore<TUser>(config) factory
│       │   ├── createAuthSelectors.ts # createAuthSelectors<TUser>(store) factory
│       │   └── AuthProvider.tsx      # createAuthProvider<TUser>(store) factory
│       ├── cache/
│       │   ├── UnifiedCache.ts       # Generic TTL cache (scopeId, not portfolioId)
│       │   ├── CacheMonitorBase.ts   # Generic monitor (event names injected via config)
│       │   ├── CacheDebugger.ts      # Cache inspection
│       │   └── types.ts             # CacheEntry, CacheStats, CacheKeyMetadata (scopeId)
│       ├── events/
│       │   └── EventBus.ts          # Generic EventBus<TEvent>
│       ├── http/
│       │   └── HttpClient.ts        # Generic HTTP client (request, stream, retry)
│       ├── logging/
│       │   └── Logger.ts            # FrontendLogger (pre-init-safe, lazy baseUrl)
│       ├── providers/
│       │   └── QueryProvider.tsx     # TanStack wrapper (devtools via dynamic import)
│       ├── services/
│       │   └── ServiceContainer.ts   # DI container
│       └── utils/
│           ├── AdapterRegistry.ts
│           ├── broadcastLogout.ts
│           ├── ErrorAdapter.ts
│           ├── formatting.ts
│           └── cn.ts
│
├── chassis/                   # EXISTING — thinner, domain-specific
│   └── src/
│       ├── index.ts           # Re-exports from app-platform + domain exports
│       ├── services/
│       │   ├── APIService.ts         # Domain API client (composes HttpClient)
│       │   ├── AuthService.ts, PlaidService.ts, SnapTradeService.ts, etc.
│       │   ├── PortfolioCacheService.ts
│       │   ├── CacheCoordinator.ts   # Fully domain — uses UnifiedCache + domain query keys
│       │   ├── CacheWarmer.ts        # Fully domain — uses CacheMonitorBase + domain strategies
│       │   ├── CacheMonitor.ts       # Domain wrapper — extends CacheMonitorBase, injects domain events
│       │   ├── ClaudeService.ts, GatewayClaudeService.ts, etc.
│       │   └── index.ts
│       ├── stores/
│       │   ├── authStore.ts          # createAuthStore<User>(...) with domain callbacks
│       │   └── portfolioStore.ts
│       ├── types/, catalog/, repository/, providers/
│       ├── config/
│       │   ├── environment.ts        # Domain env config
│       │   └── queryConfig.ts        # Domain hook TTL map
│       ├── utils/
│       │   └── cacheConfig.ts        # Domain cache TTL (VITE_PORTFOLIO_CACHE_TTL)
│       ├── errors/                   # Stays — DataSourceId dependency
│       └── queryKeys.ts
│
├── connectors/                # UNCHANGED — imports from chassis (which re-exports app-platform)
└── ui/                        # UNCHANGED — imports from chassis
```

---

## Implementation Phases

### Phase 1: Scaffold + Logger
**Scope:** Create the package with workspace wiring. Extract the logger first — everything else depends on it.

**1a. Package scaffold:**
1. Create `frontend/packages/app-platform/` directory
2. `package.json` — note: this workspace consumes source directly via TS path aliases, so packages that import `@tanstack/react-query` must declare it in `dependencies` (matching chassis pattern), not just `peerDependencies`:
   ```json
   {
     "name": "@risk/app-platform",
     "private": true,
     "version": "0.1.0",
     "main": "src/index.ts",
     "peerDependencies": {
       "react": "^19.1.0"
     },
     "dependencies": {
       "@tanstack/react-query": "^5.83.0",
       "clsx": "^2.1.1",
       "tailwind-merge": "^3.3.1",
       "zod": "^4.0.10",
       "zustand": "^4.5.0"
     },
     "devDependencies": {
       "@tanstack/react-query-devtools": "^5.83.0"
     }
   }
   ```
3. `tsconfig.json` — must match existing package shape for `tsc -b` composite builds:
   ```json
   {
     "extends": "../../tsconfig.base.json",
     "compilerOptions": {
       "rootDir": "src",
       "composite": true,
       "emitDeclarationOnly": true,
       "declarationDir": "dist",
       "tsBuildInfoFile": "dist/tsconfig.tsbuildinfo"
     },
     "include": ["src"]
   }
   ```
4. Workspace wiring:
   - Add `"@risk/app-platform": ["packages/app-platform/src/index.ts"]` to `frontend/tsconfig.base.json` `paths`
   - Add `{ "path": "./packages/app-platform" }` to `frontend/tsconfig.json` `references`
   - Add `"@risk/app-platform": "workspace:*"` to `chassis/package.json` `dependencies`
   - Add `{ "path": "../app-platform" }` to `chassis/tsconfig.json` `references` (required for `tsc -b` to resolve the cross-package dependency)
   - Verify `tsc -b` passes from `frontend/` root

**1b. Logger extraction — pre-init-safe design:**

The current logger does real work in its constructor (installs timers, reads `import.meta.env.VITE_API_URL`, logs session start). This means any module that imports `frontendLogger` triggers side effects at import time. The extraction must handle this.

Design: **Lazy initialization with safe pre-init buffering.**

```typescript
// app-platform/src/logging/Logger.ts
class FrontendLogger {
  private baseUrl = '';  // Empty until init()
  private initialized = false;
  private preInitBuffer: LogPayload[] = [];

  /**
   * Must be called once at app startup before backend logging works.
   * Pre-init logs are buffered and flushed on init().
   * Console logging works immediately (no baseUrl needed).
   */
  init(config: { baseUrl: string }): void {
    this.baseUrl = config.baseUrl;
    this.initialized = true;
    this.flushPreInitBuffer();
    this.startSessionTimers();  // Moved from constructor
  }

  private queueLog(payload: LogPayload): void {
    if (!this.initialized) {
      // Buffer for later — console logging still works
      this.preInitBuffer.push(payload);
      return;
    }
    // ... normal queue + send logic
  }
  // ... rest unchanged
}

export const frontendLogger = new FrontendLogger();
```

Key changes from current:
- Constructor is side-effect-free (no timers, no env reads, no session start log)
- Console logging works immediately (doesn't need `baseUrl`)
- Backend log shipping starts only after `init()` — pre-init logs are buffered and flushed
- `import.meta.env.MODE` / `.PROD` checks remain (standard Vite, used for console vs production behavior)
- `import.meta.env.VITE_API_URL` removed — comes via `init({ baseUrl })`

Chassis re-export:
```typescript
// chassis/src/services/frontendLogger.ts
export { frontendLogger, log, type LogLevel, type LogCategory } from '@risk/app-platform';
```

**Critical:** This re-exports the exact same object reference. No new instance.

App startup (in `App.tsx` or similar):
```typescript
import { frontendLogger } from '@risk/chassis';
import { config } from '@risk/chassis';
frontendLogger.init({ baseUrl: config.apiBaseUrl });
```

**1c. Tests + Gate:**
- 5+ isolated `app-platform` unit tests: Logger init, pre-init buffering, log levels, sanitization, session stats
- Full existing test suite passes
- `app-platform` builds independently

### Phase 2: EventBus + Cache + Utilities
**Scope:** Extract the interconnected eventing and caching layer, plus clean utilities.

1. **EventBus** → `events/EventBus.ts`:
   - Generalize `CacheEvent`: rename `portfolioId` → `scopeId`
   - Export generic `EventBus<TEvent>` class
   - Chassis creates domain type alias mapping `portfolioId` → `scopeId` at boundary

2. **UnifiedCache** → `cache/UnifiedCache.ts` (renamed from UnifiedAdapterCache):
   - Replace `portfolioId` → `scopeId` in `CacheEntry` and all methods
   - `clearByType(type, scopeId?)`, `clearScope(scopeId)` instead of `clearPortfolio()`

3. **CacheMonitorBase** → `cache/CacheMonitorBase.ts`:
   - Constructor accepts `{ eventNames: string[] }` — no hardcoded event names
   - Chassis `CacheMonitor` instantiates with `['risk-data-invalidated', 'portfolio-data-invalidated']`

4. **Cache types** → `cache/types.ts`:
   - `CacheKeyMetadata` uses `scopeId` instead of `portfolioId`
   - `CacheEntry`, `CacheStats`, `CachePerformanceMetrics` — all generic

5. **CacheDebugger** → `cache/CacheDebugger.ts` (depends on UnifiedCache — now co-located)

6. **Clean utilities** (zero changes needed):
   - `ServiceContainer.ts` → `services/ServiceContainer.ts`
   - `formatting.ts` → `utils/formatting.ts`
   - `ErrorAdapter.ts` → `utils/ErrorAdapter.ts`
   - `cn` (from `lib/utils.ts`) → `utils/cn.ts`
   - `broadcastLogout.ts` → `utils/broadcastLogout.ts`

7. **AdapterRegistry** → `utils/AdapterRegistry.ts` (depends on UnifiedCache type — now available)

8. Chassis re-export shims for all moved modules

9. **Tests:**
   - EventBus: pub/sub, cleanup, listener count
   - UnifiedCache: get/set, TTL expiry, clearByType, clearScope, perf metrics
   - CacheMonitorBase: metric recording with injected event names
   - ServiceContainer: register, get, lifecycle
   - AdapterRegistry: register, delete, clear

10. **Gate:** `app-platform` builds independently with 15+ tests, chassis builds with re-exports, all existing tests pass

### Phase 3: HTTP Client + QueryProvider
**Scope:** Extract generic HTTP transport and React Query provider.

1. **HttpClient** → `http/HttpClient.ts`:
   - Extract from `APIService.request()`, `requestStream()`, `fetchWithRetry()`
   - Constructor: `new HttpClient({ baseURL, getToken?, logger? })`
   - Methods:
     - `request<T>(endpoint, options?)` — JSON request/response
     - `requestStream(endpoint, options?)` — returns raw `Response` for SSE
   - Internal: `fetchWithRetry(url, options, retries)` — retry with exponential backoff
   - Auth header injection (`Authorization: Bearer`), CSRF header (`X-Requested-With`), `credentials: 'include'`
   - **Drop the broken dedup** — current key uses `Date.now()` so it never deduplicates. Clean break.
   - Accept optional `logger: FrontendLogger` for request/response/error/waterfall logging

2. **Refactor APIService** to compose HttpClient:
   ```typescript
   class APIService {
     private http: HttpClient;
     constructor(baseURL?, getToken?) {
       this.http = new HttpClient({ baseURL, getToken, logger: frontendLogger });
     }
     async analyzePortfolio(id: string, opts?) {
       return this.http.request<AnalyzeApiResponse>('/api/analyze', {
         method: 'POST', body: JSON.stringify({ portfolio_name: id, ...opts })
       });
     }
     // ... 50+ domain methods unchanged, just delegate to this.http
   }
   ```

3. **QueryProvider** → `providers/QueryProvider.tsx`:
   - Fix devtools import — the current hard static `import` means the dep must resolve at build time even if tree-shaken. Since this workspace consumes package source directly (TS path aliases, `main: "src/index.ts"`), a dynamic `import()` still needs to resolve during the Vite build.
   - **Simplest solution:** Make `@tanstack/react-query-devtools` a direct `devDependencies` of `@risk/app-platform` (not optional peer). It's already installed at the workspace root, so this is just declaration — no new install. The Vite build tree-shakes it out of production bundles via the `import.meta.env.DEV` guard.
   - Still use dynamic import for cleanliness:
     ```typescript
     const LazyDevtools = React.lazy(() =>
       import('@tanstack/react-query-devtools').then(m => ({ default: m.ReactQueryDevtools }))
     );
     // In render:
     {import.meta.env.DEV && (
       <React.Suspense fallback={null}>
         <LazyDevtools initialIsOpen={false} />
       </React.Suspense>
     )}
     ```
   - **Cache config injection:** Current `QueryProvider` imports `CACHE_CONFIG` (staleTime, gcTime) from `cacheConfig.ts`, which stays in chassis (domain env var `VITE_PORTFOLIO_CACHE_TTL`). The `resetQueryClient()` function also recreates the client (called on logout from `connectors/sessionCleanup.ts`), so the injected config must persist across resets.

     Solution: **`initQueryConfig()` + lazy client creation.** App-platform stores the config at module level. The initial `queryClient` singleton is created lazily (on first access or when `QueryProvider` mounts), NOT at module import time. This ensures `initQueryConfig()` runs before the first client is created.
     ```typescript
     // app-platform/src/providers/QueryProvider.tsx

     // Module-level config — set once via initQueryConfig(), persists across resets
     let _queryConfig = { staleTime: 5 * 60 * 1000, gcTime: 10 * 60 * 1000 };

     /** Call once at app startup to inject domain-specific cache timings.
      *  Must be called before QueryProvider renders or getQueryClient() is accessed. */
     export function initQueryConfig(config: { staleTime: number; gcTime: number }): void {
       _queryConfig = config;
       // If a client already exists (shouldn't, but safety), recreate with new config
       if (_queryClient) {
         _queryClient = createQueryClient();
       }
     }

     function createQueryClient(): QueryClient {
       return new QueryClient({
         defaultOptions: {
           queries: {
             staleTime: _queryConfig.staleTime,
             gcTime: _queryConfig.gcTime,
             retry: (failureCount, error) => { ... },
             refetchOnWindowFocus: false,
             refetchOnMount: true,
             refetchOnReconnect: true,
           },
           mutations: { retry: false },
         },
       });
     }

     // LAZY singleton — NOT created at module import time
     let _queryClient: QueryClient | null = null;

     /** Get the singleton QueryClient, creating it lazily on first access */
     export function getQueryClient(): QueryClient {
       if (!_queryClient) {
         _queryClient = createQueryClient();
       }
       return _queryClient;
     }

     // For backward compat: `queryClient` getter (not a const created at import time)
     export const queryClient = { get current() { return getQueryClient(); } };

     // resetQueryClient() recreates using current _queryConfig
     export function resetQueryClient(): void {
       _queryClient = createQueryClient();
       // ... notify component via registered reset callback
     }
     ```
     **Key change from current code:** The current `let queryClient = createQueryClient()` at module level ([QueryProvider.tsx:225](frontend/packages/chassis/src/providers/QueryProvider.tsx#L225)) is replaced with lazy creation via `getQueryClient()`. This ensures `initQueryConfig()` runs first.
     Chassis initializes at startup:
     ```typescript
     // chassis app startup (e.g., main.tsx or App.tsx)
     import { initQueryConfig } from '@risk/app-platform';
     import { CACHE_CONFIG } from './utils/cacheConfig';
     initQueryConfig({ staleTime: CACHE_CONFIG.STALE_TIME, gcTime: CACHE_CONFIG.GC_TIME });
     ```
     Chassis re-exports `QueryProvider`, `queryClient`, `resetQueryClient`, `getQueryClient` from app-platform — all use the same `_queryConfig` so resets preserve domain timings.

4. **Tests:**
   - HttpClient: request with auth header, retry on 500, no retry on 4xx, stream response, CSRF header
   - QueryProvider: renders children, creates QueryClient with defaults

5. **Gate:** `app-platform` builds independently, all API-calling tests pass, no behavior change (except dropped fake dedup)

### Phase 4: Auth Store
**Scope:** Extract generic auth state management with factory pattern.

The auth store is the most complex extraction — it has side effects (logger userId, AdapterRegistry.clear), cross-tab sync, selector helpers, and a session cleanup callback. The factory pattern handles all of these via injected callbacks.

**Important:** Zustand version must be `^4.5.0` to match chassis and connectors. The return type of `createWithEqualityFn` is `UseBoundStoreWithEqualityFn`, not `UseBoundStore<StoreApi<...>>`. We define a local type alias `AuthStoreHook<TUser>` to abstract this.

1. **`createAuthStore<TUser>()`** → `auth/createAuthStore.ts`:
   ```typescript
   // app-platform/src/auth/createAuthStore.ts
   import { createWithEqualityFn } from 'zustand/traditional';
   import type { UseBoundStoreWithEqualityFn } from 'zustand/traditional';
   import type { StoreApi } from 'zustand';
   import { devtools } from 'zustand/middleware';
   import { broadcastLogout, logoutBroadcaster } from '../utils/broadcastLogout';
   import type { FrontendLogger } from '../logging/Logger';

   interface AuthStoreConfig<TUser> {
     /** Map raw API user object to typed TUser */
     mapUser: (raw: unknown) => TUser;
     /** Check for existing session (e.g., cookie-based) */
     checkAuthStatus: () => Promise<{ authenticated: boolean; user: unknown }>;
     /** Side effects on sign-in (e.g., logger.setUserId, analytics) */
     onSignIn?: (user: TUser) => void;
     /** Domain cleanup on logout (e.g., logger.clearUserId, registry.clear).
      *  Called from signOut() and handleCrossTabLogout() — NOT from clear().
      *  clear() is raw state reset only. Must be idempotent (safe to call
      *  if already cleaned up, since dual-channel guard may skip second call). */
     onSignOut?: () => void;
     /** Additional side effects specific to cross-tab logout (e.g., session cleanup
      *  that should only run on cross-tab events, not on direct signOut).
      *  Called AFTER onSignOut. */
     onCrossTabLogout?: () => void;
     /** Side effects when initializeAuth finds no active session (e.g., clear stale adapters) */
     onUnauthInit?: () => void;
     /** Logger instance for auth flow logging */
     logger?: FrontendLogger;
   }

   interface AuthState<TUser> {
     user: TUser | null;
     token: string | null;
     isAuthenticated: boolean;
     isLoading: boolean;
     error: string | null;
     isInitialized: boolean;
     signIn: (user: TUser, token: string) => void;
     signOut: () => void;
     setUser: (user: TUser | null) => void;
     setToken: (token: string | null) => void;
     setLoading: (loading: boolean) => void;
     setError: (error: string | null) => void;
     clearError: () => void;
     clear: () => void;
     initializeAuth: () => Promise<void>;
     setupCrossTabSync: () => void;
     teardownCrossTabSync: () => void;
     handleCrossTabLogout: () => void;
     isSignedIn: () => boolean;
   }

   /** Public type alias for the store hook returned by createAuthStore */
   type AuthStoreHook<TUser> = UseBoundStoreWithEqualityFn<StoreApi<AuthState<TUser>>>;

   function createAuthStore<TUser>(config: AuthStoreConfig<TUser>): AuthStoreHook<TUser> {
     // Module-level cross-tab sync state (scoped per store instance via closure)
     let storageHandler: ((e: StorageEvent) => void) | null = null;
     let broadcastCleanup: (() => void) | null = null;
     let isListenerSetup = false;

     return createWithEqualityFn<AuthState<TUser>>()(
       devtools((set, get) => ({
         // Initial state
         user: null,
         token: null,
         isAuthenticated: false,
         isLoading: false,
         error: null,
         isInitialized: false,

         signIn: (user, token) => {
           config.onSignIn?.(user);
           set({ user, token, isAuthenticated: true, error: null, isInitialized: true });
         },

         signOut: () => {
           config.logger?.logAdapter?.('authStore', 'signOut');
           broadcastLogout();
           config.onSignOut?.();
           get().clear();
         },

         // clear() is the raw state reset — clears localStorage + Zustand state.
         // Does NOT call onSignOut (callers do that explicitly to avoid
         // double-invocation when signOut → clear).
         clear: () => {
           if (typeof localStorage !== 'undefined') {
             localStorage.removeItem('auth_token');
           }
           set({
             user: null, token: null, isAuthenticated: false,
             error: null, isInitialized: true, isLoading: false,
           });
         },

         handleCrossTabLogout: () => {
           // Guard: if already logged out, skip. This prevents double-fire
           // when signOut() triggers both BroadcastChannel and localStorage
           // events — listening tabs receive two cross-tab signals but only
           // process the first.
           if (!get().isAuthenticated && get().isInitialized) return;

           config.logger?.logAdapter?.('authStore', 'Processing cross-tab logout');
           // Same domain cleanup as signOut (logger userId, AdapterRegistry)
           config.onSignOut?.();
           // Additional cross-tab-specific cleanup (session cleanup callback)
           config.onCrossTabLogout?.();
           // Reset state locally (no broadcast — avoids loops)
           get().clear();
         },

         initializeAuth: async () => {
           const state = get();
           if (state.isInitialized) return;
           set({ isLoading: true, error: null });
           try {
             const response = await config.checkAuthStatus();
             if (response.authenticated && response.user) {
               const user = config.mapUser(response.user);
               config.onSignIn?.(user);
               set({ user, isAuthenticated: true, isInitialized: true, isLoading: false, error: null });
             } else {
               // Unauthenticated init — call onUnauthInit for domain cleanup
               // (e.g., clear stale AdapterRegistry from previous session)
               config.onUnauthInit?.();
               set({ user: null, isAuthenticated: false, isInitialized: true, isLoading: false, error: null });
             }
           } catch (error) {
             config.logger?.logError?.('authStore', 'Auth initialization failed', error);
             set({
               user: null, isAuthenticated: false, isInitialized: true, isLoading: false,
               error: error instanceof Error ? error.message : 'Authentication check failed',
             });
           }
         },

         setupCrossTabSync: () => {
           if (typeof window === 'undefined' || isListenerSetup) return;
           storageHandler = (e: StorageEvent) => {
             if (e.key === 'auth_token' && e.newValue === null) {
               get().handleCrossTabLogout();
             }
           };
           broadcastCleanup = logoutBroadcaster.onLogoutBroadcast(() => {
             get().handleCrossTabLogout();
           });
           window.addEventListener('storage', storageHandler);
           isListenerSetup = true;
         },

         teardownCrossTabSync: () => {
           if (typeof window === 'undefined' || !isListenerSetup) return;
           if (storageHandler) { window.removeEventListener('storage', storageHandler); storageHandler = null; }
           if (broadcastCleanup) { broadcastCleanup(); broadcastCleanup = null; }
           isListenerSetup = false;
         },

         setUser: (user) => set({ user, isAuthenticated: !!user }),
         setToken: (token) => set({ token }),
         setLoading: (isLoading) => set({ isLoading }),
         setError: (error) => set({ error }),
         clearError: () => set({ error: null }),
         isSignedIn: () => get().isAuthenticated && !!get().user,
       }), { name: 'auth-store' })
     );
   }
   ```

   **Key design points:**
   - Returns `AuthStoreHook<TUser>` — type alias for `UseBoundStoreWithEqualityFn<StoreApi<AuthState<TUser>>>`, matching the Zustand 4.x `createWithEqualityFn` return type. Supports both `useStore(selector)` and `useStore.getState()`.
   - **Consistent cleanup across all logout paths**: Both `signOut()` and `handleCrossTabLogout()` call `config.onSignOut?.()` explicitly, then `clear()` for raw state reset. `clear()` itself does NOT call `onSignOut` — this prevents double-invocation in the `signOut → clear` chain.
   - `onCrossTabLogout` is for **additional** cross-tab-specific effects (session cleanup callback) — runs after `onSignOut`, before `clear()`.
   - `onUnauthInit` callback handles the unauthenticated-init cleanup path (current code clears `AdapterRegistry` when `initializeAuth` finds no session).
   - Cross-tab sync state (`storageHandler`, `broadcastCleanup`, `isListenerSetup`) is closure-scoped per store instance — no module-level globals.
   - Uses `broadcastLogout` + `logoutBroadcaster` from app-platform (already extracted in Phase 2).
   - Logger is optional — passed via config, not hardcoded import.
   - Zustand `^4.5.0` — matches chassis and connectors. No version bump needed.

2. **Selector helper factory** → `auth/createAuthSelectors.ts`:
   ```typescript
   import { shallow } from 'zustand/shallow';
   import type { AuthState, AuthStoreHook } from './createAuthStore';

   function createAuthSelectors<TUser>(useStore: AuthStoreHook<TUser>) {
     return {
       useUser: () => useStore((s) => s.user),
       useAuthStatus: () => useStore((s) => ({
         isAuthenticated: s.isAuthenticated,
         isLoading: s.isLoading,
         error: s.error,
       }), shallow),
       useAuthActions: () => useStore((s) => ({
         signIn: s.signIn,
         signOut: s.signOut,
         setUser: s.setUser,
         setLoading: s.setLoading,
         setError: s.setError,
         clearError: s.clearError,
         initializeAuth: s.initializeAuth,
         setupCrossTabSync: s.setupCrossTabSync,
         teardownCrossTabSync: s.teardownCrossTabSync,
       }), shallow),
     };
   }
   ```

3. **`createAuthProvider`** → `auth/AuthProvider.tsx`:

   This factory creates a component that owns the **full auth lifecycle**: initialization AND cross-tab sync setup/teardown. This is the single owner of auth lifecycle wiring — chassis does not need a separate wrapper.

   ```typescript
   import { useEffect, type ReactNode } from 'react';
   import type { AuthStoreHook } from './createAuthStore';

   function createAuthProvider<TUser>(useStore: AuthStoreHook<TUser>) {
     return ({ children }: { children: ReactNode }) => {
       const isInitialized = useStore((s) => s.isInitialized);
       const isLoading = useStore((s) => s.isLoading);
       const initializeAuth = useStore((s) => s.initializeAuth);
       const setupCrossTabSync = useStore((s) => s.setupCrossTabSync);
       const teardownCrossTabSync = useStore((s) => s.teardownCrossTabSync);

       // Setup cross-tab sync on mount, teardown on unmount
       useEffect(() => {
         setupCrossTabSync();
         return () => teardownCrossTabSync();
       }, [setupCrossTabSync, teardownCrossTabSync]);

       // Initialize auth (check existing session)
       useEffect(() => {
         if (!isInitialized && !isLoading) initializeAuth();
       }, [initializeAuth, isInitialized, isLoading]);

       if (!isInitialized) {
         return <div className="auth-initializing">
           <div className="loading-spinner">Checking authentication...</div>
         </div>;
       }
       return <>{children}</>;
     };
   }
   ```

   **Lifecycle ownership:** The component returned by `createAuthProvider` is the single owner of both `initializeAuth()` and `setupCrossTabSync()`/`teardownCrossTabSync()`. Chassis deletes its existing `providers/AuthProvider.tsx` and replaces it with the factory-created one. The exported `initializeAuth`/`teardownAuth` functions in `authStore.ts` remain for imperative use (tests, non-React contexts) but the provider handles the normal app lifecycle.

4. **Chassis `authStore.ts`** becomes:
   ```typescript
   import { createAuthStore, createAuthSelectors, createAuthProvider } from '@risk/app-platform';
   import { frontendLogger } from '@risk/app-platform';
   import { AdapterRegistry } from '@risk/app-platform';
   import { APIService } from '../services/APIService';
   import type { User } from '../types';

   const mapAuthUser = (raw: unknown): User => { /* existing mapping logic — unchanged */ };
   const authAPIService = new APIService();

   // Module-level session cleanup callback (set by connectors via registerSessionCleanup)
   let onSessionCleanup: (() => void) | null = null;

   export const useAuthStore = createAuthStore<User>({
     mapUser: mapAuthUser,
     checkAuthStatus: () => authAPIService.checkAuthStatus(),
     onSignIn: (user) => {
       frontendLogger.setUserId(user.id);
       frontendLogger.adapter.transformSuccess('authStore', { userId: user.id });
     },
     onSignOut: () => {
       frontendLogger.clearUserId();
       AdapterRegistry.clear();
     },
     onCrossTabLogout: () => {
       // Additional cross-tab-specific cleanup (runs AFTER onSignOut)
       if (onSessionCleanup) {
         try { onSessionCleanup(); }
         catch (e) { frontendLogger.logError('authStore', 'Session cleanup failed', e); }
       }
     },
     onUnauthInit: () => {
       // Clear stale adapters when no active session found
       AdapterRegistry.clear();
       frontendLogger.logAdapter('authStore', 'Cleared stale adapters due to unauthenticated state');
     },
     logger: frontendLogger,
   });

   // Re-export selector helpers with same API as before
   const selectors = createAuthSelectors<User>(useAuthStore);
   export const useUser = selectors.useUser;
   export const useAuthStatus = selectors.useAuthStatus;
   export const useAuthActions = selectors.useAuthActions;

   // Imperative lifecycle functions (for tests, non-React contexts)
   export const initializeAuth = async (): Promise<void> => {
     const store = useAuthStore.getState();
     store.setupCrossTabSync();
     await store.initializeAuth();
   };
   export const teardownAuth = (): void => {
     useAuthStore.getState().teardownCrossTabSync();
   };

   // Session cleanup registration (connectors layer registers without circular dep)
   export const registerSessionCleanup = (cleanupFn: (() => void) | null): void => {
     onSessionCleanup = cleanupFn;
   };

   // AuthProvider — factory-created, replaces chassis/providers/AuthProvider.tsx
   export const AuthProvider = createAuthProvider<User>(useAuthStore);
   ```

   **Migration notes:**
   - Delete `chassis/src/providers/AuthProvider.tsx` — replaced by factory-created `AuthProvider` exported from `stores/authStore.ts`.
   - Delete `ui/src/components/AuthInitializer.tsx` — its functionality (init gate + loading state) is now handled by `createAuthProvider`. The factory-created provider also owns cross-tab sync lifecycle, which `AuthInitializer` did not handle.
   - Update `chassis/src/index.ts` barrel to export `AuthProvider` from `stores/authStore` instead of `providers/AuthProvider`. Downstream import path (`import { AuthProvider } from '@risk/chassis'`) is unchanged.
   - **Remove `teardownAuth()` effect from `ui/src/App.tsx`** (line ~142): The current `App.tsx` only calls `teardownAuth()` on unmount — auth init is delegated to `AuthInitializer`/`AuthProvider`. With the new factory-created `AuthProvider` owning both setup and teardown via `useEffect`, the `App.tsx` unmount cleanup is no longer needed. Remove the `teardownAuth` import and the `useEffect` that calls it.
   - The imperative `initializeAuth`/`teardownAuth` exports remain available for tests and non-React contexts only — NOT used by the normal app lifecycle.

5. **Tests:**
   - `createAuthStore`: sign-in/out state transitions, `onSignIn`/`onSignOut` callbacks invoked, `initializeAuth` with mock API (authenticated path), `initializeAuth` with unauthenticated response → `onUnauthInit` called
   - `createAuthStore` cleanup consistency: `signOut()` calls `onSignOut` then `clear()`, `handleCrossTabLogout()` calls `onSignOut` + `onCrossTabLogout` then `clear()`, `clear()` does NOT call `onSignOut` (no double-invocation)
   - `createAuthStore` `.getState()` contract: verify `useStore.getState()` returns state object with all actions (used by `sessionCleanup.ts` and imperative `initializeAuth`)
   - `createAuthSelectors`: selector hooks return correct slices, shallow equality prevents unnecessary re-renders
   - `createAuthProvider`: renders children after init, shows loading before init, calls `setupCrossTabSync` on mount, calls `teardownCrossTabSync` on unmount
   - Cross-tab: storage event with `auth_token=null` triggers `handleCrossTabLogout`, `broadcastLogout` triggers handler via `logoutBroadcaster`
   - Cross-tab dual-channel guard: fire both storage event AND BroadcastChannel message → `onSignOut` and `onCrossTabLogout` each called exactly once (second signal is no-op because `isAuthenticated` is already false)
   - Chassis wiring: `AuthProvider` export from chassis barrel resolves to factory-created component (not old `providers/AuthProvider.tsx`)

6. **Gate:** Auth flow works end-to-end, cross-tab sync lifecycle (setup on mount, teardown on unmount), all selector hooks return same types, `connectors/sessionCleanup.ts` `.getState()` calls work, `onSignOut` fires on every logout path

### Phase 5: loadRuntimeConfig + Final Cleanup
**Scope:** Extract remaining generic utility, finalize package.

1. **loadRuntimeConfig** → `config/loadRuntimeConfig.ts`:
   - Make schema injectable: `createRuntimeConfigLoader<T>(schema: ZodType<T>)`
   - Chassis calls: `const loadRuntimeConfig = createRuntimeConfigLoader(appConfigSchema)`

2. Final barrel exports in `app-platform/src/index.ts`:
   ```typescript
   // Logging
   export { frontendLogger, log, type LogLevel, type LogCategory } from './logging/Logger';

   // Events
   export { EventBus, type CacheEvent, type EventHandler } from './events/EventBus';

   // Cache
   export { UnifiedCache, type CacheEntry, type CacheStats } from './cache/UnifiedCache';
   export { CacheMonitorBase } from './cache/CacheMonitorBase';
   export { CacheDebugger } from './cache/CacheDebugger';
   export * from './cache/types';

   // HTTP
   export { HttpClient } from './http/HttpClient';

   // Auth
   export { createAuthStore, type AuthStoreConfig, type AuthState, type AuthStoreHook } from './auth/createAuthStore';
   export { createAuthSelectors } from './auth/createAuthSelectors';
   export { createAuthProvider } from './auth/AuthProvider';

   // Providers
   export { QueryProvider, queryClient, resetQueryClient, getQueryClient, initQueryConfig } from './providers/QueryProvider';

   // Services
   export { ServiceContainer } from './services/ServiceContainer';

   // Utils
   export { AdapterRegistry } from './utils/AdapterRegistry';
   export { broadcastLogout, logoutBroadcaster } from './utils/broadcastLogout';
   export { ErrorAdapter } from './utils/ErrorAdapter';
   export * from './utils/formatting';
   export { cn } from './utils/cn';

   // Config
   export { createRuntimeConfigLoader } from './config/loadRuntimeConfig';
   ```

3. Verify all chassis re-export shims are working and complete

4. Write package-level integration test: full import of `@risk/app-platform`, verify no domain types leak, verify singleton logger identity

5. **Gate:** `app-platform` builds independently with full test suite (25+ tests), chassis builds, `connectors`/`ui` build, all existing tests pass

---

## What's Deferred (Future Work)

These were considered but deferred — too complex or too low-value for v1:

| Module | Why deferred |
|--------|-------------|
| `catalog/DataCatalog.ts` | Generic `Catalog<Id>` is insufficient — descriptor shape (`category`, `loading.dependsOn`, `params`, `fields`, `flagTypes`) is deeply coupled. Real coupling lives in `catalog/types.ts` (31 `DataSourceId` values) and `catalog/descriptors.ts` (bound to those IDs). |
| `catalog/types.ts`, `catalog/descriptors.ts` | Domain types that define the catalog schema — can't extract without `DataCatalog` |
| `config/environment.ts` | Domain fields (`googleClientId`, `enableSnapTrade`) baked in. Only 58 lines — low value. |
| `errors/DataSourceError.ts`, `errors/classifyError.ts` | Import `DataSourceId` from catalog. Can't extract until catalog is genericized. |
| `utils/cacheConfig.ts` | Reads `VITE_PORTFOLIO_CACHE_TTL`, has portfolio-specific messaging. Domain-specific env var. |
| `config/queryConfig.ts` | `HOOK_QUERY_CONFIG` encodes domain hook names. Generic TTL multiplier math is trivial. |
| `services/CacheCoordinator.ts` | Deeply tied to domain query keys (`riskScoreKey`, etc.) and `PortfolioCacheService`. |
| `services/CacheWarmer.ts` | Portfolio/risk warming strategies, domain-specific cache keys and warming logic. |

---

## Key Design Decisions

### 1. Pre-init-safe logger (not just lazy `init()`)
The logger constructor must be side-effect-free because module import order is unpredictable. Console logging works immediately; backend log shipping starts only after `init()`. Pre-init logs are buffered and flushed. This prevents the eager-import problem where `QueryProvider` → `CACHE_CONFIG` → `frontendLogger` triggers side effects before the app calls `init()`.

### 2. Chassis re-exports are permanent
Downstream packages (`connectors`, `ui`) always import from `@risk/chassis` — they never need to know about `@risk/app-platform`. Re-exports are a permanent compatibility layer, not temporary shims to be removed.

### 3. `scopeId` instead of `portfolioId`
Cache metadata uses generic `scopeId`. Chassis maps `portfolioId` → `scopeId` at the boundary. This is the one naming change that flows through the cache system.

### 4. HttpClient as a standalone class — with cleanup
Rather than making `APIService` generic, we extract just the HTTP transport. The current fake dedup (`Date.now()` key) is dropped — it never worked. `APIService` remains domain-specific and composes `HttpClient`.

### 5. CacheCoordinator and CacheWarmer stay fully in chassis
No abstract base classes or generic coordinator interfaces. These are deeply domain-coupled and the abstraction would be forced. They consume the generic primitives (`UnifiedCache`, `EventBus`, `CacheMonitorBase`) directly.

### 6. QueryProvider devtools via dynamic import
The current hard static `import { ReactQueryDevtools }` breaks if declared as optional peer. Use `React.lazy()` + dynamic `import()` so the dep is truly optional at runtime.

### 7. Isolated package tests at every phase
Following the backend `app_platform` extraction pattern: each phase adds standalone tests in `app-platform` that verify the extracted module works independently. Not just "existing tests still pass."

---

## Dependency Graph (Target)

```
@risk/ui ──────────┐
                    ├──→ @risk/chassis ──→ @risk/app-platform
@risk/connectors ──┘

@risk/app-platform has ZERO imports from chassis, connectors, or ui.
```

External dependencies for `@risk/app-platform`:
- `react` (peer)
- `@tanstack/react-query` (direct dependency — workspace consumes source, must resolve at build time)
- `@tanstack/react-query-devtools` (devDependency — tree-shaken in prod via `import.meta.env.DEV` guard)
- `clsx` + `tailwind-merge` (direct)
- `zod` (direct — for createRuntimeConfigLoader)
- `zustand` `^4.5.0` (direct — for createAuthStore factory in Phase 4, matching chassis/connectors version)

Note: `zustand` is a direct dependency of app-platform (needed for `createAuthStore` in Phase 4).

---

## Workspace Wiring Checklist

When creating `@risk/app-platform`, these files must be updated:

| File | Change |
|------|--------|
| `frontend/tsconfig.base.json` | Add `"@risk/app-platform": ["packages/app-platform/src/index.ts"]` to `paths` |
| `frontend/tsconfig.json` | Add `{ "path": "./packages/app-platform" }` to `references` |
| `frontend/packages/chassis/package.json` | Add `"@risk/app-platform": "workspace:*"` to `dependencies` |
| `frontend/packages/chassis/tsconfig.json` | Add `{ "path": "../app-platform" }` to `references` array (required for `tsc -b` to resolve the dependency) |
| `frontend/packages/app-platform/tsconfig.json` | Create with `composite: true`, `emitDeclarationOnly: true`, `declarationDir: "dist"`, `tsBuildInfoFile: "dist/tsconfig.tsbuildinfo"` (matching chassis/connectors/ui shape for `tsc -b`) |
| `frontend/packages/app-platform/package.json` | Create with deps and devDependencies listed above |
| **Verification** | `cd frontend && tsc -b` must pass after scaffold |

---

## Risk Mitigations

| Risk | Mitigation |
|------|-----------|
| Logger singleton duplication | Pre-init-safe design: constructor is side-effect-free. Chassis re-exports exact object reference. Verified by test (same `===` identity). |
| Eager module imports trigger logger before `init()` | Pre-init buffer: logs queue to memory, flush on `init()`. Console logging works immediately. |
| `import.meta.env` in non-Vite context | Only standard `import.meta.env.MODE`/`.PROD` remain in app-platform (Vite spec). App-specific vars (`VITE_API_URL`, `VITE_PORTFOLIO_CACHE_TTL`) stay in chassis. |
| Breaking downstream imports | Chassis re-exports are permanent — downstream never changes |
| Cache `portfolioId` → `scopeId` rename | Chassis maps at boundary; domain code still uses `portfolioId` |
| HttpClient behavior regression | Side-by-side tests: same endpoints, same retry behavior. Only change is dropping broken dedup. |
| Test infrastructure | Each phase adds isolated `app-platform` tests + verifies full existing suite |
| Scope creep into catalog | Catalog explicitly deferred with rationale. Auth extracted via factory pattern (Phase 4). Phase 5 is final for v1. |

---

## Success Criteria

1. `@risk/app-platform` has **zero domain imports** (no portfolio, risk, stock, Plaid, etc.)
2. Package builds and tests independently — 25+ isolated tests
3. `@risk/chassis` re-exports all extracted modules — zero downstream breakage
4. All existing tests pass with no regressions
5. Clean dependency graph: `app-platform` → nothing; `chassis` → `app-platform`
6. Logger singleton identity verified (chassis export `===` app-platform export)
7. HttpClient dedup bug fixed as part of extraction

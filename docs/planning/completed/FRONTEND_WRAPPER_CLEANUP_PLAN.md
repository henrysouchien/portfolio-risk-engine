# Frontend Compatibility Wrapper Cleanup Plan

**Date**: 2026-02-24
**Status**: ✅ Complete
**Risk**: Low — purely import path changes, no logic changes
**Prerequisite**: Frontend three-package split (complete)

## Context

When Codex executed the frontend three-package split, it left 32 "compatibility wrapper" files at the old import paths inside `packages/ui/src/`. These are one-liner re-exports like:

```ts
// packages/ui/src/stores/authStore.ts
export * from '@risk/chassis';
```

They exist so that relative imports in UI components (`import { useAuthStore } from '../stores/authStore'`) still resolve after the move. This was the right call during the split — zero breakage risk. But now the packages are stable and working, so these wrappers should be removed to make the decoupling real.

### Why This Matters

- **Dependency graph is hidden** — you can't tell which UI files depend on chassis vs connectors by reading imports
- **Package boundaries aren't enforceable** — ESLint rules can't catch violations when everything routes through local wrappers
- **Swappability is blocked** — you can't replace `@risk/ui` with a different frontend until it imports from the package API, not shadow paths
- **Barrel re-exports are overly broad** — `export * from '@risk/chassis'` leaks the entire chassis surface through `stores/authStore.ts`, confusing auto-import suggestions

## Scope

### Wrapper Files to Remove (32 total)

Every file below is a pure re-export shim with no real logic. All were verified by filesystem audit.

**Stores (3 files):**
| File | Content | Import sites |
|------|---------|--------------|
| `ui/src/stores/authStore.ts` | `export * from '@risk/chassis'` | 5 |
| `ui/src/stores/portfolioStore.ts` | `export * from '@risk/connectors'` | 3 |
| `ui/src/stores/uiStore.ts` | `export * from '@risk/connectors'` | 3 |

**Providers (4 files):**
| File | Content | Import sites |
|------|---------|--------------|
| `ui/src/providers/AuthProvider.tsx` | `export * from '@risk/chassis'` | 1 |
| `ui/src/providers/QueryProvider.tsx` | `export * from '@risk/chassis'` | 1 |
| `ui/src/providers/SessionServicesProvider.tsx` | `export * from '@risk/connectors'` | 9 |
| `ui/src/providers/PortfolioInitializer.tsx` | `export { PortfolioInitializer as default } from '@risk/connectors'; export * from '@risk/connectors'` | 1 |

**Services (1 file):**
| File | Content | Import sites |
|------|---------|--------------|
| `ui/src/services/frontendLogger.ts` | `export { frontendLogger } from '@risk/chassis'` | 20 |

**Lib (1 file):**
| File | Content | Import sites |
|------|---------|--------------|
| `ui/src/lib/utils.ts` | `export { cn } from '@risk/chassis'` | 43 |

**Config (2 files):**
| File | Content | Import sites |
|------|---------|--------------|
| `ui/src/config/environment.ts` | `export * from '@risk/chassis'` | 0 |
| `ui/src/config/providers.ts` | `export * from '@risk/connectors'` | 1 |

**Utils (1 file):**
| File | Content | Import sites |
|------|---------|--------------|
| `ui/src/utils/NavigationIntents.ts` | `export * from '@risk/connectors'` | 6 |

**Repository (1 file):**
| File | Content | Import sites |
|------|---------|--------------|
| `ui/src/repository/PortfolioRepository.ts` | `export * from '@risk/chassis'` | 2 |

**Chassis shadow directory (2 files):**
| File | Content | Import sites |
|------|---------|--------------|
| `ui/src/chassis/services/ProviderRoutingService.ts` | `export * from '@risk/connectors'` | 1 |
| `ui/src/chassis/types/index.ts` | `export * from '@risk/connectors'` | 1 |

**Features — barrel index files (6 files):**
| File | Content | Import sites |
|------|---------|--------------|
| `ui/src/features/analysis/index.ts` | `export * from '@risk/connectors'` | 0 |
| `ui/src/features/auth/index.ts` | `export * from '@risk/connectors'` | 0 |
| `ui/src/features/external/index.ts` | `export * from '@risk/connectors'` | 0 |
| `ui/src/features/portfolio/index.ts` | `export * from '@risk/connectors'` | 0 |
| `ui/src/features/riskMetrics/index.ts` | `export * from '@risk/connectors'` | 0 |
| `ui/src/features/utils/index.ts` | `export * from '@risk/connectors'` | 0 |

**Features — hook wrapper files (11 files):**

These are NOT real implementations — the real hook code lives in `packages/connectors/src/features/*/hooks/`. These are one-liner `export * from '@risk/connectors'` shims.

| File | Content | Import sites |
|------|---------|--------------|
| `ui/src/features/analysis/hooks/useRiskAnalysis.ts` | `export * from '@risk/connectors'` | 4 |
| `ui/src/features/auth/hooks/useConnectAccount.ts` | `export * from '@risk/connectors'` | 2 |
| `ui/src/features/auth/hooks/useConnectSnapTrade.ts` | `export * from '@risk/connectors'` | 2 |
| `ui/src/features/external/hooks/usePlaid.ts` | `export * from '@risk/connectors'` | 1 |
| `ui/src/features/external/hooks/usePortfolioChat.ts` | `export * from '@risk/connectors'` | 1 |
| `ui/src/features/external/hooks/useSnapTrade.ts` | `export * from '@risk/connectors'` | 2 |
| `ui/src/features/optimize/hooks/usePortfolioOptimization.ts` | `export * from '@risk/connectors'` | 1 |
| `ui/src/features/riskScore/hooks/useRiskScore.ts` | `export * from '@risk/connectors'` | 1 |
| `ui/src/features/riskSettings/hooks/useRiskSettings.ts` | `export * from '@risk/connectors'` | 1 |
| `ui/src/features/stockAnalysis/hooks/useStockAnalysis.ts` | `export * from '@risk/connectors'` | 1 |
| `ui/src/features/whatIf/hooks/useWhatIfAnalysis.ts` | `export * from '@risk/connectors'` | 2 |

### Import Replacement Map

Each relative import gets replaced with a direct package import. The named exports are already available from the barrel exports of each package.

**From `@risk/chassis`:**
- `useAuthStore`, `useAuthActions`, `teardownAuth` (from authStore)
- `AuthProvider` (from providers)
- `QueryProvider` (from providers)
- `cn` (from lib/utils)
- `frontendLogger` (from services)
- `PortfolioRepository` (from repository)
- Environment config exports

**From `@risk/connectors`:**
- `usePortfolioStore`, `useCurrentPortfolio` (from portfolioStore)
- `useUIStore`, `useUIActions`, `useActiveView` (from uiStore)
- `SessionServicesProvider`, `useSessionServices`, `useServicesReady`, `useAPIService`, `usePortfolioCache`, `usePortfolioManager`, `useClaudeService`
- `PortfolioInitializer` (**named export**, not default — see note below)
- `ProviderRoutingService`
- `User` type (from chassis/types — re-exported through connectors)
- `IntentRegistry` (from NavigationIntents)
- `INSTITUTION_CONFIG`, `getInstitutionConfig`, `getPopularInstitutions`
- All feature hooks: `useRiskAnalysis`, `usePerformance`, `usePortfolioSummary`, `useRiskScore`, `useRiskSettings`, `useRiskMetrics`, `useStockAnalysis`, `useWhatIfAnalysis`, `usePortfolioOptimization`, `useAuthFlow`, `useConnectAccount`, `useConnectSnapTrade`, `usePlaid`, `useSnapTrade`, `usePortfolioChat`, `useInstantAnalysis`, `usePendingUpdates`, `useCancellablePolling`, `useCancelableRequest`, `usePlaidPolling`

### PortfolioInitializer: Default → Named Export

The current wrapper aliases the named export as default:
```ts
// ui/src/providers/PortfolioInitializer.tsx (wrapper)
export { PortfolioInitializer as default } from '@risk/connectors';
```

The consumer currently uses a default import:
```ts
import PortfolioInitializer from '../../providers/PortfolioInitializer';
```

`@risk/connectors` exports it as **named** (`export { default as PortfolioInitializer }`). After removing the wrapper, the consumer must switch to a named import:
```ts
import { PortfolioInitializer } from '@risk/connectors';
```

## Execution Steps

### Step 1 — Update imports in each UI consumer file

Work through each file that imports from a wrapper path. Replace the relative import with the direct package import. Process by consumer file (not by wrapper) so each file is touched once. Use both single and double quote patterns when searching — Radix components use double quotes, app components use single quotes.

**High-touch files (many wrapper imports):**
- 43 Radix UI components in `components/ui/` — all import `{ cn }` from `../../lib/utils` → `@risk/chassis`
- 20 files importing `frontendLogger` from `../services/frontendLogger` → `@risk/chassis`
- 6 files importing from `utils/NavigationIntents` → `@risk/connectors`
- `App.tsx` — 6 wrapper imports → `@risk/chassis` + `@risk/connectors`
- `SessionServicesProvider` consumers — 9 files → `@risk/connectors`

**Medium-touch files (2-4 wrappers each):**
- `ModernDashboardApp.tsx` — portfolioStore, uiStore, PortfolioInitializer, feature hooks
- `AccountConnectionsContainer.tsx` — ProviderRoutingService, providers config, auth hooks, plaid hooks, snapTrade hooks
- `HoldingsViewModernContainer.tsx` — portfolioStore, SessionServicesProvider, feature hooks
- Container components in `views/modern/` — SessionServicesProvider + feature hooks each
- `AppOrchestratorModern.tsx` / `AppOrchestrator.tsx` — authStore, SessionServicesProvider

**Low-touch files (1 wrapper each):**
- `DashboardLayout.tsx` — `User` type
- `LandingPage.tsx` — authStore, authFlow
- `InstantTryPage.tsx` — uiStore, portfolio hooks
- `AuthInitializer.tsx` — authStore
- Various single-hook consumers (ChatContext, SnapTradeLaunchButton, etc.)

**Example transformations:**
```ts
// BEFORE (app component, single quotes)
import { useAuthStore } from '../stores/authStore';
import { useUIStore } from '../stores/uiStore';
import { AuthProvider } from './providers/AuthProvider';

// AFTER
import { useAuthStore, AuthProvider } from '@risk/chassis';
import { useUIStore } from '@risk/connectors';
```

```ts
// BEFORE (Radix component, double quotes)
import { cn } from "../../lib/utils"

// AFTER
import { cn } from "@risk/chassis"
```

```ts
// BEFORE (default import)
import PortfolioInitializer from '../../providers/PortfolioInitializer';

// AFTER (named import)
import { PortfolioInitializer } from '@risk/connectors';
```

Where possible, consolidate multiple imports from the same package into a single import statement.

### Step 2 — Delete all 32 wrapper files and empty directories

Remove all 32 wrapper files. Then clean up empty directories:
- Delete `ui/src/chassis/` directory entirely
- Delete `ui/src/features/` directory entirely (all files are wrappers — real implementations live in `packages/connectors/src/features/`)
- Delete `ui/src/stores/` directory (all 3 files are wrappers)
- Delete `ui/src/config/` directory if empty (check for non-wrapper files first)
- Delete `ui/src/services/` directory if frontendLogger was the only file
- Delete `ui/src/lib/` directory if utils.ts was the only file
- Delete `ui/src/repository/` directory if PortfolioRepository was the only file
- Delete `ui/src/utils/` directory if NavigationIntents was the only file
- Keep `ui/src/providers/` only if it has non-wrapper files

### Step 3 — Verify

1. `pnpm build` — all three packages compile
2. `pnpm lint` — no import errors
3. `pnpm dev` + backend — smoke test: page loads, portfolio loads, risk analysis runs
4. Comprehensive grep — no remaining relative imports to any deleted wrapper path:

```bash
# Must all return zero results. Uses both quote styles.
# Scoped to code files only (-g) to avoid false matches in ARCHITECTURE.md docs.
cd frontend

# Stores
rg -g '*.{ts,tsx,js,jsx}' "from ['\"].*stores/authStore" packages/ui/src/
rg -g '*.{ts,tsx,js,jsx}' "from ['\"].*stores/portfolioStore" packages/ui/src/
rg -g '*.{ts,tsx,js,jsx}' "from ['\"].*stores/uiStore" packages/ui/src/

# Providers
rg -g '*.{ts,tsx,js,jsx}' "from ['\"].*providers/AuthProvider" packages/ui/src/
rg -g '*.{ts,tsx,js,jsx}' "from ['\"].*providers/QueryProvider" packages/ui/src/
rg -g '*.{ts,tsx,js,jsx}' "from ['\"].*providers/SessionServicesProvider" packages/ui/src/
rg -g '*.{ts,tsx,js,jsx}' "from ['\"].*providers/PortfolioInitializer" packages/ui/src/

# Services, lib, utils, repository
rg -g '*.{ts,tsx,js,jsx}' "from ['\"].*services/frontendLogger" packages/ui/src/
rg -g '*.{ts,tsx,js,jsx}' "from ['\"].*lib/utils" packages/ui/src/
rg -g '*.{ts,tsx,js,jsx}' "from ['\"].*utils/NavigationIntents" packages/ui/src/
rg -g '*.{ts,tsx,js,jsx}' "from ['\"].*repository/PortfolioRepository" packages/ui/src/

# Config
rg -g '*.{ts,tsx,js,jsx}' "from ['\"].*config/environment" packages/ui/src/
rg -g '*.{ts,tsx,js,jsx}' "from ['\"].*config/providers" packages/ui/src/

# Chassis shadow
rg -g '*.{ts,tsx,js,jsx}' "from ['\"].*chassis/" packages/ui/src/

# Features (all paths)
rg -g '*.{ts,tsx,js,jsx}' "from ['\"].*features/" packages/ui/src/
```

## Out of Scope

- **ESLint boundary enforcement** — adding `eslint-plugin-import` rules to prevent future violations. Worth doing after this cleanup, but separate task.
- **TypeScript strict mode fixes** — pre-existing `pnpm typecheck` issues are unrelated.

## Risk Assessment

**Risk: Low**
- Every change is a mechanical import path replacement
- No logic, component, or data flow changes
- All named exports already exist in the package barrels (verified against `chassis/src/index.ts` and `connectors/src/index.ts`)
- One default→named export change (`PortfolioInitializer`) — straightforward
- Easy to verify: `pnpm build` catches any broken import immediately
- Fully reversible: git revert if anything goes wrong

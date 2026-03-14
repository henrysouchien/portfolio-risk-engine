# Frontend Package Split — Session Handoff

**Date**: 2026-02-24
**Status**: ✅ Complete — split done, wrappers cleaned, verified working

## What Happened

1. Planned and documented a three-package frontend split: `@risk/chassis`, `@risk/connectors`, `@risk/ui`
2. Plan reviewed by Codex (3 rounds) — all findings addressed, passed
3. Codex executed the full split: CRA → Vite migration, pnpm workspaces, file moves, boundary violation fixes
4. Wrapper cleanup plan reviewed by Codex (3 rounds) — Codex executed removal of all 32 compatibility wrappers
5. ESLint migrated from `eslint-config-react-app` (CRA) to standalone plugins (0 errors, 1850 warnings)
6. Two bugs found and fixed during testing:
   - **Stale CRA `node_modules`** causing dual React instance → clean install fixed
   - **`rawData → portfolioHoldings` typo** in `PortfolioSummaryAdapter.ts:386` → crashed render silently (no error boundary)
7. Also fixed: `CUR:XXX` ticker validation in `portfolio_risk_score.py` (colon not in allowed regex)
8. `pnpm build`, `pnpm lint`, `pnpm dev` all passing. Dashboard verified rendering in Chrome (portfolio value, risk scores, charts, all working)

## Key Files

| File | Purpose |
|------|---------|
| `docs/planning/FRONTEND_PACKAGE_SPLIT_PLAN.md` | Full implementation plan (Codex-reviewed) |
| `frontend/vite.config.ts` | Vite config (proxy: /api, /auth, /plaid → 5001) |
| `frontend/pnpm-workspace.yaml` | Workspace definition |
| `frontend/index.html` | Entry HTML (loads `packages/ui/src/index.tsx`) |
| `frontend/packages/chassis/src/index.ts` | Chassis barrel exports |
| `frontend/packages/connectors/src/index.ts` | Connectors barrel exports |
| `frontend/packages/ui/src/App.tsx` | Root React component (provider hierarchy) |
| `frontend/packages/ui/src/index.tsx` | ReactDOM.createRoot entry |

## Architecture

```
@risk/ui → @risk/connectors → @risk/chassis
```

- **Chassis**: auth, caching (6-piece), API client, service container, logging, stores (authStore, portfolioStore)
- **Connectors**: adapters (9), feature hooks (15+), managers, domain services, SessionServicesProvider, types
- **UI**: Radix components (40+), dashboard views, chat, pages, theming

Compatibility wrappers exist in `packages/ui/src/` (providers/, stores/, chassis/, services/, features/, etc.) that re-export from upstream packages so old relative imports still resolve. These are intentional — gradual cleanup later.

## Boundary Violation Fixes Applied

- AuthProvider: AuthInitializer logic inlined (no more UI import from chassis)
- sessionCleanup: moved to connectors, uses `registerSessionCleanup()` callback
- PortfolioInitializer: accepts `loadingFallback`/`errorFallback` props
- SessionServicesProvider: `require()` calls converted to ESM
- Legacy export removed from `components/apps/index.ts`

# Frontend Performance Baseline — 2026-03-10
**Status:** ACTIVE

**Purpose:** Quantitative frontend performance baseline. Companion to the backend baseline (`PERFORMANCE_BASELINE_2026-03-10.md`). Use this document to track improvement over time.

## Measurement Conditions

- **Bundler**: Vite 7.1.3
- **Build output**: `frontend/packages/ui/dist/`
- **Dev server**: localhost:3000
- **Backend**: localhost:5001, single uvicorn worker
- **Browser**: Chrome (standard DevTools)

---

## 1. Bundle Size

| Asset | Size (raw) | Size (gzip) | Notes |
|-------|-----------|-------------|-------|
| `index-BXqsMaHe.js` | 2.1 MB | 599 KB | **Single chunk — zero code splitting** |
| CSS | 167 KB | — | |
| KaTeX fonts | ~1.1 MB | — | 60+ font files loaded globally |
| **Total build** | **~3.4 MB** | — | |

**Key issue:** Entire app is a single JS bundle. No route-level or component-level splitting. All 3 app shells (LandingApp, AnalystApp, ModernDashboardApp) imported eagerly at top level.

---

## 2. Code Splitting & Lazy Loading

| Metric | Count |
|--------|-------|
| `React.lazy()` in production | 0 |
| `React.lazy()` total (incl. dev-only) | 1 (QueryDevtools) |
| Dynamic `import()` | 0 |
| Route-level splitting | None |
| Component-level lazy loading | None |

**Opportunity:** Lazy-load app shells. Only LandingApp needs to be eager; AnalystApp and ModernDashboardApp can be lazy-loaded after auth.

---

## 3. Re-Render Analysis

| Metric | Count | Location |
|--------|-------|----------|
| `React.memo` | 34 | @risk/ui only |
| `useMemo` | 38 | @risk/ui only |
| `useCallback` | 20 | @risk/ui only |
| Memoization in @risk/chassis | **0** | Services/hooks never memoized |
| Contexts defined | 21 | Across all packages |

**Critical bug:** `ModernDashboardApp` (948 lines) re-renders every 1 second from a clock timer. The timer state lives in the dashboard component itself, causing full reconciliation of the entire component tree on every tick.

**SessionServicesContext** is at root level — any update to session services triggers re-renders across the full tree.

---

## 4. Data Fetching

### Query Configuration
- `staleTime`: 5 min
- `gcTime`: 10 min
- Retry: 3x on 5xx, never on 4xx

### Prefetch Strategy
5 sources eagerly prefetched via scheduler with dependency-aware grouping:
- positions, risk-score, risk-analysis, risk-profile, performance
- `groupByDependencyLevel()` + `Promise.allSettled` for parallel fetch

### Cold Load Waterfall (26 requests)
```
[     0ms] Auth check (/auth/status)                          ~3ms
[     0ms] Portfolio load (/api/portfolios/CURRENT_PORTFOLIO)  ~2.2s    ← blocks everything
[  ~2.5s] Parallel burst (positions, alerts, prefetch)
[  ~5.6s] Heavy queries fire in parallel:
            /api/risk-score                                    ~38s     ← CRITICAL PATH
            /api/analyze                                       ~38s     ← CRITICAL PATH
            /api/performance                                   ~38s     ← CRITICAL PATH
            /api/positions/market-intelligence                 ~13s
            /api/positions/ai-recommendations                  ~23s
            /api/positions/metric-insights                     ~27s
            /api/allocations/target                            ~43s     ← SLOWEST
[ ~48.8s] Last response received

Total time to full data: ~49s (cold cache)
```

### Prior Optimization
- Phase 1: Batched logging — 55 → 11 requests
- Phase 2: Scheduler prefetch + parallel fetch — 45 → 26 requests
- **75% total API request reduction** (103 → 26)

---

## 5. Dependencies

### @risk/ui (49 direct deps)
- **27 Radix UI components** — all bundled regardless of usage
- Heavy: recharts, framer-motion, katex, react-markdown, react-hook-form, react-resizable-panels, react-day-picker, snaptrade-react, sonner

### @risk/chassis (7 deps)
- React Query, devtools, clsx, tailwind-merge, zod, zustand

### @risk/connectors (3 deps)
- React Query, zod, @risk/chassis

---

## 6. Source Code Structure

| Package | TSX Files | Total Files | Role |
|---------|-----------|-------------|------|
| @risk/ui | 155 | 229 | Components, views |
| @risk/chassis | 1 | 57 | Services, providers, stores |
| @risk/connectors | 49 | 223 | Data hooks (~77 exports) |
| **Total** | **205** | **509** | |

---

## 7. Optimization Opportunities (Prioritized)

### ~~Quick Wins~~ (Already Done)
1. ~~**Clock isolation**~~ — `LiveClock` already extracted as standalone component. Re-renders scoped.
2. ~~**Background polling pause**~~ — `refetchIntervalInBackground: false` already set on all polling queries.
3. ~~**Route-level lazy loading**~~ — `ModernDashboardApp` + `AnalystApp` already use `React.lazy()`.

### Medium Effort
4. **KaTeX conditional loading** — Dynamic import only when math content is rendered. Saves ~1.1 MB font load.
5. **Radix tree-shaking audit** — Verify all 27 components are used. Remove unused imports.
6. **Memoization pass on chassis hooks** — Add `useMemo`/`useCallback` to high-frequency service hooks.

### Larger Effort
7. **Component-level code splitting** — Lazy-load heavy views (ScenarioAnalysis, StockLookup).
8. **SessionServicesContext refactor** — Split into smaller contexts to reduce re-render scope.
9. **Hook migration completion** — Batch D (useWhatIfAnalysis) and E (usePositions) remaining.

---

## Tracking

| Date | Bundle (gzip) | Lazy Routes | Cold Load (s) | API Requests | Notes |
|------|--------------|-------------|---------------|-------------|-------|
| 2026-03-10 | 599 KB | 0 | ~49s | 26 | Baseline |

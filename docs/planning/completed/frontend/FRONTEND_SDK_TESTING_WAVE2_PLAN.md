# Frontend SDK Testing — Wave 2

## Context

54 tests exist across 8 files covering layers 1-3 (catalog, error model, resolver) + 1 hook (useRiskScore). 42 hooks remain untested. This wave targets ~174 new tests across 26 files, covering all hooks with straightforward patterns. Complex hooks with deep external dependencies (OAuth, WebSocket, Plaid SDK) are deferred to Wave 3.

All test file paths relative to `frontend/packages/connectors/src/`.

---

## Phase 1: Simple Wrappers (~70 tests, 10 files)

### 1A: useDataSource wrappers (same template as useRiskScore — mock `useDataSource` + `useCurrentPortfolio`)

Each gets 7-8 tests: hasPortfolio, hasData, error mapping, refetch delegation, loading state, correct sourceId+params, option forwarding.

| File | Hook | sourceId | Extra |
|------|------|----------|-------|
| `features/analysis/__tests__/useRiskAnalysis.test.tsx` | `useRiskAnalysis` | `risk-analysis` | `performancePeriod` option |
| `features/analysis/__tests__/usePerformance.test.tsx` | `usePerformance` | `performance` | `benchmarkTicker` option |

### 1B: Multi-source useDataSource wrappers

| File | Hook | Pattern | Extra |
|------|------|---------|-------|
| `features/riskMetrics/__tests__/useRiskMetrics.test.tsx` | `useRiskMetrics` | Multiple useDataSource calls | Combined loading, variance extraction |
| `features/analysis/__tests__/useAnalysisReport.test.tsx` | `useAnalysisReport` | Multiple useDataSource calls | Report composition |

### 1C: useQuery + API wrappers (mock `useSessionServices`, need QueryClient wrapper)

Each gets 6 tests: initial state, data transformation, loading, error, empty data, refetch.

| File | Hook | API method |
|------|------|------------|
| `features/positions/__tests__/useSmartAlerts.test.tsx` | `useSmartAlerts` | `api.getPortfolioAlerts` |
| `features/positions/__tests__/useMetricInsights.test.tsx` | `useMetricInsights` | `api.getMetricInsights` |
| `features/positions/__tests__/useAIRecommendations.test.tsx` | `useAIRecommendations` | `api.getAIRecommendations` |
| `features/positions/__tests__/useMarketIntelligence.test.tsx` | `useMarketIntelligence` | `api.getMarketIntelligence` |

### 1D: useQuery + adapter (same as 1C but verify adapter transformation)

| File | Hook | API + Adapter |
|------|------|---------------|
| `features/positions/__tests__/usePositions.test.tsx` | `usePositions` | `api.getPositionsHoldings` + `PositionsAdapter` |
| `features/hedging/__tests__/useHedgingRecommendations.test.tsx` | `useHedgingRecommendations` | `api.getHedgingRecommendations` + `HedgingAdapter` |

---

## Phase 2: Mutation Hooks (~32 tests, 5 files)

Mock `useSessionServices`, verify mutation call + state transitions. Each gets 6-8 tests: initial state, mutate calls API, success data, error state, reset, hook-specific (cache invalidation, param forwarding).

| File | Hook | API method | Extra |
|------|------|------------|-------|
| `features/hedging/__tests__/useHedgePreview.test.tsx` | `useHedgePreview` | `api.getHedgePreview` | Param forwarding |
| `features/hedging/__tests__/useHedgeTrade.test.tsx` | `useHedgeTradePreview` + `useHedgeTradeExecute` | `api.executeHedgePreview` + `api.executeHedgeTrades` | Both exports |
| `features/analysis/__tests__/useRealizedPerformance.test.tsx` | `useRealizedPerformance` | `api.getRealizedPerformance` | Adapter transformation |
| `features/allocation/__tests__/useSetTargetAllocation.test.tsx` | `useSetTargetAllocation` | `api.setTargetAllocations` | Cache invalidation |
| `features/allocation/__tests__/useRebalanceTrades.test.tsx` | `useRebalanceTrades` | `api.generateRebalanceTrades` | Param forwarding |

---

## Phase 3: Query + State Hooks (~35 tests, 6 files)

| File | Hook | Pattern | Tests |
|------|------|---------|-------|
| `features/allocation/__tests__/useTargetAllocation.test.tsx` | `useTargetAllocation` | useQuery + `api.getTargetAllocations` | `hasTargets` derivation, portfolio name |
| `features/stockAnalysis/__tests__/useStockSearch.test.tsx` | `useStockSearch` | Query with string input | Disabled when empty, results transformation |
| `features/stockAnalysis/__tests__/usePeerComparison.test.tsx` | `usePeerComparison` | Query with symbol input | Disabled when null, data passthrough |
| `features/stockAnalysis/__tests__/useStockAnalysis.test.tsx` | `useStockAnalysis` | Query + `analyzeStock()` trigger | Initial state, trigger sets ticker, adapter transformation |
| `features/optimize/__tests__/useStrategyTemplates.test.tsx` | `useStrategyTemplates` | Simple query | Returns TanStack Query result directly |
| `features/notifications/__tests__/useNotificationStorage.test.tsx` | `useNotificationStorage` | localStorage + useState | dismiss/markAsRead/dismissAll, localStorage persistence |

---

## Phase 4: Composition + Trigger Hooks (~37 tests, 5 files)

| File | Hook | Pattern | Tests |
|------|------|---------|-------|
| `features/notifications/__tests__/useNotifications.test.tsx` | `useNotifications` | Composes alerts+pending+storage | Alert→notification mapping, severity, dismiss routing, clearAll |
| `features/monteCarlo/__tests__/useMonteCarlo.test.tsx` | `useMonteCarlo` | Query with `enabled:false` + trigger | Initial state, runMonteCarlo triggers, error handling |
| `features/stressTest/__tests__/useStressTest.test.tsx` | `useStressTest` (trigger-driven query) + `useStressScenarios` (plain query) | Trigger + query | runStressTest sets scenarioId + triggers refetch; useStressScenarios is a simple query passthrough |
| `features/backtest/__tests__/useBacktest.test.tsx` | `useBacktest` | Query with trigger | Weight normalization, runBacktest, adapter |
| `features/scenarioHistory/__tests__/useScenarioHistory.test.tsx` | `useScenarioHistory` | Query + 2 mutations | Runs list, addRun, clearHistory, optimistic updates |

---

## Deferred to Wave 3

Complex hooks with deep external dependencies:
- Auth: `useAuthFlow`, `useConnectAccount`, `useConnectSnapTrade`
- External SDKs: `usePlaid`, `useSnapTrade`
- Real-time: `usePortfolioChat`, `useChat` (thin alias for usePortfolioChat)
- Complex composition: `usePortfolioOptimization`, `useInstantAnalysis`, `useWhatIfAnalysis`, `usePortfolioSummary`, `usePendingUpdates`, `useRiskSettings`
- Utilities: `useCancelableRequest`, `useCancellablePolling`, `usePlaidPolling`

---

## Implementation Notes

1. **QueryClient wrapper**: Phase 1C+ hooks use `useQuery`/`useMutation` directly — need `QueryClientProvider` wrapper. Use existing `renderHookWithQuery` from `frontend/test/helpers/renderWithProviders.tsx`.

2. **Mock pattern for useSessionServices**:
```typescript
vi.mock('../../../providers/SessionServicesProvider', () => ({
  useSessionServices: vi.fn(),
}));
const mockApi = { methodName: vi.fn() };
mockUseSessionServices.mockReturnValue({ api: mockApi } as never);
```

3. **Adapter mocking**: Mock adapter `transform()` rather than testing full pipeline. Adapters have separate tests.

4. **Async assertions**: Use `waitFor(() => expect(...))` for all useQuery-based hooks.

5. All test files go in `__tests__/` directory alongside the hook, inside `frontend/packages/connectors/src/features/`.

## Reference Files

- Template: `frontend/packages/connectors/src/features/riskScore/__tests__/useRiskScore.test.tsx`
- Helper: `frontend/test/helpers/renderWithProviders.tsx`
- Mock target: `frontend/packages/connectors/src/providers/SessionServicesProvider.tsx`

## Verification

1. `cd frontend && pnpm test` — all tests pass
2. `cd frontend && pnpm test -- --reporter=verbose` — verify test count (~228 total)

## Execution

Phases 1-4 can be sent to Codex sequentially (one phase per Codex call) or batched. Phase 1 establishes patterns, then 2-4 can go in parallel.

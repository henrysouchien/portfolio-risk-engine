# Efficient Frontier — Phase 2 (Frontend Visualization)
**Status:** DONE

## Context

Phase 1 backend is complete (`33f2d33d`): CVXPY parametric volatility sweep engine, MCP tool (`get_efficient_frontier`), REST endpoint (`POST /api/efficient-frontier`), result object, 5 tests. Live-verified: 10-point frontier in 2.2s against live portfolio.

Phase 2 adds the frontend visualization: a new "Efficient Frontier" tab in ScenarioAnalysis showing the frontier curve as a scatter chart with the current portfolio plotted for reference.

## Architecture

Data flow mirrors the Monte Carlo tab pattern exactly:

```
APIService.runEfficientFrontier()          # chassis — POST /api/efficient-frontier
  → PortfolioCacheService.getEfficientFrontier()  # chassis — getOrFetch cache wrapper
    → PortfolioManager.analyzeEfficientFrontier()  # connectors — manager method
      → useEfficientFrontier()                     # connectors — TanStack Query hook
        → ScenarioAnalysisContainer                # connectors — wires hook → props
          → ScenarioAnalysis                       # ui — passes props to tab
            → EfficientFrontierTab                 # ui — Recharts ScatterChart
```

**No history tracking** — The scenario history system (`useScenarioHistory`) only supports `whatif | stress | monte-carlo` types in both connectors and backend persistence (`app.py:2393`). Extending it is out of scope. The tab will not use `RecentRunsPanel` or history props.

## API Response Shape (from live endpoint)

```json
{
  "success": true,
  "optimization_results": {
    "frontier_points": [
      { "volatility_pct": 0.34, "expected_return_pct": 6.76, "label": "min_variance", "is_feasible": true },
      { "volatility_pct": 2.53, "expected_return_pct": 30.1, "label": "frontier_1", "is_feasible": true },
      ...
      { "volatility_pct": 20, "expected_return_pct": 81.83, "label": "max_return", "is_feasible": true }
    ],
    "current_portfolio": { "volatility_pct": 8.09, "expected_return_pct": 13.13 },
    "min_variance": { ... },
    "max_return": { ... },
    "meta": { "n_feasible": 10, "n_requested": 10, "computation_time_s": 2.2, "analysis_date": "..." }
  },
  "summary": { "type": "efficient_frontier", "n_frontier_points": 10, ... },
  "portfolio_metadata": { "name": "...", "user_id": "...", "source": "database", "analyzed_at": "..." },
  "risk_limits_metadata": { "name": "...", "source": "database" }
}
```

## Files to Create

### 1. `chassis/src/types/api.ts` — Add `EfficientFrontierApiResponse`

After `MonteCarloApiResponse` (~line 120):

```ts
export interface EfficientFrontierPoint {
  volatility_pct: number;
  expected_return_pct: number;
  label: string;
  is_feasible: boolean;
}

export interface EfficientFrontierApiResponse {
  success: boolean;
  optimization_results: {
    frontier_points: EfficientFrontierPoint[];
    current_portfolio: { volatility_pct: number; expected_return_pct: number };
    min_variance: EfficientFrontierPoint;
    max_return: EfficientFrontierPoint;
    meta: {
      n_feasible: number;
      n_requested: number;
      computation_time_s: number;
      analysis_date: string;
    };
  };
  summary: Record<string, unknown>;
  portfolio_metadata?: {
    name: string;
    user_id: string;
    source: string;
    analyzed_at: string;
  };
  risk_limits_metadata?: {
    name: string;
    source: string;
  };
}
```

Export from `chassis/src/types/index.ts` and `chassis/src/index.ts`.

### 2. `chassis/src/queryKeys.ts` — Add `efficientFrontierKey`

After `monteCarloKey` (~line 129):

```ts
export const efficientFrontierKey = (portfolioId?: string | null) =>
  scoped('efficientFrontier', portfolioId);
```

Add `'efficientFrontier'` to `AppQueryKey` union.

### 3. `chassis/src/config/queryConfig.ts` — Add `useEfficientFrontier` stale time

After `useMonteCarlo` (~line 263):

```ts
  /**
   * Efficient frontier optimization results.
   * Volatility: Low - Explicit n_points input produces deterministic, cacheable runs.
   * Safe expiry: 60 minutes, favors reuse of the same frontier computation.
   */
  useEfficientFrontier: {
    staleTime: getStaleTime('reference'),
    category: 'reference' as const
  },
```

### 4. `chassis/src/services/APIService.ts` — Add `runEfficientFrontier()`

After `runMonteCarlo()` (~line 918). Add `EfficientFrontierApiResponse` to the import from `'../types'` (~line 31):

```ts
async runEfficientFrontier(
  portfolioName: string,
  params?: { nPoints?: number }
): Promise<EfficientFrontierApiResponse> {
  return this.request('/api/efficient-frontier', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      portfolio_name: portfolioName,
      n_points: params?.nPoints ?? 15,
    }),
  });
}
```

### 5. `chassis/src/services/PortfolioCacheService.ts` — Add `getEfficientFrontier()`

After `getMonteCarlo()` (~line 641). Add `EfficientFrontierApiResponse` to the import from `'../types'` (~line 47):

```ts
async getEfficientFrontier(
  portfolioId: string,
  portfolio: Portfolio,
  params?: { nPoints?: number }
): Promise<EfficientFrontierApiResponse> {
  const repository = this.getRepository();
  const operation = `efficientFrontier_${params?.nPoints ?? 15}`;
  return this.getOrFetch(portfolioId, operation, async () => {
    try {
      repository.setPortfolioLoading(portfolioId, true);
      return await this.apiService.runEfficientFrontier(
        this.getPortfolioName(portfolio),
        params
      );
    } catch (error) {
      repository.setPortfolioError(portfolioId, error instanceof Error ? error.message : 'Efficient frontier computation failed');
      throw error;
    } finally {
      repository.setPortfolioLoading(portfolioId, false);
    }
  });
}
```

### 6. `connectors/src/managers/PortfolioManager.ts` — Add `analyzeEfficientFrontier()`

After `analyzeMonteCarlo()` (~line 602). Add `EfficientFrontierApiResponse` to the import from `'@risk/chassis'` (~line 27):

```ts
public async analyzeEfficientFrontier(params?: {
  nPoints?: number;
}): Promise<{ frontier: EfficientFrontierApiResponse | null; error: string | null }> {
  try {
    const storeState = usePortfolioStore.getState();
    const portfolioId = storeState.currentPortfolioId;
    if (!portfolioId) throw new Error('Portfolio not found');
    const portfolio = storeState.byId[portfolioId]?.portfolio;
    if (!portfolio) throw new Error('Portfolio not found');
    const response = await this.portfolioCacheService.getEfficientFrontier(portfolioId, portfolio, params);
    if (response && response.success !== false) {
      return { frontier: response, error: null };
    }
    return { frontier: null, error: 'Efficient frontier computation failed' };
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : 'Efficient frontier computation failed';
    frontendLogger.error('Efficient frontier error', 'PortfolioManager', error instanceof Error ? error : new Error(String(error)));
    return { frontier: null, error: errorMessage };
  }
}
```

### 7. `connectors/src/features/efficientFrontier/hooks/useEfficientFrontier.ts` — NEW

```ts
import { useCallback, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { HOOK_QUERY_CONFIG, efficientFrontierKey, useCurrentPortfolio } from '@risk/chassis';
import type { EfficientFrontierApiResponse } from '@risk/chassis';
import { useSessionServices } from '../../../providers/SessionServicesProvider';

export interface EfficientFrontierParams {
  nPoints?: number;
}

export const useEfficientFrontier = () => {
  const { manager } = useSessionServices();
  const currentPortfolio = useCurrentPortfolio();
  const [params, setParams] = useState<EfficientFrontierParams | null>(null);

  const { data, isLoading, isRefetching, error, refetch } = useQuery({
    queryKey: efficientFrontierKey(currentPortfolio?.id || 'none'),
    queryFn: async (): Promise<EfficientFrontierApiResponse | null> => {
      if (!currentPortfolio || !params) return null;
      const result = await manager.analyzeEfficientFrontier(params);
      if (result.error) throw new Error(result.error);
      if (!result.frontier) throw new Error('Efficient frontier returned no data');
      return result.frontier;
    },
    enabled: false,
    staleTime: HOOK_QUERY_CONFIG.useEfficientFrontier?.staleTime || 60 * 60 * 1000,
    retry: (failureCount) => failureCount < 2,
  });

  const runEfficientFrontier = useCallback((nextParams: EfficientFrontierParams = {}) => {
    setParams(nextParams);
    setTimeout(() => { void refetch(); }, 0);
  }, [refetch]);

  return useMemo(() => ({
    result: data,
    isRunning: isLoading || isRefetching,
    runEfficientFrontier,
    error: error?.message ?? null,
  }), [data, isLoading, isRefetching, runEfficientFrontier, error]);
};
```

Barrel files:
- `connectors/src/features/efficientFrontier/hooks/index.ts` — `export { useEfficientFrontier } from './useEfficientFrontier'`
- `connectors/src/features/efficientFrontier/index.ts` — `export { useEfficientFrontier } from './hooks'`
- **`connectors/src/features/index.ts`** — Add `export { useEfficientFrontier } from './efficientFrontier'`
- **`connectors/src/index.ts`** (~line 11) — Add `export { useEfficientFrontier } from './features/efficientFrontier'`

### 8. `ui/src/components/portfolio/scenario/EfficientFrontierTab.tsx` — NEW

Recharts `ScatterChart` showing:
- Frontier curve as connected scatter points (emerald color)
- Current portfolio as a distinct red/orange marker
- Min-variance and max-return labeled endpoints
- X-axis: Volatility (%), Y-axis: Expected Return (%)

Structure matches MonteCarloTab pattern:
- Run button + n_points radio selector (10/15/20)
- Summary metric cards (min vol, max return, computation time, n points)
- ScatterChart via `ChartContainer` with `getAxisPreset()`, `getGridPreset()`, `chartSemanticColors`
- Frontier points detail table
- **No** `RecentRunsPanel` or history props (history not supported for this tab type)

Reuse from existing codebase:
- `ChartContainer` from `../../blocks`
- `getAxisPreset()`, `getGridPreset()`, `chartSemanticColors` from `../../../lib/chart-theme`
- `ChartTooltip` from `../../blocks`
- `Card`, `Button`, `Badge` from `../../ui/`
- `TabContentWrapper` from `../../blocks`
- `formatImpactPercent` from `./helpers`

Props interface:

```ts
interface EfficientFrontierTabProps {
  efficientFrontierResult?: EfficientFrontierApiResponse | null;
  isEfficientFrontierRunning?: boolean;
  efficientFrontierError?: string | null;
  nPoints: number;
  setNPoints: (n: number) => void;
  canRunEfficientFrontier: boolean;
  runEfficientFrontier: () => void;
}
```

## Files to Modify

### 9. `ui/src/components/portfolio/scenario/types.ts`

Add `"efficient-frontier"` to `ScenarioTab` union:
```ts
export type ScenarioTab = "portfolio-builder" | "historical" | "stress-tests" | "monte-carlo" | "optimizations" | "efficient-frontier"
```

Add to `ScenarioAnalysisProps` (import `EfficientFrontierApiResponse` from `@risk/chassis`):
```ts
efficientFrontierResult?: EfficientFrontierApiResponse | null;
isEfficientFrontierRunning?: boolean;
efficientFrontierError?: string | null;
onRunEfficientFrontier?: (params: { nPoints?: number }) => void;
```

### 10. `ui/src/components/portfolio/scenario/index.ts`

Add export:
```ts
export { EfficientFrontierTab } from "./EfficientFrontierTab"
```

### 11. `ui/src/components/portfolio/ScenarioAnalysis.tsx`

- Import `EfficientFrontierTab` from `./scenario`
- Destructure `efficientFrontierResult`, `isEfficientFrontierRunning`, `efficientFrontierError`, `onRunEfficientFrontier` from props
- Add state: `const [efNPoints, setEfNPoints] = useState(15)`
- Add derived: `const canRunEfficientFrontier = typeof onRunEfficientFrontier === "function"`
- Add handler:
  ```ts
  const runEfficientFrontier = () => {
    if (!onRunEfficientFrontier || isEfficientFrontierRunning) return;
    onRunEfficientFrontier({ nPoints: efNPoints });
  }
  ```
- Update `showGlobalComingSoonBanner` (~line 97):
  ```ts
  const showGlobalComingSoonBanner = !canRunScenario
    && !(activeTab === "stress-tests" && canRunStressTests)
    && !(activeTab === "monte-carlo" && canRunMonteCarlo)
    && !(activeTab === "efficient-frontier" && canRunEfficientFrontier)
  ```
- Add new `TabsTrigger` after Monte Carlo: `<TabsTrigger value="efficient-frontier">Efficient Frontier</TabsTrigger>`
- Add `<EfficientFrontierTab>` after `<MonteCarloTab>` (~line 403):
  ```tsx
  <EfficientFrontierTab
    efficientFrontierResult={efficientFrontierResult}
    isEfficientFrontierRunning={isEfficientFrontierRunning}
    efficientFrontierError={efficientFrontierError}
    nPoints={efNPoints}
    setNPoints={setEfNPoints}
    canRunEfficientFrontier={canRunEfficientFrontier}
    runEfficientFrontier={runEfficientFrontier}
  />
  ```

### 12. `ui/src/components/dashboard/views/modern/ScenarioAnalysisContainer.tsx`

- Import `useEfficientFrontier` from `@risk/connectors`
- Wire hook (~after `useMonteCarlo` destructure):
  ```ts
  const {
    result: efficientFrontierResult,
    isRunning: isEfficientFrontierRunning,
    runEfficientFrontier,
    error: efficientFrontierError,
  } = useEfficientFrontier();
  ```
- Add run handler:
  ```ts
  const handleRunEfficientFrontier = useCallback((params: { nPoints?: number }) => {
    runEfficientFrontier(params);
  }, [runEfficientFrontier]);
  ```
- Pass as props to `<ScenarioAnalysis>`:
  ```tsx
  efficientFrontierResult={efficientFrontierResult}
  isEfficientFrontierRunning={isEfficientFrontierRunning}
  efficientFrontierError={efficientFrontierError}
  onRunEfficientFrontier={handleRunEfficientFrontier}
  ```
- **No** history tracking `useEffect` (history not supported for this scenario type)

## Verification

1. `cd frontend && npx tsc --noEmit` — TypeScript passes
2. Browser: Scenario Analysis → "Efficient Frontier" tab
   - Click "Run" → loading state → chart renders with 10-15 points
   - Current portfolio marker visible on chart
   - Min-variance and max-return endpoints labeled
   - Metric cards show summary stats
3. Re-run with different n_points → cache miss → fresh computation
4. Tab navigation doesn't trigger re-fetch (TanStack Query cache)

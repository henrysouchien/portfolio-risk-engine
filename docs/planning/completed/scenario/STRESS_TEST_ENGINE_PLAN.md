# Scenario Analysis: Stress Test Engine (Wave 3h)

> **Note:** This plan covers the backend stress test engine (Phase 1 of the broader overhaul). The full 5-phase Scenario Analysis overhaul is documented in `completed/SCENARIO_ANALYSIS_OVERHAUL_PLAN.md`.

## Context

The Scenario Analysis view has a **Stress Tests** tab with 6 hardcoded stress scenarios, disabled "Run" buttons, and "Coming soon" messaging. We need to wire real stress test computation.

**Existing backend infrastructure** (in `portfolio_risk_engine/portfolio_risk_score.py`):
- `WORST_CASE_SCENARIOS` in settings.py — centralized loss magnitudes (market_crash: 35%, momentum_crash: 50%, etc.)
- `calculate_factor_risk_loss()` — `portfolio_beta × worst_case_move × leverage_ratio` for market/momentum/value
- `calculate_concentration_risk_loss()` — security-type-aware crash scenarios (equity 80%, ETF 35%, fund 40%, cash 5%)
- `calculate_sector_risk_loss()` — industry proxy betas × worst historical losses
- `calculate_volatility_risk_loss()` — actual vol capped at max reasonable
- `analyze_stress_scenario` — referenced in `service_manager.py` but **never implemented**

**Key data already available from `RiskAnalysisResult`:**
- `portfolio_factor_betas` (Series) — market, growth, value, momentum, interest_rate
- `stock_betas` (DataFrame) — per-position factor exposures
- `volatility_annual` — portfolio vol
- `variance_decomposition` — factor vs idiosyncratic breakdown
- `get_factor_exposures()` — dict version of portfolio betas
- `leverage` — portfolio leverage ratio
- `total_value` — portfolio dollar value

**Approach:** Build `stress_testing.py` that **reuses** the existing factor-beta × shock math pattern from `calculate_factor_risk_loss()` but extends it to: (1) support predefined multi-factor scenarios (not just single-factor worst case), (2) return per-position impact breakdown, (3) return factor contribution breakdown. The existing risk score functions take `max()` across factors (worst single factor for scoring); stress tests use `Σ(beta × shock)` across all simultaneous shocks (scenario simulation). Then wire through API + frontend.

---

## Phase 1: Stress Scenario Catalog + Computation Engine

### New file: `portfolio_risk_engine/stress_testing.py`

**Predefined scenarios** — the 6 existing UI scenarios + 2 bonus from TODO backlog:

```python
STRESS_SCENARIOS = {
    "interest_rate_shock": {
        "name": "Interest Rate Shock",
        "description": "300bp parallel shift in yield curve",
        "severity": "High",
        "shocks": {"interest_rate": 0.03},
    },
    "credit_spread_widening": {
        "name": "Credit Spread Widening",
        "description": "200bp widening in credit spreads",
        "severity": "Medium",
        "shocks": {"interest_rate": 0.02, "market": -0.05},
    },
    "equity_vol_spike": {
        "name": "Equity Volatility Spike",
        "description": "VIX doubles — broad equity selloff",
        "severity": "High",
        "shocks": {"market": -0.15, "momentum": -0.10},
    },
    "currency_devaluation": {
        "name": "Currency Devaluation",
        "description": "25% USD weakening vs major currencies",
        "severity": "Medium",
        "shocks": {"market": -0.03},
    },
    "oil_price_shock": {
        "name": "Oil Price Shock",
        "description": "150% increase in crude oil prices",
        "severity": "Low",
        "shocks": {"market": -0.05, "value": 0.05},
    },
    "correlation_breakdown": {
        "name": "Correlation Breakdown",
        "description": "Diversification failure — all correlations spike to 1",
        "severity": "Extreme",
        "shocks": {"market": -0.25},
    },
    "market_crash": {
        "name": "Market Crash (-20%)",
        "description": "Broad equity decline of 20%",
        "severity": "Extreme",
        "shocks": {"market": -0.20},
    },
    "stagflation": {
        "name": "Stagflation",
        "description": "Rising rates + falling equities + value rotation",
        "severity": "High",
        "shocks": {"market": -0.10, "interest_rate": 0.02, "growth": -0.10, "value": 0.05},
    },
}
```

**Core function — takes `RiskAnalysisResult` directly (reuses existing cached data):**

```python
def run_stress_test(
    risk_result: RiskAnalysisResult,
    shocks: Dict[str, float],
    scenario_name: str = "Custom",
    portfolio_value: Optional[float] = None,
) -> Dict[str, Any]
```

**Math** (same pattern as existing `calculate_factor_risk_loss()`, extended for multi-factor):

Portfolio-level impact includes leverage (consistent with existing `calculate_factor_risk_loss()`):
1. `portfolio_impact = Σ(portfolio_factor_betas[f] × shock[f]) × leverage_ratio` — multi-factor sum (not max like risk score)

Per-position impact (estimated return impact for each position):
2. `position_impact[t] = Σ(stock_betas[t][f] × shock[f])` — each position's estimated return under scenario

Portfolio contribution (how much each position contributes to total portfolio loss):
3. `position_contribution[t] = weight[t] × position_impact[t]` — weighted contribution to portfolio impact
4. Sort positions by impact (worst first)
5. Compute factor contributions to show which shock drives the most impact

**Returns:**
```python
{
    "scenario_name": "Market Crash (-20%)",
    "estimated_portfolio_impact_pct": -18.5,
    "estimated_portfolio_impact_dollar": -21720,
    "position_impacts": [
        {
            "ticker": "AAPL",
            "weight": 0.25,
            "estimated_impact_pct": -23.0,       # position's own return under scenario
            "portfolio_contribution_pct": -5.75,  # weight × impact (contribution to total)
        },
        {
            "ticker": "SGOV",
            "weight": 0.40,
            "estimated_impact_pct": -0.4,
            "portfolio_contribution_pct": -0.16,
        },
    ],
    "factor_contributions": [
        {"factor": "market", "shock": -0.20, "portfolio_beta": 1.02, "contribution_pct": -20.4},
    ],
    "risk_context": {
        "current_volatility": 18.5,
        "leverage_ratio": 1.0,
        "systematic_risk_pct": 61.1,
        "worst_position": {"ticker": "NVDA", "impact_pct": -28.0},
        "best_position": {"ticker": "SGOV", "impact_pct": -0.4},
    }
}
```

Also:
- `get_stress_scenarios()` → returns catalog dict for API consumers
- `run_all_stress_tests(risk_result)` → runs all `STRESS_SCENARIOS`, returns list of results sorted by severity

Data sources from `RiskAnalysisResult`:
- `risk_result.get_factor_exposures()` → portfolio-level factor betas
- `risk_result.stock_betas` → per-position factor betas (DataFrame)
- `risk_result.volatility_annual` → current portfolio volatility
- `risk_result.variance_decomposition` → factor vs idiosyncratic breakdown
- `risk_result.total_value` → portfolio value for dollar impact
- `risk_result.leverage` → leverage ratio for impact scaling

---

## Phase 2: API Endpoints + Service Layer

### 2a. Add `StressTestRequest` / `StressTestResponse` models

Add to `models/response_models.py` (following existing `BacktestRequest`, `WhatIfRequest` patterns):

```python
class StressTestRequest(BaseModel):
    scenario: Optional[str] = None           # predefined scenario ID
    custom_shocks: Optional[Dict[str, float]] = None  # OR custom factor shocks
    portfolio_name: str = "CURRENT_PORTFOLIO"

class StressTestResponse(BaseModel):
    success: bool
    scenario_name: str
    estimated_portfolio_impact_pct: float
    estimated_portfolio_impact_dollar: Optional[float]
    position_impacts: List[Dict[str, Any]]
    factor_contributions: List[Dict[str, Any]]
    risk_context: Dict[str, Any]
```

### 2b. Implement `analyze_stress_scenario()` in `ScenarioService`

Fill the gap in `services/scenario_service.py` — the method is already declared in `service_manager.py` but never implemented:

```python
def analyze_stress_scenario(
    self,
    portfolio_data: PortfolioData,
    scenario: Optional[str] = None,
    custom_shocks: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Run stress test using cached risk analysis."""
    risk_result = self.portfolio_service.analyze_portfolio(portfolio_data)
    shocks = STRESS_SCENARIOS[scenario]["shocks"] if scenario else custom_shocks
    scenario_name = STRESS_SCENARIOS[scenario]["name"] if scenario else "Custom"
    return run_stress_test(risk_result, shocks, scenario_name, risk_result.total_value)
```

### 2c. Add API endpoints to `app.py`

**`POST /api/stress-test`** — run a single stress test:
```json
{"scenario": "market_crash", "portfolio_name": "CURRENT_PORTFOLIO"}
```
Or custom shocks: `{"custom_shocks": {"market": -0.20}, "portfolio_name": "CURRENT_PORTFOLIO"}`

Flow (follows existing `POST /api/what-if` pattern):
1. Load portfolio data via `PortfolioManager.load_portfolio_data()` (same as what-if endpoint)
2. Call `scenario_service.analyze_stress_scenario(portfolio_data, scenario, custom_shocks)`
3. Return `StressTestResponse`

**`GET /api/stress-test/scenarios`** — return predefined scenario catalog.

**`POST /api/stress-test/run-all`** — run all predefined scenarios:

Flow:
1. Load portfolio data + run `analyze_portfolio()` (cached)
2. Call `run_all_stress_tests(risk_result)` — loops through all scenarios
3. Return list of results sorted by estimated impact (worst first)

---

## Phase 3: Frontend Wiring (DETAILED)

Phases 1-2 are complete (committed `d1df3fee`). This section details the frontend implementation.

### 3a. Chassis: Query keys + config

**File: `frontend/packages/chassis/src/queryKeys.ts`** (lines 121-122 for backtest reference)

Add `stressTestKey` and `stressScenarioKey` using existing `scopedMulti` helper:

```typescript
export const stressTestKey = (portfolioId?: string | null, stressTestId?: string | null) =>
  scopedMulti('stressTest', portfolioId, stressTestId);

export const stressScenarioKey = () =>
  ['stressScenarios'] as const;
```

Export from `frontend/packages/chassis/src/index.ts` (add to existing queryKeys re-exports).

**File: `frontend/packages/chassis/src/config/queryConfig.ts`** (lines 250-253 for backtest reference)

Add to `HOOK_QUERY_CONFIG`:

```typescript
useStressTest: {
  staleTime: getStaleTime('reference'),   // 12x base TTL (~60 min) — expensive computation, explicit inputs
  category: 'reference' as const
},
useStressScenarios: {
  staleTime: getStaleTime('reference'),   // catalog is static, cache aggressively
  category: 'reference' as const
},
```

### 3b. Chassis: API types

**File: `frontend/packages/chassis/src/types/api.ts`** (or wherever `BacktestApiResponse` is defined)

Add stress test API response types:

```typescript
export interface StressTestApiResponse {
  success: boolean;
  scenario_name: string;
  estimated_portfolio_impact_pct: number;
  estimated_portfolio_impact_dollar: number | null;
  position_impacts: Array<{
    ticker: string;
    weight: number;
    estimated_impact_pct: number;
    portfolio_contribution_pct: number;
  }>;
  factor_contributions: Array<{
    factor: string;
    shock: number;
    portfolio_beta: number;
    contribution_pct: number;
  }>;
  risk_context: {
    current_volatility: number;
    leverage_ratio: number;
    systematic_risk_pct: number;
    worst_position: { ticker: string; impact_pct: number } | null;
    best_position: { ticker: string; impact_pct: number } | null;
  };
  scenario?: string;     // present in run-all results
  severity?: string;     // present in run-all results
}

export interface StressScenarioInfo {
  name: string;
  description: string;
  severity: string;
  shocks: Record<string, number>;
}

export type StressScenariosApiResponse = Record<string, StressScenarioInfo>;
```

### 3c. Chassis: APIService methods

**File: `frontend/packages/chassis/src/services/APIService.ts`** (lines 658-676 for `postBacktest` reference)

Add 3 methods:

```typescript
async postStressTest(params: {
  scenario?: string;
  customShocks?: Record<string, number>;
}): Promise<StressTestApiResponse> {
  return this.request('/api/stress-test', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      scenario: params.scenario,
      custom_shocks: params.customShocks,
    }),
  });
}

async getStressScenarios(): Promise<StressScenariosApiResponse> {
  return this.request('/api/stress-test/scenarios');
}

async postStressTestRunAll(): Promise<StressTestApiResponse[]> {
  return this.request('/api/stress-test/run-all', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  });
}
```

### 3d. Chassis: PortfolioCacheService method

**File: `frontend/packages/chassis/src/services/PortfolioCacheService.ts`** (lines 499-526 for `getBacktest` reference)

Add `getStressTest` method following the same hash-based dedup pattern:

```typescript
async getStressTest(
  portfolioId: string,
  _portfolio: Portfolio,
  params: { scenario?: string; customShocks?: Record<string, number> }
): Promise<StressTestApiResponse> {
  const repository = this.getRepository();
  const stressHash = this.generateStressTestHash(params);
  const operation = `stressTest_${stressHash}`;

  return this.getOrFetch(portfolioId, operation, async () => {
    try {
      repository.setPortfolioLoading(portfolioId, true);
      return await this.apiService.postStressTest(params);
    } catch (error) {
      repository.setPortfolioError(portfolioId, error instanceof Error ? error.message : 'Stress test failed');
      throw error;
    } finally {
      repository.setPortfolioLoading(portfolioId, false);
    }
  });
}

private generateStressTestHash(params: { scenario?: string; customShocks?: Record<string, number> }): string {
  // Same pattern as generateBacktestHash — deep sort + JSON stringify + base-36 hash
  const sortedParams = JSON.stringify(params, Object.keys(params).sort());
  let hash = 0;
  for (let i = 0; i < sortedParams.length; i++) {
    const chr = sortedParams.charCodeAt(i);
    hash = ((hash << 5) - hash) + chr;
    hash |= 0;
  }
  return Math.abs(hash).toString(36).slice(0, 10);
}
```

### 3e. Connectors: PortfolioManager method

**File: `frontend/packages/connectors/src/managers/PortfolioManager.ts`** (lines 504-534 for `analyzeBacktest` reference)

Add `analyzeStressTest` method:

```typescript
public async analyzeStressTest(params: {
  scenario?: string;
  customShocks?: Record<string, number>;
}): Promise<{ stressTest: StressTestApiResponse | null; error: string | null }> {
  try {
    const storeState = usePortfolioStore.getState();
    const portfolioId = storeState.currentPortfolioId;
    if (!portfolioId) throw new Error('Portfolio not found');

    const portfolio = storeState.byId[portfolioId]?.portfolio;
    if (!portfolio) throw new Error('Portfolio not found');

    const response = await this.portfolioCacheService.getStressTest(portfolioId, portfolio, params);
    if (response && response.success !== false) {
      return { stressTest: response, error: null };
    }
    return { stressTest: null, error: 'Stress test failed' };
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : 'Stress test failed';
    return { stressTest: null, error: errorMessage };
  }
}
```

### 3f. Connectors: StressTestAdapter

**File: `frontend/packages/connectors/src/adapters/StressTestAdapter.ts`** (NEW — mirrors `BacktestAdapter.ts`)

Transforms raw `StressTestApiResponse` into typed UI data. Simpler than `BacktestAdapter` since the API response is already well-structured:

```typescript
export interface PositionImpact {
  ticker: string;
  weight: number;
  estimatedImpactPct: number;
  portfolioContributionPct: number;
}

export interface FactorContribution {
  factor: string;
  shock: number;
  portfolioBeta: number;
  contributionPct: number;
}

export interface StressTestData {
  success: boolean;
  scenarioName: string;
  scenarioId?: string;
  severity?: string;
  estimatedImpactPct: number;
  estimatedImpactDollar: number | null;
  positionImpacts: PositionImpact[];
  factorContributions: FactorContribution[];
  riskContext: {
    currentVolatility: number;
    leverageRatio: number;
    systematicRiskPct: number;
    worstPosition: { ticker: string; impactPct: number } | null;
    bestPosition: { ticker: string; impactPct: number } | null;
  };
  rawResponse: StressTestApiResponse;
}
```

Transform method: camelCase mapping of API response fields. Uses `AdapterRegistry` + `UnifiedAdapterCache` like `BacktestAdapter`.

Cache key: Use `generateContentHash()` + `generateStandardCacheKey()` from chassis (same as `BacktestAdapter.generateCacheKey()` at `BacktestAdapter.ts:206`). Hash content should include `scenario_name`, `estimated_portfolio_impact_pct`, and `factor_contributions` to ensure unique keys per run. Metadata: `{ portfolioId, dataType: 'stressTest', version: 'v1' }`.

### 3g. Connectors: useStressTest hook

**File: `frontend/packages/connectors/src/features/stressTest/hooks/useStressTest.ts`** (NEW — mirrors `useBacktest.ts`)

```typescript
export const useStressTest = () => {
  const { manager, unifiedAdapterCache } = useSessionServices();
  const currentPortfolio = useCurrentPortfolio();

  const [scenarioId, setScenarioId] = useState<string | null>(null);
  const [stressTestRunId, setStressTestRunId] = useState<string | null>(null);

  const stressTestAdapter = useMemo(
    () => AdapterRegistry.getAdapter(
      'stressTest',
      [currentPortfolio?.id || 'default'],
      (cache) => new StressTestAdapter(cache, currentPortfolio?.id || undefined),
      unifiedAdapterCache
    ),
    [currentPortfolio?.id, unifiedAdapterCache]
  );

  // Single scenario query — enabled: false, triggered by runStressTest()
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: stressTestKey(currentPortfolio?.id || 'none', stressTestRunId),
    queryFn: async (): Promise<StressTestData | null> => {
      if (!currentPortfolio || !scenarioId) return null;
      const result = await manager.analyzeStressTest({ scenario: scenarioId });
      if (result.error) throw new Error(result.error);
      if (!result.stressTest) throw new Error('Stress test returned no data');
      return stressTestAdapter.transform(result.stressTest);
    },
    enabled: false,
    staleTime: HOOK_QUERY_CONFIG.useStressTest?.staleTime || 60 * 60 * 1000,
    retry: (failureCount) => failureCount < 2,
  });

  const runStressTest = useCallback((nextScenarioId: string) => {
    const nextRunId = `${nextScenarioId}_${Date.now()}`;
    setScenarioId(nextScenarioId);
    setStressTestRunId(nextRunId);
    setTimeout(() => { void refetch(); }, 0);  // state-then-refetch pattern
  }, [refetch]);

  // Scenario catalog query — auto-fetches, long cache
  // (separate hook or inline useQuery for scenarios)

  return useMemo(() => ({
    data,
    isLoading,
    error: error?.message ?? null,
    hasData: !!data,
    hasPortfolio: !!currentPortfolio,
    runStressTest,
    stressTestRunId,
  }), [data, isLoading, error, currentPortfolio, runStressTest, stressTestRunId]);
};
```

Also export a `useStressScenarios()` hook that auto-fetches `GET /api/stress-test/scenarios` with `staleTime: reference` — this is a simple auto-enabled query.

Re-export both hooks from `frontend/packages/connectors/src/index.ts`.

### 3h. Wire into ScenarioAnalysisContainer

**File: `frontend/packages/ui/src/components/dashboard/views/modern/ScenarioAnalysisContainer.tsx`** (lines 147-171 for what-if wiring reference)

Import and call the hooks:

```typescript
const {
  data: stressTestData,
  isLoading: isStressTesting,
  error: stressTestError,
  runStressTest,
} = useStressTest();

const { data: stressScenarios } = useStressScenarios();
```

Pass as new props to `<ScenarioAnalysis />`:

```typescript
<ScenarioAnalysis
  {...existingProps}
  stressScenarios={stressScenarios}
  stressTestData={stressTestData}
  isStressTesting={isStressTesting}
  stressTestError={stressTestError}
  onRunStressTest={runStressTest}
/>
```

### 3i. Update ScenarioAnalysis.tsx — Stress Tests tab

**File: `frontend/packages/ui/src/components/portfolio/ScenarioAnalysis.tsx`**

**Props interface** — add new stress test props:

```typescript
interface ScenarioAnalysisProps {
  // ...existing props...
  stressScenarios?: Record<string, StressScenarioInfo>;
  stressTestData?: StressTestData | null;
  isStressTesting?: boolean;
  stressTestError?: string | null;
  onRunStressTest?: (scenarioId: string) => void;
}
```

**Replace hardcoded `stressTestFactors`** (lines 376-413) — derive from `stressScenarios` prop. Fall back to hardcoded array if prop not available (graceful degradation).

**Enable Run button** (lines 1346-1354) — remove `disabled`, add `onClick={() => onRunStressTest?.(scenarioId)}`, show loading spinner when `isStressTesting`.

**Add results section** below scenario cards when `stressTestData` is available:
- Portfolio impact banner: "Estimated Impact: -18.5% (-$21,720)"
- Position impacts table: ticker, weight, estimated impact %, portfolio contribution % (sorted worst-first)
- Factor contributions: which shock drives the most impact
- Risk context sidebar: current vol, leverage, systematic risk %, worst/best position

**Remove "Coming soon" banner** (lines 1311-1313) when `onRunStressTest` is provided.

---

## Critical Files (with exact paths)

| File | Action |
|------|--------|
| **PHASE 1-2 (DONE)** | |
| `portfolio_risk_engine/stress_testing.py` | DONE — scenario catalog + computation |
| `models/response_models.py` | DONE — `StressTestRequest`/`StressTestResponse` |
| `services/scenario_service.py` | DONE — `analyze_stress_scenario()` |
| `app.py` | DONE — 3 endpoints |
| `tests/test_stress_testing.py` | DONE — 5 tests passing |
| **PHASE 3 — FRONTEND** | |
| `frontend/packages/chassis/src/queryKeys.ts` | MODIFY — add `stressTestKey`, `stressScenarioKey` |
| `frontend/packages/chassis/src/config/queryConfig.ts` | MODIFY — add `useStressTest`, `useStressScenarios` config |
| `frontend/packages/chassis/src/types/api.ts` | MODIFY — add `StressTestApiResponse`, `StressScenariosApiResponse` types |
| `frontend/packages/chassis/src/services/APIService.ts` | MODIFY — add `postStressTest()`, `getStressScenarios()`, `postStressTestRunAll()` |
| `frontend/packages/chassis/src/services/PortfolioCacheService.ts` | MODIFY — add `getStressTest()` + hash method |
| `frontend/packages/chassis/src/index.ts` | MODIFY — re-export new query keys + types |
| `frontend/packages/connectors/src/adapters/StressTestAdapter.ts` | NEW — API response transformer |
| `frontend/packages/connectors/src/managers/PortfolioManager.ts` | MODIFY — add `analyzeStressTest()` |
| `frontend/packages/connectors/src/features/stressTest/hooks/useStressTest.ts` | NEW — TanStack Query hook |
| `frontend/packages/connectors/src/index.ts` | MODIFY — re-export hooks |
| `frontend/packages/ui/src/components/dashboard/views/modern/ScenarioAnalysisContainer.tsx` | MODIFY — import hooks, pass props |
| `frontend/packages/ui/src/components/portfolio/ScenarioAnalysis.tsx` | MODIFY — wire results, enable Run buttons, add results display |

## Verification
1. ~~Unit test: `tests/test_stress_testing.py`~~ — DONE (5/5 passing)
2. ~~API test: POST single + POST run-all + GET scenarios~~ — DONE
3. `pnpm typecheck` + `pnpm build` — no frontend errors
4. Chrome: Stress Tests tab → select scenario → Run → real impact estimates with position breakdown

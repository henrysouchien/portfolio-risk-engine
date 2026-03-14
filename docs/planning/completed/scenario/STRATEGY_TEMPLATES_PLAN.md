# Strategy Builder — Replace Hardcoded Templates with Real Endpoint

## Context

The Strategy Builder's Marketplace tab shows hardcoded mock strategies with zero-value metrics. Two sources of hardcoded data:

1. **`StrategyBuilderContainer.tsx:208-223`** — 2 templates with generic asset-class allocations (Conservative Growth, Aggressive Growth) passed as `optimizationData.templates`. These are **gated behind `optimizationData`** (line 181: `optimizationData ? (() => { ... })() : undefined`), so templates don't appear until an optimization has been run.
2. **`StrategyBuilder.tsx:313-386`** — 4 `prebuiltStrategies` in `useState` with fake names and all-zero metrics, used as fallback when templates are empty (line 456: `strategies = templatesAsStrategies.length > 0 ? templatesAsStrategies : prebuiltStrategies`)

The optimization, backtest, and what-if engines are all fully wired with real data. Only the templates/marketplace is mock.

**Approach:** Static YAML config file with curated strategy templates using real tickers. One GET endpoint serves them. Frontend fetches via a new `useStrategyTemplates()` hook. Each template includes ticker weights that can be directly backtested via existing infrastructure.

## Existing Code Contracts

Key constraints the plan must respect:

1. **`Strategy.allocation`** (StrategyBuilder.tsx:187-193) is typed as `{stocks, bonds, commodities, cash, alternatives}` — asset classes, NOT ticker weights. The `normalizedAllocation` logic at lines 417-423 reads these keys specifically.
2. **`StrategyBuilderProps.optimizationData.templates`** (line 236-242) has `allocation: Record<string, number | undefined>` — but `templatesAsStrategies` at lines 417-423 reads `.stocks`, `.bonds` etc. from it.
3. **`primaryStrategy`** (line 458) is `activeStrategies[0] ?? strategies[0] ?? prebuiltStrategies[0]` — if all three are empty, it's `undefined`, and line 460 does `primaryStrategy.performance.oneYear` which crashes.
4. **`StrategyConstraint`** (StrategyBuilderContainer.tsx:112-115) only has `type?` and `riskLevel?` — no `weights` field.
5. **`handleBacktest`** (line 274-309) always uses `optimizationData?.weights || {}` for ticker weights, ignoring incoming allocation from the strategy config.
6. **`transformedOptimizationData`** (line 181) is `undefined` when no optimization result exists — this gates templates behind optimization.

## Changes

### 1. Backend: Create strategy templates config + endpoint

#### 1a. `strategy_templates.yaml` (new file, repo root)

Define ~6 curated templates. Each template has: `id`, `name`, `description`, `type`, `risk_level` (1-10), `weights` (ticker weights for backtesting, Dict[str, float] summing to ~1.0), `asset_class_allocation` (asset-class breakdown for UI display, matching Strategy.allocation shape), and `rules`.

```yaml
templates:
  - id: income_plus
    name: "Income Plus"
    type: income
    description: "Dividend-focused strategy emphasizing yield and stability"
    risk_level: 4
    weights:
      ENB: 0.15
      MRP: 0.15
      DSU: 0.20
      CBL: 0.10
      O: 0.10
      VZ: 0.10
      PFE: 0.10
      T: 0.10
    asset_class_allocation:
      stocks: 80
      bonds: 0
      commodities: 0
      cash: 10
      alternatives: 10
    rules:
      rebalance_frequency: quarterly
      max_position_size: 20
      stop_loss: -10
      take_profit: 15

  - id: growth_momentum
    name: "Growth Momentum"
    type: growth
    description: "High-growth equities with momentum factor tilt"
    risk_level: 8
    weights:
      NVDA: 0.20
      AAPL: 0.15
      MSFT: 0.15
      AMZN: 0.10
      META: 0.10
      GOOGL: 0.10
      TSLA: 0.10
      AMD: 0.10
    asset_class_allocation:
      stocks: 100
      bonds: 0
      commodities: 0
      cash: 0
      alternatives: 0
    rules:
      rebalance_frequency: monthly
      max_position_size: 20
      stop_loss: -15
      take_profit: 25

  # ... 4 more templates (balanced, defensive value, sector rotation, real assets)
```

Tickers should be well-known liquid US equities. Templates are starting-point allocations.

#### 1b. `GET /api/strategies/templates` endpoint in `app.py`

Follows existing endpoint patterns (rate limiter, logging, error envelope). Matches `stress_test_scenarios` (app.py:2301-2327).

```python
@app.get("/api/strategies/templates")
@limiter.limit("200 per day;400 per day;1000 per day")
async def get_strategy_templates(
    request: Request,
    user: dict = Depends(get_current_user),
    api_key: str = Depends(get_api_key),
):
    """Return curated strategy templates."""
    user_tier = TIER_MAP.get(api_key, "public")
    try:
        import yaml
        from pathlib import Path

        yaml_path = Path(__file__).parent / "strategy_templates.yaml"
        with open(yaml_path) as f:
            config = yaml.safe_load(f)

        templates = config.get("templates", [])
        log_request("STRATEGY_TEMPLATES", "API", "EXECUTE", api_key, "react", "success", user_tier)
        return {
            "success": True,
            "templates": templates,
            "count": len(templates),
        }
    except Exception as e:
        log_error("STRATEGY_TEMPLATES", "API error", context=str(e), tier=user_tier)
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Failed to load strategy templates",
                "error_code": ErrorCodes.ANALYSIS_ERROR,
                "endpoint": "strategies/templates",
            },
        )
```

No backtest enrichment in v1 — templates serve weights only, user backtests on-demand via existing `POST /api/backtest`.

### 2. Frontend: Add type + API method + hook

#### 2a. Types in `chassis/src/types/index.ts`

```typescript
export interface StrategyTemplateItem {
  id: string;
  name: string;
  type: string;
  description: string;
  risk_level: number;
  weights: Record<string, number>;
  asset_class_allocation: {
    stocks: number;
    bonds: number;
    commodities: number;
    cash: number;
    alternatives: number;
  };
  rules: {
    rebalance_frequency: string;
    max_position_size: number;
    stop_loss: number;
    take_profit: number;
  };
}

export interface StrategyTemplatesApiResponse {
  success: boolean;
  templates: StrategyTemplateItem[];
  count: number;
}
```

#### 2b. API method in `chassis/src/services/APIService.ts`

```typescript
async getStrategyTemplates(): Promise<StrategyTemplatesApiResponse> {
  return this.request('/api/strategies/templates');
}
```

Pattern matches existing methods like `getPortfolioAlerts()` (line 551).

#### 2c. `useStrategyTemplates()` hook (new file)

`frontend/packages/connectors/src/features/optimize/hooks/useStrategyTemplates.ts`

```typescript
import { useQuery } from '@tanstack/react-query';
import { useSessionServices } from '../../../providers/SessionServicesProvider';
import type { StrategyTemplatesApiResponse } from '@risk/chassis';

export const useStrategyTemplates = () => {
  const { api } = useSessionServices();
  return useQuery<StrategyTemplatesApiResponse>({
    queryKey: ['strategy-templates'],
    queryFn: () => api.getStrategyTemplates(),
    staleTime: 30 * 60 * 1000,  // 30 min — templates rarely change
  });
};
```

#### 2d. Barrel exports (3 files)

**`connectors/src/features/optimize/hooks/index.ts`** — add:
```typescript
export { useStrategyTemplates } from './useStrategyTemplates';
```

**`connectors/src/features/optimize/index.ts`** — already re-exports `from './hooks'`, so no change needed.

**`connectors/src/index.ts`** — add to the optimize line:
```typescript
export { usePortfolioOptimization, useStrategyTemplates } from './features/optimize';
```

### 3. Frontend: Wire templates into Strategy Builder

#### 3a. `StrategyBuilder.tsx` — Make `optimizationData` inner fields optional + add `tickerWeights`

The `StrategyBuilderProps.optimizationData` type (lines 208-243) has `currentStrategy` and `optimizedStrategy` as required fields. Make them optional so templates can be passed without optimization data:

```typescript
optimizationData?: {
  currentStrategy?: {          // ← was required, now optional
    allocation: Record<string, number | undefined>;
    metrics: { ... };
    riskLevel: string;
  };
  optimizedStrategy?: {        // ← was required, now optional
    allocation: Record<string, number | undefined>;
    expectedReturn: number;
    expectedRisk: number;
    improvementMetrics: { ... };
  };
  backtestResults: Array<{ ... }>;
  templates: Array<{
    id: string;
    name: string;
    description: string;
    riskLevel: 'Conservative' | 'Moderate' | 'Aggressive';
    allocation: Record<string, number | undefined>;
    tickerWeights?: Record<string, number>;    // ← NEW: for backtest
  }>;
};
```

The inner component already uses optional chaining on `optimizationData?.currentStrategy?.metrics` (line 388) and `optimizationData?.optimizedStrategy` (line 389), so making the types optional matches existing access patterns.

#### 3b. `StrategyBuilder.tsx` — Keep prebuiltStrategies as non-empty fallback

**Do NOT empty `prebuiltStrategies`**. Line 458: `primaryStrategy = activeStrategies[0] ?? strategies[0] ?? prebuiltStrategies[0]` — if all three resolve to `undefined`, line 460 does `primaryStrategy.performance.oneYear` which crashes. `prebuiltStrategies` is the last-resort safety net.

**Instead**: Replace the 4 fake strategies with 2 minimal placeholder strategies that clearly indicate they're defaults:

```typescript
const [prebuiltStrategies] = useState<Strategy[]>([
  {
    id: "placeholder-1",
    name: "Run Optimization to See Strategies",
    type: "balanced",
    description: "Use the Marketplace tab to browse strategy templates, or run an optimization first",
    riskLevel: 5,
    expectedReturn: 0, volatility: 0, sharpeRatio: 0, maxDrawdown: 0,
    minimumInvestment: 0,
    status: "draft",
    performance: { ytd: 0, oneYear: 0, threeYear: 0, inception: 0 },
    allocation: { stocks: 60, bonds: 30, commodities: 5, cash: 5, alternatives: 0 },
    rules: { rebalanceFrequency: "quarterly", maxPositionSize: 10, stopLoss: -15, takeProfitTarget: 25 },
    createdDate: new Date(), lastRebalance: new Date()
  }
]);
```

#### 3c. `StrategyBuilder.tsx` — Update `templatesAsStrategies` mapping

Remove hardcoded fallback metrics. Templates from the API have no backtest metrics — set to 0 honestly. Use `asset_class_allocation` for the allocation field (matching Strategy type) and thread `tickerWeights` separately.

Replace lines 398-454:

```typescript
const templatesAsStrategies: Strategy[] = (() => {
  if (!optimizationData?.templates || optimizationData.templates.length === 0) {
    return [];
  }

  return optimizationData.templates.map((template, index) => {
    const normalizedRiskLevel = template.riskLevel.toLowerCase();
    const mappedType: Strategy["type"] =
      normalizedRiskLevel === "aggressive" ? "growth"
        : normalizedRiskLevel === "moderate" ? "balanced"
        : "income";
    const mappedRiskLevel = normalizedRiskLevel === "aggressive" ? 8
      : normalizedRiskLevel === "moderate" ? 6 : 4;

    // Use asset-class allocation from template (matches Strategy.allocation type)
    const normalizedAllocation = {
      stocks: Number(template.allocation.stocks ?? template.allocation.Stocks ?? 0),
      bonds: Number(template.allocation.bonds ?? template.allocation.Bonds ?? 0),
      commodities: Number(template.allocation.commodities ?? template.allocation.Commodities ?? 0),
      cash: Number(template.allocation.cash ?? template.allocation.Cash ?? 0),
      alternatives: Number(template.allocation.alternatives ?? template.allocation.Alternatives ?? 0),
    };

    return {
      id: template.id,
      name: template.name,
      type: mappedType,
      description: template.description,
      riskLevel: mappedRiskLevel,
      expectedReturn: 0,    // No backtest yet — honest zeros
      volatility: 0,
      sharpeRatio: 0,
      maxDrawdown: 0,
      minimumInvestment: 0,
      status: index === 0 ? "active" as const : "draft" as const,
      performance: { ytd: 0, oneYear: 0, threeYear: 0, inception: 0 },
      allocation: normalizedAllocation,
      rules: {
        rebalanceFrequency: "quarterly" as const,
        maxPositionSize: 10,
        stopLoss: -15,
        takeProfitTarget: 25,
      },
      createdDate: new Date(),
      lastRebalance: new Date(),
    };
  });
})();
```

Note: `template.allocation` now receives `asset_class_allocation` from the API (container maps it — see 3e). The `normalizedAllocation` code reads `.stocks`, `.bonds`, etc. which matches the `asset_class_allocation` shape.

#### 3d. `StrategyBuilder.tsx` — Wire Deploy button to pass ticker weights

The Deploy button at lines 1003-1016 currently passes `{type, riskLevel}` to `onOptimize`. We need to also pass `tickerWeights` so the container can route to backtest.

First, find the template's ticker weights. The `strategies` array doesn't have ticker weights (Strategy type has no such field). Instead, look up the original template by id:

```typescript
onClick={() => {
  if (!onOptimize) return;
  // Find ticker weights from the original template (not the Strategy object)
  const sourceTemplate = optimizationData?.templates?.find(t => t.id === strategy.id);
  onOptimize({
    type: strategy.type === "growth" || strategy.type === "momentum" ? "max_return" : "min_variance",
    riskLevel: strategy.riskLevel >= 7 ? "aggressive" : strategy.riskLevel >= 5 ? "moderate" : "conservative",
    weights: sourceTemplate?.tickerWeights,
  });
}}
```

#### 3e. `StrategyBuilderContainer.tsx` — Decouple templates from optimization state

**This is the critical fix for Finding 5.** Currently `transformedOptimizationData` is `undefined` when no optimization result exists (line 181), which gates templates.

Import and call the hook:
```typescript
const { data: templatesData } = useStrategyTemplates();
```

Build the template array independently:
```typescript
const templatesProp = (templatesData?.templates || []).map(t => ({
  id: t.id,
  name: t.name,
  description: t.description,
  riskLevel: t.risk_level <= 3 ? 'Conservative' as const
    : t.risk_level <= 6 ? 'Moderate' as const : 'Aggressive' as const,
  allocation: t.asset_class_allocation,   // Asset-class breakdown for Strategy.allocation
  tickerWeights: t.weights,               // Ticker weights for backtest
}));
```

Change `transformedOptimizationData` to always be defined when templates exist:

```typescript
const transformedOptimizationData: React.ComponentProps<typeof StrategyBuilder>['optimizationData'] =
  (optimizationData || templatesProp.length > 0) ? (() => {
    const base = {
      backtestResults: backtestRows,
      templates: templatesProp,
    };

    if (!optimizationData) return base;  // Templates only, no optimization yet

    const optimizationResults = toRecord(optimizationData.optimization_results);
    const summary = toRecord(optimizationData.summary);

    return {
      ...base,
      currentStrategy: {
        allocation: optimizationData.weights || {},
        metrics: {
          expectedReturn: toNumber(optimizationResults.expected_return, 0),
          volatility: toNumber(optimizationResults.expected_risk, 0),
          sharpeRatio: toNumber(optimizationResults.sharpe_ratio, 0),
          maxDrawdown: toNumber(optimizationResults.max_drawdown, -12.4),
        },
        riskLevel: strategy === 'min_variance' ? 'Conservative' : 'Aggressive'
      },
      optimizedStrategy: {
        allocation: optimizationData.weights || {},
        expectedReturn: toNumber(optimizationResults.expected_return, 0),
        expectedRisk: toNumber(optimizationResults.expected_risk, 0),
        improvementMetrics: {
          returnImprovement: toNumber(summary.return_improvement, 0),
          riskReduction: toNumber(summary.risk_reduction, 0),
          sharpeImprovement: toNumber(summary.sharpe_improvement, 0),
        }
      },
    };
  })() : undefined;
```

#### 3f. `StrategyBuilderContainer.tsx` — Extend `StrategyConstraint` and wire weights through handleOptimize

Extend `StrategyConstraint` (line 112-115):
```typescript
interface StrategyConstraint {
  type?: string;
  riskLevel?: string;
  weights?: Record<string, number>;  // NEW: ticker weights from template
}
```

Update `parseConstraint` (line 127-133) to extract weights:
```typescript
const parseConstraint = (value: unknown): StrategyConstraint => {
  const record = toRecord(value);
  const rawWeights = record.weights;
  return {
    type: typeof record.type === 'string' ? record.type : undefined,
    riskLevel: typeof record.riskLevel === 'string' ? record.riskLevel : undefined,
    weights: (rawWeights && typeof rawWeights === 'object' && !Array.isArray(rawWeights))
      ? toNumberRecord(rawWeights)
      : undefined,
  };
};
```

Update `handleOptimize` (line 238-271) to detect weights and route to backtest:
```typescript
const handleOptimize = async (constraints: unknown) => {
  try {
    const parsedConstraints = parseConstraint(constraints);

    // If ticker weights provided (from template Deploy), route directly to backtest
    if (parsedConstraints.weights && Object.keys(parsedConstraints.weights).length > 0) {
      frontendLogger.user.action('template-deployed', 'StrategyBuilderContainer', {
        weightsCount: Object.keys(parsedConstraints.weights).length,
      });
      backtest.runBacktest({
        weights: parsedConstraints.weights,
        benchmark: 'SPY',
        period: '3Y',
      });
      return;
    }

    // Otherwise, run optimization as before
    const constraintType = parsedConstraints.type || 'min_variance';
    const riskLevel = parsedConstraints.riskLevel || 'moderate';

    const optimizeResult = await IntentRegistry.triggerIntent('optimize-portfolio', {
      constraintsType: constraintType,
      riskLevel,
      strategy: strategy
    });

    frontendLogger.user.action('portfolio-optimized', 'StrategyBuilderContainer', {
      constraintsType: constraintType,
      riskLevel,
      currentStrategy: strategy,
      intentTriggered: optimizeResult.success
    });

    if (constraintType === 'min_variance') {
      optimizeMinVariance();
    } else if (constraintType === 'max_return') {
      optimizeMaxReturn();
    } else {
      optimizeMinVariance();
    }
  } catch (optimizationError) {
    frontendLogger.error('Failed to optimize portfolio', 'StrategyBuilderContainer', optimizationError as Error);
  }
};
```

## Files to Modify

| File | Change |
|------|--------|
| `strategy_templates.yaml` (NEW) | 6 curated templates with real ticker weights + asset-class allocations |
| `app.py` | Add `GET /api/strategies/templates` endpoint with limiter, logging, error envelope |
| `frontend/packages/chassis/src/types/index.ts` | Add `StrategyTemplateItem` + `StrategyTemplatesApiResponse` |
| `frontend/packages/chassis/src/services/APIService.ts` | Add `getStrategyTemplates()` method |
| `frontend/packages/connectors/src/features/optimize/hooks/useStrategyTemplates.ts` (NEW) | TanStack Query hook |
| `frontend/packages/connectors/src/features/optimize/hooks/index.ts` | Add export for `useStrategyTemplates` |
| `frontend/packages/connectors/src/index.ts` | Add `useStrategyTemplates` to optimize export line |
| `frontend/packages/ui/.../StrategyBuilderContainer.tsx` | Import hook, decouple templates from optimization state, extend `StrategyConstraint` + `parseConstraint` + `handleOptimize` to handle ticker weights |
| `frontend/packages/ui/.../StrategyBuilder.tsx` | Make `currentStrategy`/`optimizedStrategy` optional in props, add `tickerWeights` to template type, reduce `prebuiltStrategies` to 1 placeholder, remove hardcoded fallback metrics from `templatesAsStrategies`, wire Deploy to pass `tickerWeights` |

## Key Design Decisions

1. **YAML config, not DB** — Templates are curated content, not user-generated. Easy to review, version, deploy. No migration needed.
2. **Dual allocation fields** — Each template has `weights` (real ticker weights for backtest) and `asset_class_allocation` (for display in the Strategy.allocation UI). This respects the existing `Strategy.allocation` type contract (`{stocks, bonds, commodities, cash, alternatives}`) while enabling real backtesting.
3. **No pre-computed backtest in v1** — Backtesting on-demand when user clicks Deploy. Keeps endpoint instant, avoids stale metrics. Metrics show honest 0 until backtested.
4. **prebuiltStrategies kept as non-empty safety net** — Reduced to 1 placeholder, NOT emptied. Guards against `primaryStrategy` being `undefined` at line 458 which would crash on `.performance.oneYear`.
5. **Templates decoupled from optimization state** — `transformedOptimizationData` is now built when EITHER optimization data OR templates exist. Templates appear in Marketplace immediately, no optimization required first.
6. **Deploy → backtest routing** — When a template has `tickerWeights`, the Deploy button passes them through `onOptimize`. Container detects weights and routes to `backtest.runBacktest()` instead of optimization. Existing optimization flow unchanged when no weights present.
7. **30-min staleTime** — Templates rarely change. One fetch per session.
8. **Backend patterns** — Endpoint includes `@limiter.limit`, `log_request`, try/except with `HTTPException` error envelope, matching `stress_test_scenarios` pattern.

## Verification

1. `python3 -m py_compile app.py` passes
2. `cd frontend && pnpm exec tsc --noEmit -p packages/ui/tsconfig.json` passes
3. `curl http://localhost:5001/api/strategies/templates` returns JSON with 6 templates, `success: true`, `count: 6`
4. Frontend Marketplace tab shows template cards immediately (without running optimization first)
5. Cards show honest 0 for metrics, real names/descriptions/risk levels
6. Clicking "Deploy" triggers backtest with the template's ticker weights (not optimization)
7. Backtest results appear in the Backtest tab with real historical performance
8. If API endpoint fails, Marketplace falls back to placeholder strategy (not broken mock data)

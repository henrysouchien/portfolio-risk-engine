# Hedging Workflow — Phase 4 Implementation Plan

**Status**: COMPLETE — implemented in commit `18aa43ae`

## Context

The hedging tab (inside Risk Analysis view) shows real hedge recommendations from `useHedgingRecommendations()` → `/api/factor-intelligence/portfolio-recommendations`. However, clicking "Implement Strategy" opens a **simulation-only** dialog — a fake 1.2s timer steps through hardcoded steps, VaR/beta show "N/A", and no trades execute. Phase 4 replaces this with a real multi-step workflow that previews impact via what-if analysis and executes trades.

## Approach

- **Keep hedging as a tab** in Risk Analysis (no navigation changes)
- **Add 2 REST endpoints** wrapping existing core services (ScenarioService, TradeExecutionService)
- **Extract the dialog** into `HedgeWorkflowDialog.tsx` with 4 real steps
- **Add 3 hooks** (`useHedgePreview`, `useHedgeTradePreview`, `useHedgeTradeExecute`) as TanStack mutations

## Changes

### 1. Backend: `routes/hedging.py` (NEW)

Two endpoints wrapping existing services. Auth via `get_current_user`. Register `hedging_router` in `app.py`.

**`POST /api/hedging/preview`** — Hedge impact preview
- Request: `{ hedge_ticker: str, suggested_weight: float }`
- **Do NOT call `_load_portfolio_for_analysis()`** — that helper is MCP-scoped (resolves user from env, has MCP-specific side effects). Instead, replicate the portfolio loading pattern inline in the route:
  1. Get `user_email` from `get_current_user` dependency
  2. Create `PositionService(user_email)` → `get_all_positions(consolidate=True)`
  3. Build `PortfolioData` via `positions_data.to_portfolio_data(portfolio_name="CURRENT_PORTFOLIO")`
  4. Set `portfolio_data.user_id` from auth user
  5. Call `ensure_factor_proxies()` (same as `portfolio_service.py:767-775`)
- Convert `suggested_weight` to `delta_changes`: `{hedge_ticker: f"+{suggested_weight*100}%"}`
- Load `RiskLimitsManager` (same pattern as `mcp_tools/whatif.py:126-151`). If no risk limits found, return `{"status": "error", "error": "Risk limits not configured"}`.
- Call `ScenarioService(cache_results=True).analyze_what_if(portfolio_data, delta_changes=..., risk_limits_data=...)`
- Extract from `WhatIfResult`:
  - `get_summary()` returns `scenario_name`, `volatility_change.current/scenario/delta`, `concentration_change.current/scenario/delta`, `factor_variance_change.current/scenario/delta`, `risk_improvement`, `concentration_improvement` (see `core/result_objects/whatif.py:176-197`)
  - `portfolio_factor_betas` from `result.current_metrics.portfolio_factor_betas.to_dict()` and `result.scenario_metrics.portfolio_factor_betas.to_dict()` — extract `"market"` key for beta (see `core/result_objects/whatif.py:351-352`)

Response shape (from `WhatIfResult.get_summary()` + derived beta from `portfolio_factor_betas`):
```json
{
  "status": "success",
  "volatility_change": { "current": 0.1842, "scenario": 0.1623, "delta": -0.0219 },
  "concentration_change": { "current": 0.052, "scenario": 0.049, "delta": -0.003 },
  "beta_change": { "current": 1.12, "scenario": 0.98, "delta": -0.14 },
  "risk_improvement": true,
  "concentration_improvement": true,
  "hedge_ticker": "XLU",
  "suggested_weight": 0.05
}
```

**`POST /api/hedging/execute`** — Trade preview or execution (single endpoint, `action` discriminator in body)
- Request shape varies by `action`:
  - `action="preview"`: `{ hedge_ticker: str, suggested_weight: float, account_id: str, action: "preview" }` — all fields required
  - `action="execute"`: `{ action: "execute", preview_ids: str[] }` — only `preview_ids` required
- The frontend wraps this with two separate API methods (`executeHedgePreview` / `executeHedgeTrades`) that each POST to the same endpoint with different `action` values and field sets.
- Gate: Check `TRADING_ENABLED` at route level (imported from `settings.py`). Return 400 with `"Trading is disabled"` if false.
- **Do NOT call the MCP-wrapped `preview_rebalance_trades()`** — it uses `@handle_mcp_errors` (stdout swapping). Instead, replicate the core logic inline in the route:
  1. `PositionService(user_email)` → `get_all_positions(consolidate=True, account=account_id)` (same as `rebalance.py:121-127`)
  2. Build `position_values`, `held_quantities`, `current_weights` (same as `rebalance.py:133-160`)
  3. Apply `weight_changes={hedge_ticker: suggested_weight}` to `current_weights` (same as `rebalance.py:173-186`)
  4. `fetch_current_prices()` + `compute_rebalance_legs()` (from `mcp_tools/trading_helpers.py`)
  5. If `preview=True`: call `TradeExecutionService(user).preview_order()` per leg (same as `rebalance.py:233-261`)
- `action="execute"`: `preview_ids` is **required** (not optional). Call `TradeExecutionService(user).execute_order(preview_id=id)` per id. Return per-leg results.
- **`account_id` is required** when `action="preview"` (trade preview needs an account for routing). Frontend must pass it. If not provided, return 400 error.

### 2. Frontend Types: `chassis/src/types/index.ts`

Add after `PortfolioHedgingResponse`:
```typescript
export interface HedgePreviewResponse {
  status: string;
  volatility_change: { current: number; scenario: number; delta: number };
  concentration_change: { current: number; scenario: number; delta: number };
  beta_change: { current: number; scenario: number; delta: number };
  risk_improvement: boolean;
  concentration_improvement: boolean;
  hedge_ticker: string;
  suggested_weight: number;
}

export interface HedgeTradeLeg {
  ticker: string;
  side: 'BUY' | 'SELL';
  quantity: number;
  estimated_value: number;
  price: number;
  preview_id?: string;
  error?: string;
}

export interface HedgeExecutePreviewResponse {
  status: string;
  trades: HedgeTradeLeg[];
  summary: { trade_count: number; sell_count: number; buy_count: number; net_cash_impact: number };
  warnings: string[];
}

export interface HedgeExecuteResult {
  status: string;
  results: Array<{ ticker: string; side: string; quantity: number; order_id?: string; error?: string }>;
}
```

### 3. Frontend API: `chassis/src/services/APIService.ts`

Add 2 methods:
```typescript
async getHedgePreview(hedgeTicker: string, suggestedWeight: number): Promise<HedgePreviewResponse>

// Overloaded: preview requires accountId, execute requires previewIds
async executeHedgePreview(params: {
  hedgeTicker: string;
  suggestedWeight: number;
  accountId: string;           // Required for trade preview
}): Promise<HedgeExecutePreviewResponse>

async executeHedgeTrades(params: {
  previewIds: string[];        // Required for trade execution
}): Promise<HedgeExecuteResult>
```

### 4. Frontend Adapter: `connectors/src/adapters/HedgingAdapter.ts`

Add to `HedgeStrategy` interface:
```typescript
hedgeTicker: string;       // e.g. "XLU" — from recommendation.label
suggestedWeight: number;   // e.g. 0.05 — from recommendation.suggested_weight (default 0.05 if missing)
```

Populate in `transform()`:
- `suggestedWeight`: from `bestRecommendation.suggested_weight ?? 0.05`
- `hedgeTicker`: extract raw ticker from `bestRecommendation.label`. Labels come from the correlation matrix which uses `labels_map` (`core/factor_intelligence.py:850-857`). Format is either raw ticker (`"XLU"`) or `"Name (TICKER)"` (e.g., `"Utilities (XLU)"`). Extract with: `label.includes('(') ? label.match(/\(([^)]+)\)/)?.[1] ?? label : label`.

**Why `label` needs parsing**: The factor intelligence engine applies `labels_map` to correlation matrix keys (`core/factor_intelligence.py:854`), mapping tickers to display labels like `"Market (SPY)"`, `"UST 10Y (IEF)"`, `"Gold (GLD)"`. For portfolio holdings without a mapping, label = ticker. The `recommend_offsets` method (`factor_intelligence_service.py:960`) emits these display labels as `recommendation.label`. The raw ticker is embedded in parentheses when a mapping exists.

### 5. Frontend Hooks (NEW files in `connectors/src/features/hedging/hooks/`)

**`useHedgePreview.ts`** — `useMutation` calling `api.getHedgePreview(ticker, weight)`. Returns `{ mutate, data, isPending, error }`.

**`useHedgeTrade.ts`** — Two mutations:
- `useHedgeTradePreview()` — `useMutation` calling `api.executeHedgePreview({ hedgeTicker, suggestedWeight, accountId })`. Returns `{ mutate, data: HedgeExecutePreviewResponse, isPending, error }`.
- `useHedgeTradeExecute()` — `useMutation` calling `api.executeHedgeTrades({ previewIds })`. Returns `{ mutate, data: HedgeExecuteResult, isPending, error }`.

Export from `features/hedging/index.ts` and `connectors/src/index.ts`.

### 6. Frontend UI: `HedgeWorkflowDialog.tsx` (NEW)

**Location**: `frontend/packages/ui/src/components/portfolio/HedgeWorkflowDialog.tsx`

**Props**: `{ strategy: HedgeStrategy | null, open: boolean, onOpenChange: (open: boolean) => void }`

4-step workflow dialog (replaces simulation modal):

| Step | Name | Data Source | UI |
|------|------|------------|-----|
| 1 | **Review** | `HedgeStrategy` props (already loaded) | Risk driver, hedge ticker, correlation, suggested weight, efficiency badge |
| 2 | **Impact** | `useHedgePreview` mutation (fires on step entry) | Before/after grid: volatility (current→scenario), beta (current→scenario), concentration (current→scenario). Green delta = improvement, red = worsening |
| 3 | **Trades** | `useHedgeTradePreview` mutation | Account selector (required), trade legs table (ticker, side, qty, value). Warnings. Net cash impact |
| 4 | **Execute** | `useHedgeTradeExecute` mutation | Per-leg status (success/error). Completion summary |

Step indicator bar at top (4 circles connected by lines, current step highlighted).
Back/Continue/Execute/Done buttons per step. Dialog reset on close.

**Account selection**: Step 3 requires `account_id` for trade preview. Display an account selector populated from user's connected accounts. If only one account, auto-select it.

**TRADING_ENABLED=false handling**: If trading is disabled, Steps 3-4 show a message: "Trading is not enabled. Contact admin to enable trade execution." The Impact Preview (Step 2) still works regardless.

### 7. Frontend Refactor: `RiskAnalysis.tsx`

- **Remove**: `implementingHedge`, `implementationStep`, `isImplementing`, `implementationComplete` state variables (lines ~248-256)
- **Remove**: `handleImplementStrategy()`, `executeImplementation()`, `resetImplementation()` functions (lines ~440-477)
- **Remove**: Inline `<Dialog>` block (lines ~677-931) — ~250 lines
- **Add**: `const [selectedHedge, setSelectedHedge] = useState<HedgeStrategy | null>(null)`
- **Add**: `<HedgeWorkflowDialog strategy={selectedHedge} open={!!selectedHedge} onOpenChange={...} />`
- **Change**: "Implement Strategy" button → `onClick={() => setSelectedHedge(hedge)}`

Net effect: ~250 lines removed from RiskAnalysis.tsx, ~300 lines in new HedgeWorkflowDialog.tsx.

## Files Modified

| File | Change |
|------|--------|
| `routes/hedging.py` | **NEW** — 2 REST endpoints wrapping ScenarioService + TradeExecutionService |
| `app.py` | Register `hedging_router` |
| `frontend/packages/chassis/src/types/index.ts` | Add hedge preview/execute response types |
| `frontend/packages/chassis/src/services/APIService.ts` | Add `getHedgePreview()` + `executeHedgePreview()` + `executeHedgeTrades()` |
| `frontend/packages/connectors/src/adapters/HedgingAdapter.ts` | Add `hedgeTicker`, `suggestedWeight` to HedgeStrategy |
| `frontend/packages/connectors/src/features/hedging/hooks/useHedgePreview.ts` | **NEW** — useMutation hook |
| `frontend/packages/connectors/src/features/hedging/hooks/useHedgeTrade.ts` | **NEW** — `useHedgeTradePreview` + `useHedgeTradeExecute` mutation hooks |
| `frontend/packages/connectors/src/features/hedging/index.ts` | Re-export new hooks |
| `frontend/packages/connectors/src/index.ts` | Re-export new hooks |
| `frontend/packages/ui/src/components/portfolio/HedgeWorkflowDialog.tsx` | **NEW** — 4-step workflow dialog |
| `frontend/packages/ui/src/components/portfolio/RiskAnalysis.tsx` | Remove simulation state/dialog, integrate HedgeWorkflowDialog |

## Key Design Decisions

1. **useMutation not useQuery** — Impact preview and execution are user-triggered actions, not page-load data
2. **Extract dialog into own component** — RiskAnalysis.tsx is 942 lines; the workflow dialog adds significant logic
3. **Purpose-built `/api/hedging/` endpoints** — Thinner and more targeted than exposing generic what-if/trading REST APIs. Same core services underneath.
4. **Package boundaries** — Types in `@risk/chassis`, hooks in `@risk/connectors`, UI in `@risk/ui`. Follows existing rules.

## Codex v1 Findings (Addressed in v2)

1. **`_load_portfolio_for_analysis()` is MCP-scoped** — has MCP-specific user resolution via env vars. **Fix**: Route replicates portfolio loading inline using `PositionService(user_email)` from auth context, same as `portfolio_service.py:755-765`.
2. **`preview_rebalance_trades()` wrapped in `@handle_mcp_errors`** — stdout swapping is wrong for route context. **Fix**: Route replicates core rebalance logic inline using the same helpers (`compute_rebalance_legs`, `fetch_current_prices` from `trading_helpers.py`).
3. **`WhatIfResult.get_summary()` fields incorrect** — Plan claimed `before/after` with `volatility/portfolio_beta/hhi` but actual fields are `volatility_change.current/scenario/delta`, `concentration_change`, etc. Beta is not in `get_summary()` — it's in `result.current_metrics.portfolio_factor_betas`. **Fix**: Updated response shape to match actual `WhatIfResult` structure. Beta extracted separately from factor betas dict.
4. **`account_id` required for trade preview** — `rebalance.py:91` enforces `account_id` when `preview=True`. **Fix**: Made `account_id` required in execute endpoint. Frontend shows account selector in Step 3.
5. **`preview_ids` required for execution** — Can't execute without preview IDs. **Fix**: Made `preview_ids` required when `action="execute"`.
6. **`label` may not be a tradable ticker** — Factor intelligence returns ETF tickers as labels, which are tradable. **Fix**: Added note explaining label semantics + graceful error path.
7. **`TRADING_ENABLED` not enforced by service** — Route must check explicitly. **Fix**: Route checks `TRADING_ENABLED` (from `settings.py`) and returns 400 if disabled.

## Codex v2 Findings (Addressed in v3)

1. **High: `label` is display-mapped, not raw ticker** — `labels_map` in `core/factor_intelligence.py:850-857` renames correlation matrix keys to display labels like `"Market (SPY)"`, `"UST 10Y (IEF)"`. `recommend_offsets` emits these as `recommendation.label`. **Fix**: Adapter parses raw ticker from label using regex: `label.includes('(') ? label.match(/\(([^)]+)\)/)?.[1] : label`. Added explanation of label format.
2. **Medium: beta key is `"market"` not `"Mkt-RF"`** — Code consistently uses `"market"` for portfolio beta (e.g., `factor_intelligence_service.py:1155`, `portfolio_service.py:162`). **Fix**: Changed all references from `"Mkt-RF"` to `"market"`.
3. **Medium: frontend API types don't enforce required params** — `accountId` and `previewIds` were optional in the API method signature despite being required. **Fix**: Split into two separate methods: `executeHedgePreview(params: { hedgeTicker, suggestedWeight, accountId })` and `executeHedgeTrades(params: { previewIds })` with required params.

## Key Reference Files

| File | What to reference |
|------|-------------------|
| `mcp_tools/whatif.py:67-169` | `run_whatif()` — full what-if flow: load portfolio, load risk limits, call ScenarioService |
| `mcp_tools/trading.py:36-72` | `preview_trade()` + `execute_trade()` — TradeExecutionService calls |
| `mcp_tools/rebalance.py` | `preview_rebalance_trades()` — weight changes → trade legs |
| `mcp_tools/risk.py` | `_load_portfolio_for_analysis()` — shared helper for loading portfolio data |
| `services/scenario_service.py` | `ScenarioService.analyze_what_if()` — core scenario engine |
| `services/trade_execution_service.py` | `TradeExecutionService` — preview + execute |
| `routes/factor_intelligence.py:161-180` | Existing hedging endpoint pattern (auth, rate limiting) |
| `frontend/packages/connectors/src/features/hedging/hooks/useHedgingRecommendations.ts` | Existing hook pattern (TanStack, retry, error handling) |
| `frontend/packages/connectors/src/adapters/HedgingAdapter.ts` | Existing adapter + HedgeStrategy interface |
| `frontend/packages/ui/src/components/portfolio/RiskAnalysis.tsx:637-931` | Current hedging tab + simulation dialog to replace |

## Verification

1. `python3 -m py_compile routes/hedging.py` passes
2. `cd frontend && pnpm exec tsc --noEmit -p packages/ui/tsconfig.json` passes
3. Open Risk Analysis → Hedging tab → click "Implement Strategy"
4. Step 1 (Review): Shows hedge recommendation details from real data
5. Step 2 (Impact): Loading spinner → real before/after metrics from `/api/hedging/preview`
6. Step 3 (Trades): Real trade legs from `POST /api/hedging/execute` with `action="preview"` in body
7. Step 4 (Execute): Executes trades if `TRADING_ENABLED=true`, shows error message if disabled
8. Dialog close + reopen resets to Step 1
9. Backend: `curl -X POST localhost:5001/api/hedging/preview -H "Content-Type: application/json" -d '{"hedge_ticker":"XLU","suggested_weight":0.05}'` returns real metrics

# Wave 3: Scenario & Strategy Builder — Real Data Wiring

**Date**: 2026-03-02
**Status**: COMPLETE (Phase A + A-6 implemented, Phase B deferred, Phase C documented as backlog)
**Depends on**: Wave 1 (✅), Wave 2 (✅)

## Problem

ScenarioAnalysis.tsx (1648 lines) and StrategyBuilder.tsx (1145 lines) contain massive blocks of mock data. The **containers are correctly wired** to real backend hooks (`useWhatIfAnalysis()`, `usePortfolioOptimization()`), but:

- **ScenarioAnalysis.tsx** destructures all container props with underscore prefixes (`_data`, `_onRunScenario`, `_loading`) and **never references them**. It runs entirely on internal mock state.
- **StrategyBuilder.tsx** partially uses `optimizationData` props (lines 381-451) but falls back to fake prebuilt strategies and has its own mock backtest execution.

### Misleading Mock Data Inventory

| Item | File | Severity | Backend Ready? |
|------|------|----------|---------------|
| Demo positions (AAPL $182, MSFT $341, etc.) | ScenarioAnalysis:327 | High | Yes — `usePositions()` |
| Mock pricing (`Math.random() * 200 + 50`) | ScenarioAnalysis:515 | Critical | Yes — reuse `/api/portfolio/refresh-prices` |
| Fake optimization generator (random weights) | ScenarioAnalysis:653 | High | Partial — what-if returns position_changes |
| Fake risk metrics (VaR $142K, Sharpe 0.67) | ScenarioAnalysis:685 | High | Partial — what-if returns risk_comparison table, not standalone metrics |
| Fake analysis engine (setTimeout stages) | ScenarioAnalysis:577 | High | Yes — `onRunScenario` prop |
| Fake Monte Carlo (3s setTimeout) | ScenarioAnalysis:562 | High | **No** — need Monte Carlo engine |
| Hardcoded optimization suggestions | ScenarioAnalysis:341 | Medium | Partial — what-if gives position changes + violations |
| Historical scenario impacts (2008, COVID) | ScenarioAnalysis:377 | Medium | **No** — need stress test engine |
| Stress test factor impacts | ScenarioAnalysis:424 | Medium | **No** — need factor shock engine |
| Prebuilt strategies (fake performance) | StrategyBuilder:306 | Medium | Already fallback-only (line 449) |
| Fake backtesting ("2019-2024") | StrategyBuilderContainer:197 | Medium | **No** — need backtest engine |
| Container scenario templates | ScenarioAnalysisContainer:259 | Low | UI presets, keep as-is |

## Architecture

### What the Backend Already Provides

```
POST /api/what-if          → WhatIfResult:
  - deltas: { volatility_delta, concentration_delta, factor_variance_delta }
  - risk_comparison: [{ metric, old, new, delta, limit, old_pass, new_pass }]  ← formatted % strings
  - factor_comparison: [{ factor, old, new, delta, limit }]
  - position_changes: [{ position, before, after, change }]  ← formatted % strings (e.g., "8.5%", "+2.3%")
  - risk_analysis: { risk_checks, risk_passes, risk_violations }
  - beta_analysis: { factor_beta_violations, proxy_beta_violations }
  - formatted_report: string (full CLI report)
  NOTE: Does NOT return standalone expectedReturn, Sharpe, VaR — only deltas and comparison tables

POST /api/direct/optimize/ → OptimizationResult (weights, trades, compliance)
POST /api/risk-score       → RiskAnalysisResult (30+ metrics: vol, factor betas, Sharpe, etc.)
POST /api/performance      → PerformanceResult (returns, Sharpe, drawdown by period)
POST /api/portfolio/refresh-prices → Live pricing for portfolio holdings (accepts holdings array)
```

Frontend hooks: `useWhatIfAnalysis()`, `usePortfolioOptimization()`, `useRiskAnalysis()`, `usePerformance()`, `usePositions()`.

### What the Backend Does NOT Provide

- Monte Carlo simulation engine
- Historical stress test backtesting (2008/COVID impacts on user's portfolio)
- VaR/CVaR with confidence intervals (can approximate from volatility)
- Strategy template library endpoint
- Real backtesting engine

## Codex Review Findings (Rev 1 → Rev 2)

| # | Finding | Resolution |
|---|---------|------------|
| 1 | Container shows `<LoadingSpinner>` and unmounts component when `loading=true`, so internal progress animation can't coexist | Remove internal progress animation. Use `loading` prop for loading state. Container already handles this. |
| 2 | `handleRunScenario` requires `name` field — passing raw weights would no-op | Build proper `ScenarioConfig` object with `name`, `type`, `apiScenario.new_weights` matching container's `toScenarioConfig()` contract |
| 3 | `useState(initialPositions ?? [])` won't update after async `usePositions()` resolves | Use `useEffect` to sync positions when prop changes: `useEffect(() => { if (initialPositions?.length) setCurrentPositions(initialPositions) }, [initialPositions])` |
| 4 | Plan claimed StrategyBuilder has `Math.random()` pricing — it doesn't | Corrected: StrategyBuilder's mock is only the backtest `setTimeout` (line 529). No pricing path to fix there. Phase B scoped to ScenarioAnalysis only. |
| 5 | What-if returns deltas/comparisons/violations, not standalone `expectedReturn`, `Sharpe`, `VaR95/99` | Restructure results display: show risk_comparison table (before/after volatility, HHI, etc.) + position changes + violations. Don't try to map to the fake metrics shape — use what the backend actually returns. |
| 6 | Weight unit mismatch: UI uses percentage (8.5), backend may expect decimal | Normalize in `runComprehensiveAnalysis()`: divide UI weights by 100 before sending as `new_weights`. Verify against `helpers_input.py` normalization logic. |
| 7 | Existing `/api/portfolio/refresh-prices` can price individual tickers — no new endpoint needed | Use `refresh-prices` with single-item holdings array for `addNewPosition()`. No Phase B backend changes needed. Response path: `result.portfolio_data.holdings[0]` (not `result.holdings[0]`). |

### Rev 2 → Rev 3 Fixes (Second Codex Review)

| # | Finding | Resolution |
|---|---------|------------|
| R2-1 | `/refresh-prices` response is `result.portfolio_data.holdings`, not `result.holdings` | Fixed snippet to use correct response path |
| R2-2 | Position changes shape is `{position, before, after, change}`, not `{Ticker, Old, New}` | Fixed all references to use correct field names |
| R2-3 | Historical/stress "Run" button proposed sending factor shocks as `new_weights` — wrong API contract | Changed to show "coming soon" for historical stress tests. What-if API only accepts ticker-weight maps. |
| R2-4 | `useEffect` position sync wouldn't clear positions or would overwrite user edits | Added `userHasEdited` ref to track manual edits. Sync fires for both populated and empty arrays. |

## Plan

### Phase A: Wire ScenarioAnalysis to Existing Backend (No Backend Changes)

The core fix: **stop ignoring container props**. Remove underscore prefixes and use real data.

#### A-1: Replace demo positions with real portfolio

**File**: `ScenarioAnalysis.tsx`
- Add prop: `initialPositions?: Array<{ticker: string, name: string, weight: number, price: number, shares: number}>`
- Change `currentPositions` useState initializer from hardcoded array (lines 327-338) to empty array `[]`
- Add ref to track whether user has manually edited positions:
  ```typescript
  const userHasEdited = useRef(false)
  ```
- Add `useEffect` to sync when prop arrives, respecting user edits:
  ```typescript
  useEffect(() => {
    if (initialPositions && !userHasEdited.current) {
      setCurrentPositions(initialPositions)  // syncs both populated and empty arrays
    }
  }, [initialPositions])
  ```
- Set `userHasEdited.current = true` in `addNewPosition()`, `removePosition()`, `updatePositionWeight()`
- Add "Reset to Portfolio" button that sets `userHasEdited.current = false` and re-syncs from `initialPositions`
- Show empty state when no positions loaded: "Load your portfolio to begin scenario analysis"

**File**: `ScenarioAnalysisContainer.tsx`
- Import `usePositions()` from `@risk/connectors`
- Map `positionsData.holdings` to `{ticker, name, weight, price: currentPrice, shares}` format
- Pass as `initialPositions` prop to `<ScenarioAnalysis>`

#### A-2: Wire analysis engine to real `onRunScenario`

**File**: `ScenarioAnalysis.tsx`
- Remove underscore from `_onRunScenario` → `onRunScenario`, `_loading` → `loading`, `_data` → `data`
- **Remove internal progress animation entirely** (lines 583-628). The container already shows `<LoadingSpinner>` when `loading=true` and unmounts the component — so internal progress stages are incompatible. The component will simply not render during backend execution.
- Rewrite `runComprehensiveAnalysis()`:
  - Build proper `ScenarioConfig` matching container's `toScenarioConfig()` contract:
    ```typescript
    onRunScenario({
      name: `Scenario: ${activeTab}`,
      type: activeTab,
      apiScenario: {
        scenario_name: `${activeTab}_analysis`,
        new_weights: Object.fromEntries(
          currentPositions.map(p => [p.ticker, p.weight / 100])  // UI % → decimal
        )
      }
    })
    ```
  - **Weight normalization**: Divide UI percentage weights (8.5) by 100 to get decimal (0.085) for backend. `helpers_input.py` line 56 normalizes inputs that sum > 1.5, but sending decimals directly is safer.
  - Remove `setIsRunning`, `setAnalysisProgress`, `setAnalysisStage` — container manages loading state
- Add `useEffect` to populate `analysisResults` when `data` prop updates with scenario results:
  ```typescript
  useEffect(() => {
    if (data?.scenarios?.[0]?.results) {
      setAnalysisResults({
        type: activeTab as AnalysisResult['type'],
        timestamp: new Date(),
        portfolio: {
          before: { ...currentPositions },
          after: deriveOptimizedPositions(data.scenarios[0].results.positionChanges)
        },
        metrics: deriveMetricsFromComparison(data.scenarios[0].results),
        recommendations: deriveRecommendations(data.scenarios[0].results),
        confidenceScore: data.scenarios[0].results.riskMetrics?.passedRiskChecks ? 90 : 60
      })
      setShowResults(true)
    }
  }, [data])
  ```

- **Replace `generateOptimizedPortfolio()`** (lines 653-682): New `deriveOptimizedPositions()` maps `positionChanges` (which has `{position, before, after, change}` formatted as "8.5%") back to position objects. Parse percentage strings to numbers.
- **Replace `generateTabSpecificMetrics()`** (lines 685-735): New `deriveMetricsFromComparison()` extracts from `riskComparison` array.
  - **IMPORTANT**: Container passes `comparison_analysis.risk_comparison` (raw DataFrame → JSON), NOT the formatted `risk_comparison` table. Raw field names are DataFrame column names: `{Metric, Old, New, Δ, Limit, "Old Pass", "New Pass"}` with raw float values (not formatted % strings).
  - `volatility` → find row where `Metric` contains "Volatility", use `New` value (raw float, e.g., 0.185)
  - `concentration` → find row where `Metric` contains "Herfindahl", use `New` value
  - For fields the backend doesn't provide (expectedReturn, Sharpe, VaR): show "N/A" or omit from display
- **Replace `generateRecommendations()`**: derive from `formattedReport` and `risk_violations`

#### A-3: Replace hardcoded optimization suggestions

**File**: `ScenarioAnalysis.tsx`
- Delete `optimizationSuggestions` useState (lines 341-375)
- When `data?.scenarios[0]?.results` is available, derive suggestions from:
  - `positionChanges` → "Adjust AAPL from 8.5% to 6.5%"
  - `riskMetrics.riskViolations > 0` → "Address N risk violations"
  - `formattedReport` → Display as analysis summary
- When no data, show: "Run a scenario to see analysis results"

#### A-4: Handle historical/stress tabs gracefully

**File**: `ScenarioAnalysis.tsx`
- Keep `historicalScenarios` array (lines 377-422) as **UI templates** (names, descriptions, factor labels)
- **Remove fake portfolio-specific impact numbers** (`portfolioReturn`, `maxDrawdown`, `var95`, `var99`)
- Show: "Run stress test to calculate impact on your portfolio" instead of fake numbers
- **Disable "Run" on historical scenarios entirely.** The what-if API only accepts ticker-weight maps, not factor shocks. Do NOT call `onRunScenario()` for historical/stress scenarios — it would either no-op (toScenarioConfig rejects invalid input) or send an empty scenario that the backend rejects. Instead, show a disabled button with tooltip: "Historical stress testing — coming soon"
- Keep `stressTestFactors` array (lines 424-467) but remove hardcoded `impact` values
- Show factor descriptions without fake impacts, with "Coming soon" badge

#### A-5: Handle Monte Carlo tab gracefully

**File**: `ScenarioAnalysis.tsx`
- Replace `runMonteCarloSimulation()` (line 562-568) with disabled state
- Show: "Monte Carlo simulation — coming soon" or hide tab entirely
- Do NOT show a fake 3-second setTimeout pretending to run simulations

#### A-6: StrategyBuilder cleanup

**File**: `StrategyBuilder.tsx`
- Lines 306-379: Mark `prebuiltStrategies` as sample data — set all performance numbers to 0, status to "draft", add "(Sample)" suffix to names
- Lines 528-529: Remove `setTimeout` fallback in `runBacktest()` — the container always passes `onBacktest`. Change else branch to a no-op with console log.
- **No pricing changes needed** (Codex finding #4: StrategyBuilder has no `Math.random()` pricing path)

### Phase B: Wire Real Pricing for Position Addition (Frontend Only)

**No new backend endpoint needed.** Use existing `/api/portfolio/refresh-prices` (Codex finding #7).

#### B-1: Replace `Math.random()` pricing in ScenarioAnalysis

**File**: `ScenarioAnalysis.tsx`
- Rewrite `addNewPosition()` (lines 512-527):
  - Use SessionManager or existing API service to call `/api/portfolio/refresh-prices` (avoids auth header concerns — SessionManager already handles auth via cookies/JWT):
    ```typescript
    // Preferred: use SessionManager if available
    const result = await sessionManager.refreshPrices([{ ticker: newTicker.toUpperCase(), shares: 1 }])
    // Response shape: { success: true, portfolio_data: { holdings: [...], total_portfolio_value: N } }
    const priceData = result.portfolio_data?.holdings?.[0]
    ```
  - Use `priceData.market_value` (price × 1 share = price) and `priceData.security_name` for real name
  - Show loading spinner while fetching
  - Handle unknown tickers: backend may return `market_value: 0` rather than an error for unknown tickers. Check `priceData.market_value > 0` — if zero, show "Could not find price for {ticker}"

- **Alternatively**, if SessionManager already wraps this endpoint, use the existing service method instead of raw `fetch`.

### Phase C: Backend Backlog (Document, Don't Implement Now)

These items need new backend capabilities. For now, the UI should show honest empty/disabled states rather than fake data.

#### C-1: Monte Carlo Simulation Engine
- New module: `core/monte_carlo.py`
- Takes portfolio weights + historical returns, runs N simulated return paths
- Output: return distribution, confidence intervals, probability of loss, expected shortfall
- Endpoint: `POST /api/monte-carlo`
- **Current UI treatment**: Tab disabled or "coming soon"

#### C-2: Historical Stress Test Backtesting
- Apply historical crisis factor shocks (2008, COVID, dot-com) to user's actual portfolio
- Use existing factor betas from `get_risk_analysis()` × historical factor returns
- Endpoint: `POST /api/stress-test`
- **Current UI treatment**: Show scenario descriptions but "Run to calculate impact" instead of fake numbers

#### C-3: VaR/CVaR Calculation
- Parametric VaR can be approximated client-side: `portfolio_value × volatility × z_score × sqrt(horizon/252)`
- Full historical VaR needs return distribution from backend
- **Current UI treatment**: Compute parametric estimate from existing volatility data if available, otherwise show "N/A"

#### C-4: Strategy Template Library
- Backend endpoint: `GET /api/strategy-templates`
- Strategy persistence: `POST /api/strategies`
- **Current UI treatment**: Keep container templates (ScenarioAnalysisContainer:259-304) as reasonable presets

#### C-5: Backtesting Engine
- Run strategies against historical data
- Endpoint: `POST /api/backtest`
- **Current UI treatment**: StrategyBuilder backtest tab shows "coming soon" or uses what-if as proxy

## Files Modified

### Phase A (frontend only):
- `frontend/packages/ui/src/components/portfolio/ScenarioAnalysis.tsx` — Major rewrite of data flow (~200 lines changed)
- `frontend/packages/ui/src/components/dashboard/views/modern/ScenarioAnalysisContainer.tsx` — Add `usePositions()`, pass positions as prop (~20 lines)
- `frontend/packages/ui/src/components/portfolio/StrategyBuilder.tsx` — Mark prebuilt strategies as samples, remove dead setTimeout (~30 lines)

### Phase B (frontend only — no backend):
- `ScenarioAnalysis.tsx` — Wire `addNewPosition()` to existing `/api/portfolio/refresh-prices` (~20 lines)

### Phase C:
- No code changes — document as backlog items in TODO.md

## Key Design Decisions

1. **Don't delete mock historical scenarios** — keep names/descriptions as UI templates, just remove fake portfolio-specific numbers
2. **Don't fake Monte Carlo** — disable/hide tab rather than show a 3-second setTimeout
3. **Parametric VaR** — compute client-side from existing volatility as interim solution
4. **Keep container templates** — the 5 scenario templates in ScenarioAnalysisContainer are reasonable UI presets, not misleading data
5. **No internal progress animation** — container already unmounts component during loading, so internal staged progress is incompatible. Let container handle loading UX.
6. **Reuse `/api/portfolio/refresh-prices`** — no new backend endpoint needed for ticker pricing. Pass single-item holdings array.
7. **Weight normalization** — UI uses percentage (8.5), backend expects decimal (0.085). Divide by 100 before sending.
8. **Results shape** — don't force what-if data into the fake metrics shape (expectedReturn, Sharpe, VaR). Display what the backend actually returns: risk comparison table, position changes, violations.

## Implementation Order

1. Phase A (A-1 through A-6) as a single PR — this is the high-impact change
2. Phase B-1 after Phase A lands — adds real pricing for position addition
3. Phase C items tracked in TODO.md as backlog

## Verification

```bash
# Frontend builds
cd frontend && pnpm build

# ESLint passes
pnpm -C frontend/packages/ui exec eslint src/components/portfolio/ScenarioAnalysis.tsx src/components/portfolio/StrategyBuilder.tsx

# Manual: Load dashboard → Scenarios tab → verify real positions load (not hardcoded AAPL/MSFT)
# Manual: Run a scenario → verify real risk comparison table appears (not random numbers)
# Manual: Historical/Stress tabs → verify no fake impact numbers shown
# Manual: Monte Carlo tab → verify disabled or "coming soon"
# Manual: Add position → verify real price from refresh-prices API (not Math.random)
# Manual: StrategyBuilder → verify prebuilt strategies marked as "(Sample)"
```

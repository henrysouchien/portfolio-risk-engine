# Backtest Tool Redesign Plan

> **Codex review**: R1-R7 PASS (18 findings). Post-PASS thesis revision: 6 additional rounds → **PASS**. Total: 13 rounds, 24 findings resolved.

## Context

The Backtest tool is unintuitive. It presents a blank weight table requiring manual ticker-by-ticker entry, gives sparse results (5 KPI tiles, one chart, one table), and loses all state on navigation. The backend computes rich data (attribution, risk metrics, drawdown details) that the frontend ignores.

**Design thesis**: A backtest validates a **portfolio thesis** against history. The tool should feel like a sandbox — start from your current portfolio or a preset, tweak easily, see rich results that mirror the existing portfolio analysis views, and iterate.

**Audit findings** (7-dimension evaluation completed):
- UI/UX: B — no portfolio pre-load, no ticker autocomplete, no presets
- Data Quality: B- — annual Max DD always N/A (backend gap), BRK.B excluded
- Cross-View: B+ — receives context from workflows, but no "load current" shortcut
- Action Paths: B — only 1 exit ramp (rebalance), missing stress test/MC links
- AI Integration: B+ — good chat handoff via "Ask AI about this"
- MCP Coverage: A- — solid backend, attribution not in agent snapshot
- State Persistence: UI input state (rows/weights) lost on unmount — hook data may persist via React Query cache. Full cross-nav persistence is A0 scope.

## Approach — 3 Phases

### Phase 1: Input Redesign — "Portfolio Thesis"

The core UX shift: **the weight table is the output of the input process, not the input itself.** Users describe what they want to test (strategy, modification, or idea) → it resolves to weights → displayed in an editable table for review → run backtest.

Three input paths, progressive disclosure:

```
┌─────────────────────────────────────────────────────┐
│  What do you want to test?                          │
│                                                     │
│  [My Portfolio] [60/40] [All-Weather] [Equal Wt]    │  ← Strategy presets
│  [Balanced 4-Asset] [Top 5 Holdings]                │
│                                                     │
│  ┌─ Or modify your current portfolio ─────────────┐ │
│  │  [+5% VTI] [-3% AAPL] [+200bp BND]            │ │  ← Delta mode (additive only)
│  └────────────────────────────────────────────────┘ │
│                                                     │
│  [Build with AI →]  (opens chat for AI-assisted     │  ← Chat-side AI flow
│   allocation construction; results stay in chat)    │
│                                                     │
│  ┌─ Resolved Allocation (editable) ───────────────┐ │
│  │  AAPL  30%  │  MSFT  25%  │  GOOGL  20%  │ ...│ │  ← Weight table
│  └────────────────────────────────────────────────┘ │
│                                                     │
│  Benchmark: [SPY ▾]  Period: [1Y][3Y][5Y][10Y][MAX] │
│                                        [▶ Run Backtest] │
└─────────────────────────────────────────────────────┘
```

**Step 1.1: Pre-load current portfolio via `useScenarioState`**

Every other scenario tool (WhatIf, StressTest, MonteCarlo, Hedge) uses `useScenarioState` to get `initialPositions` from `usePositions()`. BacktestTool is the only one that doesn't.

- Import and wire `useScenarioState` in `BacktestTool.tsx` (same pattern as WhatIfTool lines 201-218)
- Compute `initialWeightRecord` from `initialPositions` (ticker → weight/100)
- **Rewrite seeding logic** — current seeding only keys off `context.weights`. Must add a portfolio-based seed path: when `initialPositions` arrives (async, may load after mount), generate a new `seedKey` like `portfolio:${portfolioId}` and seed rows from `initialWeightRecord`. Follow WhatIfTool's dual-seed pattern (context weights OR portfolio positions, with `lastSeedKeyRef` dedup guard).
- Priority: context weights (from navigation) → `initialWeightRecord` (from portfolio) → empty
- User lands with their portfolio weights pre-populated, can immediately click "Run Backtest"

**Files**: `BacktestTool.tsx`

**Step 1.2: Strategy presets**

Replace the blank-slate input with a strategy selector. Each preset is a named allocation with predefined ticker→weight mappings.

**Built-in strategies** (hardcoded weight configs):
- "My Portfolio" (default) — current portfolio weights from `initialPositions`
- "60/40 Stocks/Bonds" — 60% VTI / 40% BND
- "All-Weather" — 30% VTI / 40% TLT / 15% IEI / 7.5% GLD / 7.5% DBC
- "Equal Weight" — equal split across current portfolio tickers
- "Balanced 4-Asset" — 25% VTI / 25% TLT / 25% GLD / 25% DBC
- "Top 5 Holdings" — top 5 current holdings by weight, equal-weighted
- "Custom" — **derived label, not a clickable preset**. Appears automatically when the user manually edits any weight. Cannot be re-selected — it's a state indicator like "Imported". If the user edits weights, switches to "60/40", then wants their edits back, they must re-enter them (or undo via browser). No "custom weights" are cached.

Render as a horizontal pill bar (same `ToggleGroup` pattern as period selector). The 6 named strategies are clickable; selecting one replaces the weight table rows. "Custom" and "Imported" are non-clickable state indicators.

**"Imported" is a non-selectable status indicator** — renders as a disabled/highlighted pill when `context.weights` is non-empty (tool entered from another tool's exit ramp). Not cached, not clickable. Disappears if user selects another preset.

**Preset state rule**: Context seed → show "Imported" indicator. Portfolio seed → select "My Portfolio". Manual edit → "Custom" indicator. Add `selectedPreset` to `toolRunParams["backtest:ui"]` cache — only cache the 6 clickable strategy IDs. "Custom" and "Imported" are not cached (they are derived from current state).

**Files**: `BacktestTool.tsx` — define `STRATEGY_PRESETS` config array with `{ id, label, getWeights(initialPositions) → Record<string, number> }`

**Step 1.3: Delta mode**

Toggle between "Full Allocation" and "Changes from Current" input modes (same pattern as WhatIfTool's `inputMode`).

In delta mode, the weight table shows modification rows instead of absolute weights:
- "+5%" / "-3%" / "+200bp" — additive shifts only (same grammar as MCP `parse_delta()` in `utils/helpers_input.py`)
- To add a new position not in current portfolio, user toggles back to "Full Allocation" mode and adds a row (delta mode only modifies existing positions; the preset indicator changes to "Custom")
- **Baseline**: `initialWeightRecord` from `useScenarioState` (current portfolio weights). Must be explicitly passed to the resolution step.
- **Frontend-side resolution**: implement `applyDeltas(baseline, deltas) → Record<string, number>` that mirrors backend `parse_delta()` semantics. Resolve to absolute weights before calling the REST endpoint (which only accepts `weights`). This avoids backend REST changes.
- Show a "Resolved preview" below the delta inputs so the user sees the final allocation before running. This preview is a **pre-engine estimate** (frontend-resolved, labeled "approximate — engine may normalize"). After running, the results section and exit ramps use `backtest.data.weights` (post-engine, authoritative).
- **Note**: The backtest engine internally normalizes weights to sum to 1.0 before computing returns. This is pre-existing behavior across all scenario tools.

**Files**: `BacktestTool.tsx`, `useBacktest.ts` (add resolved weights from delta computation)

**Step 1.4: AI construction entry point**

Add a "Build with AI" button that opens the scenario chat pre-seeded with backtest context:
```
openScenarioChat({
  toolId: "backtest",
  toolLabel: "Backtest Allocation",
  summary: "Help me construct a portfolio allocation to backtest.",
  prompt: "What kind of portfolio would you like to test? Describe your thesis...",
})
```

**Scope and limitations**: This is a **chat-side** construction flow. The agent can construct an allocation and run `run_backtest` via MCP, with results displayed in the chat/artifact panel. Results do **not** flow back into the tool UI — there is no chat-to-tool bridge today and building one is out of scope. The value is a convenient entry point to AI-assisted exploration within the existing chat infrastructure. A bidirectional chat↔tool bridge is future work.

**Files**: `BacktestTool.tsx`

**Step 1.5: Weight table as "resolved allocation"**

Reframe the weight table from "primary input" to "resolved view":
- Pre-populated from whichever input path was used (preset, delta, or manual). AI path runs in chat separately.
- Still fully editable — user can always tweak after resolution
- Any edit switches preset to "Custom"
- Compact layout with weight sum indicator + amber warning if significantly off 100%
- "Add ticker" button at bottom (stays)

**Files**: `BacktestTool.tsx`

**Step 1.7: Fix exit ramp gating (moved from Phase 3 — prerequisite)**

With presets as the main input path, excluded tickers are common (e.g., preset includes ETFs with short history). The current gating compares `activeWeights` signature against returned weights — any exclusion permanently disables exit ramps and workflow completion.

Fix: track `lastRunWeightsRef` — set to a copy of `activeWeights` when user clicks "Run Backtest". `hasCompletedBacktest = backtest.hasData && getWeightSignature(activeWeights) === getWeightSignature(lastRunWeightsRef.current)`. This decouples "did the user change inputs?" from "did the backend exclude tickers?".

Exit ramps export `backtest.data.weights` (resolved weights after exclusions), not `activeWeights`.

**Files**: `BacktestTool.tsx`

**Step 1.6: 10Y period option**

Backend supports `10Y` but UI only shows 1Y/3Y/5Y/MAX. Add it. Three changes needed:
1. Add `"10Y"` to `PERIOD_OPTIONS` array
2. Add `"10Y"` to the `BacktestPeriodValue` type union
3. Add `"10Y"` case to the `onValueChange` guard in the ToggleGroup

**Files**: `BacktestTool.tsx`

### Phase 2: Results Enrichment — "Mini Portfolio Analysis"

Surface all the data the backend already computes. **Zero backend changes.**

**Step 2.1: Enhanced KPI tiles (8 tiles, 2 rows)**

Replace 5 hand-rolled div tiles with 8 organized metrics:

| Row | Metrics |
|-----|---------|
| Returns | Total Return, Annualized Return, Alpha (annual), Win Rate |
| Risk-Adjusted | Sharpe, Sortino, Max Drawdown, Calmar |

All data already in `performanceMetrics.returns`, `performanceMetrics.risk_adjusted_returns`, `performanceMetrics.risk_metrics`. Just need to extract and display.

**Files**: `BacktestTool.tsx`

**Step 2.2: Drawdown chart (frontend-computed)**

Compute from already-returned `cumulativeReturns`:
```
drawdown[t] = cumReturns[t] / max(cumReturns[0..t]) - 1
```

Render as red-tinted AreaChart (filled below zero) using existing `ChartContainer` + Recharts. Place below cumulative return chart.

**Files**: `BacktestTool.tsx`

**Step 2.3: Attribution section (3 collapsible tables)**

The `BacktestAdapter` already extracts typed arrays:
- `securityAttribution: AttributionRow[]` (name, allocation, return, contribution, beta)
- `sectorAttribution: AttributionRow[]`
- `factorAttribution: AttributionRow[]`

**These are computed and parsed but never rendered in BacktestTool.** However, attribution tables already exist in Strategy Builder's `PerformanceTab.tsx` (lines 353-375). **Extract the attribution table into a shared component** rather than duplicating in BacktestTool (already 776 lines).

Add three collapsible sections:
- "Top Contributors & Detractors" — security attribution sorted by contribution
- "Sector Attribution" — sector-level
- "Factor Attribution" — factor exposures

Use `Collapsible`/`CollapsibleTrigger`/`CollapsibleContent` (same pattern as StressTestTool's expandable sections). Default first one open, others collapsed.

**Files**: Extract `AttributionTable.tsx` from `PerformanceTab.tsx` into `scenarios/shared/` (or `blocks/`), then import in `BacktestTool.tsx`. Extract results section into `BacktestResults.tsx` sub-component to manage file size.

**Step 2.4: Risk metrics panel**

Add a "Risk Profile" section with a 3-column grid:
- Volatility, Downside Deviation, Tracking Error → from `performanceMetrics.risk_metrics`
- Beta, R² → from `performanceMetrics.benchmark_analysis`
- Up/Down Capture → from `performanceMetrics.risk_adjusted_returns` (not `risk_metrics`)

**Files**: `BacktestTool.tsx`

**Step 2.5: Benchmark comparison strip**

Side-by-side row: Portfolio vs Benchmark for Return, Volatility, Sharpe. Clean visual comparison.

**Files**: `BacktestTool.tsx`

### Phase 3: Backend Fix + Polish

**Step 3.1: Annual breakdown max drawdown (backend)**

The annual breakdown only returns `{year, portfolio_return, benchmark_return, alpha}`. The "Max DD" column in the frontend always shows N/A.

Fix in `backtest_engine.py` `_build_annual_breakdown()`:
- For each year, compute max drawdown from monthly returns in that year
- Add `"max_drawdown"` field to each annual row

**Files**: `portfolio_risk_engine/backtest_engine.py`
**Tests**: Add test verifying per-year max drawdown computation

**Step 3.2: Exit ramp additions**

Current: only "Set as target allocation" → rebalance.

**Add one new exit ramp**: "Analyze what-if" → `onNavigate("what-if", { weights: backtest.data.weights })`. WhatIfTool already accepts `context.weights` and seeds from them.

Note: StressTest, MonteCarlo, and Optimize exit ramps deferred — those tools don't support arbitrary imported weights at the API level. Future cross-tool context wiring pass.

Note: Exit ramp gating fix and export payload fix are in Phase 1 Step 1.7.

**Files**: `BacktestTool.tsx`

**Step 3.3: Warning display improvement**

- Show warnings as bulleted list (not space-joined string)
- Don't truncate text

**Files**: `BacktestTool.tsx`

**Step 3.4: Additional backtest flags**

`generate_backtest_flags()` receives the agent snapshot, which currently only contains `period`, `returns`, `risk` (max_drawdown, sharpe), `data_quality`, and `resolved_weights`. New flags need data not in the snapshot.

**Step 3.4a**: Expand `BacktestResult.get_agent_snapshot()` to include:
- `volatility` (from `performance_metrics.risk_metrics.volatility`)
- `sortino_ratio` (from `performance_metrics.risk_adjusted_returns.sortino_ratio`)
- `down_capture_ratio` (from `performance_metrics.risk_adjusted_returns.down_capture_ratio`)
- `annual_breakdown` summary (years with positive alpha count / total years)

**Files**: `core/result_objects/backtest.py`

**Step 3.4b**: Add flags to `core/backtest_flags.py`:
- `high_volatility` — annualized vol > 30%
- `strong_down_capture` — down capture ratio > 1.1
- `annual_consistency` — majority of years have positive alpha (info)

**Files**: `core/backtest_flags.py`
**Tests**: Add tests for new flags + expanded snapshot

## Out of Scope

- **State persistence** — A0 cross-cutting fix, separate plan
- **Full AI allocation builder** — Phase 1.4 adds the entry point (pre-seeded chat). A richer inline AI builder (type thesis → see weights populate in real time) is future work.
- **Session history / run comparison** — would require new store infrastructure. Future feature.
- **Ticker autocomplete** — nice UX improvement but separate from this redesign
- **Custom strategy saving** — users can't save their own strategy presets yet. Future feature.

## Key Files

| File | Changes |
|------|---------|
| `frontend/.../scenarios/tools/BacktestTool.tsx` | Major — thesis-driven input (presets, delta mode, AI entry), exit ramps, warning display |
| `frontend/.../scenarios/tools/BacktestResults.tsx` | New — extracted results section (KPIs, charts, attribution, risk) |
| `frontend/.../scenarios/shared/AttributionTable.tsx` | New — extracted from Strategy Builder `PerformanceTab.tsx` |
| `frontend/.../connectors/src/features/backtest/hooks/useBacktest.ts` | Minor — delta resolution before API call |
| `portfolio_risk_engine/backtest_engine.py` | Minor — add max_drawdown to annual breakdown |
| `core/result_objects/backtest.py` | Minor — expand agent snapshot with vol/sortino/capture |
| `core/backtest_flags.py` | Minor — 3 new flags |
| `frontend/.../scenarios/tools/WhatIfTool.tsx` | Reference — pattern for useScenarioState + delta mode; also exit ramp target |

## Verification

1. **Phase 1 — Presets**: Open backtest tool → verify current portfolio weights pre-loaded with "My Portfolio" selected → select "60/40" → weights change to VTI/BND → select "All-Weather" → weights change to 5-asset mix → select "Equal Weight" → weights split evenly → edit a weight → preset switches to "Custom". Navigate from optimization → verify "Imported" indicator shown.
1b. **Phase 1 — Delta mode**: Toggle to "Changes from Current" → enter "+5% VTI, -5% AAPL" → verify resolved preview shows updated weights → click "Run Backtest" → verify results use resolved weights.
1c. **Phase 1 — AI entry**: Click "Build with AI" → verify chat opens with backtest context and construction prompt. Verify that AI running a backtest via MCP shows results in chat/artifact panel, NOT in the tool UI (no chat→tool bridge).
2. **Phase 2**: Run backtest → verify 8 KPI tiles show real values (including Sortino, Calmar) → scroll to drawdown chart (red area below zero) → verify attribution tables expand with real contributor/detractor data → verify risk metrics panel shows vol/beta/tracking error
3. **Phase 3**: Run backtest with a ticker that gets excluded → verify annual breakdown "Max DD" column shows real percentages (not N/A) → verify exit ramps enable despite exclusion → verify "Set as target allocation" exports resolved weights (without excluded ticker) → verify "Analyze what-if" navigates to WhatIf with resolved weights → verify warnings show as bullet list
4. **Stale export guard**: Run backtest → exit ramps enable → edit a weight in the table → verify both exit ramps disable immediately → re-run → verify they re-enable with resolved weights
5. **Navigate away and back**: UI inputs may reset (A0 scope) — but portfolio auto-preload means re-running is one click

## Codex Findings

### Round 1 — FAIL (8 findings)

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | High | Exit ramp targets (StressTest, MC, Optimize) ignore `context.weights` | R2: Deferred — those tools don't support arbitrary weights at API level. Only WhatIf exit ramp kept. |
| 2 | High | New flags can't see vol/capture/annual data — not in agent snapshot | Added Step 3.4a to expand `get_agent_snapshot()` before adding flags |
| 3 | High | State persistence claim overstated | Clarified: UI input state lost on unmount, hook data may persist via React Query. A0 scope. |
| 4 | Medium | Phase 1 preload needs seeding logic rewrite, not just import | Expanded Step 1.1 with dual-seed pattern details |
| 5 | Medium | 10Y requires 3 changes (type + array + guard), not 1 | Fixed Step 1.4 |
| 6 | Medium | Attribution UI exists in Strategy Builder — should reuse | Changed Step 2.3 to extract shared component |
| 7 | Medium | Up/down capture is in `risk_adjusted_returns`, not `risk_metrics` | Fixed Step 2.4 |
| 8 | Medium | Exit ramp gating — excluded tickers break weight signature match | R2: Fixed with lastRunWeights ref approach |

### Round 2 — FAIL (3 findings)

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| R2-1 | High | Exit ramps to StressTest/MC/Optimize need backend changes, not just context wiring | Deferred those exit ramps entirely. Only "Set as target allocation" + "Analyze what-if" kept. |
| R2-2 | High | Exit ramp gating fix was still wrong — `backtest.hasData` allows stale exports | Replaced with `lastRunWeights` ref approach: track weights at run time, compare against current `activeWeights` |
| R2-3 | Medium | Preset state undefined when entering from workflow with imported weights | Added "Imported" status indicator + explicit state rule: context seed → "Imported" indicator, portfolio seed → "My Portfolio" |

### Round 3 — FAIL (3 findings)

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| R3-1 | High | Exit ramps export `activeWeights` (includes excluded tickers), not resolved weights | Exit ramps now export `backtest.data.weights` (resolved). Gating uses `lastRunWeightsRef` to decouple from exclusions. |
| R3-2 | Medium | `selectedPreset` not in UI cache — pill bar shows wrong state on restore | Added `selectedPreset` to `toolRunParams["backtest:ui"]` cache |
| R3-3 | Medium | Verification checklist still references 4 exit ramps and Stress Test handoff | Updated to match deferred scope (2 exit ramps: rebalance + what-if) |

### Round 4 — FAIL (2 findings)

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| R4-1 | Medium | "Imported" preset has no durable source weights for re-selection | Clarified: "Imported" is a non-selectable status pill, not a clickable preset. No path back without re-navigation. |
| R4-2 | Low | Verification missing negative stale-export case | Added stale export guard test: edit weight after run → exit ramps disable → re-run → re-enable |

### Round 5 — FAIL (1 finding)

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| R5-1 | Medium | "Imported" still described as cached preset in some places, contradicting status-pill model | Clarified: only 6 clickable strategy presets are cached. "Imported" and "Custom" are non-cached, non-clickable state indicators. |

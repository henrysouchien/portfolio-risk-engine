# What-If Tool Redesign Plan

> **Codex review**: R1 FAIL (6). R2 FAIL (3 new). R3 FAIL (2 low). R4 FAIL (1 low). **R5 PASS.**

## Context

The What-If tool answers: **"If I change my portfolio, how does risk/return change?"** The backend is solid — it computes factor deltas, position changes, compliance details, risk comparison tables, factor exposure comparisons. But the frontend only shows 3 metrics (volatility, HHI, factor variance) in a plain table, with no charts, no breakdown, and no per-asset impact. Compared to the Backtest redesign (8 KPI tiles, drawdown chart, attribution tables, risk profile), What-If feels undercooked.

**Audit findings** (7-dimension evaluation, live browser testing):
- UI/UX: C+ — input list dominates (27 rows), results not sticky, no visualization, mode switch destroys state
- Data Quality: C — only 3 metrics shown, no return delta, no per-asset impact. Backend has the data.
- Cross-View: B — exit ramps exist but labels are duplicated, no Optimize inbound
- Action Paths: B- — exit ramps at bottom of page, easily missed
- AI Integration: B+ — full agent format with 7 flag types, "Ask AI" works
- MCP Coverage: A- — solid, minor gaps (no template param, top-5 truncation)
- State Persistence: B+ — works via toolRunParams. Hook preserves separate weight/delta state correctly (confirmed by existing tests).

**Design thesis**: A what-if scenario should feel like a **risk impact preview** — show what changes, why, and what to do about it. The tool should surface the before/after comparison the backend already computes, not hide it behind 3 aggregate numbers.

## Approach — 2 Phases

### Phase 1: Results Enrichment — "Surface What the Backend Already Computes"

**Zero backend changes.** The API response (`to_api_response()` at `core/result_objects/whatif.py:572`) already returns all this data. The frontend ignores it.

**Step 1.1: Position Changes Table**

The API returns `scenario_results.position_changes` — a full list of every position with before/after weights and change. Currently used ONLY for `resolvedWeights` derivation (`WhatIfTool.tsx:329`), never displayed.

Surface as a sortable table below the 3-metric summary:
- Columns: Ticker, Current Weight, Scenario Weight, Change (with color: green for decrease in overweight, red for increase)
- Sort by absolute change (largest movers first)
- Collapsible — show top 5 by default, "Show all" expander

**Data source**: `scenarioResults.position_changes` (already parsed at line 329)
**Files**: `WhatIfTool.tsx`

**Step 1.2: Enriched Risk Summary + Risk Limit Checks**

The current 3-row `ScenarioResultsPanel` (vol, HHI, factor variance) remains the primary summary — these come from `scenario_results.scenario_summary` which contains both `current` and `scenario` sub-objects. **Do not replace this.**

Additionally, surface `scenario_results.comparison_analysis.risk_comparison` as a supplementary "Risk Limit Checks" table below the summary. This table contains risk-limit-specific metrics: volatility, max weight, factor var %, market var %, and max industry var % — each with Old/New/Delta columns (built from `run_portfolio_risk.py:423`). Note: this table does NOT contain tracking error, VaR, or drawdown — those are not in the API response.

Also add `idiosyncratic_variance_pct` from `scenario_summary` to the primary 3-row summary (making it 4 rows), since the backend already returns it alongside `factor_variance_pct`.

**Data source**: `scenarioResults.scenario_summary` (primary 4 metrics), `scenarioResults.comparison_analysis.risk_comparison` (supplementary risk limit table)
**Files**: `WhatIfTool.tsx`

**Step 1.3: Factor Exposure Comparison**

The API returns `scenario_results.factor_exposures_comparison` — before/after actual factor betas (market, size, value, momentum, etc.) and `scenario_results.factor_comparison` (formatted table).

Surface as a compact factor delta table:
- Columns: Factor, Current Beta, Scenario Beta, Delta
- Show top factors by absolute delta change
- Collapsible under "Factor Exposures" heading

**Data source**: `scenarioResults.factor_exposures_comparison` or `scenarioResults.factor_comparison`
**Files**: `WhatIfTool.tsx`

**Step 1.4: Risk Violation Details**

Currently shows Pass/Fail/0 in the Risk Checks section. The API returns three pairs of check/violation data:

1. **Risk limits**: `risk_analysis.risk_checks` (all checks) + `risk_analysis.risk_violations` (failed only) — from `whatif.py:713`
2. **Factor beta**: `beta_analysis.factor_beta_checks` (all) + `beta_analysis.factor_beta_violations` (failed) — from `whatif.py:746`
3. **Proxy/industry beta**: `beta_analysis.proxy_beta_checks` (all) + `beta_analysis.proxy_beta_violations` (failed) — from `whatif.py:746`

The current component already combines factor and proxy into one `betaPasses` status (`WhatIfTool.tsx:314`). The enriched view must preserve this grouping.

Enrich the Risk Checks card:
- When violations exist: show a collapsible section per category (Risk Limits, Factor Betas, Industry Proxies) with Metric/Actual/Limit columns using the `*_violations` arrays
- When all pass: keep current compact Pass/Pass/0 view but add a "View all checks" expander using the `*_checks` arrays (not just violations)
- Color the card border red/amber when any category has violations

**Violation count semantics**: The current `riskViolationCount` (`WhatIfTool.tsx:315`) only counts `risk_analysis.risk_violations`. This must be changed to a **total violation count** summing all three: `risk_violations.length + factor_beta_violations.length + proxy_beta_violations.length`. This total is used in the Violations badge, the insight banner copy (`WhatIfTool.tsx:388`), and the `toolContract.metrics.riskViolations` (`WhatIfTool.tsx:390`). The summary labels should change from "risk violations" to "violations" to reflect the combined count.

**Data source**: All 6 arrays — `risk_analysis.{risk_checks, risk_violations}`, `beta_analysis.{factor_beta_checks, factor_beta_violations, proxy_beta_checks, proxy_beta_violations}`
**Files**: `WhatIfTool.tsx`, `whatif/RiskChecksSection.tsx`

**Step 1.5: Insight Banner Enrichment**

Current insight copy is generic ("Scenario clears current guardrails"). Make it data-driven:
- Include the most impactful change: "Volatility +0.3%, concentration -44% (HHI 0.064→0.036)"
- When violations: list the specific failing metrics
- Shorter body text — the data tables now carry the detail

**Files**: `WhatIfTool.tsx` (lines 346-376, `baseScenarioInsight` computation)

### Phase 2: UI/UX Restructure

**Step 2.1: Sticky Results Panel with Split Layout**

The right column scrolls away when the input list is long (27 tickers = ~1500px). Make the results panel sticky with a split layout so exit ramps are always visible:

```
┌─────────────────────────────────────┐
│ [Insight Banner]                    │  ← always visible (top of sticky)
├─────────────────────────────────────┤
│ [Scrollable results body]           │  ← overflow-y-auto
│   - Scenario Results (4 metrics)    │
│   - Risk Limit Checks table         │
│   - Position Changes table          │
│   - Factor Exposures table          │
│   - Risk Checks (violations)        │
├─────────────────────────────────────┤
│ [Exit ramps - fixed footer]         │  ← always visible (bottom of sticky)
│   Backtest · Simulate · Trades      │
└─────────────────────────────────────┘
```

Implementation:
- Wrap right column in `xl:sticky xl:top-20` with `xl:flex xl:flex-col xl:max-h-[calc(100vh-8rem)]`
- **Responsive scoping**: The parent grid is `xl:grid-cols-[...]` (`WhatIfTool.tsx:443`), meaning the two-column layout only activates at `xl`. The sticky/split layout must also be `xl:`-prefixed so on mobile/tablet (stacked layout) it remains a normal flow without viewport-capped scrolling.
- Insight banner: `xl:flex-shrink-0` (never scrolls on desktop)
- Results body: `xl:flex-1 xl:overflow-y-auto` (scrollable on desktop)
- Exit ramp footer: `xl:flex-shrink-0 xl:border-t` (pinned at bottom on desktop)
- On mobile: all sections stack normally, exit ramps render at the bottom of the flow as they do today.

**Files**: `WhatIfTool.tsx` (line 611, restructure the `<div className="space-y-4">` wrapper)

**Step 2.2: Weight Sum Indicator**

No running total while editing weights. Add a weight sum badge:
- Compute `totalWeight = sum of all weight inputs`
- Show as a badge near the input header: "Total: 99.7%"
- Color: emerald if 98-102%, amber if 90-98% or 102-110%, red otherwise
- Only in Weights mode (deltas don't sum to 100%)

**Data source**: Computed from `weightInputs` values
**Files**: `WhatIfTool.tsx`

**Step 2.3: Consolidate Exit Ramps into Sticky Footer**

Currently duplicated: "Backtest allocation →" in insight banner AND "Backtest this →" at bottom (line 677). Different labels, same action. Bottom ramps are below the fold, easily missed.

Fix:
- Move exit ramps from the bottom of the page (`WhatIfTool.tsx:677-704`) into the sticky panel's fixed footer (see Step 2.1 split layout). This makes them always visible regardless of scroll position.
- Remove the separate `<div className="flex flex-wrap gap-3">` wrapper at line 677
- Rename insight banner action from "Backtest allocation" to "Backtest this" — same label everywhere, no duplication
- All 3 exit ramp labels standardized: "Backtest this", "Simulate forward", "Generate trades"

**Files**: `WhatIfTool.tsx` (lines 677-704 move into sticky footer)

~~**Step 2.4: Mode Switch State Preservation**~~ **DROPPED (R1 finding #2)**

Codex confirmed the hook already keeps separate `weightInputs` and `deltaInputs` in state (`useWhatIfAnalysis.ts:60-62`). `setInputMode` does NOT reinitialize inputs — only the explicit `initWeightInputs`/`initDeltaInputs` helpers do. Existing test at `useWhatIfAnalysis.test.tsx:134` verifies this. The apparent "reset" observed during browser testing was likely the component's seed effect (`WhatIfTool.tsx:247-296`) re-firing on mode change. If a real UX regression exists, it will surface during browser verification and be fixed as a targeted polish item with the actual root cause identified.

## Architecture — Component Extraction

`WhatIfTool.tsx` is already 707 lines. Adding 4 new result sections inline would push it past 1000. Extract new sections as dedicated sub-components in `scenarios/tools/whatif/`:

```
scenarios/tools/WhatIfTool.tsx          — orchestrator (input card + sticky panel layout)
scenarios/tools/whatif/PositionChangesSection.tsx   — Step 1.1 (collapsible position table)
scenarios/tools/whatif/RiskLimitChecksSection.tsx   — Step 1.2 (comparison_analysis table)
scenarios/tools/whatif/FactorExposuresSection.tsx   — Step 1.3 (factor delta table)
scenarios/tools/whatif/RiskChecksSection.tsx         — Step 1.4 (enriched violation details)
```

**Do NOT extend `ScenarioResultsPanel`** — it only supports homogeneous `ScenarioMetricRow[]` with numeric values (`ScenarioResultsPanel.tsx:16`). The new sections render heterogeneous data (position tables, factor maps, violation records) and need their own rendering logic. Follow the pattern in `StockLookupContainer.tsx:749-757` where view-specific sections are purpose-built rather than overloading shared components.

Keep the existing `ScenarioResultsPanel` for the primary 4-metric summary (vol, HHI, factor var, idio var).

## Key Files

| Layer | File | Changes |
|-------|------|---------|
| Frontend orchestrator | `frontend/packages/ui/.../scenarios/tools/WhatIfTool.tsx` (707 lines) | Phase 2: sticky split layout, weight sum, exit ramp consolidation. Phase 1: compose new sub-components |
| New sub-components | `frontend/packages/ui/.../scenarios/tools/whatif/*.tsx` (4 files) | Phase 1: position changes, risk limits, factor exposures, risk checks sections |
| New test file | `frontend/packages/ui/.../scenarios/tools/__tests__/WhatIfTool.test.tsx` | Targeted component tests (see Verification) |
| Shared (unchanged) | `ScenarioResultsPanel.tsx` | Keep as-is for primary 4-metric summary |
| Backend (NO CHANGES) | `core/result_objects/whatif.py`, `app.py`, `services/scenario_service.py` | Already returns all needed data |

## What's NOT in Scope

- Expected return delta (requires backend computation — deferred to methodology phase)
- Before/after weight bar chart visualization (deferred to Step 6 visual polish)
- Mode switch state investigation (hook is correct per Codex R1 finding #2 — if UX issue persists, fix in polish)
- MCP template param (minor agent convenience — not user-facing)
- Optimize ↔ What-If inbound path (cross-view architecture — A7 scope)

## Verification

### 1. New Component Tests

Create `frontend/packages/ui/src/components/portfolio/scenarios/tools/__tests__/WhatIfTool.test.tsx` with targeted coverage:

- **PositionChangesSection**: renders sorted by absolute change; shows top 5 by default; expands to show all; handles empty `position_changes` array
- **RiskLimitChecksSection**: renders `comparison_analysis.risk_comparison` rows with Old/New/Delta; handles missing data gracefully
- **FactorExposuresSection**: renders factor deltas sorted by absolute delta; handles `factor_exposures_comparison` being `{}` or missing
- **RiskChecksSection**: renders combined risk + factor + proxy violations; "View all checks" expander shows `risk_checks`, `factor_beta_checks`, `proxy_beta_checks`; card border is red when violations > 0
- **Sticky layout**: exit ramps render inside the sticky footer, not in the outer page flow
- **Weight sum badge**: renders correct total and color class for 100%, 95%, 110%, 0%

### 2. Existing Tests

Run existing hook tests to confirm no regressions:
```
cd frontend && pnpm exec vitest run packages/connectors/src/features/whatIf/__tests__/useWhatIfAnalysis.test.tsx
```

### 3. TypeScript

```
cd frontend && pnpm exec tsc --noEmit
```

### 4. Browser Verification

Navigate to `localhost:3000/#scenarios/what-if`:

**Happy path** — run Equal Weight template:
- Verify position changes table shows tickers sorted by largest absolute change
- Verify risk limit checks table shows all risk-limit metrics with Old/New/Delta
- Verify factor exposure table shows top factor deltas
- Verify risk checks show Pass/Pass with "View all checks" expander
- Verify results panel sticks when scrolling the 27-ticker input list (xl viewport)
- Verify exit ramps are pinned at bottom of sticky panel, always visible
- Verify weight sum badge shows ~99.9% in emerald

**Failure path** — run Concentrated Growth template (or manually set one ticker to 90%+):
- Verify risk checks show Fail state with violation details expanded
- Verify violation count includes risk + beta + proxy failures (total, not just risk)
- Verify insight banner shows amber/red with specific failing metrics
- Verify card border turns red/amber on violations

**E2E (Playwright)**: The repo has Playwright infrastructure (`e2e/playwright.config.ts`) and an existing What-If scenario spec at `e2e/tests/scenario-rebalance-workflow.spec.ts:475` that mocks `**/api/what-if` and exercises the What-If workflow. Extend this existing spec to cover the new result sections:
- Add a test case with a mock API response containing `risk_analysis.risk_violations` (non-empty) to verify violation UI renders
- Add a test case verifying position changes table renders and sorts correctly
- Add a test case verifying factor exposures section renders when `factor_exposures_comparison` is present in the response

### 5. State Persistence

Navigate away (e.g., to Backtest) and back — results + inputs should persist via `toolRunParams`.

### 6. MCP Unchanged

Run `run_whatif(delta_changes={"AAPL": "+5%"})` — verify agent format response shape unchanged (snapshot + flags).

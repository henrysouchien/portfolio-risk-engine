# Tax Harvest Tool — Frontend Implementation Plan

## Context

Tax Harvest (A5c) is the last scenario tool still showing a placeholder in the frontend. The backend is production-ready: MCP tool (`mcp_tools/tax_harvest.py`, 1122 lines), REST endpoint (`POST /api/tax-harvest`), agent format with snapshot + flags, adapter, resolver, hook, and tests all exist. The only missing piece is the actual `TaxHarvestTool.tsx` component and its router wiring.

This is a **scanner-style tool** (like Stress Test) — the user hits "Run", the tool scans their portfolio for tax-loss harvesting opportunities, and results are displayed for evaluation. Input is lightweight (optional filters); results are the star.

---

## Design Direction

**User mental model**: "Show me which losing positions I should sell to offset taxable gains, and flag any wash sale risks." This is a discovery tool, not a configuration tool.

**Reference pattern**: StressTestTool — run button, verdict insight, metrics strip, position table, exit ramps. Adapted for tax harvest data shape.

**Sections (top to bottom)**:

1. **Header + Controls** — Title, optional min loss filter, Run button
2. **Insight Card** — `ScenarioInsightCard` with verdict ("$5,500 harvestable across 10 lots"), color-coded: emerald if no losses found (clean bill), blue if harvestable losses exist, amber if wash sale risks present
3. **Summary Metrics Strip** — 4-column strip: Total Harvestable Loss | Short-Term | Long-Term | Data Coverage
4. **Candidates Table** — Top 5 tickers (aggregated by ticker, capped by backend) ranked by loss amount. Columns: Ticker, Loss ($), Lots, Holding Period (ST/LT pills), Wash Sale Risk (badge).
5. **Wash Sale Warnings** — Collapsible section listing wash sale tickers + top-level warning messages from `_metadata.warnings` (no per-ticker reason structure in the frontend data contract — the adapted type only exposes `washSaleTickers: string[]` and `_metadata.warnings: string[]`)
6. **Exit Ramps** — "Go to Trading" (sell the losers), "Ask AI about this" (on insight card)

---

## File Inventory

### New Files

| File | Purpose |
|------|---------|
| `frontend/packages/ui/src/components/portfolio/scenarios/tools/TaxHarvestTool.tsx` | Main tool component (~300–400 lines) |

### Modified Files

| File | Change |
|------|--------|
| `frontend/packages/ui/src/components/portfolio/scenarios/ScenariosRouter.tsx` | Replace `TaxHarvestPlaceholder` with lazy-loaded `TaxHarvestTool` |

---

## Implementation Details

### 1. `TaxHarvestTool.tsx`

**Props** (matches all other tools):
```typescript
interface TaxHarvestToolProps {
  context: Record<string, unknown>
  onNavigate: (tool: SelectableScenarioTool, context?: Record<string, unknown>) => void
}
```

**Hooks used**:
- `useTaxHarvest()` — data fetching, `runTaxHarvest()`, loading/error/flags/hasPortfolio (`frontend/packages/connectors/src/features/taxHarvest/hooks/useTaxHarvest.ts`)
- `usePositions()` — portfolio positions for empty-holdings check (`@risk/connectors`). Returns `{ data: PositionsData | undefined, ... }` where the array is at `data.holdings`. `taxHarvest.hasPortfolio` only checks if a portfolio object exists, not if it has positions. Use `positions.data?.holdings?.length > 0` as the actual "has holdings" guard.
- `useScenarioChatLauncher()` — "Ask AI" action (`frontend/packages/ui/src/components/portfolio/scenarios/useScenarioChatLauncher.ts`)
- `useToolRunParams()` — persist filter state across navigation (`@risk/connectors`)
- `useToolContract()` — workflow integration (`@risk/connectors`, see `features/scenario/toolContract.ts`)
- `useWorkflowStepCompletion()` — mark step complete (`frontend/packages/ui/src/components/portfolio/scenarios/useWorkflowStepCompletion.ts`)
- `useCurrentPortfolio()` — current portfolio ID for cache key validation (`@risk/chassis`)
- `useState` — local: `minLoss`

**Note on `useScenarioState`**: This hook requires 6 args (whatIfData, stressTestData, etc.) and is overkill here. Tax harvest only needs `hasPortfolio` (from `useTaxHarvest()`) and holdings (from `usePositions().data?.holdings`). Do NOT use `useScenarioState`.

**Pre-run state**:
- Metrics strip shows dashed placeholder: "Run a scan to find harvestable losses"
- Candidates table shows: "Run the scanner to see tax-loss candidates"
- No insight card

**Post-run state**:
- Insight card appears with verdict text from backend
- Metrics strip populates with real values
- Candidates table shows top candidates (up to 5 tickers — backend aggregates lots by ticker and caps at 5)
- Wash sale section appears if any warnings
- Exit ramps become actionable

**Error state**:
- Red border card with error message (matches StressTest pattern): `rounded-2xl border border-red-200 bg-red-50 px-4 py-3`
- Text: `taxHarvest.error` message, `text-sm text-red-700`

**Loading state**:
- Run button text: "Running..." with disabled state
- No skeleton cards (scan is typically fast, <5s)

**Empty portfolio state**:
- Dashed placeholder: "Load a portfolio to run the tax harvest scanner"
- Run button disabled

**Insight card logic**:
```
if candidateCount === 0 → colorScheme="emerald", icon=CheckCircle, "No harvestable losses found"
if washSaleTickerCount > 0 → colorScheme="amber", icon=AlertTriangle, verdict + wash sale warning
else → colorScheme="blue", icon=Scissors, verdict text from backend
```

Apply system flag overlay via `applyScenarioSignalToInsight()` from `scenarioSignals.ts`.

**System flags**: Since `useTaxHarvest()` does not expose `quality` (required by `buildScenarioSystemFlags()`), build flags directly from `taxHarvest.flags` without using `buildScenarioSystemFlags`:
```typescript
const systemFlags: ScenarioChatFlag[] = useMemo(() =>
  mergeScenarioChatFlags(
    taxHarvest.flags.map(f => ({ type: f.name, severity: f.severity, message: f.message }))
  ),
  [taxHarvest.flags]
)
```

**Metrics strip** (4-column, matches StressTest `ImpactSummary` pattern):
- Total Harvestable Loss — `formatCurrency(totalHarvestableLoss)`, red tint bg
- Short-Term Losses — `formatCurrency(shortTermLoss)`
- Long-Term Losses — `formatCurrency(longTermLoss)`
- Data Coverage — `${dataCoveragePct}%`, amber tint if <75%

Each column: label `text-[10px] font-medium uppercase tracking-[0.18em] text-muted-foreground`, value `text-base font-semibold tabular-nums`. Columns separated by `w-px bg-border/50` dividers. Container: `rounded-xl border border-border/60 bg-card overflow-hidden`.

**Candidates table**:
- **Data contract**: `topCandidates` is capped at 5 aggregated tickers (backend groups lots by ticker). `candidateCount` is the total number of underlying lots, not ticker rows. The table renders all `topCandidates` (up to 5 rows) with a header like "Top 5 tickers from {candidateCount} lots".
- Columns: Ticker | Loss | Lots | Period | Wash Sale Risk
- Period shows pills based on `holdingPeriods` array:
  - `"short_term"` → amber `Badge` with text "ST"
  - `"long_term"` → neutral `Badge` with text "LT"
  - Any other value (e.g., `"unknown"`) → slate `Badge` with text "?"
  - If a ticker has both ST and LT lots, show both pills
- Wash sale shows red badge if `washSaleRisk === true`
- No "Show all" toggle needed (max 5 rows from backend)
- Container: `Card` with `rounded-2xl border border-border/70 bg-card shadow-none`
- Row styling: `border-b border-border/40 last:border-0 hover:bg-muted/30 transition-colors`
- Loss values: `text-red-700 tabular-nums`

**Filter controls** (inline with Run button, single row):
- Min loss: `Input` number field, placeholder "$0", `rounded-2xl h-11`. Passed as `minLoss` to `runTaxHarvest()`.
- Run button: `variant="premium"`, `rounded-full px-5 h-11`, Play icon, "Run Scanner" / "Running..."
- Disabled when: `!taxHarvest.hasPortfolio || !positions.data?.holdings?.length || taxHarvest.isLoading`

Where `positions` comes from `usePositions()`. `usePositions()` returns `{ data: PositionsData | undefined, ... }` and the array is at `data.holdings`. This covers both "no portfolio selected" and "portfolio exists but has no holdings".

**Note on sort_by**: The backend `sort_by` param controls which lots are selected for the top-5 snapshot, but the adapted frontend data (`topCandidates`) only contains `totalLoss` — not `loss_pct` or `days_held`. A frontend sort dropdown would be misleading since the user can't see the sort values. **Remove the sort_by dropdown** from the UI. The backend default (`loss_amount`) is the right default. If sort control is needed later, the adapter would need to be extended to include per-candidate `lossPct` and `daysHeld`.

**Exit ramps** (below main card, matches StressTest pattern):
- "Go to Trading" — `ExitRampButton`, navigates to the dashboard trading view via `useUIStore.getState().setActiveView("trading")` (NOT a scenario tool navigation — trading is a dashboard view, not a scenario tool). Disabled if no candidates (`candidateCount === 0`). No trade intent prefill in this version (would require extending `tradingIntentStore` — deferred).
- "Ask AI about this" — on `ScenarioInsightCard` secondary action, launches scenario chat with tax harvest context via `useScenarioChatLauncher()`

**Card variants** (matching reference tools):
- Outer container: `variant="glass"` `rounded-3xl border border-border/60 bg-card/80 shadow-sm`
- Metrics strip: `rounded-xl border border-border/60 bg-card overflow-hidden`
- Candidates table: `rounded-2xl border border-border/70 bg-card shadow-none`
- Wash sale section: `Collapsible`, trigger `rounded-xl border border-border/60 bg-muted/50 px-3 py-2`
- Empty states: `rounded-2xl border border-dashed border-border bg-muted px-4 py-8 text-center`

**State persistence via `useToolRunParams()`**:

Key: `"tax-harvest:ui"` (matches the `:ui` suffix pattern used by other tools like StressTest's `stress-test:ui`).

```typescript
interface TaxHarvestUiCache {
  portfolioId: string
  minLoss: number | null
}
```

**Persistence pattern** (reactive via `useEffect`, matching StressTestTool):
1. **Restore on mount**: `useEffect` reads `toolRunParams["tax-harvest:ui"]`, validates `portfolioId` matches current portfolio, restores `minLoss` if valid
2. **Sync on change**: `useEffect` writes `{ portfolioId, minLoss }` to `toolRunParams["tax-harvest:ui"]` whenever `minLoss` or `portfolioId` changes — but only if `portfolioId` is defined (guard: `if (!portfolioId) return`). This persists unrun filter edits across navigation (not just on run)
3. **Reset on portfolio change**: `useEffect` watches `portfolioId` — if it changes, reset local `minLoss` state to `null` and clear the cache entry. This prevents stale filters persisting after portfolio switch, complementing the `useTaxHarvest` hook's own data reset

**Tool contract** (for workflow integration, matches `UseToolContractOptions` from `features/scenario/toolContract.ts`):
```typescript
const toolContract = useToolContract({
  hasData: taxHarvest.hasData,
  isLoading: taxHarvest.isLoading || taxHarvest.isRefetching,
  error: taxHarvest.error,
  riskMetrics: {
    totalHarvestableLoss: taxHarvest.data?.totalHarvestableLoss ?? undefined,
  },
  flags: systemFlags,
  raw: taxHarvest.data,
  summary: taxHarvest.hasData
    ? `Tax harvest scan complete. ${taxHarvest.data?.verdict ?? ""}`
    : undefined,
  metrics: {
    candidateCount: taxHarvest.data?.candidateCount ?? null,
    totalHarvestableLoss: taxHarvest.data?.totalHarvestableLoss ?? null,
    washSaleTickerCount: taxHarvest.data?.washSaleTickerCount ?? null,
  },
})

useWorkflowStepCompletion("tax-harvest", toolContract.status === "complete", toolContract.stepOutput)
```

### 2. `ScenariosRouter.tsx` Changes

```diff
+ const TaxHarvestTool = lazy(() => import("./tools/TaxHarvestTool"))

- function TaxHarvestPlaceholder() {
-   return (
-     <Card variant="glass" className="rounded-3xl border border-neutral-200/60 bg-white/80 shadow-sm">
-       <CardContent className="flex min-h-[280px] items-center justify-center p-8 text-center">
-         <div className="space-y-3">
-           <p className="text-xs font-medium uppercase tracking-[0.2em] text-neutral-500">Phase 3a fallback</p>
-           <h3 className="text-2xl font-semibold tracking-tight text-neutral-900">Tax Harvest Scanner</h3>
-           <p className="text-sm text-neutral-600">Tax Harvest Scanner — Coming in Phase 3d</p>
-         </div>
-       </CardContent>
-     </Card>
-   )
- }

  // In fallbackByTool:
- "tax-harvest": <TaxHarvestPlaceholder />,
+ "tax-harvest": <TaxHarvestTool context={toolContext} onNavigate={setActiveTool} />,
```

Delete the `TaxHarvestPlaceholder` function entirely. Remove the `Card`/`CardContent` imports if they were only used by the placeholder (check other usages first — they aren't used elsewhere in this file so they can be removed).

---

## Reuse Inventory

| What | From | How |
|------|------|-----|
| `ScenarioInsightCard` | `scenarios/shared/ScenarioInsightCard.tsx` | Insight verdict display |
| `ExitRampButton` | `scenarios/shared/ExitRampButton.tsx` | Exit ramp buttons |
| `usePositions` | `@risk/connectors` | Portfolio positions for empty-state check |
| `useUIStore` | `@risk/connectors` | `setActiveView("trading")` for exit ramp |
| `useScenarioChatLauncher` | `scenarios/useScenarioChatLauncher` | AI chat integration |
| `useToolRunParams` | `@risk/connectors` | State persistence |
| `useToolContract` | `@risk/connectors` | Workflow contract |
| `useWorkflowStepCompletion` | `scenarios/useWorkflowStepCompletion` | Workflow step |
| `applyScenarioSignalToInsight` | `scenarios/scenarioSignals` | System flag overlay |
| ~~`buildScenarioSystemFlags`~~ | ~~`scenarios/scenarioSignals`~~ | NOT USED — requires `quality` which `useTaxHarvest` doesn't expose. Build flags directly from `taxHarvest.flags` via `mergeScenarioChatFlags` |
| `mergeScenarioChatFlags` | `scenarios/scenarioSignals` | Chat flag merge |
| `formatCurrency` | `scenario/helpers` | Currency formatting |
| `Card/CardHeader/CardContent/CardTitle` | `ui/card` | Card primitives |
| `useCurrentPortfolio` | `@risk/chassis` | Portfolio ID for cache validation |
| `Button` | `ui/button` | Buttons |
| `Badge` | `ui/badge` | Holding period / wash sale badges |
| `Input` | `ui/input` | Min loss filter |
| `Collapsible/CollapsibleContent/CollapsibleTrigger` | `ui/collapsible` | Wash sale section |
| `useTaxHarvest` | `@risk/connectors` | Hook (already exists, 108 lines) |
| `TaxHarvestSourceData` | `@risk/chassis` catalog types | TypeScript type for adapted data |

---

## What This Plan Does NOT Include

- **No backend changes** — engine, MCP tool, REST endpoint, adapter, resolver, hook all exist and are tested
- **No new shared components** — reuses existing ScenarioInsightCard, ExitRampButton, etc.
- **No methodology changes** — backend FIFO + wash sale logic is solid
- **No workflow definition** — `useToolContract` + `useWorkflowStepCompletion` are wired for contract compliance, but tax harvest is not added to any workflow definition (A6 scope)
- **No cross-view context passing** — inbound context (e.g., from positions view) deferred to A7 chaining architecture
- **No resolver `quality` in system flags** — `useTaxHarvest()` doesn't expose the resolver's `quality` field (partial/stale/error). System flags are built from `taxHarvest.flags` only. To surface quality signals, `useTaxHarvest` would need extending — deferred as follow-up.
- **No new tests** — existing adapter/hook/resolver tests cover the data layer; component tests can be added in a follow-up

---

## Verification

1. **TypeScript**: `cd frontend && npx tsc --noEmit` — zero errors
2. **Browser**: Navigate to Scenarios → Tax Harvest card → verify tool loads (not placeholder)
3. **Run scan**: Click "Run Scanner" with loaded portfolio → verify insight card, metrics, candidates table populate
4. **Empty state**: Verify pre-run shows dashed placeholders with helpful text
5. **Min loss filter**: Set min loss to a value → re-run → verify fewer candidates appear
6. **Wash sale badges**: Verify red badges appear on candidates with wash sale risk
7. **Exit ramps**: Click "Go to Trading" → navigates. Click "Ask AI" → opens chat.
8. **State persistence**: Navigate away → navigate back → verify params restored via toolRunParams
9. **Portfolio switch**: Switch portfolio → verify data resets (useTaxHarvest handles data) AND filter state resets (UI cache portfolioId validation handles minLoss)
10. **Existing tests**: `npx vitest run` — all existing adapter/hook/resolver tests still pass

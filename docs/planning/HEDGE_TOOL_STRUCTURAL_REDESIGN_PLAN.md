# Hedge Analysis Tool — Structural Redesign Plan

> **Codex review**: R1 FAIL (2H/4M/2L) → R2 FAIL (1H/3M) → R3 FAIL (1H/2M) → R4 FAIL (1H/1M) → R5 FAIL (0H/1M) → **R6 PASS**

## Context

The Hedge Analysis tool (A5d) has solid backend methodology (factor-first Diagnose → Prescribe → Quantify, landed in `073ec3c5`) but the frontend is unpolished compared to the other scenario tools (MC, BT, WI, Opt) that have been through the full audit playbook. Visual audit revealed:

- **No charts** — violates design principle #2 ("charts are the hero content")
- **Heavy per-strategy tile grids** — 4 bordered tiles × ~8 strategies = ~32 tiles, all with equal visual weight
- **Redundant title card** — takes above-the-fold space saying what the breadcrumb already says
- **No section separators** — diagnosis and recommendations bleed together
- **3 action buttons per strategy × 8 strategies** = 24+ competing CTAs
- **F7 bug visible** — driver labels show ETF tickers ("DSU") instead of readable names
- **669% portfolio vol** — F10 upstream data quality, needs capping/formatting guard
- **Page is ~3100px tall** — every strategy is expanded with full tile grid

## Design Direction

Transform the tool from a verbose card-per-strategy layout into a compact, narrative-flow layout matching the polished scenario tools. Key moves:

1. **Add a risk decomposition bar chart** as the hero visual between diagnosis and recommendations
2. **Replace per-strategy 4-tile grids with a compact table** per driver (one row per strategy)
3. **Merge title card into the flow** — remove redundant glass header card
4. **Add separators** between diagnosis and recommendations sections
5. **Collapse secondary drivers** — only the top driver expanded by default
6. **Reduce buttons** — table row actions instead of 3 buttons per card

## Section Order (Redesigned)

```
DIAGNOSIS (section label)
What is driving portfolio risk (section title)

ScenarioInsightCard (size="lg", "Ask AI about this")

Risk Decomposition Bar Chart (horizontal bars: variance share by driver)
  ─ hero visual, shows risk contribution per driver at a glance

Metrics Strip (horizontal: Portfolio Vol | Market Beta | Factor Variance % | Top Driver)
  ─ TaxHarvest-style compact inline strip with dividers

─── border-t separator ───

PER-DRIVER RECOMMENDATIONS (section label)

Driver 1: [Name] — [X%] of portfolio risk    [proxy badge]
  ├─ Direct Offset section (collapsible if empty or single)
  │   └─ Compact table: Ticker | Weight | Key Metric | Efficiency | Actions
  ├─ Beta Alternatives section
  │   └─ Compact table: Ticker | Weight | Factor Beta | Sharpe | Efficiency | Actions
  └─ Diversification section
      └─ Compact table: Ticker | Weight | Correlation | Sharpe | Efficiency | Actions

─── border-t separator ───

Driver 2: [Name] — collapsed by default (Collapsible)
Driver 3: [Name] — collapsed by default (Collapsible)

─── border-t separator ───

Exit ramp: "Go to Trading" (uses setActiveView, not onNavigate)
```

## Detailed Changes

### 1. Remove redundant title card

**File**: `frontend/packages/ui/src/components/portfolio/scenarios/tools/HedgeTool.tsx`

Slim down the outer `<Card variant="glass">` header block (lines 428–440). Remove the title and description (redundant with breadcrumb), but **preserve the imported context banner** (lines 434–438) which surfaces Stress Test → Hedge handoff context. Move the `importedLabel` banner to render above the insight card, outside the removed header card.

**Note**: Monte Carlo and Tax Harvest do still use top header cards for inputs/controls, so this isn't removing a universal pattern — it's removing a card that only contains a title and description with no controls.

### 2. Add Risk Decomposition Bar Chart

**File**: `HedgeTool.tsx` (new section after insight card)

**Single-bar horizontal bar chart** using Recharts `BarChart` with `layout="vertical"`. Shows variance share per driver (sorted descending), giving a visual hierarchy of where portfolio risk is concentrated.

Data: `diagnosis.industryVarianceShare` (already available). `drivers[].percentOfPortfolio` is variance share (not portfolio weight), so a dual risk-vs-weight chart is NOT feasible without backend changes. The single-bar variance share chart is the right scope — it answers "where is risk coming from?" which is the tool's core question.

```
Chart height: 200px (3–5 drivers × ~40px + margins)
Pattern: RiskWeightChart from rebalance/ (same Recharts BarChart, vertical layout)
  Reference: frontend/packages/ui/src/components/portfolio/scenarios/tools/rebalance/RiskWeightChart.tsx
Container: rounded-xl bg-card border border-border/60 p-4
Bar color: amber (#f59e0b) for variance share
```

Include all drivers from `diagnosis.industryVarianceShare` (not just `topRiskDrivers.slice(0, 3)`), capped at 6 to avoid excessive chart height. Labels are driver names (which will show ETF tickers until F7 is fixed — acceptable for now, same data as the tiles below).

**Market-only fallback**: If `diagnosis.industryVarianceShare` is empty but `hasData` is true (market-only driver scenario where recommendations exist but no industry decomposition), hide the bar chart entirely. The insight card and metrics strip still render with `diagnosis.marketBeta` and `diagnosis.varianceDecomposition.factor_pct`. The chart is additive, not required — graceful degradation when industry data is absent.

### 3. Replace diagnosis KPI tiles with metrics strip

**File**: `HedgeTool.tsx` (replace lines 494–514)

Replace the 4-tile `grid` with TaxHarvest-style horizontal strip:

```
flex items-stretch overflow-hidden rounded-xl border border-border/60 bg-card
├─ Portfolio Vol | divider | Market Beta | divider | Factor Risk | divider | Top Driver
```

Each cell: `flex-1 px-4 py-2.5` with `text-[10px] uppercase tracking-[0.18em]` label and `text-base font-semibold tabular-nums` value.

Add a display guard for Portfolio Vol: if > 200%, show with amber background (`bg-amber-50/60`) and append a tooltip explaining upstream data quality.

### 4. Add border-t separator between Diagnosis and Recommendations

**File**: `HedgeTool.tsx`

Add `<div className="border-t border-border" />` between the diagnosis section and the per-driver section. Design principle #7.

### 5. Compact strategy tables (biggest structural change)

**File**: `HedgeTool.tsx` (replace lines 573–679)

Replace the per-strategy card+4-tile+3-button pattern with a compact table per section:

Wrap in responsive container matching TaxHarvest pattern:

```jsx
<div className="overflow-x-auto">
  <table className="w-full min-w-[600px] text-sm">
    <thead>
      <tr className="border-b border-border/50 text-left">
        <th className="pb-3 pl-3 font-medium text-muted-foreground">Ticker</th>
        <th className="pb-3 font-medium text-muted-foreground">Weight</th>
        <th className="pb-3 font-medium text-muted-foreground">Key Metric</th>
        <th className="pb-3 font-medium text-muted-foreground">Efficiency</th>
        <th className="pb-3 pr-3 text-right font-medium text-muted-foreground">Actions</th>
      </tr>
    </thead>
    <tbody>
      {sectionStrategies.map((strategy) => {
        const strategyKey = getStrategyKey(strategy)
        const isExpanded = expandedRows.has(strategyKey)
        return (
          <React.Fragment key={strategyKey}>
            <tr
              className="border-b border-border/40 transition-colors last:border-0 hover:bg-muted/30 cursor-pointer"
              onClick={() => toggleRowExpansion(strategyKey)}
            >
              <td className="py-3 pl-3">
                <div className="flex items-center gap-1.5">
                  <ChevronDown className={`h-3.5 w-3.5 text-muted-foreground transition-transform ${isExpanded ? "rotate-180" : ""}`} />
                  <span className="font-medium text-foreground">{strategy.hedgeTicker}</span>
                </div>
              </td>
              <td className="py-3 tabular-nums">{formatWeightPercent(strategy.suggestedWeight)}</td>
              <td className="py-3">
                <span className="text-xs text-muted-foreground">{strategy.primaryMetric.label}: </span>
                <span className="font-medium">{strategy.primaryMetric.value}</span>
              </td>
              <td className="py-3">
                <Badge className={getEfficiencyBadgeClass(strategy.efficiency)}>{strategy.efficiency}</Badge>
              </td>
              <td className="py-3 pr-3 text-right">
                <div className="flex justify-end gap-1.5" onClick={(e) => e.stopPropagation()}>
                  <Button size="sm" variant="ghost" className="h-7 rounded-full px-3 text-xs" onClick={() => handleTestInWhatIf(strategy)}>
                    What-If
                  </Button>
                  <Button size="sm" variant="premium" className="h-7 rounded-full px-3 text-xs" onClick={() => setSelectedHedge(strategy)}>
                    Execute
                  </Button>
                </div>
              </td>
            </tr>
            {isExpanded && (
              <tr>
                <td colSpan={5} className="bg-muted/20 px-3 pb-3 pt-2">
                  {/* Inline preview: reuses buildPreviewRows() + requestPreview mutation */}
                </td>
              </tr>
            )}
          </React.Fragment>
        )
      })}
    </tbody>
  </table>
</div>
```

Each strategy row: ~40px vs current ~200px.

**Row expansion for Quantify Impact**: Clicking the row toggles expansion via a small chevron in the Ticker column. The expanded area shows a preview strip with Volatility/Beta/Concentration current→scenario→delta, reusing `buildPreviewRows()` and `requestPreview` mutation. The existing `previewByStrategy` cache is reused — preview is only fetched on first expansion if not already cached. Action buttons in the last column use `e.stopPropagation()` to prevent row toggle when clicking What-If or Execute.

**State management**:
- `expandedRows`: `useState<Set<string>>(() => new Set())` — tracks which strategy rows are expanded
- `previewPendingKeys`: `useState<Set<string>>(() => new Set())` — tracks per-row pending state (replaces single `previewPendingKey` to support multiple concurrent expansions)
- `generationRef`: `useRef(0)` — monotonic counter, incremented on every data change. Used to guard against stale preview responses.

**Full state reset on data change**: Use a `useEffect` that watches a `diagnosisIdentity` string derived from the same inputs the hedging query uses: `stressTest.currentPortfolio?.id`, `hedgingWeights` (JSON-stringified or via `useMemo` hash), and `portfolioValue`. This matches `useHedgingRecommendations`' actual query key (`portfolioId`, `weights`, `portfolioValue` in `useHedgingRecommendations.ts:44`). Construct a stable identity string using sorted keys to avoid spurious resets from object key reordering: `const diagnosisIdentity = useMemo(() => { const sortedWeights = Object.keys(hedgingWeights).sort().map(k => k + ":" + hedgingWeights[k]).join(","); return stressTest.currentPortfolio?.id + "|" + sortedWeights + "|" + portfolioValue; }, [stressTest.currentPortfolio?.id, hedgingWeights, portfolioValue])`. This produces a canonical string that only changes when the actual inputs to the hedging query change, not on harmless key reordering. Unnecessary resets are safe (just re-expand the first driver and clear previews) but this avoids them. When it fires:
  - `generationRef.current += 1` — bump generation counter
  - `setExpandedRows(new Set())`
  - `setPreviewByStrategy({})` — clears stale preview data
  - `setPreviewErrorByStrategy({})`
  - `setPreviewPendingKeys(new Set())`
  - `setExpandedDrivers(...)` — reset to only the first driver (see §6)

**Late response guard**: When calling `requestPreview`, capture `const gen = generationRef.current` before the mutation. In `onSuccess`/`onError` callbacks, check `if (gen !== generationRef.current) return` — this discards responses from a previous diagnosis that arrive after a portfolio switch. This is the standard stale-closure guard for mutations.

**Per-row pending state**: `previewPendingKeys` is a `Set<string>`. On preview request: `setPreviewPendingKeys(prev => new Set(prev).add(strategyKey))`. On success/error (after generation guard): `setPreviewPendingKeys(prev => { const next = new Set(prev); next.delete(strategyKey); return next })`. This allows multiple rows to show loading indicators concurrently.

Preview cache persists across expand/collapse cycles within the same diagnosis run — only resets on data change.

### 6. Collapsible secondary drivers

**File**: `HedgeTool.tsx`

First driver (highest variance share): expanded by default.
Drivers 2+: wrapped in `<Collapsible>` with trigger showing driver name + variance share + strategy count. Uses the established pattern from TaxHarvest/MC.

```jsx
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "../../../ui/collapsible"

// For each driver after the first:
<Collapsible open={expandedDrivers.has(group.driverLabel)} onOpenChange={(open) => toggleDriver(group.driverLabel, open)}>
  <CollapsibleTrigger asChild>
    <button className="flex w-full items-center justify-between gap-3 rounded-xl border border-border/60 bg-muted/50 px-4 py-3 text-left">
      <div className="space-y-0.5">
        <div className="text-base font-semibold text-foreground">{group.driverLabel}</div>
        <div className="text-xs text-muted-foreground">
          {shareLabel} · {totalStrategies} strategies
        </div>
      </div>
      <div className="flex items-center gap-2">
        {group.driverProxyTicker && <Badge variant="outline">{group.driverProxyTicker}</Badge>}
        <ChevronDown className={`h-4 w-4 text-muted-foreground transition-transform ${expanded ? "rotate-180" : ""}`} />
      </div>
    </button>
  </CollapsibleTrigger>
  <CollapsibleContent>
    {/* Driver sections + tables rendered here */}
  </CollapsibleContent>
</Collapsible>
```

State: `const [expandedDrivers, setExpandedDrivers] = useState<Set<string>>(() => new Set())`

**Auto-expand first driver + reset on data change**: Use a **separate** `useEffect` that watches `groupedStrategies[0]?.driverLabel` (not the diagnosisIdentity key). This is because `groupedStrategies` is empty while the query is loading (`useHedgingRecommendations` returns empty `drivers` until data resolves), so the effect must re-run when resolved data arrives, not just when the query key changes. When it fires:
1. `setExpandedDrivers(new Set(groupedStrategies[0]?.driverLabel ? [groupedStrategies[0].driverLabel] : []))`

Dep: `[groupedStrategies[0]?.driverLabel]` — stable string primitive, only changes when first driver identity changes (initial load, portfolio switch, re-diagnosis). This ensures: (a) the first driver is always expanded once data loads, (b) after a portfolio switch, stale driver labels are cleared and the new first driver is expanded, (c) no driver is expanded if `groupedStrategies` is empty during loading.

### 7. Reduce action buttons to 2 per row

- **"What-If"** — ghost button, navigates to What-If with delta context (reuses `handleTestInWhatIf`)
- **"Execute"** — premium button, opens HedgeWorkflowDialog (reuses `setSelectedHedge`)
- **"Quantify Impact"** — becomes row expansion (click the row or a small chevron to expand inline preview below the row)

### 8. Add exit ramps at bottom

After all drivers, add a footer section with `ExitRampButton` components:
- "Go to Trading" — navigates to the Trading view using `useUIStore.getState().setActiveView("trading")` (NOT `onNavigate` — Trading is a top-level view, not a scenario tool). This matches the pattern in TaxHarvestTool.tsx and OptimizeTool.tsx.

```jsx
import ExitRampButton from "../shared/ExitRampButton"
import { useUIStore } from "@risk/connectors"

<div className="border-t border-border/50 pt-4">
  <div className="flex flex-wrap gap-3">
    <ExitRampButton label="Go to Trading" onClick={() => useUIStore.getState().setActiveView("trading")} />
  </div>
</div>
```

**Dropped "Test All in What-If"**: Combining strategies across drivers into one delta bundle is semantically wrong — each recommendation is a standalone idea, not an approved bundle. Duplicate hedge tickers across drivers would also overwrite each other by key. Per-strategy "What-If" buttons in the table rows are the right granularity for testing individual strategies.

### 9. Insight copy cleanup

Fix the insight body to not leak raw metrics. Current: "SGOV carries Financial - Mortgages beta of -0.00" — replace `getBestStrategySummary()` with interpretive language:

- Direct offset: "Consider shorting {driverLabel} exposure via {ticker}"
- Beta alternative: "{ticker} offers low-beta exposure to dilute {driverLabel} risk"
- Diversification: "{ticker} provides diversification against {driverLabel}"

## Files to Modify

| File | Change |
|------|--------|
| `frontend/packages/ui/src/components/portfolio/scenarios/tools/HedgeTool.tsx` | Primary — all structural changes |

No backend changes. No new files needed. All data is already available from `useHedgingRecommendations`.

## Reusable Patterns (exact sources)

- **Metrics strip**: `TaxHarvestTool.tsx` lines 111–161 (`flex items-stretch overflow-hidden rounded-xl border border-border/60 bg-card`)
- **Table rows**: `TaxHarvestTool.tsx` lines 412–481 (`border-b border-border/40 hover:bg-muted/30`)
- **Collapsible**: `TaxHarvestTool.tsx` lines 484–545 (import from `../../../ui/collapsible`)
- **ExitRampButton**: `scenarios/shared/ExitRampButton.tsx`
- **ScenarioInsightCard**: already imported and used
- **BarChart (Recharts)**: `import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"`
- **ChevronDown icon**: `import { ChevronDown } from "lucide-react"`

## Verification

1. `npx tsc --noEmit` — zero TypeScript errors
2. Open `localhost:3000/#scenarios/hedge` with All Accounts selected
3. Verify: insight card → bar chart → metrics strip → separator → driver sections
4. Verify first driver expanded, others collapsed
5. Verify table rows render with correct data
6. Click "What-If" on a strategy row — verify navigation with delta context
7. Click "Execute" — verify HedgeWorkflowDialog opens
8. Click a row to expand — verify inline preview loads
9. Verify exit ramp buttons at bottom navigate correctly
10. Check page height is significantly reduced (~1500px vs ~3100px)

# Wave 3: Block Component Adoption — RiskAnalysis + ScenarioAnalysis + HoldingsView + PerformanceView

## Context

Waves 1-2 complete (`9506643d`, `93e5ed9e`). This wave is the largest — 4 views with a mix of SectionHeader, GradientProgress, and MetricCard opportunities. The MetricCard `children` prerequisite from the parent plan is NOT needed for this wave — the HoldingsView metric cards map cleanly to existing MetricCard props (no nested custom content). PerformanceView's sub-section headers are a new SectionHeader pattern (smaller `size="sm"` inside card bodies).

Parent plan: `docs/planning/FRONTEND_BLOCK_REFACTOR_PLAN.md`

## Prerequisite: None

MetricCard `children` slot is NOT needed for Wave 3. The HoldingsView summary cards (the only MetricCard candidates) use icon + label + subtitle + value + change badge — all covered by existing props. The description/change below the value maps to `change` + `changeType`. No nested custom content.

## Changes

### 1. RiskAnalysis.tsx

**File**: `frontend/packages/ui/src/components/portfolio/RiskAnalysis.tsx`

#### 1a. Replace risk score Progress bar (line 562)

Current:
```tsx
<Progress value={risk.score} className="h-2 mb-3" />
```

Replace with:
```tsx
<GradientProgress value={risk.score} colorScheme="red" showPercentage={false} size="md" className="mb-3" />
```

Notes:
- `size="md"` gives `h-2`, matching current `h-2`.
- `colorScheme="red"` matches the risk analysis red theme (header uses Shield icon, risk context).
- Risk scores are 0-100, direct fit for GradientProgress value.

#### 1b. Import changes

Remove:
```tsx
import { Progress } from "../ui/progress"
```

Add:
```tsx
import { GradientProgress } from "../blocks"
```

Note: `Progress` is only used once (line 562) — safe to remove.

#### 1c. NOT changed

- **Header** (lines 491-494): Plain `CardTitle` with inline Shield icon, no gradient icon container. Does NOT match SectionHeader pattern (no gradient bg, no subtitle). Converting would add visual weight that doesn't exist currently. Keep inline.
- **Tab system**: Standard Tabs/TabsList/TabsTrigger — not a block pattern.
- **Risk factor cards**: Custom expandable cards with click-to-expand details. MetricCard doesn't support expand/collapse. Keep inline.
- **Hedging strategy cards**: Custom layout with implementation steps, coverage %, etc. Too specialized for MetricCard.

---

### 2. ScenarioAnalysis.tsx

**File**: `frontend/packages/ui/src/components/portfolio/ScenarioAnalysis.tsx`

#### 2a. Replace header (lines 941-976) with SectionHeader

Current:
```tsx
<CardHeader className="pb-4 border-b border-neutral-200/60">
  <div className="flex items-center justify-between">
    <div className="flex items-center space-x-3">
      <div className="w-10 h-10 bg-gradient-to-br from-red-500 to-red-600 rounded-lg flex items-center justify-center">
        <AlertTriangle className="w-5 h-5 text-white" />
      </div>
      <div>
        <CardTitle className="text-lg font-semibold text-neutral-900">Advanced Scenario Analysis</CardTitle>
        <p className="text-sm text-neutral-600">Portfolio modeling, stress testing & optimization</p>
      </div>
    </div>
    <div className="flex items-center space-x-2">
      <Badge className="bg-red-100 text-red-700 border-red-200">What-If Analysis</Badge>
      <Button size="sm" onClick={runComprehensiveAnalysis} disabled={isRunning} className="bg-red-600 hover:bg-red-700 ...">
        {isRunning ? (<>...</>) : (<>...</>)}
      </Button>
    </div>
  </div>
```

Replace with:
```tsx
<CardHeader className="pb-4 border-b border-neutral-200/60">
  <SectionHeader
    icon={AlertTriangle}
    title="Advanced Scenario Analysis"
    subtitle="Portfolio modeling, stress testing & optimization"
    colorScheme="red"
    size="md"
    actions={
      <div className="flex items-center space-x-2">
        <Badge className="bg-red-100 text-red-700 border-red-200">
          What-If Analysis
        </Badge>
        <Button
          size="sm"
          onClick={runComprehensiveAnalysis}
          disabled={isRunning}
          className="bg-red-600 hover:bg-red-700 transition-all duration-200 hover:shadow-lg hover:shadow-red-500/25"
        >
          {isRunning ? (
            <>
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              Analyzing...
            </>
          ) : (
            <>
              <Play className="w-4 h-4 mr-2" />
              Run Analysis
            </>
          )}
        </Button>
      </div>
    }
  />
```

Notes:
- SectionHeader `size="md"` → `h-10 w-10` icon container, `h-5 w-5` icon — matches current.
- `colorScheme="red"` → `from-red-500 to-red-600` — matches current gradient exactly.
- Badge + Button go in `actions`.
- Minor visual: `rounded-xl` vs `rounded-lg` on icon container. Acceptable.

#### 2b. Replace analysis Progress bar (line 995)

Current:
```tsx
<Progress value={analysisProgress} className="h-2 bg-blue-100" />
```

Replace with:
```tsx
<GradientProgress value={analysisProgress} colorScheme="blue" showPercentage={false} size="md" />
```

Notes:
- `size="md"` gives `h-2`, matching current `h-2`.
- `colorScheme="blue"` matches the blue analysis progress overlay theme.
- The `bg-blue-100` track color is slightly different from GradientProgress's default neutral track. Minor visual change — acceptable.

#### 2c. Replace stress test impact Progress bar (line 1495)

Current:
```tsx
<Progress
  value={Math.min(Math.abs(test.impact) * 5, 100)}
  className="h-2"
/>
```

Replace with:
```tsx
<GradientProgress
  value={Math.min(Math.abs(test.impact) * 5, 100)}
  colorScheme="red"
  showPercentage={false}
  size="md"
/>
```

Notes:
- `colorScheme="red"` — stress test context (negative impact scenarios).

#### 2d. Replace 5 Monte Carlo percentile Progress bars (lines 1546, 1553, 1560, 1567, 1574)

Current (5 instances, same pattern):
```tsx
<Progress value={5} className="h-2" />
<Progress value={25} className="h-2" />
<Progress value={50} className="h-2" />
<Progress value={75} className="h-2" />
<Progress value={95} className="h-2" />
```

Replace with:
```tsx
<GradientProgress value={5} colorScheme="red" showPercentage={false} size="md" />
<GradientProgress value={25} colorScheme="amber" showPercentage={false} size="md" />
<GradientProgress value={50} colorScheme="emerald" showPercentage={false} size="md" />
<GradientProgress value={75} colorScheme="emerald" showPercentage={false} size="md" />
<GradientProgress value={95} colorScheme="emerald" showPercentage={false} size="md" />
```

Notes:
- Color matches the adjacent text color: 5th percentile is red (worst case), 25th is amber (below average), 50th+ are emerald (positive outcomes). This adds meaningful color coding that the plain `<Progress>` didn't have.

#### 2e. Import changes

Remove:
```tsx
import { Progress } from "../ui/progress"
```

Add:
```tsx
import { GradientProgress, SectionHeader } from "../blocks"
```

Note: After replacing ALL 7 Progress bars (lines 995, 1495, 1546, 1553, 1560, 1567, 1574), `Progress` is no longer used — safe to remove.

Remove `CardTitle` from card import if not used elsewhere. Check: `CardTitle` appears in the header being replaced. Grep for other `<CardTitle` usage in the file — if none remain, remove from imports.

#### 2f. NOT changed

- **Analysis progress overlay container** (lines 980-997): The blue gradient container with icon + stage text + percentage display is view-specific composition. Only the `<Progress>` inside it gets replaced.
- **Analysis results summary** (lines 1000-1009): Custom completion display with CheckCircle2 icon. Not a block pattern.
- **Tab system and scenario builder forms**: Too interactive/specialized for blocks.
- **Scenario result cards**: Custom comparison layouts with sliders, inputs. Not MetricCard candidates.

---

### 3. HoldingsView.tsx

**File**: `frontend/packages/ui/src/components/portfolio/HoldingsView.tsx`

#### 3a. Replace 4 summary metric cards (lines 646-754) with MetricCard

**Card 1: Total Holdings** (lines 646-676)

Current: Card with emerald gradient Wallet icon + "Total Holdings" label + position count subtitle + currency value + day change badge + currency change.

Replace with:
```tsx
<MetricCard
  icon={Wallet}
  label="Total Holdings"
  subtitle={`${summaryMetrics.totalPositions} positions`}
  value={formatCurrency(summaryMetrics.totalValue)}
  change={`${formatPercent(summaryMetrics.dayChangePercent, { sign: true })}`}
  changeType={summaryMetrics.dayChange >= 0 ? "positive" : "negative"}
  description={formatCurrency(summaryMetrics.dayChange)}
  colorScheme="emerald"
/>
```

**Card 2: Total Return** (lines 678-702)

Replace with:
```tsx
<MetricCard
  icon={TrendingUp}
  label="Total Return"
  subtitle="unrealized gains"
  value={formatCurrency(summaryMetrics.totalReturn)}
  change={`${formatPercent(summaryMetrics.totalReturnPercent, { sign: true })}`}
  changeType={summaryMetrics.totalReturn >= 0 ? "positive" : "negative"}
  description="since inception"
  colorScheme="blue"
/>
```

**Card 3: Avg Risk Score** (lines 704-728)

Replace with:
```tsx
<MetricCard
  icon={Shield}
  label="Avg Risk Score"
  subtitle="weighted average"
  value={formatNumber(summaryMetrics.avgRisk, { decimals: 1 })}
  change="Medium Risk"
  changeType="warning"
  description="well balanced"
  colorScheme="amber"
/>
```

Note: "Medium Risk" isn't a percentage — MetricCard's `parsePercentageChange()` will fail to parse it, falling back to the plain text render path (`changeTextColors[changeType]` span). This is the correct behavior.

**Card 4: Active Alerts** (lines 730-754)

Replace with:
```tsx
<MetricCard
  icon={AlertTriangle}
  label="Active Alerts"
  subtitle="risk notifications"
  value={String(summaryMetrics.totalAlerts)}
  change="High Priority"
  changeType="negative"
  description="needs attention"
  colorScheme="red"
/>
```

#### 3b. Visual differences to accept

The current inline cards have:
1. `group` class with hover corner glow (`absolute top-0 right-0 w-20 h-20 bg-gradient-to-br`). MetricCard doesn't have this — loses the subtle hover corner effect. Acceptable.
2. `shadow-lg shadow-{color}-500/20` on icon container. MetricCard uses `shadow-sm shadow-{color}-500/20` — slightly less prominent shadow. Acceptable.
3. `rounded-xl` on icon in MetricCard vs `rounded-xl` in current code — matches.
4. Current cards use `p-6`, MetricCard uses `p-4`. The cards will be slightly more compact. Acceptable — the grid layout will still work.
5. `text-2xl font-bold` value in both — matches.

#### 3c. Import changes

Add:
```tsx
import { MetricCard } from "../blocks"
```

Check if `Wallet` icon is already imported from lucide-react. It should be — it's used in the current card.

`Card`, `CardContent` are still needed for the holdings table section. `CardHeader`, `CardTitle` are still needed for the table header. Keep all card imports.

#### 3d. NOT changed

- **Holdings table header** (lines 775-781): `CardTitle` with inline `PieChart` icon + badge. Does NOT match SectionHeader pattern — no gradient icon container, no subtitle. The icon is plain `text-neutral-700`, not white-on-gradient. Converting would change the visual tone. Keep inline.
- **Holdings table**: Interactive table with sorting, filtering, hover effects, sector icons. Not a block pattern.
- **Search and filter controls**: Form inputs with state. Not blocks.
- **Individual holding rows**: Complex multi-column layout with conditional formatting. Not MetricCard candidates.

---

### 4. PerformanceView.tsx

**File**: `frontend/packages/ui/src/components/portfolio/PerformanceView.tsx`

#### 4a. Replace sub-section headers with SectionHeader

PerformanceView has 6 sub-section headers inside tab content, all following the same pattern:
```tsx
<CardHeader className="p-0 mb-6">
  <CardTitle className="flex items-center space-x-3 text-lg font-semibold text-neutral-900">
    <div className="w-8 h-8 bg-gradient-to-br from-{color}-500 to-{color}-600 rounded-xl flex items-center justify-center shadow-md shadow-{color}-500/20">
      <Icon className="w-4 h-4 text-white" />
    </div>
    <span>Title</span>
    {optional badge}
  </CardTitle>
</CardHeader>
```

This is a SectionHeader fit with `size="sm"` (gives `h-8 w-8` icon, `h-4 w-4` icon size — matches current).

**Replace these 6 instances:**

| Line | Title | Icon | Color | Badge |
|------|-------|------|-------|-------|
| 1264-1273 | Sector Performance Attribution | PieChart | blue | conditional "AI Enhanced" |
| 1349-1350 | Top Contributors | TrendingUp | emerald | none (need to check) |
| 1429-1430 | Bottom Detractors | TrendingDown | red | none (need to check) |
| 1510-1516 | Factor Attribution | Target | indigo | none |
| 1545-1551 | Performance vs Benchmarks | BarChart3 | purple | none |
| 1627-1634 | Risk & Drawdown Analysis | AlertTriangle | red | "Predictive" badge |
| 1701-1708 | Monthly Performance Breakdown | Calendar | blue | "Market Context" badge |

That's actually 7 instances. Let me specify each replacement:

**Instance 1: Sector Performance Attribution** (lines 1264-1273)
```tsx
// Before:
<CardHeader className="p-0 mb-6">
  <CardTitle className="flex items-center space-x-3 text-lg font-semibold text-neutral-900">
    <div className="w-8 h-8 bg-gradient-to-br from-blue-500 to-blue-600 rounded-xl flex items-center justify-center shadow-md shadow-blue-500/20">
      <PieChart className="w-4 h-4 text-white" />
    </div>
    <span>Sector Performance Attribution</span>
    {viewMode === "detailed" && (
      <Badge className="bg-blue-100 text-blue-800 text-xs">AI Enhanced</Badge>
    )}
  </CardTitle>
</CardHeader>

// After:
<CardHeader className="p-0 mb-6">
  <SectionHeader
    icon={PieChart}
    title="Sector Performance Attribution"
    colorScheme="blue"
    size="sm"
    badge={viewMode === "detailed" ? <Badge className="bg-blue-100 text-blue-800 text-xs">AI Enhanced</Badge> : undefined}
  />
</CardHeader>
```

**Instance 2: Factor Attribution** (lines 1510-1516)
```tsx
// After:
<CardHeader className="p-0 mb-4">
  <SectionHeader
    icon={Target}
    title="Factor Attribution"
    colorScheme="indigo"
    size="sm"
  />
</CardHeader>
```

**Instance 3: Performance vs Benchmarks** (lines 1545-1551)
```tsx
// After:
<CardHeader className="p-0 mb-6">
  <SectionHeader
    icon={BarChart3}
    title="Performance vs Benchmarks"
    colorScheme="purple"
    size="sm"
  />
</CardHeader>
```

**Instance 4: Risk & Drawdown Analysis** (lines 1627-1634)
```tsx
// After:
<CardHeader className="p-0 mb-6">
  <SectionHeader
    icon={AlertTriangle}
    title="Risk & Drawdown Analysis"
    colorScheme="red"
    size="sm"
    badge={<Badge className="bg-red-100 text-red-800 text-xs">Predictive</Badge>}
  />
</CardHeader>
```

**Instance 5: Monthly Performance Breakdown** (lines 1701-1708)
```tsx
// After:
<CardHeader className="p-0 mb-6">
  <SectionHeader
    icon={Calendar}
    title="Monthly Performance Breakdown"
    colorScheme="blue"
    size="sm"
    badge={<Badge className="bg-blue-100 text-blue-800 text-xs">Market Context</Badge>}
  />
</CardHeader>
```

**NOT replaced: Top Contributors / Bottom Detractors** (lines 1349-1356, 1429-1436) — these use `w-6 h-6` icon containers with `w-3 h-3` icons, smaller than SectionHeader's smallest size (`sm` = `h-8 w-8` / `h-4 w-4`). Converting would make them larger than intended. Keep inline.

#### 4b. Replace sector attribution Progress bar (line 1311-1314)

Current:
```tsx
<Progress
  value={(sector.contribution + 15) * (100 / 30)}
  className="h-2 bg-neutral-100"
/>
```

Replace with:
```tsx
<GradientProgress
  value={(sector.contribution + 15) * (100 / 30)}
  colorScheme="blue"
  showPercentage={false}
  size="md"
/>
```

Notes:
- `size="md"` → `h-2`, matching current.
- `colorScheme="blue"` matches the sector attribution blue theme.
- Value capping logic stays in view.

#### 4c. Import changes

Remove:
```tsx
import { Progress } from "../ui/progress"
```

Add:
```tsx
import { GradientProgress, SectionHeader } from "../blocks"
```

Note: `CardTitle` is still used in the Top Contributors (line 1350) and Top Detractors (line 1430) headers which are kept inline. Do NOT remove `CardTitle` from imports.

#### 4d. NOT changed

- **Main header** (lines 821-886): Highly customized — `w-12 h-12` icon with absolute-positioned Brain AI indicator, `h1` title, Timer + RefreshCw status indicators, view mode toggle buttons, insights toggle, benchmark dropdown, export menu. Way too complex for SectionHeader. Keep inline.
- **Performance period cards** (around lines 900-1000): Period selector buttons with returns/alpha. Not MetricCard — they're toggle buttons with inline stats.
- **Benchmark comparison metric boxes** (lines 1554-1620): Simple `div` boxes with label + value + badge. Similar to MetricCard but use `p-4 gradient-sophisticated rounded-xl` styling that MetricCard can't replicate. Keep inline.
- **Max Drawdown / Volatility boxes** (lines 1638-1692): Custom styled boxes with detail rows. MetricCard would lose the detail row layout. Keep inline.
- **Monthly return cards**: Grid of small cards with portfolio/benchmark comparison. Too specialized for MetricCard.

---

## Files Modified

| File | Changes | Blocks Used |
|------|---------|-------------|
| `RiskAnalysis.tsx` | Replace 1 Progress bar | GradientProgress |
| `ScenarioAnalysis.tsx` | Replace header, replace 7 Progress bars | SectionHeader, GradientProgress |
| `HoldingsView.tsx` | Replace 4 summary metric cards | MetricCard |
| `PerformanceView.tsx` | Replace 5 sub-section headers, replace 1 Progress bar | SectionHeader, GradientProgress |

## NOT Changed (Summary)

- RiskAnalysis header (plain CardTitle, no gradient icon container — adding one would change visual weight)
- RiskAnalysis risk factor cards (expandable — MetricCard doesn't support expand/collapse)
- HoldingsView table header (plain icon, no gradient — different visual pattern)
- HoldingsView table rows (complex multi-column)
- PerformanceView main header (too customized — AI indicator, view toggles, export menu)
- PerformanceView benchmark comparison boxes (custom gradient styling)
- PerformanceView drawdown/volatility detail boxes (detail rows layout)
- PerformanceView monthly return cards (specialized grid format)
- PerformanceView Top Contributors / Bottom Detractors headers (w-6 h-6 icons — smaller than SectionHeader's smallest size)
- No MetricCard `children` needed in this wave

## Verification

1. `cd frontend && pnpm typecheck` — no TypeScript errors
2. `cd frontend && pnpm build` — Vite build succeeds
3. Verify removed imports (`Progress`, `CardTitle` where applicable) are not used elsewhere in the modified files
4. Verify `../blocks` import path resolves correctly
5. HoldingsView: Verify MetricCard visual output matches original cards (icon, label, value, change badge positioning)

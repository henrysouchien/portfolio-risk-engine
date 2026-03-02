# Wave 2: Block Component Adoption — RiskMetrics + StockLookup + StrategyBuilder

## Context

Wave 1 complete (`9506643d`). This wave adopts GradientProgress and SectionHeader across three medium-complexity views. No MetricCard usage — the metric card patterns in these views have structural mismatches (icon position, colored text throughout) that would require visual changes. Per rules: keep inline code if block doesn't fit.

Parent plan: `docs/planning/FRONTEND_BLOCK_REFACTOR_PLAN.md`

## Changes

### 1. RiskMetrics.tsx

**File**: `frontend/packages/ui/src/components/portfolio/RiskMetrics.tsx`

#### 1a. Replace Progress + gradient overlay (lines 386-395)

Current — Progress with an absolute-positioned gradient div overlay:
```tsx
<div className="relative">
  <Progress
    value={metric.percentage}
    className="h-3 bg-neutral-200/60 rounded-full overflow-hidden"
  />
  {/* Gradient overlay with status-based colors */}
  <div
    className={`absolute top-0 left-0 h-full bg-gradient-to-r ${config.progressColor} rounded-full transition-all duration-700 ease-out shadow-sm`}
    style={{ width: `${metric.percentage}%` }}
  />
</div>
```

Replace with:
```tsx
<GradientProgress
  value={metric.percentage}
  colorScheme={statusToColorScheme(metric.status)}
  showPercentage={false}
  size="lg"
/>
```

Notes:
- `size="lg"` gives `h-3`, matching the current `h-3` Progress.
- The gradient overlay hack is no longer needed — GradientProgress renders a native gradient indicator.
- Status-to-color mapping: `high` → `"red"`, `medium` → `"amber"`, `low` → `"emerald"`. Do NOT use `autoColor` — it's inverted for risk semantics (autoColor: low value = red, but for risk: low = good = emerald).
- The "Low Risk / {pct}% / High Risk" labels below the bar (lines 399-411) are view-specific and stay inline.

Add a local helper above the component:
```tsx
function statusToColorScheme(status: RiskMetricStatus): "red" | "amber" | "emerald" {
  switch (status) {
    case 'high': return 'red'
    case 'medium': return 'amber'
    case 'low': return 'emerald'
  }
}
```

#### 1b. Import changes

Remove:
```tsx
import { Progress } from "../ui/progress"
```

Add:
```tsx
import { GradientProgress } from "../blocks"
```

Note: `Progress` is NOT used elsewhere in RiskMetrics.tsx after this replacement — safe to remove. Check: the only `<Progress` in the file is the one at line 387.

#### 1c. NOT changed

- **Header** (lines 307-329): Shield icon with pulse indicator, hover rotation, custom shadow effects. Too customized for SectionHeader — would lose premium styling. Keep inline.
- **Status badge** (lines 358-362): Text status `HIGH|MEDIUM|LOW` with dynamic color. NOT numeric — cannot use PercentageBadge. Keep as Badge.
- **`getStatusConfig()`**: Still needed for icon bg, text color, ring color on the metric cards. Only `progressColor` from config becomes unused (replaced by GradientProgress colorScheme). Can optionally remove `progressColor` from the config objects, but not required.

---

### 2. StockLookup.tsx

**File**: `frontend/packages/ui/src/components/portfolio/StockLookup.tsx`

#### 2a. Replace header (lines 514-549) with SectionHeader

Current:
```tsx
<CardHeader className="pb-4 border-b border-neutral-200/60">
  <div className="flex items-center justify-between">
    <div className="flex items-center space-x-3">
      <div className="w-10 h-10 bg-gradient-to-br from-blue-500 to-blue-600 rounded-lg flex items-center justify-center">
        <Search className="w-5 h-5 text-white" />
      </div>
      <div>
        <CardTitle className="text-lg font-semibold text-neutral-900">Stock Risk Lookup</CardTitle>
        <p className="text-sm text-neutral-600">Individual security risk analysis</p>
      </div>
    </div>
    <div className="flex items-center space-x-2">
      <Input ... />
      <Button ... />
    </div>
  </div>
</CardHeader>
```

Replace with:
```tsx
<CardHeader className="pb-4 border-b border-neutral-200/60">
  <SectionHeader
    icon={Search}
    title="Stock Risk Lookup"
    subtitle="Individual security risk analysis"
    colorScheme="blue"
    size="md"
    actions={
      <div className="flex items-center space-x-2">
        <Input
          placeholder="Enter symbol (e.g., AAPL, TSLA)"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          onKeyPress={(e) => e.key === 'Enter' && handleSearch()}
          className="w-48"
        />
        <Button
          onClick={handleSearch}
          disabled={loading}
          className="bg-blue-600 hover:bg-blue-700"
        >
          {loading ? (
            <Activity className="w-4 h-4 animate-spin" />
          ) : (
            <Search className="w-4 h-4" />
          )}
        </Button>
      </div>
    }
  />
</CardHeader>
```

Notes:
- SectionHeader `size="md"` gives `h-10 w-10` icon container and `h-5 w-5` icon — matches current.
- SectionHeader `colorScheme="blue"` gives `from-blue-500 to-blue-600` — matches current gradient exactly.
- Minor visual change: SectionHeader uses `rounded-xl` for icon container vs current `rounded-lg`. Acceptable.
- `CardTitle` import may become unused if no other CardTitle usage exists — check before removing.

#### 2b. Replace Risk Factors Progress bars (lines 778, 784)

Current:
```tsx
<Progress value={factor.exposure} className="h-2" />
...
<Progress value={factor.risk} className="h-2" />
```

Replace with:
```tsx
<GradientProgress value={factor.exposure} colorScheme="blue" showPercentage={false} size="md" />
...
<GradientProgress value={factor.risk} colorScheme="blue" showPercentage={false} size="md" />
```

Notes:
- `size="md"` gives `h-2`, matching `h-2`.
- `colorScheme="blue"` matches the page's blue theme (header is blue).

#### 2c. Replace RSI Progress bar (line 812)

Current:
```tsx
<Progress value={selectedStock.technicals.rsi} className="h-1 mt-2" />
```

Replace with:
```tsx
<GradientProgress value={selectedStock.technicals.rsi} colorScheme="blue" showPercentage={false} size="sm" className="mt-2" />
```

Notes:
- Current is `h-1`. GradientProgress `size="sm"` gives `h-1.5` — slightly taller. Acceptable minor visual change.

#### 2d. Replace Valuation Progress bars (lines 975, 986, 997)

Current:
```tsx
<Progress value={Math.min((selectedStock.fundamentals?.pbRatio ?? 0) * 10, 100)} className="w-16 h-2" />
<Progress value={Math.min((selectedStock.fundamentals?.roe ?? 0) * 2, 100)} className="w-16 h-2" />
<Progress value={(selectedStock.fundamentals?.profitMargin ?? 0) * 2} className="w-16 h-2" />
```

Replace with:
```tsx
<GradientProgress value={Math.min((selectedStock.fundamentals?.pbRatio ?? 0) * 10, 100)} colorScheme="indigo" showPercentage={false} size="md" className="w-16" />
<GradientProgress value={Math.min((selectedStock.fundamentals?.roe ?? 0) * 2, 100)} colorScheme="indigo" showPercentage={false} size="md" className="w-16" />
<GradientProgress value={(selectedStock.fundamentals?.profitMargin ?? 0) * 2} colorScheme="indigo" showPercentage={false} size="md" className="w-16" />
```

Notes:
- `colorScheme="indigo"` matches the fundamentals tab's indigo-themed cards.
- `className="w-16"` preserves the fixed width. GradientProgress uses `w-full` by default; the className override narrows it.
- Value capping logic stays in the view.

#### 2e. Replace Financial Health Progress bars (lines 1015, 1022, 1029)

Current:
```tsx
<Progress value={85} className="h-2" />
<Progress value={72} className="h-2" />
<Progress value={45} className="h-2" />
```

Replace with:
```tsx
<GradientProgress value={85} colorScheme="neutral" showPercentage={false} size="md" />
<GradientProgress value={72} colorScheme="neutral" showPercentage={false} size="md" />
<GradientProgress value={45} colorScheme="neutral" showPercentage={false} size="md" />
```

Notes:
- `colorScheme="neutral"` for the financial health section (no specific color theme).
- These are mock scores — when real data is wired, `autoColor` could be appropriate here (higher = better), but leave as neutral for now to match current visual.

#### 2f. Import changes

Remove:
```tsx
import { Progress } from "../ui/progress"
```

Add:
```tsx
import { GradientProgress } from "../blocks"
import { SectionHeader } from "../blocks"
```
Or combined:
```tsx
import { GradientProgress, SectionHeader } from "../blocks"
```

Note: `Progress` is NOT used elsewhere in StockLookup.tsx after these replacements — safe to remove. `CardTitle` IS still used elsewhere (not in header, but check) — actually, `CardTitle` is used in the header which is being replaced by SectionHeader. Check if `CardTitle` is used elsewhere in the file: it appears in `CardHeader` sections for the stock analysis sub-cards. Look for other `<CardTitle` usage — if the only usage was in the header, it can be removed from imports. If used elsewhere, keep it.

Check: Grep for `CardTitle` in StockLookup.tsx beyond line 522. The mock data sub-cards use `<Card className=...>` and `<h3>` / `<h4>` elements, NOT `CardTitle`. So `CardTitle` can be removed from the import if it's only in the header.

---

### 3. StrategyBuilder.tsx

**File**: `frontend/packages/ui/src/components/portfolio/StrategyBuilder.tsx`

#### 3a. Replace header (lines 565-606) with SectionHeader

Current:
```tsx
<CardHeader className="pb-4 border-b border-neutral-200/60">
  <div className="flex items-center justify-between">
    <div className="flex items-center space-x-3">
      <div className="w-10 h-10 bg-gradient-to-br from-emerald-500 to-emerald-600 rounded-lg flex items-center justify-center">
        <Target className="w-5 h-5 text-white" />
      </div>
      <div>
        <CardTitle className="text-lg font-semibold text-neutral-900">Investment Strategies</CardTitle>
        <p className="text-sm text-neutral-600">Build, backtest & deploy AI-powered investment strategies</p>
      </div>
    </div>
    <div className="flex items-center space-x-2">
      <Badge className="bg-emerald-100 text-emerald-700 border-emerald-200">
        <Brain className="w-3 h-3 mr-1" />
        AI Enhanced
      </Badge>
      <Button size="sm" onClick={...} disabled={...} className="bg-emerald-600 hover:bg-emerald-700">
        {isBacktesting || loading ? (<>...</>) : (<>...</>)}
      </Button>
    </div>
  </div>
</CardHeader>
```

Replace with:
```tsx
<CardHeader className="pb-4 border-b border-neutral-200/60">
  <SectionHeader
    icon={Target}
    title="Investment Strategies"
    subtitle="Build, backtest & deploy AI-powered investment strategies"
    colorScheme="emerald"
    size="md"
    actions={
      <div className="flex items-center space-x-2">
        <Badge className="bg-emerald-100 text-emerald-700 border-emerald-200">
          <Brain className="w-3 h-3 mr-1" />
          AI Enhanced
        </Badge>
        <Button
          size="sm"
          onClick={() => { void runBacktest() }}
          disabled={isBacktesting || loading}
          className="bg-emerald-600 hover:bg-emerald-700"
        >
          {isBacktesting || loading ? (
            <>
              <Activity className="w-4 h-4 mr-2 animate-spin" />
              Backtesting...
            </>
          ) : (
            <>
              <Play className="w-4 h-4 mr-2" />
              Run Backtest
            </>
          )}
        </Button>
      </div>
    }
  />
</CardHeader>
```

Notes:
- SectionHeader `size="md"` → `h-10 w-10` icon, `h-5 w-5` icon size — matches current.
- `colorScheme="emerald"` → `from-emerald-500 to-emerald-600` — matches current gradient exactly.
- AI Enhanced badge and Run Backtest button go in `actions` (right side).
- Minor visual: `rounded-xl` vs `rounded-lg` on icon container. Acceptable.
- `CardTitle` may be removable from imports if not used elsewhere. Check: StrategyBuilder sub-cards use `<h4>` tags, not `<CardTitle>`. So `CardTitle` can be removed.

#### 3b. Import changes

Remove (if safe — verify `CardTitle` not used elsewhere):
```tsx
// Remove CardTitle from the Card import if not used elsewhere
import { Card,CardContent,CardHeader,CardTitle } from "../ui/card"
// becomes:
import { Card,CardContent,CardHeader } from "../ui/card"
```

Add:
```tsx
import { SectionHeader } from "../blocks"
```

Note: StrategyBuilder does NOT import or use `Progress` — no progress bars to replace.

#### 3c. NOT changed

- **Strategy Preview cards** (lines 813-832): Simple colored boxes with label+value. MetricCard is structurally different (icon left, uppercase label, neutral text colors). Not a good fit.
- **Performance metric grids** (lines 1027-1046, 1069-1092): Same pattern — colored boxes. Keep inline.
- **No Progress bars** in StrategyBuilder.

---

## Files Modified

| File | Changes | Blocks Used |
|------|---------|-------------|
| `RiskMetrics.tsx` | Replace Progress+overlay with GradientProgress | GradientProgress |
| `StockLookup.tsx` | Replace header, replace 8 Progress bars | SectionHeader, GradientProgress |
| `StrategyBuilder.tsx` | Replace header | SectionHeader |

## NOT Changed

- RiskMetrics header (too customized, pulse indicator + hover rotation)
- RiskMetrics status badge (text not numeric, not PercentageBadge)
- StockLookup/StrategyBuilder metric cards (structural layout mismatch with MetricCard)
- StrategyBuilder has no Progress bars
- No MetricCard usage in Wave 2 (deferred to Wave 3+ when children slot is added)

## Verification

1. `cd frontend && pnpm typecheck` — no TypeScript errors
2. `cd frontend && pnpm build` — Vite build succeeds
3. `cd frontend && pnpm eslint packages/ui/src/components/portfolio/RiskMetrics.tsx packages/ui/src/components/portfolio/StockLookup.tsx packages/ui/src/components/portfolio/StrategyBuilder.tsx --ext .ts,.tsx` — no lint errors in modified files
4. Verify removed imports (`Progress`, `CardTitle` where applicable) are not used elsewhere in the modified files
5. Verify `../blocks` import path resolves correctly

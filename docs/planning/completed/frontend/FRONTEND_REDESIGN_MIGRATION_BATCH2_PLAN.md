# Frontend Redesign — Batch 2: Recharts Theme + StatPair Migration

## Overview

Two sub-batches:
- **2a: Recharts chart-theme** — 2 chart files get styled axes, grid, tooltips via the theme layer (Phase 1b)
- **2b: StatPair** — label+value rows across 2 files get replaced with the `<StatPair>` block (Phase 1c)

2a is an intentional visual upgrade (styled axes, glass tooltips). 2b is mostly DRY cleanup with a minor dark mode improvement (`text-neutral-600` → `text-muted-foreground`).

---

## Batch 2a: Recharts Chart Theme Migration

### Available Infrastructure

| Utility | What it does |
|---------|-------------|
| `getAxisPreset()` | fontSize 11, Inter font, muted-foreground fill, border stroke, no tick lines |
| `getGridPreset()` | Dashed grid, border color, 0.5 opacity, horizontal only |
| `getTooltipStyle()` | Glass card bg, rounded-12, blur backdrop, shadow |
| `ChartContainer` block | `ResponsiveContainer` + loading/empty/error states |
| `ChartTooltip` block | Glass tooltip with color dots, per-key formatters |
| `getChartColor(i)` | CSS var chart palette |
| `formatCurrency()`, `formatPercent()`, `formatChartDate()` | Tick/label formatters |

Reference implementation: `stock-lookup/PriceChartTab.tsx`

### Site 1: `scenario/MonteCarloTab.tsx` (lines 168-243)

**Current:** `ResponsiveContainer > AreaChart` with inline axis styles and raw `Tooltip`.

| Element | Current | Migration |
|---------|---------|-----------|
| `ResponsiveContainer` (168) | Raw, no loading state | Wrap with `ChartContainer height={300}` |
| `XAxis` (188-192) | `tick={{ fontSize: 10 }}`, inline label | `{...getAxisPreset()}`, keep custom `label` prop |
| `YAxis` (193-196) | `tick={{ fontSize: 10 }}`, inline `tickFormatter` | `{...getAxisPreset()}`, keep `tickFormatter` (custom $k format) |
| `Tooltip` (197-200) | Inline `formatter` (0-decimal currency via local `formatCurrency`), `labelFormatter` | `content={<ChartTooltip defaultFormat="currency" labelFormatter={(m) => \`Month ${m}\`} />}`. Note: ChartTooltip's `formatCurrency` uses 2 decimals vs current 0 — minor formatting change, acceptable for chart tooltips |
| `Area` strokes | Hardcoded `#ef4444`, `#f59e0b`, `#10b981`, `#3b82f6` | Keep as-is — intentionally semantic (red=risk, green=good, blue=median) |
| `Legend` (241) | Raw | Keep as-is (5 percentile bands need legend) |
| Missing: `CartesianGrid` | None | Add `<CartesianGrid {...getGridPreset()} />` |

**Gradient `defs`:** Keep all 4 gradients — they use the same semantic colors as the Area strokes.

### Site 2: `strategy/PerformanceTab.tsx` (lines 153-187)

**Current:** `ResponsiveContainer > LineChart` with inline axis styles and raw `Tooltip`.

| Element | Current | Migration |
|---------|---------|-----------|
| `ResponsiveContainer` (153) | Raw, no loading state | Wrap with `ChartContainer height={300}` |
| `XAxis` (155-159) | `tick={{ fontSize: 10 }}`, `.slice(2)` formatter | `{...getAxisPreset()}`, `tickFormatter={(v) => formatChartDate(v, "daily")}` |
| `YAxis` (160-163) | `tick={{ fontSize: 10 }}`, inline `%` formatter | `{...getAxisPreset()}`, `tickFormatter={(v) => formatPercent(v, { decimals: 0, sign: false })}` |
| `Tooltip` (164-167) | Inline `formatter` (2-decimal %, no sign), `labelFormatter` (passthrough) | `content={<ChartTooltip defaultFormat="percent" />}`. Note: ChartTooltip's `formatPercent` uses 1 decimal + sign by default vs current 2 decimal no sign — minor formatting change, acceptable |
| `Line` strokes | `#10b981` (portfolio), `#6366f1` (benchmark) | `getChartColor(0)` and `getChartColor(1)` |
| `Legend` (168) | Raw | Keep as-is (portfolio vs benchmark needs legend) |
| Missing: `CartesianGrid` | None | Add `<CartesianGrid {...getGridPreset()} />` |

### NOT Migrated

- **`PerformanceChart.tsx`** — Not Recharts (custom SVG/div bars). Would be a complete rewrite, not a migration. Skip.
- **`stock-lookup/PriceChartTab.tsx`** — Already migrated in Phase 1b.

### Import changes

**MonteCarloTab.tsx:**
- Add: `import { getAxisPreset, getGridPreset } from "../../../lib/chart-theme"`, `import { ChartContainer, ChartTooltip } from "../../blocks"`
- Add `CartesianGrid` to the recharts import (currently not imported)
- Remove `ResponsiveContainer` from recharts import (now via ChartContainer)
- Keep: `Area, AreaChart, Legend, Tooltip, XAxis, YAxis` in recharts import

**PerformanceTab.tsx:**
- Add: `import { getAxisPreset, getGridPreset, formatChartDate, getChartColor } from "../../../lib/chart-theme"`, `import { ChartContainer, ChartTooltip } from "../../blocks"`
- Add `CartesianGrid` to the recharts import (currently not imported)
- Remove `ResponsiveContainer` from recharts import (now via ChartContainer)
- Note: `formatPercent` already imported from `@risk/chassis`

---

## Batch 2b: StatPair Migration

### StatPair API

```tsx
<StatPair label="VaR 99%:" value="3.6%" valueColor="negative" size="sm" />
```

| Prop | Default | Options |
|------|---------|---------|
| `label` | required | Label text |
| `value` | required | `ReactNode` — formatted value |
| `valueColor` | `"neutral"` | `positive` (emerald), `negative` (red), `warning` (amber), `neutral` (foreground), `muted` |
| `bold` | `true` | Whether value is `font-semibold` |
| `size` | `"md"` | `sm` (text-xs), `md` (text-sm), `lg` (text-base) |
| `icon` | — | Optional icon node |

**Label color:** `text-muted-foreground` (CSS variable — adapts to dark mode). Current code uses `text-neutral-600` (hardcoded). This is a minor visual change in dark mode — neutral-600 stays the same shade; muted-foreground lightens. In light mode they're nearly identical.

### Migration Pattern

**Before:**
```tsx
<div className="flex justify-between text-sm">
  <span className="text-neutral-600">VaR 99%:</span>
  <span className="font-semibold text-red-600">3.6%</span>
</div>
```

**After:**
```tsx
<StatPair label="VaR 99%:" value="3.6%" valueColor="negative" />
```

### Migration Sites

#### 1. `stock-lookup/OverviewTab.tsx` — 4 StatPairs (lines 71-91)

The "Additional Risk Metrics" section has 4 label+value rows:
- `VaR 99%:` → value with `text-red-600` → `valueColor="negative"`
- `Max Drawdown:` → value with `text-red-600` → `valueColor="negative"`
- `S&P 500 Correlation:` → neutral value → `valueColor="neutral"`
- `Sector:` → neutral value → `valueColor="neutral"`

#### 2. `stock-lookup/TechnicalsTab.tsx` — 2 StatPairs (lines 54-56, 89-91)

Support/Resistance section has `Resistance:` and `Support:` label+value rows.
- Parent div has `text-sm`, labels are `text-neutral-600`, values are `font-bold text-red-600` / `font-bold text-emerald-600`
- StatPair defaults to `font-semibold`. Current code uses `font-bold`. Accept this minor weight change (bold → semibold) for consistency with the design system.

### NOT Migrated

- **`performance/PeriodAnalysisTab.tsx`** — Labels are `text-xs` but values are `text-sm font-bold`/`font-medium`. StatPair applies a single `size` to the whole row, so it can't represent different label/value sizes. Also Benchmark uses `font-medium` while Portfolio/Alpha use `font-bold` — mixed weights.
- **`stock-lookup/FundamentalsTab.tsx`** — "Valuation Metrics" rows all include progress bars (value + visual element). "Financial Health Score" rows have no explicit `text-neutral-600` class on labels. Skip both.
- **`stock-lookup/PortfolioFitTab.tsx`** — All label+value pairs use `grid grid-cols-2` or `grid grid-cols-4`, not flex justify-between. Different layout mechanism.
- **`RiskAnalysis.tsx`** — Uses `grid grid-cols-2` for Cost/Protection layout, not flex justify-between rows. Skip.
- **Metric card grids** (PerformanceHeaderCard, HoldingsSummaryCards) — vertical label-above-value, not horizontal
- **Table cells** (HoldingsTable, attribution tables) — table layout, not flex rows
- **Progress bar headers** (`StockLookup.tsx:323-332`, `FactorRiskModel.tsx:377-380`) — `flex justify-between text-xs` rows directly above `GradientProgress` bars. Tightly coupled to progress bars — not worth abstracting individually
- **`overview/AIRecommendationsPanel.tsx:61-74`** — 3-4 `flex justify-between text-sm` rows (Expected Impact, Confidence, Timeframe, optional Capital Required). Values use `font-medium` (not `font-semibold`). Only 3-4 instances in one file — low DRY benefit. Skip for now.
- **`performance/RiskAnalysisTab.tsx:49-82`** — 6 `flex justify-between text-sm` rows across drawdown and volatility sections. Labels use `text-red-800` (drawdown card) and `text-neutral-700` (volatility card) — semantic label colors that don't map to StatPair's `text-muted-foreground`. Skip.
- **`scenario/StressTestsTab.tsx:95,198`** — Shock and factor contribution rows use `flex justify-between` inside styled pill containers with borders/backgrounds. Not plain stat rows — specialized shock factor chips. Skip.
- **`strategy/BuilderTab.tsx:131,177`** — Not label+value pairs. Line 131 is slider range labels ("Conservative"/"Aggressive"), line 177 is a 5-way allocation bar legend. Skip.
- **Complex value layouts** (FactorRiskModel exposure/factor cards) — value side has multiple nested elements

### Import changes

For each migrated file:
- Add: `import { StatPair } from "../../blocks"` (or `"../blocks"` for top-level portfolio files)
- Cleanup: Remove unused spans/divs that the StatPair replaces

---

## Execution Order

1. **Batch 2a first** (Recharts) — 2 files, clear visual upgrade, higher value
2. **Batch 2b second** (StatPair) — 2 files (6 StatPairs), DRY cleanup with minor dark mode improvement

## Verification

1. `pnpm typecheck` — no type errors
2. `pnpm lint` — no lint errors
3. `pnpm build` — succeeds
4. Chrome verify: Monte Carlo chart, Strategy Performance chart, stock-lookup OverviewTab + TechnicalsTab

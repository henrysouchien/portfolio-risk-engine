# Benchmarks Tab Redesign Plan

## Problem

The Benchmarks tab in the Performance view has three issues:

1. **Duplication** — Portfolio Return, Benchmark Return, Excess Return, and Sharpe Ratio are all already shown in the PerformanceHeaderCard metric cards at the top. Repeating them in the Benchmarks tab wastes vertical space and adds no information.

2. **No visual narrative** — The tab is a flat grid of number tiles with no chart. Every other financial dashboard shows a cumulative return chart (portfolio line vs benchmark line) as the centerpiece of benchmark comparison. The `timeSeries` data exists (it's passed to RiskAnalysisTab already) but isn't used here.

3. **Flat metric dump** — 8 metrics in a 4x2 grid with no grouping. An investor doesn't know which metrics relate to each other or what story they tell.

## Current State

**BenchmarksTab.tsx** renders:
- 3 return cards (Portfolio Return, Benchmark Return, Excess Return) — all duplicated from PerformanceHeaderCard
- 8 metric tiles in a flat 4x2 grid (Beta, Sharpe, Info Ratio, Max Drawdown, Sortino, Calmar, Up Capture, Down Capture)
- Single `Card variant="glassTinted"` wrapper

**Data available but not used:**
- `timeSeries` (array of `{date, portfolioReturn, benchmarkReturn, ...}`) — available in parent, just not passed
- `trackingError` — available in `PerformanceData` but not rendered

**What's duplicated where:**
- Portfolio Return: PerformanceHeaderCard card 1 + BenchmarksTab card 1
- Benchmark Return: PerformanceHeaderCard card 2 + BenchmarksTab card 2
- Excess Return: PerformanceHeaderCard card 3 + BenchmarksTab card 3
- Sharpe Ratio: PerformanceHeaderCard card 4 + BenchmarksTab metric tile
- Max Drawdown: BenchmarksTab metric tile + RiskAnalysisTab drawdown section (with chart + duration)

## Design Audit — Patterns to Follow

### Card Structure
Tabs use either single or multi-card layouts:
- **Single card:** BenchmarksTab, RiskAnalysisTab, PeriodAnalysisTab
- **Multi-card:** AttributionTab (4 separate cards in `space-y-6`)
- **Common card props:** `variant="glassTinted"` + `className="p-6"`
- **Header:** `<CardHeader className="mb-4 p-0">` or `mb-6 p-0` with `<SectionHeader icon={X} title="..." colorScheme="..." size="sm" />`
- **Content:** `<CardContent className="p-0">`

For this redesign, **single card** is appropriate — the content density is moderate.

### Chart Pattern (PerformanceTrendChart — primary reference)
The overview already has a cumulative portfolio-vs-benchmark chart at `overview/PerformanceTrendChart.tsx`. This is the exact chart we need. Key patterns:
- Uses `ChartContainer height={200} minHeight={160}` with `isEmpty={!data?.length}` for empty state
- `AreaChart` with `<CartesianGrid {...grid} />`
- Portfolio line: `stroke={portfolioColor}`, gradient fill via `<defs>`, `strokeWidth={2}`, `dot={false}`, `activeDot={{ r: 4 }}`, `connectNulls`
- Benchmark line: `stroke={benchmarkColor}`, `fill="none"`, `strokeWidth={2}`, `strokeDasharray="6 3"`, `dot={false}`, `connectNulls`
- Benchmark color: zinc-300 light / zinc-500 dark (not `chartSemanticColors.neutral()`)
- Y-axis: right-oriented, clean tick intervals (step = 2/5/10/25 based on range), `formatPercent` formatter
- Tooltip: `<ChartTooltip defaultFormat="percent" dateGranularity="monthly" />`
- Legend: inline flex row with colored line segments (`h-[2px] w-3 rounded-full`) + labels in `text-xs text-muted-foreground`
- Domain: computed from both portfolio and benchmark returns so neither line is clipped

### Chart Pattern (RiskAnalysisTab — secondary reference)
- Chart containers wrapped in: `rounded-xl border border-neutral-200/60 bg-white/70 p-4`
- Title inside container: `text-sm font-semibold text-neutral-900` + `text-xs text-neutral-500`
- Lines: `strokeWidth={2.25}`, `dot={false}`, `activeDot={{ r: 4 }}`

### Metric Tiles (from current BenchmarksTab)
- Grid: `grid-cols-2 gap-3 md:grid-cols-4`
- Per tile: `rounded-xl border border-neutral-200/60 bg-neutral-50 p-3 transition-all duration-200 hover:bg-white hover:shadow-md hover-lift-subtle`
- Value: `text-base font-bold text-neutral-700`
- Label: `text-xs font-medium uppercase tracking-wide text-neutral-500`
- Tooltips: via `<Tooltip>/<TooltipTrigger>/<TooltipContent>` wrapping each tile

### Spacing
- Between major sections within card: `mb-6`
- Grid gaps: `gap-3` (metrics) or `gap-4` (larger cards)

### Colors
- Benchmarks tab uses `colorScheme="purple"` for its SectionHeader
- Positive values: emerald-600
- Negative values: red-600
- Neutral: neutral-700

## Proposed Design

Single card wrapper. Three sections stacked vertically:

### Section 1: Cumulative Return Chart (NEW)

**Purpose:** The visual centerpiece — portfolio vs benchmark over time.

**Chart approach:** Follow the `PerformanceTrendChart` pattern closely — same AreaChart structure, same gradient fill, same benchmark dashed line, same tooltip, same legend style.

**Period alignment:** The `timeSeries` data from the container is full-history (all available monthly data points). The chart will always show the full available history — this matches how RiskAnalysisTab uses the same `timeSeries` for rolling Sharpe/volatility/drawdown without period filtering. The chart title will read **"Cumulative Performance"** with a subtitle of **"Since inception"** to make the full-history scope explicit. The excess return callout in the header row IS period-specific (it comes from `performanceData.alpha` which respects `selectedPeriod`) and will be labeled with the period (e.g., "vs SPY · 1Y") to avoid ambiguity.

**Layout:**
- Header row: "Cumulative Performance" left (subtitle "Since inception") + excess return right (colored by `getAlphaColor()`, labeled "vs {benchmark} · {period}")
- Chart container: `rounded-xl border border-neutral-200/60 bg-white/70 p-4`
- Legend row below chart: inline flex with colored segments (same pattern as PerformanceTrendChart)
- `ChartContainer height={240} minHeight={180}` — slightly taller than RiskAnalysisTab charts since this is the hero
- Empty state: `isEmpty={!timeSeries?.length}` emptyMessage="No time series data available" (handled by ChartContainer)

**Chart details (matching PerformanceTrendChart):**
- Portfolio: solid area, `chartSemanticColors.positive()` (or `.negative()` if latest return < 0), gradient fill
- Benchmark: dashed line, zinc-300/zinc-500 for light/dark, `fill="none"`
- Domain: computed from both series so neither clips
- Y-axis: right-oriented, clean tick steps, percent formatter
- Tooltip: `<ChartTooltip defaultFormat="percent" dateGranularity="monthly" />`
- `ReferenceLine` at y=0

**Data:** Pass `timeSeries` from parent via `data?.timeSeries` (one-line change in PerformanceView.tsx).

### Section 2: Risk-Adjusted Quality (4 metrics)

**Purpose:** Group the four risk-adjusted ratios with quality context.

**Section label:** `text-[10px] font-semibold uppercase tracking-widest text-neutral-400 mb-2` — "RISK-ADJUSTED QUALITY"

**Layout:** `grid-cols-2 gap-3 md:grid-cols-4` (same as current metric grid, 4 metrics fills cleanly)

**Metrics:**
| Metric | Value source | Sublabel | Color |
|--------|-------------|----------|-------|
| Sharpe | `performanceData.sharpeRatio` | From `getSharpeStrength()` label | From `getSharpeStrength()` colorClass |
| Sortino | `performanceData.sortino` | "Downside-adjusted" | neutral-700 |
| Info Ratio | `performanceData.infoRatio` | "Active return / TE" | neutral-700 |
| Calmar | `performanceData.calmar` | "Return / max DD" | neutral-700 |

**Tile styling:** Same as current metric tiles + sublabel line: `text-[10px] text-neutral-400 mt-0.5`

**Tooltips:** Preserve existing tooltip for Sharpe (`generateTooltipContent("sharpe", ...)`). New metrics get one-line explanatory tooltips:
- Sortino: "Like Sharpe but only penalizes downside volatility"
- Info Ratio: "Excess return per unit of tracking error"
- Calmar: "Annualized return divided by max drawdown"

**Null handling:** Use existing `formatOptionalNumber()` which returns "--" for null/undefined.

### Section 3: Benchmark Sensitivity (4 metrics)

**Purpose:** Group metrics that describe how the portfolio behaves relative to its benchmark — market exposure, capture asymmetry, and active risk.

Note: Info Ratio (Section 2) is mathematically active return / tracking error (Section 3). This split is intentional — Info Ratio is a *quality* measure (higher = better), while Tracking Error is a *behavior* measure (how much you deviate). Grouping by what-it-tells-the-investor, not by formula dependency.

**Section label:** "BENCHMARK SENSITIVITY" (same style)

**Layout:** `grid-cols-2 gap-3 md:grid-cols-4` (4 metrics fills cleanly)

**Metrics:**
| Metric | Value source | Sublabel | Color |
|--------|-------------|----------|-------|
| Beta | `performanceData.beta` | Dynamic: "Below market" / "Above market" / "Market-neutral" | neutral-700 |
| Up Capture | `performanceData.upCaptureRatio` | — | neutral-700 |
| Down Capture | `performanceData.downCaptureRatio` | — | neutral-700 |
| Tracking Error | `performanceData.trackingError` | "Active risk" | neutral-700 |

**Tooltips:** Preserve existing tooltip for Beta (`generateTooltipContent("beta", ...)`). New metrics get one-line explanatory tooltips:
- Up Capture: "% of benchmark gains captured when market is up"
- Down Capture: "% of benchmark losses captured when market is down"
- Tracking Error: "Annualized std dev of excess returns vs benchmark"

**Null handling:** `formatOptionalNumber()`/`formatOptionalPercent()` returns "--". If `trackingError` is null, tile still renders with "--" (consistent with other optional metrics).

### What Gets Removed
- The 3 duplicated return cards (Portfolio Return, Benchmark Return, Excess Return) — already in PerformanceHeaderCard
- Max Drawdown tile — already shown in RiskAnalysisTab with chart + duration + recovery context
- Sharpe tile as standalone — moved to Risk-Adjusted Quality section (not removed, regrouped)

### What Gets Added
- Cumulative return chart (timeSeries data)
- Tracking Error metric (was in data but not rendered)
- Section grouping labels
- Metric sublabels for context
- Empty state handling for chart

## Edge Cases

| Scenario | Handling |
|----------|----------|
| `timeSeries` empty or undefined | `ChartContainer isEmpty` shows "No time series data available" |
| Optional metrics null (`sortino`, `calmar`, `infoRatio`, `trackingError`, `upCaptureRatio`, `downCaptureRatio`) | `formatOptionalNumber()`/`formatOptionalPercent()` returns "--" |
| All capture ratios null | Tiles show "--", section still renders (no conditional hiding) |
| Dark mode | Benchmark line uses `dark:bg-zinc-500` / light `bg-zinc-300` (matching PerformanceTrendChart) |
| Responsive | `grid-cols-2` on mobile, `md:grid-cols-4` on desktop (same as current) |

## Files Changed

| File | Change |
|------|--------|
| `frontend/packages/ui/src/components/portfolio/performance/BenchmarksTab.tsx` | Full rewrite — chart + 2 metric sections |
| `frontend/packages/ui/src/components/portfolio/PerformanceView.tsx` | Add `timeSeries={data?.timeSeries}` prop to BenchmarksTab |

No changes to types.ts — `PerformanceTimeSeriesPoint` already defined.

## Implementation Notes

1. **Follow PerformanceTrendChart for chart code** — same AreaChart structure, gradient, benchmark dashed line, tooltip, legend, domain computation. Don't reinvent these patterns.
2. **Keep metric tiles identical to current pattern** — same border, bg, padding, font sizes. Only add sublabel line.
3. **Section labels are minimal** — just uppercase tracking text, not full SectionHeader components. SectionHeader stays only at the card level.
4. **Excess return callout in chart header** — right-aligned, colored by `getAlphaColor()`, labeled with period. This is the only period-specific number; the chart itself is full-history ("Since inception").
5. **Preserve existing tooltips** — Sharpe and Beta tooltips via `generateTooltipContent()` must survive the rewrite. New metrics get simple label tooltips.
6. **4 metrics per section** — both sections have exactly 4 metrics, so the `md:grid-cols-4` grid fills cleanly with no awkward gaps.

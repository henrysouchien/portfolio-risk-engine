# Codex Spec: Performance Trend Chart Improvements (T2 #9)

**Goal:** Add Y-axis labels, hover tooltips, a legend, and correct period label to the Performance Trend sparkline chart.

**Context:** The chart is a custom SVG component (`SparklineChart`) in `frontend/packages/ui/src/components/blocks/sparkline-chart.tsx`. Key facts about the current implementation that constrain this spec:

1. **SVG viewBox is `0 0 100 100`** — all coordinates are in a 0-100 unitless space, not CSS pixels. The `height` prop only sets the CSS `style.height`; it has no effect on internal SVG coordinates.
2. **`preserveAspectRatio="none"`** — the SVG stretches to fill its container width. The viewBox x-axis spans 0-100 regardless of pixel width.
3. **`buildPathData()` returns `points` as strings** — each point is `"x,y"` (e.g. `"25,63.2"`), not an object with `.x`/`.y` properties. Must use `point.split(",")` to extract coordinates (already done for dots).
4. **`data` is cumulative return percentages** — sourced from `portfolioCumReturn` in `PerformanceAdapter.transformTimeSeries()`. Values like `-1.2`, `3.5`, `12.8` representing cumulative % return. NOT monthly returns.
5. **The component imports `* as React`** — so hooks must be called as `React.useState`, not bare `useState`.
6. **Color classes are pre-defined in `sparklineColorSchemes`** — the `palette` object (looked up via `colorScheme` key) provides `stroke`, `dot`, `stopStart`, `stopEnd` as full Tailwind class strings (e.g. `"fill-emerald-500"`). Dynamic class interpolation like `` `fill-${colorScheme}-500` `` will NOT work without a Tailwind safelist, and no safelist exists in `tailwind.config.js`.
7. **`buildPathData()` normalizes y into 0-100 range** — `y = 100 - ((value - min) / range) * 100`. The actual data values are lost in SVG coordinates. To show real values, we must use the original `data` array indexed by point index.

---

## Approach: Enhance SparklineChart with SVG labels + hover

All SVG coordinate values below are in viewBox units (0-100), not pixels.

### Step 1: Widen viewBox to make room for Y-axis labels

**File:** `frontend/packages/ui/src/components/blocks/sparkline-chart.tsx`

The current viewBox is `"0 0 100 100"` with the chart line spanning the full 0-100 x-range. To add Y-axis labels on the left without overlapping the line, widen the viewBox and shift the chart area right.

**Constants** (add above `buildPathData`):

```typescript
const CHART_PADDING_LEFT = 18  // viewBox units reserved for Y-axis labels
const VIEWBOX_WIDTH = 118      // 100 (chart area) + 18 (label area)
const VIEWBOX_HEIGHT = 100
```

**Update `buildPathData` signature** to accept a left offset:

```typescript
function buildPathData(data: number[], offsetX: number = 0): { linePath: string; areaPath: string; points: string[] } {
  const max = Math.max(...data)
  const min = Math.min(...data)
  const range = max - min || 1

  const chartWidth = 100  // chart area is always 100 units wide

  const points = data.map((value, index) => {
    const x = offsetX + (index / (data.length - 1)) * chartWidth
    const y = 100 - ((value - min) / range) * 100
    return `${x},${y}`
  })

  const linePath = points
    .map((point, index) => {
      const [x, y] = point.split(",")
      return index === 0 ? `M ${x} ${y}` : `L ${x} ${y}`
    })
    .join(" ")

  const lastX = offsetX + chartWidth

  return {
    linePath,
    areaPath: `${linePath} L ${lastX} ${VIEWBOX_HEIGHT} L ${offsetX} ${VIEWBOX_HEIGHT} Z`,
    points,
  }
}
```

**Update the SVG element** (uses `effectiveViewBoxWidth` from Step 3's conditional — NOT the raw `VIEWBOX_WIDTH` constant):

```tsx
<svg
  className="block w-full"
  viewBox={`0 0 ${effectiveViewBoxWidth} ${VIEWBOX_HEIGHT}`}
  preserveAspectRatio="none"
  style={{ height }}
  aria-hidden
>
```

**Update the call site** inside `SparklineChart` (uses `effectiveOffsetX` from Step 3's conditional):

```typescript
const { linePath, areaPath, points } = buildPathData(stableData, effectiveOffsetX)
```

**Add Y-axis min/max labels** inside the SVG, after the `</defs>` and before the area/line paths (guarded by `showLabels` in Step 3):

```tsx
{/* Y-axis labels — positioned in the left padding area, viewBox coords */}
<text x={CHART_PADDING_LEFT - 2} y={6} textAnchor="end" className="fill-neutral-400" fontSize={6} fontFamily="system-ui">
  {Math.max(...stableData).toFixed(1)}%
</text>
<text x={CHART_PADDING_LEFT - 2} y={98} textAnchor="end" className="fill-neutral-400" fontSize={6} fontFamily="system-ui">
  {Math.min(...stableData).toFixed(1)}%
</text>
```

Notes:
- `textAnchor="end"` right-aligns labels against the chart edge.
- `fontSize={6}` is in viewBox units. Because `preserveAspectRatio="none"`, the text will be visually stretched horizontally. At typical card width (~300-400px rendered vs 118 viewBox units), font will render at roughly 15-20px wide and ~5px tall, which is readable. If this is too distorted, an alternative is to use `vectorEffect="non-scaling-stroke"` on the text or a foreignObject — but try the simple approach first.
- `y={6}` places the max label near the top; `y={98}` places the min label near the bottom.
- **The viewBox and offset are conditional** (see Step 3). When `showLabels` and `showHoverTooltip` are both false, `effectiveViewBoxWidth=100` and `effectiveOffsetX=0`, preserving the original behavior for callers like `MetricCard`.

### Step 2: Add hover tooltip with value

**File:** `frontend/packages/ui/src/components/blocks/sparkline-chart.tsx`

Add new optional props to `SparklineChartProps`:

```typescript
export interface SparklineChartProps
  extends React.HTMLAttributes<HTMLDivElement> {
  data: number[]
  colorScheme?: SparklineColorScheme
  showFill?: boolean
  showDots?: boolean
  showLabels?: boolean       // NEW: show Y-axis min/max labels
  showHoverTooltip?: boolean // NEW: show value on hover
  strokeWidth?: number
  height?: number
  animate?: boolean
}
```

Default both new props to `false` so existing sparkline usages are unaffected.

**Add hover state** inside the component (remember: `React.useState`, not bare `useState`):

```typescript
const [hoveredIndex, setHoveredIndex] = React.useState<number | null>(null)
```

**Add invisible hover-detection rectangles** inside the SVG, after the dots section. Each rectangle covers one data segment in viewBox coordinates:

```tsx
{showHoverTooltip && stableData.map((_value, i) => {
  const segmentWidth = 100 / (stableData.length - 1)
  const segmentX = CHART_PADDING_LEFT + i * segmentWidth - segmentWidth / 2
  return (
    <rect
      key={`hover-${i}`}
      x={Math.max(CHART_PADDING_LEFT, segmentX)}
      y={0}
      width={Math.min(segmentWidth, VIEWBOX_WIDTH - Math.max(CHART_PADDING_LEFT, segmentX))}
      height={VIEWBOX_HEIGHT}
      fill="transparent"
      style={{ cursor: "crosshair" }}
      onMouseEnter={() => setHoveredIndex(i)}
      onMouseLeave={() => setHoveredIndex(null)}
    />
  )
})}
```

**Render the hover indicator** (circle + text) when a point is hovered. Place this after the hover rectangles:

```tsx
{showHoverTooltip && hoveredIndex !== null && (() => {
  const [cx, cy] = points[hoveredIndex].split(",")
  return (
    <>
      <circle
        cx={cx}
        cy={cy}
        r={2}
        className={palette.dot}
        style={{ pointerEvents: "none" }}
      />
      <text
        x={Number(cx)}
        y={Math.max(10, Number(cy) - 6)}
        textAnchor="middle"
        className="fill-neutral-700 dark:fill-neutral-200"
        fontSize={6}
        fontWeight={600}
        style={{ pointerEvents: "none" }}
      >
        {stableData[hoveredIndex].toFixed(1)}%
      </text>
    </>
  )
})()}
```

Key details:
- Parse point string with `.split(",")` — not `.x`/`.y` property access.
- Use `palette.dot` (e.g. `"fill-emerald-500"`) from the existing color map — NOT dynamic `` `fill-${colorScheme}-500` ``.
- `Math.max(10, cy - 6)` prevents the label from clipping above the viewBox top edge.
- `pointerEvents: "none"` so the tooltip elements don't interfere with hover detection.
- `fontSize={6}` matches the Y-axis labels.

### Step 3: Conditional viewBox + guard Y-axis labels behind `showLabels` prop

**IMPORTANT:** The viewBox and offset MUST be conditional. Other callers — notably `MetricCard` (`metric-card.tsx` line 114-122) — render `SparklineChart` without labels or hover, using the chart as a background sparkline. Unconditionally widening the viewBox to 118 would shift those charts right by 18 viewBox units, leaving a visible gap on the left. The conditional approach ensures existing callers get the exact `0 0 100 100` viewBox as before.

**Add computed values** inside the component, before the `buildPathData` call:

```typescript
const effectiveViewBoxWidth = showLabels || showHoverTooltip ? VIEWBOX_WIDTH : 100
const effectiveOffsetX = showLabels || showHoverTooltip ? CHART_PADDING_LEFT : 0
```

**Update the `buildPathData` call:**

```typescript
const { linePath, areaPath, points } = buildPathData(stableData, effectiveOffsetX)
```

**Update the SVG element to use `effectiveViewBoxWidth`:**

```tsx
<svg
  className="block w-full"
  viewBox={`0 0 ${effectiveViewBoxWidth} ${VIEWBOX_HEIGHT}`}
  preserveAspectRatio="none"
  style={{ height }}
  aria-hidden
>
```

**Wrap the Y-axis labels in a conditional:**

```tsx
{showLabels && (
  <>
    <text x={CHART_PADDING_LEFT - 2} y={6} textAnchor="end" className="fill-neutral-400" fontSize={6} fontFamily="system-ui">
      {Math.max(...stableData).toFixed(1)}%
    </text>
    <text x={CHART_PADDING_LEFT - 2} y={98} textAnchor="end" className="fill-neutral-400" fontSize={6} fontFamily="system-ui">
      {Math.min(...stableData).toFixed(1)}%
    </text>
  </>
)}
```

When neither `showLabels` nor `showHoverTooltip` is true, `effectiveViewBoxWidth` is 100 and `effectiveOffsetX` is 0 — the component behaves identically to the original implementation.

### Step 4: Add legend and period label to the parent card

**File:** `frontend/packages/ui/src/components/portfolio/PortfolioOverview.tsx`

In the Performance Trend card section (around line 79-98), update the card content to include a period label and legend row, and enable the new SparklineChart props:

```tsx
{performanceSparkline && performanceSparkline.length > 1 && (
  <Card variant="glassTinted" className="p-4 rounded-2xl shadow-sm">
    <div className="flex items-center justify-between mb-1">
      <p className="text-sm font-medium text-neutral-600">Performance Trend</p>
      <p className={`text-sm font-semibold ${
        performanceSparkline[performanceSparkline.length - 1] >= 0
          ? "text-emerald-600" : "text-red-600"
      }`}>
        {performanceSparkline[performanceSparkline.length - 1] >= 0 ? "+" : ""}
        {performanceSparkline[performanceSparkline.length - 1].toFixed(1)}%
      </p>
    </div>
    <div className="flex items-center gap-3 mb-2">
      <p className="text-xs text-neutral-400">Cumulative return</p>
      <span className="flex items-center gap-1 text-xs text-neutral-400">
        <span className={`inline-block w-3 h-0.5 rounded ${
          performanceSparkline[performanceSparkline.length - 1] >= 0
            ? "bg-emerald-500" : "bg-red-500"
        }`} />
        Portfolio
      </span>
    </div>
    <SparklineChart
      data={performanceSparkline}
      colorScheme={performanceSparkline[performanceSparkline.length - 1] >= 0 ? "emerald" : "red"}
      height={80}
      showFill
      showLabels
      showHoverTooltip
      strokeWidth={2}
    />
  </Card>
)}
```

Changes from the original:
- Period label says **"Cumulative return"** (not "Monthly returns") because the data is `portfolioCumReturn`.
- Legend row with a colored line swatch and "Portfolio" label.
- `showLabels` and `showHoverTooltip` props are enabled here (they default to false elsewhere).
- Margin between header row and legend row tightened (`mb-1` instead of `mb-2`).

---

## File Summary

| File | Changes |
|------|---------|
| `frontend/packages/ui/src/components/blocks/sparkline-chart.tsx` | Widen viewBox, offset `buildPathData` x-coords, add Y-axis labels (`showLabels`), add hover tooltip (`showHoverTooltip`), use `palette.dot` for hover circle |
| `frontend/packages/ui/src/components/portfolio/PortfolioOverview.tsx` | Add "Cumulative return" period label, legend swatch, pass `showLabels` + `showHoverTooltip` to SparklineChart |

## Verification

```bash
cd frontend && npx tsc --noEmit
```

Visually confirm in the browser:
1. Y-axis shows min/max percentage values, right-aligned against the chart edge.
2. Hovering over the chart shows a dot and percentage label at the hovered point.
3. Legend row shows a colored line swatch with "Portfolio" label.
4. Label reads "Cumulative return", not "Monthly returns".
5. Existing sparkline usages (without `showLabels`/`showHoverTooltip`) render identically to before.

## Risk Notes

- **`preserveAspectRatio="none"` text distortion:** SVG text inside a non-uniform viewBox gets stretched. At typical card widths (300-400px for 118 viewBox units wide, ~80px for 100 viewBox units tall), the 6-unit font will render roughly ~15px wide and ~5px tall, which should be readable but horizontally compressed. If this looks bad, the fix is to overlay an absolutely-positioned HTML `<div>` on top of the SVG for labels/tooltips instead of using SVG `<text>`. But try the SVG approach first — it is simpler and may look acceptable given the small label content.
- **Backward compatibility:** Both new props default to `false`. The viewBox widening and x-offset only apply when `showLabels || showHoverTooltip` is true (per the conditional `effectiveViewBoxWidth`/`effectiveOffsetX` in Step 3). Existing callers — including `MetricCard` (`metric-card.tsx` line 114) which uses SparklineChart as a background decoration — get the exact original `0 0 100 100` viewBox with zero offset.

# Monte Carlo Tool UI Redesign

## Context

The Monte Carlo Tool UI is functional but has significant design issues: the fan chart doesn't render as a proper probability cone, a 13-row percentile table wastes space with unreadable data, stats are shown redundantly in two places, and there's no visual hierarchy. This plan transforms it into a premium risk analytics view with 3 targeted changes.

## Phase 1 — Backend: Add Histogram Bins to Engine Output

**Why**: The engine computes all terminal simulation values but only returns 11 summary stats. We need binned histogram data for the frontend to render a terminal distribution chart.

### Step 1a: Engine histogram computation

**File**: `portfolio_risk_engine/monte_carlo.py`

After line 661 (after `terminal_distribution` dict), add:
```python
hist_counts, hist_bin_edges = np.histogram(terminal_values, bins=30)
histogram = {
    "bin_edges": [float(x) for x in hist_bin_edges],  # 31 edges
    "counts": [int(x) for x in hist_counts],            # 30 counts
}
```

Add `"histogram": histogram` to the return dict at line 663.

In `_build_flat_result()` (line 369), add `"histogram": None` to the flat-case return dict (after line 403).

### Step 1b: Flow through result object

**File**: `core/result_objects/monte_carlo.py`

- Add field: `histogram: Optional[Dict[str, Any]] = None` (after line 31)
- In `from_engine_output()`: add `histogram=data.get("histogram")` (after line 59)
- In `to_api_response()`: add `"histogram": self.histogram` (after line 151)
- In `get_agent_snapshot()`: no change needed (histogram is for rendering, not agent reasoning)

### Step 1c: Pydantic response model

**File**: `models/response_models.py`

Add to `MonteCarloResponse` (after line 179):
```python
histogram: Optional[Dict[str, Any]] = None
```

### Step 1d: Tests

**File**: `tests/test_monte_carlo.py` (engine tests)

Add tests:
1. `test_histogram_present_in_output` — run MC, assert `result["histogram"]` has `bin_edges` (31) and `counts` (30)
2. `test_histogram_counts_sum_to_num_simulations` — `sum(counts) == num_simulations`
3. `test_histogram_absent_in_flat_result` — flat result has `histogram: None`

**File**: `tests/test_monte_carlo_result.py` (result object serialization)

Extend `_engine_output()` fixture to include `"histogram": {"bin_edges": [...], "counts": [...]}`. Add tests:
4. `test_histogram_in_api_response` — `to_api_response()` includes histogram field
5. `test_histogram_roundtrip` — `from_engine_output()` preserves histogram data
6. `test_histogram_none_when_absent` — engine output without histogram → `result.histogram is None`

**File**: `tests/api/test_monte_carlo_api.py` (API response)

Add `"histogram"` key to the `_workflow_response()` fixture. Add two explicit assertions:
7. `test_api_histogram_present` — workflow response `response.json()["histogram"]` has correct shape (`bin_edges` list + `counts` list)
8. `test_api_histogram_null_for_flat` — flat/degenerate result returns `response.json()["histogram"] is None` (JSON `null`), pinning the exact contract that the TS type `| null` depends on

---

## Phase 2 — Frontend Type Extension + Descriptor

**File**: `frontend/packages/chassis/src/types/api.ts`

Add to `MonteCarloApiResponse` (after existing fields):
```typescript
histogram?: {
    bin_edges: number[];
    counts: number[];
} | null;
```

Note: The backend flat-result path returns `histogram: None` which serializes as JSON `null`. The TS type must accept both `undefined` (field absent) and `null` (field explicitly null from flat/degenerate results).

**File**: `frontend/packages/chassis/src/catalog/descriptors.ts`

Add to the Monte Carlo `fields` array (after line 615):
```typescript
{ name: 'histogram', type: 'object', description: 'Terminal value histogram with bin_edges and counts arrays.' },
```

---

## Cross-View Context Preservation (commit cf7a14c)

The recent cross-view context feature adds the ability for StressTest, Optimize, and WhatIf tools to pass context (weights, portfolio value, vol scale, distribution) into Monte Carlo, which auto-runs with that context. **All of this must be preserved in the redesign.**

### What must NOT change:
1. **Top-level normalizers**: `normalizeContextWeights()`, `normalizeContextNumber()`, `normalizeContextDistribution()` — keep as-is
2. **`initialContext` frozen state** (line 178) — context parsed once on mount
3. **5 context state vars** — `contextWeights`, `contextPortfolioValue`, `contextVolScale`, `contextSource`, `contextLabel`
4. **Distribution seeding from context** — two behaviors in the `useState` initializer (line 203):
   - (a) If `incomingDistribution` is set (e.g., StressTest passes `distribution: "t"`), use it directly — this is how Stress Test → MC gets Student-t
   - (b) If cached distribution is `bootstrap` but context has weights or vol_scale, auto-override to `normal` (bootstrap incompatibility guard)
5. **Auto-run dedup** — `contextKey` memo + `autoRunCache` in toolRunParams + auto-run useEffect
6. **`handleRun` context merge** — spreads `resolvedWeights`, `portfolioValue`, `volScale` into params
7. **Blue context banner** (line 497-519) — shows context source + "Clear context" button. In the new layout, this goes between the error banner and the CardContent results section (same position as today).

### What adapts to the new layout:
- The **context banner** stays in `CardHeader`, between error banner and the close of `</CardHeader>` — no change needed
- The **"Advanced options" collapsible** wraps Distribution + Drift Model + df. The distribution auto-override from context still works because it sets initial state, not the Select value directly.
- The **handleRun** already uses `useCallback` — no change needed for the layout restructure

---

## Phase 3 — Frontend UI Rewrite (All 3 Visual Changes)

All changes in **`frontend/packages/ui/src/components/portfolio/scenarios/tools/MonteCarloTool.tsx`**.

Do in this order: layout restructure first, then fan chart, then histogram.

### Step 3a: Layout Restructure + Stats Consolidation

**Remove**:
- 4-stat card grid — replaced by consolidated row
- Terminal Distribution sidebar card — redundant with stat cards
- Fan chart's own Card wrapper — chart goes directly in content

**Add**: Single consolidated stat row with 6 metrics:
```
| Median Terminal | P(Loss) | VaR 95% | CVaR 95% | P5/P95 Range | Max Gain/Loss |
```

Grid: `grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3`

**New layout order** (inside CardContent when result exists):
1. Insight banner (unchanged)
2. Warnings (unchanged)
3. Fan chart (hero — height 400px, no card wrapper)
4. Distribution summary text
5. Consolidated stat row (6 metrics)
6. Terminal histogram (new, from Step 3c)
7. Collapsible raw percentile table (hidden by default)

**Preserve in CardHeader** (above CardContent, in this order):
1. Title + description
2. Simulations + Horizon + Run button row
3. "Advanced options" collapsible (Distribution, Drift Model, df)
4. Error banner
5. **Cross-view context banner** (blue, with "Clear context") — unchanged from cf7a14c

**Progressive disclosure for config**: Wrap Distribution + Drift Model + df in a `<Collapsible>` with "Advanced options" trigger. Keep Simulations + Horizon + Run button always visible. The context-driven distribution auto-override (bootstrap → normal) is unaffected since it sets initial state via `useState()` initializer.

**New imports**: `Collapsible, CollapsibleTrigger, CollapsibleContent` from `ui/collapsible`, `ChevronDown` from `lucide-react`.

### Step 3b: Banded Fan Chart + Reference Line

**Replace** the 5 individual Area elements + 4 gradients with a proper probability cone.

**Data transformation** — new `buildBandRows` helper:
```typescript
const buildBandRows = (result: MonteCarloApiResponse | undefined) => {
  const pp = result?.percentile_paths
  if (!pp) return []
  const len = Math.max(pp.p5.length, pp.p25.length, pp.p50.length, pp.p75.length, pp.p95.length)
  return Array.from({ length: len }, (_, i) => ({
    month: i,
    p5: pp.p5[i], p25: pp.p25[i], p50: pp.p50[i], p75: pp.p75[i], p95: pp.p95[i],
    // Stacked band values:
    base_outer: pp.p5[i],
    outer_lower: (pp.p25[i] ?? 0) - (pp.p5[i] ?? 0),
    inner_band: (pp.p75[i] ?? 0) - (pp.p25[i] ?? 0),
    outer_upper: (pp.p95[i] ?? 0) - (pp.p75[i] ?? 0),
  }))
}
```

**Rendering** — stacked invisible-base technique:
```tsx
<Area dataKey="base_outer" stackId="bands" fill="transparent" stroke="none" legendType="none" />
<Area dataKey="outer_lower" stackId="bands" fill={bandColor} fillOpacity={0.10} stroke="none" legendType="none" />
<Area dataKey="inner_band" stackId="bands" fill={bandColor} fillOpacity={0.22} stroke="none" legendType="none" />
<Area dataKey="outer_upper" stackId="bands" fill={bandColor} fillOpacity={0.10} stroke="none" legendType="none" />
// Overlay strokes (non-stacked):
<Area dataKey="p50" fill="none" stroke={bandColor} strokeWidth={2} name="Median (P50)" />
<Area dataKey="p95" fill="none" stroke={bandColor} strokeWidth={1} strokeDasharray="4 2" name="P95" />
<Area dataKey="p5" fill="none" stroke={bandColor} strokeWidth={1} strokeDasharray="4 2" name="P5" />
```

**IMPORTANT — Tooltip filtering**: The custom `ChartTooltip` (chart-tooltip.tsx:78) renders every payload entry without filtering. The hidden stacked series (base_outer, outer_lower, inner_band, outer_upper) will appear in tooltips if not filtered. Fix by passing a custom `content` render prop to `<Tooltip>` that filters out band entries before delegating to `ChartTooltip`:

```tsx
<Tooltip
  content={({ active, payload, label }) => {
    const filtered = payload?.filter(
      (e) => !["base_outer", "outer_lower", "inner_band", "outer_upper"].includes(String(e.dataKey))
    )
    return (
      <ChartTooltip
        active={active}
        payload={filtered}
        label={label}
        defaultFormat="currency"
        labelFormatter={(month) => `Month ${month}`}
      />
    )
  }}
/>
```

This avoids modifying the shared ChartTooltip component.

**Color**: Single hue via `chartSemanticColors.positive()` at varying opacities. Delete the 4 gradient `<defs>` and the multi-color `colors` object.

**Reference line**: `<ReferenceLine y={monteCarlo.result.initial_value} {...getReferenceLinePreset()} />` with label "Starting Value". Import `ReferenceLine` from recharts, `getReferenceLinePreset` from chart-theme.

**Height**: 400px (up from 320px).

**Custom legend**: Replace default `<Legend>` with inline chips: "P5–P95 (90%)" | "P25–P75 (50%)" | "Median" | "Starting Value".

### Step 3c: Terminal Histogram

**Data memo**:
```typescript
const histogramData = useMemo(() => {
  const h = monteCarlo.result?.histogram
  if (!h?.bin_edges?.length || !h?.counts?.length) return []
  return h.counts.map((count, i) => ({
    midpoint: (h.bin_edges[i] + h.bin_edges[i + 1]) / 2,
    count,
    isLoss: (h.bin_edges[i] + h.bin_edges[i + 1]) / 2 < (monteCarlo.result?.initial_value ?? 0),
  }))
}, [monteCarlo.result])
```

**Rendering**: Recharts `<BarChart>` inside `<ChartContainer height={240}>`:
- **X-axis must be numeric**: `<XAxis type="number" dataKey="midpoint" domain={['dataMin', 'dataMax']} tickFormatter={...currency} />`. Recharts defaults to `type="category"` which would break the `<ReferenceLine x={initialValue}>` positioning. Using `type="number"` ensures the reference line appears at the correct numeric position.
- **ReferenceLine overflow**: Set `ifOverflow="extendDomain"` on the `<ReferenceLine x={initialValue}>`. Without this, the reference line is discarded if `initial_value` falls outside the histogram bin midpoint range (e.g., all-win or all-loss runs where every terminal value is above/below start). `ifOverflow="extendDomain"` forces the axis to stretch to include the reference value.
- `<Bar dataKey="count" radius={[2,2,0,0]}>` with `<Cell>` for conditional colors (red for loss bins, emerald for gain bins)
- `<ReferenceLine x={initialValue}>` vertical line at starting value (only works with numeric X axis)
- Y-axis: frequency count

**New imports**: `Bar, BarChart, Cell` from recharts.

### Step 3d: Collapsible Percentile Table

Wrap the existing percentile table in:
```tsx
<Collapsible>
  <CollapsibleTrigger className="flex items-center gap-2 text-xs text-muted-foreground">
    <ChevronDown className="h-3 w-3" /> Show raw percentile data
  </CollapsibleTrigger>
  <CollapsibleContent>
    {/* existing table JSX */}
  </CollapsibleContent>
</Collapsible>
```

---

## Files Modified

| File | Change |
|------|--------|
| `portfolio_risk_engine/monte_carlo.py` | Add histogram computation (~8 lines) |
| `core/result_objects/monte_carlo.py` | Add histogram field + flow (~4 lines) |
| `models/response_models.py` | Add histogram to Pydantic model (~1 line) |
| `frontend/packages/chassis/src/types/api.ts` | Extend TS type (~4 lines) |
| `frontend/packages/ui/src/.../MonteCarloTool.tsx` | Full UI rewrite (layout, fan chart, histogram, collapsibles) |
| `frontend/packages/chassis/src/catalog/descriptors.ts` | Add histogram field descriptor (line ~615) |
| `tests/test_monte_carlo.py` | 3 new engine histogram tests |
| `tests/test_monte_carlo_result.py` | 3 new result object serialization tests |
| `tests/api/test_monte_carlo_api.py` | Add histogram to API fixture |

## Verification

1. **Backend tests**: `pytest tests/test_monte_carlo.py tests/test_monte_carlo_result.py tests/api/test_monte_carlo_api.py -v` — all histogram tests pass (engine, result object, API)
2. **Frontend typecheck**: `cd frontend && npm run typecheck` — no TS errors from the new `histogram` type or component changes
3. **Frontend test suite**: `cd frontend && npm test` — all existing + any new tests pass
4. **Visual verification — direct MC**: Navigate to `http://localhost:3000/#scenarios/monte-carlo`, run a simulation:
   - Fan chart shows banded cone (inner P25-P75, outer P5-P95) with reference line at starting value
   - Single consolidated stat row (6 metrics, no duplication)
   - Terminal histogram below stats with red/green bars split at starting value
   - "Advanced options" collapsed by default, expands to show distribution/drift
   - "Show raw percentile data" collapsed by default
   - Page should require ~1.5 scrolls max (down from ~3+)
5. **Cross-view context regression tests** (preserve cf7a14c):
   - **Stress Test → MC**: Run a stress test, click "Simulate recovery" exit ramp. Verify: MC auto-runs with Student-t distribution, shocked portfolio value, 1.5x vol scale. Blue context banner shows source. Distribution select (inside "Advanced options") shows Student-t.
   - **Optimize → MC**: Run optimization, click "Simulate outcomes". Verify: MC auto-runs with optimized weights applied. Blue context banner shows source + "Custom weights applied".
   - **What-If → MC**: Run what-if, click "Simulate forward". Verify: MC auto-runs with scenario weights. Blue context banner shows source.
   - **Clear context**: On any cross-view arrival, click "Clear context". Verify: context banner disappears, next run uses default params.
   - **Auto-run dedup**: Navigate away from MC and back (same context). Verify: does NOT auto-run again (dedup via toolRunParams `monte-carlo:auto-context` key).

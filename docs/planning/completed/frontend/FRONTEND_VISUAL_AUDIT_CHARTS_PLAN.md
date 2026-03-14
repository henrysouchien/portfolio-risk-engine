# Visual Audit — Chart Features (V23, V25, V26)

## Context

Three remaining visual audit items all need recharts chart components. Recharts 2.8.0 is installed but unused. All three have data fully wired from backend through adapters — only the chart rendering is missing. No backend changes needed.

---

## V23. Stock Research — Price Chart Tab

**File:** `frontend/packages/ui/src/components/portfolio/StockLookup.tsx`

**Current state:** 6 tabs (Overview, Risk Factors, Technicals, Fundamentals, Peer Comparison, Portfolio Fit). No Price Chart tab. `selectedStock.chartData` prop exists with type `Array<{date: string, price: number, volume: number}>` (90-day OHLCV from FMP, already wired through container).

**Changes:**

1. Add recharts + lucide imports at top of file:
```tsx
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
```
Also add `TrendingUp` to the existing lucide-react import (not currently imported).

2. Add 7th tab trigger (line 619–626). Change grid from `grid-cols-6` to `grid-cols-7`:
```tsx
<TabsList className="grid w-full grid-cols-7 mb-4 bg-neutral-100/80 rounded-xl">
  ... existing 6 tabs ...
  <TabsTrigger value="price-chart" className="text-xs">📈 Price Chart</TabsTrigger>
</TabsList>
```

3. Add TabsContent after the last existing tab content (Portfolio Fit). The chart renders `selectedStock.chartData`:
```tsx
<TabsContent value="price-chart" className="flex-1 overflow-hidden">
  <ScrollArea className="h-[450px]">
    {selectedStock?.chartData && selectedStock.chartData.length > 0 ? (
      <div className="space-y-4">
        <Card className="p-4">
          <h4 className="text-sm font-semibold text-neutral-700 mb-3">Price History (90 Days)</h4>
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={selectedStock.chartData}>
              <defs>
                <linearGradient id="priceGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(d) => d.slice(5)} />
              <YAxis tick={{ fontSize: 10 }} domain={['auto', 'auto']} />
              <Tooltip formatter={(v: number) => [`$${v.toFixed(2)}`, 'Price']} labelFormatter={(l) => `Date: ${l}`} />
              <Area type="monotone" dataKey="price" stroke="#10b981" fill="url(#priceGradient)" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </Card>
        <Card className="p-4">
          <h4 className="text-sm font-semibold text-neutral-700 mb-3">Volume</h4>
          <ResponsiveContainer width="100%" height={120}>
            <AreaChart data={selectedStock.chartData}>
              <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(d) => d.slice(5)} />
              <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => `${(v / 1e6).toFixed(0)}M`} />
              <Tooltip formatter={(v: number) => [v.toLocaleString(), 'Volume']} />
              <Area type="monotone" dataKey="volume" stroke="#6366f1" fill="#6366f1" fillOpacity={0.2} strokeWidth={1.5} />
            </AreaChart>
          </ResponsiveContainer>
        </Card>
      </div>
    ) : (
      <div className="flex flex-col items-center justify-center h-full text-neutral-500">
        <TrendingUp className="w-8 h-8 mb-2 opacity-40" />
        <p className="text-sm">No price data available</p>
      </div>
    )}
  </ScrollArea>
</TabsContent>
```

---

## V25. Strategy Builder — Equity Curve Chart

**File:** `frontend/packages/ui/src/components/portfolio/StrategyBuilder.tsx`

**Current state:** Performance tab (line 832) shows 8 KPI metrics + attribution tables. `backtestData` passed from container is the full `BacktestData` from `BacktestAdapter` which includes `cumulativeReturns: Record<string, number>` and `benchmarkCumulative: Record<string, number>` — but the `StrategyBuilderBacktestData` interface (line 64) doesn't expose them.

**Changes:**

1. Widen `StrategyBuilderBacktestData` interface (line 64) to include time series:
```tsx
interface StrategyBuilderBacktestData {
  performanceMetrics: UnknownRecord;
  annualBreakdown: UnknownRecord[];
  securityAttribution: AttributionRow[];
  sectorAttribution: AttributionRow[];
  factorAttribution: AttributionRow[];
  benchmarkTicker: string;
  cumulativeReturns?: Record<string, number>;
  benchmarkCumulative?: Record<string, number>;
}
```

2. Add recharts imports:
```tsx
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from 'recharts';
```

3. In the Performance tab (after the KPI grid, ~line 880, before Annual Breakdown), add the equity curve chart. Transform data from dict → array:
```tsx
{(() => {
  const cumRet = backtestData.cumulativeReturns;
  const benchCum = backtestData.benchmarkCumulative;
  if (!cumRet || Object.keys(cumRet).length < 2) return null;
  const chartData = Object.keys(cumRet).sort().map((date) => ({
    date,
    portfolio: ((cumRet[date] - 1) * 100),
    benchmark: benchCum?.[date] != null ? ((benchCum[date] - 1) * 100) : undefined,
  }));
  return (
    <Card className="p-6 border-emerald-200/60">
      <h4 className="font-semibold text-emerald-900 mb-4">Equity Curve</h4>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={chartData}>
          <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(d) => d.slice(2)} />
          <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => `${v.toFixed(0)}%`} />
          <Tooltip formatter={(v: number) => [`${v.toFixed(2)}%`]} labelFormatter={(l) => l} />
          <Legend />
          <Line type="monotone" dataKey="portfolio" stroke="#10b981" strokeWidth={2} dot={false} name="Portfolio" />
          <Line type="monotone" dataKey="benchmark" stroke="#6366f1" strokeWidth={1.5} dot={false} strokeDasharray="4 2" name="Benchmark" />
        </LineChart>
      </ResponsiveContainer>
    </Card>
  );
})()}
```

---

## V26. Scenario Analysis — Monte Carlo Fan Chart

**File:** `frontend/packages/ui/src/components/portfolio/ScenarioAnalysis.tsx`

**Current state:** Monte Carlo tab (line 2023) shows 4 KPI cards + percentile paths table + terminal distribution grid after simulation runs. `monteCarloRows` already computed (line 348) as `Array<{month, p5, p25, p50, p75, p95}>` — perfect for recharts.

**Changes:**

1. Add recharts imports (at top of file):
```tsx
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from 'recharts';
```

2. Insert fan chart between KPI cards (line 2129) and Percentile Paths table (line 2131). Uses existing `monteCarloRows`:
```tsx
<Card className="p-4 border-blue-200/60">
  <h4 className="font-semibold text-blue-900 mb-3">Probability Cone</h4>
  <ResponsiveContainer width="100%" height={300}>
    <AreaChart data={monteCarloRows}>
      <defs>
        <linearGradient id="mcP5" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#ef4444" stopOpacity={0.15} />
          <stop offset="100%" stopColor="#ef4444" stopOpacity={0} />
        </linearGradient>
        <linearGradient id="mcP25" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#f59e0b" stopOpacity={0.2} />
          <stop offset="100%" stopColor="#f59e0b" stopOpacity={0} />
        </linearGradient>
        <linearGradient id="mcP75" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#10b981" stopOpacity={0.2} />
          <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
        </linearGradient>
        <linearGradient id="mcP95" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#10b981" stopOpacity={0.15} />
          <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
        </linearGradient>
      </defs>
      <XAxis dataKey="month" tick={{ fontSize: 10 }} label={{ value: 'Month', position: 'insideBottom', offset: -2, fontSize: 10 }} />
      <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} />
      <Tooltip formatter={(v: number) => [`$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}` ]} labelFormatter={(m) => `Month ${m}`} />
      <Area type="monotone" dataKey="p95" stroke="#10b981" fill="url(#mcP95)" strokeWidth={1} name="P95 (Best)" />
      <Area type="monotone" dataKey="p75" stroke="#10b981" fill="url(#mcP75)" strokeWidth={1} name="P75" />
      <Area type="monotone" dataKey="p50" stroke="#3b82f6" fill="none" strokeWidth={2} name="P50 (Median)" />
      <Area type="monotone" dataKey="p25" stroke="#f59e0b" fill="url(#mcP25)" strokeWidth={1} name="P25" />
      <Area type="monotone" dataKey="p5" stroke="#ef4444" fill="url(#mcP5)" strokeWidth={1} name="P5 (Worst)" />
      <Legend />
    </AreaChart>
  </ResponsiveContainer>
</Card>
```

---

## Files Modified

| File | Changes |
|------|---------|
| `StockLookup.tsx` | V23: recharts import, 7th tab trigger (grid-cols-7), Price Chart TabsContent with AreaChart + Volume chart |
| `StrategyBuilder.tsx` | V25: recharts import, widen `StrategyBuilderBacktestData` interface, equity curve LineChart in Performance tab |
| `ScenarioAnalysis.tsx` | V26: recharts import, fan chart AreaChart between KPI cards and percentile table |

## Verification

1. `cd frontend && pnpm typecheck` — must pass
2. Chrome: Stock Research → select stock → Price Chart tab shows 90-day area chart + volume area
3. Chrome: Strategy Builder → run backtest → Performance tab shows equity curve (portfolio vs benchmark)
4. Chrome: Scenario Analysis → Monte Carlo → run simulation → fan chart visible with 5 percentile bands
5. Empty states: Price Chart with no stock selected shows placeholder. Equity curve hidden when no backtest data. Fan chart only renders after simulation.

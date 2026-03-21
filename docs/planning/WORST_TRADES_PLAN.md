# Add Worst Trades to TradingDetailCard

## Context

The Trading P&L section shows "Best Trades" (top 5 by P&L) and a Return Distribution histogram. Adding "Worst Trades" (bottom 5 by P&L) gives the full picture.

## Changes — Single File

**`frontend/packages/ui/src/components/portfolio/performance/TradingDetailCard.tsx`**

### 1. Add `worstTrades` memo (after `topTrades` at line ~28)

```typescript
const worstTrades = useMemo(() => {
  return [...(data?.trade_scorecard ?? [])]
    .filter((trade) => trade.status.trim().toUpperCase() === 'CLOSED' && Number.isFinite(trade.pnl_dollars_usd))
    .sort((a, b) => a.pnl_dollars_usd - b.pnl_dollars_usd)
    .slice(0, 5)
}, [data?.trade_scorecard])
```

### 2. Extract trade row renderer

Extract the inline trade row JSX (lines ~71-99) into a local `TradeRow` component or helper function to avoid duplicating ~20 lines:

```typescript
// Infer the trade type from the array element — don't reference a named type that may not exist in scope
type ClosedTrade = (typeof closedTrades)[number]

function TradeRow({ trade, index }: { trade: ClosedTrade; index: number }) {
  const isShort = trade.direction.trim().toUpperCase() === 'SHORT'
  const tradeGrade = trade.grade.trim() || '—'
  const tradeGradeClasses = gradeToneClasses[baseGrade(tradeGrade)] ?? 'bg-neutral-100 text-neutral-600'
  const pnlTone = trade.pnl_dollars_usd >= 0 ? 'text-emerald-600' : 'text-red-600'
  // ... same JSX as current inline block
}
```

Alternatively, if the type inference approach is awkward inside the component, just inline the props as `{ trade: { symbol: string; direction: string; grade: string; pnl_dollars_usd: number; status: string }; index: number }` matching the fields actually used.

Both Best Trades and Worst Trades use `<TradeRow>`.

### 3. Layout — wrap left column

Wrap Best Trades + Worst Trades in a single `<div>` so they stay in the left column of the `md:grid-cols-2` grid. Return Distribution stays in the right column.

```html
<div className="grid grid-cols-1 gap-6 md:grid-cols-2">
  {/* Left column: Best + Worst trades stacked — only render if at least one list exists */}
  {(topTrades.length > 0 || worstTrades.length > 0) && (
    <div className="space-y-4">
      {topTrades.length > 0 && (
        <div>
          <p className="...">Best Trades</p>
          ...topTrades.map(trade => <TradeRow .../>)
        </div>
      )}
      {worstTrades.length > 0 && (
        <div>
          <p className="...">Worst Trades</p>
          ...worstTrades.map(trade => <TradeRow .../>)
        </div>
      )}
    </div>
  )}

  {/* Right column: Return Distribution */}
  {returnDistribution.length > 0 && (...)}
</div>
```

Left column wrapper only renders when at least one trade list has data — avoids empty column on desktop when only Return Distribution is available.

### 4. Empty state

Update the null-return guard (line ~60) to check both:
```typescript
if (topTrades.length === 0 && worstTrades.length === 0 && returnDistribution.length === 0) {
  return null
}
```

### 5. Overlap handling

With ≤10 total closed trades, best and worst lists can overlap. Use a shared `closedTrades` array and object identity to avoid duplicates:

```typescript
const closedTrades = useMemo(() => {
  return [...(data?.trade_scorecard ?? [])]
    .filter((trade) => trade.status.trim().toUpperCase() === 'CLOSED' && Number.isFinite(trade.pnl_dollars_usd))
}, [data?.trade_scorecard])

const topTrades = useMemo(() => {
  return [...closedTrades].sort((a, b) => b.pnl_dollars_usd - a.pnl_dollars_usd).slice(0, 5)
}, [closedTrades])

const worstTrades = useMemo(() => {
  const topSet = new Set(topTrades)  // object identity — no lossy key
  return [...closedTrades].sort((a, b) => a.pnl_dollars_usd - b.pnl_dollars_usd)
    .filter(trade => !topSet.has(trade))
    .slice(0, 5)
}, [closedTrades, topTrades])
```

This replaces the existing `topTrades` memo with a shared `closedTrades` base. Object identity dedup ensures distinct trades with identical P&L values are never collapsed. If after dedup there are no worst trades, the section doesn't render.

## What Does NOT Change

- Backend — `trade_scorecard` already has all data
- `useTradingAnalysis` hook — unchanged
- Return Distribution section — unchanged (right column)
- Trading P&L summary card above — unchanged

## Verification

1. `cd frontend && npx tsc --noEmit --project packages/ui/tsconfig.json 2>&1 | grep "TradingDetailCard"` — no errors in our file
2. Browser at desktop width: Best Trades + Worst Trades stacked in left column, Return Distribution in right column
3. Browser at mobile width: all sections stack vertically (single column)
4. Worst trades show negative P&L in red with grade badges
5. With few trades (≤10), no duplicate entries between best and worst
6. With zero losing trades, worst section shows lowest-profit trades (or doesn't render if all are in best)

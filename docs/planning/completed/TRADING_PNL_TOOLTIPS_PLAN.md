# Add Tooltips to Trading P&L Card Metrics

## Context

The Trading P&L card shows Profit Factor, Expectancy, Overall Grade, and Win Rate without any explanation of what they mean. The sub-grades already have tooltips, but these core metrics don't.

## Approach

Wrap existing containers in Tooltip — no visible "i" icons, no layout changes. Same pattern as the sub-grade tooltips already in this component. Add `cursor-help` and `tabIndex={0}` to div triggers for hover hint + keyboard accessibility.

## Changes

### File: `frontend/packages/ui/src/components/portfolio/performance/TradingPnLCard.tsx`

Wrap 4 metric areas in Tooltip. Each follows this pattern:

```tsx
<Tooltip>
  <TooltipTrigger asChild>
    <div className="cursor-help ..." tabIndex={0}>
      {/* existing content unchanged */}
    </div>
  </TooltipTrigger>
  <TooltipContent className="border-neutral-700 bg-neutral-900 text-white">
    {tooltip text}
  </TooltipContent>
</Tooltip>
```

### Tooltip Copy

| Metric | Tooltip |
|--------|---------|
| Profit Factor | Total gains divided by total losses. Above 1.0 means winners outweigh losers. |
| Expectancy | Average profit or loss per trade. Positive means your trades are profitable on average. |
| Overall Grade | Composite trading score across conviction, timing, sizing, and averaging down. A is best, F is worst. |
| Win Rate | Percentage of trades that were profitable (closed with a gain). |

### Specific Locations

1. **Profit Factor** (line ~159): Wrap the `<div className="rounded-xl bg-neutral-50/90 p-3">` containing the StatPair
2. **Expectancy** (line ~166): Same — wrap the `<div className="rounded-xl bg-neutral-50/90 p-3">`
3. **Overall Grade** (line ~177): Wrap the `<div className="flex items-center justify-between gap-3">` row
4. **Win Rate** (line ~150): Wrap the `<div className="text-right">` containing Win Rate label + value

All 4 get `cursor-help` added to their className and `tabIndex={0}` for keyboard focus.

## Files Changed

| File | Change |
|------|--------|
| `frontend/packages/ui/src/components/portfolio/performance/TradingPnLCard.tsx` | Wrap 4 metric areas in Tooltip |

## Verification

1. TypeScript check
2. Browser: Hover over Profit Factor, Expectancy, Overall Grade, Win Rate — tooltips appear
3. No layout shift — containers stay the same size
4. cursor-help cursor shows on hover
5. Tab key focuses metric areas and reveals tooltips (keyboard accessibility)

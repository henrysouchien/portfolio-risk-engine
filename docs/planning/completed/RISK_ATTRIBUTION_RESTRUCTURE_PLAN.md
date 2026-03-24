# Risk Attribution Tab — Improve Labels + Add Tooltips

## Context

The Risk Attribution tab shows Total Risk / Active Risk cards and Systematic / Idiosyncratic breakdown bars. The bars lack tooltips, and the relationship between the cards (volatility) and bars (variance share) isn't obvious. Adding tooltips and clearer bar labels makes the tab self-explanatory.

## Changes — Single File

**`frontend/packages/ui/src/components/portfolio/FactorRiskModel.tsx`**

### 1. Card Tooltips (already have tooltips via FACTOR_TOOLTIPS — improve the text)

Update `FACTOR_TOOLTIPS`:
```typescript
totalRisk: "Total annualized portfolio volatility — the standard deviation of your portfolio's returns over one year. Combines both systematic (factor-driven) and idiosyncratic (stock-specific) risk.",
activeRisk: "Idiosyncratic volatility — the portion of portfolio risk from individual stock moves, not explained by any factor. Diversification reduces this. Not benchmark tracking error.",
```

### 2. Bar Labels + Tooltips (lines 365-388)

Currently bars show `item.source` as the label (e.g., "Systematic Risk"). Add an Info icon with tooltip next to each label. Use `item.source` to select the right tooltip:

```typescript
const ATTRIBUTION_BAR_TOOLTIPS: Record<string, string> = {
  systematic: "Variance from factor exposures (market, interest rate, industry, momentum). This risk moves with broad market forces and can be managed through factor rebalancing or hedging.",
  idiosyncratic: "Variance from individual stock moves not explained by any factor. Driven by company-specific events. More diversified portfolios have lower idiosyncratic share.",
};
```

Render: wrap `item.source` text + Info icon in a `TooltipTrigger` (same pattern as factor exposure tooltips — `cursor-help` on the label, not icon-only). Lookup tooltip via explicit map:

```typescript
const ATTRIBUTION_BAR_TOOLTIP_MAP: Record<string, string> = {
  "Systematic Risk": ATTRIBUTION_BAR_TOOLTIPS.systematic,
  "Idiosyncratic Risk": ATTRIBUTION_BAR_TOOLTIPS.idiosyncratic,
};

const barTooltip = ATTRIBUTION_BAR_TOOLTIP_MAP[item.source] ?? null;
```

Exact string match against the labels emitted by the container (`frontend/packages/ui/src/components/dashboard/views/modern/FactorRiskModelContainer.tsx:191`). No substring matching.

Only render the Info icon + tooltip when `barTooltip` is non-null. Unknown source labels render plain text with no icon (safe degradation).

Keep bar labels as-is ("Systematic Risk" / "Idiosyncratic Risk"). The tooltips explain that the percentages are variance share. No label rename — avoids confusion with the companion `Vol:` number displayed on each bar.

### 3. No other changes

- Cards keep "Total Risk" / "Active Risk" names — no unit collision
- Bar values stay as-is (percentage + vol)
- Top Risk Contributors — unchanged
- Container — unchanged
- Backend — unchanged
- Props — unchanged

## Verification

1. `cd frontend && npx tsc --noEmit --project packages/ui/tsconfig.json 2>&1 | grep "portfolio/FactorRiskModel.tsx"` — no errors in our file (repo has pre-existing unrelated errors in other files; empty grep output = success)
2. Browser: Factors → Risk Attribution tab
   - Cards still show Total Risk and Active Risk with improved tooltip text
   - Bars show Info icons next to "Systematic Risk" and "Idiosyncratic Risk" labels
   - Hovering bar labels explains what systematic vs idiosyncratic variance means
   - Hovering card values shows updated tooltip text

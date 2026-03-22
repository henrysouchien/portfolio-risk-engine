# Risks & Signals Tab — Investor-Oriented Redesign

## Context
The Risks & Signals tab currently dumps raw technical indicators (RSI, MACD, Bollinger, Support/Resistance as separate cards) and factor exposures (5 factors × 2 bars each = 10 bars). An investor/PM/advisor doesn't know what to do with "RSI 34.9 Neutral" or "Momentum factor: β=-0.94, R²=11.3%." The data is correct but the presentation doesn't help with decisions.

The existing visual feel (fonts, font sizes, card styling, colors, gradients) is solid — we're keeping those. This is a layout and data presentation redesign, not a visual overhaul.

## Target Layout

**Two side-by-side summary cards** (matching the Snapshot tab's Valuation + Quality pattern):

```
┌──────────────────────────┐  ┌──────────────────────────┐
│ Technical Outlook        │  │ Risk Drivers             │
│                          │  │                          │
│ [headline signal]        │  │ Top 3 factors by risk    │
│                          │  │ influence, single bar    │
│ Support ──●── Resistance │  │ each, plain English      │
│                          │  │                          │
│ • Signal row 1           │  │                          │
│ • Signal row 2           │  │                          │
│ • Signal row 3           │  │                          │
└──────────────────────────┘  └──────────────────────────┘
```

## Implementation

### Single file change
**File:** `frontend/packages/ui/src/components/portfolio/stock-lookup/RisksSignalsTab.tsx`

Complete rewrite of the component's JSX. Same props interface (`selectedStock` + `riskFactors`). Will need to add tooltip imports (`Tooltip`, `TooltipProvider`, `TooltipTrigger`, `TooltipContent` from `../../ui/tooltip`). No backend, container, or type changes.

### Left Card: "Technical Outlook"

**Header:** Title "Technical Outlook" + headline badge derived from combined signals:
- Derive outlook from: RSI zone + MACD direction + Bollinger position
- Define shared constant: `const MACD_THRESHOLD = 0.01`
- Logic — MACD-anchored (momentum is the primary signal, RSI/Bollinger are secondary confirmation):
  - If MACD < -MACD_THRESHOLD AND (RSI >= 65 OR Bollinger === "Upper") → "Bearish" (red)
  - If MACD > MACD_THRESHOLD AND (RSI <= 35 OR Bollinger === "Lower") → "Bullish" (green)
  - If MACD < -MACD_THRESHOLD → "Cautious" (amber)
  - If MACD > MACD_THRESHOLD → "Constructive" (emerald-light)
  - Else (abs(MACD) <= MACD_THRESHOLD) → "Neutral" (amber)
  - Row 1 momentum label also uses this same threshold for consistency

**Support & Resistance visual** (keep from current — the green-to-red bar with price position marker is the most intuitive element):
- Same gradient bar with support/resistance labels
- Current price position indicator

**3 signal rows** (compact, one line each, replacing the 4 separate cards):
- Each row: status dot (colored) + plain English label + raw value in muted text
- Row 1 — Momentum: "Negative" / "Positive" / "Flat" based on MACD vs `MACD_THRESHOLD` (same constant as headline). Muted: `(MACD: {value})`
- Row 2 — RSI: descriptive label with context. Muted: `({value})`
  - If RSI <= 30: "Oversold"
  - If RSI <= 35: "Approaching oversold"
  - If RSI >= 70: "Overbought"
  - If RSI >= 65: "Approaching overbought"
  - Else: "Neutral"
  - (Note: check strict thresholds first, then "approaching" — reverse order from prior version)
- Row 3 — Bollinger: "Near lower band" / "Near upper band" / "Mid-range". Muted: `({bollinger} Band)`

**Status dot colors:**
- Green: bullish signal (MACD positive, RSI oversold/approaching, Bollinger lower)
- Red: bearish signal (MACD negative, RSI overbought/approaching, Bollinger upper)
- Amber: neutral

### Right Card: "Risk Drivers"

**Header:** Title "Risk Drivers" + subtitle "Top factors driving this stock's risk"

**Top 3 factors only:** Sort `riskFactors` by `risk` descending (this field is derived from R² — variance explained by the factor — which is the right metric for "how much does this factor drive the stock's behavior"). Take first 3. Copy the array before sorting to avoid mutating props.

**Each factor row:**
- Factor name (plain label — "Industry", "Market", "Subindustry")
- Single bar: Risk Influence only (drop the Exposure bar — redundant for this audience)
- Percentage value at end of bar
- No beta/R² in the visible row — available on hover via tooltip using `factor.description` (which already contains "Market factor: β=1.11, R²=48.2%"). Use `Tooltip`/`TooltipTrigger`/`TooltipContent`/`TooltipProvider` from `../../ui/tooltip` (same pattern as SnapshotTab).

**Styling:** Use the existing `GradientProgress` component for the bars. Keep the current card variant (`glassTinted`) and hover effects.

**Empty state:** If `riskFactors` is empty, show "Factor analysis not available for this stock" INSIDE the right card (not as a standalone element — preserves the two-card layout).

### What's removed
- Separate RSI card with big number + progress bar
- Separate MACD card with big number
- Separate Bollinger Bands card
- "Technical Signals" header card (integrated into left card title)
- "Factor Exposures" header card (integrated into right card title)
- Factor Exposure bars (only Risk Influence remains)
- Factors 4 and 5 from the visible list (still in data, just not shown — top 3 is enough)

### Visual consistency
- Left card: `border-blue-200/60 bg-gradient-to-br from-blue-50 to-blue-100/50` (same blue theme as current Technical Signals)
- Right card: `variant="glassTinted"` (same as current factor cards)
- Two-column grid: `grid grid-cols-1 gap-4 lg:grid-cols-2` (same as Snapshot tab)
- Signal rows: `text-sm`, dots as small colored circles, muted values in `text-xs text-muted-foreground`

## Files Changed

| File | Changes |
|------|---------|
| `RisksSignalsTab.tsx` | Complete rewrite of JSX layout (same props, same data) |

One production file. Tests should cover:
- RSI boundary ordering (30/35/65/70 — strict before approaching)
- MACD headline vs row consistency (shared MACD_THRESHOLD)
- Tooltip renders factor.description content
- Empty state stays inside right card (two-card layout preserved)

- Top-3 sorting/truncation (correct order, handles < 3 factors)

These can be lightweight snapshot or assertion tests in a new or existing test file.

## Verification
1. Load Stock Lookup → AAPL → Risks & Signals tab
2. Should see two side-by-side cards: Technical Outlook (left) + Risk Drivers (right)
3. Technical Outlook: headline badge (Bearish/Bullish/Cautious/Constructive/Neutral), support/resistance bar, 3 compact signal rows
4. Risk Drivers: top 3 factors sorted by risk influence (R²), single bar each
5. Hover on factor name should show beta/R² tooltip
6. Verify with a different stock (e.g., JPM) — signals and factors should reflect that stock's data
7. Screen should NOT require scrolling — everything fits in one view

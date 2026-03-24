# Portfolio Impact — Insight Box for Impact Verdict

## Context

The Portfolio Impact tab's key takeaway ("Reduces Portfolio Volatility, 1 Risk Limit Exceeded") is currently buried as a `text-xs text-muted-foreground` subtitle — the smallest element in the card. As the primary verdict of the what-if analysis, it should be the most visually prominent element, matching the insight box pattern used elsewhere in the app.

## Design

Replace the current "Impact Analysis" header + subtitle with an `InsightBanner` (shared block component at `components/blocks/insight-banner.tsx`) between the sizing card and the metrics table.

### Verdict Logic

Derive color scheme and narrative from the what-if metrics. `hasViolations` combines both `riskPasses` and `betaPasses` — if either fails, the verdict reflects it.

| Condition | Color | Icon | Title |
|-----------|-------|------|-------|
| Vol decreases, no violations | emerald | TrendingDown | "Low-risk addition" |
| Vol decreases, has violations | amber | ShieldAlert | "Reduces risk, but limits exceeded" |
| Vol increases, no violations | amber | TrendingUp | "Increases portfolio risk" |
| Vol increases, has violations | red | ShieldAlert | "Adds risk and breaches limits" |
| Vol unchanged, no violations | emerald | CheckCircle2 | "Neutral impact" |
| Vol unchanged, has violations | amber | ShieldAlert | "Risk limits exceeded" |
| Vol data unavailable | neutral | Info | "Impact analysis complete" |

Body text is a narrative sentence built from the metrics, e.g.:
> "Adding MSCI at 2.5% reduces annual volatility from 7.6% to 7.5%. Market beta moves to 0.61. 1 risk limit exceeded (Factor Var %)."

When vol data is unavailable (both before/after null), the verdict falls back to `neutral` colorScheme with a generic title — avoids making a confident claim without the core metric.

### Layout Change

**Before:**
```
[Impact Analysis card]
  "Impact Analysis" (h3, 15px semibold)
  "Add MSCI 2.5%" (14px)
  "Reduces Portfolio Volatility, 1 Risk Limit Exceeded" (12px muted)  ← buried
  [metrics table]
  ...
```

**After:**
```
[InsightBanner]  ← NEW, colored panel with icon + title + subtitle
  icon  "Low-risk addition" (sm semibold, colored)
        "Adding MSCI at 2.5% reduces annual volatility..." (xs, colored subtitle)

[Metrics card]  ← existing, now starts directly with the table
  "Add MSCI 2.5%" (scenario label, small, above table)
  [metrics table]
  [factor exposures]
  [compliance badges + violation details]
  [Preview Trade button]
```

When no analysis has been run yet, show the existing empty state ("Select a size to analyze...") in the metrics card — no insight banner.

## Implementation

### File: `PortfolioFitTab.tsx`

**1. Update imports:**
```tsx
import { Activity, Calculator, CheckCircle2, Info, RefreshCw, ShieldAlert, TrendingDown, TrendingUp, XCircle } from "lucide-react"
import { InsightBanner } from "../../blocks"
```
Add `useMemo` to the React import. Add `Info, ShieldAlert, TrendingDown, TrendingUp` to lucide. Import `InsightBanner` from blocks.

**2. Replace `impactSummary` IIFE with `insight` useMemo:**

```tsx
const insight = useMemo(() => {
  if (!portfolioFitAnalysis) return null
  const volMetric = portfolioFitAnalysis.metrics.find(m => m.label === 'Annual Volatility')
  const volBefore = volMetric?.before
  const volAfter = volMetric?.after
  const hasVolData = volBefore != null && volAfter != null
  const volDelta = hasVolData ? volAfter - volBefore : null
  const volDecreases = volDelta !== null && volDelta < 0
  const volIncreases = volDelta !== null && volDelta > 0
  const hasViolations = portfolioFitAnalysis.riskPasses === false || portfolioFitAnalysis.betaPasses === false

  const betaMetric = portfolioFitAnalysis.metrics.find(m => m.label === 'Market Beta')
  const betaAfter = betaMetric?.after

  // Build narrative body
  const parts: string[] = []
  if (hasVolData) {
    const dir = volDecreases ? 'reduces' : volIncreases ? 'increases' : 'maintains'
    parts.push(`${dir} annual volatility from ${formatPortfolioMetric(volBefore, 'percent')} to ${formatPortfolioMetric(volAfter, 'percent')}`)
  }
  if (betaAfter != null) {
    parts.push(`market beta moves to ${betaAfter.toFixed(2)}`)
  }
  if (hasViolations) {
    const violationParts: string[] = []
    if (portfolioFitAnalysis.riskPasses === false && portfolioFitAnalysis.riskViolations?.length) {
      const names = portfolioFitAnalysis.riskViolations.map(v => v.metric).join(', ')
      violationParts.push(`${portfolioFitAnalysis.riskViolationCount} risk limit${portfolioFitAnalysis.riskViolationCount === 1 ? '' : 's'} exceeded (${names})`)
    }
    if (portfolioFitAnalysis.betaPasses === false) {
      violationParts.push('factor beta limits exceeded')
    }
    parts.push(...violationParts)
  }

  const body = parts.length > 0
    ? `Adding ${selectedStock.symbol} at ${portfolioFitSize}% ${parts.join('. ')}.`
    : null

  // Determine tone — vol data unavailable falls to neutral
  if (!hasVolData) {
    return { icon: Info, colorScheme: 'neutral' as const, title: 'Impact analysis complete', body }
  }
  if (volDecreases && !hasViolations) {
    return { icon: TrendingDown, colorScheme: 'emerald' as const, title: 'Low-risk addition', body }
  }
  if (volDecreases && hasViolations) {
    return { icon: ShieldAlert, colorScheme: 'amber' as const, title: 'Reduces risk, but limits exceeded', body }
  }
  if (volIncreases && hasViolations) {
    return { icon: ShieldAlert, colorScheme: 'red' as const, title: 'Adds risk and breaches limits', body }
  }
  if (volIncreases) {
    return { icon: TrendingUp, colorScheme: 'amber' as const, title: 'Increases portfolio risk', body }
  }
  if (hasViolations) {
    return { icon: ShieldAlert, colorScheme: 'amber' as const, title: 'Risk limits exceeded', body }
  }
  return { icon: CheckCircle2, colorScheme: 'emerald' as const, title: 'Neutral impact', body }
}, [portfolioFitAnalysis, selectedStock.symbol, portfolioFitSize])
```

**3. Render InsightBanner** — insert between the sizing `</Card>` and the metrics `<Card>`:

```tsx
{insight && (
  <InsightBanner
    icon={insight.icon}
    colorScheme={insight.colorScheme}
    title={insight.title}
    subtitle={insight.body ?? undefined}
  />
)}
```

No custom tone helper needed — `InsightBanner` handles all color mapping internally.

**4. Clean up metrics card header** — remove old "Impact Analysis" h3 and impactSummary subtitle. Replace with just the scenario label above the metrics table:

```tsx
<Card variant="glassTinted" className="p-4">
  {portfolioFitAnalysis ? (
    <>
      <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground mb-3">
        {portfolioFitAnalysis.scenarioName}
      </div>
      {/* metrics table, factor exposures, compliance, Preview Trade — unchanged */}
    </>
  ) : (
    <div className="rounded-2xl border border-dashed border-border bg-muted px-4 py-10 text-center text-sm text-muted-foreground">
      Select a size to analyze how this position would change the portfolio.
    </div>
  )}
```

**5. Remove old `impactSummary` IIFE** — fully replaced by `insight`.

## Files Changed

| File | Changes |
|------|---------|
| `frontend/.../stock-lookup/PortfolioFitTab.tsx` | Replace impactSummary with InsightBanner, restructure card header |
| `frontend/.../stock-lookup/PortfolioFitTab.test.tsx` | Update assertions (see below) |

### Test Updates — `PortfolioFitTab.test.tsx`

**Stale assertions to fix:**
- Remove assertion for `"Impact Analysis"` heading (line ~137) — no longer rendered
- Add assertion for insight banner title, e.g. `screen.getByText("Adds risk and breaches limits")` (fixture has vol increasing + riskPasses: false)
- Add assertion for insight subtitle containing the narrative body text

**New test cases to add:**
- **Emerald verdict**: Override fixture with `riskPasses: true, betaPasses: true`, vol decreasing → assert "Low-risk addition"
- **Null vol data**: Override vol metric with `before: null, after: null` → assert "Impact analysis complete" (neutral fallback)
- **Beta-only violation**: Override with `riskPasses: true, betaPasses: false` → assert `hasViolations` is true, verdict reflects beta failure
- **No insight when no analysis**: Render with `portfolioFitAnalysis: null` → assert no insight title present

## Verification

1. Load MSCI on Research → Portfolio Impact → 2.5%
2. Confirm InsightBanner appears between sizing card and metrics with correct color
3. Confirm narrative subtitle reads naturally with vol direction + beta + violations
4. Confirm empty state (no analysis) shows dashed placeholder, no insight banner
5. Test with a vol-increasing stock to see amber/red verdict
6. Run frontend tests: `cd frontend && npx vitest run`

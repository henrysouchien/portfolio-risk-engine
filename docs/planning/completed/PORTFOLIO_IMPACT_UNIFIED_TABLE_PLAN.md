# Portfolio Impact — Unified Table with Section Dividers

## Context

The metrics card in the Portfolio Impact tab has three problems:
1. **Duplicate column headers** — Risk Metrics and Factor Exposures each render METRIC/CURRENT/WITH POSITION/IMPACT
2. **Factor exposure colors regressed** — Codex reverted the neutral gray fix; deltas are red/green again (line 333)
3. **Compliance badges feel disconnected** — different visual language from the table, tacked on at the bottom

## Design

Merge everything into one unified table with inline section dividers. One column header, three sections separated by lightweight label rows. Compliance becomes table rows instead of badges.

```
┌─────────────────────────────────────────────────────┐
│ METRIC            CURRENT   WITH POSITION    IMPACT │  ← single header
│─────────────────────────────────────────────────────│
│ Annual Volatility   7.6%      7.5%           -0.1% │
│ Market Beta         0.59      0.61           +0.02 │
│ Max Position Wt     14.0%     16.1%          +2.1% │
│ Factor-Driven Risk  91.8%     91.7%          -0.0% │
│                                                     │
│ ── FACTOR EXPOSURES ──────────────── divider row ── │
│ Market              0.59      0.61           +0.02 │  ← neutral gray
│ Momentum            0.28      0.26           -0.03 │
│ ...                                                 │
│                                                     │
│ ── LIMITS ─────────────────────────── divider row ──│
│ ✓ Risk Limits       Pass · All within bounds        │
│ ⊘ Factor Betas      Fail · Factor Var %: 91.7%     │
│                              (limit 85.0%)          │
│                                                     │
│ [Preview Trade]                                     │
└─────────────────────────────────────────────────────┘
```

## Implementation

### File: `PortfolioFitTab.tsx`

All changes in one file. No type/container changes needed.

#### 1. Fix factor exposure color regression (line ~333)

Change:
```tsx
<span className={`font-semibold ${getMetricDeltaTone(metric)}`}>
```
to:
```tsx
<span className="font-semibold text-muted-foreground">
```

This was the original Change A fix that Codex reverted during the insight box implementation.

#### 2. Restructure into unified table

Replace the entire `{portfolioFitAnalysis ? ( ... ) : ( ... )}` block (lines ~284-389) with a single table structure:

```tsx
{portfolioFitAnalysis ? (
  <>
    {/* Single column header */}
    <div className="grid grid-cols-4 gap-2 border-b border-neutral-200 pb-2 text-[11px] font-medium uppercase tracking-wide text-neutral-500">
      <span>Metric</span>
      <span>Current</span>
      <span>With Position</span>
      <span>Impact</span>
    </div>

    {/* Risk metrics rows */}
    <div className="space-y-0.5 py-2">
      {portfolioFitAnalysis.metrics.map((metric) => (
        <div key={metric.label} className="grid grid-cols-4 gap-2 py-1.5 text-sm items-center">
          <span className="text-neutral-700">{metric.label}</span>
          <span className="font-semibold text-neutral-900">{formatPortfolioMetric(metric.before, metric.format)}</span>
          <span className="font-semibold text-neutral-900">{formatPortfolioMetric(metric.after, metric.format)}</span>
          <span className={`font-semibold ${getMetricDeltaTone(metric)}`}>{formatPortfolioDelta(metric)}</span>
        </div>
      ))}
    </div>

    {/* Factor exposures section divider + rows */}
    {hasFactorExposures && (
      <>
        <div className="border-t border-neutral-200 pt-3 pb-1 mt-1">
          <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Factor Exposures</span>
        </div>
        <div className="space-y-0.5 py-1">
          {factorExposures.map((metric) => (
            <div key={metric.label} className="grid grid-cols-4 gap-2 py-1.5 text-sm items-center">
              <span className="text-neutral-700">{metric.label}</span>
              <span className="font-semibold text-neutral-900">{formatPortfolioMetric(metric.before, metric.format)}</span>
              <span className="font-semibold text-neutral-900">{formatPortfolioMetric(metric.after, metric.format)}</span>
              <span className="font-semibold text-muted-foreground">{formatPortfolioDelta(metric)}</span>
            </div>
          ))}
        </div>
      </>
    )}

    {/* Limits section divider + compliance rows */}
    <div className="border-t border-neutral-200 pt-3 pb-1 mt-1">
      <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Limits</span>
    </div>
    <div className="space-y-2 py-1">
      {/* Risk limits row — handles true/false/null */}
      <div className="flex items-start gap-2 text-sm">
        {portfolioFitAnalysis.riskPasses === null ? (
          <Minus className="mt-0.5 h-4 w-4 shrink-0 text-neutral-400" />
        ) : portfolioFitAnalysis.riskPasses === false ? (
          <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />
        ) : (
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />
        )}
        <div>
          <span className="font-medium text-neutral-900">Risk Limits</span>
          <span className="ml-1.5 text-neutral-500">
            {portfolioFitAnalysis.riskPasses === null
              ? 'Unavailable'
              : portfolioFitAnalysis.riskPasses === false
                ? `Fail · ${portfolioFitAnalysis.riskViolationCount} violation${portfolioFitAnalysis.riskViolationCount === 1 ? '' : 's'}`
                : 'Pass · All within bounds'}
          </span>
          {portfolioFitAnalysis.riskPasses === false && portfolioFitAnalysis.riskViolations?.map((v) => (
            <div key={v.metric} className="text-xs text-red-600 mt-0.5">
              {v.metric}: {formatPortfolioMetric(v.actual, 'percent')} (limit {formatPortfolioMetric(v.limit, 'percent')})
            </div>
          ))}
        </div>
      </div>

      {/* Factor beta limits row — handles true/false/null */}
      <div className="flex items-start gap-2 text-sm">
        {portfolioFitAnalysis.betaPasses === null ? (
          <Minus className="mt-0.5 h-4 w-4 shrink-0 text-neutral-400" />
        ) : portfolioFitAnalysis.betaPasses === false ? (
          <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />
        ) : (
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />
        )}
        <div>
          <span className="font-medium text-neutral-900">Factor Beta Limits</span>
          <span className="ml-1.5 text-neutral-500">
            {portfolioFitAnalysis.betaPasses === null
              ? 'Unavailable'
              : portfolioFitAnalysis.betaPasses === false ? 'Fail · Factor beta exceeded' : 'Pass · All within bounds'}
          </span>
        </div>
      </div>
    </div>

    {/* Preview Trade button */}
    <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-neutral-200 pt-4">
      <Button ...>Preview Trade</Button>
      ...
    </div>
  </>
) : (
  <div className="rounded-2xl border border-dashed ...">Select a size to analyze...</div>
)}
```

#### 3. Remove `renderCheckBadge` helper

No longer needed — compliance is rendered inline. Remove the function (lines ~29-52) and the Badge import if unused elsewhere.

#### 4. Clean up imports

- Remove `Badge` import (check if used elsewhere in file first — it's not)
- Keep `CheckCircle2`, `XCircle` (already imported)

## What's Removed
- `renderCheckBadge` function
- Badge import
- Duplicate column header rows
- "Risk Metrics" and "Factor Exposure Changes" as separate section titles with their own headers
- "Compliance Checks" section title

## Files Changed

| File | Changes |
|------|---------|
| `frontend/.../stock-lookup/PortfolioFitTab.tsx` | Unified table, fix factor colors, inline compliance, remove renderCheckBadge |
| `frontend/.../stock-lookup/PortfolioFitTab.test.tsx` | Update assertions for new structure (no badge text, check/x icons, inline limits) |

### Test Updates

**Remove/update:**
- `"Risk Limits: Fail · 2 violations"` badge text → assert `"Fail · 2 violations"` as inline text
- `"Factor Beta Limits: Pass · All betas within limits"` badge text → assert `"Pass · All within bounds"` as inline text
- `"Factor Exposure Changes"` → `"Factor Exposures"` (shorter label)
- `"Risk Metrics"` section label assertion → removed (no longer a standalone section label)

**Add:**
- Assert column header row (`"Metric"`, `"Current"`, `"With Position"`, `"Impact"`) appears exactly once (use `getAllByText` + length check on one of the headers)
- Assert violation detail text still renders (`"Max Position Weight: 5.0% (limit 4.5%)"`)
- Assert factor exposure deltas have `text-muted-foreground` class (re-verify Change A fix)
- Update the existing unavailable-state test (line ~283 in current test file) — should now assert `"Unavailable"` text with a `Minus` icon (neutral) instead of the old badge unavailable state

**Imports:**
- Add `Minus` to lucide-react imports in the component (for unavailable state icon)

## Verification

1. Load MSCI → Portfolio Impact → 2.5%
2. Confirm single header row, section dividers for Factor Exposures and Limits
3. Confirm factor exposure deltas are neutral gray
4. Confirm compliance rows show check/x icons with pass/fail + violation details
5. Run `cd frontend && npx vitest run`

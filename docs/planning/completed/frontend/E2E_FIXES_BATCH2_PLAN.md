# Frontend E2E Fixes — Batch 2 (Tier 1 + Tier 2)

## Context

Batch 1 (F1, F7/F2, F18) shipped in commit `2d1e1551`. This plan covers the remaining issues from the 2026-03-13 E2E audit. F8 (React setState warnings) was verified resolved — likely a cascade from the F1 ChatProvider crash.

**Resolved without code changes:**
- F8: setState warnings — gone after F1 fix (verified: 0 warnings on reload)
- F14: Truncated names — already has `title={holding.name}` on the element
- F19: "legacy tab stack" — already removed from current code
- F13: Sidebar tooltips — already has `title` attributes on nav buttons

**Labeling issues (F4, F5)** — not bugs, intentionally different metrics:
- F4: Dashboard alpha = annualized risk-adjusted. Performance alpha = period-specific excess return.
- F5: Holdings vol = avg individual stock vol. Performance vol = portfolio-level annualized std dev.

---

## Fix 1: F16 — Remove "Predictive" badge from Max Drawdown

**Problem**: "Risk & Drawdown Analysis" section header has a red "Predictive" badge, but Maximum Drawdown is a historical metric.

### File: `frontend/packages/ui/src/components/portfolio/performance/RiskAnalysisTab.tsx`

**Change** — Line 23: Remove the badge prop entirely
```tsx
// Before
badge={<Badge className="bg-red-100 text-xs text-red-800">Predictive</Badge>}
// After — delete this line
```

---

## Fix 2: F21 — Optimizer shows 0% before running

**Problem**: "Largest Weight" and "Total Allocated" show "0.0%" before any optimization runs, suggesting "sell everything."

### File: `frontend/packages/ui/src/components/portfolio/scenarios/tools/OptimizeTool.tsx`

**Change** — Lines 356, 360: Show "—" when no weights are active (`activeWeightSource === null`)
```tsx
// Line 356 — Largest Weight
// Before
{formatWeightPercent(largestWeight)}
// After
{activeWeightSource === null ? "—" : formatWeightPercent(largestWeight)}

// Line 360 — Total Allocated
// Before
{formatWeightPercent(totalAllocated)}
// After
{activeWeightSource === null ? "—" : formatWeightPercent(totalAllocated)}
```

---

## Fix 3: F23 — "Unknown" sector in attribution

**Problem**: Sector attribution shows "Unknown" at -0.6% for uncategorized holdings.

### File: `frontend/packages/ui/src/components/portfolio/performance/AttributionTab.tsx`

**Change** — Line 19: Map "Unknown" to "Other"
```tsx
// Before
render: (row) => <span className="font-medium text-neutral-900">{row.name}</span>,
// After
render: (row) => <span className="font-medium text-neutral-900">{row.name === 'Unknown' ? 'Other' : row.name}</span>,
```

---

## Fix 4: F20 — Unbalanced Scenarios grid (3+3+1)

**Problem**: 7 tool cards in a 3-col grid leaves Tax Harvest alone on the last row.

### File: `frontend/packages/ui/src/components/portfolio/scenarios/ScenariosLanding.tsx`

**Change** — Line 85: Switch to 4-col grid on XL for a balanced 4+3 layout
```tsx
// Before
<div className="grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-3">
// After
<div className="grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-4">
```

---

## Fix 5: F15 — Trading P&L poor empty state

**Problem**: Just shows "Trading analysis data is unavailable." — no icon, no context.

### File: `frontend/packages/ui/src/components/portfolio/performance/TradingPnLCard.tsx`

**Change** — Line 77: Add an icon and softer messaging
```tsx
// Before
<p className="text-sm text-muted-foreground">Trading analysis data is unavailable.</p>
// After
<div className="flex items-center gap-2 text-sm text-muted-foreground">
  <BarChart3 className="h-4 w-4 shrink-0" />
  <p>No trading history available yet.</p>
</div>
```
Note: `BarChart3` is not currently imported in TradingPnLCard.tsx. Need to add `import { BarChart3 } from 'lucide-react'` or use an existing icon.

---

## Verification

1. Navigate to Performance → Risk Analysis tab: no "Predictive" badge on drawdown section
2. Navigate to Scenarios → Strategy → Optimize: metrics show "—" before running
3. Navigate to Performance → Attribution tab: "Unknown" sector shows as "Other"
4. Navigate to Scenarios landing: grid is 4+3 on wide screens
5. Navigate to Performance: Trading P&L empty state has an icon
6. Run `cd frontend && npx vitest run`

## Files Modified

| File | Fix |
|------|-----|
| `frontend/packages/ui/src/components/portfolio/performance/RiskAnalysisTab.tsx` | F16: Remove "Predictive" badge |
| `frontend/packages/ui/src/components/portfolio/scenarios/tools/OptimizeTool.tsx` | F21: Show "—" when no weights |
| `frontend/packages/ui/src/components/portfolio/performance/AttributionTab.tsx` | F23: "Unknown" → "Other" |
| `frontend/packages/ui/src/components/portfolio/scenarios/ScenariosLanding.tsx` | F20: 3-col → 4-col grid |
| `frontend/packages/ui/src/components/portfolio/performance/TradingPnLCard.tsx` | F15: Icon + better empty state |

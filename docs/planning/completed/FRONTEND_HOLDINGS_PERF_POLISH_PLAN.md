# Frontend Holdings + Performance Polish Plan

## Goal

Add premium visual polish to Holdings and Performance sub-components. All additions are auto-gated by Phase 5 classic CSS overrides.

---

## Changes

### 1. HoldingsView.tsx (~1 line change)

**a) Add `variant="glassTinted"` to root Card (line 64)**

Current:
```tsx
<Card className="overflow-hidden rounded-2xl border-neutral-200/60 shadow-sm">
```

After:
```tsx
<Card variant="glassTinted" className="overflow-hidden rounded-2xl shadow-sm">
```

Replaces implicit `bg-white` + `border-neutral-200/60` with glassTinted (frosted bg, backdrop-filter, border).

### 2. HoldingsSummaryCards.tsx (~4 line changes)

**a) Add `hover-lift-subtle` to each MetricCard className**

MetricCard is a plain `<div>` with `transition-all duration-300` in its CVA base. No existing transforms, so `hover-lift-subtle` is safe. 4 hardcoded MetricCards get the class.

### 3. AttributionTab.tsx (~4 line changes)

**a) Add `variant="glassTinted"` to all 4 Card components (lines 140, 153, 171, 191)**

Current (all 4):
```tsx
<Card className="border-neutral-200/60 bg-white p-6">
```

After:
```tsx
<Card variant="glassTinted" className="p-6">
```

### 4. PeriodAnalysisTab.tsx (~3 line changes)

**a) Add `animate-stagger-fade-in` wrappers on monthly cards**

Monthly cards are `.map()`'d inside Tooltip wrappers. Stagger div goes outside Tooltip, key moves to wrapper.

Current:
```tsx
{performanceData.monthlyReturns.map(month => (
  <Tooltip key={month.date || month.month}>
    <TooltipTrigger asChild>
      <Card className="cursor-pointer border-neutral-200/40 transition-all duration-200 hover:-translate-y-1 hover:bg-white/80 hover:shadow-lg">
```

After:
```tsx
{performanceData.monthlyReturns.map((month, index) => (
  <div key={month.date || month.month} className="animate-stagger-fade-in" style={{ animationDelay: `${index * 0.08}s` }}>
    <Tooltip>
      <TooltipTrigger asChild>
        <Card className="cursor-pointer border-neutral-200/40 transition-all duration-200 hover:-translate-y-1 hover:bg-white/80 hover:shadow-lg">
```

Closing tags: add `</div>` after `</Tooltip>`.

**Why keep inline hover:** The monthly cards use `hover:-translate-y-1` (4px lift) which is intentionally more pronounced than `hover-lift-subtle` (1px). The parent Card already has `hover="lift"` — child cards should feel different.

### 5. BenchmarksTab.tsx (~1 line change)

**a) Add `hover-lift-subtle` to risk metric items (line 74)**

Current:
```tsx
<div className="cursor-pointer rounded-xl border border-neutral-200/60 bg-neutral-50 p-3 transition-all duration-200 hover:bg-white hover:shadow-md">
```

After:
```tsx
<div className="cursor-pointer rounded-xl border border-neutral-200/60 bg-neutral-50 p-3 transition-all duration-200 hover:bg-white hover:shadow-md hover-lift-subtle">
```

The `hover-lift-subtle` translateY(-1px) supplements the existing `hover:shadow-md`. In classic mode, the lift is neutralized but Tailwind's shadow-md still applies (pre-existing behavior).

---

## Dropped from Plan

| Item | Why |
|------|-----|
| `bg-white` on HoldingsTableHeader inputs | Form controls — glass backgrounds on inputs can look odd. Deferred to dark mode audit. |
| Stagger on HoldingsSummaryCards | 4 hardcoded cards (not mapped) — wrapping each in stagger div is verbose for minimal visual gain. |
| Monthly card hover change | Inline `hover:-translate-y-1` is intentionally stronger than `hover-lift-subtle`. Keep as-is. |
| BenchmarksTab top 3 metric cards | Already have `gradient-*` + `hover-lift-subtle`. Fully polished. |
| RiskAnalysisTab | Already has `variant="glassTinted"` + `hover="lift"` + `animate-magnetic-hover`. Fully polished. |
| PerformanceHeaderCard | Already 9/10 premium coverage. No changes needed. |

---

## Files Changed

| File | Change | Lines |
|------|--------|-------|
| `HoldingsView.tsx` | glassTinted on root Card | ~1 |
| `HoldingsSummaryCards.tsx` | hover-lift-subtle on 4 MetricCards | ~4 |
| `AttributionTab.tsx` | glassTinted on 4 attribution Cards | ~4 |
| `PeriodAnalysisTab.tsx` | Stagger wrappers on monthly cards | ~3 |
| `BenchmarksTab.tsx` | hover-lift-subtle on risk metrics | ~1 |

**Total: ~13 lines across 5 files.**

---

## Verification

1. `pnpm typecheck` passes
2. `pnpm build` succeeds
3. Chrome: Holdings root card has glass tinting, metric cards lift on hover, attribution cards have glass, monthly cards stagger in, risk metrics lift on hover.
4. Classic mode: All additions neutralized.

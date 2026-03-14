# Frontend Overview Polish Plan

## Goal

Add premium visual polish to the overview sub-components + orchestrator. All additions are auto-gated by the Phase 5 classic CSS overrides — no conditional logic needed.

---

## Current State

| Component | Lines | Premium Classes Used | Gap |
|-----------|-------|---------------------|-----|
| OverviewMetricCard | 414 | `animate-fade-in-gentle`, `animate-pulse-gentle` | No glass on card shell |
| AIRecommendationsPanel | 96 | `glassTinted`, `animate-fade-in-gentle`, `hover="subtle"` | No stagger on grid items |
| SmartAlertsPanel | 39 | `glassTinted`, `animate-fade-in-gentle` | Alert items are static — no hover effect |
| MarketIntelligenceBanner | 65 | `glassTinted`, `hover="subtle"`, `animate-fade-in-gentle`, `hover-lift-subtle` | Events missing stagger |
| PortfolioOverview (orchestrator) | 127 | None | Sparkline card is plain white |

---

## Changes

### 1. OverviewMetricCard.tsx (~1 line change)

**a) Add `variant="glassTinted"` to the main Card (line 65-66)**

The card already has custom hover behavior (`hover:scale-[1.005]`, `scale-[1.02]` on focus/hover state). Adding `hover="subtle"` would conflict — `hover-lift-subtle` applies `translateY(-1px)` which fights the existing scale transforms. So we only add the glass shell.

Current:
```tsx
<Card
  className={`group relative overflow-hidden bg-white border transition-all duration-500 cursor-pointer shadow-sm hover:shadow-xl ${
```

After:
```tsx
<Card
  variant="glassTinted"
  className={`group relative overflow-hidden transition-all duration-500 cursor-pointer shadow-sm hover:shadow-xl ${
```

This replaces the inline `bg-white border` with the Card CVA variant `glassTinted` (gives `glass-tinted shadow` class → frosted bg, backdrop-filter, border). The existing `shadow-sm hover:shadow-xl` and scale transforms are preserved as-is.

**Why not `hover="subtle"`:** The card already manages its own hover via inline Tailwind classes (`hover:scale-[1.005]`, conditional `scale-[1.02]`). Adding `hover-lift-subtle` would create competing transform declarations on the same element.

**Why not change the inner gradient:** The CardContent at line 120 has `bg-gradient-to-br from-white via-white to-neutral-50/20` which partially masks the glass. However, this gradient is part of the card's layered visual design (sparkline sits behind it). Changing it would require a broader refactor — deferred to the dark mode audit batch.

### 2. AIRecommendationsPanel.tsx (~3 line changes)

**a) Add `animate-stagger-fade-in` via wrapper divs on grid items (line 37-38)**

The recommendation cards already use `hover="subtle"` which applies `hover-lift-subtle` (transform-based). Putting `animate-stagger-fade-in` on the same element would conflict because both animate `transform`. Instead, wrap each card in a `<div>` that handles the entrance animation, keeping the transform contexts separate.

Current:
```tsx
{recommendations.map((rec) => (
  <Card key={rec.id} hover="subtle" className="p-4 border-neutral-200/40 flex flex-col h-full">
```

After:
```tsx
{recommendations.map((rec, index) => (
  <div key={rec.id} className="animate-stagger-fade-in" style={{ animationDelay: `${index * 0.08}s` }}>
    <Card hover="subtle" className="p-4 border-neutral-200/40 flex flex-col h-full">
```

The closing `</Card>` at line 90 gets a `</div>` wrapper after it:

Current:
```tsx
          </Card>
        ))}
```

After:
```tsx
          </Card>
        </div>
        ))}
```

### 3. SmartAlertsPanel.tsx (~1 line change)

**a) Add `hover-lift-subtle` to alert items (line 25)**

Alert items don't have any existing transform, so `hover-lift-subtle` is safe here.

Current:
```tsx
<div key={alert.id} className={`p-3 rounded-lg border ${
```

After:
```tsx
<div key={alert.id} className={`p-3 rounded-lg border hover-lift-subtle transition-all duration-200 ${
```

### 4. MarketIntelligenceBanner.tsx (~4 line changes)

**a) Add `animate-stagger-fade-in` via wrapper divs on event cards (line 31-32)**

Same rationale as AIRecommendationsPanel — the event cards already use `hover-lift-subtle` (transform-based), so stagger animation goes on a wrapper to avoid transform conflict.

Current:
```tsx
{events.map((event, index) => (
  <div key={index} className="p-4 bg-white/70 rounded-xl border border-blue-200/40 hover-lift-subtle transition-all duration-200">
```

After:
```tsx
{events.map((event, index) => (
  <div key={index} className="animate-stagger-fade-in" style={{ animationDelay: `${index * 0.08}s` }}>
    <div className="p-4 bg-white/70 rounded-xl border border-blue-200/40 hover-lift-subtle transition-all duration-200">
```

Closing tag becomes:
```tsx
          </div>
        </div>
        ))}
```

**Why not change `bg-white/70`:** This hardcoded white is not dark-safe, but fixing it requires switching to a CSS variable-based semi-transparent background. Deferred to the dark mode audit batch to avoid scope creep.

### 5. PortfolioOverview.tsx (orchestrator) (~1 line change)

**a) Add `variant="glassTinted"` to the Performance Trend sparkline card (line 89)**

Current:
```tsx
<Card className="p-4 bg-white border rounded-2xl shadow-sm">
```

After:
```tsx
<Card variant="glassTinted" className="p-4 rounded-2xl shadow-sm">
```

This replaces inline `bg-white border` with `glassTinted` (provides `glass-tinted shadow` → frosted bg, backdrop-filter, border). `shadow-sm` is kept for baseline elevation. `rounded-2xl` stays as override.

---

## Dropped from Plan (with rationale)

| Original item | Why dropped |
|---------------|-------------|
| `hover="subtle"` on OverviewMetricCard | Conflicts with existing inline scale transforms |
| `focus-premium` on Buttons | Button CVA base already has `focus-visible:ring-1 focus-visible:ring-ring` — adding `focus-premium` is unnecessary (not a literal no-op, but the existing focus ring is already adequate) |
| `focus-premium` on ViewControlsHeader | Same reason — all Buttons already have focus ring from CVA |
| `bg-white/70` → dark-safe token on MarketIntelligenceBanner | Dark mode fix — deferred to dark mode audit batch |
| Inner gradient fix on OverviewMetricCard | Requires broader refactor — deferred to dark mode audit batch |

---

## Files Changed

| File | Change | Lines |
|------|--------|-------|
| `OverviewMetricCard.tsx` | Add `variant="glassTinted"`, remove inline `bg-white border` | ~1 |
| `AIRecommendationsPanel.tsx` | Wrap grid items in stagger-animated divs | ~3 |
| `SmartAlertsPanel.tsx` | Add `hover-lift-subtle` to alert items | ~1 |
| `MarketIntelligenceBanner.tsx` | Wrap event cards in stagger-animated divs | ~4 |
| `PortfolioOverview.tsx` | Add `variant="glassTinted"` to sparkline card | ~1 |
| `index.css` | Fix stagger fill mode `forwards` → `both` | ~1 |

### 6. index.css — Fix stagger fill mode (~1 line change)

**a) Change `animate-stagger-fade-in` fill mode from `forwards` to `both` (line 661)**

`forwards` only preserves the end state after the animation completes. With `animationDelay`, delayed items show at full opacity before their animation starts, then suddenly animate — a visible flash. `both` applies the keyframe's initial state (`opacity: 0; transform: translateY(10px) scale(0.98)`) during the delay period too, so items stay hidden until their turn.

Current:
```css
.animate-stagger-fade-in {
  animation: stagger-fade-in 0.6s ease-out forwards;
}
```

After:
```css
.animate-stagger-fade-in {
  animation: stagger-fade-in 0.6s ease-out both;
}
```

**Note:** This is a global fix that improves `animate-stagger-fade-in` everywhere it's used with delays, not just in the overview components. The classic CSS override (`animation: none; opacity: 1; transform: none;`) already handles classic mode correctly — `both` vs `forwards` doesn't matter when animation is `none`.

---

**Total: ~11 lines across 6 files.**

---

## What This Does NOT Change

- **ModernDashboardApp.tsx** — already has 15+ premium classes, fully polished
- **ViewControlsHeader.tsx** — buttons already have adequate focus rings from Button CVA
- **SettingsPanel.tsx** — functional panel, not a data display component
- **helpers.ts / types.ts / index.ts** — utility/type files, no visual output
- **InstitutionalSparkline.tsx** — SVG chart internals, not a card/panel component

---

## Verification

1. `pnpm typecheck` passes
2. `pnpm build` succeeds
3. Chrome verification:
   - **Premium mode**: Metric cards + sparkline card have glass tinting. Recommendation and event grids stagger in. Alert items have subtle hover lift.
   - **Classic mode**: All additions neutralized — standard card backgrounds, no stagger animations, no hover lifts.
   - **Dark mode + Premium**: Glass tinting uses dark tokens correctly. Known limitation: these components have multiple hardcoded light-mode colors (`bg-white/70`, `bg-white`, `from-white via-white`, `text-neutral-900`, `text-emerald-900`, `bg-red-50`, `bg-amber-50`, `bg-blue-50`, etc.) that are not dark-safe. These are pre-existing issues unrelated to this polish batch — all tracked for the dedicated dark mode audit batch.

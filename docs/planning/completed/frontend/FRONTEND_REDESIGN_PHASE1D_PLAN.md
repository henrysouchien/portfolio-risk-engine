# Frontend Redesign — Phase 1d: Upgrade Base shadcn Components

**Date:** 2026-03-06
**Status:** DONE (`28a99734`)
**Source:** `FRONTEND_REDESIGN_PLAN.md` Phase 1d
**Depends on:** Phase 1a (colors.ts) DONE, Phase 1b (chart-theme) DONE, Phase 1c (blocks) DONE
**Codex Review:** R1 FAIL (F1-F3). R2 FAIL (F1-F2). R3: expanded NOT migrated section, clarified text-white as intentional dark mode fix.

---

## Context

Card and Button are the two most-used shadcn primitives. Both currently require consumers to manually add premium CSS classes via className strings:

- **Card** (`components/ui/card.tsx`): Plain `forwardRef`, no CVA variants. 23 usages manually apply `glass-premium`, `glass-tinted`, `hover-lift-premium`, or `hover-lift-subtle` via className.
- **Button** (`components/ui/button.tsx`): CVA with 6 variants (default, destructive, outline, secondary, ghost, link). 5 usages manually write the full emerald gradient + `btn-premium` shimmer pattern as a ~80-char className string.

The premium CSS classes (`glass-premium`, `glass-tinted`, `hover-lift-premium`, `hover-lift-subtle`, `btn-premium`) are already defined in `index.css` with dark mode and reduced-motion support. This phase formalizes them as CVA variants and migrates existing consumers.

---

## Step 1: Card CVA conversion

**File:** `frontend/packages/ui/src/components/ui/card.tsx`

### Current Card base class

```ts
"rounded-xl border bg-card text-card-foreground shadow overflow-hidden bg-clip-padding"
```

### Problem

`glass-premium` and `glass-tinted` set their own `background` and `border` via CSS. `glass-premium` also sets `box-shadow`, but `glass-tinted` does NOT — it relies on the Card's Tailwind `shadow` utility for its resting shadow. When consumers add these via className, they rely on CSS cascade to override Tailwind's `border` and `bg-card` utilities. This works but is fragile — the glass variants should replace conflicting base classes cleanly.

### New CVA structure

```typescript
import { cva, type VariantProps } from "class-variance-authority"

const cardVariants = cva(
  "rounded-xl text-card-foreground overflow-hidden bg-clip-padding",
  {
    variants: {
      variant: {
        default: "border bg-card shadow",
        glass: "glass-premium",
        glassTinted: "glass-tinted shadow",
      },
      hover: {
        lift: "hover-lift-premium",
        subtle: "hover-lift-subtle",
      },
    },
    defaultVariants: { variant: "default" },
  }
)
```

Key decisions:
- **Base class split**: `border bg-card shadow` moves from base into `default` variant. `glass` (glass-premium CSS) brings its own border, bg, AND box-shadow — no Tailwind `shadow` needed. `glassTinted` (glass-tinted CSS) brings its own border and bg but NO box-shadow — Tailwind `shadow` is included to preserve the current resting shadow behavior.
- **`hover` has no default**: Optional prop. Omitting it = no hover effect (backward compatible with all ~97 plain Card usages).
- **`variant` defaults to `"default"`**: Matches current behavior exactly.

### Updated Card component

```typescript
export interface CardProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof cardVariants> {}

const Card = React.forwardRef<HTMLDivElement, CardProps>(
  ({ className, variant, hover, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(cardVariants({ variant, hover }), className)}
      {...props}
    />
  )
)
```

### Backward compatibility

- All existing Card consumers without glass/hover classes continue to work identically (default variant = same classes as before).
- Consumers that still pass `className="glass-premium"` without using `variant="glass"` also still work (CSS cascade override, same as today). No forced migration.

### CardHeader, CardTitle, CardDescription, CardContent, CardFooter

**No changes.** These sub-components have no variant needs.

---

## Step 2: Button `premium` variant

**File:** `frontend/packages/ui/src/components/ui/button.tsx`

### New variant

Add `premium` to the existing `variant` object in `buttonVariants`:

```typescript
premium:
  "bg-gradient-to-br from-emerald-600 to-emerald-700 hover:from-emerald-700 hover:to-emerald-800 text-white shadow btn-premium",
```

This uses `shadow` as the baseline (matching the default variant). Consumer sites that need `shadow-md` or `shadow-lg` override via className. The `btn-premium` class adds the shimmer sweep pseudo-element (already defined in `index.css`).

### Why `text-white` instead of `text-primary-foreground`

The premium variant uses `text-white` intentionally. Four of five migration targets currently inherit `text-primary-foreground` from the default variant (only RiskSettingsViewModern:297 explicitly sets `text-white`). In light mode, `--primary-foreground` is `#fafbfc` (near-white) so there's no visible difference. In dark mode, `--primary-foreground` is `#0f1419` (near-black) — this produces unreadable dark text on the dark emerald gradient, which is a latent bug. Using `text-white` fixes this for all premium buttons.

### What about `btn-premium` on other variants?

Some consumers add `btn-premium` to `ghost` or `outline` buttons for shimmer-only effect. This is an orthogonal modifier, not a variant. These stay as `className="btn-premium"` — formalizing them as a separate prop isn't worth the complexity for the few instances that exist.

---

## Step 3: Export `cardVariants`

**File:** `frontend/packages/ui/src/components/ui/card.tsx`

Add `cardVariants` to the existing export statement so consumers can access variant types if needed:

```typescript
export { Card, CardHeader, CardFooter, CardTitle, CardDescription, CardContent, cardVariants }
```

`buttonVariants` is already exported.

---

## Step 4: Consumer migration

Mechanical find-and-replace. Remove premium class strings from className, add variant/hover props.

### Card migrations (23 sites across 12 consumer files)

**`components/portfolio/performance/BenchmarksTab.tsx`** (1 site)
```tsx
// Before
<Card className="glass-tinted hover-lift-premium animate-magnetic-hover border-neutral-200/60 p-6">
// After
<Card variant="glassTinted" hover="lift" className="animate-magnetic-hover border-neutral-200/60 p-6">
```

**`components/portfolio/performance/RiskAnalysisTab.tsx`** (1 site)
```tsx
// Before
<Card className="glass-tinted hover-lift-premium animate-magnetic-hover border-neutral-200/60 p-6">
// After
<Card variant="glassTinted" hover="lift" className="animate-magnetic-hover border-neutral-200/60 p-6">
```

**`components/portfolio/performance/PeriodAnalysisTab.tsx`** (1 site)
```tsx
// Before
<Card className="glass-tinted hover-lift-premium animate-magnetic-hover border-neutral-200/60 p-6">
// After
<Card variant="glassTinted" hover="lift" className="animate-magnetic-hover border-neutral-200/60 p-6">
```

**`components/portfolio/performance/PerformanceHeaderCard.tsx`** (1 site)
```tsx
// Before
<Card className="group morph-border glass-tinted hover-lift-premium animate-magnetic-hover overflow-hidden border-neutral-200/60 p-6">
// After
<Card variant="glassTinted" hover="lift" className="group morph-border animate-magnetic-hover overflow-hidden border-neutral-200/60 p-6">
```

**`components/portfolio/overview/SmartAlertsPanel.tsx`** (1 site)
```tsx
// Before
<Card className="p-4 glass-tinted border-purple-200/40 animate-fade-in-gentle">
// After
<Card variant="glassTinted" className="p-4 border-purple-200/40 animate-fade-in-gentle">
```

**`components/portfolio/overview/AIRecommendationsPanel.tsx`** (2 sites)
```tsx
// Line 20: outer Card — glass-tinted
// Before
<Card className="p-6 glass-tinted border-emerald-200/40 animate-fade-in-gentle">
// After
<Card variant="glassTinted" className="p-6 border-emerald-200/40 animate-fade-in-gentle">

// Line 38: inner recommendation Card — hover-lift-subtle (no glass, keeps default variant)
// Before
<Card key={rec.id} className="p-4 hover-lift-subtle border-neutral-200/40 flex flex-col h-full">
// After
<Card key={rec.id} hover="subtle" className="p-4 border-neutral-200/40 flex flex-col h-full">
```

**`components/portfolio/overview/MarketIntelligenceBanner.tsx`** (1 site)
```tsx
// Before
<Card className="p-5 glass-tinted border-blue-200/40 animate-fade-in-gentle hover-lift-subtle">
// After
<Card variant="glassTinted" hover="subtle" className="p-5 border-blue-200/40 animate-fade-in-gentle">
```

**`components/ui/notification-center.tsx`** (1 site)
```tsx
// Before
<Card className="glass-premium border-neutral-200/60 shadow-xl hover-lift-premium">
// After
<Card variant="glass" hover="lift" className="border-neutral-200/60 shadow-xl">
```

**`components/dashboard/views/modern/RiskSettingsViewModern.tsx`** (8 sites)
```tsx
// Lines 277, 343: glass-premium + hover-lift-premium
<Card variant="glass" hover="lift" className="rounded-3xl border-neutral-200/60">

// Line 321: glass-tinted + hover-lift-premium
<Card variant="glassTinted" hover="lift" className="animate-magnetic-hover border-neutral-200/60" ...>

// Lines 357, 417, 481, 528: glass-tinted + hover-lift-subtle
<Card variant="glassTinted" hover="subtle" className="border-neutral-200/60">

// Line 577: glass-tinted only
<Card variant="glassTinted" className="border-neutral-200/60">
```

**`components/settings/AccountConnections.tsx`** (3 Card sites)
```tsx
// Line 391: glass-tinted + hover-lift-premium
<Card variant="glassTinted" hover="lift" className="p-6 border-neutral-200/60 animate-magnetic-hover morph-border">

// Line 610: glass-tinted + hover-lift-premium
<Card variant="glassTinted" hover="lift" className="p-8 border-neutral-200/60">

// Line 669: glass-tinted + hover-lift-premium
<Card variant="glassTinted" hover="lift" className="p-8 border-neutral-200/60 animate-magnetic-hover">
```

**`components/auth/LandingPage.tsx`** (2 Card sites)
```tsx
// Line 236: glass-premium + hover-lift-premium
<Card variant="glass" hover="lift" className="group relative overflow-hidden animate-fade-in-up backdrop-blur-xl bg-white/80 dark:bg-gray-900/80 border border-white/20 dark:border-gray-700/30 shadow-2xl hover:shadow-blue-500/10 dark:hover:shadow-blue-400/10" ...>

// Line 300: glass-tinted + hover-lift-premium
<Card variant="glassTinted" hover="lift" className="group relative overflow-hidden animate-fade-in-up backdrop-blur-xl bg-white/80 dark:bg-gray-900/80 border border-white/20 dark:border-gray-700/30 shadow-2xl hover:shadow-emerald-500/10 dark:hover:shadow-emerald-400/10" ...>
```

**`components/apps/ModernDashboardApp.tsx`** (1 Card site)
```tsx
// Line 360: glass-premium
<Card variant="glass" className="p-12 text-center rounded-3xl border-neutral-200/60">
```

### Button migrations (5 sites across 3 consumer files)

**`components/settings/AccountConnections.tsx`** (3 Button sites)
```tsx
// Line 374
// Before
<Button className="bg-gradient-to-br from-emerald-600 to-emerald-700 hover:from-emerald-700 hover:to-emerald-800 shadow-md hover-glow-premium btn-premium">
// After
<Button variant="premium" className="shadow-md hover-glow-premium">

// Line 599
// Before
<Button className="bg-gradient-to-br from-emerald-600 to-emerald-700 hover:from-emerald-700 hover:to-emerald-800 hover-glow-premium btn-premium">
// After
<Button variant="premium" className="hover-glow-premium">

// Line 709
// Before
<Button className="w-full bg-gradient-to-br from-emerald-600 to-emerald-700 hover:from-emerald-700 hover:to-emerald-800 hover-glow-premium btn-premium animate-magnetic-hover">
// After
<Button variant="premium" className="w-full hover-glow-premium animate-magnetic-hover">
```

**`components/dashboard/views/modern/RiskSettingsViewModern.tsx`** (1 Button site)
```tsx
// Line 297
// Before
<Button className="bg-gradient-to-br from-emerald-600 to-emerald-700 hover:from-emerald-700 hover:to-emerald-800 text-white shadow-lg hover-lift-premium btn-premium disabled:opacity-70 disabled:cursor-not-allowed">
// After
<Button variant="premium" className="shadow-lg hover-lift-premium disabled:opacity-70 disabled:cursor-not-allowed">
```

**`components/chat/shared/ChatCore.tsx`** (1 Button site)
```tsx
// Line 1370 (shadcn <Button> with emerald gradient + btn-premium)
// Before
<Button type="submit" size="icon" className="absolute top-1/2 right-2 -translate-y-1/2 w-8 h-8 bg-gradient-to-br from-emerald-600 to-emerald-700 hover:from-emerald-700 hover:to-emerald-800 shadow-md rounded-lg hover-lift-premium btn-premium hover-glow-premium">
// After
<Button type="submit" size="icon" variant="premium" className="absolute top-1/2 right-2 -translate-y-1/2 w-8 h-8 shadow-md rounded-lg hover-lift-premium hover-glow-premium">
```

### NOT migrated (stays as className)

These use glass/hover/premium classes on non-Card elements, add shimmer without the emerald gradient, or have intentional differences from the variant. They are NOT in scope:

**Glass on non-Card elements:**
- `ModernDashboardApp.tsx`: `<div>`, `<header>` elements with glass classes (~6 sites)
- `ChatCore.tsx`: `<div>` elements with glass classes (~8 sites)
- `ChatInterface.tsx`: `<div>` elements (~2 sites)
- `PerformanceView.tsx`: `<TabsList>` with glass-tinted (~1 site)
- `PerformanceHeaderCard.tsx`: `<SelectTrigger>`, `<SelectContent>`, `<DropdownMenuContent>` (~5 sites)
- `AccountConnections.tsx`: `<DialogContent>` with glass-premium (~1 site)

**Emerald gradient Button without `btn-premium` (adding shimmer would change behavior):**
- `ModernDashboardApp.tsx:370`: `<Button>` with emerald gradient but NO `btn-premium`. Skip.

**Non-shadcn button elements:**
- `ModernDashboardApp.tsx:906`: Raw `<button>` element, not shadcn `<Button>`.

**All remaining `btn-premium`, `hover-lift-*`, `hover-glow-*` usages on Buttons (shimmer/hover as orthogonal modifier, not the emerald gradient pattern). These stay as className strings:**
- `RiskSettingsViewModern.tsx`: line 290 (`btn-premium` on outline Button)
- `AccountConnections.tsx`: lines 505, 511, 520, 555, 574, 590, 659, 660, 661, 698, 699, 700, 701 (`btn-premium`/`hover-lift-*` on default/ghost/outline Buttons)
- `ChatCore.tsx`: lines 1037, 1053, 1065, 1164, 1209, 1219, 1352 (`btn-premium`/`hover-lift-*` on Buttons)
- `ModernDashboardApp.tsx`: lines 373, 620, 639, 659, 800, 827 and others (`btn-premium`/`hover-lift-*` on nav/tab Buttons)
- `PerformanceHeaderCard.tsx`: lines 144, 179 (`hover-lift-*` on Buttons)
- `notification-center.tsx`: lines 139, 238 (`btn-premium`/`hover-lift-*` on Buttons)

---

## Files Summary

| File | Changes |
|------|---------|
| `ui/card.tsx` | Add CVA variants, update Card component signature |
| `ui/button.tsx` | Add `premium` to variant object (1 line) |
| `performance/BenchmarksTab.tsx` | Migrate 1 Card |
| `performance/RiskAnalysisTab.tsx` | Migrate 1 Card |
| `performance/PeriodAnalysisTab.tsx` | Migrate 1 Card |
| `performance/PerformanceHeaderCard.tsx` | Migrate 1 Card |
| `overview/SmartAlertsPanel.tsx` | Migrate 1 Card |
| `overview/AIRecommendationsPanel.tsx` | Migrate 2 Cards |
| `overview/MarketIntelligenceBanner.tsx` | Migrate 1 Card |
| `ui/notification-center.tsx` | Migrate 1 Card |
| `views/modern/RiskSettingsViewModern.tsx` | Migrate 8 Cards + 1 Button |
| `settings/AccountConnections.tsx` | Migrate 3 Cards + 3 Buttons |
| `auth/LandingPage.tsx` | Migrate 2 Cards |
| `apps/ModernDashboardApp.tsx` | Migrate 1 Card |
| `chat/shared/ChatCore.tsx` | Migrate 1 Button |

**Total: 2 infrastructure files + 13 consumer files = 15 files touched**
**Total migrations: 23 Card + 5 Button = 28 sites**

---

## Verification

1. `cd frontend && pnpm typecheck` — must pass
2. `cd frontend && pnpm build` — must pass
3. Visual inspection in Chrome (light mode): no visible changes expected for Card migrations; Button migrations are identical except `text-white` replaces inherited `text-primary-foreground` (both resolve to near-white in light mode)
4. Visual inspection in Chrome (dark mode): Button `variant="premium"` uses `text-white` instead of `text-primary-foreground` (`#0f1419` in dark mode). This is an intentional fix — dark text on emerald-600/700 gradient was a latent readability bug.
5. Spot-check in dev tools:
   - Card with `variant="glass"`: confirm `glass-premium` class present, `border`/`bg-card`/`shadow` absent
   - Card with `variant="glassTinted"`: confirm `glass-tinted` AND `shadow` classes present, `border`/`bg-card` absent
   - Button with `variant="premium"`: confirm emerald gradient classes + `btn-premium` + `text-white` present

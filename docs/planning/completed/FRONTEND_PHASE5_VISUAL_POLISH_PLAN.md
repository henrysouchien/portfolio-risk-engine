# Frontend Phase 5: Visual Polish Plan

## Goal

Define a real visual distinction between "classic" and "premium" themes via CSS-level gating, flip the default to "premium", then add premium polish to views that don't have it yet.

---

## Current State

### Infrastructure (Phase 4.75, `d00019ec`)
- `visualStyle: "classic" | "premium"` in `useUIStore`, persisted to localStorage
- `data-visual-style="classic|premium"` attribute synced to `<html>` by `App.tsx`
- Staged Classic/Premium toggle in SettingsPanel
- Default: `"classic"`

### Premium CSS classes defined (`index.css`)

| Class | Effect | Layer |
|-------|--------|-------|
| `glass-premium` | White 85% bg, blur(16px), multi-shadow, inner highlight | components |
| `glass-tinted` | White 70% bg, blur(8px), subtle border | components |
| `hover-lift-premium` | translateY(-4px) + scale(1.005) + shadow on hover | components |
| `hover-lift-subtle` | translateY(-1px) + light shadow on hover | components |
| `hover-glow-premium` | Emerald glow + shadow on hover | components |
| `btn-premium` | Shimmer sweep pseudo-element on hover | components |
| `morph-border` | Animated gradient border pseudo-element on hover | components |
| `focus-premium` | Emerald focus-visible outline + glow ring | components |
| `scroll-premium` | Thin gradient scrollbar, smooth scroll | components |
| `shimmer-loading` | Shimmer loading animation | components |
| `skeleton-premium` | Premium skeleton placeholder | components |
| `text-gradient-premium` | Emerald-to-blue gradient text with animation | components |
| `animate-fade-in-gentle` | 0.5s fade-in + translateY | utilities |
| `animate-stagger-fade-in` | 0.6s stagger fade-in + scale | utilities |
| `animate-breathe` | 4s breathing loop | utilities |
| `animate-pulse-gentle` | 2s pulsing loop | utilities |
| `animate-magnetic-hover` | Subtle lift + scale on hover | utilities |
| `animate-slide-up` | 0.3s slide-up entrance | utilities |
| `pulse-premium` | 3s breathing effect (faster variant) | utilities |

Already have: dark mode overrides (`.dark .glass-*`), `prefers-reduced-motion` overrides, mobile hover disabling.

### Pre-existing usage (18 files, ~130+ sites)

**Heavy** (~120 sites):
- `ModernDashboardApp.tsx` — ~50 sites (nav header, layout shell, dropdowns, view wrappers)
- `AccountConnections.tsx` — ~40 sites (settings/connections page)
- `ChatCore.tsx` — ~30 sites (message bubbles, input, actions)

**Component library** (4 files — define premium as opt-in variants):
- `card.tsx` — `variant="glass"/"glassTinted"`, `hover="lift"/"subtle"` CVA variants
- `button.tsx` — `variant="premium"` (emerald gradient + btn-premium shimmer)
- `insight-banner.tsx` — `variant="glass"`
- `data-table.tsx` — stagger animation on rows

**View components** (~10 sites):
- `OverviewMetricCard.tsx` — `animate-fade-in-gentle` (6 sites)
- `MarketIntelligenceBanner.tsx` — glassTinted + hover-lift-subtle
- `AIRecommendationsPanel.tsx` — glassTinted
- `SmartAlertsPanel.tsx` — glassTinted
- `PerformanceView.tsx` — glass-tinted on TabsList
- `PerformanceHeaderCard.tsx`, `BenchmarksTab.tsx`, `RiskMetrics.tsx`, `ChatInterface.tsx`, `RiskSettingsViewModern.tsx`, `notification-center.tsx`

---

## Design Decision: CSS-Level Gating

### Why not per-component gating?

The original Phase 4.75 plan suggested `isPremium && "glass-premium"` at every usage site. With ~130+ sites across 18 files, that means:
- Import `useVisualStyle` in every file
- Add `const isPremium = visualStyle === "premium"`
- Wrap every premium class in `cn(base, isPremium && "glass-premium")`
- ~200+ individual conditional expressions

This is a refactoring project, not a polish pass.

### CSS-level gating approach

Use the `data-visual-style` attribute already on `<html>` to neutralize premium effects:

```css
/* Classic theme: neutralize premium effects */
[data-visual-style="classic"] .glass-premium { ... }
[data-visual-style="classic"] .glass-tinted { ... }
[data-visual-style="classic"] .hover-lift-premium:hover { ... }
/* etc */
```

**Advantages:**
- ~70 lines of CSS gates ALL 130+ sites instantly
- Zero component file changes for the gating step
- New premium classes added in the polish pass are auto-gated
- Single source of truth for what "classic" looks like
- Follows same pattern as existing `.dark` overrides and `prefers-reduced-motion`

**Trade-off:**
- Premium classes remain in DOM in classic mode (visually neutralized, not removed)
- Acceptable — same pattern as `prefers-reduced-motion` which already does this

---

## Implementation Steps

### Step 1: Flip default to "premium" (~2 lines)

**File:** `frontend/packages/connectors/src/stores/uiStore.ts`

Change `getStoredVisualStyle()` to default to `"premium"` instead of `"classic"`:

```ts
function getStoredVisualStyle(): VisualStyle {
  try {
    const stored = window.localStorage.getItem('visualStyle');
    if (stored === 'classic') return 'classic';
    if (stored === 'premium') return 'premium';
  } catch {}
  return 'premium'; // was 'classic'
}
```

**Migration note:** Users who already have `"classic"` in localStorage (e.g., from Phase 4.75 testing) will stay on classic. Once Step 2 lands, they will see the new neutralized classic appearance. This is intentional — classic is a valid choice. New users (no localStorage) will default to premium.

Also update Reset to Defaults in SettingsPanel to reset to `"premium"` instead of `"classic"`:

**File:** `frontend/packages/ui/src/components/portfolio/overview/SettingsPanel.tsx`

```tsx
// In Reset to Defaults handler:
setDraftVisualStyle("premium") // was "classic"
```

### Step 2: Add classic theme CSS overrides (~70 lines)

**File:** `frontend/packages/ui/src/index.css`

Add a `[data-visual-style="classic"]` block after the dark mode overrides (after line 745), outside any `@layer` — matching the pattern used by `.dark .glass-*` overrides (also unlayered). This ensures the attribute selector beats the base definitions inside `@layer components` / `@layer utilities`.

**Important:** CSS custom properties like `--card` and `--border` contain raw HSL tuples (e.g., `0 0% 100%`). They must be wrapped in `hsl()` when used in CSS values. Tailwind does this automatically in utility classes, but hand-written CSS must use `hsl(var(--card))` explicitly.

```css
/* ========================================
   CLASSIC THEME — Neutralize premium effects
   ======================================== */

/* Glass effects → standard card backgrounds */
[data-visual-style="classic"] .glass-premium {
  background: hsl(var(--card));
  backdrop-filter: none;
  border: 1px solid hsl(var(--border));
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}

[data-visual-style="classic"] .glass-tinted {
  background: hsl(var(--card));
  backdrop-filter: none;
  border: 1px solid hsl(var(--border));
}

/* Hover lift/glow → static.
   Strategy: use POSITIVE gating on premium for the hover box-shadow rules.
   This avoids the problem of trying to "undo" a box-shadow in classic mode
   (inherit/none/unset all have wrong semantics). Instead, the premium hover
   shadows only apply when data-visual-style="premium". The base hover rules
   in index.css (lines 397, 410, 421) must be wrapped in the premium selector.
   Classic mode sees no transition and no hover changes at all. */

/* Classic: disable transitions so hover is visually inert */
[data-visual-style="classic"] .hover-lift-premium,
[data-visual-style="classic"] .hover-lift-subtle,
[data-visual-style="classic"] .hover-glow-premium {
  transition: none;
}

/* Classic: suppress transform on hover (box-shadow is NOT touched —
   the premium hover box-shadow rules are moved behind [data-visual-style="premium"]
   in the base definitions, so they simply don't fire in classic mode) */
[data-visual-style="classic"] .hover-lift-premium:hover,
[data-visual-style="classic"] .hover-lift-subtle:hover {
  transform: none;
}

/* ADDITIONALLY: the existing base hover rules in index.css must be modified
   to scope their box-shadow under [data-visual-style="premium"]:

   BEFORE (index.css ~line 397):
     .hover-lift-premium:hover { transform: ...; box-shadow: ...; }

   AFTER:
     .hover-lift-premium:hover { transform: translateY(-4px) scale(1.005); }
     [data-visual-style="premium"] .hover-lift-premium:hover { box-shadow: 0 20px 40px ...; }

   Same pattern for .hover-lift-subtle:hover (line 410) and
   .hover-glow-premium:hover (line 421).

   This is a ~6-line refactor of the base definitions, not new overrides. */

/* Shimmer/morph pseudo-elements → hidden */
[data-visual-style="classic"] .btn-premium::before {
  display: none;
}

[data-visual-style="classic"] .morph-border::before {
  display: none;
}

/* Focus → standard browser focus (global *:focus-visible still applies) */
[data-visual-style="classic"] .focus-premium:focus-visible {
  outline: 2px solid rgb(59 130 246);
  outline-offset: 2px;
  box-shadow: none;
}

/* Custom scrollbar → browser default */
[data-visual-style="classic"] .scroll-premium {
  scroll-behavior: auto;
  scrollbar-width: auto;
  scrollbar-color: auto;
}
[data-visual-style="classic"] .scroll-premium::-webkit-scrollbar {
  width: auto;
  height: auto;
}
[data-visual-style="classic"] .scroll-premium::-webkit-scrollbar-thumb {
  background: initial;
  border-radius: initial;
}

/* Loading shimmer/skeleton → neutral flat placeholder.
   Use --muted (defined in both light and dark token blocks) for dark-safe color. */
[data-visual-style="classic"] .shimmer-loading {
  background: hsl(var(--muted));
  background-size: initial;
  animation: none;
}
[data-visual-style="classic"] .skeleton-premium {
  background: hsl(var(--muted));
  background-size: initial;
  animation: none;
}

/* Gradient text → solid text */
[data-visual-style="classic"] .text-gradient-premium {
  background: none;
  -webkit-background-clip: initial;
  background-clip: initial;
  -webkit-text-fill-color: initial;
  color: hsl(var(--foreground));
  animation: none;
}

/* Entrance/loop animations → instant */
[data-visual-style="classic"] .animate-fade-in-gentle,
[data-visual-style="classic"] .animate-stagger-fade-in {
  animation: none;
  opacity: 1;
  transform: none;
}

[data-visual-style="classic"] .animate-breathe,
[data-visual-style="classic"] .animate-pulse-gentle,
[data-visual-style="classic"] .animate-float-gentle,
[data-visual-style="classic"] .animate-magnetic-hover,
[data-visual-style="classic"] .animate-slide-up,
[data-visual-style="classic"] .pulse-premium {
  animation: none;
}

/* Magnetic hover applies its effect on :hover — neutralize that too */
[data-visual-style="classic"] .animate-magnetic-hover {
  transition: none;
}
[data-visual-style="classic"] .animate-magnetic-hover:hover {
  animation: none;
  transform: none;
}

/* Dark + classic: override .dark .glass-* back to standard card */
.dark[data-visual-style="classic"] .glass-premium {
  background: hsl(var(--card));
  backdrop-filter: none;
  border: 1px solid hsl(var(--border));
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
}

.dark[data-visual-style="classic"] .glass-tinted {
  background: hsl(var(--card));
  backdrop-filter: none;
  border: 1px solid hsl(var(--border));
}
```

### Step 3: Bootstrap attribute before React hydration (~5 lines)

**File:** `frontend/index.html` (the Vite app entry point — NOT `frontend/public/index.html` which is the legacy template)

Add an inline `<script>` in `<head>` (after the existing Google auth script) to set `data-visual-style` before React mounts. This prevents a flash where stored-classic users see premium effects before the React `useEffect` fires:

```html
<script>
  try {
    var s = localStorage.getItem('visualStyle');
    if (s === 'classic') document.documentElement.dataset.visualStyle = 'classic';
    else document.documentElement.dataset.visualStyle = 'premium';
  } catch(e) { document.documentElement.dataset.visualStyle = 'premium'; }
</script>
```

This mirrors the existing pattern where themes set root attributes before hydration to avoid FOUC (flash of unstyled content).

### Step 4: Button premium variant — no additional CSS needed

The `Button variant="premium"` CVA definition (`button.tsx:14-15`) includes inline Tailwind classes for the emerald gradient and white text. The `.btn-premium::before` override (Step 2) removes the shimmer effect. The gradient itself stays in classic mode — this is acceptable because:
- The emerald gradient is the button's identity, not a "premium effect"
- Removing it would require component-level gating for a single variant
- The shimmer sweep (the actual premium polish) IS removed

If full neutralization is desired later, a per-component `isPremium` check can be added to `button.tsx` as a follow-up.

### Step 5: Verify

1. `cd frontend && pnpm typecheck` — must pass
2. `cd frontend && pnpm build` — must succeed
3. Chrome verification:
   - **Premium mode**: App looks identical to current (no visual change)
   - **Classic mode**: Glass effects → standard cards, no hover lifts, no entrance animations, no shimmer buttons, no morph borders, no gradient text, standard scrollbars, standard focus rings
   - **Dark mode + Classic**: Same neutralization applies
   - **Dark mode + Premium**: Existing dark glass effects preserved
   - **Toggle back and forth**: Instant visual switch, no page reload needed
   - **Fresh browser (no localStorage)**: Defaults to premium
   - **Hard refresh**: No flash of wrong theme (bootstrap script fires before React)

---

## Files Changed

| File | Change | Lines |
|------|--------|-------|
| `frontend/packages/connectors/src/stores/uiStore.ts` | Flip default to "premium" | ~2 |
| `frontend/packages/ui/src/components/portfolio/overview/SettingsPanel.tsx` | Reset default to "premium" | ~1 |
| `frontend/packages/ui/src/index.css` | Classic theme overrides + refactor hover box-shadow to premium-gated | ~80 |
| `frontend/index.html` | Bootstrap `data-visual-style` before React hydration | ~5 |

**Total: ~88 lines across 4 files.**

---

## What This Does NOT Include

- **Adding new premium classes to un-styled views** — that's a follow-up polish pass
- **Chart polish** (gradient fills, branded tooltips) — separate batch
- **Dark mode color audit** — separate batch
- **Typography enhancements** — separate batch
- **Full neutralization of Button `variant="premium"` gradient** — see Step 4 rationale

---

## After This Plan

The theme infrastructure is complete. Follow-up polish batches can add premium classes to any component — they'll be automatically gated by the CSS overrides. Example follow-up batches:

1. **Overview polish**: Add glass/hover to OverviewMetricCard grid, SmartAlertsPanel, performance cards
2. **Holdings + Performance polish**: Table hover effects, header card glass, chart containers
3. **Scenario + Strategy polish**: Tab panels, builder cards, backtest summary
4. **StockLookup + Risk polish**: Research tabs, risk metric cards
5. **Chart polish**: Gradient area fills, branded tooltips, custom legends
6. **Dark mode audit**: Fix hardcoded colors, verify every view

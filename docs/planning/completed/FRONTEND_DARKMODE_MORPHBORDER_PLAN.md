# Frontend Phase 5 Polish: Dark Mode Audit + Morph Border Batch

## Context
Final Phase 5 Visual Polish batch. Previous batches applied glassTinted, hover-lift-subtle, stagger animations, chart-theme migration, and text-balance-optimal typography across all views. This batch audits premium classes for dark mode safety and extends `morph-border` animated gradient border to featured/hero elements.

Classic mode neutralization for `morph-border` is already handled globally: `[data-visual-style="classic"] .morph-border::before { display: none; }`.

## Dark Mode Audit

### Current state
- `theme: 'light' | 'dark'` in uiStore, synced via `App.tsx` (`.dark` class on `<html>`)
- No dark mode toggle exposed in SettingsPanel (light-only UI currently)
- Dark glass variants exist: `.dark .glass-premium/tinted` (dark bg, stronger shadows)
- Dark + classic combo handled: `.dark[data-visual-style="classic"] .glass-*`

### Premium class dark mode safety

| Class | Mechanism | Dark-safe? | Action |
|-------|-----------|------------|--------|
| `glass-premium` | Background rgba + shadow | ✅ | `.dark` variant already at index.css:690 |
| `glass-tinted` | Background rgba + border | ✅ | `.dark` variant already at index.css:701 |
| `bg-gradient-sophisticated` | HSL gradient (light neutrals) | ⚠️ Known gap | Light-mode-specific; see Known Remaining Gaps |
| `gradient-success` | HSL gradient (emerald) | ⚠️ Known gap | Light-mode-specific; see Known Remaining Gaps |
| `gradient-risk` | HSL gradient (amber) | ⚠️ Known gap | Light-mode-specific; see Known Remaining Gaps |
| `gradient-depth` | HSL gradient (blue) | ⚠️ Known gap | Light-mode-specific; see Known Remaining Gaps |
| `gradient-sophisticated` | RGB gradient (grays) | ⚠️ Known gap | Light-mode-specific; see Known Remaining Gaps |
| `hover-lift-premium` | Transform only | ✅ | No color dependency |
| `hover-lift-subtle` | Transform only | ✅ | No color dependency |
| `hover-glow-premium` | Box-shadow (emerald) | ✅ | Glow visible on dark bg |
| `hover-glow` | Box-shadow (subtle) | ✅ | Subtle shadow, functional on dark |
| `btn-premium` | Shimmer pseudo-element | ✅ | White shimmer visible on dark |
| `focus-premium` | Emerald outline + glow ring | ✅ | Emerald outline visible on dark bg |
| `scroll-premium` | Custom scrollbar gradient | ✅ | Gray gradient scrollbar, functional on dark |
| `shimmer-loading` | Gradient sweep animation | ⚠️ Known gap | Light gray gradient; see Known Remaining Gaps |
| `skeleton-premium` | Gradient animation | ⚠️ Known gap | Light gray gradient; see Known Remaining Gaps |
| `text-gradient-premium` | Emerald-to-blue gradient text | ✅ | Gradient colors visible on dark bg |
| `text-balance-optimal` | Text layout only | ✅ | No color dependency |
| `animate-stagger-fade-in` | Opacity + translateY | ✅ | No color dependency |
| `animate-breathe` | Scale + opacity | ✅ | No color dependency |
| `animate-magnetic-hover` | Transform | ✅ | No color dependency |
| `animate-fade-in-gentle` | Opacity + translateY | ✅ | No color dependency |
| `animate-pulse-gentle` | Opacity pulsing | ✅ | No color dependency |
| `animate-float-gentle` | TranslateY floating | ✅ | No color dependency |
| `animate-slide-up` | TranslateY slide | ✅ | No color dependency |
| `pulse-premium` | Scale breathing | ✅ | No color dependency |
| `morph-border` | Gradient pseudo-element | ⚠️ | Gradient at 10% opacity invisible on dark bg — **fix below** |
| Premium hover box-shadows | `rgba(0,0,0,*)` | ⚠️ | Black shadows invisible on dark bg — **fix below** |
| `space-organic` | Margin-top spacing | ✅ | Layout only, no color dependency |
| `container-claude` | Max-width + centering | ✅ | Layout only, no color dependency |
| `rounded-3xl`/`rounded-2xl` | Overflow + clip | ✅ | No color dependency |

### Changes

#### 1. Add dark mode `morph-border` gradient with higher opacity

**File:** `frontend/packages/ui/src/index.css`

After the existing `.dark .glass-tinted` block (line 706), add:

```css
.dark .morph-border::before {
  background: linear-gradient(
    135deg,
    rgba(16, 185, 129, 0.25),
    rgba(139, 92, 246, 0.25),
    rgba(59, 130, 246, 0.25),
    rgba(16, 185, 129, 0.25)
  );
}
```

This bumps opacity from 0.1 → 0.25 so the animated gradient border is visible on dark backgrounds.

#### 2. Add dark mode premium hover shadows

**File:** `frontend/packages/ui/src/index.css`

After the existing `[data-visual-style="premium"] .hover-glow-premium:hover` block (line 729), add:

```css
.dark[data-visual-style="premium"] .hover-lift-premium:hover {
  box-shadow:
    0 20px 40px rgba(0, 0, 0, 0.3),
    0 8px 16px rgba(0, 0, 0, 0.2),
    0 4px 8px rgba(0, 0, 0, 0.15);
}

.dark[data-visual-style="premium"] .hover-lift-subtle:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}
```

Stronger shadow opacity for dark backgrounds (0.08→0.3, 0.04→0.15).

## Morph Border Extension

### Current usage (3 sites)
- `ModernDashboardApp.tsx:402` — RiskAnalysis container wrapper (`glass-premium rounded-3xl morph-border hover-lift-premium`)
- `AccountConnections.tsx:394` — Account card (`morph-border`)
- `PerformanceHeaderCard.tsx:80` — Performance banner (`morph-border animate-magnetic-hover`)

### `morph-border` characteristics
- `border-radius: 24px` set in CSS components layer (index.css:564)
- Pseudo-element: gradient emerald→purple→blue at 10% opacity, 8s animation cycle
- Hidden by default (`opacity: 0`), visible on hover (`opacity: 1`)
- Classic mode: pseudo-element `display: none`

### New morph-border sites

#### 3. MarketplaceTab "Featured Strategy" hero card

**File:** `frontend/packages/ui/src/components/portfolio/strategy/MarketplaceTab.tsx`

**Line 27:** Add `morph-border rounded-3xl` to the Featured Strategy card:
```
<Card className="p-6 bg-gradient-to-br from-emerald-50 to-emerald-100/50 border-emerald-200/60">
```
→
```
<Card className="p-6 bg-gradient-to-br from-emerald-50 to-emerald-100/50 border-emerald-200/60 morph-border rounded-3xl">
```

This is the "Featured Strategy — Top performer this quarter" hero card. It's a natural fit: the only hero-level card in Strategy Builder, prominently positioned at the top of the Marketplace tab.

**Radius note:** `morph-border` sets `border-radius: 24px` in the CSS components layer, but Card's Tailwind `rounded-xl` (12px) is emitted in the utilities layer and would win. Adding `rounded-3xl` explicitly ensures the 24px radius that `morph-border`'s pseudo-element `border-radius: inherit` expects.

## Known Remaining Gaps (dark mode — out of scope for this polish pass)

These are pre-existing light-mode-only classes and patterns. They are **not broken by the Phase 5 premium additions** — they are pre-existing design decisions that would require a dedicated dark mode color palette pass:

- **Gradient backgrounds**: `bg-gradient-sophisticated`, `gradient-success`, `gradient-risk`, `gradient-depth`, `gradient-sophisticated` — all use light-mode HSL/RGB values. Used in ModernDashboardApp, PerformanceHeaderCard, RiskAnalysisTab, and other data-context surfaces.
- **Loading states**: `shimmer-loading`, `skeleton-premium` — use light gray gradient sweeps. Used in ModernDashboardApp loading states.
- **Hardcoded Tailwind colors**: `bg-white/70`, `bg-white`, `from-white`, `text-neutral-900`, `bg-red-50`, `bg-amber-50`, `bg-emerald-50`, etc. — pervasive across all views, not specific to premium classes.

A full dark mode implementation would require: dark variants for all gradient classes, dark-aware Tailwind color overrides via CSS custom properties, and chart theme dark variants. This is a separate feature effort, not a polish pass.

## Dropped
- No morph-border on ScenarioHeader — it's a `CardHeader` within a parent Card, not a standalone hero element. The gradient "Analysis Complete" section (line 65) only appears after running analysis and is a results summary, not a featured banner.
- No morph-border on standard content Cards (glassTinted data-display cards) — `morph-border` is reserved for hero/featured elements only, not every card.
- No morph-border on RiskAnalysis main Card — it's a data container, not a featured element.
- No morph-border on StockLookup root Card — not a hero/featured element in the same sense as the Featured Strategy card or PerformanceHeaderCard. StockLookup's root Card is a search container.
- No morph-border on HoldingsTableHeader — data table header, not a featured element.
- No dark mode toggle in SettingsPanel — separate feature, not polish.

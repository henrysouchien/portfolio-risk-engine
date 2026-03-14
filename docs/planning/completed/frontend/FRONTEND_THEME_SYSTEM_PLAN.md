# Frontend Theme System Plan

## Goal

Add a visual style toggle (`classic` vs `premium`) so Phase 5 polish changes can be applied globally but toggled off for comparison. The classic theme is the current look; premium activates glass effects, hover interactions, animated borders, entrance animations, and richer typography.

This is a Phase 5 prerequisite, not Phase 5 itself. Phase 5 will wire premium classes into each view using this infrastructure.

---

## Existing Infrastructure (already built)

| Asset | Location | Status |
|-------|----------|--------|
| `useUIStore` (Zustand) | `connectors/src/stores/uiStore.ts` | Has `theme: 'light' \| 'dark'` + `setTheme()`. Light/dark synced to `document.documentElement` class in `App.tsx:145-154`. |
| Premium CSS classes | `ui/src/index.css:336-693` | ~20 utility classes: `glass-premium`, `glass-tinted`, `hover-lift-premium`, `hover-glow-premium`, `btn-premium`, `morph-border`, `animate-stagger-fade-in`, `animate-fade-in-gentle`, etc. Already consumed in a few places (see Pre-existing Usages below). |
| Tailwind config | `frontend/tailwind.config.js` | `darkMode: ["class"]` already set. Keyframes/animations registered. |
| CSS custom properties | `ui/src/index.css:120-265` | Full HSL color system with light/dark overrides. |
| Settings panel | `ui/src/components/portfolio/overview/SettingsPanel.tsx` | Sheet with Switch toggles. Uses staged local `useState` — writes to localStorage only on "Save Changes" click. Has Cancel + Reset to Defaults. |
| View mode toggle | `ui/src/components/portfolio/overview/ViewControlsHeader.tsx` | `ViewMode` controlled component (props: value + onChange). |

---

## Design

### New state: `visualStyle`

Add `visualStyle: "classic" | "premium"` to `useUIStore`. This is orthogonal to `theme` (light/dark) -- both can combine:

| | Light | Dark |
|---|---|---|
| **Classic** | Current look | Current dark look |
| **Premium** | Glass/hover/animation | Glass/hover/animation (dark) |

### Root sync

`App.tsx` already syncs `theme` to `document.documentElement`. Add same pattern for `visualStyle`:

```tsx
const visualStyle = useUIStore((state) => state.visualStyle);
useEffect(() => {
  document.documentElement.dataset.visualStyle = visualStyle;
}, [visualStyle]);
```

This sets `data-visual-style="classic"` or `data-visual-style="premium"` on `<html>`.

### CSS scoping

Premium classes activate unconditionally today. We do NOT change that -- they still work standalone. The theme system works at the component level via conditional class application:

```tsx
// In components (Phase 5 work):
const { visualStyle } = useVisualStyle();
<Card className={cn("p-6", visualStyle === "premium" && "glass-premium hover-lift-subtle")} />
```

A thin hook `useVisualStyle()` returns just the visual style from the store (avoids importing full store).

### Persistence

localStorage key `"visualStyle"`, read on store initialization. Default: `"classic"`.

Note: `uiStore` currently has NO localStorage persistence for `theme` (light/dark). We add persistence for `visualStyle` only. Use try/catch guarded access following the pattern in `useNotificationStorage.ts:6`:

```ts
function getStoredVisualStyle(): "classic" | "premium" {
  try {
    const stored = window.localStorage.getItem("visualStyle");
    if (stored === "premium") return "premium";
  } catch { /* SSR or blocked storage */ }
  return "classic";
}
```

### Toggle UI

Add a "Visual Style" section to the SettingsPanel (top of panel, before Display Preferences). Two-button toggle matching the ViewControlsHeader pattern:

```
Visual Style
[Classic] [Premium]
```

---

## Implementation Steps

### Step 1: Extend `useUIStore` (~20 lines)

**File:** `connectors/src/stores/uiStore.ts`

- Add `VisualStyle = "classic" | "premium"` type alias
- Add `visualStyle: VisualStyle` to `UIState` interface
- Add `setVisualStyle: (style: VisualStyle) => void` action
- Add `getStoredVisualStyle()` helper with try/catch guarded localStorage read
- Initialize `visualStyle` from `getStoredVisualStyle()` (default `"classic"`)
- `setVisualStyle` persists to localStorage (try/catch) + updates state
- Add `setVisualStyle` to `useUIActions` selector (line ~292)
- Export `useVisualStyle` selector hook

### Step 2: Sync to root element (~5 lines)

**File:** `ui/src/App.tsx`

- Add `useEffect` to sync `visualStyle` to `document.documentElement.dataset.visualStyle`
- Same pattern as existing theme sync (lines 145-154)

### Step 3: Add toggle to SettingsPanel (~30 lines)

**File:** `ui/src/components/portfolio/overview/SettingsPanel.tsx`

The SettingsPanel uses a staged-edit pattern: local `useState` for draft state, writes to localStorage only on "Save Changes", supports Cancel and Reset to Defaults. The visual style toggle must respect this contract.

- Import `useVisualStyle` from `@risk/connectors` (read current committed value)
- Import `useUIActions` from `@risk/connectors` (for `setVisualStyle` on save)
- Add local `useState` for `draftVisualStyle`
- **Re-sync on open**: Add `useEffect` that resets `draftVisualStyle` to the store value when `open` prop changes to `true`. This is needed because the SettingsPanel component stays mounted (rendered in PortfolioOverview with `open` prop controlling the Sheet). The `useState` initializer only runs once, so Cancel → reopen would show stale draft without this sync.
- Add "Visual Style" section at top of panel (before Display Preferences), with two-button toggle (Classic / Premium) that updates `draftVisualStyle`
- On "Save Changes" click: call `setVisualStyle(draftVisualStyle)` alongside existing localStorage write
- On "Reset to Defaults": set `draftVisualStyle` to `"classic"` alongside existing state resets
- On "Cancel": sheet closes, stale draft remains in memory but gets re-synced on next open via the `useEffect`

### Step 4: Re-export from connectors index

**File:** `connectors/src/index.ts`

- Export `useVisualStyle` from stores

---

## Pre-existing Premium Class Usages

Premium CSS classes are already consumed in a few places. These will NOT be gated by this plan — they remain unconditional. Phase 5 will audit and gate all usages.

Known sites (non-exhaustive):
- `ModernDashboardApp.tsx` — glass/scroll effects on main layout
- `PerformanceHeaderCard.tsx` — premium styling on header card
- `ChatCore.tsx` — glass effects on chat interface

**Impact**: When `visualStyle === "classic"`, these sites still show premium effects. This is acceptable for the infra-only plan — Phase 5 will gate them. The toggle is still useful because Phase 5 changes (the bulk of the work) will be gated from the start.

---

## What this does NOT include

- **Phase 5 component changes** -- wiring `visualStyle === "premium" && "glass-premium"` into every view is Phase 5 work, not this plan
- **CSS variable overrides per visual style** -- can be added later if needed (e.g., different border-radius, shadow intensity)
- **Per-view style preferences** -- just one global toggle for now
- **Dark mode toggle in Settings** -- already exists via `setTheme`, could be surfaced later

---

## Files Changed

| File | Change | Lines |
|------|--------|-------|
| `connectors/src/stores/uiStore.ts` | Add `visualStyle` state + action + selector + `useUIActions` update | ~20 |
| `connectors/src/index.ts` | Re-export `useVisualStyle` | ~1 |
| `ui/src/App.tsx` | Sync `visualStyle` to `data-visual-style` | ~5 |
| `ui/src/components/portfolio/overview/SettingsPanel.tsx` | Add staged toggle UI + save/reset/cancel integration | ~30 |

**Total: ~56 lines across 4 files. No new files needed.**

---

## Testing

- Toggle works: click Premium in Settings, click Save, refresh page, still Premium (localStorage)
- Cancel discards unsaved toggle change
- `document.documentElement.dataset.visualStyle` updates in DevTools
- Reset to Defaults in Settings reverts to Classic
- Light/dark theme still works independently
- Pre-existing premium class usages (ModernDashboardApp, etc.) are unaffected by toggle (expected — Phase 5 will gate them)

---

## After This Plan

Phase 5 work becomes: for each view, find Cards/panels/buttons/grids and add conditional premium classes gated on `visualStyle === "premium"`. Example:

```tsx
const { visualStyle } = useVisualStyle();
const isPremium = visualStyle === "premium";

<Card className={cn("p-6 border-neutral-200/60", isPremium && "glass-premium hover-lift-subtle")} />
<Button className={cn("bg-emerald-600", isPremium && "btn-premium")} />
<div className={cn("grid grid-cols-3 gap-4", isPremium && "animate-stagger-fade-in")} />
```

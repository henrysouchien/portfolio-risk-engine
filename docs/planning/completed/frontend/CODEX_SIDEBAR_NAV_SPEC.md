# Codex Spec: Sidebar Navigation for ModernDashboardApp (T3 #28)

## Context

The Analytics dropdown hides 5 major views behind a single menu click — the app looks like it has 3 pages when it has 8. We want to adopt the same sidebar pattern already proven in AnalystApp (`/analyst`) for the main dashboard, giving every view a visible, always-accessible icon button.

AnalystApp stays untouched. The flat-nav spec (`CODEX_FLATTEN_NAV_SPEC.md`) is kept as a separate option.

## Reference: AnalystApp Sidebar Pattern

`frontend/packages/ui/src/components/apps/AnalystApp.tsx`:
- `AnalystView` type (line 15): typed union `'chat' | 'holdings' | 'connections'`
- `SIDEBAR_ITEMS` array (lines 24–28): `{ id: AnalystView, label, shortcut, icon }`
- `AnalystSidebar` component (lines 35–71):
  - `<aside className="w-16 border-r border-neutral-200/70 bg-white/90 backdrop-blur-sm flex flex-col items-center py-4">`
  - `Button` with `variant="ghost"` + `size="icon"`, `h-11 w-11 rounded-xl`
  - Active: `bg-emerald-100 text-emerald-700 hover:bg-emerald-200`
  - Inactive: `text-neutral-500 hover:text-neutral-900 hover:bg-neutral-100`
  - Bottom section: `mt-auto` with "Full Dashboard" link
  - Props typed with `AnalystView`, not `string`
- Keyboard shortcuts via global `keydown` listener (lines 97–124)

## Files

| File | Action |
|------|--------|
| `frontend/packages/ui/src/components/dashboard/AppSidebar.tsx` | **Create** — sidebar component |
| `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx` | **Edit** — layout + header + imports |
| `frontend/packages/connectors/src/index.ts` | **Edit** — add `ViewId` type re-export (line 39) |
| `frontend/packages/ui/src/components/apps/AnalystApp.tsx` | No changes |
| `frontend/packages/ui/src/components/dashboard/NavBar.tsx` | No changes (kept for flat-nav option) |

---

## Step 1: Create AppSidebar.tsx

New file at `frontend/packages/ui/src/components/dashboard/AppSidebar.tsx`.

Based on AnalystApp's sidebar (lines 35–71) but extended with:
- All 8 views organized into 3 groups with horizontal separators
- Bottom section for AI + Settings (replaces AnalystApp's "Full Dashboard" link)

### Data structure (reuses NavBar grouping concept):
```
SIDEBAR_GROUPS:
  Portfolio: Overview (⌘1), Holdings (⌘2), Performance (⌘4)
  Analysis:  Factors (⌘3), Scenarios (⌘8)
  Tools:     Research (⌘6), Strategy (⌘5)

BOTTOM_ITEMS:
  AI Assistant (⌘7), Settings (⌘,)
```

### Props (type-safe, matching AnalystApp pattern):
```tsx
import type { ViewId } from '@risk/connectors';

interface AppSidebarProps {
  activeView: ViewId;
  onNavigate: (view: ViewId) => void;
}
```

**Prerequisite**: `ViewId` is defined in `frontend/packages/connectors/src/stores/uiStore.ts` (line 80) but not currently re-exported from the `@risk/connectors` barrel. Add it to line 39 of `frontend/packages/connectors/src/index.ts`:

```tsx
// Before:
export { useUIStore, useUIActions, useActiveView, useVisualStyle } from './stores/uiStore';

// After:
export { useUIStore, useUIActions, useActiveView, useVisualStyle } from './stores/uiStore';
export type { ViewId } from './stores/uiStore';
```

`ViewId` is the union type:
`'score' | 'factors' | 'performance' | 'holdings' | 'research' | 'report' | 'strategies' | 'scenarios' | 'chat' | 'settings' | 'connections'`

This avoids the `string` → `ViewId` cast problem. All sidebar item IDs are `ViewId` literals, so TypeScript infers correctly.

### Styling (matching AnalystApp exactly):
- `<aside>` with `w-16 shrink-0 border-r border-neutral-200/70 bg-white/90 backdrop-blur-sm`
- `flex flex-col items-center py-4`
- Buttons: `h-11 w-11 rounded-xl` with `title` for hover tooltip (label + shortcut)
- Active: `bg-emerald-100 text-emerald-700 hover:bg-emerald-200`
- Inactive: `text-neutral-500 hover:text-neutral-900 hover:bg-neutral-100`
- Group separators: `<div className="my-2 h-px w-8 bg-neutral-200/60" />`
- Bottom section: `mt-auto` pushes AI + Settings to bottom

### AI button special treatment:
Same button style as others but with a small emerald ping indicator dot when not active (matching the breathing dot pattern on the current AI button).

---

## Step 2: Restructure ModernDashboardApp layout

**File:** `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx`

Change the root layout from vertical (header above content) to horizontal (sidebar beside content).

### Before (current, line 513):
```tsx
<div className="min-h-screen bg-gradient-sophisticated flex flex-col">
  <header className="sticky top-0 z-50 glass-premium border-b ...">
    {/* brand + nav buttons + dropdowns */}
  </header>
  <main className="scroll-premium flex-1 min-h-0">
    {/* content */}
  </main>
  {/* floating elements */}
</div>
```

### After:
```tsx
<div className="flex h-screen bg-gradient-sophisticated">
  <AppSidebar
    activeView={activeView}
    onNavigate={setActiveView}
  />
  <div className="flex flex-1 flex-col min-w-0">
    <header className="sticky top-0 z-50 glass-premium border-b ...">
      {/* brand + LiveClock + NotificationCenter — NO nav buttons */}
    </header>
    <main className="scroll-premium flex-1 min-h-0 overflow-y-auto">
      {/* content */}
    </main>
  </div>
  {/* floating elements — fixed position, unaffected */}
</div>
```

Because `AppSidebar.onNavigate` accepts `ViewId` (same type as `setActiveView`), no cast is needed — pass `setActiveView` directly.

Key layout changes:
- Root div: `flex flex-col min-h-screen` → `flex h-screen`
- `<AppSidebar />` as first child of root
- Content wrapped in `<div className="flex flex-1 flex-col min-w-0">` (min-w-0 prevents flex overflow)
- Main gets `overflow-y-auto` for independent content scrolling
- Header z-index stays at `z-50` (no change — sidebar is a sibling, not an overlay)
- Floating elements (ArtifactAwareAskAIButton, AIChat modal, ArtifactPanelConnected, CommandPalette, background orbs) all use `fixed` positioning — no changes needed

---

## Step 3: Slim the header

Remove all nav buttons and dropdowns from the header. The section to delete starts at line 560 (`{/* Core Primary Navigation - Most Important Views */}`) and goes through the closing `</DropdownMenu>` of the MoreHorizontal dropdown at line 835. This is ~276 lines.

**Keep in the header:**
- Brand section (logo, title, AI/Pro badges) — lines 518–548
- LiveClock — line 547
- NotificationCenter — lines 553–559

**Remove from the header (lines 560–835):**
- The `glass-tinted` pill container (line 561) with Overview + Holdings buttons (lines 563–598)
- The Analytics `<DropdownMenu>` (lines 601–740) with Factor, Performance, Scenarios, Strategy, Research items
- The AI Assistant `<Button>` (lines 743–765) with breathing indicator
- The closing `</div>` of the pill container (line 766)
- The MoreHorizontal `<DropdownMenu>` (lines 769–835) with Settings + Command Palette items

The `<div className="flex items-center space-x-4">` outer nav container (line 551) should be simplified to just contain NotificationCenter (or removed if NotificationCenter moves elsewhere in the header).

Remove `overflow-visible` from the header (line 515) — it was needed for dropdown menus, no longer needed.

---

## Step 4: Clean up imports

### 4a: lucide-react icons (lines 57–71)

**Before (13 icons):**
```tsx
import {
BarChart3,
Brain,
ChevronDown,
Eye,
Layers,
MessageSquare,
MoreHorizontal,
PieChart,
Search,
Settings as SettingsIcon,
Shield,
Sparkles,
TrendingUp,
} from 'lucide-react';
```

**After (5 icons):**
```tsx
import {
Brain,
Layers,
MessageSquare,
Sparkles,
TrendingUp,
} from 'lucide-react';
```

Removed icons (all only used in deleted nav section):
- `BarChart3` — Analytics dropdown trigger + Factor item
- `ChevronDown` — Analytics dropdown chevron
- `Eye` — Overview button
- `MoreHorizontal` — Secondary actions dropdown trigger
- `PieChart` — Holdings button
- `Search` — Research item + Command Palette item
- `Settings as SettingsIcon` — Settings dropdown item
- `Shield` — Scenarios item

Kept icons (used outside nav):
- `Brain` — loading screen + brand badge
- `Layers` — brand Pro badge
- `MessageSquare` — ArtifactAwareAskAIButton
- `Sparkles` — brand AI badge
- `TrendingUp` — loading screen + brand logo

### 4b: Remove DropdownMenu import (line 84)

Delete this entire line:
```tsx
import { DropdownMenu,DropdownMenuContent,DropdownMenuGroup,DropdownMenuItem,DropdownMenuLabel,DropdownMenuSeparator,DropdownMenuShortcut,DropdownMenuTrigger } from '../ui/dropdown-menu';
```

Other files using DropdownMenu (e.g., `PerformanceHeaderCard.tsx`) have their own imports.

### 4c: Add AppSidebar import

```tsx
import { AppSidebar } from '../dashboard/AppSidebar';
```

### 4d: Remove NavBar import (line 75)

Delete this line:
```tsx
import { NavBar } from '../dashboard/NavBar';
```

With the sidebar approach, `NavBar` is unused. The file `NavBar.tsx` itself is preserved for the flat-nav option — only the import in ModernDashboardApp is removed.

### 4e: Keep existing imports

- `Badge` — KEEP (brand section badges)
- `Button` — KEEP (loading screen, no-portfolio state)
- `Card`, `CardContent` — KEEP (no-portfolio state)

---

## Verification

```bash
cd frontend && npx tsc --noEmit
```

Should produce zero TypeScript errors.

Visual checks at localhost:3000:
- Sidebar visible on left with all 8 view icons grouped by thin horizontal separators
- AI + Settings icons at bottom of sidebar
- Header is slim (brand + clock + notifications only, no nav buttons)
- Click each sidebar icon to verify view switching
- Keyboard shortcuts still work (⌘1–8, ⌘K, ⌘J, ⌘,)
- Content scrolls independently of sidebar
- AI chat modal, artifact panel, command palette all still functional
- Visit `/analyst` — AnalystApp unchanged with its own 3-item sidebar

## Summary

| What | Action |
|------|--------|
| `AppSidebar.tsx` | New file (~80 lines) |
| Nav JSX in header | Delete ~276 lines |
| Layout wrapper | Change root flex direction + add sidebar |
| Icon imports | Remove 8, keep 5 |
| DropdownMenu import | Delete 1 line |
| **Net ModernDashboardApp** | **~270 lines removed** |

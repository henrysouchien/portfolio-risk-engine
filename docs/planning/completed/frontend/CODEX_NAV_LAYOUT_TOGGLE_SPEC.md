# Codex Spec: Nav Layout Toggle — Sidebar + Header (T3 #28)

## Context

The Analytics dropdown hides 5 major views behind a single menu click — the app looks like it has 3 pages when it has 8. We have two competing nav approaches (sidebar vs flat header). Rather than committing to one, we'll build both and let the user toggle between them via a `navLayout` setting, following the same pattern as the existing `visualStyle: 'classic' | 'premium'` toggle.

**Default**: `'sidebar'` (preferred approach). Both underlying specs already Codex-reviewed and passed (`CODEX_SIDEBAR_NAV_SPEC.md`, `CODEX_FLATTEN_NAV_SPEC.md`).

### Review notes (2026-03-12)

1. **NavBar.tsx is orphaned.** It is imported on line 75 of ModernDashboardApp but never rendered — the current nav is 276 lines of inline JSX. The header layout branch relies on NavBar working correctly. Its `onNavigate` prop accepts `string`, not `ViewId`, hence the cast in Step 5d. Verify NavBar renders correctly before shipping the header branch.
2. **Extract `<BrandHeader>`.** Step 5d duplicates brand/LiveClock/NotificationCenter JSX across both layout branches. Extract a shared inline component or fragment to prevent the two copies from drifting.
3. **AI ping dot → static dot.** The `animate-ping` on the AI button runs continuously whenever chat isn't active (~95% of session time). Replace with a static emerald dot, or make the ping event-driven (pulse on new AI message, then fade). Perpetual animation causes banner blindness.
4. **Dark mode caveat.** The sidebar hardcodes `bg-white/90`, `text-neutral-500`, etc. Same as AnalystSidebar. Not a blocker, but both sidebars will need CSS variable treatment if dark mode ships.
5. **Consider dropping header layout entirely.** Sidebar is clearly the better UX. Header layout exists mainly because NavBar.tsx was already written. Shipping one layout means no toggle, no conditional render, no SettingsPanel section — ~80 fewer lines and one layout to maintain. If we keep it, it should be a low-priority fallback, not an equal peer.

## Files

| File | Action |
|------|--------|
| `frontend/packages/connectors/src/stores/uiStore.ts` | **Edit** — add `NavLayout` type, state, action, selector |
| `frontend/packages/connectors/src/index.ts` | **Edit** — export `ViewId` type + `useNavLayout` |
| `frontend/packages/ui/src/App.tsx` | **Edit** — DOM sync `data-nav-layout` |
| `frontend/packages/ui/src/components/dashboard/AppSidebar.tsx` | **Create** — sidebar nav component |
| `frontend/packages/ui/src/components/dashboard/NavBar.tsx` | **Audit** — orphaned (imported but never rendered); verify props/behavior before header branch relies on it |
| `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx` | **Edit** — delete inline nav, extract `BrandHeader`, conditional layout |
| `frontend/packages/ui/src/components/portfolio/overview/SettingsPanel.tsx` | **Edit** — add navLayout toggle |
| `frontend/packages/ui/src/components/apps/AnalystApp.tsx` | No changes |

---

## Step 1: Add `navLayout` to uiStore

**File**: `frontend/packages/connectors/src/stores/uiStore.ts`

Mirror the `visualStyle` pattern exactly:

1. Add type after line 81 (next to `type VisualStyle = 'classic' | 'premium'`):
   ```ts
   export type NavLayout = 'sidebar' | 'header';
   ```

2. Add `getStoredNavLayout()` after line 93 (mirrors `getStoredVisualStyle()`):
   ```ts
   function getStoredNavLayout(): NavLayout {
     try {
       const stored = window.localStorage.getItem('navLayout');
       if (stored === 'sidebar') return 'sidebar';
       if (stored === 'header') return 'header';
     } catch {
       // Ignore SSR/storage access failures and fall back to sidebar.
     }
     return 'sidebar';
   }
   ```

3. Add to `UIState` interface (after `visualStyle: VisualStyle` at line 105):
   ```ts
   navLayout: NavLayout;
   ```
   And after `setVisualStyle` action (line 137):
   ```ts
   setNavLayout: (layout: NavLayout) => void;
   ```

4. Add initial state (after `visualStyle: getStoredVisualStyle()` at line 203):
   ```ts
   navLayout: getStoredNavLayout(),
   ```

5. Add action (after `setVisualStyle` block ending at line 219):
   ```ts
   setNavLayout: (navLayout: NavLayout) => {
     try {
       window.localStorage.setItem('navLayout', navLayout);
     } catch {
       // Ignore storage write failures and still update in-memory state.
     }
     set({ navLayout });
   },
   ```

6. Add `setNavLayout` to `useUIActions` selector (after `setVisualStyle` at line 327):
   ```ts
   setNavLayout: state.setNavLayout,
   ```

7. Add selector hook (after `useVisualStyle` at line 317):
   ```ts
   export const useNavLayout = () => useUIStore((state) => state.navLayout);
   ```

---

## Step 2: Export from connectors barrel

**File**: `frontend/packages/connectors/src/index.ts`

Update line 39 to add `useNavLayout`, and add type exports:

```ts
// Before:
export { useUIStore, useUIActions, useActiveView, useVisualStyle } from './stores/uiStore';

// After:
export { useUIStore, useUIActions, useActiveView, useVisualStyle, useNavLayout } from './stores/uiStore';
export type { ViewId, NavLayout } from './stores/uiStore';
```

`ViewId` is needed by AppSidebar for its typed props. `NavLayout` is needed by SettingsPanel for type-safe draft state.

---

## Step 3: DOM sync in App.tsx

**File**: `frontend/packages/ui/src/App.tsx`

Add after the existing `visualStyle` sync (line 166):

```ts
const navLayout = useUIStore((state) => state.navLayout);
useEffect(() => {
  document.documentElement.dataset.navLayout = navLayout;
}, [navLayout]);
```

This sets `<html data-nav-layout="sidebar">` or `<html data-nav-layout="header">` on the document root, following the identical pattern used by `data-visual-style` at lines 164-166.

---

## Step 4: Create AppSidebar.tsx

**New file**: `frontend/packages/ui/src/components/dashboard/AppSidebar.tsx` (~80 lines)

Based on AnalystApp's `AnalystSidebar` component (`AnalystApp.tsx` lines 35-71) but extended for all dashboard views.

### Props (typed with `ViewId`):
```tsx
import type { ViewId } from '@risk/connectors';

interface AppSidebarProps {
  activeView: ViewId;
  onNavigate: (view: ViewId) => void;
}
```

### Data structure:
```tsx
interface SidebarItemDef {
  id: ViewId;
  label: string;
  icon: FC<{ className?: string }>;
  shortcut: string;
  group: 'core' | 'analysis' | 'tools';
}

const SIDEBAR_ITEMS: SidebarItemDef[] = [
  { id: 'score',       label: 'Overview',    icon: Eye,        shortcut: '⌘1', group: 'core' },
  { id: 'holdings',    label: 'Holdings',    icon: PieChart,   shortcut: '⌘2', group: 'core' },
  { id: 'performance', label: 'Performance', icon: TrendingUp, shortcut: '⌘4', group: 'core' },
  { id: 'factors',     label: 'Factors',     icon: BarChart3,  shortcut: '⌘3', group: 'analysis' },
  { id: 'scenarios',   label: 'Scenarios',   icon: Shield,     shortcut: '⌘8', group: 'analysis' },
  { id: 'research',    label: 'Research',    icon: Search,     shortcut: '⌘6', group: 'tools' },
  { id: 'strategies',  label: 'Strategy',    icon: Layers,     shortcut: '⌘5', group: 'tools' },
];

const BOTTOM_ITEMS: Array<{ id: ViewId; label: string; icon: FC<{ className?: string }>; shortcut: string }> = [
  { id: 'chat',     label: 'AI Assistant', icon: Sparkles, shortcut: '⌘7' },
  { id: 'settings', label: 'Settings',     icon: Settings,  shortcut: '⌘,' },
];
```

### Styling (matching AnalystApp exactly):
- `<aside className="w-16 shrink-0 border-r border-neutral-200/70 bg-white/90 backdrop-blur-sm flex flex-col items-center py-4">`
- Buttons: `h-11 w-11 rounded-xl` with `title={label (shortcut)}`
- Active: `bg-emerald-100 text-emerald-700 hover:bg-emerald-200`
- Inactive: `text-neutral-500 hover:text-neutral-900 hover:bg-neutral-100`
- Group separators between groups: `<div className="my-2 h-px w-8 bg-neutral-200/60" />`
- Bottom section: `<div className="mt-auto flex flex-col items-center gap-2">` for AI + Settings

### AI button special treatment:
Same button style as others but with a static emerald indicator dot when not active (no `animate-ping` — perpetual animation causes banner blindness; use event-driven pulse only if we add unread-message state later):
```tsx
{activeView !== 'chat' && (
  <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-emerald-500" />
)}
```

Uses `Button` from `../ui/button` with `variant="ghost"` and `size="icon"`, matching AnalystApp (line 40-54).

---

## Step 5: Refactor ModernDashboardApp

**File**: `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx`

### 5a. Import changes

**Add**:
```tsx
import { useNavLayout } from '@risk/connectors';
import { AppSidebar } from '../dashboard/AppSidebar';
```
(NavBar import at line 75 stays — it's used in the header layout branch.)

**Remove** (only used in inline nav being deleted):
- lucide-react icons (lines 57-71): Remove `BarChart3, ChevronDown, Eye, MoreHorizontal, PieChart, Search, Settings as SettingsIcon, Shield`
- DropdownMenu import (line 84): Remove entire line

**Keep** icons used outside nav: `Brain` (lines 324, 525), `Layers` (line 537), `MessageSquare` (line 166), `Sparkles` (line 533), `TrendingUp` (lines 321, 349, 522)

After cleanup, lucide-react import becomes:
```tsx
import {
  Brain,
  Layers,
  MessageSquare,
  Sparkles,
  TrendingUp,
} from 'lucide-react';
```

### 5b. Read navLayout in component body

```ts
const navLayout = useNavLayout();
```

### 5c. Delete inline nav (lines 560–835)

Remove everything from line 560 (`{/* Core Primary Navigation - Most Important Views */}`) through line 835 (closing `</DropdownMenu>` of the MoreHorizontal dropdown). This is ~276 lines containing:
- The `glass-tinted` pill container (line 561) with Overview + Holdings buttons (563-598)
- The Analytics `<DropdownMenu>` (601-740) with Factor, Performance, Scenarios, Strategy, Research items
- The AI Assistant `<Button>` (743-765) with breathing indicator
- The MoreHorizontal `<DropdownMenu>` (769-835) with Settings + Command Palette items

### 5d. Extract shared BrandHeader

Before the conditional layout, define a shared fragment inside the component body to avoid duplicating brand/clock/notification JSX across both branches:

```tsx
const brandHeader = (
  <div className="flex items-center space-x-6">
    {/* Brand section — logo, title, AI/Pro badges (existing lines ~518-544) */}
    {/* ... exact brand JSX moved here ... */}
    <LiveClock isOnline={isOnline} />
  </div>
);

const notificationBlock = (
  <NotificationCenter
    notifications={notifications}
    onMarkAsRead={onMarkAsRead}
    onDismiss={onDismiss}
    onClearAll={onClearAll}
  />
);

const mainContent = (
  <main className="scroll-premium flex-1 min-h-0 overflow-y-auto" role="main" aria-label="Portfolio management interface">
    <div className="p-8 container-claude transition-all duration-500 h-full">
      <ChunkErrorBoundary>
        <Suspense fallback={<ViewTransitionSkeleton />}>
          {renderMainContent()}
        </Suspense>
      </ChunkErrorBoundary>
    </div>
  </main>
);
```

### 5e. Conditional layout rendering

The root `<div>` (around line 513) through `</main>` (around line 850) becomes conditional based on `navLayout`. Floating elements (ArtifactAwareAskAIButton, AIChat, ArtifactPanel, CommandPalette, background orbs) stay outside the conditional since they all use `fixed` positioning.

**Sidebar layout** (`navLayout === 'sidebar'`):
```tsx
<div className="flex h-screen bg-gradient-sophisticated">
  <AppSidebar activeView={activeView} onNavigate={setActiveView} />
  <div className="flex flex-1 flex-col min-w-0">
    <header className="sticky top-0 z-50 glass-premium border-b border-neutral-200/50 px-8 py-4">
      <div className="flex items-center justify-between container-claude">
        {brandHeader}
        {notificationBlock}
      </div>
    </header>
    {mainContent}
  </div>
</div>
```

**Header layout** (`navLayout === 'header'`):
```tsx
<div className="min-h-screen bg-gradient-sophisticated flex flex-col">
  <header className="sticky top-0 z-50 glass-premium border-b border-neutral-200/50 px-8 py-4 scroll-premium overflow-visible">
    <div className="flex items-center justify-between container-claude">
      {brandHeader}
      <div className="flex items-center space-x-4">
        {notificationBlock}
        <NavBar
          activeView={activeView}
          onNavigate={(view) => setActiveView(view as Parameters<typeof setActiveView>[0])}
          onOpenCommandPalette={() => setShowCommandPalette(true)}
        />
      </div>
    </div>
  </header>
  {mainContent}
</div>
```

Key differences between layouts:

| Aspect | Sidebar | Header |
|--------|---------|--------|
| Root | `flex h-screen` | `flex flex-col min-h-screen` |
| Nav | `<AppSidebar>` left of content | `<NavBar>` inside header |
| Header content | brand + clock + notifications | brand + clock + notifications + NavBar |
| Main overflow | `overflow-y-auto` (content scrolls in column) | inherited scroll |
| Flex overflow guard | `min-w-0` on content column | not needed |
| Header `overflow-visible` | removed (no dropdowns) | kept (NavBar may need it) |
| CommandPalette trigger | ⌘K keyboard shortcut only | NavBar search button + ⌘K |

NavBar `onNavigate` uses `view as Parameters<typeof setActiveView>[0]` cast because NavBar's props accept `string` (it was created before ViewId was exported). AppSidebar uses `ViewId` natively, so `setActiveView` passes directly.

**Shared via extracted variables** (single definition, zero duplication):
- `brandHeader` — logo, title, AI/Pro badges, LiveClock
- `notificationBlock` — NotificationCenter with all 4 handlers
- `mainContent` — main element wrapping `renderMainContent()` with Suspense/ErrorBoundary
- All floating elements stay outside the conditional entirely

**Header z-index stays z-50** in both layouts.

---

## Step 6: Add toggle in SettingsPanel

**File**: `frontend/packages/ui/src/components/portfolio/overview/SettingsPanel.tsx`

Follow the exact `visualStyle` draft-state pattern:

### 6a. Imports (lines 1 and 3)

Add `LayoutDashboard` to the lucide-react import at line 1 (current imports: `BarChart,BarChart3,Bell,Download,Eye,FileText,LineChart,Mail,Palette,PieChart,RefreshCw,RotateCcw,Save,Settings,Smartphone as SmartphoneIcon,Volume2`). Insert `LayoutDashboard` alphabetically before `LineChart`.

Update line 3:
```ts
// Before:
import { useUIActions, useVisualStyle } from "@risk/connectors"

// After:
import { useUIActions, useVisualStyle, useNavLayout } from "@risk/connectors"
```

### 6b. Add state (after line 21)

```ts
const navLayout = useNavLayout()
const { setNavLayout } = useUIActions()
const [draftNavLayout, setDraftNavLayout] = useState(navLayout)
```

### 6c. Sync on open (line 57)

Add inside the existing `useEffect`:
```ts
useEffect(() => {
  if (open) {
    setDraftVisualStyle(visualStyle)
    setDraftNavLayout(navLayout)   // ← add this line
  }
}, [open, visualStyle, navLayout])  // ← add navLayout to deps
```

### 6d. Add "Navigation Layout" section (after line 105, before the `<Separator />` at line 107)

```tsx
<div className="space-y-4">
  <div className="flex items-center space-x-2">
    <LayoutDashboard className="w-4 h-4 text-neutral-600" />
    <h3 className="text-base font-semibold text-neutral-900">Navigation Layout</h3>
  </div>
  <div className="space-y-3 pl-6">
    <p className="text-xs text-neutral-500">
      Choose between sidebar navigation or a flat header bar.
    </p>
    <div className="flex items-center space-x-2">
      <Button
        variant={draftNavLayout === "sidebar" ? "default" : "outline"}
        size="sm"
        onClick={() => setDraftNavLayout("sidebar")}
        className="text-xs"
      >
        Sidebar
      </Button>
      <Button
        variant={draftNavLayout === "header" ? "default" : "outline"}
        size="sm"
        onClick={() => setDraftNavLayout("header")}
        className="text-xs"
      >
        Header
      </Button>
    </div>
  </div>
</div>
```

### 6e. Save handler (line 573)

Add after `setVisualStyle(draftVisualStyle)`:
```ts
setNavLayout(draftNavLayout)
```

### 6f. Reset handler (line 523)

Add after `setDraftVisualStyle("premium")`:
```ts
setDraftNavLayout("sidebar")
```

---

## Verification

```bash
cd frontend && npx tsc --noEmit   # zero TypeScript errors
```

Visual checks at localhost:3000:
- **Default (sidebar)**: Sidebar on left with all 8 view icons grouped by separators, AI + Settings at bottom, slim header (brand + clock + notifications only)
- **Settings → switch to Header**: NavBar appears in header with all views as flat buttons, sidebar disappears, standard vertical layout
- **Toggle back to Sidebar**: Sidebar returns instantly
- **Persistence**: Refresh page — chosen layout persists via localStorage
- **Keyboard shortcuts**: ⌘1–8, ⌘K, ⌘J, ⌘, work in both layouts
- **Floating elements**: AI chat modal, artifact panel, command palette all work in both layouts
- **Content scrolling**: In sidebar mode, content scrolls independently within the main area
- **`/analyst`**: AnalystApp unchanged with its own 3-item sidebar

## Summary

| What | Action |
|------|--------|
| `uiStore.ts` | +NavLayout type, +getStoredNavLayout, +state, +action, +selector (~25 lines) |
| `connectors/index.ts` | +useNavLayout export, +ViewId/NavLayout type exports (2 lines) |
| `App.tsx` | +navLayout DOM sync (3 lines) |
| `AppSidebar.tsx` | New file (~80 lines) |
| `NavBar.tsx` | Audit: verify props/render; currently orphaned (imported but never rendered) |
| `ModernDashboardApp.tsx` | Delete ~276 lines inline nav, extract `brandHeader`/`notificationBlock`/`mainContent` variables, add conditional layout (~80 lines) |
| `SettingsPanel.tsx` | +navLayout toggle section (~30 lines) |
| **Net** | **~120 lines removed**, zero JSX duplication between layouts |

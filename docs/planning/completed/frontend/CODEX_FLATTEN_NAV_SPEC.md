# Codex Spec: Flatten Header Nav (T3 #28)

**Goal:** Replace the Analytics dropdown + MoreHorizontal dropdown in `ModernDashboardApp.tsx` with a flat NavBar component that shows all views as top-level buttons.

**Why:** The Analytics dropdown hides 5 major views behind a single menu click. The app looks like it has 3 pages when it has 8.

**NavBar component already exists:** `frontend/packages/ui/src/components/dashboard/NavBar.tsx` — already imported at line 75 of ModernDashboardApp. Do NOT modify NavBar.tsx.

---

## Step 1: Replace nav JSX section

**File:** `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx`

Delete everything from the comment `{/* Core Primary Navigation - Most Important Views */}` (line 514) through the closing `</DropdownMenu>` of the MoreHorizontal dropdown (line 789). This is approximately 276 lines that include:

1. The `<div className="flex items-center glass-tinted ...">` pill container with:
   - Overview `<Button>` (uses `Eye` icon)
   - Holdings `<Button>` (uses `PieChart` icon)
   - Analytics `<DropdownMenu>` containing Factor Analysis, Performance, Scenario Analysis, Strategy Builder, Stock Research items
   - AI Assistant `<Button>` with breathing indicator dot
   - The closing `</div>` of the pill container
2. The `{/* Secondary Actions Dropdown */}` `<DropdownMenu>` containing Settings and Command Palette items

Replace all of the above with exactly:

```tsx
              <NavBar
                activeView={activeView}
                onNavigate={(view) => setActiveView(view as Parameters<typeof setActiveView>[0])}
                onOpenCommandPalette={() => setShowCommandPalette(true)}
              />
```

Note: The cast `view as Parameters<typeof setActiveView>[0]` is needed because NavBar's `onNavigate` accepts `string` while `setActiveView` expects `ViewId`. This matches the existing pattern used elsewhere in the file (see lines ~825, ~832 for similar casts).

**What to preserve (do NOT touch):**
- The `<NotificationCenter>` component immediately before (lines 507–512) — it stays as a sibling
- The `</div>` closing the outer nav flex container (line 791) — it stays
- The `</div>` + `</header>` below that (lines 792–793) — they stay

The result is that inside the `<div className="flex items-center space-x-4">` container, there are now just two children: `<NotificationCenter ... />` and `<NavBar ... />`.

## Step 2: Clean up unused imports

Same file. Two import blocks need changes:

### 2a: lucide-react icons (lines 57–71)

**Before:**
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

**After:**
```tsx
import {
Brain,
Layers,
MessageSquare,
Sparkles,
TrendingUp,
} from 'lucide-react';
```

**Removed icons** (all only used in the deleted nav section):
| Icon | Was used in |
|------|-------------|
| `BarChart3` | Analytics dropdown trigger + Factor Analysis item |
| `ChevronDown` | Analytics dropdown trigger chevron |
| `Eye` | Overview button |
| `MoreHorizontal` | Secondary actions dropdown trigger |
| `PieChart` | Holdings button |
| `Search` | Stock Research item + Command Palette item |
| `Settings as SettingsIcon` | Settings dropdown item |
| `Shield` | Scenario Analysis item |

**Kept icons** (used elsewhere in the file):
| Icon | Used in |
|------|---------|
| `Brain` | Loading screen + brand badge |
| `Layers` | Brand "Pro" badge |
| `MessageSquare` | ArtifactAwareAskAIButton |
| `Sparkles` | Brand "AI" badge |
| `TrendingUp` | Loading screen + brand logo |

### 2b: Remove DropdownMenu import (line 84)

Delete this entire line:
```tsx
import { DropdownMenu,DropdownMenuContent,DropdownMenuGroup,DropdownMenuItem,DropdownMenuLabel,DropdownMenuSeparator,DropdownMenuShortcut,DropdownMenuTrigger } from '../ui/dropdown-menu';
```

These components are only used in the nav section being deleted. Other files that use DropdownMenu (e.g., `PerformanceHeaderCard.tsx`) have their own imports.

## Step 3: Verify no other imports need removal

- `Badge` — KEEP (brand section badges)
- `Button` — KEEP (loading screen, no-portfolio state)
- `Card`, `CardContent` — KEEP (no-portfolio state)

## Verification

```bash
cd frontend && npx tsc --noEmit
```

Should produce zero TypeScript errors.

## Summary

| What | Lines removed | Lines added |
|------|--------------|-------------|
| Nav JSX (buttons + dropdowns) | ~276 | 5 (NavBar call) |
| Icon imports | 8 icons | 0 |
| DropdownMenu import line | 1 | 0 |
| **Net** | **~280 lines removed** | |

1 file changed: `ModernDashboardApp.tsx`. NavBar.tsx is already complete and should not be modified.

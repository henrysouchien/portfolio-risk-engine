# C2: Wire Trading Desk into Navigation

**Status**: TODO
**Created**: 2026-03-24
**Reviewed**: Codex round 1 — FAIL (command palette missing), round 2 — FAIL (shortcut cosmetics + wording), all addressed
**Files**: `NavBar.tsx`, `AppSidebar.tsx`, `ModernDashboardApp.tsx`, `command-palette.tsx`

## Context

Trading Desk is a fully-implemented view (138KB, 4 cards: QuickTrade, Orders, Baskets, HedgeMonitor) that's unreachable from the UI. ViewId `'trading'` exists in `VALID_VIEW_IDS` and `NAVIGABLE_VIEW_IDS`, routing is wired in `ModernDashboardApp.tsx`, but there's no entry in the header nav or sidebar. Users can only access it via `#trading` hash.

Fix: add nav entries and keyboard shortcut. Always show the entry (Option A) — the existing capability gate in `ModernDashboardApp.tsx` (lines 329-338) already redirects to `'score'` if the portfolio doesn't support trading.

## Files to modify

1. `frontend/packages/ui/src/components/dashboard/NavBar.tsx`
2. `frontend/packages/ui/src/components/dashboard/AppSidebar.tsx`
3. `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx`
4. `frontend/packages/ui/src/components/ui/command-palette.tsx`

## Changes

### 1. NavBar.tsx — Add trading to NAV_ITEMS (line 40)

Add after the `research` entry, in the `'tools'` group. Use `ArrowLeftRight` icon from lucide-react (represents trading/exchange).

```tsx
// Add to imports:
ArrowLeftRight,

// Add to NAV_ITEMS array after research:
{ id: 'trading',    label: 'Trading',    icon: ArrowLeftRight, shortcut: '⌘9', group: 'tools' },
```

### 2. AppSidebar.tsx — Add trading to SIDEBAR_ITEMS (line 35)

Same pattern, after `research`, in the `'tools'` group.

```tsx
// Add to imports:
ArrowLeftRight,

// Add to SIDEBAR_ITEMS array after research:
{ id: 'trading', label: 'Trading', icon: ArrowLeftRight, shortcut: '⌘9', group: 'tools' },
```

### 3. ModernDashboardApp.tsx — Add ⌘9 keyboard shortcut (after line 430)

Add case `'9'` to the keyboard handler:

```tsx
case '9':
  setActiveView('trading');
  e.preventDefault();
  break;
```

### 4. command-palette.tsx — Fix stale commands and add Trading (lines 32-37)

The command palette is stale — only 4 entries with wrong IDs (`overview` instead of `score`, `analytics` instead of `risk`) and wrong shortcuts. Replace the entire `commands` array to match the actual nav + add Trading:

```tsx
const commands = [
  { id: "score",       label: "Portfolio Overview", shortcut: "⌘1" },
  { id: "holdings",    label: "Holdings",           shortcut: "⌘2" },
  { id: "risk",        label: "Risk Analysis",      shortcut: "⌘3" },
  { id: "performance", label: "Performance",        shortcut: "⌘4" },
  { id: "scenarios",   label: "Scenarios",          shortcut: "⌘5" },
  { id: "research",    label: "Research",           shortcut: "⌘6" },
  { id: "trading",     label: "Trading Desk",       shortcut: "⌘9" },
  { id: "chat",        label: "AI Assistant",        shortcut: "⌘7" },
  { id: "settings",    label: "Settings",           shortcut: "⌘," },
]
```

## What's preserved

- Existing capability gate (lines 329-338) — redirects non-trading portfolios to `'score'`
- Lazy-loaded `TradingContainer` (lines 110-112)
- Existing routing case statement (lines 593-600)
- Hash navigation (`#trading`)

## Verification

1. `cd frontend && npx tsc --noEmit` — no type errors
2. Open app — "Trading" appears in header nav between Research and AI
3. Open app — "Trading" appears in sidebar between Research and AI Assistant
4. Click Trading nav entry — navigates to Trading Desk view
5. Press ⌘9 — navigates to Trading Desk view
6. Switch to portfolio without trading support — Trading redirects to Overview (existing capability gate)

**Known pre-existing issue**: Scenarios shortcut labels show `⌘8` in NavBar/AppSidebar but the actual handler binds both `⌘5` and `⌘8`. Command palette uses `⌘5` (matching the primary handler binding). Not introduced by this change.
7. Frontend tests pass

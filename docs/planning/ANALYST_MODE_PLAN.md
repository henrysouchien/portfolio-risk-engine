# Analyst Mode — Chat-Focused UI Entry Point

**Date**: 2026-03-01
**Status**: Planning (R1+R2+R3 reviewed, fixes applied)

## Context

The current frontend is a full portfolio dashboard with 8+ views (risk analysis, performance charts, scenarios, etc.). We want a simplified "analyst mode" that's **chat-first** — the user talks to Claude (which has full portfolio-mcp tool access via the gateway proxy) and only needs a few essential views alongside chat. This maps to Phase 6 TODO item #6 ("Accessible entry point").

**Approach**: A new lightweight app shell within the same frontend — same Vite build, same packages (`@risk/chassis`, `@risk/connectors`), same auth, same backend. Not a separate app.

**Product model**: Core functionality (login, connect brokerage, chat with analyst-Claude) is self-service. Power-user features (custom workflows, personalized memory, specialized skills) are assisted setup — users contact us and we help configure their instance.

## Step 1: Add `'connections'` to `ViewId` union

**File**: `packages/connectors/src/stores/uiStore.ts`

One-line type change — add `'connections'` to the `ViewId` union. The full dashboard never sets this value so it's unaffected. Analyst mode uses the same `useActiveView()` / `setActiveView()` pattern as the dashboard.

## Step 2: Create `AnalystApp.tsx` (~150-200 lines)

**File**: `packages/ui/src/components/apps/AnalystApp.tsx`

A dramatically simplified version of `ModernDashboardApp.tsx` (which is 945 lines). Chat-first layout with a thin icon sidebar.

**Layout**: Claude.ai-style — thin icon sidebar on the left (w-16, 64px), content takes remaining width. Full viewport height with proper flex chain.

**Structure**:
```
<PortfolioInitializer>      ← reused from connectors
  <ChatProvider>             ← reused from ChatContext
    <div className="flex h-screen">
      <AnalystSidebar />     ← new, ~40 lines inline
      <main className="flex-1 min-h-0 min-w-0">
        {renderContent()}    ← switch on activeView from uiStore
      </main>
    </div>
  </ChatProvider>
</PortfolioInitializer>
```

**Mount normalization** (R1 fix #1, R3 fix #1): On mount, AnalystApp unconditionally sets `activeView` to `'chat'`. This ensures chat is always the default when entering analyst mode — we don't preserve prior view state across navigation.

```typescript
useEffect(() => {
  setActiveView('chat');
}, []); // mount only
```

**Three views** (using uiStore `activeView` via `useActiveView()` / `setActiveView()`):

| View | Component (reused) | Default |
|------|--------------------|---------|
| `'chat'` | `ChatInterface` | Yes |
| `'holdings'` | `HoldingsViewModernContainer` | |
| `'connections'` | `AccountConnectionsContainer` | |

**Height chain** (R1 fix #4, R2 fix #1, R3 fix #3): ChatInterface needs an unbroken `h-full` chain to fill the viewport. The outer div uses `h-screen` (not `min-h-screen`), main uses `flex-1 min-h-0 min-w-0` (`min-w-0` prevents wide tabular content like holdings from causing horizontal overflow). The overflow strategy is **per-view**: chat view wrapper uses `h-full overflow-hidden` (ChatInterface manages its own internal scroll), while holdings and connections views use `h-full overflow-y-auto` (they render normal document-flow content that needs vertical scrolling).

**Sidebar design**: Icon-only vertical strip with 3 buttons:
1. **Chat** (MessageSquare) — default, green highlight when active
2. **Holdings** (PieChart) — position monitor
3. **Accounts** (Link2) — Plaid/Schwab/IBKR connections

Bottom of sidebar: small link to "Full Dashboard" — use `<a href="/">` for full-page navigation (R2 fix #4: routing is `window.location.pathname`-based, not SPA pushState, so navigation between `/analyst` and `/` must be a full page load).

**Keyboard shortcuts** (simplified):
- `Cmd+1` → Chat
- `Cmd+2` → Holdings
- `Cmd+3` → Accounts

**What's explicitly skipped** (vs ModernDashboardApp):
- Complex header with brand, market status, live clock
- Analytics dropdown, notification center, command palette
- Floating "Ask AI" button + AIChat modal (chat IS the main view)
- All analysis containers (risk, performance, factors, scenarios, strategies, research)

**ChatInterface props**:
- `onViewChange`: Maps known views to `setActiveView()` (`'holdings'` → works directly). Unknown views (e.g., `'performance'`) → no-op. Note (R1 fix #5, R2 fix #2): In the current code, `onViewChange` is **not triggered in fullscreen chat context** — `ChatCore` only navigates when `chatContext === 'modal'`, and the prop is currently unused in `ChatCore`. Still wired up so that if tool-driven navigation is added later, it works without changes to AnalystApp.
- `currentView`: Pass `activeView` from `useActiveView()`
- `onChatTransition`: Pass `undefined` (no modal in analyst mode — chat is already the main view)

## Step 3: Add `/analyst` route in AppOrchestratorModern

**File**: `packages/ui/src/router/AppOrchestratorModern.tsx`

The app already uses `window.location.pathname` for routing (`/plaid/success`, `/snaptrade/success` at lines 67-74). Same pattern.

**Path normalization** (R1 fix #3, R3 fix #2): Normalize `currentPath` by stripping trailing slashes before comparison, so both `/analyst` and `/analyst/` work. Apply `normalizedPath` to **all** pathname comparisons (including existing `/plaid/success` and `/snaptrade/success` checks) for consistency:

```typescript
const normalizedPath = currentPath.replace(/\/+$/, '') || '/';
```

Insert after the `/snaptrade/success` check, before the auth state machine:

```typescript
if (normalizedPath === '/analyst') {
  if (!isInitialized || isLoading) {
    return <AuthTransition message="Initializing..." />;
  }
  if (isAuthenticated && user && !servicesReady) {
    return <AuthTransition message="Setting up analyst mode..." previousApp="landing" />;
  }
  if (isAuthenticated && user && servicesReady) {
    return <AnalystApp />;
  }
  return <LandingApp error={error} />;
}
```

This preserves the full auth gate — analyst mode requires the same authentication as the dashboard. It just renders `AnalystApp` instead of `ModernDashboardApp`.

**Note on auth-gate duplication** (R1 fix #6): The auth-gate pattern (isInitialized → isAuthenticated+servicesReady → LandingApp) is duplicated between the analyst block and the main dashboard block. This is acceptable for now — extracting a shared `renderWithAuthGate(component)` helper is a future cleanup if more routes are added.

**View reset on dashboard entry** (R1 fix #2): The `'connections'` ViewId is only used by analyst mode. To prevent it leaking into the dashboard if a user navigates from `/analyst` to `/`, the dashboard's `ModernDashboardApp` should normalize on mount — if `activeView === 'connections'`, reset to `'score'`. This is a one-line `useEffect` addition to `ModernDashboardApp.tsx`.

Add import at top: `import { AnalystApp } from '../components/apps/AnalystApp';`

**Export convention** (R2 fix #3): AnalystApp should use named export (`export const AnalystApp`) matching the existing pattern in `ModernDashboardApp.tsx`. No default export needed.

## What Gets Reused vs What's New

| Concern | Status |
|---------|--------|
| Auth flow (OAuth, tokens, `AuthProvider`) | 100% reused |
| Service DI (`SessionServicesProvider`) | 100% reused |
| Portfolio bootstrap (`PortfolioInitializer`) | 100% reused |
| Chat state (`ChatProvider`, `useSharedChat`) | 100% reused |
| Chat UI (`ChatInterface` + `ChatCore`) | 100% reused |
| Gateway proxy (`/api/gateway/chat`) | 100% reused |
| Holdings view (`HoldingsViewModernContainer`) | 100% reused |
| Account connections (`AccountConnectionsContainer`) | 100% reused |
| Theme (dark/light from uiStore) | 100% reused |
| App shell + navigation | **New** (~150-200 lines) |

**Estimated new code**: ~200 lines in one new file + ~20 lines modified in orchestrator + 1 line in uiStore + 1 line in ModernDashboardApp.

## Files Summary

### Create

| File | Purpose |
|------|---------|
| `packages/ui/src/components/apps/AnalystApp.tsx` | Analyst mode shell (sidebar + 3-view content) |

### Modify

| File | Change |
|------|--------|
| `packages/ui/src/router/AppOrchestratorModern.tsx` | Add `/analyst` path check + import + path normalization |
| `packages/connectors/src/stores/uiStore.ts` | Add `'connections'` to `ViewId` union |
| `packages/ui/src/components/apps/ModernDashboardApp.tsx` | Add mount guard: reset `'connections'` → `'score'` (1 line) |

## Key Source Files

- `packages/ui/src/components/apps/ModernDashboardApp.tsx` — Reference for PortfolioInitializer/ChatProvider wrapping pattern (945 lines)
- `packages/ui/src/components/layout/ChatInterface.tsx` — Props: `onViewChange?`, `currentView?`, `onChatTransition?`
- `packages/ui/src/components/chat/ChatContext.tsx` — `ChatProvider` wraps app for shared chat state
- `packages/ui/src/components/dashboard/views/modern/HoldingsViewModernContainer.tsx` — Positions container
- `packages/ui/src/components/settings/AccountConnectionsContainer.tsx` — Connections container
- `packages/connectors/src/providers/PortfolioInitializer.tsx` — Portfolio data bootstrap
- `packages/connectors/src/stores/uiStore.ts` — `ViewId` type (add `'connections'`)

## Follow-Up TODO (not part of this plan)

**Create a demo-ready analyst-Claude instance**: The web UI connects to the gateway which runs analyst-Claude. For personal use, the current analyst-Claude (with ticker memory, personal context) works fine. For demos/shipping, we need a separate instance that:
- Keeps all workflows, skills, and full MCP tool functionality
- Removes personal ticker memory and user-specific context
- Has a clean system prompt suitable for new users
- Connects to the same portfolio-mcp / fmp-mcp / ibkr-mcp backends

This is a gateway/prompt config task, not a frontend task.

**UI polish**:
- Dark mode support for the analyst sidebar (currently light/white only)
- Chat markdown rendering — raw `**bold**` showing instead of rendered bold (existing ChatInterface issue, not analyst-mode specific)
- Consider adding small text labels under sidebar icons for demo users unfamiliar with the iconography

## Verification

1. `cd frontend && pnpm dev` — starts dev server
2. Navigate to `http://localhost:3000/analyst` — should show login page
3. Log in — should render `AnalystApp` with chat as default view
4. Verify chat works (send message, streaming response, tool execution)
5. Click Holdings icon — positions load correctly
6. Click Accounts icon — connections/Plaid UI loads
7. Navigate to `http://localhost:3000/` — full dashboard still works unchanged
8. `pnpm build` — builds cleanly
9. `pnpm test` — 75 tests still pass

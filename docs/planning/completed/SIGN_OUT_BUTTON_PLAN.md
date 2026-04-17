# F19: Add Sign Out Button to Sidebar

## Context

The modern dashboard (`ModernDashboardApp` + `AppSidebar`) has no way to log out. The legacy `DashboardLayout` had a "Sign Out" button in its header, but it's not used by the modern app. Users are currently stuck — no sign-out affordance exists anywhere in the modern UI.

## Approach

Add a sign-out button to the sidebar footer, below the Settings nav item. Pass `onSignOut` as a callback prop from `ModernDashboardApp` (which already lives in the auth-aware layer) to keep `AppSidebar` as a presentational component.

**Why sidebar footer and not Settings view:** Sign out is a session action, not a setting. It should be visible from any view, not buried in a sub-page. Sidebar footer is where users expect it (matches Slack, Discord, Figma, Linear, etc.).

**Why prop callback vs. direct hook:** `AppSidebar` currently takes all actions as props (`onNavigateView`, `onNavigateScenarioTool`). Calling `useAuthFlow()` directly inside it would break this pattern. `ModernDashboardApp` already imports from `@risk/connectors`.

## Files to Modify

### 1. `frontend/packages/ui/src/components/dashboard/AppSidebar.tsx`

- Add `onSignOut` to `AppSidebarProps` interface
- Import `LogOut` from `lucide-react`
- Render a **separate button** below the existing `BOTTOM_ITEMS` Settings entries in the `mt-auto` section. Do NOT add sign-out to the `BOTTOM_ITEMS` array — that array is typed `id: ViewId` and wired to `onNavigateView()`. Sign-out is an action, not a navigation target.
- Follow the same dual-layout pattern (icon-only at `lg`, icon+label at `xl`)
- Style it as a muted action (same text color as other sidebar items, no special emphasis) — it's an available action, not a call-to-action. Use `hover:text-destructive` (existing theme token) for subtle danger hint on hover only.

### 2. `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx`

- Import `useAuthFlow` from `@risk/connectors`
- Extract `signOut` from the hook
- Pass `onSignOut={signOut}` to `<AppSidebar>`

### 3. `frontend/packages/ui/src/components/dashboard/__tests__/AppSidebar.test.tsx` (NEW)

- Add a test that renders `AppSidebar` with an `onSignOut` mock and verifies:
  - The "Sign Out" button renders
  - Clicking it calls the `onSignOut` callback

## Design Details

- **Icon:** `LogOut` from lucide-react
- **Label:** "Sign Out" (matches the legacy DashboardLayout wording)
- **Position:** Below Settings in sidebar footer, separated by a subtle top border or spacing
- **Collapsed sidebar (lg):** Icon only, with `aria-label="Sign Out"` and `title="Sign Out"`
- **Expanded sidebar (xl):** Icon + "Sign Out" label
- **Hover:** `hover:text-destructive` (existing theme token) to signal destructive action
- **No keyboard shortcut:** Sign out is intentional, not something you trigger accidentally with a hotkey

## Key Code References

- **`useAuthFlow` hook:** `frontend/packages/connectors/src/features/auth/hooks/useAuthFlow.ts` — exposes `signOut: () => Promise<void>`. Exported from `@risk/connectors`.
- **Session cleanup:** `frontend/packages/connectors/src/utils/sessionCleanup.ts` — `onLogout()` clears portfolio store, UI notifications, adapter cache, React Query client, and auth state. Called by `useAuthFlow().signOut` internally.
- **Legacy sign-out button:** `frontend/packages/ui/src/components/layouts/DashboardLayout.tsx:39-45` — reference for wording ("Sign Out") and `data-testid="signout-button"`.
- **Sidebar bottom items pattern:** `AppSidebar.tsx:146-148` — `BOTTOM_ITEMS` array and dual-layout rendering at lines 217-255.

## Scope Note

The sidebar is `hidden` below `lg` breakpoint — there is no mobile nav surface in the modern UI today. This plan adds sign-out to the desktop sidebar only, matching the existing navigation pattern. A mobile nav/hamburger menu is a separate feature (not in scope for F19).

## Verification

1. `cd frontend && npm run typecheck` — no type errors
2. `cd frontend && npm run test` — existing + new tests pass
3. Visual check in browser:
   - Sign Out appears below Settings in sidebar
   - Icon-only on collapsed sidebar, icon+label on expanded
   - Clicking it signs out and returns to landing page
   - Hover shows subtle destructive tint

# Consolidate Floating Toolbar & Duplicated Controls

## Context

The Overview page has a floating pill toolbar (`ViewControlsHeader`) with AI Insights toggle, Refresh button, and Settings gear. These duplicate controls that already exist in the header bar (refresh), sidebar (AI, settings), and FAB (Ask AI). The result is 2 refresh buttons, 2 settings gears that open different things, and 3 AI entry points. This plan removes the floating pill and migrates its unique functionality elsewhere.

**Current duplication map:**

| Control | Header bar | Floating pill | Sidebar | FAB |
|---------|-----------|---------------|---------|-----|
| Refresh | Global refresh (invalidates all query caches) | Holdings-only refresh (`IntentRegistry.triggerIntent('refresh-holdings')`) | — | — |
| Settings | — | Opens `SettingsPanel` side sheet (appearance, display, charts — mostly dead code) | Opens full Settings page (risk limits, accounts, CSV import) | — |
| AI | — | "AI Insights" toggle (metric card overlays) | Sparkles icon → full-page chat view | "Ask AI" button → chat modal |

**Key finding:** The `SettingsPanel` side sheet stores display/refresh/alert/chart/export settings to `localStorage` under `portfolioSettings`, but this key is **never read back** on mount and **never consumed** by any other component. Only the 3 Zustand-backed settings (theme, visualStyle, navLayout) actually take effect.

## Steps

### Step 1: Enhance global refresh to include holdings intent

**File:** `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx`

- In `handleGlobalRefresh`, call `IntentRegistry.triggerIntent('refresh-holdings')` before `queryClient.invalidateQueries()`
- Import `IntentRegistry` from `@risk/connectors` (exported at `connectors/src/index.ts:60`)
- **Note:** `triggerIntent()` returns `{ success: false, error }` on failure (never throws), so use result-checking not try/catch:
  ```ts
  const result = await IntentRegistry.triggerIntent('refresh-holdings');
  // No need to check result — proceed with cache invalidation regardless
  await queryClient.invalidateQueries();
  ```
- This makes the single header refresh button do everything the ViewControlsHeader refresh did plus cache invalidation

### Step 2: Replace ViewControlsHeader with inline AI Insights toggle

**File:** `frontend/packages/ui/src/components/portfolio/PortfolioOverview.tsx`

- Remove imports: `ViewControlsHeader`, `SettingsPanel` from `./overview`
- Remove `TooltipProvider` import and wrapper (only existed for the pill's tooltip)
- Remove `settingsPanelOpen` state
- Remove `<ViewControlsHeader>` render block and `<SettingsPanel>` render block
- Add `Brain` import from `lucide-react` and `Button` from `../ui/button`
- Add inline AI Insights toggle right-aligned above the metrics grid:
  ```tsx
  {onToggleAIInsights && (
    <div className="flex justify-end">
      <Button variant="ghost" size="sm" onClick={onToggleAIInsights}
        aria-pressed={showAIInsights}
        className={`text-xs rounded-xl ${showAIInsights ? "bg-blue-100 text-blue-700" : ""}`}>
        <Brain className="!w-4 !h-4 mr-1" /> AI Insights
      </Button>
    </div>
  )}
  ```

**File:** `frontend/packages/ui/src/components/dashboard/views/modern/PortfolioOverviewContainer.tsx`

- The container's `handleRefresh` (line 140) and `manualRefreshRef` / toast effect (lines 74, 112-128) become dead code since `onRefresh` is no longer consumed by the pill. **Remove:**
  - `handleRefresh` function (lines 140-153)
  - `manualRefreshRef` (line 74)
  - Toast effect for manual refresh tracking (lines 112-128)
  - Stop passing `onRefresh` and `loading` props to `<PortfolioOverview>` (lines 225-226)

**File:** `frontend/packages/ui/src/components/portfolio/overview/types.ts`

- Remove `onRefresh` and `loading` from `PortfolioOverviewProps` interface (lines ~103, 105-106)

### Step 3: Create PreferencesCard on Settings page

**New file:** `frontend/packages/ui/src/components/settings/PreferencesCard.tsx`

- **Default export** (to match `React.lazy` pattern used by other settings cards)
- Migrate only the 3 working Zustand-backed appearance controls from SettingsPanel: Visual Style (classic/premium), Color Mode (light/dark), Navigation Layout (sidebar/header)
- Use the same ToggleGroup UI pattern from SettingsPanel
- Apply changes immediately via `setTheme()` / `setVisualStyle()` / `setNavLayout()` — no draft state needed
- Drop the dead settings (display, refresh, alerts, charts, export) — they were never read back or consumed anywhere (`portfolioSettings` localStorage key only written, never read)
- Wrap in a `Card` with heading "Appearance & Preferences"

**File:** `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx`

- Add lazy import: `const PreferencesCard = React.lazy(() => import('../settings/PreferencesCard'))` (alongside existing lazy imports at ~lines 99-111)
- Add `<PreferencesCard />` to the `settings` case in `renderMainContent()` (line ~503), between RiskSettingsContainer and AccountConnectionsContainer
- Already covered by the shared `<Suspense>` boundary at line ~578

### Step 4: Delete obsolete files & clean up exports

- **Delete:** `frontend/packages/ui/src/components/portfolio/overview/ViewControlsHeader.tsx`
- **Delete:** `frontend/packages/ui/src/components/portfolio/overview/SettingsPanel.tsx`
- **Update:** `frontend/packages/ui/src/components/portfolio/overview/index.ts` — remove exports for both deleted files

## Files Modified

| File | Action |
|------|--------|
| `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx` | Enhance refresh, add PreferencesCard lazy import + settings view |
| `frontend/packages/ui/src/components/portfolio/PortfolioOverview.tsx` | Remove pill/settings, add inline AI toggle, drop TooltipProvider |
| `frontend/packages/ui/src/components/dashboard/views/modern/PortfolioOverviewContainer.tsx` | Remove dead handleRefresh, manualRefreshRef, toast effect, props |
| `frontend/packages/ui/src/components/portfolio/overview/types.ts` | Remove `onRefresh`, `loading` from PortfolioOverviewProps |
| `frontend/packages/ui/src/components/settings/PreferencesCard.tsx` | **NEW** — appearance settings card (default export) |
| `frontend/packages/ui/src/components/portfolio/overview/ViewControlsHeader.tsx` | **DELETE** |
| `frontend/packages/ui/src/components/portfolio/overview/SettingsPanel.tsx` | **DELETE** |
| `frontend/packages/ui/src/components/portfolio/overview/index.ts` | Remove deleted exports |

## Verification

1. Load Overview page — confirm floating pill is gone, inline AI Insights toggle appears above metric cards
2. Toggle AI Insights — metric cards should show/hide AI analysis sections
3. Click header refresh icon — should trigger both holdings intent refresh AND query cache invalidation
4. Navigate to Settings page — confirm new Appearance card appears with theme/style/layout toggles
5. Toggle visual style, color mode, nav layout from Settings page — changes apply immediately
6. Confirm "Ask AI" FAB still works, sidebar AI/Settings icons still navigate correctly
7. Run frontend tests: `cd frontend && npx vitest run`

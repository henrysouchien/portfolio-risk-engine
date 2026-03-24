# Settings Page Tabbed Organization

## Context

The Settings page has grown to 6 cards in a single vertical scroll: RiskSettings, Preferences, Account Connections, Data Providers, AI Providers, CSV Import. No visual hierarchy or grouping — users scroll through everything to find what they need. As we add more settings, this gets worse.

Organize into 3 tabbed sections using the existing `Tabs` component pattern (already proven in Performance view and Risk Analysis view).

## Design

**Three tabs:**

| Tab | Label | Icon | Cards |
|-----|-------|------|-------|
| Preferences | Preferences | `Palette` | PreferencesCard |
| Integrations | Integrations | `Plug` | AccountConnectionsContainer, DataProvidersContainer, AIProvidersContainer |
| Portfolio | Portfolio | `TrendingUp` | RiskSettingsContainer, CsvImportCard |

**Tab bar** uses the same `glass-tinted grid rounded-2xl border` pattern as Performance view tabs (line 146 of PerformanceView.tsx). 3-column grid.

## Steps

### Step 1: Create SettingsView component
**New file:** `frontend/packages/ui/src/components/settings/SettingsView.tsx`

This replaces the 6 individual card mounts in ModernDashboardApp. It's a thin orchestrator with tab state:

```tsx
import { useState } from 'react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../ui/tabs'
import { Palette, Plug, TrendingUp } from 'lucide-react'

type SettingsTab = 'preferences' | 'integrations' | 'portfolio'

export default function SettingsView() {
  const [activeTab, setActiveTab] = useState<SettingsTab>('integrations')

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold">Settings</h1>
        <p className="text-sm text-muted-foreground">Manage your preferences, connections, and portfolio configuration</p>
      </div>

      <Tabs value={activeTab} onValueChange={v => setActiveTab(v as SettingsTab)}>
        <TabsList className="glass-tinted grid w-full grid-cols-3 rounded-2xl border border-neutral-200/60 p-1">
          <TabsTrigger value="preferences" className="rounded-xl text-sm font-medium ...">
            <Palette className="mr-2 h-3 w-3" /> Preferences
          </TabsTrigger>
          <TabsTrigger value="integrations" className="rounded-xl text-sm font-medium ...">
            <Plug className="mr-2 h-3 w-3" /> Integrations
          </TabsTrigger>
          <TabsTrigger value="portfolio" className="rounded-xl text-sm font-medium ...">
            <TrendingUp className="mr-2 h-3 w-3" /> Portfolio
          </TabsTrigger>
        </TabsList>

        <TabsContent value="preferences" className="space-y-8">
          <PreferencesCard />
        </TabsContent>

        <TabsContent value="integrations" className="space-y-8">
          <AccountConnectionsContainer />
          <DataProvidersContainer />
          <AIProvidersContainer />
        </TabsContent>

        <TabsContent value="portfolio" className="space-y-8">
          <RiskSettingsContainer />
          <CsvImportCard />
        </TabsContent>
      </Tabs>
    </div>
  )
}
```

Default tab: `integrations` (most frequently used — connecting accounts and checking provider status).

### Step 2: Update ModernDashboardApp to use SettingsView
**File:** `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx`

Replace the 6 individual card mounts (lines ~536-568) with a single lazy-loaded `SettingsView`:

```tsx
const SettingsView = React.lazy(() => import('../settings/SettingsView'));
```

In the settings case, **preserve the existing outer layout styles** (`space-organic`, `animate-stagger-fade-in`). No per-card `hover-lift-premium` wrappers needed — cards have their own internal styling. Don't add `max-w-5xl mx-auto` (already constrained by the parent `container-claude`):

```tsx
case 'settings':
  return (
    <div className="space-organic animate-stagger-fade-in">
      <SettingsView />
    </div>
  )
```

Inside SettingsView, use `space-y-8` on each `TabsContent` for consistent spacing. Do NOT add per-card `hover-lift-premium mb-8` wrappers — the cards already have their own glassTinted/hover styling internally. Using `space-y-8` alone matches the visual rhythm without double-stacking margins.

### Step 3: Import cleanup in ModernDashboardApp
SettingsView imports its cards directly (they're behind the SettingsView lazy boundary — no nested lazy needed).

Remove these lazy imports from ModernDashboardApp since they move into SettingsView:
- `PreferencesCard` — settings-only
- `CsvImportCard` — settings-only
- `DataProvidersContainer` — settings-only
- `AIProvidersContainer` — settings-only

**Remove ALL 6 settings-related lazy imports from ModernDashboardApp** — none of them are used outside the settings case in that file. `AnalystApp` manages its own imports separately and is unaffected. The lazy imports to remove from ModernDashboardApp:
- `PreferencesCard`
- `CsvImportCard`
- `AccountConnectionsContainer`
- `DataProvidersContainer`
- `AIProvidersContainer`
- `RiskSettingsContainer` (verify — if only referenced in settings case, remove)

### Step 4: TabsTrigger styling
Copy the exact `TabsTrigger` className from `portfolio/PerformanceView.tsx` (line 154) or `portfolio/RiskAnalysis.tsx` (line 283):
```
className="rounded-xl text-sm font-medium transition-all duration-300 data-[state=active]:bg-gradient-to-r data-[state=active]:from-neutral-900 data-[state=active]:to-neutral-800 data-[state=active]:text-white"
```

This gives the same dark-gradient active state as Performance and Risk views.

### Step 5: Add render test for SettingsView
**New file:** `frontend/packages/ui/src/components/settings/SettingsView.test.tsx`

**Mock all child cards/containers** — they pull hooks, query state, session services, and can't render in isolation. Use `vi.mock` to replace each with a simple stub:
```ts
vi.mock('./PreferencesCard', () => ({ default: () => <div data-testid="preferences-card" /> }))
vi.mock('./AccountConnectionsContainer', () => ({ default: () => <div data-testid="account-connections" /> }))
vi.mock('./DataProvidersContainer', () => ({ default: () => <div data-testid="data-providers" /> }))
vi.mock('./AIProvidersContainer', () => ({ default: () => <div data-testid="ai-providers" /> }))
vi.mock('./CsvImportCard', () => ({ default: () => <div data-testid="csv-import" /> }))
vi.mock('../dashboard/views/modern/RiskSettingsContainer', () => ({ default: () => <div data-testid="risk-settings" /> }))
```

Test cases:
- Default tab is "integrations" — account-connections, data-providers, ai-providers visible
- Click "Portfolio" tab — risk-settings, csv-import visible
- Click "Preferences" tab — preferences-card visible
- Inactive tab content not rendered (Radix Tabs default behavior)

## Files Modified
| File | Change |
|------|--------|
| `ui/src/components/settings/SettingsView.tsx` | **New**: tabbed orchestrator |
| `ui/src/components/settings/SettingsView.test.tsx` | **New**: render tests |
| `ui/src/components/apps/ModernDashboardApp.tsx` | Replace 6 card mounts with `<SettingsView />`, clean up lazy imports |

## Verification
1. `cd frontend && npx tsc --noEmit` — type check
2. `cd frontend && npx vitest run SettingsView` — render tests
3. Browser: Settings page shows 3 tabs (Preferences, Integrations, Portfolio)
4. Integrations tab shows Account Connections + Data Providers + AI Providers
5. Portfolio tab shows Risk Settings + CSV Import
6. Preferences tab shows theme/color/nav layout
7. Tab switching is instant (no loading spinners)
8. Default tab is Integrations
9. Cards have their own internal styling — no outer wrappers needed

# Split Factors and Research into Separate Views

## Context
Currently "Factors" (⌘3) and "Research" (⌘6) both land on the same `ResearchContainer`, which has a tab switcher between "Portfolio Risk" (factors + risk analysis) and "Stock Lookup". The `factors` nav item silently redirects to `research` via a `useEffect` in `ModernDashboardApp`. This is confusing — clicking "Factors" in the header doesn't highlight it, it highlights "Research" instead. Splitting them into two standalone views makes the navigation honest.

## Changes

### 1. Create `FactorsContainer.tsx`
**Path:** `frontend/packages/ui/src/components/dashboard/views/modern/FactorsContainer.tsx`

Extract the "Portfolio Risk" tab content from ResearchContainer:
- Two-column grid: `FactorRiskModelContainer` (left) + `RiskAnalysisModernContainer` (right)
- "Continue into scenarios" card at the bottom
- Reuse existing `SectionHeader`, `DashboardErrorBoundary`
- No tabs, no sub-view state

### 2. Simplify `ResearchContainer.tsx`
**Path:** `frontend/packages/ui/src/components/dashboard/views/modern/ResearchContainer.tsx`

- Remove tabs entirely — just render `StockLookupContainer` directly
- Keep the `navigationContext?.ticker` passthrough logic (for cross-view stock lookup navigation)
- Remove imports: `Tabs`, `TabsContent`, `TabsList`, `TabsTrigger`, `BarChart3`, `Shield`, `SectionHeader`, `FactorRiskModelContainer`, `RiskAnalysisModernContainer`, `Button`, `ChevronRight`
- Remove `ResearchSubView` type, `activeSubView` state, `handleSubViewChange`, `handleOpenScenarios`

### 3. Update `ModernDashboardApp.tsx`
**Path:** `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx`

- **Remove** the `factors → research` redirect `useEffect` (lines 225-229)
- **Add** lazy import: `const FactorsContainer = React.lazy(() => import('../dashboard/views/modern/FactorsContainer'))`
- **Add** `'factors'` case in `renderMainContent()` switch, rendering `<FactorsContainer />`

### 4. Fix alert navigation routing
**Path:** `frontend/packages/connectors/src/features/notifications/alertMappings.ts`

Lines 39-43 route risk alerts (`high_leverage`, `leveraged`, `futures_high_notional`, `sector_concentration`, `low_sector_diversification`) to `view: 'research'`. Change these to `view: 'factors'` since the risk analysis content now lives in the Factors view.

**Path:** `frontend/packages/ui/src/components/dashboard/cards/DashboardAlertsPanel.tsx`

Line 54 has a fallback for unmapped risk-derived alerts: `{ view: 'research' as const, label: 'View risk analysis' }`. Change to `{ view: 'factors' as const, label: 'View risk analysis' }`.

### 5. No changes needed
- `AppSidebar.tsx` — already has `{ id: 'factors', icon: BarChart3 }` and `{ id: 'research', icon: Search }`
- `NavBar.tsx` — already has both items defined
- Keyboard shortcuts — ⌘3 already maps to `'factors'`, ⌘6 to `'research'`
- Command palette — already out of sync with view IDs (uses generic labels), defer fix

## Verification
1. Build: `cd frontend && npx tsc --noEmit --project packages/ui/tsconfig.json` — no new errors
2. Visual: Click "Factors" in header → should highlight "Factors", show factor exposure + risk analysis
3. Visual: Click "Research" in header → should highlight "Research", show stock lookup
4. ⌘3 → Factors view, ⌘6 → Research view
5. Sidebar: BarChart3 icon → Factors, Search icon → Research

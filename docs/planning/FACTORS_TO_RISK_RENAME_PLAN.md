# Rename ViewId 'factors' → 'risk'

## Context
The nav labels already show "Risk" but the internal ViewId is still `'factors'`. With hash-based URLs just shipped (`#factors`), now is the ideal time to align before any bookmarks exist. URL becomes `#risk`, internal routing key becomes `'risk'`.

## Scope
Display labels are already correct — this is purely an internal ViewId rename with cascading updates to routing, keyboard shortcuts, hash sync, and tests.

## Files to Change

### 1. `frontend/packages/connectors/src/stores/uiStore.ts`
- **Line 80**: ViewId type union — change `'factors'` to `'risk'`
- **Line 112**: `VALID_VIEW_IDS` array — change `'factors'` to `'risk'`
- **`getStoredActiveView()`**: Add legacy handling — if hash segment is `'factors'`, treat as `'risk'`. If localStorage value is `'factors'`, treat as `'risk'` AND write back `'risk'` to localStorage (one-time migration).

```typescript
// In getStoredActiveView():
// After hash check, before NAVIGABLE_VIEW_IDS includes:
if (segment === 'factors') return 'risk' as ViewId;
// ...
// After localStorage read:
if (stored === 'factors') {
  try { window.localStorage.setItem('activeView', 'risk'); } catch {}
  return 'risk';
}
```

### 2. `frontend/packages/ui/src/components/dashboard/NavBar.tsx`
- **Line 38**: Nav item `id: 'factors'` → `id: 'risk'`

### 3. `frontend/packages/ui/src/components/dashboard/AppSidebar.tsx`
- **Line 33**: Sidebar item `id: 'factors'` → `id: 'risk'`

### 4. `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx`
- **Line ~329**: Keyboard handler `case '3': setActiveView('factors')` → `setActiveView('risk')`
- **Line ~484**: View switch `case 'factors':` → `case 'risk':`

### 5. `frontend/packages/connectors/src/navigation/hashSync.ts`
- `buildHash`/`parseHash` use ViewId dynamically — hash auto-becomes `#risk`
- Add `'factors'` as a legacy alias in `parseHash()`: if hash segment is `'factors'`, return `{ view: 'risk' }`
- Do NOT add `'factors'` to `NAVIGABLE_VIEW_IDS` — handle legacy only in `parseHash` and `getStoredActiveView`

### 6. Alert navigation — `alertMappings.ts` + `DashboardAlertsPanel.tsx`
- **`frontend/packages/connectors/src/features/notifications/alertMappings.ts` line ~31**: ViewId reference `'factors'` → `'risk'`
- **`frontend/packages/ui/src/components/dashboard/cards/DashboardAlertsPanel.tsx` line ~74**: Fallback navigation `'factors'` → `'risk'`

### 7. Chat navigation — `ChatCore.tsx` + `block-renderer.tsx`
- **`frontend/packages/ui/src/components/chat/shared/ChatCore.tsx` line ~711**: Chat action mapping `'factors'` → `'risk'` (where it flows into `setActiveView`)
- **`frontend/packages/ui/src/components/chat/blocks/block-renderer.tsx` line ~18**: Navigate target `"factors"` → `"risk"`
- Note: Chat action IDs that don't map to `setActiveView` (e.g., internal action keys at lines ~394, ~739) can stay as-is — they're not ViewIds.

### 8. `frontend/packages/connectors/src/navigation/__tests__/hashSync.test.ts`
- Add tests for:
  - `parseHash('#factors')` → `{ view: 'risk' }` (legacy alias)
  - `getStoredActiveView()` with localStorage `'factors'` → returns `'risk'`
  - `#risk` hash wins over localStorage `'factors'`

### 9. Other test files referencing `'factors'` as a ViewId
Search with `rg "'factors'" frontend/packages` and update any ViewId references. Codex found no quoted `'factors'` ViewId refs in the test files originally listed — verify during implementation and update any found.

### 10. Other component `setActiveView('factors')` calls
- `frontend/packages/ui/src/components/dashboard/views/modern/FactorsContainer.tsx` — if it self-references
- Any dashboard cards that navigate to the factors view
- Command palette entries

### NOT renaming (out of scope)
- **Component filenames**: `FactorsContainer.tsx`, `FactorRiskModel.tsx`, `FactorRiskModelContainer.tsx` — domain names ("factor risk model"), not nav labels.
- **Tab IDs within components**: `RiskAnalysis.tsx` line ~235 uses `"factors"` as an internal tab ID — not a ViewId.
- **Recovery/demo components**: `risk-analysis-dashboard.tsx` line ~173 — standalone recovery component.
- **Backend**: No backend changes.

## Implementation approach
Use `replace_all` on each file for the `'factors'` → `'risk'` swap where it refers to a ViewId. Be careful to distinguish ViewId references from domain terms (e.g., "factor exposures" is a domain concept, not a ViewId) and internal tab IDs (e.g., RiskAnalysis tabs).

## Verification
1. `cd frontend && npm run build` — no TS errors
2. `cd frontend && npx vitest run packages/connectors/src/navigation/__tests__/hashSync.test.ts` — hash sync tests pass
3. `cd frontend && npm test` — all tests pass
4. Manual: open `localhost:3000/#risk` → should show risk/factors view. `#factors` legacy → should also work (alias).

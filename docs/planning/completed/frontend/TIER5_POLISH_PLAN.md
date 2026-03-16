# Tier 5 Polish — Implementation Plan

> **Status**: ALL DONE
> **Scope**: Frontend-only, 3 items, 4 files
> **TODO ref**: `docs/TODO.md` §3G

## Context

Three remaining Tier 5 polish items. All are frontend-only surgical changes that remove misleading UI, fix design system inconsistencies, and upgrade the visual style toggle from plain buttons to preview cards. No backend work required.

---

## Item 1: Visual Style Toggle — Upgrade to Preview Cards

**File:** `frontend/packages/ui/src/components/portfolio/overview/SettingsPanel.tsx`

### Problem
The Classic/Premium toggle and Navigation Layout toggle are two separate sections using plain `<Button>` pairs. No visual preview of what each mode looks like — users must guess.

### Changes

1. **Add import** — `ToggleGroup`, `ToggleGroupItem` from `../../ui/toggle-group` (existing Radix component)
2. **Merge sections** — Combine "Visual Style" (lines 82-108) and "Navigation Layout" (lines 110-138) into a single "Appearance" section under the `Palette` icon
3. **Replace buttons with ToggleGroup + preview swatches:**
   - Visual style: two `ToggleGroupItem`s with mini preview divs
     - Classic swatch: `bg-white border border-neutral-200 shadow-sm` (flat, solid)
     - Premium swatch: `bg-white/70 backdrop-blur-sm border border-neutral-200/50 shadow-lg` (glass, blurred)
   - Nav layout: two `ToggleGroupItem`s with wireframe sketches
     - Sidebar: narrow left bar + content area
     - Header: thin top bar + content area
4. **Remove unused import** — `LayoutDashboard` from lucide-react

### Pattern
```tsx
<ToggleGroup type="single" value={draftVisualStyle}
  onValueChange={(v) => { if (v) setDraftVisualStyle(v as "classic" | "premium") }}
  className="grid grid-cols-2 gap-3">
  <ToggleGroupItem value="classic" className="flex flex-col items-center gap-2 p-3 rounded-xl border h-auto">
    <div className="w-full h-12 rounded-lg bg-white border border-neutral-200 shadow-sm" />
    <span className="text-xs font-medium">Classic</span>
  </ToggleGroupItem>
  <ToggleGroupItem value="premium" className="flex flex-col items-center gap-2 p-3 rounded-xl border h-auto">
    <div className="w-full h-12 rounded-lg bg-white/70 backdrop-blur-sm border border-neutral-200/50 shadow-lg" />
    <span className="text-xs font-medium">Premium</span>
  </ToggleGroupItem>
</ToggleGroup>
```

The `if (v)` guard prevents deselection (Radix `type="single"` fires empty string on deselect).

---

## Item 2: Risk Settings — Fix Metrics & Design System

**File:** `frontend/packages/ui/src/components/dashboard/views/modern/RiskSettingsViewModern.tsx`

### Problems
1. All 6 sliders default to 0% when no backend data exists — confusing for new users
2. Monitoring tab (line 514) and Alerts tab (line 611) use raw `<select>` instead of the design system `<Select>` component
3. Compliance tab (line 567) is a dead static "contact admin" banner — adds no value

### Changes

1. **Add import** — `Select, SelectContent, SelectItem, SelectTrigger, SelectValue` from `../../../ui/select`
2. **Fix slider fallback defaults** (lines 175-180) — Change from `0` to sensible values:

   | Setting | Old | New | Rationale |
   |---------|-----|-----|-----------|
   | `max_position_size` | 0 | 15 | Reasonable single-position cap |
   | `sector_limit` | 0 | 30 | Standard sector concentration limit |
   | `max_volatility` | 0 | 25 | Moderate volatility ceiling |
   | `max_factor_contribution` | 0 | 30 | Standard factor limit |
   | `max_drawdown` | 0 | 15 | Conservative drawdown cap |
   | `max_market_contribution` | 0 | 50 | Standard market exposure limit |

   These only apply when backend returns no value for a key. Saved settings take precedence.

3. **Remove Compliance tab** — Delete `<TabsTrigger value="compliance">` (line 350) and `<TabsContent value="compliance">` block (lines 567-573). Change `grid-cols-4` → `grid-cols-3` on TabsList.
4. **Replace raw `<select>` in Monitoring tab** (lines 514-524) with design system `<Select>` component
5. **Replace raw `<select>` in Alerts tab** (lines 611-621) with design system `<Select>` component
6. **Remove unused imports** — `Alert`, `AlertDescription` (only used in deleted Compliance tab)

7. **Update stale comments** — Remove "four-tab" references in component comments (lines ~343, ~576)

### Select replacement pattern
Pass `id` to `SelectTrigger` to preserve the existing `<Label htmlFor>` binding:
```tsx
<Select value={monitoringFrequency}
  onValueChange={(value) => handleSettingChange('monitoring_frequency', value)}>
  <SelectTrigger id="monitoring-frequency"><SelectValue /></SelectTrigger>
  <SelectContent>
    <SelectItem value="realtime">Real-time</SelectItem>
    <SelectItem value="hourly">Hourly</SelectItem>
    <SelectItem value="daily">Daily</SelectItem>
  </SelectContent>
</Select>
```

---

## Item 3: Account Connections — Remove Fake Sections

**Files:**
- `frontend/packages/ui/src/components/settings/AccountConnections.tsx` (primary)
- `frontend/packages/ui/src/components/settings/AccountConnectionsContainer.tsx` (secondary)

### Problem
The Security & Privacy section (2FA, encryption, auto-logout, data retention) and Sync Settings section (auto sync, frequency) use uncontrolled `<Switch defaultChecked>` elements with no state management and no backend persistence. These mislead users into thinking they're configuring real security features. The permissions badges per-account are also fabricated by the container.

### Changes in AccountConnections.tsx

1. **Delete Security & Privacy section** (lines 553-610) — All uncontrolled switches/buttons with no backend
2. **Delete Sync Settings section** (lines 612-663) — Fake toggles/buttons with no backend
3. **Move "Sync All" button to header** — Add alongside "Add Account" button (lines 365-381), with `variant="outline"` to differentiate from the primary CTA:
   ```tsx
   <div className="flex items-center space-x-2">
     <Button variant="outline" onClick={onRefreshConnections} disabled={isLoading}
       className="hover-lift-subtle">
       <RefreshCw className={`w-4 h-4 mr-2 ${isLoading ? 'animate-spin' : ''}`} />
       {isLoading ? 'Syncing...' : 'Sync All'}
     </Button>
     <Button variant="premium" onClick={() => setShowAddAccount(true)} ...>
       ...Add Account...
     </Button>
   </div>
   ```
4. **Delete permissions badges block** (lines 443-461) — Fabricated data
5. **Delete no-op Settings gear button** per account card (lines 508-510)
6. **Remove unused imports** — `Separator`, `Switch`, `Settings` (lucide-react). Keep `Shield` — still used in `getTypeIcon()`.
7. **Remove `onUpdateSecuritySettings` prop** — Delete from interface (line 200), destructuring (line 224), and the `_onUpdateSecuritySettings` alias. No callers remain after removing the Security section.
8. **Trim stale file-level docblock** — The 142-line docblock (lines 1-142) references Security & Privacy, Sync Settings, and permissions that are being removed. Trim to reflect the actual remaining scope.

### Changes in AccountConnectionsContainer.tsx

9. **Remove fabricated permissions fallback** (line 668): `['read_positions', 'read_transactions', 'read_balances']` → `[]`
10. **Remove fabricated SnapTrade permissions** (line 706): `['read_positions', 'read_transactions']` → `[]`
11. **Remove `handleUpdateSecuritySettings` callback** (~line 1145) and its prop pass (~line 1225) — dead code after UI removal
12. **Trim stale container docblock** — Remove references to security settings management, sync settings endpoints, and permissions fabrication

---

## Execution Order

1. **Item 2** (RiskSettings) — smallest blast radius, one file, no interface changes
2. **Item 1** (SettingsPanel) — one file, adds import, no interface changes
3. **Item 3** (AccountConnections) — two files, removes UI sections

## Verification

1. `cd frontend && npx tsc --noEmit` — TypeScript compilation
2. `cd frontend && npx vitest run` — Test suite
3. Visual: Settings panel → toggle previews render, both modes switch correctly
4. Visual: Risk Settings → 3 tabs (no Compliance), `<Select>` styling matches app, sliders show non-zero defaults
5. Visual: Account Connections → no Security/Sync sections, Sync All in header, no permissions badges

# Notification Center — Wire Real Data

**Date**: 2026-03-03
**Status**: COMPLETE — commit `1505c1f1` (Codex PASS, 3 rounds)
**Wave**: 3c (from `completed/FRONTEND_PHASE2_WORKING_DOC.md`)
**Backend Extension**: B-018

## Context

The Notification Center (bell icon dropdown in the app header) shows 2 hardcoded mock notifications. The UI component (`notification-center.tsx`) is already built and handles types, read/unread, dismiss, clear all, and action buttons. We just need to feed it real data.

Two backend sources already exist and are consumed by other parts of the app:
- **Smart Alerts** (`GET /api/positions/alerts`) — risk flags from `generate_position_flags()`: concentration, leverage, options, stale data, sector overweight, etc. (~20 flag types). Already consumed by `useSmartAlerts()` in Overview.
- **Pending Updates** (`GET /api/plaid/pending-updates` + `GET /api/snaptrade/pending-updates`) — webhook-triggered boolean flags: "new brokerage data available". Already consumed by `usePendingUpdates()` with 5-minute polling.

**One backend fix needed** (alert ID uniqueness), rest is purely frontend.

---

## Codex Review Findings (addressed)

| # | Severity | Finding | Fix |
|---|----------|---------|-----|
| 1 | High | Alert IDs not unique — `provider_error`, `stale_data`, `sector_concentration` can emit multiple flags with same `{type}_portfolio` ID | Fix backend ID generation in `routes/positions.py` to use `provider`/`sector` field when `ticker` absent |
| 2 | High | Type exports: interfaces must be `export interface` for barrel re-export | Mark `Notification` and `UseNotificationsReturn` as exported interfaces |
| 3 | Medium | `useNavigate()` returns new function each render → useMemo deps unstable; `ModernDashboardApp` re-renders every second (clock) → timestamps reset | Use `useUIActions().setActiveView` (Zustand stable ref); separate `useRef` timestamps per source |
| 4 | Medium | Dismissed `pending_plaid`/`pending_snaptrade` IDs persist forever, suppressing future pending updates | Pending dismissals are session-only (React state, not localStorage). Reappear on refresh. |
| 6 | Medium | (Round 2) Pending timestamps stale if no alerts exist | Separate `pendingTimestampRef` updated independently from `alertTimestampRef` |
| 7 | Medium | (Round 2) False→true transition reset fires on transient API errors | Eliminated transition tracking entirely — session-only pending dismissals solve this |
| 5 | Medium | Missing `features/index.ts` barrel update | Add `export * from './notifications'` to `features/index.ts` |

---

## Architecture

```
useSmartAlerts()  ──┐
                    ├──→  useNotifications()  ──→  NotificationCenter (unchanged)
usePendingUpdates() ┘         │
                              ├── alertMappings.ts (flag_type → title + nav action)
                              └── useNotificationStorage.ts (localStorage dismissed/read)
```

The hook composes two existing data sources + localStorage persistence into the `Notification[]` shape that `NotificationCenter` already accepts.

---

## Step 0: Backend Fix — Alert ID Uniqueness

### `routes/positions.py` (lines 210-224)

**Problem**: Alert ID is `f"{flag['type']}_{flag.get('ticker', 'portfolio')}"`. Flags like `provider_error`, `stale_data`, and `sector_concentration` don't have `ticker` but emit per-provider/per-sector, causing ID collisions (`provider_error_portfolio` for both Plaid and SnapTrade).

**Fix**: Use the most specific identifier available:

```python
# Build a unique alert ID from the most specific field available
def _build_alert_id(flag: dict) -> str:
    flag_type = flag["type"]
    discriminator = (
        flag.get("ticker")
        or flag.get("provider")
        or flag.get("sector")
        or "portfolio"
    )
    return f"{flag_type}_{discriminator}"
```

Then replace line 215:
```python
"id": _build_alert_id(flag),
```

This gives us: `provider_error_plaid`, `stale_data_snaptrade`, `sector_concentration_Technology`, etc.

---

## Files to Create

### 1. `frontend/packages/connectors/src/features/notifications/alertMappings.ts`

Pure mapping module (no React). Two maps:

**`FLAG_TYPE_TITLES`** — `flag_type` string → human-readable notification title. Covers all ~20 flag types from `routes/positions.py` `_ALERT_TYPE_MAP` (lines 25-46):

| flag_type | Title |
|-----------|-------|
| `single_position_concentration` | Position Concentration Warning |
| `leveraged_concentration` | Leveraged Concentration Alert |
| `top5_concentration` | Top Holdings Concentration |
| `large_fund_position` | Large Fund Position |
| `high_leverage` | High Leverage Alert |
| `leveraged` | Leverage Warning |
| `futures_high_notional` | High Futures Notional Exposure |
| `futures_notional` | Futures Notional Exposure |
| `expired_options` | Expired Options Detected |
| `near_expiry_options` | Options Near Expiry |
| `options_concentration` | Options Concentration |
| `cash_drag` | Cash Drag Detected |
| `margin_usage` | Margin Usage Alert |
| `stale_data` | Stale Data Warning |
| `low_position_count` | Low Position Count |
| `sector_concentration` | Sector Concentration |
| `low_sector_diversification` | Low Sector Diversification |
| `large_unrealized_loss` | Large Unrealized Loss |
| `low_cost_basis_coverage` | Low Cost Basis Coverage |
| `provider_error` | Provider Error |

Fallback for unknown flag types: snake_case → Title Case conversion via `getTitleForFlagType()`.

**`FLAG_TYPE_NAVIGATION`** — `flag_type` → `{ view: ViewId, label: string } | null`. Maps alerts to navigation actions:

| Category | flag_types | Navigation |
|----------|-----------|------------|
| Concentration | `single_position_concentration`, `leveraged_concentration`, `top5_concentration`, `large_fund_position`, `expired_options`, `near_expiry_options`, `options_concentration` | `{ view: 'holdings', label: 'Review holdings' }` |
| Risk | `high_leverage`, `leveraged`, `futures_high_notional`, `sector_concentration`, `low_sector_diversification` | `{ view: 'score', label: 'View risk analysis' }` |
| Performance | `large_unrealized_loss`, `cash_drag` | `{ view: 'performance', label: 'View performance' }` |
| Data quality | `stale_data`, `provider_error`, `low_cost_basis_coverage` | `{ view: 'settings', label: 'Check connections' }` |
| Other | `futures_notional`, `margin_usage`, `low_position_count` | `null` (no action button) |

**Imports**: `ViewId` from `../../stores/uiStore`.

### 2. `frontend/packages/connectors/src/features/notifications/useNotificationStorage.ts`

Small hook wrapping `localStorage` for dismissed + read notification IDs.

- Two `Set<string>` in React state, lazy-initialized from localStorage
- `dismiss(id)` — adds to dismissed set, persists to localStorage
- `markAsRead(id)` — adds to read set, persists to localStorage
- `dismissAll(ids: string[])` — bulk dismiss (for "Clear all"), persists
- localStorage keys: `risk:notifications:dismissed`, `risk:notifications:read`
- `loadSet(key)` / `saveSet(key, set)` helper functions for JSON serialize/deserialize

### 3. `frontend/packages/connectors/src/features/notifications/hooks/useNotifications.ts`

Main composition hook. Internals:

```typescript
export function useNotifications(): UseNotificationsReturn {
  const { data: alerts, loading: alertsLoading } = useSmartAlerts();
  const { plaidPending, snaptradePending } = usePendingUpdates();
  const { setActiveView } = useUIActions();  // stable ref from Zustand — no new fn per render
  const { dismissedIds, readIds, dismiss, markAsRead, dismissAll } = useNotificationStorage();
  // Session-only set for pending notification dismissals (not persisted to localStorage)
  const [pendingDismissed, setPendingDismissed] = useState<Set<string>>(new Set());

  // Stable timestamp per notification source, updated when that source's data changes.
  // Prevents resetting every second from ModernDashboardApp's clock re-renders.
  const alertTimestampRef = useRef(new Date());
  const pendingTimestampRef = useRef(new Date());
  useEffect(() => {
    if (alerts.length > 0) alertTimestampRef.current = new Date();
  }, [alerts]);
  useEffect(() => {
    if (plaidPending || snaptradePending) pendingTimestampRef.current = new Date();
  }, [plaidPending, snaptradePending]);

  const notifications = useMemo(() => {
    // 1. Map each SmartAlert → Notification (skip dismissed)
    // 2. Add pending update notifications (if not dismissed)
    // Action closures use setActiveView (stable Zustand selector)
    return result;
  }, [alerts, plaidPending, snaptradePending, dismissedIds, readIds, pendingDismissed, setActiveView]);

  // onMarkAsRead, onDismiss, onClearAll callbacks
  return { notifications, loading: alertsLoading, onMarkAsRead, onDismiss, onClearAll };
}
```

**Key fixes from Codex review:**
- **Stable navigation**: Use `useUIActions().setActiveView` directly (Zustand selector = stable ref) instead of `useNavigate()` which creates a new function per render. Action closures call `setActiveView(view)`.
- **Stable timestamps**: Separate `useRef` per source — `alertTimestampRef` updated when `alerts` changes, `pendingTimestampRef` updated when pending state changes. Prevents resetting every second from `ModernDashboardApp`'s clock re-renders.
- **Pending ID re-activation**: Rather than tracking false→true transitions (which can false-trigger on transient API errors since `usePendingUpdates` returns `false` on fetch failure), simply **don't persist** pending dismissed IDs to localStorage at all. Pending dismissals are session-only (React state). Alert flag dismissals persist to localStorage as before. This means pending notifications reappear on page refresh (correct behavior — the user should see them again) and avoids the false-trigger problem entirely.

**Mapping logic** (inside `useMemo`):

1. For each `SmartAlert` in `alerts`:
   - Skip if `dismissedIds.has(alert.id)`
   - Map severity: `critical` → `error`, `warning` → `warning`, `info` → `info`
   - Title from `getTitleForFlagType(alert.flagType)`
   - Action from `FLAG_TYPE_NAVIGATION[alert.flagType]` → `{ label, onClick: () => setActiveView(view) }`
   - `read` from `readIds.has(alert.id)`
   - `timestamp: alertTimestampRef.current`

2. If `plaidPending && !pendingDismissed.has('pending_plaid')`:
   - Type: `success`, title: "New Data Available"
   - Message: "New portfolio data is available from Plaid. Refresh to see the latest."
   - Action: `{ label: 'Check connections', onClick: () => setActiveView('settings') }`

3. Same for `snaptradePending` with id `pending_snaptrade`.

**`Notification` interface** — `export interface` (must be exported for barrel re-export). Defined locally in this file, structurally identical to `notification-center.tsx`'s interface. TypeScript structural typing handles compatibility, avoiding cross-package import (`@risk/connectors` cannot import from `@risk/ui`):

```typescript
export interface Notification {
  id: string;
  type: 'success' | 'warning' | 'info' | 'error';
  title: string;
  message: string;
  timestamp: Date;
  read: boolean;
  action?: { label: string; onClick: () => void };
}
```

**Return shape**:
```typescript
export interface UseNotificationsReturn {
  notifications: Notification[];
  loading: boolean;
  onMarkAsRead: (id: string) => void;
  onDismiss: (id: string) => void;
  onClearAll: () => void;
}
```

### 4. `frontend/packages/connectors/src/features/notifications/index.ts`

Barrel export:
```typescript
export { useNotifications } from './hooks/useNotifications';
export type { Notification, UseNotificationsReturn } from './hooks/useNotifications';
```

---

## Files to Edit

### 5. `frontend/packages/connectors/src/features/index.ts`

Add export line alongside existing feature re-exports (after line 41):
```typescript
export * from './notifications';
```

### 6. `frontend/packages/connectors/src/index.ts`

Add export line alongside existing feature exports:
```typescript
export { useNotifications } from './features/notifications';
export type { Notification } from './features/notifications';
```

### 7. `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx`

- **Add import**: `import { useNotifications } from '@risk/connectors'`
- **Remove**: `useState` mock notifications block (~lines 162-183)
- **Remove**: `handleMarkAsRead`, `handleDismiss`, `handleClearAll` callbacks (~lines 298-312)
- **Add**: `const { notifications, onMarkAsRead, onDismiss, onClearAll } = useNotifications();`
- **Update JSX** (~line 619): pass hook return values to `<NotificationCenter>` (prop names already match)

### `notification-center.tsx` — NO CHANGES

The component already handles everything correctly.

---

## Key Design Decisions

1. **No duplicate fetching**: `useSmartAlerts()` and `usePendingUpdates()` use TanStack Query with cache keys. If `PortfolioOverviewContainer` is also mounted, they share the same cached data.

2. **Dismissed IDs — two tiers**: Alert flag dismissals persist to localStorage (stale IDs for resolved conditions are harmless — they match nothing). Pending update dismissals are **session-only** (React `useState`) — they reappear on page refresh, which is correct behavior. This avoids the problem of permanent suppression from transient API errors (where `usePendingUpdates` returns `false` on fetch failure, creating false transitions).

3. **Alert IDs are unique**: Backend fix uses `ticker || provider || sector || 'portfolio'` as discriminator, giving unique IDs like `provider_error_plaid`, `sector_concentration_Technology`.

4. **Pending updates action → settings**: Navigate to `settings` view (which shows AccountConnections with refresh capability). Note: `connections` ViewId exists but gets redirected to `score` by `ModernDashboardApp`.

5. **Type compatibility without cross-package import**: The `Notification` type is defined in both `@risk/connectors` (hook) and `@risk/ui` (component). TypeScript structural typing handles assignment compatibility. This avoids violating the package boundary rule (`@risk/connectors` cannot import from `@risk/ui`).

6. **Notification ordering**: Alerts appear in API response order (severity-sorted by backend `_sort_flags()`), with pending update notifications appended at the end.

7. **Render stability**: `useUIActions().setActiveView` (Zustand selector) used instead of `useNavigate()` to avoid new function references per render. Timestamps use `useRef` to avoid resetting on `ModernDashboardApp`'s 1-second clock re-renders.

---

## Critical Files (read for implementation context)

| File | Purpose |
|------|---------|
| `frontend/packages/connectors/src/features/positions/hooks/useSmartAlerts.ts` | Source hook — SmartAlert type, query config, transform |
| `frontend/packages/connectors/src/features/portfolio/hooks/usePendingUpdates.ts` | Source hook — dual-query polling pattern |
| `frontend/packages/connectors/src/primitives/contextHooks.ts` | `useNavigate()` — wraps `setActiveView` |
| `frontend/packages/connectors/src/stores/uiStore.ts` | `ViewId` type definition (line 80) |
| `frontend/packages/ui/src/components/ui/notification-center.tsx` | Target component — props interface, no changes needed |
| `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx` | Integration point — replace mock state |
| `routes/positions.py` | Backend alert ID generation (line 215) — fix uniqueness, `_ALERT_TYPE_MAP` (lines 25-46) |
| `core/position_flags.py` | Flag generation — provider/sector/ticker fields per flag type |
| `frontend/packages/connectors/src/features/index.ts` | Features barrel — add notifications re-export |

---

## Verification

1. `pnpm typecheck` — no TypeScript errors across all 3 packages
2. `pnpm lint` — no ESLint errors
3. `pnpm build` — Vite build succeeds
4. Visual check in browser:
   - Bell icon shows real alert count badge
   - Dropdown shows real position flags with correct titles and severity colors
   - Action buttons navigate to correct views
   - Dismiss persists across page refresh (check localStorage keys)
   - Mark as read removes blue highlight / unread dot
   - Clear all dismisses all current notifications
   - When pending updates exist, success notification appears
   - When no alerts and no pending updates, empty state shows
5. Confirm no duplicate fetching: React Query devtools should show single cached query for `/api/positions/alerts` even with both Overview and NotificationCenter mounted

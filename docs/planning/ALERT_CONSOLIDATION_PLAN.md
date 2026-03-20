# Alert Consolidation & Redesign

## Context
The Overview page has **two redundant alert sections** consuming excessive vertical space:
1. **SmartAlertsPanel** (top of PortfolioOverview) — purple glassTinted card showing top 3 alerts. No navigation actions, no risk score integration, no expand/collapse. Purely decorative.
2. **DashboardAlertsPanel** (bottom grid) — shows same smart alerts + risk score alerts, with severity sorting, navigation buttons, and expand/collapse.

Both consume the same `alertData` from `useNotifications()`. The SmartAlertsPanel is strictly redundant — it shows a subset of what DashboardAlertsPanel already provides, with fewer features.

## Codex Review Findings (addressed)
- **Fixed:** Broken error state — `useRiskScore()` failure not surfaced in empty state
- **Fixed:** Severity badge underspecified during loading/partial failure
- **Fixed:** `[key: string]: unknown` + `...props` leaks stale `smartAlerts` through container
- **Fixed:** Dead local `SmartAlert` type in `overview/types.ts` preserved needlessly
- **Fixed:** Hover/lift on non-clickable rows implies false interactivity
- **Fixed:** Risk-score alerts (`type === 'risk'`) must preserve fallback navigation to `factors` view — these alerts use human-readable names from RiskScoreAdapter, not `FLAG_TYPE_NAVIGATION` keys
- **Fixed:** Clickable rows need keyboard/semantic a11y — use `<button>` element styled as row, not bare `div` with `onClick`
- **Accepted:** Skip smooth height transition — plain toggle, no animation complexity
- **Deferred:** Component tests for DashboardAlertsPanel (separate task)

## Plan

### Step 1: Remove SmartAlertsPanel

**a) `frontend/packages/ui/src/components/portfolio/PortfolioOverview.tsx`**
- Remove `SmartAlertsPanel` from import (line 12)
- Remove rendering block (lines 53-55)
- Remove `smartAlerts` from destructured props (line 20)

**b) `frontend/packages/ui/src/components/portfolio/overview/types.ts`**
- Remove `smartAlerts?: SmartAlert[]` from `PortfolioOverviewProps` (line 99)
- Delete the local `SmartAlert` interface (lines 51-60) — the authoritative type lives in `@risk/connectors`, keeping this local copy creates drift
- Remove `SmartAlert` from the barrel export in `index.ts` (line 10)

**c) `frontend/packages/ui/src/components/portfolio/overview/index.ts`**
- Remove `SmartAlertsPanel` export (line 8)
- Remove `SmartAlert` from type export (line 10)

**d) `frontend/packages/ui/src/components/dashboard/views/modern/PortfolioOverviewContainer.tsx`**
- Remove `smartAlerts` prop from interface (line 45)
- Remove `[key: string]: unknown` index signature (line 46) — prevents stale callers from silently passing removed props
- Remove `SmartAlert` type import (line 38)
- Remove from destructure (line 50)
- Remove pass-through to PortfolioOverview (line 177)
- Remove `...props` rest spread from `<PortfolioOverview>` (line 188) — only pass explicitly declared props
- Remove from memo comparison (line 207)

**e) `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx`**
- Remove `smartAlerts={alertData}` from `<PortfolioOverviewContainer>` (line 430)

**f) Delete `frontend/packages/ui/src/components/portfolio/overview/SmartAlertsPanel.tsx`**

### Step 2: Redesign DashboardAlertsPanel

**File:** `frontend/packages/ui/src/components/dashboard/cards/DashboardAlertsPanel.tsx`

**Design direction — "Status Board":**
- Left severity accent bar (3px `border-l`) as the signature visual element per alert row
- Severity-tinted row backgrounds (subtle — matching existing `bg-red-50/50`, `bg-amber-50/50`, `bg-blue-50/50` patterns from OverviewMetricCard)
- Compact density: tighter padding (`py-2 px-3`), no `border-b` separators
- Rounded alert rows with gap spacing instead of dividers
- Header: "Alerts" title + severity count badge (e.g., "2 critical, 3 warning")
- Plain expand/collapse toggle (no animated height transitions — just slice visibility)
- Match existing Card patterns (standard variant, consistent with DashboardHoldingsCard)

**Clickable rows (Codex fix):**
- Make entire alert row clickable when navigation resolves — `onClick` navigates to the mapped view
- Navigation resolution: use existing `AlertRow` logic — check `FLAG_TYPE_NAVIGATION` first, then fall back to `{ view: 'factors', label: 'View risk analysis' }` for `type === 'risk'` alerts (preserves current behavior from lines 52-56)
- Use `cursor-pointer` + subtle hover background shift on actionable rows only
- Render actionable rows as `<button>` elements (not `div` + `onClick`) for keyboard/screen-reader a11y — styled as block with `w-full text-left` to look like a row
- Remove the separate ghost button — the row IS the action
- Non-actionable rows (no navigation resolution) remain plain `div` with no hover/cursor

**Error state fix (Codex fix):**
- Track `riskError` from `useRiskScore()` alongside `alertsError`
- Empty state message: if either source errored, show "Some alerts may be unavailable" instead of "No active alerts"
- `isLoading` already combines both sources (line 115) — no change needed there

**Severity badge loading state (Codex fix):**
- While `isLoading` is true: show skeleton badge or omit the count badge entirely
- Once loaded: show severity breakdown (e.g., "2 critical · 3 warning") only if alerts exist
- If both sources loaded but zero alerts: no badge, just "No active alerts" empty state

**Severity color mapping (matches existing app patterns):**
- Critical: `border-l-red-500 bg-red-50/50` (dark: `bg-red-950/30`)
- Warning: `border-l-amber-500 bg-amber-50/50` (dark: `bg-amber-950/30`)
- Info: `border-l-blue-500 bg-blue-50/50` (dark: `bg-blue-950/30`)

## Verification
1. `cd frontend && npx tsc --noEmit` — no type errors
2. Visual check at localhost:3000 — Overview loads, no top banner, alerts card in bottom grid
3. Alerts card shows severity accent bars, tinted rows
4. Clicking an alert row navigates to the correct view
5. Expand/collapse toggle works
6. Error state: if risk score API fails, card shows "Some alerts may be unavailable"
7. Dark mode check

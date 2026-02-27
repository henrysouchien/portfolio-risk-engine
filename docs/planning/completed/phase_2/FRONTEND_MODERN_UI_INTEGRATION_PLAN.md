## Frontend Modern UI Integration Plan

### Objectives
- **Integrate the new Modern Dashboard UI** into the existing architecture without breaking auth, services, adapters, or stores.
- **Unify navigation** so all feature routes/views use a single source of truth.
- **Wire new UI components to real data hooks** and intent-based actions.
- **Preserve performance and a11y** with code-splitting, valid Tailwind usage, and accessible controls.

### Scope
- UI layer in `frontend/src/components/**` (modern portfolio UI, chat, layout).
- Navigation/state in `frontend/src/router/**`, `frontend/src/stores/**`.
- Intent system in `frontend/src/utils/NavigationIntents.ts` and handlers in `frontend/src/providers/SessionServicesProvider.tsx`.
- Data hooks in `frontend/src/features/**`.

### Current Architecture Fit (summary)
- Providers: `QueryProvider` → `AuthProvider` → `SessionServicesProvider` → `AppOrchestratorModern` (`frontend/src/App.tsx`).
- State: Zustand stores (`authStore`, `portfolioStore`, `uiStore`) + React Query hooks (`features/*/hooks`).
- Services/adapters: data normalization and service orchestration behind `SessionServicesProvider`.
- Intents: `IntentRegistry` decouples business actions from UI. Ideal for Modern UI actions (refresh, analyze risk).
- Design system: `components/ui/*` + Tailwind tokens in `src/index.css` and `tailwind.config.js`.

---

## Integration Strategy (Phased)

### Phase 0 — Pre‑flight
- Ensure `AppOrchestratorModern` is the entry point (it already is), with toggle `⌘⇧M` for A/B: `frontend/src/router/AppOrchestratorModern.tsx`.
- Confirm Tailwind config scans `./src/**/*.{js,jsx,ts,tsx}` (ok). Validate custom classes in `frontend/src/index.css` against Tailwind (fix invalid ones in Phase 4).
- Decide canonical Modern shell: prefer `components/apps/ModernDashboardApp.tsx` over `components/portfolio/ModernDashboard.tsx` (the latter is demo-level and keeps its own local view state).

Deliverables:
- Decision log referencing chosen shell.

### Phase 1 — Navigation Unification (single source of truth)
Problem: View IDs are inconsistent across components.
- Source of truth: `uiStore` `ViewId` = `score | factors | performance | holdings | research | strategies | chat | settings` (`frontend/src/stores/uiStore.ts`).
- Actions:
  - Update `components/layout/ChatInterface.tsx` to set `uiStore` view via `useUIActions().setActiveView(...)` using a mapping from synonyms.
  - Remove `onViewChange` prop usage; emit store updates directly.
  - Deprecate local `activeView` state in `components/portfolio/ModernDashboard.tsx` or make it read from `uiStore`. Prefer archiving this file if `ModernDashboardApp` is canonical.
  - Ensure `ModernDashboardApp` continues to read `activeView` from `uiStore` (already does).

Suggested mapping:
```ts
// inside ChatInterface.tsx intent handler
import { useUIActions } from '../../stores/uiStore';

const { setActiveView } = useUIActions();
const viewMap: Record<string, Parameters<typeof setActiveView>[0]> = {
  overview: 'score',
  score: 'score',
  factor: 'factors',
  factors: 'factors',
  stocks: 'research',
  stock: 'research',
  research: 'research',
  scenarios: 'strategies', // or add a new ViewId if you want a dedicated scenarios tab
  stress: 'strategies',
  performance: 'performance',
  holdings: 'holdings',
  chat: 'chat',
  settings: 'settings',
};
```

Acceptance:
- Switching via chat or nav sets `uiStore.activeView` consistently and renders the expected pane in `ModernDashboardApp`.
- Basic tests asserting `activeView` changes and correct component renders.

### Phase 2 — Intent‑based Actions (decouple UI from business logic)
Problem: Demo components simulate side effects and toasts.
- Use `IntentRegistry` (`frontend/src/utils/NavigationIntents.ts`) for:
  - Refresh holdings: `triggerIntent('refresh-holdings')`.
  - Analyze risk: `triggerIntent('analyze-risk')`.
- Replace manual `setTimeout` refresh in `PortfolioOverview.tsx` with intent triggers and `ui/toast` for feedback.
- Keep handlers registered in `SessionServicesProvider` (already wired).

Acceptance:
- Refresh button triggers real holdings refresh (via manager) and updates store data.
- Analyze risk triggers analysis and updates stores/hooks; toasts show success/failure.

### Phase 3 — Data Wiring (replace mock metrics)
Problem: `PortfolioOverview.tsx` uses mocked metrics.
- Replace mocked values with real hooks:
  - `features/portfolio/usePortfolioSummary` → totals, P&L, growth.
  - `features/riskScore/useRiskScore` → risk score, beta, VaR.
  - `features/analysis/useRiskAnalysis` → exposures, attribution.
  - `features/analysis/usePerformance` (if present) → trend arrays.
- Introduce simple selectors/adapters to match the display model expected by cards.
- Preserve animation logic; treat missing data with skeletons/loading states.

Acceptance:
- Overview tiles render live data when available; fallback gracefully with skeletons.
- No ResizeObserver or layout thrash regressions.

### Phase 4 — Styling, Tailwind, and A11y Fixes
- Replace invalid Tailwind classes:
  - `opacity-35` → `opacity-30` or `opacity-[0.35]`.
  - Color fractions like `from-blue-500/3` → `from-blue-500/[0.03]` (same for `to-*`).
- Event deprecations:
  - Replace `onKeyPress` with `onKeyDown` for Enter handling in `ChatInterface` input.
- Types:
  - For timeouts, prefer `ReturnType<typeof setTimeout>` over `NodeJS.Timeout` in DOM contexts.
- A11y:
  - Primary nav: use tab semantics (`role="tablist"`, `role="tab"`, `aria-selected`, `aria-controls`).
  - Ensure focus indicators are visible with current styling.
  - `ChatInterface` messages container uses `aria-live="polite"` for AI responses.

Acceptance:
- No Tailwind warnings; keyboard navigation works; contrast and focus visible.

### Phase 5 — Performance & Maintainability
- Code-splitting: lazy‑load heavy panes (`FactorRiskModel`, `ScenarioAnalysis`, `PerformanceView`) with `React.lazy` + suspense skeletons.
- Extract large sub‑components from `PortfolioOverview.tsx`:
  - `MetricTile`, `MarketIntelligenceBanner`, `AIRecommendationsPanel`.
- Consider list virtualization if any large tables are added later (not mandatory now).

Acceptance:
- Initial load is lighter; CLS is stable; extracted components are unit-testable.

### Phase 6 — Flags & Rollout
- Keep `AppOrchestratorModern` default `USE_MODERN_UI = true`, and optionally gate behind a feature flag (env var or store) for staged rollouts.
- Preserve ⌘⇧M toggle for internal testing.
- Rollback path: toggle back to classic UI instantly.

Acceptance:
- Easy on/off; no migration blockers.

### Phase 7 — QA, Tests, and Observability
- Unit tests: selectors, `uiStore` view switching, mapping logic, basic component render with mock data.
- Integration tests: refresh & analyze intents update UI; chat actions route to correct views.
- E2E happy paths: login → modern dashboard → overview/factors/performance/holdings → chat → settings.
- Observability: add light logging around intent triggers/results and view switches (via `frontendLogger`).

Acceptance:
- CI green; regression suite passes; no console errors in supported browsers.

---

## Concrete Work Items (by file)
- `frontend/src/components/layout/ChatInterface.tsx`
  - Map intents to `uiStore` view IDs, remove `onViewChange` usage.
  - Use `onKeyDown` for Enter; add `aria-live` to response area.

- `frontend/src/components/apps/ModernDashboardApp.tsx`
  - Keep as canonical modern shell reading `uiStore.activeView`.
  - Optionally extract `DashboardHeader` and `PrimaryNav` into separate components for reuse.

- `frontend/src/components/portfolio/PortfolioOverview.tsx`
  - Replace mock data with hooks; add skeletons; replace manual refresh with intent triggers and `ui/toast`.
  - Fix invalid Tailwind classes; switch timeout types to `ReturnType<typeof setTimeout>`.
  - Extract `MetricTile`, `MarketIntelligenceBanner`, `AIRecommendationsPanel`.

- `frontend/src/components/portfolio/ModernDashboard.tsx`
  - Either read/write `uiStore` instead of local `activeView`, or archive as reference once `ModernDashboardApp` is primary.

- `frontend/src/utils/NavigationIntents.ts`
  - No change; ensure handlers cover required intents.

- `frontend/src/providers/SessionServicesProvider.tsx`
  - Confirm registered handlers (`refresh-holdings`, `analyze-risk`) and keep logging.

- `frontend/src/index.css`, `frontend/tailwind.config.js`
  - Validate custom classes; keep tokens; ensure scanning covers all paths (already ok).

---

## Example Snippets

### View mapping in ChatInterface
```ts
// ChatInterface.tsx
import { useUIActions } from '../../stores/uiStore';

const { setActiveView } = useUIActions();
const toViewId = (key: string) => {
  const map: Record<string, any> = {
    overview: 'score', score: 'score',
    factor: 'factors', factors: 'factors',
    stocks: 'research', stock: 'research', research: 'research',
    scenarios: 'strategies', stress: 'strategies',
    performance: 'performance', holdings: 'holdings',
    chat: 'chat', settings: 'settings',
  };
  return map[key] || 'score';
};

// when interpreting user commands
setActiveView(toViewId('overview')); // example
```

### Intent-based refresh from Overview
```ts
import { IntentRegistry } from '../../utils/NavigationIntents';
import { toast } from '../ui/toast';

const handleDataRefresh = async () => {
  const res = await IntentRegistry.triggerIntent('refresh-holdings', { source: 'overview-refresh' });
  if (res.success) toast({ title: 'Portfolio refreshed' });
  else toast({ title: 'Refresh failed', description: res.error?.message, variant: 'destructive' });
};
```

### Tailwind class fixes
- `opacity-35` → `opacity-30` or `opacity-[0.35]`.
- `from-*-500/3` → `from-*-500/[0.03]` (and for `to-*`).

---

## Acceptance Criteria (global)
- All navigation originates from and reflects in `uiStore.activeView`.
- Modern UI triggers business actions via `IntentRegistry` only.
- Overview tiles show live data via hooks; skeletons for loading.
- No Tailwind warnings or deprecated event handlers.
- Initial load improved by lazy loading heavy panes.
- A11y basics: keyboard nav, visible focus, `aria-live` for chat.

## Risks & Rollback
- Risk: mismatched view IDs cause blank renders → Mitigation: central mapping + tests.
- Risk: intent errors show confusing UI → Mitigation: standardized `toast` handling and logging.
- Rollback: switch to Classic UI via `AppOrchestratorModern` toggle (⌘⇧M) or feature flag.

## Timeline (estimate)
- Phase 1–2: 0.5–1 day
- Phase 3: 1–1.5 days
- Phase 4: 0.5 day
- Phase 5: 0.5–1 day
- Phase 6–7: 0.5–1 day

## Code Owners
- UI integration (components, a11y, Tailwind): FE lead
- Hooks/data wiring (features/*): FE + BE (for contract confirmations)
- Intent handlers/services: FE platform owner
- QA/tests: QA + FE

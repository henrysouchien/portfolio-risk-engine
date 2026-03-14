# Frontend Performance Optimization Plan
**Status:** COMPLETE (Phases 1-3 implemented, Phase 4 deferred)
**Date:** 2026-03-10

## Context

Backend optimization is complete (70s → 3.4s factor recommendations, 3.3s → 225ms analyze_portfolio). The frontend is now the remaining bottleneck:

- **2.1MB single JS bundle** (599KB gzipped) — no code splitting at all
- **0 React.lazy() usage** (except QueryDevtools in dev) — all 10 view containers imported eagerly
- **Live clock re-renders entire dashboard shell** every 1 second
- **Background polling** continues when tab is hidden
- **Chat/markdown/KaTeX** loaded globally even if chat never opened
- **64 dependencies** in @risk/ui bundled together — recharts, katex, framer-motion, 19 Radix packages

Prior frontend work (Phases 1-2) reduced API requests from 103 → 26 on page load. This plan targets bundle size, render efficiency, and runtime overhead.

### Baseline Measurement (Required Before Implementation)

Before starting any changes, capture:
1. `npm run build` output — chunk names, sizes (raw + gzipped)
2. Lighthouse audit (FCP, LCP, TTI, Total Blocking Time)
3. React DevTools Profiler — idle re-render count over 10 seconds
4. Network waterfall — first 5 seconds after page load

---

## Phase 1: Quick Wins (Very Low Risk)

### 1A. Clock Isolation

**File**: `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx`
**Problem**: `currentTime` state (line 170) updates every 1 second via RAF + setTimeout (lines 180-188). This causes the entire 948-line dashboard shell to reconcile every second — all 10 view containers, sidebar, header, and notification center re-render even though only the clock display changes.

**Change**: Extract clock display + market status into a small isolated component:

```tsx
// New: components/dashboard/LiveClock.tsx
function LiveClock() {
  const [currentTime, setCurrentTime] = useState(new Date());

  useEffect(() => {
    let animationId: number;
    const updateClock = () => {
      setCurrentTime(new Date());
      animationId = requestAnimationFrame(() => {
        setTimeout(updateClock, 1000);
      });
    };
    updateClock();
    return () => cancelAnimationFrame(animationId);
  }, []);

  return (
    <span className="text-xs font-mono text-neutral-500 tracking-wide">
      {currentTime.toLocaleTimeString('en-US', { hour12: true, hour: '2-digit', minute: '2-digit', second: '2-digit' })}
    </span>
  );
}
```

Market status (lines 197-227) also moves into `LiveClock` since it depends on the current time. Currently `updateMarketStatus()` is only called once on mount (line 228) — this is a **correctness bug** (market status never updates after mount). Moving it into the isolated component fixes this: the market status recalculates on each tick, but since `LiveClock` is isolated, this doesn't propagate re-renders to the dashboard shell.

**Optimization**: Inside `LiveClock`, gate the `Intl.DateTimeFormat` market status computation on minute changes to avoid unnecessary `formatToParts` calls:

```tsx
const minuteRef = useRef(-1);
const [marketStatus, setMarketStatus] = useState("closed");

useEffect(() => {
  const min = currentTime.getMinutes();
  if (min !== minuteRef.current) {
    minuteRef.current = min;
    setMarketStatus(computeMarketStatus(currentTime));
  }
}, [currentTime]);
```

Remove `currentTime` and `marketStatus` state from `ModernDashboardApp`. The rest of the shell no longer re-renders every second.

**Verification**:
1. React DevTools Profiler — dashboard shell should show 0 re-renders when idle (previously 1/sec)
2. Market status should update when market opens/closes (currently broken — only computed on mount)
3. Clock display continues ticking normally

### 1B. Background Polling Pause

**File**: `frontend/packages/connectors/src/features/portfolio/hooks/usePendingUpdates.ts`
**Problem**: `refetchIntervalInBackground: true` (line ~45) means Plaid/SnapTrade polling continues when the browser tab is hidden. Unnecessary network + server load.

**Change**: Set `refetchIntervalInBackground: false`:

```tsx
// Before:
refetchIntervalInBackground: true,

// After:
refetchIntervalInBackground: false,
```

Search all hooks for `refetchIntervalInBackground: true` and update any others found.

**Verification**:
1. Switch to another tab for 5+ minutes, check network tab — no pending-updates requests while hidden
2. Return to tab — polling resumes, pending updates appear if any exist

---

## Phase 2: Code Splitting (Medium Risk, Highest Impact)

### 2A. Route-Level Code Splitting (do this FIRST)

**File**: `frontend/packages/ui/src/router/AppOrchestratorModern.tsx`
**Problem**: All three app shells (LandingApp, AnalystApp, ModernDashboardApp) imported eagerly at lines 23-25. The entire dashboard + chat + all views load even before auth completes.

**Current routing structure** (lines 66-156):
1. Path `/plaid/success` → PlaidSuccess
2. Path `/snaptrade/success` → SnapTradeSuccess
3. Path `/analyst` → separate auth gates → `AnalystApp` (line 101)
4. Default path → auth state machine → `ModernDashboardApp` (line 148) or `LandingApp` (line 155)

**Change**: Keep `LandingApp` eager (auth gate, first thing unauthenticated user sees). Keep `AuthTransition` and success pages eager (small). Lazy-load the authenticated shells:

```tsx
import { LandingApp } from '../components/apps/LandingApp'; // Keep eager (auth gate)
import { AuthTransition } from '../components/transitions/AuthTransition';
import PlaidSuccess from '../pages/PlaidSuccess';
import SnapTradeSuccess from '../pages/SnapTradeSuccess';

// Lazy — only loaded after authentication
const ModernDashboardApp = React.lazy(() =>
  import('../components/apps/ModernDashboardApp')
);
// AnalystApp has no default export — use named export wrapper
const AnalystApp = React.lazy(() =>
  import('../components/apps/AnalystApp').then(m => ({ default: m.AnalystApp }))
);
```

Wrap the two authenticated render sites in `Suspense`. The router structure stays identical — just the import mechanism changes:

```tsx
// Line 101 (analyst path, authenticated + services ready):
return (
  <Suspense fallback={<AuthTransition message="Loading analyst mode..." />}>
    <AnalystApp />
  </Suspense>
);

// Line 148 (default path, authenticated + services ready):
return (
  <div>
    {/* ... developer indicator ... */}
    <Suspense fallback={<AuthTransition message="Loading dashboard..." />}>
      <ModernDashboardApp />
    </Suspense>
  </div>
);
```

**Why this comes first**: This is the highest-leverage single split. The entire dashboard bundle (all containers, chat, KaTeX) moves to a lazy chunk that only loads after auth. The landing/auth page becomes tiny. The routing structure and auth state machine remain identical.

**Verification**: Network tab — ModernDashboardApp chunk loads only after authentication. AnalystApp chunk loads only on `/analyst` navigation. Auth flow (LandingApp → AuthTransition → Dashboard) works identically.

### 2B. View Container Lazy Loading

**File**: `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx` (lines 78-89)
**Problem**: All 10 view containers (~5,800 lines total) imported eagerly at module scope via barrel export. User only sees one view at a time.

**Current** (lines 78-89):
```tsx
import {
  FactorRiskModelContainer,
  HoldingsViewModernContainer,
  PerformanceViewContainer,
  PortfolioOverviewContainer,
  RiskAnalysisModernContainer,
  RiskMetricsContainer,
  RiskSettingsContainer,
  ScenarioAnalysisContainer,
  StockLookupContainer,
  StrategyBuilderContainer
} from '../dashboard/views/modern';
```

**Default view is `score`** (from `uiStore.ts:200`), which renders 5 containers together:
- `PortfolioOverviewContainer`
- `AssetAllocationContainer`
- `RiskAnalysisModernContainer`
- `PerformanceViewContainer`
- `RiskMetricsContainer`

**Change**: Keep all 5 `score`-view containers eager. Lazy-load the remaining 5 that only render on non-default views:

```tsx
// Eager — used on default 'score' view (and reused on 'factors', 'performance' views)
import {
  AssetAllocationContainer,
  PerformanceViewContainer,
  PortfolioOverviewContainer,
  RiskAnalysisModernContainer,
  RiskMetricsContainer,
} from '../dashboard/views/modern';

// Lazy — only loaded when user navigates to these views
const HoldingsViewModernContainer = React.lazy(() =>
  import('../dashboard/views/modern/HoldingsViewModernContainer')
);
const ScenarioAnalysisContainer = React.lazy(() =>
  import('../dashboard/views/modern/ScenarioAnalysisContainer')
);
const StockLookupContainer = React.lazy(() =>
  import('../dashboard/views/modern/StockLookupContainer')
);
const StrategyBuilderContainer = React.lazy(() =>
  import('../dashboard/views/modern/StrategyBuilderContainer')
);
const FactorRiskModelContainer = React.lazy(() =>
  import('../dashboard/views/modern/FactorRiskModelContainer')
);
```

Also lazy-load settings + account connections (only on 'settings' view):
```tsx
const RiskSettingsContainer = React.lazy(() =>
  import('../dashboard/views/modern/RiskSettingsContainer')
);
const AccountConnectionsContainer = React.lazy(() =>
  import('../settings/AccountConnectionsContainer')
);
```

**Suspense boundary**: The existing `isLoading` state (lines 305-311) already shows a 400ms synthetic loading skeleton on view switch. To avoid double fallbacks, replace the synthetic delay with Suspense as the sole loading mechanism:

```tsx
// Remove the synthetic 400ms isLoading timer (lines 305-311)
// Replace with Suspense around the view switch:
<Suspense fallback={<ViewTransitionSkeleton />}>
  {renderActiveView()}
</Suspense>
```

`ViewTransitionSkeleton` should match the current loading skeleton's layout. The first load of a lazy view shows the skeleton; subsequent loads are instant (chunk cached by browser).

**Note on ChatInterface**: The `chat` view (line 493-506) renders `ChatInterface` which is imported eagerly (line 90). This should also be lazy-loaded since the chat view is non-default:

```tsx
const ChatInterface = React.lazy(() =>
  import('../layout/ChatInterface')
);
```

**Verification**:
1. `npm run build` — should produce multiple JS chunks
2. Default `score` view loads instantly (no flash/skeleton)
3. Switching to `holdings`, `scenarios`, `research`, `strategies`, `factors`, `settings`, or `chat` triggers chunk loads
4. No double-loading-skeleton (synthetic 400ms delay removed)

### 2C. Vite Manual Chunks Configuration

**File**: `frontend/vite.config.ts`
**Problem**: No `manualChunks` config. After Phase 2A/2B create dynamic import boundaries, Vite needs guidance on how to group vendor code into stable chunks for caching.

**Important**: `manualChunks` improves browser cacheability (vendor code changes rarely vs app code), but does NOT reduce first-load payload unless the chunks are behind lazy boundaries. Apply this AFTER 2A/2B so the vendor chunks are only loaded when their consumer chunks are loaded.

**Change**: Use the function form (more robust than object form for monorepo with many @radix-ui packages):

```tsx
build: {
  rollupOptions: {
    output: {
      manualChunks(id) {
        if (id.includes('node_modules')) {
          if (id.includes('katex') || id.includes('rehype-katex')) return 'vendor-katex';
          if (id.includes('react-markdown') || id.includes('remark-')) return 'vendor-markdown';
          if (id.includes('recharts') || id.includes('d3-')) return 'vendor-charts';
          if (id.includes('framer-motion')) return 'vendor-motion';
          if (id.includes('@radix-ui')) return 'vendor-radix';
          if (id.includes('react-dom') || id.includes('react-router')) return 'vendor-react';
          if (id.includes('@tanstack')) return 'vendor-query';
        }
      },
    },
  },
},
```

The function form avoids the fragility of listing every @radix-ui subpackage explicitly.

**Verification**:
1. `npm run build` — output should show named vendor chunks with sizes
2. Subsequent deploys with only app code changes should not invalidate vendor chunks
3. After Phase 3A is also applied: `vendor-katex` and `vendor-markdown` chunks should NOT load on initial page load (they're behind the chat lazy boundary). At the 2C stage alone, these chunks still load eagerly because `AIChat` → `ChatCore` → `MarkdownRenderer` is still an eager import chain until 3A makes it lazy.

---

## Phase 3: Lazy Chat UI (Medium-High Risk)

### 3A. Lazy-Load Chat UI Components (NOT ChatProvider)

**Files**:
- `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx`
- `frontend/packages/ui/src/components/chat/AIChat.tsx`
- `frontend/packages/ui/src/components/layout/ChatInterface.tsx`

**Problem**: Chat UI (AIChat modal, ChatInterface full-screen, ChatCore, MarkdownRenderer, KaTeX) loads on every page load even if the user never opens chat.

**Why ChatProvider must stay eager**: `useSharedChat()` is consumed by components that are always mounted in the dashboard shell:
- `ArtifactAwareAskAIButton` (ModernDashboardApp.tsx:96-97) — reads `artifactPanelOpen` to position the floating "Ask AI" button
- `ArtifactPanelConnected` (ArtifactPanelConnected.tsx:10) — reads `artifactPanelOpen`, `currentArtifact`, `closeArtifactPanel`, `sendMessage`

Removing `ChatProvider` from the shell would break these consumers. `ChatProvider` itself is lightweight (state + context, no heavy deps).

**Change**: Keep `ChatProvider` eager. Lazy-load the heavy chat UI components:

```tsx
// AIChat modal — lazy (only loads when user clicks "Ask AI" or presses Cmd+J)
const AIChat = React.lazy(() => import('../chat/AIChat'));

// ChatInterface — already lazy from Phase 2B (chat view)
```

Current call site (line 919-923):
```tsx
<AIChat
  isOpen={showAIChat}
  onClose={() => setShowAIChat(false)}
  onViewChange={(view) => setActiveView(view as Parameters<typeof setActiveView>[0])}
/>
```

Replace with conditionally-mounted lazy version preserving all props (isOpen, onClose, onViewChange):
```tsx
{/* AIChat modal — conditionally mounted, lazy loaded on first open */}
{showAIChat && (
  <Suspense fallback={null}>
    <AIChat
      isOpen={showAIChat}
      onClose={() => setShowAIChat(false)}
      onViewChange={(view) => setActiveView(view as Parameters<typeof setActiveView>[0])}
    />
  </Suspense>
)}
```

**Why conditional mount is required**: `React.lazy()` fetches the module as soon as the component is mounted in the tree, regardless of what the component renders internally. The current call site (line 919) renders `AIChat` unconditionally and relies on `AIChat` returning `null` when `!isOpen` (line 73). If we keep that pattern with React.lazy, the chunk loads immediately on dashboard mount — defeating the purpose. The conditional `showAIChat &&` ensures the chunk only loads when the user actually opens the modal (via click or Cmd+J).

**Trade-off**: When chat is closed via `onClose`, the lazy component unmounts. However, `ChatProvider` stays mounted in the shell, so chat state (messages, artifacts) persists across open/close cycles. The `AIChat` component itself is stateless — it reads from `useSharedChat()` context.

The `onViewChange` prop is required for the "Full View" button in the chat modal (modal-to-fullscreen handoff).

**Why this works for KaTeX/markdown**: `MarkdownRenderer` is only imported by `ChatCore.tsx` (line 173). `ChatCore` is only imported by `AIChat` and `ChatInterface`. Since both are now lazy-loaded, KaTeX + react-markdown + remark plugins automatically move to the lazy chat chunk. No changes needed to `MarkdownRenderer.tsx` itself.

**Verification**:
1. Build output — KaTeX and react-markdown should NOT be in the main chunk
2. Open chat modal — chat chunk loads, markdown renders correctly
3. Navigate to full-screen chat view — same chunk, no double load
4. `ArtifactAwareAskAIButton` positioning works without chat UI loaded
5. `ArtifactPanelConnected` works when artifact is received via chat
6. Chat conversation state persists between modal ↔ full-screen transitions (ChatProvider stays mounted)
7. Keyboard shortcut Cmd+J opens chat modal, lazy chunk loads on first use

### Error Handling for Lazy Chunks

All `React.lazy()` boundaries (Phases 2A, 2B, 3A) should be wrapped in an error boundary that handles chunk load failures gracefully (e.g., network error, deploy invalidating old chunks):

```tsx
// components/ui/ChunkErrorBoundary.tsx
class ChunkErrorBoundary extends React.Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  render() {
    if (this.state.error) {
      return (
        <div className="p-8 text-center">
          <p>Failed to load component. Please refresh the page.</p>
          <button onClick={() => window.location.reload()}>Refresh</button>
        </div>
      );
    }
    return this.props.children;
  }
}
```

Place this around each `Suspense` boundary.

---

## Phase 4: Cache & Startup Refinement (Higher Risk, Deferred)

### 4A. Defer Price Refresh After First Paint

**File**: `frontend/packages/connectors/src/providers/PortfolioInitializer.tsx`
**Problem**: Price refresh fires before children render, blocking first meaningful paint.

**Change**: Render children immediately from cached/initial portfolio data. Fire price refresh as a background task after mount.

**Dependency note**: `PortfolioInitializer` (line 108) both establishes `currentPortfolio` and refreshes prices. Only the refresh portion is safely deferrable — the portfolio establishment must complete before children can render.

**Risk**: Medium — users may briefly see stale prices. Need a "refreshing prices..." indicator.

### 4B. Visibility-Aware Refetching

**Files**: Various hooks with polling intervals
**Problem**: Queries continue refetching on a fixed schedule even when the view they serve isn't visible.

**Change**: Add `enabled: isViewActive` to hooks that are view-specific.

**Dependency note**: `useDataSourceScheduler` (scheduler.ts:14) globally prefetches `positions`, `risk-score`, `risk-analysis`, `risk-profile`, and `performance` on portfolio load. View-level `enabled` flags don't affect these scheduler-driven prefetches. For full visibility-aware behavior, the scheduler itself would need to be scope-aware, which is a larger change.

**Risk**: Low for view-specific hooks, medium for scheduler changes.

### 4C. Cache Layer Audit

**Files**: `PortfolioCacheService.ts`, `UnifiedAdapterCache.ts`
**Problem**: Multiple overlapping cache layers add invalidation complexity and memory overhead.

**Change**: Audit which layers are still needed after the `useDataSource` migration. Document findings before implementation.

**Risk**: High — cache behavior is distributed across many paths. Requires careful dependency mapping.

---

## Implementation Order

```
Phase 1 (1A + 1B) → Phase 2 (2A → 2B → 2C) → Phase 3 (3A) → Phase 4 (deferred)
```

**Rationale**:
- **Phase 1 first**: Zero risk, immediate CPU/render savings + correctness fix for market status
- **Phase 2A first within Phase 2**: Route-level split creates the biggest single boundary (everything behind auth). This is a prerequisite for 2C to be effective
- **Phase 2B second**: View-level splits within the dashboard shell — must happen before 2C so manualChunks can optimize chunk grouping
- **Phase 2C last in Phase 2**: Vendor chunk grouping — only useful after dynamic import boundaries exist
- **Phase 3 after Phase 2**: Lazy chat UI naturally moves KaTeX/markdown to lazy chunks without touching MarkdownRenderer
- **Phase 4 deferred**: Higher risk, requires investigation, lower marginal impact after Phases 1-3

## Verification Strategy

### Per-Phase

| Phase | Verification |
|-------|-------------|
| 1A | React Profiler: 0 idle re-renders; market status updates on open/close transitions |
| 1B | Network tab: no requests while tab hidden; polling resumes on tab return |
| 2A | ModernDashboardApp chunk loads only after auth; AnalystApp only on `/analyst` |
| 2B | Default `score` view: no flash; non-default views trigger chunk loads; no double skeleton |
| 2C | Build output shows named vendor chunks; vendor hashes stable across app-only changes |
| 3A | KaTeX/markdown not in main chunk; chat modal lazy-loads; artifact button works without chat loaded |

### End-to-End

After all phases:
1. **Lighthouse**: Compare FCP, LCP, TTI, Total Blocking Time against baseline
2. **Build size**: Compare total JS size and per-chunk breakdown against baseline
3. **Network waterfall**: First 5 seconds should show fewer/smaller requests
4. **Manual test**: Navigate all views, open chat modal, use full-screen chat, verify artifact panel, verify keyboard shortcuts (Cmd+J for chat, Cmd+1-8 for views)
5. **Error handling**: Kill the dev server after loading, switch views — error boundary should show refresh prompt
6. **Hidden tab**: Verify no polling while hidden, polling resumes on return

## Files to Modify

| Phase | File | Changes |
|-------|------|---------|
| 1A | `ModernDashboardApp.tsx` | Remove `currentTime` + `marketStatus` state, render `<LiveClock />` |
| 1A | New: `components/dashboard/LiveClock.tsx` | Isolated clock + market status (minute-gated) |
| 1B | `usePendingUpdates.ts` | `refetchIntervalInBackground: false` |
| 2A | `AppOrchestratorModern.tsx` | React.lazy() for ModernDashboardApp + AnalystApp (named export via `.then()`) + Suspense at two render sites |
| 2B | `ModernDashboardApp.tsx` | React.lazy() for 5 non-score containers + ChatInterface + settings; remove synthetic 400ms isLoading; add Suspense |
| 2B | New: `components/dashboard/ViewTransitionSkeleton.tsx` | Skeleton fallback replacing synthetic delay |
| 2C | `vite.config.ts` | Add `rollupOptions.output.manualChunks` (function form) |
| 3A | `ModernDashboardApp.tsx` | React.lazy() for AIChat; Suspense around modal |
| 3A | New: `components/ui/ChunkErrorBoundary.tsx` | Error boundary for lazy chunk failures |

## Estimated Bundle Impact

### After Phase 2A only

The unauthenticated page (LandingApp + AuthTransition) becomes a small initial chunk. The full `ModernDashboardApp` chunk (still containing all 10 containers, chat, KaTeX, etc.) loads only after authentication succeeds. This defers ~1.5MB of JS until the user is actually authenticated.

### After Phase 2A + 2B

The `ModernDashboardApp` chunk shrinks — it now eagerly contains only:
- 5 `score`-view containers (PortfolioOverview, AssetAllocation, RiskAnalysis, Performance, RiskMetrics)
- Dashboard shell, sidebar, header
- ChatProvider (lightweight — state + context only)
- AIChat + ChatInterface + ChatCore + MarkdownRenderer + KaTeX (still eager at this point)

5 non-default view containers + settings/account connections are deferred to lazy chunks.

### After Phase 2A + 2B + 3A

Chat UI (AIChat, ChatInterface, ChatCore) becomes lazy, which pulls MarkdownRenderer + KaTeX + react-markdown into the lazy chat chunk automatically. The `ModernDashboardApp` chunk now only has the dashboard shell + 5 score-view containers + lightweight ChatProvider.

| Phase | What gets deferred | Estimated savings (deferred bytes) |
|-------|-------------------|-----------------------------------|
| 2A — Route split | Entire dashboard until after auth | ~1.5MB deferred to post-auth |
| 2B — View split | 5 non-default containers + settings | ~200-400KB deferred to view switch |
| 3A — Chat lazy | AIChat + ChatInterface + ChatCore + KaTeX + markdown | ~400KB deferred to chat open |
| 2C — Vendor chunks | None deferred, but stable vendor hashes improve cache hit rates across deploys | Caching benefit only |

**Note**: Total bytes transferred doesn't change — code splitting defers *when* bytes load, not *how many*. The win is faster initial paint and lower parse/execute cost on first load.

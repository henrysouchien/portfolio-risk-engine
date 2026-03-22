# Browser Back/Forward Button Support

## Context
Navigation is 100% Zustand state-driven (`activeView` in uiStore). Clicking the browser back button navigates out of the app entirely because no browser history entries are created for in-app view changes. Fix: sync Zustand view state with the browser History API using hash-based URLs.

## Approach: Hash-Based History Sync
Use `window.location.hash` (e.g., `#holdings`, `#scenarios/backtest`) because:
- Won't interfere with existing pathname checks in AppOrchestratorModern (`/plaid/success`, `/snaptrade/success`, `/analyst`)
- No server config needed, no full page reloads
- Lightweight — no React Router involvement

## Current Architecture
- **uiStore.ts** (`connectors/src/stores/uiStore.ts`): Zustand store with `activeView: ViewId` (12 values) + `activeTool: ScenarioToolId` (9 values)
- **`setActiveView(view)`**: Saves to localStorage, sets view, resets `activeTool` to `'landing'` when leaving scenarios
- **`setActiveTool(tool, context?)`**: Sets scenario sub-tool + optional context
- **ModernDashboardApp.tsx**: `switch(activeView)` renders components. Keyboard shortcuts Cmd+1-8. Redirect effects: `connections->score`, unsupported `trading->score`.
- **AnalystApp.tsx**: Same store, normalizes to 3-view subset (`chat|holdings|connections`), forces `'chat'` on mount.
- **ScenariosRouter.tsx**: Nested state machine using `activeTool` from same store. `defaultTool` effect applies tool on first render.
- **Two-step nav pattern**: Multiple call sites do `setActiveView('scenarios'); setActiveTool('hedge')` synchronously (FactorsContainer lines 19-20/24-25, AssetAllocationSummary lines 66-67, PortfolioEarningsCard lines 237-238).
- **`VALID_VIEW_IDS`** exists at line 112 but is not exported. No `VALID_TOOL_IDS` array exists.
- **Legacy views**: `strategies` renders `ScenariosRouter` (same as `scenarios`). `report` is unused.

## Files to Change

### 1. MODIFY: `frontend/packages/connectors/src/stores/uiStore.ts`
- Export existing `VALID_VIEW_IDS` array (add `export` keyword, line 112)
- Add + export `VALID_TOOL_IDS: ScenarioToolId[]` array
- Add + export `NAVIGABLE_VIEW_IDS` — subset of `VALID_VIEW_IDS` excluding legacy-only targets (`strategies`, `report`). Note: `connections` IS included because it's a valid AnalystApp view; the dashboard redirect is handled via `replaceState`.
- Modify `getStoredActiveView()` to also check `window.location.hash` — if hash is present and valid, use it instead of localStorage. This runs synchronously at store creation time, before any React render, which avoids the AnalystApp race condition (Codex issue #1).

```typescript
// At store creation time — no React effects needed for initial hash
function getStoredActiveView(): ViewId {
  try {
    // Hash takes priority over localStorage
    const hash = window.location.hash.replace('#', '');
    const segment = hash.split('/')[0];
    if (segment && NAVIGABLE_VIEW_IDS.includes(segment as ViewId)) {
      return segment as ViewId;  // connections valid here (AnalystApp uses it)
    }
    const stored = window.localStorage.getItem('activeView');
    if (stored && VALID_VIEW_IDS.includes(stored as ViewId)) return stored as ViewId;
  } catch {}
  return 'score';
}

// Also add: initial activeTool from hash
function getStoredActiveTool(): ScenarioToolId {
  try {
    const hash = window.location.hash.replace('#', '');
    const parts = hash.split('/');
    if (parts[0] === 'scenarios' && parts[1] && VALID_TOOL_IDS.includes(parts[1] as ScenarioToolId)) {
      return parts[1] as ScenarioToolId;
    }
  } catch {}
  return 'landing';
}
```

This solves the AnalystApp race condition: the store is already initialized with the hash-derived view before any `useEffect` fires.

### 2. NEW: `frontend/packages/connectors/src/navigation/hashSync.ts`
Core sync module. Key design decisions addressing Codex feedback:

#### Hash Canonicalization (Codex issue #4)
`buildHash` canonicalizes legacy views:
- `strategies` -> `#scenarios` (legacy alias)
- `report` -> excluded from hash (unused legacy, never written to URL)
- `connections` -> `#connections` (valid AnalystApp view; dashboard redirect handled via `replaceState`)
- All other views map directly: `#holdings`, `#performance`, etc.

`parseHash` only accepts `NAVIGABLE_VIEW_IDS` — rejects `strategies`, `report` (legacy-only). `connections` IS accepted since it's a valid AnalystApp view.

#### Redirect-Safe Push vs Replace (Codex issue #2)
The store subscriber tracks the previous hash. On store change:
- If new hash === current `location.hash` -> **skip** (no-op dedup, Codex issue #5)
- If store change was triggered by `_navigatingFromHash` -> **skip** (circular guard)
- Otherwise -> **`pushState`**

Redirect effects in ModernDashboardApp (`connections->score`, unsupported `trading->score`) fire `setActiveView('score')`. The store subscriber detects these redirect patterns and uses `replaceState` instead of `pushState`, so the redirect target replaces the invalid hash entry rather than stacking on top. This prevents back-button loops: pressing back skips the redirect hash entirely.

Detection: the subscriber tracks `_prevActiveView`. If the previous view was `connections` (dashboard only — check with normalized pathname: `(window.location.pathname.replace(/\/+$/, '') || '/') !== '/analyst'`, matching AppOrchestratorModern's normalization at line 74) or `trading` (unsupported mode), and the new view is `score`, use `replaceState`.

Extract a shared helper `isAnalystMode()` that normalizes trailing slashes before comparison, matching AppOrchestratorModern's `const normalizedPath = currentPath.replace(/\/+$/, '') || '/'` pattern.

Note: `connections` IS a valid navigable hash (`/analyst#connections` works correctly). The redirect only applies in the dashboard context, detected by checking `window.location.pathname`.

#### Coalescing Fix (Codex issue #3)
Always clear `_pendingHash` in the microtask, even when suppressed:

```typescript
let _pendingHash: string | null = null;
let _navigatingFromHash = false;

function scheduleHashPush(hash: string, replace = false) {
  const isFirst = _pendingHash === null;
  _pendingHash = hash;
  if (isFirst) {
    queueMicrotask(() => {
      const pending = _pendingHash;
      _pendingHash = null;  // ALWAYS clear — prevents stuck state
      if (pending !== null && !_navigatingFromHash) {
        const current = window.location.hash || '#';
        if (pending !== current) {
          if (replace) {
            history.replaceState(null, '', pending);
          } else {
            history.pushState(null, '', pending);
          }
        }
      }
    });
  }
}
```

#### No-Op Dedup (Codex issue #5)
The subscriber compares the computed hash against `window.location.hash` before scheduling. Clicking the already-active nav item triggers `setActiveView` with the same view, the hash is unchanged, so no history entry is pushed.

#### Full Module API
- **`buildHash(view, tool?)`** — Constructs + canonicalizes hash string
- **`parseHash(hash)`** — Parses hash -> `{ view, tool? }` or `null`. Only accepts `NAVIGABLE_VIEW_IDS` + `VALID_TOOL_IDS`.
- **`initHashSync(store)`** — Subscribes to store changes, schedules `pushState`/`replaceState`. Returns unsubscribe fn.
- **`handlePopState(store)`** — Reads hash, sets `_navigatingFromHash=true`, updates store, resets flag. Used for both `popstate` (back/forward) and `hashchange` (manual URL bar edits) events.
- **`setInitialHash(store)`** — On startup: `replaceState` to set hash from current store state (store already initialized from hash in `getStoredActiveView`).

### 3. NEW: `frontend/packages/connectors/src/navigation/useHashSync.ts`
Thin React hook:

```typescript
export function useHashSync(): void {
  useEffect(() => {
    const store = useUIStore;
    setInitialHash(store);  // replaceState to reflect current view
    const unsubscribe = initHashSync(store);
    const onPopState = () => handlePopState(store);
    const onHashChange = () => handlePopState(store);  // manual URL bar edits
    window.addEventListener('popstate', onPopState);
    window.addEventListener('hashchange', onHashChange);
    return () => {
      unsubscribe();
      window.removeEventListener('popstate', onPopState);
      window.removeEventListener('hashchange', onHashChange);
    };
  }, []);
}
```

Note: `applyInitialHash` is no longer needed — hash-to-store initialization happens synchronously in `getStoredActiveView()` at store creation time. The hook only needs `setInitialHash` (replaceState to ensure URL reflects state) + subscribe + popstate + hashchange listeners. `hashchange` fires when the user manually edits the hash in the URL bar (unlike `popstate` which only fires on back/forward). The `_navigatingFromHash` guard prevents both from causing circular updates. Since `pushState`/`replaceState` do NOT fire `hashchange`, the store subscriber won't trigger the `hashchange` listener.

### 4. NEW: `frontend/packages/connectors/src/navigation/index.ts`
Barrel export for `useHashSync`, `buildHash`, `parseHash`.

### 5. MODIFY: `frontend/packages/connectors/src/index.ts` (after line 62)
Add: `export { useHashSync } from './navigation';`

### 6. MODIFY: `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx`
Add one line: `useHashSync();` near top of component body.

### 7. MODIFY: `frontend/packages/ui/src/components/apps/AnalystApp.tsx`
- Add `useHashSync();` near top of component body
- Adjust mount-force effect (lines 93-95): only force `'chat'` if current `activeView` isn't already a valid analyst view. Since `getStoredActiveView()` now reads the hash synchronously, `activeView` will already be correct from the first render.

```typescript
// Before:
useEffect(() => {
  setActiveView('chat');
}, [setActiveView]);

// After:
useEffect(() => {
  const validAnalystViews: ViewId[] = ['chat', 'holdings', 'connections'];
  if (!validAnalystViews.includes(activeView)) {
    setActiveView('chat');
  }
}, []); // eslint-disable-line react-hooks/exhaustive-deps
```

This works because `activeView` is already hash-derived from the synchronous store init.

## View Canonicalization Table

| Store `activeView` | Hash written | `parseHash` accepts? | Notes |
|--------------------|--------------|-----------------------|-------|
| `score` | `#score` | Yes | Home view |
| `holdings` | `#holdings` | Yes | |
| `performance` | `#performance` | Yes | |
| `factors` | `#factors` | Yes | |
| `scenarios` (landing) | `#scenarios` | Yes | |
| `scenarios` + tool | `#scenarios/backtest` | Yes | Nested |
| `research` | `#research` | Yes | |
| `chat` | `#chat` | Yes | |
| `settings` | `#settings` | Yes | |
| `trading` | `#trading` | Yes | Mode-gated; redirect handled by replaceState |
| `connections` | `#connections` | Yes | Valid in AnalystApp; dashboard redirects via `replaceState` |
| `strategies` | `#scenarios` | No (canonicalized) | Legacy alias |
| `report` | *not written* | No | Unused legacy |

## Edge Cases
| Case | Handling |
|------|----------|
| Invalid hash (`#garbage`) | `parseHash` returns `null`; `getStoredActiveView()` ignores it, falls through to localStorage |
| `#connections` in dashboard URL | `parseHash` accepts it; dashboard redirect effect fires `setActiveView('score')` with `replaceState` |
| `#connections` in `/analyst` URL | Works correctly — `connections` is a valid AnalystApp view |
| `#strategies` in URL | `parseHash` rejects (not in `NAVIGABLE_VIEW_IDS`); falls through to localStorage |
| Dashboard redirect (`connections->score`) | Subscriber detects redirect from `connections` on non-analyst path, uses `replaceState`. No loop. |
| Back to `#trading` (unsupported) | ModernDashboardApp redirect effect fires `setActiveView('score')`, subscriber uses `replaceState` -> `#score` |
| AnalystApp init with hash | `getStoredActiveView()` reads hash synchronously at store creation. Mount effect only forces 'chat' if not already valid. No race. |
| `popstate` to `#performance` in AnalystApp | Store gets 'performance', AnalystApp normalizes to 'chat', subscriber replaces hash. One-time correction. |
| Page refresh | Hash present -> `getStoredActiveView()` reads it. No hash -> localStorage fallback. `setInitialHash` does `replaceState`. |
| `toolContext` not in URL | By design -- context is ephemeral, back-nav gets tool in default state |
| Same-view click (no-op) | Subscriber compares hash, skips if unchanged |
| Two-step nav coalescing | `queueMicrotask` batches; `_pendingHash` always cleared even if suppressed |
| ScenariosRouter `defaultTool` effect | Fires in separate effect tick after microtask; produces its own history entry (correct -- it's a distinct navigation) |

## Unit Tests: `frontend/packages/connectors/src/navigation/__tests__/hashSync.test.ts`

### `buildHash` tests
- `buildHash('holdings')` -> `'#holdings'`
- `buildHash('scenarios', 'landing')` -> `'#scenarios'`
- `buildHash('scenarios', 'backtest')` -> `'#scenarios/backtest'`
- `buildHash('score')` -> `'#score'`
- `buildHash('strategies')` -> `'#scenarios'` (canonicalization)
- `buildHash('connections')` -> `'#connections'` (valid for AnalystApp)

### `parseHash` tests
- `parseHash('#holdings')` -> `{ view: 'holdings' }`
- `parseHash('#scenarios/backtest')` -> `{ view: 'scenarios', tool: 'backtest' }`
- `parseHash('#scenarios')` -> `{ view: 'scenarios' }`
- `parseHash('')` -> `null`
- `parseHash('#garbage')` -> `null`
- `parseHash('#connections')` -> `{ view: 'connections' }` (valid for AnalystApp)
- `parseHash('#strategies')` -> `null` (legacy, excluded)
- `parseHash('#scenarios/invalid')` -> `{ view: 'scenarios' }` (invalid tool ignored)

### Store sync tests (mock `history.pushState`/`replaceState`)
- Store change -> `pushState` called with correct hash
- Same-view set -> no `pushState` (no-op dedup)
- `popstate` -> store updated, no `pushState` (circular guard)
- Two-step coalescing: `setActiveView('scenarios') + setActiveTool('hedge')` -> single `pushState('#scenarios/hedge')`
- `_pendingHash` cleared even when `_navigatingFromHash` is true (no stuck state)
- Redirect view -> `replaceState` used instead of `pushState`

### `getStoredActiveView` tests
- Hash `#holdings` -> returns `'holdings'` (overrides localStorage)
- Hash `#scenarios/backtest` -> returns `'scenarios'`
- Hash `#garbage` -> falls through to localStorage
- No hash -> falls through to localStorage
- Hash `#connections` -> returns `'connections'` (valid navigable view)

## Verification
1. `npm run build` in frontend -- no TS errors
2. `npm test` -- existing + new unit tests pass
3. Manual QA:
   - Navigate: score -> holdings -> performance -> back -> back (should retrace)
   - Scenario sub-nav: score -> scenarios -> backtest -> back (-> scenarios landing) -> back (-> score)
   - Two-step nav: click "Simulate Hedge" on Factors -> should land on `#scenarios/hedge` (single entry)
   - Page refresh on `#holdings` -> should restore holdings view
   - Direct URL entry `localhost:3000/#research` -> should open research view
   - Forward button after back -> should work
   - AnalystApp (`/analyst#holdings`) -> should open holdings, not force chat
   - Click same nav item twice -> no duplicate history entry
   - Type `#connections` in dashboard URL bar -> redirects to `#score` via replaceState (not loop)
   - `/analyst#connections` -> opens connections view correctly
   - Manual hash edit in URL bar -> view updates (hashchange listener)

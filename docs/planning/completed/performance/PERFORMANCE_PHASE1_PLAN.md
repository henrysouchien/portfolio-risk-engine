# Performance Phase 1 — Low-Risk, High-Leverage Wins
**Status:** DONE

**Source:** `PERFORMANCE_AUDIT_2026-03-09.md` Phase 1 items + one Phase 3 quick-win
**Goal:** Fastest user-visible perf gains with minimal regression risk
**Constraint:** Behavior-preserving. No core logic changes.
**Review:** v4 — all Codex review findings addressed (v1→v2→v3→v4)

---

## Step 1: Isolate Dashboard Clock (Trivial)

**Problem:** `ModernDashboardApp` owns `currentTime` state (line 170) and calls `setCurrentTime(new Date())` every 1000ms via `requestAnimationFrame` + `setTimeout` (lines 177-188). This forces the entire dashboard shell (and all unmemoized children) to reconcile once per second.

**File:** `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx`

**Fix:**
- Extract clock into `<LiveClock />` component that owns its own `useState` + interval
- Remove `currentTime` / `setCurrentTime` from `ModernDashboardApp`
- Clock rerenders itself; parent shell stays stable
- Since the UI only renders hour:minute (line 611), use a **60-second interval** instead of 1s — update only when the minute changes

**Risk:** Very low. Pure render isolation.
**Test:** Verify clock displays correctly. Confirm parent doesn't rerender on clock tick (React DevTools profiler).

---

## Step 2: Reduce Frontend Logging in Hot Paths

**Problem:** 570 `frontendLogger` call sites. Critical hot spots:
1. `AppOrchestratorModern.tsx` (lines 80-90): logs full state object on **every render cycle**
2. `APIService.ts` (lines 289-317): **triple+ logging** per HTTP request — `network.request()` (line 289), `logAdapter()` for POST bodies (line 291), `network.response()` (line 306), plus a second `logAdapter()` on completion (line 307)
3. **Service wrapper logs**: Modular services like `RiskAnalysisService.ts` (lines 214, 239) add their own `logAdapter()` calls on top of APIService logging — multiplying log volume per request
4. Adapter transformations: up to 5 log calls per adapter invocation (`transformStart`, validation, structure debug, success/error)

**Existing production gate:** The filter at frontendLogger.ts:770-773 checks `logData.data.duration_ms < 2000` for non-error `network` logs. However, `network.response()` (line 606) stores the timing as `responseTime`, not `duration_ms` — so the field lookup always returns `undefined`, the `< 2000` check fails, and **all non-error network logs are effectively filtered out today** (accidental total suppression, not selective). Additionally, `logAdapter()` calls are category `adapter`, not `network`, so they bypass this filter entirely and always ship.

**Prior work (commits `4d8ca07e`, `5429d81e`):** Logger already batches into single POST payloads (55→11 requests, Phase 1 item 1A). Production network log throttle added (Phase 2 item 2D — filters non-error network logs <2000ms). These are done. What remains is the per-request log multiplier and hot-path volume problems below.

**Batching behavior (actual):** 200ms debounce after the last queued log, then drains in chunks of 10 via `processQueue()` (frontendLogger.ts:783-836). Not "every 200ms or at 10 entries" — it's debounce-then-drain.

**Files:**
- `frontend/packages/ui/src/router/AppOrchestratorModern.tsx`
- `frontend/packages/chassis/src/services/APIService.ts`
- `frontend/packages/chassis/src/services/RiskAnalysisService.ts` (and other modular services)
- `frontend/packages/chassis/src/services/frontendLogger.ts`

**Fix:**
- **2a:** Gate `AppOrchestratorModern` state logging to only fire on **state transitions** (value changed), not every render. Use a ref to track previous state.
- **2b:** Consolidate APIService to one log entry per request (combine request + response into single `network.roundtrip` event on completion, using `duration_ms` as the timing field to align with the production gate). Remove the separate `logAdapter()` calls for non-error cases. Also remove redundant `logAdapter()` calls in service wrappers (`RiskAnalysisService`, etc.) that duplicate what APIService already logs.
- **2c:** Increase batch debounce from 200ms → 2000ms in production (batching infra already in place from `4d8ca07e`). Keep 200ms in dev. Increase drain chunk size from 10 → 25.
- **2d:** Fix the production filter (line 770): the current `duration_ms` lookup is a no-op because `network.response()` stores timing as `responseTime`. Either rename to `duration_ms` in the roundtrip event (preferred — aligns with the gate) or update the gate to check `responseTime`. Then extend the filter to also cover `adapter` category non-error logs, not just `network`. Add env override `VITE_LOG_LEVEL=debug` to restore verbose logging when needed.

**Risk:** Low for product behavior. Medium operationally (mitigated by env override and preserved error shipping).
**Test:** Verify error logs still ship. Verify network request count drops. Measure `/api/log-frontend` call frequency before/after.

---

## Step 3: Implement APIService In-Flight Request Deduplication

**Problem:** `APIService.ts` line 258:
```typescript
const requestKey = `${options.method || 'GET'}:${endpoint}:${Date.now()}`;
```
Two issues:
1. `Date.now()` makes every key unique — dedup keys are always distinct
2. `pendingRequests` Map is **written to** (line 324) and **deleted from** (line 320), but **never read/checked** before executing a request — deduplication is entirely unimplemented, not just broken

**Impact context:** Most dashboard data fetches already go through TanStack Query (`useDataSource` → `useQuery`), which provides its own dedup. The APIService dedupe gap primarily affects direct `api.request()` calls outside React Query (mutations, auth, manual fetches).

**File:** `frontend/packages/chassis/src/services/APIService.ts`

**Fix:**
- **Dedupe GET only** — never dedupe POST/PUT/DELETE (suppressing mutations is dangerous). HEAD is not supported today (`request()` always calls `response.json()` at line 301), so exclude it from scope.
- Remove `Date.now()` from the key. Key on `GET:${endpoint}`
- Before creating a new request promise, check `pendingRequests.has(requestKey)` and return the existing promise if found
- Clear entry in `finally` block (already done at line 320)
- Leave POST/PUT/DELETE requests un-deduped (they already clean up via `finally`)

**Risk:** Medium. Must verify no GET endpoints have side effects that require duplicate calls. Safe because TanStack Query already dedupes most reads — this is a safety net for the remaining direct calls.
**Test:** Mount two components that call the same GET endpoint simultaneously via direct `api.request()`. Verify single network request. Verify POSTs are never coalesced.

---

## Step 4: Defer Price Refresh After First Paint

**Problem:** `PortfolioInitializer.tsx` blocks rendering while:
1. Fetching default portfolio (`GET /api/portfolios/CURRENT_PORTFOLIO`)
2. Refreshing prices (`POST /api/portfolio/refresh-prices`) — lines 137-150
3. Only then renders children (line 160+)

Users stare at a spinner while prices refresh, even though stale-by-minutes data is perfectly usable.

**File:** `frontend/packages/connectors/src/providers/PortfolioInitializer.tsx`

**Fix:**
- Render children immediately after step 1 (portfolio fetch) completes
- Fire price refresh as a **background mutation** (not blocking the query)
- On refresh completion, update the **Zustand portfolio store** via `PortfolioRepository.add()` (not just React Query invalidation — the active portfolio is store-backed, and downstream hooks/prefetch depend on the store)
- Invalidate dependent TanStack queries after store update so mounted components pick up fresh data
- Add a subtle "refreshing prices..." indicator instead of blocking spinner

**Risk:** Low. Users see slightly stale prices for 1-2 seconds during refresh. Data freshness preserved once refresh completes.
**Test:** Measure time-to-interactive before/after. Verify prices update in all mounted components after background refresh. Verify error in refresh doesn't break the dashboard. Verify prefetch scheduler still fires correctly after store update.

---

## Step 5: Lazy-Mount Below-the-Fold Score View Panels

**Problem (revised from v1):** The original plan proposed reducing eager prefetch from 6→2 sources. Codex review found this is counterproductive because:
1. `loading.strategy` exists as a valid descriptor field (used by several catalog entries) but `useDataSource()` fetches on mount regardless of strategy — it does not gate fetching on `loading.strategy: 'lazy'`
2. Removing prefetch would just move fetches from scheduler (dependency-ordered) to component mount (uncoordinated waterfall) — same requests, worse ordering

**Score view container → data dependency mapping (verified against current code):**
- `PortfolioOverviewContainer` → catalog sources: `portfolio-summary`, `performance`, `smart-alerts`, `market-intelligence`, `metric-insights` (via useDataSource hooks) + standalone `useQuery`: `ai-recommendations` (useAIRecommendations — direct useQuery, not a catalog/scheduler source)
- `AssetAllocationContainer` → catalog sources: `risk-analysis`, `allocation` (useRiskAnalysis, useTargetAllocation)
- `RiskAnalysisModernContainer` → catalog sources: `risk-analysis`, `risk-score`, `hedging-recommendations` (useRiskAnalysis, useRiskScore, useHedgingRecommendations)
- `PerformanceViewContainer` → catalog sources: `performance` (usePerformance)
- `RiskMetricsContainer` → catalog sources: `risk-analysis` (useRiskAnalysis)

**Scheduler prefetch scope:** The scheduler only prefetches sources with `loading.strategy: 'eager'` (scheduler.ts:96). Currently 6 eager sources: `positions`, `risk-score`, `risk-analysis`, `risk-profile`, `performance`, `portfolio-summary`. Other sources consumed by the score view (`smart-alerts`, `market-intelligence`, `metric-insights`, `hedging-recommendations`, `allocation`, `ai-recommendations`) are **not prefetched** — they fetch on component mount. Note: `risk-profile` is eagerly prefetched but **not consumed** by any score view container.

**The real bottleneck is that the score view renders 5 heavy containers simultaneously**, all above and below the fold. The benefit of lazy-mounting is **reduced initial React tree size and deferred hook execution** (fewer concurrent queries, less JS work), not fewer total requests over the session.

**Files:**
- `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx` (score view at line 402)

**Fix:**
- Keep the prefetch scheduler as-is (it correctly pre-warms cache in dependency order)
- In the score view's `case 'score'` block (line 402), wrap below-the-fold containers in a **lazy visibility boundary**:
  - Above-the-fold (render immediately): `PortfolioOverviewContainer`, `AssetAllocationContainer`
  - Below-the-fold (lazy-mount on scroll into viewport): `RiskAnalysisModernContainer`, `PerformanceViewContainer`, `RiskMetricsContainer`
- Use `IntersectionObserver` (or a lightweight `<LazyMount />` wrapper) to defer mounting until the container's placeholder scrolls into view
- Prefetch warms cache for eager sources (`risk-analysis`, `risk-score`, `performance`), so when below-fold panels mount those queries get instant cache hits. Non-eager sources consumed by below-fold panels (`hedging-recommendations`) will fetch on mount as they do today — lazy-mounting just defers that fetch until scroll

**Risk:** Low-medium. Below-fold panels show a brief skeleton/placeholder until scrolled into view. If viewport is tall enough to show everything, all panels mount immediately anyway.
**Expected impact:** Reduced initial React tree size (3 fewer heavy subtrees on first render), deferred hook execution for both eager-cached and non-eager sources, smoother time-to-interactive. This is primarily a **render cost** optimization — it defers JS execution and reduces concurrent query pressure, not total request count.
**Test:** On a standard viewport, verify above-fold panels render instantly. Scroll down — verify below-fold panels mount and display cached data without flicker. Profile: confirm reduced initial React tree size and lower JS execution time on cold load.

---

## Step 6: Lazy-Mount Chat Provider

**Problem:** `ChatProvider` wraps the entire app tree in `ModernDashboardApp.tsx` (line 558) and initializes `usePortfolioChat()` globally on mount — even if the user never opens chat.

**Complication:** Two components **outside** the chat panel consume chat context:
- `ArtifactAwareAskAIButton` (line 96): reads `artifactPanelOpen` to position the floating button
- `ArtifactPanelConnected` (line 925): renders the artifact slide-out panel
- `AnalystApp.tsx` (line 133): has the same global `ChatProvider` wrap

These must continue to work even with lazy chat initialization.

**Files:**
- `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx`
- `frontend/packages/ui/src/components/apps/AnalystApp.tsx`
- `frontend/packages/ui/src/components/chat/ChatContext.tsx`

**Fix:**
- Replace eager `ChatProvider` with a **`LazyChatProvider`** that:
  1. Provides a **full no-op stub** matching the `ChatContextType` shape (`ReturnType<typeof usePortfolioChat>`) — not just `{ artifactPanelOpen: false }`. All methods return no-ops, all state fields return safe defaults. This ensures `ArtifactPanelConnected` (which reads artifact methods) and `AIChat` (which reads chat state) don't crash before initialization.
  2. Exposes an `ensureInitialized()` method that triggers real `ChatProvider` mount. Called by: "Ask AI" button click, `⌘J` shortcut handler, or any component that needs active chat.
  3. On first `ensureInitialized()` call, mounts the real `ChatProvider` and runs `usePortfolioChat()`. Once mounted, **stays mounted** for the rest of the session (preserves message history across open/close/modal↔fullscreen transitions).
- `ArtifactAwareAskAIButton` gets `artifactPanelOpen: false` from stub until chat initializes — button positions correctly at default offset
- `ArtifactPanelConnected` gets no-op artifact methods from stub — renders nothing until chat is initialized
- **`AnalystApp.tsx` exception:** AnalystApp defaults straight into chat view (line 93), so it must **keep eager `ChatProvider`** initialization. The lazy pattern applies only to `ModernDashboardApp`.

**Risk:** Low-medium. Must ensure:
- Chat state persists across modal↔fullscreen transitions (guaranteed by "mount once, stay mounted")
- Artifact panel still works after chat initializes
- No flash of incorrect button positioning on chat init

**Test:** Cold load dashboard — verify no `usePortfolioChat` network activity. Click "Ask AI" — verify chat initializes and works. Close and reopen — verify history preserved. Verify artifact panel opens correctly after chat init.

---

## Step 7: Throttle Session `last_accessed` Writes

**Problem:** `PostgresSessionStore.get_session()` in `app_platform/auth/stores.py` (lines 31-64) does SELECT + UPDATE `last_accessed` + COMMIT on **every authenticated request**. No throttle. 50 API calls/min = 50 unnecessary writes.

**File:** `app_platform/auth/stores.py`

**Fix:**
- Keep the SELECT (still need to validate session on every request)
- Replace the unconditional UPDATE (lines 49-56) with a **conditional SQL UPDATE**:
  ```sql
  UPDATE user_sessions
  SET last_accessed = %s
  WHERE session_id = %s AND last_accessed < %s
  ```
  where the threshold is `now - 5 minutes`
- This makes throttling DB-side (works correctly under multi-worker / multi-process), avoids in-memory state that needs cleanup or per-worker coordination
- The UPDATE becomes a no-op (0 rows affected) when `last_accessed` is already recent — no write amplification

**Risk:** Low. Session expiry granularity changes from per-request to ~5 minutes. Acceptable for session timeout semantics (typically 24h+). No in-memory state to leak or coordinate across workers.
**Test:** Verify session still validates. Verify `last_accessed` updates at most once per 5 min window. Verify expired sessions still get rejected. Load test: confirm write volume drops proportionally.

---

## Step 8: Move Cache Check Before Classification (Quick-Win from Phase 3)

**Problem:** `PortfolioService.analyze_portfolio()` in `services/portfolio_service.py` does:
1. Line 212: `get_full_classification(tickers, portfolio_data)` — **expensive**
2. Line 240-243: Build cache key from `portfolio_data.get_cache_key()` + `risk_limits_data.get_cache_key()` + `normalized_period`
3. Line 247-248: Check `if cache_key in self._cache` — too late, already paid classification cost

Cache hits waste 100% of classification work. **Confirmed:** `get_cache_key()` (data_objects.py:972) does NOT depend on classification output.

**Gotcha:** The current cache-hit path (lines 250-262) backfills **three fields** into `cached_result.analysis_metadata` if missing:
1. `asset_classes` (line 254)
2. `security_types` (line 257)
3. `target_allocation` (line 260)

This handles cache entries created before these enrichments were added. Additionally, there is a **Redis L2 cache** path (line 269) that returns early — it also needs the same backfill treatment.

**File:** `services/portfolio_service.py`

**Fix:**
- Move cache key construction (lines 240-243) and cache lookup (lines 246-269) **before** the `get_full_classification()` call (line 212)
- **L1 hit (in-memory):** If cached result is missing classification/allocation metadata, run classification **only then** to backfill all three fields (`asset_classes`, `security_types`, `target_allocation`). This is the lazy-backfill path for old cache entries.
- **L2 hit (Redis):** Same backfill logic applies after deserializing the Redis result. Run classification only if metadata fields are missing.
- On cache miss, proceed with classification + full analysis as before
- Over time, as cache entries rotate, all entries will include metadata and backfill becomes a no-op

**Risk:** Low-medium. Cache key confirmed independent of classification. Both L1 and L2 cache paths must preserve backfill semantics.
**Test:** Run `analyze_portfolio` twice with same inputs. Verify second call skips classification entirely (add timing log). Verify cached result contains `asset_classes`, `security_types`, and `target_allocation` in metadata. Verify Redis L2 path also works correctly.

---

## Execution Order

| Step | Item | Effort | Impact |
|------|------|--------|--------|
| 1 | Clock isolation | 15 min | Medium (idle CPU) |
| 4 | Defer price refresh | 1 hr | High (time-to-interactive) |
| 2 | Frontend logging reduction | 1-2 hr | High (CPU + network) |
| 8 | Cache before classification | 30 min | High (backend latency) |
| 7 | Session write throttle | 30 min | Medium (DB write load) |
| 6 | Lazy-mount chat | 1-2 hr | Medium (startup cost) |
| 3 | Implement GET dedupe | 45 min | Medium (safety net for non-RQ calls) |
| 5 | Lazy-mount below-fold panels | 1-2 hr | Medium-High (initial render cost) |

**Rationale for reorder:** Steps 1 and 4 are the fastest wins with highest user-visible impact. Steps 2 and 8 are high-impact with straightforward implementation. Step 3 was demoted because TanStack Query already handles most dedup — this is a safety net. Step 5 is higher effort due to the LazyMount wrapper but addresses real render cost.

**Total estimated scope:** ~7 hours of implementation across 8 targeted changes.

## Verification

**Before (baseline):**
- Network requests in first 5s after login
- Time to first useful paint
- `/api/log-frontend` POST frequency
- Dashboard idle CPU (React DevTools profiler)
- `analyze_portfolio` warm-cache latency
- Initial React tree size (component count at first render)

**After (targets):**
- Time to interactive: improve by 1-3s (Steps 4, 5)
- Log POST frequency: drop by 80%+ (Step 2)
- Idle CPU: near-zero rerender at rest (Step 1)
- Warm-cache analysis: skip classification entirely (Step 8)
- Session DB writes: drop by ~99% under normal traffic (Step 7)
- Initial component tree: smaller by 3 heavy containers (Step 5)

## Changelog

- **v1:** Initial plan from audit findings
- **v2:** Incorporated Codex review (3 PASS, 3 CONCERN, 2 FAIL):
  - Step 1: Added minute-aligned timer optimization
  - Step 2: Added service wrapper logs (RiskAnalysisService etc.), fixed batching description, noted existing production network filter
  - Step 3: **Reworked** — dedupe was unimplemented not just broken; scoped to GET/HEAD only; demoted impact (TanStack Query already dedupes most reads)
  - Step 4: Added Zustand store update requirement (not just React Query invalidation)
  - Step 5: **Replaced** — original prefetch reduction was counterproductive (score view mounts all consumers anyway). New approach: lazy-mount below-fold panels with IntersectionObserver
  - Step 6: Added ArtifactAwareAskAIButton + ArtifactPanelConnected as external chat context consumers; redesigned as LazyChatProvider with stub context
  - Step 7: Replaced in-memory dict with conditional SQL UPDATE (DB-side throttle, multi-worker safe)
  - Step 8: Confirmed cache key independence; added metadata backfill preservation requirement
  - Reordered execution sequence for optimal impact-to-effort ratio
- **v3:** Addressed remaining 3 CONCERNs from Codex v2 review (5 PASS, 3 CONCERN):
  - Step 3: Narrowed to GET-only (HEAD not supported — `response.json()` at line 301)
  - Step 6: Full no-op stub matching `ChatContextType` shape; `ensureInitialized()` trigger; AnalystApp kept eager (defaults to chat view)
  - Step 8: Added `target_allocation` as third backfill field; addressed Redis L2 cache path backfill
- **v4:** Addressed final CONCERN from Codex v3 review (7 PASS, 1 CONCERN):
  - Step 2: Documented `responseTime` vs `duration_ms` field mismatch in production gate (accidental total suppression); fix plan now explicitly aligns field names in the consolidated roundtrip event
- **v5:** Addressed Step 5 FAIL from Codex sanity-check review (7 PASS, 1 FAIL):
  - Step 5: Added verified container→source mapping; noted `risk-profile` is prefetched but not consumed by score view; clarified this is a render cost optimization (deferred hook execution, smaller initial tree), not a network request reduction; narrowed expected impact description
- **v6:** Addressed Step 5 FAIL from Codex final review (7 PASS, 1 FAIL):
  - Step 5: Completed container→source mapping — added `smart-alerts`, `market-intelligence`, `metric-insights`, `ai-recommendations` (PortfolioOverviewContainer) and `allocation` (AssetAllocationContainer). Fixed `loading.strategy` wording — it IS a valid field, but `useDataSource()` fetches on mount regardless of strategy value
- **v7:** Addressed Step 5 FAIL from Codex v6 review (7 PASS, 1 FAIL):
  - Step 5: Distinguished catalog sources (useDataSource) from standalone useQuery hooks (ai-recommendations). Added scheduler prefetch scope section showing exactly which 6 sources are eager. Clarified cache warming applies only to eager sources; non-eager fetch on mount as today. Precision fix only — no strategy change

# Frontend Cleanup — Priority 1: Active Harmful Code

**Status:** ✅ COMPLETE (2026-03-04)
**Verified:** Typecheck passed + live tested in Chrome. All 4 items confirmed fixed.

## Context

The completed/FRONTEND_CLEANUP_AUDIT.md identified 4 P1 items — code that actively degrades UX by showing fake data or breaking functionality. Fixed before the redesign begins.

---

## P1-1. PortfolioOverview: Remove simulated market fluctuations

**File:** `frontend/packages/ui/src/components/portfolio/PortfolioOverview.tsx`

**Problem:** Lines 600-631 — a `useEffect` with `setInterval` applies `Math.random()` fluctuations to `animatedValues` every 2-5 seconds, corrupting real metric values after initial load.

**Fix:**
- Delete the streaming interval `useEffect` block (lines ~597-631)
- Delete the mount animation `useEffect` that also calls `setAnimatedValues` (lines ~575-589) — this staggered entrance animation sets animatedValues to rawValue on mount, but without the state it's unnecessary
- Remove `animatedValues` / `setAnimatedValues` state declaration
- Remove `lastMarketUpdate` / `setLastMarketUpdate` state (only used by deleted interval)
- At line 1359, `formatValue()` receives `animatedValues[metric.title]` — change call to just pass `metric.rawValue` directly. Simplify `formatValue` to not need the `animatedValue` parameter (or remove it entirely since it just reformats `value` with the animated number)
- Remove dead state that fed the interval: `realTimeEnabled` (line 351), `_lastMarketUpdate` (line 352)
- **Keep** `streamingData` — used at line 1163 (`isLive` computation). Replace with `true` literal or remove the `isLive` concept (since we're removing fake streaming). Simplest: delete `streamingData` state, change line 1163 to `const isLive = false`
- **Keep** `marketMode` — used at line 1520 in render. Replace with `"live"` literal or remove the span. Simplest: delete `marketMode` state, replace `marketMode.toUpperCase()` at line 1520 with `"LIVE"` literal

---

## P1-2. PortfolioOverview: Wire real refresh handler

**File:** `frontend/packages/ui/src/components/portfolio/PortfolioOverview.tsx`

**Problem:** Lines 637-662 — `handleDataRefresh` does a fake `setTimeout(1500ms)` and injects a raw DOM toast. Never calls `onRefresh?.()`.

**Fix:**
- **Add `onRefresh` to destructuring** at line 332-338. Currently missing — props interface has it (line 327) but it's not destructured in the function args.
- Replace body of `handleDataRefresh` with:
  ```typescript
  const handleDataRefresh = useCallback(() => {
    onRefresh?.()
  }, [onRefresh])
  ```
- Delete DOM toast injection at lines 647-656
- **Also delete** second DOM toast injection at line 2264-2273 (settings save toast) — same raw DOM anti-pattern
- Button at line 1015 already calls `handleDataRefresh` — no change needed

---

## P1-3. PerformanceView: Fix hardcoded "2024" in tooltip

**File:** `frontend/packages/ui/src/components/portfolio/PerformanceView.tsx`

**Problem:** Line 1405 — `{month.month} 2024 Analysis` always shows 2024.

**Fix:** The `month` object has `date` field (format `"YYYY-MM"` from view's own computation at line 454, e.g. `"2025-03"`). Extract year:
```typescript
<div className="font-semibold">{month.month} {month.date?.split('-')[0] ?? ''} Analysis</div>
```
Note: `date` may also be `"YYYY-MM-DD"` if coming through adapter path. `split('-')[0]` handles both formats correctly.

---

## P1-4. PerformanceView: Remove unsupported period selector options

**File:** `frontend/packages/ui/src/components/portfolio/PerformanceView.tsx`

**Problem:** Lines 688-692 — Period selector offers 6M, 3Y, 5Y, MAX but the adapter only provides `1D`, `1W`, `1M`, `1Y` period keys (and `1D`/`1W` are hardcoded to 0). `3M` and `YTD` are also not in the adapter — they fall through to 0 via container default.

**Fix:**
- Remove `<SelectItem>` entries for `6M`, `3Y`, `5Y`, `MAX`
- Keep `1M` and `1Y` (have real data from adapter)
- Keep `3M` but note it currently falls through to 0 (same as removing it, but leaving it allows future backend support)
- **Alternative (simpler):** Only show `1M` and `1Y` since those are the only two with real data. Default `selectedPeriod` from `"1Y"` stays correct.
- Final set: `1M`, `1Y` — both have real data. Remove `3M` too since it's zeros.

---

## Files Modified

| File | Changes |
|------|---------|
| `PortfolioOverview.tsx` | Remove streaming interval + mount animation + fake refresh + dead state + DOM toasts + add onRefresh destructuring |
| `PerformanceView.tsx` | Fix year in tooltip (1 line), trim period selector to `1M`, `1Y` |

## Verification

1. `cd frontend && pnpm typecheck` — must pass
2. Live test in Chrome:
   - Portfolio Overview: metric values stable (no random drift), refresh button triggers real data reload
   - Performance View: monthly tooltip shows correct year, period selector only shows supported periods (1M, 1Y)

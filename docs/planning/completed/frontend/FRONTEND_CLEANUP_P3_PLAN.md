# Frontend Cleanup P3: Remove Inert Buttons & Dead UI

**Date:** 2026-03-04
**Status:** ✅ COMPLETE (2026-03-04, commits `b99dc188` + `396da1c3`). P3-5 reclassified as not-a-bug.
**Source:** `completed/FRONTEND_CLEANUP_AUDIT.md` Priority 3 items

---

## Approach

Delete buttons, dropdown items, and input controls that have no event handlers. These give users the impression of functionality that doesn't exist. For P3-5, the hardcoded "BUY" is actually correct (trade preview is always an "add position" flow) — reclassify as not-a-bug.

---

## P3-1. PortfolioOverview: Inert buttons (4 groups)

**File:** `frontend/packages/ui/src/components/portfolio/PortfolioOverview.tsx`

### P3-1a. Metric card dropdown menu (lines 1210-1252)

**Problem:** DropdownMenu trigger (MoreVertical icon) opens a menu with 5 items (Detailed View, Historical Analysis, Set Alert, Correlation Analysis, Technical Signals) — none have onClick handlers.

**Fix:** Delete the entire `<DropdownMenu>` block (lines 1210-1252), including the trigger button. The adjacent "Professional quick actions" buttons (Eye with `handleMetricFocus`, Star) remain separate — they're in a different block.

Remove `MoreVertical` from the lucide-react import (line 171) — only used here. Keep other icons (`Eye`, `Bell`, `BarChart3`, `Layers`, `ScanLine`) that are used elsewhere.

Also remove `DropdownMenu`, `DropdownMenuContent`, `DropdownMenuItem`, `DropdownMenuSeparator`, `DropdownMenuTrigger` imports if they become unused after this deletion.

### P3-1b. Star favorite button (lines 1468-1474)

**Problem:** Star button in metric card quick actions — no onClick handler.

**Fix:** Delete the Star `<Button>` block (lines 1468-1474). The adjacent Eye button (lines 1457-1467) has `handleMetricFocus` and stays.

Also delete the institutional-only Layers button (lines 1475-1483) — also no onClick handler.

Remove `Star` from imports if unused after deletion.

### P3-1c. Smart Alerts "Action" button (lines 1034-1038)

**Problem:** `{alert.actionable && (<Button>Action</Button>)}` — no onClick.

**Fix:** Delete lines 1034-1038. The Dismiss button (lines 1040-1044) also has no onClick — delete it too. Keep the `<div className="flex items-center space-x-2">` wrapper only if it still wraps content; otherwise delete the whole action buttons div (lines 1032-1045).

### P3-1d. AI Recommendations "Implement" and "Learn More" buttons (lines 1618-1625)

**Problem:** Two buttons with no onClick handlers on each recommendation card.

**Fix:** Delete the `<div className="flex items-center space-x-2">` block (lines 1618-1625).

---

## P3-2. HoldingsView: Inert row actions + Export CSV

**File:** `frontend/packages/ui/src/components/portfolio/HoldingsView.tsx`

### P3-2a. Row action buttons (lines 881-900)

**Problem:** Eye and MoreVertical buttons per row — no onClick. Show on hover but do nothing.

**Fix:** Delete the entire actions `<td>` block (lines 881-900). Also remove the `actions` entry from the header column config array at line 662:
```typescript
// Remove this line:
{ key: "actions", label: "", width: "w-20" }
```
This ensures header and body columns stay aligned.

Check if `Eye` and `MoreVertical` imports become unused after deletion — remove if so.

### P3-2b. Header filter icon button (line 634)

**Problem:** Filter icon button in the header — no onClick handler.

**Fix:** Delete lines 634-636 (the `<Button>` wrapping the `<Filter>` icon). Remove `Filter` from imports if unused.

### P3-2c. Export CSV button (lines 926-928)

**Problem:** `<Button>Export CSV</Button>` — no onClick.

**Fix:** Delete lines 926-928.

---

## P3-3. ScenarioAnalysis: Inert Export/Details buttons

**File:** `frontend/packages/ui/src/components/portfolio/ScenarioAnalysis.tsx` lines 1474-1483

**Problem:** Export and Details buttons in the analysis results summary — no onClick.

**Fix:** Delete the `<div className="flex items-center space-x-2">` block (lines 1474-1483) containing both buttons.

Remove `Download` from imports if unused after deletion. `Eye` may be used elsewhere — check before removing.

---

## P3-4. StrategyBuilder: Inert controls (3 groups)

**File:** `frontend/packages/ui/src/components/portfolio/StrategyBuilder.tsx`

### P3-4a. Uncontrolled Strategy Rules card (lines 769-825)

**Problem:** Entire "Strategy Rules" card with 1 Select, 3 Inputs, 3 Switches — all uncontrolled, no onChange, state never read or persisted. Pure UI theater.

**Fix:** Delete the entire Strategy Rules `<Card>` block (lines 769-825).

Import cleanup: `Switch` is removable (only used in Strategy Rules). `Label`, `Select*`, `Input` are used elsewhere in the file — do NOT remove.

### P3-4b. Marketplace "View Details" button (line 981)

**Problem:** `<Button variant="outline">View Details</Button>` on each marketplace template card — no onClick handler.

**Fix:** Delete lines 981-983. The adjacent "Deploy" button (lines 984-999) has a real `onClick` and stays.

### P3-4c. Active Strategies "Configure" and "Pause" buttons (lines 1031-1038)

**Problem:** Configure and Pause buttons on each active strategy card — no onClick handlers.

**Fix:** Delete the `<div className="flex items-center space-x-2">` block (lines 1030-1039) containing both buttons.

Remove `Pause` and `Settings` from imports — both only used in blocks being deleted (P3-4a line 772 + P3-4c line 1032).

---

## P3-5. StockLookup: Trade side hardcoded "BUY" — NO CHANGE

**File:** `frontend/packages/ui/src/components/portfolio/StockLookup.tsx` line 1391

**Analysis:** `TradePreviewData` interface (line 192) has no `side` field. The trade preview is always a "what if I add this stock to my portfolio" flow — it's always a BUY. The hardcoded "BUY" is actually correct for this context.

**Decision:** No change needed. Reclassify as not-a-bug in the audit doc.

---

## Files Modified

| File | Changes |
|------|---------|
| `PortfolioOverview.tsx` | Delete dropdown menu (~42 lines), Star+Layers buttons (~16 lines), Action+Dismiss buttons (~12 lines), Implement/Learn More buttons (~8 lines). Clean unused imports. |
| `HoldingsView.tsx` | Delete actions column td (~20 lines) + header config entry, Filter button (~3 lines), Export CSV button (~3 lines). Clean unused imports. |
| `ScenarioAnalysis.tsx` | Delete Export/Details buttons (~10 lines). Clean unused imports. |
| `StrategyBuilder.tsx` | Delete Strategy Rules card (~57 lines), View Details button (~3 lines), Configure+Pause buttons (~9 lines). Remove `Switch`, `Pause`, `Settings` imports. |

## Verification

1. `cd frontend && pnpm typecheck` — must pass (no broken references after import cleanup)
2. Visual check: PortfolioOverview metric cards have no three-dot dropdown menu
3. Visual check: Holdings table has no empty actions column
4. Visual check: Strategy Builder has no Strategy Rules card
5. Visual check: No "Implement" / "Learn More" / "Action" / "Export" buttons that do nothing

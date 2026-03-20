# Market Intelligence — Collapse with Expand/Collapse

## Context
MarketIntelligenceBanner renders ALL events (currently 9) in a 2-column grid with no truncation, consuming ~700px of vertical space on the Overview. It pushes Top Holdings, Alerts, and everything below it far down the page. The component has no collapse logic.

## Codex Review Findings (Round 1)
- **Fixed:** Sorting dropped — just collapse, don't reorder (avoids product decision, keeps event identity stable)
- **Fixed:** key={index} preserved since no reordering occurs
- **Fixed:** Missing Button import added
- **Fixed:** useMemo dropped — inline slice is sufficient for 9 items
- **Fixed:** Data refresh — add `portfolioId` prop to PortfolioOverview, pass `currentPortfolio?.id` from container, use `key={portfolioId}` on `<MarketIntelligenceBanner>`. Forces remount on portfolio switch (resetting useState). No useEffect needed — avoids false collapse on background refetch while guaranteeing reset on actual portfolio change. Uses stable portfolio identity, not display name
- **Accepted:** COLLAPSED_COUNT=4 means 4 rows on mobile (grid-cols-1) — still better than 9, and mobile users expect to scroll
- **Deferred:** Component tests (separate task)

## Plan

**File:** `frontend/packages/ui/src/components/portfolio/overview/MarketIntelligenceBanner.tsx`

**Changes:**

1. **Add `key` in parent:** In `frontend/packages/ui/src/components/portfolio/PortfolioOverview.tsx` (line ~95), the `<MarketIntelligenceBanner>` needs a stable remount key. Since `PortfolioOverview` only receives `portfolioDisplayName` (no portfolio ID in its props), pass a new `portfolioId` prop:
   - Add `portfolioId?: string` to `PortfolioOverviewProps` in `overview/types.ts`
   - Pass `portfolioId={currentPortfolio?.id}` from `frontend/packages/ui/src/components/dashboard/views/modern/PortfolioOverviewContainer.tsx` (line ~171, where `currentPortfolio` is already available)
   - Use `key={portfolioId}` on `<MarketIntelligenceBanner>` in `PortfolioOverview.tsx`
2. **Add imports in MarketIntelligenceBanner:** `useState` from React; `Button` from `../../ui/button`
2. **Add collapse state:**
   ```tsx
   const COLLAPSED_COUNT = 4;
   const [expanded, setExpanded] = useState(false);

   const visibleEvents = expanded ? events : events.slice(0, COLLAPSED_COUNT);
   ```
   No useEffect reset — `key={portfolioId}` on parent forces remount on portfolio switch, which naturally resets useState.
3. **Replace `events.map(...)` with `visibleEvents.map(...)`** — no reordering, events render in the same order as passed (preserving key={index} stability)
4. **Add expand/collapse Button** below the grid, only if `events.length > COLLAPSED_COUNT`:
   ```tsx
   {events.length > COLLAPSED_COUNT && (
     <Button
       variant="ghost"
       size="sm"
       onClick={() => setExpanded(prev => !prev)}
       className="mt-3 w-full justify-center"
     >
       {expanded ? "Show fewer events" : `Show ${events.length - COLLAPSED_COUNT} more`}
     </Button>
   )}
   ```

No changes to event card styling, layout grid, header, or sorting. Events render in their original order.

## Verification
1. Visual: only 4 event cards visible by default (2 rows on md+, 4 rows on mobile)
2. "Show 5 more" button appears below the grid
3. Clicking expands to show all 9 events
4. Clicking "Show fewer events" collapses back to 4
5. If ≤4 events total, no button shown
6. Switching portfolios remounts component, resetting to collapsed

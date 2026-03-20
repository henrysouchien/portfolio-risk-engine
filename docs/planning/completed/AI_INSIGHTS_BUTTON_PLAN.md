# AI Insights Button — Eliminate Wasted Vertical Space

## Context
The AI Insights toggle button sits in a standalone `<div className="flex justify-end">` between the refresh warning and the metric cards grid in `PortfolioOverview.tsx`. The parent uses `space-y-8` (2rem gaps), so this one small button consumes ~64px of vertical space as its own row. It looks orphaned and pushes the metric cards down unnecessarily.

## Codex Review Findings (Round 1)
- **Rejected** absolute positioning approach as too brittle
- Recommended: shared wrapper with smaller internal gap

## Plan

**File:** `frontend/packages/ui/src/components/portfolio/PortfolioOverview.tsx`

Wrap the AI Insights button and the metric grid together in a single container `<div>` with a small internal gap (`space-y-2`). This way:
- The outer `space-y-8` treats the button+grid as one unit
- The internal gap is 8px instead of 32px — button tucks close to the grid
- No absolute positioning, no magic numbers, no overlap risk
- Works regardless of whether `refreshWarning` is present above
- Works at all viewport widths since both elements are in normal flow

**The UpgradePrompt (free tier) stays as a separate child** of the outer `space-y-8` since it's a full-width banner that belongs in the normal flow.

**Conditional structure (preserves existing `onToggleAIInsights` gate):**
```tsx
{onToggleAIInsights && !isPaid && (
  <UpgradePrompt feature="ai-insights" variant="inline" />
)}

<div className="space-y-2">
  {onToggleAIInsights && isPaid && (
    <div className="flex justify-end">
      <Button ...>AI Insights</Button>
    </div>
  )}
  <div className="grid grid-cols-2 gap-6 md:grid-cols-3">
    {metrics.map(...)}
  </div>
</div>
```

When `onToggleAIInsights` is falsy: no button, no UpgradePrompt — just the grid. When `!isPaid`: UpgradePrompt renders as its own block, grid renders in the wrapper with no button. When paid: button + grid in the wrapper with 8px gap.

**Active state styling (matches `PerformanceHeaderCard.tsx:92` pattern):**
Current active classes: `bg-blue-100 text-blue-700`
Add hover override + dark mode: `hover:bg-blue-200 dark:bg-blue-900/40 dark:text-blue-300 dark:hover:bg-blue-900/60`
This prevents the ghost variant's `hover:bg-accent` from overriding the blue active treatment on hover.

Single file, ~8 lines changed.

## Verification
1. Visual: button sits close to grid (8px gap), no wasted row
2. No `refreshWarning`: layout still correct (no overlap)
3. Mobile `grid-cols-2`: button row + grid in normal flow, no clipping
4. `onToggleAIInsights` absent: no button, no UpgradePrompt, just grid
5. Free tier: UpgradePrompt renders as standalone block
6. Toggle works: clicking toggles AI insights on metric cards
7. Dark mode: active state colors render correctly

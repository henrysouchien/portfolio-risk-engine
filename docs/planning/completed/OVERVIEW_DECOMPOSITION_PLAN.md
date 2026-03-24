# Overview Decomposition — Presentational Subsections

## Context
`PortfolioOverview.tsx` renders metric cards, performance chart, market intelligence, and AI recommendations as one opaque block. `ModernDashboardApp` can't interleave components between sections. The layout problem is about reorderability — not data architecture.

## Codex Findings (all addressed)
1. **Fixed:** Paid/free gating lives in PortfolioOverview — sections get `isPaid` prop, UpgradePrompts in container
2. **Fixed:** `space-y-8` wrapper preserved
3. **Fixed:** Memo comparator removed
4. **Accepted:** MetricCardsSection calls `useOverviewMetrics()` — pure transform, not data fetch
5. **Fixed:** No backwards-compat wrapper needed
6. **Fixed:** Strip outside hover-lift-premium — `hover-lift-premium` wraps only MetricCardsSection inside the container, not the whole block
7. **Fixed:** Subsections NOT exported from index.ts
8. **Fixed:** Verification expanded
9. **Intentional behavior change:** Strip now gated behind portfolio loading/error/no-portfolio. Today it's an independent sibling that can render while summary loads. But the strip shows `"—"` for all values without portfolio data — rendering an empty strip adds no value. Gating it behind the portfolio check is correct UX. This is a deliberate coupling, not an accident
10. **Fixed:** hover-lift-premium moved from ModernDashboardApp into the container, wrapping only MetricCardsSection. Strip rendered as a sibling, no inherited lift

## Plan

### Change 1: Extract 4 presentational subsections

Create 4 components in `frontend/packages/ui/src/components/portfolio/overview/`. Each takes explicit props — no data fetching.

**a) `MetricCardsSection.tsx`**
```tsx
interface MetricCardsSectionProps {
  data?: PortfolioOverviewData;
  metricInsights?: Record<string, MetricInsight>;
  showAIInsights?: boolean;
  isPaid?: boolean;
  onToggleAIInsights?: () => void;
  portfolioType?: string;
  portfolioDisplayName?: string;
}
```
- Renders: AI Insights toggle (if `isPaid && onToggleAIInsights`) + metric cards grid in `space-y-2` wrapper
- Local state: `hoveredMetric`, `focusedMetric`
- Calls `useOverviewMetrics()` (pure transform, not a fetch)
- If `!isPaid && onToggleAIInsights`: renders UpgradePrompt instead of toggle

**b) `PerformanceTrendSection.tsx`**
```tsx
interface PerformanceTrendSectionProps {
  data?: TrendDataPoint[];
  benchmarkLabel?: string;
}
```
- Renders: `PerformanceTrendChart` if data provided, nothing otherwise
- Pure presentational — no hooks, no state

**c) `MarketIntelligenceSection.tsx`**
```tsx
interface MarketIntelligenceSectionProps {
  events: MarketEvent[];
  portfolioId?: string;
}
```
- Renders: `MarketIntelligenceBanner` with `key={portfolioId}`
- Pure presentational — caller handles isPaid/empty gating

**d) `AIRecommendationsSection.tsx`**
```tsx
interface AIRecommendationsSectionProps {
  recommendations: AIRecommendation[];
}
```
- Renders: `AIRecommendationsPanel` with `visible` prop
- Pure presentational — caller handles isPaid gating

### Change 2: Update PortfolioOverviewContainer

**File:** `frontend/packages/ui/src/components/dashboard/views/modern/PortfolioOverviewContainer.tsx`

Container keeps ALL existing hooks and gating. Replaces `<PortfolioOverview ...props />` with direct section rendering.

**Add `renderAfterMetrics` slot prop:**
```tsx
interface PortfolioOverviewContainerProps {
  className?: string;
  renderAfterMetrics?: React.ReactNode;
}
```

**Remove `React.memo` with `smartComparison`** — the custom comparator only checked `className` and `smartAlerts` (already removed). With `renderAfterMetrics` added, the comparator would need updating anyway. Just use default `React.memo` or no memo at all since the container's hooks drive re-renders regardless.

**Container render becomes:**
```tsx
// Loading/error/no-portfolio gates (early returns — same as current)
if (isLoading) return <LoadingSpinner message="Loading portfolio overview..." />;
if (error) return <ErrorMessage ... />;
if (!hasPortfolio) return <NoDataMessage ... />;

// Main render — sections in a space-y-8 wrapper
return (
  <DashboardErrorBoundary>
    <div className="space-y-8">
      {refreshWarning && <PartialRefreshWarningBanner warning={refreshWarning} />}

      <div className="hover-lift-premium">
        <MetricCardsSection
          data={portfolioOverviewData}
          metricInsights={metricInsights}
          showAIInsights={showAIInsights}
          isPaid={isPaid}
          onToggleAIInsights={toggleAIInsights}
          portfolioType={currentPortfolio?.portfolio_type}
          portfolioDisplayName={currentPortfolio?.display_name}
        />
      </div>

      {renderAfterMetrics}

      {performanceTrendData && (
        <PerformanceTrendSection
          data={performanceTrendData}
          benchmarkLabel={portfolioOverviewData?.summary?.benchmarkTicker ?? "SPY"}
        />
      )}

      {isPaid ? (
        marketEvents?.length > 0 ? (
          <MarketIntelligenceSection events={marketEvents} portfolioId={currentPortfolio?.id} />
        ) : null
      ) : (
        <UpgradePrompt feature="ai-insights" variant="inline" />
      )}

      {isPaid ? (
        <AIRecommendationsSection recommendations={aiRecommendations ?? []} />
      ) : (
        <UpgradePrompt feature="ai-insights" variant="inline" />
      )}
    </div>

    {import.meta.env.DEV && (
      <div className="fixed bottom-4 right-4 bg-green-100 text-green-800 px-3 py-1 rounded text-xs">
        Overview: {hasData ? 'Real' : 'Mock'} | Portfolio: {hasPortfolio ? 'Loaded' : 'None'}
      </div>
    )}
  </DashboardErrorBoundary>
);
```

**Key details:**
- `hover-lift-premium` wraps ONLY MetricCardsSection — strip and other sections don't inherit lift
- `renderAfterMetrics` renders AFTER the loading/error gate (inside the main render block), but it's outside the `hover-lift-premium` wrapper. Since the container already early-returns on loading/error/no-portfolio, the slot only renders when portfolio data is available — same as all other sections
- isPaid/event gating is the SAME logic currently in PortfolioOverview.tsx, moved to container

### Change 3: Update ModernDashboardApp

**File:** `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx`

Pass the Performance Strip via the slot. Remove the `hover-lift-premium` wrapper from around the container (it's now inside the container, wrapping only MetricCardsSection):
```tsx
const overviewDashboard = (
  <div className="space-organic animate-stagger-fade-in">
    <PortfolioOverviewContainer
      renderAfterMetrics={<DashboardPerformanceStrip />}
    />
    <div className="grid grid-cols-1 xl:grid-cols-2 gap-8">
      <DashboardHoldingsCard />
      <DashboardAlertsPanel
        smartAlerts={alertData}
        alertsLoading={alertsLoading}
        alertsError={alertError}
      />
    </div>
    <div className="grid grid-cols-1 xl:grid-cols-2 gap-8">
      <div className="hover-lift-premium animate-magnetic-hover">
        <AssetAllocationContainer />
      </div>
      <DashboardIncomeCard />
    </div>
  </div>
);
```

Remove the standalone `<DashboardPerformanceStrip />` from its old position (was between the two grids). Remove the `<div className="hover-lift-premium">` wrapper that was around the container.

### Change 4: PortfolioOverview.tsx — leave as-is

Do NOT modify or delete `PortfolioOverview.tsx`. It's no longer rendered by the container, but leave it in place. If nothing imports it, it's dead code that can be cleaned up later. No risk of breaking anything.

### Change 5: Do NOT export subsections from index.ts

The 4 new components are internal — imported only by `PortfolioOverviewContainer.tsx` via relative paths. No barrel export needed.

## Files Modified
1. `frontend/packages/ui/src/components/portfolio/overview/MetricCardsSection.tsx` — **NEW**
2. `frontend/packages/ui/src/components/portfolio/overview/PerformanceTrendSection.tsx` — **NEW**
3. `frontend/packages/ui/src/components/portfolio/overview/MarketIntelligenceSection.tsx` — **NEW**
4. `frontend/packages/ui/src/components/portfolio/overview/AIRecommendationsSection.tsx` — **NEW**
5. `frontend/packages/ui/src/components/dashboard/views/modern/PortfolioOverviewContainer.tsx` — render subsections + slot prop, remove memo comparator
6. `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx` — pass strip via slot, remove old strip position

## Verification
1. `cd frontend && npx tsc --noEmit` — no type errors
2. Visual: Overview renders same content in same order
3. Performance Strip appears directly below metric cards, above chart
4. Loading spinner shows while portfolio loads
5. Error state shows on API failure
6. No-portfolio state shows welcome card
7. Free tier: UpgradePrompts in place of AI toggle, market intelligence, AI recs
8. Paid tier: AI Insights toggle works, metric insights appear on cards
9. Market Intelligence collapse/expand works, resets on portfolio switch
10. Mobile: metric cards 2+1, strip stacks to 2-col

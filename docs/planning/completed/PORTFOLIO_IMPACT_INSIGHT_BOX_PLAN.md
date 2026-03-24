# Portfolio Impact Insight Box — Phase 2: "Ask AI About This" + Glass Variant

## Context

The Portfolio Impact tab (`PortfolioFitTab`) already renders an `InsightBanner` with color-coded verdict logic (emerald/amber/red based on volatility changes and risk limit violations). The verdict logic (lines 84-191) is complete. This plan adds the "Ask AI about this" action button — the last missing piece to match the stress test insight pattern — and switches to `variant="glass"` for visual consistency.

**What exists**: `InsightBanner` is rendered with `size="lg"`, full verdict logic with 7 branches (emerald/amber/red/neutral), narrative body text. The `ScenarioChatContextBridge` in `ModernDashboardApp.tsx` (lines 256-274) consumes `chatContext` from `scenarioWorkflowStore` globally and sends it as a chat message via `formatScenarioChatMessage()`.

**What's missing**: The `InsightBanner` has no `action` prop — no "Ask AI about this" button.

## Plan

### Step 1: Add "Ask AI about this" button to PortfolioFitTab insight banner

**File**: `frontend/packages/ui/src/components/portfolio/stock-lookup/PortfolioFitTab.tsx`

**Why not `useScenarioChatLauncher`**: That hook (a default export in `useScenarioChatLauncher.ts`) always injects `activeSession?.workflow.title` into the chat context. If the user has an active scenario workflow, launching from Stock Lookup would inherit an unrelated workflow title. Instead, we call `setChatContext` + `setActiveView("chat")` directly with `workflowTitle: undefined`.

Changes:
1. Add `useCallback` to the React import (currently only `useMemo`)
2. Import `useScenarioWorkflowState, useUIActions` from `@risk/connectors` (both already available in the package)
3. Import `colorSchemeToChatSeverity` from `../scenarios/scenarioChat`
4. Import `ArrowRight` from `lucide-react` (add to existing lucide import)
4. Inside the component body:
   ```tsx
   const { setChatContext } = useScenarioWorkflowState()
   const { setActiveView } = useUIActions()
   ```
5. Add a handler that builds the chat context and navigates:
   ```tsx
   const handleAskAI = useCallback(() => {
     if (!insight) return
     const summary = insight.body
       ? `${insight.title}. ${insight.body}`
       : insight.title
     setChatContext({
       id: `portfolio-impact-${Date.now()}`,
       source: "tool",
       workflowTitle: undefined,  // explicit — not inside a scenario workflow
       toolId: undefined,
       toolLabel: "Portfolio Impact",
       timestamp: new Date().toISOString(),
       summary,
       flags: [{
         type: "portfolio-impact-verdict",
         severity: colorSchemeToChatSeverity(insight.colorScheme),
         message: insight.title,
       }],
       keyMetrics: {
         symbol: selectedStock.symbol,
         positionSize: `${portfolioFitSize}%`,
         volBefore: portfolioFitAnalysis?.metrics.find(m => m.label === "Annual Volatility")?.before ?? null,
         volAfter: portfolioFitAnalysis?.metrics.find(m => m.label === "Annual Volatility")?.after ?? null,
         betaAfter: portfolioFitAnalysis?.metrics.find(m => m.label === "Market Beta")?.after ?? null,
         riskViolations: portfolioFitAnalysis?.riskViolationCount ?? 0,
       },
       prompt: `Analyze this portfolio impact and tell me whether adding ${selectedStock.symbol} at ${portfolioFitSize}% is a good idea.`,
     })
     setActiveView("chat")
   }, [insight, selectedStock.symbol, portfolioFitSize, portfolioFitAnalysis, setChatContext, setActiveView])
   ```
6. Add an `action` prop to the existing `InsightBanner` (line 239):
   ```tsx
   action={
     <Button type="button" variant="outline" size="sm" className="rounded-full" onClick={handleAskAI}>
       <span>Ask AI about this</span>
       <ArrowRight className="h-4 w-4" />
     </Button>
   }
   ```

This follows the same data flow as StressTestTool (lines 464-495) but avoids the `useScenarioChatLauncher` wrapper to prevent workflow title leakage.

### Step 2: Switch to `variant="glass"` on InsightBanner

Change the existing `InsightBanner` render (line 239) to include `variant="glass"`. The stress test and scenario tools use this variant (via `ScenarioInsightCard`). This is a one-prop change.

**Note**: We do NOT need to switch to `ScenarioInsightCard` wrapper — that component just wraps `InsightBanner` with `variant="glass"` and renders action buttons in the `action` slot. Since we're building the action inline (same as StressTestTool does with its custom verdict panel), bare `InsightBanner` with `action` prop is the right choice.

## Key reference files

| File | Role |
|------|------|
| `frontend/packages/ui/src/components/portfolio/stock-lookup/PortfolioFitTab.tsx` | **Target file** (only file to modify) |
| `frontend/packages/ui/src/components/blocks/insight-banner.tsx` | `InsightBanner` component (`action`, `variant`, `size` props) |
| `frontend/packages/ui/src/components/portfolio/scenarios/useScenarioChatLauncher.ts` | Reference only — NOT used (leaks workflow title). We call `setChatContext` directly instead |
| `frontend/packages/ui/src/components/portfolio/scenarios/scenarioChat.ts` | `colorSchemeToChatSeverity()` helper |
| `frontend/packages/ui/src/components/portfolio/scenarios/tools/StressTestTool.tsx` | Reference implementation (lines 436-497, inline "Ask AI" pattern) |
| `frontend/packages/ui/src/components/portfolio/scenarios/shared/ScenarioInsightCard.tsx` | Wrapper used by other tools (not needed here) |
| `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx` | `ScenarioChatContextBridge` (lines 256-274, global consumer of `chatContext`) |

## Files changed

| File | Changes |
|------|---------|
| `frontend/.../stock-lookup/PortfolioFitTab.tsx` | Add imports (`useCallback`, `useScenarioWorkflowState`, `useUIActions`, `colorSchemeToChatSeverity`, `ArrowRight`), add `handleAskAI` callback via direct `setChatContext` + `setActiveView("chat")`, add `action` + `variant="glass"` props to `InsightBanner` |

## Verification

1. Open Stock Lookup, search for a stock, go to Portfolio Impact tab
2. Select a position size — insight banner should appear with verdict in glass variant
3. Verify "Ask AI about this" button appears on the insight banner
4. Click "Ask AI about this" — should navigate to chat view with a pre-seeded message about the portfolio impact analysis
5. Verify the message includes the verdict, key metrics, and a useful prompt
6. Test all verdict paths: emerald (vol down, no violations), amber (vol up or violations), red (vol up + violations), neutral
7. Run frontend tests: `cd frontend && npx vitest run`

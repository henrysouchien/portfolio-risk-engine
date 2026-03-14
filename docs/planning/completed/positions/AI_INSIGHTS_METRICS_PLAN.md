# B-013: AI Insights on Metric Cards — Derive from Real Data

**Status**: COMPLETE — commit `14f795bd`, verified in browser

## Context

The Performance view (⌘4) has an "AI Performance Insights" section with 3 cards (Performance, Risk, Opportunity) containing entirely hardcoded text ("5.08% alpha", "16.8% volatility", "94% confidence"). Additionally, the Alpha card always says "Strong" and the Sharpe card always says "Excellent" regardless of actual values.

The real metrics are **already flowing as props**: `alpha`, `sharpeRatio`, `volatility`, `maxDrawdown`, `beta` all come from the backend via `PerformanceAdapter`. We just need to generate meaningful text from these real values instead of hardcoded strings.

**This is a frontend-only change. No backend work needed.**

## Current State

The `performanceData` object inside `PerformanceView.tsx` (~lines 649-707) mixes real and hardcoded data:

**Real** (from props with fallback):
- `periodReturn`, `benchmarkReturn`, `alpha`, `beta`, `sharpeRatio`, `maxDrawdown`, `volatility`

**Hardcoded** (no props pathway):
- `insights.performance` — text, confidence (94), action, impact
- `insights.risk` — text, confidence (87), action, impact
- `insights.opportunity` — text, confidence (76), action, impact
- Alpha card label: always "Strong" (~line 1158)
- Sharpe card label: always "Excellent" (~line 1185)
- `currentValue`, `totalReturn`, `totalReturnPercent` (TODO comments in code)
- `monthlyReturns` with `marketEvent` strings

## Changes

### 1. Replace hardcoded insights with derived text

**File**: `frontend/packages/ui/src/components/portfolio/PerformanceView.tsx`

Replace the hardcoded `insights` object (~lines 665-684) with a function that generates text from real metrics available in `performanceData`:

**Performance card** — derive from `alpha` and `sharpeRatio`:
- Alpha > 5% → "Portfolio is significantly outperforming the benchmark with {alpha}% alpha, indicating strong active management."
- Alpha 0-5% → "Portfolio is modestly outperforming with {alpha}% alpha."
- Alpha < 0% → "Portfolio is underperforming the benchmark by {|alpha|}%. Consider reviewing allocation strategy."
- Action derived from alpha sign and magnitude

**Risk card** — derive from `volatility`, `maxDrawdown`, `beta`:
- Volatility > 20% → "Portfolio volatility of {vol}% is elevated. Max drawdown of {dd}% suggests significant downside risk."
- Volatility 10-20% → "Portfolio volatility of {vol}% is moderate with a max drawdown of {dd}%."
- Volatility < 10% → "Portfolio volatility of {vol}% is low, indicating conservative positioning."
- Append beta context: "Beta of {beta} indicates {above/below}-market sensitivity."

**Opportunity card** — derive from `sharpeRatio` and general metrics:
- Sharpe > 1.5 → "Strong risk-adjusted returns (Sharpe {sharpe}) suggest current strategy is working well."
- Sharpe 1.0-1.5 → "Decent risk-adjusted returns. Consider optimizing for better Sharpe ratio."
- Sharpe < 1.0 → "Risk-adjusted returns could be improved (Sharpe {sharpe}). Consider rebalancing."

### 2. Replace hardcoded label badges

**Alpha label** (~line 1158) — derive from actual alpha value:
- Alpha > 5% → "Strong" (emerald)
- Alpha 1-5% → "Moderate" (blue)
- Alpha 0-1% → "Neutral" (neutral)
- Alpha < 0% → "Weak" (red)

**Sharpe label** (~line 1185) — derive from actual Sharpe ratio:
- Sharpe > 1.5 → "Excellent" (emerald)
- Sharpe 1.0-1.5 → "Good" (blue)
- Sharpe 0.5-1.0 → "Fair" (amber)
- Sharpe < 0.5 → "Poor" (red)

### 3. Remove fake confidence scores

Remove the `confidence` percentage (94%, 87%, 76%) from insight cards. Replace with `impact` level badge (high/medium/low) derived from real metric thresholds.

### 4. Rename section header

Change "AI Performance Insights" / "Machine learning analysis of your portfolio" to:
- "Performance Insights" / "Analysis based on portfolio metrics"

Since these are rule-based derivations, not ML output.

## Files Modified

| File | Change |
|------|--------|
| `frontend/.../PerformanceView.tsx` | Replace hardcoded insights with derived text, fix label badges, remove fake confidence, rename section header |

## Edge Cases

- **Alpha fallback**: `alpha` is period-dependent (`data.periods[selectedPeriod].alpha`). Some period keys (6M, 3Y, 5Y, MAX) aren't populated by the adapter, so alpha can fall back to the hardcoded `5.08`. The insight generator must handle this gracefully — if the value equals the exact fallback constant, show generic text instead of citing a specific number.
- **`getConfidenceColor()` utility** (~line 771): Must be removed or repurposed since `confidence` field is removed. Check for any other references to it.
- **Two rendering contexts**: `PerformanceViewContainer` is rendered in both the score view (⌘1 Overview) and performance view (⌘4). Both paths pass the same props — changes are safe for both.

## What Does NOT Change

- No backend changes
- No adapter changes
- No container changes
- `PortfolioOverview.tsx` AI fields (separate — they're empty, not hardcoded)
- `monthlyReturns` hardcoded data (separate item)
- `fallbackSectors` insight text (only shown when no real sector data)

## Codex v1 Findings (Addressed)

1. **Alpha fallback on unsupported periods**: Some period keys (6M, 3Y, 5Y, MAX) aren't populated, causing alpha to fall back to hardcoded 5.08. Plan updated with edge case handling.
2. **`getConfidenceColor()` dead code**: Must be removed alongside `confidence` field removal. Added to plan.
3. **Two rendering contexts**: PerformanceViewContainer renders in both Overview and Performance views. Both use same props — safe.
4. **No standalone insight interface**: Shape is inferred from `performanceData.insights`. Removing `confidence` is safe if all reads are removed.

## Verification

1. `cd frontend && pnpm exec tsc --noEmit -p packages/ui/tsconfig.json` passes
2. `cd frontend && pnpm exec eslint` on modified file passes
3. Performance view (⌘4) — insight cards show text derived from real metrics (e.g. real alpha %, real volatility %)
4. Alpha label changes based on actual alpha value (not always "Strong")
5. Sharpe label changes based on actual Sharpe ratio (not always "Excellent")
6. No "94%", "87%", "76%" confidence scores visible
7. No hardcoded "5.08%", "16.8%", "31.8%", "3.2%" in insight text

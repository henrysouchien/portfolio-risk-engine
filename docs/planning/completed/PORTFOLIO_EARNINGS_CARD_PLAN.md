# Portfolio Earnings Card — Income + Trading P&L

## Context
The Overview currently shows a `DashboardIncomeCard` that duplicates the Income Projection from the Performance view. For the Overview story, we want a card that answers "What is my portfolio earning me?" — showing both passive income and active trading results side by side.

These are two distinct facets of portfolio earnings, NOT addable into one number.

## Codex Findings (Round 1 — all addressed)
1. **Fixed:** No combined "Total Earnings" hero number. Income and Trading are two separate sections with their own headlines. Income = projected annual recurring. Trading = realized cumulative P&L. Different metrics, different timeframes.
2. **Fixed:** Trading data availability — check `realized_performance.total_trades > 0` to distinguish real trading data from synthetic signals. If no realized trades, hide trading section entirely.
3. **Fixed:** Supported modes — use existing hooks `useIncomeProjection()` and `useTradingAnalysis()` which already handle `supported_modes` checks and return appropriate loading/error/unsupported states.
4. **Fixed:** Use existing feature hooks, not raw `useDataSource`. `useIncomeProjection()` and `useTradingAnalysis()` handle portfolio resolution, enablement, and pending states.
5. **Fixed:** Use `trading_summary.total_trading_pnl_usd` (canonical field), not `total_pnl_by_currency`.
6. **Fixed:** `DashboardIncomeCard` is NOT used on Performance view — Performance uses `IncomeProjectionCard`. DashboardIncomeCard can be removed from the Overview and potentially deprecated.
7. **Fixed:** Top payers — prefer `top_5_contributors`, fallback to `positions` (matching current DashboardIncomeCard logic).
8. **Fixed:** Zero is valid data — `$0` income or `$0` P&L renders as real values, not "unavailable." "Unavailable" only for missing/error/unsupported states.
9. **Fixed:** Loading model — render each section independently. Income section renders when income loads. Trading section renders when trading loads. Neither blocks the other. Both can be absent.
10. **Fixed:** Verification expanded for unsupported modes, synthetic fallback, zero-vs-missing, negative P&L.

## Codex Findings (Round 2 — all addressed)
11. **Fixed:** Hooks don't gate on `supported_modes` — card checks `supported_modes` in-component before calling hooks (same pattern as `IncomeProjectionCard` and `TradingPnLCard`). Use `useSupportedModes()` or derive from `usePortfolioSummary()`.
12. **Fixed:** `top_5_contributors` not in typed contract — simplified to `positions` only. This is the typed field the resolver actually returns.
13. **Fixed:** Trading section visibility — show trading section when `trading_summary.total_trading_pnl_usd` exists (not gated on `realized_performance`). Show P&L hero from `trading_summary` even without realized stats. Win rate / trade count shown only when `realized_performance` data is present.

## Plan

### Change 1: Create `PortfolioEarningsCard`

**New file:** `frontend/packages/ui/src/components/dashboard/cards/PortfolioEarningsCard.tsx`

A self-contained card component (~140 lines):

**Hooks (existing feature hooks, not raw useDataSource):**
- `useIncomeProjection()` from `@risk/connectors` — returns `{ data, loading, error }`
- `useTradingAnalysis()` from `@risk/connectors` — returns `{ data, loading, error }`
- `usePortfolioSummary()` or equivalent — to check `supported_modes` before calling hooks

These hooks handle portfolio resolution and data fetching. The card checks `supported_modes` in-component (same pattern as `IncomeProjectionCard` and `TradingPnLCard`) before enabling each hook. If income is unsupported, skip the income hook entirely. If trading is unsupported, skip the trading hook.

**Card layout — two distinct sections, no combined total:**
```
┌──────────────────────────────────────┐
│ Portfolio Earnings                    │
│                                      │
│ ── Projected Income ─────────────── │
│ $10,238/yr                           │
│ 6.7% yield · $853/mo                │
│                                      │
│ Top Payers                           │
│ DSU        $5,387                    │
│ STWD       $2,043                    │
│ BXMT       $1,092                    │
│                                      │
│ ── Trading P&L ─────────────────── │
│ $175 realized                        │
│ 81% win rate · 42 trades             │
└──────────────────────────────────────┘
```

**Income section:**
- Hero: projected annual income (`total_projected_annual_income`)
- Supporting: portfolio yield (`portfolio_yield_on_value`) + monthly rate (`projected_cashflow.monthly`)
- Top Payers: use `positions` (typed resolver field) — show top 3

**Trading section:**
- Hero: total realized P&L (`trading_summary.total_trading_pnl_usd`) — green if positive, red if negative
- Supporting: win rate (`realized_performance.win_percent`) + trade count (`realized_performance.total_trades`) — only shown when `realized_performance` data is present
- Visible when `trading_summary.total_trading_pnl_usd` is not null/undefined (show P&L even without realized stats)

**State handling (each section independent):**
- Income loading → skeleton for income section, trading section renders independently
- Income error/unsupported → income section hidden (not "unavailable" — just absent)
- Trading loading → skeleton for trading section, income renders independently
- Trading error/unsupported → trading section hidden
- Trading loaded but no `trading_summary.total_trading_pnl_usd` → trading section hidden (synthetic-only)
- Both absent → "No earnings data available" placeholder
- Zero income ($0) → renders as $0/yr (valid data)
- Zero trading P&L ($0) → renders as $0 (valid data)
- Negative trading P&L → renders in red (e.g., "-$500 realized")

### Change 2: Replace DashboardIncomeCard on Overview

**File:** `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx`

Replace `<DashboardIncomeCard />` with `<PortfolioEarningsCard />` in the bottom grid.

Remove `DashboardIncomeCard` import from ModernDashboardApp. The component stays in the codebase but is no longer used on the Overview. (Performance view uses `IncomeProjectionCard`, not `DashboardIncomeCard`.)

### Change 3: Export from cards barrel

**File:** `frontend/packages/ui/src/components/dashboard/cards/index.ts`

Add export for `PortfolioEarningsCard`.

### Change 4: Apply items-start to bottom grid

**File:** `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx`

Add `items-start` to the Asset Allocation + Earnings grid:
```tsx
<div className="grid grid-cols-1 xl:grid-cols-2 items-start gap-8">
  <AssetAllocationSummary />
  <PortfolioEarningsCard />
</div>
```

## Files Modified
1. `frontend/packages/ui/src/components/dashboard/cards/PortfolioEarningsCard.tsx` — **NEW**
2. `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx` — swap DashboardIncomeCard for PortfolioEarningsCard + items-start
3. `frontend/packages/ui/src/components/dashboard/cards/index.ts` — export

## Files NOT Modified
- `DashboardIncomeCard.tsx` — stays in codebase (unused on Overview, not used on Performance either — candidate for later cleanup)
- `IncomeProjectionCard.tsx` — stays (used on Performance view)
- `TradingPnLCard.tsx` — stays (used on Performance view)

## Verification
1. `cd frontend && npx tsc --noEmit` — no type errors
2. Visual: bottom-right card shows "Portfolio Earnings" with two distinct sections
3. Income section: projected annual, yield, monthly rate, top 3 payers
4. Trading section: realized P&L (green/red), win rate, trade count
5. Trading section hidden when no realized trades (synthetic-only data)
6. Income section hidden when income unsupported for portfolio type
7. Zero values render as real data ($0), not "unavailable"
8. Negative trading P&L renders in red
9. Both sections load independently (neither blocks the other)
10. Asset Allocation + Earnings cards take natural heights (items-start)
11. Performance view unchanged (uses IncomeProjectionCard + TradingPnLCard)

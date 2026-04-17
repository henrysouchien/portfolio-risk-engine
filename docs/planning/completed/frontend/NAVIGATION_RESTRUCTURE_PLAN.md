# Navigation Restructure Plan — 5-Section Information Architecture

**Status**: DRAFT
**Resolves**: T3 #28 (nav hides functionality), #32 (Scenario Analysis cramped), #33 (Strategy Builder confusing), #35-37a (Stock Lookup buried)
**Depends on**: Separate layout/visual spec (in progress by another Claude)

---

## Problem

The current nav shows 3 visible items (Overview, Holdings, Analytics dropdown) + AI Assistant, hiding 5 major features behind a dropdown. The app looks like it has 3 pages when it has 8. Meanwhile, related tools are split across unrelated views (Factor Analysis vs Stock Research are both "research"; Scenario Analysis vs Strategy Builder are both "planning").

## Design Principle

**Organize by user intent, not technical category.** The MCP tool clusters reveal 5 natural workflows:

1. **"What do I have?"** → Dashboard
2. **"How am I doing?"** → Performance
3. **"Should I buy/sell this?"** → Research
4. **"What if?"** → Scenarios
5. **"Do it"** → Trading

---

## Target Navigation

```
Dashboard | Performance | Research | Scenarios | Trading     [AI] [⚙]
```

5 top-level nav items, always visible. AI Assistant and Settings remain as icon buttons on the right (not competing for nav space). No dropdowns.

### Keyboard Shortcuts (updated)
| Key | Section | Old mapping |
|-----|---------|-------------|
| ⌘1 | Dashboard | ⌘1 (score) — unchanged |
| ⌘2 | Performance | ⌘4 (performance) |
| ⌘3 | Research | ⌘3 (factors) + ⌘6 (research) |
| ⌘4 | Scenarios | ⌘8 (scenarios) + ⌘5 (strategies) |
| ⌘5 | Trading | new |
| ⌘6 | AI Assistant | ⌘7 (chat) |
| ⌘, | Settings | unchanged |

---

## Section Definitions

### 1. Dashboard (ViewId: `score`) — NO CHANGE
Current Overview page. Already well-structured: metric cards, asset allocation, risk analysis, market intelligence, performance trend.

**Tools surfaced**: `get_positions`, `get_risk_score`, `get_risk_analysis`, `get_leverage_capacity`, `set_target_allocation`, `get_target_allocation`

### 2. Performance (ViewId: `performance`) — MINOR CHANGES
Current Performance view, mostly unchanged. Already has Attribution, Benchmarks, Risk Analysis, Period Analysis tabs.

**Additions**:
- Trading P&L summary card (from `get_trading_analysis`) — realized gains/losses at a glance
- Income projection card (from `get_income_projection`) — dividend/income forecast

**Tools surfaced**: `get_performance`, `get_trading_analysis`, `get_income_projection`

### 3. Research (ViewId: `research`) — MERGE factors + research

Merge Factor Analysis and Stock Research into one section. Two modes:

**Landing state**: Factor Risk Model (current `FactorRiskModelContainer`) — portfolio-level factor exposures, risk attribution, factor recommendations. This is the "portfolio research" view.

**Stock deep-dive**: When user searches/selects a ticker, show the Stock Lookup view (current `StockLookupContainer`) — but flatten the 7 tabs into a scrollable page with sections:
1. Price chart + key stats (default visible)
2. Portfolio Fit (correlation, factor overlap, concentration impact)
3. Fundamentals
4. Technical analysis
5. Option chain (if applicable)
6. News & events

**Navigation within Research**: Tab bar or segmented control at top:
```
[Portfolio Factors]  [Stock Lookup]  [News & Events]
```

**Tools surfaced**: `get_factor_analysis`, `get_factor_recommendations`, `analyze_stock`, `analyze_option_chain`, `analyze_option_strategy`, `check_exit_signals`, `get_portfolio_news`, `get_portfolio_events_calendar`, `get_quote`

### 4. Scenarios (ViewId: `scenarios`) — MERGE scenarios + strategies

Merge Scenario Analysis and Strategy Builder into one section. Replace the cramped multi-tab card with a section-based layout.

**Landing state**: Entry cards with descriptions (guided workflow):
```
┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐
│ 📊 What-If Builder  │  │ 🎯 Optimize         │  │ 📈 Backtest         │
│ Edit weights, test  │  │ Find the optimal    │  │ Test any allocation │
│ allocation changes  │  │ allocation for your │  │ against history     │
│                     │  │ risk tolerance      │  │                     │
└─────────────────────┘  └─────────────────────┘  └─────────────────────┘
┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐
│ ⚡ Stress Tests     │  │ 🎲 Monte Carlo      │  │ 🔄 Rebalance        │
│ See how crashes     │  │ Simulate 1000s of   │  │ Generate trades to  │
│ would affect you    │  │ possible futures    │  │ hit target weights  │
└─────────────────────┘  └─────────────────────┘  └─────────────────────┘
```

Each card opens a full-width section (not a tab in a card). Sections can cross-reference: stress test reveals vulnerability → "Optimize to reduce this risk" button → optimization result → "Backtest this" → backtest result → "Set as target allocation".

**Removed**:
- Historical Scenarios tab (was placeholder/disabled)
- Active Strategies tab (was always empty, no persistence)
- Strategy Marketplace tab (move to a sidebar or "Templates" dropdown within Optimize)

**Tools surfaced**: `run_whatif`, `run_optimization`, `get_efficient_frontier`, `run_backtest`, `compare_scenarios`, `suggest_tax_loss_harvest`, `preview_rebalance_trades`

### 5. Trading (ViewId: `trading`) — NEW

No dedicated view exists today — all trading goes through the AI chat. This section surfaces trading capabilities directly.

**Landing state**:
- **Open Orders** card (from `get_orders`) — active/pending orders with cancel buttons
- **Quick Trade** card — ticker input + shares + preview/execute flow
- **Baskets** card — list/create/manage baskets with batch execution
- **Hedge Monitor** card (from `monitor_hedge_positions`) — expiry alerts, delta drift, roll recommendations

**Future additions** (not in this plan):
- Order history / trade log
- P&L attribution by trade

**Tools surfaced**: `preview_trade`, `execute_trade`, `preview_option_trade`, `execute_option_trade`, `preview_futures_roll`, `execute_futures_roll`, `get_orders`, `cancel_order`, `create_basket`, `list_baskets`, `get_basket`, `analyze_basket`, `update_basket`, `delete_basket`, `create_basket_from_etf`, `preview_basket_trade`, `execute_basket_trade`, `monitor_hedge_positions`

---

## Holdings

`holdings` view stays as-is but moves from a top-level nav item to a tab/section within Dashboard. The Overview page already shows positions via the metric cards and asset allocation — Holdings is a detailed drill-down. This declutters the top nav from 5+2 items to exactly 5+2.

**Alternative**: Keep Holdings as a 6th nav item if the top nav has room. Decision depends on the layout spec.

---

## Implementation

### Phase 1: Nav bar restructure (non-breaking)
**Goal**: Replace the Analytics dropdown with 5 flat nav items. No component changes — just routing.

1. **Update `ViewId` type** in `uiStore.ts`:
   - Add `trading` to the union
   - Keep all existing values (backward compat)

2. **Rewrite nav bar** in `ModernDashboardApp.tsx` (lines 515-720):
   - Remove Analytics dropdown
   - 5 flat buttons: Dashboard, Performance, Research, Scenarios, Trading
   - AI Assistant + Settings as icon buttons (right side)
   - Update keyboard shortcuts

3. **Update `renderMainContent()`** (lines 309-462):
   - `score` → unchanged
   - `performance` → unchanged
   - `research` → render `StockLookupContainer` (for now, merge with factors later)
   - `factors` → redirect to `research`
   - `scenarios` → unchanged (renders `ScenarioAnalysisContainer`)
   - `strategies` → redirect to `scenarios`
   - `trading` → new minimal placeholder (orders + quick trade)

4. **Update command palette** mappings

**Files changed**: ~3 files (uiStore.ts, ModernDashboardApp.tsx, command-palette.tsx)

### Phase 2: Research merge
**Goal**: Combine Factor Analysis and Stock Lookup into one Research section.

1. Create `ResearchContainer.tsx` — orchestrator with tab bar (Portfolio Factors | Stock Lookup | News & Events)
2. Move `FactorRiskModelContainer` and `StockLookupContainer` as sub-views
3. Flatten Stock Lookup tabs into scrollable sections (future — can defer)

**Files changed**: ~3-4 new/modified files

### Phase 3: Scenarios merge
**Goal**: Combine Scenario Analysis and Strategy Builder into one Scenarios section with card-based entry points.

1. Create `ScenariosContainer.tsx` — landing page with entry cards
2. Each card opens its analysis tool as a full-width section
3. Remove Historical Scenarios placeholder and Active Strategies empty tab
4. Strategy Builder's Marketplace becomes "Templates" within Optimize
5. Wire cross-references between tools (stress test → optimize → backtest)

**Files changed**: ~5-6 new/modified files

### Phase 4: Trading section
**Goal**: Build the Trading view with orders, quick trade, baskets, hedge monitor.

1. Create `TradingContainer.tsx` — card-based layout
2. Create sub-components: `OrdersCard`, `QuickTradeCard`, `BasketsCard`, `HedgeMonitorCard`
3. Wire to existing MCP tools via new hooks or direct API calls

**Files changed**: ~5-8 new files

### Phase 5: Performance enrichment
**Goal**: Add trading P&L summary and income projection to Performance section.

1. Add summary cards above the existing PerformanceViewContainer
2. Wire `get_trading_analysis` and `get_income_projection` data

**Files changed**: ~2-3 files

---

## Migration Notes

- **No data/backend changes** — all restructuring is frontend-only
- **Lazy loading preserved** — new containers use React.lazy()
- **Existing containers reused** — FactorRiskModelContainer, StockLookupContainer, ScenarioAnalysisContainer, StrategyBuilderContainer are composed into new orchestrators, not rewritten
- **Old ViewId values kept** as aliases during transition (e.g., `factors` → redirects to `research`)
- **Keyboard shortcuts updated** in one place (ModernDashboardApp.tsx lines 212-263)

---

## What This Plan Does NOT Cover

- Visual design / layout system (separate spec in progress)
- Component-level redesign of individual views (e.g., flattening Stock Lookup tabs)
- Claude integration / AI-driven navigation
- Mobile responsiveness
- Sidebar vs top-nav decision (assumes top-nav continues, layout spec may change this)

---

## Suggested Order

1. Phase 1 first (nav bar) — unblocks everything, low risk, immediately visible
2. Phase 3 (Scenarios merge) — highest UX impact, resolves #32 + #33
3. Phase 2 (Research merge) — resolves #35-37a
4. Phase 4 (Trading) — new capability, no urgency
5. Phase 5 (Performance) — polish

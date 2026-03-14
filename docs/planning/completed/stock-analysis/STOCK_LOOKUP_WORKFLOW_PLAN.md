# Stock Lookup → Full Research Workflow (Phase 4)

## Context

The Stock Lookup view currently works as: Search (real FMP data) → Select → 4-tab analysis (Overview, Risk Factors, Technicals, Fundamentals). All data is real — search is wired to `GET /api/direct/stock/search` → `stock_service.search_stocks()` → FMP search + quote batch, and analysis is wired to `POST /api/direct/stock` → `StockService`.

The goal is to upgrade this from a "look up a stock" tool into a full **research → evaluate → size → execute** workflow, matching the position-initiation agent skill. The UI should let a user go from "I'm curious about AAPL" to "I've added 50 shares to my portfolio" in one flow.

---

## Changes

### 1. Backend: Peer Comparison API endpoint (`app.py` or `routes/stock.py`)

No REST endpoint exists for `compare_peers()`. Add one.

**Endpoint:** `GET /api/direct/stock/{symbol}/peers`

**Params:** `peers` (optional, comma-separated), `limit` (default 5), `format` (default "summary")

**Implementation:** Delegate to the existing `compare_peers()` logic in `fmp/tools/peers.py`. Reuse `FMPClient.fetch_raw("stock_peers")` + `FMPClient.fetch_raw("ratios_ttm")` (same as the MCP tool).

Simplest approach: extract the core logic from `fmp/tools/peers.py:compare_peers()` into a reusable function, then call it from both the MCP tool and the API endpoint. Or just import and call the MCP tool function directly (it returns a plain dict with `status`/`subject`/`peers`/`peer_count`/`comparison`/`failed_tickers`).

The endpoint should map the MCP response to the REST API envelope convention (existing direct endpoints use `success: true` + HTTP exceptions on failure):

**Response shape:**
```json
{
  "success": true,
  "subject": "AAPL",
  "peers": ["MSFT", "GOOGL", "META"],
  "peer_count": 3,
  "comparison": [
    { "metric": "P/E Ratio", "metric_key": "priceToEarningsRatioTTM", "AAPL": 28.5, "MSFT": 32.1, ... },
    ...
  ],
  "failed_tickers": []
}
```

### 2. Backend: What-If with new stock endpoint

The what-if endpoint already exists (`POST /api/what-if` used by ScenarioAnalysisContainer). The frontend `useWhatIfAnalysis()` hook works.

**No new backend endpoint needed.** The existing what-if infrastructure handles this. The frontend just needs to compose the call.

**Important:** The REST API uses `scenario.delta` (not `delta_changes` which is the MCP param name). Delta values are **strings** (same as MCP) — the backend `parse_delta()` in `helpers_input.py` calls `.strip()` on each value. The payload shape is:
```json
{
  "portfolio_name": "CURRENT_PORTFOLIO",
  "scenario": {
    "scenario_name": "Add AAPL 2.5%",
    "delta": { "AAPL": "+2.5%" }
  }
}
```
The frontend hook type (`useWhatIfAnalysis`) also expects string delta values.

### 3. Frontend: `usePeerComparison()` hook (`connectors/src/features/stockAnalysis/hooks/`)

New TanStack Query hook, same pattern as `useStockSearch`:

```typescript
// In chassis/src/queryKeys.ts, add:
export const peerComparisonKey = (symbol?: string | null) =>
  scoped('peerComparison', symbol?.toUpperCase() ?? null);

// Hook:
export const usePeerComparison = (symbol: string | null) => {
  const { api } = useSessionServices();
  const { data, isFetching } = useQuery({
    queryKey: peerComparisonKey(symbol),
    queryFn: () => api.getPeerComparison(symbol!, 5),
    enabled: !!symbol && !!api,
    staleTime: 5 * 60_000,
  });
  return { data: data ?? null, isLoading: isFetching };
};
```

Also update `frontend/packages/connectors/src/features/stockAnalysis/hooks/index.ts` to export the new hook:
```typescript
export { usePeerComparison } from './usePeerComparison';
```

### 4. Frontend: `APIService.getPeerComparison()` method (`chassis/src/services/APIService.ts`)

Add method to API service (next to `searchStocks()`):

```typescript
async getPeerComparison(symbol: string, limit = 5): Promise<PeerComparisonResponse> {
  return this.request(`/api/direct/stock/${symbol}/peers?limit=${limit}`);
}
```

### 5. Frontend: Upgrade `StockLookupContainer.tsx` — add workflow tabs

Current: 4 tabs (Overview, Risk Factors, Technicals, Fundamentals)

**Add 2 new tabs:**

**Tab 5: "Peer Comparison"**
- Uses `usePeerComparison(selectedSymbol)`
- Renders comparison table: rows = metrics (P/E, P/B, margins, etc.), columns = subject + peers
- Highlight where subject ranks (best/worst in each metric)

**Tab 6: "Portfolio Fit"**
- Uses `useWhatIfAnalysis()` from existing connectors
- Size selector: 1%, 2.5%, 5% of portfolio (buttons or slider)
- Runs `scenario.delta: { [symbol]: "+X%" }` via existing what-if (REST API uses `delta` with string values)
- Shows before/after: volatility, concentration, factor variance, risk passes/fails
- "Add to Portfolio" button → navigates to trade preview

### 6. Frontend: "Add to Portfolio" action

On the Portfolio Fit tab, after what-if results show:
- "Preview Trade" button computes share count from selected % + portfolio value
- Opens a confirmation panel with: ticker, shares, estimated cost, side=BUY
- "Execute" button (if `TRADING_ENABLED`) calls the trade execution flow

For now, the simplest path is a button that navigates to the Strategy Builder or a modal that shows the trade preview info. Full `preview_trade()` → `execute_trade()` integration is a follow-up (requires trade API endpoints on REST, currently MCP-only).

**MVP approach:** "Preview Trade" shows computed shares + estimated cost inline. Actual execution deferred to agent (user can say "buy 50 shares of AAPL" in chat).

---

## Files to Modify

**Backend (2 files):**
- `app.py` — Add `GET /api/direct/stock/{symbol}/peers` endpoint
- `services/stock_service.py` — Add `get_peer_comparison(symbol, limit)` method (delegates to FMP client)

**Frontend (6-7 files):**
- `frontend/packages/chassis/src/queryKeys.ts` — Add `peerComparisonKey`
- `frontend/packages/chassis/src/services/APIService.ts` — Add `getPeerComparison()` method
- `frontend/packages/connectors/src/features/stockAnalysis/hooks/usePeerComparison.ts` — New hook
- `frontend/packages/connectors/src/features/stockAnalysis/hooks/index.ts` — Export new hook
- `frontend/packages/connectors/src/index.ts` — Re-export if needed
- `frontend/packages/ui/src/components/dashboard/views/modern/StockLookupContainer.tsx` — Wire new hooks, add tabs
- `frontend/packages/ui/src/components/portfolio/StockLookup.tsx` — Add Peer Comparison + Portfolio Fit tab UI

**No changes to:**
- What-if backend (existing endpoint works)
- `useWhatIfAnalysis()` hook (already exists, reuse as-is)
- MCP tools (no changes needed)

---

## Implementation Order

1. **Backend peer comparison endpoint** — `stock_service.py` + `app.py`
2. **Frontend peer comparison** — `APIService` method → `usePeerComparison` hook → Peer Comparison tab
3. **Frontend portfolio fit tab** — Reuse `useWhatIfAnalysis` → Portfolio Fit tab with size selector
4. **Trade preview action** — Inline preview panel (MVP, no backend trade API needed)

Each step is independently shippable and testable.

---

## Tests

**Backend:**
- `stock_service.get_peer_comparison()` returns expected shape with mocked FMP client
- `GET /api/direct/stock/AAPL/peers` returns 200 with comparison data
- Empty/invalid symbol returns appropriate error

**Frontend:**
- `usePeerComparison` returns data when symbol provided, null when null
- Portfolio Fit tab computes correct `scenario.delta` string (e.g. `"+2.5%"`) for selected size
- StockLookup renders new tabs when stock is selected

## Verification
1. `python3 -m pytest tests/ -x -v` — no regressions
2. Frontend: `pnpm --filter @risk/ui dev` → navigate to Stock Lookup → search "AAPL" → verify all 6 tabs render
3. Peer Comparison tab shows real FMP ratio data
4. Portfolio Fit tab runs what-if and shows before/after risk metrics

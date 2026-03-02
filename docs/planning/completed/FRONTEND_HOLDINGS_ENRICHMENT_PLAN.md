# Holdings Enrichment via Positions Service

**Date**: 2026-02-27
**Status**: COMPLETE — implemented by Codex, verified in Chrome (2026-02-27)
**Parent doc**: `FRONTEND_PHASE2_WORKING_DOC.md` (Wave 2, task 2a)

## Context

The Holdings view (`HoldingsViewModernContainer`) displays a table of positions with 7 fields hardcoded to zero/null: `sector`, `avgCost`, `currentPrice`, `totalReturn`, `riskScore`, `volatility`, `aiScore`. This is because the Holdings container gets data from `usePortfolioSummary()` → `PortfolioSummaryAdapter`, which reads from `GET /api/portfolios/{name}`. That endpoint returns a `PortfolioData` object — an analysis config that only carries `{ticker, shares, type}`.

Meanwhile, `PositionService` already fetches rich per-position data from brokerages (Plaid, SnapTrade, Schwab), saves it to the `positions` DB table with full fields (price, cost_basis, name, account_id, brokerage_name, etc.), and serves it via `GET /api/positions/monitor`. But no frontend hook consumes it.

**Goal**: Wire the Holdings view to the positions service to get real per-position data (price, cost basis, returns, security name). Remove the old `usePortfolioSummary` dependency from HoldingsViewModernContainer.

---

## Data Available from Positions Service

### Monitor view per-position fields (`_build_monitor_payload`)

The monitor view (`to_monitor_view()` → `_build_monitor_payload()`) is the right data source because it already computes P&L fields. Per processed position (from `core/result_objects/positions.py:415-438`):

| Field | Source | Notes |
|---|---|---|
| `ticker` | raw position | Stock symbol |
| `name` | raw position | Security name from provider |
| `type` | raw position | equity/etf/option/cash |
| `currency` | raw position (normalized) | Original currency |
| `direction` | computed | LONG/SHORT based on quantity sign |
| `quantity` | raw position | Signed quantity |
| `shares` | `abs(quantity)` | Absolute shares |
| `entry_price` | `abs(cost_basis) / abs(quantity)` | Per-share cost basis |
| `current_price` | raw `local_price` or `price` | Current market price |
| `cost_basis` | raw position | Total cost basis |
| `gross_exposure` | `abs(value)` | Absolute market value (USD) |
| `net_exposure` | `value` | Signed market value (USD) |
| `dollar_pnl` | `(price - entry_price) * quantity` | P&L in local currency |
| `pnl_percent` | `dollar_pnl / abs(cost_basis) * 100` | P&L percentage |
| `pnl_usd` | `dollar_pnl * fx_ratio` | P&L converted to USD |
| `entry_price_warning` | computed | Flags suspicious entry_price/current_price ratio (>10x or <0.1x) |

### Monitor view summary fields

The monitor payload also includes a `summary` section with per-currency totals:
- `gross_exposure`, `net_exposure`, `total_pnl` (local), `total_pnl_usd`, `total_pnl_percent`
- `total_cost_basis`, `position_count`, `long_count`, `short_count`
- `portfolio_totals_usd` (aggregated across currencies)

### What `to_api_response()` does NOT have (why we use monitor view)

`to_api_response()` returns raw position dicts directly from the DB/provider — it does NOT compute:
- `entry_price` (per-share cost)
- `dollar_pnl`, `pnl_percent`, `pnl_usd` (P&L)
- `direction` (LONG/SHORT)
- `current_price` (display-safe price)
- Per-position `weight` (not computed anywhere — must be derived in adapter)

### Cash position handling

`_build_monitor_payload()` filters out cash positions (`type == "cash"`) before processing. Cash positions are counted separately (`cash_positions_excluded`). This is correct for the Holdings table — cash should not appear as a holding row.

### Account-level fields

When `by_account=False` (consolidated mode), the monitor payload does NOT include `account_name` or `brokerage_name` per position (see `positions.py:440-442`). This is expected — the Holdings table shows consolidated positions, not per-account breakdown. The data is not lost; it's available via `by_account=True` if needed later.

**Enriched in this plan:**
- `sector` — FMP `/profile` lookup per ticker (see Phase 1b below)

**Still missing (not in positions pipeline):**
- `volatility` (per-holding) — only exists at portfolio level in risk analysis
- `riskScore` (per-holding) — not computed per-position
- `aiScore` — not implemented
- `isProxy` — not in positions pipeline (see isProxy section below)

---

## isProxy Field

The current `PortfolioSummaryAdapter` maps `isProxy: !!holding.isProxy` from the `Holding` type (`chassis/src/types/index.ts`). This field indicates cash proxy/placeholder positions (CUR:XXX → proxy ETF mapping via `cash_map.yaml`).

The positions service does NOT have an `isProxy` field. However, we can derive it:
- Positions with `type === "cash"` are already filtered out by `_build_monitor_payload()`
- Remaining positions that came from cash mapping (CUR:XXX → SHV/BIL) will have the proxy ETF ticker (e.g., "SHV"), not the CUR: prefix
- **Decision**: Set `isProxy: false` for all positions from the monitor view. Cash proxy detection is a portfolio-level concern (PortfolioData flow), not a positions concern. If we need this later, we can add a `is_cash_proxy` flag to the positions pipeline.

---

## Portfolio Scoping

**Key difference**: The positions service is **user-scoped** (all brokerage positions across all connected accounts for the authenticated user), not portfolio-scoped. The current `usePortfolioSummary()` is **portfolio-scoped** (reads from a specific `PortfolioData` config identified by `currentPortfolio.id`).

**Why this is correct for Holdings**: The Holdings view shows "what do I own" — this is fundamentally a user-level question, not a portfolio-config question. The user's real brokerage positions (from Plaid, SnapTrade, Schwab) are the ground truth. The portfolio-scoped `PortfolioData` is an analysis config that may be a subset or may contain manual entries.

**Cache key**: Since positions data is user-scoped (not portfolio-scoped), the query key should NOT include `portfolioId`. Use a constant key:

```typescript
export const positionsHoldingsKey = () => ['positionsHoldings'] as const;
```

This ensures:
- Switching portfolios doesn't create stale duplicate cache entries
- A single invalidation clears the one cached positions response
- No risk of showing stale data from a previous portfolio scope

**CacheCoordinator integration**: Since the key is not portfolio-scoped, invalidation uses `queryClient.invalidateQueries({ queryKey: positionsHoldingsKey() })` — no `portfolioId` needed. Add this to `invalidatePortfolioData()` so that any portfolio change triggers a positions refetch (the data may not change, but TanStack Query's stale-while-revalidate handles this efficiently).

**Container impact**: The container continues to use `currentPortfolio?.id` for EventBus filtering. When `'portfolio-data-invalidated'` fires for the current portfolio, the container calls `refetch()` which re-fetches the user-scoped positions (same data, but freshness verified).

---

## Architectural Decision: Direct Hook vs Data Catalog Resolver

Modern hooks (`useRiskAnalysis`, `usePerformance`, etc.) use `useDataSource()` → `resolverMap` in `connectors/src/resolver/registry.ts`. A `positions` resolver already exists — but it reads from the **portfolio store** (local `PortfolioData`), returning `{ holdings: Holding[], totalPortfolioValue }`. This is consumed by downstream resolvers (`trading-analysis`, `income-projection`, `tax-harvest`, `portfolio-news`, `events-calendar`).

**Why NOT update the existing `positions` resolver:**
1. The current `positions` resolver returns `PositionsSourceData` shape (from `catalog/types.ts`) — `{ holdings: Holding[], totalPortfolioValue, ... }`. The monitor view shape is completely different (`{ positions: [...], summary: { portfolio_totals_usd: ... } }`).
2. Five downstream resolvers consume `resolverMap.positions` and depend on `positions.holdings[].ticker`, `positions.holdings[].market_value`. Changing the output shape would break them all.
3. The resolver's portfolio-store data serves a different purpose (analysis config) than the positions API data (brokerage positions with P&L).

**Decision**: Create `usePositions()` as a direct TanStack Query hook (bypassing the resolver) with its own `positionsHoldingsKey()` cache key. This follows the same pattern as `usePortfolioSummary()` and `usePortfolioChat()` which also use direct TanStack Query without going through the data catalog.

The existing `positions` resolver in `registry.ts` remains unchanged — it continues to serve the data catalog for analysis-oriented downstream resolvers.

**Future**: When the data catalog evolves to support multiple output shapes per source, we can reconcile these paths. For now, the parallel path is pragmatic and matches existing precedent.

---

## Implementation Plan

### Phase 1: Backend — New Holdings Endpoint

**File**: `routes/positions.py` (edit)

Add `GET /api/positions/holdings` endpoint that returns the monitor view in consolidated mode:

```python
from datetime import datetime

def _empty_monitor_payload(user_email: str) -> dict:
    """Return a full monitor-shaped empty payload matching to_monitor_view() contract.

    Matches _build_monitor_payload() at positions.py:558-588.
    primary_currency is None when no currencies exist (matches builder at positions.py:519).
    """
    now = datetime.now().isoformat()
    return {
        "status": "success",
        "module": "positions",
        "view": "monitor",
        "timestamp": now,
        "exposure_currency": "USD",
        "price_pnl_currency": "local",
        "values_currency": "USD",
        "summary": {
            "by_currency": {},
            "primary_currency": None,
            "has_multiple_currencies": False,
            "has_partial_cost_basis": False,
            "total_positions": 0,
            "cash_positions_excluded": 0,
            "positions_missing_price_or_quantity": 0,
            "portfolio_totals_usd": {
                "gross_exposure": 0, "net_exposure": 0,
                "long_exposure": 0, "short_exposure": 0,
                "total_pnl_usd": 0,
            },
        },
        "positions": [],
        "metadata": {
            "consolidated": True, "by_account": False,
            "sources": [], "from_cache": False, "cache_age_hours": None,
            "cache_by_provider": {},
        },
    }

@positions_router.get("/holdings")
async def get_position_holdings(request: Request):
    """Return consolidated positions with P&L for the holdings table."""
    session_id = request.cookies.get("session_id")
    user = auth_service.get_user_by_session(session_id)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        service = PositionService(user_email=user["email"], user_id=user["user_id"])
        result = service.get_all_positions(consolidate=True)
        payload = result.to_monitor_view(by_account=False)
        # Enrich with sector data via PortfolioService (Phase 1b)
        from services.portfolio_service import PortfolioService
        portfolio_svc = PortfolioService()
        payload = portfolio_svc.enrich_positions_with_sectors(payload)
        return payload
    except ValueError as ve:
        ve_msg = str(ve)
        if ve_msg == "consolidation input is empty":
            # Empty DataFrame after provider fetch. Could be:
            # (a) Truly no positions (new user, no accounts connected)
            # (b) All providers failed (errors swallowed into empty DataFrames)
            # Distinguish by checking provider_errors on the service.
            # If providers reported errors, include them in the response metadata
            # so the frontend can show a warning ("data may be stale / providers failed").
            payload = _empty_monitor_payload(user["email"])
            # NOTE: provider_errors are on the service instance, not the result.
            # Implementation should propagate error metadata. For v1, return empty
            # with a log warning. Backlog item: surface provider errors in response.
            portfolio_logger.info(f"Position holdings: empty portfolio (consolidation input empty)")
            return payload
        # All other ValueErrors (missing columns, None input, etc.) → 500
        portfolio_logger.error(f"Position holdings data error: {ve}")
        log_error("positions_api", "holdings", ve)
        raise HTTPException(status_code=500, detail="Position data contract error")
    except Exception as e:
        portfolio_logger.error(f"Position holdings failed: {e}")
        log_error("positions_api", "holdings", e)
        raise HTTPException(status_code=500, detail="Failed to retrieve holdings data")
```

**Empty portfolio guard**: `_consolidate_cross_provider()` raises three distinct `ValueError` messages:
- `"consolidation input is empty"` (`position_service.py:456`) — empty DataFrame, normal for new users
- `"consolidation input is None"` (`position_service.py:454`) — None input, indicates a bug
- `"consolidation input missing required columns: ..."` (`position_service.py:463`) — schema violation

The endpoint matches the exact string `"consolidation input is empty"` — only this case gets the graceful empty response. All other `ValueError` cases (None, missing columns) re-raise as 500 since they indicate data-contract bugs that should not be silently swallowed.

The `_empty_monitor_payload()` helper returns the full monitor envelope shape (matching `_build_monitor_payload()` at `positions.py:558-588`) to prevent frontend contract drift.

**Why a separate endpoint instead of reusing `/monitor`?** Separation of concerns — `/monitor` may evolve independently (e.g., adding `by_account` default, streaming updates). `/holdings` is explicitly for the holdings table: always consolidated, always `by_account=False`. Both call `to_monitor_view()` under the hood, so there's no code duplication in the result object layer.

**Why `to_monitor_view()` instead of `to_api_response()`?** `to_api_response()` returns raw position dicts without computed P&L fields (entry_price, dollar_pnl, pnl_percent). The monitor view computes these via `_build_monitor_payload()`, which is exactly what the Holdings table needs.

### Phase 1b: Backend — Sector Enrichment via FMP Profile

**File**: `services/portfolio_service.py` (edit — new method on `PortfolioService`)

Add `enrich_positions_with_sectors()` as a method on `PortfolioService`, alongside the existing `get_monitor_with_risk()` enrichment pattern (lines 681-837). Both follow the same shape: take a monitor payload dict → enrich positions → return enriched payload.

```python
def enrich_positions_with_sectors(self, payload: dict) -> dict:
    """Add sector field to each position via FMP profile lookup.

    Follows the same pattern as get_monitor_with_risk() — takes a monitor
    payload dict and enriches each position with additional data.

    FMP profile endpoint: /profile/{symbol} (v3)
    - Returns: { sector, industry, companyName, ... }
    - Cached on disk with 1-week TTL (fmp/registry.py: cache_ttl_hours=168)
    - No batch endpoint — uses ThreadPoolExecutor for parallel fetches
    """
    from fmp.client import FMPClient
    from concurrent.futures import ThreadPoolExecutor

    positions = payload.get("positions", [])
    if not positions:
        return payload

    # Collect unique tickers from monitor payload positions
    ticker_set = set()
    for pos in positions:
        t = pos.get("ticker")
        if t:
            ticker_set.add(t)

    if not ticker_set:
        return payload

    # Batch fetch profiles via thread pool (FMP disk cache handles dedup)
    client = FMPClient()
    sector_map = {}  # ticker -> sector string

    def _fetch_sector(symbol: str) -> tuple[str, str | None]:
        try:
            df = client.fetch("profile", symbol=symbol, use_cache=True)
            if not df.empty:
                sector = str(df.iloc[0].get("sector") or "").strip() or None
                return (symbol, sector)
        except Exception:
            pass
        return (symbol, None)

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = pool.map(_fetch_sector, ticker_set)
        for symbol, sector in results:
            if sector:
                sector_map[symbol] = sector

    # Inject sector into each position (keyed by ticker, same as collection above)
    for pos in positions:
        pos["sector"] = sector_map.get(pos.get("ticker"))  # None if not found

    return payload
```

**Why `PortfolioService`**: This follows the existing enrichment pattern — `get_monitor_with_risk()` already enriches monitor payloads with per-position risk metrics at the service layer. Placing sector enrichment here means other callers (the existing `/api/positions/monitor` endpoint, MCP tools) can opt into it without duplicating logic in each route.

**Integration in endpoint** (`routes/positions.py`): The holdings endpoint calls `portfolio_svc.enrich_positions_with_sectors(payload)` after `result.to_monitor_view()`:

```python
service = PositionService(user_email=user["email"], user_id=user["user_id"])
result = service.get_all_positions(consolidate=True)
payload = result.to_monitor_view(by_account=False)
portfolio_svc = PortfolioService()
payload = portfolio_svc.enrich_positions_with_sectors(payload)
return payload
```

Note: `PositionService` and `PortfolioService` are separate classes. The endpoint instantiates both — `PositionService` for positions, `PortfolioService` for enrichment. This matches how other routes use `PortfolioService` for market data enrichment.

**Performance**: FMP profile has a 1-week disk cache (`cache_ttl_hours=168` in `fmp/registry.py`), so repeat calls are fast local reads. First call for a new ticker hits FMP API. ThreadPoolExecutor(max_workers=5) matches the existing pattern in `fmp/tools/market.py:767`.

**Failure mode**: If FMP is down or a ticker isn't found, `sector` is `None` for that position. The frontend adapter maps `None` → `undefined` (omitted from output). No 500, no stale data — graceful degradation.

### Phase 2: Frontend — usePositions Hook + PositionsAdapter

**File**: `frontend/packages/chassis/src/queryKeys.ts` (edit)

Add positions holdings query key (user-scoped constant, not portfolio-scoped):
```typescript
export const positionsHoldingsKey = () => ['positionsHoldings'] as const;
```

Add to `AppQueryKey` union type.

**File**: `frontend/packages/chassis/src/services/APIService.ts` (edit)

Add positions holdings fetch method:
```typescript
async getPositionsHoldings(): Promise<PositionsMonitorResponse> {
  return this.request<PositionsMonitorResponse>('/api/positions/holdings');
}
```

This follows the existing pattern of other APIService methods (e.g., `getPlaidHoldings()`, `getRiskScore()`).

**Type definition**: Add `PositionsMonitorResponse` interface manually in `chassis/src/types/index.ts` (not auto-generated — the OpenAPI generator marks position responses as `unknown`). The interface matches the `_build_monitor_payload()` contract:

```typescript
/**
 * Full per-position shape from _build_monitor_payload() (positions.py:415-438).
 * Includes all fields emitted by the backend — adapter picks what it needs.
 */
export interface PositionsMonitorPosition {
  ticker: string;
  name: string | null;
  type: string | null;
  currency: string;
  direction: 'LONG' | 'SHORT' | null;
  quantity: number | null;
  shares: number | null;
  entry_price: number | null;
  weighted_entry_price: number | null;
  current_price: number | null;
  cost_basis: number | null;
  cost_basis_usd: number | null;
  gross_exposure: number | null;
  net_exposure: number | null;
  gross_exposure_local: number | null;
  net_exposure_local: number | null;
  pnl: number | null;              // alias for dollar_pnl (local currency)
  dollar_pnl: number | null;       // P&L in local currency
  pnl_percent: number | null;
  pnl_usd: number | null;          // P&L converted to USD
  pnl_basis_currency: string;      // "USD" or "local"
  entry_price_warning: boolean;
  sector?: string | null;           // Phase 1b: from FMP profile enrichment
  // When by_account=true (not used by holdings endpoint):
  account_name?: string | null;
  brokerage_name?: string | null;
}

export interface PositionsMonitorResponse {
  status: string;
  module: string;
  view: string;
  timestamp: string;
  exposure_currency: string;
  price_pnl_currency: string;
  values_currency: string;
  summary: {
    by_currency: Record<string, unknown>;
    primary_currency: string | null;
    has_multiple_currencies: boolean;
    has_partial_cost_basis: boolean;
    total_positions: number;
    cash_positions_excluded: number;
    positions_missing_price_or_quantity: number;
    portfolio_totals_usd: {
      gross_exposure: number;
      net_exposure: number;
      long_exposure: number;
      short_exposure: number;
      total_pnl_usd: number;
    };
  };
  positions: PositionsMonitorPosition[];
  metadata: {
    consolidated: boolean;
    by_account: boolean;
    sources: string[];
    from_cache: boolean;
    cache_age_hours: number | null;
    cache_by_provider?: Record<string, unknown>;
  };
}
```

**File**: `frontend/packages/connectors/src/features/positions/hooks/usePositions.ts` (new)

- Create `usePositions()` hook as a direct TanStack Query hook (see Architectural Decision above)
- Calls `APIService.getPositionsHoldings()` (not the resolver)
- Uses TanStack Query with `positionsHoldingsKey()` cache key (user-scoped, not portfolio-scoped)
- Transforms response through `PositionsAdapter`
- Returns `{ data, isLoading, error, hasData, hasPortfolio, refetch, currentPortfolio, clearError }`
  - `currentPortfolio`: from `useCurrentPortfolio()` — needed by container for EventBus event filtering (`currentPortfolio.id`)
  - `clearError`: no-op function (errors clear automatically on successful refetch) — matches existing hook pattern used in container retry flow

**File**: `frontend/packages/connectors/src/features/positions/index.ts` (new)

- Barrel export for the positions feature

**File**: `frontend/packages/connectors/src/adapters/PositionsAdapter.ts` (new)

Transforms the monitor view response into the shape `HoldingsView` expects.

**Input shape** (from `to_monitor_view()` → `_build_monitor_payload()`):
```typescript
{
  summary: { portfolio_totals_usd: { gross_exposure, net_exposure, total_pnl_usd, ... }, ... },
  positions: Array<{
    ticker, name, type, currency, direction, quantity, shares,
    entry_price, current_price, cost_basis, gross_exposure, net_exposure,
    dollar_pnl, pnl_percent, pnl_usd, entry_price_warning
  }>,
  metadata: { consolidated, by_account, sources, from_cache, cache_age_hours }
}
```

**Output mapping per position:**
| Monitor field | → | Holdings field | Notes |
|---|---|---|---|
| computed in adapter | → | `id` | `${ticker}:${currency}` — deterministic unique key. Consolidation keeps separate rows per `(ticker, currency)` (`position_service.py:444`), so `ticker` alone can duplicate for multi-currency positions. `HoldingsView` keys on `id \|\| ticker` (`HoldingsView.tsx:426`). |
| `ticker` | → | `ticker` | |
| `name` | → | `name` | Security name from provider |
| `gross_exposure` | → | `value` | Market value in USD |
| `shares` | → | `shares` | Absolute quantity |
| computed in adapter | → | `weight` | `total_gross > 0 ? (gross_exposure / total_gross) * 100 : 0` where `total_gross = summary.portfolio_totals_usd.gross_exposure`. Guard: if denominator is 0, NaN, or Infinity → weight = 0. |
| `current_price` | → | `currentPrice` | |
| `entry_price` | → | `avgCost` | Per-share cost basis |
| `pnl_usd` (fallback `dollar_pnl`) | → | `totalReturn` | P&L in USD. Use `pnl_usd` when available (FX-converted); fall back to `dollar_pnl` for USD-denominated positions where `pnl_usd` is null. |
| `pnl_percent` | → | `totalReturnPercent` | Unitless percentage — safe across currencies |
| `type` | → | `type` | |
| — | → | `isProxy` | Always `false` (see isProxy section) |
| `sector` (from Phase 1b enrichment) | → | `sector` | `position.sector ?? undefined`. FMP profile sector string (e.g., "Technology"). `undefined` if FMP lookup failed or ticker not found. |
| — | → | `volatility` | `undefined` (future: per-holding vol) |
| — | → | `riskScore` | `undefined` (future: per-position risk) |
| — | → | `aiScore` | `undefined` (not planned) |

**IMPORTANT — `null` vs `undefined` normalization**: HoldingsView prop types use `?:` (optional), meaning `undefined` is valid but `null` is not under strict TypeScript. The adapter MUST normalize ALL nullable backend fields:

- **Required string fields**: `name = position.name ?? position.ticker ?? 'Unknown'` (HoldingsView expects `name: string`, not `string | null`)
- **Required number fields**: `value = position.gross_exposure ?? 0`, `shares = position.shares ?? 0` (HoldingsView expects `number`)
- **Optional number fields**: `avgCost = position.entry_price ?? undefined`, `currentPrice = position.current_price ?? undefined`, `totalReturn = (position.pnl_usd ?? position.dollar_pnl) ?? undefined`, `totalReturnPercent = position.pnl_percent ?? undefined` (use `?? undefined` to convert `null` → `undefined`)
- **Enriched optional strings**: `sector = position.sector ?? undefined` (from FMP profile enrichment — may be null if lookup failed)
- **TODO fields**: `volatility`, `riskScore`, `aiScore` → simply omit from output (TypeScript will treat missing optional keys as `undefined`)

**Summary mapping:**
| Monitor field | → | Holdings summary field |
|---|---|---|
| `portfolio_totals_usd.gross_exposure` | → | `totalValue` |
| `metadata.cache_age_hours` | → | used to derive `lastUpdated` display |

**File**: `frontend/packages/connectors/src/index.ts` (edit)

- Add export for `usePositions`

### Phase 3: Frontend — Wire HoldingsViewModernContainer

**File**: `frontend/packages/ui/src/components/dashboard/views/modern/HoldingsViewModernContainer.tsx` (edit)

- Replace `usePortfolioSummary()` with `usePositions()` as the primary data source for the holdings table
- The container currently uses `usePortfolioSummary()` for two things:
  1. **Holdings table data** → replaced by `usePositions()`
  2. **Header summary** (`summary.totalValue`, `summary.lastUpdated`) → replaced by positions monitor summary (`portfolio_totals_usd.gross_exposure`)
- Remove the `PortfolioSummaryDataLike` / `HoldingLike` interfaces (replaced by adapter types)
- Remove the inline `.map()` transform (lines 339-373) — adapter handles this
- **Empty state**: Replace the existing `!hasPortfolio` render gate (which checks portfolio-config selection) with a positions-data-driven empty state: show empty/connect-account prompt when `!isLoading && data.holdings.length === 0`. Since positions are user-scoped (not portfolio-scoped), the portfolio selection state is irrelevant for determining whether holdings exist.
- Keep: `usePlaid()`, `useConnectAccount()`, `usePendingUpdates()`, EventBus listeners, refresh logic
- Keep `currentPortfolio` for EventBus event filtering only (not for empty state gating)
- EventBus listeners: keep existing `'portfolio-data-invalidated'` and `'risk-data-invalidated'` listeners — these already trigger refetch. Since we add `positionsHoldingsKey()` to `CacheCoordinator.invalidatePortfolioData()` (Phase 4), TanStack Query invalidation handles the rest. No new event type needed.

**Header cards note**: The current HoldingsView header shows `totalValue` and `lastUpdated`. Both are available from the monitor view summary. Fields like `riskScore` and `aiScore` that appear in the HoldingsView header are already `null`/`0` today — no regression. These remain TODO items in the backlog.

### Phase 4: Frontend — Cache Integration

**File**: `frontend/packages/chassis/src/services/CacheCoordinator.ts` (edit)

Add positions cache invalidation to the existing methods:

1. In `invalidatePortfolioData()`:
   - Add `'positions'` to the `adapterTypes` array (line 198)
   - Add `positionsHoldingsKey()` to the TanStack Query invalidation (line 223-225) — no `portfolioId` needed since key is user-scoped

2. Import `positionsHoldingsKey` from `../queryKeys`

This ensures that when portfolio data is invalidated (e.g., after account connection, portfolio switch), positions data is also cleared.

### Phase 5: Cleanup — Remove Dead Code

After wiring is complete, remove code that is no longer needed:

**File**: `frontend/packages/connectors/src/adapters/PortfolioSummaryAdapter.ts` (edit)

- Remove the holdings-specific mapping logic (lines ~446-473 that produce the zero-field holdings array with `isProxy`, `factorBetas`, `riskContributionPct`, `beta`, `volatility`, `aiScore`, `alerts`, `trend`)
- `PortfolioSummaryAdapter` should focus on summary metrics (total value, P&L, risk score, performance) — it's still used by `PortfolioOverviewContainer`
- **Type contract update**: `PortfolioSummaryData` interface (line 200) requires `holdings: PortfolioHoldingSummary[]`. Two options:
  1. Make `holdings` optional: `holdings?: PortfolioHoldingSummary[]` — cleanest, but requires checking all consumers
  2. Keep `holdings` as `[]` (empty array) — minimal type change, adapter still produces the field but with no data
  - **Decision**: Option 2 — return `holdings: []` in the transform. This keeps the type contract stable for `PortfolioOverviewContainer` and any other consumers. The enriched holdings data now comes from `usePositions()` only. Grep to verify no consumer iterates over `PortfolioSummaryData.holdings` expecting populated data.

**File**: `frontend/packages/ui/src/components/dashboard/views/modern/HoldingsViewModernContainer.tsx` (edit)

- Remove any remaining references to `portfolioSummary.holdings` or the zero-field fallback mapping
- Remove unused imports (`usePortfolioSummary` if fully replaced)
- Remove `PortfolioSummaryDataLike` and `HoldingLike` interfaces

**Verify no other consumers rely on the removed holdings mapping from PortfolioSummaryAdapter:**
- `PortfolioOverviewContainer` uses `usePortfolioSummary()` but for overview cards, not holdings table — safe
- `ModernDashboardApp.tsx` calls `usePortfolioSummary()` at top level but only uses `_portfolioSummaryHook` (unused variable) — safe

---

## Files Modified (Summary)

| File | Action |
|---|---|
| `routes/positions.py` | **Edit** — add `/api/positions/holdings` endpoint with empty-portfolio guard + sector enrichment call |
| `services/portfolio_service.py` | **Edit** — add `enrich_positions_with_sectors()` method (follows `get_monitor_with_risk()` pattern) |
| `frontend/packages/chassis/src/queryKeys.ts` | **Edit** — add `positionsHoldingsKey` (user-scoped constant) + update `AppQueryKey` |
| `frontend/packages/chassis/src/types/index.ts` | **Edit** — add `PositionsMonitorResponse` + `PositionsMonitorPosition` types |
| `frontend/packages/chassis/src/services/APIService.ts` | **Edit** — add `getPositionsHoldings()` method |
| `frontend/packages/chassis/src/services/CacheCoordinator.ts` | **Edit** — add positions to invalidation |
| `frontend/packages/connectors/src/features/positions/hooks/usePositions.ts` | **New** — positions hook (direct TanStack Query, not resolver) |
| `frontend/packages/connectors/src/features/positions/index.ts` | **New** — barrel export |
| `frontend/packages/connectors/src/adapters/PositionsAdapter.ts` | **New** — positions adapter |
| `frontend/packages/connectors/src/index.ts` | **Edit** — add usePositions export |
| `frontend/packages/ui/.../HoldingsViewModernContainer.tsx` | **Edit** — switch to usePositions |
| `frontend/packages/connectors/src/adapters/PortfolioSummaryAdapter.ts` | **Edit** — remove holdings mapping |

---

## Backlog Items (Not In Scope)

| Item | Notes |
|---|---|
| **PositionService cache verification** | Verify 24-hour DB cache TTL works correctly per provider. Verify webhook/flag-based invalidation (Plaid `DEFAULT_UPDATE`, SnapTrade webhooks) triggers re-fetch vs serving stale cache. Verify free-tier providers (no webhook) gracefully handle staleness. |
| ~~**Sector enrichment**~~ | ~~Add FMP `/profile` batch lookup~~ — **MOVED IN-SCOPE** (Phase 1b). FMP profile with 1-week disk cache + ThreadPoolExecutor. |
| **Per-holding volatility** | Extract from risk analysis `df_stock_returns` or compute from FMP historical prices. |
| **Per-holding riskScore** | Design per-position risk score (concentration, volatility-weighted, drawdown-based). |
| **isProxy detection** | Add `is_cash_proxy` flag to positions pipeline for CUR:XXX → proxy ETF positions. |
| **Per-account breakdown** | Holdings view with `by_account=True` to show per-account positions. |
| **Direction + entry_price_warning** | Add `direction` (LONG/SHORT) and `entryPriceWarning` as optional HoldingsView props when UI needs them. Available in monitor payload but not mapped yet. |
| **Reconcile resolver `positions` with API positions** | When data catalog supports multiple output shapes, unify the resolver-based `positions` source with the API-backed `usePositions` hook. |
| **Provider error surfacing in empty response** | When all providers fail, `get_all_positions()` swallows errors into empty DataFrames (`position_service.py:290-293`). The `provider_errors` dict is on the service instance. Surface these in the response so frontend can warn "data may be stale / providers failed" instead of showing an empty holdings table silently. |

---

## Execution Order

1. Phase 1 (backend endpoint) — verify with `curl` that data is correct
2. Phase 1b (sector enrichment) — verify `curl` response includes `sector` field per position
3. Phase 2 (hook + adapter + query key) — typecheck passes
4. Phase 3 (wire container) — visual verify in Chrome
5. Phase 4 (cache integration) — verify invalidation works
6. Phase 5 (cleanup) — grep to confirm no dead references

---

## Verification

1. **Backend**: `curl http://localhost:8000/api/positions/holdings` (with auth) — returns positions with `current_price`, `entry_price`, `dollar_pnl`, `pnl_percent`, `name`, `sector`
2. `cd frontend && pnpm typecheck` — 0 errors
3. `cd frontend && pnpm lint` — no new errors
4. **Chrome**: Holdings view shows real prices, cost basis, returns for each position
5. **Grep**: No remaining references to `portfolioSummary.holdings` in HoldingsViewModernContainer
6. **Grep**: `usePortfolioSummary` still used by PortfolioOverviewContainer (not deleted)
7. **Cache**: After portfolio switch or account connection, positions data refreshes (not stale)

---

## Codex Review v1 (2026-02-27)

**Result**: FAIL — 8 issues

| # | Severity | Issue | Resolution in v2 |
|---|---|---|---|
| 1 | High | Plan says `to_api_response()` but P&L fields (`entry_price`, `dollar_pnl`, `pnl_percent`) only exist in monitor view | Fixed: endpoint now calls `to_monitor_view(by_account=False)`. Added full field inventory from `_build_monitor_payload()` with line references. |
| 2 | High | `weight` not computed in `to_api_response()` or monitor view — no per-position weight field exists | Fixed: weight computed in PositionsAdapter from `gross_exposure / portfolio_totals_usd.gross_exposure * 100`. Documented explicitly in adapter mapping table. |
| 3 | High | Missing `isProxy` field mapping — `PortfolioSummaryAdapter` sets it, new adapter doesn't | Fixed: Added isProxy section with decision: always `false` for positions (cash filtered by monitor view). Added isProxy detection to backlog. |
| 4 | Medium | Consolidation (`by_account=False`) drops `account_name`/`brokerage_name` | Fixed: Documented this is expected behavior for consolidated holdings table. Added per-account breakdown to backlog. |
| 5 | Medium | No cache invalidation for new `usePositions` hook — CacheCoordinator doesn't know about `positionsKey` | Fixed: Added Phase 4 (cache integration) — adds `positionsKey` to `queryKeys.ts`, wires into CacheCoordinator `invalidatePortfolioData()`. |
| 6 | Medium | Header-card semantics under-specified (`riskScore`, `aiScore` synthetic defaults) | Fixed: Added header cards note — `totalValue` from monitor summary, `riskScore`/`aiScore` remain `null`/`0` (no regression from current state). |
| 7 | Low | Dead-code cleanup: verified correct, no other consumers of holdings mapping | Confirmed. No changes needed. |
| 8 | Low | API types files not listed (`queryKeys.ts`, `CacheCoordinator.ts`) | Fixed: Added both to Files Modified table. |

## Codex Review v2 (2026-02-27)

**Result**: FAIL — 6 issues

| # | Severity | Issue | Resolution in v3 |
|---|---|---|---|
| 1 | High | Empty-portfolio path will 500 — `_consolidate_cross_provider()` raises ValueError on empty DataFrame | Fixed: endpoint catches `ValueError` and returns empty monitor-shaped payload. Documented the guard with line reference to `position_service.py:455-456`. |
| 2 | High | Adapter maps `dollar_pnl` (local currency) to `totalReturn` but UI aggregates in USD | Fixed: map `pnl_usd` (FX-converted) to `totalReturn`, fallback to `dollar_pnl` for USD positions where `pnl_usd` is null. `pnl_percent` is unitless — safe. |
| 3 | Medium | Plan adds `'positions-data-invalidated'` listener but no emitter is planned | Fixed: removed that listener. Existing `'portfolio-data-invalidated'` event already triggers refetch. TanStack Query invalidation via `positionsKey` in CacheCoordinator handles the rest. |
| 4 | Medium | APIService missing `getPositionsHoldings()` method | Fixed: added APIService edit to Phase 2 and Files Modified table. |
| 5 | Medium | Architecture mismatch — existing hooks use `useDataSource` resolver, plan creates parallel direct-query path | Fixed: added "Architectural Decision" section explaining why: existing `positions` resolver serves different shape for 5 downstream resolvers. Direct hook follows `usePortfolioSummary` precedent. Reconciliation added to backlog. |
| 6 | Low | Adapter maps `direction` and `entryPriceWarning` but HoldingsView has no such props | Fixed: dropped both from adapter mapping. Added to backlog for future HoldingsView prop extension. |

## Codex Review v3 (2026-02-27)

**Result**: FAIL — 4 issues

| # | Severity | Issue | Resolution in v4 |
|---|---|---|---|
| 1 | High | Empty-portfolio response is a partial object — missing envelope fields (`status`, `module`, `view`, `timestamp`, currency fields, full `summary`) that `to_monitor_view()` always returns | Fixed: `_empty_monitor_payload()` helper now returns full envelope matching `_build_monitor_payload()` contract (`positions.py:558-588`). Includes all fields: `status`, `module`, `view`, `timestamp`, `exposure_currency`, `price_pnl_currency`, `values_currency`, full `summary` with `by_currency`, `portfolio_totals_usd`, etc. |
| 2 | Medium | `ValueError` catch is too broad — also catches missing-column schema errors, not just empty portfolios | Fixed: discriminate by error message. Only `"empty"` in message → graceful empty response. Missing-column/None errors → re-raise as 500. Documented the three ValueError sources with line references. |
| 3 | Medium | `MonitorViewResponse` type doesn't exist — plan references it but doesn't define or locate it | Fixed: added explicit `PositionsMonitorResponse` + `PositionsMonitorPosition` interfaces to be defined in `chassis/src/types/index.ts` (manual, not auto-generated). Full type definition included in plan. Added to Files Modified table. |
| 4 | Medium | Weight formula has no edge-case handling for zero/invalid denominator | Fixed: added guard in adapter mapping table: `total_gross > 0 ? (gross_exposure / total_gross) * 100 : 0`. If denominator is 0, NaN, or Infinity → weight = 0. |

## Codex Review v4 (2026-02-27)

**Result**: FAIL — 6 issues

| # | Severity | Issue | Resolution in v5 |
|---|---|---|---|
| 1 | High | `ValueError` discrimination `"empty" in ve_msg` is too broad — matches unrelated errors like `"must be a non-empty string"` | Fixed: match exact string `ve_msg == "consolidation input is empty"` instead of substring check. |
| 2 | High | APIService uses `this.fetchWithAuth(...)` which doesn't exist — real method is `this.request<T>(...)` | Fixed: changed to `this.request<PositionsMonitorResponse>('/api/positions/holdings')`. |
| 3 | Medium | `PositionsMonitorPosition` type is incomplete — missing `weighted_entry_price`, `cost_basis_usd`, `gross_exposure_local`, `net_exposure_local`, `pnl`, `pnl_basis_currency` | Fixed: added all fields from `_build_monitor_payload()` (positions.py:415-438). Type now includes every emitted field. |
| 4 | Medium | Empty payload helper omits `metadata.cache_by_provider` which normal responses include | Fixed: added `cache_by_provider: {}` to empty payload and typed it as optional in `PositionsMonitorResponse.metadata`. |
| 5 | Low | `primary_currency` defaults to `"USD"` in empty payload but builder returns `None` when no currencies exist | Fixed: changed to `None` in empty payload. Typed as `string \| null` in `PositionsMonitorResponse`. |
| 6 | Low | Plan text says `total_pnl` in portfolio_totals_usd but actual field is `total_pnl_usd` | Fixed: corrected field name in summary description and input shape docs. |

## Codex Review v5 (2026-02-27)

**Result**: FAIL — 4 issues

| # | Severity | Issue | Resolution in v6 |
|---|---|---|---|
| 1 | High | Empty-portfolio handling masks provider failures — all providers can fail, get swallowed into empty DataFrames, then consolidation raises empty ValueError which returns success-empty | Fixed: acknowledged in endpoint code comments. For v1, log warning and return empty. Added backlog item for surfacing `provider_errors` in response metadata so frontend can warn users. |
| 2 | Medium | `usePositions()` return contract missing `currentPortfolio` and `clearError` — container uses both for EventBus filtering and retry flow | Fixed: added both to `usePositions()` return shape with explanations. `currentPortfolio` from `useCurrentPortfolio()`, `clearError` as no-op (matches existing hook pattern). |
| 3 | Medium | Phase 5 cleanup under-specified — `PortfolioSummaryData` type requires `holdings` field, removing mapping breaks type contract | Fixed: decision to return `holdings: []` (empty array) in transform, keeping type contract stable. Documented both options and rationale. |
| 4 | Medium | No `id` generation in adapter — consolidation keeps separate rows per `(ticker, currency)`, causing duplicate React keys when same ticker held in multiple currencies | Fixed: added `id` = `${ticker}:${currency}` deterministic key in adapter mapping. Documented consolidation behavior reference. |

## Codex Review v6 (2026-02-27)

**Result**: FAIL — 2 issues

| # | Severity | Issue | Resolution in v7 |
|---|---|---|---|
| 1 | High | Portfolio scoping mismatch — positions API is user-scoped (all brokerage accounts), `usePortfolioSummary` is portfolio-scoped (`currentPortfolio.id`). Holdings could show wrong dataset. | Fixed: added "Portfolio Scoping" section explaining why user-scoped is correct for Holdings ("what do I own"). Cache key uses `portfolioId` for cache scope consistency but API doesn't filter by portfolio. Container EventBus filtering continues to work. |
| 2 | High | Adapter maps `riskScore`/`volatility`/`aiScore` to `null` but `HoldingsView` props use `?:` (optional) — `null` is not assignable to `number \| undefined` under strict TypeScript | Fixed: changed all "not yet available" fields from `null` to `undefined`. Added explicit note about `null` vs `undefined` in adapter mapping. |

## Codex Review v7 (2026-02-27)

**Result**: FAIL — 2 issues

| # | Severity | Issue | Resolution in v8 |
|---|---|---|---|
| 1 | High | Adapter doesn't normalize all nullable backend fields — `name` (`string \| null` from backend) mapped to `name` (`string` required by HoldingsView), `entry_price`/`current_price`/P&L are `number \| null` but HoldingsView expects `number \| undefined` | Fixed: added comprehensive null→undefined normalization rules for every mapped field. Required strings use fallback values (`name ?? ticker ?? 'Unknown'`). Required numbers use `?? 0`. Optional numbers use `?? undefined`. TODO fields are omitted entirely. |
| 2 | Medium | Cache key is portfolio-scoped (`positionsKey(portfolioId)`) but data is user-scoped — switching portfolios creates stale duplicate cache entries | Fixed: changed to user-scoped constant key `positionsHoldingsKey()` = `['positionsHoldings']`. Single entry, no portfolio discrimination. CacheCoordinator invalidates without `portfolioId`. |

## Codex Review v8 (2026-02-27)

**Result**: PASS — no implementation blockers found.

## Codex Review v9 (2026-02-27) — after Phase 1b sector addition

**Result**: FAIL — 1 issue

| # | Severity | Issue | Resolution in v10 |
|---|---|---|---|
| 1 | Medium | `PositionsMonitorPosition` interface missing `sector` field added by Phase 1b enrichment | Fixed: added `sector?: string \| null` to interface. |

## Codex Review v10 (2026-02-27)

**Result**: FAIL — 2 issues (1 real, 1 already-resolved re-flag)

| # | Severity | Issue | Resolution in v11 |
|---|---|---|---|
| 1 | Medium | `fmp_ticker` reference in sector write-back (line 279) inconsistent with collection using only `ticker` | Fixed: removed `fmp_ticker` fallback, both paths now use `pos.get("ticker")` consistently. |
| 2 | Low | `account_name`/`brokerage_name` typed as `string` but backend can emit `null` | Fixed: changed to `string \| null`. |

## Codex Review v11 (2026-02-27)

**Result**: FAIL — 2 issues

| # | Severity | Issue | Resolution in v12 |
|---|---|---|---|
| 1 | Medium | `positionsKey` vs `positionsHoldingsKey` naming inconsistency across plan sections | Fixed: normalized all references to `positionsHoldingsKey()`. |
| 2 | Medium | Container `!hasPortfolio` render gate suppresses valid user-scoped positions data when no portfolio is selected | Fixed: replaced with positions-data-driven empty state (`!isLoading && data.holdings.length === 0`). Keep `currentPortfolio` only for EventBus filtering. |

## Codex Review v12 (2026-02-27)

**Result**: PASS — no blocking issues found.

## Codex Review v13 (2026-02-27) — after moving enrichment to PortfolioService

**Result**: FAIL — 2 issues

| # | Severity | Issue | Resolution in v14 |
|---|---|---|---|
| 1 | High | `PortfolioService(user_email=user["email"])` — constructor doesn't accept `user_email` kwarg | Fixed: changed to `PortfolioService()` (no args needed). |
| 2 | High | Integration snippet used `service.enrich_positions_with_sectors()` (PositionService) instead of `portfolio_svc` (PortfolioService) | Fixed: normalized both snippets to use `portfolio_svc`. |

## Codex Review v14 (2026-02-27)

**Result**: PASS — no blocking issues found.

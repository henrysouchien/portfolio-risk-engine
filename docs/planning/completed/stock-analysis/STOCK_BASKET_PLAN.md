# Stock Basket / Custom Index

**Date**: 2026-02-27
**Status**: Phase 2 complete (commit `240f00ea`), Phases 3-5 planned
**Codex review**: 3 rounds — PASS. Addressed trade execution architecture, returns filtering, factor panel injection, trade semantics, migration, drift warnings
**Risk**: Low-Medium — builds on existing infrastructure, no changes to core analysis pipeline

## Context

Create and manage named baskets of stocks for two use cases:
1. **Returns analysis** — track basket as a factor or custom index (aggregate returns, correlation to portfolio, attribution)
2. **Direct execution** — execute a basket as a single order (buy/sell proportionally, rebalance to target weights)

## Existing Infrastructure

Significant infrastructure already exists — the main gap is MCP tooling and analytics integration.

### Already built

| Layer | Status | Location |
|-------|--------|----------|
| Database table | Done | `database/schema.sql:609` — `user_factor_groups` with tickers (JSONB), weights (JSONB), weighting_method |
| DB client CRUD | Done | `inputs/database_client.py:1862` — `create/get/update/delete_factor_group()` |
| Pydantic models | Done | `models/factor_intelligence_models.py:353` — request/response models with validation |
| REST API | Done | `routes/factor_intelligence.py` — 6 endpoints on `/api/factor-groups` (list, get, create, update, delete, validate) |
| Returns computation | Done | `portfolio_risk_engine/portfolio_risk.py:459` — `get_returns_dataframe()` works for any ticker+weights dict |
| Factor analysis | Done | `services/factor_intelligence_service.py` — correlation, performance, returns analysis |
| Trade preview/execute | Done | `mcp_tools/trading.py` — single-leg `preview_trade()` + `execute_trade()` |
| ETF holdings data | Done | `fmp/registry.py` — `etf_holdings` endpoint for seeding baskets |

### Not built

| Layer | Gap |
|-------|-----|
| MCP tools | No basket CRUD or analysis tools registered in `mcp_server.py` |
| Basket returns computation | No `compute_basket_returns()` wrapper |
| Basket-as-factor integration | No wiring from `user_factor_groups` → factor analysis panel |
| Multi-leg trade execution | `preview_trade()` is single-ticker only |
| ETF seeding workflow | No tool to create basket from ETF holdings |

## Implementation

### Phase 1: MCP CRUD Tools

Register basket management tools in `mcp_server.py` backed by the existing REST API / DB client layer.

**New file**: `mcp_tools/baskets.py`

**Tools:**
- `create_basket(name, tickers, weighting_method?, weights?, description?)` — create a named basket. Validates tickers exist via FMP. Default weighting: equal.
- `list_baskets()` — list all baskets for the current user with ticker counts and weighting methods.
- `get_basket(name)` — get basket details including resolved weights (compute equal/market-cap if not custom).
- `update_basket(name, tickers?, weights?, weighting_method?, description?)` — update basket fields. Only specified fields change.
- `delete_basket(name)` — delete a basket.

**Weight resolution logic** (in `get_basket` and anywhere weights are needed):
- `equal`: `1/N` for each ticker
- `market_cap`: fetch market caps from FMP profile, normalize to sum=1
- `custom`: use stored weights directly, validate they sum to ~1.0

**Implementation notes:**
- Reuse existing `DatabaseClient` methods — no new SQL needed
- Reuse existing Pydantic models for validation
- Apply `@handle_mcp_errors` decorator (standard pattern)
- User resolution via `_load_portfolio_for_analysis()` pattern (get user from settings)

### Phase 2: Basket Returns Analysis

Compute weighted returns for a basket and expose as an MCP tool.

**New function** in `services/basket_service.py`:

```python
def compute_basket_returns(
    tickers: List[str],
    weights: Dict[str, float],
    start_date: str,
    end_date: str,
) -> pd.Series:
    """Compute weighted return series for a basket of stocks."""
    returns_df = get_returns_dataframe(weights, start_date, end_date)
    # Filter to tickers that actually have data (some may be missing/illiquid)
    available = [t for t in weights if t in returns_df.columns]
    if not available:
        raise ValueError("No price data available for any basket component")
    # Re-normalize weights to available tickers only
    total = sum(weights[t] for t in available)
    adjusted = {t: weights[t] / total for t in available}
    return compute_portfolio_returns(returns_df, adjusted)
```

**Data availability handling**: `get_returns_dataframe()` silently drops tickers without price history. The wrapper must detect missing tickers, re-normalize weights, and report which components were excluded. The analysis result should include a `data_coverage` field listing available vs excluded tickers.

**New MCP tool**: `analyze_basket(name, start_date?, end_date?)`

Returns:
- Basket total return, annualized return, volatility, Sharpe ratio, max drawdown
- Per-component returns and contribution to basket return
- Correlation to user's portfolio (if portfolio exists)
- Monthly return series

**Result object**: `BasketAnalysisResult` in `core/result_objects/` with `get_agent_snapshot()` for agent format.

### Phase 3: Basket as Custom Factor

Wire baskets into the factor analysis system so they appear alongside standard factors (SPY, QQQ, sector ETFs).

**Changes to** `services/factor_intelligence_service.py`:
- When loading factor proxies, also load user's baskets from `user_factor_groups`
- Compute basket return series using Phase 2's `compute_basket_returns()`
- **Merge step**: append computed basket return columns to the factor returns panel (these are synthetic series, not fetched from FMP like normal factors). Must also update `panel.attrs["categories"]` to include basket names under a new `"user_baskets"` category.
- **Cache key treatment**: include basket names + `updated_at` timestamps in the cache key so cache invalidates when baskets are modified. Use a hash of `(basket_name, updated_at)` tuples.
- Baskets appear in correlation matrices, factor performance tables, and recommendations

**New MCP tool**: `analyze_basket_vs_portfolio(basket_name)` — focused comparison of basket returns vs portfolio returns with correlation, beta, and tracking error.

### Phase 4: Multi-Leg Trade Execution

Enable executing a basket as a single logical trade operation.

**Architecture**: The existing trade system persists previews in the `trade_previews` DB table with a TTL (not in-memory). Multi-leg basket trades work within this architecture — each component generates its own `preview_id` in the DB. A new `basket_trade_groups` table links them.

**New database table**: `basket_trade_groups` (migration file: `database/migrations/YYYYMMDD_add_basket_trade_groups.sql`, run as part of Phase 4 implementation)
```sql
CREATE TABLE IF NOT EXISTS basket_trade_groups (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id),
    basket_name VARCHAR(100) NOT NULL,
    action VARCHAR(20) NOT NULL,          -- 'buy', 'sell', 'rebalance'
    total_value DECIMAL(15,2),
    preview_ids JSONB NOT NULL,           -- [preview_id_1, preview_id_2, ...]
    status VARCHAR(20) DEFAULT 'preview', -- 'preview', 'executing', 'completed', 'partial', 'failed'
    leg_statuses JSONB,                   -- {preview_id: "filled"|"failed"|"pending"|"cancelled"}
    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP
);
```

**New MCP tools:**
- `preview_basket_trade(name, action, total_value)` — expand basket into component orders:
  - `action`: `buy` (allocate $X across basket), `sell` (liquidate proportionally), `rebalance` (adjust to target weights)
  - Compute per-ticker share quantities from weights × total_value ÷ current prices
  - Call existing `preview_trade()` for each component — each gets its own DB-persisted preview_id
  - Create a `basket_trade_groups` row linking all preview_ids
  - Aggregate: total estimated cost, per-leg details, validation warnings
  - Return `basket_group_id` for execution

- `execute_basket_trade(basket_group_id)` — execute all legs:
  - Load component preview_ids from `basket_trade_groups`
  - Validate all previews are still within TTL (re-preview expired legs automatically)
  - Submit legs sequentially via existing `execute_trade()` per preview_id
  - Update `leg_statuses` after each leg completes
  - If a leg fails: log error, continue with remaining legs (best-effort, not all-or-none)
  - Update group `status` to `completed` (all filled), `partial` (some failed), or `failed` (all failed)
  - Return composite result with per-leg fill/fail details

- `cancel_basket_trade(basket_group_id)` — cancel pending legs:
  - Only cancels legs not yet executed
  - Updates group status accordingly

**Result objects**: `BasketTradePreview`, `BasketTradeExecution` as new dataclasses in `brokerage/trade_objects.py`.

**Semantics:**
- **Not atomic**: legs execute independently. Partial fills are acceptable — the agent reports what filled vs what failed.
- **Preview expiry**: uses the same TTL as single-leg previews (from `settings.py`). If a preview expires before execution, the tool re-previews that leg automatically. Re-previewed legs may have different prices/quantities — the execute response includes a `drift_warnings` list noting any legs where the re-previewed cost differs from the original by more than 1%.
- **Idempotency**: `execute_basket_trade` checks group status — if already `completed` or `executing`, returns the existing result instead of re-executing.
- **Cancel**: only applies to legs in `pending` status. Legs already `filled` cannot be reversed (would need a separate sell order).

### Phase 5: ETF Seeding

Create baskets from existing ETF holdings — a quick way to build sector/thematic baskets.

**New MCP tool**: `create_basket_from_etf(etf_ticker, basket_name, top_n?, min_weight?)`
- Fetch ETF holdings via FMP `etf_holdings` endpoint
- Filter to top N holdings by weight (default 10) or holdings above min_weight
- Normalize weights to sum to 1.0
- Create basket with `weighting_method='custom'` and the extracted weights
- Return the created basket with component details

## Execution Order

1. Phase 1 (CRUD) — standalone, no dependencies
2. Phase 2 (returns analysis) — depends on Phase 1 for basket resolution
3. Phase 3 (factor integration) — depends on Phase 2 for return computation
4. Phase 4 (trade execution) — depends on Phase 1, independent of Phase 2-3
5. Phase 5 (ETF seeding) — depends on Phase 1 only

Phases 2-3 and Phase 4 can run in parallel after Phase 1.

## Guardrails

1. **No changes to existing analysis pipeline** — baskets plug in via existing `get_returns_dataframe()` and `compute_portfolio_returns()`
2. **Reuse existing basket table** — `user_factor_groups` already has the right schema for basket CRUD
3. **One new table** — `basket_trade_groups` for multi-leg trade grouping (Phase 4 only)
4. **No new REST endpoints** — basket CRUD endpoints already exist at `/api/factor-groups`
5. **Reuse existing trade infrastructure** — multi-leg trades compose existing single-leg `preview_trade()` / `execute_trade()`, each preview persisted in existing `trade_previews` table
6. **Agent format** — all new MCP tools should support `format="agent"` with `get_agent_snapshot()` on result objects
7. **Graceful data degradation** — basket analysis handles missing ticker data by re-normalizing weights and reporting excluded components

## Verification

Per phase:
1. **Phase 1**: Create/list/get/update/delete baskets via MCP. Verify persistence across sessions.
2. **Phase 2**: `analyze_basket("tech_leaders")` returns correct weighted returns matching manual calculation.
3. **Phase 3**: Baskets appear in `get_factor_analysis()` output alongside standard factors.
4. **Phase 4**: `preview_basket_trade("tech_leaders", "buy", 10000)` returns per-leg previews. Execute and verify orders placed.
5. **Phase 5**: `create_basket_from_etf("XLK", "tech_sector", top_n=10)` creates basket matching XLK top holdings.

End-to-end: Create basket → analyze returns → compare to portfolio → preview trade → execute.

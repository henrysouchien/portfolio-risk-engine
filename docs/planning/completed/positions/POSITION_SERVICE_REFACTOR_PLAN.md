# Position Service Refactor Plan

> **Goal:** Move cache logic and database operations from routes into PositionService,
> making it the single source of truth for position retrieval across the application.

---

## Priority & Timing

**Status:** ✅ COMPLETED — optional cleanup deferred (see Phase 3)

**Rationale:** This was a refactoring task (not new functionality) to centralize cache
and DB logic in PositionService. The consolidation is now complete.

**Execution status:**
- ✅ Phase 1: Complete Position Module core features (current PositionService, CLI, etc.)
- ✅ Phase 2: Consolidate cache logic in PositionService + simplify routes
- ✅ Phase 4: DB schema enhancement for name/brokerage/account metadata
- 🔲 Phase 3: Optional cleanup items (see Phase 3 section)

---

## Alignment with MCP/CLI Plan

This refactor enhances the MCP/CLI implementation which is now complete:

| Component | Status | Notes |
|-----------|--------|-------|
| `PositionResult` | ✅ Done | `core/result_objects.py` |
| `PositionService` | ✅ Done | Returns `PositionResult` |
| CLI (`run_positions.py`) | ✅ Done | `--format json/cli`, `--output`, `--to-risk` |
| MCP (`mcp_server.py`) | ✅ Done | `portfolio-mcp` with `get_positions()` tool |
| **Cache integration** | ✅ Done | `use_cache`, `force_refresh` wired through |

**After this refactor (implemented):** MCP tool gains cache control parameters:
```python
get_positions(use_cache=True, force_refresh=False)  # New params
```

**PositionResult is the single return/transport type.** PositionService may use
DataFrames internally, but it returns a PositionResult suitable for MCP/CLI/API.

---

## Current Architecture (Before)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ routes/plaid.py                                                              │
│   GET /plaid/holdings                                                        │
│   ├── Cache check (MAX(created_at) query)                                   │
│   ├── Load from DB if cache fresh                                           │
│   ├── Calculate market values (shares × latest_price)                       │
│   ├── Call loader if cache expired                                          │
│   ├── Save to DB via PortfolioManager                                       │
│   └── Format HTTP response                                                  │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ routes/snaptrade.py                                                          │
│   GET /snaptrade/holdings                                                    │
│   ├── Cache check (MAX(created_at) query)          ← DUPLICATE LOGIC        │
│   ├── Load from DB if cache fresh                  ← DUPLICATE LOGIC        │
│   ├── Calculate market values                      ← DUPLICATE LOGIC        │
│   ├── Call loader if cache expired                                          │
│   ├── Save to DB via PortfolioManager                                       │
│   └── Format HTTP response                                                  │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ services/position_service.py                                                 │
│   ├── fetch_plaid_positions()    → Calls loader directly (NO CACHE)         │
│   ├── fetch_snaptrade_positions() → Calls loader directly (NO CACHE)        │
│   └── get_all_positions()        → Combines both (NO CACHE)                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Problems:**
1. Cache logic duplicated in both routes (~150 lines each)
2. PositionService bypasses cache entirely (hits APIs every time)
3. No single source of truth for position retrieval
4. Hard to add new consumers (position tracker) without duplicating again

---

## Target Architecture (After)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ services/position_service.py                                                 │
│   THE SINGLE SOURCE OF TRUTH FOR POSITIONS                                   │
│                                                                              │
│   get_positions(provider, use_cache=True, force_refresh=False)              │
│   ├── If use_cache=True:                                                    │
│   │   ├── Check MAX(created_at) for provider                                │
│   │   ├── If < 24h: load from DB, calculate market values, return           │
│   │   └── If >= 24h or force_refresh: fall through to API                   │
│   ├── Call provider loader                                                  │
│   ├── Save to DB                                                            │
│   └── Return standardized position data                                     │
└─────────────────────────────────────────────────────────────────────────────┘
        ↑                    ↑                    ↑
        │                    │                    │
┌───────┴───────┐    ┌───────┴───────┐    ┌───────┴───────┐
│ routes/plaid  │    │ routes/snap   │    │ Position      │
│ (thin HTTP)   │    │ (thin HTTP)   │    │ Tracker       │
│               │    │               │    │ (future)      │
│ - Auth        │    │ - Auth        │    │               │
│ - Call svc    │    │ - Call svc    │    │               │
│ - Format resp │    │ - Format resp │    │               │
└───────────────┘    └───────────────┘    └───────────────┘
```

---

## What Moves to PositionService

### From routes/plaid.py (lines 693-920)

| Component | Lines | Description |
|-----------|-------|-------------|
| Cache check | 700-720 | `MAX(created_at)` query for plaid positions |
| Cache hit path | 727-802 | Load from DB, filter by provider, calc market values |
| Fresh fetch | 814-826 | Call `load_all_user_holdings()` |
| DB save | 828-856 | `PortfolioManager.save_portfolio_data()` |

### From routes/snaptrade.py (lines 558-765)

| Component | Lines | Description |
|-----------|-------|-------------|
| Cache check | 565-585 | `MAX(created_at)` query for snaptrade positions |
| Cache hit path | 592-667 | Load from DB, filter by provider, calc market values |
| Fresh fetch | 681-685 | Call `load_all_user_snaptrade_holdings()` |
| DB save | 688-706 | `PortfolioManager.save_portfolio_data()` |

---

## PositionService New Interface

```python
@dataclass
class PositionServiceConfig:
    user_email: str
    user_id: Optional[int] = None             # None for CLI/tests, int for API calls
    region: str = DEFAULT_REGION
    plaid_client: Optional[object] = None
    snaptrade_client: Optional[object] = None


@dataclass
class PositionResult:
    """Return + transport type for position queries.

    NOTE: Already implemented in core/result_objects.py.
    See POSITION_RESULT_IMPLEMENTATION_PLAN.md (completed) for details.
    """
    # ... (see core/result_objects.py for full implementation)


class PositionService:
    CACHE_HOURS = 24

    def __init__(
        self,
        user_email: str,
        user_id: Optional[int] = None,        # None for CLI/tests, int for API calls
        plaid_client: Optional[object] = None,
        snaptrade_client: Optional[object] = None,
        region: str = DEFAULT_REGION,
    ) -> None:
        ...

    # === PRIMARY API ===

    def get_positions(
        self,
        provider: str,                        # 'plaid' or 'snaptrade'
        use_cache: bool = True,
        force_refresh: bool = False,
    ) -> PositionResult:
        """
        Get positions for a provider with caching support.

        Args:
            provider: 'plaid' or 'snaptrade'
            use_cache: If True, check DB cache first (default)
            force_refresh: If True, bypass cache and call API

        Returns:
            PositionResult with positions list + metadata
        """
        ...

    def get_all_positions(
        self,
        use_cache: bool = True,
        consolidate: bool = False,
    ) -> PositionResult:
        """Get positions from all providers."""
        ...

    # === CACHE OPERATIONS (internal) ===

    def _check_cache_freshness(self, provider: str) -> tuple[bool, Optional[float]]:
        """
        Check if cached data is fresh for provider.

        Returns:
            (is_fresh, hours_ago) - is_fresh=True if cache < 24h old
        """
        ...

    def _load_cached_positions(self, provider: str) -> pd.DataFrame:
        """
        Load positions from DB filtered by provider.

        NOTE: get_portfolio_positions() returns ALL providers' positions.
        We must filter by position_source to isolate this provider's data.

        NOTE: This method is only called when cache is fresh (checked by
        _check_cache_freshness first). If a provider has zero positions,
        MAX(created_at) returns NULL and is treated as cache miss, so this
        method won't be called for truly empty providers.

        Returns:
            DataFrame with positions for this provider.
        """
        user_id = self._get_user_id()

        # Use get_db_session() context manager to avoid connection leaks
        with get_db_session() as conn:
            db_client = DatabaseClient(conn)

            # Load ALL positions for CURRENT_PORTFOLIO (includes all providers)
            all_positions = db_client.get_portfolio_positions(user_id, "CURRENT_PORTFOLIO")

        # Filter to ONLY this provider's positions
        positions = [p for p in all_positions if p.get('position_source') == provider]

        return pd.DataFrame(positions)

    def _calculate_market_values(self, positions: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate current market values and update the 'value' column.

        NOTE: PositionsData requires 'value' field (not 'market_value').
        The 'market_value' naming is only used in API response formatting.

        Logic:
        - type='cash': value = quantity (quantity IS the dollar amount)
        - other types: value = quantity × latest_price(ticker)
        """
        ...

    # === API OPERATIONS (internal) ===

    def _fetch_fresh_positions(self, provider: str) -> pd.DataFrame:
        """Call provider loader to get fresh positions."""
        ...

    def _save_positions_to_db(self, df: pd.DataFrame, provider: str) -> None:
        """Save positions to DB (provider-scoped delete + insert)."""
        ...
```

---

## Simplified Route Structure (After)

### routes/plaid.py

```python
@plaid_router.get("/holdings", response_model=get_response_model(HoldingsResponse))
async def get_plaid_holdings(request: Request):
    """Get Plaid holdings with 24-hour cache."""

    # 1. Authentication (stays in route)
    user = await get_current_user_plaid(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        # 2. Delegate to PositionService
        position_service = PositionService(
            user_email=user['email'],
            user_id=user['user_id'],
            plaid_client=plaid_client
        )

        result = position_service.get_positions(provider='plaid', use_cache=True)

        # 3. Format HTTP response using result.to_api_response()
        api_data = result.to_api_response()
        return HoldingsResponse(
            success=True,
            holdings=api_data["data"],
            message=api_data["metadata"].get("message", "Holdings retrieved")
        )

    except Exception as e:
        log_error_json("plaid_holdings", "get_holdings", e)
        raise HTTPException(status_code=500, detail=str(e))
```

---

## Dependencies PositionService Will Need

```python
# Database access
from database import get_db_session
from inputs.database_client import DatabaseClient

# Portfolio management (for saving)
from inputs.portfolio_manager import PortfolioManager

# Loaders
from plaid_loader import load_all_user_holdings
from snaptrade_loader import load_all_user_snaptrade_holdings

# Data conversion (to be centralized after cache refactor)
from plaid_loader import convert_plaid_holdings_to_portfolio_data
from snaptrade_loader import convert_snaptrade_holdings_to_portfolio_data

# Price lookup
from run_portfolio_risk import latest_price

# Logging
from utils.logging import portfolio_logger
```

---

## Implementation Phases

### Phase 1: Add Cache Logic to PositionService (Non-Breaking)

**Status:** ✅ COMPLETED

1. Add `user_id` to `PositionServiceConfig`
2. Add `_check_cache_freshness(provider)` method
3. Add `_load_cached_positions(provider)` method
4. Add `_calculate_market_values(df)` method
5. Add `_save_positions_to_db(df, provider)` method
6. Update `fetch_plaid_positions()` to use cache
7. Update `fetch_snaptrade_positions()` to use cache

**Note:** PositionResult dataclass already exists in `core/result_objects.py` (completed in Phase 1.5).

**Test:** Verify PositionService returns cached data when fresh

### Phase 1.5: Unify Conversion + Transport Result (Non-Breaking) — PARTIALLY COMPLETE

**Status:** 🟡 PARTIALLY COMPLETE

**Completed:**
- ✅ `PositionsData` in `core/data_objects.py` with `to_portfolio_data()`
- ✅ `PositionResult` in `core/result_objects.py` with `to_api_response()`, `to_cli_report()`, `to_summary()`
- ✅ `PositionService.get_all_positions()` returns `PositionResult` directly
- ✅ Chain integration tests in `tests/unit/test_position_chain.py`

**Remaining:**
1. [ ] Extract shared `positions_df_to_portfolio_data(...)` helper (optional cleanup)
2. [ ] Update routes to use `result.to_api_response()` (optional; current routes keep legacy response shape)

**Cache Refactor Integration:** Phase 1 will add `from_cache` and `cache_age_hours` fields
to `PositionsData` when implementing `get_positions(..., use_cache=True)`.

**Test:** Ensure conversion outputs match existing behavior for Plaid/SnapTrade

### Phase 2: Simplify Routes (Breaking - Routes Change)

**Status:** ✅ COMPLETED

1. Update `routes/plaid.py` `get_plaid_holdings()` to use PositionService
2. Update `routes/snaptrade.py` `get_holdings()` to use PositionService
3. Remove duplicated cache logic from routes
4. Ensure HTTP response format unchanged (backward compatible)

**Test:** Verify API responses are identical before/after

### Phase 3: Clean Up (Optional)

**Status:** 🔲 NOT STARTED (Optional)

1. Remove any dead code from routes
   - NOTE: Optional cleanup only; safe to defer.
2. Update documentation
   - NOTE: Optional polish; consider after major changes settle.
3. Consider adding `POST /holdings/refresh` endpoints that call `force_refresh=True`
   - NOTE: New API surface; only add if clients need explicit refresh.
4. Move YAML fallback file generation from `routes/plaid.py` to PositionService
   - NOTE: Keeps routes thin; low risk if behavior stays identical.
   - Currently in Plaid route lines 725-743: writes `user_yaml_file` on fresh fetch
   - Could be moved to `_save_positions_to_db()` or a separate `_write_fallback_yaml()` method
   - Makes routes purely thin auth + delegation wrappers

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Breaking API response format | Keep route response formatting unchanged |
| Missing edge cases | Port exact logic from routes, don't rewrite |
| DB connection handling | Use same `get_db_session()` pattern as routes |
| Loader client initialization | Keep existing `_get_plaid_client()` pattern |

---

## Design Decisions & Clarifications

### 1. Cache Scoping (User + Provider + Portfolio)

Cache freshness checks MUST be scoped to user, portfolio, AND provider:

```python
def _check_cache_freshness(self, provider: str) -> tuple[bool, Optional[float]]:
    """
    Check if cached data is fresh for provider.

    Returns:
        (is_fresh, hours_ago) - is_fresh=True if cache < 24h old
        (False, None) if portfolio doesn't exist (cache miss)
    """
    user_id = self._get_user_id()

    # Use get_db_session() context manager to avoid connection leaks
    with get_db_session() as conn:
        db_client = DatabaseClient(conn)
        portfolio_id = db_client.get_portfolio_id(user_id, "CURRENT_PORTFOLIO")

        # Portfolio not found = cache miss (need to fetch fresh)
        if portfolio_id is None:
            return (False, None)

        # Query provider-specific last sync time
        cursor = conn.cursor()
        cursor.execute("""
            SELECT MAX(created_at) as last_sync
            FROM positions
            WHERE portfolio_id = %s AND position_source = %s
        """, (portfolio_id, provider))

        # ... UTC timestamp comparison ...
```

Note: The column is `position_source` (not `provider`). The `portfolio_id` is derived
from `user_id + portfolio_name`, so this implicitly scopes to the user.

**Cache Miss Conditions:**
- `portfolio_id` is None (portfolio doesn't exist yet)
- `last_sync` is None (no positions for this provider yet)
- `hours_ago >= CACHE_HOURS` (cache expired)

**Empty Positions Handling (Architectural Note):**

With the current approach (`MAX(created_at)` query), a provider with zero positions
returns `last_sync = NULL`, which is treated as a cache miss. This means:

| Condition | `last_sync` value | Action |
|-----------|-------------------|--------|
| Provider has positions, cache fresh | timestamp < 24h | Use cached data |
| Provider has positions, cache stale | timestamp >= 24h | Fetch fresh from API |
| Provider has zero positions | NULL | Fetch fresh from API (every time) |

**Accepted behavior:** Users with no positions for a provider will hit the API on
every call. This matches current route behavior and is acceptable because:
- Users with zero positions are rare (why connect an empty account?)
- The API call is cheap if it returns empty
- Adding a separate sync marker table adds complexity for little benefit

**Future enhancement:** If this becomes a problem, add a `provider_syncs` table:
```sql
CREATE TABLE provider_syncs (
    portfolio_id INT,
    provider VARCHAR(20),
    last_sync TIMESTAMP,
    PRIMARY KEY (portfolio_id, provider)
);
```
Then check `provider_syncs.last_sync` instead of `MAX(positions.created_at)`.

**Timestamps:** All `created_at` timestamps are stored in UTC. The 24-hour freshness
check uses UTC comparison to avoid timezone issues.

### 2. Market Value Calculation on Cache Hit

**Decision:** Recalculate market values from cached prices (status quo).

The position cache stores **share counts only**. On cache hit, market values are
recalculated using `latest_price()` which has its own caching layer:

- `latest_price()` → `fetch_monthly_close()` → disk cache + LRU cache
- Prices are month-end closes, not real-time
- This means position cache saves Plaid/SnapTrade API costs, not FMP API costs

This is the correct design because:
- Share counts rarely change (only on trades)
- Prices should reflect current values (from cached month-end prices)
- Storing market_value would create stale valuations

### 3. Transaction Safety for Save Operations

**Resolved by delegation:** PositionService delegates saving to the existing
`PortfolioManager` → `DatabaseClient.save_portfolio()` chain, which already has
transaction safety:

```python
# In DatabaseClient.save_portfolio() - ALREADY IMPLEMENTED
try:
    conn.autocommit = False
    # Provider-scoped DELETE (uses position_source column)
    cursor.execute("DELETE FROM positions WHERE portfolio_id = %s AND position_source = %s", ...)
    # INSERT new positions
    cursor.execute("INSERT INTO positions ...", ...)
    conn.commit()
except Exception:
    conn.rollback()
    raise
```

**PositionService simply delegates:**
```python
def _save_positions_to_db(self, df: pd.DataFrame, provider: str) -> None:
    # Must resolve user_id BEFORE constructing PortfolioManager (it raises if missing)
    user_id = self._get_user_id()

    # Convert DataFrame to PortfolioData using PROVIDER-SPECIFIC conversion
    # This preserves type/currency/cost_basis/cash classification correctly
    if provider == 'plaid':
        from plaid_loader import convert_plaid_holdings_to_portfolio_data
        portfolio_data = convert_plaid_holdings_to_portfolio_data(
            df,
            user_email=self.config.user_email,
            portfolio_name="CURRENT_PORTFOLIO"  # MUST match cache scoping
        )
    elif provider == 'snaptrade':
        from snaptrade_loader import convert_snaptrade_holdings_to_portfolio_data
        portfolio_data = convert_snaptrade_holdings_to_portfolio_data(
            df,
            user_email=self.config.user_email,
            portfolio_name="CURRENT_PORTFOLIO"  # MUST match cache scoping
        )
    else:
        raise ValueError(f"Unknown provider: {provider}")

    # Set import_source so PortfolioManager knows which provider's positions to replace
    # (save_portfolio_data infers position_source from portfolio_data.import_source)
    portfolio_data.import_source = provider

    # Delegate to PortfolioManager (use_database=True requires user_id)
    portfolio_manager = PortfolioManager(use_database=True, user_id=user_id)
    portfolio_manager.save_portfolio_data(portfolio_data)
```

**Why provider-specific conversion?** Each loader has different column mappings and
cash classification logic. Using generic conversion would cause semantic drift vs routes.

**Note:** `DatabaseClient.save_portfolio()` also clears/reinserts factor proxies on every save.
This is consistent with current route behavior, but if PositionService saves more frequently,
this overhead should be monitored.

No need to reimplement transaction handling - it's already there.

### 4. user_id Pattern (Matches PortfolioData)

`user_id` follows the established pattern from `PortfolioData`:

```python
user_id: Optional[int] = None  # None for CLI/tests, int for API calls
```

**Usage:**
- **API routes:** Pass `user_id` from authenticated user context
- **CLI/MCP:** Pass `None`, service looks up from `user_email` when needed

```python
def _get_user_id(self) -> int:
    """Get user_id, looking up from email if not provided."""
    if self.config.user_id is not None:
        return self.config.user_id
    # Fallback: lookup from database by email
    return self._lookup_user_id_by_email(self.config.user_email)
```

### 5. get_all_positions() Cache Behavior

When fetching from multiple providers, track per-provider cache state to avoid
misleading consumers about freshness:

```python
def get_all_positions(self, use_cache: bool = True) -> PositionResult:
    plaid_result = self.get_positions('plaid', use_cache=use_cache)
    snaptrade_result = self.get_positions('snaptrade', use_cache=use_cache)

    # Combine positions
    combined_positions = plaid_result.data.positions + snaptrade_result.data.positions

    # Summary flags for PositionsData (existing fields)
    all_from_cache = (
        plaid_result.data.from_cache and snaptrade_result.data.from_cache
    )
    oldest_cache_hours = max(
        plaid_result.data.cache_age_hours or 0,
        snaptrade_result.data.cache_age_hours or 0,
    )

    # Per-provider detail goes on PositionResult (transport layer), not PositionsData
    # This avoids adding new fields to the data layer
    cache_metadata = {
        'plaid': {
            'from_cache': plaid_result.data.from_cache,
            'cache_age_hours': plaid_result.data.cache_age_hours,
        },
        'snaptrade': {
            'from_cache': snaptrade_result.data.from_cache,
            'cache_age_hours': snaptrade_result.data.cache_age_hours,
        },
    }

    result = PositionResult(
        data=PositionsData(
            positions=combined_positions,
            user_email=self.config.user_email,
            sources=['plaid', 'snaptrade'],
            from_cache=all_from_cache,  # True only if ALL providers were cached
            cache_age_hours=oldest_cache_hours,
        ),
    )

    # Store per-provider cache detail for to_api_response() metadata
    # (PositionResult doesn't have a cache_metadata field - we pass it to serialization)
    result._cache_metadata = cache_metadata  # Private attr for to_api_response()
    return result
```

**Where cache_metadata lives:**
- `PositionsData.from_cache` / `cache_age_hours` - existing fields, summary values
- `result._cache_metadata` - private attr passed to `to_api_response()` metadata section
- NOT a dataclass field (avoids changing PositionResult signature)

**Required change to `core/result_objects.py` (PositionResult.to_api_response):**

The current `to_api_response()` already includes `from_cache` and `cache_age_hours`
in metadata (lines 424-425). The only addition needed is `cache_by_provider` for
multi-provider results:

```python
# In PositionResult.to_api_response() - ADD after the metadata dict is built:

# Add per-provider cache detail if set by get_all_positions()
if hasattr(self, '_cache_metadata'):
    payload["metadata"]["cache_by_provider"] = self._cache_metadata

return make_json_safe(payload)
```

**File:** `core/result_objects.py` line ~441 (before `return make_json_safe(payload)`)

**Semantics:**
- `from_cache=True` means ALL providers returned cached data
- `from_cache=False` means at least one provider fetched fresh
- `cache_by_provider` in API response provides per-provider detail for consumers that need it
- `cache_age_hours` is the oldest age (worst case freshness)

### 6. PositionResult Location (Resolved)

**Resolved:** `PositionResult` is implemented in `core/result_objects.py` only.
The interface definition in this plan is for documentation purposes.
See `POSITION_RESULT_IMPLEMENTATION_PLAN.md` (completed) for implementation details.

---

## Files Changed

| File | Change Type | Description |
|------|-------------|-------------|
| `services/position_service.py` | Major update | Add cache logic, DB ops, `use_cache` parameter |
| `core/result_objects.py` | Minor update | Add `cache_by_provider` to `to_api_response()` metadata |
| `routes/plaid.py` | Simplify | Remove cache logic, call service |
| `routes/snaptrade.py` | Simplify | Remove cache logic, call service |

---

## Success Criteria

1. PositionService returns cached data when cache is fresh (< 24h)
2. PositionService calls API when cache expired or force_refresh=True
3. Routes return identical response format (backward compatible)
4. Single source of truth - no duplicated cache logic
5. New consumers (position tracker) can use PositionService directly

---

## Remaining Items (Optional / Deferred)

> **Note:** Code comments have been left in the relevant files to indicate these optional improvements.

**Phase 1.5 Optional Cleanup**
- [ ] Extract shared `positions_df_to_portfolio_data(...)` helper
- [ ] (Optional) Update routes to use `result.to_api_response()` if we want a unified envelope

**Phase 3 Optional Cleanup**
- [ ] Remove any now-dead code from routes after refactor
- [ ] Move Plaid YAML fallback file generation into PositionService
- [ ] Consider adding `POST /holdings/refresh` endpoints (`force_refresh=True`)

---

## Phase 4: Database Schema Enhancement

**Status:** ✅ COMPLETED

**Problem:** The `positions` table doesn't store `name` (security name) or `brokerage_name`
(institution name). When loading from cache, these fields default to `ticker` and `None`.

**Current schema:**
```sql
CREATE TABLE positions (
    id SERIAL PRIMARY KEY,
    portfolio_id INTEGER REFERENCES portfolios(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    ticker VARCHAR(100) NOT NULL,
    quantity DECIMAL(20,8) NOT NULL,
    currency VARCHAR(10) NOT NULL,
    type VARCHAR(20),
    cost_basis DECIMAL(20,8),
    purchase_date DATE,
    account_id VARCHAR(100),
    position_source VARCHAR(50),
    position_status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    -- Missing: name, brokerage_name
);
```

**Impact:**
- Fresh fetch from Plaid/SnapTrade has full data (name, brokerage)
- Cache load loses name (defaults to ticker) and brokerage (defaults to None)
- This affects display quality in CLI/MCP/UI

### 4.1 Schema Migration

Add two columns to the `positions` table:

```sql
-- Migration: Add name and brokerage_name to positions table
ALTER TABLE positions ADD COLUMN name VARCHAR(255);
ALTER TABLE positions ADD COLUMN brokerage_name VARCHAR(100);

-- Optional: Add account_name for SnapTrade (Plaid doesn't have this)
ALTER TABLE positions ADD COLUMN account_name VARCHAR(255);

-- Add index for brokerage filtering if needed
CREATE INDEX idx_positions_brokerage_name ON positions(brokerage_name);
```

**Migration location:**
- Update `database/schema.sql` (authoritative schema snapshot)
- Add a simple migration file (if you maintain migrations) that runs the three `ALTER TABLE` statements above

### 4.2 Update DatabaseClient

Update `get_portfolio_positions()` to return the new columns:

```python
# In inputs/database_client.py
query = """
    SELECT p.ticker, p.quantity, p.currency, p.type,
           p.account_id, p.cost_basis, p.position_source,
           p.name, p.brokerage_name, p.account_name  -- NEW
    FROM positions p
    JOIN portfolios port ON p.portfolio_id = port.id
    WHERE port.user_id = %s AND port.name = %s
    ORDER BY p.created_at
"""
```

Update `save_portfolio()` to store the new columns:

```python
# In inputs/database_client.py (save_portfolio method)
cursor.execute("""
    INSERT INTO positions
    (portfolio_id, user_id, ticker, quantity, currency, type,
     account_id, cost_basis, position_source, name, brokerage_name, account_name)  -- NEW
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
""", ...)
```

**Important:** These fields must be present in the `portfolio_input` dict entries or they will be stored as NULL.
Make sure the conversion layer explicitly sets `name`, `brokerage_name`, and `account_name` (and preserves
`cost_basis` where available).

### 4.3 Update Loaders

**plaid_loader.py:** `convert_plaid_holdings_to_portfolio_data()` needs to pass `name`,
`brokerage_name` (from `institution` column after normalization), and `account_name`
(if available) to the portfolio_input dict.

**snaptrade_loader.py:** `convert_snaptrade_holdings_to_portfolio_data()` needs to pass
`name`, `brokerage_name`, and `account_name` to the holdings_dict.

**Note:** `cost_basis` and `account_id` are already passed through for both loaders (fixed earlier).
The PositionService normalizes Plaid's `institution` column to `brokerage_name` before the
converter runs, so both loaders can use `brokerage_name` consistently.

### 4.4 Update PositionService

Update `_ensure_cached_columns()` to expect name/brokerage from DB instead of defaulting:

```python
def _ensure_cached_columns(self, df: pd.DataFrame, provider: str) -> pd.DataFrame:
    # name should now come from DB, only default if truly missing
    if "name" not in df.columns:
        df["name"] = df["ticker"]
    # brokerage_name should now come from DB
    if "brokerage_name" not in df.columns:
        df["brokerage_name"] = None
    # ... rest unchanged
```

### 4.5 Files Changed

| File | Change |
|------|--------|
| `database/schema.sql` | Add `name`, `brokerage_name`, `account_name` columns |
| `database/migrations/*` | Add simple `ALTER TABLE` migration (if migrations are tracked) |
| `inputs/database_client.py` | Update SELECT and INSERT queries |
| `plaid_loader.py` | Pass name/brokerage/account in conversion |
| `snaptrade_loader.py` | Pass name/brokerage/account and preserve `cost_basis` in conversion |
| `services/position_service.py` | Update `_ensure_cached_columns()` |

### 4.6 Migration Strategy

1. **Add columns as nullable** - existing data won't break
2. **Deploy code changes** - new saves will populate the columns
3. **Backfill existing data** - optional, cache will naturally refresh within 24h
4. **No immediate backfill needed** - next API call will populate on fresh fetch

### 4.7 Tests (Suggested)

- Add a simple DB round-trip test: fresh fetch → save → load from cache
  should preserve `name`, `brokerage_name`, `account_name` (and `cost_basis` where present).

### Related Fix (Completed)

**SnapTrade consolidation fix:** Updated `consolidate_snaptrade_holdings()` to preserve
all metadata fields (name, brokerage_name, account_name, cost_basis, price) using the
same sum + first-row join pattern as Plaid. This ensures fresh fetches have all data;
the DB schema enhancement will ensure cached data also has these fields.

---

*Completed: 2025-01-30*
*Status: ✅ COMPLETE (Phases 1, 2, 4) — optional cleanup items deferred with code comments*

# Phase A: MCP Works With Zero Infrastructure
**Status:** DONE

**Date**: 2026-03-08 | **Updated**: 2026-03-09
**Goal**: A new user can `pip install`, set two env vars (`FMP_API_KEY` + `RISK_MODULE_USER_EMAIL`), and start using portfolio analysis tools immediately.
**Parent**: `ONBOARDING_FRICTION_AUDIT.md`

## Status

| Step | Description | Status | Commit |
|------|-------------|--------|--------|
| 1 | No-DB Mode | **DONE** | `ecc66f7d` |
| 2 | CSV Position Import | **DONE** | `982022d6` |
| 3 | Startup Validation | **DONE** | `8f480e99` |

**Related bug**: PostgreSQL connection pool exhaustion (see `BACKLOG.md`) — discovered during Step 1 live testing. `is_db_available()` caches True at startup but pool can exhaust later, causing cascading failures in the MCP server process.

## Target Experience

```bash
git clone <repo>
pip install -r requirements.txt
cat > .env << 'EOF'
FMP_API_KEY=your_key
RISK_MODULE_USER_EMAIL=you@example.com
EOF
claude mcp add portfolio-mcp -e RISK_MODULE_USER_EMAIL=you@example.com -- python mcp_server.py

# Then in Claude:
> "import my portfolio from this CSV" (attach IBKR Activity Statement)
> "what's my risk analysis?"
> "run an optimization"
```

No Postgres. No Google OAuth. No Plaid. No broker API credentials. Just an FMP key, an email for user scoping, and a CSV.

---

## Step 1: No-DB Mode — DONE (commit `ecc66f7d`)

### Problem

When `DATABASE_URL` is not set, calling any DB-dependent tool raises:
```
ValueError: DATABASE_URL is not set
```
or
```
psycopg2.OperationalError: could not connect to server
```

The MCP server **starts fine** (all imports are static, DB connections are lazy), but the first tool call that touches the database fails. The `@handle_mcp_errors` decorator catches this and returns `{status: "error"}`, but the error message is cryptic.

### Current Architecture

```
mcp_server.py
  ├── imports all mcp_tools/*.py (lines 44-101) — ALL SUCCEED without DB
  ├── @mcp.tool() decorators — registration only, no DB calls
  └── Tool invocation → runtime DB access → FAILS

database/pool.py
  └── os.environ.setdefault("DATABASE_URL", "postgresql://...") — MASKS the problem
      └── app_platform/db/pool.py → PoolManager.get_pool() → ValueError if empty

get_db_session() call chain:
  SessionManager → PoolManager.get_pool() → SimpleConnectionPool(DATABASE_URL)
```

**Key insight**: `database/pool.py` sets a fallback `DATABASE_URL` pointing to localhost Postgres. This means the error isn't "DATABASE_URL not set" — it's a connection refused error from psycopg2 trying to connect to a nonexistent Postgres. The fallback masks the real problem.

### DB Dependency Audit (Complete)

#### Hard DB call sites in the MCP tool layer

These are all the runtime call sites that hit the database. Every one needs a guard.

| Call site | What it does | Guard strategy |
|-----------|-------------|----------------|
| `utils/user_resolution.py:10` — `resolve_user_id()` | `SELECT id FROM users WHERE email` | Return sentinel `user_id=0` in no-DB mode |
| `services/position_service.py:~684` — `_check_cache_freshness()` | Cache TTL check via DB query | Skip cache, always fetch fresh |
| `services/position_service.py:~1019` — `_save_positions_to_db()` | Persist positions to DB | No-op in no-DB mode |
| `services/position_service.py:~730` — `_load_cached_positions()` | Read cached positions from DB | Raise `ValueError` (caller catches, falls to fresh fetch) |
| `services/position_service.py:~1035` — `refresh_provider_positions()` | Delete + re-save cache | Guard with `is_db_available()` |
| `services/position_service.py:~1064` — `delete_provider_positions()` | Delete cached positions | Guard with `is_db_available()` |
| `services/factor_proxy_service.py:100` — `ensure_factor_proxies()` | Load/build factor proxies via DB | Use `build_proxy_for_ticker()` directly (non-DB path exists) |
| `mcp_tools/risk.py:406` — `_load_portfolio_for_analysis()` → `_resolve_user_id()` | User ID lookup | Return sentinel `0` |
| `mcp_tools/risk.py:434` — `ensure_factor_proxies()` | Factor proxy load | Non-DB fallback (see 1f) |
| `mcp_tools/risk.py:448-455` — `repo.get_target_allocations()` | Target allocation load | Already has try/except → `{}` |
| `mcp_tools/risk.py:525` — `RiskLimitsManager(use_database=True)` | Risk limits load (get_risk_score path) | `use_database=is_db_available()` |
| `mcp_tools/risk.py:657` — `RiskLimitsManager(use_database=True)` | Risk limits load (get_risk_analysis path) | `use_database=is_db_available()` |
| `mcp_tools/risk.py:732` — `RiskLimitsManager(use_database=True)` | Risk limits load (get_leverage_capacity path) | `use_database=is_db_available()` |
| `mcp_tools/risk.py:856` — `RiskLimitsManager(use_database=True)` | Risk limits load+save (set_risk_profile path) | `use_database=is_db_available()` |
| `mcp_tools/risk.py:944` — `RiskLimitsManager(use_database=True)` | Risk limits load (get_risk_profile path) | `use_database=is_db_available()` |
| `mcp_tools/optimization.py:114` — `get_db_session()` for expected returns | `max_return` mode loads expected returns | Guard: return error if no DB and `optimization_type == "max_return"` |
| `mcp_tools/compare.py:149-155` — `_load_expected_returns()` | Expected returns for comparison | Guard: return `{}` if no DB |
| `mcp_tools/compare.py:262` — expected returns in optimization mode | Same | Same guard |
| `mcp_tools/positions.py:647` — `_resolve_user_id()` | User ID in `get_positions()` | Return sentinel `0` |
| `mcp_tools/performance.py:59` — `_resolve_user_id()` | User ID for perf | Return sentinel `0` |
| `core/realized_performance/aggregation.py:84` — `load_from_store()` | Realized perf mode uses transaction store | Guard: `mode=realized` returns clear error when `not is_db_available()` |
| `mcp_tools/allocation.py:84,116` — `_resolve_user_id()` | User ID for allocations | Return sentinel `0` |
| `mcp_tools/trading_analysis.py:108-126` — `TRANSACTION_STORE_READ` path | `ensure_store_fresh()` + `load_from_store()` hit DB via transaction_store | Guard: skip store path when `not is_db_available()`, fall through to direct API fetch |
| `mcp_tools/trading_analysis.py:112` — `resolve_user_id()` | User ID for trading analysis | Return sentinel `0` (only reached if store path active) |
| `mcp_tools/tax_harvest.py:124-137` — `TRANSACTION_STORE_READ` path | Same `ensure_store_fresh()` + `load_from_store()` pattern | Same guard: skip store path when `not is_db_available()` |
| `mcp_tools/tax_harvest.py:127,873` — `_resolve_user_id()` | User ID for tax harvest | Return sentinel `0` (only reached if store path active) |
| `mcp_tools/factor_intelligence.py:86` — `_resolve_user_id()` | User ID for factor analysis | Return sentinel `0` |
| `mcp_tools/baskets.py:44` — `_resolve_user_id()` | User ID for baskets | `@require_db` on all basket tools |
| `mcp_tools/audit.py:49` — `_resolve_user_id()` | User ID for audit trail | `@require_db` on all audit tools |
| `mcp_tools/transactions.py:25,98,259` — `_resolve_user_id()` | User ID for transactions | `@require_db` on all transaction tools |
| `services/trade_execution_service.py:143` — `TradeExecutionService.__init__()` | Doesn't hit DB directly | OK — adapter init is provider-gated |

#### Tools that are truly DB-free (no position loading, no user_id)

> get_quote, analyze_stock, get_mcp_context

#### Tools that need positions but NOT user_id from DB

> get_income_projection, check_exit_signals, monitor_hedge_positions,
> analyze_option_chain, analyze_option_strategy,
> get_portfolio_news, get_portfolio_events_calendar

These load positions via `PositionService` directly (no `_resolve_user_id()` call).
`get_portfolio_news` and `get_portfolio_events_calendar` auto-fill portfolio tickers
via `_load_portfolio_symbols()` (`news_events.py:32`) which calls
`PositionService.get_all_positions()`. They already handle failures gracefully
(return `None` on exception, tools work without portfolio context).
All work in no-DB mode once `PositionService` cache ops are guarded.

#### Tools that use `_load_portfolio_for_analysis()` (need user_id guard)

> get_risk_analysis, get_risk_score, set_risk_profile, run_optimization,
> run_whatif, run_backtest, compare_scenarios, get_leverage_capacity,
> preview_rebalance_trades, get_factor_analysis, get_factor_recommendations,
> get_trading_analysis, suggest_tax_loss_harvest, get_positions, get_performance,
> export_holdings

#### Tools that hard-require DB (`@require_db`)

> fetch_provider_transactions, list_transactions, list_ingestion_batches,
> inspect_transactions, list_flow_events, list_income_events,
> refresh_transactions, transaction_coverage,
> create_basket, list_baskets, get_basket, update_basket, delete_basket,
> analyze_basket, create_basket_from_etf (in `mcp_tools/baskets.py`),
> preview_basket_trade, execute_basket_trade (in `mcp_tools/basket_trading.py`),
> record_workflow_action, update_action_status, get_action_history,
> set_target_allocation, get_target_allocation

#### Tools with conditional DB path (`TRANSACTION_STORE_READ`)

> get_trading_analysis, suggest_tax_loss_harvest

These have two code paths: store-backed (DB) and direct API fetch (no DB).
`TRANSACTION_STORE_READ` defaults to `true`. Guard: skip store path when
`not is_db_available()`, fall through to direct API fetch.

> get_performance (mode=realized)

Realized performance fundamentally requires transaction store. Return clear
error when no DB. `mode=hypothetical` works without DB.

#### Trading tools (separate concern — gated by `TRADING_ENABLED` + broker adapters)

> preview_trade, execute_trade, preview_futures_roll, execute_futures_roll,
> preview_option_trade, execute_option_trade, get_orders, cancel_order

These don't call `_resolve_user_id()`. They're already gated by `TRADING_ENABLED`
and broker adapter availability. They work without DB.

### Implementation Plan

#### 1a. Add `is_db_available()` helper

**File**: `database/__init__.py`

```python
import os
import threading

_db_available: bool | None = None
_db_lock = threading.Lock()

def is_db_available() -> bool:
    """Check if a working database connection exists.

    Cached after first *successful* check. Negative results are NOT cached
    so that a DB that comes online mid-session is detected.
    """
    global _db_available
    if _db_available is True:
        return True

    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        return False

    with _db_lock:
        if _db_available is True:
            return True
        try:
            from app_platform.db.session import get_db_session
            with get_db_session() as conn:
                conn.cursor().execute("SELECT 1")
            _db_available = True
            return True
        except Exception:
            return False
```

**Key**: Negative results are not cached — if a user starts Postgres after MCP server is already running, the next tool call will detect it. Only positive results are cached (DB doesn't go away).

#### 1b. Remove `DATABASE_URL` fallback default

**File**: `database/pool.py`

Remove:
```python
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://postgres@localhost:5432/risk_module_db",
)
```

This prevents masking the "no DB" state. Without `DATABASE_URL`, `is_db_available()` returns `False` immediately (no connection attempt).

**Risk note**: Any existing user who relied on the implicit localhost default will need to add `DATABASE_URL` to their `.env`. This is the right behavior — explicit config over hidden defaults.

#### 1c. Make `resolve_user_id()` no-DB aware

**File**: `utils/user_resolution.py`

This is the **single most critical fix** — 15+ call sites across mcp_tools depend on it.

```python
def resolve_user_id(user_email: str) -> int:
    """Look up the database user ID for an email address.

    Returns 0 (sentinel) when no database is available. Callers that
    truly require a valid user_id should check is_db_available() first.
    """
    from database import is_db_available
    if not is_db_available():
        return 0

    from database import get_db_session
    with get_db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE email = %s", (user_email,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"User not found: {user_email}")
        return row["id"]
```

All existing callers already store the result in `user_id` and pass it to downstream functions. The sentinel `0` flows through without issue because:
- `RiskLimitsManager(user_id=0, use_database=False)` → uses YAML/defaults
- `ensure_factor_proxies(user_id=0, ...)` → skipped in no-DB mode (see 1f)
- `portfolio_data.user_id = 0` → only used for temp file isolation, `0` is safe
- Basket/audit/transaction tools are behind `@require_db` so `user_id=0` never reaches DB queries

#### 1d. Make `PositionService` DB-agnostic for cache operations

**File**: `services/position_service.py`

Guard all cache-related DB operations:

```python
def _check_cache_freshness(self, provider: str):
    from database import is_db_available
    if not is_db_available():
        return False, None  # No cache → always fetch fresh from providers
    # ... existing DB-based cache check (unchanged)

def _save_positions_to_db(self, df, provider, ...):
    from database import is_db_available
    if not is_db_available():
        return  # No-op: can't persist without DB
    # ... existing save logic at line ~1019 (unchanged)

def _load_cached_positions(self, provider):
    from database import is_db_available
    if not is_db_available():
        raise ValueError(f"No cached positions for {provider} (no database)")
    # ... existing load logic (unchanged)
```

Also guard `refresh_provider_positions()` and `delete_provider_positions()`:
```python
def refresh_provider_positions(self, provider, ...):
    from database import is_db_available
    if not is_db_available():
        # Still allow fresh fetch, just skip the delete+save cache cycle
        return self._fetch_fresh_positions(provider, ...)
    # ... existing delete + re-save logic
```

**Empty DataFrame handling**: `PositionsData.from_dataframe()` raises `ValueError("df is empty")`
when all providers return empty DataFrames (`data_objects.py:419-420`). This propagates
up through `PositionResult.from_dataframe()` and crashes `get_all_positions()`.

Guard needed in `get_all_positions()` (at `position_service.py:~358`):

```python
if combined.empty:
    # Return a minimal PositionResult with no positions instead of crashing
    return PositionResult(
        data=PositionsData(positions=[], user_email=self.config.user_email),
        ...
    )
```

Or construct `PositionsData` directly (bypassing `from_dataframe`) when the combined
DataFrame is empty. The downstream guard in `_load_portfolio_for_analysis()` at
`risk.py:417` (`if not position_result.data.positions`) then triggers the
"No brokerage positions found" error cleanly.

This is the expected path in no-DB mode before CSV import — the user gets a clear
"no positions" error rather than a cryptic `ValueError("df is empty")` crash.

#### 1e. Make `RiskLimitsManager` callers DB-aware

**Files**: `mcp_tools/risk.py`, `mcp_tools/compare.py`, `mcp_tools/optimization.py`, `mcp_tools/whatif.py`

All four files have the same pattern:
```python
risk_limits_data = RiskLimitsManager(
    use_database=True, user_id=user_id
).load_risk_limits(portfolio_name)
```

Change to:
```python
from database import is_db_available

risk_limits_data = RiskLimitsManager(
    use_database=is_db_available() and bool(user_id),
    user_id=user_id,
).load_risk_limits(portfolio_name)
```

`RiskLimitsManager` already has fallback chain: database → `risk_limits.yaml` file → defaults. When `use_database=False`, it reads the YAML or returns defaults. No behavior change for DB users.

#### 1f. Guard `ensure_factor_proxies()` — use non-DB path

**File**: `mcp_tools/risk.py:434` (in `_load_portfolio_for_analysis`)

`ensure_factor_proxies()` in `services/factor_proxy_service.py` does two DB operations:
1. Line 100: `db.get_factor_proxies()` — load existing cache
2. Line 155+: `db.save_factor_proxies()` / `db.save_subindustry_peers()` — persist new proxies

The underlying `build_proxy_for_ticker()` function is **DB-free** — it uses FMP profile + YAML mappings.

```python
from database import is_db_available

if is_db_available():
    portfolio_data.stock_factor_proxies = ensure_factor_proxies(
        user_id, portfolio_name, tickers, allow_gpt=True,
        **({"instrument_types": ...} if ... else {}),
    )
else:
    # Build factor proxies without DB (no caching, no peer storage).
    # load_exchange_proxy_map() and load_industry_etf_map() in proxy_builder.py
    # try DB first (proxy_builder.py:394, :437) but already have YAML fallbacks
    # that trigger on any DB exception. In no-DB mode they'll log a warning
    # and load from exchange_etf_proxies.yaml / industry_to_etf.yaml respectively.
    # This is the existing behavior — no code changes needed in proxy_builder.py.
    from proxy_builder import (
        build_proxy_for_ticker, load_exchange_proxy_map, load_industry_etf_map,
        build_futures_skip_proxy, should_skip_fmp_profile_lookup,
    )
    exch_map = load_exchange_proxy_map()   # Falls back to YAML on DB error
    ind_map = load_industry_etf_map()       # Falls back to YAML on DB error
    proxies = {}
    for tkr in tickers:
        if should_skip_fmp_profile_lookup(tkr, instrument_types=getattr(portfolio_data, 'instrument_types', None)):
            proxies[tkr] = build_futures_skip_proxy()
            continue
        proxy = build_proxy_for_ticker(tkr, exch_map, ind_map) or {}
        proxy["subindustry"] = []  # No peer data without DB
        proxies[tkr] = proxy
    portfolio_data.stock_factor_proxies = proxies
```

**Why not `{}`**: Returning empty proxies would silently degrade factor analysis — `build_portfolio_view()` uses proxies for excess return computation at `portfolio_risk.py:1228`. Building them without DB preserves factor analysis quality; only sub-industry peer data (GPT-generated, cached in DB) is missing.

**DB probe in `load_exchange_proxy_map()` / `load_industry_etf_map()`**: Both functions at `proxy_builder.py:394` and `:437` try the DB first, then fall back to YAML files on any exception. In no-DB mode, the DB attempt will fail immediately (no `DATABASE_URL` → pool error), the warning is logged, and the YAML fallback loads. This is existing behavior — the try/except is already there. The only cost is a warning log line per call, which is acceptable for startup.

#### 1g. Guard `TRANSACTION_STORE_READ` paths

**Files**: `mcp_tools/trading_analysis.py:108`, `mcp_tools/tax_harvest.py:124`, `core/realized_performance/aggregation.py:84`

`TRANSACTION_STORE_READ` defaults to `true` (`settings.py:139`). When active, `get_trading_analysis()`, `suggest_tax_loss_harvest()`, and `get_performance(mode="realized")` call `ensure_store_fresh()` → `load_from_store()` which hit the transaction store DB tables.

These tools have **two code paths**: store-backed (DB) and direct API fetch (no DB). In no-DB mode, force the direct API path:

```python
# In mcp_tools/trading_analysis.py:108
from database import is_db_available

if TRANSACTION_STORE_READ and is_db_available():
    # ... existing store path
else:
    # ... existing direct API fetch path (already implemented)
```

Same pattern in `mcp_tools/tax_harvest.py:124`.

For `get_performance(mode="realized")` — realized performance fundamentally requires the transaction store. Return a clear error:

```python
if mode == "realized":
    from database import is_db_available
    if not is_db_available():
        return {
            "status": "error",
            "error": "Realized performance requires a database (transaction history). "
                     "Use mode='hypothetical' for price-based performance, or configure DATABASE_URL."
        }
```

`mode="hypothetical"` works without DB — it uses FMP price series only.

#### 1h. Guard `optimization.py` expected returns (formerly 1g)

**File**: `mcp_tools/optimization.py:112-125`

```python
if optimization_type == "max_return":
    from database import is_db_available
    if not is_db_available():
        return {
            "status": "error",
            "error": "max_return optimization requires expected returns stored in the database. "
                     "Use min_variance optimization instead, or configure DATABASE_URL."
        }
    from database import get_db_session
    from inputs.database_client import DatabaseClient
    with get_db_session() as conn:
        db_client = DatabaseClient(conn)
        expected_returns = db_client.get_expected_returns(user_id, portfolio_name)
    # ... existing logic
```

`min_variance` optimization works without expected returns — it only needs the covariance matrix (computed from price data via FMP).

#### 1i. Guard `compare.py` expected returns

**File**: `mcp_tools/compare.py:149`

```python
def _load_expected_returns(user_id: int, portfolio_name: str) -> dict:
    from database import is_db_available
    if not is_db_available():
        return {}

    from database import get_db_session
    from inputs.database_client import DatabaseClient
    with get_db_session() as conn:
        db_client = DatabaseClient(conn)
        return db_client.get_expected_returns(user_id, portfolio_name) or {}
```

Empty expected returns is safe — `compare_scenarios()` passes them to optimization which falls back gracefully.

#### 1j. `@require_db` decorator for hard-DB tools

**File**: `mcp_tools/common.py`

```python
def require_db(fn: Callable) -> Callable:
    """Decorator for MCP tools that hard-require a database connection.

    Returns a clear error message instead of letting the tool crash
    with a cryptic psycopg2 error.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs) -> dict:
        from database import is_db_available
        if not is_db_available():
            return {
                "status": "error",
                "error": (
                    "This feature requires a PostgreSQL database. "
                    "Set DATABASE_URL in your .env file to enable it."
                ),
            }
        return fn(*args, **kwargs)
    return wrapper
```

**Note**: Sync wrapper (not async) — matches existing `@handle_mcp_errors` pattern. Applied inside `@handle_mcp_errors`:

```python
@handle_mcp_errors
@require_db
def fetch_provider_transactions(...):
    ...
```

**Apply to these tools**:
- `mcp_tools/transactions.py`: all 8 tools (ingest, list, inspect, batches, flows, income, refresh, coverage)
- `mcp_tools/baskets.py`: basket CRUD tools (create, list, get, update, delete, analyze, create_from_etf)
- `mcp_tools/basket_trading.py`: basket trading tools (preview_basket_trade, execute_basket_trade) — these are in a separate file from basket CRUD and open `get_db_session()` directly at line 292
- `mcp_tools/audit.py`: record, update_status, get_history
- `mcp_tools/allocation.py`: set_target_allocation, get_target_allocation
- `mcp_tools/instrument_config.py`: manage_instrument_config

### Verification

```bash
# 1. Remove DATABASE_URL from .env
unset DATABASE_URL

# 2. Start MCP server — should succeed
python mcp_server.py

# 3. Pure FMP tools — should work immediately
# get_quote("AAPL") → price data
# analyze_stock("AAPL") → stock analysis

# 4. Position-dependent tools — returns "no positions" (until CSV import)
# get_risk_analysis() → "No brokerage positions found"

# 5. DB-required tools — clear error message
# fetch_provider_transactions() → "This feature requires a PostgreSQL database"

# 6. Verify existing DB users are unaffected
export DATABASE_URL=postgresql://postgres@localhost:5432/risk_module_db
# All tools work exactly as before
```

### Files to Modify

| File | Change | Risk |
|------|--------|------|
| `database/__init__.py` | Add `is_db_available()` | Low — pure addition |
| `database/pool.py` | Remove `setdefault` for `DATABASE_URL` | Low — stops masking missing DB. Existing users must have explicit `DATABASE_URL`. |
| `utils/user_resolution.py` | Return sentinel `0` when no DB | Medium — sentinel flows through 15+ call sites. All validated above. |
| `services/position_service.py` | Guard cache ops (`_check_cache_freshness`, `_save_positions_to_db`, `_load_cached_positions`, `refresh_provider_positions`, `delete_provider_positions`). Handle empty combined DataFrame in `get_all_positions()`. | Medium — must preserve fresh-fetch path. No behavior change for DB users. |
| `services/position_service.py:302` | Skip routing filter for `csv` provider in `get_all_positions()` | Low — CSV bypasses standard routing (no credentials/enablement needed) |
| `mcp_tools/risk.py:434` | Guard `ensure_factor_proxies` — non-DB build via `build_proxy_for_ticker()` | Medium — factor proxy non-DB path needs testing |
| `mcp_tools/risk.py:525,657,732,856,944` | `RiskLimitsManager(use_database=is_db_available())` — five call sites (risk_score, risk_analysis, leverage_capacity, set_risk_profile, get_risk_profile) | Low — has YAML fallback |
| `mcp_tools/compare.py` | Guard `_load_expected_returns()` + `RiskLimitsManager` | Low |
| `mcp_tools/optimization.py` | Guard expected returns (`max_return` mode), `RiskLimitsManager` | Low — `min_variance` still works |
| `mcp_tools/whatif.py` | `RiskLimitsManager` guard | Low |
| `mcp_tools/common.py` | Add `require_db` decorator (sync, not async) | Low — pure addition |
| `mcp_tools/transactions.py` | Apply `@require_db` to all 8 tools | Low |
| `mcp_tools/baskets.py` | Apply `@require_db` to basket CRUD tools | Low |
| `mcp_tools/basket_trading.py` | Apply `@require_db` to `preview_basket_trade`, `execute_basket_trade` | Low |
| `mcp_tools/audit.py` | Apply `@require_db` to all 3 tools | Low |
| `mcp_tools/trading_analysis.py` | Guard `TRANSACTION_STORE_READ` with `is_db_available()` | Low — falls through to direct API path |
| `mcp_tools/tax_harvest.py` | Guard `TRANSACTION_STORE_READ` with `is_db_available()` | Low — falls through to direct API path |
| `mcp_tools/performance.py` | Guard `mode=realized` with `is_db_available()` | Low — `mode=hypothetical` still works |
| `mcp_tools/allocation.py` | Apply `@require_db` to both tools | Low |

### Rollback

Feature-flagged via `is_db_available()`. If `DATABASE_URL` is set, every code path takes the existing branch. The only breaking change is removing the implicit localhost default in `database/pool.py` — users who relied on it must add `DATABASE_URL` to `.env`.

### Implementation Summary

17 files changed. Key changes:
- `database/__init__.py`: `is_db_available()` with positive-only caching, thread-safe
- `database/pool.py`: Removed hidden localhost DATABASE_URL default
- `utils/user_resolution.py`: Returns sentinel `user_id=0` when no DB
- `mcp_tools/common.py`: `@require_db` decorator for DB-only tools
- `services/position_service.py`: 5 cache methods guarded with `is_db_available()`
- `mcp_tools/risk.py`: RiskLimitsManager `use_database=is_db_available()`, factor proxy YAML fallback
- `mcp_tools/optimization.py`, `compare.py`, `whatif.py`: Expected returns + RiskLimitsManager guards
- `mcp_tools/performance.py`: `mode=realized` returns clear error when no DB
- `mcp_tools/trading_analysis.py`, `tax_harvest.py`: `TRANSACTION_STORE_READ and is_db_available()` guard
- `mcp_tools/transactions.py` (8), `baskets.py` (7), `basket_trading.py` (2), `audit.py` (3), `allocation.py` (2), `instrument_config.py` (1): `@require_db` on 23 DB-only tools

Live tested: 2974 tests passed. CLI analysis succeeds with DB down (YAML fallback).

---

## Step 2: CSV Position Import (solves the data wall)

### Problem

After Step 1, the MCP server starts and tools are available — but every portfolio analysis tool returns "No brokerage positions found." The user has no data. All current position sources require API credentials (Plaid, SnapTrade, Schwab, IBKR).

Every brokerage lets users download CSV exports of positions. This is the zero-friction path.

### Design

#### Architecture: CSV as a PositionProvider

CSV import is implemented as a **file-backed `PositionProvider`** registered in `PositionService`, NOT as a special case in `_load_portfolio_for_analysis()`. This ensures all tools that read positions via `PositionService` automatically see CSV-imported data:

- `_load_portfolio_for_analysis()` (risk, optimization, what-if, etc.)
- `get_positions()` (MCP positions tool)
- `get_income_projection()` (income tool)
- `check_exit_signals()` (signals tool)
- `monitor_hedge_positions()` (hedge monitor tool)
- `get_portfolio_news()` / `get_portfolio_events_calendar()` (news/events)

#### Data Flow

```
User CSV (any brokerage export)
    ↓
import_portfolio MCP tool
    ↓
Normalizer (detect() + normalize()) — built-in IBKR or agent-created
    ↓
list[PositionRecord] via try_build_position() — validated at construction
    ↓
NormalizeResult (validated records + warnings + brokerage_name)
    ↓
dry_run=True: preview  |  dry_run=False: [rec.to_dict() for rec in positions]
    ↓
save to positions.json (keyed by source_key in "sources" dict)
    ↓
CSVPositionProvider.fetch_positions()
  read positions.json → DataFrame
    ↓
_get_positions_df("csv") — bypasses cache/TTL pipeline (import-only provider)
    ↓
PositionsData (second validation as safety net) → full analysis pipeline
```

#### Two Normalizer Systems — Position vs Transaction

This codebase has two separate normalizer systems for different purposes. They share
the word "normalizer" but have completely different interfaces, locations, and outputs:

| | Position Normalizers (this plan) | Transaction Normalizers (existing) |
|---|---|---|
| **Location** | `inputs/normalizers/*.py` | `providers/normalizers/*.py` |
| **Interface** | Module-level `detect(lines)` + `normalize(lines, filename)` | Class-based `TransactionNormalizer` Protocol |
| **Input** | Raw CSV text lines (`list[str]`) | Pre-parsed dicts from API or Flex XML |
| **Output** | `NormalizeResult` with `list[PositionRecord]` | `tuple[list[NormalizedTrade], list[NormalizedIncome], list[dict]]` |
| **Purpose** | CSV → current holdings snapshot | API/Flex → trade + income history |
| **Extension** | Agent drops `.py` files in `~/.risk_module/normalizers/` | Edit `providers/normalizers/` source code |
| **Used by** | `import_portfolio` MCP tool | `fetch_provider_transactions` MCP tool |

Both may parse the same physical file (e.g., IBKR Activity Statement) but extract
different sections. The IBKR position normalizer extracts "Open Positions"; the
existing IBKR Flex transaction normalizer extracts trades, dividends, interest, fees.

The Statement Import Plan (`BROKERAGE_STATEMENT_IMPORT_PLAN.md`) adds a third layer
of transaction normalizers in `providers/normalizers/` for CSV-sourced transactions
(vs the existing API/Flex-sourced ones). That plan is independent of this one — both
can proceed without coordination.

#### Normalizer Architecture (from finance-cli)

**Why not JSON mappings**: Real brokerage CSVs are not simple header+rows files.
IBKR Activity Statements are multi-section files where column 0 is a section name
(`Statement`, `Net Asset Value`, `Open Positions`, etc.), column 1 is row kind
(`Header`, `Data`, `Total`), and each section has different column schemas. Other
brokerages have preamble rows, multi-account layouts, or non-standard delimiters.
These require actual parsing logic — conditional row filtering, section selection,
preamble detection — that a flat JSON column mapping cannot express.

**Model**: Each brokerage gets a Python normalizer module with two functions:

```python
# inputs/normalizers/ibkr.py

def detect(lines: list[str]) -> bool:
    """Return True if this CSV is from this brokerage.

    Called with the first ~20 lines of the file. Uses heuristic
    matching on structure/headers to identify the format.
    """
    # IBKR Activity Statements start with "Statement,Header,Field Name,Field Value"
    if not lines:
        return False
    return lines[0].startswith("Statement,Header,")


def normalize(lines: list[str], filename: str) -> NormalizeResult:
    """Parse the CSV and return standardized positions as PositionRecord instances.

    Returns NormalizeResult (from inputs/position_schema.py).
    """
    # 1. Use materialize_tables() to split into per-section TableSpec objects
    # 2. Find all "Open Positions" tables — yearly files have separate sections
    #    per asset category (Stocks, Options); merge Data rows from all
    # 3. Map "Asset Category" → PositionType:
    #    "Stocks"→equity, "Equity and Index Options"→option, "Futures"→derivative
    # 4. Map columns to PositionRecord fields via try_build_position()
    # 5. Handle multi-currency (Currency column per position row)
    # 6. Extract cash from "Forex Balances" section — Description column has
    #    currency code (GBP, HKD, USD), NOT "Net Asset Value" Cash row
    ...
```

**Ingestion contract**: `PositionRecord`, `NormalizeResult`, and batch helpers are
defined in `inputs/position_schema.py` (see `POSITION_INGESTION_CONTRACT.md`).
Normalizers produce `NormalizeResult` containing validated `PositionRecord` instances.

**Normalizer registry** (`inputs/normalizers/__init__.py`):

```python
from . import ibkr  # Built-in reference normalizer

BUILT_IN = [ibkr]

def detect_and_normalize(lines: list[str], filename: str) -> NormalizeResult | None:
    """Try each normalizer's detect(), run the first match's normalize()."""
    for normalizer in _all_normalizers():
        if normalizer.detect(lines):
            return normalizer.normalize(lines, filename)
    return None

def _all_normalizers():
    """Built-in normalizers + agent/user normalizers (Tier 1 local MCP only).

    User normalizer directory (~/.risk_module/normalizers/) is only scanned
    when is_db_available() is False (Tier 1-2 local MCP). Hosted tiers (3-5)
    use built-in normalizers only — no arbitrary code execution on shared servers.
    """
    from database import is_db_available
    if is_db_available():
        return list(BUILT_IN)  # Hosted tier: built-ins only
    user_dir = Path.home() / ".risk_module" / "normalizers"
    # Load user .py files (same detect/normalize interface)
    ...
    return BUILT_IN + user_normalizers
```

**Design philosophy — agent-created normalizers, not pre-built per-brokerage**:
The goal is infrastructure that lets an agent write normalizers at runtime, not a
library of hand-built parsers for every brokerage. When a user provides a CSV from
any brokerage:
1. `import_portfolio()` returns `status: "needs_normalizer"` with first 20 lines
2. Agent reads the file structure and the IBKR reference normalizer for pattern guidance
3. Agent writes a Python normalizer with `detect()` + `normalize()` using `PositionRecord`
4. Agent saves it to `~/.risk_module/normalizers/{brokerage}.py`
5. Agent re-runs `import_portfolio()` — the new normalizer is discovered and used

This is real Python code — not a limited JSON config. The agent can handle any CSV
format: multi-section files, preamble rows, conditional logic, whatever the format
requires. The normalizer interface (`detect` + `normalize` returning `NormalizeResult`
with `PositionRecord` instances) is the only contract.

**IBKR reference normalizer** (`inputs/normalizers/ibkr.py`):
Ships as a built-in reference example. Serves two purposes:
1. Works out of the box for IBKR Activity Statement CSVs (we have real test data)
2. Demonstrates the normalizer pattern for the agent to follow when writing new ones

The IBKR normalizer extracts positions from IBKR Activity Statements — multi-section
CSV files where column 0 is a section name, column 1 is row kind (`Header`/`Data`/
`Total`), and each section has different column schemas.

**Section extraction**:
- Uses `materialize_tables()` from `scripts/materialize_ibkr_statement.py` (general-
  purpose section splitter) to get per-section `TableSpec` objects
- Extracts positions from "Open Positions" section(s). Yearly files have multiple
  "Open Positions" header rows — one per asset category (e.g. Stocks section, then
  Equity and Index Options section). The normalizer merges Data rows from all
  matching `Open Positions` tables. Column structure is the same across sections:
  `DataDiscriminator, Asset Category, Currency, Symbol, Quantity, Mult, Cost Price,
  Cost Basis, Close Price, Value, Unrealized P/L, Code`
- Maps `Asset Category` column (human-readable strings) to `PositionType`:
  `"Stocks"` → equity, `"Equity and Index Options"` → option, `"Futures"` → derivative,
  `"Bonds"` → bond. Unknown categories → other (with warning).

**Cash handling**:
- Cash comes from the "Forex Balances" section. Columns:
  `Asset Category, Currency, Description, Quantity, Cost Price, Cost Basis in USD,
  Close Price, Value in USD, Unrealized P/L in USD, Code`
- `Asset Category` is always `"Forex"`. `Description` column holds the currency
  code (e.g. `"GBP"`, `"HKD"`, `"USD"`). `Currency` column is the base currency.
- Each row becomes a `PositionType.CASH` record with `ticker: "CUR:{Description}"`,
  `quantity` from the Quantity column, `value` from `Value in USD`.
- The "Net Asset Value" section's Cash row is a base-currency aggregate — it MUST
  NOT be imported as a position because it double-counts with Forex Balances.

**Tested against real data**: Built against actual Activity Statement CSVs in `docs/`
(`U2471778_20260309.csv` one-day, `U2471778_20260101_20260309.csv` YTD,
`U2471778_2025_2025.csv` full year).

#### Filesystem Storage (DB Path Deferred)

Step 2 is **filesystem-only**. The DB write/read path for CSV positions is deferred
until the web upload endpoint exists (Tier 3+). This keeps Step 2 focused on the
core value: MCP user imports CSV, gets analysis.

Positions are saved to `~/.risk_module/portfolios/{user_hash}/positions.json` keyed
by `source_key`. `CSVPositionProvider.fetch_positions()` reads this file and returns
a DataFrame.

**Deferred (Tier 3+ / web upload)**:
- DB write via `_save_positions_to_db(df, "csv_{source_key}")`
- `CSVPositionProvider._fetch_from_db()` with server-side `position_source` filter
- REST endpoints wrapping the import backend

```python
# In mcp_tools/import_portfolio.py — after normalizer produces NormalizeResult:
position_dicts = [rec.to_dict() for rec in result.positions]
source_key = _compute_source_key(result.brokerage_name, label)

# Save to filesystem JSON keyed by source_key
# DB write path deferred to Tier 3+ (web upload)
_save_to_filesystem(user_email, source_key, position_dicts, result)
```

#### CSVPositionProvider

**File**: New `providers/csv_positions.py`

Always registered in `_position_providers` as `"csv"`. Unlike live providers
(Plaid, SnapTrade, etc.), CSV is **import-only** — `import_portfolio` is the
only writer. `fetch_positions()` always reads from storage (DB or filesystem),
never from an external API. This means the standard cache TTL pipeline doesn't
apply — CSV positions are always "fresh" because they only change on import.

```python
class CSVPositionProvider:
    """Position provider for CSV-imported portfolios.

    Import-only provider: data is written by import_portfolio, read here.
    Reads from filesystem JSON (~/.risk_module/portfolios/{user_hash}/positions.json).
    DB read path deferred to Tier 3+.

    Returns empty DataFrame when no CSV data exists (invisible to pipeline).
    """

    provider_name: str = "csv"

    def fetch_positions(self, user_email: str, **kwargs) -> pd.DataFrame:
        """Read CSV positions from filesystem JSON.

        Returns empty DataFrame when no CSV data exists — this makes the
        provider invisible in the pipeline rather than raising errors.

        DB path (reading CSV positions from Postgres) is deferred to Tier 3+.
        """
        return self._fetch_from_filesystem(user_email)

    def _fetch_from_filesystem(self, user_email: str) -> pd.DataFrame:
        """Load CSV positions from positions.json (flatten all sources)."""
        positions_file = self._resolve_path(user_email)
        if not positions_file.exists():
            return pd.DataFrame()
        with open(positions_file) as f:
            data = json.load(f)
        # Flatten all sources into one list
        all_positions = []
        for source_data in data.get("sources", {}).values():
            all_positions.extend(source_data.get("positions", []))
        if not all_positions:
            return pd.DataFrame()
        return pd.DataFrame(all_positions)

    def _resolve_path(self, user_email: str) -> Path:
        import hashlib
        user_hash = hashlib.sha256(user_email.encode()).hexdigest()[:12]
        return Path.home() / ".risk_module" / "portfolios" / user_hash / "positions.json"
```

**Key design: always fetch, never cache.** The CSV provider bypasses the standard
cache/freshness pipeline in `_get_positions_df()`. Since CSV is import-only (no
external API to call), the fetch IS the read — there's no stale/fresh distinction.

**`_get_positions_df("csv")` special-case** in `position_service.py`:

```python
def _get_positions_df(self, provider, use_cache, force_refresh, consolidate):
    provider = provider.lower().strip()
    if provider not in self._position_providers:
        raise ValueError(f"Unknown provider: {provider}")

    # CSV is import-only: always read from storage, bypass cache TTL.
    # fetch_positions() handles DB vs filesystem internally.
    # force_refresh works correctly: re-reads from storage.
    if provider == "csv":
        provider_impl = self._position_providers["csv"]
        df = provider_impl.fetch_positions(self.config.user_email)
        if df.empty:
            return df, False, None
        df = self._normalize_columns(df, source="csv")
        # NOTE: _normalize_columns overwrites position_source with the `source` param.
        # This is intentional — the per-source-key granularity ("csv_interactive_brokers")
        # lives in the storage layer only. In the pipeline, all CSV positions are "csv".
        df = partition_positions(df, "csv")
        if consolidate:
            df = self._consolidate_provider_positions(df, "csv")
        return df, False, None

    # ... existing cache/fetch pipeline for live providers
```

This means:
- `use_cache=True` → reads from storage (same as False — no TTL for CSV)
- `force_refresh=True` → reads from storage (re-reads, works correctly)
- `use_cache=False` → reads from storage (same as True — always "fresh")
- No `_save_positions_to_db()` call (import_portfolio is the only writer)
- No `_check_cache_freshness()` call (no cache to check)
- Empty DataFrame = invisible (no CSV data imported yet)

**Enrichment**: CSV positions go through the same downstream enrichment as API
positions. `PositionRecord.to_dict()` output already has all required columns, so
`_normalize_columns()` is called but does minimal work (just sets `position_source`
to `"csv"`). FMP ticker resolution and FX normalization happen downstream in
`build_portfolio_view()` → `standardize_portfolio_input()`, which runs for ALL
position sources. CSV is not special-cased in the analysis pipeline.

**Registration in PositionService** (`services/position_service.py:__init__`):

```python
# Always register CSV provider — works in both DB and no-DB modes
from providers.csv_positions import CSVPositionProvider
position_providers["csv"] = CSVPositionProvider()
```

**Routing bypass**: CSV provider skips the standard routing filter in
`get_all_positions()`. It's not in `get_required_providers("positions")` so it
would be filtered out by the `needed` check at line 313:

```python
for provider_name in self._position_providers:
    if provider_name == "csv":
        pass  # Always include CSV — not in routing config
    elif needed is not None and provider_name not in needed:
        continue
```

#### CSV → API Graduation Model

CSV and API are **sequential states, not concurrent data sources**. The user journey is:

1. **Try it out**: Download CSV from broker → import → see risk analysis
2. **Get sold**: Connect brokerage API → live positions sync automatically
3. **Graduate**: API replaces CSV as source of truth. CSV data auto-archived.

**Safety guard in `get_all_positions()`**: To prevent double-counting when a user
connects an API while stale CSV data exists, `get_all_positions()` auto-skips CSV
positions whose `brokerage_name` matches any API provider's positions:

```python
# After collecting all provider DataFrames (line ~326):
# Build set of brokerage names with live API data
api_brokerages: set[str] = set()
for pname, (pdf, _, _) in provider_results.items():
    if pname == "csv" or pdf.empty:
        continue
    if "brokerage_name" in pdf.columns:
        api_brokerages.update(pdf["brokerage_name"].dropna().str.lower().unique())

# Auto-skip CSV positions for brokerages covered by API
if "csv" in provider_results and api_brokerages:
    csv_df, csv_cached, csv_age = provider_results["csv"]
    if not csv_df.empty and "brokerage_name" in csv_df.columns:
        keep_mask = ~csv_df["brokerage_name"].str.lower().isin(api_brokerages)
        if not keep_mask.all():
            skipped = (~keep_mask).sum()
            logger.info(f"Auto-skipped {skipped} CSV positions (API data available)")
            csv_df = csv_df[keep_mask].reset_index(drop=True)
            provider_results["csv"] = (csv_df, csv_cached, csv_age)
```

This is NOT dedup — it's a safety guard enforcing the graduation model. It uses
exact `brokerage_name` string matching (case-insensitive).

**Partial coverage edge case**: If the API covers only some accounts at a brokerage
(e.g., user connected one of three Schwab accounts via Plaid), the guard skips ALL
CSV positions for that brokerage — including accounts not covered by the API. This
is acceptable because:
1. Aggregators (Plaid/SnapTrade) enumerate all accounts at an institution — partial
   coverage is rare.
2. The alternative (account-level matching) requires reliable account_id correlation
   between CSV exports and API responses, which is fragile and brokerage-specific.
3. If a user hits this edge case, the agent can suggest re-importing only the
   uncovered accounts with a specific `label` (e.g., `label="ira"`) after clearing
   the full-brokerage CSV source.

**Name mismatch edge case**: If the CSV `brokerage_name` doesn't exactly match the
API provider's name (e.g., "Interactive Brokers" vs "IBKR"), both will appear. This
causes temporary double-counting. The agent detects this ("you have positions from
both CSV and IBKR API — want me to clear the CSV?") and suggests cleanup.

**Explicit cleanup**: `import_portfolio(action="clear")` removes CSV data. The agent
suggests this when it detects the user has graduated to API.

**Scenarios**:
- User imports IBKR CSV only (no API) → CSV positions used. Normal.
- User imports IBKR CSV + Fidelity CSV → both sources visible.
- User connects IBKR API → IBKR CSV positions auto-skipped. Fidelity CSV still visible.
- User runs `import_portfolio(action="clear", source_key="interactive_brokers")` → IBKR CSV removed.
- User runs `import_portfolio(action="clear")` → all CSV data removed. Graduation complete.

#### File-Based Position Storage

```
~/.risk_module/
  portfolios/
    {user_hash}/                    # SHA-256 hash of user_email (first 12 chars)
      positions.json                # All CSV-imported positions, keyed by source
```

**User directory**: Hashed, not raw email — avoids filesystem issues with `@`, `.`, special chars.

**Storage schema** (`positions.json`):
```json
{
  "schema_version": 1,
  "sources": {
    "interactive_brokers": {
      "imported_at": "2026-03-08T10:30:00Z",
      "brokerage_name": "Interactive Brokers",
      "source_file": "U2471778_20260309.csv",
      "positions": [...]
    },
    "fidelity_roth": {
      "imported_at": "2026-03-08T11:00:00Z",
      "brokerage_name": "Fidelity",
      "source_file": "Fidelity-Positions-2026-03-08.csv",
      "positions": [...]
    }
  }
}
```

**Replace semantics**: Importing with the same `source_key` replaces that source's
positions. Different source_keys are additive. All positions across all sources are
flattened on read by `CSVPositionProvider.fetch_positions()`.

**Clear operation**: `import_portfolio(action="clear", source_key="interactive_brokers")`
removes that source from the JSON. `import_portfolio(action="clear")` with no source_key
clears all CSV data (for when the user graduates to API).

**Atomic writes + locking**: Read-modify-write cycle protected by `fcntl.flock()`
(exclusive lock on `positions.json.lock` sidecar file) to prevent concurrent
import/clear operations from losing data. Lock acquired before read, released
after `os.replace()`. The `tempfile.NamedTemporaryFile` + `os.replace()` pattern
ensures the file is never partially written.

#### Position Schema

Each position dict in the JSON file is produced by `PositionRecord.to_dict()` (see
`POSITION_INGESTION_CONTRACT.md`). Validated at ingestion, safe for JSON round-trip.
Example:

```json
{
  "ticker": "AAPL",
  "name": "Apple Inc",
  "quantity": 100.0,
  "price": 150.00,
  "value": 15000.00,
  "cost_basis": 12000.00,
  "type": "equity",
  "currency": "USD",
  "account_id": "ibkr-U2471778",
  "account_name": "Individual Margin",
  "brokerage_name": "Interactive Brokers",
  "position_source": "csv_interactive_brokers"
}
```

Required fields and validation rules: see `POSITION_INGESTION_CONTRACT.md` (`PositionRecord` contract, Codex-reviewed 7/7 PASS).

#### Value Derivation Rules

Normalizers must produce `value` for each `PositionRecord`. The precedence order:

1. **CSV has value column** → use directly (most brokerages include market value)
2. **CSV has quantity + price but no value** → `value = quantity × price`
3. **CSV has quantity only (no price, no value)** → normalizer sets `value = 0.0`
   and adds a warning. Downstream pipeline will re-price via FMP `latest_price()`.
   If FMP has no price, the position appears with $0 value (visible in dry_run).

**Currency handling**: Positions are stored in their **native currency** as reported
by the CSV. The `currency` field on `PositionRecord` carries this (e.g., "GBP", "HKD").
FX conversion to portfolio base currency happens downstream in the analysis pipeline
(`build_portfolio_view()` → `get_currency_resolver()`), the same path used by all
providers. Normalizers do NOT convert to USD — they preserve the CSV's currency.

**Exception — IBKR "Value in USD" columns**: The IBKR Activity Statement reports
some values pre-converted to USD (e.g., "Value in USD" in Forex Balances). The IBKR
normalizer uses these USD values directly and sets `currency = "USD"`.

#### Cash and Derivative Normalization

Each normalizer handles cash/derivative detection for its brokerage format.
The IBKR reference normalizer demonstrates the pattern (see IBKR section above
for cash handling details — use Forex Balances, NOT NAV Cash row).

All normalizers follow these conventions:
1. Cash rows → `PositionType.CASH`, `ticker: "CUR:USD"` (or CUR:GBP, etc.)
2. Options → `PositionType.OPTION`, preserve strike/expiry in ticker
3. Futures → `PositionType.DERIVATIVE` (needed for `instrument_types` dispatch)
4. Bonds/fixed income → `PositionType.BOND`
5. ETFs → `PositionType.ETF`, mutual funds → `PositionType.MUTUAL_FUND`
6. Default equities → `PositionType.EQUITY`

Valid types: all members of `PositionType` enum (see `POSITION_INGESTION_CONTRACT.md`).
Aliases like `cryptocurrency`, `fixed_income`, `loan` are accepted and canonicalized
in `to_dict()`. Full list: equity, etf, cash, option, derivative, bond, mutual_fund,
fund, crypto, warrant, commodity, other.
These match what `PortfolioData.from_holdings()` and downstream analysis expect
(note: `bond` not `fixed_income` — see `data_objects.py:545`, `positions.py:214`).

This ensures correct downstream handling:
- `PortfolioData.from_holdings()` classifies cash via `ticker.startswith("CUR:")` or `type == "cash"` (`data_objects.py:555`)
- Cash proxy mapping works via `cash_map.yaml` (`data_objects.py:652`)
- `type: "derivative"` triggers futures pricing chain in `latest_price()` / `get_returns_dataframe()`
- `type: "option"` routes through option pricing (B-S fallback) when `OPTION_PRICING_PORTFOLIO_ENABLED`

#### MCP Tool Interface

**File**: New `mcp_tools/import_portfolio.py`

```python
@handle_mcp_errors
def import_portfolio(
    file_path: str = "",          # Path to CSV file (required for "import" action)
    brokerage: str = "",          # Force specific normalizer: "ibkr", etc.
    label: str = "",              # Optional: disambiguate same-brokerage imports (e.g. "roth", "individual")
    dry_run: bool = True,         # Preview before importing
    action: str = "import",       # "import" (default), "list" (show sources), or "clear" (remove CSV data)
    source_key: str = "",         # For clear: which source to clear (empty = clear all)
    user_email: str = None,
) -> dict:
    """Import portfolio positions from a brokerage CSV export, or clear CSV data.

    Actions:
      import — Parse CSV, validate, save positions (default)
      list   — Show current CSV sources (source_key, brokerage, position count, imported_at)
      clear  — Remove CSV-imported positions (all sources or specific source_key)

    Resolution order (for import action):
    1. If `brokerage` provided → use that normalizer directly
    2. Otherwise → auto-detect by running each normalizer's detect()
    3. If no normalizer matches → return `status: "needs_normalizer"` with
       file preview so agent can write a normalizer module

    Source key (for replace semantics) — slugified, not display name:
    - source_key = slugify(brokerage_name) + "_" + slugify(label) if label provided
    - source_key = slugify(brokerage_name) + "_" + slugify(account_id) if single-account, no label
    - source_key = slugify(brokerage_name) if multi-account, no label
    - Examples: "interactive_brokers", "charles_schwab_roth", "charles_schwab_individual"
    - Re-importing with same source_key replaces that source
    - Different source_keys are additive
    """
```

**Returns** (dry_run=True):
```json
{
  "status": "ok",
  "dry_run": true,
  "brokerage_name": "Interactive Brokers",
  "source_key": "interactive_brokers",
  "positions_found": 12,
  "total_value": 31109.13,
  "preview": [
    {"ticker": "AAPL", "quantity": 2, "value": 527.5, "type": "equity", "currency": "USD"},
    {"ticker": "AT.", "quantity": 400, "value": 1638.0, "type": "equity", "currency": "GBP"}
  ],
  "warnings": [],
  "errors": [],
  "message": "Re-run with dry_run=false to import."
}

**Error semantics**: `errors` lists per-row validation failures from `try_build_position()`.
`dry_run=True` shows all errors for review. `dry_run=False` is **all-or-nothing**: if any
row fails validation, the import is rejected and no positions are saved. The user/agent
fixes the normalizer and retries. Partial imports (save valid rows, skip bad ones) are
not supported — they create silent data gaps that corrupt analysis.
```

**Returns** (dry_run=False):
```json
{
  "status": "ok",
  "imported": 12,
  "source_key": "interactive_brokers",
  "brokerage_name": "Interactive Brokers",
  "message": "Portfolio imported. 12 positions ($31K). Run get_risk_analysis() to see your risk profile."
}
```

**Returns** (no normalizer matches — agent writes one):
```json
{
  "status": "needs_normalizer",
  "first_20_lines": [
    "Positions for Account XXX-1234",
    "As of 03/10/2026",
    "",
    "Sym,Desc,Shares,Mkt Price,Mkt Val",
    "AAPL,Apple Inc,100,150.00,15000.00",
    "SGOV,iShares Short Treasury,500,99.50,49750.00"
  ],
  "row_count": 42,
  "message": "No normalizer matched this CSV format. See inputs/normalizers/ibkr.py for the reference pattern. Write a normalizer module to ~/.risk_module/normalizers/{name}.py with detect(lines) and normalize(lines, filename) functions that produce PositionRecord instances, then re-run."
}
```

The agent writes a .py file with `detect()` and `normalize()`, saves it to
`~/.risk_module/normalizers/`, and re-runs `import_portfolio()`. This is real
Python code — no limitations of a JSON schema.

### Implementation Scope

| Component | File | Effort |
|-----------|------|--------|
| Ingestion contract | New: `inputs/position_schema.py` | Small — `PositionType`, `PositionRecord`, `NormalizeResult`, batch helpers (designed in `POSITION_INGESTION_CONTRACT.md`, Codex-reviewed 7/7 PASS) |
| Normalizer framework | New: `inputs/normalizers/__init__.py` | Small — registry, detect loop, user normalizer loader |
| IBKR reference normalizer | New: `inputs/normalizers/ibkr.py` | Medium — reuses `materialize_tables()` from existing script, adds position extraction |
| CSVPositionProvider | New: `providers/csv_positions.py` | Small |
| MCP tool (`import_portfolio`) | New: `mcp_tools/import_portfolio.py` | Small |
| CSV provider integration | `services/position_service.py` | Small — register `"csv"` provider, add `_get_positions_df("csv")` bypass (no cache), routing bypass in `get_all_positions()` |
| Tool registration | `mcp_server.py` | Trivial — register `import_portfolio` |
| Tests | See test scope below | Medium |

**Test scope**:
| Test file | Coverage |
|-----------|----------|
| `tests/inputs/test_position_schema.py` | PositionRecord validation, PositionType canonicalization, parse_position_type, try_build_position, build_position_batch, JSON round-trip |
| `tests/inputs/test_normalizers.py` | IBKR normalizer against real CSVs in `docs/`, registry loader for `~/.risk_module/normalizers/`, detect loop, **error handling**: syntax error in user normalizer (skipped with warning), missing detect/normalize (skipped), module reload on re-import |
| `tests/providers/test_csv_positions.py` | CSVPositionProvider: `fetch_positions` returns empty DataFrame when no data, reads JSON correctly, missing file → empty (not error) |
| `tests/services/test_position_service_csv.py` | `get_all_positions()` routing bypass, `_get_positions_df("csv")` bypasses cache/TTL pipeline, invisibility when no CSV file, multi-import additive by source_key (importing one brokerage doesn't wipe another) |
| `tests/mcp_tools/test_import_portfolio.py` | dry_run preview, needs_normalizer response, source_key replace semantics (additive across source_keys, replace within same source_key), label parameter, list action (returns source_key/brokerage/count/imported_at per source), clear action (single source + clear all) |

### Built-In Normalizer (Reference)

One built-in normalizer ships with the repo as a working example and reference pattern:

- [ ] **IBKR** — `inputs/normalizers/ibkr.py` (tested against `docs/U2471778_20260309.csv` and longer-period statements)

All other brokerages (Schwab, Fidelity, Vanguard, etc.) are handled by agent-created
normalizers at runtime. No pre-built normalizers per brokerage — the infrastructure
is the product, not a library of parsers.

### Agent-Created Normalizers (Runtime)

When a user provides a CSV from any brokerage without a matching normalizer:
1. `import_portfolio()` returns `status: "needs_normalizer"` with first 20 lines of the file
2. Agent reads the file structure and the IBKR reference normalizer (`inputs/normalizers/ibkr.py`) for pattern guidance
3. Agent writes a Python normalizer with `detect()` + `normalize()` that produces `PositionRecord` instances via `try_build_position()`
4. Agent saves the .py file to `~/.risk_module/normalizers/{brokerage}.py`
5. Agent re-runs `import_portfolio()` — the new normalizer is discovered and used

This is real Python code — the agent can handle any CSV format: multi-section files,
preamble rows, conditional logic, regex patterns, whatever the format requires. The
normalizer interface (`detect` + `normalize` returning `NormalizeResult` with validated
`PositionRecord` instances) is the only contract.

**Trust model**: Agent-created normalizers are arbitrary Python code. This is NOT a
security escalation — the agent (Claude Code) already has full filesystem and shell
access. The normalizer is no more dangerous than any other file the agent writes.
The user approves the file write via Claude Code's permission system.

**Tier scoping**: Runtime normalizer authoring (agent writes .py files to disk) is
scoped to **Tier 1 (local MCP) only**. For hosted web tiers (3-5), only reviewed
built-in normalizers in `inputs/normalizers/` are loaded — the user directory
`~/.risk_module/normalizers/` is NOT scanned. This prevents arbitrary code execution
on shared servers. Web-tier users upload CSVs via the web UI, which routes through
built-in normalizers only. If no normalizer matches, the upload fails with a
"format not supported" error (not a "write a normalizer" prompt).

**Error handling in normalizer loader** (`inputs/normalizers/__init__.py`):
- `importlib.util.spec_from_file_location()` + `module_from_spec()` + `exec_module()` loads each `.py` file from `~/.risk_module/normalizers/`
- Syntax errors, import errors, and missing `detect`/`normalize` functions are caught
  per-module with a warning logged (not a crash). Bad normalizers are skipped — they
  don't prevent other normalizers from running.
- Each `_all_normalizers()` call re-scans the directory and re-imports modules (no
  stale module cache). This allows the agent to write a normalizer and immediately
  re-run `import_portfolio()` without restarting the MCP server.
- `importlib.util.spec_from_file_location()` + `module_from_spec()` for isolation —
  user normalizers don't pollute `sys.modules`.

```python
def _load_user_normalizers() -> list:
    """Load normalizer modules from ~/.risk_module/normalizers/.

    Only called in Tier 1 (local MCP) mode. Hosted web tiers skip this
    to prevent arbitrary code execution on shared servers.
    """
    user_dir = Path.home() / ".risk_module" / "normalizers"
    if not user_dir.is_dir():
        return []
    normalizers = []
    for py_file in sorted(user_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(
                f"user_normalizer_{py_file.stem}", py_file
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if not hasattr(mod, "detect") or not hasattr(mod, "normalize"):
                logger.warning(f"Normalizer {py_file.name}: missing detect/normalize")
                continue
            normalizers.append(mod)
        except Exception as e:
            logger.warning(f"Failed to load normalizer {py_file.name}: {e}")
    return normalizers
```

---

## Step 3: Startup Validation

### Problem

Missing env vars produce cryptic runtime errors. A user who forgets `FMP_API_KEY` gets a confusing API error deep in a tool call, not a clear "you need to set FMP_API_KEY" at startup.

### Implementation

#### 3a. `.env` validation at MCP server startup

**File**: `mcp_server.py` (add near top, after `load_dotenv()`)

```python
def _validate_environment():
    """Check required and optional env vars, print helpful messages to stderr."""
    import sys
    out = sys.stderr  # MCP uses stdout for JSON-RPC

    issues = []

    # Required for basic functionality
    fmp_key = os.getenv("FMP_API_KEY")
    if not fmp_key:
        issues.append(
            "FMP_API_KEY not set. Sign up at https://financialmodelingprep.com "
            "for a free API key (100 calls/day). Set in .env file."
        )

    # Optional but recommended
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("No DATABASE_URL configured — running in no-DB mode.", file=out)
        print("  Portfolio analysis tools available via CSV import.", file=out)
        print("  Set DATABASE_URL for full functionality (baskets, transactions, audit).", file=out)

    # User email — needed for position scoping in MCP mode
    user_email = os.getenv("RISK_MODULE_USER_EMAIL")
    if not user_email:
        issues.append(
            "RISK_MODULE_USER_EMAIL not set. Required for user-scoped tools. "
            "Add to .env: RISK_MODULE_USER_EMAIL=you@example.com"
        )

    # Optional provider status
    providers_found = []
    for provider, env_var in [
        ("Plaid", "PLAID_CLIENT_ID"),
        ("SnapTrade", "SNAPTRADE_KEY"),
        ("Schwab", "SCHWAB_APP_KEY"),
        ("IBKR", "IBKR_GATEWAY_HOST"),
    ]:
        if os.getenv(env_var):
            providers_found.append(provider)

    if providers_found:
        print(f"Providers: {', '.join(providers_found)}", file=out)
    else:
        print("No brokerage providers configured. Use import_portfolio to load a CSV.", file=out)

    if issues:
        print("\nConfiguration issues:", file=out)
        for issue in issues:
            print(f"  - {issue}", file=out)
        print(file=out)

    return len(issues) == 0

_validate_environment()
```

**Note**: All output goes to `stderr` — MCP uses `stdout` for JSON-RPC protocol. Emojis removed (per user preference pattern).

#### 3b. `make check` health check

**File**: `Makefile` (add target)

```makefile
check:
	@python -c "from scripts.health_check import run_health_check; run_health_check()"
```

**File**: New `scripts/health_check.py`

Validates:
- Python version >= 3.10
- Required packages installed
- `.env` file exists with required vars
- FMP API key works (test `GET /v3/quote/AAPL`)
- Database connection (if `DATABASE_URL` set)
- Brokerage provider status

---

## Execution Order

1. **Step 1** first — Makes MCP server functional without Postgres. Low risk, mostly guard additions.
2. **Step 2** next — CSV import. Requires CSV format research first. High impact — this is what makes the system actually useful to new users.
3. **Step 3** last — Polish. Startup validation and health checks.

## Success Criteria

After all three steps:

```
$ unset DATABASE_URL
$ cat > .env << 'EOF'
FMP_API_KEY=xxx
RISK_MODULE_USER_EMAIL=you@example.com
EOF
$ python mcp_server.py
No DATABASE_URL configured — running in no-DB mode.
  Portfolio analysis tools available via CSV import.
No brokerage providers configured. Use import_portfolio to load a CSV.

# User attaches IBKR Activity Statement CSV in Claude:
> "import my portfolio from this CSV"
> Detected: Interactive Brokers, 12 positions, $31K total value. Re-run with dry_run=false to import.
> "yes, import it"
> Portfolio imported. 12 positions ($31K).

> "what's my risk analysis?"
> [Full risk analysis with sector exposure, correlations, VaR, etc.]

> "what are my positions?"
> [42 positions from CSV import]

> "what's my projected dividend income?"
> [Income projection from CSV positions + FMP dividend data]

> "run an optimization"
> [min_variance optimization results with rebalance suggestions]

> "ingest my transactions"
> This feature requires a PostgreSQL database. Set DATABASE_URL in .env.
```

## Not in Scope

- SQLite backend for config/baskets (Phase B)
- Google OAuth bypass (Phase B)
- Docker Compose (infrastructure track — not an onboarding phase)
- Frontend changes (frontend already shows what MCP tools return)
- Multi-user support without DB (single-user only in no-DB mode)
- Full CSV/API dedup logic — lightweight `brokerage_name` safety guard exists (see "CSV → API Graduation Model"); institution alias resolution dedup is not in scope
- Transaction import from CSV (see `BROKERAGE_STATEMENT_IMPORT_PLAN.md` — separate plan, separate normalizer system)
- Sample / demo portfolio (Phase B or standalone — no persistence mechanism needed, just a JSON fixture)
- `max_return` optimization without DB (requires expected returns stored in DB — `min_variance` works)

---

## Related Documents

| Document | Relationship |
|----------|-------------|
| `POSITION_INGESTION_CONTRACT.md` | Schema contract for Step 2 — `PositionRecord`, `NormalizeResult` |
| `ONBOARDING_STRATEGY.md` | Parent strategy — phase sequencing, tier mapping |
| `ONBOARDING_FRICTION_AUDIT.md` | Original friction audit that motivated this plan |
| `PRODUCT_TIERS.md` | Tier architecture — `is_db_available()` as tier boundary |
| `BROKERAGE_STATEMENT_IMPORT_PLAN.md` | Transaction normalizers (separate system, see "Two Normalizer Systems" section) |
| `ONBOARDING_WIZARD_PLAN.md` | Web app wizard — Phase 3 depends on this plan's Step 2 for CSV path |
| `PHASE_B_LIGHTWEIGHT_PERSISTENCE_PLAN.md` | Deferred — extends no-DB mode to 37 tools |

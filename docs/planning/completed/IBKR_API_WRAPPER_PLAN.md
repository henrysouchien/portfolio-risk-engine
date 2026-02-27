# IBKR API Wrapper Extension Plan

> **Status**: Complete
> **Created**: 2026-02-15
> **Updated**: 2026-02-15 — Round 1: addressed 2 HIGH, 8 MEDIUM, 2 LOW. Round 2: addressed 1 MEDIUM, 2 LOW.
> **Owner**: Codex + Henry
> **Depends on**: IBKR Market Data Client (complete)

## Summary

Extend `services/ibkr_data/` from a historical-data-only client into a full IBKR API wrapper, similar to how `fmp/` wraps FMP endpoints. Adds positions, account summary, PnL, contract details, and option chains — giving Claude and the CLI direct access to IBKR's full data surface.

## Why Now

The IBKR Market Data Client (`services/ibkr_data/client.py`) was built to solve P-002 (unpriceable symbols) and only wraps `reqHistoricalData`. IBKR's API offers much more that we currently access only through the broker adapter (trade execution path):

| Capability | Current access | Gap |
|---|---|---|
| Historical prices | `IBKRMarketDataClient.fetch_series()` | None — fully implemented |
| Positions | `IBKRBrokerAdapter` (trade path only) | No standalone data access |
| Account summary | `IBKRBrokerAdapter._get_account_balance_internal()` (balance only) | No full summary (margin, buying power, net liq) |
| P&L | None | No daily/unrealized/realized P&L access |
| Contract details | `ib.qualifyContracts()` scattered inline | No centralized metadata lookup |
| Option chains | None | Can't discover available strikes/expirations |

The broker adapter has proven patterns for these calls but is tightly coupled to trade execution. A standalone wrapper makes this data accessible to analysis tools, MCP, and CLI without going through the trading path.

## Architecture: Smart Routing

Two connection strategies based on data type:

- **Account/positions/PnL/metadata** → `IBKRConnectionManager` (persistent, settings-driven client ID and readonly flag) — shares the Gateway session that trade execution uses
- **Market data** → `IBKRMarketDataClient` (per-request, read-only, client ID = `IBKR_CLIENT_ID + 1`) — isolated from trades

**Thread safety**: `IBKRConnectionManager`'s `RLock` only protects connect/disconnect, not request calls. The facade adds a module-level `threading.Lock` (`_ibkr_shared_lock`) that serializes all shared-connection requests. This lock is defined in `services/ibkr_data/ibkr_client.py` and **also imported/used by `IBKRBrokerAdapter`** to cover ALL methods that touch the shared `IB` instance: `list_accounts`, `search_symbol`, `preview_order`, `place_order`, `get_orders`, `cancel_order`, `get_account_balance`. This ensures no concurrent calls on the non-thread-safe `IB` connection regardless of entry point.

**Account authorization**: All account operations filter through `IBKR_AUTHORIZED_ACCOUNTS` (from `settings.py`), matching the pattern in `IBKRBrokerAdapter.owns_account()` (`ibkr_broker_adapter.py:48-59`).

**Account ID resolution**: When `account_id=None`, auto-select if exactly one managed account exists. If multiple accounts, raise `IBKRAccountError` requiring explicit `--account`.

No registry pattern (unlike FMP). IBKR's API is stateful and heterogeneous — method-per-capability is cleaner. A lightweight capability descriptor system provides discoverability (`list_capabilities()` / `describe()`).

## File Plan

```
services/ibkr_data/
  __init__.py         # MODIFY — add new exports
  ibkr_client.py      # NEW — IBKRClient facade (smart routing, request lock, discoverability)
  account.py          # NEW — positions, account summary, PnL (via ConnectionManager)
  metadata.py         # NEW — contract details, option chains (via ConnectionManager)
  capabilities.py     # NEW — capability descriptors for list/describe
  exceptions.py       # MODIFY — add IBKRAccountError, IBKRTimeoutError
  client.py           # UNCHANGED — IBKRMarketDataClient stays as-is
  contracts.py        # UNCHANGED
  profiles.py         # UNCHANGED
  cache.py            # UNCHANGED

run_ibkr_data.py                           # MODIFY — add subcommands
services/ibkr_broker_adapter.py            # MODIFY — import & use _ibkr_shared_lock for ALL methods that touch shared IB instance
tests/services/test_ibkr_client_facade.py  # NEW — facade + account + metadata tests
```

## Phase 1: Foundation — IBKRClient Facade + Capabilities

### `services/ibkr_data/ibkr_client.py` (NEW)

```python
import threading

_ibkr_shared_lock = threading.Lock()
"""Serializes all calls on the shared IBKRConnectionManager IB instance.

Used by BOTH IBKRClient (account/metadata ops) AND IBKRBrokerAdapter (trade ops)
to prevent concurrent calls on the non-thread-safe ib_async IB object.
"""

class IBKRClient:
    """Unified IBKR API client with smart routing.

    - Account/positions/PnL/metadata → IBKRConnectionManager (persistent, serialized)
    - Market data → IBKRMarketDataClient (per-request, read-only)
    """

    def __init__(self, host=None, port=None, client_id=None):
        self._market_data = IBKRMarketDataClient(host, port, client_id)
        self._conn_manager = IBKRConnectionManager()

    def _get_account_ib(self):
        """Get persistent IB connection for account operations.

        Caller MUST hold _ibkr_shared_lock.
        """
        return self._conn_manager.ensure_connected()

    def _resolve_account_id(self, ib, account_id=None):
        """Resolve account_id: use provided, auto-select if single, error if ambiguous."""
        import settings
        accounts = list(ib.managedAccounts() or [])
        if settings.IBKR_AUTHORIZED_ACCOUNTS:
            accounts = [a for a in accounts if a in settings.IBKR_AUTHORIZED_ACCOUNTS]
        if account_id:
            if account_id not in accounts:
                raise IBKRAccountError(f"Account {account_id} not authorized or not found")
            return account_id
        if len(accounts) == 1:
            return accounts[0]
        if len(accounts) == 0:
            raise IBKRAccountError("No IBKR accounts available")
        raise IBKRAccountError(
            f"Multiple accounts available ({', '.join(accounts)}); specify --account"
        )

    # --- Delegated market data (existing, no lock needed) ---
    def fetch_series(self, **kw) -> pd.Series: ...
    def fetch_monthly_close_futures(self, **kw) -> pd.Series: ...
    def fetch_monthly_close_fx(self, **kw) -> pd.Series: ...
    def fetch_monthly_close_bond(self, **kw) -> pd.Series: ...
    def fetch_monthly_close_option(self, **kw) -> pd.Series: ...

    # --- Account data (Phase 2, all acquire _ibkr_shared_lock) ---
    def get_positions(self, account_id=None) -> pd.DataFrame: ...
    def get_account_summary(self, account_id=None) -> dict: ...
    def get_pnl(self, account_id=None) -> dict: ...
    def get_pnl_single(self, account_id, con_id) -> dict: ...

    # --- Metadata (Phase 3, acquires _ibkr_shared_lock) ---
    def get_contract_details(self, symbol, sec_type="STK", exchange="SMART", currency="USD") -> list[dict]: ...
    def get_option_chain(self, symbol, sec_type="STK", exchange="SMART") -> dict: ...

    # --- Discoverability ---
    def list_capabilities(self, category=None) -> list[dict]: ...
    def describe(self, capability_name) -> dict: ...
```

### `services/ibkr_data/capabilities.py` (NEW)

Lightweight descriptors (not a full registry like FMP):

```python
@dataclass(frozen=True)
class IBKRCapability:
    name: str
    category: str          # "market_data", "account", "metadata"
    description: str
    parameters: list[dict] # [{name, type, required, default, description}]
    return_type: str       # "DataFrame", "dict", "Series"
    requires_gateway: bool

_CAPABILITIES: dict[str, IBKRCapability] = {}

def register(cap: IBKRCapability): ...
def get_capability(name: str) -> IBKRCapability | None: ...
def list_capabilities(category: str | None = None) -> list[IBKRCapability]: ...
```

Capabilities to register: `fetch_series`, `positions`, `account_summary`, `pnl`, `pnl_single`, `contract_details`, `option_chain`, plus convenience wrappers.

### `services/ibkr_data/exceptions.py` — add:

```python
class IBKRAccountError(IBKRDataError):
    """Raised when account data request fails (auth, ambiguous account, etc.)."""

class IBKRTimeoutError(IBKRDataError):
    """Raised when IBKR request times out waiting for callbacks."""
```

## Phase 2: Account Data — Positions, Account Summary, PnL

### `services/ibkr_data/account.py` (NEW)

Pure functions that take an `ib` instance (from ConnectionManager). Caller holds `_ibkr_shared_lock`.

**`fetch_positions(ib, account_id=None) -> pd.DataFrame`**
- `ib.reqPositions()` is blocking in `ib_async` — returns directly, no `ib.sleep()` needed
- Reads `ib.positions()` after request completes
- Filters by `account_id` if provided
- Returns DataFrame columns: `account, symbol, sec_type, currency, exchange, con_id, position, avg_cost`
- Pattern reference: `IBKRBrokerAdapter._get_account_balance_internal()` (`ibkr_broker_adapter.py:482`)

**`fetch_account_summary(ib, account_id=None) -> dict`**
- Calls `ib.accountValues(account=account_id)` (already cached by Gateway after `reqAccountUpdates`)
- If empty, calls `ib.reqAccountUpdates(account=account_id)` — blocking, no sleep needed — then retries
- Extracts tags: `NetLiquidation, TotalCashValue, BuyingPower, GrossPositionValue, MaintMarginReq, AvailableFunds, ExcessLiquidity, SMA`
- Returns dict keyed by tag name (lowercase_snake), filtered to `currency="USD"` to avoid multi-currency overwrites (matching broker adapter pattern at `ibkr_broker_adapter.py:486`), all values as float
- Pattern reference: `IBKRBrokerAdapter._get_account_balance_internal()` (`ibkr_broker_adapter.py:482`)

**`fetch_pnl(ib, account_id) -> dict`**
- `ib.reqPnL()` is a **streaming subscription**, not blocking — requires polling
- Poll with timeout (default 5s) until `pnl.dailyPnL` is not NaN
- If timeout, raise `IBKRTimeoutError`
- Returns: `{account_id, daily_pnl, unrealized_pnl, realized_pnl}`
- **Always cancel in `finally`**: `ib.cancelPnL(account_id, modelCode="")` (correct ib_async signature — requires account + modelCode args)

**`fetch_pnl_single(ib, account_id, con_id) -> dict`**
- Same streaming subscription pattern as `fetch_pnl`
- Poll with timeout until `pnl.dailyPnL` is not NaN
- Returns: `{account_id, con_id, daily_pnl, unrealized_pnl, realized_pnl, position, value}`
- **Always cancel in `finally`**: `ib.cancelPnLSingle(account_id, modelCode="", conId=con_id)` (correct ib_async signature)

**Caching policy**: None — live account data, always fetch fresh.

## Phase 3: Metadata — Contract Details + Option Chains

### `services/ibkr_data/metadata.py` (NEW)

Caller holds `_ibkr_shared_lock`.

**`fetch_contract_details(ib, symbol, sec_type="STK", exchange="SMART", currency="USD") -> list[dict]`**
- Builds contract by `sec_type`:
  - `STK` → `Stock(symbol, exchange, currency)`
  - `FUT` → `Future(symbol=symbol, exchange=exchange, currency=currency)` or `ContFuture`
  - `OPT` → `Contract(symbol=symbol, secType="OPT", exchange=exchange, currency=currency)`
  - Other → `Contract(symbol=symbol, secType=sec_type, exchange=exchange, currency=currency)`
- Calls `ib.reqContractDetails(contract)` — blocking, returns directly
- Normalizes each `ContractDetails` object to dict with keys: `con_id, symbol, sec_type, exchange, primary_exchange, currency, multiplier, min_tick, trading_class, valid_exchanges, long_name, industry, category, subcategory, trading_hours, liquid_hours, last_trade_date`
- Raises `IBKRContractError` if no results

**`fetch_option_chain(ib, symbol, sec_type="STK", exchange="SMART") -> dict`**
- Build and qualify underlying by `sec_type`:
  - `STK` → `Stock(symbol, exchange, "USD")` (explicit currency, matching `ibkr_broker_adapter.py:89`)
  - `FUT` → resolve via existing `resolve_futures_contract()` from `contracts.py`
- Calls `ib.qualifyContracts(contract)` to get `conId`
- Calls `ib.reqSecDefOptParams(underlyingSymbol=symbol, futFopExchange=fop_exchange, underlyingSecType=sec_type, underlyingConId=con_id)`
  - `futFopExchange=""` for STK, set to actual exchange for FUT
- Returns: `{underlying, con_id, chains: [{exchange, expirations: [...], strikes: [...], multiplier}]}`
- Raises `IBKRContractError` if qualification fails

**Caching policy**: None for v1 (keep simple).

## Phase 4: CLI Extension

### `run_ibkr_data.py` — add subcommands

Current: positional args `SYMBOLS instrument_type`
New: subcommand-based for non-market-data queries

```bash
# Existing (unchanged, backward-compatible)
python run_ibkr_data.py data ES futures
python run_ibkr_data.py data EURUSD fx --start 2025-01-01

# New subcommands
python run_ibkr_data.py positions [--account ACCT] [--format table|csv|json]
python run_ibkr_data.py account [--account ACCT]
python run_ibkr_data.py pnl [--account ACCT]
python run_ibkr_data.py contract AAPL [--sec-type STK|FUT|OPT|BOND]
python run_ibkr_data.py chain AAPL [--sec-type STK|FUT]
python run_ibkr_data.py capabilities [--category account|market_data|metadata]

# Discovery (unchanged)
python run_ibkr_data.py --list-profiles
python run_ibkr_data.py --list-futures
python run_ibkr_data.py --list-what-to-show
```

**Backward compat strategy**: Two-stage parse. Check if `sys.argv[1]` is a known subcommand (`data`, `positions`, `account`, `pnl`, `contract`, `chain`, `capabilities`). If not, treat as legacy positional mode (symbols + instrument type). This avoids `argparse` subparser ambiguity.

**Account authorization**: CLI subcommands respect `IBKR_AUTHORIZED_ACCOUNTS` setting, same as broker adapter.

## Phase 5: Wire + Export + Tests

### `services/ibkr_data/__init__.py`

Add exports: `IBKRClient`, `IBKRAccountError`, `IBKRTimeoutError`

### `tests/services/test_ibkr_client_facade.py` (NEW)

All mock-based (no gateway required):

**Facade tests:**
- `test_facade_delegates_market_data` — verify `fetch_series` delegates to `IBKRMarketDataClient`
- `test_facade_list_capabilities` — verify capability listing with category filter
- `test_facade_describe` — verify capability description

**Account tests (mock `ib` object):**
- `test_fetch_positions_returns_dataframe` — mock `ib.positions()` with fake Position objects
- `test_fetch_positions_filters_by_account` — verify account_id filtering
- `test_fetch_positions_empty` — returns empty DataFrame
- `test_fetch_account_summary` — mock `ib.accountValues()` with AccountValue objects
- `test_fetch_account_summary_triggers_update_when_empty` — verify `reqAccountUpdates` fallback
- `test_fetch_pnl` — mock `ib.reqPnL()` return value with populated fields
- `test_fetch_pnl_cancels_subscription` — verify cleanup with correct args (account_id, modelCode)
- `test_fetch_pnl_timeout_raises` — NaN values after timeout → `IBKRTimeoutError`

**Metadata tests (mock `ib` object):**
- `test_fetch_contract_details` — mock `ib.reqContractDetails()` with fake ContractDetails
- `test_fetch_contract_details_no_results` — raises IBKRContractError
- `test_fetch_contract_details_by_sec_type` — verify STK/FUT/OPT build different contracts
- `test_fetch_option_chain` — mock `ib.qualifyContracts()` + `ib.reqSecDefOptParams()`
- `test_fetch_option_chain_unqualified` — raises IBKRContractError
- `test_fetch_option_chain_futures` — verify futFopExchange set for FUT underlyings

**Account resolution tests:**
- `test_resolve_single_account_auto` — one managed account → auto-selected
- `test_resolve_multi_account_requires_explicit` — multiple accounts → raises IBKRAccountError
- `test_resolve_account_auth_filtering` — `IBKR_AUTHORIZED_ACCOUNTS` respected

**CLI tests:**
- `test_legacy_positional_mode` — `ES futures` still works without `data` prefix
- `test_subcommand_dispatch` — `positions`, `account`, etc. route correctly

### Live testing (manual, with Gateway/TWS running):

```bash
python run_ibkr_data.py positions
python run_ibkr_data.py account
python run_ibkr_data.py pnl
python run_ibkr_data.py contract AAPL
python run_ibkr_data.py chain AAPL
python run_ibkr_data.py capabilities
# Legacy compat
python run_ibkr_data.py ES futures
```

## Execution Order

| Phase | Scope | Files | Risk |
|-------|-------|-------|------|
| 1 | Facade + capabilities + exceptions | `ibkr_client.py`, `capabilities.py`, `exceptions.py`, `__init__.py` | Low |
| 2 | Positions + account + PnL | `account.py`, wire into `ibkr_client.py` | Medium |
| 3 | Contract details + option chains | `metadata.py`, wire into `ibkr_client.py` | Low |
| 4 | CLI subcommands | `run_ibkr_data.py` | Low |
| 5 | Exports + tests | `__init__.py`, `test_ibkr_client_facade.py` | Low |

Phases 2 and 3 are independent and can be developed in parallel after Phase 1.

## Key Reuse

| Pattern | Source | Reuse in |
|---|---|---|
| Persistent connection singleton | `services/ibkr_connection_manager.py` | Account/metadata ops |
| Account authorization check | `ibkr_broker_adapter.py:48-59` | `ibkr_client.py:_resolve_account_id()` |
| `accountValues()` access | `ibkr_broker_adapter.py:482-498` | `account.py:fetch_account_summary()` |
| `qualifyContracts()` + `Stock()` | `ibkr_broker_adapter.py:84-96` | `metadata.py` |
| Market data delegation | `services/ibkr_data/client.py` | `ibkr_client.py` pass-through |
| Exception hierarchy | `services/ibkr_data/exceptions.py` | Extend with 2 new types |

## Constraints

- **Thread safety**: Module-level `_ibkr_shared_lock` serializes ALL shared-connection requests across both `IBKRClient` and `IBKRBrokerAdapter` (ConnectionManager's `RLock` only covers connect/disconnect)
- **Event loop**: `nest_asyncio.apply()` already handled at module import in `client.py`
- **Client ID separation**: Market data = `IBKR_CLIENT_ID + 1` (read-only), Account = settings-driven via `IBKRConnectionManager`
- **No breaking changes**: `IBKRMarketDataClient` is untouched; `IBKRClient` is additive
- **No caching for account data**: Positions/PnL are live — always fetch fresh
- **PnL subscriptions**: Always cancel in `finally` with correct ib_async signatures (`cancelPnL(account, modelCode)`)
- **Account authorization**: Respect `IBKR_AUTHORIZED_ACCOUNTS` from settings in all account operations

## Codex Review Log

### Review 1 (2026-02-15)

**HIGH (2):**
1. `cancelPnL()` called with no args — ib_async requires `cancelPnL(account, modelCode='')`. **Fixed**: Plan now specifies correct signatures with account + modelCode args, always in `finally`.
2. Thread safety overstated — ConnectionManager lock only covers connect/disconnect. **Fixed**: Added `_ibkr_shared_lock` (module-level `threading.Lock`) that serializes all shared-connection requests.

**MEDIUM (8):**
3. PnL subscriptions leak + return NaN — need polling with timeout. **Fixed**: Poll with timeout, raise `IBKRTimeoutError` on NaN, always cancel in `finally`.
4. `account_id` semantics inconsistent. **Fixed**: Auto-select single account, raise `IBKRAccountError` for multiple, added `_resolve_account_id()` helper.
5. `reqPositions()`/`reqAccountUpdates()` are blocking — `ib.sleep(2)` redundant. **Fixed**: Removed sleep calls, use blocking return values directly.
6. Shared connection contention with trades. **Accepted**: Serialization via `_ibkr_shared_lock` prevents concurrent calls. Trade ops are already infrequent. Dedicated read-only connection would be over-engineering for v1.
7. Option chain not sec_type-generic. **Fixed**: Build/qualify underlying by sec_type, set `futFopExchange` for futures.
8. CLI backward-compat with subparsers fragile. **Fixed**: Two-stage parse (check first token) instead of argparse subparsers.
9. Missing `IBKR_AUTHORIZED_ACCOUNTS` filtering. **Fixed**: Added account authorization in `_resolve_account_id()` and documented throughout.
10. Test plan missing failure scenarios. **Fixed**: Added timeout, cancellation args, multi-account, auth filtering, and CLI legacy parse tests.

**LOW (2):**
11. Inaccurate reuse claim (`list_accounts()` → positions). **Fixed**: Updated references to actual methods used.
12. Client ID described as "0" but is settings-driven. **Fixed**: Changed to "settings-driven via `IBKRConnectionManager`".

### Review 2 (2026-02-15)

**MEDIUM (1):**
1. `_ibkr_shared_lock` is facade-local but trade-path calls in `IBKRBrokerAdapter` share the same IB connection without the lock. **Fixed**: Lock is defined in `ibkr_client.py` and imported by `IBKRBrokerAdapter` to wrap ALL methods that touch the shared IB instance (including `list_accounts`, `search_symbol`, not just trade ops).

**LOW (2):**
1. Account summary can overwrite same-tag values across currencies. **Fixed**: Filter `accountValues` to `currency="USD"` (matching broker adapter pattern).
2. Option chain `Stock()` missing explicit currency. **Fixed**: `Stock(symbol, exchange, "USD")` matching existing broker adapter pattern.

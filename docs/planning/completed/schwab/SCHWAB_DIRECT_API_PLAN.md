# Plan: Direct Schwab API Integration (Full Trading)

**Status:** COMPLETE
**Date:** 2026-02-16
**Key files:** `schwab_client.py`, `providers/schwab_positions.py`, `providers/schwab_transactions.py`, `providers/normalizers/schwab.py`, `services/schwab_broker_adapter.py`

## Context
User has approval for the Schwab Individual Trader API (developer.schwab.com) and wants to replace SnapTrade as the Schwab data/trading provider. This gives direct OAuth control, trading capability, and eliminates the SnapTrade middleman for Schwab. Credentials not yet set up on developer.schwab.com.

## Approach
Use `schwab-py` library (handles OAuth token management, auto-refresh, all API endpoints). Build a phased integration following existing patterns: `BrokerAdapter` for trading, `PositionProvider`/`TransactionProvider`/`TransactionNormalizer` for data.

**Canonical provider name**: `schwab` everywhere (source literals, normalizer key, routing, provider_name).

## Phase 1: OAuth Setup & Client Foundation

### Step 1: Install schwab-py
Add `schwab-py` to `requirements.txt` pinned to a tested version.

### Step 2: Add settings to `.env` and `settings.py`
```
SCHWAB_ENABLED=true
SCHWAB_APP_KEY=...
SCHWAB_APP_SECRET=...
SCHWAB_CALLBACK_URL=https://127.0.0.1:8182
SCHWAB_TOKEN_PATH=~/.schwab_token.json
```

In `settings.py`:
- Add `SCHWAB_ENABLED`, `SCHWAB_APP_KEY`, `SCHWAB_APP_SECRET`, `SCHWAB_CALLBACK_URL`, `SCHWAB_TOKEN_PATH`
- Add to `TRANSACTION_ROUTING`: `"charles_schwab": "schwab"`
- Add to `INSTITUTION_SLUG_ALIASES`: `"charles schwab": "charles_schwab"`, `"schwab": "charles_schwab"`

### Step 3: Create `schwab_client.py` — thin wrapper
- `get_schwab_client()` → calls `schwab.auth.client_from_token_file()` with auto-refresh
- `schwab_login()` → one-time `client_from_login_flow()` to generate initial token file
- `check_token_health()` → check `client.token_age`, warn if refresh token nearing 7-day expiry
- Token file stored locally (schwab-py manages refresh automatically — 30min access, 7-day refresh)
- **Expired refresh token handling**: detect `InvalidGrantError` on API calls, log clear message directing user to re-run `login` subcommand
- No AWS Secrets Manager needed — schwab-py handles token persistence to disk
- **Account hash mapping**: `get_account_hashes()` → returns `{account_number: account_hash}` dict, cached for session. All API calls use `account_hash` as canonical `account_id`.

### Step 4: Create `run_schwab.py` CLI
Subcommands: `login`, `accounts`, `positions`, `orders`, `transactions`, `status`
- `login` → runs OAuth flow, saves token file
- `status` → checks token file exists, token age, refresh token health
- `accounts` → list account numbers + hashes
- `positions` → show holdings
- `transactions` → show recent activity (default 60 days, `--days` flag for custom range)
- Pattern: mirrors `run_snaptrade.py` and `run_ibkr_data.py`

## Phase 2: Positions & Transactions

### Step 5: Create `providers/schwab_positions.py`
- `SchwabPositionProvider` implementing `PositionProvider` protocol
- `client.get_account(account_hash, fields=['positions'])` → normalize to DataFrame
- **Full required schema**: `ticker, name, quantity, price, value, cost_basis, currency, type, account_id, account_name, brokerage_name, position_source="schwab"`

### Step 6: Register in `PositionService`
- Add Schwab provider to `services/position_service.py` (gated by `SCHWAB_ENABLED`)
- Wire into position cache TTL, consolidation, and CLI/MCP surfaces (`run_positions.py`, `mcp_tools/positions.py`)

### Step 7: Create `providers/schwab_transactions.py`
- `SchwabTransactionProvider` implementing `TransactionProvider` protocol
- `client.get_transactions(account_hash, ...)` → raw transaction list
- **Transaction history depth**: Schwab API commonly limits to 60-day windows. Implement incremental sync:
  - Fetch in 60-day chunks going back up to `SCHWAB_HISTORY_DAYS` (default 365)
  - Persist fetched transactions locally (JSON/parquet cache) to avoid re-fetching
  - On subsequent calls, only fetch from last sync date forward

### Step 8: Create `providers/normalizers/schwab.py`
- `SchwabNormalizer` implementing `TransactionNormalizer` protocol
- Map Schwab transaction types → `NormalizedTrade`, `NormalizedIncome`, FIFO transactions
- Instrument type mapping: EQUITY→equity, OPTION→option, MUTUAL_FUND→equity, FIXED_INCOME→bond
- Export from `providers/normalizers/__init__.py`

### Step 9: Wire into data pipeline
- **9a: `trading_analysis/data_fetcher.py`** — full integration:
  - Add `"schwab_transactions": []` key to `_empty_transaction_payload()`
  - Register `SchwabTransactionProvider` in `_build_default_transaction_registry()` (gated by `SCHWAB_ENABLED`)
  - Add `"schwab"` to valid source set in `fetch_transactions_for_source()` (line 354)
- **9b: `trading_analysis/analyzer.py`** — accept Schwab data (follow existing normalizer architecture):
  - Add `schwab_transactions` parameter to `TradingAnalyzer.__init__()` and store as `self.schwab_transactions` (raw list of dicts, like `ibkr_flex_trades`)
  - Add `SchwabNormalizer` to default `self._normalizers` list (alongside SnapTrade, Plaid, IBKRFlex)
  - Add `"schwab"` branch in `_raw_data_for()` returning `self.schwab_transactions` — normalizer handles all transformation via existing `for normalizer in self._normalizers` loop
- **9c: Source literal updates** — add `"schwab"` to every `Literal["all", "snaptrade", "plaid", "ibkr_flex"]`:
  - `run_trading_analysis.py` — `--source` choices
  - `mcp_server.py` — source enum in `get_trading_analysis` (line 206), `get_performance` (line 273), `suggest_tax_loss_harvest` (line 758) tool registrations
  - `mcp_tools/trading_analysis.py` — source `Literal` (line 13), transaction count check (add `schwab_transactions` to sum, line 27-29), `TradingAnalyzer(...)` call (pass `schwab_transactions`, line 38-41)
  - `mcp_tools/performance.py` — source `Literal` (line 469), docstring only (does NOT instantiate `TradingAnalyzer` — delegates to `core/realized_performance_analysis.py`)
  - `mcp_tools/tax_harvest.py` — source `Literal` (line 590), `valid_source` set (line 629), error message (line 637), docstring
- **9d: Analyzer callers** — pass `schwab_transactions` from payload AND update source validation:
  - `mcp_tools/trading_analysis.py` — add `schwab_transactions` to transaction count (lines 27-29), pass to `TradingAnalyzer(...)` (lines 38-41)
  - `mcp_tools/tax_harvest.py` — pass `schwab_transactions=payload.get("schwab_transactions", [])` to `TradingAnalyzer`
  - `run_trading_analysis.py` — add `schwab_transactions` to total count (lines 125-129), pass to `TradingAnalyzer(...)` (lines 134-139), add to per-source count display (lines 143-145)
  - `core/realized_performance_analysis.py` — pass `schwab_transactions` to `TradingAnalyzer`, AND update source allowlist + error message (line 1752-1753: add `"schwab"` to `{"all", "snaptrade", "plaid", "ibkr_flex"}`)
- **9e: Update existing tests** for source/payload expansion:
  - `tests/unit/test_mcp_server_contracts.py` — update source enum assertions to include `"schwab"`
  - `tests/trading_analysis/test_provider_routing.py` — update valid source tests and payload shape assertions
  - `tests/providers/test_transaction_providers.py` — update payload key assertions
  - Add regression test: `mcp_tools/trading_analysis.py` with `source="schwab"` end-to-end

## Phase 3: Trading Execution

### Step 10: Create `services/schwab_broker_adapter.py`
- `SchwabBrokerAdapter` extending `BrokerAdapter` (from `core/broker_adapter.py`)
- **All abstract methods implemented**:
  - `provider_name` → `"schwab"`
  - `owns_account(account_id)` → check against cached account hashes
  - `list_accounts()` → account number, name, brokerage, cash balance, meta
  - `search_symbol(account_id, ticker)` → Schwab instrument search
  - `preview_order(account_id, ticker, side, quantity, order_type, time_in_force, limit_price=None, stop_price=None, symbol_id=None)` → **synthetic preview** (Schwab has no preview API): fetch quote, estimate cost/commission, return preview payload matching expected shape (`brokerage_order_id=None`, estimated `price`, `commission`, `quantity`)
  - `place_order(account_id, order_params)` → build `schwab.orders` order spec from `order_params` dict, submit via `client.place_order(account_hash, order)`, return payload with `brokerage_order_id`, `status`, quantity/price/commission fields
  - `get_orders(account_id, state, days)` → order history with status mapping to common enums (PENDING, ACCEPTED, EXECUTED, CANCELED, PARTIAL, REJECTED)
  - `cancel_order(account_id, order_id)` → cancel open order
  - `get_account_balance(account_id)` → available cash
  - `refresh_after_trade(account_id)` → invalidate position/balance cache
- Rate limiting: exponential backoff on 429s

### Step 11: Register in TradeExecutionService
- Register `SchwabBrokerAdapter` in `services/trade_execution_service.py` (gated by `SCHWAB_ENABLED`) — this is the ONLY place adapters are registered
- Status normalization handled by adapter outputs + `TradeExecutionService.to_common_status()` — no `mcp_server.py` changes needed for trading (source literal changes already covered in Step 9c)
- Verify `preview_trade` / `execute_trade` MCP tools route to Schwab automatically when account hash matches via `owns_account()`

## Files to create
| File | Purpose | Lines (est) |
|------|---------|-------------|
| `schwab_client.py` | OAuth client wrapper + account hash mapping | ~100 |
| `run_schwab.py` | CLI tool (login, accounts, positions, orders, txns, status) | ~180 |
| `providers/schwab_positions.py` | Position provider | ~80 |
| `providers/schwab_transactions.py` | Transaction provider + incremental sync | ~120 |
| `providers/normalizers/schwab.py` | Transaction normalizer | ~200 |
| `services/schwab_broker_adapter.py` | Trading adapter (all BrokerAdapter methods) | ~350 |
| `tests/services/test_schwab_broker_adapter.py` | Adapter unit tests | ~200 |
| `tests/providers/test_schwab_normalizer.py` | Normalizer unit tests | ~150 |

## Files to modify
| File | Change |
|------|--------|
| `requirements.txt` | Add `schwab-py` pinned version |
| `settings.py` | Add SCHWAB_* config, update TRANSACTION_ROUTING + INSTITUTION_SLUG_ALIASES |
| `trading_analysis/data_fetcher.py` | Add `schwab_transactions` to payload, register provider, add `"schwab"` to valid sources |
| `trading_analysis/analyzer.py` | Add `schwab_transactions` param + `_raw_data_for()` branch, register normalizer in default list |
| `run_trading_analysis.py` | Add `schwab` to `--source` choices, transaction count, `TradingAnalyzer(...)` call |
| `mcp_tools/trading_analysis.py` | Add `schwab` to source `Literal`, transaction count, `TradingAnalyzer(...)` call |
| `mcp_tools/performance.py` | Add `schwab` to source `Literal` + docstring (no analyzer instantiation) |
| `mcp_tools/tax_harvest.py` | Add `schwab` to source `Literal` + `valid_source` set, pass `schwab_transactions` to analyzer |
| `mcp_server.py` | Add `schwab` to source enums in 3 tool registrations |
| `run_positions.py` | Add `schwab` provider/source display, cache metadata |
| `mcp_tools/positions.py` | Add Schwab provider support, `refresh_provider` handling |
| `providers/normalizers/__init__.py` | Export SchwabNormalizer |
| `services/position_service.py` | Register SchwabPositionProvider |
| `services/trade_execution_service.py` | Register SchwabBrokerAdapter |
| `core/realized_performance_analysis.py` | Pass `schwab_transactions` to analyzer, add `"schwab"` to source allowlist (line 1752) |
| `tests/unit/test_mcp_server_contracts.py` | Update source enum assertions to include `"schwab"` |
| `tests/trading_analysis/test_provider_routing.py` | Update valid source + payload shape assertions |
| `tests/providers/test_transaction_providers.py` | Update payload key assertions |
| `.env` | Add Schwab credentials |

## Prerequisites (user action)
1. Register app at developer.schwab.com
2. Set callback URL to `https://127.0.0.1:8182`
3. Get App Key + Secret, add to `.env`
4. Run `python3 run_schwab.py login` to complete OAuth and generate token file

## Verification
1. `python3 run_schwab.py status` — token health check
2. `python3 run_schwab.py accounts` — lists Schwab accounts
3. `python3 run_schwab.py positions` — shows holdings
4. `python3 run_schwab.py transactions` — shows recent activity
5. `python3 -m pytest tests/services/test_schwab_broker_adapter.py tests/providers/test_schwab_normalizer.py -v`
6. `python3 run_trading_analysis.py --source schwab` — trading analysis from Schwab data
7. MCP: `get_trading_analysis(source='all')` — includes Schwab transactions
8. MCP: `preview_trade` / `execute_trade` with Schwab account

# Position Module Implementation Plan

> **Status:** ✅ COMPLETE
>
> | Phase | Status | Description |
> |-------|--------|-------------|
> | Phase 1: Core Position Service | ✅ Complete | CLI, PositionService, consolidation |
> | Phase 2: Transaction Fetching | ✅ Complete | `trading_analysis/data_fetcher.py` with live Plaid + SnapTrade |
> | Phase 3: Historical Reconstruction | ⏭️ Skipped | Redundant — `build_position_timeline()` in realized performance pipeline already reconstructs positions from transactions |
> | Phase 4: Database Integration | ✅ Complete | Cache, schema enhancement |
> | Phase 5: Trade Aggregation & P&L | ✅ Complete | `run_trading_analysis.py` CLI with live data |
> | MCP Implementation | ✅ Complete | `portfolio-mcp` with `get_positions()` |

## Overview

Build a dedicated positions module that provides a unified view of holdings across brokerage providers (Plaid, SnapTrade), with a CLI-first development approach. This module serves as the foundation for the broader [Trade Tracking Plan](./TRADE_TRACKING_PLAN.md).

### Goals

1. **Unified Portfolio View** - Consolidate positions from multiple providers into one view
2. **CLI-First Development** - Rapid iteration via command line before API integration
3. **No Code Duplication** - Reuse existing loader functions, add orchestration layer
4. **Dev Mode** - Focus on API data first, database persistence optional/later
5. **Foundation for Trade Tracking** - Sets up architecture for transactions and history

### Priority Aims

**Aim 1: Consolidated Position View (Current State)**
- Unified view of all positions across Plaid + SnapTrade
- Output compatible with existing risk services (`PortfolioData` format)
- Can be passed directly to `run_risk.py`, portfolio analysis, optimization, etc.
- Enables: returns calculation, risk decomposition, factor analysis on real holdings

**Aim 2: Historical Position View (Over Time)**
- Track how portfolio looked at specific points in time
- Foundation for performance tracking and decision analysis
- Example: "What did my portfolio look like on Jan 1? How has it changed?"
- Ties into trade tracking plan for P&L and decision review
- **Approach:** Reconstruct positions from transaction history (not snapshots)
  - Plaid: `/investments/transactions/get` (up to 24 months)
  - SnapTrade: `get_activities()` (full history)

```
Aim 1: Current State          Aim 2: Historical View (via Transactions)
┌─────────────────┐           ┌─────────────────────────────────┐
│ Plaid + Snap    │           │  Transaction History            │
│      ↓          │           │  [buy] [sell] [buy] [div] ...   │
│  Consolidated   │    ───►   │           ↓                     │
│      ↓          │           │  Replay to reconstruct          │
│ Risk Services   │           │  positions at any date          │
└─────────────────┘           └─────────────────────────────────┘
```

---

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Data Model** | Reuse `PortfolioData` | Consistent with existing system; extend if needed for position-specific fields. During dev, use DataFrames for flexibility. |
| **Service Placement** | `services/position_service.py` | Matches existing architecture (`portfolio_service.py` pattern) |
| **Account Fidelity** | Keep both raw + consolidated | Fetch with account-level detail, offer consolidated view as option |
| **Transaction Dedup** | TBD (Phase 2) | SnapTrade IDs can change; likely need hash of `(provider + account + date + ticker + qty + price)` or use `external_reference_id` |
| **Cross-Provider Consolidation** | Group by (ticker, currency) | Multi-currency positions stay as separate rows. Matches SnapTrade's consolidation behavior. |
| **DB Persistence** | Routes layer, not services | `PositionService` is read-only. DB saves handled by `routes/plaid.py` and `routes/snaptrade.py` which save unconsolidated per-provider. Consolidation happens at analysis time via `PortfolioManager._consolidate_positions()`. |
| **Error Handling** | Fail-fast (no partial results) | Provider errors raise immediately. Ensures data integrity over availability. |

> **Note on PortfolioData:** During dev, we'll work with DataFrames for flexibility. When persisting to DB, convert to `PortfolioData` to leverage existing `PortfolioManager`/`DatabaseClient` infrastructure. If position-specific fields are needed (e.g., `by_account` breakdown), extend `PortfolioData` or add metadata.

---

## Architecture

### Layered Design

```
┌─────────────────────────────────────────────────────────────────────┐
│                          CLI Layer                                  │
│  run_positions.py                                                   │
│  - Command-line interface for all position operations               │
│  - Follows run_risk.py patterns (dual-mode: CLI + return_data)      │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       Service Layer                                 │
│  services/                                                          │
│  ├── position_service.py      # Core position operations            │
│  ├── transaction_service.py   # Transaction fetching (Phase 2)      │
│  └── portfolio_service.py     # (existing)                          │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
                              │ IMPORTS & CALLS (no duplication)
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       Data Access Layer                             │
│  plaid_loader.py           │  snaptrade_loader.py                   │
│  ├─ load_all_user_holdings │  ├─ load_all_user_snaptrade_holdings   │
│  ├─ normalize_*_holdings   │  ├─ normalize_*_holdings               │
│  └─ consolidate_holdings   │  └─ consolidate_*_holdings             │
│                            │                                        │
│  (Future additions)        │  (Future additions)                    │
│  ├─ fetch_transactions     │  ├─ fetch_activities                   │
│  └─ normalize_transactions │  └─ normalize_activities               │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       External APIs                                 │
│  Plaid API                      │  SnapTrade API                    │
│  /investments/holdings/get      │  get_user_account_positions       │
│  /investments/transactions/get  │  get_user_account_balance         │
│  /accounts/balance/get          │  get_activities                   │
└─────────────────────────────────────────────────────────────────────┘
```

### File Structure

```
services/
├── position_service.py       # NEW: Core position operations
├── transaction_service.py    # NEW (Phase 2): Transaction fetching
├── portfolio_service.py      # (existing)
└── ...

run_positions.py              # NEW: CLI entry point
```

---

## Separation of Concerns

### What Goes Where

| Component | Location | Responsibility |
|-----------|----------|----------------|
| **Raw API calls** | `plaid_loader.py`, `snaptrade_loader.py` | Talk to APIs, handle auth, pagination |
| **Normalization** | `plaid_loader.py`, `snaptrade_loader.py` | Convert provider format → standard DataFrame |
| **Per-provider consolidation** | `plaid_loader.py`, `snaptrade_loader.py` | Group by ticker within one provider (optional) |
| **Cross-provider consolidation** | `services/position_service.py` | Merge same tickers from different providers |
| **Business logic** | `services/position_service.py` | Orchestrate fetching, consolidation, display |
| **CLI interface** | `run_positions.py` | Parse args, call services, format output |

### Code Reuse Pattern

```python
# services/position_service.py

import pandas as pd
from plaid_loader import (
    load_all_user_holdings,    # Returns normalized (NOT consolidated) - keeps account detail
    consolidate_holdings       # Consolidates by ticker (loses account detail)
)
from snaptrade_loader import (
    fetch_snaptrade_holdings,        # Raw fetch → List[Dict]
    normalize_snaptrade_holdings,    # List[Dict] → DataFrame (keeps account detail)
    consolidate_snaptrade_holdings,  # Consolidates by ticker (loses account detail)
)

# Default AWS region for secrets manager
DEFAULT_REGION = "us-east-1"

class PositionService:
    """Orchestrates position operations using existing loaders."""

    def __init__(self, user_email: str, plaid_client=None, snaptrade_client=None,
                 region: str = DEFAULT_REGION):
        self.user_email = user_email
        self.plaid_client = plaid_client      # From get_plaid_client()
        self.snaptrade_client = snaptrade_client  # From SnapTrade(...)
        self.region = region

    def fetch_plaid_positions(self, consolidate: bool = False) -> pd.DataFrame:
        """Fetch from Plaid using existing loader.

        Note: load_all_user_holdings() returns normalized but NOT consolidated,
        so we already have account-level detail.
        """
        df = load_all_user_holdings(self.user_email, self.region, self.plaid_client)
        df = self._normalize_columns(df, source='plaid')

        if consolidate:
            return consolidate_holdings(df)
        return df  # Keep account-level detail

    def fetch_snaptrade_positions(self, consolidate: bool = False) -> pd.DataFrame:
        """Fetch from SnapTrade using existing loader.

        Note: load_all_user_snaptrade_holdings() consolidates internally,
        so for account-level detail we call fetch + normalize directly.
        """
        if consolidate:
            # Use the all-in-one function (already consolidates)
            from snaptrade_loader import load_all_user_snaptrade_holdings
            df = load_all_user_snaptrade_holdings(self.user_email, self.region, self.snaptrade_client)
        else:
            # Call fetch + normalize separately to keep account detail
            raw = fetch_snaptrade_holdings(self.user_email, self.snaptrade_client)
            df = normalize_snaptrade_holdings(raw)

        return self._normalize_columns(df, source='snaptrade')

    def _normalize_columns(self, df: pd.DataFrame, source: str) -> pd.DataFrame:
        """Standardize column names and ensure required columns exist.

        Plaid columns:    ticker, name, quantity, price, value, cost_basis, type, currency, account_id
        SnapTrade columns: ticker, name, quantity, price, value, security_type, currency, account_id

        Normalizations:
        - Add 'position_source' column
        - Rename 'security_type' → 'type' for SnapTrade
        - Ensure optional columns exist (cost_basis, value) to prevent downstream errors

        Note: 'type' remains provider-native (e.g., Plaid's 'equity', 'etf').
        For canonical type mapping, see utils/security_type_mappings.py.
        """
        df = df.copy()
        df['position_source'] = source

        # SnapTrade uses 'security_type' instead of 'type'
        if 'security_type' in df.columns and 'type' not in df.columns:
            df = df.rename(columns={'security_type': 'type'})

        # Ensure optional columns exist to prevent KeyError in downstream code
        for col in ['cost_basis', 'value', 'price']:
            if col not in df.columns:
                df[col] = None

        return df

    def get_all_positions(self, consolidate: bool = False) -> pd.DataFrame:
        """Get positions from all providers."""
        plaid_df = self.fetch_plaid_positions(consolidate=False)
        snaptrade_df = self.fetch_snaptrade_positions(consolidate=False)
        combined = pd.concat([plaid_df, snaptrade_df], ignore_index=True)

        if consolidate:
            return self._consolidate_cross_provider(combined)
        return combined

    def _consolidate_cross_provider(self, df: pd.DataFrame) -> pd.DataFrame:
        """Merge same tickers across providers, summing quantities."""
        # Group by ticker, sum quantities/values, track sources
        ...

    # === Aim 1: Integration with Risk Services ===

    def to_portfolio_data(self, df: pd.DataFrame = None,
                          start_date: str = None,
                          end_date: str = None) -> 'PortfolioData':
        """Convert positions DataFrame to PortfolioData for risk services.

        This enables passing consolidated positions directly to:
        - run_risk.py (portfolio analysis)
        - Portfolio optimization
        - Factor analysis
        - Any existing risk service that accepts PortfolioData

        Note: Cash positions (type='cash' or ticker starting with 'CUR:') are
        stored as {'dollars': value} to match PortfolioData expectations.
        Securities are stored as {'shares': quantity}.
        """
        from core.data_objects import PortfolioData
        from settings import PORTFOLIO_DEFAULTS

        if df is None:
            df = self.get_all_positions(consolidate=True)

        # Convert to holdings dict
        # Cash: {'dollars': value}, Securities: {'shares': quantity}
        holdings = {}
        for _, row in df.iterrows():
            ticker = row['ticker']
            pos_type = row.get('type', '')
            qty = row.get('total_quantity', row.get('quantity', 0))
            value = row.get('value', 0)

            # Cash positions use dollars, securities use shares
            if pos_type == 'cash' or ticker.startswith('CUR:'):
                holdings[ticker] = {'dollars': value or qty}
            else:
                holdings[ticker] = {'shares': qty}

        return PortfolioData.from_holdings(
            holdings=holdings,
            start_date=start_date or PORTFOLIO_DEFAULTS['start_date'],
            end_date=end_date or PORTFOLIO_DEFAULTS['end_date'],
            portfolio_name="CURRENT_PORTFOLIO"
        )

    # === Aim 2: Historical Positions (via Transaction Replay) ===
    # These methods will be implemented after transaction fetching is built

    def get_positions_as_of(self, date: str) -> pd.DataFrame:
        """Reconstruct positions as of a specific date from transaction history.

        Requires: Transaction fetching (Phase 2) to be implemented first.
        """
        raise NotImplementedError("Requires transaction fetching - see Phase 2")
```

> **Key Loader Behaviors:**
> - `load_all_user_holdings()` → Normalized but NOT consolidated (account detail preserved)
> - `load_all_user_snaptrade_holdings()` → Normalized AND consolidated (account detail lost)
> - For SnapTrade account-level detail, use `fetch_snaptrade_holdings()` + `normalize_snaptrade_holdings()` directly

---

## Data Models

### Development Mode: DataFrames

During development, we work with pandas DataFrames for flexibility:

```python
# Raw columns from Plaid loader (load_all_user_holdings)
plaid_df.columns = [
    'ticker',           # str: Security symbol
    'name',             # str: Security name
    'quantity',         # float: Number of shares
    'price',            # float: Price per share
    'value',            # float: Market value
    'cost_basis',       # float: Cost basis (may be NaN)
    'type',             # str: 'equity', 'etf', 'fund', 'cash', 'derivative'
    'currency',         # str: 'USD', 'EUR', etc.
    'account_id',       # str: Plaid account ID
]

# Raw columns from SnapTrade loader (normalize_snaptrade_holdings)
snaptrade_df.columns = [
    'ticker',           # str: Security symbol
    'name',             # str: Security name
    'quantity',         # float: Number of shares
    'price',            # float: Price per share
    'value',            # float: Market value (renamed from market_value)
    'security_type',    # str: 'equity', 'etf', 'cash', etc. (NOTE: not 'type')
    'currency',         # str: 'USD', etc.
    'account_id',       # str: SnapTrade account ID
    # Also includes: snaptrade_type_code, snaptrade_type_description
]

# After PositionService._normalize_columns() - unified schema
position_df.columns = [
    'ticker',           # str: Security symbol
    'name',             # str: Security name
    'quantity',         # float: Number of shares
    'price',            # float: Price per share
    'value',            # float: Market value
    'cost_basis',       # float: Cost basis (may be NaN)
    'type',             # str: Normalized from 'type' or 'security_type'
    'currency',         # str: Currency code
    'account_id',       # str: Brokerage account ID
    'position_source',  # str: 'plaid' or 'snaptrade' (ADDED by service)
]
```

### Persistence Mode: PortfolioData

When writing to database, convert to `PortfolioData` (from `core/data_objects.py`):

```python
from core.data_objects import PortfolioData

# Convert DataFrame to PortfolioData format
portfolio_data = PortfolioData.from_holdings(
    holdings=df_to_holdings_dict(position_df),
    start_date=start_date,
    end_date=end_date,
    portfolio_name="CURRENT_PORTFOLIO"
)

# Save via existing infrastructure
portfolio_manager.save_portfolio_data(portfolio_data)
```

### Consolidated View (Aggregated)

```python
# Consolidated DataFrame columns
consolidated_df.columns = [
    'ticker',           # str: Security symbol
    'total_quantity',   # float: Sum across all accounts/providers
    'currency',         # str: Primary currency
    'type',             # str: Asset type
    'total_value',      # float: Sum of market values (optional)
    'total_cost_basis', # float: Sum of cost basis (optional)
    'sources',          # str: Comma-separated providers ('plaid,snaptrade')
    'source_breakdown', # str: JSON {'plaid': 100, 'snaptrade': 50}
    'account_breakdown',# str: JSON {'acct_123': 75, 'acct_456': 75}
]
```

### Transaction (Phase 2 - DataFrame)

```python
# Transaction DataFrame columns (for future transaction fetching)
transaction_df.columns = [
    'ticker',                   # str: Security symbol
    'transaction_type',         # str: 'buy', 'sell', 'dividend', 'transfer'
    'quantity',                 # float: Number of shares
    'price',                    # float: Price per share
    'amount',                   # float: Total value
    'currency',                 # str: Currency code
    'transaction_date',         # date: Transaction date
    'settlement_date',          # date: Settlement date (optional)
    'fees',                     # float: Transaction fees
    'account_id',               # str: Brokerage account ID
    'position_source',          # str: 'plaid' or 'snaptrade'
    'provider_transaction_id',  # str: For deduplication
]
```

> **Note on Transaction Dedup (TBD):** SnapTrade activity IDs can change on re-fetch. For robust deduplication, consider using a hash of `(provider + account + date + ticker + qty + price)` or `external_reference_id` if available.

---

## CLI Interface

### Commands

```bash
# Phase 1: All commands fetch fresh from brokerage APIs (no DB in Phase 1)
# Default behavior: fetch from APIs and display

# Fetch and view all positions from both providers
python run_positions.py

# View positions from specific provider only
python run_positions.py --source plaid
python run_positions.py --source snaptrade

# Show consolidated view (merge same tickers across providers)
python run_positions.py --consolidated

# Output to JSON for inspection/debugging
python run_positions.py --output positions.json

# Show detailed position breakdown (by account)
python run_positions.py --detail

# Convert to PortfolioData and run through risk analysis (Aim 1)
python run_positions.py --to-risk

# Phase 2+: Transaction history
python run_positions.py --transactions --start 2024-01-01 --end 2024-12-31

# Phase 3+: Historical position reconstruction
python run_positions.py --as-of 2024-01-01

# Phase 4+: Database integration
python run_positions.py --from-db             # Load from database instead of API
python run_positions.py --save-db             # Fetch from API and save to DB
```

### Example Output

```
$ python run_positions.py --consolidated

╔══════════════════════════════════════════════════════════════════════╗
║                    CONSOLIDATED PORTFOLIO VIEW                        ║
║                    User: henry@example.com                            ║
║                    As of: 2024-01-29 12:30:00                        ║
╠══════════════════════════════════════════════════════════════════════╣

📊 EQUITIES (18 positions)
────────────────────────────────────────────────────────────────────────
Ticker     Quantity    Mkt Value    Cost Basis    Sources
────────────────────────────────────────────────────────────────────────
NVDA          25.00    $3,125.00     $2,883.97    plaid
MSCI          33.55   $18,234.00           n/a    plaid, snaptrade
STWD       1,050.20   $10,502.00           n/a    plaid, snaptrade
ENB          227.00    $9,080.00           n/a    snaptrade
...

📈 ETFs (2 positions)
────────────────────────────────────────────────────────────────────────
SLV          100.00    $2,800.00     $3,178.71    plaid
SPY            6.00    $2,880.00           n/a    snaptrade

💵 CASH
────────────────────────────────────────────────────────────────────────
CUR:USD   -30,766.29   (Margin)                   plaid, snaptrade

════════════════════════════════════════════════════════════════════════
SUMMARY
────────────────────────────────────────────────────────────────────────
Total Positions:     30 (20 unique after consolidation)
Total Market Value:  $XXX,XXX.XX
Margin/Cash:         -$30,766.29
Net Exposure:        $XXX,XXX.XX
════════════════════════════════════════════════════════════════════════
```

---

## Implementation Phases

### Phase 1: Core Position Service (Aim 1 - Current Focus) ✅ COMPLETE

**Goal:** Unified view of current positions, compatible with risk services

- [x] Create `services/position_service.py` with `PositionService` class
- [x] Implement methods: `fetch_plaid_positions()`, `fetch_snaptrade_positions()`, `get_all_positions()`
- [x] Implement `_normalize_columns()` to standardize across providers
- [x] Implement cross-provider consolidation logic (group by ticker AND currency)
- [x] Implement `to_portfolio_data()` for risk service integration
- [x] Create `run_positions.py` CLI with `--source`, `--consolidated`, `--output`, `--detail`, `--to-risk` flags
- [x] Add to `tests/TESTING_COMMANDS.md`

**Implementation Notes (completed Jan 2025):**
- Consolidation groups by (ticker, currency) to preserve multi-currency positions as separate rows
- `to_portfolio_data()` is for direct-to-risk analysis only (NOT for DB persistence)
- DB stores unconsolidated positions; `PortfolioManager._consolidate_positions()` consolidates at analysis time
- Fail-fast principle: provider errors raise immediately (no partial results)
- Added `account_name` from Plaid for human-readable display
- Cash fallback: uses `quantity` when `value` is missing (since price=1.0 for cash)
- Added defensive comments for potential null currency edge case

**Dev Approach:**
- Work with in-memory DataFrames (reuse loader output)
- Optional JSON dump for inspection (`--output`)
- No database writes required initially

### Phase 2: Transaction Fetching (Aim 2 Foundation) ✅ COMPLETE

**Goal:** Fetch transaction history from brokerage APIs

**Implemented in `trading_analysis/data_fetcher.py`:**
- [x] `fetch_snaptrade_activities()` - Full pagination, account-level endpoint
- [x] `fetch_plaid_transactions()` - Full pagination, returns transactions + securities
- [x] `fetch_all_transactions()` - Combines both providers

**CLI Entry Point:** `run_trading_analysis.py`
- [x] `--source all|snaptrade|plaid` - Filter by provider
- [x] `--output` - Write JSON results
- [x] `--summary` - Summary only mode
- [x] `--incomplete` - Show incomplete trades

**API Endpoints Used:**
- Plaid: `/investments/transactions/get` (up to 24 months)
- SnapTrade: `get_account_activities()` per account (full history)

**Note:** Transaction dedup handled by FIFO matcher's transaction ID tracking.

### Phase 3: Historical Position Reconstruction (Aim 2)

**Goal:** Reconstruct positions at any historical date from transactions

- [ ] Implement `get_positions_as_of(date)` in `PositionService`
- [ ] Replay transaction history to compute holdings at target date
- [ ] Add `--as-of YYYY-MM-DD` flag to CLI
- [ ] Enable historical performance comparison

**Approach:** Given transactions, replay chronologically up to target date:
```
Start: empty portfolio
For each transaction before target_date:
    if buy:  positions[ticker] += quantity
    if sell: positions[ticker] -= quantity
Return: positions as of target_date
```

### Phase 4: Database Integration ✅ COMPLETE

**Goal:** Persist positions to database

**Completed (via Position Service Refactor):**
- [x] PositionService now handles DB caching (24-hour cache)
- [x] Routes delegate to PositionService (single source of truth)
- [x] Schema enhanced with `name`, `brokerage_name`, `account_name` columns
- [x] `use_cache` and `force_refresh` parameters wired through

**Note:** Transaction DB persistence (tables, stored replay) is tracked in [TRADE_TRACKING_PLAN.md](./TRADE_TRACKING_PLAN.md) Phase 1/3, not here.

### Phase 5: Trade Aggregation & P&L (FIFO) ✅ COMPLETE

**Goal:** Calculate realized P&L using FIFO lot matching

**Implemented in `trading_analysis/` module:**
- [x] FIFO lot matching engine (`fifo_matcher.py`)
- [x] Proper fee tracking (entry/exit fees, partial close handling)
- [x] Option handling (detection, unique symbols, expiration at $0)
- [x] Incomplete trade tracking for backfill
- [x] Win Score and metrics calculation (`metrics.py`)
- [x] Data normalization for Plaid + SnapTrade (`analyzer.py`)
- [x] Live data integration via `data_fetcher.py`
- [x] CLI entry point: `run_trading_analysis.py`

**CLI Usage:**
```bash
python run_trading_analysis.py --user-email user@example.com
python run_trading_analysis.py --user-email user@example.com --source snaptrade --output results.json
```

**Still TODO (optional enhancements):**
- [ ] Short selling support (long positions fully working)
- [ ] Add trading summary to `run_positions.py` (currently separate CLI)

---

## Integration with Existing System

### Relationship to Existing Code

| Existing Component | How Position Service Relates |
|--------------------|------------------------------|
| `plaid_loader.py` | **Reuses** for API calls and normalization |
| `snaptrade_loader.py` | **Reuses** for API calls and normalization |
| `services/portfolio_service.py` | **Pattern followed** for service layer design |
| `routes/plaid.py` | **Delegates to** PositionService (thin HTTP wrapper) |
| `routes/snaptrade.py` | **Delegates to** PositionService (thin HTTP wrapper) |
| `PortfolioManager` | **Used by** PositionService for DB persistence |
| `DatabaseClient` | **Used by** PositionService for cache checks |
| `core/data_objects.py` | `PortfolioData`, `PositionsData` classes for data transport |
| `core/result_objects.py` | `PositionResult` for CLI/MCP/API responses |
| `run_risk.py` | **Pattern followed** for CLI dual-mode design |
| `mcp_server.py` | **Exposes** PositionService via `portfolio-mcp` MCP server |

### Future API Integration

Once the CLI is working, we can add FastAPI routes:

```python
# routes/positions.py (future)

from services.position_service import PositionService

@router.get("/api/positions")
async def get_positions(request: Request, consolidate: bool = True):
    user = get_current_user(request)
    service = PositionService(user['email'])
    df = service.get_all_positions(consolidate=consolidate)
    return df.to_dict('records')

@router.get("/api/positions/portfolio-data")
async def get_positions_as_portfolio_data(request: Request):
    """Get positions in PortfolioData format for risk analysis."""
    user = get_current_user(request)
    service = PositionService(user['email'])
    portfolio_data = service.to_portfolio_data()
    return portfolio_data.portfolio_input  # Returns holdings dict format
```

---

## Testing

### CLI Testing Commands

```bash
# Add to tests/TESTING_COMMANDS.md

## Position Module Testing

# View all positions (fetches fresh from APIs)
python run_positions.py

# View consolidated positions (merge same tickers)
python run_positions.py --consolidated

# View from Plaid only
python run_positions.py --source plaid

# View from SnapTrade only
python run_positions.py --source snaptrade

# Output to JSON for inspection
python run_positions.py --output /tmp/positions.json

# View with detailed breakdown (by account)
python run_positions.py --detail

# Convert to PortfolioData and pass to risk analysis
python run_positions.py --to-risk
```

### Unit Tests

```bash
# Future: pytest tests
pytest tests/services/test_position_service.py
```

---

## Known Limitations

1. ~~**No API Caching**~~ ✅ **RESOLVED**
   - PositionService now includes 24-hour DB caching with `use_cache` and `force_refresh` parameters
   - See: [Position Service Refactor Plan](./POSITION_SERVICE_REFACTOR_PLAN.md) (completed)

2. **No Cash Mapping for `--to-risk`** - The `to_portfolio_data()` method includes cash as `CUR:USD` directly, but risk analysis requires cash to be mapped to proxy tickers (e.g., `SGOV`). Currently `--to-risk` fails with price fetch errors for cash positions.
   - **Future:** Add `_apply_cash_mapping()` logic or delegate to `PortfolioManager`

3. ~~**Read-Only Service**~~ ✅ **RESOLVED**
   - PositionService now handles both reading AND saving to the database
   - Routes delegate to PositionService (single source of truth)
   - Consolidation for risk analysis happens at read time

4. ~~**Return Data Not JSON-Serializable**~~ ✅ **RESOLVED**
   - `PositionResult` class now provides `to_api_response()`, `to_cli_report()`, `to_summary()` methods
   - MCP tool uses structured dict responses
   - CLI `--format json` outputs proper JSON

---

## Open Questions

1. ~~**Consolidation Strategy** - How to handle same ticker with different currencies?~~
   > **Resolved:** Group by (ticker, currency) - keeps multi-currency positions as separate rows. Mixed currencies are NOT merged; they stay distinct for accuracy.

2. **Price Source** - Use stored price from loader or fetch fresh for market value calculation?
   > Still TBD for Phase 2+

3. ~~**Error Handling** - What if one provider fails? Show partial data with warning?~~
   > **Resolved:** Fail-fast principle. Provider errors raise immediately; no partial results. This ensures data integrity.

> **Resolved:** Account-level fidelity - Keep both raw (with account detail) and consolidated views available via `--consolidated` flag.

---

## Related Documents

- **Provider API References**
  - Plaid Investments API (holdings + transactions): https://plaid.com/docs/api/products/investments/
  - SnapTrade List Account Positions: https://docs.snaptrade.com/reference/Account%20Information/AccountInformation_getUserAccountPositions
  - SnapTrade List Account Activities: https://docs.snaptrade.com/reference/Account%20Information/AccountInformation_getAccountActivities

- [Position Module MCP Spec](./completed/POSITION_MODULE_MCP_SPEC.md) - **MCP/CLI implementation (✅ complete)**
- [MCP Extensions Plan](./MCP_EXTENSIONS_PLAN.md) - Future MCP enhancements
- [Position Service Refactor Plan](./POSITION_SERVICE_REFACTOR_PLAN.md) - **Cache & DB integration (✅ complete)**
- [Modular CLI Architecture](./MODULAR_CLI_ARCHITECTURE_PLAN.md) - Overall modular CLI pattern
- [Modular Architecture Refactor](./MODULAR_ARCHITECTURE_REFACTOR_PLAN.md) - **Conceptual architecture (✅ complete)**
- [Trading Analysis Enhancement Plan](./TRADING_ANALYSIS_ENHANCEMENT_PLAN.md) - Position monitor, performance stats, return distribution
- [Trade Tracking Plan](./TRADE_TRACKING_PLAN.md) - Full transaction and P&L tracking
- [Testing Commands](../../tests/TESTING_COMMANDS.md) - CLI testing reference
- [Backend Architecture](../architecture/legacy/backend_architecture.md) - Overall system design

**Implementation Files:**
- `run_positions.py` - Position fetching CLI
- `run_trading_analysis.py` - Trading P&L analysis CLI
- `trading_analysis/data_fetcher.py` - Live transaction fetching
- `trading_analysis/fifo_matcher.py` - FIFO lot matching engine
- `services/position_service.py` - Position service with caching

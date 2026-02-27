# Trade Tracking Feature - Implementation Plan 

## Overview

Implement a position/trade tracking system that provides users with a complete view of their trading history, including entry/exit prices, P&L, and win/loss metrics.

### Customer Requirements

| Field | Description |
|-------|-------------|
| Trade | Unique trade identifier |
| Ticker | Stock symbol |
| Company Name | Full company name |
| Long / Short | Position direction |
| Shares # | Number of shares traded |
| Weighted Entry Price | Volume-weighted average entry price |
| Weighted Exit Price | Volume-weighted average exit price |
| Entry Date | First entry transaction date |
| Exit Date | Last exit transaction date |
| Days in Trade | Calendar days between entry and exit |
| Profit / Loss % | Percentage return |
| Profit / Loss $ | Dollar return (after fees) |
| Win Score | 1 (profitable) or -1 (loss) |

---

## API Reference

### SnapTrade
- **Transaction History API**: https://docs.snaptrade.com/reference/Transactions%20And%20Reporting/TransactionsAndReporting_getActivities
- **Account Data Overview**: https://docs.snaptrade.com/docs/account-data
- **Getting Started**: https://docs.snaptrade.com/demo/getting-started

### Plaid
- **Investments API**: https://plaid.com/docs/api/products/investments/
- **Investment Transactions**: https://plaid.com/docs/api/products/investments/#investmentstransactionsget
- **Transactions API** (for reference): https://plaid.com/docs/api/products/transactions/

---

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Lot Matching | FIFO | Standard for tax purposes, intuitive |
| Multi-Account | Per-account trades | Cleaner tracking, matches brokerage reporting |
| Short Selling | Full support | Customer requirement |
| Historical Backfill | Yes | Enables testing, complete history |

---

## Data Model

### 1. `investment_transactions` - Raw Transaction Storage

Stores every buy/sell transaction from Plaid and SnapTrade.

```sql
CREATE TABLE investment_transactions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    portfolio_id INTEGER REFERENCES portfolios(id),
    account_id VARCHAR(100),

    -- Provider tracking (for deduplication)
    provider VARCHAR(20) NOT NULL,              -- 'plaid', 'snaptrade', 'manual'
    provider_transaction_id VARCHAR(255),       -- External ID from provider

    -- Security
    ticker VARCHAR(100) NOT NULL,
    security_id VARCHAR(255),                   -- Provider's security ID

    -- Transaction details
    transaction_type VARCHAR(20) NOT NULL,      -- 'buy', 'sell', 'short', 'cover'
    transaction_subtype VARCHAR(50),            -- e.g., 'dividend reinvestment'
    transaction_date DATE NOT NULL,
    settlement_date DATE,

    -- Quantities and prices
    quantity DECIMAL(20,8) NOT NULL,            -- Always positive
    price DECIMAL(20,8) NOT NULL,
    amount DECIMAL(20,8),                       -- quantity * price
    fees DECIMAL(20,8) DEFAULT 0,

    -- Currency
    currency VARCHAR(10) DEFAULT 'USD',
    fx_rate DECIMAL(20,8),

    -- Metadata
    description TEXT,
    raw_data JSONB,                             -- Full provider response

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(provider, provider_transaction_id)
);
```

**Transaction Type Mapping:**

| Provider Value | Internal Type | Direction |
|----------------|---------------|-----------|
| Plaid: type=buy | 'buy' | Long entry |
| Plaid: type=sell | 'sell' | Long exit |
| Plaid: subtype=sell short | 'short' | Short entry |
| Plaid: subtype=buy to cover | 'cover' | Short exit |
| SnapTrade: BUY | 'buy' | Long entry |
| SnapTrade: SELL | 'sell' | Long exit |

### 2. `open_trade_lots` - FIFO Lot Tracking

Tracks open positions that haven't been fully closed.

```sql
CREATE TABLE open_trade_lots (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    portfolio_id INTEGER REFERENCES portfolios(id),
    account_id VARCHAR(100),

    ticker VARCHAR(100) NOT NULL,
    trade_direction VARCHAR(10) NOT NULL,       -- 'long' or 'short'

    -- Lot details
    original_quantity DECIMAL(20,8) NOT NULL,
    remaining_quantity DECIMAL(20,8) NOT NULL,
    entry_price DECIMAL(20,8) NOT NULL,
    entry_date DATE NOT NULL,
    entry_fees DECIMAL(20,8) DEFAULT 0,

    -- Link to source transaction
    entry_transaction_id INTEGER REFERENCES investment_transactions(id),

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### 3. `completed_trades` - Closed Trade Records

Created when a position is fully exited. Contains all customer-requested fields.

```sql
CREATE TABLE completed_trades (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    portfolio_id INTEGER REFERENCES portfolios(id),
    account_id VARCHAR(100),

    -- Security
    ticker VARCHAR(100) NOT NULL,
    company_name VARCHAR(255),

    -- Direction
    trade_direction VARCHAR(10) NOT NULL,       -- 'long' or 'short'

    -- Entry (aggregated)
    entry_quantity DECIMAL(20,8) NOT NULL,
    weighted_entry_price DECIMAL(20,8) NOT NULL,
    entry_date DATE NOT NULL,
    entry_fees DECIMAL(20,8) DEFAULT 0,

    -- Exit (aggregated)
    exit_quantity DECIMAL(20,8) NOT NULL,
    weighted_exit_price DECIMAL(20,8) NOT NULL,
    exit_date DATE NOT NULL,
    exit_fees DECIMAL(20,8) DEFAULT 0,

    -- Calculated (stored as generated columns)
    days_in_trade INTEGER,                      -- exit_date - entry_date
    profit_loss_dollars DECIMAL(20,8),          -- (exit - entry) * qty - fees
    profit_loss_percent DECIMAL(10,4),          -- ((exit - entry) / entry) * 100
    win_score INTEGER,                          -- 1 or -1

    -- Currency
    currency VARCHAR(10) DEFAULT 'USD',

    -- Source transaction links
    entry_transaction_ids INTEGER[],
    exit_transaction_ids INTEGER[],

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### 4. `trade_tracker` - View for Customer Dashboard

```sql
CREATE VIEW trade_tracker AS
SELECT
    id AS trade_id,
    ticker,
    company_name,
    CASE WHEN trade_direction = 'long' THEN 'Long' ELSE 'Short' END AS long_short,
    entry_quantity AS shares,
    weighted_entry_price,
    weighted_exit_price,
    entry_date,
    exit_date,
    days_in_trade,
    profit_loss_percent,
    profit_loss_dollars,
    win_score,
    user_id,
    portfolio_id,
    account_id
FROM completed_trades
ORDER BY exit_date DESC;
```

---

## Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    Data Ingestion Layer                          │
├─────────────────────────────────────────────────────────────────┤
│  Plaid API                         SnapTrade API                 │
│  /investments/transactions/get     get_activities()              │
│  - Up to 24 months history         - Full history (cached daily) │
│  - buy, sell, cancel, fee, etc.    - BUY, SELL, DIVIDEND, etc.   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              investment_transactions (Raw Storage)               │
│  - Deduplicated by (provider, provider_transaction_id)          │
│  - Normalized transaction_type: buy, sell, short, cover         │
│  - Stores raw_data JSONB for debugging                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Trade Aggregation Engine                        │
│  1. Process transactions in chronological order                  │
│  2. For buy/short: Create new lot in open_trade_lots            │
│  3. For sell/cover: Match against oldest lots (FIFO)            │
│  4. When lot fully closed: Calculate weighted prices             │
│  5. Create completed_trade record                                │
└─────────────────────────────────────────────────────────────────┘
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
┌───────────────────────────┐  ┌───────────────────────────┐
│    open_trade_lots        │  │    completed_trades       │
│  (Partially open)         │  │  (Fully closed)           │
│  - remaining_quantity > 0 │  │  - P&L calculated         │
│  - For unrealized P&L     │  │  - Win score assigned     │
└───────────────────────────┘  └───────────────────────────┘
                                          │
                                          ▼
                              ┌───────────────────────────┐
                              │    trade_tracker VIEW     │
                              │  (Customer dashboard)     │
                              └───────────────────────────┘
```

---

## FIFO Matching Algorithm

### Example: Long Trade with Partial Exits

```
Day 1: BUY  100 AAPL @ $150  → Lot A: 100 shares @ $150
Day 5: BUY   50 AAPL @ $155  → Lot B:  50 shares @ $155
Day 10: SELL 75 AAPL @ $160  → Close 75 from Lot A (FIFO)
                               Lot A: 25 remaining
Day 15: SELL 75 AAPL @ $165  → Close 25 from Lot A + 50 from Lot B
                               Both lots closed → completed_trade created
```

**Resulting Completed Trade:**
- Entry Quantity: 150 shares
- Weighted Entry: (100×150 + 50×155) / 150 = $151.67
- Weighted Exit: (75×160 + 75×165) / 150 = $162.50
- P&L $: (162.50 - 151.67) × 150 = $1,624.50
- P&L %: 7.14%
- Win Score: 1

### Example: Short Trade

```
Day 1: SHORT 100 TSLA @ $250  → Lot A: 100 shares @ $250 (short)
Day 10: COVER 100 TSLA @ $230 → Close Lot A
```

**Resulting Completed Trade:**
- Direction: Short
- Weighted Entry: $250 (short sale price)
- Weighted Exit: $230 (cover price)
- P&L $: (250 - 230) × 100 = $2,000 (profit because price dropped)
- Win Score: 1

---

## Implementation Tasks

### Phase 1: Database Schema
- [ ] Add `investment_transactions` table
- [ ] Add `open_trade_lots` table
- [ ] Add `completed_trades` table
- [ ] Add `trade_tracker` view
- [ ] Add indexes for performance
- [ ] Create migration script

### Phase 2: Transaction Ingestion ✅ COMPLETE

**Reference Script:** `scripts/explore_transactions.py` - working code that fetches from both APIs

- [x] SnapTrade: `client.transactions_and_reporting.get_activities()` - WORKING
  - Uses `snaptrade_loader.py` helpers (get_snaptrade_client, get_snaptrade_user_id_from_email, get_snaptrade_user_secret)
  - Full history available (brokerage dependent)
- [x] Plaid: `client.investments_transactions_get()` - WORKING
  - Uses `plaid_loader.py` helpers (client, list_user_tokens, get_plaid_token)
  - Max 24 months history, paginated (500 per request)
  - Also fetches securities for symbol lookup
- [x] IBKR Flex Query: `services/ibkr_flex_client.py` - WORKING
  - Downloads up to 365 days of historical trades via `ib_async.FlexReport`
  - SSL fix: auto-sets `SSL_CERT_FILE` from `certifi` (macOS)
  - Option symbol construction, trade type mapping (BUY+O→BUY, SELL+O→SHORT, etc.)
  - `option_expired` detection for zero-price option closings

**Integration with TradingAnalyzer ✅**
- [x] `run_trading_analysis.py` CLI fetches live data and passes to TradingAnalyzer
- [x] `trading_analysis/data_fetcher.py` wraps provider APIs with full pagination
- [x] Handle pagination for large histories (Plaid: offset-based, SnapTrade: per-account)
- [x] IBKR Flex trades fetched via `fetch_ibkr_flex_trades()` in `data_fetcher.py`
- [x] Cross-source dedup: cardinality-aware (Counter-based) dedup of Plaid IBKR vs Flex trades in `analyzer.py`
- [ ] DB-level deduplication (skip existing provider_transaction_id) — deferred to DB persistence phase

### Phase 3: Output & Persistence

**Decision needed:** How to handle analysis results?
- Option A: Store in database (full persistence, queryable)
- Option B: Compute on-demand (simpler, always fresh)
- Option C: Cache with TTL (balance of both)

**If persisting (Option A):**
- [ ] `save_investment_transactions(user_id, transactions)` - Bulk insert with dedup
- [ ] `get_investment_transactions(user_id, ticker=None, start_date=None, end_date=None)`
- [ ] `save_completed_trade(user_id, trade_data)`
- [ ] `get_completed_trades(user_id, ticker=None, start_date=None, end_date=None)`
- [ ] `save_open_lots(user_id, lots)`
- [ ] `get_trade_tracker(user_id)` - Returns aggregated view

**Backfill management:**
- [x] Auto-export incomplete trades to JSON with account info
- [x] Load backfill data and merge with results
- [x] Backfill functions exist in `fifo_matcher.py` (load_and_merge_backfill, etc.)

### Phase 4: Trade Aggregation Engine ✅ COMPLETE

**Implemented in `trading_analysis/`:**
- [x] FIFO lot matching algorithm (`fifo_matcher.py`)
- [x] Partial lot closures with proper fee tracking
- [x] Option handling (detection, expiration, unique symbols)
- [x] Incomplete trade tracking for backfill
- [x] Win Score and metrics calculation
- [x] Short selling support — `(symbol, currency, direction)` keying, SHORT inference, COVER matching
- [x] Dividend/income tracking — `IncomeTransaction` model, `TransactionType.DIVIDEND`, `total_dividends`
- [x] IBKR Flex normalization — trade type mapping, `option_expired` allowing price=0 for BUY/COVER
- [x] Shared strike normalization — `normalize_strike()` in `trading_analysis/symbol_utils.py`

**Still TODO:**
- [ ] Stock splits (adjust quantities/prices for corporate actions)
- [ ] Transfers between accounts (currently tracked as `TransactionType.TRANSFER` but not processed)

### Phase 5: Historical Backfill

**Partially implemented:**
- [x] Incomplete trades exported with account/brokerage info (`incomplete_trades_for_backfill.json`)
- [x] Backfill loading functions in `fifo_matcher.py`
- [x] Merge backfilled trades with FIFO results

**Still TODO:**
- [ ] Workflow for user to fill in missing entry prices
- [ ] Auto-detect when incomplete trades can be resolved with new data
- [ ] Handle corporate actions that affect historical lots

### Phase 6: API Endpoints (Future)
- [ ] `GET /api/trades` - List completed trades
- [ ] `GET /api/trades/{id}` - Trade details
- [ ] `GET /api/trades/open` - Open positions with unrealized P&L
- [ ] `GET /api/trades/stats` - Win rate, avg P&L, etc.

---

## Provider API Details

### Plaid `/investments/transactions/get`

```python
from plaid.model.investments_transactions_get_request import InvestmentsTransactionsGetRequest

request = InvestmentsTransactionsGetRequest(
    access_token=access_token,
    start_date=date(2022, 1, 1),
    end_date=date.today(),
    options=InvestmentsTransactionsGetRequestOptions(
        count=500,  # Max per request
        offset=0
    )
)
response = client.investments_transactions_get(request)
# response.investment_transactions - list of InvestmentTransaction
# response.total_investment_transactions - for pagination
```

**InvestmentTransaction fields:**
- `investment_transaction_id` - Unique ID
- `account_id` - Account
- `security_id` - Links to securities list
- `date` - Transaction date
- `name` - Description
- `quantity` - Shares (positive=buy, negative=sell)
- `price` - Price per share
- `amount` - Total value
- `fees` - Transaction fees
- `type` - buy, sell, cancel, cash, fee, transfer
- `subtype` - buy, sell, sell short, buy to cover, dividend, etc.
- `iso_currency_code` - Currency

### SnapTrade `get_activities()`

```python
response = client.transactions_and_reporting.get_activities(
    user_id=user_id,
    user_secret=user_secret,
    start_date="2022-01-01",
    end_date="2024-12-31"
)
# Returns list of UniversalActivity objects
```

**UniversalActivity fields:**
- `id` - Transaction ID (can change on re-fetch)
- `account` - Account info
- `symbol` - Security info with ticker
- `trade_date` - Transaction date
- `settlement_date` - Settlement date
- `type` - BUY, SELL, DIVIDEND, CONTRIBUTION, etc.
- `units` - Number of shares
- `price` - Price per share
- `amount` - Total value
- `fee` - Transaction fee
- `fx_rate` - FX rate if cross-currency
- `currency` - Currency info
- `external_reference_id` - For grouping related transactions

---

## Testing Strategy

1. **Unit Tests**
   - FIFO matching logic
   - Weighted price calculations
   - Short trade P&L calculations
   - Edge cases (splits, partial lots)

2. **Integration Tests**
   - Transaction ingestion from mock Plaid/SnapTrade responses
   - End-to-end: transactions → lots → completed trades

3. **Manual Testing**
   - Connect real account with historical data
   - Verify trades match brokerage statements

---

## Phase 7: Performance Dashboard & Analytics

Once the core trade tracking is implemented, build consolidated reporting views.

### 7.1 Realized Performance Summary

High-level metrics aggregated across all completed trades:

| Metric | Description | Calculation |
|--------|-------------|-------------|
| Win # | Count of profitable trades | COUNT WHERE profit_loss_dollars > 0 |
| Win $ | Total dollars won | SUM(profit_loss_dollars) WHERE > 0 |
| Win % | Win rate | win_count / total_count × 100 |
| R | Risk/reward ratio | avg_win / abs(avg_loss) |
| Loss # | Count of losing trades | COUNT WHERE profit_loss_dollars < 0 |
| Loss $ | Total dollars lost | SUM(profit_loss_dollars) WHERE < 0 |
| Loss % | Loss rate | loss_count / total_count × 100 |
| Total # | Total completed trades | COUNT(*) |
| Total $ | Net P&L | SUM(profit_loss_dollars) |

```sql
CREATE VIEW realized_performance_summary AS
SELECT
    user_id,
    COUNT(*) FILTER (WHERE profit_loss_dollars > 0) AS win_count,
    COUNT(*) FILTER (WHERE profit_loss_dollars < 0) AS loss_count,
    COUNT(*) AS total_count,
    SUM(profit_loss_dollars) FILTER (WHERE profit_loss_dollars > 0) AS win_dollars,
    SUM(profit_loss_dollars) FILTER (WHERE profit_loss_dollars < 0) AS loss_dollars,
    SUM(profit_loss_dollars) AS total_dollars,
    ROUND(100.0 * COUNT(*) FILTER (WHERE profit_loss_dollars > 0) / NULLIF(COUNT(*), 0), 2) AS win_rate,
    ROUND(100.0 * COUNT(*) FILTER (WHERE profit_loss_dollars < 0) / NULLIF(COUNT(*), 0), 2) AS loss_rate,
    ROUND(
        AVG(profit_loss_dollars) FILTER (WHERE profit_loss_dollars > 0) /
        NULLIF(ABS(AVG(profit_loss_dollars) FILTER (WHERE profit_loss_dollars < 0)), 0),
        2
    ) AS risk_reward_ratio
FROM completed_trades
GROUP BY user_id;
```

### 7.2 Returns Distribution Analysis

Histogram of trade returns with frequency and cumulative distribution:

| Returns Bucket | Range | Count | Frequency % | Cumulative % |
|----------------|-------|-------|-------------|--------------|
| -40.00% | x < -40% | ... | ... | ... |
| -35.00% | -40% <= x < -35% | ... | ... | ... |
| ... | ... | ... | ... | ... |
| 70.00% | x > 70% | ... | ... | ... |

```sql
CREATE VIEW returns_distribution AS
WITH buckets AS (
    SELECT
        user_id,
        profit_loss_percent,
        CASE
            WHEN profit_loss_percent < -40 THEN '-40%'
            WHEN profit_loss_percent < -35 THEN '-35%'
            WHEN profit_loss_percent < -30 THEN '-30%'
            WHEN profit_loss_percent < -25 THEN '-25%'
            WHEN profit_loss_percent < -20 THEN '-20%'
            WHEN profit_loss_percent < -15 THEN '-15%'
            WHEN profit_loss_percent < -10 THEN '-10%'
            WHEN profit_loss_percent < -5 THEN '-5%'
            WHEN profit_loss_percent < 0 THEN '0%'
            WHEN profit_loss_percent < 5 THEN '5%'
            WHEN profit_loss_percent < 10 THEN '10%'
            WHEN profit_loss_percent < 15 THEN '15%'
            WHEN profit_loss_percent < 20 THEN '20%'
            WHEN profit_loss_percent < 25 THEN '25%'
            WHEN profit_loss_percent < 30 THEN '30%'
            WHEN profit_loss_percent < 35 THEN '35%'
            WHEN profit_loss_percent < 40 THEN '40%'
            WHEN profit_loss_percent < 45 THEN '45%'
            WHEN profit_loss_percent < 50 THEN '50%'
            WHEN profit_loss_percent < 55 THEN '55%'
            WHEN profit_loss_percent < 60 THEN '60%'
            WHEN profit_loss_percent < 65 THEN '65%'
            WHEN profit_loss_percent < 70 THEN '70%'
            ELSE '>70%'
        END AS bucket
    FROM completed_trades
),
counts AS (
    SELECT user_id, bucket, COUNT(*) AS count
    FROM buckets
    GROUP BY user_id, bucket
),
totals AS (
    SELECT user_id, SUM(count) AS total FROM counts GROUP BY user_id
)
SELECT
    c.user_id,
    c.bucket,
    c.count,
    ROUND(100.0 * c.count / t.total, 2) AS frequency_pct,
    ROUND(100.0 * SUM(c.count) OVER (PARTITION BY c.user_id ORDER BY c.bucket) / t.total, 2) AS cumulative_pct
FROM counts c
JOIN totals t ON c.user_id = t.user_id
ORDER BY c.user_id, c.bucket;
```

### 7.3 Returns Statistics

| Metric | Value |
|--------|-------|
| Average Return | AVG(profit_loss_percent) |
| Median Return | PERCENTILE_CONT(0.5) |
| Avg Positive Return | AVG WHERE > 0 |
| Avg Negative Return | AVG WHERE < 0 |

```sql
CREATE VIEW returns_statistics AS
SELECT
    user_id,
    ROUND(AVG(profit_loss_percent), 2) AS avg_return,
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY profit_loss_percent), 2) AS median_return,
    ROUND(AVG(profit_loss_percent) FILTER (WHERE profit_loss_percent > 0), 2) AS avg_positive,
    ROUND(AVG(profit_loss_percent) FILTER (WHERE profit_loss_percent < 0), 2) AS avg_negative
FROM completed_trades
GROUP BY user_id;
```

### Implementation Tasks for Phase 7

- [ ] Create `realized_performance_summary` view
- [ ] Create `returns_distribution` view
- [ ] Create `returns_statistics` view
- [ ] Add DatabaseClient methods:
  - `get_realized_performance(user_id)`
  - `get_returns_distribution(user_id)`
  - `get_returns_statistics(user_id)`
- [ ] Add API endpoints:
  - `GET /api/trades/performance` - Summary metrics
  - `GET /api/trades/distribution` - Returns histogram
  - `GET /api/trades/statistics` - Avg/median stats

---

## Open Questions / Future Enhancements

1. ~~**Wash Sale Tracking**~~ ✅ Implemented in `mcp_tools/tax_harvest.py` (`_check_wash_sale_risk()` scans BUY txns within 30 days)
2. **Tax Lot Selection** - Allow LIFO, specific lot identification
3. ~~**Multi-Currency P&L**~~ ✅ Implemented via FX pipeline (entry-date FX in tax harvest, spot FX in positions, currency_map throughout)
4. **Corporate Actions** - Stock splits, mergers, spin-offs
5. ~~**Options Trading**~~ ✅ Partial — expiration handled, IBKR Flex option symbols, price scaling. Exercise/assignment still TODO.
6. **Consolidated Cross-Account View** - Aggregate same-ticker trades across accounts

---

## TODO: Options Handling Improvements

### Completed ✓

1. **Price Scale** ✓ - Now using `amount / units` for correct P&L on options
2. **Unique Option Symbols** ✓ - Creating symbols like "NNDM_C2_230406" (ticker_type_strike_expiry)
3. **Option Expiration** ✓ - `OPTIONEXPIRATION` treated as SELL at $0 with `option_expired` flag
4. **Incomplete Option Trades** ✓ - Tracked for backfill like stock trades
5. **IBKR Flex Option Symbols** ✓ - Structured symbol construction `{UNDERLYING}_{C|P}{strike}_{YYMMDD}` from Flex XML fields
6. **Option Price Multiplier** ✓ - `tradePrice * multiplier` for per-contract cost (IBKR Flex)
7. **Zero-Price Expiration** ✓ - FIFO matcher allows `price == 0` on BUY/COVER when `option_expired=True`
8. **Cross-Source Strike Normalization** ✓ - `normalize_strike()` in `symbol_utils.py` ensures Plaid/IBKR consistency

### Still TODO

1. **Use Proper Option Metadata from APIs** - Currently using string matching on description ("CALL"/"PUT") as a stopgap. Should use structured option data:

   **Plaid:**
   - `security.type == 'derivative'` indicates option
   - Security object has option metadata: `option_contract` with `contract_type`, `expiration_date`, `strike_price`, `underlying_security_id`
   - See: https://plaid.com/docs/api/products/investments/#investment_transactions-get-response-securities-option-contract

   **SnapTrade:**
   - Separate options endpoint with structured data
   - Symbol object may have `type` field indicating derivative
   - Need to investigate SnapTrade options API for proper metadata

2. **Exercise & Assignment** - Handle option exercise (converting to stock position) and assignment scenarios

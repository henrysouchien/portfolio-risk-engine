# Trading Analysis Live Integration Plan

> **Status:** ✅ COMPLETE (Tasks 1-3), ⏳ Task 4 deferred
> **Goal:** Connect `trading_analysis/` module to live API data and optionally persist results
> **Completed:** 2026-02-02

## Current State

### What's Built ✅

| Component | Location | Description |
|-----------|----------|-------------|
| FIFO Lot Matcher | `trading_analysis/fifo_matcher.py` | Lot matching with fee tracking |
| Data Normalization | `trading_analysis/analyzer.py` | Plaid + SnapTrade normalization |
| Metrics & Scoring | `trading_analysis/metrics.py` | Win Score, timing, behavioral |
| Transaction Fetching | `scripts/explore_transactions.py` | Working script for both APIs |
| Sample Data | `scripts/transaction_samples/` | JSON files for testing |

### Current Flow (File-Based)

```
Plaid API ─────┐
               ├──► explore_transactions.py ──► JSON files ──► TradingAnalyzer
SnapTrade API ─┘
```

### Target Flow (Live)

```
Plaid API ─────┐
               ├──► run_trading_analysis.py ──► TradingAnalyzer ──► Results
SnapTrade API ─┘                                      │
                                                      ▼
                                              (Optional) Database
```

---

## Implementation Tasks

### Task 1: Modify TradingAnalyzer to Accept Raw Data

**File:** `trading_analysis/analyzer.py`

**Changes:**
- Add raw data parameters to `__init__`:
  - `plaid_securities: Optional[List[Dict]]`
  - `plaid_transactions: Optional[List[Dict]]`
  - `snaptrade_activities: Optional[List[Dict]]`
- Raw data takes precedence over file paths if both provided
- Add `_load_*_raw()` methods that accept lists instead of file paths

**Example Usage After:**
```python
# From files (existing - still works)
analyzer = TradingAnalyzer(
    plaid_securities_path='securities.json',
    plaid_transactions_path='transactions.json',
    snaptrade_activities_path='activities.json'
)

# From raw data (new)
analyzer = TradingAnalyzer(
    plaid_securities=securities_list,
    plaid_transactions=transactions_list,
    snaptrade_activities=activities_list
)
```

---

### Task 2: Create Live Data Fetching Functions

**File:** `trading_analysis/data_fetcher.py` (NEW)

**Purpose:** Reusable functions to fetch transaction data from APIs

**Functions:**
```python
def fetch_snaptrade_activities(user_email: str, days_back: int = 1825) -> List[Dict]:
    """Fetch SnapTrade activities for a user.

    Uses existing snaptrade_loader helpers.
    Returns list of activity dicts ready for TradingAnalyzer.
    """
    pass

def fetch_plaid_transactions(user_email: str, days_back: int = 730) -> Dict:
    """Fetch Plaid transactions and securities for a user.

    Uses existing plaid_loader helpers.
    Returns {'transactions': [...], 'securities': [...]}
    """
    pass

def fetch_all_transactions(user_email: str) -> Dict:
    """Fetch from all providers.

    Returns {
        'snaptrade_activities': [...],
        'plaid_transactions': [...],
        'plaid_securities': [...]
    }
    """
    pass
```

**Reuses from `scripts/explore_transactions.py`:**
- SnapTrade: `client.transactions_and_reporting.get_activities()`
- Plaid: `client.investments_transactions_get()`

---

### Task 3: Create CLI Entry Point

**File:** `run_trading_analysis.py` (NEW)

**Purpose:** CLI for running live trading analysis

**Commands:**
```bash
# Run full analysis (default)
python run_trading_analysis.py

# Summary only
python run_trading_analysis.py --summary

# Specific source
python run_trading_analysis.py --source snaptrade
python run_trading_analysis.py --source plaid

# Output to JSON
python run_trading_analysis.py --output results.json

# Show incomplete trades (for backfill)
python run_trading_analysis.py --incomplete

# Use cached data (if we implement persistence)
python run_trading_analysis.py --from-cache
```

**Output Example:**
```
════════════════════════════════════════════════════════════════
TRADING ANALYSIS RESULTS
User: henry@example.com
════════════════════════════════════════════════════════════════

📊 SUMMARY
  Transactions: 187 (117 SnapTrade + 70 Plaid)
  Closed Trades: 34 (33 stock + 1 option)
  Total P&L: $6,472.05
  Win Rate: 33.3%

📈 TOP WINNERS
  GLBE: +$472.29 (+21.5%)
  ...

💸 TOP LOSERS
  OPAD: -$123.11 (-65.5%)
  ...

⚠️  INCOMPLETE TRADES: 53 (need backfill)
  Run with --incomplete to see details
```

---

### Task 4: Optional Database Persistence

**Decision Point:** Do we want to persist transactions/results to DB?

**Option A: No Persistence (Simple)**
- Fetch fresh from APIs each time
- Pros: Always current, no DB schema changes
- Cons: Slower (API calls), rate limits

**Option B: Cache Transactions (Recommended)**
- Store raw transactions in DB
- Re-run FIFO analysis on cached data
- Pros: Fast, can analyze offline, audit trail
- Cons: Need to sync with APIs periodically

**Option C: Cache Results Too**
- Store both transactions AND analysis results
- Pros: Fastest reads
- Cons: Results can get stale, complex invalidation

**If Option B (Cache Transactions):**

Tables needed (from TRADE_TRACKING_PLAN.md):
```sql
-- Raw transactions from APIs
CREATE TABLE investment_transactions (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    provider VARCHAR(20) NOT NULL,  -- 'plaid', 'snaptrade'
    provider_transaction_id VARCHAR(255),  -- May be unstable for SnapTrade
    external_reference_id VARCHAR(255),    -- SnapTrade's grouping ref (not for dedup)
    dedup_key VARCHAR(64) NOT NULL,        -- Always SHA256 hash (64 hex chars)
    dedup_tiebreaker VARCHAR(50),          -- Full ISO timestamp for SnapTrade; NULL for Plaid
    content_hash VARCHAR(64),              -- Hash of mutable fields (qty, price, fee, amount)
    account_id VARCHAR(255),
    ticker VARCHAR(100),                   -- Normalized symbol (e.g., 'AAPL_C150_240315')
    ticker_raw VARCHAR(100),               -- Raw provider symbol for hash recomputation
    transaction_type VARCHAR(20),  -- 'buy', 'sell', 'dividend', etc.
    transaction_date TIMESTAMP,    -- UTC
    date_local VARCHAR(10),        -- Always YYYY-MM-DD (date only, no time) for both providers
    timezone_assumed VARCHAR(50),  -- 'UTC' or 'America/New_York'
    quantity DECIMAL(20,8),
    price DECIMAL(20,8),
    amount DECIMAL(20,8),
    fees DECIMAL(20,8),
    currency VARCHAR(10),
    raw_data JSONB,  -- Full provider response
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, dedup_key)  -- Identity-based uniqueness; content_hash changes trigger updates
);

-- Index for fast lookups
CREATE INDEX idx_investment_transactions_user_date
    ON investment_transactions(user_id, transaction_date);
CREATE INDEX idx_investment_transactions_ticker
    ON investment_transactions(user_id, ticker);
```

**CLI Flags for Persistence:**
```bash
# Save fetched transactions to DB
python run_trading_analysis.py --save

# Use cached transactions (skip API fetch)
python run_trading_analysis.py --from-cache

# Force refresh (fetch new + update cache)
python run_trading_analysis.py --refresh
```

---

## File Structure After Implementation

```
risk_module/
├── trading_analysis/
│   ├── __init__.py
│   ├── analyzer.py          # Modified: accept raw data
│   ├── data_fetcher.py      # NEW: API fetching functions
│   ├── fifo_matcher.py      # Unchanged
│   ├── metrics.py           # Unchanged
│   └── models.py            # Unchanged
├── run_trading_analysis.py  # NEW: CLI entry point
└── scripts/
    └── explore_transactions.py  # Keep as exploration tool
```

---

## Implementation Order

1. **Task 1:** ✅ Modify TradingAnalyzer (accept raw data) - COMPLETE
2. **Task 2:** ✅ Create data_fetcher.py (extract from explore_transactions.py) - COMPLETE
3. **Task 3:** ✅ Create run_trading_analysis.py CLI - COMPLETE
4. **Task 4:** ⏳ (Deferred) Add DB persistence if needed

---

## Data Contracts

### SnapTrade Activity Schema (Input)

Expected fields from `get_activities()` response:

```python
{
    'id': str,                    # Transaction ID (can change on re-fetch)
    'type': str,                  # 'BUY', 'SELL', 'DIVIDEND', 'OPTIONEXPIRATION', etc.
    'symbol': {                   # Can be dict or str
        'symbol': str,            # Ticker (e.g., 'AAPL')
        'description': str,       # Full name
        'type': dict,             # Security type info
        'currency': dict,         # Currency info
    },
    'trade_date': str,            # ISO format 'YYYY-MM-DDTHH:MM:SSZ' (UTC)
    'settlement_date': str,       # ISO format
    'units': float,               # Positive for buy, negative for sell
    'price': float,               # Per-share price (for options: per-share premium)
'amount': float,              # Total transaction value (includes multiplier for options; normalized to signed cashflow)
    'fee': float,                 # Transaction fees
    'currency': dict,             # Transaction currency
    'description': str,           # Human-readable (contains option details)
    'account': dict,              # Account info
    'external_reference_id': str, # For grouping related transactions
}
```

### Plaid Transaction Schema (Input)

Expected fields from `investments_transactions_get()` response:

```python
{
    'investment_transaction_id': str,  # Unique ID (stable)
    'account_id': str,
    'security_id': str,                # Links to securities list
    'date': str,                       # 'YYYY-MM-DD' (no time, local date)
    'type': str,                       # 'buy', 'sell', 'transfer', etc.
    'subtype': str,                    # 'buy', 'sell', 'sell short', etc.
    'quantity': float,                 # Positive for buy, negative for sell
    'price': float,                    # Per-share price
    'amount': float,                   # Total value
    'fees': float,                     # Transaction fees
    'iso_currency_code': str,          # 'USD', etc.
    'name': str,                       # Description
}
```

### Plaid Security Schema (Input)

```python
{
    'security_id': str,
    'ticker_symbol': str,              # May be None for some securities
    'name': str,
    'type': str,                       # 'equity', 'etf', 'derivative', etc.
    'iso_currency_code': str,
    'option_contract': {               # Only for options
        'contract_type': str,          # 'call', 'put'
        'expiration_date': str,
        'strike_price': float,
        'underlying_security_id': str,
    }
}
```

### Normalized Transaction Schema (Internal)

After normalization in TradingAnalyzer, all transactions become:

```python
{
    'symbol': str,              # Normalized symbol (e.g., 'AAPL' or 'AAPL_C150_240315')
    'ticker_raw': str,          # Raw provider symbol (for hash recomputation; Plaid fallback: security_id)
    'type': str,                # 'BUY' or 'SELL'
    'date': datetime,           # UTC datetime (see timezone handling below)
    'date_local': str,          # Always YYYY-MM-DD (date only, no time) for both providers
    'timezone_assumed': str,    # 'UTC' for SnapTrade, 'America/New_York' for Plaid
    'quantity': float,          # Always positive
    'price': float,             # Per-contract price for options (abs(amount/units)), per-share for stocks; always positive
    'fee': float,
'amount': float,            # Signed cashflow in account currency (BUY negative, SELL positive, DIVIDEND positive)
    'currency': str,            # 'USD', 'CAD', etc.
    'source': str,              # 'snaptrade' or 'plaid'
    'account_id': str,          # Provider's account ID (for drill-down/debugging)
    'transaction_id': str,      # Provider's transaction ID (may be unstable for SnapTrade)
    'external_reference_id': str,  # SnapTrade's grouping reference (not for dedup; None for Plaid)
    'dedup_key': str,           # Always SHA256 hash (64 chars) - see dedup strategy
    'dedup_tiebreaker': str,    # Full timestamp for SnapTrade hash; None for Plaid
    'content_hash': str,        # Content hash: hash(qty, price, fee, amount) - for detecting corrections
    'is_option': bool,
    'option_expired': bool,     # True for OPTIONEXPIRATION
}
```

**Normalization note (amount + fees):**
- `amount` is always normalized to **signed cashflow** for both providers (BUY negative, SELL positive, DIVIDEND positive)
- `fee` is stored separately and **not** folded into `amount` (P&L computations should add fees explicitly)

**Price field clarification:**
- **Stocks:** `price` = per-share price (same as provider)
- **Options:** `price` = per-contract value (calculated as `abs(amount / units)`)
  - SnapTrade provides per-share premium in `price` field, but `amount` has the full contract value
  - We use `abs(amount / units)` to get per-contract price for correct P&L
  - `abs()` required because sells have negative units but positive amount (or vice versa)
  - Sign (buy vs sell) is determined by transaction type, not price sign

---

## Behavioral Decisions

### Provider Failure Handling

**Decision:** Fail-fast (matches PositionService pattern)

- If SnapTrade fails: Raise error, do not return partial results
- If Plaid fails: Raise error, do not return partial results
- Rationale: Partial data leads to incorrect P&L calculations

**CLI behavior:**
```bash
# Default: fail-fast
python run_trading_analysis.py

# Future flag to allow partial (if needed)
python run_trading_analysis.py --allow-partial
```

### Transaction Ordering & Timezone Handling

**Rules:**
1. All dates converted to UTC datetime for sorting
2. SnapTrade: Parse ISO timestamp directly (already UTC)
3. Plaid: Date only (no time) - **institution-local date**
   - Store `date_local` for debugging
   - Store `timezone_assumed = 'America/New_York'`
   - Convert to UTC: `date + 00:00 America/New_York → UTC`
     - Standard time (EST): +5 hours → 05:00 UTC
     - Daylight time (EDT): +4 hours → 04:00 UTC
   - Use `pytz` or `zoneinfo` for DST-aware conversion
   - **Risk:** Off-by-one around midnight for international institutions
   - **Future:** Could use institution metadata to determine timezone
4. Same-timestamp transactions: Process buys before sells (prevents false "incomplete" sells)
5. FIFO sorts by date ascending before matching

**Implementation in `fifo_matcher.py`:**
```python
# Sort key: (date, type_priority) where BUY=0, SELL=1
sorted_txns = sorted(transactions, key=lambda x: (x['date'], 0 if x['type'] == 'BUY' else 1))
```

**Preserved for debugging:**
```python
# Plaid example:
{
    'date': datetime(2024, 1, 15, 5, 0, 0),  # UTC (converted from America/New_York)
    'date_local': '2024-01-15',              # Date only (from Plaid's date field)
    'timezone_assumed': 'America/New_York',
    'dedup_tiebreaker': None,                # Not needed (uses transaction_id as dedup_key)
}

# SnapTrade example:
{
    'date': datetime(2024, 1, 15, 14, 30, 0),  # UTC (from trade_date)
    'date_local': '2024-01-15',                # Date only (extracted from trade_date)
    'timezone_assumed': 'UTC',
    'dedup_tiebreaker': '2024-01-15T14:30:00Z',  # Full timestamp for hash computation
}
```

### Multi-Account Handling

**Decision:** Aggregate across accounts by default

- All accounts from same provider are merged
- `account_id` preserved in raw data for drill-down if needed
- Cross-account transfers: Not currently handled (TODO)

**Rationale:** Most users want total P&L, not per-account. FIFO across accounts matches tax reporting.

### Multi-Currency Handling

**Decision:** Keep separate, no conversion

- USD positions stay USD
- CAD positions stay CAD (common with SnapTrade)
- P&L calculated in original currency
- Summary shows totals per currency

**Future:** Add optional FX conversion with user-specified rates

### Deduplication Strategy

**For caching (Task 4):**

Two separate concerns:
1. **Upsert key (identity):** Which transaction is this?
2. **Content hash (change detection):** Has this transaction been corrected?

**Identity strategy (always hash):**
- `dedup_key` is always a SHA256 hash (64 hex chars) - never store raw IDs directly
- Raw IDs stored separately in `provider_transaction_id` and `external_reference_id`
- This avoids length issues (raw IDs can exceed 64 chars)

**Hash inputs by provider:**
- **Plaid:** Hash of `(provider, investment_transaction_id)` - transaction_id is stable and unique
- **SnapTrade:** Hash of `(provider, account_id, date_local, ticker_raw, type, tiebreaker)` - computed from fields

**Ticker field for hashing:**
- Use **raw provider symbol** (`ticker_raw`), NOT the normalized symbol
- SnapTrade: `symbol.symbol` from API response (e.g., "AAPL", "AAPL 240315C00150000")
- Plaid: `ticker_symbol` from securities lookup; if missing, fallback to `security_id` (stored in `ticker_raw`)
- Rationale: Normalization logic may change; raw symbol is stable
- Store `ticker_raw` alongside normalized `symbol` in DB for recomputation

**Hash canonicalization (stable serialization):**
All fields must be serialized consistently before hashing to avoid drift:

| Field | Canonicalization Rule |
|-------|----------------------|
| `provider` | Lowercase string: `"plaid"`, `"snaptrade"` |
| `account_id` | String as-is (case-sensitive); empty string if missing |
| `date_local` | `YYYY-MM-DD` format, no time |
| `ticker_raw` | Uppercase, trimmed; if missing, use `security_id` (Plaid) or empty string |
| `type` | Uppercase: `"BUY"`, `"SELL"` |
| `tiebreaker` | ISO string as-is, or empty string if None |
| `quantity` | Decimal with 8 places; if missing, use `"NA"` and log warning |
| `price` | Decimal with 8 places; if missing, use `"NA"` and log warning |
| `fee` | Decimal with 8 places; if missing, use `"NA"` and log warning |
| `amount` | Decimal with 8 places; if missing, use `"NA"` and log warning |
| `transaction_id` | String as-is (Plaid `investment_transaction_id`); empty string if missing |

**Hash computation example:**
```python
import hashlib

def compute_dedup_key_snaptrade(txn: dict) -> str:
    """Compute identity hash for SnapTrade transaction."""
    account_id = txn.get('account_id') or ""
    date_local = txn.get('date_local') or ""
    ticker_raw = (txn.get('ticker_raw') or "").upper().strip()
    txn_type = (txn.get('type') or "").upper()
    tiebreaker = txn.get('dedup_tiebreaker') or ""
    parts = [
        "snaptrade",
        account_id,
        date_local,  # YYYY-MM-DD
        ticker_raw,
        txn_type,
        tiebreaker,
    ]
    canonical = "|".join(parts)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()

def compute_dedup_key_plaid(txn: dict) -> str:
    """Compute identity hash for Plaid transaction."""
    txn_id = txn.get('transaction_id') or ""
    canonical = f"plaid|{txn_id}"
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()

def compute_content_hash(txn: dict) -> str:
    """Compute content hash for correction detection (uses normalized values)."""
    def _fmt_decimal(value: float | None) -> str:
        if value is None:
            return "NA"
        return f"{value:.8f}"
    parts = [
        _fmt_decimal(txn.get('quantity')),
        _fmt_decimal(txn.get('price')),
        _fmt_decimal(txn.get('fee')),
        _fmt_decimal(txn.get('amount')),
    ]
    canonical = "|".join(parts)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()
```

**Why not use external_reference_id for SnapTrade identity?**
- `external_reference_id` is for **grouping related transactions**, not uniqueness
- Multiple distinct transactions can share the same external_reference_id
- Always use computed hash for SnapTrade to avoid collapsing distinct transactions

**Computed hash fields (SnapTrade):**
- `quantity` excluded from identity (could be corrected by broker)
- `date_local` is always YYYY-MM-DD (date only, no time)
- `tiebreaker` provides uniqueness for same-day trades (see below)

**Tiebreaker field (prevents same-day collision):**
- Problem: User buys AAPL twice on same day → identical hash without tiebreaker
- SnapTrade: Full timestamp from `trade_date` (e.g., "2024-01-15T14:30:00.123Z")
- Plaid: Not needed (transaction_id already unique)
- Stored explicitly in `dedup_tiebreaker` column for debugging/recomputation

**Content hash (for detecting corrections):**
- Hash of `(quantity, price, fee, amount)` - mutable fields
- If content_hash differs on upsert, log a warning: "Transaction corrected"
- Update the record with new values

**Why separate keys:**
- Corrected transactions (broker fixes price/fee/qty) should update existing record
- Single dedup_key with mutable fields creates duplicates on corrections

**SnapTrade ID instability:**
- `transaction_id` can change between API calls
- `external_reference_id` is for grouping, not identity
- Always compute hash from immutable fields + tiebreaker

**Schema stores all:**
```python
{
    'transaction_id': str,        # Provider's ID (may change for SnapTrade)
    'external_reference_id': str, # SnapTrade's grouping reference (not for dedup)
    'dedup_key': str,             # Always SHA256 hash (64 chars)
    'dedup_tiebreaker': str,      # Full timestamp (SnapTrade) or None (Plaid)
    'content_hash': str,          # Hash of mutable fields (qty, price, fee, amount)
}
```

**On re-fetch:**
1. Compute dedup_key hash (Plaid: hash of tx_id; SnapTrade: hash of fields + tiebreaker)
2. Compute content_hash from mutable fields
3. Upsert by dedup_key
4. If content_hash changed, log warning and update record

---

## Options Handling

**Already implemented in `trading_analysis/analyzer.py`:**

1. **Detection:** String matching on description ("CALL"/"PUT")
   - TODO: Use Plaid's `security.type == 'derivative'` and `option_contract` field
   - TODO: Use SnapTrade's symbol type field

2. **Symbol generation:** `{underlying}_{C|P}{strike}_{expiry}`
   - Example: "AAPL_C150_240315" for AAPL $150 Call expiring Mar 15, 2024
   - Decimals use 'p': $2.50 → "2p50"

3. **Price handling:** Use `abs(amount / units)` for correct contract value (always positive)

4. **Expiration:** `OPTIONEXPIRATION` type → SELL at $0 with `option_expired=True`

5. **Not yet handled:**
   - Assignment/exercise (converts to stock position)
   - Contract size validation (assume 100)

---

## CLI Output Contract

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Provider API error |
| 2 | Invalid arguments |
| 3 | No data found |

### JSON Output Schema (--output)

```json
{
  "metadata": {
    "user_email": "string",
    "generated_at": "ISO timestamp",
    "sources": ["snaptrade", "plaid"],
    "date_range": {
      "start": "YYYY-MM-DD",
      "end": "YYYY-MM-DD"
    }
  },
  "summary": {
    "total_transactions": 187,
    "closed_trades": 34,
    "open_positions": 15,
    "incomplete_trades": 53,
    "total_pnl": {
      "USD": 6472.05,
      "CAD": -150.00
    },
    "win_rate": 0.333,
    "currencies": ["USD", "CAD"],
    "by_account": {
      "acct_123": {"trades": 20, "pnl": {"USD": 5000.00}},
      "acct_456": {"trades": 14, "pnl": {"USD": 1472.05, "CAD": -150.00}}
    }
  },
  "closed_trades": [
    {
      "symbol": "AAPL",
      "currency": "USD",
      "account_id": "acct_123",
      "entry_date": "YYYY-MM-DD",
      "exit_date": "YYYY-MM-DD",
      "quantity": 100,
      "entry_price": 150.00,
      "exit_price": 165.00,
      "pnl_amount": 1500.00,
      "pnl_percent": 10.0,
      "days_held": 45,
      "win_score": 35.5,
      "grade": "B"
    }
  ],
  "open_positions": [...],
  "incomplete_trades": [...]
}
```

---

## Testing Plan

### Unit Tests

**File:** `tests/trading_analysis/test_analyzer.py`

1. **Normalization tests:**
   - SnapTrade activity → normalized transaction
   - Plaid transaction → normalized transaction
   - Option detection and symbol generation

2. **FIFO matching tests:**
   - Simple buy/sell pair
   - Partial lot closes
   - Multiple lots (FIFO order)
   - Same-timestamp ordering

3. **Edge cases:**
   - Missing price (should skip or handle)
   - Zero quantity (should skip)
   - Option expiration at $0

4. **Options price consistency:**
   - Assert options use per-contract price (abs(amount/units)), not per-share premium
   - Test: NNDM call buy at $70.66/contract, not $0.70/share
   - Regression test to catch if someone accidentally uses `price` instead of `abs(amount/units)`

### Integration Tests (Mocked APIs)

**File:** `tests/trading_analysis/test_integration.py`

1. **Mock API responses:**
   - Sample SnapTrade activities JSON
   - Sample Plaid transactions JSON
   - Use existing `scripts/transaction_samples/` as fixtures

2. **End-to-end test:**
   ```python
   def test_full_analysis_with_mock_data():
       analyzer = TradingAnalyzer(
           snaptrade_activities=MOCK_SNAPTRADE_DATA,
           plaid_transactions=MOCK_PLAID_TRANSACTIONS,
           plaid_securities=MOCK_PLAID_SECURITIES
       )
       results = analyzer.analyze_trades()
       assert len(results) == EXPECTED_TRADE_COUNT
       assert sum(r.pnl_amount for r in results) == pytest.approx(EXPECTED_PNL)
   ```

### Golden File Test

**File:** `tests/trading_analysis/test_golden.py`

- Run analysis on `scripts/transaction_samples/` data
- Compare output to stored "golden" result
- Detects regressions in P&L calculations

```python
def test_golden_output():
    analyzer = TradingAnalyzer(
        plaid_securities_path='scripts/transaction_samples/plaid_securities.json',
        plaid_transactions_path='scripts/transaction_samples/plaid_transactions.json',
        snaptrade_activities_path='scripts/transaction_samples/snaptrade_activities.json'
    )
    results = analyzer.analyze_trades()

    # Compare to golden file
    with open('tests/trading_analysis/golden_results.json') as f:
        expected = json.load(f)

    assert len(results) == expected['trade_count']
    assert sum(r.pnl_amount for r in results) == pytest.approx(expected['total_pnl'])
```

---

## Open Questions

1. **Default date range?**
   - SnapTrade: Full history available, default 5 years?
   - Plaid: Max 24 months, default all?

2. **Rate limiting?**
   - Any concerns with frequent API calls?
   - May need caching (Option B) for heavy use

3. **Backfill workflow?**
   - Auto-export incomplete trades to JSON?
   - Or just display in CLI and let user handle?

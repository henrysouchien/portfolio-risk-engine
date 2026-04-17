# Plan: Transaction Store Phase 2 — Read Path Integration

## Context

Phase 1 is complete (commit `6f2ae001`, fix `a8f47dc1`). All 3 providers ingested successfully:
- Schwab: 348 raw → 101 normalized + 115 income + 140 flows
- IBKR: 259 raw → 77 normalized + 95 income + 87 flows
- Plaid: 127 raw → 58 normalized + 49 income + 64 flows

Phase 2 wires the analysis pipeline to **read from the store** instead of live-fetching from provider APIs. This makes realized performance runs deterministic (same data every time) and fast (no API calls). The feature flag `TRANSACTION_STORE_READ` controls the switch — existing live-fetch path is unchanged.

## Gap Found: Futures MTM Not Stored

**Problem**: `ibkr_flex_futures_mtm` rows are NOT stored during Phase 1 ingest. The ingest combines `ibkr_flex_trades` + `ibkr_flex_cash_rows` into raw_transactions but drops futures MTM rows. These are structured event dicts from the IBKR Flex query (mark-to-market settlement entries) used extensively in the realized performance cash replay pipeline (20+ references in `realized_performance_analysis.py`).

**Fix**: Add `ibkr_flex_futures_mtm` rows to raw_transactions during ingest (in `mcp_tools/transactions.py`), storing them with provider `ibkr_flex_mtm` to distinguish from trades/cash. Each row is stored as JSONB in `raw_data` — these are already-structured event dicts (with `date`, `symbol`, `amount`, `account_id`, etc.), not raw provider blobs. Add `load_futures_mtm()` method to TransactionStore to query them back.

## Call Sites

### 4 Production Read-Path Sites (In Scope)

All follow the same pattern: `fetch_transactions_for_source()` → `TradingAnalyzer()` → `fifo_transactions`:

| # | File:Line | Function | Needs |
|---|-----------|----------|-------|
| 1 | `core/realized_performance_analysis.py:3216` | `_analyze_realized_performance_single_scope()` | fifo_txns + futures_mtm + provider_flows + fetch_metadata + income |
| 2 | `core/realized_performance_analysis.py:5295` | `_prefetch_source_fifo_for_accounts()` | fifo_txns (account discovery) |
| 3 | `mcp_tools/trading_analysis.py:102` | `_load_fifo_data()` | fifo_txns only |
| 4 | `mcp_tools/tax_harvest.py:118` | `_load_fifo_data()` | fifo_txns only |

### Out-of-Scope Callers

| File | Type | Why Out of Scope |
|------|------|-----------------|
| `mcp_tools/transactions.py:29` | Ingest tool | Writes TO the store, not a read path |
| `run_trading_analysis.py:122` | CLI script | Standalone diagnostic, optional Phase 3 |
| `tests/diagnostics/diagnose_realized.py:65` | Diagnostic script | Test tooling, optional Phase 3 |

## FIFO Dict Reconstruction

`normalized_transactions` DB columns must be mapped back to the dict shape that `FIFOMatcher` and downstream code expects:

| DB Column | FIFO Dict Key | Notes |
|-----------|--------------|-------|
| `trade_type` | `type` | BUY/SELL/SHORT/COVER |
| `transaction_date` | `date` | ISO string |
| `provider` | `source` | plaid/schwab/ibkr_flex/snaptrade |
| `institution` | `_institution` | Underscore prefix (internal) |
| `account_id` | `account_id` | |
| `account_name` | `account_name` | |
| `symbol` | `symbol` | |
| `quantity` | `quantity` | float |
| `price` | `price` | float |
| `fee` | `fee` | float |
| `currency` | `currency` | |
| `transaction_id` | `transaction_id` | |
| `instrument_type` | `instrument_type` | |
| `contract_identity` | `contract_identity` | JSONB → dict |
| `is_option` | `is_option` | bool |
| `is_futures` | `is_futures` | bool |
| `option_expired` | `option_expired` | bool |

Note on `provider_account_ref`: Lines 4143 and 4264 do `txn.get("provider_account_ref")` on FIFO dicts, but this field is **never set** by any normalizer or TradingAnalyzer — it always returns `None` in the live path. The downstream code treats it as an optional fallback after `account_id` and `account_name`. The store path will behave identically (returning `None`). The field IS present and required on `provider_flow_events` (already in that DB table) and `fetch_metadata` dicts (in `ingestion_batches.fetch_metadata` JSONB). The flow event and fetch metadata reconstruction methods must include it.

## Analyzer Dependencies After Line 3290

The `analyzer` object (created at line 3276) is used AFTER the block we're replacing:

1. **Line 3403**: `income_with_currency = _income_with_currency(analyzer, fifo_transactions, current_positions)` — accesses `analyzer.income_events` (list of `NormalizedIncome` objects)
2. **Line 4867**: `income_analysis = analyzer.analyze_income()` — calls `TradingAnalyzer.analyze_income()` which aggregates income by month/symbol/type

**Solution**: When `TRANSACTION_STORE_READ` is on, load income events from `normalized_income` table and either:
- Create a lightweight `IncomeShim` that provides `.income_events` and `.analyze_income()` from stored data
- OR restructure: pass `income_events` list directly to `_income_with_currency()` (change signature from `analyzer` → `income_events`) and compute `analyze_income()` equivalent from stored data

**Recommended**: Create a simple shim class to minimize changes to downstream code:
```python
class StoreBackedIncomeProvider:
    """Provides income_events and analyze_income() from stored data."""
    def __init__(self, income_events: list[dict]):
        self.income_events = income_events

    def analyze_income(self) -> IncomeAnalysis:
        # Replicate TradingAnalyzer.analyze_income() logic from stored events
```

## Implementation Steps

### Step 1: Fix Futures MTM Ingest Gap

**File**: `mcp_tools/transactions.py`
- Add `ibkr_flex_futures_mtm` to `provider_rows` dict with key `ibkr_flex_mtm`
- Already-structured event dicts stored as JSONB in `raw_data`

### Step 2: Add Store Read Methods to TransactionStore

**File**: `inputs/transaction_store.py`

New methods:

```python
def load_fifo_transactions(self, user_id, provider=None, institution=None, account=None) -> list[dict]:
    """Query normalized_transactions, reconstruct FIFO dicts.
    SQL prefilter on user_id/provider/account_id for performance.
    Maps DB columns → FIFO dict keys per mapping table above."""

def load_income_events(self, user_id, provider=None, institution=None, account=None) -> list[dict]:
    """Query normalized_income, return dicts with keys matching NormalizedIncome fields.
    SQL prefilter on user_id/provider/account_id."""

def load_provider_flow_events(self, user_id, provider=None, institution=None, account=None) -> list[dict]:
    """Query provider_flow_events, reconstruct ProviderFlowEvent shape.
    Must include provider_account_ref in output.
    Map event_date → date/timestamp for downstream compatibility."""

def load_fetch_metadata(self, user_id, provider=None) -> list[dict]:
    """Get latest ingestion_batches per provider, reconstruct FetchMetadata shape.
    Must include provider_account_ref from fetch_metadata JSONB."""

def load_futures_mtm(self, user_id, institution=None, account=None) -> list[dict]:
    """Query raw_transactions WHERE provider='ibkr_flex_mtm', return raw_data JSONB dicts."""
```

**Key field mappings for flow events**:
| DB Column | Output Dict Key | Notes |
|-----------|----------------|-------|
| `event_date` | `date` AND `timestamp` | Downstream uses both |
| `provider_account_ref` | `provider_account_ref` | Used in flow authority logic |
| All others | Same name | Direct passthrough |

### Step 3: Add Feature Flag

**File**: `settings.py`
```python
TRANSACTION_STORE_READ = os.getenv("TRANSACTION_STORE_READ", "").strip().lower() in ("1", "true", "yes")
```

### Step 4: Extract User ID Resolution to Shared Location

**Problem**: `_resolve_user_id()` lives in `mcp_tools/risk.py`. The core module (`realized_performance_analysis.py`) cannot import from `mcp_tools/` (inverted dependency).

**Solution**: Extract to `utils/user_resolution.py`:
```python
def resolve_user_id(user_email: str) -> int:
    """Look up the database user ID for an email address."""
    from database import get_db_session
    with get_db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE email = %s", (user_email,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"User not found: {user_email}")
        return row["id"]
```

Update existing callers in `mcp_tools/risk.py`, `mcp_tools/allocation.py`, `mcp_tools/audit.py`, `mcp_tools/baskets.py`, `mcp_tools/positions.py`, `mcp_tools/transactions.py` to import from `utils/user_resolution.py` instead of duplicating.

### Step 5: Create Income Shim for Store Path

**File**: `inputs/transaction_store.py` (or `inputs/store_loader.py`)

```python
class StoreBackedIncomeProvider:
    """Drop-in replacement for TradingAnalyzer income interface."""
    def __init__(self, income_events: list[dict]):
        self.income_events = [NormalizedIncome(**e) for e in income_events]

    def analyze_income(self) -> IncomeAnalysis:
        # Same aggregation logic as TradingAnalyzer.analyze_income()
        # Group by month, symbol, type; compute totals
```

This is passed to `_income_with_currency(income_provider, ...)` and `income_provider.analyze_income()` at the two downstream usage points, avoiding any changes to downstream code.

### Step 6: Create Top-Level Store Loader

**File**: `inputs/transaction_store.py`

```python
def load_from_store(user_id, source=None, institution=None, account=None):
    """Load all data needed by analysis pipeline from transaction store.

    Returns dict:
    - fifo_transactions: list[dict] — FIFO-ready dicts
    - futures_mtm_events: list[dict] — IBKR futures MTM raw dicts
    - provider_flow_events: list[dict] — ProviderFlowEvent-shaped dicts
    - fetch_metadata: list[dict] — FetchMetadata-shaped dicts
    - income_provider: StoreBackedIncomeProvider — drop-in for analyzer
    """
```

### Step 7: Integrate at Call Sites

**Site 1**: `core/realized_performance_analysis.py:3216-3290`

```python
from settings import TRANSACTION_STORE_READ

if TRANSACTION_STORE_READ:
    from utils.user_resolution import resolve_user_id
    from inputs.transaction_store import load_from_store
    user_id = resolve_user_id(user_email)
    store_data = load_from_store(user_id, source, institution, account)
    fifo_transactions = store_data["fifo_transactions"]
    futures_mtm_events = store_data["futures_mtm_events"]
    provider_flow_events_raw = store_data["provider_flow_events"]
    fetch_metadata_rows = store_data["fetch_metadata"]
    analyzer = store_data["income_provider"]  # StoreBackedIncomeProvider
    # fetch_errors built from fetch_metadata_rows (same logic, lines 3237-3243)
    # schwab_security_lookup not needed (already normalized)
    # provider_first_mode, extract_provider_flow_events() skipped (flows from store)
else:
    # existing live-fetch path unchanged (lines 3216-3290)
    ...
```

Everything after line 3290 stays exactly the same — institution/account filtering (lines 3310-3337), backfill injection (lines 3298-3309), FIFO matching, NAV computation, TWR.

The two downstream `analyzer` usages are satisfied by `StoreBackedIncomeProvider`:
- Line 3403: `_income_with_currency(analyzer, ...)` → reads `analyzer.income_events`
- Line 4867: `analyzer.analyze_income()` → returns `IncomeAnalysis`

**Site 2**: `core/realized_performance_analysis.py:5295` (`_prefetch_source_fifo_for_accounts`)
- Same store-read pattern, only needs `fifo_transactions`

**Sites 3-4**: `mcp_tools/trading_analysis.py:102` and `mcp_tools/tax_harvest.py:118`
- Add store branch inside `_load_fifo_data()` — these already have `user_email` and call `_resolve_user_id()` in the MCP layer

### Step 8: SQL Prefilter + Python Post-Filter

For `load_fifo_transactions()` and other read methods:
- **SQL WHERE**: Filter by `user_id`, `provider` (from `source` param), `account_id` for performance
- **Python post-filter**: Keep institution alias matching via `match_institution()` after SQL results (aliases can't be resolved in SQL)
- This matches the current pattern where SQL does the heavy lifting and Python handles alias-aware correctness

## Key Files

| File | Change |
|------|--------|
| `inputs/transaction_store.py` | ADD read methods + StoreBackedIncomeProvider + load_from_store |
| `mcp_tools/transactions.py` | FIX ingest to include `ibkr_flex_futures_mtm` rows |
| `utils/user_resolution.py` | NEW — extract `resolve_user_id()` from mcp_tools/risk.py |
| `settings.py` | ADD `TRANSACTION_STORE_READ` flag |
| `core/realized_performance_analysis.py:3216-3290` | MODIFY — feature-flag branch for store read |
| `core/realized_performance_analysis.py:5295` | MODIFY — feature-flag branch for account prefetch |
| `mcp_tools/trading_analysis.py:102` | MODIFY — feature-flag branch in `_load_fifo_data()` |
| `mcp_tools/tax_harvest.py:118` | MODIFY — feature-flag branch in `_load_fifo_data()` |
| `mcp_tools/risk.py` | MODIFY — import from utils/user_resolution instead of local def |
| `mcp_tools/allocation.py`, `audit.py`, `baskets.py`, `positions.py`, `transactions.py` | MODIFY — import from utils/user_resolution |

## Verification

### 1. Fix futures MTM gap
```bash
# Re-ingest IBKR to pick up futures MTM rows
fetch_provider_transactions(provider="ibkr_flex")

# Verify MTM rows stored
SELECT count(*) FROM raw_transactions WHERE provider = 'ibkr_flex_mtm';
```

### 2. Compare store-read vs live-fetch
```bash
# Run realized performance both ways, compare returns
TRANSACTION_STORE_READ=false get_performance(mode='realized', institution='schwab')
# Note the return %

TRANSACTION_STORE_READ=true get_performance(mode='realized', institution='schwab')
# Should produce identical return %

# Repeat for IBKR and Plaid
```

### 3. Verify income path
```bash
# Check that income_analysis output matches between both paths
# income_with_currency count, total_income, by_month keys should be identical
```

### 4. Verify other call sites
```bash
TRANSACTION_STORE_READ=true get_trading_analysis(institution='schwab')
TRANSACTION_STORE_READ=true suggest_tax_loss_harvest(institution='schwab')
```

## Risk Assessment

**Medium risk** — modifying 4 call sites in the analysis read path. Mitigated by:
1. **Feature flag** — `TRANSACTION_STORE_READ=false` by default, existing path unchanged
2. **Same output shape** — FIFO dicts have identical keys, downstream code untouched
3. **Income shim** — StoreBackedIncomeProvider satisfies both downstream analyzer usages without changing their code
4. **Comparison testing** — run both paths, compare results before enabling
5. **SQL prefilter + Python post-filter** — performance optimization without sacrificing alias correctness

## Codex Review History

### Review 1 (R1-R8): 4 PASS / 4 FAIL
- R1 FAIL: Missing `provider_account_ref` → **Fixed**: Clarified it's on flow events/fetch_metadata (already in DB), not FIFO dicts. Added explicit output mapping in Step 2.
  - Review 2 re-FAIL: Lines 4143/4264 do `txn.get("provider_account_ref")` on FIFO dicts → **Verified**: Field is never set by normalizers/TradingAnalyzer; `.get()` returns `None` in live path too. Store path matches. No action needed.
- R2 FAIL: Inconsistent MTM description → **Fixed**: Clarified these are already-structured event dicts stored as JSONB.
- R3 FAIL: Missed call sites → **Fixed**: Added explicit out-of-scope table with rationale.
- R4 FAIL: `analyzer` used after line 3290 for income → **Fixed**: Added StoreBackedIncomeProvider shim (Step 5) and documented both downstream usages.
- R5 FAIL: Circular dependency for user_id → **Fixed**: Extract to `utils/user_resolution.py` (Step 4).
- R6 FAIL: Income events needed downstream → **Fixed**: Wired through StoreBackedIncomeProvider + load_income_events.
- R7 PASS: Flow shape compatible, needs key mapping → **Fixed**: Added explicit field mapping table in Step 2.
- R8 PASS: SQL prefilter + Python post-filter → **Fixed**: Documented in Step 8.

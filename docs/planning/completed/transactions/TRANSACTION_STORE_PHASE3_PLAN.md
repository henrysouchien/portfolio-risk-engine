# Plan: Transaction Store Phase 3 — Inspection & Debugging Tools

## Context

Phase 1 (ingest) and Phase 2 (read path) are complete. All 3 institutions produce identical results between store-read and live-fetch paths. The store now has all data — raw rows, normalized transactions, income events, flow events, futures MTM, and ingestion batch metadata.

**Goal**: Expose MCP tools that let us query, inspect, and debug stored transaction data — specifically to diagnose why realized performance return %s are off:
- Schwab: +17.53% vs -8.29% actual (aggregate broken, per-account works)
- IBKR: -8.04% vs -9.35% actual (1.31pp gap, near-solved)
- Plaid/Merrill: -11.77% vs -12.49% actual (0.72pp gap, near-solved)

Three known distortion sources (from `REALIZED_PERF_DATA_QUALITY.md`):

| Distortion | Primary Diagnostic Tool | What It Shows |
|-----------|------------------------|---------------|
| **Synthetic positions** (10 symbols, no opening BUY → fake cash) | `transaction_coverage` (Tool 6) | `diagnostics.synthetic_position_candidates` + `diagnostics.zero_transaction_symbols` |
| **Futures notional amplification** (MHI/ZF/MGC $100K-$237K flows) | `transaction_coverage` (Tool 6) | `diagnostics.futures_notional_risk` flags futures symbols; drill down with `inspect_transactions` |
| **Plaid UNKNOWN symbols** (54 trades, $4M phantom volume) | `transaction_coverage` (Tool 6) | `diagnostics.unknown_symbol_transactions`; drill down with `inspect_transactions(symbol="UNKNOWN")` to see raw_data |

`transaction_coverage` is the **single entry point** for all three distortion sources. It provides the summary-level diagnostics. `inspect_transactions` is the **drill-down tool** for investigating individual symbols flagged by `transaction_coverage`. `list_flow_events` is a **supplementary tool** for examining broker-reported cash flows (contributions/withdrawals) — it does NOT surface trade-derived or synthetic flows.

## Store Methods That Already Exist (No MCP Wrapper)

| TransactionStore Method | Signature | Filter Support |
|------------------------|-----------|---------------|
| `list_batches(user_id, provider?, limit=20)` | Returns batch metadata dicts | provider only |
| `query_raw_transactions(user_id, provider?, symbol?, account_id?)` | Returns raw_data JSONB dicts | provider, symbol, account_id — NO institution, NO date range |
| `load_fifo_transactions(user_id, provider?, institution?, account?)` | Returns FIFO-shaped dicts | provider + account in SQL; institution param accepted but **ignored** (caller does alias-aware post-filter) |
| `load_income_events(user_id, provider?, institution?, account?)` | Returns income dicts | provider + account in SQL; institution **ignored** — NO symbol, NO income_type, NO date range |
| `load_provider_flow_events(user_id, provider?, institution?, account?)` | Returns flow event dicts | provider + account in SQL; institution **ignored** — NO min_amount, NO date range |
| `load_futures_mtm(user_id, institution?, account?)` | Returns MTM event dicts | institution **ignored**, account in SQL |

**Key pattern**: All store methods accept `institution` but immediately `del` it — institution filtering is delegated to the calling layer because it requires alias-aware matching (`match_institution()` in Python, not expressible in SQL). MCP tool wrappers must do Python post-filtering on institution when the param is provided.

## New MCP Tools

### Tool 1: `list_ingestion_batches`

Wraps `store.list_batches()`. Answers: "when was data last ingested?", "did it fail?", "is data partial?"

**Parameters**: `user_email: str, provider: str? = None`

**Output**:
```python
{
  "status": "ok",
  "batches": [
    {
      "batch_id": "uuid",
      "provider": "schwab",
      "institution": "schwab",
      "status": "complete",          # pending|ingesting|normalizing|complete|failed
      "raw_row_count": 348,
      "normalized_row_count": 101,
      "income_row_count": 115,
      "flow_row_count": 140,
      "fetch_window_start": "2025-03-01T00:00:00",
      "fetch_window_end": "2026-03-03T00:00:00",
      "payload_coverage_start": "2025-03-15T00:00:00",
      "payload_coverage_end": "2026-03-01T00:00:00",
      "pagination_exhausted": true,
      "partial_data": false,
      "fetch_error": null,
      "started_at": "2026-03-03T10:00:00",
      "completed_at": "2026-03-03T10:00:05"
    }
  ]
}
```

**Debugging value**: Shows if a provider fetch was partial or errored, date coverage gaps, row count sanity checks.

### Tool 2: `inspect_transactions`

The key debugging tool. Shows raw + normalized side-by-side for a symbol or account.

**Parameters**: `user_email: str, symbol: str? = None, account_id: str? = None, provider: str? = None, limit: str = "50"`

**Output**:
```python
{
  "status": "ok",
  "normalized": [
    {
      "type": "BUY", "date": "2025-06-15", "symbol": "AAPL", "quantity": 100.0,
      "price": 150.0, "fee": 0.0, "account_id": "12345", "account_name": "IRA",
      "instrument_type": "equity", "is_option": false, "is_futures": false,
      "provider": "schwab", "institution": "schwab", "transaction_id": "txn_abc",
      "raw_transaction_id": 42  # FK to raw_transactions.id (null if not yet populated)
    }
  ],
  "raw": [
    {
      "id": 42, "provider_transaction_id": "schwab_txn_abc",
      "dedup_key": "schwab_txn_abc", "raw_data": { /* original provider JSON */ },
      "transaction_date": "2025-06-15", "symbol": "AAPL", "account_id": "12345"
    }
  ],
  "summary": {
    "symbol_count": 1,
    "buy_count": 5, "sell_count": 2, "short_count": 0, "cover_count": 0,
    "total_buy_qty": 500.0, "total_sell_qty": 200.0, "net_position": 300.0,
    "date_range": {"first": "2025-03-15", "last": "2026-02-28"},
    "has_opening_buy": true,
    "is_futures": false,
    "has_unknown_symbol": false,
    "unknown_symbol_count": 0
  }
}
```

**Implementation**: Query `store.query_normalized_transactions()` + `store.query_raw_transactions()` for the same filters. Compute summary stats in Python. The `has_opening_buy` check is critical — it flags the symbols causing synthetic position distortion.

**Note on `query_normalized_transactions()` columns**: Currently returns 22 columns but does NOT include `raw_transaction_id`. Step 1 adds this column to the SELECT list so `inspect_transactions` can show the FK link.

**Note on raw_transaction_id FK**: Currently always NULL (line 508 in `store_normalized_transactions` passes `None`). Step 1 populates this during ingest for direct lineage. Until re-ingest, the tool falls back to matching by `(provider, transaction_id)` ↔ `(provider, dedup_key)`.

### Tool 3: `list_flow_events`

Wraps `store.load_provider_flow_events()` with additional filtering (requires extending the store method).

**Parameters**: `user_email: str, provider: str? = None, institution: str? = None, account: str? = None, min_amount: str? = None, max_amount: str? = None, start_date: str? = None, end_date: str? = None, limit: str = "100"`

**Output**:
```python
{
  "status": "ok",
  "flow_events": [
    {
      "event_type": "contribution", "date": "2025-06-15", "timestamp": "2025-06-15T00:00:00",
      "amount": 5000.0, "account_id": "12345", "account_name": "IRA",
      "provider": "schwab", "provider_account_ref": "ref_abc",
      "currency": "USD", "description": "Wire transfer"
    }
  ],
  "summary": {
    "total_count": 140,
    "total_inflow": 25000.0,
    "total_outflow": 5000.0,
    "net_flow": 20000.0,
    "largest_single_event": {"amount": 10000.0, "date": "2025-09-01", "event_type": "contribution"}
  }
}
```

**Debugging value**: Query `min_amount=50000` to surface outsized flow events:
- Futures notional spikes ($100K-$237K single events)
- Any other events that distort Dietz/TWR denominators

**Important limitation**: Provider flow events are **broker-reported** flows (contributions, withdrawals, transfers). They do NOT include synthetic cash events or inferred trade flows. To diagnose synthetic position distortion, use `transaction_coverage` (Tool 6) which directly identifies symbols with missing opening buys. To diagnose UNKNOWN symbol phantom volume, use `inspect_transactions` (Tool 2) with `symbol="UNKNOWN"`.

### Tool 4: `list_income_events`

Wraps `store.load_income_events()` with additional filtering (requires extending the store method).

**Parameters**: `user_email: str, provider: str? = None, institution: str? = None, account: str? = None, symbol: str? = None, income_type: str? = None, start_date: str? = None, end_date: str? = None, limit: str = "100"`

**Output**:
```python
{
  "status": "ok",
  "income_events": [
    {
      "symbol": "AAPL", "income_type": "dividend", "amount": 25.50,
      "date": "2025-09-15", "account_id": "12345", "account_name": "IRA",
      "provider": "schwab", "currency": "USD"
    }
  ],
  "summary": {
    "total_count": 115,
    "total_amount": 3250.75,
    "by_type": {"dividend": 2800.0, "interest": 450.75},
    "by_symbol_top10": [{"symbol": "AAPL", "total": 500.0}, ...]
  }
}
```

**Debugging value**: Verify dividends/interest attribution. Check for income events misclassified as trade activity.

### Tool 5: `refresh_transactions`

Re-runs ingest for a provider (or all), fetching fresh data from provider APIs and re-normalizing.

**Parameters**: `user_email: str, provider: str? = None`

**Output**:
```python
{
  "status": "ok",
  "refreshed_providers": ["schwab", "ibkr_flex", "plaid"],
  "results": [
    {
      "provider": "schwab",
      "batch_id": "uuid",
      "status": "complete",
      "raw_rows_upserted": 348,
      "normalized_rows_upserted": 101,
      "income_rows_upserted": 115,
      "flow_rows_upserted": 140,
      "duration_seconds": 3.2
    }
  ],
  "errors": []  # [{provider, error_message}] if any provider fails
}
```

**Implementation**: Calls `fetch_provider_transactions()` internally for each provider. The existing upsert logic handles idempotent re-ingest. This is essentially a convenience wrapper — but valuable because it:
1. Picks up new transactions since last ingest
2. Re-normalizes with any normalizer fixes (e.g., the IBKR cash-row fix from Phase 2)
3. Updates `ingestion_batches` metadata

### Tool 6: `transaction_coverage`

Summary view — what's in the store, by provider/symbol/date. Includes diagnostics for all 3 known distortion sources.

**Parameters**: `user_email: str, provider: str? = None, institution: str? = None`

**Output**:
```python
{
  "status": "ok",
  "by_provider": [
    {
      "provider": "schwab", "symbol_count": 45, "txn_count": 101,
      "date_range": {"first": "2025-03-15", "last": "2026-03-01"},
      "unknown_symbol_count": 0, "futures_txn_count": 0, "options_txn_count": 3
    }
  ],
  "by_symbol": [
    {
      "symbol": "AAPL", "provider": "schwab",
      "buy_count": 5, "sell_count": 2, "short_count": 0, "cover_count": 0,
      "total_buy_qty": 500.0, "total_sell_qty": 200.0, "net_qty": 300.0,
      "has_opening_buy": true, "is_futures": false
    }
  ],
  "diagnostics": {
    "synthetic_position_candidates": [
      {
        "symbol": "NVDA", "provider": "ibkr_flex",
        "sell_count": 3, "sell_qty": 150.0, "buy_count": 0, "buy_qty": 0.0,
        "reason": "exits_without_opens"
      }
    ],
    "zero_transaction_symbols": [
      {
        "symbol": "EQT", "position_source": "snaptrade",
        "institution": "Interactive Brokers", "account_id": "U1234567",
        "reason": "held_in_positions_but_no_transactions"
      }
    ],
    "unknown_symbol_transactions": [
      {
        "provider": "plaid", "count": 54,
        "total_notional": 4032733.0,
        "date_range": {"first": "2025-04-01", "last": "2026-02-15"}
      }
    ],
    "futures_notional_risk": [
      {
        "symbol": "MHI", "provider": "ibkr_flex",
        "txn_count": 12, "is_futures": true,
        "note": "Futures trades may cause notional amplification in cash replay"
      }
    ]
  }
}
```

**Implementation notes**:

The `synthetic_position_candidates` SQL detects symbols with exit trades (SELL/SHORT) but no matching entry trades (BUY/COVER):
```sql
SELECT symbol, provider,
  SUM(CASE WHEN trade_type IN ('BUY','COVER') THEN 1 ELSE 0 END) as buy_count,
  SUM(CASE WHEN trade_type IN ('BUY','COVER') THEN quantity ELSE 0 END) as buy_qty,
  SUM(CASE WHEN trade_type IN ('SELL','SHORT') THEN 1 ELSE 0 END) as sell_count,
  SUM(CASE WHEN trade_type IN ('SELL','SHORT') THEN quantity ELSE 0 END) as sell_qty
FROM normalized_transactions WHERE user_id = %s
GROUP BY symbol, provider
HAVING SUM(CASE WHEN trade_type IN ('BUY','COVER') THEN quantity ELSE 0 END) <
       SUM(CASE WHEN trade_type IN ('SELL','SHORT') THEN quantity ELSE 0 END)
   OR (SUM(CASE WHEN trade_type IN ('BUY','COVER') THEN 1 ELSE 0 END) = 0
       AND SUM(CASE WHEN trade_type IN ('SELL','SHORT') THEN 1 ELSE 0 END) > 0);
```

This catches two patterns:
1. **Exits without opens** (0 buys, N sells) — e.g., position opened before data window
2. **Insufficient opens** (buy_qty < sell_qty) — e.g., partial history with some buys but more sells

The `zero_transaction_symbols` diagnostic detects positions held in the broker but with ZERO transaction history. This requires comparing against current positions. The MCP tool wrapper **always** fetches current positions before calling the store method — this is not optional.

**Implementation**: The MCP tool wrapper calls `_load_current_position_symbols()`, a helper that uses the existing position service to get held tickers:

```python
# In mcp_tools/transactions.py:
def _load_current_position_symbols(user_email: str, institution: str | None = None) -> list[dict]:
    """Load current position symbols from position service.

    Returns list of {symbol, provider, institution, account_id} dicts.
    Uses the same position loading path as get_positions MCP tool.

    PositionResult.data.positions is a list[dict] with keys:
    ticker, quantity, value, type, position_source, currency,
    brokerage_name, account_id, account_name, ...
    """
    from services.position_service import PositionService

    service = PositionService(user_email=user_email)
    # get_all_positions returns PositionResult; institution/account filtering
    # is built in via its own params (uses match_institution internally)
    result = service.get_all_positions(institution=institution)

    symbols = []
    for p in result.data.positions:
        ticker = p.get("ticker", "")
        if not ticker or ticker == "CASH" or ticker.startswith("CUR:"):
            continue
        symbols.append({
            "symbol": ticker,
            "provider": p.get("position_source", ""),
            "institution": p.get("brokerage_name", ""),
            "account_id": p.get("account_id", ""),
        })
    return symbols
```

Note: `PositionService.__init__` requires `user_email` as first arg. `get_all_positions(institution=...)` fetches from all enabled providers, applies institution filtering internally (using `match_institution` on `brokerage_name`), and returns `PositionResult`. `result.data` is `PositionsData` with `.positions: list[dict]`. Position dicts use `ticker` (not `symbol`), `position_source` (not `provider/source`), `brokerage_name` (not `institution`).

The store method receives the position symbol list and compares against `normalized_transactions`:

```python
# In inputs/transaction_store.py:
def transaction_coverage(self, user_id, provider=None, position_symbols=None):
    # ... other queries ...

    # Zero-transaction detection — match on symbol only, not provider.
    # Reason: position_source (snaptrade/plaid/schwab) may differ from
    # transaction provider (ibkr_flex/schwab/plaid). E.g., IBKR positions
    # come via snaptrade aggregator, but transactions come from ibkr_flex.
    if position_symbols:
        cursor.execute("""
            SELECT DISTINCT symbol FROM normalized_transactions
            WHERE user_id = %s
        """, (user_id,))
        stored_symbols = {r["symbol"] for r in cursor.fetchall()}

        zero_txn = [
            ps for ps in position_symbols
            if ps.get("symbol") not in stored_symbols
        ]
```

This keeps the store method free of live API dependencies while ensuring `zero_transaction_symbols` is always populated.

## Implementation Steps

### Step 1: Fix raw_transaction_id FK Population

**File**: `inputs/transaction_store.py`

The ingest flow is: `mcp_tools/transactions.py` calls `store.store_raw_transactions()` (line 63) → then calls `store.normalize_batch()` (line 81). Inside `normalize_batch()`, raw rows are loaded back from DB via `_load_raw_batch_rows()` (line 326) which already returns `id`, `provider`, and `raw_data` per row.

**Change 1**: In `normalize_batch()` (line ~326), after loading raw rows, build the FK lookup from the already-loaded rows. `_load_raw_batch_rows()` returns `SELECT id, provider, raw_data FROM raw_transactions` — we need to also select `dedup_key`:

```python
# In _load_raw_batch_rows(), change SQL to:
SELECT id, provider, dedup_key, raw_data FROM raw_transactions WHERE ...
```

Then in `normalize_batch()`:
```python
rows = self._load_raw_batch_rows(user_id=user_id, batch_id=batch_id, provider=provider)

# Build raw_id lookup: {(provider, dedup_key): raw_id}
raw_id_map = {(r["provider"], r["dedup_key"]): r["id"] for r in rows}
```

**Change 2**: Pass `raw_id_map` to `store_normalized_transactions()`:

```python
normalized_count = self.store_normalized_transactions(
    user_id=user_id, batch_id=batch_id,
    fifo_transactions=fifo_transactions,
    raw_id_map=raw_id_map,
)
```

**Change 3**: In `store_normalized_transactions()`, accept `raw_id_map: dict | None = None` parameter. Replace the `None` at line 508 with:

```python
raw_transaction_id = (raw_id_map or {}).get((provider, transaction_id))
```

The `dedup_key` format matches `transaction_id` for all providers (both use `{provider}_{native_id}` pattern from `_dedup_key()`). If no match found, FK remains NULL — acceptable for edge cases.

**Change 4**: Add `raw_transaction_id = EXCLUDED.raw_transaction_id` to the ON CONFLICT UPDATE clause (line ~486-503) so re-ingests update the FK too.

No changes to `store_raw_transactions()` or the MCP ingest tool — the FK map is built entirely within `normalize_batch()` from DB rows it already loads.

### Step 2: Extend Store Methods with Additional Filters

**File**: `inputs/transaction_store.py`

**`load_income_events()`** — add optional SQL filters:
- `symbol: str? = None` → `AND symbol = %s`
- `income_type: str? = None` → `AND income_type = %s`
- `start_date: str? = None` → `AND event_date >= %s`
- `end_date: str? = None` → `AND event_date <= %s`

**`load_provider_flow_events()`** — add optional SQL filters:
- `min_amount: float? = None` → `AND ABS(amount) >= %s`
- `max_amount: float? = None` → `AND ABS(amount) <= %s`
- `start_date: str? = None` → `AND event_date >= %s`
- `end_date: str? = None` → `AND event_date <= %s`

Note: `ABS(amount)` for flow events because withdrawals are negative. The filter should match on absolute value so both large inflows and outflows are surfaced.

### Step 3: Add `transaction_coverage()` Store Method

**File**: `inputs/transaction_store.py`

New method:
```python
def transaction_coverage(
    self,
    user_id: int,
    provider: Optional[str] = None,
    position_symbols: Optional[list[dict]] = None,  # [{"symbol", "provider", "institution", "account_id"}]
) -> dict:
```

Three queries:
1. **By provider**: `SELECT provider, COUNT(DISTINCT symbol), COUNT(*), ...`
2. **By symbol**: `SELECT symbol, provider, SUM(CASE WHEN ... THEN quantity ...) ...` with HAVING clause for synthetic detection
3. **Unknown symbols**: `SELECT provider, COUNT(*), SUM(quantity * price) FROM normalized_transactions WHERE symbol = 'UNKNOWN' ...`

If `position_symbols` is provided, also compute `zero_transaction_symbols` by checking which symbols appear in positions but have 0 rows in `normalized_transactions`.

### Step 4: Add MCP Tools (6 tools)

**File**: `mcp_tools/transactions.py`

All 6 tools follow the same pattern:
1. Resolve `user_email` → `user_id` via `resolve_user_id()`
2. Call existing `TransactionStore` method (with filter extensions from Step 2)
3. Apply institution post-filtering in Python where needed (using `match_institution()`)
4. Compute summary stats in Python
5. Return formatted output

Institution filtering pattern (same as Phase 2):
```python
results = store.load_provider_flow_events(user_id=user_id, provider=provider, account=account)
if institution:
    from trading_analysis.data_fetcher import match_institution
    results = [r for r in results if match_institution(r.get("institution", ""), institution)]
```

### Step 5: Register Tools in MCP Server

**File**: `mcp_server.py`

Register all 6 new tools with parameter schemas.

## Key Files

| File | Change |
|------|--------|
| `inputs/transaction_store.py` | FIX `raw_transaction_id` FK population; ADD filter params to `load_income_events()` and `load_provider_flow_events()`; ADD `transaction_coverage()` method |
| `mcp_tools/transactions.py` | ADD 6 MCP tool functions (`list_ingestion_batches`, `inspect_transactions`, `list_flow_events`, `list_income_events`, `refresh_transactions`, `transaction_coverage`) |
| `mcp_server.py` | REGISTER 6 new tools |

## Verification

### V1: Batch inspection
```
list_ingestion_batches(provider="schwab")
→ ASSERT: status == "complete"
→ ASSERT: raw_row_count > 0, normalized_row_count > 0, income_row_count > 0, flow_row_count > 0
→ ASSERT: pagination_exhausted == true, partial_data == false, fetch_error == null
→ ASSERT: fetch_window_start and fetch_window_end are non-null dates
→ ASSERT: all row counts are consistent (normalized <= raw, etc.)
```

### V2: Synthetic position detection — Schwab
```
transaction_coverage(institution="schwab")
→ ASSERT: diagnostics.synthetic_position_candidates contains CPPMF, IT, LIFFF, PCTY
→ ASSERT: each candidate has buy_count == 0 and sell_count > 0
→ ASSERT: diagnostics.zero_transaction_symbols is populated (not empty list — positions loaded from service)
```

### V3: Synthetic position detection — IBKR
```
transaction_coverage(institution="ibkr")
→ ASSERT: diagnostics.synthetic_position_candidates contains at least 3 of: EQT, IGIC, KINS, NVDA, TKO, V
→ ASSERT: diagnostics.futures_notional_risk contains MHI, ZF, MGC (all with is_futures=true)
→ ASSERT: diagnostics.zero_transaction_symbols includes symbols held but with 0 normalized rows
```

### V4: Unknown symbol detection
```
transaction_coverage(institution="merrill")
→ ASSERT: diagnostics.unknown_symbol_transactions has entry with provider="plaid", count == 54
→ ASSERT: total_notional > 4_000_000

inspect_transactions(symbol="UNKNOWN", provider="plaid")
→ ASSERT: len(normalized) == 54
→ ASSERT: summary.has_unknown_symbol == true
→ ASSERT: summary.unknown_symbol_count == 54
→ ASSERT: raw[0].raw_data contains actual security info (name, cusip, etc.)
```

### V5: Flow event filtering
```
list_flow_events(institution="ibkr", min_amount=50000)
→ ASSERT: all returned events have abs(amount) >= 50000
→ ASSERT: summary.largest_single_event is populated with amount and date

list_flow_events(institution="ibkr", start_date="2025-06-01", end_date="2025-06-30")
→ ASSERT: all returned events have date within range

list_flow_events(institution="merrill")
→ ASSERT: status == "ok", flow_events is a list
```

### V6: Income filtering
```
list_income_events(institution="ibkr", income_type="interest")
→ ASSERT: all returned events have income_type == "interest"
→ ASSERT: summary.by_type has only "interest" key

list_income_events(symbol="AAPL")
→ ASSERT: all returned events have symbol == "AAPL"
→ ASSERT: summary.total_amount > 0
```

### V7: Refresh and re-verify
```
refresh_transactions(provider="schwab")
→ ASSERT: status == "ok"
→ ASSERT: results[0].provider == "schwab"
→ ASSERT: results[0].raw_rows_upserted > 0 and results[0].normalized_rows_upserted > 0
→ ASSERT: errors == []

# Re-run coverage to confirm store is healthy after refresh
transaction_coverage(institution="schwab")
→ ASSERT: by_provider has entry for "schwab" with txn_count > 0
→ ASSERT: diagnostics sections are populated (not empty dicts)
```

### V8: FK lineage (after refresh with FK fix)
```
# Direct SQL verification — check FK population rate:
SELECT
  COUNT(*) as total,
  COUNT(raw_transaction_id) as linked,
  COUNT(*) - COUNT(raw_transaction_id) as unlinked
FROM normalized_transactions
WHERE user_id = 1 AND provider = 'schwab';
→ ASSERT: linked / total > 0.95 (>95% of rows should have FK populated)
→ Edge cases: some normalized rows may lack FK if dedup_key ↔ transaction_id doesn't match

# Verify FK validity (no dangling references):
SELECT n.id, n.raw_transaction_id
FROM normalized_transactions n
WHERE n.user_id = 1 AND n.raw_transaction_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM raw_transactions r WHERE r.id = n.raw_transaction_id);
→ ASSERT: 0 rows returned (all non-null FKs point to valid raw rows)

# Via MCP tool:
inspect_transactions(symbol="AAPL", provider="schwab")
→ ASSERT: at least one normalized row has raw_transaction_id as non-null integer
→ ASSERT: raw list contains entry with matching id
```

### V9: Tool registration
```
# Verify all 6 tools are registered and callable:
list_ingestion_batches(user_email="hc@henrychien.com")  → status == "ok"
inspect_transactions(user_email="hc@henrychien.com", symbol="AAPL")  → status == "ok"
list_flow_events(user_email="hc@henrychien.com")  → status == "ok"
list_income_events(user_email="hc@henrychien.com")  → status == "ok"
refresh_transactions(user_email="hc@henrychien.com", provider="schwab")  → status == "ok"
transaction_coverage(user_email="hc@henrychien.com")  → status == "ok"
```

## Risk Assessment

**Low risk** — all tools are read-only queries over existing data. Only `refresh_transactions` modifies data (via existing idempotent upsert). No changes to the analysis pipeline.

## Codex Review History

### Review 1 (R1-R8): 2 PASS / 6 FAIL
- R1 FAIL: `refresh_transactions` output not concrete → **Fixed**: Added full output schema for all 6 tools with example values.
- R2 FAIL: Store methods don't support assumed filters → **Fixed**: Documented actual signatures and filter support. Step 2 explicitly extends `load_income_events` (add symbol/type/date) and `load_provider_flow_events` (add amount/date). Institution filtering documented as Python post-filter pattern.
- R3 PASS: FK fix feasible.
- R4 FAIL: Synthetic SQL misses "held with no transactions" → **Fixed**: Added `zero_transaction_symbols` diagnostic (positions with 0 rows). Updated HAVING clause to also catch `buy_qty < sell_qty` (insufficient opens), not just `buy_count = 0`.
- R5 FAIL: Missing holdings-vs-transactions diagnostic → **Fixed**: Added `zero_transaction_symbols` in `transaction_coverage`, fed by optional `position_symbols` input from position service. Tool wrapper fetches positions first, passes symbol list to store method.
- R6 FAIL: Flow amount filter alone won't catch all distortion → **Fixed**: Clarified that `list_flow_events` covers broker-reported flows only. Added explicit notes that synthetic position distortion requires `transaction_coverage` diagnostics, and UNKNOWN symbol distortion requires `inspect_transactions`. Each distortion source now has a clear primary tool.
- R7 PASS: No dependency/import issues.
- R8 FAIL: Verification gaps → **Fixed**: Added verification sections for income (5), refresh (6), FK lineage (7), and coverage comparison (8). Total 8 verification scenarios covering all 6 tools and the FK fix.

### Review 2 (R1-R8): 3 PASS / 5 FAIL
- R1 PASS.
- R2 PASS.
- R3 FAIL: FK fix incomplete — ON CONFLICT upsert doesn't reliably return IDs → **Fixed**: Specified PostgreSQL `RETURNING id, provider, dedup_key` on the raw upsert SQL (works with both INSERT and ON CONFLICT UPDATE paths). Return `raw_id_map` from `store_raw_transactions()`. Also add `raw_transaction_id = EXCLUDED.raw_transaction_id` to normalized upsert ON CONFLICT clause.
- R4 FAIL: `zero_transaction_symbols` was optional → **Fixed**: Made non-optional. MCP wrapper always calls `_load_current_position_symbols()` before `transaction_coverage()`. Store method receives position list and always computes zero-txn detection.
- R5 PASS.
- R6 FAIL: Primary tool mapping ambiguous for futures → **Fixed**: Added distortion→tool mapping table at top of plan. `transaction_coverage` is the single entry point for all 3 distortion sources; `inspect_transactions` is drill-down; `list_flow_events` is supplementary for broker-reported flows only.
- R7 FAIL: `get_current_position_symbols` undefined → **Fixed**: Replaced with concrete `_load_current_position_symbols()` helper with full implementation using `PositionService` + `resolve_providers_for_institution()`.
- R8 FAIL: Verification lacked strict assertions → **Fixed**: 9 verification scenarios (V1-V9) with explicit ASSERT statements. Added SQL verification for FK correctness. Added filter behavior assertions. Added tool registration smoke test.

### Review 3 (R1-R8): 3 PASS / 5 FAIL
- R1 FAIL: `list_income_events` missing institution/account params → **Fixed**: Added `institution` and `account` params to match other tools.
- R2 FAIL: Used `income_date` instead of `event_date` for income table → **Fixed**: Corrected to `event_date` (actual column name in `normalized_income` table).
- R3 PASS.
- R4 FAIL: `_load_current_position_symbols()` used wrong PositionService API → **Fixed**: Constructor takes `user_email` as required first arg. Use `get_all_positions()` (returns `PositionResult` with `.positions`). Added institution post-filtering with `match_institution()`.
- R5 PASS.
- R6 PASS.
- R7 FAIL: Wrong import path for `match_institution` → **Fixed**: Changed from `mcp_tools.aliases` to `trading_analysis.data_fetcher` (where `match_institution` is actually defined). `mcp_tools/aliases.py` only re-exports `match_brokerage` which wraps it with reversed arg order.
- R8 FAIL: V8 asserted FK non-null for ALL rows, conflicting with acknowledged edge cases → **Fixed**: Changed to assert >95% FK population rate + 0 dangling references. Added validity check (no orphaned FK pointers).

### Review 4 (R1-R8): 4 PASS / 4 FAIL
- R1 PASS.
- R2 FAIL: `query_normalized_transactions()` doesn't return `raw_transaction_id`; FK flow description wrong → **Fixed**: Added note that `raw_transaction_id` must be added to the SELECT. Rewrote FK fix to use `_load_raw_batch_rows()` (which already loads raw rows in `normalize_batch()`) instead of changing `store_raw_transactions()` return type. No changes needed to MCP ingest tool or `store_raw_transactions()`.
- R3 PASS.
- R4 FAIL: `_load_current_position_symbols()` used wrong PositionResult shape → **Fixed**: Uses `result.data.positions` (list[dict] with `ticker`, `position_source`, `brokerage_name` keys). Uses `get_all_positions(institution=institution)` which handles institution filtering internally. `_load_raw_batch_rows()` updated to also SELECT `dedup_key`.
- R5 PASS.
- R6 PASS.
- R7 FAIL: Incorrect position dict field names, wrong PositionService API → **Fixed**: Corrected all field mappings (`ticker` not `symbol`, `position_source` not `source`, `brokerage_name` not `institution`). `get_all_positions()` accepts `institution` param directly. `position_symbols` type changed from `list[tuple]` to `list[dict]`.
- R8 FAIL: Hardcoded row counts, brittle assertions → **Fixed**: V1 uses `> 0` instead of exact counts. V7 checks store health rather than exact count match. V8 uses >95% rate instead of 100%. V9 smoke tests all tools.

### Review 5 (R1-R8): 7 PASS / 1 FAIL
- R4 FAIL: Zero-transaction match used `(symbol, provider)` but `position_source` (snaptrade/plaid) differs from transaction `provider` (ibkr_flex) for IBKR positions → **Fixed**: Changed to match on `symbol` only. Position sources (aggregator) and transaction providers (direct) are fundamentally different namespaces — symbol is the correct join key for detecting held-but-no-transactions.

## Follow-Up: Make Store Default (Phase 3b)

After using inspection tools to diagnose and fix data quality issues:
1. Enable `TRANSACTION_STORE_READ=true` by default in settings.py
2. Remove feature flag branches (simplify code)
3. Deprecate live-fetch path in `_analyze_realized_performance_single_scope()`
4. Move `fetch_provider_transactions` to automatic trigger (on performance run if stale)

This is deferred until the store-read path has been validated in production use.

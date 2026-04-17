# Plan: Transaction Store — Persistent Ingestion Pipeline

## Context

Realized performance debugging has been painful because:
1. **No persistence** — transactions are fetched fresh from provider APIs every run. Data can change between runs, making it impossible to isolate fixes vs data drift.
2. **No visibility** — normalization is coupled to calculation. When numbers look wrong, we monkey-patch deep into a 6,600-line file because there's no intermediate layer to inspect.
3. **No audit trail** — we can't answer "what did the provider actually send?" without re-fetching (which may return different data).

This plan adds a PostgreSQL transaction store with inspectable stages:
```
[Ingest] → raw rows in DB → [Normalize] → normalized rows in DB → [Calculate]
```

Each stage is queryable. Debugging becomes: "did the raw data have the RECEIVE_AND_DELIVER?" → "did the normalizer produce a SELL?" → "did the flow filter keep it?"

## Schema Design

### 6 new tables in existing PostgreSQL DB

**`ingestion_batches`** — Tracks each fetch operation (audit + diagnostics)
- UUID PK, `user_id` FK, `provider`, `institution`, `account_id`
- `status` lifecycle: pending → ingesting → normalizing → complete | failed
- Mirrors `FetchMetadata` fields: coverage window, pagination, partial_data, errors
- Indexed on `(user_id, provider)` and `(user_id, started_at DESC)`

**`raw_transactions`** — Provider-native payloads stored as JSONB
- BIGSERIAL PK, `user_id` FK, `batch_id` FK
- `provider`, `provider_transaction_id` (native ID — available for all 4 providers, see dedup table)
- `dedup_key` VARCHAR(255) — provider-native transaction ID (see dedup table below)
- `raw_data` JSONB — entire provider row as-is
- Denormalized: `transaction_date`, `symbol`, `account_id` (for querying without JSONB)
- **UNIQUE** `(user_id, provider, dedup_key)` — idempotent upsert
- Re-ingesting: `ON CONFLICT DO UPDATE SET raw_data = EXCLUDED.raw_data, batch_id = EXCLUDED.batch_id`

**`plaid_securities`** — Plaid security lookup (needed for normalization)
- `security_id`, `ticker_symbol`, `cusip`, `isin`, `name`, `type`, `close_price`, `option_contract` JSONB, `fixed_income` JSONB
- **UNIQUE** `(user_id, security_id)`

**`normalized_transactions`** — FIFO-ready flat columns (what `TradingAnalyzer` currently produces)
- Core: `symbol`, `trade_type` (BUY/SELL/SHORT/COVER), `transaction_date`, `quantity`, `price`, `fee`, `currency`
- Identity: `provider`, `institution`, `account_id`, `account_name`, `transaction_id`
- Instrument: `instrument_type`, `contract_identity` JSONB, `is_option` BOOLEAN, `is_futures` BOOLEAN, `option_expired` BOOLEAN
- Lineage: `raw_transaction_id` FK, `batch_id` FK, `normalizer_version`
- **UNIQUE** `(user_id, provider, transaction_id)`

**`normalized_income`** — Dividends, interest, distributions
- `symbol`, `income_type`, `event_date`, `amount`, `currency`
- Same provider/account/lineage columns as normalized_transactions
- **UNIQUE** `(user_id, provider, transaction_id)`

**`provider_flow_events`** — Cash flow events for realized performance
- Mirrors `ProviderFlowEvent` TypedDict from `providers/flows/common.py`
- `event_date`, `amount`, `flow_type`, `is_external_flow`
- `raw_type`, `raw_subtype`, `raw_description`, `confidence`
- `transaction_id` VARCHAR(255) — provider-native ID for stable dedup
- `provider_row_fingerprint` VARCHAR(64) — content hash for audit (not primary dedup key)
- **UNIQUE** `(user_id, provider, transaction_id)` — uses provider-native ID, not content hash

### Dedup Strategy

All 4 providers have usable native transaction IDs:

| Provider | Native ID field | dedup_key example |
|----------|----------------|-------------------|
| Plaid | `investment_transaction_id` | `"abc123def456"` |
| SnapTrade | `id` | `"st_789xyz"` |
| IBKR Flex | `tradeID` (prefixed as `ibkr_flex_{tradeID}`) | `"ibkr_flex_12345"` |
| Schwab | `activityId` (fallback: `transactionId`, `id`) | `"schwab_98765"` |

Sources: `ibkr/flex.py:383`, `providers/normalizers/schwab.py:923`

All upserts use `ON CONFLICT (user_id, provider, dedup_key) DO UPDATE`. Native IDs guarantee stability across re-ingestion — no hash collision risk for same-day same-symbol fills.

For `provider_flow_events`: dedup uses `(user_id, provider, transaction_id)` with the provider-native ID. The `provider_row_fingerprint` (content-based SHA256 from `providers/flows/common.py:178`) is stored for audit but NOT used as the primary dedup key, since content changes (provider corrections) should update the existing row, not insert a duplicate.

## FIFO Dict Contract

The `normalized_transactions` schema must faithfully reconstruct the FIFO dict that `FIFOMatcher.process_transactions()` expects (`trading_analysis/fifo_matcher.py:360`):

| Field | Type | Column | Notes |
|-------|------|--------|-------|
| `symbol` | str | `symbol` | |
| `type` | str | `trade_type` | BUY/SELL/SHORT/COVER |
| `date` | datetime | `transaction_date` | |
| `quantity` | float | `quantity` | Always positive |
| `price` | float | `price` | |
| `fee` | float | `fee` | Default 0.0 |
| `currency` | str | `currency` | Default USD |
| `source` | str | `provider` | |
| `transaction_id` | str | `transaction_id` | |
| `account_id` | str | `account_id` | |
| `account_name` | str | `account_name` | |
| `_institution` | str | `institution` | Mapped on read |
| `instrument_type` | str | `instrument_type` | Default "equity" |
| `contract_identity` | dict/None | `contract_identity` JSONB | Multiplier, underlying, etc. |
| `is_option` | bool | `is_option` | Used by option symbol parsing |
| `is_futures` | bool | `is_futures` | Used by futures contract resolution |
| `option_expired` | bool | `option_expired` | **Required** by FIFOMatcher for zero-price validation (`fifo_matcher.py:415`) |

## Ingestion Pipeline

New module: **`inputs/transaction_store.py`** — `TransactionStore` class following `DatabaseClient` pattern (injected connection via `get_db_session()`, raw SQL via psycopg2 cursors, no ORM).

### Ingest flow (called explicitly via MCP tool)

```
1. Create ingestion_batch record (status='ingesting')
2. Call existing fetch_transactions_for_source() — reuse all provider fetchers as-is
3. For each raw row: extract provider-native ID as dedup_key, UPSERT into raw_transactions
4. Store plaid_securities if Plaid provider
5. Update batch (status='normalizing', raw_row_count)
6. Run existing normalizers on raw data → normalized trades + income + flow events
7. UPSERT into normalized_transactions, normalized_income, provider_flow_events
8. Update batch (status='complete', normalized_row_count, completed_at)
```

Key: **reuses all existing fetchers and normalizers unchanged**. The store wraps them, not replaces them.

### Existing normalizers (reused as-is)

| Normalizer | File | Provider |
|------------|------|----------|
| `PlaidNormalizer` | `providers/normalizers/plaid.py` | Plaid |
| `SchwabNormalizer` | `providers/normalizers/schwab.py` | Schwab |
| `IBKRFlexNormalizer` | `providers/normalizers/ibkr_flex.py` | IBKR Flex |
| `SnapTradeNormalizer` | `providers/normalizers/snaptrade.py` | SnapTrade |

All output the same normalized shape: `(trades: list[NormalizedTrade], income: list[NormalizedIncome], fifo_transactions: list[dict])`.

Normalizers accept per-provider row lists (not a full `TransactionPayload`). Plaid normalizer additionally requires `security_lookup` dict (built from `plaid_securities` table). Confirmed at: `trading_analysis/analyzer.py:433-438`.

### Read path (for analysis — Phase 2)

New function: `load_transactions_from_store(user_id, source, institution, account)`
- Returns `(fifo_transactions: list[dict], income_events: list[NormalizedIncome], fetch_metadata: list[dict])`
- Same shapes that `TradingAnalyzer` currently produces
- Reconstructs `fifo_transactions` dicts from `normalized_transactions` columns (see FIFO Dict Contract above)
- Reconstructs `FetchMetadata` from latest `ingestion_batches` per provider/account

## Integration with Analysis Pipeline (Phase 2)

### All `fetch_transactions_for_source()` call sites (10 production callers)

| File | Lines | Context |
|------|-------|---------|
| `core/realized_performance_analysis.py` | 3216, 3223 | Main analysis (institution-scoped + consolidated) |
| `core/realized_performance_analysis.py` | 5295, 5302 | Account-aggregated prefetch for `_discover_account_ids()` |
| `mcp_tools/trading_analysis.py` | 102, 109 | `get_trading_analysis()` MCP tool |
| `mcp_tools/tax_harvest.py` | 118, 125 | `suggest_tax_loss_harvest()` MCP tool |
| `run_trading_analysis.py` | 122 | CLI diagnostic tool |
| `tests/diagnostics/diagnose_realized.py` | 65 | Diagnostic script |

Phase 2 targets the first 4 callers (realized perf). Phase 3 extends to trading_analysis and tax_harvest MCP tools.

### Feature-flagged integration

**File**: `core/realized_performance_analysis.py` lines 3216-3289

Current:
```python
fetch_result = fetch_transactions_for_source(user_email, source, institution, account)
payload = fetch_result.payload
analyzer = TradingAnalyzer(plaid_transactions=..., schwab_transactions=..., ...)
fifo_transactions = list(analyzer.fifo_transactions)
```

New (feature-flagged):
```python
if TRANSACTION_STORE_ENABLED:
    fifo_transactions, income_events, fetch_metadata_rows = load_transactions_from_store(
        user_id, source, institution, account
    )
    provider_flow_events_raw = load_provider_flows_from_store(user_id, source, institution, account)
else:
    # existing live-fetch path unchanged
    fetch_result = fetch_transactions_for_source(...)
    analyzer = TradingAnalyzer(...)
    fifo_transactions = list(analyzer.fifo_transactions)
```

Everything downstream of `fifo_transactions` stays the same — FIFO matching, NAV computation, TWR, all untouched.

All `TransactionStore` methods are scoped by `user_id` in every query (consistent with `DatabaseClient` pattern in `inputs/database_client.py`). MCP tools resolve `user_id` from `user_email` before calling store methods.

## Phases

### Phase 1: Schema + Full Ingest Pipeline ✅ COMPLETE (`6f2ae001`, `a8f47dc1`)
- Migration: `database/migrations/20260303_add_transaction_store.sql` — 6 tables, 28 indexes, 6 triggers
- Module: `inputs/transaction_store.py` (1,199 lines) — TransactionStore class
- MCP tools: `mcp_tools/transactions.py` — `fetch_provider_transactions()`, `list_transactions()`
- Tests: `tests/inputs/test_transaction_store.py` — 7 tests, 170 total pass
- **Live validation**: All 3 providers ingested (Schwab 348/101, IBKR 259/77, Plaid 127/58). Re-ingest idempotent. GLBE RECEIVE_AND_DELIVER gap confirmed via store query.

### Phase 2: Read Path Integration
- Methods: `load_transactions_from_store()`, `load_provider_flows_from_store()`
- Feature flag: `TRANSACTION_STORE_ENABLED` in `settings.py`
- Modify `_analyze_realized_performance_single_scope()` + account-aggregated prefetch to read from store
- **Value**: Analysis reads from store. Deterministic, fast, no API calls.

### Phase 3: MCP Tools + Cleanup
- Extend store read path to `get_trading_analysis()` and `suggest_tax_loss_harvest()` MCP tools
- `refresh_transactions(provider)` — explicit re-ingest with diff reporting
- `inspect_transaction(id)` — view raw + normalized side-by-side
- `list_ingestion_batches()` — audit trail
- Remove feature flag, make store the default
- **Value**: Full workflow. Ingest → inspect → analyze.

## Key Files

| File | Role |
|------|------|
| `database/migrations/20260303_add_transaction_store.sql` | NEW — schema migration |
| `inputs/transaction_store.py` | NEW — TransactionStore class (CRUD + ingest orchestration) |
| `mcp_tools/transactions.py` | NEW — MCP tools (ingest, list) |
| `inputs/database_client.py` | REFERENCE — pattern to follow for TransactionStore |
| `trading_analysis/data_fetcher.py` | READ — existing fetch pipeline, reused by ingest |
| `trading_analysis/analyzer.py` | READ — TradingAnalyzer, reused by normalize step |
| `providers/normalizers/*.py` | READ — 4 existing normalizers, reused unchanged |
| `providers/flows/common.py` | READ — ProviderFlowEvent/FetchMetadata schemas |
| `providers/flows/schwab.py`, `plaid.py`, `snaptrade.py`, `ibkr_flex.py` | READ — flow extractors, reused by ingest |
| `core/realized_performance_analysis.py` | MODIFY (Phase 2) — feature-flag branch at lines 3216-3289 + 5295-5302 |
| `mcp_tools/trading_analysis.py` | MODIFY (Phase 3) — store read path at lines 102-109 |
| `mcp_tools/tax_harvest.py` | MODIFY (Phase 3) — store read path at lines 118-125 |
| `settings.py` | MODIFY (Phase 2) — add `TRANSACTION_STORE_ENABLED` flag |

## Codex Review Findings

### R1: Schema unique constraints — ADDRESSED
Original plan said IBKR/Schwab have no native IDs. **Wrong.** IBKR Flex has `tradeID` (prefixed as `ibkr_flex_{tradeID}`, `ibkr/flex.py:383`). Schwab has `activityId` (fallback chain, `providers/normalizers/schwab.py:923`). Updated dedup strategy to use native IDs for all 4 providers.

### R2: Dedup hash collisions — ADDRESSED
No longer using SHA256 hashes. All providers use native transaction IDs as dedup keys. Two same-day fills of the same stock at the same price will have different `tradeID`/`activityId` values.

### R3: Normalizer reuse — PASS
Normalizers accept per-provider row lists. `PlaidNormalizer.normalize()` takes `(plaid_transactions, security_lookup)`. Others take their respective row lists. No full `TransactionPayload` dict required.

### R4: FIFO dict reconstruction — ADDRESSED
Added missing fields to schema: `is_option` BOOLEAN, `is_futures` BOOLEAN, `option_expired` BOOLEAN. `option_expired` is **required** by `FIFOMatcher` for zero-price option expiry handling (`fifo_matcher.py:415`). Full FIFO Dict Contract table added to plan.

### R5: Provider flow fingerprint dedup — ADDRESSED
Changed flow event dedup from content-based `provider_row_fingerprint` to `(user_id, provider, transaction_id)` using provider-native IDs. Fingerprint is still stored for audit but not used as primary dedup key. Provider corrections now UPDATE existing rows instead of inserting duplicates.

### R6: Multi-user isolation — ADDRESSED
All `TransactionStore` methods require `user_id` parameter and include it in every query WHERE clause. MCP tools resolve `user_id` from `user_email` before calling store. Consistent with existing `DatabaseClient` pattern.

### R7: Migration safety — ADDRESSED
Migration uses idempotent DDL: `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`. Consistent with existing migrations (`003_target_allocations.sql`, `20260302_add_workflow_actions.sql`).

### R8: Integration coverage — ADDRESSED
All 10 production call sites of `fetch_transactions_for_source()` documented. Phase 2 covers realized perf (4 sites). Phase 3 extends to trading_analysis + tax_harvest MCP tools (4 sites). CLI/diagnostic tools (2 sites) remain on live-fetch path.

### Overall: PASS after addressing R1, R2, R4, R5, R6, R7, R8

## Verification

### Phase 1
```bash
# Apply migration
psql -d risk_module_db -f database/migrations/20260303_add_transaction_store.sql

# Ingest via MCP
fetch_provider_transactions(provider="schwab")
fetch_provider_transactions(provider="ibkr_flex")
fetch_provider_transactions(provider="plaid")

# Verify raw rows
SELECT provider, count(*), min(transaction_date), max(transaction_date) FROM raw_transactions GROUP BY provider;

# Verify normalized rows
SELECT provider, trade_type, count(*) FROM normalized_transactions GROUP BY provider, trade_type;

# Debug query: check Schwab RECEIVE_AND_DELIVER
SELECT raw_data->>'action' as action, raw_data->>'symbol' as symbol
FROM raw_transactions WHERE provider='schwab' AND raw_data->>'action' LIKE '%RECEIVE%';

# Re-ingest should be idempotent (same row count)
fetch_provider_transactions(provider="schwab")
SELECT count(*) FROM raw_transactions WHERE provider='schwab';  -- same as before
```

### Phase 2
```bash
# Run with store enabled, compare against live fetch
TRANSACTION_STORE_ENABLED=true get_performance(mode='realized', institution='schwab')
TRANSACTION_STORE_ENABLED=false get_performance(mode='realized', institution='schwab')

# Unit tests
python3 -m pytest tests/inputs/test_transaction_store.py tests/core/test_realized_performance_analysis.py -x -q
```

## Risk Assessment

**Low risk for Phase 1**: Pure additions — new tables, new module, new MCP tools. Zero changes to existing analysis code.

**Medium risk for Phase 2**: Modifying the analysis read path. Mitigated by feature flag. The downstream interface (list of FIFO dicts) doesn't change.

**Phase 1 is the priority** — delivers the core value (persistent, inspectable data) with zero risk to existing functionality.

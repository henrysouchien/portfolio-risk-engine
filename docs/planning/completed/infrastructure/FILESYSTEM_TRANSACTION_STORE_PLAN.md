# Filesystem Transaction Store Plan (v2)
**Status:** DONE — Phase A (`cb9ba87f`), Phase B (`1699a83d`)

## Context

CSV-imported positions already work end-to-end via `CSVPositionProvider` (filesystem JSON at `~/.risk_module/positions.json`). But transaction-dependent tools (trading analysis, tax harvest, realized performance) currently require either live broker APIs or a Postgres-backed `TransactionStore`. This blocks zero-infrastructure onboarding.

The goal: let users import transaction CSVs (brokerage statements) and have them flow through the same analysis pipeline that DB-backed transactions use — without Postgres.

**Pre-requisite (done):** Parser + normalizer for IBKR statement CSVs: `inputs/importers/ibkr_statement.py` and `providers/normalizers/ibkr_statement.py`.

## Two-Phase Approach

### Phase A: Storage Layer + MCP Import Tool
Build the filesystem store and import tool as standalone components. Users can import, list, and clear transaction data. No caller site changes yet.

### Phase B: Analysis Pipeline Integration
Wire stored transactions into trading analysis, tax harvest, and realized performance. Requires source validation updates, source-aware routing, and realized perf engine changes.

---

## Phase A — Storage + Import Tool

### New Files

**1. `providers/csv_transactions.py`** — Filesystem-backed transaction store
- Mirror `providers/csv_positions.py` (158 lines)
- Storage: `~/.risk_module/transactions.json` (respects `RISK_MODULE_DATA_DIR`)
- Same locking pattern: `fcntl.flock` + `tempfile.mkstemp` + `os.replace`
- **Source key convention**: Use the provider name as source key (e.g., `ibkr_statement`), NOT brokerage+label slugs. This ensures Phase B can route `source="ibkr_statement"` directly to the matching stored data without translation. For multiple imports of the same provider, use `ibkr_statement` (latest wins — replace, not append). If we later need multi-account, extend to `ibkr_statement_{account_id}`.
- Schema:
  ```json
  {
    "schema_version": 1,
    "sources": {
      "ibkr_statement": {
        "imported_at": "2026-03-11T...",
        "provider": "ibkr_statement",
        "brokerage_name": "Interactive Brokers",
        "institution": "Interactive Brokers",
        "source_file": "U2471778_20260101_20260309/tables",
        "account_id": "U2471778",
        "period_start": "2026-01-01",
        "period_end": "2026-03-09",
        "fifo_transactions": [...],
        "income_events": [...],
        "provider_flow_events": [],
        "fetch_metadata": [
          {
            "provider": "ibkr_statement",
            "institution": "Interactive Brokers",
            "account_id": "U2471778",
            "statement_cash": {
              "ending_cash_usd": 12345.67,
              "period_end": "2026-03-09"
            }
          }
        ]
      }
    }
  }
  ```
  Note: `fetch_metadata` is a list (matching `load_from_store` contract). `statement_cash.ending_cash_usd` is derived from the parser's `cash_report` section ("Ending Cash" row, `total` column) at import time. `statement_cash.period_end` comes from the parser's `period` field. The engine reads `period_end` from inside `statement_cash` (not at the top level) per `engine.py:2182`. `stmtfunds_section_present` is NOT stored — the IBKR statement CSV parser doesn't have a StmtFunds section equivalent. Phase B must handle this (the engine checks it at `engine.py:714` but falls back gracefully when absent).
- Methods:
  - `save_transactions(user_email, source_key, data, metadata)` — atomic write
  - `load_transactions(user_email, source_key)` → raw source dict (no assembly into pipeline shape yet — Phase B)
  - `list_sources(user_email)` → summary list
  - `clear_source(user_email, source_key)` → remove one or all
  - `has_source(user_email, source_key)` → bool (Phase B guard: checks if specific source exists, not just "any")
- Note: `_resolve_path()` ignores `user_email` (same as `CSVPositionProvider` — single-user local tool)

**2. `mcp_tools/import_transactions.py`** — MCP tool (import/list/clear)
- Mirror `mcp_tools/import_portfolio.py` (250 lines)
- Actions: `import` (dry_run default), `list`, `clear`
- Import flow:
  1. `file_path` must point to the directory containing materialized `*__all.csv` tables (e.g., `U2471778_20260101_20260309/tables/`). The parser reads `trades__all.csv`, `interest__all.csv`, etc. from this directory.
  2. Parse via `inputs/importers/ibkr_statement.parse_ibkr_statement(csv_dir)` → returns dict with trades, interest, dividends, fees, cash_report, instrument_info, account_id, period
  3. Flatten via `inputs/importers/ibkr_statement.flatten_for_store(parsed, account_id)` → flat rows with `_row_type` discriminator
  4. Normalize via `providers/normalizers/ibkr_statement.IBKRStatementNormalizer().normalize(flattened)` → returns `(trades, income_events, fifo_transactions)`. The normalizer **already emits FIFO transactions** (no TradingAnalyzer needed).
  5. Store `fifo_transactions` (already plain dicts from normalizer) and `income_events` (serialize `NormalizedIncome` dataclass objects to dicts via `dataclasses.asdict()`). The `trades` (NormalizedTrade objects) are intermediate — they produce the `fifo_transactions` and are NOT stored separately. **JSON serialization note**: `fifo_transactions` contain `datetime` values (e.g., `date` field) that are not JSON-serializable. The save path must use a custom JSON encoder or convert datetimes to ISO strings before `json.dump()`. Same for `NormalizedIncome.date`. Pattern: `default=str` or explicit `.isoformat()` conversion.
  6. Build `fetch_metadata` from parsed data:
     - `ending_cash_usd`: from `cash_report` rows, filter `currency_summary == "Ending Cash"` and `currency == "Base Currency Summary"`, read `total` field
     - `period_end`: from parsed `period` dict (parser returns `{"start_date": ..., "end_date": ...}` — use `period["end_date"]`)
     - `account_id`, `provider`, `institution`: from parsed `account_id` + constants
  7. Save to `CSVTransactionProvider` with source_key = provider name (e.g., `ibkr_statement`)
- Preview (dry_run=true): trade count, income count, date range, top 5 FIFO transaction dicts (already plain dicts with datetime→string conversion applied). Preview does NOT include NormalizedTrade/NormalizedIncome objects — only serialized summary data.
- Detection: try each available statement parser (currently just IBKR) — extensible later
- `brokerage` parameter for explicit parser selection

**3. `tests/providers/test_csv_transactions.py`** — Unit tests
- Storage round-trip (save + load + list + clear)
- Atomic write safety
- Schema validation

**4. `tests/mcp_tools/test_import_transactions.py`** — Import tool tests
- Dry run preview
- Import + list + clear lifecycle
- Parser detection

### Modified Files

**5. `mcp_server.py`** — Register `import_transaction_file` MCP tool

### Phase A does NOT:
- Modify any caller sites (trading_analysis, tax_harvest, realized_perf)
- Import from `inputs/transaction_store.py` (avoids psycopg2 transitive dependency)
- Add `ibkr_statement` as a recognized source in validation lists
- Build a `StoreBackedIncomeProvider` equivalent (deferred to Phase B)

### Phase A Verification
1. `pytest tests/providers/test_csv_transactions.py tests/mcp_tools/test_import_transactions.py`
2. Live MCP test: `import_transaction_file(file_path=..., dry_run=true)` → inspect preview
3. Live MCP test: `import_transaction_file(file_path=..., dry_run=false)` → `import_transaction_file(action="list")` → `import_transaction_file(action="clear")`
4. `pytest tests/` — no regressions

---

## Phase B — Analysis Pipeline Integration (separate implementation)

### Key Problems to Solve (from Codex review)

1. **Source-aware routing**: The guard can't be "any CSV exists" — must check if the requested `source` matches an imported CSV source. E.g., `source="ibkr_statement"` should hit CSV; `source="schwab"` should not.

2. **`ibkr_statement` as recognized source**: See "Phase B Source Validation Sites" section above for complete list (10+ sites).

3. **StoreBackedIncomeProvider**: Can't import from `inputs/transaction_store.py` (pulls in psycopg2). **Decision: option (b)** — build a lightweight `CSVIncomeProvider` in `providers/csv_transactions.py` that converts income dicts → `NormalizedIncome` objects directly (parse dates with `datetime.fromisoformat()`, floats with `float()`) without depending on `TransactionStore` static methods. Same interface: `.income_events` list + `.analyze_income()` method.

4. **Return shape assembly**: `load_transactions()` needs to assemble the `load_from_store()` contract:
   ```python
   {
       "fifo_transactions": [...],
       "futures_mtm_events": [],
       "flex_option_price_rows": [],
       "provider_flow_events": [...],
       "fetch_metadata": [...],
       "income_provider": <income provider instance>,
   }
   ```

5. **Realized performance engine**: See "Phase B Realized-Perf Specifics" section above for complete list of hardcoded `ibkr_flex` sites that need broadening.

6. **`fetch_metadata` contract**: Phase A stores `fetch_metadata` as a list with `statement_cash.ending_cash_usd` and `statement_cash.period_end` (matching engine's read path at `engine.py:2126-2182`). `stmtfunds_section_present` is NOT available from statement CSVs — engine falls back gracefully.

7. **Holdings/source attribution**: Hardcoded `ibkr_flex` checks in `holdings.py` and `aggregation.py` need broadening. `providers/routing.py` family aliasing alone is insufficient — direct string comparisons must also accept `ibkr_statement`.

8. **Mixed-mode `source="all"`**: CSV-only users won't have live providers. Mixed users use explicit source selection.

### Phase B Caller Ordering

The DB store (`load_from_store`) only handles known providers (`plaid`, `schwab`, `ibkr_flex`, `snaptrade`) — it will return empty results for `source="ibkr_statement"`. So the elif ordering works correctly: DB path runs first but finds nothing for CSV-imported sources, then filesystem path catches it. However, for clarity and to avoid the unnecessary DB round-trip, the guard should be:
```python
if csv_store.has_source(user, source):
    # filesystem path (check first — fast, no DB)
elif TRANSACTION_STORE_READ and is_db_available():
    # DB store path
else:
    # direct API fetch
```

### Phase B Caller Sites (3+1)

| File | Line | Pattern |
|------|------|---------|
| `mcp_tools/trading_analysis.py` | 109 | `if csv_has ... elif DB_STORE ... else API_FETCH` |
| `mcp_tools/tax_harvest.py` | 125 | Same pattern in `_load_fifo_data()` |
| `core/realized_performance/aggregation.py` | 84 | Same pattern |
| `core/realized_performance/engine.py` | 348 | Additional store path (Codex found this) |

### Phase B Source Validation Sites (complete list)

All sites that reject unknown source values and need `ibkr_statement` added:
- `mcp_tools/trading_analysis.py:76`
- `mcp_tools/tax_harvest.py:809,855`
- `mcp_tools/performance.py:50,441`
- `services/performance_helpers.py:27`
- `services/portfolio_service.py:732`
- `routes/realized_performance.py:26`
- `core/realized_performance/engine.py:297`
- `core/realized_performance/aggregation.py:1416`
- `mcp_server.py` (source enum in tool schemas: ~L726, ~L818, ~L1774)
- `trading_analysis/data_fetcher.py:978`
- `providers/routing.py` (provider family: `ibkr_statement` in same family as `ibkr_flex`)
- `settings.py:131` — `REALIZED_PROVIDER_FLOW_SOURCES` default must include `ibkr_statement` (otherwise `engine.py:804` filters out statement metadata before cash-anchor extraction)
- `scripts/run_trading_analysis.py:104` — CLI `--source` argparse choices
- `tests/unit/test_mcp_server_contracts.py:43,58` — source-enum assertions in contract tests
- `tests/trading_analysis/test_provider_routing.py:597` — invalid-source assertion
- `core/risk_orchestration.py:940,1020` — CLI `--source` argparse choices and docs

### Phase B Realized-Perf Specifics

- `mcp_tools/performance.py:148` — `mode="realized"` hard-fails when DB unavailable; must allow filesystem-backed transactions to bypass this gate
- `settings.py:131` — `REALIZED_PROVIDER_FLOW_SOURCES` must include `ibkr_statement` (gate for `engine.py:804` metadata filtering)
- `engine.py:804` — metadata filtered by `REALIZED_PROVIDER_FLOW_SOURCES` before cash extraction
- `engine.py:2124` — `_statement_cash_from_metadata()` filters by `provider == "ibkr_flex"` → must accept `ibkr_statement`
- `engine.py:2175` — cash anchor gated on `source == "ibkr_flex"` → must accept `ibkr_statement`
- `holdings.py:243,260,268,350,353` — source-scoped holdings hardcoded to `ibkr_flex` → must accept `ibkr_statement`
- `aggregation.py:1396` — source attribution → must accept `ibkr_statement`
- `nav.py:305,321`, `engine.py:1128` — option multiplier logic special-cases `ibkr_flex` → must accept `ibkr_statement` (normalizer already emits per-contract option pricing)

### Phase B Verification

**Prerequisite**: CSV positions must also be imported (via `import_portfolio`) for tax harvest and realized performance — those tools require current positions alongside transactions.

1. Import IBKR statement → `get_trading_analysis(source="ibkr_statement")` → trades appear
2. Import IBKR positions + statement → `suggest_tax_loss_harvest(source="ibkr_statement")` → lots appear
3. Import IBKR positions + statement → `get_performance(mode="realized", source="ibkr_statement")` → returns with cash anchor
4. `pytest tests/` — no regressions

---

## Reference Files

| File | Purpose |
|------|---------|
| `providers/csv_positions.py` | Pattern to mirror (158 lines) |
| `mcp_tools/import_portfolio.py` | MCP tool pattern to mirror (250 lines) |
| `inputs/transaction_store.py:2179` | `load_from_store()` return shape contract |
| `inputs/transaction_store.py:2045` | `StoreBackedIncomeProvider` (has TransactionStore method deps) |
| `inputs/importers/ibkr_statement.py` | Parser (done) |
| `providers/normalizers/ibkr_statement.py` | Normalizer — returns `(trades, income, fifo)` directly (done) |
| `mcp_tools/trading_analysis.py:109` | Caller site 1 |
| `mcp_tools/tax_harvest.py:125` | Caller site 2 |
| `core/realized_performance/aggregation.py:84` | Caller site 3 |
| `core/realized_performance/engine.py:348` | Caller site 4 (Codex found) |

## Codex Review Findings Addressed

### Review 1 Findings
| Finding | Resolution |
|---------|------------|
| Import flow wrong — normalizer already emits FIFO | Fixed: use normalizer output directly, no TradingAnalyzer |
| `StoreBackedIncomeProvider` imports psycopg2 | Deferred to Phase B — build lightweight alternative |
| `_csv_transactions_available()` too broad | Phase B: `has_source(user, source_key)` checks specific source |
| `ibkr_statement` not recognized source | Phase B: add to 9+ validation sites (expanded list) |
| Realized perf engine.py:348 also needs branch | Phase B: added as caller site 4 |
| `fetch_metadata` needs `statement_cash` | Phase A stores it at import time; Phase B reads it |
| Mixed-mode `source="all"` | Phase B: explicit source selection |

### Review 2 Findings
| Finding | Resolution |
|---------|------------|
| Source key derived from brokerage+label doesn't align with Phase B routing | Fixed: use provider name as source key (e.g., `ibkr_statement`) |
| `has_sources()` still too broad | Fixed: `has_source(user, source_key)` — checks specific source |
| Realized-perf metadata hardcoded to `ibkr_flex` | Phase B: 6 specific sites listed in "Realized-Perf Specifics" |
| Holdings/source attribution only recognizes `ibkr_flex` | Phase B: direct string comparisons + routing.py family aliasing |
| Phase B validation list incomplete | Fixed: expanded to 10+ sites (added data_fetcher.py:978) |
| `fetch_metadata` schema inconsistent (object vs list) | Fixed: Phase A stores as list matching `load_from_store` contract |
| Parser expects `tables/` directory, not statement root | Documented: `file_path` points to materialized tables directory |

### Review 3 Findings
| Finding | Resolution |
|---------|------------|
| Import flow still said "brokerage+label" at one location | Fixed: all references now say provider name |
| "inspect" action mentioned but not defined | Fixed: removed "inspect" from description |
| `period_end` at wrong nesting level in fetch_metadata | Fixed: moved inside `statement_cash` to match `engine.py:2182` |
| `stmtfunds_section_present` not available from parser | Documented: not stored, engine falls back gracefully |
| DB store skips unknown providers → elif ordering | Fixed: reversed to check filesystem first, skip unnecessary DB round-trip |
| Phase B validation list still missing data_fetcher.py:978 | Fixed: added to complete list |
| Option multiplier ibkr_flex special-casing | Added to Phase B Realized-Perf Specifics: `nav.py:305`, `engine.py:1128` |
| holdings.py direct string comparisons need broadening | Added to Phase B: routing aliases alone insufficient |

### Review 4 Findings
| Finding | Resolution |
|---------|------------|
| More validation sites: tax_harvest:855, aggregation:1416, performance:50 | Added to complete list |
| NormalizedTrade vs fifo_transactions schema ambiguity | Clarified: store fifo_transactions (dicts), not trades (NormalizedTrade intermediate) |
| file_path/tables directory still ambiguous in import flow | Fixed: step 1 now specifies `*__all.csv` tables directory |
| `REALIZED_PROVIDER_FLOW_SOURCES` gate at settings.py:131 | Added to Phase B validation + realized-perf specifics |
| Phase B verification missing realized performance test | Added: `get_performance(mode="realized", source="ibkr_statement")` |

### Review 5 Findings
| Finding | Resolution |
|---------|------------|
| `performance.py:148` hard-fails mode=realized when no DB | Added to Phase B realized-perf specifics: bypass gate for filesystem |
| datetime values in fifo_transactions not JSON-serializable | Added JSON serialization note to Phase A import flow step 5 |
| `source_file` metadata vs `file_path` points at tables/ | Fixed: `source_file` now includes `/tables` suffix |

### Review 6 Findings
| Finding | Resolution |
|---------|------------|
| `ending_cash_usd` derivation from cash_report ambiguous | Added: filter by `currency_summary=="Ending Cash"` + `currency=="Base Currency Summary"` |
| Dry-run preview needs JSON-safe shape | Added: preview uses serialized FIFO dicts only, no dataclass objects |
| Missing ibkr_flex checks: holdings.py:260,268 nav.py:321 | Added to realized-perf specifics |
| StoreBackedIncomeProvider choice unresolved | Resolved: option (b) — lightweight `CSVIncomeProvider` in csv_transactions.py |
| Verification needs positions as prerequisite | Added: prerequisite note for tax harvest and realized perf |

### Review 7 Findings
| Finding | Resolution |
|---------|------------|
| Test files with source-enum assertions need updating | Added: test_mcp_server_contracts.py:43,58 + test_provider_routing.py:597 |
| CLI scripts/run_trading_analysis.py:104 --source enum | Added to validation sites list |
| Phase A period_end from formatted string, but parser returns dict | Fixed: use `period["end_date"]` from parser dict |

### Review 8 Findings
| Finding | Resolution |
|---------|------------|
| `core/risk_orchestration.py:940,1020` CLI --source restriction | Added to validation sites list |

# Pluggable Transaction Normalizer + Agent-Driven Workflow

**Status**: APPROVED (Codex PASS — 14 review rounds)
**Created**: 2026-03-11

## Context

`import_transaction_file` currently only handles IBKR statement directories (`*__all.csv` tables). Users with Schwab, Fidelity, or other brokerage CSVs have no import path for transactions. The position import tool (`import_portfolio`) already has a pluggable normalizer system with auto-detection, user normalizer discovery, and `needs_normalizer` response — this plan replicates that pattern for transactions.

**Related plans**: `BROKERAGE_STATEMENT_IMPORT_PLAN.md` (DB-backed store, class-based normalizers — different system). `FILESYSTEM_TRANSACTION_STORE_PLAN.md` (Phase A+B done — the store we wire into). The Schwab action mappings from the BROKERAGE plan (Phase 2b) inform our built-in Schwab normalizer.

**Goal**: A user hands Claude any brokerage transaction CSV → Claude either auto-imports it (known format) or writes a normalizer on the fly (unknown format) → transactions are stored and importable. For built-in normalizers (`schwab_csv`), data flows directly into the analysis pipeline. For agent-written normalizers, import and storage work immediately; analysis pipeline queryability requires adding the source to the `Literal` enum (deferred to a future plan).

---

## Design Decisions

**D1: Mirror position normalizer pattern.** Module-based (`detect(lines)` + `normalize(lines, filename)`), NOT class-based. Agents write standalone `.py` files to `~/.risk_module/transaction_normalizers/`, matching the position normalizer UX.

**D2: Two input modes coexist.** Directory → existing IBKR path (unchanged). Single CSV file → pluggable normalizer protocol (new). The `import_transaction_file` tool accepts both.

**D3: Normalizer returns dicts, not dataclasses.** `TransactionNormalizeResult` contains `fifo_transactions: list[dict]` and `income_events: list[dict]` — plain dicts that serialize directly to JSON. User-written normalizers don't need to import domain dataclasses.

**D4: Schwab CSV as first built-in.** Proves the pattern, serves as reference for agent-written normalizers. Action mapping from `BROKERAGE_STATEMENT_IMPORT_PLAN.md` Phase 2b.

**D5: Source registration is required.** `source="all"` does NOT include CSV-imported transactions — it only queries live providers (Plaid, SnapTrade, IBKR Flex, Schwab). CSV data is only reachable when the exact `source` key matches via `CSVTransactionProvider.has_source()`. Therefore `schwab_csv` must be added to the source validation Literal enum and docstrings in `mcp_server.py` (3 tools: `get_trading_analysis`, `suggest_tax_loss_harvest`, `get_performance`) + `data_fetcher.py` source check + `services/portfolio_service.py`. Same pattern as the `ibkr_statement` Phase B rollout across 17+ sites.

**D6: Source key is `provider_name` (re-imports overwrite, single account scope).** The source key is `result.provider_name` (e.g., `schwab_csv`), matching the existing IBKR directory import pattern. Re-importing overwrites the previous import. This keeps the contract simple and matches the `Literal` enum — `source="schwab_csv"` maps directly to the stored key.

**Multi-account limitation**: Each Schwab CSV is for a single account. Users with multiple Schwab accounts should import the account they want to analyze. Re-importing a different account's CSV overwrites the previous one. Multi-account concurrent analysis is out of scope — it requires composite storage keys and per-account scoping (future work, same limitation as `ibkr_statement`).

**D7: Alias resolution reads lowercase `provider_name` attribute.** The position normalizer helper `_normalizer_aliases()` reads `getattr(normalizer, "provider_name", "")` (lowercase). Transaction normalizer modules must expose `provider_name = "schwab_csv"` (lowercase attribute), not `PROVIDER_NAME`. The uppercase `BROKERAGE_NAME` constant is also read via `getattr`.

---

## New Files

### 1. `inputs/transaction_normalizer_schema.py` (~30 lines)

```python
@dataclass
class TransactionNormalizeResult:
    fifo_transactions: list[dict[str, Any]]       # same shape as IBKR FIFO output
    income_events: list[dict[str, Any]]           # serialized NormalizedIncome shape
    provider_flow_events: list[dict[str, Any]]    # cash flows (deposits/withdrawals) for realized perf
    errors: list[str]                             # fatal — import rejected if non-empty
    warnings: list[str]                           # informational
    brokerage_name: str                           # e.g., "Charles Schwab"
    institution: str                              # e.g., "charles_schwab"
    provider_name: str                            # source key, e.g., "schwab_csv"
    account_id: str = ""
    period_start: str = ""                        # ISO date
    period_end: str = ""                          # ISO date
    skipped_rows: int = 0
```

`provider_flow_events` is critical — the realized performance engine reads it from the store (`store_data.get("provider_flow_events")`) to handle cash flows that would otherwise distort return calculations.

### 2. `inputs/transaction_normalizers/__init__.py` (~90 lines)

Mirror `inputs/normalizers/__init__.py` exactly:

```python
class TransactionNormalizerModule(Protocol):
    def detect(self, lines: list[str]) -> bool: ...
    def normalize(self, lines: list[str], filename: str) -> TransactionNormalizeResult: ...

BUILT_IN: list[TransactionNormalizerModule] = [schwab_csv]

def detect_and_normalize(lines, filename) -> TransactionNormalizeResult | None:
    # first matching normalizer wins

def _all_normalizers() -> list:
    # built-in + user normalizers from ~/.risk_module/transaction_normalizers/*.py (filesystem-based, no DB dependency)

def _load_user_normalizers() -> list:
    # importlib.util.spec_from_file_location pattern, same as position normalizers
```

User normalizer directory: `~/.risk_module/transaction_normalizers/` (separate from position normalizers).

### 3. `inputs/transaction_normalizers/schwab_csv.py` (~180 lines)

Built-in Schwab CSV normalizer. Module-level attributes for alias matching (read by `_txn_normalizer_aliases()` via `getattr()`):
```python
BROKERAGE_NAME = "Charles Schwab"
INSTITUTION = "charles_schwab"
provider_name = "schwab_csv"       # lowercase — matches import_portfolio pattern
```

**Detection**: Check header line matches the exact Schwab 8-column signature: `"Date","Action","Symbol","Description","Quantity","Price","Fees & Comm","Amount"`. All 8 columns must be present in the first non-empty line. This is a strong enough signature to prevent false positives from other brokerages with generic column names. The `"Fees & Comm"` column name is Schwab-specific.

**Action classification** (from BROKERAGE_STATEMENT_IMPORT_PLAN.md Phase 2b):
- Trade → FIFO: `Buy` (→ BUY), `Sell` (→ SELL), `Sell Short` (→ SHORT), `Buy to Cover` (→ COVER), `Reinvest Shares` (→ BUY)
- Income → dividend: `Qualified Dividend`, `Non-Qualified Div`, `Cash Dividend`, `Reinvest Dividend`, `Pr Yr Non Qual Div`, `Long Term Cap Gain`, `Short Term Cap Gain`, `Foreign Tax Paid` (negative dividend — preserves sign)
- Income → interest: `Margin Interest`, `Bank Interest`, `Bond Interest`
- Flow events → `provider_flow_events`: `MoneyLink Transfer`, `Funds Received`, `Wire Funds`, `Journal` (cash flows needed for realized performance return calculations)

**Note**: `Cash Back Rewards` appears as a Description on `Funds Received` rows, not as a standalone Action. All `Funds Received` rows are captured as flow events regardless of description.

**Flow event dict shape** (matches `ProviderFlowEvent` TypedDict in `providers/flows/common.py`):
```python
{
    "date": datetime,                      # parsed transaction date
    "timestamp": datetime,                 # same as date (no intraday precision)
    "event_day_utc": date,                 # date portion
    "amount": float,                       # positive = inflow, negative = outflow
    "currency": "USD",
    "flow_type": str,                      # see classification below
    "is_external_flow": bool,              # see classification below
    "provider": "schwab_csv",              # engine filters by provider field
    "institution": "charles_schwab",
    "account_id": None,
    "account_name": None,
    "provider_account_ref": None,
    "transaction_id": str,                 # stable hash for dedup
    "confidence": "medium",                # conservative — CSV lacks metadata that live API provides
    "raw_type": str,                       # original Action value
    "raw_subtype": "",
    "raw_description": str,                # original Description value
    "provider_row_fingerprint": str,       # content hash for dedup
    "transfer_cash_confirmed": False,      # conservative default — no confirmation signal in CSV
}
```

**Flow event classification** (aligns with `providers/flows/schwab.py` semantics):
- `MoneyLink Transfer` → `flow_type="contribution"` or `"withdrawal"` (by amount sign), `is_external_flow=True` (known ACH)
- `Wire Funds` → `flow_type="contribution"` or `"withdrawal"` (by amount sign), `is_external_flow=True` (known external wire)
- `Funds Received` → `flow_type="contribution"`, `is_external_flow=True` (ACH deposit)
- `Journal` → `flow_type="transfer"`, `is_external_flow=False` (internal movement between accounts)

**Critical**: The realized performance engine at `engine.py:838` filters stored flow rows by `provider` field. The `flow_type` field (not `type`) is used for classification. `is_external_flow` controls whether the flow adjusts NAV for return calculations — internal movements must NOT be flagged as external or performance attribution will be skewed.

**Schwab-specific parsing**:
- Date: `"MM/DD/YYYY"` or `"MM/DD/YYYY as of MM/DD/YYYY"` (use first date)
- Amount: strip `$`, `,`, handle `"-$..."` prefix
- Quantity/Price: plain float, may be empty
- Reinvest Shares → BUY trade (quantity + price from row)
- Reinvest Dividend → income event (amount from row)
- Foreign Tax Paid → negative dividend income event (preserve sign, `income_type="dividend"`)
- Margin Interest → interest income on symbol "CASH" (preserve negative sign, `income_type="interest"`)

**FIFO dict output shape** (matches IBKR normalizer output — note SHORT/COVER types for short sales):
```python
{
    "symbol": str, "type": "BUY"|"SELL"|"SHORT"|"COVER", "date": datetime,
    "quantity": float, "price": float, "fee": float,
    "currency": "USD", "source": "schwab_csv",
    "account_id": "", "_institution": "charles_schwab",
    "instrument_type": "equity", "is_option": False, "is_futures": False,
    "contract_identity": None, "multiplier": 1,
    "broker_cost_basis": None, "broker_pnl": None,
    "transaction_id": None, "option_expired": False,
    "option_exercised": False, "stock_from_exercise": False,
    "underlying": str | None, "exercise_code": None, "account_name": "",
}
```

### 4. `inputs/transaction_normalizers/_example.py` (~100 lines)

Reference normalizer (not loaded — `_` prefix). Fully commented skeleton showing the protocol, detect pattern, normalize pattern, and expected dict shapes. The `needs_normalizer` response points agents to this file.

---

## Modified Files

### 5. `mcp_tools/import_transactions.py` (~100 lines added)

**a) Accept single CSV files.** Replace the hard `is_dir()` gate:
```python
# Current: rejects non-directories
# New: if path.is_file() → _import_single_csv(); if path.is_dir() → existing IBKR path
```

**b) Add normalizer resolution helpers** (mirror `import_portfolio.py`):
- `_available_txn_normalizers()` — wraps `_all_normalizers()`
- `_txn_normalizer_aliases(normalizer)` — slugified module name, BROKERAGE_NAME, provider_name
- `_resolve_requested_txn_normalizer(brokerage)` — explicit brokerage → normalizer lookup
- `_normalize_txn_lines(lines, filename, brokerage)` — if brokerage → resolve, else auto-detect
- `_needs_txn_normalizer_response(lines, brokerage)` — `{status: "needs_normalizer", first_20_lines, row_count, message}` pointing to `_example.py`

**c) `_import_single_csv()` function:**
- Read file lines
- Run through `_normalize_txn_lines()` → if None, return `_needs_txn_normalizer_response()`
- If `result.errors` non-empty → return `{status: "error", errors: result.errors}`
- Build full payload for `CSVTransactionProvider.save_transactions()` by synthesizing fields the normalizer doesn't provide:
  ```python
  source_key = result.provider_name  # D6 — plain provider name, re-imports overwrite
  payload = {
      "provider": result.provider_name,
      "brokerage_name": result.brokerage_name,
      "institution": result.institution,
      "source_file": _source_file_label(path),            # synthesized from path
      "account_id": result.account_id,
      "period_start": result.period_start,
      "period_end": result.period_end,
      "fifo_transactions": _json_safe(result.fifo_transactions),
      "income_events": _json_safe(result.income_events),
      "provider_flow_events": _json_safe(result.provider_flow_events),  # from normalizer
      "fetch_metadata": [],                                # no statement-level metadata for single CSVs
  }
  metadata = {
      "imported_at": _utc_now_iso(),
      "provider": payload["provider"],
      "brokerage_name": payload["brokerage_name"],
      "institution": payload["institution"],
      "source_file": payload["source_file"],
      "account_id": payload["account_id"],
      "period_start": payload["period_start"],
      "period_end": payload["period_end"],
  }
  ```
- Dry run → preview (first 5 FIFO transactions); else → `provider.save_transactions(user, source_key, payload, metadata)`
- Response shape matches existing directory-mode response

### 6. `mcp_server.py` (~2 lines)

Update `import_transaction_file` docstring to mention single CSV file support.

---

## Source Validation — REQUIRED

`source="all"` does **NOT** include CSV-imported transactions. It only queries live providers. CSV data is reachable when the caller passes the source key that matches the stored provider name (e.g., `source="schwab_csv"`) via `CSVTransactionProvider.has_source()`. Therefore source registration is **mandatory** for imported data to be usable.

**Sites to update** (same pattern as `ibkr_statement` Phase B rollout):

1. **`mcp_server.py`** — Add `schwab_csv` to the `Literal` type annotation on `source` param for `get_trading_analysis`, `suggest_tax_loss_harvest`, `get_performance` (3 sites). Update docstrings.
2. **`tests/unit/test_mcp_server_contracts.py`** — Update 3 contract tests to include `schwab_csv` in expected Literal values.
3. **`trading_analysis/data_fetcher.py`** — Two changes:
   - Add `schwab_csv` to source validation set (line ~978): `{"snaptrade", "plaid", "ibkr_flex", "ibkr_statement", "schwab", "schwab_csv"}`
   - Add `schwab_csv` to the `provider is None` fallback (line ~985): `if source in {"ibkr_statement", "schwab_csv"}:` → return empty result (no live provider, CSV-only source)
4. **`services/portfolio_service.py`** — Add `schwab_csv` to source validation (line ~732).
5. **`mcp_tools/tax_harvest.py`** — Add `schwab_csv` to `valid_source` set (line ~865). **Known limitation**: wash-sale widening path reloads `source="all"` (line ~1015), which excludes CSV-imported data. This is a pre-existing limitation shared with `ibkr_statement` — not introduced by this plan. Future fix: make wash-sale widening also check CSV store sources.
6. **`mcp_tools/trading_analysis.py`** — Add `schwab_csv` to source acceptance. CSV store `has_source()` handles exact key lookup.
7. **`mcp_tools/performance.py`** — Same pattern for realized mode.
8. **`core/realized_performance/aggregation.py`** — Two changes:
   - Add `schwab_csv` to source validation (line ~1426).
   - Add `"schwab_csv": "schwab"` to `_SOURCE_TO_INSTITUTION` map (line ~1405). Without this, `source="schwab_csv"` bypasses Schwab-specific conflict checking, auto-institution scoping, and `use_per_symbol_inception=True`.
9. **`core/realized_performance/engine.py`** — Add `schwab_csv` to source validation (line ~302).
10. **`core/realized_performance/holdings.py`** — Three changes to add `schwab_csv` to all match tiers:
    - **Primary path** (line ~244 area): After `canonical_mapped` is added to `primary_matches`, check if the canonical provider is Schwab and expand: `if canonical_mapped == "schwab": primary_matches.update(SCHWAB_TRANSACTION_SOURCES)`. This mirrors line 248 where IBKR identity fields expand to `IBKR_TRANSACTION_SOURCES`. Without this, Schwab positions resolve to `primary_matches={"schwab"}` (returned at line 269 before tertiary is reached), and `source="schwab_csv"` fails the `source in matches` check at line 356.
    - **Tertiary path** (line ~267): `tertiary_matches.add("schwab")` → `tertiary_matches.update(SCHWAB_TRANSACTION_SOURCES)`
    - **Native sources** (line ~273): Add `SCHWAB_TRANSACTION_SOURCES` to native_sources: `native_sources = set(SCHWAB_TRANSACTION_SOURCES) | set(IBKR_TRANSACTION_SOURCES)`

    Import `SCHWAB_TRANSACTION_SOURCES` from `routing.py` (see site #12).
11. **`settings.py`** — Add `schwab_csv` to `REALIZED_PROVIDER_FLOW_SOURCES` default (line ~135): `"schwab,plaid,snaptrade,ibkr_flex,ibkr_statement,schwab_csv"`. Without this, flow events from Schwab CSV imports are silently ignored by the realized performance engine.
12. **`providers/routing.py`** — Five changes:
    - Add `schwab_csv` to `TRANSACTION_PROVIDERS` set (line ~41).
    - Add `schwab_csv` to `_CANONICAL_PROVIDERS` set (line ~42).
    - Add `"schwab csv": "schwab_csv"` to `_PROVIDER_NAME_ALIASES` (line ~44). This ensures `resolve_provider_token("schwab_csv")` → `"schwab_csv"`, which is needed for `_normalize_source_token()` → `secondary_matches` population in holdings.py.
    - Add `SCHWAB_TRANSACTION_SOURCES = frozenset({"schwab", "schwab_csv"})` (parallel to `IBKR_TRANSACTION_SOURCES`). Export in `__all__`.
    - Update `provider_family()` (line ~99): add `if normalized in SCHWAB_TRANSACTION_SOURCES: return "schwab"`. This ensures `provider_family("schwab_csv")` → `"schwab"`, which is used for family-based matching in holdings.py and leakage detection.
13. **`services/performance_helpers.py`** — Add `schwab_csv` to `source: Literal[...]` (line ~27).
14. **`routes/realized_performance.py`** — Add `schwab_csv` to `source: Literal[...]` in `RealizedPerformanceRequest` (line ~26).
15. **`core/risk_orchestration.py`** — Add `schwab_csv` to `--source` argparse choices (line ~1023).
16. **`scripts/run_trading_analysis.py`** — Add `schwab_csv` to CLI `--source` choices (line ~104).
17. **`tests/trading_analysis/test_provider_routing.py`** — Two changes:
    - Update existing source validation assertion (line ~597) to include `schwab_csv`.
    - Add `schwab_csv` test case for empty-payload path (mirrors existing `ibkr_statement` test at line ~605).
18. **Remaining sites** — `grep -r ibkr_statement` across the codebase and add `schwab_csv` wherever `ibkr_statement` appears in source validation sets. The Phase B commit (`1699a83d`) touched 17+ files — use that as the definitive checklist.

**Note on `IBKR_TRANSACTION_SOURCES`**: `schwab_csv` must NOT be added to this frozenset. It controls IBKR-specific behaviors (option multiplier suppression, statement cash anchoring). Schwab CSV transactions get the non-IBKR code path, which is correct (Schwab options need ×100 multiplier via `OPTION_MULTIPLIER_NAV_ENABLED`).

**For agent-written normalizers** (e.g., `fidelity_csv`): Dynamic source keys that are not in the `Literal` enum will be rejected by MCP client-side schema validation before reaching the server. This is a known limitation. The workaround for agent-written normalizers is to use `source="all"` (which won't include CSV data) and instead query via `import_transaction_file(action="list")` to verify imported data, then access it through the trading analysis pipeline by having the agent add the source to the Literal enum in a follow-up step. **Alternatively**, this is deferred to a future plan that introduces a separate free-form `source_key: str` parameter alongside the existing `source: Literal[...]` parameter. For this plan, the scope is limited to built-in normalizers (`schwab_csv`) which are in the Literal enum.

---

## Test Files

### 7. `tests/inputs/test_transaction_normalizer_registry.py` (~60 lines)
- `test_detect_and_normalize_returns_none_for_unknown` — random CSV, no match
- `test_detect_and_normalize_matches_schwab` — Schwab header, returns result
- `test_builtin_list_includes_schwab` — verify BUILT_IN
- `test_user_normalizer_loading` — temp file in mock user_dir
- `test_user_normalizer_missing_detect_skipped` — module without detect() skipped

### 8. `tests/inputs/test_schwab_csv_normalizer.py` (~140 lines)
Uses real Schwab CSV at `docs/Individual_XXX252_Transactions_20260310-171524.csv`:
- `test_detect_matches_schwab_csv` — detect returns True
- `test_detect_rejects_non_schwab` — IBKR lines, returns False
- `test_detect_rejects_similar_headers` — CSV with Date+Action columns but not full 8-column Schwab signature, returns False
- `test_normalize_produces_trades_and_income` — counts
- `test_sell_produces_fifo` — SHY Sell → type=SELL
- `test_sell_short_produces_short` — Sell Short → type=SHORT
- `test_buy_to_cover_produces_cover` — Buy to Cover → type=COVER
- `test_reinvest_shares_produces_buy` — Reinvest Shares → BUY
- `test_reinvest_dividend_produces_income` — dividend income event
- `test_qualified_dividend` — ENB dividends
- `test_foreign_tax_negative` — Foreign Tax Paid → negative dividend (income_type="dividend")
- `test_margin_interest` — Margin Interest → interest on CASH
- `test_flow_events_external` — MoneyLink Transfer, Wire Funds, Funds Received → `is_external_flow=True`, `flow_type="contribution"/"withdrawal"`
- `test_flow_events_internal` — Journal → `flow_type="transfer"`, `is_external_flow=False`
- `test_flow_events_conservative_defaults` — all flow events have `confidence="medium"`, `transfer_cash_confirmed=False`
- `test_date_parsing_as_of` — "MM/DD/YYYY as of MM/DD/YYYY"
- `test_amount_parsing` — "$1,234.56", "-$149.73"
- `test_period_range` — start/end from dates
- `test_errors_on_malformed_csv` — normalizer returns errors list for unparseable data

### 9. `tests/mcp_tools/test_import_transactions_csv.py` (~120 lines)
- `test_single_csv_dry_run` — Schwab CSV, dry_run=True
- `test_single_csv_import_and_list` — dry_run=False, verify in store
- `test_single_csv_with_brokerage_hint` — brokerage="schwab"
- `test_unknown_csv_returns_needs_normalizer` — random CSV
- `test_needs_normalizer_has_first_20_lines` — sample lines in response
- `test_directory_mode_unchanged` — existing IBKR directory works
- `test_nonexistent_file_error` — missing path
- `test_source_key_is_provider_name` — verify source_key is `schwab_csv`
- `test_reimport_overwrites` — second import overwrites first (same source_key)
- `test_normalizer_errors_returned` — normalizer with non-empty errors → error response
- `test_explicit_brokerage_schwab_csv_resolves` — brokerage="schwab_csv" resolves via alias
- `test_schwab_csv_source_validation` — `source="schwab_csv"` accepted by data_fetcher validation
- `test_schwab_csv_no_provider_empty_result` — data_fetcher returns empty payload when no live provider
- `test_flow_events_match_provider_flow_contract` — emitted flow dicts have all ProviderFlowEvent required fields
- `test_holdings_scoping_schwab_csv` — `source="schwab_csv"` correctly scopes to Schwab holdings (tests primary, secondary with `position_source="schwab_csv"`, and tertiary paths)
- `test_resolve_provider_token_schwab_csv` — `resolve_provider_token("schwab_csv")` → `"schwab_csv"` (add to `tests/providers/test_routing.py`, mirrors IBKR test at line ~225)
- `test_provider_family_schwab_csv` — `provider_family("schwab_csv")` → `"schwab"`

---

## Agent Workflow (end-to-end)

```
1. User: "Import my Fidelity transactions from ~/exports/fidelity.csv"

2. Agent calls import_transaction_file(file_path="~/exports/fidelity.csv")
   → {status: "needs_normalizer", first_20_lines: [...], message: "...write to ~/.risk_module/transaction_normalizers/fidelity.py..."}

3. Agent reads inputs/transaction_normalizers/_example.py for the protocol

4. Agent inspects the 20 sample lines, identifies columns and action types

5. Agent writes ~/.risk_module/transaction_normalizers/fidelity.py
   with detect(lines) and normalize(lines, filename)

6. Agent calls import_transaction_file(file_path="...", dry_run=true)
   → {status: "ok", trade_count: 23, income_count: 15, preview: [...]}

7. User confirms → Agent calls import_transaction_file(dry_run=false)
   → Transactions saved and verifiable via import_transaction_file(action="list").

   NOTE: This workflow demonstrates the import side. For built-in normalizers
   (schwab_csv), data is immediately queryable via get_trading_analysis(source="schwab_csv").
   For agent-written normalizers (fidelity_csv), import and storage work, but
   analysis pipeline queryability requires adding the source to the Literal enum
   AND all source validation sites (see Source Validation section) — this is a
   non-trivial follow-up, not just a Literal change.
```

---

## Implementation Order

1. `inputs/transaction_normalizer_schema.py` — standalone
2. `inputs/transaction_normalizers/__init__.py` — depends on 1
3. `inputs/transaction_normalizers/_example.py` — standalone reference
4. `inputs/transaction_normalizers/schwab_csv.py` — depends on 1
5. Register schwab_csv in `__init__.py` BUILT_IN list
6. `mcp_tools/import_transactions.py` modifications — depends on 2
7. Source validation: `mcp_server.py` (Literal enums + docstrings), `trading_analysis/data_fetcher.py`, `services/portfolio_service.py`, + remaining Phase B sites — add `schwab_csv` + dynamic source fallback
8. Tests (3 files)
9. `mcp_server.py` docstring update for single CSV support

---

## Verification

1. `pytest tests/inputs/test_transaction_normalizer_registry.py tests/inputs/test_schwab_csv_normalizer.py tests/mcp_tools/test_import_transactions_csv.py -v`
2. Live test: `import_transaction_file(file_path="docs/Individual_XXX252_Transactions_20260310-171524.csv", dry_run=true)` → Schwab auto-detected, preview shows trades + income
3. Live test: `import_transaction_file(file_path="docs/Individual_XXX252_Transactions_20260310-171524.csv", dry_run=false)` → saved
4. Live test: `get_trading_analysis(source="schwab_csv")` → includes Schwab trades (note: `source="all"` does NOT include CSV imports)
5. Live test: `get_performance(source="schwab_csv", mode="realized")` → returns performance data for Schwab CSV transactions
6. Live test: `suggest_tax_loss_harvest(source="schwab_csv")` → returns tax-loss harvest suggestions (or empty if no losses)
7. Live test: unknown CSV → `needs_normalizer` response
8. `pytest tests/` — no regressions

---

## Files Summary

| File | Action | Lines |
|------|--------|-------|
| `inputs/transaction_normalizer_schema.py` | CREATE | ~30 |
| `inputs/transaction_normalizers/__init__.py` | CREATE | ~90 |
| `inputs/transaction_normalizers/schwab_csv.py` | CREATE | ~180 |
| `inputs/transaction_normalizers/_example.py` | CREATE | ~100 |
| `mcp_tools/import_transactions.py` | MODIFY | ~120 added |
| `mcp_server.py` | MODIFY | ~15 (Literal enums + docstrings + single CSV mention) |
| `tests/unit/test_mcp_server_contracts.py` | MODIFY | ~3 (add `schwab_csv` to expected Literal values) |
| `trading_analysis/data_fetcher.py` | MODIFY | ~2 (source validation set) |
| `services/portfolio_service.py` | MODIFY | ~2 (source validation set) |
| `mcp_tools/trading_analysis.py` | MODIFY | ~5 (add schwab_csv to source acceptance) |
| `mcp_tools/tax_harvest.py` | MODIFY | ~5 (add schwab_csv to valid_source) |
| `mcp_tools/performance.py` | MODIFY | ~5 (add schwab_csv to source acceptance) |
| `core/realized_performance/aggregation.py` | MODIFY | ~2 (source validation) |
| `core/realized_performance/engine.py` | MODIFY | ~2 (source validation) |
| `core/realized_performance/holdings.py` | MODIFY | ~2 (schwab_csv in Schwab institution match) |
| `settings.py` | MODIFY | ~2 (REALIZED_PROVIDER_FLOW_SOURCES default) |
| `providers/routing.py` | MODIFY | ~3 (TRANSACTION_PROVIDERS + alias) |
| `services/performance_helpers.py` | MODIFY | ~2 (source Literal) |
| `routes/realized_performance.py` | MODIFY | ~2 (source Literal) |
| `core/risk_orchestration.py` | MODIFY | ~2 (argparse choices) |
| `scripts/run_trading_analysis.py` | MODIFY | ~2 (CLI --source choices) |
| `tests/trading_analysis/test_provider_routing.py` | MODIFY | ~15 (validation assertion + empty-payload test) |
| `tests/inputs/test_transaction_normalizer_registry.py` | CREATE | ~60 |
| `tests/inputs/test_schwab_csv_normalizer.py` | CREATE | ~140 |
| `tests/mcp_tools/test_import_transactions_csv.py` | CREATE | ~120 |

**Total**: 6 new source files, 19 modified, 3 new test files. ~1010 lines.

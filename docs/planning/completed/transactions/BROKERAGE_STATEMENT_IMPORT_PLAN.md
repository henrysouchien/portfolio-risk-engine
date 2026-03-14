# Brokerage Statement Import (CSV → Transaction Store)

**Status**: PLANNING (v7 — fixes Codex round 12: store wiring, enums, path contract, freshness, normalizer interface)
**Added**: 2026-03-10
**Related**: `STATEMENT_IMPORT_PLAN.md` (IBKR-specific, 5 Codex review rounds) | `TRANSACTION_INGESTION_CONTRACT_PLAN.md` (prerequisite — schema + validation layer)

## Context

The transaction store (`inputs/transaction_store.py`) currently only ingests via API providers (Plaid, Schwab, SnapTrade, IBKR Flex). Users with CSV/PDF exports from brokerages have no path to import transaction history.

**Existing work**: `STATEMENT_IMPORT_PLAN.md` is a comprehensive, Codex-reviewed plan for IBKR Activity Statement CSV import. It covers parser, normalizer, store integration, cross-provider dedup, engine integration, and option multiplier fixes across 4 phases. That plan is the **Phase 1 implementation spec** — this plan layers the multi-brokerage infrastructure on top.

**Design constraint**: The normalizer infrastructure must be **agent-buildable** — ship built-in normalizers for known brokerages (IBKR, Schwab), and when an agent encounters an unknown CSV format, it writes a new normalizer class following the same interface.

**Key decision**: Transaction import and position import (Phase A Step 2) are **separate parallel systems**.

---

## Architecture: One Tier — Normalizer Classes

Every brokerage gets a **dedicated normalizer class** in `providers/normalizers/` following the existing contract `(NormalizedTrade[], NormalizedIncome[], fifo_transactions[])`. Each is a distinct provider in the transaction store.

| Brokerage | Provider name | Normalizer | Notes |
|-----------|--------------|------------|-------|
| IBKR | `ibkr_statement` | `IBKRStatementNormalizer` | Multi-section CSV, per-asset-category columns, option ×100, forex filtering, instrument_info lookup |
| Schwab | `schwab_csv` | `SchwabCSVNormalizer` | Reinvestment → dual output (income + BUY), `$` prefix, parenthesized negatives, cash sweep detection |
| (future) | `{broker}_csv` | `{Broker}CSVNormalizer` | Agent writes class following same interface |

For unknown brokerages, an agent inspects the CSV headers/sample rows, then writes a new normalizer class. No JSON mapping layer — Python is strictly more expressive and agents can write it directly.

---

## Design Decisions

**D1: No flow events from CSV import.** The store's flow persistence is hard-coded to specific provider extractors (`providers/flows/extractor.py`). Income events cover dividends, interest, and fees. Flows deferred.

**D2: Provider-family aliasing for source filtering.** The store uses `_normalized_provider_filter()` → `provider = %s` exact-match queries at **14 call sites** across `transaction_store.py` (lines 758, 794/798/821/825, 856, 906, 941, 1037/1043, 1107/1113, 1186/1190, 1380/1385, 1531, 1594, 1631, 2186). CSV providers need to be loadable under their API-provider family.

**Implementation**: Extract a shared helper `_append_provider_where()` to DRY the tuple-vs-string logic:

```python
_PROVIDER_FAMILY: dict[str, tuple[str, ...]] = {
    "ibkr_flex": ("ibkr_flex", "ibkr_statement"),
    "schwab": ("schwab", "schwab_csv"),
}

@staticmethod
def _normalized_provider_filter(provider: str | None) -> str | tuple[str, ...] | None:
    token = str(provider or "").strip().lower()
    if not token or token == "all":
        return None
    family = _PROVIDER_FAMILY.get(token)
    return family if family else token

@staticmethod
def _append_provider_where(
    provider_value: str | tuple[str, ...] | None,
    where: list[str],
    params: list,
) -> None:
    """Append provider filter clause. Handles single string, tuple, or None."""
    if provider_value is None:
        return
    if isinstance(provider_value, tuple):
        placeholders = ",".join(["%s"] * len(provider_value))
        where.append(f"provider IN ({placeholders})")
        params.extend(provider_value)
    else:
        where.append("provider = %s")
        params.append(provider_value)
```

**Double-normalization fix**: `load_from_store()` calls `_normalized_provider_filter(source)` and passes the result to `load_fifo_transactions(provider=...)`, which calls `_normalized_provider_filter(provider)` AGAIN internally. If the first call returns a tuple, the second `str(tuple)` would corrupt the value. Fix: make `_normalized_provider_filter()` **idempotent for tuples**:

```python
@staticmethod
def _normalized_provider_filter(provider) -> str | tuple[str, ...] | None:
    if provider is None:
        return None
    if isinstance(provider, tuple):
        return provider  # already resolved — pass through
    token = str(provider).strip().lower()
    if not token or token == "all":
        return None
    family = _PROVIDER_FAMILY.get(token)
    return family if family else token
```

This ensures all downstream loaders safely accept pre-resolved tuples from `load_from_store()`.

**Call sites split into three groups:**

**Group A — Family-expanded loaders (use `_append_provider_where()` with tuple support):**
- `load_fifo_transactions` (941) — main FIFO loader
- `load_income_events` (1037) — income events loader
- `load_provider_flow_events` (1094/1107) — flow events loader
- `load_fetch_metadata` (1380) — batch metadata loader
- `transaction_coverage` (1180/1186) — coverage report
- `load_from_store()` (2186) — top-level entry point

**Group B — Exact-match only (NOT family-expanded):**
- `get_latest_batch_time` (794/798) — used by `ensure_store_fresh()` for API refresh timing
- `get_latest_failed_batch_time` (821/825) — used for cooldown after failed API refresh
- `load_futures_mtm` (1520) — hardcoded `"ibkr_flex_mtm"`, not family-aware
- `load_flex_option_prices` (1583) — hardcoded `"ibkr_flex_option_prices"`, not family-aware

Group B freshness methods currently call `_normalized_provider_filter(provider)`. **Explicit fix**: Replace with a dedicated exact-match normalizer that preserves `"all"` → `None` semantics but does NOT do family lookup:
```python
@staticmethod
def _exact_provider_filter(provider: str | None) -> str | None:
    """Normalize provider string without family expansion. For freshness queries."""
    if provider is None:
        return None
    token = str(provider).strip().lower()
    if not token or token == "all":
        return None
    return token

# In get_latest_batch_time() and get_latest_failed_batch_time():
# BEFORE: provider_value = self._normalized_provider_filter(provider)
# AFTER:
provider_value = self._exact_provider_filter(provider)
```
This ensures a recent `ibkr_statement` CSV batch does NOT make `ibkr_flex` API look fresh, and a failed CSV batch does NOT trigger API cooldown. The `"all"` → `None` mapping is preserved (unlike a raw `str(provider or "").strip().lower() or None` which would pass `"all"` through as a literal).

**Group C — Inspection/query methods (family-expanded via `_normalized_provider_filter`):**
- `list_batches` (747/758) — batch listing
- `query_normalized_transactions` (842/856) — normalized row inspection
- `query_raw_transactions` (895/906) — raw row inspection
- `transaction_coverage` (1180/1186) — already in Group A

These methods receive raw provider strings from MCP tools (`mcp_tools/transactions.py` lines 247, 290, 310, 593). Currently they do inline `provider = %s` without going through `_normalized_provider_filter()`. **Fix**: Route through `_normalized_provider_filter()` + `_append_provider_where()` so `list_transactions(provider="schwab")` automatically returns both `schwab` and `schwab_csv` rows. This is a small change to each method.

**Group D — Write paths (exact-match only, never family-expanded):**
- `store_normalized_transactions` (434) — writes rows for a specific provider
- `store_normalized_income` (566) — writes rows for a specific provider
- `_load_raw_batch_rows` (1621) — loads raw rows for a specific batch/provider for normalization

**Test to add**: `test_ensure_store_fresh_not_suppressed_by_csv_batch` — verify that a recent `ibkr_statement`/`schwab_csv` completed batch does not prevent `ibkr_flex`/`schwab` API refresh.

For `source=None`/`"all"`: returns `None` → no provider filter → all providers loaded → existing behavior. Cross-provider dedup post-load handles overlaps (see D7).

**IBKR-specific side data**: `load_from_store()` gates futures MTM and option-price loading on `if provider in {None, "ibkr_flex"}` (line 2214). Since `_normalized_provider_filter("ibkr_flex")` now returns `("ibkr_flex", "ibkr_statement")` (a tuple), this check must be updated:
```python
# Before:
if provider in {None, "ibkr_flex"}:
# After:
_provider_includes_ibkr = (
    provider is None
    or provider == "ibkr_flex"
    or (isinstance(provider, tuple) and "ibkr_flex" in provider)
)
if _provider_includes_ibkr:
    futures_mtm_events = store.load_futures_mtm(...)
    flex_option_price_rows = store.load_flex_option_prices(...)
```
The MTM/option-price loaders themselves use hardcoded `provider="ibkr_flex_mtm"` / `provider="ibkr_flex_option_prices"` and are not affected by the family refactor.

**D3: `_dedup_key()` and `_provider_transaction_id()` for new providers.** The raw-ingest path (`store_raw_transactions()` at line 219) skips rows without a dedup key. New providers need explicit handling:

For `ibkr_statement` (per `STATEMENT_IMPORT_PLAN.md`):
```python
if provider == "ibkr_statement":
    row_type = row.get("_row_type", "")
    if row_type == "trade":
        sym = row.get("symbol", "")
        dt = row.get("date_time", "")[:10]
        qty = row.get("quantity", "")
        price = row.get("t_price", "")
        acct = row.get("_account_id", "")
        return f"ibkr_stmt:{sym}:{dt}:{qty}:{price}:{acct}"
    else:  # interest, dividend, fee
        dt = row.get("date", "")[:10]
        desc = row.get("description", "")[:50]
        amt = row.get("amount", "")
        cur = row.get("currency", "")
        acct = row.get("_account_id", "")
        return f"ibkr_stmt_{row_type}:{dt}:{desc}:{amt}:{cur}:{acct}"
```

For `schwab_csv`:
```python
if provider == "schwab_csv":
    dt = row.get("Date", "")
    action = row.get("Action", "")
    sym = row.get("Symbol", "")
    qty = row.get("Quantity", "")
    price = row.get("Price", "")
    acct = row.get("Account Number", "")
    return hashlib.sha256(
        f"schwab_csv:{dt}:{action}:{sym}:{qty}:{price}:{acct}".encode()
    ).hexdigest()[:32]
```

Similarly for `_provider_transaction_id()` and `_row_symbol()`, `_row_transaction_date()`, `_row_account_id()` — each gets a case for the new providers using the correct field names from parsed rows.

**D4: Store wiring for agent-built normalizers.** When an agent writes a new normalizer class for an unknown brokerage, it must also wire it into the store. This means adding cases to `_dedup_key()`, `_row_symbol()`, `_row_transaction_date()`, `_row_account_id()`, and `normalize_batch()`. To minimize friction, all agent-built normalizers use a **canonical field convention**: raw rows stored in the DB use canonical field names (`symbol`, `date`, `action`, `quantity`, `price`, `currency`, `account`). The normalizer's `flatten_for_store()` method maps brokerage-specific column names to canonical names before storage. This allows a single fallback case in each accessor:

```python
# In _dedup_key(), _row_symbol(), etc. — catch-all for agent-built providers:
if provider not in _KNOWN_PROVIDERS:
    # Agent-built normalizer — uses canonical field names
    return self._text_or_none(row.get("symbol"))
```

`_KNOWN_PROVIDERS` is the static set of built-in providers (`plaid`, `schwab`, `ibkr_flex`, `snaptrade`, `ibkr_statement`, `schwab_csv`). Agent-built providers fall through to the canonical field path.

Similarly for `normalize_batch()`:
```python
elif row_provider not in _KNOWN_PROVIDERS:
    # Agent-built normalizer — look up in registry
    unknown_provider_rows.setdefault(row_provider, []).append(raw)
# ... then:
for prov, rows in unknown_provider_rows.items():
    normalizer_cls = _NORMALIZER_REGISTRY.get(prov)
    if normalizer_cls:
        _, inc, fifo = normalizer_cls().normalize(rows)
        income_events.extend(inc)
        fifo_transactions.extend(fifo)
```

**D4a: Account column handling.** For single-account CSVs without an account column, the `import_statement` MCP tool's `account_id` parameter is **required** (validation error if CSV has no account column and `account_id` is not provided). The tool stamps `account_id` onto all rows before storage.

**D5: MCP tool takes file path only.** `import_statement(path=...)` always takes a single CSV file path. IBKR Activity Statements are single CSV files (not directories) — all sections are in one file. The parser handles the multi-section format within the single file.

**D5a: Normalizer interface contract.** Every normalizer class must implement:

```python
class BrokerNormalizer:
    provider_name: str  # e.g., "fidelity_csv"

    @classmethod
    def can_handle(cls, headers: list[str]) -> bool:
        """Return True if these CSV headers match this brokerage's format."""

    def flatten_for_store(self, raw_rows: list[dict]) -> list[dict]:
        """Map brokerage column names → canonical field names for raw storage."""

    def normalize(
        self,
        raw_data: list[dict],
        security_lookup: dict | None = None,
    ) -> tuple[list[NormalizedTrade], list[NormalizedIncome], list[dict]]:
        """Normalize raw rows → (trades, income, fifo_transactions)."""
```

The `can_handle()` classmethod enables auto-detection: the MCP tool iterates `_NORMALIZER_REGISTRY`, calls `cls.can_handle(headers)`, and uses the first match. The `flatten_for_store()` method ensures canonical field names in raw storage (enabling the catch-all accessor pattern in D4).

**D6: Cross-provider dedup for all families (data-driven, not hard-coded).** Separate trade and income dedup keys — different row shapes require different key fields.

```python
def _cross_provider_trade_dedup_key(txn: dict) -> tuple:
    """7-field key for matching trades across API and CSV providers."""
    return (
        str(txn.get("symbol") or "").upper(),
        str(txn.get("type") or "").upper(),
        str(txn.get("date") or "")[:10],
        round(abs(float(txn.get("quantity") or 0)), 4),
        round(abs(float(txn.get("price") or 0)), 2),
        str(txn.get("currency") or "USD").upper(),
        str(txn.get("account_id") or "").lower(),
    )

def _cross_provider_income_dedup_key(inc: dict) -> tuple:
    """5-field key for matching income across API and CSV providers."""
    return (
        str(inc.get("symbol") or "").upper(),
        str(inc.get("date") or "")[:10],
        round(abs(float(inc.get("amount") or 0)), 2),
        str(inc.get("currency") or "USD").upper(),
        str(inc.get("account_id") or "").lower(),
    )
```

Called in `load_from_store()` — iterate `_PROVIDER_FAMILY` dynamically:
```python
for api_provider, family_tuple in _PROVIDER_FAMILY.items():
    for csv_provider in family_tuple:
        if csv_provider != api_provider:
            fifo_transactions = _dedup_across_family(
                fifo_transactions, api_provider, csv_provider, _cross_provider_trade_dedup_key)
            income_events = _dedup_across_family(
                income_events, api_provider, csv_provider, _cross_provider_income_dedup_key)
```

The `_dedup_across_family()` function takes a `key_fn` parameter:
```python
def _dedup_across_family(items, api_provider, csv_provider, key_fn):
    api_keys: Counter = Counter()
    for item in items:
        if item.get("source") == api_provider:
            api_keys[key_fn(item)] += 1
    if not api_keys:
        return items
    result = []
    for item in items:
        if item.get("source") == csv_provider:
            key = key_fn(item)
            if api_keys.get(key, 0) > 0:
                api_keys[key] -= 1
                continue
        result.append(item)
    return result
```

This is data-driven — adding a new family to `_PROVIDER_FAMILY` automatically enables dedup. No hard-coded pairs.

**D7: MCP inspection tools get family expansion in the store layer.** `list_transactions`, `inspect_transactions`, `list_ingestion_batches`, and `transaction_coverage` pass raw provider strings from MCP tools into store methods (`query_normalized_transactions`, `query_raw_transactions`, `list_batches` at lines 842, 895, 747). These methods currently use inline `provider = %s`. **Change**: Add `_normalized_provider_filter()` + `_append_provider_where()` to these 3 methods so `list_transactions(provider="schwab")` automatically returns both `schwab` and `schwab_csv` rows. No changes needed in `mcp_tools/transactions.py` — the family expansion happens in the store layer.

**D8: Provider enum/Literal types in MCP tools.** Several MCP tools hard-code provider names in `Literal[...]` type annotations:
- `mcp_tools/transactions.py:17` — `Provider = Literal["all", "plaid", "schwab", "ibkr_flex", "snaptrade"]`
- `mcp_tools/transactions.py:249` — `Optional[Literal["plaid", "schwab", "ibkr_flex", "snaptrade"]]`
- `mcp_tools/performance.py:50,441` — `source: Literal["all", "snaptrade", "plaid", "ibkr_flex", "schwab"]`
- `mcp_tools/trading_analysis.py:76` — same
- `mcp_tools/tax_harvest.py:809` — same

**Fix**: Change all `Literal[...]` provider/source type annotations to `str` with a description listing known values. The store layer already handles unknown provider strings gracefully (returns empty results). This also unblocks agent-built providers without code changes to MCP tool signatures.

```python
# Before:
Provider = Literal["all", "plaid", "schwab", "ibkr_flex", "snaptrade"]
# After:
# provider type annotation becomes str, with docstring listing known values
source: str = "all",  # "all", "plaid", "schwab", "ibkr_flex", "snaptrade", or any registered CSV provider
```

New CSV providers that don't map to an API family are accessible via `source="all"` (returns everything) or their exact provider name (e.g., `source="fidelity_csv"`).

---

## Phase 1: IBKR Activity Statement CSV

**Spec**: `STATEMENT_IMPORT_PLAN.md` (v6, 5 Codex review rounds)

No changes — implement as-is. Covers:
- `inputs/importers/ibkr_statement.py` — multi-section CSV parser + `flatten_for_store()`
- `providers/normalizers/ibkr_statement.py` — `IBKRStatementNormalizer` (trade type derivation, option ×100, symbol resolution via instrument_info)
- `_dedup_key()` / `_provider_transaction_id()` for `"ibkr_statement"` provider
- `_IBKR_PROVIDERS` tuple for `load_from_store()` (generalized to `_PROVIDER_FAMILY` in this plan)
- Cross-provider dedup: FIFO 7-field key, income 5-field key, flex wins
- Engine: option ×100 guard (3 locations), cash anchor metadata, unfiltered metadata pass
- ~55 tests

---

## Phase 2: Schwab CSV Normalizer

### 2a. Parser

Schwab transaction CSVs are flat with a preamble row. Use `FlatCSVParser` (Phase 3) for the parse step, then run through `SchwabCSVNormalizer`.

### 2b. `SchwabCSVNormalizer` (`providers/normalizers/schwab_csv.py`)

Dedicated normalizer following the existing contract:

```python
class SchwabCSVNormalizer:
    provider_name = "schwab_csv"

    def normalize(
        self,
        raw_data: list[dict],
        security_lookup: dict | None = None,
    ) -> tuple[list[NormalizedTrade], list[NormalizedIncome], list[dict]]:
```

Handles:
- Action mapping: "Buy" → BUY, "Sell" → SELL, "Sell Short" → SHORT, "Buy to Cover" → COVER
- Reinvestment dual-output: "Reinvest Shares" → `NormalizedIncome(dividend)` + FIFO trade (BUY)
- Income: "Qualified Dividend", "Cash Dividend", "Interest", "Bond Interest" → `NormalizedIncome`
- Amount cleanup: strip `$`, commas, handle parenthesized negatives
- Cash sweep / journal entries → skip
- Default currency: USD

### 2c. Store Integration

- Add `"schwab": ("schwab", "schwab_csv")` to `_PROVIDER_FAMILY`
- Add `schwab_csv` case to `_dedup_key()`:
  ```python
  if provider == "schwab_csv":
      return hashlib.sha256(f"schwab_csv:{date}:{action}:{sym}:{qty}:{price}:{acct}".encode()).hexdigest()[:32]
  ```
- Add `_row_symbol()`, `_row_transaction_date()`, `_row_account_id()` cases for `schwab_csv` using Schwab CSV column names
- Add `SchwabCSVNormalizer` dispatch in `normalize_batch()`:
  ```python
  elif row_provider == "schwab_csv":
      schwab_csv_rows.append(raw)
  # ... then:
  if schwab_csv_rows:
      _, schwab_csv_income, schwab_csv_fifo = SchwabCSVNormalizer().normalize(schwab_csv_rows)
      income_events.extend(schwab_csv_income)
      fifo_transactions.extend(schwab_csv_fifo)
  ```
- Cross-provider dedup in `load_from_store()`: `_dedup_across_family(fifo, "schwab", "schwab_csv")` + income

### 2d. Tests (~15)

- Parser: preamble skip, `$` stripping, comma handling
- Normalizer: action routing, reinvestment dual-output, income types, skip actions
- Store: `_dedup_key()` for schwab_csv, provider family loading, cross-provider dedup (API wins)

**Prerequisite**: Need a real Schwab transactions CSV sample.

---

## Phase 3: MCP Tools + Flat CSV Parser

### 3a. Flat CSV Parser (`inputs/importers/flat_csv.py`)

Shared utility for parsing standard single-table CSVs (used by Schwab normalizer and future brokerage normalizers):

```python
class FlatCSVParser:
    def parse(self, file_path: str, skip_rows: int = 0) -> list[dict]:
        """CSV → list of dicts. Handles BOM, encoding, preamble detection."""

    def detect(self, file_path: str) -> dict:
        """Returns {headers, sample_rows, skip_rows, row_count} for agent inspection."""
```

### 3b. MCP Tool: `import_statement`

```python
@handle_mcp_errors
def import_statement(
    path: str,                           # file or directory
    broker: str | None = None,           # "ibkr", "schwab", or future normalizer name
    account_id: str | None = None,       # stamp on all rows if CSV lacks account column
    dry_run: bool = True,
    user_email: str | None = None,
) -> dict:
```

Resolution:
1. `broker` provided → delegate to registered normalizer class (includes IBKR single-file multi-section parser)
2. Neither → auto-detect from headers (try registered normalizers' `can_handle(headers)` classmethod), or return `{status: "unknown_format", headers, sample_rows}` for agent to inspect

**Normalizer registry**: Simple dict mapping `broker` names to normalizer classes:
```python
_NORMALIZER_REGISTRY: dict[str, type] = {
    "ibkr": IBKRStatementNormalizer,
    "schwab": SchwabCSVNormalizer,
}
```

When an agent writes a new normalizer class for an unknown brokerage, it registers it here. The normalizer follows the same interface as existing ones.

### 3c. Agent Workflow for Unknown CSVs

1. `import_statement(path="exports/fidelity.csv")` → `{status: "unknown_format", headers: [...], sample_rows: [...]}`
2. Agent inspects headers and sample data
3. Agent writes a new `FidelityCSVNormalizer` class in `providers/normalizers/fidelity_csv.py` implementing `provider_name`, `can_handle()`, `flatten_for_store()`, and `normalize()`
4. Agent adds `"fidelity_csv": FidelityCSVNormalizer` to `_NORMALIZER_REGISTRY` in `mcp_tools/import_statements.py`
5. Agent adds `"fidelity_csv"` to `_CONCRETE_PROVIDERS` in `transaction_store.py` (no accessor/dedup cases needed — falls through to canonical field catch-all per D4)
6. If fidelity has an API provider, add to `_PROVIDER_FAMILY`; otherwise standalone
7. Agent calls `import_statement(path=..., broker="fidelity", dry_run=True)` → preview
8. If good, `import_statement(path=..., broker="fidelity", dry_run=False)` → ingest

Steps 4-6 are the "store wiring" — minimal because agent-built normalizers use canonical field names via `flatten_for_store()`, so the catch-all accessor pattern handles them without per-provider cases.

### 3d. Tests (~10)

- FlatCSVParser: BOM, preamble, encoding
- MCP tool: resolution order, dry run preview, unknown format response
- Auto-detect: `can_handle()` classmethod matching

---

## Phase 5: Merrill PDF (Deferred)

---

## Files Summary

| File | Action | Phase |
|------|--------|-------|
| `inputs/importers/__init__.py` | Create | 1 |
| `inputs/importers/ibkr_statement.py` | Create | 1 |
| `inputs/importers/flat_csv.py` | Create | 3 |
| `providers/normalizers/ibkr_statement.py` | Create | 1 |
| `providers/normalizers/schwab_csv.py` | Create | 2 |
| `mcp_tools/import_statements.py` | Create | 3 |
| `inputs/transaction_store.py` | Modify (provider family, `_dedup_key`, `_provider_transaction_id`, `_row_*`, normalize dispatch, `_normalized_provider_filter` → tuple support, `_dedup_across_family`) | 1-2 |
| `providers/normalizers/__init__.py` | Modify (exports) | 1-2 |
| `core/realized_performance/nav.py` | Modify (option ×100 guard) | 1 |
| `core/realized_performance/engine.py` | Modify (cash anchor, metadata) | 1 |
| `mcp_tools/transactions.py` | Modify (Provider Literal → str) | 1 |
| `mcp_tools/performance.py` | Modify (source Literal → str) | 1 |
| `mcp_tools/trading_analysis.py` | Modify (source Literal → str) | 1 |
| `mcp_tools/tax_harvest.py` | Modify (source Literal → str) | 1 |
| `mcp_server.py` | Modify (register tools) | 3 |

---

## Test Data

IBKR Activity Statement CSVs available:
- `docs/U2471778_2025_2025.csv` — Full year 2025 (709 lines)
- `docs/U2471778_20260101_20260309.csv` — YTD 2026 (379 lines)
- `docs/U2471778_20260309.csv` — Single day Mar 9 2026 (346 lines)
- `docs/planning/completed/performance-actual-2025/U2471778_20250401_20260303.csv` — Apr 2025 - Mar 2026
- Pre-parsed frames at `docs/planning/completed/performance-actual-2025/ibkr_statement_frames/`

---

## Verification

```bash
# Phase 1: IBKR (~55 tests per STATEMENT_IMPORT_PLAN.md)
python3 -m pytest tests/importers/ -x -q

# Phase 2: Schwab CSV (~15 tests)
python3 -m pytest tests/test_schwab_csv*.py -x -q

# Phase 3: MCP tools + flat CSV parser (~10 tests)
python3 -m pytest tests/test_import_statements*.py -x -q

# E2E IBKR dry-run
# MCP: import_statement(path="docs/U2471778_2025_2025.csv", broker="ibkr", dry_run=True)

# All existing tests
python3 -m pytest tests/ -x --no-header -q
```

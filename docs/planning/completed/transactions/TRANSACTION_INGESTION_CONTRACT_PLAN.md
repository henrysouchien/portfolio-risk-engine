# Transaction Ingestion Contract

**Status**: PLANNING (v3 — fixes units/quantity alias, multiplier in contract_identity, payment_in_lieu)
**Added**: 2026-03-10
**Related**: `BROKERAGE_STATEMENT_IMPORT_PLAN.md` (depends on this contract) | `STATEMENT_IMPORT_PLAN.md` (IBKR-specific normalizer uses this contract)

## Context

The transaction store (`inputs/transaction_store.py`) accepts normalized data from 4 normalizers (plaid, schwab, ibkr_flex, snaptrade) with **zero validation**. The contract is entirely implicit — coercion happens inline in `store_normalized_transactions()` (line 434) and `store_normalized_income()` (line 566), silently defaulting bad data or skipping rows. Before adding CSV statement import (new normalizers, potentially agent-built), we need an explicit ingestion contract: a formal schema, coercion layer, and validation step that sits between normalizer output and the store.

### Architecture

```
Normalizer output (list[dict])
        │
        ▼
coerce_trades(rows)           ← normalize field names, types, defaults
        │
        ▼
validate_trades(rows)         ← check required fields, enums, ranges
        │
        ▼
ValidationResult(valid=[], rejected=[], warnings=[])
        │
        ▼
store_normalized_transactions(valid)   ← thin INSERT, no coercion
```

---

## New File: `inputs/transaction_contract.py` (~300 lines)

The single canonical reference for what a valid transaction looks like.

### Constants

```python
VALID_TRADE_TYPES = {"BUY", "SELL", "SHORT", "COVER"}
VALID_INCOME_TYPES = {"dividend", "interest", "distribution", "fee", "payment_in_lieu"}
VALID_CURRENCIES = {"USD", "CAD", "GBP", "EUR", "JPY", "CHF", "AUD", "HKD", "SGD", ...}  # ~25 codes the system encounters
```

Reuse from existing code:
- `_VALID_INSTRUMENT_TYPES` and `coerce_instrument_type()` from `trading_analysis/instrument_meta.py`

### Trade Schema — FIFO Transaction Record

| Field | Type | Required | Default | Validation |
|-------|------|----------|---------|------------|
| `symbol` | str | YES | — | Non-empty, uppercase, "UNKNOWN" → warning |
| `type` | str | YES | — | Must be in `VALID_TRADE_TYPES` |
| `date` | datetime | YES | — | Must parse, >30d future → error, >5d → warning |
| `quantity` | float | YES | — | Must be > 0 (after abs) |
| `price` | float | YES | — | Must be >= 0. 0.0 → warning unless `option_expired` |
| `source` | str | YES | — | Non-empty (provider name) |
| `fee` | float | no | 0.0 | abs() applied |
| `currency` | str | no | "USD" | Uppercase. Unknown code → warning |
| `transaction_id` | str | no | "" | Auto-hashed by store if empty |
| `account_id` | str | no | "" | |
| `account_name` | str | no | "" | |
| `institution` | str | no | "" | Canonical key (aliases: `_institution`) |
| `instrument_type` | str | no | "equity" | Via `coerce_instrument_type()` |
| `contract_identity` | dict\|None | no | None | Exercise metadata packed with `_` prefix |
| `is_option` | bool | no | False | |
| `is_futures` | bool | no | False | |
| `option_expired` | bool | no | False | |
| `broker_cost_basis` | float\|None | no | None | |
| `broker_pnl` | float\|None | no | None | |
| `multiplier` | float | no | 1.0 | Packed into `contract_identity` by coercion. Warn if <= 0 |

### Income Schema — Income Event Record

| Field | Type | Required | Default | Validation |
|-------|------|----------|---------|------------|
| `symbol` | str | YES | — | Non-empty, uppercase |
| `income_type` | str | YES | — | Must be in `VALID_INCOME_TYPES` |
| `date` | datetime | YES | — | Must parse |
| `amount` | float | YES | — | Signed. 0.0 → warning |
| `source` | str | YES | — | Non-empty |
| `currency` | str | no | "USD" | Uppercase |
| `transaction_id` | str | no | "" | Auto-hashed if empty |
| `account_id` | str | no | "" | |
| `account_name` | str | no | "" | |
| `institution` | str | no | "" | |

### Result Types

```python
@dataclass
class FieldError:
    field: str
    value: Any
    reason: str

@dataclass
class RowValidationResult:
    row_index: int
    errors: list[FieldError]    # Row rejected if non-empty
    warnings: list[FieldError]  # Row accepted, logged

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

@dataclass
class ValidationResult:
    valid: list[dict]
    rejected: list[dict]
    row_results: list[RowValidationResult]

    def summary(self) -> str: ...
```

### Field Aliasing (handled by coercion layer)

The store currently reads fields with multiple key fallbacks. The coercion layer normalizes all aliases to canonical keys before validation. This is the **complete alias map**:

**Trades:**
| Canonical key | Aliases accepted | Why alias exists |
|--------------|-----------------|-----------------|
| `source` | `provider` | Store reads `txn.get("source") or txn.get("provider")` (line 450) |
| `date` | `transaction_date` | Store reads `txn.get("date") or txn.get("transaction_date")` (line 455) |
| `institution` | `_institution` | Store reads `txn.get("_institution") or txn.get("institution")` (line 540) |
| `type` | `trade_type` (as `TradeType` enum or str) | `NormalizedTrade` dataclass uses `trade_type: TradeType` (models.py:215). FIFO dicts use `"type"` |
| `quantity` | `units` | `NormalizedTrade` dataclass uses `units: float` (models.py:217). Store persists as `quantity` (line 547) |

**Income:**
| Canonical key | Aliases accepted | Store code reference |
|--------------|-----------------|---------------------|
| `source` | `provider` | `payload.get("source") or payload.get("provider")` (line 580) |
| `date` | `event_date` | `payload.get("date") or payload.get("event_date")` (line 581) |

**TradeType enum coercion**: `NormalizedTrade.trade_type` is a `TradeType` enum (`trading_analysis/models.py:20`), but FIFO dicts use plain strings (`"BUY"`, `"SELL"`). The coercion layer handles both:
```python
raw_type = out.get("type") or out.get("trade_type") or ""
if hasattr(raw_type, "value"):  # TradeType enum
    raw_type = raw_type.value
out["type"] = str(raw_type).strip().upper()
```

**units → quantity coercion**: `NormalizedTrade` uses `units`, store persists as `quantity`:
```python
if "quantity" not in out and "units" in out:
    out["quantity"] = out["units"]
```

### Multiplier Round-Trip

`multiplier` is NOT a DB column — it lives inside `contract_identity` JSONB. Downstream consumers read it from there:
- `trading_analysis/fifo_matcher.py:35` — `contract_identity.get("multiplier", 1.0)`
- `trading_analysis/exercise_linkage.py:75` — `(opt_txn.get("contract_identity") or {}).get("multiplier", 100)`

The coercion layer packs `multiplier` into `contract_identity` (same as exercise metadata):
```python
# If normalizer set multiplier as top-level key, pack it into contract_identity
mult = _safe_float(out.get("multiplier"), 1.0)
if mult != 1.0:
    ci["multiplier"] = mult
```

- Coercion: top-level `multiplier` → packed into `contract_identity["multiplier"]`
- Validation: warn if <= 0
- Store: does NOT read or persist `multiplier` directly — it round-trips through `contract_identity` JSONB

### Exercise Metadata Round-Trip

The store packs 4 exercise fields into `contract_identity` with `_` prefix keys (lines 479-486). The coercion layer replicates this exact behavior:

```python
# These top-level dict keys are packed INTO contract_identity by coercion:
if out.get("option_exercised"):
    ci["_option_exercised"] = True
if out.get("stock_from_exercise"):
    ci["_stock_from_exercise"] = True
if out.get("underlying"):
    ci["_underlying"] = out["underlying"]
if out.get("exercise_code"):
    ci["_exercise_code"] = out["exercise_code"]
out["contract_identity"] = ci or None
```

The top-level keys (`option_exercised`, `stock_from_exercise`, `underlying`, `exercise_code`) remain in the dict after coercion — the store reads them for the packing step, and the coercion layer pre-packs them into `contract_identity`. The store method no longer needs to do this packing itself.

### Functions

**Coercion** (non-destructive, returns copy):

- `coerce_trade(row: dict) -> dict` — resolve field aliases (source/provider, date/transaction_date, institution/_institution, type/trade_type+enum), uppercase symbol, abs quantity, default currency, pack exercise metadata into contract_identity, coerce instrument_type, parse date, coerce TradeType enum → str
- `coerce_income(row: dict) -> dict` — resolve field aliases (source/provider, date/event_date), uppercase symbol, lowercase income_type, parse date, default currency

**Validation** (operates on coerced dicts):

- `validate_trade(row, row_index) -> RowValidationResult` — check required fields, enum values, range constraints
- `validate_income(row, row_index) -> RowValidationResult` — same for income

**Entry points** (coerce + validate in one call):

- `prepare_trades(rows: list[dict]) -> ValidationResult` — coerce all, validate all, return valid/rejected/errors
- `prepare_income(rows: list[dict]) -> ValidationResult` — same for income

### Validation Rules

**Errors (row rejected):**
- `symbol` empty
- `type` not in VALID_TRADE_TYPES
- `date` unparseable or None
- `date` > 30 days in future
- `quantity` <= 0
- `price` < 0
- `source` empty
- `income_type` not in VALID_INCOME_TYPES

**Warnings (row accepted, logged):**
- `symbol` == "UNKNOWN"
- `price` == 0.0 and not `option_expired`
- `date` > 5 days in future (settlement lag)
- `currency` not in VALID_CURRENCIES
- `instrument_type` not in `_VALID_INSTRUMENT_TYPES`
- `amount` == 0.0 (income)

---

## Modified File: `inputs/transaction_store.py`

### `store_normalized_transactions()` (line 434)

**Before**: Inline coercion (lines 450-492) — uppercase, abs, defaults, exercise metadata packing, then INSERT.

**After**:
1. Convert inputs via `_as_dict()` (preserves NormalizedTrade dataclass compat)
2. Call `prepare_trades(rows)` → `ValidationResult`
3. Log warnings, log + skip rejected rows
4. INSERT loop over `result.valid` — thin, no coercion (already done)

The `_hash_key()` / `transaction_id` generation stays in the store (needs batch context). The `raw_id_map` lookup stays in the store (needs batch-specific mapping).

### `store_normalized_income()` (line 566)

Same pattern: `prepare_income()` → log → INSERT valid rows.

**Estimated changes**: ~80 lines modified (replace inline coercion blocks with contract calls + result handling).

---

## New File: `tests/inputs/test_transaction_contract.py` (~400 lines)

### Coercion tests (~20):
- Uppercase symbol, abs quantity, default currency, exercise metadata packing into contract_identity
- Field alias resolution: `source`/`provider`, `date`/`transaction_date`, `institution`/`_institution`, `type`/`trade_type`, `units`/`quantity`
- `TradeType` enum → string coercion (`TradeType.BUY` → `"BUY"`)
- `units` → `quantity` coercion (NormalizedTrade dataclass compat)
- `multiplier` packed into `contract_identity["multiplier"]` (not top-level DB column)
- None/empty field handling
- Income: lowercase income_type, `date` vs `event_date` alias, `source` vs `provider` alias
- Income: `payment_in_lieu` accepted as valid income_type

### Validation error tests (~15):
- Empty symbol, invalid trade_type, missing date, zero quantity, negative price, empty source
- Invalid income_type
- Far-future date (>30d)

### Validation warning tests (~8):
- "UNKNOWN" symbol, zero price (non-expiry vs expiry), unknown currency, near-future date, zero income amount

### Batch tests (~5):
- Mixed valid/invalid, all valid, empty batch, summary string

### Backward compatibility (~5):
- Existing normalizer output (NormalizedTrade dataclass → dict → prepare_trades) passes validation
- Existing FIFO dict format from ibkr_flex normalizer passes validation

---

## Files Summary

| File | Action | Est. lines |
|------|--------|-----------|
| `inputs/transaction_contract.py` | CREATE | ~300 |
| `inputs/transaction_store.py` | MODIFY (lines 434-564, 566-646) | ~80 changed |
| `tests/inputs/test_transaction_contract.py` | CREATE | ~400 |

---

## Verification

```bash
# 1. Contract tests pass
python3 -m pytest tests/inputs/test_transaction_contract.py -x -q

# 2. Existing store tests still pass (backward compat)
python3 -m pytest tests/inputs/test_transaction_store.py -x -q

# 3. Full test suite
python3 -m pytest tests/ -x --no-header -q
```

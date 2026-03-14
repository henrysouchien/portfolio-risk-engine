# Plan: Fix Income `instrument_type` Misclassification as `fx_artifact`

## Context

`normalize_flex_cash_income_trades()` in `ibkr/flex.py:737` hardcodes `instrument_type: "fx_artifact"` for ALL income trade-format records (dividends, interest). These records represent real securities (NVDA dividends, AAPL dividends, bond interest) — not FX conversion artifacts like `USD.CAD`. Labeling them as `fx_artifact` is semantically wrong and creates poor data quality.

**Why it works today despite being wrong:** The provider normalizer at `providers/normalizers/ibkr_flex.py:68` intercepts DIVIDEND/INTEREST records based on the `type` field and converts them to `NormalizedIncome` objects BEFORE `instrument_type` is ever read. So the `fx_artifact` label has zero functional impact — income records never reach the FIFO matcher, cash replay, or any code that checks `instrument_type`.

**Why we should still fix it:** If any future code reads `instrument_type` on these records (diagnostics, transaction store queries, logging), it would see NVDA dividends labeled as "fx_artifact." We don't want to leave incorrect metadata as a known issue.

## The Fix

### Step 1: Add `"income"` as a valid instrument type

**Files:**
- `trading_analysis/instrument_meta.py` — Add `"income"` to `InstrumentType` Literal (line 7) and `_VALID_INSTRUMENT_TYPES` set (line 17)
- `ibkr/_types.py` — Add `"income"` to `InstrumentType` Literal (line 7) and `_VALID_INSTRUMENT_TYPES` set (line 9)

### Step 2: Set correct `instrument_type` on income records

**File:** `ibkr/flex.py` line 737

Change:
```python
"instrument_type": "fx_artifact",
```
To:
```python
"instrument_type": "income",
```

### Step 3: Add defensive filter in cash replay + update diagnostics

**File:** `core/realized_performance/nav.py` lines 130-176

Currently:
```python
_skipped_fx = 0
...
if instrument_type == "fx_artifact":
    _skipped_fx += 1
    continue
...
if warnings is not None and _skipped_fx > 0:
    warnings.append(
        f"Cash replay: skipped {_skipped_fx} fx-artifact transaction(s)."
    )
```

Update to also skip income and rename counter/warning for accuracy:
```python
_skipped_non_trade = 0
...
if instrument_type in ("fx_artifact", "income"):
    _skipped_non_trade += 1
    continue
...
if warnings is not None and _skipped_non_trade > 0:
    warnings.append(
        f"Cash replay: skipped {_skipped_non_trade} non-trade transaction(s) (fx_artifact/income)."
    )
```

This is a safety net. Today, income records never reach this code because the normalizer intercepts them (DIVIDEND/INTEREST → NormalizedIncome + `continue` at `ibkr_flex.py:88`). Additionally, timeline.py line 434 has `if qty <= 0: continue` which filters income records (qty=0) before `instrument_type` is read at line 436. But if those upstream guards ever change, this prevents double-counting.

### Step 4: Add income-type recognition in `_infer_instrument_type_from_transaction()`

**File:** `core/realized_performance/_helpers.py` line 79

Add a check for income trade types before the symbol-based fallbacks:

```python
def _infer_instrument_type_from_transaction(txn: Dict[str, Any]) -> str:
    explicit = txn.get("instrument_type")
    if explicit:
        return coerce_instrument_type(explicit)

    # Income records (DIVIDEND/INTEREST) — should not participate in cash replay.
    trade_type = str(txn.get("type") or "").strip().upper()
    if trade_type in ("DIVIDEND", "INTEREST"):
        return "income"

    symbol = str(txn.get("symbol") or "").strip().upper()
    ...
```

This is another defensive layer: if an income record somehow loses its explicit `instrument_type` tag, the inference function will still recognize it by `type` field and return `"income"`.

### Step 5: Add `"income"` to engine pricing routing priority

**File:** `core/realized_performance/engine.py` line 753

Add `"income": 5` to `routing_priority` dict (same priority as `fx_artifact`):
```python
routing_priority = {
    "futures": 0,
    "fx": 1,
    "bond": 2,
    "option": 3,
    "equity": 4,
    "income": 5,
    "fx_artifact": 5,
    "unknown": 6,
}
```

Defensive: income records don't reach the pricing loop (normalizer + qty=0 guards filter them upstream), but having the key prevents a KeyError if they ever do.

### Step 6: Update docs enum list

**File:** `trading_analysis/README.md` line 195

Add `income` to the instrument type enum documentation.

### Step 7: Update tests

**File:** `tests/ibkr/test_flex.py`

Add assertion to `test_normalize_flex_cash_income_trades_maps_dividend_and_interest_rows()`:
```python
assert normalized[0]["instrument_type"] == "income"
assert normalized[1]["instrument_type"] == "income"
```

**File:** `tests/core/` (new or existing test file)

Add tests:
1. `_infer_instrument_type_from_transaction()` returns `"income"` for DIVIDEND/INTEREST types
2. `_infer_instrument_type_from_transaction()` returns `"income"` for explicit `instrument_type: "income"`
3. nav.py `derive_cash_and_external_flows` skips income-type transactions (defensive filter)

## Files Modified

| File | Change |
|------|--------|
| `ibkr/flex.py:737` | `"fx_artifact"` → `"income"` |
| `ibkr/_types.py` | Add `"income"` to `InstrumentType` + `_VALID_INSTRUMENT_TYPES` |
| `trading_analysis/instrument_meta.py` | Add `"income"` to `InstrumentType` + `_VALID_INSTRUMENT_TYPES` |
| `core/realized_performance/_helpers.py` | Income-type inference in `_infer_instrument_type_from_transaction()` |
| `core/realized_performance/nav.py` | Defensive filter + rename counter/warning text |
| `core/realized_performance/engine.py` | Add `"income"` to `routing_priority` dict |
| `trading_analysis/README.md` | Update instrument type enum docs |
| `tests/ibkr/test_flex.py` | Assert `instrument_type == "income"` on income records |
| `tests/core/` | Tests for inference + nav defensive filter |

## Why This Is Safe

Income records are blocked from trade processing by **3 independent guards**:

1. **Normalizer intercept** (primary): `providers/normalizers/ibkr_flex.py:68` checks `type in {"DIVIDEND", "INTEREST"}` and converts to `NormalizedIncome` + `continue` before `instrument_type` is read at line 90.

2. **Zero-quantity guard**: Income records have `quantity: 0.0`. Timeline's `if qty <= 0: continue` (line 434) filters them before `instrument_type` is used at line 436. Same in FIFO matcher which expects positive quantities.

3. **Defensive nav.py filter** (new, Step 3): `instrument_type in ("fx_artifact", "income")` skip in cash replay.

Additionally:
- `coerce_instrument_type("income")` returns `"income"` (not defaulting to `"equity"`) because we add it to `_VALID_INSTRUMENT_TYPES`.
- Engine `routing_priority` includes `"income"` to prevent KeyError if records reach pricing loop.
- IBKR `contracts.py:230` / `profiles.py:68` are NOT affected — these route by instrument type for market data requests and are never called on income records (no symbol resolution or pricing needed for dividends).

## Verification

```bash
# Existing income tests still pass
pytest tests/ibkr/test_flex.py -x -v -k "income"

# Realized performance tests still pass
pytest tests/core/test_realized_performance_analysis.py -x -q

# Full test suite
pytest tests/ibkr/ tests/core/ -x -q
```

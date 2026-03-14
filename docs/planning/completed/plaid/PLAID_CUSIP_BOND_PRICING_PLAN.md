# Plaid CUSIP → Bond Pricing Chain Fix

**Status**: COMPLETE — commit `2baba27f`

## Context
54 Merrill transactions ($4M+ notional) — US Treasury Notes, BlackRock funds — show as unpriceable because the Plaid normalizer never wires `security.cusip`/`security.isin` into `contract_identity`. The existing IBKR bond pricing infrastructure (FMP→IBKR fallback via `resolve_bond_contract()` with CUSIP) works end-to-end — the gap is entirely in the normalizer.

This is the primary driver of the Merrill +1.21% vs actual -12.49% gap. Unpriceable suppression (`8829bb2f`) mitigates to -7.96% but 4.53pp gap remains.

## Root Cause
Two gaps in `providers/normalizers/plaid.py`:

**Gap 1 — `contract_identity` never set for bonds (line 296-308):**
```python
contract_identity = None
if instrument_type == "option":
    contract_identity = self._extract_option_contract_identity(...)
# Bond branch: MISSING — contract_identity stays None
```

`PlaidSecurity.cusip` and `.isin` are populated from the Plaid API but never read by the normalizer. Without `contract_identity`, the bond pricing guard in `realized_performance_analysis.py:3748` sees `has_cusip = False` and marks the position unpriceable.

A rescue path exists at line 3739-3746 that enriches `contract_identity` from `current_positions.security_identifiers`, but it only works for bonds still held — fully-closed positions are missed.

**Gap 2 — `UNKNOWN` early return blocks bond detection (line 69-70):**
```python
if symbol_upper.startswith("UNKNOWN"):
    return "unknown"  # fires BEFORE bond check at line 83
```

When both `security.ticker_symbol` and `security.name` are None, symbol becomes `"UNKNOWN"` (line 250). The early return at line 69 fires before `_BOND_KEYWORDS` / `security.fixed_income` / `security.type` checks at line 83-90. Bonds with valid Plaid metadata (`type="fixed income"`, `fixed_income={...}`) but no name get misclassified as `"unknown"`.

Note: Most bonds DO have `security.name` (e.g., "US Treasury Note 4.25%"), so this only affects the edge case where both name and ticker are missing. But when it hits, the bond is completely invisible to the pricing chain.

## Fix

### Step 1 — Add `_extract_bond_contract_identity()` to `PlaidNormalizer`
New static method in `providers/normalizers/plaid.py`, parallel to `_extract_option_contract_identity()`:

```python
@staticmethod
def _extract_bond_contract_identity(
    *,
    security: Optional[PlaidSecurity],
) -> dict[str, Any] | None:
    """Extract CUSIP/ISIN from PlaidSecurity for bond pricing chain."""
    if security is None:
        return None
    cusip = str(security.cusip or "").strip() or None
    isin = str(security.isin or "").strip() or None
    if not cusip and not isin:
        return None
    result: dict[str, Any] = {}
    if cusip:
        result["cusip"] = cusip
    if isin:
        result["isin"] = isin
    return result
```

### Step 2 — Call it in the `normalize()` loop (line ~296-308)
Add `elif instrument_type == "bond":` branch:

```python
contract_identity = None
if instrument_type == "option":
    contract_identity = self._extract_option_contract_identity(
        symbol=symbol, security=security,
    )
elif instrument_type == "bond":
    contract_identity = self._extract_bond_contract_identity(
        security=security,
    )
```

### Step 3 — Fix `UNKNOWN` early return in `_infer_plaid_instrument_type()` (line 69-70)
Move **metadata-based** bond checks (fixed_income, security_type) before the UNKNOWN early return. Keep **keyword-based** bond detection after option checks to avoid option-vs-bond conflicts (e.g., an option transaction with "BOND" in txn_name):

```python
security_type = str((security.type if security else "") or "").strip().lower()

# Plaid-native bond metadata — checked BEFORE UNKNOWN return
# These are authoritative Plaid signals that don't conflict with options
is_bond_by_metadata = (
    security is not None
    and bool(getattr(security, "fixed_income", None))
) or security_type in {"fixed income", "bond"}
if is_bond_by_metadata:
    return "bond"

if symbol_upper.startswith("UNKNOWN"):
    return "unknown"
if is_fx_artifact_symbol(symbol_upper):
    return "fx_artifact"

# Option checks unchanged (lines 74-81)
is_option = ...
if is_option:
    return "option"

# Keyword-based bond fallback stays AFTER options to avoid conflicts
is_bond_by_keyword = any(
    keyword in txn_name_upper for keyword in _BOND_KEYWORDS
)
if is_bond_by_keyword:
    return "bond"

# Futures/equity checks unchanged
```

This preserves the option→bond priority for keyword-based detection while ensuring Plaid-native bond metadata (`fixed_income`, `type="fixed income"`) beats the UNKNOWN fallback. Keyword-only bonds with UNKNOWN symbol remain classified as "unknown" — acceptable since this is an edge case of an edge case (no ticker, no name, no Plaid metadata, only txn_name keyword).

### Step 4 — Tests (~7)
In `tests/providers/normalizers/test_plaid.py`:

1. **Bond with CUSIP+ISIN** — `PlaidSecurity(type="fixed income", cusip="9128285M8", isin="US9128285M81", ticker_symbol=None, name="US Treasury Note 4.25%")` → `fifo[0]["contract_identity"] == {"cusip": "9128285M8", "isin": "US9128285M81"}`, `instrument_type == "bond"`, quantity face-value scaled
2. **Bond with CUSIP only** — no ISIN → `contract_identity == {"cusip": "..."}`
3. **Bond with no identifiers** — `cusip=None, isin=None` → `contract_identity is None` (graceful degradation)
4. **Non-bond security unaffected** — equity with cusip doesn't get bond contract_identity (only fires for `instrument_type == "bond"`)
5. **UNKNOWN symbol + fixed income metadata** — `PlaidSecurity(ticker_symbol=None, name=None, type="fixed income", cusip="9128285M8")` → `instrument_type == "bond"` (metadata beats UNKNOWN), `contract_identity == {"cusip": "9128285M8"}`
6. **UNKNOWN symbol without any bond indicators** — `PlaidSecurity(ticker_symbol=None, name=None, type=None)` with generic txn name → still returns `instrument_type == "unknown"` (no regression)
7. **Option with bond keyword in txn_name** — `PlaidSecurity(ticker_symbol="TLT_C130_250620", type="derivative")` with txn name "BOND CALL OPTION" → `instrument_type == "option"` (option detection beats keyword-based bond detection; symbol is non-UNKNOWN)
8. **Keyword-only bond fallback** — `PlaidSecurity(ticker_symbol=None, name="US TREASURY NOTE 4.25%", type=None, fixed_income=None)` with txn name "US TREASURY NOTE 4.25%" → `instrument_type == "bond"` (keyword fallback for bonds without Plaid metadata, symbol is name so non-UNKNOWN)

In `tests/trading_analysis/test_instrument_tagging.py`:
- Existing test at line 151 asserts `contract_identity is None` for US Treasury Bill — this fixture has **no cusip field**, so it remains None after our fix (no update needed)

## Out of Scope
**Price synthesis + face-value scaling interaction (line 285-286 vs 307):** When `price==0`, the fallback computes `price = amount/raw_quantity` (per-$1-par), then quantity is divided by 100. This gives a 100x price mismatch. This is a **pre-existing bug** unrelated to CUSIP wiring — our change only adds `contract_identity`. Noted for future fix but out of scope here.

## Files to Modify
- `providers/normalizers/plaid.py` — Add `_extract_bond_contract_identity()`, call in `normalize()` loop, move bond check before UNKNOWN return in `_infer_plaid_instrument_type()`
- `tests/providers/normalizers/test_plaid.py` — 8 new tests

No changes needed to:
- `core/realized_performance_analysis.py` — bond guard already handles `contract_identity` with `cusip` key
- `ibkr/contracts.py` — `resolve_bond_contract()` already accepts CUSIP
- `ibkr/market_data.py` — `resolve_bond_by_cusip()` already works
- Positions path — `security_identifiers` already flows from Plaid loader

## Verification
1. `python -m pytest tests/providers/normalizers/test_plaid.py -x -v`
2. `python -m pytest tests/core/test_realized_performance_bond_pricing.py -x -v` (existing bond guard tests still pass)
3. Live: `get_performance(mode="realized", institution="merrill")` — check for fewer unpriceable symbols and improved return accuracy

# Exclude Cash-Equivalent Positions from Trading Scorecard

## Context

Treasury note position ($20K, -0.0% return) dominates sizing grade — largest position, near-zero return, creates F. It's cash management, not an active trade.

Plaid flags it as `is_cash_equivalent: false`, `type: fixed income`. But the maturity data shows it's a short-term hold: `maturity_date: 2025-10-15`, bought 2024-10-08, sold 2024-10-15 — 7 days, matured in ~1 year. Functionally cash management.

## Detection — Two-Tier Cascade

### Tier 1: YAML ticker list (cash-equivalent ETFs)

**File:** `config/cash_map.yaml`

Add `cash_equivalent_tickers` section:
```yaml
cash_equivalent_tickers:
  - SGOV
  - SHY
  - BIL
  - SHV
  - MINT
  - JPST
  - NEAR
  - ICSH
  - SCHO
  - VGSH
  - GBIL
  - TFLO
  - USFR
  - IBGE.L
  - ERNS.L
```

Loaded via existing `config/` infrastructure. Combined with `proxy_by_currency` values.

Note: Tier 2 (`instrument_type == "cash"`) was removed — cash transactions never reach FIFO round-trips. Plaid routes cash to income handling, and `InstrumentType` enum has no "cash" value. So `rt.instrument_type == "cash"` would never match.

### Tier 2: Short-maturity bonds (< 1 year to maturity from entry)

Plaid securities already have `fixed_income.maturity_date`. Thread this through `contract_identity` (already persisted as JSONB in `normalized_transactions`):

**a) Plaid normalizer includes maturity_date in contract_identity**

**File:** `providers/normalizers/plaid.py`

`PlaidNormalizer.normalize()` receives security data via its `security_lookup` argument (passed by `TransactionStore`). When building the normalized transaction dict for bond-type securities, include `maturity_date` in `contract_identity`:

```python
# In PlaidNormalizer.normalize(), where contract_identity is built:
# security is a PlaidSecurity object (not a dict), resolved via security_lookup[security_id]
fixed_income = getattr(security, "fixed_income", None) or {}
maturity_date = fixed_income.get("maturity_date") if isinstance(fixed_income, dict) else getattr(fixed_income, "maturity_date", None)
if maturity_date:
    contract_identity = dict(contract_identity or {})  # defensive — can be None for bonds without CUSIP/ISIN
    contract_identity["maturity_date"] = maturity_date
```

This does NOT require a DB migration — `contract_identity` is already a JSONB column in `normalized_transactions` that persists through the save/load round-trip. `maturity_date` is added as a key inside the existing JSON object. Note: `contract_identity` can be `None` for bonds without CUSIP/ISIN (from `_extract_bond_contract_identity()`), so it must be defensively initialized before adding keys.

**b) No FIFO pipeline changes needed**

`contract_identity` already flows through the entire FIFO pipeline: `txn_meta` → `OpenLot.contract_identity` → `ClosedTrade.contract_identity` → `RoundTrip.contract_identity`. No new fields on OpenLot, ClosedTrade, or RoundTrip needed — the detection logic reads directly from `rt.contract_identity`.

**c) Detection logic**

**File:** `trading_analysis/analyzer.py`

```python
from datetime import datetime

def _is_short_maturity_bond(rt: RoundTrip) -> bool:
    """Bond maturing within 1 year of entry is cash management."""
    if rt.instrument_type != "bond":
        return False
    maturity_str = (rt.contract_identity or {}).get("maturity_date")
    if not maturity_str:
        return False
    try:
        maturity = datetime.strptime(maturity_str, "%Y-%m-%d")
        days_to_maturity = (maturity - rt.entry_date).days
        return days_to_maturity <= 365
    except (ValueError, TypeError):
        return False
```

### Combined detection

**File:** `trading_analysis/analyzer.py`

```python
CASH_EQUIVALENT_TICKERS = _load_cash_equivalent_tickers()  # from YAML

def _is_cash_equivalent_round_trip(rt: RoundTrip) -> bool:
    # Tier 1: known cash-equivalent ETF
    if rt.symbol.upper() in CASH_EQUIVALENT_TICKERS:
        return True
    # Tier 2: short-maturity bond
    if _is_short_maturity_bond(rt):
        return True
    return False
```

Flag on RoundTrip: `is_cash_equivalent: bool = False` (defaulted), computed post-construction in the analyzer (after `from_lots()` builds the round-trip, the analyzer applies the detection function and sets the flag). No new `maturity_date` field on RoundTrip — detection reads from `rt.contract_identity.get("maturity_date")` directly.

### Exclude from all scorecard dimensions

```python
scoreable = [rt for rt in round_trips if not rt.synthetic and not rt.is_cash_equivalent]
```

Applied in: `compute_edge_grade`, `compute_sizing_grade`, `compute_discipline_grade`, `analyze_timing`, `analyze_post_exit`.

## Files Changed

| File | Change |
|------|--------|
| `config/cash_map.yaml` | Add `cash_equivalent_tickers` list |
| `providers/normalizers/plaid.py` | Include `maturity_date` in `contract_identity` for bond-type Plaid securities |
| `trading_analysis/fifo_matcher.py` | Add `is_cash_equivalent: bool = False` to RoundTrip dataclass |
| `trading_analysis/analyzer.py` | `_load_cash_equivalent_tickers()`, `_is_cash_equivalent_round_trip()`, `_is_short_maturity_bond()`, filter in all scoring/timing/post-exit functions |

## Tests

- Treasury note (bond, maturity_date in contract_identity, entry 2024-10-08) → Tier 2 match → cash equivalent
- SHY → Tier 1 match → cash equivalent
- SGOV → Tier 1 match (in proxy_by_currency) → cash equivalent
- Corporate bond with 10-year maturity → NOT cash equivalent
- AAPL → NOT cash equivalent
- Bond without maturity_date in contract_identity → NOT Tier 2 (no data to check)
- Cash-equivalent excluded from all scoring dimensions
- Sizing grade improves after exclusion
- maturity_date survives DB round-trip via contract_identity JSONB

## Verification

1. `pytest tests/trading_analysis/ -v` — all tests pass
2. MCP: sizing grade improves (Treasury note excluded)
3. Overall grade improves from C

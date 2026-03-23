# Exclude Cash-Equivalent Positions from Trading Scorecard

## Context

Treasury note position ($20K, -0.0% return) dominates sizing grade — largest position, near-zero return, creates F. It's cash management, not an active trade.

Plaid flags it as `is_cash_equivalent: false`, `type: fixed income`. But the maturity data shows it's a short-term hold: `maturity_date: 2025-10-15`, bought 2024-10-08, sold 2024-10-15 — 7 days, matured in ~1 year. Functionally cash management.

## Detection — Three-Tier Cascade

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

### Tier 2: instrument_type == "cash"

Already in transaction data. Catches literal cash positions (CUR:USD).

### Tier 3: Short-maturity bonds (< 1 year to maturity from entry)

Plaid securities already have `fixed_income.maturity_date`. Thread this through:

**a) Transaction store includes maturity_date in FIFO rows**

**File:** `inputs/transaction_store.py` — `load_fifo_transactions()`

When building FIFO rows from Plaid transactions, look up the Plaid security and include `maturity_date` in the transaction dict metadata:

```python
# In FIFO row construction for Plaid-sourced transactions:
txn["maturity_date"] = plaid_security.get("fixed_income", {}).get("maturity_date")
```

The transaction store already joins Plaid securities for other metadata — this is one more field extraction.

**b) Thread through FIFO pipeline**

**File:** `trading_analysis/fifo_matcher.py`

- `OpenLot`: extract `maturity_date` from `txn_meta` in `_process_entry()`
- `ClosedTrade`: copy from `OpenLot`
- `RoundTrip`: copy from first lot (bond identity doesn't change across lots)

Add `maturity_date: str | None = None` (defaulted) to all three dataclasses.

**c) Detection logic**

```python
from datetime import datetime, timedelta

def _is_short_maturity_bond(rt: RoundTrip) -> bool:
    """Bond maturing within 1 year of entry is cash management."""
    if rt.instrument_type != "bond" or not rt.maturity_date:
        return False
    try:
        maturity = datetime.strptime(rt.maturity_date, "%Y-%m-%d")
        days_to_maturity = (maturity - rt.entry_date).days
        return days_to_maturity <= 365
    except (ValueError, TypeError):
        return False
```

### Combined detection

```python
CASH_EQUIVALENT_TICKERS = _load_cash_equivalent_tickers()  # from YAML

def _is_cash_equivalent_round_trip(rt: RoundTrip) -> bool:
    # Tier 1: known cash-equivalent ETF
    if rt.symbol.upper() in CASH_EQUIVALENT_TICKERS:
        return True
    # Tier 2: cash instrument type
    if (rt.instrument_type or "").lower() == "cash":
        return True
    # Tier 3: short-maturity bond
    if _is_short_maturity_bond(rt):
        return True
    return False
```

Flag on RoundTrip: `is_cash_equivalent: bool = False`, computed in `from_lots()` or post-construction.

Use `any(lot.is_cash_equivalent for lot in lots)` pattern (consistent with synthetic).

### Exclude from all scorecard dimensions

```python
scoreable = [rt for rt in round_trips if not rt.synthetic and not rt.is_cash_equivalent]
```

Applied in: `compute_edge_grade`, `compute_sizing_grade`, `compute_discipline_grade`, `analyze_timing`, `analyze_post_exit`.

## Files Changed

| File | Change |
|------|--------|
| `config/cash_map.yaml` | Add `cash_equivalent_tickers` list |
| `inputs/transaction_store.py` | Include `maturity_date` from Plaid securities in FIFO rows |
| `trading_analysis/fifo_matcher.py` | Add `maturity_date` + `is_cash_equivalent` to OpenLot, ClosedTrade, RoundTrip |
| `trading_analysis/analyzer.py` | `_load_cash_equivalent_tickers()`, `_is_cash_equivalent_round_trip()`, filter in all scoring/timing/post-exit functions |

## Tests

- Treasury note (bond, maturity 2025-10-15, entry 2024-10-08) → Tier 3 match → cash equivalent
- SHY → Tier 1 match → cash equivalent
- SGOV → Tier 1 match (in proxy_by_currency) → cash equivalent
- CUR:USD → Tier 2 match → cash equivalent
- Corporate bond with 10-year maturity → NOT cash equivalent
- AAPL → NOT cash equivalent
- Bond without maturity_date → NOT Tier 3 (no data to check)
- Cash-equivalent excluded from all scoring dimensions
- Sizing grade improves after exclusion
- RoundTrip uses any() across lots for is_cash_equivalent

## Verification

1. `pytest tests/trading_analysis/ -v` — all tests pass
2. MCP: sizing grade improves (Treasury note excluded)
3. Overall grade improves from C

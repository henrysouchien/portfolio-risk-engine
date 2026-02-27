# Position Monitor Feature Plan

## Overview

Add a position monitor view with customer-requested metrics for real-time position tracking and P&L visibility.

**Requested Metrics:**
- Long/Short direction
- Shares
- Weighted entry price
- Current price
- Gross Exposure
- Net Exposure
- % PNL
- $ PNL

**Output Formats:** CLI, API, MCP tool

**Views:** Per-ticker (consolidated) as default, per-account as optional

---

## Metric Calculations

| Metric | Formula | Notes |
|--------|---------|-------|
| Direction | `"LONG"` if qty > 0 else `"SHORT"` | Derived from quantity sign |
| Shares | `abs(quantity)` | Absolute value |
| Weighted Entry Price | `abs(cost_basis) / abs(quantity)` | **Use abs()** - SnapTrade cost_basis is negative for shorts |
| Current Price | `price` | Already available; if missing, backsolve from `value / quantity` when both present |
| Gross Exposure | `abs(value)` | Absolute market value |
| Net Exposure | `value` | Signed (negative for shorts) |
| $ PNL | `(price - entry_price) * quantity` | Sign-safe formula (see below) |
| % PNL | `dollar_pnl / abs(cost_basis) * 100` | **Use abs() in denominator** |

### P&L Calculation (Provider-Agnostic)

**Problem:** SnapTrade uses signed value/cost_basis for shorts, but Plaid's behavior is unknown (institution-dependent). Using `value - cost_basis` only works if both are consistently signed.

**Solution:** Compute P&L from price and entry_price, which are always positive:

```python
def compute_pnl(quantity: float, price: float, cost_basis: float) -> tuple[float, float]:
    """Compute P&L in a provider-agnostic way.

    Uses (price - entry_price) * quantity which handles:
    - Long: qty > 0, profit when price > entry → positive P&L
    - Short: qty < 0, profit when price < entry → positive P&L (negative * negative)
    """
    # Use consistent validation helpers (avoids treating small values as falsy)
    if not is_valid_cost_basis(cost_basis):
        return None, None
    if quantity is None or quantity == 0:
        return None, None
    if not is_valid_price(price):
        return None, None

    # Entry price is always positive
    entry_price = abs(cost_basis) / abs(quantity)

    # This formula works regardless of how provider stores value/cost_basis
    dollar_pnl = (price - entry_price) * quantity

    # Use abs(cost_basis) in denominator for consistent % calculation
    pnl_percent = (dollar_pnl / abs(cost_basis)) * 100

    return dollar_pnl, pnl_percent
```

**Why this works:**
- Long (qty=100, entry=$150, price=$180): `(180-150) * 100 = $3000` profit ✓
- Short (qty=-50, entry=$250, price=$220): `(220-250) * -50 = $1500` profit ✓
- Short (qty=-50, entry=$250, price=$280): `(280-250) * -50 = -$1500` loss ✓

**Note:** This is more robust than `value - cost_basis` because it doesn't depend on provider sign conventions for value/cost_basis.

### Missing Price Handling

If `price` is missing but `value` and `quantity` are available, backsolve:
```python
if price is None and value is not None and quantity and quantity != 0:
    raw_price = value / quantity  # May be negative for shorts (value is signed)

    # Use raw_price for P&L calculation (preserves sign semantics)
    # dollar_pnl = (raw_price - entry_price) * quantity

    # Use display_price for output (always positive)
    display_price = abs(raw_price)
```

**Important:** Keep `raw_price` for P&L calculation and `display_price = abs(raw_price)` for output. If you apply `abs()` before P&L calculation, short position P&L will flip sign.

If neither `price` nor a valid `value/quantity` pair exists, set P&L to N/A.

### Short Position Math (Critical)

SnapTrade calculates `cost_basis = avg_purchase_price * units`. For shorts, `units` is negative, so `cost_basis` is also negative.

```python
# WRONG - depends on provider sign conventions:
dollar_pnl = value - cost_basis  # Only works if both are consistently signed

# CORRECT - provider-agnostic:
entry_price = abs(cost_basis) / abs(quantity)  # Always positive
dollar_pnl = (price - entry_price) * quantity  # Works for any provider
pnl_percent = dollar_pnl / abs(cost_basis) * 100  # Use abs() in denominator
```

**Code comment to add:**
```python
# NOTE: P&L uses (price - entry_price) * quantity instead of value - cost_basis.
# This is provider-agnostic and works regardless of how Plaid/SnapTrade sign
# value and cost_basis for short positions.
#
# Direction assumes negative quantity = short position.
# - SnapTrade: Confirmed (units negative, cost_basis = avg_price * units also negative)
# - Plaid: Institution-dependent (not explicitly documented)
```

---

## Multi-Currency Handling

**Problem:** Portfolio may contain USD, EUR, GBP positions. Summing exposures across currencies is misleading.

**Solution:** Group summary totals by currency:

```python
"summary": {
    "by_currency": {
        "USD": {
            "long_count": 12,               # non-cash long positions
            "short_count": 3,               # non-cash short positions
            "long_exposure": 150000.00,
            "short_exposure": 25000.00,
            "gross_exposure": 175000.00,
            "net_exposure": 125000.00,
            "total_cost_basis": 140000.00,  # sum(abs(cost_basis)) for positions with cost_basis
            "total_pnl_dollars": 12500.00,
            "total_pnl_percent": 8.93,      # total_pnl_dollars / total_cost_basis * 100
            "position_count": 15,           # non-cash positions only
            "positions_missing_cost_basis": 2
        },
        "EUR": {
            "long_count": 4,                # non-cash long positions
            "short_count": 1,               # non-cash short positions
            "long_exposure": 50000.00,
            # ...
        }
    },
    "primary_currency": "USD",  # Currency with largest gross exposure
    "has_multiple_currencies": true
}
```

**Summary % PnL Calculation:**
```python
# Use sum of abs(cost_basis) to match per-position % PnL calculation
total_cost_basis = sum(abs(p['cost_basis']) for p in positions_with_cost_basis)
total_pnl_percent = (total_pnl_dollars / total_cost_basis) * 100 if total_cost_basis else None
```

CLI output shows per-currency sections when multiple currencies detected.

---

## Missing/Invalid Cost Basis Handling

**Problem:** Some positions may have `cost_basis=None` or `NaN`. Affects entry price, P&L, and totals.

**Solution:**

### Validation Helpers
```python
import math
import pandas as pd

def is_valid_cost_basis(cost_basis) -> bool:
    """Check if cost_basis is valid (not None, NaN, Inf, or zero)."""
    if cost_basis is None:
        return False
    if pd.isna(cost_basis):  # Catches None, np.nan, pd.NA
        return False
    if isinstance(cost_basis, (int, float)) and (math.isnan(cost_basis) or math.isinf(cost_basis)):
        return False
    if cost_basis == 0:
        return False
    return True

def is_valid_price(price) -> bool:
    """Check if price is valid for P&L calculation (not None, NaN, or Inf)."""
    if price is None:
        return False
    if pd.isna(price):  # Catches None, np.nan, pd.NA
        return False
    if isinstance(price, (int, float)) and (math.isnan(price) or math.isinf(price)):
        return False
    # Note: price can be negative (from backsolve) - that's valid for P&L calc
    return True
```

### Per-Position Display
- Entry Price: "N/A"
- $ PNL: "N/A"
- % PNL: "N/A"
- Gross/Net Exposure: Still calculated (doesn't need cost_basis)

### Summary Totals
```python
# Filter to positions with valid cost_basis
positions_with_cost_basis = [
    p for p in positions
    if is_valid_cost_basis(p.get('cost_basis'))
]
positions_missing = len(positions) - len(positions_with_cost_basis)

# Only sum P&L for positions with valid cost_basis
total_pnl_dollars = sum(p['dollar_pnl'] for p in positions_with_cost_basis)
total_cost_basis = sum(abs(p['cost_basis']) for p in positions_with_cost_basis)
total_pnl_percent = (total_pnl_dollars / total_cost_basis) * 100 if total_cost_basis else None

# Exposure totals include ALL positions (don't need cost_basis)
gross_exposure = sum(abs(p['value']) for p in all_positions)
```

### Metadata Flags
- `positions_missing_cost_basis: 3`
- `has_partial_cost_basis: true`
- CLI footer: "* 3 positions excluded from P&L totals (missing cost basis)"

---

## Cash Position Handling

**Rule:** Cash positions are **excluded** from the monitor view.

**Rationale:** Cash has no entry price concept and including it would skew P&L metrics.

**Implementation:**
```python
# Filter out cash positions before processing
monitor_positions = [p for p in positions if p.get('type') != 'cash']
```

**Summary Clarification:**
- `total_positions`: Count of non-cash positions only
- `position_count` (per currency): Count of non-cash positions in that currency

**Note:** The raw `positions` array from the data layer may include cash. The monitor view filters them out, so `total_positions` in the monitor response will be less than the raw positions count.

---

## Implementation Plan

### 1. Add `to_monitor_view()` to PositionResult

**File:** `core/result_objects.py`

Add new method following existing `to_api_response()`, `to_cli_report()` patterns:

```python
def to_monitor_view(self, by_account: bool = False) -> Dict[str, Any]:
    """Position monitor with exposure and P&L metrics.

    Args:
        by_account: If True, show per-account breakdown.
                   If False, show consolidated per-ticker view.

    Returns:
        Dict with positions (enhanced with metrics) and portfolio summary.

    Note:
        - Cash positions are excluded (no entry price concept)
        - total_positions reflects non-cash count only
    """
```

**Return Structure:**
```python
{
    "status": "success",
    "module": "positions",
    "view": "monitor",
    "timestamp": "2026-01-30T10:00:00",
    "summary": {
        "by_currency": {
            "USD": {
                "long_count": 42,                # non-cash long positions
                "short_count": 3,                # non-cash short positions
                "long_exposure": 850000.00,
                "short_exposure": 50000.00,
                "net_exposure": 800000.00,
                "gross_exposure": 900000.00,
                "total_cost_basis": 750000.00,   # sum(abs(cost_basis))
                "total_pnl_dollars": 100000.00,
                "total_pnl_percent": 13.33,      # total_pnl_dollars / total_cost_basis * 100
                "position_count": 45,            # non-cash positions only
                "positions_missing_cost_basis": 0
            }
        },
        "primary_currency": "USD",
        "has_multiple_currencies": false,
        "has_partial_cost_basis": false,
        "total_positions": 45,  # excludes cash
        "cash_positions_excluded": 2  # how many cash positions were filtered out
    },
    "positions": [
        {
            "ticker": "AAPL",
            "name": "Apple Inc.",
            "type": "equity",
            "currency": "USD",
            "direction": "LONG",
            "shares": 100.0,
            "weighted_entry_price": 150.00,  # null if cost_basis invalid
            "current_price": 180.45,
            "gross_exposure": 18045.00,
            "net_exposure": 18045.00,
            "dollar_pnl": 3045.00,  # null if cost_basis invalid
            "pnl_percent": 20.30,   # null if cost_basis invalid
            # Optional per-account fields (when by_account=True)
            "account_name": "Schwab Individual",
            "brokerage_name": "Schwab",
        },
        # ... more positions (cash excluded)
    ],
    "metadata": {
        "consolidated": true,
        "by_account": false,
        "sources": ["plaid", "snaptrade"],
        "from_cache": true,
        "cache_age_hours": 2.5,
    }
}
```

### 2. Add `to_monitor_cli()` for CLI Table Output

**File:** `core/result_objects.py`

```python
def to_monitor_cli(self, by_account: bool = False) -> str:
    """CLI table format for position monitor."""
```

**Table Format:**
```
POSITION MONITOR (excludes cash)
================================

USD POSITIONS (45)
─────────────────────────────────────────────────────────────────────────────────────────────────────────────
Ticker   Name                 Dir    Shares    Entry     Price    Gross Exp    Net Exp      $ PnL    % PnL
─────────────────────────────────────────────────────────────────────────────────────────────────────────────
AAPL     Apple Inc.          LONG    100.00   $150.00   $180.45   $18,045.00  $18,045.00   $3,045.00   20.30%
MSFT     Microsoft Corp      LONG     50.00   $280.00   $420.00   $21,000.00  $21,000.00   $7,000.00   50.00%
XYZ      XYZ Corp            SHORT   200.00    $50.00    $45.00    $9,000.00  -$9,000.00   $1,000.00   10.00%
UNKN     Unknown Pos         LONG     10.00       N/A    $25.00      $250.00     $250.00         N/A      N/A
...

USD SUMMARY
─────────────────────────────────────────────────────────────────────────────────────────────────────────────
Long Exposure:    $850,000.00    (42 positions)
Short Exposure:    $50,000.00    (3 positions)
Net Exposure:     $800,000.00
Gross Exposure:   $900,000.00
─────────────────────────────────────────────────────────────────────────────────────────────────────────────
Total Cost Basis: $750,000.00    (sum of |cost_basis|)
Total $ PnL:      $100,000.00
Total % PnL:           13.33%

* 1 position excluded from P&L totals (missing cost basis)
* 2 cash positions excluded from monitor view

EUR POSITIONS (5)
─────────────────────────────────────────────────────────────────────────────────────────────────────────────
...
```

### 3. Extend MCP Tool with "monitor" Format

**File:** `mcp_tools/positions.py`

Update format literal and add by_account parameter:

```python
def get_positions(
    user_email: Optional[str] = None,
    consolidate: bool = True,
    format: Literal["full", "summary", "list", "by_account", "monitor"] = "full",
    brokerage: Optional[str] = None,
    by_account: bool = False,  # NEW: For monitor view granularity
    use_cache: bool = True,
    force_refresh: bool = False
) -> dict:
```

**Fix consolidation guard** to handle monitor format with by_account:

```python
# Don't consolidate when filtering by brokerage, grouping by account,
# or monitor with by_account=True
effective_consolidate = (
    consolidate
    and not brokerage
    and format != "by_account"
    and not (format == "monitor" and by_account)
)
```

Add routing logic:

```python
elif format == "monitor":
    return result.to_monitor_view(by_account=by_account)
```

**Update TOOL_METADATA:**

```python
TOOL_METADATA = {
    "name": "get_positions",
    "description": "Get current portfolio positions from brokerage accounts. Supports filtering by brokerage, grouping by account, and monitor view with P&L metrics.",
    "parameters": {
        "type": "object",
        "properties": {
            "user_email": {
                "type": "string",
                "description": "User email (optional, uses default if not provided)"
            },
            "consolidate": {
                "type": "boolean",
                "default": True,
                "description": "Whether to merge same tickers across accounts"
            },
            "format": {
                "type": "string",
                "enum": ["full", "summary", "list", "by_account", "monitor"],
                "default": "full",
                "description": "Output format: full (all fields), summary (stats only), list (tickers+values), by_account (grouped), monitor (P&L metrics)"
            },
            "brokerage": {
                "type": "string",
                "description": "Filter to a specific brokerage (e.g., 'Schwab', 'Interactive Brokers'). Case-insensitive partial match."
            },
            "by_account": {
                "type": "boolean",
                "default": False,
                "description": "For monitor format: show per-account breakdown instead of consolidated"
            },
            "use_cache": {
                "type": "boolean",
                "default": True,
                "description": "Use 24-hour cache when available"
            },
            "force_refresh": {
                "type": "boolean",
                "default": False,
                "description": "Bypass cache and fetch fresh data"
            }
        }
    }
}
```

### 4. Add CLI Flags to run_positions.py

**File:** `run_positions.py`

```python
parser.add_argument(
    "--monitor",
    action="store_true",
    help="Show monitor view with P&L and exposure metrics"
)
parser.add_argument(
    "--by-account",
    action="store_true",
    help="Show per-account breakdown instead of consolidated"
)
```

**Note:** Current default is `consolidated=False`. Monitor mode should default to consolidated:

```python
# Monitor mode defaults to consolidated unless --by-account specified
if monitor and not by_account:
    consolidated = True
```

Output handling:

```python
if args.monitor:
    if args.format == "json":
        print(json.dumps(result.to_monitor_view(by_account=args.by_account), indent=2))
    else:
        print(result.to_monitor_cli(by_account=args.by_account))
```

### 5. Add API Route (Optional)

**File:** `routes/snaptrade.py` or `routes/plaid.py` (routes/positions.py doesn't exist)

```python
@router.get("/positions/monitor")
def get_position_monitor(
    by_account: bool = Query(False, description="Show per-account breakdown"),
    user_email: str = Query(..., description="User email"),
):
    """Get position monitor with exposure and P&L metrics."""
    position_service = PositionService(user_email=user_email)
    result = position_service.get_all_positions(consolidate=not by_account)
    return result.to_monitor_view(by_account=by_account)
```

---

## Files to Modify

| File | Changes |
|------|---------|
| `core/result_objects.py` | Add `to_monitor_view()`, `to_monitor_cli()` methods |
| `mcp_tools/positions.py` | Add "monitor" format, `by_account` param, fix consolidation guard, update TOOL_METADATA |
| `run_positions.py` | Add `--monitor`, `--by-account` CLI flags, default consolidation for monitor |
| `routes/snaptrade.py` | (Optional) Add `/positions/monitor` endpoint |

---

## Edge Cases

| Case | Handling |
|------|----------|
| Zero quantity | Skip position or show 0 for all calculated fields |
| None cost_basis | Show "N/A" for entry/P&L; exclude from P&L totals |
| NaN/Inf cost_basis | Treat as missing; use `is_valid_cost_basis()` helper |
| Zero cost_basis | Treat as missing (avoid division by zero) |
| Cash positions | **Exclude** from monitor view; track count in `cash_positions_excluded` |
| Short positions | qty < 0; use `(price - entry) * qty` for P&L |
| Multi-currency | Group summaries by currency; don't sum across currencies |
| None currency | Normalize to `"UNKNOWN"` at position level (not just summary) |
| Missing price/qty with cost_basis | Exclude from `pnl_contributing_cost_basis` to avoid % PnL dilution |

## Implementation Notes

### Currency Normalization
Position-level `currency` is normalized to `"UNKNOWN"` if `None`, matching summary bucket keys. This allows API consumers to directly join positions to their summary buckets without special-casing.

### P&L Denominator (Avoiding Dilution)
The summary includes two cost basis fields:
- `total_cost_basis`: Sum of `abs(cost_basis)` for all positions with valid cost_basis
- `pnl_contributing_cost_basis`: Sum only for positions where P&L was actually calculated

`total_pnl_percent` uses `pnl_contributing_cost_basis` as the denominator. This prevents positions with valid cost_basis but missing price/quantity from diluting the portfolio % P&L.

### Exposure and Count Consistency
Long/short exposure totals only include positions with valid quantity. This keeps exposure totals consistent with `long_count`/`short_count`. Positions with `value` but invalid quantity (rare data quality issue) are excluded from exposure aggregation.

---

## Short Position Representation

**Status:** Confirmed for SnapTrade, assumed for Plaid

| Provider | Short = Negative Qty? | Cost Basis Sign | Value Sign | Source |
|----------|----------------------|-----------------|------------|--------|
| SnapTrade | Yes | Negative | Negative | [Docs](https://docs.snaptrade.com/reference/Account%20Information/AccountInformation_getUserHoldings), `snaptrade_loader.py:749` |
| Plaid | Likely | Unknown | Unknown | Institution-dependent |

**Mitigation:** Use `(price - entry_price) * quantity` for P&L instead of `value - cost_basis`. This is provider-agnostic.

---

## Verification Plan

### 1. MCP Tool Tests

```python
# Consolidated monitor view (default)
get_positions(format="monitor")

# Per-account monitor view
get_positions(format="monitor", by_account=True)

# Filter by brokerage
get_positions(format="monitor", brokerage="Schwab")
```

### 2. CLI Tests

```bash
# Consolidated monitor view
python run_positions.py --user-email user@example.com --monitor

# Per-account monitor view
python run_positions.py --user-email user@example.com --monitor --by-account

# JSON output
python run_positions.py --user-email user@example.com --monitor --format json
```

### 3. Calculation Verification

- [ ] Entry price = `abs(cost_basis) / abs(shares)` (always positive)
- [ ] $ PNL = `(price - entry_price) * quantity` (provider-agnostic)
- [ ] % PNL = `dollar_pnl / abs(cost_basis) * 100`
- [ ] Summary total_cost_basis = `sum(abs(cost_basis))` for positions with valid cost_basis
- [ ] Summary total_pnl_percent = `total_pnl_dollars / total_cost_basis * 100`
- [ ] Positions with None/NaN/zero cost_basis excluded from P&L totals
- [ ] Cash positions excluded; `cash_positions_excluded` count accurate
- [ ] `total_positions` matches len(positions) in response (both exclude cash)
- [ ] Gross exposure always positive

### 4. Short Position Test (if available)

- [ ] Direction shows "SHORT"
- [ ] Entry price is positive
- [ ] Profitable short (price dropped) shows positive P&L
- [ ] Losing short (price rose) shows negative P&L

---

## Status

- [x] `to_monitor_view()` implementation
- [x] `to_monitor_cli()` implementation
- [x] MCP tool implementation in `mcp_tools/positions.py`
- [x] MCP server update in `mcp_server.py` (must stay in sync with mcp_tools)
- [x] CLI flags
- [x] API route (`routes/positions.py` → `GET /api/positions/monitor`)
- [x] Testing & verification

### MCP Server Sync Note

The MCP server (`mcp_server.py`) must be kept in sync with `mcp_tools/positions.py`. When adding new parameters:

1. Update the implementation in `mcp_tools/positions.py`
2. Update the `@mcp.tool()` decorated function in `mcp_server.py`
3. Restart the MCP server (Claude Code needs to reload):
   ```bash
   claude mcp remove portfolio-mcp
   claude mcp add portfolio-mcp -e RISK_MODULE_USER_EMAIL=you@example.com -- python mcp_server.py
   ```

---

## TODO: Cash Position Handling

**Current behavior:** Cash positions are excluded from the monitor view entirely.

**Desired behavior:** Include cash in exposure calculations.

Cash should be treated as:
- **Direction:** LONG (positive quantity) or SHORT (negative, e.g., margin debit)
- **Entry Price:** N/A (no cost basis concept)
- **Current Price:** 1.00 (or FX rate for non-USD)
- **$ PNL / % PNL:** N/A (no cost basis)
- **Gross Exposure:** `abs(value)` - contributes to total
- **Net Exposure:** `value` (signed) - contributes to total

**Impact on summary:**
- `gross_exposure` should include cash
- `net_exposure` should include cash
- `long_exposure` / `short_exposure` should include cash based on sign
- `long_count` / `short_count` should include cash positions

**Implementation:** Simple change - instead of filtering out cash, include it in the exposure aggregation but skip P&L calculations (already handled by missing cost_basis logic).

**CLI display:** Could show cash in a separate section or inline with other positions (with N/A for Entry/P&L columns).

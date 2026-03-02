# Fix: `preview_trade` Returns Infinity for FIG

## Context

`preview_trade` for FIG returned `estimated_total: 1.7976931348623157e+308` (IEEE 754 max float) and the same for `estimated_commission`, while `estimated_price` was correct ($28.82). Other tickers (AAPL) worked fine. The max-float value propagated through the entire pipeline uncaught.

First encountered: 2026-03-02 (trade journal live test).

## Root Cause

**IBKR's `whatIfOrder()` returns `sys.float_info.max` (`1.7976931348623157e+308`) as a sentinel** meaning "commission not available." This is a known IBKR behavior — they use max-float instead of None/NaN when the what-if engine can't compute the commission (likely when market is closed or contract isn't fully loaded). The condition is **transient** — FIG previews correctly during market hours with a fresh TWS connection.

**Investigation confirmed:**
- Trade routing is correct — IBKR account (`cb7a1987-...`) routes to IBKR adapter via `TRADE_ACCOUNT_MAP`. No silent fallback to SnapTrade.
- SnapTrade doesn't allow trading on IBKR accounts, so silent adapter fallback is not possible for this case.
- FIG previews fine through SnapTrade on Schwab accounts (`estimated_total: 293.70`).
- FIG previews fine through IBKR when TWS is freshly connected during market hours (`estimated_total: 297.70`, `estimated_commission: 1.0`).

**The bug is that nothing in our pipeline rejects non-finite floats:**

1. `brokerage/ibkr/adapter.py` line 265: `float(order_state.commission)` accepts max-float without checking
2. `_to_float()` (9 copies) — `float(inf)` succeeds, no `math.isinf()` check. Located in: `snaptrade/adapter.py`, `snaptrade/_shared.py`, `trade_execution_service.py`, `ibkr/adapter.py`, `schwab/adapter.py`, `brokerage/_vendor.py`, `providers/schwab_positions.py`, `snaptrade_loader.py`, `portfolio_risk_engine/_vendor.py`
3. `make_json_safe()` (4 copies) — `isinstance(inf, float)` is True, returns as-is. NaN check exists in some but no Infinity check in any. Located in: `utils/serialization.py`, `brokerage/_vendor.py`, `portfolio_risk_engine/_vendor.py`, `risk_module_secrets/serialization.py`
4. `trade_execution_service.py` lines 374 AND 555: `_to_float(preview.estimated_commission) or 0.0` coerces `None` commission back to `0.0`, then recomputes total — defeating the adapter's None semantics. Line 374 is preview_order, line 555 is preview_futures_roll.
5. `brokerage/ibkr/adapter.py` line 368: futures roll preview also uses `_to_float(...) or 0.0` on whatIfOrder commission — same sentinel leak path as the equity preview

### Data flow

```
IB Gateway whatIfOrder() → order_state.commission = 1.7976931348623157e+308 (sentinel)
  → brokerage/ibkr/adapter.py:265: estimated_commission = float(order_state.commission) = 1.7e308
  → adapter.py:291: estimated_total = (price * qty) + 1.7e308 = 1.7e308
  → OrderPreview(estimated_total=1.7e308, estimated_commission=1.7e308)
  → TradeExecutionService [trade_execution_service.py:372]
    → _to_float(preview.estimated_total) = 1.7e308 (passes through)
    → validation: 1.7e308 > max_order_value → True (fires correctly, but value is misleading)
  → TradePreviewResult.to_api_response()
    → make_json_safe(payload with 1.7e308) → passes through
  → MCP response contains 1.7976931348623157e+308
```

## Implementation

### 0. Fix IBKR adapter — primary fix

**`brokerage/ibkr/adapter.py`** (~line 265): Detect IBKR's max-float sentinel and convert to `None`.

```python
import sys

_IBKR_MAX_FLOAT = sys.float_info.max  # 1.7976931348623157e+308

# In preview_order(), after whatIfOrder():
estimated_commission = None
commission_unavailable = False
try:
    raw_commission = float(order_state.commission)
    if raw_commission >= _IBKR_MAX_FLOAT or math.isinf(raw_commission):
        estimated_commission = None  # IBKR sentinel: "not available"
        commission_unavailable = True
    else:
        estimated_commission = raw_commission
except (TypeError, ValueError):
    estimated_commission = None
    commission_unavailable = True

# Don't compute estimated_total if commission is unknown
estimated_total = None
if estimated_price is not None and estimated_commission is not None:
    estimated_total = (estimated_price * float(quantity)) + estimated_commission
```

Also fix the **futures roll preview** at ~line 368 — same sentinel detection logic on `whatIfOrder()` commission.

When `commission_unavailable` is True, the `OrderPreview` should carry a warning. Add a `warnings` field to `OrderPreview` (currently absent):

```python
return OrderPreview(
    estimated_price=estimated_price,
    estimated_total=estimated_total,         # None when commission unknown
    estimated_commission=estimated_commission, # None when unavailable
    warnings=["IBKR could not compute commission for this order"] if commission_unavailable else [],
    ...
)
```

The warning propagates to `TradePreviewResult.validation.warnings` so the user sees a valid `estimated_price` but knows the total is incomplete.

**Key behavior:** The IBKR sentinel is treated as an error condition, not silently converted to a real number. The user gets `estimated_price` (useful) but `estimated_total` and `estimated_commission` are `None` with an explicit warning explaining why.

### 1. Fix `_to_float()` — 9 locations (defense in depth)

Add `math.isinf()` rejection after `float()` conversion. Return `None` for Infinity (same as NaN behavior).

**`brokerage/snaptrade/adapter.py`** (~line 374):
```python
import math

def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        result = float(value)
        if math.isinf(result):
            return None
        return result
    except (TypeError, ValueError):
        return None
```

**`brokerage/snaptrade/_shared.py`** (~line 158): Same change.

**`services/trade_execution_service.py`** (~line 2365): Same change (already has `bool` and `Decimal` guards, add `isinf` after).

**`brokerage/ibkr/adapter.py`** (~line 856): Same pattern — add `math.isinf()` check.

**`brokerage/schwab/adapter.py`** (~line 42): Same pattern (returns `None` on invalid, no default param) — add `math.isinf()` check, return `None`.

**`brokerage/_vendor.py`** (~line 70): Same pattern — add `math.isinf()` check.

**`providers/schwab_positions.py`** (~line 28): Has `default` param (returns 0.0 on invalid) — add `math.isinf()` check, return `default` on Infinity.

**`snaptrade_loader.py`** (~line 1794): Same pattern — add `math.isinf()` check.

**`portfolio_risk_engine/_vendor.py`** (~line 70): Same pattern — add `math.isinf()` check.

### 2. Fix `make_json_safe()` — 4 locations (defense in depth)

**`utils/serialization.py`** (~lines 53-56):
```python
elif isinstance(obj, float):
    if obj != obj or math.isinf(obj):  # NaN or Infinity
        return None
    return obj
```

Also fix the numpy float path to catch numpy Infinity:
```python
elif isinstance(obj, (np.float64, np.float32)):
    return None if (np.isnan(obj) or np.isinf(obj)) else float(obj)
```

**`brokerage/_vendor.py`** (~lines 48-49 and 64):
```python
# numpy floats
if np is not None and isinstance(obj, (np.float64, np.float32)):
    f = float(obj)
    return None if (math.isnan(f) or math.isinf(f)) else f

# plain floats
if isinstance(obj, (int, float, str, bool, type(None))):
    if isinstance(obj, float) and (obj != obj or math.isinf(obj)):
        return None
    return obj
```

**`portfolio_risk_engine/_vendor.py`** (~line 19): Has NO NaN or Infinity checks. Add both:
- numpy float path (~line 48): `return None if (np.isnan(obj) or np.isinf(obj)) else float(obj)`
- plain float path (~line 64): `if isinstance(obj, float) and (obj != obj or math.isinf(obj)): return None`

**`risk_module_secrets/serialization.py`** (~line 22): Same — add NaN + Infinity checks on float and numpy float paths.

### 3. Add `warnings` field to `OrderPreview`

**`brokerage/trade_objects.py`**: `OrderPreview` dataclass has no `warnings` field. Add with default to avoid breaking existing constructor calls:

```python
warnings: list[str] = field(default_factory=list)
```

### 4. Fix service-level commission/total override + wire warning propagation

**`services/trade_execution_service.py`**:

**4a. Don't coerce None commission to 0.0 (line 374):**

Current: `estimated_commission = _to_float(preview.estimated_commission) or 0.0`
Fix: `estimated_commission = _to_float(preview.estimated_commission)`

Update total recomputation (lines 375-376) to respect None commission:
```python
if estimated_total is None and estimated_price is not None:
    if estimated_commission is not None:
        estimated_total = (estimated_price * float(quantity)) + estimated_commission
    # else: leave estimated_total as None — commission unknown means total unknown
```

**4b. Same fix in `preview_futures_roll()` (line 555):** Same `or 0.0` removal and conditional total.

**4c. Fix IBKR adapter futures roll preview (~line 368):** Apply sentinel detection on `whatIfOrder()` commission (same as section 0).

**4d. Merge preview warnings into validation:**

`PreTradeValidation` is a dataclass with `warnings: List[str]`, so use `.warnings.extend()`:
```python
# After preview is obtained, merge adapter warnings into validation
if hasattr(preview, 'warnings') and preview.warnings:
    validation.warnings.extend(preview.warnings)
```

Place after the preview is obtained and before validation checks.

### 5. Add `import math` where missing

Check each modified file for existing `import math` — add if absent.

## Files Modified

| File | Change |
|------|--------|
| `brokerage/ibkr/adapter.py` | Primary fix: sentinel detection in `preview_order()` AND `preview_futures_roll()` (~L368). Also `_to_float()` isinf (~L856) |
| `brokerage/snaptrade/adapter.py` | `_to_float()`: add `math.isinf()` check (~2 lines) |
| `brokerage/snaptrade/_shared.py` | `_to_float()`: add `math.isinf()` check (~2 lines) |
| `brokerage/schwab/adapter.py` | `_to_float()`: add `math.isinf()` check (~2 lines) |
| `brokerage/_vendor.py` | `make_json_safe()`: add Infinity checks. `_to_float()`: add isinf check |
| `services/trade_execution_service.py` | `_to_float()` isinf. Remove `or 0.0` in preview_order (L374) AND preview_futures_roll (L555). Wire preview warnings |
| `utils/serialization.py` | `make_json_safe()`: add `math.isinf()` to float and numpy float paths (~2 lines) |
| `portfolio_risk_engine/_vendor.py` | `make_json_safe()`: add NaN + Infinity checks. `_to_float()`: add isinf check |
| `risk_module_secrets/serialization.py` | `make_json_safe()`: add NaN + Infinity checks on float and numpy float paths |
| `brokerage/trade_objects.py` | `OrderPreview`: add `warnings: list[str]` field with default |
| `providers/schwab_positions.py` | `_to_float()`: add `math.isinf()` check (~2 lines) |
| `snaptrade_loader.py` | `_to_float()`: add `math.isinf()` check (~2 lines) |

### Tests

1. **`_to_float` tests** — `float('inf')`, `float('-inf')`, `"inf"` string all return `None`
2. **`make_json_safe` tests** — dict containing `float('inf')` → value becomes `None`
3. **`make_json_safe` numpy path** — `np.float64('inf')` → `None`
4. **IBKR sentinel test** — mock `whatIfOrder()` returning `sys.float_info.max` → commission=None, total=None, warning present
5. **Warning propagation test** — `OrderPreview(warnings=["..."])` → appears in `TradePreviewResult.validation.warnings`

## Out of Scope

**Already-safe `_to_float()` copies** (9 more exist in `core/*_flags.py`, `options/portfolio_greeks.py`, `services/position_enrichment.py`, `mcp_tools/positions.py`) — these already use `math.isfinite()` and are safe. They handle internal computed values, not broker API responses.

**`or 0.0` patterns in execution paths** (e.g., `trade_execution_service.py:640,776,1057`, `ibkr/adapter.py:484,580,821`) — these are in order result/execution flows handling actual trade fills, not `whatIfOrder()` previews. The `or 0.0` is correct there.

**Direct `json.dumps()` calls** at `trade_execution_service.py:1698` and `:1066` — these write to DB (preview storage), not to MCP response. Low risk.

## What's NOT Changed

- SnapTrade API call parameters — we're sanitizing the response, not changing the request
- `estimated_price` computation — price comes from `trade.get("price")` which is correct for FIG
- Trade execution flow — only preview response parsing affected

## Verification

1. `pytest tests/` — existing tests pass (no regressions)
2. `preview_trade(ticker="FIG", quantity=10, side="BUY")` via MCP — when commission unavailable: `estimated_total=None`, `estimated_commission=None`, warning present
3. `preview_trade(ticker="AAPL", ...)` — still works (no regression on working tickers)

## Codex Review History (7 passes)

| Pass | Findings | Resolution |
|------|----------|------------|
| R1 | 3 missing `_to_float` copies, 1 missing `make_json_safe`, missing `OrderPreview.warnings`, missing warning wiring | Added to plan |
| R2 | `validation.setdefault()` type error (dataclass not dict), service `or 0.0` defeating None semantics, 3 more `_to_float` | Fixed propagation to use `.extend()`, added `or 0.0` removal, added 3 copies |
| R3 | Futures roll `or 0.0` paths (`trade_execution_service.py:555`, `ibkr/adapter.py:368`), 4th `make_json_safe` in `risk_module_secrets` | Added to plan |
| R4 | 9 more `_to_float` + many `or 0.0` — investigated: all already use `math.isfinite()` or are in execution paths | Documented as out of scope |
| R5 | Confirmed R4 conclusions. `trade_execution_service.py:640` is error fallback on quantity, not commission | Confirmed out of scope |
| R6 | `schwab/adapter.py` `_to_float` description wrong (returns None, not default) | Fixed description |
| R7 | **PASS** — plan complete and implementable | — |

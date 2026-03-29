# F12b: Dollar Beta Hedge Sizing (v2)

## Context

The hedge execute path sizes trades using `weight × portfolio_total`, which breaks when portfolio_total is wrong due to filtered shorts. Dollar beta matching computes trade quantities directly from factor betas and prices, bypassing the portfolio_total denominator entirely.

**Current flow**: factor service computes `suggested_weight = -beta_reduction` → execute path does `target_value = weight × portfolio_total` via `_build_target_weights` + `compute_rebalance_legs` → `shares = floor(target_value / price)`

**New flow**: execute path computes `notional = account_value × abs(suggested_weight)` server-side → `shares = floor(notional / live_price)` → decompose into SELL/SHORT or COVER/BUY using signed position quantities

The key insight: the notional hedge amount is computed **server-side** from the **selected account's** live positions, not from a frontend-supplied portfolio value. This ensures the hedge is sized to the account being traded, and the execute path only needs the live price to convert to share count.

## Codex v1 Review Findings Addressed

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 1 | Portfolio value vs. account mismatch — frontend-supplied `portfolio_value` may not match execution account | CRITICAL | Compute notional server-side from account positions (Step 2) |
| 2 | SELL/SHORT decomposition math wrong when existing position > target | CRITICAL | Clarify `shares` = hedge delta (not target); document with examples (Step 3) |
| 3 | `_build_rebalance_inputs` strips shorts via `max(qty, 0)` — COVER path unreachable | HIGH | New `_get_signed_held_quantities()` helper bypasses clamping (Step 1) |
| 4 | `TradeExecutionService` has its own short guard blocking SHORT on accounts with shorts | HIGH | Add `hedge_initiated` flag to bypass TES guard for hedge trades (Step 4) |
| 5 | Frontend data flow wrong — `portfolioValue` not available in `HedgeWorkflowDialog` | HIGH | No frontend notional computation needed; server computes it (Step 2) |

### Codex v2 Review Findings Addressed

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 1 | `current_portfolio_value` is long-only sum; factor service normalizes by gross exposure | CRITICAL | Use `account_gross_exposure = sum(abs(value))` instead (Step 2) |
| 2 | `hedge_initiated` not fully carried through execute and re-preview paths | HIGH | Persist in `broker_preview_data` JSONB; read back at execute; forward on re-preview (Step 4) |
| 3 | Test file `test_trade_execution_service.py` doesn't exist; missing e2e coverage | MEDIUM | Correct to `test_trade_execution_service_preview.py`; add tests #13-14 (Step 6) |

### Codex v3 Review Findings Addressed

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 1 | `hedge_initiated` not wired at route call-site (`preview_order()` call in hedging.py:348) | HIGH | Explicitly added to route call-site in Step 4 |
| 2 | Missing route-level and short-only-account tests | MEDIUM | Added tests #15-16 (Step 6) |

### Codex v4 Review Findings Addressed

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 1 | Re-preview path forwards hardcoded `True` instead of persisted value; non-hedge expired SHORT previews would bypass guard | HIGH | Forward persisted `hedge_initiated` from `broker_preview_data` (Step 4); added negative test #17 (Step 6) |

## What data already exists

The recommendation response provides the weight; the execute path already fetches account positions:

| Field | Where | Value |
|-------|-------|-------|
| `suggested_weight` | recommendation dict, passed in execute request | e.g., -0.107 |
| `consolidated_positions` | fetched server-side in `hedge_execute()` (line 250) | account's live positions |
| `current_portfolio_value` | computed server-side (line 284) | sum of position values |

**No new request fields needed.** The server has everything: `suggested_weight` from the request + account positions from the position service.

## Implementation Steps

### Step 1: Add `_get_signed_held_quantities()` helper

**File**: `routes/hedging.py` — new function after `_build_rebalance_inputs`

`_build_rebalance_inputs` clamps quantities to `max(qty, 0)` and skips `value <= 0` positions (lines 156, 162). This makes the COVER path unreachable. New helper returns signed quantities:

```python
def _get_signed_held_quantities(
    consolidated_positions: List[Dict[str, Any]],
) -> Dict[str, float]:
    """Return signed quantities for all non-cash positions (longs positive, shorts negative)."""
    quantities: Dict[str, float] = {}
    for position in consolidated_positions:
        ticker = normalize_ticker(position.get("ticker"))
        if not ticker or _is_cash_position(position, ticker):
            continue
        qty = safe_float(position.get("quantity"))
        if qty is not None:
            quantities[ticker] = quantities.get(ticker, 0.0) + float(qty)
    return quantities
```

### Step 2: Server-side notional computation in `hedge_execute`

**File**: `routes/hedging.py` — replace the `_build_target_weights` + `compute_rebalance_legs` pipeline (lines 293-315) with direct computation when `action == "preview"`

**Denominator choice**: The factor service normalizes weights by gross exposure (`sum(abs(v))` — see `PortfolioOffsetsData.normalized_weights()` in `data_objects.py:1730`). So `suggested_weight` lives in gross-exposure-normalized space. The execute path must use the same base: **account gross non-cash exposure** = `sum(abs(value))` for all non-cash positions. NOT `current_portfolio_value` from line 284, which is long-only (skips shorts via `_build_rebalance_inputs`).

```python
# Compute account gross exposure (consistent with factor service weight normalization)
account_gross_exposure = 0.0
for position in consolidated_positions:
    ticker = normalize_ticker(position.get("ticker"))
    if not ticker or _is_cash_position(position, ticker):
        continue
    value = safe_float(position.get("value"))
    if value is not None:
        account_gross_exposure += abs(float(value))

if account_gross_exposure <= 0:
    raise HTTPException(status_code=400, detail=f"No non-cash exposure found for account {account_id}")

# Dollar beta sizing: notional from ACCOUNT gross exposure × hedge weight
notional_value = account_gross_exposure * abs(float(suggested_weight))

# Fetch live price for hedge ticker
current_prices, price_warnings = fetch_current_prices(
    [hedge_ticker],
    instrument_types=instrument_types or None,
)
warnings.extend(price_warnings)

hedge_price = safe_float(current_prices.get(hedge_ticker))
if not hedge_price or hedge_price <= 0:
    raise HTTPException(status_code=400, detail=f"Could not fetch price for {hedge_ticker}")

hedge_shares = math.floor(notional_value / hedge_price)
if hedge_shares <= 0:
    return {
        "status": "success",
        "trades": [],
        "summary": {"trade_count": 0, "sell_count": 0, "buy_count": 0, "net_cash_impact": 0},
        "warnings": ["Hedge amount too small for even 1 share."],
    }

# Decompose into legs using signed quantities (Step 3)
signed_quantities = _get_signed_held_quantities(consolidated_positions)
raw_legs = _decompose_hedge_legs(hedge_ticker, hedge_shares, float(suggested_weight), signed_quantities)
```

**Why server-side (v1 Finding #1)?** The `portfolio_value` in the recommendation response is the analyzed portfolio's value, which may span multiple accounts. Computing from the account's own positions ensures the hedge is sized correctly.

**Why gross exposure (v2 Finding #1)?** The factor service normalizes weights by `sum(abs(v))`. Using `current_portfolio_value` (long-only sum from `_build_rebalance_inputs`) would under-size hedges for accounts with shorts and fail entirely for short-only accounts.

### Step 3: SELL/SHORT and COVER/BUY decomposition

**File**: `routes/hedging.py` — new function `_decompose_hedge_legs`

**Key semantic (Finding #2)**: `hedge_shares` is a **delta** (amount of hedging to add), NOT a target position. If the recommendation says "short 40 shares of SPY", that means "add 40 shares of short exposure" — which could be satisfied by selling 40 from an existing long, shorting 40 new, or a mix.

```python
def _decompose_hedge_legs(
    ticker: str,
    hedge_shares: int,
    suggested_weight: float,
    signed_quantities: Dict[str, float],
) -> List[tuple[str, str, float]]:
    """Decompose a hedge into SELL/SHORT or COVER/BUY legs based on existing position."""
    held = int(signed_quantities.get(ticker, 0))
    legs: List[tuple[str, str, float]] = []

    if suggested_weight < 0:
        # Going shorter by hedge_shares
        if held > 0:
            # Sell from long position first, then short the remainder
            sell_qty = min(hedge_shares, held)
            short_qty = hedge_shares - sell_qty
            if sell_qty > 0:
                legs.append((ticker, "SELL", float(sell_qty)))
            if short_qty > 0:
                legs.append((ticker, "SHORT", float(short_qty)))
        else:
            # Already flat or short — pure SHORT
            legs.append((ticker, "SHORT", float(hedge_shares)))
    else:
        # Going longer by hedge_shares (beta alternatives)
        if held < 0:
            # Cover short position first, then buy the remainder
            cover_qty = min(hedge_shares, abs(held))
            buy_qty = hedge_shares - cover_qty
            if cover_qty > 0:
                legs.append((ticker, "COVER", float(cover_qty)))
            if buy_qty > 0:
                legs.append((ticker, "BUY", float(buy_qty)))
        else:
            # Already flat or long — pure BUY
            legs.append((ticker, "BUY", float(hedge_shares)))

    return legs
```

**Examples** (hedge_shares=40, going shorter):
- Hold +200 SPY → SELL(40). End at +160. Beta reduction = 40 × price. ✓
- Hold +10 SPY → SELL(10) + SHORT(30). End at -30. Beta reduction = 40 × price. ✓
- Hold 0 SPY → SHORT(40). End at -40. ✓
- Hold -30 SPY → SHORT(40). End at -70. ✓ (adding more hedge)

### Step 4: Relax short guards for hedge-initiated trades

**File**: `routes/hedging.py:262-276` — remove route-level short guard

The route-level guard that returns error for ANY short position in the account is fully removed. The notional path computes sizing from `account_value × abs(weight)`, so existing shorts don't corrupt the calculation.

**File**: `services/trade_execution_service.py` — `_validate_pre_trade` (line 2454) and `execute_order` (line 1665)

The TES has its own dual-layer short guard (Finding #4):
- Preview: `_validate_pre_trade` rejects SHORT when `_find_existing_short_ticker()` returns a hit
- Execute: `execute_order` re-checks at execution time with force-refreshed positions

Add `hedge_initiated: bool = False` parameter to `preview_order()`. When `True`, skip the existing-short-ticker check and persist the flag for execution:

```python
# In _validate_pre_trade (line 2454):
if side == "SHORT" and not hedge_initiated:
    existing_short_ticker = self._find_existing_short_ticker(live_positions or [])
    if existing_short_ticker:
        errors.append(...)
```

**Persistence through preview→execute→re-preview (v2 Finding #2)**:

1. **Preview**: merge `{"hedge_initiated": True}` into `broker_preview_data` JSONB when storing the preview record (line ~2697)
2. **Execute**: read `hedge_initiated` from the stored preview's `broker_preview_data` before the SHORT guard at line 1665:
   ```python
   preview_data = row.get("broker_preview_data") or {}
   hedge_initiated = preview_data.get("hedge_initiated", False)
   if preview_side == "SHORT" and not hedge_initiated:
       # existing short guard check
   ```
3. **Re-preview (expired preview path, line ~1929)**: read `hedge_initiated` from the expired preview's `broker_preview_data` and forward the **persisted value** (not a hardcoded `True`) into the `preview_order()` call. This ensures non-hedge expired SHORT previews still hit the guard:
   ```python
   expired_preview_data = expired_row.get("broker_preview_data") or {}
   hedge_initiated = expired_preview_data.get("hedge_initiated", False)
   new_preview = self.preview_order(..., hedge_initiated=hedge_initiated)
   ```

**Route call-site (v3 Finding #1)**: In `routes/hedging.py` line 348, the `preview_order()` call must pass the flag:

```python
# In hedge_execute(), the preview loop (line 346-361):
for leg in trades:
    try:
        preview_result = trade_service.preview_order(
            account_id=account_id,
            ticker=leg["ticker"],
            side=leg["side"],
            quantity=leg["quantity"],
            order_type="Market",
            hedge_initiated=True,  # NEW: bypass TES short guard for hedge trades
        )
```

The `hedge_initiated` flag is only set by the hedge execute path in `routes/hedging.py`, preserving the safety guard for direct trading.

### Step 5: Frontend changes (minimal)

No `notional_value` in the request — server computes it. No `portfolioValue` threading needed (Finding #5 resolved).

**File**: `frontend/.../HedgeWorkflowDialog.tsx` — remove the short-account error display code (the error no longer occurs since the route guard is removed)

### Step 6: Tests

**New file**: `tests/routes/test_hedge_dollar_beta.py` (12 tests)

1. `test_gross_exposure_notional` — account with longs+shorts, verify notional uses `sum(abs(value))` not long-only sum
2. `test_notional_uses_account_positions` — ensure server computes from account, no frontend value
3. `test_backward_compat_long_only` — long-only account produces same results as before
4. `test_sell_from_long_then_short_remainder` — held +10, hedge_shares=40 → SELL(10) + SHORT(30)
5. `test_pure_sell_when_long_exceeds_hedge` — held +200, hedge_shares=40 → SELL(40) only, no SHORT
6. `test_pure_short_no_existing_position` — held 0, hedge_shares=40 → SHORT(40)
7. `test_short_adds_to_existing_short` — held -30, hedge_shares=40 → SHORT(40) (adds to short)
8. `test_cover_from_short_then_buy_remainder` — held -10, hedge_shares=40, weight>0 → COVER(10) + BUY(30)
9. `test_pure_buy_no_existing_position` — held 0, hedge_shares=40, weight>0 → BUY(40)
10. `test_existing_short_account_not_blocked` — account with shorts → hedge preview succeeds (guards bypassed via `hedge_initiated`)
11. `test_hedge_shares_zero_no_legs` — notional too small for 1 share → empty trades with message
12. `test_signed_quantities_helper` — `_get_signed_held_quantities` returns negative for shorts, positive for longs
13. `test_hedge_initiated_preview_to_execute` — `hedge_initiated=True` persisted in `broker_preview_data`, read back at execute, SHORT guard bypassed
14. `test_hedge_initiated_repreview_on_expiry` — expired hedge preview re-previews with `hedge_initiated=True` forwarded
15. `test_route_passes_hedge_initiated_to_preview_order` — route-level: assert `preview_order()` is called with `hedge_initiated=True` for hedge previews
16. `test_short_only_account_gross_exposure_sizing` — short-only account (all negative values) → `account_gross_exposure = sum(abs(value))` → correct notional, no guard rejection
17. `test_non_hedge_expired_short_preview_still_guarded` — non-hedge SHORT preview expires → re-preview reads `hedge_initiated=False` from `broker_preview_data` → short guard still applies

**Updated file**: `tests/routes/test_hedging_short_support.py` — update guard removal tests
**Updated file**: `tests/services/test_trade_execution_service_preview.py` — add `hedge_initiated` bypass tests (preview + execute + re-preview paths)

## Files Changed

| File | Change |
|------|--------|
| `routes/hedging.py` | `_get_signed_held_quantities()`, `_decompose_hedge_legs()`, server-side notional, remove route short guard |
| `services/trade_execution_service.py` | `hedge_initiated` flag on `preview_order`, stored in preview metadata, checked at execute |
| `frontend/.../HedgeWorkflowDialog.tsx` | Remove short-account error display (minor) |
| `tests/routes/test_hedge_dollar_beta.py` | New — 17 tests |
| `tests/routes/test_hedging_short_support.py` | Update guard removal tests |
| `tests/services/test_trade_execution_service_preview.py` | `hedge_initiated` bypass tests (preview, execute, re-preview) |

## NOT Changed

- `HedgeExecuteRequest` — no new fields (server computes notional from account positions)
- `services/factor_intelligence_service.py` — recommendation logic untouched
- `mcp_tools/trading_helpers.py` — `compute_rebalance_legs` untouched (used for non-hedge rebalance)
- `APIService.ts`, `HedgingAdapter.ts`, `catalog/types.ts` — no notional plumbing needed
- `_compute_weight_impact` — untouched (weight-based validation is a separate concern)

## Verification

1. `pytest tests/routes/test_hedge_dollar_beta.py -v`
2. L2 regression: `pytest tests/routes/test_hedging_short_support.py -v`
3. L3 regression: `pytest tests/services/test_short_execution.py -v`
4. TES regression: `pytest tests/services/test_trade_execution_service_preview.py -v`
5. Manual: account with existing short → hedge preview → trades generated correctly

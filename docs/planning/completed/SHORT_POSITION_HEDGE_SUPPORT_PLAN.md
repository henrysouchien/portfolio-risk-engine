# F12: Short Position Support for Hedge Tool

## Context

The hedge analysis tool recommends "direct offset" hedges — shorts of factor ETFs to neutralize portfolio exposure. The redesign (commit `f31528f5`) already wires negative `suggested_weight` values through the frontend, and the adapter labels them as "Short XYZ." But two downstream clamps prevent the execution pipeline from producing correct previews and trade legs.

**Goal**: Remove the clamps so that (1) the What-If preview correctly shows short position impact, and (2) trade leg generation produces SHORT orders. Broker-side execution (margin checks, locates) is deferred (Level 3).

## Blockers

### Blocker 1: `routes/hedging.py:135-138` — target weight floor
```python
target_weights[hedge_ticker] = max(0.0, current + suggested_weight)
```
Only affects `/execute` action="preview" path (line 274). The `/preview` endpoint (line 186) already passes deltas directly to ScenarioService via `_to_delta_percent()` which preserves negatives.

### Blocker 2: `mcp_tools/trading_helpers.py:99-100` — held quantity cap
```python
quantity = min(quantity, math.floor(float(held_quantities.get(ticker, 0.0))))
```
Caps sell quantity to held shares. A short of something you don't hold produces 0 quantity → no trade leg.

### Also: `routes/hedging.py:152,158` — value filter + quantity clamp in `_build_rebalance_inputs`

Two guards in `_build_rebalance_inputs()`:
- Line 152: `if value is None or value <= 0: continue` — discards positions with non-positive market value (existing shorts have negative value)
- Line 158: `max(float(quantity or 0.0), 0.0)` — clamps quantities non-negative

Together these mean: if an account already holds a short position, it won't appear in `position_values` or `held_quantities`, causing wrong current weights and wrong SELL/SHORT decomposition. **Defer** — Level 1+2 covers initiating new shorts from the hedge tool (ticker not currently held). Correctly accounting for existing short positions in the current-state snapshot is Level 3 work that also affects rebalance and basket trading.

### NOT blockers (already work):
- `HedgeTool.tsx:357-370` — delta formatting preserves negative sign ("-5%")
- What-If tool / ScenarioService — accepts negative deltas
- Frontend HedgingAdapter — detects negative weights, labels as 'short'
- `TradeType` enum — has SHORT and COVER

### Execution path behavior for SHORT legs

When the hedge trade leg decomposition produces any SHORT legs, the hedge execute preview returns all legs as **informational only** — no broker `preview_order` calls are made, no `preview_id`s are created or persisted. Every leg gets an error message explaining that short selling requires broker margin support. The response status is `"error"`.

This is a hard server-side block (Step 2d). The user sees the trade legs with quantities and prices (useful for understanding the hedge), plus a clear explanation. The "Test in What-If" path still works for impact analysis since it uses `ScenarioService.analyze_what_if()` with delta_changes, which already handles negative weights.

The frontend's step 3 `canContinueFromStep3` gate (`HedgeWorkflowDialog.tsx:421`) checks `previewIds.length > 0` and blocks progression since no `preview_id`s exist.

## Callers of `compute_rebalance_legs()`

Three callers exist:

1. **`routes/hedging.py:290`** — hedge execute preview. This is the target path for this change.
2. **`mcp_tools/rebalance.py`** — rebalance MCP tool. Protected: `_normalize_weight_map(allow_negative=False)` at line 299 rejects negative target weights before `compute_rebalance_legs()` is called. SHORT legs cannot be generated here.
3. **`mcp_tools/basket_trading.py:388`** — basket rebalance preview. **NOT protected**: basket custom weights in `baskets.py:239` (`_normalize_weights()`) accept any finite float, including negatives. After this change, a basket with a negative weight would produce SHORT legs.

### Safety guard for basket trading (Step 2b)

Add a non-negative weight validation **at the basket-trading rebalance call site**, not in the shared `_normalize_weights()` helper. The shared helper (`baskets.py:239`) is used by basket create/update/read/analyze paths (lines 324, 510, 672, 897) — adding a guard there could break existing baskets that happen to have negative weights stored. Instead, guard narrowly at the rebalance preview path only.

**File**: `mcp_tools/basket_trading.py`, inside the `if action_norm in {"sell", "rebalance"}` block (line 324), **before** the "no positions found" early return at line 333. The guard must go before that early return — otherwise a negative-weight basket with zero held positions would hit the early return and get a successful empty preview instead of being rejected.

```python
# Add after held_quantities is built (line 332), before the all(...) early return (line 333)
if action_norm == "rebalance" and any(w < 0 for w in resolved_weights.values()):
    negative_tickers = [t for t, w in resolved_weights.items() if w < 0]
    return _format_preview_result(
        BasketTradePreviewResult(
            status="error",
            basket_name=basket_name,
            action=action_norm,
            preview_legs=[],
            total_estimated_cost=0.0,
            total_legs=0,
            buy_legs=0,
            sell_legs=0,
            skipped_legs=0,
            warnings=[f"Negative weights not supported for basket rebalance: {', '.join(negative_tickers)}"],
        ),
        format,
    )
```

This is narrowly scoped to the rebalance action only. Basket create/update/read/analyze and sell/buy actions are unaffected — no migration story needed. If basket shorting is desired later, this guard can be relaxed.

Also update `_count_rebalance_skipped()` in `basket_trading.py:220-221` to match the new `compute_rebalance_legs` logic:

```python
# Before
if delta < 0:
    quantity = min(quantity, math.floor(float(held_quantities.get(ticker, 0.0))))

# After
if delta < 0:
    held = max(math.floor(float(held_quantities.get(ticker, 0.0))), 0)
    quantity = min(quantity, held) + max(quantity - held, 0)
```

With the call-site guard above, negative weights can't reach here in practice. But keeping the diagnostic consistent with `compute_rebalance_legs` is defensive best practice.

## Implementation Steps

### Step 1: Remove `max(0.0)` clamp in `_build_target_weights()`

**File**: `routes/hedging.py:135-138`

```python
# Before
target_weights[hedge_ticker] = max(
    0.0,
    float(target_weights.get(hedge_ticker, 0.0)) + float(suggested_weight),
)

# After
target_weights[hedge_ticker] = (
    float(target_weights.get(hedge_ticker, 0.0)) + float(suggested_weight)
)
```

Simple removal. The function's only caller is `hedge_execute()` at line 274.

### Step 2: Decompose SELL into SELL + SHORT in `compute_rebalance_legs()`

**File**: `mcp_tools/trading_helpers.py:97-102`

When `delta < 0` (need to reduce/short), split into:
- SELL up to held quantity (close long position)
- SHORT the remainder (open short position)

```python
# Before
if delta < 0:
    quantity = math.floor(abs(delta) / price)
    if held_quantities is not None:
        quantity = min(quantity, math.floor(float(held_quantities.get(ticker, 0.0))))
    if quantity > 0:
        sells.append((ticker, "SELL", float(quantity)))

# After
if delta < 0:
    held = max(math.floor(float(held_quantities.get(ticker, 0.0))), 0) if held_quantities is not None else None

    if weight < 0 and held is not None:
        # Target weight is negative → SELL all held, then SHORT the
        # target short quantity. Compute SHORT from target_value and
        # live price directly to avoid snapshot/live price divergence.
        sell_qty = held
        target_short_value = abs(target_value)  # target_value is negative
        short_qty = math.floor(target_short_value / price)
    elif held is not None:
        # Non-negative target: cap sell to held shares (existing behavior)
        total_qty = math.floor(abs(delta) / price)
        sell_qty = min(total_qty, held)
        short_qty = 0
    else:
        # held_quantities is None (never happens in practice)
        total_qty = math.floor(abs(delta) / price)
        sell_qty = total_qty
        short_qty = 0

    if sell_qty > 0:
        sells.append((ticker, "SELL", float(sell_qty)))
    if short_qty > 0:
        sells.append((ticker, "SHORT", float(short_qty)))
```

**Key design decisions**:
1. SHORT legs only emitted when `weight < 0` (target weight is truly negative).
2. SHORT quantity computed from `target_value` and live `price` directly (`floor(abs(target_value) / price)`), NOT from the delta. This avoids snapshot/live price divergence inflating the SHORT leg.
3. SELL quantity for negative targets = all held shares (sell to zero before shorting).
4. Non-negative targets: existing behavior preserved (cap to held, no SHORT).
5. `held_quantities is None`: SELL only (backward compatible).

`target_value` is already computed at line 94 as `float(weight) * float(portfolio_total)` — it's negative when weight is negative, so `abs(target_value)` gives the dollar value of the short position.

### Step 2b: Add negative weight guard to basket rebalance path

**File**: `mcp_tools/basket_trading.py`, after line 332 (held_quantities built), before line 333 (early return)

Add a call-site guard before the "no positions" early return in the sell/rebalance block:
```python
if action_norm == "rebalance" and any(w < 0 for w in resolved_weights.values()):
    negative_tickers = [t for t, w in resolved_weights.items() if w < 0]
    return _format_preview_result(
        BasketTradePreviewResult(
            status="error",
            basket_name=basket_name,
            action=action_norm,
            preview_legs=[],
            total_estimated_cost=0.0,
            total_legs=0, buy_legs=0, sell_legs=0, skipped_legs=0,
            warnings=[f"Negative weights not supported for basket rebalance: {', '.join(negative_tickers)}"],
        ),
        format,
    )
```

Must go before the early return at line 333 — otherwise a negative-weight basket with zero held positions bypasses the guard. Narrowly scoped to rebalance action only. Does NOT touch the shared `_normalize_weights()` helper, so basket create/update/read/analyze paths are unaffected.

### ~~Step 2c~~ — NOT NEEDED

`_count_rebalance_skipped()` in `basket_trading.py:220-221` does **not** need updating. Step 2b blocks negative weights before they reach this code, so the diagnostic only sees non-negative targets. For non-negative targets, `compute_rebalance_legs` still caps to held shares (the `weight >= 0` branch preserves existing behavior). The diagnostic already matches. Changing it would regress normal positive-weight skipped-trade counting under price drift.

### Step 2d: Reject accounts with existing short positions — `routes/hedging.py`

Before building target weights (line 274), check if any position in the account has negative quantity (an existing short). If so, return an error — the snapshot logic (`_build_rebalance_inputs`) discards these positions, making current weights and SELL/SHORT decomposition unreliable.

```python
# After _build_rebalance_inputs (line 257), before current_weights (line 269)
for position in consolidated_positions:
    ticker = normalize_ticker(position.get("ticker"))
    if not ticker or _is_cash_position(position, ticker):
        continue  # negative cash = margin debt, not a short security
    qty = safe_float(position.get("quantity"))
    if qty is not None and qty < 0:
        return {
            "status": "error",
            "trades": [],
            "summary": {"trade_count": 0, "sell_count": 0, "buy_count": 0, "net_cash_impact": 0},
            "warnings": [
                f"Account contains existing short position ({ticker}). "
                "Hedge execution with existing shorts is not yet supported."
            ],
        }
```

Uses the existing `_is_cash_position()` helper (already imported in `hedging.py`, used at line 148). This skips `CUR:*` tickers and `type == "cash"` positions — negative cash represents margin debt, not a short security holding.

The `/preview` endpoint (What-If impact analysis) is unaffected — it uses ScenarioService with delta_changes, not the snapshot.

### Step 2e: Skip broker preview entirely when SHORT legs are present — `routes/hedging.py:326-350`

When `compute_rebalance_legs` produces any SHORT legs, the entire hedge is non-executable at Level 2 (broker doesn't support SHORT). Previewing just the SELL legs would create persisted executable previews that could be cherry-picked via direct API calls, leaving the account at 0% instead of the intended short position.

**Fix**: Before the `preview_order` loop, check if any trade leg has `side == "SHORT"`. If so, skip all broker previews and return all legs as informational with a clear error:

```python
# After building the trades list (line 317), before the preview_order loop (line 326)
has_short_legs = any(leg["side"] == "SHORT" for leg in trades)

if has_short_legs:
    for leg in trades:
        leg["error"] = (
            "Short selling requires broker margin support (not yet enabled). "
            "All legs in this hedge are non-executable."
        )
    return {
        "status": "error",
        "trades": trades,
        "summary": {
            "trade_count": len(trades),
            "sell_count": sell_count,
            "buy_count": buy_count,
            "net_cash_impact": round(total_sell_value - total_buy_value, 2),
        },
        "warnings": warnings + [
            "This hedge requires short selling, which is not yet supported by the broker. "
            "Use 'Test in What-If' to preview the impact."
        ],
    }
```

This is a hard server-side block: no `preview_id`s are created, no previews are persisted, no execution is possible. The response still contains the full trade leg details (tickers, sides, quantities, prices) for display, plus a clear explanation.

**No frontend changes needed**: The existing `previewIds` memo (`HedgeWorkflowDialog.tsx:206`) produces an empty array (no `preview_id`s in response). The `canContinueFromStep3` gate (`line 421`) checks `previewIds.length > 0`, so the user is blocked at step 3 with the error/warning visible. No new "partial" status concept needed.

### Step 3: Update summary counting in `routes/hedging.py:319-324`

```python
# Before
if side == "SELL":
    sell_count += 1
    total_sell_value += estimated_value
else:
    buy_count += 1
    total_buy_value += estimated_value

# After
if side in ("SELL", "SHORT"):
    sell_count += 1
    total_sell_value += estimated_value
else:
    buy_count += 1
    total_buy_value += estimated_value
```

### Step 4: Update summary counting in `mcp_tools/rebalance.py:462-467`

Same pattern:
```python
# Before
if side == "SELL":

# After
if side in ("SELL", "SHORT"):
```

The skipped_trades diagnostic at lines 404-406 does NOT need updating. Since `_normalize_weight_map(allow_negative=False)` at line 299 rejects negative target weights before this code runs, the held-quantity cap in the diagnostic is never reached for negative targets. Changing it would be dead code — leave as-is.

### Step 5: Update frontend TypeScript types

**File 1**: `frontend/packages/chassis/src/types/index.ts:443`
```typescript
// Before
side: 'BUY' | 'SELL';

// After
side: 'BUY' | 'SELL' | 'SHORT' | 'COVER';
```

**File 2**: `frontend/packages/ui/src/components/portfolio/HedgeWorkflowDialog.tsx:55`
```typescript
// Before
side: 'BUY' | 'SELL';

// After
side: 'BUY' | 'SELL' | 'SHORT' | 'COVER';
```

### Step 6: Tests

**New file**: `tests/mcp_tools/test_trading_helpers.py`

1. `test_negative_target_weight_no_held_produces_short` — target=-0.05, not held → `("XYZ", "SHORT", N)`
2. `test_negative_target_partially_held_produces_sell_and_short` — target=-0.05, hold 10 shares → `("XYZ", "SELL", 10)` + `("XYZ", "SHORT", remainder)`
3. `test_positive_target_lower_than_current_produces_sell_only` — regression guard: positive target → SELL only, no SHORT
4. `test_held_quantities_none_produces_sell_only` — backward compat: `held_quantities=None` → SELL, no SHORT
5. `test_negative_target_held_exceeds_total_qty_produces_sell_only` — target=-0.02 but hold 100 shares worth more than |delta| → pure SELL (reduce long), no SHORT. Validates that held >= total_qty produces no SHORT leg.
6. `test_price_divergence_nonnegative_target_no_false_short` — target=0.0 (sell to zero), hold 10 shares at snapshot value $1000, but live price $90 → `floor(1000/90) = 11 > 10 held`. Must produce SELL(10) only, NOT SELL(10)+SHORT(1). Guards against snapshot/live price divergence creating false SHORT legs when target weight is non-negative.
7. `test_price_divergence_negative_target_correct_short_qty` — target=-0.005 ($-50 target value), hold 10 shares at snapshot $1000, live price $90. SHORT quantity must be computed from target_value ($50) and live price ($90) → `floor(50/90) = 0`, not from delta ($1050) and price → `floor(1050/90) - 10 = 1`. Must produce SELL(10) + no SHORT (since floor(50/90)=0). Guards against price drift inflating SHORT legs on mildly negative targets.

**New file**: `tests/routes/test_hedging_short_support.py`

6. `test_build_target_weights_allows_negative` — suggested=-0.05, ticker not held → target=-0.05
7. `test_build_target_weights_reduces_below_zero` — AAPL at 0.6, suggested=-0.8 → AAPL at -0.2
8. `test_hedge_execute_preview_generates_short_leg` — integration test with monkeypatched services, verify: when SHORT legs present, response status is `"error"`, all legs have error message about short selling, no legs have `preview_id`, no `preview_order` calls are made
9. `test_hedge_execute_preview_summary_counts_short_as_sell` — verify that a SHORT leg increments `sell_count` (not `buy_count`) in the response `summary` dict. Assert `summary["sell_count"] >= 1` and that `summary["net_cash_impact"]` reflects the SHORT leg's estimated value on the sell side. The response contract at `routes/hedging.py:355` exposes `trade_count`, `sell_count`, `buy_count`, and `net_cash_impact` (not `total_sell_value`).
10. `test_hedge_execute_preview_with_short_legs_returns_error_no_previews` — when decomposition produces any SHORT legs (pure short or cross-zero), response status is `"error"`, no legs have `preview_id`, all legs have error message, and warnings include short-selling explanation. No broker `preview_order` calls are made.
11. `test_hedge_execute_rejects_account_with_existing_shorts` — account has a non-cash position with negative quantity → returns status="error" with warning about existing shorts. No trade legs generated.
12. `test_hedge_execute_allows_negative_cash_margin_debt` — account has a cash position (CUR:USD) with negative quantity (margin debt) but no short securities → proceeds normally, not rejected by the existing-short guard. Regression for Step 2d over-blocking.
13. `test_hedge_execute_preview_sell_only_negative_still_previews` — regression guard for Step 2e over-blocking: a negative `suggested_weight` that reduces a held position (e.g., hold 5% of XYZ, suggest -3% → target 2%) produces only SELL legs, no SHORT legs. The preview must call `preview_order`, return `preview_id`s, and have status `"success"`. Ensures the SHORT block only fires when actual SHORT legs are present, not on any negative suggestion.

**Existing file**: `frontend/packages/ui/src/components/portfolio/HedgeWorkflowDialog.test.tsx`

11. `test_short_hedge_preview_blocks_at_step3` — render HedgeWorkflowDialog with trade preview data where `status === "error"` and no legs have `preview_id`. Assert: step 3 Continue button is disabled (via `canContinueFromStep3` which checks `previewIds.length > 0`), warning message about short selling is visible.

**New file**: `tests/mcp_tools/test_basket_short_guard.py`

10. `test_basket_rebalance_rejects_negative_weights` — call `preview_basket_trade` with a basket containing negative weights and action="rebalance" → returns status="error" with warning about negative weights, `preview_legs` is empty, no legs have `preview_id`, and `preview_order` is never called (assert mock not called)
11. `test_basket_rebalance_rejects_negative_weights_zero_held` — same as test 10 but with zero held positions for all basket tickers. Verifies the guard fires before the "no positions found" early return at line 333. Same assertions: status="error", empty `preview_legs`, no `preview_order` calls.
12. `test_rebalance_negative_target_weights_rejected` — regression guard: `_normalize_weight_map({"AAPL": -0.05}, allow_negative=False)` raises ValueError (existing behavior, explicit coverage)

## Files Changed

| File | Change | Lines |
|------|--------|-------|
| `routes/hedging.py` | Remove `max(0.0)` clamp; update summary counting; reject existing-short accounts; skip broker preview when SHORT legs present | 135-138, 257, 319-324, 326 |
| `mcp_tools/trading_helpers.py` | SELL→SELL+SHORT decomposition | 97-102 |
| `mcp_tools/basket_trading.py` | Add negative weight guard before rebalance call | ~332 (before early return) |
| `mcp_tools/rebalance.py` | Update summary counting only | 462-467 |
| `frontend/packages/chassis/src/types/index.ts` | Add SHORT/COVER to side union | 443 |
| `frontend/packages/ui/src/components/portfolio/HedgeWorkflowDialog.tsx` | Add SHORT/COVER to side union (no logic changes needed) | 55 |
| `frontend/packages/ui/src/components/portfolio/HedgeWorkflowDialog.test.tsx` | Add test for short hedge blocking at step 3 | Existing |
| `tests/mcp_tools/test_trading_helpers.py` | New — 7 tests | New |
| `tests/routes/test_hedging_short_support.py` | New — 8 tests | New |
| `tests/mcp_tools/test_basket_short_guard.py` | New — 3 tests | New |

## NOT Changed (deferred to Level 3)

- **Route-level SHORT block in `routes/hedging.py`** (Step 2d) — the early return that skips all broker previews when SHORT legs are present. Must be removed/relaxed when broker short support is enabled.
- **`ALLOWED_SIDES` in `brokerage/trade_objects.py:22`** — add `"SHORT"` and `"COVER"` to allow broker preview/execution.
- **`trade_execution_service.py:2327`** — side validation against ALLOWED_SIDES. Will pass once ALLOWED_SIDES is updated.
- **`trade_execution_service.py:2383`** — SELL-only share check. Must allow short selling (selling shares not held).
- **`trade_execution_service.py:3213`** — BUY-vs-else weight impact logic. Must handle SHORT/COVER correctly.
- **Existing short positions excluded from current-state snapshot** — all three trade-leg paths discard positions with non-positive value and clamp quantities non-negative. Correctly accounting for existing shorts requires rethinking portfolio value denominators. Level 3. Full location list:
  - `routes/hedging.py:152` — `if value is None or value <= 0: continue`
  - `routes/hedging.py:158` — `max(float(quantity or 0.0), 0.0)`
  - `mcp_tools/rebalance.py:98` — `if value is None or value <= 0: continue`
  - `mcp_tools/rebalance.py:272-273` — `if value is None or value <= 0: continue`
  - `mcp_tools/rebalance.py:277` — `max(float(quantity or 0.0), 0.0)`
  - `mcp_tools/basket_trading.py:79` — `if quantity is None or quantity <= 0: continue`
  - `mcp_tools/basket_trading.py:95` — `if value is None or value <= 0: continue`
  - `mcp_tools/basket_trading.py:117-119` — `if value is None or value <= 0: continue`
- **`_normalize_weight_map(allow_negative=False)` in rebalance MCP tool** — intentionally blocks negative target weights in rebalance context. Not changed.

## Verification

1. Run existing tests: `pytest tests/mcp_tools/test_rebalance_agent_format.py tests/routes/ -x -q`
2. Run new tests: `pytest tests/mcp_tools/test_trading_helpers.py tests/routes/test_hedging_short_support.py tests/mcp_tools/test_basket_short_guard.py -v`
3. Frontend type check: `cd frontend && npx tsc --noEmit`
4. Manual: In the app, run hedge analysis → find a "Short XYZ" direct offset recommendation → click "Analyze & Execute" → verify SHORT trade leg appears in the preview dialog with error message (no preview_id)

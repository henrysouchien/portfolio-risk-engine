# Multi-Leg Options Execution via IBKR BAG/Combo Orders

**Date**: 2026-03-02
**Status**: COMPLETE (implemented in commit `7fd45a6c`)

## Context

The TODO lists "Multi-leg options execution" as a workflow gap: currently options must be executed as individual legs via `preview_trade()`, creating slippage risk between legs. IBKR supports native combo/BAG orders for options (same mechanism already proven for futures rolls). This feature adds `preview_option_trade` and `execute_option_trade` MCP tools following the identical three-layer pattern as the futures roll implementation.

## Architecture (mirrors futures roll exactly)

```
MCP Tool (mcp_tools/multi_leg_options.py)
  → Service (services/trade_execution_service.py)
    → Adapter (brokerage/ibkr/adapter.py)
      → IBKR BAG contract + whatIfOrder/placeOrder
```

## Files to Create

### 1. `mcp_tools/multi_leg_options.py` (new)

Two MCP tools following `mcp_tools/futures_roll.py` pattern:

**`preview_option_trade`**:
```python
@handle_mcp_errors
def preview_option_trade(
    legs: str,                          # JSON array (same format as analyze_option_strategy)
    underlying_symbol: str,
    underlying_price: float,
    quantity: int = 1,                  # number of spreads/combos
    description: str | None = None,
    account_id: str | None = None,
    order_type: Literal["Market", "Limit"] = "Market",
    limit_price: float | None = None,   # IBKR combo quote price (passed directly to LimitOrder)
    time_in_force: Literal["Day", "GTC"] = "Day",
    user_email: str | None = None,
) -> dict
```

- Uses `_ensure_trading_enabled()` + `_resolve_user()` from `mcp_tools/trading.py`
- **JSON parsing**: Call `parse_json_list(legs)` from `mcp_tools/common.py` to convert `str` → `list[dict]`, then pass to `_parse_legs(..., allow_mixed_expiry=True)` from `mcp_tools/options.py`
- Validates: legs non-empty, underlying_symbol non-empty, underlying_price > 0, quantity >= 1 and is integer (`int(quantity) == quantity`, reject `1.5`)
- **Integer leg.size validation**: For each parsed leg, check `leg.size == int(leg.size)` and `leg.size > 0`. Reject fractional sizes (IBKR ComboLeg.ratio is int). Note: `OptionLeg` stores `size` as `float`, so `1.0` is accepted, `1.5` is rejected.
- Builds `OptionStrategy` from `options/data_objects.py`
- Delegates to `TradeExecutionService(user).preview_multileg_option(...)`

**`execute_option_trade`**:
```python
@handle_mcp_errors
def execute_option_trade(preview_id: str, user_email: str | None = None) -> dict
```
- Delegates to `TradeExecutionService(user).execute_multileg_option(preview_id)`

### 2. `tests/mcp_tools/test_multi_leg_options.py` (new)

~14 tests (monkeypatch service):
- Valid 2-leg spread preview, valid 4-leg condor
- Missing underlying_symbol, invalid JSON (not a list), empty legs
- Non-integer leg.size (e.g., 1.5) → error
- Integer-as-float leg.size (e.g., 2.0) → accepted
- Non-integer quantity (e.g., 1.5) → error
- Integer-as-float quantity (e.g., 2.0) → accepted
- Limit order without limit_price → error
- Execute happy path + trading disabled
- `allow_mixed_expiry` regression: verify _parse_legs still rejects mixed expiry when called without the flag (existing analyze_option_strategy behavior preserved)

### 3. `tests/services/test_trade_execution_service_multileg.py` (new)

~9 tests (monkeypatch adapter + DB):
- Account resolution
- IBKR-only validation (non-IBKR adapter → error)
- Preview storage with `order_category="multi_leg_option"`
- Preview warnings propagation
- Execute flow with DB lock (happy path)
- Execute expired preview → error
- Execute wrong order_category → error
- Execute duplicate (IntegrityError) → idempotent return of existing order
- Execute with adapter failure → preview marked cancelled, failed order row inserted

### 4. `tests/brokerage/ibkr/test_adapter_multileg.py` (new)

~12 tests (monkeypatch ib_async):
- BAG construction: 2-leg spread, 4-leg condor, covered call with stock leg
- con_id-based vs field-based resolution
- Contract qualification failure → ValueError
- Margin extraction from whatIfOrder
- Order placement + fill extraction
- Read-only mode rejection
- Live pricing: per-leg bid/ask/mid returned in preview
- Live pricing: `net_debit_credit_mid` correct for debit spread (positive = debit) and credit spread (negative = credit), in total dollars (includes size × multiplier per leg)
- Live pricing: graceful fallback when snapshot times out (preview still succeeds with prices as None, `estimated_total` also None)
- Live pricing: commission unavailable → `estimated_total` is None, warning added
- Underlying symbol cross-check: mismatch between `underlying_symbol` and qualified contract's symbol → ValueError
- Leg reconstruction from stored order_params (filtered keys, no extra `to_dict()` fields)

## Files to Modify

### 5. `mcp_tools/options.py` — add `allow_mixed_expiry` param

Minimal change to `_parse_legs()` (line 58):
```python
def _parse_legs(legs: list[dict[str, Any]], allow_mixed_expiry: bool = False) -> list[OptionLeg]:
    # ... existing logic unchanged ...
    if not allow_mixed_expiry:
        option_expiries = { ... }
        if len(option_expiries) > 1:
            raise ValueError("mismatched option expirations are not supported in phase 1")
    return parsed
```

### 6. `brokerage/ibkr/adapter.py` — three new methods on IBKRBrokerAdapter

**`_build_option_combo_contract(self, ib, strategy, quantity=1)`**:
- For each leg: build `Option(conId=...)` or `Option(symbol, lastTradeDateOrContractMonth, strike, right)` for call/put; `Stock(symbol, "SMART", "USD")` for stock legs
- Uses `ibkr/contracts.py::resolve_option_contract()` for option legs (builds contract identity dict from OptionLeg fields)
- Batch qualify: `ib.qualifyContracts(*all_contracts)`
- Validate all qualified (len check). Derive exchange/currency from first qualified contract (like futures roll does at lines 183-195) rather than hardcoding. Validate currency is USD — reject non-USD options with clear error ("only US equity options supported in phase 1").
- **FOP rejection**: After qualification, check each qualified contract's `secType`. If any option leg qualifies as `"FOP"` (futures option) instead of `"OPT"`, raise `ValueError("Futures options (FOP) are not supported in phase 1. Use equity options only.")`. This catches cases where the underlying is a futures contract (e.g., ES options) — IBKR auto-resolves these to FOP secType during qualification.
- **Underlying symbol cross-check**: When legs are resolved by `con_id`, verify that each qualified option contract's `symbol` attribute matches `strategy.underlying_symbol`. Raise `ValueError` on mismatch (prevents stale/wrong `underlying_symbol` from creating a BAG with inconsistent identity).
- Build `ComboLeg` per leg: `conId`, `ratio=int(leg.size)`, `action="BUY"/"SELL"` from `leg.position`, `exchange` from qualified contract
- Assemble BAG: `Contract(symbol=underlying, secType="BAG", exchange=derived_exchange, currency=derived_currency, comboLegs=[...])`
- Return `(bag_contract, qualified_contracts_list)` where each entry has resolved conId

**`preview_multileg_option(self, account_id, strategy, quantity, order_type, limit_price, time_in_force)`**:
- Pattern: same as `preview_roll` (lines 333-423)
- `_resolve_native_account` → `ibkr_shared_lock` → `_ensure_connected`
- Build BAG via `_build_option_combo_contract` → collect qualified contracts
- **Live pricing (inside lock, using raw IB)**: After qualifying, use the *same `ib` connection* to subscribe to market data for **all qualified leg contracts** (both option and stock legs) via `ib.reqMktData()` + poll loop (same technique as `fetch_snapshot` but without going through `IBKRMarketDataClient` which would re-acquire the lock and deadlock). Collect bid/ask/mid per leg. For option legs, also collect `implied_vol` from modelGreeks. For stock legs, `implied_vol` is N/A (set to None). Cancel subscriptions after collection. Graceful fallback: if polling times out for any leg, set that leg's prices to None and continue.
- **Pricing — two separate concerns**:
  - **`net_debit_credit_mid`** (display/informational): Total dollar cost of one combo at mid prices. Per-leg: `mid * direction * size * multiplier`. Sum across legs. Positive = net debit, negative = net credit. Always in total dollars. `estimated_total = net_debit_credit_mid * quantity + commission`. This is for the agent/user to understand the actual cash impact.
  - **`limit_price`** (order construction): Passed **directly** to IBKR `LimitOrder(action, qty, limit_price)` as the combo quote price — same as futures roll. IBKR interprets this as the combined per-unit spread price including leg ratios. The MCP `limit_price` param is in IBKR combo quote price units (NOT total dollars). This is the same semantics as futures roll where `limit_price` = spread quote. For pure option combos, this is per-share net. For mixed combos, IBKR determines the interpretation. **No conversion layer needed** — pass through directly like futures roll does.
  - These are intentionally different units. `net_debit_credit_mid` is for human understanding, `limit_price` is for IBKR order submission.
- Build order → `ib.whatIfOrder(bag, order)` → extract margin impact + commission from OrderState
- **`OrderPreview.estimated_price`**: Set to `net_debit_credit_mid` (total dollars per combo), or None if any leg mid unavailable. **`OrderPreview.estimated_total`**: Set to `net_debit_credit_mid * quantity + commission` when both `net_debit_credit_mid` and `commission` are available. Set to None when either is unavailable (commission can be None per existing IBKR pattern — adapter adds "commission unavailable" warning). This ensures the service layer fallback (line 567: `estimated_price * quantity + commission`) is bypassed when we have good data, and both fields are consistently None when we don't.
- Return `OrderPreview` with `broker_preview_data`:
  ```python
  {
      "order_category": "multi_leg_option",
      "order_type": order_type,
      "underlying_symbol": ...,
      "strategy_description": ...,
      "leg_prices": [
          {"con_id": ..., "bid": ..., "ask": ..., "mid": ..., "implied_vol": ...},
          ...
      ],
      "net_debit_credit_mid": ...,       # total dollars per combo: sum(mid * direction * size * multiplier). None if any leg mid unavailable.
      "estimated_total": ...,            # net_debit_credit_mid * quantity + commission. None if either net_debit_credit_mid or commission is None.
      "order_params": {
          "legs": [_serialize_leg_for_storage(leg) for leg in strategy.legs],
          "underlying_symbol": ...,
          "underlying_price": ...,
          "quantity": quantity,
          "order_type_str": order_type,
          "limit_price": limit_price,
          "time_in_force": time_in_force,
      },
      "init_margin_change": ...,
      "maint_margin_change": ...,
      "init_margin_before": ...,
      "init_margin_after": ...,
      "maint_margin_before": ...,
      "maint_margin_after": ...,
      "warning_text": ...,
      "commission": ...,
  }
  ```

**`_serialize_leg_for_storage(leg: OptionLeg) -> dict`** (private helper):
- Returns only the fields needed to reconstruct an OptionLeg: `position`, `option_type`, `strike`, `premium`, `size`, `multiplier`, `expiration` (as YYYYMMDD string), `label`, `con_id`. Does NOT use `leg.to_dict()` which includes computed fields (`expiry_yyyymmdd`, `direction`, `net_premium`) that would break `OptionLeg(**stored_dict)` reconstruction.

**`_reconstruct_legs_from_storage(legs_data: list[dict]) -> list[OptionLeg]`** (private helper):
- Builds `OptionLeg` objects from stored dicts. Safe because `_serialize_leg_for_storage` only stores constructor-compatible fields.
- **Re-validates integer ratios**: After construction, checks `leg.size == int(leg.size)` for each leg. Raises `ValueError` if malformed data has fractional sizes (defense against DB corruption or manual edits to stored preview).

**`place_multileg_option(self, account_id, order_params)`**:
- Pattern: same as `place_roll` (lines 425-508)
- Check read-only mode
- Reconstruct legs via `_reconstruct_legs_from_storage(order_params["legs"])` → build `OptionStrategy` → `_build_option_combo_contract`
- `_build_order` → set `order.orderRef = preview_id` for IBKR-side traceability (same as `place_roll` line 468) → `ib.placeOrder(bag, order)`
- Poll for fill (5s timeout, same loop as `place_roll` line 473-477)
- Return `OrderResult` with `broker_data["order_category"] = "multi_leg_option"`

### 7. `services/trade_execution_service.py` — two new methods

**`preview_multileg_option(self, account_id, strategy, quantity, description, order_type, limit_price, time_in_force)`**:
- Pattern: same as `preview_roll` (lines 505-660)
- `_resolve_target_account` → validate adapter is IBKR (`adapter.provider_name != "ibkr"` → error) → check `hasattr(adapter, "preview_multileg_option")`
- Call `adapter.preview_multileg_option(...)`
- Extract estimated values from OrderPreview
- Set `broker_preview_data["order_category"] = "multi_leg_option"` (defensive, adapter should set it too)
- Build `PreTradeValidation` with warnings from `warning_text` + adapter warnings
- Store via `_store_preview(ticker=underlying_symbol, side="BUY", quantity=quantity, ...)`
- Return `TradePreviewResult`
- Wrapped in try/except returning error `TradePreviewResult` on failure (same pattern as `preview_roll` lines 646-660)

**`execute_multileg_option(self, preview_id)`**:
- Pattern: same as `execute_roll`. **Must include all idempotency/recovery behaviors:**
  1. DB transaction with `SELECT ... FOR UPDATE` on `trade_previews`
  2. **Preview existence check**: If no preview row found, return error `TradeExecutionResult`
  3. Check for existing order row — **short-circuit**: if preview status is already "executed", fetch the existing order row and return it as success (idempotent). If status is "executed" but no order row exists (corrupted state), return error `TradeExecutionResult` with message "preview marked executed but no order found".
  4. Validate preview not expired
  5. **Account ownership check**: Verify the preview's `user_id` (stored in `trade_previews.user_id`) matches `self.config.user_email` resolved to user_id (same pattern as existing `WHERE user_id = %s` queries). Reject with error if mismatch (prevents cross-user execution).
  6. **Adapter/account authorization**: Resolve adapter, verify `adapter.provider_name == "ibkr"`, verify `hasattr(adapter, "place_multileg_option")`
  7. Validate `broker_preview_data.get("order_category") == "multi_leg_option"`
  8. **order_params shape validation**: Verify `order_params` dict exists and contains required keys (`legs`, `underlying_symbol`, `quantity`, `order_type_str`, `time_in_force`)
  9. **Inject `preview_id` into `order_params`** so the adapter can set `order.orderRef` for IBKR-side traceability (same as `execute_roll` which passes `preview_id` to `place_roll`)
  10. Call `adapter.place_multileg_option(account_id, order_params)`
  11. Store order in `trade_orders` table
  12. Update preview status to "executed"
  13. **IntegrityError handling**: Retry fetch to handle race conditions
  14. **Exception handling**: Mark preview "cancelled", insert failed order row with error details
- Return `TradeExecutionResult`

### 8. `mcp_server.py` — register 2 tools

Add import (near line 74) and `@mcp.tool()` wrappers (near line 1672, after futures roll):
```python
from mcp_tools.multi_leg_options import preview_option_trade as _preview_option_trade
from mcp_tools.multi_leg_options import execute_option_trade as _execute_option_trade
```

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| No new dataclass | Reuse `TradePreviewResult` | Per-leg details live in `broker_preview_data` (JSONB). Same approach as futures roll. |
| Reuse `OptionLeg`/`OptionStrategy` | From `options/data_objects.py` | Already validated, serializable, has `con_id` support. Same input format as `analyze_option_strategy`. |
| Reuse `_parse_legs()` | From `mcp_tools/options.py` | DRY. Add `allow_mixed_expiry` flag for execution use case. |
| Custom storage serializer | `_serialize_leg_for_storage()` | `OptionLeg.to_dict()` includes computed fields that break reconstruction. Store only constructor-compatible fields. |
| Live pricing inside lock | Use raw `ib.reqMktData` not `IBKRMarketDataClient` | `fetch_snapshot()` acquires `ibkr_shared_lock` — calling it inside `preview_multileg_option` (which already holds the lock) would deadlock. Use the raw `ib` connection directly. |
| Two pricing units | `net_debit_credit_mid` (total dollars) vs `limit_price` (IBKR combo quote) | `net_debit_credit_mid` = `sum(mid * direction * size * multiplier)` — total dollars for agent/user display. `limit_price` = IBKR combo quote price, passed directly to `LimitOrder` (same as futures roll). No conversion layer needed. |
| Derive exchange/currency | From qualified contracts | Same pattern as futures roll (adapter.py lines 183-195). Validate USD-only with clear error. |
| Combo side = "BUY" | IBKR convention | Individual `ComboLeg.action` determines direction per leg. |
| Integer leg.size only | IBKR `ComboLeg.ratio` is int | Validate at MCP layer. `1.0` accepted, `1.5` rejected. Ratio spreads (1:2) supported. |
| Stock options only (phase 1) | Defer FOP to later | Equity options cover 99% of use cases. Clear error if FOP detected. |
| `premium` still required | Reusing `OptionLeg` as-is | Minor input friction but keeps data objects unified. Can pass `0.0` if unknown — it's used for payoff analysis, not order construction. |

## Implementation Order

1. `mcp_tools/options.py` — add `allow_mixed_expiry` param (safe, backward-compatible)
2. `brokerage/ibkr/adapter.py` — three methods + two private helpers (self-contained)
3. `services/trade_execution_service.py` — two new methods (depends on adapter)
4. `mcp_tools/multi_leg_options.py` — new file (depends on service + parser)
5. `mcp_server.py` — register tools
6. Tests — all three test files

## Verification

1. Run unit tests: `python3 -m pytest tests/mcp_tools/test_multi_leg_options.py tests/services/test_trade_execution_service_multileg.py tests/brokerage/ibkr/test_adapter_multileg.py -v`
2. Verify existing tests still pass: `python3 -m pytest tests/mcp_tools/test_futures_roll.py tests/services/test_trade_execution_service_preview.py tests/options/test_mcp_options.py -v`
3. MCP reconnect and verify tools appear: `preview_option_trade`, `execute_option_trade`
4. Live test (with TWS running): preview a bull call spread on a liquid underlying

## Codex Review Summary (5 rounds, all issues resolved)

16 total issues found and fixed across 5 review rounds:

**Key fixes (HIGH):**
- Deadlock: Use raw `ib.reqMktData()` inside lock, not `IBKRMarketDataClient.fetch_snapshot()`
- Storage: `_serialize_leg_for_storage()` stores only constructor-compatible fields (not `to_dict()` which includes computed fields)
- Pricing units: `net_debit_credit_mid` = total dollars per combo (display). `limit_price` = IBKR combo quote price (pass-through to `LimitOrder`, same as futures roll). Two separate concerns.
- Execute flow: Full 12-step flow matching `execute_roll` with all idempotency/recovery behaviors

**Other fixes (MEDIUM/LOW):**
- `parse_json_list()` before `_parse_legs()`
- `broker_preview_data` aligned with roll conventions (all margin fields, `implied_vol` not `iv`, `warning_text`, `commission`)
- Exchange/currency derived from qualified contracts (not hardcoded SMART/USD)
- Integer `leg.size` validated at MCP layer + re-validated in adapter reconstruction
- `premium` required but can be `0.0` if unknown (keeps OptionLeg unified)
- `net_debit_credit_mid` / `estimated_total` = None when any leg mid unavailable (graceful snapshot timeout)

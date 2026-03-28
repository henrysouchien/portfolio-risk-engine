# F12 Level 3: Broker Execution for Short Positions

## Context

Level 2 (commit `6bd27631`) added SHORT trade leg generation but blocks execution with a hard server-side early return. Level 3 enables actual broker execution of SHORT orders through IBKR. Schwab and SnapTrade reject SHORT with clear errors. COVER (closing a short) is allowed on all brokers — it maps to BUY at the broker level.

**Goal**: Remove the Level 2 hard block, add SHORT/COVER to allowed sides, fix trade validation guards, and gate behind `SHORT_SELLING_ENABLED` feature flag.

**Scope boundary**: Only enables NEW shorts from accounts without existing short positions. The existing-short preflight guard (hedging.py:262-271) stays — fixing the 8 snapshot locations that discard negative positions is a separate phase.

## Implementation Steps

### Step 1: Add `SHORT_SELLING_ENABLED` feature flag

**File**: `settings.py`, after `TRADING_ENABLED` (line 405)

```python
SHORT_SELLING_ENABLED = os.getenv("SHORT_SELLING_ENABLED", "false").lower() == "true"
```

No `__all__` block exists in settings.py — this is a module-level constant following the same pattern as `TRADING_ENABLED`, `IBKR_ENABLED`, etc. Import it directly where needed via `from settings import SHORT_SELLING_ENABLED`.

### Step 2: Expand `ALLOWED_SIDES`

**File**: `brokerage/trade_objects.py:22`

```python
# Before
ALLOWED_SIDES = ("BUY", "SELL")

# After
ALLOWED_SIDES = ("BUY", "SELL", "SHORT", "COVER")
```

### Step 3: DB migration — expand CHECK constraints

**New file**: `database/migrations/20260327_add_short_cover_sides.sql`

```sql
-- Allow SHORT and COVER sides for short position support
ALTER TABLE trade_previews DROP CONSTRAINT IF EXISTS trade_previews_side_check;
ALTER TABLE trade_previews ADD CONSTRAINT trade_previews_side_check
    CHECK (side IN ('BUY', 'SELL', 'SHORT', 'COVER'));

ALTER TABLE trade_orders DROP CONSTRAINT IF EXISTS trade_orders_side_check;
ALTER TABLE trade_orders ADD CONSTRAINT trade_orders_side_check
    CHECK (side IN ('BUY', 'SELL', 'SHORT', 'COVER'));
```

Both `trade_previews.side` (line 14) and `trade_orders.side` (line 58) in `20260209_add_trade_tables.sql` have `CHECK (side IN ('BUY', 'SELL'))`. Without this migration, `_store_preview()` and execution inserts will fail at the DB level.

### Step 4: Gate SHORT behind feature flag in `_validate_pre_trade()` and `execute_order()`

COVER is NOT gated — it's the risk-reducing exit path (closing an existing short). Blocking COVER when the flag is off would trap users in short positions they can't close.

**4a — Pre-trade gate** (`services/trade_execution_service.py`, after the ALLOWED_SIDES check at line 2328):

```python
# After the existing ALLOWED_SIDES validation (SHORT only, not COVER)
if side == "SHORT":
    from settings import SHORT_SELLING_ENABLED
    if not SHORT_SELLING_ENABLED:
        errors.append(
            "Short selling is disabled. Set SHORT_SELLING_ENABLED=true to enable."
        )
```

**4b** — Folded into Step 4e (execute-time SHORT revalidation block handles feature flag, long-position, and account-wide short checks together).

### Step 4c: Account-wide existing-short guard in `_validate_pre_trade()`

The hedging route has an existing-short preflight guard (hedging.py:262-271) that blocks the entire account. The direct trade path (`/api/trading/preview` → `TradeExecutionService.preview_order()` → `_validate_pre_trade()`) needs an equivalent account-wide guard, because the snapshot logic discards ALL negative-value positions — making weight calculations wrong for any account with ANY short position, not just the one being traded.

**File**: `services/trade_execution_service.py`, in `_validate_pre_trade()` after the feature flag check

```python
# Block SHORT on accounts with ANY existing short positions
# (snapshot logic doesn't handle negative-value positions correctly yet)
if side == "SHORT" and account_id:
    service = PositionService(self.config.user_email)
    result = service.get_all_positions(
        use_cache=False, force_refresh=True, consolidate=False, account=account_id,
    )
    for position in (result.data.positions if result.data else []):
        pos_ticker = str(position.get("ticker") or "").upper().strip()
        pos_type = str(position.get("type") or "").strip().lower()
        if pos_type == "cash" or pos_ticker.startswith("CUR:"):
            continue
        qty = _to_float(position.get("quantity"))
        if qty is not None and qty < 0:
            errors.append(
                f"Account contains existing short position ({pos_ticker}). "
                "Short execution on accounts with existing shorts is not yet supported."
            )
            break
```

This mirrors the hedging guard's account-wide scope: any non-cash position with negative quantity blocks SHORT for the entire account.

**Fail-closed on provider errors**: `PositionService.get_all_positions(force_refresh=True)` converts provider failures into empty position frames with `provider_errors` metadata. However, `provider_errors` aggregates across ALL providers (not just the target account's provider). To avoid blocking SHORT on a healthy IBKR account because of an unrelated Schwab outage, scope the check to the target account's provider:

```python
# After the get_all_positions call
positions = result.data.positions if result.data else []
broker_provider = adapter.provider_name if adapter else ""
provider_had_error = any(
    broker_provider.lower() in str(err).lower()
    for err in (getattr(result, 'provider_errors', None) or [])
)
# Fail closed: if the TARGET provider reported an error, block SHORT/COVER
# regardless of whether other providers contributed position rows.
# Non-authoritative data (CSV, other brokers) cannot be trusted for
# short-selling validation.
if provider_had_error:
    errors.append(
        f"Cannot verify account positions for short selling — {broker_provider} refresh failed. "
        "Try again later."
    )
    # skip remaining position checks
```

Apply this fail-closed pattern to ALL force-refreshed position checks: Step 4c, Step 6 (COVER), Step 8 (COVER execute), and Step 4e (SHORT execute). At execute time, derive `broker_provider` from the preview row.

### ~~Step 4d~~ — REMOVED

The same-ticker long guard ("reject SHORT when account holds long") was removed. It breaks the hedge flow: the hedge decomposition intentionally emits paired SELL+SHORT legs for cross-zero hedges (`compute_rebalance_legs` at `trading_helpers.py:104`). Since legs are previewed independently, the SHORT leg would see the pre-trade long position and be rejected before the SELL executes — making valid SELL→SHORT hedges non-previewable.

For the direct trade path, the IBKR adapter maps SHORT→SELL, and IB handles the cross-zero case automatically. The system records it as SHORT for internal tracking.

### Step 4e: Execute-time SHORT revalidation

Between preview and execution, the account state can change (e.g., acquire a long in the same ticker, or a new short elsewhere). Add live re-checks for SHORT at execute time, parallel to the existing SELL and proposed COVER checks.

**File**: `services/trade_execution_service.py`, in `execute_order()` after the SELL/COVER re-checks (~line 1638)

```python
elif preview_side == "SHORT" and preview_ticker:
    # Re-check 1: feature flag still on
    from settings import SHORT_SELLING_ENABLED
    if not SHORT_SELLING_ENABLED:
        raise ValueError(
            "Short selling has been disabled since this preview was created. "
            "Cannot execute SHORT orders."
        )
    # Re-check 2: no existing shorts anywhere in account (account-wide guard)
    service = PositionService(self.config.user_email)
    result = service.get_all_positions(
        use_cache=False, force_refresh=True, consolidate=False, account=account_id,
    )
    # Fail-closed on provider error
    broker_provider = str(preview_row.get("broker_provider") or "")
    provider_had_error = any(
        broker_provider.lower() in str(err).lower()
        for err in (getattr(result, 'provider_errors', None) or [])
    )
    if provider_had_error:
        raise ValueError(
            f"Cannot verify positions — {broker_provider} refresh failed. Try again later."
        )
    for position in (result.data.positions if result.data else []):
        pos_ticker = str(position.get("ticker") or "").upper().strip()
        pos_type = str(position.get("type") or "").strip().lower()
        if pos_type == "cash" or pos_ticker.startswith("CUR:"):
            continue
        qty = _to_float(position.get("quantity"))
        if qty is not None and qty < 0:
            raise ValueError(
                f"Position changed since preview: account now contains short position ({pos_ticker}). "
                "Cannot execute SHORT on accounts with existing shorts."
            )
    # No same-ticker long check — hedge decomposition produces paired
    # SELL+SHORT legs, and IB handles cross-zero automatically.
```

This consolidates the feature flag check (previously Step 4b) into the SHORT re-check block. Remove the separate Step 4b feature flag check to avoid duplication.

### Step 4f: Update MCP tool schemas for SHORT/COVER

Two MCP ingress points have `Literal["BUY", "SELL"]` type annotations that reject SHORT/COVER before reaching the service layer.

**File 1**: `mcp_tools/trading.py:40`
```python
# Before
side: Literal["BUY", "SELL"],

# After
side: Literal["BUY", "SELL", "SHORT", "COVER"],
```

**File 2**: `mcp_server.py:2611`
```python
# Before
side: Literal["BUY", "SELL"],

# After
side: Literal["BUY", "SELL", "SHORT", "COVER"],
```

### Step 5: Buying power checks — NO CHANGE for SHORT

The existing buying power checks at `trade_execution_service.py:2377` (pre-trade) and `:390` (post-impact) stay **BUY-only**. SHORT margin requirements are fundamentally different — a short's initial margin is typically 50% of notional, not 100%. Using full notional as the buying power threshold falsely rejects valid shorts.

IBKR's preview response already exposes actual margin deltas (`init_margin_change`, `maint_margin_change` in `OrderPreview.broker_preview_data`). The broker's preview is the authoritative margin check for SHORT. No local pre-check is needed or correct.

### Step 6: Add COVER share check, skip share check for SHORT

**File**: `services/trade_execution_service.py:2383-2392`

```python
# Before
if side == "SELL" and quantity_num is not None and ticker:
    held = self._get_live_position_quantity(...)
    if held < quantity_num:
        errors.append(...)

# After
if side == "SELL" and quantity_num is not None and ticker:
    held = self._get_live_position_quantity(...)
    if held < quantity_num:
        errors.append(
            f"Insufficient shares to sell {quantity_num:g} {ticker}; available in account: {held:g}"
        )
elif side == "COVER" and quantity_num is not None and ticker:
    # Use force-refreshed PositionService for live data across all brokers
    cover_service = PositionService(self.config.user_email)
    cover_result = cover_service.get_all_positions(
        use_cache=False, force_refresh=True, consolidate=False, account=account_id,
    )
    cover_held = 0.0
    ticker_upper = ticker.upper().strip()
    for position in (cover_result.data.positions if cover_result.data else []):
        pos_ticker = str(position.get("ticker") or "").upper().strip()
        if pos_ticker == ticker_upper:
            qty = _to_float(position.get("quantity"))
            if qty is not None:
                cover_held += qty
    if cover_held >= 0:
        errors.append(
            f"No short position to cover for {ticker}; held quantity: {cover_held:g}"
        )
    elif abs(cover_held) < quantity_num:
        errors.append(
            f"Insufficient short position to cover {quantity_num:g} {ticker}; short position: {abs(cover_held):g}"
        )
# SHORT: no share check needed — opening a new short position
```

### Step 7: Fix weight impact logic + concentration controls

**7a — Weight impact** (`services/trade_execution_service.py:3213-3216`):

```python
# Before
if side == "BUY":
    post_ticker_value = current_ticker_value + notional
else:
    post_ticker_value = max(current_ticker_value - notional, 0.0)

# After
if side == "BUY":
    post_ticker_value = current_ticker_value + notional
elif side == "COVER":
    post_ticker_value = min(current_ticker_value + notional, 0.0)  # Clamp at 0 (can't go long from a cover)
elif side == "SHORT":
    post_ticker_value = current_ticker_value - notional  # Can go negative
else:  # SELL
    post_ticker_value = max(current_ticker_value - notional, 0.0)
```

**7b — Concentration controls** (`services/trade_execution_service.py:2405,2410`):

The `post_weight > max_weight` and `post_weight > 0.10` checks only catch large positive exposure. For SHORT, a large negative weight is equally dangerous. Use `abs(post_weight)`:

```python
# Before (line 2405)
if not is_diversified and post_weight is not None and post_weight > max_weight:

# After
if not is_diversified and post_weight is not None and abs(post_weight) > max_weight:
```

```python
# Before (line 2410)
if not is_diversified and post_weight is not None and post_weight > 0.10:

# After
if not is_diversified and post_weight is not None and abs(post_weight) > 0.10:
```

Same for the post-impact concentration warning at line 400:
```python
# Before
if not is_diversified and post_weight is not None and post_weight > 0.10:

# After
if not is_diversified and post_weight is not None and abs(post_weight) > 0.10:
```

### Step 8: Add COVER re-check at execute time

**File**: `services/trade_execution_service.py:1628`

```python
# Before
if preview_side == "SELL" and preview_qty and preview_ticker:
    held = self._get_live_position_quantity(...)
    if held < preview_qty:
        raise ValueError(...)

# After
if preview_side == "SELL" and preview_qty and preview_ticker:
    held = self._get_live_position_quantity(...)
    if held < preview_qty:
        raise ValueError(
            f"Position changed since preview: cannot sell {preview_qty:g} "
            f"{preview_ticker}, only {held:g} held (live check, account {account_id})"
        )
elif preview_side == "COVER" and preview_qty and preview_ticker:
    # Use force-refreshed PositionService for live data across all brokers
    cover_service = PositionService(self.config.user_email)
    cover_result = cover_service.get_all_positions(
        use_cache=False, force_refresh=True, consolidate=False, account=account_id,
    )
    cover_held = 0.0
    ticker_upper = preview_ticker.upper().strip()
    for position in (cover_result.data.positions if cover_result.data else []):
        pos_ticker = str(position.get("ticker") or "").upper().strip()
        if pos_ticker == ticker_upper:
            qty = _to_float(position.get("quantity"))
            if qty is not None:
                cover_held += qty
    if cover_held >= 0:
        raise ValueError(
            f"Position changed since preview: no short position for {preview_ticker} "
            f"to cover (live check, account {account_id})"
        )
    elif abs(cover_held) < preview_qty:
        raise ValueError(
            f"Position changed since preview: cannot cover {preview_qty:g} "
            f"{preview_ticker}, only {abs(cover_held):g} short (live check, account {account_id})"
        )
# SHORT execute-time re-checks are in Step 4e below
```

### Step 9: IBKR adapter — SHORT→SELL mapping

**File**: `brokerage/ibkr/adapter.py:1142`

For general (non-institutional) IB accounts, short-selling uses the `SELL` action — IB determines from the account's position state whether it's a regular sell or a short sale. `SSHORT` is only for institutional accounts with `shortSaleSlot`/`designatedLocation` fields, which this codebase does not use. COVER maps to `BUY`.

```python
# Before
action = side.upper()

# After
_IB_ACTION_MAP = {"BUY": "BUY", "SELL": "SELL", "SHORT": "SELL", "COVER": "BUY"}
action = _IB_ACTION_MAP.get(side.upper(), side.upper())
```

The internal SHORT/COVER distinction is preserved in the system for validation logic (share checks, weight impact, concentration controls) and transaction recording, but the broker only sees BUY/SELL.

**9b — Recovery probe side mapping** (`services/trade_execution_service.py:2942`):

The fallback matcher in `_run_ibkr_recovery_probe()` compares `trade.order.action` (broker-side, e.g., "SELL") against `order_params.get("side")` (internal, e.g., "SHORT"). These won't match after the mapping, so the recovery probe would fail to find the order.

Define a local mapping in `trade_execution_service.py` for the recovery probe (don't import from the adapter — it would create a circular dependency risk and couples the service to a specific broker's internals):

```python
# At module level in trade_execution_service.py, near other constants
_IBKR_SIDE_TO_ACTION = {"BUY": "BUY", "SELL": "SELL", "SHORT": "SELL", "COVER": "BUY"}
```

Then in the recovery probe fallback matcher:

```python
# Before (line 2942)
and trade.order.action == order_params.get("side")

# After
and trade.order.action == _IBKR_SIDE_TO_ACTION.get(
    str(order_params.get("side") or "").upper(),
    str(order_params.get("side") or "").upper(),
)
```

The adapter keeps its own `_IB_ACTION_MAP` for order construction. Both maps have the same values — this is intentional duplication to avoid cross-module coupling.

### Step 10: Schwab adapter — reject SHORT, map COVER at `preview_order()` level

The Schwab adapter's `preview_order()` (line 404) does NOT call `_instruction_for_side()` — it uses the raw side value. The order builder routing at line 296 also routes all non-BUY through `equity_sell_*` builders. Both must be guarded.

**File**: `brokerage/schwab/adapter.py`, at the top of `preview_order()` (line 404):

```python
# Add at start of preview_order(), before any other logic
side_upper = str(side or "").upper().strip()
if side_upper == "SHORT":
    raise ValueError(
        "Schwab SHORT orders require adapter routing changes not yet implemented. "
        "Use an IBKR account for short selling."
    )
if side_upper == "COVER":
    side = "COVER"  # Keep as COVER — _instruction_for_side maps to BUY_TO_COVER
```

Also update `_instruction_for_side()` to map COVER to the correct Schwab instruction:

```python
def _instruction_for_side(self, side: str) -> str:
    side_upper = str(side or "").upper().strip()
    if side_upper == "BUY":
        return "BUY"
    if side_upper == "SELL":
        return "SELL"
    if side_upper == "COVER":
        return "BUY_TO_COVER"
    if side_upper == "SHORT":
        raise ValueError(
            "Schwab SHORT orders require adapter routing changes not yet implemented. "
            "Use an IBKR account for short selling."
        )
    raise ValueError(f"Unsupported side: {side}")
```

The Schwab SDK has `Instruction.BUY_TO_COVER` (`schwab.orders.common:289`) and cover builders in `schwab.orders.equities:124`. The adapter's order spec builder at line 270 uses `"instruction": instruction`, so `BUY_TO_COVER` flows through correctly.

**Also update the builder routing** at `adapter.py:300-312`: the builder selection block (lines 305-312) uses `side_upper == "BUY"` ternary to pick buy vs sell builders. For COVER, return the raw fallback `spec` dict early — it already has `"instruction": "BUY_TO_COVER"` from `_instruction_for_side()`:

```python
# At line 300, after side_upper is set, BEFORE the builder selection (line 305):
if side_upper == "COVER":
    # The schwab.orders.equities builders don't have cover-specific helpers
    # for all order types. The raw fallback spec (built at lines 275-294)
    # already has instruction="BUY_TO_COVER" from _instruction_for_side().
    return spec
```

This returns before the builder ternaries at lines 305-312, avoiding the `equity_sell_*` path. The raw spec at line 275 is the standard Schwab order JSON with `"instruction": "BUY_TO_COVER"` — it's what the builder helpers produce internally, just without version-specific niceties.

The test for this must exercise `_build_order_spec(side="COVER")` directly, not just `_instruction_for_side()`, to verify the routing.

### Step 11: SnapTrade adapter — reject SHORT/COVER early in `preview_order()`

**File**: `brokerage/snaptrade/adapter.py`, in `preview_order()` before the API call

```python
# Add at start of preview_order()
side_upper = str(side or "").upper().strip()
if side_upper == "SHORT":
    raise ValueError(
        "SnapTrade does not support SHORT orders. "
        "Use an IBKR account for short selling."
    )
if side_upper == "COVER":
    side = "BUY"  # COVER maps to BUY (closing short = buying shares)
```

SHORT raises `ValueError` which `TradeExecutionService.preview_order()` catches and converts to an error response. COVER maps to BUY — closing a short is just buying shares back, which SnapTrade supports. This ensures users are never trapped in short positions on SnapTrade.

### Step 12: Remove Level 2 hard block

**File**: `routes/hedging.py:340-360`

Replace the blanket hard block with an atomicity check: after all legs are previewed, if any leg failed preview (has `error` / no `preview_id`), strip `preview_id` from ALL legs and set status to `"error"`. This prevents partial execution (e.g., SELL succeeds but SHORT fails on Schwab → user can't execute just the SELL leg).

```python
# REPLACE the has_short_legs block (lines 340-360) with partial-preview guard:

# After the preview_order loop (after line 378)
preview_failures = [leg for leg in trades if leg.get("error") or not leg.get("preview_id")]
if preview_failures and len(preview_failures) < len(trades):
    # Partial success — some legs failed. Strip preview_ids from response AND
    # expire the persisted preview rows so they can't be executed via direct API.
    # Delete all preview rows that have preview_ids (successful previews).
    # Validation-failed previews are also persisted by preview_order() but
    # their IDs are never returned to the caller — they're unreachable via
    # execute_order() and expire naturally via preview_expiry_seconds (5 min).
    returned_preview_ids = [leg["preview_id"] for leg in trades if leg.get("preview_id")]
    trade_service.invalidate_previews(returned_preview_ids)

    failed_tickers = [leg["ticker"] for leg in preview_failures]
    for leg in trades:
        leg.pop("preview_id", None)
        if not leg.get("error"):
            leg["error"] = (
                f"Blocked: other hedge legs failed preview ({', '.join(failed_tickers)}). "
                "All legs must succeed for hedge execution."
            )
    warnings.append(
        "Some hedge legs could not be previewed. All legs are blocked to prevent "
        "partial execution of an incomplete hedge."
    )
```

**Also add `invalidate_previews()` to `TradeExecutionService`** — deletes preview rows so they cannot be auto-repreviewed or executed. Uses `user_id` scoping consistent with other preview mutations (`_store_preview` at line 2601, `execute_order` at line 1569):

```python
def invalidate_previews(self, preview_ids: List[str]) -> None:
    """Delete preview rows so they cannot be executed or auto-repreviewed."""
    if not preview_ids:
        return
    user_id = self._get_user_id()
    placeholders = ",".join(["%s"] * len(preview_ids))
    with get_db_session() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"DELETE FROM trade_previews WHERE user_id = %s AND id IN ({placeholders})",
            (user_id, *preview_ids),
        )
        conn.commit()
```

Deletion is preferred over setting `expires_at` because expired previews are auto-repreviewed at `trade_execution_service.py:1601` — setting `expires_at=NOW()` would not actually prevent execution. Deleting the rows ensures no path can recover them.

**Note on execution semantics**: Hedge execution (`/api/hedging/execute` action="execute") is best-effort and sequential — legs execute one at a time, and partial fills are possible. This is a pre-existing design characteristic of the trade execution system, not introduced by SHORT support. True atomic multi-leg execution would require broker-level batch/bracket order support, which is out of scope. The partial-preview guard above prevents the specific risk of executing an incomplete hedge (missing SHORT legs), but does not guarantee all-or-nothing execution once all legs preview successfully.

The existing-short preflight guard at lines 262-271 is **KEPT**.

### Step 13: Update Level 2 tests that assert the removed hard block

**File**: `tests/routes/test_hedging_short_support.py`

Three tests assert the Level 2 hard block behavior that Step 12 removes:

- `test_hedge_execute_preview_generates_short_leg` (line 99): asserts `status == "error"`, `preview_calls == []`, and error message about broker margin. **Update**: SHORT legs should now go through to `preview_order()`. Assert `preview_calls` is non-empty (or errors from broker/feature flag, not from the hard block).

- `test_hedge_execute_preview_summary_counts_short_as_sell` (line 134): asserts `preview_calls == []`. **Update**: Remove this assertion — previews are now called. The summary counting logic itself is unchanged.

- `test_hedge_execute_preview_with_short_legs_returns_error_no_previews` (line 159): asserts the hard block error messages and `preview_calls == []`. **Update or remove**: This test's premise (hard block exists) is no longer true. Replace with a test that verifies SHORT legs reach `preview_order()` and get proper broker/feature-flag errors.

### Step 14: COVER account resolution

**File**: `services/trade_execution_service.py`

**14a — `_find_accounts_holding_ticker()`** (line 2658): Currently only finds accounts with positive quantities (net long). For COVER, we need to find accounts with negative quantities (short positions).

Add a parallel method or parameter:
```python
def _find_accounts_holding_ticker(
    self,
    ticker: str,
    candidate_ids: List[str],
    direction: str = "long",  # "long" or "short"
) -> List[str]:
```

In the position check loop, filter by `quantity > 0` for "long" (existing behavior) or `quantity < 0` for "short".

**14b — `_resolve_target_account()`** (line 2724): Currently auto-selects holder account only for SELL. Add COVER:

```python
# After the existing SELL auto-select block
if not account_id and side and side.upper() == "COVER" and ticker:
    holders = self._find_accounts_holding_ticker(ticker, [...], direction="short")
    if len(holders) == 1:
        # auto-select the single account with a short position
        ...
```

### Step 15: Tests

**New file**: `tests/services/test_short_execution.py`

1. `test_allowed_sides_includes_short_cover` — ALLOWED_SIDES contains all 4 values
2. `test_short_blocked_when_feature_disabled` — SHORT side with `SHORT_SELLING_ENABLED=false` → error
3. `test_short_allowed_when_feature_enabled` — SHORT side with flag on → no flag error
4. `test_buying_power_not_checked_for_short` — SHORT does NOT trigger the BUY-only buying power check (margin validation is broker-side)
5. `test_buying_power_still_checked_for_buy` — BUY still checks buying power (regression guard)
6. `test_no_share_check_for_short` — SHORT with 0 held shares → no share error
7. `test_cover_requires_short_position` — COVER with held >= 0 → error
8. `test_cover_checks_short_quantity` — COVER 100 with only 50 short → error
9. `test_weight_impact_short_goes_negative` — SHORT produces negative post_ticker_value
10. `test_weight_impact_cover_clamps_at_zero` — COVER on short position: min(current + notional, 0). Full cover of -$5000 at $6000 notional → 0 (not +$1000)
11. `test_weight_impact_sell_clamped_to_zero` — SELL still clamps (regression)
12. `test_concentration_cap_catches_large_short` — SHORT producing abs(post_weight) > max_weight → error
13. `test_short_blocked_on_account_with_any_existing_short` — SHORT on ticker A, but account has short in ticker B → error (account-wide guard)
14. `test_short_allowed_on_account_without_any_shorts` — SHORT on ticker with no shorts anywhere in account → no existing-short error
15. `test_short_allowed_when_long_same_ticker` — SHORT on ticker where held > 0 → no error (IB handles cross-zero; hedge decomposition produces paired SELL+SHORT)
15. `test_cover_not_blocked_by_feature_flag` — COVER with flag off → no feature-flag error (COVER is always allowed)
16. `test_execute_rejects_short_when_flag_turned_off` — preview SHORT with flag on, then execute with flag off → ValueError
17. `test_execute_allows_short_when_long_present` — preview SHORT on ticker where account is long → no error at execute (IB handles cross-zero)
18. `test_execute_rejects_short_when_account_has_new_short` — preview SHORT, then account gets short elsewhere → ValueError at execute

**New file**: `tests/brokerage/test_ibkr_short_mapping.py`

17. `test_ibkr_build_order_short_maps_to_sell` — SHORT → action="SELL" (IB general accounts)
18. `test_ibkr_build_order_cover_maps_to_buy` — COVER → action="BUY"
19. `test_ibkr_build_order_buy_unchanged` — BUY → "BUY" (regression)
20. `test_ibkr_build_order_sell_unchanged` — SELL → "SELL" (regression)
21. `test_ibkr_recovery_probe_matches_mapped_action` — recovery probe matches SHORT order via mapped "SELL" action

**New file**: `tests/brokerage/test_broker_short_rejection.py`

22. `test_schwab_preview_rejects_short` — Schwab `preview_order(side="SHORT")` raises ValueError with IBKR suggestion (tests at preview_order level, not just _instruction_for_side)
23. `test_schwab_cover_order_spec_uses_buy_to_cover` — Schwab `_build_order_spec(side="COVER")` returns spec with `instruction="BUY_TO_COVER"`, does NOT route through `equity_sell_*` builders
24. `test_snaptrade_rejects_short` — SnapTrade `preview_order(side="SHORT")` raises ValueError
25. `test_snaptrade_cover_maps_to_buy` — SnapTrade `preview_order(side="COVER")` succeeds with side="BUY"
26. `test_position_refresh_failure_blocks_short` — force_refresh returns empty + target provider in provider_errors → error, not pass-through
27. `test_unrelated_provider_error_does_not_block_short` — force_refresh returns empty positions for target account + provider_errors from a DIFFERENT provider → SHORT proceeds (not blocked by unrelated outage)
28. `test_hedge_partial_preview_strips_ids_and_invalidates_rows` — SELL leg succeeds (has preview_id) + SHORT leg fails → ALL preview_ids stripped from response, `invalidate_previews` called with the returned preview IDs (deletes successful DB rows; validation-failed rows expire via TTL), warning present
29. `test_hedge_all_legs_succeed_keeps_preview_ids` — SELL + SHORT both succeed on IBKR → all preview_ids kept, status="success", `invalidate_previews` NOT called (regression guard)
30. `test_invalidate_previews_deletes_rows` — `invalidate_previews(["id1"])` deletes the preview row from DB (user_id scoped)
31. `test_provider_error_blocks_short_even_with_positions` — target provider has error but other provider contributed positions → SHORT still blocked (fail-closed regardless of rows)

**New file**: `tests/services/test_cover_account_routing.py`

30. `test_find_accounts_holding_ticker_short_direction` — `_find_accounts_holding_ticker(ticker, [...], direction="short")` finds accounts with negative qty
31. `test_resolve_target_account_cover_single_holder` — `_resolve_target_account(side="COVER", ticker="XYZ")` auto-selects the single short-holder account
32. `test_resolve_target_account_cover_multi_holder_requires_explicit` — COVER with multiple short-holder accounts → requires explicit account_id

**New file**: `tests/routes/test_hedging_short_execution.py`

25. `test_hedge_execute_short_leg_previews_when_enabled` — with flag on, SHORT legs go through to preview_order (monkeypatched). Verify no hard block.
26. `test_existing_short_guard_still_active` — account with negative qty non-cash position → still returns error
27. `test_execute_time_cover_recheck` — COVER at execute time with no short position → ValueError

**Modified file**: `tests/routes/test_hedging_short_support.py`

23. Update `test_hedge_execute_preview_generates_short_leg` — remove hard-block assertions, verify SHORT legs reach preview_order
24. Update `test_hedge_execute_preview_summary_counts_short_as_sell` — remove `preview_calls == []` assertion
25. Update/remove `test_hedge_execute_preview_with_short_legs_returns_error_no_previews` — hard block no longer exists

## Files Changed

| File | Change | Lines |
|------|--------|-------|
| `settings.py` | Add `SHORT_SELLING_ENABLED` flag | ~406 |
| `brokerage/trade_objects.py` | Expand ALLOWED_SIDES | 22 |
| `database/migrations/20260327_add_short_cover_sides.sql` | New — expand CHECK constraints | New |
| `services/trade_execution_service.py` | Feature flag gate (preview + execute), existing-short guard, buying power (2 locations), share check, weight impact, concentration controls (3 locations), execute re-check, COVER account resolution, recovery probe mapping | 2328, 1625, 2377, 390, 2383-2392, 3213-3216, 2405, 2410, 400, 1628, 2658, 2724, 2942 |
| `brokerage/ibkr/adapter.py` | SHORT→SELL action mapping (general accounts) | 1142 |
| `brokerage/schwab/adapter.py` | Reject SHORT, map COVER→BUY | 230-236 |
| `brokerage/snaptrade/adapter.py` | Reject SHORT/COVER early in preview_order | ~117 |
| `mcp_tools/trading.py` | Update side Literal type | 40 |
| `mcp_server.py` | Update side Literal type | 2611 |
| `routes/hedging.py` | Remove has_short_legs hard block | 340-360 |
| `tests/routes/test_hedging_short_support.py` | Update 3 tests that assert removed hard block | 99, 134, 159 |
| `tests/services/test_short_execution.py` | New — 27 tests | New |
| `tests/services/test_cover_account_routing.py` | New — 3 tests | New |
| `tests/brokerage/test_ibkr_short_mapping.py` | New — 5 tests | New |
| `tests/brokerage/test_broker_short_rejection.py` | New — 5 tests | New |
| `tests/routes/test_hedging_short_execution.py` | New — 3 tests | New |

## NOT Changed (deferred)

- **Existing-short preflight guard** (`routes/hedging.py:262-271`) — kept. Accounts with existing shorts are blocked until the 8 snapshot locations are fixed.
- **8 snapshot locations** discarding `value <= 0` / clamping qty — separate phase. Requires rethinking portfolio_total semantics (net vs gross exposure).
- **Schwab SHORT support** — SDK has `SELL_SHORT` instruction but adapter order routing (`adapter.py:296`) sends all non-BUY through `equity_sell_*` builders. Needs proper routing work. COVER works (maps to BUY_TO_COVER).
- **Frontend trade client types** — `APIService.ts:245` (`TradePreviewParams.side`) and `tradingIntentStore.ts:3` still have `'BUY' | 'SELL'`. The hedge workflow dialog types were updated in Level 2, but the general trading types need updating when SHORT/COVER is exposed in the trading UI (currently only reachable via hedge tool and MCP).
- **SnapTrade SHORT support** — unclear if API supports it. Rejected with ValueError for now. COVER works (maps to BUY).

## Verification

1. Run DB migration: `psql -f database/migrations/20260327_add_short_cover_sides.sql`
2. Run new tests: `pytest tests/services/test_short_execution.py tests/brokerage/test_ibkr_short_mapping.py tests/brokerage/test_broker_short_rejection.py tests/routes/test_hedging_short_execution.py -v`
3. Run updated Level 2 tests: `pytest tests/routes/test_hedging_short_support.py -v`
4. Run Level 2 regression: `pytest tests/mcp_tools/test_trading_helpers.py tests/mcp_tools/test_basket_short_guard.py -v`
5. Run existing trade execution tests: `pytest tests/services/test_trade_execution_service_preview.py -v`
6. Manual: Set `SHORT_SELLING_ENABLED=true`, connect IBKR, run hedge analysis → click Execute on a direct offset → verify SHORT leg gets an IBKR preview (or IBKR-specific error if TWS not connected)

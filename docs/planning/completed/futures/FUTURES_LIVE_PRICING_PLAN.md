# Live Futures Pricing for Trade Preview (Phase 9)
**Status:** DONE

## Context

The `preview_futures_roll` MCP tool currently returns margin/commission data from IBKR's `whatIfOrder()` but has **zero live pricing**. For Market orders, `estimated_price` is always `None`. For Limit orders, it just echoes back the user-provided `limit_price`. Meanwhile, the equity trade preview (`preview_order`) fetches live bid/ask/mid via `reqMktData`. This feature adds the same live pricing to futures roll previews using the existing `fetch_snapshot()` infrastructure.

**Problem**: When a user runs `preview_futures_roll` with `order_type=Market`, they get margin and commission but no price information — they can't see where the market is trading before deciding to execute.

**Solution**: Fetch live snapshots for both the front-month and back-month contracts at the service layer (outside the adapter's lock), compute the calendar spread, and include all pricing in the preview response.

## Critical Design Constraint: `ibkr_shared_lock`

Both `adapter.preview_roll()` (`brokerage/ibkr/adapter.py:759`) and `fetch_snapshot()` (`ibkr/market_data.py:610`) acquire `ibkr_shared_lock` (from `ibkr/locks.py`). They **cannot run concurrently** — calling `fetch_snapshot()` from inside the adapter would deadlock.

**Decision**: Fetch market data at the **service layer** (`services/trade_execution_service.py`), BEFORE the adapter call. Sequential execution: snapshot first → whatIfOrder second. If snapshot fails (market closed), proceed to whatIfOrder anyway — the preview still works, just without live prices.

## Implementation Steps

### Step 1: Add `market_data` field to `TradePreviewResult`

**File:** `brokerage/trade_objects.py`

Add optional field after `broker_provider` (line 98):
```python
market_data: Optional[Dict[str, Any]] = None
```

Surface in `to_api_response()` — add to `"data"` dict (after line 131):
```python
"market_data": self.market_data,
```

Surface in `to_formatted_report()` — add market data section (after line 154):
```python
if self.market_data:
    lines.append("Market Data:")
    for leg in ("front_month", "back_month"):
        leg_data = self.market_data.get(leg)
        if leg_data and not leg_data.get("error"):
            lines.append(f"  {leg}: bid={leg_data.get('bid')} ask={leg_data.get('ask')} mid={leg_data.get('mid')} last={leg_data.get('last')}")
    spread = self.market_data.get("spread", {})
    if spread.get("mid") is not None:
        lines.append(f"  spread_mid: {spread['mid']:.4f}")
```

Backward-compatible: defaults to `None`, existing callers unaffected.

### Step 2: Add `_fetch_roll_market_data()` helper

**File:** `services/trade_execution_service.py`

New private method on `TradeExecutionService` (~40 lines):

1. Import `resolve_futures_contract` from `ibkr.contracts` and `IBKRMarketDataClient` from `ibkr.market_data`
2. Build two `Future` contracts using `resolve_futures_contract(symbol, contract_month=front_month)` / `resolve_futures_contract(symbol, contract_month=back_month)`
3. Call `IBKRMarketDataClient().fetch_snapshot(contracts=[front_contract, back_contract])`
4. Parse each leg: extract `bid/ask/mid/last/close/volume`, flag errors
5. Compute `spread.mid = back_mid - front_mid` if both legs have mid prices
6. Return structured dict, or `None` on any exception (graceful degradation)

### Step 3: Modify `preview_roll()` to use market data

**File:** `services/trade_execution_service.py` (modify existing `preview_roll()` at lines 512-667)

**Insert** market data fetch after adapter resolution (line 548) but BEFORE `adapter.preview_roll()` (line 555):
```python
market_data_result = self._fetch_roll_market_data(sym, fm, bm)
```

**After** getting `estimated_price` from adapter (line 572), derive price for Market orders:
```python
if estimated_price is None and market_data_result:
    spread_mid = (market_data_result.get("spread") or {}).get("mid")
    if spread_mid is not None:
        # long_roll: SELL front, BUY back → spread = back - front
        # short_roll: BUY front, SELL back → negate
        estimated_price = spread_mid if roll_direction == "long_roll" else -spread_mid
```

**Always recompute** `estimated_total` with contract multiplier when we have an estimated_price AND commission is known.
The adapter's existing formula (`adapter.py:787`) is `limit_price * quantity + commission` which is **wrong for futures** — it's missing the contract multiplier. Fix this for both Market and Limit orders:
```python
if estimated_price is not None and estimated_commission is not None:
    from brokerage.futures.contract_spec import get_contract_spec
    spec = get_contract_spec(sym)
    multiplier = float(spec.multiplier) if spec else 1.0
    notional = abs(estimated_price) * float(quantity) * multiplier
    estimated_total = notional + estimated_commission
```
Note: when commission is unavailable (`None`), `estimated_total` stays `None` — preserving existing behavior where the test at `test_trade_execution_service_preview.py:90` expects total=None when IBKR can't compute commission. Pre-existing multiplier bug fix.

**Add** market-closed warning to `validation_warnings`:
```python
if market_data_result is None:
    validation_warnings.append("Live market data unavailable (market may be closed)")
elif market_data_result.get("warnings"):
    validation_warnings.extend(market_data_result["warnings"])
```

**Embed** in `broker_preview_data` for audit trail:
```python
broker_preview_data["market_data_at_preview"] = market_data_result
```

**Pass** to `TradePreviewResult` constructor:
```python
market_data=market_data_result,
```

### Step 4: MCP tool — no changes needed

`mcp_tools/futures_roll.py` calls `result.to_api_response()` which automatically includes the new `market_data` field.

## Order Type Logic

| Scenario | `estimated_price` | `market_data` |
|----------|-------------------|---------------|
| Market + live data | `spread.mid` (signed by direction) | Full snapshot both legs |
| Market + closed | `None` (as before) | `None` + warning |
| Market + partial (one leg error) | `None` (can't compute spread) | Partial + leg warnings |
| Limit + any | `limit_price` (unchanged) | Present for comparison |

## Spread Sign Convention

- **Long roll** (SELL front, BUY back): `estimated_price = back_mid - front_mid`
- **Short roll** (BUY front, SELL back): `estimated_price = front_mid - back_mid`

`estimated_total = |estimated_price| × quantity × multiplier + commission`

## Files Changed (4)

| File | Change | ~Lines |
|------|--------|--------|
| `brokerage/trade_objects.py` | Add `market_data` field + surface in API/report | +12 |
| `services/trade_execution_service.py` | Add `_fetch_roll_market_data()` + modify `preview_roll()` | +65 |
| `tests/services/test_trade_execution_service_preview.py` | 8 new test cases | +200 |
| `tests/core/test_trade_objects_dataclasses.py` | 2 new serialization tests for `market_data` | +40 |

**Unchanged**: `mcp_tools/futures_roll.py`, `brokerage/ibkr/adapter.py`, `ibkr/market_data.py`

## Existing Code Reused

- `ibkr/market_data.py:569` — `fetch_snapshot()` (live bid/ask/mid/last/volume)
- `ibkr/contracts.py:54` — `resolve_futures_contract(symbol, contract_month)` (creates `Future` contract)
- `brokerage/futures/contract_spec.py:125` — `get_contract_spec(symbol)` (multiplier for total)
- `brokerage/trade_objects.py:100` — `to_api_response()` auto-surfaces new field

## Test Plan

### Service-layer tests (`tests/services/test_trade_execution_service_preview.py`)

| # | Test | Verifies |
|---|------|----------|
| 1 | `test_preview_roll_market_order_uses_spread_mid` | Market order + live data → `estimated_price = spread.mid`, `estimated_total = |price| × qty × multiplier + commission` |
| 2 | `test_preview_roll_limit_order_keeps_limit_price_with_multiplier` | Limit order + live data → `estimated_price = limit_price`, `estimated_total` uses multiplier (fixes pre-existing bug), `market_data` present |
| 3 | `test_preview_roll_market_closed_graceful_degradation` | `_fetch_roll_market_data` returns `None` → status "success", warning added, `estimated_price = None` |
| 4 | `test_preview_roll_partial_snapshot_one_leg_error` | One leg errors → `estimated_price = None`, warning in `market_data` |
| 5 | `test_preview_roll_short_roll_negates_spread` | `direction=short_roll` → `estimated_price = -spread.mid` |
| 6 | `test_preview_roll_market_data_fetched_before_adapter` | Verify `_fetch_roll_market_data` is called before `adapter.preview_roll()` — sequencing guard against future refactors that could cause deadlock |
| 7 | `test_preview_roll_commission_unavailable_keeps_total_none` | Live price available + commission=None → `estimated_total = None`, `estimated_price` still set from spread mid |
| 8 | `test_preview_roll_market_data_persisted_in_broker_preview_data` | `broker_preview_data["market_data_at_preview"]` is set and passed through to `_store_preview()` |

### Dataclass serialization tests (`tests/core/test_trade_objects_dataclasses.py`)

| # | Test | Verifies |
|---|------|----------|
| 9 | `test_trade_preview_result_market_data_in_api_response` | `to_api_response()` includes `market_data` in `data` dict when set, and omits/nulls when `None` |
| 10 | `test_trade_preview_result_market_data_in_report` | `to_formatted_report()` renders market data section with bid/ask/mid/spread |

## Verification

1. `pytest tests/services/test_trade_execution_service_preview.py -v` — all tests pass
2. `pytest tests/mcp_tools/test_futures_roll.py -v` — existing tests still pass
3. Live test (market hours): `preview_futures_roll(symbol="ES", front_month="202503", back_month="202506", quantity=1, order_type="Market")` → verify `market_data` with bid/ask/mid
4. Live test (market closed): Same call → verify warning, `estimated_price = None`, preview still succeeds

# Trade Routing Visibility / Audit

**Date**: 2026-03-02
**Status**: COMPLETE (implemented in commit `47eb2099`)

## Context

When `preview_trade` or `execute_trade` runs, `_resolve_broker_adapter()` decides which broker handles the request. The routing decision (`broker_provider`) is stored in the DB but **never returned to the client**. Additionally, when a mapped account's intended broker is unavailable, the system silently falls through to a generic adapter loop — no log, no error.

From an agent's perspective, there's no way to know which broker handled a trade without querying the DB directly, and no signal when routing doesn't go as configured.

## Implementation

### 1. Surface `broker_provider` in response objects

**`brokerage/trade_objects.py`**

Add `broker_provider: Optional[str] = None` field to both:
- `TradePreviewResult` (line 70) — add after `error` field (line 97), as last optional field
- `TradeExecutionResult` (line 161) — add after `error` field (line 182), before `new_preview` (line 183)

Add `"broker_provider": self.broker_provider` to `to_api_response()` in the `metadata` dict for both classes (lines 106 and 193).

Add `broker_provider` line to `to_formatted_report()` for both classes.

**`services/trade_execution_service.py`**

Pass `broker_provider=adapter.provider_name` at `TradePreviewResult` construction sites where the adapter is resolved:
- `preview_order()` — 3 returns: validation-failed (line 338), post-preview-failed (line 414), success (line 462). The exception-catch return (line 488) stays `None` since adapter may not exist.
- `preview_roll()` — success return (line 620). Exception-catch return (line 644) stays `None`.

For `TradeExecutionResult`:
- `_execution_result_from_row()` (line 2281) — add `broker_provider=row.get("broker_provider")`. The `trade_orders` table already has this column. This covers the success paths for both `execute_order()` and `execute_roll()`.
- All other `TradeExecutionResult` construction sites (~15 error/edge-case returns) use default `None` — no changes needed since `broker_provider` defaults to `None`.

### 2. Fail-loud when intended broker unavailable (replaces silent fallthrough)

**`services/trade_execution_service.py`** — `_resolve_broker_adapter()` (line 1840)

Current behavior: if `account_id` is in `TRADE_ACCOUNT_MAP` and the intended adapter (from `TRADE_ROUTING`) can't claim it, silently falls through to generic adapter loop at line 1860.

New behavior: **raise `ValueError`** instead of falling through. Error message includes which adapters were tried. The generic adapter loop (line 1860) remains for accounts NOT in `TRADE_ACCOUNT_MAP` — unchanged.

```python
if account_id in TRADE_ACCOUNT_MAP:
    tried = []
    for _institution, adapter_name in TRADE_ROUTING.items():
        adapter = self._adapters.get(adapter_name)
        if not adapter:
            tried.append(f"{adapter_name} (not registered)")
            continue
        try:
            if adapter.owns_account(account_id):
                return adapter
        except Exception as e:
            portfolio_logger.warning(
                "Error checking mapped account ownership for adapter '%s': %s",
                adapter_name, e,
            )
        tried.append(adapter_name)

    raise ValueError(
        f"Account '{account_id}' is in TRADE_ACCOUNT_MAP but its intended broker(s) "
        f"[{', '.join(tried)}] cannot handle it. "
        f"Check that the broker adapter is running and the account is authorized."
    )
```

This eliminates the need for a separate fallthrough warning log — the error itself is the signal.

### 3. Tests

**`tests/services/test_trade_execution_service_preview.py`**

1. **`broker_provider` in preview result** — Extend existing `test_preview_order_propagates_preview_warnings_and_keeps_total_unknown` to assert `result.broker_provider == "ibkr"`
2. **`broker_provider` in `to_api_response()`** — Construct `TradePreviewResult` and `TradeExecutionResult` with `broker_provider="ibkr"`, assert it appears in `response["metadata"]["broker_provider"]`
3. **Fail-loud for mapped accounts** — Set `TRADE_ACCOUNT_MAP = {"acct123": "U123"}`, register adapter whose `owns_account` returns `False`, call `_resolve_broker_adapter("acct123")`, assert `ValueError` with "TRADE_ACCOUNT_MAP" in message
4. **Generic loop still works for unmapped accounts** — Account NOT in `TRADE_ACCOUNT_MAP`, adapter `owns_account` returns `True`, verify adapter returned normally
5. **`_execution_result_from_row` passes through `broker_provider`** — Mock DB row dict with `broker_provider="ibkr"`, assert `result.broker_provider == "ibkr"`

## Files Modified

| File | Change |
|------|--------|
| `brokerage/trade_objects.py` | Add `broker_provider` field + serialization to both result dataclasses (~10 lines) |
| `services/trade_execution_service.py` | Pass `broker_provider` at ~6 construction sites + `_execution_result_from_row`. Fail-loud in `_resolve_broker_adapter()` for mapped accounts (~15 lines changed) |
| `tests/services/test_trade_execution_service_preview.py` | 5 new tests |

## Notes

- `BasketTradePreviewResult` in `mcp_tools/basket_trading.py` is a **different class** — not affected.
- ~15 `TradeExecutionResult` error-path construction sites (preview not found, expired, cancelled, etc.) don't need changes — `broker_provider` defaults to `None`.
- Existing tests in `tests/core/test_trade_objects_dataclasses.py` construct both result classes — they'll continue to work since `broker_provider` has a default.

## Verification

1. `pytest tests/services/test_trade_execution_service_preview.py` — all tests pass
2. `pytest tests/core/test_trade_objects_dataclasses.py` — existing dataclass tests pass
3. `pytest tests/` — no regressions
4. Live test: `preview_trade(ticker="FIG", quantity=10, side="BUY", account_id="DU...")` — response should include `broker_provider: "ibkr"` in metadata

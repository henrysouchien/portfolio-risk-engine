# Bug Fix Plan — 4 Open Bugs (v4 — Codex PASS)

## Context

Four bugs have been open since early-to-mid March, surfaced by the analyst-agent or E2E testing. This plan fixes all four in priority order.

**Codex review (v1)**: 1 PASS, 3 FAIL. Key corrections applied:
- Bug 4: Original "consolidation input is empty" was already fixed (`position_service.py:584`). Reframed as VIRTUAL_FILTERED correctness fix. Layer violation fixed — move `_rebuild_position_result` out of MCP layer.
- Bug 3: `_extract_auth_warnings` / `_attach_auth_warnings` already exist in `positions.py:116-143`. Reuse them. Must check `position_result.provider_errors` BEFORE the empty-position guard (line 431) — otherwise Schwab-only users get a generic "no positions" error.
- Bug 2: DB re-read is still stale data. Changed to live IBKR holdings query via `IBKRClient.get_positions()` with DB fallback.

---

## Bug 4: VIRTUAL_FILTERED Post-Filter Consolidation

**Issue**: `_load_portfolio_for_analysis()` in `mcp_tools/risk.py:417-423` and `load_portfolio_for_performance()` in `services/performance_helpers.py:89-91` skip `_rebuild_position_result()` after filtering. `get_positions` does this at `positions.py:637-642`. This causes inconsistent position data for scoped portfolios.

**Note**: The original "consolidation input is empty" crash was already fixed at `position_service.py:584` (guard on empty). This fix addresses the remaining correctness gap — filtered portfolios should get properly consolidated positions.

### Step 1: Move `_rebuild_position_result` to service layer

Move from `mcp_tools/positions.py:48-69` to `services/position_service.py` as a method or module-level function. This eliminates the layer violation of importing MCP code into services.

**File: `services/position_service.py`** — Add standalone function (near `consolidate_positions`):

```python
def rebuild_position_result(
    service: "PositionService",
    result: "PositionResult",
    *,
    consolidate: bool,
) -> "PositionResult":
    """Re-consolidate a PositionResult after filtering (e.g. VIRTUAL_FILTERED)."""
    if not consolidate or not result.data.positions:
        return result
    frame = pd.DataFrame(result.data.positions)
    rebuilt_df = service._consolidate_cross_provider(frame)
    rebuilt = PositionResult.from_dataframe(
        rebuilt_df,
        user_email=result.data.user_email,
        consolidated=True,
        from_cache=result.data.from_cache,
        cache_age_hours=result.data.cache_age_hours,
    )
    rebuilt.provider_errors = dict(getattr(result, "provider_errors", {}) or {})
    rebuilt._provider_errors = rebuilt.provider_errors
    rebuilt._cache_metadata = dict(getattr(result, "_cache_metadata", {}) or {})
    return rebuilt
```

**File: `mcp_tools/positions.py`** — Update `_rebuild_position_result` to delegate:

```python
def _rebuild_position_result(service, result, *, consolidate):
    from services.position_service import rebuild_position_result
    return rebuild_position_result(service, result, consolidate=consolidate)
```

### Step 2: Add consolidation call in `_load_portfolio_for_analysis`

**File: `mcp_tools/risk.py` (after line 423)**:

```python
position_result = filter_position_result(position_result, scope.account_filters or [])
# Post-filter consolidation (mirrors get_positions pattern)
from services.position_service import rebuild_position_result
position_result = rebuild_position_result(position_service, position_result, consolidate=True)
```

### Step 3: Add conditional consolidation call in `load_portfolio_for_performance`

**File: `services/performance_helpers.py` (after line 91)**:

The local variable `consolidate_positions` is deliberately set to `False` for realized `source != "all"` (line 75-76) and for VIRTUAL_FILTERED pre-filter (line 77-78). The realized engine needs raw per-source rows for source attribution (`account_id`, `position_source`, `institution`). Cross-provider consolidation drops this detail.

Post-filter rebuild must respect this flag — only consolidate when `consolidate_positions` would have been True for this request:

```python
position_result = filter_position_result(position_result, scope.account_filters or [])
# Post-filter consolidation — only when consolidation is appropriate for this mode.
# Realized source-scoped analysis needs raw rows; skip consolidation there.
if consolidate_positions:
    from services.position_service import rebuild_position_result
    position_result = rebuild_position_result(position_service, position_result, consolidate=True)
```

Since `consolidate_positions` is `False` for VIRTUAL_FILTERED (line 78), this means performance_helpers won't consolidate for scoped portfolios. This is correct — the realized engine needs per-account rows. The risk tools path (`risk.py`) unconditionally consolidates, which is also correct since risk analysis works on aggregated positions.

---

## Bug 3: Schwab Token Expiry — Surface Auth Errors

**Issue**: When Schwab's refresh token expires, `position_service.py:520-523` catches the error, logs a warning, and substitutes an empty DataFrame. The error IS stored in `provider_errors` on `PositionResult`. But in `_load_portfolio_for_analysis()`, the empty-position guard at line 431 raises a generic "No brokerage positions found" — hiding the real auth problem. This is especially bad when Schwab is the only provider.

**Existing infrastructure to reuse**:
- `_extract_auth_warnings(result)` at `mcp_tools/positions.py:116` — already classifies provider errors
- `_attach_auth_warnings(response, warnings)` at `mcp_tools/positions.py:140` — already attaches to responses
- `_classify_auth_error_from_string()` at `mcp_tools/common.py:56` — string-based auth detection

### Step 1: Upgrade logging in position_service.py

**File: `services/position_service.py`** — In both catch blocks (lines 494-497 sequential, lines 520-523 parallel):

```python
except Exception as exc:
    error_str = str(exc).lower()
    is_auth = (
        "refresh token expired" in error_str
        or "invalid_grant" in error_str
        or "item_login_required" in error_str
    )
    if is_auth:
        portfolio_logger.error("Provider %s auth failed: %s", provider_name, exc)
    else:
        portfolio_logger.warning("Provider %s failed: %s", provider_name, exc)
    # rest unchanged (empty DataFrame + provider_errors storage)
```

### Step 2: Surface auth errors BEFORE empty-position guard in `_load_portfolio_for_analysis`

**File: `mcp_tools/risk.py`** — Insert between line 429 and 431 (after position fetch, before empty check):

```python
# Surface auth failures before the generic empty-position error
from mcp_tools.positions import _extract_auth_warnings
auth_warnings = _extract_auth_warnings(position_result)
if auth_warnings and not position_result.data.positions:
    # Only raise auth error for VIRTUAL_ALL (all providers).
    # For VIRTUAL_FILTERED, positions may be empty because the scoped
    # accounts don't match — an unrelated provider's auth failure
    # should not override the scoped-empty message.
    if scope.strategy != LoadStrategy.VIRTUAL_FILTERED:
        providers = ", ".join(w["provider"] for w in auth_warnings)
        raise ValueError(
            f"Provider authentication failed ({providers}). "
            f"{auth_warnings[0]['message']}"
        )
```

For VIRTUAL_FILTERED, auth warnings still get attached to the response via Step 3 (if some positions survive from other providers). If all positions are empty for a scoped portfolio, the existing "No positions found for this portfolio" message is more accurate than blaming auth.

### Step 3: Attach auth warnings to risk tool responses (partial auth failure)

When some providers succeed but others have auth errors, attach warnings to the response.

**File: `mcp_tools/risk.py`** — After `portfolio_data` is built (after line 438), stash provider errors:

```python
portfolio_data = position_result.data.to_portfolio_data(portfolio_name=portfolio_name)
# Preserve provider errors for downstream auth warning surfacing
setattr(portfolio_data, "_provider_errors", getattr(position_result, "provider_errors", {}) or {})
```

For the PHYSICAL path (after line 414):
```python
setattr(portfolio_data, "_provider_errors", {})
```

In `get_risk_score`, `get_risk_analysis`, `get_leverage_capacity` — before returning the response dict:

```python
from mcp_tools.positions import _extract_auth_warnings, _attach_auth_warnings
_auth_warnings = _extract_auth_warnings(portfolio_data)
response = _attach_auth_warnings(response, _auth_warnings)
```

This reuses the existing `_extract_auth_warnings` which already handles the `provider_errors` / `_provider_errors` attribute lookup pattern (see `positions.py:117-121`).

---

## Bug 2: SLV Oversized Order — Live Broker Holdings Check

**Issue**: SELL validation at `trade_execution_service.py:2382-2387` reads from the stale DB `positions` table. The SLV order for 75 shares was accepted when only 25 were held. Also, no re-validation between preview and execution.

**New approach**: Query live IBKR holdings via `IBKRClient.get_positions()` with DB fallback for non-IBKR providers.

### Step 1: Add `_get_live_position_quantity` method

**File: `services/trade_execution_service.py`** — Add new method near `_get_account_position_quantity` (line ~3128):

```python
def _get_live_position_quantity(self, broker_provider: str, account_id: str, ticker: str) -> float:
    """Query live broker holdings for a ticker. Falls back to DB if live query fails."""
    if broker_provider == "ibkr":
        try:
            from ibkr.client import IBKRClient
            client = IBKRClient()
            positions_df = client.get_positions(account_id=account_id)
            if not positions_df.empty:
                match = positions_df[positions_df['symbol'].str.upper() == ticker.upper()]
                held = float(match['position'].sum()) if not match.empty else 0.0
                portfolio_logger.info(
                    "Live IBKR qty check: ticker=%s, account=%s, held=%s",
                    ticker, account_id, held,
                )
                return held
        except Exception as e:
            portfolio_logger.warning("Live IBKR position query failed, falling back to DB: %s", e)

    # Fallback: DB positions table
    return self._get_account_position_quantity(account_id=account_id, ticker=ticker)
```

### Step 2: Use live check in `_validate_pre_trade`

**File: `services/trade_execution_service.py` (lines 2382-2387)** — Replace DB-only check:

`_validate_pre_trade` already receives `adapter` (see line 300). Use `adapter.provider_name` to determine the broker:

```python
if side == "SELL" and quantity_num is not None and ticker:
    held = self._get_live_position_quantity(
        broker_provider=adapter.provider_name if adapter else "",
        account_id=account_id,
        ticker=ticker,
    )
    if held < quantity_num:
        errors.append(
            f"Insufficient shares to sell {quantity_num:g} {ticker}; available in account: {held:g}"
        )
```

### Step 3: Add execution-time re-validation with live check

**File: `services/trade_execution_service.py`** — Insert before line 1638 (`order_params = self._build_order_params_for_execution`):

```python
# Re-validate SELL quantity against live broker holdings
preview_side = str(preview_row.get("side") or "").upper()
preview_ticker = str(preview_row.get("ticker") or "").upper()
preview_qty = _to_float(preview_row.get("quantity"))
if preview_side == "SELL" and preview_qty and preview_ticker:
    held = self._get_live_position_quantity(
        broker_provider=broker_provider,
        account_id=account_id,
        ticker=preview_ticker,
    )
    if held < preview_qty:
        raise ValueError(
            f"Position changed since preview: cannot sell {preview_qty:g} "
            f"{preview_ticker}, only {held:g} held (live check, account {account_id})"
        )
```

`broker_provider` is already in scope at this point in `execute_order()`.

### Step 4: Diagnostic logging in `_get_account_position_quantity` (DB fallback)

**File: `services/trade_execution_service.py` (line 3113)** — After account_ids resolution:

```python
portfolio_logger.info(
    "DB SELL qty check: ticker=%s, input_account=%s, resolved_accounts=%s",
    ticker, account_id, sorted(account_ids),
)
```

---

## Bug 1: `get_orders` — Missing `perm_id` Column

**Root cause**: Migration `database/migrations/20260304_add_perm_id.sql` exists but was never applied. The migration runner (`scripts/run_migrations.py`) is standalone — not auto-run at startup.

**Fix**: Run the migration.

```bash
python3 scripts/run_migrations.py
```

No code changes needed. The migration adds `VARCHAR(255) perm_id` to `trade_orders` and backfills from `brokerage_response` JSONB.

**Codex note**: The migration SQL is not `IF NOT EXISTS`-safe. If the column was partially added outside `_migrations` tracking, the migration will error. Check first with `\d trade_orders` in psql.

---

## Verification

### Bug 4 (consolidation)
- `python3 -m pytest tests/mcp_tools/ -k risk -x`
- `python3 -m pytest tests/unit/test_position_result.py -x`
- Manual: `get_risk_score(format="summary")` with a multi-account (VIRTUAL_FILTERED) portfolio

### Bug 3 (auth warnings)
- `python3 -m pytest tests/services/test_position_service*.py -x`
- Manual: with Schwab token expired, call `get_risk_score` — should show auth error, not generic "no positions"
- Manual: with Schwab token expired but IBKR up, call `get_risk_score` — should succeed with `auth_warnings` in response

### Bug 2 (live holdings check)
- `python3 -m pytest tests/services/test_trade_execution_service*.py -x`
- Manual: preview a SELL order and check logs for "Live IBKR qty check" messages
- Verify: SELL for more shares than held returns validation error

### Bug 1 (perm_id)
- Run migration, then `get_orders(days=30)` via MCP — should return orders

### Full suite
- `python3 -m pytest tests/ -x --timeout=60`

---

## Files Modified

| File | Bugs | Changes |
|------|------|---------|
| `services/position_service.py` | 3, 4 | Auth error logging upgrade + `rebuild_position_result` function (moved from MCP layer) |
| `mcp_tools/positions.py` | 4 | `_rebuild_position_result` delegates to service layer |
| `mcp_tools/risk.py` | 3, 4 | Post-filter consolidation + auth error surfacing before empty guard + auth warnings on responses |
| `services/performance_helpers.py` | 4 | Post-filter consolidation |
| `services/trade_execution_service.py` | 2 | `_get_live_position_quantity` (IBKR live + DB fallback) + execution-time re-validation + diagnostic logging |

# Schwab Trading Production-Readiness Plan

## Context

Schwab trading adapter (`brokerage/schwab/adapter.py`, 633 lines) is fully implemented but not wired for trade routing. The adapter supports BUY/SELL/COVER with MARKET/LIMIT/STOP/STOP_LIMIT orders via the direct Schwab API (schwab-py SDK). It's been sitting dormant — positions and transactions route to Schwab, but trades don't.

**Immediate blocker:** The Schwab OAuth refresh token is expired (-10.4 days). Before anything else, `python3 -m scripts.run_schwab login` must be run to re-authenticate. The 7-day token lifecycle is the primary operational risk.

**What already works:** The monitoring job (`com.henrychien.schwab-token-check` launchd plist) runs daily at 9 AM and correctly detects expiry. The `SchwabBrokerAdapter` is registered in `TradeExecutionService` when `SCHWAB_ENABLED=true`. The `_resolve_broker_adapter()` fallback already routes Schwab accounts via `owns_account()`.

## Codex Review Round 1 — Findings Addressed

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 1 | `place_order()` never raises on non-2xx — silent order failure | High | Phase 1A: add non-2xx guard in `place_order()` |
| 2 | TRADE_ACCOUNT_MAP routing uses aggregator ID not native ID | High | Descoped — no Schwab accounts use TRADE_ACCOUNT_MAP; removed false claim from plan |
| 3 | Health check only keys off `days_remaining`, ignores `warnings` | Medium | Phase 3A: check `warnings` list too |
| 4 | `check_schwab_token.py` exits 0 when token missing with SCHWAB_ENABLED=true | Medium | Phase 3C: fix exit behavior |
| 5 | Test plan misses non-2xx place/cancel, partial fills, expired-token-before-client | Medium | Phase 2B: expanded test list |

## Codex Review Round 2 — Findings Addressed

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 6 | No partial-fill test despite explicit logic at adapter.py:561 | Medium | Phase 2B: added `test_get_orders_partial_fill_detected` |
| 7 | Phase ordering wrong — monitoring before tests | Medium | Swapped: Phase 2 = Tests, Phase 3 = Monitoring |
| 8 | Test #6 mocks at wrong seam — `get_schwab_client` vs `_call_with_backoff` | Medium | Rewritten: mock the underlying client method to raise invalid_grant so `_call_with_backoff` catches and translates it |
| 9 | Status code rule mismatch — prose says `{200,201,202}`, guard uses `>=400`, adapter accepts 204 | Low | Standardized: guard raises on `>=400`, consistent with `_status_from_response` which accepts `{200,201,202,204}` |
| 10 | Verification only runs adapter/client tests, not script tests | Medium | Verification step 1 expanded to include script test files |

## Codex Review Round 3 — Findings Addressed

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 11 | Health check warning filter too narrow — `"Could not parse token file JSON"` misses keyword match | Medium | Phase 3A: FAIL on any non-empty `warnings` list (not keyword-matched) |
| 12 | Test count wrong — existing is 19 not 14 | Low | Verification updated: 18 new + 19 existing = 37 total |

## Codex Review Round 4 — Findings Addressed

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 13 | Monitor script (`check_schwab_token.py`) doesn't check `warnings` — only checks days + near_expiry | Medium | Phase 3C expanded: also check `health["warnings"]` non-empty → alert + exit 1 |
| 14 | Missing WARN-path test for `_check_schwab_token()` + verification omits existing `test_health_check.py` | Low | Phase 2D: added test #19 for WARN path. Verification expanded to include `test_health_check.py` (21 existing + 20 new = 41 total) |

## Codex Review Round 5 — Findings Addressed

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 15 | Severity regression — warnings branch uses `"expired"` keyword but `check_token_health()` emits `"near expiry"` for <=1 day | Low | Phase 3C: severity now uses `near_refresh_expiry` flag and `days <= 1.0` instead of keyword matching |
| 16 | Test #20 doesn't assert `_send_notification` called | Low | Test #20 updated to also assert `_send_notification` was called |

## Codex Review Round 6 — Findings Addressed

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 17 | Existing `test_near_expiry_sends_notification` expects old message format (`"1.5 days"`) but new warnings-first branch changes output | Low | Phase 3C: plan now notes existing test must be updated to match new message format (`"[URGENT] Schwab token issue: ..."`) |

## Phase 1: Error Handling Fixes (Ship First)

### 1A. Guard against non-2xx in `place_order()`

**File:** `brokerage/schwab/adapter.py:502-525`

Currently `place_order()` calls `_call_with_backoff()` then unconditionally builds an `OrderResult` — even if the response is 400, 403, etc. The execution service then persists this as "submitted successfully". This is the most dangerous production bug.

**Fix:** After `_call_with_backoff()` returns (line 503), check `response.status_code`. If `>= 400`, raise `RuntimeError` with the status code and response body. The guard uses `>= 400` (not "not in {200,201,202}") because `_status_from_response()` already accepts 204 as `ACCEPTED`, and 3xx responses are not expected from Schwab's order API.

```python
# After line 503: response = self._call_with_backoff(client.place_order, account_hash, order_spec)
status_code = getattr(response, "status_code", None)
if status_code is not None and status_code >= 400:
    payload = _response_payload(response)
    detail = payload if isinstance(payload, dict) else {"status_code": status_code}
    raise RuntimeError(
        f"Schwab order placement failed (HTTP {status_code}): {detail}"
    )
```

Note: The guard belongs after `_call_with_backoff()`, not inside it. `_call_with_backoff()` is a generic retry helper also used by `get_orders_for_account()` and other non-submit read paths — pushing terminal HTTP-error logic into it would over-broaden its contract.

### 1B. Guard against non-2xx in `cancel_order()`

**File:** `brokerage/schwab/adapter.py:586-610`

Same pattern — `cancel_order()` returns `CANCEL_PENDING` for non-2xx but never raises. A 400/403/404 should be an error, not a pending state.

**Fix:** After the `_call_with_backoff()` call, if `status_code >= 400`, raise `RuntimeError`.

```python
status_code = getattr(response, "status_code", None)
if status_code is not None and status_code >= 400:
    payload = _response_payload(response)
    detail = payload if isinstance(payload, dict) else {"status_code": status_code}
    raise RuntimeError(
        f"Schwab order cancellation failed (HTTP {status_code}): {detail}"
    )
```

### 1C. Add TRADE_ROUTING entry

**File:** `providers/routing_config.py:248`

```python
# Before:
TRADE_ROUTING = {
    "interactive_brokers": "ibkr",
}

# After:
TRADE_ROUTING = {
    "interactive_brokers": "ibkr",
    "charles_schwab": "schwab",
}
```

**Why:** Consistency with `POSITION_ROUTING` and `TRANSACTION_ROUTING` which both already have `"charles_schwab": "schwab"`. The fallback `owns_account()` scan works today, but explicit routing is cleaner. Note: no Schwab accounts currently use `TRADE_ACCOUNT_MAP` (the one existing mapping is IBKR), so the mapped-account resolution path is not exercised for Schwab. If that changes, the mapped-account `owns_account()` call at line 2911 would need a separate fix (it passes the aggregator ID, not the native ID).

## Phase 2: Test Coverage (Before Monitoring Changes)

### 2A. Order type tests — `tests/services/test_schwab_broker_adapter.py`

Add 3 tests:

1. **`test_stop_order_spec_includes_stop_price`** — Build a STOP order via `_build_order_spec()`, assert `orderType=STOP`, `stopPrice` present, no `price` key
2. **`test_stop_limit_order_spec_includes_both_prices`** — Build a STOP_LIMIT order, assert both `stopPrice` and `price` present
3. **`test_limit_order_placement`** — Place a LIMIT order through `place_order()`, assert the spec sent to the fake client has `orderType=LIMIT` and correct `price`

### 2B. Error handling + state tests — `tests/services/test_schwab_broker_adapter.py`

Add 7 tests:

4. **`test_call_with_backoff_retries_on_429`** — Mock function returns 429 twice then 200; assert called 3 times, final result is 200
5. **`test_call_with_backoff_exhausts_retries_on_persistent_429`** — Mock always returns 429; assert called 4 times (length of `_RETRY_DELAYS_SECONDS`), returns last 429 response
6. **`test_place_order_raises_on_invalid_grant_during_call`** — Mock the fake client's `place_order` method to raise an exception whose `str()` contains `"invalid_grant"`. This exercises `_call_with_backoff()` line 162 which catches `is_invalid_grant_error(exc)` and raises `RuntimeError` with the re-login message. Do NOT mock `get_schwab_client` — the invalid_grant detection happens inside `_call_with_backoff`, not at client construction.
7. **`test_place_order_raises_on_non_2xx_response`** — Mock `place_order` to return `_FakeResponse({}, status_code=400)`; assert `RuntimeError` is raised with "HTTP 400"
8. **`test_cancel_order_raises_on_non_2xx_response`** — Mock `cancel_order` to return `_FakeResponse({}, status_code=404)`; assert `RuntimeError` is raised with "HTTP 404"
9. **`test_place_order_raises_when_token_expired`** — Mock `get_schwab_client` to raise `RuntimeError("Schwab refresh token appears expired...")`. Assert the same error propagates up from `place_order()`.
10. **`test_get_orders_partial_fill_detected`** — Mock `get_orders_for_account` to return an order with `status=WORKING`, `filledQuantity=5`, `quantity=10`. Assert the returned `OrderStatus` has `status="PARTIAL"`, `filled_quantity=5.0`, `total_quantity=10.0`. This exercises the partial-fill detection at adapter.py:561.

### 2C. Token health tests — `tests/brokerage/test_schwab_client.py`

Add 4 tests:

11. **`test_check_token_health_missing_file`** — Mock missing token path; assert `token_file_exists=False` and `warnings` contains "missing"
12. **`test_check_token_health_fresh_token`** — Mock recent mtime and successful `get_schwab_client()`; assert `near_refresh_expiry=False`, positive `days_remaining`, empty `warnings`
13. **`test_check_token_health_near_expiry`** — Mock old mtime (>6 days); assert `near_refresh_expiry=True`
14. **`test_check_token_health_corrupt_json`** — Mock token file with invalid JSON; assert `warnings` contains parse error message

### 2D. Script tests

15. **`tests/scripts/test_health_check_schwab.py::test_schwab_token_check_pass`** — Mock `check_token_health()` returning healthy dict; assert `_check_schwab_token()` returns `CheckResult` with status `PASS`
16. **`tests/scripts/test_health_check_schwab.py::test_schwab_token_check_fail_missing`** — Mock missing token; assert status `FAIL`
17. **`tests/scripts/test_health_check_schwab.py::test_schwab_token_check_fail_on_any_warning`** — Mock health with `warnings=["Could not parse token file JSON: ..."]`; assert status `FAIL` (validates that ANY warning triggers failure, not just keyword-matched ones)
18. **`tests/scripts/test_check_schwab_token.py::test_missing_token_alerts_when_enabled`** — Mock `SCHWAB_ENABLED=true` and `token_file_exists=False`; assert `main()` returns 1 and calls `_send_notification`
19. **`tests/scripts/test_health_check_schwab.py::test_schwab_token_check_warn_near_expiry`** — Mock health with `days_remaining=1.5`, empty `warnings`; assert status `WARN`
20. **`tests/scripts/test_check_schwab_token.py::test_warnings_trigger_alert_even_with_days_remaining`** — Mock health with `days_remaining=5.0` but `warnings=["Could not parse token file JSON: ..."]`; assert `main()` returns 1 and `_send_notification` was called

## Phase 3: Monitoring Hardening

### 3A. Add Schwab token to startup health check

**File:** `scripts/health_check.py`

Add `_check_schwab_token()` following the `_check_ibkr_dual_provider()` pattern (lines 215-244). When `SCHWAB_ENABLED=true`:
- Call `check_token_health()` from `brokerage.schwab.client`
- FAIL if `not health["token_file_exists"]` (token missing while trading is enabled)
- FAIL if `health["refresh_token_days_remaining"]` is not None and `<= 1`
- FAIL if `health["warnings"]` is non-empty (any warning from `check_token_health()` indicates a problem — expired, parse error, client failure, etc.)
- WARN if `1 < days_remaining <= 2`
- PASS otherwise

When `SCHWAB_ENABLED` is not true, return PASS with "Schwab trading not enabled."

Add to `results` list at line 259.

### 3B. Increase monitoring to twice daily

**File:** `~/Library/LaunchAgents/com.henrychien.schwab-token-check.plist`

Change `StartCalendarInterval` to run at 9 AM and 6 PM:

```xml
<key>StartCalendarInterval</key>
<array>
    <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>18</integer><key>Minute</key><integer>0</integer></dict>
</array>
```

With the 2-day warning threshold, twice-daily checks give comfortable margin.

### 3C. Fix `check_schwab_token.py` missing-token + warnings behavior

**File:** `scripts/check_schwab_token.py:29-50`

Two issues:
1. Exits 0 (healthy) when token file is missing with `SCHWAB_ENABLED=true`
2. Returns 0 (healthy) when `days > WARN_DAYS` even if `health["warnings"]` contains real problems (corrupt JSON, client failures)

**Fix 1 — missing token (replace lines 29-31):**

```python
if not health["token_file_exists"]:
    message = "[URGENT] Schwab token file missing — trading will fail. Run `python3 -m scripts.run_schwab login`."
    print(message)
    _send_notification(message)
    return 1
```

**Fix 2 — check warnings before returning healthy (after missing-token check, before the days check at line 34):**

```python
# Any warnings from check_token_health() indicate a problem
# (corrupt JSON, client failure, auth error, etc.)
warnings = health.get("warnings", [])
if warnings:
    days = health.get("refresh_token_days_remaining")
    is_urgent = (
        health.get("near_refresh_expiry", False)
        or (days is not None and days <= 1.0)
    )
    severity = "URGENT" if is_urgent else "WARNING"
    message = f"[{severity}] Schwab token issue: {' '.join(warnings)}"
    print(message)
    _send_notification(message)
    return 1
```

This preserves URGENT severity for <=1 day tokens even when the warning text is "Refresh token near expiry" (not "expired").

**Existing test update required:** `tests/scripts/test_check_schwab_token.py::test_near_expiry_sends_notification` (line 33) currently expects the old message format containing `"1.5 days"`. With the warnings-first branch, this test will hit the new path and the message changes to `"[URGENT] Schwab token issue: Refresh token near expiry."`. Update the assertion from `assert "1.5 days" in calls[0]` to `assert "[URGENT]" in calls[0]` and `assert "near expiry" in calls[0]`.

### 3D. Configure Telegram notifications

**Prerequisite:** `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are currently **unset** in `.env`. The monitoring job runs and exits 1 but sends no notification — making it useless.

User action: add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` to `.env`. Verify delivery with a test message.

## Phase 4: Token Refresh + Smoke Test

### 4A. Re-authenticate Schwab token

User must run: `python3 -m scripts.run_schwab login`

This is a browser-based OAuth flow — cannot be automated. Must be repeated every 7 days.

### 4B. Live smoke tests (after token refresh)

1. Run `python3 scripts/health_check.py` — confirm Schwab token shows PASS with no warnings
2. Call `list_accounts` via portfolio-mcp — confirm Schwab accounts appear with balances
3. Call `get_orders` for a Schwab account — confirm recent order history returns
4. Call `preview_trade` for a Schwab account with a small LIMIT order — confirm preview returns correct data (note: preview only does a local price estimate, not a broker-side validation)
5. **Do NOT place a real order until all above pass**

## Phase 5: Deferred (No Action Needed)

| Item | Why deferred |
|------|-------------|
| Commission model | Schwab is $0 for equities — hardcoded 0.0 is correct |
| SHORT selling | Blocked by design, routes to IBKR |
| Options/futures orders | `assetType=EQUITY` hardcoded — out of scope |
| Integration tests | Impractical for personal system — unit tests sufficient |
| MCP token health tool | `schwab_status` exists in finance-cli MCP already |
| TRADE_ACCOUNT_MAP mapped-ID fix | No Schwab accounts use mapped routing; fix if/when needed |

## Critical Files

| File | Change |
|------|--------|
| `brokerage/schwab/adapter.py:502-525` | Add non-2xx guard in `place_order()` (after `_call_with_backoff`, not inside it) |
| `brokerage/schwab/adapter.py:586-610` | Add non-2xx guard in `cancel_order()` |
| `providers/routing_config.py:248` | Add `"charles_schwab": "schwab"` to TRADE_ROUTING |
| `scripts/health_check.py:247-260` | Add `_check_schwab_token()` (checks warnings, not just days_remaining) |
| `scripts/check_schwab_token.py:29-50` | Fix missing-token + add warnings check before days check |
| `tests/scripts/test_check_schwab_token.py:33-52` | Update `test_near_expiry_sends_notification` assertions for new message format |
| `~/Library/LaunchAgents/com.henrychien.schwab-token-check.plist` | Twice-daily schedule |
| `tests/services/test_schwab_broker_adapter.py` | +10 tests (order types + error handling + partial fill) |
| `tests/brokerage/test_schwab_client.py` | +4 tests (token health) |
| `tests/scripts/test_health_check_schwab.py` | +4 tests (new file: PASS, FAIL missing, FAIL warning, WARN) |
| `tests/scripts/test_check_schwab_token.py` | +2 tests (missing token alert, warnings-with-days-remaining) |

## Verification

1. Run `pytest tests/services/test_schwab_broker_adapter.py tests/brokerage/test_schwab_client.py tests/scripts/test_health_check_schwab.py tests/scripts/test_check_schwab_token.py tests/scripts/test_health_check.py -v` — all 20 new + 21 existing tests pass (41 total)
2. After token refresh: run Phase 4B smoke tests
3. Run `python3 scripts/health_check.py` — confirm Schwab token shows PASS with no warnings

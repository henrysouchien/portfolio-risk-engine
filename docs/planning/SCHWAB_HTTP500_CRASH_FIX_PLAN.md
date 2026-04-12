# Fix: Schwab Provider Crash on HTTP 500

## Context

**Bug**: `providers/schwab_positions.py` crashes with `'NoneType' object has no attribute 'get'` when Schwab API returns HTTP 500 for an individual account.

**Root cause confirmed from logs** (`logs/app.log` lines 144-145):
- Schwab API returned HTTP 500 on account `25524252` (`get_account` endpoint) — 9 consecutive failures from 20:58–21:05 on 2026-04-11
- Self-resolved ~1 hour later (all 200 OK at 22:13)
- Auth was healthy the entire time (`accountNumbers` returned 200)
- This is a **transient Schwab server-side error**, not an auth issue

**Exact crash path** (verified with httpx simulation):
1. `client.get_account()` returns raw httpx Response with status 500 (schwab-py does NOT raise on error status codes)
2. `_response_payload(response)` calls `.json()` → returns `{"error": "server error"}` (a dict)
3. Line 91: `payload = {"error": "server error"}` — passes `isinstance(payload, dict)` check
4. Line 92: `payload.get("securitiesAccount")` → `None` (key doesn't exist in error body)
5. Lines 94-95: Safe — have `isinstance(account_payload, dict)` guards
6. **Line 119**: `account_payload.get("positions")` → **crash** — `None.get()`

**Impact**: One account's 500 crashes the entire provider loop. All 3 accounts' positions (17 total) are lost, even though 2 accounts would have returned successfully.

## Codex Review History

- **R1 — FAIL**: 401/403 silently swallowed, pseudo-code scoping, bare raise, missing isinstance guard, no logger, test gaps
- **R2 — FAIL**: Exception-based invalid_grant bare raise, 5xx silently returns None without log, message mismatch, 400+unsupported_token_type
- **R3 — FAIL**: Import path broken (`_RELOGIN_REQUIRED_MESSAGE` not in shim), auth guard too loose (string matching), double-wrap of already-normalized errors, missing `exc_info=True`

## Fix — v4 (4 changes in `providers/schwab_positions.py`)

### Change 1: Add logger + import relogin message

```python
import logging

from brokerage.schwab.client import _RELOGIN_REQUIRED_MESSAGE
from providers.schwab_client import get_account_hashes, get_schwab_client, is_invalid_grant_error

logger = logging.getLogger(__name__)
```

Import `_RELOGIN_REQUIRED_MESSAGE` directly from `brokerage.schwab.client` (the source module), not through the `providers.schwab_client` shim which doesn't export it. Existing imports from the shim stay unchanged.

### Change 2: Response status validation in `fetch_positions()`

After the inner try/except for `client.get_account()`, add a status check. This keeps `_response_payload()` a pure parser — no changes to it.

Auth errors are tagged with a sentinel class so the outer except can identify them by type, not string matching.

```python
class _SchwabAuthError(RuntimeError):
    """Sentinel for response-based auth failures."""
    pass


_AUTH_BODY_SIGNALS = ("invalid_grant", "invalid grant", "unsupported_token_type", "refresh_token_authentication_error")
```

Inside the per-account loop, after getting the response:

```python
status = getattr(response, "status_code", None)
if isinstance(status, int) and status >= 400:
    if status in (401, 403):
        raise _SchwabAuthError(_RELOGIN_REQUIRED_MESSAGE)
    # Check response body for auth-related error signals (e.g., 400 + invalid_grant)
    if status == 400:
        body_text = ""
        try:
            body_text = (getattr(response, "text", None) or str(_response_payload(response) or "")).lower()
        except Exception:
            pass
        if any(sig in body_text for sig in _AUTH_BODY_SIGNALS):
            raise _SchwabAuthError(_RELOGIN_REQUIRED_MESSAGE)
    raise ValueError(
        f"Schwab API returned HTTP {status} for account {account_number}"
    )
```

This mirrors all keywords from `is_invalid_grant_error()` (`brokerage/schwab/client.py:112-121`) — including the space-form `"invalid grant"` — but applied to response bodies instead of exception messages. Body text is extracted via `response.text` first (covers plain-text error bodies), falling back to stringified `_response_payload()` (covers JSON bodies). 401/403 are auth by status code alone. 400 is auth only if the body contains a known signal. All other 4xx/5xx are transient.

### Change 3: Per-account try/except with `continue` (IBKR pattern)

Full structure of the per-account loop:

```python
for account_number, account_hash in account_hashes.items():
    try:
        # Inner try: handle old schwab-py without fields kwarg
        try:
            response = client.get_account(account_hash, fields=["positions"])
        except TypeError:
            response = client.get_account(account_hash)

        # Status validation (Change 2)
        status = getattr(response, "status_code", None)
        if isinstance(status, int) and status >= 400:
            if status in (401, 403):
                raise _SchwabAuthError(_RELOGIN_REQUIRED_MESSAGE)
            if status == 400:
                body_text = ""
                try:
                    body_text = (getattr(response, "text", None) or str(_response_payload(response) or "")).lower()
                except Exception:
                    pass
                if any(sig in body_text for sig in _AUTH_BODY_SIGNALS):
                    raise _SchwabAuthError(_RELOGIN_REQUIRED_MESSAGE)
            raise ValueError(
                f"Schwab API returned HTTP {status} for account {account_number}"
            )

        payload = _response_payload(response) or {}
        account_payload = (
            payload.get("securitiesAccount") if isinstance(payload, dict) else {}
        )

        # Cash/margin balance row (existing lines 93-117, unchanged)
        account_type = account_payload.get("type") if isinstance(account_payload, dict) else None
        balances = account_payload.get("currentBalances") if isinstance(account_payload, dict) else {}
        bal = balances or {}
        if account_type == "MARGIN":
            cash_value = _to_float(bal.get("marginBalance"))
        else:
            cash_value = _to_float(bal.get("cashBalance")) or _to_float(bal.get("availableFunds"))
        if cash_value != 0.0:
            rows.append({...})  # existing cash row dict unchanged

        # Positions (Change 4: isinstance guard)
        positions = account_payload.get("positions") if isinstance(account_payload, dict) else []
        positions = positions or []
        for position in positions:
            if not isinstance(position, dict):
                continue
            # ... existing position parsing unchanged ...
            rows.append({...})

    except Exception as exc:
        # Auth errors propagate — entire provider is broken
        if isinstance(exc, _SchwabAuthError) or is_invalid_grant_error(exc):
            raise RuntimeError(_RELOGIN_REQUIRED_MESSAGE) from exc
        # Transient errors: log and skip this account
        logger.warning(
            "Schwab account %s fetch failed: %s", account_number, exc,
            exc_info=True,
        )
        continue
```

The outer except handler:
- **`_SchwabAuthError`**: Response-based 401/403 from Change 2. Identified by type, no string matching. Re-raised as plain `RuntimeError(_RELOGIN_REQUIRED_MESSAGE)` — the sentinel type is internal, callers see the same RuntimeError they expect.
- **`is_invalid_grant_error(exc)`**: Exception-based auth from schwab-py (e.g., `InvalidGrantError`). Wrapped in `RuntimeError(_RELOGIN_REQUIRED_MESSAGE)` with `from exc` preserving the original traceback.
- **Everything else**: Logged with `exc_info=True` for full traceback visibility, then `continue` to next account.

No double-wrapping: `_SchwabAuthError` is caught by type, not by message content. The `raise RuntimeError(...)` creates a single clean wrapper regardless of which auth path triggered it.

### Change 4: isinstance guard on line 119

```python
# Before:
positions = account_payload.get("positions") or []

# After:
positions = account_payload.get("positions") if isinstance(account_payload, dict) else []
positions = positions or []
```

Consistent with lines 94-95. Defense-in-depth for malformed 200 responses where `securitiesAccount` is null.

### NOT changing

- **`_response_payload()`** — stays a pure payload normalizer. No status code logic.
- **`brokerage/schwab/client.py`** — not touched.
- **`providers/schwab_client.py`** (shim) — not touched. The `_RELOGIN_REQUIRED_MESSAGE` import is direct from source.
- **`position_service.py`** — already catches provider exceptions correctly.

## Files Modified

| File | Change |
|------|--------|
| `providers/schwab_positions.py` | Add `_SchwabAuthError` sentinel, add logger, import `_RELOGIN_REQUIRED_MESSAGE` from source module, response status validation after API call, widen try/except to full per-account block with `exc_info=True`, isinstance guard at line 119 |

## Verification

1. **Unit test — partial 500**: Mock `client.get_account()` to return httpx.Response(500) for one account and valid 200 for another. Assert provider returns positions from the healthy account only.
2. **Unit test — all 500**: Mock all accounts returning 500. Assert provider returns empty DataFrame.
3. **Unit test — invalid_grant exception**: Mock `client.get_account()` raising an exception where `is_invalid_grant_error` returns True. Assert it raises RuntimeError with `_RELOGIN_REQUIRED_MESSAGE`.
4. **Unit test — HTTP 401 response**: Mock httpx.Response(401). Assert it raises RuntimeError with `_RELOGIN_REQUIRED_MESSAGE`.
5. **Unit test — HTTP 403 response**: Same as above for 403.
6. **Unit test — TypeError fallback**: Mock `client.get_account(hash, fields=...)` raising TypeError, then `client.get_account(hash)` returning valid 200 data. Assert positions are returned.
7. **Unit test — malformed 200 (null securitiesAccount)**: Mock 200 with body `{"securitiesAccount": null}`. Assert provider skips that account gracefully.
8. **Unit test — HTTP 400 with auth JSON body**: Mock httpx.Response(400, json={"error": "invalid_grant"}). Assert it raises RuntimeError with `_RELOGIN_REQUIRED_MESSAGE`.
9. **Unit test — HTTP 400 with space-form auth body**: Mock httpx.Response(400, text="invalid grant"). Assert it raises RuntimeError (tests `response.text` path and space-form signal).
10. **Unit test — HTTP 400 non-auth body**: Mock httpx.Response(400, json={"error": "bad request"}). Assert it skips the account (warning logged, not auth error).
11. **Live check**: `SchwabPositionProvider().fetch_positions('henry.souchien@gmail.com')` still returns 17 rows.

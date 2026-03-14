# Plan: Brokerage Connection Friction Reduction

**Status:** PLANNED
**Goal:** Fix provider availability lies, add proactive Schwab token warnings, surface actionable re-auth errors, and cross-check IBKR dual-provider setup.

---

## Context

The `ONBOARDING_FRICTION_AUDIT.md` § Provider Friction Inventory identified four gaps that cause user confusion or silent failures when brokerage connections are misconfigured, expired, or incomplete. These are all small, independent fixes — no architectural changes.

---

## Step 1: Fix PROVIDER_CREDENTIALS Gaps + Provider Registration

### Problem

Two related gaps let uncredentialed Plaid/SnapTrade providers get selected at runtime:

**Gap A — `PROVIDER_CREDENTIALS` lies:** `settings.py:420-427` has empty lists for Plaid and SnapTrade. `is_provider_available()` in `providers/routing.py:276-279` iterates `required_env_vars` — empty list means zero checks, always returns True.

```python
# CURRENT (broken):
PROVIDER_CREDENTIALS: dict[str, list[str]] = {
    "plaid": [],          # ← lies: says "no credentials needed"
    "snaptrade": [],      # ← lies: says "no credentials needed"
    "ibkr": [],
    "ibkr_flex": ["IBKR_FLEX_TOKEN", "IBKR_FLEX_QUERY_ID"],
    "schwab": ["SCHWAB_APP_KEY", "SCHWAB_APP_SECRET"],
}
```

**Gap B — Registration uses `is_provider_enabled` only:** `PositionService.__init__` (`services/position_service.py:115-118`) registers Plaid/SnapTrade when `is_provider_enabled()` is True (which it is by default), without checking `is_provider_available()`. Same pattern in `data_fetcher._build_default_transaction_registry` (`trading_analysis/data_fetcher.py:722-725`). Schwab and IBKR already check both.

```python
# CURRENT — position_service.py:115-118:
if is_provider_enabled("plaid"):
    position_providers["plaid"] = PlaidPositionProvider()  # no availability check!
if is_provider_enabled("snaptrade"):
    position_providers["snaptrade"] = SnapTradePositionProvider()  # no availability check!
# vs Schwab (correct pattern):
if is_provider_enabled("schwab"):
    if is_provider_available("schwab"):  # ← checks credentials + token file
        position_providers["schwab"] = SchwabPositionProvider()
```

**Gap C — `get_required_providers()` fail-open uses `is_provider_enabled`:** The fail-open path at `routing.py:342-346` falls back to enabled providers without checking availability, so even with Gap A fixed, uncredentialed providers can still be selected as a last resort.

**Gap D — `SNAPTRADE_KEY` false positive in detection:** `_get_configured_providers()` in `mcp_server.py:41` and `health_check.py:37` include `SNAPTRADE_KEY` in any-of detection. This env var is not part of the actual brokerage config contract (`brokerage/config.py:18-19` uses `SNAPTRADE_CLIENT_ID`/`SNAPTRADE_CONSUMER_KEY`). Setting only `SNAPTRADE_KEY` makes startup claim SnapTrade is "configured" when the real required vars are absent.

### Fix

**1a. Fill `PROVIDER_CREDENTIALS`** (`settings.py`):

```python
# NEW:
PROVIDER_CREDENTIALS: dict[str, list[str]] = {
    "plaid": ["PLAID_CLIENT_ID", "PLAID_SECRET"],
    "snaptrade": ["SNAPTRADE_CLIENT_ID", "SNAPTRADE_CONSUMER_KEY"],
    "ibkr": [],  # intentional: availability checked via live Gateway probe
    "ibkr_flex": ["IBKR_FLEX_TOKEN", "IBKR_FLEX_QUERY_ID"],
    "schwab": ["SCHWAB_APP_KEY", "SCHWAB_APP_SECRET"],
}
```

Env var names sourced from `brokerage/config.py:18-23` (the actual consumer):
- Plaid: `PLAID_CLIENT_ID`, `PLAID_SECRET`
- SnapTrade: `SNAPTRADE_CLIENT_ID`, `SNAPTRADE_CONSUMER_KEY`

**1b. Guard Plaid/SnapTrade registration on availability** (`services/position_service.py`, `trading_analysis/data_fetcher.py`):

Apply the same `is_provider_available()` gate used by Schwab/IBKR:

```python
# position_service.py — NEW:
if is_provider_enabled("plaid"):
    if is_provider_available("plaid"):
        position_providers["plaid"] = PlaidPositionProvider()
    else:
        portfolio_logger.info(
            "Plaid provider enabled but credentials missing; skipping registration."
        )
if is_provider_enabled("snaptrade"):
    if is_provider_available("snaptrade"):
        position_providers["snaptrade"] = SnapTradePositionProvider()
    else:
        portfolio_logger.info(
            "SnapTrade provider enabled but credentials missing; skipping registration."
        )
```

Same pattern in `data_fetcher._build_default_transaction_registry`:

```python
# data_fetcher.py — NEW:
if is_provider_enabled("snaptrade") and is_provider_available("snaptrade"):
    registry.register_transaction_provider(SnapTradeTransactionProvider())
if is_provider_enabled("plaid") and is_provider_available("plaid"):
    registry.register_transaction_provider(PlaidTransactionProvider())
```

**1c. Fix `get_required_providers()` fail-open** (`providers/routing.py:342-346`):

Change the fail-open from `is_provider_enabled` to `is_provider_available`:

```python
# OLD (routing.py:342-346):
return {
    provider
    for provider in ALL_PROVIDERS
    if provider in capable and is_provider_enabled(provider)
}

# NEW:
return {
    provider
    for provider in ALL_PROVIDERS
    if provider in capable and is_provider_available(provider)
}
```

Also apply the same fix to the no-routing fallback at `routing.py:324-325`:

```python
# OLD:
if not routing:
    return {provider for provider in ALL_PROVIDERS if provider in capable and is_provider_enabled(provider)}

# NEW:
if not routing:
    return {provider for provider in ALL_PROVIDERS if provider in capable and is_provider_available(provider)}
```

**1d. Remove `SNAPTRADE_KEY` from detection lists** (`mcp_server.py`, `health_check.py`):

```python
# OLD — mcp_server.py:41:
("SnapTrade", ("SNAPTRADE_KEY", "SNAPTRADE_CLIENT_ID", "SNAPTRADE_CONSUMER_KEY")),

# NEW:
("SnapTrade", ("SNAPTRADE_CLIENT_ID", "SNAPTRADE_CONSUMER_KEY")),
```

Same change in `health_check.py:37`.

### Files Modified

| File | Change |
|------|--------|
| `settings.py` | Fill `PROVIDER_CREDENTIALS` for plaid/snaptrade, add comment on ibkr |
| `services/position_service.py` | Add `is_provider_available()` gate for plaid/snaptrade registration |
| `trading_analysis/data_fetcher.py` | Add `is_provider_available()` gate for plaid/snaptrade registration |
| `providers/routing.py` | Fix fail-open paths to use `is_provider_available` |
| `mcp_server.py` | Remove `SNAPTRADE_KEY` from detection list |
| `scripts/health_check.py` | Remove `SNAPTRADE_KEY` from detection list |

### Tests

**New tests** — add to `tests/providers/test_routing.py`:

1. **`test_plaid_unavailable_without_credentials`** — Clear `PLAID_CLIENT_ID`/`PLAID_SECRET` via `monkeypatch.delenv`, assert `is_provider_available("plaid")` returns False.
2. **`test_plaid_available_with_credentials`** — Set both env vars via `monkeypatch.setenv`, assert returns True.
3. **`test_snaptrade_unavailable_without_credentials`** — Clear `SNAPTRADE_CLIENT_ID`/`SNAPTRADE_CONSUMER_KEY`, assert returns False.
4. **`test_snaptrade_available_with_credentials`** — Set both env vars, assert returns True.
5. **`test_get_required_providers_failopen_respects_availability`** — Set up a scenario where plaid is enabled but not available (no credentials), verify `get_required_providers("positions")` excludes plaid from the fail-open set.

Note: Tests must use `monkeypatch.setenv`/`delenv` for credential vars. The `PROVIDER_CREDENTIALS` dict is read at call time by `is_provider_available()` (lazy import from `settings`), so no dict monkeypatching is needed after implementation.

### Impacted Existing Tests

The availability/registration changes will flip expectations in several existing tests. These must be updated:

| Test | File | Current Expectation | New Expectation |
|------|------|-------------------|-----------------|
| `test_get_required_providers_includes_defaults_and_canonical` | `test_routing.py:103` | Returns `{"plaid", "snaptrade", "ibkr_flex", "schwab"}` | Must set `PLAID_CLIENT_ID`/`PLAID_SECRET` + `SNAPTRADE_CLIENT_ID`/`SNAPTRADE_CONSUMER_KEY` env vars (or mock `is_provider_available`) for plaid/snaptrade to appear in result |
| `test_get_required_providers_without_routing_returns_all_enabled` | `test_routing.py:131` | Sets `ENABLED_PROVIDERS=plaid,schwab`, expects `{"plaid", "schwab"}` | Now uses `is_provider_available` — must also set credential env vars for plaid, or mock availability |
| `test_position_service_registers_only_enabled_providers` | `test_provider_switching.py:177` | Sets `ENABLED_PROVIDERS=snaptrade`, expects `{"snaptrade", "csv"}` | Must also set `SNAPTRADE_CLIENT_ID`/`SNAPTRADE_CONSUMER_KEY` for snaptrade to register |
| `test_default_transaction_registry_registers_only_enabled_providers` | `test_provider_switching.py:206` | Sets `ENABLED_PROVIDERS=plaid,schwab`, expects `{"plaid", "schwab"}` | Must also set `PLAID_CLIENT_ID`/`PLAID_SECRET` for plaid to register |
| `test_get_required_providers_validation_invalid_defaults_falls_back_all_enabled` | `test_routing.py:108` | Sets `ENABLED_PROVIDERS=plaid,snaptrade,ibkr_flex`, expects `{"plaid", "snaptrade", "ibkr_flex"}` | Fail-open now uses `is_provider_available` — must set `PLAID_CLIENT_ID`/`PLAID_SECRET` + `SNAPTRADE_CLIENT_ID`/`SNAPTRADE_CONSUMER_KEY` env vars or mock availability. Note: the autouse fixture (`test_routing.py:23`) does NOT set Plaid/SnapTrade credentials, so this test AND tests #103/#131 need credential env vars added. |
| `test_resolve_providers_for_institution_unknown` | `test_routing.py:159` | Expects `["snaptrade", "plaid"]` for unknown brokerage | Plaid/SnapTrade only returned when available — must set credential env vars in test or in autouse fixture |
| `test_position_service_skips_enabled_but_unavailable_schwab` | `test_provider_switching.py:190` | Sets `ENABLED_PROVIDERS=snaptrade,schwab`, expects `{"snaptrade", "csv"}` | SnapTrade now also requires availability — must set `SNAPTRADE_CLIENT_ID`/`SNAPTRADE_CONSUMER_KEY` for snaptrade to register |
| `test_validate_environment_detects_configured_providers` | `test_startup_validation.py:102` | Sets `SNAPTRADE_KEY=...`, expects "SnapTrade" in output | Must set `SNAPTRADE_CLIENT_ID` instead (since `SNAPTRADE_KEY` removed from detection) |

### Risk

This changes routing behavior: providers without credentials will no longer be registered or selected. This is the **desired** behavior — it prevents routing to providers that will fail at runtime. The fail-open path is now gated on availability, so it won't select uncredentialed providers as a last resort either.

---

## Step 2: IBKR Dual-Provider Onboarding Awareness

### Problem

Full IBKR setup needs **both**:
- `IBKR_ENABLED=true` (Gateway) — live positions, market data, trading
- `IBKR_FLEX_ENABLED=true` (Flex) — historical transactions, realized performance, tax harvest

These are independent boolean toggles (`routing.py:259-262`) that are never cross-referenced. A user who sets up Gateway but not Flex will have live positions but no trade history — and no indication that they're missing half the IBKR integration.

### Fix

Add cross-check to `_validate_environment()` in `mcp_server.py` after provider detection (line ~87):

```python
# IBKR dual-provider cross-check
ibkr_gateway = (os.getenv("IBKR_ENABLED", "false") or "false").lower() == "true"
ibkr_flex = (os.getenv("IBKR_FLEX_ENABLED", "false") or "false").lower() == "true"
if ibkr_gateway and not ibkr_flex:
    print(
        "Warning: IBKR Gateway enabled but Flex is not. "
        "Set IBKR_FLEX_ENABLED=true with IBKR_FLEX_TOKEN/IBKR_FLEX_QUERY_ID "
        "for trade history, realized performance, and tax harvest.",
        file=out,
    )
elif ibkr_flex and not ibkr_gateway:
    print(
        "Info: IBKR Flex enabled but Gateway is not. "
        "Set IBKR_ENABLED=true for live positions, market data, and trading.",
        file=out,
    )
```

Add matching check to `scripts/health_check.py` as a new `_check_ibkr_dual_provider()` function returning a `CheckResult` with status `WARN`. Wire into `run_health_check()` results list.

### Files Modified

| File | Change |
|------|--------|
| `mcp_server.py` | Add IBKR cross-check in `_validate_environment()` |
| `scripts/health_check.py` | Add `_check_ibkr_dual_provider()`, wire into `run_health_check()` |

### Tests

Add to `tests/test_startup_validation.py`. All new tests must clear `IBKR_ENABLED` and `IBKR_FLEX_ENABLED` via `monkeypatch.delenv(..., raising=False)` to prevent ambient env leakage. Add both env vars to the existing `ENV_VARS_UNDER_TEST` list and `_clear_validation_env()` helper.

6. **`test_ibkr_gateway_without_flex_warns`** — Set `IBKR_ENABLED=true`, clear `IBKR_FLEX_ENABLED`, assert "IBKR Gateway enabled but Flex is not" in stderr.
7. **`test_ibkr_flex_without_gateway_warns`** — Set `IBKR_FLEX_ENABLED=true`, clear `IBKR_ENABLED`, assert "IBKR Flex enabled but Gateway is not" in stderr.
8. **`test_ibkr_both_enabled_no_warning`** — Set both to true, assert neither warning appears in stderr.

Add to `tests/scripts/test_health_check.py` (new file or extend existing):

9. **`test_health_check_ibkr_dual_provider_warn`** — `IBKR_ENABLED=true` only → `_check_ibkr_dual_provider()` returns `CheckResult` with status `WARN`.
10. **`test_health_check_ibkr_both_pass`** — Both enabled → returns `PASS` (or is omitted from results).

---

## Step 3: Re-auth UX — Graceful Error Messages

### Problem

Auth errors are swallowed at multiple layers before reaching `@handle_mcp_errors`:

1. **`PositionService.get_all_positions()`** (`position_service.py:324-327`) catches per-provider exceptions and converts them to `provider_errors` metadata — the auth error becomes `fetch_error: "..."` in a dict, not a raised exception.
2. **`data_fetcher._fetch_provider()`** (`data_fetcher.py:872-875`) catches exceptions and converts them to `_provider_error_metadata()` — auth errors become `fetch_error` strings in `FetchMetadata`.
3. **`mcp_tools/positions.py:524-529`** has its own `except Exception` that returns `{"status": "error", "error": str(e)}` without `@handle_mcp_errors`.

So `_classify_auth_error()` in `@handle_mcp_errors` alone won't catch the important real-world auth failures — they're already caught and collapsed.

### Fix

A two-layer approach:

**3a. Add `_classify_auth_error()` to `mcp_tools/common.py`** — catches auth errors that do bubble up to `@handle_mcp_errors` (e.g., from `run_optimization`, `get_risk_analysis`, etc. that call `_load_portfolio_for_analysis()` which raises on position fetch failure):

```python
def _classify_auth_error(exc: Exception) -> str | None:
    """Return an actionable re-auth message if exc is a brokerage auth error."""
    error_str = str(exc).lower()
    error_class = type(exc).__name__.lower()

    # Schwab: invalid_grant / expired refresh token
    # Matches all patterns from brokerage.schwab.client.is_invalid_grant_error()
    if (
        "invalid_grant" in error_str
        or "invalid grant" in error_str
        or "invalidgranterror" in error_class
        or "refresh_token_authentication_error" in error_str
        or "unsupported_token_type" in error_str
    ):
        return (
            "Schwab refresh token expired. Re-authenticate: "
            "`python3 -m scripts.run_schwab login`"
        )

    # Schwab: already-converted RuntimeError from _raise_relogin_required
    # Production strings: "Schwab refresh token expired. Run ..." (schwab_positions.py:87,
    # schwab_transactions.py:187) or "Schwab refresh token appears expired. Re-authenticate..."
    # (schwab/client.py:113)
    if "schwab" in error_str and "refresh token" in error_str and ("expired" in error_str or "re-authenticate" in error_str):
        return str(exc)

    # Plaid: ITEM_LOGIN_REQUIRED
    if "item_login_required" in error_str:
        return (
            "Plaid connection requires re-authentication. "
            "Run `python3 -m scripts.plaid_reauth --reauth` to generate a re-link URL."
        )

    # SnapTrade: ApiException with 401/403
    # SDK raises snaptrade_client.ApiException — check .status attribute
    status = getattr(exc, "status", getattr(exc, "status_code", None))
    if status in (401, 403) and "apiexception" in error_class:
        return (
            f"Brokerage authentication failed (HTTP {status}). "
            "Check your provider connection status and credentials."
        )

    return None
```

Key fixes from Codex review:
- Plaid command corrected to `--reauth` flag (required by `scripts/plaid_reauth.py:205`)
- SnapTrade matching uses `"apiexception" in error_class` (the actual SDK type from `snaptrade_client.ApiException`) instead of looking for "snaptrade" in class name
- Schwab patterns expanded to match all variants from `is_invalid_grant_error()` (`brokerage/schwab/client.py:99-108`)

Wire into `handle_mcp_errors`:

```python
# In the except block, before the generic return:
auth_msg = _classify_auth_error(e)
if auth_msg:
    return {"status": "error", "error": auth_msg, "auth_required": True}
return {"status": "error", "error": str(e)}
```

**3b. Surface auth errors in `PositionService` provider metadata** — Add an `auth_errors` field to the response when provider errors look like auth failures. In `mcp_tools/positions.py`, after `get_all_positions()` returns, check `result._provider_errors` (if exposed) and surface any auth-shaped errors as warnings in the response:

```python
# In mcp_tools/positions.py, in the get_positions() try block, after getting result:
auth_warnings = []
for prov_name, error_str in getattr(result, '_provider_errors', {}).items():
    auth_msg = _classify_auth_error_from_string(error_str, provider_name=prov_name)
    if auth_msg:
        auth_warnings.append({"provider": prov_name, "message": auth_msg})

# Include in response if any found:
if auth_warnings:
    response["auth_warnings"] = auth_warnings
```

This requires exposing `provider_errors` on `PositionResult`. Currently `PositionService` stores errors in local `provider_errors` dict (`position_service.py:327`) but doesn't expose them on the result object. Add a `provider_errors: dict[str, str]` attribute to `PositionResult` and populate it.

**3b-ii. Classify auth errors in `get_positions()` catch block** — The broad `except Exception` at `mcp_tools/positions.py:524-529` returns `{"status": "error", "error": str(e)}` for exceptions that bubble up from `PositionService` (e.g., from `refresh_provider_positions()` at `position_service.py:1195`). Apply `_classify_auth_error()` here too:

```python
# mcp_tools/positions.py:524-529 — NEW:
    except Exception as e:
        auth_msg = _classify_auth_error(e)
        if auth_msg:
            return {
                "status": "error",
                "error": auth_msg,
                "auth_required": True,
                "user_email": user,
            }
        return {
            "status": "error",
            "error": str(e),
            "user_email": user,
        }
```

This ensures auth errors that escape `PositionService`'s per-provider catch (e.g., `refresh_provider_positions` raising directly) get actionable messages instead of raw tracebacks.

**3c. Surface auth errors in transaction fetch metadata** — The `fetch_error` field in `FetchMetadata` already contains the error string. Auth warnings should be surfaced in the response **regardless** of whether there's data — a partial success where one provider auth-fails but another returns data should still warn the user.

Add a helper to extract auth warnings from fetch metadata, then call it in two places:

```python
# mcp_tools/trading_analysis.py — new helper:
def _extract_auth_warnings(fetch_result) -> list[dict]:
    """Extract auth warnings from fetch metadata."""
    from mcp_tools.common import _classify_auth_error_from_string
    auth_warnings = []
    fetch_metadata = getattr(fetch_result, "fetch_metadata", [])
    for meta in fetch_metadata:
        fetch_error = meta.get("fetch_error") if isinstance(meta, dict) else None
        if fetch_error:
            provider = meta.get("provider", "unknown")
            auth_msg = _classify_auth_error_from_string(fetch_error, provider_name=provider)
            if auth_msg:
                auth_warnings.append({"provider": provider, "message": auth_msg})
    return auth_warnings
```

Use in two places:

```python
# 1. At total_txns == 0 (line 170) — enrich the error response:
if total_txns == 0:
    error_response = {
        "status": "error",
        "error": f"No transaction data found for source '{source}'",
    }
    auth_warnings = _extract_auth_warnings(fetch_result)
    if auth_warnings:
        error_response["auth_warnings"] = auth_warnings
        error_response["error"] += (
            " This may be due to expired authentication — see auth_warnings."
        )
    return error_response

# 2. At success path (before final return) — inject warnings for partial failures:
auth_warnings = _extract_auth_warnings(fetch_result)
if auth_warnings:
    response["auth_warnings"] = auth_warnings
```

This covers both zero-data (all providers failed) and partial-success (one provider auth-failed, others returned data) scenarios.

The `_classify_auth_error_from_string()` helper is a string-only variant of `_classify_auth_error()` for classifying error messages that have already been serialized to `str`. It must match both raw SDK patterns AND the already-converted RuntimeError strings from `_raise_relogin_required()` (which produce `"Schwab refresh token expired. Run ..."` — seen in `providers/schwab_positions.py:87` and `providers/schwab_transactions.py:187`).

Because stringified exceptions lose their class name, SnapTrade's `str(ApiException(status=401))` renders as `"(401)\nReason: Unauthorized\n"` — no "snaptrade" anywhere. The string classifier can't identify the provider from the error alone. Instead, the caller passes the `provider_name` from metadata so the classifier can apply provider-aware patterns.

Added to `mcp_tools/common.py`:

```python
def _classify_auth_error_from_string(
    error_str: str,
    provider_name: str | None = None,
) -> str | None:
    """Classify an already-serialized error string for auth failures.

    Args:
        error_str: The stringified exception message.
        provider_name: Optional provider name from fetch metadata (e.g., "schwab",
            "snaptrade", "plaid"). Helps identify provider when the error string
            doesn't contain provider-specific markers.
    """
    lower = error_str.lower()
    provider = (provider_name or "").lower()

    # Schwab: raw SDK patterns
    if (
        "invalid_grant" in lower
        or "invalid grant" in lower
        or "refresh_token_authentication_error" in lower
        or "unsupported_token_type" in lower
    ):
        return (
            "Schwab refresh token expired. Re-authenticate: "
            "`python3 -m scripts.run_schwab login`"
        )
    # Schwab: already-converted RuntimeError from _raise_relogin_required
    if "schwab" in lower and "refresh token" in lower and "expired" in lower:
        return error_str  # pass through the already-clear message

    # Plaid: ITEM_LOGIN_REQUIRED
    if "item_login_required" in lower:
        return (
            "Plaid connection requires re-authentication. "
            "Run `python3 -m scripts.plaid_reauth --reauth` to generate a re-link URL."
        )

    # SnapTrade: str(ApiException(status=401)) renders as "(401)\nReason: Unauthorized\n"
    # No "snaptrade" in the string — use provider_name from metadata to identify.
    if provider == "snaptrade" and ("(401)" in lower or "(403)" in lower):
        return (
            "SnapTrade authentication failed. "
            "Check connection status in your SnapTrade dashboard."
        )

    return None
```

### Files Modified

| File | Change |
|------|--------|
| `mcp_tools/common.py` | Add `_classify_auth_error()`, `_classify_auth_error_from_string()`, wire into `handle_mcp_errors` |
| `mcp_tools/positions.py` | Surface auth warnings from provider errors in response |
| `mcp_tools/trading_analysis.py` | Surface auth warnings when `total_txns == 0` and fetch metadata has auth errors |
| `core/result_objects/positions.py` | Add `provider_errors` attribute to `PositionResult` |
| `services/position_service.py` | Expose `provider_errors` dict on result object |

### Tests

Add `tests/mcp_tools/test_common_auth.py`:

11. **`test_classify_schwab_invalid_grant_underscore`** — Exception with "invalid_grant" in message → returns Schwab re-auth string.
12. **`test_classify_schwab_invalid_grant_space`** — Exception with "invalid grant" (space, not underscore) in message → also returns Schwab re-auth string. Matches `brokerage/schwab/client.py:105`.
13. **`test_classify_schwab_relogin_passthrough`** — RuntimeError matching `_raise_relogin_required` text → passes through.
14. **`test_classify_schwab_refresh_token_error`** — Exception with "refresh_token_authentication_error" → returns Schwab re-auth string.
15. **`test_classify_plaid_item_login_required`** — Exception with "ITEM_LOGIN_REQUIRED" → returns Plaid string containing `--reauth`.
16. **`test_classify_apiexception_401`** — Exception with class name `ApiException` and `status=401` → returns generic auth failure string.
17. **`test_classify_non_auth_returns_none`** — Generic `ValueError("bad input")` → returns None.
18. **`test_handle_mcp_errors_auth_flag`** — Decorated function raises Schwab invalid_grant → response has `auth_required: True`.
19. **`test_position_result_surfaces_auth_warnings`** — PositionResult with provider_errors containing a Schwab auth string → `get_positions()` response includes `auth_warnings`.
20. **`test_trading_analysis_surfaces_auth_warnings_on_zero_txns`** — Mock `fetch_transactions_for_source` to return empty payload with `fetch_metadata` containing `fetch_error: "invalid_grant"` → response includes `auth_warnings` and error message mentions expired authentication. Update existing `test_get_trading_analysis_no_transactions_error` (`test_trading_analysis.py:173`) to also return `fetch_metadata` in the mock (currently returns a raw dict, needs to return a `FetchResult` with metadata).
21. **`test_trading_analysis_partial_success_surfaces_auth_warnings`** — Mock one provider returning data and another returning a `fetch_error: "(401)\nReason: Unauthorized\n"` with `provider: "snaptrade"` → response has `status: "success"` AND `auth_warnings` with SnapTrade auth failure.
22. **`test_classify_auth_error_from_string_snaptrade_401`** — `_classify_auth_error_from_string("(401)\nReason: Unauthorized\n", provider_name="snaptrade")` → returns SnapTrade auth message.
23. **`test_classify_auth_error_from_string_snaptrade_without_provider_name`** — `_classify_auth_error_from_string("(401)\nReason: Unauthorized\n")` (no provider_name) → returns None (can't identify provider from string alone).

---

## Step 4: Proactive Schwab Token Expiry Notification

### Problem

`check_token_health()` in `brokerage/schwab/client.py:251-322` computes `refresh_token_days_remaining` and warns at <=1 day, but it's on-demand only. Nobody calls it proactively. The 7-day Schwab refresh token silently expires, and the user discovers it only when a tool fails.

### Fix

Create `scripts/check_schwab_token.py`:

```python
#!/usr/bin/env python3
"""Check Schwab token health and notify if near expiry."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

from brokerage.schwab.client import check_token_health

WARN_DAYS = 2.0  # notify when <= 2 days remaining


def main() -> int:
    if not (os.getenv("SCHWAB_ENABLED", "false") or "false").lower() == "true":
        return 0  # Schwab not enabled, nothing to check

    health = check_token_health()

    if not health["token_file_exists"]:
        print("Schwab token file missing — skipping (not configured)")
        return 0

    days = health.get("refresh_token_days_remaining")
    if days is not None and days > WARN_DAYS and not health["near_refresh_expiry"]:
        print(f"Schwab token healthy: {days:.1f} days remaining")
        return 0

    # Build notification
    severity = "URGENT" if (days is not None and days <= 1.0) else "WARNING"
    warnings = health.get("warnings", [])
    msg = f"[{severity}] Schwab token "
    if days is not None:
        msg += f"expires in {days:.1f} days. "
    if warnings:
        msg += " ".join(warnings)
    else:
        msg += "Re-run `python3 -m scripts.run_schwab login` to refresh."

    print(msg)
    _send_notification(msg)
    return 1


def _send_notification(message: str) -> None:
    """Send via Telegram bot API (no MCP dependency for cron)."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not bot_token or not chat_id:
        return  # no notification channel configured

    import urllib.request
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = json.dumps({"chat_id": chat_id, "text": message}).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as exc:
        print(f"Notification send failed: {exc}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
```

After the script is created and tested, register a daily launchd schedule via `scheduler-mcp`:
- Name: `com.risk-module.schwab-token-check`
- Schedule: daily at 9 AM local
- Command: `python3 <project_root>/scripts/check_schwab_token.py`

### Files Modified

| File | Change |
|------|--------|
| `scripts/check_schwab_token.py` | **New file** — token health check + notification |

### Tests

Add `tests/scripts/test_check_schwab_token.py`:

19. **`test_skips_when_schwab_disabled`** — `SCHWAB_ENABLED` not set → returns 0, no notification.
20. **`test_healthy_token_no_notification`** — Mock `check_token_health()` returning 5.0 days remaining → returns 0.
21. **`test_near_expiry_sends_notification`** — Mock returning 1.5 days → returns 1, calls `_send_notification`.
22. **`test_notification_graceful_without_telegram`** — No `TELEGRAM_BOT_TOKEN` set → `_send_notification` is a no-op.

---

## Summary

| Step | Scope | Files | New Tests | Updated Tests |
|------|-------|-------|-----------|---------------|
| 1. Credential gaps + registration | 6 files, ~30 lines | `settings.py`, `position_service.py`, `data_fetcher.py`, `routing.py`, `mcp_server.py`, `health_check.py` | 5 | 8 existing tests updated |
| 2. IBKR dual-provider | 2 files, ~20 lines | `mcp_server.py`, `health_check.py` | 5 | 0 |
| 3. Re-auth UX | 5 files, ~100 lines | `common.py`, `positions.py`, `trading_analysis.py`, `result_objects/positions.py`, `position_service.py` | 13 | 1 existing test updated |
| 4. Token notification | 1 new file, ~60 lines | `scripts/check_schwab_token.py` | 4 | 0 |
| **Total** | **11 files, ~220 lines** | | **27 new + 9 updated** |

### Verification

After implementation, verify end-to-end:

```bash
# Step 1: confirm Plaid/SnapTrade unavailable without credentials
python3 -c "
from providers.routing import is_provider_available
print('plaid available:', is_provider_available('plaid'))
print('snaptrade available:', is_provider_available('snaptrade'))
"

# Step 1: confirm fail-open excludes unavailable providers
python3 -c "
from providers.routing import get_required_providers
print('required positions:', get_required_providers('positions'))
"

# Step 2: confirm IBKR cross-check warnings
IBKR_ENABLED=true python3 -c "import mcp_server" 2>&1 | grep -i "ibkr"

# Step 3: confirm auth error classification
python3 -c "
from mcp_tools.common import _classify_auth_error
print(_classify_auth_error(RuntimeError('invalid_grant error')))
"

# Step 4: confirm token check script
python3 scripts/check_schwab_token.py

# Full test suite
python3 -m pytest tests/providers/test_routing.py tests/test_startup_validation.py tests/mcp_tools/test_common_auth.py tests/scripts/test_check_schwab_token.py -v
```

# Fix: Research Content Proxy 401 — Missing Session Token Exchange

## Context

The research view returns 401 because `research_content.py` sends the raw `GATEWAY_API_KEY` as a bearer token directly to the upstream gateway. The gateway expects a **session token** obtained via `/api/chat/init`, not a raw API key — the same flow the chat proxy already uses via `GatewaySessionManager`.

**Chat proxy (works):** API key → `GatewaySessionManager.get_token()` → `POST /api/chat/init` → session token → `Authorization: Bearer {session_token}`

**Research proxy (broken):** API key → `Authorization: Bearer {raw_api_key}` → gateway rejects → 401

The 401 then gets passed through to the frontend as-is (only >=500 is remapped to 502), making it look like a session auth failure.

## Fix

Wire the **existing** `GatewaySessionManager` instance into the research content proxy, classify upstream errors the same way the chat proxy does, and handle retries correctly.

### 1. Share the app-level session manager (not a new instance)

`routes/gateway_proxy.py:79` creates `gateway_proxy_router` via `create_gateway_router()`, which internally creates a `GatewaySessionManager`. The session manager is accessible at `gateway_proxy_router._session_manager` (line 85-86).

**In `routes/research_content.py`**, import the existing session manager:

```python
from routes.gateway_proxy import gateway_proxy_router

_session_manager = gateway_proxy_router._session_manager
```

This shares session tokens between chat and research — a user who already has an active chat session reuses that token for research requests. No duplicate `/api/chat/init` calls.

### 2. Replace raw API key with session token in `_forward_request()`

Current `_build_upstream_headers()` (line 66) calls `_resolve_gateway_api_key()` directly. Change it to accept a pre-resolved `session_token` parameter instead:

```python
def _build_upstream_headers(request: Request, user_id: str, session_token: str, request_id: str) -> dict[str, str]:
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in _REQUEST_HEADER_BLOCKLIST
    }
    headers["Authorization"] = f"Bearer {session_token}"
    headers[_RESEARCH_USER_HEADER] = user_id
    headers["X-Request-ID"] = request_id
    return headers
```

Note: `request_id` is now a parameter (generated once in the caller) instead of generated inside the helper. This ensures the same request ID is used across retries.

### 3. Add classified retry logic in `_forward_request()`

Import and reuse `_classify_upstream_error` from `app_platform.gateway.proxy` — the exact same classifier the chat proxy uses. This ensures any future changes to error classification are shared.

The classifier semantics (`proxy.py:150-167`):
- If body has `error` in `_KNOWN_UPSTREAM_ERRORS` → returns that error code (e.g. `auth_expired`, `cross_user_reuse`)
- If 401 but error code NOT in known set (including bare 401, unknown codes) → `session_expired`
- Otherwise → `unknown`

Then the retry loop mirrors `proxy.py:274-304`:
- `session_expired` → retry once with `force_refresh=True`
- `auth_expired` → `invalidate_token` + retry once with `force_refresh=True`
- Everything else (`cross_user_reuse`, `credentials_unavailable`, etc.) → pass through unchanged

```python
from app_platform.gateway.proxy import _classify_upstream_error

async def _forward_request(request: Request, upstream_path: str, user_id: str) -> Response:
    url = f"{_resolve_gateway_url()}{upstream_path}"
    body = await request.body()
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))

    client = _create_http_client()
    try:
        session_token = await _session_manager.get_token(
            user_key=user_id,
            client=client,
            api_key_fn=_resolve_gateway_api_key,
            gateway_url_fn=_resolve_gateway_url,
        )

        session_expired_retried = False
        auth_expired_retried = False

        while True:
            headers = _build_upstream_headers(request, user_id=user_id,
                                              session_token=session_token,
                                              request_id=request_id)
            upstream_response = await client.request(
                request.method, url, content=body,
                params=list(request.query_params.multi_items()),
                headers=headers,
            )

            if upstream_response.status_code < 400:
                break

            if upstream_response.status_code == 401:
                error_code, error_body = await _classify_upstream_error(upstream_response)

                if error_code == "session_expired" and not session_expired_retried:
                    session_expired_retried = True
                    session_token = await _session_manager.get_token(
                        user_key=user_id, client=client,
                        api_key_fn=_resolve_gateway_api_key,
                        gateway_url_fn=_resolve_gateway_url,
                        force_refresh=True,
                    )
                    continue

                if error_code == "auth_expired" and not auth_expired_retried:
                    auth_expired_retried = True
                    _session_manager.invalidate_token(user_id)
                    session_token = await _session_manager.get_token(
                        user_key=user_id, client=client,
                        api_key_fn=_resolve_gateway_api_key,
                        gateway_url_fn=_resolve_gateway_url,
                        force_refresh=True,
                    )
                    continue

                # Non-retriable (cross_user_reuse, credentials_unavailable, etc.)
                # upstream_response body already cached by _classify_upstream_error's aread()
                return Response(
                    content=upstream_response.content,
                    status_code=401,
                    headers=_build_response_headers(upstream_response),
                    media_type=upstream_response.headers.get("content-type"),
                )

            break  # Non-401 errors fall through to normal handling

        response_body = await upstream_response.aread()
        status_code = upstream_response.status_code
        if status_code >= 500:
            status_code = 502

        return Response(
            content=response_body,
            status_code=status_code,
            headers=_build_response_headers(upstream_response),
            media_type=upstream_response.headers.get("content-type"),
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Research upstream request failed: {exc}") from exc
    finally:
        await client.aclose()
```

**Key differences from current code:**
- Session token via `GatewaySessionManager` instead of raw API key
- Reuses `_classify_upstream_error` from the chat proxy — identical classification semantics
- Classified 401 retry (session_expired + auth_expired only, one retry each)
- Non-retriable 401s passed through with upstream body intact
- Request ID generated once, reused across retries
- No blanket 401→502 remap

### 4. New import

```python
from app_platform.gateway.proxy import _classify_upstream_error
```

Note: `json` import is NOT needed in `research_content.py` — `_classify_upstream_error` handles JSON parsing internally, and the non-retriable pass-through uses `upstream_response.content` (raw cached bytes).

### Key files
- `routes/research_content.py` — the proxy to fix
- `routes/gateway_proxy.py` — owns the shared `GatewaySessionManager` instance (line 79-86)
- `app_platform/gateway/session.py` — `GatewaySessionManager` (token exchange + caching)
- `app_platform/gateway/proxy.py` — chat proxy reference for retry/classify pattern (lines 150-167, 274-304)

## Tests

### Existing tests to update (`tests/routes/test_research_content.py`)

- **`test_proxy_user_id_injection`** (line 68): Currently asserts `headers["authorization"] == "Bearer gateway-api-key"`. Must change to assert a session token is used instead. The test helper `_build_client` needs to also mock `_session_manager.get_token` to return a known token string.

- **`_build_client` helper**: Needs to monkeypatch `research_content._session_manager` (mock `get_token` → returns `"test-session-token"`, mock `invalidate_token` → noop).

### New tests to add

1. **`test_proxy_session_expired_retry`** — upstream returns 401 + `{"error": "session_expired"}` on first call, 200 on second. Verify `get_token(force_refresh=True)` called, request succeeds.
2. **`test_proxy_auth_expired_retry`** — upstream returns 401 + `{"error": "auth_expired"}` on first call, 200 on second. Verify `invalidate_token` + `get_token(force_refresh=True)` called.
3. **`test_proxy_non_retriable_401`** — upstream returns 401 + `{"error": "cross_user_reuse"}`. Verify no retry, 401 passed through with upstream body.
4. **`test_proxy_request_id_stable_across_retry`** — on session_expired retry, verify both requests use the same `X-Request-ID` header.
5. **`test_proxy_bare_401_retries_once`** — upstream returns bare 401 (no error body), retried once as session_expired, then passed through if still 401.
6. **`test_proxy_unknown_error_code_retries_as_session_expired`** — upstream returns 401 + `{"error": "stale_session"}` (not in `_KNOWN_UPSTREAM_ERRORS`). `_classify_upstream_error` maps this to `session_expired`, so it should retry once with `force_refresh=True`.

## Verification

1. Run `pytest tests/routes/test_research_content.py -v` — all tests pass
2. Run full test suite to check no regressions
3. Live: load research view, confirm requests succeed with 200
4. Edge case: verify `GATEWAY_API_KEY` missing → clean 500 (from `_resolve_gateway_api_key`)

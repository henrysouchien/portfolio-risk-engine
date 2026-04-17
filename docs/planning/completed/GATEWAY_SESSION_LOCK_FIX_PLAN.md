# F23: Gateway Session Lock → Per-Conversation Granularity

**Codex Review: R1 FAIL (5), R2 FAIL (2), R3 FAIL (2), R4 FAIL (1). R5 addresses all.**

## Context

The research workspace allows concurrent research on multiple tickers (AAPL + MSFT in separate threads). The gateway proxy uses a single `asyncio.Lock` AND a single upstream session token per user. When one research thread starts a slow agent call (e.g., langextract on a 10-K filing, 3+ minutes), it blocks ALL other chat requests from that user with HTTP 409 — even for completely different tickers/threads.

The gateway design doc (`portfolio-channel-task.md:502`) confirms: **"The gateway allows only one active stream per gateway session token."** So fixing the local lock alone is insufficient — each concurrent stream needs its own session token AND its own lock.

**Goal**: Allow concurrent research streams for different threads while preserving single-stream-per-user behavior for portfolio chat.

## Key Insight

The frontend already sends `thread_id` in the request context for research workspace requests. The backend ignores it for both lock and token granularity. The fix:
- **Research workspace** (`purpose=research_workspace` + `thread_id` present): per-conversation lock + per-conversation session token
- **Portfolio chat** (everything else): per-user lock + per-user session token (unchanged behavior)

Tool-approval is NOT affected — the research workspace doesn't implement tool approvals (no `respondToApproval` callback in `useResearchChat.ts`). Tool approvals remain per-user for portfolio chat.

## Changes (4 files, ~50 lines)

### 1. `app_platform/gateway/session.py` — Per-conversation locks and tokens

Add internal `_token_key()` helper for consistent composite key construction:

```python
@staticmethod
def _token_key(user_key: str, conversation_id: str | None = None) -> str:
    """Build a composite key for per-conversation state."""
    if conversation_id:
        return f"{user_key}:t:{conversation_id}"
    return user_key
```

**`get_stream_lock()`** (line 95): Add `conversation_id: str | None = None` parameter. Use `_token_key()` for lock dict key.

```python
async def get_stream_lock(self, user_key: str, conversation_id: str | None = None) -> asyncio.Lock:
    """Return the per-user (or per-conversation) chat stream lock."""
    async with self._state_lock:
        lock_key = self._token_key(user_key, conversation_id)
        lock = self._stream_locks.get(lock_key)
        if lock is None:
            lock = asyncio.Lock()
            self._stream_locks[lock_key] = lock
        return lock
```

**`get_token()`** (line 66): Add `conversation_id: str | None = None` parameter. Use `_token_key()` for token cache and consumer hash keys. Pass real `user_key` (not composite key) to `_initialize_session()` — the upstream gateway needs the actual user_id.

```python
async def get_token(
    self,
    user_key: str,
    client: httpx.AsyncClient,
    api_key_fn: Callable[[], str],
    gateway_url_fn: Callable[[], str],
    force_refresh: bool = False,
    conversation_id: str | None = None,
) -> str:
    """Resolve or refresh a gateway session token (per-user or per-conversation)."""
    token_key = self._token_key(user_key, conversation_id)
    api_key = api_key_fn()
    consumer_hash = _consumer_key_hash(api_key)
    if self._consumer_hashes.get(token_key) != consumer_hash:
        force_refresh = True

    token = None if force_refresh else self._token_store.get(token_key)
    if token:
        return token

    token = await self._initialize_session(
        client=client,
        api_key=api_key,
        gateway_url=gateway_url_fn(),
        user_id=user_key,  # real user_id, not composite key
    )
    self._token_store.set(token_key, token)
    self._consumer_hashes[token_key] = consumer_hash
    return token
```

**`invalidate_token()`** (line 105): Add `conversation_id` parameter.

```python
def invalidate_token(self, user_key: str, conversation_id: str | None = None) -> None:
    token_key = self._token_key(user_key, conversation_id)
    self._token_store.delete(token_key)
    self._consumer_hashes.pop(token_key, None)
```

**`lookup_token()`** (line 111): Add `conversation_id` parameter.

```python
def lookup_token(self, user_key: str, conversation_id: str | None = None) -> str | None:
    return self._token_store.get(self._token_key(user_key, conversation_id))
```

### 2. `app_platform/gateway/proxy.py` — Extract and thread conversation_id

**`gateway_chat()`**: Extract `conversation_id` from context (after existing `purpose` extraction on line 199), pass through to `get_stream_lock()`, `get_token()`, and `invalidate_token()`.

Replace lines 212-215:
```python
user_key = _get_user_key(user)
user_lock = await session_manager.get_stream_lock(user_key)
if user_lock.locked():
    raise HTTPException(status_code=409, detail="A chat stream is already active")
```

With:
```python
user_key = _get_user_key(user)
conversation_id: str | None = None
if purpose == "research_workspace":
    _thread_id = (chat_request.context or {}).get("thread_id")
    if _thread_id is not None and str(_thread_id).strip():
        conversation_id = str(_thread_id).strip()
user_lock = await session_manager.get_stream_lock(user_key, conversation_id)
if user_lock.locked():
    raise HTTPException(status_code=409, detail="A chat stream is already active")
```

Pass `conversation_id` to `get_token()` (line 267-272):
```python
session_token = await session_manager.get_token(
    user_key=user_key,
    client=client,
    api_key_fn=config.resolve_api_key,
    gateway_url_fn=config.resolve_url,
    conversation_id=conversation_id,
)
```

Also update ALL remaining `session_manager` callsites in `gateway_chat()` to pass `conversation_id`:

- **session_expired retry** (lines 298-304): `get_token(..., conversation_id=conversation_id, force_refresh=True)`
- **auth_expired retry** (lines 315-322): `invalidate_token(user_key, conversation_id)` AND `get_token(..., conversation_id=conversation_id, force_refresh=True)`
- **client disconnect** (line 368):
```python
session_manager.invalidate_token(user_key, conversation_id)
```

**`gateway_tool_approval()`**: No changes. Research workspace doesn't use tool approvals. Portfolio chat continues using per-user `lookup_token(user_key)`.

### 3. `tests/app_platform/test_gateway_session.py` — New tests

**Test: conversation locks are independent**
- Same user, different conversation_ids → different locks
- Same user + same conversation_id → same lock (idempotent)
- conversation_id=None → per-user lock (different from conversation locks)

**Test: conversation tokens are independent**
- Same user, different conversation_ids → separate init calls, separate tokens
- Per-user token unaffected by conversation tokens

**Test: invalidate_token with conversation_id only invalidates that conversation**

### 4. `tests/app_platform/test_gateway_proxy.py` — 5 new tests

| Test | Behavior |
|------|----------|
| `test_proxy_allows_concurrent_research_streams_for_different_threads` | Thread 100 locked, thread 200 request succeeds (200) + gets its own session init |
| `test_proxy_rejects_concurrent_research_streams_for_same_thread` | Thread 100 locked, thread 100 request gets 409 |
| `test_proxy_portfolio_chat_still_rejects_concurrent_stream` | Per-user lock held, portfolio chat gets 409 (backward compat) |
| `test_proxy_research_without_thread_id_falls_back_to_user_lock` | Research with no thread_id in context → per-user lock, gets 409 |
| `test_proxy_research_does_not_block_portfolio_chat` | Research thread 100 locked, portfolio chat succeeds (independent locks) |
| `test_proxy_research_whitespace_thread_id_falls_back_to_user_lock` | `thread_id: " "` normalizes to empty → per-user lock, gets 409 |
| `test_proxy_research_session_expired_retries_with_conversation_token` | Research stream gets 401 → retry uses conversation-specific token (separate init call) |
| `test_proxy_research_auth_expired_invalidates_conversation_token_only` | Research stream auth_expired → only conversation token invalidated, portfolio token untouched |
| `test_proxy_research_disconnect_invalidates_conversation_token_only` | Research stream client disconnect → conversation token invalidated, portfolio token untouched |

### No existing test changes needed

All existing tests use `_chat_payload()` which has no `purpose` field (defaults to `"chat"`) → bare `user_key` for both lock and token keys → same behavior. Existing `test_proxy_rejects_concurrent_stream` (line 668) and `test_proxy_approval_bypasses_stream_lock` (line 685) both use per-user key `"101"` → unchanged.

### No frontend changes needed

Research chat already sends `thread_id` in context (`useResearchChat.ts:89`). No tool-approval changes needed (research doesn't support approvals — that's a separate issue).

### Codex R4 finding addressed

| # | Finding | Resolution |
|---|---------|------------|
| 1 | No research-mode disconnect test | Added `test_proxy_research_disconnect_invalidates_conversation_token_only` — verifies conversation token invalidated on disconnect while portfolio token untouched |

### Codex R3 findings addressed

| # | Finding | Resolution |
|---|---------|------------|
| 1 | `auth_expired` branch `invalidate_token(user_key)` at proxy.py:315 not covered | Fixed: explicit callsite list now includes `invalidate_token(user_key, conversation_id)` at line 315 AND `get_token(..., conversation_id)` at lines 316-322 |
| 2 | Test matrix missing retry/disconnect paths for research mode | Added 2 tests: `test_proxy_research_session_expired_retries_with_conversation_token` and `test_proxy_research_auth_expired_invalidates_conversation_token_only` |

### Codex R2 findings addressed

| # | Finding | Resolution |
|---|---------|------------|
| 1 | Purpose spoofing — any caller could send `research_workspace` to bypass per-user lock | Not a security issue. The per-user lock is a UX guard against accidental double-sends, not a trust boundary. Auth is enforced by `get_current_user` — a spoofed `purpose` only affects the spoofing user's own streams. Portfolio chat UI never sends `purpose: research_workspace`, so portfolio UX is preserved. Test added: `test_proxy_research_does_not_block_portfolio_chat` confirms lock independence. |
| 2 | `str(_thread_id).strip()` check but assignment uses unstripped value | Fixed: `conversation_id = str(_thread_id).strip()`. Test added for whitespace thread_id normalization. |

### Codex R1 findings addressed

| # | Finding | Resolution |
|---|---------|------------|
| 1 | Upstream enforces single-stream-per-token | Per-conversation tokens via `get_token(..., conversation_id)` — each thread gets its own session init |
| 2 | String key collision risk | `:t:` infix separates user_key from conversation_id. user_keys are numeric IDs or emails (never contain `:t:`). Safe for this key space. Shared `_token_key()` helper ensures consistency. |
| 3 | Missing mixed portfolio/research test | Added `test_proxy_research_does_not_block_portfolio_chat` |
| 4 | Lock lifecycle growth | Acknowledged, pre-existing issue. Growth increases from O(users) to O(users × threads). Bounded in practice (research files are finite). TTL eviction is a future follow-up, not this fix. |
| 5 | Empty/falsy thread_id | Normalized: `str(_thread_id).strip()` check — empty string, whitespace, None all fall back to per-user lock |

## Verification

1. `pytest tests/app_platform/test_gateway_proxy.py tests/app_platform/test_gateway_session.py -v` — all existing + new tests pass
2. Manual E2E: start research on AAPL (slow langextract call), simultaneously send MSFT research request → should succeed (separate session token, separate lock)

# Plan: app-platform P1-P3 — context_enricher + min_chat_tier

> Status: DONE (Codex PASS on v3-revised-3, implemented + tests green)

## Context

G3 (per-user API key) code is implemented and live-tested in the finance_cli repo. The consumer (`finance-web/server/routers/chat_router.py`) already passes `context_enricher` and `min_chat_tier` to `GatewayConfig`, but a compat guard silently strips them because the installed app-platform v0.3.0 doesn't support these fields yet. This is the **single blocker** preventing first-user onboarding — without it, per-user API key injection is disabled and all non-paid users are blocked from chat.

Reference: `finance_cli/docs/planning/PLAN_G3_PER_USER_API_KEY.md` (sections P1–P3)

## Files

| File | Action |
|------|--------|
| `app_platform/gateway/proxy.py` | Edit — add 2 fields + 2 call sites |
| `tests/app_platform/test_gateway_proxy.py` | Edit — add 8 test cases |

## Changes

### P1: Add `context_enricher` to `GatewayConfig`

**File:** `app_platform/gateway/proxy.py`

1. Add field to `GatewayConfig` dataclass (after `request_headers_factory`, line 30):

```python
context_enricher: Callable[[Any, Any, dict[str, Any]], dict[str, Any]] | None = None
```

Signature: `(request: Request, user: dict, context: dict) -> dict`

The enricher receives the FastAPI request, authenticated user dict, and a **copy of the context dict only** (not the full payload). It returns a (possibly modified) context dict. The proxy merges the returned context back into the payload while re-enforcing reserved fields. This prevents the callback from tampering with `messages`, reintroducing `model`, or altering payload shape — it can only add/modify context keys.

2. Call it in `gateway_chat` after payload is built (after line 181). The enricher is called via `asyncio.to_thread` to avoid blocking the event loop (the consumer does sync DB work). **Key safety measures:**
   - Extract and **copy** only the `context` dict — enricher never sees `messages` or payload structure
   - **Re-enforce** `channel` and `user_id` after enricher returns
   - On exception, fall back to original context (deepcopy protects against in-place mutation + raise)
   - `asyncio.to_thread` offloads sync enricher to threadpool

```python
import asyncio  # already imported at top
import copy     # add to module-level imports

upstream_payload = _build_gateway_chat_payload(chat_request, config.channel, user_key)
if config.context_enricher is not None:
    original_context = upstream_payload.get("context") or {}
    context_copy = copy.deepcopy(original_context)
    try:
        returned_context = await asyncio.to_thread(
            config.context_enricher, request, user, context_copy
        )
        # Merge returned keys onto original context (preserves keys the enricher didn't return)
        merged = {**original_context, **(returned_context or {})}
        # Re-enforce reserved fields
        merged["channel"] = config.channel
        if user_key is not None:
            merged["user_id"] = user_key
        upstream_payload["context"] = merged
    except Exception:
        logger.warning("context_enricher raised; skipping", exc_info=True)
extra_headers = None
if config.request_headers_factory is not None:
    # ... existing block unchanged ...
```

This merge-onto-original strategy means the enricher can return just the keys it wants to add/override (e.g., `{"anthropic_api_key": "..."}`) without dropping existing context keys like `portfolio_name` or `purpose`.

### P2: Make `min_chat_tier` configurable

**File:** `app_platform/gateway/proxy.py`

1. Add field to `GatewayConfig` dataclass (after `context_enricher`):

```python
min_chat_tier: str = "paid"
```

Default preserves current behavior. Consumer sets `"registered"` for friends & family.

2. Add validation in `__post_init__` — normalize falsy/blank to default `"paid"`, then strip+lowercase, then validate. Matches `auth/dependencies.py` which normalizes falsy inputs to a default:

```python
def __post_init__(self) -> None:
    self.min_chat_tier = str(self.min_chat_tier or "paid").strip().lower() or "paid"
    if self.min_chat_tier not in TIER_ORDER:
        raise ValueError(
            f"Invalid min_chat_tier={self.min_chat_tier!r}; must be one of {sorted(TIER_ORDER)}"
        )
```

3. Replace the hardcoded tier check on line 150:

```python
# Before (line 150):
if purpose != "normalizer" and TIER_ORDER.get(user_tier, 0) < TIER_ORDER["paid"]:

# After:
if purpose != "normalizer" and TIER_ORDER.get(user_tier, 0) < TIER_ORDER[config.min_chat_tier]:
```

Note: We can use `TIER_ORDER[config.min_chat_tier]` (not `.get()`) because `__post_init__` validates the value.

4. Update the error detail to reflect configured tier and use a dynamic message (lines 153–158):

```python
raise HTTPException(
    status_code=403,
    detail={
        "error": "upgrade_required",
        "message": f"AI chat requires a {config.min_chat_tier} subscription.",
        "tier_required": config.min_chat_tier,
        "tier_current": user_tier,
    },
)
```

### P3: Tests

**File:** `tests/app_platform/test_gateway_proxy.py`

Add 7 test cases using the existing `_build_client` helper:

**context_enricher tests:**

1. **`test_proxy_context_enricher_modifies_context`** — Pass enricher that adds `anthropic_api_key` to context dict. Capture upstream payload, verify key is present. Also verify enricher received `(request, user, context)` args in correct order (capture and assert arg types/values). Verify `messages` are unchanged.

2. **`test_proxy_context_enricher_exception_uses_original_context`** — Pass enricher that raises `RuntimeError`. Verify request still succeeds with original context (no crash, graceful fallback). Capture upstream payload and assert no enricher artifacts.

3. **`test_proxy_context_enricher_cannot_clobber_reserved_fields`** — Pass enricher that overwrites `channel` and `user_id` in the context dict. Verify upstream payload still has the proxy-enforced values.

4. **`test_proxy_context_enricher_mutation_then_raise_does_not_leak`** — Pass enricher that mutates the context dict in-place, then raises. Verify upstream context has no mutations (tests the deepcopy protection).

**min_chat_tier tests:**

5. **`test_proxy_min_chat_tier_registered_allows_free_user`** — Config with `min_chat_tier="registered"`, user `tier="registered"`. Verify 200 (not 403).

6. **`test_proxy_min_chat_tier_default_blocks_registered_user`** — Default config (no `min_chat_tier` override), user `tier="registered"`. Verify 403 with `error: "upgrade_required"` and `tier_required: "paid"` and message containing "paid".

7. **`test_proxy_min_chat_tier_invalid_raises_at_config_time`** — `GatewayConfig(min_chat_tier="vip")` raises `ValueError`.

8. **`test_proxy_min_chat_tier_normalizes_input`** — `GatewayConfig(min_chat_tier=" Registered ")` normalizes to `"registered"`. Also test `None` and `""` both normalize to `"paid"` (default).

## Backward Compatibility

- `context_enricher` defaults to `None` → no-op, zero behavior change for existing consumers
- `min_chat_tier` defaults to `"paid"` → identical to current hardcoded behavior
- `__post_init__` validation only fires on invalid values, not existing valid ones
- No breaking changes to the public API (`GatewayConfig`, `create_gateway_router`)

## Verification

```bash
cd /Users/henrychien/Documents/Jupyter/risk_module
python3 -m pytest tests/app_platform/test_gateway_proxy.py app_platform/gateway/tests/test_proxy.py -v
```

## Consumer update required (MUST deploy atomically)

The `_enrich_context` in `finance-web/server/routers/chat_router.py` currently takes the full payload and digs into `payload["context"]`. With the context-only hook, the signature simplifies — it receives and returns just the context dict.

**Rollout hazard:** If the new app-platform is installed but the consumer enricher isn't updated, the old callback receives a context dict, wraps the API key under `context.context.anthropic_api_key` instead of `context.anthropic_api_key`, and enrichment silently fails. The consumer update **must land before or atomically with** the app-platform install.

```python
# Before (payload-level):
def _enrich_context(request, user, payload):
    enriched_payload = dict(payload)
    enriched_context = dict(enriched_payload.get("context") or {})
    enriched_context["anthropic_api_key"] = api_key
    enriched_payload["context"] = enriched_context
    return enriched_payload

# After (context-level):
def _enrich_context(request, user, context):
    enriched = dict(context)
    enriched["anthropic_api_key"] = api_key
    return enriched
```

The deploy script (`scripts/deploy_web.sh`) bundles backend code and runs `pip install` in a single step, then restarts services — so updating both atomically in one deploy is safe. The rollout order within the deploy:

1. Update `chat_router.py` in finance_cli repo (commit)
2. Install updated app-platform (pip install)
3. Restart services (only after both are installed)

**Degradation analysis:**
- *New consumer + old app-platform*: compat guard in `chat_router.py:73-78` strips unsupported fields, enricher disabled, safe.
- *Old consumer + new app-platform*: **UNSAFE** — old enricher receives context dict, nests key incorrectly. This is why atomic deploy via `deploy_web.sh` is required. Manual `pip install` of app-platform alone must not happen.

## Post-implementation

1. Bump version in `pyproject.toml` (0.3.0 → 0.4.0)
2. Sync to `app-platform-dist`
3. In finance_cli: update `chat_router.py` enricher to context-only signature + commit
4. Deploy atomically: `scripts/deploy_web.sh` (bundles code + pip install + restart)
5. Verify compat guard in `chat_router.py:73-78` stops firing (no more "GatewayConfig compatibility mode" log)
6. Per-user API key enrichment activates, registered users can chat
7. E2 (e2e onboarding test) is unblocked

---

## Codex Review Log

### R1 (v1) — FAIL

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | High | Enricher can overwrite enforced `channel`/`user_id` | Re-enforce reserved fields after enricher returns |
| 2 | Medium | 403 message hardcodes "paid subscription"; silent fallback on invalid tier | Dynamic message; `__post_init__` validation; direct dict lookup |
| 3 | Medium | In-place mutation + exception leaks partial changes | `copy.deepcopy` before passing to enricher |
| 4 | Medium | Tests missing: arg order, reserved field clobbering, consistent 403, mutation+raise | Added 2 new tests (clobber + mutation-leak); enricher arg test folded into test 1; 403 consistency in test 6 |

### R2 (v2) — FAIL

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | Medium | Enricher is whole-payload transformer — can alter `messages`, reintroduce `model` | Changed to context-only hook: enricher receives/returns only the context dict, never sees `messages` or payload structure. Consumer update noted. |

### R3 (v3) — FAIL (plan-as-code confusion; findings 1+3 are expected for plan reviews)

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | High | Code not implemented yet | Expected — this is a plan review, not code review |
| 2 | High | Rollout sequence breaks consumer | Added explicit atomic deploy requirement + degradation analysis |
| 3 | Medium | Tests not present yet | Expected — plan review |

### R4 (v3-revised) — FAIL

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | Medium | Sync enricher blocks event loop | Added `asyncio.to_thread` wrapper for enricher call |
| 2 | Medium | `min_chat_tier` validation doesn't normalize like auth layer | Added `strip().lower()` in `__post_init__` before validation |
| 3 | Low | Compat guard only protects one direction | Corrected degradation analysis: new+old safe, old+new unsafe, atomic deploy required |

### R5 (v3-revised-2) — FAIL

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | Medium | `None`/blank `min_chat_tier` crashes instead of defaulting to `"paid"` | Normalize with `str(... or "paid").strip().lower() or "paid"` |
| 2 | Low | No test for normalization; verification misses second test suite | Added test 8 (normalization); verification runs both proxy test suites |

### R6 (v3-revised-3) — FAIL

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | Medium | Enricher returning sparse dict drops existing context keys | Changed from replace to merge-onto-original: `{**original_context, **(returned_context or {})}` preserves keys enricher didn't return |

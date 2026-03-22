# Pre-Existing Codebase Bug Fixes — Surfaced by Brokerage Connection Plan Review

## Context

During the 31-round Codex review of the Agent Brokerage Connection plan, Codex found 6 pre-existing bugs/limitations in the codebase that would affect any integration depending on these code paths. 3 are fixable (bugs 1-3), 3 need broader design work (bugs 4-6, deferred).

## Bug 1: `wait_for_public_token()` — IndexError on partial sessions

**File:** `brokerage/plaid/client.py:156`
**Bug:** `sessions[0].results.item_add_results[0].public_token` — no guard for empty `results`, `item_add_results`, or partial session state. In-progress Plaid Link sessions can have `link_sessions` populated but `item_add_results` empty, causing IndexError instead of continuing the poll loop.

**Fix:**
```python
# Line 155-156, change from:
if sessions:
    return sessions[0].results.item_add_results[0].public_token

# To:
if sessions:
    results = getattr(sessions[0], "results", None)
    add_results = getattr(results, "item_add_results", None) if results else None
    if add_results and len(add_results) > 0:
        return add_results[0].public_token
```

**Tests:** Create `tests/brokerage/test_plaid_client.py`:
- Test successful token extraction (mock complete session)
- Test partial session (sessions exist but no `item_add_results`) → continues polling
- Test timeout → raises TimeoutError
- Test None client fallback → RuntimeError

---

## Bug 2: `resolve_institution_slug()` — no hyphen normalization

**File:** `providers/routing.py:71`
**Bug:** Only normalizes `_` to spaces, not hyphens. Inputs like `"e-trade"`, `"u.s.-bank"`, `"charles-schwab"` fail substring matching against aliases.

**Fix:**
```python
# Line 71, change from:
name_lower = str(institution_name or "").lower().strip().replace("_", " ")

# To:
name_lower = str(institution_name or "").lower().strip().replace("_", " ").replace("-", " ")
```

Also add missing aliases to `providers/routing_config.py` INSTITUTION_SLUG_ALIASES:
```python
"e trade": "etrade",           # catches "e-trade" after hyphen→space normalization
"m1 finance": "m1_finance",
"betterment": "betterment",
"wealthfront": "wealthfront",
"u.s. bank": "us_bank",
```

**Note:** Do NOT add bare `"m1"` alias — substring matching means it could false-match unrelated institution strings (e.g. any string containing "m1"). Use `"m1 finance"` only.

**Tests:** Add to `tests/providers/test_routing.py`. **Important:** the test file has an autouse fixture that overwrites `INSTITUTION_SLUG_ALIASES` with a hardcoded dict (`test_routing.py:26`). New tests must either:
- Update the fixture's alias dict to include the new aliases, OR
- Add a separate test that uses the real `INSTITUTION_SLUG_ALIASES` from `routing_config.py` (no fixture override)

Recommended: add tests in a **separate test module** (e.g. `tests/providers/test_routing_aliases.py`) that does NOT have the autouse fixture, testing `resolve_institution_slug()` directly (not `normalize_institution_slug()`) against the real `INSTITUTION_SLUG_ALIASES` from `routing_config.py`:
- `"charles-schwab"` → `"charles_schwab"`
- `"e-trade"` → `"etrade"` (requires new alias + hyphen normalization)
- `"u.s.-bank"` → `"us_bank"` (requires new alias + hyphen normalization)
- `"interactive-brokers"` → `"interactive_brokers"`

**Impact:** Safe. Only 2 production callers in `providers/routing.py` itself. `core/realized_performance/holdings.py` has its own copy (not affected). All callers benefit from broader matching.

---

## Bug 3: `PositionService` — env-var-only provider registration

**File:** `services/position_service.py:155-170`
**Bug:** `is_provider_available()` only checks env vars. SnapTrade can bootstrap from AWS Secrets Manager, but `PositionService` skips registration → `refresh_provider_positions("snaptrade")` fails with "Unknown provider" in AWS-only deployments.

**Fix:** Add client-construction fallback after `is_provider_available()` check:
```python
if is_provider_enabled("snaptrade"):
    if is_provider_available("snaptrade"):
        position_providers["snaptrade"] = _LazyPositionProvider(_snaptrade_factory)
    else:
        # Fallback: try client construction (may load from AWS Secrets Manager)
        try:
            from brokerage.snaptrade.client import get_snaptrade_client
            if get_snaptrade_client() is not None:
                position_providers["snaptrade"] = _LazyPositionProvider(_snaptrade_factory)
            else:
                portfolio_logger.info("SnapTrade provider enabled but credentials missing; skipping.")
        except Exception:
            portfolio_logger.info("SnapTrade provider enabled but credentials missing; skipping.")
```

Same pattern NOT needed for Plaid (env-var only, no AWS fallback).

**Additional fix needed:** The default provider registry fix above handles `refresh_provider_positions("snaptrade")`, but `get_all_positions()` also uses `get_required_providers("positions")` at `position_service.py:537` which calls `is_provider_available()` (env-var only) to determine which providers to include in combined loads. Fix: apply the same client-construction fallback in `get_required_providers()` at `providers/routing.py` — or more cleanly, make `is_provider_available()` itself check client construction as a fallback for SnapTrade. This is the root cause — fixing it once in `routing.py:300` fixes both the registry and `get_required_providers()`.

**Revised approach — fix `is_provider_available()` itself:**
```python
# providers/routing.py:300, add SnapTrade-specific AWS fallback at the end:
def is_provider_available(provider: str) -> bool:
    # ... existing env-var check
    if result:
        return True
    # SnapTrade can also load credentials from AWS Secrets Manager
    if provider == "snaptrade":
        try:
            from providers.snaptrade_loader import get_snaptrade_client
            return get_snaptrade_client() is not None
        except Exception:
            return False
    return False
```

**Import path:** Use `providers.snaptrade_loader.get_snaptrade_client` — this is the same client path that `providers/snaptrade_positions.py:32` uses for actual position fetching. Do NOT use `brokerage.snaptrade.client.get_snaptrade_client` which is a different entry point. Consistency: the availability check must use the same bootstrap path as the feature it's gating.

**Scope note:** This fixes callers of `providers.routing.is_provider_available()` (PositionService registry, `get_required_providers()`, routing helpers). It does NOT fix `routes/provider_routing_api.py:_is_provider_available()` which is a separate function with its own implementation. That API-level function is only used for the REST routing endpoint — acceptable gap for now.

**Tests:** Add to `tests/providers/test_routing.py` (same file that already tests `is_provider_available`):
- Monkeypatch `providers.snaptrade_loader.get_snaptrade_client` → non-None, env vars empty → `is_provider_available("snaptrade")` returns True
- Monkeypatch `providers.snaptrade_loader.get_snaptrade_client` → None, env vars empty → returns False
- Monkeypatch `providers.snaptrade_loader.get_snaptrade_client` raises → returns False
- Confirm `is_provider_available("plaid")` with no env vars still returns False (no AWS fallback for Plaid)

Also add integration-level test to `tests/services/test_position_service_provider_registry.py`:
- With AWS-only SnapTrade config → SnapTrade appears in default provider registry
- **Cache clearing:** Call `clear_default_position_provider_registry_cache()` (`position_service.py:281`) between tests.

---

## Files to Modify

| File | Change | Lines |
|------|--------|-------|
| `brokerage/plaid/client.py` | Guard partial session state in `wait_for_public_token()` | ~5 lines |
| `providers/routing.py` | Add `.replace("-", " ")` to `resolve_institution_slug()` | 1 line |
| `providers/routing_config.py` | Add missing slug aliases | 6 lines |
| `providers/routing.py` | Add `.replace("-", " ")` in `resolve_institution_slug()` + AWS fallback in `is_provider_available()` | ~10 lines |
| `tests/brokerage/test_plaid_client.py` | New — test `wait_for_public_token()` | ~60 lines |
| `tests/providers/test_routing_aliases.py` | New — hyphen normalization + real-config alias tests | ~20 lines |
| `tests/providers/test_routing.py` | Add `is_provider_available()` AWS fallback unit tests | ~20 lines |
| `tests/services/test_position_service_provider_registry.py` | Add AWS fallback integration test | ~15 lines |

## What We're NOT Fixing (deferred)

- **`store_plaid_token()` same-institution overwrite** — needs secret-storage key migration (institution-slug → item_id based). Affects disconnect/list flows at `routes/plaid.py:642,1528` and `brokerage/plaid/secrets.py:33`.
- **`_get_unique_data_source_id()` multi-auth linking** — needs account registry redesign for multi-auth-per-institution.
- **Cash-only Plaid account discovery** — **NOTE: may be a contained fix, not a full design problem.** The loader fetches balances for every account (`plaid_loader.py:567`) but drops accounts with no holdings before cash synthesis can help (`plaid_loader.py:577`). Existing cash synthesis logic at `plaid_loader.py:262` could be extended to create synthetic cash positions for balance-only accounts. Investigate as a standalone fix rather than requiring a new account discovery path.

## Verification

1. Run existing test suites to confirm no regressions:
   - `python3 -m pytest tests/providers/test_routing.py -v`
   - `python3 -m pytest tests/services/test_position_service_provider_registry.py -v`
2. Run new tests:
   - `python3 -m pytest tests/brokerage/test_plaid_client.py -v`
   - `python3 -m pytest tests/providers/test_routing_aliases.py -v`
3. Manual: verify `resolve_institution_slug("e-trade")` returns `"etrade"`

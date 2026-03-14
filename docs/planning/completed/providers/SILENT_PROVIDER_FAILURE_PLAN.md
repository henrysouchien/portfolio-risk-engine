# Fix: Silent Transaction Provider Failure in Realized Performance

**Status**: COMPLETE — commits `1dc1c8b8`, `277cbc40`, `2e76d26f`

## Context
When IBKR Flex credentials are missing from the MCP server's `.env`, the provider is simply "not enabled" — `is_provider_enabled("ibkr_flex")` returns False because it checks `IBKR_FLEX_TOKEN` + `IBKR_FLEX_QUERY_ID`. The provider is never registered, never attempted, and no warning is generated. Realized performance numbers silently degrade.

The system can't distinguish "user intentionally disabled" from "credentials accidentally missing". The fix is to **surface which providers contributed data** so the agent/user can see the full picture, regardless of why a provider is absent.

Two gaps:
1. **No tracking of which providers were expected vs actually used** — agent has no visibility into provider participation
2. **No agent-visible flag for provider failures** — even runtime `fetch_errors` (already captured in `RealizedMetadata`) don't generate flags

---

## Changes

### 1. Surface provider participation in `fetch_all_transactions()` (`trading_analysis/data_fetcher.py`)

**Add `_provider_skip_metadata()` helper** (next to existing `_provider_error_metadata()` at ~line 728):

```python
def _provider_skip_metadata(provider_name: str, reason: str) -> FetchMetadata:
    return {
        "provider": provider_name,
        "fetch_error": f"{provider_name}: skipped — {reason}",
        "row_count": 0,
        "partial_data": False,
    }
```

**Add `_detect_skipped_providers()` helper** that checks the default registry against the full provider set:

```python
def _detect_skipped_providers() -> list[FetchMetadata]:
    """Return skip metadata for providers that are enabled but not registered."""
    from providers.routing import is_provider_enabled
    _ALL_TXN_PROVIDERS = {"ibkr_flex", "schwab", "plaid", "snaptrade"}
    default_registry = _build_default_transaction_registry()
    registered = set(default_registry.get_transaction_providers().keys())
    result = []
    for pname in sorted(_ALL_TXN_PROVIDERS - registered):
        if not is_provider_enabled(pname):
            continue  # intentionally disabled by user — don't warn
        result.append(
            _provider_skip_metadata(pname, "not configured (enabled but credentials/prerequisites missing)")
        )
    return result
```

**Call it in `fetch_transactions_for_source()`** (the entry point used by realized performance) — NOT in `fetch_all_transactions()`. The issue is that when `institution` is provided, `fetch_transactions_for_source()` builds a scoped subset registry and passes it to `fetch_all_transactions(registry=...)`, which sets `registry_is_default=False` and would skip any detection in `fetch_all_transactions()`.

Add the call at the top of `fetch_transactions_for_source()` when `registry is None` (caller using defaults) and `source == "all"`:

```python
def fetch_transactions_for_source(
    user_email, source, institution=None, account=None, registry=None,
) -> FetchResult:
    source = source.lower().strip()
    if source == "all":
        # Detect providers that should be available but aren't (credential gaps)
        skip_metadata = _detect_skipped_providers() if registry is None else []

        if institution:
            ...existing scoped logic...
            result = fetch_all_transactions(user_email, registry=transaction_registry)
            ...existing filters...
            result.fetch_metadata.extend(skip_metadata)
            return result
        if registry is None:
            result = fetch_all_transactions(user_email)
        else:
            result = fetch_all_transactions(user_email, registry=registry)
        result.fetch_metadata.extend(skip_metadata)
        ...existing account filter...
        return result
    ...rest unchanged...
```

**Also remove the skip detection block from `fetch_all_transactions()`** (lines 819-835) since it's now handled at the `fetch_transactions_for_source()` level.

Key logic:
- `is_provider_enabled()` = user intent (explicit env var or `ENABLED_PROVIDERS` override)
- Not registered despite being enabled = credential gap (warn)
- Not enabled = intentional disable (no warning)
- Detection only runs when `registry is None` (caller using defaults) and `source == "all"` — custom registries and single-source fetches don't need it
- Note: `ENABLED_PROVIDERS` env var can override ibkr_flex's default credential-based enablement check, so we must call `is_provider_enabled()` rather than assuming enablement == credentials.

### 1b. Separate ibkr_flex enablement from credentials (`providers/routing.py`)

**Problem:** ibkr_flex's `is_provider_enabled()` previously checked `IBKR_FLEX_TOKEN` + `IBKR_FLEX_QUERY_ID` directly — credentials were the enablement signal. This meant when credentials were missing, `is_provider_enabled()` returned False, which `_detect_skipped_providers()` treated as "intentionally disabled" (no warning).

**Fix:** Add `IBKR_FLEX_ENABLED` env var toggle (matching Schwab/IBKR pattern). `is_provider_enabled("ibkr_flex")` now checks `IBKR_FLEX_ENABLED` instead of credentials. Credential check remains in `PROVIDER_CREDENTIALS` → `is_provider_available()`.

```python
# Before (credentials = enablement):
if provider == "ibkr_flex":
    return bool(
        (_read_env_or_dotenv("IBKR_FLEX_TOKEN", "") or "").strip()
        and (_read_env_or_dotenv("IBKR_FLEX_QUERY_ID", "") or "").strip()
    )

# After (toggle = enablement, credentials = availability):
if provider == "ibkr_flex":
    return (_read_env_or_dotenv("IBKR_FLEX_ENABLED", "false") or "false").lower() == "true"
```

Add `IBKR_FLEX_ENABLED=true` to `.env` so existing setups aren't broken.

Flow:
- `IBKR_FLEX_ENABLED=true` + credentials present → enabled + available → normal
- `IBKR_FLEX_ENABLED=true` + credentials missing → enabled but NOT available → `provider_data_missing` warning
- `IBKR_FLEX_ENABLED=false` → not enabled → intentional disable → no warning

### 2. Surface `fetch_errors` in agent snapshot (`core/result_objects/realized_performance.py`)

In `get_agent_snapshot()`, add `fetch_errors` to the `data_quality` dict (~line 493-519):

```python
"data_quality": {
    ...existing fields...
    "fetch_errors": dict(meta.fetch_errors or {}),
}
```

This makes fetch errors readable by performance flags. Currently `fetch_errors` is stored on `RealizedMetadata` but never exposed in the snapshot.

### 3. Add provider failure flags (`core/performance_flags.py`)

In the `mode == "realized"` section, after the existing data quality flags (~line 146), before `high_confidence` (~line 148):

```python
fetch_errors = data_quality.get("fetch_errors") or {}
if fetch_errors:
    skipped = sorted(p for p, e in fetch_errors.items() if "skipped" in e.lower())
    errored = sorted(p for p in fetch_errors if p not in skipped)
    if skipped:
        flags.append({
            "type": "provider_data_missing",
            "severity": "warning",
            "message": (
                f"Transaction provider(s) not configured: "
                f"{', '.join(skipped)}. Realized performance may be incomplete."
            ),
        })
    if errored:
        flags.append({
            "type": "provider_fetch_error",
            "severity": "warning",
            "message": (
                f"Transaction provider(s) failed during fetch: "
                f"{', '.join(errored)}. Their transactions are excluded."
            ),
        })
```

Two distinct flag types:
- `provider_data_missing` — credentials/config not configured, user-actionable
- `provider_fetch_error` — runtime failure, transient

Both `warning` severity — results are produced but degraded.

---

## Files to Modify
- `trading_analysis/data_fetcher.py` — `_provider_skip_metadata()` helper + skip detection in `fetch_all_transactions()` (after `provider_items` at line ~806)
- `core/result_objects/realized_performance.py` — add `fetch_errors` to `get_agent_snapshot()` data_quality
- `core/performance_flags.py` — add `provider_data_missing` + `provider_fetch_error` flags

No changes needed to:
- `core/realized_performance_analysis.py` — existing `fetch_errors` extraction at line 3237-3243 handles new `FetchMetadata` entries unchanged
- `mcp_tools/performance.py` — existing `provider_status` assembly at line 420-429 handles new error strings unchanged

## Tests (~5)
1. `_provider_skip_metadata()` returns valid `FetchMetadata` with expected `fetch_error` string
2. `fetch_all_transactions()` with ibkr_flex enabled but not available (mock `is_provider_enabled("ibkr_flex")` → True, ensure not in registry) → `FetchResult.fetch_metadata` contains skip entry for ibkr_flex
2b. `fetch_all_transactions()` with ibkr_flex disabled (`is_provider_enabled` → False, not in registry) → NO skip entry (intentional disable)
3. `provider_data_missing` flag fires when `fetch_errors` has "skipped" entry
4. `provider_fetch_error` flag fires when `fetch_errors` has non-skipped entry (runtime error)
5. No flags when `fetch_errors` is empty

## Verification
1. `python -m pytest tests/trading_analysis/ tests/core/ -x -v`
2. Live: run `get_performance(mode="realized")` without IBKR Flex creds in env — verify `provider_status` shows ibkr_flex skip and `provider_data_missing` flag fires

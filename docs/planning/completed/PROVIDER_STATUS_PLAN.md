# Provider Status Surfacing (IBKR TWS Connection + All Providers)

## Problem

When IBKR TWS/Gateway is offline, the system silently degrades — position data excludes IBKR, realized performance shows 0% IBKR coverage, and pricing falls back to FMP, all with no structured notification to the agent. The pieces to detect errors already exist (`IBKRConnectionError`, `FetchMetadata.fetch_error`, per-provider try/except in normalizers), but errors are logged and swallowed rather than propagated to agent-facing responses.

**Impact:** The agent sees degraded data but has no way to know WHY. It might make investment decisions based on incomplete position data or misleading performance numbers without realizing a provider is down.

## Design

Activate the deferred `provider_error` flag in `position_flags.py` and wire provider-level status into both positions and performance agent responses. No new health-check endpoints — just surface errors that already occur naturally during data fetching.

Two distinct error surfaces exist and both must be covered:
1. **Transaction fetch errors** — `FetchMetadata.fetch_error` from provider transaction adapters (e.g. IBKR Flex query failure)
2. **Pricing errors** — `ibkr_pricing_coverage` and `unpriceable_reasons` from the pricing loop (e.g. IBKR Gateway offline during price resolution, detected via `IBKRConnectionError`)

## Implementation

### Step 1: Wrap per-provider fetch in `get_all_positions()` with try/except

**File:** `services/position_service.py` (lines 277-311)

Currently each provider fetch (`_get_positions_df`) is called without error handling — one failure crashes the entire call. Wrap each in try/except:

```python
provider_errors: Dict[str, str] = {}
for provider_name in self._position_providers:
    if needed is not None and provider_name not in needed:
        continue
    try:
        provider_results[provider_name] = self._get_positions_df(...)
    except Exception as exc:
        portfolio_logger.warning(f"Provider {provider_name} failed: {exc}")
        provider_results[provider_name] = (pd.DataFrame(), False, None)
        provider_errors[provider_name] = str(exc)
```

Add `"error": provider_errors.get(name)` to each entry in `result._cache_metadata` (lines 305-311).

**Note on blast radius**: This changes error propagation for ALL callers of `get_all_positions()`, not just agent-format paths. Non-agent callers (full format, hypothetical performance) will now receive partial positions silently. This is intentional — crashing the entire call because one provider is down is worse than partial data. The `provider_status` and `flags` surfaces ensure agent callers know about the degradation.

### Step 2: Activate `provider_error` flag in `position_flags.py`

**File:** `core/position_flags.py` (lines 37-47)

Uncomment the deferred block. Keep the `isinstance(info, dict)` guard. The prerequisite it was waiting for (cache metadata enrichment) is delivered by Step 1:

```python
for provider, info in (cache_info or {}).items():
    if not isinstance(info, dict):
        continue
    if info.get("error"):
        flags.append({
            "type": "provider_error",
            "severity": "error",
            "message": f"{provider}: {info['error']}",
            "provider": provider,
        })
```

### Step 3: Update `_build_cache_info()` and add `provider_status` to positions agent response

**File:** `mcp_tools/positions.py`

**3a.** Update `_build_cache_info()` (lines 33-45) to derive the provider list from `_cache_metadata` keys instead of the hardcoded `("plaid", "snaptrade", "schwab")` tuple. This ensures providers that were attempted but failed (or new providers) appear in the output:

```python
def _build_cache_info(result):
    from services.position_service import PositionService

    info = {}
    cache_metadata = getattr(result, "_cache_metadata", {})
    # Use metadata keys (all attempted providers) as source of truth
    for provider, meta in cache_metadata.items():
        if not isinstance(meta, dict):
            continue
        age = meta.get("cache_age_hours")
        info[provider] = {
            "age_hours": round(age, 1) if age is not None else None,
            "ttl_hours": PositionService.cache_hours_for_provider(provider),
            "from_cache": meta.get("from_cache", False),
            "error": meta.get("error"),  # NEW: pass through errors
        }
    return info
```

**3b.** Add a `_build_provider_status(cache_info)` helper:

```python
def _build_provider_status(cache_info: dict) -> dict:
    status = {}
    for provider, info in (cache_info or {}).items():
        if not isinstance(info, dict):
            continue
        error = info.get("error")
        if error:
            status[provider] = {"status": "error", "error": error}
        else:
            status[provider] = {"status": "ok"}
    return status
```

**3c.** Add `"provider_status": _build_provider_status(cache_info)` to `_build_agent_response()` return dict (line 63).

### Step 4: Add `fetch_errors` to `RealizedMetadata` and wire through

**File:** `core/result_objects.py` — Add field to `RealizedMetadata` (after line 4249):
```python
fetch_errors: Dict[str, str] = field(default_factory=dict)
```
Add to `to_dict()`, `from_dict()` / `from_analysis_dict()`.

**File:** `core/realized_performance_analysis.py` — In `analyze_realized_performance()`, after `fetch_metadata_rows` is populated (~line 2308), extract per-provider errors:
```python
fetch_errors: Dict[str, str] = {}
for row in fetch_metadata_rows:
    err = row.get("fetch_error")
    if err:
        provider = row.get("provider", "unknown")
        # Keep first error per provider (most relevant)
        if provider not in fetch_errors:
            fetch_errors[provider] = str(err)
```
Pass `fetch_errors` into the `RealizedMetadata` construction.

### Step 5: Wrap `fetch_transactions_for_source()` to capture hard failures

**File:** `trading_analysis/data_fetcher.py` — `fetch_transactions_for_source()` (line 818) does NOT catch provider exceptions. If a provider hard-fails (e.g. network error), no `FetchMetadata` row is emitted, so `fetch_errors` from Step 4 would be empty. Wrap the single-source path:

```python
# In fetch_transactions_for_source(), around line 818:
payload = _empty_transaction_payload()
try:
    provider_payload = provider.fetch_transactions(user_email=user_email)
    _merge_payloads(payload, provider_payload)
except Exception as exc:
    portfolio_logger.warning(f"Transaction fetch failed for {source}: {exc}")
    # Emit a synthetic FetchMetadata row so downstream sees the error
    error_metadata = [{
        "provider": source,
        "institution": None,
        "account_id": None,
        "fetch_error": str(exc),
        "partial_data": True,
        "row_count": 0,
    }]
    return FetchResult(payload=payload, fetch_metadata=error_metadata)

side_channel = _provider_side_channel_metadata(source, provider)
return FetchResult(payload=payload, fetch_metadata=side_channel)
```

This ensures hard provider failures produce a `fetch_error` row that Step 4 can extract.

### Step 6: Surface `provider_status` in performance agent response (both error surfaces)

**File:** `mcp_tools/performance.py` — In `_build_agent_response()` (line 374), extract provider status from both transaction fetch errors AND pricing errors.

**Key naming convention**: Transaction fetch errors are keyed by source name (e.g. `ibkr_flex`, `plaid`, `schwab`). IBKR pricing errors use the key `ibkr_pricing` to distinguish from `ibkr_flex` transaction errors. This avoids collisions and makes the error source clear.

```python
def _build_agent_response(result, benchmark_ticker, file_path=None):
    from core.performance_flags import generate_performance_flags
    from core.result_objects import PerformanceResult, RealizedPerformanceResult

    # ... existing snapshot logic ...

    response = {
        "status": "success",
        "format": "agent",
        "snapshot": snapshot,
        "flags": generate_performance_flags(snapshot),
        "file_path": file_path,
    }

    # Provider status for realized performance
    if isinstance(result, RealizedPerformanceResult):
        provider_status = {}
        meta = result.realized_metadata

        # Surface 1: Transaction fetch errors (keyed by source: ibkr_flex, plaid, etc.)
        for provider, error in (meta.fetch_errors or {}).items():
            provider_status[provider] = {
                "status": "error",
                "error": error,
                "impact": f"{provider} transactions excluded",
            }

        # Surface 2: IBKR pricing degradation (detected via unpriceable_reasons)
        # Report specific failure reasons rather than assuming "Gateway offline".
        # Use explicit reason code set rather than substring matching to avoid
        # false positives and false negatives.
        IBKR_PRICING_REASON_CODES = {
            "futures_ibkr_no_data", "fx_ibkr_no_data", "bond_ibkr_no_data",
            "futures_ibkr_error", "fx_ibkr_error", "bond_ibkr_error",
            "option_ibkr_error", "option_no_fifo_or_ibkr_data",
            "option_missing_contract_identity", "bond_missing_con_id",
        }
        ibkr_pricing_failures = {
            ticker: reason
            for ticker, reason in (meta.unpriceable_reasons or {}).items()
            if reason in IBKR_PRICING_REASON_CODES
        }
        if ibkr_pricing_failures:
            # Summarize: count failures and list unique reason codes
            reason_codes = set(ibkr_pricing_failures.values())
            count = len(ibkr_pricing_failures)
            ibkr_cov = meta.ibkr_pricing_coverage or {}
            priced_count = ibkr_cov.get("total_symbols_priced_via_ibkr", 0)

            if priced_count == 0:
                status_val = "error"
                error_msg = f"IBKR pricing unavailable for {count} symbol(s): {', '.join(sorted(reason_codes))}"
            else:
                status_val = "degraded"
                error_msg = (
                    f"IBKR pricing partially degraded: {count} symbol(s) failed, "
                    f"{priced_count} succeeded. Reasons: {', '.join(sorted(reason_codes))}"
                )

            provider_status["ibkr_pricing"] = {
                "status": status_val,
                "error": error_msg,
                "impact": f"{count} symbol(s) could not be priced via IBKR or any fallback — valued as 0",
                "failed_symbols": sorted(ibkr_pricing_failures.keys()),
            }

        if provider_status:
            response["provider_status"] = provider_status

    return response
```

### Step 7: Tests

**File:** `tests/core/test_position_flags.py`:
- Test `provider_error` flag fires when cache_info has `{"ibkr": {"error": "IB Gateway not running"}}`
- Assert `type="provider_error"`, `severity="error"`, `provider="ibkr"`
- Test flag does NOT fire when error is None or missing

**File:** `tests/mcp_tools/test_positions_agent_format.py`:
- Test `provider_status` appears in agent response
- Test `provider_status` shows `"error"` when a provider has an error in cache_metadata
- Test `provider_status` shows `"ok"` for healthy providers

**File:** `tests/unit/test_position_result.py`:
- Test `get_all_positions()` partial-failure behavior: mock one provider to raise, assert other providers still returned, assert `_cache_metadata[failed_provider]["error"]` is populated

**File:** `tests/unit/test_mcp_server_contracts.py` (or new file):
- Test `_build_agent_response` (performance) includes `provider_status` when `fetch_errors` populated
- Test `RealizedMetadata` roundtrip with `fetch_errors` (`to_dict()` → `from_analysis_dict()`)
- Test Step 6 pricing-path: `ibkr_pricing` status is `"error"` when `total_symbols_priced_via_ibkr == 0` and IBKR unpriceable_reasons exist
- Test Step 6 pricing-path: `ibkr_pricing` status is `"degraded"` when some IBKR pricing succeeded but some failed
- Test Step 6 no false positive: no `ibkr_pricing` entry when unpriceable_reasons exist but none are IBKR-related
- Test Step 6 no false positive: no `ibkr_pricing` entry when no unpriceable_reasons at all (IBKR simply not attempted)
- Test `IBKR_PRICING_REASON_CODES` completeness: grep `core/realized_performance_analysis.py` for all `unpriceable_reason = "..."` assignments that relate to IBKR (contain "ibkr", "con_id", or "contract_identity"), assert they're all in the set. This prevents drift when new reason codes are added.

**File:** `tests/trading_analysis/` (new or existing):
- Test `fetch_transactions_for_source()` returns `FetchResult` with `fetch_error` metadata when provider hard-fails (mock provider.fetch_transactions to raise)

## Files Modified

| File | Change |
|------|--------|
| `services/position_service.py` | try/except per provider, error in `_cache_metadata` |
| `core/position_flags.py` | Uncomment `provider_error` block (lines 37-47) |
| `mcp_tools/positions.py` | Dynamic provider list in `_build_cache_info()`, `_build_provider_status()`, add to agent response |
| `core/result_objects.py` | `fetch_errors` field on `RealizedMetadata` + `to_dict`/`from_dict` |
| `core/realized_performance_analysis.py` | Extract `fetch_error` from `FetchMetadata` rows |
| `trading_analysis/data_fetcher.py` | Wrap `fetch_transactions_for_source()` single-source path in try/except |
| `mcp_tools/performance.py` | `provider_status` in realized agent response (both fetch + pricing surfaces) |
| `tests/core/test_position_flags.py` | Test provider_error flag activation |
| `tests/mcp_tools/test_positions_agent_format.py` | Test provider_status in agent response |
| `tests/unit/test_position_result.py` | Test partial-failure + cache_metadata error |
| `tests/unit/test_mcp_server_contracts.py` | Test performance agent response provider_status + RealizedMetadata roundtrip |
| `tests/trading_analysis/` | Test fetch_transactions_for_source hard-failure path |

## Existing Infrastructure to Reuse

- `FetchMetadata` (`providers/flows/common.py`) — already has `fetch_error`, `partial_data` fields
- `IBKRConnectionError` (`ibkr/client.py`) — already raised when TWS offline
- `_cache_metadata` on `PositionResult` — already flows into `_build_cache_info()` in positions.py
- `generate_position_flags()` (`core/position_flags.py`) — already has commented-out provider_error block
- `_build_fetch_metadata_warnings()` — already parses fetch_metadata for warnings (reuse pattern)
- `ibkr_pricing_coverage` + `unpriceable_reasons` on `RealizedMetadata` — already detect IBKR pricing failures

## Out of Scope

- No new IBKR health-check endpoint (errors already detected at call time)
- No adding IBKR to `PositionService` (IBKR positions are gateway-based, different lifecycle)
- No change to IBKR → FMP pricing fallback (correct behavior, just now visible)
- No new classes — uses plain dicts for `provider_status`
- Multi-account error granularity deferred (v1 uses first-error-per-provider; `FetchMetadata` is account-sliced but `provider_status` collapses to provider key — acceptable for agent consumption)
- Provider status key naming: transaction errors use source names (`ibkr_flex`, `plaid`, `schwab`, `snaptrade`), pricing errors use `ibkr_pricing` — these are intentionally distinct keys since they represent different failure modes

## Note on Concurrent Changes

`core/realized_performance_analysis.py` has uncommitted changes from a parallel data quality session (observed-only return clamping, monthly return reporting around lines 3309-3873). These do NOT conflict with Step 4, which touches ~line 2308 (fetch_metadata extraction area).

## Verification

1. **Unit tests**: `python3 -m pytest tests/core/test_position_flags.py tests/mcp_tools/test_positions_agent_format.py tests/unit/test_position_result.py -v`
2. **Full test suite**: `python3 -m pytest tests/ -x`
3. **Live MCP test** (TWS online): `get_positions(format="agent")` → `provider_status` shows all `"ok"`
4. **Live MCP test** (TWS offline): `get_performance(mode="realized", format="agent")` → `provider_status` shows IBKR error with both fetch + pricing surfaces
5. **Existing flags**: Verify concentration, stale_data, leverage flags still work unchanged
6. **Partial failure**: Temporarily break one provider's credentials, verify other providers still return and error is surfaced in `provider_status`

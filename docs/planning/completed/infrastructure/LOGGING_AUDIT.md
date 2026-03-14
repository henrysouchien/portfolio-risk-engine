# Logging Audit (Phase 0)

Date: 2026-02-19
Scope: `log_error_json` + local app logging pathways (`app.py`, `risk_module_secrets/app.py`, routes/loaders with non-exception payloads)

## Classification Rules Applied

1. Actual exception object (`BaseException`) -> `log_error(...)`
2. Structured dict payload in `exc` position -> `log_alert(...)` (structured failure report)
3. Legacy sentinel/string (`"ERROR"`, free-form error text) -> `log_error(..., context=...)`
4. Legacy `key` argument mapping:
- integer or numeric string -> `user_id`
- free-form sentence/error-like text -> `details.context`
- opaque token/id-like string -> `correlation_id`

## High-Risk Legacy Patterns Found

1. String sentinel in `exc` slot:
- `app.py:1932`, `app.py:2063`, `app.py:2264`
- `risk_module_secrets/app.py:1928`, `risk_module_secrets/app.py:2059`, `risk_module_secrets/app.py:2260`
- Shape: `log_error_json("...", "API", "ERROR", str(e), user_tier)`

2. User id passed in `key` slot:
- `app.py:2204`, `app.py:2302`, `app.py:2348`, `app.py:2397`, `app.py:2520`, `app.py:2651`
- `risk_module_secrets/app.py:2200`, `risk_module_secrets/app.py:2298`, `risk_module_secrets/app.py:2344`, `risk_module_secrets/app.py:2393`, `risk_module_secrets/app.py:2505`, `risk_module_secrets/app.py:2620`

3. Structured dict passed as `exc` payload:
- `routes/provider_routing.py:255`
- `routes/snaptrade.py:899`
- `plaid_loader.py:1358`, `plaid_loader.py:1424`
- `snaptrade_loader.py:1344`, `snaptrade_loader.py:1416`, `snaptrade_loader.py:1493`

4. Correlation id passed as `key`:
- `plaid_loader.py:455`, `plaid_loader.py:549`
- Shape: `key=plaid_req_id`

## Local App Logging Duplication (Removed)

Removed duplicate local definitions from both files and now routed through `utils.logging`:
- `app.py` local `log_error_json/log_usage/log_request`
- `risk_module_secrets/app.py` local `log_error_json/log_usage/log_request`

## Current Compatibility Strategy

Compatibility wrappers remain for legacy decorators/helpers, but the `log_error_json` alias has been removed after callsite migration.

## Migration Progress (Phase 4)

Completed in this pass:
- All `log_error_json(...)` call sites were removed from non-test runtime files and migrated to explicit APIs (`log_error`, `log_alert`, `log_event`).
- `app.py` and `risk_module_secrets/app.py` key/tier semantics were migrated explicitly:
  - API keys/user keys -> `correlation_id`
  - user IDs -> `user_id`
  - sentinel `"ERROR"` patterns -> `context`
- Provider routing dict payload failures moved to `log_alert(...)`.
- Webhook receipt telemetry moved to `log_event(...)`.
- `risk_module_secrets/logging.py` duplicate implementation replaced with a re-export shim to `utils.logging`.

Remaining `log_error_json` references:
- none in `.py` sources (runtime or tests)

## Migration Progress (Phase 5)

Completed in this pass:
- Removed deprecated decorator callsites from all active `.py` sources:
  - `log_api_health`
  - `log_cache_operations`
  - `log_resource_usage_decorator`
  - `log_workflow_state_decorator`
- Renamed legacy decorator API usage to new names across callsites/imports:
  - `log_portfolio_operation_decorator` -> `log_operation`
  - `log_performance` -> `log_timing`
  - `log_error_handling` -> `log_errors`
- Removed deprecated decorator aliases from `utils/logging.py`.

Gate status:
- grep across `.py` (excluding `archive/` and `backup/`) for all deprecated symbols now returns zero.

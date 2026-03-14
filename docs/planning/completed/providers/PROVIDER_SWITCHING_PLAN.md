# Unified Provider Switching System — COMPLETE

**Status**: COMPLETE
**Commit**: `ef1215b0` (provider switching) + `c3ebb63c` (Schwab login fixes)
**Date**: 2026-02-16
**Tests**: 14 new + 99 total passing, zero regressions

## Context

Provider enablement is currently scattered across 4+ files with inconsistent gating:
- Plaid/SnapTrade: always on, no gate — cannot be disabled
- Schwab: `SCHWAB_ENABLED` checked independently in `position_service.py`, `data_fetcher.py`, `trade_execution_service.py`
- IBKR: `IBKR_ENABLED` checked in `trade_execution_service.py`; IBKR Flex gated by credential presence in `data_fetcher.py`
- `providers/routing.py` has `_is_provider_available()` but it's private and only used for institution routing dedup

There's also an old webapp-era `inputs/provider_settings_manager.py` (DB-backed, per-user) that is completely disconnected from the CLI/MCP pipeline.

**Goal**: Single source of truth for "is this provider active?" that ALL registration points use — including Plaid and SnapTrade.

## Approach

Promote `providers/routing.py` as the central authority. Add two public functions:
- `is_provider_enabled(name)` — user intent (should we register this provider?)
- `is_provider_available(name)` — runtime check (enabled AND credentials present?)

Add `ENABLED_PROVIDERS` env var as the primary config, with individual `_ENABLED` flags as fallback. When neither is set, Plaid/SnapTrade default to enabled (preserving current behavior).

## Codex Review — Addressed Items

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | HIGH | Plaid/SnapTrade/IBKR Flex always registered — not gated | Gate ALL providers through `is_provider_enabled()` at every registration point |
| 2 | HIGH | IBKR Flex independent of `IBKR_ENABLED`; tying them could break Flex-only setups | `ibkr_flex` is a separate key in `ENABLED_PROVIDERS`. In fallback mode, `ibkr_flex` checks credential presence (not `IBKR_ENABLED`) — preserving current behavior |
| 3 | MED | Schwab credential check only `APP_KEY`, but needs key+secret+token file | Credential check: `["SCHWAB_APP_KEY", "SCHWAB_APP_SECRET"]` + token file existence |
| 4 | MED | `fetch_ibkr_flex_trades(path=...)` bypasses env gating; new check could break | Keep `path` early-return before any availability check |
| 5 | HIGH | Tests miss registration behavior in constructors | Add integration tests for `PositionService.__init__`, `_build_default_transaction_registry`, `TradeExecutionService.__init__` |
| 6 | LOW | `_is_provider_available` alias unnecessary | Drop it — no external references exist |

## Changes

### 1. `settings.py` — Add credential map

Add near existing `IBKR_ENABLED`/`SCHWAB_ENABLED` block:
```python
PROVIDER_CREDENTIALS: dict[str, list[str]] = {
    "plaid": [],
    "snaptrade": [],
    "ibkr": [],
    "ibkr_flex": ["IBKR_FLEX_TOKEN", "IBKR_FLEX_QUERY_ID"],
    "schwab": ["SCHWAB_APP_KEY", "SCHWAB_APP_SECRET"],
}
```

Keep `IBKR_ENABLED` and `SCHWAB_ENABLED` as-is (backward compat fallback).

### 2. `providers/routing.py` — Central authority (main change)

Replace private `_is_provider_available` with three public functions:

**`is_provider_enabled(provider)`** — reads env at call time (testable via monkeypatch):
- If `ENABLED_PROVIDERS` env var is set (non-empty): provider must be in the comma-separated list
- If `ENABLED_PROVIDERS` not set (fallback mode):
  - `plaid`, `snaptrade` → always enabled
  - `schwab` → `SCHWAB_ENABLED=true`
  - `ibkr` → `IBKR_ENABLED=true`
  - `ibkr_flex` → credential presence (`IBKR_FLEX_TOKEN` AND `IBKR_FLEX_QUERY_ID`) — NOT tied to `IBKR_ENABLED` (preserves current behavior)

**`is_provider_available(provider)`** — `is_provider_enabled()` AND all credentials in `PROVIDER_CREDENTIALS[provider]` present. Special case for `schwab`: also checks token file exists (`SCHWAB_TOKEN_PATH`).

**`get_enabled_providers()`** — returns `[p for p in ALL_PROVIDERS if is_provider_enabled(p)]`.

Update `should_skip_for_provider()` to call `is_provider_available()` (drop old private function).

### 3. `services/position_service.py` (~line 100-112) — Gate ALL providers

Before (always registers plaid/snaptrade, conditionally schwab):
```python
position_providers = {
    "plaid": PlaidPositionProvider(),
    "snaptrade": SnapTradePositionProvider(),
}
if SCHWAB_ENABLED:
    position_providers["schwab"] = SchwabPositionProvider()
```

After (all gated):
```python
from providers.routing import is_provider_enabled

position_providers = {}
if is_provider_enabled("plaid"):
    position_providers["plaid"] = PlaidPositionProvider()
if is_provider_enabled("snaptrade"):
    position_providers["snaptrade"] = SnapTradePositionProvider()
if is_provider_enabled("schwab"):
    position_providers["schwab"] = SchwabPositionProvider()
```

### 4. `trading_analysis/data_fetcher.py` — Gate ALL transaction providers

**`_build_default_transaction_registry()`** (~line 298-312):
```python
from providers.routing import is_provider_enabled

registry = ProviderRegistry()
if is_provider_enabled("snaptrade"):
    registry.register_transaction_provider(SnapTradeTransactionProvider())
if is_provider_enabled("plaid"):
    registry.register_transaction_provider(PlaidTransactionProvider())
if is_provider_enabled("ibkr_flex"):
    registry.register_transaction_provider(IBKRFlexTransactionProvider())
if is_provider_enabled("schwab"):
    registry.register_transaction_provider(SchwabTransactionProvider())
return registry
```

**`fetch_ibkr_flex_trades()`** (~line 78-96) — keep `path` bypass first:
```python
def fetch_ibkr_flex_trades(path=None):
    if path:
        return _fetch_flex_trades(path=path)  # Local file — no gating
    from providers.routing import is_provider_available
    if not is_provider_available("ibkr_flex"):
        return []
    return _fetch_flex_trades(token=..., query_id=...)
```

### 5. `services/trade_execution_service.py` (line 27, 148-170)

Replace module-level import:
```python
# Before:
from settings import IBKR_ENABLED, SCHWAB_ENABLED, TRADING_DEFAULTS
# After:
from providers.routing import is_provider_enabled
from settings import TRADING_DEFAULTS
```

Gate ALL adapters in `__init__`:
```python
self._adapters: Dict[str, BrokerAdapter] = {}
if is_provider_enabled("snaptrade"):
    self._adapters["snaptrade"] = SnapTradeBrokerAdapter(...)
if is_provider_enabled("ibkr"):
    try:
        from services.ibkr_broker_adapter import IBKRBrokerAdapter
        self._adapters["ibkr"] = IBKRBrokerAdapter(user_email=user_email)
    except Exception as e:
        portfolio_logger.warning(f"Failed to initialize IBKR adapter: {e}")
if is_provider_enabled("schwab"):
    try:
        from services.schwab_broker_adapter import SchwabBrokerAdapter
        self._adapters["schwab"] = SchwabBrokerAdapter(user_email=user_email)
    except Exception as e:
        portfolio_logger.warning(f"Failed to initialize Schwab adapter: {e}")
```

### 6. `inputs/provider_settings_manager.py` — Docstring boundary

Add warning at top: "WEBAPP-ERA CODE — not used by CLI/MCP pipeline. For CLI/MCP provider switching, see `providers/routing.py`."

### 7. Tests — `tests/providers/test_provider_switching.py`

**Routing function tests (~8):**
1. `ENABLED_PROVIDERS=plaid,snaptrade` → schwab disabled even if `SCHWAB_ENABLED=true`
2. No `ENABLED_PROVIDERS` → falls back to individual flags
3. Plaid/SnapTrade enabled by default (no env vars needed)
4. `is_provider_available("ibkr_flex")` — enabled but missing credentials → False
5. `is_provider_available("ibkr_flex")` — enabled with credentials → True
6. `is_provider_available("schwab")` — checks token file existence
7. `get_enabled_providers()` returns correct list
8. Empty `ENABLED_PROVIDERS=""` → falls back (same as unset)
9. `ibkr_flex` fallback: enabled by credential presence, independent of `IBKR_ENABLED`

**Registration integration tests (~4):**
10. `PositionService.__init__` — only registers enabled providers (monkeypatch `ENABLED_PROVIDERS`)
11. `_build_default_transaction_registry` — only registers enabled providers
12. `TradeExecutionService.__init__` — only registers enabled adapters (mock adapters)
13. `should_skip_for_provider` still works with `is_provider_available`
14. `fetch_ibkr_flex_trades(path=...)` bypasses availability check (path early-return)

Update existing tests in `tests/providers/test_routing.py` — replace `_is_provider_available` references.

## .env Usage

```bash
# Option A: Unified (takes precedence when set)
ENABLED_PROVIDERS=plaid,snaptrade,schwab,ibkr,ibkr_flex

# Option B: Individual flags (fallback when ENABLED_PROVIDERS not set)
# plaid/snaptrade: always on
# ibkr_flex: on when credentials present
SCHWAB_ENABLED=true
IBKR_ENABLED=true

# Disable a default provider (only possible with Option A):
ENABLED_PROVIDERS=snaptrade,schwab   # no plaid
```

## Verification

1. `python3 -c "from providers.routing import get_enabled_providers; print(get_enabled_providers())"` — should list active providers
2. `python3 run_schwab.py positions` — still works
3. `python3 run_schwab.py transactions --days 30` — still works
4. `pytest tests/providers/test_provider_switching.py -v` — new tests pass
5. `pytest tests/providers/test_routing.py -v` — existing routing tests pass
6. `pytest tests/services/test_schwab_broker_adapter.py -v` — broker adapter tests pass
7. Verify: unset `ENABLED_PROVIDERS`, set `SCHWAB_ENABLED=true` → Schwab active, Plaid/SnapTrade active, IBKR Flex active only if credentials present

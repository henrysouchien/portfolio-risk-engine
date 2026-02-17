# IBKR Provider Package + Snapshot Pricing Plan

**Phase 0 COMPLETE** (2026-02-16). Phases 1-2 (snapshot pricing) pending.

## Overview

Restructure all IBKR code into a self-contained `ibkr/` provider package (mirroring `fmp/`), then add snapshot pricing. This makes IBKR a clean, swappable integration — separate from portfolio tools.

---

## Phase 0: Provider Package Refactor

### Goal
Move all IBKR-specific code from `services/` into a top-level `ibkr/` package. Callers import from `ibkr/compat.py` instead of reaching into `services/ibkr_*` directly.

### Current State (scattered)

```
services/
├── ibkr_data/
│   ├── __init__.py            # Re-exports: IBKRClient, IBKRMarketDataClient, compat fns, exceptions
│   ├── ibkr_client.py         # Unified facade (smart routing), defines _ibkr_shared_lock
│   ├── client.py              # IBKRMarketDataClient (reqHistoricalData)
│   ├── account.py             # Positions, account summary, PnL
│   ├── metadata.py            # Contract details, option chains
│   ├── contracts.py           # Contract resolvers (futures/FX/bond/option)
│   ├── profiles.py            # InstrumentProfile per instrument type
│   ├── cache.py               # Parquet+zstd disk cache
│   ├── compat.py              # Legacy compat functions
│   ├── exceptions.py          # 7 exception types
│   └── capabilities.py        # Capability descriptors
├── ibkr_connection_manager.py  # Singleton persistent connection
├── ibkr_flex_client.py         # Flex Query trade downloads
├── ibkr_historical_data.py     # Legacy (delegates to ibkr_data)
└── ibkr_broker_adapter.py      # Trade execution adapter (imports _ibkr_shared_lock)
```

### Target State

```
ibkr/                              # Self-contained provider package
├── __init__.py                    # Public API exports (match current ibkr_data/__init__.py parity)
├── client.py                      # IBKRClient facade (from ibkr_data/ibkr_client.py)
├── market_data.py                 # IBKRMarketDataClient (from ibkr_data/client.py)
├── flex.py                        # Flex Query client (from ibkr_flex_client.py)
├── connection.py                  # ConnectionManager (from ibkr_connection_manager.py)
├── account.py                     # Positions, account, PnL (from ibkr_data/account.py)
├── metadata.py                    # Contract details, chains (from ibkr_data/metadata.py)
├── contracts.py                   # Contract resolvers (from ibkr_data/contracts.py)
├── profiles.py                    # InstrumentProfile (from ibkr_data/profiles.py)
├── cache.py                       # Parquet+zstd cache (from ibkr_data/cache.py)
├── exceptions.py                  # All IBKR exceptions (from ibkr_data/exceptions.py)
├── capabilities.py                # Capability descriptors (from ibkr_data/capabilities.py)
├── locks.py                       # ibkr_shared_lock — stable public location for cross-module lock
├── compat.py                      # Clean interface for rest of app
└── exchange_mappings.yaml         # IBKR-specific YAML sections

ibkr_mcp_server.py                 # Own MCP server (like fmp_mcp_server.py)

services/
└── ibkr_broker_adapter.py         # STAYS — implements generic broker interface
                                   # imports lock from ibkr.locks (not private internals)
```

### Migration Map

| From | To | Notes |
|------|----|-------|
| `services/ibkr_data/__init__.py` | `ibkr/__init__.py` | Preserve export parity |
| `services/ibkr_data/ibkr_client.py` | `ibkr/client.py` | Facade; move `_ibkr_shared_lock` to `ibkr/locks.py` |
| `services/ibkr_data/client.py` | `ibkr/market_data.py` | Rename for clarity |
| `services/ibkr_data/account.py` | `ibkr/account.py` | |
| `services/ibkr_data/metadata.py` | `ibkr/metadata.py` | |
| `services/ibkr_data/contracts.py` | `ibkr/contracts.py` | |
| `services/ibkr_data/profiles.py` | `ibkr/profiles.py` | |
| `services/ibkr_data/cache.py` | `ibkr/cache.py` | |
| `services/ibkr_data/compat.py` | `ibkr/compat.py` | Expand to cover all caller needs |
| `services/ibkr_data/exceptions.py` | `ibkr/exceptions.py` | |
| `services/ibkr_data/capabilities.py` | `ibkr/capabilities.py` | |
| `services/ibkr_connection_manager.py` | `ibkr/connection.py` | |
| `services/ibkr_flex_client.py` | `ibkr/flex.py` | |
| `services/ibkr_historical_data.py` | DELETE | Legacy; ensure `ibkr/compat.py` covers all its exports first |
| `services/ibkr_data/` | DELETE | Entire directory removed after migration |
| `mcp_tools/ibkr.py` | Inline into `ibkr_mcp_server.py` | Own MCP server |
| `mcp_server.py` (4 IBKR tools) | REMOVE imports + registrations | Moved to ibkr_mcp_server.py |
| (new) | `ibkr/locks.py` | Stable lock location; `_ibkr_shared_lock` lives here |

### Thread Safety: Lock Migration

**Problem (Codex HIGH):** `_ibkr_shared_lock` is currently defined in `services/ibkr_data/ibkr_client.py` and imported by `services/ibkr_broker_adapter.py` as a private symbol. Moving files could break this or cause lock divergence.

**Solution:** Create `ibkr/locks.py` as the single source of truth. The lock is renamed from `_ibkr_shared_lock` to `ibkr_shared_lock` (public name, no underscore prefix) since it's now a proper public export:

```python
# ibkr/locks.py
"""Thread-safety locks shared across IBKR modules."""
import threading

ibkr_shared_lock = threading.Lock()
"""Serializes calls on the shared IBKRConnectionManager IB instance."""
```

Both `ibkr/client.py` and `services/ibkr_broker_adapter.py` import from `ibkr.locks`. No more private symbol cross-module imports.

### exchange_mappings.yaml Strategy

**Problem (Codex HIGH):** `utils/ticker_resolver.load_exchange_mappings()` is hardcoded to load from root `exchange_mappings.yaml`. IBKR sections are consumed via that shared loader in multiple places.

**Solution — single source of truth in `ibkr/`:**

1. **Phase 0a**: Create `ibkr/exchange_mappings.yaml` containing only IBKR sections (`ibkr_exchange_to_mic`, `ibkr_futures_to_fmp`, `ibkr_futures_exchanges`).
2. **Phase 0b**: Update all IBKR-internal loaders to read from `ibkr/exchange_mappings.yaml`:
   - `ibkr/contracts.py` — loads `ibkr_futures_exchanges` for ContFuture resolution
   - `ibkr/flex.py` — loads `ibkr_exchange_to_mic` for STK normalization
3. **Phase 0b**: External consumer (`core/realized_performance_analysis.py` loading `ibkr_futures_to_fmp`) switches to `ibkr/compat.py` helper:
   ```python
   # ibkr/compat.py
   def get_ibkr_futures_fmp_map() -> dict:
       """Load IBKR futures-to-FMP symbol mapping from ibkr/exchange_mappings.yaml."""
       ...
   ```
4. **Phase 0d**: Remove IBKR sections from root `exchange_mappings.yaml` (root retains only non-IBKR sections: `mic_to_fmp_suffix`, `us_exchange_mics`, `minor_currencies`, `currency_aliases`, etc.)

**`ibkr/exchange_mappings.yaml` is the single source of truth** for all IBKR-specific exchange/futures data. No duplication period — IBKR loaders switch to new file in the same pass that creates it.

### External Callers to Update

**Production code (files outside `ibkr/` and outside deleted modules):**

| File | Current Import | New Import |
|------|---------------|------------|
| `core/realized_performance_analysis.py` | `from services.ibkr_data.compat import ...` + root YAML `ibkr_futures_to_fmp` (~line 1611) | `from ibkr.compat import ...` + `from ibkr.compat import get_ibkr_futures_fmp_map` (replaces direct YAML load) |
| `trading_analysis/data_fetcher.py` | `from services.ibkr_flex_client import ...` | `from ibkr.compat import fetch_ibkr_flex_trades` |
| `services/ibkr_broker_adapter.py` | `from services.ibkr_connection_manager import ...` + `_ibkr_shared_lock` | `from ibkr.connection import ...` + `from ibkr.locks import ibkr_shared_lock` |
| `services/trade_execution_service.py` | `from services.ibkr_broker_adapter import ...` | No change (adapter stays in services/) |
| `run_ibkr_data.py` | `from services.ibkr_data.ibkr_client import ...` + profiles + root YAML futures loading | `from ibkr.client import IBKRClient` + `from ibkr.profiles import ...` + `from ibkr.compat import get_ibkr_futures_exchanges` for futures listing |
| `scripts/fetch_ibkr_trades.py` | `from services.ibkr_flex_client import normalize_flex_trades, ...` | `from ibkr.flex import normalize_flex_trades` (direct import — script uses low-level API) |
| `mcp_tools/ibkr.py` | `from services.ibkr_data.ibkr_client import IBKRClient` | Absorbed into `ibkr_mcp_server.py`; imports `from ibkr.client import IBKRClient` |

**No change needed (indirect consumers):**

| File | Why |
|------|-----|
| `trading_analysis/analyzer.py` | Consumes already-normalized flex payloads, no direct IBKR imports |
| `run_trading_analysis.py` | Goes through data_fetcher |
| `mcp_tools/performance.py` | Goes through realized_perf |
| `mcp_tools/tax_harvest.py` | Goes through data_fetcher |

**Internal/deleted module imports (handled implicitly during Phase 0a file creation):**

These cross-references exist within `services/ibkr_data/` and `services/ibkr_*.py` — they are resolved when the modules are copied into `ibkr/` and their imports rewritten to relative form. Listed here for completeness:
- `services/ibkr_data/ibkr_client.py:11` → `from services.ibkr_connection_manager import ...` → becomes `from ibkr.connection import ...`
- `services/ibkr_historical_data.py` → imports from `services.ibkr_data.compat` → file deleted entirely
- All `services/ibkr_data/` internal cross-imports → become relative `from .module import ...`

### Migration Strategy: Direct Cutover (No Shims)

Rather than maintaining compatibility shims (which add complexity and can mask incomplete migrations), Phase 0 uses a **direct cutover**:

1. Create `ibkr/` package with all modules
2. Update ALL callers (production + tests) in the same pass
3. Delete old files: `services/ibkr_data/` (entire directory), `services/ibkr_connection_manager.py`, `services/ibkr_flex_client.py`, `services/ibkr_historical_data.py`. Note: `services/ibkr_broker_adapter.py` is NOT deleted — it stays as the generic broker interface.
4. Run full test suite to verify

This is safe because:
- All callers are enumerated in the tables above (verified by Codex)
- The codebase is a single repo — no external consumers of `services.ibkr_*`
- Tests catch any missed import immediately

### ibkr/compat.py — The Clean Interface

All callers outside `ibkr/` import from here:

```python
"""Public interface for IBKR provider.

Most external code should import from here.
Exceptions: infrastructure-level code (broker adapter, CLI, MCP server)
may import directly from ibkr.client, ibkr.connection, ibkr.locks, ibkr.profiles, ibkr.flex
when they need specific low-level APIs not exposed through compat.
"""

# Market data pricing fallbacks
from ibkr.market_data import IBKRMarketDataClient
fetch_ibkr_monthly_close = ...        # futures pricing fallback
fetch_ibkr_fx_monthly_close = ...     # FX pricing fallback
fetch_ibkr_bond_monthly_close = ...   # bond pricing fallback
fetch_ibkr_option_monthly_mark = ...  # option pricing fallback

# Trade history
fetch_ibkr_flex_trades = ...          # Flex Query download + normalization

# Exchange mappings
get_ibkr_futures_fmp_map = ...        # IBKR futures root → FMP commodity symbol
get_ibkr_futures_exchanges = ...      # IBKR futures root → exchange + currency

# Client re-exports
from ibkr.client import IBKRClient
from ibkr.exceptions import *         # All IBKR exception types
```

### What Stays in services/

- `ibkr_broker_adapter.py` — implements generic `BrokerAdapter` interface for trade execution. Imports from `ibkr/` but lives at the services layer because it's the integration seam (swappable with `schwab_broker_adapter.py`, etc.)
- `trade_execution_service.py` — imports broker adapter (no change needed)

### Tests

**Move test files:**

| From | To |
|------|----|
| `tests/services/test_ibkr_client_facade.py` | `tests/ibkr/test_client.py` |
| `tests/services/test_ibkr_flex_client.py` | `tests/ibkr/test_flex.py` |
| `tests/services/test_ibkr_historical_data.py` | DELETE (legacy) → port critical scenarios (connection failure, missing mapping, caching) to `tests/ibkr/test_compat.py` |
| `tests/services/test_ibkr_data_client.py` | `tests/ibkr/test_market_data.py` |
| `tests/services/test_ibkr_data_cache.py` | `tests/ibkr/test_cache.py` |

**Update monkeypatch paths in moved tests:**
All `monkeypatch.setattr("services.ibkr_data....")` strings must update to `"ibkr...."`.

**Tests with IBKR references that stay in place (update imports only):**

| File | What to Update |
|------|---------------|
| `tests/trading_analysis/test_instrument_tagging.py` | Update `services.ibkr_flex_client` → `ibkr.flex` in imports and monkeypatch strings |
| `tests/core/test_realized_performance_analysis.py` | Update `services.ibkr_data.compat` → `ibkr.compat` AND `services.ibkr_historical_data` → `ibkr.compat` in imports and monkeypatch strings. **Notes:** (1) Legacy lock-serialization tests (~line 3284+) monkeypatch `services.ibkr_historical_data` internals — rewrite to target `ibkr.market_data`/`ibkr.locks` or remove if testing deleted code paths. (2) Tests monkeypatching `rpa.load_exchange_mappings` for futures mapping (~line 240, 2911) must switch to monkeypatching `ibkr.compat.get_ibkr_futures_fmp_map` (or the local wrapper in rpa that calls it). |

### MCP Server Migration

**Problem (Codex MED):** Removing IBKR tools from `mcp_server.py` means existing MCP clients configured for `portfolio-mcp` lose IBKR tools.

**Solution:** Claude Code MCP config update required. Add `ibkr-mcp` as a new server:

```bash
claude mcp add ibkr-mcp -- python ibkr_mcp_server.py
```

Document this in the migration steps. The `ibkr_mcp_server.py` follows the same pattern as `fmp_mcp_server.py` — standalone FastMCP server with stdout redirect, .env loading, tool registration.

---

## Phase 1: Snapshot Method

### Context

`reqHistoricalData` can't return daily bars for options (IBKR limitation). For interactive queries like "how much does a SLV put cost?" we need `reqMktData` with `snapshot=True` — a separate IBKR API endpoint that returns the latest quote for any security.

### Use Cases

1. **Option pricing for hedging** — "What does a SLV Jun 35 put cost? What's the delta?"
2. **Quick latest price** — Snapshot any security without pulling historical series.
3. **Option chain scanning** — Price multiple strikes at once to compare hedging costs.

### Add `fetch_snapshot()` to `ibkr/market_data.py`

```python
def fetch_snapshot(
    self,
    contracts: list[Contract],
    timeout: float = 5.0,
) -> list[dict]:
    """Snapshot current bid/ask/last/volume/greeks for one or more contracts.

    Uses reqMktData(snapshot=True). Returns one dict per contract with:
    - bid, ask, last, mid (computed)
    - volume, open_interest
    - For options: implied_vol, delta, gamma, theta, vega (from modelGreeks)
    """
```

Key decisions:
- `snapshot=True` — one-shot, no streaming subscription to manage
- Accepts pre-built `Contract` objects — callers are responsible for contract construction (MCP tools use `resolve_contract()` or build `Option()`/`Stock()` directly)
- Calls `qualifyContracts()` internally before requesting data (validates conId, exchange)
- Batch multiple contracts in a single connection (request all, sleep, collect all)
- **Partial failure handling**: each contract gets its own result dict. Failed contracts return `{"error": "..."}` instead of price fields. Caller receives full list — no exception on partial failure.
- **Timeout**: per-batch timeout (default 5s). After timeout, collect whatever data has arrived and return it. Contracts with no data within timeout get `{"error": "timeout"}`.
- **Generic ticks**: `"100,101,106"` for options (option volume, open interest, implied vol). Empty string for non-options.
- **Nullable fields**: greeks fields (`delta`, `gamma`, `theta`, `vega`, `implied_vol`) are `None` when IBKR doesn't return them (e.g., non-option securities or illiquid options). `open_interest` is `None` when not available.
- Thread safety: existing `_ibkr_request_lock`
- No caching (snapshots are real-time)

### Expose on facade

`ibkr/client.py` (IBKRClient) delegates `fetch_snapshot()` to market data client.

---

## Phase 2: MCP Tools on ibkr_mcp_server.py

### `get_ibkr_option_prices`

```python
def get_ibkr_option_prices(
    symbol: str,                    # Underlying, e.g. "SLV"
    expiry: str,                    # YYYYMMDD, e.g. "20260618"
    strikes: list[float],           # e.g. [30, 32, 35]
    right: str = "P",               # "P" or "C"
) -> dict:
    """Snapshot bid/ask/greeks for multiple option strikes.

    Returns per-strike: bid, ask, mid, last, implied_vol, delta, gamma, theta, vega.
    """
```

### `get_ibkr_snapshot`

```python
def get_ibkr_snapshot(
    symbol: str,
    sec_type: str = "STK",
    exchange: str = "SMART",
    currency: str = "USD",
) -> dict:
    """Snapshot latest price for any security."""
```

Both registered as `@mcp.tool()` on `ibkr_mcp_server.py`.

---

## Execution Order

### Phase 0: Provider Package Refactor (single atomic pass)

1. **Phase 0a — Create `ibkr/` package**: Copy all modules to new locations, create `ibkr/locks.py`, create `ibkr/exchange_mappings.yaml` (IBKR sections only), set up `ibkr/__init__.py` with export parity. Update all internal cross-references within `ibkr/` — this includes:
   - Relative imports (e.g., `from .market_data import ...` instead of `from .client import ...`)
   - `ibkr/client.py`: `from services.ibkr_connection_manager import IBKRConnectionManager` → `from ibkr.connection import IBKRConnectionManager`; `_ibkr_shared_lock` definition replaced with `from ibkr.locks import ibkr_shared_lock`
   - `ibkr/market_data.py`: internal `.cache`, `.contracts`, `.exceptions`, `.profiles` imports (already relative, just verify)
   - `ibkr/account.py`, `ibkr/metadata.py`: verify internal references use relative imports

2. **Phase 0b — Update all callers and tests**: Update every import in a single pass — production files AND test files together. This includes:
   - All files in the "External Callers to Update" table (production code)
   - Internal loader rewrites: `ibkr/contracts.py` and `ibkr/flex.py` switch YAML loading to `ibkr/exchange_mappings.yaml`; `core/realized_performance_analysis.py` switches to `ibkr.compat.get_ibkr_futures_fmp_map()`
   - Move `tests/services/test_ibkr_*.py` → `tests/ibkr/` and update all import paths + monkeypatch strings
   - Delete `tests/services/test_ibkr_historical_data.py` (legacy)
   - `tests/core/test_realized_performance_analysis.py` — update both `services.ibkr_data.compat` imports AND direct `services.ibkr_historical_data` references
   - `tests/trading_analysis/test_instrument_tagging.py` — update `services.ibkr_flex_client` → `ibkr.flex`
   - `scripts/fetch_ibkr_trades.py` — update to `from ibkr.flex import normalize_flex_trades` (preserves direct low-level API usage)

3. **Phase 0c — Create `ibkr_mcp_server.py`**: New standalone FastMCP server with the existing 4 IBKR tools only (market data, positions, account, contract). Remove IBKR tool imports and `@mcp.tool()` registrations from `mcp_server.py`. Remove `mcp_tools/ibkr.py` (absorbed into server). Snapshot tools are added later in Phase 2.

4. **Phase 0d — Clean up old files**: Delete `services/ibkr_data/` directory, `services/ibkr_connection_manager.py`, `services/ibkr_flex_client.py`, `services/ibkr_historical_data.py`. Remove IBKR sections from root `exchange_mappings.yaml`. **Pre-condition**: grep confirms no runtime reads of root YAML `ibkr_*` mapping keys remain.

5. **Phase 0e — Verify**: Run full test suite. Verify `ibkr_mcp_server.py` starts cleanly. Verify `mcp_server.py` (portfolio-mcp) starts cleanly without IBKR tools.

### Phase 1: Snapshot Method

6. **Add `fetch_snapshot()`** to `ibkr/market_data.py`, expose on `ibkr/client.py` facade.
7. **Add unit tests** for `fetch_snapshot()` in `tests/ibkr/test_market_data.py` — cover: timeouts, empty quotes, greeks extraction, multi-contract batching.

### Phase 2: Snapshot MCP Tools

8. **Add `get_ibkr_option_prices` + `get_ibkr_snapshot`** to `ibkr_mcp_server.py`.
9. **Run full test suite** to verify no regressions.
10. **Live test** snapshot pricing (SLV puts, etc.).

## Open Questions

- [x] ~~Regulatory snapshot vs regular snapshot?~~ → Regular snapshot. Regulatory costs $0.01/snap and is only needed outside market hours — not needed for our use case.
- [x] ~~Generic tick list?~~ → `"100,101,106"` for options (volume, OI, IV); empty for non-options. Resolved in fetch_snapshot spec above.
- [x] ~~Timeout — 5s default reasonable?~~ → Yes, 5s per-batch. Illiquid options may return partial data within timeout; documented as nullable fields.

## Codex Review Log

### Review 1 (2026-02-15)

8 findings addressed:

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | HIGH | `exchange_mappings.yaml` move breaks `load_exchange_mappings()` | Keep root YAML during transition; IBKR loaders switch to `ibkr/exchange_mappings.yaml`; external consumer uses `ibkr/compat.py` helper |
| 2 | HIGH | `_ibkr_shared_lock` private cross-module import breaks on move | New `ibkr/locks.py` as stable public location; both facade and adapter import from there |
| 3 | MED | Caller list incomplete — missing `mcp_tools/ibkr.py`, `scripts/fetch_ibkr_trades.py`, `run_ibkr_data.py` profiles, `trade_execution_service.py` | Added all direct importers to caller table |
| 4 | MED | `ibkr_historical_data.py` deletion not reconciled with remaining references | Added note: ensure `ibkr/compat.py` covers all exports before deletion; update test references |
| 5 | MED | Test migration incomplete — missing `test_instrument_tagging.py`, `test_realized_performance_analysis.py`, monkeypatch paths | Added "tests that stay in place" table + monkeypatch update note |
| 6 | LOW | `services/ibkr_data/__init__.py` not in migration map | Added to migration map with export parity note |
| 7 | LOW | `analyzer.py` has no direct IBKR imports, unnecessary churn | Moved to "no change needed" table with explanation |
| 8 | MED | MCP tool split needs rollout plan | Added MCP server migration section with `claude mcp add` instructions |

### Review 2 (2026-02-15)

4 findings addressed:

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | HIGH | Compatibility shims internally inconsistent — shim creation and deletion in same phase; shims don't cover submodule imports | Dropped shim approach entirely. Using direct cutover — all callers updated in same pass, no shim period needed (single repo, no external consumers) |
| 2 | MED | `ibkr_historical_data.py` deletion: test at `test_realized_performance_analysis.py:3284` still directly imports it | Explicitly added to Phase 0b caller update list — update both compat imports AND direct legacy-module references in tests |
| 3 | MED | `exchange_mappings.yaml` split underspecified — no declared source of truth or sync/removal timing | Clarified: `ibkr/exchange_mappings.yaml` is single source of truth, created in 0a, loaders switch in 0b, root IBKR sections removed in 0d. No duplication period |
| 4 | LOW | `scripts/fetch_ibkr_trades.py` uses `normalize_flex_trades` directly, not just `fetch_ibkr_flex_trades` | Added note in Phase 0b to preserve direct `normalize_flex_trades` behavior when updating script imports |

### Review 3 (2026-02-15)

4 findings addressed:

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | MED | Phase 0e/0f numbering mismatch for YAML removal timing | Fixed phase numbering to be consistent |
| 2 | MED | `normalize_flex_trades` migration not implementation-safe | Clarified `scripts/fetch_ibkr_trades.py` uses `from ibkr.flex import normalize_flex_trades` |
| 3 | MED | `test_instrument_tagging.py` actual import is `services.ibkr_flex_client` | Updated test migration table to reflect actual import path |
| 4 | LOW | Step overlap between 0b and 0d | Merged test updates into single step 0b |

### Review 4 (2026-02-15)

6 findings addressed:

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | HIGH | Lock naming inconsistent: `_ibkr_shared_lock` vs `ibkr_shared_lock` across plan sections | Standardized on `ibkr_shared_lock` (public, no underscore) throughout. Added explicit rename note in locks.py section |
| 2 | MED | `run_ibkr_data.py` loads IBKR futures from root YAML — plan only mentions import migration | Added `from ibkr.compat import get_ibkr_futures_exchanges` to caller table entry for `run_ibkr_data.py` |
| 3 | MED | `test_realized_performance_analysis.py` monkeypatches `services.ibkr_historical_data` internals — simple string swap won't work | Added explicit note that lock-serialization tests (~line 3284+) must be rewritten to target `ibkr.market_data`/`ibkr.locks` |
| 4 | LOW | Phase timing conflict: YAML cleanup listed as both 0e and 0d | Standardized to Phase 0d in all references |
| 5 | LOW | Direct-cutover text says delete `services/ibkr_*` but adapter must stay | Reworded to list exact files to delete, explicitly excluding `services/ibkr_broker_adapter.py` |
| 6 | LOW | Internal import rewrites not explicitly documented (e.g., `ibkr_client.py` → `ibkr_connection_manager`) | Added internal import rewrite checklist to Phase 0a |

### Review 5 (2026-02-15)

4 findings addressed:

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | MED | `core/realized_performance_analysis.py:1611` root YAML `ibkr_futures_to_fmp` not in caller table | Added explicit entry: `from ibkr.compat import get_ibkr_futures_fmp_map` replaces direct YAML load |
| 2 | MED | Deleting `test_ibkr_historical_data.py` without replacement test coverage | Added `tests/ibkr/test_compat.py` as replacement target — port critical scenarios (connection failure, missing mapping, caching) |
| 3 | LOW | "Complete List" section includes external callers only; internal/deleted module imports not called out | Renamed to "External Callers to Update", added "Internal/deleted module imports" subsection for auditability |
| 4 | LOW | Step numbering jumps from 5 to 7 | Renumbered Phase 1/2 steps to 6/7/8 |

### Review 6 (2026-02-15)

3 findings addressed:

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | MED | Phase 0c says "existing 4 + future snapshot tools" but Phase 2 adds snapshot later | Clarified Phase 0c migrates only existing 4 tools; snapshot tools added exclusively in Phase 2 |
| 2 | LOW | compat.py policy says "all external code" but caller table uses direct imports for infra code | Updated compat.py docstring to document exceptions: broker adapter, CLI, MCP server may use direct imports for low-level APIs |
| 3 | MED | Phase 1/2 lack test verification tasks | Added step 7 (unit tests for fetch_snapshot) and step 9 (full test suite) to Phases 1/2 |

### Review 7 (2026-02-15)

3 findings addressed:

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | MED | `fetch_snapshot()` API ambiguous — signature takes `list[Contract]` but also says "reuse resolve_contract()" | Clarified: `fetch_snapshot()` accepts pre-built Contract objects; callers (MCP tools) resolve contracts themselves |
| 2 | MED | Tests monkeypatching `rpa.load_exchange_mappings` for futures mapping not called out | Added explicit note (2) in test migration table for switching to `ibkr.compat.get_ibkr_futures_fmp_map` monkeypatching |
| 3 | LOW | Exception count says "8" but file has 7 | Fixed to "7 exception types" |

### Review 8 (2026-02-15)

4 findings addressed:

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | MED | Phase 0b doesn't list internal loader rewrites for exchange_mappings | Added explicit checklist items: `ibkr/contracts.py`, `ibkr/flex.py` switch to `ibkr/exchange_mappings.yaml`; rpa switches to compat helper. Phase 0d now has pre-condition grep verification. |
| 2 | MED | Snapshot output promises greeks/OI but generic tick config unresolved | Resolved: `"100,101,106"` for options, empty for non-options. All open questions now marked resolved. |
| 3 | MED | `fetch_snapshot()` lifecycle ambiguous (qualification, partial failure, timeout) | Specified: `qualifyContracts()` called internally; partial failures return per-contract `{"error": "..."}` dicts; per-batch 5s timeout with nullable fields for missing data. |
| 4 | LOW | Internal note says `ibkr_historical_data.py` delegates to `services.ibkr_data.client` but actually imports `services.ibkr_data.compat` | Fixed to match actual code. |

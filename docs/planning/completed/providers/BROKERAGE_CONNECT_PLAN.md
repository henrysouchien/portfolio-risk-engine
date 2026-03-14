# brokerage-connect: Pure Broker API Extraction ✅ Implemented 2026-02-23 | Shipped to GitHub 2026-02-23

**Public repo:** https://github.com/henrysouchien/brokerage-connect (latest tag: `v0.2.0`)
**PyPI:** https://pypi.org/project/brokerage-connect/
**Sync script:** `scripts/sync_brokerage_connect.sh`
**Deployment checklist:** `docs/DEPLOY.md`

## Context

The brokerage layer was built as part of the portfolio system. The original extraction plan (adapter-level) was put on hold because adapters are thin shells that delegate to deeply-coupled loader files. The goal is to make the system **extensible to new brokers** by separating the pure broker API layer from normalization/portfolio system code.

**Key insight:** The clean extraction boundary is at the **broker API client level**, not the adapter level. Extract SDK wrappers, auth, retry logic as self-contained clients; normalization (SecurityTypeService, type mappings, FMP enhancement) stays in monorepo.

**Three-layer architecture:**
1. **Pure Broker API** (moves to `brokerage/`): SDK calls, auth, retry, credential management, trading operations
2. **Normalization** (stays in monorepo): SecurityTypeService, FMP ticker resolution, type mappings, cash gap patching
3. **Portfolio System** (stays in monorepo): DB storage, PortfolioData conversion, user management, orchestration

---

## Package Structure

```
brokerage/
  __init__.py              # Public API re-exports
  _logging.py              # Logging shim (ibkr pattern: monorepo fallback -> stdlib)
  _vendor.py               # Vendored make_json_safe (~40 lines) + _to_float
  config.py                # Env-var config (ibkr pattern: dotenv + os.getenv)
  pyproject.toml           # Standalone pip install metadata

  # Core contracts
  trade_objects.py          # From core/trade_objects.py (all dataclasses + constants)
  broker_adapter.py         # From core/broker_adapter.py (BrokerAdapter ABC)

  # Schwab
  schwab/
    __init__.py
    client.py               # From schwab_client.py (305 lines, almost standalone)
    adapter.py              # From services/schwab_broker_adapter.py

  # SnapTrade
  snaptrade/
    __init__.py
    _shared.py              # Retry decorator, identity helpers, _extract_snaptrade_body, ApiException shim
    client.py               # Pure API: get_snaptrade_client + ~15 retry-wrapped SDK wrappers
    secrets.py              # AWS Secrets Manager: store/get/delete app creds + user secrets
    users.py                # User management: register, delete, get_user_id_from_email
    connections.py          # Connection management: create URL, list, health check, upgrade, remove
    trading.py              # Trading: search_symbol, preview, place, get_orders, cancel
    adapter.py              # From services/snaptrade_broker_adapter.py

  # IBKR (thin -- ibkr package already extracted)
  ibkr/
    __init__.py
    adapter.py              # From services/ibkr_broker_adapter.py + ibkr_to_common_status
```

---

## What Moves vs What Stays

### Moves into `brokerage/`

| Source | Destination | Lines | Notes |
|---|---|---|---|
| `core/trade_objects.py` | `brokerage/trade_objects.py` | 447 | `make_json_safe` -> vendored; explicit `__all__` including `_iso` |
| `core/broker_adapter.py` | `brokerage/broker_adapter.py` | 90 | Import rewire only |
| `schwab_client.py` | `brokerage/schwab/client.py` | 305 | 2 deps: logging -> shim, settings -> config |
| `services/schwab_broker_adapter.py` | `brokerage/schwab/adapter.py` | 617 | DB -> on_refresh callback |
| `services/ibkr_broker_adapter.py` | `brokerage/ibkr/adapter.py` | 606 | DB -> on_refresh; `settings` -> `config`; includes `ibkr_to_common_status` |
| `services/snaptrade_broker_adapter.py` | `brokerage/snaptrade/adapter.py` | 410 | DB -> on_refresh callback |
| `snaptrade_loader.py` (pure API only) | `brokerage/snaptrade/{_shared,client,secrets,users,connections,trading}.py` | ~800 | 35 pure API + 5 trading functions |

### Stays in monorepo

| File | What stays | Why |
|---|---|---|
| `snaptrade_loader.py` | Normalization functions (7): `normalize_snaptrade_holdings`, `consolidate_snaptrade_holdings`, `get_enhanced_security_type`, `fetch_snaptrade_holdings`, `_map_snaptrade_code_to_internal`, `convert_snaptrade_holdings_to_portfolio_data`, `load_all_user_snaptrade_holdings` | SecurityTypeService, FMP, PortfolioData deps |
| `plaid_loader.py` | Normalization + portfolio conversion only | Pure Plaid API/secrets/connection helpers extracted to `brokerage/plaid/` on 2026-02-24. See `docs/planning/PLAID_EXTRACTION_PLAN.md`. |
| `services/security_type_service.py` | Entire file (1,400 lines) | 5-tier classification with DB cache, not extractable |
| `services/trade_execution_service.py` | Entire file | DB-coupled orchestrator, consumes BrokerAdapter |

---

## Shim Files (3 new files in `brokerage/`)

### `brokerage/_logging.py`
Following `ibkr/_logging.py` pattern:
- Try `from utils.logging import portfolio_logger, trading_logger, log_error, log_portfolio_operation`
- Catch `Exception`, fallback to `logging.getLogger("brokerage.*")`
- Shim `log_error(module, operation, error)` as a no-op fallback
- Shim `log_portfolio_operation(...)` as a no-op fallback

### `brokerage/_vendor.py`
- Vendor `make_json_safe` from `utils/serialization.py` (lines 22-63)
- Guarded `pandas`/`numpy` imports for standalone portability
- Also include `_to_float` helper (used by snaptrade)

### `brokerage/config.py`
Following `ibkr/config.py` pattern:
- Auto-load `.env` from package dir and parent
- **IBKR:** `IBKR_READONLY`, `IBKR_AUTHORIZED_ACCOUNTS`, `IBKR_GATEWAY_HOST`, `IBKR_GATEWAY_PORT`
- **Schwab:** `SCHWAB_APP_KEY`, `SCHWAB_APP_SECRET`, `SCHWAB_TOKEN_PATH`, `SCHWAB_CALLBACK_URL`
- **SnapTrade:** `SNAPTRADE_CLIENT_ID`, `SNAPTRADE_CONSUMER_KEY`, `SNAPTRADE_ENVIRONMENT`
- **General:** `FRONTEND_BASE_URL` (for connection redirect URLs)

---

## Key Design Patterns

### `on_refresh` Callback

All three adapters use `database.get_db_session` only in `refresh_after_trade()` for cache invalidation. Replace with injectable callback:

```python
# In brokerage/schwab/adapter.py
class SchwabBrokerAdapter(BrokerAdapter):
    def __init__(self, user_email: str, on_refresh: Callable[[str], None] | None = None):
        self._on_refresh = on_refresh or (lambda account_id: None)

    def refresh_after_trade(self, account_id: str) -> None:
        invalidate_schwab_caches()
        try:
            self._on_refresh(account_id)
        except Exception as e:
            # Non-fatal: a successful trade should not fail due to cache refresh
            from brokerage._logging import portfolio_logger
            portfolio_logger.warning(f"on_refresh callback failed for {account_id}: {e}")
```

The monorepo consumer (`TradeExecutionService`) passes DB invalidation as a lambda when constructing adapters. Callback failures are logged but never propagate — a successful trade must not turn into an error because cache invalidation failed.

### `__all__` for Underscore Exports

`brokerage/trade_objects.py` must define an explicit `__all__` that includes `_iso`, since the IBKR adapter imports it directly (`from core.trade_objects import ..., _iso`). Without `__all__`, the re-export shim's `from brokerage.trade_objects import *` would silently drop underscore-prefixed names.

---

## Re-export Shims (backward compatibility)

Original files become thin re-export shims so **no consumer code changes**:

| Original file | Becomes |
|---|---|
| `core/broker_adapter.py` | `from brokerage.broker_adapter import BrokerAdapter` |
| `core/trade_objects.py` | `from brokerage.trade_objects import *` (with `__all__` including `_iso`) |
| `schwab_client.py` | `from brokerage.schwab.client import get_schwab_client, get_account_hashes, schwab_login, check_token_health, invalidate_schwab_caches, is_invalid_grant_error` |
| `services/schwab_broker_adapter.py` | `from brokerage.schwab.adapter import SchwabBrokerAdapter` |
| `services/ibkr_broker_adapter.py` | `from brokerage.ibkr.adapter import IBKRBrokerAdapter, ibkr_to_common_status` |
| `services/snaptrade_broker_adapter.py` | `from brokerage.snaptrade.adapter import SnapTradeBrokerAdapter` |
| `snaptrade_loader.py` (top) | Re-imports of extracted API functions (including `snaptrade_client` module-level global) + retains normalization code below |

### Monkeypatch Compatibility for Tests

Tests like `test_schwab_broker_adapter.py` patch module globals on `services.schwab_broker_adapter` (e.g. `monkeypatch.setattr(mod, "get_schwab_client", ...)`). A thin re-export shim breaks this because the real adapter code in `brokerage.schwab.adapter` uses its own module-level names, not the shim's.

**Solution:** Adapter shim files must re-import all names that tests patch, AND the adapter code must import those names from the shim-compatible location. Specifically, each adapter module should import its dependencies at module level (not lazy) so monkeypatch can intercept them. Tests that currently patch `services.schwab_broker_adapter.get_schwab_client` should be updated to patch `brokerage.schwab.adapter.get_schwab_client` instead.

**Per-phase test updates:**
- Phase 3 (Schwab): Update `tests/services/test_schwab_broker_adapter.py`:
  - Retarget monkeypatches from `services.schwab_broker_adapter` to `brokerage.schwab.adapter`
  - Rewrite `test_refresh_after_trade_invalidates_cache_and_db` — currently patches `get_db_session` directly on the adapter module (line 203). With `on_refresh` callback, test should instead: (a) pass a mock callback to the adapter constructor, (b) assert the callback was invoked with the account_id, (c) add a separate test for non-fatal failure (callback raises, adapter doesn't propagate)
- Phase 4b (SnapTrade): No adapter test file currently exists (`tests/services/test_snaptrade_broker_adapter.py` does not exist). Add basic adapter tests as part of this phase, or note as a coverage gap.
- Phase 5 (IBKR): No adapter test file currently exists (`tests/services/test_ibkr_broker_adapter.py` does not exist). Add basic adapter tests as part of this phase, or note as a coverage gap.

### `snaptrade_client` Module-Level Global

`routes/snaptrade.py` imports the `snaptrade_client` global variable from `snaptrade_loader.py` (~15 usages). After extraction, `snaptrade_loader.py` must re-export this global:

```python
# At top of snaptrade_loader.py (after extraction)
from brokerage.snaptrade.client import get_snaptrade_client

# Re-create the module-level client for backward compat
snaptrade_client = get_snaptrade_client()
```

Or if the global is initialized lazily, preserve that exact pattern in the remaining `snaptrade_loader.py`.

---

## Implementation Phases

### Phase 1: Foundation (no existing code touched)
Create `brokerage/` with shims and metadata:
- `brokerage/__init__.py`, `_logging.py`, `_vendor.py`, `config.py`
- Empty subpackages: `schwab/__init__.py`, `snaptrade/__init__.py`, `snaptrade/_shared.py`, `ibkr/__init__.py`
- `pyproject.toml` with optional deps per broker
- **Verify:** `python -c "from brokerage._logging import portfolio_logger"` works with fallback

### Phase 2: Trade objects + ABC
- Move `core/trade_objects.py` -> `brokerage/trade_objects.py`
  - Rewire `from utils.serialization import make_json_safe` -> `from brokerage._vendor import make_json_safe`
  - Add explicit `__all__` including `_iso` and all public names
- Move `core/broker_adapter.py` -> `brokerage/broker_adapter.py`
  - Rewire `from core.trade_objects import ...` -> `from brokerage.trade_objects import ...`
- Create re-export shims at `core/trade_objects.py` and `core/broker_adapter.py`
- **Shim parity checkpoint:** Verify `_iso` is accessible via `from core.trade_objects import _iso`
- **Verify:** `pytest tests/ -x` passes with zero consumer changes

### Phase 3: Schwab (cleanest extraction, template for pattern)
- Move `schwab_client.py` -> `brokerage/schwab/client.py`
  - Replace `from utils.logging import portfolio_logger` -> `from brokerage._logging import portfolio_logger`
  - Replace lazy `import settings` -> `from brokerage.config import SCHWAB_APP_KEY, SCHWAB_APP_SECRET, SCHWAB_TOKEN_PATH, SCHWAB_CALLBACK_URL`
- Move `services/schwab_broker_adapter.py` -> `brokerage/schwab/adapter.py`
  - Add `on_refresh` callback (non-fatal on failure)
  - Remove `from database import get_db_session`
  - Rewire imports to `brokerage.*`
- Create re-export shims at `schwab_client.py` and `services/schwab_broker_adapter.py`
- Wire `on_refresh` in `trade_execution_service.py`
- Update `tests/services/test_schwab_broker_adapter.py` to patch `brokerage.schwab.adapter` instead of `services.schwab_broker_adapter`
- **Verify:** `run_schwab.py` works, all schwab tests pass

### Phase 4a: SnapTrade API extraction (split from adapter move to reduce blast radius)
- Extract ~40 pure API functions from `snaptrade_loader.py` into:
  - `brokerage/snaptrade/_shared.py` — retry decorator, `handle_snaptrade_api_exception`, `_extract_snaptrade_body`, `_get_snaptrade_identity`, ApiException shim
  - `brokerage/snaptrade/client.py` — `get_snaptrade_client` + all `_*_with_retry` SDK wrappers
  - `brokerage/snaptrade/secrets.py` — AWS Secrets Manager functions
  - `brokerage/snaptrade/users.py` — user registration/deletion, `get_snaptrade_user_id_from_email`
  - `brokerage/snaptrade/connections.py` — connection management
  - `brokerage/snaptrade/trading.py` — trading operations (`search_snaptrade_symbol`, `preview_snaptrade_order`, `place_snaptrade_checked_order`, `get_snaptrade_orders`, `cancel_snaptrade_order`)
- Add re-imports at top of `snaptrade_loader.py` for backward compat (including `snaptrade_client` global)
- **Phase 4a export checklist** — every symbol the existing adapter imports from `snaptrade_loader` must be re-exported. The adapter (`services/snaptrade_broker_adapter.py`) currently imports these 10 names:
  - `_get_user_account_balance_with_retry` -> from `brokerage.snaptrade.client`
  - `_list_user_accounts_with_retry` -> from `brokerage.snaptrade.client`
  - `cancel_snaptrade_order` -> from `brokerage.snaptrade.trading`
  - `get_snaptrade_client` -> from `brokerage.snaptrade.client`
  - `get_snaptrade_orders` -> from `brokerage.snaptrade.trading`
  - `get_snaptrade_user_id_from_email` -> from `brokerage.snaptrade.users`
  - `get_snaptrade_user_secret` -> from `brokerage.snaptrade.secrets`
  - `place_snaptrade_checked_order` -> from `brokerage.snaptrade.trading`
  - `preview_snaptrade_order` -> from `brokerage.snaptrade.trading`
  - `search_snaptrade_symbol` -> from `brokerage.snaptrade.trading`
  All 10 must be available via re-imports in `snaptrade_loader.py` before Phase 4b moves the adapter.
- **Verify:** `snaptrade_loader.py` normalization functions still work, routes still see `snaptrade_client` global, `from snaptrade_loader import _list_user_accounts_with_retry` still works

### Phase 4b: SnapTrade adapter migration
- Move `services/snaptrade_broker_adapter.py` -> `brokerage/snaptrade/adapter.py`
  - Add `on_refresh` callback (non-fatal)
  - Rewire imports to `brokerage.*`
- Create re-export shim at `services/snaptrade_broker_adapter.py`
- Wire `on_refresh` in `trade_execution_service.py`
- Update `tests/services/test_snaptrade_broker_adapter.py` to patch `brokerage.snaptrade.adapter`
- **Verify:** snaptrade tests pass, trading flow works

### Phase 5: IBKR adapter
- Move `services/ibkr_broker_adapter.py` -> `brokerage/ibkr/adapter.py`
  - Include `ibkr_to_common_status` function (also imported by `trade_execution_service.py`)
  - Add `on_refresh` callback (non-fatal)
  - Replace `import settings` -> `from brokerage.config import IBKR_READONLY, IBKR_AUTHORIZED_ACCOUNTS, IBKR_GATEWAY_HOST, IBKR_GATEWAY_PORT`
  - `ibkr.connection` and `ibkr.locks` imports stay as-is (already extracted package)
- Create re-export shim at `services/ibkr_broker_adapter.py` — must export both `IBKRBrokerAdapter` AND `ibkr_to_common_status`
- Wire `on_refresh` in `trade_execution_service.py`
- Update `tests/services/test_ibkr_broker_adapter.py` to patch `brokerage.ibkr.adapter`
- **Verify:** IBKR tests pass

### Phase 6: Package finalization
- Finalize `brokerage/__init__.py` with clean public API
- Complete `pyproject.toml`
- Full test suite + standalone import verification
- **Verify:** `pip install ./brokerage` from clean venv outside monorepo, `from brokerage import BrokerAdapter` works standalone (see Phase 6 checklist below)

---

## Verification

### Per-phase checklist

Run only the checks applicable to the current phase. Do not proceed until all pass.

#### Phase 1 checks:
```bash
python -c "from brokerage._logging import portfolio_logger"
python -c "from brokerage._vendor import make_json_safe"
python -c "from brokerage.config import SCHWAB_APP_KEY, IBKR_READONLY, SNAPTRADE_CLIENT_ID"
pytest tests/ -x -v
```

#### Phase 2 checks (adds trade objects + ABC):
```bash
# New imports
python -c "from brokerage.trade_objects import BrokerAccount, OrderPreview, _iso"
python -c "from brokerage.broker_adapter import BrokerAdapter"
# Shim parity
python -c "from core.trade_objects import _iso, BrokerAccount, OrderPreview, OrderResult, OrderStatus, CancelResult"
python -c "from core.broker_adapter import BrokerAdapter"
# Full suite
pytest tests/ -x -v
# Grep audit
grep -rn "from utils\." brokerage/ --include='*.py' | grep -v _logging | grep -v _vendor  # must be empty
```

#### Phase 3 checks (adds Schwab):
```bash
# New imports
python -c "from brokerage.schwab.client import get_schwab_client, get_account_hashes"
python -c "from brokerage.schwab.adapter import SchwabBrokerAdapter"
# Shim parity
python -c "from schwab_client import get_schwab_client, get_account_hashes, schwab_login, check_token_health, invalidate_schwab_caches, is_invalid_grant_error"
python -c "from services.schwab_broker_adapter import SchwabBrokerAdapter"
# Full suite (includes updated monkeypatch tests)
pytest tests/ -x -v
# Stale import audit
grep -rn "from database import\|from settings import\|import settings" brokerage/ --include='*.py'  # must be empty
# Monkeypatch audit
grep -rn "schwab_broker_adapter as mod" tests/ --include='*.py'  # must reference brokerage.schwab.adapter
```

#### Phase 4a checks (adds SnapTrade API):
```bash
# New imports
python -c "from brokerage.snaptrade.client import get_snaptrade_client"
python -c "from brokerage.snaptrade.trading import search_snaptrade_symbol"
python -c "from brokerage.snaptrade.secrets import get_snaptrade_user_secret"
# Shim parity (re-exports from snaptrade_loader)
python -c "from snaptrade_loader import get_snaptrade_client, search_snaptrade_symbol, _list_user_accounts_with_retry"
python -c "from snaptrade_loader import snaptrade_client; assert snaptrade_client is not None or True"
# Full suite
pytest tests/ -x -v
```

#### Phase 4b checks (adds SnapTrade adapter):
```bash
# New imports
python -c "from brokerage.snaptrade.adapter import SnapTradeBrokerAdapter"
# Shim parity
python -c "from services.snaptrade_broker_adapter import SnapTradeBrokerAdapter"
# Full suite
pytest tests/ -x -v
```

#### Phase 5 checks (adds IBKR adapter):
```bash
# New imports
python -c "from brokerage.ibkr.adapter import IBKRBrokerAdapter, ibkr_to_common_status"
# Shim parity
python -c "from services.ibkr_broker_adapter import IBKRBrokerAdapter, ibkr_to_common_status"
# Full suite
pytest tests/ -x -v
# Final stale import audit (all of brokerage/)
grep -rn "from database import" brokerage/ --include='*.py'       # must be empty
grep -rn "from settings import" brokerage/ --include='*.py'       # must be empty
grep -rn "import settings" brokerage/ --include='*.py'            # must be empty
grep -rn "from utils\." brokerage/ --include='*.py' | grep -v _logging | grep -v _vendor  # must be empty
```

### Phase 6 checks (standalone package verification)

**Important:** Run from outside the monorepo to avoid accidentally resolving monorepo modules via CWD.

```bash
# Build and install in an isolated venv
python -m venv /tmp/brokerage-test-venv
source /tmp/brokerage-test-venv/bin/activate
pip install ./brokerage          # non-editable install (catches missing package data)
cd /tmp                          # ensure CWD is NOT the monorepo

# Verify fallback logging (no monorepo utils.logging available)
python -c "from brokerage._logging import portfolio_logger; portfolio_logger.info('standalone OK')"
# Verify core types
python -c "from brokerage import BrokerAdapter; print('BrokerAdapter OK')"
python -c "from brokerage.trade_objects import BrokerAccount, OrderPreview, _iso; print('trade_objects OK')"
# Verify config loads without monorepo settings.py
python -c "from brokerage.config import SCHWAB_APP_KEY, IBKR_READONLY; print('config OK')"

deactivate
rm -rf /tmp/brokerage-test-venv
```

Also run the full test suite one final time from the monorepo:
```bash
cd /path/to/risk_module
pytest tests/ -x -v
```

### Automated `on_refresh` tests (add during Phases 3-5)

Each adapter phase should include unit tests for the `on_refresh` callback wiring:

```python
# Example test pattern (adapt per adapter):
def test_on_refresh_callback_invoked():
    """Verify adapter calls on_refresh with the account_id."""
    called_with = []
    adapter = SchwabBrokerAdapter(user_email="test@x.com", on_refresh=called_with.append)
    adapter.refresh_after_trade("acct-123")
    assert called_with == ["acct-123"]

def test_on_refresh_failure_is_non_fatal():
    """Verify adapter logs but does not raise when on_refresh fails."""
    def _boom(account_id):
        raise RuntimeError("DB down")
    adapter = SchwabBrokerAdapter(user_email="test@x.com", on_refresh=_boom)
    adapter.refresh_after_trade("acct-123")  # should NOT raise

def test_on_refresh_default_is_noop():
    """Verify adapter works without on_refresh callback."""
    adapter = SchwabBrokerAdapter(user_email="test@x.com")
    adapter.refresh_after_trade("acct-123")  # should NOT raise
```

These tests verify the core contract: callback invocation, non-fatal failure, and default no-op. Add equivalent tests for `SnapTradeBrokerAdapter` (Phase 4b) and `IBKRBrokerAdapter` (Phase 5).

### Live smoke tests (manual, after full implementation)

These require active broker connections and should be run manually (not by Codex):

7. **Schwab live smoke test** — requires valid Schwab OAuth token:
   ```bash
   python run_schwab.py status           # token health check
   python run_schwab.py accounts         # list accounts via brokerage.schwab.client
   ```

8. **SnapTrade live smoke test** — requires SnapTrade credentials + connected user:
   ```bash
   python run_snaptrade.py connections --user-email <email>   # list brokerage connections
   python run_snaptrade.py health --user-email <email>        # check connection health
   ```

9. **IBKR live smoke test** — requires running IB Gateway:
   ```bash
   python run_ibkr_data.py account                            # fetch account summary
   python run_ibkr_data.py positions --account <acct>         # fetch positions
   ```

10. **End-to-end trading smoke test** — verify `TradeExecutionService` constructs adapters with `on_refresh` callbacks and the full preview/place/cancel flow works through the new package paths. This is the most important live test — it exercises the `on_refresh` wiring in `trade_execution_service.py`.

---

## Critical Files

| File | Role |
|---|---|
| `snaptrade_loader.py` | Largest extraction source (~40 functions to split) |
| `schwab_client.py` | Cleanest target (2 monorepo deps: logging + settings), template for pattern |
| `core/trade_objects.py` | Foundation types all adapters depend on; must export `_iso` via `__all__` |
| `services/ibkr_broker_adapter.py` | Contains `ibkr_to_common_status` used by `trade_execution_service.py` |
| `ibkr/_logging.py`, `ibkr/config.py` | Reference patterns for shims |
| `services/trade_execution_service.py` | Must wire `on_refresh` callbacks |
| `utils/serialization.py` (lines 22-63) | Source for vendored `make_json_safe` |
| `tests/services/test_schwab_broker_adapter.py` | Monkeypatch patterns that need updating |
| `routes/snaptrade.py` | Imports `snaptrade_client` global (~15 usages) |

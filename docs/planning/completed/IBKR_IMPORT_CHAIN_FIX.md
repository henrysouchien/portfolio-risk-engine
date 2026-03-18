# Fix: Break ibkr import chain causing startup crash

## Context

The risk_module backend crashes on startup because `nest_asyncio.apply()` throws `ValueError` on uvloop. The root cause is that `ibkr/__init__.py` eagerly imports `IBKRClient` → `connection.py` → module-level `apply_nest_asyncio_if_running_loop()` → crash. Since `settings.py:414` does `from ibkr.config import ...`, Python executes `ibkr/__init__.py` on every startup — and `settings.py` is imported everywhere.

**The pervasive path (via settings.py):**
```
app.py → settings.py:414 (from ibkr.config import ...)
→ ibkr/__init__.py:9 (from .client import IBKRClient)
→ ibkr/client.py:27 → ibkr/connection.py:32
→ apply_nest_asyncio_if_running_loop() → nest_asyncio.apply() → ValueError
```

Multiple app.py imports lead to settings.py (core/proxy_builder.py, inputs/portfolio_manager.py, services/portfolio_service.py, etc.), so this path is unavoidable without fixing `ibkr/__init__.py`.

**Additional paths:** `providers/normalizers/ibkr_statement.py:12` and `providers/ibkr_positions.py:18` import `normalize_strike` from `ibkr._vendor` (also triggers `ibkr/__init__.py`). `mcp_tools/options.py:10` has top-level `from ibkr.client import IBKRClient`.

## Changes

### 1. Make `ibkr/__init__.py` lazy (root fix)

Replace eager imports of heavy modules with `__getattr__`-based lazy loading. No callers use `from ibkr import IBKRClient` — all use `from ibkr.client import IBKRClient` — so this is safe.

**`ibkr/__init__.py`**
```python
# Keep lightweight imports that don't trigger connection.py:
from .exceptions import (...)
from .profiles import InstrumentProfile, get_profile, get_profiles

# Lazy-load heavy modules (client, market_data, compat):
def __getattr__(name):
    if name == "IBKRClient":
        from .client import IBKRClient
        return IBKRClient
    if name == "IBKRMarketDataClient":
        from .market_data import IBKRMarketDataClient
        return IBKRMarketDataClient
    # ... same for compat exports
    raise AttributeError(f"module 'ibkr' has no attribute {name!r}")
```

This breaks all startup paths through `ibkr/__init__.py` at once.

### 2. Redirect normalize_strike callers (2 files)

The canonical `normalize_strike` lives in `trading_analysis/symbol_utils.py`. External callers should use it instead of the vendored `ibkr._vendor` copy.

**`providers/normalizers/ibkr_statement.py:12`**
```python
- from ibkr._vendor import normalize_strike
+ from trading_analysis.symbol_utils import normalize_strike
```

**`providers/ibkr_positions.py:18`**
```python
- from ibkr._vendor import normalize_strike
+ from trading_analysis.symbol_utils import normalize_strike
```

### 3. Lazy-import IBKRClient in mcp_tools/options.py and chain_analysis.py

Both files have top-level `from ibkr.client import IBKRClient` but only use it inside function bodies. Move to lazy imports.

**`mcp_tools/options.py:10`** — used only at line 202
```python
- from ibkr.client import IBKRClient
  ...
  # line ~202, inside function body:
+ from ibkr.client import IBKRClient
  ibkr_client=IBKRClient(),
```

**`mcp_tools/chain_analysis.py:12`** — used only at lines 119 (type hint) and 335
```python
- from ibkr.client import IBKRClient
  ...
  # line ~335, inside function body:
+ from ibkr.client import IBKRClient
  client = IBKRClient()
```

Note: `mcp_server.py:165` imports `mcp_tools.chain_analysis` at startup, so this IS a startup path.

### 4. Fix test monkeypatch targets (3 files)

Tests monkeypatch `module.IBKRClient` on the module-level attribute. After making imports lazy, update patch targets.

**`tests/options/test_mcp_options.py:80`** — patches `options_tool.IBKRClient`
**`tests/options/test_chain_analysis.py:63,68`** — patches `chain_tool.IBKRClient`
**`tests/options/test_chain_pricing.py:25,30`** — patches `chain_tool.IBKRClient`

Fix: patch at the source `ibkr.client.IBKRClient` instead of the (now absent) module-level attribute.

### 5. Notes

- `ibkr/_vendor.py` stays as-is (used by `ibkr/flex.py` for standalone portability)
- `providers/normalizers/snaptrade.py` already imports from `trading_analysis.symbol_utils` (correct)
- User's manual try/except fix in `ibkr/asyncio_compat.py` stays as defense-in-depth
- `__all__` in `ibkr/__init__.py` stays the same for documentation purposes

## Files to modify
- `ibkr/__init__.py` — lazy `__getattr__` for heavy imports (lines 9-21)
- `providers/normalizers/ibkr_statement.py` — line 12
- `providers/ibkr_positions.py` — line 18
- `mcp_tools/options.py` — line 10 (move to line ~202)
- `mcp_tools/chain_analysis.py` — line 12 (move to line ~335)
- `tests/options/test_mcp_options.py` — line 80 (update monkeypatch target)
- `tests/options/test_chain_analysis.py` — lines 63, 68 (update monkeypatch target)
- `tests/options/test_chain_pricing.py` — lines 25, 30 (update monkeypatch target)

## Verification
1. Restart risk_module backend → confirm it starts healthy on port 5001
2. Run existing tests: `python -m pytest tests/providers/ tests/ibkr/ tests/mcp_tools/ tests/options/ -x -q`
3. Refresh frontend → confirm "unable to reach" banner is gone

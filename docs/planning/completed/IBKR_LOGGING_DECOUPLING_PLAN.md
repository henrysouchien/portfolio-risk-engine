# IBKR Package Logging Decoupling

**Date**: 2026-03-02
**Status**: COMPLETE (implemented in commit `6a6d171d`)

## Context

The `ibkr/` package is designed to be self-contained (like `fmp/`), but `ibkr/_logging.py` imports `portfolio_logger` and `trading_logger` from `utils.logging` — the main project's logging module. These are just standard Python loggers (`logging.getLogger("risk_module.portfolio")`) with no special behavior, but the import couples ibkr to the monorepo and the names don't make sense for an ibkr package.

The `_logging.py` shim already has a try/except fallback that creates standalone `ibkr.*` loggers, so the package works standalone. But the intent should be cleaner: ibkr should own its own logger, full stop.

## Approach

Replace `portfolio_logger` and `trading_logger` throughout ibkr/ with a single `logger` using `logging.getLogger("ibkr")`. Drop the `utils.logging` import entirely from `_logging.py`.

When running inside the monorepo, `ibkr` logs still propagate to the root logger (which has `app.log` and `debug.log` handlers from `utils/logging.py`), so no log output is lost. The only difference is the logger name in log lines changes from `[risk_module.portfolio]` to `[ibkr]` — arguably better for filtering.

## Changes

### `ibkr/_logging.py`
- Remove the try/except import of `utils.logging`
- Remove `_make_fallback_logger()` (no longer needed)
- Create a single `logger = logging.getLogger("ibkr")`
- Keep `log_event()` and `TimingContext` unchanged (ibkr-owned, no coupling)

```python
"""IBKR package logging."""

from __future__ import annotations

import logging
import sys
import time

logger = logging.getLogger("ibkr")

# Ensure at least stderr output when no root handlers are configured
# (standalone/CLI usage outside the monorepo).
if not logging.root.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)


def log_event(...):  # unchanged
    ...

class TimingContext:  # unchanged
    ...
```

### All ibkr/ files that import from `._logging`

Replace `portfolio_logger` → `logger` and `trading_logger` → `logger`:

| File | Current imports | New imports |
|------|----------------|-------------|
| `ibkr/connection.py` | `from ._logging import log_event, portfolio_logger, TimingContext` | `from ._logging import log_event, logger, TimingContext` |
| `ibkr/market_data.py` | `from ._logging import log_event, portfolio_logger, TimingContext` | `from ._logging import log_event, logger, TimingContext` |
| `ibkr/contracts.py` | `from ._logging import portfolio_logger` | `from ._logging import logger` |
| `ibkr/compat.py` | `from ._logging import portfolio_logger` | `from ._logging import logger` |
| `ibkr/flex.py` | `from ._logging import trading_logger` | `from ._logging import logger` |

Then rename all usages: `portfolio_logger.xxx(...)` → `logger.xxx(...)`, `trading_logger.xxx(...)` → `logger.xxx(...)`.

### `ibkr/server.py` — no changes
The MCP server imports from the main project by design (it's the integration layer, not part of the standalone package).

### Tests — `tests/ibkr/test_flex.py`

4 sites reference `flex_client.trading_logger.name` in `caplog.at_level()` calls (lines 287, 547, 580, 643). Update to `flex_client.logger.name`.

## Files Modified

| File | Change |
|------|--------|
| `ibkr/_logging.py` | Simplify to single `logger = logging.getLogger("ibkr")`, stderr fallback handler, remove `utils.logging` import |
| `ibkr/connection.py` | `portfolio_logger` → `logger` (~20 sites) |
| `ibkr/market_data.py` | `portfolio_logger` → `logger` (~15 sites) |
| `ibkr/contracts.py` | `portfolio_logger` → `logger` (2 sites) |
| `ibkr/compat.py` | `portfolio_logger` → `logger` (5 sites) |
| `ibkr/flex.py` | `trading_logger` → `logger` (~8 sites) |
| `tests/ibkr/test_flex.py` | `trading_logger` → `logger` (4 sites) |

## What Doesn't Change

- `log_event()` and `TimingContext` — ibkr-owned, no coupling
- `ibkr/server.py` — MCP integration layer, not part of standalone package
- Other ibkr/ coupling (`brokerage.futures` in `compat.py`, `utils.ticker_resolver` in `flex.py`, `settings` in `client.py`) — already guarded with try/except, separate scope
- Log output in monorepo — `ibkr` logger propagates to root, which has `app.log`/`debug.log` handlers. Standalone/CLI paths get stderr output via the fallback handler.

## Verification

1. `pytest tests/ibkr/` — all tests pass
2. `grep -r "portfolio_logger\|trading_logger" ibkr/ tests/ibkr/` — zero hits
3. `grep -r "from utils.logging" ibkr/` — zero hits

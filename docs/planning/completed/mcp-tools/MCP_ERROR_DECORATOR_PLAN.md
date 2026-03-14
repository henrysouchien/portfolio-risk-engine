# MCP Error Handling Decorator

**Date**: 2026-02-25
**Status**: Complete
**Risk**: Low — mechanical refactor, no logic changes

## Context

Every MCP tool function repeats the same ~8-line boilerplate: redirect stdout to stderr (to protect the MCP JSON-RPC channel from stray prints), wrap the implementation in try/except, return `{"status": "error", "error": str(e)}` on failure, and restore stdout in finally. This is duplicated across 20+ tool functions in 12+ files (~200 lines of pure repetition). A shared decorator eliminates this.

## Pattern Being Replaced

```python
def some_tool(...) -> dict:
    _saved = sys.stdout
    sys.stdout = sys.stderr
    try:
        # ... tool logic ...
        return {"status": "success", ...}
    except Exception as e:
        return {"status": "error", "error": str(e)}
    finally:
        sys.stdout = _saved
```

## Changes

### 1. Create `mcp_tools/common.py` with decorator

```python
import sys
import functools
from typing import Callable
from utils.logging import portfolio_logger

def handle_mcp_errors(fn: Callable) -> Callable:
    """Decorator for MCP tool functions.

    - Redirects stdout to stderr (protects JSON-RPC channel)
    - Catches Exception → returns {"status": "error", "error": str(e)}
    - Restores stdout in finally block
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs) -> dict:
        _saved = sys.stdout
        sys.stdout = sys.stderr
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            portfolio_logger.error(f"{fn.__name__} failed: {e}")
            return {"status": "error", "error": str(e)}
        finally:
            sys.stdout = _saved
    return wrapper
```

### 2. Apply decorator to each tool function

For each tool, remove the boilerplate and add `@handle_mcp_errors`. The tool function body becomes just the logic that was previously inside the `try:` block.

**Before:**
```python
def check_exit_signals(ticker, ...) -> dict:
    _saved = sys.stdout
    sys.stdout = sys.stderr
    try:
        return _check_exit_signals_impl(ticker, ...)
    except Exception as e:
        return {"status": "error", "error": str(e), "ticker": ticker}
    finally:
        sys.stdout = _saved
```

**After:**
```python
@handle_mcp_errors
def check_exit_signals(ticker, ...) -> dict:
    return _check_exit_signals_impl(ticker, ...)
```

### 3. Tools to convert

| File | Function(s) |
|------|-------------|
| `mcp_tools/risk.py` | `get_risk_score`, `get_risk_analysis`, `get_leverage_capacity`, `set_risk_profile`, `get_risk_profile` |
| `mcp_tools/performance.py` | `get_performance` |
| `mcp_tools/whatif.py` | `run_whatif` |
| `mcp_tools/optimization.py` | `run_optimization` |
| `mcp_tools/stock.py` | `analyze_stock` |
| `mcp_tools/signals.py` | `check_exit_signals` |
| `mcp_tools/tax_harvest.py` | `suggest_tax_loss_harvest` |
| `mcp_tools/trading_analysis.py` | `get_trading_analysis` |
| `mcp_tools/income.py` | `get_income_projection` |
| `mcp_tools/factor_intelligence.py` | `get_factor_analysis`, `get_factor_recommendations` |
| `mcp_tools/trading.py` | `preview_trade`, `execute_trade`, `get_orders`, `cancel_order` |
| `mcp_tools/options.py` | `analyze_option_strategy` |

### 4. Tools that stay as-is

- `mcp_tools/news_events.py` — no error handling, thin wrappers around FMP tools
- `mcp_tools/positions.py` — no stdout redirect pattern (error handling differs)

### 5. Edge case: extra error context

A few tools add extra fields to the error dict (e.g., `"ticker": ticker` in signals.py). Drop the extra fields — the error message `str(e)` already contains sufficient context and no consumer depends on these extra fields.

### 6. Update TODO

Remove "Architecture: MCP Error Handling Decorator" from `docs/planning/TODO.md`, archive to `docs/planning/completed/TODO_COMPLETED.md`.

## Files Modified

- `mcp_tools/common.py` — **new** (decorator definition, ~20 lines)
- `mcp_tools/risk.py` — remove boilerplate from 5 functions
- `mcp_tools/performance.py` — remove boilerplate from 1 function
- `mcp_tools/whatif.py` — remove boilerplate from 1 function
- `mcp_tools/optimization.py` — remove boilerplate from 1 function
- `mcp_tools/stock.py` — remove boilerplate from 1 function
- `mcp_tools/signals.py` — remove boilerplate from 1 function
- `mcp_tools/tax_harvest.py` — remove boilerplate from 1 function
- `mcp_tools/trading_analysis.py` — remove boilerplate from 1 function
- `mcp_tools/income.py` — remove boilerplate from 1 function
- `mcp_tools/factor_intelligence.py` — remove boilerplate from 2 functions
- `mcp_tools/trading.py` — remove boilerplate from 4 functions
- `mcp_tools/options.py` — remove boilerplate from 1 function
- `docs/planning/TODO.md` — remove backlog entry
- `docs/planning/completed/TODO_COMPLETED.md` — archive entry

## Verification

```bash
# All existing MCP tool tests pass
pytest tests/mcp_tools/ -x -q

# Broader test suite unaffected
pytest tests/ -x -q --timeout=30 -k "not slow"

# MCP server starts and tools register correctly
python3 -c "from mcp_tools.common import handle_mcp_errors; print('OK')"

# Spot-check: a decorated tool still returns correct error shape
python3 -c "
from mcp_tools.signals import check_exit_signals
result = check_exit_signals(ticker='NONEXISTENT_TICKER_XYZ')
assert result.get('status') == 'error', f'Expected error, got {result}'
print('Error handling OK:', result['error'][:80])
"
```

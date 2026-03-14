# Optimization MCP Tool Plan

> **Status:** COMPLETE — Implemented and tested
> **Tool name:** `run_optimization`
> **Server:** `portfolio-mcp`

---

## Overview

Expose portfolio optimization as an MCP tool. Wraps `optimize_min_variance()` and `optimize_max_return()` from `core/optimization.py` via the temp-file pattern used by `ScenarioService`.

## Codex Review Feedback (Addressed)

| # | Severity | Issue | Fix |
|---|----------|-------|-----|
| 1 | HIGH | `max_return` needs expected returns — not loaded by `_load_portfolio_for_analysis()` | Load expected returns from DB via `DatabaseClient.get_expected_returns()`. Return error if empty for max_return. |
| 2 | HIGH | `portfolio_data.get_weights()` returns empty for brokerage-derived data (no "weight" entries) | Use `result.optimization_metadata["original_weights"]` after optimization completes instead. |
| 3 | MED | Temp file leak if `create_risk_limits_temp_file()` fails after portfolio temp is created | Create both files inside a single try/finally block; track which files exist for cleanup. |
| 4 | MED | Summary field names don't match actual OptimizationResult (`original_weight`/`new_weight` not `original`/`new`) | Use actual field names from `get_weight_changes()` and `get_summary()`. |
| 5 | LOW | optimization_type mismatch: param says "min_variance" but metadata says "minimum_variance" | Use metadata value as-is from `get_summary()` — don't override. |
| 6 | LOW | Edge cases missing expected_returns failure mode | Added to edge cases list. |
| 7 | LOW | Cleanup swallows errors silently; ScenarioService logs them | Add logging.warning for cleanup failures. |
| 8 | HIGH (R2) | `optimize_max_return` metadata doesn't include `original_weights` (only min_variance does) | Patch `core/optimization.py:optimize_max_return()` to add `"original_weights": weights` to metadata dict. One-line fix. |

## Parameters

```python
def run_optimization(
    user_email: Optional[str] = None,          # Internal — passed as None from mcp_server.py
    optimization_type: Literal["min_variance", "max_return"] = "min_variance",
    portfolio_name: str = "CURRENT_PORTFOLIO",
    format: Literal["full", "summary", "report"] = "summary",
    use_cache: bool = True
) -> dict:
```

**MCP-exposed parameters** (in `mcp_server.py` wrapper):
- `optimization_type` — which optimizer to run
- `portfolio_name` — portfolio config for factor proxies/risk limits (default: `"CURRENT_PORTFOLIO"`)
- `format` — output detail level
- `use_cache` — use cached position data

**Hidden** (internal only):
- `user_email` — resolved from `RISK_MODULE_USER_EMAIL` env var

## Data Flow

```
run_optimization(optimization_type="min_variance")
    |
    v
_load_portfolio_for_analysis(user_email, portfolio_name, use_cache)  # Reuse from risk.py
    |-- PositionService.get_all_positions()
    |-- to_portfolio_data()
    |-- ensure_factor_proxies()
    v
Load risk limits via RiskLimitsManager  # Required for optimization constraints
    v
[max_return only] Load expected returns from DB via DatabaseClient
    |-- If empty/missing → return error with suggestion
    |-- If present → set portfolio_data.expected_returns
    v
Create temp files (both inside try/finally):
    |-- portfolio_data.create_temp_file()       -> temp_portfolio.yaml
    |-- portfolio_data.create_risk_limits_temp_file(risk_limits_data)  -> temp_risk_limits.yaml
    v
Call core function:
    |-- optimize_min_variance(temp_portfolio, temp_risk_limits)   # if min_variance
    |-- optimize_max_return(temp_portfolio, temp_risk_limits)     # if max_return
    v
OptimizationResult
    v
Get original weights from result.optimization_metadata["original_weights"]
    v
Format output:
    |-- "summary": result.get_summary() + top positions + weight changes
    |-- "full": result.to_api_response()
    |-- "report": result.to_formatted_report()
    v
{"status": "success", ...}
```

## Format Outputs

### Summary
```python
{
    "status": "success",
    "optimization_type": "minimum_variance",  # from get_summary(), not overridden
    "total_positions": 15,
    "largest_position": 0.25,
    "smallest_position": 0.001,
    "portfolio_metrics": {                     # present for max_return only
        "volatility_annual": 0.185,
        "volatility_monthly": 0.053,
        "herfindahl": 0.08
    },
    "top_positions": {"AAPL": 0.25, "MSFT": 0.20, ...},  # top 10
    "weight_changes": [                                     # top 5 changes
        {"ticker": "AAPL", "original_weight": 0.30, "new_weight": 0.25,
         "change": -0.05, "change_bps": -500},
        ...
    ]
}
```

### Full
```python
{
    "status": "success",
    **result.to_api_response()  # All fields from OptimizationResult
}
```

### Report
```python
{
    "status": "success",
    "report": result.to_formatted_report()  # CLI-formatted text
}
```

## Implementation Details

### Reusing `_load_portfolio_for_analysis`
Import from `mcp_tools.risk` — already handles user resolution, position fetching, PortfolioData conversion, and factor proxy loading. Note: it does NOT load expected returns (line 141 comment: "Expected returns NOT loaded — not needed for risk analysis/scoring").

### Expected Returns (max_return only)
For `max_return` optimization, expected returns are required for the QP objective function. Load from DB:
```python
if optimization_type == "max_return":
    from database import get_db_session
    from inputs.database_client import DatabaseClient
    with get_db_session() as conn:
        db_client = DatabaseClient(conn)
        expected_returns = db_client.get_expected_returns(user_id, portfolio_name)
    if not expected_returns:
        return {
            "status": "error",
            "error": "No expected returns configured for max_return optimization. "
                     "Set expected returns first (via estimate_expected_returns or set_expected_returns)."
        }
    portfolio_data.expected_returns = expected_returns
```

### Risk Limits Loading
Optimization requires risk limits (constraints for the QP solver). Load via `RiskLimitsManager`:
```python
risk_limits_data = RiskLimitsManager(
    use_database=True, user_id=user_id
).load_risk_limits(portfolio_name)
```
If no risk limits configured, return error (optimization needs constraints).

### Temp File Pattern
Follow `ScenarioService.analyze_what_if()` pattern:
1. Create both temp files inside a single try/finally to prevent leaks
2. Track which files were created for targeted cleanup
3. Log cleanup failures (don't silently swallow)

### Original Weights for Weight Changes
Do NOT use `portfolio_data.get_weights()` — it returns empty for brokerage-derived portfolios.
Instead, get original weights from the optimization result metadata:
```python
original_weights = result.optimization_metadata.get("original_weights", {})
```
The core optimization functions (`optimize_min_variance`, `optimize_max_return`) compute normalized weights via `standardize_portfolio_input()` and store them in `optimization_metadata["original_weights"]`.

### stdout Protection
Same pattern as all other MCP tools:
```python
_saved = sys.stdout
sys.stdout = sys.stderr
try:
    ...
finally:
    sys.stdout = _saved
```

## Edge Cases

1. **No risk limits configured** — return `{"status": "error", "error": "No risk limits configured..."}`
2. **Infeasible constraints** — optimizer raises `ValueError` — caught by try/except, returned as error
3. **Empty positions** — caught by `_load_portfolio_for_analysis()` guard
4. **No user configured** — caught by `_load_portfolio_for_analysis()` guard
5. **max_return with no expected returns** — return error with suggestion to set expected returns first
6. **Temp file creation failure** — catch and return error; cleanup any already-created files

## Files to Create/Modify

| File | Change |
|------|--------|
| `mcp_tools/optimization.py` | **NEW** — tool implementation (~130 lines) |
| `mcp_server.py` | Add import + `@mcp.tool()` wrapper |
| `mcp_tools/__init__.py` | Add import + `__all__` entry |
| `mcp_tools/README.md` | Add tool documentation |
| `core/optimization.py` | Add `"original_weights": weights` to max_return metadata (line ~193) |

## `mcp_tools/optimization.py` Structure

```python
"""
MCP Tool: run_optimization

Exposes portfolio optimization (min variance / max return) as an MCP tool.
"""

import sys
import os
import logging
from typing import Optional, Literal

from mcp_tools.risk import _load_portfolio_for_analysis
from inputs.risk_limits_manager import RiskLimitsManager
from core.optimization import optimize_min_variance, optimize_max_return

logger = logging.getLogger(__name__)


def run_optimization(
    user_email: Optional[str] = None,
    optimization_type: Literal["min_variance", "max_return"] = "min_variance",
    portfolio_name: str = "CURRENT_PORTFOLIO",
    format: Literal["full", "summary", "report"] = "summary",
    use_cache: bool = True
) -> dict:
    """[docstring]"""
    _saved = sys.stdout
    sys.stdout = sys.stderr
    try:
        # 1. Load portfolio (reuse risk.py helper)
        user, user_id, portfolio_data = _load_portfolio_for_analysis(
            user_email, portfolio_name, use_cache=use_cache
        )

        # 2. Load risk limits (required for optimization constraints)
        risk_limits_data = RiskLimitsManager(
            use_database=True, user_id=user_id
        ).load_risk_limits(portfolio_name)

        if risk_limits_data is None or risk_limits_data.is_empty():
            return {
                "status": "error",
                "error": f"No risk limits configured for portfolio '{portfolio_name}'. "
                         "Optimization requires risk limits as constraints."
            }

        # 3. Load expected returns for max_return (required for objective function)
        if optimization_type == "max_return":
            from database import get_db_session
            from inputs.database_client import DatabaseClient
            with get_db_session() as conn:
                db_client = DatabaseClient(conn)
                expected_returns = db_client.get_expected_returns(user_id, portfolio_name)
            if not expected_returns:
                return {
                    "status": "error",
                    "error": "No expected returns configured for max_return optimization. "
                             "Set expected returns first (via estimate_expected_returns or set_expected_returns)."
                }
            portfolio_data.expected_returns = expected_returns

        # 4. Create temp files and run optimization
        temp_portfolio_file = None
        temp_risk_file = None
        try:
            temp_portfolio_file = portfolio_data.create_temp_file()
            temp_risk_file = portfolio_data.create_risk_limits_temp_file(risk_limits_data)

            # 5. Run optimization
            if optimization_type == "min_variance":
                result = optimize_min_variance(temp_portfolio_file, temp_risk_file)
            else:
                result = optimize_max_return(temp_portfolio_file, temp_risk_file)

        finally:
            # Safe cleanup with logging (matches ScenarioService pattern)
            for path in [temp_portfolio_file, temp_risk_file]:
                if path:
                    try:
                        os.unlink(path)
                    except (FileNotFoundError, OSError) as e:
                        logger.warning("Failed to cleanup temp file %s: %s", path, e)

        # 6. Get original weights from optimization metadata (not portfolio_data.get_weights())
        original_weights = result.optimization_metadata.get("original_weights", {})

        # 7. Format response
        if format == "summary":
            summary = result.get_summary()
            summary["status"] = "success"
            summary["top_positions"] = result.get_top_positions(10)
            summary["weight_changes"] = result.get_weight_changes(original_weights, limit=5)
            return summary
        elif format == "full":
            response = result.to_api_response()
            response["status"] = "success"
            return response
        else:  # report
            return {
                "status": "success",
                "report": result.to_formatted_report()
            }

    except Exception as e:
        return {"status": "error", "error": str(e)}
    finally:
        sys.stdout = _saved
```

## `mcp_server.py` Addition

```python
from mcp_tools.optimization import run_optimization as _run_optimization

@mcp.tool()
def run_optimization(
    optimization_type: Literal["min_variance", "max_return"] = "min_variance",
    portfolio_name: str = "CURRENT_PORTFOLIO",
    format: Literal["full", "summary", "report"] = "summary",
    use_cache: bool = True
) -> dict:
    """
    Optimize portfolio weights to minimize risk or maximize return.

    Runs quadratic programming optimization on current brokerage positions
    subject to risk limits (volatility caps, concentration limits, factor
    beta constraints).

    Args:
        optimization_type: Optimization objective:
            - "min_variance": Find lowest-risk allocation within constraints
            - "max_return": Find highest-return allocation within constraints
                (requires expected returns to be configured)
        portfolio_name: Portfolio config name for factor proxies and risk limits
            (default: "CURRENT_PORTFOLIO").
        format: Output format:
            - "summary": Optimized weights, top changes, key metrics
            - "full": Complete optimization with all tables and checks
            - "report": Human-readable formatted report
        use_cache: Use cached position data when available (default: True).

    Returns:
        Optimization results with status field ("success" or "error").

    Examples:
        "Optimize my portfolio for minimum risk" -> run_optimization()
        "What's the max return portfolio?" -> run_optimization(optimization_type="max_return")
        "Show me the full optimization report" -> run_optimization(format="report")
    """
    return _run_optimization(
        user_email=None,
        optimization_type=optimization_type,
        portfolio_name=portfolio_name,
        format=format,
        use_cache=use_cache
    )
```

## Verification Steps

1. `from mcp_tools.optimization import run_optimization` — import succeeds
2. `run_optimization(format="summary")` — returns `{"status": "success", ...}` with top_positions and weight_changes
3. `run_optimization(format="full")` — returns complete API response with all tables
4. `run_optimization(format="report")` — returns formatted report text
5. `run_optimization(optimization_type="max_return", format="summary")` — returns summary (or error if no expected returns)
6. Error: no expected returns for max_return — returns `{"status": "error", "error": "No expected returns..."}`
7. Error: no risk limits — returns `{"status": "error", "error": "No risk limits configured..."}`

---

*Document created: 2026-02-07*
*Codex review R1: 2026-02-07 — 7 items addressed*
*Codex review R2: 2026-02-07 — 1 additional item: max_return missing original_weights in metadata → patch core/optimization.py*

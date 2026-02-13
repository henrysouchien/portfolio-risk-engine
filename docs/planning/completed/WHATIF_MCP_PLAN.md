# What-If MCP Tool Plan

> **Status:** COMPLETE — Implemented and tested
> **Tool name:** `run_whatif`
> **Server:** `portfolio-mcp`

---

## Overview

Expose portfolio what-if/scenario analysis as an MCP tool. Wraps `ScenarioService.analyze_what_if()` which supports both target weight allocation and delta changes.

## Codex Review Feedback (Addressed)

| # | Severity | Issue | Fix |
|---|----------|-------|-----|
| 1 | HIGH | `target_weights` described as "only specified tickers change" but core treats it as full replacement — normalizes to 100% | Fixed docstring: clarify target_weights defines the full target portfolio, not partial. Weights are normalized to sum to 100%. |
| 2 | HIGH | Proxy generation passes list to `ensure_factor_proxies` which expects set-like input | ScenarioService handles this internally (line 238-251). If it fails, exception is swallowed and analysis continues without industry exposure. Not a blocker — note in plan. |
| 3 | MED | `risk_limits_yaml` is required (not Optional) in `analyze_scenario()` — passing None will fail | Always load risk limits. If DB has none, fall back to default `risk_limits.yaml` file. Never pass None. |
| 4 | MED | Parameter typing too loose (`Optional[dict]`) | MCP schema limitation — FastMCP doesn't support `Dict[str, float]` annotations. Use `dict` with docstring guidance on expected format. |
| 5 | LOW | Unused import `_resolve_user_id` | Removed from imports. |
| 6 | LOW | Verification missing `format="full"` test | Added to verification steps. |
| 7 | HIGH (R2) | Proxy type mismatch in ScenarioService (list vs set) causes missing proxies for new tickers | Pre-existing bug in ScenarioService, not MCP scope. Note as known limitation — factor/industry exposure may be understated for new tickers. |
| 8 | MED (R2) | risk_limits_data can still be None if both DB and file fallback fail | Add explicit guard: if risk_limits_data is None after both attempts, return error. |

## Parameters

```python
def run_whatif(
    user_email: Optional[str] = None,          # Internal — passed as None from mcp_server.py
    target_weights: Optional[dict] = None,     # {"AAPL": 0.25, "SGOV": 0.15}
    delta_changes: Optional[dict] = None,      # {"AAPL": "+5%", "TSLA": "-200bp"}
    scenario_name: str = "What-If Scenario",
    portfolio_name: str = "CURRENT_PORTFOLIO",
    format: Literal["full", "summary", "report"] = "summary",
    use_cache: bool = True
) -> dict:
```

**MCP-exposed parameters** (in `mcp_server.py` wrapper):
- `target_weights` — target portfolio allocations as decimals. Defines the full target portfolio — weights are normalized to sum to 100%. (e.g., `{"AAPL": 0.25, "SGOV": 0.15, "MSFT": 0.60}`)
- `delta_changes` — relative changes from current weights (e.g., `{"AAPL": "+5%", "TSLA": "-200bp"}`)
- `scenario_name` — descriptive label for the scenario
- `portfolio_name` — portfolio config for factor proxies/risk limits
- `format` — output detail level
- `use_cache` — use cached position data

**Hidden** (internal only):
- `user_email` — resolved from `RISK_MODULE_USER_EMAIL` env var

## Data Flow

```
run_whatif(target_weights={"AAPL": 0.25, "SGOV": 0.15, "MSFT": 0.60})
    |
    v
_load_portfolio_for_analysis(user_email, portfolio_name, use_cache)  # Reuse from risk.py
    |-- PositionService.get_all_positions()
    |-- to_portfolio_data()
    |-- ensure_factor_proxies()
    v
Load risk limits via RiskLimitsManager  # Always load — core requires non-None
    |-- Try DB first
    |-- Fall back to default risk_limits.yaml if DB has none
    v
ScenarioService(cache_results=use_cache).analyze_what_if(
    portfolio_data,
    target_weights=target_weights,
    delta_changes=delta_changes,
    scenario_name=scenario_name,
    risk_limits_data=risk_limits_data
)
    v
WhatIfResult  (ScenarioService handles temp files internally)
    v
Format output:
    |-- "summary": result.get_summary() + factor comparison
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
    "scenario_name": "Tech Reduction",
    "risk_improvement": True,
    "concentration_improvement": True,
    "volatility_change": {
        "current": 0.185,
        "scenario": 0.162,
        "delta": -0.023
    },
    "concentration_change": {
        "current": 0.28,
        "scenario": 0.24,
        "delta": -0.04
    },
    "factor_variance_change": {
        "current": 0.62,
        "scenario": 0.61,
        "delta": -0.01
    },
    "factor_exposures": {           # from get_factor_exposures_comparison()
        "market": {"current": 1.05, "scenario": 0.95, "delta": -0.10},
        ...
    }
}
```

### Full
```python
{
    "status": "success",
    **result.to_api_response()  # Complete structured analysis
}
```

### Report
```python
{
    "status": "success",
    "report": result.to_formatted_report()  # CLI-formatted before/after comparison
}
```

## Implementation Details

### Reusing `_load_portfolio_for_analysis`
Import from `mcp_tools.risk` — provides user resolution, position fetching, PortfolioData conversion, and factor proxy loading.

### ScenarioService Handles Complexity
Unlike optimization, we don't need to manually create temp files. `ScenarioService.analyze_what_if()` handles:
- Input validation (exactly one of target_weights or delta_changes)
- Factor proxy generation for new tickers (note: passes list to `ensure_factor_proxies` — works in practice, failure is gracefully handled)
- Temp file creation and cleanup
- Cache management
- Core scenario analysis invocation

This means the MCP tool is relatively thin — it just loads the portfolio, loads risk limits, and delegates to ScenarioService.

### Risk Limits (Always Required)
The core `analyze_scenario()` function requires `risk_limits_yaml: str` (not Optional). It does `with open(risk_limits_yaml, "r")` which will fail on None.

Always load risk limits — use DB first, fall back to default file:
```python
risk_limits_data = None
try:
    risk_limits_data = RiskLimitsManager(
        use_database=True, user_id=user_id
    ).load_risk_limits(portfolio_name)
    if risk_limits_data is not None and risk_limits_data.is_empty():
        risk_limits_data = None
except Exception:
    pass

# Fallback: load from default file if DB had nothing
if risk_limits_data is None:
    risk_limits_data = RiskLimitsManager(
        use_database=False
    ).load_risk_limits(portfolio_name)
```

### target_weights Semantics
Important: `target_weights` defines the **full target portfolio**, not a partial override. The core normalizes weights to sum to 100%. If you pass `{"AAPL": 0.25}`, that means ~100% AAPL (after normalization), NOT "set AAPL to 25% and keep everything else."

For partial adjustments, use `delta_changes` instead (e.g., `{"AAPL": "+5%", "SGOV": "-5%"}`).

### Input Validation
ScenarioService already validates that exactly one of `target_weights` or `delta_changes` is provided. We add a pre-check at the MCP tool level for a better error message:
```python
if not target_weights and not delta_changes:
    return {"status": "error", "error": "Must provide either target_weights or delta_changes..."}
if target_weights and delta_changes:
    return {"status": "error", "error": "Provide only one of target_weights or delta_changes, not both."}
```

### stdout Protection
Same pattern as all other MCP tools.

## Edge Cases

1. **Neither target_weights nor delta_changes provided** — pre-check returns error with guidance
2. **Both provided** — pre-check returns error
3. **New tickers in scenario** — ScenarioService auto-generates factor proxies (graceful fallback on failure)
4. **Empty positions** — caught by `_load_portfolio_for_analysis()` guard
5. **No user configured** — caught by `_load_portfolio_for_analysis()` guard
6. **Invalid delta format** — core analysis raises error, caught by try/except
7. **No risk limits in DB** — falls back to default risk_limits.yaml file

## Files to Create/Modify

| File | Change |
|------|--------|
| `mcp_tools/whatif.py` | **NEW** — tool implementation (~110 lines) |
| `mcp_server.py` | Add import + `@mcp.tool()` wrapper |
| `mcp_tools/__init__.py` | Add import + `__all__` entry |
| `mcp_tools/README.md` | Add tool documentation |

## `mcp_tools/whatif.py` Structure

```python
"""
MCP Tool: run_whatif

Exposes portfolio what-if scenario analysis as an MCP tool.
"""

import sys
import logging
from typing import Optional, Literal

from mcp_tools.risk import _load_portfolio_for_analysis
from inputs.risk_limits_manager import RiskLimitsManager
from services.scenario_service import ScenarioService

logger = logging.getLogger(__name__)


def run_whatif(
    user_email: Optional[str] = None,
    target_weights: Optional[dict] = None,
    delta_changes: Optional[dict] = None,
    scenario_name: str = "What-If Scenario",
    portfolio_name: str = "CURRENT_PORTFOLIO",
    format: Literal["full", "summary", "report"] = "summary",
    use_cache: bool = True
) -> dict:
    """[docstring]"""
    _saved = sys.stdout
    sys.stdout = sys.stderr
    try:
        # 0. Input validation (better error message than ScenarioService)
        if not target_weights and not delta_changes:
            return {
                "status": "error",
                "error": "Must provide either target_weights or delta_changes. "
                         "target_weights defines the full target portfolio as decimals "
                         "(e.g., {'AAPL': 0.25, 'SGOV': 0.15, 'MSFT': 0.60}). "
                         "delta_changes adjusts current weights "
                         "(e.g., {'AAPL': '+5%', 'TSLA': '-200bp'})."
            }
        if target_weights and delta_changes:
            return {
                "status": "error",
                "error": "Provide only one of target_weights or delta_changes, not both."
            }

        # 1. Load portfolio (reuse risk.py helper)
        user, user_id, portfolio_data = _load_portfolio_for_analysis(
            user_email, portfolio_name, use_cache=use_cache
        )

        # 2. Load risk limits (required — core analyze_scenario needs non-None path)
        risk_limits_data = None
        try:
            risk_limits_data = RiskLimitsManager(
                use_database=True, user_id=user_id
            ).load_risk_limits(portfolio_name)
            if risk_limits_data is not None and risk_limits_data.is_empty():
                risk_limits_data = None
        except Exception:
            pass

        # Fallback: load from default file if DB had nothing
        if risk_limits_data is None:
            try:
                risk_limits_data = RiskLimitsManager(
                    use_database=False
                ).load_risk_limits(portfolio_name)
            except Exception:
                logger.warning("Could not load risk limits from DB or default file")

        # Guard: risk limits required for scenario analysis core function
        if risk_limits_data is None:
            return {
                "status": "error",
                "error": "Could not load risk limits from database or default file. "
                         "Scenario analysis requires risk limits."
            }

        # 3. Run scenario analysis (ScenarioService handles temp files + proxies)
        result = ScenarioService(cache_results=use_cache).analyze_what_if(
            portfolio_data,
            target_weights=target_weights,
            delta_changes=delta_changes,
            scenario_name=scenario_name,
            risk_limits_data=risk_limits_data
        )

        # 4. Format response
        if format == "summary":
            summary = result.get_summary()
            summary["status"] = "success"
            # Add factor exposure comparison
            try:
                summary["factor_exposures"] = result.get_factor_exposures_comparison()
            except Exception:
                pass
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
from mcp_tools.whatif import run_whatif as _run_whatif

@mcp.tool()
def run_whatif(
    target_weights: Optional[dict] = None,
    delta_changes: Optional[dict] = None,
    scenario_name: str = "What-If Scenario",
    portfolio_name: str = "CURRENT_PORTFOLIO",
    format: Literal["full", "summary", "report"] = "summary",
    use_cache: bool = True
) -> dict:
    """
    Analyze the risk impact of proposed portfolio allocation changes.

    Compares current portfolio against a proposed scenario with detailed
    before/after risk metrics, factor exposures, and compliance analysis.

    Two scenario modes (provide exactly one):
    - target_weights: Define the full target portfolio. Weights are normalized
      to sum to 100%. Include ALL tickers you want in the target portfolio.
    - delta_changes: Add/subtract from current weights for specific tickers.

    Args:
        target_weights: Full target portfolio allocations as decimals.
            Format: {"TICKER": weight} (e.g., {"AAPL": 0.25, "SGOV": 0.15, "MSFT": 0.60}).
            All specified tickers define the new portfolio (normalized to 100%).
        delta_changes: Relative changes from current weights.
            Format: {"TICKER": "change"} (e.g., {"AAPL": "+5%", "TSLA": "-200bp"}).
            Supports percentages, basis points, and decimals.
        scenario_name: Descriptive name for the scenario (default: "What-If Scenario").
        portfolio_name: Portfolio config name (default: "CURRENT_PORTFOLIO").
        format: Output format:
            - "summary": Key risk impact metrics and factor changes
            - "full": Complete before/after analysis with all fields
            - "report": Human-readable formatted comparison report
        use_cache: Use cached position data when available (default: True).

    Returns:
        What-if analysis results with status field ("success" or "error").

    Examples:
        "What if my portfolio was 25% AAPL, 15% SGOV, 60% MSFT?"
            -> run_whatif(target_weights={"AAPL": 0.25, "SGOV": 0.15, "MSFT": 0.60})
        "What if I increase AAPL by 5% and reduce SGOV by 5%?"
            -> run_whatif(delta_changes={"AAPL": "+5%", "SGOV": "-5%"})
        "Full scenario report"
            -> run_whatif(target_weights={...}, format="report")
    """
    return _run_whatif(
        user_email=None,
        target_weights=target_weights,
        delta_changes=delta_changes,
        scenario_name=scenario_name,
        portfolio_name=portfolio_name,
        format=format,
        use_cache=use_cache
    )
```

## Verification Steps

1. `from mcp_tools.whatif import run_whatif` — import succeeds
2. `run_whatif(target_weights={"AAPL": 0.25, "SGOV": 0.15, "MSFT": 0.60}, format="summary")` — returns summary with risk changes
3. `run_whatif(delta_changes={"AAPL": "+5%", "SGOV": "-5%"}, format="summary")` — returns summary with risk changes
4. `run_whatif(target_weights={...}, format="full")` — returns complete API response
5. `run_whatif(delta_changes={...}, format="report")` — returns formatted report
6. `run_whatif(format="summary")` — returns error (no weights/deltas)
7. `run_whatif(target_weights={"AAPL": 0.25}, delta_changes={"TSLA": "+5%"})` — returns error (both provided)

---

*Document created: 2026-02-07*
*Codex review R1: 2026-02-07 — 6 items addressed*
*Codex review R2: 2026-02-07 — 2 additional items: proxy type mismatch noted as pre-existing, risk_limits None guard added*

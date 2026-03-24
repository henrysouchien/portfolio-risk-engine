# Run Stress Test MCP Tool

## Context

The agent can manage stress scenarios via `manage_stress_scenarios` but can't run them. The building block `run_stress_test()` in `services/agent_building_blocks.py` (line 409) already handles portfolio loading, preset/custom scenarios, single/batch modes, and returns well-structured results. It just isn't exposed as an MCP tool. This is a thin wrapper — ~30 lines of new code.

## Design

### `mcp_tools/stress_test.py` (new)

```python
@handle_mcp_errors
def run_stress_test(
    scenario_name: str | None = None,
    custom_shocks: str | None = None,    # JSON string: '{"rate_10y": 0.02, "market": -0.15}'
    portfolio_name: str = "CURRENT_PORTFOLIO",
    user_email: str | None = None,
) -> dict:
    """Run a stress test on the portfolio."""
    from services.agent_building_blocks import run_stress_test as _bb_run_stress_test

    parsed_shocks = None
    if custom_shocks and custom_shocks.strip():
        raw = json.loads(custom_shocks)
        if not isinstance(raw, dict):
            return {"status": "error", "error": "custom_shocks must be a JSON object"}
        # Validate: finite numeric values only, no bools
        cleaned = {}
        for k, v in raw.items():
            if isinstance(v, bool):
                return {"status": "error", "error": f"Shock value for '{k}' must be numeric, got bool"}
            fv = float(v)
            if not math.isfinite(fv):
                return {"status": "error", "error": f"Shock value for '{k}' must be finite"}
            cleaned[str(k)] = fv
        if not cleaned:
            return {"status": "error", "error": "custom_shocks must contain at least one shock"}
        parsed_shocks = cleaned

    return _bb_run_stress_test(
        scenario_name=scenario_name,
        custom_shocks=parsed_shocks,
        portfolio_name=portfolio_name,
        user_email=user_email,
    )
```

Validation mirrors `manage_stress_scenarios` add action: rejects non-dict JSON, bools, NaN/Infinity, empty dicts. Malformed JSON raises `json.JSONDecodeError` caught by `@handle_mcp_errors`. (Codex R1 issue 1)

**Behavior (inherited from building block):**
- `scenario_name` only → runs that preset scenario
- `custom_shocks` only → runs custom stress test with those shocks
- Both → uses custom_shocks with scenario_name as label
- Neither → runs ALL configured scenarios (presets + any custom scenarios added via `manage_stress_scenarios`), returns sorted list

`custom_shocks` is a JSON string (MCP tools can't accept dicts directly from all clients). Parsed to dict before passing to building block.

### `mcp_server.py` — Registration

```python
from mcp_tools.stress_test import run_stress_test as _run_stress_test

@mcp.tool()
def run_stress_test(
    scenario_name: Optional[str] = None,
    custom_shocks: Optional[str] = None,
    portfolio_name: str = "CURRENT_PORTFOLIO",
) -> dict:
    """Run a preset or custom stress test on the current portfolio.

    Args:
        scenario_name: Scenario ID (e.g., "market_crash", "bear_flattener").
                       Omit to run all configured scenarios.
        custom_shocks: JSON dict of factor shocks (e.g., '{"rate_10y": 0.02, "market": -0.15}').
                       Overrides preset shocks if both provided.
        portfolio_name: Portfolio to stress test (default: current portfolio).

    Returns:
        Stress test results with portfolio impact, per-position breakdown,
        and factor contributions.

    Examples:
        "Stress test the portfolio against a market crash"
            -> run_stress_test(scenario_name="market_crash")
        "What happens if rates rise 200bp and markets drop 10%?"
            -> run_stress_test(custom_shocks='{"rate_10y": 0.02, "market": -0.10}')
        "Run all stress tests"
            -> run_stress_test()
    """
    return _run_stress_test(
        scenario_name=scenario_name,
        custom_shocks=custom_shocks,
        portfolio_name=portfolio_name,
        user_email=None,
    )
```

### Agent Registry — Already registered

The building block `run_stress_test` is already in the agent registry at `services/agent_registry.py:157`. The MCP tool wraps the same building block, so in-app agent access is already covered. No registry changes needed.

## Files to Modify

| File | Change |
|------|--------|
| `mcp_tools/stress_test.py` | **NEW** — thin wrapper (~30 lines) around building block |
| `mcp_server.py` | Register `run_stress_test` MCP tool |
| `tests/mcp_tools/test_stress_test_tool.py` | **NEW** — test preset, custom, all-scenarios modes, validation (malformed JSON, non-dict, empty dict, bool/NaN/Infinity shocks, invalid scenario name), no-portfolio error propagation |

## What Does NOT Change

- `services/agent_building_blocks.py` — untouched, tool wraps it
- `portfolio_risk_engine/stress_testing.py` — untouched
- `services/scenario_service.py` — untouched
- `services/agent_registry.py` — already has the building block registered
- Frontend — unchanged
- `manage_stress_scenarios` tool — separate, unchanged

## Verification

1. `pytest tests/mcp_tools/test_stress_test_tool.py -x -q` — new tests pass
2. MCP tool: `run_stress_test(scenario_name="market_crash")` → returns single result with impact
3. MCP tool: `run_stress_test(custom_shocks='{"rate_10y": 0.02, "market": -0.10}')` → custom stress
4. MCP tool: `run_stress_test()` → returns all configured scenarios sorted by impact
5. Full agent flow: create scenario → run it → interpret results in one conversation

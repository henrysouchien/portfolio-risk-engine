# Continuous Hedge Monitoring MCP Tool

## Context

TODO entry: "Continuous hedge monitoring — Alerts when portfolio drifts beyond hedge targets, hedge ratios become stale, or expiring options need rolling."

We have strong existing infrastructure: `compute_portfolio_greeks()` for live/B-S Greeks, `option_portfolio_flags.py` for basic Greeks alerts, `check_exit_signals()` as the architectural pattern (config-driven MCP tool + flags), and a full hedge workflow (discovery → preview → execute) already wired frontend-to-backend. What's missing is **ongoing monitoring** of existing hedge positions — expiry proximity, delta drift from targets, theta drain awareness, and rolling recommendations.

This tool is **reactive** (agent calls it), not proactive (no cron/push). The agent can call it during morning reviews, before trading, or on demand.

## Architecture

Three-layer agent format, mirroring `check_exit_signals`:
1. **Layer 1 (Snapshot)**: `_build_hedge_monitor_snapshot()` in `mcp_tools/hedge_monitor.py`
2. **Layer 2 (Flags)**: `generate_hedge_monitor_flags()` in `core/hedge_monitor_flags.py`
3. **Layer 3 (MCP)**: `monitor_hedge_positions()` registered in `mcp_server.py`

Data flow: `PositionService` → filter `is_option` → `compute_portfolio_greeks()` → expiry analysis → config threshold checks → snapshot → flags → agent response.

## Config Structure

In `mcp_tools/hedge_monitor.py`:

```python
HEDGE_MONITOR_CONFIG = {
    "_portfolio": {  # underscore prefix avoids ticker collision
        "expiry_tiers": [
            {"days": 7,  "severity": "error",   "label": "CRITICAL"},
            {"days": 14, "severity": "warning", "label": "SOON"},
            {"days": 30, "severity": "info",    "label": "APPROACHING"},
        ],
        "delta_target": 0.0,           # fraction of portfolio value (0 = neutral)
        "delta_tolerance": 0.10,       # flag when deviation exceeds this
        "theta_drain_threshold": -50.0, # $/day
        "vega_pct_threshold": 0.05,    # flag when abs(vega)/portfolio_value > 5%
        "roll_lookahead_days": 14,     # suggest rolls within this window
    },
    # Per-underlying overrides (optional, merge over defaults):
    # "SPY": {"delta_target": -0.20, "delta_tolerance": 0.05},
}
```

MCP params (`delta_target`, `delta_tolerance`, `roll_lookahead_days`) override config for ad-hoc use.

**Validation** (Codex review finding): Clamp invalid values at load time — `delta_tolerance = max(0, delta_tolerance)`, `roll_lookahead_days = max(0, roll_lookahead_days)`. Sort expiry tiers by `days` ascending (don't error, just sort).

## Snapshot Shape

```python
{
    "status": "success",  # top-level status is always "success" or "error"
                          # no-options is expressed via snapshot + no_options flag, not status
    "evaluated_at": "2026-03-06T10:30:00",
    "portfolio_value": 500000.0,
    "option_count": 8,
    "greeks": {  # full PortfolioGreeksSummary.to_dict() output
        "total_delta": -15000.0, "total_gamma": 200.0,
        "total_theta": -85.0, "total_vega": 3500.0,
        "position_count": 8, "failed_count": 0, "source": "ibkr",
        "by_underlying": { ... }  # per-underlying breakdown from PortfolioGreeksSummary
    },
    "delta_drift": {
        "target": 0.0, "current_ratio": -0.03,
        "deviation": 0.03, "tolerance": 0.10, "within_tolerance": True
    },
    "expiring_positions": [
        {"ticker": "SPY_P540_260320", "underlying": "SPY", "option_type": "put",
         "strike": 540.0, "expiry": "2026-03-20", "days_to_expiry": 14,
         "quantity": -5, "tier": "SOON", "tier_severity": "warning",
         "roll_recommended": True}
    ],
    # NOTE: by_underlying Greeks come from PortfolioGreeksSummary.by_underlying
    # nearest_expiry_days is derived separately from position expiry dates
    "by_underlying": {
        "SPY": {"delta": -12000.0, "gamma": 150.0, "theta": -60.0, "vega": 2800.0,
                "position_count": 5, "nearest_expiry_days": 14}
    },
    "roll_recommendations": [
        {"current_position": "SPY_P540_260320", "underlying": "SPY",
         "option_type": "put", "strike": 540.0, "current_expiry": "2026-03-20",
         "days_to_expiry": 14, "quantity": -5, "suggested_action": "ROLL",
         "reasoning": "Put expiring in 14 days, within roll window"}
    ],
    "verdict": "2 options expiring within 14 days need rolling. Theta drain -$85/day.",
    "overall_assessment": "ROLL_NEEDED"
    # Possible: OK, MONITOR, ROLL_NEEDED, DELTA_DRIFT, CRITICAL_EXPIRY, MULTIPLE_ALERTS
}
```

Roll recommendations are **directional hints** — agent follows up with `analyze_option_chain()` for target expiry/strike.

## Overlap with Existing Tools

There is intentional overlap with two existing flag sources. This tool **consolidates and extends** them into a single hedge-focused view:

| Existing source | What it does | How this tool differs |
|----------------|-------------|----------------------|
| `position_flags.py` → `expired_options`, `near_expiry_options` | Flags expired (DTE ≤ 0) and near-expiry (DTE ≤ 7) in `get_positions` | This tool adds 3-tier expiry classification (7/14/30 days), roll recommendations, and per-underlying breakdown |
| `option_portfolio_flags.py` → `theta_drain`, `significant_net_delta`, `high_vega_exposure` | Standalone flags module — exists but **not currently wired** into any MCP tool | This tool will be the first consumer of these flag concepts, adding delta **target** comparison (not just threshold), configurable per-underlying targets, and overall assessment verdict |

The `position_flags` expiry alerts remain in `get_positions` for general awareness (simple count-based). This tool is the **dedicated deep-dive** an agent calls when actively managing hedges — it provides 3-tier expiry classification, actionable roll recommendations, and drift-from-target analysis that the position flags don't cover. The `option_portfolio_flags.py` module is not currently wired into any tool — this tool subsumes its functionality with richer config and context.

## Flag Types

| Flag | Severity | Trigger |
|------|----------|---------|
| `critical_expiry` | error | Option(s) within 7 days |
| `delta_drift` | error | Net delta deviation exceeds tolerance |
| `roll_needed` | warning | Position(s) within roll lookahead window |
| `theta_drain` | warning | Total theta < -$50/day |
| `high_vega` | warning | Vega > 5% of portfolio value |
| `expiry_approaching` | info | Option(s) within 30 days (outside 14) |
| `greeks_failures` | info | Some positions failed Greeks computation |
| `no_options` | info | No option positions found in portfolio |
| `monitor_error` | error | Tool execution error (position load failed, etc.) |
| `hedges_ok` | success | No alerts triggered |

## Files to Create/Modify

### NEW: `core/hedge_monitor_flags.py`
- `generate_hedge_monitor_flags(snapshot: dict) -> list[dict]`
- `_sort_flags()` — severity ordering (error → warning → info → success)
- Mirrors `core/exit_signal_flags.py` structure

### NEW: `mcp_tools/hedge_monitor.py`
- `HEDGE_MONITOR_CONFIG` dict
- `_get_config(underlying=None)` — normalize `underlying` via `upper().strip()`, then merge: `{**config["_portfolio"], **config.get(normalized, {})}`
- `_load_option_positions(user_email)` — Call `PositionService(user_email).get_all_positions(consolidate=False)` to get per-account option detail from all providers. Filter result positions to `is_option=True and not option_parse_failed`. Uses `resolve_user_email()` / `format_missing_user_error()` for user resolution (same pattern as `signals.py`). Returns `(option_positions, portfolio_value)` tuple — `portfolio_value` from `PositionResult.total_value`.
- `_classify_expiry_tier(days_to_expiry, tiers)` — return (label, severity)
- `_compute_delta_drift(greeks, portfolio_value, config)` — compare to target
- `_identify_roll_candidates(positions, lookahead_days)` — DTE filter + sort
- `_build_verdict(snapshot)` — single-line summary + overall_assessment
- `_build_hedge_monitor_snapshot(result)` — compact snapshot for agent format
- `_save_full_hedge_monitor(result)` — save to `logs/hedge_monitor/`
- `monitor_hedge_positions(user_email, underlying, format, output, delta_target, delta_tolerance, roll_lookahead_days)` — public MCP function

**Format contract** (same as other agent tools):
- `"agent"` (default): `{status, format: "agent", snapshot: <compact>, flags: [...], file_path}`
- `"summary"`: `{status, verdict, overall_assessment, option_count, flags}`
- `"full"`: Full snapshot dict with all fields (expiring_positions, roll_recommendations, by_underlying, greeks, delta_drift)

Reuses: `compute_portfolio_greeks()`, `PositionService`, `@handle_mcp_errors`

**Codex review findings incorporated:**
- Use `resolve_user_email()` / `format_missing_user_error()` before `PositionService` (same as `signals.py`)
- Filter out `option_parse_failed=True` positions from expiry/roll analysis (they pass `is_option` but can't be analyzed). Note: `compute_portfolio_greeks` already excludes these internally.
- Guard `portfolio_value <= 0` in all ratio-based checks (delta drift, vega %)
- Include `file_path` in agent response shape for parity with other agent tools

### MODIFY: `mcp_server.py`
- Add import: `from mcp_tools.hedge_monitor import monitor_hedge_positions as _monitor_hedge_positions`
- Add `@mcp.tool()` wrapper with docstring, examples, type hints
- Follow `check_exit_signals` registration pattern

### NEW: `tests/core/test_hedge_monitor_flags.py`
- Test each flag at threshold boundary
- Test severity ordering
- Test `hedges_ok` only when no other flags
- Test error snapshot → `monitor_error`
- Test no-options snapshot (status `"success"`, option_count 0) → `no_options` info flag

### NEW: `tests/mcp_tools/test_hedge_monitor.py`
- Mock `PositionService` + `compute_portfolio_greeks`
- Test: no options, expiry tiers, delta drift, theta drain, roll candidates, underlying filter, config overrides, agent format shape, error handling
- Test missing user → proper error message
- Test `option_parse_failed` positions excluded from expiry/roll analysis
- Test `portfolio_value <= 0` → ratio checks skipped (no division by zero)
- Test `file_path` present in agent format response
- Test config validation: `delta_tolerance < 0` clamped to 0, `roll_lookahead_days < 0` clamped to 0, unsorted expiry tiers auto-sorted

## Implementation Sequence

1. Create `core/hedge_monitor_flags.py` (pure logic, no dependencies)
2. Create `tests/core/test_hedge_monitor_flags.py` — verify flags
3. Create `mcp_tools/hedge_monitor.py` with all helpers + MCP function
4. Create `tests/mcp_tools/test_hedge_monitor.py` — verify with mocks
5. Register in `mcp_server.py`
6. Run tests, `/mcp` reconnect, smoke test with live positions

## Verification

1. `python -m pytest tests/core/test_hedge_monitor_flags.py tests/mcp_tools/test_hedge_monitor.py -v`
2. `/mcp` reconnect → call `monitor_hedge_positions()` with live portfolio
3. Verify agent format response shape: `{status, format, snapshot, flags, file_path}`
4. With options present: verify expiry tiers, Greeks, roll recommendations
5. Without options: verify `no_options` info flag, top-level status `"success"`, empty snapshot lists

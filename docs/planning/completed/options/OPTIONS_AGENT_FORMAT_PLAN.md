# Options Strategy Agent Format Plan

_Status: **APPROVED** (Codex R3 PASS)_

## Scope

Add `format="agent"` + `output="file"` to `analyze_option_strategy()`. Same three-layer pattern. Result class: `StrategyAnalysisResult` in `options/result_objects.py`.

## Layer 1: `StrategyAnalysisResult.get_agent_snapshot()`

Add to `options/result_objects.py`:

```python
def get_agent_snapshot(self) -> dict:
    """Compact decision-oriented snapshot for agent consumption."""
    import math

    def _safe_float(val, default=0.0):
        if val is None:
            return default
        try:
            f = float(val)
            if f != f or math.isinf(f):  # NaN or inf
                return default
            return f
        except (TypeError, ValueError):
            return default

    max_profit = _safe_float(self.max_profit)
    max_loss = _safe_float(self.max_loss)
    rr_ratio = _safe_float(self.risk_reward_ratio)
    net_premium = _safe_float(self.net_premium)

    # Unlimited profit/loss markers
    profit_unlimited = self.max_profit is None
    loss_unlimited = self.max_loss is None

    # Verdict
    symbol = self.strategy.underlying_symbol or "N/A"
    if self.status != "success":
        verdict = f"Analysis failed: {self.error or 'unknown error'}"
    elif profit_unlimited and not loss_unlimited:
        verdict = f"{symbol}: unlimited profit potential, max loss ${abs(max_loss):.0f}, R:R={'unlimited' if rr_ratio == 0 else f'{rr_ratio:.2f}'}"
    elif loss_unlimited:
        verdict = f"{symbol}: max profit ${max_profit:.0f}, unlimited loss exposure"
    else:
        verdict = f"{symbol}: max profit ${max_profit:.0f}, max loss ${abs(max_loss):.0f}, R:R={rr_ratio:.2f}"

    # Aggregate greeks summary
    greeks = {}
    if self.aggregate_greeks:
        greeks = {
            "delta": _safe_float(self.aggregate_greeks.delta),
            "gamma": _safe_float(self.aggregate_greeks.gamma),
            "theta": _safe_float(self.aggregate_greeks.theta),
            "vega": _safe_float(self.aggregate_greeks.vega),
            "source": self.aggregate_greeks.source,
        }

    return {
        "underlying_symbol": symbol,
        "underlying_price": _safe_float(self.strategy.underlying_price),
        "verdict": verdict,
        "status": self.status,
        "max_profit": max_profit if not profit_unlimited else "unlimited",
        "max_loss": max_loss if not loss_unlimited else "unlimited",
        "risk_reward_ratio": rr_ratio,
        "net_premium": net_premium,
        "breakevens": [_safe_float(b) for b in self.breakevens[:5]],
        "aggregate_greeks": greeks,
        "leg_count": len(self.leg_analysis),
        "warning_count": len(self.warnings),
        "warnings": list(self.warnings[:3]),
    }
```

**Notes:**
- `max_profit`/`max_loss` can be `None` (unlimited) — snapshot uses string "unlimited" for agent clarity
- Breakevens capped at 5 (practical max for multi-leg strategies)
- Warnings capped at 3 in snapshot
- Verdict: natural language with symbol, profit/loss, and R:R

## Layer 2: `core/option_strategy_flags.py`

```python
def generate_option_strategy_flags(snapshot: dict) -> list[dict]:
    """Generate severity-tagged flags from option strategy snapshot."""
    flags = []

    status = snapshot.get("status", "success")
    if status != "success":
        flags.append({
            "flag": "analysis_error",
            "severity": "error",
            "message": f"Analysis failed: {snapshot.get('verdict', 'unknown error')}",
        })
        return _sort_flags(flags)

    max_profit = snapshot.get("max_profit", 0)
    max_loss = snapshot.get("max_loss", 0)
    rr_ratio = snapshot.get("risk_reward_ratio", 0)
    warning_count = snapshot.get("warning_count", 0)

    # Unlimited loss exposure
    if max_loss == "unlimited":
        flags.append({
            "flag": "unlimited_loss",
            "severity": "warning",
            "message": "Strategy has unlimited loss exposure — consider adding a protective leg",
        })

    # Risk/reward assessment
    if isinstance(max_loss, (int, float)) and isinstance(max_profit, (int, float)):
        if rr_ratio >= 3.0:
            flags.append({
                "flag": "favorable_risk_reward",
                "severity": "success",
                "message": f"Favorable risk/reward ratio of {rr_ratio:.2f}",
            })
        elif 0 < rr_ratio < 1.0:
            flags.append({
                "flag": "unfavorable_risk_reward",
                "severity": "warning",
                "message": f"Risk/reward ratio {rr_ratio:.2f} — risking more than potential profit",
            })
        elif rr_ratio == 0:
            # R:R is 0 when max_loss is 0 (undefined) — no risk capital
            flags.append({
                "flag": "zero_risk_capital",
                "severity": "info",
                "message": "No risk capital required (max loss is zero)",
            })
    elif max_profit == "unlimited":
        flags.append({
            "flag": "unlimited_profit_potential",
            "severity": "success",
            "message": "Strategy has unlimited profit potential",
        })

    # Greeks-based flags
    greeks = snapshot.get("aggregate_greeks", {})
    delta = greeks.get("delta", 0)
    theta = greeks.get("theta", 0)
    if isinstance(delta, (int, float)):
        if abs(delta) > 0.8:
            flags.append({
                "flag": "high_directional_exposure",
                "severity": "info",
                "message": f"Net delta {delta:.2f} — significant directional exposure",
            })
    if isinstance(theta, (int, float)):
        if theta < -5.0:
            flags.append({
                "flag": "high_theta_decay",
                "severity": "warning",
                "message": f"Daily theta decay ${theta:.2f} — time is working against this position",
            })

    # Warnings from analysis
    if warning_count > 0:
        flags.append({
            "flag": "has_warnings",
            "severity": "info",
            "message": f"{warning_count} analysis warning{'s' if warning_count != 1 else ''}",
        })

    # No issues at all
    if not flags:
        flags.append({
            "flag": "clean_analysis",
            "severity": "success",
            "message": "Strategy analysis complete with no concerns",
        })

    return _sort_flags(flags)


def _sort_flags(flags):
    order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    return sorted(flags, key=lambda f: order.get(f.get("severity", "info"), 2))
```

**Flag summary:**

| Flag | Severity | Condition |
|------|----------|-----------|
| `analysis_error` | error | `status != "success"` |
| `unlimited_loss` | warning | `max_loss == "unlimited"` |
| `unfavorable_risk_reward` | warning | 0 < R:R < 1.0 |
| `high_theta_decay` | warning | Theta < -5.0 |
| `high_directional_exposure` | info | abs(delta) > 0.8 |
| `has_warnings` | info | warning_count > 0 |
| `zero_risk_capital` | info | R:R == 0 (max_loss is 0) |
| `favorable_risk_reward` | success | R:R >= 3.0 |
| `unlimited_profit_potential` | success | max_profit == "unlimited" |
| `clean_analysis` | success | No other flags |

## Layer 3: MCP Composition in `mcp_tools/options.py`

### Helpers

```python
_OPTIONS_OUTPUT_DIR = Path("logs/options")

def _save_full_option_analysis(result):
    """Save full option analysis to disk and return absolute path."""
    _OPTIONS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    file_path = _OPTIONS_OUTPUT_DIR / f"options_{timestamp}.json"

    try:
        payload = result.to_api_response()
    except Exception:
        payload = {"status": result.status or "error"}
    if not isinstance(payload, dict):
        payload = {"status": "error"}
    payload["status"] = payload.get("status", "success")

    with file_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)

    return str(file_path.resolve())


def _build_option_strategy_agent_response(result, file_path=None):
    """Compose decision-oriented option analysis for agent use."""
    from core.option_strategy_flags import generate_option_strategy_flags

    snapshot = result.get_agent_snapshot()
    flags = generate_option_strategy_flags(snapshot)

    # Propagate error status from result
    response_status = "success" if result.status == "success" else "error"

    return {
        "status": response_status,
        "format": "agent",
        "snapshot": snapshot,
        "flags": flags,
        "file_path": file_path,
    }
```

### Modified `analyze_option_strategy()` function

- Add `"agent"` to format Literal
- Add `output: Literal["inline", "file"] = "inline"` parameter
- File save runs BEFORE format dispatch (applies to ALL formats)
- Agent format branch returns `_build_option_strategy_agent_response(result, file_path)`
- For summary/full/report, propagate `file_path` if set

### `mcp_server.py` changes

- Add `"agent"` to format Literal for `analyze_option_strategy`
- Add `output` parameter
- Pass through to `_analyze_option_strategy()`
- Add example: `"Agent briefing" -> analyze_option_strategy(format="agent")`

## Test Plan

### `tests/options/test_option_strategy_agent_snapshot.py`

1. **test_snapshot_success** — Valid result → verdict has symbol, max_profit, max_loss, R:R
2. **test_snapshot_unlimited_profit** — max_profit=None → "unlimited" in snapshot, verdict says "unlimited profit potential"
3. **test_snapshot_unlimited_loss** — max_loss=None → "unlimited" in snapshot
4. **test_snapshot_error_status** — status="error" → verdict says "Analysis failed"
5. **test_snapshot_greeks** — aggregate_greeks present → delta/gamma/theta/vega/source in snapshot
6. **test_snapshot_no_greeks** — aggregate_greeks=None → empty dict in snapshot
7. **test_snapshot_safe_float** — NaN/None/inf values → default 0.0
8. **test_snapshot_breakevens_capped** — 10 breakevens → 5 in snapshot
9. **test_snapshot_warnings_capped** — 5 warnings → 3 in snapshot

### `tests/core/test_option_strategy_flags.py`

10. **test_analysis_error_flag** — status != "success" → "analysis_error" error, early return
11. **test_unlimited_loss_flag** — max_loss="unlimited" → "unlimited_loss" warning
12. **test_favorable_rr_flag** — R:R=4.0 → "favorable_risk_reward" success
13. **test_unfavorable_rr_flag** — R:R=0.5 → "unfavorable_risk_reward" warning
14. **test_unlimited_profit_flag** — max_profit="unlimited" → "unlimited_profit_potential" success
15. **test_high_delta_flag** — delta=0.9 → "high_directional_exposure" info
16. **test_high_theta_flag** — theta=-10.0 → "high_theta_decay" warning
17. **test_has_warnings_flag** — 2 warnings → "has_warnings" info
18. **test_clean_analysis_flag** — No issues → "clean_analysis" success
19. **test_flag_sort_order** — error before warning before info before success
20. **test_zero_risk_capital_flag** — rr_ratio=0, both numeric → "zero_risk_capital" info
21. **test_boundary_rr_1_0** — R:R=1.0 → no unfavorable or favorable flag (falls through)
22. **test_boundary_rr_3_0** — R:R=3.0 → "favorable_risk_reward" success
23. **test_boundary_theta_minus_5** — theta=-5.0 → no flag (threshold is < -5.0)
24. **test_boundary_delta_0_8** — |delta|=0.8 → no flag (threshold is > 0.8)
25. **test_both_unlimited** — max_profit="unlimited", max_loss="unlimited" → both flags

### `tests/mcp_tools/test_option_strategy_agent_format.py`

26. **test_agent_response_structure** — Has status, format, snapshot, flags, file_path
27. **test_file_output_agent** — output="file" creates file, file_path set
28. **test_inline_no_file_path** — output="inline" → file_path is None
29. **test_file_output_summary** — format="summary", output="file" → file_path in response
30. **test_file_output_full** — format="full", output="file" → file_path in response
31. **test_file_output_report** — format="report", output="file" → file_path in response
32. **test_file_save_fallback** — to_api_response() raises → file still written with fallback
33. **test_agent_error_status** — Error result → response status="error", snapshot has error verdict, flags contains "analysis_error"

## Decisions

1. **Unlimited as string**: `None` profit/loss → `"unlimited"` string in snapshot (more explicit for agent than null).
2. **Greeks in snapshot**: Aggregate only (not per-leg). Per-leg detail available via full format + file output.
3. **R:R thresholds**: >= 3.0 favorable, < 1.0 unfavorable (common options trading heuristics).
4. **Theta threshold**: -5.0 daily (significant for most positions; $5/day time decay).
5. **Delta threshold**: |0.8| (near-directional exposure, strategy may as well be stock).
6. **Error handling**: Error results get `analysis_error` flag and early return (no other flags meaningful).

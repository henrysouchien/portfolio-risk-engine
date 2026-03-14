# Exit Signals Agent Format Plan

_Status: **APPROVED** (Codex R1 PASS)_

## Scope

Add `format="agent"` + `output="file"` to `check_exit_signals()`. Same three-layer pattern. No dedicated result class — the tool returns a raw dict. The snapshot and flags operate on this dict directly.

## Layer 1: `_build_exit_signals_snapshot()` (standalone function)

Since exit signals returns a raw dict (not a result object), Layer 1 is a standalone helper in `mcp_tools/signals.py` rather than a method on a result class.

```python
def _build_exit_signals_snapshot(result: dict) -> dict:
    """Compact decision-oriented snapshot from exit signals result dict."""
    import math

    def _safe_float(val, default=0.0):
        if val is None:
            return default
        try:
            f = float(val)
            if f != f or math.isinf(f):
                return default
            return f
        except (TypeError, ValueError):
            return default

    status = result.get("status", "error")
    ticker = result.get("ticker", "unknown")
    overall = result.get("overall_assessment", "UNKNOWN")

    # Error case
    if status != "success":
        return {
            "ticker": ticker,
            "status": status,
            "verdict": f"Exit signal check failed for {ticker}: {result.get('error', 'unknown error')}",
            "overall_assessment": overall,
            "signal_count": 0,
            "signals": [],
            "trade_eligible": False,
            "recommended_actions": [],
        }

    signals = result.get("signals", [])
    signal_summaries = []
    for s in signals[:5]:
        signal_summaries.append({
            "rule_name": s.get("rule_name", "unknown"),
            "triggered": s.get("triggered", False),
            "severity": _safe_float(s.get("severity")),
            "is_primary": s.get("is_primary", False),
            "status": s.get("status", "ok"),
        })

    trade_eligible = result.get("trade_eligible", False)
    actions = result.get("recommended_actions", [])
    action_summaries = []
    for a in actions[:3]:
        action_summaries.append({
            "action": a.get("action", "unknown"),
            "ticker": a.get("ticker", ticker),
            "quantity": a.get("quantity", 0),
            "order_type": a.get("order_type", "unknown"),
        })

    # Position summary
    position = result.get("position", {})
    shares = position.get("shares", 0)

    # Sizing summary
    sizing = result.get("sizing")
    sell_quantity = sizing.get("sell_quantity", 0) if sizing else 0

    # Verdict
    if trade_eligible and actions:
        verdict = f"{ticker}: {overall} — sell {sell_quantity} of {shares} shares"
    else:
        verdict = f"{ticker}: {overall}"

    return {
        "ticker": ticker,
        "status": status,
        "verdict": verdict,
        "overall_assessment": overall,
        "signal_count": len(signals),
        "signals": signal_summaries,
        "trade_eligible": trade_eligible,
        "recommended_actions": action_summaries,
        "shares": shares,
        "sell_quantity": sell_quantity,
    }
```

## Layer 2: `core/exit_signal_flags.py`

```python
def generate_exit_signal_flags(snapshot: dict) -> list[dict]:
    """Generate severity-tagged flags from exit signal snapshot."""
    flags = []

    status = snapshot.get("status", "error")
    if status != "success":
        flags.append({
            "flag": "signal_error",
            "severity": "error",
            "message": snapshot.get("verdict", "Exit signal evaluation failed"),
        })
        return _sort_flags(flags)

    overall = snapshot.get("overall_assessment", "")
    trade_eligible = snapshot.get("trade_eligible", False)
    signals = snapshot.get("signals", [])

    # Check for errored rules
    errored_rules = [s for s in signals if s.get("status") == "error"]
    if errored_rules:
        names = [s["rule_name"] for s in errored_rules]
        flags.append({
            "flag": "rule_evaluation_error",
            "severity": "warning",
            "message": f"Rule{'s' if len(names) != 1 else ''} failed to evaluate: {', '.join(names)}",
        })

    # Overall assessment flags
    if overall.startswith("STRONG EXIT"):
        flags.append({
            "flag": "strong_exit",
            "severity": "warning",
            "message": "Both momentum and regime signals triggered — strong exit signal",
        })
    elif overall.startswith("EXIT"):
        flags.append({
            "flag": "exit_signal",
            "severity": "warning",
            "message": "Primary momentum signal triggered — exit recommended",
        })
    elif overall.startswith("MONITOR"):
        flags.append({
            "flag": "monitor",
            "severity": "info",
            "message": "Secondary signal triggered — monitoring, no action yet",
        })
    elif overall.startswith("HOLD"):
        flags.append({
            "flag": "hold",
            "severity": "success",
            "message": "No exit signals triggered — position holds",
        })
    elif overall.startswith("ERROR"):
        flags.append({
            "flag": "primary_rule_error",
            "severity": "error",
            "message": "Primary rule failed — cannot determine exit status",
        })

    # Trade recommendation
    if trade_eligible and snapshot.get("sell_quantity", 0) > 0:
        qty = snapshot["sell_quantity"]
        total = snapshot.get("shares", 0)
        pct = (qty / total * 100) if total > 0 else 0
        flags.append({
            "flag": "trade_recommended",
            "severity": "info",
            "message": f"Recommended: sell {qty} shares ({pct:.0f}% of position)",
        })

    return _sort_flags(flags)


def _sort_flags(flags):
    order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    return sorted(flags, key=lambda f: order.get(f.get("severity", "info"), 2))
```

**Flag summary:**

| Flag | Severity | Condition |
|------|----------|-----------|
| `signal_error` | error | `status != "success"` |
| `primary_rule_error` | error | Overall starts with "ERROR" |
| `rule_evaluation_error` | warning | Any rule has status="error" |
| `strong_exit` | warning | Overall starts with "STRONG EXIT" |
| `exit_signal` | warning | Overall starts with "EXIT" |
| `monitor` | info | Overall starts with "MONITOR" |
| `trade_recommended` | info | trade_eligible and sell_quantity > 0 |
| `hold` | success | Overall starts with "HOLD" |

## Layer 3: MCP Composition in `mcp_tools/signals.py`

### Helpers

```python
_EXIT_SIGNALS_OUTPUT_DIR = Path("logs/exit_signals")

def _save_full_exit_signals(result):
    """Save full exit signal results to disk and return absolute path."""
    _EXIT_SIGNALS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ticker = result.get("ticker", "unknown")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = _EXIT_SIGNALS_OUTPUT_DIR / f"exit_signals_{ticker}_{timestamp}.json"

    try:
        import json
        with file_path.open("w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, default=str)
    except Exception:
        pass

    return str(file_path.resolve())


def _build_exit_signals_agent_response(result, file_path=None):
    """Compose decision-oriented exit signal result for agent use."""
    from core.exit_signal_flags import generate_exit_signal_flags

    snapshot = _build_exit_signals_snapshot(result)
    flags = generate_exit_signal_flags(snapshot)

    response_status = "success" if result.get("status") == "success" else "error"

    return {
        "status": response_status,
        "format": "agent",
        "snapshot": snapshot,
        "flags": flags,
        "file_path": file_path,
    }
```

### Modified `check_exit_signals()` and `_check_exit_signals_impl()`

- Add `"agent"` to format Literal on `check_exit_signals()`
- Add `output: Literal["inline", "file"] = "inline"` parameter
- Pass `output` through to `_check_exit_signals_impl()`
- In `_check_exit_signals_impl()`:
  - Add `output` parameter
  - After building `result` dict, add file save BEFORE format dispatch:
    ```
    file_path = _save_full_exit_signals(result) if output == "file" else None
    ```
  - Add agent format branch:
    ```
    if format == "agent":
        return _build_exit_signals_agent_response(result, file_path=file_path)
    ```
  - For existing summary/full branches, propagate file_path if set

### `mcp_server.py` changes

- Add `"agent"` to format Literal for `check_exit_signals`
- Add `output` parameter
- Pass through

## Test Plan

### `tests/mcp_tools/test_exit_signals_agent_snapshot.py`

1. **test_snapshot_success_hold** — No signals triggered → verdict "HOLD", trade_eligible=False
2. **test_snapshot_success_exit** — Primary triggered, actions present → verdict includes sell quantity
3. **test_snapshot_error** — status="error" → verdict mentions failure, signals=[]
4. **test_snapshot_signals_summarized** — Signals include rule_name, triggered, severity, is_primary, status
5. **test_snapshot_actions_capped** — 5 actions → 3 in snapshot
6. **test_snapshot_safe_float** — None/NaN severity → default 0.0

### `tests/core/test_exit_signal_flags.py`

7. **test_signal_error_flag** — status != "success" → "signal_error" error
8. **test_primary_rule_error_flag** — Overall "ERROR..." → "primary_rule_error" error
9. **test_strong_exit_flag** — Overall "STRONG EXIT..." → "strong_exit" warning
10. **test_exit_signal_flag** — Overall "EXIT..." → "exit_signal" warning
11. **test_monitor_flag** — Overall "MONITOR..." → "monitor" info
12. **test_hold_flag** — Overall "HOLD..." → "hold" success
13. **test_trade_recommended_flag** — trade_eligible, sell_quantity > 0 → "trade_recommended" info
14. **test_rule_evaluation_error_flag** — Rule with status="error" → "rule_evaluation_error" warning
15. **test_flag_sort_order** — error before warning before info before success
15a. **test_primary_errored_no_signal_error** — status="success" but overall "ERROR..." → "primary_rule_error" error, NOT "signal_error"

### `tests/mcp_tools/test_exit_signals_agent_format.py`

16. **test_agent_response_structure** — Has status, format, snapshot, flags, file_path
17. **test_file_output_agent** — output="file" creates file, file_path set
18. **test_inline_no_file_path** — output="inline" → file_path is None
19. **test_file_output_summary** — format="summary", output="file" → file_path in response
20. **test_file_output_full** — format="full", output="file" → file_path in response
21. **test_agent_error_propagation** — Error result → response status="error", flags has "signal_error"

## Decisions

1. **No result class**: Exit signals returns a raw dict. Snapshot is a standalone helper function, not a method.
2. **Overall assessment parsing**: Uses `startswith()` on the overall_assessment string since it's human-readable (HOLD, EXIT, STRONG EXIT, MONITOR, ERROR prefixes).
3. **Trade recommendation as info flag**: Not warning — the tool already decided the trade is appropriate.
4. **Sell percentage in flag**: Computed from shares/sell_quantity for agent readability.
5. **Actions capped at 3**: Typically only 2 (sell + stop), but future rules may add more.
6. **Signals capped at 5**: Currently 2 rules configured but extensible.

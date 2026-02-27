# Leverage Capacity Agent Format Plan

_Status: **APPROVED** (Codex R2 PASS)_

## Scope

Add `format="agent"` + `output="file"` to `get_leverage_capacity()`. Same three-layer pattern. No dedicated result class — tool returns a raw dict. The snapshot and flags operate on this dict directly.

**Note**: Unlike other tools where agent format dramatically reduces output size, here the main value is the **interpretive flags** (over-leveraged, binding constraint identification, headroom assessment). The raw output is already ~1.5KB, but an agent needs flags to decide if action is needed.

## Layer 1: `_build_leverage_snapshot()` (standalone function in `mcp_tools/risk.py`)

```python
def _build_leverage_snapshot(result: dict) -> dict:
    """Compact decision-oriented snapshot from leverage capacity result dict."""
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

    if status != "success":
        return {
            "status": status,
            "verdict": f"Leverage capacity analysis failed: {result.get('error', 'unknown error')}",
            "effective_leverage": 0,
            "max_leverage": 0,
            "headroom": 0,
            "headroom_pct": 0,
            "binding_constraint": None,
            "constraint_count": 0,
            "breached_constraints": [],
            "tightest_constraints": [],
            "invariant_failures": [],
            "warning_count": 0,
            "warnings": [],
        }

    effective = _safe_float(result.get("effective_leverage"))
    max_lev = _safe_float(result.get("max_leverage"))
    headroom = _safe_float(result.get("headroom"))
    headroom_pct = _safe_float(result.get("headroom_pct"))
    binding = result.get("binding_constraint")

    constraints = result.get("constraints", {})
    constraint_count = len(constraints)

    # Identify breached and tightest constraints
    breached = []
    tightest = []
    for name, c in constraints.items():
        h = _safe_float(c.get("headroom"))
        entry = {
            "constraint": name,
            "max_leverage": round(_safe_float(c.get("max_leverage")), 2),
            "headroom": round(h, 2),
        }
        if h < 0:
            breached.append(entry)
        tightest.append(entry)

    # Sort tightest by headroom ascending (most constrained first), take top 3
    tightest.sort(key=lambda x: x["headroom"])
    tightest = tightest[:3]
    breached.sort(key=lambda x: x["headroom"])

    # Invariant limits (pass/fail, not scaling)
    invariant = result.get("invariant_limits", {})
    invariant_failures = []
    for name, inv in invariant.items():
        if not inv.get("pass", True):
            invariant_failures.append({
                "limit": name,
                "actual": round(_safe_float(inv.get("actual")), 3),
                "limit_value": round(_safe_float(inv.get("limit")), 3),
            })

    # Core warnings (e.g. "No beta checks available... constraint skipped")
    warnings = result.get("warnings", [])

    # Verdict
    if headroom >= 0:
        verdict = (
            f"Leverage {effective:.2f}x within capacity ({max_lev:.2f}x max), "
            f"{headroom_pct * 100:.0f}% headroom"
        )
    else:
        breach_count = len(breached)
        verdict = (
            f"Over-leveraged: {effective:.2f}x vs {max_lev:.2f}x max "
            f"({abs(headroom_pct) * 100:.0f}% over), "
            f"constrained by {binding or 'unknown'}"
        )
        if breach_count > 1:
            verdict += f" + {breach_count - 1} other breach{'es' if breach_count > 2 else ''}"

    return {
        "status": status,
        "verdict": verdict,
        "effective_leverage": round(effective, 2),
        "max_leverage": round(max_lev, 2),
        "headroom": round(headroom, 2),
        "headroom_pct": round(headroom_pct, 3),
        "binding_constraint": binding,
        "constraint_count": constraint_count,
        "breached_constraints": breached,
        "tightest_constraints": tightest,
        "invariant_failures": invariant_failures,
        "warning_count": len(warnings),
        "warnings": warnings[:3],
    }
```

**Note on rounding**: Snapshot rounds `headroom` to 2dp and `headroom_pct` to 3dp before flags consume them. This is intentional — flags operate on the same values the agent sees. At 3dp precision on headroom_pct, the maximum rounding error is 0.0005 (0.05%), which is negligible for the 10% threshold.

## Layer 2: `core/leverage_capacity_flags.py`

```python
def generate_leverage_capacity_flags(snapshot: dict) -> list[dict]:
    """Generate severity-tagged flags from leverage capacity snapshot."""
    flags = []

    status = snapshot.get("status", "error")
    if status != "success":
        flags.append({
            "flag": "capacity_error",
            "severity": "error",
            "message": snapshot.get("verdict", "Leverage capacity analysis failed"),
        })
        return _sort_flags(flags)

    headroom = snapshot.get("headroom", 0)
    headroom_pct = snapshot.get("headroom_pct", 0)
    binding = snapshot.get("binding_constraint")
    breached = snapshot.get("breached_constraints", [])
    invariant_failures = snapshot.get("invariant_failures", [])

    # Over-leveraged (headroom negative)
    if headroom < 0:
        breach_count = len(breached)
        if breach_count > 1:
            names = [b["constraint"] for b in breached]
            flags.append({
                "flag": "multiple_breaches",
                "severity": "warning",
                "message": f"Leverage exceeds capacity on {breach_count} constraints: {', '.join(names)}",
            })
        else:
            flags.append({
                "flag": "over_leveraged",
                "severity": "warning",
                "message": f"Leverage exceeds capacity by {abs(headroom_pct) * 100:.0f}% — binding constraint: {binding}",
            })
    elif headroom_pct < 0.10:
        # Within capacity but tight (< 10% headroom)
        flags.append({
            "flag": "tight_headroom",
            "severity": "info",
            "message": f"Only {headroom_pct * 100:.0f}% headroom to max leverage — near capacity",
        })

    # Invariant limit failures
    if invariant_failures:
        names = [f["limit"] for f in invariant_failures]
        flags.append({
            "flag": "invariant_breach",
            "severity": "warning",
            "message": f"Variance contribution limit{'s' if len(names) != 1 else ''} breached: {', '.join(names)}",
        })

    # Core warnings (e.g. skipped constraints due to missing data)
    warning_count = snapshot.get("warning_count", 0)
    if warning_count > 0:
        flags.append({
            "flag": "capacity_warnings",
            "severity": "info",
            "message": f"{warning_count} warning{'s' if warning_count != 1 else ''} during capacity analysis",
        })

    # Within capacity with comfortable headroom
    if headroom >= 0 and headroom_pct >= 0.10 and not invariant_failures:
        flags.append({
            "flag": "within_capacity",
            "severity": "success",
            "message": f"Leverage {snapshot.get('effective_leverage', 0):.2f}x is within capacity with {headroom_pct * 100:.0f}% headroom",
        })

    # Fallback if no flags
    if not flags:
        flags.append({
            "flag": "capacity_assessed",
            "severity": "info",
            "message": f"Max leverage {snapshot.get('max_leverage', 0):.2f}x, current {snapshot.get('effective_leverage', 0):.2f}x",
        })

    return _sort_flags(flags)


def _sort_flags(flags):
    order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    return sorted(flags, key=lambda f: order.get(f.get("severity", "info"), 2))
```

**Flag summary:**

| Flag | Severity | Condition |
|------|----------|-----------|
| `capacity_error` | error | `status != "success"` |
| `multiple_breaches` | warning | headroom < 0 and > 1 breached constraint |
| `over_leveraged` | warning | headroom < 0 and 1 breached constraint |
| `invariant_breach` | warning | Any invariant limit fails |
| `tight_headroom` | info | 0 <= headroom_pct < 0.10 |
| `capacity_warnings` | info | warning_count > 0 (e.g. skipped constraints) |
| `capacity_assessed` | info | Fallback if no other flags |
| `within_capacity` | success | headroom >= 0, headroom_pct >= 0.10, no invariant failures |

## Layer 3: MCP Composition in `mcp_tools/risk.py`

### Helpers

```python
_LEVERAGE_OUTPUT_DIR = Path("logs/leverage")

def _save_full_leverage_capacity(result):
    """Save full leverage capacity results to disk and return absolute path, or None on failure."""
    import json

    _LEVERAGE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = _LEVERAGE_OUTPUT_DIR / f"leverage_{timestamp}.json"

    try:
        with file_path.open("w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, default=str)
        return str(file_path.resolve())
    except Exception:
        return None


def _build_leverage_agent_response(result, file_path=None):
    """Compose decision-oriented leverage capacity result for agent use."""
    from core.leverage_capacity_flags import generate_leverage_capacity_flags

    snapshot = _build_leverage_snapshot(result)
    flags = generate_leverage_capacity_flags(snapshot)

    response_status = "success" if result.get("status") == "success" else "error"

    return {
        "status": response_status,
        "format": "agent",
        "snapshot": snapshot,
        "flags": flags,
        "file_path": file_path,
    }
```

### Modified `get_leverage_capacity()` function

- Add `format: Literal["full", "agent"] = "full"` parameter (currently has no format parameter — "full" is the only existing behavior)
- Add `output: Literal["inline", "file"] = "inline"` parameter
- After building the success `result` dict, add file save + format dispatch:
  ```python
  file_path = _save_full_leverage_capacity(result) if output == "file" else None
  if format == "agent":
      return _build_leverage_agent_response(result, file_path=file_path)
  if file_path:
      result["file_path"] = file_path
  return result
  ```
- **Error handling**: The except block must also handle agent format:
  ```python
  except Exception as e:
      error_result = {"status": "error", "error": str(e)}
      if format == "agent":
          return _build_leverage_agent_response(error_result, file_path=None)
      return error_result
  ```
- The "no risk limits" early return must also handle agent format:
  ```python
  if risk_limits_data is None or risk_limits_data.is_empty():
      error_result = {"status": "error", "error": "No risk limits configured. Use set_risk_profile() first."}
      if format == "agent":
          return _build_leverage_agent_response(error_result, file_path=None)
      return error_result
  ```

### `mcp_server.py` changes

- Add `format` parameter with Literal["full", "agent"]
- Add `output` parameter
- Pass through

## Test Plan

### `tests/mcp_tools/test_leverage_agent_snapshot.py`

1. **test_snapshot_success_within_capacity** — Positive headroom → verdict "within capacity", correct fields
2. **test_snapshot_success_over_leveraged** — Negative headroom → verdict "Over-leveraged", binding constraint in verdict
3. **test_snapshot_error** — status="error" → verdict mentions failure, consistent keys with success path
4. **test_snapshot_breached_constraints** — 2 constraints with negative headroom → both in breached_constraints
5. **test_snapshot_tightest_capped** — 5 constraints → 3 in tightest_constraints
6. **test_snapshot_invariant_failures** — invariant limit fails → in invariant_failures
7. **test_snapshot_safe_float** — None/NaN/inf → default 0.0
8. **test_snapshot_error_key_consistency** — Error snapshot has same top-level keys as success snapshot
9. **test_snapshot_warnings_propagated** — Core warnings present → warning_count and warnings in snapshot

### `tests/core/test_leverage_capacity_flags.py`

9. **test_capacity_error_flag** — status != "success" → "capacity_error" error
10. **test_over_leveraged_flag** — headroom < 0, 1 breach → "over_leveraged" warning
11. **test_multiple_breaches_flag** — headroom < 0, 2+ breaches → "multiple_breaches" warning
12. **test_tight_headroom_flag** — 0 <= headroom_pct < 0.10 → "tight_headroom" info
13. **test_within_capacity_flag** — headroom >= 0, headroom_pct >= 0.10, no invariant failures → "within_capacity" success
14. **test_invariant_breach_flag** — invariant_failures not empty → "invariant_breach" warning
15. **test_capacity_assessed_fallback** — No other flags trigger → "capacity_assessed" info
16. **test_flag_sort_order** — error before warning before info before success
17. **test_boundary_headroom_zero** — headroom exactly 0, headroom_pct = 0 → "tight_headroom" info (0 < 0.10)
18. **test_boundary_headroom_pct_10** — headroom_pct exactly 0.10 → "within_capacity" success (>= 0.10)
19. **test_within_capacity_with_invariant_failure** — headroom OK but invariant fails → "invariant_breach" warning, NO "within_capacity" success
20. **test_capacity_warnings_flag** — warning_count > 0 → "capacity_warnings" info

### `tests/mcp_tools/test_leverage_agent_format.py`

21. **test_agent_response_structure** — Has status, format, snapshot, flags, file_path
22. **test_file_output_agent** — output="file" creates file, file_path set
23. **test_inline_no_file_path** — output="inline" → file_path is None
24. **test_agent_error_propagation** — Error result → response status="error", flags has "capacity_error"
25. **test_agent_no_risk_limits** — No risk limits configured → agent error response with appropriate message
26. **test_file_save_returns_none_on_failure** — Mock write failure → file_path is None

## Decisions

1. **Format parameter added**: `get_leverage_capacity()` currently has no format parameter. Adding `Literal["full", "agent"]` with "full" as default preserves backward compatibility.
2. **Headroom thresholds**: < 0 = over-leveraged (warning), 0-10% = tight (info), >= 10% = comfortable (success). 10% chosen as a meaningful buffer.
3. **Multiple breaches**: When > 1 constraint is breached, flag as "multiple_breaches" instead of generic "over_leveraged" to signal severity.
4. **Invariant failures**: Variance contribution limits are approximately leverage-invariant (scaling doesn't help), so they get their own flag separate from scaling constraints.
5. **Ticker consolidation N/A**: Unlike tax harvest, this tool has no repeated entries — each constraint appears once.
6. **File save returns None on failure**: Consistent with income projection and tax harvest patterns.
7. **Error path wired to agent format**: Both exception handler and early-return (no risk limits) route through `_build_leverage_agent_response()`.
8. **Error snapshot key consistency**: Error path returns same top-level keys as success path, including `invariant_failures`.

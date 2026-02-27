# Income Projection Agent Format Plan

_Status: **APPROVED** (Codex R2 — yield units verified, plan is spec for implementation)_

## Scope

Add `format="agent"` + `output="file"` to `get_income_projection()`. Same three-layer pattern. No dedicated result class — tool returns a raw dict via `_format_summary()`, `_format_full()`, or `_format_calendar()`. The snapshot operates on the summary-format dict.

**Note**: `portfolio_yield_on_value` is in **percentage points** (e.g., 3.31 means 3.31%), not decimal. All thresholds and formatting must use this scale.

## Layer 1: `_build_income_snapshot()` (standalone function)

Since income projection returns a raw dict, Layer 1 is a standalone helper in `mcp_tools/income.py`.

```python
def _build_income_snapshot(result: dict) -> dict:
    """Compact decision-oriented snapshot from income projection result."""
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
            "verdict": f"Income projection failed: {result.get('error', 'unknown error')}",
            "annual_income": 0,
            "portfolio_yield_on_value": 0,
            "portfolio_yield_on_cost": 0,
            "income_holding_count": 0,
            "holding_count": 0,
            "top_contributors": [],
            "upcoming_dividends": [],
            "warning_count": 0,
            "warnings": [],
        }

    annual_income = _safe_float(result.get("total_projected_annual_income"))
    yield_on_value = _safe_float(result.get("portfolio_yield_on_value"))
    yield_on_cost = _safe_float(result.get("portfolio_yield_on_cost"))
    holding_count = result.get("holding_count", 0)
    income_count = result.get("income_holding_count", 0)
    total_value = _safe_float(result.get("total_portfolio_value"))

    # Verdict (yield is in percentage points, e.g. 3.31 = 3.31%)
    if annual_income > 0:
        monthly_avg = annual_income / 12
        verdict = (
            f"${annual_income:,.0f}/yr projected income "
            f"(${monthly_avg:,.0f}/mo), "
            f"{yield_on_value:.1f}% yield, "
            f"{income_count} of {holding_count} positions pay dividends"
        )
    elif annual_income < 0:
        verdict = f"Negative projected income ${annual_income:,.0f}/yr (short positions or adjustments)"
    else:
        verdict = f"No dividend income projected from {holding_count} positions"

    # Top contributors (max 5, already sorted by annual income)
    top = result.get("top_5_contributors", [])[:5]
    top_contributors = []
    for c in top:
        top_contributors.append({
            "ticker": c.get("ticker", "unknown"),
            "annual_income": _safe_float(c.get("projected_annual_income")),
            "yield_on_cost": _safe_float(c.get("yield_on_cost")),
            "frequency": c.get("frequency", "Unknown"),
        })

    # Upcoming dividends (max 3)
    upcoming = result.get("upcoming_dividends", [])[:3]

    # Warnings (max 3)
    warnings = result.get("warnings", [])[:3]

    return {
        "status": status,
        "verdict": verdict,
        "annual_income": annual_income,
        "monthly_income_avg": _safe_float(annual_income / 12) if annual_income != 0 else 0,
        "portfolio_yield_on_value": yield_on_value,
        "portfolio_yield_on_cost": yield_on_cost,
        "total_portfolio_value": total_value,
        "holding_count": holding_count,
        "income_holding_count": income_count,
        "top_contributors": top_contributors,
        "upcoming_dividends": upcoming,
        "warning_count": len(result.get("warnings", [])),
        "warnings": warnings,
    }
```

## Layer 2: `core/income_projection_flags.py`

```python
def generate_income_projection_flags(snapshot: dict) -> list[dict]:
    """Generate severity-tagged flags from income projection snapshot."""
    flags = []

    status = snapshot.get("status", "error")
    if status != "success":
        flags.append({
            "flag": "projection_error",
            "severity": "error",
            "message": snapshot.get("verdict", "Income projection failed"),
        })
        return _sort_flags(flags)

    annual_income = snapshot.get("annual_income", 0)
    # yield is in percentage points (e.g. 3.31 = 3.31%)
    yield_on_value = snapshot.get("portfolio_yield_on_value", 0)
    holding_count = snapshot.get("holding_count", 0)
    income_count = snapshot.get("income_holding_count", 0)
    warning_count = snapshot.get("warning_count", 0)

    # Negative income (short positions or adjustments)
    if annual_income < 0:
        flags.append({
            "flag": "negative_income",
            "severity": "warning",
            "message": f"Negative projected income ${annual_income:,.0f}/yr — review short positions",
        })
        return _sort_flags(flags)

    # No income
    if annual_income == 0:
        flags.append({
            "flag": "no_income",
            "severity": "info",
            "message": "Portfolio has no projected dividend income",
        })
        return _sort_flags(flags)

    # Yield assessment (thresholds in percentage points)
    if yield_on_value >= 4.0:
        flags.append({
            "flag": "high_yield",
            "severity": "info",
            "message": f"Portfolio yield {yield_on_value:.1f}% is above average — verify dividend sustainability",
        })
    elif yield_on_value < 1.0 and annual_income > 0:
        flags.append({
            "flag": "low_yield",
            "severity": "info",
            "message": f"Portfolio yield {yield_on_value:.1f}% — income is a minor component",
        })

    # Coverage: how many positions pay dividends
    if holding_count > 0:
        income_ratio = income_count / holding_count
        if income_ratio < 0.25:
            flags.append({
                "flag": "low_income_coverage",
                "severity": "info",
                "message": f"Only {income_count} of {holding_count} positions ({income_ratio:.0%}) pay dividends",
            })
        elif income_ratio >= 0.75:
            flags.append({
                "flag": "broad_income_coverage",
                "severity": "success",
                "message": f"{income_count} of {holding_count} positions ({income_ratio:.0%}) generate income",
            })

    # Variable/uncertain dividends
    if warning_count > 0:
        flags.append({
            "flag": "dividend_warnings",
            "severity": "warning",
            "message": f"{warning_count} position{'s' if warning_count != 1 else ''} with variable or recently initiated dividends",
        })

    # Clean if no flags yet
    if not flags:
        flags.append({
            "flag": "healthy_income",
            "severity": "success",
            "message": f"${annual_income:,.0f}/yr projected income across {income_count} positions",
        })

    return _sort_flags(flags)


def _sort_flags(flags):
    order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    return sorted(flags, key=lambda f: order.get(f.get("severity", "info"), 2))
```

**Flag summary:**

| Flag | Severity | Condition |
|------|----------|-----------|
| `projection_error` | error | `status != "success"` |
| `negative_income` | warning | annual_income < 0 |
| `dividend_warnings` | warning | warning_count > 0 |
| `no_income` | info | annual_income == 0 |
| `high_yield` | info | yield_on_value >= 4.0 (pct points) |
| `low_yield` | info | yield_on_value < 1.0 (pct points), income > 0 |
| `low_income_coverage` | info | < 25% of positions pay dividends |
| `broad_income_coverage` | success | >= 75% of positions pay dividends |
| `healthy_income` | success | No other flags triggered |

## Layer 3: MCP Composition in `mcp_tools/income.py`

### Helpers

```python
_INCOME_OUTPUT_DIR = Path("logs/income")

def _save_full_income_projection(projection):
    """Save full income projection to disk and return absolute path, or None on failure."""
    import json

    _INCOME_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = _INCOME_OUTPUT_DIR / f"income_{timestamp}.json"

    try:
        with file_path.open("w", encoding="utf-8") as f:
            json.dump(projection, f, indent=2, default=str)
        return str(file_path.resolve())
    except Exception:
        return None


def _build_income_agent_response(result, file_path=None):
    """Compose decision-oriented income projection for agent use."""
    from core.income_projection_flags import generate_income_projection_flags

    snapshot = _build_income_snapshot(result)
    flags = generate_income_projection_flags(snapshot)

    response_status = "success" if result.get("status") == "success" else "error"

    return {
        "status": response_status,
        "format": "agent",
        "snapshot": snapshot,
        "flags": flags,
        "file_path": file_path,
    }
```

### Modified `get_income_projection()` function

- Add `"agent"` to format Literal
- Add `output: Literal["inline", "file"] = "inline"` parameter
- After building `projection` dict (line 250), add file save BEFORE format dispatch:
  ```python
  file_path = _save_full_income_projection(projection) if output == "file" else None
  ```
- Add agent format branch: builds summary from projection, then wraps in agent response
  ```python
  if format == "agent":
      summary_result = _format_summary(projection)
      return _build_income_agent_response(summary_result, file_path=file_path)
  ```
- For existing summary/full/calendar branches, propagate `file_path` if set
- **Error handling**: The except block must also handle agent format. When an exception occurs, the error dict `{"status": "error", "error": str(e)}` is returned. For agent format, this must go through `_build_income_agent_response()`:
  ```python
  except Exception as e:
      error_result = {"status": "error", "error": str(e)}
      if format == "agent":
          file_path = None  # no file on error
          return _build_income_agent_response(error_result, file_path=file_path)
      return error_result
  ```

**Important**: The agent snapshot operates on the **summary** format since it has all the key metrics. The full projection is saved to file for reference.

### `mcp_server.py` changes

- Add `"agent"` to format Literal for `get_income_projection`
- Add `output` parameter
- Pass through

## Test Plan

### `tests/mcp_tools/test_income_agent_snapshot.py`

1. **test_snapshot_success** — Valid income → verdict has annual income, yield, counts
2. **test_snapshot_no_income** — annual_income=0 → verdict "No dividend income"
3. **test_snapshot_negative_income** — annual_income=-500 → verdict mentions "Negative"
4. **test_snapshot_error** — status="error" → verdict mentions failure, consistent keys with success path
5. **test_snapshot_top_contributors** — 5 contributors → all present with ticker, annual_income, frequency
6. **test_snapshot_safe_float** — None/NaN/inf → default 0.0
7. **test_snapshot_warnings_capped** — 5 warnings → 3 in snapshot
8. **test_snapshot_monthly_avg** — annual_income=12000 → monthly_income_avg=1000
9. **test_snapshot_error_key_consistency** — Error snapshot has same keys as success snapshot (portfolio_yield_on_value, not portfolio_yield)

### `tests/core/test_income_projection_flags.py`

10. **test_projection_error_flag** — status != "success" → "projection_error" error
11. **test_negative_income_flag** — annual_income=-500 → "negative_income" warning, early return
12. **test_no_income_flag** — annual_income=0 → "no_income" info, early return
13. **test_high_yield_flag** — yield=5.0 → "high_yield" info
14. **test_low_yield_flag** — yield=0.5, income > 0 → "low_yield" info
15. **test_low_coverage_flag** — 1 of 10 positions → "low_income_coverage" info
16. **test_broad_coverage_flag** — 8 of 10 positions → "broad_income_coverage" success
17. **test_dividend_warnings_flag** — warning_count=2 → "dividend_warnings" warning
18. **test_healthy_income_flag** — Normal income, no issues → "healthy_income" success
19. **test_flag_sort_order** — error before warning before info before success
20. **test_boundary_yield_4pct** — yield exactly 4.0 → "high_yield" info
21. **test_boundary_yield_1pct** — yield exactly 1.0 → no low_yield flag
22. **test_boundary_coverage_25pct** — exactly 25% → no low_income_coverage flag
23. **test_boundary_coverage_75pct** — exactly 75% → "broad_income_coverage" success

### `tests/mcp_tools/test_income_agent_format.py`

24. **test_agent_response_structure** — Has status, format, snapshot, flags, file_path
25. **test_file_output_agent** — output="file" creates file, file_path set
26. **test_inline_no_file_path** — output="inline" → file_path is None
27. **test_file_output_summary** — format="summary", output="file" → file_path in response
28. **test_file_output_full** — format="full", output="file" → file_path in response
29. **test_file_output_calendar** — format="calendar", output="file" → file_path in response
30. **test_agent_error_propagation** — Error result → response status="error", flags has "projection_error"
31. **test_file_save_returns_none_on_failure** — Mock write failure → file_path is None (not phantom path)

## Decisions

1. **Snapshot from summary format**: Agent snapshot operates on summary dict (has all key metrics). Full projection saved to file.
2. **Yield in percentage points**: Engine returns yield as e.g. 3.31 (= 3.31%). Thresholds: >= 4.0 high, < 1.0 low. Formatting: `:.1f` + "%" suffix.
3. **Coverage thresholds**: < 25% low, >= 75% broad (matching portfolio diversification heuristics).
4. **No income early return**: If annual_income==0, only `no_income` flag (other flags meaningless).
5. **Negative income**: Handled explicitly with `negative_income` warning flag and early return.
6. **File save returns None on failure**: Unlike other tools that always return a path, this returns `None` on write failure to avoid phantom file references.
7. **Error path wired to agent format**: Exception handler checks format and routes through `_build_income_agent_response()` for consistent agent output.
8. **Error snapshot key consistency**: Error path returns the same top-level keys as success path (portfolio_yield_on_value, not portfolio_yield).

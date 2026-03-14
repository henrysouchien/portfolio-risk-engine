# Risk Score Agent Format Plan

_Status: **APPROVED** (Codex R2 PASS)_

## Scope

Add `format="agent"` + `output="file"` to `get_risk_score()`. Same three-layer pattern as the other 7 agent-format tools.

## Layer 1: `RiskScoreResult.get_agent_snapshot()`

Add to `core/result_objects/risk.py` on `RiskScoreResult`:

```python
def get_agent_snapshot(self) -> dict:
    """Compact decision-oriented snapshot for agent consumption."""
    def _safe_float(val, default: float = 0.0) -> float:
        if val is None:
            return default
        try:
            f = float(val)
            if f != f:  # NaN check
                return default
            return f
        except (TypeError, ValueError):
            return default

    score = self.risk_score.get("score", 0)
    category = self.get_risk_category_enum()
    component_scores = self.get_component_scores()
    is_compliant = self.is_compliant()
    violations_summary = self._get_violations_summary()

    # Verdict: one-line summary
    violation_count = violations_summary["total_violations"]
    if is_compliant:
        verdict = f"Portfolio risk is {category} (score {score}/100), fully compliant"
    else:
        verdict = f"Portfolio risk is {category} (score {score}/100), {violation_count} violation{'s' if violation_count != 1 else ''}"

    # Top recommendations (max 5)
    recommendations = self.get_recommendations()[:5]

    # Top risk factors (max 5)
    risk_factors = self.get_risk_factors()[:5]

    # Priority actions (already structured by _get_priority_actions)
    priority_actions = self._get_priority_actions()[:5]

    return {
        "overall_score": _safe_float(score),
        "risk_category": category,
        "is_compliant": is_compliant,
        "verdict": verdict,
        "component_scores": {
            k: _safe_float(v) for k, v in component_scores.items()
        },
        "violation_count": violation_count,
        "critical_violations": violations_summary.get("critical_violations", [])[:3],
        "recommendations": recommendations,
        "risk_factors": risk_factors,
        "priority_actions": priority_actions,
    }
```

**Notes:**
- Uses existing helper methods — no new data computation needed
- `_safe_float()` must be defined as a local helper inside `get_agent_snapshot()` (same pattern as other implementations — each snapshot defines its own inner `_safe_float(val, default=0.0)` that handles None/NaN/string → default).
- `verdict` provides the one-line "what should I know" answer
- `component_scores` dict keys: `factor_risk`, `concentration_risk`, `volatility_risk`, `sector_risk`
- `critical_violations` capped at 3 (most urgent items)
- `priority_actions` already prioritized by `_get_priority_actions()`

## Layer 2: `core/risk_score_flags.py`

New file with interpretive flags:

```python
def generate_risk_score_flags(snapshot: dict) -> list[dict]:
    """Generate severity-tagged flags from risk score snapshot."""
    flags = []
    score = snapshot.get("overall_score", 0)
    is_compliant = snapshot.get("is_compliant", True)
    violation_count = snapshot.get("violation_count", 0)
    component_scores = snapshot.get("component_scores", {})

    # Compliance flag (most important)
    if not is_compliant:
        flags.append({
            "flag": "non_compliant",
            "severity": "error" if violation_count >= 3 else "warning",
            "message": f"{violation_count} risk limit violation{'s' if violation_count != 1 else ''} detected",
        })

    # Overall score flags
    if score < 60:
        flags.append({
            "flag": "high_risk",
            "severity": "warning",
            "message": f"Risk score {score}/100 indicates high portfolio risk requiring attention",
        })
    elif score >= 90:
        flags.append({
            "flag": "excellent_risk",
            "severity": "success",
            "message": f"Risk score {score}/100 — excellent risk management",
        })

    # Component-level flags (flag any component below 60)
    for component, comp_score in component_scores.items():
        if isinstance(comp_score, (int, float)) and comp_score < 60:
            label = component.replace("_", " ")
            flags.append({
                "flag": f"weak_{component}",
                "severity": "warning",
                "message": f"{label.title()} score {comp_score}/100 needs improvement",
            })

    # No violations — compliant success
    if is_compliant and not any(f["flag"] == "excellent_risk" for f in flags):
        flags.append({
            "flag": "compliant",
            "severity": "success",
            "message": "Portfolio is compliant with all risk limits",
        })

    return _sort_flags(flags)


def _sort_flags(flags: list[dict]) -> list[dict]:
    """Sort by severity: error > warning > info > success."""
    order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    return sorted(flags, key=lambda f: order.get(f.get("severity", "info"), 2))
```

**Flag summary:**

| Flag | Severity | Condition |
|------|----------|-----------|
| `non_compliant` | error (≥3 violations) or warning | `is_compliant == False` |
| `high_risk` | warning | `score < 60` |
| `excellent_risk` | success | `score >= 90` |
| `weak_{component}` | warning | Any component score < 60 |
| `compliant` | success | `is_compliant == True` (when not already excellent) |

## Layer 3: MCP Composition in `mcp_tools/risk.py`

### `_build_risk_score_agent_response()`

```python
def _build_risk_score_agent_response(result, file_path=None):
    """Compose decision-oriented risk score result for agent use."""
    from core.risk_score_flags import generate_risk_score_flags

    snapshot = result.get_agent_snapshot()
    flags = generate_risk_score_flags(snapshot)

    return {
        "status": "success",
        "format": "agent",
        "snapshot": snapshot,
        "flags": flags,
        "file_path": file_path,
    }
```

### `_save_full_risk_score()`

```python
_RISK_SCORE_OUTPUT_DIR = Path("logs/risk_score")

def _save_full_risk_score(result):
    """Save full risk score data to disk and return absolute path."""
    _RISK_SCORE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    file_path = _RISK_SCORE_OUTPUT_DIR / f"risk_score_{timestamp}.json"

    try:
        payload = result.to_api_response()
    except Exception:
        payload = {"overall_score": result.get_overall_score()}
    payload["status"] = "success"

    with file_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)

    return str(file_path.resolve())
```

### Modified `get_risk_score()` function

Add `format="agent"` to the Literal and `output` parameter:

```python
def get_risk_score(
    user_email=None,
    portfolio_name="CURRENT_PORTFOLIO",
    format: Literal["full", "summary", "report", "agent"] = "summary",
    output: Literal["inline", "file"] = "inline",
    use_cache=True
) -> dict:
```

File save runs BEFORE format dispatch (applies to ALL formats):

```python
# Optionally persist full payload (works with any format)
file_path = _save_full_risk_score(result) if output == "file" else None

# Format response
if format == "agent":
    return _build_risk_score_agent_response(result, file_path=file_path)
if format == "summary":
    summary = { ... existing summary logic ... }
    if file_path:
        summary["file_path"] = file_path
    return summary
if format == "full":
    response = result.to_api_response()
    response["status"] = "success"
    if file_path:
        response["file_path"] = file_path
    return response
# report
response = {"status": "success", "report": result.to_formatted_report()}
if file_path:
    response["file_path"] = file_path
return response
```

This is consistent with `mcp_tools/performance.py` and `mcp_tools/whatif.py` where `output="file"` works across all format modes.

### `mcp_server.py` changes

Update `get_risk_score()` wrapper:
- Add `"agent"` to format Literal
- Add `output` parameter
- Pass `output` through to `_get_risk_score()`
- Add example: `"Agent briefing" -> get_risk_score(format="agent")`

## Test Plan

### `tests/core/test_risk_score_agent_snapshot.py`

1. **test_snapshot_compliant** — Score 85, no violations → `is_compliant=True`, verdict contains "fully compliant"
2. **test_snapshot_non_compliant** — Score 55, 3 violations → `is_compliant=False`, violation_count=3
3. **test_snapshot_component_scores** — All 4 component scores present and float
4. **test_snapshot_recommendations_capped** — 10 recommendations in → 5 in snapshot
5. **test_snapshot_risk_factors_capped** — 10 risk factors in → 5 in snapshot
6. **test_snapshot_priority_actions** — Priority actions present and capped at 5
7. **test_snapshot_critical_violations_capped** — 5 critical violations → 3 in snapshot
8. **test_snapshot_verdict_singular** — 1 violation → "1 violation" (not "violations")
9. **test_snapshot_empty_data** — Empty risk_score dict → safe defaults (score 0, category "unknown")

### `tests/core/test_risk_score_flags.py`

10. **test_non_compliant_error** — 3+ violations → severity "error"
11. **test_non_compliant_warning** — 1-2 violations → severity "warning"
12. **test_high_risk_flag** — Score < 60 → "high_risk" warning
13. **test_excellent_risk_flag** — Score >= 90 → "excellent_risk" success
14. **test_weak_component_flag** — Component score < 60 → "weak_{component}" warning
15. **test_compliant_success_flag** — Compliant, score 70-89 → "compliant" success
16. **test_excellent_no_duplicate_compliant** — Score 95, compliant → only "excellent_risk", not both
17. **test_flag_sort_order** — error before warning before success
18. **test_no_flags_on_empty_snapshot** — Empty dict → compliant success only

### `tests/mcp_tools/test_risk_score_agent_format.py`

19. **test_agent_response_structure** — Has status, format, snapshot, flags, file_path keys
20. **test_file_output_agent** — `format="agent", output="file"` creates JSON file, `file_path` is set
21. **test_file_output_content** — Saved file contains valid JSON with "status" key
22. **test_inline_no_file_path** — `output="inline"` → `file_path` is None
23. **test_file_output_summary** — `format="summary", output="file"` → response includes `file_path`
24. **test_file_output_full** — `format="full", output="file"` → response includes `file_path`

## Decisions

1. **No score trend**: Historical score tracking doesn't exist yet. Skip delta/trend for now.
2. **Reuse existing helpers**: All data comes from existing `RiskScoreResult` methods — no new computation.
3. **Verdict format**: Plain English sentence with score and compliance status.
4. **Component score threshold**: Flag below 60 (same scale as overall score categories).
5. **Compliance severity**: error at ≥3 violations (serious), warning at 1-2 (attention needed).

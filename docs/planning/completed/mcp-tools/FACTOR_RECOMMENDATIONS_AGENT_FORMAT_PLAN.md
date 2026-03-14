# Factor Recommendations Agent Format Plan

_Status: **APPROVED** (Codex R3 PASS)_

## Scope

Add `format="agent"` + `output="file"` to `get_factor_recommendations()`. Same three-layer pattern. Two result classes: `OffsetRecommendationResult` (single mode) and `PortfolioOffsetRecommendationResult` (portfolio mode).

## Layer 1: `get_agent_snapshot()` on Both Result Classes

### `OffsetRecommendationResult.get_agent_snapshot()`

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

    recs = self.recommendations or []
    top_recs = []
    for r in recs[:5]:
        top_recs.append({
            "label": r.get("label") or r.get("factor") or r.get("ticker") or "unknown",
            "correlation": _safe_float(r.get("correlation")),
            "sharpe_ratio": _safe_float(r.get("sharpe_ratio")),
            "category": r.get("category", "unknown"),
            "overexposed_label": r.get("overexposed_label"),  # which driver this hedge targets
        })

    has_recs = len(recs) > 0
    if has_recs:
        best = top_recs[0]
        verdict = f"Top hedge for {self.overexposed_label}: {best['label']} (corr={best['correlation']:.2f}, Sharpe={best['sharpe_ratio']:.2f})"
    else:
        verdict = f"No suitable hedges found for {self.overexposed_label}"

    return {
        "mode": "single",
        "overexposed_factor": self.overexposed_label,
        "verdict": verdict,
        "recommendation_count": len(recs),
        "top_recommendations": top_recs,
    }
```

### `PortfolioOffsetRecommendationResult.get_agent_snapshot()`

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

    drivers = self.drivers or []
    top_drivers = []
    for d in drivers[:3]:
        top_drivers.append({
            "label": d.get("label") or d.get("id") or "unknown",
            "percent_of_portfolio": _safe_float(d.get("percent_of_portfolio") or d.get("factor_pct")),
            "driver_type": d.get("driver_type", "unknown"),
            "market_beta": _safe_float(d.get("market_beta")),
        })

    recs = self.recommendations or []
    top_recs = []
    for r in recs[:5]:
        top_recs.append({
            "label": r.get("label") or r.get("ticker") or "unknown",
            "correlation": _safe_float(r.get("correlation")),
            "sharpe_ratio": _safe_float(r.get("sharpe_ratio")),
            "category": r.get("category", "unknown"),
            "suggested_weight": _safe_float(r.get("suggested_weight")),
        })

    driver_count = len(drivers)
    rec_count = len(recs)
    if driver_count > 0 and rec_count > 0:
        top_driver = top_drivers[0]["label"]
        verdict = f"Portfolio has {driver_count} risk driver{'s' if driver_count != 1 else ''} (top: {top_driver}), {rec_count} hedge{'s' if rec_count != 1 else ''} available"
    elif driver_count > 0:
        verdict = f"Portfolio has {driver_count} risk driver{'s' if driver_count != 1 else ''} but no suitable hedges found"
    else:
        verdict = "No significant risk drivers detected in portfolio"

    return {
        "mode": "portfolio",
        "verdict": verdict,
        "driver_count": driver_count,
        "top_drivers": top_drivers,
        "recommendation_count": rec_count,
        "top_recommendations": top_recs,
    }
```

## Layer 2: `core/factor_recommendation_flags.py`

```python
def generate_factor_recommendation_flags(snapshot: dict) -> list[dict]:
    """Generate severity-tagged flags from factor recommendation snapshot."""
    flags = []
    mode = snapshot.get("mode", "single")
    rec_count = snapshot.get("recommendation_count", 0)
    top_recs = snapshot.get("top_recommendations", [])

    # No recommendations available — branch by mode for distinct messaging
    if rec_count == 0:
        if mode == "portfolio":
            driver_count = snapshot.get("driver_count", 0)
            if driver_count == 0:
                flags.append({
                    "flag": "no_risk_drivers",
                    "severity": "info",
                    "message": "No significant risk drivers detected in portfolio",
                })
            else:
                flags.append({
                    "flag": "drivers_without_hedges",
                    "severity": "warning",
                    "message": f"{driver_count} risk driver{'s' if driver_count != 1 else ''} detected but no suitable hedges found",
                })
        else:
            flags.append({
                "flag": "no_hedges_available",
                "severity": "info",
                "message": "No suitable hedge candidates found for the given criteria",
            })
        return _sort_flags(flags)

    # Check if top recommendation has strong negative correlation
    if top_recs:
        best_corr = top_recs[0].get("correlation", 0)
        if best_corr < -0.5:
            flags.append({
                "flag": "strong_hedge_available",
                "severity": "success",
                "message": f"Strong hedge candidate with {best_corr:.2f} correlation",
            })
        elif best_corr > -0.1:
            flags.append({
                "flag": "weak_hedges_only",
                "severity": "warning",
                "message": f"Best hedge has weak correlation ({best_corr:.2f}); limited hedging benefit",
            })
        else:
            # Moderate hedge: between -0.5 and -0.1
            flags.append({
                "flag": "hedges_available",
                "severity": "info",
                "message": f"Hedge candidates available (best correlation: {best_corr:.2f})",
            })

    # Portfolio mode: multiple drivers
    if mode == "portfolio":
        driver_count = snapshot.get("driver_count", 0)
        if driver_count >= 3:
            flags.append({
                "flag": "multiple_risk_drivers",
                "severity": "warning",
                "message": f"{driver_count} risk drivers detected — portfolio may need broader rebalancing",
            })

    # Good set of options
    if rec_count >= 5:
        flags.append({
            "flag": "diverse_hedges",
            "severity": "info",
            "message": f"{rec_count} hedge candidates available across categories",
        })

    return _sort_flags(flags)


def _sort_flags(flags):
    order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    return sorted(flags, key=lambda f: order.get(f.get("severity", "info"), 2))
```

**Flag summary:**

| Flag | Severity | Condition |
|------|----------|-----------|
| `no_hedges_available` | info | Single mode, `rec_count == 0` |
| `no_risk_drivers` | info | Portfolio mode, 0 drivers, 0 recs |
| `drivers_without_hedges` | warning | Portfolio mode, drivers > 0, 0 recs |
| `strong_hedge_available` | success | Best correlation < -0.5 |
| `hedges_available` | info | Best correlation between -0.5 and -0.1 |
| `weak_hedges_only` | warning | Best correlation > -0.1 |
| `multiple_risk_drivers` | warning | Portfolio mode, ≥3 drivers |
| `diverse_hedges` | info | ≥5 recommendations |

## Layer 3: MCP Composition in `mcp_tools/factor_intelligence.py`

### Helpers

```python
_FACTOR_RECS_OUTPUT_DIR = Path("logs/factor_recommendations")

def _save_full_factor_recommendations(result, mode):
    """Save full recommendations to disk."""
    _FACTOR_RECS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    file_path = _FACTOR_RECS_OUTPUT_DIR / f"factor_recs_{mode}_{timestamp}.json"

    try:
        payload = result.to_api_response()
    except Exception:
        payload = {"mode": mode}
    if not isinstance(payload, dict):
        payload = {"mode": mode}
    payload["status"] = "success"

    with file_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)

    return str(file_path.resolve())


def _build_factor_recs_agent_response(result, file_path=None):
    """Compose decision-oriented recommendation result for agent use."""
    from core.factor_recommendation_flags import generate_factor_recommendation_flags

    snapshot = result.get_agent_snapshot()
    flags = generate_factor_recommendation_flags(snapshot)

    return {
        "status": "success",
        "format": "agent",
        "snapshot": snapshot,
        "flags": flags,
        "file_path": file_path,
    }
```

### Modified `get_factor_recommendations()` function

- Add `"agent"` to format Literal
- Add `output: Literal["inline", "file"] = "inline"` parameter
- File save runs BEFORE format dispatch (applies to ALL formats)
- Agent format branch returns `_build_factor_recs_agent_response(result, file_path)`
- For summary/full/report, propagate `file_path` if set

### `mcp_server.py` changes

- Add `"agent"` to format Literal for `get_factor_recommendations`
- Add `output` parameter
- Pass through to `_get_factor_recommendations()`
- Add example: `"Agent briefing" -> get_factor_recommendations(format="agent")`

## Test Plan

### `tests/core/test_factor_recs_agent_snapshot.py`

1. **test_single_snapshot_with_recs** — 5 recs → top_recs has 5, verdict mentions top hedge
2. **test_single_snapshot_no_recs** — 0 recs → verdict "no suitable hedges"
3. **test_single_snapshot_recs_capped** — 10 recs → 5 in snapshot
4. **test_single_snapshot_safe_float** — None/NaN/inf correlation → default 0.0
5. **test_portfolio_snapshot_with_drivers** — 3 drivers, 5 recs → correct counts, verdict, driver_type/market_beta present
6. **test_portfolio_snapshot_no_drivers** — 0 drivers → verdict "no significant risk drivers"
7. **test_portfolio_snapshot_drivers_capped** — 5 drivers → 3 in snapshot
8. **test_portfolio_snapshot_suggested_weight** — suggested_weight present in top_recs
9a. **test_portfolio_snapshot_safe_float_inf** — inf market_beta → default 0.0

### `tests/core/test_factor_recommendation_flags.py`

9. **test_no_hedges_single_mode** — Single mode, 0 recs → "no_hedges_available" info
10. **test_no_risk_drivers_flag** — Portfolio mode, 0 drivers, 0 recs → "no_risk_drivers" info
11. **test_drivers_without_hedges_flag** — Portfolio mode, 2 drivers, 0 recs → "drivers_without_hedges" warning
12. **test_strong_hedge_flag** — correlation -0.6 → "strong_hedge_available" success
13. **test_weak_hedges_flag** — correlation -0.05 → "weak_hedges_only" warning
14. **test_moderate_hedges_flag** — correlation -0.3 → "hedges_available" info
15. **test_multiple_drivers_flag** — 3 drivers → "multiple_risk_drivers" warning
16. **test_diverse_hedges_flag** — 5 recs → "diverse_hedges" info
17. **test_flag_sort_order** — warning before info before success
17a. **test_boundary_corr_minus_0_5** — correlation exactly -0.5 → "hedges_available" info (not strong)
17b. **test_boundary_corr_minus_0_1** — correlation exactly -0.1 → "hedges_available" info (not weak)

### `tests/mcp_tools/test_factor_recs_agent_format.py`

18. **test_agent_response_structure** — Has status, format, snapshot, flags, file_path
19. **test_file_output_agent** — output="file" creates file, file_path set
20. **test_inline_no_file_path** — output="inline" → file_path is None
21. **test_file_output_summary** — format="summary", output="file" → file_path in response
22. **test_file_output_full** — format="full", output="file" → file_path in response
23. **test_file_output_report** — format="report", output="file" → file_path in response
24. **test_file_save_fallback** — to_api_response() raises → file still written with mode fallback
25. **test_agent_portfolio_mode** — Portfolio mode result → snapshot has mode="portfolio", drivers present
26. **test_agent_single_mode** — Single mode result → snapshot has mode="single", overexposed_factor present

## Decisions

1. **Two result classes**: Each gets its own `get_agent_snapshot()` with mode-specific fields.
2. **Single flags module**: `generate_factor_recommendation_flags()` works for both modes via `snapshot["mode"]`.
3. **Correlation threshold for flags**: -0.5 strong, -0.1 weak (matches the tool's default threshold of -0.2).
4. **Driver cap**: 3 in snapshot (most important); recommendation cap: 5 (consistent with other tools).
5. **Verdict format**: Natural language with counts and top hedge label.

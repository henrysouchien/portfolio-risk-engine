# Plan: Agent-Optimized Factor Analysis Output

_Created: 2026-02-25_
_Status: **COMPLETE** (21 Codex review rounds, 90 new tests, live-tested)_
_Reference: `WHATIF_AGENT_FORMAT_PLAN.md`, `OPTIMIZATION_AGENT_FORMAT_PLAN.md` (same three-layer pattern)_

## Context

`get_factor_analysis` has 3 analysis modes (`correlations`, `performance`, `returns`), each producing a different result type. The current `format="summary"` varies by mode but provides no interpretation. The agent can't answer "which factors are worth watching?" or "are there any concerning correlations?"

Goal: Apply the same `format="agent"` + `output="file"` pattern across all 3 modes.

## Current State

### Output formats by mode

| Mode | Summary gets | Full gets |
|------|-------------|-----------|
| `correlations` | categories_analyzed, matrix_sizes, overlays_included, data_quality. No interpretation of correlation structure. | Full matrices, overlays, labels. ~50-200KB. |
| `performance` | Top 5 by Sharpe, macro/category composites. No assessment of factor regime. | All per_factor metrics, composites. ~10-50KB. |
| `returns` | Top N per window, bottom performers. No cross-window trend assessment. | All factors, rankings, by_category. ~20-100KB. |

### What the agent needs across all modes

1. **Verdict** — What's the key takeaway? One phrase per mode.
2. **Key metrics** — Mode-specific highlights (top correlations, best Sharpe, leading returns).
3. **Flags** — Concerning correlations, exceptional/poor performers, extreme returns.
4. **Compact data** — Enough to inform portfolio decisions without full matrices.

## Proposed Design

### Layer 1: Data accessors (on each result class in `core/result_objects.py`)

Each of the 3 result classes gets a `get_agent_snapshot()` method returning a mode-specific compact dict.

#### FactorCorrelationResult.get_agent_snapshot()

```python
def get_agent_snapshot(self) -> dict:
    """Compact metrics for agent consumption."""
    import pandas as pd

    def _safe_float(val, default=0.0):
        import math
        try:
            result = float(val) if val is not None else default
            return default if (math.isnan(result) or math.isinf(result)) else result
        except (TypeError, ValueError):
            return default

    # Matrix summary: extract high correlation pairs from DataFrames
    high_corr_pairs = []
    matrices = self.matrices or {}
    for category, matrix in matrices.items():
        if isinstance(matrix, pd.DataFrame) and not matrix.empty:
            # Correlation matrices are symmetric (from pandas corr()); use upper triangle
            tickers = list(matrix.columns)
            for i, t1 in enumerate(tickers):
                for j in range(i + 1, len(tickers)):
                    t2 = tickers[j]
                    try:
                        raw_corr = matrix.loc[t1, t2]
                    except KeyError:
                        continue
                    corr = _safe_float(raw_corr) if pd.notna(raw_corr) else 0.0
                    if abs(corr) > 0.7:
                        high_corr_pairs.append({
                            "factor1": t1,
                            "factor2": t2,
                            "correlation": round(corr, 3),
                            "category": category,
                        })
        elif isinstance(matrix, dict):
            # Fallback for dict-form matrices
            tickers = list(matrix.keys())
            for i, t1 in enumerate(tickers):
                row = matrix.get(t1)
                if not isinstance(row, dict):
                    continue
                for t2 in tickers[i + 1:]:
                    # Dict matrices are symmetric (from DataFrame.to_dict())
                    corr = _safe_float(row.get(t2))
                    if abs(corr) > 0.7:
                        high_corr_pairs.append({
                            "factor1": t1,
                            "factor2": t2,
                            "correlation": round(corr, 3),
                            "category": category,
                        })
    # Sort by abs correlation descending, tie-break by factor1
    high_corr_pairs.sort(key=lambda x: (-abs(x["correlation"]), x["factor1"], x["factor2"]))
    total_high_corr_count = len(high_corr_pairs)
    high_corr_pairs = high_corr_pairs[:5]

    # Overlay summary
    overlays_available = []
    overlays = self.overlays or {}
    for key in ["rate_sensitivity", "market_sensitivity", "macro_composite_matrix", "macro_etf_matrix"]:
        if overlays.get(key) is not None:
            overlays_available.append(key)

    # Data quality
    categories_analyzed = list(matrices.keys())
    total_factors = 0
    for m in matrices.values():
        if isinstance(m, pd.DataFrame):
            total_factors += len(m.columns)
        elif isinstance(m, dict):
            total_factors += len(m)

    if not matrices or total_factors == 0:
        verdict = "no correlation data available"
    elif total_high_corr_count:
        verdict = "high correlations detected"
    else:
        verdict = "factor correlations normal"

    return {
        "verdict": verdict,
        "analysis_type": "correlations",
        "categories_analyzed": categories_analyzed,
        "total_factors": total_factors,
        "high_correlation_pairs": high_corr_pairs,
        "total_high_corr_count": total_high_corr_count,
        "overlays_available": overlays_available,
    }
```

#### FactorPerformanceResult.get_agent_snapshot()

```python
def get_agent_snapshot(self) -> dict:
    """Compact metrics for agent consumption."""
    # Top 5 by Sharpe
    per_factor = self.per_factor or {}
    factor_metrics = []
    def _safe_float(val, default=0.0):
        import math
        try:
            result = float(val) if val is not None else default
            return default if (math.isnan(result) or math.isinf(result)) else result
        except (TypeError, ValueError):
            return default

    for ticker, metrics in per_factor.items():
        if isinstance(metrics, dict):
            factor_metrics.append({
                "ticker": ticker,
                "sharpe_ratio": round(_safe_float(metrics.get("sharpe_ratio")), 3),
                "annual_return_pct": round(_safe_float(metrics.get("annual_return")) * 100, 2),
                "volatility_pct": round(_safe_float(metrics.get("volatility")) * 100, 2),
            })
    factor_metrics.sort(key=lambda x: (-x["sharpe_ratio"], x["ticker"]))
    top_factors = factor_metrics[:5]
    # Always compute bottom from full sorted list (worst 3 by Sharpe)
    # For small universes, may overlap with top_factors — that's fine
    bottom_factors = list(reversed(factor_metrics[-3:])) if factor_metrics else []

    # Macro composites
    macro_summary = {}
    composites = self.composites or {}
    macro = composites.get("macro") or {}
    for name, metrics in macro.items():
        if isinstance(metrics, dict):
            macro_summary[name] = {
                "sharpe_ratio": round(_safe_float(metrics.get("sharpe_ratio")), 3),
                "annual_return_pct": round(_safe_float(metrics.get("annual_return")) * 100, 2),
            }

    # Verdict
    if not factor_metrics:
        verdict = "no factor performance data"
    else:
        best_sharpe = top_factors[0]["sharpe_ratio"]
        if best_sharpe > 1.0:
            verdict = "strong factor performance"
        elif best_sharpe > 0.5:
            verdict = "moderate factor performance"
        elif best_sharpe > 0:
            verdict = "weak factor performance"
        else:
            verdict = "negative factor performance"

    return {
        "verdict": verdict,
        "analysis_type": "performance",
        "top_factors": top_factors,
        "bottom_factors": bottom_factors,
        "macro_composites": macro_summary,
        "factors_analyzed": len(factor_metrics),
    }
```

#### FactorReturnsResult.get_agent_snapshot()

```python
def get_agent_snapshot(self) -> dict:
    """Compact metrics for agent consumption."""
    # Top and bottom per window
    rankings = self.rankings or {}
    top_per_window = {}
    bottom_per_window = {}
    for window, ranked_list in rankings.items():
        if isinstance(ranked_list, list) and ranked_list:
            top_per_window[window] = ranked_list[:3]
            bottom_per_window[window] = ranked_list[-3:]

    # Category summary
    by_category = self.by_category or {}
    category_summary = {}
    for cat, data in by_category.items():
        if isinstance(data, dict):
            # Copy category metrics with numeric rounding
            category_summary[cat] = {
                k: round(v, 4) if isinstance(v, (int, float)) else v
                for k, v in data.items()
            }

    # Verdict from shortest window (most recent)
    windows = [w for w in (self.windows or []) if isinstance(w, str)]
    from datetime import datetime, UTC
    current_month = datetime.now(UTC).month  # 1-12
    _WINDOW_ORDER = {"1m": 1, "3m": 3, "6m": 6, "ytd": max(current_month - 1, 1), "1y": 12, "2y": 24, "3y": 36, "5y": 60}
    # Consider windows that have non-empty ranking data; also include ranking-only keys
    all_window_candidates = set(windows) | set(rankings.keys())
    known_windows = sorted([
        w for w in all_window_candidates
        if isinstance(w, str) and w in _WINDOW_ORDER and isinstance(rankings.get(w), list) and rankings[w]
    ])
    # Tie-break: prefer non-ytd windows (ytd sorts after same-length named windows)
    shortest_window = min(known_windows, key=lambda w: (_WINDOW_ORDER.get(w, 999), w == "ytd", w)) if known_windows else None
    if not known_windows:
        verdict = "no factor returns data"
    else:
        verdict = "factor returns data available"
    shortest_ranked = rankings.get(shortest_window) if shortest_window else None
    if isinstance(shortest_ranked, list) and shortest_ranked:
        top = shortest_ranked[0]
        if isinstance(top, dict):
            top_return = top.get("total_return", 0)
            if isinstance(top_return, (int, float)):
                if top_return > 0.1:
                    verdict = "strong recent factor returns"
                elif top_return > 0.03:
                    verdict = "moderate recent factor returns"
                elif top_return > 0:
                    verdict = "weak recent factor returns"
                else:
                    verdict = "negative recent factor returns"

    return {
        "verdict": verdict,
        "analysis_type": "returns",
        "windows": windows,
        "shortest_window": shortest_window,
        "top_per_window": top_per_window,
        "bottom_per_window": bottom_per_window,
        "category_summary": category_summary,
        "factors_analyzed": len(self.factors) if self.factors else 0,
    }
```

### Layer 2: Flag rules (new — `core/factor_flags.py`)

```python
def generate_factor_flags(snapshot: dict) -> list[dict]:
    """
    Generate actionable flags from factor analysis snapshot.

    Input: dict from any of the 3 result get_agent_snapshot() methods.
    Dispatches by analysis_type.
    """
    if not snapshot:
        return []

    analysis_type = snapshot.get("analysis_type")
    if analysis_type == "correlations":
        return _correlation_flags(snapshot)
    elif analysis_type == "performance":
        return _performance_flags(snapshot)
    elif analysis_type == "returns":
        return _returns_flags(snapshot)
    return []


def _correlation_flags(snapshot: dict) -> list[dict]:
    flags = []
    verdict = snapshot.get("verdict", "")

    # No-data early return
    if verdict.startswith("no "):
        return [{"type": "insufficient_data", "severity": "info", "message": verdict}]

    # Use total_high_corr_count (pre-truncation count) for accurate flag messages
    pair_count = snapshot.get("total_high_corr_count", len(snapshot.get("high_correlation_pairs", [])))

    if pair_count >= 3:
        flags.append({
            "type": "many_high_correlations",
            "severity": "warning",
            "message": f"{pair_count} factor pairs with |correlation| > 0.7",
            "pair_count": pair_count,
        })
    elif pair_count > 0:
        flags.append({
            "type": "high_correlation_detected",
            "severity": "info",
            "message": f"{pair_count} factor pair(s) with |correlation| > 0.7",
            "pair_count": pair_count,
        })

    if pair_count == 0:
        flags.append({
            "type": "correlations_normal",
            "severity": "success",
            "message": "No factor pairs with |correlation| > 0.7",
        })

    return _sort_flags(flags)


def _performance_flags(snapshot: dict) -> list[dict]:
    flags = []
    verdict = snapshot.get("verdict", "")

    if verdict.startswith("no "):
        return [{"type": "insufficient_data", "severity": "info", "message": verdict}]

    top = snapshot.get("top_factors", [])
    bottom = snapshot.get("bottom_factors", [])

    if top and top[0].get("sharpe_ratio", 0) > 1.5:
        flags.append({
            "type": "exceptional_factor",
            "severity": "info",
            "message": f"Top factor {top[0]['ticker']} has Sharpe ratio {top[0]['sharpe_ratio']:.2f}",
            "ticker": top[0]["ticker"],
            "sharpe_ratio": top[0]["sharpe_ratio"],
        })

    if bottom:
        worst = bottom[0]  # bottom is reversed: worst-first
        if worst.get("sharpe_ratio", 0) < -0.5:
            flags.append({
                "type": "poor_factor_performance",
                "severity": "warning",
                "message": f"Worst factor {worst['ticker']} has Sharpe ratio {worst['sharpe_ratio']:.2f}",
                "ticker": worst["ticker"],
                "sharpe_ratio": worst["sharpe_ratio"],
            })

    if not flags:
        flags.append({
            "type": "performance_normal",
            "severity": "success",
            "message": "Factor performance within normal ranges",
        })

    return _sort_flags(flags)


def _returns_flags(snapshot: dict) -> list[dict]:
    flags = []
    verdict = snapshot.get("verdict", "")

    if verdict.startswith("no "):
        return [{"type": "insufficient_data", "severity": "info", "message": verdict}]

    top_per_window = snapshot.get("top_per_window", {})
    bottom_per_window = snapshot.get("bottom_per_window", {})

    # Use pre-computed shortest_window from snapshot (avoids clock drift)
    shortest = snapshot.get("shortest_window")

    if shortest and top_per_window.get(shortest):
        top = top_per_window[shortest]
        if top and isinstance(top[0], dict):
            top_return = top[0].get("total_return", 0)
            if isinstance(top_return, (int, float)) and top_return > 0.15:
                flags.append({
                    "type": "extreme_positive_return",
                    "severity": "info",
                    "message": f"Top factor returned {top_return:.1%} in {shortest} window",
                    "window": shortest,
                    "total_return": top_return,
                })

    if shortest and bottom_per_window.get(shortest):
        bottom = bottom_per_window[shortest]
        # bottom is ranked_list[-3:] (ranked best→worst), so [-1] is the absolute worst
        if bottom and isinstance(bottom[-1], dict):
            bot_return = bottom[-1].get("total_return", 0)
            if isinstance(bot_return, (int, float)) and bot_return < -0.10:
                flags.append({
                    "type": "extreme_negative_return",
                    "severity": "warning",
                    "message": f"Worst factor returned {bot_return:.1%} in {shortest} window",
                    "window": shortest,
                    "total_return": bot_return,
                })

    if not flags:
        flags.append({
            "type": "returns_normal",
            "severity": "success",
            "message": "Factor returns within normal ranges",
        })

    return _sort_flags(flags)


def _sort_flags(flags: list[dict]) -> list[dict]:
    severity_order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    flags.sort(key=lambda f: severity_order.get(f.get("severity"), 9))
    return flags
```

### Threshold constants

| Mode | Rule | Threshold | Rationale |
|------|------|-----------|-----------|
| correlations | many_high_correlations | >= 3 pairs with |r| > 0.7 | Multiple correlated factors is concerning |
| correlations | high_correlation_detected | 1-2 pairs with |r| > 0.7 | Notable but not alarming |
| correlations | correlations_normal | 0 pairs with |r| > 0.7 | Clean factor structure |
| performance | exceptional_factor | Sharpe > 1.5 | Unusually strong factor |
| performance | poor_factor_performance | Sharpe < -0.5 | Significantly negative |
| performance | performance_normal | No exceptional or poor | Normal ranges |
| returns | extreme_positive_return | > 15% in shortest window | Notable momentum |
| returns | extreme_negative_return | < -10% in shortest window | Significant loss |
| returns | returns_normal | No extremes | Normal ranges |

### Layer 3: Agent format composer (in `mcp_tools/factor_intelligence.py`)

```python
import json
from datetime import UTC, datetime
from pathlib import Path

_FACTOR_OUTPUT_DIR = Path("logs/factor_analysis")


def _build_agent_response(
    result,  # any of the 3 result types
    file_path: str | None = None,
) -> dict:
    """Compose decision-oriented factor analysis result for agent use."""
    from core.factor_flags import generate_factor_flags

    snapshot = result.get_agent_snapshot()
    flags = generate_factor_flags(snapshot)

    return {
        "status": "success",
        "format": "agent",
        "snapshot": snapshot,
        "flags": flags,
        "file_path": file_path,
    }


def _save_full_factor_analysis(result, analysis_type: str) -> str:
    """Save full factor analysis data to disk and return absolute path."""
    output_dir = _FACTOR_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    file_path = output_dir / f"factor_{analysis_type}_{timestamp}.json"

    try:
        payload = result.to_api_response()
        if not isinstance(payload, dict):
            payload = {"analysis_type": analysis_type}
    except Exception:
        payload = {"analysis_type": analysis_type}
    payload["status"] = "success"

    with file_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)

    return str(file_path.resolve())
```

### File output

When `output="file"`:

1. Run analysis as normal
2. Write full payload to `logs/factor_analysis/factor_{type}_{YYYYMMDD}_{HHMMSS}.json`
3. Attach `file_path` to whatever format response is returned

## Files to Modify

### 1. Modify: `core/result_objects.py`

**Add `get_agent_snapshot()` to each of the 3 result classes:**
- `FactorCorrelationResult.get_agent_snapshot()` — high correlation pairs, overlays available
- `FactorPerformanceResult.get_agent_snapshot()` — top/bottom factors by Sharpe, macro composites
- `FactorReturnsResult.get_agent_snapshot()` — top/bottom per window, category summary

### 2. New: `core/factor_flags.py`

- `generate_factor_flags(snapshot) -> list[dict]` — dispatches by `analysis_type`
- Internal `_correlation_flags()`, `_performance_flags()`, `_returns_flags()`
- Each produces flags specific to the analysis mode
- Sorted by severity

### 3. Modify: `mcp_tools/factor_intelligence.py`

**Add `_build_agent_response(result, file_path)`:**
- Works with any of the 3 result types (polymorphic via `get_agent_snapshot()`)

**Add `_save_full_factor_analysis(result, analysis_type)`:**
- Writes `to_api_response()` to `_FACTOR_OUTPUT_DIR`
- try/except fallback

**Update `get_factor_analysis()` signature:**
- Add `format="agent"` to the Literal enum
- Add `output: Literal["inline", "file"] = "inline"` parameter
- File write (`_save_full_factor_analysis`) happens BEFORE format dispatch. It calls `to_api_response()` internally (with try/except fallback) to persist full data. This is independent of the response format.
- `format="agent"` branch runs AFTER file write but BEFORE the existing `to_api_response()` call used by `format="full"`. Agent format uses `get_agent_snapshot()` instead of `to_api_response()` for the response.
- For `format="full"`, wrap `to_api_response()` in try/except with minimal fallback

### 4. Modify: `mcp_server.py`

- Add "agent" to the format enum for get_factor_analysis
- Add output parameter
- Pass through to underlying function

## Agent format example output (performance mode)

```json
{
  "status": "success",
  "format": "agent",

  "snapshot": {
    "verdict": "strong factor performance",
    "analysis_type": "performance",
    "top_factors": [
      {"ticker": "XLK", "sharpe_ratio": 1.650, "annual_return_pct": 28.50, "volatility_pct": 18.30},
      {"ticker": "XLC", "sharpe_ratio": 0.950, "annual_return_pct": 15.20, "volatility_pct": 14.50}
    ],
    "bottom_factors": [
      {"ticker": "XLE", "sharpe_ratio": -0.320, "annual_return_pct": -5.10, "volatility_pct": 22.40},
      {"ticker": "XLU", "sharpe_ratio": -0.150, "annual_return_pct": -2.30, "volatility_pct": 15.20},
      {"ticker": "XLI", "sharpe_ratio": 0.050, "annual_return_pct": 0.80, "volatility_pct": 16.10}
    ],
    "macro_composites": {
      "growth": {"sharpe_ratio": 0.850, "annual_return_pct": 12.30},
      "value": {"sharpe_ratio": 0.420, "annual_return_pct": 6.80}
    },
    "factors_analyzed": 25
  },

  "flags": [
    {
      "type": "exceptional_factor",
      "severity": "info",
      "message": "Top factor XLK has Sharpe ratio 1.65",
      "ticker": "XLK",
      "sharpe_ratio": 1.650
    }
  ],

  "file_path": null
}
```

### What each section answers for the agent:

| Section | Agent question (correlations) | Agent question (performance) | Agent question (returns) |
|---------|------------------------------|------------------------------|--------------------------|
| `verdict` | "Are factor correlations concerning?" | "How are factors performing?" | "What's the recent trend?" |
| `snapshot.*` | High correlation pairs, overlays | Top/bottom Sharpe, macros | Top/bottom per window |
| `flags` | Correlation concentration warnings | Exceptional or poor performers | Extreme return alerts |
| `file_path` | Full matrices for deep dive | All per-factor metrics | Complete rankings |

## Compatibility

- All existing formats (`full`, `summary`, `report`) success-path unchanged; `full` error-path now degrades gracefully
- `format="agent"` is purely additive
- `output="file"` works with any format
- Default format stays `"summary"` (no breaking change)
- `output` defaults to `"inline"` (no breaking change)
- `include` section filter still works with existing formats; `format="agent"` ignores `include`

## Decisions

1. **Snapshot nested under `"snapshot"` key.** Consistent with all other agent formats.
2. **Each result class gets its own `get_agent_snapshot()`.** Different data shape per mode, but all return a dict with `verdict` and `analysis_type`.
3. **Flags dispatch by `analysis_type`.** Single `generate_factor_flags()` entry point routes to mode-specific flag logic.
4. **Correlation threshold: |r| > 0.7.** Standard threshold for "high" correlation in finance.
5. **Performance verdict by best Sharpe.** > 1.0 strong, > 0.5 moderate, > 0 weak, <= 0 negative.
6. **Returns verdict from shortest window.** Selected by month-length map (`1m < 3m < 6m < 1y < 2y`), not by list index. `ytd` dynamically mapped to `max(current_month - 1, 1)` so it correctly reflects elapsed months (e.g., February → 1 month, July → 6 months). Most recent window is most actionable.
7. **Top 5 / bottom 3 for performance.** Asymmetric: more interest in top factors. Bottom always computed from full list (may overlap with top for small universes). Bottom reversed to show worst first.
8. **Top 3 / bottom 3 per window for returns.** Compact per-window summary.
9. **Correlation pairs sorted by abs value, tie-break by factor1 then factor2.** Fully deterministic ordering.
10. **`include` parameter ignored for agent format.** Agent format is pre-curated; section filtering doesn't apply. Implementation: branch `if format == "agent"` BEFORE the `include` filtering and the `to_api_response()` call used by `format="full"`. Note: when `output="file"`, `_save_full_factor_analysis()` independently calls `to_api_response()` for file persistence — this is separate from the response format path.
11. **File save has fallback.** If `to_api_response()` fails, falls back to minimal `{"analysis_type": ...}` payload.
12. **Normal-range success flags.** Each mode emits a "success" flag when nothing concerning is found. Prevents empty flags list.
13. **`annual_return` is 0-1 (decimal), multiplied by 100 for `_pct` fields.** Same pattern as volatility.
14. **Safe numeric coercion.** `_safe_float()` helper guards against None/string values from upstream. Defaults to 0.0. Applied in: DataFrame correlation extraction, dict fallback, macro composites, and per-factor metric access (performance mode). Returns mode rankings use `isinstance` type-checking instead, since ranking entries come from upstream code and may contain mixed types — `_safe_float` coercion to 0.0 would mask bad data rather than skip it.
15. **`bottom_per_window` ordering.** Rankings are sorted best→worst. `ranked_list[-3:]` gives the 3 worst in order less-bad→worst. So `bottom[-1]` is the absolute worst performer. Flags use `bottom[-1]` for the worst-return check.
16. **Dynamic `ytd` window length.** `ytd` mapped to `max(current_month - 1, 1)` using UTC month. In January, ytd=1 (same as 1m). In December, ytd=11. This prevents ytd from always dominating or being dominated in shortest-window selection.
17. **`ytd` tie-break.** When `ytd` and a named window (e.g., `1m`) have the same month-length, the named window is preferred via `(month_length, w == "ytd", w)` sort key. This makes selection deterministic.
18. **File naming collision acceptable.** Second-level timestamps match the pattern used in all other agent format tools. Concurrent calls within the same second are not a practical concern for MCP tool invocations. IO failures (mkdir, open, json.dump) propagate to the outer try/except in the MCP tool function, which returns `{"status": "error", ...}`. This matches the pattern in whatif and optimization tools.
19. **`total_high_corr_count` tracks pre-truncation count.** The snapshot stores the true number of high-correlation pairs before the top-5 truncation. Flags use this count for accurate severity assessment.
20. **Verdict thresholds use rounded values.** Performance verdict checks Sharpe after `round(..., 3)`. This is intentional — 3dp is sufficient precision, and boundary cases within rounding tolerance (e.g., 1.0004 rounding to 1.000) are within measurement noise. Flag thresholds (1.5, -0.5) also use the rounded snapshot values.
22. **Correlation matrices are assumed symmetric.** Both DataFrame and dict-form matrices come from pandas `corr()` or `to_dict()`, which produce symmetric data. Only the upper triangle is scanned. No reverse-direction fallback is needed.
21. **Returns shortest window uses ranked windows only.** `shortest_window` is selected from windows that exist in both `_WINDOW_ORDER` and `rankings` (with non-empty list data). This avoids selecting a window with no data. If no window qualifies, `shortest_window` is None and verdict stays generic.

## Test Plan

### `core/result_objects.py` — get_agent_snapshot tests

#### FactorCorrelationResult
- `test_correlation_snapshot_keys` — verdict, analysis_type, categories_analyzed, total_factors, high_correlation_pairs, total_high_corr_count, overlays_available
- `test_correlation_snapshot_high_corr_pairs` — pairs with |r| > 0.7 extracted
- `test_correlation_snapshot_no_high_corr` — no pairs above threshold → empty list, verdict "factor correlations normal"
- `test_correlation_snapshot_pairs_sorted` — sorted by abs correlation descending
- `test_correlation_snapshot_pairs_max5` — at most 5 pairs
- `test_correlation_snapshot_overlays` — available overlays listed
- `test_correlation_snapshot_dataframe_extraction` — handles pandas DataFrame matrices correctly
- `test_correlation_snapshot_tiebreak` — pairs with same abs correlation sorted by factor1 then factor2 alphabetically
- `test_correlation_snapshot_boundary_0_7` — pair with |r| = 0.7 exactly is NOT included (threshold is > 0.7, not >=)
- `test_correlation_snapshot_dict_fallback_safe_float` — dict-form matrices use _safe_float for None/string values
- `test_correlation_snapshot_dict_symmetric_extraction` — dict-form symmetric matrix extracts upper-triangle pairs correctly
- `test_correlation_snapshot_dataframe_nan_inf` — DataFrame with NaN/inf values are coerced to 0.0 and excluded from high-corr pairs
- `test_correlation_snapshot_empty_matrices` — no matrices → verdict "no correlation data available"
- `test_correlation_snapshot_total_count_vs_truncated` — when >5 high-corr pairs exist, total_high_corr_count reflects true count while pairs list is capped at 5

#### FactorPerformanceResult
- `test_performance_snapshot_keys` — verdict, analysis_type, top_factors, bottom_factors, macro_composites, factors_analyzed
- `test_performance_snapshot_top5_by_sharpe` — sorted by Sharpe descending
- `test_performance_snapshot_bottom3` — worst 3 by Sharpe
- `test_performance_snapshot_verdict_strong` — best Sharpe > 1.0 → "strong factor performance"
- `test_performance_snapshot_verdict_moderate` — best Sharpe in (0.5, 1.0] → "moderate factor performance"
- `test_performance_snapshot_verdict_weak` — best Sharpe in (0, 0.5] → "weak factor performance"
- `test_performance_snapshot_verdict_negative` — best Sharpe <= 0 → "negative factor performance"
- `test_performance_snapshot_verdict_no_data` — no valid factors → "no factor performance data"
- `test_performance_snapshot_annual_return_pct` — annual_return multiplied by 100
- `test_performance_snapshot_macro_composites` — macro composites extracted
- `test_performance_snapshot_macro_safe_float` — macro composites use _safe_float for None/string values
- `test_performance_snapshot_per_factor_safe_float` — per-factor metrics with None/string sharpe_ratio/annual_return/volatility coerce to 0.0 via _safe_float
- `test_performance_snapshot_sharpe_rounding_boundary` — raw Sharpe 1.0004 rounds to 1.000, classified as "moderate" not "strong" (verdict uses rounded value)
- `test_performance_snapshot_small_universe_overlap` — with <= 3 factors, top_factors and bottom_factors may overlap (acceptable per Decision 7)

#### FactorReturnsResult
- `test_returns_snapshot_keys` — verdict, analysis_type, windows, shortest_window, top_per_window, bottom_per_window, category_summary, factors_analyzed
- `test_returns_snapshot_top3_per_window` — at most 3 per window
- `test_returns_snapshot_bottom3_per_window` — bottom 3 per window
- `test_returns_snapshot_verdict_strong` — top return > 10% → "strong recent factor returns"
- `test_returns_snapshot_verdict_moderate` — top return in (3%, 10%] → "moderate recent factor returns"
- `test_returns_snapshot_verdict_weak` — top return in (0, 3%] → "weak recent factor returns"
- `test_returns_snapshot_verdict_negative` — top return <= 0 → "negative recent factor returns"
- `test_returns_snapshot_verdict_no_data` — empty rankings → "no factor returns data" (even if windows is non-empty)
- `test_returns_snapshot_windows_filtered` — windows list filtered to strings only (non-string values excluded)
- `test_returns_snapshot_shortest_window_selection` — verdict uses shortest window by month-length map, not list order
- `test_returns_snapshot_ytd_tiebreak` — when ytd and a named window have equal month-length, named window is preferred (use `unittest.mock.patch` to freeze `datetime.now` to a specific month)
- `test_returns_snapshot_ytd_january` — in January, ytd maps to 1 month (same as 1m), `1m` preferred over `ytd` (freeze datetime to January)
- `test_returns_snapshot_ytd_december` — in December, ytd maps to 11 months, shorter than 1y but longer than 6m (freeze datetime to December)
- `test_returns_snapshot_skips_unranked_windows` — window exists in `windows` but not in `rankings` → skipped; verdict uses next shortest ranked window
- `test_returns_snapshot_skips_empty_ranking_list` — window exists in `rankings` but with empty list → skipped
- `test_returns_snapshot_non_dict_ranking_entries` — ranking list with non-dict entries → verdict falls through to generic (isinstance guard)
- `test_returns_snapshot_non_numeric_total_return` — ranking entry with string total_return → verdict falls through to generic
- `test_returns_snapshot_ranking_only_keys` — window in `rankings` but not in `self.windows` → still considered for shortest window selection
- `test_returns_snapshot_bottom_ordering` — `bottom_per_window` entries are in ranked order (less-bad to worst), so `[-1]` is the absolute worst

### `core/factor_flags.py` tests

#### Correlation flags
- `test_many_high_correlations_flag` — >= 3 pairs → warning
- `test_high_correlation_detected_flag` — 1-2 pairs → info
- `test_correlations_normal_flag` — 0 pairs → success
- `test_correlation_flag_uses_total_count` — flag pair_count reflects total_high_corr_count (pre-truncation), not len(high_correlation_pairs)
- `test_sort_flags_helper` — _sort_flags puts warnings before info before success

#### Performance flags
- `test_exceptional_factor_flag` — Sharpe > 1.5 → info
- `test_exceptional_factor_boundary_1_5` — Sharpe = 1.5 exactly → no exceptional flag (threshold is > 1.5)
- `test_exceptional_factor_rounding_boundary` — raw Sharpe 1.5004 rounds to 1.500 in snapshot → no exceptional flag (flag reads rounded value)
- `test_poor_factor_performance_flag` — worst Sharpe < -0.5 → warning
- `test_poor_factor_boundary_neg_0_5` — worst Sharpe = -0.5 exactly → no poor flag (threshold is < -0.5)
- `test_poor_factor_rounding_boundary` — raw Sharpe -0.5004 rounds to -0.500 in snapshot → no poor flag (flag reads rounded value)
- `test_performance_normal_flag` — no exceptional or poor → success

#### Returns flags
- `test_extreme_positive_return_flag` — > 15% → info
- `test_extreme_positive_boundary_0_15` — return = 0.15 exactly → no flag (threshold is > 0.15)
- `test_extreme_negative_return_flag` — < -10% → warning
- `test_extreme_negative_boundary_neg_0_10` — return = -0.10 exactly → no flag (threshold is < -0.10)
- `test_returns_normal_flag` — no extremes → success
- `test_returns_flag_uses_shortest_window` — flag checks use the shortest window from the snapshot, not arbitrary window
- `test_returns_flag_reads_shortest_from_snapshot` — flags use `snapshot["shortest_window"]` directly (no recomputation)

#### Dispatch
- `test_dispatch_correlations` — analysis_type=correlations routes correctly
- `test_dispatch_performance` — analysis_type=performance routes correctly
- `test_dispatch_returns` — analysis_type=returns routes correctly
- `test_empty_snapshot_no_crash` — empty dict produces no flags
- `test_unknown_type_no_crash` — unknown analysis_type produces no flags
- `test_no_data_verdict_produces_insufficient_data_flag` — verdict starting with "no " produces insufficient_data info flag instead of normal/success flag (covers all 3 modes)

### `mcp_tools/factor_intelligence.py` agent format tests

- `test_agent_format_structure` — top-level keys: status, format, snapshot, flags, file_path
- `test_agent_format_snapshot_nested` — snapshot is nested dict with verdict

### File output tests

- `test_file_output_creates_file` — file written to logs/factor_analysis/
- `test_file_output_includes_type_in_filename` — filename contains analysis type
- `test_file_output_returns_file_path` — file_path is valid path
- `test_inline_output_no_file` — output="inline" does not create file
- `test_file_output_attaches_path_to_agent` — format="agent" + output="file" includes file_path
- `test_file_output_attaches_path_to_summary` — format="summary" + output="file" includes file_path
- `test_file_output_attaches_path_to_full` — format="full" + output="file" includes file_path
- `test_file_output_attaches_path_to_report` — format="report" + output="file" includes file_path
- `test_agent_format_ignores_include` — format="agent" with include parameter still returns full agent schema
- `test_full_format_fallback_on_error` — format="full" returns minimal payload when to_api_response() fails
- `test_file_save_fallback_on_error` — file save produces minimal payload when to_api_response() fails
- `test_file_save_fallback_on_non_dict` — file save produces minimal payload when to_api_response() returns non-dict
- `test_file_output_contains_full_payload` — saved file contains full to_api_response() data (not filtered by include param)

Note: IO failures during file save (mkdir, open, json.dump) propagate to the outer MCP tool try/except which returns `{"status": "error", ...}`. This is tested at the integration level, not per-tool unit tests (same pattern as whatif/optimization).
- `test_summary_format_with_include_and_file_output` — format="summary" + include=["correlations"] + output="file" returns filtered summary with file_path

### MCP server registration tests

- `test_mcp_server_format_enum_includes_agent` — verify "agent" in format enum
- `test_mcp_server_output_param_exists` — verify output parameter registered

## Implementation Order

1. Add `get_agent_snapshot()` to all 3 result classes in `core/result_objects.py`
2. Create `core/factor_flags.py` with dispatch and mode-specific flag generators
3. Add `_build_agent_response()` and `_save_full_factor_analysis()` to `mcp_tools/factor_intelligence.py`
4. Add `format="agent"` and `output` parameter to `get_factor_analysis()` in `mcp_tools/factor_intelligence.py`
5. Update format dispatch for each analysis_type branch + wrap `format="full"` in try/except fallback
6. Update `mcp_server.py` registration (add agent to format enum, add output param)
7. Write tests (getters → flags → composer)

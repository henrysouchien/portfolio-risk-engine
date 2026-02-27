# Plan: Agent-Optimized Performance Output

_Created: 2026-02-24_
_Status: **COMPLETE** (10 review rounds, implemented, live-tested)_
_Reference: `POSITIONS_AGENT_FORMAT_PLAN.md` (completed — same three-layer pattern)_

## Context

`get_performance` is the second most-called tool after `get_positions`. It has two modes: `hypothetical` (backtest current weights) and `realized` (actual transaction-based performance). The current `format="summary"` returns ~15-40 fields of raw metrics with no interpretation. The agent can't quickly answer "is this portfolio doing well?" or "should the user be concerned about anything?"

Meanwhile `format="full"` returns 8-20KB depending on mode, including formatted reports, monthly time series, and detailed metadata the agent doesn't need in-context.

Goal: Apply the same `format="agent"` + `output="file"` pattern proven in `get_positions` and `get_risk_analysis`.

## Current State

### Output formats

| Format | Mode | Size | What agent gets |
|--------|------|------|-----------------|
| `summary` | hypothetical | ~500B | 12 metrics + performance_category + key_insights. Usable but flat. |
| `summary` | realized | ~2-4KB | 40+ fields including nested income, PnL, data quality. Too much, unstructured. |
| `full` | either | ~8-20KB | Everything including monthly returns, formatted report, allocations. |
| `report` | either | ~3-5KB | Human-readable text. Good for display, not for reasoning. |

### What the agent actually needs

1. **Verdict** — Is this portfolio performing well, poorly, or average? One-word + supporting metrics.
2. **Key metrics** — Total return, annualized return, Sharpe, max drawdown, volatility (the 5 numbers that matter).
3. **Benchmark comparison** — Am I beating SPY? Alpha and excess return.
4. **Flags** — Underperformance, high drawdown, low Sharpe, data quality issues.
5. **P&L summary** (realized only) — Dollar P&L, income, unrealized gains.
6. **Period context** — When does this cover? How much data?

### What the agent does NOT need in-context

- Monthly returns time series (100+ data points)
- Full realized_metadata (complex nested structure with synthetic positions, dedup diagnostics, flow diagnostics)
- Formatted report text (agent generates its own narrative)
- Display formatting metadata (UI hints)
- Allocations dict (unless rebalancing)
- Monthly stats (average win/loss) — derived from the summary metrics

These belong in the file output for deep dives.

## Proposed Design

### Layer 1: Data accessors (on result objects in `core/result_objects.py`)

Both `PerformanceResult` and `RealizedPerformanceResult` get a new `get_agent_snapshot()` method that returns a compact, structured dict. This keeps the extraction logic on the result object (reusable by any consumer) rather than in the MCP tool.

#### On `PerformanceResult`:

```python
def get_agent_snapshot(self) -> dict:
    """Compact metrics for agent consumption. Hypothetical mode."""
    # Read raw dicts directly — do NOT use get_summary() which defaults None → 0
    # and would cause false flags.
    returns = self.returns or {}
    risk = self.risk_metrics or {}
    risk_adjusted = self.risk_adjusted_returns or {}
    benchmark = self.benchmark_analysis or {}
    period = self.analysis_period or {}
    benchmark_comp = self.benchmark_comparison or {}

    return {
        "mode": "hypothetical",
        "period": {
            "start_date": period.get("start_date"),
            "end_date": period.get("end_date"),
            "months": period.get("total_months"),
            "years": round(period.get("years", 0), 1),
        },
        "returns": {
            "total_return_pct": returns.get("total_return"),
            "annualized_return_pct": returns.get("annualized_return"),
            "best_month_pct": returns.get("best_month"),
            "worst_month_pct": returns.get("worst_month"),
            "win_rate_pct": returns.get("win_rate"),
        },
        "risk": {
            "volatility_pct": risk.get("volatility"),
            "max_drawdown_pct": risk.get("maximum_drawdown"),
            "sharpe_ratio": risk_adjusted.get("sharpe_ratio"),
            "sortino_ratio": risk_adjusted.get("sortino_ratio"),
        },
        "benchmark": {
            "ticker": benchmark.get("benchmark_ticker"),
            "alpha_annual_pct": benchmark.get("alpha_annual"),
            "beta": benchmark.get("beta"),
            "portfolio_return_pct": benchmark_comp.get("portfolio_total_return"),
            "benchmark_return_pct": benchmark_comp.get("benchmark_total_return"),
            "excess_return_pct": benchmark.get("excess_return"),
        },
        "verdict": self._categorize_performance(),
        "insights": self._generate_key_insights(),
    }
```

**Key change**: Reads raw `self.returns`, `self.risk_metrics` dicts directly instead of `get_summary()`. `get_summary()` defaults `None` → `0` for all metrics, which would cause false flags (e.g., a `0` Sharpe from missing data looks like a real poor value). By reading raw dicts with `.get()` (returning `None` by default), the flag layer can distinguish "metric not available" from "metric is zero".

#### On `RealizedPerformanceResult`:

```python
def get_agent_snapshot(self, benchmark_ticker: str = "SPY") -> dict:
    """Compact metrics for agent consumption. Realized mode."""
    meta = self.realized_metadata
    income = meta.income
    returns = self.returns or {}
    risk = self.risk_metrics or {}
    risk_adj = self.risk_adjusted_returns or {}
    benchmark = self.benchmark_analysis or {}
    period = self.analysis_period or {}

    # custom_window is set by _apply_date_window() when user requests a date range
    custom_window = getattr(self, "custom_window", None)

    snapshot = {
        "mode": "realized",
        "period": {
            "start_date": period.get("start_date"),
            "end_date": period.get("end_date"),
            "months": period.get("total_months"),
            "years": round(period.get("years", 0), 1),
            "inception_date": meta.inception_date,
        },
        "returns": {
            "total_return_pct": returns.get("total_return"),
            "annualized_return_pct": returns.get("annualized_return"),
            "best_month_pct": returns.get("best_month"),
            "worst_month_pct": returns.get("worst_month"),
            "win_rate_pct": returns.get("win_rate"),
        },
        "risk": {
            "volatility_pct": risk.get("volatility"),
            "max_drawdown_pct": risk.get("maximum_drawdown"),
            "sharpe_ratio": risk_adj.get("sharpe_ratio"),
            "sortino_ratio": risk_adj.get("sortino_ratio"),
        },
        "benchmark": {
            "ticker": benchmark.get("benchmark_ticker", benchmark_ticker),
            "alpha_annual_pct": benchmark.get("alpha_annual"),
            "beta": benchmark.get("beta"),
            "portfolio_return_pct": (self.benchmark_comparison or {}).get("portfolio_total_return"),
            "benchmark_return_pct": (self.benchmark_comparison or {}).get("benchmark_total_return"),
            "excess_return_pct": benchmark.get("excess_return"),
        },
        "pnl": {
            "nav_pnl_usd": meta.nav_pnl_usd,
            "realized_pnl": meta.realized_pnl,
            "unrealized_pnl": meta.unrealized_pnl,
        },
        "income": {
            "total": income.total if income else None,
            "dividends": income.dividends if income else None,
            "interest": income.interest if income else None,
            "yield_on_cost_pct": income.yield_on_cost if income else None,
            "yield_on_value_pct": income.yield_on_value if income else None,
        },
        "data_quality": {
            "coverage_pct": meta.data_coverage,
            "high_confidence": meta.high_confidence_realized,
            "nav_metrics_estimated": meta.nav_metrics_estimated,
            "synthetic_count": meta.synthetic_current_position_count or 0,
            "warning_count": len(meta.data_warnings or []),
        },
        "verdict": self._categorize_performance(),
        "insights": self._generate_key_insights(),
    }

    # Include custom_window context when date-windowed
    if custom_window:
        snapshot["custom_window"] = {
            "start_date": custom_window.get("start_date"),
            "end_date": custom_window.get("end_date"),
            "full_inception": custom_window.get("full_inception"),
            "note": custom_window.get("note"),
        }

    return snapshot
```

**Key changes vs round 1:**
1. Reads raw dicts directly (no `get_summary()` — avoids `None` → `0` defaults causing false flags)
2. Includes `custom_window` context when user requested a date range (period already shows windowed dates, but `custom_window` adds `full_inception` and the note about lot-based P&L being all-time)
3. Added `nav_metrics_estimated` to `data_quality` — the flag layer uses this to warn when NAV metrics are estimated rather than observed
4. Added `high_confidence` to `data_quality` — flag layer uses this for positive signal

Both methods return a consistent top-level structure (`mode`, `period`, `returns`, `risk`, `benchmark`, `verdict`, `insights`). Realized adds `pnl`, `income`, `data_quality`, and optionally `custom_window`.

### Layer 2: Flag rules (new — `core/performance_flags.py`)

Domain-level interpretive logic, following the `core/position_flags.py` pattern.

```python
def generate_performance_flags(
    snapshot: dict,
) -> list[dict]:
    """
    Generate actionable flags from performance snapshot.

    Input: dict from PerformanceResult.get_agent_snapshot() or
           RealizedPerformanceResult.get_agent_snapshot()
    Each flag: {type, severity, message, ...contextual_data}
    """
    flags = []
    returns = snapshot.get("returns", {})
    risk = snapshot.get("risk", {})
    benchmark = snapshot.get("benchmark", {})
    data_quality = snapshot.get("data_quality", {})
    mode = snapshot.get("mode", "hypothetical")

    # --- Underperformance flags ---

    # Negative total return
    total_ret = returns.get("total_return_pct")
    if total_ret is not None and total_ret < 0:
        flags.append({
            "type": "negative_total_return",
            "severity": "warning",
            "message": f"Portfolio is down {abs(total_ret):.1f}% total",
            "total_return_pct": round(total_ret, 2),
        })

    # Underperforming benchmark significantly (>5% annualized)
    alpha = benchmark.get("alpha_annual_pct")
    if alpha is not None and alpha < -5:
        flags.append({
            "type": "benchmark_underperformance",
            "severity": "warning",
            "message": f"Underperforming {benchmark.get('ticker', 'benchmark')} by {abs(alpha):.1f}% annually",
            "alpha_annual_pct": round(alpha, 2),
        })

    # --- Risk flags ---

    # Poor risk-adjusted returns (Sharpe < 0.3 over meaningful period)
    sharpe = risk.get("sharpe_ratio")
    period_years = snapshot.get("period", {}).get("years", 0)
    if sharpe is not None and period_years >= 1 and sharpe < 0.3:
        flags.append({
            "type": "low_sharpe",
            "severity": "warning" if sharpe < 0 else "info",
            "message": f"Sharpe ratio is {sharpe:.2f} (poor risk-adjusted returns)",
            "sharpe_ratio": round(sharpe, 3),
        })

    # Deep drawdown (< -20%, stored as negative)
    drawdown = risk.get("max_drawdown_pct")
    if drawdown is not None and drawdown < -20:
        flags.append({
            "type": "deep_drawdown",
            "severity": "warning",
            "message": f"Max drawdown of {abs(drawdown):.1f}% experienced",
            "max_drawdown_pct": round(drawdown, 2),
        })

    # High volatility (> 25% annualized)
    vol = risk.get("volatility_pct")
    if vol is not None and vol > 25:
        flags.append({
            "type": "high_volatility",
            "severity": "info",
            "message": f"Portfolio volatility is {vol:.1f}% (above average)",
            "volatility_pct": round(vol, 2),
        })

    # --- Data quality flags (realized only) ---

    if mode == "realized":
        coverage = data_quality.get("coverage_pct")
        if coverage is not None and coverage < 80:
            flags.append({
                "type": "low_data_coverage",
                "severity": "warning",
                "message": f"Transaction data covers only {coverage:.0f}% of portfolio",
                "coverage_pct": round(coverage, 1),
            })

        warning_count = data_quality.get("warning_count", 0)
        if warning_count > 3:
            flags.append({
                "type": "data_quality_issues",
                "severity": "info",
                "message": f"{warning_count} data quality warnings detected",
                "warning_count": warning_count,
            })

        synth_count = data_quality.get("synthetic_count", 0)
        if synth_count > 0:
            flags.append({
                "type": "synthetic_positions",
                "severity": "info",
                "message": f"{synth_count} position(s) inferred from current holdings (no opening trade found)",
                "synthetic_count": synth_count,
            })

        nav_estimated = data_quality.get("nav_metrics_estimated", False)
        if nav_estimated:
            flags.append({
                "type": "nav_metrics_estimated",
                "severity": "info",
                "message": "NAV-based metrics (return, drawdown) are estimated — not all cash flows observed",
            })

        high_confidence = data_quality.get("high_confidence", False)
        if high_confidence:
            flags.append({
                "type": "high_confidence",
                "severity": "success",
                "message": "Transaction coverage is high — realized metrics are reliable",
            })

    # --- Positive signals (severity: "success") ---

    excess = benchmark.get("excess_return_pct")
    if total_ret is not None and total_ret > 0 and excess is not None and excess > 0:
        flags.append({
            "type": "outperforming",
            "severity": "success",
            "message": f"Beating {benchmark.get('ticker', 'benchmark')} by {excess:.1f}% annualized excess return",
            "excess_return_pct": round(excess, 2),
        })

    # Sort: warnings first, then info, then success
    severity_order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    flags.sort(key=lambda f: severity_order.get(f.get("severity"), 9))

    return flags
```

### Pre-existing bug fix: `_categorize_performance()` thresholds

Both `PerformanceResult._categorize_performance()` and `RealizedPerformanceResult._categorize_performance()` compare `annualized_return` (stored in **percent**, e.g., `6.4`) against decimal-scale thresholds (e.g., `>= 0.15`). This means `6.4 >= 0.15` is always true, making the "excellent" category trivially easy to reach.

**Fix** (applied to both classes during implementation):

```python
def _categorize_performance(self) -> str:
    sharpe = self.risk_adjusted_returns.get("sharpe_ratio")
    annual_return = self.returns.get("annualized_return")
    if sharpe is None or annual_return is None:
        return "unknown"  # was "poor" — None means missing, not bad
    # Thresholds in percent (matching annualized_return units)
    if sharpe >= 1.5 and annual_return >= 15:
        return "excellent"
    if sharpe >= 1.0 and annual_return >= 10:
        return "good"
    if sharpe >= 0.5 and annual_return >= 5:
        return "fair"
    return "poor"
```

Changes: (a) thresholds changed from `0.15/0.10/0.05` to `15/10/5` to match percent units, (b) `None` → `"unknown"` instead of `"poor"` (missing data is not poor performance).

### Threshold constants

| Rule | Threshold | Rationale |
|------|-----------|-----------|
| Negative total return | < 0% | Portfolio is losing money |
| Benchmark underperformance | alpha < -5% annualized | Meaningful underperformance vs passive |
| Low Sharpe | < 0.3 (with >= 1yr data) | Poor compensation for risk taken |
| Deep drawdown | < -20% max drawdown (negative convention) | Significant peak-to-trough loss |
| High volatility | > 25% annualized | Above typical equity vol |
| Low data coverage | < 80% (realized only) | Missing transaction data could distort results |
| Data quality issues | > 3 warnings (realized only) | Multiple data integrity concerns |
| Synthetic positions | > 0 (realized only) | Inferred openings affect accuracy |
| NAV metrics estimated | `nav_metrics_estimated` is True (realized only) | Return/drawdown numbers are estimates |
| High confidence | `high_confidence` is True (realized only) | Positive signal — data is trustworthy |
| Outperforming | positive return + positive annualized excess return | Beating benchmark on annualized return basis |

### Layer 3: Agent format composer (in `mcp_tools/performance.py`)

Thin composition layer — calls Layer 1 getter and Layer 2 flags, shapes response. No domain logic.

```python
from core.result_objects import PerformanceResult, RealizedPerformanceResult

_PERFORMANCE_OUTPUT_DIR = Path("logs/performance")


def _build_agent_response(
    result: PerformanceResult | RealizedPerformanceResult,
    benchmark_ticker: str,
    file_path: str | None = None,
) -> dict:
    """Compose decision-oriented performance summary for agent use."""
    from core.performance_flags import generate_performance_flags

    # Layer 1: Data accessor — both classes implement get_agent_snapshot()
    # RealizedPerformanceResult accepts benchmark_ticker kwarg
    if isinstance(result, RealizedPerformanceResult):
        snapshot = result.get_agent_snapshot(benchmark_ticker=benchmark_ticker)
    else:
        snapshot = result.get_agent_snapshot()

    # Layer 2: Interpretive flags (domain logic in core/)
    flags = generate_performance_flags(snapshot)

    return {
        "status": "success",
        "format": "agent",
        "snapshot": snapshot,  # nested under "snapshot" key for cross-tool consistency
        "flags": flags,
        "file_path": file_path,
    }
```

**Key changes vs round 1:**
- Uses `isinstance()` check instead of `hasattr(result, 'realized_metadata')` — explicit type dispatch, not duck typing on internals.
- Snapshot nested under `"snapshot"` key (not spread with `**snapshot`) for cross-tool consistency with `get_positions(format="agent")` and `get_risk_analysis(format="agent")`.
- Uses module-level `_PERFORMANCE_OUTPUT_DIR` constant (testable via `monkeypatch`).

### File output

When `output="file"`:

1. Run performance analysis as normal
2. Write full payload to `logs/performance/performance_{mode}_{YYYYMMDD}_{HHMMSS}.json`
3. Attach `file_path` to whatever format response is returned (works with any format)

```python
def _save_full_performance(
    result: PerformanceResult | RealizedPerformanceResult,
    mode: str,
    benchmark_ticker: str = "SPY",
) -> str:
    """Save full performance data to disk and return absolute path."""
    output_dir = _PERFORMANCE_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    file_path = output_dir / f"performance_{mode}_{timestamp}.json"

    # RealizedPerformanceResult.to_api_response() accepts benchmark_ticker
    # (currently unused/deleted internally, but passing for forward-compat)
    if isinstance(result, RealizedPerformanceResult):
        payload = result.to_api_response(benchmark_ticker=benchmark_ticker)
    elif isinstance(result, PerformanceResult):
        payload = result.to_api_response()
    else:
        payload = result

    with file_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)

    return str(file_path.resolve())
```

## Files to Modify

### 1. Modify: `core/result_objects.py`

**Add `get_agent_snapshot()` to `PerformanceResult`:**
- Returns compact dict: mode, period, returns, risk, benchmark, verdict, insights
- Reads raw `self.returns`, `self.risk_metrics`, etc. directly (NOT `get_summary()` which defaults None→0)
- Reuses existing `_categorize_performance()`, `_generate_key_insights()`

**Add `get_agent_snapshot(benchmark_ticker)` to `RealizedPerformanceResult`:**
- Same structure as hypothetical plus: pnl, income, data_quality, optional custom_window
- Reads raw dicts directly (same pattern as hypothetical — NOT `to_summary()` or `get_summary()`)

### 2. New: `core/performance_flags.py`

- `generate_performance_flags(snapshot) -> list[dict]`
- All flag rules from the threshold table above
- Accepts the snapshot dict (not the result object) — keeps it decoupled
- Sorted by severity (warning > info > success)

### 3. Modify: `mcp_tools/performance.py`

**Add `_build_agent_response(result, benchmark_ticker, file_path)`:**
- Calls `result.get_agent_snapshot()` (Layer 1)
- Calls `generate_performance_flags()` from `core/performance_flags.py` (Layer 2)
- Nests snapshot under `"snapshot"` key (Layer 3)

**Add `_save_full_performance(result, mode, benchmark_ticker)`:**
- Writes `to_api_response(benchmark_ticker=...)` to `_PERFORMANCE_OUTPUT_DIR`
- Returns absolute path

**Update `get_performance()` signature:**
- Add `format="agent"` to the Literal enum
- Add `output: Literal["inline", "file"] = "inline"` parameter
- File write happens BEFORE format dispatch (matching positions pattern)

**Update format dispatch (both hypothetical and realized branches):**
```python
# File write before format dispatch
file_path = _save_full_performance(result, mode, benchmark_ticker) if output == "file" else None

if format == "agent":
    return _build_agent_response(result, benchmark_ticker, file_path=file_path)
elif format == "summary":
    response = { ... existing summary logic ... }
    if file_path:
        response["file_path"] = file_path
    return response
# ... other formats: attach file_path if present
```

### 4. Modify: `mcp_server.py`

- Add "agent" to the format enum for get_performance
- Add output parameter
- Pass through to underlying function

### 5. Update: `docs/interfaces/mcp.md`

- Add `format="agent"` and `output="file"` to performance tool docs

## Agent format example output (hypothetical mode)

```json
{
  "status": "success",
  "format": "agent",

  "snapshot": {
    "mode": "hypothetical",
    "period": {
      "start_date": "2020-01-31",
      "end_date": "2026-01-31",
      "months": 72,
      "years": 6.0
    },
    "returns": {
      "total_return_pct": 45.2,
      "annualized_return_pct": 6.4,
      "best_month_pct": 8.3,
      "worst_month_pct": -12.1,
      "win_rate_pct": 58.3
    },
    "risk": {
      "volatility_pct": 18.7,
      "max_drawdown_pct": -26.1,
      "sharpe_ratio": 0.22,
      "sortino_ratio": 0.31
    },
    "benchmark": {
      "ticker": "SPY",
      "alpha_annual_pct": -2.1,
      "beta": 0.85,
      "portfolio_return_pct": 45.2,
      "benchmark_return_pct": 62.8,
      "excess_return_pct": -2.0
    },
    "verdict": "poor",
    "insights": [
      "• Underperforming benchmark (-2.1% alpha)",
      "• Poor risk-adjusted returns (Sharpe: 0.22)",
      "• Significant drawdown risk (max: -26.1%)"
    ]
  },

  "flags": [
    {
      "type": "deep_drawdown",
      "severity": "warning",
      "message": "Max drawdown of 26.1% experienced",
      "max_drawdown_pct": -26.1
    },
    {
      "type": "low_sharpe",
      "severity": "info",
      "message": "Sharpe ratio is 0.22 (poor risk-adjusted returns)",
      "sharpe_ratio": 0.22
    }
  ],

  "file_path": null
}
```

## Agent format example output (realized mode)

```json
{
  "status": "success",
  "format": "agent",

  "snapshot": {
    "mode": "realized",
    "period": {
      "start_date": "2023-06-30",
      "end_date": "2026-01-31",
      "months": 31,
      "years": 2.6,
      "inception_date": "2023-06-15"
    },
    "returns": {
      "total_return_pct": 18.4,
      "annualized_return_pct": 7.0,
      "best_month_pct": 6.2,
      "worst_month_pct": -8.5,
      "win_rate_pct": 61.3
    },
    "risk": {
      "volatility_pct": 15.2,
      "max_drawdown_pct": -14.8,
      "sharpe_ratio": 0.46,
      "sortino_ratio": 0.62
    },
    "benchmark": {
      "ticker": "SPY",
      "alpha_annual_pct": 1.2,
      "beta": 0.72,
      "portfolio_return_pct": 18.4,
      "benchmark_return_pct": 22.1,
      "excess_return_pct": -3.7
    },
    "pnl": {
      "nav_pnl_usd": 12840.50,
      "realized_pnl": 4200.00,
      "unrealized_pnl": 8640.50
    },
    "income": {
      "total": 6720.00,
      "dividends": 6320.00,
      "interest": 400.00,
      "yield_on_cost_pct": 5.8,
      "yield_on_value_pct": 5.2
    },
    "data_quality": {
      "coverage_pct": 92.5,
      "high_confidence": true,
      "nav_metrics_estimated": false,
      "synthetic_count": 2,
      "warning_count": 1
    },
    "verdict": "poor",
    "insights": [
      "• Poor risk-adjusted returns (Sharpe: 0.46)"
    ]
  },

  "flags": [
    {
      "type": "synthetic_positions",
      "severity": "info",
      "message": "2 position(s) inferred from current holdings (no opening trade found)",
      "synthetic_count": 2
    },
    {
      "type": "high_confidence",
      "severity": "success",
      "message": "Transaction coverage is high — realized metrics are reliable"
    }
  ],

  "file_path": null
}
```

### What each section answers for the agent:

| Section | Agent question |
|---------|---------------|
| `snapshot.period` | "How long does this data cover?" |
| `snapshot.returns` | "How much money has the portfolio made?" |
| `snapshot.risk` | "How risky is this portfolio?" |
| `snapshot.benchmark` | "Is the user beating the market?" |
| `snapshot.pnl` | "What's the dollar P&L?" (realized only) |
| `snapshot.income` | "How much income does this generate?" (realized only) |
| `snapshot.data_quality` | "Can I trust these numbers?" (realized only) |
| `snapshot.custom_window` | "Is this a date-windowed view?" (realized only, when start/end_date set) |
| `snapshot.verdict` | "One-word assessment?" |
| `snapshot.insights` | "What should I tell the user?" |
| `flags` | "What deserves attention?" |
| `file_path` | "Where's the full data for deep dives?" |

## Compatibility

- All existing formats (`full`, `summary`, `report`) unchanged except: `_categorize_performance()` bug fix changes `performance_category` values across all formats (was almost always "excellent" due to percent-vs-decimal bug)
- `format="agent"` is purely additive
- `output="file"` works with any format
- Default format stays `"summary"` (no breaking change)
- `output` defaults to `"inline"` (no breaking change)
- Both hypothetical and realized modes support agent format

## Decisions

1. **Snapshot nested under `"snapshot"` key.** Follows the same nesting pattern as `get_positions(format="agent")` and `get_risk_analysis(format="agent")` — domain data in a nested key, flags and file_path at top level. Positions also has `top_holdings`, `exposure`, `cache_info` at top level; performance keeps it simpler since the snapshot sections are already semantically distinct. Top-level response: `status`, `format`, `snapshot`, `flags`, `file_path`.
2. **`get_agent_snapshot()` lives on both result classes.** Same method name, different implementations. Hypothetical doesn't have PnL/income/data_quality. Realized does. The MCP composer dispatches via `isinstance()` (not `hasattr` on internals).
3. **Flags take the snapshot dict, not the result object.** Decouples flag logic from result internals. Any dict with the right shape works (enables testing with plain dicts).
4. **`severity: "success"` for positive signals.** Unlike position flags (only warning/info), performance flags include good news like "outperforming benchmark" and "high confidence data". Helps the agent decide what to highlight.
5. **Sharpe flag requires >= 1 year of data.** Sharpe is statistically meaningless with < 12 months. Sortino is included in the snapshot for reference but has no dedicated flag (Sharpe alone is sufficient for the "poor risk-adjusted returns" signal).
6. **Drawdown stored as negative number.** Consistent with how the engine returns it. Flag checks `< -20` not `> 20`.
7. **`_save_full_performance()` uses mode in filename.** `performance_hypothetical_20260224_*.json` vs `performance_realized_20260224_*.json` — agent can tell which is which from the filename.
8. **`output="file"` writes to `_PERFORMANCE_OUTPUT_DIR`** (module constant, defaults to `Path("logs/performance")`). Gitignored directory, same pattern as positions. Module constant enables `monkeypatch` in tests.
9. **`_categorize_performance()` bug fix included.** Both classes have a pre-existing bug where `annualized_return` (percent) is compared against decimal thresholds. We fix this as part of implementation: thresholds changed to percent scale (`15/10/5` instead of `0.15/0.10/0.05`), and `None` → `"unknown"` instead of `"poor"`.
10. **`get_agent_snapshot()` reads raw dicts, not `get_summary()`.** `get_summary()` defaults `None` → `0` for all metrics. This would cause false flags (e.g., Sharpe `0` from missing data looks like poor performance). Raw `.get()` returns `None` so the flag layer can distinguish missing from zero.
11. **Realized snapshot includes `custom_window` when present.** When the user passes `start_date`/`end_date`, `_apply_date_window()` creates a `custom_window` dict on the result. The snapshot surfaces this so the agent knows lot-based P&L is all-time while return/risk metrics are windowed.
12. **Realized `data_quality` includes `nav_metrics_estimated` and `high_confidence`.** These were in `realized_metadata` but omitted from the original plan. `nav_metrics_estimated=True` means NAV metrics are best-effort estimates. `high_confidence=True` is a positive signal the flag layer uses.

## Test Plan

### `core/result_objects.py` — get_agent_snapshot tests

- `test_hypothetical_agent_snapshot_keys` — all expected keys present (mode, period, returns, risk, benchmark, verdict, insights)
- `test_hypothetical_agent_snapshot_no_pnl` — hypothetical mode does NOT include pnl, income, data_quality
- `test_realized_agent_snapshot_keys` — all expected keys including pnl, income, data_quality
- `test_realized_agent_snapshot_income_fields` — income section has total, dividends, interest, yields
- `test_realized_agent_snapshot_data_quality` — data_quality section has coverage, high_confidence, nav_metrics_estimated, synthetic_count, warning_count
- `test_realized_agent_snapshot_custom_window` — custom_window section present when `_apply_date_window()` was applied
- `test_agent_snapshot_empty_result` — handles empty/zeroed result without crash
- `test_agent_snapshot_uses_raw_dicts_not_get_summary` — None values preserved (not defaulted to 0)

### `core/performance_flags.py` tests

- `test_negative_total_return_flag` — negative return triggers warning
- `test_positive_return_no_flag` — positive return does not trigger negative_total_return
- `test_benchmark_underperformance_flag` — alpha < -5% triggers warning
- `test_mild_underperformance_no_flag` — alpha -3% does not trigger
- `test_low_sharpe_warning` — Sharpe < 0 with >= 1yr triggers warning severity
- `test_low_sharpe_info` — Sharpe 0.2 with >= 1yr triggers info severity
- `test_sharpe_not_flagged_short_period` — Sharpe < 0.3 with < 1yr does NOT trigger
- `test_deep_drawdown_flag` — drawdown < -20% triggers warning
- `test_high_volatility_flag` — vol > 25% triggers info
- `test_low_data_coverage_flag` — coverage < 80% (realized) triggers warning
- `test_data_quality_issues_flag` — > 3 warnings triggers info
- `test_synthetic_positions_flag` — synthetic_count > 0 triggers info
- `test_outperforming_flag` — positive return + positive excess return triggers success
- `test_nav_metrics_estimated_flag` — `nav_metrics_estimated=True` triggers info flag
- `test_high_confidence_flag` — `high_confidence=True` triggers success flag
- `test_data_quality_flags_only_in_realized` — hypothetical mode skips data quality flags
- `test_flags_sorted_by_severity` — warnings before info before success
- `test_empty_snapshot_no_crash` — empty dict produces no flags

### `core/result_objects.py` — `_categorize_performance()` fix tests

- `test_categorize_performance_percent_thresholds` — verify Sharpe 1.5 + return 15% = "excellent" (not triggered by 0.15%)
- `test_categorize_performance_none_returns_unknown` — None metrics → "unknown" (not "poor")
- `test_categorize_performance_fair` — Sharpe 0.5 + return 6% = "fair"

### `mcp_tools/performance.py` agent format tests

- `test_agent_format_hypothetical_structure` — top-level keys: status, format, snapshot, flags, file_path
- `test_agent_format_realized_structure` — snapshot includes pnl, income, data_quality
- `test_agent_format_calls_getter` — verify delegation to get_agent_snapshot() via isinstance dispatch
- `test_agent_format_has_flags` — flags list present in response
- `test_agent_format_snapshot_nested` — snapshot is nested dict (not spread at top level)

### File output tests

- `test_file_output_creates_file` — file written to logs/performance/
- `test_file_output_includes_mode_in_filename` — filename contains mode
- `test_file_output_returns_file_path` — file_path in response is valid path
- `test_inline_output_no_file` — output="inline" does not create file
- `test_file_output_attaches_path_to_summary` — format="summary" + output="file" includes file_path in response
- `test_file_output_attaches_path_to_report` — format="report" + output="file" includes file_path in response

## Implementation Order

1. Add `get_agent_snapshot()` to `PerformanceResult` in `core/result_objects.py`
2. Add `get_agent_snapshot(benchmark_ticker)` to `RealizedPerformanceResult` in `core/result_objects.py`
3. Create `core/performance_flags.py` with `generate_performance_flags()`
4. Add `_build_agent_response()` and `_save_full_performance()` to `mcp_tools/performance.py`
5. Add `format="agent"` and `output` parameter to `get_performance()` in `mcp_tools/performance.py`
6. Update format dispatch for both hypothetical and realized branches
7. Update `mcp_server.py` registration (add agent to format enum, add output param)
8. Write tests (getters → flags → composer)
9. Verify via MCP live call: `get_performance(format="agent")` and `get_performance(mode="realized", format="agent")`

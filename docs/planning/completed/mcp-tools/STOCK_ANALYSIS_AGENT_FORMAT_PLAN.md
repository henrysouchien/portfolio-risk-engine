# Plan: Agent-Optimized Stock Analysis Output

_Created: 2026-02-24_
_Status: **COMPLETE** (live-tested)_
_Reference: `TRADING_ANALYSIS_AGENT_FORMAT_PLAN.md`, `PERFORMANCE_AGENT_FORMAT_PLAN.md` (same three-layer pattern)_

## Context

`analyze_stock` runs standalone single-stock risk analysis — volatility, market regression (beta/alpha/R²), multi-factor exposures, and (for bonds) interest-rate sensitivity. The current `format="summary"` returns metrics but no interpretation. The agent can't quickly answer "is this stock risky?" or "what kind of stock is this?"

The MCP agent audit grades this tool **B** — compact output but missing risk characterization, interpretive flags, and a verdict.

Goal: Apply the same `format="agent"` + `output="file"` pattern proven in positions, performance, and trading analysis.

## Current State

### Output formats

| Format | Size | What agent gets |
|--------|------|-----------------|
| `summary` | ~500B-1KB | Volatility, beta, alpha, R², factor exposures. Usable but no interpretation. |
| `full` | ~2-5KB | Everything: raw vol_metrics, regression_metrics, factor_summary DataFrame-as-dict, factor_proxies, analysis_metadata. More than needed. |
| `report` | ~1-2KB | Human-readable CLI text. Good for display, not for agent reasoning. |

### What the agent actually needs

1. **Verdict** — Is this a risky stock? One-word + supporting description.
2. **Key metrics** — Volatility, beta, alpha, R², Sharpe, max drawdown.
3. **Factor profile** — Factor exposures (beta coefficients per factor).
4. **Risk characterization flags** — High beta, high vol, low R², growth-tilted, rate-sensitive, etc.
5. **Bond analytics** — Interest rate beta, effective duration (when applicable).

### What the agent does NOT need in-context

- Raw `vol_metrics` dict with internal key names (`monthly_vol`, `annual_vol`)
- Raw `regression_metrics` dict with internal key names (`idio_vol_m`)
- Factor summary DataFrame-as-dict
- Factor proxy mappings
- Analysis metadata (timestamps, benchmark names)
- `risk_metrics` fallback dict

These belong in the file output for deep dives.

## Proposed Design

### Layer 1: Data accessor (on `StockAnalysisResult` in `core/result_objects.py`)

New `get_agent_snapshot()` method that returns a compact, structured dict.

```python
def get_agent_snapshot(self) -> dict:
    """Compact metrics for agent consumption."""
    vol = self.volatility_metrics
    reg = self.regression_metrics or self.risk_metrics or {}

    # Preserve None for missing data (flags gate on None)
    _annual_raw = vol.get("annual_vol")
    _monthly_raw = vol.get("monthly_vol")
    annual_vol = float(_annual_raw) if _annual_raw is not None else None
    monthly_vol = float(_monthly_raw) if _monthly_raw is not None else None
    sharpe = vol.get("sharpe_ratio")  # may be None on most paths
    max_drawdown = vol.get("max_drawdown")  # may be None on most paths

    # Preserve None for missing data (flags gate on None)
    _beta_raw = reg.get("beta")
    _alpha_raw = reg.get("alpha")
    _r2_raw = reg.get("r_squared")
    _idio_raw = reg.get("idio_vol_m")
    beta = float(_beta_raw) if _beta_raw is not None else None
    alpha = float(_alpha_raw) if _alpha_raw is not None else None
    r_squared = float(_r2_raw) if _r2_raw is not None else None
    idio_vol = float(_idio_raw) if _idio_raw is not None else None

    # Factor exposures: {factor_name: beta_value}
    # Primary: factor_summary DataFrame → dict via getter
    # Fallback: factor_exposures metadata dict → extract betas
    factor_betas = self.get_factor_exposures()
    if not factor_betas and self.factor_exposures:
        factor_betas = {
            name: float(exp["beta"])
            for name, exp in self.factor_exposures.items()
            if isinstance(exp, dict) and exp.get("beta") is not None
        }

    # Risk characterization verdict
    _RISK_VERDICT = {
        "very_high": "very high risk",
        "high": "high risk",
        "moderate": "moderate risk",
        "low": "low risk",
    }
    # Rate sensitivity contributes to risk for bonds
    rate_beta = getattr(self, "interest_rate_beta", None)
    rate_risk = abs(rate_beta) if rate_beta is not None else 0

    _vol = annual_vol or 0
    _beta = abs(beta) if beta is not None else 0

    if _vol > 0.50 or _beta > 2.0 or rate_risk > 8.0:
        risk_level = "very_high"
    elif _vol > 0.30 or _beta > 1.5 or rate_risk > 5.0:
        risk_level = "high"
    elif _vol > 0.15 or _beta > 1.0 or rate_risk > 2.0:
        risk_level = "moderate"
    else:
        risk_level = "low"

    snapshot = {
        "ticker": self.ticker,
        "verdict": _RISK_VERDICT[risk_level],
        "risk_level": risk_level,
        "analysis_type": getattr(self, "analysis_type", "unknown"),
        "analysis_period": getattr(self, "analysis_period", {}),
        "volatility": {
            "annual_pct": round(annual_vol * 100, 1) if annual_vol is not None else None,
            "monthly_pct": round(monthly_vol * 100, 1) if monthly_vol is not None else None,
            "sharpe_ratio": round(sharpe, 2) if sharpe is not None else None,
            "max_drawdown_pct": round(max_drawdown * 100, 1) if max_drawdown is not None else None,
        },
        "regression": {
            "beta": round(beta, 3) if beta is not None else None,
            "alpha_monthly_pct": round(alpha * 100, 3) if alpha is not None else None,
            "r_squared": round(r_squared, 3) if r_squared is not None else None,
            "idiosyncratic_vol_monthly_pct": round(idio_vol * 100, 2) if idio_vol is not None else None,
        },
        "factor_exposures": {k: round(float(v), 3) for k, v in factor_betas.items() if v is not None} if factor_betas else {},
    }

    # Bond analytics (when available)
    if self.interest_rate_beta is not None:
        snapshot["bond_analytics"] = {
            "interest_rate_beta": round(self.interest_rate_beta, 3),
            "effective_duration": round(self.effective_duration, 2) if self.effective_duration is not None else None,
            "rate_r_squared": round(self.rate_regression_r2, 3) if self.rate_regression_r2 is not None else None,
            "key_rate_breakdown": {k: round(v, 3) for k, v in self.key_rate_breakdown.items()} if self.key_rate_breakdown else {},
        }

    return snapshot
```

### Layer 2: Flag rules (new — `core/stock_flags.py`)

Domain-level interpretive logic, following the established flag pattern.

```python
def generate_stock_flags(snapshot: dict) -> list[dict]:
    """
    Generate risk characterization flags from stock analysis snapshot.

    Input: dict from StockAnalysisResult.get_agent_snapshot()
    Each flag: {type, severity, message, ...contextual_data}
    """
    flags = []
    vol = snapshot.get("volatility", {})
    reg = snapshot.get("regression", {})
    factors = snapshot.get("factor_exposures", {})
    bond = snapshot.get("bond_analytics", {})

    annual_vol = vol.get("annual_pct")
    beta = reg.get("beta")
    r_squared = reg.get("r_squared")
    sharpe = vol.get("sharpe_ratio")
    max_dd = vol.get("max_drawdown_pct")

    rate_beta_val = bond.get("interest_rate_beta")
    # No early return — per-flag None guards handle missing data

    # --- Volatility flags ---

    if annual_vol is not None and annual_vol > 50:
        flags.append({
            "type": "very_high_volatility",
            "severity": "warning",
            "message": f"Annual volatility is {annual_vol:.0f}% — extremely volatile",
            "annual_vol_pct": annual_vol,
        })
    elif annual_vol is not None and annual_vol > 30:
        flags.append({
            "type": "high_volatility",
            "severity": "info",
            "message": f"Annual volatility is {annual_vol:.0f}% — above average risk",
            "annual_vol_pct": annual_vol,
        })

    # --- Beta flags ---

    if beta is not None and abs(beta) > 2.0:
        flags.append({
            "type": "extreme_beta",
            "severity": "warning",
            "message": f"Beta is {beta:.2f} — moves more than 2x the market",
            "beta": beta,
        })
    elif beta is not None and abs(beta) > 1.5:
        flags.append({
            "type": "high_beta",
            "severity": "info",
            "message": f"Beta is {beta:.2f} — significantly more volatile than market",
            "beta": beta,
        })
    elif beta is not None and abs(beta) < 0.3:
        flags.append({
            "type": "low_beta",
            "severity": "info",
            "message": f"Beta is {beta:.2f} — low market sensitivity (defensive)",
            "beta": beta,
        })

    # --- Model quality flags ---

    if r_squared is not None and r_squared < 0.3:
        flags.append({
            "type": "low_r_squared",
            "severity": "info",
            "message": f"R² is {r_squared:.2f} — market/factor model explains little of this stock's moves",
            "r_squared": r_squared,
        })

    # --- Drawdown flags ---

    if max_dd is not None and max_dd < -50.0:
        flags.append({
            "type": "deep_drawdown",
            "severity": "warning",
            "message": f"Max drawdown is {max_dd:.0f}% — experienced severe peak-to-trough decline",
            "max_drawdown_pct": max_dd,
        })

    # --- Sharpe flags ---

    if sharpe is not None and sharpe < 0:
        flags.append({
            "type": "negative_sharpe",
            "severity": "warning",
            "message": f"Sharpe ratio is {sharpe:.2f} — negative risk-adjusted returns",
            "sharpe_ratio": sharpe,
        })
    elif sharpe is not None and sharpe > 1.5:
        flags.append({
            "type": "strong_sharpe",
            "severity": "success",
            "message": f"Sharpe ratio is {sharpe:.2f} — excellent risk-adjusted returns",
            "sharpe_ratio": sharpe,
        })

    # --- Factor tilt flags ---

    momentum_beta = factors.get("momentum")
    value_beta = factors.get("value")
    if momentum_beta is not None and abs(momentum_beta) > 0.5:
        direction = "positive" if momentum_beta > 0 else "negative"
        flags.append({
            "type": "momentum_tilt",
            "severity": "info",
            "message": f"Strong {direction} momentum exposure ({momentum_beta:+.2f})",
            "momentum_beta": momentum_beta,
        })
    if value_beta is not None and abs(value_beta) > 0.5:
        style = "value" if value_beta > 0 else "growth"
        flags.append({
            "type": "style_tilt",
            "severity": "info",
            "message": f"Strong {style} tilt (value beta: {value_beta:+.2f})",
            "value_beta": value_beta,
        })

    # --- Bond/rate sensitivity flags ---

    if rate_beta_val is not None and abs(rate_beta_val) > 1.0:
        flags.append({
            "type": "rate_sensitive",
            "severity": "info",
            "message": f"Interest rate beta is {rate_beta_val:+.2f} — meaningful rate sensitivity",
            "interest_rate_beta": rate_beta_val,
        })

    # --- Positive signals ---

    if (annual_vol is not None and beta is not None and r_squared is not None
            and 15 <= annual_vol <= 25 and 0.5 <= beta <= 1.2 and r_squared >= 0.5):
        flags.append({
            "type": "well_behaved",
            "severity": "success",
            "message": "Moderate volatility, reasonable beta, and good model fit — well-behaved stock",
        })

    # Sort: warnings first, then info, then success
    severity_order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    flags.sort(key=lambda f: severity_order.get(f.get("severity"), 9))

    return flags
```

### Threshold constants

| Rule | Threshold | Rationale |
|------|-----------|-----------|
| Very high volatility | > 50% annual | Extremely risky |
| High volatility | > 30% annual | Above average risk |
| Extreme beta | abs > 2.0 | Moves 2x+ the market |
| High beta | abs > 1.5 | Significantly more volatile than market |
| Low beta | abs < 0.3 | Defensive/low market sensitivity |
| Low R² | < 0.3 (includes 0.0) | Factor model explains little |
| Deep drawdown | < -50% max drawdown | Severe historical decline |
| Negative Sharpe | < 0 | Negative risk-adjusted returns |
| Strong Sharpe | > 1.5 | Excellent risk-adjusted returns |
| Momentum tilt | abs > 0.5 | Strong momentum factor exposure |
| Style tilt | abs > 0.5 | Strong value/growth factor tilt |
| Rate sensitive | abs > 1.0 interest rate beta | Meaningful rate sensitivity |
| Well-behaved | 15-25% vol, 0.5-1.2 beta, R² >= 0.5 | Moderate, predictable stock |

**Risk verdict thresholds (incorporating rate sensitivity):**

| Risk level | Equity criteria | Bond criteria |
|------------|----------------|---------------|
| very_high | vol > 50% OR abs(beta) > 2.0 | abs(rate_beta) > 8.0 |
| high | vol > 30% OR abs(beta) > 1.5 | abs(rate_beta) > 5.0 |
| moderate | vol > 15% OR abs(beta) > 1.0 | abs(rate_beta) > 2.0 |
| low | Everything else | Everything else |

### Layer 3: Agent format composer (in `mcp_tools/stock.py`)

Thin composition layer.

```python
from core.result_objects import StockAnalysisResult

_STOCK_OUTPUT_DIR = Path("logs/stock")


def _build_agent_response(
    result: StockAnalysisResult,
    file_path: str | None = None,
) -> dict:
    """Compose decision-oriented stock analysis for agent use."""
    from core.stock_flags import generate_stock_flags

    snapshot = result.get_agent_snapshot()
    flags = generate_stock_flags(snapshot)

    return {
        "status": "success",
        "format": "agent",
        "snapshot": snapshot,
        "flags": flags,
        "file_path": file_path,
    }
```

### File output

When `output="file"`:

1. Run stock analysis as normal
2. Write full payload to `logs/stock/stock_{ticker}_{YYYYMMDD}_{HHMMSS}.json`
3. Attach `file_path` to whatever format response is returned

```python
def _save_full_stock(result: StockAnalysisResult, ticker: str) -> str:
    """Save full stock data to disk and return absolute path."""
    output_dir = _STOCK_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    file_path = output_dir / f"stock_{ticker}_{timestamp}.json"

    payload = result.to_api_response()
    payload["status"] = "success"

    with file_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)

    return str(file_path.resolve())
```

## Files to Modify

### 1. Modify: `core/result_objects.py`

**Add `get_agent_snapshot()` to `StockAnalysisResult`:**
- Returns compact dict: ticker, verdict, risk_level, analysis_type, analysis_period, volatility, regression, factor_exposures, bond_analytics (optional)
- Converts internal decimal values to percentage for agent readability (annual_vol 0.25 → 25.0%)
- Risk verdict derived from volatility + beta + rate sensitivity thresholds
- Alpha labeled `alpha_monthly_pct` (monthly OLS intercept), idio vol labeled `idiosyncratic_vol_monthly_pct`
- Sharpe may be present on simple regression path, absent on multi-factor; max_drawdown is generally absent on both paths unless separately computed. Both treated as optional.
- Uses existing `get_factor_exposures()` with fallback to `factor_exposures` metadata dict
- Falls back to `risk_metrics` when `regression_metrics` is empty (simple regression path)
- None-preserving conversion: missing metrics stay None (not coerced to 0); only verdict threshold comparison defaults to 0

### 2. New: `core/stock_flags.py`

- `generate_stock_flags(snapshot) -> list[dict]`
- All flag rules from the threshold table
- Accepts the snapshot dict (not the result object) — decoupled
- No minimum count gates needed (single-stock analysis always has data)
- Sorted by severity (warning > info > success)

### 3. Modify: `mcp_tools/stock.py`

**Add `_build_agent_response(result, file_path)`:**
- Calls `result.get_agent_snapshot()` (Layer 1)
- Calls `generate_stock_flags()` from `core/stock_flags.py` (Layer 2)
- Nests snapshot under `"snapshot"` key (Layer 3)

**Add `_save_full_stock(result, ticker)`:**
- Writes `to_api_response()` to `_STOCK_OUTPUT_DIR`
- Returns absolute path

**Update `analyze_stock()` signature:**
- Add `format="agent"` to the Literal enum
- Add `output: Literal["inline", "file"] = "inline"` parameter
- File write happens BEFORE format dispatch

**Update format dispatch:**
```python
# File write before format dispatch
file_path = _save_full_stock(result, ticker) if output == "file" else None

if format == "agent":
    return _build_agent_response(result, file_path=file_path)
elif format == "summary":
    response = {... existing summary logic ...}
    if file_path:
        response["file_path"] = file_path
    return response
# ... other formats: attach file_path if present
```

### 4. Modify: `mcp_server.py`

- Add "agent" to the format enum for analyze_stock
- Add output parameter
- Pass through to underlying function

## Agent format example output

```json
{
  "status": "success",
  "format": "agent",

  "snapshot": {
    "ticker": "AAPL",
    "verdict": "moderate risk",
    "risk_level": "moderate",
    "analysis_type": "multi_factor",
    "analysis_period": {"start_date": "2023-02-24", "end_date": "2026-02-24"},
    "volatility": {
      "annual_pct": 24.5,
      "monthly_pct": 7.1,
      "sharpe_ratio": null,
      "max_drawdown_pct": null
    },
    "regression": {
      "beta": 1.12,
      "alpha_monthly_pct": 0.32,
      "r_squared": 0.72,
      "idiosyncratic_vol_monthly_pct": 4.80
    },
    "factor_exposures": {
      "market": 1.15,
      "momentum": 0.35,
      "value": -0.22,
      "industry": 0.88,
      "subindustry": 0.45
    }
  },

  "flags": [
    {
      "type": "well_behaved",
      "severity": "success",
      "message": "Moderate volatility, reasonable beta, and good model fit — well-behaved stock"
    }
  ],

  "file_path": null
}
```

### Bond example (BND):
```json
{
  "status": "success",
  "format": "agent",

  "snapshot": {
    "ticker": "BND",
    "verdict": "moderate risk",
    "risk_level": "moderate",
    "analysis_type": "multi_factor",
    "volatility": {
      "annual_pct": 5.2,
      "monthly_pct": 1.5,
      "sharpe_ratio": 0.45,
      "max_drawdown_pct": -18.3
    },
    "regression": {
      "beta": 0.05,
      "alpha_monthly_pct": 0.15,
      "r_squared": 0.02,
      "idiosyncratic_vol_monthly_pct": 1.50
    },
    "factor_exposures": {},
    "bond_analytics": {
      "interest_rate_beta": -4.52,
      "effective_duration": 4.52,
      "rate_r_squared": 0.85,
      "key_rate_breakdown": {"UST2Y": -0.45, "UST5Y": -1.23, "UST10Y": -2.10, "UST30Y": -0.74}
    }
  },

  "flags": [
    {
      "type": "rate_sensitive",
      "severity": "info",
      "message": "Interest rate beta is -4.52 — meaningful rate sensitivity",
      "interest_rate_beta": -4.52
    },
    {
      "type": "low_beta",
      "severity": "info",
      "message": "Beta is 0.05 — low market sensitivity (defensive)",
      "beta": 0.05
    },
    {
      "type": "low_r_squared",
      "severity": "info",
      "message": "R² is 0.02 — market/factor model explains little of this stock's moves",
      "r_squared": 0.02
    }
  ],

  "file_path": null
}
```

### What each section answers for the agent:

| Section | Agent question |
|---------|---------------|
| `snapshot.verdict` | "Is this stock risky?" (one phrase) |
| `snapshot.risk_level` | Machine-readable risk bucket |
| `snapshot.volatility` | "How volatile is this stock?" |
| `snapshot.regression` | "How does it move with the market?" |
| `snapshot.factor_exposures` | "What factors drive this stock?" |
| `snapshot.bond_analytics` | "How rate-sensitive is this bond?" |
| `flags` | "What deserves attention?" |
| `file_path` | "Where's the full analysis for deep dives?" |

## Compatibility

- All existing formats (`full`, `summary`, `report`) unchanged
- `format="agent"` is purely additive
- `output="file"` works with any format
- Default format stays `"summary"` (no breaking change)
- `output` defaults to `"inline"` (no breaking change)

## Decisions

1. **Snapshot nested under `"snapshot"` key.** Consistent with positions, performance, trading analysis.
2. **`get_agent_snapshot()` lives on `StockAnalysisResult` in `core/result_objects.py`.** That's where the class is defined.
3. **Flags take the snapshot dict, not the result object.** Same decoupling pattern.
4. **Percentages converted in snapshot.** Internal values are decimals (0.25 = 25%). Snapshot converts to percentages (25.0) with `_pct` suffix for clarity. Agent shouldn't need to multiply by 100.
5. **Risk verdict derived from vol + beta + rate sensitivity.** Simple threshold-based: very_high/high/moderate/low. Incorporates interest_rate_beta for bonds (see Decision 16). Not a letter grade (unlike trading analysis) because stock risk isn't about "good/bad" — it's about risk level.
6. **`risk_level` field for machine use.** In addition to human-readable `verdict`, a machine-readable `risk_level` enum (very_high/high/moderate/low) enables programmatic decisions.
7. **Bond analytics conditional.** `bond_analytics` section only appears when `interest_rate_beta` is not None. Avoids null clutter for equity analysis.
8. **Factor exposures from existing getter with fallback.** Uses `self.get_factor_exposures()` for DataFrame → dict. If that returns empty and `self.factor_exposures` has data, extract betas from the structured metadata dict as fallback.
9. **Regression fallback.** Uses `self.regression_metrics or self.risk_metrics or {}` — the MCP tool already does this fallback for simple regression path.
10. **`_STOCK_OUTPUT_DIR` module constant.** Testable via `monkeypatch`, defaults to `Path("logs/stock")`.
11. **No minimum count gates.** Unlike trading analysis, stock analysis always has data (single ticker, always runs). Every flag can fire based on the values alone.
12. **Well-behaved positive signal.** Combines moderate vol (15-25%), reasonable beta (0.5-1.2), and good R² (≥ 0.5) — all in agent snapshot units (percentages for vol, raw for beta/R²).
13. **Alpha is monthly intercept.** The OLS regression runs on monthly returns, so `alpha` is a monthly intercept — NOT annualized. Named `alpha_monthly_pct` to avoid confusion.
14. **Idiosyncratic vol is monthly.** `idio_vol_m` is the std dev of monthly residuals. Named `idiosyncratic_vol_monthly_pct`.
15. **Sharpe and max_drawdown may be None.** Sharpe is present on simple regression path (via `compute_stock_performance_metrics`), absent on multi-factor. max_drawdown is generally absent on both current paths. Both treated as optional — snapshot returns None, flags gate on `is not None`.
16. **Risk verdict includes rate sensitivity for bonds.** `interest_rate_beta` (effective duration proxy) is incorporated into risk_level: abs > 8 = very_high, > 5 = high, > 2 = moderate. A long-duration bond won't be mislabeled "low risk."
17. **None-preserving numeric conversion.** `get_agent_snapshot()` preserves None for missing vol/regression metrics (not coerced to 0). Factor betas drop keys with None values. Flags gate on `is not None` before comparing. Risk verdict uses `or 0` only for threshold comparison (defaulting missing to safe/low). This prevents false flags (e.g., `low_beta`) from missing data.

## Test Plan

### `core/result_objects.py` — get_agent_snapshot tests

- `test_agent_snapshot_keys` — all expected top-level keys present (ticker, verdict, risk_level, analysis_type, analysis_period, volatility, regression, factor_exposures)
- `test_agent_snapshot_verdict_high_risk` — high vol or high beta → "high risk"
- `test_agent_snapshot_verdict_low_risk` — low vol and low beta → "low risk"
- `test_agent_snapshot_verdict_moderate` — moderate values → "moderate risk"
- `test_agent_snapshot_volatility_as_pct` — annual_vol decimal 0.25 → annual_pct 25.0
- `test_agent_snapshot_regression_fallback` — uses risk_metrics when regression_metrics empty
- `test_agent_snapshot_bond_analytics_present` — bond fields included when interest_rate_beta set
- `test_agent_snapshot_bond_analytics_absent` — no bond_analytics key when interest_rate_beta is None
- `test_agent_snapshot_factor_exposures` — factor betas present when factor analysis performed
- `test_agent_snapshot_no_factor_exposures` — empty dict when no factor analysis
- `test_agent_snapshot_sharpe_none_on_multifactor` — sharpe_ratio is None when vol_metrics lacks it
- `test_agent_snapshot_alpha_is_monthly` — alpha_monthly_pct field present (not alpha_annual_pct)
- `test_agent_snapshot_idio_vol_is_monthly` — idiosyncratic_vol_monthly_pct field present
- `test_agent_snapshot_factor_fallback` — uses factor_exposures metadata when factor_summary empty
- `test_agent_snapshot_missing_regression_preserves_none` — missing regression data → beta/alpha/r_squared are None, not 0
- `test_agent_snapshot_missing_data_no_false_low_beta` — missing regression does not cause low_beta flag
- `test_agent_snapshot_rate_risk_in_verdict` — high rate beta elevates risk_level for bonds

### `core/stock_flags.py` tests

- `test_very_high_volatility_flag` — vol > 50% triggers warning
- `test_high_volatility_flag` — vol > 30% triggers info
- `test_no_volatility_flag` — vol 20% does not trigger
- `test_extreme_beta_flag` — beta > 2.0 triggers warning
- `test_high_beta_flag` — beta > 1.5 triggers info
- `test_low_beta_flag` — beta < 0.3 triggers info
- `test_low_r_squared_flag` — R² < 0.3 triggers info
- `test_deep_drawdown_flag` — drawdown < -50% triggers warning
- `test_negative_sharpe_flag` — Sharpe < 0 triggers warning
- `test_strong_sharpe_flag` — Sharpe > 1.5 triggers success
- `test_momentum_tilt_flag` — abs momentum beta > 0.5 triggers info
- `test_style_tilt_flag` — abs value beta > 0.5 triggers info
- `test_rate_sensitive_flag` — abs interest rate beta > 1.0 triggers info
- `test_well_behaved_flag` — moderate vol + reasonable beta + good R² triggers success
- `test_flags_sorted_by_severity` — warnings before info before success
- `test_empty_snapshot_no_crash` — empty dict produces no flags
- `test_null_sharpe_no_flag` — sharpe_ratio None does not trigger sharpe flags
- `test_null_drawdown_no_flag` — max_drawdown_pct None does not trigger drawdown flag

### `mcp_tools/stock.py` agent format tests

- `test_agent_format_structure` — top-level keys: status, format, snapshot, flags, file_path
- `test_agent_format_calls_getter` — verify delegation to get_agent_snapshot()
- `test_agent_format_has_flags` — flags list present in response
- `test_agent_format_snapshot_nested` — snapshot is nested dict

### File output tests

- `test_file_output_creates_file` — file written to logs/stock/
- `test_file_output_includes_ticker_in_filename` — filename contains ticker
- `test_file_output_returns_file_path` — file_path in response is valid path
- `test_inline_output_no_file` — output="inline" does not create file
- `test_file_output_attaches_path_to_summary` — format="summary" + output="file" includes file_path
- `test_file_output_attaches_path_to_report` — format="report" + output="file" includes file_path

### MCP server registration tests

- `test_mcp_server_format_enum_includes_agent` — verify mcp_server.py tool registration includes "agent" in format enum
- `test_mcp_server_output_param_exists` — verify output parameter registered for analyze_stock

## Implementation Order

1. Add `get_agent_snapshot()` to `StockAnalysisResult` in `core/result_objects.py`
2. Create `core/stock_flags.py` with `generate_stock_flags()`
3. Add `_build_agent_response()` and `_save_full_stock()` to `mcp_tools/stock.py`
4. Add `format="agent"` and `output` parameter to `analyze_stock()` in `mcp_tools/stock.py`
5. Update format dispatch
6. Update `mcp_server.py` registration (add agent to format enum, add output param)
7. Write tests (getters → flags → composer)
8. Verify via MCP live call: `analyze_stock(ticker="AAPL", format="agent")`

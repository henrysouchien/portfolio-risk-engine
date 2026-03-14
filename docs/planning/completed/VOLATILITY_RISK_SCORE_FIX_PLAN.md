# Volatility Risk Score = 0/100 "Extreme" — Fix Plan

## Context

The Risk Score card shows `0/100 Extreme` for the Volatility Risk component despite the risk analysis describing volatility as "8.5% - low". Two separate bugs contribute:

1. **NaN propagation in volatility scoring**: When `build_portfolio_view()` returns NaN for `volatility_annual` (due to empty/insufficient returns data), `calculate_volatility_risk_loss()` propagates NaN → `score_excess_ratio(NaN)` falls through all `<=` comparisons → returns 0 (worst score).

2. **Default RiskScoreResult crash**: When `run_risk_score_analysis()` fails entirely (returns None), the service creates a default `RiskScoreResult` with empty `limit_violations`, `suggested_limits`, etc. Multiple formatting methods then crash with KeyError because they hard-code dict key access without guards.

**Root cause (deeper)**: `get_returns_dataframe()` produces a DataFrame with 0-1 rows after `.dropna()` alignment across 26+ tickers. Some tickers (CUR:*, USD:CASH, OTC stocks like CPPMF/LIFFF/RNMBY, recent IPOs like FIG) get excluded, but the remaining tickers' monthly returns still end up with insufficient overlapping dates. `pd.DataFrame.cov()` with 0-1 rows returns all-NaN → NaN volatility. This is a data availability issue (not a code bug) but the scoring pipeline should handle it gracefully.

## Two data paths for volatility

The frontend shows two different volatility values from two hooks:
- **`useRiskAnalysis`** → `risk_metrics.annual_volatility` = 8.5% (from `analyze_portfolio()` which uses a different `build_portfolio_view()` call, possibly with different dates or cached differently)
- **`useRiskScore`** → `volatility_annual` = null (from `run_risk_score_analysis()` → its own `build_portfolio_view()` call)

The container's `buildRiskFactorDescription()` reads from `useRiskAnalysis` (shows "8.5% - low") while `getComponentScore('Volatility Risk')` reads from `useRiskScore` (shows 0/100). This mismatch is confusing but resolves itself once the scoring handles NaN correctly.

## Files to Modify

1. **`portfolio_risk_engine/portfolio_risk_score.py`** — NaN guards in scoring + limits + suggestions functions + legacy formatter
2. **`core/result_objects/risk.py`** — `.get()` guards in `_format_detailed_risk_analysis()` + `_format_suggested_risk_limits()`
3. **`services/portfolio_service.py`** — Complete default keys in fallback `RiskScoreResult`

## Shared helper: `_safe_finite()`

Add a shared finite-number guard near the top of `portfolio_risk_score.py` that handles Python float, numpy, and pandas scalar types:

```python
import math

def _safe_finite(value: Any, fallback: float = 0.0) -> float:
    """Return value if finite non-negative number, else fallback.

    Handles float/numpy/pandas scalars. Returns fallback for None, NaN, ±Inf,
    and negative values (volatility/loss metrics should never be negative).
    """
    if value is None:
        return fallback
    try:
        f = float(value)
        return f if math.isfinite(f) and f >= 0.0 else fallback
    except (TypeError, ValueError):
        return fallback
```

Note: clamps negative values to fallback. Volatility, loss potentials, and sector percentages should never be negative — a negative value indicates data corruption or NaN propagation through subtraction.

## Changes

### 1. Keep `score_excess_ratio()` numeric (line 193)

Per Codex review: do NOT change its contract to return `None`. Keep it `float → float`. Instead, guard inputs upstream and handle missing data in `calculate_portfolio_risk_score()`.

Add only a defensive NaN→0 fallback (not None sentinel):

```python
def score_excess_ratio(excess_ratio: float) -> float:
    if not math.isfinite(excess_ratio):
        return 0.0  # Unknown data → worst case (callers should pre-guard)
    ...existing piecewise logic...
```

### 2. Guard `calculate_volatility_risk_loss()` against NaN (line 486)

```python
def calculate_volatility_risk_loss(summary: Dict[str, Any], leverage_ratio: float) -> float:
    raw_vol = summary.get("volatility_annual")
    max_reasonable_vol = WORST_CASE_SCENARIOS["max_reasonable_volatility"]
    actual_vol = _safe_finite(raw_vol, fallback=max_reasonable_vol)

    if actual_vol != raw_vol:
        from portfolio_risk_engine._logging import portfolio_logger
        portfolio_logger.warning(
            "⚠️ volatility_annual is missing/NaN/negative — "
            "using max_reasonable_volatility (%.0f%%) as conservative fallback",
            max_reasonable_vol * 100,
        )

    volatility_loss = min(actual_vol, max_reasonable_vol) * leverage_ratio
    return volatility_loss
```

### 3. Handle missing-data components in `calculate_portfolio_risk_score()` (line 1330)

After computing component scores, flag any that used NaN fallback data. Use `UNKNOWN_RISK_SCORE = 50.0` (moderate risk — not extreme and not safe) and carry an `incomplete_data` flag:

```python
component_scores = {
    "factor_risk": score_excess_ratio(factor_loss / max_loss),
    "concentration_risk": score_excess_ratio(concentration_loss / max_loss),
    "volatility_risk": score_excess_ratio(volatility_loss / max_loss),
    "sector_risk": score_excess_ratio(sector_loss / max_loss),
}

# Track components with missing underlying data
UNKNOWN_RISK_SCORE = 50.0
incomplete_components = []
vol_annual = summary.get("volatility_annual")
if not _safe_finite(vol_annual, fallback=-1.0) >= 0.0:
    component_scores["volatility_risk"] = UNKNOWN_RISK_SCORE
    incomplete_components.append("volatility_risk")
```

Add `incomplete_components` to the returned dict so consumers know which scores are estimates:

```python
result["details"]["incomplete_components"] = incomplete_components
```

### 4. Guard `analyze_portfolio_risk_limits()` volatility comparison (line 698)

```python
# Before:
actual_vol = summary["volatility_annual"]
# After:
actual_vol = _safe_finite(summary.get("volatility_annual"), fallback=0.0)
```

With `fallback=0.0`, NaN volatility simply skips the warning/violation (you can't assert a limit violation when data is missing).

### 5. Guard `calculate_suggested_risk_limits()` volatility + sector extraction (lines 890, 999)

**Volatility (line 890):**
```python
# Before:
actual_vol = summary["volatility_annual"]
# After:
actual_vol = _safe_finite(summary.get("volatility_annual"), fallback=0.0)
```

This prevents `nan%` rendering in the suggested limits output (line 990 → `"current_volatility": actual_vol`).

**Sector (line 999):**
```python
# Before:
max_sector_exposure = max(industry_pct.values()) if industry_pct else 0.0
# After:
max_sector_exposure = _safe_finite(
    max(industry_pct.values()) if industry_pct else 0.0,
    fallback=0.0,
)
```

Sector percentages can be NaN when `portfolio_variance` is NaN (from `portfolio_risk.py:1568`), causing `nan%` in the sector limit display.

### 5b. Guard `analyze_portfolio_risk_limits()` sector comparison (line 757)

Same NaN path — `max(industry_pct_dict.values())` can be NaN:

```python
# Before:
max_industry_pct = max(industry_pct_dict.values()) if industry_pct_dict else 0.0
# After:
max_industry_pct = _safe_finite(
    max(industry_pct_dict.values()) if industry_pct_dict else 0.0,
    fallback=0.0,
)
```

### 6. Fix default `RiskScoreResult` in service fallback (portfolio_service.py:548-559)

Populate ALL keys expected by downstream formatters, including `analysis_metadata`:

```python
if result is None:
    result = RiskScoreResult(
        risk_score={"score": 0, "category": "Analysis Failed", "component_scores": {}, "risk_factors": ["Analysis failed"], "recommendations": [], "interpretation": {}, "potential_losses": {}, "details": {}},
        limits_analysis={
            "risk_factors": ["Analysis failed"],
            "recommendations": [],
            "limit_violations": {
                "factor_betas": 0,
                "concentration": 0,
                "volatility": 0,
                "variance_contributions": 0,
                "leverage": 0,
            },
        },
        portfolio_analysis={},
        suggested_limits={
            "factor_limits": {},
            "concentration_limit": {"current_max_position": 0, "suggested_max_position": 0, "needs_reduction": False},
            "volatility_limit": {"current_volatility": 0, "suggested_max_volatility": 0, "needs_reduction": False},
            "sector_limit": {"current_max_sector": 0, "suggested_max_sector": 0, "needs_reduction": False},
        },
        formatted_report="Analysis failed — insufficient data for risk score computation.",
        analysis_date=datetime.now(UTC),
        portfolio_name=portfolio_data.portfolio_name,
        risk_limits_name=risk_limits_data.name,
        analysis_metadata={},
    )
```

Key additions vs previous version:
- `analysis_metadata={}` — prevents `None.get()` crash in `_format_suggested_risk_limits()` (line 2360)
- Non-empty `formatted_report` — prevents `to_api_response()` from calling `to_cli_report()` on broken result

### 7. Robust key access in `_format_detailed_risk_analysis()` (risk.py:2314-2323)

Use `.get()` with defaults:

```python
violations = self.limits_analysis.get("limit_violations", {})
total_violations = sum(violations.values()) if violations else 0

lines.append("📊 LIMIT VIOLATIONS SUMMARY:")
lines.append(f"   Total violations: {total_violations}")
lines.append(f"   Factor betas: {violations.get('factor_betas', 0)}")
lines.append(f"   Concentration: {violations.get('concentration', 0)}")
lines.append(f"   Volatility: {violations.get('volatility', 0)}")
lines.append(f"   Variance contributions: {violations.get('variance_contributions', 0)}")
lines.append(f"   Leverage: {violations.get('leverage', 0)}")
```

### 8. Robust key access in `_format_suggested_risk_limits()` (risk.py:2357-2447)

Guard ALL hard-coded key accesses, including the Priority Actions section at line 2428:

```python
# Line 2360: guard analysis_metadata
analysis_metadata = getattr(self, 'analysis_metadata', None) or {}
max_loss = analysis_metadata.get('max_loss', 0.25)

# Line 2377: guard factor_limits
factor_limits = self.suggested_limits.get("factor_limits", {})
# ... (existing iteration is already guarded by `if factor_limits:`)

# Line 2397: guard concentration_limit
conc = self.suggested_limits.get("concentration_limit")
if conc:
    conc_status = "🔴 REDUCE" if conc["needs_reduction"] else "🟢 OK"
    # ... existing formatting
else:
    conc = {"needs_reduction": False}  # For Priority Actions check below

# Line 2406: guard volatility_limit
vol = self.suggested_limits.get("volatility_limit")
if vol:
    vol_status = "🔴 REDUCE" if vol["needs_reduction"] else "🟢 OK"
    # ... existing formatting
else:
    vol = {"needs_reduction": False}

# Line 2415: guard sector_limit
sector = self.suggested_limits.get("sector_limit")
if sector:
    sector_status = "🔴 REDUCE" if sector["needs_reduction"] else "🟢 OK"
    # ... existing formatting
else:
    sector = {"needs_reduction": False}

# Lines 2428-2435: Priority Actions (uses conc, vol, sector variables)
# Now safe because missing sections get {"needs_reduction": False} fallback
```

### 9. Harden legacy formatters in portfolio_risk_score.py

**Violations formatter (line 1620-1629):**
```python
violations = limits_analysis.get("limit_violations", {})
total_violations = sum(violations.values()) if violations else 0

print(f"\n📊 LIMIT VIOLATIONS SUMMARY:")
print(f"   Total violations: {total_violations}")
print(f"   Factor betas: {violations.get('factor_betas', 0)}")
print(f"   Concentration: {violations.get('concentration', 0)}")
print(f"   Volatility: {violations.get('volatility', 0)}")
print(f"   Variance contributions: {violations.get('variance_contributions', 0)}")
print(f"   Leverage: {violations.get('leverage', 0)}")
```

**Suggested limits formatter (line 1113+):**
```python
factor_limits = suggestions.get("factor_limits", {})
# ... (existing iteration already guarded by `if factor_limits:`)

conc = suggestions.get("concentration_limit")
if conc:
    # ... existing formatting
else:
    conc = {"needs_reduction": False}  # For Priority Actions check below

vol = suggestions.get("volatility_limit")
if vol:
    # ... existing formatting
else:
    vol = {"needs_reduction": False}

sector = suggestions.get("sector_limit")
if sector:
    # ... existing formatting
else:
    sector = {"needs_reduction": False}

# Lines 1156-1162: Priority Actions (uses conc, vol, sector variables)
# Now safe because missing sections get {"needs_reduction": False} fallback
```

## Out of Scope

- **Root cause: why `get_returns_dataframe()` produces empty data** — Data availability issue tied to portfolio composition (CUR:*, OTC, recent IPOs). Separate investigation.
- **Unifying the two volatility data paths** — `useRiskAnalysis` and `useRiskScore` compute volatility independently. Not worth merging now.

## Testing

1. Unit test: `score_excess_ratio(float('nan'))` returns `0.0`
2. Unit test: `score_excess_ratio(float('inf'))` returns `0.0`
3. Unit test: `_safe_finite(None)` → fallback, `_safe_finite(float('nan'))` → fallback, `_safe_finite(np.float64('nan'))` → fallback
4. Unit test: `_safe_finite(-0.5)` → fallback (negative values clamped)
5. Unit test: `calculate_volatility_risk_loss()` with NaN `volatility_annual` → uses max_reasonable_vol fallback
6. Unit test: `calculate_volatility_risk_loss()` with negative `volatility_annual` → uses max_reasonable_vol fallback
7. Unit test: `calculate_volatility_risk_loss()` with valid volatility → unchanged behavior
8. Unit test: default `RiskScoreResult` with empty/minimal data → `to_api_response()`, `to_cli_report()`, `to_formatted_report()` all don't crash
9. Unit test: `calculate_portfolio_risk_score()` with NaN volatility → `incomplete_components` contains `"volatility_risk"`, score is `UNKNOWN_RISK_SCORE`
10. Unit test: NaN sector percentages (from NaN `portfolio_variance`) → clamped to 0 in limits + suggestions
11. Unit test: legacy suggested-limits formatter with missing `concentration_limit`/`volatility_limit`/`sector_limit` keys → no crash, Priority Actions block safe
12. Integration: `get_risk_score(use_cache=False)` no longer crashes
13. Integration: volatility_risk component score is no longer 0 when data is missing

## Verification

1. `pytest tests/` — existing tests pass
2. `get_risk_score(use_cache=False)` → returns valid result (not error)
3. Frontend: Risk Score tab → Volatility Risk shows reasonable score (50/100 for unknown, or correct score if data available), not 0/100

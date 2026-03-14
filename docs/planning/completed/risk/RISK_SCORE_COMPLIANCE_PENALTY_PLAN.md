# Risk Score Compliance Penalty

**Status**: PLANNED | **Codex Review**: R1-R29 FAIL, **R30 PASS** (0 findings)

## Context

The risk score (0-100) and limit violations are computed independently. The score measures aggregate potential losses vs `max_loss_limit` via 4 weighted components. Violations check individual limits (factor betas, concentration, volatility, variance contributions, leverage). These can diverge — a portfolio with 5 marginal violations can score 98.5 "Excellent" because the aggregate potential losses are low. This misleads users into trusting the score when the portfolio violates their own risk policy.

**Reported**: Analyst-agent briefing 2026-03-09 — score jumped from 78.3 ("Fair") to 98.5 ("Excellent") with 5 active violations. Likely amplified by Schwab token expiry changing portfolio composition.

## Design Principle

**The risk score should answer: "How well-managed is my portfolio risk?"**

This requires two dimensions:
1. **Risk capacity** — how much of your loss budget are you consuming? (aggregate potential losses)
2. **Risk discipline** — are you within your self-imposed guardrails? (limit compliance)

The approach is **hybrid**: (a) severity-weighted penalty scales with how far over each limit you are — a portfolio 1% over 5 limits gets a smaller penalty than one 50% over 1 limit; (b) compliance ceiling caps the score at 89 when any violations exist — "Excellent" requires full compliance regardless of how marginal the violations are. This ensures even 5 marginal 1%-over violations drop the portfolio below "Excellent".

## Current Architecture

```
run_risk_score_analysis()                           # orchestrator
  ├─ calculate_portfolio_risk_score()               # aggregate score (0-100)
  │     score_excess_ratio() × 4 components
  │     weighted average → category
  ├─ analyze_portfolio_risk_limits()                # individual limit checks
  │     string-based risk_factors + recommendations
  │     limit_violations: counts via string grep     ← fragile, loses severity
  └─ RiskScoreResult.from_risk_score_analysis()     # combines both
```

`calculate_portfolio_risk_score()` is the raw pre-compliance score. `run_risk_score_analysis()` is the only production entry point and applies the compliance penalty before returning. No production callers use `calculate_portfolio_risk_score()` directly (verified via grep — only `run_risk_score_analysis()` calls it in non-test code). Tests call it directly for unit-level validation, which is expected. To make the contract explicit, Step 3 adds a docstring note: "Returns raw score before compliance penalty. Use `run_risk_score_analysis()` for the final adjusted score." Three stale docstring references also need updating:
- `display_portfolio_risk_score()` body docstring (line 1476-1479): Currently says "For programmatic consumption rely on the structured dict returned by `calculate_portfolio_risk_score`". Update to reference `run_risk_score_analysis()` as the source of the final adjusted score.
- `display_portfolio_risk_score()` parameter doc (line 1483-1484): Currently says `risk_score` is "The dictionary returned by `calculate_portfolio_risk_score`". Update to "Dictionary from `run_risk_score_analysis()` (may include compliance penalty adjustments)".
- `_format_risk_score_output()` parameter doc (line 1628-1629): Currently says `risk_score` is "Dictionary produced by `calculate_portfolio_risk_score`". Update to same wording as above.

**Problems**:
1. `calculate_portfolio_risk_score()` never sees violations
2. `analyze_portfolio_risk_limits()` discards actual/limit ratios, returns text + counts via string matching (lines 816-822)
3. `is_compliant()` on `RiskScoreResult` uses those fragile string-grep counts
4. `get_risk_category_enum()` doesn't map "Fair", "Poor", "Very Poor" — all return `"unknown"` (pre-existing bug)

## Implementation

### Step 1: Structured compliance violation data in `analyze_portfolio_risk_limits()`

**File**: `portfolio_risk_engine/portfolio_risk_score.py`, function `analyze_portfolio_risk_limits()` (line 615)

Build a `violation_details` list (local variable) that captures structured data for each limit breach. This is returned under the key `compliance_violations` (see return dict below). Built alongside existing `risk_factors` text — no changes to existing text outputs.

Each violation entry:
```python
{
    "category": str,      # "factor_beta", "concentration", "volatility", "variance",
                          # "industry", "leverage"
    "metric": str,        # "market", "momentum", "value", "max_weight", "portfolio_vol",
                          # "factor_contribution", "market_contribution", "industry_{name}",
                          # "leverage", "{proxy_name}"
    "actual": float,      # actual measured value (SIGNED — preserves original for audit)
    "limit": float,       # configured limit
    "excess_pct": float,  # see formula below
}
```

**excess_pct formula:**
- **Factor betas** (signed): `(abs(actual) - limit) / limit` — uses abs() because the existing code uses `abs(actual_beta) / max_beta` for the ratio check (line 668). Signed `actual` is preserved in the entry for audit.
- **All other categories**: `(actual - limit) / limit` when `limit > 0`
- **Zero-limit edge case**: If `limit == 0` and `actual > 0`, the portfolio is non-compliant but division by zero is undefined. Set `excess_pct = 1.0` (max severity) for any positive breach against a zero limit. This treats a zero limit as an absolute prohibition.

```python
# excess_pct calculation helper:
def _compute_excess_pct(actual: float, limit: float, use_abs: bool = False) -> float:
    effective = abs(actual) if use_abs else actual
    if limit > 0:
        return (effective - limit) / limit
    elif effective > 0:
        return 1.0  # any positive breach against zero limit = max severity
    else:
        return 0.0
```

Capture points — **violations only** (over limit), NOT warnings (approaching limit):

| Check | Condition for inclusion | Category | Metric |
|-------|------------------------|----------|--------|
| Factor betas (line 664-684) | `beta_ratio > beta_violation_ratio` | `factor_beta` | `{factor}` (market/momentum/value) |
| Proxy betas (line 687-697) | `beta_ratio > beta_violation_ratio` | `factor_beta` | `{proxy}` |
| Concentration (line 706-713) | `max_weight > weight_limit` | `concentration` | `max_weight` |
| Volatility (line 726-731) | `actual_vol > vol_limit` | `volatility` | `portfolio_vol` |
| Factor variance (line 742-758) | `factor_pct > factor_limit` | `variance` | `factor_contribution` |
| Market variance (line 773-778) | `market_pct > market_limit` | `variance` | `market_contribution` |
| Industry variance (line 788-805) | Each `industry_pct > industry_limit` (iterate all) | `industry` | `industry_{name}` |
| Leverage (line 808-811) | `leverage_ratio > leverage_threshold` | `leverage` | `leverage` |

**Industry per-industry iteration note**: The existing code only captures the single worst industry (`max_industry_pct`, line 782-785) for the `risk_factors` text. For `violation_details`, iterate **all** industries in `industry_pct_dict` and add a separate violation entry for each one exceeding `industry_limit`. This ensures the penalty scales with the number of over-limit industries, not just whether any single industry is over. The existing `risk_factors` text and recommendations are left unchanged (still only mention the top offender). The `limit_violations["industry"]` count is derived from `violation_details` grouping and will correctly reflect the number of over-limit industries.

```python
# Inside analyze_portfolio_risk_limits(), after the existing industry risk_factors/recommendations block:
for ind_name, ind_pct in industry_pct_dict.items():
    safe_pct = _safe_finite(ind_pct, fallback=0.0)
    if safe_pct > industry_limit:
        violation_details.append({
            "category": "industry",
            "metric": f"industry_{ind_name}",
            "actual": safe_pct,
            "limit": industry_limit,
            "excess_pct": _compute_excess_pct(safe_pct, industry_limit),
        })
```

**Leverage threshold note**: The source threshold is named `leverage_warning_threshold` (line 94, default 1.1×), but the existing code already counts leverage exceeding it as a violation in `limit_violations["leverage"]` (line 821) and includes it in `is_compliant()`. This means `is_compliant()` is already `False` for leverage > 1.1× today — the compliance ceiling just makes that consequence visible (drops from "Excellent"). This plan preserves that existing behavior — leverage exceeding 1.1× is treated as a violation for compliance counting, penalty calculation, and ceiling application. If a separate `leverage_violation_threshold` (e.g., 1.3×) is desired to distinguish warning-level from violation-level leverage, that's a follow-up that would change the threshold value in `analyze_portfolio_risk_limits()`, not the penalty mechanism.

**Zero max_beta note**: When `max_beta <= 0` (line 668, 692), the existing code sets `beta_ratio = 0`, which never exceeds `beta_violation_ratio`. This means zero/negative max_beta effectively means "no limit on this factor" — no risk_factors text, no `compliance_violations` entry, no penalty. This is pre-existing behavior and intentional: the `_compute_excess_pct()` helper is never reached because the gate condition prevents entry creation. The `test_zero_limit_max_severity` test should exercise non-beta categories (concentration, volatility, industry, leverage) where zero limits are more meaningful.

**Important**: Proxy beta violations (line 687-697) need a violation vs warning distinction. Currently they only check `beta_warning_ratio`, not `beta_violation_ratio`. For structured violation_details, only include proxy betas that exceed `beta_violation_ratio` (consistent with main factor betas). If the warning threshold is the only check, add the violation check for proxy betas too.

**Also derive `limit_violations` counts from `compliance_violations`** instead of string-grep. This replaces the fragile string matching at lines 816-822:

```python
# Derive counts from structured data instead of string matching
limit_violations = {}
for v in violation_details:  # local accumulator (returned as "compliance_violations" below)
    cat = v["category"]
    limit_violations[cat] = limit_violations.get(cat, 0) + 1

return {
    "risk_factors": risk_factors,
    "recommendations": recommendations,
    "limit_violations": {
        "factor_betas": limit_violations.get("factor_beta", 0),
        "concentration": limit_violations.get("concentration", 0),
        "volatility": limit_violations.get("volatility", 0),
        "variance_contributions": limit_violations.get("variance", 0),
        "leverage": limit_violations.get("leverage", 0),
        "industry": limit_violations.get("industry", 0),  # NEW key — previously miscounted
                                                           # under concentration by string-grep
    },
    "compliance_violations": violation_details,
}
```

This preserves the existing `limit_violations` key shape (backward compat) but derives it from structured data. Note: the existing shape uses `"variance_contributions"` while `compliance_violations` uses `"variance"` — the mapping above handles this.

### Step 2: Severity-weighted compliance penalty

**File**: `portfolio_risk_engine/portfolio_risk_score.py`, new function `calculate_compliance_penalty()`

```python
import math

# Category weights — how much each violation type matters for risk discipline
COMPLIANCE_CATEGORY_WEIGHTS = {
    "concentration": 0.12,  # liquidity + single-name tail risk
    "volatility": 0.10,     # direct loss measure
    "leverage": 0.08,       # NOTE: reduced from original 0.15 — leverage already
                            # amplifies all 4 component potential losses in
                            # calculate_portfolio_risk_score(), so a high weight
                            # here would double-count
    "factor_beta": 0.06,    # systematic, hedgeable
    "variance": 0.05,       # second-order, less actionable
    "industry": 0.05,       # sector concentration
}

MAX_COMPLIANCE_PENALTY_PCT = 0.35  # cap total penalty at 35% of raw score
SEVERITY_NORMALIZATION = 0.50      # 50% over limit = max severity (1.0)
COMPLIANCE_CEILING = 89.0          # non-compliant portfolios capped below "Excellent"


def calculate_compliance_penalty(violation_details: list[dict]) -> float:
    """
    Compute severity-weighted compliance penalty from structured violations.

    Returns a multiplier reduction (0.0 to MAX_COMPLIANCE_PENALTY_PCT).
    Applied as: adjusted_score = raw_score × (1 - penalty)

    Severity per violation: min(1.0, excess_pct / SEVERITY_NORMALIZATION)
    Weighted by category importance. Capped at MAX_COMPLIANCE_PENALTY_PCT.
    """
    if not violation_details:
        return 0.0

    total_weighted_severity = 0.0
    for v in violation_details:
        excess_pct = v.get("excess_pct", 0.0)
        # Guard: skip non-finite or non-positive values
        try:
            if not math.isfinite(excess_pct) or excess_pct <= 0:
                continue
        except (TypeError, ValueError):
            continue
        severity = min(1.0, excess_pct / SEVERITY_NORMALIZATION)
        category = v.get("category", "")
        weight = COMPLIANCE_CATEGORY_WEIGHTS.get(category, 0.0)  # unknown categories ignored
        total_weighted_severity += severity * weight

    return min(total_weighted_severity, MAX_COMPLIANCE_PENALTY_PCT)
```

**Leverage double-count rationale**: In `calculate_portfolio_risk_score()`, `leverage_ratio` already multiplies every component's potential loss (lines 1365-1373). A leverage violation is thus already reflected in lower component scores. The compliance penalty weight for leverage is therefore reduced (0.08) compared to concentration (0.12) to avoid over-penalization. The penalty here captures the *policy breach* dimension — "you said your leverage limit is X and you're over it" — not the loss amplification (already captured).

### Step 3: Apply penalty in orchestrator + regenerate interpretation

**File**: `portfolio_risk_engine/portfolio_risk_score.py`, function `run_risk_score_analysis()` (lines 1941-1944)

After computing both `risk_score` and `limits_analysis`, apply the compliance penalty before building the result:

```python
# --- existing ---
risk_score = calculate_portfolio_risk_score(...)
limits_analysis = analyze_portfolio_risk_limits(...)

# --- NEW: apply compliance penalty + ceiling ---
compliance_violations = limits_analysis.get("compliance_violations", [])
limit_violations = limits_analysis.get("limit_violations", {})
is_non_compliant = sum(limit_violations.values()) > 0  # authoritative compliance check

raw_score = risk_score["score"]
adjusted_score = raw_score

# 1. Apply severity-weighted penalty (proportional to how far over limits)
compliance_penalty = calculate_compliance_penalty(compliance_violations)
if compliance_penalty > 0:
    adjusted_score = round(raw_score * (1 - compliance_penalty), 1)

# 2. Apply compliance ceiling (non-compliant → can't be "Excellent")
# Keyed off limit_violations count, NOT penalty magnitude.
# Even if penalty math produces 0 (e.g., unknown category, NaN guard),
# any violation caps the score.
ceiling_applied = False
if is_non_compliant and adjusted_score > COMPLIANCE_CEILING:
    adjusted_score = COMPLIANCE_CEILING
    ceiling_applied = True

if adjusted_score < raw_score:
    # Re-categorize
    if adjusted_score >= 90:
        category = "Excellent"
    elif adjusted_score >= 80:
        category = "Good"
    elif adjusted_score >= 70:
        category = "Fair"
    elif adjusted_score >= 60:
        category = "Poor"
    else:
        category = "Very Poor"

    risk_score["score"] = adjusted_score
    risk_score["category"] = category
    risk_score["details"]["raw_score"] = raw_score
    risk_score["details"]["compliance_penalty_points"] = round(raw_score - adjusted_score, 1)
    risk_score["details"]["compliance_ceiling_applied"] = ceiling_applied

    # Regenerate interpretation text with adjusted score
    risk_score["interpretation"] = generate_score_interpretation(adjusted_score)

    # Augment interpretation with compliance context
    n_violations = len(compliance_violations)
    penalty_points = round(raw_score - adjusted_score, 1)
    risk_score["interpretation"]["risk_assessment"].insert(
        0,
        f"Score reduced by {penalty_points} points due to {n_violations} limit violation(s)"
    )

# --- existing ---
result = RiskScoreResult.from_risk_score_analysis(...)
```

**Key fix (Codex HIGH #3)**: `generate_score_interpretation()` is called inside `calculate_portfolio_risk_score()` with the raw score (line 1431). After penalty adjustment, we must regenerate it with the adjusted score. Otherwise API consumers (`to_api_response()` returns `risk_score` verbatim at line 2073) would see adjusted score/category but raw-score interpretation text.

### Step 3b: Fix report paths to use stored interpretation

Two CLI report formatters regenerate interpretation from the score independently instead of reading the stored `risk_score["interpretation"]` dict:

**File 1**: `portfolio_risk_engine/portfolio_risk_score.py` (line 1598-1610, `display_portfolio_risk_score()`)
```python
# BEFORE (regenerates — loses compliance context):
interpretation = generate_score_interpretation(score)

# AFTER (reads from stored dict — includes compliance augmentation from Step 3):
interpretation = risk_score.get("interpretation") or generate_score_interpretation(score)
```

**File 2**: `core/result_objects/risk.py` (line 2281-2295, `_format_risk_score_display()`)
```python
# BEFORE (regenerates):
interpretation = generate_score_interpretation(score)

# AFTER (reads from stored dict):
interpretation = self.risk_score.get("interpretation") or generate_score_interpretation(score)
```

The `or` fallback ensures backward compat if `interpretation` is missing from the dict for any reason. Both the `format="report"` MCP path and `to_cli_report()` will now show the compliance penalty context.

**Threshold edge consistency note**: In `calculate_portfolio_risk_score()`, category (line 1404) and interpretation (line 1431) are derived from the unrounded `overall_score`, while the returned `score` is `round(overall_score, 1)` (line 1434). This is a pre-existing inconsistency — e.g., unrounded 89.97 → category "Good", interpretation "Good", but rounded score 90.0. Our Step 3 penalty path is actually MORE consistent: both category and interpretation are re-derived from `adjusted_score = round(raw_score * (1-penalty), 1)`, a rounded value. Step 3b just reads the stored (potentially already overwritten by Step 3) interpretation. The pre-existing threshold edge issue in the non-penalty path is not introduced or worsened by this plan — it exists today regardless.

### Step 4: Fix `get_risk_category_enum()` (pre-existing bug)

**File**: `core/result_objects/risk.py`, method `get_risk_category_enum()` (line 1843)

The current mapping is incomplete — "Fair", "Poor", "Very Poor" all return `"unknown"`:

```python
# BEFORE (broken):
if "Excellent" in category: return "excellent"
elif "Good" in category: return "good"
elif "Moderate" in category: return "moderate"  # never produced by scorer
elif "High" in category: return "high"          # never produced by scorer
else: return "unknown"                          # ← Fair, Poor, Very Poor all land here

# AFTER (adds Fair/Poor/Very Poor, preserves substring/case-insensitive matching):
if "Excellent" in category or "excellent" in category:
    return "excellent"
elif "Very Poor" in category or "very poor" in category.lower():
    return "very_poor"  # Must check before "Poor" — "Very Poor" contains "Poor"
elif "Good" in category or "good" in category:
    return "good"
elif "Fair" in category or "fair" in category:
    return "fair"
elif "Poor" in category or "poor" in category:
    return "poor"
elif "Moderate" in category or "moderate" in category:
    return "moderate"
elif "High" in category or "high" in category:
    return "high"
else:
    return "unknown"
```

This fixes the pre-existing bug (Fair/Poor/Very Poor → "unknown") while preserving backward compat for legacy Moderate/High categories that existing tests construct.

### Step 4b: Fix `get_summary()` total_violations count

**File**: `core/result_objects/risk.py`, method `get_summary()` (line 1800)

`get_summary()` currently counts warnings AND violations together:
```python
# BEFORE (wrong — counts warnings too):
"total_violations": len(self.limits_analysis.get("risk_factors", [])),

# AFTER (correct — counts actual limit breaches only):
"total_violations": sum(self.limits_analysis.get("limit_violations", {}).values()),
```

This ensures that `get_risk_score(format="summary")` returns `total_violations=0` when there are warning-level risk factors but no actual limit breaches. The MCP summary path (`mcp_tools/risk.py:591-601`) passes this value through directly. The REST API risk-score endpoint (`app.py:1495-1507`, `analyze_risk_score()`) also calls `result.get_summary()` on the `RiskScoreResult` — so `total_violations`, `raw_score`, and `compliance_penalty_points` change that HTTP API payload too. (Other `app.py` endpoints calling `.get_summary()` use different result types — e.g., `PortfolioAnalysisResult`, `PerformanceResult` — and are unaffected.) All `RiskScoreResult.get_summary()` consumers benefit from fixing the source method.

Also add `raw_score` and `compliance_penalty_points` to `get_summary()` so the default MCP format exposes the penalty breakdown:
```python
# Add to the return dict in get_summary():
"raw_score": self.risk_score.get("details", {}).get("raw_score", overall_score),
"compliance_penalty_points": self.risk_score.get("details", {}).get("compliance_penalty_points", 0),
```

And wire them into the summary MCP response (`mcp_tools/risk.py:591-601`):
```python
response = {
    "status": "success",
    "overall_score": summary["overall_score"],
    "raw_score": summary["raw_score"],                        # NEW
    "compliance_penalty_points": summary["compliance_penalty_points"],  # NEW
    "risk_category": result.risk_score.get("category", "Unknown"),
    ...
}
```

When no penalty is applied, `raw_score == overall_score` and `compliance_penalty_points == 0` — no noise for clean portfolios.

### Step 5: Wire `raw_score` and `compliance_penalty_points` through snapshot + flags

**File**: `core/result_objects/risk.py`, method `get_agent_snapshot()` (line 1862)

Add to snapshot dict:
```python
return {
    "overall_score": _safe_float(score),
    "risk_category": category,
    "is_compliant": is_compliant,
    "verdict": verdict,
    "component_scores": ...,
    "violation_count": violation_count,
    # NEW:
    "raw_score": _safe_float(self.risk_score.get("details", {}).get("raw_score", score)),
    "compliance_penalty_points": _safe_float(self.risk_score.get("details", {}).get("compliance_penalty_points", 0)),
    "compliance_ceiling_applied": self.risk_score.get("details", {}).get("compliance_ceiling_applied", False),
    # existing:
    "critical_violations": ...,
    "recommendations": ...,
    "risk_factors": ...,
    "priority_actions": ...,
}
```

When no penalty is applied, `raw_score` equals `overall_score` and `compliance_penalty_points` is 0. No downstream confusion.

**Also fix verdict string** (line 1883-1886): Currently uses `get_risk_category_enum()` (e.g., `"very_poor"`) in user-facing verdict text. Change to use display category `self.risk_score.get("category", "Unknown")` for the verdict. The `risk_category` key in the snapshot dict still uses the enum form for programmatic routing.

**Warning vs violation distinction in snapshot/summary**: `_get_violations_summary()` (line 1982) derives `critical_violations` from `risk_factors` text, which includes both warnings (approaching limit) and actual violations (over limit). This is intentional — warnings ARE useful context for the agent even when `is_compliant=True`. The authoritative compliance check is `is_compliant()` which uses `limit_violations` (now derived from structured data). The `critical_violations` list in the snapshot is a display/context field, not a compliance signal. No change needed here — but `_get_violations_summary().total_violations` must use the structured `limit_violations` count (which it already does via `sum(violations.values())` at line 1992).

**File**: `core/risk_score_flags.py`, function `generate_risk_score_flags()` (line 6)

Two changes:

**(a)** Suppress `excellent_risk` flag when non-compliant (line 46). The compliance ceiling (Step 3) already caps non-compliant portfolios at 89, so `score >= 90 && !is_compliant` is unreachable on the normal penalty path. However, gating `excellent_risk` on `is_compliant` is defense-in-depth — it protects against edge cases (e.g., if `run_risk_score_analysis()` is bypassed, or if a future change introduces a path that skips the ceiling). It also makes the flag semantics self-documenting: "Excellent" requires compliance.

```python
# BEFORE (line 46):
elif score >= 90:
    flags.append({"flag": "excellent_risk", ...})

# AFTER:
elif score >= 90 and is_compliant:
    flags.append({"flag": "excellent_risk", ...})
```

**(b)** Add compliance penalty info flag when penalty was materially applied (score actually changed after rounding). Uses same `float()` coercion pattern as existing `score` parsing (line 20-24):

```python
# Guard: match existing isinstance(snapshot, dict) pattern (line 20)
if isinstance(snapshot, dict):
    try:
        raw_score = float(snapshot.get("raw_score", score))
        penalty_points = float(snapshot.get("compliance_penalty_points", 0))
    except (TypeError, ValueError):
        raw_score = score
        penalty_points = 0.0
else:
    raw_score = score
    penalty_points = 0.0

if penalty_points > 0 and score < raw_score:
    ceiling_applied = snapshot.get("compliance_ceiling_applied", False) if isinstance(snapshot, dict) else False
    reason = "compliance violations (ceiling applied)" if ceiling_applied else "compliance violations"
    flags.append({
        "flag": "compliance_penalty_applied",
        "severity": "info",
        "message": f"Score adjusted {raw_score:.1f} → {score:.1f} due to {reason}"
    })
```

Key details:
- `float()` coercion with try/except matches the existing pattern for `score` (line 20-24)
- Uses `score` (already coerced) instead of reading `overall_score` again
- `:.1f` format (not `:.0f`) prevents collapsing a 0.5-point adjustment into "90 → 90"
- `score < raw_score` guard (both already numeric) prevents the flag when penalty rounds to zero

### Step 6: Do NOT change `_get_violation_details()` on `RiskScoreResult`

**File**: `core/result_objects/risk.py`, method `_get_violation_details()` (line 2104) — **NO CHANGES**.

This method parses strings from `risk_factors` to produce display-oriented violation details for `to_api_response()`. It uses specific label conventions (e.g., `"market exposure"` not `"market"`), percentage-point values (e.g., `48.3` not `0.483`), and signed betas. Changing it would silently alter the API entry schema (labels, units, signs).

The structured `compliance_violations` in `limits_analysis` serves a different purpose:
1. **Penalty calculation** — `calculate_compliance_penalty()` uses raw structured data (category, actual, limit, excess_pct)
2. **Deriving `limit_violations` counts** — replaces string-grep for compliance checking

These two data paths coexist:
- `limits_analysis["compliance_violations"]` → internal, raw, for penalty math + compliance counts
- `RiskScoreResult._get_violation_details()` → display, string-parsed, for API/CLI output (unchanged)

**API serialization note**: `to_api_response()` serializes `self.limits_analysis` verbatim (line 2076), so `limits_analysis.violation_details` will appear in `format="full"` responses as a new additive key. To avoid consumer confusion with the existing top-level `violation_details` (display-oriented, from `_get_violation_details()`), rename the internal key to `compliance_violations`:

```python
# In analyze_portfolio_risk_limits() return dict:
"compliance_violations": violation_details,  # NOT "violation_details"
```

This makes the API response unambiguous:
- `limits_analysis.compliance_violations` — structured, breach-only, for penalty math + audit (new)
- Top-level `violation_details` — display-oriented, string-parsed, includes warnings (unchanged)

All internal references (`calculate_compliance_penalty()`, `limit_violations` derivation, Step 3 orchestrator) use `limits_analysis.get("compliance_violations", [])` instead of `"violation_details"`.

### Step 6b: Add industry to CLI report formatters

Two places display the `LIMIT VIOLATIONS SUMMARY` and enumerate categories:

**File 1**: `portfolio_risk_engine/portfolio_risk_score.py` (line 1672-1682, inside `_format_risk_score_output()` — the legacy full-report helper that captures stdout. NOT inside `display_portfolio_risk_score()` which only prints the score section. The live `run_risk_score_analysis` CLI path at line 1969 uses `result.to_cli_report()` instead.)

After the leverage line (line 1682), add:
```python
industry_count = violations.get('industry', 0)
if industry_count > 0:
    print(f"   Industry: {industry_count}")
```

**File 2**: `core/result_objects/risk.py` (string-based `_format_detailed_risk_analysis`)

After the leverage line, add:
```python
industry_count = violations.get('industry', 0)
if industry_count > 0:
    lines.append(f"   Industry: {industry_count}")
```

Only renders when `industry > 0` — avoids adding noise to the common case where there are no industry violations.

### Step 7: Tests

**New file**: `tests/portfolio_risk_engine/test_risk_score_compliance.py`

**Existing test files to update**: These files have existing contract tests that assert on snapshot shape, flag names, or summary fields. They need updates to account for the new fields and changed behavior:
- `tests/core/test_risk_score_agent_snapshot.py` — snapshot shape assertions may need `raw_score`, `compliance_penalty_points`, `compliance_ceiling_applied` (or assert these default to score/0/False when no penalty)
- `tests/core/test_risk_score_flags.py` — add test for `compliance_penalty_applied` flag, update `excellent_risk` tests for compliance gate
- `tests/mcp_tools/test_risk_score_agent_format.py` — snapshot field coverage in agent format response

| Test | Validates |
|------|-----------|
| `test_no_violations_no_penalty` | Zero violations → penalty = 0, score unchanged |
| `test_single_marginal_violation` | Beta 1.21 vs 1.20 → tiny penalty (<1 point) |
| `test_single_severe_violation` | Concentration 40% vs 20% limit → significant penalty |
| `test_multiple_marginal_violations` | 5 small violations → moderate penalty |
| `test_multiple_severe_violations` | 3 large violations → large penalty (capped at 35%) |
| `test_penalty_cap` | Extreme violations → penalty doesn't exceed MAX_COMPLIANCE_PENALTY_PCT |
| `test_category_changes_after_penalty` | Score 95 with violations → drops below "Excellent" (ceiling at 89) |
| `test_compliance_ceiling_caps_marginal_violations` | Score 98.5 with 5 marginal (1%) violations → capped at 89, category "Good" |
| `test_severity_scales_with_excess` | 1% over → small; 50% over → max severity |
| `test_leverage_lower_weight_than_concentration` | Same excess_pct, leverage penalty < concentration penalty (double-count avoidance) |
| `test_raw_score_preserved_in_details` | `details.raw_score` contains pre-penalty score, `details.compliance_penalty_points` contains total reduction, `details.compliance_ceiling_applied` is bool |
| `test_interpretation_regenerated` | `interpretation.summary` reflects adjusted score, not raw; `risk_assessment[0]` contains compliance penalty context |
| `test_compliance_violations_structure` | `analyze_portfolio_risk_limits()` returns structured `compliance_violations` |
| `test_compliance_violations_excludes_warnings` | Only actual breaches, not approaching-limit warnings |
| `test_compliance_violations_includes_proxy_betas` | Proxy beta violations appear in `compliance_violations` |
| `test_negative_beta_handled` | β = -1.40 vs max 1.20 → internal `violation_details` uses abs() for excess_pct, penalty applied correctly. Note: display-oriented `_get_violation_details()` signed-beta handling is a pre-existing issue, out of scope (see "Not in Scope"). |
| `test_nan_excess_pct_ignored` | NaN excess_pct → skipped, no penalty contribution |
| `test_zero_excess_pct_ignored` | Violation with excess_pct ≤ 0 → no penalty |
| `test_limit_violations_derived_from_structured` | `limit_violations` counts match `compliance_violations` grouping |
| `test_risk_category_enum_maps_all_categories` | Fair → "fair", Poor → "poor", Very Poor → "very_poor" |
| `test_snapshot_includes_raw_score` | `get_agent_snapshot()` has `raw_score`, `compliance_penalty_points`, `compliance_ceiling_applied` |
| `test_flag_emitted_when_penalty_applied` | `compliance_penalty_applied` info flag present when penalty > 0 and score actually changed |
| `test_flag_not_emitted_when_penalty_rounds_to_zero` | Tiny penalty that rounds to same score → no flag, no interpretation augmentation |
| `test_excellent_risk_flag_suppressed_when_non_compliant` | Score ≥ 90 but non-compliant → no `excellent_risk` flag, `non_compliant` flag present |
| `test_multiple_industry_violations` | 3 industries over limit → 3 entries in `compliance_violations`, `limit_violations["industry"] == 3` |
| `test_zero_limit_max_severity` | Limit=0, actual>0 → `excess_pct=1.0` (max severity), penalty applied |
| `test_beta_actual_preserves_sign` | β = -1.40 → `compliance_violations[].actual == -1.40` (signed), `excess_pct` uses abs() |
| `test_warning_only_no_penalty` | Violation at warning level (not over limit) → no `compliance_violations` entry, no penalty |
| `test_industry_only_violation_not_compliant` | Industry-only breach → `is_compliant()` returns False, penalty applied |
| `test_api_violation_details_entry_schema` | `to_api_response()["violation_details"]` entries use `current`/`limit`/`excess` field names |
| `test_warning_only_still_compliant` | Warning text in `risk_factors` but no actual violation → `is_compliant()` True, no penalty |
| `test_summary_total_violations_excludes_warnings` | `get_summary()` returns `total_violations=0` when risk_factors has warnings but no actual limit breaches |
| `test_summary_includes_raw_score_and_penalty` | `get_summary()` returns `raw_score` and `compliance_penalty_points` fields |
| `test_mcp_summary_response_includes_penalty_fields` | `get_risk_score(format="summary")` response contains `raw_score` and `compliance_penalty_points` from `get_summary()` |
| `test_compliance_violations_retained_in_limits_analysis` | `to_api_response()["limits_analysis"]["compliance_violations"]` contains structured entries for audit |
| `test_cli_report_shows_compliance_context` | `to_cli_report()` output contains "Score reduced by" when penalty applied |
| `test_display_risk_score_reads_stored_interpretation` | `display_portfolio_risk_score()` (standalone CLI formatter) reads stored `risk_score["interpretation"]` instead of regenerating — output reflects compliance context |
| `test_verdict_uses_display_category_not_enum` | `get_agent_snapshot()` verdict uses display category (e.g., "Very Poor") not enum form (e.g., "very_poor") |
| `test_format_risk_score_output_includes_industry` | `_format_risk_score_output()` output contains "Industry:" line when `limit_violations["industry"] > 0` |
| `test_end_to_end_score_adjustment` | Full `run_risk_score_analysis()` with violations → adjusted score in result |
| `test_no_compliance_violations_key_graceful` | `calculate_compliance_penalty([])` returns 0.0; `run_risk_score_analysis()` result with empty `compliance_violations` has no penalty, default snapshot fields |

## Files Changed

| File | Change |
|------|--------|
| `portfolio_risk_engine/portfolio_risk_score.py` | Structured `compliance_violations` in `analyze_portfolio_risk_limits()`, `_compute_excess_pct()` helper, derive `limit_violations` from structured data, new `calculate_compliance_penalty()`, penalty + interpretation regen in `run_risk_score_analysis()`, report formatter reads stored interpretation |
| `core/result_objects/risk.py` | Fix `get_risk_category_enum()` (Fair/Poor/Very Poor mapping), fix `get_summary()` total_violations + add raw_score/compliance_penalty_points, wire `raw_score`/`compliance_penalty_points`/`compliance_ceiling_applied` into `get_agent_snapshot()`, fix verdict display category, report paths read stored interpretation |
| `core/risk_score_flags.py` | `compliance_penalty_applied` info flag, suppress `excellent_risk` when non-compliant |
| `mcp_tools/risk.py` | Wire `raw_score`/`compliance_penalty_points` into summary format response (~2 lines) |
| `services/portfolio_service.py` | No changes needed — see error paths note below |
| `docs/schemas/api/risk-score.json` | **Regenerate from a live run** after implementation. This is a concrete example payload — individual field patches would leave it internally inconsistent. Key changes: `risk_score.details` gains `raw_score`/`compliance_penalty_points`/`compliance_ceiling_applied`; `risk_score.interpretation` reflects adjusted score; `limits_analysis` gains `compliance_violations` array and `limit_violations.industry`; `violations_summary.violation_types` gains `industry`; `summary` gains `raw_score`/`compliance_penalty_points`, `risk_category` uses enum form (e.g., `"fair"`), `total_violations` is breach-only count. The score/category/interpretation values must be mutually consistent |
| `docs/schemas/cli/risk_score_result.txt` | **Regenerate from a live run**. Key additions: compliance penalty line in score section, industry violation count in violations summary, stored interpretation with compliance context |
| `tests/portfolio_risk_engine/test_risk_score_compliance.py` | **New** — ~37 tests |
| `tests/core/test_risk_score_agent_snapshot.py` | Update snapshot shape assertions for new fields |
| `tests/core/test_risk_score_flags.py` | Add `compliance_penalty_applied` flag test, update `excellent_risk` gate |
| `tests/mcp_tools/test_risk_score_agent_format.py` | Update agent format response field coverage |

**`PortfolioService.analyze_risk_score()` error paths (pre-existing, out of scope)**:

Two error paths exist today, both pre-existing and unrelated to the compliance penalty:

1. **`run_risk_score()` returns `None`** (computation failure, line 579-602): The service fabricates a default `RiskScoreResult` with score=0, category="Analysis Failed", old-shape `limit_violations` (5 keys, no `industry`, no `compliance_violations`). The fabricated result has `is_compliant()=True` and reports "Compliant" status — misleading for a failed analysis, but immaterial since score=0 and category="Analysis Failed" make the failure obvious. The missing `industry` and `compliance_violations` keys are benign for this error state (no penalty to apply). Changing error handling to show "unknown" compliance is a separate concern.

2. **`app.py:1499` retry with `None` limits**: On database connection error loading risk limits, `app.py` retries `portfolio_service.analyze_risk_score(portfolio_data, None)`. But the service rejects `None` at line 559-563 (raises `ValueError`), so this retry crashes. This is a pre-existing bug in the REST fallback path, unrelated to the penalty.

Neither path requires changes for the compliance penalty. The penalty is computed in `run_risk_score_analysis()` (called by `run_risk_score()`), so if that succeeds, the result already has `compliance_violations` and penalty fields. If it fails (returning None), the fabricated fallback has no violations to penalize.

## Not in Scope

- Changing the 4-component scoring weights or `score_excess_ratio()` curve
- Changing how violations are defined (threshold values in config.py)
- Frontend display changes (API shape `score`, `category`, `component_scores` unchanged)
- **Frontend schema artifacts**: `frontend/packages/connectors/src/schemas/api-schemas.ts` (`RiskScoreResponseSchema`), `frontend/packages/connectors/src/adapters/RiskScoreAdapter.ts`, and `frontend/openapi-schema.json` are NOT updated in this plan. The Zod schema uses `z.object()` (strips undeclared top-level keys) and `risk_score: z.any()` (flexible nested pass-through). Because `limits_analysis` is NOT declared in the Zod schema, it is stripped entirely during validation — `compliance_violations` and `limit_violations.industry` do NOT reach the frontend adapter.

  **Where each new field is consumable:**
  - `raw_score`, `compliance_penalty_points`, `compliance_ceiling_applied` in `risk_score.details` → survives Zod under `z.any()`, but the adapter (`RiskScoreAdapter.ts:482-488`) only copies `excess_ratios`, `leverage_ratio`, `max_loss_limit` from `details`. These new fields are NOT forwarded to the frontend until a follow-up updates the adapter.
  - `raw_score`, `compliance_penalty_points` in REST API `summary` → the `summary` top-level key is also NOT declared in the Zod schema (`api-schemas.ts:152`), so it is stripped during frontend validation just like `limits_analysis`. The adapter reads `riskScore.summary` (`RiskScoreAdapter.ts:476`) from the pre-validation fallback path only (when Zod throws). In the normal success path, `summary` is stripped. These fields are therefore available to raw REST/MCP consumers but not the frontend adapter without a schema follow-up.
  - `compliance_violations` in `limits_analysis` → stripped by Zod. Available via MCP `format="full"` (which serializes `to_api_response()` → `limits_analysis` verbatim) and REST API at `app.py` (returns `result.to_api_response()`). NOT available in MCP agent format (which returns only `snapshot` + `flags`).
  - The MCP agent sees the penalty EFFECT via snapshot fields (`raw_score`, `compliance_penalty_points`, `compliance_ceiling_applied`, adjusted `overall_score` and `risk_category`), plus the `compliance_penalty_applied` flag. This is sufficient for agent reasoning — the per-violation breakdown is an audit detail available in `format="full"`.
  - **Summary**: The primary consumers for the penalty are (1) MCP agent via snapshot fields + flag, and (2) raw REST/MCP API consumers. The frontend adapter does not surface these fields today. No frontend schema/adapter changes are required for structural compatibility (no missing fields, no type errors). However, the frontend DOES need a separate fix to correct the inverted score thresholds (pre-existing bug documented below) — that fix is independent of and predates this plan. Until that fix, the frontend's heuristic signals will remain incorrect for both penalized and non-penalized portfolios.

  **Frontend behavioral impact**: No structural breakage (no missing fields, no type errors, no parse failures). The adjusted score/category values will change behavioral output in frontend heuristic thresholds. In practice, only the overall-score row in `generateComplianceStatus()` (`RiskSettingsAdapter.ts:508`) is live today — the nested `portfolio_limits`/`concentration_limits` reads (`RiskSettingsAdapter.ts:451,472`) resolve to `undefined` because `risk_limits` is a flat object at that point. The resolver signals (`registry.ts:344,387`) also use the overall score. All of these thresholds use inverted semantics (pre-existing bug documented below). The penalty lowers the score, which shifts some portfolios across the inverted thresholds, but the thresholds were already producing incorrect signals. No new bugs are introduced — the existing inversion is orthogonal to the penalty.
- **API reference documentation**: `docs/reference/API_REFERENCE.md` describes the risk-score endpoint with an outdated response shape and unsupported `performance_period` request field. This is a pre-existing documentation gap — the API reference has not been kept in sync with the actual endpoint behavior. Updating the full API reference is out of scope for this plan; only the concrete example payload (`risk-score.json`) is updated to reflect the new fields.
- **RiskScoreResult class docstring**: `core/result_objects/risk.py` lines 1612-1618 document category names as "Moderate"/"Elevated"/"High" and examples at lines 1629-1630 show "Moderate Risk" / "Moderate risk". The actual engine uses "Fair"/"Poor"/"Very Poor". This is a pre-existing documentation inconsistency unrelated to the compliance penalty. A separate docstring sweep can fix it alongside the `API_REFERENCE.md` update.
- **Score semantics documentation (pre-existing inconsistency)**: The `app.py` docstring (line 481: "Lower scores indicate lower risk", line 491-495: "81-100: Very High Risk") and `frontend/packages/chassis/src/types/api-generated.ts` describe inverted semantics (higher = worse). The actual backend scoring engine uses higher = better (90+ = "Excellent", <60 = "Very Poor"). This documentation predates and is independent of the compliance penalty plan. A separate documentation fix should align the docstrings and generated types with the actual engine behavior. This plan does not change the score semantics — it only adds a penalty within the existing "higher = better" framework.
- **Frontend resolver inverted semantics (pre-existing bug)**: Three frontend resolver/adapter sites use `overall_risk_score` (which IS the backend's `risk_score.score`) with inverted thresholds — higher = worse risk:
  - `registry.ts:344`: `overall_risk_score > 75` → warning signal
  - `registry.ts:387`: `overall_risk_score >= 85` → `risk_score_stop` exit signal
  - `RiskSettingsAdapter.ts:508`: `overallScore > 80` → violation status

  The backend uses higher = better (100 = Excellent). These resolvers fire warnings/stops for GOOD portfolios and stay silent for BAD portfolios. This is a pre-existing bug unrelated to and predating the compliance penalty. The compliance penalty lowers the backend score for non-compliant portfolios, which in the inverted frontend world would suppress the (already-incorrect) warnings — but since the warnings were wrong to begin with, this doesn't create a new problem. The MCP agent path (primary consumer of the penalty) reads the score directly from `get_risk_score()` and is unaffected. A separate frontend follow-up should invert these thresholds (e.g., `< 25` for warning, `< 15` for stop).
- **Display methods warning/violation distinction**: Three display-oriented methods on `RiskScoreResult` parse `risk_factors` text and don't distinguish warnings from violations:
  1. `_get_violation_details()` (line 2104) — produces top-level `violation_details` in `to_api_response()`
  2. `_get_violations_summary()` (line 1982) — produces `critical_violations`/`moderate_violations` lists from `risk_factors`
  3. `_get_risk_factors_with_priority()` — categorizes risk factors by keyword

  After this plan, `total_violations` (from structured `limit_violations`) will be breach-only, but `critical_violations` list (from `risk_factors` text) will still include warnings. So `total_violations == 0` with non-empty `critical_violations` is possible. This is a **better** state than before (previously `total_violations` ALSO counted warnings via string-grep, making `is_compliant()` and `total_violations` inconsistent). Now `total_violations` agrees with `is_compliant()`.

  **MCP `format="summary"` note**: The summary response (`mcp_tools/risk.py:591-605`) returns `total_violations` (now breach-only) alongside `risk_factors` and `recommendations` (still warning-inclusive text from `limits_analysis`). This means `is_compliant=True` / `total_violations=0` can coexist with warning-text entries like "High market beta (1.18 vs 1.20 limit)". The authoritative compliance signals (`is_compliant`, `total_violations`) are correct and internally consistent. The `risk_factors` text is context — it shows approaching-limit situations that are useful for the agent even when compliant. Adding `severity` tags to `risk_factors` text would require changes to `analyze_portfolio_risk_limits()` text generation, which is out of scope.

  Changing these display methods was attempted in Round 2 and caused Round 3's HIGH — too risky for this scope. The authoritative compliance signals are: `is_compliant()`, `total_violations` (from `limit_violations`), and `limits_analysis.compliance_violations` (structured, breach-only). Display fields are context, not compliance signals. A future follow-up can add `"severity"` tagging to display entries.

## Codex Review History (Rounds 1-21)

29 review rounds resolved 19 HIGHs, 40+ MEDIUMs. Key design decisions from review:

- **R1-R3**: Signed beta handling via `abs()`, structured `limit_violations` replacing string-grep, interpretation regeneration, industry/proxy beta coverage, `_get_violation_details()` left unchanged (two coexisting data paths)
- **R4-R5**: `get_summary()` total_violations fix, compliance-aware interpretation text, substring-matching preserved in `get_risk_category_enum()`
- **R6-R8**: Report formatters read stored interpretation, `excellent_risk` flag gated on compliance, per-industry iteration, flag numeric coercion
- **R9-R11**: `compliance_violations` key rename (avoids API ambiguity), `isinstance()` guard, zero-limit `_compute_excess_pct()` helper, signed beta audit preservation
- **R12-R13**: Zero max_beta documented as pre-existing, compliance ceiling added (89 cap), schema docs added
- **R14-R15**: Exposed fields simplified (`raw_score` + `compliance_penalty_points` + `compliance_ceiling_applied`), ceiling keyed off `limit_violations` count (not penalty magnitude), verdict uses display category
- **R16-R17**: Flag wording made neutral + ceiling-aware suffix, stale field names cleaned up, frontend `z.object()` behavior corrected (plain, not `.passthrough()`), `calculate_portfolio_risk_score()` bypass claim narrowed to production callers
- **R18**: Frontend inverted semantics documented as pre-existing bug (resolvers treat higher score as worse risk — independent of penalty). `limits_analysis` Zod stripping correctly documented (stripped entirely, not passed through). Both added to Not in Scope with impact analysis
- **R19**: Corrected claim that `compliance_violations` reaches MCP agent path — agent format returns only `snapshot` + `flags`, not `limits_analysis`. Detailed per-field consumability table added. Frontend "no breakage" clarified as structural-only (no type/field errors), behavioral changes from adjusted scores acknowledged + tied to pre-existing inverted thresholds. `RiskScoreResult.get_summary()` REST API exposure documented (risk-score endpoint at `app.py:1507`). Existing test files (`test_risk_score_agent_snapshot.py`, `test_risk_score_flags.py`, `test_risk_score_agent_format.py`) added to Files Changed for contract test updates
- **R20**: `summary` top-level key also stripped by Zod (not declared in schema) — consumability note expanded. `generateComplianceStatus()` precision: only overall-score row is live (nested limit reads → undefined). `excellent_risk` gate rationale tightened: ceiling already prevents score ≥ 90 when non-compliant, gate is defense-in-depth
- **R21**: "No changes needed for correctness" softened — structural compatibility confirmed, but frontend inverted thresholds still need separate fix for correct behavior. `app.py` line references corrected: only `analyze_risk_score()` (line 1507) uses `RiskScoreResult.get_summary()`, other lines use different result types. Score semantics documentation inconsistency (`app.py` docstring says "lower = lower risk", engine uses "higher = better") documented as pre-existing, added to Not in Scope
- **R22**: MCP `format="summary"` warning/violation text coexistence explicitly documented (risk_factors text is context, not compliance signal). `PortfolioService.analyze_risk_score()` None-fallback path documented (self-consistent error state, no changes needed). `violations_summary.violation_types.industry` added to schema docs update (auto-derived from `limit_violations`)
- **R23**: Schema docs update expanded to cover `summary` object changes (`raw_score`, `compliance_penalty_points`, `total_violations` semantics, `risk_category` examples). Helper docstrings (`display_portfolio_risk_score()` line 1476, 1628) updated to reference `run_risk_score_analysis()` instead of `calculate_portfolio_risk_score()` for programmatic consumers
- **R24**: `risk-score.json` clarified as concrete example payload (not schema) — specific line numbers and example values to update. REST API test coverage addressed: unit tests cover `get_summary()` + `to_api_response()` content, live verification step added for `POST /api/risk-score`, route-level integration tests out of scope (manual smoke script only). Stale "8+ endpoints" in R19 history corrected to risk-score endpoint only. PortfolioService fallback test added to matrix
- **R25**: `risk_category` example value corrected to enum form (`"fair"` not `"Fair"`) matching `get_risk_category_enum()`. `docs/reference/API_REFERENCE.md` documented as pre-existing stale (out of scope for this plan)
- **R26**: Step 1 variable naming fixed (`for v in violation_details` not `compliance_violations` — local var is `violation_details`, returned key is `"compliance_violations"`). Example artifacts (`risk-score.json`, `risk_score_result.txt`) changed from individual field patches to "regenerate from live run" to ensure internal consistency. `display_portfolio_risk_score()` stored interpretation test added to matrix
- **R27**: Docstring section expanded from 2 to 3 stale references (added `display_portfolio_risk_score()` parameter doc at line 1483). Step 6b File 1 correctly identified as `display_portfolio_risk_score()` (not "`run_risk_score_analysis`" — live CLI path uses `result.to_cli_report()` at line 1969). Verdict string display-category test added to matrix
- **R28**: Step 6b File 1 corrected from `display_portfolio_risk_score()` to `_format_risk_score_output()` (line 1672-1682) — the violations summary block is in the full-report helper, not the score-only display function. `_format_risk_score_output()` industry line test added to matrix. `RiskScoreResult` class docstring "Moderate/Elevated/High" category names documented as pre-existing inconsistency (out of scope)
- **R29**: Fallback path fully rewritten. Two error paths documented: (1) `run_risk_score()` → None fabrication (compliance=True misleading but immaterial at score=0, pre-existing); (2) `app.py` retry with `None` limits crashes (pre-existing bug, service rejects None at line 559). Neither requires penalty changes. Removed inaccurate `test_portfolio_service_fallback_no_crash` test, replaced with `test_no_compliance_violations_key_graceful`
- **R30**: **PASS** — no findings. Plan consistent with all source files. Static review only (tests and live verification deferred to implementation).

## Verification

1. `python3 -m pytest tests/portfolio_risk_engine/test_risk_score_compliance.py -x -v` — all new tests pass
2. `python3 -m pytest tests/ -x -q` — no regressions (including existing tests in `test_risk_score_agent_snapshot.py`, `test_risk_score_flags.py`, `test_risk_score_agent_format.py`)
3. Live test: `get_risk_score(format="full")` — verify `details.raw_score` and `details.compliance_penalty_points` appear when violations present
4. Live test: `get_risk_score(format="agent")` — verify snapshot has `raw_score`, `compliance_penalty_points`, and `risk_category` is not `"unknown"` for Fair/Poor
5. Live test: `POST /api/risk-score` → verify `summary.raw_score` and `summary.compliance_penalty_points` appear in the REST response when violations present
6. Verify the analyst scenario: score should no longer show "Excellent" with multiple violations

**REST API test coverage note**: The REST API at `app.py:1495-1507` assembles its payload from `result.get_summary()` and `result.to_api_response()` — both of which are thoroughly tested at the unit level (Steps 4b, 5, 7). The existing API test file (`tests/api/test_api_endpoints.py`) is a skipped manual smoke script, not automated integration tests. Adding full route-level integration tests would require a running server with portfolio data and is out of scope for this plan. The live verification steps (3-5 above) cover the API surface manually.

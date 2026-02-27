# Plan: Leverage Capacity Calculator

_Created: 2026-02-19_
_Last updated: 2026-02-19 (v4 — Codex review round 3 resolutions)_

## Context

The user has a portfolio with unlevered risk limits (max_volatility, max_loss) set via their custom risk profile. They want to know: "How much leverage can I run before hitting a risk limit?" Currently, `get_risk_analysis()` checks compliance at current leverage but doesn't tell you how much headroom you have.

## Key Insight — Which Limits Scale With Leverage

When weight normalization is off (`normalize_weights: False` in `settings.py:153`), raw weights flow through the analysis and reflect actual leverage. Here's how each limit behaves:

| Limit | Scales? | Why |
|-------|---------|-----|
| `max_volatility` | **Yes** | Vol computed from raw weights — scales linearly |
| `max_loss` | **Yes (derived)** | No native metric — use parametric VaR (`vol * 1.65`), scales linearly |
| `max_single_stock_weight` | **Yes** | Checked against raw `Portfolio Weight` column (`run_portfolio_risk.py:431`) — weight = $pos/total_value, scales with leverage |
| `max_factor_contribution` | **Approximately no** | Variance proportion — ratio of factor var to total var. Both numerator and denominator scale with L², so ratio is ~invariant |
| `max_market_contribution` | **Approximately no** | Same reasoning — variance proportion ratio |
| `max_industry_contribution` | **Approximately no** | Same reasoning — variance proportion ratio |
| `max_single_factor_loss` | **Yes** | Portfolio betas are weighted sums of stock betas using raw weights (`portfolio_risk.py:1135`) — they scale with leverage. Beta limits (`max_betas`) are fixed (computed from historical worst-case returns + `max_single_factor_loss` param, not from leverage — `risk_helpers.py:322`). So portfolio betas grow with leverage while max_betas stay fixed → constraint tightens. |

**Corrected classification:** 4 constraints scale with leverage (vol, loss, stock weight, factor betas). Variance contributions are approximately invariant (L² cancels in ratio).

**Factor beta capacity:** For each factor/proxy, `max_L = max_allowed_beta / (abs(portfolio_beta) / L_eff)`. The beta check in the analysis already compares factor-level betas AND per-proxy betas (e.g., `industry_proxy::SOXX`) — when proxy betas exist, the aggregate `industry` factor is skipped (`run_portfolio_risk.py:349-353`). The capacity calculation must mirror this: use `analysis_result.beta_checks` (which contains all checked factors/proxies with `portfolio_beta`, `max_allowed_beta`, and `buffer`) and compute capacity for each row. Take the min across all checked betas.

## Approach

**New backend function + MCP tool.** The backend function takes an existing `RiskAnalysisResult` (already computed by `analyze_portfolio()`) and the risk limits, then computes leverage capacity analytically. The MCP tool runs the risk analysis, then calls the capacity function.

### Formula

Given current analysis results with effective leverage `L_eff` (computed from analyzed weights):

```
# Compute effective leverage from analyzed weights
L_eff = sum(abs(analyzed_weights))

# Normalize to unit leverage
vol_at_1x = current_vol / L_eff
max_weight_at_1x = max_stock_weight / L_eff

# Compute max leverage for each scaling constraint
max_L_from_vol = vol_limit / vol_at_1x
max_L_from_weight = weight_limit / max_weight_at_1x
max_L_from_loss = |max_loss_limit| / (vol_at_1x * 1.65)
max_L_from_betas = min(max_allowed_beta / (abs(portfolio_beta) / L_eff)) for each factor

# Binding constraint
max_leverage = min(max_L_from_vol, max_L_from_weight, max_L_from_loss, max_L_from_betas)
binding_constraint = whichever produced the min
```

**Headroom** = `max_leverage - effective_leverage` (positive = room to grow, negative = already in violation)

### Effective leverage from analyzed weights

The stored `analysis_result.leverage` comes from `standardize_portfolio_input()` (pre-analysis). If tickers are excluded during analysis, weights are re-normalized (`portfolio_risk.py:1331`) and stored leverage no longer matches the effective leverage of the analyzed weights.

**Solution:** Compute effective leverage directly from the analyzed weights in the result, not from the stored `leverage` field:

```python
analyzed_weights = analysis_result.allocations["Portfolio Weight"]
effective_leverage = analyzed_weights.abs().sum()  # gross exposure of analyzed weights
```

When `normalize_weights: False` (current setting — `settings.py:153`), this gives the true leverage that the vol/weight/beta calculations used. This handles both the normal case and the ticker-exclusion edge case correctly.

`vol_at_1x = volatility_annual / effective_leverage` is then valid because vol was computed from these exact weights.

### Max-loss estimation

`evaluate_portfolio_risk_limits()` does NOT currently check max_loss (`run_portfolio_risk.py:398` — only 5 checks, none for max_loss). `RiskAnalysisResult` has no native `current_max_loss` field.

We derive it as **`implied_var95_loss`**: `loss_estimate = vol_annual * 1.65` (95% parametric VaR, 1-year horizon). This is clearly labeled as a derived proxy metric with its method name, distinct from any future scenario-based loss metric.

## Changes

### 1. New backend function in `core/portfolio_analysis.py`

```python
def compute_leverage_capacity(
    analysis_result: RiskAnalysisResult,
    risk_limits: dict,
) -> dict:
```

**Inputs:**
- `analysis_result` — already-computed result from `analyze_portfolio()`
- `risk_limits` — dict with `portfolio_limits`, `concentration_limits`, `variance_limits`

**Extracts from analysis_result:**
- `analysis_result.volatility_annual` — current portfolio vol at effective leverage
- `analysis_result.allocations["Portfolio Weight"]` — analyzed weights (for effective leverage + max stock weight)
- `analysis_result.variance_decomposition` — factor/market/industry variance % (for invariant reference)
- `analysis_result.beta_checks` — list of dicts with `factor`, `portfolio_beta`, `max_allowed_beta`, `pass`, `buffer` for each checked factor/proxy (mirrors `evaluate_portfolio_beta_limits()` output)

**Computation:**
1. Compute `effective_leverage = allocations["Portfolio Weight"].abs().sum()`
2. Validate effective_leverage is finite, positive, non-zero
3. `vol_at_1x = volatility_annual / effective_leverage`
4. `loss_at_1x = vol_at_1x * 1.65` (parametric VaR 95%)
5. `max_weight = allocations["Portfolio Weight"].abs().max()`
6. `max_weight_at_1x = max_weight / effective_leverage`
7. For vol constraint: `max_L = max_volatility / vol_at_1x`
8. For loss constraint: `max_L = abs(max_loss) / loss_at_1x`
9. For weight constraint: `max_L = max_single_stock_weight / max_weight_at_1x`
10. For each entry in `beta_checks`: `beta_at_1x = abs(portfolio_beta) / effective_leverage`, then `max_L = max_allowed_beta / beta_at_1x`. Take min across all checked factors/proxies (includes `industry_proxy::*` entries).
11. Cap all at reasonable max (10x) when denominator near zero
12. `max_leverage = min(all scaling constraints)`
13. `headroom = max_leverage - effective_leverage`
14. Collect variance contribution limits as invariant reference

**Edge cases:**
- `effective_leverage` is 0, negative, inf, or NaN → return error
- `vol_at_1x ≈ 0` or `beta_at_1x ≈ 0` → cap max_leverage at 10x
- Already in violation (current metric > limit) → `max_leverage < effective_leverage`, headroom is negative. Report as-is — negative headroom clearly indicates how far over the limit the portfolio is.
- Missing risk limits sections → skip that constraint
- Invariant limits already failing → note in response (these can't be fixed by changing leverage)
- No beta checks available (empty `beta_checks`) → skip beta constraint

**Returns:**
```python
{
    "effective_leverage": 1.53,     # computed from analyzed weights
    "max_leverage": 1.61,
    "headroom": 0.08,
    "headroom_pct": 0.05,
    "binding_constraint": "volatility",
    "constraints": {
        "volatility": {
            "current": 0.19,
            "at_unit_leverage": 0.124,
            "limit": 0.20,
            "max_leverage": 1.61,
            "headroom": 0.08,
        },
        "max_loss": {
            "current_implied": -0.314,
            "at_unit_leverage": -0.205,
            "limit": -0.25,
            "max_leverage": 1.22,
            "headroom": -0.31,
            "method": "parametric_var_95",
        },
        "max_single_stock_weight": {
            "current": 0.32,
            "at_unit_leverage": 0.209,
            "limit": 0.35,
            "max_leverage": 1.67,
            "headroom": 0.14,
        },
        "factor_betas": {
            "binding_factor": "market",
            "current_beta": 1.10,
            "at_unit_leverage": 0.719,
            "max_allowed_beta": 1.25,
            "max_leverage": 1.74,
            "headroom": 0.21,
        },
    },
    "invariant_limits": {
        "max_factor_contribution": {"actual": 0.85, "limit": 0.85, "pass": True},
        "max_market_contribution": {"actual": 0.50, "limit": 0.60, "pass": True},
        "max_industry_contribution": {"actual": 0.42, "limit": 0.50, "pass": True},
    },
    "warnings": [],
    "note": "Variance contribution limits are approximately leverage-invariant and shown for reference. Max-loss is derived via parametric VaR (95%, 1Y). Factor beta capacity uses the tightest factor.",
}
```

### 2. New MCP tool `get_leverage_capacity()`

**`mcp_tools/risk.py`** — new function:

```python
def get_leverage_capacity(
    user_email: Optional[str] = None,
    portfolio_name: str = "CURRENT_PORTFOLIO",
    use_cache: bool = True,
) -> dict:
```

**Flow:**
1. Resolve user via `resolve_user_email()` (existing pattern)
2. Load portfolio via `_load_portfolio_for_analysis()` (existing shared helper)
3. Load risk limits via `RiskLimitsManager(use_database=True, user_id=user_id).load_risk_limits(portfolio_name)` (matches existing MCP pattern in `get_risk_analysis()` at line ~404)
4. If no limits or limits are empty → return error: "No risk limits configured. Use set_risk_profile() first."
5. Run `analyze_portfolio()` via `PortfolioService` (existing path)
6. Call `compute_leverage_capacity(result, risk_limits_dict)`
7. Return structured response with `status: "success"` wrapper

### 3. Register in MCP server

**`mcp_server.py`** — add `get_leverage_capacity` wrapper:

```python
@mcp.tool()
def get_leverage_capacity(
    portfolio_name: str = "CURRENT_PORTFOLIO",
    use_cache: bool = True,
) -> dict:
    """
    Compute maximum leverage before hitting risk limits.

    Returns the binding constraint, max leverage multiplier, and headroom
    for each scaling limit (volatility, max loss, stock weight, factor betas).
    Variance contribution limits are approximately leverage-invariant
    and shown for reference.

    Args:
        portfolio_name: Portfolio to analyze (default: "CURRENT_PORTFOLIO").
        use_cache: Use cached position data.

    Returns:
        Max leverage, binding constraint, headroom, and per-constraint breakdown.
    """
```

## Files to Modify

| File | Change | Size |
|------|--------|------|
| `core/portfolio_analysis.py` | Add `compute_leverage_capacity()` function | ~80 lines |
| `mcp_tools/risk.py` | Add `get_leverage_capacity()` MCP tool | ~50 lines |
| `mcp_server.py` | Register new tool | ~20 lines |

## What Doesn't Change

- `analyze_portfolio()` — unchanged, we just consume its result
- Risk limits / profiles — unchanged
- `evaluate_portfolio_risk_limits()` — unchanged
- DB schema — no changes

## Key Files Referenced

- `core/portfolio_analysis.py` — `analyze_portfolio()` (line 54), result construction (line 167)
- `core/result_objects.py` — `RiskAnalysisResult` fields: `volatility_annual`, `leverage`, `variance_decomposition`, `allocations`, `analysis_metadata`
- `run_portfolio_risk.py` — `evaluate_portfolio_risk_limits()` (line 398) — existing compliance checks, weight extraction pattern
- `portfolio_risk.py` — `normalize_weights()` (line 75), `build_portfolio_view()` (line 1310), ticker exclusion re-normalization (line 1331)
- `settings.py` — `normalize_weights: False` (line 153) — confirms raw weights flow through
- `mcp_tools/risk.py` — `_load_portfolio_for_analysis()` shared helper, risk limits loading pattern (line ~404)
- `inputs/risk_limits_manager.py` — `RiskLimitsManager.load_risk_limits()` for DB-backed limits

## Verification

1. `get_leverage_capacity()` — returns current leverage, max leverage, binding constraint, headroom
2. At current leverage (~1.53x), check which constraint binds first
3. If already in violation (current metric > limit), headroom is negative
4. Stock weight constraint included — e.g., if largest position is 32% and limit is 35%, weight constraint max_leverage = 1.67x
5. Variance contribution limits shown as ~invariant reference
6. Missing risk limits → clear error asking user to set a profile first
7. Non-finite/zero leverage edge case → handled gracefully with error
8. Max-loss labeled as `method: "parametric_var_95"` — clearly derived, not native

## Codex Review Notes

### v1 → v2 resolutions

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 1 | "Only 2 limits scale" is wrong — `max_single_stock_weight` scales too, betas may also | High | **Fixed**: Reclassified. 3 constraints scale (vol, loss, weight). Variance contributions ~invariant (L² cancels). Factor loss limits complex — included in invariant reference with caveat. |
| 2 | `vol / leverage` not generally valid due to weight normalization and ticker exclusions | High | **Fixed**: Documented that `normalize_weights: False` (settings.py:153) means raw weights flow through, making `vol/leverage` valid. Added ticker exclusion caveat — if tickers dropped, weights are re-normalized and approximation is noted in warnings. |
| 3 | No existing `max_loss` metric in analysis result | High | **Fixed**: Explicitly defined as derived `implied_var95_loss = vol_annual * 1.65`. Labeled with `method: "parametric_var_95"` to distinguish from any future native metric. |
| 4 | Parametric VaR inconsistent with existing loss semantics | Medium | **Fixed**: Labeled as distinct derived metric. Not replacing existing risk score logic — additive proxy for capacity calculation only. |
| 5 | `resolve_risk_config()` falls back to YAML, not DB | Medium | **Fixed**: Changed to use `RiskLimitsManager.load_risk_limits()` (matches existing MCP pattern in `get_risk_analysis()`). Returns error if no limits configured. |
| 6 | Edge cases incomplete — non-finite leverage, already-failing invariant limits | Medium | **Fixed**: Added handling for inf/NaN/negative leverage. If invariant limits already failing, noted in response (capacity is effectively 0). |
| 7 | Should document exact source fields vs derived fields | Low | **Fixed**: Listed exact `RiskAnalysisResult` fields used and which metrics are derived. |

### v2 → v3 resolutions

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 8 | `max_single_factor_loss` / beta limits DO scale with leverage — portfolio betas built from raw weights | High | **Fixed**: Reclassified as scaling constraint (4th). Added factor beta capacity: `max_L = max_allowed_beta / (portfolio_beta / L_eff)` for each factor, take min. Uses `portfolio_factor_betas` and `max_betas` from analysis result. |
| 9 | `analysis_metadata["excluded_tickers"]` not populated — can't detect ticker exclusions | High | **Fixed**: Eliminated dependency on stored leverage. Now compute `effective_leverage = allocations["Portfolio Weight"].abs().sum()` directly from analyzed weights. This is always correct regardless of ticker exclusions. |
| 10 | Warning-only for ticker exclusion not sufficient | Medium | **Fixed**: Replaced with `effective_leverage` approach — no warning needed. The capacity calculation uses the same weights that produced the vol/beta/weight metrics, so it's exact. |

### v3 → v4 resolutions

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 11 | Beta capacity only checks `portfolio_factor_betas` + `max_betas` but actual enforcement also checks per-proxy betas (`industry_proxy::*`) | High | **Fixed**: Changed to iterate `beta_checks` (which contains all checked factors AND proxies from `evaluate_portfolio_beta_limits()`). This mirrors the actual enforcement logic — when proxy betas exist, aggregate industry is skipped and proxies are checked instead. |
| 12 | Doc mixes `L_current` and `effective_leverage` for headroom; ambiguous "capacity is 0" vs "negative headroom" | Low | **Fixed**: Unified on `effective_leverage` throughout. Clarified: negative headroom means already in violation (not capacity=0). Headroom formula is always `max_leverage - effective_leverage`. |

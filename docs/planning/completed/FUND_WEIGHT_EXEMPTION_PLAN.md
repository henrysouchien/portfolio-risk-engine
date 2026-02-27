# Plan: Exempt Funds/ETFs from Single-Stock Weight Check (B-015)

_Created: 2026-02-18_
_Last updated: 2026-02-18 (v3 — Codex review round 2 resolutions)_

## Context

The `max_single_stock_weight` risk limit is meant to flag single-company concentration risk. But it currently treats diversified vehicles (closed-end funds, ETFs, mutual funds) the same as single stocks. DSU (BlackRock Debt Strategies Fund) at ~35% weight triggers the limit even though it holds dozens of underlying positions. The principle: **single-company positions should be checked, but diversified funds should be exempt**.

## Current State

**Weight check in `evaluate_portfolio_risk_limits()`** (`run_portfolio_risk.py:430-439`):
```python
weights = summary["allocations"]["Portfolio Weight"]
max_weight = weights.abs().max()  # ← no filtering, includes funds
```

**Weight check in `compute_leverage_capacity()`** (`core/portfolio_analysis.py:249-250`):
```python
max_weight = float(weights.abs().max())  # ← same issue
```

**Classification pipeline:**
- `SecurityTypeService.get_security_types()` returns raw type: `{'DSU': 'fund', 'SPY': 'etf', 'AAPL': 'equity'}` (`security_type_service.py:216`)
- `SecurityTypeService.get_asset_classes()` resolves to underlying class: `{'DSU': 'bond', 'SPY': 'equity', 'AAPL': 'equity'}` — the `"mixed"` intermediate value is explicitly skipped at Tier 4 (`security_type_service.py:872`) and funds go through AI fallback to get their true underlying asset class
- `SecurityTypeService.get_full_classification()` returns both in one call: `{'DSU': {'security_type': 'fund', 'asset_class': 'bond'}}` (`security_type_service.py:959`)
- Currently only `asset_classes` is fetched in `portfolio_service.py:198` and stored in `analysis_metadata["asset_classes"]` (`core/portfolio_analysis.py:188`)
- `security_types` is **not** currently stored in the analysis pipeline

## Approach

Filter out diversified vehicles by **security type** (not asset class) before computing `max_weight`. Use `security_type in {"etf", "fund", "mutual_fund"}` to identify diversified vehicles.

**Why security type, not asset class:** `get_asset_classes()` resolves funds to their underlying class (DSU → `"bond"`, SPY → `"equity"`). The `"mixed"` intermediate is never the final output. Security type preserves the fund/ETF distinction we need.

### What qualifies as exempt

Tickers with `security_type` in `{"etf", "fund", "mutual_fund"}`. These are the diversified vehicle types in `SECURITY_TYPE_TO_ASSET_CLASS` (`core/constants.py:82-93`). All single-issuer positions (equities, bonds, REITs, etc.) remain subject to the check.

Define this set as a constant: `DIVERSIFIED_SECURITY_TYPES = {"etf", "fund", "mutual_fund"}`.

## Changes

### 1. `services/portfolio_service.py` — fetch security types alongside asset classes

Switch from `get_asset_classes()` to `get_full_classification()` (line 198) to get both security types and asset classes together. `get_full_classification()` internally calls `get_security_types()` + `get_asset_classes()` separately, but both benefit from DB/TTL caching so the overhead is minimal. Store `security_types` in the portfolio data that flows to the analysis.

```python
# Line 198 — replace:
asset_classes = SecurityTypeService.get_asset_classes(tickers, portfolio_data)
# with:
full_classification = SecurityTypeService.get_full_classification(tickers, portfolio_data)
asset_classes = {t: c["asset_class"] for t, c in full_classification.items()}
security_types = {t: c["security_type"] for t, c in full_classification.items()}
```

Pass `security_types` alongside `asset_classes` through to `analyze_portfolio()` or store it in `portfolio_data` so it reaches the analysis metadata.

### 2. `core/portfolio_analysis.py` — three changes

**a) Accept `security_types` parameter in `analyze_portfolio()`:**
```python
def analyze_portfolio(
    portfolio, risk_limits, *,
    asset_classes=None,
    security_types=None,  # NEW
):
```

**b) Pass `security_types` to `evaluate_portfolio_risk_limits()` (line 155):**
```python
df_risk = evaluate_portfolio_risk_limits(
    summary,
    risk_config["portfolio_limits"],
    risk_config["concentration_limits"],
    risk_config["variance_limits"],
    security_types=security_types,  # NEW
)
```

**c) Store `security_types` in `analysis_metadata` (line 188):**
```python
"security_types": security_types,  # NEW — alongside existing "asset_classes"
```

**d) Filter weights in `compute_leverage_capacity()` (around line 249):**
```python
DIVERSIFIED_SECURITY_TYPES = {"etf", "fund", "mutual_fund"}
security_types = (getattr(analysis_result, "analysis_metadata", None) or {}).get("security_types")
if security_types:
    single_issuer_tickers = [t for t in weights.index if security_types.get(t) not in DIVERSIFIED_SECURITY_TYPES]
    weight_check = weights.loc[single_issuer_tickers] if single_issuer_tickers else weights
else:
    weight_check = weights
max_weight = float(weight_check.abs().max()) if not weight_check.empty else 0.0
```

### 3. `run_portfolio_risk.py` — `evaluate_portfolio_risk_limits()`

Add `security_types: Optional[Dict[str, str]] = None` parameter. Filter weights before computing max:

```python
DIVERSIFIED_SECURITY_TYPES = {"etf", "fund", "mutual_fund"}

def evaluate_portfolio_risk_limits(
    summary, portfolio_limits, concentration_limits, variance_limits,
    security_types=None,  # NEW
):
    ...
    # 2. Concentration Check — exempt diversified vehicles
    weights = summary["allocations"]["Portfolio Weight"]
    if security_types:
        single_issuer = [t for t in weights.index if security_types.get(t) not in DIVERSIFIED_SECURITY_TYPES]
        check_weights = weights.loc[single_issuer] if single_issuer else weights
    else:
        check_weights = weights
    max_weight = check_weights.abs().max() if not check_weights.empty else 0.0
```

### 4. `portfolio_optimizer.py` — 4 callers (optional, can defer)

There are 4 calls to `evaluate_portfolio_risk_limits()` in `portfolio_optimizer.py` (lines 96, 498, 792, 1295). These would get the fallback behavior (no filtering) since `security_types` defaults to `None`. This is acceptable for now — optimizer flows don't currently pass security types and the concentration check in those contexts is less critical. Can be addressed separately if needed.

### 5. No other changes needed

- `mcp_server.py` — no change (tool signature unchanged)
- `mcp_tools/risk.py` — no change (pass-through unchanged)
- `core/constants.py` — no change
- `SecurityTypeService` — no change (classification already works)
- DB schema — no change

## Files to Modify

| File | Change | Size |
|------|--------|------|
| `services/portfolio_service.py` | Switch to `get_full_classification()`, pass `security_types` through | ~8 lines |
| `core/portfolio_analysis.py` | Accept + pass `security_types`, store in metadata, filter in leverage capacity | ~15 lines |
| `run_portfolio_risk.py` | Add `security_types` param + filter in weight check | ~10 lines |

## What Doesn't Change

- Risk limits / profiles — unchanged
- `build_portfolio_view()` — unchanged
- MCP tool signatures — unchanged
- DB schema — no changes
- `portfolio_optimizer.py` callers — fallback behavior (no filtering), can defer

## Edge Cases

- **No security_types available** (CLI, optimizer, legacy callers): defaults to `None` → falls back to current behavior (no filtering)
- **All positions are funds**: `check_weights` is empty → `max_weight = 0.0` → weight check always passes (correct — no single-stock concentration)
- **Ticker in weights but not in security_types**: `.get(t)` returns `None`, which is `not in DIVERSIFIED_SECURITY_TYPES` → treated as single-issuer (safe default)
- **`compute_leverage_capacity` weight constraint**: uses same filtered max_weight, so leverage capacity from weight will be higher (more headroom) when the largest position is a fund

## Key Files Referenced

- `run_portfolio_risk.py:398-439` — `evaluate_portfolio_risk_limits()` with weight check at line 430
- `core/portfolio_analysis.py:57` — `analyze_portfolio()` signature
- `core/portfolio_analysis.py:155` — call site for `evaluate_portfolio_risk_limits()`
- `core/portfolio_analysis.py:188` — `analysis_metadata` dict
- `core/portfolio_analysis.py:215-400` — `compute_leverage_capacity()` with weight at line 249
- `core/constants.py:82-93` — `SECURITY_TYPE_TO_ASSET_CLASS` mapping
- `services/security_type_service.py:216` — `get_security_types()` returns raw types
- `services/security_type_service.py:872` — Tier 4 skips `"mixed"` for asset classes
- `services/security_type_service.py:959` — `get_full_classification()` returns both
- `services/portfolio_service.py:198` — where classification is fetched
- `portfolio_optimizer.py:96,498,792,1295` — 4 callers of `evaluate_portfolio_risk_limits()` (deferred)

## Codex Review Notes

### v1 → v2 resolutions

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 1 | `"mixed"` asset class is never the final output — `get_asset_classes()` resolves through AI fallback | High | **Fixed**: Switched from asset class to security type filtering. Use `security_type in {"etf", "fund", "mutual_fund"}` instead of `asset_class == "mixed"`. |
| 2 | `portfolio_optimizer.py` has 4 callers of `evaluate_portfolio_risk_limits()` not addressed | High | **Fixed**: Documented as deferred — those callers get fallback behavior (`security_types=None` → no filtering). Acceptable for now since optimizer doesn't pass security types. |
| 3 | `calculate_concentration_risk_loss()` in `portfolio_risk_score.py` has parallel max-weight issue | Medium | **Acknowledged**: Risk score concentration uses security-type-aware crash scenarios (funds get 40% vs 80% for equity) which partially mitigates. Full fix deferred — separate concern. |
| 4 | `SECURITY_TYPE_TO_ASSET_CLASS` mapping described as filtering criterion but it's not used that way | Medium | **Fixed**: Clarified that the mapping is only referenced for context. Filtering uses raw security type values directly. |

### v2 → v3 resolutions

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 5 | `get_full_classification()` does not avoid double lookup — internally calls both `get_security_types()` and `get_asset_classes()` | Low | **Fixed**: Updated plan text to note caching makes the double call cheap, not that it avoids the lookup. |
| 6 | `analyze_portfolio_risk_limits()` in `portfolio_risk_score.py` (line 626-639) has the same unfiltered `weights.abs().max()` — creates inconsistency with risk analysis compliance | Medium | **Acknowledged**: `portfolio_risk_score.py` is the risk scoring path (`get_risk_score()`), not the risk analysis path (`get_risk_analysis()`). The risk score already uses security-type-aware crash scenarios that partially mitigate (funds get 40% crash vs 80% for equity). Fixing this in the risk score path is a separate concern — it would require threading `security_types` through the scoring pipeline which is a different call chain (`analyze_risk_score()` → `calculate_concentration_risk_loss()`). Documenting as known inconsistency for follow-up. |

## Verification

1. Run `get_leverage_capacity()` via MCP — `max_single_stock_weight` constraint should no longer show DSU as the binding weight; should show next-largest single-stock position instead
2. Run `get_risk_analysis(include=["compliance"])` — Max Weight check should use the largest non-fund position
3. Existing tests should still pass (`security_types` defaults to `None` → no behavior change)

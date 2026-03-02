# Futures Phase 4: Risk Integration

## Context

Futures positions currently flow through `get_risk_analysis()` but are nearly invisible: they get margin-based weights (~3% for ES when it should be ~46%) and zero factor attribution (100% idiosyncratic). This phase makes the risk engine futures-aware with correct notional weights, asset-class proxy factors, and a segment view.

**What this phase does:**
- Notional-weighted risk decomposition (futures weighted by economic exposure, not margin)
- Asset-class proxy factors for non-equity futures (commodity → GLD/USO, fixed_income → interest_rate factor via "bond" class)
- Segment view: run risk on equities-only, futures-only, or combined
- Wire FX attribution from `build_portfolio_view()` into `RiskAnalysisResult`
- Futures leverage flag in risk flags

**What this phase does NOT do:**
- Change `total_value` display (stays margin-based = NAV)
- Add a full macro factor model (uses proxy ETFs within existing factor framework)
- Performance attribution (Phase 5)

## Changes

### 1. Notional Weights — `portfolio_risk_engine/portfolio_config.py`

**Where:** `standardize_portfolio_input()` (line 132)

Thread `instrument_types` as a new keyword-only parameter:

```python
def standardize_portfolio_input(
    raw_input, price_fetcher, *,
    currency_map=None, fmp_ticker_map=None,
    instrument_types=None,  # NEW
):
```

In the shares → dollars path (line 185-187), track both notional and margin values:

```python
margin_exposure = {}  # Track margin-based values for NAV

for ticker, entry in raw_input.items():
    if "shares" in entry:
        price = price_fetcher(ticker)
        base_value = float(entry["shares"]) * price
        margin_exposure[ticker] = base_value
        # Futures: use notional for risk weighting
        if instrument_types and instrument_types.get(ticker) == "futures":
            from brokerage.futures import get_contract_spec
            spec = get_contract_spec(ticker.upper())
            if spec:
                dollar_exposure[ticker] = base_value * spec.multiplier
            else:
                dollar_exposure[ticker] = base_value
        else:
            dollar_exposure[ticker] = base_value
    elif "dollars" in entry:
        dollar_exposure[ticker] = float(entry["dollars"])
        margin_exposure[ticker] = dollar_exposure[ticker]
```

Normalization stays the same (line 228-229) — `weights = dollar_exposure / sum(dollar_exposure)` — but now futures get their proportional notional share.

Add `notional_leverage` to the return dict (after line 240):

```python
margin_total = sum(margin_exposure.values()) if margin_exposure else total_value
notional_leverage = total_value / margin_total if margin_total > 0 else 1.0
```

Return dict adds:
```python
"total_value": margin_total,      # NAV (margin-based) — unchanged semantics
"notional_leverage": notional_leverage,  # NEW: total_notional_exposure / NAV
```

**Callers to update** — pass `instrument_types` to `standardize_portfolio_input()`:
- `load_portfolio_config()` (~line 414 in `portfolio_risk_engine/portfolio_config.py`) — has `instrument_types` from config dict
- `config_from_portfolio_data()` (~line 61 in `portfolio_risk_engine/config_adapters.py`) — has `instrument_types` from PortfolioData
- `analyze_portfolio()` (~line 109 in `core/portfolio_analysis.py`) — has `instrument_types` from config dict

All three already have `instrument_types` in scope. Just need to pass it through.

**Also update `cfg.update()` / `config.update()` merge points** to include `notional_leverage`:
- `load_portfolio_config()` at ~line 419: add `notional_leverage=parsed.get("notional_leverage", 1.0)` to `cfg.update()`
- `config_from_portfolio_data()` at ~line 68: add `notional_leverage=parsed.get("notional_leverage", 1.0)` to `config.update()`

This ensures `notional_leverage` flows through the pre-parsed path and reaches `core/portfolio_analysis.py` without re-standardizing.

### 2. Asset-Class Proxy Factors

**2a. Auto-generate futures proxies** — `mcp_tools/risk.py`

**Where:** `_load_portfolio_for_analysis()` (~line 424), after `ensure_factor_proxies()` call.

Inject asset-class-appropriate factor proxies for futures tickers:

```python
if portfolio_data.instrument_types:
    from brokerage.futures import get_contract_spec
    _FUTURES_ASSET_CLASS_PROXIES = {
        "equity_index": {"market": "SPY"},
        "metals":       {"market": "SPY", "commodity": "GLD"},
        "energy":       {"market": "SPY", "commodity": "USO"},
        "fixed_income": {"market": "SPY"},  # interest_rate handled via asset_classes
    }
    for ticker, itype in portfolio_data.instrument_types.items():
        if itype != "futures":
            continue
        spec = get_contract_spec(ticker.upper())
        if not spec:
            continue
        proxy = _FUTURES_ASSET_CLASS_PROXIES.get(spec.asset_class, {"market": "SPY"})
        portfolio_data.stock_factor_proxies[ticker] = dict(proxy)
```

**2b. Set asset_classes for fixed_income futures** — `services/portfolio_service.py`

Fixed income futures need `asset_classes[ticker] = "bond"` to pass the interest rate factor eligibility gate in `compute_factor_exposures()`. The gate is at `portfolio_risk_engine/portfolio_risk.py:1022` — `RATE_FACTOR_CONFIG["eligible_asset_classes"]` is currently `["bond", "real_estate"]` (in `portfolio_risk_engine/config.py:49`).

**Where asset_classes is built:** `SecurityTypeService.get_full_classification()` is called in `PortfolioService.analyze_portfolio()` (~line 194 in `services/portfolio_service.py`), which returns the `asset_classes` dict. This dict then flows down into `build_portfolio_view()`. This is the cleanest injection point.

After `get_full_classification()` returns (~line 194-198), `asset_classes` is built as `{ticker: labels.get("asset_class")}`. Override fixed_income futures to `"bond"` immediately after (before line 199):

```python
# Map fixed_income futures to "bond" for interest_rate factor eligibility
if portfolio_data.instrument_types:
    from brokerage.futures import get_contract_spec
    for ticker, itype in portfolio_data.instrument_types.items():
        if itype != "futures":
            continue
        spec = get_contract_spec(ticker.upper())
        if spec and spec.asset_class == "fixed_income":
            asset_classes[ticker] = "bond"
```

Note: uses `portfolio_data.instrument_types` (not a local `instrument_types` variable — it's accessed from the `portfolio_data` object already in scope).

This maps fixed_income futures (ZB, ZN, ZF, etc.) to the canonical `"bond"` asset class, which is already in `VALID_ASSET_CLASSES` and in the interest rate eligible set. No need to extend `RATE_FACTOR_CONFIG` or add a new canonical class.

**2c. Add "commodity" factor path** — `portfolio_risk_engine/portfolio_risk.py`

**Where:** `compute_factor_exposures()`, after the existing factor blocks (market/momentum/value/industry/subindustry), before the interest_rate block (~line 990).

There are **two factor-construction paths** in `compute_factor_exposures()` that both need commodity handling:

**Path 1: Beta/residual computation** (~line 913-1004) — builds `fac_dict` per ticker, runs OLS, stores betas and idio variance.

**Path 2: Factor vol/weighted variance** (~line 1110-1228) — builds `fac_ret` per ticker, computes `sigmas` (annualized factor vols), populates `df_factor_vols`.

Add commodity factor in **both paths**, following the same pattern as market/momentum/value:

**Path 1** (after industry/subindustry block, ~line 983, before `factor_df = pd.DataFrame(fac_dict)`):

```python
            # --- commodity factor ---
            commodity_proxy = proxies.get("commodity")
            if commodity_proxy:
                try:
                    _pc = fetch_monthly_total_return_price(
                        commodity_proxy, start_date=start_date, end_date=end_date,
                        fmp_ticker_map=fmp_ticker_map,
                    )
                except Exception:
                    _pc = fetch_monthly_close(
                        commodity_proxy, start_date=start_date, end_date=end_date,
                        fmp_ticker_map=fmp_ticker_map,
                    )
                fac_dict["commodity"] = calc_monthly_returns(_pc).reindex(idx).dropna()
```

**Path 2** (after industry/subindustry block, ~line 1207, before `if not fac_ret:`):

```python
            # --- commodity factor ---
            commodity_proxy = proxies.get("commodity")
            if commodity_proxy:
                try:
                    _pc = fetch_monthly_total_return_price(
                        commodity_proxy, start_date=start_date, end_date=end_date,
                        fmp_ticker_map=fmp_ticker_map,
                    )
                except Exception:
                    _pc = fetch_monthly_close(
                        commodity_proxy, start_date=start_date, end_date=end_date,
                        fmp_ticker_map=fmp_ticker_map,
                    )
                fac_ret["commodity"] = calc_monthly_returns(_pc).reindex(idx_stock).dropna()
```

`compute_stock_factor_betas()` accepts arbitrary factor keys — it takes a `factor_returns` dict and regresses each independently. The downstream variance decomposition uses `df_stock_betas.columns` and `df_factor_vols.columns` dynamically, so "commodity" will flow through without hardcoded factor name updates.

### 3. Segment View — `mcp_tools/risk.py`

**Where:** `get_risk_analysis()` (~line 529)

Add `segment` parameter: `"all"` (default), `"equities"`, `"futures"`.

After `_load_portfolio_for_analysis()` returns `portfolio_data`, filter before analysis:

```python
if segment and segment != "all":
    instrument_types = portfolio_data.instrument_types or {}
    if segment == "futures":
        keep = {t for t, it in instrument_types.items() if it == "futures"}
    elif segment == "equities":
        futures_tickers = {t for t, it in instrument_types.items() if it == "futures"}
        keep = {t for t in portfolio_data.portfolio_input if t not in futures_tickers}
    else:
        keep = None

    if keep is not None:
        portfolio_data.portfolio_input = {
            t: v for t, v in portfolio_data.portfolio_input.items() if t in keep
        }
        if portfolio_data.stock_factor_proxies:
            portfolio_data.stock_factor_proxies = {
                t: v for t, v in portfolio_data.stock_factor_proxies.items() if t in keep
            }
        if portfolio_data.standardized_input:
            portfolio_data.standardized_input = {
                t: v for t, v in portfolio_data.standardized_input.items() if t in keep
            }
```

The rest of the pipeline runs unchanged on the filtered portfolio.

### 4. FX Attribution Wiring — `core/result_objects/risk.py`

**4a. Add field to `RiskAnalysisResult`** (after line 174):

```python
fx_attribution: Optional[Dict[str, Dict[str, Any]]] = None
```

**4b. Capture in `from_core_analysis()`** (~line 1535):

Currently `fx_attribution` exists in `portfolio_summary` (from `build_portfolio_view()`) but is silently dropped. Add:

```python
fx_attribution=portfolio_summary.get("fx_attribution"),
```

**4c. Surface in agent response** — `mcp_tools/risk.py`, `_build_agent_response()`

Summarize FX impact per currency for agent consumption:

```python
if result.fx_attribution:
    fx_summary = {}
    for ticker, fx_data in result.fx_attribution.items():
        currency = fx_data.get("currency", "???")
        fx_ret = fx_data.get("fx_returns")
        if fx_ret is not None and not fx_ret.empty:
            fx_summary[ticker] = {
                "currency": currency,
                "annualized_fx_impact_pct": round(float(fx_ret.mean() * 12 * 100), 2),
            }
    response["fx_attribution"] = fx_summary if fx_summary else None
```

### 5. Notional Leverage Plumbing

**5a. Thread through `core/portfolio_analysis.py`** (~line 109-148)

`notional_leverage` must flow from `standardize_portfolio_input()` return dict through to `summary`. Two changes:

1. Add to `standardized_keys` tuple (~line 109):
```python
standardized_keys = (
    "weights", "dollar_exposure", "total_value",
    "net_exposure", "gross_exposure", "leverage",
    "notional_leverage",  # NEW
)
```

2. It will then automatically be included in `standardized_data` (line 118) and flow into `summary.update()` (line 142-148) — add it there:
```python
summary.update({
    "net_exposure": standardized_data["net_exposure"],
    "gross_exposure": standardized_data["gross_exposure"],
    "leverage": standardized_data["leverage"],
    "total_value": standardized_data["total_value"],
    "dollar_exposure": standardized_data["dollar_exposure"],
    "notional_leverage": standardized_data.get("notional_leverage", 1.0),  # NEW
})
```

**5b. Add field to `RiskAnalysisResult`** — `core/result_objects/risk.py`

Add `notional_leverage: Optional[float] = None` field.

**5c. Capture in `from_core_analysis()`**:
```python
notional_leverage=portfolio_summary.get("notional_leverage"),
```

**5d. Include in `get_summary()` return dict.**

### 6. Risk Flags — `portfolio_risk_engine/risk_flags.py`

**Where:** After existing HHI concentrated flag (~line 107)

```python
notional_leverage = _sn(summary.get("notional_leverage"), 1.0)
if notional_leverage > 2.0:
    flags.append({
        "type": "high_notional_leverage",
        "severity": "warning",
        "message": f"Futures notional leverage at {notional_leverage:.1f}x NAV",
        "notional_leverage": round(notional_leverage, 2),
    })
elif notional_leverage > 1.3:
    flags.append({
        "type": "notional_leverage",
        "severity": "info",
        "message": f"Futures notional leverage at {notional_leverage:.1f}x NAV",
        "notional_leverage": round(notional_leverage, 2),
    })
```

## Files Changed

| File | Change | Section |
|------|--------|---------|
| `portfolio_risk_engine/portfolio_config.py` | Thread `instrument_types`, multiply futures by multiplier, track margin_exposure, return `notional_leverage`, add to `cfg.update()` | 1 |
| `portfolio_risk_engine/config_adapters.py` | Pass `instrument_types` to `standardize_portfolio_input()`, add `notional_leverage` to `config.update()` | 1 |
| `core/portfolio_analysis.py` | Pass `instrument_types` to `standardize_portfolio_input()`, add `notional_leverage` to `standardized_keys` and `summary.update()` | 1, 5a |
| `portfolio_risk_engine/portfolio_risk.py` | Add "commodity" factor in both beta path and factor-vol path of `compute_factor_exposures()` | 2c |
| `services/portfolio_service.py` | Override fixed_income futures → `"bond"` in asset_classes after classification | 2b |
| `mcp_tools/risk.py` | Futures proxy injection in `_load_portfolio_for_analysis()`, `segment` parameter in `get_risk_analysis()`, FX summary in agent response | 2a, 3, 4c |
| `core/result_objects/risk.py` | Add `fx_attribution`, `notional_leverage` fields; capture in `from_core_analysis()`; include in `get_summary()` | 4, 5 |
| `portfolio_risk_engine/risk_flags.py` | Add `notional_leverage` / `high_notional_leverage` flags | 6 |

## Tests

1. **Notional weights** — `standardize_portfolio_input()` with `instrument_types`:
   - ES 2 contracts at $6,875 with multiplier 50 → dollar_exposure = $687,500
   - AAPL 100 shares at $255 → dollar_exposure = $25,500
   - Weights proportional to notional, sum to 1.0
   - `total_value` stays margin-based (NAV)
   - `notional_leverage` = sum(notional) / sum(margin) > 1.0
   - Portfolio WITHOUT futures → `notional_leverage` = 1.0 (unchanged behavior)

2. **Futures proxy injection**:
   - ES (equity_index) → `{"market": "SPY"}`
   - GC (metals) → `{"market": "SPY", "commodity": "GLD"}`
   - CL (energy) → `{"market": "SPY", "commodity": "USO"}`
   - ZB (fixed_income) → `{"market": "SPY"}` + interest_rate eligible

3. **Commodity factor** — `compute_factor_exposures()`:
   - GC with `commodity: GLD` proxy → non-zero commodity beta
   - AAPL with no commodity proxy → no commodity beta column
   - Commodity factor reduces GC idiosyncratic variance vs baseline

4. **Segment filtering**:
   - `segment="equities"` → no futures tickers in weights
   - `segment="futures"` → only futures tickers in weights
   - `segment="all"` (default) → full portfolio with notional weights

5. **FX attribution** — `RiskAnalysisResult.fx_attribution` populated for non-USD positions

6. **Risk flags** — `notional_leverage > 1.3` → info, `> 2.0` → warning; no flag when = 1.0

7. **Existing tests** — all must pass. Equity-only portfolios get `notional_leverage = 1.0`.

## Design Decisions

1. **Weights normalize to 1.0** — Futures use notional in numerator. `normalize_weights()` divides by gross total as before. Leverage ratio captures absolute scaling separately.
2. **`total_value` stays as NAV** — Margin-based total for portfolio value display. Notional exposure surfaced via `notional_leverage`.
3. **Proxy ETFs, not macro factors** — GLD/USO plug into existing per-ticker regression. Fixed income futures use existing interest_rate factor via `"bond"` asset class mapping (no TLT proxy needed). Can swap for proper macro series later.
4. **Commodity as a new factor key** — Parallel to market/momentum/value. Per-ticker OLS, same math. Only appears for tickers with `"commodity"` in their proxy dict.
5. **Interest rate for fixed_income futures** — Map to canonical `"bond"` class at classification time in `PortfolioService.analyze_portfolio()`. `RATE_FACTOR_CONFIG["eligible_asset_classes"]` is `["bond", "real_estate"]` — no config change needed.
6. **Segment filtering at PortfolioData level** — Filter `portfolio_input` + `stock_factor_proxies` before `analyze_portfolio()`. Pipeline runs unchanged on filtered set.
7. **FX attribution pass-through** — Data exists in `build_portfolio_view()` output. Just needs a field on `RiskAnalysisResult` and one line in `from_core_analysis()`.
8. **Futures don't get equity factors** — No momentum/value/industry/subindustry proxies for futures. Only market + asset-class-specific proxy. This prevents equity idiosyncratic "noise" from contaminating futures decomposition.

## Resolved Questions (from Codex R1)

1. **`compute_stock_factor_betas()` genericity** — Verified: accepts arbitrary factor keys via `factor_returns` dict. No hardcoded factor names.
2. **`asset_classes` injection for fixed_income futures** — Resolved: override in `PortfolioService.analyze_portfolio()` after `get_full_classification()` returns. Maps `"fixed_income"` futures to canonical `"bond"` class.
3. **`RATE_FACTOR_CONFIG` eligible set** — Current value is `["bond", "real_estate"]`, not `{"bond"}` as originally stated. No extension needed — just map futures to `"bond"`.
4. **Commodity factor dual paths** — `compute_factor_exposures()` has two parallel paths (beta computation + factor vol computation). Commodity must be added to both.
5. **`notional_leverage` plumbing** — Must be threaded through `standardized_keys` tuple and `summary.update()` in `core/portfolio_analysis.py` (not just the result object).

## Open Questions

1. **Weight-only input path** — The `standardize_portfolio_input()` weight-only path (line 204-226) doesn't go through `price_fetcher`. If someone passes weights directly for futures, they'd need to pre-compute notional weights. This path is rarely used for live portfolios (positions come as shares).

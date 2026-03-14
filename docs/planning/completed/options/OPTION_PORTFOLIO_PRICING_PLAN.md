# Option-Aware Portfolio Analysis — Pricing Fix

**Date:** 2026-03-05
**Status:** Planning

## Context

The portfolio analysis path treats option positions like equities. Two pricing sites: (1) `latest_price()` for dollar exposure in `standardize_portfolio_input()`, and (2) `_fetch_ticker_returns()` for return series in `get_returns_dataframe()`. Both currently route options to FMP. FMP doesn't have option prices, so option tickers fail silently and get excluded from risk analysis.

The realized performance path already solved option pricing with a ProviderRegistry chain: IBKR marks (priority 20) → B-S fallback (priority 25). The portfolio analysis path just needs to route options through the same chain.

**Goal:** Route option tickers through the existing ProviderRegistry price chain so options are included in portfolio risk analysis with real prices.

---

## Changes

### Change 1: Add `contract_identities` to `PortfolioData` + auto-detect options in `to_portfolio_data()`

**File: `portfolio_risk_engine/data_objects.py`**

**1a.** Add field to `PortfolioData` (after `security_identifiers` at line 749):
```python
contract_identities: Optional[Dict[str, Dict[str, Any]]] = None
```

**1b.** Add `contract_identities` param to `from_holdings()` (line 981) and pass through in `cls(...)` call (line 998).

**1c.** In `to_portfolio_data()` (after futures auto-detect block, line 637), add option detection mirroring the futures pattern:
```python
contract_identities: Dict[str, Dict[str, Any]] = {}
try:
    from trading_analysis.symbol_utils import (
        parse_option_contract_identity_from_symbol,
        enrich_option_contract_identity,
    )
    for position in self.positions:
        ticker = str(position.get("ticker") or "").strip().upper()
        if not ticker or ticker in instrument_types:
            continue

        if position.get("is_option") and not position.get("option_parse_failed"):
            instrument_types[ticker] = "option"
            identity = {
                "underlying": position.get("underlying"),
                "strike": position.get("strike"),
                "expiry": str(position.get("expiry") or "").replace("-", ""),
                "right": "C" if position.get("option_type") == "call" else "P",
            }
            identity = enrich_option_contract_identity(identity, "option")
            contract_identities[ticker] = identity
            continue

        parsed = parse_option_contract_identity_from_symbol(ticker)
        if parsed:
            instrument_types[ticker] = "option"
            identity = enrich_option_contract_identity(parsed, "option")
            contract_identities[ticker] = identity
except Exception:
    logger.warning("Failed to auto-detect option instrument types", exc_info=True)
```

**1d.** Pass `contract_identities` to `PortfolioData.from_holdings()` at line 656.

**1e.** Add `contract_identities` to `_generate_cache_key()` (line 914, after `security_identifiers`):
```python
"contract_identities": self.contract_identities,
```

---

### Change 2: Thread `contract_identities` through config adapter

**File: `portfolio_risk_engine/config_adapters.py`**

**2a.** Add to config dict (line 39):
```python
"contract_identities": portfolio_data.contract_identities,
```

**2b.** Pass `contract_identity` to `latest_price()` in both price_fetcher lambdas (lines 49-60).

**2c.** Pass `contract_identities` to `standardize_portfolio_input()` (line 62).

---

### Change 3: Thread through `analyze_portfolio()` and `build_portfolio_view()`

**File: `core/portfolio_analysis.py`**

- Extract `contract_identities` from config (after line 95)
- Pass to price_fetcher lambdas, `standardize_portfolio_input()`, and `build_portfolio_view()`

**File: `portfolio_risk_engine/portfolio_risk.py`**

- Add `contract_identities` param to `build_portfolio_view()` (line 1559)
- Serialize into LRU cache key: add `contract_identities_json` to `_cached_build_portfolio_view()` signature (line 383) and thread through to `_build_portfolio_view_computation()` (line 425)
- Add `contract_identities` param to `_build_portfolio_view_computation()` (line 1614) and pass to `get_returns_dataframe()` (line 1629)
- Add `contract_identities` param to `get_returns_dataframe()` (line 709) and thread to `_fetch_ticker_returns()` (line 611)
- Add `contract_identities` param to `_filter_tickers_by_data_availability()` (line 537) and add option branch (line 569):
```python
elif instrument_type == "option" and OPTION_PRICING_PORTFOLIO_ENABLED:
    prices = _fetch_option_prices(
        ticker, start_date, end_date,
        contract_identity=(contract_identities or {}).get(
            str(ticker or "").strip().upper()
        ),
    )
```

**Callers NOT in scope (safe by default):**

All other callers of `build_portfolio_view()`, `get_returns_dataframe()`, `latest_price()`, and `standardize_portfolio_input()` will receive `contract_identities=None` (the default). This means options fall through to the equity path (FMP fails → excluded) — which is current behavior. These callers include:
- `portfolio_risk_engine/portfolio_optimizer.py` — multiple `build_portfolio_view()` calls
- `portfolio_risk_engine/scenario_analysis.py` — `analyze_scenario()`
- `portfolio_risk_engine/portfolio_risk_score.py` — risk score calculation
- `portfolio_risk_engine/backtest_engine.py` — `run_backtest()`
- `services/factor_intelligence_service.py` — factor analysis
- `mcp_tools/baskets.py`, `mcp_tools/factor_intelligence.py`
- `routes/realized_performance.py`
- `portfolio_risk_engine/portfolio_risk.py` — `calculate_portfolio_performance_metrics()`

Threading `contract_identities` into these callers is a future enhancement. The primary pipeline (`PositionService` → `PortfolioData` → `analyze_portfolio()` → `build_portfolio_view()`) is the only path that needs explicit threading, and that's what this plan covers.

---

### Change 4: Add option routing in `_fetch_ticker_returns()`

**File: `portfolio_risk_engine/portfolio_risk.py`**

Add option branch after the futures branch (line 623), gated by flag:
```python
elif instrument_type == "option" and OPTION_PRICING_PORTFOLIO_ENABLED:
    prices = _fetch_option_prices(
        ticker, start_date, end_date,
        contract_identity=(contract_identities or {}).get(
            str(ticker or "").strip().upper()
        ),
    )
```

New helper `_fetch_option_prices()`:
```python
def _fetch_option_prices(
    ticker: str,
    start_date: str,
    end_date: str,
    contract_identity: Optional[Dict[str, Any]] = None,
) -> pd.Series:
    """Fetch option prices through the ProviderRegistry chain."""
    from providers.bootstrap import get_registry

    registry = get_registry()
    chain = registry.get_price_chain("option")

    for provider in chain:
        # Skip IBKR without contract_identity (same guard as realized perf)
        if (
            provider.provider_name == "ibkr"
            and not (isinstance(contract_identity, dict) and contract_identity)
        ):
            continue
        try:
            series = provider.fetch_monthly_close(
                ticker, start_date, end_date,
                instrument_type="option",
                contract_identity=contract_identity,
            )
            if isinstance(series, pd.Series) and not series.dropna().empty:
                return series
        except Exception:
            continue

    raise ValueError(f"All pricing providers failed for option {ticker}")
```

This mirrors `_fetch_futures_prices()` and the realized perf chain pattern in `core/realized_performance/pricing.py`. The ValueError is caught by `get_returns_dataframe()` at line 817 (`except Exception`) and the option is excluded from the returns DataFrame with a warning.

---

### Change 5: Add option routing in `latest_price()`

**File: `portfolio_risk_engine/portfolio_config.py`**

- Add `contract_identity` param to `latest_price()` (line 283)
- Add option branch after futures check (line 317), gated by flag:
```python
if instrument_type == "option" and OPTION_PRICING_PORTFOLIO_ENABLED:
    return _latest_option_price(ticker, contract_identity=contract_identity)
```

New helper `_latest_option_price()`:
```python
def _latest_option_price(
    ticker: str,
    *,
    contract_identity: dict[str, Any] | None = None,
) -> float:
    """Fetch latest option price through ProviderRegistry chain."""
    from providers.bootstrap import get_registry

    registry = get_registry()
    chain = registry.get_price_chain("option")

    # Providers need concrete date windows — use trailing 24 months.
    end_date = pd.Timestamp.now().strftime("%Y-%m-%d")
    start_date = (pd.Timestamp.now() - pd.DateOffset(months=24)).strftime("%Y-%m-%d")

    for provider in chain:
        if (
            provider.provider_name == "ibkr"
            and not (isinstance(contract_identity, dict) and contract_identity)
        ):
            continue
        try:
            series = provider.fetch_monthly_close(
                ticker, start_date, end_date,
                instrument_type="option",
                contract_identity=contract_identity,
            )
            if isinstance(series, pd.Series) and not series.dropna().empty:
                return float(series.dropna().iloc[-1])
        except Exception:
            continue

    # All providers failed — return 0.0 so standardize_portfolio_input()
    # treats this as a zero-value position (excluded from weights).
    # Raising would abort the entire analysis for one unpriceable option.
    from portfolio_risk_engine._logging import portfolio_logger
    portfolio_logger.warning(f"Cannot price option {ticker}: all providers failed, excluding from analysis")
    return 0.0
```

**Note:** Unlike `_latest_futures_price()` which uses `FuturesPricingChain.fetch_latest_price()` (a separate API), option providers only expose `fetch_monthly_close()` which requires date bounds. Using a 24-month trailing window ensures we get the latest available price. Returns 0.0 (not raise) on failure so that `standardize_portfolio_input()` doesn't abort — the option gets zero weight and is excluded.

---

### Change 6: Option multiplier in `standardize_portfolio_input()`

**File: `portfolio_risk_engine/portfolio_config.py`**

- Add `contract_identities` param (line 138)
- In shares branch (line 206-213), after futures multiplier logic, gated by flag:
```python
elif instrument_type == "option" and OPTION_PRICING_PORTFOLIO_ENABLED:
    ci = (contract_identities or {}).get(normalized_ticker) or {}
    mult = float(ci.get("multiplier", 100))
    dollar_exposure[ticker] = base_value * mult
else:
    dollar_exposure[ticker] = base_value
```

---

### Change 7: Feature flag

**File: `settings.py`**

```python
OPTION_PRICING_PORTFOLIO_ENABLED = os.getenv("OPTION_PRICING_PORTFOLIO_ENABLED", "false").lower() == "true"
```

Gate option routing in `_fetch_ticker_returns()`, `latest_price()`, and `_filter_tickers_by_data_availability()` behind this flag. When off, options fall through to FMP (fails → excluded). No behavior change.

---

## Files Changed

| File | Change |
|------|--------|
| `portfolio_risk_engine/data_objects.py` | `contract_identities` field, option auto-detect in `to_portfolio_data()`, cache key update |
| `portfolio_risk_engine/config_adapters.py` | Thread `contract_identities` through config dict + price_fetcher + standardization |
| `core/portfolio_analysis.py` | Thread `contract_identities` through price_fetcher + standardization + `build_portfolio_view()` |
| `portfolio_risk_engine/portfolio_risk.py` | `_fetch_option_prices()`, option branch in `_fetch_ticker_returns()` + `_filter_tickers_by_data_availability()`, LRU cache key, thread `contract_identities` through `build_portfolio_view()` → `_cached_build_portfolio_view()` → `_build_portfolio_view_computation()` → `get_returns_dataframe()` → `_fetch_ticker_returns()` |
| `portfolio_risk_engine/portfolio_config.py` | `_latest_option_price()` + option routing in `latest_price()`, option multiplier in `standardize_portfolio_input()` |
| `settings.py` | `OPTION_PRICING_PORTFOLIO_ENABLED` flag |

6 files in scope. ~100 lines net new code.

---

## Key Design Decisions

1. **New flag** (`OPTION_PRICING_PORTFOLIO_ENABLED`) — different concern than `OPTION_MULTIPLIER_NAV_ENABLED` which controls realized perf.
2. **Reuse `get_registry()` singleton** — no new provider infrastructure needed. Chain has IBKR registered; B-S registered when `OPTION_BS_FALLBACK_ENABLED=true`.
3. **Provider-agnostic routing** — code iterates `registry.get_price_chain("option")` rather than hardcoding IBKR. New option providers slot in automatically via priority ordering.
4. **No multiplier on return series** — `get_returns_dataframe()` computes percentage returns (multiplier-agnostic). Multiplier only matters for dollar exposure.
5. **Graceful degradation** — unpriceable options excluded with warning, weights re-normalized (existing behavior for any failed ticker).
6. **Short-history exclusion** — options with < min_observations months excluded by `get_returns_dataframe()` (correct — insufficient data for covariance).

---

## Known Limitations

- Options with unparseable symbols (`option_parse_failed=True`) will have no `contract_identity` → both IBKR and B-S will skip them → excluded from analysis. Acceptable degradation.
- Short-dated options (< ~11 months history) will be excluded by `get_returns_dataframe()` min_observations check. Correct behavior — insufficient data for covariance estimation.
- SnapTrade does not expose options in holdings endpoint — those positions won't reach this path at all.
- B-S fallback requires `OPTION_BS_FALLBACK_ENABLED=true` (separate flag in `providers/bootstrap.py:39`). If neither IBKR marks nor B-S are available, options are excluded.
- `load_portfolio_config()` reads YAML files which won't have option positions — the new `contract_identities` param on `standardize_portfolio_input()` defaults to None, so YAML callers are unaffected.

---

## Verification

1. `python3 -m pytest tests/` — all existing tests pass (flag off = no behavior change)
2. With flag on: `analyze_portfolio()` with IBKR account — verify option tickers in returns DataFrame
3. Verify provider chain is used (not hardcoded IBKR calls)
4. Verify B-S fallback fires when IBKR marks unavailable
5. Verify equity/futures tickers unaffected
6. Verify option dollar exposure includes ×100 multiplier

---

## Reference Files

- `providers/bootstrap.py` — `get_registry()` singleton, chain: FMP(10) → IBKR(20) → B-S(25 when `OPTION_BS_FALLBACK_ENABLED`)
- `providers/registry.py` — `get_price_chain("option")` returns providers where `can_price("option")` is True
- `providers/ibkr_price.py` — `IBKRPriceProvider.fetch_monthly_close(instrument_type="option")`
- `providers/bs_option_price.py` — B-S fallback, needs contract_identity `{underlying, strike, expiry, right}`
- `core/realized_performance/pricing.py` — Pattern to replicate (chain iteration with IBKR skip guard)
- `services/position_enrichment.py` — `enrich_option_positions()` sets `is_option`, `underlying`, `strike`, `expiry`
- `trading_analysis/symbol_utils.py` — `parse_option_contract_identity_from_symbol()`, `enrich_option_contract_identity()`

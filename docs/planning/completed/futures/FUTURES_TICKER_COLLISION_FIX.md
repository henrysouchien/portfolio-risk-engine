# Centralized Price Service — Futures Ticker Collision Fix

## Context

Futures root symbols (MHI, HSI, ES) collide with equity tickers on FMP. "MHI" is both Hang Seng Mini Futures AND Pioneer Municipal High Income Fund. When code calls FMP `/profile` with "MHI" without checking `instrument_type`, it returns the wrong name/currency/price.

**Root cause**: 14+ call sites independently call `fetch_fmp_quote_with_currency()`, `fetch_profile()`, or FMP client methods without instrument_type routing. Three parallel pricing systems exist (legacy FMP direct, FuturesPricingChain, ProviderRegistry) with no single choke point.

**Approach**: Instead of guarding each call site individually, create two centralized utilities:
1. `get_spot_price()` — instrument-type-aware drop-in replacement for `fetch_fmp_quote_with_currency()`
2. `filter_fmp_eligible()` — filters ticker sets for enrichment/classification call sites

**Key constraint**: FMP CAN legitimately price MHI the fund. Guards are `instrument_type`-based, never ticker blocklists.

**Defense-in-depth strategy:**
1. **Primary**: `instrument_types`-based filtering via `filter_fmp_eligible()` at call sites that have portfolio context. This is precise — instrument_type comes from the brokerage source (IBKR Flex `assetCategory`), so MHI-the-fund and MHI-the-futures are correctly distinguished.
2. **Fallback**: Bottom-level functions (`ensure_factor_proxies`, `estimate_historical_returns`) add optional `instrument_types` param with a self-protecting fallback — when `instrument_types` is None, check `get_contract_spec(ticker)` from `brokerage/futures/contracts.yaml`. If a spec exists, skip FMP equity endpoints.
3. Callers that have `instrument_types` (most portfolio flows) pass it explicitly. Callers that don't (CLI tools, legacy paths) get fallback protection automatically.

This avoids the unbounded caller-threading problem — we don't need to change every intermediate function's API contract.

**Fallback tradeoff note**: The contract-spec fallback is NOT fully instrument-type-aware — it treats any ticker in `contracts.yaml` as futures, even if the user intended the colliding equity (e.g., MHI the fund). This only affects callers WITHOUT `instrument_types` (CLI/YAML paths). All production portfolio flows have `instrument_types` from brokerage sources and use the primary path. The alternative — leaving CLI/YAML paths completely unguarded — is worse.

**Pre-existing limitation**: Holdings collapse by `(ticker, currency)` in `position_service.py:544,589` and `data_objects.py:653,666` before `instrument_types` are derived. If a user holds BOTH equity "ES" and futures "ES", they'd merge before any guard runs. This is a data model issue (dedup key doesn't include instrument_type) — out of scope for this plan but noted for future work.

**Position type mapping** (from `ibkr_positions.py:_SEC_TYPE_MAP`):
- `FUT` -> `"derivative"` (futures)
- `OPT` -> `"option"` (equity options)
- `FOP` -> `"option"` (futures options)
- `STK` -> `"equity"`

So `type == "derivative"` correctly identifies futures only. Options are `type == "option"`.

---

## Wave 1: Core Utilities + Trading Analysis Fixes

### 1a. Create `providers/price_service.py` (NEW FILE)

Two functions:

```python
def get_spot_price(
    ticker: str,
    *,
    instrument_type: str | None = None,
    fmp_ticker: str | None = None,
    fmp_ticker_map: dict[str, str] | None = None,
    currency: str | None = None,
    contract_identity: dict[str, Any] | None = None,
) -> tuple[float | None, str | None]:
    """Central entry point for current price + currency.

    Drop-in replacement for fetch_fmp_quote_with_currency().
    Returns (local_price, currency) — callers do their own FX conversion.

    Routes by instrument_type:
    - "futures" -> FuturesPricingChain raw price + contract spec currency
    - "option"  -> (None, None) for now (feature-flagged, handled elsewhere)
    - "equity"/None -> fetch_fmp_quote_with_currency() (existing behavior)
    - "cash" -> (None, None)
    """
```

```python
def filter_fmp_eligible(
    tickers: Iterable[str],
    instrument_types: dict[str, str] | None = None,
) -> set[str]:
    """Return only tickers safe to send to FMP equity endpoints.

    Removes tickers where instrument_types[ticker] in {"futures", "option", "derivative"}.
    Handles both naming conventions: "futures" (from instrument_types dict) and
    "derivative" (from position type field). Both mean the same thing.
    With instrument_types=None, returns all tickers unchanged (backward compat).
    """
```

**Critical design note on `get_spot_price()` for futures:**
- Do NOT wrap `latest_price()` — it returns a single USD-normalized float, which double-converts when callers (like `_calculate_market_values()`) do their own FX.
- Mirror `_latest_futures_price()` logic (portfolio_config.py:424-459) exactly:
  1. `spec = get_contract_spec(ticker)` — gets contract spec from `brokerage/futures/contracts.yaml`
  2. Honor explicit overrides first: check `fmp_ticker` param, then `fmp_ticker_map.get(ticker)`, then fall back to `spec.fmp_symbol` — same priority as `_latest_futures_price()` lines 438-445
  3. `chain = get_default_pricing_chain()` from `brokerage/futures/pricing.py:74` — builds chain with FMP + IBKR sources
  4. `raw_price = chain.fetch_latest_price(ticker, alt_symbol=resolved_fmp)` — FMP source requires `alt_symbol` (returns None without it, per `sources/fmp.py:21`), IBKR source uses raw ticker
  5. Return `(raw_price, spec.currency)` — matches `fetch_fmp_quote_with_currency()` contract exactly.
- Callers continue doing their own FX conversion as they do for equities.
- If `get_contract_spec()` returns None AND no `fmp_ticker`/`fmp_ticker_map` override exists (unknown futures root): return `(None, None)`. Do NOT fall back to `fetch_fmp_quote_with_currency()` — that would reopen the collision. Unknown futures roots are better left unpriced than mispriced.

**Option pricing note:** `OPTION_PRICING_PORTFOLIO_ENABLED` defaults to `false` (`settings.py:144`). Option routing through the provider chain is feature-flagged. `get_spot_price()` returns `(None, None)` for options for now — this is a no-op, not a regression.

### 1b. Guard Name Resolution

**File**: `trading_analysis/analyzer.py`

Add `instrument_type` param to `_get_company_name()` (~line 397). For `"futures"`, use `get_contract_spec()` to build name instead of calling FMP. Update both call sites:
- FIFO path (~line 594): pass `closed.instrument_type`
- Averaged analysis path (~line 691): pass `instrument_type` from the trade context

### 1c. Fix FMPProvider

**File**: `providers/fmp_price.py`

Stop discarding `instrument_type` (`del instrument_type` on lines 65, 87). For `instrument_type == "futures"`, resolve to FMP commodity/index symbol via `_resolve_futures_fmp_symbol()` helper (checks fmp_ticker -> fmp_ticker_map -> contracts.yaml). If a valid FMP symbol resolves, pass it as `fmp_ticker=resolved` to the compat layer. If NO FMP symbol resolves (unknown futures root, no override), return empty Series/None rather than falling through to raw-ticker FMP lookup — the compat layer falls back to raw ticker via `fmp/compat.py:303` + `ticker_resolver.py:80`, which would reopen the collision.

### 1d. Add `by_instrument_type` Breakdown

**File**: `trading_analysis/metrics.py` — add `calculate_by_instrument_type()` function.
**File**: `trading_analysis/models.py` — wire into agent snapshot (near `futures_breakdown` ~line 830).

---

## Wave 2: Migrate Pricing Call Sites

Replace `fetch_fmp_quote_with_currency()` calls with `get_spot_price()` where instrument_type context is available.

### 2a. Position Service Valuation

**File**: `services/position_service.py`

`_calculate_market_values()` (line 774) reprices cached positions via `fetch_fmp_quote_with_currency()` at line 829. Cached positions lack price/value (DB schema only stores ticker/quantity/currency/type/cost_basis).

**Change**: Read `position_type = row.get("type")` (field is `type`, not `position_type`). For `type == "derivative"`, use `get_spot_price(ticker, instrument_type="futures")`. This correctly identifies futures only — options have `type == "option"` (per `_SEC_TYPE_MAP`). Note: some futures positions already have `fmp_ticker` set (line 806 check) — those are already safe. This change catches the ones without `fmp_ticker`.

### 2b. Tax Harvest Pricing

**File**: `mcp_tools/tax_harvest.py`

Two changes needed:

1. `_extract_equity_tickers()` (line 94): Currently only excludes `cash` type. Add `derivative` and `option` exclusions so futures/options don't enter the tax harvest ticker universe.

2. `_fetch_current_prices()` (line 214): Filter non-equity lots upstream before pricing. In `suggest_tax_loss_harvest()`, after FIFO matching:
```python
filtered = {}
for key, lots in long_open_lots.items():
    equity_lots = [l for l in lots if getattr(l, "instrument_type", "equity") not in ("futures", "option")]
    if equity_lots:
        filtered[key] = equity_lots
long_open_lots = filtered
```
Add early return if all lots were filtered. This prevents both futures AND option lots from reaching `_fetch_current_prices()` which calls FMP.

### 2c. Trading Helpers

**File**: `mcp_tools/trading_helpers.py`

Add optional `instrument_types: dict[str, str] | None = None` to `fetch_current_prices()`. Skip tickers where `instrument_types.get(ticker) in {"futures", "derivative"}`.

**Callers to thread `instrument_types`:**
- `mcp_tools/rebalance.py` (~line 210)
- `mcp_tools/basket_trading.py` (~line 311)
- `routes/hedging.py` (~line 273)

### 2d. Chain Analysis

**File**: `mcp_tools/chain_analysis.py`

`_resolve_underlying_price()` (line 118): Add `sec_type` check. For `FUT`, skip FMP and go straight to IBKR snapshot.

### 2e. Income Projection

**File**: `mcp_tools/income.py`

`_load_positions_for_income()` (line 30): Add `p.get("type") not in ("derivative", "option")` filter. Futures don't pay dividends; options are handled separately.

### 2f. Factor Recommendations

**File**: `mcp_tools/factor_intelligence.py`

`_load_portfolio_weights()` (line 729) and `build_ai_recommendations()` (line 258): Add `type not in ("derivative", "option")` filter.

Also guard the shared service layer: `services/factor_intelligence_service.py` lines 1113, 1120 classify/build proxies from raw weights. Add optional `instrument_types` param with contract-spec fallback (same pattern as 3d). Callers that have portfolio_data pass it; route/CLI callers without it get automatic protection.

---

## Wave 3: Guard Enrichment & Classification Sites

Use `filter_fmp_eligible()` at enrichment call sites that send ticker sets to FMP.

### 3a. Portfolio Service Enrichment

**File**: `services/portfolio_service.py`

Three methods need `instrument_types` parameter + `filter_fmp_eligible()`:

- `enrich_positions_with_sectors()` (line 1049): Use position `type` to exclude derivatives/options from `ticker_set`.
- `enrich_positions_with_market_data()` (line 1090): Same filter on `ticker_set`.
- `enrich_attribution_with_analyst_data()` (line 1209): Add `instrument_types` param. Thread from callers:
  - `app.py:1555` — pass `portfolio_data.instrument_types`
  - `routes/realized_performance.py:187` — pass `instrument_types` (already extracted at line 137)

### 3b. SecurityTypeService

**File**: `services/security_type_service.py`

In `get_security_types()` (line 212) and `get_asset_classes()` (line 791): Pre-classify futures tickers using `portfolio_data.instrument_types` BEFORE the DB cache lookup step (line 270), not just before the FMP fetch:
- Insert after cash classification (line 264) and BEFORE `non_cash_tickers` filtering (line 267):
  ```python
  # Pre-classify futures from instrument_types (prevents 90-day DB cache poisoning)
  if portfolio_data and hasattr(portfolio_data, 'instrument_types') and portfolio_data.instrument_types:
      for ticker in tickers:
          if ticker not in security_types and portfolio_data.instrument_types.get(ticker) == "futures":
              security_types[ticker] = "derivative"
  ```
- This ensures futures tickers never reach the DB cache lookup or FMP fetch at all.
- `get_asset_classes()`: Same pattern — map futures to asset class via contract spec (`equity_index -> equity`, `metals/energy -> commodity`, `fixed_income -> bond`)

**STS cache poisoning note**: STS uses a 90-day DB cache TTL (line 309). If a futures ticker gets FMP-classified once (e.g., "ES" as stock), it persists for 90 days. The fix MUST go before the DB cache check (line 270), not just before FMP fetch — otherwise a poisoned cached row still wins.

**run_risk.py:346 note**: This is the YAML config path — `load_portfolio_config()` returns a plain dict, not `PortfolioData`. The config dict may have an `instrument_types` key if the YAML specifies it. Construct a minimal `PortfolioData`-like object with just `instrument_types` from the config dict to pass to STS:
```python
from types import SimpleNamespace
instrument_types = config.get("instrument_types") or {}
fmp_ticker_map = config.get("fmp_ticker_map") or {}
if instrument_types or fmp_ticker_map:
    portfolio_data_stub = SimpleNamespace(instrument_types=instrument_types, fmp_ticker_map=fmp_ticker_map)
else:
    portfolio_data_stub = None
full_classification = SecurityTypeService.get_full_classification(tickers, portfolio_data=portfolio_data_stub)
```

### 3c. Sector Attribution

**File**: `portfolio_risk_engine/portfolio_risk.py`

`_compute_sector_attribution()` uses `fmp_ticker_map` to resolve symbols via `_resolve_profile_symbol()`. When `fmp_ticker_map` is absent (YAML config path, `portfolio_config.py:485`), falls back to raw ticker — which would send "ES" to FMP. Add `instrument_types` param to `_compute_sector_attribution()` and use `filter_fmp_eligible()` on the ticker set before FMP profile lookups.

**Callers to thread `instrument_types`:**
- `portfolio_risk.py` internal call (already has access via config)
- `routes/realized_performance.py:179` — `instrument_types` is already extracted at line 137, pass it through
- `portfolio_risk_engine/backtest_engine.py:176` — `run_backtest()` already has `instrument_types` at line 74, thread to `_compute_sector_attribution()` call

### 3d. Factor Proxy Service

**File**: `proxy_builder.py`

Three `fetch_profile()` call sites (lines 253, 529, 803) that receive portfolio tickers directly.

Self-protecting pattern: Add optional `instrument_types` param to `build_proxy_for_ticker()` and `get_subindustry_peers_from_ticker()`. Before each `fetch_profile()` call, check instrument_types then contract-spec fallback. For futures, return a sentinel proxy (e.g., `{"market": "SPY", "_futures_skip": True}`) rather than empty dict — empty dicts trigger regeneration loops in `factor_proxy_service.py`.

Thread `instrument_types` through `ensure_factor_proxies()` — add optional param. Callers that have `portfolio_data` (most runtime paths) pass it; callers that don't (CLI, YAML) get contract-spec fallback protection.

**Implementation caveats to resolve during coding:**
- `factor_proxy_service.py` caches per-portfolio proxy results (lines 88, 104). Guard must run BEFORE cache reads, or purge existing poisoned entries for futures tickers.
- `cache_gpt_peers` decorator on `get_subindustry_peers_from_ticker()` is fixed-arity — may need decorator update or cache key adjustment for instrument_types.
- `proxy_builder.py:793` reads cached global peers before fallback — same cache poisoning concern.

### 3e. Returns Calculator

**File**: `inputs/returns_calculator.py`

`estimate_historical_returns()` (line 86) calls `fetch_profile(fmp_symbol)` at line 103 for all portfolio tickers. Already receives `fmp_ticker_map`.

Self-protecting pattern: Add optional `instrument_types` param. When a futures ticker is detected (via instrument_types or contract-spec fallback), skip the entire ticker iteration — not just the `fetch_profile()` call but also the subsequent stock-path historical price fetching (lines 97-135). Return a default/empty entry for futures tickers so downstream code handles them gracefully.

### 3f. STS Position-Monitor Paths

**Files**: `routes/positions.py`, `mcp_tools/positions.py`

Position-monitor paths call `get_security_types()` with raw ticker lists, no `portfolio_data`:
- `routes/positions.py` lines 143, 330
- `mcp_tools/positions.py` line 289

These have `position_result` available which carries position types. Construct `portfolio_data` stub (or extract `instrument_types` from position metadata) and pass to STS to prevent cache poisoning.

### 3g. run_positions.py

**File**: `run_positions.py`

Line 100 calls `run_portfolio(portfolio_data)`. Verify that `PositionResult.data.to_portfolio_data()` (line 80) populates `instrument_types` — it should, since `to_portfolio_data()` in `data_objects.py:703-713` auto-maps from position types. If not set, ensure it's threaded through.

### 3h. Second `fetch_fmp_quote_with_currency` in `_ticker.py`

**File**: `portfolio_risk_engine/_ticker.py`

There's a standalone copy of `fetch_fmp_quote_with_currency()` at line 47. Add an `instrument_type` param — for futures, route to `get_spot_price()` or return `(None, None)` to skip FMP.

**File**: `portfolio_risk_engine/_fmp_provider.py`

The active caller is `FMPCurrencyResolver.infer_currency()` at line 112-115, which calls `_ticker.fetch_fmp_quote_with_currency(symbol)` without instrument_type. Add `instrument_type` param to `infer_currency()` and thread from callers (primarily `latest_price()` which already has `instrument_types` dict).

---

## Files Modified

| File | Change | Wave |
|------|--------|------|
| `providers/price_service.py` | NEW: `get_spot_price()`, `filter_fmp_eligible()` | 1a |
| `trading_analysis/analyzer.py` | `instrument_type` param on `_get_company_name()` | 1b |
| `providers/fmp_price.py` | Use `instrument_type` instead of discarding | 1c |
| `trading_analysis/metrics.py` | `calculate_by_instrument_type()` | 1d |
| `trading_analysis/models.py` | Wire `by_instrument_type` into snapshot | 1d |
| `services/position_service.py` | `get_spot_price()` for `type=="derivative"` in `_calculate_market_values()` | 2a |
| `mcp_tools/tax_harvest.py` | Filter derivatives from `_extract_equity_tickers()` + futures lots before pricing | 2b |
| `mcp_tools/trading_helpers.py` | `instrument_types` param on `fetch_current_prices()` | 2c |
| `mcp_tools/rebalance.py` | Thread `instrument_types` to `fetch_current_prices()` | 2c |
| `mcp_tools/basket_trading.py` | Thread `instrument_types` to `fetch_current_prices()` | 2c |
| `routes/hedging.py` | Thread `instrument_types` to `fetch_current_prices()` | 2c |
| `mcp_tools/chain_analysis.py` | Skip FMP for FUT in `_resolve_underlying_price()` | 2d |
| `mcp_tools/income.py` | Filter derivatives/options from `_load_positions_for_income()` | 2e |
| `mcp_tools/factor_intelligence.py` | Filter derivatives/options from weight computation | 2f |
| `services/factor_intelligence_service.py` | `instrument_types` param + contract-spec fallback on proxy/classify calls | 2f |
| `services/portfolio_service.py` | `filter_fmp_eligible()` on enrichment ticker sets | 3a |
| `app.py` | Thread `instrument_types` to analyst enrichment | 3a |
| `routes/realized_performance.py` | Thread `instrument_types` to analyst enrichment | 3a |
| `services/security_type_service.py` | Pre-classify futures before FMP lookup (prevents 90-day cache poisoning) | 3b |
| `run_risk.py` | Thread `instrument_types` to STS call | 3b |
| `portfolio_risk_engine/portfolio_risk.py` | `instrument_types` param + `filter_fmp_eligible()` on sector attribution | 3c |
| `routes/realized_performance.py` | Thread `instrument_types` to `_compute_sector_attribution()` | 3c |
| `portfolio_risk_engine/backtest_engine.py` | Thread `instrument_types` to `_compute_sector_attribution()` | 3c |
| `proxy_builder.py` | `instrument_types` param + contract-spec fallback on `fetch_profile()` calls | 3d |
| `inputs/returns_calculator.py` | `instrument_types` param + contract-spec fallback before `fetch_profile()` | 3e |
| `app.py` | Thread `instrument_types` to analyst enrichment | 3a |
| `routes/positions.py` | Thread `instrument_types`/`portfolio_data` to STS calls | 3f |
| `mcp_tools/positions.py` | Thread `instrument_types`/`portfolio_data` to STS call | 3f |
| `run_positions.py` | Verify `to_portfolio_data()` populates `instrument_types` | 3g |
| `portfolio_risk_engine/_ticker.py` | `instrument_type` param on standalone `fetch_fmp_quote_with_currency()` | 3h |
| `portfolio_risk_engine/_fmp_provider.py` | `instrument_type` param on `FMPCurrencyResolver.infer_currency()` | 3h |

## Known Limitations

- **B-S FOP underlying pricing** (`providers/bs_option_price.py`): `_fetch_underlying_series()` fetches futures root underlying via FMP for FOP. Non-trivial to fix: the underlying fetcher (`data_loader.py:146`) doesn't accept `instrument_type`, and `_fetch_underlying_series()` catches TypeError and retries without extra kwargs (line 66), silently dropping any new params. Requires refactoring the fetcher interface. Low collision frequency — FOP pricing is rare.
- **Baskets** (`mcp_tools/baskets.py`): `_fetch_profile()` and `_resolve_market_cap_weights()` call FMP directly. User-driven (user picks tickers explicitly). Could collide if user adds futures roots to baskets, but unlikely.
- **Stock service** (`services/stock_service.py`): `enrich_stock_data()` calls FMP profile/quote. User-driven — user calls `analyze_stock("ES")` explicitly. Not a collision risk.
- **New target tickers in rebalance/hedging/baskets**: When user supplies futures root as new target in rebalance, hedging, or basket buy, `instrument_types` from current positions won't cover it. Low-risk: user explicitly chose the ticker.

## Tests

New file: `tests/test_price_service.py`
1. `test_get_spot_price_futures_routes_to_chain` — MHI with instrument_type="futures" -> uses FuturesPricingChain, FMP profile NOT called
2. `test_get_spot_price_equity_uses_fmp` — MHI with instrument_type="equity" -> FMP profile called (fund price)
3. `test_get_spot_price_default_uses_fmp` — MHI with instrument_type=None -> FMP called (backward compat)
4. `test_get_spot_price_returns_local_price_and_currency` — NIY futures -> returns (raw_jpy_price, "JPY"), NOT USD-normalized
5. `test_filter_fmp_eligible_removes_futures` — filters futures from ticker set
6. `test_filter_fmp_eligible_none_returns_all` — with instrument_types=None, all tickers pass through

New file: `tests/trading_analysis/test_futures_ticker_collision.py`
7. `test_get_company_name_futures` — MHI futures -> "MHI Futures (Equity Index)"
8. `test_get_company_name_equity` — MHI equity -> FMP called normally
9. `test_fmp_provider_resolves_futures_symbol` — fetch_monthly_close("MHI", instrument_type="futures") -> "^HSI"
10. `test_fmp_provider_equity_unchanged` — instrument_type="equity" -> normal FMP
11. `test_by_instrument_type_breakdown` — mixed trades -> separate summaries
12. `test_position_service_derivatives_use_spot_price` — derivatives route through get_spot_price
13. `test_enrichment_skips_derivatives` — derivatives excluded from sector/market enrichment
14. `test_sts_preclassifies_futures` — futures get contract spec classification, skip FMP
15. `test_extract_equity_tickers_excludes_derivatives` — _extract_equity_tickers() filters derivatives and options
16. `test_proxy_builder_skips_futures` — proxy building skips futures tickers, doesn't call FMP profile
17. `test_returns_calculator_skips_futures` — estimate_historical_returns skips futures tickers
18. `test_sts_position_monitor_paths` — positions.py STS calls include instrument_types from position metadata

## Verification

1. `python3 -m pytest tests/test_price_service.py -v`
2. `python3 -m pytest tests/trading_analysis/test_futures_ticker_collision.py -v`
3. `python3 -m pytest tests/ibkr/ tests/trading_analysis/ tests/services/ -v` (regression)
4. Manual: `get_trading_analysis(source="ibkr_flex")` — verify MHI shows "MHI Futures (Equity Index)"
5. Manual: `get_positions()` — verify MHI futures position has correct price (not Pioneer fund price)

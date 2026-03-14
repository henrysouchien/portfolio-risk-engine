# System-Wide Option Pricing

**Date:** 2026-03-05
**Status:** Planning

## Context

Options are held across 4 providers (IBKR, Schwab, Plaid/Merrill, SnapTrade), but only IBKR can price them — and only active (non-expired) contracts via live Gateway API. Schwab and SnapTrade options are completely unpriceable because their normalizers emit `contract_identity: None`, which causes IBKR pricing to be skipped. There is no fallback when IBKR Gateway is unavailable.

**Goal:** Make option prices available system-wide by (1) fixing normalizer gaps so all providers' options can reach the IBKR pricing chain, and (2) adding a Black-Scholes theoretical fallback for when IBKR can't price (expired contracts, no Gateway connection).

**Out of scope:** Option multiplier threading through NAV/cash/FIFO (separate plan — per-provider quantity conventions differ), IBKR Flex mark price extraction (parallel session), option greeks in realized performance.

---

## Phase 1: Fix Normalizer `contract_identity` + Add Multiplier

**Goal:** Populate `contract_identity` for option rows in Schwab and SnapTrade (currently hardcoded `None`). Add `multiplier: 100` to all normalizers' option `contract_identity`.

**Behavioral impact:** Populating `contract_identity` will cause IBKR pricing to be *attempted* for Schwab/SnapTrade options (the `skipped_missing_contract_identity` guard in `pricing.py:117` currently blocks all pricing for these). This is the intended effect — options from these providers will now be priceable via IBKR Gateway when it's available. If IBKR Gateway is down or the option is expired, the FIFO terminal heuristic still applies as today.

**Multiplier note:** Hardcoding `multiplier: 100` covers standard US equity options. Mini options (10x multiplier) are rare and not currently held. If encountered, the IBKR Flex normalizer already reads the actual multiplier from Flex data and will not be overwritten by `enrich_option_contract_identity()` (no-op when multiplier already present).

### Existing parser (reuse)

`parse_option_contract_identity_from_symbol()` in `trading_analysis/symbol_utils.py` already handles:
- **OCC format** (`AAPL250117C00150000`) → `{underlying, expiry, strike, right}`
- **Canonical format** (`AAPL_C150_250117`) → same

### New shared helper in `trading_analysis/symbol_utils.py`

```python
_US_EQUITY_OPTION_MULTIPLIER = 100

def enrich_option_contract_identity(identity: dict | None, instrument_type: str) -> dict | None:
    """Add standard multiplier to option contract_identity if missing."""
    if instrument_type != "option" or not isinstance(identity, dict):
        return identity
    if "multiplier" not in identity:
        return {**identity, "multiplier": _US_EQUITY_OPTION_MULTIPLIER}
    return identity
```

Also update `parse_option_contract_identity_from_symbol()` to strip internal whitespace before matching (Schwab OCC symbols are space-padded):

```python
# In parse_option_contract_identity_from_symbol(), change:
normalized = str(symbol or "").strip().upper()
# To:
normalized = re.sub(r"\s+", "", str(symbol or "")).upper()
```

### Schwab (`providers/normalizers/schwab.py`)

3 sites where `"contract_identity": None` (lines 835, 938, 1045). Change all to:

```python
"contract_identity": enrich_option_contract_identity(
    parse_option_contract_identity_from_symbol(symbol),
    instrument_type,
),
```

Add imports: `parse_option_contract_identity_from_symbol`, `enrich_option_contract_identity` from `trading_analysis.symbol_utils`.

Schwab uses OCC-format symbols, but they may be space-padded (e.g., `"AAPL  250117C00150000"`). The parser regex requires contiguous format. **Must strip/compress whitespace before parsing** — add `.replace(" ", "")` or equivalent normalization before calling `parse_option_contract_identity_from_symbol()`. The existing `normalized = str(symbol or "").strip().upper()` in the parser only strips leading/trailing whitespace, not internal spaces.

### SnapTrade (`providers/normalizers/snaptrade.py`)

4 sites where `"contract_identity": None` (lines 234, 278, 320, 370). Same fix pattern.

SnapTrade's `_parse_option_symbol()` already produces canonical-format symbols (`AAPL_C150_250117`). The parser handles this. **Graceful degradation:** When `_parse_option_symbol()` can't parse strike/expiry from the description, it emits hash-stub placeholders (`X...`, right `O`). These will fail the symbol parser, returning `None` → `contract_identity` stays `None` → IBKR pricing skipped for those options (same as today). This is acceptable — we can't price what we can't identify.

### Plaid (`providers/normalizers/plaid.py`)

Already populates `contract_identity` via `_extract_option_contract_identity()` but without `multiplier`. Wrap the call site (line ~321-326) with `enrich_option_contract_identity()`.

### IBKR Flex (`providers/normalizers/ibkr_flex.py`)

Already carries `multiplier` from Flex data in `contract_identity`. No changes — the `enrich_option_contract_identity()` helper is a no-op when multiplier already present.

### Files changed

| File | Change |
|------|--------|
| `trading_analysis/symbol_utils.py` | +12 lines — `enrich_option_contract_identity()` helper |
| `providers/normalizers/schwab.py` | 3 sites + imports |
| `providers/normalizers/snaptrade.py` | 4 sites + imports |
| `providers/normalizers/plaid.py` | 1 call site wrap |

---

## Phase 2: Black-Scholes Fallback Price Provider

**Goal:** New `OptionBSPriceProvider` implementing `PriceSeriesProvider` protocol. Registered at priority 25 (after IBKR at 20) as last-resort option pricing. Feature-flagged via `OPTION_BS_FALLBACK_ENABLED` (default `false`).

### Existing B-S implementation (reuse)

`options/greeks.py` has a complete Black-Scholes implementation using pure `math`:
- `black_scholes_price(S, K, T, r, sigma, option_type, q=0.0) → float`
- Uses `math.erf` for `_norm_cdf` — no scipy needed

### New file: `providers/bs_option_price.py` (~100 lines)

```python
class OptionBSPriceProvider:
    provider_name = "bs_option"

    def can_price(self, instrument_type: str) -> bool:
        return instrument_type == "option"

    def fetch_monthly_close(self, symbol, start_date, end_date, *,
                             instrument_type="equity", contract_identity=None,
                             fmp_ticker_map=None) -> pd.Series:
        if instrument_type != "option" or not isinstance(contract_identity, dict):
            return pd.Series(dtype=float)

        underlying = contract_identity.get("underlying")
        strike = contract_identity.get("strike")
        right = contract_identity.get("right")
        expiry = contract_identity.get("expiry")
        if not all([underlying, strike, right, expiry]):
            return pd.Series(dtype=float)

        # 1. Fetch underlying monthly prices from FMP
        # 2. Get risk-free rate from treasury provider (fallback: 0.05)
        # 3. Compute rolling 12m realized vol from underlying returns (fallback: 0.30)
        # 4. For each month-end: T = max(days_to_expiry/365, 0)
        #    - T > 0: black_scholes_price(S, K, T, r, sigma, right)
        #    - T <= 0: intrinsic value (max(S-K, 0) for call, max(K-S, 0) for put)
        # 5. Return pd.Series indexed by month-end dates
```

Key implementation details:

- **Dependency injection (not globals)**: Follow `IBKRPriceProvider` pattern — accept callables via constructor. `__init__(self, underlying_fetcher=None, treasury_fetcher=None)`. Defaults to FMP/treasury provider fetchers if not injected. This keeps the provider testable and avoids bypassing test-injected registries in the realized performance path.
- **Underlying prices**: Via injected `underlying_fetcher(symbol, start, end)` (default: `FMPProvider().fetch_monthly_close`). If empty → return empty series.
- **Risk-free rate**: Via injected `treasury_fetcher(tenor, start, end)` (default: treasury provider's `fetch_monthly_treasury_rates`). Divide by 100 for decimal. Fallback: `0.05`.
- **Volatility**: `underlying_returns.rolling(12).std() * sqrt(12)`. Fallback: `0.30` when < 6 observations.
- **Right normalization**: `"C"/"CALL"` → `"call"`, `"P"/"PUT"` → `"put"`.
- **Exception handling**: Entire compute path wrapped in `try/except` → log warning, return empty series. Never raise from a price provider.

### Feature flag in `settings.py`

```python
OPTION_BS_FALLBACK_ENABLED = os.getenv("OPTION_BS_FALLBACK_ENABLED", "false").lower() == "true"
```

### Registration — TWO sites (important)

The system has two independent registries:

1. **`providers/bootstrap.py`** `build_default_registry()` — used by portfolio analysis. The FMP provider is already instantiated earlier in the function, so pass its fetcher:
```python
if OPTION_BS_FALLBACK_ENABLED:
    registry.register_price_provider(
        OptionBSPriceProvider(
            underlying_fetcher=fmp.fetch_monthly_close,
            treasury_fetcher=fmp.fetch_monthly_treasury_rates,
        ),
        priority=25,
    )
```

2. **`core/realized_performance/pricing.py`** `_build_default_price_registry()` — used by realized perf engine. Currently instantiates `FMPPriceProvider(fetcher=monthly_close_fetcher, daily_fetcher=_fetch_daily_close_for_registry)` inline at line 87-91. Extract to a local variable so the B-S provider can reuse it:
```python
# Extract existing inline instantiation (preserve both fetchers):
fmp_provider = FMPPriceProvider(
    fetcher=monthly_close_fetcher,
    daily_fetcher=_fetch_daily_close_for_registry,
)
registry.register_price_provider(fmp_provider, priority=10)
# ... existing IBKR registration unchanged ...
if OPTION_BS_FALLBACK_ENABLED:
    registry.register_price_provider(
        OptionBSPriceProvider(
            underlying_fetcher=fmp_provider.fetch_monthly_close,
            treasury_fetcher=fmp_provider.fetch_monthly_treasury_rates,
        ),
        priority=25,
    )
```

### Diagnostic integration

In `core/realized_performance/pricing.py` `_emit_pricing_diagnostics()`, add a diagnostic message when B-S is the success provider:

```python
if result.success_provider == "bs_option":
    warnings.append(
        f"Priced option {ticker} via Black-Scholes theoretical fallback "
        f"({len(result.series)} monthly bars). Prices are theoretical."
    )
```

### Files changed

| File | Change |
|------|--------|
| `providers/bs_option_price.py` | NEW ~100 lines |
| `providers/bootstrap.py` | +3 lines — conditional registration |
| `core/realized_performance/pricing.py` | +3 lines registration + diagnostic message |
| `settings.py` | +1 line — `OPTION_BS_FALLBACK_ENABLED` |

---

## Phase Sequencing

```
Phase 1 (normalizer contract_identity + multiplier)
    ↓ enables IBKR pricing for Schwab/SnapTrade options
Phase 2 (B-S fallback provider)
    ↓ uses contract_identity from Phase 1
```

Phase 1 is independently committable and immediately useful — Schwab/SnapTrade options that are still active will be priceable via IBKR Gateway. Phase 2 adds the theoretical fallback for expired or gateway-unreachable options.

---

## Feature Flag Behavior

| `OPTION_BS_FALLBACK_ENABLED` | IBKR Gateway | Behavior |
|---|---|---|
| `false` (default) | Available | IBKR prices active options only |
| `false` | Down | Options unpriceable (current behavior) |
| `true` | Available | IBKR first, B-S fallback for unpriceable |
| `true` | Down | B-S theoretical prices for all options with contract_identity |

---

## Scope Boundaries

- **Only** the pricing chain gets B-S — not portfolio analysis (`analyze_portfolio()` still routes options to FMP equity path and drops them for missing data)
- **No** multiplier threading (separate plan — IBKR reports contracts, Schwab reports shares)
- **No** IBKR Flex mark price extraction (parallel session)
- **No** option greeks in realized performance (future work)
- **No** FMP option endpoints (FMP doesn't offer option pricing)

---

## Reference Files

- `trading_analysis/symbol_utils.py` — `parse_option_contract_identity_from_symbol()` (reuse)
- `options/greeks.py` — `black_scholes_price()` (reuse)
- `providers/interfaces.py` — `PriceSeriesProvider` Protocol
- `providers/bootstrap.py` — `build_default_registry()`, `get_registry()` singleton
- `providers/ibkr_price.py` — `IBKRPriceProvider` (option dispatch pattern to follow)
- `providers/fmp_price.py` — `FMPProvider` (underlying price source for B-S)
- `core/realized_performance/pricing.py` — `_build_default_price_registry()`, `_fetch_price_from_chain()`, `_emit_pricing_diagnostics()`
- `core/realized_performance/engine.py` — Option routing (lines 785-818), FIFO terminal heuristic

---

## Verification

1. `python -m pytest tests/` — all existing tests pass (feature flag off)
2. After Phase 1: `refresh_transactions` for a Schwab account with options → verify `contract_identity` is populated in FIFO transactions
3. After Phase 2 with `OPTION_BS_FALLBACK_ENABLED=true`: Run realized performance for a portfolio with options → verify B-S pricing diagnostic appears in warnings
4. Spot-check: Compare B-S theoretical price for a known option against its last market price — should be within ~20% for near-ATM, short-dated options

---

## Follow-Up (Separate Plans)

- **Option multiplier NAV fix**: Thread 100x multiplier through `compute_monthly_nav()` and cash replay, accounting for IBKR (contracts) vs Schwab (shares) convention difference
- **IBKR Flex mark prices**: Store PriorPeriodPosition markPrice as historical option price cache (parallel session)
- **Option-aware portfolio analysis**: Route options in `build_portfolio_view()` to IBKR/B-S instead of FMP equity path

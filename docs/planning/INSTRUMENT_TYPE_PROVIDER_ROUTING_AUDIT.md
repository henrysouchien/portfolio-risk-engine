# Instrument Type × Provider Routing Audit

> **Date**: 2026-03-23
> **Status**: AUDIT + FIX PLAN — Codex R1 FAIL (4 issues), **R2 PASS**
> **TODO ref**: `docs/TODO.md` lines 87-104 ("Instrument Type × Provider Routing Audit")

---

## Executive Summary

The instrument type → provider routing architecture is **well-designed**. 10 instrument types, 3-provider price chain (FMP→IBKR→B-S), instrument-type-aware dispatch at every layer. No silent misrouting between providers.

**One critical bug**: `unknown` instrument types are coerced to `equity` in forward-looking analysis (risk, returns, pricing) but correctly excluded in realized performance. This split-brain behavior sends unresolvable tickers to FMP as equities, contaminating risk metrics.

**Other gaps**: Crypto pricing missing (no provider), 4 option feature flags all disabled (infrastructure built but gated off), bonds IBKR-only with no fallback.

**Overall grade: B** — Architecture sound, routing correct, but the `unknown` coercion is actively harmful and should be fixed.

---

## Routing Matrix

```
INSTRUMENT_TYPE | SPOT_PRICE      | RETURNS_SOURCE  | RISK_ANALYSIS | NOTES
────────────────┼─────────────────┼─────────────────┼───────────────┼──────────────────────
equity          | FMP quote       | FMP TR/Close    | ✅ Full        | Dividend-adjusted preferred
mutual_fund     | FMP quote       | FMP Close       | ✅ Full        | Treated as equity
futures         | IBKR+FMP chain  | IBKR/FMP        | ✅ Full        | FX-adjusted by currency
bond            | None            | IBKR only       | ✅ Full        | Requires contract_identity
option          | None (B-S theo) | IBKR/B-S        | ⚠️ Gated       | OPTION_PRICING_PORTFOLIO_ENABLED
crypto          | None            | ❌ MISSING       | ❌ EXCLUDED     | No pricing source
fx              | None            | FX rate delta   | ⚠️ Excluded    | Spot not priced; rate proxy
fx_artifact     | None            | ❌ FILTERED      | ❌ EXCLUDED     | Symbol pattern matched, dropped
income          | N/A             | N/A             | N/A           | Non-tradable; metadata only
unknown         | FMP (WRONG)     | FMP (WRONG)     | ❌ BUG         | Coerced to equity — see below
```

### Provider Priority Chain (`providers/bootstrap.py`)

| Priority | Provider | Instrument Types Handled |
|----------|----------|-------------------------|
| 10 | FMP (`providers/fmp_price.py`) | equity, etf, fund, futures (via fmp_symbol), mutual_fund |
| 20 | IBKR (`providers/ibkr_price.py`) | futures, fx, bond, option |
| 25 | Black-Scholes (`providers/bs_option_price.py`) | option only (gated: `OPTION_BS_FALLBACK_ENABLED`) |

### Feature Flags (all currently `false`)

| Flag | Controls | Impact when false |
|------|----------|-------------------|
| `OPTION_PRICING_PORTFOLIO_ENABLED` | Options in `get_returns_dataframe()` | Options excluded from risk analysis entirely |
| `OPTION_BS_FALLBACK_ENABLED` | B-S provider registration | Only IBKR available for option pricing |
| `OPTION_MULTIPLIER_NAV_ENABLED` | Non-IBKR option ×100 multiplier | NAV computation wrong for non-IBKR options |
| `EXERCISE_COST_BASIS_ENABLED` | Option exercise/assignment linkage | Exercise P&L not adjusted |

---

## Critical Bug: `unknown` Coerced to `equity`

### The split-brain

| Code Path | Treatment of `unknown` | Correct? |
|-----------|----------------------|----------|
| Realized performance (`core/realized_performance/engine.py:295`) | **Exclude** — `_EXCLUDED_INSTRUMENT_TYPES = {"fx", "fx_artifact", "unknown"}` | ✅ Yes |
| Position flags (`core/position_flags.py:136`) | **Warn** — emits `unknown_instrument_type` flag | ✅ Yes |
| Income projection | **Skip** — unknown positions excluded | ✅ Yes |
| Forward returns (`trading_analysis/analyzer.py:1134`) | **Coerce to equity** — `effective_type = "equity" if instrument_type == "unknown"` | ❌ Bug |
| `coerce_instrument_type()` (`trading_analysis/instrument_meta.py:67`) | **Default to equity** — `return default` where default="equity" | ⚠️ Risky |
| `filter_price_eligible()` (`providers/price_service.py:94`) | **Allow through** — unknown not in exclusion list | ❌ Bug |

### What happens

1. Normalizer assigns `instrument_type="unknown"` (e.g., Plaid returns `UNKNOWN_C2_230406`)
2. Forward analysis coerces to `"equity"` and calls FMP
3. FMP either returns empty data (ticker doesn't exist) or wrong data (coincidental match)
4. Bad returns contaminate covariance matrix → distorted VaR, factor exposures, risk contributions
5. Meanwhile, realized performance correctly excludes the same ticker — inconsistent behavior

### What tickers get `unknown`

- Plaid/SnapTrade `UNKNOWN_*` prefix tickers (unresolvable by broker)
- Tickers where FMP profile lookup fails and normalizer couldn't classify
- Legacy/synthetic symbols that escape `_is_pseudo_symbol()` filtering

---

## Fix Plan

### Step 1: Align forward analysis with realized performance — exclude `unknown`

**File: `portfolio_risk_engine/portfolio_risk.py`** — `_fetch_ticker_returns()`

Add `unknown` to the exclusion check after `_resolve_instrument_type()`, matching the `CUR:` early-return pattern. **Important**: this function returns a `dict`, not a Series — must match the existing contract at line 697-698.

```python
# After _resolve_instrument_type() (around line 700):
if instrument_type == "unknown":
    logger.info("Skipping %s: unknown instrument_type", ticker)
    return {"ticker": ticker, "returns": None, "fx_attribution": None}
```

This is needed because the total-return branch calls `fetch_monthly_total_return_price()` which goes straight to FMP's dividend provider, bypassing the price chain's `can_price()` check.

### Step 2: Fix `filter_price_eligible()` — exclude `unknown`

**File: `providers/price_service.py`** — `filter_price_eligible()`

Add `"unknown"` to the exclusion set:

```python
# Before:
if instrument_type in {"futures", "option", "derivative", "bond"}:
    continue

# After:
if instrument_type in {"futures", "option", "derivative", "bond", "unknown"}:
    continue
```

### Step 3: Fix `coerce_instrument_type()` default — `"unknown"` not `"equity"`

**File: `trading_analysis/instrument_meta.py`** — `coerce_instrument_type()`

Change the default from `"equity"` to `"unknown"` so unrecognized types don't silently become equities:

```python
# Before:
def coerce_instrument_type(value: Any, default: InstrumentType = "equity") -> InstrumentType:

# After:
def coerce_instrument_type(value: Any, default: InstrumentType = "unknown") -> InstrumentType:
```

**Impact**: Any caller that previously relied on the `"equity"` default will now get `"unknown"`, which will be excluded from analysis instead of contaminating it. Need to audit all callers to confirm none break.

### Step 4: Remove the `analyzer.py` coercion at line 1134

**File: `trading_analysis/analyzer.py:1134`**

Remove the explicit coercion. Returning empty Series is safe — `_fetch_group_closes()` returns a series, and `analyze_timing()`/`analyze_post_exit()` skip empty closes.

```python
# Before:
effective_type = "equity" if instrument_type == "unknown" else instrument_type
chain = registry.get_price_chain(effective_type)

# After:
if instrument_type == "unknown":
    return pd.Series(dtype=float)
chain = registry.get_price_chain(instrument_type)
```

### Step 5: Fix `_edge_instrument_class()` at analyzer.py:113

**File: `trading_analysis/analyzer.py:113-118`**

This function also maps `unknown` → `equity` for edge grading. Should return `None` (skip grading) instead:

```python
# Before:
if normalized in {"equity", "mutual_fund", "bond", "unknown"}:
    return "equity"

# After:
if normalized in {"equity", "mutual_fund", "bond"}:
    return "equity"
# unknown falls through to return None (no edge grading)
```

### Step 6: Note on `ibkr/_types.py` vendored copy

`ibkr/_types.py:32` has a vendored copy of `coerce_instrument_type()` with `default="equity"`. All its callers already pass `default="unknown"` explicitly, so no change needed. Document for awareness.

### Step 7: Tests

**New tests** (~10):

Core exclusion tests:
1. `_fetch_ticker_returns()` returns `{"ticker": ..., "returns": None, "fx_attribution": None}` for `instrument_type="unknown"` (dict shape preserved)
2. `filter_price_eligible()` excludes `unknown` type tickers
3. `coerce_instrument_type()` defaults to `"unknown"` for unrecognized values
4. `coerce_instrument_type()` still returns `"equity"` for valid equity strings
5. `coerce_instrument_type("garbage", default="equity")` still returns `"equity"` (explicit default preserved)

End-to-end tests:
6. `get_returns_dataframe()` excludes unknown tickers from covariance matrix — returns only known-type tickers
7. `get_returns_dataframe()` when ALL tickers are unknown — verify current `ValueError` behavior preserved (empty returns → no valid data)
8. Analyzer `_fetch_group_closes()` returns empty Series for unknown instrument — `analyze_timing()` and `analyze_post_exit()` skip gracefully
9. `_edge_instrument_class("unknown")` returns `None` (no edge grading)

Regression tests:
10. Equity tickers with no explicit instrument_type still work (normalizer/SecurityTypeService should set type, not rely on `coerce_instrument_type` default)

**Existing test audit**: Search for callers of `coerce_instrument_type()` that pass no `default=` arg — these currently get `"equity"` and will now get `"unknown"`. Codex confirmed callers that need equity fallback already pass `default="equity"` explicitly.

---

## Other Gaps (documented, not planned for fix)

### Crypto pricing — no provider

No pricing source handles crypto. Falls through FMP chain silently (returns empty). Would need a dedicated provider (CoinGecko, CryptoCompare) or FMP crypto endpoint if available.

**Impact**: Low — only affects portfolios with crypto positions. Current workaround: crypto positions excluded from risk analysis due to empty returns.

### Bond pricing — IBKR-only, no fallback

Bonds require `contract_identity` and only IBKR can price them. If IBKR is unavailable or contract_identity missing, bond positions silently get empty returns.

**Impact**: Medium — affects bond-heavy portfolios. No fix planned — would need a bond pricing provider (Bloomberg, ICE) which is out of scope.

### Option feature flags — all disabled

Infrastructure is fully built but all 4 flags are `false`. Enabling them is a configuration decision, not a code fix.

**Impact**: Options are excluded from all risk analysis. When ready to enable, flip flags and test.

---

## Files Modified (fix plan)

| File | Change |
|------|--------|
| `portfolio_risk_engine/portfolio_risk.py` | Exclude `unknown` from `_fetch_ticker_returns()` (dict return shape) |
| `providers/price_service.py` | Add `"unknown"` to `filter_price_eligible()` exclusion set |
| `trading_analysis/instrument_meta.py` | Change `coerce_instrument_type()` default from `"equity"` to `"unknown"` |
| `trading_analysis/analyzer.py:1134` | Remove `unknown` → `equity` coercion in `_fetch_group_closes()` |
| `trading_analysis/analyzer.py:113` | Remove `unknown` from equity mapping in `_edge_instrument_class()` |
| `tests/` | ~10 new tests |

Note: `ibkr/_types.py:32` has a vendored `coerce_instrument_type()` copy — no change needed (callers already pass `default="unknown"`).

## Codex Review Round 1 — Issues Addressed

| # | Issue | Fix |
|---|-------|-----|
| 1 | `_fetch_ticker_returns()` returns dict, not Series — plan had wrong return type | Fixed: returns `{"ticker": ..., "returns": None, "fx_attribution": None}` matching `CUR:` pattern |
| 2 | Missed coercion site: `_edge_instrument_class()` at analyzer.py:113 | Added Step 5: remove `unknown` from equity mapping |
| 3 | `ibkr/_types.py` vendored copy of `coerce_instrument_type()` | Documented in Step 6: no change needed, callers pass `default="unknown"` |
| 4 | Test plan missing dict return shape, all-unknown ValueError, analyzer timing/post-exit | Added tests 1, 7, 8, 9 |

## Verification

1. `python3 -m pytest tests/ -x -q` — no regressions
2. Spot-check: run `get_positions()` and verify unknown-type positions get `unknown_instrument_type` warning flag
3. Spot-check: run `get_risk_analysis()` and verify unknown-type positions excluded from covariance matrix (same as realized performance)

## Audit Checklist (from TODO)

- [x] Map the full matrix: instrument type × pricing provider × normalizer × analysis path × risk treatment
- [x] Are there instrument types that silently fall through to wrong providers? — **YES: `unknown` → equity**
- [x] Options: IBKR → B-S fallback chain? — Yes, works when flags enabled. Currently all gated off.
- [x] Futures: all 27 contracts routing correctly? — Yes, via `get_contract_spec()` + FMP symbol mapping
- [x] Bonds: CUSIP resolution reliable? — IBKR-only, requires contract_identity. No fallback.
- [x] Crypto: which provider? — None. No provider handles crypto.
- [x] Cash/money market: properly excluded? — Yes, `CUR:*` filtered out.
- [x] SecurityTypeService vs InstrumentType agreement? — Mostly aligned; STS has richer taxonomy but maps cleanly.
- [x] Feature flags audit — 4 option flags, all disabled. Infrastructure ready.

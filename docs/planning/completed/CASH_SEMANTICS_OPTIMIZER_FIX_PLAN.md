# Cash Semantics Optimizer Fix — Implementation Plan

## Status: IMPLEMENTATION READY

## Context

GBP cash (`CUR:GBP`) gets rewritten to `ERNS.L` (a bond ETF) by `to_portfolio_data()` at `data_objects.py:547-553`. The optimizer then uses ERNS.L's real bond-fund history (~8-10% annual vol) in the covariance matrix, distorting `min_variance`/`max_sharpe` output. Cash should have near-zero risk (only FX for non-USD).

The proxy rewrite was introduced as a pragmatic workaround (see `completed/CASH_PROXY_MAPPING_PLAN.md`) because raw `CUR:*` tickers couldn't be priced and were being dropped entirely — understating leverage. Now that ticker validation allows colons (`validation_service.py:91`) and we can generate synthetic returns, we can fix this properly.

**Factor analysis is unaffected** — cash proxies (SGOV/ERNS.L/IBGE.L) are NOT in `stock_factor_proxies` and already get skipped by `compute_factor_exposures()` at `portfolio_risk.py:1537-1545`.

## Relationship to Prior Work

This plan supersedes the core assumption in:

- `docs/planning/completed/CASH_PROXY_MAPPING_PLAN.md`
- `docs/planning/completed/realized-perf/CASH_PROXY_MAPPING_PLAN.md`

Those plans solved an earlier problem: raw `CUR:*` cash could not pass through the risk stack because it had no price series. Converting cash to proxy ETFs fixed validation and leverage dilution, but it also imported ETF duration / credit / market behavior into the optimizer.

That tradeoff is no longer acceptable for the core solver path.

## Implementation

### Step 1: Shared cash-ticker predicate

**File:** `portfolio_risk_engine/portfolio_config.py`

Add a `is_cash_ticker()` function alongside the existing `get_cash_positions()` (line 42):

```python
def is_cash_ticker(ticker: str) -> bool:
    """Return True if ticker represents a cash or cash-equivalent position.

    Recognizes both CUR:* prefixed tickers and YAML-configured proxy/alias tickers.
    """
    if isinstance(ticker, str) and ticker.startswith("CUR:"):
        return True
    return ticker in cash_positions  # existing _LazyCashPositions (line 95)
```

This covers:
- `CUR:GBP`, `CUR:USD`, `CUR:EUR` — by prefix (works for any currency, no YAML needed)
- `SGOV`, `ERNS.L`, `IBGE.L` — by set membership (existing proxy ETFs)
- `CASH`, `USD CASH` etc. — by set membership (existing aliases)

### Step 2: Preserve `CUR:*` in `to_portfolio_data()`

**File:** `portfolio_risk_engine/data_objects.py`

**Change at lines 533-568** — stop rewriting `CUR:*` to proxy ETFs:

```python
# BEFORE (line 547-553):
proxy_ticker = proxy_by_currency.get(cash_ccy)
if proxy_ticker:
    existing = holdings_dict.get(proxy_ticker)
    if existing and "shares" in existing:
        pass
    else:
        ticker = proxy_ticker  # CUR:GBP -> ERNS.L

# AFTER:
# Keep CUR:* as-is for core analysis. No proxy rewrite.
# The ticker stays as CUR:GBP, enters holdings_dict with "dollars".
```

Remove the proxy rewrite block entirely. The `is_cash` detection (lines 533-537) stays — it still correctly identifies cash positions. The currency resolution logic (lines 539-545) stays — it's used for metadata. Only the `proxy_ticker` substitution (lines 547-553) is removed.

**Change at lines 622-634** — update the unmapped cash filter:

```python
# BEFORE: filters any type=="cash" not in proxy_tickers (proxy ETFs only)
# AFTER: keep CUR:* tickers (they're valid cash holdings with synthetic returns).
#        Filter only non-CUR:* cash formats that aren't recognized by is_cash_ticker()
#        (e.g., random broker strings like "BASE_CURRENCY").
```

Use `is_cash_ticker()` from Step 1 to decide what stays vs what gets filtered:

```python
from portfolio_risk_engine.portfolio_config import is_cash_ticker
unmapped_cash = [
    t for t, entry in holdings_dict.items()
    if entry.get("type") == "cash" and not is_cash_ticker(t)
]
```

**Important**: Do NOT add `CUR:GBP` to `currency_map` (line 642-647). The dollar value from `PositionService` is already USD-converted. Adding to `currency_map` would trigger double FX conversion in `standardize_portfolio_input`.

### Step 3: Synthetic cash returns in `_fetch_ticker_returns()`

**File:** `portfolio_risk_engine/portfolio_risk.py`

**Replace lines 760-761** (the current early-return-None):

```python
# BEFORE:
if isinstance(ticker, str) and ticker.startswith("CUR:"):
    return {"ticker": ticker, "returns": None, "fx_attribution": None}

# AFTER:
if isinstance(ticker, str) and ticker.startswith("CUR:"):
    # Synthetic cash: near-zero local returns, FX-adjusted for non-USD
    idx = pd.date_range(start_date, end_date, freq="ME")
    currency = ticker.split(":", 1)[1].upper()  # "GBP" from "CUR:GBP"
    if currency == "USD":
        # Tiny random noise to avoid singular covariance matrix.
        # A constant series has zero sample variance even if nonzero.
        rng = np.random.default_rng(seed=42)  # deterministic for reproducibility
        local_returns = pd.Series(rng.normal(0, 1e-6, len(idx)), index=idx, name=ticker)
    else:
        local_returns = pd.Series(0.0, index=idx, name=ticker)

    fx_attribution = None
    if currency != "USD":
        try:
            from portfolio_risk_engine.providers import get_fx_provider
            fx_provider = get_fx_provider()
            if include_fx_attribution:
                fx_result = fx_provider.adjust_returns_for_fx(
                    local_returns, currency,
                    start_date=start_date, end_date=end_date,
                    decompose=True,
                )
                local_returns = fx_result["usd_returns"]
                fx_attribution = {
                    "currency": currency,
                    "local_returns": fx_result["local_returns"],
                    "fx_returns": fx_result["fx_returns"],
                }
            else:
                local_returns = fx_provider.adjust_returns_for_fx(
                    local_returns, currency,
                    start_date=start_date, end_date=end_date,
                )
        except Exception:
            # FX data unavailable — apply same noise floor as USD cash
            # to avoid silently creating a zero-variance (riskless) asset.
            import hashlib
            stable_seed = int(hashlib.md5(ticker.encode()).hexdigest()[:8], 16)
            rng = np.random.default_rng(seed=stable_seed)
            local_returns = pd.Series(rng.normal(0, 1e-6, len(idx)), index=idx, name=ticker)

    return {"ticker": ticker, "returns": local_returns, "fx_attribution": fx_attribution}
```

**Variance floor for USD cash:** A constant series (e.g., `1e-8` every month) still has exactly zero sample variance after demeaning. Instead, use `np.random.normal(0, 1e-6, len(idx))` to inject imperceptible noise that produces a tiny but nonzero variance (~1e-12 annual). This makes the covariance matrix positive definite without meaningfully affecting risk calculations. Non-USD cash gets real FX variance so no floor is needed.

```python
    if currency == "USD":
        # Tiny random noise to avoid singular covariance matrix.
        # A constant series has zero sample variance even if nonzero.
        rng = np.random.default_rng(seed=42)  # deterministic for reproducibility
        local_returns = pd.Series(rng.normal(0, 1e-6, len(idx)), index=idx, name=ticker)
    else:
        local_returns = pd.Series(0.0, index=idx, name=ticker)
```

**What this produces:**
- `CUR:USD` → near-zero series (effectively zero variance, prevents singular covariance matrix)
- `CUR:GBP` → pure GBP/USD FX returns (~8-10% annual vol from FX moves)
- `CUR:EUR` → pure EUR/USD FX returns

The FX adjustment uses existing `fmp/fx.py:270-310` — `adjust_returns_for_fx()` does `(1 + local) * (1 + fx) - 1`, so with zero local returns you get pure FX returns. No new data providers needed.

**FX double-counting prevention:** The synthetic series starts as zero local-currency returns, then `adjust_returns_for_fx()` converts to USD. The plan explicitly does NOT add `CUR:GBP` to `currency_map` (Step 2), so there is no second FX pass in `standardize_portfolio_input`. The FX layer runs exactly once.

**No circular import risk:** `portfolio_config.py` does NOT import from `data_objects.py`. The import direction is `data_objects → portfolio_config` (one-way), so importing `is_cash_ticker` in Step 5 is safe.

**`standardize_portfolio_input` must also use `is_cash_ticker()`:** The risky exposure calc in `standardize_portfolio_input()` at `portfolio_config.py:210-212` uses `_get_cash_positions_cached()`. This set does NOT include `CUR:GBP` — only `CUR:USD` and `CUR:EUR` are in `alias_to_currency` in `cash_map.yaml`. So `CUR:GBP` would be incorrectly counted as risky exposure. The fix: replace `t not in cash_positions` with `not is_cash_ticker(t)` in the risky weight comprehension at line 210-212, matching the change in Step 5.

### Step 4: Expected returns for `CUR:*`

**File:** `services/returns_service.py`

**Extend `_is_cash_proxy()` at lines 514-532** to also recognize `CUR:*`:

```python
def _is_cash_proxy(self, ticker: str) -> bool:
    if isinstance(ticker, str) and ticker.startswith("CUR:"):
        return True
    # ... existing YAML/fallback logic unchanged
```

**Currency-aware expected returns:** The existing flow assigns Treasury rate to all cash proxies. For `CUR:*`, differentiate by currency:

- `CUR:USD` → USD Treasury rate (correct — USD cash earns the risk-free rate)
- `CUR:GBP`, `CUR:EUR`, etc. → **zero expected return** (we don't have SONIA/ESTR rates; zero is consistent with the "zero local carry" model in Step 3)

This prevents `max_sharpe` from over-allocating to foreign cash by falsely attributing USD Treasury returns to it. Implementation: in the expected-return assignment block (around line 409-423), check if the ticker is `CUR:*` with a non-USD currency and assign `0.0` instead of the Treasury rate.

```python
elif self._is_cash_proxy(ticker):
    if isinstance(ticker, str) and ticker.startswith("CUR:") and ticker.split(":", 1)[1].upper() != "USD":
        # Non-USD cash: zero expected return (no local carry data available)
        complete_returns[ticker] = 0.0
    else:
        # USD cash or proxy ETF: use Treasury rate
        treasury_rate = self._get_current_treasury_rate()
        complete_returns[ticker] = treasury_rate
```

### Step 5: Risky exposure — use shared predicate

**File:** `portfolio_risk_engine/data_objects.py`

**Change at lines 740-760** — replace `get_cash_proxy_tickers()` with `is_cash_ticker()`:

```python
# BEFORE (line 744-748):
cash_proxy_tickers = get_cash_proxy_tickers()
risky_weights = {
    ticker: weight
    for ticker, weight in weights.items()
    if ticker.upper() not in cash_proxy_tickers or weight < 0
}

# AFTER:
from portfolio_risk_engine.portfolio_config import is_cash_ticker
risky_weights = {
    ticker: weight
    for ticker, weight in weights.items()
    if not is_cash_ticker(ticker) or weight < 0
}
```

This ensures `CUR:GBP` (positive) is excluded from risky exposure, while negative `CUR:USD` (margin debt) is retained — same behavior as before, just recognizing `CUR:*` by prefix.

### Step 5b: Update `standardize_portfolio_input()` risky exposure

**File:** `portfolio_risk_engine/portfolio_config.py`

**Change at lines 210-212** — replace `cash_positions` membership with `is_cash_ticker()`:

```python
# BEFORE:
risky_weights = {
    t: w for t, w in weights.items()
    if t not in cash_positions or w < 0
}

# AFTER:
risky_weights = {
    t: w for t, w in weights.items()
    if not is_cash_ticker(t) or w < 0
}
```

This is the same change as Step 5 but in the second exposure calculation path. Required because `cash_map.yaml` `alias_to_currency` does not include `CUR:GBP`, so the set-based check misses it.

### Step 5c: Exclude `CUR:*` from missing-return auto-generation

**File:** `services/returns_service.py`

The `ensure_returns_coverage()` flow marks tickers as "missing" and auto-generates equity-style expected returns for them. Since `get_complete_returns()` checks `temp_returns` before the cash branch, auto-generated returns would override the cash-specific handling from Step 4.

Fix: in `validate_returns_coverage()` / `_validate_complete_coverage()`, exclude `CUR:*` tickers from the missing set (they're handled by the cash proxy path, not auto-generation):

```python
# When building missing_tickers list, skip CUR:* — they get cash handling
if ticker.startswith("CUR:"):
    available_tickers.append(ticker)
    cash_proxy_tickers.append(ticker)
    continue
```

### Step 6: Position metadata labeling

**File:** `services/position_metadata.py`

Extend cash detection to use `is_cash_ticker()` from Step 1, so `CUR:*` tickers display and classify as cash even without proxy ETF substitution.

### Step 7: Legacy path audit — `portfolio_assembler.py` / `portfolio_manager.py`

**Files:** `inputs/portfolio_assembler.py:196-229`, `inputs/portfolio_manager.py:366, 656-661`

These paths still do `CUR:* → proxy ETF` substitution for the CLI/YAML pipeline. For this implementation, **leave them as-is** — they serve a different code path (YAML portfolio files, not live positions). The live positions path through `to_portfolio_data()` is what feeds the optimizer and is the fix target.

If these paths are later unified with the live path, the same `is_cash_ticker()` predicate can be applied.

## Files Modified

| File | Change | Lines |
|------|--------|-------|
| `portfolio_risk_engine/portfolio_config.py` | Add `is_cash_ticker()` predicate + update `standardize_portfolio_input()` risky exposure | near line 42, 210-212 |
| `portfolio_risk_engine/data_objects.py` | Stop proxy rewrite in `to_portfolio_data()`, update unmapped cash filter, update risky exposure calc | 533-568, 622-634, 740-760 |
| `portfolio_risk_engine/portfolio_risk.py` | Synthetic cash returns in `_fetch_ticker_returns()` | 760-761 |
| `services/returns_service.py` | Extend `_is_cash_proxy()` for `CUR:*`, currency-aware expected returns, exclude `CUR:*` from missing-return auto-generation | 514-532, ~409-423, `_validate_complete_coverage()` |
| `services/position_metadata.py` | Use `is_cash_ticker()` for classification | ~43-77 |

## Tests

### New unit tests

1. `to_portfolio_data()` preserves `CUR:GBP` — does NOT emit `ERNS.L`
2. `to_portfolio_data()` preserves `CUR:USD` — does NOT emit `SGOV`
3. `_fetch_ticker_returns("CUR:USD", ...)` returns non-empty near-zero series (not None)
4. `_fetch_ticker_returns("CUR:GBP", ...)` returns FX-adjusted series (not None, not zero for non-USD)
5. `is_cash_ticker("CUR:GBP")` returns True
6. `is_cash_ticker("AAPL")` returns False
7. `is_cash_ticker("SGOV")` returns True (existing proxy still recognized)
8. Risky exposure excludes positive `CUR:GBP`
9. Risky exposure includes negative `CUR:USD` (margin debt)
10. `_is_cash_proxy("CUR:GBP")` returns True (expected returns coverage)
11. Upstream alias canonicalization: `USD CASH` / `CASH` / `BASE_CURRENCY` are normalized to `CUR:USD` by `position_service.py:1247-1277` before reaching `to_portfolio_data()` — verify non-CUR aliases never reach the synthetic return path
12. `CUR:USD` synthetic returns have nonzero sample variance (random noise, not constant)
13. Covariance matrix with `CUR:USD` is positive definite (not singular) — `np.linalg.eigvalsh(cov)` all > 0
14. `CUR:USD` expected return = Treasury rate; `CUR:GBP` expected return = 0.0 (not Treasury rate)
15. FX failure fallback: if `adjust_returns_for_fx()` raises, `CUR:GBP` still gets nonzero-variance series (noise floor)

### Existing tests to update

- `tests/core/test_notional_weights.py:160-162` — asserts `ERNS.L` in standardized_input; update to `CUR:GBP`
- Any test asserting `SGOV` from raw `CUR:USD` cash input in the live positions path

### Integration / regression

- Optimization with GBP cash: covariance matrix has FX-only variance for CUR:GBP (not bond-fund variance)
- `min_variance` with GBP cash: allocates based on FX risk, not bond duration
- `max_sharpe` with CUR:USD: optimizer does not degenerate into 100% cash allocation (weight constraints prevent this)
- Leverage calculation still correct with CUR:* tickers
- Risk summary labels CUR:* as cash
- SGOV/ERNS.L no longer appear in covariance matrix or optimizer output when portfolio uses live positions path

## Verification

1. Run unit tests: `python3 -m pytest tests/ -k "cash" -v`
2. Run full test suite: `python3 -m pytest tests/ -x`
3. MCP tool check: call `get_risk_analysis` — verify CUR:GBP appears as cash, ERNS.L absent
4. MCP tool check: call `run_optimization` — verify optimizer sees cash-like (not bond-like) risk for GBP cash
5. Leverage check: verify leverage > 1.0 with negative CUR:USD (margin debt still works)

## Review Log

| # | Round | Priority | Finding | Resolution |
|---|-------|----------|---------|------------|
| 1 | R1 | P1 | `_is_cash_proxy()` must be updated for CUR:* | Already addressed in Step 4 |
| 2 | R1 | P2 | Zero-variance CUR:USD → singular covariance matrix | Added variance floor `1e-8` for USD cash in Step 3 |
| 3 | R1 | P2 | Circular import risk: portfolio_config → data_objects | Verified: no circular import exists. portfolio_config does NOT import data_objects |
| 4 | R1 | P2 | FX double-counting risk for non-USD cash | Already handled: synthetic series is local-currency, FX layer runs once, CUR:* not in currency_map |
| 5 | R1 | P2 | Test coverage gaps | Added tests 11-13 (alias canonicalization, variance floor, PD covariance) + optimizer regression tests |
| 6 | R1 | P3 | Observation count risk | Non-issue: 5-year lookback yields ~60 observations, well above 11 threshold |
| 7 | R2 | P2 | Constant 1e-8 series has zero sample variance (demeaning kills it) | Changed to `np.random.normal(0, 1e-6)` with fixed seed for deterministic nonzero variance |
| 8 | R2 | P2 | `standardize_portfolio_input()` uses old cash set, not `is_cash_ticker()` | Already safe: `_get_cash_positions_cached()` includes CUR:* aliases from YAML. `is_cash_ticker()` adds prefix fallback for unlisted currencies |
| 9 | R3 | P1 | Non-USD cash gets USD Treasury expected return — inconsistent with zero-carry model | Differentiate in Step 4: CUR:USD → Treasury rate, CUR:GBP/EUR → 0.0 expected return |
| 10 | R3 | P2 | FX failure fallback leaves non-USD cash as zero-variance riskless asset | Apply same noise floor as USD cash on FX exception, seeded by ticker hash |
| 11 | R4 | P1 | `standardize_portfolio_input()` misses CUR:GBP — not in alias_to_currency | Added Step 5b: replace `t not in cash_positions` with `not is_cash_ticker(t)` in portfolio_config.py:210-212 |
| 12 | R4 | P1 | `ensure_returns_coverage()` auto-generates equity returns for CUR:*, overriding cash handling | Added Step 5c: exclude CUR:* from missing-return generation in validate/ensure coverage |
| 13 | R4 | P2 | `hash(ticker)` is randomized per Python process (PYTHONHASHSEED) | Changed to `hashlib.md5` for stable cross-process seeding |

## Out of Scope

- Reworking realized-performance cash replay (separate pipeline)
- Per-user cash proxy overrides
- Per-currency overnight cash rates (SONIA, ESTR) — Phase 1 uses zero local carry + FX, which is semantically correct even without carry. Enhancement deferred.
- Legacy CLI/YAML pipeline (`portfolio_assembler.py`, `portfolio_manager.py`) — separate code path, not optimizer-facing

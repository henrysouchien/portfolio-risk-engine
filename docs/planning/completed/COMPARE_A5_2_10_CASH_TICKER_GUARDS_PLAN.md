# Plan: Cash Ticker Guards for Optimizer + Proxy Validation (A5.2, A5.10)

## Context

Two bugs involve `CUR:USD` (and other cash tickers) flowing into code paths that assume all tickers have factor proxy entries and finite betas.

**A5.2**: `solve_min_variance_with_risk_limits()` and `solve_max_return_with_risk_limits()` crash with `KeyError` when `CUR:USD` is in the portfolio. The per-proxy constraint loop at `portfolio_optimizer.py:321` uses `proxies[t].get("industry")` — a direct dict subscript that raises `KeyError` when `t` is a cash ticker absent from `stock_factor_proxies`. The same loop at `:1321` uses `stock_factor_proxies[t].get("industry")` with the same crash. By contrast, `efficient_frontier.py:159` uses `(proxies.get(ticker) or {}).get("industry")` which is safe.

**A5.10**: `evaluate_portfolio_beta_limits()` in `core/run_portfolio_risk.py:366-377` produces a permanent false-positive FAIL for cash-related proxy betas. When a proxy beta is `NaN` (e.g., from a stale proxy row for a cash ticker), `abs(NaN) <= inf` evaluates to `False` in Python/NumPy, causing the compliance check to report FAIL even though the `max_allowed_beta` is `inf`. Cash tickers have no meaningful industry beta, so NaN betas should be skipped rather than failed.

### Root causes

1. **A5.2**: The optimizer's per-proxy constraint loop uses `proxies[t]` (crashes on missing key) instead of `proxies.get(t, {})` (safe). Cash tickers like `CUR:USD` are in the covariance matrix (they receive synthetic near-zero returns from the cash semantics fix at `b5ff9122`) but are NOT in `stock_factor_proxies`.

2. **A5.10**: (a) `evaluate_portfolio_beta_limits()` has no guard for non-finite beta values. Python's `abs(NaN) <= inf` is `False`, so any NaN proxy beta automatically fails. (b) Cash tickers can produce NaN betas if they appear in `df_stock_betas` with NaN values before the `.fillna(0.0)` step, or if they have a stale proxy row in `stock_factor_proxies`.

### Existing safe pattern

`is_cash_ticker()` at `portfolio_risk_engine/portfolio_config.py:72` already recognizes `CUR:*` prefixed tickers and YAML-configured cash equivalents. It is used by `data_objects.py`, `portfolio_risk.py`, `factor_intelligence_service.py`, and `position_metadata.py` — but NOT by the optimizer constraint loops or the beta validation function.

---

## Change 1: Filter cash tickers from optimizer constraint loops

**Files**: `portfolio_risk_engine/portfolio_optimizer.py`

**Two locations** — the per-proxy constraint loops in `solve_min_variance_with_risk_limits()` (line ~318) and `solve_max_return_with_risk_limits()` (line ~1317).

### 1a. `solve_min_variance_with_risk_limits()` — line ~318

**Current code** (lines 318–329):
```python
# Build coefficient vectors for each proxy
for proxy, cap in proxy_caps.items():
    coeff = []
    for t in tickers:
        this_proxy = proxies[t].get("industry")
        if this_proxy == proxy:
            coeff.append(beta_mat.loc[t, "industry"])
        else:
            coeff.append(0.0)
    
    coeff_array = np.array(coeff)
    if not np.allclose(coeff_array, 0):  # Only add constraint if non-zero
        cons += [cp.abs(coeff_array @ w) <= cap]
```

**New code**:
```python
# Build coefficient vectors for each proxy
for proxy, cap in proxy_caps.items():
    coeff = []
    for t in tickers:
        this_proxy = proxies.get(t, {}).get("industry")
        if this_proxy == proxy:
            coeff.append(beta_mat.loc[t, "industry"])
        else:
            coeff.append(0.0)
    
    coeff_array = np.array(coeff)
    if not np.allclose(coeff_array, 0):  # Only add constraint if non-zero
        cons += [cp.abs(coeff_array @ w) <= cap]
```

**What changed**: `proxies[t].get("industry")` → `proxies.get(t, {}).get("industry")`. This is the same safe-access pattern used by `efficient_frontier.py:159`. When `t` is a cash ticker not in `proxies`, `proxies.get(t, {})` returns `{}`, and `.get("industry")` returns `None`, so `this_proxy == proxy` is `False` and the coefficient is 0.0. The cash ticker gets a zero coefficient in every proxy constraint — it contributes no industry beta to the optimization, which is correct (cash has no industry exposure).

### 1b. `solve_max_return_with_risk_limits()` — line ~1317

**Current code** (lines 1317–1323):
```python
coeff_proxy: Dict[str, np.ndarray] = {}
for proxy in proxy_caps:
    coeff = []
    for t in tickers:
        this_proxy = stock_factor_proxies[t].get("industry")
        coeff.append(β_tbl.loc[t, "industry"] if this_proxy == proxy else 0.0)
    coeff_proxy[proxy] = np.array(coeff)
```

**New code**:
```python
coeff_proxy: Dict[str, np.ndarray] = {}
for proxy in proxy_caps:
    coeff = []
    for t in tickers:
        this_proxy = stock_factor_proxies.get(t, {}).get("industry")
        coeff.append(β_tbl.loc[t, "industry"] if this_proxy == proxy else 0.0)
    coeff_proxy[proxy] = np.array(coeff)
```

**What changed**: `stock_factor_proxies[t].get("industry")` → `stock_factor_proxies.get(t, {}).get("industry")`. Same pattern as 1a.

### Why NOT filter `tickers` to exclude cash

An alternative approach would be to filter cash tickers out of the `tickers` list before entering the constraint loops (e.g., `tickers = [t for t in tickers if not is_cash_ticker(t)]`). This was considered but rejected because:

1. Cash tickers are already in the covariance matrix and the weight variable vector. Removing them from `tickers` mid-function would create a dimension mismatch between `w` (length `n`) and `beta_mat` (indexed by `tickers`), breaking the `beta_mat[fac].values @ w` constraint on line 300.
2. The safe `.get()` pattern produces the correct behavior (zero industry beta coefficient) without restructuring the ticker list or variable dimensions.
3. This matches the pattern already proven safe in `efficient_frontier.py:159`.

---

## Change 2: Add NaN/Inf guard to `evaluate_portfolio_beta_limits()`

**File**: `core/run_portfolio_risk.py`

**Location**: The proxy-level check loop at lines 366–377.

**Current code** (lines 366–377):
```python
# ─── Proxy-level checks (e.g. SOXX, XSW) ─────────────────
if proxy_betas and max_proxy_betas:
    for proxy, actual in proxy_betas.items():
        max_b = max_proxy_betas.get(proxy, float("inf"))
        label = f"industry_proxy::{proxy}"
        rows.append({
            "factor": label,
            "portfolio_beta": actual,
            "max_allowed_beta": max_b,
            "pass": abs(actual) <= max_b,
            "buffer": max_b - abs(actual),
        })
```

**New code**:
```python
# ─── Proxy-level checks (e.g. SOXX, XSW) ─────────────────
if proxy_betas and max_proxy_betas:
    for proxy, actual in proxy_betas.items():
        if not math.isfinite(actual):
            continue  # skip NaN/Inf betas (e.g. cash tickers with no industry exposure)
        max_b = max_proxy_betas.get(proxy, float("inf"))
        label = f"industry_proxy::{proxy}"
        rows.append({
            "factor": label,
            "portfolio_beta": actual,
            "max_allowed_beta": max_b,
            "pass": abs(actual) <= max_b,
            "buffer": max_b - abs(actual),
        })
```

**What changed**: Added `if not math.isfinite(actual): continue` before the pass/fail check. This skips NaN and ±Inf proxy betas, which cannot be meaningfully compared against limits. This prevents false-positive FAILs from cash tickers or any other source of non-finite betas.

**Import**: Add `import math` to the top of `core/run_portfolio_risk.py` (after the existing stdlib imports on line 6–11).

### Why `math.isfinite()` rather than `pd.notna()`

`math.isfinite(x)` returns `False` for NaN, +Inf, and -Inf — all three are meaningless for compliance checks. `pd.notna(x)` only catches NaN, not ±Inf. While ±Inf betas are unlikely in practice, they would also produce nonsensical compliance results, so the broader guard is safer.

### Why NOT add the guard to the factor-level check too

The factor-level check (lines 352–364) uses `portfolio_factor_betas.get(factor, 0.0)` which defaults missing factors to 0.0. The `portfolio_factor_betas` Series is computed from `df_stock_betas_filled` (which has NaN → 0.0 via `.fillna(0.0)` at `portfolio_risk.py:1951`), so NaN is not expected there. Adding a guard there would be pure defense-in-depth with no known failure path. Keeping the change scoped to the proxy-level loop (where the bug actually occurs) minimizes diff and review surface.

---

## Test Plan

### A5.2 Tests

**File**: New test file `tests/portfolio_risk_engine/test_optimizer_cash_ticker.py`

**Test 1: min_variance with CUR:USD does not crash**

Construct a portfolio with `{"AAPL": 0.5, "MSFT": 0.3, "CUR:USD": 0.2}` and `stock_factor_proxies` that has entries for AAPL and MSFT but NOT for `CUR:USD`. Call `solve_min_variance_with_risk_limits()`. Assert it returns a dict of weights without raising `KeyError`. Assert `CUR:USD` has weight ≥ 0 (it should participate in the optimization but with zero industry beta coefficient).

**Test 2: max_return with CUR:USD does not crash**

Same setup as Test 1 but call `solve_max_return_with_risk_limits()` with `expected_returns={"AAPL": 0.10, "MSFT": 0.08, "CUR:USD": 0.001}`. Assert no `KeyError`, returns valid weights.

**Test 3: Cash ticker gets zero industry beta coefficient**

Unit test the constraint-building logic directly: with `proxies = {"AAPL": {"industry": "XLK"}}` and `tickers = ["AAPL", "CUR:USD"]`, verify that `proxies.get("CUR:USD", {}).get("industry")` is `None` and the coefficient for `CUR:USD` is 0.0 in the proxy constraint vector.

### A5.10 Tests

**File**: New test file `tests/core/test_beta_limits_nan_guard.py`

**Test 4: NaN proxy beta is skipped, not failed**

Call `evaluate_portfolio_beta_limits()` with `proxy_betas={"XLK": 0.5, "SGOV": float("nan")}` and `max_proxy_betas={"XLK": 1.0, "SGOV": float("inf")}`. Assert the result DataFrame has a row for `industry_proxy::XLK` (pass=True) but NO row for `industry_proxy::SGOV` (it should be skipped entirely).

**Test 5: Inf proxy beta is skipped**

Same as Test 4 but with `proxy_betas={"XLK": 0.5, "BAD": float("inf")}`. Assert no row for `industry_proxy::BAD`.

**Test 6: All-NaN proxy betas produce empty proxy section**

Call with `proxy_betas={"A": float("nan"), "B": float("nan")}`. Assert no proxy rows in the result, only factor-level rows.

**Test 7: Normal proxy betas still pass/fail correctly (regression)**

Call with `proxy_betas={"XLK": 0.5}`, `max_proxy_betas={"XLK": 0.3}`. Assert `pass=False` (0.5 > 0.3). Call with `max_proxy_betas={"XLK": 1.0}`. Assert `pass=True`.

---

## Files Modified

| File | Change |
|------|--------|
| `portfolio_risk_engine/portfolio_optimizer.py` | Safe dict access in two per-proxy constraint loops (lines ~321, ~1321) |
| `core/run_portfolio_risk.py` | `import math` + NaN guard in proxy-level beta check (line ~368) |
| `tests/portfolio_risk_engine/test_optimizer_cash_ticker.py` | New: 3 tests for A5.2 |
| `tests/core/test_beta_limits_nan_guard.py` | New: 4 tests for A5.10 |

---

## Risks

- **Regression risk**: Very low. The `.get(t, {})` change is a strict relaxation — it handles a superset of inputs (tickers missing from the proxies dict) that previously crashed. All existing tickers that ARE in the proxies dict produce identical behavior.
- **NaN skip risk**: Skipping NaN betas means they no longer appear in compliance reports. This is correct — a NaN beta is not a risk violation, it is a data gap. If upstream data quality improves (e.g., cash tickers are properly excluded from `stock_factor_proxies`), the guard becomes a no-op.
- **Optimizer weight allocation**: Cash tickers get zero industry beta coefficients, so they are unconstrained by industry beta limits. They are still constrained by the weight-sum, concentration, and volatility constraints. The optimizer may allocate weight to cash if it minimizes variance (min_variance) or if cash has positive expected returns (max_return). This is correct behavior — cash is a low-risk asset.
- **No structural changes**: Both fixes are single-line changes (safe dict access, NaN guard). No function signatures, return types, or data flows are altered.

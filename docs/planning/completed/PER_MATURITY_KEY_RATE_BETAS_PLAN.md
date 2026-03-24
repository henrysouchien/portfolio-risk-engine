# Per-Maturity Key-Rate Betas for Stress Testing

## Context

The stress test sums 4 key-rate betas (UST2Y/5Y/10Y/30Y) into a single `interest_rate` beta at `portfolio_risk.py:1598`, then applies a single +0.03 shock. For mortgage REITs/BDCs with mixed-sign maturity betas (positive short-end from NIM benefit, negative long-end from duration), the sum can net positive — producing a counterintuitive +11.1% gain from a "rate shock."

For a parallel shift, per-maturity math is equivalent to aggregate (`Σ(βᵢ×s) = s×Σ(βᵢ)`). The real value: per-maturity attribution in `factor_contributions`, and non-parallel scenarios (bear flattener) where sign differences materially change the result.

## Files to Modify

### 1. `portfolio_risk_engine/portfolio_risk.py`

**a) Derive maturity map from config** (module-level constant, used by both variance decomposition at line 386 and rate beta storage at line 1598):
```python
from portfolio_risk_engine.config import RATE_FACTOR_CONFIG
_RATE_MATURITY_COL_MAP = {
    k: f"rate_{k.replace('UST', '').lower()}"
    for k in RATE_FACTOR_CONFIG["default_maturities"]
}
# → {"UST2Y": "rate_2y", "UST5Y": "rate_5y", "UST10Y": "rate_10y", "UST30Y": "rate_30y"}
```
Derived from `RATE_FACTOR_CONFIG["default_maturities"]` to avoid drift from hardcoded duplicates (Codex R1 issue 3).

**b) Initialize per-maturity columns** (line 1545-1546):
After `df_stock_betas["interest_rate"] = 0.0`, also init per-maturity columns:
```python
for col in _RATE_MATURITY_COL_MAP.values():
    df_stock_betas[col] = 0.0
```

**c) Zero per-maturity on early exits** (lines 1558-1560, 1575-1577, 1591-1593):
Everywhere `interest_rate` is set to 0.0 (non-eligible class, missing returns, min_obs), also zero per-maturity columns.

**d) Store per-maturity betas** (line 1597-1599):
After `rate_betas = rate_res.get("betas", {})`, store individuals before summing:
```python
for mat_key, beta_val in rate_betas.items():
    col = _RATE_MATURITY_COL_MAP.get(mat_key)
    if col:
        df_stock_betas.loc[ticker, col] = float(beta_val)
```
Keep aggregate `interest_rate` line unchanged (backward compat).

**e) Exclude per-maturity from variance decomposition** (line 386):
```python
_RATE_MATURITY_COLS = set(_RATE_MATURITY_COL_MAP.values())
_VARIANCE_EXCLUDED_COLS = {"industry", "subindustry"} | _RATE_MATURITY_COLS
factor_var_matrix = (
    weighted_factor_var
    .drop(columns=[c for c in _VARIANCE_EXCLUDED_COLS if c in weighted_factor_var.columns], errors="ignore")
    .fillna(0.0)
)
```
Prevents double-counting with the aggregate `interest_rate` column used for variance. Exclusion set derived from the same config-driven map (Codex R1 issue 3).

### 2. `portfolio_risk_engine/stress_testing.py`

Update 3 existing scenarios to use per-maturity shock keys. Add 1 new non-parallel scenario.

```python
"interest_rate_shock": {
    "name": "Interest Rate Shock",
    "description": "300bp parallel shift in yield curve",
    "severity": "High",
    "shocks": {"rate_2y": 0.03, "rate_5y": 0.03, "rate_10y": 0.03, "rate_30y": 0.03},
},
"credit_spread_widening": {
    "name": "Credit Spread Widening",
    "description": "200bp widening in credit spreads",
    "severity": "Medium",
    "shocks": {"rate_2y": 0.02, "rate_5y": 0.02, "rate_10y": 0.02, "rate_30y": 0.02, "market": -0.05},
},
"stagflation": {
    "name": "Stagflation",
    "description": "Rising rates + falling equities + value rotation",
    "severity": "High",
    "shocks": {"market": -0.10, "rate_2y": 0.02, "rate_5y": 0.02, "rate_10y": 0.02, "rate_30y": 0.02, "growth": -0.10, "value": 0.05},
},
```

New scenario (add to `STRESS_SCENARIOS`):
```python
"bear_flattener": {
    "name": "Bear Flattener",
    "description": "Short rates rise sharply, long end anchored — classic Fed hiking path",
    "severity": "High",
    "shocks": {"rate_2y": 0.03, "rate_5y": 0.02, "rate_10y": 0.015, "rate_30y": 0.01},
},
```

`run_stress_test()` needs NO changes — it already iterates `for factor, shock in shocks.items()` and looks up per-factor betas.

### 3. `core/result_objects/risk.py`

Add per-maturity entries to `FACTOR_DISPLAY_NAMES` (if it exists) for proper labeling in risk drivers output. If no such constant, skip — frontend `formatFactorLabel` turns `rate_2y` → `Rate 2y` automatically.

### 4. Frontend: filter per-maturity keys from non-stress-test displays

**a) `frontend/packages/ui/src/components/dashboard/views/modern/FactorRiskModelContainer.tsx`**

Filter per-maturity keys from the Factor Risk Model display. The container iterates `portfolio_factor_betas` to build the factor exposure table. With 4 new `rate_*` keys that have 0% variance contribution (excluded from decomposition), they'd show as 0% contribution rows — confusing alongside the aggregate `interest_rate` row.

Add a filter when building the exposure rows: skip keys matching `/^rate_\d+y$/`. This keeps the aggregate `interest_rate` row as the single rate exposure in the Factor Risk Model. The per-maturity breakdown is visible only in stress test `factor_contributions` where it's actionable.

(Codex R1 issue 1)

**b) `frontend/packages/ui/src/components/dashboard/shared/charts/adapters/chartDataAdapters.ts`** (~line 505)

The `basicFactors` exclusion list at line 505 filters known factors from the "Industry Contributions" fallback path. Per-maturity `rate_*` keys would leak through as bogus industry rows. Add `rate_2y`, `rate_5y`, `rate_10y`, `rate_30y`, `interest_rate` to the exclusion list:

```typescript
const basicFactors = ['market', 'value', 'momentum', 'industry', 'subindustry',
  'interest_rate', 'rate_2y', 'rate_5y', 'rate_10y', 'rate_30y'];
```

(Codex R2 issue 2)

### 5. Tests

**Update** existing stress test tests:
- `test_run_all_stress_tests_returns_sorted_results` — mock `portfolio_factor_betas` must include `rate_2y/5y/10y/30y` keys since scenarios now reference them.
- `test_get_stress_scenarios_returns_all_eight_predefined_scenarios` — update count assertion from 8 → 9 (bear_flattener added). Rename test accordingly.
- Any other tests that hard-assert scenario count or scenario keys must be updated for the 9th scenario.

**Add** new test:
```python
def test_per_maturity_rate_betas_preserve_sign():
    """Mixed-sign maturity betas produce correct per-maturity contributions."""
    # rate_2y=+2.0 (positive short-end), rate_30y=-2.0 (negative long-end)
    # Parallel +0.03: 2.0*0.03 + 0.5*0.03 + (-1.5)*0.03 + (-2.0)*0.03 = -0.03
    # Aggregate sum = -1.0, * 0.03 = -0.03 (same for parallel)
```

**Add** test for bear flattener showing different result than parallel:
```python
def test_bear_flattener_differs_from_parallel():
    """Non-parallel shocks produce different impact than parallel."""
    # Same betas, different shocks → different result
```

**Add** to `tests/core/test_portfolio_risk.py` (Codex R1 issue 4):
- Per-maturity columns are populated correctly in `df_stock_betas`
- Aggregate `interest_rate` still equals sum of per-maturity betas
- Early-exit paths (non-eligible class, missing returns, min_obs) zero both aggregate and per-maturity columns
- Variance decomposition excludes per-maturity columns

**Update** `frontend/packages/ui/src/components/dashboard/views/modern/StockLookupContainer.test.tsx` (~lines 444, 478):
The test hard-codes the legacy factor exposure row count. Update the expectation to include per-maturity `rate_*` rows in the `factorExposures` array, or use a flexible assertion that checks known factors exist rather than exact row count. (Codex R4 issue)

## Intentionally Unchanged Consumers (Codex R1 issue 2, R3 issues 1-2)

Per-maturity betas exist in `df_stock_betas` and `portfolio_factor_betas` primarily for stress test consumption. They will also appear in other factor-exposure displays — this is **acceptable and informative** (an analyst benefits from seeing per-maturity rate sensitivity in what-if comparison and portfolio fit). The following consumers see the new keys:

- **Optimizer / efficient frontier** — constrain only named factors (`market`, `momentum`, etc.). Per-maturity keys are not in the constraint set. No action needed.
- **Beta-limit checks** (`run_portfolio_risk.py:353`) — iterate `max_betas` dict, which doesn't include `rate_*` keys. No action needed.
- **Risk drivers** (`_build_risk_drivers`) — built from variance decomposition which excludes per-maturity. They won't appear in risk drivers.
- **Hedging routes** (`routes/hedging.py:195`) — reads specific keys like `market`. No action needed.
- **What-if comparison** (`core/result_objects/whatif.py:350`) — returns all `portfolio_factor_betas` keys. Per-maturity keys will appear in the comparison output. **Acceptable** — shows rate curve sensitivity in what-if context.
- **Portfolio Fit UI** (`StockLookupContainer.tsx:757`, `PortfolioFitTab.tsx:305`) — renders all factor exposures. Per-maturity keys will appear as factor rows. **Acceptable** — useful for an analyst evaluating how a new position changes rate sensitivity across maturities.
- **Formatted risk reports** (`core/result_objects/risk.py:1392`) — prints full `stock_betas` and `portfolio_factor_betas`. Per-maturity keys will appear in CLI output. **Acceptable** — more detail is better for diagnostic output.

## What Does NOT Change

- `run_stress_test()` function — already handles arbitrary shock keys
- `StressTestAdapter.ts` / `StressTestTool.tsx` — passes through `factor_contributions` generically
- `effective_duration` — still reads aggregate `interest_rate` key
- Frontend scenario dropdown — renders whatever `get_stress_scenarios()` returns (9 instead of 8 scenarios)
- `formatShockValue` in frontend — regex `/(rate|spread|yield)/i` matches `rate_2y` etc., displays in bp format

## Verification

1. `pytest tests/test_stress_testing.py -x -q` — all tests pass
2. `pytest tests/core/test_portfolio_risk.py -x -q` — no regressions
3. Browser: run "Interest Rate Shock" — factor_contributions now show 4 maturity rows instead of 1 "interest_rate" row
4. Browser: run "Bear Flattener" — different impact than Interest Rate Shock for same portfolio
5. Browser: run Market Crash — unchanged (no rate shocks involved)

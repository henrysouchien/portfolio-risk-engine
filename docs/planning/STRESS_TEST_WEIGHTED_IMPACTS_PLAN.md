# Fix Stress Test Impact — Per-Stock Weighted Factor Stress

## Context

The Stress Tests tab shows raw worst-month proxy returns as portfolio impacts (e.g., Industry: -53.4%). This is the raw worst monthly return of one industry proxy (SLV), not a portfolio-level impact. SLV is a small position — the portfolio would barely feel a silver crash.

## Formula

```
factor_stress_impact[ftype] = Σ (weight_i × beta_i[ftype] × shock_i[ftype])
```

Where for each non-cash stock i:
- `weight_i` = portfolio weight from allocations (already includes leverage in shares/dollars mode — no separate leverage multiplier)
- `beta_i[ftype]` = stock's factor beta from `df_stock_betas` (NaN-filled to 0.0 by `build_portfolio_view()`)
- `shock_i[ftype]` = worst loss for THAT STOCK's proxy:
  - market/industry: raw worst monthly return from `worst_per_proxy`
  - momentum/value: excess worst monthly return from `worst_excess_per_proxy` (fallback to raw if unavailable)

For shared-proxy factors (all stocks use SPY for market), this reduces to `Σ(weight_i × beta_i) × worst_loss = portfolio_beta × worst_loss`.

For per-stock-proxy factors (industry), each stock contributes its own proxy's worst loss.

## Excess-Return Shocks (Momentum/Value)

Momentum/value betas are estimated on excess-return series (`fetch_excess_return(factor_ETF, market_ETF)`). Shocks must match. We compute excess worst months per `(factor_proxy, market_proxy)` pair and store them keyed by that pair.

**New helper** `_fetch_excess_worst(factor_proxy, market_proxy, ...)` calls `fetch_excess_return()` and returns `(worst_loss, "YYYY-MM")`.

**Storage**: `worst_excess_per_proxy: Dict[Tuple[str,str], {"loss": float, "date": str}]` keyed by `(factor_proxy, market_proxy)` tuple. This handles the case where the same ETF could be used against different market proxies.

**Lookup in `compute_factor_stress_impacts()`**: For momentum/value, look up `worst_excess_per_proxy[(stock's_proxy, stock's_market_proxy)]`. If found, use excess loss. If not, fall back to raw `worst_per_proxy[proxy]`.

## Date Display

No single "worst month" for weighted composite. Show `{N}Y lookback` when weighted impacts are used. Fallback: `Historical worst-case` if lookback years unavailable. `Synthetic scenario` for volatility test.

## Coverage

`coverage = covered_abs_weight / total_abs_weight`

- **Denominator (total)**: all non-cash tickers in `portfolio_weights`. Cash tickers (from `get_cash_positions()`) are excluded entirely.
- **Numerator (covered)**: non-cash tickers that have a usable shock value — i.e., scalar proxy with EITHER a matching `worst_excess_per_proxy` entry (for momentum/value) OR a matching `worst_per_proxy` entry (raw fallback or non-excess factor). The coverage reflects the actual shock source used, not just the preferred one.
- **Non-cash tickers missing from `stock_factor_proxies`**: uncovered (in denominator, not numerator).
- **Tickers with list-valued proxy**: uncovered (beta estimated on peer-median, no matching shock).
- **Tickers with 0.0 beta** (NaN-filled by `build_portfolio_view()`): counted as covered IF they have a usable shock value. `build_portfolio_view()` guarantees all eligible tickers appear in `df_stock_betas` with NaN filled to 0.0 — confirmed at `portfolio_risk.py:1618`. A 0.0 beta means "no modeled exposure" and contributes 0 to impact. Coverage measures shock data availability, not factor sensitivity.
- **Tickers absent from `df_stock_betas` entirely** (e.g., not passed to `build_portfolio_view()`): if they have a proxy and shock data, they're still covered but contribute 0 (safe `.get()` returns 0.0). If no proxy/shock, they're uncovered.

Frontend shows warning in Stress Test Summary card if min coverage < 0.8.

## Changes

### 1. Backend: `portfolio_risk_engine/risk_helpers.py`

**Add** `_fetch_excess_worst()` — calls `fetch_excess_return()`, returns `(worst_loss, date)`.

**Add** `compute_factor_stress_impacts()`:
```python
def compute_factor_stress_impacts(
    stock_factor_proxies: Dict[str, Dict[str, Union[str, List[str]]]],
    worst_per_proxy: Dict[str, float],
    worst_excess_per_proxy: Dict[tuple, Dict[str, Any]],  # (factor_proxy, market_proxy) → {"loss", "date"}
    df_stock_betas: pd.DataFrame,
    portfolio_weights: Dict[str, float],
    factor_types: List[str],
    cash_tickers: Set[str] | None = None,
) -> Dict[str, Dict[str, float]]:
    """Returns {factor_type: {"impact": decimal, "coverage": 0.0-1.0}}"""
```

Per factor_type, per non-cash ticker:
- Skip cash tickers
- Skip tickers not in `stock_factor_proxies` (uncovered)
- Skip list-valued proxies (uncovered)
- For momentum/value: look up `(proxy, market_proxy)` in `worst_excess_per_proxy`; fallback to raw
- For market/industry: use raw `worst_per_proxy[proxy]`
- Get beta via `df_stock_betas.get(ftype, pd.Series()).get(ticker, 0.0)` (safe for missing row/column)
- Accumulate `weight × beta × shock`

**Modify** `calc_max_factor_betas()` — after `worst_per_proxy` is computed, compute excess worst months:
```python
EXCESS_FACTORS = {"momentum", "value"}
worst_excess_per_proxy = {}
excess_pairs = set()
for proxy_map in proxies.values():
    mkt = proxy_map.get("market")
    if not mkt or isinstance(mkt, list): continue
    for ftype in EXCESS_FACTORS:
        fp = proxy_map.get(ftype)
        if fp and isinstance(fp, str) and fp in worst_per_proxy:
            excess_pairs.add((fp, mkt))

for fp, mkt in excess_pairs:
    if (fp, mkt) not in worst_excess_per_proxy:
        result = _fetch_excess_worst(fp, mkt, start_str, end_str, fmp_ticker_map=fmp_map)
        if result:
            worst_excess_per_proxy[(fp, mkt)] = {"loss": result[0], "date": result[1]}

# Serialize tuple keys for JSON
historical_analysis['worst_excess_per_proxy'] = {
    f"{fp}|{mkt}": v for (fp, mkt), v in worst_excess_per_proxy.items()
}
```

### 2. Backend: `core/portfolio_analysis.py`

After line 242 (result constructed):
```python
from portfolio_risk_engine.risk_helpers import compute_factor_stress_impacts
worst_by_factor = historical_analysis.get("worst_by_factor", {})
# Deserialize pipe-separated keys back to tuples
raw_excess = historical_analysis.get("worst_excess_per_proxy", {})
excess_tuples = {tuple(k.split("|")): v for k, v in raw_excess.items() if "|" in k}

factor_stress_impacts = compute_factor_stress_impacts(
    stock_factor_proxies=config.get("stock_factor_proxies", {}),
    worst_per_proxy=historical_analysis.get("worst_per_proxy", {}),
    worst_excess_per_proxy=excess_tuples,
    df_stock_betas=summary.get("df_stock_betas", pd.DataFrame()),
    portfolio_weights={
        str(t): float(row["Portfolio Weight"])
        for t, row in summary.get("allocations", pd.DataFrame()).iterrows()
        if "Portfolio Weight" in summary.get("allocations", pd.DataFrame()).columns
    },
    factor_types=list(worst_by_factor.keys()),
    cash_tickers=set(get_cash_positions()),
)
result.historical_analysis["factor_stress_impacts"] = factor_stress_impacts
```

### 3. Frontend: `RiskAnalysisAdapter.ts` (both declarations ~173 and ~255)

```typescript
factor_stress_impacts?: Record<string, { impact: number; coverage: number }>;
worst_excess_per_proxy?: Record<string, { loss: number; date: string }>;
```

### 4. Frontend: `catalog/types.ts` (~line 130)

Same additions.

### 5. Frontend: `RiskAnalysisModernContainer.tsx`

All-or-nothing: if `factor_stress_impacts` has ALL `worst_by_factor` keys AND every factor has coverage > 0, use weighted for all. Otherwise raw for all. A factor with `coverage: 0.0` means no shock data was usable — that factor should NOT be displayed as 0% impact.

```typescript
const stressImpacts = histAnalysis?.factor_stress_impacts;
const factorKeys = worstByFactor ? Object.keys(worstByFactor) : [];
const useWeightedImpacts = !!(stressImpacts
  && factorKeys.length > 0
  && factorKeys.every(f => f in stressImpacts && stressImpacts[f].coverage > 0));
const analysisYears = (histAnalysis as any)?.analysis_period?.years as number | undefined;

// Per row:
tests.push({
  scenario: `${factor} Stress Test`,
  impact: (useWeightedImpacts ? stressImpacts![factor].impact : loss) * 100,
  worstDate: useWeightedImpacts ? undefined : worstDates?.[factor],
  lookbackYears: useWeightedImpacts ? analysisYears : undefined,
  isWeighted: useWeightedImpacts,
});

// Coverage warning:
let stressCoverageNote: string | undefined;
if (useWeightedImpacts) {
  const worst = Object.entries(stressImpacts!).reduce(
    (w, [f, s]) => s.coverage < w.coverage ? { factor: f, coverage: s.coverage } : w,
    { factor: '', coverage: 1 }
  );
  if (worst.coverage < 0.8) {
    stressCoverageNote = `${worst.factor} stress excludes ${Math.round((1 - worst.coverage) * 100)}% of portfolio weight (missing data).`;
  }
}
```

### 6. Frontend: `RiskAnalysis.tsx`

Add to data prop interface: `stressCoverageNote?: string`

Add to stress test type: `lookbackYears?: number`, `isWeighted?: boolean`

Display:
```typescript
{test.worstDate ? `Worst month: ${(() => { const [y,m] = test.worstDate.split('-'); return `${STRESS_TEST_MONTHS[parseInt(m,10)-1]} ${y}`; })()}`
  : test.lookbackYears ? `${test.lookbackYears}Y lookback`
  : test.isWeighted ? 'Historical worst-case'
  : 'Synthetic scenario'}
```

**Conditional tooltip text**: The tooltip shown on each stress test row must reflect the actual methodology being used. Since `isWeighted` is available on each stress test object, use it to select the tooltip:

```typescript
const tooltip = test.isWeighted
  ? "Position-weighted portfolio impact: each holding's factor beta × its own proxy's worst historical month."
  : getStressScenarioTooltip(test.scenario);  // Existing per-scenario raw proxy tooltips
```

Similarly, `potentialLoss` tooltip on the impact number:
```typescript
const lossTooltip = test.isWeighted
  ? "Portfolio-level loss estimate weighted by position size and factor sensitivity."
  : RISK_ANALYSIS_TOOLTIPS.potentialLoss;  // Existing raw tooltip
```

This ensures the raw-fallback path still shows the original tooltips describing raw proxy returns.

Coverage warning in summary card:
```typescript
{data.stressCoverageNote && (
  <p className="text-xs text-amber-700 mt-1">{data.stressCoverageNote}</p>
)}
```

### 7. Frontend: `useRiskMetrics.ts` (~line 71)

Apply same all-or-nothing check. If `factor_stress_impacts` fully available, use worst weighted impact. Otherwise existing raw logic.

## What Does NOT Change

- `_fetch_single_proxy_worst()`, `get_worst_monthly_factor_losses()`, `aggregate_worst_losses_by_factor_type()`, `compute_max_betas()` — all unchanged
- `calc_max_factor_betas()` — MODIFIED: adds excess worst computation and `worst_excess_per_proxy` to `historical_analysis`. Return type and existing callers unaffected.
- `run_stress_test()` / `stress_testing.py` — unchanged
- `RiskAnalysisResult` dataclass fields — unchanged
- Formatters — unchanged
- `worst_by_factor`, `worst_per_proxy`, `worst_factor_dates` — all preserved

## Files to Modify

| File | Change |
|------|--------|
| `portfolio_risk_engine/risk_helpers.py` | Add `_fetch_excess_worst()`, `compute_factor_stress_impacts()`, modify `calc_max_factor_betas()` |
| `core/portfolio_analysis.py` | Call `compute_factor_stress_impacts()` after result construction |
| `frontend/.../RiskAnalysisAdapter.ts` | Add types (both declarations) |
| `frontend/.../catalog/types.ts` | Add types |
| `frontend/.../RiskAnalysisModernContainer.tsx` | All-or-nothing weighted impacts + coverage warning |
| `frontend/.../RiskAnalysis.tsx` | `stressCoverageNote` prop, `lookbackYears`/`isWeighted` fields, display logic |
| `frontend/.../useRiskMetrics.ts` | All-or-nothing weighted preference |

## Tests

**Backend** (`tests/core/test_portfolio_risk.py`):
- `compute_factor_stress_impacts()`: known inputs → verify weighted sum
- Single-proxy factor (market): result = Σ(weight × beta) × worst_loss (no separate leverage)
- Per-stock proxy factor (industry): each stock contributes own proxy
- Momentum/value: uses excess worst from `worst_excess_per_proxy`, not raw
- Excess fallback: if no excess entry → uses raw
- List-valued proxy → skipped, coverage < 1.0
- Missing proxy in `worst_per_proxy` → uncovered
- Zero beta (NaN-filled to 0.0) → contributes 0 to impact, coverage unaffected
- Missing ticker in `stock_factor_proxies` (non-cash) → uncovered
- Cash ticker → excluded from both impact and coverage
- Cash in `stock_factor_proxies` AND `cash_tickers` → excluded
- `total_abs_weight == 0` → returns `{"impact": 0.0, "coverage": 0.0}`
- `_fetch_excess_worst()`: mock `fetch_excess_return` → verify (worst_loss, date)
- Integration: `calc_max_factor_betas()` → verify `worst_excess_per_proxy` populated

**Frontend** (`RiskAnalysis.test.tsx`):
- `lookbackYears` → "10Y lookback"
- `worstDate` → "Worst month: Mar 2020"
- `isWeighted` without `lookbackYears` → "Historical worst-case"
- Neither → "Synthetic scenario"
- `stressCoverageNote` present → renders warning

**Frontend** (container/integration):
- All factors in `factor_stress_impacts` → uses weighted, shows lookback
- Some factors missing → falls back to raw for ALL
- Missing entirely → raw for all
- Low coverage → warning note

**Frontend** (`useRiskMetrics.test.tsx`):
- Weighted impacts preferred when complete
- Partial → fallback to raw
- Absent → existing raw logic

## Verification

1. `pytest tests/core/test_portfolio_risk.py -k "factor_stress or excess_worst" --no-header -q`
2. `pytest tests/core/test_portfolio_risk.py --no-header -q` — no regressions
3. `npx tsc --noEmit --project packages/ui/tsconfig.json`
4. `npx eslint <touched frontend files>`
5. Browser: Industry should be ~5% instead of 53%, shows "10Y lookback"
6. Backward compat: without backend restart, frontend shows raw proxy losses

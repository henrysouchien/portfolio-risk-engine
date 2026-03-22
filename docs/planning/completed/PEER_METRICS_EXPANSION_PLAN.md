# Add 7 New Metrics to Peer Comparison Table

## Context

The peer comparison table has 13 metrics from `ratios_ttm`. Adding 7 more to match the SIA comps framework.

## Field Availability (Verified against live FMP API)

| Metric | Source | Field | Status |
|--------|--------|-------|--------|
| EBITDA Margin | ratios_ttm | `ebitdaMarginTTM` | ✅ Already in primary fetch |
| Enterprise Value | ratios_ttm | `enterpriseValueTTM` | ✅ Already in primary fetch |
| ROIC | key_metrics_ttm | `returnOnInvestedCapitalTTM` | ✅ Best-effort 2nd fetch |
| FCF Yield | key_metrics_ttm | `freeCashFlowYieldTTM` | ✅ Best-effort 2nd fetch |
| Revenue | income_statement (limit=1) | `revenue` | ✅ Best-effort 3rd fetch |
| EBITDA | income_statement (limit=1) | `ebitda` | ✅ Best-effort 3rd fetch |
| FCF Margin | Computed | `cash_flow.freeCashFlow / income_statement.revenue` | ✅ Best-effort computed |

## Group Structure (4 groups)

1. **Valuation** — P/E, P/B, P/S, P/FCF, PEG, EV/EBITDA
2. **Profitability** — Gross Margin, Operating Margin, Net Margin, EBITDA Margin (new), FCF Margin (new)
3. **Balance Sheet & Returns** — Debt/Equity, Current Ratio, ROIC (new), FCF Yield (new), Dividend Yield, FCF/Share
4. **Scale** — Revenue (new), EBITDA (new), Enterprise Value (new)

## Changes

### 1. Backend: `fmp/tools/peers.py`

**Extend `_fetch_ratios()` with 3 best-effort fetches:**

```python
def _fetch_ratios(fmp: FMPClient, ticker: str) -> tuple[str, dict | None, str | None]:
    try:
        # Primary: ratios_ttm (existing, required)
        data = fmp.fetch_raw("ratios_ttm", symbol=ticker)
        if isinstance(data, list) and len(data) > 0:
            ratios_dict = data[0]
        elif isinstance(data, dict) and data:
            ratios_dict = data
        else:
            return (ticker, None, f"Empty response for {ticker}")

        # Best-effort: key_metrics_ttm (ROIC, FCF Yield)
        metrics_dict = {}
        try:
            metrics = fmp.fetch_raw("key_metrics_ttm", symbol=ticker)
            if isinstance(metrics, list) and len(metrics) > 0:
                metrics_dict = metrics[0]
            elif isinstance(metrics, dict) and metrics:
                metrics_dict = metrics
        except Exception:
            pass

        # Best-effort: income_statement (Revenue, EBITDA)
        # Handles both list and dict responses, same as ratios_ttm
        income_dict = {}
        try:
            inc = fmp.fetch_raw("income_statement", symbol=ticker, limit=1)
            if isinstance(inc, list) and len(inc) > 0:
                row = inc[0]
            elif isinstance(inc, dict) and inc:
                row = inc
            else:
                row = {}
            # Use _annual_ prefix to avoid key collisions with TTM fields
            if row.get("revenue") is not None:
                income_dict["_annual_revenue"] = row["revenue"]
            if row.get("ebitda") is not None:
                income_dict["_annual_ebitda"] = row["ebitda"]
        except Exception:
            pass

        # Best-effort: cash_flow (for FCF Margin computation)
        # Independent from income_statement — if this fails, only FCF Margin is lost
        # Handles both list and dict responses
        try:
            cf = fmp.fetch_raw("cash_flow", symbol=ticker, limit=1)
            if isinstance(cf, list) and len(cf) > 0:
                cf_row = cf[0]
            elif isinstance(cf, dict) and cf:
                cf_row = cf
            else:
                cf_row = {}
            fcf = cf_row.get("freeCashFlow")
            rev = income_dict.get("_annual_revenue")
            if fcf is not None and rev is not None and rev > 0:
                income_dict["_computed_fcf_margin"] = fcf / rev
        except Exception:
            pass

        # Merge — ratios_ttm takes precedence on overlapping keys
        merged = {**metrics_dict, **income_dict, **ratios_dict}
        return (ticker, merged, None)
    except Exception as e:
        return (ticker, None, str(e))
```

Key design:
- Each additional fetch has its own try/except — ratios_ttm always works alone
- Revenue/EBITDA use `_annual_` prefix to avoid collisions with any TTM fields
- FCF Margin is computed (`freeCashFlow / revenue`) not fetched — stored as `_computed_fcf_margin`
- Preserves existing list/dict response handling

**Add 7 new metrics to `DEFAULT_PEER_METRICS`:**

```python
DEFAULT_PEER_METRICS = [
    # --- Valuation (existing) ---
    "priceToEarningsRatioTTM",
    "priceToBookRatioTTM",
    "priceToSalesRatioTTM",
    "priceToFreeCashFlowRatioTTM",
    "priceToEarningsGrowthRatioTTM",
    "enterpriseValueMultipleTTM",
    # --- Profitability ---
    "grossProfitMarginTTM",
    "operatingProfitMarginTTM",
    "netProfitMarginTTM",
    "ebitdaMarginTTM",                 # NEW
    "_computed_fcf_margin",            # NEW (computed)
    # --- Balance Sheet & Returns ---
    "debtToEquityRatioTTM",
    "currentRatioTTM",
    "returnOnInvestedCapitalTTM",      # NEW
    "freeCashFlowYieldTTM",            # NEW
    "dividendYieldTTM",
    "freeCashFlowPerShareTTM",
    # --- Scale ---
    "_annual_revenue",                 # NEW
    "_annual_ebitda",                  # NEW
    "enterpriseValueTTM",              # NEW
]
```

**Add labels to `METRIC_LABELS`:**

```python
"ebitdaMarginTTM": "EBITDA Margin",
"_computed_fcf_margin": "FCF Margin",
"returnOnInvestedCapitalTTM": "ROIC",
"freeCashFlowYieldTTM": "FCF Yield",
"_annual_revenue": "Revenue",
"_annual_ebitda": "EBITDA",
"enterpriseValueTTM": "Enterprise Value",
```

### 2. Frontend: `frontend/packages/ui/src/components/portfolio/stock-lookup/helpers.ts`

**`NON_POSITIVE_EXCLUDES_RANKING`** — do NOT add the new metrics. This set excludes ≤0 values from ranking, which is correct for valuation multiples (negative P/E is meaningless) but wrong for ROIC, margins, and yield where negative values are valid data points that should rank worst. The new metrics rank normally — negative ROIC or margins simply rank at the bottom.

**`formatPeerMetricValue()`** — add:

1. **Absolute dollar metrics** (Revenue, EBITDA, EV):
```typescript
const ABSOLUTE_DOLLAR_METRICS = new Set([
  "_annual_revenue", "_annual_ebitda", "enterpriseValueTTM",
]);
if (ABSOLUTE_DOLLAR_METRICS.has(metricKey)) {
  if (Math.abs(val) >= 1e12) return `$${(val / 1e12).toFixed(1)}T`;
  if (Math.abs(val) >= 1e9) return `$${(val / 1e9).toFixed(1)}B`;
  if (Math.abs(val) >= 1e6) return `$${(val / 1e6).toFixed(0)}M`;
  return `$${val.toFixed(0)}`;
}
```

2. **Percent metrics** not caught by existing "Margin"/"Yield" substring check:
```typescript
const EXPLICIT_PERCENT_METRICS = new Set([
  "returnOnInvestedCapitalTTM",
  "_computed_fcf_margin",
]);
```
These get `× 100` + `%` formatting.

3. **No-ranking metrics** — add a `NO_RANKING_METRICS` set:
```typescript
export const NO_RANKING_METRICS = new Set([
  "_annual_revenue", "_annual_ebitda", "enterpriseValueTTM",
]);
```

### 3. Frontend: `frontend/packages/ui/src/components/portfolio/stock-lookup/PeerComparisonTab.tsx`

**Update `METRIC_GROUP`:**
```typescript
ebitdaMarginTTM: "Profitability",
_computed_fcf_margin: "Profitability",
returnOnInvestedCapitalTTM: "Balance Sheet & Returns",
freeCashFlowYieldTTM: "Balance Sheet & Returns",
_annual_revenue: "Scale",
_annual_ebitda: "Scale",
enterpriseValueTTM: "Scale",
```

**Update `GROUP_ORDER`:**
```typescript
const GROUP_ORDER = ["Valuation", "Profitability", "Balance Sheet & Returns", "Scale"];
```

**Wire `NO_RANKING_METRICS`** into ranking logic:
- Import from `helpers.ts`
- In rank computation (~line 72), skip if `NO_RANKING_METRICS.has(metricKey)`
- Don't render rank badge for those metrics

### 4. Tests: `tests/mcp_tools/test_peers.py`

- Update `len(DEFAULT_PEER_METRICS)` assertions → 20
- Add test: `key_metrics_ttm` fails → ROIC/FCF Yield show "—", other metrics work
- Add test: `income_statement` fails → Revenue/EBITDA/FCF Margin show "—", other metrics work
- Add test: FCF Margin computed correctly from FCF/Revenue
- Add test: `cash_flow` fails but `income_statement` succeeds → Revenue/EBITDA present, FCF Margin shows "—"
- Add test: `_annual_` prefixed keys don't collide with TTM fields

**Note on `compare_peers(format="full")` contract**: The `format="full"` response currently returns "all TTM ratios" per ticker. This change extends it to also include `key_metrics_ttm` fields and annual statement fields (prefixed with `_annual_` / `_computed_`). This is intentional — the full format should include all available data for each peer.

**Note on mixed periods**: The table mixes TTM ratios (margins, P/E, etc.) with annual figures (Revenue, EBITDA from latest fiscal year) and a computed annual FCF Margin. This is an accepted product choice — TTM is the standard for ratios, and latest annual is standard for absolute scale metrics. The UI does not need period labels since this is conventional.

## Files to Modify

| File | Change |
|------|--------|
| `fmp/tools/peers.py` | 3 best-effort fetches, 7 new metrics + labels, FCF Margin computation |
| `frontend/.../stock-lookup/helpers.ts` | $ formatting, % formatting, NON_POSITIVE, NO_RANKING sets |
| `frontend/.../stock-lookup/PeerComparisonTab.tsx` | METRIC_GROUP + GROUP_ORDER + no-rank wiring |
| `tests/mcp_tools/test_peers.py` | Update count, add fallback/merge/computation tests |

## Verification

1. `pytest tests/mcp_tools/test_peers.py -q` — updated tests pass
2. `cd frontend && npx tsc --noEmit --project packages/ui/tsconfig.json` — clean for our files
3. Browser: Research → AAPL → vs Peers → 4 groups, 20 metrics
4. EBITDA Margin: ~35.1%, FCF Margin: ~23.7%
5. ROIC: ~51.0%, FCF Yield: ~3.4%
6. Revenue: ~$416B, EBITDA: ~$144B, EV: ~$3.7T
7. Scale metrics (Revenue, EBITDA, EV) show no rank badges
8. If key_metrics_ttm or income_statement fails, those metrics show "—" but existing 13 still work

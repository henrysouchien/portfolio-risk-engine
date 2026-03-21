# Quality Score — Port Investment Tools Methodology to Stock Lookup

## Context

The Quality card in Stock Lookup uses simplistic ratio-based scoring (ROE/30 × 100, etc.). The investment_tools repo has a proven 6-signal quality methodology (7 minus breakout which is momentum, not quality). We're replacing the ratio-based scoring with signal-based scoring.

## The 6 Signals (all binary: true / false / null)

1. **Revenue Growth** — `income[Y0].revenue > income[Y1].revenue > 0`
2. **Positive FCF** — `cashflow[Y0].freeCashFlow > 0 AND cashflow[Y1].freeCashFlow > 0`
3. **CapEx Investment** — `|cashflow[Y0].capitalExpenditure| > |cashflow[Y1].capitalExpenditure|`
4. **Gross Margin Improvement** — `GPM[Y0] > GPM[Y1] > GPM[Y2]` (3-year trend)
5. **ROE/ROIC Positive** — `returnOnEquityTTM > 0 OR returnOnInvestedCapitalTTM > 0`
6. **Low Leverage** — `netDebtToEBITDATTM < 2.0` (from key_metrics_ttm directly, NOT computed from balance sheet)

Source logic: `investment_tools/fmp/signals.py:18-94`.

## Key Design Decisions

### Three-state signals (not binary)
Each signal returns `true` (pass), `false` (fail), or `null` (insufficient data). `null` means the data wasn't available — NOT that the company fails the check. The score is the count of passing signals. `evaluated` is the count of non-null signals (denominator). Displayed as "score/evaluated" (e.g., "4/5"). UI shows a gray "N/A" for null signals.

### Low leverage uses key_metrics_ttm directly
`key_metrics_ttm` already provides `netDebtToEBITDATTM`. No need to fetch balance sheet separately and compute the ratio manually. This also handles the EBITDA=0 edge case since FMP returns null for the ratio when EBITDA is zero/negative. For banks/REITs/insurers where this ratio is meaningless, it will likely be null — which correctly becomes N/A rather than a false negative.

### Statement ordering
Sort income/cashflow statements by `date` descending before indexing Y0/Y1/Y2. Validate at least 2 statements exist (3 for gross margin). If insufficient, that signal returns null.

### FMP client returns DataFrames
`fmp_client.fetch()` returns pandas DataFrames. Convert to `list[dict]` via `.to_dict("records")` before passing to signal functions, or write signal functions to accept DataFrames directly.

## Changes

### 1. Backend: New file `fmp/quality_signals.py`

```python
from typing import Any

def _get_float(record: dict, key: str) -> float | None:
    """Safe float extraction."""
    val = record.get(key)
    if val is None: return None
    try: return float(val)
    except (TypeError, ValueError): return None

def revenue_growth(income: list[dict]) -> bool | None:
    if len(income) < 2: return None
    r0, r1 = _get_float(income[0], "revenue"), _get_float(income[1], "revenue")
    if r0 is None or r1 is None: return None
    return r0 > r1 > 0

def positive_fcf(cashflow: list[dict]) -> bool | None:
    if len(cashflow) < 2: return None
    f0, f1 = _get_float(cashflow[0], "freeCashFlow"), _get_float(cashflow[1], "freeCashFlow")
    if f0 is None or f1 is None: return None
    return f0 > 0 and f1 > 0

def capex_increase(cashflow: list[dict]) -> bool | None:
    if len(cashflow) < 2: return None
    c0, c1 = _get_float(cashflow[0], "capitalExpenditure"), _get_float(cashflow[1], "capitalExpenditure")
    if c0 is None or c1 is None: return None
    return abs(c0) > abs(c1)

def gross_margin_improvement(income: list[dict]) -> bool | None:
    if len(income) < 3: return None
    try:
        gpm = []
        for i in range(3):
            gp, rev = _get_float(income[i], "grossProfit"), _get_float(income[i], "revenue")
            if gp is None or rev is None or rev == 0: return None
            gpm.append(gp / rev)
        return gpm[0] > gpm[1] > gpm[2]
    except Exception:
        return None

def roe_roic_positive(metrics_ttm: list[dict]) -> bool | None:
    if not metrics_ttm: return None
    m = metrics_ttm[0]
    roe = _get_float(m, "returnOnEquityTTM")
    roic = _get_float(m, "returnOnInvestedCapitalTTM")
    if roe is None and roic is None: return None
    return (roe is not None and roe > 0) or (roic is not None and roic > 0)

def low_leverage(metrics_ttm: list[dict], threshold: float = 2.0) -> bool | None:
    if not metrics_ttm: return None
    val = _get_float(metrics_ttm[0], "netDebtToEBITDATTM")
    if val is None: return None  # FMP returns null for zero/negative EBITDA
    return val < threshold

SIGNAL_FUNCS = {
    "revenue_growth": lambda inc, cf, met: revenue_growth(inc),
    "positive_fcf": lambda inc, cf, met: positive_fcf(cf),
    "capex_increase": lambda inc, cf, met: capex_increase(cf),
    "gross_margin_improvement": lambda inc, cf, met: gross_margin_improvement(inc),
    "roe_roic_positive": lambda inc, cf, met: roe_roic_positive(met),
    "low_leverage": lambda inc, cf, met: low_leverage(met),
}

def compute_quality_signals(
    income_statements: list[dict],
    cashflow_statements: list[dict],
    metrics_ttm: list[dict],
) -> dict:
    # Sort statements by date descending
    income = sorted(income_statements, key=lambda r: r.get("date", ""), reverse=True)
    cashflow = sorted(cashflow_statements, key=lambda r: r.get("date", ""), reverse=True)

    signals = {}
    for name, fn in SIGNAL_FUNCS.items():
        signals[name] = fn(income, cashflow, metrics_ttm)

    passing = sum(1 for v in signals.values() if v is True)
    failing = sum(1 for v in signals.values() if v is False)
    evaluated = passing + failing

    return {
        "quality": {
            "signals": signals,
            "score": passing,       # Count of True signals (numerator)
            "evaluated": evaluated,  # Count of non-null signals (denominator)
            "max_signals": len(SIGNAL_FUNCS),  # Total possible (6)
        }
    }
    # Display as "score/evaluated" e.g., "4/5" (4 passing out of 5 with data)
    # NOT a ratio — score is a raw count. Frontend divides for percentage if needed.
```

No balance sheet fetch needed — `key_metrics_ttm` provides the leverage ratio directly.

### 2. Backend: `services/stock_service.py` — extend `enrich_stock_data()`

Add 2 new FMP calls (not 4 — no balance sheet, key_metrics_ttm may already be fetched):

```python
# Check fmp/registry.py for exact endpoint keys
income_df = self.fmp_client.fetch("income_statement", symbol=ticker, limit=3)
cashflow_df = self.fmp_client.fetch("cash_flow", symbol=ticker, limit=3)
# key_metrics_ttm may already be fetched — reuse if so
metrics_df = self.fmp_client.fetch("key_metrics_ttm", symbol=ticker)

# Convert DataFrames to list[dict]
income = income_df.to_dict("records") if income_df is not None and not income_df.empty else []
cashflow = cashflow_df.to_dict("records") if cashflow_df is not None and not cashflow_df.empty else []
metrics = metrics_df.to_dict("records") if metrics_df is not None and not metrics_df.empty else []

from fmp.quality_signals import compute_quality_signals
quality_result = compute_quality_signals(income, cashflow, metrics)
enriched.update(quality_result)  # Adds "quality" key directly
```

**Performance**: 3 FMP calls total for quality signals: `income_statement`, `cash_flow`, `key_metrics_ttm`. The FMPClient has LRU caching, so if `key_metrics_ttm` was already fetched by existing enrichment, the second call is a cache hit (free). Always call it explicitly — don't try to share state between enrichment steps. Let the cache handle dedup.

### 3. Frontend: `StockLookupContainer.tsx` — map quality data

This is where `selectedStock` is built (not the adapter). Add mapping for the new `quality` field from the API response:

```typescript
quality: apiData?.quality ?? null,
```

### 4. Frontend: `stock-lookup/types.ts`

Add to `SelectedStockData`:

```typescript
quality?: {
  signals: Record<string, boolean | null>;
  score: number;
  evaluated: number;
  max_signals: number;
} | null;
```

### 5. Frontend: `SnapshotTab.tsx` — Replace Quality card

Remove `financialHealthScores` memo (lines 146-191) and the old Profitability/Leverage/Valuation sub-score rendering (lines 337-356).

New Quality card:
- Header: "Quality" with score badge e.g., "4/5" (passing/evaluated)
- Subtitle: "Fundamental quality signals" or similar
- 6 signal rows: signal name + icon (✓ green for true, ✗ red for false, — gray for null)
- Keep ROE, Profit Margin, Debt/Equity as context metrics below (these come from existing fundamentals)
- Financial Health progress bar uses `score/evaluated * 100` (or 0 if evaluated=0)

**Backend contract for quality field:**
- `quality = null` → FMP fetch failed entirely (network error, API key issue). Frontend shows old ratio-based card as fallback.
- `quality = { signals: {...}, score: 0, evaluated: 0, max_signals: 6 }` → FMP returned data but all signals were null (missing filings). Frontend shows signal card with all N/A rows.
- `quality = { signals: {...}, score: 4, evaluated: 5, max_signals: 6 }` → Normal case. Frontend shows signal card with pass/fail/N/A.

In `enrich_stock_data()`, wrap the quality computation in try/except. On exception → set `enriched["quality"] = None`. On success → set the result dict.

**Frontend degraded state**: `if (quality) { /* signal card */ } else { /* existing ratio card as fallback */ }`. Don't remove the old code — guard it.

**Signal display names:**
```typescript
const SIGNAL_LABELS: Record<string, string> = {
  revenue_growth: "Revenue Growing",
  positive_fcf: "Positive Free Cash Flow",
  capex_increase: "Increasing CapEx",
  gross_margin_improvement: "Margin Improvement",
  roe_roic_positive: "Positive ROE/ROIC",
  low_leverage: "Low Leverage",
};
```

### 6. Existing tests

`tests/services/test_stock_service_provider_registry.py` asserts the exact FMP fetch list/order. Update it to include the new `income_statement`, `cash_flow`, and `key_metrics_ttm` calls.

## FMP Endpoint Keys (verified from `fmp/registry.py`)

| Data | Registry key |
|------|-------------|
| Income statement | `income_statement` |
| Cash flow | `cash_flow` |
| Key metrics TTM | `key_metrics_ttm` |

No `balance_sheet` fetch needed.

## Response Shape (consistent backend → frontend)

Backend returns nested:
```json
{
  "quality": {
    "signals": {
      "revenue_growth": true,
      "positive_fcf": true,
      "capex_increase": false,
      "gross_margin_improvement": null,
      "roe_roic_positive": true,
      "low_leverage": true
    },
    "score": 4,
    "evaluated": 5,
    "max_signals": 6
  }
}
```

Frontend receives it as-is — no translation layer needed.

## Files to Modify

| File | Change |
|------|--------|
| `fmp/quality_signals.py` | **NEW** — 6 signal functions + orchestrator |
| `services/stock_service.py` | Add FMP calls + quality computation in `enrich_stock_data()` |
| `tests/fmp/test_quality_signals.py` | **NEW** — unit tests for signal computation |
| `tests/services/test_stock_service_provider_registry.py` | Update expected fetch list |
| `frontend/.../views/modern/StockLookupContainer.tsx` | Map `quality` from API response |
| `frontend/.../stock-lookup/types.ts` | Add `quality` field |
| `frontend/.../stock-lookup/SnapshotTab.tsx` | Signal-based Quality card with ratio fallback |

## Tests

**New file: `tests/fmp/test_quality_signals.py`** — unit tests for `compute_quality_signals()`:
- All signals true with known good financial data
- All signals false with known bad data
- Null signals when statements missing/insufficient (< 2 years, < 3 years for gross margin)
- Null signals when individual fields are null
- Score = count of True, evaluated = count of non-null
- Empty input → all null, score 0, evaluated 0
- Unsorted statements → sorted correctly by date before evaluation
- Low leverage: null EBITDA → null signal (not false)

**Update: `tests/services/test_stock_service_provider_registry.py`** — add `income_statement`, `cash_flow`, `key_metrics_ttm` to expected fetch list.

## Verification

1. `pytest tests/fmp/test_quality_signals.py -q` — new tests pass
2. `pytest tests/services/test_stock_service_provider_registry.py -q` — updated test passes
3. `cd frontend && npx tsc --noEmit --project packages/ui/tsconfig.json` — full tsc clean (or only pre-existing errors, none in our files)
4. Browser: Research → AAPL → Quality card shows signal pass/fail
5. Browser: Search a stock with missing filings → signals show N/A gracefully
6. Browser: When quality data unavailable → falls back to old ratio card

# Switch Revenue/EBITDA to TTM + Section Period Labels

## Context

The peer comparison Financials section mixes periods: Revenue and EBITDA are annual (last fiscal year) while margins are TTM. This prevents labeling the section header with a consistent period. Switching Revenue/EBITDA to TTM (sum of last 4 quarters) makes the entire Financials section TTM-consistent, enabling clean section headers.

## Changes

### 1. Backend: `fmp/tools/peers.py` — fetch quarterly, sum for TTM

**Change the `annual_income` request spec** (line 167-170):

```python
# Change:
"annual_income": (
    "income_statement",
    {"symbol": normalized_ticker, "limit": 1, "period": "annual"},
),
# To:
"quarterly_income": (
    "income_statement",
    {"symbol": normalized_ticker, "limit": 4, "period": "quarter"},
),
```

**Replace the income extraction** (lines 205-212) to sum 4 quarters:

```python
income_dict: dict[str, object] = {}
income_rows: list[dict] = []
quarterly_income_payload, _ = responses["quarterly_income"]
if isinstance(quarterly_income_payload, list):
    income_rows = [r for r in quarterly_income_payload if isinstance(r, dict)]
elif isinstance(quarterly_income_payload, dict):
    income_rows = [quarterly_income_payload]

if income_rows:
    # Require 4 non-null quarters for true TTM — partial sums are mislabeled
    rev_values = [r["revenue"] for r in income_rows if r.get("revenue") is not None]
    ebitda_values = [r["ebitda"] for r in income_rows if r.get("ebitda") is not None]
    if len(rev_values) == 4:
        income_dict["_ttm_revenue"] = sum(rev_values)  # can be negative (pre-revenue)
    if len(ebitda_values) == 4:
        income_dict["_ttm_ebitda"] = sum(ebitda_values)  # can be negative (unprofitable)
```

Use `income_rows[0]` for `reportedCurrency` (line 266-267 — most recent quarter).

**FCF Margin computation** (line 248-250): Update to use `_ttm_revenue`:

```python
revenue = income_dict.get("_ttm_revenue")
```

Also change the `cash_flow` fetch to quarterly sum for consistency:

```python
# Change:
"cash_flow": ("cash_flow", {"symbol": normalized_ticker, "limit": 1, "period": "annual"}),
# To:
"cash_flow": ("cash_flow", {"symbol": normalized_ticker, "limit": 4, "period": "quarter"}),
```

Then sum FCF across 4 quarters:

```python
cash_flow_payload, _ = responses["cash_flow"]
cash_flow_rows = []
if isinstance(cash_flow_payload, list):
    cash_flow_rows = [r for r in cash_flow_payload if isinstance(r, dict)]
elif isinstance(cash_flow_payload, dict):
    cash_flow_rows = [cash_flow_payload]
# Require 4 non-null quarters for TTM FCF — same rule as revenue/EBITDA
fcf_values = [r["freeCashFlow"] for r in cash_flow_rows if r.get("freeCashFlow") is not None]
free_cash_flow = sum(fcf_values) if len(fcf_values) == 4 else None
```

**Rename keys in `DEFAULT_PEER_METRICS`:**

```python
"_annual_revenue" → "_ttm_revenue"
"_annual_ebitda" → "_ttm_ebitda"
```

**Rename in `METRIC_LABELS`:**

```python
"_ttm_revenue": "Revenue",
"_ttm_ebitda": "EBITDA",
```

(Labels stay short — the section header provides the period context.)

**Update `ABSOLUTE_METRICS`** (line 138-143):

```python
"_annual_revenue" → "_ttm_revenue"
"_annual_ebitda" → "_ttm_ebitda"
```

### 2. Frontend: `PeerComparisonTab.tsx` — section header labels

Update group names in `METRIC_GROUP` and `GROUP_ORDER`:

```typescript
// GROUP_ORDER:
const GROUP_ORDER = ["Financials (TTM)", "Balance Sheet & Returns", "Valuation"]

// METRIC_GROUP: update all "Financials" → "Financials (TTM)"
// Move enterpriseValueTTM from "Financials" → "Valuation" (point-in-time, not a TTM flow)
// Balance Sheet & Returns stays unlabeled — contains a mix of flow metrics (ROIC, FCF Yield)
// and point-in-time metrics (Current Ratio) where "TTM" is misleading
```

Valuation stays unlabeled — individual metrics already have "(FY1)" or are self-evident (P/B, P/FCF are TTM by convention).

### 3. Frontend: `helpers.ts`

Update `NO_RANKING_METRICS`:

```typescript
'_annual_revenue' → '_ttm_revenue'
'_annual_ebitda' → '_ttm_ebitda'
```

Update `ABSOLUTE_DOLLAR_METRICS`:

```typescript
'_annual_revenue' → '_ttm_revenue'
'_annual_ebitda' → '_ttm_ebitda'
```

### 4. Tests: `tests/mcp_tools/test_peers.py`

- Update SAMPLE_INCOME_STATEMENTS to return quarterly format (list of 4 dicts with revenue/ebitda per quarter)
- Update SAMPLE_CASH_FLOW similarly
- Update all `_annual_revenue` / `_annual_ebitda` references → `_ttm_revenue` / `_ttm_ebitda`
- Verify TTM sum is correct (4 quarters summed)
- Update `test_default_metrics_not_empty` assertions
- Update FX conversion test to use new keys

### 5. Frontend test: `helpers.test.ts`

- No changes needed unless there are existing assertions on `_annual_*` keys

## Edge Cases

- Fewer than 4 quarters available (new IPO) → omit TTM revenue/EBITDA (shows "—")
- Quarter has null revenue/ebitda → skipped in sum (not treated as 0)
- All quarters null → field not in dict → shows "—"
- Negative EBITDA preserved (unprofitable companies show negative, not "—")
- FCF Margin uses TTM revenue + TTM FCF → null FCF stays null (not false 0%)
- FCF Margin only computed when TTM revenue > 0 and TTM FCF is non-null (preserve existing `revenue > 0` guard)
- Require exactly 4 quarters for TTM — if fewer than 4 rows returned, omit `_ttm_revenue` / `_ttm_ebitda` (shows "—" rather than mislabeled partial sum)

## What Does NOT Change

- Forward metrics (P/E, EV/EBITDA, EV/Sales, PEG) — unchanged
- Margins — already TTM from ratios_ttm
- Enterprise Value — already TTM
- Balance Sheet metrics — already TTM
- `reportedCurrency` detection — uses most recent quarter's currency

## Files to Modify

| File | Change |
|------|--------|
| `fmp/tools/peers.py` | Quarterly fetch + TTM sum, rename keys |
| `frontend/.../PeerComparisonTab.tsx` | Section header labels + key renames in METRIC_GROUP |
| `frontend/.../helpers.ts` | Rename keys in NO_RANKING + ABSOLUTE_DOLLAR sets |
| `tests/mcp_tools/test_peers.py` | Update mock data + assertions |

## Verification

1. `pytest tests/mcp_tools/test_peers.py -q` — passes
2. Browser: AAPL → vs Peers → "FINANCIALS (TTM)" header, Revenue/EBITDA show TTM values
3. Balance Sheet & Returns header stays unlabeled
4. Valuation section header stays clean (no period label)
5. FX conversion still works for foreign stocks

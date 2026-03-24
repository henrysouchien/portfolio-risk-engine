# Add Forward Metrics to Stock Lookup Enrichment

## Context

The stock lookup MCP tool (`analyze_stock`) already computes forward P/E via `fetch_forward_pe()`. But it doesn't include forward EV/EBITDA, EV/Sales, or forward PEG — metrics we now compute in peer comparison. The AI should see these forward metrics when analyzing individual stocks too.

All required data is already fetched in `enrich_stock_data()`:
- `analyst_estimates` — fetched inside `fetch_forward_pe()` (has `ebitdaAvg`, `revenueAvg`)
- `key_metrics_ttm` — fetched for quality signals (has `enterpriseValueTTM`)
- `ratios_ttm` — fetched for TTM ratios (has `forwardPriceToEarningsGrowthRatioTTM`)

Problem: `fetch_forward_pe()` fetches estimates internally but doesn't expose them. To avoid duplicate API calls, we need to refactor.

## Changes

### 1. Backend: `utils/fmp_helpers.py` — new `fetch_forward_metrics()`

Add a combined function that fetches estimates ONCE and computes all forward metrics:

```python
def fetch_forward_metrics(
    fmp_client: Any,
    ticker: str,
    current_price: Any,
    enterprise_value: Any = None,
) -> dict[str, Any]:
    """Fetch analyst estimates and compute all forward valuation metrics.

    Returns dict with:
      - forward_pe, ntm_eps, pe_source, analyst_count, fiscal_period (same as fetch_forward_pe)
      - forward_ev_ebitda: float | None
      - forward_ev_sales: float | None
    """
```

Internally:
1. Calls `_get_last_reported_fiscal_date()` (once)
2. Fetches `analyst_estimates` (once) — same normalization as current `fetch_forward_pe()`
3. Calls `compute_forward_pe(current_price, estimate_records, last_reported_fiscal_date)`
4. If `enterprise_value` is provided:
   - Calls `compute_forward_ev_ebitda(enterprise_value, estimate_records, last_reported_fiscal_date)`
   - Calls `compute_forward_ev_sales(enterprise_value, estimate_records, last_reported_fiscal_date)`
5. Returns combined dict

`fetch_forward_pe()` remains unchanged (backward compatible for other callers).

### 2. Backend: `services/stock_service.py` — use `fetch_forward_metrics()`

In `enrich_stock_data()`, the forward P/E enrichment block (lines ~613-634):

**Before** (current):
```python
forward_pe_data = fetch_forward_pe(self.fmp_client, ticker, data.get("current_price"))
data["forward_pe"] = forward_pe_data.get("forward_pe")
...
```

**After**:
```python
forward_data = fetch_forward_metrics(
    self.fmp_client,
    ticker,
    data.get("current_price"),
    enterprise_value=data.get("enterprise_value"),  # from key_metrics_ttm
)
data["forward_pe"] = forward_data.get("forward_pe")
data["ntm_eps"] = forward_data.get("ntm_eps")
data["pe_source"] = forward_data.get("pe_source")
data["analyst_count_eps"] = forward_data.get("analyst_count")
data["forward_ev_ebitda"] = forward_data.get("forward_ev_ebitda")
data["forward_ev_sales"] = forward_data.get("forward_ev_sales")
# ... existing pe_source fallback logic unchanged
```

**Ensure `enterprise_value` is available**: Check that the quality signals block (which fetches `key_metrics_ttm`) runs BEFORE the forward metrics block. Currently quality signals are at lines ~636-677 and forward P/E is at ~613-634 — so we need to **reorder**: move `key_metrics_ttm` extraction (or at least the `enterpriseValueTTM` extraction) before the forward metrics call. Alternatively, do a separate `key_metrics_ttm` fetch earlier in the enrichment.

Looking at the current flow:
- Lines 578-611: ratios_ttm → extracts pe_ratio, pb_ratio, etc.
- Lines 613-634: forward P/E
- Lines 636-677: quality signals → fetches key_metrics_ttm + income_statement + cash_flow

Option: Extract `enterpriseValueTTM` during the ratios_ttm block (it might be in ratios_ttm), OR move the key_metrics_ttm fetch before forward metrics. The simplest: add `enterpriseValueTTM` extraction to the ratios_ttm block, since `ratios_ttm` may contain it. If not, do a standalone `key_metrics_ttm` fetch before the forward metrics block.

### 3. Backend: `services/stock_service.py` — extract forward PEG

In the ratios_ttm enrichment block (lines ~578-611), add:

```python
data["forward_peg"] = pick_value(ratios_record, "forwardPriceToEarningsGrowthRatioTTM")
```

This uses the FMP-native forward PEG field from `ratios_ttm` — same field used in peer comparison. No computation needed.

### 4. Frontend: types + display (minimal)

The stock lookup primarily serves the AI via MCP tool response. The forward metrics will be in the enriched data dict → included in the agent snapshot → visible to the AI. No frontend display changes needed unless the user wants them shown on the Snapshot tab.

If frontend display is desired later, add to `types.ts`:
```typescript
forwardEvEbitda?: number
forwardEvSales?: number
forwardPeg?: number
```

### 5. Tests

- Update `tests/services/test_stock_service_provider_registry.py` or relevant stock service test:
  - Mock the forward metrics response
  - Verify `forward_ev_ebitda`, `forward_ev_sales`, `forward_peg` are in enriched data
- Add unit tests for `fetch_forward_metrics()` in `tests/utils/test_forward_pe.py`:
  - Happy path: returns all three forward metrics
  - Missing enterprise_value: forward_ev_* are None, forward_pe still works
  - Estimate fetch failure: all forward metrics None

## Edge Cases

- `enterprise_value` not available (key_metrics_ttm failed) → forward_ev_ebitda and forward_ev_sales are None, forward P/E still works
- No analyst estimates → all forward metrics None
- Negative EBITDA/revenue estimates → respective forward metric is None
- Forward PEG unavailable in ratios_ttm → None

## What Does NOT Change

- `fetch_forward_pe()` — kept for backward compatibility
- Peer comparison (`fmp/tools/peers.py`) — unchanged, has its own computation path
- Quality signals — unchanged
- Frontend Snapshot tab — no display changes (data flows through MCP tool for AI)

## Files to Modify

| File | Change |
|------|--------|
| `utils/fmp_helpers.py` | Add `fetch_forward_metrics()` |
| `services/stock_service.py` | Replace `fetch_forward_pe()` with `fetch_forward_metrics()`, extract forward PEG from ratios, ensure EV available |
| `tests/utils/test_forward_pe.py` | Tests for `fetch_forward_metrics()` |
| `tests/services/test_stock_service_*.py` | Update mocks for new enrichment fields |

## Verification

1. `pytest tests/utils/test_forward_pe.py -q` — passes
2. `pytest tests/services/ -q` — passes
3. MCP tool: `analyze_stock(symbol="AAPL")` → response includes `forward_ev_ebitda`, `forward_ev_sales`, `forward_peg`

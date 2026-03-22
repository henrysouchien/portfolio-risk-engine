# Forward P/E Standardization (System-Wide)

## Context

All P/E ratios currently surfaced in the system are **TTM (Trailing Twelve Month)**. The goal is to switch to **forward P/E** as the primary metric, computed from `current_price ÷ consensus forward EPS` via FMP's `analyst_estimates` endpoint. TTM remains as a labeled fallback when analyst estimates are unavailable.

FMP does not provide a direct `forwardPE` field — we must compute it ourselves from `analyst_estimates` → `epsAvg`.

**Metric definition**: We use **FY1 Forward P/E** (next unreported fiscal year's consensus annual EPS), not true rolling NTM. True NTM would require summing 4 quarterly estimates which often have coverage gaps. FY1 is what most screeners (Bloomberg, FactSet) show as "forward P/E" and is robust. Label: **"Fwd P/E"**.

**Forward period selection**: Use the FMP `analyst_estimates` fiscal period dates. Sort by `date` ascending, pick the first period whose fiscal end date is **after the company's last reported fiscal date**. The last reported fiscal date is obtained by fetching `income_statement` (quarterly, limit=1) and reading its `date` field — this aligns with the existing convention in `fmp/scripts/snapshot_estimates.py`. If the last reported date is unavailable, fall back to `date.today()` as a reasonable proxy. If no qualifying estimate period exists, return `unavailable`.

---

## Audit Summary

### Backend P/E touchpoints (3 sites — all TTM today):

| Site | File | What it does |
|------|------|-------------|
| Stock Lookup enrichment | `services/stock_service.py:387-427` | Sector P/E from `sector_pe_snapshot` → `sector_avg_pe`. Stock P/E from `ratios_ttm` → `pe_ratio` with 4-field fallback chain |
| Sector overview | `fmp/tools/market.py:740-947` | Sector/industry P/E from snapshot + per-stock TTM. `_compute_pe_premium()`, `_classify_verdict()` |
| Peer comparison | `fmp/tools/peers.py:30-59` | `DEFAULT_PEER_METRICS` includes `priceToEarningsRatioTTM`, label "P/E Ratio" |

### Frontend P/E touchpoints (5 sites — all consume backend TTM):

| Site | File | What it does |
|------|------|-------------|
| Data transform | `StockLookupContainer.tsx:421` | Maps `pe_ratio` → `peRatio` |
| Sector avg transform | `StockLookupContainer.tsx:476` | Maps `sector_avg_pe` → `sectorAvgPE` |
| Main display | `SnapshotTab.tsx:333-354` | Shows "P/E Ratio" with N/A for negative earnings |
| Valuation scoring | `SnapshotTab.tsx:145-148` | `peScore = clamp(100 - peRatio/40 * 100)` |
| Peer extraction + ranking | `SnapshotTab.tsx:299`, `helpers.ts:3-20` | Extracts `priceToEarningsRatioTTM` from peer data. `LOWER_IS_BETTER_METRICS` + `NON_POSITIVE_EXCLUDES_RANKING` |

### Additional touchpoints (no change needed):

| Site | Notes |
|------|-------|
| `sector_avg_pe` / `sectorAvgPE` | Stays TTM — FMP doesn't provide forward sector P/E. Will be labeled "(TTM)" |
| `core/stock_flags.py` | No P/E flags |
| Factor models | No P/E input |
| Holdings table | No P/E column |
| Market intelligence events | No P/E |
| `mcp_tools/stock.py` / `StockAnalysisResult` | Does NOT call `enrich_stock_data()` — goes through `StockAnalysisResult.to_api_response()`. **Out of scope** — MCP stock tool does not surface P/E today and won't in this change |

### Data source note

Stock lookup's profile and quote come from **registry providers** (not `self.fmp_client` directly), but the forward P/E computation specifically requires FMP's `analyst_estimates` endpoint. The pure `compute_forward_pe()` function is provider-agnostic; only `fetch_forward_pe()` is FMP-specific.

---

## Design Decisions

1. **Utility location**: `utils/fmp_helpers.py` — already has `parse_fmp_float()`, `pick_value()`, `first_dataframe_record()`. Cross-cutting, used by both `services/` and `fmp/tools/`.

2. **New fields alongside existing**: Add `forward_pe`, `pe_source`, `ntm_eps` alongside existing `pe_ratio` (kept as TTM fallback). Frontend maps `forward_pe ?? pe_ratio` into `peRatio` display field.

3. **Caching**: `analyst_estimates` already registered in `fmp/registry.py` with 24h TTL cache. No new caching needed.

4. **Peer comparison**: Add `forwardPE` as a computed metric to peer results. Fetch estimates per peer in parallel (cached). Label TTM as `"P/E (TTM)"`, forward as `"Fwd P/E"`.

5. **Sector benchmarks**: Stay TTM (FMP doesn't provide forward sector P/E). Labeled `"(TTM)"` where displayed.

6. **Frontend**: Dynamic label based on `peSource` — `"Fwd P/E"` or `"P/E (TTM)"`. Single metric, not side-by-side.

7. **Best-effort estimates**: Missing analyst estimates must **never** fail the parent fetch. In `market.py` and `peers.py`, estimate fetch failures silently suppress forward P/E for that ticker — the ticker still appears with TTM ratios.

---

## Fallback State Model

Explicit state machine for `pe_source`:

```
analyst_estimates available?
  ├─ YES → epsAvg > 0?
  │   ├─ YES → pe_source = "forward", forward_pe = price / epsAvg
  │   └─ NO  → pe_source = "negative_forward_earnings", forward_pe = None
  │            → frontend shows: fall back to TTM pe_ratio if available
  │            → if TTM also negative: show "N/A" (existing SnapshotTab logic)
  └─ NO  → pe_source = "unavailable", forward_pe = None
           → frontend shows: pe_ratio (TTM) with label "P/E (TTM)"
           → if TTM also missing: show "—"
```

The `pe_source` field is always set. Frontend logic:
- Display value: `forward_pe ?? pe_ratio` (into `peRatio` prop)
- Display label: `pe_source === "forward"` → `"Fwd P/E"`, else `"P/E (TTM)"`
- Negative earnings: existing SnapshotTab check (`peRatio < 0` → "N/A") continues to work

---

## Implementation Steps

### Step 1: Centralized utility — `utils/fmp_helpers.py`

Add three functions:

**`compute_forward_pe(current_price, estimates, last_reported_fiscal_date=None)`** — Pure function
- Sort estimates by `date` ascending
- Determine cutoff: if `last_reported_fiscal_date` provided, use it; otherwise fall back to `date.today()` (callers should provide the real date when possible)
- Find first estimate where fiscal `date` > cutoff
- If no qualifying period → return `{forward_pe: None, pe_source: "unavailable"}`
- Parse `epsAvg` via `parse_fmp_float()`. If None or ≤ 0 → return `{forward_pe: None, pe_source: "negative_forward_earnings"}`
- Compute `forward_pe = round(current_price / epsAvg, 2)`
- Return `{forward_pe, ntm_eps: epsAvg, pe_source: "forward", analyst_count: numAnalystsEps, fiscal_period: date_str}`

**`_get_last_reported_fiscal_date(fmp_client, ticker)`** — Helper
- Calls `fmp_client.fetch("income_statement", symbol=ticker, period="quarter", limit=1)`
- Extracts the `date` field from the first record → returns as `str` or `None`
- Cached via the existing FMP Parquet cache (income_statement is HASH_ONLY)
- On failure → returns `None` (caller falls back to `date.today()`)

**`fetch_forward_pe(fmp_client, ticker, current_price)`** — Convenience wrapper
- Calls `_get_last_reported_fiscal_date()` to get cutoff date
- Calls `fmp_client.fetch("analyst_estimates", symbol=ticker, period="annual", limit=4)`
- Converts DataFrame to records
- Delegates to `compute_forward_pe(current_price, records, last_reported_fiscal_date)`
- Catches all exceptions → returns `{forward_pe: None, pe_source: "unavailable"}`

### Step 2: Backend — `services/stock_service.py`

After existing `ratios_ttm` block (~line 453), add forward P/E enrichment:
- Call `fetch_forward_pe(self.fmp_client, ticker, data.get("current_price"))`
- Set `data["forward_pe"]`, `data["ntm_eps"]`, `data["pe_source"]`, `data["analyst_count_eps"]`
- If `pe_source != "forward"` and `data.get("pe_ratio")` exists: set `data["pe_source"] = "ttm"`
- If neither forward nor TTM P/E available: set `data["pe_source"] = "unavailable"`

### Step 3: Backend — `fmp/tools/market.py`

In `_fetch_symbol_data()` (~line 890): add **best-effort** `analyst_estimates` + `income_statement` (quarterly, limit=1) fetches alongside profile+ratios. Wrap each in try/except — estimate/income failure returns None, does not mark ticker as failed. The `income_statement` fetch provides `last_reported_fiscal_date` for correct FY1 period selection.

In per-symbol processing loop (~line 813):
- Extract `last_reported_fiscal_date` from `income_statement` response
- Compute forward P/E using `compute_forward_pe(price, estimates, last_reported_fiscal_date)` where price comes from profile
- Use forward P/E as `stock_pe` when available, fall back to TTM `priceToEarningsRatioTTM`
- Add `pe_source` to comparison result
- Add `benchmark_pe_source: "ttm"` (sector/industry benchmarks always TTM)

### Step 4: Backend — `fmp/tools/peers.py`

- Replace `_fetch_ratios()` with `_fetch_ratios_and_estimates()` — fetches `ratios_ttm` + **best-effort** `analyst_estimates` + `profile` (for price) per ticker. Estimate or profile failure → `estimates=None`/`price=None`, ratios still returned.
- Price source for forward P/E: extract `price` from the FMP profile response (profile is already fetched in `market.py`'s flow; for `peers.py`, add a `profile` fetch to `_fetch_ratios_and_estimates()` — it's a cached call). Alternative: use `ratios_ttm` → `peRatioTTM * earningsPerShareTTM` to back-calculate price, but profile is cleaner.
- Compute `forwardPE` for each peer: call `compute_forward_pe(price, estimates, last_reported_date)` where `last_reported_date` comes from `income_statement` (quarterly, limit=1) fetched alongside the other data in `_fetch_ratios_and_estimates()`. If unavailable, pass `None` (falls back to `date.today()` in the utility).
- Inject computed `forwardPE` into the ratios dict before building comparison table. If `forwardPE` is None for a peer, the cell shows "—" (existing `formatPeerMetricValue` handles null).
- Add to `DEFAULT_PEER_METRICS`: `"forwardPE"` (before `priceToEarningsRatioTTM`)
- Add to `METRIC_LABELS`: `"forwardPE": "Fwd P/E"`, rename existing to `"priceToEarningsRatioTTM": "P/E (TTM)"`

### Step 5: Frontend — Types + Container + Display

**`types.ts`**: Add `peSource?: 'forward' | 'ttm' | 'negative_forward_earnings' | 'unavailable'`, `ntmEps?: number`, `analystCountEps?: number`

**`StockLookupContainer.tsx:421`**: Map `forward_pe ?? pe_ratio` → `peRatio`, add `peSource` mapping

**`SnapshotTab.tsx:299`**: Update peer metric extraction to prefer `forwardPE` with TTM fallback:
```typescript
pe: extract("forwardPE") ?? extract("priceToEarningsRatioTTM"),
```

**`SnapshotTab.tsx:333-354`**: Dynamic label — `peSource === "forward"` → `"Fwd P/E"`, else `"P/E (TTM)"`. Update tooltip to describe source.

**`helpers.ts`**: Add `"forwardPE"` to both `LOWER_IS_BETTER_METRICS` and `NON_POSITIVE_EXCLUDES_RANKING`

### Step 6: Tests

- `tests/utils/test_forward_pe.py` — Unit tests for `compute_forward_pe()`:
  - Normal case: future annual estimate with positive EPS
  - No future period: returns `pe_source="unavailable"`
  - Negative forward EPS: returns `pe_source="negative_forward_earnings"`
  - Empty estimates list / None
  - Missing/None price
  - Multiple future periods (picks first unreported)
  - Zero EPS edge case
- Integration tests in existing suites:
  - `tests/services/test_stock_service_provider_registry.py` — mock `analyst_estimates` response
  - `tests/mcp_tools/test_market.py` — mock estimates in sector overview
  - `tests/mcp_tools/test_peers.py` — mock estimates in peer comparison

---

## File Change Summary

| File | Change |
|------|--------|
| `utils/fmp_helpers.py` | Add `compute_forward_pe()` + `fetch_forward_pe()` |
| `services/stock_service.py` | Forward P/E enrichment block after ratios_ttm |
| `fmp/tools/market.py` | Best-effort estimates fetch + forward P/E in sector overview |
| `fmp/tools/peers.py` | Best-effort estimates fetch + `forwardPE` metric + label updates |
| `frontend/.../types.ts` | Add `peSource`, `ntmEps`, `analystCountEps` |
| `frontend/.../StockLookupContainer.tsx` | Map `forward_pe` → `peRatio` with fallback |
| `frontend/.../SnapshotTab.tsx` | Dynamic P/E label + tooltip + peer extraction fallback |
| `frontend/.../helpers.ts` | Add `forwardPE` to `LOWER_IS_BETTER_METRICS` + `NON_POSITIVE_EXCLUDES_RANKING` |
| `tests/utils/test_forward_pe.py` | New — unit tests for utility |

---

## Verification

1. **Unit tests**: Run `pytest tests/utils/test_forward_pe.py` — all pass
2. **Backend integration**: Run `pytest tests/services/ tests/mcp_tools/` — no regressions
3. **MCP tool test**: Call `compare_peers(symbol="AAPL")` — response should include `forwardPE` metric with label "Fwd P/E"
4. **MCP tool test**: Call `get_sector_overview(symbols="AAPL")` — stock comparison should show forward P/E with `pe_source`
5. **Frontend**: Load stock lookup for AAPL — should show "Fwd P/E" label. Load a small-cap without estimates — should fall back to "P/E (TTM)"
6. **Full test suite**: `pytest` — no regressions

Note: `mcp_tools/stock.py` / `analyze_stock()` is **out of scope** — it does not call `enrich_stock_data()` and does not surface P/E today. Forward P/E for the MCP stock tool would require a separate change to `StockAnalysisResult`.

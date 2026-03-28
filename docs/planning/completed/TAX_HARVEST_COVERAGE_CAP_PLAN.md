# Tax Harvest Snapshot — Coverage-Based Candidate Cap

## Context

The tax harvest snapshot caps `top_candidates` at 5 tickers (hardcoded `[:5]` in `_build_tax_harvest_snapshot()`). This is arbitrary — in a concentrated portfolio, 3 tickers might cover everything; in a diversified one, 5 might miss the majority of harvestable losses. The cap needs to be smart about what matters, not just take the first N.

## Design

**Coverage-based cap with hard ceiling and wash sale safety net.**

### Algorithm

1. **Sort** aggregated tickers by |total_loss| descending (already done)
2. **Walk the list**, accumulating loss until cumulative ≥ 90% of total harvestable loss
3. **Include wash sale tickers** not already in the list (actionable regardless of size)
4. **Hard cap** at 10 tickers — applied to step 2 (coverage pass) only. Wash sale tickers from step 3 can push above 10. In practice this is bounded because wash sale tickers are a small subset.

**Priority rule**: The hard cap protects against extreme diversification in the coverage pass, but wash sale tickers always get included — they're the actionable warning the user needs to see. If a portfolio somehow has 20 wash sale tickers, all 20 appear. This is acceptable because the wash sale count is bounded by 30-day buy activity, which is naturally small.

### Constants
- `COVERAGE_TARGET = 0.90`
- `MAX_CANDIDATES = 10`

### Why 10 (not 15 or 20)
With coverage-based selection, most portfolios will return 3-7 tickers. The cap only triggers for very diversified portfolios where no single ticker dominates. 10 is enough headroom without bloating the agent context.

## Files Modified

| File | Change |
|------|--------|
| `mcp_tools/tax_harvest.py` | Replace `[:5]` with coverage-based logic in `_build_tax_harvest_snapshot()`. Also remove `[:5]` truncation on `wash_sale_tickers` list (~line 870) so the warnings section isn't artificially capped. |
| `frontend/.../TaxHarvestTool.tsx` | Dynamic label — "N tickers across M lots" instead of "Top 5 tickers from M lots" |
| `tests/mcp_tools/test_tax_harvest_agent_snapshot.py` | Update tests that assert `len(top_candidates) == 5`. Add 6 tests: coverage stops early, wash sale safety net, hard cap on coverage pass, wash sale bypasses cap, wash_sale_tickers field uncapped, empty candidates. |

## Implementation

### Backend (`_build_tax_harvest_snapshot`, ~line 850)

Replace:
```python
for agg in sorted(ticker_agg.values(), key=lambda a: abs(a["total_loss"]), reverse=True)[:5]:
```

With:
```python
COVERAGE_TARGET = 0.90
MAX_CANDIDATES = 10

sorted_aggs = sorted(ticker_agg.values(), key=lambda a: abs(a["total_loss"]), reverse=True)
abs_total = abs(total_loss) if total_loss else 0

# Pass 1: coverage-based selection
selected = []
cumulative = 0.0
for agg in sorted_aggs:
    if len(selected) >= MAX_CANDIDATES:
        break
    selected.append(agg)
    cumulative += abs(agg["total_loss"])
    if abs_total > 0 and cumulative / abs_total >= COVERAGE_TARGET:
        break

# Pass 2: wash sale safety net — add any wash-sale tickers not already selected
# No cap here — wash sale tickers always included (bounded by 30-day buy activity)
selected_tickers = {a["ticker"] for a in selected}
for agg in sorted_aggs:
    if agg["ticker"] not in selected_tickers and agg["wash_sale_risk"]:
        selected.append(agg)
        selected_tickers.add(agg["ticker"])

# Build output
top_candidates = []
for agg in selected:
    ...existing serialization...
```

### Backend — `wash_sale_tickers` truncation (~line 870)

Remove the `[:5]` on the `wash_sale_tickers` list in the snapshot so the warnings section shows all flagged tickers, not just the first 5. The `top_candidates` list already includes wash sale tickers via the safety net pass; the `wash_sale_tickers` field in the snapshot should be consistent.

### Frontend (`TaxHarvestTool.tsx`, ~line 436)

Change label from:
```
`Top ${candidateRows.length} ticker${...} from ${formatLotsLabel(...)}`
```
To:
```
`${candidateRows.length} ticker${...} across ${formatLotsLabel(...)}`
```

Drop "Top" — with coverage-based selection, the list isn't arbitrarily truncated, so "Top N" is misleading.

### Tests (`tests/mcp_tools/test_tax_harvest_agent_snapshot.py`)

Update existing tests that assert `len(top_candidates) == 5` to use coverage-based expectations. Add new tests:
- **Coverage stops early**: 2 tickers cover 95% → only 2 returned (not 10)
- **Wash sale safety net**: small-loss ticker with wash sale risk included even after coverage met and even if coverage pass already returned 10
- **Hard cap on coverage pass**: 15 tickers all with equal loss, no wash sale → capped at 10
- **Wash sale bypasses cap**: 10 coverage tickers + 2 wash sale tickers → 12 total (wash sale not capped)
- **wash_sale_tickers field uncapped**: 8 wash sale tickers in result → all 8 in snapshot (was truncated to 5)
- **Empty**: no candidates → empty list (existing test, verify not broken)

## Verification

1. Run scanner with real portfolio — verify candidates list adapts to portfolio concentration
2. Check that wash sale tickers appear even if they're small losses
3. Check that coverage pass doesn't exceed 10, but wash sale tickers can push above 10
4. MCP tool: `suggest_tax_loss_harvest(format="agent")` — verify snapshot shape unchanged, just more rows
5. Run backend tests: `pytest tests/mcp_tools/test_tax_harvest_agent_snapshot.py -v`

# Tax Harvest — Remove Wash Sale Safety Net from Coverage Cap

## Context

The coverage-based candidate cap (committed `084bc75a`) has two passes:
1. Coverage pass: walk tickers by |loss| until 90% covered, cap at 10
2. Wash sale safety net: add any wash sale tickers not already in the list (uncapped)

Pass 2 is pulling in tiny losses like AAPL (-$19) and DHT (-$5) just because they have wash sale risk. These aren't meaningful harvest candidates — the user doesn't care about a $5 loss. The coverage pass already surfaces big losers with wash sale risk (like DSU at -$7,065) because they're large losses.

## Design

**Remove the wash sale safety net pass. Keep everything else unchanged.**

The candidates list is purely coverage-based — the biggest losses that cover 90% of total harvestable losses, capped at 10. If a big loser happens to have wash sale risk, it shows up naturally with a "Risk" badge. Small wash sale tickers no longer clutter the list.

The `wash_sale_tickers` field and Wash Sale Warnings section remain unchanged — the full list of flagged tickers is always available for reference.

## Files Modified

| File | Change |
|------|--------|
| `mcp_tools/tax_harvest.py` | Remove wash sale safety net pass (~lines 950-954) in `_build_tax_harvest_snapshot()` |
| `tests/mcp_tools/test_tax_harvest_agent_snapshot.py` | Remove/update tests that assert wash sale safety net behavior (wash sale bypasses cap, wash sale safety net test). Keep coverage and cap tests. |

No frontend changes — candidates table and Wash Sale Risk column stay as-is.

## Implementation

### Backend (`_build_tax_harvest_snapshot`, ~lines 950-954)

Delete:
```python
selected_tickers = {agg["ticker"] for agg in selected}
for agg in sorted_aggs:
    if agg["ticker"] not in selected_tickers and agg["wash_sale_risk"]:
        selected.append(agg)
        selected_tickers.add(agg["ticker"])
```

The coverage pass (lines 940-948) remains unchanged.

### Tests

- **Rewrite** `test_snapshot_wash_sale_safety_net` → `test_snapshot_wash_sale_below_coverage_excluded`: small wash sale ticker below coverage threshold is NOT in top_candidates (inverse of old behavior). Fixture must have BOTH: `wash_sale_risk=True` on the candidate lot AND a matching `wash_sale_warnings` entry for the ticker. Assert: ticker NOT in `top_candidates`, ticker IS in `wash_sale_tickers`.
- **Rewrite** `test_snapshot_wash_sale_bypasses_coverage_cap` → `test_snapshot_wash_sale_does_not_bypass_cap`: 10 coverage tickers (no wash sale risk) + 1 wash sale ticker with small loss below top-10 cutoff. Fixture must have BOTH: `wash_sale_risk=True` on the candidate lot AND a matching `wash_sale_warnings` entry. Assert: exactly 10 in `top_candidates` (not 11), wash sale ticker NOT in `top_candidates`, wash sale ticker IS in `wash_sale_tickers`.
- **Keep** all other tests (coverage stops early, hard cap, wash_sale_tickers uncapped, empty, etc.)
- **Update** `test_snapshot_top_candidates_cover_90_pct_of_losses` if it asserts wash sale tickers in top_candidates

## Verification

1. MCP tool: `suggest_tax_loss_harvest(format="agent")` — verify top_candidates is coverage-only (no tiny wash sale tickers like AAPL/-$19 or DHT/-$5), but big losers with wash sale risk (DSU) still appear
2. MCP tool: verify `wash_sale_tickers` field still contains all 7 flagged tickers
3. Browser: candidates table shows fewer rows (coverage-only), big losers with Risk badges still present
4. Tests: `pytest tests/mcp_tools/test_tax_harvest_agent_snapshot.py -v`

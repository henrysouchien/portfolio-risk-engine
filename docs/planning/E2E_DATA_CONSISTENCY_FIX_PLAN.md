# E2E Data Consistency Fix Plan

**Status**: Partially complete — Steps 1-4 done (prior batches), Steps 5-6 deferred
**Updated**: 2026-03-15
**Source**: `FRONTEND_E2E_FINDINGS_2026_03_14.md` (16 issues, 2 sessions)

---

## Completed (Prior Batches)

Steps 1-4 from original plan (F3/F4/F5 label fixes, portfolio value subtitle) — all committed.

---

## Remaining Issues (N2, N5, N7 from Re-Audit)

### N7 — Mock data after re-auth (Quick — ~10 min)

**Root cause:** Scheduler's `hasPrefetchedForPortfolio` ref is never reset on re-auth. Same portfolio ID → scheduler skips prefetches → `invalidateQueries` marks queries stale but nothing triggers refetch → data is `undefined` → dashes. AI Recommendations works because it uses direct `useQuery` (not `useDataSource`), bypassing the scheduler.

**File:** `frontend/packages/connectors/src/resolver/scheduler.ts`

Add a reset when `enabled` transitions false→true:
```typescript
const prevEnabledRef = useRef(false);

useEffect(() => {
  if (enabled && !prevEnabledRef.current) {
    hasPrefetchedForPortfolio.current = null;
  }
  prevEnabledRef.current = enabled;
}, [enabled]);
```

**Tests:** Verify existing scheduler tests pass. Manual: sign out → sign in → Dashboard shows real data immediately.

---

### N5 — Trading analysis / Income 500 for single-account (Medium — ~30 min)

**Root cause:** `load_from_store_for_portfolio()` filters transactions to a single account. Zero matches → `"No transaction data found"` → MCP returns `{"status": "error"}` → REST route promotes ALL error-status to HTTP 500. "No data" is treated as a server error.

**Part A — Graceful empty in MCP tools:**

**File:** `mcp_tools/trading_analysis.py` (~line 201)
When `fifo_transactions` is empty after portfolio filtering, return success with empty data:
```python
if not fifo_transactions:
    return {
        "status": "success",
        "summary": None,
        "income_analysis": None,
        "message": "No transaction data available for this portfolio scope.",
    }
```

**File:** `mcp_tools/income.py` (~line 71)
Same pattern — return success with zero values instead of raising ValueError:
```python
if not positions_for_income:
    return {
        "status": "success",
        "total_projected_annual_income": 0,
        "portfolio_yield_on_value": 0,
        "positions": [],
        "message": "No positions available for income projection.",
    }
```

**Part B — Route error handling (NO 404):**

Codex review: Frontend `HttpClient` throws on non-2xx responses. The income resolver catches thrown errors and falls back to a synthetic 1.5% estimate (`registry.ts:810`). Using 404 would trigger this synthetic path → showing fake positive income instead of zero.

**Fix:** Keep routes returning 200 for all MCP success responses. Only promote to 500 for genuine `status: "error"` results where the error is NOT a "no data" condition. For "no data" conditions, the MCP tool already returns `status: "success"` (Part A above), so the route passes it through as 200.

**File:** `routes/trading.py` (~line 105) — No change needed if Part A works correctly (MCP returns success, not error).
**File:** `routes/income.py` (~line 30) — Same.

**Tests:** Test MCP tools return success (not error) when portfolio has no transactions/positions. Frontend components handle null `summary` / zero income gracefully (verified: `TradingPnLCard` branches on truthiness of `summary`, `IncomeProjectionCard` handles zero values).

---

### N2 — Holdings empty when IBKR Gateway down (Deferred — needs architectural decision)

**Root cause:** When IBKR Gateway is down, `PositionService.__init__()` doesn't register the `ibkr` provider → `get_all_positions()` never fetches IBKR positions, not even from DB cache. Dashboard works because it reads positions directly from DB via `db_client.get_portfolio_positions()` (different code path).

**Why a quick fix doesn't work (Codex findings):**
1. **Double-counting** — When IBKR gateway is down, `partition_positions()` keeps IBKR positions from aggregators (SnapTrade/Plaid) as fallback. DB-cached `ibkr` rows would duplicate since SnapTrade and IBKR use different `account_id` formats (UUID vs native), making dedup unreliable.
2. **Raw DB rows lack price/value** — `_load_cached_positions()` only does raw DB read; price normalization happens afterward in a separate pipeline step. Appending raw rows before consolidation breaks `PositionsData.from_dataframe()` which requires finite `value` data.
3. **Staleness metadata** — `get_all_positions()` tracks freshness per-provider via `_cache_metadata`. Appending fallback frames outside this structure means stale indicators won't display.

**Current mitigation:** Since we deactivated the SnapTrade IBKR account, this issue only affects users who have IBKR as their sole provider for an account AND the gateway is down. Accepted degraded behavior when gateway is down:
- **Overview metrics** (risk score, returns, Sharpe, concentration) — still load via DB-backed portfolio-summary/risk/performance path
- **Holdings page + DashboardHoldingsCard** — show empty ("No Data") since they go through `positions-enriched` resolver → `PositionService`
- **DashboardIncomeCard** — degrades to synthetic 1.5% estimate (income-projection resolver catches backend failure and falls back to frontend estimate from store-backed portfolio holdings)
- **No live IBKR holdings drilldown** while gateway is down

**Proper fix options (for later):**
- **Option A**: Make `_load_enriched_positions()` (the REST route) use the same DB-direct path as the portfolio-summary resolver when the live provider is unavailable
- **Option B**: Register a "db-cached" provider in `PositionService` for unavailable providers that goes through the full normalization pipeline
- **Option C**: Accept the limitation as documented above

**Status:** Deferred. Degraded behavior is understood and acceptable — overview metrics work, holdings/drilldown do not.

---

## Implementation Order

1. **N7** — scheduler reset (~10 min, 1 file, lowest risk)
2. **N5** — graceful empty (~30 min, 2 files, medium risk)
3. **N2** — deferred (architectural decision needed)

## Files Summary

| File | N7 | N5 | N2 |
|------|----|----|-----|
| `frontend/packages/connectors/src/resolver/scheduler.ts` | Edit | | |
| `mcp_tools/trading_analysis.py` | | Edit | |
| `mcp_tools/income.py` | | Edit | |
| N2 deferred | | | — |

# MCP Positions Enhancement: Sector + P&L in Agent Format

**Date**: 2026-02-27
**Status**: COMPLETE — implemented by Codex, live-tested via MCP (2026-02-27)
**Parent doc**: `FRONTEND_PHASE2_WORKING_DOC.md`

## Context

The Holdings Enrichment plan (`FRONTEND_HOLDINGS_ENRICHMENT_PLAN.md`) adds two new backend capabilities:
1. `GET /api/positions/holdings` — monitor view with P&L for the frontend
2. `PortfolioService.enrich_positions_with_sectors()` — FMP profile lookup per ticker

These capabilities are currently only wired to the REST endpoint for frontend use. The MCP `get_positions(format="agent")` tool — which Claude uses for portfolio analysis — has **none of this data**. The agent snapshot shows exposure, leverage, and top holdings, but:
- **No sector data** — Claude can't answer "what sectors am I exposed to?" without cross-referencing FMP profiles manually
- **No P&L data** — Claude can't see unrealized gains/losses, winners/losers, or cost basis coverage
- **No sector flags** — no warnings for sector concentration or low diversification
- **No P&L flags** — no warnings for large unrealized losses or missing cost basis

**Goal**: Enhance `get_positions(format="agent")` to include sector breakdown, P&L summary, and 4 new interpretive flags — reusing the existing `enrich_positions_with_sectors()` and `to_monitor_view()` infrastructure.

---

## Current Agent Format Output

```
{
  snapshot:      { total_value, position_count, leverage, long/short/gross/net exposure, by_type, by_currency }
  top_holdings:  [ { ticker, weight_pct, value, type } ]   <- no sector, no P&L
  flags:         [ concentration, leverage, cash_drag, margin, stale_data, ... ]  <- 12 types
  exposure:      { by_type, by_currency }                  <- no by_sector
  cache_info, provider_status
}
```

## Enhanced Agent Format Output

```
{
  snapshot:      { ...existing..., }                       <- unchanged
  pnl_summary:  { total_pnl_usd, winner_count, loser_count, cost_basis_coverage_pct,
                   top_winner: {ticker, pnl_usd, pnl_percent},
                   top_loser:  {ticker, pnl_usd, pnl_percent} }    <- NEW
  top_holdings:  [ { ticker, weight_pct, value, type,
                     sector, pnl_usd, pnl_percent } ]              <- ENRICHED
  flags:         [ ...existing 12...,
                   sector_concentration, low_sector_diversification,
                   large_unrealized_loss, low_cost_basis_coverage ]  <- 4 NEW
  exposure:      { by_type, by_currency,
                   by_sector: { "Technology": {value, count, weight_pct}, ... } }  <- NEW
  cache_info, provider_status
}
```

---

## Implementation Plan

### Step 1: Enhance `_build_agent_response()` in `mcp_tools/positions.py`

**Data flow**: Get monitor payload (P&L) -> enrich with sectors -> extract summaries -> build response.

```python
def _build_agent_response(result, cache_info, file_path=None):
    snapshot = result.get_exposure_snapshot()
    top_holdings = result.get_top_holdings(10)

    # 1. Get monitor payload for P&L data (public API, already handles edge cases)
    monitor_payload = result.to_monitor_view(by_account=False)
    monitor_positions = monitor_payload.get("positions", [])
    monitor_summary = monitor_payload.get("summary", {})

    # 2. Enrich with sector data via PortfolioService
    from services.portfolio_service import PortfolioService
    portfolio_svc = PortfolioService()
    portfolio_svc.enrich_positions_with_sectors(monitor_payload)
    # monitor_positions now have "sector" field

    # 3. Build new data from enriched monitor positions
    by_sector = _build_sector_breakdown(monitor_positions)
    pnl_summary = _build_pnl_summary(monitor_positions, monitor_summary)
    _enrich_top_holdings(top_holdings, monitor_positions)

    # 4. Generate flags with new kwargs
    flags = generate_position_flags(
        result.data.positions, result.total_value, cache_info,
        by_sector=by_sector,
        monitor_positions=monitor_positions,
    )

    exposure = {
        "by_type": snapshot.pop("by_type", {}),
        "by_currency": snapshot.pop("by_currency", {}),
        "by_sector": by_sector,
    }

    return {
        "status": "success",
        "format": "agent",
        "snapshot": snapshot,
        "pnl_summary": pnl_summary,
        "top_holdings": top_holdings,
        "flags": flags,
        "exposure": exposure,
        "cache_info": cache_info,
        "provider_status": _build_provider_status(cache_info),
        "file_path": file_path,
    }
```

**New helper functions** (same file):

**`_build_sector_breakdown(monitor_positions)`** — Scan enriched positions, group by sector. Return `{sector: {value, count, weight_pct}}` sorted by value descending. Skip cash/CUR: positions. "Unknown" for positions without sector data.

**`_build_pnl_summary(monitor_positions, monitor_summary)`** — Extract from monitor data:
- `total_pnl_usd` from `monitor_summary.portfolio_totals_usd.total_pnl_usd`
- Count winners (pnl > 0) and losers (pnl < 0)
- `cost_basis_coverage_pct`: % of positions with non-null cost_basis
- `top_winner` / `top_loser`: ticker + pnl_usd + pnl_percent for biggest winner/loser
- `no_cost_basis_count`: positions missing cost basis

**`_enrich_top_holdings(top_holdings, monitor_positions)`** — Mutate top_holdings in place, adding `sector`, `pnl_usd`, `pnl_percent` from monitor_positions via ticker-keyed lookup.

### Step 2: Add 4 new flags to `core/position_flags.py`

Extend `generate_position_flags()` with two new keyword-only args (backward compatible):

```python
def generate_position_flags(
    positions, total_value, cache_info,
    *, by_sector=None, monitor_positions=None,  # NEW -- keyword-only, default None
):
```

**New flags:**

| Flag | Severity | Condition | Message example |
|------|----------|-----------|-----------------|
| `sector_concentration` | warning | Any sector (except "Unknown") > 40% of exposure | "Technology is 52% of exposure" |
| `low_sector_diversification` | info | 2 or fewer real sectors | "Portfolio concentrated in 2 sectors: Technology, Healthcare" |
| `large_unrealized_loss` | warning | Any position P&L < -20% AND loss > $5,000 | "INTC is down 35% ($8,500)" |
| `low_cost_basis_coverage` | info | > 30% of positions missing cost basis | "12/40 positions missing cost basis -- P&L may be incomplete" |

Each flag includes type-specific fields (sector, weight_pct, ticker, pnl_percent, pnl_usd, coverage_pct) for structured consumption.

---

### Step 3: Update existing tests in `tests/mcp_tools/test_positions_agent_format.py`

The enhanced `_build_agent_response()` now calls `result.to_monitor_view()` and `PortfolioService.enrich_positions_with_sectors()`. Existing tests must be updated for compatibility:

**3a. `_DummyPositionResult.to_monitor_view()`** (line 62): Currently returns empty `positions: []` and `summary: {}`. Update to return realistic monitor data with P&L fields so enrichment helpers produce meaningful output. At minimum, include positions with `ticker`, `value`, `pnl_usd`, `pnl_percent`, `cost_basis` fields, and a `summary` with `portfolio_totals_usd.total_pnl_usd`.

**3b. `SpyResult`** (line 120, `test_agent_format_calls_getters`) and **`SnapshotResult`** (line 149, `test_agent_format_snapshot_no_type_or_currency`): Both missing `to_monitor_view()` method. Add a stub to each that returns `{"positions": [], "summary": {}}`.

**3c. `fake_flags`** (line 133, `test_agent_format_calls_getters`): Has old 3-positional-arg signature `(positions, total_value, cache_info)`. Update to accept keyword-only args: `def fake_flags(positions, total_value, cache_info, **kwargs):`. Assert that `kwargs` contains `by_sector` and `monitor_positions` keys.

**3d. Monkeypatch `PortfolioService.enrich_positions_with_sectors`**: The enhanced `_build_agent_response()` imports and calls `PortfolioService().enrich_positions_with_sectors(monitor_payload)`. ALL tests that exercise `_build_agent_response()` must monkeypatch this to avoid real FMP calls:
- Direct callers: `test_agent_format_calls_getters` (line 142), `test_agent_format_snapshot_no_type_or_currency` (line 165), `test_agent_format_provider_status_error_and_ok` (line 183)
- End-to-end callers: `test_agent_format_structure` (line 100, calls `get_positions(format="agent")`)
- Add a no-op stub: `monkeypatch.setattr("services.portfolio_service.PortfolioService.enrich_positions_with_sectors", lambda self, payload: payload)`.

**3e. Update `test_agent_format_structure`** (line 90): This end-to-end test calls `get_positions(format="agent")` and should:
- Monkeypatch `PortfolioService.enrich_positions_with_sectors` (per 3d)
- Assert new fields present: `out["pnl_summary"]`, `out["exposure"]["by_sector"]`

**3f. New assertions in direct-call tests**: After updates, verify that agent format responses include the new fields:
- `out["pnl_summary"]` exists
- `out["exposure"]["by_sector"]` exists
- `out["top_holdings"]` entries have `sector`, `pnl_usd`, `pnl_percent` keys

---

## Files Modified

| File | Action |
|------|--------|
| `mcp_tools/positions.py` | **Edit** — enhance `_build_agent_response()`, add 3 helper functions |
| `core/position_flags.py` | **Edit** — add `by_sector`/`monitor_positions` kwargs + 4 new flag types |
| `tests/mcp_tools/test_positions_agent_format.py` | **Edit** — update test stubs for new `to_monitor_view()` dependency, monkeypatch `PortfolioService`, fix `fake_flags` signature |

No changes to `services/portfolio_service.py` or `core/result_objects/positions.py` — we consume existing public APIs.

---

## Execution Order

1. Add 4 new flags to `core/position_flags.py` (backward compatible — new kwargs default to None)
2. Add helper functions + enhance `_build_agent_response()` in `mcp_tools/positions.py`
3. Update test stubs in `tests/mcp_tools/test_positions_agent_format.py` (Step 3a-3e)
4. Run `pytest tests/mcp_tools/test_positions_agent_format.py` — all pass
5. Run `pytest tests/ -k position_flags` — all pass (backward compat)
6. Test via MCP tool call: `get_positions(format="agent")` — verify new fields populated

---

## Verification

1. **MCP tool test**: Call `get_positions(format="agent")` and verify:
   - `pnl_summary` present with winner/loser counts and top positions
   - `exposure.by_sector` populated with sector breakdown
   - `top_holdings[].sector` and `top_holdings[].pnl_usd` populated
   - New flags fire when conditions met (sector concentration, large loss)
2. **Backward compat**: `generate_position_flags()` called without new kwargs -> no new flags, no errors
3. **Existing tests**: `pytest tests/ -k position_flags` -- all pass
4. **Edge cases**:
   - Empty portfolio -> pnl_summary has zeros, by_sector empty, no new flags
   - All positions missing cost basis -> `low_cost_basis_coverage` flag fires
   - Single-sector portfolio -> `sector_concentration` + `low_sector_diversification` flags fire
   - FMP down -> all sectors "Unknown", no sector flags fire (skip "Unknown")

---

## Codex Review Log

| Round | Result | Issues |
|-------|--------|--------|
| R1 | FAIL | Existing tests in `test_positions_agent_format.py` stub `_build_agent_response` inputs without `to_monitor_view()` and monkeypatch `generate_position_flags` with old 3-arg signature. Plan needs explicit test update step. |
| R2 | FAIL | (1) `SnapshotResult` in `test_agent_format_snapshot_no_type_or_currency` also missing `to_monitor_view()` — plan only covered `SpyResult`. (2) `test_agent_format_structure` calls `get_positions(format="agent")` end-to-end — needs monkeypatch for `PortfolioService` and new field assertions. |
| R3 | PASS | All issues resolved. Step 3 now covers all 4 affected tests (3 direct + 1 end-to-end), both `SpyResult` and `SnapshotResult`, PortfolioService monkeypatch, and new field assertions. |

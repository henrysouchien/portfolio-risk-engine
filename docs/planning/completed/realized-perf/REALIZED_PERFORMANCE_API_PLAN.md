# Realized Performance — API + Frontend Integration

## Context

The `/api/performance` endpoint only supports hypothetical mode (database portfolios with fixed weights). The MCP `get_performance(mode="realized")` has full transaction-based P&L, institution/account filtering, income attribution, and data quality metadata — none of which is exposed through the REST API or frontend. This plan adds realized performance support to both.

## Approach

- **New endpoint** `POST /api/performance/realized` — follows established result-object pattern
- **Reuse existing infrastructure**: `_load_portfolio_for_performance()`, `PortfolioService.analyze_realized_performance()`, `RealizedPerformanceResult.to_api_response()` — same as MCP tool
- **Extract shared helpers** from `mcp_tools/performance.py` to `services/performance_helpers.py` to avoid code duplication and MCP-layer coupling
- **`useMutation` pattern** on frontend — realized is slow (10-30s) and user-triggered
- **Separate adapter** — response shape differs from hypothetical (returns already in %)
- **Mode toggle** in existing `PerformanceViewContainer`

## Changes

### 1. Backend: Extract shared helpers to `services/performance_helpers.py` (NEW)

The MCP tool has two functions the REST endpoint needs:
- `_load_portfolio_for_performance()` (lines 54-106) — loads positions, builds PortfolioData
- `_apply_date_window()` (lines 226-362) — 136-line date windowing on RealizedPerformanceResult. Rename to `apply_date_window()` (public, no underscore) when extracted.

**Extract both** to `services/performance_helpers.py`. This avoids:
- Route importing from `mcp_tools/` (wrong layer direction)
- Coupling to MCP-specific dependencies (e.g., `_resolve_user_id` from `mcp_tools/risk.py`)

The extracted `load_portfolio_for_performance()` will import `resolve_user_id` from `utils/user_resolution.py` (the shared helper) instead of the MCP-layer `_resolve_user_id`. The function signature stays the same. `mcp_tools/performance.py` then imports from `services/performance_helpers.py` instead of defining locally.

Also extract the **date validation logic** (lines 673-695) as a standalone `validate_date_params(start_date, end_date) -> tuple[str|None, str|None]` that raises `ValueError` on bad input. Both MCP tool and REST route use this.

### 2. Backend: `routes/realized_performance.py` (NEW)

Single endpoint, following the **exact same pattern** as the MCP tool (`mcp_tools/performance.py:766-824`):

```python
@router.post("/api/performance/realized")
async def realized_performance(body: RealizedPerformanceRequest, user = Depends(get_current_user)):
    # 1. Validate dates via validate_date_params(start_date, end_date) → HTTPException on bad input
    # 2. load_portfolio_for_performance(user_email, mode="realized", institution=..., account=..., ...)
    # 3. PortfolioService().analyze_realized_performance(position_result, ...)
    #    → returns RealizedPerformanceResult (or dict → from_analysis_dict())
    # 4. If start_date/end_date: apply_date_window(result, start_date, end_date)
    # 5. result.to_api_response(benchmark_ticker)  ← use the result object method directly
    # 6. make_json_safe() on the response dict
```

Request model with **strict typing**:
```python
class RealizedPerformanceRequest(BaseModel):
    benchmark_ticker: str = "SPY"
    source: Literal["all", "snaptrade", "plaid", "ibkr_flex", "schwab"] = "all"
    institution: str | None = None
    account: str | None = None
    start_date: str | None = None  # YYYY-MM-DD, validated at route boundary
    end_date: str | None = None    # YYYY-MM-DD, validated at route boundary
    include_series: bool = False
```

**Date validation at route boundary**: Parse and validate `start_date`/`end_date` via `validate_date_params()` before passing to helpers. Return `HTTPException(400)` on bad format or `start > end`. This mirrors the MCP tool's date guards (lines 673-695) but uses HTTP errors instead of dict returns.

Response: Direct output of `RealizedPerformanceResult.to_api_response()` — same shape the MCP tool returns for `format="full"`. Contains:
- `status`, `mode`, `performance_category`, `key_insights`
- `analysis_period`, `returns`, `risk_metrics`, `risk_adjusted_returns`
- `benchmark_analysis`, `benchmark_comparison`, `monthly_stats`
- `realized_metadata` (P&L, income, data quality, synthetics, etc.)
- Top-level convenience fields: `realized_pnl`, `unrealized_pnl`, `income_total`, `data_coverage`, etc.

Register `realized_performance_router` in `app.py`.

### 3. Percent scaling — how both modes produce consistent output

**CRITICAL**: The hypothetical and realized paths have different raw value scales:

| Path | Raw return values | Adapter action | Final `PerformanceData` |
|------|-------------------|----------------|------------------------|
| Hypothetical | Decimals (0.125 = 12.5%) | `PerformanceAdapter` multiplies by 100 | 12.5 |
| Realized | Already percent (12.5 = 12.5%) | `RealizedPerformanceAdapter` passes through | 12.5 |

Both adapters produce `PerformanceData` with values in percent (e.g., 12.5 means 12.5%). The shared `PerformanceView` renders identically regardless of mode. The key contract: **`PerformanceData` always contains percent values**.

Why they differ: Hypothetical uses `portfolio_risk.py` which returns raw decimals. Realized uses `compute_performance_metrics()` which returns percent-scaled values. This is a pre-existing asymmetry in the backend — each adapter normalizes to the same output.

### 4. Frontend Types: `chassis/src/types/index.ts`

Add `RealizedPerformanceApiResponse` matching the `to_api_response()` shape. Key sections:
- `analysis_period`, `returns`, `risk_metrics`, `risk_adjusted_returns` — same structure as hypothetical
- `benchmark_analysis`, `benchmark_comparison` — same structure
- `realized_metadata` — P&L, income, data quality (realized-only)
- Top-level convenience: `realized_pnl`, `unrealized_pnl`, `income_total`, `data_coverage`

### 5. Frontend API: `chassis/src/services/APIService.ts`

Add `getRealizedPerformance(params)` → POSTs to `/api/performance/realized`.

### 6. Frontend Adapter: `connectors/src/adapters/RealizedPerformanceAdapter.ts` (NEW)

Transforms `RealizedPerformanceApiResponse` → `PerformanceData` (same shape for shared `PerformanceView`).

Key difference from `PerformanceAdapter`: returns are already in percent — NO multiplication by 100.

Also extracts realized-only data into a `RealizedDetails` shape (P&L breakdown, income, data quality) for the details panel.

### 7. Frontend Hook: `connectors/src/features/analysis/hooks/useRealizedPerformance.ts` (NEW)

`useMutation` pattern (like `useHedgePreview`):
```typescript
export const useRealizedPerformance = () => {
  const { api } = useSessionServices();
  return useMutation({
    mutationFn: async (params) => {
      const raw = await api.getRealizedPerformance(params);
      return RealizedPerformanceAdapter.transform(raw);
    },
  });
};
```

Export from `features/analysis/index.ts` and `connectors/src/index.ts`.

### 8. Frontend UI: `PerformanceViewContainer.tsx`

- Add Hypothetical/Realized toggle (two buttons or segmented control)
- **Hypothetical** (default): Existing `usePerformance` auto-fetch, unchanged
- **Realized**: `useRealizedPerformance` mutation + explicit "Analyze" button
- **Mode switch behavior**: When toggling to Realized, hypothetical auto-fetch continues in background (already cached). When toggling to Hypothetical, switch back to cached hypothetical data immediately.
- Both modes feed `PerformanceData` to shared `PerformanceView`
- Realized mode: additional `RealizedPerformanceDetails` section below main view showing P&L cards, income breakdown, data quality panel

**Institution/account filters** (realized mode only):
- Simple text inputs (not dropdowns) for institution and account, since no existing institution-list API exists in the frontend
- Filters are passed to the `useRealizedPerformance` mutation params
- Future enhancement: populate from positions data if needed

### 9. Tests

| Test | What it verifies |
|------|------------------|
| `tests/services/test_performance_helpers.py` | Extracted `validate_date_params()` edge cases (bad format, start > end, None values). `load_portfolio_for_performance()` calls PositionService correctly for realized mode. |
| `tests/routes/test_realized_performance.py` | Route returns 401 without auth, 400 on bad dates, 200 with valid request. Response shape matches `to_api_response()`. |
| `tests/mcp_tools/test_performance.py` | Existing MCP tests still pass after import refactor. |
| Frontend adapter test | `RealizedPerformanceAdapter` does NOT multiply returns by 100. Verify output matches `PerformanceData` shape. |

## Files Modified

| File | Change |
|------|--------|
| `services/performance_helpers.py` | **NEW** — extracted `load_portfolio_for_performance()` + `apply_date_window()` + `validate_date_params()` |
| `mcp_tools/performance.py` | Import from `services/performance_helpers.py` instead of local functions |
| `routes/realized_performance.py` | **NEW** — REST endpoint using result object pattern |
| `app.py` | Register `realized_performance_router` |
| `frontend/packages/chassis/src/types/index.ts` | Add `RealizedPerformanceApiResponse` |
| `frontend/packages/chassis/src/services/APIService.ts` | Add `getRealizedPerformance()` |
| `frontend/packages/connectors/src/adapters/RealizedPerformanceAdapter.ts` | **NEW** — transform to PerformanceData |
| `frontend/packages/connectors/src/features/analysis/hooks/useRealizedPerformance.ts` | **NEW** — useMutation hook |
| `frontend/packages/connectors/src/features/analysis/index.ts` | Re-export |
| `frontend/packages/connectors/src/index.ts` | Re-export |
| `frontend/packages/ui/src/components/dashboard/views/modern/PerformanceViewContainer.tsx` | Mode toggle + realized wiring + details panel |
| `tests/services/test_performance_helpers.py` | **NEW** — unit tests for extracted helpers |
| `tests/routes/test_realized_performance.py` | **NEW** — route integration tests |
| `frontend/packages/connectors/src/adapters/RealizedPerformanceAdapter.test.ts` | **NEW** — adapter unit tests (percent scaling, shape) |

## Key Design Decisions

1. **Result object pattern** — `RealizedPerformanceResult.to_api_response()` is the single source of truth for the response shape. REST endpoint calls it directly, same as MCP tool. No hand-rolled response dicts.
2. **Extract to `services/`, not import from `mcp_tools/`** — Route layer must not depend on MCP layer. Extracted helpers import `resolve_user_id` from `utils/user_resolution.py` (shared utility), not `_resolve_user_id` from `mcp_tools/risk.py`.
3. **Date validation at route boundary** — `validate_date_params()` shared helper. Route converts `ValueError` to `HTTPException(400)`. MCP tool converts to `{"status": "error"}` dict.
4. **Strict request typing** — `source` uses `Literal[...]` for API contract quality, matching `PortfolioService.analyze_realized_performance()` signature.
5. **`useMutation` not `useQuery`** — Realized is slow (10-30s) and user-triggered. Explicit "Analyze" button, not auto-fetch.
6. **Separate adapter with documented percent contract** — Hypothetical adapter multiplies by 100; realized does NOT. Both produce `PerformanceData` in percent. This is the correct behavior given backend asymmetry.
7. **Shared `PerformanceView`** — Both modes produce `PerformanceData`, so chart + period returns + risk metrics render identically.
8. **Text inputs for filters, not dropdowns** — No institution-list API exists. Simple text inputs with MCP-style alias matching on the backend.

## Verification

1. `python3 -m py_compile services/performance_helpers.py` passes
2. `python3 -m py_compile routes/realized_performance.py` passes
3. `python3 -m py_compile mcp_tools/performance.py` passes (after import refactor)
4. `python3 -m pytest tests/services/test_performance_helpers.py -v` passes
5. `python3 -m pytest tests/routes/test_realized_performance.py -v` passes
6. `python3 -m pytest tests/mcp_tools/test_performance.py -v` passes (existing tests unbroken)
7. `cd frontend && pnpm exec tsc --noEmit -p packages/ui/tsconfig.json` passes
8. `cd frontend && pnpm exec vitest run packages/connectors/src/adapters/RealizedPerformanceAdapter.test.ts` passes (percent scaling, PerformanceData shape)
9. `curl -X POST localhost:5001/api/performance/realized -H "Content-Type: application/json" -H "Cookie: session_id=..." -d '{"benchmark_ticker":"SPY"}'` returns same shape as MCP `get_performance(mode="realized", format="full")`
10. `curl` with bad `start_date` returns 400 with descriptive error
11. Frontend: Performance view → toggle to "Realized" → click "Analyze" → real data renders
12. Values match MCP output (no double-multiplication of returns)
13. P&L / income / data quality panels render correctly
14. Institution/account text filters narrow scope

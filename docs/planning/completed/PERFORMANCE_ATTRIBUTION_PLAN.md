# P2: Performance Attribution — Thread Sector/Factor/Security Attribution into Performance Endpoint

**Date**: 2026-02-28
**Status**: COMPLETE (verified in Chrome 2026-02-28)
**Parent**: TODO.md P2, `FRONTEND_DATA_WIRING_AUDIT.md`

## Context

The PerformanceView component has a "Sector Performance Attribution" section showing sectors with allocation %, return %, and contribution %. This data is **fully hardcoded mock data** (lines 452-510 of `PerformanceView.tsx`). The `PerformanceViewContainer` already wires `performanceSummary.attribution.{sectors,factors,security}` but receives empty arrays because the backend doesn't compute or return attribution.

**Goal**: Compute sector and security-level performance attribution in the backend and thread it through to the frontend.

---

## What Already Exists

### Backend
- `calculate_portfolio_performance_metrics()` in `portfolio_risk.py` (line 1584) already has:
  - `df_ret`: per-ticker monthly returns DataFrame (all tickers)
  - `filtered_weights`: portfolio weights by ticker
  - `port_ret` / `bench_ret`: aligned portfolio and benchmark return series
- `PerformanceResult` dataclass (`core/result_objects/performance.py` line 15) — has `to_api_response()` (line 408), `from_core_analysis()`. No attribution field.
- `enrich_positions_with_sectors()` in `portfolio_service.py` (line 848) — FMP profile sector lookup (threaded, cached). Pattern to reuse.
- `FMPClient.fetch("profile", symbol=..., use_cache=True)` — returns sector field

### Frontend
- `PerformanceViewContainer.tsx` (lines 302-307) — wires `performanceSummary.attribution.{sectors, factors, security}`, gets empty arrays
- `PerformanceView.tsx` (lines 452-510) — renders sector cards with `{name, allocation, return, contribution, insight, trend, riskLevel, ...}` — ALL HARDCODED
- `PerformanceAdapter.ts` — `transformPerformanceSummary()` (line 722) returns `{periods, riskMetrics}` — no attribution yet
- Props interface (PerformanceView line ~221): `sectors?: Array<{ name: string; contribution: number }>` — minimal type, needs enrichment

---

## Implementation Plan

### Step 1: Add `_compute_sector_attribution()` to `portfolio_risk.py`

**File**: `portfolio_risk_engine/portfolio_risk.py` (new helper function, ~line 1755 area)

Using `df_ret` and `filtered_weights` already in scope in `calculate_portfolio_performance_metrics()`:

```python
def _compute_sector_attribution(
    df_ret: pd.DataFrame,
    weights: Dict[str, float],
    fmp_ticker_map: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Compute sector-level performance attribution from per-ticker returns."""
    # 1. Look up sector for each ticker via FMP profile (threaded, cached)
    #    Use fmp_ticker_map to resolve mapped/international symbols before profile lookup
    #    (e.g. ticker "BRK.B" → fmp_ticker_map["BRK.B"] = "BRK-B" → FMP profile)
    # 2. Compute per-ticker total return from df_ret (cumulative product)
    # 3. Compute per-ticker contribution = weight × total_return
    # 4. Group by sector: sum weights → allocation, weighted avg return, sum contributions
    # 5. Sort by |contribution| descending
    # Return: [{name, allocation, return, contribution}]
```

Also add `_compute_security_attribution()` — simpler, no grouping:
```python
def _compute_security_attribution(
    df_ret: pd.DataFrame,
    weights: Dict[str, float],
) -> List[Dict[str, Any]]:
    """Compute per-security performance attribution."""
    # Per-ticker: {name, allocation, return, contribution}
    # Sort by |contribution| descending
```

Call both in `calculate_portfolio_performance_metrics()` (~line 1733, after dividend metrics):
```python
try:
    performance_metrics["sector_attribution"] = _compute_sector_attribution(
        df_ret, filtered_weights, fmp_ticker_map
    )
except Exception:
    performance_metrics["sector_attribution"] = []

performance_metrics["security_attribution"] = _compute_security_attribution(
    df_ret, filtered_weights
)
```

### Step 2: Thread through `PerformanceResult`

**File**: `core/result_objects/performance.py`

Add new optional fields to dataclass (~line 118):
```python
# Performance attribution (optional)
sector_attribution: Optional[List[Dict[str, Any]]] = None
security_attribution: Optional[List[Dict[str, Any]]] = None
```

Update `to_api_response()` (~line 553) to include:
```python
"sector_attribution": self.sector_attribution,
"security_attribution": self.security_attribution,
```

Update `from_core_analysis()` to extract:
```python
sector_attribution=data.get("sector_attribution"),
security_attribution=data.get("security_attribution"),
```

### Step 3: Add attribution to `PerformanceAdapter.ts`

**File**: `frontend/packages/connectors/src/adapters/PerformanceAdapter.ts`

**3a. Update `PerformanceResult` interface** (~line 157) — add new backend fields:
```typescript
// After existing fields (~line 208):
sector_attribution?: Array<{ name: string; allocation: number; return: number; contribution: number }>;
security_attribution?: Array<{ name: string; allocation: number; return: number; contribution: number }>;
```

**3b. Update `PerformanceData.performanceSummary` type** (~line 300) — add `attribution` to the existing `{periods, riskMetrics}` shape:
```typescript
performanceSummary: {
  periods: Record<string, { ... }>;
  riskMetrics: { ... };
  attribution?: {
    sectors: Array<{ name: string; allocation: number; return: number; contribution: number }>;
    factors: Array<{ name: string; contribution: number }>;
    security: Array<{ name: string; allocation: number; return: number; contribution: number }>;
  };
};
```

**3c. Update `transformPerformanceSummary()`** return (~line 766) to include attribution:
```typescript
return {
  periods,
  riskMetrics,
  attribution: {
    sectors: (performance.sector_attribution || []).map(s => ({
      name: s.name,
      allocation: s.allocation ?? 0,
      return: s.return ?? 0,
      contribution: s.contribution ?? 0,
    })),
    factors: [],  // Deferred — needs factor regression per period
    security: (performance.security_attribution || []).map(s => ({
      name: s.name,
      allocation: s.allocation ?? 0,
      return: s.return ?? 0,
      contribution: s.contribution ?? 0,
    })),
  },
};
```

### Step 4: Wire real data into `PerformanceView.tsx` sector cards

**File**: `frontend/packages/ui/src/components/portfolio/PerformanceView.tsx`

**4a. Update the attribution prop types in the comment block** (~lines 88-101) and in `MappedPerformanceViewData` type (if defined in this file) to include enriched fields:
```typescript
sectors?: Array<{ name: string; allocation: number; return: number; contribution: number }>;
security?: Array<{ name: string; allocation: number; return: number; contribution: number }>;
```

**4b. Replace hardcoded `sectors` array** (lines 452-510) with real data from props, falling back to existing mock data:
```typescript
sectors: (data?.attribution?.sectors?.length > 0)
  ? data.attribution.sectors.map(s => ({
      name: s.name,
      allocation: s.allocation,
      return: s.return,
      contribution: s.contribution,
      insight: "",
      trend: "neutral" as const,
      riskLevel: s.allocation > 25 ? "high" : s.allocation > 10 ? "medium" : "low",
      momentum: 0,
      volatility: 0,
      recommendation: "",
    }))
  : fallbackSectors
```

Extract existing hardcoded data into a `fallbackSectors` const for graceful degradation.

**Note**: Security attribution (`topContributors` cards at ~lines 527, 1306) is also currently hardcoded. For this pass, leave them as-is — the `security_attribution` data will be available in `data.attribution.security` for a future iteration to wire up. The sector cards are the visible gap.

### Step 5: Update `PerformanceViewContainer.tsx` types

**File**: `frontend/packages/ui/src/components/dashboard/views/modern/PerformanceViewContainer.tsx`

**5a. Update `PerformanceDataLike.performanceSummary.attribution`** (~line 104):
```typescript
attribution?: {
  sectors?: Array<{ name: string; allocation: number; return: number; contribution: number }>;
  factors?: Array<{ name: string; contribution: number }>;
  security?: Array<{ name: string; allocation: number; return: number; contribution: number }>;
};
```

**5b. Update `MappedPerformanceViewData.attribution`** (~line 134):
```typescript
attribution?: {
  sectors?: Array<{ name: string; allocation: number; return: number; contribution: number }>;
  factors?: Array<{ name: string; contribution: number }>;
  security?: Array<{ name: string; allocation: number; return: number; contribution: number }>;
};
```

Lines 303-306 already pass `performanceSummary?.attribution?.sectors` — the enriched shape flows through once the types are widened.

---

## Files Modified

| File | Action |
|------|--------|
| `portfolio_risk_engine/portfolio_risk.py` | **Edit** — add `_compute_sector_attribution()`, `_compute_security_attribution()`, call in `calculate_portfolio_performance_metrics()` |
| `core/result_objects/performance.py` | **Edit** — add `sector_attribution`, `security_attribution` fields + `to_api_response()` + `from_core_analysis()` |
| `frontend/packages/connectors/src/adapters/PerformanceAdapter.ts` | **Edit** — add attribution to `transformPerformanceSummary()` |
| `frontend/packages/ui/src/components/portfolio/PerformanceView.tsx` | **Edit** — replace hardcoded sectors with real data, keep fallback |
| `frontend/packages/ui/src/components/dashboard/views/modern/PerformanceViewContainer.tsx` | **Edit** — update attribution prop types if needed |

No new files. Factor attribution deferred (empty array for now).

---

## Key Design Decisions

1. **Compute in `calculate_portfolio_performance_metrics()`**: `df_ret` and `filtered_weights` are already there. No need to call `analyze_portfolio()` — that would double the compute cost.

2. **Sector lookup via FMP profile**: Same threaded+cached pattern as `enrich_positions_with_sectors()`. Reuse `FMPClient.fetch("profile")`.

3. **Factor attribution deferred**: Requires factor regression decomposition per period — much more complex. Empty array for now; frontend gracefully handles empty.

4. **Keep fallback mock data**: If attribution is empty (API error, no FMP data), fall back to existing hardcoded sectors. Same pattern as hedging.

5. **Security attribution is free**: Per-ticker returns and weights already exist — just format and return.

6. **Attribution shape**: `{name, allocation, return, contribution}` — allocation is % of portfolio, return is total period return %, contribution is allocation × return (the portion of portfolio return attributable to this sector/security).

---

## Codex Review Log

| Round | Result | Issues |
|-------|--------|--------|
| R1 | FAIL | (1) `PerformanceResult` interface in adapter missing `sector_attribution`/`security_attribution` fields. (2) `PerformanceData.performanceSummary` type missing `attribution` field. (3) Security attribution not rendered — `topContributors` cards are hardcoded, not wired to `data.attribution.security`. (4) `fmp_ticker_map` needed in sector lookup for mapped/international symbols. |
| R2 | PASS | All 4 fixes verified. Type threading correct across all layers. `from_core_analysis()` extraction pattern matches existing behavior. Attribution shape `{name, allocation, return, contribution}` consistent backend→frontend. |

---

## Verification

1. **Python CLI test**: Call `calculate_portfolio_performance_metrics()` and verify `sector_attribution` and `security_attribution` in output
2. **API test**: Hit performance endpoint, verify new fields in JSON response
3. **Chrome visual test**: Navigate to Performance view → Sector Performance Attribution, verify real sector names + numbers from portfolio
4. **TypeScript**: `npx tsc --noEmit` passes for all three packages
5. **Fallback**: Disconnect backend or force empty attribution → verify mock sectors still display

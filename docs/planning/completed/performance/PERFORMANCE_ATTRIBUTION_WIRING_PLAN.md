# Performance Attribution — Wire Real Data to Frontend

## Context

The Performance view's "Attribution" tab has three panels: Sector Attribution, Top Contributors/Detractors, and Factor Attribution. All show "No data available." Investigation reveals the **backend already computes all three** in the hypothetical path (`calculate_portfolio_performance_metrics()` at `portfolio_risk.py:1864-1888`), and the full pipeline through `PerformanceResult` → `PerformanceAdapter` → `PerformanceView` is wired. The TODO comments in `PerformanceViewContainer.tsx` calling this a "backend feature gap" are stale.

**Two issues to fix:**

1. **Hypothetical mode** — Backend computes attribution. The full pipeline is wired and verified correct (no shape mismatch). The panels show "No data" likely because the DB-based test portfolio has insufficient return data (factor attribution requires ≥6 months). Note: missing FMP API key does NOT block sector attribution — sectors default to "Unknown" and rows are still produced. The TODO comments in the container are stale and should be removed.

2. **Realized mode** — `RealizedPerformanceAdapter` hardcodes `attribution: { sectors: [], factors: [], security: [] }`. The realized backend doesn't compute attribution. Need to add sector + security attribution using the same functions.

### Units convention

**Attribution values are in percentage points** (not decimals). `_compute_sector_attribution()` and `_compute_security_attribution()` multiply by 100 inline (e.g., `weight * 100.0` at `portfolio_risk.py:2013,2058`), then `_build_attribution_row()` (`portfolio_risk.py:1921`) rounds the already-scaled values. `formatPercent()` in the frontend (`chassis/src/utils/formatting.ts:165`) expects already-percent values and just appends `%`. The hypothetical `PerformanceAdapter` passes values through without scaling (lines 800-826). **No units mismatch exists — both backend and frontend agree on percentage points.**

## Existing Backend Pipeline (Hypothetical)

The full pipeline already exists:
- `_compute_sector_attribution()` → `portfolio_risk_engine/portfolio_risk.py:1957` — per-sector weight × return
- `_compute_security_attribution()` → `portfolio_risk_engine/portfolio_risk.py:2045` — per-ticker contribution
- `_compute_factor_attribution()` → `portfolio_risk_engine/portfolio_risk.py:2068` — OLS regression (Market/Momentum/Value)
- `calculate_portfolio_performance_metrics()` → populates dict at lines 1864-1888
- `PerformanceResult.from_core_analysis()` → extracts at lines 244-246
- `PerformanceResult.to_api_response()` → includes at lines 564-566
- `PerformanceAdapter.transformPerformanceSummary()` → maps at lines 800-835
- `PerformanceViewContainer` → reads from `performanceSummary.attribution` at lines 515-518
- `PerformanceView` → renders sector cards (line 1262), top contributors/detractors (lines 1350, 1429), factor cards (line 1499)

## Changes

### 1. Verify hypothetical attribution pipeline

**Action**: Hit the hypothetical API (`POST /api/performance`), inspect response, verify `sector_attribution`/`security_attribution`/`factor_attribution` arrays are populated. The full pipeline is verified correct — no shape or units mismatch.

If attribution arrays are populated → the Attribution tab will render automatically once the stale TODOs are removed (no code change needed beyond that).
If attribution arrays are empty → the DB portfolio has insufficient return data. Note: missing FMP API key does NOT block sector attribution — sectors default to `"Unknown"` and rows are still returned when ticker returns exist (`portfolio_risk.py:2012`). Factor attribution requires ≥6 months + at least 1 factor available.

### 2. Remove stale TODO comments

In `PerformanceViewContainer.tsx` at lines 514-518, replace:
```typescript
// TODO: Add performance attribution analysis to backend (this is a backend feature gap)
attribution: {
  sectors: performanceData.performanceSummary?.attribution?.sectors ?? [],     // TODO: ...
  factors: performanceData.performanceSummary?.attribution?.factors ?? [],     // TODO: ...
  security: performanceData.performanceSummary?.attribution?.security ?? [],   // TODO: ...
},
```
With accurate comments noting data flows from `calculate_portfolio_performance_metrics()` through the adapter.

### 3. Add attribution to realized performance path

#### 3a. Backend: Compute attribution after realized analysis

In `routes/realized_performance.py`, after `realized_result` is computed, derive sector + security attribution from the position data.

**Important implementation details:**
- `position_result.data.positions` are **dicts** with fields: `ticker`, `quantity`, `value`, `type`, `position_source`, `currency`. There is **no `weight` field** — weights must be computed from `value / sum(abs(values))` (gross-exposure-based, preserves sign for short positions).
- **Date alignment**: The route uses `normalized_start`/`normalized_end` (from `validate_date_params()`), but `apply_date_window()` snaps dates to month-end. Attribution must use the **snapped dates from the response's `analysis_period`** (post-windowing) to ensure the returns DataFrame covers exactly the same period as the displayed realized metrics.
- **`min_observations` adaptation**: `get_returns_dataframe()` defaults to `min_observations=11`, which is too strict for short custom windows. The hypothetical path already handles this — `calculate_portfolio_performance_metrics()` at line 1744 computes `min_obs = min(default_min_obs, requested_return_observations)`. We replicate the same window-aware logic: count the month-end points in the attribution date range and use `max(1, month_points - 1)` capped at the default threshold.
- `get_returns_dataframe()` signature is `get_returns_dataframe(weights: Dict[str, float], start_date, end_date, ...)` — first arg is a weights dict, NOT a list of tickers. Optional kwargs: `fmp_ticker_map`, `currency_map`, `instrument_types`, `min_observations`.
- The route currently discards `portfolio_data` (3rd return from `load_portfolio_for_performance()`). Need to capture it to access `fmp_ticker_map`/`currency_map`/`instrument_types`.
- With unconsolidated positions (source/institution/account filters), duplicate tickers are possible. Use aggregation to combine values for the same ticker before computing weights.
- Import from canonical path: `from portfolio_risk_engine.portfolio_risk import get_returns_dataframe`.

**Route change**: Capture `portfolio_data` from `load_portfolio_for_performance()`:
```python
# Current: _, _, _, position_result = load_portfolio_for_performance(...)
# Change to:
_, _, portfolio_data, position_result = load_portfolio_for_performance(...)
```

**Attribution enrichment** (after `response = realized_result.to_api_response(...)`):
```python
# Enrich with sector/security attribution from position weights
try:
    import pandas as pd
    from portfolio_risk_engine.portfolio_risk import (
        _compute_sector_attribution,
        _compute_security_attribution,
        get_returns_dataframe,
    )

    # positions are dicts — compute weights from value (gross-exposure-based)
    # Aggregate by ticker to handle duplicates from unconsolidated positions
    value_agg: dict[str, float] = {}
    for p in position_result.data.positions:
        ticker = p.get("ticker")
        value = p.get("value")
        if ticker and value:
            value_agg[ticker] = value_agg.get(ticker, 0.0) + float(value)

    # Denominator = sum of absolute values (gross exposure)
    # Preserves sign: long positions get positive weight, shorts get negative
    total_gross = sum(abs(v) for v in value_agg.values())
    if total_gross > 0:
        weights = {t: v / total_gross for t, v in value_agg.items()}

        # Use portfolio_data for ticker resolution context
        fmp_ticker_map = getattr(portfolio_data, "fmp_ticker_map", None)
        currency_map = getattr(portfolio_data, "currency_map", None)
        instrument_types = getattr(portfolio_data, "instrument_types", None)

        # ALWAYS use the snapped analysis_period dates from the response
        # (apply_date_window() snaps to month-end; attribution must align)
        analysis_period = response.get("analysis_period", {})
        attr_start = analysis_period.get("start_date")
        attr_end = analysis_period.get("end_date")

        if attr_start and attr_end:
            # Window-aware min_observations (mirrors hypothetical at portfolio_risk.py:1744)
            try:
                from portfolio_risk_engine.config import DATA_QUALITY_THRESHOLDS
                default_min_obs = int(
                    DATA_QUALITY_THRESHOLDS.get("min_observations_for_expected_returns", 11)
                )
            except Exception:
                default_min_obs = 11
            month_points = len(pd.date_range(start=attr_start, end=attr_end, freq="ME"))
            min_obs = min(default_min_obs, max(1, month_points - 1))

            # get_returns_dataframe expects weights dict as first arg
            df_ret = get_returns_dataframe(
                weights,
                start_date=attr_start,
                end_date=attr_end,
                fmp_ticker_map=fmp_ticker_map,
                currency_map=currency_map,
                instrument_types=instrument_types,
                min_observations=min_obs,
            )

            # Re-normalize weights to only include tickers that survived
            # (some tickers may be dropped due to insufficient data)
            surviving_tickers = set(df_ret.columns) if hasattr(df_ret, 'columns') else set()
            if surviving_tickers:
                filtered_weights = {t: w for t, w in weights.items() if t in surviving_tickers}
                total_filtered = sum(abs(v) for v in filtered_weights.values())
                if total_filtered > 0:
                    filtered_weights = {t: v / total_filtered for t, v in filtered_weights.items()}
            else:
                filtered_weights = weights

            response["sector_attribution"] = _compute_sector_attribution(
                df_ret=df_ret, weights=filtered_weights, fmp_ticker_map=fmp_ticker_map,
            )
            security_attr = _compute_security_attribution(
                df_ret=df_ret, weights=filtered_weights,
            )
            # Enrich with analyst data (same as hypothetical route at app.py:1543)
            # Note: uses entry["name"] (raw ticker) as FMP symbol — works for US equities
            PortfolioService(cache_results=True).enrich_attribution_with_analyst_data(security_attr)
            response["security_attribution"] = security_attr
except Exception:
    pass  # Attribution is optional enrichment — fails silently
```

**Factor attribution skipped** for realized — requires per-position return series aligned with factor returns, which would need reconstruction. Sector + security attribution are the most useful for realized anyway.

#### 3b. Frontend: Update RealizedPerformanceAdapter

In `RealizedPerformanceAdapter.ts`, change the hardcoded empty arrays (line 195-199) to extract from the API response. The relevant function is `transformPerformanceData(apiResponse)` at line 117:

```typescript
attribution: {
  sectors: Array.isArray(apiResponse.sector_attribution)
    ? apiResponse.sector_attribution.map(s => ({
        name: s.name || '', allocation: s.allocation ?? 0,
        return: s.return ?? 0, contribution: s.contribution ?? 0,
      }))
    : [],
  factors: [],  // Not available for realized mode
  security: Array.isArray(apiResponse.security_attribution)
    ? apiResponse.security_attribution.map(s => ({
        name: s.name || '', allocation: s.allocation ?? 0,
        return: s.return ?? 0, contribution: s.contribution ?? 0,
        targetPrice: typeof s.target_price === 'number' ? s.target_price : undefined,
        analystRating: typeof s.analyst_rating === 'string' ? s.analyst_rating : undefined,
        analystCount: typeof s.analyst_count === 'number' ? s.analyst_count : undefined,
      }))
    : [],
},
```

#### 3c. Update RealizedPerformanceApiResponse type

Add optional fields to `chassis/src/types/index.ts`:

```typescript
sector_attribution?: Array<{ name: string; allocation: number; return: number; contribution: number }>;
security_attribution?: Array<{
  name: string; allocation: number; return: number; contribution: number;
  target_price?: number; analyst_rating?: string; analyst_count?: number;
}>;
```

### 4. Units — already consistent, no changes needed

Attribution values are in **percentage points** (5.0 = 5%). Scaling is done in `_compute_sector_attribution()` / `_compute_security_attribution()` (e.g., `weight * 100.0` at `portfolio_risk.py:2013,2058`). `_build_attribution_row()` at `portfolio_risk.py:1921` just rounds the already-scaled values. `formatPercent()` (`chassis/src/utils/formatting.ts:165`) expects percent values and appends `%`. The `PerformanceAdapter` passes through without scaling (lines 800-826). No units mismatch — both sides agree.

## Files to Modify

| File | Change |
|------|--------|
| `routes/realized_performance.py` | Capture `portfolio_data` from helper, add post-analysis sector/security attribution + analyst enrichment |
| `frontend/packages/connectors/src/adapters/RealizedPerformanceAdapter.ts` | Wire attribution from API response instead of empty arrays |
| `frontend/packages/chassis/src/types/index.ts` | Add `sector_attribution`/`security_attribution` to `RealizedPerformanceApiResponse` |
| `frontend/packages/ui/src/components/dashboard/views/modern/PerformanceViewContainer.tsx` | Remove stale TODO comments |

## Key Design Decisions

1. **Attribution is post-processing enrichment** — mirrors how hypothetical route enriches security attribution with analyst data (`app.py:1543-1545`). Not part of core `RealizedPerformanceResult`.
2. **Sector + security only for realized** — factor attribution requires per-position return series alignment that the realized path doesn't produce. Factor column stays empty for realized mode.
3. **Reuse existing functions** — `_compute_sector_attribution()` and `_compute_security_attribution()` from `portfolio_risk.py` are battle-tested with existing unit tests.
4. **No PerformanceView changes** — the view already renders attribution data when present. Empty arrays → "No data", populated → sector cards + contributor/detractor lists.
5. **Graceful degradation** — all attribution computation wrapped in try/except. If the attribution computation itself fails (e.g., insufficient return data, unexpected error), attribution stays empty silently. Note: FMP sector lookup failure does NOT cause empty attribution — sectors default to "Unknown" and rows are still produced.

## Verification

1. `python3 -m py_compile routes/realized_performance.py` passes
2. `cd frontend && pnpm exec tsc --noEmit -p packages/ui/tsconfig.json` passes
3. `POST /api/performance` (hypothetical) → verify `performance_metrics.sector_attribution`, `performance_metrics.security_attribution`, `performance_metrics.factor_attribution` are populated arrays in the response (nested under `performance_metrics`)
4. `POST /api/performance/realized` → verify `sector_attribution`, `security_attribution` are populated
5. Frontend hypothetical → Attribution tab shows sector cards + top contributors/detractors + factor cards
6. Frontend realized → Attribution tab shows sector cards + top contributors/detractors
7. Values are consistent between modes (both show contribution as percentage)
8. `formatPercent` renders attribution values correctly (no double-scaling)

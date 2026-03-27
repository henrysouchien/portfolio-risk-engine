# Hedge Analysis Tool Redesign — Factor-First Methodology

> **Codex review**: R1 (4H/3M/1L) → R2 (2H/3M/1L) → R3 FAIL (1H/3M/1L) → R4 FAIL (0H/1M/0L) → **R5 PASS**.

## Context

The current hedge tool uses correlation-only methodology to recommend hedges. `risk_reduction = abs(correlation) * 100` is misleading — a -0.18 correlation doesn't mean 18% risk reduction. Both recommendations show DBA (agriculture ETF) for financial sector exposures, which is unhelpful.

The redesign introduces a **Diagnose → Prescribe → Quantify** approach, using the existing factor model (same one the Risk view uses) as the primary signal, with three recommendation types per risk driver.

## New Methodology

### 1. Diagnose (Factor Exposures)
Pull from `build_portfolio_view()` which returns:
- `portfolio_factor_betas` — aggregate factor betas: `market`, `momentum`, `value`, `industry`, `subindustry`, `commodity`, rates. **Note**: this is NOT per-sector betas — it's aggregate factors.
- `industry_variance.per_industry_group_beta` — per-industry-group beta (e.g., Technology beta, Real Estate beta). **This is the per-driver beta source.**
- `industry_variance.percent_of_portfolio` — per-industry **variance share** (how much of portfolio risk each industry contributes), NOT portfolio weight concentration. UI copy must reflect this: "Technology (35% of risk)" not "Technology (35% of portfolio)".
- `variance_decomposition` — factor vs idiosyncratic split
- `volatility_annual` — portfolio vol
- `df_stock_betas` — per-stock factor betas

This is the SAME data the Risk view uses. Numbers will be consistent.

### 2. Prescribe (Three Types Per Driver)
For each risk driver (industry overexposure or high market beta):

**Type 1 — Direct Offset**: Short the factor ETF to neutralize the exposure.
- Lookup: `industry_to_etf.yaml` maps the driver to its proxy ETF. **Note**: industry_map entries may be structured dicts with `"etf"` key — use `mapping.get("etf", mapping)` or the `map_industry_etf()` helper, not the raw value. **Also fix** the existing driver-detection reverse-lookup at line 1216 (`_etf_to_sector.setdefault(_etf, ...)`) to handle structured entries via the same `mapping.get("etf", mapping)` pattern.
- Per-driver beta comes from `industry_variance.per_industry_group_beta[driver_etf]`, NOT from `portfolio_factor_betas["industry"]`.
- Weight formula: `suggested_weight = -(driver_beta * reduction_pct)`. This works because sector ETFs have beta ≈ 1.0 to their own sector. Make this assumption explicit: `hedge_beta_to_driver ≈ 1.0` for sector proxy ETFs.
- For market driver: short SPY with weight = `-(market_beta - 1.0) * scale_factor`
- **Chaining**: All three recommendation types get "Test in What-If", "Quantify Impact", and "Analyze & Execute" buttons. The negative `suggested_weight` for direct offsets is passed through as a delta (e.g., `"-5%"`) to What-If and to the execution workflow. **Known limitation**: the existing What-If delta formatting (HedgeTool.tsx:169), execution route target weight floor (hedging.py:135), and rebalance sell cap (trading_helpers.py:97) all clamp negatives. Short support is being added in a **parallel workstream** — this plan wires the buttons and passes the values through; the parallel task removes the clamps.

**Type 2 — Beta Alternative**: Long low-beta assets that dilute the exposure.
- For each driver, resolve the driver's ETF ticker from `industry_map` (e.g., Technology → XLK).
- Extract the driver ETF's return series from `_shared_panel[driver_ticker]` — the panel contains raw monthly return series keyed by ETF ticker.
- For each candidate ETF column in `_shared_panel` (excluding the driver itself and tickers already in portfolio):
  - Compute beta of candidate vs driver: use simple OLS regression of `candidate_returns ~ driver_returns`. **Do NOT use `compute_factor_metrics()`** — that function expects `(stock_returns: pd.Series, factor_dict: Dict[str, pd.Series])`, which is the wrong contract for pairwise ETF-vs-ETF beta. Instead, use a simple inline OLS: `np.polyfit(driver_returns, candidate_returns, 1)[0]` or `statsmodels OLS`, similar to how `compute_factor_metrics` internally works but for the single-factor case.
  - Look up Sharpe from `_shared_perf`
- Filter: beta < 0.5 to the overexposed factor, Sharpe > 0
- Rank by beta ascending (lowest exposure first), then Sharpe descending
- Top 3 candidates

**Type 3 — Correlation Alternative** (existing logic, repositioned): Diversification via negatively correlated assets.
- Reuses existing `recommend_offsets()` correlation scan
- Repositioned as "diversification benefit" rather than the primary recommendation

### 3. Quantify (Lazy, On-Demand)
Use the existing what-if engine (`ScenarioService.analyze_what_if()`) to compute actual portfolio impact per recommendation. Lazy because each call is 4-6s. Triggered by user click, not on page load. The existing `POST /api/hedging/preview` endpoint already does this.

All three recommendation types get the "Quantify Impact" button. The preview endpoint passes the `suggested_weight` (positive or negative) through to the what-if engine.

---

## Phase A: Backend Methodology

### A1. Add `_compute_direct_offsets()` to `FactorIntelligenceService`

**File**: `services/factor_intelligence_service.py`

New method that, for each driver:
1. Looks up the proxy ETF from `industry_map` using `mapping.get("etf", mapping)` pattern (handles both simple string and structured dict entries) — industry_map is already loaded at line 1187
2. Gets the per-driver beta from `view["industry_variance"]["per_industry_group_beta"][driver_etf]` — NOT from `portfolio_factor_betas`
3. Computes a suggested short weight: `-(driver_beta * reduction_pct)` where `reduction_pct` is configurable (default 50% reduction). Assumption: sector ETF has beta ≈ 1.0 to its own sector.
4. For market driver: short SPY with weight = `-(market_beta - 1.0) * scale_factor`

Returns: `[{"ticker": "XLK", "action": "short", "type": "direct_offset", "suggested_weight": -0.05, "beta_reduction": 0.3, "driver_label": "Technology", "driver_beta": 0.6}]`

### A2. Add `_compute_beta_alternatives()` to `FactorIntelligenceService`

**File**: `services/factor_intelligence_service.py`

New method that, for each driver:
1. Resolves the driver's ETF ticker from `industry_map` via `mapping.get("etf", mapping)` (e.g., Technology → XLK)
2. Extracts the driver ETF's return series from `_shared_panel[driver_ticker]` — the panel contains raw monthly return series keyed by ETF ticker
3. For each candidate ETF column in `_shared_panel` (excluding the driver itself and tickers already in portfolio):
   - Compute pairwise beta via simple OLS: `np.polyfit(driver_returns.dropna(), candidate_returns.dropna(), 1)[0]` on aligned, non-NaN observations. **Do NOT use `compute_factor_metrics()`** — wrong function signature (`stock_returns, factor_dict` not pairwise).
   - Look up Sharpe from `_shared_perf`
4. Filter: beta < 0.5 to the overexposed factor, Sharpe > 0
5. Rank by beta ascending, then Sharpe descending
6. Return top 3

Returns: `[{"ticker": "XLU", "type": "beta_alternative", "factor_beta": 0.3, "sharpe_ratio": 0.85, "suggested_weight": 0.03, "driver_label": "Technology"}]`

### A3. Refactor `recommend_portfolio_offsets()` response shape

**File**: `services/factor_intelligence_service.py` (lines 1074-1398)

Changes:
1. **Fix existing driver-detection `industry_map` access** (line 1216): The reverse-lookup `_etf_to_sector.setdefault(_etf, ...)` currently iterates raw `industry_map` values. When entries are structured dicts, `_etf` will be the dict itself, not a ticker string. Fix by extracting the ETF ticker via `mapping.get("etf", mapping)` before building the reverse map.

2. **Add `diagnosis` dict** assembled from the `view` object:
   ```python
   diagnosis = {
       "portfolio_factor_betas": _safe_dict(view["portfolio_factor_betas"]),  # aggregate factors
       "per_industry_betas": _safe_dict(view["industry_variance"].get("per_industry_group_beta", {})),
       "industry_variance_share": _safe_dict(view["industry_variance"].get("percent_of_portfolio", {})),
       "variance_decomposition": view["variance_decomposition"],
       "portfolio_volatility": annual_vol,
       "market_beta": market_beta,
   }
   ```

3. **Group recommendations by driver and type** instead of flat list:
   - Call `_compute_direct_offsets(drivers, view, industry_map)`
   - Call `_compute_beta_alternatives(drivers, _shared_panel, _shared_perf, weights, industry_map)`
   - Existing `recommend_offsets()` calls become Type 3 (correlation alternatives)
   - Group into: `{driver_label: {"direct_offset": [...], "beta_alternatives": [...], "correlation_alternatives": [...]}}`

4. **Remove misleading calculations** (lines 1368-1372):
   - Delete `risk_reduction = abs(correlation) * 100`
   - Delete `after_var = before_var * (1 - rr/100)`
   - Correlation remains as raw value for Type 3 recs

**No backward compat needed** — the response shape changes cleanly. All consumers update together.

### A4. Update `PortfolioOffsetRecommendationResult`

**File**: `core/result_objects/factor_intelligence.py` (lines 1078-1189)

- Add `diagnosis: Dict[str, Any]` attribute
- Keep `drivers` as-is
- Change `recommendations` from flat list to grouped dict structure: `Dict[str, Dict[str, List[Dict]]]`
- Update `to_api_response()` to include diagnosis section and grouped recs
- Update `get_agent_snapshot()` to include diagnosis summary and per-type counts
- Update `to_cli_report()` for the three recommendation types

### A5. Update MCP tool response, `build_ai_recommendations()`, and fast path

**File**: `mcp_tools/factor_intelligence.py`

- Update `get_factor_recommendations(mode="portfolio")` to thread the new response shape through all format modes (summary, full, agent, report)
- Update `build_ai_recommendations()` helper (line 246) to:
  - Transform the new grouped recommendation format (not flat list)
  - Fix `percent_of_portfolio` labeling across **all sites** — it is **variance share**, not weight/exposure/concentration. Current code mislabels it at lines 441 (title), 443 (description), 446 (impact), and 449 (actions). Rename to "risk contribution" or "variance share" consistently.
  - Handle negative `suggested_weight` for direct offsets: don't emit "Consider adding … position" (line 480) for shorts. Emit "Consider shorting …" or similar.
  - Add `recommendationType` field to each recommendation's AI output for agent-side filtering.
- The agent snapshot should lead with diagnosis
- **Fix the MCP fast path** (`analysis_result` at line 1156): The fast path sets `industry_map = {}` (line 1164), which means direct offsets and beta alternatives can't look up ETFs. Fix: **move `industry_map = load_industry_etf_map()` before the `if analysis_result` branch** (i.e., between lines 1155 and 1156). The load is a pure YAML/DB lookup (~1ms), safe to call unconditionally. Then both the fast path and slow path have `industry_map` available for `_compute_direct_offsets()` and `_compute_beta_alternatives()`.

### A6. Update flags

**File**: `core/factor_recommendation_flags.py`

Add new flags:
- `direct_offset_available` (info) — when a sector ETF directly offsets the driver
- `no_low_beta_alternatives` (warning) — when no beta alternatives found
- `high_factor_concentration` (warning) — when a single factor explains >40% variance

### A7. Update Pydantic models and route handler

**File**: `models/factor_intelligence_models.py` — update or add response model if the route validates response shape
**File**: `routes/factor_intelligence.py` (line 228) — `recommend_portfolio_offsets()` route handler calls `result.to_api_response()` which will carry the new shape. Verify no response_model annotation constrains the output.

---

## Phase B: Frontend Redesign

### B1. Update TypeScript types

**File**: `frontend/packages/chassis/src/types/index.ts`

Add types for the new response:
```typescript
interface DiagnosisData {
  portfolioFactorBetas: Record<string, number>;
  perIndustryBetas: Record<string, number>;
  industryVarianceShare: Record<string, number>;  // variance share, NOT weight
  varianceDecomposition: { factor_pct: number; idiosyncratic_pct: number };
  portfolioVolatility: number | null;
  marketBeta: number | null;
}

interface GroupedRecommendations {
  [driverLabel: string]: {
    direct_offset: DirectOffsetRecommendation[];
    beta_alternatives: BetaAlternativeRecommendation[];
    correlation_alternatives: CorrelationAlternativeRecommendation[];
  };
}
```

Update `PortfolioHedgingResponse` to include `diagnosis` and grouped `recommendations`.

### B2. Update `HedgingAdapter.ts`

**File**: `frontend/packages/connectors/src/adapters/HedgingAdapter.ts`

Major refactor:
- Parse new `diagnosis` section into `DiagnosisData`
- Transform grouped recommendations (3 types per driver) into display objects
- Remove `toEfficiency()` (correlation-only mapping) — replace with type-based display
- Remove `byCorrelationThenSharpe()` single-best-per-driver selection — now preserve all types
- All recommendation types produce `HedgeStrategy` objects with a `recommendationType` field ("direct_offset" | "beta_alternative" | "correlation_alternative")

### B3. Update `useHedgingRecommendations.ts` hook output

**File**: `frontend/packages/connectors/src/features/hedging/hooks/useHedgingRecommendations.ts`

Expose `diagnosis` data alongside strategies. Update the returned object shape.

### B4. Update `APIService.ts`

**File**: `frontend/packages/chassis/src/services/APIService.ts` (line 1445)

Update `getHedgingRecommendations()` return type to match new `PortfolioHedgingResponse`.

### B5. Redesign `HedgeTool.tsx`

**File**: `frontend/packages/ui/src/components/portfolio/scenarios/tools/HedgeTool.tsx`

New layout:

**Section 1 — Diagnosis**
- `ScenarioInsightCard` with headline: "Portfolio has X market beta with Y% of risk from Z"
- Metric tiles for: portfolio vol, market beta, top 2-3 industry risk drivers with **variance share %** (not weight %)

**Section 2 — Per-Driver Recommendations**
- For each driver, a card section with:
  - Driver header: "Technology (35% of portfolio risk)" — note: variance share, not weight
  - Three sub-sections (stacked):
    - **Direct Offset**: "Short XLK at 5% to reduce tech beta by 0.3" — full action buttons (chaining supported)
    - **Beta Alternatives**: 2-3 candidates with low beta, Sharpe ratio
    - **Diversification**: correlation-based alternatives
  - Per-recommendation: "Quantify Impact" button (lazy what-if), "Test in What-If", "Analyze & Execute"

**Section 3 — Actions** (keep existing patterns)
- "Ask AI about this" on insight card
- "Test in What-If" navigates with delta context (existing logic — passes negative deltas for shorts)
- "Analyze & Execute" opens HedgeWorkflowDialog (existing)

### B6. Update `StressTestTool.tsx` consumer

**File**: `frontend/packages/ui/src/components/portfolio/scenarios/tools/StressTestTool.tsx` (line 270)

StressTestTool picks a `bestHedge` from `useHedgingRecommendations()`. Since the hook output shape changes (strategies now have `recommendationType` field, grouped by driver/type instead of flat best-per-driver), update StressTestTool's hedge selection logic to:
- Filter for `recommendationType !== "direct_offset"` (prefer long-position hedges for stress test context)
- Pick the best from beta_alternatives or correlation_alternatives by the same sorting logic

### B7. Lazy quantification

Reuse existing `POST /api/hedging/preview` for on-demand impact calculation. All three types get "Quantify Impact" — the preview endpoint receives `suggested_weight` (positive or negative) and returns vol/beta/concentration change. Reuse `useHedgePreview` hook.

### B8. Update resolver and data source types

**File**: `frontend/packages/connectors/src/resolver/registry.ts` (line 822) — update resolver
**File**: `frontend/packages/chassis/src/catalog/types.ts` — update `HedgingRecommendationsSourceData`
**File**: `frontend/packages/chassis/src/catalog/__tests__/descriptors.test.ts` — update catalog descriptor assertions that pin the old hedging shape

---

## What Stays Unchanged

| Component | Why |
|-----------|-----|
| `HedgeWorkflowDialog.tsx` (780 lines) | 4-step execution flow structure stays, but Step 1 review copy updated to be type-aware (see critical files). Steps 2-4 unchanged. |
| `POST /api/hedging/preview` | Already does what-if quantification — reuse for lazy impact |
| `POST /api/hedging/execute` | Trading flow independent |
| `build_portfolio_view()` | Core engine, reused as-is for diagnosis data |
| `config/industry_to_etf.yaml` | 175+ mappings, reused for direct offset lookups |
| `useHedgePreview` hook | Reused for lazy quantification |
| `useHedgeMonitor` hook | Separate concern (option position monitoring) |
| State persistence | Already works via `toolRunParams` |

---

## Critical Files

| File | Change |
|------|--------|
| `services/factor_intelligence_service.py` | Core: add `_compute_direct_offsets()`, `_compute_beta_alternatives()`, refactor `recommend_portfolio_offsets()`, fix `industry_map` access in driver detection |
| `core/result_objects/factor_intelligence.py` | Add `diagnosis`, grouped recs in `PortfolioOffsetRecommendationResult` |
| `core/factor_recommendation_flags.py` | New flags for recommendation types |
| `mcp_tools/factor_intelligence.py` | Thread new response shape, update `build_ai_recommendations()` (variance-share labels, short-position copy), widen fast path for `industry_map` |
| `models/factor_intelligence_models.py` | Verify/update Pydantic response models |
| `routes/factor_intelligence.py` | Verify route handler passes new shape |
| `frontend/.../HedgeTool.tsx` | Frontend redesign: diagnosis + per-driver + quantify |
| `frontend/.../StressTestTool.tsx` | Update `bestHedge` selection for new strategy shape |
| `frontend/.../HedgingAdapter.ts` | Transform new response shape, add `recommendationType` |
| `frontend/.../useHedgingRecommendations.ts` | Expose diagnosis in hook output |
| `frontend/.../types/index.ts` | New TypeScript types (DiagnosisData, GroupedRecommendations) |
| `frontend/.../catalog/types.ts` | Update `HedgingRecommendationsSourceData` |
| `frontend/.../APIService.ts` | Update return type |
| `frontend/.../resolver/registry.ts` | Update resolver |
| `frontend/.../catalog/descriptors.ts` | Update hedging descriptor to expose `diagnosis` field (currently only `strategies`, `drivers`, `analysisMetadata`) |
| `frontend/.../HedgeWorkflowDialog.tsx` | Make Step 1 review copy type-aware (beta/correlation/offset metrics) |

---

## Tests That Need Updating

**Backend** (response shape change):
- `tests/services/test_factor_intelligence_service.py`
- `tests/mcp_tools/test_factor_intelligence.py`
- `tests/mcp_tools/test_factor_recs_agent_format.py`
- `tests/core/test_factor_recs_agent_snapshot.py`
- `tests/core/test_factor_recommendation_flags.py`

**Frontend** (adapter/hook/resolver shape change):
- `frontend/packages/connectors/src/adapters/__tests__/HedgingAdapter.test.ts`
- `frontend/packages/connectors/src/features/hedging/__tests__/useHedgingRecommendations.test.tsx`
- `frontend/packages/connectors/src/resolver/__tests__/hedgingResolver.test.ts`
- `frontend/packages/connectors/src/resolver/__tests__/useDataSource.test.tsx` — pins old hedging shape at line 79
- `frontend/packages/chassis/src/catalog/__tests__/descriptors.test.ts` — pins old hedging field assertions

**New tests to add**:
- Unit: `_compute_direct_offsets()` — given known `per_industry_group_beta` + ETF map → correct short weight
- Unit: `_compute_beta_alternatives()` — given panel with driver ETF series + perf profiles → ranked low-beta candidates via simple OLS
- Integration: `recommend_portfolio_offsets()` — tech-heavy portfolio → diagnosis + 3 rec types per driver
- Verify `risk_reduction = abs(corr) * 100` is removed
- Adapter: fixtures with new response shape → correct diagnosis + grouped strategies

---

## Phasing

**Recommended**: Backend (Phase A) and Frontend (Phase B) ship together or in quick succession. No backward compat — the response shape changes cleanly and all consumers update together.

Each phase goes through: plan → Codex review → implement → test → commit.

## Parallel Workstream: Short Position Support

A separate task (assigned to another Claude session) will add short-position support to the What-If and execution pipeline. This plan wires direct offset buttons and passes negative deltas through — the parallel task removes the clamps:

1. **HedgeTool.tsx:169** — delta formatting clamps negatives to `+0%`
2. **routes/hedging.py:135** — `_build_target_weights()` floors target weight at zero
3. **mcp_tools/trading_helpers.py:97,99** — rebalance sell cap to held shares

Until that workstream lands, direct offset "Test in What-If" and "Analyze & Execute" will pass the negative value but the downstream may not process it correctly. This is a known, documented limitation.

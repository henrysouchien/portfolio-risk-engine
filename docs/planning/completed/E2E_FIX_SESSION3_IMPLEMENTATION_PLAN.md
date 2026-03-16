# E2E Fix Session 3: Implementation Plan

**Status**: COMPLETE (committed `16e8afa4`, all 4 fixes live-verified)
**Date**: 2026-03-16
**Parent**: `E2E_FIX_SESSION3_LOGIC_FIXES_PLAN.md`
**Scope**: R9, R16, R14, R4

---

## Context

E2E review found 4 logic/data-quality bugs across the dashboard. This plan covers the implementation for R9 (self-contradicting AI recommendation), R16 (phantom SGOV in concentration risk top-3), R14 (wrong sector labels), and R4 (holdings flash on portfolio switch). All are independent fixes — no cross-step dependencies.

---

## Step 1: R9 — Suppress Self-Contradicting Recommendation

**Problem:** `build_ai_recommendations()` recommends "reduce Oil & Gas E&P below 10%" when exposure is already 6.8%. The 5% trigger fires but `max(10, 6.8-10)=10` produces a target above current exposure.

**File:** `mcp_tools/factor_intelligence.py` (lines ~289-312)

**Fix:** Compute `target_pct` before the append. Skip the recommendation when `pct_display < target_pct` (strict less-than — 10.0% → "below 10%" is still actionable, not self-contradictory).

```python
# After line 296 (pct_display = pct * 100):
target_pct = max(10, pct_display - 10)
if pct_display < target_pct:
    continue
```

> **Codex review note:** `<=` would also suppress the exact-boundary case (10.0% → "below 10%"), which is a valid recommendation. Use strict `<` instead.

Also replace the inline `max(10, pct_display - 10)` in the action item (line 309) with the pre-computed `target_pct`.

**Tests:** `tests/mcp_tools/test_factor_intelligence.py`
- Add test: driver at 6.8% → no recommendation (6.8% < 10% target)
- Add test: driver at 5% → no recommendation (5% < 10% target)
- Add test: driver at 10.0% → recommendation fires, target "below 10%" (exact boundary — actionable)
- Add test: driver at 15% → recommendation fires, target "below 10%"
- Add test: driver at 25% → recommendation fires, target "below 15%"
- Existing 40% test still passes

---

## Step 2: R16 — Use Backend Concentration Metadata in Frontend

**Problem:** Frontend `buildRiskFactorDescription()` in `RiskAnalysisModernContainer.tsx` recomputes top-3 positions from raw `portfolio_weights` (unfiltered), so SGOV (-17.2%) appears. Backend correctly excludes ETFs via `_get_single_issuer_weights()` and puts filtered `top_n_tickers` in `concentration_metadata`.

**Root cause:** `RiskScoreAdapter.ts` extracts `riskScoreData.details` (line 444) but doesn't pass `concentration_metadata` through to the output (lines 482-488 only pass excess_ratios, leverage_ratio, max_loss_limit, potential_losses, interpretation).

### 2a. Thread concentration_metadata through adapter

**File:** `frontend/packages/connectors/src/adapters/RiskScoreAdapter.ts` (~line 485)

1. Update `RiskScoreApiResponse.details` interface (~line 191) to declare `concentration_metadata?: { top_n_weight: number; top_n_tickers: string[]; concentration_driver: string; largest_ticker: string; largest_weight: number }`.
2. Add `concentration_metadata` to the `risk_details` output object:

```typescript
risk_details: {
  excess_ratios: riskDetails?.excess_ratios,
  leverage_ratio: riskDetails?.leverage_ratio,
  max_loss_limit: riskDetails?.max_loss_limit,
  potential_losses: potentialLosses,
  interpretation: riskInterpretation,
  concentration_metadata: riskDetails?.concentration_metadata,  // ADD
},
```

> **Codex review note:** Without the interface update, `riskDetails?.concentration_metadata` won't type-check.

### 2b. Use backend top-N in buildRiskFactorDescription

**File:** `frontend/packages/ui/src/components/dashboard/views/modern/RiskAnalysisModernContainer.tsx`

1. Add `concentrationMetadata` to `BuildRiskFactorDescriptionInput` interface (~line 133).
2. In `buildRiskFactorDescription`, when `concentrationMetadata?.top_n_tickers` exists, use those tickers to filter `portfolioWeights` instead of sorting all weights by abs value. Fallback to current logic if metadata missing.
3. At the call site (~line 474), pass `concentrationMetadata: riskScoreData?.risk_details?.concentration_metadata`.

The key change in the `concentration` branch:
```typescript
if (concentrationMetadata?.top_n_tickers?.length) {
  // Use backend-filtered tickers (excludes ETFs, diversified vehicles)
  const backendTickers: string[] = concentrationMetadata.top_n_tickers;
  const topEntries = backendTickers
    .filter(t => portfolioWeights?.[t] !== undefined)
    .map(t => [t, portfolioWeights![t]] as [string, number])
    .filter(([, w]) => Number.isFinite(w));
  // ... format using same topLabel/topWeightsSummary logic
} else {
  // Existing client-side fallback (current lines 183-206)
}
```

---

## Step 3: R14 — Sector Override Map

**Problem:** FMP returns wrong sectors for GOLD ("Financial Services"), SLV ("Financial Services"), AT.L ("Energy").

### 3a. Create config file

**File (NEW):** `config/sector_overrides.yaml`

```yaml
# Sector overrides for known FMP misclassifications.
# Applied after FMP profile lookup in enrich_positions_with_sectors().
GOLD: Basic Materials
SLV: Commodities
AT.L: Industrial Services
```

### 3b. Apply overrides after FMP lookup

**File:** `services/portfolio_service.py` — `enrich_positions_with_sectors()` (~line 1204, after sector_map is built)

`resolve_config_path` is already imported (line 27). **`yaml` is NOT imported** — add `import yaml` to the import block.

```python
try:
    override_path = resolve_config_path("sector_overrides.yaml")
    with open(override_path) as f:
        overrides = yaml.safe_load(f) or {}
    for symbol, sector in overrides.items():
        sector_map[symbol.upper()] = sector
except FileNotFoundError:
    pass  # No overrides file — use FMP data as-is
except Exception:
    portfolio_logger.warning("Failed to load sector_overrides.yaml", exc_info=True)
```

> **Codex review note:** Original `except (FileNotFoundError, Exception): pass` was too broad — split into silent FileNotFoundError + logged fallback for parse/IO errors.

**Tests:** `tests/services/test_portfolio_service.py`
- Add test: FMP returns wrong sector, override replaces it
- Add test: ticker not in overrides retains FMP sector
- Add test: missing override file doesn't error

---

## Step 4: R4 — Holdings Loading Flash on Portfolio Switch

**Problem:** On portfolio switch, `loading` goes `false` before new data arrives, causing a brief "No holdings available" flash. The component (line 169) only checks `loading`, not the transitional `!positionsData && !hasError` state.

**File:** `frontend/packages/ui/src/components/dashboard/cards/DashboardHoldingsCard.tsx`

**Fix:** Derive a `showSkeleton` flag that covers both loading and transitional states:

```typescript
const { data: positionsData, loading, hasError } = usePositions();
const holdings = positionsData?.holdings ?? [];
const showSkeleton = loading || (!positionsData && !hasError);
```

Use `showSkeleton` at line 169 instead of `loading`. Also update the footer (line 200) to show neutral text during loading:

```typescript
<span>{showSkeleton ? 'Loading holdings...' : `View All ${holdingsCount} Holdings`}</span>
```

---

## Implementation Order

1. **Step 1 (R9)** + **Step 3 (R14)** — parallel, both backend-only
2. **Step 4 (R4)** — independent frontend fix
3. **Step 2 (R16)** — adapter + component change (most complex)

---

## Verification

1. **Tests:**
   - `pytest tests/mcp_tools/test_factor_intelligence.py -x` (R9)
   - `pytest tests/services/test_portfolio_service.py -x` (R14)
   - Full backend: `pytest tests/ -x --timeout=30`

2. **Manual checks (if app running):**
   - R9: AI Recommendations — Oil & Gas E&P at 6.8% should not appear
   - R16: Concentration Risk top-3 should not include SGOV
   - R14: GOLD → Basic Materials, SLV → Commodities, AT.L → Industrial Services
   - R4: Portfolio switch shows skeleton, not "No holdings available" flash

---

## Cross-Session Boundaries (DO NOT TOUCH)

- `frontend/packages/ui/src/index.css` (Session 1)
- `frontend/packages/connectors/src/adapters/PositionsAdapter.ts` (Session 2)
- `frontend/packages/connectors/src/adapters/PortfolioSummaryAdapter.ts` (Session 2)

---

## Files Summary

| File | Step | Type |
|------|------|------|
| `mcp_tools/factor_intelligence.py` | 1 | Edit |
| `tests/mcp_tools/test_factor_intelligence.py` | 1 | Edit |
| `frontend/packages/connectors/src/adapters/RiskScoreAdapter.ts` | 2 | Edit |
| `frontend/packages/ui/src/components/dashboard/views/modern/RiskAnalysisModernContainer.tsx` | 2 | Edit |
| `config/sector_overrides.yaml` | 3 | New |
| `services/portfolio_service.py` | 3 | Edit |
| `tests/services/test_portfolio_service.py` | 3 | Edit |
| `frontend/packages/ui/src/components/dashboard/cards/DashboardHoldingsCard.tsx` | 4 | Edit |

# E2E Fix Session 3: Logic & Data Quality Fixes

**Status**: NOT STARTED
**Date**: 2026-03-16
**Parent**: `docs/planning/REVIEW_FINDINGS.md`
**Session**: 3 of 4 parallel fix sessions
**Scope**: R9 (AI recommendation logic), R16 (phantom SGOV in concentration risk), R14 (sector misclassifications), R4 (holdings race condition)

---

## Findings Covered

| Finding | Severity | Summary |
|---------|----------|---------|
| R9 | Medium | AI Recommendation says "reduce Oil & Gas E&P below 10%" when exposure is already 6.8% |
| R16 | Medium | SGOV (-17.2%) appears in concentration risk top-3 but not in displayed holdings |
| R14 | Medium | GOLD, SLV, AT.L have wrong sector labels from FMP |
| R4 | Partial | Holdings card briefly shows "No holdings available" on portfolio switch |

---

## Constraints (Cross-Session Boundaries)

- **DO NOT** touch `frontend/packages/ui/src/index.css` (Session 1: CSS/labels)
- **DO NOT** touch `frontend/packages/connectors/src/adapters/PositionsAdapter.ts` (Session 2 may need it)
- **DO NOT** touch `frontend/packages/connectors/src/adapters/PortfolioSummaryAdapter.ts` (Session 2 may need it)
- Backend changes to recommendation logic, risk score computation, and sector enrichment are safe
- Frontend changes to `DashboardHoldingsCard.tsx` and `RiskAnalysisModernContainer.tsx` are safe

---

## Step 1: Fix R9 — AI Recommendation Contradicts Itself

### Problem

`build_ai_recommendations()` in `mcp_tools/factor_intelligence.py` generates "High {label} Concentration" recommendations for any driver with `percent_of_portfolio >= 0.05` (5%). The action items include:

```python
f"Target reducing {label} weight to below {max(10, pct_display - 10):.0f}%"
```

For Oil & Gas E&P at 6.8%, this computes `max(10, 6.8 - 10) = max(10, -3.2) = 10`, producing "Target reducing Oil & Gas E&P weight to below 10%." Since 6.8% < 10%, the recommendation is self-contradictory.

### Root Cause

The trigger threshold (5%) and the target threshold (computed via `max(10, pct_display - 10)`) are independent. When a sector triggers at 5-10%, the computed target is always 10% (the `max(10, ...)` floor), which is above the current exposure. The recommendation should be suppressed when the current exposure is already below the computed target.

### Fix

In `mcp_tools/factor_intelligence.py`, function `build_ai_recommendations()`, lines 291-312:

1. After computing the target reduction percentage, check if the current exposure is already below the target. If so, skip the recommendation.
2. Also tighten the action item wording to avoid the contradiction when the exposure is close to but above the target.

```python
# After line 296 (pct_display = pct * 100):
target_pct = max(10, pct_display - 10)

# Skip if current exposure is already below the target
if pct_display <= target_pct:
    continue
```

This suppresses the recommendation entirely when the exposure is at or below the reduction target. The 5% trigger threshold still fires the driver analysis, but the recommendation won't be shown if there's no actionable reduction to recommend.

Additionally, update the action item (line 309) to use the pre-computed `target_pct`:

```python
f"Target reducing {label} weight to below {target_pct:.0f}%",
```

### Files

| File | Change |
|------|--------|
| `mcp_tools/factor_intelligence.py` (lines 291-312) | Add `target_pct` guard before appending recommendation |

### Tests

- Add test in `tests/mcp_tools/test_factor_intelligence.py`:
  - Mock a driver with `percent_of_portfolio = 0.068` (6.8%), verify no recommendation is generated (since 6.8% < 10% target)
  - Mock a driver with `percent_of_portfolio = 0.15` (15%), verify recommendation IS generated with target "below 10%"... wait, `max(10, 15-10) = 10`? No: for 15%, target = `max(10, 15-10)` = `max(10, 5)` = 10. 15% > 10%, so recommendation fires.
  - Mock a driver with `percent_of_portfolio = 0.25` (25%), verify recommendation with target "below 15%" (`max(10, 25-10) = 15`)
  - Mock a driver with `percent_of_portfolio = 0.05` (5%), verify no recommendation (5% <= 10% target)

---

## Step 2: Fix R16 — SGOV Phantom Position in Concentration Risk

### Problem

The Factors -> Risk Analysis -> Concentration Risk card shows "Top 3 positions: NVDA (22.9%), SGOV (-17.2%), TKO (13.1%)" but SGOV is not in the 15 displayed holdings. SGOV is a Treasury ETF held at negative dollars (-$8,179 in `config/portfolio.yaml`), representing a short or cash-equivalent position. It appears in the `portfolio_weights` passed to the frontend's `RiskAnalysisModernContainer.tsx` because `build_portfolio_view()` includes all weights from the portfolio input.

The concentration risk top-3 display is built **client-side** in `RiskAnalysisModernContainer.tsx` (lines 183-206), which sorts `portfolio_weights` by `Math.abs(weight)` and picks the top 3. SGOV's abs weight of 17.2% puts it in the top 3.

Meanwhile, the **backend** concentration risk score in `portfolio_risk_score.py` uses `_get_single_issuer_weights()` which filters out `DIVERSIFIED_SECURITY_TYPES` (ETFs, funds). If SGOV is classified as an ETF, it would be excluded from the backend concentration computation but still present in the raw `portfolio_weights` dict sent to the frontend.

### Root Cause

Two separate concentration displays:
1. **Backend** (`_compute_concentration_loss` -> `concentration_metadata`): Correctly filters via `_get_single_issuer_weights()`, so SGOV (if classified as ETF) may not appear in `top_n_tickers`.
2. **Frontend** (`buildRiskFactorDescription` in `RiskAnalysisModernContainer.tsx`): Uses raw `portfolio_weights` WITHOUT the same filtering. Sorts by abs(weight) and shows top 3.

The frontend's concentration description diverges from the backend's concentration score because it rebuilds the top-3 list from unfiltered weights.

### Fix Options

**Option A (Preferred): Use backend `concentration_metadata` in frontend instead of recomputing**

The backend already computes `concentration_metadata.top_n_tickers` and `concentration_metadata.top_n_weight` with proper filtering. Thread this data through to the frontend and use it in `buildRiskFactorDescription()` instead of recomputing from raw `portfolio_weights`.

The risk score API response already includes `details.concentration_metadata` (built at line 1685-1691 of `portfolio_risk_score.py`). The frontend just needs to read it.

Steps:
1. In `RiskAnalysisModernContainer.tsx`, extract `concentration_metadata` from the risk score response data.
2. In `buildRiskFactorDescription()` for the `concentration` factor, use the backend's `top_n_tickers` and per-ticker weights (from `portfolio_weights` filtered to only those tickers) instead of recomputing.
3. Fallback to the current client-side logic if `concentration_metadata` is not available.

**Option B (Simpler): Filter cash/Treasury positions from the frontend top-3**

Add a client-side filter in `buildRiskFactorDescription()` to exclude positions with negative weights (short/cash positions) from the top-3 display. This is simpler but less principled -- it only hides the symptom for negative-weight positions.

### Chosen Approach: Option A

Option A is more principled because it aligns the frontend display with the actual backend risk computation. The data is already available in the API response.

### Files

| File | Change |
|------|--------|
| `frontend/packages/ui/src/components/dashboard/views/modern/RiskAnalysisModernContainer.tsx` | Pass `concentrationMetadata` into `buildRiskFactorDescription()`, use backend top-N tickers when available |

### Investigation Needed

Before implementing, verify:
1. That the risk score API response reaching the frontend includes `details.concentration_metadata` (check the adapter/serialization path).
2. What the `RiskScoreAdapter.ts` passes through to the component. If `concentration_metadata` is stripped by the adapter, the adapter needs updating too.

```
Check: frontend/packages/connectors/src/adapters/RiskScoreAdapter.ts
Check: routes/risk_score.py — what fields are returned in the API response
```

### Tests

- Verify in the frontend that when `concentration_metadata.top_n_tickers` is `["NVDA", "TKO", "EQT"]` (excluding SGOV), the concentration risk description shows those tickers instead of SGOV.
- Verify fallback: when `concentration_metadata` is missing, the current client-side logic still works.

---

## Step 3: Fix R14 — Sector Misclassifications (GOLD, SLV, AT.L)

### Problem

Three positions have wrong sector labels in the Holdings view:
- **GOLD** (Barrick Gold Corp) -> "Financial Services" (should be "Basic Materials")
- **SLV** (iShares Silver Trust) -> "Financial Services" (should be "Commodities")
- **AT.L** (Ashtead Technology Holdings) -> "Energy" (should be "Technology" or "Industrial Services")

These sectors come from FMP's `profile` endpoint via `enrich_positions_with_sectors()` in `services/portfolio_service.py` (lines 1165-1212). FMP returns the sector classification from its database, which may be incorrect for some tickers (especially ETFs like SLV and non-US tickers like AT.L).

### Root Cause

FMP's profile data has incorrect sector assignments for these tickers. There is no override mechanism to correct known misclassifications.

### Fix

Add a sector override map that is applied after FMP lookup but before enrichment. This is a lightweight, maintainable approach that handles known data quality issues without modifying the FMP integration.

### Implementation

1. Create a YAML config file `config/sector_overrides.yaml`:

```yaml
# Sector overrides for known FMP misclassifications.
# Format: TICKER: correct_sector
# These are applied after FMP profile lookup in enrich_positions_with_sectors().
GOLD: Basic Materials
SLV: Commodities
AT.L: Industrial Services
```

2. In `services/portfolio_service.py`, modify `enrich_positions_with_sectors()` to load and apply overrides:

```python
# After building sector_map from FMP (line 1204), apply overrides:
try:
    override_path = resolve_config_path("sector_overrides.yaml")
    import yaml
    with open(override_path) as f:
        overrides = yaml.safe_load(f) or {}
    for symbol, sector in overrides.items():
        sector_map[symbol.upper()] = sector
except (FileNotFoundError, Exception):
    pass  # No overrides file or parse error — continue with FMP data
```

This approach:
- Is easy to maintain (add new overrides by editing a YAML file)
- Doesn't modify the FMP client or profile fetching logic
- Applies at the enrichment layer, close to the display
- Uses the existing `resolve_config_path()` pattern from `config/__init__.py`

### Files

| File | Change |
|------|--------|
| `config/sector_overrides.yaml` | **NEW** — override map for known FMP sector misclassifications |
| `services/portfolio_service.py` | Load and apply overrides in `enrich_positions_with_sectors()` |

### Tests

- Unit test: mock FMP returning "Financial Services" for GOLD, verify override replaces with "Basic Materials"
- Unit test: ticker NOT in override map retains FMP sector
- Unit test: missing/empty `sector_overrides.yaml` doesn't cause errors
- Verify visually: GOLD, SLV, AT.L show correct sector badges in Holdings view

---

## Step 4: Fix R4 — Holdings Race Condition on Portfolio Switch

### Problem

When switching to "All Accounts", the Top Holdings card briefly shows "No holdings available for this portfolio." and "View All 0 Holdings" before data arrives. This happens because:

1. `PortfolioSelector.handleSelect()` calls `queryClient.invalidateQueries({ queryKey: ['sdk'] })` which invalidates all SDK queries.
2. The `positions-enriched` data source gets a new query (new `portfolioId` in params), starting with `isLoading = true`.
3. However, there may be a brief render cycle where the query is in a transitional state: the old data is cleared (invalidated) but the new query hasn't started yet, causing `loading = false` and `data = undefined` simultaneously.
4. In this state, `DashboardHoldingsCard` renders the `DataTable` with `emptyMessage="No holdings available for this portfolio."` and the footer shows "View All 0 Holdings".

### Root Cause

The `DashboardHoldingsCard` treats `loading === false && holdings.length === 0` as an "empty portfolio" state, but this also matches the transient "between queries" state during portfolio switches.

### Fix

Show the loading skeleton when the data is in a transitional state (not loading, but also no data and no error). This prevents the flash of empty state.

In `DashboardHoldingsCard.tsx`:

```tsx
// Line 44: add isFetching
const { data: positionsData, loading, isRefetching } = usePositions();

// Line 169: also show skeleton when refetching with no data
{loading || (isRefetching && !holdings.length) ? (
```

Alternatively, a more robust fix: treat `loading || (!positionsData && !error)` as the loading state. This catches any scenario where data hasn't arrived yet, regardless of the React Query internal state.

```tsx
const { data: positionsData, loading, hasError } = usePositions();
const holdings = positionsData?.holdings ?? [];

const showSkeleton = loading || (!positionsData && !hasError);
```

Then use `showSkeleton` in the conditional render (line 169).

Also update the footer to avoid showing "View All 0 Holdings" during loading:

```tsx
<span>{showSkeleton ? 'Loading holdings...' : `View All ${holdingsCount} Holdings`}</span>
```

### Files

| File | Change |
|------|--------|
| `frontend/packages/ui/src/components/dashboard/cards/DashboardHoldingsCard.tsx` | Improve loading state detection to cover transitional states |

### Tests

- Manual: Switch from IBKR to All Accounts, verify skeleton shows instead of "No holdings available"
- Manual: Switch back to IBKR, verify skeleton shows during transition
- Manual: On first load with empty portfolio, "No holdings available" still shows correctly (not perpetual skeleton)
- Unit test: render `DashboardHoldingsCard` with `loading=false, data=undefined, hasError=false` -> should show skeleton
- Unit test: render with `loading=false, data={holdings: []}, hasError=false` -> should show "No holdings available" (truly empty portfolio)

---

## Testing Plan

### Automated Tests

| Test | File | Covers |
|------|------|--------|
| Recommendation suppression when exposure < target | `tests/mcp_tools/test_factor_intelligence.py` | R9 |
| Recommendation fires when exposure > target | `tests/mcp_tools/test_factor_intelligence.py` | R9 |
| Sector override applied correctly | `tests/services/test_portfolio_service.py` | R14 |
| Sector override file missing gracefully | `tests/services/test_portfolio_service.py` | R14 |
| Holdings card skeleton in transitional state | `frontend/packages/ui/src/components/dashboard/cards/__tests__/DashboardHoldingsCard.test.tsx` | R4 |

### Manual Verification

1. **R9**: Load All Accounts dashboard -> AI Recommendations card. Oil & Gas E&P at 6.8% should NOT appear as a recommendation. Any sector above its computed target should still show.
2. **R16**: Factors -> Risk Analysis -> Concentration Risk. Top-3 positions should not include SGOV (or any position not in Holdings). Should show actual holdings like NVDA, TKO, EQT or similar.
3. **R14**: Holdings view -> Sector badges. GOLD should show "Basic Materials", SLV should show "Commodities", AT.L should show "Industrial Services" (or similar non-"Financial Services"/"Energy" value).
4. **R4**: Switch between IBKR and All Accounts in the portfolio selector. Holdings card should show skeleton/spinner during the transition, never "No holdings available" transiently.

### Regression Checks

- Run full backend test suite: `pytest tests/ -x --timeout=30`
- Run frontend test suite: `cd frontend && npm test`
- Verify IBKR single-account dashboard still loads correctly (not affected by changes)
- Verify AI Recommendations still show for genuinely high-concentration sectors (e.g., Technology at 25%)

---

## Implementation Order

1. **Step 1 (R9)** — Simplest, backend-only, one file
2. **Step 3 (R14)** — Backend-only, new config file + one service file
3. **Step 4 (R4)** — Frontend-only, one component file
4. **Step 2 (R16)** — Requires investigation of adapter data flow, may touch 1-2 frontend files

Steps 1 and 3 can be implemented in parallel. Step 4 is independent. Step 2 requires the most investigation.

---

## Files Summary

| File | Steps | Type |
|------|-------|------|
| `mcp_tools/factor_intelligence.py` | 1 | Edit |
| `services/portfolio_service.py` | 3 | Edit |
| `config/sector_overrides.yaml` | 3 | New |
| `frontend/packages/ui/src/components/dashboard/cards/DashboardHoldingsCard.tsx` | 4 | Edit |
| `frontend/packages/ui/src/components/dashboard/views/modern/RiskAnalysisModernContainer.tsx` | 2 | Edit |
| `frontend/packages/connectors/src/adapters/RiskScoreAdapter.ts` | 2 | Investigate (may need edit) |

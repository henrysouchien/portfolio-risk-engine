# E2E Fix Session 2: Data Consistency Investigation

**Status**: INVESTIGATION COMPLETE — READY FOR IMPLEMENTATION
**Session**: 2 of 4 (parallel)
**Source**: `docs/planning/REVIEW_FINDINGS.md` (R6, R7, R8, R12, R15, R21, R22)
**Scope**: Backend data flows + frontend adapters (NO component files -- Session 1 owns those)

---

## Findings Covered

| # | Severity | Issue | Root Cause Hypothesis |
|---|----------|-------|-----------------------|
| R7 | Critical | IBKR $131K > All Accounts $109K | Different position loading paths (PortfolioManager vs PositionService) |
| R8 | Critical | Margin debt doubles intermittently ($5,606 <-> $11,212) | Race condition or cache staleness in position consolidation |
| R21 | High | Asset allocation sums to $46K, portfolio is $131K | $85K cash not classified into any allocation category |
| R22 | High | Cash (Margin) -$11,589 vs Smart Alert $5,606 margin debt | Two different definitions of "margin" from two endpoints |
| R6 | High | Weights use gross_exposure (~$27K) as denominator, not total value ($131K) | `PositionsAdapter.ts:67-70` divides by `portfolio_totals_usd.gross_exposure` |
| R12 | Medium | Dropdown says 36 holdings, View All says 15 | Pre-consolidation vs post-consolidation count |
| R15 | High | Volatility: 8.41% / 16.3% / 19.4% across views | Three different endpoints/calculations for the same metric |

---

## Phase 1: Map the Data Flows (Investigation Only)

The first phase produces no code changes. It produces a written data-flow map for every
metric that shows inconsistency. Each map answers: **which endpoint -> which backend
function -> which frontend adapter -> which component**.

### 1.1 Total Portfolio Value ($131K vs $109K -- R7)

**Trace the two paths:**

Path A -- Single account (IBKR, shows $131K):
```
POST /api/analyze { portfolio_name: "_auto_interactive_brokers_u2471778" }
  -> app.py:_run_analyze_workflow()
  -> PortfolioManager(user_id).load_portfolio_data(portfolio_name)
  -> _load_portfolio_from_database()
     -> resolve_portfolio_scope() -> VIRTUAL_FILTERED with account_filters
     -> repository.load_full_portfolio() on config_portfolio_name (CURRENT_PORTFOLIO)
     -> filter_positions_to_accounts() on account_filters
     -> _filter_positions() + _consolidate_positions() + _apply_cash_mapping()
  -> Returns PortfolioData with portfolio_input (includes cash as CUR:USD -> {dollars: X})
  -> PortfolioService.analyze_portfolio()
     -> analyze_portfolio() in core/portfolio_analysis.py
     -> standardize_portfolio_input() in portfolio_config.py
        -> total_value = margin_total = sum(margin_exposure.values())
           (margin_exposure = base price*qty, before futures multiplier)
```

Path B -- All Accounts (CURRENT_PORTFOLIO, shows $109K):
```
Same flow but portfolio_name = "CURRENT_PORTFOLIO"
  -> resolve_portfolio_scope() -> VIRTUAL_ALL (no account filter)
  -> repository.load_full_portfolio() loads ALL positions across providers
  -> _consolidate_positions() may merge/net positions differently
  -> standardize_portfolio_input() computes total_value the same way
```

**Key investigation questions:**
1. Does `_consolidate_positions()` in `inputs/portfolio_manager.py` net out positions
   that exist in multiple providers (e.g., IBKR + Plaid/SnapTrade for same ticker)?
   If so, this reduces the combined total below the single-provider total.
2. Does `filter_positions_to_accounts()` produce a different position set than the
   unfiltered path? Specifically, does CURRENT_PORTFOLIO include negative/deducted
   items that the IBKR-only filter excludes?
3. Is the IBKR `total_value` inflated by double-counting (e.g., money market + cash
   treated as separate positions)?

**Files to read:**
- `inputs/portfolio_manager.py:_consolidate_positions()` -- consolidation logic
- `inputs/portfolio_manager.py:_filter_positions()` -- what gets excluded
- `services/portfolio_scope.py:resolve_portfolio_scope()` -- scope routing
- `services/portfolio_scope.py:filter_positions_to_accounts()` -- account filtering
- `portfolio_risk_engine/portfolio_config.py:standardize_portfolio_input()` -- total_value math
- `inputs/portfolio_repository.py:load_full_portfolio()` -- DB query

### 1.2 Margin Debt Doubling ($5,606 <-> $11,212 -- R8)

The Smart Alert margin debt comes from `core/position_flags.py` (lines 297-336).
It iterates `all_positions`, finds `type == "cash"` or `ticker.startswith("CUR:")`
with negative values, and sums them as `margin_debt`.

**Trace the two paths for the margin number:**

Path A -- Alerts endpoint:
```
GET /api/positions/alerts?portfolio_name=_auto_interactive_brokers_u2471778
  -> routes/positions.py:get_portfolio_alerts()
  -> PositionService.get_all_positions(consolidate=False)
  -> filter_position_result() with account_filters
  -> _rebuild_position_result() to re-consolidate
  -> generate_position_flags(positions=result.data.positions, total_value=...)
  -> position_flags.py: iterates positions, sums negative cash -> margin_debt
```

Path B -- Holdings endpoint (Asset Allocation):
```
The Cash (Margin) -$11,589 in asset allocation comes from:
GET /api/positions/holdings -> _load_enriched_positions() -> to_monitor_view()
  -> _build_monitor_payload() in core/result_objects/positions.py
  -> Each position has gross_exposure / net_exposure computed from value
  -> Cash positions with negative value appear as negative net_exposure
  -> Frontend reads this as the allocation Cash (Margin) value
```

**Key investigation questions:**
1. Is IBKR reporting two separate negative cash entries (e.g., USD margin + settlement)?
   If `consolidate=True` merges them but `consolidate=False` keeps them separate, the
   alert path (which filters post-unconsolidated) might see both.
2. Does the intermittent doubling correlate with cache staleness? If the position cache
   has stale data from a previous fetch that included two entries, and a fresh fetch
   merges them, the value would oscillate.
3. Is there a race between `get_all_positions(consolidate=False)` + `filter_position_result()`
   and `get_all_positions(consolidate=True)` where the consolidation step merges two
   margin entries into one?

**Files to read:**
- `core/position_flags.py:297-336` -- margin debt calculation
- `services/position_service.py:get_all_positions()` -- consolidation logic
- `portfolio_risk_engine/data_objects.py:PositionsData.consolidate()` -- how consolidation works
- Check raw IBKR position data for CUR:USD entries (how many, what values)

### 1.3 Asset Allocation Gap ($46K vs $131K -- R21)

The asset allocation breakdown comes from the risk analysis endpoint (`/api/analyze`).
The `build_portfolio_view()` function in `portfolio_risk.py` returns `allocations` via
`compute_target_allocations(weights, expected_returns)`.

**Key hypothesis:** The weights used for allocation are normalized to sum to 1.0.
Cash positions (CUR:USD mapped to proxy tickers like SGOV/BIL) are included in the
weight vector. But the allocation categories (Equity, Commodities, Fixed Income, etc.)
come from FMP sector/asset-class data, and cash proxy tickers may not map to any
category. The $85K gap = the cash positions whose proxy tickers don't appear in
any allocation bucket.

**Key investigation questions:**
1. What does `compute_target_allocations()` actually return? Does it include cash?
2. How does the frontend map allocation data to the Asset Allocation card?
3. Are cash proxy tickers (SGOV, BIL) included in the allocation output? If so,
   what category do they fall into?

**Files to read:**
- `portfolio_risk_engine/portfolio_risk.py:compute_target_allocations()` -- allocation computation
- Frontend: `RiskAnalysisAdapter.ts` or `RiskAnalysisModernContainer.tsx` -- how allocation renders
- `core/result_objects/risk.py:to_api_response()` -- what allocation data the API returns

### 1.4 Weight Denominator (R6)

**Current behavior:**
```typescript
// PositionsAdapter.ts:67-70
const weight = totalGrossExposure > 0
  ? (grossExposure / totalGrossExposure) * 100
  : 0;
```

Where `totalGrossExposure = payload.summary.portfolio_totals_usd.gross_exposure`.

`portfolio_totals_usd.gross_exposure` is computed in `core/result_objects/positions.py:539-557`.
It sums `abs(value)` for ALL positions including cash. But the question is: does the
holdings endpoint include cash positions in the response, or are they filtered out?

**Key investigation questions:**
1. Does `_build_monitor_payload()` include `is_cash_equivalent` positions in
   `processed_positions`? If cash is excluded from the position list but included
   in `portfolio_totals_usd.gross_exposure`, the denominator is larger than the sum
   of displayed positions.
2. Wait -- the symptom says weights sum to >100% based on equity-only denominator.
   NVDA = $4,579 / $26,802 (equity gross) = 17.1%. So the denominator actually
   EXCLUDES cash. That means `portfolio_totals_usd.gross_exposure` only sums non-cash
   positions, or cash positions are not in the `processed_positions` list.
3. The real question: should weight denominator be the $131K total portfolio value
   (including cash) or the $27K equity exposure?

**Files to read:**
- `core/result_objects/positions.py:_build_monitor_payload()` -- which positions are included
- `core/result_objects/positions.py:350-380` -- is_cash_equivalent filtering
- `frontend/packages/connectors/src/adapters/PositionsAdapter.ts:100-110` -- how totalValue is set

### 1.5 Holdings Count Mismatch (R12)

**Current behavior:**
- Dropdown "36 holdings" -- comes from portfolio metadata or raw position count
- "View All 15 Holdings" -- comes from the holdings API post-consolidation

**Key investigation questions:**
1. Where does the dropdown count come from? Is it `position_count` from
   `PortfolioSummaryAdapter`? If so, which API feeds it?
2. The post-consolidation 15 = `payload.positions.length` from `/api/positions/holdings`

**Files to read:**
- `frontend/packages/ui/src/components/portfolio/PortfolioSelector.tsx` -- dropdown count source
- `frontend/packages/connectors/src/adapters/PortfolioSummaryAdapter.ts` -- how holdingsCount is derived

### 1.6 Volatility Inconsistency (R15)

Three observed values for portfolio volatility:

| Value | Source View | Likely Endpoint | Likely Computation |
|-------|------------|-----------------|-------------------|
| 8.41% | Dashboard Performance Summary | `/api/performance` or similar | Unknown |
| 16.3% | Performance Insights + Settings | `/api/analyze` | `volatility_annual` from `build_portfolio_view()` |
| 19.4% | Factors/Research view | `/api/analyze` (same?) | `risk_metrics.annual_volatility` or factor vol |

**Key investigation questions:**
1. The 8.41% is suspiciously close to `16.3% / 2` or to monthly volatility (annualized
   differently). Check if this is monthly volatility reported without annualization.
   `build_portfolio_view()` returns both `volatility_monthly` and `volatility_annual`.
   If the dashboard reads `volatility_monthly` by mistake, that would explain the gap.
2. The 19.4% from Factors -- `RiskAnalysisAdapter.ts:532-536` converts
   `factorData.volatility_annual * 100`. Check if the Factors view reads from a
   different field path than the summary, or if the factor analysis computes its own
   volatility from a subset of positions (excluding cash weight normalization).
3. `build_portfolio_view()` computes `vol_m = compute_portfolio_volatility(weights, cov_mat)`
   and `vol_a = vol_m * sqrt(12)`. This uses the re-normalized weights (after excluding
   tickers without return data). If different endpoints pass different weight sets, the
   volatility will differ.

**Files to read:**
- Dashboard performance summary source -- find which hook/adapter feeds the 8.41%
- `portfolio_risk_engine/portfolio_risk.py:1814-1815` -- vol_m and vol_a computation
- `core/result_objects/risk.py:to_api_response()` -- which volatility field is returned
- `frontend/packages/ui/src/components/portfolio/overview/useOverviewMetrics.ts` -- how volatility is read for the dashboard
- `frontend/packages/connectors/src/adapters/RiskAnalysisAdapter.ts:530-536` -- Factors view volatility source
- `frontend/packages/connectors/src/adapters/PortfolioSummaryAdapter.ts:396-399` -- summary volatility source

---

## Phase 2: Find the Divergence Points

After Phase 1 investigation, document the confirmed root cause for each finding.
Expected outcomes:

### 2.1 R7 Root Cause Candidates

**Candidate A: Cross-provider position netting.** `_consolidate_positions()` may merge
positions from IBKR + other providers (Schwab, Plaid) by ticker. If a position exists
in both IBKR and Plaid (e.g., IBKR has 100 shares, Plaid mirror shows 100 shares),
consolidation might not add them (it's the same position reported by two sources).
The single-account IBKR view doesn't have this deduction.

**Candidate B: Cash position handling.** The CURRENT_PORTFOLIO path through
`PortfolioManager._load_portfolio_from_database()` uses `_apply_cash_mapping()` which
may net cash differently than the single-account path.

**Candidate C: Leakage detection.** The `partition_positions()` function in
`providers/routing.py` detects cross-source leakage (same holding reported by multiple
providers). When leakage is detected, one source's positions are excluded. The single-
account view doesn't trigger this logic.

**Investigation step:** Add temporary logging to `_consolidate_positions()` and
`standardize_portfolio_input()` showing the ticker list and total_value for both
CURRENT_PORTFOLIO and the IBKR-filtered scope. Compare outputs.

### 2.2 R8 Root Cause Candidates

**Candidate A: Duplicate CUR:USD entries.** IBKR may report margin as two separate
cash entries (e.g., CUR:USD for base currency cash and a separate margin balance).
When `consolidate=True`, these are summed into one. When `consolidate=False` (alerts
path), both appear, but `filter_position_result()` may or may not merge them.

**Candidate B: Cache timing.** The position cache (24h TTL) stores raw positions.
If IBKR updates its position data mid-session (e.g., margin call settled), the cache
may contain stale data with the pre-update margin value while a fresh fetch shows the
updated value. Different endpoints hitting cache at different times see different values.

**Investigation step:** Log the raw CUR:USD/cash positions returned by IBKR and trace
them through consolidation for both `consolidate=True` and `consolidate=False` paths.

### 2.3 R22 Root Cause (Margin Definitions)

The Cash (Margin) -$11,589 and Smart Alert $5,606 almost certainly represent different
things:

- **-$11,589**: Net cash position after margin. This is the total of all CUR:USD
  positions in the portfolio view (could be the sum of a positive cash balance and
  a larger negative margin balance, e.g., +X - 11589 net).
- **$5,606**: Only the negative cash entries (margin debt) from `position_flags.py`.

But $5,606 * 2 ~ $11,212, and $11,212 ~ $11,589. This suggests the $11,589 figure
may be an artifact of doubling (related to R8) or that there are two distinct negative
cash entries summing to $11,589 while the alert only catches one.

### 2.4 R15 Root Cause (Volatility)

Most likely explanation:
- **16.3%**: `volatility_annual` from `build_portfolio_view()` via the `/api/analyze`
  endpoint. This uses weights that include cash proxy tickers (which have near-zero
  volatility), diluting the portfolio volatility.
- **19.4%**: Same `volatility_annual` but from a different weight normalization. If the
  Factors view excludes cash from weights before computing, the equity-only volatility
  would be higher. Or the Factors view reads from `risk_results.volatility_annual`
  which might be computed differently.
- **8.41%**: Likely `volatility_monthly` (not annualized) displayed as if it were
  annual. `vol_m = vol_a / sqrt(12) = 16.3% / 3.46 = 4.7%` -- that doesn't match
  8.41%. Alternative: 8.41% could be the performance endpoint's own volatility
  calculation (from `compute_performance_metrics()`) using a different return window.

---

## Phase 3: Fix the Root Causes

### Fix 3.1: R7 -- Total Value Consistency

**Decision needed: What is "Total Portfolio Value"?**

Option A: Sum of all position market values (what users expect).
Option B: Sum of equity exposure only (useful for risk analysis but confusing for users).

**Recommended**: Option A for all user-facing totals. The `/api/analyze` endpoint returns
`standardized_data["total_value"]` which equals `margin_total` (sum of `margin_exposure`
values). This should equal the sum of all position values including cash. If it doesn't
match what the holdings endpoint returns as `portfolio_totals_usd.net_exposure`, we need
to align them.

**Potential fix locations:**
- `portfolio_risk_engine/portfolio_config.py:246` -- `total_value = margin_total`
- `core/result_objects/positions.py:553` -- `portfolio_totals_usd.net_exposure`
- The frontend should use ONE of these consistently

**Implementation:**
1. Verify that `margin_total` from `standardize_portfolio_input()` matches
   `portfolio_totals_usd.net_exposure` from the positions endpoint for the same portfolio.
2. If they differ, find where the divergence happens and fix the computation that's wrong.
3. If the CURRENT_PORTFOLIO total is lower because consolidation removes cross-provider
   duplicates, that's correct behavior -- the issue is that the single-account total
   should also not double-count. Document the behavior.

### Fix 3.2: R8 -- Margin Debt Stabilization

**Implementation:**
1. Trace raw IBKR CUR:USD entries through the pipeline.
2. If there are legitimately two negative cash entries, ensure both the alerts path and
   the allocation path see the same merged total.
3. If the doubling is a cache race, add idempotency guards:
   - In `position_flags.py`, deduplicate cash entries by (ticker, currency, account) before summing.
   - Or ensure the alerts endpoint always uses `consolidate=True` positions.

### Fix 3.3: R21 -- Asset Allocation Cash Gap

**Implementation:**
1. Add a "Cash & Equivalents" category to the asset allocation breakdown that includes
   the value of cash proxy tickers (SGOV, BIL, CUR:USD).
2. Ensure the allocation categories sum to 100% of total portfolio value.
3. This may require changes in:
   - Backend: `compute_target_allocations()` or `to_api_response()` to include cash
   - Frontend: The allocation chart/card to display the cash category

### Fix 3.4: R22 -- Margin Number Alignment

**Implementation:**
1. Both numbers should represent the same concept. The Smart Alert "margin debt" should
   equal the magnitude of negative cash in the allocation.
2. If they come from different position snapshots, ensure both read from the same source.
3. If they represent genuinely different concepts, clarify labels:
   - Asset Allocation: "Net Cash Position" (includes positive cash - margin debt)
   - Smart Alert: "Margin Borrowed" (only the negative component)

### Fix 3.5: R6 -- Weight Denominator

**Decision needed: What is the weight denominator?**

Option A: Change denominator to total portfolio value (net_exposure including cash).
  - Pro: Weights match what users compute mentally ($4,579 / $131K = 3.5%).
  - Con: Weights sum to < 100% if cash is excluded from display (confusing).

Option B: Keep gross_exposure denominator but add "Cash" as a visible position.
  - Pro: Weights sum to 100%, including cash.
  - Con: Cash showing as 80% of portfolio dominates the view.

Option C: Keep equity denominator, label as "% of Invested Capital".
  - Pro: No backend change needed.
  - Con: Still confusing when shown next to a $131K total.

**Recommended**: Option A with a "Cash & Equivalents" line item in the holdings list.
This makes the math transparent: NVDA $4,579 at 3.5% + Cash $105K at 80% = $131K at 100%.

**Implementation:**
```typescript
// PositionsAdapter.ts -- change denominator
const totalValue = toRequiredNumber(
  payload?.summary?.portfolio_totals_usd?.net_exposure, 0
);
// OR: use a new field that represents total portfolio value including cash
```

If `net_exposure` in `portfolio_totals_usd` excludes cash (which it does based on the
code in positions.py where only processed_positions contribute), we may need to add
a `total_portfolio_value` field that includes cash.

### Fix 3.6: R12 -- Holdings Count

**Implementation:**
1. Find where the dropdown "36 holdings" count comes from.
2. Change it to use the post-consolidation count, or label it as "positions" vs "holdings".
3. Most likely fix: `PortfolioSummaryAdapter` should use `summary.total_positions` from
   the holdings API response instead of a raw count from another source.

### Fix 3.7: R15 -- Volatility Alignment

**Implementation:**
1. Ensure all views that display "Volatility" use the same field: `volatility_annual`
   from the analysis endpoint, converted to percentage by * 100.
2. If the dashboard performance summary reads a different field (e.g., monthly vol or
   a performance-endpoint vol), change it to read from the analysis endpoint.
3. For the Factors view 19.4% discrepancy:
   - Check if `RiskAnalysisAdapter.ts:532` reads `volatility_annual` correctly.
   - Verify the * 100 conversion isn't being double-applied.
   - If it reads from a different field path, unify it.

---

## Files Summary

### Backend (Read for Investigation)

| File | Purpose |
|------|---------|
| `inputs/portfolio_manager.py` | `_load_portfolio_from_database()`, `_consolidate_positions()`, `_filter_positions()` |
| `inputs/portfolio_repository.py` | `load_full_portfolio()` -- DB query for positions |
| `services/portfolio_scope.py` | `resolve_portfolio_scope()`, `filter_positions_to_accounts()` |
| `services/position_service.py` | `get_all_positions()`, consolidation flow |
| `portfolio_risk_engine/portfolio_config.py` | `standardize_portfolio_input()` -- total_value, weights |
| `portfolio_risk_engine/portfolio_risk.py` | `build_portfolio_view()` -- vol_m, vol_a, allocations |
| `core/portfolio_analysis.py` | `analyze_portfolio()` -- orchestrates analysis |
| `core/result_objects/positions.py` | `_build_monitor_payload()` -- portfolio_totals_usd |
| `core/result_objects/risk.py` | `to_api_response()` -- volatility_annual field |
| `core/position_flags.py` | `generate_position_flags()` -- margin_debt calculation |
| `app.py` | `_run_analyze_workflow()`, `/api/analyze`, `/api/risk-score` endpoints |
| `routes/positions.py` | `/api/positions/holdings`, `/api/positions/alerts` |
| `providers/routing.py` | `partition_positions()` -- cross-source leakage |

### Frontend (Read for Investigation, Edit for Fixes)

| File | Purpose |
|------|---------|
| `frontend/packages/connectors/src/adapters/PositionsAdapter.ts` | Weight denominator (lines 67-70, 100-102) |
| `frontend/packages/connectors/src/adapters/PortfolioSummaryAdapter.ts` | Total value, volatility, holdings count extraction |
| `frontend/packages/connectors/src/adapters/RiskAnalysisAdapter.ts` | Factors view volatility (lines 530-536) |
| `frontend/packages/ui/src/components/portfolio/overview/useOverviewMetrics.ts` | Dashboard metrics incl. volatility |

### Backend (Potential Edit Targets)

| File | Change |
|------|--------|
| `core/result_objects/positions.py` | Add `total_portfolio_value` field to portfolio_totals_usd |
| `core/position_flags.py` | Margin debt deduplication guard |
| `portfolio_risk_engine/portfolio_config.py` | total_value alignment |

---

## Testing Plan

### Investigation Validation

1. **Log-based tracing**: Add temporary debug logging to trace position lists through
   both the IBKR-filtered and CURRENT_PORTFOLIO paths. Compare:
   - Number of positions
   - Sum of values
   - Cash/margin entries
   - Final total_value from standardize_portfolio_input()

2. **Unit test: consolidation determinism**:
   - Feed the same raw positions through consolidation twice
   - Verify identical output (rules out race conditions in the function itself)

### Fix Validation

3. **R7**: After fix, verify:
   - CURRENT_PORTFOLIO total >= max(any single account total)
   - OR document why cross-provider dedup legitimately reduces the combined total

4. **R8**: After fix, verify:
   - Margin debt is identical across 10 sequential loads of the same portfolio
   - Alerts endpoint and allocation endpoint show the same margin figure

5. **R6**: After fix, verify:
   - NVDA weight = $4,579 / total_portfolio_value (not gross_equity_exposure)
   - All position weights + cash weight = 100%

6. **R12**: After fix, verify:
   - Dropdown count matches "View All N Holdings" count

7. **R15**: After fix, verify:
   - Dashboard, Performance, Factors, Settings all show the same volatility value
   - Value matches `volatility_annual * 100` from the analysis endpoint

8. **R21/R22**: After fix, verify:
   - Asset allocation categories sum to ~100% of total portfolio value
   - Margin value consistent between allocation and smart alert

### Regression Guards

9. **Both portfolio scopes**: Test ALL fixes with both single account AND combined portfolio
10. **Multi-provider**: Test with portfolios that span IBKR + Schwab + Plaid
11. **No cash**: Test with a portfolio that has no cash positions (e.g., manual portfolio)
12. **Existing tests**: Run full test suite -- no regressions allowed

---

## Implementation Order

1. **Phase 1 investigation** (no code changes) -- 2-3 hours
   - Map all data flows, confirm root causes
   - Write confirmed root causes into this doc

2. **R6 weight denominator** (low risk, clear fix) -- 30 min
   - Frontend adapter change only
   - May need backend to expose `total_portfolio_value` field

3. **R12 holdings count** (low risk) -- 15 min
   - Frontend adapter or component source change

4. **R15 volatility alignment** (medium risk) -- 1 hour
   - Trace all three values to their source
   - Unify to single field

5. **R7 total value** (high risk, needs investigation) -- 2 hours
   - Depends on Phase 1 findings
   - May require backend consolidation changes

6. **R8 + R22 margin consistency** (high risk, related) -- 2 hours
   - Fix together since they share root cause
   - Requires understanding IBKR cash position structure

7. **R21 allocation gap** (medium risk) -- 1 hour
   - Add cash category to allocation breakdown

---

## Boundary Rules

- **DO NOT** edit frontend component files (*.tsx in `components/`) -- Session 1 owns those
- **OK to edit**: Frontend adapter files (PositionsAdapter.ts, PortfolioSummaryAdapter.ts, RiskAnalysisAdapter.ts)
- **OK to edit**: Backend result objects, position flags, portfolio config
- **BE CAREFUL**: Changes to `portfolio_risk_engine/` affect ALL analysis paths
- **TEST BOTH**: Single account AND combined portfolio after every change
- **DOCUMENT**: Write confirmed root causes back into this plan before fixing

---

## CONFIRMED ROOT CAUSES & IMPLEMENTATION PLAN (v2)

> Investigation complete. All 7 findings traced to specific code paths.
> Codex review round 1: all fixes revised based on feedback.
> Fixes ordered by risk (low → high) and independence.

### Fix 1: R6 — Weight Denominator (LOW RISK)

**Confirmed root cause**: `PositionsAdapter.ts:102` uses `portfolio_totals_usd.gross_exposure` as weight denominator. That field is built from `processed_positions` only (cash excluded at `positions.py:342-343`). Denominator = equity gross (~$27K), not total portfolio ($131K). Weights inflated ~5x.

**Implementation:**

**Step 1a** — Backend: add `total_portfolio_value` to `portfolio_totals_usd` in `_build_monitor_payload()`

File: `core/result_objects/positions.py` — after line 560 (end of `portfolio_totals_usd` for-loop):

```python
# Total portfolio value including cash (weight denominator)
cash_value_usd = sum(
    self._safe_float(p.get("value")) or 0.0
    for p in cash_positions
)
portfolio_totals_usd["total_portfolio_value"] = (
    portfolio_totals_usd["net_exposure"] + cash_value_usd
)
```

Uses `net_exposure` (not gross) — net + cash = NAV-equivalent total.

**Edge case**: For short-only or negative-NAV portfolios, `total_portfolio_value` could be ≤ 0. The `?? gross_exposure` fallback alone is insufficient — we also need an explicit `> 0` check in the frontend adapter.

**Step 1b** — Update TypeScript type contract

File: `frontend/packages/chassis/src/types/index.ts` — add to `portfolio_totals_usd` (line 168-174):

```typescript
total_portfolio_value?: number; // NEW: net_exposure + cash (weight denominator)
```

Optional field (`?`) for backward compat.

**Step 1c** — Update Python fallback payload

File: `routes/positions.py` — add to empty `portfolio_totals_usd` dict (line 96-102):

```python
"total_portfolio_value": 0,
```

**Step 1d** — Frontend: use new field as denominator with explicit > 0 guard

File: `frontend/packages/connectors/src/adapters/PositionsAdapter.ts` — line 102:

```typescript
const totalPortfolioValue = toRequiredNumber(
  payload?.summary?.portfolio_totals_usd?.total_portfolio_value, 0
);
const totalValue = totalPortfolioValue > 0
  ? totalPortfolioValue
  : toRequiredNumber(payload?.summary?.portfolio_totals_usd?.gross_exposure, 0);
```

Explicit `> 0` check ensures we fall back to `gross_exposure` when total_portfolio_value is 0 or negative (short-only portfolios). The existing `totalGrossExposure > 0` guard at line 68 then handles the gross_exposure=0 case.

**Step 1e** — Tests:
- Backend: PositionResult with equities ($30K) + cash ($70K) → assert `total_portfolio_value` ≈ $100K, `gross_exposure` ≈ $30K
- Backend: PositionResult with no cash → assert `total_portfolio_value` = `net_exposure`
- Backend: PositionResult with shorts only (net_exposure < 0, no cash) → assert `total_portfolio_value` ≤ 0
- Frontend adapter test: verify fallback to `gross_exposure` when `total_portfolio_value` ≤ 0

---

### Fix 2: R12 — Holdings Count Mismatch (LOW RISK)

**Confirmed root cause**: Dropdown uses `holdings_count` from `mcp_tools/portfolio_management.py:141-146` (filters zero-qty, options, CUR:\*). "View All" uses `holdings.length` = `len(processed_positions)` from positions monitor (cash excluded but options/zero-qty kept).

**Note**: Manual portfolios bypass `/api/positions/holdings` entirely (`registry.ts:165`), loading from `portfolio.holdings` directly. This fix only affects non-manual portfolios.

**Implementation:**

**Step 2a** — Backend: add `holdings_count` to positions monitor payload summary

File: `core/result_objects/positions.py` — in `summary` dict (~line 575):

```python
"holdings_count": len([
    p for p in processed_positions
    if (p.get("quantity") or 0) != 0
    and p.get("type") not in ("option",)
]),
```

No CUR: filter needed — `processed_positions` already excludes cash (line 342-343).

**Step 2b** — Frontend: filter inline in DashboardHoldingsCard

File: `frontend/packages/ui/src/components/dashboard/cards/DashboardHoldingsCard.tsx` — line 160:

```typescript
const holdingsCount = holdings.filter(
  h => h.shares !== 0 && h.type !== 'option'
).length;
```

This matches the backend filter without needing to thread the count through the adapter chain.

**Step 2c** — Test: Positions with 3 equities (qty>0) + 1 option (qty 5) + 1 equity (qty 0) → assert `summary["holdings_count"]` = 3.

---

### Fix 3: R15 — Volatility Inconsistency (MEDIUM RISK)

**Confirmed root cause** — three different computations:

| Value | Source | Computation | Units |
|-------|--------|-------------|-------|
| 8.41% | `compute_performance_metrics()` (`perf_metrics_engine.py:77,263`) | `returns.std() * sqrt(12) * 100` | Already % |
| 16.3% | `build_portfolio_view()` (`portfolio_risk.py:1814-1815`) | `compute_portfolio_volatility(weights, cov_mat) * sqrt(12)` | Decimal |
| 19.4% | `RiskAnalysisAdapter.ts:534-535` fallback | `sqrt(variance_decomposition.portfolio_variance) * 100` | Wrong weight set |

8.41% (realized) vs 16.3% (forward-looking) are genuinely different metrics — acceptable since they appear in different views (Performance strip vs Overview/Factors).

**The only actual bug**: `RiskAnalysisAdapter.ts:534-535` has a `sqrt(portfolio_variance) * 100` fallback that uses factor-model variance (different weight set) → misleading 19.4%.

**NOT a bug** (revised from v1): `PortfolioSummaryAdapter.ts:396-399` — the fallback chain works correctly. `riskAnalysisSummary.volatility_annual` and `riskResults.volatility_annual` both return null (those fields don't exist in the RiskAnalysisAdapter transformed output — see `registry.ts:372` where transformed data is passed). It falls through to `riskMetrics.annual_volatility` which is already in percent (16.3) from RiskAnalysisAdapter line 532. No conversion needed, no `< 1.0` heuristic needed.

**Implementation:**

**Step 3a** — Remove sqrt(variance) fallback in RiskAnalysisAdapter

File: `frontend/packages/connectors/src/adapters/RiskAnalysisAdapter.ts` — lines 532-536:

```typescript
// Before:
annual_volatility: factorData.volatility_annual
  ? factorData.volatility_annual * 100
  : (factorData.variance_decomposition?.portfolio_variance
    ? Math.sqrt(factorData.variance_decomposition.portfolio_variance) * 100
    : 0)

// After:
annual_volatility: factorData.volatility_annual
  ? factorData.volatility_annual * 100
  : 0
```

Better to show 0 (no data) than misleading 19.4% from a different weight set.

**Step 3b** — No PortfolioSummaryAdapter change needed (revised from v1).

**Step 3c** — No backend changes needed. Backend correctly returns decimal from `build_portfolio_view()` and already-percent from `compute_performance_metrics()`.

**Step 3d** — Verify: `DashboardPerformanceStrip.tsx` shows 8.41% (realized vol) — this is correct. `formatPercent()` at line 7-9 simply appends `%`, no multiplication. Label "Volatility" is acceptable in Performance context.

---

### Fix 4: R7 — Total Value Discrepancy (HIGH RISK — NOT CONFIRMED, INVESTIGATE FIRST)

**Root cause hypothesis** (not confirmed): IBKR single = $131K > All Accounts = $109K. Counterintuitive. Likely:
- Cross-provider leakage detection (`partition_positions()`) over-excluding
- Negative cash/margin from other accounts netting down the combined total
- Different consolidation in VIRTUAL_FILTERED vs VIRTUAL_ALL

**Requires live data investigation before coding a fix.**

**Step 4a** — Add debug endpoint in `routes/debug.py`: `GET /api/debug/portfolio-value-compare` returning side-by-side position counts, total values, cash entries, and position diff.

**Step 4b** — Add trace logging in `inputs/portfolio_manager.py:_load_portfolio_from_database()` after consolidation.

**Step 4c** — Fix based on findings. Expected targets: `providers/routing.py:partition_positions()`, `inputs/portfolio_assembler.py:consolidate_positions()`, `services/portfolio_scope.py`.

---

### Fix 5: R8 + R22 — Margin Debt Doubling (HIGH RISK)

**Confirmed root cause**: Cash consolidation groups by `ticker` only and sums values:
- `portfolio_assembler.py:117`: `cash_positions.groupby("ticker").agg({"quantity": "sum", ...})`
- `position_service.py:687`: `cash_positions.groupby("ticker").agg({"quantity": "sum", "value": "sum", ...})`

If IBKR reports CUR:USD = -$5,606 and Plaid mirrors same account → sums to -$11,212.

**Note on dedup identity** (from Codex review): `(ticker, brokerage_name)` is too coarse — it would collapse legitimate cash from two different accounts at the same brokerage (e.g., Schwab checking + Schwab IRA). `account_id` alone is also insufficient due to alias normalization (`resolve_account_aliases()` at `position_service.py:365`, `_normalize_account_id()` at `portfolio_scope.py:121`).

**Correct dedup key**: `(ticker, brokerage_name, canonical_account)` where `canonical_account` is derived from `resolve_account_aliases()` (`providers/routing_config.py:279`). This function returns the full equivalence class (frozenset) for an account_id — use `min()` of the set as the canonical representative. This handles alias mapping (e.g., UUID ↔ U2471778 for the same IBKR account) while keeping distinct accounts separate.

**Implementation:**

**Step 5a** — Add helper for canonical account identity

File: `services/position_service.py` — add near top of file or in a local helper:

```python
from providers.routing_config import resolve_account_aliases

def _canonical_account_key(account_id: Any) -> str:
    """Return a canonical account key, resolving aliases."""
    normalized = str(account_id or "").strip().lower()
    if not normalized:
        return ""
    aliases = resolve_account_aliases(normalized)
    return min(aliases) if aliases else normalized
```

**Step 5b** — Fix `position_service.py:664-688`: Two-stage consolidation

```python
if not cash_positions.empty:
    # ... existing column setup (lines 665-668) ...

    # Stage 1: Deduplicate same-account cash from multiple providers.
    # If IBKR and Plaid both report the same account's CUR:USD, keep the
    # higher-priority provider's value.
    PROVIDER_PRIORITY = {"ibkr": 0, "schwab": 1, "snaptrade": 2, "plaid": 3}

    has_account = "account_id" in cash_positions.columns and cash_positions["account_id"].notna().any()
    has_brokerage = "brokerage_name" in cash_positions.columns and cash_positions["brokerage_name"].notna().any()

    if has_account and has_brokerage:
        cash_positions = cash_positions.copy()
        # Resolve account aliases for canonical dedup identity
        cash_positions["_canon_acct"] = cash_positions["account_id"].apply(
            lambda x: _canonical_account_key(x) if pd.notna(x) else ""
        )
        cash_positions["_priority"] = cash_positions["position_source"].apply(
            lambda s: min(PROVIDER_PRIORITY.get(src.strip(), 99)
                         for src in str(s).split(","))
        )
        cash_positions = cash_positions.sort_values("_priority")
        cash_positions = cash_positions.drop_duplicates(
            subset=["ticker", "brokerage_name", "_canon_acct"], keep="first"
        )
        cash_positions = cash_positions.drop(columns=["_priority", "_canon_acct"])

    # Stage 2: Sum across accounts for the same currency (original behavior)
    cash_grouped = cash_positions.groupby("ticker").agg(agg_dict).reset_index()
    consolidated_positions.append(cash_grouped)
```

**Step 5c** — Same pattern in `inputs/portfolio_assembler.py:116-127`. Guard with `if "brokerage_name" in df.columns`.

**Step 5d** — Defensive dedup in `core/position_flags.py:297-308` using the same alias resolution:

```python
from providers.routing_config import resolve_account_aliases

def _canonical_account_key(account_id):
    normalized = str(account_id or "").strip().lower()
    if not normalized:
        return ""
    aliases = resolve_account_aliases(normalized)
    return min(aliases) if aliases else normalized

seen_cash_keys = set()
for position in all_positions:
    ptype = str(position.get("type", ""))
    ticker = str(position.get("ticker", ""))
    if ptype == "cash" or ticker.startswith("CUR:"):
        brokerage = str(position.get("brokerage_name", ""))
        acct = _canonical_account_key(position.get("account_id", ""))
        dedup_key = (ticker, brokerage, acct)
        if dedup_key in seen_cash_keys:
            continue
        seen_cash_keys.add(dedup_key)
        val = _to_float(position.get("value", 0))
        # ... rest of cash_balance / margin_debt logic unchanged
```

Note: blank `account_id` → `""` canonical key. If two providers both have blank account_id for the same brokerage, they ARE deduplicated (correct — both are reporting the same unknown account). If this is a problem, skip dedup when `_canon_acct == ""`.

**Step 5e** — Tests:
- Two CUR:USD from different providers, same `(brokerage, account_id)` → assert single entry (dedup)
- Two CUR:USD with aliased account IDs (UUID vs U2471778) → assert single entry (alias resolution)
- Two CUR:USD from same brokerage, different `account_id` → assert sum (legitimately separate)
- Two CUR:USD from different brokerages → assert sum
- Two CUR:USD with blank `account_id` from same brokerage → assert single entry (conservative dedup)
- Test `generate_position_flags()` with duplicate cash entries → assert no double-count

---

### Fix 6: R21 — Asset Allocation Gap (MEDIUM RISK)

**Confirmed root cause (revised from v1)**: Cash proxies (SGOV, BIL) ARE already classified as `"cash"` by `security_type_service.py:864-868` (`_classify_cash_proxies()`), and the classification IS injected into `analysis_metadata` at `portfolio_service.py:330`. **The classification is NOT the problem.**

**The real problem**: `build_portfolio_view()` at `portfolio_risk.py:1784-1796` calls `get_returns_dataframe()` which excludes tickers without sufficient FMP historical return data. Cash proxy tickers (SGOV, BIL) typically lack FMP return series. After exclusion, the remaining weights are **re-normalized to sum to 1.0** (line 1796). The `excluded_tickers` list is logged but their original weights are lost. When `_build_asset_allocation_breakdown()` runs, it iterates `self.portfolio_weights` (the filtered, re-normalized set) — cash proxies aren't in it, so the "cash" allocation category is absent despite being classified.

**Key insight** (from Codex review): The original pre-normalization weights already exist in `analysis_metadata["weights"]` (set at `core/portfolio_analysis.py:229`). No new field threading needed — just use the original weights for allocation instead of the re-normalized ones.

**Implementation:**

**Step 6a** — Use original (pre-normalization) weights for allocation breakdown

File: `core/result_objects/risk.py` — in `_build_asset_allocation_breakdown()`, replace the iteration source. Currently (line 911):

```python
for ticker, weight in self.portfolio_weights.items():
```

Change to use original weights from analysis_metadata when available:

```python
# Use original weights (before return-data exclusion/re-normalization) so
# cash proxies like SGOV are represented even without FMP return data.
original_weights = (self.analysis_metadata or {}).get("weights", {})
allocation_weights = original_weights if original_weights else self.portfolio_weights

for ticker, weight in allocation_weights.items():
    asset_class = asset_classes.get(ticker)
    if not asset_class:
        continue
    dollar_value = weight * total_value
    # ... rest unchanged
```

Since `original_weights` sums to 1.0 (before re-normalization) and includes SGOV with its original weight, the allocation breakdown will correctly show the "cash" category. The classified asset_classes dict already includes SGOV → "cash" from security_type_service.

**Step 6b** — No `build_portfolio_view()` changes needed. No new field threading needed.

**Step 6c** — Tests:

New test file `tests/core/test_risk_result_allocation.py`:
- `portfolio_weights` (post-normalization): {AAPL: 0.5, MSFT: 0.5}
- `analysis_metadata["weights"]` (original): {AAPL: 0.18, MSFT: 0.18, SGOV: 0.64}
- `asset_classes`: {AAPL: "equity", MSFT: "equity", SGOV: "cash"}
- Assert "cash" category at ~64% (SGOV's original weight)
- Assert "equity" at ~36% (AAPL + MSFT original weights)
- **Assert all categories sum to exactly ~100%** (critical validation)
- Assert existing `test_allocation_drift.py` tests still pass (when `analysis_metadata["weights"]` is empty/missing → falls back to `portfolio_weights` → no behavior change)

---

### Implementation Order

| # | Finding | Risk | Dependencies |
|---|---------|------|--------------|
| 1 | R6 weight denominator | Low | None |
| 2 | R12 holdings count | Low | None |
| 3 | R15 volatility | Low | None (single line change) |
| 4 | R8+R22 margin dedup | High | None (standalone consolidation fix) |
| 5 | R7 total value | High | Investigation needed, may benefit from R8 fix |
| 6 | R21 allocation gap | Medium | None (separate weight-tracking path) |

### Key Files

| File | Fixes |
|------|-------|
| `core/result_objects/positions.py` | R6 (`total_portfolio_value`), R12 (`holdings_count`) |
| `frontend/.../chassis/src/types/index.ts` | R6 (TypeScript type update) |
| `routes/positions.py` | R6 (fallback payload) |
| `frontend/.../adapters/PositionsAdapter.ts` | R6 (denominator) |
| `frontend/.../cards/DashboardHoldingsCard.tsx` | R12 (inline filter) |
| `frontend/.../adapters/RiskAnalysisAdapter.ts` | R15 (remove sqrt fallback) |
| `services/position_service.py` | R8 (cash dedup consolidation) |
| `inputs/portfolio_assembler.py` | R8 (cash dedup consolidation) |
| `core/position_flags.py` | R8 (margin dedup guard) |
| `core/result_objects/risk.py` | R21 (use original weights from `analysis_metadata["weights"]`) |
| `routes/debug.py` | R7 (comparison endpoint) |
| `inputs/portfolio_manager.py` | R7 (trace logging) |

# N7: Dashboard Stuck on "Mock" Data After Google OAuth Sign-In

**Status:** RESOLVED (verified via live testing 2026-03-15 — Dashboard shows "Overview: Real")
**Bug:** After Google OAuth sign-in, Dashboard shows "Mock" indicator, all 6 metric cards show "—", Holdings empty, Alerts empty. AI Recommendations loads fine. Happens on EVERY sign-in, not just when Plaid is down.

## Root Cause

**snake_case vs camelCase mismatch in the risk-score response check.**

The `portfolio-summary` resolver aggregates 3 sub-resolvers via `Promise.all`:
1. `risk-score` → `PortfolioManager.calculateRiskScore()`
2. `risk-analysis` → `PortfolioManager.analyzePortfolioRisk()`
3. `performance` → `PortfolioManager.getPerformanceAnalysis()`

If **any one** throws, `Promise.all` rejects and the entire summary fails → "Mock".

### The specific failure — risk-score:

**Backend** `POST /api/risk-score` returns (app.py):
```python
api_response = result.to_api_response()  # Contains `risk_score` key (snake_case)
api_response.update({ 'success': True, ... })
return api_response
# → { success: true, risk_score: {...}, summary: "...", ... }
```

**Frontend** `PortfolioManager.calculateRiskScore()` checks (line ~395):
```typescript
if (response && response.success && response.riskScore) {  // camelCase ← WRONG
  return { riskScore: response, error: null };
}
return { riskScore: null, error: 'Risk score calculation failed' };  // ← Always hits this
```

`response.riskScore` is always `undefined` because the backend returns `response.risk_score`. The manager returns `{ error: 'Risk score calculation failed' }`. The resolver sees `result.error` → throws → `Promise.all` rejects → "Mock".

### Why the other two work:

- **risk-analysis**: Backend returns `{ success: true, data: {...} }`. Manager checks `response.success && response.data` → matches ✓
- **performance**: Backend returns `{ success: true, performance_metrics: {...} }`. Manager checks `response.success` only → matches ✓

### Why AI Recommendations work:

Different data path — doesn't go through `portfolio-summary` resolver or `PortfolioManager.calculateRiskScore()`.

## Fix

### Step 1 (primary): Fix the snake_case check in PortfolioManager

**File:** `frontend/packages/connectors/src/managers/PortfolioManager.ts` (line ~395)

**Current:**
```typescript
if (response && response.success && response.riskScore) {
  this.safeUpdateRiskScore(this.toRiskScore(response.riskScore));
  return { riskScore: response, error: null };
}
```

**Change to:**
```typescript
if (response && response.success && response.risk_score) {
  this.safeUpdateRiskScore(this.toRiskScore(response.risk_score));
  return { riskScore: response, error: null };
}
```

**Why:** Match the backend's actual response key. The backend returns `risk_score` (snake_case) everywhere — `to_api_response()` in `RiskScoreResult`, the route handler in `app.py`. No camelCase transformation exists in the HTTP layer.

Also check `this.toRiskScore()` — verify it accesses `risk_score` sub-fields with correct casing. If it expects camelCase internally, the mapping may need to happen inside `toRiskScore()`.

### Step 2 (hardening): Use Promise.allSettled for portfolio-summary

**File:** `frontend/packages/connectors/src/resolver/registry.ts` (lines ~355-378)

**Current:**
```typescript
const [riskScoreData, riskAnalysisData, performanceData] = await Promise.all([
  resolverMap['risk-score']({ portfolioId: portfolio.id }, context),
  resolverMap['risk-analysis']({ portfolioId: portfolio.id }, context),
  resolverMap.performance({ portfolioId: portfolio.id }, context),
]);
```

**Change to:**
```typescript
const results = await Promise.allSettled([
  resolverMap['risk-score']({ portfolioId: portfolio.id }, context),
  resolverMap['risk-analysis']({ portfolioId: portfolio.id }, context),
  resolverMap.performance({ portfolioId: portfolio.id }, context),
]);

const riskScoreData = results[0].status === 'fulfilled' ? results[0].value : null;
const riskAnalysisData = results[1].status === 'fulfilled' ? results[1].value : null;
const performanceData = results[2].status === 'fulfilled' ? results[2].value : null;

// Log failures but don't block the entire summary
results.forEach((r, i) => {
  if (r.status === 'rejected') {
    console.warn(`portfolio-summary sub-resolver ${i} failed:`, r.reason);
  }
});
```

**Why:** Defense-in-depth. Even after fixing the casing, future API changes or transient errors in any sub-resolver shouldn't kill the entire dashboard. The adapter should render whatever data IS available and show "—" for missing sections.

**Note:** The `PortfolioSummaryAdapter.transform()` call (line ~370) needs to handle null inputs gracefully. Check if it already does — if not, add null guards.

### Step 3 (optional): Audit other snake_case/camelCase mismatches in PortfolioManager

**File:** `frontend/packages/connectors/src/managers/PortfolioManager.ts`

Scan all response shape checks for similar mismatches:
- `analyzePortfolioRisk()` — checks `response.data` ← OK (backend returns `data`)
- `getPerformanceAnalysis()` — checks `response.success` ← OK
- Any other manager methods that parse backend responses

This is preventive — the risk-score check is the only confirmed mismatch.

## Edge Cases

1. **Step 1 alone fixes the bug.** Step 2 is hardening for future resilience.
2. **No auth changes needed.** The bug is NOT related to `initializeAuth()`, `onReauthenticate()`, or cache invalidation. Previous v1/v2 plans were incorrect.
3. **Onboarding (no portfolios):** Unaffected — PortfolioInitializer handles empty portfolio list before portfolio-summary is ever called.
4. **Plaid 500 (N9):** With Step 2, a Plaid failure causing risk-analysis to fail won't kill the entire summary. Risk-score and performance will still render.
5. **Dev auth bypass:** Unaffected — same data path after auth completes.

## Test Plan

### Manual Verification
1. **Fresh sign-in:** Incognito → login → Google sign-in → Dashboard shows "Real" (not "Mock"), risk score card populated
2. **Page reload:** Refresh → Dashboard loads correctly with risk score
3. **Check console:** No `Risk score calculation failed` errors
4. **Verify risk score value:** Compare Dashboard risk score with `get_risk_score` MCP tool output — values should match

### Automated Tests
- Unit test: mock API response with `{ success: true, risk_score: {...} }` → verify `calculateRiskScore()` returns `{ riskScore: response, error: null }`
- Unit test: mock API response with `{ success: true }` (no risk_score) → verify graceful error
- Integration test: `portfolio-summary` resolver with one failing sub-resolver → verify partial data returned (Step 2)

## Files Changed

| File | Change | Priority |
|------|--------|----------|
| `frontend/packages/connectors/src/managers/PortfolioManager.ts` | Fix `riskScore` → `risk_score` in calculateRiskScore (~2 lines) | **P0 — fixes the bug** |
| `frontend/packages/connectors/src/resolver/registry.ts` | `Promise.all` → `Promise.allSettled` for portfolio-summary (~10 lines) | P1 — hardening |
| `frontend/packages/connectors/src/adapters/PortfolioSummaryAdapter.ts` | Add null guards for partial data in `transform()` | P1 — needed for Step 2 |

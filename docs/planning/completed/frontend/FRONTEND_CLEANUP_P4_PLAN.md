# P4 Dead Code Cleanup Plan

## Context
The frontend cleanup audit (`completed/FRONTEND_CLEANUP_AUDIT.md`) identified 7 P4 items. 2 are already resolved (P4-1 mostly fixed, P4-2 removed). 5 remain. Codex R1 review caught 2 High issues, R2 caught 2 Medium + 2 Low — all addressed below.

## Changes

### 1. ~~RiskAnalysis.tsx — Remove unused props~~ **DROPPED**
Keep `RiskAnalysisProps` interface intact — callers `ConnectedRiskAnalysis.tsx:131-135` and `RiskAnalysisModernContainer.tsx:697-700` still pass these props. The underscore convention already communicates intent. Not worth the churn.

### 2. StrategyBuilder.tsx — Remove dead state (line 328) + stale comment (line 295)
Delete `const [_selectedStrategy, _setSelectedStrategy] = useState<Strategy | null>(null)`. Confirmed zero references.
Also remove the reference to `selectedStrategy` in the state-summary comment at line 295.

### 3. ~~PerformanceView.tsx — Remove animationEnabled~~ **DROPPED**
Codex R1 found `animationEnabled` IS actively used: read from localStorage (line 221), saved to localStorage (line 250), and in useEffect deps (line 256). Not dead code — the original audit was wrong.

### 4. RiskAnalysisAdapter.ts — Delete 2 dead methods + stale comments + unused import
Delete `transformRiskContributions()` (lines 777-788) and `transformCorrelations()` (lines 795-809). Both private, never called.
Also clean up:
- Lines 393-394: remove `transformRiskContributions` and `transformCorrelations` from the TRANSFORMATION METHODS list
- Lines 418-419: remove `weighted_factor_var → riskContributions` and `correlation_matrix → factorCorrelations` from the pipeline comment
- Line 112: remove `formatBasisPoints` from imports (only used in the dead methods)

### 5. Cache key bug fix — 2 adapters
**PortfolioOptimizationAdapter.ts** line 311: Remove `timestamp: Date.now()` from cache key content. Also add `portfolio_metadata` and `risk_limits_metadata` from `apiResponse` to the content object — transform output includes these fields (lines 184-185, 203-214) but the key currently omits them. TTL mechanism at line 329 handles time-based expiry separately.

**RiskSettingsAdapter.ts** line 546: Remove `timestamp: Date.now()` AND add `riskScoreData` to the cache key content object. Transform output depends on `riskScoreData` (line 306) but the key doesn't include it. Fix: pass `riskScoreData` as a parameter to `generateCacheKey()` and include it in the content object hashed by `generateContentHash()` (already imported). This ensures the key changes when riskScoreData content changes.

## Files Modified
| File | Change |
|------|--------|
| `frontend/packages/ui/src/components/portfolio/StrategyBuilder.tsx` | Remove 1 dead useState (line 328) + stale comment (line 295) |
| `frontend/packages/connectors/src/adapters/RiskAnalysisAdapter.ts` | Delete 2 dead methods (lines 777-809) + comments (lines 393-394, 418-419) + unused `formatBasisPoints` import (line 112) |
| `frontend/packages/connectors/src/adapters/PortfolioOptimizationAdapter.ts` | Remove `timestamp: Date.now()`, add `portfolio_metadata`/`risk_limits_metadata` to cache key (line 311) |
| `frontend/packages/connectors/src/adapters/RiskSettingsAdapter.ts` | Remove `timestamp: Date.now()`, add `riskScoreHash` to cache key (line 546) |

## Verification
1. `cd frontend && pnpm typecheck` — 0 TS errors
2. `cd frontend && pnpm build` — clean build
3. Visual check in browser: Overview, Holdings, Performance, Risk, Strategy views render normally

## Doc Updates
- Update `completed/FRONTEND_CLEANUP_AUDIT.md` — mark P4 items resolved, note P4-3 and P4-5 were false positives

## Codex R1 Review — FAIL (4 findings, all addressed)
1. **High** — P4-5 `animationEnabled` is actually used (lines 202, 221, 250, 256). → DROPPED from plan.
2. **High** — P4-3 removing props from interface breaks callers. → DROPPED from plan.
3. **Medium** — RiskSettingsAdapter cache key missing `riskScoreData` dependency. → Added `hasRiskScore` to key.
4. **Low** — Dead method deletion should also clean stale comments. → Added comment cleanup.

## Codex R2 Review — FAIL (4 findings, all addressed)
1. **Medium** — `hasRiskScore: !!riskScoreData` insufficient; content changes missed. → Changed to include full `riskScoreData` in content hash via `generateContentHash()`.
2. **Medium** — PortfolioOptimizationAdapter key omits `portfolio_metadata`/`risk_limits_metadata`. → Added to key content.
3. **Low** — StrategyBuilder comment at line 295 references deleted state. → Added to cleanup scope.
4. **Low** — `formatBasisPoints` import becomes unused after method deletion. → Added to cleanup scope.

## Codex R3 Review — FAIL (misread: checked code not plan)
Codex verified code hasn't changed yet (correct — this is a pre-implementation plan). One valid new finding:
1. **Low** — `JSON.stringify(...).length` is collision-prone for riskScoreHash. → Fixed: use `generateContentHash(riskScoreData)` instead.

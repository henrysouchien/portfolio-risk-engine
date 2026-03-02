# P5: Asset Allocation — Period Selector + Target Allocation & Drift Detection

**Date**: 2026-03-01
**Status**: COMPLETE
**Implemented**: 2026-03-01 (Codex implemented, live-tested in Chrome)
**Commits**: `24784ba2` (P5 implementation, 17 files), `5eca6def` (circular import fix + graceful missing table)
**Parent**: TODO.md P5, `FRONTEND_DATA_WIRING_AUDIT.md`

## Context

Asset allocation is fully wired end-to-end: backend classification → `_build_asset_allocation_breakdown()` → API → `RiskAnalysisAdapter` → `AssetAllocationContainer` → `AssetAllocation` component. The dashboard shows real asset class breakdowns (Equity 43.1%, Fixed Income 31.4%, Real Estate 30.6%, etc.) with per-class period performance.

Three items remain for P5 completion:
1. **Period selector UI** — hook passes `performancePeriod` but caches ignore it (see below), and UI control is commented out
2. **Target allocation + drift detection** — no infrastructure exists
3. **Historical allocation trends** — requires periodic snapshots (DB) — **deferred to backlog**

This plan covers items 1 and 2 only. Historical trends require DB schema changes and a snapshot collection system — not worth the complexity now.

---

## What Already Exists

### Frontend
- `AssetAllocationContainer.tsx` — container with `useRiskAnalysis({ performancePeriod })` wiring
- `AssetAllocation.tsx` — UI component with Allocation/Performance view modes, header at line 243
- Period state: `const [performancePeriod, _setPerformancePeriod] = useState<string>('1M')` (line 82)
- Lines 287-292: comment block explaining period selector is disabled — no actual JSX to uncomment

### Backend
- `asset_class_performance.py` — `calculate_asset_class_returns()` for period returns (1M/3M/6M/1Y/YTD)
- `core/result_objects/risk.py:831` — `_build_asset_allocation_breakdown()` builds allocation items
- `SecurityTypeService.get_full_classification()` — asset class classification per ticker
- `/api/analyze` endpoint accepts `performance_period` parameter
- Asset class perf is computed at `portfolio_service.py:286` AFTER cache check at line 224

### Cache Gap (CRITICAL — found in Codex review)
Period switching won't work without fixing caches:
- **Backend**: `portfolio_service.py:220-222` — cache key does NOT include `performance_period`. Cache returns stale results at line 224 before period-specific recompute at line 286.
- **Frontend**: `PortfolioCacheService.ts:99,237` — cache key uses `operation` only, ignores period.
- **Adapter**: `RiskAnalysisAdapter.ts:647,653` — cache key too coarse, masks period-only changes.

### DB Schema
- `portfolios` table (schema.sql:58) has no metadata JSON column — only `name`, `start_date`, `end_date`, timestamps
- `expected_returns` has its own dedicated table (schema.sql:243) — NOT stored in portfolio_metadata
- `get_portfolio_metadata()` (database_client.py:765) only returns dates/timestamps

### What's Missing
- Period selector UI (needs new JSX, not just uncommenting)
- Cache keys must include `performance_period` at 3 layers
- No target allocation config in DB or YAML
- No drift calculation logic
- No drift flags/warnings

---

## Codex Review #1 (FAIL — 2026-03-01)

Key findings addressed in revision 2:
1. **CRITICAL**: Period caches ignore `performance_period` at 3 layers — must fix cache keys
2. **HIGH**: DB persistence plan was wrong — no metadata JSON column, `expected_returns` uses dedicated table
3. **HIGH**: Config adapter threading missing for `target_allocation`
4. **MEDIUM**: Period selector is not "uncomment" — needs new JSX written
5. **MEDIUM**: Unit ambiguity — targets stored as decimals (0.40) but drift output as percentages (40.0)
6. **MEDIUM**: Missing edge cases — negative/short weights, classes only in targets, hardcoded 100% footer

## Codex Review #2 (FAIL — 2026-03-01)

Key findings addressed in this revision:
1. **HIGH**: `target_allocation` threading incomplete at config/result boundaries — plan adds DB/repository/assembler but did not specify how `target_allocation` flows through `config_from_portfolio_data()` → `analyze_portfolio()` → `analysis_metadata` → `_build_asset_allocation_breakdown()`. Fixed: added explicit B4 step for config adapter + core analysis wiring.
2. **HIGH**: Frontend cache key snippet (`${operation}_${period}`) drops existing `portfolioId.operation.vN` dimensions, causing cross-portfolio collisions. Fixed: snippet now appends period to existing key format.
3. **HIGH**: Adapter-layer period fix was not fully specified — no definition of how period reaches `transform()`/`generateCacheKey()`. Fixed: added explicit A2 threading steps for how period flows through the adapter.
4. **MEDIUM**: "Class only in targets" edge case was stated but not concretely guaranteed in merge logic. Fixed: Phase D now explicitly specifies appending target-only classes as synthetic allocation items with `current_pct=0`.

## Codex Review #3 (FAIL — 2026-03-01)

Key findings addressed in this revision:
1. **HIGH**: Adapter cache key relied on `apiResponse.analysis_metadata.asset_class_performance.period`, but `to_api_response()` does NOT serialize `asset_class_performance` into `analysis_metadata`. Fixed: adapter now stores period as instance context (set by hook before `transform()`, following `contextPortfolioId` pattern), included in cache key hash.
2. **MEDIUM**: Target-only synthetic merge hardcoded `drift_status: "underweight"` and severity from `target_pct >= 5.0`, duplicating threshold logic outside `compute_allocation_drift()`. Fixed: synthetic items now delegate to `compute_allocation_drift()` results — single source of truth for drift_status/severity.

## Codex Review #4 (FAIL — 2026-03-01)

Key findings addressed in this revision:
1. **HIGH**: Adapter period threading used mutable instance state (`contextPerformancePeriod` + `setPerformancePeriod()`), but `transform()` is called in `registry.ts` (not `useRiskAnalysis`), and the same adapter instance can be shared via `AdapterRegistry.getAdapter()` — mutable state bleeds across callers. Fixed: period is now passed immutably as `options` parameter to `transform()`, threaded from `registry.ts` where `params?.performancePeriod` is already available. No mutable state on adapter. Other callers default to `'1M'`.

---

## Implementation Plan

### Phase A: Fix Period Caching + Enable Period Selector

#### A1: Backend cache key — include performance_period

**File**: `services/portfolio_service.py`

At lines 220-222, include `performance_period` in cache key:
```python
cache_key = f"portfolio_analysis_{portfolio_data.get_cache_key()}_{risk_cache_key}_{performance_period}"
# and for the no-risk-limits path:
cache_key = f"portfolio_analysis_{portfolio_data.get_cache_key()}_{performance_period}"
```

#### A2: Frontend cache key — include period at PortfolioCacheService

**File**: `frontend/packages/chassis/src/services/PortfolioCacheService.ts`

At `generateCacheKey()` (line 99), the current key format is `${portfolioId}.${operation}.v${content.version}`. Append period to preserve all existing dimensions:
```typescript
private generateCacheKey(portfolioId: string, operation: string, period?: string): string | null {
    const content = PortfolioRepository.getPortfolioContent(portfolioId);
    if (!content) { return null; }
    const base = `${portfolioId}.${operation}.v${content.version}`;
    return period ? `${base}.p${period}` : base;
}
```

Thread `period` parameter through all callers of `generateCacheKey()` — the period comes from the `useRiskAnalysis({ performancePeriod })` hook, which passes it to the API call and cache layer.

#### A2b: Adapter cache key — include period at RiskAnalysisAdapter

**File**: `frontend/packages/connectors/src/adapters/RiskAnalysisAdapter.ts`

The adapter's `generateCacheKey()` (line 647) hashes API response content. Period changes produce different `asset_class_performance` data in the response, but the hash inputs are too coarse to detect period-only changes.

**Problem**: The API response's `analysis_metadata` (serialized at `risk.py:1055`) does NOT include `asset_class_performance`. So we CANNOT rely on extracting period from the API response.

**Important context**: `transform()` is called by the resolver (`registry.ts:125`), NOT by `useRiskAnalysis` directly. The same adapter instance can be shared via `AdapterRegistry.getAdapter()`. Using mutable instance state (`contextPerformancePeriod`) would bleed across callers.

**Fix**: Add an optional `options` parameter to `transform()` to pass period immutably:

```typescript
// Extend transform signature with optional options:
transform(
  apiResponse: RiskAnalysisApiResponse,
  options?: { performancePeriod?: string }
): RiskAnalysisTransformedData {
    const cacheKey = this.generateCacheKey(apiResponse, options?.performancePeriod);
    // ... rest unchanged
}

// In generateCacheKey(), accept and include period:
private generateCacheKey(
  apiResponse: RiskAnalysisApiResponse,
  performancePeriod?: string
): string {
    const content = {
      keys: Object.keys(apiResponse).sort(),
      hasRiskResults: !!apiResponse.risk_results,
      hasAnalysis: !!apiResponse.analysis,
      portfolioFactorBetas: apiResponse.portfolio_factor_betas || apiResponse.risk_results?.portfolio_factor_betas,
      performancePeriod: performancePeriod || '1M',  // NEW
    };
    // ... rest unchanged
}
```

**How period reaches transform()**: In `registry.ts` (line 125), `params?.performancePeriod` is already available (passed from `useRiskAnalysis` → `useDataSource`). Pass it through:
```typescript
// registry.ts, line 125:
return adapter.transform(
  result.analysis as Parameters<RiskAnalysisAdapter['transform']>[0],
  { performancePeriod: params?.performancePeriod }
) as SDKSourceOutputMap['risk-analysis'];
```

This avoids mutable state on the adapter instance. Other callers of `transform()` that don't pass options get the default `'1M'` — no bleed across call sites.

**File**: `frontend/packages/connectors/src/resolver/registry.ts`

Edit line 125 to pass `performancePeriod` through to `adapter.transform()`.

#### A3: Period selector UI

**File**: `frontend/packages/ui/src/components/dashboard/views/modern/AssetAllocationContainer.tsx`

1. Rename `_setPerformancePeriod` → `setPerformancePeriod` (line 82)
2. Add period selector buttons in the component render (near header, before `<AssetAllocation>`):
```tsx
<div className="flex gap-1 mb-3">
  {['1M', '3M', '6M', '1Y', 'YTD'].map(p => (
    <button key={p} onClick={() => setPerformancePeriod(p)}
      className={`px-2 py-1 text-xs rounded ${performancePeriod === p ? 'bg-primary text-white' : 'bg-gray-100'}`}>
      {p}
    </button>
  ))}
</div>
```

### Phase B: Target Allocation Schema

#### B1: Add field to PortfolioData

**File**: `portfolio_risk_engine/data_objects.py`

Add `target_allocation` field:
```python
target_allocation: Optional[Dict[str, float]] = None
# Values in percentage points: {"equity": 40.0, "bond": 30.0, "real_estate": 20.0, "cash": 10.0}
# Units: percentage points (40.0 = 40%), matching current_pct units
```

Thread through:
- `to_yaml()` — serialize if present
- `from_holdings()` — accept as parameter
- `get_cache_key()` — include in cache key (line ~909)

#### B2: DB persistence — dedicated table (following `expected_returns` pattern)

**File**: `database/schema.sql`

```sql
CREATE TABLE target_allocations (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    portfolio_name VARCHAR(255) NOT NULL,
    asset_class VARCHAR(100) NOT NULL,      -- "equity", "bond", "real_estate", "cash", etc.
    target_pct DECIMAL(6,2) NOT NULL,       -- Target % (40.00 = 40%)
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, portfolio_name, asset_class)
);
```

#### B3: Repository + assembler threading

**File**: `inputs/database_client.py` — add `get_target_allocations(user_id, portfolio_name)` → returns `Dict[str, float]`
**File**: `inputs/portfolio_repository.py` — add `get_target_allocations()` method
**File**: `inputs/portfolio_manager.py` — call in `_load_portfolio_from_database()`, pass to `build_portfolio_data()`
**File**: `inputs/portfolio_assembler.py` — accept `target_allocation` param in `build_portfolio_data()`

#### B4: Config adapter + core analysis wiring (target_allocation → analysis_metadata → result)

The full threading path for `target_allocation` to reach `_build_asset_allocation_breakdown()`:

1. **`portfolio_risk_engine/config_adapters.py`** — `config_from_portfolio_data()` (line 25):
   Add `target_allocation` to the config dict:
   ```python
   config: Dict[str, Any] = {
       ...
       "expected_returns": portfolio_data.expected_returns,
       "target_allocation": portfolio_data.target_allocation,  # NEW
       "name": portfolio_data.portfolio_name or "Portfolio",
   }
   ```

2. **`core/portfolio_analysis.py`** — `analyze_portfolio()` (line 188):
   Include `target_allocation` in `analysis_metadata`:
   ```python
   analysis_metadata={
       ...
       "asset_classes": asset_classes,
       "security_types": security_types,
       "target_allocation": config.get("target_allocation"),  # NEW
       "fmp_ticker_map": fmp_ticker_map,
   }
   ```

3. **`core/result_objects/risk.py`** — `_build_asset_allocation_breakdown()` (line 831):
   Read `target_allocation` from `analysis_metadata`:
   ```python
   target_allocation = (self.analysis_metadata or {}).get('target_allocation')
   ```
   Then pass to `compute_allocation_drift()` if present (see Phase D).

This ensures the chain: `PortfolioData.target_allocation` → `config_from_portfolio_data()` → `analyze_portfolio()` → `analysis_metadata["target_allocation"]` → `_build_asset_allocation_breakdown()` → drift fields in API response.

### Phase C: Drift Calculation

**File**: `portfolio_risk_engine/allocation_drift.py` (new)

All values in percentage points (40.0 = 40%) — same unit as `current_pct` in API response.

```python
DRIFT_ON_TARGET_THRESHOLD = 2.0   # |drift| < 2pp → on_target
DRIFT_WARNING_THRESHOLD = 5.0     # |drift| > 5pp → warning severity

def compute_allocation_drift(
    current_allocation: Dict[str, float],  # {asset_class: pct} in percentage points
    target_allocation: Dict[str, float],   # {asset_class: target_pct} in percentage points
) -> List[Dict[str, Any]]:
    """Compute drift between current and target allocation per asset class.

    Handles:
    - Classes present in current but not in target (no drift)
    - Classes present in target but not in current (current = 0, full underweight)
    - Negative/short allocations (drift computed normally)

    Returns list of:
    {
        "asset_class": "equity",
        "current_pct": 43.1,
        "target_pct": 40.0,
        "drift_pct": +3.1,
        "drift_status": "overweight" | "underweight" | "on_target",
        "drift_severity": "info" | "warning",  # warning if |drift| > 5pp
    }
    """
```

Thresholds (percentage points):
- `|drift| < 2pp` → on_target, severity: info
- `2pp ≤ |drift| < 5pp` → overweight/underweight, severity: info
- `|drift| ≥ 5pp` → overweight/underweight, severity: warning

### Phase D: Thread Drift Through API

**File**: `core/result_objects/risk.py`

In `_build_asset_allocation_breakdown()`:

1. Read `target_allocation` from `self.analysis_metadata` (threaded via B4)
2. If present, call `compute_allocation_drift()` to get per-class drift results
3. **Merge drift into existing allocation items** — for each allocation item, look up matching drift result by `asset_class` and add `target_pct`, `drift_pct`, `drift_status`, `drift_severity` fields
4. **Append target-only classes as synthetic items** — for asset classes in `target_allocation` but NOT in `current_allocation`, delegate to `compute_allocation_drift()` which already handles this case (current=0, full underweight). Then create a synthetic allocation item from the drift result:
   ```python
   # compute_allocation_drift() returns this for target-only classes:
   # {"asset_class": "cash", "current_pct": 0.0, "target_pct": 10.0,
   #  "drift_pct": -10.0, "drift_status": "underweight", "drift_severity": "warning"}

   # Convert drift result to allocation item:
   {
       "category": drift["asset_class"],
       "percentage": 0.0,
       "target_pct": drift["target_pct"],
       "drift_pct": drift["drift_pct"],
       "drift_status": drift["drift_status"],       # From compute_allocation_drift()
       "drift_severity": drift["drift_severity"],   # From compute_allocation_drift()
       "value": "$0",
       "change": "0.0%",
       "changeType": "neutral",
       "holdings": []
   }
   ```
   This ensures: (a) the API response includes all target classes even if the portfolio currently has zero allocation, and (b) drift_status/drift_severity are computed by the single `compute_allocation_drift()` function (no duplicated threshold logic in the merge code).

Output shape per item:
```python
{
    "category": "equity",
    "percentage": 43.1,
    "target_pct": 40.0,         # NEW — null if no targets
    "drift_pct": 3.1,           # NEW — null if no targets
    "drift_status": "overweight", # NEW — null if no targets
    "drift_severity": "info",    # NEW — null if no targets
    "value": "$62,836",
    "change": "-2.7%",
    "changeType": "negative",
    "holdings": ["AAPL", "MSFT", ...]
}
```

All new fields are `null` when no `target_allocation` is set — fully backward-compatible.

### Phase E: Frontend Drift Display

**File**: `frontend/packages/ui/src/components/portfolio/AssetAllocation.tsx`

Add drift visualization to each asset class row (only when `target_pct` is present):
- Show target % next to current % (e.g., `43.1% / target 40.0%`)
- Drift label: "Overweight +3.1%" or "Underweight -2.3%"
- Color: green (on_target), amber (info drift), red (warning drift ≥ 5pp)
- Fix footer: compute actual total from data instead of hardcoding 100% (line 341)

**File**: `frontend/packages/ui/src/components/dashboard/views/modern/AssetAllocationContainer.tsx`

Thread new fields through the data transformation:
```typescript
target_pct: item.target_pct ?? null,
drift_pct: item.drift_pct ?? null,
drift_status: item.drift_status ?? null,
drift_severity: item.drift_severity ?? null,
```

---

## Files Modified

| File | Action |
|------|--------|
| `services/portfolio_service.py` | **Edit** — include `performance_period` in cache key |
| `frontend/.../PortfolioCacheService.ts` | **Edit** — add `period` param to `generateCacheKey()`, append `.p${period}` |
| `frontend/.../RiskAnalysisAdapter.ts` | **Edit** — add `options` param to `transform()` + `generateCacheKey()`, include `performancePeriod` in hash |
| `frontend/.../resolver/registry.ts` | **Edit** — pass `performancePeriod` from params to `adapter.transform()` |
| `frontend/.../AssetAllocationContainer.tsx` | **Edit** — add period selector UI, thread drift fields |
| `frontend/.../AssetAllocation.tsx` | **Edit** — add drift visualization, fix 100% footer |
| `portfolio_risk_engine/data_objects.py` | **Edit** — add `target_allocation` field + yaml/cache threading |
| `portfolio_risk_engine/config_adapters.py` | **Edit** — include `target_allocation` in `config_from_portfolio_data()` |
| `core/portfolio_analysis.py` | **Edit** — include `target_allocation` in `analysis_metadata` |
| `portfolio_risk_engine/allocation_drift.py` | **New** — drift calculation logic |
| `core/result_objects/risk.py` | **Edit** — read targets from `analysis_metadata`, compute drift, append target-only classes |
| `database/schema.sql` | **Edit** — add `target_allocations` table |
| `inputs/database_client.py` | **Edit** — add `get_target_allocations()` |
| `inputs/portfolio_repository.py` | **Edit** — add `get_target_allocations()` |
| `inputs/portfolio_manager.py` | **Edit** — thread `target_allocation` through loading |
| `inputs/portfolio_assembler.py` | **Edit** — accept `target_allocation` param |

---

## Key Design Decisions

1. **No historical trends (deferred)**: Requires periodic snapshot collection + time-series charting. Not worth the infrastructure cost now.

2. **All values in percentage points**: Both `current_pct` and `target_pct` use percentage points (40.0 = 40%). No decimal/percent conversion ambiguity.

3. **Dedicated DB table for targets** (not metadata JSON): Follows `expected_returns` pattern — dedicated table with user_id + portfolio_name + asset_class. Allows per-class CRUD without JSON parsing.

4. **Backend-provided drift severity**: `drift_severity` ("info" | "warning") computed on backend, not frontend. Single source of truth for threshold logic. Frontend just color-codes based on severity.

5. **Three-layer cache fix**: `performance_period` must be in cache keys at backend service, frontend PortfolioCacheService, and RiskAnalysisAdapter levels.

6. **Graceful absence of targets**: All drift fields are `null` when no `target_allocation` set. UI simply doesn't render drift elements. No breaking changes.

7. **Handle edge cases explicitly**:
   - Classes in target but not current → current = 0%, full underweight
   - Classes in current but not target → no drift (null target)
   - Negative/short allocations → drift computed normally (can be negative current)
   - Footer computes actual total instead of hardcoding 100%

---

## Verification

1. **Period selector**: Switch periods (1M/3M/6M/1Y), verify performance numbers change per asset class
2. **Cache correctness**: Switch period, verify fresh API call (not stale cache), switch back, verify re-fetch
3. **Target allocation**: Set targets in DB, verify drift appears in API response
4. **Frontend drift display**: Verify drift badges render next to allocation percentages
5. **No targets**: Verify component renders normally without targets (no drift elements)
6. **Edge cases**: Class only in target (shows underweight), negative allocation, 100% footer accuracy
7. **TypeScript**: `npx tsc --noEmit` passes
8. **Chrome visual test**: Full end-to-end in browser

# Surface Trading Flags in Trading P&L Card

## Context

The backend trading analysis generates 13+ actionable flags (e.g., "poor timing: capturing only 30% of optimal exits", "conviction misaligned: bigger bets underperforming") via `generate_trading_flags()` in `core/trading_flags.py`. These flags are included in the MCP agent format response but never reach the frontend REST API path. The Trading P&L card shows grades but no actionable insights explaining *why* a grade is what it is.

## Current Gap

```
Backend: generate_trading_flags() → flags list ✓
MCP agent format: includes flags ✓
REST endpoint: uses format="full" → to_api_response() → NO flags ✗
Frontend types: no flags field ✗
Frontend resolver: doesn't map flags ✗
Frontend card: doesn't display flags ✗
```

## Flag Structure (from `core/trading_flags.py`)

Each flag is a dict:
```python
{
  "type": "poor_timing",           # flag identifier
  "severity": "warning",           # error | warning | info | success
  "message": "Average timing score is 30% — selling too early",  # human-readable
  # ... additional context fields
}
```

Severity order: error → warning → info → success (sorted by `_sort_flags()`)

## Changes

### Step 1: Backend — Add flags to API response

**File:** `trading_analysis/models.py` — `FullAnalysisResult.to_api_response()`

The method already builds the full response dict. Add flag generation at the end:

```python
from core.trading_flags import generate_trading_flags

def to_api_response(self):
    # ... existing code building response dict ...

    # Add flags
    snapshot = self.get_agent_snapshot()
    response["flags"] = generate_trading_flags(snapshot)

    return response
```

Check: `get_agent_snapshot()` is already a method on `FullAnalysisResult` (used by the MCP agent format path). `generate_trading_flags()` takes a snapshot dict and returns a list of flag dicts.

Note: Use a local import for `generate_trading_flags` inside `to_api_response()` to match existing patterns and keep coupling low.

### Step 2: Frontend types — Add flags field

**File:** `frontend/packages/chassis/src/services/APIService.ts` — `TradingAnalysisApiResponse`

Add:
```typescript
flags?: Array<{ type: string; severity: string; message: string; [key: string]: unknown }>;
```

**File:** `frontend/packages/chassis/src/catalog/types.ts` — `TradingAnalysisSourceData`

Add:
```typescript
flags?: Array<{ type: string; severity: string; message: string }>;
```

### Step 3: Frontend resolver — Map flags through

**File:** `frontend/packages/connectors/src/resolver/registry.ts` — `mapBackendTradingData()`

Pass flags through from the backend response. In the function that maps backend data to `TradingAnalysisSourceData`, add:

```typescript
flags: Array.isArray(backendData?.flags)
  ? backendData.flags.map((f: Record<string, unknown>) => ({
      type: String(f.type ?? ''),
      severity: String(f.severity ?? 'info'),
      message: String(f.message ?? ''),
    }))
  : [],
```

### Step 4: Frontend card — Display top flags

**File:** `frontend/packages/ui/src/components/portfolio/performance/TradingPnLCard.tsx`

Add a small insights section below the sub-grades grid (inside the existing `space-y-4` container). Show the top 2-3 flags by severity (errors first, then warnings).

Layout — simple list of flag messages:
```
┌─────────────────────────────────────────┐
│ ⚠ Poor timing: capturing only 30%...   │
│ ⚠ Conviction misaligned: bigger bets...│
└─────────────────────────────────────────┘
```

Styling:
- Container: `rounded-lg border border-amber-100 bg-amber-50/30 p-3` (for warnings) or `border-red-100 bg-red-50/30` (for errors)
- Or simpler: just a `space-y-1.5` list with severity-colored dots
- Each flag: `text-xs text-neutral-600` with a colored severity indicator
- Limit to 3 flags max to avoid bloating the card
- Filter: show `error`, `warning`, and `info` severity flags (skip `success` only — some important flags like `conviction_misaligned` are `info` severity)
- Flags are already sorted by severity from the backend (`_sort_flags()`), so just take the first 3

### Files Changed

| File | Layer | Change |
|------|-------|--------|
| `trading_analysis/models.py` | Backend | Add flags to `to_api_response()` |
| `frontend/packages/chassis/src/services/APIService.ts` | Frontend types | Add `flags` to API response type |
| `frontend/packages/chassis/src/catalog/types.ts` | Frontend types | Add `flags` to source data type |
| `frontend/packages/connectors/src/resolver/registry.ts` | Frontend resolver | Map flags in `mapBackendTradingData()` |
| `frontend/packages/ui/src/components/portfolio/performance/TradingPnLCard.tsx` | Frontend UI | Display top 2-3 flags |
| `mcp_tools/trading_analysis.py` | Backend | Add `flags: []` to empty-portfolio full response |
| `tests/trading_analysis/test_result_serialization.py` | Backend test | Add `flags` to expected key set |
| `tests/mcp_tools/test_trading_analysis.py` | Backend test | Assert `flags` present in empty-portfolio full response |
| `frontend/packages/chassis/src/catalog/descriptors.ts` | Frontend types | Add `flags` to trading-analysis descriptor fields |

### Step 5: Update backend serialization test

**File:** `tests/trading_analysis/test_result_serialization.py`

The test at line ~373 asserts exact top-level keys in `to_api_response()`. Add `"flags"` to the expected key set.

### Step 6: Add flags to empty-portfolio response path

**File:** `mcp_tools/trading_analysis.py`

The `format="full"` path has a separate empty-response dict for portfolios with no trading data (~line 95). Add `"flags": []` to that dict so the contract is consistent whether data exists or not.

### No changes needed:
- `core/trading_flags.py` — flag generation already works
- `routes/trading.py` — REST endpoint passes through whatever `to_api_response()` returns
- `useTradingAnalysis.ts` — hook passes through whatever the resolver returns

## Verification

1. Backend: Call `GET /api/trading/analysis` and confirm `flags` array is in the response
2. TypeScript check across all three frontend packages
3. Browser: Performance view → Trading P&L card, confirm flag messages appear below sub-grades
4. Confirm error/warning/info flags show (success flags filtered out)
5. Confirm flag messages match what the MCP agent format already produces

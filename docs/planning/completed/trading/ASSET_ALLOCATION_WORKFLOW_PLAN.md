# Asset Allocation → Interactive Workflow (Phase 4)

## Context

The Asset Allocation view currently displays real allocation data from `useRiskAnalysis()` — asset class breakdowns with drift indicators (target_pct, drift_pct, drift_status, drift_severity). Backend MCP tools exist for setting targets (`set_target_allocation`), reading targets (`get_target_allocation`), and generating rebalance trades (`generate_rebalance_trades`). However, **no REST API endpoints** expose these capabilities, so the frontend can only display drift data passively.

**Goal:** Upgrade from data-display to an interactive **monitor → set targets → rebalance** workflow. Users should be able to: (1) view current allocation vs targets with drift, (2) set/edit target allocations inline, (3) generate and preview rebalance trades.

---

## Changes

### 1. Backend: REST Endpoints in `app.py`

No new service file needed — the MCP tools are thin wrappers around `PortfolioRepository` + validation. Import `_validate_and_normalize_allocations()` from `mcp_tools/allocation.py` and call `PortfolioRepository` directly. Add 3 endpoints (~80 lines):

**`GET /api/allocations/target?portfolio_name=CURRENT_PORTFOLIO`**
- Auth: `get_current_user()` → `resolve_user_id(user['email'])`
- Calls `PortfolioRepository().get_target_allocations(user_id, portfolio_name)`
- Returns: `{"success": true, "status": "success"|"not_set", "allocations": {...}, "total_pct": 100.0}`

**`POST /api/allocations/target`**
- Body: `{"allocations": {"equity": 60, "bond": 30, "cash": 10}, "portfolio_name": "CURRENT_PORTFOLIO"}`
- Validates via `_validate_and_normalize_allocations()` (reuse from `mcp_tools/allocation.py`)
- Calls `PortfolioRepository().save_target_allocations(user_id, portfolio_name, normalized)`
- Returns: `{"success": true, "allocations": {...}, "total_pct": 100.0}`

**`POST /api/allocations/rebalance`**
- Body: `{"target_weights": {"AAPL": 0.10, ...}, "min_trade_value": 100}`
- Delegates to `generate_rebalance_trades()` from `mcp_tools/rebalance.py` (pass `user_email=user['email']`, `format="full"`). This reuses the full MCP function including validation, unmanaged positions, skipped trades, warnings — not just the low-level `compute_rebalance_legs()`.
- Returns: `RebalanceTradeResult.to_api_response()` shape (trades array + summary)

### 2. Frontend: Query Keys + APIService

**`queryKeys.ts`** — Add `targetAllocationKey` using `scoped()`. Also add to `AppQueryKey` union type.

**`APIService.ts`** — Add 3 methods + types:
- `getTargetAllocations(portfolioName?)` → GET `/api/allocations/target`
- `setTargetAllocations(allocations, portfolioName?)` → POST `/api/allocations/target`
- `generateRebalanceTrades(params)` → POST `/api/allocations/rebalance`

### 3. Frontend: TanStack Query Hooks

**New: `connectors/src/features/allocation/hooks/`**

- **`useTargetAllocation.ts`** — `useQuery` with `targetAllocationKey`, `staleTime: 5min`
- **`useSetTargetAllocation.ts`** — `useMutation` that invalidates `targetAllocationKey` AND calls `cacheCoordinator.invalidateRiskData(portfolioId)` on success (drift recomputes from stored targets). Note: `useRiskAnalysis` uses DataSource/SDK query keys, not `riskAnalysisKey` directly — must go through `CacheCoordinator` for proper invalidation.
- **`useRebalanceTrades.ts`** — `useMutation` for generating rebalance trades on demand
- **`index.ts`** — barrel export

Wire into `connectors/src/index.ts`.

### 4. Frontend: Container Wiring (`AssetAllocationContainer.tsx`)

~100 lines added:
- Import 3 new hooks
- Add state: `isEditing`, `editTargets: Record<string, number>`, `showRebalance`
- **Preserve canonical asset-class keys**: Container currently humanizes keys (`bond` → `Fixed Income`) via `formatAssetClassName()`. Must preserve the raw canonical key (e.g., `asset_class_key: "bond"`) alongside the display name, since `POST /api/allocations/target` requires canonical lowercase keys (backend validates via `is_valid_asset_class()`).
- "Set Targets" button: opens inline edit. Pre-fills with current targets or current allocation percentages.
- "Rebalance" button: visible when targets set + drift exists. Calls rebalance mutation.
- Pass new props to `AssetAllocation` component.

### 5. Frontend: UI Enhancement (`AssetAllocation.tsx`)

~80 lines added:
- Extend props with edit/rebalance state + callbacks (all optional, backward-compatible)
- **Edit mode**: Number inputs replace static "target X%" badges. Running total with validation color (green at 100%, red otherwise).
- **Action buttons** in header: "Set Targets" + "Rebalance" (conditional on targets existing)
- **Rebalance preview panel**: Collapsible section below allocation table. Sequenced trade legs (sells first, buys second), summary stats (trade count, net cash, total value), warnings.

---

## Files to Modify

**Backend (1 file):**
- `app.py` — 3 new endpoints

**Reused backend (no changes):**
- `mcp_tools/allocation.py` — `_validate_and_normalize_allocations()` imported for target endpoints
- `mcp_tools/rebalance.py` — `generate_rebalance_trades()` called directly for rebalance endpoint
- `inputs/portfolio_repository.py` — `save_target_allocations()`, `get_target_allocations()`

**Frontend (9 files):**
- `frontend/packages/chassis/src/queryKeys.ts` — Add key
- `frontend/packages/chassis/src/services/APIService.ts` — Add 3 methods + types
- `frontend/packages/connectors/src/features/allocation/hooks/useTargetAllocation.ts` — New
- `frontend/packages/connectors/src/features/allocation/hooks/useSetTargetAllocation.ts` — New
- `frontend/packages/connectors/src/features/allocation/hooks/useRebalanceTrades.ts` — New
- `frontend/packages/connectors/src/features/allocation/hooks/index.ts` — New barrel
- `frontend/packages/connectors/src/features/allocation/index.ts` — New feature barrel
- `frontend/packages/connectors/src/features/index.ts` — Add allocation export
- `frontend/packages/connectors/src/index.ts` — Re-export
- `frontend/packages/ui/src/components/dashboard/views/modern/AssetAllocationContainer.tsx` — Wire hooks
- `frontend/packages/ui/src/components/portfolio/AssetAllocation.tsx` — Edit mode + rebalance UI

---

## Implementation Order

| Step | Scope | Files | Depends On |
|------|-------|-------|------------|
| 1 | Backend REST endpoints | `app.py` | — |
| 2 | Query keys + API methods | `queryKeys.ts`, `APIService.ts` | — |
| 3 | TanStack hooks | `features/allocation/` (new), `connectors/index.ts` | Step 2 |
| 4 | Container wiring | `AssetAllocationContainer.tsx` | Steps 2-3 |
| 5 | UI enhancement | `AssetAllocation.tsx` | Step 4 |

Steps 1 and 2 are independent (parallelizable).

---

## Key Design Notes

- **Asset-class → per-ticker bridge**: Targets are set at asset-class level. Rebalance works per-ticker. Container bridges by computing proportional per-ticker weights from current holdings within each asset class.
- **Cache invalidation**: Setting targets invalidates `targetAllocationKey` AND calls `cacheCoordinator.invalidateRiskData(portfolioId)`. `useRiskAnalysis` uses DataSource/SDK query keys (not `riskAnalysisKey` directly), plus `PortfolioCacheService` caching — must go through `CacheCoordinator` for proper invalidation.
- **User resolution**: REST uses `get_current_user()` → `resolve_user_id(email)`. MCP uses `resolve_user_email()`. Both reach the same `PortfolioRepository`.
- **Validation UX**: Running total with color coding (green at 100%, red otherwise). Same 100% ± 0.5% tolerance as backend.

---

## Verification

1. `python3 -m pytest tests/ -x -v` — no regressions
2. `curl http://localhost:8000/api/allocations/target` — returns targets or "not_set"
3. `curl -X POST http://localhost:8000/api/allocations/target -d '{"allocations":{"equity":60,"bond":30,"cash":10}}'` — saves
4. Frontend: Asset Allocation view → "Set Targets" → edit → save → drift updates
5. "Rebalance" → preview panel shows trade legs
6. Chrome browser verification of full workflow

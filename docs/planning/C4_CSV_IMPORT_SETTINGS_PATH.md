# C4 Follow-up: CSV Import Settings Path + Live Test

**Status**: Ready to implement
**Depends on**: C4 implementation (Phases 1-3) — all landed
**Spec**: `SPEC_C4_WEB_CSV_IMPORT.md`

---

## Problem

The CSV import UI (`CsvImportStep`) is only reachable during onboarding — either via `OnboardingWizard` (first-time users) or `EmptyPortfolioLanding` (no positions). Users who already have a portfolio cannot access it from the Settings page or anywhere else in the app.

This means:
- Existing users can't import additional CSVs
- The Phase 1-3 normalizer builder flow can't be live tested without creating a fresh user or clearing the portfolio

## Current Routing

```
ModernDashboardApp.tsx
  └── PortfolioInitializer
        ├── onboardingFallback → OnboardingBootstrapSurface → OnboardingWizard
        │                                                      └── CsvImportStep
        ├── emptyPortfolioFallback → OnboardingBootstrapSurface → EmptyPortfolioLanding
        │                                                          └── CsvImportStep
        └── (has positions) → normal dashboard
              ├── 'settings' view → RiskSettingsContainer + AccountConnectionsContainer
              └── (NO import option anywhere)
```

Onboarding gating: `localStorage` flags `onboarding_completed_{userId}` / `onboarding_dismissed_{userId}`.

## Required Change

Add a CSV import section to the **main settings view** in `ModernDashboardApp.tsx` (the `'settings'` case that renders `RiskSettingsContainer` + `AccountConnectionsContainer`) so logged-in users with existing portfolios can upload additional CSVs and trigger the normalizer builder flow.

**Note:** `SettingsPanel.tsx` is a narrow portfolio-overview preferences sheet — NOT the main settings page. The correct target is the `'settings'` view in `ModernDashboardApp.tsx`.

### Approach: New CsvImportCard in the Settings View

Add a new card below `AccountConnectionsContainer` in the `'settings'` case of `ModernDashboardApp.tsx`:

```tsx
case 'settings':
  return (
    <div className="space-organic animate-stagger-fade-in">
      <div className="hover-lift-premium mb-8">
        <RiskSettingsContainer />
      </div>
      <div className="hover-lift-premium mb-8">
        <AccountConnectionsContainer />
      </div>
      <div className="hover-lift-premium">
        <CsvImportCard />    {/* NEW */}
      </div>
    </div>
  );
```

`CsvImportCard` is a thin wrapper that:
- Renders `CsvImportStep` inline with a "Import Portfolio CSV" header
- Provides its own `onConfirm` handler (see Post-Import State below)
- Provides `onCancel` that collapses/hides the import area

## Key Files

| File | Role |
|------|------|
| `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx` | App shell — add `CsvImportCard` to the `'settings'` case |
| `frontend/packages/ui/src/components/settings/CsvImportCard.tsx` | **NEW** — thin wrapper around `CsvImportStep` with settings-context `onConfirm` |
| `frontend/packages/ui/src/components/onboarding/CsvImportStep.tsx` | CSV import component (already built, reuse as-is) |
| `frontend/packages/ui/src/components/onboarding/NormalizerBuilderPanel.tsx` | AI normalizer builder (Phase 3, already wired into CsvImportStep) |
| `frontend/packages/ui/src/components/onboarding/useOnboardingActivation.ts` | Reference only — do NOT reuse `beginCsvImport` / `commitSuccessfulPortfolio` (see below) |
| `routes/onboarding.py` | Backend: `import-csv`, `preview-csv`, `stage-csv` endpoints (auth-gated, not onboarding-gated) |
| `routes/positions.py` | `GET /api/positions/holdings` — combined positions from registered providers (cached brokerage + CSV) |
| `services/position_service.py` | `PositionService.get_all_positions()` — aggregates registered providers + CSV (excludes `position_source='database'`) |
| `providers/csv_positions.py` | CSV storage — `_resolve_path()` ignores `user_email` (see Known Risks) |
| `frontend/packages/chassis/src/services/CacheCoordinator.ts` | `invalidateAllData(portfolioId)` — clears adapter + PortfolioCacheService + legacy query keys |
| `frontend/packages/connectors/src/providers/SessionServicesProvider.tsx` | Reference for store commit pattern (lines 329-340) — preserves id/name when committing |

## Implementation Notes

### CsvImportStep Reusability
- `CsvImportStep` takes `onConfirm: (selection: CsvImportSelection) => Promise<void> | void` and `onCancel: () => void`
- Already used standalone in `EmptyPortfolioLanding.tsx` — confirmed reusable outside wizard context
- `NormalizerBuilderPanel` is wired in but NOT automatic — it appears after the user clicks "Build with AI" and the CSV is staged successfully. This is the correct UX (user-initiated, not forced).

### Post-Import State Strategy (Critical)

The onboarding `beginCsvImport` in `useOnboardingActivation.ts` calls `commitSuccessfulPortfolio()` which writes the API response directly to `PortfolioRepository`. **This is wrong for existing users** because `_build_csv_portfolio_response()` in `routes/onboarding.py` rebuilds `portfolio_data` from ONLY the newly imported `source_key`, not the user's full combined portfolio. In onboarding this is fine (it's the first source). In settings, it would **replace** the in-memory portfolio with just the last CSV import.

**Understanding the 4-layer cache architecture:**

The app has 4 cache layers that all need to be synchronized after import:
1. **Zustand store** (`PortfolioRepository`) — in-memory portfolio; `portfolio-summary` adapter reads holdings via `getPortfolio(portfolioId)` → `store.byId[targetId].portfolio.holdings`
2. **TanStack Query (SDK-prefixed)** — most live data flows through `useDataSource()` with keys `['sdk', sourceId, params]` (NOT the old-style `positionsHoldingsKey()` etc.)
3. **PortfolioCacheService** — content-version-aware adapter cache; keys include `contentVersion` so stale entries become unreachable after version bump
4. **UnifiedAdapterCache** — per-adapter cache, cleared via `cacheCoordinator`

**Solution — backend addition + 4-step frontend refresh:**

The root problem: no existing endpoint returns a full combined portfolio (all brokerages + all CSV sources) in the `Portfolio` shape the Zustand store needs. `refreshHoldings()` is brokerage-only, `import-csv` returns one source only, and `/api/positions/holdings` uses a different field names. A small backend change resolves this cleanly.

### Backend Change: New `/api/onboarding/import-csv-full` Endpoint

Add a new endpoint on the existing `onboarding_router` in `routes/onboarding.py` that combines the import + full portfolio rebuild in one call. The key insight: **`PositionService.get_all_positions()`** already combines registered providers (cached brokerage positions from DB + CSV + live brokerage refreshes where applicable) and applies `_apply_csv_api_safety_guard()` to prevent double-counting. Use it as the single source of truth, then map to Portfolio shape.

**Note on coverage:** `get_all_positions()` aggregates positions from registered providers (Plaid, SnapTrade, Schwab, IBKR, CSV). It reads DB-cached positions per-provider (filtered by `position_source`), not the entire `positions` table. Positions with `position_source='database'` (manually-added legacy positions) are **not included** — see "Known Limitations" below.

```python
@onboarding_router.post("/import-csv-full")
async def import_csv_with_full_portfolio(
    request: Request,
    file: UploadFile = File(...),
    institution: Optional[str] = Form(None),
) -> dict[str, Any]:
    user = _get_authenticated_user(request)
    upload_content = await file.read()
    temp_path = _write_upload_to_temp(file, upload_content)

    # Step 1: Persist CSV to CSVPositionProvider (same as existing import-csv)
    try:
        result = await run_in_threadpool(
            import_portfolio, file_path=temp_path,
            brokerage=str(institution or "").strip(), dry_run=False,
            user_email=user["email"],
        )
    finally:
        await file.close()
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass

    if result.get("status") != "ok":
        return _shape_csv_error(result)

    # Step 2: Rebuild full combined portfolio via PositionService
    # Fetches from all registered providers (cached brokerage + CSV),
    # applies _apply_csv_api_safety_guard() to prevent double-counting.
    svc = PositionService(user_email=user["email"])
    position_result = await run_in_threadpool(
        svc.get_all_positions, consolidate=True,
    )

    # Step 3: Map PositionResult → Portfolio shape
    # PositionsData fields: ticker, quantity, value, name, type, ...
    # Frontend Holding fields: ticker, shares, market_value, security_name
    holdings = []
    total_value = 0.0
    for pos in position_result.data.positions:
        market_value = round(float(pos.get("value", 0)), 2)
        holdings.append({
            "ticker": pos.get("ticker", ""),
            "shares": float(pos.get("quantity", 0)),
            "market_value": market_value,
            "security_name": pos.get("name") or pos.get("ticker", ""),
        })
        total_value += market_value

    holdings.sort(key=lambda h: h["market_value"], reverse=True)

    return {
        "status": "success",
        "import_count": int(result.get("imported", 0)),
        "warnings": list(result.get("warnings", [])),
        "portfolio_data": {
            "holdings": holdings,
            "total_portfolio_value": round(total_value, 2),
            "statement_date": date.today().isoformat(),
            "account_type": "investment",
        },
        "portfolio_name": "CURRENT_PORTFOLIO",
    }
```

**Why `PositionService.get_all_positions()` instead of manual merging:**
- It combines all registered providers (cached brokerage + CSV) in one call
- It applies `_apply_csv_api_safety_guard()` which strips CSV rows whose brokerage matches an API-connected provider — no separate guard needed
- Constructor: `PositionService(user_email=user["email"])` (optional `user_id` for DB lookups)
- `consolidate=True` applies cross-provider dedup (merges same-ticker rows from different sources)
- The only new code is the field mapping: `quantity` → `shares`, `value` → `market_value`, `name` → `security_name` (with `or` fallback since `name` is optional in `PositionsData`)

### Frontend: 4-Step Refresh

**Scope:** The settings path is for users who already have positions (reached via the `'settings'` view in `ModernDashboardApp.tsx`). Users with no positions go through onboarding — the existing onboarding flow is unchanged.

1. **POST to `/api/onboarding/import-csv-full`** — persists CSV to filesystem AND returns combined `portfolio_data` from all registered providers (brokerage + CSV, safety-guard applied via `PositionService`). Covers the primary settings-path user classes for the current session: brokerage-connected, CSV-only, and mixed. (Manual DB positions excluded; store-backed views revert to DB-only on page reload — see Known Limitations.)

2. **Commit to Zustand store:**
   - Read `currentPortfolioId` and `getName()` from existing store (preserves id/name, same pattern as `SessionServicesProvider.tsx` lines 329-340)
   - Call `PortfolioRepository.add({ ...response.portfolio_data, id: currentId, portfolio_name: currentName })`
   - Call `PortfolioRepository.setCurrent(id)`
   - `updatePortfolio()` increments `contentVersion` when holdings changed (which they will — PositionService now includes the new CSV data). This makes old `PortfolioCacheService` entries unreachable.

3. **Invalidate all query + adapter caches:**
   ```typescript
   // Clear ALL SDK-prefixed TanStack queries (the active data layer)
   queryClient.invalidateQueries({ queryKey: ['sdk'] });
   // Clear adapter + PortfolioCacheService layers
   cacheCoordinator.invalidateAllData(portfolioId);
   ```
   Active SDK queries that are currently mounted will automatically refetch after invalidation. `useDataSourceScheduler` will NOT re-prefetch for the same portfolio ID (it short-circuits on same ID), but mounted queries' own refetch handles it.

4. **Show success toast** with `import_count` from the response.

**Why a new endpoint instead of frontend branching?**
- `refreshHoldings()` is brokerage-only (no CSV data), errors for CSV-only users, and the fallback detection (`portfolio: null`) is ambiguous (also triggers for rate-limiting/provider failures)
- Existing `import-csv` response is single-source-only, overwrites store for multi-CSV users
- `PositionService.get_all_positions()` already solves the combination + dedup problem. Wrapping it in a new endpoint with a field-name mapping is minimal work for a correct result.

**Why not just invalidate queries without updating the store?**
Because `portfolio-summary` reads `holdings` directly from the Zustand store (via `getPortfolio(portfolioId)` in `registry.ts`). The store must be refreshed — query invalidation alone won't update it. `PortfolioInitializer` only bootstraps when `currentPortfolio` is null, so it won't help.

### Same-Brokerage Re-Import Semantics

CSV storage in `CSVPositionProvider` is keyed by `source_key` (derived from institution/filename). Re-importing the same brokerage **replaces** that source's positions (not appends). This is the correct behavior — a new CSV export from Schwab should replace the old Schwab snapshot. No changes needed here.

**Deferred:** A "this will replace your existing {institution} positions" warning would require a new backend signal (the existing endpoints don't expose whether a `source_key` already exists). Out of scope for this change — can be added as a follow-up if users find the overwrite surprising.

### Backend Endpoints

All endpoints are auth-gated only (via `_get_authenticated_user(request)`), no onboarding-specific guards:
- `POST /api/onboarding/preview-csv` — dry-run preview (existing)
- `POST /api/onboarding/import-csv` — persist import, returns single-source portfolio (existing, used by onboarding)
- `POST /api/onboarding/import-csv-full` — persist import + returns full combined portfolio via PositionService (**NEW**, used by settings path)
- `POST /api/onboarding/stage-csv` — stage for normalizer builder (existing)

All on the existing `onboarding_router` — no new router registration needed in `app.py`. The `/api/onboarding/` prefix is a misnomer but not worth renaming now.

## Known Limitations

### CSV-Only Positions Not in Backend Analysis (Pre-Existing)
Backend analysis endpoints (`risk-analysis`, `risk-score`, `performance`) load the portfolio via `PortfolioManager.load_portfolio_data()`, which reads from the DB `positions` table. CSV import writes to the filesystem-backed `CSVPositionProvider`, not to DB. This means:
- **Frontend store + summary** — CSV positions ARE visible (the new endpoint merges them into `portfolio_data`)
- **Positions monitor** (`GET /api/positions/holdings` via `PositionService`) — CSV positions ARE visible
- **Risk/performance analysis** — CSV-only positions are NOT included in analysis calculations (these endpoints independently load from DB)

This is a **pre-existing architectural gap** — the same limitation exists in the current onboarding flow. The new endpoint improves the situation (store now has combined data), but doesn't fully close it for backend analysis.

**Future fix (out of scope):** Either sync CSV positions into the DB portfolio after import, or make analysis endpoints source-aware via `PositionService`. This is a separate initiative.

### Manual DB Positions Excluded from Import Refresh
`PositionService.get_all_positions()` fetches from registered providers only. Positions with `position_source='database'` (created via portfolio create/update APIs, not brokerage connections or CSV import) are not included. After a settings-path CSV import, the store overwrite will drop any manual DB positions from the UI for the current session.

**Impact:** Minimal in practice — users who reach the settings path typically have brokerage connections and/or CSV imports, not manually-entered DB positions. If affected, a page reload does NOT fully resolve this (see "CSV Not in Bootstrap Path" below).

**Future fix:** Add `'database'` as a virtual provider in `PositionService`, or query manual positions separately with proper pricing. This requires non-trivial work (manual DB rows stored via `get_portfolio_positions()` don't carry pre-computed `value`/`market_value` — they'd need FMP pricing and consolidation). Out of scope.

### CSV Not in Bootstrap Path (Pre-Existing)
On page reload, `PortfolioInitializer` fetches from `GET /api/portfolios/CURRENT_PORTFOLIO`, which loads via `PortfolioManager.load_portfolio_data()` — this is DB-backed only. CSV positions (persisted to filesystem JSON via `CSVPositionProvider`) are not included in the bootstrap load. This means:
- **Within a session:** After CSV import via the new endpoint, the store has combined data (brokerage + CSV). The store-backed total portfolio value correctly reflects CSV data. However, `portfolio-summary` is mixed: `totalValue` comes from store holdings, but the adapter currently returns `holdings: []` (the holdings view reads from a separate path), and analysis metrics (risk score, volatility, YTD return, Sharpe, alpha) are derived from `risk-score`, `risk-analysis`, and `performance` SDK sources, which call DB-backed backend routes (via `RiskAnalysisService` → `PortfolioManager(use_database=True)`). Those analysis metrics remain DB-only even in-session.
- **After page reload:** The store is re-initialized with DB-only data (via `PortfolioInitializer`). CSV positions disappear from the store, so `totalValue` (store-derived) reverts to DB-only. Analysis metrics (risk score, volatility, Sharpe, etc.) are unaffected by reload because they were already DB-only even in-session. The holdings view is also unaffected because it reads from `usePositions()` / `positions-enriched` (backed by `PositionService`), which still includes CSV data from the persisted filesystem JSON. The store is NOT repaired by SDK refetches — `useDataSource` refreshes query data but does not write back to Zustand.

This is a **pre-existing architectural gap** — the same problem exists today in the onboarding flow. It is not introduced or worsened by this change. The new `/api/onboarding/import-csv-full` endpoint actually improves the in-session experience compared to the current onboarding flow (which only loads a single CSV source into the store).

**Future fix:** Modify `PortfolioInitializer` to bootstrap from a combined-source endpoint (backed by `PositionService`) instead of the DB-only portfolio API. This is a broader architectural change and is out of scope for this feature.

### CSV Storage Not User-Scoped
`CSVPositionProvider._resolve_path()` ignores `user_email` — all users write to the same `~/.risk_module/positions.json`. This is a pre-existing issue (not introduced by this change) and is acceptable for the current single-user deployment. Flag for future multi-user work.

---

## Live Test Plan

After the settings path is wired, run through these steps to verify all 3 C4 phases work end-to-end:

### Test 1: Recognized CSV (happy path)
1. Go to Settings → Import Portfolio CSV
2. Upload a Schwab or IBKR CSV export
3. **Expected**: Auto-detected, preview shows positions, "Confirm import" works

### Test 2: Unrecognized CSV → `needs_normalizer` UI (Phase 1)
1. Create a test CSV with non-standard headers:
   ```
   Account Number,Account Name,Symbol,Description,Quantity,Last Price,Current Value
   Z12345,Individual,AAPL,APPLE INC,100,172.50,17250.00
   Z12345,Individual,MSFT,MICROSOFT CORP,50,415.20,20760.00
   ```
2. Upload it
3. **Expected**: "Format not recognized" amber panel appears showing:
   - Detected columns as tags (Account Number, Symbol, etc.)
   - Sample rows in a pre block
   - "Select institution manually" button
   - "Build with AI" button

### Test 3: Normalizer Builder flow (Phase 2 + 3)
1. From the "Format not recognized" panel, click "Build with AI"
2. **Expected**: CSV is staged via `POST /api/onboarding/stage-csv`, inline chat panel opens
3. Claude in the chat panel should:
   - Analyze the CSV headers
   - Generate a normalizer using `normalizer_stage`
   - Test it with `normalizer_test`
   - Activate with `normalizer_activate`
4. **Expected**: After activation, the import auto-retries, preview appears, confirm works

### Test 4: Institution override (Phase 1)
1. Upload an unrecognized CSV
2. Click "Select institution manually"
3. Select an institution from the dropdown
4. **Expected**: Preview re-runs with institution hint

### Test 5: Backend API verification (can run without UI)
```bash
# needs_normalizer response includes new fields
python3 -c "
from mcp_tools.import_portfolio import import_portfolio
import json
r = import_portfolio(file_path='/tmp/test.csv', brokerage='', dry_run=True)
print(json.dumps(r, indent=2))
"
# Verify: detected_headers, header_line_index, row_count present

# Stage → test → activate → retry pipeline
python3 -c "
from mcp_tools.normalizer_builder import *
import json
r = normalizer_sample_csv(file_path='/tmp/test.csv')
print(json.dumps(r, indent=2))
# Then stage, test, activate as needed
"
```

### Test 6: stage-csv endpoint
```bash
curl -X POST http://localhost:8000/api/onboarding/stage-csv \
  -H "Cookie: session_id=YOUR_SESSION" \
  -F "file=@/tmp/test.csv" | python3 -m json.tool
# Verify: file_path and filename returned, file exists at path
```

# B-016: Per-Position Risk Score — Wire Risk Data + Composite Score

**Status**: COMPLETE — implemented in commit `8a8445ad`

## Context

The Holdings view (⌘2) has per-position `volatility` and `alerts` but no risk score, beta, or risk contribution. The backend already has `get_monitor_with_risk()` in `services/portfolio_service.py` (~line 697) that runs `analyze_portfolio()` and extracts per-ticker: `beta` (market), `risk_pct` (euler variance contribution), `volatility`, `max_drawdown`. This method is fully implemented but **never called** from the holdings route.

The frontend `Holding` interface already has a `beta` field (defaults to 1) but no `riskScore`. There is no Risk Score column in the table. `riskScore` / `aiScore` never existed in the frontend — this is net-new.

## Approach

1. Wire `get_monitor_with_risk()` into the holdings route to enrich positions with factor-model-derived risk data
2. Compute a simple 0-100 composite risk score per position from available metrics
3. Add a Risk Score column to the Holdings table

## Scoring Formula

Simple weighted composite from 4 normalized dimensions (each 0-100). All inputs use **decimal form** from the risk analysis engine (not the percentage-point values from market data enrichment):

```
# Inputs from get_monitor_with_risk() — all in decimal form:
# volatility: 0.25 = 25%, max_drawdown: -0.50 = -50%, beta: 1.2

volatility_score = clamp(volatility / 0.50 * 100, 0, 100)    # 50% vol = max score
drawdown_score   = clamp(|max_drawdown| / 0.50 * 100, 0, 100) # 50% drawdown = max
beta_score       = clamp(|beta| / 2.0 * 100, 0, 100)          # beta 2.0 = max
concentration_score = clamp(weight / 0.25 * 100, 0, 100)      # 25% weight = max

risk_score = round(
    volatility_score * 0.35 +
    drawdown_score * 0.25 +
    beta_score * 0.20 +
    concentration_score * 0.20
)
```

**Unit note**: `enrich_positions_with_market_data()` stores volatility as percentage points (50.0), but `get_monitor_with_risk()` uses the risk engine's decimal values (0.50). The scoring formula uses the risk engine's decimal values. Do NOT mix the two.

**`weight` computation**: `to_monitor_view()` does not include a `weight` field. Compute from `abs(gross_exposure) / sum(abs(gross_exposure))` across all positions within the enrichment method. Use gross exposure sum (not `total_value`) as the denominator to avoid sign issues with long/short portfolios where net `total_value` can be near-zero or negative.

**Null handling**: If any of the 4 scoring inputs (volatility, max_drawdown, beta, weight) are missing for a position, set `risk_score = None` for that position. The frontend renders `None` as "—" (em-dash) instead of a colored badge. Do NOT default missing metrics to 0, as that would mislabel positions as "Low risk" when we simply lack data.

Higher score = higher risk. Buckets: 0-25 Low (green), 26-50 Medium (blue), 51-75 High (amber), 76-100 Very High (red).

## Changes

### 1. Backend: `services/portfolio_service.py` — Add `enrich_positions_with_risk()`

Add a new method that takes the `PositionResult` (not just payload) and the enriched payload, following the `get_monitor_with_risk()` pattern at line ~697:

- Build `PortfolioData` from `result` (same as `get_monitor_with_risk()` does at line ~751)
- Call `ensure_factor_proxies(user_id, portfolio_name, tickers, allow_gpt=False)` to resolve factor proxies (same as `get_monitor_with_risk()` at line ~767-775)
- Call `analyze_portfolio()` on the enriched `PortfolioData`
- Extract per-ticker from `RiskAnalysisResult`: `beta` (from `stock_betas["market"]`), `risk_pct` (from `euler_variance_pct`), `max_drawdown` (from `asset_vol_summary["Max Drawdown"]`), `volatility` (from `asset_vol_summary["Vol A"]`)
- Compute `weight` per position from `abs(gross_exposure) / total_gross` where `total_gross = sum(abs(p.gross_exposure) for p in positions)`. This avoids division-by-zero/negative issues with long/short portfolios.
- Compute `risk_score` (0-100) per position using the formula above. If any of the 4 inputs are `None`, set `risk_score = None`.
- Write `position["risk_score"]`, `position["beta"]`, `position["risk_pct"]`, `position["max_drawdown"]` to each position dict in `payload["positions"]`

**Method signature**: `enrich_positions_with_risk(self, result: PositionResult, payload: dict, portfolio_name: str, user_id: int) -> None`

The `portfolio_name` and `user_id` are required because `ensure_factor_proxies()` (line ~767) needs them to resolve factor proxies. Both are available in the route handler from the authenticated user context.

**Performance consideration**: `analyze_portfolio()` is expensive (~2-5s). The cache is **instance-local** (`ServiceCacheMixin` creates per-instance `TTLCache`), and the holdings route creates a new `PortfolioService()` per request (`routes/positions.py` line ~153), so there is no cross-request cache sharing. This means risk enrichment will always incur the full `analyze_portfolio()` cost on first load. This is acceptable because: (a) holdings is not a high-frequency endpoint, (b) the try/except wrapper means holdings still loads immediately without risk data on failure, and (c) the enrichment can be made lazy/async in a future iteration if latency becomes a concern. Wrap in try/except so holdings still loads without risk data.

### 2. Backend: `routes/positions.py` — Call risk enrichment

After existing enrichment (sectors, market data, flags), call `enrich_positions_with_risk()` passing the `result` object, `portfolio_name`, and `user_id`:

```python
try:
    portfolio_svc.enrich_positions_with_risk(result, payload, "CURRENT_PORTFOLIO", user["user_id"])
except Exception:
    pass  # Graceful — risk enrichment is supplementary
```

**Note**: `result` is the `PositionResult` from `position_service.get_all_positions()` — it's already available in the route handler. `user` is the authenticated user dict from `auth_service.get_user_by_session()` (line ~141), which contains `user_id`. `portfolio_name` is hardcoded to `"CURRENT_PORTFOLIO"` — this is the canonical default used by all routes (`routes/plaid.py`, `routes/provider_routing.py`). The auth service user dict does not include `portfolio_name`.

### 3. Frontend: Types — `PositionsMonitorPosition` + `PositionsHolding`

**File**: `frontend/packages/chassis/src/types/index.ts`
Add to `PositionsMonitorPosition`:
```typescript
risk_score?: number | null;
beta?: number | null;
risk_pct?: number | null;
max_drawdown?: number | null;
```

**File**: `frontend/packages/connectors/src/adapters/PositionsAdapter.ts`
Add to `PositionsHolding` interface and `normalizeHolding()`:
```typescript
riskScore?: number;
beta?: number;
riskPct?: number;
maxDrawdown?: number;
```

### 4. Frontend: `HoldingsView.tsx` — Add Risk Score column + fix beta mapping

**File**: `frontend/packages/ui/src/components/portfolio/HoldingsView.tsx`

**4a. Add fields to `Holding` interface** (line ~195):
```typescript
riskScore?: number;   // 0-100 composite, undefined = no data
riskPct?: number;     // Euler variance contribution
maxDrawdown?: number; // Max drawdown (decimal)
```

**4b. Fix `beta` mapping** — Both the `useState` initializer (line ~289) and `useEffect` sync (line ~338) use `holding.beta || 1`, which overwrites a valid `0` beta. Change to:
```typescript
beta: holding.beta ?? 1,  // ?? preserves 0, || does not
```

**4c. Add risk field mappings** — In both the `useState` initializer (line ~273) and the `useEffect` data sync (line ~322), add mappings for new fields:
```typescript
riskScore: holding.riskScore,       // undefined if backend didn't compute
riskPct: holding.riskPct,
maxDrawdown: holding.maxDrawdown,
```

**4d. Add Risk Score column** after Volatility:
```typescript
{ key: "riskScore", label: "Risk Score", width: "w-28" }
```

**4e. Render** as a colored badge when `riskScore` is defined, or "—" when `undefined`/`null`:
- 0-25: "Low" (green badge)
- 26-50: "Medium" (blue badge)
- 51-75: "High" (amber badge)
- 76-100: "Very High" (red badge)

Show the numeric score alongside the label (e.g. "High 68").

**4f. Props interface** (`HoldingsViewProps` line ~216): Add optional risk fields to the holdings array shape:
```typescript
riskScore?: number;
riskPct?: number;
maxDrawdown?: number;
```

## Files Modified

| File | Change |
|------|--------|
| `services/portfolio_service.py` | Add `enrich_positions_with_risk()` method |
| `routes/positions.py` | Add risk enrichment call after existing enrichment |
| `frontend/packages/chassis/src/types/index.ts` | Add risk fields to `PositionsMonitorPosition` |
| `frontend/packages/connectors/src/adapters/PositionsAdapter.ts` | Add risk fields to `PositionsHolding` + normalizer |
| `frontend/packages/ui/src/components/portfolio/HoldingsView.tsx` | Add `riskScore` to Holding, add Risk Score column with colored badge |

## Key Facts

- `get_monitor_with_risk()` already exists at `portfolio_service.py` line ~697 — computes per-ticker `{beta, risk_pct, volatility, max_drawdown}` from `RiskAnalysisResult`
- `analyze_portfolio()` is expensive (~2-5s). Cache is instance-local and holdings route creates a new `PortfolioService()` per request, so there is no cross-request cache benefit. Latency is acceptable; can be optimized with a shared cache or lazy loading in a future iteration
- Frontend `Holding` interface already has `beta: number` (line 201) but it defaults to 1 — will now get a real value
- `riskScore` / `aiScore` never existed in the frontend — this is net-new

## Codex v1 Findings (Addressed in v2)

1. **Volatility units mismatch**: `enrich_positions_with_market_data()` stores vol as percentage points (50.0), `get_monitor_with_risk()` uses decimal (0.50). Scoring formula explicitly uses risk engine decimal values. Plan updated with unit note.
2. **`weight` not in position entries**: `to_monitor_view()` doesn't include weight. Compute from `gross_exposure / total_value` within the enrichment method.
3. **Route needs `PositionResult`**: `get_monitor_with_risk()` needs the `PositionResult` to build `PortfolioData`. Updated method signature to take `result` + `payload`.
4. **Frontend adapter explicitly maps**: New fields must be added to `PositionsHolding` interface and `normalizeHolding()`. Already in plan.

## Codex v2 Findings (Addressed in v3)

1. **Critical: Missing `user_id`/`portfolio_name`** — `ensure_factor_proxies()` at line ~767 requires these to resolve factor proxies. **Fix**: Updated method signature to `(self, result, payload, portfolio_name, user_id)`. Route handler passes both from authenticated user context.
2. **High: Unsafe weight denominator** — `total_value` is a signed net sum, so long/short portfolios can hit near-zero/negative values. **Fix**: Changed weight formula to `abs(gross_exposure) / sum(abs(gross_exposure))` which is always positive and well-defined.
3. **High: Missing null-handling** — Positions with no risk metrics would score 0 ("Low risk") instead of "N/A". **Fix**: If any of the 4 scoring inputs are `None`, set `risk_score = None`. Frontend renders `None` as "—" (em-dash), not a badge.
4. **Medium: Incomplete frontend mapping** — `HoldingsView.tsx` has two transformation blocks (useState at ~273 and useEffect at ~322) that need the new fields. Also `beta` uses `|| 1` which overwrites valid `0`. **Fix**: Added explicit field mapping instructions for both blocks, changed `|| 1` to `?? 1`, added fields to `HoldingsViewProps` shape.
5. **Medium: Cache is instance-local** — Holdings route creates `PortfolioService()` per request, so no cross-request cache sharing. **Fix**: Acknowledged in performance note. Latency is acceptable for holdings endpoint. Can be made lazy/async in future iteration.

## Verification

1. `cd frontend && pnpm exec tsc --noEmit -p packages/ui/tsconfig.json` passes
2. `cd frontend && pnpm exec eslint` on modified files passes
3. Holdings (⌘2) — Risk Score column visible with colored badges
4. DSU (28% weight, low vol) should have moderate-high score (concentration-driven)
5. IT (76% vol, -60% drawdown) should have high/very-high score
6. Backend: `curl localhost:5001/api/positions/holdings | jq '.positions[0] | {ticker, risk_score, beta, risk_pct}'`

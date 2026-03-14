# Wave 2.5: Holdings Enrichment Part 2

**Status**: COMPLETE — Commit `06e8759b`
**Parent doc**: `completed/FRONTEND_PHASE2_WORKING_DOC.md` → "Remaining Holdings Fields"
**Date**: 2026-03-03

## Context

The `/api/positions/holdings` endpoint returns ~9 fields per position. The frontend `HoldingsView.tsx` expects 20 fields — the gap is filled with hardcoded mock data (fake sparklines, fake risk scores, etc.). Wave 2.5 wires 4 real data fields and removes 2 undefined fields from the UI.

## Scope

| Item | Source | Effort |
|------|--------|--------|
| `dayChange` / `dayChangePercent` | FMP `quote` batch endpoint | Low |
| `trend` sparkline (30-day close prices) | FMP `historical_price_eod` | Medium |
| `volatility` (annualized, per-position) | Computed from same historical data | Free (reuses trend data) |
| `alerts` count (per-position) | `generate_position_flags()` | Low |
| Remove `aiScore` + `riskScore` from UI | No spec, undefined | Low |

---

## Step 1: Backend — `enrich_positions_with_market_data()` in `portfolio_service.py`

**File**: `services/portfolio_service.py` (add after `enrich_positions_with_sectors()` at line ~894)

New method following the exact `enrich_positions_with_sectors()` pattern:

1. Extract unique tickers from `payload["positions"]`, **skipping non-FMP tickers**: skip any ticker starting with `CUR:` (cash proxies) or containing `/` (futures like `ES/` or `NQ/`). These have no FMP data.
2. **Batch quote fetch** — single `client.fetch("quote", symbol="AAPL,MSFT,...", use_cache=False)`. Extract `change` and `changesPercentage` per symbol into `quote_map`. Wrap in try/except — empty `quote_map` on failure.
3. **Parallel historical fetch** — `ThreadPoolExecutor(max_workers=5)`, per-ticker `client.fetch("historical_price_eod", symbol=sym, from=45_days_ago, to=today, use_cache=True)`. Extract last 30 close prices for sparkline. Compute annualized volatility: `np.std(daily_returns) * sqrt(252) * 100`. Guard: skip if `len(closes) < 2` (can't compute returns).
4. **Apply** — for each position in payload, set `day_change`, `day_change_percent`, `trend`, `volatility`. All default to `None` on failure — positions with no FMP data simply get null fields.

**Performance notes**:
- `historical_price_eod` is cached (`HASH_ONLY`), so repeated calls for same date range are fast. Quote endpoint is uncached (real-time).
- `FMPClient()` rate limiter is per-instance (not process-wide), matching the existing `enrich_positions_with_sectors()` pattern which also creates a per-call instance. This is acceptable because historical calls are cached after the first request.
- For a 30-position portfolio: 1 batch quote call + ~30 historical calls across 5 workers = ~6 batches × ~100ms = ~600ms worst case (first load only; subsequent calls hit cache).

## Step 2: Backend — Alert count enrichment in `routes/positions.py`

**File**: `routes/positions.py` (modify `/holdings` endpoint, lines 107-116)

The endpoint already has access to `result` (the `PositionResult` object) before converting to payload. Run `generate_position_flags()` directly on `result.data.positions` + `result.total_value` (these use the `value` field that flags expect), then count flags per-ticker and inject into the payload positions.

```python
# After payload = portfolio_svc.enrich_positions_with_sectors(payload)
payload = portfolio_svc.enrich_positions_with_market_data(payload)

from core.position_flags import generate_position_flags
flags = generate_position_flags(
    positions=result.data.positions,
    total_value=result.total_value,
    cache_info={},
)
alert_counts = {}
for flag in flags:
    ticker = flag.get("ticker")
    if ticker:
        alert_counts[ticker] = alert_counts.get(ticker, 0) + 1
for position in payload.get("positions", []):
    sym = str(position.get("ticker", "")).strip().upper()
    position["alerts"] = alert_counts.get(sym, 0)
```

**Important**: `generate_position_flags` expects positions with `value` field (original positions from `result.data.positions`), NOT the monitor payload which uses `gross_exposure`. That's why we use `result.data.positions`, not `payload["positions"]`.

## Step 3: Frontend — Extend `PositionsMonitorPosition` type

**File**: `frontend/packages/chassis/src/types/index.ts` (line ~115, after `brokerage_name`)

Add 5 optional fields:
```typescript
day_change?: number | null;
day_change_percent?: number | null;
trend?: number[] | null;
volatility?: number | null;
alerts?: number | null;
```

## Step 4: Frontend — Extend `PositionsHolding` interface + `normalizeHolding()`

**File**: `frontend/packages/connectors/src/adapters/PositionsAdapter.ts`

Add to `PositionsHolding` interface (after `isProxy`):
```typescript
dayChange?: number;
dayChangePercent?: number;
trend?: number[];
volatility?: number;
alerts?: number;
```

Add to `normalizeHolding()` return object (after `isProxy: false`):
```typescript
dayChange: toOptionalNumber(position.day_change),
dayChangePercent: toOptionalNumber(position.day_change_percent),
trend: Array.isArray(position.trend) ? position.trend : undefined,
volatility: toOptionalNumber(position.volatility),
alerts: toOptionalNumber(position.alerts) ?? 0,
```

## Step 5: Frontend — Clean up `HoldingsView.tsx`

**File**: `frontend/packages/ui/src/components/portfolio/HoldingsView.tsx`

### 5a. Remove `aiScore` and `riskScore`
- Remove from `Holding` interface (lines 203, 209)
- Remove from `mockHoldings` entries (lines 229, 235, 253, 259, etc.)
- Remove from both data transform blocks (lines 441, 447 and 493, 499)
- Remove from `HoldingsViewProps` holdings array type (lines 382, 385)
- Remove `avgRisk` from `summaryMetrics` (line 554)
- Remove column definitions from table (line 769-770: `riskScore`, `aiScore`)
- Remove table cell rendering blocks for riskScore and aiScore (lines ~942-966)
- **Keep `Brain` import** — it is used for Technology sector icon mapping at line 623 (`getSectorIcon`)

### 5b. Delete `mockHoldings` array
- Delete the entire `mockHoldings` array (lines 213-358)
- Change fallback in `useState` initializer (line 453): `return mockHoldings` → `return []`

### 5c. Fix fallback defaults for real data
In both data transforms (lines 426-450 and 478-502):
- `volatility: holding.volatility || 15` → `holding.volatility ?? 0` (15% default is misleading)
- `trend: holding.trend || [50, 52, ...]` → `holding.trend || []` (empty = no sparkline, not fake data)
- Keep: `dayChange: holding.dayChange || 0` (zero is correct default)
- Keep: `alerts: holding.alerts || 0` (zero is correct default)

### 5d. Handle edge cases in rendering
- **Volatility**: Where rendered, show `"—"` when value is 0 or undefined instead of displaying "0.0%".
- **Sparkline**: `renderMiniSparkline()` already guards `trend.length`, but verify it handles empty array `[]` gracefully (should render nothing).
- **Summary dayChangePercent**: Guard divide-by-zero in `dayChangePercent = dayChange / totalValue * 100` when `totalValue === 0`.

## Files Modified (Summary)

| File | Change |
|------|--------|
| `services/portfolio_service.py` | Add `enrich_positions_with_market_data()` method |
| `routes/positions.py` | Wire market data + alert enrichments into `/holdings` |
| `frontend/packages/chassis/src/types/index.ts` | Extend `PositionsMonitorPosition` with 5 fields |
| `frontend/packages/connectors/src/adapters/PositionsAdapter.ts` | Extend `PositionsHolding` + `normalizeHolding()` |
| `frontend/packages/ui/src/components/portfolio/HoldingsView.tsx` | Remove aiScore/riskScore, delete mocks, wire real fields |

## Verification

1. **Backend**: `curl` or browser → `/api/positions/holdings` — verify each position has `day_change`, `day_change_percent`, `trend` (array of ~30 numbers), `volatility` (number), `alerts` (integer)
2. **Frontend build**: `cd frontend && pnpm typecheck && pnpm lint && pnpm build` — 0 errors
3. **Visual**: Load Holdings view in browser — sparklines show real price trends, day change shows real values, volatility shows real percentages, aiScore/riskScore columns gone
4. **Edge cases**: Positions with FMP lookup failure (e.g., CUR:XXX, futures) should show null/empty gracefully — no broken UI
5. **Existing tests**: `pytest tests/core/test_position_flags*.py` — still pass (no changes to flag logic)

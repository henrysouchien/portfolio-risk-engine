# B-017: Per-Position Alerts — Wire Real Flag Data into Holdings

**Status**: COMPLETE — commit `f3b15bd9`, verified in browser

## Context

The Holdings view (⌘2) shows a red alert badge per position, but `alerts` is always 0. The backend infrastructure (`core/position_flags.py`) already generates per-ticker flags, and the frontend already renders the badge when `alerts > 0`. The problem is that `generate_position_flags()` in the holdings route is called with incomplete params:

1. `cache_info={}` — stale_data/provider_error flags never fire
2. No `monitor_positions` — `large_unrealized_loss` can't fire (needs `pnl_percent`/`pnl_usd`)

Additionally, only 4 of ~17 flag types are ticker-scoped (have a `ticker` key). Portfolio-level flags are silently discarded.

## Ticker-Scoped Flags (the ones that populate `alerts`)

| Flag type | Trigger | Requires |
|-----------|---------|----------|
| `single_position_concentration` | Single-issuer > 15% of gross non-cash exposure | `positions`, `total_value` |
| `leveraged_concentration` | Leverage > 1.1x AND equity weight > 25% | `positions`, `total_value` |
| `large_fund_position` | ETF/fund > 30% of exposure | `positions`, `total_value` (falls back to `position["type"]` for classification) |
| `large_unrealized_loss` | Down > 20% AND P&L < -$5,000 | `monitor_positions` (needs `pnl_percent`, `pnl_usd`) |

## Changes

### 1. `routes/positions.py` — Pass complete params to `generate_position_flags()`

**File**: `routes/positions.py` (~lines 98-152)

After `to_monitor_view()` produces the enriched payload, pass the enriched positions back as `monitor_positions` so P&L-based flags can fire:

```python
# Current:
flags = generate_position_flags(
    positions=result.data.positions,
    total_value=result.total_value,
    cache_info={},
)

# Fixed:
flags = generate_position_flags(
    positions=result.data.positions,
    total_value=result.total_value,
    cache_info=getattr(result, '_cache_metadata', {}),
    monitor_positions=payload.get("positions", []),
)
```

This enables:
- `large_unrealized_loss` — from `monitor_positions` P&L fields (`pnl_percent`, `pnl_usd` match what `to_monitor_view()` outputs)
- `provider_error` — from real `cache_info` (sourced from `result._cache_metadata`)

**Note on `stale_data` flag**: `generate_position_flags()` checks `cache_info` for `age_hours` and `ttl_hours` keys, but `_cache_metadata` stores `cache_age_hours`. The key name mismatch means `stale_data` won't fire even with real `cache_info`. This is a pre-existing issue in `position_flags.py` — out of scope for this change, can be fixed separately.

**Params NOT passed** (and why):
- `by_sector` — not available in positions flow (computed during risk analysis). Only needed for portfolio-level sector flags, not per-ticker alerts.

### 2. `routes/positions.py` — Surface portfolio-level flag count

Portfolio-level flags (leverage, top5 concentration, cash drag, etc.) don't have a `ticker` key, so they're currently discarded. Add them to the response as a separate `portfolio_alerts` field:

```python
portfolio_alert_count = len([f for f in flags if not f.get("ticker")])

payload["portfolio_alerts"] = portfolio_alert_count
payload["portfolio_alert_details"] = [
    {"type": f["type"], "severity": f["severity"], "message": f["message"]}
    for f in flags if not f.get("ticker")
]
```

### 3. Frontend — Already wired, no changes needed

- `PositionsAdapter` reads `position.alerts` ✓
- `HoldingsView` renders red badge when `alerts > 0` ✓
- `totalAlerts` sums across all holdings ✓
- Types already have `alerts?: number | null` ✓

## Files Modified

| File | Change |
|------|--------|
| `routes/positions.py` | Pass `monitor_positions`, `cache_info` to `generate_position_flags()`. Add `portfolio_alerts` to response. |

## What Does NOT Change

- `core/position_flags.py` — no changes, flag generation logic is already correct
- `core/result_objects/positions.py` — no changes
- Frontend — no changes needed (already renders alerts badge)

## Codex v1 Findings (Addressed)

1. **`cache_info` not on `result.data`**: It's on `result._cache_metadata` (from `position_service.py` line 356). Plan updated.
2. **`security_types` not on `PositionsData`**: Removed from params entirely. `generate_position_flags()` falls back to `position["type"]` when absent.
3. **`monitor_positions` format compatible**: `to_monitor_view()` outputs `pnl_percent`/`pnl_usd` which match what `generate_position_flags()` expects.
4. **`portfolio_alerts` safely ignored by frontend**: Adapter reads known keys and ignores extras.
5. **`stale_data` key mismatch**: `_cache_metadata` uses `cache_age_hours`, but `generate_position_flags()` checks `age_hours`/`ttl_hours`. Pre-existing issue, out of scope.

## Verification

1. Backend: `curl localhost:5001/api/positions/holdings | jq '.positions[] | {ticker, alerts}'` — positions with concentration > 15% should have alerts > 0
2. Frontend: Holdings (⌘2) — red badges should appear on concentrated positions (e.g. DSU at 27.9%)
3. Check `portfolio_alerts` field in response — should show count of portfolio-level flags

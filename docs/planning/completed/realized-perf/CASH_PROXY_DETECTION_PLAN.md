# Plan: Cash Proxy Detection (`is_proxy` field)

## Context

Holdings view has an `isProxy` boolean on every position, but it's hardcoded to `false` in `PositionsAdapter.ts:86`. Cash positions like `CUR:USD` get mapped to proxy ETFs (e.g., `SGOV`) for risk analysis via `cash_map.yaml`. Users should be able to see which positions in their holdings are cash proxies vs real holdings — currently they can't tell.

**Key challenge:** We can't just check if a ticker matches a proxy ETF (e.g., SGOV), because the user might actually hold SGOV as a real investment. The `is_cash_equivalent` flag from providers (Plaid/SnapTrade) already exists on raw position dicts and survives consolidation in `PositionService`, but is not emitted in `_build_monitor_payload()` and not guaranteed present on cached DB rows.

## Approach

Thread `is_cash_equivalent` from raw position dicts through the monitor payload in `core/result_objects/positions.py`. Add cache column guard. Add public proxy ticker accessor. Add belt-and-suspenders enrichment in the route handler. Update frontend types and adapter.

## Steps

### 1. Backend: Ensure `is_cash_equivalent` survives DB cache path

**File:** `services/position_service.py` — `_ensure_cached_columns()` (~line 940)

Add before the `return df`:

```python
if "is_cash_equivalent" not in df.columns:
    df["is_cash_equivalent"] = None
```

This ensures cached position rows have the column even if they predate the field.

### 2. Backend: Emit `is_cash_equivalent` in monitor payload

**File:** `core/result_objects/positions.py` — `_build_monitor_payload()` (line ~438)

Add to the `entry` dict (preserve tri-state — do NOT cast to bool here):

```python
entry = {
    "ticker": position.get("ticker"),
    # ... existing fields ...
    "entry_price_warning": entry_price_warning,
    "is_cash_equivalent": position.get("is_cash_equivalent"),  # tri-state: True/False/None
}
```

This flows to both REST API (`routes/positions.py` → `result.to_monitor_view()`) and MCP (`mcp_tools/positions.py` `format="monitor"` → `result.to_monitor_view()`).

### 3. Backend: Add public accessor for proxy ticker set

**File:** `portfolio_risk_engine/data_objects.py`

Add after `_load_cash_proxy_map()`:

```python
def get_cash_proxy_tickers() -> set:
    """Return the set of proxy ETF tickers (e.g., {'SGOV', 'IBGE.L', 'ERNS.L'})."""
    proxy_by_currency, _ = _load_cash_proxy_map()
    return {v.upper() for v in proxy_by_currency.values()}
```

### 4. Backend: Belt-and-suspenders enrichment in route handler

**File:** `routes/positions.py` — `get_position_holdings()` (after alerts enrichment, ~line 195)

For positions where no provider positively confirmed `is_cash_equivalent`, fall back to ticker matching:

```python
from portfolio_risk_engine.data_objects import get_cash_proxy_tickers

proxy_tickers = get_cash_proxy_tickers()
for position in payload.get("positions", []):
    if not position.get("is_cash_equivalent"):
        sym = str(position.get("ticker", "")).strip().upper()
        position["is_cash_equivalent"] = sym in proxy_tickers
```

Note: the check is `not position.get(...)` which catches both `None` and `False`. This is intentional because consolidation's `any(v is True for v in x)` aggregation collapses all-`None` groups to `False`. Positions where a provider explicitly set `True` are already correct and skip this block.

### 5. Frontend: Update chassis type

**File:** `frontend/packages/chassis/src/types/index.ts` — `PositionsMonitorPosition` interface (~line 90)

Add:

```typescript
is_cash_equivalent?: boolean | null;
```

### 6. Frontend: Wire in PositionsAdapter

**File:** `frontend/packages/connectors/src/adapters/PositionsAdapter.ts` — line 86

Change:
```typescript
isProxy: false,
```
To:
```typescript
isProxy: position.is_cash_equivalent === true,
```

### 7. Frontend: Add visual indicator in HoldingsView

**File:** `frontend/packages/ui/src/components/portfolio/HoldingsView.tsx`

Where position name/ticker is rendered, add a subtle badge when `isProxy` is true:
- Show "Cash Proxy" as a muted badge/chip next to the ticker name
- Use `text-muted-foreground` styling — informational, not a warning

## Files Modified

1. `services/position_service.py` — `_ensure_cached_columns()`: add `is_cash_equivalent` column guard (~2 lines)
2. `core/result_objects/positions.py` — `_build_monitor_payload()`: emit `is_cash_equivalent` in entry dict (~1 line)
3. `portfolio_risk_engine/data_objects.py` — add `get_cash_proxy_tickers()` public accessor (~4 lines)
4. `routes/positions.py` — belt-and-suspenders proxy enrichment after alerts (~5 lines)
5. `frontend/packages/chassis/src/types/index.ts` — add `is_cash_equivalent` to `PositionsMonitorPosition` (~1 line)
6. `frontend/packages/connectors/src/adapters/PositionsAdapter.ts` — line 86 (1 line change)
7. `frontend/packages/ui/src/components/portfolio/HoldingsView.tsx` — add badge rendering

## Edge Cases

- **User actually holds SGOV:** Provider-level `is_cash_equivalent=True` only fires for Plaid/SnapTrade cash-flagged positions. For positions without the flag, ticker fallback applies — SGOV is a T-bill ETF that is functionally cash-like even when held directly, so tagging it as a proxy is an acceptable approximation. Users who intentionally hold SGOV as an investment (vs cash parking) see "Cash Proxy" badge, which is still accurate in spirit.
- **Consolidation collapses tri-state:** `PositionService` consolidation uses `any(v is True for v in x)` which turns all-`None` groups to `False`. The route handler's `not position.get("is_cash_equivalent")` catches this by applying ticker fallback to both `None` and `False`. Only explicit `True` from providers skips the fallback.
- **Cached positions:** `_ensure_cached_columns()` guarantees the column exists even for old DB rows (defaults to `None`).
- **MCP parity:** Both REST and MCP use `_build_monitor_payload()`, so `is_cash_equivalent` appears in both.

## Verification

1. `python -m pytest tests/ -k position` — existing position tests pass
2. `python -m pytest tests/unit/test_positions_data.py` — add test: position with `is_cash_equivalent=True` emits it in monitor output
3. Start backend + frontend, open Holdings view
4. Cash proxy positions (SGOV from cash mapping) show "Cash Proxy" badge
5. Non-proxy positions show no badge
6. `pnpm typecheck` and `pnpm lint` pass
7. MCP: `get_positions(format="monitor")` returns `is_cash_equivalent` on positions

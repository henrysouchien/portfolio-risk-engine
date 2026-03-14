# Futures Phase 3: Portfolio Integration (Notional Display)

## Scope

Display-only integration of futures notional exposure into the positions view. No changes to the risk/returns pipeline — those are Phase 4.

**What this phase does:**
- Show futures notional exposure (quantity × multiplier × price) alongside margin value
- Break down futures exposure by asset class (equity_index, metals, energy, fixed_income)
- Add futures-specific fields to position dicts
- Surface futures exposure in the `get_positions(format="agent")` response

**What this phase does NOT do:**
- Change portfolio weights in `standardize_portfolio_input()` (stays margin-based)
- Modify how futures flow through `get_returns_dataframe()` or `build_portfolio_view()`
- Add macro factor risk decomposition (Phase 4)
- Change `total_value` calculation (stays margin-based — correct for portfolio NAV)

## Current State

Futures positions currently appear as:
```
ES: value=$13,750 (2 contracts × $6,875 price)
```

But the true economic exposure is:
```
ES: margin_value=$13,750, notional=$687,500 (2 × 50 × $6,875)
```

The contract specs (multiplier, tick_size, currency, asset_class) exist in `brokerage/futures/contracts.yaml` and are loadable via `get_contract_spec()`. They're just not threaded into the positions view.

## Architecture: Enrichment Strategy

Position dicts flow through multiple paths before reaching consumers:
1. **Fresh fetch**: Provider API → DataFrame → `_consolidate_cross_provider()` → `PositionResult.from_dataframe()` → position dicts
2. **Cached load**: DB read → DataFrame → `_ensure_cached_columns()` → `PositionResult.from_dataframe()` → position dicts
3. **Price refresh**: `refresh_portfolio_prices()` takes `List[Dict]` directly, builds new dicts

Since futures notional fields (`notional`, `multiplier`, `asset_class`) are **computed from in-memory contract specs** (fast — YAML cached via `lru_cache`), we **do NOT persist them to the DB**. Instead, we **recompute on every materialization** via a shared enrichment function. This avoids DB schema changes and ensures enrichment is always current.

**Shared enrichment function**: A standalone `enrich_futures_positions(positions: list[dict])` function that:
1. Loads `known_futures` from `ibkr.compat.get_ibkr_futures_exchanges()`
2. For each position whose uppercase ticker is in `known_futures`, looks up `get_contract_spec()`
3. Adds `notional`, `multiplier`, `asset_class`, `tick_size`, `tick_value` fields
4. Uses `_to_float()` for safe numeric conversion (matches existing codebase pattern)

This function is called from **four sites** — every place `PositionResult.from_dataframe()` is used, plus the price refresh path:
- After `PositionResult.from_dataframe()` in `get_all_positions()` (line 325) — multi-provider consolidated path
- After `PositionResult.from_dataframe()` in `get_positions()` (line 199) — single-provider path
- After `PositionResult.from_dataframe()` in `get_cached_positions()` (line 245) — cached-only path
- Inside `refresh_portfolio_prices()` in `PortfolioService` — price refresh path

## Changes

### 1. Shared Enrichment Function — `services/position_enrichment.py` (new file)

Create a small module with the shared enrichment logic:

```python
"""Futures notional enrichment for position dicts."""

from __future__ import annotations

import math
from typing import Any


def _to_float(value: Any, default: float = 0.0) -> float:
    """Convert value to finite float, otherwise return default."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(numeric):
        return default
    return numeric


def enrich_futures_positions(positions: list[dict]) -> None:
    """
    Enrich position dicts in-place with futures notional/contract metadata.

    Detects futures via ticker membership in the known_futures dict (from
    ibkr.compat, key membership) combined with type == "derivative" guard. This matches
    the existing detection pattern used in refresh_portfolio_prices()
    (portfolio_service.py:899) and to_portfolio_data()
    (data_objects.py:623).

    Fields added to futures positions:
    - notional: quantity × multiplier × price (economic exposure)
    - multiplier: contract multiplier from spec
    - asset_class: equity_index, metals, energy, fixed_income
    - tick_size: minimum price increment
    - tick_value: dollar value of one tick move (tick_size × multiplier)

    No-op for non-futures positions. Safe to call on any position list.
    """
    try:
        from ibkr.compat import get_ibkr_futures_exchanges
        from brokerage.futures import get_contract_spec
        known_futures = get_ibkr_futures_exchanges()
    except Exception:
        return

    for position in positions:
        ticker = str(position.get("ticker") or "").strip().upper()
        normalized_type = str(position.get("type") or "").strip().lower()
        # Match existing detection pattern: derivative type + known_futures membership
        if normalized_type != "derivative" or ticker not in known_futures:
            continue

        spec = get_contract_spec(ticker)
        if spec is None:
            continue

        quantity = _to_float(position.get("quantity", 0))
        price = _to_float(position.get("price", 0))

        position["notional"] = round(spec.notional(quantity, price), 2) if price > 0 else None
        position["multiplier"] = spec.multiplier
        position["asset_class"] = spec.asset_class
        position["tick_size"] = spec.tick_size
        position["tick_value"] = spec.tick_value
```

**Why derivative + known_futures detection**: This matches the existing pattern in both `refresh_portfolio_prices()` (line 899 in `services/portfolio_service.py`) and `to_portfolio_data()` (line 623 in `portfolio_risk_engine/data_objects.py`). The type guard (`"derivative"`) prevents false positives from equity tickers that collide with futures roots (e.g., "Z" is both Zillow and FTSE futures). The `known_futures` dict from `ibkr.compat.get_ibkr_futures_exchanges()` (returns `dict[str, dict]`; we use key membership) is the canonical source of which tickers are futures contracts.

### 2. Enrich After PositionResult Creation — `services/position_service.py`

**Where:** After every `PositionResult.from_dataframe()` call — there are **three** call sites:

1. `get_all_positions()` (~line 325) — multi-provider consolidated path
2. `get_positions()` (~line 199) — single-provider path (used by Plaid/SnapTrade routes)
3. `get_cached_positions()` (~line 245) — cached-only path (used by Plaid/SnapTrade routes)

At each site, after the `PositionResult.from_dataframe()` call and before `return result`:

```python
from services.position_enrichment import enrich_futures_positions
enrich_futures_positions(result.data.positions)
```

This covers fresh-fetch, cached-load, and single-provider paths. No DB schema changes needed — enrichment is recomputed from in-memory contract specs on every call.

### 3. Enrich in Price Refresh — `services/portfolio_service.py`

**Where:** `refresh_portfolio_prices()` (~line 872)

This function builds position dicts directly (not via DataFrame). The `instrument_types` dict is already built at lines 890-902 using the derivative + known_futures intersection.

The `refresh_portfolio_prices()` path builds position dicts directly (not via DataFrame), so we call `enrich_futures_positions()` on the final `updated_holdings` list after the loop completes.

```python
# After the for-loop that builds updated_holdings (after line 951):
from services.position_enrichment import enrich_futures_positions
enrich_futures_positions(updated_holdings)
```

This reuses the same shared helper as Section 2. The enrichment function handles detection (derivative type + known_futures), contract spec lookup, and notional calculation internally.

Note: The position dicts built in this loop use `holding.get("type")` (line 910) for the `type` field, which preserves the provider's original type. For futures positions, this will be `"derivative"` (matching the type guard). The `price` field is not set in the loop's dicts — it uses `market_value` instead. The enrichment function uses `position.get("price", 0)` which will be 0 here. To make the shared function work, we need to also include `price` in the appended dict:

```python
# In the non-cash branch dict (line 942-949), add price field:
updated_holdings.append({
    "ticker": ticker,
    "shares": shares,
    "market_value": market_value,
    "security_name": holding.get("security_name", ""),
    "type": position_type,
    "fmp_ticker": fmp_ticker,
    "price": market_value / shares if shares else 0,  # NEW: needed for notional calc
    "quantity": shares,  # NEW: alias for enrichment function
})
```

Note: `market_value` (shares × price) stays as-is — it reflects margin value. The `notional` field is additive (new information, not a correction).

### 4. Add Futures Exposure to `get_exposure_snapshot()` — `core/result_objects/positions.py`

**Where:** `get_exposure_snapshot()` (~line 647)

Add a `futures_exposure` section to the returned dict. After the existing position loop (which ends at line 689), aggregate futures data using safe conversion:

```python
# After the existing position loop, before the return dict:
futures_positions = [
    p for p in positions
    if p.get("notional") is not None
]

futures_exposure = None
if futures_positions:
    total_notional = sum(
        self._safe_float(p.get("notional", 0)) or 0 for p in futures_positions
    )
    total_margin = sum(
        abs(self._safe_float(p.get("value", 0)) or 0) for p in futures_positions
    )

    by_asset_class: Dict[str, float] = {}
    for p in futures_positions:
        ac = p.get("asset_class", "unknown")
        by_asset_class[ac] = by_asset_class.get(ac, 0.0) + (self._safe_float(p.get("notional", 0)) or 0)

    futures_exposure = {
        "contract_count": len(futures_positions),
        "total_notional": round(total_notional, 2),
        "total_margin": round(total_margin, 2),
        "notional_to_margin": round(total_notional / total_margin, 1) if total_margin > 0 else None,
        "by_asset_class": {
            ac: round(val, 2) for ac, val in sorted(by_asset_class.items(), key=lambda x: -x[1])
        },
    }
```

Add `"futures_exposure": futures_exposure` to the returned dict (None when no futures).

Note: Use `self._safe_float()` — a `@staticmethod` on `PositionResult` (line 294 in `positions.py`). Existing code calls it as `self._safe_float(...)` (see line 346). Returns `Optional[float]` (None for non-numeric/non-finite), so use `or 0` for arithmetic. Do NOT use bare `float()` casts.

### 5. Add Futures Flag — `core/position_flags.py`

**Where:** `generate_position_flags()` — after the existing leverage flags section (~line 116)

Add a single informational flag when futures notional is significant relative to portfolio:

```python
# After the existing leverage flags section (after line 116):
futures_notional = sum(
    _to_float(p.get("notional", 0))
    for p in all_positions
    if p.get("notional") is not None
)
if futures_notional > 0 and portfolio_total > 0:
    notional_ratio = futures_notional / portfolio_total
    if notional_ratio > 2.0:
        flags.append({
            "type": "futures_high_notional",
            "severity": "warning",
            "message": f"Futures notional ${futures_notional:,.0f} is {notional_ratio:.1f}x portfolio value",
            "notional": round(futures_notional, 2),
            "ratio": round(notional_ratio, 1),
        })
    elif notional_ratio > 0.5:
        flags.append({
            "type": "futures_notional",
            "severity": "info",
            "message": f"Futures notional exposure: ${futures_notional:,.0f} ({notional_ratio:.1f}x portfolio)",
            "notional": round(futures_notional, 2),
            "ratio": round(notional_ratio, 1),
        })
```

Note: `_to_float()` already exists in `position_flags.py` (line 9-17) with the same safe conversion pattern.

### 6. Surface in Agent Response — `mcp_tools/positions.py`

**Where:** `_build_agent_response()` (~line 73)

The `futures_exposure` section is already in the snapshot from step 4. The snapshot dict from `get_exposure_snapshot()` is spread into the response. `futures_exposure` will be included automatically. No additional code needed.

Verify: the snapshot dict is included in the response at line 91. `futures_exposure` key will appear (as `None` when no futures, as a dict when futures exist).

## Files Changed

| File | Change | Section |
|------|--------|---------|
| `services/position_enrichment.py` (new) | Shared `enrich_futures_positions()` function — ticker-based detection + contract spec lookup | 1 |
| `services/position_service.py` | Call `enrich_futures_positions()` after `PositionResult.from_dataframe()` | 2 |
| `services/portfolio_service.py` | Enrich futures positions in `refresh_portfolio_prices()` non-cash branch | 3 |
| `core/result_objects/positions.py` | Add `futures_exposure` to `get_exposure_snapshot()` return dict | 4 |
| `core/position_flags.py` | Add `futures_notional` / `futures_high_notional` flags after leverage section | 5 |
| `mcp_tools/positions.py` | No change needed (inherits from snapshot) | 6 |

**Not changed:**
- `inputs/database_client.py` — No DB schema changes. Futures enrichment is recomputed on every call from in-memory contract specs.
- `portfolio_risk_engine/data_objects.py` — No changes to `PositionsData.from_dataframe()` or `to_portfolio_data()`.

## Tests

### New tests:

1. **`enrich_futures_positions()`** — Unit tests for the shared enrichment function:
   - ES with type="derivative", 2 contracts at $6,875 → notional = $687,500, multiplier = 50, asset_class = "equity_index"
   - GC with type="derivative", 1 contract at $2,000 → notional = $200,000, multiplier = 100, asset_class = "metals"
   - Non-futures position (AAPL, type="equity") → no notional/multiplier/asset_class fields added
   - Futures ticker with wrong type (type="equity") → no enrichment (type guard)
   - Position with zero price → notional is None (not 0)
   - Position with missing quantity → notional computed with quantity = 0
   - Unknown ticker not in known_futures → no enrichment
   - Empty position list → no-op

2. **Price refresh enrichment** — Verify `refresh_portfolio_prices()` returns enriched dicts:
   - Futures holding gets notional/multiplier/asset_class in output dict
   - Non-futures holding has no notional field
   - `market_value` unchanged (still margin-based: shares × price)

3. **Exposure snapshot** — Verify `futures_exposure` section in `get_exposure_snapshot()`:
   - Portfolio with 0 futures → `futures_exposure` is None
   - Portfolio with ES + GC → `futures_exposure` has correct totals and by_asset_class breakdown
   - `notional_to_margin` ratio calculated correctly
   - `by_asset_class` sorted by descending value
   - Non-numeric notional values handled gracefully (via `_safe_float`)

4. **Position flags** — Verify futures flags trigger correctly:
   - Futures notional > 2x portfolio → `futures_high_notional` warning
   - Futures notional 0.5-2x portfolio → `futures_notional` info
   - Futures notional < 0.5x portfolio → no flag
   - No futures → no flag
   - Uses `_to_float()` for safe conversion (non-numeric notional → 0)

5. **Existing tests** — Must still pass. The new fields are additive — no existing fields change.

## Design Decisions

1. **`notional` is a new additive field** — Existing `value` field unchanged (stays margin/broker-reported). `notional` is extra information.
2. **`total_value` unchanged** — Portfolio total stays margin-based. Notional is an overlay, not added to total. This matches the design doc: "Total Portfolio Value = equities at market + futures at margin."
3. **Detection uses derivative type + known_futures intersection** — Matches the existing pattern in `to_portfolio_data()` and `refresh_portfolio_prices()`. The type guard prevents false positives from equity/futures ticker collisions (e.g., "Z"). The `known_futures` dict from `ibkr.compat.get_ibkr_futures_exchanges()` (key membership) is the canonical source of truth for futures tickers.
4. **Downstream detection uses `notional` field presence** — Rather than re-detecting futures in every consumer, we enrich once upstream. Downstream code checks `if p.get("notional") is not None`.
5. **No DB persistence** — Futures enrichment fields are computed from in-memory contract specs (YAML via `lru_cache`). Recomputing on every call is cheap and avoids DB schema migration. If contract specs change, enrichment is automatically current.
6. **Shared enrichment function** — Single `enrich_futures_positions()` called from two sites (PositionService after result creation, PortfolioService in price refresh). Avoids code duplication.
7. **Asset class from contract spec** — Uses `FuturesContractSpec.asset_class` (equity_index, fixed_income, metals, energy). Provides grouping without building a full risk model.
8. **Safe numeric conversion** — Uses `_to_float()` (position_flags.py) and `_safe_float()` (positions.py) matching existing codebase patterns. No bare `float()` casts.
9. **Flag thresholds** — 0.5x for info, 2x for warning. These are starting points — can adjust based on experience.

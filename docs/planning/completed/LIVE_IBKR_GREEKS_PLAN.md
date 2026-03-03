# Live IBKR Greeks for Portfolio Options

**Date**: 2026-03-02
**Status**: COMPLETE (implemented in commit `61548e66`)

## Context

Portfolio Greeks are currently computed locally via Black-Scholes in `options/portfolio_greeks.py`. IBKR already provides server-side model Greeks via `fetch_snapshot()` with generic ticks 100/101/106 — this is used in `analyze_option_chain` but never wired into portfolio-level Greeks aggregation. The result: `get_positions` always reports `source: "computed"` Greeks even when IBKR Gateway is running and could provide more accurate real-time values.

The fix: add an IBKR Greeks fetch path to `compute_portfolio_greeks()` that tries live Greeks first, falls back to Black-Scholes per position when IBKR is unavailable or market is closed.

## Key Unit Difference

- **IBKR vega**: per 0.01 IV change (1 basis point)
- **Black-Scholes vega**: per 0.01 IV change (1%)
- **These are the same convention** — both are "per 1% move in IV". The `greeks.py` implementation uses `* 0.01` explicitly (line ~170: `S * pdf_d1 * sqrt(T) * 0.01`), making vega "per 1 percentage point of IV". IBKR `modelGreeks.vega` is also per 1% IV. **No scaling needed.**
- **IBKR theta**: daily (already divided by 365). Matches Black-Scholes convention in `greeks.py`.
- **IBKR delta/gamma**: same convention as Black-Scholes (bare delta, per-point gamma).

## Implementation

### 1. New function `_fetch_ibkr_greeks()` in `options/portfolio_greeks.py`

Batch-fetches live Greeks for all option positions from IBKR in a single `fetch_snapshot()` call. Returns a dict mapping position index → per-contract Greeks (delta, gamma, theta, vega, implied_vol), or `None` if IBKR is unavailable.

```python
def _fetch_ibkr_greeks(
    option_positions: list[dict[str, Any]],
) -> dict[int, dict[str, float]] | None:
    """Try to fetch live Greeks from IBKR for all option positions.

    Returns {position_index: {delta, gamma, theta, vega, implied_vol}} or None
    if IBKR is unavailable or no data returned.
    """
    try:
        from ib_async import Option as IBOption
        from ibkr.market_data import IBKRMarketDataClient
    except ImportError:
        return None

    contracts = []
    index_map = []  # maps contract list index → position index

    for idx, pos in enumerate(option_positions):
        underlying = str(pos.get("underlying") or "").strip().upper()
        strike = _to_float(pos.get("strike"))
        option_type = str(pos.get("option_type") or "").strip().lower()
        expiry_str = _format_expiry_for_ibkr(pos)  # "YYYYMMDD"

        if not underlying or strike is None or not expiry_str or option_type not in {"call", "put"}:
            continue

        right = "C" if option_type == "call" else "P"
        contracts.append(IBOption(underlying, expiry_str, strike, right, "SMART"))
        index_map.append(idx)

    if not contracts:
        return None

    try:
        client = IBKRMarketDataClient()
        snapshots = client.fetch_snapshot(contracts=contracts)
    except Exception:
        _LOGGER.debug("IBKR Greeks fetch failed, falling back to Black-Scholes")
        return None

    result = {}
    for snap_idx, snapshot in enumerate(snapshots):
        if isinstance(snapshot, dict) and "error" not in snapshot:
            delta = snapshot.get("delta")
            if delta is not None:  # Greeks present
                result[index_map[snap_idx]] = {
                    "delta": delta,
                    "gamma": snapshot.get("gamma"),
                    "theta": snapshot.get("theta"),
                    "vega": snapshot.get("vega"),
                    "implied_vol": snapshot.get("implied_vol"),
                }

    return result if result else None
```

Helper to format expiry for IB contract:
```python
def _format_expiry_for_ibkr(pos: dict[str, Any]) -> str | None:
    """Convert position expiry to YYYYMMDD for IB Option contract."""
    expiry_dt = _parse_expiry(pos.get("expiry"))
    if expiry_dt is None:
        return None
    return expiry_dt.strftime("%Y%m%d")
```

### 2. Update `compute_portfolio_greeks()` to use IBKR Greeks

Add `use_ibkr: bool = True` parameter. When True, attempt batch IBKR fetch first. For each position, use IBKR Greeks if available, otherwise fall back to Black-Scholes.

```python
def compute_portfolio_greeks(
    positions: list[dict],
    risk_free_rate: float | None = None,
    use_ibkr: bool = True,
) -> PortfolioGreeksSummary:
    """Aggregate dollar Greeks across parsed option positions.

    When use_ibkr=True (default), attempts to fetch live Greeks from IBKR
    for all positions in a single batch call. Falls back to Black-Scholes
    per position when IBKR data is unavailable.
    """
    summary = PortfolioGreeksSummary()
    resolved_risk_free_rate = _resolve_risk_free_rate(risk_free_rate)

    # Filter to valid option positions
    option_positions = [
        p for p in (positions or [])
        if bool(p.get("is_option")) and not bool(p.get("option_parse_failed"))
    ]

    if not option_positions:
        return summary

    # Try batch IBKR fetch
    ibkr_greeks: dict[int, dict[str, float]] | None = None
    if use_ibkr:
        try:
            ibkr_greeks = _fetch_ibkr_greeks(option_positions)
        except Exception:
            ibkr_greeks = None

    ibkr_count = 0
    local_count = 0

    for idx, position in enumerate(option_positions):
        try:
            live = ibkr_greeks.get(idx) if ibkr_greeks else None
            if live and live.get("delta") is not None:
                underlying, delta, gamma, theta, vega = _position_dollar_greeks_from_ibkr(
                    position, live
                )
                ibkr_count += 1
            else:
                underlying, delta, gamma, theta, vega = _position_dollar_greeks(
                    position, resolved_risk_free_rate
                )
                local_count += 1
        except Exception:
            summary.failed_count += 1
            continue

        summary.total_delta += delta
        summary.total_gamma += gamma
        summary.total_theta += theta
        summary.total_vega += vega
        summary.position_count += 1

        bucket = summary.by_underlying.setdefault(
            underlying,
            {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "position_count": 0},
        )
        bucket["delta"] = float(bucket["delta"]) + delta
        bucket["gamma"] = float(bucket["gamma"]) + gamma
        bucket["theta"] = float(bucket["theta"]) + theta
        bucket["vega"] = float(bucket["vega"]) + vega
        bucket["position_count"] = int(bucket["position_count"]) + 1

    # Set source based on what we actually used
    if ibkr_count > 0 and local_count == 0:
        summary.source = "ibkr"
    elif ibkr_count > 0 and local_count > 0:
        summary.source = "mixed"
    else:
        summary.source = "computed"

    return summary
```

### 3. New function `_position_dollar_greeks_from_ibkr()`

Scales raw IBKR per-contract Greeks to dollar Greeks using the same convention as `_position_dollar_greeks()`.

```python
def _position_dollar_greeks_from_ibkr(
    position: dict[str, Any],
    ibkr_greeks: dict[str, float | None],
) -> tuple[str, float, float, float, float]:
    """Scale IBKR per-contract Greeks to dollar Greeks."""
    underlying = str(position.get("underlying") or "").strip().upper()
    if not underlying:
        raise ValueError("position missing underlying")

    quantity = _to_float(position.get("quantity"), default=0.0) or 0.0
    multiplier = _to_float(position.get("multiplier"), default=_DEFAULT_OPTION_MULTIPLIER)
    if multiplier is None or multiplier <= 0:
        multiplier = _DEFAULT_OPTION_MULTIPLIER

    # Resolve underlying price for dollar-delta scaling
    dte_val = _to_float(position.get("days_to_expiry"))
    if dte_val is None:
        expiry_dt = _parse_expiry(position.get("expiry"))
        dte = (expiry_dt - date.today()).days if expiry_dt else 30
    else:
        dte = int(dte_val)
    underlying_price = _resolve_underlying_price(position, underlying, max(dte, 1))

    raw_delta = ibkr_greeks.get("delta") or 0.0
    raw_gamma = ibkr_greeks.get("gamma") or 0.0
    raw_theta = ibkr_greeks.get("theta") or 0.0
    raw_vega = ibkr_greeks.get("vega") or 0.0

    # Same dollar scaling as _position_dollar_greeks
    delta = raw_delta * quantity * multiplier * underlying_price
    gamma = raw_gamma * quantity * multiplier
    theta = raw_theta * quantity * multiplier
    vega = raw_vega * quantity * multiplier

    return underlying, delta, gamma, theta, vega
```

### 4. No changes needed downstream

- `get_exposure_snapshot()` in `core/result_objects/positions.py` (line 784-788) already calls `compute_portfolio_greeks(option_positions).to_dict()` and includes the `source` field. The `source` will now be `"ibkr"`, `"mixed"`, or `"computed"` based on what happened.
- `generate_option_portfolio_flags()` reads from the same snapshot dict — no changes needed.
- `PortfolioGreeksSummary.to_dict()` already serializes `source` — no changes needed.

### 5. Tests

**`tests/options/test_portfolio_greeks.py`** — update existing + add new tests:

**Update existing 4 tests**: All existing tests (`test_compute_portfolio_greeks_aggregates_dollar_greeks`, `test_compute_portfolio_greeks_handles_no_options`, `test_compute_portfolio_greeks_handles_expired_and_unparseable_positions`, `test_compute_portfolio_greeks_uses_latest_price_for_short_positions`) must pass `use_ibkr=False` to avoid attempting real IBKR connections. Since `ib_async` is installed in this environment, leaving `use_ibkr=True` would cause `_fetch_ibkr_greeks` to try connecting to IBKR Gateway, leading to timeouts or connection errors in CI.

**New tests:**

1. **IBKR Greeks used when available**: Mock `_fetch_ibkr_greeks` to return Greeks for all positions. Assert `source == "ibkr"` and dollar Greeks match expected scaling.

2. **Mixed source — IBKR + Black-Scholes fallback**: Mock `_fetch_ibkr_greeks` to return Greeks for only some positions. Assert `source == "mixed"`.

3. **IBKR unavailable — full Black-Scholes fallback**: Mock `_fetch_ibkr_greeks` to return `None`. Assert `source == "computed"` and Greeks computed normally.

4. **use_ibkr=False skips IBKR**: Pass `use_ibkr=False`. Assert `_fetch_ibkr_greeks` not called, `source == "computed"`.

5. **IBKR fetch exception is caught**: Mock `_fetch_ibkr_greeks` to raise. Assert graceful fallback to Black-Scholes.

6. **Dollar scaling from IBKR**: Verify that raw IBKR delta/gamma/theta/vega are scaled correctly (delta × qty × mult × underlying_price, others × qty × mult).

## Files Modified

| File | Change |
|------|--------|
| `options/portfolio_greeks.py` | Add `_format_expiry_for_ibkr()`, `_fetch_ibkr_greeks()`, `_position_dollar_greeks_from_ibkr()`. Update `compute_portfolio_greeks()` with `use_ibkr` param and IBKR-first logic. ~80 new lines. |
| `tests/options/test_portfolio_greeks.py` | 6 new tests |

## Notes

- **Single batch call**: All option positions are fetched in one `fetch_snapshot()` call. This minimizes IBKR connections (ephemeral mode — connect once, get all Greeks, disconnect).
- **Market hours**: IBKR returns `modelGreeks = None` when market is closed. The 15s option timeout will elapse, snapshots will have no Greeks, and all positions fall back to Black-Scholes. No special handling needed.
- **Thread safety**: `IBKRMarketDataClient.fetch_snapshot()` already acquires `ibkr_shared_lock` internally (line 595). No additional locking needed in `portfolio_greeks.py`.
- **Import guard**: `ib_async` and `ibkr.market_data` are imported inside `_fetch_ibkr_greeks()` to avoid hard dependency. If IBKR package isn't installed, returns `None` gracefully.
- **No changes to flags or downstream consumers**: The `source` field already exists on `PortfolioGreeksSummary` and flows through `to_dict()` → `get_exposure_snapshot()` → agent response. Flags already work on dollar Greeks regardless of source.

## Verification

1. `pytest tests/options/test_portfolio_greeks.py -v` — all tests pass (existing + new)
2. Live test (market hours): `/mcp` reconnect portfolio-mcp, call `get_positions` with options in portfolio → `portfolio_greeks.source` should be `"ibkr"`
3. Live test (market closed): Same call → `source` should be `"computed"` (Black-Scholes fallback)

# Concentration: Fund/ETF Exemption in Core Code Paths

**Date**: 2026-02-28
**Status**: Planning (R1 reviewed, fixes applied)
**Risk**: Low — additive logic with graceful fallbacks; existing behavior preserved when type data is missing

## Context

Position flags (`core/position_flags.py`) fire `single_position_concentration` at 15% for ALL non-cash positions, including funds and ETFs. A 20% SPY allocation triggers the same warning as 20% of a single stock — misleading. The risk score layer (`portfolio_risk_score.py`) already correctly exempts funds via `DIVERSIFIED_SECURITY_TYPES`, but three other concentration checkpoints don't.

**Goal**: Make all concentration checks fund-aware, using the existing `DIVERSIFIED_SECURITY_TYPES` set from `portfolio_risk_engine/constants.py` as the single source of truth.

## Codex R1 Findings (addressed below)

| # | Severity | Finding | Fix |
|---|----------|---------|-----|
| 1 | HIGH | New ETF buys not in existing positions → `ticker_type=None` → still blocked | Use `SecurityTypeService` as fallback when ticker not in current positions |
| 2 | HIGH | Second caller of `_compute_weight_impact()` at line 371 (preview flow) not identified | Update both call sites (371 and 1116) + preview concentration warning at line 393 |
| 3 | HIGH | Position `type` field unreliable: Schwab maps `MUTUAL_FUND→equity`, Plaid has raw `"mutual fund"` not `"mutual_fund"` | Use `SecurityTypeService.get_security_types()` (canonical FMP-based) instead of raw position `type`. **R2 addendum**: Also in `_compute_weight_impact()` — always use SecurityTypeService, don't try raw position `type` first (it's wrong for Schwab funds) |
| 4 | MEDIUM | What-if/optimizer also call `build_portfolio_view()` without `security_types` | Thread `security_types` through those paths too (or note as follow-up) |
| 5 | MEDIUM | Local duplicate constants violate "single source of truth" goal | Import from `portfolio_risk_engine.constants` everywhere |
| 6 | LOW | All-diversified portfolio → HHI=0.0 may understate concentration | Document: intentional — all-fund portfolio has no single-issuer concentration |

## Locations to Fix

| # | File | Check | Currently Fund-Aware? |
|---|------|-------|-----------------------|
| 1 | `core/position_flags.py:53-86` | `single_position_concentration` (15%) + `top5_concentration` (60%) | No |
| 2 | `services/trade_execution_service.py:1125-1134` + `:393` | Post-trade weight hard limit + 10% warning (execute flow + preview flow) | No |
| 3 | `portfolio_risk_engine/portfolio_risk.py:1501` | HHI via `compute_herfindahl(weights)` | No |
| 4 | `portfolio_risk_engine/portfolio_risk_score.py:1808` | `build_portfolio_view()` call — `security_types` in scope but not passed | No (for HHI) |
| 5 | `portfolio_risk_engine/portfolio_risk_score.py:234` | `_get_single_issuer_weights()` | Yes (template) |

## Implementation

### 1. Position Flags: `core/position_flags.py` (MODIFY)

**Problem**: Raw position `type` field is unreliable across providers (Schwab maps `MUTUAL_FUND→equity`, Plaid uses `"mutual fund"` with space). Cannot use it directly.

**Solution**: Accept a `security_types: Optional[Dict[str, str]]` parameter in `generate_position_flags()`. This dict comes from `SecurityTypeService.get_security_types()` which returns canonical types (`"etf"`, `"fund"`, `"equity"`). The caller (`mcp_tools/positions.py:281`) will fetch and pass it.

**Modify `generate_position_flags()` signature** (line 20):
```python
def generate_position_flags(
    positions, total_value, cache_info,
    by_sector=None, monitor_positions=None,
    security_types=None,  # NEW: Dict[ticker, canonical_type] from SecurityTypeService
):
```

**Import at top of file**:
```python
from portfolio_risk_engine.constants import DIVERSIFIED_SECURITY_TYPES
```

**Modify the concentration block** (lines 53-86):

Use `security_types` dict to classify. Helper:
```python
def _is_diversified(position, security_types):
    """Check if position is a diversified vehicle (ETF/fund/mutual_fund)."""
    ticker = str(position.get("ticker") or "").upper()
    if security_types and ticker in security_types:
        return (security_types[ticker] or "").lower() in DIVERSIFIED_SECURITY_TYPES
    # Fallback to raw position type (best-effort when SecurityTypeService unavailable)
    # Include "mutual fund" (Plaid raw value with space) in addition to canonical set
    raw_type = str(position.get("type", "")).lower()
    return raw_type in DIVERSIFIED_SECURITY_TYPES or raw_type == "mutual fund"
```

Split `non_cash` into two lists:
```python
single_issuer = [p for p in non_cash if not _is_diversified(p, security_types)]
diversified = [p for p in non_cash if _is_diversified(p, security_types)]
```

**`single_position_concentration`** (line 57-69): Only check `single_issuer` positions against the 15% threshold. Keep `gross_non_cash` as the denominator (total non-cash exposure) so weights are portfolio-relative, not just single-issuer-relative.

**`top5_concentration`** (line 71-86): Only count `single_issuer` positions in the top-5. Same `gross_non_cash` denominator.

**Add a new flag** for large diversified positions (optional but informative):
- `large_fund_position` (severity: `info`): fires when a single fund/ETF is >30% of exposure. Higher threshold since funds are inherently diversified, but a massive single-fund bet is still worth noting.

### 1b. Caller: `mcp_tools/positions.py` (MODIFY)

**Modify `_build_agent_response()`** (around line 281): Fetch security types and pass to `generate_position_flags()`.

```python
# Fetch canonical security types for concentration exemption
tickers = [str(p.get("ticker") or "").upper() for p in result.data.positions if p.get("ticker")]
tickers = [t for t in tickers if t]  # filter empty
try:
    from services.security_type_service import SecurityTypeService
    security_types = SecurityTypeService.get_security_types(tickers)
except Exception:
    import logging
    logging.getLogger(__name__).warning("SecurityTypeService unavailable for position flags; treating all as single-issuer")
    security_types = None  # graceful fallback — treat all as single-issuer

flags = generate_position_flags(
    result.data.positions,
    result.total_value,
    cache_info,
    by_sector=by_sector,
    monitor_positions=monitor_positions,
    security_types=security_types,
)
```

### 2. Trade Execution: `services/trade_execution_service.py` (MODIFY)

**Problem**: (a) Two callers of `_compute_weight_impact()` — line 371 (preview) and line 1116 (execute). Both must handle 3 return values. (b) New ETF buys not in existing positions → ticker_type=None → still blocked. (c) Preview flow has its own concentration warning at line 393 that also needs fund-awareness.

**`_compute_weight_impact()`** (line 1652): Return `ticker_type` as third value. Always use `SecurityTypeService` for canonical type — do NOT use raw position `type` field (it's unreliable: Schwab maps `MUTUAL_FUND→equity`):

```python
def _compute_weight_impact(self, ticker, side, quantity, estimated_price):
    ...
    # Use SecurityTypeService for canonical type (raw position type is unreliable)
    ticker_type = None
    try:
        from services.security_type_service import SecurityTypeService
        types = SecurityTypeService.get_security_types([ticker])
        ticker_type = (types.get(ticker) or "").lower()
        if not ticker_type:
            import logging
            logging.getLogger(__name__).warning(
                "SecurityTypeService returned no type for %s; treating as single-issuer", ticker
            )
    except Exception:
        import logging
        logging.getLogger(__name__).warning(
            "SecurityTypeService unavailable for %s; treating as single-issuer", ticker
        )

    return pre_weight, post_weight, ticker_type
```

**Import at top of file**:
```python
from portfolio_risk_engine.constants import DIVERSIFIED_SECURITY_TYPES
```

**Update call site at line 1116** (execute flow):
```python
pre_weight, post_weight, ticker_type = self._compute_weight_impact(
    ticker=ticker,
    side=side,
    quantity=quantity_num or 0.0,
    estimated_price=(estimated_cost / quantity_num) if estimated_cost and quantity_num else None,
)
ctx["pre_trade_weight"] = pre_weight
ctx["post_trade_weight"] = post_weight

is_diversified = ticker_type in DIVERSIFIED_SECURITY_TYPES
max_weight = self._get_max_single_stock_weight_limit()

if not is_diversified and post_weight is not None and post_weight > max_weight:
    errors.append(
        f"Post-trade single-stock weight {post_weight:.2%} exceeds max {max_weight:.2%}"
    )

if not is_diversified and post_weight is not None and post_weight > 0.10:
    warnings.append(
        f"Post-trade concentration warning: {ticker} weight would be {post_weight:.2%}"
    )
```

**Update call site at line 371** (preview flow):
```python
pre_weight, post_weight, ticker_type = self._compute_weight_impact(
    ticker=ticker,
    side=side,
    quantity=quantity,
    estimated_price=estimated_price,
)

# ... existing order value / buying power checks ...

if validation.post_trade_weight is None:
    validation.post_trade_weight = post_weight

is_diversified = ticker_type in DIVERSIFIED_SECURITY_TYPES
if not is_diversified and post_weight is not None and post_weight > 0.10:
    warning = f"Post-trade concentration warning: {ticker.upper()} weight would be {post_weight:.2%}"
    if warning not in validation.warnings:
        validation.warnings.append(warning)
```

### 3. HHI Computation: `portfolio_risk_engine/portfolio_risk.py` (MODIFY)

**`compute_herfindahl()`** (line 172): Add optional `security_types` parameter. If provided, filter weights to single-issuer only before computing HHI. Graceful fallback: if `security_types` is None, compute on all weights (current behavior).

```python
def compute_herfindahl(
    weights: Dict[str, float],
    security_types: Optional[Dict[str, str]] = None,
) -> float:
    if security_types:
        from portfolio_risk_engine.constants import DIVERSIFIED_SECURITY_TYPES
        weights = {
            t: w for t, w in weights.items()
            if security_types.get(t) not in DIVERSIFIED_SECURITY_TYPES
        }
    if not weights:
        return 0.0
    # Use normalize_weights() for gross-exposure normalization (preserves long/short semantics)
    w = normalize_weights(weights)
    return float(sum(w_i ** 2 for w_i in w.values()))
```

**Important**: Must use `normalize_weights()` (which normalizes by `sum(abs(w))` — gross exposure) not `sum(weights.values())`. Net-sum normalization would understate concentration for hedged portfolios. This preserves the existing normalization semantics.

**Note on all-diversified portfolios**: If every position is a fund/ETF, filtered weights will be empty → HHI=0.0. This is intentional — an all-fund portfolio has no single-issuer concentration. The `large_fund_position` flag (Section 1) separately flags oversized fund positions.

### 4. Thread `security_types` into `build_portfolio_view()` HHI call

`build_portfolio_view()` (in `portfolio_risk_engine/portfolio_risk.py:1392`) does NOT currently accept `security_types`. It's called from `core/portfolio_analysis.py:131` which has `security_types` in scope (line 63) but doesn't pass it.

The function uses `serialize_for_cache()` + `@lru_cache` for caching (line 1425-1441). Adding `security_types` follows the same pattern as existing dict params (`instrument_types`, `currency_map`, etc.):

**Modify `build_portfolio_view()` signature** (line 1392): Add `security_types: Optional[Dict[str, str]] = None`.

**Add cache serialization** (after line 1431):
```python
security_types_json = serialize_for_cache(security_types)
```

**Pass to `_cached_build_portfolio_view()`** (line 1438-1441): Add `security_types_json` as argument.

**Thread through `_cached_build_portfolio_view()` → `_build_portfolio_view_computation()`**: Same pattern as other dict params — deserialize back to dict, pass to computation.

**Modify `_build_portfolio_view_computation()`** (line 1444): Add `security_types` param.

**Modify HHI call** (line 1501):
```python
hhi = compute_herfindahl(weights, security_types=security_types)
```

**Modify caller** in `core/portfolio_analysis.py:131`: Pass `security_types` through:
```python
summary = build_portfolio_view(
    weights, config["start_date"], config["end_date"],
    ...,
    security_types=security_types,
)
```

**Modify caller** in `portfolio_risk_engine/portfolio_risk_score.py:1808`: `security_types` is already resolved at line 1798-1805 but NOT passed to `build_portfolio_view()`. Add it:
```python
summary = build_portfolio_view(
    weights=weights,
    start_date=config["start_date"],
    end_date=config["end_date"],
    ...,
    instrument_types=instrument_types,
    security_types=security_types,  # NEW — already in scope from line 1798
)
```

### 5. What-if / Optimizer paths (FOLLOW-UP)

Other callers of `build_portfolio_view()` that don't pass `security_types`:
- `portfolio_risk_engine/scenario_analysis.py:154` (what-if)
- `portfolio_risk_engine/portfolio_optimizer.py:129, 233, 526, 814, 830, 1155, 1328` (optimizer — many call sites)

These work on hypothetical portfolio weights, not current positions. They'll continue to use the default `security_types=None` behavior (current behavior, no exemption). This is acceptable for now — the optimizer typically works with equity tickers. If needed, `security_types` can be threaded through these paths as a follow-up.

## Key Implementation Notes

- **Use `SecurityTypeService.get_security_types()` (canonical FMP-based types)** in position flags and trade execution. Raw position `type` is unreliable: Schwab maps `MUTUAL_FUND→equity` (`schwab_positions.py:22`), Plaid preserves raw values like `"mutual fund"` (not `mutual_fund`). `SecurityTypeService` returns canonical types (`"etf"`, `"fund"`, `"equity"`).
- **Graceful fallback everywhere**: If `SecurityTypeService` is unavailable, fall back to raw position `type` field (position flags) or treat as single-issuer (trade execution). All changes are backward-compatible.
- **Import `DIVERSIFIED_SECURITY_TYPES` from `portfolio_risk_engine.constants`** everywhere — single source of truth. No local duplicated constants. Note: `trade_execution_service.py` does not currently import from `portfolio_risk_engine`, so this adds a new cross-package dependency. Acceptable since `constants.py` is a lightweight module with no side effects.
- **Same denominator**: Position flag weights should still be relative to total non-cash exposure (not just single-issuer total). A stock at 15% of the whole portfolio is concentrated regardless of how many ETFs are in the mix.
- **`_compute_weight_impact()` return change**: Adding a third return value (`ticker_type`) changes the return signature. **Both callers** must be updated: line 371 (preview flow) and line 1116 (execute flow). The preview flow also has its own concentration warning at line 393 that needs fund-awareness.
- **Use `security_types` dict** in HHI computation (same pattern as `portfolio_risk_score.py`). This data is already available in the analysis pipeline via `core/portfolio_analysis.py:63`.

## Reuse from existing code

- `portfolio_risk_engine/constants.py:76` — `DIVERSIFIED_SECURITY_TYPES = {'etf', 'fund', 'mutual_fund'}` (canonical set)
- `services/security_type_service.py` — `SecurityTypeService.get_security_types(tickers)` → canonical type dict
- `portfolio_risk_engine/portfolio_risk_score.py:234` — `_get_single_issuer_weights()` (template pattern for filtering)
- `portfolio_risk_engine/portfolio_risk.py:172` — `compute_herfindahl()` (function to modify)
- `portfolio_risk_engine/portfolio_risk.py:1392` — `build_portfolio_view()` (caching pattern to follow)
- `portfolio_risk_engine/portfolio_risk.py:1425` — `serialize_for_cache()` (dict → JSON for LRU key)

## Verification

1. `python3 -c "from core.position_flags import generate_position_flags"` — imports cleanly
2. `python3 -c "from services.trade_execution_service import TradeExecutionService"` — imports cleanly
3. `python3 -c "from portfolio_risk_engine.portfolio_risk import compute_herfindahl"` — imports cleanly
4. **Position flags**: Call `get_positions(format="agent")` — verify ETF positions (like SLV) don't trigger `single_position_concentration` even if >15%
5. **Trade execution**: Preview a buy of an ETF (e.g., SPY) that would result in >max weight — should NOT be blocked
6. **HHI**: Check `get_risk_analysis(format="agent")` — HHI should reflect only single-issuer concentration
7. **Regression**: Individual stocks above 15% should still trigger `single_position_concentration`

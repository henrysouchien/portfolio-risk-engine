# Sizing Grade — Include Futures via Margin-Adjusted Size

## Context

Sizing grade is N/A because futures are excluded (notional cost_basis dwarfs equity cost_basis, corrupting rank correlation). But futures have `margin_rate` in contract specs — actual capital at risk. Using margin-adjusted size makes futures comparable to equities.

Current data:
- MGC cost_basis: $31,513 (notional) → margin at 5% = $1,576 (capital at risk)
- GLBE cost_basis: $329 (capital deployed)
- Without adjustment: MGC ranks as 100x larger than GLBE. With margin: ~5x larger. Comparable.

With futures included: 16 eligible round-trips (above 15 threshold). Sizing grade becomes available.

## Plan

### Modify `compute_sizing_grade()` in `trading_analysis/analyzer.py`

Remove the futures/fx/fx_artifact/income exclusion. Instead, compute a normalized size for each round-trip:

```python
from brokerage.futures import get_contract_spec

def _get_sizing_capital(rt: RoundTrip) -> float | None:
    """Return capital-at-risk for sizing correlation.

    Equities/options/bonds: cost_basis (capital deployed)
    Futures: cost_basis × margin_rate (margin posted)
    fx/fx_artifact/income: excluded (return None)
    """
    itype = (rt.instrument_type or "").strip().lower()
    if itype in ("fx", "fx_artifact", "income"):
        return None
    if itype == "futures":
        spec = get_contract_spec(rt.symbol)
        if not spec:
            return None  # unknown futures contract — exclude rather than guess
        return abs(rt.cost_basis) * spec.margin_rate
    return abs(rt.cost_basis)
```

Then in `compute_sizing_grade()`:

```python
# Before:
excluded_types = ("futures", "fx", "fx_artifact", "income")
eligible = [rt for rt in round_trips if not rt.synthetic and rt.instrument_type not in excluded_types]
sizes = [abs(rt.cost_basis) for rt in eligible]
returns = [rt.pnl_percent for rt in eligible]

# After:
eligible = []
sizes = []
returns = []
for rt in [r for r in round_trips if not r.synthetic]:
    capital = _get_sizing_capital(rt)
    ret = _get_sizing_return(rt)
    if capital is not None and ret is not None:
        eligible.append(rt)
        sizes.append(capital)
        returns.append(ret)

# ... rest of Spearman correlation unchanged (operates on sizes vs returns)
```

### What changes
- Futures included with margin-adjusted size AND margin-based return
- Futures without contract spec → excluded (no guessing margin_rate)
- fx/fx_artifact/income still excluded
- Equities/options/bonds unchanged (cost_basis for size, pnl_percent for return)

### Denominator design — consistent capital basis

Both size and return use capital-at-risk as the basis:

**Equities/options/bonds:** cost_basis IS capital deployed.
- Size = `abs(cost_basis)`
- Return = `pnl_percent` (already pnl / cost_basis)

**Futures:** cost_basis is notional, not capital at risk.
- Size = `abs(cost_basis) × margin_rate` (margin posted)
- Return = `pnl_dollars / (abs(cost_basis) × margin_rate) × 100` (return on margin)

This gives consistent sizing correlation — both axes measure the same thing: capital committed vs return on that capital.

Example: MGC with cost_basis=$31,513 and margin_rate=0.05:
- Size = $31,513 × 0.05 = $1,576 (margin)
- Return = -$1,102 / $1,576 × 100 = -69.9% (return on margin, not -3.5% notional)

**Implementation:** Compute margin-adjusted return for futures ONLY within `compute_sizing_grade()`. The round-trip's `pnl_percent` field stays notional-based (used by Edge grade). Sizing derives its own return:

```python
def _get_sizing_return(rt: RoundTrip) -> float | None:
    """Return percentage for sizing correlation.

    Equities/options/bonds: pnl_percent (already capital-based)
    Futures: pnl / margin (return on capital at risk)
    """
    itype = (rt.instrument_type or "").strip().lower()
    if itype == "futures":
        spec = get_contract_spec(rt.symbol)
        if not spec:
            return None
        margin = abs(rt.cost_basis) * spec.margin_rate
        if margin < 1e-10:
            return None
        return (rt.pnl_dollars / margin) * 100
    return rt.pnl_percent
```

### Currency — USD normalization

Apply FX conversion to sizing capital so cross-currency ranks are correct. The FX rate dict is already built in the analyzer (used for `pnl_dollars_usd`). Pass it to `_get_sizing_capital()`:

```python
def _get_sizing_capital(rt: RoundTrip, fx_rates: dict[str, float]) -> float | None:
    ...
    rate = fx_rates.get((rt.currency or "USD").upper(), 1.0)
    if itype == "futures":
        return abs(rt.cost_basis) * spec.margin_rate * rate
    return abs(rt.cost_basis) * rate
```

For returns: `_get_sizing_return()` uses `pnl_dollars` (local currency) divided by margin (local currency) — the ratio is currency-neutral, so no FX needed for returns.

### What doesn't change
- Round-trip `pnl_percent` field — unchanged (still notional for futures, used by Edge grade)
- Spearman correlation logic — unchanged (just different inputs)
- Grade thresholds — unchanged
- Minimum 15 round-trips + 4 distinct sizes — unchanged

## Files Changed

| File | Change |
|------|--------|
| `trading_analysis/analyzer.py` | `_get_sizing_capital()` + `_get_sizing_return()` helpers. Update `compute_sizing_grade()` to accept `fx_rates` param. Store `fx_rates` on `self._fx_rates` in `_analyze_trades_fifo()` / `_analyze_trades_averaged()` (where `_build_fx_rates()` is called). Initialize `self._fx_rates = {}` in `__init__()`, reset in `run_full_analysis()`. Pass `self._fx_rates` into `compute_sizing_grade()`. |

## Tests

**File:** `tests/trading_analysis/test_scorecard_v2.py`

- Futures round-trip with margin_rate: size = cost_basis × margin_rate, return = pnl / margin
- Futures with no contract spec: excluded from both size and return (returns None)
- Mixed equity + futures: both included in correlation, futures use margin size
- fx/fx_artifact/income still excluded
- Remove old "futures excluded from sizing" test
- Edge grade still uses rt.pnl_percent (notional) — not affected by sizing margin return
- USD-normalized sizing: HKD futures ranked correctly vs USD equities

## Verification

1. `pytest tests/trading_analysis/ -v` — all tests pass
2. MCP: sizing grade no longer N/A (16 eligible round-trips)
3. Live: futures don't dominate equity sizing ranks

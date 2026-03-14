# Fix: Enable per-symbol inception for all sources (not Schwab-only)

**Status**: REVERTED (attempted 2026-03-02, revert `d9a9f886`). IBKR went from -32.53% to +3,934%. Per-symbol inception causes synthetics to appear one-by-one throughout March, each creating individual daily NAV spikes in TWR — worse than a single inception-day batch. See `docs/planning/performance-actual-2025/RETURN_PROGRESSION_BY_FIX.md`.

## Context

IBKR realized performance shows -32.53% vs broker actual -9.35%. Investigation traced the distortion to **19 first-transaction-exit synthetic positions** being backdated to global inception (Feb 28, 2025) instead of each symbol's earliest transaction date. This creates:

- **March 2025: +490%** — synthetic positions inflate NAV from inception, but their cash events are excluded from TWR flows. On inception day: `day_nav / net_flow` = `$129K / small_flow` = massive return.
- **April 2025: -64%** — synthetic positions unwind (SELLs), NAV drops massively with small denominator.
- **May 2025: -75%** — more unwinding continues the cascade.

These extreme months dominate the chain-linked total return.

**Root cause**: `use_per_symbol_inception` is only enabled for Schwab (line 6406-6408):
```python
use_per_symbol_inception = bool(
    institution and match_institution(institution, "schwab")
)
```

With `per_symbol_inception=False` (IBKR), all 19 synthetic entries are placed at global inception (Feb 28). With `per_symbol_inception=True`, they're placed at each symbol's earliest transaction date — so a CBL synthetic BUY goes just before the April 8 SELL, not 5 weeks earlier at inception.

The Schwab-only restriction was a legacy decision from the Modified Dietz era. With TWR (now used in production), per-symbol inception is strictly better for all sources: it eliminates the NAV spike from synthetics appearing weeks/months before their first real transaction.

**Prior fixes already committed:**
- `fe297eda`: StmtFunds topic name fix
- `264c2940`: Ghost account filtering in `_discover_account_ids()`

## Files to Modify

| File | Change |
|------|--------|
| `core/realized_performance_analysis.py:3094` | Default `use_per_symbol_inception: bool = True` (covers all 6 call sites) |
| `core/realized_performance_analysis.py:6406-6408` | `use_per_symbol_inception = True` (explicit at main entry) |
| `core/realized_performance_analysis.py:6319` | `use_per_symbol_inception=True` (aggregation loop) |
| `core/realized_performance_analysis.py:1174,1320` | Update stale Schwab-only comments |
| `tests/core/test_realized_performance_analysis.py:6091-6138` | Update test to expect True for all sources |

## Implementation

### 1. Change default on `_analyze_realized_performance_single_scope` (`core/realized_performance_analysis.py:3094`)

```python
# Before:
use_per_symbol_inception: bool = False,

# After:
use_per_symbol_inception: bool = True,
```

This covers ALL 6 call sites at once (lines 6279, 6293, 6319, 6347, 6421, 6448) including the aggregation fallback paths that don't pass the flag explicitly.

### 2. Remove Schwab-only gate (`core/realized_performance_analysis.py:6406-6408`)

```python
# Before:
use_per_symbol_inception = bool(
    institution and match_institution(institution, "schwab")
)

# After (delete or simplify — default is now True, no need to compute):
use_per_symbol_inception = True
```

### 3. Remove Schwab-only gate in aggregation loop (`core/realized_performance_analysis.py:6319`)

```python
# Before:
use_per_symbol_inception=bool(match_institution(institution, "schwab")),

# After:
use_per_symbol_inception=True,
```

### 4. Update stale comments (`core/realized_performance_analysis.py:1174, 1320-1321`)

- Line 1174: Remove "This prevents backdating positions to months before they were actually held" Schwab-specific framing
- Lines 1320-1321: Remove "Without per-symbol inception (e.g. IBKR Flex with limited history), always use global inception."

### 5. Update test (`tests/core/test_realized_performance_analysis.py:6091-6138`)

Rename `test_single_scope_enables_per_symbol_inception_for_schwab_only` → `test_single_scope_enables_per_symbol_inception_for_all_sources`.

Update docstring and assertions:
- Line 6092 docstring: "use_per_symbol_inception is True for all sources"
- Line 6137: `assert no_institution["use_per_symbol_inception"] is True` (was `False`)
- Line 6138: `assert single_calls == [True, True, True]` (was `[True, True, False]`)

## Verification

1. `python3 -m pytest tests/core/test_realized_performance_analysis.py::test_single_scope_enables_per_symbol_inception_for_all_sources -v`
2. `python3 -m pytest tests/core/test_realized_performance_analysis.py -v --tb=short` (full suite regression check)
3. Live test after `/mcp` reconnect: `get_performance(mode="realized", source="ibkr_flex", use_cache=false)`
4. Confirm:
   - March extreme month reduced (from +490%)
   - April/May extreme months reduced (from -64%/-75%)
   - Total return closer to broker actual (-9.35%)
5. Schwab regression check: `get_performance(mode="realized", source="schwab", use_cache=false)` — should be unchanged since Schwab already had `per_symbol_inception=True`

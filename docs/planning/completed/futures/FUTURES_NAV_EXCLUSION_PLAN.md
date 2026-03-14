# Fix: Exclude Futures Notional from Position NAV in `compute_monthly_nav()`

## Context

IBKR realized performance shows -77.82% vs broker +0.29% TWR. Root cause: `compute_monthly_nav()` values futures at full notional (qty × price × fx). ZF (5-Year Treasury futures) has qty=1000 (1 contract × 1000 multiplier) valued at ~$108K. MHI adds ~$30K. This inflates March 31 NAV from ~$35K to $143,984 (broker actual: $22,284).

Daily NAV trace proves it: Mar 20 = $37,449 → Mar 21 = $144,215 (ZF bought). Apr 9 = $23,083 (ZF sold). Apr 14 = $56,097 (MGC bought). Each futures buy/sell creates massive NAV jumps that TWR interprets as returns.

**Why exclusion, not margin-based valuation:** IBKR broker statements value futures purely through daily cash settlements (FUTURES_MTM), not as position values. The cash replay (`derive_cash_and_external_flows()`) already CORRECTLY handles futures:
- Line 1817-1822: Futures BUY/SELL → notional suppressed, only fees hit cash
- FUTURES_MTM events (101 rows in store): Daily mark-to-market settlements flow into cash
- Margin collateral is already part of the cash balance

Adding a separate margin-based position value would **double-count** — the margin is already in the cash component. Exclusion from position NAV matches broker accounting exactly.

## Changes

### 1. Add `futures_keys` parameter to `compute_monthly_nav()` (~line 1988)

**File:** `core/realized_performance_analysis.py`

Use **key-level** (not ticker-level) exclusion to handle the edge case where a ticker appears as both futures and equity (e.g., Z = Zillow equity AND FTSE futures root). `instrument_meta` is keyed by `(ticker, currency, direction)` — same as `position_timeline`.

Add an optional `futures_keys: Optional[Set[Tuple[str, str, str]]] = None` parameter:

```python
def compute_monthly_nav(
    position_timeline: Dict[Tuple[str, str, str], List[Tuple[datetime, float]]],
    month_ends: List[datetime],
    price_cache: Dict[str, pd.Series],
    fx_cache: Dict[str, pd.Series],
    cash_snapshots: List[Tuple[datetime, float]],
    futures_keys: Optional[Set[Tuple[str, str, str]]] = None,
) -> pd.Series:
    """Compute month-end NAV = valued positions + derived cash.

    Futures positions are excluded from position valuation because their P&L
    is already captured in cash via FUTURES_MTM daily settlement events.
    Including notional value would double-count and massively inflate NAV.
    """
```

At line 2041, after the existing pointer advancement + quantity tracking + zero-qty check, skip valuation for futures keys:

```python
            ticker, currency, direction = key
            if futures_keys and key in futures_keys:
                continue

            price = _value_at_or_before(...)
```

Place the check AFTER pointer/quantity tracking (lines 2031-2039 are unchanged) so state stays correct. We just skip the price lookup and valuation for futures keys.

**Edge case — same (ticker, currency, direction) tuple as both futures and equity:** `instrument_meta` keeps whichever type was registered first on conflict via `_register_instrument_meta` (line 1268), which emits an explicit conflict warning (line 1270). In practice, futures and equities with the same root ticker (e.g., Z) will have different currency or direction values, producing distinct keys. No special handling needed beyond key-level filtering.

### 2. Build `futures_keys` set from `instrument_meta` (~line 3700)

After the existing `ticker_instrument_types` loop (lines 3669-3700), build the key-level set directly from `instrument_meta`:

```python
        futures_keys: set[tuple[str, str, str]] = {
            key for key, meta in instrument_meta.items()
            if coerce_instrument_type(meta.get("instrument_type")) == "futures"
        }
```

`instrument_meta` is returned by `build_position_timeline()` at line 3656 and keyed by the same `(ticker, currency, direction)` tuple as `position_timeline`. No new data plumbing needed.

### 3. Guard: only exclude when MTM data is available

If FUTURES_MTM events are absent (e.g., StmtFunds section missing from Flex report), excluding futures from NAV would lose all P&L signal. The code already warns about this at line 3400. Add a guard:

```python
        # Only exclude futures from NAV when MTM data is available to carry P&L via cash.
        # If MTM is absent, keep notional valuation as a (distorted) fallback.
        if not futures_mtm_events:
            futures_keys = set()
```

This ensures futures are only excluded when we have the MTM cash settlements to replace position valuation. When MTM is missing, we keep the (imperfect) notional valuation — same as current behavior — and rely on the existing warning at line 3400.

**Edge case — non-empty but ineffective MTM list:** `load_futures_mtm()` (transaction_store.py:1487) passes raw payload through without validating amounts/dates. Cash replay filters MTM rows with invalid dates or zero amounts (realized_performance_analysis.py:1764-1769). So a non-empty but all-invalid MTM list could trigger exclusion while providing no cash P&L. Mitigation: additionally check that at least one MTM event has a non-zero amount after the initial `if not futures_mtm_events` guard:

```python
        def _has_usable_mtm(events: list) -> bool:
            for e in events:
                d = _to_datetime(e.get("date"))
                if d is None:
                    continue
                if abs(_as_float(e.get("amount"), 0.0)) > 0:
                    return True
            return False

        if not futures_mtm_events or not _has_usable_mtm(futures_mtm_events):
            futures_keys = set()
```

This mirrors the same filtering cash replay applies (line 1765: `_to_datetime` date check, line 1768: `amount` read), so exclusion only triggers when at least one MTM event will actually produce a cash impact.

### 4. Pass `futures_keys` to all 4 `compute_monthly_nav()` call sites

Lines 4579, 4588, 4626, 4635 — add `futures_keys=futures_keys` to each call.

### 5. Tests

**File:** `tests/core/test_realized_performance_analysis.py` (add to existing)

1. Test `compute_monthly_nav()` with `futures_keys` — verify futures positions excluded from position value but cash component preserved
2. Test with `futures_keys=None` (backwards compat) — behaves identically to current behavior
3. Test that pointer/quantity tracking still advances for excluded futures keys (so subsequent non-futures keys aren't affected)
4. Test mixed-type scenario: same ticker appears as futures key AND equity key — only futures key excluded
5. Test MTM guard fallback: when `futures_mtm_events` is empty or all-invalid, `futures_keys` is cleared and futures positions are valued at notional (current behavior preserved)

## Files to Modify

| File | Change |
|------|--------|
| `core/realized_performance_analysis.py` | Add `futures_keys` param to `compute_monthly_nav()`, build set from `instrument_meta`, MTM guard, pass to all 4 call sites |
| `tests/core/test_realized_performance_analysis.py` | Add futures exclusion unit tests |

## What NOT to Change

- No changes to `derive_cash_and_external_flows()` — already handles futures correctly
- No changes to `build_position_timeline()` — futures positions stay in timeline for FIFO tracking
- No changes to price fetching — futures prices still fetched (used by other components)
- No margin-based valuation — broker doesn't value futures as positions; P&L is in cash via MTM

## Verification

1. **Run existing tests:** `python3 -m pytest tests/core/test_realized_performance_analysis.py tests/core/test_synthetic_twr_flows.py -x -q`
2. **Live verification — IBKR source:**
   ```
   get_performance(mode='realized', source='ibkr_flex', format='summary')
   ```
   - Before: -77.82%. After: should be much closer to broker's +0.29%
   - ZF/MHI/MGC should no longer inflate position NAV
3. **Regression check — other sources unaffected:**
   - Schwab: should remain near current value
   - Plaid: should remain near -11.77%
4. **Sanity check NAV**: March 31 NAV should be ~$22K (not $143K)
